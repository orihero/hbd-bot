"""The job that makes the FIL-7 retention schedule actually run.

Everything under it already existed and none of it had ever executed. ``purge_expired``
was complete, tested and called by nothing: ``WorkerSettings`` registered one function and
no ``cron_jobs``, so every retention clock in the schema was decorative. This module is the
caller, and the hourly ``cron`` entry in :mod:`bayram.runtime.jobs` is the thing that fires it.

It exists as its own module rather than as another function in ``jobs.py`` because it
shares nothing with the kit job: no ``Bot``, no chat, no progress sink, no FSM session, no
retry ladder. The only thing the two have in common is the ARQ context, and joining them
would drag ``aiogram`` into the one job that has no user waiting on it.

**Three things it does that the report alone cannot.**

*It deletes the bytes.* ``purge_expired`` deliberately returns storage keys instead of
deleting the objects itself — it owns rows, not a bucket, and must not half-succeed by
deleting bytes and then failing to commit (see :mod:`bayram.db.purge`). That design was
correct and load-bearing and had no counterpart: with no caller, an archived song's row
vanished on schedule and its file stayed on disk forever. The deletion loop below is that
counterpart.

*It records the mismatch rather than smoothing it over.* ``storage_keys_returned`` and
``storage_keys_deleted`` are written as two numbers. When they differ, bytes were orphaned,
and that is the exact failure this job exists to make visible — an averaged "objects
cleaned up" figure would have hidden it. Every failing delete is logged individually, with
its error, before the count is incremented.

*It writes a row for a FAILED sweep too.* A run that returned ``Err`` is the run an
operator most needs to see; recording nothing would make it indistinguishable from a
scheduler that stopped firing, which is the one thing ``purge_runs`` exists to tell apart.

Note on today's honest zero: nothing writes ``assets.storage_key`` yet (the repository's
asset replace path does not set it), so ``purge_expired`` hands back an empty tuple and
this job records deleting zero keys. That is the truth about today and it is recorded as
such — not asserted away — and the loop is already correct for the day the column starts
being written.
"""

from __future__ import annotations

import time
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Final

from bayram.contracts import Result, is_err
from bayram.db.admin import retention as retention_queries
from bayram.db.base import utc_now
from bayram.db.enums import PurgeTrigger
from bayram.db.purge import DEFAULT_PURGE_BATCH_SIZE, PurgeReport, purge_expired
from bayram.db.retention import resolve_retention_policy
from bayram.errors import PipelineError
from bayram.logging import get_logger
from bayram.runtime.container import AppContainer

__all__ = [
    "run_retention_sweep",
    "RETENTION_JOB_NAME",
    "RETENTION_CRON_MINUTE",
    "StorageSweepResult",
]

_LOG = get_logger(__name__)

#: ARQ dispatches by function name, so the enqueue side (``POST /api/retention/run``) and
#: the worker side must agree on this exact string. Asserted against the function at import.
RETENTION_JOB_NAME: Final[str] = "run_retention_sweep"

#: Minute past the hour the cron fires. Deliberately not ``:00``: every other scheduled
#: thing in the world fires on the hour, and a bounded sweep of five tables has no reason
#: to queue behind them.
RETENTION_CRON_MINUTE: Final[int] = 17

#: The kit job's context key, re-stated rather than imported. Importing it from ``jobs``
#: would make this module depend on the one that depends on it.
CONTAINER_CTX_KEY: Final[str] = "container"


@dataclass(frozen=True, slots=True)
class StorageSweepResult:
    """How the object-store leg went. Two numbers, never collapsed into one.

    ``deleted < len(keys)`` means bytes were orphaned. Reporting only "objects cleaned up"
    would make that arithmetically invisible, which is the failure this job exists to
    surface.
    """

    deleted: int = 0
    failed: int = 0


def _as_trigger(value: object) -> PurgeTrigger:
    """Coerce whatever the queue handed over into a ``PurgeTrigger``.

    ARQ round-trips job kwargs through a serializer, and the admin enqueue side may well
    send a plain string. An unrecognised value is recorded as ``CRON`` with a warning
    rather than raising: the sweep itself is the important part, and refusing to run a
    legally required purge over a mislabelled trigger would be the wrong trade.
    """
    if isinstance(value, PurgeTrigger):
        return value
    if isinstance(value, str):
        try:
            return PurgeTrigger(value)
        except ValueError:
            pass
    _LOG.warning(
        "unrecognised purge trigger; recording it as cron",
        extra={"trigger": repr(value)},
    )
    return PurgeTrigger.CRON


def _require_container(ctx: Mapping[str, Any]) -> AppContainer:
    container = ctx.get(CONTAINER_CTX_KEY)
    if not isinstance(container, AppContainer):
        raise PipelineError(
            "worker context is missing a usable 'container'",
            context={"key": CONTAINER_CTX_KEY, "found": type(container).__name__},
        )
    return container


