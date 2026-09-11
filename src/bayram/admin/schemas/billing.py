"""Wire models for the Rail Board — the rail, and individual payments, and no revenue total.

This surface is about a MACHINE and about ONE PAYMENT AT A TIME. It deliberately publishes no
money aggregate at all: ``routers/dashboard.py::finance`` already concatenates
``plan_revenue_totals`` and ``topup_revenue_totals`` into the one revenue rollup this panel
has, and a second, differently-computed figure beside it would be free to disagree — at which
point the first operator to notice files the difference as a bug against whichever screen they
opened second. Nothing here sums ``amount_minor`` across intents. Sandbox contamination is made
VISIBLE per row and on the header instead of being subtracted from a total nobody can
reconcile (``BILLING_RAIL_BOARD §1``).

**Two facts are computed HERE rather than in the SPA, and both for the same reason.**
:func:`settlement_verdict` turns four integers into one of five words, and :func:`build_lifeline`
turns an intent plus four collections into six steps in four states. Putting either in the
client would let two clients invent a fifth state, and would let the panel's reading of the
reconciliation identity drift from the one ``run_payme_sweep`` logs every five minutes on the
same numbers. Both are pure functions over view models, so both are unit-testable with no
router, no session and no HTTP (``tests/test_admin/test_billing_schema.py``).

**The lifeline's prose is a SLUG and never a sentence.** :class:`LifelineNote` is a closed
vocabulary and the console renders it from its own locale files, because the deployed console
is trilingual (uz/ru/en, key parity asserted across all three). An English sentence on the wire
would be a fourth translation nobody could reach. The same rule governs
:class:`NotifyRefusal` and :class:`SettlementVerdict`.

**PRIVACY — three absences, each load-bearing.**

* There is **no ``telegramUserId`` field anywhere on this surface**, not even a nullable one.
  A payer's identity is a ``POST /api/reveal`` question with its own step-up, its own budget
  and its own audit row; a billing route that could answer it would be a second reveal path
  with none of the three. What travels instead is ``telegramUserIdMasked`` plus an EXPLICIT
  ``isBuyerErased``, because ``null`` (erased) and ``"•••"`` (masked) are two different facts
  and collapsing them is the bug the panel's masked-value components exist to prevent.
* There is **no ``idempotencyKey``** on any model here, asserted by test. It is shaped
  ``topup:{telegram_user_id}:{scope}:{seq}`` and therefore CONTAINS the customer's Telegram id
  — the precise leak ``public_ref`` was minted to prevent. Shipping it behind a warning tooltip
  was the rejected alternative: a tooltip does not stop a value reaching a DOM node, a
  screenshot and a support ticket. It is not a field on any view model either — not even a
  server-side one, because a view is rendered into log lines and ``repr``\\ s: the dossier
  handler fetches it through ``payment_intents.idempotency_key_for``, hands it to three
  queries, and lets it go out of scope.
* :attr:`IntentDossierView.settle_command` contains the public reference and **nothing else**,
  which is why it is built here from one template rather than assembled in the SPA.

**No ``gatewayEnabled`` and no ``checkoutProvider`` on :class:`RailStatusView`, not even as
nulls.** Neither is readable from this process — ``Settings.checkout_provider`` is loaded from
the BOT's env file and ``PaymeSettings.payme_enabled`` from ``/etc/bayram/payme.env`` — and a
field that is always ``null`` teaches the next reader it might one day be populated, which is
how somebody eventually populates it from ``.env.admin`` and renders the wrong answer with
total confidence. The ABSENCE plus the console's stated refusal is what teaches the truth. What
the panel can honestly report is :class:`CheckoutSeenView`, measured off the newest intent, and
the Redis pause key, which it can actually read.

**``isPaused`` is a ``bool`` and never a tri-state.** ``bayram.payme.pause.is_paused`` never
raises and answers ``False`` when Redis is unwell, because that is what the bot's own checkout
path does. A panel reporting ``UNKNOWN`` would be a second reader disagreeing with the one
``PaymeCheckoutProvider.charge`` consults — two answers to "is the rail paused?", and the
operator would act on the panel's. The two caveats travel as copy beside the switch instead
(``BILLING_RAIL_BOARD §2``).

**Why :class:`WindowView` is spelled here and not imported from
:mod:`bayram.admin.schemas.dashboard`.** That module's window model is
``{from, to}``, whose Python field must be written ``from_`` with a hand-written
``Field(alias="from")`` — the one place in this package where a field name cannot be generated
mechanically from its wire name, which is the property ``ApiModel``'s ``alias_generator``
exists to guarantee. ``since``/``until`` restore it, and they are the names the server's own
code already uses for the two bounds (``window.resolve_window(since, until, *, now)``). The
cost is real and is recorded rather than hidden: this API now spells one concept two ways, and
a reader who finds ``from``/``to`` on ``/metrics/dashboard/*`` and ``since``/``until`` here
should know the difference is a Python keyword and nothing else.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Final
from uuid import UUID

from bayram.admin.schemas.actions import ReasonedRequest
from bayram.admin.schemas.common import ApiModel
from bayram.admin.schemas.page import PageMeta
from bayram.admin.serializers.redaction import mask_telegram_user_id
from bayram.db.admin.payment_intents import SettleSource
from bayram.db.admin.sql import TimeWindow
from bayram.db.admin.views import (
    AttentionCounts,
    CheckoutSeen,
    FaultCluster,
    InboundCall,
    IntentDetail,
    IntentFunnel,
    IntentListItem,
    IntentReferenceMatch,
    PaymentGrant,
    PaymentReceipt,
    RailStateCount,
    RailTransaction,
    SettlementSnapshot,
)
from bayram.db.enums import IntentProduct, PaymentIntentState
from bayram.payme.ports import OPERATOR_SETTLE_PREFIX

__all__ = [
    "SETTLE_COMMAND_TEMPLATE",
    "AttentionView",
    "CallPage",
    "ChainStopKind",
    "ChainStopView",
    "CheckoutSeenView",
    "FaultClusterListView",
    "FaultClusterView",
    "InboundCallView",
    "IntentDetailView",
    "IntentDossierView",
    "IntentListItemView",
    "IntentLookupView",
    "IntentPage",
    "LedgerEntryView",
    "LifelineNote",
    "LifelineStatus",
    "LifelineStep",
    "LifelineStepView",
    "LifelineView",
    "NotifyEligibilityView",
    "NotifyEnqueuedView",
    "NotifyRefusal",
    "NotifyRequest",
    "RailFunnelView",
    "RailProbesView",
    "RailStatusView",
    "RailSwitchRequest",
    "RailSwitchView",
    "RailTransactionView",
    "ReceiptView",
    "SettlementVerdict",
    "SettlementView",
    "StateCountView",
    "WindowView",
    "build_lifeline",
    "notify_refusal",
    "settle_command",
    "settle_source_of",
    "settlement_verdict",
    "to_attention_view",
    "to_chain_stop_view",
    "to_checkout_seen_view",
    "to_fault_cluster_list_view",
    "to_fault_cluster_view",
    "to_inbound_call_view",
    "to_intent_detail_view",
    "to_intent_list_item_view",
    "to_intent_lookup_view",
    "to_ledger_entry_view",
    "to_notify_eligibility_view",
    "to_rail_funnel_view",
    "to_rail_status_view",
    "to_rail_transaction_view",
    "to_receipt_view",
    "to_settlement_view",
    "to_window_view",
]

#: The recovery command the dossier RENDERS and never runs. Spelled once so the flag names
#: live in one place, and interpolated with the public reference TWICE on purpose: the string
#: an operator copies then contains nothing but that reference — no Telegram id, no
#: idempotency key, no amount — which is what makes it safe to paste into a ticket.
#:
#: The panel has no route behind this. ``payme_sql.claim_intent_for_operator`` is the ONE
#: transition in the whole state machine that names no holder and therefore drops the mutex
#: ``hold_intent`` exists to enforce, and the evidence that authorises it is a charge in the
#: Payme merchant cabinet — which this process is structurally forbidden to see, because
#: ``app.py::derive_forbidden_env_vars`` refuses to boot in prod if the merchant key is
#: reachable. A terminal is the correct blast door (``DECISIONS.md``: the panel may find and
#: may nudge; it may not mint).
SETTLE_COMMAND_TEMPLATE: Final[str] = "python -m bayram.payme.cli settle --ref {ref} --note '{ref}'"


# ---------------------------------------------------------------------------
# Small shared shapes
# ---------------------------------------------------------------------------
class WindowView(ApiModel):
    """The half-open ``[since, until)`` a windowed number was counted over.

    ``since`` is nullable and ``until`` is not, which is :class:`~bayram.db.admin.sql.TimeWindow`'s
    own asymmetry rather than a new one: ``?to=`` alone counts everything ever recorded up to
    that instant and has no lower bound to echo, while ``?from=`` alone always has an upper one
    — the moment the request was served — and echoing it is what keeps the answer reproducible.
    """

    since: datetime | None
    until: datetime


def to_window_view(window: TimeWindow) -> WindowView:
    """Echo a window the caller asked for. Never invents one; see :func:`to_optional_window`."""
    return WindowView(since=window.start, until=window.end)


def to_optional_window(window: TimeWindow | None) -> WindowView | None:
    """``None`` for "the whole record", which is a different answer from "since the beginning"."""
    return None if window is None else to_window_view(window)


class StateCountView(ApiModel):
    """One state and how many rows are in it. **A state with no rows is ABSENT, never zero.**

    Shared by the intent funnel and the transaction funnel because the shape is identical and a
    second class would be two chances to zero-fill one of them. A zero bar on a payments screen
    is a claim about payments nobody attempted on a day this rail may not have been on.
    """

    state: str
    count: int


class CheckoutSeenView(ApiModel):
    """Provider, cashbox and sandbox flag — MEASURED off the newest intent, never configured.

    ``seenAt`` is the provenance of the other three and is on the wire beside them so a reading
    taken from a six-week-old row is VISIBLY stale rather than quietly wrong. ``null`` for the
    whole object means no checkout has ever been opened here, which is a different screen with
    a different remedy from "the last one was a sandbox rehearsal".
    """

    provider: str
    merchant_id: str
    is_sandbox: bool
    seen_at: datetime


def to_checkout_seen_view(seen: CheckoutSeen) -> CheckoutSeenView:
    return CheckoutSeenView(
        provider=seen.provider,
        merchant_id=seen.merchant_id,
        is_sandbox=seen.is_sandbox,
        seen_at=seen.seen_at,
    )


class InboundCallView(ApiModel):
    """One inbound JSON-RPC call from the rail, and how this deployment answered it.

    ``replyCode`` is ``0`` for success and the JSON-RPC code otherwise — negative for every
    protocol fault — and success is told from failure BY SIGN with no second boolean beside it,
    which would be a fact the code already states and free to disagree with it. The code's
    protocol NAME is resolved at the presentation edge only, with the integer always shown, so
    a code Payme adds tomorrow still renders.

    ``peerIp`` is Payme's data-centre address and never a customer's; this table holds no
    Telegram id, no request body and no header at all.
    """

    id: UUID
    at: datetime
    method: str
    public_ref: str | None
    payme_transaction_id: str | None
    reply_code: int
    peer_ip: str | None
    duration_ms: int


def to_inbound_call_view(call: InboundCall) -> InboundCallView:
    return InboundCallView(
        id=call.id,
        at=call.at,
        method=call.method,
        public_ref=call.public_ref,
        payme_transaction_id=call.payme_transaction_id,
        reply_code=call.reply_code,
        peer_ip=call.peer_ip,
        duration_ms=call.duration_ms,
    )


class CallPage(ApiModel):
    """One keyset page of the inbound journal."""

    items: list[InboundCallView]
    meta: PageMeta


# ---------------------------------------------------------------------------
# The board: status, the settlement identity, the funnel, what needs attention
# ---------------------------------------------------------------------------
class RailStatusView(ApiModel):
    """Is this machine armed, and what has it heard? The board's header, in one round trip.

    **It takes no window, deliberately.** Every field is either a current fact or a probe
    measured with the window ignored; giving the route a range would invite the console to
    render "the rail is off" because somebody narrowed the picker to an hour.

    The four ``has*`` probes are what make a screen of zeros legible: ``0`` alone cannot
    separate "nothing in the range you chose" from "this has never run here", and those are two
    screens with two remedies (§11.4). They are ROW probes rather than ``has_table`` probes
    because the migration ships WITH this panel, so "the table exists" is true on day one and
    is not the question anybody is asking.

    ``pauseKey`` is on the wire so an operator debugging with ``redis-cli`` reads the key name
    off the screen they are already looking at, rather than from a runbook.
    """

    checkout_seen: CheckoutSeenView | None
    is_paused: bool
    pause_key: str
    last_inbound_call: InboundCallView | None
    has_opened_any_intent: bool
    has_recorded_transaction: bool
    has_recorded_inbound_call: bool
    has_settled_any_intent: bool
    as_of: datetime


def to_rail_status_view(
    *,
    seen: CheckoutSeen | None,
    is_paused: bool,
    pause_key: str,
    last_call: InboundCall | None,
    has_opened_any_intent: bool,
    has_recorded_transaction: bool,
    has_recorded_inbound_call: bool,
    has_settled_any_intent: bool,
    now: datetime,
) -> RailStatusView:
    """Assemble the header. Every argument is keyword-only: eight of them are booleans."""
    return RailStatusView(
        checkout_seen=None if seen is None else to_checkout_seen_view(seen),
        is_paused=is_paused,
        pause_key=pause_key,
        last_inbound_call=None if last_call is None else to_inbound_call_view(last_call),
        has_opened_any_intent=has_opened_any_intent,
        has_recorded_transaction=has_recorded_transaction,
        has_recorded_inbound_call=has_recorded_inbound_call,
        has_settled_any_intent=has_settled_any_intent,
        as_of=now,
    )


class SettlementVerdict(StrEnum):
    """The reconciliation identity, collapsed to one word the console renders from its locale.

    Computed server-side by :func:`settlement_verdict` so the panel and
    ``runtime.payme_jobs.run_payme_sweep`` cannot reach different conclusions from the same four
    integers — the sweep logs the identity every five minutes on both the healthy and the
    mismatched path, and a screen that disagreed with the log would send an operator to
    reconcile the two tools instead of the two tables.
    """

    #: Nothing has ever settled here. **NOT** :attr:`BALANCED`: a zero-equals-zero green tick on
    #: a rail that has never taken a payment is the worst lie this card can tell, because it is
    #: indistinguishable from a healthy quiet week and it is the state this deployment is in
    #: today.
    NEVER_SETTLED = "never_settled"
    #: ``grantsWritten > receiptsWritten``. The ONE strictly impossible combination, and the
    #: only one the console renders as a fault: a grant is written inside the same commit as
    #: the receipt it belongs to, and grants are the single-song SUBSET of receipts because a
    #: plan sale grants nothing at purchase.
    GRANTS_OVER_RECEIPTS = "grants_over_receipts"
    #: Fewer receipts than settlements. TWO legitimate causes come first in the copy, and
    #: neither is a defect. One: a buyer erased between paying and settling writes no sale at
    #: all (``db/payme.py::_settle``) — money moved with nobody left to grant to. Two: a
    #: hand-settled payment whose rail transaction ARRIVED LATER is counted in both left-hand
    #: terms against the one receipt it correctly wrote, because
    #: ``_already_settled_by_this_transaction_or_refuse`` answers that late ``PerformTransaction``
    #: with state 2 — it marks the transaction ``performed`` and re-runs an insert-or-ignore
    #: sale under the operator's own key, leaving ``settle_note`` and ``settled_at`` untouched.
    #: See :func:`~bayram.db.admin.payment_intents.settlement_snapshot` for why that is left
    #: uncorrected rather than subtracted.
    RECEIPTS_SHORT = "receipts_short"
    #: More receipts than settlements. The window's edge is the usual cause — a sale settled
    #: just inside it against a transaction performed just outside.
    RECEIPTS_OVER = "receipts_over"
    #: ``transactionsPerformed + operatorSettlements == receiptsWritten``.
    BALANCED = "balanced"


def settlement_verdict(
    snapshot: SettlementSnapshot, *, has_recorded_settlement: bool
) -> SettlementVerdict:
    """Five words, in one precedence order, from four integers and one probe.

    **The identity is NOT the two-way equality** ``payme_sql.settlement_counts``' own docstring
    asserts. A force-settled intent has no performed transaction, so
    ``transactions_performed == receipts_written`` reports every use of the recovery button as a
    defect — and an alert that fires on a correct action is an alert operators mute.
    ``operatorSettlements`` is a named term precisely so hand-settlements are not mistaken for
    discrepancies, and it is the term that makes the identity true:
    ``performed + operator == receipts``, with ``grants <= receipts`` beside it.

    Precedence, and each step is a decision rather than an ordering accident:

    1. :attr:`~SettlementVerdict.NEVER_SETTLED` first, because it is the only verdict that says
       "there is no identity to check yet" and every arithmetic branch below would answer
       :attr:`~SettlementVerdict.BALANCED` on four zeros.
    2. :attr:`~SettlementVerdict.GRANTS_OVER_RECEIPTS` second and above the arithmetic, because
       it is impossible rather than merely unequal: on a database showing both, the impossible
       fact is the one to investigate.
    3. The two arithmetic mismatches, which differ only in sign and in which explanation the
       console leads with.
    """
    if not has_recorded_settlement:
        return SettlementVerdict.NEVER_SETTLED
    if snapshot.grants_written > snapshot.receipts_written:
        return SettlementVerdict.GRANTS_OVER_RECEIPTS
    settled = snapshot.transactions_performed + snapshot.operator_settlements
    if settled > snapshot.receipts_written:
        return SettlementVerdict.RECEIPTS_SHORT
    if settled < snapshot.receipts_written:
        return SettlementVerdict.RECEIPTS_OVER
    return SettlementVerdict.BALANCED


class SettlementView(ApiModel):
    """The reconciliation identity over one bounded window, with its verdict attached.

    ``grantsWritten`` sits apart from the other three in the console because it is a SUBSET
    rather than a term of the identity: a plan sale writes a receipt and no credit at all, so
    ``grants < receipts`` is the ordinary state of a deployment that sells plans and says
    nothing about health.
    """

    window: WindowView
    transactions_performed: int
    operator_settlements: int
    receipts_written: int
    grants_written: int
    #: Measured with the window IGNORED. Without it, four zeros are unreadable.
    has_recorded_settlement: bool
    verdict: SettlementVerdict


def to_settlement_view(
    snapshot: SettlementSnapshot, *, window: TimeWindow, has_recorded_settlement: bool
) -> SettlementView:
    return SettlementView(
        window=to_window_view(window),
        transactions_performed=snapshot.transactions_performed,
        operator_settlements=snapshot.operator_settlements,
        receipts_written=snapshot.receipts_written,
        grants_written=snapshot.grants_written,
        has_recorded_settlement=has_recorded_settlement,
        verdict=settlement_verdict(snapshot, has_recorded_settlement=has_recorded_settlement),
    )


class RailFunnelView(ApiModel):
    """Where a window's payments got to, on both sides of the rail, plus the RPC volume.

    The expiry split is the only derived pair here and it is the one worth having: an intent
    that expired with **no** rail transaction is a customer who never reached the payment form
    (a funnel problem), and one that expired **after** a transaction is a payment that started
    and did not finish (a rail problem). Two owners, two remedies, one column that records
    neither — so it is a read-time ``EXISTS`` rather than a migration.

    ``rpcCalls`` and ``rpcFaults`` are counts and not a series: a sparkline with no data for
    months is a chart with an axis and no line, which reads as a failed fetch. The moment the
    rail has taken real traffic for a fortnight, ``/metrics/rail/calls-by-bucket`` is the route
    to add.
    """

    window: WindowView | None
    intents: list[StateCountView]
    intents_expired_after_transaction: int
    intents_expired_with_no_transaction: int
    transactions: list[StateCountView]
    rpc_calls: int
    rpc_faults: int
    has_opened_any_intent: bool
    has_recorded_transaction: bool
    has_recorded_inbound_call: bool


def to_rail_funnel_view(
    *,
    window: TimeWindow | None,
    funnel: IntentFunnel,
    transactions: tuple[RailStateCount, ...],
    rpc_calls: int,
    rpc_faults: int,
    has_opened_any_intent: bool,
    has_recorded_transaction: bool,
    has_recorded_inbound_call: bool,
) -> RailFunnelView:
    return RailFunnelView(
        window=to_optional_window(window),
        intents=[StateCountView(state=row.state, count=row.count) for row in funnel.states],
        intents_expired_after_transaction=funnel.expired_after_transaction,
        intents_expired_with_no_transaction=funnel.expired_with_no_transaction,
        transactions=[StateCountView(state=row.state, count=row.count) for row in transactions],
        rpc_calls=rpc_calls,
        rpc_faults=rpc_faults,
        has_opened_any_intent=has_opened_any_intent,
        has_recorded_transaction=has_recorded_transaction,
        has_recorded_inbound_call=has_recorded_inbound_call,
    )


class AttentionView(ApiModel):
    """The three populations an operator can act on, as of one instant. **No window.**

    A payment stuck last Tuesday is still stuck today, so scoping these to the header's range
    would hide exactly the rows they exist to find. ``asOf`` and ``staleAfterHours`` are echoed
    because the first count is the only one whose definition the caller chose.

    ``paidWithNoReceipt`` is dominated by ERASED BUYERS and is not a defect list — see
    :attr:`SettlementVerdict.RECEIPTS_SHORT`.
    """

    as_of: datetime
    stale_after_hours: int
    awaiting_held_past_timeout: int
    paid_never_announced: int
    paid_with_no_receipt: int


def to_attention_view(
    counts: AttentionCounts, *, now: datetime, stale_after_hours: int
) -> AttentionView:
    return AttentionView(
        as_of=now,
        stale_after_hours=stale_after_hours,
        awaiting_held_past_timeout=counts.awaiting_held_past_timeout,
        paid_never_announced=counts.paid_never_announced,
        paid_with_no_receipt=counts.paid_with_no_receipt,
    )


class FaultClusterView(ApiModel):
    """``method`` × ``replyCode``, counted, with the span it happened over.

    ``firstAt``/``lastAt`` are the point beside the count: a fault that happened once an hour
    all night and one that happened 240 times in eight minutes are the same number and two
    different incidents. ``slowestMs`` is a max and never a mean, because a mean over a cluster
    containing one timeout hides the timeout.
    """

    method: str
    reply_code: int
    calls: int
    first_at: datetime
    last_at: datetime
    slowest_ms: int


def to_fault_cluster_view(cluster: FaultCluster) -> FaultClusterView:
    return FaultClusterView(
        method=cluster.method,
        reply_code=cluster.reply_code,
        calls=cluster.calls,
        first_at=cluster.first_at,
        last_at=cluster.last_at,
        slowest_ms=cluster.slowest_ms,
    )


class FaultClusterListView(ApiModel):
    """The fault table, with the probe that says whether an empty one means anything."""

    window: WindowView | None
    clusters: list[FaultClusterView]
    has_recorded_inbound_call: bool


def to_fault_cluster_list_view(
    clusters: tuple[FaultCluster, ...],
    *,
    window: TimeWindow | None,
    has_recorded_inbound_call: bool,
) -> FaultClusterListView:
    return FaultClusterListView(
        window=to_optional_window(window),
        clusters=[to_fault_cluster_view(cluster) for cluster in clusters],
        has_recorded_inbound_call=has_recorded_inbound_call,
    )


# ---------------------------------------------------------------------------
# One payment: the list row, the lookup, and the dossier
# ---------------------------------------------------------------------------
def settle_source_of(settle_note: str | None) -> SettleSource | None:
    """Who moved this money — the rail, or one of us. ``None`` while it has not moved.

    Decided by the OPERATOR prefix alone and never by matching the rail's own note. That is
    one predicate rather than two, it is the same predicate
    ``payment_intents.settlement_snapshot`` counts operator settlements with, and it fails in
    the honest direction: anything that is not a hand-settlement was written by the settlement
    path, so a future rail whose note reads something other than ``'payme'`` classifies as
    ``rail`` rather than as ``null``. The ``'payme'`` literal itself is private to
    :mod:`bayram.db.payme` and is deliberately not imported — a third reader of a fourth copy of
    that string is how the two halves start disagreeing.
    """
    if settle_note is None:
        return None
    if settle_note.startswith(OPERATOR_SETTLE_PREFIX):
        return SettleSource.OPERATOR
    return SettleSource.RAIL


class IntentListItemView(ApiModel):
    """One started payment, with its whole fulfilment chain answered as booleans.

    ``telegramUserIdMasked`` is ``null`` when — and only when — ``isBuyerErased`` is true. The
    pair is redundant on purpose: a console that had to infer erasure from a null would have to
    get that inference right on every screen, and the one time it does not it renders a
    lawfully erased customer as a blank cell that reads as a bug or as fraud. The explicit
    boolean makes "buyer erased" a state the SPA can render as a chip, with the amount intact
    beside it.

    ``settleSource`` and ``settleNote`` travel together: the enum is what a filter and a badge
    read, and the raw note is what an operator reads, because ``operator:INC-441`` names the
    incident and the enum cannot.
    """

    intent_id: UUID
    public_ref: str
    created_at: datetime
    valid_until: datetime
    state: str
    product: str
    plan_songs: int | None
    plan_days: int | None
    amount_minor: int
    currency: str
    provider: str
    merchant_id: str
    is_sandbox: bool
    telegram_user_id_masked: str | None
    is_buyer_erased: bool
    transaction_count: int
    latest_transaction_state: str | None
    latest_perform_time: datetime | None
    has_receipt: bool
    #: **``false`` is normal for a plan sale**, which writes a receipt and grants nothing at
    #: purchase. Rendering it as a broken chain is the regression the schema test pins.
    has_grant: bool
    settled_at: datetime | None
    settle_source: SettleSource | None
    settle_note: str | None
    notified_at: datetime | None


def to_intent_list_item_view(item: IntentListItem) -> IntentListItemView:
    """Project one row. The masking decision is made HERE and nowhere else on this surface."""
    return IntentListItemView(
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
        telegram_user_id_masked=(
            None if item.telegram_user_id is None else mask_telegram_user_id(item.telegram_user_id)
        ),
        is_buyer_erased=item.telegram_user_id is None,
        transaction_count=item.transaction_count,
        latest_transaction_state=item.latest_transaction_state,
        latest_perform_time=item.latest_perform_time,
        has_receipt=item.has_receipt,
        has_grant=item.has_grant,
        settled_at=item.settled_at,
        settle_source=settle_source_of(item.settle_note),
        settle_note=item.settle_note,
        notified_at=item.notified_at,
    )


class RailProbesView(ApiModel):
    """The three window-blind probes that ride INSIDE the intents page.

    Inside the envelope rather than behind a second ``/ops/capabilities`` request, which is the
    shape ``getVendorUsage`` already takes for the same reason: an empty table must be legible
    from the response that was empty, not from a follow-up the console might not make.
    """

    has_opened_any_intent: bool
    has_recorded_transaction: bool
    has_settled_any_intent: bool


class IntentPage(ApiModel):
    """One keyset page of payments, plus the probes that say what an empty page means."""

    items: list[IntentListItemView]
    meta: PageMeta
    capabilities: RailProbesView


class IntentLookupView(ApiModel):
    """ "The customer read me a reference over the phone" — answered in one round trip.

    Both fields are ``null`` together for a well-formed reference that matches nothing, which
    is a **200 and not a 404**: the question "does a payment exist under this reference?" was
    answered, and the answer is no. A 404 would make the console render an error page for a
    successful search, and would make a typo indistinguishable from a route that is missing.
    A MALFORMED reference is a different screen and is a 422 from the boundary.

    ``matchedOn`` says which identifier answered, so a support agent who pasted a Payme
    transaction id into the reference box learns that rather than wondering why the lookup
    "worked differently".
    """

    intent_id: UUID | None
    matched_on: str | None


def to_intent_lookup_view(match: IntentReferenceMatch | None) -> IntentLookupView:
    if match is None:
        return IntentLookupView(intent_id=None, matched_on=None)
    return IntentLookupView(intent_id=match.intent_id, matched_on=match.matched_on)


class IntentDetailView(ApiModel):
    """The dossier's head. :class:`IntentListItemView`'s fields, as its own type.

    Separate for the reason :class:`~bayram.db.admin.views.IntentDetail` is separate from
    :class:`~bayram.db.admin.views.IntentListItem`: this is where a field that costs a subquery
    per row would land, and sharing the model would put that cost on every row of every page.

    **It carries no ``idempotencyKey``**, asserted by a test that introspects ``model_fields``
    for the substring — see the module docstring.
    """

    intent_id: UUID
    public_ref: str
    created_at: datetime
    valid_until: datetime
    state: str
    product: str
    plan_songs: int | None
    plan_days: int | None
    amount_minor: int
    currency: str
    provider: str
    merchant_id: str
    is_sandbox: bool
    telegram_user_id_masked: str | None
    is_buyer_erased: bool
    transaction_count: int
    latest_transaction_state: str | None
    latest_perform_time: datetime | None
    has_receipt: bool
    has_grant: bool
    settled_at: datetime | None
    settle_source: SettleSource | None
    settle_note: str | None
    notified_at: datetime | None


def to_intent_detail_view(detail: IntentDetail) -> IntentDetailView:
    """Project the dossier's head. The join key is not on ``detail`` and never reaches here."""
    return IntentDetailView(
        intent_id=detail.intent_id,
        public_ref=detail.public_ref,
        created_at=detail.created_at,
        valid_until=detail.valid_until,
        state=detail.state,
        product=detail.product,
        plan_songs=detail.plan_songs,
        plan_days=detail.plan_days,
        amount_minor=detail.amount_minor,
        currency=detail.currency,
        provider=detail.provider,
        merchant_id=detail.merchant_id,
        is_sandbox=detail.is_sandbox,
        telegram_user_id_masked=(
            None
            if detail.telegram_user_id is None
            else mask_telegram_user_id(detail.telegram_user_id)
        ),
        is_buyer_erased=detail.telegram_user_id is None,
        transaction_count=detail.transaction_count,
        latest_transaction_state=detail.latest_transaction_state,
        latest_perform_time=detail.latest_perform_time,
        has_receipt=detail.has_receipt,
        has_grant=detail.has_grant,
        settled_at=detail.settled_at,
        settle_source=settle_source_of(detail.settle_note),
        settle_note=detail.settle_note,
        notified_at=detail.notified_at,
    )


