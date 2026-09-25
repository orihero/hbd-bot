"""The media stage chain: short, idempotent ARQ jobs in the existing worker (IMAGE_VIDEO_SPEC §3.3).

A song is one long job; a media request is a CHAIN of short ones, because a customer's image
can wait an hour for the GPU and a video renders for seventeen minutes, and neither may hold one
of the worker's fifteen slots (or its 900 s job timeout) while it waits. Each stage reads the
``media_jobs`` row, does one thing, moves the row with a conditional ``UPDATE`` and enqueues the
next stage::

    media_prescreen ─► (tray: shape | refusal | busy)       ← video ✅ Done, before payment
    media_screen ─► (tray: quote | refusal | busy)          ← before payment
    media_start ─► media_submit ×N ─► media_poll … ─► media_fetch ─► fan-in
        ─► media_output_screen ─► media_deliver ─► media_cleanup
    media_sweep (cron, 5 min) re-drives whatever a lost enqueue stranded, and fails the late

**Every stage is a no-op unless the row is where it expects** (§3.2.2 "State guards"). A move
that finds rowcount 0 means another path got there first — the deadline sweep, ``/forget``, an
output block — and the loser releases the GPU lock, discards what it holds, and never delivers
or refunds. That is also what makes a duplicate enqueue harmless: the second copy finds the row
already moved.

**A deliberate re-enqueue gets a NEW ARQ id** (``bayram.media.stages``): ``submit_seq`` for a
submit waiting on the GPU, the tick for a poll, ``oscreen_seq`` for an output screen waiting on
a guard. ARQ would silently drop the re-run otherwise, for the hour it keeps results.

**No POST is ever repeated for one attempt** (R7). ``media_submit`` writes the
``media_attempts`` row (``submitting``) before the POST; a worker killed between the two leaves
that row, and the re-run marks it ``ambiguous`` instead of posting again. **An ambiguous
attempt is reconciled before anything is resubmitted** (§4.2): on the GPU, ``GET /queue`` is
read and the slot stays held while the render may still be there; only once it is gone does
the retry policy try attempt N+1 (local cost is GPU time only). A backend that costs money
holds the job for an operator instead (§4.3).

**The GPU slot** (:mod:`bayram.runtime.gpu_lock`) is held by the attempt id from just before the
POST until ``media_fetch`` — which always releases it, CAS on the attempt id, even when it then
discards a late result.

**Screened bytes only** (§3.3). ``media_screen`` stores each upload once, EXIF-stripped and
re-encoded, and records its ``sha256``; everything after it reads that stored copy and checks
the hash. Nothing re-downloads by Telegram ``file_id``.

**Progress is DB-driven** (§3.3 "Progress"): ``media_start`` sends one status message, and the
waiting submit and each poll re-render it from the row and the GPU queue — editing only when
the queue position or the rounded-minute ETA changed, and at most once a minute. Delivery is a
new message, so it notifies.

**Video** shares submit/poll/fetch: its fetch normalises the clip with ffprobe/ffmpeg
(:mod:`bayram.media.mux`) into a ``video_raw`` output and sets ``render_ready_at``, while
``media_tts`` (an AI voice) or ``media_voice_prepare`` (an own note) runs beside the render
and sets ``audio_ready_at``. Whichever finishes second
fans in to ``media_mux``, once, by a conditional UPDATE; the output screen reads frames of the
muxed clip and the delivery sends it by ``sendVideo`` (a document above 50 MB).

Moderation goes through :class:`~bayram.moderation.contracts.MediaModerator` — the fake in tests,
``GatewayGuardModerator`` (G1, G2, G8) in production — and every ``Err`` from it is
``unavailable``: ``media.busy`` before payment, a two-minute retry after it (§6.4). Around it
this module owns what needs the row and Redis (§6.4, §6.7): the suspension check and the
per-account screening budget before anything is downloaded, L0 (caps and the denylist, no guard
call) before the guards, the youth signal carried from the words to the pictures, strikes on
every block, and the CSAM hard rule — the legal hold placed **in the same transaction as the
verdict**, the held bytes sealed to the escalation owner, the account suspended until an
operator clears it.
"""

from __future__ import annotations

import asyncio
import hashlib
import math
import shutil
from collections.abc import Awaitable, Callable, Collection, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import StrEnum
from pathlib import Path, PurePosixPath
from typing import Any, Final, Protocol
from uuid import UUID, uuid4

import sqlalchemy as sa
from aiogram import Bot
from aiogram.types import InlineKeyboardMarkup
from arq.worker import Retry
from PIL import Image, ImageOps, UnidentifiedImageError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from bayram.bot.delivery import BLOCKED_BY_CUSTOMER_KEY
from bayram.bot.i18n import translate
from bayram.bot.keyboards import (
    media_again_keyboard,
    media_busy_keyboard,
    media_quote_keyboard,
    media_refused_keyboard,
    media_script_review_keyboard,
    media_video_aspect_keyboard,
    media_voice_too_long_keyboard,
)
from bayram.bot.pricing import format_amount
from bayram.config import Settings
from bayram.contracts import (
    Err,
    HealthState,
    NarrationProvider,
    NarrationRequest,
    Result,
    Storage,
    VoiceGender,
    err,
    is_err,
    ok,
)
from bayram.db.base import utc_now
from bayram.db.credit_sql import rowcount_of
from bayram.db.enums import (
    MEDIA_TERMINAL_STATES,
    MediaAttemptStage,
    MediaAttemptStatus,
    MediaBackend,
    MediaCreditReason,
    MediaInputRole,
    MediaJobState,
    MediaKind,
    MediaOutputRole,
    MediaPaidVia,
    MediaReviewDecision,
    MediaReviewSource,
    MediaScreenDecision,
    MediaTier,
    MediaVoiceMode,
)
from bayram.db.media import (
    add_input,
    add_output,
    average_run_ms,
    bump_seq,
    cleanup_job_media,
    delete_inputs,
    find_attempt,
    grant_refund,
    has_standing_csam_block,
    insert_attempt,
    latest_attempts,
    list_inputs,
    list_outputs,
    load_job,
    media_balance,
    place_legal_hold,
    record_input_stored,
    record_output_file_id,
    set_attempt_status,
    stamp_input_backstop,
    touch_job,
    transition,
    update_draft,
)
from bayram.db.media_reviews import load_review, mark_applied, open_review
from bayram.db.models.media_attempt import MediaAttemptRow
from bayram.db.models.media_input import MediaInputRow, MediaOutputRow
from bayram.db.models.media_job import CSAM_BLOCKED_ERROR_CODE, MediaJobRow
from bayram.db.retention import RetentionPolicy, resolve_retention_policy
from bayram.errors import BayramError, ErrorCode, PipelineError, StorageError, ValidationError
from bayram.logging import get_logger
from bayram.media.composite import (
    COLLAGE_MIME,
    build_collage,
    needs_collage,
    target_size,
)
from bayram.media.contracts import (
    ATTEMPT_STATUS_FOR_PHASE,
    GatewayQueueReader,
    JobHandle,
    JobPhase,
    MediaGenProvider,
    MediaKindName,
    MediaRequest,
    QueuedJob,
    is_ambiguous,
)
from bayram.media.gate import QuoteBlock, quote_block
from bayram.media.mux import MAX_TEMPO, AudioFit, FfmpegVideoTools, VideoTools
from bayram.media.narration import fits_budget, is_voice_note_too_long, narration_budget
from bayram.media.offering import (
    effective_backend,
    is_beta_member,
    is_live_paid,
    media_offered,
)
from bayram.media.overrides import MediaSwitchStore, read_backend_override, read_overrides
from bayram.media.script_writer import GatewayScriptLlm, LlmScriptWriter, ScriptWriter
from bayram.media.service import MediaQueue, is_at_daily_cap
from bayram.media.stages import (
    MEDIA_CLEANUP_JOB,
    MEDIA_DELIVER_JOB,
    MEDIA_FETCH_JOB,
    MEDIA_MUX_JOB,
    MEDIA_OUTPUT_SCREEN_JOB,
    MEDIA_POLL_JOB,
    MEDIA_PRESCREEN_JOB,
    MEDIA_REVIEW_JOB,
    MEDIA_SCREEN_JOB,
    MEDIA_SCRIPT_JOB,
    MEDIA_START_JOB,
    MEDIA_SUBMIT_JOB,
    MEDIA_TTS_JOB,
    MEDIA_VOICE_PREPARE_JOB,
    cleanup_job_id,
    content_sha256,
    deliver_job_id,
    fetch_job_id,
    mux_job_id,
    output_screen_job_id,
    poll_job_id,
    sku_deadline,
    submit_job_id,
    tts_job_id,
    voice_prepare_job_id,
)
from bayram.media.voice_probe import FfmpegVoiceProbe, VoiceProbe
from bayram.moderation.contracts import (
    MEDIA_POLICY_VERSION,
    CategoryCode,
    ImageItem,
    MediaModerator,
    MediaVerdict,
    TextItem,
    lang_hint_for,
    strictest,
)
from bayram.moderation.factory import build_media_moderator
from bayram.moderation.legal_hold import SealReport, seal_held_objects
from bayram.moderation.lexicon import (
    NARRATION_MAX_CHARS,
    denylist_hits,
    has_youth_signal,
    is_within_caps,
)
from bayram.moderation.policy import apply_hard_rule, is_csam_class
from bayram.moderation.strikes import (
    CSAM_STRIKES,
    OUTPUT_BLOCK_STRIKES,
    PREPAY_BLOCK_STRIKES,
    RedisStrikeStore,
    StrikeStore,
    Suspension,
    SuspensionReason,
    record_block,
)
from bayram.moderation.voice import untrusted_transcript
from bayram.providers.media.factory import build_media_provider
from bayram.providers.media.local_gateway import CLIENT_TAG, MODEL_KINDS
from bayram.runtime.gpu_lock import (
    GPU_LOCK_ACQUIRE_TTL_MS,
    GpuSlotStore,
    RedisGpuSlotStore,
    queue_member,
    queue_score,
)
from bayram.runtime.media_telegram import TOO_LARGE_KEY, MediaMessenger, TelegramMediaMessenger
from bayram.storage import media_key

__all__ = [
    "MEDIA_CTX_KEY",
    "MEDIA_STAGE_MAX_TRIES",
    "GPU_BACKENDS",
    "MediaErrorCode",
    "MediaKV",
    "MediaRuntime",
    "ProviderCache",
    "media_runtime",
    "media_prescreen",
    "media_screen",
    "media_start",
    "media_submit",
    "media_poll",
    "media_fetch",
    "media_output_screen",
    "media_deliver",
    "media_cleanup",
    "media_review_apply",
    "fail_job",
    "reconcile_ambiguous",
    "image_fan_in",
    "video_fan_in",
    "enqueue_stage",
    "enqueue_submit",
    "enqueue_voice_stage",
    "media_script",
    "media_tts",
    "media_voice_prepare",
    "media_mux",
    "is_attempt_final",
    "media_workspace",
]

_LOG = get_logger(__name__)

#: Where a test (or a worker that built it already) keeps the stage chain's dependencies.
MEDIA_CTX_KEY: Final[str] = "media"
#: Restated rather than imported from ``bayram.runtime.jobs``, which imports THIS module to
#: register it — ``broadcast_job`` and ``activity_job`` do the same.
_CONTAINER_CTX_KEY: Final[str] = "container"
_BOT_CTX_KEY: Final[str] = "bot"
#: ARQ puts its own pool here before ``on_startup`` runs.
_REDIS_CTX_KEY: Final[str] = "redis"

#: Backends that render on the owner's one GPU and therefore take the slot (§3.4). The fake
#: stands in for the local gateway everywhere, the lock included, so the tests exercise it.
GPU_BACKENDS: Final[frozenset[MediaBackend]] = frozenset({MediaBackend.LOCAL, MediaBackend.FAKE})

#: §3.6: hard ceilings on a fetched result.
_RESULT_MAX_BYTES: Final[Mapping[MediaKind, int]] = {
    MediaKind.IMAGE: 20 * 1024 * 1024,
    MediaKind.VIDEO: 200 * 1024 * 1024,
}
#: The Bot API ``getFile`` ceiling, and so the largest upload there can be (§2.3.2).
_UPLOAD_MAX_BYTES: Final[int] = 20 * 1024 * 1024
#: A photo larger than this is refused before it is decoded (``composite``'s bound).
_MAX_SOURCE_PIXELS: Final[int] = 40_000_000
#: §3.3 ``media_deliver``: 2 photos, JPEG q92. Inputs are re-encoded at the same quality when
#: their metadata is stripped (§3.6).
_JPEG_QUALITY: Final[int] = 92
_JPEG_MIME: Final[str] = "image/jpeg"
#: Matte for a transparent upload, as in ``composite``.
_NEUTRAL: Final[tuple[int, int, int]] = (128, 128, 128)

#: A submit that is not at the head of the GPU queue tries again this much later (§3.4).
_WAIT_DEFER_S: Final[float] = 15.0
#: Poll cadence (§3.3 ``media_poll``).
_POLL_DEFER_S: Final[Mapping[MediaKind, float]] = {MediaKind.IMAGE: 5.0, MediaKind.VIDEO: 15.0}
#: ``unavailable`` at the output screen retries every 2 min for at most 30 (§6.4).
_OSCREEN_RETRY_S: Final[float] = 120.0
_OSCREEN_GIVE_UP: Final[timedelta] = timedelta(minutes=30)
#: The progress message is edited at most this often (§3.3 "Progress").
_PROGRESS_MIN_INTERVAL_S: Final[int] = 60
_PROGRESS_MEMO_TTL_S: Final[int] = 86_400
#: How long a ``submitting`` attempt with no lock and no remote id may be young before a re-run
#: treats it as a crash rather than as a sibling mid-POST (non-GPU backends only).
_SUBMITTING_GRACE: Final[timedelta] = timedelta(minutes=2)
#: Transport timeouts per call. Generous: each is one request, and a stage is a short job.
_SUBMIT_TIMEOUT_S: Final[float] = 60.0
_POLL_TIMEOUT_S: Final[float] = 20.0
_FETCH_TIMEOUT_S: Final[float] = 180.0
#: Before the first successful run there is no moving average; these are the measured
#: figures of ``RESEARCH-image-video-pipeline`` §1.3 (flux2 31–43 s; Wan ~17.5 min).
_DEFAULT_RUN_MS: Final[Mapping[MediaKind, int]] = {
    MediaKind.IMAGE: 40_000,
    MediaKind.VIDEO: 1_050_000,
}
#: An ambiguous attempt whose render may still be on the gateway is looked at again this often
#: (§4.2), holding the GPU slot meanwhile — renewed at the short acquire TTL each time, so a
#: reconciliation that stops (the job ended, the worker died) frees the slot on its own.
_RECONCILE_DEFER_S: Final[float] = 15.0
#: ``GET /queue`` is one small read; a gateway that cannot answer it in this long is busy.
_QUEUE_TIMEOUT_S: Final[float] = 10.0
#: Remote ids of attempts younger than this count as "ours" when the gateway's queue is read.
#: Older ``submitted`` rows belong to jobs the deadline ended long ago.
_OWN_REMOTE_WINDOW: Final[timedelta] = timedelta(days=1)
#: ARQ ``max_tries`` for every media stage, registered with this number in ``WorkerSettings``.
#: Only a fetch or a delivery raises ``Retry`` (a transient failure), and each reads this before
#: it does, so its last permitted try takes the terminal path instead of vanishing.
MEDIA_STAGE_MAX_TRIES: Final[int] = 3

_STAGE_FOR_KIND: Final[Mapping[MediaKind, MediaAttemptStage]] = {
    MediaKind.IMAGE: MediaAttemptStage.IMAGE,
    MediaKind.VIDEO: MediaAttemptStage.VIDEO,
}
_WORKING_STATES: Final[tuple[MediaJobState, ...]] = (
    MediaJobState.QUEUED,
    MediaJobState.GENERATING,
)
_KIND_LABEL_KEYS: Final[Mapping[MediaKind, str]] = {
    MediaKind.IMAGE: "media.kind.image",
    MediaKind.VIDEO: "media.kind.video",
}

# The customer-facing keys this module renders, named ``*_KEY`` so the locale contract test
# finds them.
_QUOTE_KEY: Final[str] = "media.image.quote"
_REFUSED_KEY: Final[str] = "media.refused"
_SUSPENDED_KEY: Final[str] = "media.refused.suspended"
_DAILY_CAP_KEY: Final[str] = "media.daily_cap"
_UNSUPPORTED_KEY: Final[str] = "media.compose.unsupported"
_BUSY_KEY: Final[str] = "media.busy"
#: ``_screen_gate``'s outcome when the strike store could not be read (fail closed).
_GATE_UNREADABLE: Final[str] = "busy_strikes_unreadable"
_QUEUED_KEY: Final[str] = "media.progress.queued"
_QUEUED_FREE_KEY: Final[str] = "media.progress.queued_free"
_RENDERING_KEY: Final[str] = "media.progress.rendering"
_DELIVERED_KEY: Final[str] = "media.image.delivered"
_VIDEO_DELIVERED_KEY: Final[str] = "media.video.delivered"
_AGAIN_KEY: Final[str] = "media.delivered.again"
_PARTIAL_KEY: Final[str] = "media.image.partial"
_PARTIAL_REFUNDED_KEY: Final[str] = "media.image.partial_refunded"
_FAILED_REFUNDED_KEY: Final[str] = "media.failed.refunded"
_FAILED_BETA_KEY: Final[str] = "media.failed.beta"
_FAILED_KEY: Final[str] = "media.failed"
_ETA_MINUTES_KEY: Final[str] = "media.eta.minutes"
_VIDEO_QUOTE_KEY: Final[str] = "media.video.quote"
_ASPECT_KEY: Final[str] = "media.aspect"
_VOICE_TOO_LONG_KEY: Final[str] = "media.voice_note.too_long"
_SCRIPT_REVIEW_KEY: Final[str] = "media.voice.script_review"
_SCRIPT_FAILED_KEY: Final[str] = "media.voice.script_failed"
_TIER_STANDARD_KEY: Final[str] = "media.tier_name.standard"
_TIER_FAST_KEY: Final[str] = "media.tier_name.fast"
_TIER_NAME_KEYS: Final[Mapping[MediaTier, str]] = {
    MediaTier.STANDARD: _TIER_STANDARD_KEY,
    MediaTier.FAST: _TIER_FAST_KEY,
}
_VOICE_NONE_KEY: Final[str] = "media.voice_mode.none"
_VOICE_AI_USER_KEY: Final[str] = "media.voice_mode.ai_user"
_VOICE_AI_LLM_KEY: Final[str] = "media.voice_mode.ai_llm"
_VOICE_OWN_KEY: Final[str] = "media.voice_mode.own"
_VOICE_MODE_NAME_KEYS: Final[Mapping[MediaVoiceMode, str]] = {
    MediaVoiceMode.NONE: _VOICE_NONE_KEY,
    MediaVoiceMode.AI_USER: _VOICE_AI_USER_KEY,
    MediaVoiceMode.AI_LLM: _VOICE_AI_LLM_KEY,
    MediaVoiceMode.OWN: _VOICE_OWN_KEY,
}
#: An own voice note (§5.4): stored as Telegram sent it (OGG/Opus), muxed as-is — never
#: re-encoded between screening and use (§3.3 "Screened bytes only").
_VOICE_NOTE_FILENAME: Final[str] = "voice-0.ogg"
_VOICE_NOTE_MIME: Final[str] = "audio/ogg"
#: Five seconds of Opus is kilobytes; this refuses something that is not a voice note at all.
_VOICE_NOTE_MAX_BYTES: Final[int] = 2 * 1024 * 1024
#: ``media_jobs.voice_transcript`` is varchar(400) (§3.2.2).
_TRANSCRIPT_MAX_CHARS: Final[int] = 400
#: The video's files (§3.6): the normalised render, the voice track, the delivered clip.
_VIDEO_RAW_FILENAME: Final[str] = "video-raw.mp4"
_VIDEO_FILENAME: Final[str] = "video.mp4"
_NARRATION_FILENAME: Final[str] = "narration.wav"
_VIDEO_MIME: Final[str] = "video/mp4"
_WAV_MIME: Final[str] = "audio/wav"
#: A narration's file suffix by the MIME its vendor answered with (§5.2: Gemini's WAV, the
#: ElevenLabs fallback's MP3), so the stored object and its ``media_outputs`` row say what the
#: bytes are. Anything else keeps ``.wav``'s place with the vendor's own MIME.
_NARRATION_SUFFIX_BY_MIME: Final[Mapping[str, str]] = {
    "audio/wav": ".wav",
    "audio/x-wav": ".wav",
    "audio/wave": ".wav",
    "audio/mpeg": ".mp3",
    "audio/mp3": ".mp3",
    "audio/ogg": ".ogg",
    "audio/opus": ".opus",
    "audio/flac": ".flac",
}
#: One narration call (§5.1): a unary WAV of five seconds.
_NARRATION_TIMEOUT_S: Final[float] = 60.0
#: §5.3: the delivery asked for when a line runs past what ``atempo`` absorbs.
_BRISK_STYLE: Final[str] = "brisk"
#: The muxed clip may differ from the render by an AAC frame or two, never more.
_MUX_DURATION_SLACK_S: Final[float] = 0.15


