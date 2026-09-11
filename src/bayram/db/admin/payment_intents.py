"""``payment_intents`` — the rail's state machine, read by the people who have to explain it.

The sibling of :mod:`bayram.db.admin.payme_transactions` and
:mod:`bayram.db.admin.payme_rpc_log`: one module per TABLE, exactly as ``plan_purchases`` /
``topup_purchases`` / ``credits`` / ``orders`` are, and **the ROUTER is what joins two
sources — never the data layer**. That rule is why the dossier's receipt and its credit
grant are not fetched here but by :func:`bayram.db.admin.topup_purchases.receipt_for_key`,
:func:`bayram.db.admin.plan_purchases.receipt_for_key` and
:func:`bayram.db.admin.credits.ledger_for_key`, which live beside the tables they read.

Everything :mod:`bayram.db.admin.plan_purchases` states holds here without repetition: every
number is computed by the database, nothing commits, no clock is read (an injected ``now`` is
a parameter), the session is first and positional and everything else is keyword-only, no
``*Row`` escapes (Rule 15), and every docstring ends with the index it rides.

**THE PANEL EXISTS BECAUSE THERE IS NO SINGLE JOINING QUERY.** ``bayram.payme.cli._dossier``
assembles six statements inside ONE read transaction, and the single-transaction part is the
design: an operator has to trust that the receipt and the transaction were true at the same
instant, and six separate reads during a live settlement would show a performed transaction
with no receipt. This module keeps that property by leaving the joining to a handler that
runs inside the request's own transaction, and by never fanning a 1:N relation into a money
column — see :func:`list_intents`.

**NOTHING HERE SUMS ``amount_minor`` ACROSS INTENTS.** ``routers/dashboard.py::finance``
already concatenates ``plan_revenue_totals`` and ``topup_revenue_totals`` into the one revenue
rollup this panel has. A second, differently-computed money figure on a payments screen — for
instance one that excluded sandbox intents by joining receipts back to ``is_sandbox`` — would
be a revenue-shaped number free to disagree with it, and the first person to notice the two
screens differ will file the difference as a bug. So sandbox contamination is made VISIBLE
per row and on the header (:func:`latest_checkout_seen`) instead of being subtracted from a
total nobody can reconcile.

**PRIVACY, and it is the whole reason two obvious fields are missing.**
``payment_intents.telegram_user_id`` is nullable for exactly one reason: ``/forget`` nulls it.
Money columns survive erasure; the buyer does not. So every read here renders an erased buyer
as a STATE — the raw ``None`` on the view model, classified at the response boundary — and
never crashes, never implies fraud, and never counts distinct buyers without publishing the
anonymised count beside it (``plan_purchases`` calls that "the single most regressible number
in this module"; the answer taken here is simpler — this module publishes no distinct-buyer
count at all).

``idempotency_key`` is NEVER a parameter and never a returned field. It is shaped
``topup:{telegram_user_id}:{scope}:{seq}`` (``bot/handlers/checkout.py``) and so contains the
customer's Telegram id — which is precisely the leak ``public_ref`` exists to prevent. It
stays a server-side join key: :func:`resolve_intent_reference` accepts ``public_ref`` and a
rail transaction id and nothing else, so it can never be searched from a URL.

**CAPABILITIES ARE MEASURED, WITH ROW PROBES, AND NOT WITH ``has_table``.** This migration
ships WITH the panel, so "the table exists" is true on day one and is not the question anybody
is asking. See :func:`has_opened_any_intent`. And do **not** repoint
``bayram.db.admin.sql.PAYMENTS_TABLE`` (``'payments'``, a table that does not exist and never
will) at these tables to light a capability up: it drives ``ReadCapabilities.is_payment_ledger``,
``TimelineSource.PAYMENTS`` reporting "not enabled here" in ``orders.py``, and the
``OrderPaymentRail`` reasoning in ``views.py`` — flipping it would silently change what an
order timeline claims about a customer's payment history.

**INDEXES.** The lists and the funnel ride ``ix_payment_intents_created_at``; the lookup rides
the unique ``ix_payment_intents_public_ref``; the settlement counts ride
``ix_payment_intents_settled_at``, which revision **0025** adds precisely because this surface
polls a number the five-minute sweep used to compute alone.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum
from typing import Any
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql import ColumnElement, Select

from bayram.db.admin.page import (
    BoundedTotal,
    Cursor,
    Page,
    PageRequest,
    bounded_total,
    build_page,
    keyset_order,
    keyset_predicate,
)
from bayram.db.admin.sql import TimeWindow, apply_in, apply_window
from bayram.db.admin.views import (
    AttentionCounts,
    CheckoutSeen,
    IntentDetail,
    IntentFunnel,
    IntentListItem,
    IntentReferenceMatch,
    IntentStateCount,
    SettlementSnapshot,
)
from bayram.db.enums import CreditEntryKind, IntentProduct, PaymentIntentState, PaymeState
from bayram.db.models.credit_ledger import CreditLedgerRow
from bayram.db.models.payme_transaction import PaymeTransactionRow
from bayram.db.models.payment_intent import PaymentIntentRow
from bayram.db.models.plan_purchase import PlanPurchaseRow
from bayram.db.models.topup_purchase import TopupPurchaseRow
from bayram.db.payme_sql import settlement_counts
from bayram.payme.ports import OPERATOR_SETTLE_PREFIX

__all__ = [
    "SettleSource",
    "AttentionPopulation",
    "IntentFilters",
    "MATCHED_ON_PUBLIC_REF",
    "MATCHED_ON_TRANSACTION_ID",
    "latest_checkout_seen",
    "has_opened_any_intent",
    "has_settled_any_intent",
    "intent_funnel",
    "settlement_snapshot",
    "attention_counts",
    "list_intents",
    "count_intents",
    "intent_by_id",
    "idempotency_key_for",
    "resolve_intent_reference",
]

#: What :attr:`IntentReferenceMatch.matched_on` says. Constants rather than literals at three
#: call sites, because the wire renders them and a typo would be a filter that silently never
#: matches rather than an error anybody sees.
MATCHED_ON_PUBLIC_REF = "public_ref"
MATCHED_ON_TRANSACTION_ID = "payme_transaction_id"


class SettleSource(StrEnum):
    """Who moved the money: the rail, or one of us.

    Not stored as a column — ``payment_intents.settle_note`` holds ``'payme'`` or
    ``'operator:<ref>'`` and this is the classification of that string. It is an enum rather
    than a boolean because "was this settled by hand?" is the first question of every
    reconciliation and a ``bool`` named ``is_manual`` would answer it in a direction somebody
    eventually inverts.
    """

    RAIL = "rail"
    OPERATOR = "operator"


class AttentionPopulation(StrEnum):
    """The three populations :class:`~bayram.db.admin.views.AttentionCounts` counts.

    A filter member per count, and that pairing is enforced structurally: the predicate behind
    each member is a module-private helper that :func:`attention_counts` and
    :func:`list_intents` BOTH call. A chip that said "4 stuck" and a list that showed three of
    them is the defect the sharing prevents, and it is the failure a naive implementation
    reaches by spelling the predicate twice.
    """

    AWAITING_STALE = "awaiting_stale"
    PAID_UNNOTIFIED = "paid_unnotified"
    PAID_NO_RECEIPT = "paid_no_receipt"


@dataclass(frozen=True, slots=True)
class IntentFilters:
    """Everything ``GET /api/billing/intents`` may narrow by. Empty tuples mean NO filter.

    That asymmetry is :func:`~bayram.db.admin.sql.apply_in`'s and is deliberate here for the
    same reason: ``IN ()`` is the query that quietly returns an empty page when a caller passed
    no values, and a payments list that renders empty because nobody ticked a box is a screen
    an operator concludes the rail is broken from.

    ``now`` and ``stale_after`` are required only by :attr:`attention` ==
    ``AWAITING_STALE`` — that population is defined against a clock, and this layer reads no
    clock. The check is re-stated in :func:`_attention_clause` rather than trusted from the
    HTTP boundary: the duplication is the standing rule of this package (the db check is the
    backstop for callers that did not arrive over HTTP), and here it is the difference between
    a 422 and a ``TypeError`` inside a money query.
    """

    states: tuple[PaymentIntentState, ...] = ()
    products: tuple[IntentProduct, ...] = ()
    settled_by: SettleSource | None = None
    attention: AttentionPopulation | None = None
    #: ``None`` means "both"; ``False`` means production only. Three states, because "hide the
    #: rehearsals" and "show me only the rehearsals" are both real questions during
    #: certification week.
    is_sandbox: bool | None = None
    #: On ``created_at``: when the payment was STARTED. Deliberately not on ``settled_at`` —
    #: an operator narrowing "today" means today's checkouts, and windowing on settlement
    #: would silently drop every payment that has not finished, which is the population the
    #: screen exists for.
    window: TimeWindow | None = None
    now: datetime | None = None
    stale_after: timedelta | None = None


async def latest_checkout_seen(session: AsyncSession) -> CheckoutSeen | None:
    """The provider, cashbox and sandbox flag of the NEWEST intent. The whole rail header.

    **This is a measurement standing in for three switches the admin process cannot read.**
    ``Settings.checkout_provider`` decides whether the bot builds real links and is loaded from
    the BOT's env file; ``PaymeSettings.payme_enabled`` decides only whether the gateway daemon
    answers and lives in ``/etc/bayram/payme.env``; neither is in this process's settings
    object. Adding a ``checkout_provider`` field to ``AdminSettings`` was the obvious
    alternative and is the trap it looks like it is not: it would read ``.env.admin``, a
    DIFFERENT file, and render ``stub`` with total confidence while the bot sold through Payme.

    So the panel reports what was actually written by the process that actually writes it, with
    ``seen_at`` beside it so a stale reading is visibly stale. ``None`` means no checkout has
    ever been opened here — a different sentence from "the rail is off", and one the caller
    renders as its own screen rather than as an error.

    One row, ordered by ``created_at`` and not by ``updated_at``: the question is which
    CONFIGURATION was most recently used to issue a link, and an old intent moving to
    ``expired`` this morning does not make its cashbox the current one.

    INDEX: ``ix_payment_intents_created_at``.
    """
    row = (
        await session.execute(
            sa.select(
                PaymentIntentRow.provider,
                PaymentIntentRow.merchant_id,
                PaymentIntentRow.is_sandbox,
                PaymentIntentRow.created_at,
            )
            .order_by(PaymentIntentRow.created_at.desc(), PaymentIntentRow.id.desc())
            .limit(1)
        )
    ).one_or_none()
    if row is None:
        return None
    return CheckoutSeen(
        provider=str(row.provider),
        merchant_id=str(row.merchant_id),
        is_sandbox=bool(row.is_sandbox),
        seen_at=row.created_at,
    )


async def has_opened_any_intent(session: AsyncSession) -> bool:
    """True once any checkout has been opened here. Window-blind, on purpose.

    **A ROW probe and never a** :func:`~bayram.db.admin.sql.has_table` **probe.** The migration
    that creates ``payment_intents`` ships WITH this panel, so a table probe would report every
    deployment as payment-instrumented the day the panel lands — which is exactly the question
    nobody is asking. The question is whether this rail has ever been switched on, and only a
    row can answer it. Same idiom as
    :func:`~bayram.db.admin.topup_purchases.has_recorded_topup_revenue`.

    Ignoring the window is the point: ``count: 0`` alone cannot separate "nothing in the range
    you chose" from "this has never run here", and those are two screens with two remedies.

    Do NOT repoint ``bayram.db.admin.sql.PAYMENTS_TABLE`` at this table to serve the same
    purpose. That constant names ``'payments'``, a table that does not exist and never will,
    and it drives ``ReadCapabilities.is_payment_ledger``, ``TimelineSource.PAYMENTS`` reporting
    "not enabled here" and the ``OrderPaymentRail`` reasoning — flipping it would silently
    change what an order timeline claims.
    """
    probe = await session.scalar(sa.select(sa.literal(1)).select_from(PaymentIntentRow).limit(1))
    return probe is not None


async def has_settled_any_intent(session: AsyncSession) -> bool:
    """True once any payment has been settled here. Window-blind, for the same reason.

    The capability that keeps the settlement card honest. All four numbers of
    :class:`~bayram.db.admin.views.SettlementSnapshot` at zero is either "nothing settled in
    your range" or "this rail has never settled anything", and a zero-equals-zero green tick on
    a rail that has never taken a payment is the worst lie that card can tell — so the verdict
    is computed against this flag rather than against the arithmetic alone.

    INDEX: none needed. ``state`` is not indexed on its own, but the ``LIMIT 1`` stops at the
    first paid row and this deployment's whole table fits in a page for months. It is worth
    revisiting only if a deployment accumulates millions of unpaid intents and no paid ones,
    at which point the composite ``ix_payment_intents_state_valid_until`` becomes the fix.
    """
    probe = await session.scalar(
        sa.select(sa.literal(1))
        .select_from(PaymentIntentRow)
        .where(PaymentIntentRow.state == PaymentIntentState.PAID)
        .limit(1)
    )
    return probe is not None


async def intent_funnel(session: AsyncSession, *, window: TimeWindow | None = None) -> IntentFunnel:
    """Where the window's payments got to, and WHY the expired ones expired.

    Two statements. The first groups by ``state``; the second counts the expiry split, which
    cannot ride the same ``GROUP BY`` because it is a partition of ONE of that grouping's
    buckets and folding it in would produce rows that do not sum to the total.

    **A state with no rows is ABSENT rather than present at zero.** The standing rule, and
    sharper on money than on orders: a zero bar is a claim about payments nobody attempted, on
    a day this rail may not have been switched on at all.

    **The expiry split needs no column and no backfill.** An expired intent that was held by at
    least one rail-side transaction reached the payment form; one with none never got there.
    That is a correlated ``EXISTS`` at read time — the shape ``payme.cli._funnel`` already uses
    — and the rejected alternative was a stored ``reached_form`` boolean, which would be a
    column that is wrong for every row written before it and right only by a migration nobody
    can write, since the evidence is exactly the ``EXISTS`` this computes.

    INDEX: ``ix_payment_intents_created_at`` for the window; the ``EXISTS`` probes
    ``ix_payme_transactions_intent_id`` once per expired row, so its work is bounded by the
    expired population and not by the table.
    """
    # Labelled ``total`` and not ``count``: a SQLAlchemy ``Row`` is a named tuple, so a column
    # labelled ``count`` shadows ``tuple.count`` and ``row.count`` silently hands back the bound
    # METHOD rather than the number. It type-checks nowhere and would have read as a database
    # bug at runtime.
    grouped: Select[Any] = sa.select(
        PaymentIntentRow.state, sa.func.count().label("total")
    ).select_from(PaymentIntentRow)
    grouped = apply_window(grouped, PaymentIntentRow.created_at, window)
    rows = (
        await session.execute(
            grouped.group_by(PaymentIntentRow.state).order_by(PaymentIntentRow.state)
        )
    ).all()

    split: Select[Any] = sa.select(
        sa.func.count(sa.case((_HELD_BY_A_TRANSACTION, 1), else_=None)).label("after"),
        sa.func.count(sa.case((~_HELD_BY_A_TRANSACTION, 1), else_=None)).label("without"),
    ).where(PaymentIntentRow.state == PaymentIntentState.EXPIRED)
    split = apply_window(split, PaymentIntentRow.created_at, window)
    expiry = (await session.execute(split)).one()

    return IntentFunnel(
        states=tuple(IntentStateCount(state=str(row.state), count=int(row.total)) for row in rows),
        expired_after_transaction=int(expiry.after),
        expired_with_no_transaction=int(expiry.without),
    )


async def settlement_snapshot(
    session: AsyncSession, *, since: datetime, until: datetime
) -> SettlementSnapshot:
    """The reconciliation identity's four numbers over one window.

    **The first three come from** :func:`bayram.db.payme_sql.settlement_counts` **unchanged.**
    Re-deriving them here was the alternative and is precisely how the panel and the
    five-minute sweep come to report different numbers about the same minute: that function
    takes all three in ONE statement with three scalar subqueries, deliberately, because read
    separately a settlement landing between the first and the third reports a race as a defect.
    A second copy would eventually differ by a boundary, and the difference would be blamed on
    the money rather than on the query.

    **The fourth is the one without which the other three lie.** A force-settled intent has no
    performed transaction at all, so the honest identity is ``transactions_performed +
    operator_settlements == receipts_written`` — not the two-way equality that holds on the
    rail-only path. Publishing the three raw numbers alone makes every use of the recovery
    button look like a defect, which is how a monitoring alert gets muted. It is counted by
    ``settle_note LIKE 'operator:%'`` using
    :data:`~bayram.payme.ports.OPERATOR_SETTLE_PREFIX`, imported rather than respelled: the
    prefix is written by ``db/payme.py`` and read by the CLI's invariant and by this — three
    spellings and the identity starts reporting incidents that are not incidents.

    ``grants_written`` is the SINGLE-SONG SUBSET; ``grants <= receipts`` is expected because a
    plan sale writes a receipt and no credit at purchase. Only ``grants > receipts`` is
    strictly impossible.

    **THE ONE CASE THIS COUNT DELIBERATELY OVER-STATES, AND WHY IT IS NOT SUBTRACTED.** An
    intent settled by hand whose rail transaction then arrives is counted in BOTH left-hand
    terms against ONE receipt: ``_already_settled_by_this_transaction_or_refuse`` answers that
    late ``PerformTransaction`` with state 2, which marks the transaction ``performed`` while
    ``settle_note`` and ``settled_at`` keep the operator's values and ``_write_sale`` writes
    nothing new (insert-or-ignore on the same key). So a correct recovery reads as
    ``receipts_short`` for that window, which is why the console names it as the SECOND
    legitimate cause beside the erased buyer rather than leading with suspicion.

    The obvious correction — excluding operator settlements that have a ``performed``
    transaction — is NOT made, and the reason is that it trades this false reading for a worse
    one. Our clock and the rail's are not the same clock, so the settle and the perform often
    fall in DIFFERENT windows; the exclusion would then take the operator term out of the
    window that holds the receipt and turn a balanced range into ``receipts_over``, which is
    the same false alarm moved somewhere harder to explain. A windowed identity cannot net two
    events that straddle its boundary, and pretending otherwise would hide the population this
    card exists to surface: a performed transaction with no receipt is also what an erased
    buyer looks like.

    **Bare instants and not a** :class:`~bayram.db.admin.sql.TimeWindow`, because
    ``settlement_counts`` requires BOTH bounds and its window is inclusive at both ends rather
    than half-open. Passing a ``TimeWindow`` would mean either quietly converting a half-open
    range into a closed one — which double-counts the settlement landing exactly on a boundary
    across two adjacent reads — or fabricating a lower bound for a caller who named none. The
    route refuses a missing ``?from=`` instead; "all time" is a different and, on this column,
    a much more expensive question.

    INDEX: ``ix_payment_intents_settled_at`` and ``ix_payme_transactions_perform_time``, both
    added by revision 0025 for exactly this pair of reads.
    """
    performed, receipts, grants = await settlement_counts(session, frm=since, to=until)
    by_operator = await session.scalar(
        sa.select(sa.func.count())
        .select_from(PaymentIntentRow)
        .where(
            PaymentIntentRow.state == PaymentIntentState.PAID,
            PaymentIntentRow.settled_at >= since,
            PaymentIntentRow.settled_at <= until,
            PaymentIntentRow.settle_note.startswith(OPERATOR_SETTLE_PREFIX),
        )
    )
    return SettlementSnapshot(
        transactions_performed=performed,
        receipts_written=receipts,
        grants_written=grants,
        operator_settlements=int(by_operator or 0),
    )


async def attention_counts(
    session: AsyncSession, *, now: datetime, stale_after: timedelta
) -> AttentionCounts:
    """The three populations an operator can act on, in ONE statement.

    One statement and not three, for :func:`~bayram.db.payme_sql.settlement_counts`' own
    reason: a settlement landing between the first read and the third would show a payment as
    both "never announced" and already handled, and an operator would be chasing a race.

    Each count is the SAME predicate the corresponding :class:`AttentionPopulation` filter
    applies in :func:`list_intents` — the helpers below are called from both — so a chip
    reading "4 stuck" and a list showing three of them is a defect that cannot be written here.

    INDEX: ``ix_payment_intents_state_valid_until`` leads with ``state`` for the two paid
    populations; the awaiting probe rides the transactions' primary key through
    ``active_transaction_id``, and the receipt probes ride the two unique
    ``idempotency_key`` indexes, index-only, once per candidate row.
    """
    statement: Select[Any] = sa.select(
        sa.select(sa.func.count())
        .select_from(PaymentIntentRow)
        .where(_awaiting_past_timeout(now=now, stale_after=stale_after))
        .scalar_subquery()
        .label("awaiting_held_past_timeout"),
        sa.select(sa.func.count())
        .select_from(PaymentIntentRow)
        .where(_paid_never_announced())
        .scalar_subquery()
        .label("paid_never_announced"),
        sa.select(sa.func.count())
        .select_from(PaymentIntentRow)
        .where(_paid_with_no_receipt())
        .scalar_subquery()
        .label("paid_with_no_receipt"),
    )
    row = (await session.execute(statement)).one()
    return AttentionCounts(
        awaiting_held_past_timeout=int(row.awaiting_held_past_timeout),
        paid_never_announced=int(row.paid_never_announced),
        paid_with_no_receipt=int(row.paid_with_no_receipt),
    )


async def list_intents(
    session: AsyncSession, *, filters: IntentFilters, request: PageRequest
) -> Page[IntentListItem]:
    """One keyset page of started payments, newest first, with the whole chain per row.

    **The chain columns are CORRELATED SUBQUERIES and emphatically not a ``LEFT JOIN``.** An
    intent accumulates one ``payme_transactions`` row per attempt — a declined card is
    cancelled and the customer tries again — so the relation is 1:N and a join fans EVERY
    column of the intent out once per transaction. A page would then show one payment three
    times, and any caller who summed ``amount_minor`` over the result would triple the sale.
    Correlated scalars keep the outer row count exactly the intent count, which is the shape
    ``payme_sql.settlement_counts`` and ``topup_purchases.count_unpriced_topups`` already use.

    ``has_receipt`` is an ``EXISTS`` over EACH receipts table on the shared
    ``idempotency_key`` rather than a ``UNION``: the two are 1:0..1 each and both keys are
    unique, so two index-only probes are cheaper than materialising a union per row.

    ``has_grant`` false is NORMAL for a plan sale — a plan mints songs as they are used and
    grants no credit at purchase — and treating it as a fault is the regression this column's
    test exists to catch.

    Keyset on ``(created_at, id)`` descending, with the predicate spelled longhand by
    :func:`~bayram.db.admin.page.keyset_predicate`. No sort parameter exists anywhere on this
    API; every list is fixed at newest-first, which is also what makes the cursor a single
    short token.

    INDEX: ``ix_payment_intents_created_at`` for the order and the window.
    """
    statement = _filtered(filters)
    resume = keyset_predicate(PaymentIntentRow.created_at, PaymentIntentRow.id, request.cursor)
    if resume is not None:
        statement = statement.where(resume)
    statement = statement.order_by(
        *keyset_order(PaymentIntentRow.created_at, PaymentIntentRow.id)
    ).limit(request.fetch_limit)
    rows = (await session.execute(statement)).all()
    return build_page([_list_item(row) for row in rows], request, _cursor_of)


async def count_intents(session: AsyncSession, *, filters: IntentFilters) -> BoundedTotal:
    """``?withTotal=true`` for the intents list. Bounded at :data:`TOTAL_COUNT_CAP`.

    **``bounded_total`` here, unlike in ``plan_purchases``.** That module refuses the cap
    because a REVENUE figure that saturated at 10 000 would misreport a real book. This is not
    a revenue figure: it is the optional row count of a paged operator list, ``page_meta``
    takes a :class:`~bayram.db.admin.page.BoundedTotal`, and ``PageMeta.isTotalExact`` exists
    precisely so a saturated count renders as "10,000+". Refusing it would mean inventing a
    parallel ``page_meta`` for one list.
    """
    return await bounded_total(session, _filtered(filters))


async def intent_by_id(session: AsyncSession, *, intent_id: UUID) -> IntentDetail | None:
    """One intent, the dossier's head. ``None`` when there is no such row.

    ``None`` rather than an exception, because this layer does not know what a caller wants a
    missing row to mean — the router turns it into a ``ProblemError`` with the message an
    operator should read. Rule 15: a frozen view, never the mapped row, which would carry a
    live session into the response layer.

    Selected with ``sa.select`` and not ``session.get``: this runs inside a request transaction
    that may already have issued Core statements, and ``get`` would hand back the identity
    map's copy — the same reason ``payme.py::_settle`` reads the intent it is about to claim
    with an explicit select.

    INDEX: the primary key.
    """
    row = (
        await session.execute(_projection().where(PaymentIntentRow.id == intent_id))
    ).one_or_none()
    if row is None:
        return None
    item = _list_item(row)
    return IntentDetail(
        intent_id=item.intent_id,
        public_ref=item.public_ref,
        created_at=item.created_at,
        valid_until=item.valid_until,
        state=item.state,
        product=item.product,
        plan_songs=item.plan_songs,
        plan_days=item.plan_days,
        amount_minor=item.amount_minor,
        currency=item.currency,
        provider=item.provider,
        merchant_id=item.merchant_id,
        is_sandbox=item.is_sandbox,
        telegram_user_id=item.telegram_user_id,
        transaction_count=item.transaction_count,
        latest_transaction_state=item.latest_transaction_state,
        latest_perform_time=item.latest_perform_time,
        has_receipt=item.has_receipt,
        has_grant=item.has_grant,
        settled_at=item.settled_at,
        settle_note=item.settle_note,
        notified_at=item.notified_at,
    )


async def idempotency_key_for(session: AsyncSession, *, intent_id: UUID) -> str | None:
    """The join key for ONE intent, handed to the handler and to nothing else.

    This exists because two rules in this module are both right and, without it, contradict each
    other. The module docstring says **the ROUTER is what joins two sources — never the data
    layer**, which is why the dossier's receipt and grant are fetched by
    :func:`bayram.db.admin.topup_purchases.receipt_for_key`,
    :func:`bayram.db.admin.plan_purchases.receipt_for_key` and
    :func:`bayram.db.admin.credits.ledger_for_key`. All three take an ``idempotency_key``. The
    same docstring then says the key is never a returned field — so the handler charged with
    joining had no way to obtain the thing it must join ON, and the dossier was unimplementable.

    **A function and not a field on** :class:`~bayram.db.admin.views.IntentDetail`, and the
    difference is the whole point.
    ``tests/test_db/test_admin_payment_intents.py::test_no_view_model_carries_the_idempotency_key``
    asserts over ``__slots__`` AND over ``str(view)``, because the key is shaped
    ``topup:{telegram_user_id}:{scope}:{seq}`` and therefore carries the customer's Telegram id.
    A view is rendered — into a log line, into an error context, into a repr somebody pastes into
    a ticket — and a field on one leaks by accident rather than by decision. A bare ``str``
    returned to one caller is read, passed to three queries, and goes out of scope. The privacy
    property that matters is the one ``public_ref`` was invented for: the key is never a
    parameter, never searchable from a URL, and never on the wire —
    :mod:`bayram.admin.schemas.billing` carries no ``idempotencyKey`` on any model and has a test
    that introspects ``model_fields`` to keep it so.

    ``None`` when there is no such intent, matching :func:`intent_by_id` rather than raising, so
    a handler that already resolved the head does not need a second error branch.

    INDEX: the primary key.
    """
    return (
        await session.execute(
            sa.select(PaymentIntentRow.idempotency_key).where(PaymentIntentRow.id == intent_id)
        )
    ).scalar_one_or_none()


async def resolve_intent_reference(
    session: AsyncSession,
    *,
    public_ref: str | None = None,
    payme_transaction_id: str | None = None,
) -> IntentReferenceMatch | None:
    """Turn a reference an operator was read over the phone into an intent id.

    Exactly one argument, re-checked here rather than trusted from the HTTP boundary — the
    standing duplication of this package, and here it stops a caller that passed both from
    silently getting whichever branch happens to be first.

    **There is deliberately no ``idempotency_key`` parameter.** That string embeds the
    customer's Telegram id, so making it searchable would put a Telegram id in a URL, in a
    browser history and in an access log — the exact leak ``public_ref`` was added to prevent.
    The two identifiers accepted here are the two that are not people.

    ``None`` is a real answer and not an error: "no payment exists under that reference on this
    deployment" is a different screen from "that is not a reference", and the caller renders
    both. The caller is what refuses a malformed reference, with a 422 naming the parameter.

    INDEX: the unique ``ix_payment_intents_public_ref``, or the unique
    ``ix_payme_transactions_payme_transaction_id`` followed by the intents' primary key.
    """
    if (public_ref is None) == (payme_transaction_id is None):
        raise ValueError("resolve_intent_reference takes exactly one reference")
    if public_ref is not None:
        found = await session.scalar(
            sa.select(PaymentIntentRow.id).where(PaymentIntentRow.public_ref == public_ref)
        )
        if found is None:
            return None
        return IntentReferenceMatch(intent_id=found, matched_on=MATCHED_ON_PUBLIC_REF)
    found = await session.scalar(
        sa.select(PaymeTransactionRow.intent_id).where(
            PaymeTransactionRow.payme_transaction_id == payme_transaction_id
        )
    )
    if found is None:
        return None
    # The transaction exists; whether its intent still does is a separate question, and the
    # honest answer is "this id belongs to intent X" either way. ``payme_transactions`` is on
    # NO retention bound while terminal unpaid intents are deleted at 400 days and there are no
    # foreign keys, so after thirteen months a transaction can legitimately name a row that has
    # been purged. The caller's 404 on the dossier is what renders that, as PURGED rather than
    # as never-happened; inventing the distinction here would need a second round trip to learn
    # something the next query learns anyway.
    return IntentReferenceMatch(intent_id=found, matched_on=MATCHED_ON_TRANSACTION_ID)


# ---------------------------------------------------------------------------
# internals — the predicates the counts and the list SHARE
#
# Every one of the three attention populations is spelled exactly once and called from both
# ``attention_counts`` and ``list_intents``. That is the whole mechanism behind "the chip and
# the list it links to cannot compute the population two different ways", and it is the reason
# these are functions returning ``ColumnElement[bool]`` rather than clauses inlined at two
# call sites where a future edit reaches only one.
# ---------------------------------------------------------------------------
#: An expired intent that at least one rail-side transaction was opened against: the customer
#: reached the payment form. Correlated, so it is evaluated per candidate row.
_HELD_BY_A_TRANSACTION: ColumnElement[bool] = (
    sa.select(sa.literal(1))
    .select_from(PaymeTransactionRow)
    .where(PaymeTransactionRow.intent_id == PaymentIntentRow.id)
    .correlate(PaymentIntentRow)
    .exists()
)


def _awaiting_past_timeout(*, now: datetime, stale_after: timedelta) -> ColumnElement[bool]:
    """``awaiting`` whose holding transaction has sat in ``created`` past the rail's timeout.

    **The boundary is EXCLUSIVE**, matching :func:`bayram.payme.rules.is_expired`, which
    compares with a strict ``>`` because Payme's own reference implementations do. At exactly
    the timeout the window is still open, and the two readings differ in DIRECTION: an
    inclusive boundary would list a payment as stuck at the instant the rail would still
    perform it, and an operator who acted on that would be intervening in a live charge.

    The transaction is reached through ``active_transaction_id`` and not through
    ``intent_id``, because the question is about THE HOLDER — the transaction the mutex names
    — and an intent may carry older, already-cancelled transactions that say nothing about
    whether the current attempt is stuck.
    """
    holder = (
        sa.select(sa.literal(1))
        .select_from(PaymeTransactionRow)
        .where(
            PaymeTransactionRow.id == PaymentIntentRow.active_transaction_id,
            PaymeTransactionRow.state == PaymeState.CREATED,
            PaymeTransactionRow.payme_time < now - stale_after,
        )
        .correlate(PaymentIntentRow)
        .exists()
    )
    return sa.and_(PaymentIntentRow.state == PaymentIntentState.AWAITING, holder)


def _paid_never_announced() -> ColumnElement[bool]:
    """Paid, and nobody has told the customer. **Erased buyers excluded.**

    ``telegram_user_id IS NOT NULL`` mirrors
    :func:`bayram.db.payme_sql.unnotified_settled_intents` exactly, and the exclusion is
    load-bearing rather than tidy: an erased buyer has nobody to tell, so ``notified_at`` will
    never be stamped, and including them would produce a backlog that never drains — a count
    an operator learns to ignore, on the one screen where every other count is actionable.

    This is deliberately a SECOND reader of that population rather than a widening of the
    :class:`bayram.payme.ports.PaymeLedger` protocol. That protocol is held by an
    internet-facing process; putting a diagnostic cross-table read on it would leave it one
    authentication bug away from a stranger. Two readers of one predicate is the cheaper risk,
    and this docstring is the pin that keeps them in step.
    """
    return sa.and_(
        PaymentIntentRow.state == PaymentIntentState.PAID,
        PaymentIntentRow.notified_at.is_(None),
        PaymentIntentRow.telegram_user_id.is_not(None),
    )


def _paid_with_no_receipt() -> ColumnElement[bool]:
    """Paid, with no sale written under the key. **Not a defect list.**

    This population is dominated by ERASED BUYERS. ``db/payme.py::_settle`` claims the intent
    and writes NO sale when ``telegram_user_id IS NULL``: ``/forget`` ran between the payment
    starting and settling, the money moved, there is nobody left to grant a credit to, and
    refusing would leave the rail retrying a charge it has already taken. It logs at ERROR and
    surfaces here as a settled intent with no receipt, which is also exactly what trips the
    settlement identity — so this count and
    :class:`~bayram.db.admin.views.SettlementSnapshot` are read together or neither is
    readable.

    A caller must render these as "buyer erased" with the money columns intact, never as a
    discrepancy to repair and never as fraud.

    Two ``NOT EXISTS`` and not a subtraction of counts: the join is exact under any partial
    write, and each probe is index-only against a unique ``idempotency_key``.
    """
    topup = (
        sa.select(sa.literal(1))
        .select_from(TopupPurchaseRow)
        .where(TopupPurchaseRow.idempotency_key == PaymentIntentRow.idempotency_key)
        .correlate(PaymentIntentRow)
        .exists()
    )
    plan = (
        sa.select(sa.literal(1))
        .select_from(PlanPurchaseRow)
        .where(PlanPurchaseRow.idempotency_key == PaymentIntentRow.idempotency_key)
        .correlate(PaymentIntentRow)
        .exists()
    )
    return sa.and_(PaymentIntentRow.state == PaymentIntentState.PAID, ~topup, ~plan)


def _attention_clause(filters: IntentFilters) -> ColumnElement[bool] | None:
    """The predicate for ``filters.attention``, or ``None`` when no population was named."""
    if filters.attention is None:
        return None
    if filters.attention is AttentionPopulation.AWAITING_STALE:
        if filters.now is None or filters.stale_after is None:
            # The backstop, deliberately duplicating the router's own 422. A caller that did
            # not arrive over HTTP would otherwise get a ``TypeError`` from inside a money
            # query, whose traceback names arithmetic rather than the missing parameter.
            raise ValueError("the awaiting_stale population needs both now and stale_after")
        return _awaiting_past_timeout(now=filters.now, stale_after=filters.stale_after)
    if filters.attention is AttentionPopulation.PAID_UNNOTIFIED:
        return _paid_never_announced()
    return _paid_with_no_receipt()


def _projection() -> Select[Any]:
    """The intent's own columns plus the four correlated chain answers. One row per intent."""
    receipt = sa.or_(
        sa.select(sa.literal(1))
        .select_from(TopupPurchaseRow)
        .where(TopupPurchaseRow.idempotency_key == PaymentIntentRow.idempotency_key)
        .correlate(PaymentIntentRow)
        .exists(),
        sa.select(sa.literal(1))
        .select_from(PlanPurchaseRow)
        .where(PlanPurchaseRow.idempotency_key == PaymentIntentRow.idempotency_key)
        .correlate(PaymentIntentRow)
        .exists(),
    )
    grant = (
        sa.select(sa.literal(1))
        .select_from(CreditLedgerRow)
        .where(
            CreditLedgerRow.idempotency_key == PaymentIntentRow.idempotency_key,
            CreditLedgerRow.kind == CreditEntryKind.GRANT,
        )
        .correlate(PaymentIntentRow)
        .exists()
    )
    transaction_count = (
        sa.select(sa.func.count())
        .select_from(PaymeTransactionRow)
        .where(PaymeTransactionRow.intent_id == PaymentIntentRow.id)
        .correlate(PaymentIntentRow)
        .scalar_subquery()
    )
    # Ordered by the RAIL's instant and not by ours: ``payme_time`` is when Payme created the
    # transaction, which is the order a customer's attempts actually happened in. ``created_at``
    # is when we heard about them, and those differ by the network, by a retry and, on a bad
    # day, by however long this process was unavailable.
    latest_state = (
        sa.select(PaymeTransactionRow.state)
        .where(PaymeTransactionRow.intent_id == PaymentIntentRow.id)
        .correlate(PaymentIntentRow)
        .order_by(PaymeTransactionRow.payme_time.desc(), PaymeTransactionRow.id.desc())
        .limit(1)
        .scalar_subquery()
    )
    # The latest PERFORM across every transaction on the intent, which is not the same question
    # as "the latest transaction's perform_time": the newest attempt may be a cancelled retry
    # against an intent a previous one already performed.
    latest_perform = (
        sa.select(sa.func.max(PaymeTransactionRow.perform_time))
        .where(PaymeTransactionRow.intent_id == PaymentIntentRow.id)
        .correlate(PaymentIntentRow)
        .scalar_subquery()
    )
    return sa.select(
        PaymentIntentRow.id,
        PaymentIntentRow.public_ref,
        PaymentIntentRow.created_at,
        PaymentIntentRow.valid_until,
        PaymentIntentRow.state,
        PaymentIntentRow.product,
        PaymentIntentRow.plan_songs,
        PaymentIntentRow.plan_days,
        PaymentIntentRow.amount_minor,
        PaymentIntentRow.currency,
        PaymentIntentRow.provider,
        PaymentIntentRow.merchant_id,
        PaymentIntentRow.is_sandbox,
        PaymentIntentRow.telegram_user_id,
        PaymentIntentRow.settled_at,
        PaymentIntentRow.settle_note,
        PaymentIntentRow.notified_at,
        transaction_count.label("transaction_count"),
        latest_state.label("latest_transaction_state"),
        latest_perform.label("latest_perform_time"),
        receipt.label("has_receipt"),
        grant.label("has_grant"),
    ).select_from(PaymentIntentRow)