class RailTransactionView(ApiModel):
    """One rail-side transaction and the three instants a replay must be able to repeat.

    ``cancelReason`` is a BARE INTEGER by argued decision: the codes are the rail's vocabulary
    and they extend it without asking us, so a ``VARCHAR`` mirror could only ever emit a value
    they do not recognise. It is named at the presentation edge with the number always beside
    the name. ``null``, never ``0`` — zero is not a reason code.
    """

    payme_transaction_id: str
    state: str
    payme_time: datetime
    create_time: datetime
    perform_time: datetime | None
    cancel_time: datetime | None
    cancel_reason: int | None


def to_rail_transaction_view(transaction: RailTransaction) -> RailTransactionView:
    return RailTransactionView(
        payme_transaction_id=transaction.payme_transaction_id,
        state=transaction.state,
        payme_time=transaction.payme_time,
        create_time=transaction.create_time,
        perform_time=transaction.perform_time,
        cancel_time=transaction.cancel_time,
        cancel_reason=transaction.cancel_reason,
    )


class ReceiptView(ApiModel):
    """The sale written under this intent's key, from whichever receipts table it landed in.

    ``source`` is the literal table name, so the console says which book the money is in rather
    than making a reader infer it from which fields are null. ``reference`` is the rail's own id
    for the charge — the only field here that is useful OUT of band, and the one an operator
    searches the Payme merchant cabinet for, which matters because this process is structurally
    forbidden to display that cabinet itself.
    """

    source: str
    amount_minor: int
    currency: str
    provider: str
    reference: str | None
    credits_granted: int | None
    songs_included: int | None
    songs_used: int | None
    plan_ends_at: datetime | None
    created_at: datetime


