"""Frozen view models the admin read layer returns. No session, no I/O, no clock.

These exist because ``bayram.db.mapping`` cannot serve the admin panel and must not be made
to. ``to_order`` raises ``PipelineError`` the moment ``recipient_name_display IS NULL``
(``mapping.py:137-147``), which is precisely the state a lawfully identity-purged order is
in. That is the right answer for the *pipeline* — a renderer must not invent a placeholder
name — and the wrong answer for an *operator console*, where "this order's identity was
erased on schedule" is a fact to display, not a page to fail.

So the rule for this whole package, stated once here:

**A purge is a first-class state on the view model, never an error.** Every field the purge
nulls is ``| None`` on the view, and the timestamp that proves the purge ran
(``identity_purged_at``, ``note_purged_at``, ``text_purged_at``) travels beside it. A list
page containing one purged order returns that page.

Two further rules the shapes below encode:

* **Free text is a length, not a value.** ``briefs.note``, ``briefs.approved_lyrics`` and
  ``generation_attempts.stt_transcript`` are the customer's own words about a real third
  party. §6.7 routes their plaintext through ``POST /reveal`` alone — audited, budgeted and
  step-up gated — so the shapes here carry ``*_chars`` counts and ``has_*`` flags instead.
  The recipient's *display name* is the exception, and a deliberate one: it is the handle
  an operator searches and reads, and §6.5 already routes it through the masking serializer.
* **Absent instrumentation is ``None``, never ``0``.** ``generation_attempts.cost_usd`` is
  always ``0.0`` and ``latency_ms`` always ``0`` in production today: the only writer is
  ``repository._replace_verdicts`` via ``attempts.verdict_row_values``, which sets neither,
  and ``GenerationAttemptRepository.record()`` has no call site in ``src/``. Rendering
  "$0.00" from that would be a confident lie about money. :class:`CostTelemetry` reports
  ``None`` and says why.

Plain frozen dataclasses rather than pydantic models: nothing here is parsed from untrusted
text, so validation would buy nothing, and the admin API's own response schemas
(``src/bayram/admin/schemas``) are the layer that owns the wire shape.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from enum import StrEnum
from typing import Any
from uuid import UUID

from bayram.contracts import (
    AssetKind,
    BalanceEstimateBasis,
    BalanceUnit,
    BroadcastKind,
    BroadcastRecipientState,
    BroadcastState,
    CostSource,
    Genre,
    Language,
    NameStrategy,
    Occasion,
    OrderState,
    Script,
    Vendor,
    VendorOperation,
    VoiceGender,
)
from bayram.db.enums import AuditReasonCode, CreditEntryKind, CreditReason, GenerationKind, PlanKind
from bayram.db.retention import RetentionClass

__all__ = [
    "CostTelemetry",
    "BriefView",
    "AssetView",
    "AttemptView",
    "OrderLedgerStatus",
    "OrderPaymentRail",
    "OrderLedger",
    "OrderStateTotal",
    "OrderListItem",
    "OrderDetail",
    "TimelineSource",
    "TimelineEventKind",
    "TimelineEvent",
    "Timeline",
    "UserListItem",
    "UserDetail",
    "SegmentBreakdown",
    # -- broadcasts: the campaign, its bodies, and the ledger of who it reached ---
    "BroadcastProgress",
    "BroadcastListItem",
    "BroadcastBodyView",
    "BroadcastDetail",
    "BroadcastRecipientItem",
    "CreditAccountState",
    "CreditLedgerItem",
    "OrdersPerDay",
    "DeliveryOutcome",
    "LatencySummary",
    "FailureCount",
    "StrategyOutcome",
    "SimilarityBucket",
    "StrategyAnalysis",
    "NameAnalytics",
    "VendorUsageRollup",
    "VendorUsageTotals",
    "VendorUsagePerDay",
    "VendorErrorCount",
    "ReadCapabilities",
    # -- the dashboard's aggregate shapes ---
    "Trend",
    "BucketPoint",
    "DeliveredPerBucket",
    "NewAccountsPerBucket",
    "AccountTotals",
    "ActiveAccounts",
    "ChurnCounts",
    "OrderFunnel",
    "RevenueSource",
    "RevenueBucket",
    "RevenueTotal",
    "CurrencyAmount",
    "PlanLiability",
    "PlanUtilisationBucket",
    "UnpricedTopups",
    "VendorSpendPerBucket",
    "VendorSpendSplit",
    "CostPerDeliveredSong",
    "UnattributedSpendPerBucket",
    "OperationLatency",
    "FakeCallGuard",
    "VendorBalanceState",
    # -- renewal, audience, unit economics, provenance ---
    "SubscriptionChurn",
    "LanguageMix",
    "LanguageMixTotals",
    "ActivityPoint",
    "TopGenerator",
    "RecentSubscriber",
    "VendorCostPerSong",
    "VendorUnitsPerSong",
    "CostProvenance",
    # -- the redirect payment rail: what it is armed with, what it heard, what it owes ---
    "CheckoutSeen",
    "IntentStateCount",
    "IntentFunnel",
    "SettlementSnapshot",
    "AttentionCounts",
    "IntentListItem",
    "IntentDetail",
    "IntentReferenceMatch",
    "RailStateCount",
    "RailTransaction",
    "InboundCall",
    "FaultCluster",
    "PaymentReceipt",
    "PaymentGrant",
]


# ---------------------------------------------------------------------------
# Telemetry — the honest answer to "what did this cost?"
# ---------------------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class CostTelemetry:
    """Cost and latency for one attempt, or an explicit statement that neither was measured.

    ``is_instrumented`` is derived per row rather than assumed for the table, because the
    day Phase 5 starts writing real numbers the old rows must keep reading as "unknown"
    rather than silently joining the average at zero.
    """

    cost_usd: float | None
    cost_source: CostSource | None
    latency_ms: int | None

    @property
    def is_instrumented(self) -> bool:
        """False when this row predates instrumentation, so the UI can say so."""
        return self.cost_usd is not None or self.latency_ms is not None


# ---------------------------------------------------------------------------
# Brief, asset, attempt
# ---------------------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class BriefView:
    """One brief, readable at every stage of its two independent retention clocks."""

    id: UUID
    occasion: Occasion
    genre: Genre
    vocal_gender: VoiceGender
    ui_language: Language
    output_language: Language
    event_day: int | None
    event_month: int | None

    #: ``None`` once the 90-day identity sweep has run. The masked serializer, not this
    #: layer, decides how much of it a VIEWER sees.
    recipient_name_display: str | None
    recipient_script: Script | None
    recipient_language: Language | None
    #: How many ranked orthographies were stored. The texts themselves are vendor input,
    #: never rendered to a human, so only the count crosses this boundary.
    candidate_count: int
    identity_expires_at: datetime
    identity_purged_at: datetime | None

    #: Length of ``briefs.note``. The note itself is reachable only through ``POST /reveal``.
    note_chars: int | None
    has_approved_lyrics: bool
    note_expires_at: datetime
    note_purged_at: datetime | None

    @property
    def is_identity_purged(self) -> bool:
        """Mirrors ``BriefRow.is_identity_purged``: the audit column is the only proof.

        A null display name is no longer evidence of a purge — an order from the
        bring-your-own-lyrics path never had a name — and reporting one as purged would tell
        an operator that personal data was erased on schedule when none was ever held.
        """
        return self.identity_purged_at is not None

    @property
    def is_note_purged(self) -> bool:
        return self.note_purged_at is not None


@dataclass(frozen=True, slots=True)
class AssetView:
    """Metadata for one delivered file. Never its bytes, never its lyric payload."""

    id: UUID
    order_id: UUID
    kind: AssetKind
    variant_index: int
    mime: str
    size_bytes: int
    duration_s: float
    sha256: str
    loudness_lufs: float | None
    persona_id: str | None
    #: ``None`` for every asset written before ``_replace_assets`` started recording it
    #: (§5.11). The retention sweep cannot delete archived bytes it has no key for, so the
    #: absence is operationally load-bearing and is surfaced rather than hidden.
    storage_key: str | None
    has_telegram_file_id: bool
    name_candidate_strategy: NameStrategy | None
    name_candidate_rank: int | None
    retention_class: RetentionClass
    expires_at: datetime
    created_at: datetime


@dataclass(frozen=True, slots=True)
class AttemptView:
    """One row of the render ledger, purge-aware and honest about instrumentation."""

    id: UUID
    #: ``None`` for a name preview made before any order existed, and for an attempt whose
    #: order was deleted — the FK is ``ON DELETE SET NULL`` so tuning data outlives orders.
    order_id: UUID | None
    kind: GenerationKind
    sequence: int
    attempt: int
    provider: str | None
    provider_remote_id: str | None
    language: Language | None
    is_success: bool

    # -- tuning signal: never purged --------------------------------------
    name_candidate_strategy: NameStrategy | None
    name_candidate_rank: int | None
    is_name_verified: bool | None
    match_confidence: float | None

    # -- personal data: nulled on its own clock ---------------------------
    name_candidate_text: str | None
    identity_purged_at: datetime | None
    #: Length only. The transcript is a near-verbatim copy of the whole song.
    stt_transcript_chars: int | None
    text_purged_at: datetime | None

    error_code: str | None
    error_message: str | None
    telemetry: CostTelemetry
    created_at: datetime

    @property
    def is_orphaned(self) -> bool:
        """True for an attempt with no surviving order — the ``isOrphaned`` filter's meaning."""
        return self.order_id is None


# ---------------------------------------------------------------------------
# Orders — and the ledger algebra that decides what an order cost
# ---------------------------------------------------------------------------
class OrderLedgerStatus(StrEnum):
    """Where one order stands in ``credit_ledger``, in the algebra the gate itself uses.

    Every member is defined against exactly three numbers, all of them taken over
    ``credit_ledger WHERE order_id = orders.id``: ``net = SUM(delta)``, the count of
    ``REFUND`` rows and the count of ``CONSUME`` rows. Prose definitions were the alternative
    and they are how this field would drift from the authorisation decision: ``charge`` reads
    ``net_position`` (``db/credit_sql.py``) and nothing else, so a status derived from
    anything else would eventually disagree with whether the customer is about to be charged
    again.

    * :attr:`PENDING` — ``net < 0`` and no ``CONSUME``. A debit stands open: the render is in
      flight, or it died without settling and the hourly sweep has not reached it yet. This
      is the state that holds an in-flight slot the customer cannot see.
    * :attr:`SETTLED` — ``net < 0`` and at least one ``CONSUME``. The charge stands and was
      closed: the kit exists (``ORDER_DELIVERED``), or exists and Telegram refused it
      (``ORDER_NOT_DELIVERED``), or the sweep closed a delivered order's debit
      (``STALE_SETTLEMENT``). The customer paid and keeps paying.
    * :attr:`REFUNDED` — ``net >= 0`` and at least one ``REFUND``. The debit was handed back,
      which returns the order to net 0 — and net 0 is precisely what makes it **chargeable
      again**, at ``generation + 1``, on its next authorisation. A refunded order is not a
      closed one, and the panel must not draw it as an ending.
    * :attr:`UNMETERED` — everything else: ``net >= 0`` with no refund, which in practice
      means the ledger holds no row for this order at all.

    :attr:`UNMETERED` is a fourth member where ``ADMIN_PANEL_AUDIT_AND_REDESIGN_PLAN.md``
    §5.1 named three (``settled`` / ``refunded`` / ``pending``), and it is the state most
    orders in this deployment are actually in: a DRAFT that never reached authorisation has
    no ledger row, and neither does anything created before the meter existed. Folding it
    into ``pending`` would tell an operator a credit is held against an order that holds
    none; folding it into ``settled`` would invent a sale. It is a real fourth state, so it
    is named.
    """

    UNMETERED = "unmetered"
    PENDING = "pending"
    SETTLED = "settled"
    REFUNDED = "refunded"


class OrderPaymentRail(StrEnum):
    """What paid for one order — restricted to what this schema can actually prove.

    §5.1 of the audit plan names ``telegram_stars``, ``credit_allowance`` and ``admin_grant``.
    Two of those three are **not derivable here and are deliberately absent**, because a
    value the data cannot support is worse than a missing field: an operator reading
    ``admin_grant`` off a screen would act on it.

    * ``telegram_stars`` has no writer anywhere in ``src/``. There is no ``payments`` table
      (``db.admin.sql.PAYMENTS_TABLE`` is what the timeline reports as unavailable for
      exactly this reason) and ``CreditReason`` has no member a payment rail could write.
      ``orders.is_paid`` is not it either: it latches when the order reaches ``AUTHORIZED``,
      whichever provider produced that, so it says *authorised*, never *by whom*.
    * ``credit_allowance`` versus ``admin_grant`` cannot be told apart **by construction**,
      not merely for want of a column. ``credit_accounts.balance`` is fungible: a debit spends
      the balance, and the balance does not record which grant minted the credit it is
      spending. An account holding one allowance credit and one comped credit that renders
      one song produces exactly one ``DEBIT``/``ORDER_RENDER`` row, and no query over this
      schema can say which of the two it consumed. Recovering it would take a lot-tracked
      ledger (FIFO consumption linking each debit to the grants it draws down), which is a
      schema decision and not a read-layer one.

    What is left is real, and the third member is the one an operator actually asks for:

    * :attr:`CREDITS` — a charge stands or stood against this order in the ledger. The
      customer's own balance paid for the render.
    * :attr:`UNENFORCED` — ``Settings.credits_enforced`` was off and the account could not
      afford the render, so ``credits._cover_the_shortfall`` minted exactly what it cost.
      Nobody paid; a configuration flag did. This is the "was it comped?" the audit document
      asks for, and it is the closest thing to ``admin_grant`` that the ledger can prove,
      because that grant is the only one keyed to a specific render.
    * :attr:`NONE` — no ledger row references this order and no top-up was written for it.
      An unmetered order, not a free one: the difference matters for a DRAFT that simply
      never got as far as being charged.

    Note that :attr:`CREDITS` and :attr:`NONE` carry no information
    :class:`OrderLedgerStatus` does not already carry — with one charging reason in the enum,
    "which rail" collapses into "was there a charge at all". The rail is a separate field
    only because :attr:`UNENFORCED` is genuinely orthogonal to it: a dark render is charged
    *and* comped, and the status alone would show it as an ordinary sale.
    """

    NONE = "none"
    CREDITS = "credits"
    UNENFORCED = "unenforced"


