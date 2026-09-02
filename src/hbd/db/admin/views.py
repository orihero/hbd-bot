"""Frozen view models the admin read layer returns. No session, no I/O, no clock.

These exist because ``hbd.db.mapping`` cannot serve the admin panel and must not be made
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
(``src/hbd/admin/schemas``) are the layer that owns the wire shape.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from enum import StrEnum
from uuid import UUID

from hbd.contracts import (
    AssetKind,
    CostSource,
    Genre,
    Language,
    NameStrategy,
    Occasion,
    OrderState,
    Script,
    VoiceGender,
)
from hbd.db.enums import GenerationKind
from hbd.db.retention import RetentionClass

__all__ = [
    "CostTelemetry",
    "BriefView",
    "AssetView",
    "AttemptView",
    "OrderListItem",
    "OrderDetail",
    "TimelineSource",
    "TimelineEventKind",
    "TimelineEvent",
    "Timeline",
    "UserListItem",
    "UserDetail",
    "OrdersPerDay",
    "DeliveryOutcome",
    "LatencySummary",
    "FailureCount",
    "StrategyOutcome",
    "ReadCapabilities",
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
        """Mirrors ``BriefRow.is_identity_purged`` — either signal is proof enough."""
        return self.identity_purged_at is not None or self.recipient_name_display is None

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
# Orders
# ---------------------------------------------------------------------------
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

    @property
    def is_identity_purged(self) -> bool:
        """True when a brief exists and its identity columns have been cleared."""
        return self.is_brief_present and (
            self.identity_purged_at is not None or self.recipient_name_display is None
        )

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

    There is deliberately **no** ``last_seen_at`` here. ``users`` is written by
    ``repository._ensure_user``, called only from ``_create_order``, so the row's clock
    advances when an order is *created* and at no other moment — and a person who walks the
    whole wizard without confirming has no row at all. ``last_order_at`` says exactly that,
    and is derived from ``MAX(orders.created_at)`` so it stays true even if a future writer
    changes what ``users.last_seen_at`` means. Phase 3's inbound middleware gives the column
    a real writer; until then the panel's header reads "last order".
    """

    id: UUID
    telegram_user_id: int
    ui_language: Language
    is_blocked: bool
    #: When the ``users`` row was inserted — i.e. when this person's FIRST order was created.
    account_created_at: datetime
    first_order_at: datetime | None
    last_order_at: datetime | None
    order_count: int
    paid_order_count: int


@dataclass(frozen=True, slots=True)
class UserDetail:
    """``/users/{telegramUserId}`` — the list row plus the per-state breakdown."""

    user: UserListItem
    #: Every state with at least one order. Absent states are absent, not zero-filled, so a
    #: reader cannot mistake "none yet" for "counted and empty".
    orders_by_state: tuple[tuple[OrderState, int], ...]
    delivered_order_count: int
    failed_order_count: int


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

    The bake-off ``HBD_NAME_CANDIDATE_ORDER`` is reordered from. Deliberately a superset of
    ``hbd.db.attempts.StrategyStat``: it adds the window's bounds so a reader can tell a
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
