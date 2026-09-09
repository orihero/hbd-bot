"""Wire models for the four dashboard sections — and the primitives that make a lie illegal.

``schemas/dashboard.py`` states the rule this file enforces: *a rate with no denominator is
``null``, never ``0.0``*. Stating a rule is how it holds until the next edit. So the four
primitives at the top of this module carry pydantic ``model_validator``s that **raise**, and
the rule becomes a property of the type rather than of reviewer diligence:

* :class:`RatioView` cannot be built with a value and a zero denominator, and cannot be
  built without one. There is no bare ``float`` rate field anywhere in this module.
* :class:`UsdCost` cannot be built with an amount and no ``costSource``, nor with a
  ``costSource`` and no amount. That is ``ck_vendor_usage_cost_carries_its_source`` restated
  at the wire, and it makes "$41.20 of unknown provenance" unrepresentable.
* :class:`MoneyTotal` carries its currency, its rail and its source; there is no scalar
  money anywhere on this surface, so "total revenue" cannot be summed across currencies by
  a consumer that did not mean to.
* :class:`TrendView` cannot carry a change against a previous period that was zero or was
  never measured. Growth from nothing is not "+100%" — the quotient has no denominator.

``RatioView(value=0.87)`` does not compile at runtime. Neither does
``UsdCost(amount_usd=41.20)``. A reviewer never has to notice.

**Absence is expressed, never zero-filled, and where the absence has a cause the cause is on
the wire.** :class:`AbsenceReason` is a closed vocabulary of why a number this page would
otherwise show is missing — no FX rate published, no unit price published, the window mixes
currencies, nothing is priced, the poller has never run, there is no denominator. Every
optional figure below travels with one, so the SPA renders "no rate configured" rather than
an em-dash whose meaning the operator has to guess, and never renders ``0``.

**No converted figure appears on this wire.** ``amountMinor`` is in its own currency,
``amountUsd`` is USD, and the FX pair is published beside them with the date it was taken.
The one exception is :class:`NetRunRateView`, which does the subtraction the Net card exists
for — and it does it only when a rate exists AND the window holds exactly one currency, it
names the rate it used and the window it used, and it reports an :class:`AbsenceReason`
rather than a number in every other case. A converted number with no rate attached has lost
its provenance and would be silently revalued the day an operator edits the rate, which is
the retroactive-repricing defect this whole workstream is shaped around.

**Revenue means SALES RECORDED, never money banked.** ``StubCheckoutProvider`` stamps
``is_paid=True`` having contacted nobody, so every provider on this deployment is ``stub``
until Payme lands. ``provider`` is carried raw at the finest grain and never collapsed, and
``isStubRail`` is the one derived field in this module — a convenience beside the raw name,
not a replacement for it — so a tile cannot be labelled "GMV" or "settled" without somebody
deleting a field that says otherwise.

**Money is never zero-filled, and counts are — but only when the caller gave a lower
bound.** A bucket with no orders is honestly zero orders; a bucket with no priced call is
``costUsd: null`` and never ``$0.00``, because the whole schema below it (no server
defaults, no ``COALESCE``, ``_as_float``) exists to preserve that distinction and a chart is
the last place it can be destroyed. And zero-filling at all is only honest when the request
supplied a ``from``: with ``?to=`` alone the series is open below, and a filled bucket before
the first row would claim "0 sign-ups" for days this deployment did not exist.
``isZeroFilled`` is on the wire so the chart knows whether a gap means "no data" or "no such
day".

**Week and month are folded here, not grouped in SQL.** :class:`~hbd.db.admin.sql.SeriesGrain`
offers HOUR and DAY only, because Postgres and SQLite number ISO weeks differently and a
query both dialects run *differently* passes the suite and is wrong in production. The fold
is Python arithmetic over already-grouped rows — bounded by the bucket count, never by rows —
and it guarantees a monthly series sums exactly to the daily one it came from.

**Nothing here is personal data.** Counts, enum members, ISO currencies, provider names, UTC
buckets, vendor names and money. No ``telegramUserId`` from ``users``, from ``orders`` or
from either receipts table; no ``reference``, no ``idempotencyKey``, no name, no note, no
transcript. §12.2's DASHBOARD_READ **R** cell for OWNER therefore changes nothing: there is
no masking branch, no ``is_unmasked`` parameter on any projection below, and no unmasked
variant of any response. Restated here rather than inherited, because a new schema module is
exactly where that invariant gets quietly dropped.

**The two identified lists are NOT here, and that is the shape of the exception.** The owner
decided that an account holder's Telegram identity may be shown directly, audited rather
than reveal-gated; those shapes live in :mod:`hbd.admin.schemas.audience_lists`, are served
on ``RECORDS_READ`` from their own audited route, and are imported by nothing in this module.
So the paragraph above is still literally true of every response below it — which is the
only reason the DASHBOARD_READ surface can keep skipping masking at all.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import UTC, date, datetime, timedelta
from enum import StrEnum
from typing import Self

from pydantic import Field, model_validator

from hbd.admin.schemas.common import ApiModel
from hbd.admin.schemas.dashboard import (
    CapabilitiesView,
    FailureView,
    LatencyView,
    WindowView,
    to_capabilities_view,
    to_failure_view,
    to_latency_view,
    to_window_view,
)
from hbd.admin.schemas.vendors import cost_source_of
from hbd.admin.settings import AdminSettings
from hbd.checkout import STUB_PROVIDER_NAME
from hbd.contracts import (
    BalanceEstimateBasis,
    BalanceUnit,
    CostSource,
    Language,
    OrderState,
    Vendor,
    VendorOperation,
)
from hbd.db.admin.sql import TimeWindow
from hbd.db.admin.views import (
    AccountTotals,
    ActiveAccounts,
    ActivityPoint,
    ChurnCounts,
    CostPerDeliveredSong,
    CostProvenance,
    CurrencyAmount,
    DeliveredPerBucket,
    FailureCount,
    FakeCallGuard,
    LanguageMixTotals,
    LatencySummary,
    NewAccountsPerBucket,
    OperationLatency,
    OrderFunnel,
    PlanLiability,
    PlanUtilisationBucket,
    ReadCapabilities,
    RevenueBucket,
    RevenueSource,
    RevenueTotal,
    SubscriptionChurn,
    Trend,
    UnattributedSpendPerBucket,
    UnpricedTopups,
    VendorBalanceState,
    VendorCostPerSong,
    VendorSpendPerBucket,
    VendorSpendSplit,
    VendorUnitsPerSong,
    VendorUsageTotals,
)

__all__ = [
    "AbsenceReason",
    "SeriesBucket",
    "ComponentState",
    "RatioView",
    "TrendView",
    "UsdCost",
    "MoneyTotal",
    "CountPointView",
    "MoneyPointView",
    "SpendPointView",
    "FxRateView",
    "ActiveAccountsView",
    "ChurnView",
    "SubscriptionChurnView",
    "LanguageMixEntryView",
    "LanguageMixView",
    "ActivityPointView",
    "AudienceResponse",
    "DerivedRevenueView",
    "CostPerSongView",
    "NetRunRateView",
    "VendorBalanceView",
    "FakeCallGuardView",
    "UnpricedTopupsView",
    "FinanceResponse",
    "ComponentStatusView",
    "OperationLatencyView",
    "OrderStateCountView",
    "OrderFunnelView",
    "PerformanceResponse",
    "CostSplitView",
    "SeriesResponse",
    "VendorCostPerSongView",
    "VendorUnitsPerSongView",
    "CostProvenanceView",
    "VendorResponse",
    "CurrencyAmountView",
    "PlanUtilisationBucketView",
    "PlanLiabilityResponse",
    "DAYS_PER_YEAR",
    "fold_points",
    "to_audience_response",
    "to_finance_response",
    "to_vendor_response",
    "to_performance_response",
    "to_series_response",
    "to_plan_liability_response",
    "to_fx_rate_view",
    "to_trend_view",
    "to_usd_cost",
]

#: Days in the year the run-rate card annualises to. The card is labelled "ARR" on the mock
#: and the obvious implementation multiplies a "monthly" net by twelve — which is wrong the
#: moment ``HBD_ADMIN_DASHBOARD_RUN_RATE_DAYS`` is anything but thirty, and silently so. The
#: scaling is therefore done from the window's REAL length, and the response echoes that
#: window so the reader can check the arithmetic.
DAYS_PER_YEAR: int = 365


class AbsenceReason(StrEnum):
    """Why a number this page would otherwise show is not there.

    A closed vocabulary rather than free text, so the SPA can render a specific remedy for
    each and so a new absence has to be named here before it can reach a screen. Every one
    of these is a state an operator can act on — configure a rate, publish a price, narrow a
    window, start the poller — which is the test a member has to pass to belong here.
    """

    #: No FX rate is published on this deployment. Set ``HBD_ADMIN_UZS_PER_USD`` and its date.
    NO_FX_RATE = "no_fx_rate"
    #: No unit price is mirrored into the panel. Set ``HBD_ADMIN_SINGLE_SONG_PRICE_MINOR``.
    NO_PRICE_PUBLISHED = "no_price_published"
    #: The window's receipts carry more than one currency, so there is no single net figure
    #: and the panel refuses to invent an exchange between them.
    MIXED_CURRENCIES = "mixed_currencies"
    #: Calls were recorded and not one of them carried a cost. Configure a vendor rate.
    NOT_PRICED = "not_priced"
    #: The quotient's denominator is zero. Not a bad rate — no rate.
    NO_DENOMINATOR = "no_denominator"
    #: Nothing has ever written the rows this number reads. Instrument the worker.
    NOT_INSTRUMENTED = "not_instrumented"


class SeriesBucket(StrEnum):
    """The grains a CHART may ask for. Wider than the two the database groups at.

    ``WEEK`` and ``MONTH`` are folded from ``DAY`` in this module — see
    :class:`~hbd.db.admin.sql.SeriesGrain` for why they are not SQL.
    """

    HOUR = "hour"
    DAY = "day"
    WEEK = "week"
    MONTH = "month"


class ComponentState(StrEnum):
    """One dot on the system-status strip.

    ``NOT_PROBED`` is a third state and not a quiet ``OK``. A component with no writer has
    told us nothing, and reporting silence as health is how a strip of green dots ends up
    describing a subsystem nobody instrumented.
    """

    OK = "ok"
    DEGRADED = "degraded"
    NOT_PROBED = "not_probed"


# ---------------------------------------------------------------------------
# the four primitives
# ---------------------------------------------------------------------------
class RatioView(ApiModel):
    """A quotient that cannot exist without the two numbers it was formed from.

    ``value`` is ``null`` if and only if ``denominator`` is zero, and the validator refuses
    both halves of the violation: a value with no denominator, and a denominator with no
    value. There is no bare ``float`` rate field anywhere in this module because every one
    of them would be a number a consumer could not check.
    """

    value: float | None
    numerator: float
    denominator: float

    @model_validator(mode="after")
    def _a_rate_carries_its_denominator(self) -> Self:
        if self.denominator == 0 and self.value is not None:
            raise ValueError("a ratio with a zero denominator has no value")
        if self.denominator != 0 and self.value is None:
            raise ValueError("a ratio with a denominator must carry its value")
        return self


class TrendView(ApiModel):
    """A count and its change against the preceding equal-length window.

    ``previous`` is ``null`` when the request gave no lower bound — an open-below range has
    no length and therefore no predecessor — and ``change`` is ``null`` whenever ``previous``
    is ``null`` or zero. The validator refuses a change in either of those cases, so "+100%"
    against a period nobody measured is not a shape this API can produce.
    """

    current: int
    previous: int | None
    change: RatioView | None

    @model_validator(mode="after")
    def _a_change_carries_a_previous_period(self) -> Self:
        if self.change is not None and (self.previous is None or self.previous == 0):
            raise ValueError("a change needs a measured, non-zero previous period")
        return self


class UsdCost(ApiModel):
    """A dollar figure, how many calls it covers, how many there were, and where it came from.

    ``amountUsd`` is ``null`` if and only if ``costSource`` is ``null``: an unpriced window
    has no cost, and a cost with no provenance is a number whose trust level is unknowable.
    That is ``ck_vendor_usage_cost_carries_its_source`` enforced a second time, at the wire,
    where the SPA can see it.

    ``costedCalls`` never exceeds ``calls``. The pair is what makes the amount readable: a
    total covering nine of nine hundred calls is a budget an operator would act on without
    it, and a sample they can see the size of with it.
    """

    amount_usd: float | None
    costed_calls: int
    calls: int
    #: ``"vendor_reported"`` | ``"derived"`` | ``"estimated"`` | ``"mixed"`` | ``null``.
    #: ``"mixed"`` is a statement about a GROUP and is deliberately not a ``CostSource``
    #: member — see :mod:`hbd.admin.schemas.vendors`.
    cost_source: str | None
    #: Why there is no amount, when there is none. ``NOT_PRICED`` with calls recorded;
    #: ``NOT_INSTRUMENTED`` when there were no calls at all.
    unavailable_reason: AbsenceReason | None

    @model_validator(mode="after")
    def _a_cost_carries_its_source(self) -> Self:
        if (self.amount_usd is None) is not (self.cost_source is None):
            raise ValueError("a dollar figure and its provenance are present together")
        if self.costed_calls > self.calls:
            raise ValueError("more priced calls than calls")
        if (self.amount_usd is None) is not (self.unavailable_reason is not None):
            raise ValueError("an absent cost carries its reason and a present one does not")
        return self


class MoneyTotal(ApiModel):
    """Sales recorded under one ``(source, product, currency, provider)`` key.

    Never a scalar and never collapsed. Summing across ``currency`` produces a figure in an
    invented unit; collapsing ``provider`` lets a stub-rail sale be read as settled money.
    Today every row is UZS from the stub rail, so a caller usually sees one element — and
    the shape stays a list, or the day a second currency appears the number silently becomes
    wrong rather than longer.
    """

    source: RevenueSource
    #: A member of ``PlanKind`` or of ``TopupKind`` depending on ``source``, rendered raw.
    #: Deliberately ``str``: a union type on the wire would force every consumer to know
    #: which enum a given row's value came from.
    product: str
    currency: str
    provider: str
    #: ``provider == "stub"``. The one derived field in this module, and the reason a tile
    #: on this surface cannot honestly be labelled "GMV" or "settled".
    is_stub_rail: bool
    sales: int
    amount_minor: int


# ---------------------------------------------------------------------------
# series points
# ---------------------------------------------------------------------------
class CountPointView(ApiModel):
    """One bucket of a pure count series. Zero-fillable, because zero orders is a fact."""

    bucket: str
    started_at: datetime
    count: int


class MoneyPointView(ApiModel):
    """One bucket of a revenue series, at the receipts' own grain. NEVER zero-filled."""

    bucket: str
    started_at: datetime
    source: RevenueSource
    product: str
    currency: str
    provider: str
    is_stub_rail: bool
    sales: int
    amount_minor: int