async def _delete_objects(container: AppContainer, keys: tuple[str, ...]) -> StorageSweepResult:
    """Delete every key the purge handed back. Never raises; logs each failure by itself.

    Failures do not stop the loop. One unreachable object must not strand the other four
    hundred, and the run's job is to remove as much as it can and then report honestly on
    what is left — which the caller does by writing both counts to the row.
    """
    deleted = 0
    failed = 0
    for key in keys:
        removed = await container.storage.delete(key)
        if is_err(removed):
            failed += 1
            # Logged one by one, with the storage layer's own error. A summary count alone
            # would say bytes leaked and never say which bytes, and the key is the only
            # handle an operator has for a manual sweep.
            #
            # This is a DELIBERATE asymmetry with ``bayram.db.purge._purge``, which excludes
            # ``storage_keys`` from its success line because "an object key is the only
            # thing standing between a signed URL and someone else's birthday song". The
            # difference is the path: on success the bytes are gone and the key buys an
            # attacker a 404, while on failure the object is still there and orphaned, and
            # unrecoverable without its key. One key per failure, on an ERROR line, is the
            # smallest thing that makes the manual sweep possible. The key is not repeated
            # as a separate field — ``to_log_dict`` already carries it, and the duplicate
            # was unintentional.
            _LOG.error(
                "an expired object could not be deleted from storage",
                extra=removed.error.to_log_dict(),
            )
            continue
        deleted += 1
    return StorageSweepResult(deleted=deleted, failed=failed)


async def _record(
    container: AppContainer,
    *,
    report: PurgeReport,
    trigger: PurgeTrigger,
    tally: StorageSweepResult,
    duration_ms: int,
    triggered_by_username: str | None,
    error_code: str | None,
) -> None:
    """Write the ``purge_runs`` row. Never raises — the sweep already happened.

    A failure here loses the record of a purge that did occur, which is bad, but raising
    would additionally hand ARQ a failed job for work that succeeded and get the whole
    thing retried. The failure is logged with its cause instead.
    """
    try:
        async with container.require_session_factory().begin() as session:
            await retention_queries.record_run(
                session,
                report=report,
                trigger=trigger,
                duration_ms=duration_ms,
                storage_keys_deleted=tally.deleted,
                storage_delete_failures=tally.failed,
                triggered_by_username=triggered_by_username,
                error_code=error_code,
            )
    except Exception as exc:
        _LOG.error(
            "the retention sweep ran but its record could not be written",
            extra={"trigger": trigger.value, "failure": repr(exc)},
            exc_info=exc,
        )


def _summary(
    *,
    report: PurgeReport,
    trigger: PurgeTrigger,
    tally: StorageSweepResult,
    duration_ms: int,
    error_code: str | None,
) -> dict[str, Any]:
    """The JSON-safe dict ARQ stores as the job result, and the log line's body."""
    return {
        "trigger": trigger.value,
        "duration_ms": duration_ms,
        "rows_affected": report.total_rows_affected,
        "storage_keys_returned": len(report.storage_keys),
        "storage_keys_deleted": tally.deleted,
        "storage_delete_failures": tally.failed,
        "is_batch_full": report.has_work_remaining,
        "error": error_code,
    }


async def run_retention_sweep(
    ctx: Mapping[str, Any],
    *,
    trigger: PurgeTrigger = PurgeTrigger.CRON,
    triggered_by_username: str | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Run every retention clock once, delete the bytes behind it, and record the run.

    ``trigger`` defaults to ``CRON`` because ARQ's ``cron()`` invokes a job with the context
    and nothing else; the manual and erasure paths pass their own and are accountable
    differently (see :class:`bayram.db.enums.PurgeTrigger`).

    ``now`` is injectable for the same reason ``purge_expired`` takes it: a test advances
    thirteen months instead of waiting for them.

    Returns a JSON-safe summary. Raises only ``PipelineError`` when the worker was wired
    up wrong — a startup bug, not a run-time one.
    """
    container = _require_container(ctx)
    resolved_trigger = _as_trigger(trigger)
    ran_at = now or utc_now()
    started = time.monotonic()

    outcome = await purge_expired(
        container.require_session_factory(),
        now=ran_at,
        policy=resolve_retention_policy(container.settings),
        batch_size=DEFAULT_PURGE_BATCH_SIZE,
    )
    report, error_code = _unpack(outcome, ran_at=ran_at)
    tally = await _delete_objects(container, report.storage_keys)
    duration_ms = int((time.monotonic() - started) * 1000)

    await _record(
        container,
        report=report,
        trigger=resolved_trigger,
        tally=tally,
        duration_ms=duration_ms,
        triggered_by_username=triggered_by_username,
        error_code=error_code,
    )
    summary = _summary(
        report=report,
        trigger=resolved_trigger,
        tally=tally,
        duration_ms=duration_ms,
        error_code=error_code,
    )
    _LOG.info("retention sweep finished", extra=summary)
    return summary


def _unpack(outcome: Result[PurgeReport], *, ran_at: datetime) -> tuple[PurgeReport, str | None]:
    """The report, or an all-zero stand-in plus the error code that produced it.

    A failed sweep still gets a row, so it still needs a report shape to build one from.
    The zeros are the truth — nothing was purged — and ``error_code`` is what says why,
    which is the difference between "the clocks had nothing due" and "the clocks did not
    run".
    """
    if is_err(outcome):
        _LOG.error("the retention purge failed", extra=outcome.error.to_log_dict())
        zeroed = PurgeReport(ran_at=ran_at, batch_size=DEFAULT_PURGE_BATCH_SIZE)
        return zeroed, str(outcome.error.error_code)
    return outcome.value, None


assert run_retention_sweep.__name__ == RETENTION_JOB_NAME, (
    "the enqueue name and the job function have drifted apart; ARQ would never dispatch"
)
