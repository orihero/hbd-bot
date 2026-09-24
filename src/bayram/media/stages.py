"""The names and ids of the media stage jobs, spelled once (IMAGE_VIDEO_SPEC §3.3).

Vendor-free and ``aiogram``-free, because two processes enqueue these: the WORKER chains its
own stages, and the BOT enqueues the first one (``media_screen`` at the aspect pick, and
``media_start`` after a 🎁/🎟 press — M2.5). ARQ dispatches by function name, so both sides
read the strings from here; ``bayram.runtime.media_jobs`` asserts each against its function.

**ARQ job ids are the idempotency mechanism, and they cut both ways** (§3.3). ARQ silently
drops an enqueue whose ``_job_id`` still has a job key or a kept result (results are kept
``queue_result_ttl_s``, an hour). So a deterministic id makes a *duplicate* enqueue a no-op —
and makes a *deliberate* re-enqueue a no-op too, which is the bug. Every self-re-enqueue
therefore carries a monotonic suffix: ``submit_seq`` and ``oscreen_seq`` persisted on the row,
or a tick passed forward as an argument, and ``media_sweep`` always hands out the NEXT suffix,
never the last id. Raising ``Retry`` is not a substitute — ``max_tries`` is five and a job can
wait hours for the GPU.

:func:`content_sha256` is here too, because the bot is not the one that computes it but both
``media_screen`` (which records it) and ``media_start`` (which re-checks it) must spell it
identically — what runs must be exactly what was screened (§2.3.1).
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterable, Mapping
from datetime import timedelta
from types import MappingProxyType
from typing import Final
from uuid import UUID

from bayram.config import Settings
from bayram.db.enums import MediaSku

__all__ = [
    "MEDIA_SCREEN_JOB",
    "MEDIA_START_JOB",
    "MEDIA_SUBMIT_JOB",
    "MEDIA_POLL_JOB",
    "MEDIA_FETCH_JOB",
    "MEDIA_OUTPUT_SCREEN_JOB",
    "MEDIA_DELIVER_JOB",
    "MEDIA_CLEANUP_JOB",
    "MEDIA_SWEEP_JOB",
    "MEDIA_MUX_JOB",
    "MEDIA_TTS_JOB",
    "SKU_DEADLINE_FIELDS",
    "screen_job_id",
    "start_job_id",
    "submit_job_id",
    "poll_job_id",
    "fetch_job_id",
    "output_screen_job_id",
    "deliver_job_id",
    "cleanup_job_id",
    "sku_deadline",
    "content_sha256",
]

MEDIA_SCREEN_JOB: Final[str] = "media_screen"
MEDIA_START_JOB: Final[str] = "media_start"
MEDIA_SUBMIT_JOB: Final[str] = "media_submit"
MEDIA_POLL_JOB: Final[str] = "media_poll"
MEDIA_FETCH_JOB: Final[str] = "media_fetch"
MEDIA_OUTPUT_SCREEN_JOB: Final[str] = "media_output_screen"
MEDIA_DELIVER_JOB: Final[str] = "media_deliver"
MEDIA_CLEANUP_JOB: Final[str] = "media_cleanup"
MEDIA_SWEEP_JOB: Final[str] = "media_sweep"
#: Video stages, M4. Named now so the video fan-in has one spelling to enqueue; NOT registered
#: in ``WorkerSettings`` until their functions exist, and ``media_start`` refuses a video job
#: until then (``bayram.runtime.media_jobs``), so nothing enqueues them early.
MEDIA_MUX_JOB: Final[str] = "media_mux"
MEDIA_TTS_JOB: Final[str] = "media_tts"

#: The ``Settings`` field holding each SKU's paid → delivered deadline (§3.5).
SKU_DEADLINE_FIELDS: Final[Mapping[MediaSku, str]] = MappingProxyType(
    {
        MediaSku.IMAGE: "media_image_deadline_s",
        MediaSku.VIDEO_STANDARD: "media_video_standard_deadline_s",
        MediaSku.VIDEO_FAST: "media_video_fast_deadline_s",
    }
)


def _prefix(job_id: UUID | str) -> str:
    return f"media:{job_id}"


def screen_job_id(job_id: UUID | str, n: int = 0) -> str:
    """``n`` is 0 for the aspect pick; 🔁 retry-later on a busy tray re-screens with ``n+1``."""
    return f"{_prefix(job_id)}:screen" if n == 0 else f"{_prefix(job_id)}:screen:{n}"


def start_job_id(job_id: UUID | str, n: int) -> str:
    """``n`` is 0 from the payment path, and the sweep's tick when ``media_sweep`` re-drives."""
    return f"{_prefix(job_id)}:start:{n}"


def submit_job_id(job_id: UUID | str, variant: int, attempt: int, seq: int) -> str:
    return f"{_prefix(job_id)}:submit:{variant}:{attempt}:w{seq}"


def poll_job_id(job_id: UUID | str, variant: int, attempt: int, tick: int) -> str:
    return f"{_prefix(job_id)}:poll:{variant}:{attempt}:{tick}"


def fetch_job_id(job_id: UUID | str, variant: int, attempt: int) -> str:
    return f"{_prefix(job_id)}:fetch:{variant}:{attempt}"


def output_screen_job_id(job_id: UUID | str, seq: int) -> str:
    return f"{_prefix(job_id)}:oscreen:{seq}"


def deliver_job_id(job_id: UUID | str) -> str:
    return f"{_prefix(job_id)}:deliver"


def cleanup_job_id(job_id: UUID | str) -> str:
    return f"{_prefix(job_id)}:cleanup"


def sku_deadline(settings: Settings, sku: MediaSku) -> timedelta:
    seconds = getattr(settings, SKU_DEADLINE_FIELDS[sku])
    return timedelta(seconds=int(seconds))


def content_sha256(
    *, prompt: str | None, narration: str | None, input_sha256s: Iterable[str]
) -> str:
    """The hash of what was screened: prompt + narration + every input's ``sha256`` (§2.3.1).

    Each part is length-prefixed so no two different requests can serialise alike ("ab" + "c"
    versus "a" + "bc"), and the inputs are taken in the order given — the caller passes them by
    (role, ordinal), which is the order generation reads them in.
    """
    digest = hashlib.sha256()
    for part in (prompt or "", narration or "", *input_sha256s):
        encoded = part.encode("utf-8")
        digest.update(len(encoded).to_bytes(4, "big"))
        digest.update(encoded)
    return digest.hexdigest()