def to_receipt_view(receipt: PaymentReceipt) -> ReceiptView:
    return ReceiptView(
        source=receipt.source,
        amount_minor=receipt.amount_minor,
        currency=receipt.currency,
        provider=receipt.provider,
        reference=receipt.reference,
        credits_granted=receipt.credits_granted,
        songs_included=receipt.songs_included,
        songs_used=receipt.songs_used,
        plan_ends_at=receipt.plan_ends_at,
        created_at=receipt.created_at,
    )


class LedgerEntryView(ApiModel):
    """One ``credit_ledger`` movement written under this intent's key.

    ``delta`` is SIGNED, as the ledger stores it, rather than an absolute value plus a
    direction — a second spelling is a second chance to get it backwards. ``actor`` is nullable
    because the column is: a settlement always stamps ``fulfilment.CHECKOUT_ACTOR``, so a null
    here means a row written by something that did not name itself, which is worth seeing
    rather than defaulting away.
    """

    kind: str
    delta: int
    reason: str
    actor: str | None
    created_at: datetime


def to_ledger_entry_view(grant: PaymentGrant) -> LedgerEntryView:
    return LedgerEntryView(
        kind=grant.kind,
        delta=grant.delta,
        reason=grant.reason,
        actor=grant.actor,
        created_at=grant.created_at,
    )