class MediaErrorCode(StrEnum):
    """``media_jobs.error_code`` values this module writes. Closed; ≤ 48 characters."""

    SCREEN_REFUSED = "screen_refused"
    UNSUPPORTED_INPUT = "unsupported_input"
    GENERATION_FAILED = "generation_failed"
    DEADLINE = "deadline"
    OUTPUT_BLOCKED = "output_blocked"
    SCREEN_STALE = "screen_stale"
    NOT_ENTITLED = "not_entitled"
    FORGET_REQUESTED = "forget_requested"
    CUSTOMER_BLOCKED = "customer_blocked"
    DELIVERY_FAILED = "delivery_failed"
    CRASHED_BEFORE_POST = "crashed_before_post"
    RENDER_TIMEOUT = "render_timeout"
    FETCH_FAILED = "fetch_failed"
    INPUT_CHANGED = "input_changed"
    AMBIGUOUS_SUBMIT = "ambiguous_submit"
    #: §6.4: refused before screening — the account is suspended, or spent today's budget.
    SCREEN_SUSPENDED = "screen_suspended"
    SCREEN_BUDGET = "screen_budget"
    #: §7.6: the account already started today's paid requests of this kind. Refused before
    #: a byte is downloaded or a guard asked, and never a strike.
    DAILY_CAP = "daily_cap"
    #: §6.4 hard rule / §6.7: a CSAM-class block. The bytes are under legal hold, and the
    #: row, until an operator clears it, is the account's durable suspension.
    CSAM_BLOCKED = CSAM_BLOCKED_ERROR_CODE
    #: §1.3 / §6.4 L0: over the length or word cap. A refusal, never a strike — the length
    #: of a description is not a judgement on its content.
    SCREEN_CAPS = "screen_caps"
    #: §6.6: an operator confirmed a held output's block, or nobody decided within 24 h.
    REVIEW_BLOCKED = "review_blocked"
    REVIEW_EXPIRED = "review_expired"
    #: A ``held`` job with no review to end it (a paid-backend ``ambiguous_submit`` hold, or
    #: one from before revision 0032), failed by ``media_sweep`` after two hours (§4.3).
    HELD_UNRESOLVED = "held_unresolved"
    #: §5.4: whisper's transcript of an own voice note did not read as real speech, so the
    #: note could not be screened. A ``review`` refusal, never a strike.
    VOICE_UNTRUSTED = "voice_untrusted"
    #: §6.4 L5: the TTS vendor refused the line on content grounds. Final: refund + strike.
    NARRATION_REFUSED = "narration_refused"
    #: §5.1: no voice could be made (every route and the fallback failed, or none is wired).
    NARRATION_FAILED = "narration_failed"
    #: §5.4: the stored own voice note could not be read or prepared.
    VOICE_PREPARE_FAILED = "voice_prepare_failed"
    #: §5.6: ffmpeg could not mux or re-wrap the clip.
    MUX_FAILED = "mux_failed"


class MediaKV(Protocol):
    """Two Redis commands for the progress memo. ``ArqRedis`` satisfies it."""

    async def get(self, name: str) -> Any: ...

    async def set(self, name: str, value: str, *, ex: int | None = None) -> Any: ...


class ProviderCache:
    """One adapter per backend for the worker's lifetime, built on first use."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._built: dict[MediaBackend, MediaGenProvider] = {}

    def __call__(self, backend: MediaBackend) -> MediaGenProvider:
        provider = self._built.get(backend)
        if provider is None:
            provider = build_media_provider(self._settings, backend)
            self._built[backend] = provider
        return provider


@dataclass(frozen=True, slots=True)
class MediaRuntime:
    """Everything a stage needs. Built once per worker (:func:`media_runtime`), or by a test."""

    settings: Settings
    sessions: async_sessionmaker[AsyncSession]
    storage: Storage
    workspace_root: Path
    messenger: MediaMessenger
    moderator: MediaModerator
    providers: Callable[[MediaBackend], MediaGenProvider]
    gpu: GpuSlotStore
    switches: MediaSwitchStore
    memo: MediaKV
    queue: MediaQueue
    strikes: StrikeStore
    clock: Callable[[], datetime] = field(default=utc_now)
    #: ffprobe + silencedetect on an own voice note (§5.4); a fake in tests.
    voice_probe: VoiceProbe = field(default_factory=FfmpegVoiceProbe)
    #: ffprobe/ffmpeg for a video: normalise, prepare a note, mux, frames (§5.6); a fake in tests.
    video: VideoTools = field(default_factory=FfmpegVideoTools)
    #: The video voice (§5.1, §5.2). ``None`` is "not wired": a narration fails the job with a
    #: refund rather than guessing a voice.
    narration: NarrationProvider | None = None
    #: 🤖 "AI writes" (§5.5). ``None`` answers the tray that no line could be written.
    script_writer: ScriptWriter | None = None


def media_runtime(ctx: Mapping[str, Any]) -> MediaRuntime:
    """The runtime in ``ctx``, building and caching it from the worker's own on first use."""
    found = ctx.get(MEDIA_CTX_KEY)
    if isinstance(found, MediaRuntime):
        return found
    # Imported here: ``runtime.container`` is the heavy half of the graph, and a test that
    # injects a runtime never needs it.
    from bayram.runtime.container import AppContainer

    container = ctx.get(_CONTAINER_CTX_KEY)
    bot = ctx.get(_BOT_CTX_KEY)
    redis = ctx.get(_REDIS_CTX_KEY)
    if not isinstance(container, AppContainer) or not isinstance(bot, Bot) or redis is None:
        raise PipelineError(
            "worker context is missing what the media stages need",
            context={
                "container": type(container).__name__,
                "bot": type(bot).__name__,
                "redis": type(redis).__name__,
            },
        )
    settings = container.settings
    runtime = MediaRuntime(
        settings=settings,
        sessions=container.require_session_factory(),
        storage=container.storage,
        workspace_root=container.workspace_root,
        messenger=TelegramMediaMessenger(bot),
        moderator=build_media_moderator(settings),
        providers=ProviderCache(settings),
        gpu=RedisGpuSlotStore(redis),
        switches=redis,
        memo=redis,
        queue=redis,
        strikes=RedisStrikeStore(redis),
        voice_probe=FfmpegVoiceProbe(
            ffprobe_binary=settings.ffprobe_binary, ffmpeg_binary=settings.ffmpeg_binary
        ),
        video=FfmpegVideoTools(
            ffmpeg_binary=settings.ffmpeg_binary,
            ffprobe_binary=settings.ffprobe_binary,
            timeout_s=settings.ffmpeg_timeout_s,
        ),
        narration=_build_narration(settings, container.require_session_factory(), redis),
        script_writer=_build_script_writer(settings, container),
    )
    if isinstance(ctx, dict):
        ctx[MEDIA_CTX_KEY] = runtime
    return runtime


def _build_narration(
    settings: Settings, sessions: async_sessionmaker[AsyncSession], redis: Any
) -> NarrationProvider:
    """The narration table over the Gemini key pool, ElevenLabs behind it (§5.1, §5.2)."""
    # Imported here for the reason ``AppContainer`` is: the vendor half of the graph.
    import httpx

    from bayram.db.vendor_usage import DbUsageSink
    from bayram.providers.tts.key_pool import RedisKeyPoolStore
    from bayram.runtime.providers import build_narration_provider

    return build_narration_provider(
        settings,
        store=RedisKeyPoolStore(redis),
        client=httpx.AsyncClient(),
        usage=DbUsageSink(sessions),
    )


def _build_script_writer(settings: Settings, container: Any) -> ScriptWriter:
    """The gateway's local LLM first, the D5 stack behind it (§5.5)."""
    gateway = (
        GatewayScriptLlm(
            base_url=settings.genai_base_url,
            api_key=settings.genai_api_key,
            model_id=settings.genai_script_model,
            access_client_id=settings.genai_access_client_id,
            access_client_secret=settings.genai_access_client_secret,
        )
        if settings.genai_base_url.strip() and not settings.use_fake_providers
        else None
    )
    providers = getattr(container, "providers", None)
    fallbacks = (
        [p for p in (providers.llm, providers.llm_fallback) if p is not None]
        if providers is not None
        else []
    )
    return LlmScriptWriter(
        gateway=gateway,
        fallbacks=fallbacks,
        gateway_timeout_s=settings.genai_script_timeout_s,
    )


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------
def _uuid(value: str) -> UUID:
    try:
        return UUID(value)
    except ValueError as exc:
        raise PipelineError(
            "a media stage was queued with a job id that is not a UUID",
            context={"media_job_id": value},
            cause=exc,
        ) from exc


def _result(outcome: str, job_id: UUID | str, **extra: Any) -> dict[str, Any]:
    """The JSON-safe dict ARQ keeps as the job result — and the log line."""
    summary = {"outcome": outcome, "media_job_id": str(job_id), **extra}
    _LOG.info("media stage finished", extra=summary)
    return summary


def media_workspace(rt: MediaRuntime, job_id: UUID) -> Path:
    """``var/workspace/media/{job_id}/`` (§3.6), swept by ``workspace_sweep`` once terminal."""
    return rt.workspace_root / "media" / str(job_id)


def _stage(kind: MediaKind) -> MediaAttemptStage:
    return _STAGE_FOR_KIND[kind]


def _kind_name(kind: MediaKind) -> MediaKindName:
    return "image" if kind is MediaKind.IMAGE else "video"


def _render_timeout_s(rt: MediaRuntime, kind: MediaKind) -> int:
    if kind is MediaKind.IMAGE:
        return rt.settings.media_image_render_timeout_s
    return rt.settings.media_video_render_timeout_s


def _backend(job: MediaJobRow) -> MediaBackend:
    """The backend ``media_start`` stamped. A working row without one is a bug, never a
    reason to guess — a guess could route a paid render to the fake."""
    if job.backend is None:
        raise PipelineError(
            "a working media job carries no backend", context={"media_job_id": str(job.id)}
        )
    return job.backend


def _members(job: MediaJobRow) -> tuple[str, ...]:
    return tuple(queue_member(job.id, variant) for variant in range(job.outputs_requested))


def is_attempt_final(row: MediaAttemptRow, max_attempts: int) -> bool:
    """The variant this attempt belongs to will get no further attempt."""
    if row.status is MediaAttemptStatus.REJECTED:
        return True
    return (
        row.status in (MediaAttemptStatus.FAILED, MediaAttemptStatus.AMBIGUOUS)
        and row.attempt >= max_attempts
    )


async def enqueue_stage(
    rt: MediaRuntime, name: str, *args: Any, job_id: str, defer_s: float = 0.0
) -> bool:
    """Enqueue one stage. A lost enqueue is logged, never raised: the sweep re-drives it."""
    try:
        await rt.queue.enqueue_job(name, *args, _job_id=job_id, _defer_by=defer_s)
    except Exception as exc:
        _LOG.warning(
            "a media stage could not be enqueued; media_sweep will re-drive it",
            extra={"job": name, "arq_job_id": job_id, "failure": repr(exc)},
        )
        return False
    return True


async def _gpu_call[T](what: str, call: Awaitable[T], default: T) -> T:
    """A GPU-store call that must not take a stage down. Redis failing is logged and the
    stage continues on ``default`` — the lock's own TTL is the backstop (§3.4)."""
    try:
        return await call
    except Exception as exc:
        _LOG.warning("a GPU slot call failed", extra={"call": what, "failure": repr(exc)})
        return default


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1 << 16):
            digest.update(chunk)
    return digest.hexdigest()


def _to_clean_jpeg(src: Path, dest: Path) -> tuple[int, int] | ValidationError:
    """Decode ``src`` as ONE still image, apply its orientation, drop every metadata segment,
    write JPEG q92 to ``dest``. The width and height, or why the file is refused.

    A multi-frame file (animated WebP/APNG, a GIF sent as a document) is refused, never
    flattened to its first frame (§3.3 ``media_screen``) — an unscreened frame must have
    nowhere to hide. The new image inherits no EXIF, GPS or ICC data (§3.6).
    """
    try:
        with Image.open(src) as opened:
            if getattr(opened, "n_frames", 1) > 1:
                return ValidationError("a multi-frame image is not a photo", context={"frames": 2})
            width, height = opened.size
            if width * height > _MAX_SOURCE_PIXELS:
                return ValidationError(
                    "the image is larger than a media input may be",
                    context={"pixels": width * height},
                )
            upright = ImageOps.exif_transpose(opened)
            if upright.mode in ("RGBA", "LA", "P"):
                rgba = upright.convert("RGBA")
                canvas = Image.new("RGB", rgba.size, _NEUTRAL)
                canvas.paste(rgba, mask=rgba.getchannel("A"))
                clean = canvas
            else:
                clean = upright.convert("RGB")
            fresh = Image.new("RGB", clean.size)
            fresh.paste(clean)
            staging = dest.with_suffix(dest.suffix + ".part")
            dest.parent.mkdir(parents=True, exist_ok=True)
            fresh.save(staging, format="JPEG", quality=_JPEG_QUALITY)
            staging.replace(dest)
            return fresh.size
    except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError) as exc:
        return ValidationError(
            "the file is not an image we can decode", context={"failure": type(exc).__name__}
        )


async def _materialise(
    rt: MediaRuntime, *, key: str, sha256: str | None, dest: Path
) -> Result[Path]:
    """The screened object at ``key``, on local disk and verified against ``sha256`` (§3.3).

    Images only: the bytes pass through memory once, which is fine at ≤ 20 MB. A video input
    (M4) needs the streaming path (``Storage.open_range``) instead.
    """
    if (
        dest.exists()
        and sha256 is not None
        and await asyncio.to_thread(_sha256_file, dest) == sha256
    ):
        return ok(dest)
    fetched = await rt.storage.get(key)
    if is_err(fetched):
        return fetched
    data = fetched.value
    if sha256 is not None and hashlib.sha256(data).hexdigest() != sha256:
        return err(
            StorageError(
                "a stored media object no longer matches the hash it was screened with",
                context={"key": key},
            )
        )
    dest.parent.mkdir(parents=True, exist_ok=True)
    await asyncio.to_thread(dest.write_bytes, data)
    return ok(dest)


async def _materialise_file(
    rt: MediaRuntime, *, key: str, sha256: str | None, dest: Path
) -> Result[Path]:
    """:func:`_materialise` for a video or its voice: streamed to disk through
    ``Storage.open_range`` and hashed on the way, never held in memory (§3.6)."""
    if (
        dest.exists()
        and sha256 is not None
        and await asyncio.to_thread(_sha256_file, dest) == sha256
    ):
        return ok(dest)
    size = await rt.storage.size(key)
    if is_err(size):
        return size
    if size.value <= 0:
        return err(StorageError("a stored media object is empty", context={"key": key}))
    opened = await rt.storage.open_range(key, start=0, end=size.value - 1)
    if is_err(opened):
        return opened
    stream = opened.value
    digest = hashlib.sha256()
    part = dest.with_name(f"{dest.name}.part")
    dest.parent.mkdir(parents=True, exist_ok=True)
    try:
        with part.open("wb") as handle:
            async for chunk in stream:
                digest.update(chunk)
                handle.write(chunk)
    except OSError as exc:
        part.unlink(missing_ok=True)
        return err(
            StorageError(
                "a stored media object could not be copied to the workspace",
                context={"key": key, "failure": type(exc).__name__},
                cause=exc,
            )
        )
    finally:
        closer = getattr(stream, "aclose", None)
        if closer is not None:
            await closer()
    if sha256 is not None and digest.hexdigest() != sha256:
        part.unlink(missing_ok=True)
        return err(
            StorageError(
                "a stored media object no longer matches the hash it was screened with",
                context={"key": key},
            )
        )
    part.replace(dest)
    return ok(dest)


def _take_name(filename: str) -> str:
    """``narration.wav`` → ``narration-1a2b3c4d.wav``: one run's own file and object key, so
    two runs of a stage (a sweep re-drive beside a slow first run) never share one."""
    stem, dot, suffix = filename.rpartition(".")
    return f"{stem}-{uuid4().hex[:8]}{dot}{suffix}"


def _translate(job: MediaJobRow, key: str, **params: Any) -> str:
    return translate(key, job.language, **params)


def _eta_text(job: MediaJobRow, minutes: int) -> str:
    return _translate(job, _ETA_MINUTES_KEY, minutes=max(1, minutes))


async def _show_tray(
    rt: MediaRuntime, job: MediaJobRow, text: str, markup: InlineKeyboardMarkup | None
) -> None:
    """Turn the compose tray into ``text`` — or, with no tray on the row, send it anew."""
    if job.tray_message_id is not None and await rt.messenger.edit(
        job.chat_id, job.tray_message_id, text, markup
    ):
        return
    await rt.messenger.send(job.chat_id, text, markup)


async def _average_run_ms(rt: MediaRuntime, job: MediaJobRow) -> int:
    return await _model_run_ms(rt, job.kind, job.model_id)


async def _model_run_ms(rt: MediaRuntime, kind: MediaKind, model_id: str | None) -> int:
    async with rt.sessions() as session:
        measured = await average_run_ms(session, stage=_stage(kind), model_id=model_id)
    return measured if measured is not None else _DEFAULT_RUN_MS[kind]


def _policy(rt: MediaRuntime) -> RetentionPolicy:
    """The retention clocks as configured (``BAYRAM_RETENTION_MEDIA_OUTPUT_DAYS``, §9.5)."""
    return resolve_retention_policy(rt.settings)


# ---------------------------------------------------------------------------
# The gateway's own queue (§3.4, §4.2)
# ---------------------------------------------------------------------------
async def _gateway_queue(provider: MediaGenProvider) -> Result[tuple[QueuedJob, ...]]:
    """What the GPU backend reports running or pending. A backend that cannot list its
    queue has nothing on it that bayram did not put there (the fake in a test of another
    seam); every real GPU backend implements :class:`GatewayQueueReader`."""
    if not isinstance(provider, GatewayQueueReader):
        return ok(())
    return await provider.queued_jobs(timeout_s=_QUEUE_TIMEOUT_S)


async def _own_remote_ids(rt: MediaRuntime) -> frozenset[str]:
    """The gateway ids of bayram's live attempts — what is NOT an orphan or a stranger."""
    cutoff = rt.clock() - _OWN_REMOTE_WINDOW
    async with rt.sessions() as session:
        rows = await session.scalars(
            sa.select(MediaAttemptRow.remote_id).where(
                MediaAttemptRow.status == MediaAttemptStatus.SUBMITTED,
                MediaAttemptRow.remote_id.is_not(None),
                MediaAttemptRow.created_at > cutoff,
            )
        )
        return frozenset(remote_id for remote_id in rows.all() if remote_id is not None)


def _foreign_kind(entry: QueuedJob) -> MediaKind:
    """How long a non-bayram entry holds the GPU, read from its model. An entry whose model
    is not reported is assumed to be a video: overstating the ETA costs a ``busy`` screen,
    understating it costs a deadline refund (NFR-20)."""
    model = (entry.model or "").lower()
    if not model:
        return MediaKind.VIDEO
    if MODEL_KINDS.get(model) == "image":
        return MediaKind.IMAGE
    return MediaKind.VIDEO if any(tag in model for tag in ("wan", "hunyuan")) else MediaKind.IMAGE


async def _foreign_backlog_ms(rt: MediaRuntime, provider: MediaGenProvider) -> int | None:
    """§3.4: the gateway's own depth of non-bayram jobs, as GPU milliseconds — each entry at
    the moving average of its model (Wan versus flux2). ``None`` when the queue is unreadable.

    Until gateway change G5 gives customers priority, marketing renders queued there run
    ahead of every customer job, so they are part of the customer's wait.
    """
    listed = await _gateway_queue(provider)
    if is_err(listed):
        return None
    own = await _own_remote_ids(rt)
    foreign = [
        entry for entry in listed.value if entry.client != CLIENT_TAG and entry.job_id not in own
    ]
    if not foreign:
        return 0
    per_kind = {
        MediaKind.IMAGE: await _model_run_ms(rt, MediaKind.IMAGE, rt.settings.genai_image_model),
        MediaKind.VIDEO: await _model_run_ms(rt, MediaKind.VIDEO, rt.settings.genai_video_model),
    }
    return sum(per_kind[_foreign_kind(entry)] for entry in foreign)