class SpendPointView(ApiModel):
    """One bucket of a spend series. ``cost`` is ``null`` for a bucket nothing priced."""

    bucket: str
    started_at: datetime
    #: ``null`` on the unattributed series, which is not grouped by vendor.
    vendor: Vendor | None
    cost: UsdCost


class FxRateView(ApiModel):
    """The operator's own soʻm-per-dollar figure and the date they took it.

    Both fields are ``null`` together or set together — ``AdminSettings`` refuses a boot
    where only one is configured — so "a rate with no date" cannot reach a screen. There is
    no feed behind this number: the as-of date is the only staleness signal there is, and it
    only works if the panel renders it beside the rate.

    Published on the finance response as well as on ``/api/config``, deliberately. Config is
    fetched once at SPA boot while the dashboard is polled, so a chart drawn from a rate
    fetched on a different request at a different time is not reproducible — the same
    decision ``/metrics/name-analytics`` already made by carrying ``threshold`` in its own
    response.
    """

    uzs_per_usd: float | None
    as_of: date | None

    @model_validator(mode="after")
    def _a_rate_carries_its_date(self) -> Self:
        if (self.uzs_per_usd is None) is not (self.as_of is None):
            raise ValueError("an FX rate and its as-of date are present together")
        return self


# ---------------------------------------------------------------------------
# audience
# ---------------------------------------------------------------------------
class ActiveAccountsView(ApiModel):
    """DAU / WAU / MAU, nested, as of one instant.

    Every account in ``day`` is also in ``week`` and in ``month``: three cutoffs against one
    column, not three disjoint buckets, so a stacked bar of these three would triple-count.
    ``asOf`` travels with them because all three are measured backwards from it.
    """

    day: int
    week: int
    month: int
    as_of: datetime


class ChurnView(ApiModel):
    """Blocks and unblocks in the window. A FLOW; the gauge is ``botBlockedAccounts``.

    Counted from membership PASSAGES, so someone who left and came back inside one window is
    in both numbers. An unblock is recorded only when a previously blocked account returns —
    the writer refuses the ``left → member`` update Telegram sends on every first
    ``/start`` — so a non-zero unblock count means real returns and never new arrivals.
    """

    blocked: TrendView
    unblocked: TrendView


class SubscriptionChurnView(ApiModel):
    """Renewal over the starter plan: of the plans that ENDED, how many were bought again.

    **This is not the churn in :class:`ChurnView`, and the panel draws them in ONE card.**
    They are different quantities with different units and different denominators, and the
    card is the single place a reader is most likely to add them up:

    * ``churn`` counts PASSAGES through ``bot_membership_events`` — people blocking the bot
      and, separately, coming back. A count of events in a window, with no denominator at
      all; somebody who left and returned inside the window is in both of its numbers.
    * this is a RATE over a POPULATION — the plans whose ``plan_ends_at`` fell inside the
      window, i.e. whose renewal decision has actually been made. Its denominator is
      ``endedPlans`` and it says nothing about whether anybody blocked anything.

    A customer can block the bot with a plan still running, and can let a plan lapse while
    still using the bot every day. Neither number bounds, explains or corrects the other, and
    a single "churn" figure formed from the two would be an average of an event count and a
    proportion.

    **A RUNNING plan is not in the denominator.** Its outcome is not final — the holder has
    not declined to renew, they have not yet reached the decision — so counting them would
    file every customer of the last thirty days as lapsed.

    **Read ``endedPlans`` before reading ``rate``.** One thirty-day product first sold weeks
    ago means a single-digit denominator, where one ending swings the percentage by thirty
    points. Nothing is smoothed and nothing is withheld below a threshold; the count is the
    measurement at this volume and the percentage is decoration, which is why ``rate`` is a
    :class:`RatioView` and carries its own denominator wherever it is rendered.
    """

    #: The denominator: plans whose ``plan_ends_at`` was at or before the handler's instant
    #: and inside the window. Zero is a real answer and means nothing has ended yet.
    ended_plans: int
    #: Ended plans whose holder has a LATER ``plan_purchases`` row. INFERRED — there is no
    #: renewal event in the schema — and it carries no recency bound: a customer who came
    #: back after four idle months is counted here beside one who renewed the same afternoon.
    renewed: int
    #: Ended plans with an identified holder and no later row. **This EXCLUDES the anonymised
    #: endings**, which are their own arm below: ``renewed + lapsed + anonymisedEnded ==
    #: endedPlans`` exactly, on every window.
    #:
    #: The consequence is that ``rate`` is a FLOOR on real churn, understated by at most
    #: ``anonymisedEnded`` endings — an erased customer cannot be followed to a later
    #: purchase by anybody, so counting them as lapsed would state that they did not come
    #: back when the truth is that nobody can tell. :class:`~hbd.db.admin.views.
    #: SubscriptionChurn` states the same partition at the view and
    #: :func:`~hbd.db.admin.plan_purchases.subscription_churn` at the query, so the three
    #: layers describe one number.
    lapsed: int
    #: How many of ``endedPlans`` carry no ``telegram_user_id`` because the customer
    #: exercised ``/forget``. The exact width of the blind spot above ``lapsed``, published
    #: beside it rather than folded into it — the same honesty column ``liveAnonymisedPlans``
    #: is on the plan book.
    anonymised_ended: int
    #: ``lapsed / endedPlans`` as a :class:`RatioView`, so the percentage cannot be rendered
    #: without the denominator it was taken over. ``value`` is ``null`` — never ``0.0`` —
    #: when no plan has ended yet: "0% churn" is the single most flattering lie this panel
    #: could tell, and it would be told on precisely the deployments too young to have
    #: measured anything.
    rate: RatioView


