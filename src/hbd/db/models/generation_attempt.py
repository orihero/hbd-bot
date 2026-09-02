"""``generation_attempts`` — every render, and whether its name survived verification.

This is the table the name subsystem is tuned from. ``HBD_NAME_CANDIDATE_ORDER`` is
configuration precisely so a finding from this table can be applied without a code change;
:meth:`hbd.db.attempts.GenerationAttemptRepository.strategy_stats` is the query that
produces that finding.

The row is split along a privacy seam that matters:

* ``name_candidate_strategy``, ``name_candidate_rank`` and ``is_name_verified`` are the
  tuning signal. They are not personal data — "stripped ranked 0 and passed" says nothing
  about anyone — so they are kept indefinitely and the analysis stays valid.
* ``name_candidate_text`` is the recipient's name. It carries the 90-day identity clock
  and the purge nulls it, leaving the tuning signal intact.
* ``stt_transcript`` is the recipient's name AND the whole song around it, which since the
  lyric preview may be text the customer wrote themselves. It therefore carries a SECOND,
  shorter clock: ``text_expires_at``, stamped from ``RetentionPolicy.brief_text_days``, the
  same 30 days that owns ``briefs.note`` and ``briefs.approved_lyrics``. Without it a
  near-verbatim copy of the customer's free text would outlive the copy it was made from by
  sixty days, which is not a retention schedule anybody promised. The 90-day identity sweep
  clears it too, so whichever clock fires first wins.

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
#: Sized for a transcript of a whole SONG, not of a name chunk. The original 200 assumed
#: inpainting would isolate the name chunk before we transcribed it; inpainting is
#: enterprise-gated, so verification hears the entire track and a real transcript ran to
#: ~700 characters. Writers truncate to this bound — see ``attempts.truncate_transcript``.
TRANSCRIPT_LENGTH: Final[int] = 4_000
ERROR_CODE_LENGTH: Final[int] = 48
ERROR_MESSAGE_LENGTH: Final[int] = 500


class GenerationAttemptRow(Base):
    """One provider call, or one acoustic verdict on a rendered name chunk."""

    __tablename__ = "generation_attempts"
    __table_args__ = (
        sa.Index("ix_generation_attempts_tuning", "name_candidate_strategy", "is_name_verified"),
        sa.Index("ix_generation_attempts_identity_sweep", "identity_expires_at"),
        sa.Index("ix_generation_attempts_text_sweep", "text_expires_at"),
        # The admin generation explorer (§5.11, migration 0009), declared here so
        # ``create_all`` and the migration chain build the same indexes.
        #
        # There is deliberately no ``(kind, created_at)``. ``kind`` has four values, so a
        # single-kind filter selects about a quarter of the table and Postgres walks
        # ``ix_generation_attempts_created_at`` backwards with a filter instead — it refuses
        # the composite even with ``enable_seqscan=off``, which means it is not a costing
        # preference. On the second-largest, only-grows table that index was pure write cost.
        #
        # These two are chosen only for a SELECTIVE value. That is the honest claim and it
        # is the one the docstring now makes: an operator chasing one rare error code or one
        # failing vendor is served; a filter on a common value is not, and no index shape
        # can change that.
        sa.Index("ix_generation_attempts_error_code_created_at", "error_code", "created_at", "id"),
        sa.Index("ix_generation_attempts_provider_created_at", "provider", "created_at", "id"),
        # ``metrics.failure_breakdown`` groups by ``error_code`` inside a ``created_at``
        # window with no equality predicate on the leading column, so the composite above
        # cannot serve it — Postgres seq-scans, and did so on every dashboard refresh. This
        # is the shape that query actually wants: ``created_at`` leading, restricted to the
        # rows it looks at.
        sa.Index(
            "ix_generation_attempts_failures_created_at",
            "created_at",
            postgresql_where=sa.text("is_success = false"),
            sqlite_where=sa.text("is_success = 0"),
        ),
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
    identity_expires_at: Mapped[datetime] = mapped_column(UtcDateTime, nullable=False)
    identity_purged_at: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)

    # -- free text: nulled at text_expires_at, and again by the identity sweep ------
    #: What verification heard. Inpainting is enterprise-gated, so this is a transcript of
    #: the WHOLE song — which means it echoes the lyric, which the customer may have
    #: written. Free text about a real person, on the free-text clock.
    stt_transcript: Mapped[str | None] = mapped_column(sa.String(TRANSCRIPT_LENGTH), nullable=True)
    text_expires_at: Mapped[datetime] = mapped_column(UtcDateTime, nullable=False)
    text_purged_at: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)

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