# ---------------------------------------------------------------------------
# Failure: the one path every stage takes to end a paid job badly
# ---------------------------------------------------------------------------
async def fail_job(
    rt: MediaRuntime,
    job_id: UUID,
    *,
    expected: Iterable[MediaJobState],
    error_code: MediaErrorCode,
    refund: MediaCreditReason | None,
    notify: bool = True,
    values: Mapping[str, Any] | None = None,
    legal_hold: bool = False,
    refund_actor: str | None = None,
) -> bool:
    """Move the job to ``failed`` iff it is in ``expected``; refund, tell, clean up. True if moved.

    The refund rides the same transaction as the move, and ``grant_refund`` grants at most one
    credit per job whatever the reason (§3.2.2) and none for a beta job (§7.5) — so a deadline
    followed by a late generation failure, or a variant failure followed by an output block,
    is one credit. A caller that loses the move does nothing else.

    ``legal_hold`` puts the job's inputs and outputs under hold in the SAME transaction as the
    move (§6.7), so the cleanup this enqueues can never reach them. ``refund_actor`` attributes
    the credit on the ledger when an operator's decision caused it (§6.6); the worker otherwise.
    """
    now = rt.clock()
    granted = False
    async with rt.sessions.begin() as session:
        moved = await transition(
            session,
            job_id,
            expected=tuple(expected),
            to=MediaJobState.FAILED,
            now=now,
            values={"error_code": error_code.value, **dict(values or {})},
            policy=_policy(rt),
        )
        if not moved:
            return False
        if legal_hold:
            await place_legal_hold(session, job_id, now=now, policy=_policy(rt))
        if refund is not None:
            # ``grant_refund`` refuses a job whose account asked to be forgotten (§9.3): a
            # credit would re-create the balance row and the ledger line /forget just erased.
            granted = await grant_refund(
                session, job_id, reason=refund, now=now, actor=refund_actor
            )
        job = await load_job(session, job_id)
    if job is None:
        return True
    await _gpu_call("leave", rt.gpu.leave(*_members(job)), None)
    if notify and job.forget_requested_at is None:
        await rt.messenger.send(job.chat_id, _failure_text(job, granted=granted), _again(job))
    await enqueue_stage(rt, MEDIA_CLEANUP_JOB, str(job_id), job_id=cleanup_job_id(job_id))
    _LOG.info(
        "a media job failed",
        extra={"media_job_id": str(job_id), "error_code": error_code.value, "refunded": granted},
    )
    return True


def _failure_text(job: MediaJobRow, *, granted: bool) -> str:
    if job.paid_via is MediaPaidVia.BETA:
        return _translate(job, _FAILED_BETA_KEY)
    if granted:
        kind = _translate(job, _KIND_LABEL_KEYS[job.kind])
        return _translate(job, _FAILED_REFUNDED_KEY, kind=kind)
    return _translate(job, _FAILED_KEY)


def _again(job: MediaJobRow) -> InlineKeyboardMarkup:
    return media_again_keyboard(job.language, job.id)


# ---------------------------------------------------------------------------
# Strikes and the hard rule (§6.4, §6.7)
# ---------------------------------------------------------------------------
async def _strike(
    rt: MediaRuntime,
    job: MediaJobRow,
    *,
    layer: str,
    weight: int,
    is_csam: bool,
) -> None:
    """Strike the account for one block. A Redis failure is logged, never fatal: the block
    itself has already been recorded on the row, and a lost strike is a lost rate limit."""
    try:
        suspended = await record_block(
            rt.strikes,
            job.telegram_user_id,
            event_id=f"{job.id}:{layer}",
            weight=weight,
            is_csam=is_csam,
            now=rt.clock(),
        )
    except Exception as exc:  # the store raises on Redis failure; strikes are best-effort
        _LOG.warning(
            "a media strike could not be recorded",
            extra={"media_job_id": str(job.id), "failure": type(exc).__name__},
        )
        return
    if suspended is not None:
        _LOG.warning(
            "media is suspended for an account",
            extra={"media_job_id": str(job.id), "reason": suspended.reason.value},
        )


async def _escalate_csam(
    rt: MediaRuntime, job: MediaJobRow, *, layer: str, categories: Sequence[CategoryCode]
) -> None:
    """§6.7: the bytes are held (already, in the verdict's transaction); seal them to the
    escalation owner and raise the alarm. The log line carries the job id, the layer and the
    closed codes — never content, never a user-visible string. The escalation owner records
    a reporting decision within ``legal_hold_expires_at`` (72 h).

    The suspension comes FIRST: the row has already moved to a terminal state, so nothing
    retries this, and a sealing failure must not be what skips it. (Should Redis lose it
    anyway, the ``csam_blocked`` row itself refuses the account at the screen gate.) A seal
    that raises is logged; ``media_cleanup`` seals again.
    """
    await _strike(rt, job, layer=layer, weight=CSAM_STRIKES, is_csam=True)
    try:
        report = await seal_held_objects(
            rt.sessions,
            rt.storage,
            job.id,
            public_key=rt.settings.media_legal_hold_recipient,
        )
    except Exception as exc:  # cleanup re-seals; the escalation line below must still go out
        _LOG.error(
            "legal-hold bytes could not be sealed; media_cleanup will try again",
            extra={"media_job_id": str(job.id), "failure": type(exc).__name__},
        )
        report = SealReport(sealed=0, already=0, failed=1)
    _LOG.error(
        "CSAM-class media block: bytes held for the escalation owner",
        extra={
            "escalation": "csam",
            "media_job_id": str(job.id),
            "layer": layer,
            "categories": [code.value for code in categories],
            "sealed": report.sealed + report.already,
            "seal_failed": report.failed,
        },
    )


def _youth_in_words(job: MediaJobRow) -> bool:
    """The youth signal from the request's own words (§6.4 item 1), for the image layers."""
    return has_youth_signal(
        [text for text in (job.prompt, job.narration_text, job.voice_transcript) if text]
    )


# ---------------------------------------------------------------------------
# media_screen (§3.3): bytes in, verdict, quote | refusal | busy
# ---------------------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class _Screened:
    """One stored, screened input on local disk."""

    role: MediaInputRole
    ordinal: int
    path: Path
    sha256: str


async def _store_upload(
    rt: MediaRuntime, job: MediaJobRow, row: MediaInputRow, workdir: Path
) -> Result[_Screened]:
    """Download one photo, normalise it, store it and record its hash. Idempotent."""
    filename = f"photo-{row.ordinal}.jpg"
    local = workdir / filename
    if row.storage_key is not None and row.sha256 is not None:
        found = await _materialise(rt, key=row.storage_key, sha256=row.sha256, dest=local)
        if is_err(found):
            return found
        return ok(_Screened(row.role, row.ordinal, local, row.sha256))
    if row.tg_file_id is None:
        return err(ValidationError("an upload row carries no Telegram file id"))
    raw = workdir / f"raw-{row.ordinal}"
    downloaded = await rt.messenger.download(row.tg_file_id, raw, max_bytes=_UPLOAD_MAX_BYTES)
    if is_err(downloaded):
        return downloaded
    clean = await asyncio.to_thread(_to_clean_jpeg, raw, local)
    raw.unlink(missing_ok=True)
    if isinstance(clean, ValidationError):
        return err(clean)
    stored = await rt.storage.put_file(
        media_key(job.id, is_output=False, filename=filename), local, content_type=_JPEG_MIME
    )
    if is_err(stored):
        return stored
    width, height = clean
    async with rt.sessions.begin() as session:
        await record_input_stored(
            session,
            row.id,
            storage_key=stored.value.key,
            mime=_JPEG_MIME,
            size_bytes=stored.value.size_bytes,
            sha256=stored.value.sha256,
            width=width,
            height=height,
        )
    return ok(_Screened(row.role, row.ordinal, local, stored.value.sha256))


async def _store_collage(
    rt: MediaRuntime,
    job: MediaJobRow,
    photos: Sequence[_Screened],
    existing: MediaInputRow | None,
    workdir: Path,
) -> Result[_Screened]:
    """Several photos on a one-reference backend → one collage input (§4.4). Idempotent."""
    local = workdir / "collage-0.jpg"
    if existing is not None and existing.storage_key is not None and existing.sha256 is not None:
        found = await _materialise(rt, key=existing.storage_key, sha256=existing.sha256, dest=local)
        if is_err(found):
            return found
        return ok(_Screened(MediaInputRole.COLLAGE, 0, local, existing.sha256))
    width, height = target_size(_kind_name(job.kind), job.aspect)
    built = await asyncio.to_thread(
        build_collage, [photo.path for photo in photos], local, width=width, height=height
    )
    if is_err(built):
        return built
    stored = await rt.storage.put_file(
        media_key(job.id, is_output=False, filename=local.name), local, content_type=COLLAGE_MIME
    )
    if is_err(stored):
        return stored
    now = rt.clock()
    async with rt.sessions.begin() as session:
        input_id = (
            existing.id
            if existing is not None
            else await add_input(
                session, job_id=job.id, ordinal=0, role=MediaInputRole.COLLAGE, now=now
            )
        )
        await record_input_stored(
            session,
            input_id,
            storage_key=stored.value.key,
            mime=COLLAGE_MIME,
            size_bytes=stored.value.size_bytes,
            sha256=stored.value.sha256,
            width=width,
            height=height,
        )
    return ok(_Screened(MediaInputRole.COLLAGE, 0, local, stored.value.sha256))


async def _screen(
    rt: MediaRuntime, job: MediaJobRow, inputs: Sequence[_Screened]
) -> tuple[MediaScreenDecision, tuple[CategoryCode, ...]]:
    """L0, then L1/L2 through the moderator, then the hard rule (§6.4). Fail closed.

    L0 here is the denylist over the words, and a hit is a block with **no guard call**; the
    length caps ran earlier (:func:`_over_caps`), since a length is not a verdict. Any ``Err``
    from a guard is ``unavailable``. The youth signal comes from the words and is
    applied to the union of every guard's codes, so "schoolgirl" in the prompt and ``sexual``
    on a photo meet here even though no single guard saw both (§6.4 hard rule).
    """
    prompt = job.prompt or ""
    narration = job.narration_text or ""
    lang_hint = lang_hint_for(job.language)
    texts = [TextItem(id="prompt", subject="prompt", content=prompt)]
    if narration:
        texts.append(TextItem(id="narration", subject="narration", content=narration))
    if job.voice_transcript:
        # An own voice note is screened through what whisper heard (§5.4, L1).
        texts.append(TextItem(id="transcript", subject="transcript", content=job.voice_transcript))
    youth = has_youth_signal([text.content for text in texts])
    hits = [hit.category for text in texts for hit in denylist_hits(text.content)]
    if hits:
        return apply_hard_rule(MediaScreenDecision.BLOCK, hits, youth_signal=youth)
    verdicts: list[Result[MediaVerdict]] = [
        await rt.moderator.screen_text(texts, policy=MEDIA_POLICY_VERSION, lang_hint=lang_hint)
    ]
    images = [
        ImageItem(
            id=f"{item.role.value}-{item.ordinal}",
            subject="collage" if item.role is MediaInputRole.COLLAGE else "upload",
            path=item.path,
        )
        for item in inputs
    ]
    if images:
        verdicts.append(
            await rt.moderator.screen_images(
                images, policy=MEDIA_POLICY_VERSION, lang_hint=lang_hint
            )
        )
    decisions: list[MediaScreenDecision] = []
    categories: list[CategoryCode] = []
    for verdict in verdicts:
        if is_err(verdict):
            decisions.append(MediaScreenDecision.UNAVAILABLE)
            continue
        decisions.append(verdict.value.decision)
        categories.extend(code for code in verdict.value.categories if code not in categories)
    return apply_hard_rule(strictest(decisions), categories, youth_signal=youth)


def _over_caps(rt: MediaRuntime, job: MediaJobRow) -> bool:
    """§1.3 / §6.4 L0: the prompt outside 3–800 characters or over the word cap, or a
    narration longer than its column or over its language's budget (§2.4.2, §5.3). The bot
    enforces the same caps at compose and at ``voice_text``, so this is a backstop for a row
    written some other way."""
    narration = job.narration_text
    return (
        not is_within_caps(job.prompt or "")
        or len(narration or "") > NARRATION_MAX_CHARS
        or (
            narration is not None
            and not fits_budget(narration, narration_budget(rt.settings, job.language))
        )
    )


async def _quote_eta_minutes(
    rt: MediaRuntime, job: MediaJobRow, backend: MediaBackend
) -> int | None:
    """Rank × moving-average run time (§3.4): everything already queued, then this request —
    plus, on the GPU, the gateway's own backlog of non-bayram jobs. ``None`` when that backlog
    cannot be read: an ETA that assumed an empty gateway could sell what misses its deadline.
    """
    ahead = len(await _gpu_call("members", rt.gpu.members(), ()))
    per_output = await _average_run_ms(rt, job)
    foreign_ms = 0
    if backend in GPU_BACKENDS:
        found = await _foreign_backlog_ms(rt, rt.providers(backend))
        if found is None:
            return None
        foreign_ms = found
    return math.ceil(((ahead + job.outputs_requested) * per_output + foreign_ms) / 60_000)


async def _is_backend_healthy(rt: MediaRuntime, backend: MediaBackend) -> bool:
    """§7.2 step 1: a backend that is down is not quoted, or the customer pays for a job that
    fails at submit until its deadline (NFR-20). Degraded still renders; anything else, or
    no answer, does not. The adapter's own health timeout bounds the call."""
    try:
        health = await rt.providers(backend).health()
    except Exception as exc:  # a provider never raises; a quote must not die if one does
        _LOG.warning("a media backend health check raised", extra={"failure": repr(exc)})
        return False
    if is_err(health):
        return False
    return health.value.state in (HealthState.HEALTHY, HealthState.DEGRADED)


def _prepay_state(job: MediaJobRow) -> MediaJobState:
    """The pre-quote state a screening stage found the row in: ``drafting`` for the video
    prescreen, ``screening`` otherwise. Every move it makes is conditional on that."""
    return (
        MediaJobState.DRAFTING if job.state is MediaJobState.DRAFTING else MediaJobState.SCREENING
    )


async def _refuse(
    rt: MediaRuntime,
    job: MediaJobRow,
    *,
    key: str,
    error_code: MediaErrorCode,
    values: Mapping[str, Any],
    legal_hold: bool = False,
    with_buttons: bool = True,
) -> bool:
    """``screening → rejected`` (or a video draft's ``drafting → rejected`` at the prescreen,
    §2.4.1) and the refusal on the tray — conditional on the state the stage loaded.
    ``legal_hold`` holds the inputs in the SAME transaction as the verdict (§6.7), before the
    cleanup this enqueues runs."""
    now = rt.clock()
    async with rt.sessions.begin() as session:
        moved = await transition(
            session,
            job.id,
            expected=(_prepay_state(job),),
            to=MediaJobState.REJECTED,
            now=now,
            values={"error_code": error_code.value, **dict(values)},
            policy=_policy(rt),
        )
        if moved and legal_hold:
            await place_legal_hold(session, job.id, now=now, policy=_policy(rt))
    if moved:
        markup = media_refused_keyboard(job.language, job.id) if with_buttons else None
        await _show_tray(rt, job, _translate(job, key), markup)
        await enqueue_stage(rt, MEDIA_CLEANUP_JOB, str(job.id), job_id=cleanup_job_id(job.id))
    return moved


async def _busy(rt: MediaRuntime, job: MediaJobRow, values: Mapping[str, Any]) -> None:
    """``media.busy``: the row stays where it is (``screening``, or a video draft's
    ``drafting``) and 🔁 re-runs this job on it (§2.3.3)."""
    if values:
        async with rt.sessions.begin() as session:
            await session.execute(
                sa.update(MediaJobRow)
                .where(MediaJobRow.id == job.id, MediaJobRow.state == _prepay_state(job))
                .values(updated_at=rt.clock(), **dict(values))
            )
    await _show_tray(rt, job, _translate(job, _BUSY_KEY), media_busy_keyboard(job.language, job.id))


async def media_screen(ctx: Mapping[str, Any], job_id: str, n: int = 0) -> dict[str, Any]:
    """Download, normalise and store the inputs; collage; screen; quote, refuse or say busy.

    ``n`` only distinguishes the ARQ id of a 🔁 retry from the first run
    (``bayram.media.stages.screen_job_id``). The row stays ``screening`` on ``busy`` so the
    retry runs on the SAME frozen row (§2.3.3); a refusal moves it to ``rejected`` and hands the
    uploads to ``media_cleanup``.
    """
    del n
    rt = media_runtime(ctx)
    jid = _uuid(job_id)
    async with rt.sessions() as session:
        job = await load_job(session, jid)
        rows = await list_inputs(session, jid) if job is not None else []
    if job is None or job.state is not MediaJobState.SCREENING:
        return _result("noop_not_screening", jid)
    gated = await _screen_gate(rt, job)
    if gated is not None:
        return gated
    if _over_caps(rt, job):
        # Refused, not struck, and before a byte is downloaded (§6.4 L0).
        await _refuse(rt, job, key=_REFUSED_KEY, error_code=MediaErrorCode.SCREEN_CAPS, values={})
        return _result("refused_caps", jid)
    workdir = media_workspace(rt, jid) / "in"

    # 1. The uploads, once each, as screened bytes.
    photos: list[_Screened] = []
    for row in rows:
        if row.role is not MediaInputRole.PHOTO:
            continue
        stored = await _store_upload(rt, job, row, workdir)
        if is_err(stored):
            return await _screen_input_failure(rt, job, stored)
        photos.append(stored.value)

    # 1b. An own voice note (§5.4): its real length before anything else, then whisper.
    voice: _Screened | None = None
    voice_row = next((row for row in rows if row.role is MediaInputRole.VOICE_NOTE), None)
    if voice_row is not None:
        heard = await _hear_voice_note(rt, job, voice_row, workdir)
        if not isinstance(heard, _Heard):
            return heard
        voice, job = heard.screened, heard.job

    # 2. The collage, when the backend takes fewer references than there are photos (§4.4).
    overrides = await read_overrides(rt.switches, job.sku)
    backend = effective_backend(rt.settings, job.sku, overrides.backend)
    inputs: list[_Screened] = list(photos)
    if needs_collage(len(photos), rt.providers(backend).capabilities().max_reference_images):
        existing = next((row for row in rows if row.role is MediaInputRole.COLLAGE), None)
        collage = await _store_collage(rt, job, photos, existing, workdir)
        if is_err(collage):
            return await _screen_input_failure(rt, job, collage)
        inputs.append(collage.value)

    # 3. The verdict — skipped when this row was already allowed under this policy for these
    #    exact bytes (a 🔁 on a tray that was busy for capacity, not for the guards).
    # In ``list_inputs`` order — photos, the voice note, the collage — as ``media_start``
    # re-computes it (§2.3.1).
    digest_inputs = [*photos, *([voice] if voice is not None else []), *inputs[len(photos) :]]
    digest = content_sha256(
        prompt=job.prompt,
        narration=job.narration_text,
        input_sha256s=[i.sha256 for i in digest_inputs],
    )
    already_allowed = (
        job.screen_decision is MediaScreenDecision.ALLOW
        and job.screen_policy_version == MEDIA_POLICY_VERSION
        and job.content_sha256 == digest
    )
    decision: MediaScreenDecision
    categories: tuple[CategoryCode, ...]
    if already_allowed:
        decision, categories = MediaScreenDecision.ALLOW, ()
    else:
        decision, categories = await _screen(rt, job, inputs)
    screen_values: dict[str, Any] = {
        "screen_decision": decision,
        "screen_categories": [code.value for code in categories],
        "screen_policy_version": MEDIA_POLICY_VERSION,
        "content_sha256": digest,
    }
    if decision in (MediaScreenDecision.BLOCK, MediaScreenDecision.REVIEW):
        return await _refuse_verdict(rt, job, decision, categories, screen_values)
    if decision is MediaScreenDecision.UNAVAILABLE:
        await _busy(rt, job, screen_values)
        return _result("busy_unscreened", jid)

    # 4. Capability (§7.2 step 1): offered, not paused, GPU not reserved, margin, a backend
    #    that answers healthy — and an ETA that fits inside the deadline, or we would take
    #    money we cannot deliver on (NFR-20).
    now = rt.clock()
    blocked = quote_block(rt.settings, job.sku, job.telegram_user_id, overrides, now=now)
    if blocked is None and not await _is_backend_healthy(rt, backend):
        blocked = QuoteBlock.UNHEALTHY
    eta_minutes = await _quote_eta_minutes(rt, job, backend) if blocked is None else None
    deadline = sku_deadline(rt.settings, job.sku)
    if blocked is QuoteBlock.GPU_RESERVED and job.kind is MediaKind.VIDEO:
        # §2.4.1: a video found the operator's reserved window at its quote. Cancelled, not
        # held open behind 🔁 for the whole window — the customer asks again afterwards.
        async with rt.sessions.begin() as session:
            cancelled = await transition(
                session,
                jid,
                expected=(MediaJobState.SCREENING,),
                to=MediaJobState.CANCELLED,
                now=now,
                values=screen_values,
                policy=_policy(rt),
            )
        if not cancelled:
            return _result("noop_lost_race", jid)
        await _show_tray(rt, job, _translate(job, _BUSY_KEY), None)
        await enqueue_stage(rt, MEDIA_CLEANUP_JOB, str(jid), job_id=cleanup_job_id(jid))
        return _result("cancelled_reserved", jid)
    if blocked is not None or eta_minutes is None or timedelta(minutes=eta_minutes) > deadline:
        await _busy(rt, job, screen_values)
        return _result(
            "busy_capacity", jid, block=None if blocked is None else blocked.value, eta=eta_minutes
        )
    async with rt.sessions.begin() as session:
        quoted = await transition(
            session,
            jid,
            expected=(MediaJobState.SCREENING,),
            to=MediaJobState.QUOTED,
            now=now,
            values={**screen_values, "quoted_at": now},
        )
        balance = await media_balance(session, telegram_user_id=job.telegram_user_id, sku=job.sku)
    if not quoted:
        return _result("noop_lost_race", jid)
    live_paid = is_live_paid(rt.settings)
    text = _quote_text(rt, job, eta_minutes)
    markup = media_quote_keyboard(
        job.language,
        jid,
        is_pay_offered=live_paid,
        is_credit_offered=balance > 0,
        is_beta_offered=not live_paid and is_beta_member(rt.settings, job.telegram_user_id),
    )
    await _show_tray(rt, job, text, markup)
    return _result("quoted", jid, eta=eta_minutes)


