"""Wire models for the dashboard — the screen where a rounded-off number does the damage.

Every shape here exists to keep one number from being read as something it is not.

**A rate with no denominator is ``null``, never ``0.0``.** ``successRate`` divides by orders
that reached a TERMINAL state, which :attr:`~hbd.db.admin.views.DeliveryOutcome.success_rate`
already computes and this layer does not recompute — but that property answers ``0.0`` for an
empty window, because a dataclass property has to answer something. On the wire that would
render as "0% delivered" over a deployment that has taken no orders at all, so
:class:`DeliveryView` reports ``null`` there and puts ``terminalCount`` beside the rate. Same
rule as ``sampleCount`` beside the percentiles: the number that says how much evidence there
is travels with the number derived from it.

**``inFlight`` is not a failure.** It is the fourth bucket, outside the denominator, for the
reason spelled out on ``DeliveryOutcome``: counting live orders as failures makes the success
rate fall every time traffic rises.

**Cost is absent from every model in this file.** ``generation_attempts.cost_usd`` defaults
to ``0.0`` and nothing writes it (§views), so a ``costUsd`` field could only ever carry a
column default dressed up as money. What the panel gets instead is
:attr:`CapabilitiesView.is_cost_telemetry` — measured from the rows that are actually there —
so the SPA renders "not instrumented" rather than a chart of zeros.

**A day with no orders is absent from the series.** ``orders_per_day`` omits it and this
layer does not fill it in, even though ``hbd.db.admin.metrics`` says the API layer knows the
requested range: here it usually does not, because ``from``/``to`` are optional, and a
zero-filled range would claim "0 orders" for days before this deployment existed. The caller
that asked for a range is the one that can fill it for rendering.

**Nothing here is personal data.** Counts, enum members, UTC days and error codes — so there
is no masking decision on this screen and no ``is_unmasked`` parameter on any projection.
§12.2 gives DASHBOARD_READ as **R** to OWNER and **M** to the other three; with no personal
column in any of these shapes the two cells produce identical bytes, which is asserted by
test rather than left for a reader to infer.
"""

from __future__ import annotations

from datetime import date, datetime

from pydantic import Field

from hbd.admin.schemas.common import ApiModel
from hbd.admin.serializers.retryability import is_retryable_code
from hbd.contracts import NameStrategy
from hbd.db.admin.sql import TimeWindow
from hbd.db.admin.views import (
    DeliveryOutcome,
    FailureCount,
    LatencySummary,
    NameAnalytics,
    OrdersPerDay,
    ReadCapabilities,
    SimilarityBucket,
    StrategyAnalysis,
    StrategyOutcome,
)

__all__ = [
    "CapabilitiesView",
    "DeliveryView",
    "FailureView",
    "LatencyView",
    "NameAnalyticsView",
    "OrdersPerDayView",
    "PulseView",
    "SimilarityBucketView",
    "StrategyAnalysisView",
    "StrategyOutcomeView",
    "WindowView",
    "to_capabilities_view",
    "to_delivery_view",
    "to_failure_view",
    "to_latency_view",
    "to_name_analytics_view",
    "to_orders_per_day_view",
    "to_pulse_view",
    "to_similarity_bucket_view",
    "to_strategy_analysis_view",
    "to_strategy_outcome_view",
    "to_window_view",
]


class DeliveryView(ApiModel):
    """Order outcomes over the whole record, and the one rate the panel leads with."""

    total: int
    delivered: int
    failed: int
    cancelled: int
    #: Every non-terminal state, collapsed. Outside the ``successRate`` denominator.
    in_flight: int
    #: ``delivered + failed + cancelled`` — the denominator, on the wire beside the quotient
    #: so "100%" from two orders cannot be read as a measurement.
    terminal_count: int
    #: ``null`` when nothing has reached a terminal state. Not ``0.0``: see the module
    #: docstring — an empty window has no success rate, it does not have a bad one.
    success_rate: float | None


class LatencyView(ApiModel):
    """``created_at`` → ``delivered_at`` in seconds, by nearest-rank percentile.

    Nearest rank, so both numbers are durations that were actually observed rather than
    interpolated ones. ``sampleCount`` is first because it is what makes the other two
    readable: ``p95 = 4.0`` over three delivered orders is a fact about three orders.
    """

    sample_count: int
    p50_seconds: float | None
    p95_seconds: float | None


class FailureView(ApiModel):
    """One error code's share of failed attempts in the window."""

    #: ``null`` groups every failure whose writer recorded no code at all.
    error_code: str | None
    count: int
    share: float
    #: Tri-state. ``null`` means no class in ``hbd.errors`` claims this code, so the panel
    #: says "unknown" instead of offering a retry that cannot help — see
    #: :mod:`hbd.admin.serializers.retryability` on why this is a hint about the class of
    #: failure and not a promise about any one attempt.
    is_retryable: bool | None


