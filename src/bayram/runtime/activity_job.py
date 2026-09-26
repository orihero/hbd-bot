"""The nightly job that gives "active users" a history.

``users.last_seen_at`` is UPSERTed in place on every touch, so the number of people active
on any past day is not merely unqueried — it is unrecoverable. Nothing on the dashboard can
draw an activity line today, and no read layer, index or endpoint could change that, because
the values that would have answered it were overwritten a minute at a time. The only fix is
to start keeping samples, and this is the thing that keeps them.

It is its own module rather than another function in :mod:`bayram.runtime.jobs` for
:mod:`bayram.runtime.retention_job`'s stated reason: it shares nothing with the kit job — no
``Bot``, no chat, no progress sink, no FSM session, no retry ladder — and folding it in would
drag one more concern into the module that already has to import ``aiogram``.

**THE SERIES STARTS TONIGHT AND CANNOT BE BACKFILLED.** There is no seeding pass and there
must never be one. An estimate from ``users.created_at`` would be a fabricated measurement in
a table whose whole purpose is to hold real ones, and ``active_30d_accounts`` is honestly
bounded by deployment age for its first thirty days — a ramp that looks like growth and is
not. The panel's job is to render that as what it is.

**A DAY THE WORKER WAS DOWN PRODUCES NO ROW, and that is the design.** This job does not
backfill yesterday, because yesterday's ``last_seen_at`` values no longer exist to be
counted: a sample taken at noon today measures today, whatever date it is filed under. So a
missed night is a GAP, the read layer returns the days it has, and nothing zero-fills. A
zero-filled gap would say nobody used the bot that day — a false measurement wearing a chart
line, which is the null-never-zero rule applied to a series rather than to a column.

**RE-RUNNING THE SAME DAY IS IDEMPOTENT, IN THE DATABASE AND NOT IN A BRANCH.**
``record_snapshot`` writes through ``insert_or_ignore`` against the unique
``snapshot_date``, so a worker restarted at 06:00 after the 00:07 cron already fired does
not re-anchor that day's sample by six hours. The job does not read-then-write to check:
that would be a race two replicas could both lose, and the constraint is authoritative
anyway. It reports which of the two happened, because "already recorded" is a restart and
"recorded" is a night's work, and an operator reading the log should be able to tell.

**IT NEVER RAISES INTO THE SCHEDULER.** A failed measurement is logged and returned as a
summary carrying its error, exactly as the retention sweep does. The only exception that
escapes is the ``PipelineError`` from :func:`_require_container`, which is a startup wiring
bug rather than a run-time one — and would be as true of the next invocation as of this one.
"""

from __future__ import annotations

import time
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Final

from bayram.db.activity import ActivityCounts, measure_activity, record_snapshot
from bayram.db.base import utc_now
from bayram.errors import PipelineError
from bayram.logging import get_logger
from bayram.runtime.container import AppContainer

__all__ = [
    "ACTIVITY_SNAPSHOT_CRON_HOUR",
    "ACTIVITY_SNAPSHOT_CRON_MINUTE",
    "ACTIVITY_SNAPSHOT_JOB_NAME",
    "ActivitySnapshotResult",
    "record_activity_snapshot",
]

_LOG = get_logger(__name__)

#: ARQ dispatches by function name, so the registration in ``WorkerSettings`` and the
#: function must agree on this exact string. Asserted against the function at import.
ACTIVITY_SNAPSHOT_JOB_NAME: Final[str] = "record_activity_snapshot"

#: Just after midnight UTC, so the sample sits at the very start of the day it is filed
#: under and ``anchor_offset_s`` reads in the hundreds of seconds. Not ``:00``, for the
#: reason the retention sweep is not either — a scheduled job has no cause to queue behind
#: everything else in the world — and minute 7 rather than 17 or 43 so that the three crons
#: in this worker never contend for the same database at the same instant.
ACTIVITY_SNAPSHOT_CRON_HOUR: Final[int] = 0
ACTIVITY_SNAPSHOT_CRON_MINUTE: Final[int] = 7