async def _refuse_verdict(
    rt: MediaRuntime,
    job: MediaJobRow,
    decision: MediaScreenDecision,
    categories: tuple[CategoryCode, ...],
    screen_values: Mapping[str, Any],
) -> dict[str, Any]:
    """A pre-pay ``block``/``review`` (§6.4), at the screen or the video prescreen.

    Pre-pay review is a refusal for the customer, non-specific (SEC-3) — the CSAM-class
    refusal reads exactly like any other. A block strikes; a review does not.
    """
    is_csam = is_csam_class(decision, categories)
    refused = await _refuse(
        rt,
        job,
        key=_REFUSED_KEY,
        error_code=MediaErrorCode.CSAM_BLOCKED if is_csam else MediaErrorCode.SCREEN_REFUSED,
        values=screen_values,
        legal_hold=is_csam,
    )
    if refused and is_csam:
        await _escalate_csam(rt, job, layer="prepay", categories=categories)
    elif refused and decision is MediaScreenDecision.BLOCK:
        await _strike(rt, job, layer="prepay", weight=PREPAY_BLOCK_STRIKES, is_csam=False)
    return _result("refused", job.id, decision=decision.value, csam=is_csam)


def _quote_text(rt: MediaRuntime, job: MediaJobRow, eta_minutes: int) -> str:
    """``media.image.quote`` or ``media.video.quote`` (§2.3.3, §2.4.2): the video's names
    its length, tier and voice, so the tier is on the quote even with no tier screen."""
    price = format_amount(job.price_minor)
    eta = _eta_text(job, eta_minutes)
    if job.kind is MediaKind.IMAGE:
        return _translate(job, _QUOTE_KEY, aspect=job.aspect.value, price=price, eta=eta)
    return _translate(
        job,
        _VIDEO_QUOTE_KEY,
        seconds=rt.settings.narration_max_seconds,
        aspect=job.aspect.value,
        tier=_translate(job, _TIER_NAME_KEYS[job.tier or MediaTier.STANDARD]),
        voice=_translate(job, _VOICE_MODE_NAME_KEYS[job.voice_mode]),
        price=price,
        eta=eta,
    )


# ---------------------------------------------------------------------------
# An own voice note (§5.4): ffprobe before payment, whisper, and the transcript's trust
# ---------------------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class _Heard:
    """A voice note that fits, is stored, and was transcribed into a trusted transcript."""

    screened: _Screened
    #: The row re-read with ``voice_transcript`` on it, for L1.
    job: MediaJobRow


async def _hear_voice_note(
    rt: MediaRuntime, job: MediaJobRow, row: MediaInputRow, workdir: Path
) -> _Heard | dict[str, Any]:
    """Download (or re-read) the note, measure it, store it, transcribe it (§5.4).

    Telegram's duration is whole seconds and client-reported, so ffprobe decides: above the
    clip length + 0.25 s the draft goes BACK to ``drafting`` for a shorter note — before
    payment, and before anything is stored or transcribed. A transcript §5.4 does not trust
    (empty, low ``avg_logprob``, high compression, a language other than uz/ru/en, too few
    words for the speech silencedetect found) refuses the request as ``review``: no strike,
    nothing was judged unsafe — the note simply cannot be screened.
    """
    local = workdir / _VOICE_NOTE_FILENAME
    stored_sha = row.sha256 if row.storage_key is not None else None
    if row.storage_key is not None and row.sha256 is not None:
        found = await _materialise(rt, key=row.storage_key, sha256=row.sha256, dest=local)
        if is_err(found):
            return await _screen_input_failure(rt, job, found)
    elif row.tg_file_id is None:
        return await _screen_input_failure(
            rt, job, err(ValidationError("a voice note row carries no Telegram file id"))
        )
    else:
        downloaded = await rt.messenger.download(
            row.tg_file_id, local, max_bytes=_VOICE_NOTE_MAX_BYTES
        )
        if is_err(downloaded):
            return await _screen_input_failure(rt, job, downloaded)
    measured = await rt.voice_probe.measure(local)
    if is_err(measured):
        # ffprobe/ffmpeg not answering is ours, not the customer's: busy, 🔁 retries.
        _LOG.warning("a voice note could not be measured", extra=measured.error.to_log_dict())
        await _busy(rt, job, {})
        return _result("busy_voice_probe", job.id)
    measure = measured.value
    if is_voice_note_too_long(measure.duration_s, rt.settings):
        return await _bounce_voice_note(rt, job, measure.duration_s)
    if stored_sha is None:
        stored = await rt.storage.put_file(
            media_key(job.id, is_output=False, filename=_VOICE_NOTE_FILENAME),
            local,
            content_type=_VOICE_NOTE_MIME,
        )
        if is_err(stored):
            return await _screen_input_failure(rt, job, stored)
        async with rt.sessions.begin() as session:
            await record_input_stored(
                session,
                row.id,
                storage_key=stored.value.key,
                mime=_VOICE_NOTE_MIME,
                size_bytes=stored.value.size_bytes,
                sha256=stored.value.sha256,
                duration_ms=round(measure.duration_s * 1000),
            )
        stored_sha = stored.value.sha256
    # No language hint: whisper detects it, which is what the language rule reads.
    heard = await rt.moderator.transcribe(local, language_hint="")
    if is_err(heard):
        await _busy(rt, job, {})
        return _result("busy_unheard", job.id)
    untrusted = untrusted_transcript(heard.value, voiced_s=measure.voiced_s)
    reason = None if untrusted is None else untrusted.value
    if reason is None and len(heard.value.text) > _TRANSCRIPT_MAX_CHARS:
        # More words than a clip-length note can hold: L1 screens only what is stored, and a
        # cut transcript would leave its tail in the delivered audio unscreened (fail closed).
        reason = "too_long"
    if reason is not None:
        _LOG.info(
            "an own voice note was refused: its transcript is not trusted",
            extra={"media_job_id": str(job.id), "reason": reason},
        )
        await _refuse(
            rt,
            job,
            key=_REFUSED_KEY,
            error_code=MediaErrorCode.VOICE_UNTRUSTED,
            values={
                "screen_decision": MediaScreenDecision.REVIEW,
                "screen_categories": [],
                "screen_policy_version": MEDIA_POLICY_VERSION,
            },
        )
        return _result("refused_voice", job.id, reason=reason)
    async with rt.sessions.begin() as session:
        await session.execute(
            sa.update(MediaJobRow)
            .where(MediaJobRow.id == job.id, MediaJobRow.state == MediaJobState.SCREENING)
            .values(voice_transcript=heard.value.text, updated_at=rt.clock())
        )
        reread = await load_job(session, job.id)
    if reread is None or reread.state is not MediaJobState.SCREENING:
        return _result("noop_lost_race", job.id)
    return _Heard(
        screened=_Screened(MediaInputRole.VOICE_NOTE, row.ordinal, local, stored_sha), job=reread
    )


async def _bounce_voice_note(
    rt: MediaRuntime, job: MediaJobRow, duration_s: float
) -> dict[str, Any]:
    """§5.4: a note over the clip (+0.25 s) is refused before payment — and only the NOTE.

    The row goes back to ``drafting`` (a pre-pay move; nothing terminal is re-opened) with
    its prescreen verdict restored, the note's row and any stored copy are deleted, and the
    tray offers 🎙 record again — so the customer re-records without re-writing the prompt
    or re-picking the shape. The next note re-finalises the same draft.
    """
    now = rt.clock()
    async with rt.sessions.begin() as session:
        moved = await transition(
            session,
            job.id,
            expected=(MediaJobState.SCREENING,),
            to=MediaJobState.DRAFTING,
            now=now,
            values={
                "screen_decision": MediaScreenDecision.ALLOW,
                "screen_categories": [],
                "screen_policy_version": MEDIA_POLICY_VERSION,
                "content_sha256": None,
                "voice_transcript": None,
            },
        )
        keys = await delete_inputs(session, job.id, role=MediaInputRole.VOICE_NOTE) if moved else ()
    if not moved:
        return _result("noop_lost_race", job.id)
    for key in keys:
        deleted = await rt.storage.delete(key)
        if is_err(deleted):
            _LOG.warning("a refused voice note could not be deleted", extra={"key": key})
    (media_workspace(rt, job.id) / "in" / _VOICE_NOTE_FILENAME).unlink(missing_ok=True)
    text = _translate(
        job,
        _VOICE_TOO_LONG_KEY,
        dur=f"{duration_s:.1f}",
        seconds=rt.settings.narration_max_seconds,
    )
    await _show_tray(rt, job, text, media_voice_too_long_keyboard(job.language, job.id))
    return _result("voice_too_long", job.id, duration_s=round(duration_s, 2))


# ---------------------------------------------------------------------------
# media_prescreen (§2.4.1): a video draft's prompt and photos, before the voice screens
# ---------------------------------------------------------------------------
async def media_prescreen(ctx: Mapping[str, Any], job_id: str, n: int = 0) -> dict[str, Any]:
    """L0 + L1 on the prompt, L2 (+G8) on the photos of a ``drafting`` video row.

    The row stays ``drafting``: an allow records the verdict on it and turns the tray into
    the shape screen; a block or review refuses it (``rejected``, struck as at the screen);
    ``unavailable`` is ``media.busy`` with 🔁. The script writer and ``finalize_video`` act
    only on a draft this allowed, so neither ever sees an unscreened prompt. ``n`` only tells
    a 🔁 or a sweep re-drive from the first run.
    """
    del n
    rt = media_runtime(ctx)
    jid = _uuid(job_id)
    async with rt.sessions() as session:
        job = await load_job(session, jid)
        rows = await list_inputs(session, jid) if job is not None else []
    if job is None or job.state is not MediaJobState.DRAFTING or job.kind is not MediaKind.VIDEO:
        return _result("noop_not_drafting", jid)
    if (
        job.screen_decision is MediaScreenDecision.ALLOW
        and job.screen_policy_version == MEDIA_POLICY_VERSION
    ):
        return _result("noop_prescreened", jid)
    gated = await _screen_gate(rt, job)
    if gated is not None:
        return gated
    if _over_caps(rt, job):
        await _refuse(rt, job, key=_REFUSED_KEY, error_code=MediaErrorCode.SCREEN_CAPS, values={})
        return _result("refused_caps", jid)
    workdir = media_workspace(rt, jid) / "in"
    photos: list[_Screened] = []
    for row in rows:
        if row.role is not MediaInputRole.PHOTO:
            continue
        stored = await _store_upload(rt, job, row, workdir)
        if is_err(stored):
            return await _screen_input_failure(rt, job, stored)
        photos.append(stored.value)
    decision, categories = await _screen(rt, job, photos)
    screen_values: dict[str, Any] = {
        "screen_decision": decision,
        "screen_categories": [code.value for code in categories],
        "screen_policy_version": MEDIA_POLICY_VERSION,
    }
    if decision in (MediaScreenDecision.BLOCK, MediaScreenDecision.REVIEW):
        return await _refuse_verdict(rt, job, decision, categories, screen_values)
    if decision is MediaScreenDecision.UNAVAILABLE:
        # Recorded, as at the screen, so the sweep leaves a busy draft to the customer's 🔁.
        await _busy(rt, job, screen_values)
        return _result("busy_unscreened", jid)
    async with rt.sessions.begin() as session:
        recorded = await update_draft(session, jid, now=rt.clock(), values=screen_values)
    if not recorded:
        return _result("noop_lost_race", jid)
    await _show_tray(
        rt, job, _translate(job, _ASPECT_KEY), media_video_aspect_keyboard(job.language)
    )
    return _result("prescreened", jid)


async def _screen_gate(
    rt: MediaRuntime, job: MediaJobRow, *, budget_id: str | None = None, draw_busy: bool = True
) -> dict[str, Any] | None:
    """§6.4 L0, before a byte is downloaded: a suspended account, one past today's
    screening budget, or one that already started today's paid requests of this kind (§7.6)
    is refused unscreened — and not struck, since nothing was judged.

    The budget counts this JOB once, so a 🔁 on a busy tray does not spend twice. A Redis
    that cannot answer is ``busy``: the suspension could not be read, so nothing is screened.
    ``budget_id`` counts something else once instead — each 🤖 line is its own screening
    (§2.4.2), so the writer passes one id per line. ``draw_busy=False`` leaves the tray to the
    caller when the store cannot answer (outcome ``_GATE_UNREADABLE``): the writer draws its
    own failure screen, since 🔁 on a draft re-runs only the prescreen.

    **A CSAM-class suspension is read from the database too** (``csam_blocked`` rows no
    operator cleared): Redis is a cache on this deployment, and a restart without persistence
    must not lift a suspension only an operator may lift (§6.4).
    """
    now = rt.clock()
    screens = 0
    try:
        suspended = await rt.strikes.suspension(job.telegram_user_id, now=now)
        async with rt.sessions() as session:
            if suspended is None and await has_standing_csam_block(session, job.telegram_user_id):
                suspended = Suspension(SuspensionReason.CSAM)
            # §7.6, read BEFORE the budget is counted and inside this fail-closed block: a
            # refusal at the cap screens nothing, so it spends none of the day's screenings,
            # and a database that cannot answer draws busy like the suspension read.
            at_cap = await is_at_daily_cap(
                session, rt.settings, telegram_user_id=job.telegram_user_id, kind=job.kind, now=now
            )
        if not at_cap:
            screens = await rt.strikes.count_screen(
                job.telegram_user_id, job_id=budget_id or str(job.id), now=now
            )
    except Exception as exc:  # the store raises on Redis or database failure; fail closed
        _LOG.warning(
            "the media suspension could not be read",
            extra={"media_job_id": str(job.id), "failure": type(exc).__name__},
        )
        if draw_busy:
            await _busy(rt, job, {})
        return _result(_GATE_UNREADABLE, job.id)
    if suspended is not None:
        await _refuse(
            rt,
            job,
            key=_SUSPENDED_KEY,
            error_code=MediaErrorCode.SCREEN_SUSPENDED,
            values={},
            with_buttons=False,
        )
        return _result("refused_suspended", job.id, reason=suspended.reason.value)
    if at_cap:
        # §7.6: no quote the customer could not pay for today. The press-time handlers check
        # again; the one-open-request index means nothing else of this kind is paid between.
        await _refuse(
            rt,
            job,
            key=_DAILY_CAP_KEY,
            error_code=MediaErrorCode.DAILY_CAP,
            values={},
            with_buttons=False,
        )
        return _result("refused_daily_cap", job.id)
    if screens > rt.settings.media_screen_daily_budget:
        await _refuse(rt, job, key=_REFUSED_KEY, error_code=MediaErrorCode.SCREEN_BUDGET, values={})
        return _result("refused_budget", job.id, screens=screens)
    return None


async def _screen_input_failure(rt: MediaRuntime, job: MediaJobRow, failure: Err) -> dict[str, Any]:
    """An upload we will not use is the customer's (refuse); anything else is ours (busy)."""
    error = failure.error
    if isinstance(error, ValidationError) and not isinstance(error, StorageError):
        await _refuse(
            rt,
            job,
            key=_UNSUPPORTED_KEY,
            error_code=MediaErrorCode.UNSUPPORTED_INPUT,
            values={},
        )
        return _result("refused_input", job.id, too_large=bool(error.context.get(TOO_LARGE_KEY)))
    _LOG.warning("a media input could not be prepared", extra=error.to_log_dict())
    await _busy(rt, job, {})
    return _result("busy_input", job.id)


# ---------------------------------------------------------------------------
# media_start (§3.3, §7.2): the latch that turns a paid row into GPU work
# ---------------------------------------------------------------------------
async def _screened_digest(session: AsyncSession, job: MediaJobRow) -> str | None:
    """A fresh ``content_sha256`` from the row and its stored inputs, or ``None`` when an
    input was never stored (so the row cannot be what was screened)."""
    shas: list[str] = []
    for row in await list_inputs(session, job.id):
        if row.sha256 is None:
            return None
        shas.append(row.sha256)
    return content_sha256(prompt=job.prompt, narration=job.narration_text, input_sha256s=shas)


async def media_start(ctx: Mapping[str, Any], job_id: str, n: int = 0) -> dict[str, Any]:
    """``paid → queued``, once, and the submits. Re-checks what was screened first (§2.3.1).

    The latch is the row's own conditional move, never ``payment_intents.resumed_at``: the
    settlement path, a 🎁/🎟 press and ``media_sweep`` may all enqueue this (``n`` tells their
    ARQ ids apart), and exactly one of them moves the row.
    """
    del n
    rt = media_runtime(ctx)
    jid = _uuid(job_id)
    now = rt.clock()
    async with rt.sessions() as session:
        job = await load_job(session, jid)
        digest = await _screened_digest(session, job) if job is not None else None
    if job is None or job.state is not MediaJobState.PAID:
        return _result("noop_not_paid", jid)
    paid_expected = (MediaJobState.PAID,)
    if job.forget_requested_at is not None:
        # §9.3: the account was forgotten between payment and start. Its inputs are gone, so
        # the digest check below would fail it as stale — with a refund that re-creates the
        # data /forget erased. End it quietly instead; ``media_cleanup`` purges the rest.
        await fail_job(
            rt,
            jid,
            expected=paid_expected,
            error_code=MediaErrorCode.FORGET_REQUESTED,
            refund=None,
            notify=False,
        )
        return _result("failed_forgotten", jid)
    if (
        job.screen_decision is not MediaScreenDecision.ALLOW
        or job.screen_policy_version != MEDIA_POLICY_VERSION
        or digest is None
        or digest != job.content_sha256
    ):
        await fail_job(
            rt,
            jid,
            expected=paid_expected,
            error_code=MediaErrorCode.SCREEN_STALE,
            refund=MediaCreditReason.GENERATION_FAILED,
        )
        return _result("failed_screen_stale", jid)
    if job.paid_via is MediaPaidVia.BETA and not (
        not is_live_paid(rt.settings)
        and media_offered(rt.settings, job.sku, job.telegram_user_id, is_paused=False)
    ):
        # §2.5: the free beta is re-checked at run time. A paused SKU still runs (paid jobs
        # continue, §4.5), so only the offer, the allowlist and the rail are read here.
        await fail_job(
            rt, jid, expected=paid_expected, error_code=MediaErrorCode.NOT_ENTITLED, refund=None
        )
        return _result("failed_not_entitled", jid)
    backend = effective_backend(
        rt.settings, job.sku, await read_backend_override(rt.switches, job.sku)
    )
    model_id = _model_id(rt, backend, job.kind)
    async with rt.sessions.begin() as session:
        latched = await transition(
            session,
            jid,
            expected=paid_expected,
            to=MediaJobState.QUEUED,
            now=now,
            # Stamped here, as the first submit is enqueued, so both variants render on the
            # same backend and the admin reads the row rather than mirroring a flag (§4.5).
            values={"backend": backend, "model_id": model_id},
        )
        if latched:
            # §3.2.2: a Payme settlement stamped the uploads' clock from the SHIPPED deadline
            # (the gateway reads no Settings); re-stamp it from the configured one before any
            # stage runs, so a raised deadline never has the photos purged mid-render.
            await stamp_input_backstop(
                session,
                jid,
                paid_at=job.paid_at or now,
                deadline=sku_deadline(rt.settings, job.sku),
            )
    if not latched:
        return _result("noop_latched_elsewhere", jid)
    paid_at = job.paid_at or now
    if backend in GPU_BACKENDS:
        for variant in range(job.outputs_requested):
            await _gpu_call(
                "join",
                rt.gpu.join(queue_member(jid, variant), queue_score(paid_at, variant)),
                None,
            )
    await _send_status(rt, jid)
    for variant in range(job.outputs_requested):
        await enqueue_stage(
            rt,
            MEDIA_SUBMIT_JOB,
            str(jid),
            variant,
            1,
            0,
            job_id=submit_job_id(jid, variant, 1, 0),
        )
    # A video's voice runs beside its render (§3.3): TTS for an AI voice, the prepared note
    # for an own one. Whichever of the two finishes second fans in to the mux.
    await enqueue_voice_stage(rt, job, n=0)
    return _result("started", jid, backend=backend.value)


async def enqueue_voice_stage(rt: MediaRuntime, job: MediaJobRow, *, n: int) -> bool:
    """``media_tts`` or ``media_voice_prepare`` for a video with a voice; nothing otherwise.
    ``n`` is 0 from ``media_start`` and the sweep's tick when it re-drives a lost one."""
    if job.kind is not MediaKind.VIDEO:
        return False
    if job.voice_mode in (MediaVoiceMode.AI_USER, MediaVoiceMode.AI_LLM):
        return await enqueue_stage(rt, MEDIA_TTS_JOB, str(job.id), n, job_id=tts_job_id(job.id, n))
    if job.voice_mode is MediaVoiceMode.OWN:
        return await enqueue_stage(
            rt,
            MEDIA_VOICE_PREPARE_JOB,
            str(job.id),
            n,
            job_id=voice_prepare_job_id(job.id, n),
        )
    return False


