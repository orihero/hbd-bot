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
duration expression compiled per dialect (:class:`~hbd.db.admin.sql.DurationSeconds`). The
database still does the ordering and the selection; three small round trips replace one
unportable one.
"""

from __future__ import annotations

from datetime import date

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql import ColumnElement, Select

from hbd.contracts import OrderState
from hbd.db.admin.attempts import is_cost_instrumented, is_latency_instrumented, strategy_outcomes
from hbd.db.admin.sql import (
    CHAT_MESSAGES_TABLE,
    PAYMENTS_TABLE,
    DurationSeconds,
    TimeWindow,
    UtcDay,
    apply_window,
    count_where,
    has_table,
    nearest_rank_offset,
)
from hbd.db.admin.views import (
    DeliveryOutcome,
    FailureCount,
    LatencySummary,
    OrdersPerDay,
    ReadCapabilities,
)
from hbd.db.models.asset import AssetRow
from hbd.db.models.generation_attempt import GenerationAttemptRow
from hbd.db.models.order import OrderRow

__all__ = [
    "P50",
    "P95",
    "orders_per_day",
    "delivery_outcome",
    "delivery_latency",
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


async def failure_breakdown(
    session: AsyncSession, *, window: TimeWindow | None = None
) -> tuple[FailureCount, ...]:
    """Failed generation attempts grouped by ``error_code``, largest first.

    ``is_retryable`` is deliberately NOT reported, though §6.4 sketches it. Retryability is a
    property of the ``HbdError`` subclass that was raised, not of the ``ErrorCode`` value that
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

    Three of the six are probes against real rows and three are schema questions, and none
    of them is a constant somebody has to remember to flip: the cost flags turn true the
    first time Phase 5 writes a non-zero column, and the table flags turn true the moment
    the migration that creates the table is in ``Base.metadata``.
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