@dataclass(frozen=True, slots=True)
class OrderLedger:
    """One order's position in ``credit_ledger``: three scalars from one statement, plus a flag.

    A value object rather than four loose parameters on :func:`~bayram.db.admin.orders.
    order_list_item`, so that adding a fifth aggregate is a field on a type the type checker
    walks rather than a positional argument every call site has to get in the right order.

    **``is_unenforced`` does not come from the same statement as the other three**, and the
    distinction is worth keeping in this docstring rather than discovering in a query plan:
    :attr:`net`, :attr:`refund_count` and :attr:`consume_count` are correlated subqueries on
    the page's own SELECT, while the comp flag arrives from :func:`~bayram.db.admin.orders.
    _unenforced_orders`, a second round trip that matches idempotency-key prefixes in Python
    for the dialect reason that function's module docstring gives.

    Every field is total: an order with no ledger rows at all is ``net=0`` with two zero
    counts and ``is_unenforced=False``, which is what a ``COALESCE``-ed ``SUM``, two
    ``COUNT``s and an absent key return for an empty set without anybody writing a branch.
    """

    #: ``SUM(delta)``. Zero for an unmetered order; negative while a debit stands; back to
    #: zero once it is refunded. This is the exact expression ``credit_sql.net_position``
    #: computes for the authorisation gate.
    net: int
    refund_count: int
    consume_count: int
    #: Whether ``credits._cover_the_shortfall`` wrote a top-up for this render. It is found
    #: by the idempotency key rather than by ``order_id`` because that grant deliberately
    #: carries no ``order_id`` — see :func:`bayram.db.credits.unenforced_key_prefix`.
    is_unenforced: bool

    @property
    def credit_cost(self) -> int:
        """Credits standing against this order right now — ``-net``, never a sum of debits.

        A "sum of the DEBIT rows" is the obvious spelling and it misreports every refunded
        order: debit ``-1`` then refund ``+1`` sums to a cost of 1 for an order the customer
        was given their credit back for, and if that order is then re-authorised it debits
        again at ``generation + 1`` and the naive number reads 2. ``-net`` is what the gate
        reads, so this field and the charge decision cannot disagree.

        Negative is arithmetically possible (more refunded than ever debited) and nothing in
        the schema forbids it; there is no writer that can produce it, and clamping it to
        zero would hide the day one appears.
        """
        return -self.net

    @property
    def status(self) -> OrderLedgerStatus:
        """The three-predicate decision :class:`OrderLedgerStatus` documents. Total by shape."""
        if self.net < 0:
            return (
                OrderLedgerStatus.SETTLED if self.consume_count > 0 else OrderLedgerStatus.PENDING
            )
        if self.refund_count > 0:
            return OrderLedgerStatus.REFUNDED
        return OrderLedgerStatus.UNMETERED

    @property
    def payment_rail(self) -> OrderPaymentRail:
        """Which rail, with the dark-switch top-up winning over the ordinary charge.

        A dark render writes BOTH rows — the top-up grant and then the debit it funds — so
        precedence is the whole content of this function. Reporting ``CREDITS`` for it would
        be true about the mechanism and false about the fact an operator is after: the
        customer's balance did not pay, it was topped up to the exact cost first.
        """
        if self.is_unenforced:
            return OrderPaymentRail.UNENFORCED
        if self.status is OrderLedgerStatus.UNMETERED:
            return OrderPaymentRail.NONE
        return OrderPaymentRail.CREDITS


@dataclass(frozen=True, slots=True)
class OrderStateTotal:
    """One state and how many orders in the CURRENT FILTER SET are in it.

    Deliberately **zero-filled**: every member of ``OrderState`` appears, in declaration
    order, whether or not it matched. That is the opposite contract from
    :attr:`UserDetail.orders_by_state`, which omits states with no orders — and the two are
    separate types rather than one shared model precisely because of it. This one draws a
    stacked distribution bar, where a missing segment and a zero segment must render
    identically or the bar's geometry changes as data arrives; that one answers "what has
    this person done", where a zero-filled list of eight states would bury the two they
    actually reached.
    """

    state: OrderState
    count: int


@dataclass(frozen=True, slots=True)
class OrderListItem:
    """One row of ``/orders``.

    ``recipient_name_display`` and ``identity_purged_at`` are the pair that makes an
    identity-purged order renderable: the name is gone, the proof that it was erased on
    schedule is not.
    """

    id: UUID
    telegram_user_id: int
    state: OrderState
    is_paid: bool
    correlation_id: str
    created_at: datetime
    updated_at: datetime
    delivered_at: datetime | None
    #: Operator triage text from a closed vocabulary. Never customer text — see the rule in
    #: ``SqlKitRepository._set_order_state``.
    failed_reason: str | None

    #: ``False`` only for an order whose brief row is genuinely absent (a ``DRAFT`` that
    #: never got one, or a hard delete). Distinct from "the brief is there but purged".
    is_brief_present: bool
    recipient_name_display: str | None
    identity_purged_at: datetime | None
    note_purged_at: datetime | None
    occasion: Occasion | None
    genre: Genre | None
    output_language: Language | None
    asset_count: int
    #: This order's position in ``credit_ledger``. Always present — an unmetered order gets
    #: the all-zero ledger rather than ``None``, because "no rows" is a position and every
    #: derived field below is defined for it.
    ledger: OrderLedger
    #: Rows in ``generation_attempts`` for this order. **Not renders.** No vendor-render
    #: attempt writer exists in ``src/`` — ``GenerationAttemptRepository.record()`` has no
    #: call site, and ``repository._replace_verdicts`` writes only ``NAME_VERIFICATION``
    #: verdicts — so today this counts acoustic name checks and nothing else. A delivered
    #: order can therefore report ``0`` while three songs were rendered for it.
    #: ``bayram.admin.schemas.orders.OrderView.retry_count`` carries the same warning to the
    #: layer that names the field on the wire.
    attempt_count: int

    @property
    def is_identity_purged(self) -> bool:
        """True when a brief exists and the purge job has stamped it.

        See ``BriefView.is_identity_purged`` for why the null display name is no longer
        part of the test.
        """
        return self.is_brief_present and self.identity_purged_at is not None

    @property
    def has_assets(self) -> bool:
        return self.asset_count > 0


class TimelineSource(StrEnum):
    """Where a timeline event came from. View-only — never persisted, never a column type."""

    #: Derived from the four timestamps ``orders`` actually has. There is no order-event
    #: table, so every ``ORDER`` event is inferred rather than recorded.
    ORDER = "order"
    ATTEMPTS = "attempts"
    ASSETS = "assets"
    #: Reserved so the SPA can render "not enabled in this deployment" rather than an empty
    #: section. Phase 3 gives ``CHAT`` rows, Phase 5 gives ``PAYMENTS``.
    CHAT = "chat"
    PAYMENTS = "payments"
    AUDIT = "audit"


class TimelineEventKind(StrEnum):
    """What happened. A closed vocabulary — no free text ever reaches a timeline label."""

    ORDER_CREATED = "order_created"
    BRIEF_RECORDED = "brief_recorded"
    ATTEMPT_SUCCEEDED = "attempt_succeeded"
    ATTEMPT_FAILED = "attempt_failed"
    ASSET_STORED = "asset_stored"
    ORDER_DELIVERED = "order_delivered"
    ORDER_FAILED = "order_failed"
    ORDER_LAST_TOUCHED = "order_last_touched"


@dataclass(frozen=True, slots=True)
class TimelineEvent:
    """One point on the merged order timeline."""

    at: datetime
    kind: TimelineEventKind
    source: TimelineSource
    #: True when the event is deduced from a mutable timestamp rather than read from an
    #: append-only record. ``updated_at`` moves; a state-transition log would not.
    is_inferred: bool
    #: A closed-vocabulary label — an enum value, a provider name or an error code.
    label: str | None
    reference_id: UUID | None


@dataclass(frozen=True, slots=True)
class Timeline:
    """The merged, time-ordered event list plus what this deployment could contribute."""

    events: tuple[TimelineEvent, ...]
    #: Sources that actually produced rows or could have.
    available_sources: tuple[TimelineSource, ...]
    #: Sources the SPA should render as "not enabled here" rather than as "nothing happened".
    unavailable_sources: tuple[TimelineSource, ...]


@dataclass(frozen=True, slots=True)
class OrderDetail:
    """Everything ``/orders/{id}`` renders, assembled without touching ``to_order``."""

    order: OrderListItem
    brief: BriefView | None
    assets: tuple[AssetView, ...]
    attempts: tuple[AttemptView, ...]
    timeline: Timeline


# ---------------------------------------------------------------------------
# Users
# ---------------------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class UserListItem:
    """One row of ``/users``, named for what the data can actually prove.

    **There are three writers of ``users``, and none of them is an order alone.**
    ``users_sql.ensure_user`` is called from ``repository._create_order`` (an order was
    placed) and from ``SqlUserProfiles.record_language`` (somebody answered the very first
    question the bot asks); ``credits.touch`` (``db/credits.py``) upserts the row on
    every inbound update, driven by ``gate.TouchDrain`` and wired in production at
    ``main.py``; and ``credits.set_blocked`` (``db/credits.py``) upserts it so an
    operator can bar an account that never ordered. So ``account_created_at`` means **first
    contact**, this list now contains people who have never bought anything, and that is a
    feature rather than a regression — it is the whole of what onboarding bought the panel.
    The previous version of this docstring claimed one writer and one call site; every clause
    of it was already false in the shipped code before onboarding landed.

    There is still deliberately **no** ``last_seen_at`` on this view, and the reason has
    changed rather than gone away: the column now has a real writer (``touch``), but it is
    written per *update*, so publishing it would let an operator watch a customer's activity
    minute by minute from a screen whose stated purpose is records. ``last_order_at`` is
    derived from ``MAX(orders.created_at)`` and says one bounded, purchase-shaped thing, no
    matter what a later writer does to the column.

    The profile half of this row comes from a LEFT OUTER join on ``user_profiles``. Every
    profile field below is ``| None`` for two different reasons at once — there is no profile
    row, or there is one with that column unset — and :attr:`is_profile_present` is the only
    thing that separates them.
    """

    id: UUID
    telegram_user_id: int
    ui_language: Language
    is_blocked: bool
    #: When the ``users`` row was inserted — i.e. this account's FIRST CONTACT, whichever of
    #: the three writers got there first: ``users_sql.ensure_user`` (from ``_create_order``
    #: or from ``record_language``), ``credits.touch``, or ``credits.set_blocked``. It is not
    #: the first order, and reading it as one understates how long an account has existed by
    #: everything between the language question and the first purchase.
    account_created_at: datetime
    first_order_at: datetime | None
    last_order_at: datetime | None
    order_count: int
    paid_order_count: int
    #: Whether a ``user_profiles`` row exists for this account at all. ``False`` is TWO facts
    #: at once and deliberately does not distinguish them: a person who has answered the
    #: language question but not yet shared a phone, and a person whose ``/forget`` deleted
    #: the row. PD-2/PD-3 put no purge stamp on this table — the row is deleted outright and
    #: absence IS the erasure record — so there is nothing further to report and the panel
    #: must not imply there is.
    is_profile_present: bool
    #: Telegram's ``@handle``, stored WITHOUT the ``@``. ``None`` when the account has none
    #: (Telegram does not require one) or when no profile row exists.
    telegram_username: str | None
    first_name: str | None
    last_name: str | None
    #: E.164, e.g. ``+998901234542``. Never masked here — masking is the response boundary's
    #: job, and this layer's whole contract is that it hands the truth to exactly one
    #: serializer rather than to every caller that thinks it needs it.
    phone_e164: str | None
    #: When the customer pressed the contact button. Distinct from ``created_at``: the row is
    #: born at the language question and the number arrives one screen later.
    phone_shared_at: datetime | None
    #: The content type the bot recorded for the stored avatar. Held on the row because
    #: ``LocalFileStorage.put`` persists no content type, so without this the avatar route
    #: would have to guess — and a guessed content type on a stored image is how an upload
    #: becomes stored XSS.
    avatar_mime: str | None
    #: When the bot last stored an avatar. A presence flag and nothing more: no ``stat``
    #: happens in this layer, for the reason ``db/admin/assets.py`` gives for refusing
    #: ``isFilePresent`` — a green tick computed without looking at a file is a claim about
    #: bytes nobody has seen.
    avatar_stored_at: datetime | None
    #: The entitlement half of the row, from a LEFT OUTER join on ``credit_accounts``.
    #:
    #: **``None`` means there is no ``credit_accounts`` row, and it is never a zero.** The
    #: column itself is ``nullable=False`` with a ``balance >= 0`` check
    #: (``models/credit_account.py``: ``balance_not_negative``), so a ``None`` arriving here
    #: has exactly one cause
    #: and needs no companion flag to disambiguate it — which is why there is no
    #: ``is_credit_account_present`` beside ``is_profile_present``. That single meaning
    #: covers two situations an operator must not see collapsed into "0 credits": an
    #: account nobody has ever metered (``open_account`` runs on the first charge or grant,
    #: so everyone who has not confirmed an order is in this state, and they are still owed
    #: the rolling allowance the moment they do), and an account whose ``/forget`` deleted
    #: the row while the anonymised ledger kept the count
    #: (``bayram.db.credit_erasure.forget_account``). Rendering either as ``0`` would tell an
    #: operator the customer has spent everything.
    credit_balance: int | None
    #: Every credit ever added, allowances included. Monotone; never decremented.
    lifetime_credits_granted: int | None
    #: The last rolling-allowance window this account was minted for, as a period index.
    #: ``None`` for two reasons at once — no account row, or an account that has never been
    #: granted an allowance — and :attr:`credit_balance` is what separates them.
    allowance_period_index: int | None

    @property
    def has_avatar(self) -> bool:
        """Whether a row claims stored avatar bytes. Says nothing about the bytes."""
        return self.avatar_stored_at is not None

    @property
    def has_credit_account(self) -> bool:
        """Whether ``credit_accounts`` holds a row for this Telegram id."""
        return self.credit_balance is not None


