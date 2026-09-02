"""Compose the song, then close the loop acoustically on the name.

This is the module the product exists for. No music model accepts IPA, SSML or a lexicon,
so pronunciation control is assembled rather than requested: render the name in its own
chunk, listen to what actually came out with STT, compare it to the intended name, and if
it is wrong re-render *that chunk only* with the next candidate orthography — silently,
before the customer hears anything.

Two properties matter more than accuracy:

* It is bounded. ``name_verification_max_attempts`` renders, at most, and never more than
  the candidate list holds.
* It degrades to delivery, never to failure. If STT is down, if every orthography misses,
  if an inpaint errors after a good take exists — the best attempt ships and the miss is
  recorded as a verdict. A silent kit is worth nothing; a slightly-off name is worth most
  of the price.
"""

from __future__ import annotations

import asyncio
import re
from typing import Final
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from hbd.config import Settings
from hbd.contracts import (
    Brief,
    CompositionPlan,
    Err,
    MusicProvider,
    NameCandidate,
    NameVerdict,
    RenderedAudio,
    Result,
    SttProvider,
    Transcript,
    ok,
)
from hbd.logging import get_logger
from hbd.pipeline.events import PipelineStage, ProgressReporter, ProgressStatus
from hbd.pipeline.idempotency import idempotency_key
from hbd.pipeline.plan_builder import with_name_candidate
from hbd.pipeline.ports import Clock, NameSimilarity, Sleeper
from hbd.pipeline.retry import RetryPolicy, call_with_retry

__all__ = [
    "SongRender",
    "render_song",
    "best_similarity",
    "MAX_NAME_TOKEN_WINDOW",
    "VERIFICATION_EVENT",
]

_LOGGER = get_logger(__name__)

#: Grep-able event name. One line per completed verification loop, whatever the outcome.
#: This is where the re-roll rate is read from: nothing else aggregates ``verdicts``.
VERIFICATION_EVENT: Final[str] = "name.verification"

#: A name may be transcribed as up to three tokens ("Gu lom jon"), so windows of one to
#: three consecutive tokens are scored. Beyond that the window is longer than any name.
MAX_NAME_TOKEN_WINDOW: Final[int] = 3

#: Word separators across all four locales, plus the punctuation STT tends to insert.
_SEPARATORS: Final[str] = '\\s,.!?;:()\\[\\]{}"\u00ab\u00bb\u2014\u2013\\-/'
_TOKEN_SPLIT: Final[re.Pattern[str]] = re.compile(f"[{_SEPARATORS}]+")


class SongRender(BaseModel):
    """The take we are shipping, plus the paper trail of how we got here."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    audio: RenderedAudio
    plan: CompositionPlan
    candidate: NameCandidate
    verdicts: tuple[NameVerdict, ...] = ()
    is_verified: bool = False
    was_checked: bool = False
    renders: int = Field(default=1, ge=1)
    cost_usd: float = Field(default=0.0, ge=0.0)


class _Take(BaseModel):
    """One rendered attempt, kept so the closest miss can still be shipped."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    candidate: NameCandidate
    audio: RenderedAudio
    plan: CompositionPlan
    score: float = 0.0


def _tokens(text: str) -> tuple[str, ...]:
    return tuple(token for token in _TOKEN_SPLIT.split(text) if token)


def best_similarity(transcript: str, expected: str, similarity: NameSimilarity) -> float:
    """Highest score any short window of the transcript scores against ``expected``.

    STT returns the whole song, not the isolated chunk, so the name has to be *found*
    before it can be judged. Scoring windows rather than the full string keeps a correct
    name from being diluted by the ninety other words around it.
    """
    tokens = _tokens(transcript)
    if not tokens:
        return 0.0
    best = 0.0
    for width in range(1, min(MAX_NAME_TOKEN_WINDOW, len(tokens)) + 1):
        for start in range(len(tokens) - width + 1):
            window = " ".join(tokens[start : start + width])
            best = max(best, similarity(window, expected))
    return best


