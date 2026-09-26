"""``/metrics/vendor-*`` — what each vendor was asked to do, and what it cost.

The rule :mod:`bayram.db.admin.metrics` states holds here without exception: **every number is
computed by the database.** Not one function below fetches rows and folds them in Python.
``vendor_usage`` is append-only and written on every vendor call in the system, so it grows
faster than ``orders`` does and a rollup written as a Python loop would read a year of spend
across the network to produce a dozen integers. The only arithmetic done here is over
already-grouped results — turning a vendor's failure counts into shares, and collapsing a
group's ``MIN``/``MAX`` provenance into "these did not agree" — both bounded by the number
of distinct groups rather than by rows.

**Nothing is coalesced to zero, and that is the whole design.** ``SUM()`` over a nullable
column returns ``NULL`` when every row in the group is ``NULL``, and ``vendor_usage``
declares no default on any quantity column, so a group in which nobody measured tokens comes
back with ``total_tokens`` of ``None`` for free. A ``COALESCE(..., 0)`` anywhere in this
module would turn "nobody counted" into "the vendor charged us for nothing" — the exact
defect ``generation_attempts.cost_usd DEFAULT 0.0`` created and this table exists not to
repeat. Counts are the one exception and they are counts on purpose:
:func:`~bayram.db.admin.sql.count_where` renders ``count(CASE WHEN … END)``, which is ``0`` for
an empty group and never ``NULL``, because "no call failed" IS a measurement.

**Cost is summed over the priced rows alone, and ``costed_calls`` says how many those were.**
The two travel together everywhere, on the wire and in the view models, because a total that
covers nine of nine hundred calls is unreadable without the second number and dangerous with
it missing: it is the figure an operator budgets against.

**The rollup is ordered by ``calls`` and never by ``cost_usd``.** Ordering by a nullable
column puts NULLs first on Postgres and last on SQLite, so a query ordered by cost would
return one row order in production and another in the suite that is supposed to be checking
it. Where a nullable column *is* part of the ordering — ``model_id``, ``error_code`` — an
explicit ``IS NULL`` sort key goes before it, which both dialects evaluate to ``0``/``1``
and so puts the unnamed group last on either.

**The two capability probes deliberately ignore the window**, mirroring
:func:`~bayram.db.admin.attempts.is_cost_instrumented`. "No rows in the range you chose" and
"no worker in this deployment has ever written one" are two different screens with two
different remedies (§11.4), and a windowed count cannot tell them apart.

**Nothing here is personal data.** Every column read below is a closed enum, an integer, a
machine id or a bounded error code — no name, no note, no transcript, no telegram id — which
is why the whole surface sits on DASHBOARD_READ rather than on a reveal.

**EVERY SELECT against ``VendorUsageRow`` in this repository is built through**
:func:`_narrow`, **and** :func:`_narrow` **excludes fake-provider rows by default.** That is
the module's load-bearing invariant and it is structural rather than a thing each caller
remembers.

Before it existed, a ``BAYRAM_USE_FAKE_PROVIDERS`` demo run inflated ``costUsd``, ``calls``,
``successRate``, ``avgLatencyMs`` and the error breakdown on three shipped routes, and a
quota probe moved a failure rate that OBS-6 pages SEV-2 on. ``Vendor.FAKE`` and
``vendor_usage.is_fake`` exist so a demo is RECORDED AND VISIBLY EXCLUDED; recorded was
done, excluded was never built.

The default FLIPPED rather than a parameter being added at every call site, because a
parameter defaulting to "include" is precisely a thing each caller remembers. This function
already existed for that reason — its own docstring calls it "the filter set every read here
shares… spelled once so the four aggregates cannot come to disagree about which rows they
describe" — and contamination is that same class of disagreement, so it belongs in the same
place. The consequence is deliberate and is stated on the three routes it changes: they
return different numbers than they did, and ``?includeFake=true`` is how a demo run stays
inspectable rather than going from silently inflating to silently invisible.

The second parameter, ``exclude_operations``, exists because the balance poller writes
roughly seventy-two ``operation=HEALTH`` rows a day with no ``order_id`` and no ``task``.
Those are real calls to a real vendor and belong in a reachability breakdown; they are not
SPEND, and they are not unattributed work. :data:`SPENDABLE_EXCLUSIONS` names them once.

**:func:`cost_per_delivered_song` lives here rather than in a finance module, and that is
what makes the invariant checkable.** ``VendorUsageRow`` reaches only six modules in
``src/`` — the model, the registry, its writer, the retention sweep, the balance poller's
per-song rate measurement, and this file — and only ONE of those six reports on the table.
So if the AST guard in ``tests/test_db/test_vendor_usage_isolation.py`` holds, no reporting
SELECT over ``vendor_usage`` can exist anywhere that skipped :func:`_narrow`. A query built
in ``db/admin/finance.py`` would be one :func:`_narrow` cannot reach and one nobody would
notice; the guard fails on the import rather than waiting for somebody to spot the missing
filter. (``bayram.db.vendor_balances`` is the one non-reporting reader and it spells
``is_fake.is_(False)`` itself, which is precisely why it is on the list by name and not by
accident.)
"""

from __future__ import annotations

from datetime import date
from typing import Any, Final

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql import Select

from bayram.contracts import CostSource, Vendor, VendorOperation
from bayram.db.admin.sql import (
    SeriesGrain,
    TimeWindow,
    UtcDay,
    apply_in,
    apply_window,
    bucket_expression,
    bucket_started_at,
    count_where,
    nearest_rank_offset,
)
from bayram.db.admin.views import (
    CostPerDeliveredSong,
    CostProvenance,
    FakeCallGuard,
    OperationLatency,
    UnattributedSpendPerBucket,
    VendorCostPerSong,
    VendorErrorCount,
    VendorSpendPerBucket,
    VendorSpendSplit,
    VendorUnitsPerSong,
    VendorUsagePerDay,
    VendorUsageRollup,
    VendorUsageTotals,
)
from bayram.db.models.order import OrderRow
from bayram.db.models.vendor_usage import VendorUsageRow