@dataclass(frozen=True, slots=True)
class UserDetail:
    """``/users/{telegramUserId}`` — the list row plus the per-state breakdown."""

    user: UserListItem
    #: Every state with at least one order. Absent states are absent, not zero-filled, so a
    #: reader cannot mistake "none yet" for "counted and empty".
    orders_by_state: tuple[tuple[OrderState, int], ...]
    delivered_order_count: int
    failed_order_count: int
    #: What the BOT would tell this customer they have right now, from
    #: :func:`bayram.db.credit_sql.read_balance` — the stored balance plus a rolling allowance
    #: that is due and not yet minted. Deliberately different from
    #: :attr:`UserListItem.credit_balance`, and both are on the wire: the stored column is
    #: what the ledger can prove, the projection is what the customer sees on the Confirm
    #: screen, and an operator answering "they say they have three songs left and your panel
    #: says zero" needs the two side by side rather than a single number that is right for
    #: one of the two conversations. It is an ``int`` rather than ``int | None`` because it
    #: is computed for every account, row or no row: no account is exactly what a brand-new
    #: customer with a full allowance looks like.
    credits_projected: int
    #: Debits this account has not settled yet, inside the settlement grace. The number that
    #: explains a refusal an operator cannot see any other way — a wedged render holds a
    #: credit that neither the balance nor the ledger's totals show as spent.
    in_flight_render_count: int


@dataclass(frozen=True, slots=True)
class SegmentBreakdown:
    """What one audience is made of — the numbers a human authorises a send against.

    Every figure here is an **exact** count over the same statement the Users screen pages
    (``BROADCAST_SPEC §1.7``), never a bounded one: "10,000+" is not a number anybody can
    approve, and a preview that saturated would disagree with the page an operator checked
    it against.

    **The three refusal counts overlap, and the arithmetic must not be invented.**
    :attr:`blocked` is our own bar and :attr:`bot_blocked` is the customer's — opposite facts
    with opposite subjects (``db.admin.segment``'s registry says so beside both fields) — and
    one account can be both, so ``matched`` is **not** the sum of the four. Only
    :attr:`reachable` is defined as a complement: neither barred by us nor blocked by them,
    which is the population a send would actually attempt.

    :attr:`by_language` is the only dimension published beside the totals, and it is the only
    personalisation a broadcast has (§6.1: the body carries no name, no placeholder and no
    reveal), so it is the one split that changes what an operator has to write.
    """

    matched: int
    #: Neither :attr:`blocked` nor :attr:`bot_blocked` — ``users.is_blocked IS false AND
    #: users.blocked_bot_at IS NULL``, the registry's ``is_reachable`` said once more here so
    #: the preview and a rule spelling it out cannot disagree.
    reachable: int
    #: Barred by us. Counted whether or not the customer also blocked the bot.
    blocked: int
    #: They blocked the bot. Counted whether or not we also barred them.
    bot_blocked: int
    #: Ordered by the language's own value so two previews of one audience compare equal.
    #: Languages with nobody in them are absent, never zero-filled — the same rule
    #: :attr:`UserDetail.orders_by_state` follows.
    by_language: tuple[tuple[Language, int], ...]


# ---------------------------------------------------------------------------
# Broadcasts — the campaign, its bodies, and the ledger of who it reached
# ---------------------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class BroadcastProgress:
    """How far one campaign has got, counted from ``broadcast_recipients`` itself.

    **The rows are the truth and this shape is what reads them.** ``broadcasts`` carries six
    denormalised counters that the worker's rollup writes, and :class:`BroadcastListItem`
    publishes those — a list of campaigns must not run a ``GROUP BY`` per row. This one is
    recomputed from the recipient rows for the detail screen, so an operator watching a send
    is looking at the ledger rather than at a summary a crashed rollup may not have caught
    up with. Two numbers that disagree are the drift worth seeing, which is the same argument
    ``credit_accounts.balance`` beside ``SUM(credit_ledger.delta)`` is kept for.

    One field per :class:`~bayram.contracts.BroadcastRecipientState`, always, zero-filled — a
    campaign whose expansion has not started reports seven zeros rather than an empty
    mapping, so a progress bar's segments do not appear from nowhere as the first row lands.
    ``UNKNOWN`` gets its own number for the reason that member's own docstring gives: folding
    a possibly-delivered message into ``failed`` misreports it in the one direction that
    matters.
    """

    pending: int
    sending: int
    sent: int
    failed: int
    #: Barred by us or blocked by them — one number, because neither is a delivery attempt.
    skipped_blocked: int
    undeliverable: int
    #: Left in ``SENDING`` by a killed job and aged out. Neither sent nor failed, ever.
    unknown: int

    @property
    def total(self) -> int:
        """Every recipient row of this campaign — the audience as materialised."""
        return (
            self.pending
            + self.sending
            + self.sent
            + self.failed
            + self.skipped_blocked
            + self.undeliverable
            + self.unknown
        )

    @property
    def settled(self) -> int:
        """Rows that have stopped moving. The complement of ``pending + sending``."""
        return self.total - self.pending - self.sending


@dataclass(frozen=True, slots=True)
class BroadcastListItem:
    """One row of the campaign list — **one per campaign, never one per recipient**.

    :attr:`audience_size` and :attr:`recipient_count` are two numbers on purpose and the gap
    between them is the whole point: the first is what the segment counted when the campaign
    was created, the second is how many recipient rows the expansion actually wrote. They are
    equal on every healthy campaign, and a half-expanded one is visible as arithmetic on the
    row rather than as a support ticket.

    The six counters are the ``broadcasts`` row's own, written by the worker's rollup.
    :class:`BroadcastProgress` recounts them from the recipient rows for the detail screen;
    on a list they would be a ``GROUP BY`` per row over the largest table in the schema.

    ``broadcasts.segment`` is deliberately NOT here. The stored document is what
    :class:`BroadcastDetail` carries, because a list of campaigns needs to say *which*
    audience each one used (:attr:`segment_hash`) rather than restate the whole filter tree
    fifty times. ``broadcasts.expand_cursor`` is not here either, at any depth: it is the
    worker's resumption token — a keyset position inside the audience — and the pair above
    already tells an operator everything the token could about an incomplete expansion.
    """

    id: UUID
    title: str
    kind: BroadcastKind
    state: BroadcastState
    #: The digest of the segment document this campaign was composed against. Enough to say
    #: "this is the audience you are looking at" without comparing two JSON blobs.
    segment_hash: str
    #: The exact count the segment returned at creation. Never bounded — see
    #: ``db.admin.users.count_segment_exactly``.
    audience_size: int
    #: The ``now`` the segment was compiled against. THE AUDIENCE IS FROZEN AT THIS INSTANT.
    audience_evaluated_at: datetime
    #: Rows the expansion actually materialised. Below :attr:`audience_size` while it runs.
    recipient_count: int
    sent_count: int
    failed_count: int
    skipped_count: int
    undeliverable_count: int
    unknown_count: int
    scheduled_for: datetime | None
    started_at: datetime | None
    finished_at: datetime | None
    #: Who composed it and who scheduled it, denormalised onto the row so a list renders
    #: without a join and a later rename cannot rewrite who sent forty thousand messages.
    #: ``None`` for a campaign whose actor was not recorded, never for a missing operator.
    created_by_admin_id: UUID | None
    created_by_username: str | None
    scheduled_by_admin_id: UUID | None
    scheduled_by_username: str | None
    #: The closed-vocabulary half of the reason. The operator's free text lives on
    #: ``admin_audit_log``, which owns its 90-day clock, and is never copied here.
    reason_code: AuditReasonCode | None
    reason_ref: str | None
    #: Why the RUN failed, as a symbolic token. Never a per-recipient outcome: a campaign in
    #: which twelve messages were refused is ``COMPLETED`` with twelve failed rows.
    error_code: str | None
    #: How many language bodies are composed for it. A correlated ``COUNT``, so it stays
    #: exact without a join that would multiply the page's rows.
    body_count: int
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class BroadcastBodyView:
    """One language's message: the text, the optional image and the optional button.

    **Operator-authored copy, so it crosses whole.** Nothing here is a customer's words: the
    body carries no name, no placeholder and no reveal (``BROADCAST_SPEC §6.1``), which is
    what lets this view publish the text itself where :class:`BriefView` publishes a length.

    ``media_file_id`` is published as a boolean and never as its value: it is the worker's
    cache of what Telegram called our upload after the first send, it is meaningless to any
    other bot token, and :attr:`media_storage_key` is the one an operator can actually fetch
    the image back from. :class:`AssetView` publishes ``tg_file_id`` the same way.
    """

    id: UUID
    broadcast_id: UUID
    language: Language
    text: str
    #: Our object store's key for the operator's upload, or ``None`` for a text-only body.
    #: A body WITH media is capped at ``BROADCAST_CAPTION_LENGTH`` by a database CHECK.
    media_storage_key: str | None
    has_media_file_id: bool
    #: Both or neither, enforced by ``ck_broadcast_bodies_button_pair``.
    button_label: str | None
    button_url: str | None
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class BroadcastDetail:
    """One campaign, its composed bodies and the progress its recipient rows report.

    :attr:`segment` is the stored document verbatim — the answer to "who was this sent to?"
    a year later, after the fields have been re-labelled and the operator who built it has
    left. It is NOT re-evaluated: a recompiled segment answers "who would match now", which
    on a campaign that has already gone out is a different and misleading question.
    """

    broadcast: BroadcastListItem
    #: Ordered by language so two reads of one campaign compare equal.
    bodies: tuple[BroadcastBodyView, ...]
    #: The segment document as stored. Opaque here; ``bayram.admin.schemas`` owns its wire shape.
    segment: dict[str, Any]
    #: Counted from ``broadcast_recipients``, not from the campaign row's counters.
    progress: BroadcastProgress


@dataclass(frozen=True, slots=True)
class BroadcastRecipientItem:
    """One account's place in one campaign — a row of the recipient ledger.

    **This is the only shape in the broadcast reads that names a person**, and it names them
    exactly as ``/users`` already does: a Telegram id and nothing else. No handle, no first
    name, no phone — the account holder's id is what ``db.admin.audience_lists`` argues may
    be shown to this panel's sole operator under an audit row, and this view widens that by
    nothing. The message is not repeated per row either; it is on
    :class:`BroadcastBodyView`, once per language.

    :attr:`telegram_user_id` is ``None`` for exactly one reason — ``/forget`` ran and
    anonymised the row. The row itself SURVIVES, because a delivery record that vanished when
    somebody exercised a right leaves "was this person sent that campaign?" unanswerable for
    every other row in the campaign too.
    """

    id: UUID
    broadcast_id: UUID
    telegram_user_id: int | None
    #: The account's language AT EXPANSION, snapshotted rather than joined — the body this
    #: row was or will be sent is chosen from this column and not from the account's today.
    language: Language
    state: BroadcastRecipientState
    attempts: int
    #: A symbolic token, never an excerpt of a Telegram response.
    error_code: str | None
    #: When this row stopped moving, whatever stopped it. ``None`` while it is pending or
    #: in flight; the SEND instant is this column narrowed by ``state == SENT``.
    settled_at: datetime | None
    created_at: datetime
    updated_at: datetime

    @property
    def is_erased(self) -> bool:
        """``/forget`` anonymised this row. The delivery record is kept; the id is gone."""
        return self.telegram_user_id is None


# ---------------------------------------------------------------------------
# Entitlements — the account, and the append-only movements that explain it
# ---------------------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class CreditAccountState:
    """One ``credit_accounts`` row, as ``GET /users/{id}/credits`` reports it.

    Separate from :class:`UserListItem`'s three credit columns rather than shared with them,
    because the two answer different questions: the list row exists for every user and
    carries ``None`` where there is no account, while this type exists only when the row
    does — the endpoint's ``account`` is ``None`` for an account that was never opened, and
    that absence is the answer rather than a missing field.

    ``balance`` is a second representation of ``SUM(credit_ledger.delta)`` and both are on
    the same response on purpose (``models/credit_account.py``'s module docstring argues why
    the duplication is bought). An operator who sees them disagree has found the drift
    ``credit_sql.verify_balances`` exists to detect, and the ledger page beside this object
    is what lets them prove it without a database session.
    """

    telegram_user_id: int
    balance: int
    lifetime_granted: int
    allowance_period_index: int | None


