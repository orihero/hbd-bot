"""The SQL the redirect rail's state machine is made of — one statement per function.

The exact sibling of :mod:`hbd.db.topup_sql` and :mod:`hbd.db.plan_sql`, written to the same
rule: nothing here decides anything, every function performs exactly one statement, takes its
session FIRST and POSITIONAL, takes ``now`` as a parameter and commits nothing. The policy
that sequences them lives in :mod:`hbd.db.payme`, so that "what does a settlement write?"
reads as a short list of named steps rather than as SQL embedded in a state machine.

**THE ROWCOUNT IS THE LOCK. That is the one idea in this file.**

Six of the writes below are conditional ``UPDATE``s of the form ``UPDATE … SET <new state>
WHERE id = :id AND <the state I expect>``, and each reports whether it touched a row. That
boolean is not a convenience — it is the concurrency primitive. Two connections that read the
same row a moment apart both go on to issue the same ``UPDATE``; under Postgres READ COMMITTED
the second one re-evaluates its ``WHERE`` clause against the first one's committed result, so
exactly one of them can see a rowcount of 1. The loser writes nothing and is told so. There is
no read-then-decide-then-write anywhere on this path, because that sequence is the shape of
every double charge in this problem domain.

This repository already runs on that primitive in two places, and both are money:
:func:`hbd.db.credit_sql.debit_balance` is ``… SET balance = balance - :cost WHERE balance >=
:cost``, and :func:`hbd.db.plan_sql.claim_plan_song` is ``… SET songs_used = songs_used + 1
WHERE songs_used = :seen``. What is new here is only that the guard is a STATE rather than a
number, and that four rows in three tables ride on the outcome instead of one.

**The two alternatives are rejected on this repository's own recorded evidence, not on taste.**

* ``SELECT … FOR UPDATE`` is a **verified silent no-op** in SQLAlchemy's SQLite dialect —
  ``credit_sql``'s docstring records the finding. The unit suite is SQLite. A lock that is
  real in production and absent in every test is worse than no lock: it makes the race
  untestable while reading as though it had been handled.
* ``session.begin_nested()`` savepoints were **reproduced behaving differently** on aiosqlite
  and on Postgres — ``credit_sql.upsert_statement``'s docstring records that a SAVEPOINT taken
  as the first statement of a transaction does not roll back on aiosqlite while it does on
  Postgres. A settlement whose atomicity depended on it would be validated by a suite that
  could not observe the failure.

**Every column is passed explicitly on the two inserts**, including ``id``, ``created_at`` and
``updated_at``. These are Core ``INSERT``s and the Python-side ``default=`` on a mapped column
fires on an ORM flush only: omitting one earns a NOT NULL violation on Postgres and a surprise
on SQLite. ``insert_topup`` and ``insert_plan`` carry the same note for the same reason.

**The four single-row lookups carry ``populate_existing=True``, and that is a correctness fix
rather than a tuning knob.** Every state change in this module is a Core ``UPDATE``, which the
ORM's identity map knows nothing about. A ``select()`` that finds an entity already loaded in
the session hands back the LOADED copy without refreshing its columns — so a read-back taken
immediately after ``mark_performed`` would report ``perform_time`` as ``None``, and the reply
Payme received would have said the charge had not been performed in the same breath as
performing it. :func:`hbd.db.credit_sql.account_state` avoids the identical trap by selecting
columns instead of the entity; this module needs the entity, so it forces the refresh instead.
The four are the reads used as read-backs; the list reads below are first loads by
construction and are left alone.

These names are public to the ``hbd.db`` package and to nothing else (Rule 15): a caller
outside persistence has no business holding a session, which is exactly why
:mod:`hbd.payme.ports` declares a protocol of ``Result``-returning coroutines instead.

See ``PAYME_INTEGRATION §3`` for the settlement's ordering argument and ``§5`` for the five
replay guarantees the persisted clocks below exist to serve.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from uuid import UUID, uuid4

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from hbd.db.credit_sql import insert_or_ignore, rowcount_of
from hbd.db.enums import CreditEntryKind, IntentProduct, PaymentIntentState, PaymeState
from hbd.db.models.credit_ledger import CreditLedgerRow
from hbd.db.models.payme_rpc_log import RPC_METHOD_LENGTH, PaymeRpcLogRow
from hbd.db.models.payme_transaction import PaymeTransactionRow
from hbd.db.models.payment_intent import PaymentIntentRow
from hbd.db.models.plan_purchase import PlanPurchaseRow
from hbd.db.models.topup_purchase import TopupPurchaseRow

__all__ = [
    # Reads
    "intent_by_ref",
    "intent_by_key",
    "intent_by_id",
    "transaction_by_payme_id",
    "transactions_in_period",
    "transaction_count_for_intent",
    "unnotified_settled_intents",
    "lapsed_pending_intents",
    "stale_created_transactions",
    "settlement_counts",
    # Writes
    "insert_intent",
    "insert_transaction",
    "hold_intent",
    "release_intent",
    "claim_intent",
    "claim_intent_for_operator",
    "expire_intent",
    "mark_performed",
    "mark_cancelled",
    "mark_intent_notified",
    "anonymise_intents",
    "insert_rpc_log",
]


# ---------------------------------------------------------------------------
# Reads
# ---------------------------------------------------------------------------
async def intent_by_ref(session: AsyncSession, public_ref: str) -> PaymentIntentRow | None:
    """The intent behind the opaque reference the rail quotes back at us.

    Every inbound call names the account, and this is the only column it can name: the
    ``ac.<field>`` value in the checkout link is ``public_ref`` and nothing else. ``None`` is
    an ordinary answer — a customer can mistype a reference into Payme's form — and it becomes
    ``-31050``, so it must not be an exception.
    """
    return (
        await session.execute(
            sa.select(PaymentIntentRow)
            .where(PaymentIntentRow.public_ref == public_ref)
            .execution_options(populate_existing=True)
        )
    ).scalar_one_or_none()


async def intent_by_key(session: AsyncSession, idempotency_key: str) -> PaymentIntentRow | None:
    """The intent opened under ``idempotency_key``. The read-back after an ignored insert.

    :func:`insert_intent` reports that it lost — it cannot report WHAT it lost to, because
    ``INSERT … ON CONFLICT DO NOTHING`` returns nothing at all. The read-back is what makes a
    replayed open return the SAME ``public_ref`` and therefore the SAME URL, which is the
    guarantee that stops one purchase putting two live payment pages in one customer's chat.
    """
    return (
        await session.execute(
            sa.select(PaymentIntentRow)
            .where(PaymentIntentRow.idempotency_key == idempotency_key)
            .execution_options(populate_existing=True)
        )
    ).scalar_one_or_none()


async def intent_by_id(session: AsyncSession, intent_id: UUID) -> PaymentIntentRow | None:
    """The intent a transaction row points at.

    ``sa.select`` rather than ``session.get`` deliberately, and the difference is load-bearing
    inside a settlement: ``session.get`` consults the identity map first and would hand back a
    copy read BEFORE the conditional ``UPDATE``s in the same transaction, which is precisely
    the stale read the whole module is written to avoid. :func:`hbd.db.credit_sql.account_state`
    carries the same note.
    """
    return (
        await session.execute(
            sa.select(PaymentIntentRow)
            .where(PaymentIntentRow.id == intent_id)
            .execution_options(populate_existing=True)
        )
    ).scalar_one_or_none()


async def transaction_by_payme_id(
    session: AsyncSession, payme_transaction_id: str
) -> PaymeTransactionRow | None:
    """The transaction under THEIR 24-character id. The first statement of every method.

    Compared as text, never parsed as a number: the id is a Mongo ObjectId, its leading
    characters are a timestamp, and any numeric coercion of it is a bug waiting for a
    hexadecimal digit.
    """
    return (
        await session.execute(
            sa.select(PaymeTransactionRow)
            .where(PaymeTransactionRow.payme_transaction_id == payme_transaction_id)
            .execution_options(populate_existing=True)
        )
    ).scalar_one_or_none()


async def transactions_in_period(
    session: AsyncSession, *, frm: datetime, to: datetime
) -> Sequence[tuple[PaymeTransactionRow, str, IntentProduct]]:
    """Every transaction created in ``[frm, to]``, with its intent's account value and product.

    **Inclusive at both ends and sorted ascending on ``payme_time``.** Both facts are the
    specification rather than a preference: the rail reconciles against its OWN creation
    clock, so a window that excluded its endpoints would silently drop the transactions
    created at midnight on a daily export, and a differently sorted list is a list a human
    cannot diff against a cabinet export line by line.

    **A join rather than a transaction read followed by N intent reads.** A statement row IS
    the pair — the rail asks for the account beside every transaction because a list of
    transaction ids with no order references is a list nobody can act on — so fetching them
    together is one statement for one concept, and the alternative is an N+1 whose N is
    "however many payments happened that day".

    An inner join is correct here and cannot lose a row: ``payme_transactions.intent_id`` is
    written from an intent that already existed in the same transaction, and nothing ever
    deletes an intent that has a transaction on it (``hbd.db.purge`` sweeps terminal intents
    only, and a transaction moves its intent out of every terminal state it could be swept
    from). There is no foreign key to enforce that — this package declares none anywhere in
    this area — so it is stated here rather than assumed.
    """
    result = await session.execute(
        sa.select(PaymeTransactionRow, PaymentIntentRow.public_ref, PaymentIntentRow.product)
        .join(PaymentIntentRow, PaymentIntentRow.id == PaymeTransactionRow.intent_id)
        .where(PaymeTransactionRow.payme_time >= frm, PaymeTransactionRow.payme_time <= to)
        .order_by(PaymeTransactionRow.payme_time.asc(), PaymeTransactionRow.id.asc())
    )
    return [(row[0], row[1], row[2]) for row in result.all()]


async def transaction_count_for_intent(session: AsyncSession, *, intent_id: UUID) -> int:
    """How many rail-side transactions this intent has ever carried.

    The operator CLI's abandoned/expired split is a read-time predicate over this number and
    nothing else: an ``expired`` intent with zero transactions is a funnel problem (the
    customer never opened the payment page), while an ``expired`` intent that once held one is
    a rail problem (the charge was attempted and never completed). Computing it on read is why
    neither outcome needs a column, and therefore why the two can never drift apart from what
    the transaction table actually holds.
    """
    total = await session.scalar(
        sa.select(sa.func.count())
        .select_from(PaymeTransactionRow)
        .where(PaymeTransactionRow.intent_id == intent_id)
    )
    return int(total or 0)


async def unnotified_settled_intents(
    session: AsyncSession, *, older_than: datetime, limit: int
) -> Sequence[PaymentIntentRow]:
    """Paid intents whose customer has not been told, settled at or before ``older_than``.

    The delivery backstop's input. ``older_than`` is what stops the sweep racing the enqueue it
    exists to back up: the post-commit enqueue fires within milliseconds of the settlement, so
    a sweep with no lower bound would double-enqueue every payment it caught mid-flight. The
    job itself is idempotent, but a backstop that fired on the healthy path would make its own
    error rate the thing nobody could read.

    **An erased intent is not in this set.** ``telegram_user_id IS NULL`` means ``/forget`` ran
    between the payment and the notification, so there is nobody to tell and ``notified_at``
    will therefore never be stamped. Filtering here rather than returning the row and letting
    the job decline it is the difference between an empty backlog and a row this sweep
    re-enqueues every five minutes for the life of the deployment.

    Ordered oldest-first so a backlog drains in the order customers have been waiting.
    """
    return (
        (
            await session.execute(
                sa.select(PaymentIntentRow)
                .where(
                    PaymentIntentRow.state == PaymentIntentState.PAID,
                    PaymentIntentRow.notified_at.is_(None),
                    PaymentIntentRow.telegram_user_id.is_not(None),
                    PaymentIntentRow.settled_at <= older_than,
                )
                .order_by(PaymentIntentRow.settled_at.asc())
                .limit(limit)
            )
        )
        .scalars()
        .all()
    )


async def lapsed_pending_intents(
    session: AsyncSession, *, now: datetime, limit: int
) -> Sequence[PaymentIntentRow]:
    """Intents whose validity window has closed with nobody paying. **``pending`` ONLY.**

    ``state = 'pending' AND valid_until <= :now`` is the whole predicate, and the omission of
    ``awaiting`` is the safety property rather than an oversight: an intent under a live
    rail-side transaction is not in the set this query can see. Our clock and the rail's are
    not the same clock, and an intent expired here while a card was being charged there
    produces the single worst outcome this system has — a customer whose money moved against
    an order we had already refused.

    Served by the hand-named composite ``ix_payment_intents_state_valid_until``, whose second
    column exists because ``pending`` is the commonest of the five states and the leading one
    alone would scan every intent ever opened.
    """
    return (
        (
            await session.execute(
                sa.select(PaymentIntentRow)
                .where(
                    PaymentIntentRow.state == PaymentIntentState.PENDING,
                    PaymentIntentRow.valid_until <= now,
                )
                .order_by(PaymentIntentRow.valid_until.asc())
                .limit(limit)
            )
        )
        .scalars()
        .all()
    )


async def stale_created_transactions(
    session: AsyncSession, *, cutoff: datetime, limit: int
) -> Sequence[PaymeTransactionRow]:
    """Transactions still in ``created`` whose ``payme_time`` is at or before ``cutoff``.

    The caller computes ``cutoff`` from the configured timeout so that the SQL carries no
    opinion about how long twelve hours is — which is what lets certification drive the same
    branch in seconds.

    ``payme_time`` and never ``created_at``: the window the specification defines runs «с
    момента создания транзакции в Payme Business», from THEIR instant. Ours differs from it by
    the network, by a retry and, on a bad day, by however long this process was unavailable —
    and measuring from ours would close the window early on exactly the transactions that had
    trouble reaching us.
    """
    return (
        (
            await session.execute(
                sa.select(PaymeTransactionRow)
                .where(
                    PaymeTransactionRow.state == PaymeState.CREATED,
                    PaymeTransactionRow.payme_time <= cutoff,
                )
                .order_by(PaymeTransactionRow.payme_time.asc())
                .limit(limit)
            )
        )
        .scalars()
        .all()
    )


async def settlement_counts(
    session: AsyncSession, *, frm: datetime, to: datetime
) -> tuple[int, int, int]:
    """``(transactions_performed, receipts_written, grants_written)`` over one window.

    The only automated reconciliation this integration can have. The protocol is entirely
    INBOUND — there is no Merchant API method a merchant may call — so nothing here can ask the
    rail what it thinks happened, and these three counts are what stands in for that.

    One statement with three scalar subqueries rather than three round trips, because the three
    numbers are only meaningful against each other: read separately, a settlement landing
    between the first and the third would produce a mismatch that is a race and not a defect,
    and the sweep would report an incident every time somebody bought a song at the wrong
    moment.

    The two populations are counted on DIFFERENT clocks and that is deliberate:
    ``transactions_performed`` filters on ``payme_transactions.perform_time`` while the
    receipts and grants are counted under the keys of intents whose ``settled_at`` falls in the
    window. Those are the SAME instant — one commit stamps both from one clock read — so the
    identity holds exactly, and if it ever stops holding, the fact that the two clocks are
    written together is what makes the difference a real defect rather than a boundary effect.

    See :class:`hbd.payme.ports.SettlementCounts` for the identity a caller may assert:
    ``transactions_performed == receipts_written`` always, while ``grants_written`` is the
    single-song subset because a plan sale grants no credit at purchase.
    """
    settled_keys = sa.select(PaymentIntentRow.idempotency_key).where(
        PaymentIntentRow.state == PaymentIntentState.PAID,
        PaymentIntentRow.settled_at >= frm,
        PaymentIntentRow.settled_at <= to,
    )
    performed = (
        sa.select(sa.func.count())
        .select_from(PaymeTransactionRow)
        .where(
            PaymeTransactionRow.state == PaymeState.PERFORMED,
            PaymeTransactionRow.perform_time >= frm,
            PaymeTransactionRow.perform_time <= to,
        )
        .scalar_subquery()
    )
    topups = (
        sa.select(sa.func.count())
        .select_from(TopupPurchaseRow)
        .where(TopupPurchaseRow.idempotency_key.in_(settled_keys))
        .scalar_subquery()
    )
    plans = (
        sa.select(sa.func.count())
        .select_from(PlanPurchaseRow)
        .where(PlanPurchaseRow.idempotency_key.in_(settled_keys))
        .scalar_subquery()
    )
    grants = (
        sa.select(sa.func.count())
        .select_from(CreditLedgerRow)
        .where(
            CreditLedgerRow.kind == CreditEntryKind.GRANT,
            CreditLedgerRow.idempotency_key.in_(settled_keys),
        )
        .scalar_subquery()
    )
    row = (await session.execute(sa.select(performed, topups + plans, grants))).one()
    return (int(row[0]), int(row[1]), int(row[2]))


# ---------------------------------------------------------------------------
# Writes
# ---------------------------------------------------------------------------
async def insert_intent(
    session: AsyncSession,
    *,
    intent_id: UUID,
    public_ref: str,
    idempotency_key: str,
    telegram_user_id: int,
    product: IntentProduct,
    amount_minor: int,
    currency: str,
    plan_songs: int | None,
    plan_days: int | None,
    provider: str,
    merchant_id: str,
    is_sandbox: bool,
    language: str,
    valid_until: datetime,
    now: datetime,
) -> bool:
    """Open one payment. ``True`` when THIS caller wrote it, ``False`` on a replayed key.

    Insert-or-ignore on ``idempotency_key`` — the same primitive, on the same kind of index,
    that ``insert_topup`` and ``insert_plan`` use. ``False`` is not a failure: it is "this
    customer already started this exact purchase", which is what a double tap looks like, and
    the caller answers it by reading the existing row back and returning the SAME
    ``public_ref``. A second reference would be a second live payment page for one purchase,
    and the customer would have no way to tell which of them took their money.

    ``public_ref`` is minted by the CALLER and passed in rather than generated here, because a
    losing insert must not leave a wasted reference behind in a variable the caller then
    returns. The caller reads the winner's row back and uses ITS reference, always.

    ``state`` is passed explicitly as ``pending`` rather than defaulted on the column: every
    state change on this row is a conditional ``UPDATE`` naming both the state it expects and
    the state it writes, and a Python-side default would be the one place a payment state was
    set by omission.
    """
    return await insert_or_ignore(
        session,
        PaymentIntentRow,
        {
            "id": intent_id,
            "public_ref": public_ref,
            "idempotency_key": idempotency_key,
            "telegram_user_id": telegram_user_id,
            "product": product,
            "amount_minor": amount_minor,
            "currency": currency,
            "plan_songs": plan_songs,
            "plan_days": plan_days,
            "provider": provider,
            "merchant_id": merchant_id,
            "is_sandbox": is_sandbox,
            "language": language,
            "state": PaymentIntentState.PENDING,
            "active_transaction_id": None,
            "valid_until": valid_until,
            "settled_at": None,
            "notified_at": None,
            "settle_note": None,
            "created_at": now,
            "updated_at": now,
        },
        index_elements=["idempotency_key"],
    )


async def insert_transaction(
    session: AsyncSession,
    *,
    transaction_id: UUID,
    payme_transaction_id: str,
    intent_id: UUID,
    payme_time: datetime,
    amount_minor: int,
    create_time: datetime,
    now: datetime,
) -> bool:
    """Record the rail's transaction. ``True`` when this caller wrote it.

    Insert-or-ignore on ``payme_transaction_id``, and **that unique index is the entire
    CreateTransaction-retry story**: the rail resends a create whenever our answer is lost, the
    sandbox asserts the second answer equals the first, and this index is what makes the second
    call find the first call's row instead of writing a second one against the same intent.

    ``create_time`` is passed separately from ``now`` even though the two are equal at the one
    call site that exists today. They are different facts — ``create_time`` is what we ANSWERED
    and must keep answering forever, ``now`` is when the row was written — and collapsing them
    would make the replay guarantee depend on a coincidence rather than on a column.
    """
    return await insert_or_ignore(
        session,
        PaymeTransactionRow,
        {
            "id": transaction_id,
            "payme_transaction_id": payme_transaction_id,
            "intent_id": intent_id,
            "payme_time": payme_time,
            "amount_minor": amount_minor,
            "state": PaymeState.CREATED,
            "cancel_reason": None,
            "create_time": create_time,
            "perform_time": None,
            "cancel_time": None,
            "created_at": now,
            "updated_at": now,
        },
        index_elements=["payme_transaction_id"],
    )


async def hold_intent(
    session: AsyncSession, *, intent_id: UUID, transaction_id: UUID, now: datetime
) -> bool:
    """Take the exclusive hold: ``pending -> awaiting``. ``False`` means somebody else has it.

    **The mutex of the whole integration.** ``WHERE id = :id AND state = 'pending'`` means two
    rail-side transactions racing for one intent cannot both win, and the loser is refused
    BEFORE its card is charged rather than after — which is the difference between a refusal
    the customer sees on a payment page and two charges an operator has to unpick.

    ``active_transaction_id`` is written in the same statement and never in a second one. A
    hold that named nobody would be a hold nobody could release: every conditional ``UPDATE``
    downstream matches on the holder, and ``ck_payment_intents_holder_present`` refuses the row
    outright, so the two columns move together or not at all.
    """
    result = await session.execute(
        sa.update(PaymentIntentRow)
        .where(
            PaymentIntentRow.id == intent_id,
            PaymentIntentRow.state == PaymentIntentState.PENDING,
        )
        .values(
            state=PaymentIntentState.AWAITING,
            active_transaction_id=transaction_id,
            updated_at=now,
        )
    )
    return rowcount_of(result) == 1


async def release_intent(
    session: AsyncSession, *, intent_id: UUID, transaction_id: UUID, now: datetime
) -> bool:
    """Give the hold back: ``awaiting -> pending``, for THIS holder only.

    Called when a transaction is cancelled or expires, and the reason the intent goes back to
    ``pending`` rather than to ``cancelled`` is the customer: a declined card should let them
    try another one within seconds, not sentence them to wait out a validity window they did
    not cause to lapse. ``cancelled`` is for the intent itself being given up, which is not
    what a failed charge means.

    Conditional on ``active_transaction_id = :tx`` as well as on the state, so a stale cancel
    for an old transaction cannot release a hold a NEWER transaction has since taken. Without
    that term this statement would be a way to steal an intent out from under a live charge.
    """
    result = await session.execute(
        sa.update(PaymentIntentRow)
        .where(
            PaymentIntentRow.id == intent_id,
            PaymentIntentRow.state == PaymentIntentState.AWAITING,
            PaymentIntentRow.active_transaction_id == transaction_id,
        )
        .values(
            state=PaymentIntentState.PENDING,
            active_transaction_id=None,
            updated_at=now,
        )
    )
    return rowcount_of(result) == 1


async def claim_intent(
    session: AsyncSession, *, intent_id: UUID, transaction_id: UUID, now: datetime, note: str
) -> bool:
    """The money landed: ``awaiting -> paid``, for THIS holder only. ``False`` means refuse.

    The second of the two conditional ``UPDATE``s that carry the settlement, and the one that
    makes exactly-once fulfilment a property of the database. ``rowcount == 0`` here means the
    intent is no longer held by this transaction — it was claimed by another one, released, or
    expired — and the ONLY correct response is to raise, which rolls back the transaction state
    flip made moments earlier in the same commit. A settlement that carried on past this point
    would write a receipt and a credit against an intent it does not hold.

    ``active_transaction_id`` is deliberately LEFT SET on a claim, unlike on a release. A paid
    intent's holder is the transaction that paid it, and blanking it would destroy the one
    link between a receipt and the rail-side charge that produced it — which is the first
    thing an operator needs when a customer disputes one.

    ``settled_at`` is stamped from the caller's ``now``, the same instant the receipt, the
    grant and the transaction's ``perform_time`` carry, which is what makes a windowed count of
    settlements and a windowed count of receipts unable to straddle a boundary differently.
    """
    result = await session.execute(
        sa.update(PaymentIntentRow)
        .where(
            PaymentIntentRow.id == intent_id,
            PaymentIntentRow.state == PaymentIntentState.AWAITING,
            PaymentIntentRow.active_transaction_id == transaction_id,
        )
        .values(
            state=PaymentIntentState.PAID,
            settled_at=now,
            settle_note=note,
            updated_at=now,
        )
    )
    return rowcount_of(result) == 1


async def claim_intent_for_operator(
    session: AsyncSession, *, intent_id: UUID, now: datetime, note: str
) -> bool:
    """An operator settles by hand: ``pending`` **or** ``awaiting`` ``-> paid``. No holder term.

    The recovery button behind ``hbd.payme.cli settle``, for the incident this rail cannot
    otherwise answer: the customer's card was charged, the cabinet shows the money, and our
    ``PerformTransaction`` never arrived or never committed.

    **It matches on two states and names no holder, and both departures are deliberate.** The
    intent may be ``awaiting`` (the rail created a transaction and then went quiet) or
    ``pending`` (the customer paid through a link whose create we never saw at all), and an
    operator has no transaction id of ours to match on — they are looking at Payme's cabinet.
    What makes that safe is not this statement but the KEY: the sale is written under the
    intent's own bot-minted ``idempotency_key``, so a late genuine ``PerformTransaction`` lands
    on the same unique indexes and grants nothing twice. The state terms still exclude ``paid``,
    ``cancelled`` and ``expired``, so this can never double-settle or resurrect a dead intent.

    ``note`` arrives already shaped as ``operator:<ref>``, so a manually settled row stays
    distinguishable from an automatic one for the life of the row — which is the first
    question of any reconciliation.
    """
    result = await session.execute(
        sa.update(PaymentIntentRow)
        .where(
            PaymentIntentRow.id == intent_id,
            PaymentIntentRow.state.in_([PaymentIntentState.PENDING, PaymentIntentState.AWAITING]),
        )
        .values(
            state=PaymentIntentState.PAID,
            settled_at=now,
            settle_note=note,
            updated_at=now,
        )
    )
    return rowcount_of(result) == 1


async def expire_intent(session: AsyncSession, *, intent_id: UUID, now: datetime) -> bool:
    """Close an unpaid window: ``pending -> expired``, and only when it has actually lapsed.

    The ``valid_until <= :now`` term is repeated here even though the caller selected on it a
    moment ago, and the repetition is the point: between the read and the write a rail-side
    transaction may have taken the hold, and re-evaluating both terms inside the ``UPDATE`` is
    what makes that race a no-op instead of an expiry racing a charge. The read is a
    convenience; this predicate is the decision.
    """
    result = await session.execute(
        sa.update(PaymentIntentRow)
        .where(
            PaymentIntentRow.id == intent_id,
            PaymentIntentRow.state == PaymentIntentState.PENDING,
            PaymentIntentRow.valid_until <= now,
        )
        .values(state=PaymentIntentState.EXPIRED, updated_at=now)
    )
    return rowcount_of(result) == 1


async def mark_performed(session: AsyncSession, *, transaction_id: UUID, now: datetime) -> bool:
    """Flip the charge: ``created -> performed``. **The first statement of the settlement.**

    ``False`` does NOT always mean refuse, and this is the one place in the module where the
    caller must do more than raise: the rail retries a ``PerformTransaction`` whose answer was
    lost, and two of its own retries can reach us concurrently. The loser of THAT race must
    re-read the row and, finding it ``performed``, return the replay — because the correct
    answer to "did this go through?" is yes, not ``-31008``. Every other cause of a zero
    rowcount is a real illegal transition. See :meth:`hbd.db.payme.SqlPaymeLedger.perform`.

    ``perform_time`` is stamped from the caller's ``now`` and then never rewritten, because a
    replayed perform must return THIS value. Nothing on this path may call a clock: the
    settlement reads one instant and every row it writes carries it.
    """
    result = await session.execute(
        sa.update(PaymeTransactionRow)
        .where(
            PaymeTransactionRow.id == transaction_id,
            PaymeTransactionRow.state == PaymeState.CREATED,
        )
        .values(state=PaymeState.PERFORMED, perform_time=now, updated_at=now)
    )
    return rowcount_of(result) == 1


async def mark_cancelled(
    session: AsyncSession,
    *,
    transaction_id: UUID,
    now: datetime,
    reason: int,
    from_state: PaymeState,
    to_state: PaymeState,
) -> bool:
    """Cancel a transaction, naming both ends of the transition explicitly.

    Both states are parameters because the protocol has two legal cancellations that must not
    be able to impersonate each other: ``created -> cancelled`` (wire ``-1``, no money moved)
    and ``performed -> cancelled_after_perform`` (wire ``-2``, money moved and something is
    being given back). A single function that inferred the target from the current state would
    be one refactor away from writing ``-1`` over a performed charge, which tells the rail
    nothing was taken from a customer whose card was debited.

    ``reason`` is Payme's own integer, stored verbatim rather than mapped through an enum of
    ours — argued at length on :class:`hbd.db.models.payme_transaction.PaymeTransactionRow`.
    The expiry path passes ``4`` (timeout), which is a value the rail defines and we echo.

    ``cancel_time`` is stamped once and never rewritten, because a replayed cancel must return
    THIS value as a SUCCESS rather than an error.
    """
    result = await session.execute(
        sa.update(PaymeTransactionRow)
        .where(
            PaymeTransactionRow.id == transaction_id,
            PaymeTransactionRow.state == from_state,
        )
        .values(state=to_state, cancel_reason=reason, cancel_time=now, updated_at=now)
    )
    return rowcount_of(result) == 1


async def mark_intent_notified(session: AsyncSession, *, intent_id: UUID, now: datetime) -> bool:
    """Stamp ``notified_at``, once. ``False`` when somebody had already stamped it.

    ``WHERE notified_at IS NULL`` rather than a bare ``UPDATE``: the post-commit enqueue and the
    sweep's backstop can both have a job in flight for the same intent, and the boolean is how
    the loser learns not to send a second "your payment went through" to a customer who has
    already read the first one.
    """
    result = await session.execute(
        sa.update(PaymentIntentRow)
        .where(PaymentIntentRow.id == intent_id, PaymentIntentRow.notified_at.is_(None))
        .values(notified_at=now, updated_at=now)
    )
    return rowcount_of(result) == 1


async def anonymise_intents(session: AsyncSession, *, telegram_user_id: int) -> int:
    """Strip the buyer off this account's intents, keeping every intent. Rows touched.

    The ``credit_ledger`` treatment and not the ``credit_accounts`` one, for a reason specific
    to this table: **a deleted intent would make ``GetStatement`` tell the rail that a
    transaction they can see in their own cabinet never existed.** That is a worse answer than
    an anonymous row, and it would be an answer we gave about somebody else's money. The
    identity comes off; ``public_ref``, the amount, the currency, the merchant, the settle note
    and all four clocks stay.

    ``idempotency_key`` is deliberately kept exactly as written, matching
    :func:`hbd.db.topup_sql.anonymise_topups` and :func:`hbd.db.plan_sql.anonymise_plans`. It is
    the replay marker: rewriting it would let a second purchase under the same key open a
    second intent for a customer who has asked to be forgotten — ``/forget`` as a way of
    clearing your own deduplication memory.

    **:func:`hbd.db.credit_erasure.forget_account` spells this statement out itself rather than
    calling this function**, and that duplication is deliberate on its side: erasure must keep
    working, and keep being asserted by test, on a deployment where ``HBD_CHECKOUT_PROVIDER``
    is ``stub`` and no rail code is reachable at all. The copy here is what the rail's own CLI
    and its own test suite use, and the two are asserted to agree by
    ``tests/test_db/test_payme_ledger.py`` reading the same columns
    ``tests/test_db/test_credit_erasure.py`` reads.
    """
    result = await session.execute(
        sa.update(PaymentIntentRow)
        .where(PaymentIntentRow.telegram_user_id == telegram_user_id)
        .values(telegram_user_id=None)
    )
    return rowcount_of(result)


async def insert_rpc_log(
    session: AsyncSession,
    *,
    at: datetime,
    method: str,
    payme_transaction_id: str | None,
    public_ref: str | None,
    reply_code: int,
    peer_ip: str | None,
    duration_ms: int,
) -> None:
    """Journal one inbound call. Never fails the request it is journalling.

    A plain ``INSERT``: there is no key to conflict on, because two identical retries from the
    rail are two genuinely different events and collapsing them would destroy the one record
    that answers "did they call us twice?".

    ``method`` is TRUNCATED here rather than validated, and that is the whole reason the column
    is a ``VARCHAR`` and not an ``enum_type``: an unknown method name is exactly the thing an
    incident needs recorded, and a closed enum would raise on the way in and lose the row.
    Truncation belongs at the writer because the writer is the only place that knows the value
    came off a hostile wire.

    No body, no header, no ``Authorization`` value and no Telegram id ever reaches this table —
    that absence is what keeps it out of ``tables_with_personal_data`` and off a retention
    clock, and it is asserted by ``tests/test_db/test_privacy_constraints.py``.
    """
    session.add(
        PaymeRpcLogRow(
            id=uuid4(),
            at=at,
            method=method[:RPC_METHOD_LENGTH],
            payme_transaction_id=payme_transaction_id,
            public_ref=public_ref,
            reply_code=reply_code,
            peer_ip=peer_ip,
            duration_ms=duration_ms,
        )
    )