# ---------------------------------------------------------------------------
# The lifeline: six steps, four states, one closed vocabulary of reasons
# ---------------------------------------------------------------------------
class LifelineStep(StrEnum):
    """The six things that have to happen for money to become a song, in order."""

    OPENED = "opened"
    RAIL_TRANSACTION = "rail_transaction"
    PERFORMED = "performed"
    RECEIPT = "receipt"
    CREDIT_GRANTED = "credit_granted"
    CUSTOMER_TOLD = "customer_told"


class LifelineStatus(StrEnum):
    """What the panel can SEE of one step. The WHY is :class:`LifelineNote`, beside it.

    Four and not three, because ``not_applicable`` is the whole value of the renderer: a plan
    sale that grants no credit and an erased buyer who gets no receipt are both COMPLETE
    payments, and a three-state renderer would have to call them broken.
    """

    #: It happened, and ``at`` says when.
    DONE = "done"
    #: It has not happened yet and still can.
    PENDING = "pending"
    #: It will never happen, and that is correct. Never a fault.
    NOT_APPLICABLE = "not_applicable"
    #: It should have happened and the panel cannot see it. The one status that asks for work.
    MISSING = "missing"


class LifelineNote(StrEnum):
    """Why a step looks the way it does. A closed slug, rendered by the console's locale files.

    English sentences on the wire were the rejected alternative: the deployed console is
    trilingual with asserted key parity, so a sentence here would be a fourth translation no
    locale file could reach and no reviewer would see.
    """

    #: Payme has never opened a transaction against this intent — which is itself the answer to
    #: most support calls, and is what a hand-settled payment looks like.
    NEVER_OPENED = "never_opened"
    #: A transaction is open and the rail has not come back. Our clock and theirs are not the
    #: same clock, so this is waiting rather than late.
    AWAITING_RAIL = "awaiting_rail"
    #: ``/forget`` ran. The money moved and there is nobody left to grant to or tell. **Never a
    #: discrepancy and never fraud** — ``db/payme.py::_settle`` claims the intent and writes no
    #: sale in exactly this case, deliberately, because refusing would leave the rail retrying
    #: a charge it has already taken.
    BUYER_ERASED = "buyer_erased"
    #: A plan sale mints songs as they are used, so it writes no credit grant at purchase.
    PLAN_GRANTS_NOTHING = "plan_grants_nothing"
    #: This payment never settled, so nothing downstream of it was ever going to happen.
    NOT_SETTLED = "not_settled"
    #: The confirmation went out, and ``at`` says when.
    ALREADY_TOLD = "already_told"
    #: The row that recorded this step is gone rather than never written. Reachable because
    #: there are no foreign keys anywhere on the rail's three tables and their retention clocks
    #: differ, so an old paid intent can outlive the evidence beneath it.
    PURGED = "purged"


