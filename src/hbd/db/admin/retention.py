"""Reads and writes against ``purge_runs`` — what ``GET /api/retention`` is built from.

Two questions, and they are genuinely different:

* **What did the last runs do?** Answered from stored rows, because a log line is not
  evidence and a sweep that ran and did nothing must be distinguishable from a scheduler
  that stopped firing. :func:`recent_runs`.
* **How far behind is the sweep right now?** Answered by counting, live, against the same
  predicates the sweep itself uses. :func:`rows_past_expiry`. This is the number that
  drives the panel's "run again" affordance, and it is deliberately not derived from the
  last run's counts: ``has_work_remaining`` says only "a batch came back full", which
  answers *whether* to run again and never *how far behind* anything is.

The predicates come from :func:`hbd.db.purge.rows_past_expiry_statements`, not from a copy
here. A counted backlog that disagreed with what the sweep actually touches would be worse
than no number at all — it would be a dashboard confidently reporting a clean schedule over
rows nobody is deleting.

Module-level functions taking an ``AsyncSession``, nothing commits: the same contract the
rest of ``hbd.db.admin`` keeps, so a request that writes a run record and then fails to
write its audit row leaves neither.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Final

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from hbd.db.enums import PurgeTrigger
from hbd.db.models.purge_run import PurgeRunRow
from hbd.db.purge import PurgeReport, rows_past_expiry_statements
from hbd.db.retention import DEFAULT_RETENTION_POLICY, RetentionPolicy

__all__ = [
    "DEFAULT_RUN_HISTORY",
    "MAX_RUN_HISTORY",
    "RetentionOverview",
    "record_run",
    "recent_runs",
    "rows_past_expiry",
    "overview",
]

#: How many runs the panel shows without asking for more. An hourly cron fills a day.
DEFAULT_RUN_HISTORY: Final[int] = 24
#: The ceiling a caller-supplied limit is clamped to, so a query string cannot ask for the
#: whole table. Validation belongs at the boundary; this is the backstop behind it.
MAX_RUN_HISTORY: Final[int] = 200


@dataclass(frozen=True, slots=True)
class RetentionOverview:
    """Everything ``GET /api/retention`` renders, in one round of queries.

    ``runs`` is newest-first. ``rows_past_expiry`` is ``(PurgeReport field name, count)``
    in sweep order, so a serializer can line the live backlog up against the last run's
    own counts without a translation table between them.
    """

    runs: tuple[PurgeRunRow, ...]
    rows_past_expiry: tuple[tuple[str, int], ...]

    @property
    def last_run(self) -> PurgeRunRow | None:
        return self.runs[0] if self.runs else None

    @property
    def total_rows_past_expiry(self) -> int:
        return sum(count for _, count in self.rows_past_expiry)

    @property
    def is_batch_full(self) -> bool:
        """The last run's own verdict. ``False`` when no run has ever been recorded."""
        last = self.last_run
        return last is not None and last.is_batch_full


async def record_run(
    session: AsyncSession,
    *,
    report: PurgeReport,
    trigger: PurgeTrigger,
    duration_ms: int,
    storage_keys_deleted: int,
    storage_delete_failures: int,
    triggered_by_username: str | None = None,
    error_code: str | None = None,
) -> PurgeRunRow:
    """Write one sweep's record. The row is written for a FAILED run too.

    ``storage_keys_deleted`` is passed in rather than derived from ``report`` because only
    the caller knows it: :func:`hbd.db.purge.purge_expired` hands back keys and the job
    deletes the objects afterwards, so the two numbers are produced by two different
    components and a mismatch between them is the whole point of storing both.
    """
    row = PurgeRunRow(
        ran_at=report.ran_at,
        trigger=trigger,
        triggered_by_username=triggered_by_username,
        duration_ms=duration_ms,
        assets_deleted=report.assets_deleted,
        brief_notes_purged=report.brief_notes_purged,
        brief_identities_purged=report.brief_identities_purged,
        attempt_identities_purged=report.attempt_identities_purged,
        attempt_transcripts_purged=report.attempt_transcripts_purged,
        name_records_deleted=report.name_records_deleted,
        abandoned_orders_deleted=report.abandoned_orders_deleted,
        audit_reasons_purged=report.audit_reasons_purged,
        audit_rows_deleted=report.audit_rows_deleted,
        admin_sessions_deleted=report.admin_sessions_deleted,
        purge_runs_deleted=report.purge_runs_deleted,
        storage_keys_returned=len(report.storage_keys),
        storage_keys_deleted=storage_keys_deleted,
        storage_delete_failures=storage_delete_failures,
        batch_size=report.batch_size,
        is_batch_full=report.has_work_remaining,
        error_code=error_code,
    )
    session.add(row)
    # Flushed, not committed: the caller owns the transaction, and a caller that wants to
    # log the row's id must be able to read it back before that transaction closes.
    await session.flush()
    return row


async def recent_runs(
    session: AsyncSession, *, limit: int = DEFAULT_RUN_HISTORY
) -> tuple[PurgeRunRow, ...]:
    """The last ``limit`` sweeps, newest first. Bounded, never a full-table read."""
    bounded = max(1, min(limit, MAX_RUN_HISTORY))
    statement = sa.select(PurgeRunRow).order_by(PurgeRunRow.ran_at.desc()).limit(bounded)
    return tuple((await session.execute(statement)).scalars().all())


async def rows_past_expiry(
    session: AsyncSession,
    *,
    now: datetime,
    policy: RetentionPolicy = DEFAULT_RETENTION_POLICY,
) -> tuple[tuple[str, int], ...]:
    """How many rows each clock is due to touch RIGHT NOW, unbounded by ``batch_size``.

    One ``COUNT`` per clock rather than one wide query: the predicates span five tables and
    a union of counts over unrelated tables is a query nobody can read and no index helps.
    """
    counted: list[tuple[str, int]] = []
    for name, statement in rows_past_expiry_statements(now=now, policy=policy):
        counted.append((name, (await session.execute(statement)).scalar_one()))
    return tuple(counted)


async def overview(
    session: AsyncSession,
    *,
    now: datetime,
    policy: RetentionPolicy = DEFAULT_RETENTION_POLICY,
    limit: int = DEFAULT_RUN_HISTORY,
) -> RetentionOverview:
    """The whole ``GET /api/retention`` payload, so the router holds no query logic."""
    return RetentionOverview(
        runs=await recent_runs(session, limit=limit),
        rows_past_expiry=await rows_past_expiry(session, now=now, policy=policy),
    )
