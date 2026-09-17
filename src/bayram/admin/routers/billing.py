"""The Rail Board's twelve routes — the payment rail, and one payment at a time.

**Four routers, because the guard is per-router and these sit on four cells** (§12.1 T3).
``build_rail_router`` carries the six aggregate reads on ``DASHBOARD_READ``;
``build_billing_records_router`` carries the three identified-ish reads on ``RECORDS_READ``;
``build_rail_control_router`` carries pause and resume on ``RAIL_CONTROL``; and
``build_payment_notify_router`` carries the one re-enqueue on ``PAYMENT_NOTIFY``. Splitting the
last two is not filing: ``RAIL_CONTROL`` is ADMIN and OWNER while ``PAYMENT_NOTIFY`` reaches
SUPPORT, and folding them would hand a support agent the switch that stops the business
selling in exchange for a button that re-sends a receipt.

**``GET /api/billing/calls`` lives under ``/api/billing`` and on the DASHBOARD_READ router**,
which looks like a mistake and is not. ``payme_rpc_log`` holds no Telegram id, no request body
and no header; ``peer_ip`` is Payme's data-centre address rather than a customer's. It is an
aggregate-class read that happens to be paged, and it is nested under ``/billing`` because that
is where an operator following an incident from the board expects it. ``dashboard.py`` already
ships the mirror image — ``/api/metrics/dashboard/audience-lists`` sits on ``RECORDS_READ``
beside five ``DASHBOARD_READ`` siblings — so a prefix in this API has never implied a cell.

**THE PANEL MAY FIND AND MAY NUDGE; IT MAY NOT MINT.** Three writes ship: pause, resume and
re-enqueue-the-confirmation. Force-settle deliberately does not, and neither do expire,
release, cancel, refund or "run reconcile". The dossier renders the ``settle`` invocation as
copyable text with no submit path (:data:`~bayram.admin.schemas.billing.SETTLE_COMMAND_TEMPLATE`),
because the evidence that authorises it is a charge in the Payme merchant cabinet — which this
process is structurally forbidden to see, since ``app.py::derive_forbidden_env_vars`` refuses
to boot in prod when the merchant key is reachable — and because
``payme_sql.claim_intent_for_operator`` is the ONE transition in the state machine that names
no holder and therefore drops the mutex ``hold_intent`` exists to enforce. An action whose
defining property is that it bypasses the concurrency guard does not belong one click from a
browser tab that polls every fifteen seconds.

**No outbound call is made from this process, on any route here.** The rail's "health" is
reported as evidence — the newest intent's provider and cashbox, the last inbound call, the
Redis pause key — and never as a green dot, which would be a guess wearing the costume of a
measurement.

**Nothing here sums money.** ``routers/dashboard.py::finance`` owns the one revenue rollup this
panel has. A second figure on a payments screen would be free to disagree with it.

**Every count travels beside a window-blind probe.** The rail is empty today — ``merchant_id``
is literally ``placeholder``, ``is_sandbox`` boots true and ``CHECKOUT_PROVIDER`` is unset — so
every number these routes return is currently ``0``, and ``0`` alone cannot separate "nothing
in the range you chose" from "this has never run here". The probes are what make the empty
state a screen with a remedy rather than one that reads as broken.

**Privacy.** No route here publishes a plaintext Telegram id and none can be made to: the wire
models carry ``telegramUserIdMasked`` plus an explicit ``isBuyerErased`` and have no plaintext
field at all, and the reads are therefore ordinary record reads that write no audit row —
exactly as ``/api/orders`` does. Plaintext still costs a ``POST /api/reveal``, with its
step-up, its budget and its own row. The intent's ``idempotency_key`` never reaches a response:
it embeds the customer's Telegram id and is read here only as the join key for the receipt and
the ledger.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Annotated, Final
from uuid import UUID

from fastapi import APIRouter, Depends, Query

from bayram.admin import audit_sink, rail_switch
from bayram.admin.deps import (
    API_PREFIX,
    Admin,
    Container,
    CurrentAdmin,
    Db,
    require_permission,
)
from bayram.admin.errors import AdminErrorCode, AdminProblem, ProblemError, problem, unwrap
from bayram.admin.queue import job_id_for_payment_notification
from bayram.admin.schemas.billing import (
    AttentionView,
    CallPage,
    FaultClusterListView,
    IntentDossierView,
    IntentLookupView,
    IntentPage,
    NotifyEnqueuedView,
    NotifyRefusal,
    NotifyRequest,
    RailFunnelView,
    RailProbesView,
    RailStatusView,
    RailSwitchRequest,
    RailSwitchView,
    SettlementView,
    build_lifeline,
    notify_refusal,
    settle_command,
    to_attention_view,
    to_chain_stop_view,
    to_fault_cluster_list_view,
    to_inbound_call_view,
    to_intent_detail_view,
    to_intent_list_item_view,
    to_intent_lookup_view,
    to_ledger_entry_view,
    to_notify_eligibility_view,
    to_rail_funnel_view,
    to_rail_status_view,
    to_rail_transaction_view,
    to_receipt_view,
    to_settlement_view,
)
from bayram.admin.schemas.page import Paging, page_meta
from bayram.admin.security.permissions import Permission
from bayram.admin.window import resolve_window
from bayram.db.admin.audit import AuditEntry
from bayram.db.admin.credits import ledger_for_key
from bayram.db.admin.payme_rpc_log import (
    CallFilters,
    call_totals,
    calls_for_intent,
    count_calls,
    fault_clusters,
    has_recorded_inbound_call,
    last_inbound_call,
    list_calls,
)
from bayram.db.admin.payme_transactions import (
    has_recorded_transaction,
    transaction_funnel,
    transactions_for_intent,
)
from bayram.db.admin.payment_intents import (
    AttentionPopulation,
    IntentFilters,
    SettleSource,
    attention_counts,
    count_intents,
    has_opened_any_intent,
    has_settled_any_intent,
    idempotency_key_for,
    intent_by_id,
    intent_funnel,
    latest_checkout_seen,
    list_intents,
    resolve_intent_reference,
    settlement_snapshot,
)
from bayram.db.admin.plan_purchases import receipt_for_key as plan_receipt_for_key
from bayram.db.admin.sql import TimeWindow
from bayram.db.admin.topup_purchases import receipt_for_key as topup_receipt_for_key
from bayram.db.admin.views import IntentDetail, PaymentReceipt
from bayram.db.base import utc_now
from bayram.db.enums import AuditAction, IntentProduct, PaymentIntentState
from bayram.db.models.admin_audit import ACTOR_USERNAME_LENGTH, AuditOutcome
from bayram.errors import ErrorCode
from bayram.payme.pause import PAYME_PAUSE_KEY
from bayram.payme.rules import DEFAULT_TRANSACTION_TIMEOUT_MS

__all__ = [
    "ATTENTION_PATH",
    "BILLING_PREFIX",
    "CALLS_PATH",
    "DEFAULT_FAULT_CLUSTERS",
    "DEFAULT_STALE_AFTER_HOURS",
    "FAULTS_PATH",
    "FUNNEL_PATH",
    "INTENTS_PATH",
    "INTENT_NOTIFY_PATH",
    "INTENT_PATH",
    "LOOKUP_PATH",
    "MAX_FAULT_CLUSTERS",
    "MAX_STALE_AFTER_HOURS",
    "MIN_STALE_AFTER_HOURS",
    "PAYMENT_SUBJECT_TYPE",
    "RAIL_METRICS_PREFIX",
    "RAIL_PATH",
    "RAIL_PAUSE_PATH",
    "RAIL_RESUME_PATH",
    "RAIL_SWITCH_SUBJECT_ID",
    "RAIL_SWITCH_SUBJECT_TYPE",
    "SETTLEMENT_PATH",
    "build_billing_records_router",
    "build_payment_notify_router",
    "build_rail_control_router",
    "build_rail_router",
]

# ---------------------------------------------------------------------------
# Paths. Full and absolute, derived from one another, no ``prefix=`` on any include.
# ---------------------------------------------------------------------------
#: The rail's own state, beside ``/api/ops/pulse`` and ``/api/ops/capabilities``: the machine,
#: not a metric over it. The two switch routes hang off it so an operator reading the header
#: and the operator flipping it are looking at one noun.
RAIL_PATH: Final[str] = f"{API_PREFIX}/ops/rail"
RAIL_PAUSE_PATH: Final[str] = f"{RAIL_PATH}/pause"
RAIL_RESUME_PATH: Final[str] = f"{RAIL_PATH}/resume"

#: Aggregates over the rail, beside the dashboard's own ``/api/metrics/*`` sections.
RAIL_METRICS_PREFIX: Final[str] = f"{API_PREFIX}/metrics/rail"
SETTLEMENT_PATH: Final[str] = f"{RAIL_METRICS_PREFIX}/settlement"
FUNNEL_PATH: Final[str] = f"{RAIL_METRICS_PREFIX}/funnel"
ATTENTION_PATH: Final[str] = f"{RAIL_METRICS_PREFIX}/attention"
#: Named for what it groups rather than for what it hides: this is every inbound call folded by
#: ``(method, replyCode)``, and the successes are excluded by the query rather than by the URL.
FAULTS_PATH: Final[str] = f"{RAIL_METRICS_PREFIX}/calls-by-code"

#: Individual payments and the journal that explains them.
BILLING_PREFIX: Final[str] = f"{API_PREFIX}/billing"
CALLS_PATH: Final[str] = f"{BILLING_PREFIX}/calls"
LOOKUP_PATH: Final[str] = f"{BILLING_PREFIX}/lookup"
INTENTS_PATH: Final[str] = f"{BILLING_PREFIX}/intents"
#: ONE identifier name for the whole ``billing`` namespace, typed ``UUID`` so a malformed id is
#: a 422 from FastAPI rather than a query that runs
#: (``test_every_path_parameter_is_typed``). The rail-facing ``public_ref`` is deliberately NOT
#: the URL key: it is the string the customer and Payme both hold, and pinning a route to it
#: would make the panel's URLs the same namespace as the rail's. It is a query parameter on
#: :data:`LOOKUP_PATH` instead, which is also where it can be refused for shape.
INTENT_PATH: Final[str] = f"{INTENTS_PATH}/{{intent_id}}"
INTENT_NOTIFY_PATH: Final[str] = f"{INTENT_PATH}/notify"

#: ``admin_audit_log.subject_type`` for the two switch actions. ``"config"`` from the closed
#: vocabulary, because the switch IS configuration — it is a key an operator sets and a process
#: reads — and because filing it under a type of its own would add a member with one user.
RAIL_SWITCH_SUBJECT_TYPE: Final[str] = "config"
#: The switch's subject id. A constant rather than the Redis key itself: ``bayram:payme:paused``
#: would also match ``_SUBJECT_ID_PATTERN``, but the audit log's subject is the SWITCH and not
#: the storage it happens to live in today, and a durable flag would move the key without
#: moving the thing operators paused.
RAIL_SWITCH_SUBJECT_ID: Final[str] = "payme_rail"

#: ``admin_audit_log.subject_type`` for a notify. The vocabulary member ``db/admin/audit.py``
#: added for exactly this: a payment is not an order, not a user and not a config, and filing it
#: as its own type keeps "everything anyone did to this payment" an indexed equality on
#: ``(subject_type, subject_id)``.
PAYMENT_SUBJECT_TYPE: Final[str] = "payment"

#: How long a rail-side transaction may sit in ``created`` before the board calls it stuck.
#: DERIVED from the rail's own default timeout rather than picked: twelve hours is what
#: ``bayram.payme.rules`` will cancel a transaction at, so a shorter default would list payments
#: the system has not given up on and a longer one would hide payments it already has.
DEFAULT_STALE_AFTER_HOURS: Final[int] = DEFAULT_TRANSACTION_TIMEOUT_MS // (60 * 60 * 1_000)
#: One hour is the shortest window in which "stuck" means anything; a week is the longest over
#: which the answer is still a work queue rather than a history. Out of range is a 422 naming
#: the parameter and never a silent clamp — a clamped value answers a different question with
#: no way for the caller to notice.
MIN_STALE_AFTER_HOURS: Final[int] = 1
MAX_STALE_AFTER_HOURS: Final[int] = 24 * 7

#: How many fault clusters the board draws. Twenty is more rows than an incident has distinct
#: shapes; fifty is the ceiling, and past it the answer is the paged journal rather than a wider
#: summary.
DEFAULT_FAULT_CLUSTERS: Final[int] = 20
MAX_FAULT_CLUSTERS: Final[int] = 50

#: ``secrets.token_hex(12)``: exactly 24 lowercase hex characters, and the alphabet is load-
#: bearing rather than cosmetic — a ``;`` truncates a Payme checkout-link value and an ``=``
#: terminates a key, so ``0-9a-f`` is what makes the reference safe by construction. Refusing
#: anything else here means a typo is a 422 that names the field, which is a different screen
#: from "no payment exists under that reference".
PUBLIC_REF_PATTERN: Final[str] = r"^[0-9a-f]{24}$"
#: A Mongo ObjectId as Payme mints them: 24 hex characters, stored and compared as TEXT and
#: never parsed as a number. Case-insensitive on the way in because it is THEIR identifier and
#: an operator pastes it from THEIR cabinet.
PAYME_TRANSACTION_ID_PATTERN: Final[str] = r"^[0-9a-fA-F]{24}$"


# ---------------------------------------------------------------------------
# Dependencies: the window in three shapes, and the intents list's filter set
# ---------------------------------------------------------------------------
def build_window(
    since: Annotated[datetime | None, Query(alias="from")] = None,
    until: Annotated[datetime | None, Query(alias="to")] = None,
) -> TimeWindow | None:
    """``?from=&to=`` as a dependency, or ``None`` for the whole record.

    Three lines rather than an import of ``dashboard.build_window``, and the reason is the
    ``utc_now()`` in it: the clock is resolved from **this module's** globals, which is this
    package's uniform seam for moving time in a test
    (``monkeypatch.setattr(billing_router, "utc_now", ...)``). A shared dependency would resolve
    it from ``dashboard``'s globals instead, and a test that moved this router's clock would
    silently not move its windows.
    """
    return resolve_window(since, until, now=utc_now())


Window = Annotated[TimeWindow | None, Depends(build_window)]


@dataclass(frozen=True, slots=True)
class BoundedWindow:
    """A window whose lower bound is present, carried as a TYPE rather than as a promise.

    :class:`~bayram.db.admin.sql.TimeWindow` models ``start`` as optional because "everything up
    to Y" is a real question everywhere else on this API. The settlement identity is the one
    place it is not, and a handler that reached for ``window.start`` after a dependency had
    "already checked" would either need an ``assert`` — which does nothing under ``-O`` and is
    not how this package refuses anything — or a second copy of the refusal. So the guarantee is
    the type: :func:`build_required_window` is the only constructor and it raises rather than
    building one it cannot fill.
    """

    start: datetime
    end: datetime

    def as_time_window(self) -> TimeWindow:
        """The ordinary window, for the response's echo and for anything that takes one."""
        return TimeWindow(start=self.start, end=self.end)