__all__ = [
    "SPENDABLE_EXCLUSIONS",
    "vendor_usage_rollup",
    "vendor_usage_totals",
    "vendor_usage_per_day",
    "vendor_error_breakdown",
    "vendor_spend_per_bucket",
    "vendor_spend_split",
    "cost_per_delivered_song",
    "cost_per_delivered_song_by_vendor",
    "units_per_delivered_song_by_vendor",
    "cost_provenance",
    "unattributed_spend",
    "vendor_operation_latency",
    "fake_call_count",
    "has_recorded_vendor_usage",
    "has_priced_vendor_usage",
]

#: Operations that are real vendor traffic but are not SPEND on the product. Today just the
#: balance poller's hourly quota probe: it calls a real endpoint, it belongs in a
#: reachability breakdown, and folding it into cost-per-song or unattributed spend would
#: report a quota check as money spent on nobody's song.
SPENDABLE_EXCLUSIONS: Final[tuple[VendorOperation, ...]] = (VendorOperation.HEALTH,)

#: The two percentiles, named so a caller cannot transpose them. Spelled here rather than
#: imported from ``bayram.db.admin.metrics``, which imports this module.
_P50: Final[float] = 0.5
_P95: Final[float] = 0.95


async def vendor_usage_rollup(
    session: AsyncSession,
    *,
    window: TimeWindow | None = None,
    vendors: tuple[Vendor, ...] = (),
    include_fake: bool = False,
    exclude_operations: tuple[VendorOperation, ...] = (),
) -> tuple[VendorUsageRollup, ...]:
    """One row per ``(vendor, operation, model_id)``, busiest first.

    The grouping is the invoice's own shape rather than the vendor's alone: ElevenLabs bills
    music by the rendered minute, speech by the character and transcription by the minute of
    audio, so one "elevenlabs" line would mix three units and reconcile against nothing. The
    model id joins the key because a rate card is quoted per model and a deployment that
    switched models mid-window would otherwise average two prices into one.

    ``cost_source`` is read as a ``MIN``/``MAX`` pair over the group. Equal means every
    priced call in it was arrived at the same way; unequal means the group mixes, say, an
    OpenRouter-reported figure with token-rate arithmetic, and the caller renders "mixed"
    rather than picking one of the two and implying the group agrees.
    """
    grouping = (VendorUsageRow.vendor, VendorUsageRow.operation, VendorUsageRow.model_id)
    calls = sa.func.count().label("calls")
    statement: Select[Any] = sa.select(
        *grouping,
        calls,
        count_where(VendorUsageRow.is_success.is_(True)).label("successes"),
        count_where(VendorUsageRow.is_success.is_(False)).label("failures"),
        sa.func.sum(VendorUsageRow.prompt_tokens).label("prompt_tokens"),
        sa.func.sum(VendorUsageRow.completion_tokens).label("completion_tokens"),
        sa.func.sum(VendorUsageRow.total_tokens).label("total_tokens"),
        sa.func.sum(VendorUsageRow.billed_characters).label("billed_characters"),
        sa.func.sum(VendorUsageRow.audio_ms).label("audio_ms"),
        sa.func.sum(VendorUsageRow.cost_usd).label("cost_usd"),
        count_where(VendorUsageRow.cost_usd.is_not(None)).label("costed_calls"),
        sa.func.min(VendorUsageRow.cost_source).label("min_cost_source"),
        sa.func.max(VendorUsageRow.cost_source).label("max_cost_source"),
        sa.func.avg(VendorUsageRow.latency_ms).label("avg_latency_ms"),
        sa.func.max(VendorUsageRow.latency_ms).label("max_latency_ms"),
    )
    statement = _narrow(
        statement,
        window=window,
        vendors=vendors,
        include_fake=include_fake,
        exclude_operations=exclude_operations,
    )
    rows = (
        await session.execute(
            statement.group_by(*grouping).order_by(
                calls.desc(),
                VendorUsageRow.vendor,
                VendorUsageRow.operation,
                # Unnamed models last on BOTH dialects — see the module docstring.
                VendorUsageRow.model_id.is_(None),
                VendorUsageRow.model_id,
            )
        )
    ).all()
    return tuple(
        VendorUsageRollup(
            vendor=row.vendor,
            operation=row.operation,
            model_id=row.model_id,
            calls=int(row.calls),
            successes=int(row.successes),
            failures=int(row.failures),
            prompt_tokens=_as_int(row.prompt_tokens),
            completion_tokens=_as_int(row.completion_tokens),
            total_tokens=_as_int(row.total_tokens),
            billed_characters=_as_int(row.billed_characters),
            audio_ms=_as_int(row.audio_ms),
            cost_usd=_as_float(row.cost_usd),
            cost_source=_as_cost_source(row.min_cost_source),
            is_cost_mixed=_is_mixed(row.min_cost_source, row.max_cost_source),
            costed_calls=int(row.costed_calls),
            avg_latency_ms=_as_rounded_int(row.avg_latency_ms),
            max_latency_ms=_as_int(row.max_latency_ms),
        )
        for row in rows
    )