class LanguageMixEntryView(ApiModel):
    """How many accounts read the BOT in one language, and that count's share of the whole.

    **The interface language, never the song's.** ``users.ui_language`` is what the customer
    reads the bot in; ``briefs.output_language`` is what the song is SUNG in, and the two are
    chosen independently — a customer can drive the bot in Russian and order an Uzbek song.
    A caption saying "song language" over this would be a different measurement, not a loose
    label.

    ``share`` carries its own denominator for the reason the whole module carries them: a
    percentage the SPA formed by summing the list it happened to receive silently
    renormalises to 100% of whatever survived a filter or a truncation.
    """

    language: Language
    accounts: int
    #: ``accounts / totalAccounts``. Its denominator is the block's ``accounts``, not the sum
    #: of the entries rendered — those are equal today and would stop being so the moment
    #: anything filtered the list.
    share: RatioView


class LanguageMixView(ApiModel):
    """The language split with the population it is a split OF.

    ``ui_language`` is ``NOT NULL DEFAULT uz_latn``, so every account lands in exactly one
    entry and the entries really do sum to ``accounts``. That default is also why the UZ_LATN
    entry over-counts CHOICE: the column is only refreshed when the writer actually knows the
    answer, so an account created by an order alone sits at the default without anybody
    having picked it. The number is a true count of what the bot WILL SPEAK and not a survey.

    A windowed request narrows this to accounts CREATED in the window — a signup cohort read
    as it stands today, not the mix that was on screen during the window. ``ui_language`` is
    a gauge with no history, so the second question has no answer in this schema.
    """

    #: Largest first. A language no account uses is ABSENT rather than present at zero: this
    #: is a fully visited population, so the gap is presentational and not a missing
    #: measurement — nobody reading the bot in English is not a measurement of English.
    languages: list[LanguageMixEntryView]
    #: Every account the same statement counted — the whole table, or the accounts created in
    #: the window. The denominator of every ``share`` above.
    accounts: int


class ActivityPointView(ApiModel):
    """One night's DAU / WAU / MAU, from the snapshot table. The history of the gauge above.

    **The three counts are NESTED CUTOFFS on one population** (``day ⊆ week ⊆ month``), all
    three from one ``last_seen_at`` predicate at one instant. Three lines, never a stacked
    area: stacking them would triple-count everybody active today and the top line would be a
    number no query can produce.

    **A night the snapshot job did not run is ABSENT from the series and is never filled.**
    Zero-filling here would report that nobody used the bot that day — a fabricated
    measurement wearing a chart line — and the gap cannot be back-filled either, because
    ``users.last_seen_at`` is a gauge that was overwritten: this history exists only from the
    first night the job ran. ``isActivityHistory`` says whether that has ever happened.
    """

    bucket: str
    started_at: datetime
    day: int
    week: int
    month: int


class AudienceResponse(ApiModel):
    """``GET /api/metrics/dashboard/audience`` — the Audience cards in one round trip."""

    window: WindowView | None
    total_accounts: TrendView
    new_accounts: TrendView
    active_accounts: ActiveAccountsView
    #: Barred by an OPERATOR (``users.is_blocked``). A decision made here and undoable here.
    blocked_accounts: int
    #: Barred by the CUSTOMER (``users.blocked_bot_at``). Not summed with the one above: an
    #: account can be both, and the remedies are nothing alike.
    bot_blocked_accounts: int
    #: Bot-block churn: a PASSAGE COUNT, in people, with no denominator. ``null`` until the
    #: membership handler has observed a transition — see ``isChurnInstrumented``. Never a
    #: pair of zeroes, which would read as "nobody left". **Not the same quantity as
    #: ``subscriptionChurn`` below**, which the panel renders in the same card; see
    #: :class:`SubscriptionChurnView` for why neither bounds the other.
    churn: ChurnView | None
    #: False means no block has ever been recorded here, so a churn count of zero would be
    #: "nothing observed" rather than "nobody left".
    is_churn_instrumented: bool
    #: Subscription churn: a RATE over the plans that ENDED in the window, in plans. ``null``
    #: when no plan has ever been sold on this deployment — ``capabilities.isPlanRevenue`` is
    #: the probe, and four zeroes would read as "nobody renews" on a deployment that has
    #: never sold anything. Rendered in the same card as ``churn`` above and measuring
    #: something else entirely.
    subscription_churn: SubscriptionChurnView | None
    #: The interface-language split, with its denominator attached.
    language_mix: LanguageMixView
    #: The recorded DAU/WAU/MAU series, oldest first, at ``activityBucket``. Empty when the
    #: nightly job has never run here, which ``isActivityHistory`` states outright; a night
    #: with no sample is absent from the series and is never zero-filled.
    activity_history: list[ActivityPointView]
    #: The grain ``activityHistory`` is at, echoed rather than assumed. Always ``day``: this
    #: route takes no ``?bucket=``, because the underlying rows are one nightly sample and
    #: the three counts are GAUGES — a coarser bucket could only be formed by summing them
    #: (which counts the same person once per day) or by picking one sample out of seven
    #: (which is a different measurement nobody asked for). See the route docstring.
    activity_bucket: SeriesBucket
    #: False means the nightly snapshot job has not run, so there is no HISTORICAL active
    #: series to draw — even though the live DAU/WAU/MAU gauge above answers perfectly well.
    is_activity_history: bool


# ---------------------------------------------------------------------------
# finance
# ---------------------------------------------------------------------------
class UnpricedTopupsView(ApiModel):
    """Top-ups sold before amounts were recorded, and those recorded. Counted, never priced.

    The first number is unrecoverable revenue: those sales left a ``credit_ledger`` GRANT
    with no amount, and back-pricing them at today's price would reprice every prior period
    the next time the price moves. It travels beside the money for the same reason
    ``costedCalls`` travels beside ``costUsd``.
    """

    unpriced: int
    priced: int


class DerivedRevenueView(ApiModel):
    """Songs delivered × the published unit price. An ESTIMATE, and labelled as one.

    A separate field from ``revenue`` and never added to it. This multiplies a config value
    read at query time; ``revenue`` is money somebody recorded a receipt for. They are the
    same class of figure as ``generation_attempts.cost_usd`` and recorded spend respectively,
    and the price and currency it multiplied by are attached so an operator can see which
    price produced the number.

    ``amountMinor`` is ``null`` with ``NO_PRICE_PUBLISHED`` when this deployment has not
    mirrored its price — never ``0``, and never the bot model's default, which would publish
    a price this deployment may not be charging.
    """

    delivered_songs: int
    unit_price_minor: int | None
    currency: str | None
    amount_minor: int | None
    unavailable_reason: AbsenceReason | None

    @model_validator(mode="after")
    def _a_derived_figure_carries_the_price_it_used(self) -> Self:
        present = (self.unit_price_minor is None, self.currency is None, self.amount_minor is None)
        if len(set(present)) != 1:
            raise ValueError("a derived amount, its price and its currency travel together")
        if (self.amount_minor is None) is not (self.unavailable_reason is not None):
            raise ValueError("an absent estimate carries its reason and a present one does not")
        return self


class CostPerSongView(ApiModel):
    """Vendor spend attributed to the songs delivered in the window, over their count.

    ``perSongUsd`` is a :class:`RatioView`, so it cannot exist without the delivered count
    it was divided by, and it is ``null`` when the cost is ``null`` — calls recorded, no rate
    configured — rather than ``$0.00``.

    ``attributedOrders`` beside ``deliveredOrders`` is the coverage pair: the gap between
    them is delivered songs that carry no vendor call at all, which is what the cost figure
    is silently missing.
    """

    cost: UsdCost
    delivered_orders: int
    attributed_orders: int
    per_song_usd: RatioView | None


class NetRunRateView(ApiModel):
    """Recorded revenue minus vendor spend over a FIXED trailing window of its own.

    **It does not use the caller's window, and that is a decision.** The mock labels a
    thirty-day net "MRR" and its twelvefold "ARR", while the global selector can be set to
    Today. A run rate computed over the selector would mean "today's net" whenever the
    selector says Today, and then be multiplied by twelve. So this carries the window it
    actually used and echoes it, and the number on the card cannot be read as belonging to
    the picker above it.

    **This is the one place on this wire where a currency conversion happens**, and it is
    fenced: ``netMinor`` is non-null only when an FX rate is published AND the window's
    receipts hold exactly one currency. Otherwise it is ``null`` with an
    :class:`AbsenceReason`, never a partial figure and never a zero. ``fxUsed`` names the
    rate the subtraction was performed at, so the number is reproducible from its own
    response after the operator edits the rate.
    """

    window: WindowView
    revenue: list[MoneyTotal]
    cost: UsdCost
    fx_used: FxRateView
    currency: str | None
    net_minor: int | None
    annualised_minor: int | None
    unavailable_reason: AbsenceReason | None

    @model_validator(mode="after")
    def _a_net_figure_carries_its_currency_or_its_reason(self) -> Self:
        parts = (self.net_minor is None, self.currency is None, self.annualised_minor is None)
        if len(set(parts)) != 1:
            raise ValueError("a net figure, its currency and its annualisation travel together")
        if (self.net_minor is None) is not (self.unavailable_reason is not None):
            raise ValueError("an absent net carries its reason and a present one does not")
        return self


class VendorBalanceView(ApiModel):
    """One vendor's remaining credit, read from cache. The admin process never asks a vendor.

    Two clocks, and they are not interchangeable: ``checkedAt`` is when the poller last
    ASKED and ``fetchedAt`` is when these numbers were last actually ANSWERED. They diverge
    during an outage, because the writer's failure path leaves the last known balance
    untouched, and ``isStale`` is computed against ``fetchedAt`` alone. A single "as of"
    would render a three-hour-old figure as fresh.

    Every quantity is nullable with no default: a vendor that reports an uncapped key
    answers ``isUnbounded`` and no remaining figure, and ``0.0`` there would say the account
    is empty.
    """

    vendor: Vendor
    is_fallback: bool
    provider: str
    unit: BalanceUnit
    remaining: float | None
    total: float | None
    used: float | None
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


class FakeCallGuardView(ApiModel):
    """How many of the window's vendor calls were a fake-provider run, and how many there were.

    Every other number on this surface excludes those rows structurally. This pair is what
    makes the exclusion visible, so a demo run goes from "silently inflating spend" to
    "excluded and said so" rather than to "silently invisible".
    """

    fake_calls: int
    total_calls: int