class OrdersPerDayView(ApiModel):
    """One UTC day of volume. Days with no orders are absent, never zero-filled."""

    day: date
    total: int
    delivered: int
    failed: int
    paid: int


class StrategyOutcomeView(ApiModel):
    """How one candidate orthography fared under acoustic verification.

    ``attempts`` counts only the rows where verification actually ran, so a disabled
    verifier reads as no data rather than as every strategy failing.
    """

    strategy: NameStrategy
    attempts: int
    verified: int
    verification_rate: float


class SimilarityBucketView(ApiModel):
    """One bar of the match-confidence histogram.

    ``from``/``to`` rather than ``lower``/``upper`` because ``from`` is the name the chart
    has always used and a rename on the wire is a rename in every consumer. ``from`` is a
    Python keyword, so the field is ``from_`` with an explicit alias — the one place in this
    package where the generated camelCase name is overridden, and it is overridden towards
    the SPA rather than away from it.
    """

    from_: float = Field(alias="from")
    to: float
    count: int


class StrategyAnalysisView(ApiModel):
    """One orthography's row: the bake-off bar, its distribution, and its cliff count.

    A strict superset of :class:`StrategyOutcomeView`, deliberately — the bake-off chart
    consumes exactly those four fields and must keep working against this response without
    a prop change.
    """

    strategy: NameStrategy
    attempts: int
    verified: int
    verification_rate: float
    #: Rows carrying a similarity score. Not ``attempts``: a verdict can be recorded with no
    #: score, and the histogram's denominator is its own number.
    scored: int
    #: ``null`` when this deployment publishes no threshold — never ``0``, which would read
    #: as "nothing sits near the cliff".
    near_threshold: int | None
    buckets: list[SimilarityBucketView]


class WindowView(ApiModel):
    """The half-open ``[from, to)`` the numbers were counted over. ``null`` for all time."""

    from_: datetime = Field(alias="from")
    to: datetime


class NameAnalyticsView(ApiModel):
    """``GET /api/metrics/name-analytics`` — the whole ``/generations/names`` screen.

    **``hasRecordedAttempts`` is what makes an empty window readable.** With ``attempts: 0``
    it is the difference between "nothing in the range you chose" (§11.4 empty-FILTERED,
    which has a remedy — widen the window) and "verification has never run here"
    (empty-VIRGIN, which does not). A zero cannot say which, and a chart of twenty empty
    bars saying neither is the failure this field exists to prevent.

    **``threshold`` and ``nearThreshold`` are ``null`` together.** The worker owns
    ``name_match_min_similarity``; this process knows it only if the deployment published it
    to the panel. Unpublished means no marker and no cliff count, rather than a default
    nobody configured drawn on the one chart whose job is to argue about where that marker
    belongs.

    **Nothing here is personal data** — strategies, counts, bucket edges and the verifier's
    own scores. No name, no candidate text, no transcript, at any role.
    """

    #: Echoed so the empty state can name the range it found nothing in.
    window: WindowView | None
    threshold: float | None
    #: How near "near" is. On the wire so the SPA labels the marker from the server's number.
    threshold_band: float
    bucket_count: int
    attempts: int
    verified: int
    #: ``null`` when nothing was verified in the window: no denominator, no rate.
    verification_rate: float | None
    scored: int
    near_threshold: int | None
    has_recorded_attempts: bool
    #: Best first, by rate then volume. A strategy with no attempts in the window is absent
    #: rather than present at zero — the chart renders "no attempts" from the gap.
    strategies: list[StrategyAnalysisView]
    #: The distribution summed over every strategy. Always ``bucketCount`` entries.
    buckets: list[SimilarityBucketView]


class CapabilitiesView(ApiModel):
    """What this deployment can honestly answer. Measured from the schema and the rows.

    Named one-to-one with :class:`~hbd.db.admin.views.ReadCapabilities`. A capability
    renamed on the way to the wire is one that drifts from the probe that produces it, and
    the SPA branches on these to decide whether to draw a panel or say "not instrumented".
    """

    is_cost_telemetry: bool
    is_latency_telemetry: bool
    is_asset_storage_key_recorded: bool
    is_chat_capture: bool
    is_payment_ledger: bool
    is_state_transition_log: bool


class PulseView(ApiModel):
    """``GET /api/ops/pulse`` — the whole dashboard in one round trip.

    ``capabilities`` travels inside the payload rather than being left to a second request,
    because every other block here is only readable next to it: ``failures`` with no cost
    figure is a list an operator would otherwise assume was missing one.
    """

    delivery: DeliveryView
    latency: LatencyView
    failures: list[FailureView]
    capabilities: CapabilitiesView