@dataclass(frozen=True, slots=True)
class CreditLedgerItem:
    """One movement of one account's credits — a row of ``GET /users/{id}/credits``.

    **Every field here is machine-written and none of it is personal data.** The table holds
    a Telegram id, two closed enums, three integers, a key this system built and a
    subsystem name (``models/credit_ledger.py``'s docstring makes the same statement, which
    is why the table is absent from ``tables_with_personal_data``). So there is nothing on
    this view to mask and nothing that could be revealed — which is what lets the endpoint
    sit on ``RECORDS_READ`` beside the row it explains rather than behind a reveal.

    :attr:`idempotency_key` is published deliberately. It is the operator's only evidence
    for "was this comped twice or once?" — the unique index on it is what makes a duplicate
    impossible rather than unlikely — and the one shape that embeds an identifier,
    ``grant:period:{telegram_user_id}:{index}``, embeds the value the caller already put in
    the path and that every ``/users`` row already carries unmasked.
    """

    id: UUID
    kind: CreditEntryKind
    reason: CreditReason
    #: Signed, and constrained to agree with :attr:`kind`: positive for a GRANT or REFUND,
    #: negative for a DEBIT, exactly zero for a CONSUME (which settles a debit without
    #: moving anything).
    delta: int
    #: The order this movement belongs to, where there is one. A period allowance and an
    #: operator grant have none, and there is no foreign key — a ledger row must outlive the
    #: order it refers to.
    order_id: UUID | None
    #: Which charge attempt for that order. Bumped by a refund, which is what makes a
    #: refunded order chargeable again.
    generation: int
    idempotency_key: str
    #: ``bot`` | ``pipeline`` | ``sweep`` | ``admin:{username}``, or ``None`` for a row whose
    #: writer was not recorded. Diagnostic attribution and not an authorisation record: the
    #: authoritative "who did this" is the audit log's row, which is why a truncated
    #: 32-character username here is harmless.
    actor: str | None
    created_at: datetime


# ---------------------------------------------------------------------------
# Metrics
# ---------------------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class OrdersPerDay:
    """One UTC day of order volume. Days with no orders are absent from the series."""

    day: date
    total: int
    delivered: int
    failed: int
    paid: int


@dataclass(frozen=True, slots=True)
class DeliveryOutcome:
    """Delivery success over a window, counted from terminal states only."""

    total: int
    delivered: int
    failed: int
    cancelled: int
    in_flight: int

    @property
    def success_rate(self) -> float:
        """Delivered as a share of orders that REACHED a terminal state.

        In-flight orders are excluded from the denominator on purpose: counting them as
        failures would make the rate drop every time traffic rises.
        """
        terminal = self.delivered + self.failed + self.cancelled
        if terminal <= 0:
            return 0.0
        return self.delivered / terminal


@dataclass(frozen=True, slots=True)
class LatencySummary:
    """``created_at`` → ``delivered_at`` in seconds, by nearest-rank percentile."""

    sample_count: int
    p50_seconds: float | None
    p95_seconds: float | None


@dataclass(frozen=True, slots=True)
class FailureCount:
    """One error code's share of failed attempts over a window."""

    #: ``None`` groups every failure whose writer recorded no code.
    error_code: str | None
    count: int
    share: float


@dataclass(frozen=True, slots=True)
class StrategyOutcome:
    """How one candidate orthography fared under acoustic verification.

    The bake-off ``BAYRAM_NAME_CANDIDATE_ORDER`` is reordered from. Deliberately a superset of
    ``bayram.db.attempts.StrategyStat``: it adds the window's bounds so a reader can tell a
    strategy with no traffic this month from one that never worked.
    """

    strategy: NameStrategy
    attempts: int
    verified: int

    @property
    def verification_rate(self) -> float:
        if self.attempts <= 0:
            return 0.0
        return self.verified / self.attempts


@dataclass(frozen=True, slots=True)
class SimilarityBucket:
    """One bar of the match-confidence histogram: a half-open ``[lower, upper)`` band.

    The top bucket is closed at ``1.0`` — a verifier that returns exactly ``1.0`` has said
    the strongest thing it can say, and dropping that sample or giving it a bucket of its
    own would be a worse answer than a single closed edge on the last bar.

    A ``count`` of ``0`` here is an empty BIN, not an absent measurement: every bucket is
    returned, always, because a histogram with holes in it is unreadable. Whether the
    distribution as a whole is worth drawing is answered by
    :attr:`NameAnalytics.scored`, not by the bars.
    """

    lower: float
    upper: float
    count: int


@dataclass(frozen=True, slots=True)
class StrategyAnalysis:
    """One candidate orthography's whole row on ``/generations/names``.

    A superset of :class:`StrategyOutcome` rather than a replacement for it: the bake-off
    bars need ``attempts``/``verified``, the histogram needs ``buckets``, and the "is the
    threshold deciding coin flips" question needs ``near_threshold`` — and all three have to
    describe the SAME window and the same population or the screen argues with itself.

    ``scored`` is not ``attempts``. Verification can run and record a verdict without a
    similarity score, so the histogram's denominator is its own number and travels with it.
    """

    strategy: NameStrategy
    #: Rows where verification RAN. The bake-off denominator.
    attempts: int
    verified: int
    #: Rows carrying a ``match_confidence``. The histogram's denominator.
    scored: int
    #: Scored rows within the band of the threshold, or ``None`` when this deployment has
    #: not published ``name_match_min_similarity``. ``None`` is "not knowable here"; ``0``
    #: is "nothing sits near the cliff", and the two lead to opposite decisions.
    near_threshold: int | None
    buckets: tuple[SimilarityBucket, ...]

    @property
    def verification_rate(self) -> float:
        """Share of attempts that passed. Zero attempts reads as ``0.0`` — see the note on
        :class:`StrategyOutcome`; the caller renders "no attempts" from the denominator."""
        if self.attempts <= 0:
            return 0.0
        return self.verified / self.attempts


@dataclass(frozen=True, slots=True)
class NameAnalytics:
    """Everything ``/generations/names`` needs to answer one question, from one window.

    The question is "what should ``BAYRAM_NAME_CANDIDATE_ORDER`` be", and it has two halves
    that must not come from two different reads: which orthography wins, and whether the
    threshold that decided those wins is in a defensible place.

    **The empty window is a first-class answer.** ``attempts == 0`` with
    ``has_recorded_attempts`` true means "nothing in THIS window" — the ledger holds
    verdicts, the window excludes them. ``attempts == 0`` with ``has_recorded_attempts``
    false means verification has never run here at all. §11.4's ``AsyncBoundary``
    distinguishes empty-filtered from empty-virgin and cannot do it from a zero.
    """

    #: Best first, by rate then volume. A strategy with no attempts in the window is
    #: ABSENT rather than present at zero, exactly as ``strategy_outcomes`` leaves it.
    strategies: tuple[StrategyAnalysis, ...]
    #: The same distribution summed across every strategy — what the single histogram on
    #: the screen draws.
    buckets: tuple[SimilarityBucket, ...]
    attempts: int
    verified: int
    scored: int
    near_threshold: int | None
    #: ``name_match_min_similarity`` as this deployment published it, or ``None``. The
    #: worker owns the real value; see :mod:`bayram.admin.settings`.
    threshold: float | None
    #: How near "near" is, on the wire so the SPA does not restate it.
    band: float
    bucket_count: int
    #: Whether the ledger holds ANY verdict at all, window ignored.
    has_recorded_attempts: bool

    @property
    def verification_rate(self) -> float | None:
        """``None`` when nothing was verified: an empty window has no rate, not a bad one."""
        if self.attempts <= 0:
            return None
        return self.verified / self.attempts


# ---------------------------------------------------------------------------
# Vendor spend — the one surface where every quantity is nullable on purpose
# ---------------------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class VendorUsageRollup:
    """One ``(vendor, operation, model_id)`` group of ``vendor_usage`` over a window.

    **Every quantity below is ``None`` when nobody in the group measured that unit**, and
    that is not defensive coding — it is what ``SUM()`` over a nullable column already
    answers. ``vendor_usage`` declares no default on any quantity column precisely so this
    stays free: a chat completion has no ``billed_characters``, a speech synthesis has no
    tokens, and a group of either comes back ``None`` for the other rather than ``0``. A
    zero here would say the vendor charged us for nothing; ``None`` says nobody counted.

    ``cost_usd`` sums **only the rows that carry one**, so ``costed_calls`` travels beside
    it: an operator reading "$4.10 over 900 calls" when nine of them were priced would be
    reading a partial total as a complete one. Same rule as ``sampleCount`` beside a
    percentile — the number that says how much evidence there is travels with the number
    derived from it.

    ``cost_source`` stays enum-typed here and ``is_cost_mixed`` carries the second fact
    separately. Only the wire collapses the two into the string ``"mixed"``: a domain model
    whose provenance field can hold a value no ``CostSource`` member has is one every later
    reader has to special-case.
    """

    vendor: Vendor
    operation: VendorOperation
    #: The vendor's own model id. ``None`` groups every call made before a model was named.
    model_id: str | None
    calls: int
    successes: int
    failures: int
    prompt_tokens: int | None
    completion_tokens: int | None
    total_tokens: int | None
    billed_characters: int | None
    audio_ms: int | None
    #: Summed over the priced rows alone. ``None`` when no call in the group was priced.
    cost_usd: float | None
    #: ``None`` when nothing in the group carries a cost; otherwise the one source every
    #: priced row agreed on, with :attr:`is_cost_mixed` saying whether they agreed at all.
    cost_source: CostSource | None
    #: True when the priced rows in this group do not share one provenance.
    is_cost_mixed: bool
    #: How many of ``calls`` carried a cost. Never inferred from ``cost_usd`` being set.
    costed_calls: int
    avg_latency_ms: int | None
    max_latency_ms: int | None

    @property
    def success_rate(self) -> float | None:
        """``None`` when the group is empty: no denominator, no rate — never ``0.0``."""
        if self.calls <= 0:
            return None
        return self.successes / self.calls


@dataclass(frozen=True, slots=True)
class VendorUsageTotals:
    """Every vendor call in the window, collapsed to one row — the hero figure's source.

    A strict aggregate of the same population :class:`VendorUsageRollup` groups, computed by
    the database in its own query rather than folded from the groups: summing a tuple of
    already-``None`` quantities in Python is how "nobody measured" turns into ``0`` on the
    one tile an operator reads first.
    """

    calls: int
    successes: int
    failures: int
    cost_usd: float | None
    costed_calls: int
    #: How the priced calls in the window arrived at their figure, and whether they agreed.
    #: The hero spend tile was the ONE cost number on the screen that could not say — the
    #: per-group rollup has carried provenance from the start — so a total that is mostly
    #: arithmetic against a placeholder rate looked exactly like one a vendor reported.
    cost_source: CostSource | None
    is_cost_mixed: bool
    total_tokens: int | None
    billed_characters: int | None
    audio_ms: int | None
    avg_latency_ms: int | None

    @property
    def success_rate(self) -> float | None:
        """``None`` over an empty window. An empty window has no success rate."""
        if self.calls <= 0:
            return None
        return self.successes / self.calls


@dataclass(frozen=True, slots=True)
class VendorUsagePerDay:
    """One vendor's spend on one UTC day. A day with no calls is ABSENT from the series.

    Absent rather than zero-filled, for the reason :class:`OrdersPerDay` states: a zero bar
    on a day this deployment made no calls is a measurement nobody took, and here it would
    be a measurement about money.
    """

    day: date
    vendor: Vendor
    calls: int
    cost_usd: float | None
    costed_calls: int


@dataclass(frozen=True, slots=True)
class VendorErrorCount:
    """One error code's share of ONE vendor's failures in the window.

    Per vendor rather than global, because the question the panel asks is "what is going
    wrong with this vendor" and a share computed against every vendor's failures answers a
    different one. ``share`` is therefore over that vendor's failures alone.
    """

    vendor: Vendor
    #: ``None`` groups every failure whose writer recorded no code.
    error_code: str | None
    count: int
    share: float


