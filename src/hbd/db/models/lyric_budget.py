"""``lyric_budgets`` — one row per account holding today's lyric-write count.

**One row per account, not one per day.** A ``(telegram_user_id, day)`` table would grow a
row per active account per day forever and would then need a retention clock, a purge
predicate and a sweep to enforce it. Rolling the count in place gives the same answer with
the same cardinality as ``credit_accounts``: the stored ``day_index`` says which day the
count belongs to, and a claim on a later day overwrites both columns in the one statement
that increments them (``hbd.db.lyric_budget.claim_write``). There is nothing to purge
because nothing accumulates.

**No foreign key to ``users``, and a natural primary key**, for the reason
``credit_accounts`` gives at ``src/hbd/db/models/credit_account.py:5``: ``users`` rows are
written by ``repository._ensure_user`` from ``_create_order``, so the accounts this table
must open a row for are exactly the ones with no ``users`` row yet — this counter is charged
at the lyric step, several screens before any order exists. ``autoincrement=False`` is
required because SQLAlchemy treats an Integer-family primary key as autoincrementing, which
on SQLite would make the column a ROWID alias and renumber an insert supplying Telegram's
own id.

**This table is deliberately NOT erased by ``/forget``**, and that is a decision rather than
an omission. It holds a Telegram id, an integer day number and a small count — no content,
no order, no history, nothing ``orders.telegram_user_id`` does not already say — and it is
an abuse control, not a record about a person. Deleting it on request would make ``/forget``
into "reset my free lyric writes", repeatable, forever: ``/forget`` is one of the three
commands ``hbd.bot.gate.ERASURE_COMMANDS`` exempts from the inbound throttle, so that reset
would be available as fast as a script could type it. This is the same trade
``hbd.db.credit_erasure`` already makes and argues for the allowance's idempotency key —
the replay marker keeps the id, because it is the only thing making the control real. The
cost is stated rather than hidden: a forgotten account leaves one row here carrying its id
and a number, until the account writes again and overwrites it.
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from hbd.db.base import Base, TimestampMixin

__all__ = ["LyricBudgetRow"]


class LyricBudgetRow(TimestampMixin, Base):
    """How many lyrics one Telegram account has been written today, and which day that is."""

    __tablename__ = "lyric_budgets"
    __table_args__ = (
        # The count only ever moves through ``writes + 1`` or a reset to 1, so a negative
        # here means a writer this table does not know about. Refusing the row is cheaper
        # than discovering it as a budget that never refuses.
        sa.CheckConstraint("writes >= 0", name="writes_not_negative"),
    )

    #: Telegram's own account id — the identity the lyric step already holds. See the module
    #: docstring for why there is no foreign key and no autoincrement.
    telegram_user_id: Mapped[int] = mapped_column(
        sa.BigInteger, primary_key=True, autoincrement=False
    )
    #: Whole UTC days since the epoch, from an injected clock — never ambient wall time,
    #: which is what would make "the budget opens again tomorrow" untestable. Computed by
    #: :func:`hbd.lyric_budget.day_index_for`, which is the allowance's own window
    #: arithmetic asked for a one-day window, so both meters turn over on one boundary.
    day_index: Mapped[int] = mapped_column(sa.Integer, nullable=False)
    #: Writes charged against ``day_index``. May exceed the configured ceiling: a refused
    #: write still counts, which is what stops a caller sitting exactly on the line.
    writes: Mapped[int] = mapped_column(sa.Integer, nullable=False, default=0)