def _model_id(rt: MediaRuntime, backend: MediaBackend, kind: MediaKind) -> str:
    """The model a job renders on. The fake stands in for the local gateway and is held to
    its allowlist, so it is stamped with the gateway's model names too."""
    if backend in GPU_BACKENDS:
        settings = rt.settings
        return settings.genai_image_model if kind is MediaKind.IMAGE else settings.genai_video_model
    return backend.value


# ---------------------------------------------------------------------------
# Progress (§3.3): one status message, re-rendered from the row
# ---------------------------------------------------------------------------
async def _progress_frame(rt: MediaRuntime, job: MediaJobRow) -> tuple[str, int, int]:
    """``(key, position, minutes)`` for the job now."""
    per_output = await _average_run_ms(rt, job)
    async with rt.sessions() as session:
        latest = await latest_attempts(session, job.id, stage=_stage(job.kind))
        done = len(await list_outputs(session, job.id, role=MediaOutputRole.IMAGE))
    remaining = max(1, job.outputs_requested - done)
    running = any(row.status is MediaAttemptStatus.SUBMITTED for row in latest.values())
    if running and job.started_at is not None:
        elapsed_ms = (rt.clock() - job.started_at).total_seconds() * 1000
        left_ms = max(0.0, job.outputs_requested * per_output - elapsed_ms)
        return _RENDERING_KEY, 0, max(1, math.ceil(left_ms / 60_000))
    ranks = [
        rank
        for member in _members(job)
        if (rank := await _gpu_call("rank", rt.gpu.rank(member), None)) is not None
    ]
    position = (min(ranks) if ranks else 0) + 1
    # §3.4: the gateway's non-bayram backlog runs ahead too. Best-effort here — the quote
    # already refused to sell on an unreadable queue; a progress frame just leaves it out.
    foreign_ms = 0
    if job.backend in GPU_BACKENDS:
        foreign_ms = await _foreign_backlog_ms(rt, rt.providers(_backend(job))) or 0
    minutes = math.ceil(((position - 1 + remaining) * per_output + foreign_ms) / 60_000)
    key = _QUEUED_KEY if job.paid_via is MediaPaidVia.PAYME else _QUEUED_FREE_KEY
    return key, position, max(1, minutes)


def _progress_text(job: MediaJobRow, key: str, position: int, minutes: int) -> str:
    if key == _RENDERING_KEY:
        return _translate(job, key, minutes=minutes)
    return _translate(job, key, pos=position, eta=_eta_text(job, minutes))


def _memo_key(job_id: UUID) -> str:
    return f"media:{job_id}:progress"


async def _send_status(rt: MediaRuntime, job_id: UUID) -> None:
    """The one progress message, sent once by ``media_start``. Best-effort."""
    async with rt.sessions() as session:
        job = await load_job(session, job_id)
    if job is None or job.status_message_id is not None:
        return
    try:
        key, position, minutes = await _progress_frame(rt, job)
    except Exception as exc:
        _LOG.warning("the media progress frame failed", extra={"failure": repr(exc)})
        return
    message_id = await rt.messenger.send(job.chat_id, _progress_text(job, key, position, minutes))
    if message_id is None:
        return
    async with rt.sessions.begin() as session:
        await session.execute(
            sa.update(MediaJobRow)
            .where(MediaJobRow.id == job_id)
            .values(status_message_id=message_id, updated_at=rt.clock())
        )
    await _remember_frame(rt, job_id, key, position, minutes)


async def _remember_frame(
    rt: MediaRuntime, job_id: UUID, key: str, position: int, minutes: int
) -> None:
    stamp = int(rt.clock().timestamp())
    try:
        await rt.memo.set(
            _memo_key(job_id), f"{key}|{position}|{minutes}|{stamp}", ex=_PROGRESS_MEMO_TTL_S
        )
    except Exception as exc:
        _LOG.info("the media progress memo could not be written", extra={"failure": repr(exc)})


async def _refresh_progress(rt: MediaRuntime, job_id: UUID) -> None:
    """Re-render the status message iff the frame changed and a minute has passed. Never raises."""
    try:
        async with rt.sessions() as session:
            job = await load_job(session, job_id)
        if job is None or job.status_message_id is None or job.state not in _WORKING_STATES:
            return
        raw = await rt.memo.get(_memo_key(job_id))
        memo = raw.decode() if isinstance(raw, bytes | bytearray) else raw
        previous: tuple[str, str, str] | None = None
        if isinstance(memo, str):
            old_key, old_pos, old_min, stamp = memo.split("|")
            if int(rt.clock().timestamp()) - int(stamp) < _PROGRESS_MIN_INTERVAL_S:
                # Checked BEFORE the frame is built: the frame reads the gateway's queue, and
                # a waiting submit or a poll comes by every few seconds.
                return
            previous = (old_key, old_pos, old_min)
        key, position, minutes = await _progress_frame(rt, job)
        if previous == (key, str(position), str(minutes)):
            return
        if await rt.messenger.edit(
            job.chat_id, job.status_message_id, _progress_text(job, key, position, minutes)
        ):
            await _remember_frame(rt, job_id, key, position, minutes)
    except Exception as exc:
        _LOG.info("the media progress message was not refreshed", extra={"failure": repr(exc)})


# ---------------------------------------------------------------------------
# media_submit (§3.3, §3.4): one POST per attempt, never two
# ---------------------------------------------------------------------------
async def _build_request(
    rt: MediaRuntime, job: MediaJobRow, variant: int, workdir: Path
) -> Result[MediaRequest]:
    """The generation request, built only from the row and the SCREENED inputs (§3.3)."""
    async with rt.sessions() as session:
        rows = await list_inputs(session, job.id)
    collage = next((row for row in rows if row.role is MediaInputRole.COLLAGE), None)
    photos = [row for row in rows if row.role is MediaInputRole.PHOTO]
    chosen = [collage] if collage is not None else photos
    refs: list[Path] = []
    for row in chosen:
        if row.storage_key is None:
            return err(ValidationError("an input was never screened", context={"role": row.role}))
        local = await _materialise(
            rt,
            key=row.storage_key,
            sha256=row.sha256,
            dest=workdir / f"ref-{row.role.value}-{row.ordinal}.jpg",
        )
        if is_err(local):
            return local
        refs.append(local.value)
    width, height = target_size(_kind_name(job.kind), job.aspect)
    params = job.params or {}
    base_seed = params.get("seed")
    seed = int(base_seed) if isinstance(base_seed, int) else job.id.int % 2_000_000_000
    is_image = job.kind is MediaKind.IMAGE
    return ok(
        MediaRequest(
            kind=_kind_name(job.kind),
            model_key=job.model_id or "",
            prompt=job.prompt or "",
            refs=tuple(refs),
            width=width,
            height=height,
            length_frames=None if is_image else 81,
            fps=None if is_image else 16,
            steps=rt.settings.media_image_steps if is_image else rt.settings.media_video_steps,
            # Variant 1 is seed s+1 (§1.3), so the two images of one request differ.
            seed=seed + variant,
            denoise=rt.settings.media_image_denoise if is_image and refs else None,
        )
    )


async def enqueue_submit(
    rt: MediaRuntime, job_id: UUID, variant: int, attempt: int, *, defer_s: float
) -> None:
    """A deliberate re-enqueue: the next ``submit_seq``, so ARQ runs it (§3.3)."""
    async with rt.sessions.begin() as session:
        seq = await bump_seq(session, job_id, column="submit_seq", now=rt.clock())
    if seq is None:
        return
    await enqueue_stage(
        rt,
        MEDIA_SUBMIT_JOB,
        str(job_id),
        variant,
        attempt,
        seq,
        job_id=submit_job_id(job_id, variant, attempt, seq),
        defer_s=defer_s,
    )


async def _after_attempt(
    rt: MediaRuntime,
    job_id: UUID,
    variant: int,
    attempt: int,
    status: MediaAttemptStatus,
) -> None:
    """The retry policy (§3.3 "Retries") for an attempt that just ended.

    An ``ambiguous`` attempt is reconciled first (:func:`_after_ambiguous`): its render may be
    running where we cannot see it, and nothing is resubmitted until that is ruled out.
    """
    if status is MediaAttemptStatus.AMBIGUOUS:
        await _after_ambiguous(rt, job_id, variant, attempt)
        return
    await _retry_or_finish(rt, job_id, variant, attempt, status)


async def _retry_or_finish(
    rt: MediaRuntime,
    job_id: UUID,
    variant: int,
    attempt: int,
    status: MediaAttemptStatus,
) -> None:
    """Only after a TERMINAL (or reconciled) attempt: attempt N+1 on the same backend while
    attempts remain; a content rejection is never retried. Otherwise the variant is finished:
    it leaves the GPU queue and the fan-in counts it."""
    retryable = status in (MediaAttemptStatus.FAILED, MediaAttemptStatus.AMBIGUOUS)
    if retryable and attempt < rt.settings.media_max_attempts:
        await enqueue_submit(
            rt,
            job_id,
            variant,
            attempt + 1,
            defer_s=rt.settings.provider_backoff_base_s * attempt,
        )
        return
    await _gpu_call("leave", rt.gpu.leave(queue_member(job_id, variant)), None)
    async with rt.sessions() as session:
        job = await load_job(session, job_id)
    if job is None:
        return
    if job.kind is MediaKind.IMAGE:
        await image_fan_in(rt, job_id)
    else:
        await fail_job(
            rt,
            job_id,
            expected=_WORKING_STATES,
            error_code=MediaErrorCode.GENERATION_FAILED,
            refund=MediaCreditReason.GENERATION_FAILED,
        )


async def _after_ambiguous(rt: MediaRuntime, job_id: UUID, variant: int, attempt: int) -> None:
    """An attempt that may have started a job we hold no answer for (§4.2, §4.3).

    * **A backend that costs money** is never re-posted automatically (§4.3, R7): the job is
      ``held`` for an operator to reconcile against the vendor.
    * **The GPU** is reconciled against the gateway's own queue before anything else happens
      (:func:`reconcile_ambiguous`).
    """
    async with rt.sessions() as session:
        job = await load_job(session, job_id)
        row = (
            await find_attempt(
                session, job_id, stage=_stage(job.kind), variant=variant, attempt=attempt
            )
            if job is not None
            else None
        )
    if job is None or row is None or job.state not in _WORKING_STATES:
        return
    if _backend(job) in GPU_BACKENDS:
        await reconcile_ambiguous(rt, job, row)
        return
    await _gpu_call("leave", rt.gpu.leave(queue_member(job_id, variant)), None)
    async with rt.sessions.begin() as session:
        held = await transition(
            session,
            job_id,
            expected=_WORKING_STATES,
            to=MediaJobState.HELD,
            now=rt.clock(),
            values={"error_code": MediaErrorCode.AMBIGUOUS_SUBMIT.value},
        )
    if held:
        _LOG.warning(
            "an ambiguous paid-backend attempt; the job is held for an operator, never re-posted",
            extra={"media_job_id": str(job_id), "variant": variant, "attempt": attempt},
        )


async def reconcile_ambiguous(rt: MediaRuntime, job: MediaJobRow, row: MediaAttemptRow) -> str:
    """§4.2 local reconciliation of one ``ambiguous`` attempt. Returns what it decided.

    The gateway may be rendering it anyway — a 5xx that arrived after the body left, a read
    timeout, a poll that answered ``unknown``, a render past its timeout, or a worker killed
    between the attempt row and the POST's answer. So ``GET /queue`` is read first:

    * **the render is (or may be) still there** — the attempt's remote id is listed, or, with
      no remote id, a bayram-or-unlabelled job we hold no id for is, or the queue cannot be
      read — then the GPU slot stays held under this attempt (renewed, or re-taken if it
      lapsed and is free) and this is looked at again in :data:`_RECONCILE_DEFER_S`: posting
      attempt N+1 now would render the same variant twice and put two jobs on one GPU (§3.4);
    * **it is gone** — the slot is released and the retry policy runs: one automatic
      resubmit, since local cost is GPU time only; ``media_max_attempts`` (2) makes a second
      ambiguous attempt the variant's last.

    Re-entered through ``media_submit`` for the SAME attempt (a fresh ``submit_seq``), so a
    lost re-enqueue is re-driven by ``media_sweep`` like any other waiting submit.
    """
    holder = str(row.id)
    listed = await _gateway_queue(rt.providers(_backend(job)))
    if is_err(listed):
        pending = True
    elif row.remote_id is not None:
        pending = row.remote_id in {entry.job_id for entry in listed.value}
    else:
        own = await _own_remote_ids(rt)
        pending = any(
            entry.job_id not in own and entry.client in (None, CLIENT_TAG) for entry in listed.value
        )
    if pending:
        current = await _gpu_call("holder", rt.gpu.holder(), None)
        if current == holder:
            await _gpu_call("renew", rt.gpu.renew(holder, ttl_ms=GPU_LOCK_ACQUIRE_TTL_MS), False)
        elif current is None:
            await _gpu_call(
                "acquire", rt.gpu.acquire(holder, ttl_ms=GPU_LOCK_ACQUIRE_TTL_MS), False
            )
        await enqueue_submit(rt, job.id, row.variant, row.attempt, defer_s=_RECONCILE_DEFER_S)
        return "reconciling"
    await _gpu_call("release", rt.gpu.release(holder), False)
    _LOG.info(
        "an ambiguous media attempt is not on the gateway; the retry policy decides",
        extra={"media_job_id": str(job.id), "variant": row.variant, "attempt": row.attempt},
    )
    await _retry_or_finish(rt, job.id, row.variant, row.attempt, MediaAttemptStatus.AMBIGUOUS)
    return "reconciled"


async def media_submit(
    ctx: Mapping[str, Any], job_id: str, variant: int, attempt: int, seq: int = 0
) -> dict[str, Any]:
    """Take the GPU slot, write the attempt, POST once, hand over to ``media_poll``.

    ``seq`` only makes the ARQ id of a waiting re-run fresh. The attempt number is fixed at
    enqueue (§3.3): a re-run of the SAME attempt that finds its ``submitting`` row with no
    remote id and no live lock is a crash between the insert and the POST — it is marked
    ``ambiguous`` and reconciled (:func:`reconcile_ambiguous`), and is never posted again (R7).
    A re-run for an attempt already ``ambiguous`` is the next look of that reconciliation.
    """
    del seq
    rt = media_runtime(ctx)
    jid = _uuid(job_id)
    now = rt.clock()
    async with rt.sessions() as session:
        job = await load_job(session, jid)
        existing = (
            await find_attempt(
                session, jid, stage=_stage(job.kind), variant=variant, attempt=attempt
            )
            if job is not None
            else None
        )
    member = queue_member(jid, variant)
    if job is None or job.state not in _WORKING_STATES:
        await _gpu_call("leave", rt.gpu.leave(member), None)
        return _result("noop_not_working", jid, variant=variant)
    if job.forget_requested_at is not None:
        await fail_job(
            rt,
            jid,
            expected=_WORKING_STATES,
            error_code=MediaErrorCode.FORGET_REQUESTED,
            refund=None,
            notify=False,
        )
        return _result("failed_forgotten", jid)
    backend = _backend(job)
    provider = rt.providers(backend)
    uses_gpu = backend in GPU_BACKENDS

    if existing is not None:
        return await _resume_attempt(rt, job, existing, uses_gpu=uses_gpu, now=now)

    attempt_id = uuid4()
    if uses_gpu:
        await _gpu_call("join", rt.gpu.join(member, queue_score(job.paid_at or now, variant)), None)
        rank = await _gpu_call("rank", rt.gpu.rank(member), None)
        acquired = rank == 0 and await _gpu_call(
            "acquire", rt.gpu.acquire(str(attempt_id), ttl_ms=GPU_LOCK_ACQUIRE_TTL_MS), False
        )
        if not acquired:
            await enqueue_submit(rt, jid, variant, attempt, defer_s=_WAIT_DEFER_S)
            await _refresh_progress(rt, jid)
            return _result("waiting_for_gpu", jid, variant=variant, rank=rank)

    async with rt.sessions.begin() as session:
        inserted = await insert_attempt(
            session,
            job_id=jid,
            stage=_stage(job.kind),
            variant=variant,
            attempt=attempt,
            provider=provider.name,
            now=now,
            model_id=job.model_id,
            attempt_id=attempt_id,
        )
    if inserted is None:
        # A sibling copy of this very submit got there first; it owns the attempt.
        if uses_gpu:
            await _gpu_call("release", rt.gpu.release(str(attempt_id)), False)
        return _result("noop_attempt_exists", jid, variant=variant)

    workdir = media_workspace(rt, jid) / "in"
    request = await _build_request(rt, job, variant, workdir)
    if is_err(request):
        return await _attempt_failed_before_post(
            rt, job, variant, attempt, attempt_id, request.error, uses_gpu=uses_gpu
        )
    submitted = await provider.submit(
        request.value,
        correlation_key=f"media:{jid}:{variant}:{attempt}",
        webhook_url=None,
        timeout_s=_SUBMIT_TIMEOUT_S,
    )
    if is_err(submitted):
        error = submitted.error
        status = MediaAttemptStatus.AMBIGUOUS if is_ambiguous(error) else MediaAttemptStatus.FAILED
        async with rt.sessions.begin() as session:
            await set_attempt_status(
                session,
                attempt_id,
                expected=(MediaAttemptStatus.SUBMITTING,),
                status=status,
                now=rt.clock(),
                error_code=error.code.value,
            )
        # An ambiguous POST may have started a render we cannot see: the slot stays held while
        # the gateway's queue is read (§4.2), and a paid backend holds the job for an operator
        # instead of retrying (§4.3). A plain failure queued nothing, so the slot goes now.
        if uses_gpu and status is not MediaAttemptStatus.AMBIGUOUS:
            await _gpu_call("release", rt.gpu.release(str(attempt_id)), False)
        await _after_attempt(rt, jid, variant, attempt, status)
        return _result("submit_failed", jid, variant=variant, status=status.value)

    handle = submitted.value
    async with rt.sessions.begin() as session:
        await set_attempt_status(
            session,
            attempt_id,
            expected=(MediaAttemptStatus.SUBMITTING,),
            status=MediaAttemptStatus.SUBMITTED,
            now=rt.clock(),
            remote_id=handle.remote_id,
        )
        await transition(
            session,
            jid,
            expected=(MediaJobState.QUEUED,),
            to=MediaJobState.GENERATING,
            now=rt.clock(),
            values={"started_at": rt.clock()},
        )
        await touch_job(session, jid, now=rt.clock())
    if uses_gpu:
        # Only now that a remote id exists does the lock last a whole render (§3.4).
        await _gpu_call(
            "renew",
            rt.gpu.renew(str(attempt_id), ttl_ms=_render_timeout_s(rt, job.kind) * 1000),
            False,
        )
    await enqueue_stage(
        rt,
        MEDIA_POLL_JOB,
        str(jid),
        variant,
        attempt,
        0,
        job_id=poll_job_id(jid, variant, attempt, 0),
        defer_s=_POLL_DEFER_S[job.kind],
    )
    await _refresh_progress(rt, jid)
    return _result("submitted", jid, variant=variant, attempt=attempt)


async def _attempt_failed_before_post(
    rt: MediaRuntime,
    job: MediaJobRow,
    variant: int,
    attempt: int,
    attempt_id: UUID,
    error: BayramError,
    *,
    uses_gpu: bool,
) -> dict[str, Any]:
    """Nothing was posted: the attempt is plainly ``failed`` (our inputs, not the backend)."""
    _LOG.warning("a media request could not be built", extra=error.to_log_dict())
    async with rt.sessions.begin() as session:
        await set_attempt_status(
            session,
            attempt_id,
            expected=(MediaAttemptStatus.SUBMITTING,),
            status=MediaAttemptStatus.FAILED,
            now=rt.clock(),
            error_code=MediaErrorCode.INPUT_CHANGED.value,
        )
    if uses_gpu:
        await _gpu_call("release", rt.gpu.release(str(attempt_id)), False)
    await _after_attempt(rt, job.id, variant, attempt, MediaAttemptStatus.FAILED)
    return _result("request_failed", job.id, variant=variant)