@dataclass(frozen=True, slots=True)
class ReadCapabilities:
    """What this deployment's data can honestly answer, for ``/ops/capabilities``.

    Every field is measured, not declared. A capability that is hardcoded ``False`` in a
    constant is one somebody forgets to flip; these are derived from the schema that is
    actually installed and the rows that are actually there.
    """

    #: Any attempt row carrying a non-zero cost. False today — see the module docstring.
    is_cost_telemetry: bool
    #: Any attempt row carrying a non-zero latency. False today, same reason.
    is_latency_telemetry: bool
    #: Any asset row carrying a storage key, which is what makes archive deletion possible.
    is_asset_storage_key_recorded: bool
    #: Derived from ``Base.metadata`` — true once Phase 3's migration lands the table.
    is_chat_capture: bool
    #: Derived from ``Base.metadata`` — true once Phase 5's migration lands the table.
    is_payment_ledger: bool
    #: Always false until an order-event table exists; the timeline says "inferred".
    is_state_transition_log: bool
    #: Any ``vendor_usage`` row at all. A ROW probe, not a ``has_table`` one: a deployment
    #: whose migration landed but whose worker has never written is honestly not
    #: instrumented, and the panel says so rather than drawing an empty chart.
    is_vendor_usage: bool
    #: Any ``vendor_usage`` row carrying a cost. Separate from the flag above because the
    #: two absences have different remedies: nothing recorded means instrument the worker,
    #: recorded-but-unpriced means configure a rate. One flag could not tell them apart.
    is_vendor_cost: bool
    #: Any ``plan_purchases`` row. A ROW probe for the same reason the two above are: the
    #: migration ships with the panel, so ``has_table`` would report every deployment as
    #: revenue-instrumented on the day it lands.
    is_plan_revenue: bool
    #: Any ``topup_purchases`` row. Two flags rather than one because the absences have
    #: different remedies — no plan has ever been sold here, against no top-up AMOUNT has
    #: ever been recorded here, which is true of every deployment's whole history up to the
    #: revision that created the table. The second is the state the SPA must render as "sold
    #: before amounts were recorded" rather than as an empty chart.
    is_topup_revenue: bool
    #: Any ``bot_membership_events`` row. False means the handler has not seen a block yet,
    #: so a churn count of zero is "nothing observed" and not "nobody left".
    is_churn_instrumented: bool
    #: Any ``vendor_balances`` row. False means the poller has never run in this deployment,
    #: which is a different screen from "the poller ran and the vendor refused".
    is_vendor_balance: bool
    #: Any ``user_activity_snapshots`` row. The historical DAU series exists only from the
    #: first night the snapshot job ran; before that there is no history to draw.
    is_activity_history: bool


# ---------------------------------------------------------------------------
# The dashboard's aggregate shapes
#
# Every quantity that CAN be unmeasured is ``| None`` with no default, at this layer as
# well as at the column. A dataclass default of ``0`` undoes at the boundary exactly what
# the schema's null-never-zero rule bought: ``generation_attempts.cost_usd DEFAULT 0.0`` is
# the cautionary tale, and ``_as_int``/``_as_float`` in ``vendor_usage.py`` exist to keep a
# ``SUM`` over an empty group from arriving here as anything but ``None``.
#
# No shape below holds a rate. Not one. A quotient's two operands travel together and the
# division happens in ``bayram.admin.schemas.overview``, where the wire type REFUSES to be
# constructed without its denominator. A dataclass property returning a float would have to
# answer something for a zero denominator, and every answer to that is a lie an operator
# would act on.
# ---------------------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class Trend:
    """A count over a window and the same count over the window immediately before it.

    ``previous`` is ``None`` — never ``0`` — whenever the request supplied no lower bound,
    because an open-below range has no length and therefore no predecessor. Zero would
    claim the preceding period was measured and empty, which is the reading that turns
    "we do not know" into "growth from nothing".
    """

    current: int
    previous: int | None

    @property
    def change_ratio(self) -> float | None:
        """``(current - previous) / previous``, or ``None`` when that is undefined.

        ``None`` for an unmeasured previous window AND for a previous window of zero.
        Growth from nothing is not "+100%": the quotient has no denominator, and a panel
        that printed one would be inventing the only number on the card an operator reads.
        """
        if self.previous is None or self.previous == 0:
            return None
        return (self.current - self.previous) / self.previous


@dataclass(frozen=True, slots=True)
class BucketPoint:
    """One bucket of a time series: the database's own key, and that key parsed.

    ``bucket`` is the raw ``YYYY-MM-DD`` or ``YYYY-MM-DDTHH`` text
    :class:`~bayram.db.admin.sql.UtcDay`/:class:`~bayram.db.admin.sql.UtcHour` produced, kept so
    the wire carries the same string the grouping used. ``started_at`` is that key as an
    aware instant, parsed once here so neither the serializer nor the week/month fold has to
    re-parse it — and so the fold has a real ``datetime`` to group on rather than a prefix
    of a string.
    """

    bucket: str
    started_at: datetime


@dataclass(frozen=True, slots=True)
class DeliveredPerBucket:
    """Songs that SHIPPED in one bucket. Buckets with no delivery are absent."""

    bucket: str
    started_at: datetime
    delivered: int


@dataclass(frozen=True, slots=True)
class NewAccountsPerBucket:
    """Accounts first seen in one bucket. Buckets with no sign-up are absent."""

    bucket: str
    started_at: datetime
    count: int


@dataclass(frozen=True, slots=True)
class AccountTotals:
    """Every account this deployment has, and the two ways one stops being reachable.

    ``blocked`` is the operator's own bar (``users.is_blocked``); ``bot_blocked`` is the
    CUSTOMER's, recorded from ``my_chat_member`` and from a delivery refusal
    (``users.blocked_bot_at``). They are two columns and two numbers because they are two
    different facts with two different remedies, and summing them would double-count an
    account that is both.
    """

    total: int
    blocked: int
    bot_blocked: int
    total_trend: Trend


@dataclass(frozen=True, slots=True)
class ActiveAccounts:
    """DAU / WAU / MAU as of one instant, nested: every ``day`` is also in ``month``.

    ``as_of`` travels with them because all three are cutoffs measured backwards from it;
    without it the three numbers are counts against a clock the reader cannot see.
    """

    day: int
    week: int
    month: int
    as_of: datetime


@dataclass(frozen=True, slots=True)
class ChurnCounts:
    """Customers who blocked the bot in a window, and those who came back.

    Counted from ``bot_membership_events``, which records PASSAGES, so a customer who left
    and returned inside one window appears in both numbers. That is deliberate: the gauge of
    who is blocked right now is ``AccountTotals.bot_blocked``, and this pair is the flow.
    """

    blocked: Trend
    unblocked: Trend


@dataclass(frozen=True, slots=True)
class OrderFunnel:
    """Survivors at each state for one created-at cohort. Never passages.

    ``capabilities.is_state_transition_log`` is false and there is no order-event table, so
    an order that passed through ``AUTHORIZED`` and then failed retains no record of the
    passage. Every number here is therefore where orders ARE now, not where they went.

    There is deliberately no ``abandoned`` count: drafts are DELETED outright at the
    abandoned-draft cutoff, so any such number would decay towards zero as the window
    lengthens and read as "nobody abandons any more". The ``DRAFT`` survivor count is
    published instead and the caption belongs to the SPA.
    """

    created: int
    paid: int
    by_state: tuple[OrderStateTotal, ...]


class RevenueSource(StrEnum):
    """Which receipts table a revenue row came from.

    Two tables and not one because a plan and a top-up are different products sold under
    different terms; they share a column vocabulary so a revenue read is a clean union, and
    this member is what keeps the union from collapsing into an unattributable total.
    """

    PLAN = "plan"
    TOPUP = "topup"


@dataclass(frozen=True, slots=True)
class RevenueBucket:
    """Sales recorded in one UTC bucket, at the finest grain the receipts carry.

    ``product`` is a ``str`` and not an enum on purpose: the two sources carry members of
    two different enums (``PlanKind``, ``TopupKind``) into one series, and a union type on
    the wire would force every consumer to know which enum a given row's value came from.
    Rendered raw, never humanised, exactly as ``VendorUsageRollup.model_id`` is.

    ``currency`` and ``provider`` are part of the key and are NEVER collapsed. Summing
    across currencies produces a figure in an invented unit; collapsing providers lets a
    stub-rail sale — ``StubCheckoutProvider`` reports every charge paid having contacted
    nobody — be read as settled money.
    """

    bucket: str
    started_at: datetime
    source: RevenueSource
    product: str
    currency: str
    provider: str
    sales: int
    amount_minor: int


@dataclass(frozen=True, slots=True)
class RevenueTotal:
    """:class:`RevenueBucket` without the bucket — one window, one row per key."""

    source: RevenueSource
    product: str
    currency: str
    provider: str
    sales: int
    amount_minor: int


@dataclass(frozen=True, slots=True)
class CurrencyAmount:
    """A money total that carries its unit. There is no scalar money anywhere on this surface."""

    currency: str
    amount_minor: int


@dataclass(frozen=True, slots=True)
class PlanLiability:
    """What the plans still running owe, measured in SONGS and never valued in soʻm.

    Valuing an unconsumed song means dividing ``amount_minor`` by ``songs_included``, which
    is an accounting ALLOCATION policy nobody in this codebase has chosen. So this shape
    publishes measured song counts and the measured ``SUM(amount_minor)`` of plans still
    running, and refuses the pro-rata figure: a number that looks measured and is really a
    policy is worse than no number.

    ``live_holders`` is ``COUNT(DISTINCT telegram_user_id)`` and therefore does NOT count
    the erased — ``/forget`` nulls the column and ``COUNT(DISTINCT)`` skips NULLs — so it
    understates by exactly the number of customers who exercised a right.
    ``live_anonymised_plans`` is what makes that visible, and is the reason the holder count
    is not returned alone. ``live_plans`` can also exceed ``live_holders`` before any
    erasure: a renewal bought before the previous plan lapsed leaves two current rows, and
    liability is carried by rows.

    The three song totals are ``int | None`` rather than ``int`` because they come from
    ``SUM(CASE … ELSE NULL)`` over a partition that may be empty. ``None`` means "no plan is
    in this partition" and ``0`` means "plans are, and they owe nothing" — two different
    screens, which is the null-never-zero rule applied to an aggregate.
    """

    as_of: datetime
    live_plans: int
    live_holders: int
    live_anonymised_plans: int
    live_plans_with_songs_left: int
    unconsumed_songs: int | None
    live_amounts: tuple[CurrencyAmount, ...]
    ended_plans: int
    breakage_songs: int | None
    expiring_within_days: int
    expiring_plans: int
    expiring_songs_left: int | None


@dataclass(frozen=True, slots=True)
class PlanUtilisationBucket:
    """One tenth of the songs-used-over-songs-included distribution, for ENDED plans.

    A ``count`` of ``0`` is an empty BIN and not an absent measurement, so all ten are
    always returned: a histogram with holes in it is unreadable. Whether the distribution is
    worth drawing at all is answered by ``PlanLiability.ended_plans`` beside it — breakage
    is not measurable before the clock stops, and a running plan's ratio is not final.
    """

    lower: float
    upper: float
    count: int


@dataclass(frozen=True, slots=True)
class UnpricedTopups:
    """The population sold before amounts were recorded, counted and never priced.

    ``_fulfil_single`` used to write only a ``credit_ledger`` GRANT under
    ``reason=TOPUP_PURCHASE`` — no amount, no currency, no provider — so that money is gone
    and cannot be recovered. Back-pricing it at ``single_song_price_minor`` would price
    history at a value read at QUERY time, moving every historical figure the next time the
    price moves. So the count travels beside the money on the wire, exactly as
    ``costed_calls`` travels beside ``cost_usd`` and for the same reason.
    """

    unpriced: int
    priced: int


@dataclass(frozen=True, slots=True)
class VendorSpendPerBucket:
    """One vendor's calls and priced spend in one bucket."""

    bucket: str
    started_at: datetime
    vendor: Vendor
    calls: int
    cost_usd: float | None
    costed_calls: int


@dataclass(frozen=True, slots=True)
class VendorSpendSplit:
    """Where the money went: one ``(vendor, operation)`` slice of the window.

    Ordered by ``calls`` and never by ``cost_usd`` — a nullable sort key puts NULLs first on
    Postgres and last on SQLite, so a cost ordering returns one row order in production and
    another in the suite meant to be checking it.
    """

    vendor: Vendor
    operation: VendorOperation
    calls: int
    cost_usd: float | None
    costed_calls: int
    cost_source: CostSource | None
    is_cost_mixed: bool


@dataclass(frozen=True, slots=True)
class CostPerDeliveredSong:
    """The numerator and both denominators of the unit-economics figure. Never the quotient.

    The cost can be ``None`` while ``delivered_orders`` is positive — calls recorded, no
    rate configured — so a ratio computed here would have to invent something for that case.
    The division happens in the wire layer, in a type that cannot be constructed without
    both operands.

    ``attributed_orders`` is how many delivered orders had ANY vendor call attributed to
    them, and it is not ``delivered_orders``: an order rendered before the usage ledger
    existed carries no calls at all, and the gap between the two numbers is what says the
    cost covers part of the cohort.
    """

    cost_usd: float | None
    costed_calls: int
    calls: int
    attributed_orders: int
    delivered_orders: int
    cost_source: CostSource | None
    is_cost_mixed: bool


@dataclass(frozen=True, slots=True)
class UnattributedSpendPerBucket:
    """Spend on real work that reached no order — the leak the cost-per-song ratio misses."""

    bucket: str
    started_at: datetime
    cost_usd: float | None
    costed_calls: int
    calls: int


@dataclass(frozen=True, slots=True)
class OperationLatency:
    """Nearest-rank p50/p95 of ``latency_ms`` for ONE vendor operation.

    Three counts and not one: ``calls`` is every call in the window, ``measured_calls`` is
    how many recorded a latency at all, and ``sample_count`` is what the percentiles were
    taken over. They can differ, and a percentile whose sample size is invisible is a
    measurement of the system rather than of three calls.
    """

    operation: VendorOperation
    calls: int
    measured_calls: int
    sample_count: int
    p50_ms: int | None
    p95_ms: int | None


@dataclass(frozen=True, slots=True)
class FakeCallGuard:
    """How many of the window's vendor calls came from a fake-provider run.

    The one reader in this package that opts INTO ``is_fake`` rows. Every other number on
    the finance surface excludes them structurally, and this pair is what tells the operator
    that exclusion happened rather than leaving a demo run silently invisible.
    """

    fake_calls: int
    total_calls: int


