"""``/metrics`` and ``/ops/*`` — the dashboard aggregates.

**Every number on this page is computed by the database.** Not one function here fetches a
row set and folds it in Python. That is a hard rule rather than a preference: the dashboard
is the screen an operator opens first and refreshes most, ``orders`` and
``generation_attempts`` are the two tables that only grow, and a rollup written as a Python
loop is one that reads the whole table across the network to produce nine integers. The
only arithmetic done in Python is over the handful of already-grouped results — turning
counts into shares — which is bounded by the number of distinct error codes, not by rows.

The one aggregate SQL cannot express portably is the percentile. ``percentile_cont`` is a
Postgres ordered-set function with no SQLite equivalent, and the unit suite runs on SQLite,
so a query only production can execute is a query nobody tests. :func:`delivery_latency`
instead takes the nearest-rank percentile with ``ORDER BY … LIMIT 1 OFFSET k`` over a
duration expression compiled per dialect (:class:`~bayram.db.admin.sql.DurationSeconds`). The
database still does the ordering and the selection; three small round trips replace one
unportable one.
"""

from __future__ import annotations

from datetime import date
from typing import Any

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql import ColumnElement, Select

from bayram.contracts import OrderState
from bayram.db.admin.attempts import (
    is_cost_instrumented,
    is_latency_instrumented,
    strategy_outcomes,
)
from bayram.db.admin.balances import has_polled_vendor_balances
from bayram.db.admin.overview import has_recorded_activity_history, has_recorded_churn
from bayram.db.admin.plan_purchases import has_recorded_plan_revenue
from bayram.db.admin.sql import (
    CHAT_MESSAGES_TABLE,
    PAYMENTS_TABLE,
    DurationSeconds,
    SeriesGrain,
    TimeWindow,
    UtcDay,
    apply_window,
    bucket_expression,
    bucket_started_at,
    count_pair,
    count_where,
    has_table,
    nearest_rank_offset,
    previous_window,
    spanning_window,
)
from bayram.db.admin.topup_purchases import has_recorded_topup_revenue
from bayram.db.admin.vendor_usage import has_priced_vendor_usage, has_recorded_vendor_usage
from bayram.db.admin.views import (
    DeliveredPerBucket,
    DeliveryOutcome,
    FailureCount,
    LatencySummary,
    OrderFunnel,
    OrdersPerDay,
    OrderStateTotal,
    ReadCapabilities,
    Trend,
)
from bayram.db.models.asset import AssetRow
from bayram.db.models.generation_attempt import GenerationAttemptRow
from bayram.db.models.order import OrderRow

__all__ = [
    "P50",
    "P95",
    "orders_per_day",
    "delivered_per_bucket",
    "delivered_counts",
    "delivery_outcome",
    "delivery_latency",
    "delivered_latency",
    "order_funnel",
    "failure_breakdown",
    "strategy_outcomes",
    "read_capabilities",
]

#: The two percentiles §6.4 asks for, named so a caller cannot transpose 0.5 and 0.95.
P50 = 0.5
P95 = 0.95

#: Terminal states. ``success_rate`` divides by these and by nothing else.
_TERMINAL_STATES: tuple[OrderState, ...] = (
    OrderState.DELIVERED,
    OrderState.FAILED,
    OrderState.CANCELLED,
)