def build_required_window(
    since: Annotated[datetime | None, Query(alias="from")] = None,
    until: Annotated[datetime | None, Query(alias="to")] = None,
) -> BoundedWindow:
    """The same window, **refusing** an unbounded one. Only ``/metrics/rail/settlement``.

    The reconciliation identity is a statement ABOUT A WINDOW — "in this range, performed plus
    hand-settled equals receipts written" — and "all time" is a different question. Answering it
    silently would also be expensive in the one place it is least visible: ``settled_at`` and
    ``perform_time`` are the filter columns, and a request with no lower bound scans the whole
    table on a route the board POLLS.

    So a missing or half-open lower bound is a 422 naming ``from``, in the same envelope every
    other refusal on this API uses, rather than a widening the caller cannot see.
    """
    window = resolve_window(since, until, now=utc_now())
    if window is None or window.start is None:
        raise _refuse("the settlement identity needs a lower bound; give ?from=", "from")
    return BoundedWindow(start=window.start, end=window.end)


RequiredWindow = Annotated[BoundedWindow, Depends(build_required_window)]

StaleAfterHours = Annotated[
    int, Query(alias="staleAfterHours", ge=MIN_STALE_AFTER_HOURS, le=MAX_STALE_AFTER_HOURS)
]
WithTotal = Annotated[bool, Query(alias="withTotal")]