async def vendor_usage_totals(
    session: AsyncSession,
    *,
    window: TimeWindow | None = None,
    vendors: tuple[Vendor, ...] = (),
    include_fake: bool = False,
    exclude_operations: tuple[VendorOperation, ...] = (),
) -> VendorUsageTotals:
    """The whole window in one row: volume, spend, and the units that were measured.

    Its own query rather than a fold over :func:`vendor_usage_rollup`'s output, and the
    reason is arithmetic rather than efficiency: summing a tuple of groups in Python means
    deciding what ``None + None`` is, and every answer to that question except "leave it
    ``None``" puts a fabricated zero on the tile an operator reads first. The database
    already answers it correctly, so the question is never asked here.

    ``cost_source`` and ``is_cost_mixed`` ride along because this was the ONE cost figure on
    the screen that could not say how it was arrived at: ``VendorUsageRollup`` has carried
    provenance from the start and the hero tile beside it did not, so a total that is mostly
    arithmetic against a placeholder rate looked exactly like one the vendor reported. Two
    extra aggregates in a query that is already grouping nothing.
    """
    statement: Select[Any] = sa.select(
        sa.func.count().label("calls"),
        count_where(VendorUsageRow.is_success.is_(True)).label("successes"),
        count_where(VendorUsageRow.is_success.is_(False)).label("failures"),
        sa.func.sum(VendorUsageRow.cost_usd).label("cost_usd"),
        count_where(VendorUsageRow.cost_usd.is_not(None)).label("costed_calls"),
        sa.func.min(VendorUsageRow.cost_source).label("min_cost_source"),
        sa.func.max(VendorUsageRow.cost_source).label("max_cost_source"),
        sa.func.sum(VendorUsageRow.total_tokens).label("total_tokens"),
        sa.func.sum(VendorUsageRow.billed_characters).label("billed_characters"),
        sa.func.sum(VendorUsageRow.audio_ms).label("audio_ms"),
        sa.func.avg(VendorUsageRow.latency_ms).label("avg_latency_ms"),
    )
    row = (
        await session.execute(
            _narrow(
                statement,
                window=window,
                vendors=vendors,
                include_fake=include_fake,
                exclude_operations=exclude_operations,
            )
        )
    ).one()
    return VendorUsageTotals(
        calls=int(row.calls),
        successes=int(row.successes),
        failures=int(row.failures),
        cost_usd=_as_float(row.cost_usd),
        costed_calls=int(row.costed_calls),
        cost_source=_as_cost_source(row.min_cost_source),
        is_cost_mixed=_is_mixed(row.min_cost_source, row.max_cost_source),
        total_tokens=_as_int(row.total_tokens),
        billed_characters=_as_int(row.billed_characters),
        audio_ms=_as_int(row.audio_ms),
        avg_latency_ms=_as_rounded_int(row.avg_latency_ms),
    )


async def vendor_usage_per_day(
    session: AsyncSession,
    *,
    window: TimeWindow | None = None,
    vendors: tuple[Vendor, ...] = (),
    include_fake: bool = False,
    exclude_operations: tuple[VendorOperation, ...] = (),
) -> tuple[VendorUsagePerDay, ...]:
    """Calls and spend per UTC day per vendor, oldest first.

    A ``(day, vendor)`` pair with no calls is absent from the series, never present at zero.
    This layer does not know what range the caller wants charted — ``from``/``to`` are both
    optional — so filling the gaps here would claim "$0.00 spent" for days before the
    deployment existed. The day is :class:`~bayram.db.admin.sql.UtcDay` and never
    ``sa.func.date``, which resolves through the *session* time zone on Postgres and would
    file every call made after 19:00 UTC on a ``Asia/Tashkent`` server under the next day.
    """
    day = UtcDay(VendorUsageRow.created_at)
    statement: Select[Any] = sa.select(
        day.label("day"),
        VendorUsageRow.vendor,
        sa.func.count().label("calls"),
        sa.func.sum(VendorUsageRow.cost_usd).label("cost_usd"),
        count_where(VendorUsageRow.cost_usd.is_not(None)).label("costed_calls"),
    )
    statement = _narrow(
        statement,
        window=window,
        vendors=vendors,
        include_fake=include_fake,
        exclude_operations=exclude_operations,
    )
    rows = (
        await session.execute(
            statement.group_by(day, VendorUsageRow.vendor).order_by(day, VendorUsageRow.vendor)
        )
    ).all()
    return tuple(
        VendorUsagePerDay(
            day=date.fromisoformat(str(row.day)),
            vendor=row.vendor,
            calls=int(row.calls),
            cost_usd=_as_float(row.cost_usd),
            costed_calls=int(row.costed_calls),
        )
        for row in rows
    )


async def vendor_error_breakdown(
    session: AsyncSession,
    *,
    window: TimeWindow | None = None,
    vendors: tuple[Vendor, ...] = (),
    include_fake: bool = False,
    exclude_operations: tuple[VendorOperation, ...] = (),
) -> tuple[VendorErrorCount, ...]:
    """Failed calls grouped by ``(vendor, error_code)``, largest first.

    ``share`` is that code's share of **that vendor's** failures, not of every vendor's:
    the question this table answers is "what is going wrong with ElevenLabs", and a
    denominator spanning four vendors answers a different one. The division is the one piece
    of Python arithmetic this module permits, and it is over already-grouped rows — bounded
    by the number of distinct codes a vendor has produced, never by rows.

    ``is_retryable`` is deliberately absent, exactly as on
    :func:`~bayram.db.admin.metrics.failure_breakdown`: retryability belongs to the
    ``BayramError`` subclass that was raised and not to the string that got persisted, so
    deriving it here would print a guess as a fact.
    """
    grouping = (VendorUsageRow.vendor, VendorUsageRow.error_code)
    # Labelled ``failures`` and not ``count``: ``Row.count`` is a tuple method, so a column
    # named that reads back as a bound method under a type checker and by luck at runtime.
    total = sa.func.count().label("failures")
    statement: Select[Any] = sa.select(*grouping, total).where(VendorUsageRow.is_success.is_(False))
    statement = _narrow(
        statement,
        window=window,
        vendors=vendors,
        include_fake=include_fake,
        exclude_operations=exclude_operations,
    )
    rows = (
        await session.execute(
            statement.group_by(*grouping).order_by(
                total.desc(),
                VendorUsageRow.vendor,
                # Uncoded failures last on BOTH dialects — see the module docstring.
                VendorUsageRow.error_code.is_(None),
                VendorUsageRow.error_code,
            )
        )
    ).all()
    failures_by_vendor: dict[Vendor, int] = {}
    for row in rows:
        failures_by_vendor[row.vendor] = failures_by_vendor.get(row.vendor, 0) + int(row.failures)
    return tuple(
        VendorErrorCount(
            vendor=row.vendor,
            error_code=row.error_code,
            count=int(row.failures),
            share=int(row.failures) / failures_by_vendor[row.vendor],
        )
        for row in rows
    )