async def orders_per_day(
    session: AsyncSession, *, window: TimeWindow | None = None
) -> tuple[OrdersPerDay, ...]:
    """Order volume per UTC day, oldest first. Days with no orders are absent from the series.

    **A COHORT, not throughput, and :func:`delivered_per_bucket` is the other one.** This
    buckets on ``created_at``, so a day's row answers "how much work ARRIVED that day, and
    what has become of it since" — a bucket whose ``delivered`` column keeps rising for days
    after the day itself closed. "How many songs SHIPPED that day" is a different question
    over a different column and the two disagree by exactly the pipeline latency. Neither is
    a fixed version of the other; ``/api/metrics/orders-by-day``, the pulse's callers and the
    SPA's ``summariseDays`` all depend on this one meaning what it has always meant.

    Absent rather than zero-filled: this layer does not know what range the caller wants
    charted, and inventing zeroes for days outside the data is how a chart grows a flat tail
    nobody asked for. The API layer, which does know the requested range, fills the gaps.
    """
    day = UtcDay(OrderRow.created_at)
    statement: Select[tuple[str, int, int, int, int]] = sa.select(
        day.label("day"),
        sa.func.count().label("total"),
        count_where(OrderRow.state == OrderState.DELIVERED).label("delivered"),
        count_where(OrderRow.state == OrderState.FAILED).label("failed"),
        count_where(OrderRow.is_paid.is_(True)).label("paid"),
    )
    statement = apply_window(statement, OrderRow.created_at, window)
    rows = (await session.execute(statement.group_by(day).order_by(day))).all()
    return tuple(
        OrdersPerDay(
            day=date.fromisoformat(str(day_text)),
            total=int(total),
            delivered=int(delivered),
            failed=int(failed),
            paid=int(paid),
        )
        for day_text, total, delivered, failed, paid in rows
    )


async def delivered_per_bucket(
    session: AsyncSession,
    *,
    window: TimeWindow | None = None,
    grain: SeriesGrain = SeriesGrain.DAY,
) -> tuple[DeliveredPerBucket, ...]:
    """Songs that SHIPPED per bucket, windowed on ``delivered_at``. Oldest first.

    The throughput counterpart of :func:`orders_per_day`, which is a cohort — see that
    function's docstring for the one-sentence difference. This is the series the mock's
    "Songs delivered" card and chart ask for, and counting it on ``created_at`` instead is
    how a chart of yesterday's shipping ends up describing the day before's intake.

    **No ``state = 'delivered'`` predicate accompanies the timestamp**, and that is a
    deliberate omission rather than a missing filter. ``delivered_at`` has exactly one
    writer — ``repository.set_state``, inside ``if state is OrderState.DELIVERED`` — and it
    is never cleared, so the column IS the delivery event. A state predicate beside a
    ``delivered_at`` range predicate cannot exclude a row the range already included; it
    would only cost the heap fetch the index scan otherwise avoids.

    The ``IS NOT NULL`` guard is applied only for an unwindowed call, because a range
    predicate already implies it and a redundant clause on the indexed column is one more
    thing for a planner to consider.

    INDEX: ``ix_orders_delivered_at``, a range scan. ``ix_orders_created_at`` cannot serve
    this — different column — and ``ix_orders_state_created_at`` leads with ``state``.
    """
    bucket = bucket_expression(grain, OrderRow.delivered_at)
    statement: Select[tuple[str, int]] = sa.select(
        bucket.label("bucket"), sa.func.count().label("delivered")
    )
    if window is None:
        statement = statement.where(OrderRow.delivered_at.is_not(None))
    statement = apply_window(statement, OrderRow.delivered_at, window)
    rows = (await session.execute(statement.group_by(bucket).order_by(bucket))).all()
    return tuple(
        DeliveredPerBucket(
            bucket=str(key),
            started_at=bucket_started_at(grain, str(key)),
            delivered=int(delivered),
        )
        for key, delivered in rows
    )


async def delivered_counts(session: AsyncSession, *, window: TimeWindow | None = None) -> Trend:
    """Songs delivered in the window, and in the equal-length window before it.

    ONE round trip for both numbers. The two counts are conditionals under a single
    predicate spanning both ranges (:func:`~bayram.db.admin.sql.count_pair` over
    :func:`~bayram.db.admin.sql.spanning_window`), so the database makes one index range scan
    that happens to be twice as wide rather than two scans. That economy is why every card
    on this screen can carry a delta without the page making eighteen extra requests a tick.

    ``previous`` is ``None`` when the caller gave no lower bound, because there is then no
    window length to step back by. Honest absence, not zero.

    INDEX: ``ix_orders_delivered_at``.
    """
    previous = previous_window(window)
    if window is None or previous is None:
        statement: Select[tuple[int]] = sa.select(sa.func.count()).select_from(OrderRow)
        statement = statement.where(OrderRow.delivered_at.is_not(None))
        statement = apply_window(statement, OrderRow.delivered_at, window)
        return Trend(current=int(await session.scalar(statement) or 0), previous=None)
    current_count, previous_count = count_pair(OrderRow.delivered_at, current=window)
    pair: Select[tuple[int, int]] = sa.select(
        current_count.label("current"), previous_count.label("previous")
    ).select_from(OrderRow)
    pair = apply_window(pair, OrderRow.delivered_at, spanning_window(window, previous))
    row = (await session.execute(pair)).one()
    return Trend(current=int(row.current), previous=int(row.previous))