def _refuse(message: str, parameter: str) -> ProblemError:
    """A 422 naming the parameter, through the one envelope every failure here uses."""
    return ProblemError(
        AdminProblem(
            code=ErrorCode.INVALID_INPUT, message=message, details={"parameter": parameter}
        )
    )


def build_intent_filters(
    state: Annotated[list[PaymentIntentState] | None, Query()] = None,
    product: Annotated[list[IntentProduct] | None, Query()] = None,
    settled_by: Annotated[SettleSource | None, Query(alias="settledBy")] = None,
    attention: Annotated[AttentionPopulation | None, Query()] = None,
    sandbox: Annotated[bool | None, Query()] = None,
    since: Annotated[datetime | None, Query(alias="from")] = None,
    until: Annotated[datetime | None, Query(alias="to")] = None,
    stale_after_hours: StaleAfterHours = DEFAULT_STALE_AFTER_HOURS,
) -> IntentFilters:
    """§6.5's filter shape for payments, as one dependency so the handlers stay straight lines.

    Repeated ``state`` and ``product`` parameters are OR within the field and AND across fields
    (§6.1), and both are typed as their enums so an unknown value is a 422 from FastAPI rather
    than a filter that quietly matches nothing.

    ``?attention=`` is the board's three chips as a filter, and it exists so a chip and the list
    it links to cannot compute one population two ways: the same module-private predicate backs
    ``attention_counts`` and ``list_intents``, so a chip reading "4 stuck" and a list showing
    three of them is impossible rather than unlikely.

    **``?staleAfterHours=`` is read only when ``attention=awaiting_stale``**, and it is here —
    rather than defaulted inside the query layer — for the same reason: the board's attention
    card takes the parameter, so a chip that carries it through produces byte-identical
    populations on both screens. It is bounded twice, here and in ``IntentFilters``, which is
    the standing pairing (``page_params`` does it too): the boundary makes an out-of-range value
    a 422 naming the parameter, and the data layer is the backstop for callers that did not
    arrive over HTTP.

    ``now`` is read **once** for both the window's open upper bound and the staleness cutoff, so
    a request cannot narrow "today" against one instant and decide what is stuck against
    another.
    """
    now = utc_now()
    return IntentFilters(
        states=tuple(state or ()),
        products=tuple(product or ()),
        settled_by=settled_by,
        attention=attention,
        is_sandbox=sandbox,
        window=resolve_window(since, until, now=now),
        now=now,
        stale_after=timedelta(hours=stale_after_hours),
    )


