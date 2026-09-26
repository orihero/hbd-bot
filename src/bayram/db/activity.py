"""The nightly activity sample: five counts over the whole account population, once a day.

``users.last_seen_at`` is a GAUGE. ``credits.touch`` UPSERTs it in place through
``bot/gate.py``'s ``TouchDrain``, so the value that would have answered "how many people were
active last Tuesday" was written over on Wednesday. Nothing in this schema can reconstruct
that series and nothing ever could. This module is the one writer that gives it a past, by
sampling the gauge every night and keeping the sample.

**THE COUNTS ARE ROLLING WINDOWS, SAMPLED DAILY — NOT CALENDAR-DAY DISTINCT USERS.** Active
means ``last_seen_at >= taken_at - N days``, evaluated in ONE statement at the instant the
job runs, which is why every count on a row shares one anchor and why that anchor is stored
beside them. Calendar-day DAU is unobtainable here at any grain: a customer active on Monday
and again on Tuesday leaves no trace of Monday. The names ``active_24h`` / ``active_7d`` /
``active_30d`` are load-bearing, and a serializer that renames one ``dau`` reintroduces
exactly the confusion the model's naming was chosen to prevent.

**ONE STATEMENT, NOT FIVE.** All five counts come from a single ``SELECT`` over ``users``, so
they are consistent with each other and with the one ``taken_at`` the row records. Five
separate statements would let an account arrive between the second and the third and produce
a row whose ``active_7d`` was smaller than its ``active_24h`` — an impossible shape that a
chart would render as a real event.

**RE-RUNNING A DAY IS A NO-OP, ENFORCED BY THE DATABASE.** :func:`record_snapshot` writes
through ``insert_or_ignore`` against ``uq_user_activity_snapshots_snapshot_date``, so a
worker restarted at 06:00 after the 00:07 cron already ran does not silently re-anchor that
day's measurement by six hours. The boolean it returns says which of the two happened, and
the job logs it, because "the snapshot was already there" and "the snapshot was written" are
different facts about a night and only one of them is worth investigating.

**NO ZERO-FILL, EVER.** A day the worker was down produces NO ROW. The null-never-zero rule
governs the SERIES here and not only the columns: a zero-filled gap would report that nobody
used the bot that day, which is a fabricated measurement wearing a chart line. The read layer
returns the days it has and the panel renders the rest as absent.

**NOTHING HERE NARROWS TO A PERSON.** Every value this module computes is a count over the
entire population and no statement selects a ``telegram_user_id``. That is the structural
reason ``user_activity_snapshots`` can sit in neither privacy set, and it is a property of
the queries below as much as of the columns they write.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any, Final

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from bayram.db.credit_sql import insert_or_ignore
from bayram.db.models.user import UserRow
from bayram.db.models.user_activity_snapshot import UserActivitySnapshotRow

__all__ = ["ACTIVE_WINDOW_DAYS", "ActivityCounts", "measure_activity", "record_snapshot"]

#: The three rolling windows the row carries, in days, in the order the columns appear.
#: Constants here rather than in ``Settings`` deliberately: they are the SHAPE of a stored
#: series, not an operator knob. Changing one silently redefines every historical row it is
#: charted against, which is a migration-shaped decision and not an environment variable.
ACTIVE_WINDOW_DAYS: Final[tuple[int, int, int]] = (1, 7, 30)


@dataclass(frozen=True, slots=True)
class ActivityCounts:
    """One night's five numbers, all measured at the same instant.

    :attr:`blocked` is the OPERATOR-set bar (``users.is_blocked``) and is **not churn**. A
    customer blocking the BOT is ``users.blocked_bot_at`` and ``bot_membership_events``;
    reporting operator moderation as customer churn would be a category error on a card an
    operator reads to decide whether the product is losing people.
    """

    total: int
    blocked: int
    active_24h: int
    active_7d: int
    active_30d: int


def _active_within(days: int, at: datetime) -> sa.ColumnElement[bool]:
    """The rolling-window predicate, spelled once so all three windows agree."""
    return UserRow.last_seen_at >= at - timedelta(days=days)


def _counted(condition: sa.ColumnElement[bool]) -> sa.ColumnElement[int]:
    """``COUNT`` of the rows matching ``condition``.

    ``count(CASE WHEN … THEN 1 END)`` rather than ``count(*) FILTER (WHERE …)``: the FILTER
    clause is Postgres-and-modern-SQLite only, and this project's unit suite runs on SQLite
    while production runs on Postgres, so a construct one of them may not have is a schema
    nobody can test. It also returns 0 rather than NULL on an empty table, which a
    ``SUM`` would not, and a coalesce over a genuine count is exactly the smoothing this
    codebase refuses everywhere else.
    """
    return sa.func.count(sa.case((condition, 1)))


async def measure_activity(session: AsyncSession, *, at: datetime) -> ActivityCounts:
    """Take one sample of the whole population, in one statement, anchored at ``at``.

    ``at`` is passed rather than read from the clock inside the query so the anchor the row
    stores is the anchor the windows were computed against — the two cannot drift by the
    duration of the statement, and a test can move time without moving the database's.
    """
    day, week, month = ACTIVE_WINDOW_DAYS
    row = (
        await session.execute(
            sa.select(
                sa.func.count(),
                _counted(UserRow.is_blocked.is_(True)),
                _counted(_active_within(day, at)),
                _counted(_active_within(week, at)),
                _counted(_active_within(month, at)),
            ).select_from(UserRow)
        )
    ).one()
    return ActivityCounts(
        total=int(row[0]),
        blocked=int(row[1]),
        active_24h=int(row[2]),
        active_7d=int(row[3]),
        active_30d=int(row[4]),
    )


async def record_snapshot(
    session: AsyncSession, *, day: date, at: datetime, counts: ActivityCounts
) -> bool:
    """File one sample under ``day``. ``True`` when THIS call wrote it.

    ``False`` means a row for that UTC day already existed and this one was ignored — the
    idempotency the model's unique constraint exists for, and the reason a re-run cannot
    re-anchor a day that has already been measured. The caller reports which happened rather
    than treating one as an error: a second run in a day is a restart, not a fault.
    """
    values: dict[str, Any] = {
        "snapshot_date": day,
        "taken_at": at,
        "total_accounts": counts.total,
        "blocked_accounts": counts.blocked,
        "active_24h_accounts": counts.active_24h,
        "active_7d_accounts": counts.active_7d,
        "active_30d_accounts": counts.active_30d,
        "created_at": at,
    }
    return await insert_or_ignore(
        session, UserActivitySnapshotRow, values, index_elements=["snapshot_date"]
    )
