"""``media_inputs`` and ``media_outputs`` — the bytes a media job reads and writes.

IMAGE_VIDEO_SPEC §3.2.2, §3.2.4, O16. Both tables record WHERE an object is and WHAT it is;
the bytes live in object storage under :func:`bayram.storage.media_key`, never in a row.

**AN UPLOAD IS DELETED THE MOMENT IT HAS DONE ITS JOB.** ``media_cleanup`` deletes every
input's object and row right after delivery, and on failure, rejection, cancellation or
abandonment (O16). ``expires_at`` is only the backstop the purge reads if that never ran:
``created_at`` + 24 h before payment, RESET on payment to ``paid_at`` + the SKU's deadline +
the 24 h review SLA, in the same transaction that moves the job to ``paid`` — so a customer
who pays late in the quote window keeps their inputs until the job is done.

**OUTPUTS** live ``retention_media_output_days`` (30 by default, open question Q2), and the
intermediates (``video_raw``, ``narration``) 24 hours. ``tg_file_id`` goes with the row.

**LEGAL HOLD** (§6.7, Q16). A CSAM-class block moves the offending rows to
``retention_class = 'legal_hold'`` with a ``legal_hold_expires_at`` at most 72 hours out. Every
ordinary sweep and ``media_cleanup`` skip them; a separate purge arm deletes them when their
own clock runs out. A CHECK makes a hold without an expiry impossible — a hold nobody set a
clock on would be kept for ever, which is the one outcome the owner's decision rules out.

**PRIVACY** — both in ``tables_with_personal_data``: a photo of a person and a person's voice
are the most sensitive bytes this product touches, and ``expires_at`` is the clock that
obliges a sweep by name (``tests/test_db/test_audit_retention.py``).
"""

from __future__ import annotations

from datetime import datetime
from typing import Final
from uuid import UUID, uuid4

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from bayram.db.base import SHA256_LENGTH, Base, UtcDateTime, enum_type, utc_now
from bayram.db.enums import MediaInputRole, MediaOutputRole
from bayram.db.retention import RetentionClass

__all__ = [
    "MediaInputRow",
    "MediaOutputRow",
    "LEGAL_HOLD_HAS_EXPIRY",
    "MEDIA_STORAGE_KEY_LENGTH",
    "MEDIA_TG_FILE_ID_LENGTH",
]

MEDIA_STORAGE_KEY_LENGTH: Final[int] = 512
MEDIA_TG_FILE_ID_LENGTH: Final[int] = 256
_TG_FILE_UNIQUE_ID_LENGTH: Final[int] = 64
_MIME_LENGTH: Final[int] = 64
_ROLE_LENGTH: Final[int] = 16

#: A legal hold without its own clock would never leave. Spelled against the literal, as
#: every CHECK here is: DDL outlives the enum.
LEGAL_HOLD_HAS_EXPIRY: Final[str] = (
    "retention_class <> 'legal_hold' OR legal_hold_expires_at IS NOT NULL"
)