IntentQuery = Annotated[IntentFilters, Depends(build_intent_filters)]


def build_call_filters(
    method: Annotated[list[str] | None, Query()] = None,
    faults_only: Annotated[bool, Query(alias="faultsOnly")] = False,
    ref: Annotated[str | None, Query(pattern=PUBLIC_REF_PATTERN)] = None,
    transaction_id: Annotated[
        str | None, Query(alias="transactionId", pattern=PAYME_TRANSACTION_ID_PATTERN)
    ] = None,
    since: Annotated[datetime | None, Query(alias="from")] = None,
    until: Annotated[datetime | None, Query(alias="to")] = None,
) -> CallFilters:
    """The journal's filter set.

    ``method`` is a plain ``str`` and NOT an enum, which is the one place this API accepts a
    free-text filter value on purpose: ``payme_rpc_log.method`` records an UNKNOWN method
    deliberately — a closed type would have raised on the way in and lost exactly the row an
    incident needs — so a filter that could not name one would be unable to find it.

    An empty ``method`` list means NO filter and never "match none"; that asymmetry belongs to
    ``apply_in`` and is what stops an unticked box rendering an empty journal an operator would
    read as an outage.
    """
    return CallFilters(
        methods=tuple(method or ()),
        faults_only=faults_only,
        public_ref=ref,
        payme_transaction_id=transaction_id,
        window=resolve_window(since, until, now=utc_now()),
    )


CallQuery = Annotated[CallFilters, Depends(build_call_filters)]