class FinanceResponse(ApiModel):
    """``GET /api/metrics/dashboard/finance`` — the money half of the page, in one request."""

    window: WindowView | None
    #: Plan and top-up receipts in one list, each row carrying its source, currency and
    #: rail. Never summed to a scalar by this server, and never summable across currencies
    #: by a consumer that reads the shape.
    revenue: list[MoneyTotal]
    unpriced_topups: UnpricedTopupsView
    #: Delivered × published price. An estimate; never added to ``revenue``.
    derived_revenue: DerivedRevenueView
    vendor_spend: UsdCost
    cost_per_song: CostPerSongView
    #: Priced work that reached no order — the leak ``costPerSong`` cannot see.
    unattributed_spend: UsdCost
    net_run_rate: NetRunRateView
    fx: FxRateView
    #: Empty when the poller has never run here; ``capabilities.isVendorBalance`` says which.
    vendor_balances: list[VendorBalanceView]
    fake_calls: FakeCallGuardView
    capabilities: CapabilitiesView


# ---------------------------------------------------------------------------
# performance
# ---------------------------------------------------------------------------
class OperationLatencyView(ApiModel):
    """Nearest-rank p50/p95 of one vendor operation, with all three of its denominators."""

    operation: VendorOperation
    calls: int
    measured_calls: int
    sample_count: int
    p50_ms: int | None
    p95_ms: int | None


class ComponentStatusView(ApiModel):
    """One dot on the System status strip, with the evidence it was derived from.

    **No outbound call produces any of these.** They are read from
    :func:`~hbd.db.admin.metrics.read_capabilities` and from the cached balance rows the
    ARQ worker writes; the admin process holds no vendor credential and makes no HTTP
    request. A "System status" card is exactly where somebody reaches for a client, so the
    refusal is a property of the shape: there is no field here a probe would fill.

    ``evidence`` is a short machine-readable phrase naming what was actually observed, so a
    dot that says ``NOT_PROBED`` also says why nobody probed it.
    """

    component: str
    state: ComponentState
    as_of: datetime | None
    evidence: str


class OrderStateCountView(ApiModel):
    """How many orders of the cohort are in one state RIGHT NOW. A survivor count."""

    state: OrderState
    count: int


class OrderFunnelView(ApiModel):
    """Where a created-at cohort of orders stands. Survivors, never passages.

    There is no ``abandoned`` field: drafts are deleted outright at the abandoned-draft
    cutoff, so any such number would decay towards zero as the window lengthens and read as
    "nobody abandons any more". ``isStateTransitionLog`` on the capabilities block is what
    tells the SPA these are positions and not a flow.
    """

    created: int
    paid: int
    by_state: list[OrderStateCountView]


class PerformanceResponse(ApiModel):
    """``GET /api/metrics/dashboard/performance`` — how fast, how reliably, and what is up."""

    window: WindowView | None
    #: Counted on ``delivered_at``, so it reconciles with the latency beside it.
    delivered_orders: TrendView
    #: Sampled on ``delivered_at`` for the same reason — see
    #: :func:`~hbd.db.admin.metrics.delivered_latency`. NOT the created-at cohort the pulse
    #: and ``/metrics/latency`` publish by contract.
    delivery_latency: LatencyView
    music_render_latency: OperationLatencyView
    failures: list[FailureView]
    order_funnel: OrderFunnelView
    system_status: list[ComponentStatusView]
    capabilities: CapabilitiesView


# ---------------------------------------------------------------------------
# series
# ---------------------------------------------------------------------------
class CostSplitView(ApiModel):
    """One ``(vendor, operation)`` slice of where the money went. Ordered by calls."""

    vendor: Vendor
    operation: VendorOperation
    cost: UsdCost


class SeriesResponse(ApiModel):
    """``GET /api/metrics/dashboard/series`` — every chart on the page, in one request."""

    window: WindowView | None
    bucket: SeriesBucket
    #: True only when the request gave a lower bound. With ``?to=`` alone the series is open
    #: below and a filled bucket before the first row would claim "0" for days this
    #: deployment did not exist, so the fill is skipped and this says so.
    is_zero_filled: bool
    signups: list[CountPointView]
    delivered: list[CountPointView]
    #: NEVER zero-filled — see the module docstring. A bucket with no sale is absent.
    revenue: list[MoneyPointView]
    #: NEVER zero-filled. A bucket with calls but no rate carries ``cost.amountUsd: null``.
    spend: list[SpendPointView]
    unattributed_spend: list[SpendPointView]
    #: Not a series: one slice per ``(vendor, operation)`` over the whole window.
    cost_split: list[CostSplitView]
    #: Not a series either: the cohort's positions over the whole window.
    order_funnel: OrderFunnelView


# ---------------------------------------------------------------------------
# vendor
# ---------------------------------------------------------------------------
class VendorCostPerSongView(ApiModel):
    """One vendor's cut of the cost-per-delivered-song figure, with its coverage.

    ``CostPerSongView`` on the finance response answers "what does a song cost"; this answers
    "and who charged us for it", which is the only form of the number an operator can act on
    — the remedy for an expensive song is a different model or a different vendor, and the
    aggregate names neither.

    **These rows do not sum to the finance card, and three separate things stop them.**
    ``attributedOrders`` double-counts an order across every vendor that rendered it, so the
    coverage column is not additive at all. ``costUsd`` does partition the window exactly —
    but only while every group is rendered, which a top-N table or a vendor filter breaks.
    And a ``null`` is not an addend. The aggregate is on ``/dashboard/finance``; take it from
    there rather than from a sum of these.

    **There is no :class:`UsdCost` here, and its absence is a real gap rather than an
    oversight.** That primitive exists so a dollar figure cannot travel without its
    provenance and its coverage in CALLS; this read groups by vendor and carries neither
    ``costedCalls`` nor a per-vendor ``costSource``. The provenance for the same window and
    the same filters is ``costProvenance`` on this response — partitioned by source rather
    than by vendor — and the per-vendor pair is on ``GET /api/metrics/vendor-usage``, which
    groups the same table the other way. Do not read ``costUsd`` here as a priced-and-sourced
    figure the way ``vendorSpend`` may be read.
    """

    vendor: Vendor
    #: Summed over this vendor's priced rows in the window. ``null`` — never ``0.0`` — when
    #: none of them carried a cost.
    cost_usd: float | None
    #: Why there is no amount, when there is none. Only ever ``NOT_PRICED``: a vendor with no
    #: calls in the window has no row here at all, so "not instrumented" cannot arise on a
    #: row that exists.
    unavailable_reason: AbsenceReason | None
    #: Delivered orders carrying at least one call from THIS vendor — how much of the cohort
    #: the numerator covers, and the reason the average is not a complete figure.
    attributed_orders: int
    #: ``costUsd / deliveredOrders`` — over the whole cohort, deliberately, not over
    #: ``attributedOrders``. Dividing by the covered subset would report the cost of the
    #: orders we happen to have instrumented, a figure that IMPROVES as instrumentation
    #: degrades. ``null`` when the vendor is unpriced or nothing was delivered.
    cost_per_song: RatioView | None

    @model_validator(mode="after")
    def _an_absent_cost_carries_its_reason(self) -> Self:
        if (self.cost_usd is None) is not (self.unavailable_reason is not None):
            raise ValueError("an absent cost carries its reason and a present one does not")
        return self


class VendorUnitsPerSongView(ApiModel):
    """What one delivered song CONSUMES from one vendor, in that vendor's own units.

    **The three unit families do not share an axis.** Tokens, billed characters and
    milliseconds of audio are incommensurable: each is a separate row on any table and a
    separate chart, never three series on one pair of axes, never summed, never totalled into
    a "units" column. A chat completion has no billed characters and a speech synthesis has
    no tokens, so each quantity is ``null`` for the families nobody measured — a ``0`` there
    would say the vendor charged us for nothing.

    **``totalTokens`` is CONSUMPTION and never a remaining balance.** It only grows, and no
    reading of it says anything about what is left; the remaining side is ``vendorBalances``,
    a different table with a different clock, polled by the worker. A tile that put a token
    count under a "remaining" heading would be reporting spend as headroom.

    Every per-song figure is over the same cohort-wide ``deliveredOrders`` the cost rows use,
    so cost-per-song and tokens-per-song move against one population: cost moving alone is a
    price change, the two moving together is a change in what we ask the vendor to do. The
    coverage caveat is the same one ``VendorCostPerSongView`` states, and the number that
    quantifies it — ``attributedOrders`` — is on that row for the same vendor and window.
    """

    vendor: Vendor
    total_tokens: int | None
    billed_characters: int | None
    audio_ms: int | None
    #: ``null`` when the vendor measured no tokens at all; a present ratio with a ``null``
    #: value means nothing was delivered to divide by. The two absences are different facts.
    tokens_per_song: RatioView | None
    characters_per_song: RatioView | None
    #: Still MILLISECONDS. Not converted to seconds anywhere on this wire: the column is
    #: milliseconds, and a unit change here is one the schema cannot show happening.
    audio_ms_per_song: RatioView | None


class CostProvenanceView(ApiModel):
    """One ``cost_source`` bucket: how much of the window's money was arrived at HOW.

    Every other money shape on this surface collapses provenance to one source and an
    ``isCostMixed`` boolean, so the actual mix is not reconstructible from them: an operator
    can be told a figure is mixed but never that nine-tenths of it is arithmetic against a
    rate somebody typed into an environment variable. This is the breakdown that boolean
    summarises.

    **``costSource: null`` is its own bucket and means NOT PRICED.** The calls happened and
    were recorded; no cost could be computed for them. So ``costUsd`` is ``null`` there while
    ``calls`` is positive, and that combination is the point of the row rather than a
    contradiction in it.

    **"0 reported" and "not priced" must never render the same.** A vendor that reports a
    genuine ``0.0`` — OpenRouter's free models do, and the provider keeps that zero
    deliberately — lands in ``vendor_reported`` with ``costUsd: 0.0``: MEASURED. A
    rate-card-only vendor with no configured rate lands in the ``null`` bucket: UNMEASURED.
    One says "this cost nothing", the other says "nobody could say", and collapsing them is
    how a deployment concludes its rendering pipeline is free.
    """

    #: The real :class:`~hbd.contracts.CostSource` member, not the ``str`` the collapsed
    #: shapes carry: this is a partition, so ``"mixed"`` cannot arise in it and a widened
    #: type would invite a consumer to expect one.
    cost_source: CostSource | None
    #: Calls in this bucket. Always measured, in every bucket, including the unpriced one.
    calls: int
    #: Their summed cost. ``null`` in the unpriced bucket by construction; ``0.0`` is a
    #: legitimate value in the ``vendor_reported`` bucket and means the vendor said zero.
    cost_usd: float | None

    @model_validator(mode="after")
    def _the_unpriced_bucket_is_the_one_without_money(self) -> Self:
        if (self.cost_usd is None) is not (self.cost_source is None):
            raise ValueError("a priced bucket carries an amount and the unpriced one does not")
        return self


