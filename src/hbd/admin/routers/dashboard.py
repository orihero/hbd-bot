"""``GET /api/ops/*`` and ``GET /api/metrics/*`` — the first screen an operator opens.

Six reads, no writes, and every one of them answers with something the database counted.
The rules below are what this screen lives or dies by, because a dashboard that rounds a
number off is worse than one that has no number: it is believed.

**Capabilities are MEASURED, never declared.** :func:`~hbd.db.admin.metrics.read_capabilities`
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

**``successRate`` divides by terminal orders only.** :class:`~hbd.db.admin.views.DeliveryOutcome`
already computes it that way and this router exposes that value rather than recomputing one;
counting in-flight orders in the denominator would make the rate fall every time traffic
rises, which is the opposite of what the number is for. The schema layer reports ``null``
when nothing has reached a terminal state at all — see :mod:`hbd.admin.schemas.dashboard`.

**Percentiles are nearest-rank, and ``sampleCount`` travels with them.** Both numbers are
durations that were really observed, and the count that produced them is on the wire beside
them so "p95 = 4s" from three orders is not read as a measurement of the system.

**A day with no orders is absent from the series**, not zero-filled. ``from``/``to`` are
optional here, so this layer frequently does not know what range the caller wants charted,
and inventing zeroes for days before the deployment existed is how a chart grows a flat tail
nobody asked for.

**Nothing on this screen is personal data.** Counts, enum members, UTC days and error codes —
no name, no note, no transcript, no telegram id. So §12.2's DASHBOARD_READ **R** cell for
OWNER changes nothing here: there is no masking decision to make, no serializer to route
through, and no unmasked variant of any response. That is stated so a reader who checks the
matrix and sees **R** does not go looking for the redaction this router does not do.

**The pulse takes no window.** It is the state of the deployment as a whole; a default window
baked in here would be a policy an operator could not see or argue with, and the four
``/metrics/*`` routes are where a window is asked for explicitly. ``from`` and ``to`` there
are given together or not at all — one end of a half-open interval is a range nobody chose.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Final

from fastapi import APIRouter, Depends, Query

from hbd.admin.deps import API_PREFIX, Db, require_permission
from hbd.admin.errors import AdminProblem, ProblemError, unwrap
from hbd.admin.schemas.dashboard import (
    CapabilitiesView,
    FailureView,
    LatencyView,
    OrdersPerDayView,
    PulseView,
    StrategyOutcomeView,
    to_capabilities_view,
    to_failure_view,
    to_latency_view,
    to_orders_per_day_view,
    to_pulse_view,
    to_strategy_outcome_view,
)
from hbd.admin.security.permissions import Permission
from hbd.db.admin.attempts import strategy_outcomes
from hbd.db.admin.metrics import (
    delivery_latency,
    delivery_outcome,
    failure_breakdown,
    orders_per_day,
    read_capabilities,
)
from hbd.db.admin.sql import TimeWindow, time_window
from hbd.errors import ErrorCode

__all__ = [
    "CAPABILITIES_PATH",
    "FAILURES_PATH",
    "LATENCY_PATH",
    "NAME_STRATEGIES_PATH",
    "ORDERS_BY_DAY_PATH",
    "PULSE_PATH",
    "build_dashboard_router",
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


def _invalid(message: str) -> ProblemError:
    """422 in the pipeline taxonomy — the code the rest of the system already uses for this."""
    return ProblemError(AdminProblem(code=ErrorCode.INVALID_INPUT, message=message))


def _aware(name: str, value: datetime | None) -> datetime | None:
    """Refuse a naive instant (§6.1): the column is ``timestamptz`` and would raise anyway."""
    if value is not None and value.tzinfo is None:
        raise _invalid(f"{name} must carry a UTC offset, e.g. 2026-08-30T12:00:00Z")
    return value


def build_window(
    since: Annotated[datetime | None, Query(alias="from")] = None,
    until: Annotated[datetime | None, Query(alias="to")] = None,
) -> TimeWindow | None:
    """``?from=&to=`` as a dependency, or ``None`` for the whole record.

    Both or neither. Accepting one end would mean guessing the other — "now", or the first
    row ever written — and a window half of which the caller did not choose is one whose
    numbers they cannot reproduce. ``time_window`` owns the ordering check, so ``to`` before
    ``from`` comes back as the same 422 through the same path.
    """
    start, end = _aware("from", since), _aware("to", until)
    if start is None and end is None:
        return None
    if start is None or end is None:
        raise _invalid("from and to must be given together, or neither")
    return unwrap(time_window(start, end))


#: The dependency alias every windowed route annotates with.
Window = Annotated[TimeWindow | None, Depends(build_window)]


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
        """The candidate-orthography bake-off ``HBD_NAME_CANDIDATE_ORDER`` is reordered from."""
        return [
            to_strategy_outcome_view(outcome)
            for outcome in await strategy_outcomes(db, window=window)
        ]

    return router