async def delivery_outcome(
    session: AsyncSession, *, window: TimeWindow | None = None
) -> DeliveryOutcome:
    """Delivered / failed / cancelled / in-flight counts over a window, in one query."""
    statement: Select[tuple[int, int, int, int]] = sa.select(
        sa.func.count().label("total"),
        count_where(OrderRow.state == OrderState.DELIVERED).label("delivered"),
        count_where(OrderRow.state == OrderState.FAILED).label("failed"),
        count_where(OrderRow.state == OrderState.CANCELLED).label("cancelled"),
    )
    statement = apply_window(statement, OrderRow.created_at, window)
    row = (await session.execute(statement)).one()
    total, delivered, failed, cancelled = (int(value) for value in row)
    return DeliveryOutcome(
        total=total,
        delivered=delivered,
        failed=failed,
        cancelled=cancelled,
        in_flight=total - delivered - failed - cancelled,
    )


async def delivery_latency(
    session: AsyncSession, *, window: TimeWindow | None = None
) -> LatencySummary:
    """p50 and p95 of ``created_at`` → ``delivered_at``, in seconds.

    Only delivered orders are sampled. An order still in flight has no latency yet, and one
    that failed has no delivery to measure to; including either would make the number answer
    a question nobody asked.
    """
    seconds = DurationSeconds(OrderRow.created_at, OrderRow.delivered_at)
    base: Select[tuple[float]] = sa.select(seconds.label("seconds")).where(
        OrderRow.delivered_at.is_not(None)
    )
    base = apply_window(base, OrderRow.created_at, window)
    sample_count = int(
        await session.scalar(sa.select(sa.func.count()).select_from(base.subquery())) or 0
    )
    if sample_count == 0:
        return LatencySummary(sample_count=0, p50_seconds=None, p95_seconds=None)
    return LatencySummary(
        sample_count=sample_count,
        p50_seconds=await _percentile(session, base, seconds, sample_count, P50),
        p95_seconds=await _percentile(session, base, seconds, sample_count, P95),
    )


async def delivered_latency(
    session: AsyncSession, *, window: TimeWindow | None = None
) -> LatencySummary:
    """p50 and p95 of ``created_at`` → ``delivered_at``, sampled on the DELIVERY instant.

    Structurally :func:`delivery_latency` with one line changed — the window is applied to
    ``delivered_at`` instead of ``created_at`` — and the one line is the whole point.

    :func:`delivery_latency` samples orders CREATED in the window that happen to have been
    delivered, which at the trailing edge of any window is biased towards the fast ones: a
    slow order created inside the window has not delivered yet and is silently excluded. Set
    beside a "Songs delivered" card counted on ``delivered_at``, that is two numbers over two
    different populations sitting two hundred pixels apart. This function is what makes the
    median song time reconcile with the count of songs it is a median of.

    :func:`delivery_latency` is left alone rather than corrected, because the pulse and
    ``/metrics/latency`` publish the created-at cohort by contract and other callers read it.

    INDEX: ``ix_orders_delivered_at`` for the range; the percentile's ordering is over a
    computed duration that no index serves, so the sort is bounded by the window — which is
    itself an improvement on the pulse's unwindowed version, but is still a sort.
    """
    seconds = DurationSeconds(OrderRow.created_at, OrderRow.delivered_at)
    base: Select[tuple[float]] = sa.select(seconds.label("seconds")).where(
        OrderRow.delivered_at.is_not(None)
    )
    base = apply_window(base, OrderRow.delivered_at, window)
    sample_count = int(
        await session.scalar(sa.select(sa.func.count()).select_from(base.subquery())) or 0
    )
    if sample_count == 0:
        return LatencySummary(sample_count=0, p50_seconds=None, p95_seconds=None)
    return LatencySummary(
        sample_count=sample_count,
        p50_seconds=await _percentile(session, base, seconds, sample_count, P50),
        p95_seconds=await _percentile(session, base, seconds, sample_count, P95),
    )