class MediaInputRow(Base):
    """One photo, voice note or collage a job was given or built.

    The row is written at freeze with Telegram's file ids; ``storage_key``, ``sha256``, size
    and geometry are filled in when ``media_screen`` downloads and checks the bytes, which is
    why they are nullable. Generation reads only the stored copy, verified against ``sha256``.
    """

    __tablename__ = "media_inputs"
    __table_args__ = (
        # Leads with ``job_id``, so it is also the index cleanup and /forget read by job.
        sa.UniqueConstraint("job_id", "role", "ordinal"),
        sa.CheckConstraint(LEGAL_HOLD_HAS_EXPIRY, name="legal_hold_has_expiry"),
    )

    id: Mapped[UUID] = mapped_column(sa.Uuid, primary_key=True, default=uuid4)
    job_id: Mapped[UUID] = mapped_column(
        sa.Uuid, sa.ForeignKey("media_jobs.id", ondelete="CASCADE"), nullable=False
    )
    ordinal: Mapped[int] = mapped_column(sa.SmallInteger, nullable=False)
    role: Mapped[MediaInputRole] = mapped_column(
        enum_type(MediaInputRole, length=_ROLE_LENGTH), nullable=False
    )
    tg_file_id: Mapped[str | None] = mapped_column(
        sa.String(MEDIA_TG_FILE_ID_LENGTH), nullable=True
    )
    tg_file_unique_id: Mapped[str | None] = mapped_column(
        sa.String(_TG_FILE_UNIQUE_ID_LENGTH), nullable=True
    )
    #: NULL until downloaded.
    storage_key: Mapped[str | None] = mapped_column(
        sa.String(MEDIA_STORAGE_KEY_LENGTH), nullable=True
    )
    mime: Mapped[str | None] = mapped_column(sa.String(_MIME_LENGTH), nullable=True)
    size_bytes: Mapped[int | None] = mapped_column(sa.BigInteger, nullable=True)
    sha256: Mapped[str | None] = mapped_column(sa.String(SHA256_LENGTH), nullable=True)
    width: Mapped[int | None] = mapped_column(sa.Integer, nullable=True)
    height: Mapped[int | None] = mapped_column(sa.Integer, nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(sa.Integer, nullable=True)
    retention_class: Mapped[RetentionClass] = mapped_column(
        enum_type(RetentionClass), nullable=False, default=RetentionClass.MEDIA_INPUT
    )
    legal_hold_expires_at: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)
    #: The backstop clock. See the module docstring on the reset at payment.
    expires_at: Mapped[datetime] = mapped_column(UtcDateTime, nullable=False, index=True)
    #: Set when the object was deleted and the row kept; the purge skips such rows.
    deleted_at: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime, nullable=False, default=utc_now)


class MediaOutputRow(Base):
    """One stored result: an image variant, a raw or final video, or a narration track."""

    __tablename__ = "media_outputs"
    __table_args__ = (
        sa.UniqueConstraint("job_id", "role", "variant"),
        sa.CheckConstraint(LEGAL_HOLD_HAS_EXPIRY, name="legal_hold_has_expiry"),
    )

    id: Mapped[UUID] = mapped_column(sa.Uuid, primary_key=True, default=uuid4)
    job_id: Mapped[UUID] = mapped_column(
        sa.Uuid, sa.ForeignKey("media_jobs.id", ondelete="CASCADE"), nullable=False
    )
    role: Mapped[MediaOutputRole] = mapped_column(
        enum_type(MediaOutputRole, length=_ROLE_LENGTH), nullable=False
    )
    variant: Mapped[int] = mapped_column(sa.SmallInteger, nullable=False, default=0)
    storage_key: Mapped[str] = mapped_column(sa.String(MEDIA_STORAGE_KEY_LENGTH), nullable=False)
    mime: Mapped[str | None] = mapped_column(sa.String(_MIME_LENGTH), nullable=True)
    size_bytes: Mapped[int | None] = mapped_column(sa.BigInteger, nullable=True)
    sha256: Mapped[str | None] = mapped_column(sa.String(SHA256_LENGTH), nullable=True)
    width: Mapped[int | None] = mapped_column(sa.Integer, nullable=True)
    height: Mapped[int | None] = mapped_column(sa.Integer, nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(sa.Integer, nullable=True)
    #: What Telegram minted on delivery: a re-send costs zero bytes. Goes with the row.
    tg_file_id: Mapped[str | None] = mapped_column(
        sa.String(MEDIA_TG_FILE_ID_LENGTH), nullable=True
    )
    retention_class: Mapped[RetentionClass] = mapped_column(
        enum_type(RetentionClass), nullable=False, default=RetentionClass.MEDIA_OUTPUT
    )
    legal_hold_expires_at: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)
    expires_at: Mapped[datetime] = mapped_column(UtcDateTime, nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime, nullable=False, default=utc_now)
