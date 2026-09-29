"""The media output reveal: which ``media_outputs`` rows the panel may stream, and from where.

IMAGE_VIDEO_SPEC §8 ("Reveal"). The song reveal (:mod:`bayram.admin.services.assets`) reads
``AssetRow`` and keys its window on an asset id; media never uses ``assets``, so this is the
second loader, keyed on the output id, and everything after it — the step-up, the budget, the
committed-first audit row, the ten-minute window, ``parse_range`` and ``Storage.open_range``'s
bounded chunks — is the song path's, reused rather than copied.

**What is never revealable, decided here rather than in the router:**

* **Uploads.** Only ``media_outputs`` rows are loaded at all; ``media_inputs`` has no loader,
  and the customer's photos and voice notes are deleted after delivery anyway (O16).
* **Intermediates.** ``video_raw`` and ``narration`` are 24-hour working files, not what the
  customer received; only ``image`` and ``video`` are served.
* **Legal hold** (§6.7). A ``legal_hold`` row is a 404 — not a 403 a step-up could clear — and
  so is one whose bytes the purge or ``/forget`` already took (``deleted_at``).

**The key is rebuilt, not trusted.** The stored ``storage_key`` must be exactly what
:func:`bayram.storage.media_key` spells for this row's job and filename, and the filename must
match :data:`~bayram.admin.services.assets.FILENAME_PATTERN`; anything else is refused and
logged by length only, the song path's rule (§12.1 T4).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Final
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from bayram.admin.services.assets import FILENAME_PATTERN
from bayram.db.enums import MediaOutputRole
from bayram.db.models.media_input import MediaOutputRow
from bayram.db.retention import RetentionClass
from bayram.logging import get_logger
from bayram.storage import media_key

__all__ = [
    "MEDIA_OUTPUT_SUBJECT_TYPE",
    "MEDIA_OUTPUT_FIELD_NAME",
    "MEDIA_OUTPUT_MIMES",
    "REVEALABLE_OUTPUT_ROLES",
    "MediaOutputMedia",
    "load_media_output",
    "media_output_key",
]

_LOGGER: Final = get_logger(__name__)

#: ``db.admin.audit.SUBJECT_TYPES`` carries this one.
MEDIA_OUTPUT_SUBJECT_TYPE: Final[str] = "media_output"

#: The column that addresses the bytes, for the audit row's ``field_names``.
MEDIA_OUTPUT_FIELD_NAME: Final[str] = "media_outputs.storage_key"

#: What the delivery writes (§3.3 ``media_deliver``), matched whole. Kept apart from the song
#: route's ``STREAMABLE_MIMES`` so that route stays audio-only.
MEDIA_OUTPUT_MIMES: Final[frozenset[str]] = frozenset({"image/png", "image/jpeg", "video/mp4"})

#: What the customer received. Intermediates are not revealable.
REVEALABLE_OUTPUT_ROLES: Final[frozenset[MediaOutputRole]] = frozenset(
    {MediaOutputRole.IMAGE, MediaOutputRole.VIDEO}
)


@dataclass(frozen=True, slots=True)
class MediaOutputMedia:
    """What the stream route needs from one output row. Never serialised."""

    output_id: UUID
    job_id: UUID
    storage_key: str
    mime: str


async def load_media_output(session: AsyncSession, output_id: UUID) -> MediaOutputMedia | None:
    """One revealable output, or ``None`` for the caller to answer 404 with.

    ``None`` too for an intermediate, a legal-hold row and a row whose bytes are gone — each is
    "not here" to the panel, and none of them may be distinguished from a missing id by the
    answer.
    """
    row = await session.get(MediaOutputRow, output_id)
    if (
        row is None
        or row.role not in REVEALABLE_OUTPUT_ROLES
        or row.retention_class == RetentionClass.LEGAL_HOLD
        or row.deleted_at is not None
        or row.mime is None
    ):
        return None
    return MediaOutputMedia(
        output_id=row.id, job_id=row.job_id, storage_key=row.storage_key, mime=row.mime
    )


def media_output_key(media: MediaOutputMedia) -> str | None:
    """The object key, rebuilt through :func:`bayram.storage.media_key`, or ``None``."""
    filename = PurePosixPath(media.storage_key).name
    rebuilt: str | None = None
    if FILENAME_PATTERN.fullmatch(filename) is not None:
        try:
            rebuilt = media_key(media.job_id, is_output=True, filename=filename)
        except ValueError:
            rebuilt = None
    if rebuilt is not None and rebuilt == media.storage_key:
        return rebuilt
    _log_refused(media, filename)
    return None


def _log_refused(media: MediaOutputMedia, filename: str) -> None:
    _LOGGER.error(
        "a media output row names a key this route will not resolve",
        extra={
            "event": "admin.media_output.key_refused",
            "output_id": str(media.output_id),
            "filename_chars": len(filename),
        },
    )
    return