async def _resume_attempt(
    rt: MediaRuntime,
    job: MediaJobRow,
    existing: MediaAttemptRow,
    *,
    uses_gpu: bool,
    now: datetime,
) -> dict[str, Any]:
    """A submit for an attempt that already has a row: a duplicate, or a crash to reconcile."""
    variant, attempt = existing.variant, existing.attempt
    if existing.status is MediaAttemptStatus.SUBMITTED:
        # The POST landed; make sure a poll chain exists. Its ids are deterministic per tick,
        # so a duplicate of a live chain is dropped by ARQ.
        await enqueue_stage(
            rt,
            MEDIA_POLL_JOB,
            str(job.id),
            variant,
            attempt,
            0,
            job_id=poll_job_id(job.id, variant, attempt, 0),
            defer_s=_POLL_DEFER_S[job.kind],
        )
        return _result("noop_already_submitted", job.id, variant=variant)
    if existing.status is MediaAttemptStatus.AMBIGUOUS and uses_gpu:
        # A reconciliation in progress (§4.2) — unless a later attempt already replaced it.
        async with rt.sessions() as session:
            latest = await latest_attempts(session, job.id, stage=_stage(job.kind))
        newest = latest.get(variant)
        if newest is not None and newest.attempt > attempt:
            return _result("noop_attempt_replaced", job.id, variant=variant)
        decided = await reconcile_ambiguous(rt, job, existing)
        return _result(decided, job.id, variant=variant, attempt=attempt)
    if existing.status is not MediaAttemptStatus.SUBMITTING or existing.remote_id is not None:
        return _result("noop_attempt_finished", job.id, variant=variant)
    holder = str(existing.id)
    if uses_gpu:
        if await _gpu_call("holder", rt.gpu.holder(), None) == holder:
            # Its owner holds the slot and is mid-POST — not a crash.
            return _result("noop_in_flight", job.id, variant=variant)
    elif existing.created_at > now - _SUBMITTING_GRACE:
        return _result("noop_in_flight", job.id, variant=variant)
    # The worker died between writing this row and posting (R7). Never post it again.
    async with rt.sessions.begin() as session:
        marked = await set_attempt_status(
            session,
            existing.id,
            expected=(MediaAttemptStatus.SUBMITTING,),
            status=MediaAttemptStatus.AMBIGUOUS,
            now=now,
            error_code=MediaErrorCode.CRASHED_BEFORE_POST.value,
        )
    if not marked:
        return _result("noop_attempt_moved", job.id, variant=variant)
    _LOG.warning(
        "a media attempt was found half-submitted; marked ambiguous, not re-posted",
        extra={"media_job_id": str(job.id), "variant": variant, "attempt": attempt},
    )
    await _after_attempt(rt, job.id, variant, attempt, MediaAttemptStatus.AMBIGUOUS)
    return _result("reconciled_ambiguous", job.id, variant=variant)


# ---------------------------------------------------------------------------
# media_poll (§3.3)
# ---------------------------------------------------------------------------
def _handle(job: MediaJobRow, row: MediaAttemptRow) -> JobHandle:
    return JobHandle(
        provider=row.provider,
        remote_id=row.remote_id or "",
        kind=_kind_name(job.kind),
        model_key=row.model_id or job.model_id or "",
    )


async def _discard_late(rt: MediaRuntime, job_id: UUID, variant: int, attempt_id: UUID) -> None:
    """A result for a job that already ended (deadline, ``/forget``, an output block): free
    the slot — CAS, so only if this attempt still holds it — and walk away (§3.3 "Late
    results")."""
    await _gpu_call("release", rt.gpu.release(str(attempt_id)), False)
    await _gpu_call("leave", rt.gpu.leave(queue_member(job_id, variant)), None)


async def media_poll(
    ctx: Mapping[str, Any], job_id: str, variant: int, attempt: int, tick: int = 0
) -> dict[str, Any]:
    """Ask the backend once; re-enqueue with ``tick + 1`` while it runs (§3.3)."""
    rt = media_runtime(ctx)
    jid = _uuid(job_id)
    now = rt.clock()
    async with rt.sessions() as session:
        job = await load_job(session, jid)
        row = (
            await find_attempt(
                session, jid, stage=_stage(job.kind), variant=variant, attempt=attempt
            )
            if job is not None
            else None
        )
    if row is None or row.status is not MediaAttemptStatus.SUBMITTED:
        return _result("noop_attempt_not_live", jid, variant=variant)
    if job is None or job.state is not MediaJobState.GENERATING:
        await _discard_late(rt, jid, variant, row.id)
        return _result("discarded_late", jid, variant=variant)
    uses_gpu = _backend(job) in GPU_BACKENDS
    provider = rt.providers(_backend(job))
    async with rt.sessions.begin() as session:
        await touch_job(session, jid, now=now)
    polled = await provider.poll(_handle(job, row), timeout_s=_POLL_TIMEOUT_S)
    next_poll = tick + 1
    defer = _POLL_DEFER_S[job.kind]
    if is_err(polled):
        # Transport trouble ("Network is unreachable", 5xx) is retried with backoff up to the
        # job deadline (§4.2) — the deadline sweep is what ends it.
        await enqueue_stage(
            rt,
            MEDIA_POLL_JOB,
            str(jid),
            variant,
            attempt,
            next_poll,
            job_id=poll_job_id(jid, variant, attempt, next_poll),
            defer_s=defer * 2,
        )
        return _result("poll_error", jid, variant=variant, code=polled.error.code.value)
    phase = polled.value.phase
    if not phase.is_terminal:
        queue_ms = row.queue_ms
        if phase is JobPhase.RUNNING and queue_ms is None:
            queue_ms = int((now - row.created_at).total_seconds() * 1000)
            async with rt.sessions.begin() as session:
                await set_attempt_status(
                    session,
                    row.id,
                    expected=(MediaAttemptStatus.SUBMITTED,),
                    status=MediaAttemptStatus.SUBMITTED,
                    now=now,
                    queue_ms=queue_ms,
                )
        running_ms = (
            (now - row.created_at).total_seconds() * 1000 - queue_ms
            if queue_ms is not None
            else 0.0
        )
        if running_ms > _render_timeout_s(rt, job.kind) * 1000:
            # There is no per-job cancel (``/interrupt`` is global, §4.2), so on the GPU the
            # render keeps going: the attempt is ``ambiguous`` and holds the slot until the
            # gateway's queue no longer lists it — never a retry on top of a live render.
            timed_out = MediaAttemptStatus.AMBIGUOUS if uses_gpu else MediaAttemptStatus.FAILED
            async with rt.sessions.begin() as session:
                await set_attempt_status(
                    session,
                    row.id,
                    expected=(MediaAttemptStatus.SUBMITTED,),
                    status=timed_out,
                    now=now,
                    error_code=MediaErrorCode.RENDER_TIMEOUT.value,
                )
            await _after_attempt(rt, jid, variant, attempt, timed_out)
            return _result("render_timeout", jid, variant=variant)
        if uses_gpu:
            await _gpu_call(
                "renew",
                rt.gpu.renew(str(row.id), ttl_ms=_render_timeout_s(rt, job.kind) * 1000),
                False,
            )
        await _refresh_progress(rt, jid)
        await enqueue_stage(
            rt,
            MEDIA_POLL_JOB,
            str(jid),
            variant,
            attempt,
            next_poll,
            job_id=poll_job_id(jid, variant, attempt, next_poll),
            defer_s=defer,
        )
        return _result("running", jid, variant=variant, phase=phase.value)
    status = ATTEMPT_STATUS_FOR_PHASE[phase]
    total_ms = int((now - row.created_at).total_seconds() * 1000)
    async with rt.sessions.begin() as session:
        await set_attempt_status(
            session,
            row.id,
            expected=(MediaAttemptStatus.SUBMITTED,),
            status=status,
            now=now,
            run_ms=max(0, total_ms - (row.queue_ms or 0))
            if status is MediaAttemptStatus.SUCCEEDED
            else None,
            error_code=None if status is MediaAttemptStatus.SUCCEEDED else phase.value,
        )
    if status is MediaAttemptStatus.SUCCEEDED:
        await enqueue_stage(
            rt,
            MEDIA_FETCH_JOB,
            str(jid),
            variant,
            attempt,
            job_id=fetch_job_id(jid, variant, attempt),
        )
        return _result("succeeded", jid, variant=variant)
    if uses_gpu and status is not MediaAttemptStatus.AMBIGUOUS:
        # ``unknown`` (ambiguous) keeps the slot while it is reconciled (§4.2).
        await _gpu_call("release", rt.gpu.release(str(row.id)), False)
    await _after_attempt(rt, jid, variant, attempt, status)
    return _result("attempt_ended", jid, variant=variant, status=status.value)


# ---------------------------------------------------------------------------
# media_fetch (§3.3): always releases the slot
# ---------------------------------------------------------------------------
def _job_try(ctx: Mapping[str, Any]) -> int:
    value = ctx.get("job_try", 1)
    return value if isinstance(value, int) and value > 0 else 1


async def media_fetch(
    ctx: Mapping[str, Any], job_id: str, variant: int, attempt: int
) -> dict[str, Any]:
    """Stream the result to the workspace, re-encode, store it, fan in. Releases the GPU slot
    whatever happens — CAS on the attempt id, so a late fetch frees nobody else's lock."""
    rt = media_runtime(ctx)
    jid = _uuid(job_id)
    async with rt.sessions() as session:
        job = await load_job(session, jid)
        row = (
            await find_attempt(
                session, jid, stage=_stage(job.kind), variant=variant, attempt=attempt
            )
            if job is not None
            else None
        )
    if row is None or row.status is not MediaAttemptStatus.SUCCEEDED:
        return _result("noop_attempt_not_succeeded", jid, variant=variant)
    try:
        if job is None or job.state is not MediaJobState.GENERATING:
            await _gpu_call("leave", rt.gpu.leave(queue_member(jid, variant)), None)
            return _result("discarded_late", jid, variant=variant)
        return await _fetch(rt, ctx, job, row)
    finally:
        await _gpu_call("release", rt.gpu.release(str(row.id)), False)


async def _fetch(
    rt: MediaRuntime, ctx: Mapping[str, Any], job: MediaJobRow, row: MediaAttemptRow
) -> dict[str, Any]:
    variant = row.variant
    if job.kind is MediaKind.VIDEO:
        return await _fetch_video(rt, ctx, job, row)
    outdir = media_workspace(rt, job.id) / "out"
    raw = outdir / f"raw-{variant}-{row.attempt}.part"
    provider = rt.providers(_backend(job))
    fetched = await provider.fetch(
        _handle(job, row),
        0,
        raw,
        max_bytes=_RESULT_MAX_BYTES[job.kind],
        timeout_s=_FETCH_TIMEOUT_S,
    )
    if is_err(fetched):
        return await _fetch_failed(rt, ctx, job, row, fetched.error)
    filename = f"image-{variant}.jpg"
    final = outdir / filename
    clean = await asyncio.to_thread(_to_clean_jpeg, fetched.value.path, final)
    raw.unlink(missing_ok=True)
    if isinstance(clean, ValidationError):
        return await _fetch_failed(rt, ctx, job, row, clean)
    if await _is_forgotten(rt, job.id):
        # §9.3: /forget ran while this rendered. The result is never stored — a new output
        # row written after the erasure would outlive it by the whole output period.
        final.unlink(missing_ok=True)
        await _gpu_call("leave", rt.gpu.leave(queue_member(job.id, variant)), None)
        await fail_job(
            rt,
            job.id,
            expected=_WORKING_STATES,
            error_code=MediaErrorCode.FORGET_REQUESTED,
            refund=None,
            notify=False,
        )
        return _result("discarded_forgotten", job.id, variant=variant)
    stored = await rt.storage.put_file(
        media_key(job.id, is_output=True, filename=filename), final, content_type=_JPEG_MIME
    )
    if is_err(stored):
        return await _fetch_failed(rt, ctx, job, row, stored.error)
    width, height = clean
    async with rt.sessions.begin() as session:
        await add_output(
            session,
            job_id=job.id,
            role=MediaOutputRole.IMAGE,
            variant=variant,
            storage_key=stored.value.key,
            now=rt.clock(),
            mime=_JPEG_MIME,
            size_bytes=stored.value.size_bytes,
            sha256=stored.value.sha256,
            width=width,
            height=height,
            policy=_policy(rt),
        )
    await _gpu_call("leave", rt.gpu.leave(queue_member(job.id, variant)), None)
    await image_fan_in(rt, job.id)
    return _result("fetched", job.id, variant=variant)


async def _fetch_video(
    rt: MediaRuntime, ctx: Mapping[str, Any], job: MediaJobRow, row: MediaAttemptRow
) -> dict[str, Any]:
    """The clip → ffprobe-verified, streamable ``video_raw`` → ``render_ready_at`` → fan-in.

    The render is silent (Wan has no audio; §4.3 sends ``sound:"off"``), and whatever came
    back is re-wrapped — or re-encoded when it is not H.264 ``yuv420p`` — so the mux can
    stream-copy it and Telegram can play it inline. A file ffprobe does not read as a video is
    a failed attempt, and the retry policy decides (§3.3 "Retries").
    """
    outdir = media_workspace(rt, job.id) / "out"
    raw = outdir / f"raw-{row.variant}-{row.attempt}.part"
    provider = rt.providers(_backend(job))
    fetched = await provider.fetch(
        _handle(job, row),
        0,
        raw,
        max_bytes=_RESULT_MAX_BYTES[job.kind],
        timeout_s=_FETCH_TIMEOUT_S,
    )
    if is_err(fetched):
        return await _fetch_failed(rt, ctx, job, row, fetched.error)
    # This run's own file and object key (``_take_name``): a sweep re-drive racing a slow
    # fetch, or a retry after a failure left an object behind, never replaces the bytes the
    # winning ``video_raw`` row hashes — or ``media_mux`` would fail its sha256 check.
    final = outdir / _take_name(_VIDEO_RAW_FILENAME)
    normalised = await rt.video.normalise(fetched.value.path, final)
    raw.unlink(missing_ok=True)
    if is_err(normalised):
        return await _fetch_failed(rt, ctx, job, row, normalised.error)
    if await _is_forgotten(rt, job.id):
        final.unlink(missing_ok=True)
        await _gpu_call("leave", rt.gpu.leave(queue_member(job.id, row.variant)), None)
        await fail_job(
            rt,
            job.id,
            expected=_WORKING_STATES,
            error_code=MediaErrorCode.FORGET_REQUESTED,
            refund=None,
            notify=False,
        )
        return _result("discarded_forgotten", job.id, variant=row.variant)
    stored = await rt.storage.put_file(
        media_key(job.id, is_output=True, filename=final.name),
        final,
        content_type=_VIDEO_MIME,
    )
    if is_err(stored):
        final.unlink(missing_ok=True)
        return await _fetch_failed(rt, ctx, job, row, stored.error)
    clip = normalised.value
    now = rt.clock()
    async with rt.sessions.begin() as session:
        wrote = await add_output(
            session,
            job_id=job.id,
            role=MediaOutputRole.VIDEO_RAW,
            variant=row.variant,
            storage_key=stored.value.key,
            now=now,
            mime=_VIDEO_MIME,
            size_bytes=stored.value.size_bytes,
            sha256=stored.value.sha256,
            width=clip.width,
            height=clip.height,
            duration_ms=round(clip.duration_s * 1000),
            policy=_policy(rt),
        )
        await session.execute(
            sa.update(MediaJobRow)
            .where(MediaJobRow.id == job.id, MediaJobRow.state == MediaJobState.GENERATING)
            .values(render_ready_at=now, updated_at=now)
        )
    if wrote:
        # The mux materialises to the fixed name and finds the winner's bytes already there.
        final.replace(outdir / _VIDEO_RAW_FILENAME)
    else:
        await rt.storage.delete(stored.value.key)
        final.unlink(missing_ok=True)
    await _gpu_call("leave", rt.gpu.leave(queue_member(job.id, row.variant)), None)
    await video_fan_in(rt, job.id)
    return _result("fetched", job.id, variant=row.variant)


async def _fetch_failed(
    rt: MediaRuntime,
    ctx: Mapping[str, Any],
    job: MediaJobRow,
    row: MediaAttemptRow,
    error: BayramError,
) -> dict[str, Any]:
    """Retry a transient fetch through ARQ a few times; after that the attempt counts as a
    failed one and the retry policy decides (a fresh render, or the variant is lost)."""
    if error.is_retryable and _job_try(ctx) < MEDIA_STAGE_MAX_TRIES:
        raise Retry(defer=rt.settings.provider_backoff_base_s * _job_try(ctx))
    _LOG.warning("a media result could not be fetched", extra=error.to_log_dict())
    async with rt.sessions.begin() as session:
        await set_attempt_status(
            session,
            row.id,
            expected=(MediaAttemptStatus.SUCCEEDED,),
            status=MediaAttemptStatus.FAILED,
            now=rt.clock(),
            error_code=MediaErrorCode.FETCH_FAILED.value,
        )
    await _after_attempt(rt, job.id, row.variant, row.attempt, MediaAttemptStatus.FAILED)
    return _result("fetch_failed", job.id, variant=row.variant)


async def _is_forgotten(rt: MediaRuntime, job_id: UUID) -> bool:
    """Read fresh: /forget may have marked the row since this stage loaded it."""
    async with rt.sessions() as session:
        stamp = await session.scalar(
            sa.select(MediaJobRow.forget_requested_at).where(MediaJobRow.id == job_id)
        )
    return stamp is not None


# ---------------------------------------------------------------------------
# Fan-in (§3.3)
# ---------------------------------------------------------------------------
async def _lock_job_row(session: AsyncSession, job_id: UUID) -> None:
    """``SELECT … FOR UPDATE`` on the job, so two variants finishing at once count serially.

    Without it, two fetches committing concurrently under READ COMMITTED could each count only
    its own output and neither would move the job. A no-op on SQLite, whose writers are
    serialised anyway.
    """
    await session.execute(
        sa.select(MediaJobRow.id).where(MediaJobRow.id == job_id).with_for_update()
    )


async def image_fan_in(rt: MediaRuntime, job_id: UUID) -> None:
    """When every variant is terminal: ≥ 1 image → ``post`` and the output screen; none →
    ``failed`` with one refund credit. The conditional move is the idempotency (§3.3).

    The all-failed branch runs from ``queued`` too: ``queued → generating`` happens only on a
    successful POST, so a job whose every submit failed (gateway down, an unbuilt backend)
    never reaches ``generating`` — and would otherwise wait out its whole deadline.
    """
    now = rt.clock()
    oscreen_seq: int | None = None
    all_failed = False
    async with rt.sessions.begin() as session:
        await _lock_job_row(session, job_id)
        job = await load_job(session, job_id)
        if job is None or job.state not in _WORKING_STATES:
            return
        successes = {
            output.variant
            for output in await list_outputs(session, job_id, role=MediaOutputRole.IMAGE)
        }
        latest = await latest_attempts(session, job_id, stage=MediaAttemptStage.IMAGE)
        failures = {
            variant
            for variant, row in latest.items()
            if variant not in successes and is_attempt_final(row, rt.settings.media_max_attempts)
        }
        if len(successes) + len(failures) < job.outputs_requested:
            return
        if successes:
            if await transition(
                session,
                job_id,
                expected=(MediaJobState.GENERATING,),
                to=MediaJobState.POST,
                now=now,
            ):
                oscreen_seq = job.oscreen_seq
        else:
            all_failed = True
    if oscreen_seq is not None:
        await enqueue_stage(
            rt,
            MEDIA_OUTPUT_SCREEN_JOB,
            str(job_id),
            oscreen_seq,
            job_id=output_screen_job_id(job_id, oscreen_seq),
        )
    elif all_failed:
        await fail_job(
            rt,
            job_id,
            expected=_WORKING_STATES,
            error_code=MediaErrorCode.GENERATION_FAILED,
            refund=MediaCreditReason.GENERATION_FAILED,
        )


async def video_fan_in(rt: MediaRuntime, job_id: UUID) -> bool:
    """Whichever of render and narration finishes second moves ``generating → post`` and
    enqueues ``media_mux`` (§3.3). The conditional UPDATE fires once whatever the order.

    Each producer (the video fetch, ``media_tts``, ``media_voice_prepare``) COMMITS its own
    ``*_ready_at`` before calling this, so the second caller's UPDATE — which waits on the
    first's row lock and re-reads the row — sees both, and the first's sees at most one. A
    narration ready while the render still queues finds the row ``queued`` and changes
    nothing; the render's fetch is then the second, and fires it.
    """
    async with rt.sessions.begin() as session:
        result = await session.execute(
            sa.update(MediaJobRow)
            .where(
                MediaJobRow.id == job_id,
                MediaJobRow.state == MediaJobState.GENERATING,
                MediaJobRow.render_ready_at.is_not(None),
                sa.or_(
                    MediaJobRow.voice_mode == MediaVoiceMode.NONE,
                    MediaJobRow.audio_ready_at.is_not(None),
                ),
            )
            .values(state=MediaJobState.POST, updated_at=rt.clock())
        )
        moved = int(getattr(result, "rowcount", 0) or 0) == 1
    if moved:
        await enqueue_stage(rt, MEDIA_MUX_JOB, str(job_id), 0, job_id=mux_job_id(job_id))
    return moved


# ---------------------------------------------------------------------------
# media_output_screen (§3.3, §6.4 L4)
# ---------------------------------------------------------------------------
async def _output_paths(rt: MediaRuntime, job: MediaJobRow) -> Result[list[tuple[UUID, Path]]]:
    async with rt.sessions() as session:
        outputs = await list_outputs(session, job.id, role=MediaOutputRole.IMAGE)
    found: list[tuple[UUID, Path]] = []
    outdir = media_workspace(rt, job.id) / "out"
    for output in outputs:
        local = await _materialise(
            rt,
            key=output.storage_key,
            sha256=output.sha256,
            dest=outdir / f"image-{output.variant}.jpg",
        )
        if is_err(local):
            return local
        found.append((output.id, local.value))
    return ok(found)