@dataclass(frozen=True, slots=True)
class VendorBalanceState:
    """One row of the cached ``vendor_balances`` table, read and never fetched.

    **The admin process makes no outbound call and holds no vendor key.** The poller lives
    in the ARQ worker and writes here; this layer reads what it wrote. That boundary is the
    reason this shape carries ``checked_at`` and ``fetched_at`` as two separate clocks: the
    first is when we last ASKED, the second is when the numbers below it were last actually
    ANSWERED, and after an outage they diverge while the balance stays at its last known
    value. A single "as of" would make a stale figure look fresh.
    """

    vendor: Vendor
    is_fallback: bool
    provider: str
    balance_unit: BalanceUnit
    balance_remaining: float | None
    balance_total: float | None
    balance_used: float | None
    is_unbounded: bool | None
    quota_resets_at: datetime | None
    quota_reset_hint: str | None
    plan_tier: str | None
    subscription_status: str | None
    songs_remaining: int | None
    per_song_rate: float | None
    estimate_basis: BalanceEstimateBasis | None
    fetched_at: datetime | None
    checked_at: datetime
    is_last_poll_ok: bool
    http_status: int | None
    error_code: str | None
    consecutive_failures: int


# ---------------------------------------------------------------------------
# The second dashboard cut: renewal, audience, unit economics, provenance
#
# Same rules as the block above, and two additions the shapes here are the first to need.
#
# **A derived quotient is a ``@property`` returning ``float | None``, never a constructor
# argument.** ``Trend.change_ratio`` established the form and every quotient below follows
# it: the operands are the measurement, the ratio is arithmetic over them, and a ratio
# passed IN could disagree with the numbers printed beside it — a per-song cost computed
# against one denominator in SQL and rendered next to another on the card is the exact
# failure. ``None`` and not ``0.0`` whenever the denominator is zero or the numerator
# unmeasured, which is the same refusal ``change_ratio`` makes and for the same reason.
#
# **Two shapes here carry identity on purpose.** :class:`TopGenerator` and
# :class:`RecentSubscriber` hold ``telegram_user_id`` and the profile's handle and first
# name, which no other view in this package does. They are served on ``RECORDS_READ`` and
# audited, they are NOT part of the ``DASHBOARD_READ`` surface, and the reveal / step-up
# machinery they sit beside is untouched and still load-bearing for the screens that use
# it. The recipient's name is a different subject entirely and stays out: nothing below
# reads ``briefs.recipient_name_display`` or ``name_records.grapheme``.
# ---------------------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class SubscriptionChurn:
    """Renewal over the starter plan: of the plans that ENDED, how many were bought again.

    The starter plan (twelve songs, thirty days, :attr:`~bayram.db.enums.PlanKind.STARTER`) is
    the only subscription-shaped product this deployment sells, so it is the only thing
    "churn" can mean on the revenue side. ``ChurnCounts`` is the other churn on this
    surface and measures something else entirely — passages through
    ``bot_membership_events``, i.e. customers leaving the BOT — and the two must never be
    read as one number.

    **A RUNNING plan is not in the denominator.** Its outcome is not final: the holder has
    not declined to renew, they simply have not reached the decision yet, and counting them
    would put every new customer in the lapsed column for thirty days. This is the same
    argument :func:`~bayram.db.admin.plan_purchases.plan_utilisation` makes for restricting the
    utilisation histogram to ended plans, and it has the same consequence — the figure is
    late by up to the plan length and is honest rather than early.

    **A renewal is INFERRED, because there is no renewal event.** Nothing in the schema
    records "this purchase replaced that one": ``plan_purchases`` rows are independent
    receipts, and :func:`bayram.db.fulfilment.write_plan_sale` refuses to write a second row
    while a plan is current — it hands back the running row instead — so a renewal can only
    ever appear as a LATER row for the same ``telegram_user_id``. That inference is what
    this shape publishes, and it is why the two counts are named ``renewed`` / ``lapsed``
    rather than anything that implies a link the data does not hold.

    ``anonymised_ended`` is the honesty column. ``/forget`` nulls ``telegram_user_id`` on
    the receipt (``bayram.db.credit_erasure.forget_account`` — the row survives, the identity
    does not), and a plan with no identity cannot be followed to a later purchase by
    anybody, including this read. Those rows are IN ``ended_plans`` because they really did
    end, and they can never be in ``renewed`` — nor in ``lapsed``, which counts only the
    identified endings, so the three arms partition the denominator exactly. Publishing the
    count beside the pair is what keeps an exercised right from reading as a wave of lapses,
    exactly as ``PlanLiability.live_anonymised_plans`` does for the liability count.
    """

    #: Plans whose ``plan_ends_at`` fell inside the window. The denominator, and the only
    #: population whose renewal decision has actually been made.
    ended_plans: int
    #: Ended plans whose holder has a LATER ``plan_purchases`` row. Never includes an
    #: anonymised row, which has no holder to follow.
    renewed: int
    #: Ended plans with an IDENTIFIED holder and no later row. **The anonymised endings are
    #: NOT in here** — they are their own arm below, so the three counts partition the
    #: denominator exactly: ``renewed + lapsed + anonymised_ended == ended_plans``, on every
    #: window, asserted by ``tests/test_db/test_plan_churn.py``. Folding them in would state
    #: that an erased customer did not come back, when the truth is that nobody can tell.
    #: The consequence is that :attr:`rate` is a FLOOR on real churn rather than a ceiling,
    #: understated by at most :attr:`anonymised_ended` endings.
    lapsed: int
    #: How many of :attr:`ended_plans` carry ``telegram_user_id IS NULL``. The exact width of
    #: the blind spot ABOVE :attr:`lapsed` — published beside it rather than folded into it,
    #: and never a correction applied to it.
    anonymised_ended: int

    @property
    def rate(self) -> float | None:
        """``lapsed / ended_plans``, or ``None`` when no plan ended in the window.

        ``None`` and never ``0.0``: a window in which nothing ended has no churn rate, and
        "0% churn" is the single most flattering lie this panel could tell — it reads as
        perfect retention on precisely the deployments too young to have measured any.

        A FLOOR, not a ceiling. The numerator excludes the anonymised endings (see
        :attr:`lapsed`), so the real lapse rate is this figure plus at most
        ``anonymised_ended / ended_plans``. Render the counts beside it.
        """
        if self.ended_plans <= 0:
            return None
        return self.lapsed / self.ended_plans


@dataclass(frozen=True, slots=True)
class LanguageMix:
    """How many accounts read the BOT in one language. One entry per ``users.ui_language``.

    **This is the interface language and NOT the song's.** ``users.ui_language`` is what the
    customer reads the bot in; ``briefs.output_language`` is what the song is SUNG in, and
    :class:`bayram.contracts.Language`'s own docstring states the two are chosen independently
    — a customer can drive the bot in Russian and order a song in Uzbek Latin, and many do.
    Labelling this chart "song language" would therefore not be a loose caption but a
    different measurement.

    ``ui_language`` is ``NOT NULL DEFAULT uz_latn`` (``models/user.py``), so every account
    lands in exactly one entry and no bucket is missing — but the default is also why the
    UZ_LATN entry is an over-count of *choice*: ``ensure_user`` refreshes the column only
    when the writer actually knows the answer (``is_language_authoritative``), so an account
    created by an order alone sits at the default without anybody having picked it. The
    number is a true count of what the bot WILL SPEAK, and not a survey result.
    """

    language: Language
    accounts: int


@dataclass(frozen=True, slots=True)
class LanguageMixTotals:
    """:class:`LanguageMix` entries with the denominator they are shares of.

    The denominator is carried explicitly rather than left to be summed in the SPA, for the
    reason the block comment above gives: a share whose denominator was reconstructed by the
    reader is a share the reader can reconstruct WRONGLY — a filtered or truncated
    ``languages`` tuple would silently renormalise to 100% of whatever survived. It also
    keeps the shape honest if a later language is ever added to
    :class:`~bayram.contracts.Language` and no account has chosen it yet.
    """

    #: Largest first. A language no account uses is ABSENT rather than present at zero:
    #: nobody reading the bot in English is not a measurement of English.
    languages: tuple[LanguageMix, ...]
    #: Every account counted, which — because ``ui_language`` is ``NOT NULL`` — equals the
    #: sum of the entries above. Published anyway; see the class docstring.
    accounts: int


@dataclass(frozen=True, slots=True)
class ActivityPoint:
    """One night's DAU / WAU / MAU, from ``user_activity_snapshots``. The history of
    :class:`ActiveAccounts`.

    **The three counts are NESTED CUTOFFS on one population, not three disjoint buckets.**
    Every account in ``day`` is in ``week`` and every account in ``week`` is in ``month``
    (``day ⊆ week ⊆ month``), because all three come from one ``last_seen_at`` predicate
    evaluated at one instant. They may therefore be drawn as three lines and never stacked,
    never summed, and never added to a total: a stacked area chart of these three would
    triple-count everybody active today, and the resulting top line would be a number no
    query can produce.

    A day the snapshot job did not run has NO row and this series has no point for it —
    zero-filling would report that nobody used the bot that day, a fabricated measurement
    wearing a chart line. The table's own docstring argues that at length, and it is also
    why the series cannot be back-filled: ``users.last_seen_at`` is a gauge that was
    overwritten, so history exists only from the first night the job ran.
    """

    #: The database's own bucket key, ``YYYY-MM-DD``, kept as text exactly as
    #: :class:`BucketPoint` keeps it — the string the grouping used travels to the wire.
    bucket: str
    #: That key as an aware instant, parsed once here.
    started_at: datetime
    #: ``active_24h_accounts``. Named ``day`` to match :class:`ActiveAccounts`, whose tiles
    #: this series is the history of; the COLUMN keeps its honest ``active_24h_accounts``
    #: name because a rolling 24-hour count is not a calendar-day DAU.
    day: int
    #: ``active_7d_accounts``.
    week: int
    #: ``active_30d_accounts``. Bounded by deployment age for the first thirty days, which
    #: is a ramp that looks like growth and is not.
    month: int


@dataclass(frozen=True, slots=True)
class TopGenerator:
    """One customer on the identified top-generators list, ranked by songs DELIVERED.

    **This view intentionally carries identity**, and it is one of exactly two in this
    package that do. The owner is the sole operator of this panel and has decided that an
    account holder's Telegram identity may be shown to them directly, with an AUDIT ENTRY
    rather than a reveal gate. So it is served on ``RECORDS_READ`` — the permission the
    ``/users`` records screen already stands on — from its own route, which writes an audit
    row the way every other record read does. It is **not** part of the ``DASHBOARD_READ``
    surface, and that separation is the whole of what keeps the dashboard's blanket
    exemption from masking true: every other aggregate in this package remains
    personal-data-free, so nothing about this decision reaches them.

    The reveal / step-up machinery is untouched by that decision and stays load-bearing:
    free text, media and phone numbers are still ``POST /reveal`` alone. **The recipient's
    name is not here and must not be added.** The decision covers the ACCOUNT HOLDER — the
    person who pays and whom an operator answers to — not the third party a song is about,
    who never consented to anything and whose name ``briefs.recipient_name_display`` holds
    behind the masking serializer.

    ``delivered_songs`` and ``orders_created`` are two numbers because the gap between them
    is the whole story of a heavy user: somebody with forty orders and three deliveries is
    not a top generator, they are a support case.
    """

    #: Present on every row, and never ``None``: ``orders.telegram_user_id`` is ``NOT NULL``
    #: and the ranking is keyed to it, so there is no anonymous row to render here the way
    #: there is on :class:`RecentSubscriber`.
    #:
    #: **An erased customer is NOT excluded from this list, and a reader must not assume
    #: they are.** ``/forget`` reaches the receipts (``plan_purchases``, ``topup_purchases``,
    #: ``credit_ledger``, ``bot_membership_events``, ``payment_intents``), deletes the
    #: ``user_profiles`` row and keeps the ``users`` row on purpose — an operator's block
    #: must outlast a data-subject request. It does not touch ``orders`` at all: there is no
    #: per-user order erasure, only the time-based sweep in ``bayram.db.purge``
    #: (``purge_user`` is planned and does not exist — ``ADMIN_PANEL_PLAN`` §9.3). So an
    #: account that sent ``/forget`` keeps ranking here, under this id, with
    #: :attr:`telegram_username` and :attr:`first_name` ``None``, until its orders age out.
    #: That id is the same one ``GET /api/users`` already publishes from the surviving
    #: ``users`` row, so this list discloses nothing that screen does not — but it is a
    #: state to render, not a row this read filters away.
    telegram_user_id: int
    #: Telegram's ``@handle`` WITHOUT the ``@``, from ``user_profiles``. ``None`` when the
    #: account has none (Telegram does not require one) or has no profile row at all.
    telegram_username: str | None
    first_name: str | None
    #: Orders whose ``delivered_at`` fell in the read's window — every delivery ever, when
    #: there is no window. The ranking key.
    delivered_songs: int
    #: Orders this account CREATED in the SAME window, on ``created_at`` — not the lifetime
    #: count. A lifetime number under a caption naming a week would be read as a number
    #: about that week; :func:`~bayram.db.admin.audience_lists.top_generators` argues it and
    #: ``tests/test_db/test_audience_lists.py`` pins it. Two consequences, neither a bug:
    #: the pair is **not** a conversion rate (an order created before the window and
    #: delivered inside it is in :attr:`delivered_songs` only), and this can legitimately be
    #: ``0`` beside a positive delivery count — a measurement, not a missing number.
    orders_created: int
    #: The language the BOT speaks to them in — see :class:`LanguageMix`; not the song's.
    ui_language: Language
    #: ``users.created_at``, i.e. FIRST CONTACT and not the first order — the same
    #: distinction :attr:`UserListItem.account_created_at` documents.
    first_seen_at: datetime
    #: ``MAX(orders.delivered_at)``. ``None`` for an account with orders but no delivery,
    #: which is exactly the support case above and must not render as a date.
    last_delivered_at: datetime | None