async def vendor_spend_per_bucket(
    session: AsyncSession,
    *,
    window: TimeWindow | None = None,
    grain: SeriesGrain = SeriesGrain.DAY,
    vendors: tuple[Vendor, ...] = (),
) -> tuple[VendorSpendPerBucket, ...]:
    """Calls and priced spend per ``(bucket, vendor)``, oldest first.

    :func:`vendor_usage_per_day`'s grain-parameterised sibling rather than a replacement for
    it: that function is what ``/api/metrics/vendor-usage-by-day`` publishes by contract and
    returns a ``date``, while this one returns the bucket key at whichever grain the chart
    asked for. Folding the two would change a shipped response's ``day`` field into a string.

    A ``(bucket, vendor)`` pair with no calls is ABSENT, never present at zero — a zero bar
    here is a claim about money we did not spend on a day this deployment may not have
    existed on.

    INDEX: ``ix_vendor_usage_vendor_created_at``.
    """
    bucket = bucket_expression(grain, VendorUsageRow.created_at)
    statement: Select[Any] = sa.select(
        bucket.label("bucket"),
        VendorUsageRow.vendor,
        sa.func.count().label("calls"),
        sa.func.sum(VendorUsageRow.cost_usd).label("cost_usd"),
        count_where(VendorUsageRow.cost_usd.is_not(None)).label("costed_calls"),
    )
    statement = _narrow(statement, window=window, vendors=vendors)
    rows = (
        await session.execute(
            statement.group_by(bucket, VendorUsageRow.vendor).order_by(
                bucket, VendorUsageRow.vendor
            )
        )
    ).all()
    return tuple(
        VendorSpendPerBucket(
            bucket=str(row.bucket),
            started_at=bucket_started_at(grain, str(row.bucket)),
            vendor=row.vendor,
            calls=int(row.calls),
            cost_usd=_as_float(row.cost_usd),
            costed_calls=int(row.costed_calls),
        )
        for row in rows
    )


async def vendor_spend_split(
    session: AsyncSession, *, window: TimeWindow | None = None
) -> tuple[VendorSpendSplit, ...]:
    """Where the cost goes: one row per ``(vendor, operation)``, busiest first.

    Coarser than :func:`vendor_usage_rollup` on purpose — no ``model_id`` — because this
    feeds a slice chart rather than an invoice reconciliation, and a chart with one slice per
    model id is unreadable the first time a deployment switches models mid-window.

    ``HEALTH`` is excluded through :data:`SPENDABLE_EXCLUSIONS`: the balance poller's hourly
    quota probe is a real call and belongs in :func:`vendor_error_breakdown`, but reporting
    it as a slice of what a song costs would put "checking our own balance" on the pie.

    Ordered by ``calls`` and never by ``cost_usd`` — the module docstring's NULLS rule.

    INDEX: ``ix_vendor_usage_vendor_created_at``; the window is a filter rather than a seek
    because the index leads with ``vendor``.
    """
    grouping = (VendorUsageRow.vendor, VendorUsageRow.operation)
    calls = sa.func.count().label("calls")
    statement: Select[Any] = sa.select(
        *grouping,
        calls,
        sa.func.sum(VendorUsageRow.cost_usd).label("cost_usd"),
        count_where(VendorUsageRow.cost_usd.is_not(None)).label("costed_calls"),
        sa.func.min(VendorUsageRow.cost_source).label("min_cost_source"),
        sa.func.max(VendorUsageRow.cost_source).label("max_cost_source"),
    )
    statement = _narrow(
        statement, window=window, vendors=(), exclude_operations=SPENDABLE_EXCLUSIONS
    )
    rows = (
        await session.execute(statement.group_by(*grouping).order_by(calls.desc(), *grouping))
    ).all()
    return tuple(
        VendorSpendSplit(
            vendor=row.vendor,
            operation=row.operation,
            calls=int(row.calls),
            cost_usd=_as_float(row.cost_usd),
            costed_calls=int(row.costed_calls),
            cost_source=_as_cost_source(row.min_cost_source),
            is_cost_mixed=_is_mixed(row.min_cost_source, row.max_cost_source),
        )
        for row in rows
    )


async def cost_per_delivered_song(
    session: AsyncSession, *, window: TimeWindow | None = None, delivered_orders: int
) -> CostPerDeliveredSong:
    """The vendor spend attributable to songs DELIVERED in the window, and its coverage.

    **The cohort is ``delivered_at`` and not ``created_at``, and that overrules the research
    doc on purpose.** ``docs/research/DASHBOARD_METRICS_RESEARCH.md`` item 4 specifies
    ``state='delivered' AND created_at IN window``, on the stated grounds that
    ``delivered_at`` had no index and would not reconcile with any other tile. Both premises
    are void: the index exists, and after the throughput correction every tile this figure
    must reconcile with — "Songs delivered",
    :func:`~bayram.db.admin.metrics.delivered_per_bucket`,
    :func:`~bayram.db.admin.metrics.delivered_latency` — is windowed on ``delivered_at``.
    Reconciliation across the card row is the stronger constraint. Restoring the research
    doc's version would leave the ratio's numerator and denominator counted over two
    different populations, which is the one defect a unit-economics number cannot survive.

    The skew that choice accepts, stated rather than discovered: a song delivered today may
    have been rendered by calls billed yesterday, so this attributes cost to the DELIVERY
    instant. That is the only attribution under which both halves of the quotient share one
    cohort.

    **No ratio is returned.** ``cost_usd`` can be ``None`` while ``delivered_orders`` is
    positive — calls recorded, no rate configured — and a quotient formed here would have to
    invent something for that case. The division happens in the wire layer, in a type that
    cannot be built without both operands.

    ``attributed_orders`` is not ``delivered_orders``: it counts delivered orders that had
    any vendor call attributed to them at all, and the gap between the two is what says the
    cost covers only part of the cohort.

    ``delivered_orders`` is a PARAMETER and not something this query counts, which is the
    one place this module takes a number it did not measure. The denominator has to be the
    same integer the "Songs delivered" card publishes — :func:`delivered_counts`' current
    value over the same window — and counting it again through this join would produce a
    number that silently differs the moment an order delivers with no vendor call attributed
    to it. One denominator, computed once, handed to both.

    The window is applied to ``OrderRow.delivered_at`` and :func:`_narrow` is then called
    with ``window=None``: a second range predicate on ``vendor_usage.created_at`` would
    exclude exactly the yesterday-billed calls this cohort is defined to include.

    INDEX: ``ix_orders_delivered_at`` for the outer range scan, then a nested loop into
    ``ix_vendor_usage_order_id``.
    """
    statement: Select[Any] = sa.select(
        sa.func.sum(VendorUsageRow.cost_usd).label("cost_usd"),
        count_where(VendorUsageRow.cost_usd.is_not(None)).label("costed_calls"),
        sa.func.count().label("calls"),
        sa.func.count(sa.distinct(VendorUsageRow.order_id)).label("attributed_orders"),
        sa.func.min(VendorUsageRow.cost_source).label("min_cost_source"),
        sa.func.max(VendorUsageRow.cost_source).label("max_cost_source"),
    ).join(OrderRow, OrderRow.id == VendorUsageRow.order_id)
    statement = statement.where(OrderRow.delivered_at.is_not(None))
    statement = apply_window(statement, OrderRow.delivered_at, window)
    statement = _narrow(statement, window=None, vendors=(), exclude_operations=SPENDABLE_EXCLUSIONS)
    row = (await session.execute(statement)).one()
    return CostPerDeliveredSong(
        cost_usd=_as_float(row.cost_usd),
        costed_calls=int(row.costed_calls),
        calls=int(row.calls),
        attributed_orders=int(row.attributed_orders),
        delivered_orders=delivered_orders,
        cost_source=_as_cost_source(row.min_cost_source),
        is_cost_mixed=_is_mixed(row.min_cost_source, row.max_cost_source),
    )


