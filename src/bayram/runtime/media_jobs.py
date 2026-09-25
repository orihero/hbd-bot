"""The media stage chain: short, idempotent ARQ jobs in the existing worker (IMAGE_VIDEO_SPEC §3.3).

A song is one long job; a media request is a CHAIN of short ones, because a customer's image
can wait an hour for the GPU and a video renders for seventeen minutes, and neither may hold one
of the worker's fifteen slots (or its 900 s job timeout) while it waits. Each stage reads the
``media_jobs`` row, does one thing, moves the row with a conditional ``UPDATE`` and enqueues the
next stage::

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

**Video** shares submit/poll/fetch and has its fan-in written here (render + narration →
``media_mux``), but narration, mux and video delivery are M4. Until they exist ``media_start``
fails a video job before it reaches the GPU (``video_not_built``), so no customer pays for a
render nothing can finish.

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
from collections.abc import Awaitable, Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import StrEnum
from pathlib import Path
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
)
from bayram.bot.pricing import format_amount
from bayram.config import Settings
from bayram.contracts import Err, HealthState, Result, Storage, err, is_err, ok
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
    MediaVoiceMode,
)
from bayram.db.media import (
    add_input,
    add_output,
    average_run_ms,
    bump_seq,
    cleanup_job_media,
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
    touch_job,
    transition,
)
from bayram.db.media_reviews import load_review, mark_applied, open_review
from bayram.db.models.media_attempt import MediaAttemptRow
from bayram.db.models.media_input import MediaInputRow
from bayram.db.models.media_job import CSAM_BLOCKED_ERROR_CODE, MediaJobRow
from bayram.db.retention import RetentionPolicy, resolve_retention_policy
from bayram.errors import BayramError, PipelineError, StorageError, ValidationError
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
from bayram.media.offering import (
    effective_backend,
    is_beta_member,
    is_live_paid,
    media_offered,
)
from bayram.media.overrides import MediaSwitchStore, read_backend_override, read_overrides
from bayram.media.service import MediaQueue
from bayram.media.stages import (
    MEDIA_CLEANUP_JOB,
    MEDIA_DELIVER_JOB,
    MEDIA_FETCH_JOB,
    MEDIA_MUX_JOB,
    MEDIA_OUTPUT_SCREEN_JOB,
    MEDIA_POLL_JOB,
    MEDIA_REVIEW_JOB,
    MEDIA_SCREEN_JOB,
    MEDIA_START_JOB,
    MEDIA_SUBMIT_JOB,
    cleanup_job_id,
    content_sha256,
    deliver_job_id,
    fetch_job_id,
    output_screen_job_id,
    poll_job_id,
    sku_deadline,
    submit_job_id,
)
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
_UNSUPPORTED_KEY: Final[str] = "media.compose.unsupported"
_BUSY_KEY: Final[str] = "media.busy"
_QUEUED_KEY: Final[str] = "media.progress.queued"
_QUEUED_FREE_KEY: Final[str] = "media.progress.queued_free"
_RENDERING_KEY: Final[str] = "media.progress.rendering"
_DELIVERED_KEY: Final[str] = "media.image.delivered"
_AGAIN_KEY: Final[str] = "media.delivered.again"
_PARTIAL_KEY: Final[str] = "media.image.partial"
_PARTIAL_REFUNDED_KEY: Final[str] = "media.image.partial_refunded"
_FAILED_REFUNDED_KEY: Final[str] = "media.failed.refunded"
_FAILED_BETA_KEY: Final[str] = "media.failed.beta"
_FAILED_KEY: Final[str] = "media.failed"
_ETA_MINUTES_KEY: Final[str] = "media.eta.minutes"


class MediaErrorCode(StrEnum):
    """``media_jobs.error_code`` values this module writes. Closed; ≤ 48 characters."""

    SCREEN_REFUSED = "screen_refused"
    UNSUPPORTED_INPUT = "unsupported_input"
    GENERATION_FAILED = "generation_failed"
    DEADLINE = "deadline"
    OUTPUT_BLOCKED = "output_blocked"
    SCREEN_STALE = "screen_stale"
    NOT_ENTITLED = "not_entitled"
    VIDEO_NOT_BUILT = "video_not_built"
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
    )
    if isinstance(ctx, dict):
        ctx[MEDIA_CTX_KEY] = runtime
    return runtime


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


def _over_caps(job: MediaJobRow) -> bool:
    """§1.3 / §6.4 L0: the prompt outside 3–800 characters or over the word cap, or a
    narration longer than its column. The bot enforces the same caps at compose, so this is
    a backstop for a row written some other way."""
    return not is_within_caps(job.prompt or "") or len(job.narration_text or "") > (
        NARRATION_MAX_CHARS
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
    """``screening → rejected`` and the refusal on the tray. ``legal_hold`` holds the inputs
    in the SAME transaction as the verdict (§6.7), before the cleanup this enqueues runs."""
    now = rt.clock()
    async with rt.sessions.begin() as session:
        moved = await transition(
            session,
            job.id,
            expected=(MediaJobState.SCREENING,),
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
    """``media.busy``: the row stays ``screening`` and 🔁 re-runs this job on it (§2.3.3)."""
    if values:
        async with rt.sessions.begin() as session:
            await session.execute(
                sa.update(MediaJobRow)
                .where(MediaJobRow.id == job.id, MediaJobRow.state == MediaJobState.SCREENING)
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
    if _over_caps(job):
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
    digest = content_sha256(
        prompt=job.prompt, narration=job.narration_text, input_sha256s=[i.sha256 for i in inputs]
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
        # Pre-pay review is a refusal for the customer (§6.4), non-specific (SEC-3) — the
        # CSAM-class refusal reads exactly like any other. A block strikes; a review does not.
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
        return _result("refused", jid, decision=decision.value, csam=is_csam)
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
    text = _translate(
        job,
        _QUOTE_KEY,
        aspect=job.aspect.value,
        price=format_amount(job.price_minor),
        eta=_eta_text(job, eta_minutes),
    )
    markup = media_quote_keyboard(
        job.language,
        jid,
        is_pay_offered=live_paid,
        is_credit_offered=balance > 0,
        is_beta_offered=not live_paid and is_beta_member(rt.settings, job.telegram_user_id),
    )
    await _show_tray(rt, job, text, markup)
    return _result("quoted", jid, eta=eta_minutes)


async def _screen_gate(rt: MediaRuntime, job: MediaJobRow) -> dict[str, Any] | None:
    """§6.4 L0, before a byte is downloaded: a suspended account, or one past today's
    screening budget, is refused unscreened — and not struck, since nothing was judged.

    The budget counts this JOB once, so a 🔁 on a busy tray does not spend twice. A Redis
    that cannot answer is ``busy``: the suspension could not be read, so nothing is screened.

    **A CSAM-class suspension is read from the database too** (``csam_blocked`` rows no
    operator cleared): Redis is a cache on this deployment, and a restart without persistence
    must not lift a suspension only an operator may lift (§6.4).
    """
    now = rt.clock()
    try:
        suspended = await rt.strikes.suspension(job.telegram_user_id, now=now)
        screens = await rt.strikes.count_screen(job.telegram_user_id, job_id=str(job.id), now=now)
        if suspended is None:
            async with rt.sessions() as session:
                if await has_standing_csam_block(session, job.telegram_user_id):
                    suspended = Suspension(SuspensionReason.CSAM)
    except Exception as exc:  # the store raises on Redis failure; fail closed
        _LOG.warning(
            "the media suspension could not be read",
            extra={"media_job_id": str(job.id), "failure": type(exc).__name__},
        )
        await _busy(rt, job, {})
        return _result("busy_strikes_unreadable", job.id)
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
    if job.kind is MediaKind.VIDEO:
        # M4 seam: narration, mux and video delivery do not exist yet (module docstring).
        await fail_job(
            rt,
            jid,
            expected=paid_expected,
            error_code=MediaErrorCode.VIDEO_NOT_BUILT,
            refund=MediaCreditReason.GENERATION_FAILED,
        )
        return _result("failed_video_not_built", jid)
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
    return _result("started", jid, backend=backend.value)


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
    if job.kind is not MediaKind.IMAGE:
        # M4: the raw clip becomes a ``video_raw`` output and ``render_ready_at`` is set, then
        # :func:`video_fan_in`. Unreachable until then (media_start refuses video).
        raise PipelineError("video fetch is M4", context={"media_job_id": str(job.id)})
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

    Written now so M4 only adds the two producers (``media_fetch`` for video, ``media_tts``);
    ``media_mux`` is not registered until then, which is why ``media_start`` refuses video.
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
        await enqueue_stage(rt, MEDIA_MUX_JOB, str(job_id), job_id=f"media:{job_id}:mux")
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
    paths = await _output_paths(rt, job)
    decision = MediaScreenDecision.UNAVAILABLE
    categories: tuple[CategoryCode, ...] = ()
    # No outputs to look at is ``unavailable``, never an ``allow`` of nothing (§6.3): a job
    # that reached ``post`` without image rows (a video in M4, a future path) retries and
    # is finally held, and is never delivered unscreened.
    if not is_err(paths) and paths.value:
        verdict = await rt.moderator.screen_images(
            [
                ImageItem(id=f"output-{index}", subject="output_image", path=path)
                for index, (_, path) in enumerate(paths.value)
            ],
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
        sent = await rt.messenger.send_photos(
            job.chat_id,
            [path for _, path in paths.value],
            caption=_translate(job, _DELIVERED_KEY),
        )
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


assert media_screen.__name__ == MEDIA_SCREEN_JOB
assert media_start.__name__ == MEDIA_START_JOB
assert media_submit.__name__ == MEDIA_SUBMIT_JOB
assert media_poll.__name__ == MEDIA_POLL_JOB
assert media_fetch.__name__ == MEDIA_FETCH_JOB
assert media_output_screen.__name__ == MEDIA_OUTPUT_SCREEN_JOB
assert media_deliver.__name__ == MEDIA_DELIVER_JOB
assert media_cleanup.__name__ == MEDIA_CLEANUP_JOB
assert media_review_apply.__name__ == MEDIA_REVIEW_JOB