class LifelineStepView(ApiModel):
    """One step: what it is, what the panel can see, when, and why it looks like that."""

    key: LifelineStep
    status: LifelineStatus
    at: datetime | None
    note_code: LifelineNote | None


class LifelineView(ApiModel):
    """The six steps, in order. The dossier's dominant panel and this section's whole value."""

    steps: list[LifelineStepView]


def _step(
    key: LifelineStep,
    status: LifelineStatus,
    *,
    at: datetime | None = None,
    note: LifelineNote | None = None,
) -> LifelineStepView:
    return LifelineStepView(key=key, status=status, at=at, note_code=note)


def build_lifeline(
    intent: IntentDetail,
    *,
    transactions: tuple[RailTransaction, ...],
    receipt: PaymentReceipt | None,
    grants: tuple[PaymentGrant, ...],
) -> LifelineView:
    """Six steps in four states, computed once, on the server.

    **Server-side because two clients would invent a fifth state.** The four-state logic is the
    only thing in this section that turns five tables into a sentence an operator can act on,
    and it is exactly the logic that must not differ between the screen and whatever reads the
    API next. It is a pure function so it is asserted against fixtures rather than through a
    router (``tests/test_admin/test_billing_schema.py``).

    **``status`` is what the panel can see; ``note_code`` is why.** That split is what lets
    :attr:`LifelineStatus.MISSING` mean "the evidence is not here" without deciding whether the
    cause is a defect (no note) or a purged row (:attr:`LifelineNote.PURGED`), and it keeps
    every legitimate dead end — a plan that grants nothing, a buyer who was erased, a payment
    that was never made — on :attr:`LifelineStatus.NOT_APPLICABLE` rather than on a fault.

    A step that is merely WAITING on an earlier one carries no note: four identical sentences
    down a six-row list is noise, and the step that actually stopped is the one carrying the
    explanation. The exception is an erased buyer, where the receipt, the grant and the message
    each have their OWN reason to be absent and each says so.
    """
    is_paid = intent.state == PaymentIntentState.PAID.value
    is_terminal_unpaid = intent.state in {
        PaymentIntentState.CANCELLED.value,
        PaymentIntentState.EXPIRED.value,
    }
    is_plan = intent.product == IntentProduct.STARTER.value
    buyer_erased = intent.telegram_user_id is None
    by_operator = settle_source_of(intent.settle_note) is SettleSource.OPERATOR
    opened_at = min((row.payme_time for row in transactions), default=None)
    performed_at = max(
        (row.perform_time for row in transactions if row.perform_time is not None), default=None
    )
    is_holding = any(row.perform_time is None and row.cancel_time is None for row in transactions)

    return LifelineView(
        steps=[
            # The intent row exists, so this one is never anything else. It is on the list
            # because a lifeline that started at "Payme called us" would give an operator no
            # anchor for the instant the customer was handed a link.
            _step(LifelineStep.OPENED, LifelineStatus.DONE, at=intent.created_at),
            _rail_transaction_step(
                opened_at=opened_at,
                is_paid=is_paid,
                by_operator=by_operator,
                is_terminal_unpaid=is_terminal_unpaid,
            ),
            _performed_step(
                performed_at=performed_at,
                is_paid=is_paid,
                by_operator=by_operator,
                is_terminal_unpaid=is_terminal_unpaid,
                is_holding=is_holding,
            ),
            _receipt_step(
                receipt=receipt,
                is_paid=is_paid,
                buyer_erased=buyer_erased,
                is_terminal_unpaid=is_terminal_unpaid,
            ),
            _grant_step(
                grants=grants,
                is_plan=is_plan,
                is_paid=is_paid,
                buyer_erased=buyer_erased,
                is_terminal_unpaid=is_terminal_unpaid,
            ),
            _told_step(
                notified_at=intent.notified_at,
                is_paid=is_paid,
                buyer_erased=buyer_erased,
                is_terminal_unpaid=is_terminal_unpaid,
            ),
        ]
    )


