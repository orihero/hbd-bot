"""``media_attempts`` — one call to a backend, guard or speech vendor for a media job.

IMAGE_VIDEO_SPEC §3.2.2, §3.3, R7. **The row is written BEFORE the POST** with
``status = 'submitting'``, and ``UNIQUE (job_id, stage, variant, attempt)`` makes the attempt
number a fact rather than a guess: a worker killed between the insert and the POST re-enters,
finds a ``submitting`` row with no ``remote_id``, and marks it ``ambiguous`` for
reconciliation instead of paying a vendor twice. The attempt number is fixed as a job argument
at enqueue; only the retry policy, after a terminal ``failed``/``rejected``, creates N+1.

**NO PERSONAL DATA** — every column is a closed enum, a machine id, a number or a clock, so it
is in neither privacy set; the job it pointed at may be purged, hence ``ON DELETE SET NULL``.
Growth is bounded by a 400-day cutoff on ``created_at`` (``bayram.db.purge``), the
``vendor_usage`` footing: a cutoff, not a clock, so no column ends in ``*_expires_at``.
"""

from __future__ import annotations

from datetime import datetime
from typing import Final
from uuid import UUID, uuid4

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from bayram.contracts import CostSource
from bayram.db.base import Base, UtcDateTime, enum_type, utc_now
from bayram.db.enums import MediaAttemptStage, MediaAttemptStatus

__all__ = ["MediaAttemptRow", "REMOTE_ID_LENGTH"]

#: A gateway ``job_id`` or a Higgsfield request id.
REMOTE_ID_LENGTH: Final[int] = 128
_PROVIDER_LENGTH: Final[int] = 32
_MODEL_ID_LENGTH: Final[int] = 64
_ERROR_CODE_LENGTH: Final[int] = 48
_SHORT_ENUM: Final[int] = 16


class MediaAttemptRow(Base):
    """One attempt at one stage of one variant."""

    __tablename__ = "media_attempts"
    __table_args__ = (
        sa.UniqueConstraint("job_id", "stage", "variant", "attempt"),
        # ``vendor_usage``'s rule: a dollar figure with no provenance is unreadable.
        sa.CheckConstraint(
            "(cost_usd IS NULL AND cost_source IS NULL)"
            " OR (cost_usd IS NOT NULL AND cost_source IS NOT NULL)",
            name="cost_carries_its_source",
        ),
    )

    id: Mapped[UUID] = mapped_column(sa.Uuid, primary_key=True, default=uuid4)
    #: NULL once the job row has been purged; the measurement outlives it.
    job_id: Mapped[UUID | None] = mapped_column(
        sa.Uuid, sa.ForeignKey("media_jobs.id", ondelete="SET NULL"), nullable=True
    )
    stage: Mapped[MediaAttemptStage] = mapped_column(
        enum_type(MediaAttemptStage, length=_SHORT_ENUM), nullable=False
    )
    variant: Mapped[int] = mapped_column(sa.SmallInteger, nullable=False, default=0)
    #: The adapter: ``local_gateway``, ``higgsfield``, ``gemini_tts``, ``gateway_guard``…
    provider: Mapped[str] = mapped_column(sa.String(_PROVIDER_LENGTH), nullable=False)
    model_id: Mapped[str | None] = mapped_column(sa.String(_MODEL_ID_LENGTH), nullable=True)
    #: NULL until the POST returns one. ``submitting`` + NULL here is the ambiguous case.
    remote_id: Mapped[str | None] = mapped_column(sa.String(REMOTE_ID_LENGTH), nullable=True)
    attempt: Mapped[int] = mapped_column(sa.Integer, nullable=False)
    status: Mapped[MediaAttemptStatus] = mapped_column(
        enum_type(MediaAttemptStatus, length=_SHORT_ENUM), nullable=False
    )
    error_code: Mapped[str | None] = mapped_column(sa.String(_ERROR_CODE_LENGTH), nullable=True)
    # Quantities: nullable, never defaulted — "not measured" is not "zero".
    queue_ms: Mapped[int | None] = mapped_column(sa.Integer, nullable=True)
    #: Feeds the moving-average ETA (§3.4).
    run_ms: Mapped[int | None] = mapped_column(sa.Integer, nullable=True)
    gpu_seconds: Mapped[float | None] = mapped_column(sa.Float, nullable=True)
    cost_usd: Mapped[float | None] = mapped_column(sa.Float, nullable=True)
    cost_source: Mapped[CostSource | None] = mapped_column(
        enum_type(CostSource, length=_SHORT_ENUM), nullable=True
    )
    #: Indexed for the 400-day cutoff.
    created_at: Mapped[datetime] = mapped_column(
        UtcDateTime, nullable=False, default=utc_now, index=True
    )
    finished_at: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)