class VendorResponse(ApiModel):
    """``GET /api/metrics/dashboard/vendor`` — the Vendor section, in one request.

    Its own section rather than three more fields on ``FinanceResponse``, because the
    questions differ: finance asks what a song costs and what is left over, and this asks
    which vendor that money went to, in what units, and how any of it was arrived at. Fetched
    on its own cadence too — spend moves slower than the fire-hose cards.

    **``vendorSpend`` and ``vendorBalances`` also appear on ``/dashboard/finance``, under
    exactly these names, from exactly these functions.** They are not recomputed differently
    and not renamed: republishing the same figure under a second name is how two cards come
    to disagree, and republishing it under the same name is what lets the section stand alone
    in one request. ``vendorSpend`` is the total the per-vendor rows partition — reading them
    without it is how a partial breakdown gets mistaken for a total — and the balances are
    what turn a cost-per-song into "and there is this much left". The two responses agree
    whenever they are fetched over the same window, which both echo.
    """

    window: WindowView | None
    #: The denominator of every per-song figure below: delivered orders in the window,
    #: counted once for the whole cohort and used identically by the cost rows and the unit
    #: rows. Published here as well as inside each ``RatioView`` so an EMPTY breakdown still
    #: says what it would have divided by.
    delivered_orders: int
    #: The window's whole vendor spend, fake-provider rows excluded structurally and the
    #: unspendable operations excluded — the same figure ``/dashboard/finance`` publishes
    #: under this name, from the same function with the same exclusions.
    vendor_spend: UsdCost
    #: Most-covered vendor first. Empty means nothing was delivered in the window, or nothing
    #: that was delivered carries an attributed call; ``capabilities.isVendorUsage`` tells
    #: those apart from a deployment whose worker records nothing at all.
    cost_per_song_by_vendor: list[VendorCostPerSongView]
    #: One row per vendor, ordered by vendor: all three quantity columns are nullable, so
    #: there is no volume column an honest ordering could use.
    units_per_song_by_vendor: list[VendorUnitsPerSongView]
    #: The provenance partition over the same window and the same exclusions, busiest bucket
    #: first with the unpriced bucket last. It partitions CALLS, not the money above it.
    cost_provenance: list[CostProvenanceView]
    #: Read from the cached table. This process makes no outbound call and holds no vendor
    #: credential — the same rows the finance response and the status strip are built from.
    vendor_balances: list[VendorBalanceView]
    capabilities: CapabilitiesView


# ---------------------------------------------------------------------------
# plan liability
# ---------------------------------------------------------------------------
class CurrencyAmountView(ApiModel):
    """A money total that carries its unit. There is no scalar money on this surface."""

    currency: str
    amount_minor: int


class PlanUtilisationBucketView(ApiModel):
    """One tenth of the ENDED-plan utilisation distribution. All ten always present.

    ``from``/``to`` rather than ``lower``/``upper`` because that is the vocabulary
    :class:`~hbd.admin.schemas.dashboard.SimilarityBucketView` already put on the wire for
    the only other histogram in this panel, and a second spelling for the same thing is a
    second chart component. ``from`` is a Python keyword, so the field is ``from_`` with an
    explicit alias — overridden towards the SPA rather than away from it.
    """

    from_: float = Field(alias="from")
    to: float
    count: int


class PlanLiabilityResponse(ApiModel):
    """``GET /api/metrics/plans`` — what the running plans owe. A STATE, so no window.

    Liability is not a flow: "how much was owed during March" is a question this table
    cannot answer. So this route takes no ``from``/``to`` — the same argument the pulse
    makes for taking none — and echoes the ``asOf`` instant both the liability row and the
    utilisation histogram were computed at, so the number stays reproducible.

    **The liability is in SONGS.** There is no soʻm figure for unconsumed songs anywhere
    here, because valuing one means dividing ``amountMinor`` by ``songsIncluded``, which is
    an accounting allocation policy nobody in this codebase has chosen. ``liveAmounts`` is
    the measured total of what the running plans were SOLD for, which is a different and
    honest number.

    ``liveHolders`` excludes every customer who sent ``/forget`` while their plan was
    running, because ``COUNT(DISTINCT)`` does not count NULLs.
    ``liveAnonymisedPlans`` is what makes that undercount visible.
    """

    as_of: datetime
    live_plans: int
    #: Distinct identified holders. Understates by exactly ``liveAnonymisedPlans``.
    live_holders: int
    live_anonymised_plans: int
    live_plans_with_songs_left: int
    #: ``null`` when no plan is live; ``0`` when plans are live and owe nothing.
    unconsumed_songs: int | None
    #: What the RUNNING plans were sold for, per currency. The measured figure, not a
    #: pro-rata valuation of the songs still owed — see the class docstring. Empty when
    #: nothing is live, which ``livePlans: 0`` beside it already says.
    live_amounts: list[CurrencyAmountView]
    ended_plans: int
    #: Songs paid for and never claimed on plans that have ENDED. ``null`` when none has.
    breakage_songs: int | None
    expiring_within_days: int
    expiring_plans: int
    expiring_songs_left: int | None
    #: Ten bars, always, over ENDED plans only. ``endedPlans`` above is the denominator.
    utilisation: list[PlanUtilisationBucketView]
    #: False means no plan has ever been sold here, so ten empty bars are "nothing to show"
    #: rather than "everybody used nothing".
    is_plan_revenue: bool


# ---------------------------------------------------------------------------
# projections
# ---------------------------------------------------------------------------
def to_fx_rate_view(settings: AdminSettings) -> FxRateView:
    """The published rate, or a pair of nulls. ``AdminSettings`` guarantees they agree."""
    return FxRateView(
        uzs_per_usd=settings.admin_uzs_per_usd, as_of=settings.admin_uzs_per_usd_as_of
    )


def to_trend_view(trend: Trend) -> TrendView:
    """Project a count and its predecessor, forming the change only where one is defined."""
    ratio = trend.change_ratio
    change = (
        None
        if ratio is None or trend.previous is None
        else RatioView(
            value=ratio,
            numerator=float(trend.current - trend.previous),
            denominator=float(trend.previous),
        )
    )
    return TrendView(current=trend.current, previous=trend.previous, change=change)


def to_usd_cost(
    *,
    amount_usd: float | None,
    costed_calls: int,
    calls: int,
    cost_source: str | None,
) -> UsdCost:
    """Assemble a dollar figure with its coverage, naming the absence when there is one.

    The reason is derived rather than passed, because it is derivable and a passed one could
    disagree with the numbers beside it: no calls at all is ``NOT_INSTRUMENTED``, calls with
    nothing priced is ``NOT_PRICED``, and those are the only two ways an amount can be
    missing once the query has run.
    """
    reason = (
        None
        if amount_usd is not None
        else (AbsenceReason.NOT_INSTRUMENTED if calls == 0 else AbsenceReason.NOT_PRICED)
    )
    return UsdCost(
        amount_usd=amount_usd,
        costed_calls=costed_calls,
        calls=calls,
        cost_source=cost_source,
        unavailable_reason=reason,
    )


def _to_money_total(total: RevenueTotal) -> MoneyTotal:
    return MoneyTotal(
        source=total.source,
        product=total.product,
        currency=total.currency,
        provider=total.provider,
        is_stub_rail=total.provider == STUB_PROVIDER_NAME,
        sales=total.sales,
        amount_minor=total.amount_minor,
    )


def _to_money_point(bucket: RevenueBucket) -> MoneyPointView:
    return MoneyPointView(
        bucket=bucket.bucket,
        started_at=bucket.started_at,
        source=bucket.source,
        product=bucket.product,
        currency=bucket.currency,
        provider=bucket.provider,
        is_stub_rail=bucket.provider == STUB_PROVIDER_NAME,
        sales=bucket.sales,
        amount_minor=bucket.amount_minor,
    )


def to_audience_response(
    *,
    window: TimeWindow | None,
    totals: AccountTotals,
    active: ActiveAccounts,
    churn: ChurnCounts,
    subscription_churn: SubscriptionChurn,
    language_mix: LanguageMixTotals,
    activity: tuple[ActivityPoint, ...],
    activity_bucket: SeriesBucket,
    capabilities: ReadCapabilities,
) -> AudienceResponse:
    """Assemble the Audience section. Keyword-only: eight aggregates of eight shapes.

    **Two of them are dropped to ``null`` rather than published as zeroes, and each has its
    own probe.** ``churn`` goes ``null`` when no membership transition has ever been
    observed, and ``subscriptionChurn`` goes ``null`` when no plan has ever been sold —
    ``capabilities.isPlanRevenue``, which exists for exactly this and is why there is no
    fourth flag on the response. "Nobody blocked the bot", "nobody let a plan lapse" and "we
    have never watched" are three different sentences, and only the last is true on a fresh
    deployment.

    The two churns are different quantities in the same card; :class:`SubscriptionChurnView`
    carries that argument, because the field docstrings are what a reader of the card has in
    front of them.

    ``activityBucket`` is echoed rather than defaulted here: this builder does not decide the
    grain, it reports the one the route asked the database for.
    """
    return AudienceResponse(
        window=to_window_view(window),
        total_accounts=_total_accounts_trend(totals),
        new_accounts=to_trend_view(totals.total_trend),
        active_accounts=ActiveAccountsView(
            day=active.day, week=active.week, month=active.month, as_of=active.as_of
        ),
        blocked_accounts=totals.blocked,
        bot_blocked_accounts=totals.bot_blocked,
        churn=(
            ChurnView(
                blocked=to_trend_view(churn.blocked), unblocked=to_trend_view(churn.unblocked)
            )
            if capabilities.is_churn_instrumented
            else None
        ),
        is_churn_instrumented=capabilities.is_churn_instrumented,
        subscription_churn=(
            _to_subscription_churn(subscription_churn) if capabilities.is_plan_revenue else None
        ),
        language_mix=_to_language_mix(language_mix),
        activity_history=[
            ActivityPointView(
                bucket=point.bucket,
                started_at=point.started_at,
                day=point.day,
                week=point.week,
                month=point.month,
            )
            for point in activity
        ],
        activity_bucket=activity_bucket,
        is_activity_history=capabilities.is_activity_history,
    )