def _rail_transaction_step(
    *,
    opened_at: datetime | None,
    is_paid: bool,
    by_operator: bool,
    is_terminal_unpaid: bool,
) -> LifelineStepView:
    """Did Payme ever open a transaction against this intent?

    A paid intent the RAIL settled must have had one, so its absence is a row that is gone
    rather than an event that never happened — :attr:`LifelineNote.PURGED`, and the one branch
    here that asks for work. A paid intent one of US settled never had one by construction,
    which is what ``settle`` means.
    """
    if opened_at is not None:
        return _step(LifelineStep.RAIL_TRANSACTION, LifelineStatus.DONE, at=opened_at)
    if is_paid and not by_operator:
        return _step(
            LifelineStep.RAIL_TRANSACTION, LifelineStatus.MISSING, note=LifelineNote.PURGED
        )
    if is_paid or is_terminal_unpaid:
        return _step(
            LifelineStep.RAIL_TRANSACTION,
            LifelineStatus.NOT_APPLICABLE,
            note=LifelineNote.NEVER_OPENED,
        )
    return _step(
        LifelineStep.RAIL_TRANSACTION, LifelineStatus.PENDING, note=LifelineNote.NEVER_OPENED
    )


def _performed_step(
    *,
    performed_at: datetime | None,
    is_paid: bool,
    by_operator: bool,
    is_terminal_unpaid: bool,
    is_holding: bool,
) -> LifelineStepView:
    """Did a transaction reach ``performed`` — i.e. did the rail take the money?"""
    if performed_at is not None:
        return _step(LifelineStep.PERFORMED, LifelineStatus.DONE, at=performed_at)
    if is_paid and by_operator:
        return _step(
            LifelineStep.PERFORMED, LifelineStatus.NOT_APPLICABLE, note=LifelineNote.NEVER_OPENED
        )
    if is_paid:
        return _step(LifelineStep.PERFORMED, LifelineStatus.MISSING, note=LifelineNote.PURGED)
    if is_terminal_unpaid:
        return _step(
            LifelineStep.PERFORMED, LifelineStatus.NOT_APPLICABLE, note=LifelineNote.NOT_SETTLED
        )
    if is_holding:
        return _step(
            LifelineStep.PERFORMED, LifelineStatus.PENDING, note=LifelineNote.AWAITING_RAIL
        )
    return _step(LifelineStep.PERFORMED, LifelineStatus.PENDING)