async def cost_per_delivered_song_by_vendor(
    session: AsyncSession, *, window: TimeWindow | None = None, delivered_orders: int
) -> tuple[VendorCostPerSong, ...]:
    """:func:`cost_per_delivered_song`, split by who charged us. Same cohort, same filters.

    The aggregate answers "what does a song cost"; this answers "and to whom", which is the
    only form of the number an operator can act on — the remedy for an expensive song is a
    different model or a different vendor, and one figure names neither. It is a SECOND
    query rather than a widening of the first because the ungrouped shape is what the
    cost-per-song card publishes by contract, and a caller that needs only the hero figure
    should not pay for a grouped aggregate to get it.

    **Every predicate below is :func:`cost_per_delivered_song`'s, copied rather than
    approximated.** The two are read side by side, and a breakdown counted over a different
    population than the total beside it is a screen arguing with itself. So: the cohort is
    ``delivered_at`` in the window and not ``created_at`` — the aggregate argues that at
    length and the argument is not repeated here; :data:`SPENDABLE_EXCLUSIONS` drops the
    balance poller's quota probes; :func:`_narrow` drops fake-provider rows; and
    :func:`_narrow` is called with ``window=None`` because a second range predicate on
    ``vendor_usage.created_at`` would exclude exactly the yesterday-billed calls this cohort
    is defined to include.

    ``delivered_orders`` is a PARAMETER, the same integer on every row returned, and for the
    same reason it is a parameter one function up: the denominator has to be the number the
    "Songs delivered" card publishes, counted once and handed to everything that divides by
    it. Being the same on every row is also what makes these figures comparable — with each
    other, and with the ungrouped one.

    **Why these rows do not necessarily add up to the ungrouped figure.** Three separate
    reasons, and only the second is arithmetic:

    * ``attributed_orders`` NEVER adds. It is a ``COUNT(DISTINCT order_id)`` taken inside
      each group, and one delivered song is normally rendered by several vendors — an LLM
      for the lyrics, a music vendor for the track. That order is counted once in every
      group it appears in, so the column sums past ``delivered_orders`` and may exceed it
      several times over. The aggregate's single ``attributed_orders`` counts ORDERS; this
      column counts orders per vendor, which is a different measurement wearing the name.
    * ``cost_usd`` does partition exactly — ``vendor`` is ``NOT NULL``, so every row this
      join sees lands in exactly one group — but only while every group is RENDERED. A table
      sorted by spend and cut to the top few, or a caller narrowing to one vendor, shows a
      subset whose total is short by precisely the rows it dropped, and nothing in the row
      shape says which.
    * ``None`` is not an addend. A vendor whose every call in the window was unpriced comes
      back with ``cost_usd`` of ``None`` and ``cost_per_song_usd`` of ``None``. ``SUM``
      already skipped those rows in the aggregate and a reader adding the rendered column
      skips them again — and then reads the result as complete. That gap is real spend
      nobody could price; :func:`cost_provenance` is the read that measures it.

    A window in which nothing was delivered returns an EMPTY tuple. Not a row per vendor at
    zero: "we shipped nothing" is not "our vendors were free".

    Ordered by coverage and never by ``cost_usd`` — the module docstring's NULLS rule, and
    ``cost_usd`` is exactly the nullable column that rule is about.

    INDEX: ``ix_orders_delivered_at`` for the outer range scan, then a nested loop into
    ``ix_vendor_usage_order_id``. The ``GROUP BY`` adds an aggregate over the joined rows
    whose group count is bounded by :class:`~bayram.contracts.Vendor`, not by the table.
    """
    attributed_orders = sa.func.count(sa.distinct(VendorUsageRow.order_id)).label(
        "attributed_orders"
    )
    statement: Select[Any] = sa.select(
        VendorUsageRow.vendor,
        sa.func.sum(VendorUsageRow.cost_usd).label("cost_usd"),
        attributed_orders,
    ).join(OrderRow, OrderRow.id == VendorUsageRow.order_id)
    statement = statement.where(OrderRow.delivered_at.is_not(None))
    statement = apply_window(statement, OrderRow.delivered_at, window)
    statement = _narrow(statement, window=None, vendors=(), exclude_operations=SPENDABLE_EXCLUSIONS)
    rows = (
        await session.execute(
            statement.group_by(VendorUsageRow.vendor).order_by(
                attributed_orders.desc(), VendorUsageRow.vendor
            )
        )
    ).all()
    return tuple(
        VendorCostPerSong(
            vendor=row.vendor,
            cost_usd=_as_float(row.cost_usd),
            delivered_orders=delivered_orders,
            attributed_orders=int(row.attributed_orders),
        )
        for row in rows
    )


