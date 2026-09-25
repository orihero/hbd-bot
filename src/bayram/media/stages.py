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
    "MEDIA_PRESCREEN_JOB",
    "MEDIA_SCREEN_JOB",
    "MEDIA_SCRIPT_JOB",
    "MEDIA_START_JOB",
    "MEDIA_SUBMIT_JOB",
    "MEDIA_POLL_JOB",
    "MEDIA_FETCH_JOB",
    "MEDIA_OUTPUT_SCREEN_JOB",
    "MEDIA_DELIVER_JOB",
    "MEDIA_CLEANUP_JOB",
    "MEDIA_SWEEP_JOB",
    "MEDIA_REVIEW_JOB",
    "MEDIA_MUX_JOB",
    "MEDIA_TTS_JOB",
    "MEDIA_VOICE_PREPARE_JOB",
    "SKU_DEADLINE_FIELDS",
    "DEFAULT_SKU_DEADLINES",
    "prescreen_job_id",
    "screen_job_id",
    "script_job_id",
    "start_job_id",
    "submit_job_id",
    "poll_job_id",
    "fetch_job_id",
    "output_screen_job_id",
    "deliver_job_id",
    "cleanup_job_id",
    "review_job_id",
    "tts_job_id",
    "voice_prepare_job_id",
    "mux_job_id",
    "sku_deadline",
    "content_sha256",
]

#: Video only (§2.4.1): the ✅ Done of a video compose freezes a ``drafting`` row and this
#: screens its prompt and photos before the aspect and voice screens, so the script writer and
#: every later stage only ever see a prompt that passed L0/L1.
MEDIA_PRESCREEN_JOB: Final[str] = "media_prescreen"
MEDIA_SCREEN_JOB: Final[str] = "media_screen"
MEDIA_START_JOB: Final[str] = "media_start"
MEDIA_SUBMIT_JOB: Final[str] = "media_submit"
MEDIA_POLL_JOB: Final[str] = "media_poll"
MEDIA_FETCH_JOB: Final[str] = "media_fetch"
MEDIA_OUTPUT_SCREEN_JOB: Final[str] = "media_output_screen"
MEDIA_DELIVER_JOB: Final[str] = "media_deliver"
MEDIA_CLEANUP_JOB: Final[str] = "media_cleanup"
MEDIA_SWEEP_JOB: Final[str] = "media_sweep"
#: Carries out an operator's (or the SLA's) decision on a held job (§6.6). The ADMIN process
#: enqueues it and restates the string (``bayram.admin.queue``), which may not import this
#: package's worker half; ``tests/test_admin/test_queue.py`` holds the two spellings together.
MEDIA_REVIEW_JOB: Final[str] = "media_review_apply"
#: The video stages (M4.3, ``bayram.runtime.media_jobs``): the narration (AI voice) or the
#: prepared own note runs beside the render after ``media_start``, and whichever finishes
#: second fans in to ``media_mux`` (§3.3).
MEDIA_MUX_JOB: Final[str] = "media_mux"
MEDIA_TTS_JOB: Final[str] = "media_tts"
MEDIA_VOICE_PREPARE_JOB: Final[str] = "media_voice_prepare"
#: 🤖 "AI writes" (§2.4.2, §5.5): the bot enqueues it against the ``drafting`` row.
MEDIA_SCRIPT_JOB: Final[str] = "media_script"

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


def prescreen_job_id(job_id: UUID | str, n: int = 0) -> str:
    """``n`` is 0 for ✅ Done; 🔁 on a busy tray (or the sweep) re-screens with a new ``n``."""
    return f"{_prefix(job_id)}:prescreen" if n == 0 else f"{_prefix(job_id)}:prescreen:{n}"


def script_job_id(job_id: UUID | str, n: int) -> str:
    """``n`` counts the line asked for: 0 first, then one per 🔄 (≤ ``media_script_max_regens``)."""
    return f"{_prefix(job_id)}:script:{n}"


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


def deliver_job_id(job_id: UUID | str, n: int = 0) -> str:
    """``n`` is 0 from the output screen; a release or the sweep's re-drive of a released
    ``held`` job passes its own suffix, since the plain id may already have been spent."""
    return f"{_prefix(job_id)}:deliver" if n == 0 else f"{_prefix(job_id)}:deliver:{n}"


def cleanup_job_id(job_id: UUID | str) -> str:
    return f"{_prefix(job_id)}:cleanup"


def review_job_id(review_id: UUID | str, n: int = 0) -> str:
    """Keyed on the REVIEW, not the job: a job's review is decided once, and the id must be
    the panel's and the sweep's alike. ``n`` is the sweep's tick when it re-drives a lost one.
    Spelled again in ``bayram.admin.queue.job_id_for_media_review``."""
    base = f"media:review:{review_id}"
    return base if n == 0 else f"{base}:{n}"


def tts_job_id(job_id: UUID | str, n: int = 0) -> str:
    """``n`` is 0 from ``media_start``; the sweep's tick when it re-drives a lost narration."""
    return f"{_prefix(job_id)}:tts" if n == 0 else f"{_prefix(job_id)}:tts:{n}"


def voice_prepare_job_id(job_id: UUID | str, n: int = 0) -> str:
    """An own voice note's preparation (§5.4); ``n`` as for :func:`tts_job_id`."""
    return f"{_prefix(job_id)}:voice" if n == 0 else f"{_prefix(job_id)}:voice:{n}"


def mux_job_id(job_id: UUID | str, n: int = 0) -> str:
    """``n`` is 0 from the fan-in; the sweep's tick when it re-drives a lost mux."""
    return f"{_prefix(job_id)}:mux" if n == 0 else f"{_prefix(job_id)}:mux:{n}"


def sku_deadline(settings: Settings, sku: MediaSku) -> timedelta:
    seconds = getattr(settings, SKU_DEADLINE_FIELDS[sku])
    return timedelta(seconds=int(seconds))


#: The deadlines as shipped (§3.5), for the Payme gateway, which reads no ``Settings``. It uses
#: them only for the uploads' backstop clock on a media settlement; the deadline itself is
#: enforced by the worker's ``media_sweep`` from the configured values.
DEFAULT_SKU_DEADLINES: Final[Mapping[MediaSku, timedelta]] = MappingProxyType(
    {
        sku: timedelta(seconds=int(Settings.model_fields[field].default))
        for sku, field in SKU_DEADLINE_FIELDS.items()
    }
)


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