def _receipt_step(
    *,
    receipt: PaymentReceipt | None,
    is_paid: bool,
    buyer_erased: bool,
    is_terminal_unpaid: bool,
) -> LifelineStepView:
    """Was a sale written under this intent's key?

    A paid intent with an erased buyer has NO receipt and that is correct, not missing:
    ``_settle`` claims the intent and writes no sale when there is nobody to sell to, because
    refusing would leave the rail retrying a charge it has already taken.
    """
    if receipt is not None:
        return _step(LifelineStep.RECEIPT, LifelineStatus.DONE, at=receipt.created_at)
    if is_paid and buyer_erased:
        return _step(
            LifelineStep.RECEIPT, LifelineStatus.NOT_APPLICABLE, note=LifelineNote.BUYER_ERASED
        )
    if is_paid:
        return _step(LifelineStep.RECEIPT, LifelineStatus.MISSING)
    if is_terminal_unpaid:
        return _step(
            LifelineStep.RECEIPT, LifelineStatus.NOT_APPLICABLE, note=LifelineNote.NOT_SETTLED
        )
    return _step(LifelineStep.RECEIPT, LifelineStatus.PENDING)


def _grant_step(
    *,
    grants: tuple[PaymentGrant, ...],
    is_plan: bool,
    is_paid: bool,
    buyer_erased: bool,
    is_terminal_unpaid: bool,
) -> LifelineStepView:
    """Was a credit granted?

    **The plan branch comes first and is unconditional**, because it is structural rather than
    circumstantial: a plan mints songs as they are used and grants nothing at purchase, in every
    state, so a plan sale whose grant step read ``missing`` would be the panel reporting a
    healthy sale as broken. That is the regression this function's test exists for.
    """
    if grants:
        return _step(LifelineStep.CREDIT_GRANTED, LifelineStatus.DONE, at=grants[0].created_at)
    if is_plan:
        return _step(
            LifelineStep.CREDIT_GRANTED,
            LifelineStatus.NOT_APPLICABLE,
            note=LifelineNote.PLAN_GRANTS_NOTHING,
        )
    if is_paid and buyer_erased:
        return _step(
            LifelineStep.CREDIT_GRANTED,
            LifelineStatus.NOT_APPLICABLE,
            note=LifelineNote.BUYER_ERASED,
        )
    if is_paid:
        return _step(LifelineStep.CREDIT_GRANTED, LifelineStatus.MISSING)
    if is_terminal_unpaid:
        return _step(
            LifelineStep.CREDIT_GRANTED,
            LifelineStatus.NOT_APPLICABLE,
            note=LifelineNote.NOT_SETTLED,
        )
    return _step(LifelineStep.CREDIT_GRANTED, LifelineStatus.PENDING)


def _told_step(
    *,
    notified_at: datetime | None,
    is_paid: bool,
    buyer_erased: bool,
    is_terminal_unpaid: bool,
) -> LifelineStepView:
    """Was the customer told?

    The one DONE step that carries a note, because it is the one an operator opens the dossier
    to ask about: "was the confirmation sent, and when?" is a question the console answers in a
    sentence beside the instant.

    ``notified_at`` says this deployment enqueued the message and the worker sent it. Whether
    the customer SAW it is a Telegram fact this database does not hold, and the panel repeats
    the CLI's sentence rather than inventing a delivery status it cannot know.
    """
    if notified_at is not None:
        return _step(
            LifelineStep.CUSTOMER_TOLD,
            LifelineStatus.DONE,
            at=notified_at,
            note=LifelineNote.ALREADY_TOLD,
        )
    if is_paid and buyer_erased:
        return _step(
            LifelineStep.CUSTOMER_TOLD,
            LifelineStatus.NOT_APPLICABLE,
            note=LifelineNote.BUYER_ERASED,
        )
    if is_paid:
        return _step(LifelineStep.CUSTOMER_TOLD, LifelineStatus.MISSING)
    if is_terminal_unpaid:
        return _step(
            LifelineStep.CUSTOMER_TOLD,
            LifelineStatus.NOT_APPLICABLE,
            note=LifelineNote.NOT_SETTLED,
        )
    return _step(LifelineStep.CUSTOMER_TOLD, LifelineStatus.PENDING)


# ---------------------------------------------------------------------------
# Where the chain stops, whether the confirmation can be re-sent, and the dossier
# ---------------------------------------------------------------------------
class ChainStopKind(StrEnum):
    """Which of the two endings this payment has."""

    SINGLE_SONG = "single_song"
    PLAN = "plan"


class ChainStopView(ApiModel):
    """The last panel of the dossier, and it is **always rendered**.

    For a single song the honest answer is that whether the purchased credit became a song is
    **unanswerable by construction**: ``credit_accounts.balance`` is a fungible scalar with no
    lot structure, so a later ``DEBIT``/``ORDER_RENDER`` row cannot be attributed to the grant
    that funded it. Stating that is better than hiding the panel, because a missing panel reads
    as a screen that failed to load.

    For a plan the chain does continue — ``plan_purchases.songs_used`` sits on the receipt row
    — which is why the two endings are one model with a discriminator rather than two.
    """

    kind: ChainStopKind
    songs_used: int | None
    songs_included: int | None
    plan_ends_at: datetime | None