class _NameLoop:
    """Owns the render/listen/re-roll cycle for exactly one order.

    Instance attributes are this loop's own accumulators. Nothing passed in is mutated.
    """

    def __init__(
        self,
        *,
        order_id: UUID,
        brief: Brief,
        music: MusicProvider,
        stt: SttProvider,
        similarity: NameSimilarity,
        settings: Settings,
        policy: RetryPolicy,
        sleeper: Sleeper,
        reporter: ProgressReporter,
        clock: Clock,
        slots: asyncio.Semaphore,
    ) -> None:
        self._order_id = order_id
        self._brief = brief
        self._music = music
        self._stt = stt
        self._similarity = similarity
        self._settings = settings
        self._policy = policy
        self._sleeper = sleeper
        self._reporter = reporter
        self._clock = clock
        self._slots = slots
        self._verdicts: tuple[NameVerdict, ...] = ()
        self._best: _Take | None = None
        self._cost_usd = 0.0
        self._source_song_id: str | None = None
        self._warned_no_stored_song: bool = False

    @property
    def _max_renders(self) -> int:
        return max(
            1,
            min(
                self._settings.name_verification_max_attempts,
                len(self._brief.recipient.candidates),
            ),
        )

    async def run(self, plan: CompositionPlan) -> Result[SongRender]:
        candidate = self._brief.recipient.candidates[0]
        current = plan
        for attempt in range(self._max_renders):
            rendered = await self._render(current, candidate)
            if isinstance(rendered, Err):
                return self._on_render_failure(rendered, attempt=attempt)

            take = self._keep(rendered.value, current, candidate)
            if not self._settings.is_name_verification_enabled:
                return ok(self._ship(take, renders=attempt + 1, was_checked=False))

            heard = await self._hear(take)
            if isinstance(heard, Err):
                _LOGGER.warning(
                    "name could not be verified acoustically; delivering this take",
                    extra={"attempt": attempt, **heard.error.to_log_dict()},
                )
                return ok(self._ship(take, renders=attempt + 1, was_checked=False))

            verdict = self._judge(heard.value, take, attempt=attempt)
            if verdict.is_match:
                await self._announce(ProgressStatus.SUCCEEDED, attempt, candidate)
                return ok(self._ship(take, renders=attempt + 1, was_checked=True, is_verified=True))

            advanced = await self._advance(current, candidate, attempt=attempt)
            if advanced is None:
                break
            current, candidate = advanced

        return ok(await self._give_up())

    # -- one attempt --------------------------------------------------------
    async def _render(
        self, plan: CompositionPlan, candidate: NameCandidate
    ) -> Result[RenderedAudio]:
        key = idempotency_key(self._order_id, PipelineStage.COMPOSING_SONG, candidate.rank)
        chunk_index = plan.name_chunk_index
        source_song_id = self._source_song_id
        timeout_s = self._settings.music_timeout_s

        async def call() -> Result[RenderedAudio]:
            async with self._slots:
                if source_song_id is None or chunk_index is None:
                    return await self._music.compose(plan, idempotency_key=key, timeout_s=timeout_s)
                return await self._music.inpaint(
                    plan,
                    source_song_id=source_song_id,
                    chunk_index=chunk_index,
                    idempotency_key=key,
                    timeout_s=timeout_s,
                )

        result, _report = await call_with_retry(
            call,
            label=f"music.{self._music.name}",
            policy=self._policy,
            sleeper=self._sleeper,
        )
        return result

    async def _hear(self, take: _Take) -> Result[Transcript]:
        keyterms = (
            self._brief.recipient.display,
            *(other.text for other in self._brief.recipient.candidates),
        )

        async def call() -> Result[Transcript]:
            return await self._stt.transcribe(
                take.audio.data,
                mime=take.audio.mime,
                language=self._brief.output_language,
                keyterms=tuple(dict.fromkeys(keyterms)),
                timeout_s=self._settings.stt_timeout_s,
            )

        result, _report = await call_with_retry(
            call, label=f"stt.{self._stt.name}", policy=self._policy, sleeper=self._sleeper
        )
        return result

    def _judge(self, transcript: Transcript, take: _Take, *, attempt: int) -> NameVerdict:
        score = best_similarity(transcript.text, self._brief.recipient.display, self._similarity)
        verdict = NameVerdict(
            candidate=take.candidate,
            transcript=transcript.text,
            is_match=score >= self._settings.name_match_min_similarity,
            confidence=score,
            attempt=attempt,
        )
        self._verdicts = (*self._verdicts, verdict)
        scored = take.model_copy(update={"score": score})
        if self._best is None or score > self._best.score:
            self._best = scored
        return verdict

    async def _advance(
        self, plan: CompositionPlan, candidate: NameCandidate, *, attempt: int
    ) -> tuple[CompositionPlan, NameCandidate] | None:
        """Swap in the next orthography, or return None when the ladder ends."""
        if attempt + 1 >= self._max_renders:
            return None
        following = self._brief.recipient.candidate_at(attempt + 1)
        if following is None:
            return None
        rerolled = with_name_candidate(plan, previous=candidate, candidate=following)
        if isinstance(rerolled, Err):
            _LOGGER.warning(
                "could not build a re-roll plan; stopping verification",
                extra=rerolled.error.to_log_dict(),
            )
            return None
        await self._announce(ProgressStatus.RETRYING, attempt + 1, following)
        return rerolled.value, following

    # -- bookkeeping --------------------------------------------------------
    def _keep(self, audio: RenderedAudio, plan: CompositionPlan, candidate: NameCandidate) -> _Take:
        self._cost_usd += audio.cost_usd
        if self._source_song_id is None:
            if audio.remote_id is None:
                self._warn_no_stored_song()
            self._source_song_id = audio.remote_id
        return _Take(candidate=candidate, audio=audio, plan=plan)

    def _warn_no_stored_song(self) -> None:
        """Say it out loud, once, when the cheap re-roll path is unavailable.

        Without a stored-song handle ``_render`` falls back to ``compose``, so every
        re-roll re-renders the WHOLE track instead of inpainting the eight-second name
        chunk — the same order, at up to three times the music bill. That fallback was
        silent, which is how it could be load-bearing and unnoticed at the same time.
        """
        if self._warned_no_stored_song:
            return
        self._warned_no_stored_song = True
        _LOGGER.warning(
            "vendor returned no stored-song handle; name re-rolls will re-compose the whole "
            "track instead of inpainting one chunk",
            extra={"order_id": str(self._order_id)},
        )

    def _ship(
        self,
        take: _Take,
        *,
        renders: int,
        was_checked: bool,
        is_verified: bool = False,
    ) -> SongRender:
        render = SongRender(
            audio=take.audio,
            plan=take.plan,
            candidate=take.candidate,
            verdicts=self._verdicts,
            is_verified=is_verified,
            was_checked=was_checked,
            renders=max(1, renders),
            cost_usd=self._cost_usd,
        )
        _LOGGER.info(
            VERIFICATION_EVENT,
            extra={
                "order_id": str(self._order_id),
                "renders": render.renders,
                "attempts": len(self._verdicts),
                "is_verified": is_verified,
                "was_checked": was_checked,
                "best_score": take.score,
                "strategy": take.candidate.strategy.value,
                "did_inpaint": self._source_song_id is not None,
                "cost_usd": self._cost_usd,
            },
        )
        return render

    def _on_render_failure(self, failure: Err, *, attempt: int) -> Result[SongRender]:
        if self._best is None:
            return failure
        _LOGGER.warning(
            "name re-roll failed; shipping the best earlier take",
            extra={"attempt": attempt, **failure.error.to_log_dict()},
        )
        return ok(self._ship(self._best, renders=attempt, was_checked=True))

    async def _give_up(self) -> SongRender:
        best = self._best
        if best is None:  # pragma: no cover - the loop always keeps at least one take
            raise AssertionError("the verification loop ended without a take")
        await self._announce(ProgressStatus.DEGRADED, len(self._verdicts), best.candidate)
        _LOGGER.warning(
            "every candidate orthography missed; delivering the closest take",
            extra={
                "attempts": len(self._verdicts),
                "best_score": best.score,
                "strategy": best.candidate.strategy.value,
            },
        )
        return self._ship(best, renders=len(self._verdicts), was_checked=True)

    async def _announce(
        self, status: ProgressStatus, attempt: int, candidate: NameCandidate
    ) -> None:
        await self._reporter.emit(
            PipelineStage.VERIFYING_NAME,
            status,
            now=self._clock(),
            attempt=attempt,
            strategy=candidate.strategy.value,
        )


async def render_song(
    plan: CompositionPlan,
    *,
    order_id: UUID,
    brief: Brief,
    music: MusicProvider,
    stt: SttProvider,
    similarity: NameSimilarity,
    settings: Settings,
    policy: RetryPolicy,
    sleeper: Sleeper,
    reporter: ProgressReporter,
    clock: Clock,
    slots: asyncio.Semaphore,
) -> Result[SongRender]:
    """Render the song, re-rolling the name chunk until it is heard correctly."""
    loop = _NameLoop(
        order_id=order_id,
        brief=brief,
        music=music,
        stt=stt,
        similarity=similarity,
        settings=settings,
        policy=policy,
        sleeper=sleeper,
        reporter=reporter,
        clock=clock,
        slots=slots,
    )
    return await loop.run(plan)
