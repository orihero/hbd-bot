"""The orchestrator: one ``Brief`` in, one ``Kit`` out.

Four rules govern every line below.

**The Result boundary is absolute.** No provider call is awaited outside a ``Result``
check, and the decision to retry is read off ``HbdError.is_retryable`` rather than guessed
from the shape of the failure.

**Idempotency.** A finished kit short-circuits the whole run, provider calls carry
deterministic keys, and assets are written to deterministic paths. Re-queueing a job costs
one database read, not one more song. The short-circuit rebuilds the run's gaps from what
the stored kit proves rather than reporting none, because a replay that claims a clean run
strips the disclosures the first delivery carried — see ``_replayed_gaps``.

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
from collections.abc import Awaitable, Callable, Mapping
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
    UsageTask,
    VoiceDescriptor,
    err,
    is_ok,
    ok,
)
from hbd.db.models.order import FAILED_REASON_LENGTH
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
    scheduled_stages,
)
from hbd.pipeline.greetings import GreetingBatch, render_greetings
from hbd.pipeline.moderation import LlmModerator
from hbd.pipeline.name_stage import SongRender, render_song
from hbd.pipeline.outcome import PipelineGap, PipelineOutcome, RunLedger
from hbd.pipeline.personas import select_voices
from hbd.pipeline.plan_builder import build_composition_plan, derive_seed
from hbd.pipeline.ports import Clock, ContentWriter, Moderator, NameSimilarity, Sleeper
from hbd.pipeline.retry import RetryPolicy, call_with_retry
from hbd.usage import usage_scope

__all__ = ["KitPipeline", "DEFAULT_MUSIC_SLOTS", "DEFAULT_TTS_SLOTS"]

_LOGGER = get_logger(__name__)

#: Fallback slot counts, used only when a caller builds a pipeline without passing
#: semaphores. Production wiring passes ``music_max_concurrency`` / ``tts_max_concurrency``
#: from ``Settings``; these keep a bare ``KitPipeline(...)`` in a test from being unbounded.
DEFAULT_MUSIC_SLOTS: Final[int] = 2
DEFAULT_TTS_SLOTS: Final[int] = 3

# ---------------------------------------------------------------------------
# Stage -> vendor-usage task
#
# THE ONLY PLACE THE TWO VOCABULARIES MEET. ``PipelineStage`` is this package's word for
# where a run is; ``UsageTask`` is the vendor layer's word for what a call was FOR, and it
# lives in ``hbd.contracts`` precisely so that a provider adapter stamping a row never has
# to import ``hbd.pipeline``. Mapping them here, once, is what keeps that true.
#
# Six entries, not twelve: only these stages call a vendor. VALIDATING, AUTHORIZING,
# POST_PROCESSING, PERSISTING and DELIVERING spend nothing, so a ``.get()`` miss on them
# is the right answer and leaves ``task`` NULL rather than inventing a label for a call
# that was never made.
#
# VERIFYING_NAME is in the table but is not, today, a stage ``_staged`` wraps: the name
# loop runs INSIDE ``render_song``, which runs inside COMPOSING_SONG, so its transcription
# calls are attributed to SONG. That is honest — they are part of composing the song — and
# the entry stays because the day the loop gets its own stage wrapper the attribution
# should follow it rather than have to be discovered again.
# ---------------------------------------------------------------------------
_STAGE_TASKS: Final[Mapping[PipelineStage, UsageTask]] = {
    PipelineStage.MODERATING: UsageTask.MODERATION,
    PipelineStage.WRITING_LYRICS: UsageTask.LYRICS,
    PipelineStage.WRITING_SCRIPTS: UsageTask.GREETING_SCRIPTS,
    PipelineStage.COMPOSING_SONG: UsageTask.SONG,
    PipelineStage.VERIFYING_NAME: UsageTask.NAME_VERIFICATION,
    PipelineStage.RENDERING_GREETINGS: UsageTask.GREETING_SPEECH,
}

# ---------------------------------------------------------------------------
# orders.failed_reason
#
# *** NOTHING A CUSTOMER TYPED, AND NOTHING A MODEL WROTE ABOUT WHAT THEY TYPED,
# *** MAY EVER REACH THIS STRING.
#
# ``orders`` carries no recipient data by design (SoW DAT-3): the brief is purged on its
# own clock while the order row survives as the tax record, so anything written to
# ``failed_reason`` escapes the purge and outlives the customer's data. Meanwhile
# ``HbdError.context`` is built for the LOG, where redaction happens downstream, and
# routinely holds exactly the wrong things — ``ModerationRejectedError`` puts 200
# characters of the sender's note under ``note`` and the model's quote of it under
# ``reason``; ``hbd.names.resolve`` puts the typed name under ``raw``.
#
# So context is NOT serialised. Only these keys are copied, and the list is an allowlist
# on purpose: a key added to an error tomorrow is excluded by default, which is the only
# direction of failure this column can survive. Every entry below is either our own
# vocabulary or a vendor's — none of them is user text.
# ---------------------------------------------------------------------------
_SAFE_CONTEXT_KEYS: Final[tuple[str, ...]] = (
    "provider",  # vendor name, e.g. "elevenlabs"
    "operation",  # our own label, e.g. "stage.composing_song"
    "hit_in",  # WHICH field tripped the denylist ("note"/"name"/"lyrics") — never what was in it
    "failure",  # an ErrorCode value from a nested error
    "attempts",
    "chunk_index",
    "chunk_count",
    "timeout_s",
    "retry_after_s",
)

#: Per-value ceiling, so one long vendor string cannot crowd out the pairs after it.
_SAFE_VALUE_CHARS: Final[int] = 48

#: What we store when the formatter itself misbehaves. Still triageable: it says the run
#: failed and that the reason is the thing that broke, which is better than a NULL.
_UNRENDERABLE_REASON: Final[str] = "UNKNOWN: failed_reason could not be rendered"


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _rendered_failed_reason(error: HbdError, *, stage: PipelineStage | None) -> str:
    """Build the ``orders.failed_reason`` string. Read the banner above before editing.

    Shape is ``"<ERROR_CODE>: <ExceptionClass> at <stage>; k=v; k=v"`` — stable enough to
    ``GROUP BY`` on a ``LIKE 'CONTENT_REJECTED%'``, specific enough that the live incident
    this exists for would have read ``CONTENT_REJECTED: ModerationRejectedError at
    moderating; retryable=false`` in the database instead of needing the vendor call
    replayed by hand. ``retryable`` is always the first pair because it is the one an
    operator triages on — is this order requeueable, or is it dead? That incident carries
    no other pair: the model rejected it, so the only context keys present are ``note``
    and the model's ``reason``, and both are user text the allowlist drops. A denylist
    rejection of the same brief would add ``; hit_in=note`` — the field label, never the
    matched substring.

    The code/class/stage prefix is composed first and pairs are appended only while they
    fit, so truncation drops trailing detail and can never cut the part that makes the row
    triageable in the first place.
    """
    prefix = f"{error.error_code.value}: {type(error).__name__}"
    if stage is not None:
        prefix = f"{prefix} at {stage.value}"
    parts = [prefix[:FAILED_REASON_LENGTH]]
    budget = len(parts[0])
    for key, value in _safe_pairs(error):
        rendered = f"; {key}={value}"
        if budget + len(rendered) > FAILED_REASON_LENGTH:
            break
        parts.append(rendered)
        budget += len(rendered)
    return "".join(parts)


def _safe_pairs(error: HbdError) -> list[tuple[str, str]]:
    """Operator-safe scalars, in a fixed order so the same failure renders the same way."""
    pairs = [("retryable", str(error.is_retryable).lower())]
    for key in _SAFE_CONTEXT_KEYS:
        value = error.context.get(key)
        if value is None or isinstance(value, list | tuple | dict | set):
            continue
        pairs.append((key, str(value)[:_SAFE_VALUE_CHARS]))
    return pairs


def _failed_reason(error: HbdError, *, stage: PipelineStage | None) -> str:
    """``_rendered_failed_reason`` behind a never-throw boundary.

    This runs on the last code path a doomed order will ever take. A formatter bug here
    would turn a clean, reported failure into an unhandled exception inside ``_fail``, so
    the ugly fallback string wins over correctness every time.
    """
    try:
        return _rendered_failed_reason(error, stage=stage)
    except Exception:
        _LOGGER.exception("could not render a failed_reason; storing the fallback")
        return _UNRENDERABLE_REASON


def _failed_stage(ledger: RunLedger) -> PipelineStage | None:
    """The stage the run died in, read off the ledger instead of threaded through it.

    ``_staged`` records a timing with ``is_ok=False`` for exactly the stage that failed,
    so the last such timing IS the point of death. Returns ``None`` for the few steps that
    run outside ``_staged`` (greetings with the stage switched off), because a wrong stage
    on a failure record is worse than no stage.
    """
    for timing in reversed(ledger.timings):
        if not timing.is_ok:
            return timing.stage
    return None


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
        """Generate and persist the kit for ``order``. Never raises.

        Two scopes are bound for the whole run and neither reaches a provider signature:
        the correlation id ties every log line together, and ``usage_scope`` ties every
        vendor row this run writes to the order that paid for it. The task half is bound
        per stage in :meth:`_staged`, inside this one.
        """
        with correlation_scope(order.correlation_id), usage_scope(order_id=order.id):
            return await self._run(order)

    async def _run(self, order: Order) -> Result[PipelineOutcome]:
        replay = await self._replay(order)
        if replay is not None:
            return replay

        ledger = RunLedger()
        reporter = ProgressReporter(
            self._sink,
            order_id=order.id,
            correlation_id=order.correlation_id,
            stage_plan=scheduled_stages(has_greetings=self._settings.greetings_per_kit > 0),
        )

        words = await self._prepare(order, reporter, ledger)
        if isinstance(words, Err):
            return await self._fail(order, reporter, words.error, ledger)

        media = await self._produce(order, words.value, reporter, ledger)
        if isinstance(media, Err):
            return await self._fail(order, reporter, media.error, ledger)

        kit = await self._finish(order, words.value, media.value, reporter, ledger)
        if isinstance(kit, Err):
            return await self._fail(order, reporter, kit.error, ledger)

        await self._deliver(order)
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

        # Second, and deliberately: nothing above this line costs a vendor a cent. See
        # ``_gated`` for why the gate is here and not where it used to be.
        gate = await self._gated(order, reporter, ledger)
        if isinstance(gate, Err):
            return gate

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

        words = await self._scripted(brief, lyrics.value, reporter, ledger)
        if isinstance(words, Err):
            return words

        # The CHARGE moved to the top of this method; this MILESTONE deliberately did not —
        # see ``_gated``. The order row walks exactly the ladder it walked before.
        await self._advance_state(order, OrderState.AUTHORIZED)
        return words

    async def _scripted(
        self, brief: Brief, lyrics: LyricDraft, reporter: ProgressReporter, ledger: RunLedger
    ) -> Result[_Words]:
        """Write the spoken scripts, narrating the stage only when it will really run.

        With greetings switched off both speech stages are skipped outright rather than run
        empty, so the progress bar never narrates work that is not happening — but the
        writer is still called, because ``_Words`` carries the chosen voices that the song
        stage needs whether or not anyone speaks.
        """
        if self._settings.greetings_per_kit > 0:
            return await self._staged(
                reporter,
                ledger,
                PipelineStage.WRITING_SCRIPTS,
                lambda: self._write_scripts(brief, lyrics),
                policy=self._llm_policy,
            )
        return await self._write_scripts(brief, lyrics)

    async def _gated(
        self, order: Order, reporter: ProgressReporter, ledger: RunLedger
    ) -> Result[None]:
        """Ask whether this account may have this render, BEFORE any vendor is called.

        The stage sits second in ``STAGE_ORDER``, and its position is the whole point. It
        used to run fifth, after MODERATING and WRITING_SCRIPTS, so an account that was
        blocked, out of credits or already rendering still bought two LLM calls before being
        told no — every attempt, for as long as it kept confirming. VALIDATING is local and
        free, so this is both the first instant at which the answer can be asked for and the
        last one at which a refusal costs nothing.

        The matching ``OrderState.AUTHORIZED`` transition did NOT move up with it, and that
        split is intentional. ``OrderState`` is documented forward-only
        (``hbd.contracts``:167) and AUTHORIZED is the *tax-side* latch:
        ``repository._set_order_state`` sets ``is_paid`` from it and never clears it, and
        the retention policy reads ``is_paid`` to decide how long the audio lives. Writing
        it here would walk the row AUTHORIZED -> LYRICS_READY, i.e. backwards, to record a
        fact that is not the same fact — entitlement movement lives in ``credit_ledger``
        and has its own audit trail.
        """
        return await self._staged(
            reporter, ledger, PipelineStage.AUTHORIZING, lambda: self._authorize(order)
        )

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

    async def _deliver(self, order: Order) -> None:
        """Mark the order delivered. Emits nothing.

        The DELIVERING frames belong to ``hbd.runtime.jobs._send_kit``, which brackets the
        actual send: STARTED before the first byte, SUCCEEDED only once ``deliver_kit``
        says everything landed. This used to emit SUCCEEDED here instead — i.e. "Done —
        sending it now" — before the send had been attempted at all, so a kit that failed
        to send left a tick on the customer's screen.
        """
        await self._advance_state(order, OrderState.DELIVERED)

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
        #
        # A NAMELESS order is song-only for the same reason and by a different route: a
        # spoken greeting is a persona saying the recipient's name, so with no recipient
        # there is nothing for one to say. This is the guard that keeps the whole greeting
        # subsystem — personas, voice selection, the name respelling handed to TTS — out of
        # a code path that has no name to give it.
        if self._settings.greetings_per_kit <= 0 or brief.recipient is None:
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
            # Greetings are only written when a name exists to speak: ``_write_scripts``
            # is already gated on ``greetings_per_kit``, and a nameless order has nobody to
            # greet, so the stage is skipped for one entirely.
            name_submitted=brief.recipient.candidates[0].text,
            target_duration_s=target_s,
        )
        if isinstance(scripts, Err):
            return scripts
        return ok(_Words(lyrics=lyrics, scripts=scripts.value, voices=chosen.value))

    async def _authorize(self, order: Order) -> Result[None]:
        # The worker re-runs the gate the bot already ran, on the same order. The payer is
        # taken from the order rather than from any ambient job context, so the two calls
        # name the same person and a provider that meters per user can recognise the second
        # authorisation as a retry of the first instead of a fresh purchase.
        authorization = await self._payment.authorize(
            order_id=order.id,
            amount_minor=self._settings.kit_price_amount_minor,
            currency=self._settings.kit_currency,
            telegram_user_id=order.telegram_user_id,
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
            # ``None`` for a nameless order, which is what tells ``build_composition_plan``
            # to lay the song out with no name chunk in it.
            candidate=(
                None if order.brief.recipient is None else order.brief.recipient.candidates[0]
            ),
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
        """Time one stage, announce it, and retry it if the policy says so.

        It is also where a vendor call learns what it was FOR. Every stage funnels through
        here and every stage knows its own :class:`PipelineStage`, so binding
        ``usage_scope(task=...)`` around the one await that can reach a provider labels all
        six vendor-calling stages from a single site — including the retries, which are
        real vendor calls and are billed like any other.

        The inner scope names ONLY the task. It does not clear the ``order_id`` bound by
        :meth:`run` around the whole run: ``usage_scope`` inherits a field passed as
        ``None`` rather than blanking it, which is what makes the two-layer binding work
        at all. A stage that calls no vendor maps to ``None`` and simply leaves the task
        unbound rather than inventing a label for a call nobody made.
        """
        await reporter.emit(stage, ProgressStatus.STARTED, now=self._clock())
        started = self._clock()

        async def on_retry(attempt: int, error: HbdError) -> None:
            await reporter.emit(
                stage, ProgressStatus.RETRYING, now=self._clock(), attempt=attempt, error=error
            )

        with usage_scope(task=_STAGE_TASKS.get(stage)):
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
        if not is_ok(existing):
            return None
        kit = existing.value
        gaps = self._replayed_gaps(kit)
        _LOGGER.info(
            "order already has a kit; replaying it rather than re-buying it",
            extra={"order_id": str(order.id), "gaps": len(gaps)},
        )
        return ok(PipelineOutcome(kit=kit, gaps=gaps, name_verdicts=kit.name_verdicts))

    def _replayed_gaps(self, kit: Kit) -> tuple[PipelineGap, ...]:
        """The gaps a STORED kit still proves, rebuilt for a redelivery.

        Gaps are not persisted — there is no table for them, and the queue payload carries
        an order id and nothing else — so a replay cannot read back what the original run
        recorded. Defaulting to none was the bug: a redelivered closing message dropped the
        pronunciation disclosure the first one carried, and quietly told the customer the
        run had been clean.

        Two of the three kinds are provable from the kit itself, which is why this is a
        reconstruction rather than a guess:

        * every stored verdict is a non-match — the name loop ran out of orthographies,
          exactly the condition ``_record_name_gap`` fires on;
        * the kit holds fewer greetings than ``greetings_per_kit`` asked for — that many
          did not survive rendering or post-processing.

        The third, an asset that failed to ARCHIVE at ``PERSISTING``, leaves no trace in
        the kit and is not reconstructed. It is also the only one with no consequence the
        customer can hear: the files were delivered from the worker's disk either way. So
        this replay never claims a clean run it cannot prove — it claims the absence of
        the gaps that would have changed what the customer received.
        """
        ledger = RunLedger()
        if kit.name_verdicts and not any(verdict.is_match for verdict in kit.name_verdicts):
            ledger.record_gap(
                PipelineStage.VERIFYING_NAME,
                NameVerificationExhaustedError(
                    "the stored kit's verdicts contain no match",
                    context={"order_id": str(kit.order_id), "attempts": len(kit.name_verdicts)},
                ),
                detail="the name may not be pronounced exactly as intended",
            )
        delivered = len(kit.greetings)
        for index in range(delivered, self._settings.greetings_per_kit):
            ledger.record_gap(
                PipelineStage.RENDERING_GREETINGS,
                PipelineError(
                    "the stored kit is short of the greetings this order asked for",
                    context={
                        "order_id": str(kit.order_id),
                        "stored": delivered,
                        "requested": self._settings.greetings_per_kit,
                    },
                ),
                detail=f"greeting {index + 1} is not in the stored kit",
            )
        return ledger.gaps

    def _record_name_gap(self, ledger: RunLedger, song: SongRender) -> None:
        if song.is_verified or not song.was_checked:
            return
        ledger.record_gap(
            PipelineStage.VERIFYING_NAME,
            NameVerificationExhaustedError(
                "no candidate orthography was heard back correctly",
                context={
                    "attempts": len(song.verdicts),
                    "strategy": None if song.candidate is None else song.candidate.strategy.value,
                },
            ),
            detail="the name may not be pronounced exactly as intended",
        )

    async def _advance_state(
        self, order: Order, state: OrderState, *, failed_reason: str | None = None
    ) -> None:
        """Persist one transition. Logs and swallows a write that did not land.

        A state the database missed is worth an incident, not an exception: the customer's
        song is unaffected by it, and raising here would replace a precise failure with a
        vague one. ``failed_reason`` is only ever non-``None`` on the way to ``FAILED``.
        """
        result = await self._repository.set_order_state(
            order.id, state, now=self._clock(), failed_reason=failed_reason
        )
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
        self, order: Order, reporter: ProgressReporter, error: HbdError, ledger: RunLedger
    ) -> Result[PipelineOutcome]:
        """End the run, leaving a legible reason on the order row.

        Before this recorded a reason, a content rejection and a vendor timeout were the
        same row in the database — state FAILED, ``failed_reason`` NULL — and telling them
        apart meant replaying the customer's brief against the model by hand. That is what
        the reason is for. Read the ``failed_reason`` banner at the top of this module
        before changing what goes into it.
        """
        await self._advance_state(
            order,
            OrderState.FAILED,
            failed_reason=_failed_reason(error, stage=_failed_stage(ledger)),
        )
        _LOGGER.error("order failed", extra={"order_id": str(order.id), **error.to_log_dict()})
        return err(error)


async def _validated(brief: Brief) -> Result[None]:
    """``_staged`` wants an awaitable; boundary validation is synchronous."""
    return validate_brief(brief)