def to_chain_stop_view(detail: IntentDetail, *, receipt: PaymentReceipt | None) -> ChainStopView:
    """The consumption figures come from the RECEIPT, which is the row that counts them."""
    if detail.product != IntentProduct.STARTER.value:
        return ChainStopView(
            kind=ChainStopKind.SINGLE_SONG,
            songs_used=None,
            songs_included=None,
            plan_ends_at=None,
        )
    return ChainStopView(
        kind=ChainStopKind.PLAN,
        songs_used=None if receipt is None else receipt.songs_used,
        songs_included=None if receipt is None else receipt.songs_included,
        plan_ends_at=None if receipt is None else receipt.plan_ends_at,
    )


class NotifyRefusal(StrEnum):
    """The three cases where re-enqueuing the confirmation would do nothing.

    All three are evaluable from the intent row alone, which is why the console can disable the
    button with the reason showing instead of discovering the refusal after a round trip. The
    server re-checks every one of them before enqueuing anything: a disabled button is a
    courtesy and the handler is the authority.
    """

    NOT_PAID = "not_paid"
    BUYER_ERASED = "buyer_erased"
    ALREADY_NOTIFIED = "already_notified"


def notify_refusal(detail: IntentDetail) -> NotifyRefusal | None:
    """Why the confirmation cannot be re-sent, or ``None`` when it can.

    The order is ``bayram.payme.cli._notify``'s and is not arbitrary: state first, because an
    unpaid intent has nothing to announce whatever else is true of it; then the erased buyer,
    because there is nobody to send to; then the stamp, which is the only one of the three that
    means "this already worked".
    """
    if detail.state != PaymentIntentState.PAID.value:
        return NotifyRefusal.NOT_PAID
    if detail.telegram_user_id is None:
        return NotifyRefusal.BUYER_ERASED
    if detail.notified_at is not None:
        return NotifyRefusal.ALREADY_NOTIFIED
    return None


class NotifyEligibilityView(ApiModel):
    """Whether the "re-send the confirmation" action is live, and why not when it is not."""

    can_notify: bool
    refusal_code: NotifyRefusal | None
    notified_at: datetime | None


def to_notify_eligibility_view(detail: IntentDetail) -> NotifyEligibilityView:
    refusal = notify_refusal(detail)
    return NotifyEligibilityView(
        can_notify=refusal is None, refusal_code=refusal, notified_at=detail.notified_at
    )


def settle_command(public_ref: str) -> str:
    """The recovery invocation, rendered as text. See :data:`SETTLE_COMMAND_TEMPLATE`."""
    return SETTLE_COMMAND_TEMPLATE.format(ref=public_ref)


class IntentDossierView(ApiModel):
    """Everything an operator needs to answer "did this customer's money turn into a song?".

    One response, assembled from five reads inside ONE transaction, in the order
    ``payme.cli._render_dossier`` established: the intent, its transactions oldest-first, the
    receipt, the ledger rows, the inbound calls. The single-transaction property is the design
    — an operator has to trust that the receipt and the transaction were true at the same
    instant, and separate reads during a live settlement would show a performed transaction
    with no receipt.

    ``calls`` being empty means Payme never called about this payment, which on a live rail is
    what a hand-settled payment looks like. It is NOT a synonym for "the gateway is down", and
    on an intent older than the journal's 90-day retention it means the rows aged out — the
    console decides which by the intent's own age and renders PURGED rather than NEVER HAPPENED.
    """

    intent: IntentDetailView
    transactions: list[RailTransactionView]
    receipt: ReceiptView | None
    ledger: list[LedgerEntryView]
    calls: list[InboundCallView]
    lifeline: LifelineView
    chain_stop: ChainStopView
    notify: NotifyEligibilityView
    #: Selectable text with a copy control and **no submit path** — see
    #: :data:`SETTLE_COMMAND_TEMPLATE`.
    settle_command: str


# ---------------------------------------------------------------------------
# The three writes
# ---------------------------------------------------------------------------
class RailSwitchRequest(ReasonedRequest):
    """``POST /api/ops/rail/pause`` and ``/resume``. A reason and nothing else.

    Which of the two states is being set is carried by the PATH and never by a boolean in the
    body, for the reason ``UserBlockRequest`` gives: a single ``{"isPaused": false}`` would be a
    resume that audits as a pause, and the audit row is the only durable record of which one
    happened — the Redis key keeps no history at all.

    There is no step-up on either route and that is argued at length beside
    ``Permission.RAIL_CONTROL``. The short version: the owning module has explicitly disclaimed
    this switch as a security control, pausing stops the bot QUOTING and moves no money, and a
    password box in front of an incident brake costs seconds at the moment somebody most needs
    them.
    """


class RailSwitchView(ApiModel):
    """The switch as STORED, not as requested.

    The handler re-reads the key through ``rail_switch.read_pause`` after writing it, so an
    operator sees what the bot's checkout path would see rather than an echo of their own
    request. ``changedAt`` is the instant the action was recorded — Redis keeps no history, so
    there is no "when was it first paused" to report and inventing one would be a lie with a
    timestamp on it.
    """

    is_paused: bool
    pause_key: str
    changed_at: datetime


class NotifyRequest(ReasonedRequest):
    """``POST /api/billing/intents/{intentId}/notify``.

    ``requestId`` is ACCEPTED and deliberately NOT READ, which needs saying because the
    obvious reading is that it was forgotten. Deduplication here is structural and cannot fail:
    ``queue.job_id_for_payment_notification`` is deterministic on ``public_ref`` so ARQ collapses
    a double press onto one job, and ``mark_intent_notified`` stamps ``notified_at`` only
    ``WHERE notified_at IS NULL`` so the enqueue and the worker's own five-minute backstop
    cannot both message one person. Minting a key from ``requestId`` would add a third, weaker
    mechanism beside two that already hold.

    It is on the model rather than absent because ``ApiModel`` sets ``extra="forbid"``: the
    console sends one action-body shape for every operator action, and a field it sends that
    this model did not declare is a 422 nobody would think to look for.
    """

    request_id: UUID | None = None


class NotifyEnqueuedView(ApiModel):
    """What the queue did — and ``isReplay`` is the interesting half.

    ``true`` means ARQ already held this job id, so the announcement was already in flight and
    this press changed nothing. That is a success and not a failure, and saying so is what stops
    an operator pressing a third time. ``jobId`` is deterministic, so it is the same string
    either way and can be handed to whoever is reading the worker's logs.
    """

    intent_id: UUID
    public_ref: str
    job_id: str
    is_replay: bool
    enqueued_at: datetime
