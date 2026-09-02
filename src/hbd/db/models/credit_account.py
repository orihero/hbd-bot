"""``credit_accounts`` — the authoritative balance, and the concurrency control, in one row.

Three decisions here are load-bearing and none of them is schema taste:

* **The primary key is the Telegram account id, not ``users.id``, and there is no foreign
  key.** ``repository._ensure_user`` (``src/hbd/db/repository.py:130``) is the only writer
  of ``users`` today and it runs from ``_create_order``, so a person who walks the wizard
  and never confirms has no ``users`` row at all — and the inbound upsert that will give
  them one arrives asynchronously, off the hot path. An FK would make opening an account
  depend on a row that may not exist yet, for a join nothing performs: every reader here
  already holds the Telegram id.
* **``balance`` moves only through ``UPDATE … SET balance = balance - :cost WHERE
  telegram_user_id = :id AND balance >= :cost`` with a rowcount check.** Two concurrent
  charges cannot both see a rowcount of 1 under Postgres READ COMMITTED, so the guard needs
  no ``SELECT … FOR UPDATE`` (verified a silent no-op in SQLAlchemy's SQLite dialect) and no
  retry loop. ``ck_credit_accounts_balance_not_negative`` is the second layer: if a writer
  ever forgets the ``WHERE``, the row refuses rather than going quietly negative.
* **This table holds no personal data.** A Telegram id, three integers and two clocks say
  nothing about a person that ``orders.telegram_user_id`` does not already say, and there
  is no free text anywhere, which is why it is deliberately absent from
  ``tables_with_personal_data`` in ``tests/test_db/test_privacy_constraints.py``. It is
  still erasable — ``/forget`` drops the row, because a balance is not an audit fact — but
  it carries no ``expires_at`` and no purge clock of its own.

``balance`` is a second representation of ``SUM(credit_ledger.delta)`` and that duplication
is bought deliberately: it is what makes the debit a single lock-free statement that is
identical on both engines. The drift it risks is made *detectable* rather than assumed
impossible — both writes happen in one transaction, and the credits tests assert
``balance == SUM(delta)`` after every operation.
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from hbd.db.base import Base, TimestampMixin

__all__ = ["CreditAccountRow"]


class CreditAccountRow(TimestampMixin, Base):
    """One Telegram account's entitlement to renders.

    ``lifetime_granted`` is not the same fact as ``balance`` and neither can be derived
    from the other once anything has been spent. It is what an operator needs in order to
    answer "has this account already been comped?" without replaying the whole ledger.
    """

    __tablename__ = "credit_accounts"
    __table_args__ = (
        # The last line of defence under the conditional UPDATE. A debit that skipped its
        # `balance >= :cost` predicate would otherwise render a free song and leave a
        # negative row that every later read would silently trust.
        sa.CheckConstraint("balance >= 0", name="balance_not_negative"),
    )

    #: A natural key: Telegram's own account id, which is already the identity every gate,
    #: order and ledger row speaks. ``autoincrement=False`` is required because SQLAlchemy
    #: treats an Integer-family primary key as autoincrementing by default, which on SQLite
    #: would make this an implicit ROWID alias and quietly renumber an insert that supplied
    #: its own value. Being a natural key is also why no
    #: ``sa.BigInteger().with_variant(sa.Integer, "sqlite")`` appears here: that variant
    #: exists only to make SQLite autoincrement a BIGINT column, and nothing autoincrements.
    telegram_user_id: Mapped[int] = mapped_column(
        sa.BigInteger, primary_key=True, autoincrement=False
    )
    #: Credits available to spend right now. Authoritative; see the module docstring.
    balance: Mapped[int] = mapped_column(sa.Integer, nullable=False, default=0)
    #: Every credit ever added, allowances included. Monotone, never decremented.
    lifetime_granted: Mapped[int] = mapped_column(sa.Integer, nullable=False, default=0)
    #: The last rolling-allowance window this account was minted for, as a deterministic
    #: period index derived from an injected clock — never from ambient wall time, which is
    #: what would make the mint untestable and non-idempotent across processes. ``None``
    #: until the first allowance lands, which is also how "opened but never granted" is
    #: distinguishable from "granted in period 0".
    allowance_period_index: Mapped[int | None] = mapped_column(sa.Integer, nullable=True)