def _filtered(filters: IntentFilters) -> Select[Any]:
    """:func:`_projection` narrowed by every filter the caller supplied.

    ``settled_by`` is a predicate on ``settle_note`` and not a stored classification: the
    column holds ``'payme'`` or ``'operator:<ref>'`` and the RAIL arm is spelled as "not the
    operator prefix" rather than as an equality with ``'payme'``, so a second rail writing a
    third note still lands in "the rail moved this money" rather than vanishing from both arms.
    """
    statement = _projection()
    statement = apply_in(statement, PaymentIntentRow.state, filters.states)
    statement = apply_in(statement, PaymentIntentRow.product, filters.products)
    if filters.is_sandbox is not None:
        statement = statement.where(PaymentIntentRow.is_sandbox.is_(filters.is_sandbox))
    if filters.settled_by is SettleSource.OPERATOR:
        statement = statement.where(PaymentIntentRow.settle_note.startswith(OPERATOR_SETTLE_PREFIX))
    elif filters.settled_by is SettleSource.RAIL:
        statement = statement.where(
            PaymentIntentRow.settle_note.is_not(None),
            ~PaymentIntentRow.settle_note.startswith(OPERATOR_SETTLE_PREFIX),
        )
    attention = _attention_clause(filters)
    if attention is not None:
        statement = statement.where(attention)
    return apply_window(statement, PaymentIntentRow.created_at, filters.window)