async def order_funnel(session: AsyncSession, *, window: TimeWindow | None = None) -> OrderFunnel:
    """Where one created-at cohort of orders stands now, state by state, in one query.

    **Survivors, never passages.** ``capabilities.is_state_transition_log`` is ``False`` and
    no order-event table exists, so an order that passed through ``AUTHORIZED`` and then
    failed retains no record of the passage. Every number here says where orders ARE, and a
    caller that reads them as a flow is reading a drop-off that was never measured.

    **There is no "abandoned" count**, and that absence is argued rather than overlooked:
    drafts are DELETED outright at the abandoned-draft cutoff, so an abandonment figure
    would decay towards zero as the window lengthens and read as "nobody abandons any more".
    The ``DRAFT`` survivor count is published and the caption is the SPA's business.

    Not :func:`~bayram.db.admin.orders.count_orders_by_state`, which is correct but takes
    ``OrderFilters``, keeps a briefs outer join with no search term, and is guarded by
    RECORDS_READ — a permission a dashboard-only operator does not hold.

    Every state is present, zero-filled, in declaration order: a funnel with a rung missing
    is unreadable, and ``0`` here is a real count of a real state rather than an unmeasured
    quantity.

    QUERY COST, stated rather than implied: this gets no range seek.
    ``ix_orders_state_created_at`` leads with ``state``, so a ``created_at`` window against
    it is at best a full index scan; Postgres will more likely range-scan
    ``ix_orders_created_at`` and check ``state`` in the heap. One bounded scan per refresh
    over the window, accepted deliberately.
    """
    states = tuple(OrderState)
    statement: Select[Any] = sa.select(
        sa.func.count().label("created"),
        count_where(OrderRow.is_paid.is_(True)).label("paid"),
        *(count_where(OrderRow.state == state).label(f"state_{state.value}") for state in states),
    )
    statement = apply_window(statement, OrderRow.created_at, window)
    row = (await session.execute(statement)).one()
    mapping = row._mapping
    return OrderFunnel(
        created=int(mapping["created"]),
        paid=int(mapping["paid"]),
        by_state=tuple(
            OrderStateTotal(state=state, count=int(mapping[f"state_{state.value}"]))
            for state in states
        ),
    )


async def failure_breakdown(
    session: AsyncSession, *, window: TimeWindow | None = None
) -> tuple[FailureCount, ...]:
    """Failed generation attempts grouped by ``error_code``, largest first.

    ``is_retryable`` is deliberately NOT reported, though §6.4 sketches it. Retryability is a
    property of the ``BayramError`` subclass that was raised, not of the ``ErrorCode`` value that
    got persisted — ``ProviderTimeoutError`` and ``ProviderError`` can carry codes whose
    retryability differs per instance — so deriving it from this column would be a guess
    printed as a fact. Phase 5 can persist the flag alongside the code; until it does, the
    honest breakdown is counts.
    """
    statement: Select[tuple[str | None, int]] = sa.select(
        GenerationAttemptRow.error_code, sa.func.count().label("total")
    ).where(GenerationAttemptRow.is_success.is_(False))
    statement = apply_window(statement, GenerationAttemptRow.created_at, window)
    rows = (
        await session.execute(
            statement.group_by(GenerationAttemptRow.error_code).order_by(
                sa.func.count().desc(), GenerationAttemptRow.error_code
            )
        )
    ).all()
    counts = tuple((error_code, int(total)) for error_code, total in rows)
    failures = sum(total for _, total in counts)
    return tuple(
        FailureCount(error_code=error_code, count=total, share=total / failures)
        for error_code, total in counts
    )


