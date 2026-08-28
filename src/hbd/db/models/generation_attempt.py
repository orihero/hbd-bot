"""``generation_attempts`` — every render, and whether its name survived verification.

This is the table the name subsystem is tuned from. ``HBD_NAME_CANDIDATE_ORDER`` is
configuration precisely so a finding from this table can be applied without a code change;
:meth:`hbd.db.attempts.GenerationAttemptRepository.strategy_stats` is the query that
produces that finding.

The row is split along a privacy seam that matters:

* ``name_candidate_strategy``, ``name_candidate_rank`` and ``is_name_verified`` are the
  tuning signal. They are not personal data — "stripped ranked 0 and passed" says nothing
  about anyone — so they are kept indefinitely and the analysis stays valid.
* ``name_candidate_text`` and ``stt_transcript`` **are** the recipient's name. They carry
  the 90-day identity clock and the purge nulls them, leaving the tuning signal intact.

``order_id`` is nullable with ``ON DELETE SET NULL``: a name preview happens before an
order exists, and an attempt must outlive the order it belonged to or the tuning data
evaporates on the first purge run.
"""

from __future__ import annotations

from datetime import datetime
from typing import Final
from uuid import UUID, uuid4

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from hbd.contracts import MAX_CANDIDATE_CHARS, CostSource, Language, NameStrategy
from hbd.db.base import Base, UtcDateTime, enum_type, utc_now
from hbd.db.enums import GenerationKind

__all__ = [
    "GenerationAttemptRow",
    "PROVIDER_LENGTH",
    "REMOTE_ID_LENGTH",
    "TRANSCRIPT_LENGTH",
    "ERROR_MESSAGE_LENGTH",
]

PROVIDER_LENGTH: Final[int] = 64
REMOTE_ID_LENGTH: Final[int] = 128
#: A transcript of a name chunk, not of a song. Generous, but bounded.
TRANSCRIPT_LENGTH: Final[int] = 200
ERROR_CODE_LENGTH: Final[int] = 48
ERROR_MESSAGE_LENGTH: Final[int] = 500


class GenerationAttemptRow(Base):
    """One provider call, or one acoustic verdict on a rendered name chunk."""

    __tablename__ = "generation_attempts"
    __table_args__ = (
        sa.Index("ix_generation_attempts_tuning", "name_candidate_strategy", "is_name_verified"),
        sa.Index("ix_generation_attempts_identity_sweep", "identity_expires_at"),
    )

    id: Mapped[UUID] = mapped_column(sa.Uuid, primary_key=True, default=uuid4)
    order_id: Mapped[UUID | None] = mapped_column(
        sa.Uuid, sa.ForeignKey("orders.id", ondelete="SET NULL"), nullable=True, index=True
    )
    kind: Mapped[GenerationKind] = mapped_column(enum_type(GenerationKind), nullable=False)
    #: Ordinal within an order for this kind — greeting 0, 1, 2.
    sequence: Mapped[int] = mapped_column(sa.Integer, nullable=False, default=0)
    #: ``None`` for a NAME_VERIFICATION verdict, which is our own judgement, not a vendor's.
    provider: Mapped[str | None] = mapped_column(sa.String(PROVIDER_LENGTH), nullable=True)
    provider_remote_id: Mapped[str | None] = mapped_column(
        sa.String(REMOTE_ID_LENGTH), nullable=True
    )
    #: Retry ordinal, zero-based, within this (order, kind, sequence).
    attempt: Mapped[int] = mapped_column(sa.Integer, nullable=False, default=0)
    is_success: Mapped[bool] = mapped_column(sa.Boolean, nullable=False, default=False)
    language: Mapped[Language | None] = mapped_column(enum_type(Language), nullable=True)

    # -- tuning signal: never purged, never personal data ---------------------
    name_candidate_strategy: Mapped[NameStrategy | None] = mapped_column(
        enum_type(NameStrategy), nullable=True
    )
    name_candidate_rank: Mapped[int | None] = mapped_column(sa.Integer, nullable=True)
    #: ``None`` where verification did not run (disabled, or not a name-bearing render).
    is_name_verified: Mapped[bool | None] = mapped_column(sa.Boolean, nullable=True)
    match_confidence: Mapped[float | None] = mapped_column(sa.Float, nullable=True)

    # -- personal data: nulled at identity_expires_at -------------------------
    name_candidate_text: Mapped[str | None] = mapped_column(
        sa.String(MAX_CANDIDATE_CHARS), nullable=True
    )
    stt_transcript: Mapped[str | None] = mapped_column(sa.String(TRANSCRIPT_LENGTH), nullable=True)
    identity_expires_at: Mapped[datetime] = mapped_column(UtcDateTime, nullable=False)
    identity_purged_at: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)

    # -- cost and failure ledger ----------------------------------------------
    error_code: Mapped[str | None] = mapped_column(sa.String(ERROR_CODE_LENGTH), nullable=True)
    error_message: Mapped[str | None] = mapped_column(
        sa.String(ERROR_MESSAGE_LENGTH), nullable=True
    )
    cost_usd: Mapped[float] = mapped_column(sa.Float, nullable=False, default=0.0)
    cost_source: Mapped[CostSource] = mapped_column(
        enum_type(CostSource), nullable=False, default=CostSource.ESTIMATED
    )
    latency_ms: Mapped[int] = mapped_column(sa.Integer, nullable=False, default=0)

    created_at: Mapped[datetime] = mapped_column(
        UtcDateTime, nullable=False, default=utc_now, index=True
    )