def _to_subscription_churn(churn: SubscriptionChurn) -> SubscriptionChurnView:
    """Project the renewal counts, forming the rate through :class:`RatioView`.

    ``rate`` is built unconditionally because the denominator is always MEASURED — a window
    in which nothing ended really did have zero endings — and :class:`RatioView` is the shape
    that already expresses "a denominator of zero has no value". The quotient itself comes
    from the view's own ``rate`` property rather than being divided again here, so the number
    on the card and the number the database layer documents cannot drift.
    """
    return SubscriptionChurnView(
        ended_plans=churn.ended_plans,
        renewed=churn.renewed,
        lapsed=churn.lapsed,
        anonymised_ended=churn.anonymised_ended,
        rate=RatioView(
            value=churn.rate,
            numerator=float(churn.lapsed),
            denominator=float(churn.ended_plans),
        ),
    )


def _to_language_mix(mix: LanguageMixTotals) -> LanguageMixView:
    """Project the split, giving every entry the block's own denominator.

    The share is formed against ``mix.accounts`` and never against the sum of the entries
    rendered. They are equal today — ``ui_language`` is ``NOT NULL``, so every account is in
    exactly one entry — and the moment anything filters or truncates the list they stop
    being, which is the failure the container was written to prevent.
    """
    total = float(mix.accounts)
    return LanguageMixView(
        languages=[
            LanguageMixEntryView(
                language=entry.language,
                accounts=entry.accounts,
                share=RatioView(
                    value=None if total == 0 else entry.accounts / total,
                    numerator=float(entry.accounts),
                    denominator=total,
                ),
            )
            for entry in mix.languages
        ],
        accounts=mix.accounts,
    )


def _total_accounts_trend(totals: AccountTotals) -> TrendView:
    """ "How many accounts exist" and how many existed at the start of the window.

    The previous value is DERIVED and exactly so: ``total`` counts every account ever
    created, and every account created inside the window is counted by ``total_trend``, so
    ``total - created_in_window`` is precisely the population at the window's lower bound.
    No approximation and no second query.

    It is ``None`` whenever the sign-up trend's own previous is — that is, whenever the
    request gave no lower bound — because there is then no instant to have counted back to.
    """
    created = totals.total_trend
    previous = None if created.previous is None else totals.total - created.current
    return to_trend_view(Trend(current=totals.total, previous=previous))


def _to_derived_revenue(*, delivered: int, settings: AdminSettings) -> DerivedRevenueView:
    """Delivered × the mirrored price, or an explicit refusal to guess at one.

    ``AdminSettings`` binds the price and its currency both-or-neither, so one check covers
    both. Unset means this deployment has not published its price, and the honest answer is
    the count with no money beside it — never the bot model's default, which would publish a
    price this deployment may not be charging.
    """
    price, currency = settings.admin_single_song_price_minor, settings.admin_kit_currency
    if price is None or currency is None:
        return DerivedRevenueView(
            delivered_songs=delivered,
            unit_price_minor=None,
            currency=None,
            amount_minor=None,
            unavailable_reason=AbsenceReason.NO_PRICE_PUBLISHED,
        )
    return DerivedRevenueView(
        delivered_songs=delivered,
        unit_price_minor=price,
        currency=currency,
        amount_minor=delivered * price,
        unavailable_reason=None,
    )


def _to_net_run_rate(
    *,
    window: TimeWindow,
    revenue: tuple[RevenueTotal, ...],
    spend: VendorUsageTotals,
    settings: AdminSettings,
    days: int,
) -> NetRunRateView:
    """Revenue minus spend over the run-rate window, or ``null`` with the reason it is not.

    Three gates, in order, and each has a distinct remedy the SPA can print: no FX rate
    published; the window's receipts mix currencies, so there is no single net and this
    server will not invent an exchange between them; and no spend was priced, so the
    subtraction has nothing to subtract.

    The conversion is soʻm-side: the dollar cost is multiplied UP into minor units of the
    receipts' currency rather than the revenue being divided down into dollars, so the
    figure stays in the unit the operator sells in and no rounding happens in the middle of
    the money they took.
    """
    totals = [_to_money_total(item) for item in revenue]
    cost = to_usd_cost(
        amount_usd=spend.cost_usd,
        costed_calls=spend.costed_calls,
        calls=spend.calls,
        cost_source=cost_source_of(spend.cost_source, is_mixed=spend.is_cost_mixed),
    )
    fx = to_fx_rate_view(settings)
    currencies = {item.currency for item in revenue}

    def refuse(reason: AbsenceReason) -> NetRunRateView:
        return NetRunRateView(
            window=WindowView(from_=window.start, to=window.end),
            revenue=totals,
            cost=cost,
            fx_used=fx,
            currency=None,
            net_minor=None,
            annualised_minor=None,
            unavailable_reason=reason,
        )

    rate = settings.admin_uzs_per_usd
    if rate is None:
        return refuse(AbsenceReason.NO_FX_RATE)
    if len(currencies) > 1:
        return refuse(AbsenceReason.MIXED_CURRENCIES)
    if spend.cost_usd is None:
        return refuse(AbsenceReason.NOT_PRICED)
    currency = next(iter(currencies), None) or (settings.admin_kit_currency or "")
    if not currency:
        return refuse(AbsenceReason.NO_PRICE_PUBLISHED)
    gross = sum(item.amount_minor for item in revenue)
    net = gross - round(spend.cost_usd * rate * _MINOR_UNITS_PER_MAJOR)
    return NetRunRateView(
        window=WindowView(from_=window.start, to=window.end),
        revenue=totals,
        cost=cost,
        fx_used=fx,
        currency=currency,
        net_minor=net,
        annualised_minor=round(net * DAYS_PER_YEAR / days),
        unavailable_reason=None,
    )


#: Minor units in one major unit. The som's subunit is the tiyin at 1/100, which is what
#: ``single_song_price_minor``'s 700 000 for 7 000 soʻm already assumes.
_MINOR_UNITS_PER_MAJOR: int = 100


def to_finance_response(
    *,
    window: TimeWindow | None,
    revenue: tuple[RevenueTotal, ...],
    unpriced: UnpricedTopups,
    delivered: Trend,
    spend: VendorUsageTotals,
    cost_per_song: CostPerDeliveredSong,
    unattributed: tuple[UnattributedSpendPerBucket, ...],
    balances: tuple[VendorBalanceState, ...],
    fake_calls: FakeCallGuard,
    capabilities: ReadCapabilities,
    settings: AdminSettings,
    run_rate_window: TimeWindow,
    run_rate_revenue: tuple[RevenueTotal, ...],
    run_rate_spend: VendorUsageTotals,
) -> FinanceResponse:
    """Assemble the Finance section. Every figure keeps its unit, its coverage and its rail."""
    per_song = _per_song_ratio(cost_per_song)
    return FinanceResponse(
        window=to_window_view(window),
        revenue=[_to_money_total(item) for item in revenue],
        unpriced_topups=UnpricedTopupsView(unpriced=unpriced.unpriced, priced=unpriced.priced),
        derived_revenue=_to_derived_revenue(delivered=delivered.current, settings=settings),
        vendor_spend=to_usd_cost(
            amount_usd=spend.cost_usd,
            costed_calls=spend.costed_calls,
            calls=spend.calls,
            cost_source=cost_source_of(spend.cost_source, is_mixed=spend.is_cost_mixed),
        ),
        cost_per_song=CostPerSongView(
            cost=to_usd_cost(
                amount_usd=cost_per_song.cost_usd,
                costed_calls=cost_per_song.costed_calls,
                calls=cost_per_song.calls,
                cost_source=cost_source_of(
                    cost_per_song.cost_source, is_mixed=cost_per_song.is_cost_mixed
                ),
            ),
            delivered_orders=cost_per_song.delivered_orders,
            attributed_orders=cost_per_song.attributed_orders,
            per_song_usd=per_song,
        ),
        unattributed_spend=_fold_unattributed(unattributed),
        net_run_rate=_to_net_run_rate(
            window=run_rate_window,
            revenue=run_rate_revenue,
            spend=run_rate_spend,
            settings=settings,
            days=settings.admin_dashboard_run_rate_days,
        ),
        fx=to_fx_rate_view(settings),
        vendor_balances=[_to_balance_view(item) for item in balances],
        fake_calls=FakeCallGuardView(
            fake_calls=fake_calls.fake_calls, total_calls=fake_calls.total_calls
        ),
        capabilities=to_capabilities_view(capabilities),
    )


def _per_song_ratio(cost: CostPerDeliveredSong) -> RatioView | None:
    """The quotient, formed only where both operands exist. ``None`` is the honest answer.

    ``null`` when the cost is null (calls recorded, no rate configured) and ``null`` when
    nothing was delivered. The two absences look identical on the card and differ in the
    fields beside it, which is exactly why the ratio is not asked to carry the distinction.
    """
    if cost.cost_usd is None or cost.delivered_orders == 0:
        return None
    return RatioView(
        value=cost.cost_usd / cost.delivered_orders,
        numerator=cost.cost_usd,
        denominator=float(cost.delivered_orders),
    )


def _fold_unattributed(buckets: tuple[UnattributedSpendPerBucket, ...]) -> UsdCost:
    """Collapse the unattributed series to one figure, leaving ``None`` when nothing priced.

    The one place this module sums money in Python, and it obeys the same rule the database
    does: ``None + None`` stays ``None``. A bucket that priced nothing contributes nothing
    and does not turn the total into ``0.0``.
    """
    priced = [item.cost_usd for item in buckets if item.cost_usd is not None]
    return to_usd_cost(
        amount_usd=sum(priced) if priced else None,
        costed_calls=sum(item.costed_calls for item in buckets),
        calls=sum(item.calls for item in buckets),
        cost_source=None if not priced else "derived",
    )


def _to_balance_view(state: VendorBalanceState) -> VendorBalanceView:
    return VendorBalanceView(
        vendor=state.vendor,
        is_fallback=state.is_fallback,
        provider=state.provider,
        unit=state.balance_unit,
        remaining=state.balance_remaining,
        total=state.balance_total,
        used=state.balance_used,
        is_unbounded=state.is_unbounded,
        quota_resets_at=state.quota_resets_at,
        quota_reset_hint=state.quota_reset_hint,
        plan_tier=state.plan_tier,
        subscription_status=state.subscription_status,
        songs_remaining=state.songs_remaining,
        per_song_rate=state.per_song_rate,
        estimate_basis=state.estimate_basis,
        fetched_at=state.fetched_at,
        checked_at=state.checked_at,
        is_last_poll_ok=state.is_last_poll_ok,
        http_status=state.http_status,
        error_code=state.error_code,
        consecutive_failures=state.consecutive_failures,
    )