#: The kit job's context key, re-stated rather than imported. Importing it from ``jobs``
#: would make this module depend on the one that depends on it.
CONTAINER_CTX_KEY: Final[str] = "container"


@dataclass(frozen=True, slots=True)
class ActivitySnapshotResult:
    """What one night's run did.

    :attr:`is_written` and :attr:`counts` are separate on purpose: a run that measured the
    population and then found the day already recorded still MEASURED something, and the log
    line carries the numbers either way so a duplicate run is visibly a duplicate rather than
    a silent nothing.
    """

    counts: ActivityCounts | None = None
    is_written: bool = False
    error: str | None = None


def _require_container(ctx: Mapping[str, Any]) -> AppContainer:
    container = ctx.get(CONTAINER_CTX_KEY)
    if not isinstance(container, AppContainer):
        raise PipelineError(
            "worker context is missing a usable 'container'",
            context={"key": CONTAINER_CTX_KEY, "found": type(container).__name__},
        )
    return container


def _summary(
    result: ActivitySnapshotResult, *, taken_at: datetime, duration_ms: int
) -> dict[str, Any]:
    """The JSON-safe dict ARQ stores as the job result, and the log line's body."""
    counts = result.counts
    return {
        "snapshot_date": taken_at.date().isoformat(),
        "taken_at": taken_at.isoformat(),
        "duration_ms": duration_ms,
        "is_written": result.is_written,
        "total_accounts": counts.total if counts is not None else None,
        "blocked_accounts": counts.blocked if counts is not None else None,
        "active_24h_accounts": counts.active_24h if counts is not None else None,
        "active_7d_accounts": counts.active_7d if counts is not None else None,
        "active_30d_accounts": counts.active_30d if counts is not None else None,
        "error": result.error,
    }


async def record_activity_snapshot(
    ctx: Mapping[str, Any], *, now: datetime | None = None
) -> dict[str, Any]:
    """Measure the population once and file the sample under today's UTC date.

    ``now`` is injectable for the same reason ``purge_expired`` takes it: a test writes a
    fortnight of history in a loop instead of waiting for one.

    The measurement and the insert share ONE transaction. They must: the row's ``taken_at``
    is the anchor its five windows were computed against, and a sample committed separately
    from the counts it describes could be filed against a population that had already moved.

    Returns a JSON-safe summary. Raises only ``PipelineError`` when the worker was wired up
    wrong.
    """
    container = _require_container(ctx)
    taken_at = now or utc_now()
    started = time.monotonic()

    try:
        async with container.require_session_factory().begin() as session:
            counts = await measure_activity(session, at=taken_at)
            is_written = await record_snapshot(
                session, day=taken_at.date(), at=taken_at, counts=counts
            )
        result = ActivitySnapshotResult(counts=counts, is_written=is_written)
    except Exception as exc:
        # Logged and reported, never raised: the scheduler retrying a failed count would
        # re-take the sample minutes later and file it under the same day anyway, and a
        # crashed cron is indistinguishable from one that stopped firing.
        _LOG.error(
            "the nightly activity snapshot failed",
            extra={"snapshot_date": taken_at.date().isoformat(), "failure": repr(exc)},
            exc_info=exc,
        )
        result = ActivitySnapshotResult(error=repr(exc))

    summary = _summary(
        result, taken_at=taken_at, duration_ms=int((time.monotonic() - started) * 1000)
    )
    if result.error is not None:
        _LOG.warning("activity snapshot finished with no row", extra=summary)
    elif result.is_written:
        _LOG.info("activity snapshot recorded", extra=summary)
    else:
        # Not a warning. The unique constraint did its job; this is a restart, and saying so
        # plainly is what stops somebody "fixing" the idempotency later.
        _LOG.info("activity snapshot for this day was already recorded", extra=summary)
    return summary


assert record_activity_snapshot.__name__ == ACTIVITY_SNAPSHOT_JOB_NAME, (
    "the registered name and the job function have drifted apart; ARQ would never dispatch"
)