@dataclass(frozen=True, slots=True)
class RecentSubscriber:
    """One recent starter-plan purchase, with the buyer's identity and what they have left.

    Identified for the reason :class:`TopGenerator` states, on the same ``RECORDS_READ``
    route, audited the same way, and outside ``DASHBOARD_READ`` in the same way. The
    recipient's name is likewise absent and stays absent.

    **``is_stub_rail`` travels with the money, always.**
    :class:`~bayram.checkout.StubCheckoutProvider` stamps ``is_paid=True`` having contacted
    nobody and settled nothing (``provider == "stub"``), so a stub sale is
    indistinguishable from a real one on every column except this one. Collapsing it — or
    summing these amounts across providers — turns a demo run into revenue on a screen
    somebody makes decisions from. ``currency`` is part of the key for the same reason and
    is never summed across: a total in two currencies is a figure in an invented unit.

    **An EXPIRED plan with songs left is BREAKAGE, not headroom.** ``songs_included`` minus
    ``songs_used`` is money the customer paid and will not now receive value for; on a plan
    still running the same subtraction is an obligation this deployment still owes. The two
    are the same arithmetic and opposite facts, so :attr:`plan_ends_at` has to be read
    against the clock before the remainder means anything, and the two states must render
    differently — the finance surface already keeps them apart as
    ``PlanLiability.breakage_songs`` and ``PlanLiability.unconsumed_songs``.
    """

    #: ``None`` after ``/forget``: ``bayram.db.credit_erasure.forget_account`` nulls it and
    #: keeps the receipt, because "was this customer charged for songs they never got?"
    #: must stay answerable. A ``None`` here is a lawful erasure and never a missing write,
    #: and the row is rendered rather than dropped — a purge is a state, not an error.
    telegram_user_id: int | None
    #: From ``user_profiles``, and therefore ``None`` for a purged account whose profile row
    #: was deleted outright as well as for an account that simply has no handle.
    telegram_username: str | None
    first_name: str | None
    plan: PlanKind
    #: Minor units (UZS tiyin) — the unit the rail quotes, never converted here.
    amount_minor: int
    #: ISO-4217. Part of the key; see the class docstring.
    currency: str
    #: The rail that answered the charge, raw, as ``plan_purchases.provider`` stored it.
    provider: str
    #: ``provider == bayram.checkout.STUB_PROVIDER_NAME``. Derived at the read and carried on
    #: the row so no later layer has to know the constant to stay honest.
    is_stub_rail: bool
    #: ``plan_purchases.created_at`` — when the charge was recorded.
    purchased_at: datetime
    #: The BUSINESS clock, and deliberately not named ``*_expires_at``: no sweep reads it
    #: and no purge acts on it (``models/plan_purchase.py`` argues the naming).
    plan_ends_at: datetime
    #: Stored on the receipt rather than read from settings, so a package change tomorrow
    #: cannot retroactively shrink a plan somebody already paid for.
    songs_included: int
    #: Minted one at a time by ``credits._mint_plan_song``. A refund does not move it back.
    songs_used: int


@dataclass(frozen=True, slots=True)
class VendorCostPerSong:
    """One vendor's cut of the cost-per-delivered-song figure, and its coverage.

    :class:`CostPerDeliveredSong` answers "what does a song cost"; this answers "and who
    charged us for it", which is the only version of the number an operator can act on —
    the remedy for an expensive song is a different model or a different vendor, and the
    aggregate names neither.

    **The gap between :attr:`attributed_orders` and :attr:`delivered_orders` is the
    COVERAGE of this figure and must be published beside it.** They are two different
    counts: the first is how many delivered orders have any call from THIS vendor
    attributed to them, the second is every delivered order in the window. An order rendered
    before the usage ledger existed carries no calls at all; an order that never needed this
    vendor carries none of its calls. Both widen the gap, and an average taken over the
    covered orders and rendered against the full cohort reads as a complete figure when it
    describes a fraction — which is the same error ``costed_calls`` exists to prevent one
    level down, at the price of one number instead of two.

    ``cost_usd`` is ``None`` — never ``0.0`` — when no call from this vendor in the window
    carried a cost. See :class:`CostProvenance`: a vendor-reported zero and an unpriced call
    are different facts, and this shape must not merge them.
    """

    vendor: Vendor
    #: Summed over the priced rows alone. ``None`` when nothing in the window was priced.
    cost_usd: float | None
    #: Every delivered order in the window — the cohort the figure is ABOUT.
    delivered_orders: int
    #: How many of them carry a call from this vendor — the cohort the figure is FROM.
    attributed_orders: int

    @property
    def cost_per_song_usd(self) -> float | None:
        """``cost_usd / delivered_orders``, or ``None`` when that is undefined.

        Over ``delivered_orders`` and not ``attributed_orders``, deliberately: the question
        is what a shipped song costs, and dividing by the covered subset would report the
        cost of the orders we happen to have instrumented — a figure that IMPROVES when
        instrumentation gets worse. Read it with :attr:`attributed_orders` beside it, which
        is what says how much of the cohort the numerator actually covers.

        ``None`` for an unpriced vendor and ``None`` for a window with no delivery. A
        ``0.0`` for either would put a free song on the card.
        """
        if self.cost_usd is None or self.delivered_orders <= 0:
            return None
        return self.cost_usd / self.delivered_orders


@dataclass(frozen=True, slots=True)
class VendorUnitsPerSong:
    """What one delivered song CONSUMES from one vendor, in that vendor's own units.

    The unit analogue of :class:`VendorCostPerSong`, and the reason it is a separate shape:
    money has one axis and these do not.

    **THE THREE UNIT FAMILIES DO NOT SHARE AN AXIS.** Tokens, billed characters and
    milliseconds of audio are three incommensurable quantities, so each is a SEPARATE ROW
    on any table and a separate chart — never three series on one pair of axes, never
    summed, never totalled into a "units" column. A chat completion has no
    ``billed_characters`` and a speech synthesis has no tokens; each is ``None`` for the
    families nobody measured, which is what ``vendor_usage`` already answers by declaring no
    default on any quantity column. A ``0`` would say the vendor charged us for nothing.

    **``total_tokens`` is a CONSUMPTION measure and never a remaining balance.** It counts
    what was spent, it only ever grows, and no reading of it says anything about what is
    left — the remaining side is ``vendor_balances`` (:class:`VendorBalanceState`), a
    different table with a different clock, polled by the worker. A tile that put a token
    count under a "remaining" heading would be reporting spend as headroom.
    """

    vendor: Vendor
    #: Prompt plus completion, summed over the priced-or-not rows that recorded it.
    total_tokens: int | None
    billed_characters: int | None
    audio_ms: int | None
    #: The denominator of all three averages: every delivered order in the window. The
    #: coverage caveat :class:`VendorCostPerSong` states applies here unchanged.
    delivered_orders: int

    @property
    def tokens_per_song(self) -> float | None:
        """``total_tokens / delivered_orders``. ``None`` when either is absent or zero."""
        if self.total_tokens is None or self.delivered_orders <= 0:
            return None
        return self.total_tokens / self.delivered_orders

    @property
    def characters_per_song(self) -> float | None:
        """``billed_characters / delivered_orders``. Its own row on its own axis."""
        if self.billed_characters is None or self.delivered_orders <= 0:
            return None
        return self.billed_characters / self.delivered_orders

    @property
    def audio_ms_per_song(self) -> float | None:
        """``audio_ms / delivered_orders``, still in milliseconds. Never seconds here: the
        column is milliseconds and a unit conversion at this layer is a conversion the wire
        schema cannot see happening."""
        if self.audio_ms is None or self.delivered_orders <= 0:
            return None
        return self.audio_ms / self.delivered_orders


@dataclass(frozen=True, slots=True)
class CostProvenance:
    """How the window's money numbers were ARRIVED AT: one row per ``cost_source``.

    Every existing reader on this surface collapses provenance to a MIN/MAX
    ``is_cost_mixed`` boolean — :class:`VendorUsageRollup`, :class:`VendorUsageTotals`,
    :class:`VendorSpendSplit` and :class:`CostPerDeliveredSong` all publish one
    :class:`~bayram.contracts.CostSource` and a "they disagreed" flag — so on the wire today
    the actual MIX is not reconstructible: an operator can be told the figure is mixed but
    never that nine-tenths of it is arithmetic against a rate somebody typed into an
    environment variable. This shape is the breakdown that boolean summarises, and it exists
    so a spend total can be read with its evidence.

    **A ``None`` source is its OWN bucket and means NOT PRICED — it is not a zero and not an
    absence of data about the calls.** The calls happened and were recorded; no cost could
    be computed for them, because no rate is configured and the vendor reported nothing.
    ``cost_usd`` for that bucket is therefore ``None`` while ``calls`` is positive, and that
    combination is the point of the row.

    **"0 reported" and "not priced" must never render the same, and the case is real rather
    than theoretical.** OpenRouter's LLM leg typically reports ``usage.cost`` as a genuine
    ``0.0`` on a ``:free`` model — ``_reported_cost`` KEEPS that zero deliberately
    (``src/bayram/providers/llm/openai_compat.py:329`` and its helper), because it is the
    vendor telling us the call was free and it reconciles against an invoice line of zero.
    That lands here as :attr:`~bayram.contracts.CostSource.VENDOR_REPORTED` with
    ``cost_usd == 0.0``: MEASURED, and worth showing as such. A rate-card-only vendor with
    no configured rate lands in the ``None`` bucket with ``cost_usd is None``: UNMEASURED.
    One says "this cost nothing", the other says "nobody could say" — collapsing them is how
    a deployment concludes its rendering pipeline is free.
    """

    #: ``None`` is a real member of this grouping and means "no cost could be computed for
    #: these calls", never "these calls cost nothing".
    cost_source: CostSource | None
    #: Calls in this provenance bucket. Always a measured count, in every bucket.
    calls: int
    #: Their summed cost. ``None`` in the unpriced bucket by construction; ``0.0`` is a
    #: legitimate value in the ``VENDOR_REPORTED`` bucket and means the vendor said zero.
    cost_usd: float | None


# ---------------------------------------------------------------------------
# The redirect payment rail (PAYME_INTEGRATION §2, DECISIONS.md D11)
#
# Three tables with no read layer until now, and one property that governs every shape
# below: **money survives erasure and the buyer does not.**
# ``payment_intents.telegram_user_id`` is nullable for exactly one reason — ``/forget`` nulls
# it — so ``telegram_user_id`` is ``int | None`` on every view here and a ``None`` is a STATE
# (the buyer was erased) rather than a gap. Two further consequences a reader has to carry:
# a paid intent with no receipt is LEGITIMATE (``db/payme.py::_settle`` claims the intent and
# writes no sale when the buyer is already gone: the money moved, there is nobody left to
# grant a credit to, and refusing would leave the rail retrying a charge it has taken), and a
# transaction whose intent is missing is ordinary after thirteen months, because terminal
# unpaid intents are deleted at 400 days while ``payme_transactions`` is on no retention bound
# at all and there are no foreign keys anywhere.
#
# The masking decision is NOT made here. These views carry the raw nullable column; the
# response layer (``bayram.admin.serializers.redaction``) decides what a role may see, exactly
# as it does for orders. A view model that pre-masked would be a second place that policy
# lives, and the two would diverge on the first exception.
# ---------------------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class CheckoutSeen:
    """The rail configuration MEASURED off the newest intent, never read from settings.

    This exists because the admin process cannot read a single one of the three switches that
    decide whether the rail is selling. ``Settings.checkout_provider`` (stub or payme) is
    loaded from the BOT's env file; ``PaymeSettings.payme_enabled`` lives in the gateway's own
    ``/etc/bayram/payme.env``; only the Redis pause key is reachable. Declaring a
    ``checkout_provider`` field on ``AdminSettings`` was the obvious alternative and is the
    trap: it would read ``.env.admin`` — a DIFFERENT file from the one the bot loads — and
    render ``stub`` with total confidence while the bot sold through Payme.

    So the panel reports what was actually written, by the process that actually wrote it: the
    newest ``payment_intents`` row's ``provider``, ``merchant_id`` and ``is_sandbox``, with
    ``seen_at`` beside them so a stale reading is VISIBLY stale rather than quietly wrong.
    ``None`` from the query means no checkout has ever been opened on this deployment, which
    is a different sentence and gets a different screen.
    """

    #: ``payment_intents.provider`` — ``'payme'`` for a real link, whatever a future rail
    #: writes for one of its own. Never collapsed with the receipts' provider column: a stub
    #: sale and a rail sale must not merge into one settled figure.
    provider: str
    #: The cashbox the newest link was issued for. ``'placeholder'`` until credentials arrive,
    #: and rendering that literal is more honest than hiding it.
    merchant_id: str
    #: Whether that link was a rehearsal. Surfaced per row and on the header rather than
    #: subtracted from a revenue figure — the receipts tables have no ``is_sandbox`` column,
    #: so any "real money only" total would be a second, differently-computed rollup that can
    #: disagree with the dashboard's finance card.
    is_sandbox: bool
    #: ``created_at`` of the row these three came from. The provenance, not a clock reading.
    seen_at: datetime


