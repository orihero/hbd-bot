"""``moderation_reviews`` — the human review queue for held media outputs (IMAGE_VIDEO_SPEC §6.6).

Revision 0032. One row per time a paid media job is stopped for a person to look at: the L4
output guard answered ``review``, the guard did not answer for 30 minutes, or an operator held a
screened output on its way out (:class:`~bayram.db.enums.MediaReviewSource`). The job itself sits
in ``held``; this row is the queue's view of it and the record of who decided what.

**A NULL ``decision`` is a pending review, and there is at most one per job.** The partial
unique index ``ix_moderation_reviews_one_pending_per_job`` makes that a database fact, so the
worker's hold and an operator's hold racing each other open one row, and an operator's decision
is a conditional ``UPDATE … WHERE decision IS NULL`` whose rowcount is the lock (a second press
is a 409, never a second refund).

**The decision is recorded by the panel and carried out by the worker.** The admin process holds
no bot token (D10), so it cannot tell the customer anything or send them the images; it writes
the decision (and its audit rows) and asks the worker, through ``AdminQueue``, to apply it.
``applied_at`` is stamped by the worker once the job has moved; a decided row with no
``applied_at`` is what ``media_sweep`` re-drives, so a lost enqueue delays and never strands.

**NO CUSTOMER TEXT.** ``categories`` is closed ``CategoryCode`` values; ``actor`` is the
operator's username snapshot or ``system``; the reason is a closed ``AuditReasonCode``. So the
table is in neither privacy set (``tests/test_db/test_privacy_constraints.py``) — the prompt and
the images stay on the job's own clocks — and it has no ``*_expires_at`` of its own: it lives as
long as its ``media_jobs`` row, which it cascades with. ``due_at`` is the SLA, not a retention
clock, and deliberately not spelled like one.

This is the IMAGE_VIDEO_SPEC §6.6 shape, not ADMIN_PANEL_PLAN §5.9's song-order design, which was
never migrated: the song pipeline has no pre-delivery hold.
"""

from __future__ import annotations

from datetime import datetime
from typing import Final
from uuid import UUID, uuid4

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from bayram.db.base import Base, UtcDateTime, enum_type, utc_now
from bayram.db.enums import AuditReasonCode, MediaReviewDecision, MediaReviewSource

__all__ = [
    "ModerationReviewRow",
    "ONE_PENDING_REVIEW_INDEX",
    "PENDING_REVIEW_PREDICATE",
    "REVIEW_ACTOR_LENGTH",
    "SYSTEM_REVIEW_ACTOR",
]

#: Matches ``admin_audit_log.actor_username`` (``ACTOR_USERNAME_LENGTH``).
REVIEW_ACTOR_LENGTH: Final[int] = 64
#: ``actor`` on a review the 24 h SLA ended with nobody deciding.
SYSTEM_REVIEW_ACTOR: Final[str] = "system"
_SHORT_ENUM: Final[int] = 24
_SUBJECT_LENGTH: Final[int] = 16

#: Spelled identically in revision 0032. A string of literals so it renders on both engines.
ONE_PENDING_REVIEW_INDEX: Final[str] = "ix_moderation_reviews_one_pending_per_job"
PENDING_REVIEW_PREDICATE: Final[str] = "decision IS NULL"


class ModerationReviewRow(Base):
    """One held media job waiting for, or carrying, a human decision."""

    __tablename__ = "moderation_reviews"
    __table_args__ = (
        # ONE PENDING REVIEW PER JOB (§6.6). Partial: decided rows for the same job coexist.
        sa.Index(
            ONE_PENDING_REVIEW_INDEX,
            "job_id",
            unique=True,
            postgresql_where=sa.text(PENDING_REVIEW_PREDICATE),
            sqlite_where=sa.text(PENDING_REVIEW_PREDICATE),
        ),
        # The queue's read (pending, oldest first) and the SLA sweep's.
        sa.Index("ix_moderation_reviews_decision_created", "decision", "created_at", "id"),
    )

    id: Mapped[UUID] = mapped_column(sa.Uuid, primary_key=True, default=uuid4)
    job_id: Mapped[UUID] = mapped_column(
        sa.Uuid, sa.ForeignKey("media_jobs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    source: Mapped[MediaReviewSource] = mapped_column(
        enum_type(MediaReviewSource, length=_SHORT_ENUM), nullable=False
    )
    #: The §6.3 subject that was held — ``output_image`` or ``output_frame``.
    subject: Mapped[str] = mapped_column(sa.String(_SUBJECT_LENGTH), nullable=False)
    #: Closed ``CategoryCode`` values the guard reported; empty for a manual hold.
    categories: Mapped[list[str]] = mapped_column(sa.JSON(), nullable=False, default=list)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime, nullable=False, default=utc_now)
    #: ``created_at`` + the 24 h SLA. Past it, a pending review is decided ``expired``.
    due_at: Mapped[datetime] = mapped_column(UtcDateTime, nullable=False)
    decision: Mapped[MediaReviewDecision | None] = mapped_column(
        enum_type(MediaReviewDecision, length=_SHORT_ENUM), nullable=True
    )
    decided_at: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)
    #: No foreign key: ``admin_users`` rows are deactivated, never deleted, and ``actor`` keeps
    #: the name either way.
    actor_id: Mapped[UUID | None] = mapped_column(sa.Uuid, nullable=True)
    actor: Mapped[str | None] = mapped_column(sa.String(REVIEW_ACTOR_LENGTH), nullable=True)
    reason_code: Mapped[AuditReasonCode | None] = mapped_column(
        enum_type(AuditReasonCode), nullable=True
    )
    #: Stamped by the worker once the decision has moved the job (§6.6).
    applied_at: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)