def to_vendor_response(
    *,
    window: TimeWindow | None,
    delivered_orders: int,
    spend: VendorUsageTotals,
    cost_per_song: tuple[VendorCostPerSong, ...],
    units_per_song: tuple[VendorUnitsPerSong, ...],
    provenance: tuple[CostProvenance, ...],
    balances: tuple[VendorBalanceState, ...],
    capabilities: ReadCapabilities,
) -> VendorResponse:
    """Assemble the Vendor section. One cohort count, one total, three breakdowns.

    ``deliveredOrders`` is taken ONCE by the route and threaded into both breakdowns and onto
    the response, so the cost rows, the unit rows and the number printed under them cannot
    disagree about how many songs shipped — the same discipline
    :func:`to_finance_response` applies to the identical count.

    ``vendorSpend`` is built by the same helper the finance response uses, from the same
    aggregate with the same exclusions. It is republished here rather than recomputed
    differently: the per-vendor rows below are a partition of it, and a breakdown rendered
    without the total it partitions is how a subset gets read as a whole.
    """
    return VendorResponse(
        window=to_window_view(window),
        delivered_orders=delivered_orders,
        vendor_spend=to_usd_cost(
            amount_usd=spend.cost_usd,
            costed_calls=spend.costed_calls,
            calls=spend.calls,
            cost_source=cost_source_of(spend.cost_source, is_mixed=spend.is_cost_mixed),
        ),
        cost_per_song_by_vendor=[_to_vendor_cost_per_song(item) for item in cost_per_song],
        units_per_song_by_vendor=[_to_vendor_units_per_song(item) for item in units_per_song],
        cost_provenance=[
            CostProvenanceView(
                cost_source=item.cost_source, calls=item.calls, cost_usd=item.cost_usd
            )
            for item in provenance
        ],
        vendor_balances=[_to_balance_view(item) for item in balances],
        capabilities=to_capabilities_view(capabilities),
    )


def _to_vendor_cost_per_song(cost: VendorCostPerSong) -> VendorCostPerSongView:
    """One vendor's cost row, with the reason for an absent amount rather than a zero.

    ``NOT_PRICED`` and never ``NOT_INSTRUMENTED``: this row exists only because the vendor
    has calls attributed to a delivered order in the window, so "nothing recorded" is not a
    state a row can be in — it is a vendor that is simply absent from the list.
    """
    return VendorCostPerSongView(
        vendor=cost.vendor,
        cost_usd=cost.cost_usd,
        unavailable_reason=None if cost.cost_usd is not None else AbsenceReason.NOT_PRICED,
        attributed_orders=cost.attributed_orders,
        cost_per_song=_ratio(cost.cost_per_song_usd, cost.cost_usd, cost.delivered_orders),
    )


def _to_vendor_units_per_song(units: VendorUnitsPerSong) -> VendorUnitsPerSongView:
    """One vendor's three unit rows. Each quotient comes from the view's own property.

    Divided here a second time would be two implementations of one number; the view owns the
    arithmetic and this owns only the shape it is rendered in.
    """
    return VendorUnitsPerSongView(
        vendor=units.vendor,
        total_tokens=units.total_tokens,
        billed_characters=units.billed_characters,
        audio_ms=units.audio_ms,
        tokens_per_song=_ratio(units.tokens_per_song, units.total_tokens, units.delivered_orders),
        characters_per_song=_ratio(
            units.characters_per_song, units.billed_characters, units.delivered_orders
        ),
        audio_ms_per_song=_ratio(units.audio_ms_per_song, units.audio_ms, units.delivered_orders),
    )


def _ratio(
    value: float | None, numerator: float | int | None, denominator: int
) -> RatioView | None:
    """A quotient the view already computed, wrapped with the two operands that formed it.

    ``None`` — no ratio at all — when the NUMERATOR was never measured: an unpriced vendor
    has no cost to divide and a speech vendor has no tokens, and a ratio object with a null
    value would say "we measured this and there was nothing to divide by", which is the other
    absence. When the numerator exists and the denominator is zero the object IS built, with
    a null value, because :class:`RatioView` is the shape that states that case exactly.
    """
    if numerator is None:
        return None
    return RatioView(value=value, numerator=float(numerator), denominator=float(denominator))


def to_performance_response(
    *,
    window: TimeWindow | None,
    delivered: Trend,
    latency: LatencySummary,
    music: OperationLatency,
    failures: tuple[FailureCount, ...],
    funnel: OrderFunnel,
    balances: tuple[VendorBalanceState, ...],
    capabilities: ReadCapabilities,
    now: datetime,
) -> PerformanceResponse:
    """Assemble the Performance section, including the status strip.

    The strip is derived from capabilities and from the cached balance rows and from nothing
    else. No component reports ``OK`` because nobody looked: an unwritten subsystem is
    ``NOT_PROBED`` with an evidence string saying so.
    """
    return PerformanceResponse(
        window=to_window_view(window),
        delivered_orders=to_trend_view(delivered),
        delivery_latency=to_latency_view(latency),
        music_render_latency=OperationLatencyView(
            operation=music.operation,
            calls=music.calls,
            measured_calls=music.measured_calls,
            sample_count=music.sample_count,
            p50_ms=music.p50_ms,
            p95_ms=music.p95_ms,
        ),
        failures=[to_failure_view(failure) for failure in failures],
        order_funnel=_to_funnel_view(funnel),
        system_status=_to_system_status(capabilities, balances, now=now),
        capabilities=to_capabilities_view(capabilities),
    )


def _to_funnel_view(funnel: OrderFunnel) -> OrderFunnelView:
    return OrderFunnelView(
        created=funnel.created,
        paid=funnel.paid,
        by_state=[
            OrderStateCountView(state=item.state, count=item.count) for item in funnel.by_state
        ],
    )


def _to_system_status(
    capabilities: ReadCapabilities,
    balances: tuple[VendorBalanceState, ...],
    *,
    now: datetime,
) -> list[ComponentStatusView]:
    """The status strip: what is instrumented, and what the last poll of each vendor said.

    Every dot is a fact somebody wrote down. There is no health check here and no client to
    make one with — see :class:`ComponentStatusView`. A capability that is false becomes
    ``NOT_PROBED`` rather than ``DEGRADED``, because "nothing has written this" is not
    evidence of a fault.
    """
    strip = [
        _capability_dot("vendor_usage", capabilities.is_vendor_usage, "vendor_usage rows"),
        _capability_dot("vendor_cost", capabilities.is_vendor_cost, "priced vendor_usage rows"),
        _capability_dot("churn", capabilities.is_churn_instrumented, "bot_membership_events rows"),
        _capability_dot(
            "activity_history", capabilities.is_activity_history, "user_activity_snapshots rows"
        ),
        _capability_dot("plan_revenue", capabilities.is_plan_revenue, "plan_purchases rows"),
        _capability_dot("topup_revenue", capabilities.is_topup_revenue, "topup_purchases rows"),
        _capability_dot("balance_poller", capabilities.is_vendor_balance, "vendor_balances rows"),
    ]
    strip.extend(
        ComponentStatusView(
            component=f"{item.vendor.value}{'_fallback' if item.is_fallback else ''}",
            state=ComponentState.OK if item.is_last_poll_ok else ComponentState.DEGRADED,
            as_of=item.checked_at,
            evidence=(
                f"last poll ok, {_age_phrase(item.fetched_at, now)}"
                if item.is_last_poll_ok
                else f"{item.error_code or 'poll failed'}"
                f" x{item.consecutive_failures}, {_age_phrase(item.fetched_at, now)}"
            ),
        )
        for item in balances
    )
    return strip


def _capability_dot(component: str, is_present: bool, evidence: str) -> ComponentStatusView:
    """A capability rendered as a dot. False is ``NOT_PROBED``, never ``DEGRADED``."""
    return ComponentStatusView(
        component=component,
        state=ComponentState.OK if is_present else ComponentState.NOT_PROBED,
        as_of=None,
        evidence=f"{evidence} present" if is_present else f"no {evidence}",
    )


def _age_phrase(fetched_at: datetime | None, now: datetime) -> str:
    """How old the last successful answer is, in whole seconds, or that there is none."""
    if fetched_at is None:
        return "never answered"
    return f"answered {int((now - fetched_at).total_seconds())}s ago"


def to_series_response(
    *,
    window: TimeWindow | None,
    bucket: SeriesBucket,
    signups: tuple[NewAccountsPerBucket, ...],
    delivered: tuple[DeliveredPerBucket, ...],
    revenue: tuple[RevenueBucket, ...],
    spend: tuple[VendorSpendPerBucket, ...],
    unattributed: tuple[UnattributedSpendPerBucket, ...],
    cost_split: tuple[VendorSpendSplit, ...],
    funnel: OrderFunnel,
) -> SeriesResponse:
    """Assemble every chart on the page, folding to WEEK/MONTH and zero-filling the counts.

    Counts are zero-filled only when the request supplied a lower bound; money never is.
    Both rules are in the module docstring and both are visible on the wire through
    ``isZeroFilled``.
    """
    is_filled = window is not None and window.start is not None
    signup_points = fold_points(
        [(item.bucket, item.started_at, item.count) for item in signups], bucket
    )
    delivered_points = fold_points(
        [(item.bucket, item.started_at, item.delivered) for item in delivered], bucket
    )
    if is_filled and window is not None:
        signup_points = _zero_fill(signup_points, bucket, window)
        delivered_points = _zero_fill(delivered_points, bucket, window)
    return SeriesResponse(
        window=to_window_view(window),
        bucket=bucket,
        is_zero_filled=is_filled,
        signups=signup_points,
        delivered=delivered_points,
        revenue=[_to_money_point(item) for item in _fold_revenue(revenue, bucket)],
        spend=[_to_spend_point(item) for item in _fold_spend(spend, bucket)],
        unattributed_spend=[
            SpendPointView(
                bucket=item.bucket,
                started_at=item.started_at,
                vendor=None,
                cost=to_usd_cost(
                    amount_usd=item.cost_usd,
                    costed_calls=item.costed_calls,
                    calls=item.calls,
                    cost_source=None if item.cost_usd is None else "derived",
                ),
            )
            for item in _fold_unattributed_series(unattributed, bucket)
        ],
        cost_split=[
            CostSplitView(
                vendor=item.vendor,
                operation=item.operation,
                cost=to_usd_cost(
                    amount_usd=item.cost_usd,
                    costed_calls=item.costed_calls,
                    calls=item.calls,
                    cost_source=cost_source_of(item.cost_source, is_mixed=item.is_cost_mixed),
                ),
            )
            for item in cost_split
        ],
        order_funnel=_to_funnel_view(funnel),
    )