def _cursor_of(item: IntentListItem) -> Cursor:
    return Cursor(at=item.created_at, id=item.intent_id)


def _list_item(row: Any) -> IntentListItem:
    """Project one result row. The enums are coerced to their text on the way out.

    ``str(row.state)`` and not ``row.state.value``: the column is a ``StrEnum`` today, and the
    coercion is written so it survives a caller reading this query through a Core select that
    hands back plain text.
    """
    return IntentListItem(
        intent_id=row.id,
        public_ref=str(row.public_ref),
        created_at=row.created_at,
        valid_until=row.valid_until,
        state=str(row.state),
        product=str(row.product),
        plan_songs=None if row.plan_songs is None else int(row.plan_songs),
        plan_days=None if row.plan_days is None else int(row.plan_days),
        amount_minor=int(row.amount_minor),
        currency=str(row.currency),
        provider=str(row.provider),
        merchant_id=str(row.merchant_id),
        is_sandbox=bool(row.is_sandbox),
        telegram_user_id=(None if row.telegram_user_id is None else int(row.telegram_user_id)),
        transaction_count=int(row.transaction_count),
        latest_transaction_state=(
            None if row.latest_transaction_state is None else str(row.latest_transaction_state)
        ),
        latest_perform_time=row.latest_perform_time,
        has_receipt=bool(row.has_receipt),
        has_grant=bool(row.has_grant),
        settled_at=row.settled_at,
        settle_note=None if row.settle_note is None else str(row.settle_note),
        notified_at=row.notified_at,
    )
