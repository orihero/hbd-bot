"""``GET /api/ops/*`` and ``GET /api/metrics/*`` — the first screen an operator opens.

Fourteen reads, and every one of them answers with something the database counted. The rules
below are what this screen lives or dies by, because a dashboard that rounds a number off is
worse than one that has no number: it is believed.

Thirteen of the fourteen write nothing at all. The fourteenth — the identified
``/dashboard/audience-lists`` — writes one ``admin_audit_log`` row per call and nothing else,
because on that route the log IS the control that replaces the reveal gate.

**Capabilities are MEASURED, never declared.** :func:`~bayram.db.admin.metrics.read_capabilities`
probes the installed schema and the rows that are actually present; nothing on this surface
reads a constant that says what the deployment can do. A hardcoded flag is one somebody
forgets to flip, and the day it is wrong the panel is confidently describing a feature that
is not there.

**Cost is ``null``, not ``0``.** Nothing writes ``generation_attempts.cost_usd`` or
``latency_ms`` yet — the columns default to ``0.0`` and ``0`` — so there is deliberately no
cost figure anywhere in the pulse. What the pulse carries instead is the capability flag the
SPA branches on: ``capabilities.isCostTelemetry`` is false today, and "not instrumented" is
the honest rendering of that. Charting the column defaults would put a made-up dollar figure
on the screen an operator uses to decide what to spend.

**``successRate`` divides by terminal orders only.** :class:`~bayram.db.admin.views.DeliveryOutcome`
already computes it that way and this router exposes that value rather than recomputing one;
counting in-flight orders in the denominator would make the rate fall every time traffic
rises, which is the opposite of what the number is for. The schema layer reports ``null``
when nothing has reached a terminal state at all — see :mod:`bayram.admin.schemas.dashboard`.

**Percentiles are nearest-rank, and ``sampleCount`` travels with them.** Both numbers are
durations that were really observed, and the count that produced them is on the wire beside
them so "p95 = 4s" from three orders is not read as a measurement of the system.

**A day with no orders is absent from the series**, not zero-filled. ``from``/``to`` are
optional here, so this layer frequently does not know what range the caller wants charted,
and inventing zeroes for days before the deployment existed is how a chart grows a flat tail
nobody asked for.

**Nothing on the DASHBOARD_READ surface is personal data.** Counts, enum members, UTC days
and error codes — no name, no note, no transcript, no telegram id. So §12.2's DASHBOARD_READ
**R** cell for OWNER changes nothing there: there is no masking decision to make, no
serializer to route through, and no unmasked variant of any of those responses. That is
stated so a reader who checks the matrix and sees **R** does not go looking for the redaction
those routes do not do.

**This module now also ships ONE identified route, and it is a second router.**
``GET /api/metrics/dashboard/audience-lists`` returns the account holder's Telegram id,
handle and first name unmasked, on ``RECORDS_READ``, writing an audit row on every call —
the owner's decision, recorded in :func:`build_audience_lists_router`. It is a separate
router because the guard is per-router (§12.1 T3) and because the separation is the whole of
what keeps the paragraph above true of the six aggregate routes: they did not become
identified, one route beside them did. **The application must include both routers**;
mounting only the first drops that route with no error anywhere.

**The pulse takes no window.** It is the state of the deployment as a whole; a default window
baked in here would be a policy an operator could not see or argue with, and the five
``/metrics/*`` routes are where a window is asked for explicitly. Either end alone is enough
there: ``?from=`` is charted up to the moment the request was served and ``?to=`` leaves the
series open below (:func:`bayram.admin.window.resolve_window`). The response echoes the range it
counted over, so a chart drawn from one bound is still reproducible from the answer.

**The redesigned dashboard is ONE ROUTE PER SECTION, not one per card.**
``/dashboard/audience``, ``/dashboard/finance``, ``/dashboard/performance``,
``/dashboard/series`` and now ``/dashboard/vendor`` carry the mock's cards and charts between
them. The page refreshes on a timer — the mock's header says "LIVE · 5s" — and eighteen cards
fetched one at a time is eighteen requests per tick against a process that also serves
``/readyz``. The count also matches the cadences the SPA actually wants (fire fast, vendors
slower, cohorts nightly) and the sections a reader of the mock can point at. Fewer would
force the slowest aggregate on the page — the latency percentiles' three round trips — into
the tick of the fastest card.

**The Vendor section is its own route rather than three more fields on the finance one.**
Finance asks what a song costs and what is left over; the vendor section asks which vendor
the money went to, in what units, and how any of it was arrived at — a different cadence and
a different card group. It republishes ``vendorSpend`` and ``vendorBalances`` under the
finance response's own names, from the same functions, because a breakdown fetched without
the total it partitions is a subset waiting to be read as a whole; nothing is republished
under a second name.

**Every windowed card carries its own delta, taken in the same scan.** The prior-period
count is two conditional counts under one predicate spanning both windows
(:func:`~bayram.db.admin.sql.count_pair`), so a card's "+12%" costs one wider index range scan
rather than a second request. Where the caller gave no lower bound there is no previous
period, and ``previous`` and ``change`` are both ``null`` rather than zero.

**Counts zero-fill; money never does.** A bucket with no orders is honestly zero orders. A
bucket with no priced vendor call is ``costUsd: null`` and never ``$0.00`` — the whole
schema beneath it exists to keep those apart, and a chart is the last place the distinction
can be destroyed. And the fill only happens when the request supplied a lower bound, because
with ``?to=`` alone a filled bucket before the first row claims "0" for days this deployment
did not exist. ``isZeroFilled`` says which happened.

**The run-rate card uses a fixed window of its own and echoes it.** The mock labels a
thirty-day net "MRR" and its scaled form "ARR", while the global selector can be set to
Today; computing either over the selector would make "MRR" mean "today's net" and then
annualise it. See :class:`~bayram.admin.schemas.overview.NetRunRateView`.

**``?bucket=hour`` over a long window is REFUSED, never silently coarsened.** A year of
hourly buckets is 8 760 points, which is not a chart — and quietly answering at a different
grain answers a different question with no way for the caller to tell. The refusal is a 422
naming ``bucket``, the same shape ``time_window`` gives for ``to`` before ``from``.

**The plan-liability route takes no window at all**, and that is a decision rather than an
omission: liability is a STATE and not a flow, so a window over it is meaningless — the same
argument the pulse makes for taking none — and the response echoes the ``asOf`` instant it
was computed at so the number stays reproducible. ``now`` is read once in the handler and
threaded into both calls, because a liability count and a utilisation histogram taken
microseconds apart could disagree about a plan that ended between them.

**No outbound call is made from this process.** The system-status strip is assembled from
``read_capabilities`` and from the cached ``vendor_balances`` rows the ARQ worker writes; the
admin process holds no vendor credential and no HTTP client. A "System status" card is
exactly where somebody reaches for one, so the boundary is restated here as well as at the
poller. A component with no writer reports ``NOT_PROBED``; it never reports ``OK``.

**An empty window says so, and says which kind of empty it is.** ``/metrics/name-analytics``
carries ``hasRecordedAttempts`` — measured with the window deliberately ignored — because
``attempts: 0`` alone cannot tell "nothing in the range you chose" from "verification has
never run here", and §11.4 renders those as two different screens with two different
remedies. Zero-filled histogram bars are the same class of lie as a zero-filled day series.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Annotated, Final

from fastapi import APIRouter, Depends, Query

from bayram.admin import audit_sink
from bayram.admin.deps import (
    API_PREFIX,
    Admin,
    Container,
    CurrentAdmin,
    Db,
    Settings,
    require_permission,
)
from bayram.admin.errors import AdminProblem, ProblemError
from bayram.admin.schemas.audience_lists import (
    AudienceListsResponse,
    to_audience_lists_response,
)
from bayram.admin.schemas.dashboard import (
    CapabilitiesView,
    FailureView,
    LatencyView,
    NameAnalyticsView,
    OrdersPerDayView,
    PulseView,
    StrategyOutcomeView,
    to_capabilities_view,
    to_failure_view,
    to_latency_view,
    to_name_analytics_view,
    to_orders_per_day_view,
    to_pulse_view,
    to_strategy_outcome_view,
)
from bayram.admin.schemas.overview import (
    AudienceResponse,
    FinanceResponse,
    PerformanceResponse,
    PlanLiabilityResponse,
    SeriesBucket,
    SeriesResponse,
    VendorResponse,
    to_audience_response,
    to_finance_response,
    to_performance_response,
    to_plan_liability_response,
    to_series_response,
    to_vendor_response,
)
from bayram.admin.security.permissions import Permission
from bayram.admin.window import resolve_window
from bayram.contracts import VendorOperation
from bayram.db.admin.attempts import name_analytics, strategy_outcomes
from bayram.db.admin.audience_lists import (
    DEFAULT_RECENT_SUBSCRIBERS,
    DEFAULT_TOP_GENERATORS,
    MAX_RECENT_SUBSCRIBERS,
    MAX_TOP_GENERATORS,
    recent_subscribers,
    top_generators,
)
from bayram.db.admin.audit import AuditEntry
from bayram.db.admin.balances import vendor_balances
from bayram.db.admin.metrics import (
    delivered_counts,
    delivered_latency,
    delivered_per_bucket,
    delivery_latency,
    delivery_outcome,
    failure_breakdown,
    order_funnel,
    orders_per_day,
    read_capabilities,
)
from bayram.db.admin.overview import (
    account_totals,
    active_accounts,
    activity_history,
    churn_counts,
    language_mix,
    new_accounts_per_bucket,
)
from bayram.db.admin.plan_purchases import (
    plan_bookings_per_bucket,
    plan_liability,
    plan_revenue_totals,
    plan_utilisation,
    subscription_churn,
)
from bayram.db.admin.sql import SeriesGrain, TimeWindow
from bayram.db.admin.topup_purchases import (
    count_unpriced_topups,
    topup_bookings_per_bucket,
    topup_revenue_totals,
)
from bayram.db.admin.vendor_usage import (
    SPENDABLE_EXCLUSIONS,
    cost_per_delivered_song,
    cost_per_delivered_song_by_vendor,
    cost_provenance,
    fake_call_count,
    unattributed_spend,
    units_per_delivered_song_by_vendor,
    vendor_operation_latency,
    vendor_spend_per_bucket,
    vendor_spend_split,
    vendor_usage_totals,
)
from bayram.db.base import utc_now
from bayram.db.enums import AuditAction, AuditReasonCode
from bayram.db.models.admin_audit import ACTOR_USERNAME_LENGTH, AuditOutcome
from bayram.errors import ErrorCode

__all__ = [
    "AUDIENCE_PATH",
    "AUDIENCE_LISTS_PATH",
    "AUDIENCE_LISTS_SUBJECT_TYPE",
    "CAPABILITIES_PATH",
    "FAILURES_PATH",
    "IDENTIFIED_FIELD_NAMES",
    "LATENCY_PATH",
    "NAME_ANALYTICS_PATH",
    "FINANCE_PATH",
    "NAME_STRATEGIES_PATH",
    "ORDERS_BY_DAY_PATH",
    "PERFORMANCE_PATH",
    "PLAN_LIABILITY_PATH",
    "PULSE_PATH",
    "SERIES_PATH",
    "VENDOR_PATH",
    "build_dashboard_router",
    "build_audience_lists_router",
]

#: Full paths, built from the prefix. Routers here are included without one, because the
#: forced-rotation gate compares ``scope["route"].path`` against absolute paths.
_OPS_PREFIX: Final[str] = f"{API_PREFIX}/ops"
_METRICS_PREFIX: Final[str] = f"{API_PREFIX}/metrics"

PULSE_PATH: Final[str] = f"{_OPS_PREFIX}/pulse"
CAPABILITIES_PATH: Final[str] = f"{_OPS_PREFIX}/capabilities"
ORDERS_BY_DAY_PATH: Final[str] = f"{_METRICS_PREFIX}/orders-by-day"
FAILURES_PATH: Final[str] = f"{_METRICS_PREFIX}/failures"
LATENCY_PATH: Final[str] = f"{_METRICS_PREFIX}/latency"
NAME_STRATEGIES_PATH: Final[str] = f"{_METRICS_PREFIX}/name-strategies"
NAME_ANALYTICS_PATH: Final[str] = f"{_METRICS_PREFIX}/name-analytics"

#: The redesigned dashboard's four sections, plus the plan book. One route per section of
#: the mock — see the module docstring on why four and not eighteen.
AUDIENCE_PATH: Final[str] = f"{_METRICS_PREFIX}/dashboard/audience"
FINANCE_PATH: Final[str] = f"{_METRICS_PREFIX}/dashboard/finance"
PERFORMANCE_PATH: Final[str] = f"{_METRICS_PREFIX}/dashboard/performance"
SERIES_PATH: Final[str] = f"{_METRICS_PREFIX}/dashboard/series"
VENDOR_PATH: Final[str] = f"{_METRICS_PREFIX}/dashboard/vendor"
PLAN_LIABILITY_PATH: Final[str] = f"{_METRICS_PREFIX}/plans"

#: The one IDENTIFIED route in this module. A ``/dashboard/`` sibling because it is a section
#: of the same page, and a plural noun because it returns two lists and not one — but it is
#: NOT a DASHBOARD_READ route, and the permission is the only thing that decides that. See
#: :func:`build_audience_lists_router`.
AUDIENCE_LISTS_PATH: Final[str] = f"{_METRICS_PREFIX}/dashboard/audience-lists"

#: ``admin_audit_log.subject_type`` for a read of the identified lists. ``"system"`` from
#: :data:`bayram.db.admin.audit.SUBJECT_TYPES`' closed set, because the subject of this action is
#: a LIST and not any one of the people on it: writing a Telegram id here would pick one row
#: arbitrarily, and writing several is not a thing the column can hold. ``record_count`` is
#: what carries how many identified people the caller was shown.
AUDIENCE_LISTS_SUBJECT_TYPE: Final[str] = "system"

#: The columns this route discloses, named — never their values (§12.4). A reader of the log
#: can therefore see exactly what an ``audience.list`` row means without opening this file,
#: and the day somebody adds a field to the payload the entry stops describing it, which is
#: the review this list exists to force.
IDENTIFIED_FIELD_NAMES: Final[tuple[str, ...]] = (
    "users.telegram_user_id",
    "user_profiles.telegram_username",
    "user_profiles.first_name",
)

#: The grain ``activityHistory`` is served at, and echoed as. Fixed rather than a ``?bucket=``
#: parameter — see the ``audience`` handler for the argument.
_ACTIVITY_BUCKET: Final[SeriesBucket] = SeriesBucket.DAY

#: ``?limit=`` on the identified route, which applies to BOTH of its lists. The two database
#: modules declare their own default and ceiling; this takes the TIGHTER of each pair, so the
#: boundary can never admit a value one of the two reads would have to clamp — and so a
#: future decision to shorten one list is not silently overridden here. On an identified
#: surface the smaller default is also the right way round: fewer people on screen than asked
#: for is a design opinion, more is a disclosure nobody chose.
_DEFAULT_LIST_LIMIT: Final[int] = min(DEFAULT_TOP_GENERATORS, DEFAULT_RECENT_SUBSCRIBERS)
_MAX_LIST_LIMIT: Final[int] = min(MAX_TOP_GENERATORS, MAX_RECENT_SUBSCRIBERS)

#: The vendor operation whose latency the Performance section reports. Music composition is
#: the leg a customer waits on; the other four are milliseconds inside a request nobody
#: watches, and averaging all five would bury the one number that moves the median song time.
_WATCHED_OPERATION: Final[VendorOperation] = VendorOperation.MUSIC_COMPOSE


def build_window(
    since: Annotated[datetime | None, Query(alias="from")] = None,
    until: Annotated[datetime | None, Query(alias="to")] = None,
) -> TimeWindow | None:
    """``?from=&to=`` as a dependency, or ``None`` for the whole record.

    One end is now enough. ``?from=`` alone is charted up to the instant the request was
    served, which is the only end an open range has and is echoed back in ``window`` on
    ``/metrics/name-analytics`` so the number remains reproducible: the response says what it
    counted over even when the request did not. ``?to=`` alone leaves the series open below —
    ``window.from`` comes back ``null``, which is the honest rendering of "since the first row
    there is". :func:`~bayram.admin.window.resolve_window` makes both calls and ``time_window``
    still owns the ordering check, so ``to`` before ``from`` is the same 422 through the same
    path it always was.
    """
    return resolve_window(since, until, now=utc_now())


#: The dependency alias every windowed route annotates with.
Window = Annotated[TimeWindow | None, Depends(build_window)]


def _refuse(message: str, parameter: str) -> ProblemError:
    """A 422 naming the parameter, through the one envelope every failure here uses."""
    return ProblemError(
        AdminProblem(
            code=ErrorCode.INVALID_INPUT, message=message, details={"parameter": parameter}
        )
    )


def build_bucket(
    window: Window,
    settings: Settings,
    bucket: Annotated[SeriesBucket, Query()] = SeriesBucket.DAY,
) -> SeriesBucket:
    """``?bucket=`` as a dependency, refusing a grain that cannot honestly serve the window.

    Three refusals, all 422 and all naming ``bucket``, and all REFUSALS rather than silent
    coarsenings. Answering a request for hourly data at daily resolution answers a different
    question than the one asked, and the caller has no way to notice; a 422 is the same
    shape ``time_window`` already gives for ``to`` before ``from``.

    * ``bucket=hour`` with no window at all: the series would run from the first row ever
      recorded to now, at one point an hour.
    * ``bucket=hour`` over more than ``BAYRAM_ADMIN_DASHBOARD_MAX_HOURLY_WINDOW_DAYS``: eight
      days by default, which is a week plus the delta arm's equal-length predecessor.
    * any grain whose bucket count would exceed ``BAYRAM_ADMIN_DASHBOARD_MAX_SERIES_BUCKETS``:
      750 by default, which clears a year of daily buckets (366) and a month of hourly ones
      (744) and refuses a year of hourly ones (8 760), which is not a chart anybody draws.

    The count is computed from the window's own length rather than from the rows, because
    the refusal has to happen before the query and not after it.
    """
    if bucket is not SeriesBucket.HOUR:
        _refuse_an_oversized_series(bucket, window, settings)
        return bucket
    if window is None or window.start is None:
        raise _refuse("bucket=hour needs a bounded window; give ?from= as well", "bucket")
    span_days = (window.end - window.start).total_seconds() / _SECONDS_PER_DAY
    if span_days > settings.admin_dashboard_max_hourly_window_days:
        raise _refuse(
            "bucket=hour is refused over a window longer than "
            f"{settings.admin_dashboard_max_hourly_window_days} days; use bucket=day",
            "bucket",
        )
    _refuse_an_oversized_series(bucket, window, settings)
    return bucket


def _refuse_an_oversized_series(
    bucket: SeriesBucket, window: TimeWindow | None, settings: Settings
) -> None:
    """The ceiling on points in one series, applied to every grain including the coarse ones."""
    if window is None or window.start is None:
        return
    span = (window.end - window.start).total_seconds()
    per_bucket = _BUCKET_SECONDS[bucket]
    if span / per_bucket > settings.admin_dashboard_max_series_buckets:
        raise _refuse(
            f"bucket={bucket.value} over this window exceeds "
            f"{settings.admin_dashboard_max_series_buckets} points; widen the bucket",
            "bucket",
        )


#: Nominal seconds per bucket, used ONLY to bound the point count before a query runs. A
#: month is approximated at 28 days on purpose: the check has to over-estimate the number of
#: buckets rather than under-estimate it, or the ceiling it enforces is not a ceiling.
_SECONDS_PER_DAY: Final[float] = 86_400.0
_BUCKET_SECONDS: Final[dict[SeriesBucket, float]] = {
    SeriesBucket.HOUR: 3_600.0,
    SeriesBucket.DAY: _SECONDS_PER_DAY,
    SeriesBucket.WEEK: 7 * _SECONDS_PER_DAY,
    SeriesBucket.MONTH: 28 * _SECONDS_PER_DAY,
}

#: The two grains the DATABASE groups at, for each grain a chart may ask for. WEEK and MONTH
#: are queried at DAY and folded in the serializer — see
#: :class:`~bayram.db.admin.sql.SeriesGrain` on why they are not SQL.
_QUERY_GRAIN: Final[dict[SeriesBucket, SeriesGrain]] = {
    SeriesBucket.HOUR: SeriesGrain.HOUR,
    SeriesBucket.DAY: SeriesGrain.DAY,
    SeriesBucket.WEEK: SeriesGrain.DAY,
    SeriesBucket.MONTH: SeriesGrain.DAY,
}

#: The bucket dependency alias the series route annotates with.
Bucket = Annotated[SeriesBucket, Depends(build_bucket)]


def _run_rate_window(settings: Settings, *, now: datetime) -> TimeWindow:
    """The trailing window the net run-rate card is computed over, independent of the request.

    Its own window because "MRR" computed over a selector set to Today would mean today's
    net and then be annualised from it. The response echoes this window, so the number on
    the card can never be read as belonging to the picker above it.
    """
    days = settings.admin_dashboard_run_rate_days
    return TimeWindow(start=now - timedelta(days=days), end=now)


def build_dashboard_router() -> APIRouter:
    """The dashboard surface. One permission, declared once, on the router."""
    router = APIRouter(
        tags=["dashboard"],
        dependencies=[Depends(require_permission(Permission.DASHBOARD_READ))],
    )

    @router.get(PULSE_PATH)
    async def pulse(db: Db) -> PulseView:
        """The whole screen in one round trip, over the whole record.

        Four aggregates and the capability block, because the SPA cannot render any of the
        first four honestly without the fifth: a failure list with no cost column beside it
        reads as a missing feature rather than as an uninstrumented one.
        """
        return to_pulse_view(
            outcome=await delivery_outcome(db),
            latency=await delivery_latency(db),
            failures=await failure_breakdown(db),
            capabilities=await read_capabilities(db),
        )

    @router.get(CAPABILITIES_PATH)
    async def capabilities(db: Db) -> CapabilitiesView:
        """What this deployment can answer, probed rather than declared.

        Its own route as well as a block inside the pulse: the SPA needs it before it draws
        anything at all, and a panel that has to fetch every metric to learn which panels to
        draw is one that renders a chart of zeros for a beat first.
        """
        return to_capabilities_view(await read_capabilities(db))

    @router.get(ORDERS_BY_DAY_PATH)
    async def orders_by_day(db: Db, window: Window) -> list[OrdersPerDayView]:
        """Volume per UTC day, oldest first. Days with no orders are absent, not zero."""
        return [to_orders_per_day_view(day) for day in await orders_per_day(db, window=window)]

    @router.get(FAILURES_PATH)
    async def failures(db: Db, window: Window) -> list[FailureView]:
        """Failed attempts by error code, largest first, each with a retryability verdict."""
        return [to_failure_view(failure) for failure in await failure_breakdown(db, window=window)]

    @router.get(LATENCY_PATH)
    async def latency(db: Db, window: Window) -> LatencyView:
        """p50 and p95 of ``created_at`` → ``delivered_at``, with the sample size."""
        return to_latency_view(await delivery_latency(db, window=window))

    @router.get(NAME_STRATEGIES_PATH)
    async def name_strategies(db: Db, window: Window) -> list[StrategyOutcomeView]:
        """The candidate-orthography bake-off ``BAYRAM_NAME_CANDIDATE_ORDER`` is reordered from.

        Kept beside the fuller ``/metrics/name-analytics`` rather than folded into it: this
        is the bare series the dashboard's own summary reads, and a caller that wants three
        numbers should not have to fetch twenty histogram buckets to get them.
        """
        return [
            to_strategy_outcome_view(outcome)
            for outcome in await strategy_outcomes(db, window=window)
        ]

    @router.get(NAME_ANALYTICS_PATH)
    async def name_metrics(db: Db, window: Window, settings: Settings) -> NameAnalyticsView:
        """The whole of ``/generations/names``: bake-off, distribution, and the cliff count.

        One window over one population, because the screen's question — "what should
        ``BAYRAM_NAME_CANDIDATE_ORDER`` be, and is the threshold that decided these verdicts in
        the right place" — is answered wrongly the moment its two halves are counted over
        different ranges. The SPA drew the histogram from one keyset PAGE of
        ``/api/generations`` and said so on screen ("most recent 200 scored attempts — the
        window holds more"); this counts every scored attempt in the window, in the database.

        ``threshold`` comes from ``AdminSettings`` and is ``None`` unless the deployment
        published the worker's ``name_match_min_similarity``. There is no default here: an
        invented 0.85 would put a marker on the chart that exists to argue about markers.
        """
        return to_name_analytics_view(
            await name_analytics(
                db, window=window, threshold=settings.admin_name_match_min_similarity
            ),
            window=window,
        )

    @router.get(AUDIENCE_PATH)
    async def audience(db: Db, window: Window) -> AudienceResponse:
        """The Audience section: population, sign-ups, activity, language, and TWO churns.

        ``now`` is read ONCE and handed to both clock-dependent reads. ``active_accounts``
        needs it so the three nested cutoffs are measured from one instant — two clock reads
        could put an account inside the daily cutoff and outside the weekly — and
        ``subscription_churn`` needs it because its denominator is a predicate on
        ``plan_ends_at``, a business clock that runs into the FUTURE: with no window, or with
        a ``?to=`` an operator set to next month, an unbounded-above predicate would sweep in
        every running plan and file all of them as lapsed. That read therefore takes ``now``
        as a required argument and caps the ending at it.

        **Two different churns, one card, and the response says which is which.** The
        bot-block churn is a passage count over ``bot_membership_events``; the subscription
        churn is a rate over the plans that ended. Neither bounds the other, and
        :class:`~bayram.admin.schemas.overview.SubscriptionChurnView` carries the argument where
        a reader of the card will meet it.

        **Two nulls, two probes, no new flag.** ``churn`` is ``null`` until a membership
        transition has been observed and ``subscriptionChurn`` is ``null`` until a plan has
        been sold — ``capabilities.isPlanRevenue``, which already exists for exactly this
        question and is why the response does not grow an ``isSubscriptionChurn`` beside it.
        Four zeroes would read as "nobody renews" on a deployment that has never sold
        anything.

        **``activityHistory`` is daily, and this route takes no ``?bucket=``.** The rows are
        one nightly sample apiece — ``snapshot_date`` is UNIQUE — so DAY is the finest grain
        the data has, and HOUR would only re-key the same points. A COARSER grain cannot be
        formed at all: DAU/WAU/MAU are GAUGES, so folding a week of them means either summing
        (which counts one person once per day) or picking one sample out of seven (a
        different measurement nobody asked for). ``bucket`` on ``/dashboard/series`` exists
        because those series are FLOWS, which fold by addition and really do sum to the daily
        series they came from. Rather than accept a parameter three of whose four values are
        refusals or lies, the grain is fixed and ECHOED as ``activityBucket``, which is also
        where a future ``?bucket=`` would surface if the snapshot job ever samples more than
        once a night.
        """
        now = utc_now()
        return to_audience_response(
            window=window,
            totals=await account_totals(db, window=window),
            active=await active_accounts(db, now=now),
            churn=await churn_counts(db, window=window),
            subscription_churn=await subscription_churn(db, now=now, window=window),
            language_mix=await language_mix(db, window=window),
            activity=await activity_history(
                db, window=window, grain=_QUERY_GRAIN[_ACTIVITY_BUCKET]
            ),
            activity_bucket=_ACTIVITY_BUCKET,
            capabilities=await read_capabilities(db),
        )

    @router.get(FINANCE_PATH)
    async def finance(db: Db, window: Window, settings: Settings) -> FinanceResponse:
        """The Finance section: what came in, what went out, and what is left at each vendor.

        Recorded revenue is the two receipts tables concatenated at the finest grain they
        carry; the delivered × price ESTIMATE is a separate field with its price attached and
        is never added to it. The delivered count is taken ONCE and used as both the
        cost-per-song denominator and the estimate's multiplicand, so the two cards cannot
        disagree about how many songs shipped.

        The run-rate pair is computed over its own fixed trailing window, which the response
        echoes. Balances are read from the cached table; this process makes no outbound call.
        """
        delivered = await delivered_counts(db, window=window)
        spend = await vendor_usage_totals(
            db, window=window, exclude_operations=SPENDABLE_EXCLUSIONS
        )
        run_rate = _run_rate_window(settings, now=utc_now())
        return to_finance_response(
            window=window,
            revenue=(
                await plan_revenue_totals(db, window=window)
                + await topup_revenue_totals(db, window=window)
            ),
            unpriced=await count_unpriced_topups(db, window=window),
            delivered=delivered,
            spend=spend,
            cost_per_song=await cost_per_delivered_song(
                db, window=window, delivered_orders=delivered.current
            ),
            unattributed=await unattributed_spend(db, window=window),
            balances=await vendor_balances(db),
            fake_calls=await fake_call_count(db, window=window),
            capabilities=await read_capabilities(db),
            settings=settings,
            run_rate_window=run_rate,
            run_rate_revenue=(
                await plan_revenue_totals(db, window=run_rate)
                + await topup_revenue_totals(db, window=run_rate)
            ),
            run_rate_spend=await vendor_usage_totals(
                db, window=run_rate, exclude_operations=SPENDABLE_EXCLUSIONS
            ),
        )

    @router.get(VENDOR_PATH)
    async def vendor(db: Db, window: Window) -> VendorResponse:
        """The Vendor section: who charged us, in what units, and how the figures were made.

        **The delivered count is taken ONCE and threaded into both breakdowns**, exactly as
        the finance route does with the same number, so the cost-per-song rows and the
        units-per-song rows are quotients over one population. Two reads of ``delivered_counts``
        microseconds apart could straddle a delivery and hand the two tables different
        denominators for figures a reader is meant to compare.

        **The denominator is the WHOLE cohort, not each vendor's covered subset.** Dividing
        by the orders a vendor happens to have calls for would report a figure that IMPROVES
        as instrumentation degrades; ``attributedOrders`` on each cost row is what says how
        much of the cohort the numerator actually covers.

        ``vendorSpend`` is the same aggregate, with the same exclusions, that
        ``/dashboard/finance`` publishes under that name — republished so the breakdown is
        never rendered without the total it partitions, and never renamed. The balances are
        read from the cached table: this process holds no vendor credential and makes no
        outbound call, on this route least of all.
        """
        delivered = await delivered_counts(db, window=window)
        return to_vendor_response(
            window=window,
            delivered_orders=delivered.current,
            spend=await vendor_usage_totals(
                db, window=window, exclude_operations=SPENDABLE_EXCLUSIONS
            ),
            cost_per_song=await cost_per_delivered_song_by_vendor(
                db, window=window, delivered_orders=delivered.current
            ),
            units_per_song=await units_per_delivered_song_by_vendor(
                db, window=window, delivered_orders=delivered.current
            ),
            provenance=await cost_provenance(db, window=window),
            balances=await vendor_balances(db),
            capabilities=await read_capabilities(db),
        )

    @router.get(PERFORMANCE_PATH)
    async def performance(db: Db, window: Window) -> PerformanceResponse:
        """The Performance section: how fast, how reliably, where orders stand, and what is up.

        Both the delivered count and the latency percentiles are windowed on ``delivered_at``,
        so the "Songs delivered" card and the "Median song time" card beside it are counted
        over ONE population. The created-at cohort is still published, unchanged, by the pulse
        and by ``/metrics/latency``.

        The status strip is assembled from capabilities and cached balance rows and from
        nothing else — no HTTP client exists in this process.
        """
        return to_performance_response(
            window=window,
            delivered=await delivered_counts(db, window=window),
            latency=await delivered_latency(db, window=window),
            music=await vendor_operation_latency(db, operation=_WATCHED_OPERATION, window=window),
            failures=await failure_breakdown(db, window=window),
            funnel=await order_funnel(db, window=window),
            balances=await vendor_balances(db),
            capabilities=await read_capabilities(db),
            now=utc_now(),
        )

    @router.get(SERIES_PATH)
    async def series(db: Db, window: Window, bucket: Bucket) -> SeriesResponse:
        """Every chart on the page in one request, at the grain the caller asked for.

        WEEK and MONTH are queried at DAY and folded in the serializer, so a monthly series
        sums exactly to the daily one it came from — which two independent SQL expressions
        could not guarantee, and which neither dialect agrees on anyway.

        Counts are zero-filled across the requested range and money is not; ``isZeroFilled``
        on the response says whether the fill happened at all, which it does only when the
        request supplied a lower bound.
        """
        grain = _QUERY_GRAIN[bucket]
        return to_series_response(
            window=window,
            bucket=bucket,
            signups=await new_accounts_per_bucket(db, window=window, grain=grain),
            delivered=await delivered_per_bucket(db, window=window, grain=grain),
            revenue=(
                await plan_bookings_per_bucket(db, window=window, grain=grain)
                + await topup_bookings_per_bucket(db, window=window, grain=grain)
            ),
            spend=await vendor_spend_per_bucket(db, window=window, grain=grain),
            unattributed=await unattributed_spend(db, window=window, grain=grain),
            cost_split=await vendor_spend_split(db, window=window),
            funnel=await order_funnel(db, window=window),
        )

    @router.get(PLAN_LIABILITY_PATH)
    async def plans(db: Db) -> PlanLiabilityResponse:
        """What the running plans owe. **No window** — liability is a state, not a flow.

        ``now`` is read ONCE and threaded into both calls: a liability count and a
        utilisation histogram taken microseconds apart could disagree about a plan that ended
        between them, and the response echoes the single instant they were both computed at.
        """
        now = utc_now()
        capabilities = await read_capabilities(db)
        return to_plan_liability_response(
            liability=await plan_liability(db, now=now),
            utilisation=await plan_utilisation(db, now=now),
            is_plan_revenue=capabilities.is_plan_revenue,
        )

    return router


def build_audience_lists_router() -> APIRouter:
    """The ONE identified route on this surface. ``RECORDS_READ``, audited, unmasked.

    **A second router because the guard is per-router (§12.1 T3)**, exactly as ``users.py``
    ships three and ``assets.py`` two. Declaring ``RECORDS_READ`` on a handler inside the
    dashboard router would be the shape the convention forbids, and declaring
    ``DASHBOARD_READ`` on this route would hand an unmasked Telegram id to every role holding
    the aggregate cell. The permission is the same one ``GET /api/users`` stands on, from the
    same dependency, so this route is reachable by exactly the roles that can already list
    the account it names.

    **The audit row is the whole control, so it cannot be skipped.** §12.2 has no cell for
    "identity without a reveal"; the owner — the sole operator of this panel — decided that
    an ACCOUNT HOLDER's Telegram id, handle and first name may be shown to them directly with
    an audit entry INSTEAD OF a reveal gate, a step-up and a budget unit. That trade only
    holds while the entry is written on every call, which is why it is written inside the
    request's own transaction: :func:`bayram.admin.audit_sink.record` appends into the session
    the handler read from, so a failure to log is a failure to answer and there is no path
    that discloses these rows without recording that it did.

    **It is deliberately not routed through a masking serializer, and no masked variant
    exists.** A caller that could ask for the masked form would be paying for a control it
    opted out of, and the audit row would then record a disclosure that did not happen.

    **Consequence to know about: ``RECORDS_READ`` is ``M`` for ALL FOUR roles** (§12.2), so
    this route is reachable by VIEWER as well as OWNER — and it answers every one of them
    unmasked, which is a wider audience than the matrix cell it borrows describes. That is
    acceptable *today* on the deployment this was decided for, where the owner is the sole
    operator and the only accounts are theirs; the audit row names the actor and their role on
    every read, so the widening is at least visible. The day a second, less-trusted operator
    exists, the fix is a permission of this route's own with its own cell — not a masking
    branch bolted onto a payload whose whole purpose is to be unmasked.

    **The decision covers the account holder ONLY.** Recipient names
    (``briefs.recipient_name_display``, ``name_records.grapheme``) are a third party who
    consented to nothing, and they stay behind ``POST /reveal`` with the step-up, the reveal
    budget and the per-view audit row. The whole reveal / step-up machinery is untouched by
    this route and remains load-bearing for every screen that uses it.
    """
    router = APIRouter(
        tags=["dashboard"],
        dependencies=[Depends(require_permission(Permission.RECORDS_READ))],
    )

    @router.get(AUDIENCE_LISTS_PATH)
    async def audience_lists(
        admin: Admin,
        container: Container,
        db: Db,
        window: Window,
        limit: Annotated[int, Query(ge=1, le=_MAX_LIST_LIMIT)] = _DEFAULT_LIST_LIMIT,
    ) -> AudienceListsResponse:
        """The two identified lists: top generators in the window, and the last plans sold.

        **``?from=``/``?to=`` narrow the top generators and NOTHING else.**
        ``recent_subscribers`` is a recency list and takes no window at all — the response
        carries the window inside the ``topGenerators`` block for that reason, so no field
        placement suggests the subscriber list was filtered by a range it never saw.

        **``?limit=`` applies to both lists and is bounded twice.** ``ge``/``le`` here make an
        out-of-range value a 422 naming the parameter, and both database reads clamp again
        for any caller that reaches them without going through HTTP — the same pairing
        ``page_params`` uses. On an identified surface that ceiling is also what stops
        ``?limit=100000`` from turning a card into a bulk export of customers.

        ``now`` is read once and threaded through the subscriber projection and the audit
        row, so every ``isPlanEnded``, the ``asOf`` that explains them and the ``at`` on the
        log entry are the same instant.

        The audit row is written AFTER the reads and before the response is built: it records
        what was actually disclosed, and ``recordCount`` carries how many identified people
        that was — ``0`` for a window with nothing in it, which is an honest record of a read
        that showed nobody rather than a row worth suppressing.
        """
        now = utc_now()
        generators = await top_generators(db, window=window, limit=limit)
        subscribers = await recent_subscribers(db, limit=limit)
        capabilities = await read_capabilities(db)
        await audit_sink.record(
            db,
            container,
            _audience_lists_entry(admin, records=len(generators) + len(subscribers)),
            now=now,
        )
        return to_audience_lists_response(
            window=window,
            generators=generators,
            generators_limit=limit,
            subscribers=subscribers,
            subscribers_limit=limit,
            is_plan_revenue=capabilities.is_plan_revenue,
            now=now,
        )

    return router


def _audience_lists_entry(admin: CurrentAdmin, *, records: int) -> AuditEntry:
    """One ``audience.list`` row: who looked, how many people they were shown, and at what.

    ``field_names`` names the COLUMNS disclosed and never their values (§12.4) — the same
    rule a reveal row follows, and the reason the log can be read for "what does this action
    expose" without opening the payload it produced.

    ``reason_code`` is ``ROUTINE_OPS`` because this is not an investigation. The reason
    vocabulary exists for reveals and purges; spending ``SUPPORT_INVESTIGATION`` on a card
    the operator opens every morning would make the most common value in the table the one
    that means "something happened", which is how a reason column stops meaning anything.

    There is no ``subject_id``: the subject is the LIST (``subject_type`` ``"system"``), and
    picking one of the people on it would be arbitrary while the column cannot hold several.
    """
    return AuditEntry(
        action=AuditAction.AUDIENCE_LIST_READ,
        actor_id=admin.admin_user_id,
        actor_username=admin.username[:ACTOR_USERNAME_LENGTH],
        actor_role=admin.role,
        subject_type=AUDIENCE_LISTS_SUBJECT_TYPE,
        field_names=IDENTIFIED_FIELD_NAMES,
        record_count=records,
        reason_code=AuditReasonCode.ROUTINE_OPS,
        outcome=AuditOutcome.OK,
        ip=admin.client_ip,
    )