def _to_spend_point(item: VendorSpendPerBucket) -> SpendPointView:
    return SpendPointView(
        bucket=item.bucket,
        started_at=item.started_at,
        vendor=item.vendor,
        cost=to_usd_cost(
            amount_usd=item.cost_usd,
            costed_calls=item.costed_calls,
            calls=item.calls,
            cost_source=None if item.cost_usd is None else "derived",
        ),
    )


def fold_points(
    points: list[tuple[str, datetime, int]], bucket: SeriesBucket
) -> list[CountPointView]:
    """Fold a daily count series into weeks or months, or pass it through unchanged.

    Summing already-grouped rows, so the work is bounded by the bucket count and never by
    rows — the same licence ``failure_breakdown`` takes to turn counts into shares. The fold
    also guarantees the coarser series sums exactly to the finer one it came from, which two
    independent SQL expressions could not.
    """
    if bucket in (SeriesBucket.HOUR, SeriesBucket.DAY):
        return [
            CountPointView(bucket=key, started_at=started, count=count)
            for key, started, count in points
        ]
    totals: dict[tuple[str, datetime], int] = defaultdict(int)
    for _, started, count in points:
        totals[_coarse_key(started, bucket)] += count
    return [
        CountPointView(bucket=key, started_at=started, count=count)
        for (key, started), count in sorted(totals.items(), key=lambda item: item[0][1])
    ]


def _coarse_key(started: datetime, bucket: SeriesBucket) -> tuple[str, datetime]:
    """The ISO week or the calendar month a daily bucket belongs to.

    ``date.isocalendar()`` rather than either dialect's week numbering, so the fold has one
    definition on every deployment — which is the whole reason the coarse grains are folded
    here instead of grouped in SQL.
    """
    day = started.date()
    if bucket is SeriesBucket.WEEK:
        year, week, _ = day.isocalendar()
        monday = day - timedelta(days=day.weekday())
        return f"{year:04d}-W{week:02d}", datetime.combine(monday, datetime.min.time(), tzinfo=UTC)
    first = day.replace(day=1)
    return f"{first.year:04d}-{first.month:02d}", datetime.combine(
        first, datetime.min.time(), tzinfo=UTC
    )


def _fold_revenue(buckets: tuple[RevenueBucket, ...], bucket: SeriesBucket) -> list[RevenueBucket]:
    """Fold revenue into coarser buckets, keeping the full key. Never zero-filled."""
    if bucket in (SeriesBucket.HOUR, SeriesBucket.DAY):
        return list(buckets)
    merged: dict[tuple[str, datetime, RevenueSource, str, str, str], list[int]] = {}
    for item in buckets:
        key_text, started = _coarse_key(item.started_at, bucket)
        key = (key_text, started, item.source, item.product, item.currency, item.provider)
        totals = merged.setdefault(key, [0, 0])
        totals[0] += item.sales
        totals[1] += item.amount_minor
    return [
        RevenueBucket(
            bucket=key[0],
            started_at=key[1],
            source=key[2],
            product=key[3],
            currency=key[4],
            provider=key[5],
            sales=totals[0],
            amount_minor=totals[1],
        )
        for key, totals in sorted(merged.items(), key=lambda item: (item[0][1], item[0][2:]))
    ]


def _fold_spend(
    buckets: tuple[VendorSpendPerBucket, ...], bucket: SeriesBucket
) -> list[VendorSpendPerBucket]:
    """Fold spend into coarser buckets. **Money stays ``None`` when every member was.**"""
    if bucket in (SeriesBucket.HOUR, SeriesBucket.DAY):
        return list(buckets)
    merged: dict[tuple[str, datetime, Vendor], list[float | int | None]] = {}
    for item in buckets:
        key_text, started = _coarse_key(item.started_at, bucket)
        key = (key_text, started, item.vendor)
        entry = merged.setdefault(key, [None, 0, 0])
        entry[0] = _add_optional(entry[0], item.cost_usd)
        entry[1] = int(entry[1] or 0) + item.costed_calls
        entry[2] = int(entry[2] or 0) + item.calls
    return [
        VendorSpendPerBucket(
            bucket=key[0],
            started_at=key[1],
            vendor=key[2],
            cost_usd=None if entry[0] is None else float(entry[0]),
            costed_calls=int(entry[1] or 0),
            calls=int(entry[2] or 0),
        )
        for key, entry in sorted(merged.items(), key=lambda item: (item[0][1], item[0][2]))
    ]


def _fold_unattributed_series(
    buckets: tuple[UnattributedSpendPerBucket, ...], bucket: SeriesBucket
) -> list[UnattributedSpendPerBucket]:
    """Fold unattributed spend. Same money rule: all-null stays null, never ``0.0``."""
    if bucket in (SeriesBucket.HOUR, SeriesBucket.DAY):
        return list(buckets)
    merged: dict[tuple[str, datetime], list[float | int | None]] = {}
    for item in buckets:
        key = _coarse_key(item.started_at, bucket)
        entry = merged.setdefault(key, [None, 0, 0])
        entry[0] = _add_optional(entry[0], item.cost_usd)
        entry[1] = int(entry[1] or 0) + item.costed_calls
        entry[2] = int(entry[2] or 0) + item.calls
    return [
        UnattributedSpendPerBucket(
            bucket=key[0],
            started_at=key[1],
            cost_usd=None if entry[0] is None else float(entry[0]),
            costed_calls=int(entry[1] or 0),
            calls=int(entry[2] or 0),
        )
        for key, entry in sorted(merged.items(), key=lambda item: item[0][1])
    ]


def _add_optional(left: float | int | None, right: float | None) -> float | None:
    """``None + None`` is ``None``; anything plus a measured figure is measured.

    The whole money-folding rule in one function. Treating ``None`` as ``0`` here would undo
    at the last possible moment everything the nullable columns, the absent ``COALESCE`` and
    the ``_as_float`` helpers bought.
    """
    if right is None:
        return None if left is None else float(left)
    return float(right) if left is None else float(left) + right


def _zero_fill(
    points: list[CountPointView], bucket: SeriesBucket, window: TimeWindow
) -> list[CountPointView]:
    """Fill absent buckets with zero, but only across the range the caller actually asked for.

    Only reached when ``window.start`` is not ``None``. The fill is clipped to the window on
    both sides, so a series never grows a bucket outside the range the response echoes, and
    it fills COUNTS only — a bucket with no orders is honestly zero orders. Money is never
    filled anywhere in this module.
    """
    if window.start is None or not points:
        return points
    present = {point.bucket: point for point in points}
    filled: list[CountPointView] = []
    for key, started in _bucket_axis(bucket, window):
        filled.append(present.get(key, CountPointView(bucket=key, started_at=started, count=0)))
    return filled if filled else points


def _bucket_axis(bucket: SeriesBucket, window: TimeWindow) -> list[tuple[str, datetime]]:
    """Every bucket key between the window's bounds, oldest first.

    Half-open on the upper end, matching :class:`~hbd.db.admin.sql.TimeWindow`, so the
    instant on a boundary belongs to exactly one bucket and two adjacent windows tile
    without a duplicated bar.
    """
    if window.start is None:
        return []
    axis: list[tuple[str, datetime]] = []
    cursor = _floor(window.start, bucket)
    while cursor < window.end:
        axis.append((_bucket_key(cursor, bucket), cursor))
        cursor = _advance(cursor, bucket)
    return axis


def _floor(moment: datetime, bucket: SeriesBucket) -> datetime:
    if bucket is SeriesBucket.HOUR:
        return moment.replace(minute=0, second=0, microsecond=0)
    day = moment.replace(hour=0, minute=0, second=0, microsecond=0)
    if bucket is SeriesBucket.DAY:
        return day
    if bucket is SeriesBucket.WEEK:
        return day - timedelta(days=day.weekday())
    return day.replace(day=1)


def _advance(moment: datetime, bucket: SeriesBucket) -> datetime:
    if bucket is SeriesBucket.HOUR:
        return moment + timedelta(hours=1)
    if bucket is SeriesBucket.DAY:
        return moment + timedelta(days=1)
    if bucket is SeriesBucket.WEEK:
        return moment + timedelta(days=7)
    return (moment.replace(day=28) + timedelta(days=4)).replace(day=1)


def _bucket_key(moment: datetime, bucket: SeriesBucket) -> str:
    """The key the grouping or the fold would have produced for this instant."""
    if bucket is SeriesBucket.HOUR:
        return moment.strftime("%Y-%m-%dT%H")
    if bucket is SeriesBucket.DAY:
        return moment.strftime("%Y-%m-%d")
    return _coarse_key(moment, bucket)[0]


def to_plan_liability_response(
    *,
    liability: PlanLiability,
    utilisation: tuple[PlanUtilisationBucket, ...],
    is_plan_revenue: bool,
) -> PlanLiabilityResponse:
    """Assemble the plan-liability state. No window: liability is a state, not a flow.

    ``liveAmounts`` is per-currency and never a scalar, for the reason every money figure on
    this surface is: there is no honest total across two currencies, and today's
    one-element list is not a licence to collapse it.
    """
    return PlanLiabilityResponse(
        as_of=liability.as_of,
        live_plans=liability.live_plans,
        live_holders=liability.live_holders,
        live_anonymised_plans=liability.live_anonymised_plans,
        live_plans_with_songs_left=liability.live_plans_with_songs_left,
        unconsumed_songs=liability.unconsumed_songs,
        live_amounts=[_to_currency_amount(item) for item in liability.live_amounts],
        ended_plans=liability.ended_plans,
        breakage_songs=liability.breakage_songs,
        expiring_within_days=liability.expiring_within_days,
        expiring_plans=liability.expiring_plans,
        expiring_songs_left=liability.expiring_songs_left,
        utilisation=[
            PlanUtilisationBucketView(from_=item.lower, to=item.upper, count=item.count)
            for item in utilisation
        ],
        is_plan_revenue=is_plan_revenue,
    )


def _to_currency_amount(amount: CurrencyAmount) -> CurrencyAmountView:
    """The single conversion point for :class:`~hbd.db.admin.views.CurrencyAmount`."""
    return CurrencyAmountView(currency=amount.currency, amount_minor=amount.amount_minor)