# ---------------------------------------------------------------------------
# The board: six aggregate reads on DASHBOARD_READ
# ---------------------------------------------------------------------------
def build_rail_router() -> APIRouter:
    """The rail's own state and the aggregates over it. One permission, declared once."""
    router = APIRouter(
        tags=["billing"],
        dependencies=[Depends(require_permission(Permission.DASHBOARD_READ))],
    )

    @router.get(RAIL_PATH)
    async def rail_status(db: Db, container: Container) -> RailStatusView:
        """Is this machine armed, and what has it heard? **No window, deliberately.**

        Every field is a current fact or a window-blind probe. Giving this route a range would
        invite the console to render "the rail is off" because somebody narrowed the picker,
        which is the one sentence this screen must never say by accident.

        **Three switches decide whether the rail sells and this process can read exactly one.**
        ``Settings.checkout_provider`` is loaded from the BOT's env file and
        ``PaymeSettings.payme_enabled`` from the gateway's own ``/etc/bayram/payme.env``;
        neither is on ``AdminSettings`` and neither is guessed at here. What is returned instead
        is a MEASUREMENT — ``checkoutSeen``, taken off the newest ``payment_intents`` row, which
        is what the bot actually wrote the last time it opened a checkout — and the Redis pause
        key, which this process really can read. A ``checkoutProvider`` field on
        ``AdminSettings`` was the obvious alternative and is the trap: it would read
        ``.env.admin``, a different file, and render ``stub`` with total confidence while the
        bot sold through Payme.

        ``isPaused`` comes from the SAME function the bot's checkout path calls, so the panel
        reports what the bot would see — ``False`` included, when Redis is unwell. See
        :mod:`bayram.admin.rail_switch` for why a tri-state would be worse than a guess.
        """
        return to_rail_status_view(
            seen=await latest_checkout_seen(db),
            is_paused=await rail_switch.read_pause(container),
            pause_key=PAYME_PAUSE_KEY,
            last_call=await last_inbound_call(db),
            has_opened_any_intent=await has_opened_any_intent(db),
            has_recorded_transaction=await has_recorded_transaction(db),
            has_recorded_inbound_call=await has_recorded_inbound_call(db),
            has_settled_any_intent=await has_settled_any_intent(db),
            now=utc_now(),
        )

    @router.get(SETTLEMENT_PATH)
    async def settlement(db: Db, window: RequiredWindow) -> SettlementView:
        """The reconciliation identity over a bounded window, with its verdict computed here.

        The three counts come from ``payme_sql.settlement_counts`` **unchanged**, through
        ``payment_intents.settlement_snapshot``: a second copy of that three-subquery statement
        is precisely how the panel and the five-minute sweep come to report different numbers
        about one database. The fourth — hand-settlements — is the term without which the
        identity accuses the recovery button of being a defect.

        ``hasRecordedSettlement`` is measured with the window IGNORED, and it is what stops four
        zeros rendering as a green tick. That is not hypothetical: it is the state of this
        deployment today.
        """
        return to_settlement_view(
            await settlement_snapshot(db, since=window.start, until=window.end),
            window=window.as_time_window(),
            has_recorded_settlement=await has_settled_any_intent(db),
        )

    @router.get(FUNNEL_PATH)
    async def funnel(db: Db, window: Window) -> RailFunnelView:
        """Where the window's payments got to, on both sides of the rail.

        Four reads and three probes in one response, because the console draws them as one band
        and a band assembled from four requests can show four different instants of a live
        settlement. States with no rows are ABSENT rather than zero: a zero bar is a claim about
        payments nobody attempted on a day this rail may not have been switched on.
        """
        calls, faults = await call_totals(db, window=window)
        return to_rail_funnel_view(
            window=window,
            funnel=await intent_funnel(db, window=window),
            transactions=await transaction_funnel(db, window=window),
            rpc_calls=calls,
            rpc_faults=faults,
            has_opened_any_intent=await has_opened_any_intent(db),
            has_recorded_transaction=await has_recorded_transaction(db),
            has_recorded_inbound_call=await has_recorded_inbound_call(db),
        )

    @router.get(ATTENTION_PATH)
    async def attention(
        db: Db, stale_after_hours: StaleAfterHours = DEFAULT_STALE_AFTER_HOURS
    ) -> AttentionView:
        """The three populations an operator can act on. **No window, and that is the point.**

        A payment stuck last Tuesday is still stuck today. Scoping these counts to the header's
        range would hide exactly the rows they exist to find, which is the failure mode of every
        "alerts" panel that inherits the page's date picker.

        ``now`` is read once and threaded into the query and the response, so the cutoff the
        count was taken against is the instant the response says it was.
        """
        now = utc_now()
        return to_attention_view(
            await attention_counts(db, now=now, stale_after=timedelta(hours=stale_after_hours)),
            now=now,
            stale_after_hours=stale_after_hours,
        )

    @router.get(FAULTS_PATH)
    async def calls_by_code(
        db: Db,
        window: Window,
        limit: Annotated[int, Query(ge=1, le=MAX_FAULT_CLUSTERS)] = DEFAULT_FAULT_CLUSTERS,
    ) -> FaultClusterListView:
        """Inbound calls that were answered with an error, folded by ``(method, replyCode)``.

        ``?limit=`` is bounded at the boundary and again in the query layer, the standing
        pairing; over-range is a 422 naming the parameter and never a silent clamp.

        The probe rides in the response because an empty cluster list has two meanings —
        "nothing failed in your range" and "Payme has never called this endpoint" — and only one
        of them is good news.
        """
        return to_fault_cluster_list_view(
            await fault_clusters(db, window=window, limit=limit),
            window=window,
            has_recorded_inbound_call=await has_recorded_inbound_call(db),
        )

    @router.get(CALLS_PATH)
    async def call_journal(
        db: Db, filters: CallQuery, paging: Paging, with_total: WithTotal = False
    ) -> CallPage:
        """One keyset page of the inbound journal, newest first.

        On the DASHBOARD_READ router despite its ``/api/billing`` prefix — see the module
        docstring. Nothing on this route is personal data: the table holds no Telegram id, no
        request body and no header, and ``peerIp`` is the rail's data centre.

        An empty page on a live rail is not an outage: it is also what a hand-settled payment
        looks like, because Payme never called about one.
        """
        page = await list_calls(db, filters=filters, request=paging)
        total = await count_calls(db, filters=filters) if with_total else None
        return CallPage(
            items=[to_inbound_call_view(item) for item in page.items],
            meta=page_meta(page, total),
        )

    return router


