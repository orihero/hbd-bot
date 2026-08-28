"""The orchestrator: one ``Brief`` in, one ``Kit`` out.

Four rules govern every line below.

**The Result boundary is absolute.** No provider call is awaited outside a ``Result``
check, and the decision to retry is read off ``HbdError.is_retryable`` rather than guessed
from the shape of the failure.

**Idempotency.** A finished kit short-circuits the whole run, provider calls carry
deterministic keys, and assets are written to deterministic paths. Re-queueing a job costs
one database read, not one more song.

**Partial delivery beats no delivery.** The song and the three greetings do not share a
fate. If a greeting fails, the kit ships without it and the hole is recorded as a
``PipelineGap``; the only thing that can sink a run is losing the song, the lyric or every
single greeting.

**Everything is measured.** No vendor publishes latency for music generation, so a
``StepTiming`` per stage is the only p95 this product will ever have.

One stage is no longer guaranteed to do work. The lyric may already be decided before the
pipeline runs, because the customer previewed and approved it in the wizard; in that case
``brief.approved_lyrics`` carries the exact words they agreed to and WRITING_LYRICS simply
hands them back. The stage still exists on both paths on purpose — the timing, the progress
frame and the LYRICS_READY transition stay identical whether the lyric took eight seconds
to write or zero, so nothing downstream has to know which path an order took.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Final

from pydantic import BaseModel, ConfigDict

from hbd.config import Settings
from hbd.contracts import (
    AudioPostProcessor,
    Brief,
    Err,
    Kit,
    KitRepository,
    LlmProvider,
    LyricDraft,
    MusicProvider,
    Order,
    OrderState,
    PaymentProvider,
    Result,
    SpokenScript,
    Storage,
    SttProvider,
    TtsProvider,
    VoiceDescriptor,
    err,
    is_ok,
    ok,
)
from hbd.errors import HbdError, NameVerificationExhaustedError, PipelineError
from hbd.logging import correlation_scope, get_logger
from hbd.pipeline.assembly import assemble_kit, persist_kit, validate_brief
from hbd.pipeline.content import LlmContentWriter
from hbd.pipeline.events import (
    NullProgressSink,
    PipelineStage,
    ProgressReporter,
    ProgressSink,
    ProgressStatus,
)
from hbd.pipeline.greetings import GreetingBatch, render_greetings
from hbd.pipeline.moderation import LlmModerator
from hbd.pipeline.name_stage import SongRender, render_song
from hbd.pipeline.outcome import PipelineOutcome, RunLedger
from hbd.pipeline.personas import select_voices
from hbd.pipeline.plan_builder import build_composition_plan, derive_seed
from hbd.pipeline.ports import Clock, ContentWriter, Moderator, NameSimilarity, Sleeper
from hbd.pipeline.retry import RetryPolicy, call_with_retry

__all__ = ["KitPipeline", "DEFAULT_MUSIC_SLOTS", "DEFAULT_TTS_SLOTS"]

_LOGGER = get_logger(__name__)

#: Fallback slot counts, used only when a caller builds a pipeline without passing
#: semaphores. Production wiring passes ``music_max_concurrency`` / ``tts_max_concurrency``
#: from ``Settings``; these keep a bare ``KitPipeline(...)`` in a test from being unbounded.
DEFAULT_MUSIC_SLOTS: Final[int] = 2
DEFAULT_TTS_SLOTS: Final[int] = 3


def _utc_now() -> datetime:
    return datetime.now(UTC)


class _Words(BaseModel):
    """Everything the language stages produced, before a byte of audio exists."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    lyrics: LyricDraft
    scripts: tuple[SpokenScript, ...]
    voices: tuple[VoiceDescriptor, ...]


