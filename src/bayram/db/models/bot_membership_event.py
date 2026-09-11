"""``bot_membership_events`` — append-only, so churn is a count of PASSAGES, not survivors.

A customer blocking the bot was recorded nowhere. ``bot/delivery.py`` catches
``TelegramForbiddenError`` only to skip a retry and persists nothing, no handler is
registered on aiogram's ``my_chat_member`` observer, and ``users`` has no column for it —
so "how many customers left us last month" had no answer at all, and the Churn card could
not be drawn honestly.

**Why this table exists ALONGSIDE ``users.blocked_bot_at`` rather than instead of it.**
The column records the CURRENT state and the LAST transition, which is exactly what the
gauge needs and exactly what a period count cannot be built from. An account that blocks on
Monday and comes back on Wednesday has its column set and then cleared, so Monday's bucket
silently shrinks and every historical churn number drifts DOWNWARD precisely when win-backs
happen — yesterday's number stops being yesterday's number. A column also conflates three
different accounts under one ``NULL``: never blocked, blocked-and-returned, and never
observed. Repeat churn and win-back are invisible.

That split is not novel here. It is ``credit_accounts.balance`` (current) beside
``credit_ledger`` (history), for the same reason and with the same division of labour: the
gauge needs no window function over the event table, and a forgotten account's current
state survives its own anonymisation.

**Why not ``admin_audit_log``.** Structurally impossible, not merely untidy.
``actor_username`` is NOT NULL and ``actor_role`` is an ``AdminRole``; a customer is
neither. The chain is HMAC-SHA256 under a key that exists only in the admin process's
environment, so the bot and the worker cannot compute a ``chain_hmac`` and therefore cannot
append. ADMIN_PANEL_PLAN §12.4 revokes ``UPDATE``/``DELETE`` from the app role on that
table, and it is on a 730-day row clock. Writing customer-originated rows into an
operator's tamper-evident chain would mis-attribute the actor and require handing the bot
the audit key.

**No foreign key to ``users``**, following ``credit_ledger`` and ``vendor_usage``. The row
records a passage that must outlive any future deletion of the account row, and a cascade
here would delete the churn history that explains why the account went.

**One instant, not two.** :attr:`BotMembershipEventRow.at` is when the transition happened
as well as we can know: for ``MEMBERSHIP_UPDATE`` that is Telegram's own update instant,
and for ``DELIVERY_REFUSAL`` it is the moment the send was refused — all we learn there is
that it had already happened. :attr:`BotMembershipEventRow.source` beside it is what tells
a reader which, in the same provenance discipline as ``vendor_usage.cost_source``.

**The null-never-zero rule is satisfied VACUOUSLY here, and that is worth stating** so
nobody later "improves" the table with a counter. There is no quantity column to default to
zero: the measurement is the EXISTENCE of a row, and a row is either present or absent,
which is the one counting scheme that cannot be defaulted into a lie.

**Not personal data on either lawful route, and the omission is recorded rather than
silent.** It is in NEITHER ``tables_with_personal_data`` nor ``tables_erased_on_request`` in
``tests/test_db/test_privacy_constraints.py``, and it may NOT borrow ``vendor_usage``'s
argument for that: unlike ``vendor_usage`` this table carries a ``telegram_user_id`` and is
therefore about an identified person. Its route is ``credit_ledger``'s and
``plan_purchases``' — erasure by ANONYMISATION, nulling the id in place and keeping the row
so the day counts survive. It is not in ``tables_erased_on_request`` because that set's
semantics are "the absence of a row IS the erasure record; ``/forget`` DELETEs it outright",
which is ``user_profiles``' treatment and the opposite of this one. It is not in
``tables_with_personal_data`` because that set demands a ``*_expires_at`` column, and that
suffix obliges a sweep BY NAME in ``tests/test_db/test_audit_retention.py`` and would claim
a legal schedule this table does not have. Its growth is bounded instead by
``bayram.db.purge.BOT_MEMBERSHIP_RETENTION_DAYS`` — a 400-day CUTOFF on ``at``, thirteen months
so a year-over-year churn comparison still has last March to compare against.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from bayram.contracts import BotBlockSource, BotMembershipEvent
from bayram.db.base import Base, UtcDateTime, enum_type

__all__ = ["BotMembershipEventRow"]


class BotMembershipEventRow(Base):
    """One OBSERVED transition in whether a customer can be messaged.

    ``TimestampMixin`` is deliberately not used, following ``credit_ledger`` and
    ``vendor_usage``: this row is a record of a moment that has already passed, an
    ``updated_at`` could never be true, and offering one would invite a writer to amend a
    record whose whole value is that nobody amends it. There is no separate ``created_at``
    either — :attr:`at` is the one instant this row is about, and a second clock differing
    from it by the width of one transaction would be a column nobody could interpret.

    **Deliberately NO CHECK constraints.** Over-constraining a telemetry table loses rows,
    and a lost row is a hole in the churn record; ``vendor_usage`` makes the same call about
    the ``error_code``/``is_success`` pairing for the same reason.
    """

    __tablename__ = "bot_membership_events"
    # No ``__table_args__``: both indexes come from ``index=True`` below, so they take
    # ``NAMING_CONVENTION``'s ``ix`` template and match exactly what the migration creates
    # through ``batch_op.f()``.

    id: Mapped[UUID] = mapped_column(sa.Uuid, primary_key=True, default=uuid4)
    #: Whose transition it was. **NULLABLE ONLY SO THAT ERASURE HAS SOMEWHERE TO GO** — the
    #: writer always knows the account, so a ``NULL`` means one thing only: ``/forget`` ran
    #: and anonymised this row. Identical in spirit to ``credit_ledger.telegram_user_id``
    #: and ``plan_purchases.telegram_user_id``. Indexed for the ERASURE path first — the
    #: anonymising ``UPDATE`` runs inside the transaction a customer's ``/forget`` is
    #: waiting on and must not scan — and for a per-account support history second.
    telegram_user_id: Mapped[int | None] = mapped_column(sa.BigInteger, nullable=True, index=True)
    #: Which direction. NOT NULL: a transition with no direction is not a fact about
    #: anything.
    event: Mapped[BotMembershipEvent] = mapped_column(enum_type(BotMembershipEvent), nullable=False)
    #: How we came to know. NOT NULL, for the same reason ``vendor_usage.cost_source`` is
    #: bound to its figure: an instant inferred from a refused send is a weaker fact than
    #: one Telegram stamped, and a reader who cannot tell them apart is reading a guess.
    source: Mapped[BotBlockSource] = mapped_column(enum_type(BotBlockSource), nullable=False)
    #: When the transition happened, as well as we can know. NOT NULL. Indexed because both
    #: readers of this table bound on it: the churn series filters and groups on a window,
    #: and the retention sweep's DELETE predicate is ``at < cutoff``. Deliberately no
    #: composite index beside it — this table gains rows only on real transitions, a few a
    #: day at this product's scale, so a single-column index over the window is the whole of
    #: the access plan.
    at: Mapped[datetime] = mapped_column(UtcDateTime, nullable=False, index=True)