# ---------------------------------------------------------------------------
# Payments: the list, the lookup and the dossier, on RECORDS_READ
# ---------------------------------------------------------------------------
def build_billing_records_router() -> APIRouter:
    """One payment at a time. ``RECORDS_READ``, like every other record this panel lists.

    ``RECORDS_READ`` and not a cell of its own, because that is exactly what these rows are: a
    payment is a record with a masked buyer on it, in the same class as an order. Nothing here
    unmasks anything, so §12.2's ``M``-for-all-four-roles cell needs no masking branch and these
    handlers take no ``Admin`` — taking the operator in order to ignore them would imply a
    decision this namespace does not have (``routers/orders.py`` states the rule).
    """
    router = APIRouter(
        tags=["billing"],
        dependencies=[Depends(require_permission(Permission.RECORDS_READ))],
    )

    @router.get(INTENTS_PATH)
    async def list_payments(
        db: Db, filters: IntentQuery, paging: Paging, with_total: WithTotal = False
    ) -> IntentPage:
        """One keyset page of started payments, newest first, with the chain per row.

        **The capabilities ride INSIDE the envelope**, which is ``getVendorUsage``'s shape and
        not a second ``/ops/capabilities`` request: an empty page must be legible from the
        response that was empty, because the console may not make the follow-up and an operator
        certainly will not.

        There is no ``?sort=``. Every list on this API is ``ORDER BY created_at DESC, id DESC``,
        fixed; a control that sent one would be silently ignored, which is worse than a 422.
        """
        page = await list_intents(db, filters=filters, request=paging)
        total = await count_intents(db, filters=filters) if with_total else None
        return IntentPage(
            items=[to_intent_list_item_view(item) for item in page.items],
            meta=page_meta(page, total),
            capabilities=RailProbesView(
                has_opened_any_intent=await has_opened_any_intent(db),
                has_recorded_transaction=await has_recorded_transaction(db),
                has_settled_any_intent=await has_settled_any_intent(db),
            ),
        )

    @router.get(LOOKUP_PATH)
    async def lookup_payment(
        db: Db,
        ref: Annotated[str | None, Query(pattern=PUBLIC_REF_PATTERN)] = None,
        transaction_id: Annotated[
            str | None, Query(alias="transactionId", pattern=PAYME_TRANSACTION_ID_PATTERN)
        ] = None,
    ) -> IntentLookupView:
        """ "The customer read me a reference over the phone" — one round trip, honest not-found.

        **Exactly one of the two**, refused with a 422 naming both when that is not true. Both
        absent is a caller that forgot to fill the box; both present is a caller that would get
        whichever branch the query layer happens to try first, which is a silent behaviour
        nobody could debug from the answer.

        A well-formed reference that matches nothing is a **200 with two nulls**, not a 404: the
        question was answered and the answer is no. A 404 would render an error page for a
        successful search and make a typo look like a missing route. A MALFORMED reference is a
        different fact and is the 422 the patterns above produce.

        There is no ``?idempotencyKey=`` and there never will be: that string embeds the
        customer's Telegram id, so making it searchable would put a Telegram id in a URL, in a
        browser history and in an access log.
        """
        if (ref is None) == (transaction_id is None):
            raise _refuse(
                "give exactly one of ?ref= or ?transactionId=",
                "ref",
            )
        return to_intent_lookup_view(
            await resolve_intent_reference(db, public_ref=ref, payme_transaction_id=transaction_id)
        )

    @router.get(INTENT_PATH)
    async def payment_dossier(db: Db, intent_id: UUID) -> IntentDossierView:
        """Everything needed to answer "did this customer's money turn into a song?".

        **Six reads, one transaction.** ``get_db_session`` opens exactly one for the request,
        and that is the property being relied on rather than an accident: ``payme.cli._dossier``
        argues it directly — an operator has to trust that the receipt and the transaction were
        true at the same instant, and separate reads during a live settlement would show a
        performed transaction with no receipt and send somebody to open an incident about it.

        The order is ``_render_dossier``'s, because it is the order the questions get asked in:
        the intent, then what the rail did, then what we wrote, then what the customer got.

        **The receipt is read from the table the PRODUCT names**, not from both. Trying both
        would be one wasted statement per dossier and would also leave the code able to render
        two receipts for one payment — a state the unique indexes make impossible and the UI
        would then have to have an opinion about.

        **The join key is fetched, used three times and dropped**, through
        ``payment_intents.idempotency_key_for`` rather than off the view, and a function is the
        stronger shape than a field: the key is ``topup:{telegram_user_id}:{scope}:{seq}``, so
        a field on a frozen view would ride into every log line, error context and ``repr``
        that view ever appears in, while a local ``str`` is read, passed to three queries and
        goes out of scope. No wire model on this surface has a field for it, asserted by test.

        **The two ``None`` checks are one branch on purpose.** ``intent_by_id`` and
        ``idempotency_key_for`` answer the same question about the same row inside one
        transaction, so they can only disagree if the intent was deleted between them — a race,
        not a state — and the honest answer to it is the same 404 an unknown id gets. Two
        branches would be two sentences for one fact, and the second would be untestable.

        **No audit row.** The buyer is masked, exactly as on ``/api/orders``; plaintext still
        costs a ``POST /api/reveal`` with its step-up, its budget and its own row.
        """
        detail = await intent_by_id(db, intent_id=intent_id)
        key = await idempotency_key_for(db, intent_id=intent_id)
        if detail is None or key is None:
            raise _no_such_intent()
        transactions = await transactions_for_intent(db, intent_id=intent_id)
        receipt = await _receipt_for(db, detail, idempotency_key=key)
        grants = await ledger_for_key(db, idempotency_key=key)
        calls = await calls_for_intent(
            db,
            public_ref=detail.public_ref,
            payme_transaction_ids=tuple(row.payme_transaction_id for row in transactions),
        )
        return IntentDossierView(
            intent=to_intent_detail_view(detail),
            transactions=[to_rail_transaction_view(row) for row in transactions],
            receipt=None if receipt is None else to_receipt_view(receipt),
            ledger=[to_ledger_entry_view(row) for row in grants],
            calls=[to_inbound_call_view(row) for row in calls],
            lifeline=build_lifeline(
                detail, transactions=transactions, receipt=receipt, grants=grants
            ),
            chain_stop=to_chain_stop_view(detail, receipt=receipt),
            notify=to_notify_eligibility_view(detail),
            settle_command=settle_command(detail.public_ref),
        )

    return router


# ---------------------------------------------------------------------------
# The switch: pause and resume on RAIL_CONTROL
# ---------------------------------------------------------------------------
def build_rail_control_router() -> APIRouter:
    """The checkout pause switch. ``RAIL_CONTROL`` — ADMIN and OWNER, and **no step-up**.

    The full argument sits beside ``Permission.RAIL_CONTROL`` in ``security/permissions.py`` and
    is not repeated here. The four-word version: ``bayram.payme.pause``'s own docstring
    disclaims this switch as a security control, pausing stops the bot QUOTING rather than
    moving any money, an incident brake must not have a password box in front of it, and adding
    ``RAIL_CONTROL`` to ``STEP_UP_ACTIONS`` would ship a route that 403s at OWNER for ever while
    looking exactly correct.

    What it has instead: a mandatory ``reasonCode``, a two-role cell, one ``admin_audit_log`` row
    per press, and a response that re-reads the key.

    **Two routes and not one with a boolean.** Which state is being set is carried by the PATH,
    for the reason the block/unblock pair states: a single ``{"isPaused": false}`` would be a
    resume that audits as a pause, and the audit row is the only durable record of which one
    happened — Redis keeps no history at all.
    """
    router = APIRouter(
        tags=["billing"],
        dependencies=[Depends(require_permission(Permission.RAIL_CONTROL))],
    )

    @router.post(RAIL_PAUSE_PATH)
    async def pause_rail(
        body: RailSwitchRequest, db: Db, admin: Admin, container: Container
    ) -> RailSwitchView:
        """Stop the bot handing out NEW payment links. **Payments in flight are unaffected.**

        That exclusion is the whole design and is not a limitation to be tidied up later:
        refusing money the customer's bank has already moved is how an incident becomes a
        dispute, and ``CancelTransaction`` on a performed charge is ``-31007`` by design, so a
        gateway that honoured a pause would produce a payment with no receipt, no credit and no
        automatic way back.
        """
        return await _flip(
            db, admin, container, body=body, paused=True, action=AuditAction.RAIL_PAUSED
        )

    @router.post(RAIL_RESUME_PATH)
    async def resume_rail(
        body: RailSwitchRequest, db: Db, admin: Admin, container: Container
    ) -> RailSwitchView:
        """Start handing out payment links again. Idempotent, and audited whether or not it moved.

        Pressing resume on an open rail is a no-op that still writes a row, for §12.6's reason:
        the log records what operators DID, not what happened to change something, and "somebody
        checked the brake was off at 03:12" is exactly the line an incident review wants.
        """
        return await _flip(
            db, admin, container, body=body, paused=False, action=AuditAction.RAIL_RESUMED
        )

    return router