class _Media(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    song: SongRender
    greetings: GreetingBatch


class KitPipeline:
    """Runs one order to completion. Safe to share across concurrent jobs."""

    def __init__(
        self,
        *,
        settings: Settings,
        music: MusicProvider,
        tts: TtsProvider,
        llm: LlmProvider,
        stt: SttProvider,
        payment: PaymentProvider,
        post: AudioPostProcessor,
        storage: Storage,
        repository: KitRepository,
        similarity: NameSimilarity,
        workspace_root: Path,
        content_writer: ContentWriter | None = None,
        moderator: Moderator | None = None,
        sink: ProgressSink | None = None,
        clock: Clock = _utc_now,
        sleeper: Sleeper = asyncio.sleep,
        music_slots: asyncio.Semaphore | None = None,
        tts_slots: asyncio.Semaphore | None = None,
    ) -> None:
        self._settings = settings
        self._music = music
        self._tts = tts
        self._stt = stt
        self._payment = payment
        self._post = post
        self._storage = storage
        self._repository = repository
        self._similarity = similarity
        self._workspace_root = workspace_root
        self._content: ContentWriter = content_writer or LlmContentWriter(llm, settings)
        self._moderator: Moderator = moderator or LlmModerator(llm, settings)
        self._sink: ProgressSink = sink or NullProgressSink()
        self._clock = clock
        self._sleeper = sleeper
        self._music_slots = music_slots or asyncio.Semaphore(DEFAULT_MUSIC_SLOTS)
        self._tts_slots = tts_slots or asyncio.Semaphore(DEFAULT_TTS_SLOTS)
        self._provider_policy = RetryPolicy.from_settings(settings)
        self._llm_policy = RetryPolicy(
            max_attempts=settings.llm_parse_max_attempts,
            backoff_base_s=settings.provider_backoff_base_s,
            jitter=settings.provider_backoff_jitter,
        )

    # -- entry point --------------------------------------------------------
    async def run(self, order: Order) -> Result[PipelineOutcome]:
        """Generate and persist the kit for ``order``. Never raises."""
        with correlation_scope(order.correlation_id):
            return await self._run(order)

    async def _run(self, order: Order) -> Result[PipelineOutcome]:
        replay = await self._replay(order)
        if replay is not None:
            return replay

        ledger = RunLedger()
        reporter = ProgressReporter(
            self._sink, order_id=order.id, correlation_id=order.correlation_id
        )

        words = await self._prepare(order, reporter, ledger)
        if isinstance(words, Err):
            return await self._fail(order, reporter, words.error)

        media = await self._produce(order, words.value, reporter, ledger)
        if isinstance(media, Err):
            return await self._fail(order, reporter, media.error)

        kit = await self._finish(order, words.value, media.value, reporter, ledger)
        if isinstance(kit, Err):
            return await self._fail(order, reporter, kit.error)

        await self._deliver(order, reporter)
        return ok(
            PipelineOutcome(
                kit=kit.value,
                gaps=ledger.gaps,
                timings=ledger.timings,
                name_verdicts=media.value.song.verdicts,
                total_cost_usd=ledger.cost_usd,
            )
        )

    # -- stages -------------------------------------------------------------
    async def _prepare(
        self, order: Order, reporter: ProgressReporter, ledger: RunLedger
    ) -> Result[_Words]:
        brief = order.brief
        validated = await self._staged(
            reporter, ledger, PipelineStage.VALIDATING, lambda: _validated(brief)
        )
        if isinstance(validated, Err):
            return validated

        moderated = await self._staged(
            reporter, ledger, PipelineStage.MODERATING, lambda: self._moderator.review(brief)
        )
        if isinstance(moderated, Err):
            return moderated

        lyrics = await self._staged(
            reporter,
            ledger,
            PipelineStage.WRITING_LYRICS,
            lambda: self._lyrics_for(brief),
            policy=self._llm_policy,
        )
        if isinstance(lyrics, Err):
            return lyrics
        await self._advance_state(order, OrderState.LYRICS_READY)

        # With greetings switched off both speech stages are skipped outright rather than
        # run empty, so the progress bar never narrates work that is not happening.
        if self._settings.greetings_per_kit > 0:
            words = await self._staged(
                reporter,
                ledger,
                PipelineStage.WRITING_SCRIPTS,
                lambda: self._write_scripts(brief, lyrics.value),
                policy=self._llm_policy,
            )
        else:
            words = await self._write_scripts(brief, lyrics.value)
        if isinstance(words, Err):
            return words

        authorized = await self._staged(
            reporter, ledger, PipelineStage.AUTHORIZING, lambda: self._authorize(order)
        )
        if isinstance(authorized, Err):
            return authorized
        await self._advance_state(order, OrderState.AUTHORIZED)
        return words

    async def _produce(
        self, order: Order, words: _Words, reporter: ProgressReporter, ledger: RunLedger
    ) -> Result[_Media]:
        await self._advance_state(order, OrderState.GENERATING)
        song = await self._staged(
            reporter,
            ledger,
            PipelineStage.COMPOSING_SONG,
            lambda: self._compose(order, words, reporter),
        )
        if isinstance(song, Err):
            return song
        ledger.record_cost(song.value.cost_usd)
        self._record_name_gap(ledger, song.value)

        if self._settings.greetings_per_kit > 0:
            batch = await self._staged(
                reporter,
                ledger,
                PipelineStage.RENDERING_GREETINGS,
                lambda: self._render_greetings(order, words),
            )
        else:
            batch = await self._render_greetings(order, words)
        if isinstance(batch, Err):
            return batch
        ledger.record_cost(batch.value.cost_usd)
        for failure in batch.value.failures:
            ledger.record_gap(
                PipelineStage.RENDERING_GREETINGS,
                failure.error,
                detail=f"greeting {failure.index + 1} ({failure.persona_id}) was not rendered",
            )
        return ok(_Media(song=song.value, greetings=batch.value))

    async def _finish(
        self,
        order: Order,
        words: _Words,
        media: _Media,
        reporter: ProgressReporter,
        ledger: RunLedger,
    ) -> Result[Kit]:
        kit = await self._staged(
            reporter,
            ledger,
            PipelineStage.POST_PROCESSING,
            lambda: self._assemble(order, words, media, ledger),
        )
        if isinstance(kit, Err):
            return kit
        return await self._staged(
            reporter,
            ledger,
            PipelineStage.PERSISTING,
            lambda: self._persist(order, kit.value, ledger),
        )

    async def _deliver(self, order: Order, reporter: ProgressReporter) -> None:
        await self._advance_state(order, OrderState.DELIVERED)
        await reporter.emit(PipelineStage.DELIVERING, ProgressStatus.SUCCEEDED, now=self._clock())

    # -- individual steps ---------------------------------------------------
    async def _lyrics_for(self, brief: Brief) -> Result[LyricDraft]:
        """The lyric the customer approved, or one written now.

        Approval happens in the wizard, before payment, so by the time a job reaches the
        worker the words may already be settled. Re-writing them here would deliver a song
        the customer never saw, so an approved lyric wins outright and the LLM is not
        called at all.
        """
        approved = brief.approved_lyrics
        if approved is not None:
            _LOGGER.info(
                "using the lyric the customer approved in the wizard",
                extra={"sections": len(approved.sections)},
            )
            return ok(approved)
        return await self._content.write_lyrics(brief)

    async def _write_scripts(self, brief: Brief, lyrics: LyricDraft) -> Result[_Words]:
        # A song-only kit must not touch the speech vendor at all: no catalogue fetch, no
        # script generation. Asking for zero voices and letting the empty tuple flow on
        # would still spend a request and could fail the order on a vendor we do not use.
        if self._settings.greetings_per_kit <= 0:
            return ok(_Words(lyrics=lyrics, scripts=(), voices=()))

        async def call() -> Result[tuple[VoiceDescriptor, ...]]:
            return await self._tts.voices()

        catalogue, _report = await call_with_retry(
            call,
            label=f"tts.{self._tts.name}.voices",
            policy=self._provider_policy,
            sleeper=self._sleeper,
        )
        if isinstance(catalogue, Err):
            return catalogue

        chosen = select_voices(
            catalogue.value,
            language=brief.output_language,
            preferred_gender=brief.vocal_gender,
            count=self._settings.greetings_per_kit,
        )
        if isinstance(chosen, Err):
            return chosen

        target_s = (
            self._settings.greeting_min_duration_s + self._settings.greeting_max_duration_s
        ) / 2
        scripts = await self._content.write_scripts(
            brief,
            lyrics,
            voices=chosen.value,
            name_submitted=brief.recipient.candidates[0].text,
            target_duration_s=target_s,
        )
        if isinstance(scripts, Err):
            return scripts
        return ok(_Words(lyrics=lyrics, scripts=scripts.value, voices=chosen.value))

    async def _authorize(self, order: Order) -> Result[None]:
        authorization = await self._payment.authorize(
            order_id=order.id,
            amount_minor=self._settings.kit_price_amount_minor,
            currency=self._settings.kit_currency,
        )
        if isinstance(authorization, Err):
            return authorization
        if not authorization.value.is_authorized:
            return err(
                PipelineError(
                    "payment provider declined the order",
                    user_message_key="error.payment_failed",
                    context={"provider": authorization.value.provider},
                )
            )
        return ok(None)

    async def _compose(
        self, order: Order, words: _Words, reporter: ProgressReporter
    ) -> Result[SongRender]:
        plan = build_composition_plan(
            words.lyrics,
            brief=order.brief,
            candidate=order.brief.recipient.candidates[0],
            settings=self._settings,
            seed=derive_seed(order.id),
        )
        if isinstance(plan, Err):
            return plan
        await reporter.emit(PipelineStage.VERIFYING_NAME, ProgressStatus.STARTED, now=self._clock())
        return await render_song(
            plan.value,
            order_id=order.id,
            brief=order.brief,
            music=self._music,
            stt=self._stt,
            similarity=self._similarity,
            settings=self._settings,
            policy=self._provider_policy,
            sleeper=self._sleeper,
            reporter=reporter,
            clock=self._clock,
            slots=self._music_slots,
        )

    async def _render_greetings(self, order: Order, words: _Words) -> Result[GreetingBatch]:
        batch = await render_greetings(
            words.scripts,
            order_id=order.id,
            tts=self._tts,
            settings=self._settings,
            policy=self._provider_policy,
            sleeper=self._sleeper,
            slots=self._tts_slots,
        )
        return ok(batch)

    async def _assemble(
        self, order: Order, words: _Words, media: _Media, ledger: RunLedger
    ) -> Result[Kit]:
        return await assemble_kit(
            order_id=order.id,
            lyrics=words.lyrics,
            song=media.song,
            greetings=media.greetings,
            workspace_root=self._workspace_root,
            post=self._post,
            settings=self._settings,
            ledger=ledger,
        )

    async def _persist(self, order: Order, kit: Kit, ledger: RunLedger) -> Result[Kit]:
        return await persist_kit(
            kit,
            order_id=order.id,
            storage=self._storage,
            repository=self._repository,
            policy=self._provider_policy,
            sleeper=self._sleeper,
            ledger=ledger,
        )

    # -- plumbing -----------------------------------------------------------
    async def _staged[T](
        self,
        reporter: ProgressReporter,
        ledger: RunLedger,
        stage: PipelineStage,
        operation: Callable[[], Awaitable[Result[T]]],
        *,
        policy: RetryPolicy | None = None,
    ) -> Result[T]:
        """Time one stage, announce it, and retry it if the policy says so."""
        await reporter.emit(stage, ProgressStatus.STARTED, now=self._clock())
        started = self._clock()

        async def on_retry(attempt: int, error: HbdError) -> None:
            await reporter.emit(
                stage, ProgressStatus.RETRYING, now=self._clock(), attempt=attempt, error=error
            )

        result, report = await call_with_retry(
            operation,
            label=f"stage.{stage.value}",
            policy=policy or RetryPolicy.single_attempt(),
            sleeper=self._sleeper,
            on_retry=on_retry,
        )
        elapsed_ms = int((self._clock() - started).total_seconds() * 1_000)
        is_failed = isinstance(result, Err)
        ledger.record_timing(
            stage, duration_ms=elapsed_ms, attempts=report.attempts, is_ok=not is_failed
        )
        if isinstance(result, Err):
            await reporter.emit(stage, ProgressStatus.FAILED, now=self._clock(), error=result.error)
            return result
        await reporter.emit(stage, ProgressStatus.SUCCEEDED, now=self._clock())
        return result

    async def _replay(self, order: Order) -> Result[PipelineOutcome] | None:
        """Return the stored kit when this order already finished. Idempotency, step one."""
        existing = await self._repository.get_kit(order.id)
        if is_ok(existing):
            _LOGGER.info(
                "order already has a kit; replaying it rather than re-buying it",
                extra={"order_id": str(order.id)},
            )
            kit = existing.value
            return ok(PipelineOutcome(kit=kit, name_verdicts=kit.name_verdicts))
        return None

    def _record_name_gap(self, ledger: RunLedger, song: SongRender) -> None:
        if song.is_verified or not song.was_checked:
            return
        ledger.record_gap(
            PipelineStage.VERIFYING_NAME,
            NameVerificationExhaustedError(
                "no candidate orthography was heard back correctly",
                context={
                    "attempts": len(song.verdicts),
                    "strategy": song.candidate.strategy.value,
                },
            ),
            detail="the name may not be pronounced exactly as intended",
        )

    async def _advance_state(self, order: Order, state: OrderState) -> None:
        result = await self._repository.set_order_state(order.id, state, now=self._clock())
        if isinstance(result, Err):
            _LOGGER.warning(
                "order state transition was not persisted",
                extra={
                    "order_id": str(order.id),
                    "state": state.value,
                    **result.error.to_log_dict(),
                },
            )

    async def _fail(
        self, order: Order, reporter: ProgressReporter, error: HbdError
    ) -> Result[PipelineOutcome]:
        await self._advance_state(order, OrderState.FAILED)
        _LOGGER.error("order failed", extra={"order_id": str(order.id), **error.to_log_dict()})
        return err(error)


async def _validated(brief: Brief) -> Result[None]:
    """``_staged`` wants an awaitable; boundary validation is synchronous."""
    return validate_brief(brief)