async def units_per_delivered_song_by_vendor(
    session: AsyncSession, *, window: TimeWindow | None = None, delivered_orders: int
) -> tuple[VendorUnitsPerSong, ...]:
    """What one delivered song consumed from each vendor, in that vendor's own units.

    :func:`cost_per_delivered_song_by_vendor` in units instead of dollars, over the same
    join, the same cohort and the same denominator — deliberately, because the two are read
    as a pair: cost per song moving without tokens per song moving is a price change, and
    the two moving together is a change in what we ask the vendor to do. That only reads as
    a pair while both quotients are over the same number of songs, which is why this takes
    the same ``delivered_orders`` parameter rather than counting its own.

    **The three unit families do not share an axis and are never summed.** Tokens, billed
    characters and milliseconds of audio are three incommensurable quantities that happen to
    be three columns; an LLM leg records tokens and no characters, a speech leg characters
    and no tokens, a music leg ``audio_ms``. Each is therefore ``NULL`` for a vendor that
    measures none of it — ``SUM`` over an all-``NULL`` group returns ``NULL`` and this module
    coalesces nothing, so that falls out for free. A ``0`` there would be this module's worst
    available lie: it would say the vendor rendered a song out of no tokens at all.

    **This shape carries no coverage count, and the missing number is recoverable.**
    :class:`~bayram.db.admin.views.VendorCostPerSong` publishes ``attributed_orders`` beside
    its cost precisely so an average over the instrumented subset cannot be read as an
    average over the cohort; :class:`~bayram.db.admin.views.VendorUnitsPerSong` has one count
    and it is the denominator. Since this read joins the same orders with the same filters,
    that vendor's ``attributed_orders`` from
    :func:`cost_per_delivered_song_by_vendor` over the SAME window IS this read's coverage,
    exactly — call the two together and render them side by side rather than inventing a
    second, differently-counted coverage figure here.

    A window in which nothing was delivered returns an EMPTY tuple, and every quotient on a
    row that does come back is ``None`` unless the vendor measured that unit. Nothing here
    reports a zero it did not measure.

    Ordered by ``vendor`` alone: all three quantity columns are nullable, ordering by one
    would put NULLs first on Postgres and last on SQLite, and there is no non-nullable
    volume column in this shape to break the tie with.

    INDEX: ``ix_orders_delivered_at``, then a nested loop into ``ix_vendor_usage_order_id``,
    as :func:`cost_per_delivered_song_by_vendor`.
    """
    statement: Select[Any] = sa.select(
        VendorUsageRow.vendor,
        sa.func.sum(VendorUsageRow.total_tokens).label("total_tokens"),
        sa.func.sum(VendorUsageRow.billed_characters).label("billed_characters"),
        sa.func.sum(VendorUsageRow.audio_ms).label("audio_ms"),
    ).join(OrderRow, OrderRow.id == VendorUsageRow.order_id)
    statement = statement.where(OrderRow.delivered_at.is_not(None))
    statement = apply_window(statement, OrderRow.delivered_at, window)
    statement = _narrow(statement, window=None, vendors=(), exclude_operations=SPENDABLE_EXCLUSIONS)
    rows = (
        await session.execute(
            statement.group_by(VendorUsageRow.vendor).order_by(VendorUsageRow.vendor)
        )
    ).all()
    return tuple(
        VendorUnitsPerSong(
            vendor=row.vendor,
            total_tokens=_as_int(row.total_tokens),
            billed_characters=_as_int(row.billed_characters),
            audio_ms=_as_int(row.audio_ms),
            delivered_orders=delivered_orders,
        )
        for row in rows
    )


async def cost_provenance(
    session: AsyncSession,
    *,
    window: TimeWindow | None = None,
    vendors: tuple[Vendor, ...] = (),
    exclude_operations: tuple[VendorOperation, ...] = SPENDABLE_EXCLUSIONS,
) -> tuple[CostProvenance, ...]:
    """How the window's money was arrived at: calls and spend per ``cost_source``.

    **The ``NULL`` bucket is the point of this read, not a leftover in it.** Every other
    cost figure on this surface collapses provenance into a ``MIN``/``MAX`` "mixed" boolean,
    which can tell an operator that a total disagrees with itself but never that most of it
    is arithmetic against a rate somebody typed into an environment variable — and it cannot
    say ANYTHING about the calls that carry no cost at all, because those rows drop out of
    ``MIN(cost_source)`` entirely. Here they are a group: ``GROUP BY`` treats ``NULL`` as one
    value, nothing below filters it out, and the row it produces reads "this many real calls
    happened and no cost could be computed for one of them". That is the number that says
    how much of the spend total is missing rather than small.

    ``cost_usd`` in that bucket is ``None`` **by construction and not by convention**: the
    table's ``cost_carries_its_source`` check constraint makes ``cost_usd`` and
    ``cost_source`` NULL together, so a group keyed on a NULL source contains only unpriced
    rows and ``SUM`` over it returns ``NULL`` on its own. Nothing here has to be careful
    about it; the schema already was.

    **A ``VENDOR_REPORTED`` bucket summing to ``0.0`` is a measurement and stays one.**
    OpenRouter reports a genuine zero on a free model and the LLM adapter keeps that zero
    deliberately, so ``cost_usd == 0.0`` beside a positive ``calls`` means "the vendor said
    this was free" — a fact that reconciles against an invoice line. It must never render
    like the ``None`` bucket, which means "nobody could say". This read is where the
    difference between those two sentences is measurable.

    ``exclude_operations`` defaults to :data:`SPENDABLE_EXCLUSIONS` rather than to the empty
    tuple :func:`vendor_usage_rollup` uses, and the default is doing real work. The balance
    poller writes roughly seventy-two ``HEALTH`` rows a day, all of them unpriced on purpose;
    left in, they would dominate the ``NULL`` bucket within a week and this read would report
    a deployment's spend as uninstrumented when what is uninstrumented is its quota probe. A
    caller auditing the whole table can still pass ``()`` and see them.

    Ordered by ``calls`` descending, with an explicit ``IS NULL`` key ahead of
    ``cost_source`` so the unpriced group lands last on both dialects rather than first on
    one of them — the module docstring's NULLS rule.

    INDEX: ``ix_vendor_usage_created_at`` carries the window; unwindowed this is a
    whole-table aggregate, which is accepted here because the read runs once per dashboard
    refresh and its output is bounded by the enum — three sources plus the NULL group, four
    rows at most, ever.
    """
    calls = sa.func.count().label("calls")
    statement: Select[Any] = sa.select(
        VendorUsageRow.cost_source,
        calls,
        sa.func.sum(VendorUsageRow.cost_usd).label("cost_usd"),
    )
    statement = _narrow(
        statement, window=window, vendors=vendors, exclude_operations=exclude_operations
    )
    rows = (
        await session.execute(
            statement.group_by(VendorUsageRow.cost_source).order_by(
                calls.desc(),
                # The unpriced group last on BOTH dialects — see the module docstring.
                VendorUsageRow.cost_source.is_(None),
                VendorUsageRow.cost_source,
            )
        )
    ).all()
    return tuple(
        CostProvenance(
            cost_source=_as_cost_source(row.cost_source),
            calls=int(row.calls),
            cost_usd=_as_float(row.cost_usd),
        )
        for row in rows
    )