async def _delivered_video(
    rt: MediaRuntime, job: MediaJobRow
) -> Result[tuple[MediaOutputRow, Path]]:
    """The muxed clip on local disk (streamed, hash-checked) with its output row."""
    async with rt.sessions() as session:
        outputs = await list_outputs(session, job.id, role=MediaOutputRole.VIDEO)
    if not outputs:
        return err(
            StorageError("the video has no muxed output", context={"media_job_id": str(job.id)})
        )
    output = outputs[0]
    local = await _materialise_file(
        rt,
        key=output.storage_key,
        sha256=output.sha256,
        dest=media_workspace(rt, job.id) / "out" / _VIDEO_FILENAME,
    )
    if is_err(local):
        return local
    return ok((output, local.value))


async def _output_items(rt: MediaRuntime, job: MediaJobRow) -> Result[list[ImageItem]]:
    """What L4 looks at (§6.4): both images, or the first, last and 1 fps frames (≤ 8) of the
    muxed clip. The narration's words were screened at L1/L3 already."""
    if job.kind is MediaKind.IMAGE:
        paths = await _output_paths(rt, job)
        if is_err(paths):
            return paths
        return ok(
            [
                ImageItem(id=f"output-{index}", subject="output_image", path=path)
                for index, (_, path) in enumerate(paths.value)
            ]
        )
    video = await _delivered_video(rt, job)
    if is_err(video):
        return video
    frames = await rt.video.frames(video.value[1], media_workspace(rt, job.id) / "frames")
    if is_err(frames):
        return frames
    return ok(
        [
            ImageItem(id=f"frame-{index}", subject="output_frame", path=path)
            for index, path in enumerate(frames.value)
        ]
    )


async def media_output_screen(ctx: Mapping[str, Any], job_id: str, seq: int = 0) -> dict[str, Any]:
    """L4 on every output before delivery. allow → deliver; review → ``held``; block → failed
    with one credit (the whole request, even if one image was fine, §6.4); unavailable → again
    in two minutes with ``oscreen_seq + 1``, for at most 30, then ``held``."""
    rt = media_runtime(ctx)
    jid = _uuid(job_id)
    now = rt.clock()
    async with rt.sessions() as session:
        job = await load_job(session, jid)
    if job is None or job.state is not MediaJobState.POST:
        return _result("noop_not_post", jid)
    if job.forget_requested_at is not None:
        await fail_job(
            rt,
            jid,
            expected=(MediaJobState.POST,),
            error_code=MediaErrorCode.FORGET_REQUESTED,
            refund=None,
            notify=False,
        )
        return _result("failed_forgotten", jid)
    items = await _output_items(rt, job)
    decision = MediaScreenDecision.UNAVAILABLE
    categories: tuple[CategoryCode, ...] = ()
    # No outputs to look at is ``unavailable``, never an ``allow`` of nothing (§6.3): a job
    # that reached ``post`` without its outputs (a video whose frames could not be read)
    # retries and is finally held, and is never delivered unscreened.
    if not is_err(items) and items.value:
        verdict = await rt.moderator.screen_images(
            items.value,
            policy=MEDIA_POLICY_VERSION,
            lang_hint=lang_hint_for(job.language),
        )
        if not is_err(verdict):
            decision, categories = verdict.value.decision, verdict.value.categories
    # The words' youth signal meets the pictures' codes here (§6.4 hard rule).
    decision, categories = apply_hard_rule(decision, categories, youth_signal=_youth_in_words(job))
    values: dict[str, Any] = {
        "output_decision": decision,
        "output_categories": [code.value for code in categories],
    }
    if decision is MediaScreenDecision.ALLOW:
        async with rt.sessions.begin() as session:
            await session.execute(
                sa.update(MediaJobRow)
                .where(MediaJobRow.id == jid, MediaJobRow.state == MediaJobState.POST)
                .values(updated_at=now, **values)
            )
        await enqueue_stage(rt, MEDIA_DELIVER_JOB, str(jid), job_id=deliver_job_id(jid))
        return _result("allowed", jid)
    if decision is MediaScreenDecision.BLOCK:
        # Either image blocked fails the whole request: nothing is delivered, one credit,
        # two strikes (§6.4 L4). A CSAM-class block holds every input and output in the move's
        # own transaction (§6.7).
        is_csam = is_csam_class(decision, categories)
        failed = await fail_job(
            rt,
            jid,
            expected=(MediaJobState.POST,),
            error_code=MediaErrorCode.CSAM_BLOCKED if is_csam else MediaErrorCode.OUTPUT_BLOCKED,
            refund=MediaCreditReason.OUTPUT_BLOCKED,
            values=values,
            legal_hold=is_csam,
        )
        if failed and is_csam:
            await _escalate_csam(rt, job, layer="output", categories=categories)
        elif failed:
            await _strike(rt, job, layer="output", weight=OUTPUT_BLOCK_STRIKES, is_csam=False)
        return _result("blocked", jid, csam=is_csam)
    give_up = decision is MediaScreenDecision.REVIEW or (
        timedelta(seconds=_OSCREEN_RETRY_S) * (seq + 1) >= _OSCREEN_GIVE_UP
    )
    if give_up:
        # A human decides (§6.6, M3.2): release → deliver, or 24 h → fail + refund. The review
        # opens in the move's own transaction, so a held job is never missing from the queue.
        async with rt.sessions.begin() as session:
            held = await transition(
                session,
                jid,
                expected=(MediaJobState.POST,),
                to=MediaJobState.HELD,
                now=now,
                values=values,
            )
            if held:
                await open_review(
                    session,
                    jid,
                    kind=job.kind,
                    source=(
                        MediaReviewSource.OUTPUT_REVIEW
                        if decision is MediaScreenDecision.REVIEW
                        else MediaReviewSource.GUARD_UNAVAILABLE
                    ),
                    categories=[code.value for code in categories],
                    now=now,
                )
        return _result("held", jid, decision=decision.value)
    async with rt.sessions.begin() as session:
        next_seq = await bump_seq(session, jid, column="oscreen_seq", now=now)
    if next_seq is not None:
        await enqueue_stage(
            rt,
            MEDIA_OUTPUT_SCREEN_JOB,
            str(jid),
            next_seq,
            job_id=output_screen_job_id(jid, next_seq),
            defer_s=_OSCREEN_RETRY_S,
        )
    return _result("guard_unavailable", jid, seq=next_seq)


# ---------------------------------------------------------------------------
# media_deliver (§3.3)
# ---------------------------------------------------------------------------
async def media_deliver(ctx: Mapping[str, Any], job_id: str) -> dict[str, Any]:
    """``post``/``held`` (allowed) → ``delivering`` → one album → ``delivered``.

    The move to ``delivering`` is the claim, made BEFORE the send: two copies of this job
    cannot both send. A send that failed for a reason worth retrying puts the row back to
    ``post`` and retries; a customer who blocked the bot ends the job without a credit — the
    images were made, and a refund for our own work would be a free render.
    """
    rt = media_runtime(ctx)
    jid = _uuid(job_id)
    now = rt.clock()
    async with rt.sessions() as session:
        job = await load_job(session, jid)
    if (
        job is None
        or job.state not in (MediaJobState.POST, MediaJobState.HELD)
        or job.output_decision is not MediaScreenDecision.ALLOW
        or job.delivered_at is not None
    ):
        return _result("noop_not_deliverable", jid)
    if job.forget_requested_at is not None:
        await fail_job(
            rt,
            jid,
            expected=(MediaJobState.POST, MediaJobState.HELD),
            error_code=MediaErrorCode.FORGET_REQUESTED,
            refund=None,
            notify=False,
        )
        return _result("failed_forgotten", jid)
    video: MediaOutputRow | None = None
    paths: Result[list[tuple[UUID, Path]]]
    if job.kind is MediaKind.VIDEO:
        clip = await _delivered_video(rt, job)
        if is_err(clip):
            paths = clip
        else:
            video = clip.value[0]
            paths = ok([(video.id, clip.value[1])])
    else:
        paths = await _output_paths(rt, job)
    if is_err(paths):
        await fail_job(
            rt,
            jid,
            expected=(MediaJobState.POST, MediaJobState.HELD),
            error_code=MediaErrorCode.DELIVERY_FAILED,
            refund=MediaCreditReason.GENERATION_FAILED,
        )
        return _result("failed_outputs_missing", jid)
    previous = job.state
    async with rt.sessions.begin() as session:
        claimed = await transition(
            session,
            jid,
            expected=(previous,),
            to=MediaJobState.DELIVERING,
            now=now,
        )
    if not claimed:
        return _result("noop_claimed_elsewhere", jid)
    try:
        sent = await _send_outputs(rt, job, paths.value, video)
    except BaseException:
        # The messenger never raises by contract; if it does, the claim is handed back so the
        # re-run can take it — a row left in ``delivering`` is one nothing else moves but the
        # sweep. (A worker killed outright is that sweep's case: ``media_sweep`` arm f.)
        async with rt.sessions.begin() as session:
            await transition(
                session, jid, expected=(MediaJobState.DELIVERING,), to=previous, now=rt.clock()
            )
        raise
    if is_err(sent):
        return await _delivery_failed(rt, ctx, job, previous, sent.error)
    async with rt.sessions.begin() as session:
        for (output_id, _), file_id in zip(paths.value, sent.value, strict=False):
            if file_id:
                await record_output_file_id(session, output_id, tg_file_id=file_id)
        await transition(
            session,
            jid,
            expected=(MediaJobState.DELIVERING,),
            to=MediaJobState.DELIVERED,
            now=rt.clock(),
            values={"delivered_at": rt.clock()},
            policy=_policy(rt),
        )
        # Q3: a variant that failed TO GENERATE still costs the customer a credit's worth —
        # deliver the good one and refund one (never for an output we blocked: that path
        # failed the whole request at the output screen). None for a beta job (§7.5).
        partial = len(paths.value) < job.outputs_requested
        refunded = partial and await grant_refund(
            session, jid, reason=MediaCreditReason.GENERATION_FAILED, now=rt.clock()
        )
    if partial:
        kind = _translate(job, _KIND_LABEL_KEYS[job.kind])
        note = (
            _translate(job, _PARTIAL_REFUNDED_KEY, kind=kind)
            if refunded
            else _translate(job, _PARTIAL_KEY)
        )
        await rt.messenger.send(job.chat_id, note)
    await rt.messenger.send(job.chat_id, _translate(job, _AGAIN_KEY), _again(job))
    await enqueue_stage(rt, MEDIA_CLEANUP_JOB, str(jid), job_id=cleanup_job_id(jid))
    return _result("delivered", jid, photos=len(sent.value), partial_refund=refunded)


async def _send_outputs(
    rt: MediaRuntime,
    job: MediaJobRow,
    paths: Sequence[tuple[UUID, Path]],
    video: MediaOutputRow | None,
) -> Result[tuple[str, ...]]:
    """One album of the images, or the clip by ``sendVideo`` with the geometry and duration
    ffprobe measured (a document above 50 MB, ``media_telegram``). The ``file_id`` of each."""
    if video is None:
        return await rt.messenger.send_photos(
            job.chat_id,
            [path for _, path in paths],
            caption=_translate(job, _DELIVERED_KEY),
        )
    sent = await rt.messenger.send_video(
        job.chat_id,
        paths[0][1],
        caption=_translate(job, _VIDEO_DELIVERED_KEY),
        width=video.width,
        height=video.height,
        duration_s=video.duration_ms / 1000 if video.duration_ms else None,
    )
    if is_err(sent):
        return sent
    return ok((sent.value,))


async def _delivery_failed(
    rt: MediaRuntime,
    ctx: Mapping[str, Any],
    job: MediaJobRow,
    previous: MediaJobState,
    error: BayramError,
) -> dict[str, Any]:
    if error.context.get(BLOCKED_BY_CUSTOMER_KEY):
        await fail_job(
            rt,
            job.id,
            expected=(MediaJobState.DELIVERING,),
            error_code=MediaErrorCode.CUSTOMER_BLOCKED,
            refund=None,
            notify=False,
        )
        return _result("customer_blocked", job.id)
    if error.is_retryable and _job_try(ctx) < MEDIA_STAGE_MAX_TRIES:
        async with rt.sessions.begin() as session:
            await transition(
                session,
                job.id,
                expected=(MediaJobState.DELIVERING,),
                to=previous,
                now=rt.clock(),
            )
        retry_after = error.context.get("retry_after")
        defer = (
            float(retry_after)
            if isinstance(retry_after, int | float)
            else rt.settings.provider_backoff_base_s * _job_try(ctx)
        )
        raise Retry(defer=defer)
    await fail_job(
        rt,
        job.id,
        expected=(MediaJobState.DELIVERING,),
        error_code=MediaErrorCode.DELIVERY_FAILED,
        refund=MediaCreditReason.GENERATION_FAILED,
    )
    return _result("delivery_failed", job.id)


# ---------------------------------------------------------------------------
# media_review_apply (§6.6, M3.2)
# ---------------------------------------------------------------------------
#: ``moderation_reviews.actor`` is the operator's username; the ledger reads ``admin:{name}``,
#: the vocabulary ``credit_ledger.actor`` already uses for an operator-caused movement.
_ADMIN_ACTOR_PREFIX: Final[str] = "admin:"


async def media_review_apply(
    ctx: Mapping[str, Any], review_id: str, tick: int = 0
) -> dict[str, Any]:
    """Carry out a decided review on its ``held`` job. Idempotent; ``tick`` only varies the id.

    * ``released`` → the output is marked allowed and delivered by ``media_deliver`` under a
      review-scoped id (the plain deliver id may already have been spent by a delivery that
      stood down when the job was held) — **except a ``guard_unavailable`` hold**, whose
      output no guard ever screened and no reviewer can see (output reveal is M5): there a
      release moves the job back to ``post`` and asks the output screen again, so only a
      real guard ``allow`` delivers it (a guard still down holds it again, a new review);
    * ``blocked`` → failed with one SKU-scoped credit (none for beta, §7.5), attributed to the
      operator, the customer told non-specifically, two strikes as for an L4 block (§6.4);
    * ``expired`` → the same failure and credit, and no strike: nobody judged it unsafe.

    ``applied_at`` is stamped after the job moved (or was found already moved), so a crash in
    between re-runs to the same end: every job move here is conditional on ``held``.
    """
    rt = media_runtime(ctx)
    rid = _uuid(review_id)
    now = rt.clock()
    async with rt.sessions() as session:
        review = await load_review(session, rid)
        job = await load_job(session, review.job_id) if review is not None else None
    if review is None or review.decision is None:
        return _result("noop_undecided", review_id, review_id=review_id)
    if review.applied_at is not None:
        return _result("noop_applied", review.job_id, review_id=review_id)
    if job is None:
        async with rt.sessions.begin() as session:
            await mark_applied(session, rid, now=now)
        return _result("noop_job_gone", review.job_id, review_id=review_id)
    outcome: str
    if (
        review.decision is MediaReviewDecision.RELEASED
        and review.source is MediaReviewSource.GUARD_UNAVAILABLE
    ):
        seq: int | None = None
        async with rt.sessions.begin() as session:
            back = await transition(
                session,
                job.id,
                expected=(MediaJobState.HELD,),
                to=MediaJobState.POST,
                now=now,
                values={"output_decision": None, "output_categories": None},
            )
            if back:
                seq = await bump_seq(session, job.id, column="oscreen_seq", now=now)
            await mark_applied(session, rid, now=now)
        outcome = "rescreen" if back else "noop_not_held"
        if seq is not None:
            await enqueue_stage(
                rt,
                MEDIA_OUTPUT_SCREEN_JOB,
                str(job.id),
                seq,
                job_id=output_screen_job_id(job.id, seq),
            )
    elif review.decision is MediaReviewDecision.RELEASED:
        async with rt.sessions.begin() as session:
            released = await session.execute(
                sa.update(MediaJobRow)
                .where(MediaJobRow.id == job.id, MediaJobRow.state == MediaJobState.HELD)
                .values(output_decision=MediaScreenDecision.ALLOW, updated_at=now)
            )
            await mark_applied(session, rid, now=now)
        outcome = "released" if rowcount_of(released) == 1 else "noop_not_held"
        if outcome == "released":
            await enqueue_stage(
                rt,
                MEDIA_DELIVER_JOB,
                str(job.id),
                job_id=deliver_job_id(job.id, _review_deliver_suffix(rid)),
            )
    else:
        is_block = review.decision is MediaReviewDecision.BLOCKED
        failed = await fail_job(
            rt,
            job.id,
            expected=(MediaJobState.HELD,),
            error_code=(
                MediaErrorCode.REVIEW_BLOCKED if is_block else MediaErrorCode.REVIEW_EXPIRED
            ),
            refund=MediaCreditReason.OUTPUT_BLOCKED,
            refund_actor=(
                f"{_ADMIN_ACTOR_PREFIX}{review.actor}" if is_block and review.actor else None
            ),
        )
        if failed and is_block:
            await _strike(rt, job, layer="review", weight=OUTPUT_BLOCK_STRIKES, is_csam=False)
        async with rt.sessions.begin() as session:
            await mark_applied(session, rid, now=rt.clock())
        outcome = ("blocked" if is_block else "expired") if failed else "noop_not_held"
    return _result(outcome, job.id, review_id=review_id, tick=tick)


def _review_deliver_suffix(review_id: UUID) -> int:
    """A deliver-id suffix of the review's own (its low 48 bits), so a release never reuses
    the plain deliver id or a sweep tick's."""
    return review_id.int & 0xFFFF_FFFF_FFFF


# ---------------------------------------------------------------------------
# media_cleanup (§3.3, O16)
# ---------------------------------------------------------------------------
async def media_cleanup(ctx: Mapping[str, Any], job_id: str) -> dict[str, Any]:
    """Delete the uploads (objects and rows), the intermediates and the workspace of a
    finished job — **skipping every legal-hold row**, whose objects it seals instead (§6.7).
    Idempotent.

    The gateway keeps its own copy of every input it was sent; deleting that (G6, §9.2) is a
    gateway change the owner makes, so it is not called from here yet.
    """
    rt = media_runtime(ctx)
    jid = _uuid(job_id)
    async with rt.sessions() as session:
        job = await load_job(session, jid)
    if job is not None and job.state not in MEDIA_TERMINAL_STATES:
        return _result("noop_not_terminal", jid)
    keys: tuple[str, ...] = ()
    if job is not None:
        # Held bytes stay — sealed, if the stage that held them died before sealing (§6.7).
        # A seal that raises must not keep the ordinary uploads from being deleted (O16).
        try:
            await seal_held_objects(
                rt.sessions, rt.storage, jid, public_key=rt.settings.media_legal_hold_recipient
            )
        except Exception as exc:
            _LOG.error(
                "legal-hold bytes could not be sealed at cleanup",
                extra={"media_job_id": str(jid), "failure": type(exc).__name__},
            )
        async with rt.sessions.begin() as session:
            keys = await cleanup_job_media(session, jid)
        await _gpu_call("leave", rt.gpu.leave(*_members(job)), None)
    failed = 0
    for key in keys:
        deleted = await rt.storage.delete(key)
        if is_err(deleted):
            failed += 1
            _LOG.warning("a media object could not be deleted", extra={"key": key})
    await asyncio.to_thread(shutil.rmtree, media_workspace(rt, jid), True)
    return _result("cleaned", jid, objects=len(keys), failed=failed)