@dataclass(frozen=True, slots=True)
class IntentStateCount:
    """How many intents are in one ``PaymentIntentState``. Absent states are not zero rows."""

    state: str
    count: int


@dataclass(frozen=True, slots=True)
class IntentFunnel:
    """Where a window's payments got to, plus the split that says WHY they expired.

    States with no rows are ABSENT from :attr:`states` rather than present at zero — the
    standing rule, and sharper on money than on orders: a zero bar is a claim about payments
    nobody attempted on a day this rail may not have been switched on.

    **The expiry split is the only derived number here and it is the one worth having.** An
    intent that expired with no rail-side transaction is a customer who never reached the
    payment form; one that expired after a transaction reached the form and something went
    wrong there. Those are two different problems with two different owners, and the schema
    records neither — the split is a read-time ``EXISTS`` over ``payme_transactions``, needing
    no column, no migration and no backfill, exactly as ``payme.cli._funnel`` computes it.
    """

    states: tuple[IntentStateCount, ...]
    #: Expired having been held by at least one rail-side transaction: they got to the form.
    expired_after_transaction: int
    #: Expired with no transaction at all: they never got there. The abandonment number.
    expired_with_no_transaction: int


@dataclass(frozen=True, slots=True)
class SettlementSnapshot:
    """The three-way settlement count, and the fourth number without which it lies.

    ``payme_sql.settlement_counts`` produces the first three in ONE statement because they are
    only meaningful against each other. The fourth — settlements a HUMAN made through
    ``python -m bayram.payme.cli settle`` — is what stops the identity slandering the recovery
    button: a force-settled intent has no performed transaction at all, so the honest identity
    is ``transactions_performed + operator_settlements == receipts_written`` and NOT the
    two-way equality ``settlement_counts``' own docstring states for the rail-only path.
    Publishing the three raw numbers alone makes every use of the recovery button look like a
    defect, which is how a monitoring alert gets muted.

    ``grants_written`` is the SINGLE-SONG SUBSET and ``grants <= receipts`` is expected: a plan
    sale writes a receipt and no credit at purchase, because a plan mints songs as they are
    used. Only ``grants > receipts`` is strictly impossible.

    **All four at zero is not a pass.** It is either "nothing settled in your range" or "this
    rail has never settled anything", and the two need different screens — which is why
    ``has_settled_any_intent`` is measured with the window deliberately ignored and travels
    beside this shape rather than being inferred from it.
    """

    transactions_performed: int
    receipts_written: int
    grants_written: int
    operator_settlements: int


@dataclass(frozen=True, slots=True)
class AttentionCounts:
    """The three populations an operator can actually do something about. Not a defect list.

    Deliberately three and not five. The expiry sweep's and the stale-transaction sweep's own
    inputs — lapsed pending intents, transactions stuck in ``created`` — are excluded, because
    listing a backlog the system drains on its own teaches operators to ignore every count on
    the page.

    Read :attr:`paid_with_no_receipt`'s docstring before treating it as an incident.
    """

    #: ``awaiting`` intents whose holding transaction has been in ``created`` longer than the
    #: rail's own timeout. The customer is at a payment form that has stopped answering.
    awaiting_held_past_timeout: int
    #: Paid, and the customer was never told. **Erased buyers are excluded**: there is nobody
    #: to tell and ``notified_at`` will therefore never be stamped, so including them would
    #: produce a backlog that never drains. Mirrors ``payme_sql.unnotified_settled_intents``.
    paid_never_announced: int
    #: Paid with no receipt in either receipts table. **Dominated by erased buyers and not a
    #: defect list.** ``db/payme.py::_settle`` claims the intent and writes NO sale when
    #: ``telegram_user_id IS NULL`` — ``/forget`` ran between the payment starting and
    #: settling, the money moved, and refusing would leave the rail retrying a charge it has
    #: already taken. That is also what trips the settlement identity, so the two numbers are
    #: read together or neither is readable.
    paid_with_no_receipt: int


@dataclass(frozen=True, slots=True)
class IntentListItem:
    """One started payment, with the whole fulfilment chain answered as booleans.

    The chain columns — :attr:`has_receipt`, :attr:`has_grant`, :attr:`transaction_count`,
    :attr:`latest_transaction_state` — come from CORRELATED SUBQUERIES on the shared
    ``idempotency_key`` and never from a ``LEFT JOIN payme_transactions``. The relation is 1:N:
    an intent accumulates a transaction per declined card, so a join fans every money column
    out once per transaction and any aggregate over the result double-counts the sale.

    ``telegram_user_id`` is the RAW nullable column. ``None`` means ``/forget`` ran and means
    nothing else — not a bug, not fraud, not an anonymous purchase. Masking and the explicit
    "this buyer was erased" fact are decided at the response boundary, where every other
    identified surface in this panel decides them.

    There is deliberately no ``idempotency_key`` field. It is shaped
    ``topup:{telegram_user_id}:{scope}:{seq}`` and therefore CONTAINS the customer's Telegram
    id, which is the precise leak ``public_ref`` exists to prevent; it stays a server-side join
    key and never reaches a view model, a DOM node or a support ticket.
    """

    intent_id: UUID
    #: The only identifier that crosses to the rail: 24 opaque hex characters. What a customer
    #: reads out over the phone, and therefore what the panel is searched by.
    public_ref: str
    created_at: datetime
    valid_until: datetime
    state: str
    product: str
    #: Both NULL for a single song; both present for a plan, enforced by a CHECK.
    plan_songs: int | None
    plan_days: int | None
    amount_minor: int
    currency: str
    provider: str
    merchant_id: str
    is_sandbox: bool
    #: ``None`` means erased. See the class docstring.
    telegram_user_id: int | None
    transaction_count: int
    #: The newest transaction's state by ``payme_time``, or ``None`` when the rail has never
    #: opened one against this intent — which is itself the answer to most support calls.
    latest_transaction_state: str | None
    latest_perform_time: datetime | None
    has_receipt: bool
    #: A GRANT under this intent's key. **False is normal for a plan sale**, which writes a
    #: receipt and no credit at purchase; treating it as a fault is the regression this field's
    #: test exists to catch.
    has_grant: bool
    settled_at: datetime | None
    #: ``'payme'`` when the rail moved the money, ``'operator:<ref>'`` when one of us did.
    #: The first question of any reconciliation, kept raw here and classified on the wire.
    settle_note: str | None
    notified_at: datetime | None


@dataclass(frozen=True, slots=True)
class IntentDetail:
    """:class:`IntentListItem`'s field list, as its own type. The dossier's head.

    Identical today and separate on purpose: the detail view is where a field that costs a
    subquery per row (a receipt reference, a plan's consumption) will land, and sharing the
    class would put that cost on every row of every page. Splitting later means changing every
    call site; splitting now costs one class.
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
    telegram_user_id: int | None
    transaction_count: int
    latest_transaction_state: str | None
    latest_perform_time: datetime | None
    has_receipt: bool
    has_grant: bool
    settled_at: datetime | None
    settle_note: str | None
    notified_at: datetime | None


@dataclass(frozen=True, slots=True)
class IntentReferenceMatch:
    """Which intent a reference an operator was READ OVER THE PHONE belongs to.

    Two identifiers can reach an intent from outside: its own ``public_ref`` and any of its
    rail-side transaction ids. :attr:`matched_on` says which one answered, so a support agent
    who typed a transaction id into the reference box learns that rather than wondering why the
    lookup "worked differently". The intent's ``idempotency_key`` is deliberately not a third
    option: it contains the customer's Telegram id and must never be searchable from a URL.
    """

    intent_id: UUID
    #: The column that matched: ``'public_ref'`` or ``'payme_transaction_id'``.
    matched_on: str


@dataclass(frozen=True, slots=True)
class RailStateCount:
    """How many rail-side transactions are in one ``PaymeState``. Absent states are omitted."""

    state: str
    count: int


@dataclass(frozen=True, slots=True)
class RailTransaction:
    """One rail-side transaction and the three instants a replay has to be able to repeat.

    ``create_time`` / ``perform_time`` / ``cancel_time`` are PERSISTED and not derived, because
    a replayed method must return the ORIGINAL instant or certification fails; they are carried
    here for the same reason an operator needs them — a settlement our side applied hours after
    the rail believed it had is visible only by comparing them.

    :attr:`cancel_reason` is a BARE INTEGER by argued decision (see
    ``models/payme_transaction.py``): the codes are the rail's own vocabulary, which they extend
    without asking us, so a ``VARCHAR`` mirror could only ever emit a value they do not
    recognise. It is named at the presentation edge, with the raw number always shown beside
    the name. ``None``, never ``0`` — zero is not a reason code.
    """

    #: THEIRS: a 24-character Mongo ObjectId, stored, compared and echoed as TEXT.
    payme_transaction_id: str
    state: str
    #: The RAIL's creation instant. The timeout runs off this and never off ``created_at``.
    payme_time: datetime
    create_time: datetime
    perform_time: datetime | None
    cancel_time: datetime | None
    cancel_reason: int | None


@dataclass(frozen=True, slots=True)
class InboundCall:
    """One inbound JSON-RPC call and how it was answered. The journal, row by row.

    Both identifier columns are nullable and the NULLs are part of the answer rather than gaps
    in it: a call that failed authentication carries neither, a call about an unknown account
    carries ``public_ref`` only, a perform carries both.

    :attr:`reply_code` is ``0`` for success and the JSON-RPC error code otherwise, which is
    NEGATIVE for every protocol fault. The two populations are told apart BY SIGN and there is
    deliberately no second column: a boolean beside the code would be a fact the code already
    states, free to disagree with it.

    :attr:`peer_ip` is the RAIL's data-centre address and never a customer's. This table holds
    no Telegram id, no request body and no header — that absence is the design, and it is what
    keeps the journal off the retention and privacy inventories the other two tables are on.
    """

    id: UUID
    at: datetime
    #: A string and not an enum: an UNKNOWN method is one of the things this journal exists to
    #: record, and a closed type would raise on the way in and lose exactly the row an incident
    #: needs.
    method: str
    public_ref: str | None
    payme_transaction_id: str | None
    reply_code: int
    peer_ip: str | None
    duration_ms: int


@dataclass(frozen=True, slots=True)
class FaultCluster:
    """Inbound calls that were answered with an error, grouped by ``(method, reply_code)``.

    The incident shape: "``CheckTransaction`` answered ``-31003`` 240 times between 02:11 and
    02:19, slowest 4 s" is a sentence an operator can act on, while a list of 240 rows is not.
    ``reply_code = 0`` is excluded by construction — success is not a cluster — and the raw
    integer is carried rather than a name, for :class:`RailTransaction`'s reason.

    :attr:`first_at` and :attr:`last_at` are the whole point beside the count: a fault that
    happened once an hour all night and one that happened 240 times in eight minutes are the
    same number and different incidents.
    """

    method: str
    reply_code: int
    calls: int
    first_at: datetime
    last_at: datetime
    #: The worst single call in the cluster. A max and not a mean, because a mean over a
    #: cluster that contains one timeout hides the timeout.
    slowest_ms: int


@dataclass(frozen=True, slots=True)
class PaymentReceipt:
    """The sale written under one intent's key, from whichever receipts table it landed in.

    One shape over two tables because the ROUTER is what joins two sources and a caller asking
    "was a sale written for this payment?" should not have to know which product it was. The
    two tables' exclusive fields are therefore ``None`` on the other's rows, and :attr:`source`
    — the literal table name — is what says which set is populated rather than a caller
    guessing from a null.

    :attr:`reference` is the rail's own id for the charge: what an operator searches the Payme
    merchant cabinet for. It is the only field here that is useful OUT of band, which matters,
    because the admin process is structurally forbidden the merchant key and so can never
    display the cabinet charge itself.
    """

    #: ``'topup_purchases'`` or ``'plan_purchases'``. The table, spelled as the table.
    source: str
    amount_minor: int
    currency: str
    provider: str
    reference: str | None
    #: Single-song sales only. ``None`` on a plan receipt, which grants nothing at purchase.
    credits_granted: int | None
    #: Plan sales only. ``songs_used`` is the ONE place the fulfilment chain continues past the
    #: purchase — for a single song it stops at the grant, because ``credit_accounts.balance``
    #: is a fungible scalar with no lot structure and no query can say which song a bought
    #: credit rendered.
    songs_included: int | None
    songs_used: int | None
    plan_ends_at: datetime | None
    created_at: datetime


@dataclass(frozen=True, slots=True)
class PaymentGrant:
    """One ``credit_ledger`` movement written under an intent's key.

    A tuple of these, and not one row, because the key is unique per table but the ledger is
    where a future correction would also land; showing "the grant" as a singular would hide the
    second row on the day one exists.

    **The chain stops here for a single song.** ``credit_accounts.balance`` is a fungible scalar
    with no lot structure, so a later ``DEBIT``/``ORDER_RENDER`` cannot be attributed to the
    grant that funded it — whether this customer's money became a song is unanswerable by
    construction, and saying so is better than leaving a panel blank that reads as broken.
    """

    kind: str
    #: Signed. A grant is positive; the sign is carried rather than an absolute value plus a
    #: direction column, because that is how the ledger stores it and a second spelling is a
    #: second chance to get it backwards.
    delta: int
    reason: str
    #: ``credit_ledger.actor`` is nullable, so this is too. A settlement always stamps
    #: ``bayram.db.fulfilment.CHECKOUT_ACTOR``; a ``None`` here would mean a row written by
    #: something that did not name itself, which is worth seeing rather than defaulting away.
    actor: str | None
    created_at: datetime