async def unattributed_spend(
    session: AsyncSession,
    *,
    window: TimeWindow | None = None,
    grain: SeriesGrain = SeriesGrain.DAY,
) -> tuple[UnattributedSpendPerBucket, ...]:
    """Real work that reached no order — the spend :func:`cost_per_delivered_song` misses.

    ``order_id IS NULL AND task IS NOT NULL``, and **the second half is not optional.** A
    balance probe also carries a null ``order_id``; without the ``task`` predicate every
    hourly quota check would be reported as money spent on work nobody ordered, and the leak
    this series exists to surface would be buried under seventy-two rows a day of noise.
    :data:`SPENDABLE_EXCLUSIONS` covers the same rows from the other direction and both are
    applied, because the two predicates are answering different questions and either could
    be relaxed later without the other noticing.

    INDEX: the window rides ``ix_vendor_usage_created_at``; the null-``order_id`` predicate
    is a heap check, which is the right trade for a query that runs once per refresh.
    """
    bucket = bucket_expression(grain, VendorUsageRow.created_at)
    statement: Select[Any] = sa.select(
        bucket.label("bucket"),
        sa.func.sum(VendorUsageRow.cost_usd).label("cost_usd"),
        count_where(VendorUsageRow.cost_usd.is_not(None)).label("costed_calls"),
        sa.func.count().label("calls"),
    ).where(VendorUsageRow.order_id.is_(None), VendorUsageRow.task.is_not(None))
    statement = _narrow(
        statement, window=window, vendors=(), exclude_operations=SPENDABLE_EXCLUSIONS
    )
    rows = (await session.execute(statement.group_by(bucket).order_by(bucket))).all()
    return tuple(
        UnattributedSpendPerBucket(
            bucket=str(row.bucket),
            started_at=bucket_started_at(grain, str(row.bucket)),
            cost_usd=_as_float(row.cost_usd),
            costed_calls=int(row.costed_calls),
            calls=int(row.calls),
        )
        for row in rows
    )


async def vendor_operation_latency(
    session: AsyncSession,
    *,
    operation: VendorOperation,
    window: TimeWindow | None = None,
) -> OperationLatency:
    """Nearest-rank p50/p95 of ``latency_ms`` for ONE operation, with three denominators.

    Nearest rank rather than interpolated, and taken by the database with
    ``ORDER BY … LIMIT 1 OFFSET k``, for the reason :mod:`bayram.db.admin.metrics` gives at
    length: ``percentile_cont`` is a Postgres ordered-set function with no SQLite
    equivalent, and a query only production can execute is a query nobody tests.

    Three counts because they can differ and the difference is the story: ``calls`` is every
    call to that operation in the window, ``measured_calls`` is how many recorded a latency
    at all, and ``sample_count`` is what the percentiles were actually taken over. A p95
    whose sample size is invisible is a measurement of three calls read as a measurement of
    the system.

    INDEX: ``ix_vendor_usage_vendor_created_at`` filters the window; the ordering is over
    ``latency_ms``, which no index serves, so the sort is bounded by the window.
    """
    counts: Select[tuple[int, int]] = sa.select(
        sa.func.count().label("calls"),
        count_where(VendorUsageRow.latency_ms.is_not(None)).label("measured"),
    ).where(VendorUsageRow.operation == operation)
    counts = _narrow(counts, window=window, vendors=())
    totals = (await session.execute(counts)).one()

    base: Select[tuple[int | None]] = sa.select(
        VendorUsageRow.latency_ms.label("latency_ms")
    ).where(VendorUsageRow.operation == operation, VendorUsageRow.latency_ms.is_not(None))
    base = _narrow(base, window=window, vendors=())
    sample_count = int(totals.measured)
    if sample_count == 0:
        return OperationLatency(
            operation=operation,
            calls=int(totals.calls),
            measured_calls=0,
            sample_count=0,
            p50_ms=None,
            p95_ms=None,
        )
    return OperationLatency(
        operation=operation,
        calls=int(totals.calls),
        measured_calls=sample_count,
        sample_count=sample_count,
        p50_ms=await _latency_percentile(session, base, sample_count, _P50),
        p95_ms=await _latency_percentile(session, base, sample_count, _P95),
    )


async def fake_call_count(
    session: AsyncSession, *, window: TimeWindow | None = None
) -> FakeCallGuard:
    """How many of the window's calls came from a fake-provider run, and how many there were.

    **The one reader in this package that opts INTO ``is_fake`` rows**, and it exists so the
    exclusion every other reader performs is VISIBLE rather than silent. ``Vendor.FAKE``'s
    whole purpose is that a demo run is recorded and visibly excluded; a panel that dropped
    those rows without saying so would turn a demo from "silently inflating spend" into
    "silently invisible", which is the same defect facing the other way.

    INDEX: ``ix_vendor_usage_created_at``.
    """
    statement: Select[tuple[int, int]] = sa.select(
        count_where(VendorUsageRow.is_fake.is_(True)).label("fake_calls"),
        sa.func.count().label("total_calls"),
    ).select_from(VendorUsageRow)
    statement = _narrow(statement, window=window, vendors=(), include_fake=True)
    row = (await session.execute(statement)).one()
    return FakeCallGuard(fake_calls=int(row.fake_calls), total_calls=int(row.total_calls))