# ---------------------------------------------------------------------------
# projections
# ---------------------------------------------------------------------------
def to_delivery_view(outcome: DeliveryOutcome) -> DeliveryView:
    """Project the outcome counts. The rate is taken from the view model, never recomputed."""
    terminal = outcome.delivered + outcome.failed + outcome.cancelled
    return DeliveryView(
        total=outcome.total,
        delivered=outcome.delivered,
        failed=outcome.failed,
        cancelled=outcome.cancelled,
        in_flight=outcome.in_flight,
        terminal_count=terminal,
        success_rate=outcome.success_rate if terminal > 0 else None,
    )


def to_latency_view(summary: LatencySummary) -> LatencyView:
    return LatencyView(
        sample_count=summary.sample_count,
        p50_seconds=summary.p50_seconds,
        p95_seconds=summary.p95_seconds,
    )


def to_failure_view(failure: FailureCount) -> FailureView:
    """Add the retryability verdict the query layer deliberately refuses to guess at.

    ``failure_breakdown`` will not derive it, because retryability belongs to the exception
    instance and not to the persisted string. The serializer answers from the class that owns
    the code and returns ``None`` when none does, which is the same refusal made legible.
    """
    return FailureView(
        error_code=failure.error_code,
        count=failure.count,
        share=failure.share,
        is_retryable=is_retryable_code(failure.error_code),
    )


def to_orders_per_day_view(day: OrdersPerDay) -> OrdersPerDayView:
    return OrdersPerDayView(
        day=day.day,
        total=day.total,
        delivered=day.delivered,
        failed=day.failed,
        paid=day.paid,
    )


def to_strategy_outcome_view(outcome: StrategyOutcome) -> StrategyOutcomeView:
    return StrategyOutcomeView(
        strategy=outcome.strategy,
        attempts=outcome.attempts,
        verified=outcome.verified,
        verification_rate=outcome.verification_rate,
    )


def to_similarity_bucket_view(bucket: SimilarityBucket) -> SimilarityBucketView:
    return SimilarityBucketView(from_=bucket.lower, to=bucket.upper, count=bucket.count)


def to_strategy_analysis_view(analysis: StrategyAnalysis) -> StrategyAnalysisView:
    """The rate comes off the view model, exactly as ``to_strategy_outcome_view`` takes it."""
    return StrategyAnalysisView(
        strategy=analysis.strategy,
        attempts=analysis.attempts,
        verified=analysis.verified,
        verification_rate=analysis.verification_rate,
        scored=analysis.scored,
        near_threshold=analysis.near_threshold,
        buckets=[to_similarity_bucket_view(bucket) for bucket in analysis.buckets],
    )


def to_window_view(window: TimeWindow | None) -> WindowView | None:
    """Echo the window the caller asked for, or ``None`` for the whole record."""
    return None if window is None else WindowView(from_=window.start, to=window.end)


def to_name_analytics_view(
    analytics: NameAnalytics, *, window: TimeWindow | None
) -> NameAnalyticsView:
    """Project the analysis. The window is echoed from the request, not re-derived."""
    return NameAnalyticsView(
        window=to_window_view(window),
        threshold=analytics.threshold,
        threshold_band=analytics.band,
        bucket_count=analytics.bucket_count,
        attempts=analytics.attempts,
        verified=analytics.verified,
        verification_rate=analytics.verification_rate,
        scored=analytics.scored,
        near_threshold=analytics.near_threshold,
        has_recorded_attempts=analytics.has_recorded_attempts,
        strategies=[to_strategy_analysis_view(item) for item in analytics.strategies],
        buckets=[to_similarity_bucket_view(bucket) for bucket in analytics.buckets],
    )


def to_capabilities_view(capabilities: ReadCapabilities) -> CapabilitiesView:
    return CapabilitiesView(
        is_cost_telemetry=capabilities.is_cost_telemetry,
        is_latency_telemetry=capabilities.is_latency_telemetry,
        is_asset_storage_key_recorded=capabilities.is_asset_storage_key_recorded,
        is_chat_capture=capabilities.is_chat_capture,
        is_payment_ledger=capabilities.is_payment_ledger,
        is_state_transition_log=capabilities.is_state_transition_log,
    )


def to_pulse_view(
    *,
    outcome: DeliveryOutcome,
    latency: LatencySummary,
    failures: tuple[FailureCount, ...],
    capabilities: ReadCapabilities,
) -> PulseView:
    """Assemble the one response. Keyword-only: four aggregates of four different shapes."""
    return PulseView(
        delivery=to_delivery_view(outcome),
        latency=to_latency_view(latency),
        failures=[to_failure_view(failure) for failure in failures],
        capabilities=to_capabilities_view(capabilities),
    )