# ---------------------------------------------------------------------------
# The nudge: re-enqueue one confirmation, on PAYMENT_NOTIFY
# ---------------------------------------------------------------------------
def build_payment_notify_router() -> APIRouter:
    """Re-send one settled payment's confirmation. ``PAYMENT_NOTIFY`` — SUPPORT and above.

    A separate router from the switch because it is a separate cell, and a separate cell because
    SUPPORT is who takes the "I paid and nothing happened" call. Riding on ``RAIL_CONTROL``
    would have handed a support agent the switch that stops the business selling in exchange for
    a button that re-sends a receipt.
    """
    router = APIRouter(
        tags=["billing"],
        dependencies=[Depends(require_permission(Permission.PAYMENT_NOTIFY))],
    )

    @router.post(INTENT_NOTIFY_PATH)
    async def notify_payment(
        body: NotifyRequest, db: Db, admin: Admin, container: Container, intent_id: UUID
    ) -> NotifyEnqueuedView:
        """Ask the worker to announce a payment the customer was already owed a message about.

        **This process sends nothing.** It holds no Telegram token — that is the whole reason
        the gateway is a fourth process and the reason ``AdminSettings`` has no field for one —
        so telling a customer anything is the worker's job. What crosses this seam is a job name
        and an id.

        **The three refusals are re-checked HERE**, in ``cli._notify``'s order, because the
        console's disabled button is a courtesy and the server is the authority: an unpaid
        intent has nothing to announce, an erased buyer has nobody to announce it to, and an
        already-stamped ``notified_at`` is what the job itself stops on — so re-enqueuing would
        do nothing and reporting success would be a lie an operator acts on. All three are 409s,
        because the request is well formed and the STATE refuses it.

        **Idempotency is structural rather than promised.** The job id is deterministic on
        ``public_ref`` so ARQ collapses a double press onto one job, and ``mark_intent_notified``
        stamps only ``WHERE notified_at IS NULL`` so this enqueue and the worker's five-minute
        backstop cannot both message one person. ``isReplay`` reports which of the two happened.

        ``now`` is read once and threaded through the audit row and the response.

        **The audit row and the enqueue commit together or not at all**, which is the coupling
        this action wants rather than an accident of ordering. The row goes into the request's
        own transaction and the enqueue is the last statement, so a Redis that cannot be reached
        rolls the row back with the 503 — and a log entry saying a customer was messaged when
        nothing was ever queued is exactly the row an incident review would be misled by. It is
        the same shape ``POST /broadcasts/{id}/test-send`` takes, for the same reason. Nothing
        is lost by it either: the worker's own five-minute sweep re-enqueues every settled
        payment nobody has announced, so a refused press costs the customer minutes and not the
        message.
        """
        now = utc_now()
        detail = await intent_by_id(db, intent_id=intent_id)
        if detail is None:
            raise _no_such_intent()
        refusal = notify_refusal(detail)
        if refusal is not None:
            raise _refuse_notify(refusal, detail)
        await audit_sink.record(
            db, container, _notify_entry(admin, body=body, detail=detail), now=now
        )
        enqueued = unwrap(await container.queue.enqueue_payment_notification(detail.public_ref))
        return NotifyEnqueuedView(
            intent_id=detail.intent_id,
            public_ref=detail.public_ref,
            job_id=job_id_for_payment_notification(detail.public_ref),
            is_replay=enqueued is None,
            enqueued_at=now,
        )

    return router


# ---------------------------------------------------------------------------
# The shared bodies
# ---------------------------------------------------------------------------
def _no_such_intent() -> ProblemError:
    """404, without echoing what was asked for. An id is not a hint worth confirming."""
    return ProblemError(
        AdminProblem(code=ErrorCode.NOT_FOUND, message="no payment intent with that id")
    )


async def _receipt_for(
    db: Db, detail: IntentDetail, *, idempotency_key: str
) -> PaymentReceipt | None:
    """The sale under this intent's key, from the table its product decided at Perform time.

    ``product`` is what ``db.payme._settle`` branched on when it wrote the row, so reading the
    same column is reading the same decision rather than re-making it. A future product is a new
    member of ``IntentProduct`` and lands here as "single", which is the safe direction: it
    reports no receipt for a sale it cannot find rather than a receipt from the wrong book.

    The key is a PARAMETER and is deliberately not re-fetched here: one read per dossier, in the
    handler, is what keeps the number of places this string exists at one.
    """
    if detail.product == IntentProduct.STARTER.value:
        return await plan_receipt_for_key(db, idempotency_key=idempotency_key)
    return await topup_receipt_for_key(db, idempotency_key=idempotency_key)