async def has_recorded_vendor_usage(session: AsyncSession) -> bool:
    """True once ANY vendor call has been recorded here. The ``isVendorUsage`` capability.

    A row probe rather than a :func:`~bayram.db.admin.sql.has_table` one, and the window is
    ignored on purpose. The migration landing tells you the schema is ready; it tells you
    nothing about whether a worker in this deployment writes rows, and a panel that read the
    schema would confidently draw an empty spend chart for a bot nobody instrumented.
    """
    return await _exists(session)


async def has_priced_vendor_usage(session: AsyncSession) -> bool:
    """True once any recorded call carries a cost. The ``isVendorCost`` capability.

    Separate from :func:`has_recorded_vendor_usage` because the two absences have different
    remedies, and the rate card is why the split is not academic: out of the box the MUSIC
    leg alone is priced — ``music_usd_per_minute`` ships at a placeholder ``0.15`` and its
    figure is reported as ``ESTIMATED`` — while speech, transcription and both LLM legs stay
    unpriced until somebody configures a rate (``BAYRAM_ELEVENLABS_USD_PER_CHARACTER`` and the
    four ``BAYRAM_LLM_*_USD_PER_MILLION_*`` all ship ``0.0``, and Scribe has no rate to
    configure at all). So this flag flips true on the first rendered song and stays false in
    a deployment that has only ever moderated and written lyrics. Either way it says
    "something here is priced" and never "the money on this screen is complete", which is
    precisely why ``cost_source`` and ``costed_calls`` travel beside every total.

    ``cost_usd`` is indexed for this one query. ``read_capabilities`` reaches it on every
    ``/api/ops/pulse``, the Live screen polls that every five seconds, and the ``LIMIT 1``
    stops at the first hit only when there IS one — an unpriced deployment would otherwise
    scan the fastest-growing table in the schema, end to end, forever.
    """
    return await _exists(session, VendorUsageRow.cost_usd.is_not(None))


# ---------------------------------------------------------------------------
# internals
# ---------------------------------------------------------------------------
def _narrow[R: tuple[Any, ...]](
    statement: Select[R],
    *,
    window: TimeWindow | None,
    vendors: tuple[Vendor, ...],
    include_fake: bool = False,
    exclude_operations: tuple[VendorOperation, ...] = (),
) -> Select[R]:
    """The filter set every read here shares. **Real rows only, unless a caller says else.**

    Spelled once so the aggregates cannot come to disagree about which rows they describe —
    a rollup and a totals row counted over different populations is how one screen argues
    with itself. The window and vendor helpers are the existing ones and both are open by
    default: :func:`~bayram.db.admin.sql.apply_window` emits no lower predicate when ``start``
    is ``None``, and :func:`~bayram.db.admin.sql.apply_in` treats an empty tuple as "no filter"
    rather than as ``IN ()``.

    ``is_fake IS false`` is applied UNCONDITIONALLY unless ``include_fake`` is passed, and
    that asymmetry is the point — see the module docstring. ``exclude_operations`` is the
    opposite shape (empty means exclude nothing) because there is no operation a general
    read should silently drop; only the spend queries name :data:`SPENDABLE_EXCLUSIONS`, and
    each one names it in its own signature where a reviewer can see it.
    """
    narrowed = apply_window(statement, VendorUsageRow.created_at, window)
    narrowed = apply_in(narrowed, VendorUsageRow.vendor, vendors)
    if not include_fake:
        narrowed = narrowed.where(VendorUsageRow.is_fake.is_(False))
    if exclude_operations:
        narrowed = narrowed.where(VendorUsageRow.operation.not_in(exclude_operations))
    return narrowed


async def _exists(session: AsyncSession, *conditions: sa.ColumnElement[bool]) -> bool:
    """``SELECT 1 … LIMIT 1``. The answer is a boolean, so the scan stops at the first hit."""
    statement = sa.select(sa.literal(1)).select_from(VendorUsageRow).limit(1)
    if conditions:
        statement = statement.where(*conditions)
    return await session.scalar(statement) is not None


async def _latency_percentile(
    session: AsyncSession, base: Select[tuple[int | None]], sample_count: int, fraction: float
) -> int | None:
    """The nearest-rank percentile of ``latency_ms``, selected by the database."""
    offset = nearest_rank_offset(sample_count, fraction)
    value = await session.scalar(base.order_by(VendorUsageRow.latency_ms).limit(1).offset(offset))
    return None if value is None else int(value)


def _as_int(value: Any) -> int | None:
    """A ``SUM``/``MAX`` over a nullable integer column. ``None`` stays ``None``, always."""
    return None if value is None else int(value)


def _as_float(value: Any) -> float | None:
    """A ``SUM`` over ``cost_usd``. ``None`` means "no call in this group was priced"."""
    return None if value is None else float(value)


def _as_rounded_int(value: Any) -> int | None:
    """``AVG(latency_ms)`` as whole milliseconds.

    Rounded rather than truncated, and ``None`` when no call in the group recorded a
    latency: a mean of nothing is not zero milliseconds. The database does the averaging;
    this only chooses how the fractional millisecond is spelled.
    """
    return None if value is None else round(float(value))


def _as_cost_source(value: Any) -> CostSource | None:
    """The group's provenance, or ``None`` when nothing in it carries a cost.

    Read defensively rather than trusted to the column's own result processor: this is a
    ``MIN`` over an enum column, which SQLAlchemy types from the column but which some
    dialect could hand back as the underlying string.
    """
    return None if value is None else CostSource(value)


def _is_mixed(minimum: Any, maximum: Any) -> bool:
    """Whether the priced rows in a group disagree about how their cost was arrived at.

    ``MIN != MAX`` over the group's ``cost_source``, which is the whole test: the column is
    a closed enum, so two distinct values in one group means the group mixes provenances and
    the wire says "mixed" rather than naming one of them. ``NULL`` on either side means
    nothing in the group was priced at all, which is not a disagreement.
    """
    if minimum is None or maximum is None:
        return False
    return bool(minimum != maximum)