async def read_capabilities(session: AsyncSession) -> ReadCapabilities:
    """What this deployment can honestly answer. Measured, never declared.

    **Thirteen flags now, and five of them arrived with the dashboard instrumentation.**
    Every one of the five is a ROW probe rather than a
    :func:`~bayram.db.admin.sql.has_table` one, for the reason the vendor pair already
    documents below: their migrations ship with the panel, so a schema probe would report
    every deployment as instrumented on the day the revision lands — including one whose
    worker is an older build that writes nothing. And they are five flags rather than one
    "revenue" flag because the absences have five different remedies: nobody has bought a
    plan here; no top-up AMOUNT has ever been recorded here (which is true of every
    deployment's entire history up to that revision, and is the state the SPA must render as
    "sold before amounts were recorded" rather than as an empty chart); the membership
    handler has not yet observed a block; the balance poller has never run; and the nightly
    snapshot job has not yet taken a first reading, so there is no activity HISTORY to draw
    even though the live gauge answers fine.

    Five of the original eight are probes against real rows and three are schema questions, and none
    of them is a constant somebody has to remember to flip: the cost flags turn true the
    first time Phase 5 writes a non-zero column, and the table flags turn true the moment
    the migration that creates the table is in ``Base.metadata``.

    **The two vendor flags are ROW probes and not** :func:`~bayram.db.admin.sql.has_table`
    **ones**, which is the only place on this surface where the difference is load-bearing.
    ``vendor_usage``'s migration ships with the panel, so ``has_table`` would answer true on
    every deployment the day it lands — including one whose worker is an older build that
    writes no rows at all. That deployment is honestly *not instrumented*, and a capability
    that said otherwise would have the panel drawing an empty spend chart instead of saying
    so. The pair is also two flags rather than one because the two absences have different
    remedies: ``is_vendor_usage`` false means nothing is recording, and ``is_vendor_cost``
    false with ``is_vendor_usage`` true means calls ARE recorded and not one of them carried
    a cost — "not priced", which is true, rather than a fabricated ``$0.00``.

    That second state is the NARROW one and not the shipped one. ``music_usd_per_minute``
    ships at a placeholder ``0.15``, so the music leg is priced out of the box (reported as
    ``ESTIMATED``) while speech, transcription and both LLM legs stay unpriced until a rate
    is configured. ``is_vendor_cost`` therefore flips true on the first rendered song, and
    stays false only in a deployment that has recorded calls but never rendered one. It is
    "something here is priced", never "no rate is configured" and never "this money is
    complete" — which is why :func:`~bayram.db.admin.vendor_usage.vendor_usage_rollup` sends
    ``cost_source`` and ``costed_calls`` alongside every total.
    """
    return ReadCapabilities(
        is_cost_telemetry=await is_cost_instrumented(session),
        is_latency_telemetry=await is_latency_instrumented(session),
        is_asset_storage_key_recorded=await _any_storage_key(session),
        is_chat_capture=has_table(CHAT_MESSAGES_TABLE),
        is_payment_ledger=has_table(PAYMENTS_TABLE),
        # No order-event table exists, so every state transition on the timeline is inferred
        # from a mutable column. §6.5 requires the panel to say so rather than imply a log.
        is_state_transition_log=False,
        is_vendor_usage=await has_recorded_vendor_usage(session),
        is_vendor_cost=await has_priced_vendor_usage(session),
        is_plan_revenue=await has_recorded_plan_revenue(session),
        is_topup_revenue=await has_recorded_topup_revenue(session),
        is_churn_instrumented=await has_recorded_churn(session),
        is_vendor_balance=await has_polled_vendor_balances(session),
        is_activity_history=await has_recorded_activity_history(session),
    )


# ---------------------------------------------------------------------------
# internals
# ---------------------------------------------------------------------------
async def _percentile(
    session: AsyncSession,
    base: Select[tuple[float]],
    order_by: ColumnElement[float],
    sample_count: int,
    fraction: float,
) -> float | None:
    """The nearest-rank percentile, selected by the database rather than in Python."""
    offset = nearest_rank_offset(sample_count, fraction)
    value = await session.scalar(base.order_by(order_by).limit(1).offset(offset))
    return None if value is None else float(value)


async def _any_storage_key(session: AsyncSession) -> bool:
    """True once any asset records where its bytes live — see §5.11 on ``_replace_assets``.

    Without a storage key the retention sweep has nothing to delete from object storage, so
    this flag is what stops the panel reporting a purge as complete when the archived audio
    is still there.
    """
    probe = await session.scalar(
        sa.select(sa.literal(1))
        .select_from(AssetRow)
        .where(AssetRow.storage_key.is_not(None))
        .limit(1)
    )
    return probe is not None
