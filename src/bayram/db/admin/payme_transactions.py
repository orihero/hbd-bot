"""``payme_transactions`` — what the RAIL did, on the rail's own clock.

One module per table, the rule :mod:`bayram.db.admin.plan_purchases` states and every module
in this package follows; :mod:`bayram.db.admin.payment_intents` is the intent half and the
ROUTER is what puts the two beside each other. Everything that module's docstring establishes
holds here: every number is computed by the database, nothing commits, no clock is read, the
session is first and positional, no ``*Row`` escapes, and each function names the index it
rides.

**EVERY WINDOW ON THIS TABLE IS ON ``payme_time`` AND NEVER ON ``created_at``.** ``payme_time``
is the instant PAYME created the transaction; ``created_at`` is when we heard about it. Those
differ by the network, by a retry and, on a bad day, by however long this process was
unavailable — and the twelve-hour timeout, the statement endpoint's period filter and the
stale-transaction sweep all measure from theirs, by specification («с момента создания
транзакции в Payme Business»). A panel that grouped on ours would disagree with every one of
them about which day a payment happened, most visibly for exactly the transactions that had
trouble reaching us.

**``cancel_reason`` IS A BARE INTEGER, and that is an argued exception rather than an
oversight.** The codes are the rail's own vocabulary: defined by them, echoed back numerically
on the wire, extendable by them without asking us. A ``VARCHAR`` mirror or a db enum would be a
translation table with two failure modes and no upside — an unknown incoming code would either
be rejected (losing a cancellation the rail has already applied) or mapped to "unknown"
(destroying the only evidence of what happened). It is named at the PRESENTATION edge only,
from :class:`bayram.payme.protocol.CancelReason`, with the raw integer always rendered beside
the name so a code they add tomorrow still shows.

**THIS TABLE HOLDS NO TELEGRAM ID AT ALL.** A person is reachable from a transaction only by
joining through the intent, which is precisely the join ``/forget`` breaks. That is why the
reads here need no masking branch and no erasure handling: there is nothing personal in them
to erase. It is also why an orphaned transaction is ORDINARY rather than alarming — the table
is on NO retention bound whatsoever while terminal unpaid intents are deleted at 400 days and
there are no foreign keys anywhere, so after thirteen months a transaction whose intent is
gone is a purge that worked, not a referential defect.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql import Select

from bayram.db.admin.sql import TimeWindow, apply_window
from bayram.db.admin.views import RailStateCount, RailTransaction
from bayram.db.models.payme_transaction import PaymeTransactionRow

__all__ = [
    "transaction_funnel",
    "transactions_for_intent",
    "has_recorded_transaction",
]


async def transaction_funnel(
    session: AsyncSession, *, window: TimeWindow | None = None
) -> tuple[RailStateCount, ...]:
    """The window's rail-side transactions grouped by state. Absent states are omitted.

    The intent funnel's other half, and it answers a question the intent funnel cannot: an
    intent that never reached ``paid`` may have had no transaction at all (the customer closed
    the page) or three cancelled ones (their card kept declining). Those are two different
    problems and only this grouping separates them.

    **A state with no rows is ABSENT rather than present at zero**, the standing rule. Four
    states exist and ``cancelled_after_perform`` is written by nothing in this deployment — a
    cancel of a performed transaction is refused with ``-31007``, because
    ``credit_accounts.balance`` is a fungible scalar with no lot structure and a reversal could
    burn a credit paid for in a different purchase. Zero-filling would therefore print a
    permanent ``0`` under a heading that describes something this system cannot do.

    INDEX: ``ix_payme_transactions_state_payme_time`` — the hand-named composite, whose second
    column is exactly this window.
    """
    # Labelled ``total`` and not ``count``: a SQLAlchemy ``Row`` is a named tuple, so a column
    # labelled ``count`` shadows ``tuple.count`` and ``row.count`` silently hands back the bound
    # METHOD rather than the number. It type-checks nowhere and would have read as a database
    # bug at runtime.
    statement: Select[Any] = sa.select(
        PaymeTransactionRow.state, sa.func.count().label("total")
    ).select_from(PaymeTransactionRow)
    statement = apply_window(statement, PaymeTransactionRow.payme_time, window)
    rows = (
        await session.execute(
            statement.group_by(PaymeTransactionRow.state).order_by(PaymeTransactionRow.state)
        )
    ).all()
    return tuple(RailStateCount(state=str(row.state), count=int(row.total)) for row in rows)


async def transactions_for_intent(
    session: AsyncSession, *, intent_id: UUID
) -> tuple[RailTransaction, ...]:
    """Every transaction opened against one intent, **oldest first**.

    Oldest first and not newest first, deliberately breaking this package's list convention,
    because this is not a list — it is a NARRATIVE. "Card declined at 14:02, retried at 14:04,
    performed at 14:05" is the sentence an operator is trying to read, and reversing it makes
    them assemble the story backwards. There is no paging for the same reason: an intent
    accumulates a transaction per attempt and the CHECK constraints make an unbounded number
    of them impossible in practice, so a truncated narrative would be worse than a long one.

    Unbounded in the same sense the dossier's other five reads are: this is one intent, not a
    table scan, and the fan-out is bounded by how many times one customer retried one payment.

    INDEX: ``ix_payme_transactions_intent_id``, then the ``payme_time`` sort in the heap over
    the handful of rows it selects.
    """
    rows = (
        await session.execute(
            sa.select(
                PaymeTransactionRow.payme_transaction_id,
                PaymeTransactionRow.state,
                PaymeTransactionRow.payme_time,
                PaymeTransactionRow.create_time,
                PaymeTransactionRow.perform_time,
                PaymeTransactionRow.cancel_time,
                PaymeTransactionRow.cancel_reason,
            )
            .where(PaymeTransactionRow.intent_id == intent_id)
            .order_by(PaymeTransactionRow.payme_time.asc(), PaymeTransactionRow.id.asc())
        )
    ).all()
    return tuple(
        RailTransaction(
            payme_transaction_id=str(row.payme_transaction_id),
            state=str(row.state),
            payme_time=row.payme_time,
            create_time=row.create_time,
            perform_time=row.perform_time,
            cancel_time=row.cancel_time,
            cancel_reason=None if row.cancel_reason is None else int(row.cancel_reason),
        )
        for row in rows
    )


async def has_recorded_transaction(session: AsyncSession) -> bool:
    """True once Payme has ever opened a transaction here. Window-blind.

    A ROW probe, not a :func:`~bayram.db.admin.sql.has_table` probe, for the reason
    :func:`bayram.db.admin.payment_intents.has_opened_any_intent` states: the migration ships
    with the panel, so the table exists everywhere from day one and its existence answers
    nothing.

    **False beside a true inbound-call probe is a real and expected state**, not a
    contradiction: the gateway daemon runs behind the tunnel and answers Payme's health checks
    long before ``CHECKOUT_PROVIDER`` is switched over, so "we have heard from Payme and no
    transaction has ever been opened" is what this deployment looks like right now. A caller
    must render it as its own legible line rather than as a mismatch.
    """
    probe = await session.scalar(sa.select(sa.literal(1)).select_from(PaymeTransactionRow).limit(1))
    return probe is not None