async def _flip(
    db: Db,
    admin: Admin,
    container: Container,
    *,
    body: RailSwitchRequest,
    paused: bool,
    action: AuditAction,
) -> RailSwitchView:
    """Write the key, RE-READ it, then audit. Pause and resume are one shape.

    **The re-read is the point of the response existing at all.** Echoing ``paused`` back would
    tell the operator what they asked for, which they already know; reading the key through the
    same function the bot's checkout path calls tells them what the bot will now see. On a Redis
    that accepted the write and then evicted the key, those two answers differ, and the second
    is the true one.

    **The write comes first, and this is the one action here whose two halves cannot be made
    atomic.** Redis is not in the request's transaction, so one of two failures is available and
    the ordering picks which: write-then-audit can leave a flipped key with no row, and
    audit-then-write can leave a row asserting a flip that never landed. The first is chosen
    because it fails in the direction the switch can still be trusted in — the key is what the
    bot reads and what ``rail_switch.read_pause`` reports on the very next page load, so a
    missing row is discoverable, while a row claiming a pause that did not take is the precise
    incident ``pause.set_paused`` raises to prevent. A failed WRITE therefore changes nothing
    and audits nothing: ``unwrap`` makes it a 503 before any row is appended.

    ``now`` is read once and is both the audit row's instant and the response's ``changedAt``.
    """
    now = utc_now()
    unwrap(await rail_switch.write_pause(container, paused=paused))
    is_paused = await rail_switch.read_pause(container)
    await audit_sink.record(db, container, _switch_entry(admin, body=body, action=action), now=now)
    return RailSwitchView(is_paused=is_paused, pause_key=PAYME_PAUSE_KEY, changed_at=now)


def _switch_entry(
    admin: CurrentAdmin, *, body: RailSwitchRequest, action: AuditAction
) -> AuditEntry:
    """One ``rail.paused`` / ``rail.resumed`` row.

    ``subject_type="config"`` with a constant ``subject_id``: there is exactly one such switch
    per deployment, so "every time anybody touched the rail switch" is an indexed equality
    rather than a scan for two action values.

    There is no ``field_names``: the column vocabulary names DATABASE columns
    (``^[a-z][a-z0-9_.]{0,63}$``, checked at the audit boundary), and what moved here is a Redis
    key that no column corresponds to. Naming one would be a shape the log could not honour.
    ``record_count`` is likewise absent — this action moves no records.
    """
    return AuditEntry(
        action=action,
        actor_id=admin.admin_user_id,
        actor_username=admin.username[:ACTOR_USERNAME_LENGTH],
        actor_role=admin.role,
        subject_type=RAIL_SWITCH_SUBJECT_TYPE,
        subject_id=RAIL_SWITCH_SUBJECT_ID,
        reason_code=body.reason_code,
        reason_ref=body.reason_ref,
        reason_text=body.reason_text,
        outcome=AuditOutcome.OK,
        ip=admin.client_ip,
    )


def _notify_entry(admin: CurrentAdmin, *, body: NotifyRequest, detail: IntentDetail) -> AuditEntry:
    """One ``payment.notify`` row, about one payment.

    ``subject_id`` is ``str(intent_id)`` — a 36-character UUID — and the choice matters more
    than it looks. ``public_ref`` is 24 characters of ``[0-9a-f]``, which ``_SUBJECT_ID_PATTERN``
    accepts but which sits inside ``audit._CREDENTIAL_SHAPES``' hunt for opaque tokens; a dashed
    UUID is neither 64 hex nor an unbroken 40-character run, so it survives the boundary intact.
    A refused value is not an error an operator would see — ``audit_sink._append`` logs it and
    rewrites the row with ``subject_id=None`` — so the failure mode is an audit trail that
    quietly stopped naming which payment it was about. ``idempotency_key`` is not a candidate at
    all: it contains the customer's Telegram id.

    ``record_count=1``: one customer was messaged, which is the same reading
    ``BROADCAST_TEST`` gives the number.
    """
    return AuditEntry(
        action=AuditAction.PAYMENT_NOTIFY,
        actor_id=admin.admin_user_id,
        actor_username=admin.username[:ACTOR_USERNAME_LENGTH],
        actor_role=admin.role,
        subject_type=PAYMENT_SUBJECT_TYPE,
        subject_id=str(detail.intent_id),
        record_count=1,
        reason_code=body.reason_code,
        reason_ref=body.reason_ref,
        reason_text=body.reason_text,
        outcome=AuditOutcome.OK,
        ip=admin.client_ip,
    )


#: The refusal each :class:`~bayram.admin.schemas.billing.NotifyRefusal` becomes on the wire. The
#: message is the CLI's, shortened: an operator who has read one of these in a terminal must
#: recognise it in the panel, because they are the same refusal about the same row.
_NOTIFY_REFUSALS: Final[dict[NotifyRefusal, str]] = {
    NotifyRefusal.NOT_PAID: (
        "this payment is not paid, so there is nothing to tell the customer yet"
    ),
    NotifyRefusal.BUYER_ERASED: (
        "the buyer's account has been erased, so there is nobody left to send it to; "
        "the receipt and the credit are untouched"
    ),
    NotifyRefusal.ALREADY_NOTIFIED: (
        "this payment was already announced, and the job stops on that stamp, so "
        "re-enqueuing it would do nothing"
    ),
}


def _refuse_notify(refusal: NotifyRefusal, detail: IntentDetail) -> ProblemError:
    """409, naming which of the three refusals it is so the console can render its own copy.

    ``CONFLICT`` and not ``INVALID_INPUT``: the request is well formed and it is the payment's
    STATE that refuses it, which is a different remedy — wait, or look at a different payment,
    rather than fix your request.

    ``refusalCode`` travels beside the message because the console is trilingual and renders the
    sentence from its own locale files; the message is for the log and for a client that has no
    string for a code this deployment added.
    """
    return problem(
        AdminErrorCode.CONFLICT,
        _NOTIFY_REFUSALS[refusal],
        refusalCode=str(refusal),
        state=detail.state,
    )