# ---------------------------------------------------------------------------
# media_script (§2.4.2, §5.5): 🤖 "AI writes" on a prescreened draft
# ---------------------------------------------------------------------------
async def media_script(ctx: Mapping[str, Any], job_id: str, n: int = 0) -> dict[str, Any]:
    """Write line ``n`` for a ``drafting`` video whose prompt the prescreen allowed, re-screen
    it at L3, and turn the tray into ``media.voice.script_review`` (✅ / ✏️ / 🔄).

    The prompt is read from the row — never from ARQ arguments — and only once the prescreen
    allowed it (§2.4.1). Each line counts once against the screening budget (§6.4 L0), and
    this job writes ONE line: a line L3 refuses is never shown, and the tray offers 🔄 while
    any regenerations are left — so the next line is the customer's own 🔄, spending both a
    regeneration and a screening (§6.4 L3 "counts against regens"; a silent in-job retry would
    let a draft probe the guard past its metered budget). A writer, guard or strike store that
    cannot answer leaves the draft as it is and says so on the tray, with ✏️ to type the
    words instead — fail closed, no line is ever shown unscreened, and never ``media.busy``,
    whose 🔁 re-runs only the (already allowed) prescreen and would strand the tray.
    """
    rt = media_runtime(ctx)
    jid = _uuid(job_id)
    async with rt.sessions() as session:
        job = await load_job(session, jid)
    if (
        job is None
        or job.kind is not MediaKind.VIDEO
        or job.state is not MediaJobState.DRAFTING
        or job.voice_mode is not MediaVoiceMode.AI_LLM
    ):
        return _result("noop_not_asking", jid, n=n)
    if (
        job.screen_decision is not MediaScreenDecision.ALLOW
        or job.screen_policy_version != MEDIA_POLICY_VERSION
    ):
        return _result("noop_not_prescreened", jid, n=n)
    if job.narration_text:
        return _result("noop_written", jid, n=n)
    can_regenerate = n < rt.settings.media_script_max_regens
    gated = await _screen_gate(rt, job, budget_id=f"{jid}:script:{n}", draw_busy=False)
    if gated is not None and gated["outcome"] != _GATE_UNREADABLE:
        return gated
    line: str | None = None
    if gated is None and rt.script_writer is not None:
        written = await rt.script_writer.write(
            job.prompt or "",
            language=job.language,
            budget=narration_budget(rt.settings, job.language),
        )
        if not is_err(written):
            verdict = await rt.moderator.screen_text(
                [TextItem(id="script", subject="script", content=written.value)],
                policy=MEDIA_POLICY_VERSION,
                lang_hint=lang_hint_for(job.language),
            )
            if not is_err(verdict) and verdict.value.decision is MediaScreenDecision.ALLOW:
                line = written.value
            elif not is_err(verdict) and verdict.value.decision in (
                MediaScreenDecision.BLOCK,
                MediaScreenDecision.REVIEW,
            ):
                _LOG.info(
                    "a written line was refused at L3; it is not shown",
                    extra={"media_job_id": str(jid), "decision": verdict.value.decision.value},
                )
    if line is None:
        await _show_tray(
            rt,
            job,
            _translate(job, _SCRIPT_FAILED_KEY),
            media_script_review_keyboard(
                job.language, can_regenerate=can_regenerate, can_use=False
            ),
        )
        return _result("script_failed", jid, n=n)
    async with rt.sessions.begin() as session:
        stored = await session.execute(
            sa.update(MediaJobRow)
            .where(
                MediaJobRow.id == jid,
                MediaJobRow.state == MediaJobState.DRAFTING,
                MediaJobRow.voice_mode == MediaVoiceMode.AI_LLM,
                MediaJobRow.narration_text.is_(None),
            )
            .values(narration_text=line, updated_at=rt.clock())
        )
    if rowcount_of(stored) != 1:
        return _result("noop_lost_race", jid, n=n)
    await _show_tray(
        rt,
        job,
        _translate(job, _SCRIPT_REVIEW_KEY, script=line),
        media_script_review_keyboard(job.language, can_regenerate=can_regenerate),
    )
    return _result("script_written", jid, n=n)


# ---------------------------------------------------------------------------
# media_tts / media_voice_prepare (§5): the voice, beside the render
# ---------------------------------------------------------------------------
async def _voice_job(
    rt: MediaRuntime, jid: UUID, modes: Collection[MediaVoiceMode]
) -> MediaJobRow | None:
    """The job, when it is a working video with one of ``modes`` and no voice yet."""
    async with rt.sessions() as session:
        job = await load_job(session, jid)
    if (
        job is None
        or job.kind is not MediaKind.VIDEO
        or job.voice_mode not in modes
        or job.state not in _WORKING_STATES
        or job.forget_requested_at is not None
    ):
        return None
    return job


def voice_lease_key(job_id: UUID) -> str:
    """The memo key a running voice stage holds (:func:`is_voice_leased`)."""
    return f"media:{job_id}:voice:lease"


async def _take_voice_lease(rt: MediaRuntime, job_id: UUID) -> None:
    """Stamp "a voice run is working on this job" for one stage timeout (§3.3), so the sweep
    does not start a second paid narration beside a slow first one. Best effort: a Redis that
    cannot answer only costs the de-duplication, never the voice."""
    try:
        await rt.memo.set(
            voice_lease_key(job_id), "1", ex=max(1, int(rt.settings.queue_job_timeout_s))
        )
    except Exception as exc:
        _LOG.warning(
            "a voice lease could not be written",
            extra={"media_job_id": str(job_id), "failure": type(exc).__name__},
        )


async def is_voice_leased(rt: MediaRuntime, job_id: UUID) -> bool:
    """True while a ``media_tts``/``media_voice_prepare`` run started within one stage
    timeout — the sweep then leaves the voice alone. Unreadable reads as not leased: a lost
    voice is re-driven rather than left to hang."""
    try:
        return bool(await rt.memo.get(voice_lease_key(job_id)))
    except Exception:
        return False


async def _voice_failed(
    rt: MediaRuntime,
    ctx: Mapping[str, Any],
    job: MediaJobRow,
    error: BayramError,
    code: MediaErrorCode,
) -> dict[str, Any]:
    """A voice that could not be made. A vendor's content refusal is final (§6.4 L5: fail,
    refund, strike — but no strike for an unedited 🤖 line, ``ai_llm``: those words are ours,
    §5.5); a transient failure is retried by ARQ; the last try fails the job with one credit —
    no render is delivered without the voice the customer paid for."""
    if error.error_code is ErrorCode.CONTENT_REJECTED:
        failed = await fail_job(
            rt,
            job.id,
            expected=_WORKING_STATES,
            error_code=MediaErrorCode.NARRATION_REFUSED,
            refund=MediaCreditReason.GENERATION_FAILED,
        )
        if failed and job.voice_mode is not MediaVoiceMode.AI_LLM:
            await _strike(rt, job, layer="tts", weight=OUTPUT_BLOCK_STRIKES, is_csam=False)
        return _result("voice_refused", job.id)
    if error.is_retryable and _job_try(ctx) < MEDIA_STAGE_MAX_TRIES:
        raise Retry(defer=rt.settings.provider_backoff_base_s * _job_try(ctx))
    _LOG.warning("a video's voice could not be made", extra=error.to_log_dict())
    await fail_job(
        rt,
        job.id,
        expected=_WORKING_STATES,
        error_code=code,
        refund=MediaCreditReason.GENERATION_FAILED,
    )
    return _result("voice_failed", job.id, error_code=code.value)


async def _voice_ready(
    rt: MediaRuntime,
    ctx: Mapping[str, Any],
    job: MediaJobRow,
    path: Path,
    seconds: float,
    *,
    mime: str = _WAV_MIME,
) -> dict[str, Any]:
    """Store the voice track (an intermediate, 24 h), stamp ``audio_ready_at``, fan in.

    ``path``'s name is this run's own (``_take_name``), and so is the stored key: a sweep
    re-drive racing a slow first run can never overwrite the object the winning row hashes.
    The run whose row lost deletes its own object and only tries the fan-in. ``mime`` is what
    the bytes are: an own note is prepared as WAV; an AI voice is the vendor's answer."""
    stored = await rt.storage.put_file(
        media_key(job.id, is_output=True, filename=path.name),
        path,
        content_type=mime,
    )
    if is_err(stored):
        return await _voice_failed(rt, ctx, job, stored.error, MediaErrorCode.NARRATION_FAILED)
    now = rt.clock()
    async with rt.sessions.begin() as session:
        wrote = await add_output(
            session,
            job_id=job.id,
            role=MediaOutputRole.NARRATION,
            variant=0,
            storage_key=stored.value.key,
            now=now,
            mime=mime,
            size_bytes=stored.value.size_bytes,
            sha256=stored.value.sha256,
            duration_ms=round(seconds * 1000),
            policy=_policy(rt),
        )
        if wrote:
            await session.execute(
                sa.update(MediaJobRow)
                .where(MediaJobRow.id == job.id, MediaJobRow.state.in_(_WORKING_STATES))
                .values(audio_ready_at=now, updated_at=now)
            )
    if not wrote:
        await rt.storage.delete(stored.value.key)
    fired = await video_fan_in(rt, job.id)
    return _result("voice_ready", job.id, seconds=round(seconds, 2), fanned_in=fired)


@dataclass(frozen=True, slots=True)
class _Spoken:
    """One narration on disk: where, how long (ffprobe's figure), and what the bytes are."""

    path: Path
    seconds: float
    mime: str


async def _speak(
    rt: MediaRuntime, request: NarrationRequest, key: str, dest: Path
) -> Result[_Spoken]:
    """One narration call, written beside ``dest`` with the suffix of the MIME the vendor
    answered with (the §5.2 ElevenLabs fallback is MP3, not WAV); its length by ffprobe (the
    vendor's figure when ffprobe cannot read it)."""
    assert rt.narration is not None
    rendered = await rt.narration.narrate(
        request, idempotency_key=key, timeout_s=_NARRATION_TIMEOUT_S
    )
    if is_err(rendered):
        return rendered
    mime = rendered.value.mime.split(";", maxsplit=1)[0].strip().casefold() or _WAV_MIME
    path = dest.with_suffix(_NARRATION_SUFFIX_BY_MIME.get(mime, dest.suffix))
    path.parent.mkdir(parents=True, exist_ok=True)
    await asyncio.to_thread(path.write_bytes, rendered.value.data)
    measured = await rt.video.audio_seconds(path)
    seconds = measured.value if not is_err(measured) else rendered.value.duration_s
    return ok(_Spoken(path=path, seconds=seconds, mime=mime))


async def media_tts(ctx: Mapping[str, Any], job_id: str, n: int = 0) -> dict[str, Any]:
    """The AI voice (§5.1–§5.3): the screened ``narration_text`` in the chosen house voice.

    A line over the clip by more than the mux can absorb with ``atempo`` (§5.3: 15 %) is
    asked for once more in a brisk delivery, and the shorter of the two is kept; whatever
    still runs long is trimmed with a fade at the mux — never a failed paid job. ``n`` only
    tells a sweep re-drive from the first run.
    """
    del n
    rt = media_runtime(ctx)
    jid = _uuid(job_id)
    job = await _voice_job(rt, jid, (MediaVoiceMode.AI_USER, MediaVoiceMode.AI_LLM))
    if job is None:
        return _result("noop_no_voice_needed", jid)
    if job.audio_ready_at is not None:
        await video_fan_in(rt, jid)
        return _result("noop_voice_ready", jid)
    await _take_voice_lease(rt, jid)
    if rt.narration is None or not job.narration_text or job.voice_gender is None:
        return await _voice_failed(
            rt,
            ctx,
            job,
            PipelineError("the narration cannot be made", is_retryable=False),
            MediaErrorCode.NARRATION_FAILED,
        )
    request = NarrationRequest(
        text=job.narration_text,
        language=job.language,
        gender=VoiceGender(job.voice_gender.value),
    )
    outdir = media_workspace(rt, jid) / "out"
    spoken = await _speak(rt, request, tts_job_id(jid), outdir / _take_name(_NARRATION_FILENAME))
    if is_err(spoken):
        return await _voice_failed(rt, ctx, job, spoken.error, MediaErrorCode.NARRATION_FAILED)
    kept = spoken.value
    seconds = kept.seconds
    clip_s = float(rt.settings.narration_max_seconds)
    if seconds > clip_s * MAX_TEMPO:
        brisk = await _speak(
            rt,
            request.model_copy(update={"style": _BRISK_STYLE}),
            f"{tts_job_id(jid)}:brisk",
            outdir / _take_name(_NARRATION_FILENAME),
        )
        _LOG.info(
            "a narration ran long and was asked for again, brisk",
            extra={
                "media_job_id": str(jid),
                "language": job.language.value,
                "seconds": round(seconds, 2),
                "brisk_seconds": None if is_err(brisk) else round(brisk.value.seconds, 2),
            },
        )
        if not is_err(brisk) and brisk.value.seconds < seconds:
            kept.path.unlink(missing_ok=True)
            kept = brisk.value
            seconds = kept.seconds
        elif not is_err(brisk):
            brisk.value.path.unlink(missing_ok=True)
    return await _voice_ready(rt, ctx, job, kept.path, seconds, mime=kept.mime)


async def media_voice_prepare(ctx: Mapping[str, Any], job_id: str, n: int = 0) -> dict[str, Any]:
    """An own voice note for the mux (§5.4): the SCREENED stored copy (hash-checked, never
    re-downloaded by ``file_id``), loudness-normalised to mono 48 kHz — no cloning, no voice
    conversion. ``n`` only tells a sweep re-drive from the first run."""
    del n
    rt = media_runtime(ctx)
    jid = _uuid(job_id)
    job = await _voice_job(rt, jid, (MediaVoiceMode.OWN,))
    if job is None:
        return _result("noop_no_voice_needed", jid)
    if job.audio_ready_at is not None:
        await video_fan_in(rt, jid)
        return _result("noop_voice_ready", jid)
    await _take_voice_lease(rt, jid)
    async with rt.sessions() as session:
        rows = await list_inputs(session, jid)
    note = next((row for row in rows if row.role is MediaInputRole.VOICE_NOTE), None)
    if note is None or note.storage_key is None or note.sha256 is None:
        return await _voice_failed(
            rt,
            ctx,
            job,
            ValidationError("the screened voice note is missing"),
            MediaErrorCode.VOICE_PREPARE_FAILED,
        )
    workdir = media_workspace(rt, jid)
    local = await _materialise_file(
        rt, key=note.storage_key, sha256=note.sha256, dest=workdir / "in" / _VOICE_NOTE_FILENAME
    )
    if is_err(local):
        return await _voice_failed(rt, ctx, job, local.error, MediaErrorCode.VOICE_PREPARE_FAILED)
    prepared_path = workdir / "out" / _take_name(_NARRATION_FILENAME)
    prepared_path.parent.mkdir(parents=True, exist_ok=True)
    prepared = await rt.video.prepare_voice(local.value, prepared_path)
    if is_err(prepared):
        return await _voice_failed(
            rt, ctx, job, prepared.error, MediaErrorCode.VOICE_PREPARE_FAILED
        )
    return await _voice_ready(rt, ctx, job, prepared_path, prepared.value)


# ---------------------------------------------------------------------------
# media_mux (§5.6): the voice onto the clip, once, after the fan-in
# ---------------------------------------------------------------------------
async def media_mux(ctx: Mapping[str, Any], job_id: str, n: int = 0) -> dict[str, Any]:
    """``post`` video → the delivered clip (``video`` output) → the output screen.

    A silent request is re-wrapped with ``+faststart``; a voiced one gets its track muxed on
    and cut at the clip's own length (§5.3 fit: pad, ``atempo`` ≤ 1.15 for an AI voice, else
    a trim with a 250 ms fade — counted per language so the budgets can be tightened, Q11).
    ffprobe checks the result against the render's geometry and length before anything
    screens it. A no-op unless the row is ``post``; a clip already muxed only re-asks the
    output screen (a re-drive after a lost enqueue). ``n`` tells re-drives apart.
    """
    del n
    rt = media_runtime(ctx)
    jid = _uuid(job_id)
    async with rt.sessions() as session:
        job = await load_job(session, jid)
        outputs = {
            role: await list_outputs(session, jid, role=role)
            for role in (
                MediaOutputRole.VIDEO,
                MediaOutputRole.VIDEO_RAW,
                MediaOutputRole.NARRATION,
            )
        }
    if job is None or job.kind is not MediaKind.VIDEO or job.state is not MediaJobState.POST:
        return _result("noop_not_post", jid)
    if job.forget_requested_at is not None:
        await fail_job(
            rt,
            jid,
            expected=(MediaJobState.POST,),
            error_code=MediaErrorCode.FORGET_REQUESTED,
            refund=None,
            notify=False,
        )
        return _result("failed_forgotten", jid)
    if outputs[MediaOutputRole.VIDEO]:
        await _ask_output_screen(rt, job)
        return _result("noop_muxed", jid)
    raw_rows = outputs[MediaOutputRole.VIDEO_RAW]
    voice_rows = outputs[MediaOutputRole.NARRATION]
    needs_voice = job.voice_mode is not MediaVoiceMode.NONE
    if not raw_rows or (needs_voice and not voice_rows):
        return await _mux_failed(rt, ctx, job, StorageError("a mux input is missing"))
    raw_row = raw_rows[0]
    workdir = media_workspace(rt, jid)
    raw = await _materialise_file(
        rt,
        key=raw_row.storage_key,
        sha256=raw_row.sha256,
        dest=workdir / "out" / _VIDEO_RAW_FILENAME,
    )
    if is_err(raw):
        return await _mux_failed(rt, ctx, job, raw.error)
    final = workdir / "out" / _take_name(_VIDEO_FILENAME)
    fit: AudioFit | None = None
    if not needs_voice:
        made = await rt.video.rewrap(raw.value, final)
        if is_err(made):
            return await _mux_failed(rt, ctx, job, made.error)
        clip = made.value
    else:
        voice_row = voice_rows[0]
        voice = await _materialise_file(
            rt,
            key=voice_row.storage_key,
            sha256=voice_row.sha256,
            # The stored object's own suffix: an ElevenLabs fallback narration is MP3 (§5.2).
            dest=(workdir / "out" / _NARRATION_FILENAME).with_suffix(
                PurePosixPath(voice_row.storage_key).suffix or ".wav"
            ),
        )
        if is_err(voice):
            return await _mux_failed(rt, ctx, job, voice.error)
        muxed = await rt.video.mux(
            raw.value,
            voice.value,
            final,
            # An own note is muxed as-is: trimmed with a fade inside its tolerance, never
            # sped up (§5.4).
            may_speed_up=job.voice_mode is not MediaVoiceMode.OWN,
        )
        if is_err(muxed):
            return await _mux_failed(rt, ctx, job, muxed.error)
        clip, fit = muxed.value.probe, muxed.value.fit
        if fit is not AudioFit.PAD:
            _LOG.info(
                "a video's voice was fitted to the clip",
                extra={
                    "media_job_id": str(jid),
                    "language": job.language.value,
                    "voice_mode": job.voice_mode.value,
                    "fit": fit.value,
                    "audio_s": round(muxed.value.audio_s, 2),
                },
            )
    expected_s = (raw_row.duration_ms or 0) / 1000
    if (
        clip.width != raw_row.width
        or clip.height != raw_row.height
        or (expected_s and abs(clip.duration_s - expected_s) > _MUX_DURATION_SLACK_S)
    ):
        return await _mux_failed(
            rt,
            ctx,
            job,
            ValidationError(
                "the muxed clip does not match the render",
                is_retryable=False,
                context={
                    "width": clip.width,
                    "height": clip.height,
                    "duration_s": round(clip.duration_s, 3),
                    "expected_s": round(expected_s, 3),
                },
            ),
        )
    stored = await rt.storage.put_file(
        media_key(jid, is_output=True, filename=final.name), final, content_type=_VIDEO_MIME
    )
    if is_err(stored):
        return await _mux_failed(rt, ctx, job, stored.error)
    async with rt.sessions.begin() as session:
        wrote = await add_output(
            session,
            job_id=jid,
            role=MediaOutputRole.VIDEO,
            variant=0,
            storage_key=stored.value.key,
            now=rt.clock(),
            mime=_VIDEO_MIME,
            size_bytes=stored.value.size_bytes,
            sha256=stored.value.sha256,
            width=clip.width,
            height=clip.height,
            duration_ms=round(clip.duration_s * 1000),
            policy=_policy(rt),
        )
    if not wrote:
        # A re-drive muxed it first; its row names its own object, so this one goes.
        await rt.storage.delete(stored.value.key)
    await _ask_output_screen(rt, job)
    return _result("muxed", jid, fit=fit.value if fit is not None else None)


async def _ask_output_screen(rt: MediaRuntime, job: MediaJobRow) -> None:
    await enqueue_stage(
        rt,
        MEDIA_OUTPUT_SCREEN_JOB,
        str(job.id),
        job.oscreen_seq,
        job_id=output_screen_job_id(job.id, job.oscreen_seq),
    )


async def _mux_failed(
    rt: MediaRuntime, ctx: Mapping[str, Any], job: MediaJobRow, error: BayramError
) -> dict[str, Any]:
    """ffmpeg or storage let us down: retried by ARQ while it may pass, then one credit."""
    if error.is_retryable and _job_try(ctx) < MEDIA_STAGE_MAX_TRIES:
        raise Retry(defer=rt.settings.provider_backoff_base_s * _job_try(ctx))
    _LOG.warning("a video could not be muxed", extra=error.to_log_dict())
    await fail_job(
        rt,
        job.id,
        expected=(MediaJobState.POST,),
        error_code=MediaErrorCode.MUX_FAILED,
        refund=MediaCreditReason.GENERATION_FAILED,
    )
    return _result("mux_failed", job.id)


assert media_prescreen.__name__ == MEDIA_PRESCREEN_JOB
assert media_screen.__name__ == MEDIA_SCREEN_JOB
assert media_start.__name__ == MEDIA_START_JOB
assert media_submit.__name__ == MEDIA_SUBMIT_JOB
assert media_poll.__name__ == MEDIA_POLL_JOB
assert media_fetch.__name__ == MEDIA_FETCH_JOB
assert media_output_screen.__name__ == MEDIA_OUTPUT_SCREEN_JOB
assert media_deliver.__name__ == MEDIA_DELIVER_JOB
assert media_cleanup.__name__ == MEDIA_CLEANUP_JOB
assert media_review_apply.__name__ == MEDIA_REVIEW_JOB
assert media_script.__name__ == MEDIA_SCRIPT_JOB
assert media_tts.__name__ == MEDIA_TTS_JOB
assert media_voice_prepare.__name__ == MEDIA_VOICE_PREPARE_JOB
assert media_mux.__name__ == MEDIA_MUX_JOB
