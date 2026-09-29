"""``media_credit_ledger`` and ``media_credit_balances`` — the kind-scoped refund credit.

IMAGE_VIDEO_SPEC §3.2.2, §7.5, O13, D25. A media refund is not a song credit: the song credit
is one fungible song-denominated scalar and ``topup_purchases`` CHECKs ``credits_granted > 0``,
so a failed video refunds ONE VIDEO, spendable only on the same SKU.

**TWO TABLES, BECAUSE A LOCK ON A ROW THAT MAY NOT EXIST LOCKS NOTHING.** The ledger is the
append-only audit trail; the balance is materialised so a spend is two conditional UPDATEs
rather than a ``SELECT … FOR UPDATE`` — which is a verified silent no-op on the SQLite unit
suite, and on Postgres would lock a ``credit_accounts`` row that is absent for a media-only
account or deleted by ``/forget``. **Spend** = job ``quoted → paid`` (rowcount 1) + ``balance =
balance - 1 WHERE balance >= 1`` (rowcount 1) + ledger ``-1 spent`` + receipt, in one
transaction; either rowcount 0 rolls it back. **Refund** = claim ``media_jobs.refund_state``
NULL → ``due``, ledger ``+1``, balance upsert ``+1``, ``granted``. A reconciliation test holds
``balance = SUM(delta)`` per (account, sku).

**A JOB REFUNDS AT MOST ONCE, WHATEVER THE REASON.** Two partial unique indexes, not trust in
the call sites: one refund per job (``delta > 0`` except an operator's correction) and one
spend per job. A deadline failure followed by a late generation failure, or a variant failure
followed by an output block, therefore grants exactly one credit.

**RETENTION.** The balance is DELETED on ``/forget`` (``tables_erased_on_request``: the absence
of the row is the erasure record). The ledger takes the third route — ``/forget`` nulls the id
and keeps the movement; a 400-day cutoff bounds the anonymised remainder only.
"""

from __future__ import annotations

from datetime import datetime
from typing import Final
from uuid import UUID, uuid4

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from bayram.db.base import Base, UtcDateTime, enum_type, utc_now
from bayram.db.enums import MediaCreditReason, MediaSku

__all__ = [
    "MediaCreditBalanceRow",
    "MediaCreditLedgerRow",
    "ONE_REFUND_PER_JOB_INDEX",
    "ONE_REFUND_PER_JOB_PREDICATE",
    "ONE_SPEND_PER_JOB_INDEX",
    "ONE_SPEND_PER_JOB_PREDICATE",
    "DELTA_MATCHES_REASON",
]

ONE_REFUND_PER_JOB_INDEX: Final[str] = "ix_media_credit_ledger_one_refund_per_job"
ONE_REFUND_PER_JOB_PREDICATE: Final[str] = "delta > 0 AND reason <> 'admin_correction'"
ONE_SPEND_PER_JOB_INDEX: Final[str] = "ix_media_credit_ledger_one_spend_per_job"
ONE_SPEND_PER_JOB_PREDICATE: Final[str] = "reason = 'spent'"
#: ``spent`` is always -1, an operator's correction either way, every other reason +1.
DELTA_MATCHES_REASON: Final[str] = (
    "(reason = 'spent' AND delta = -1)"
    " OR (reason = 'admin_correction' AND delta IN (-1, 1))"
    " OR (reason NOT IN ('spent', 'admin_correction') AND delta = 1)"
)

_ACTOR_LENGTH: Final[int] = 64


class MediaCreditLedgerRow(Base):
    """One movement of one account's balance for one SKU."""

    __tablename__ = "media_credit_ledger"
    __table_args__ = (
        sa.CheckConstraint(DELTA_MATCHES_REASON, name="delta_matches_reason"),
        sa.Index(
            ONE_REFUND_PER_JOB_INDEX,
            "job_id",
            unique=True,
            postgresql_where=sa.text(ONE_REFUND_PER_JOB_PREDICATE),
            sqlite_where=sa.text(ONE_REFUND_PER_JOB_PREDICATE),
        ),
        sa.Index(
            ONE_SPEND_PER_JOB_INDEX,
            "job_id",
            unique=True,
            postgresql_where=sa.text(ONE_SPEND_PER_JOB_PREDICATE),
            sqlite_where=sa.text(ONE_SPEND_PER_JOB_PREDICATE),
        ),
    )

    id: Mapped[UUID] = mapped_column(sa.Uuid, primary_key=True, default=uuid4)
    #: NULLABLE ONLY SO ERASURE HAS SOMEWHERE TO GO: a NULL means ``/forget`` ran.
    telegram_user_id: Mapped[int | None] = mapped_column(sa.BigInteger, nullable=True, index=True)
    sku: Mapped[MediaSku] = mapped_column(enum_type(MediaSku), nullable=False)
    delta: Mapped[int] = mapped_column(sa.SmallInteger, nullable=False)
    reason: Mapped[MediaCreditReason] = mapped_column(enum_type(MediaCreditReason), nullable=False)
    #: No foreign key: the ledger outlives a purged job row. NULL only on an operator's
    #: correction that names no job.
    job_id: Mapped[UUID | None] = mapped_column(sa.Uuid, nullable=True)
    #: ``worker`` / ``bot`` / an operator's login.
    actor: Mapped[str | None] = mapped_column(sa.String(_ACTOR_LENGTH), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        UtcDateTime, nullable=False, default=utc_now, index=True
    )


class MediaCreditBalanceRow(Base):
    """What one account may spend on one SKU right now. Materialised from the ledger."""

    __tablename__ = "media_credit_balances"
    __table_args__ = (sa.CheckConstraint("balance >= 0", name="balance_not_negative"),)

    telegram_user_id: Mapped[int] = mapped_column(
        sa.BigInteger, primary_key=True, autoincrement=False
    )
    sku: Mapped[MediaSku] = mapped_column(enum_type(MediaSku), primary_key=True)
    balance: Mapped[int] = mapped_column(sa.Integer, nullable=False, default=0)
    updated_at: Mapped[datetime] = mapped_column(
        UtcDateTime, nullable=False, default=utc_now, onupdate=utc_now
    )
