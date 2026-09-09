"""The nightly activity sample: what it measures, and what it refuses to invent.

``users.last_seen_at`` is a gauge that ``credits.touch`` overwrites in place, so the number
of people active on any past day is unrecoverable unless somebody keeps a sample. This
module asserts the four properties that make the kept samples worth keeping:

* the three windows are ROLLING and anchored on the instant passed in, never on a calendar
  boundary and never on the system clock;
* the day a sample is filed under is its UTC day, so a server in Asia/Tashkent cannot file a
  late-evening sample under tomorrow;
* a second run in one day writes NOTHING and says so, which is what stops a worker restarted
  at 06:00 re-anchoring the night's point by six hours;
* a day the job never ran is a HOLE — no row, and above all no zero row, because a
  zero-filled gap is a fabricated measurement wearing a chart line.

The hole is then asserted a SECOND time, on the way out: ``overview.activity_history`` is
the only reader of this table other than the existence probe, and a gap the writer left is
only worth leaving if the read does not quietly fill it in. Those tests live here rather
than beside the other admin reads because the guarantee is one guarantee — a night nobody
measured has no row and therefore no point — and splitting its two halves across two files
is how one half comes to be changed without the other.

The last of those is the null-never-zero rule applied to a SERIES rather than to a column,
and the guard for it here is not nullability but the ABSENCE of a default: the five count
columns are ``NOT NULL`` with no ``default`` and no ``server_default``, so a future
contributor cannot make an INSERT convenient by giving one a zero. ``generation_attempts``
is what happens when somebody does.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import pytest
import sqlalchemy as sa
from sqlalchemy.dialects import sqlite
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from hbd.contracts import Language
from hbd.db.activity import ACTIVE_WINDOW_DAYS, ActivityCounts, measure_activity, record_snapshot
from hbd.db.admin.overview import activity_history, has_recorded_activity_history
from hbd.db.admin.sql import SeriesGrain, TimeWindow
from hbd.db.admin.views import ActivityPoint
from hbd.db.credits import set_blocked, touch
from hbd.db.models.user_activity_snapshot import UserActivitySnapshotRow

pytestmark = pytest.mark.anyio

#: Mid-day, so nothing below can pass by landing on a boundary it did not mean to.
_NOW: datetime = datetime(2026, 9, 8, 12, 0, tzinfo=UTC)

#: The five count columns, in the order they appear on the row. Named once so the
#: no-default guard below cannot silently stop covering one that was added later.
_COUNT_COLUMNS: tuple[str, ...] = (
    "total_accounts",
    "blocked_accounts",
    "active_24h_accounts",
    "active_7d_accounts",
    "active_30d_accounts",
)


async def _seen(
    sessions: async_sessionmaker[AsyncSession], *, who: int, ago: timedelta, now: datetime = _NOW
) -> None:
    """One account whose last inbound update was ``ago`` before ``now``.

    Written through ``credits.touch`` rather than by inserting a row by hand: the whole
    premise of this table is that it samples what the REAL liveness writer left behind, and
    a test that seeded the column directly would keep passing if that writer changed.
    """
    async with sessions.begin() as session:
        await touch(session, telegram_user_id=who, ui_language=Language.UZ_LATN, now=now - ago)


async def _snapshots(
    sessions: async_sessionmaker[AsyncSession],
) -> list[UserActivitySnapshotRow]:
    async with sessions() as session:
        rows = await session.scalars(
            sa.select(UserActivitySnapshotRow).order_by(UserActivitySnapshotRow.snapshot_date)
        )
        return list(rows)


async def _measure_and_file(
    sessions: async_sessionmaker[AsyncSession], *, at: datetime
) -> tuple[ActivityCounts, bool]:
    """One night's work end to end, in one transaction, exactly as the job does it."""
    async with sessions.begin() as session:
        counts = await measure_activity(session, at=at)
        written = await record_snapshot(session, day=at.date(), at=at, counts=counts)
    return counts, written


# ---------------------------------------------------------------------------
# What a sample measures
# ---------------------------------------------------------------------------
async def test_the_active_windows_are_measured_against_the_snapshot_instant(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    # Arrange — four accounts, one inside each window and one outside them all. The 25-hour
    # account is the one that proves the day window is 24 rolling hours rather than "today".
    await _seen(sessions, who=90_001, ago=timedelta(hours=1))
    await _seen(sessions, who=90_002, ago=timedelta(hours=25))
    await _seen(sessions, who=90_003, ago=timedelta(days=8))
    await _seen(sessions, who=90_004, ago=timedelta(days=40))

    # Act
    async with sessions() as session:
        counts = await measure_activity(session, at=_NOW)

    # Assert — nested by construction: everyone in ``active_24h`` is in ``active_7d`` too.
    # The 40-day account exists and is active in none of the three, which is the honest
    # shape of a population with a long tail.
    assert (counts.total, counts.active_24h, counts.active_7d, counts.active_30d) == (4, 1, 2, 3)


async def test_the_windows_move_with_the_instant_and_not_with_the_wall_clock(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    # Arrange — one account seen an hour before ``_NOW``.
    await _seen(sessions, who=90_010, ago=timedelta(hours=1))

    # Act — the same population, sampled two days later.
    async with sessions() as session:
        today = await measure_activity(session, at=_NOW)
        in_two_days = await measure_activity(session, at=_NOW + timedelta(days=2))

    # Assert — the account leaves the 24-hour window purely because the anchor moved. This
    # is what makes ``taken_at`` load-bearing on the row rather than decorative: the counts
    # are meaningless without the instant they were computed against.
    assert today.active_24h == 1
    assert in_two_days.active_24h == 0
    assert in_two_days.active_7d == 1


async def test_a_blocked_account_is_counted_whether_or_not_it_is_active(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    # Arrange — two barred accounts at opposite ends of the activity range.
    await _seen(sessions, who=90_020, ago=timedelta(days=40))
    await _seen(sessions, who=90_021, ago=timedelta(hours=1))
    async with sessions.begin() as session:
        for who in (90_020, 90_021):
            await set_blocked(session, telegram_user_id=who, is_blocked=True, now=_NOW)

    # Act
    async with sessions() as session:
        counts = await measure_activity(session, at=_NOW)

    # Assert — ``blocked`` is a POPULATION fact and ``active_*`` is an ACTIVITY one. The two
    # columns are not entangled in either direction: a bar does not remove somebody from the
    # active count, and inactivity does not remove them from the blocked one.
    assert counts.blocked == 2
    assert counts.active_24h == 1
    assert counts.total == 2


async def test_the_declared_windows_are_the_ones_the_columns_are_named_for(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    # A drift guard rather than a behaviour test. ``ACTIVE_WINDOW_DAYS`` is the SHAPE of a
    # stored series: changing a member silently redefines every historical row it is charted
    # against, and the column names would then be lying about what they hold.
    assert ACTIVE_WINDOW_DAYS == (1, 7, 30)


# ---------------------------------------------------------------------------
# Which day a sample is filed under
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    ("taken_at", "expected"),
    [
        (datetime(2026, 9, 8, 23, 59, tzinfo=UTC), date(2026, 9, 8)),
        (datetime(2026, 9, 9, 0, 1, tzinfo=UTC), date(2026, 9, 9)),
    ],
)
async def test_the_snapshot_date_is_the_utc_day_of_the_sample_and_never_the_local_one(
    sessions: async_sessionmaker[AsyncSession], taken_at: datetime, expected: date
) -> None:
    # Arrange / Act — the UtcDay trap in its WRITER form. A server set to Asia/Tashkent is
    # five hours ahead, so a 23:59 UTC sample is tomorrow locally; filing it under tomorrow
    # would put two samples in one day and none in another.
    _, written = await _measure_and_file(sessions, at=taken_at)

    # Assert
    assert written is True
    rows = await _snapshots(sessions)
    assert [row.snapshot_date for row in rows] == [expected]


async def test_the_anchor_offset_records_an_off_schedule_sample(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    # Arrange — the routine 00:07 run, and a run that limped in at 16:00 after an outage.
    await _measure_and_file(sessions, at=datetime(2026, 9, 8, 0, 7, tzinfo=UTC))
    await _measure_and_file(sessions, at=datetime(2026, 9, 9, 16, 0, tzinfo=UTC))

    # Act
    rows = await _snapshots(sessions)

    # Assert — the second point is anchored sixteen hours into its day and says so, so a
    # reader sees a late sample instead of guessing at a step in the line.
    assert [row.anchor_offset_s for row in rows] == [7 * 60, 16 * 60 * 60]


# ---------------------------------------------------------------------------
# Idempotence, and the gap
# ---------------------------------------------------------------------------
async def test_a_second_snapshot_for_the_same_day_writes_nothing_and_says_so(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    # Arrange — the 00:07 cron ran and measured an empty population.
    first_at = datetime(2026, 9, 8, 0, 7, tzinfo=UTC)
    _, first_written = await _measure_and_file(sessions, at=first_at)
    assert first_written is True

    # Act — a worker restarted at 16:00 the same UTC day, by which time three people have
    # arrived. This is the run that must not re-anchor the day.
    for index in range(3):
        await _seen(sessions, who=90_030 + index, ago=timedelta(hours=1))
    _, second_written = await _measure_and_file(
        sessions, at=datetime(2026, 9, 8, 16, 0, tzinfo=UTC)
    )

    # Assert — first write wins, in the database and not in a branch. The row still carries
    # the 00:07 anchor and the counts taken at 00:07; the boolean is how the job knows to log
    # "already recorded" rather than "recorded".
    assert second_written is False
    rows = await _snapshots(sessions)
    assert len(rows) == 1
    assert rows[0].taken_at == first_at
    assert rows[0].total_accounts == 0
    assert rows[0].active_24h_accounts == 0


async def test_a_day_the_job_never_ran_is_a_hole_and_not_a_zero(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    # Arrange — the worker was down on the 9th.
    await _seen(sessions, who=90_040, ago=timedelta(hours=1))
    await _measure_and_file(sessions, at=datetime(2026, 9, 8, 0, 7, tzinfo=UTC))
    await _measure_and_file(sessions, at=datetime(2026, 9, 10, 0, 7, tzinfo=UTC))

    # Act
    rows = await _snapshots(sessions)

    # Assert — exactly two points, oldest first, and the missing day is ABSENT rather than
    # present with zeroes. A zero-filled 9th would say nobody used the bot that day, which
    # is a measurement nobody took.
    assert [row.snapshot_date for row in rows] == [date(2026, 9, 8), date(2026, 9, 10)]
    assert date(2026, 9, 9) not in {row.snapshot_date for row in rows}
    assert all(row.total_accounts == 1 for row in rows)


async def test_the_series_is_stored_oldest_first_and_starts_empty(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    # Arrange / Act — the pre-history state a panel must render as "the series starts
    # tonight" rather than as a flat zero line.
    async with sessions() as session:
        before = await has_recorded_activity_history(session)
    await _measure_and_file(sessions, at=datetime(2026, 9, 10, 0, 7, tzinfo=UTC))
    await _measure_and_file(sessions, at=datetime(2026, 9, 8, 0, 7, tzinfo=UTC))
    async with sessions() as session:
        after = await has_recorded_activity_history(session)

    # Assert — the capability flips on the first row, whatever order the days arrived in,
    # and the stored series orders by date rather than by insertion.
    assert (before, after) == (False, True)
    assert [row.snapshot_date for row in await _snapshots(sessions)] == [
        date(2026, 9, 8),
        date(2026, 9, 10),
    ]


# ---------------------------------------------------------------------------
# Reading the series back — ``overview.activity_history``
# ---------------------------------------------------------------------------


def _point_counts(series: tuple[ActivityPoint, ...]) -> list[tuple[int, int, int]]:
    """The measurements alone, with the bucket keys stripped off."""
    return [(point.day, point.week, point.month) for point in series]


async def test_a_series_read_before_the_first_night_is_empty_and_not_a_flat_zero_line(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    # Arrange — accounts exist and are active; what does not exist is any HISTORY of them.
    # This is every deployment's first day, and the two facts must stay separable: the live
    # gauge (`active_accounts`) answers fine, the series has nothing to draw yet.
    await _seen(sessions, who=90_050, ago=timedelta(hours=1))

    # Act
    async with sessions() as session:
        series = await activity_history(session)

    # Assert — an empty tuple, not a point per day of some range this layer was never told
    # about. A zero line here would report an idle bot on the busiest day it has had.
    assert series == ()


async def test_a_night_with_no_snapshot_is_missing_from_the_series_and_never_a_zero_point(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    # Arrange — the writer's hole, seen from the reader's side: the worker was down on the
    # 9th, and one account was active throughout.
    await _seen(sessions, who=90_051, ago=timedelta(hours=1))
    await _measure_and_file(sessions, at=datetime(2026, 9, 8, 0, 7, tzinfo=UTC))
    await _measure_and_file(sessions, at=datetime(2026, 9, 10, 0, 7, tzinfo=UTC))

    # Act — asked for the whole span, gap included.
    async with sessions() as session:
        series = await activity_history(
            session,
            window=TimeWindow(
                start=datetime(2026, 9, 8, tzinfo=UTC), end=datetime(2026, 9, 11, tzinfo=UTC)
            ),
        )

    # Assert — two points for three days, oldest first. The read does not zero-fill the 9th
    # and it does not interpolate between its neighbours either: both would put a fabricated
    # measurement on a chart line, and the values that would have answered the 9th are gone
    # because `last_seen_at` was overwritten. What the gap RENDERS as is the API layer's
    # decision — it is the layer that knows the requested range — and the honest input to
    # that decision is a tuple with nothing in it for the 9th.
    assert [point.bucket for point in series] == ["2026-09-08", "2026-09-10"]
    assert "2026-09-09" not in {point.bucket for point in series}


async def test_each_point_carries_the_three_nested_cutoffs_under_the_names_the_tiles_use(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    # Arrange — one account inside each of the three rolling windows, so all three counts
    # differ and a column mapped onto the wrong field cannot pass by coincidence.
    await _seen(sessions, who=90_060, ago=timedelta(hours=1))
    await _seen(sessions, who=90_061, ago=timedelta(days=3))
    await _seen(sessions, who=90_062, ago=timedelta(days=20))
    await _measure_and_file(sessions, at=_NOW)

    # Act
    async with sessions() as session:
        (point,) = await activity_history(session)

    # Assert — `day`/`week`/`month` are `active_24h`/`active_7d`/`active_30d`, in that order,
    # and they are NESTED cutoffs on one population rather than three disjoint buckets. The
    # nesting is what forbids stacking or summing them: 1 + 2 + 3 is 6, which is twice the
    # accounts that exist, and no query can reproduce it.
    assert (point.day, point.week, point.month) == (1, 2, 3)
    assert point.day <= point.week <= point.month


async def test_the_bucket_key_is_the_utc_day_and_started_at_is_its_midnight(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    # Arrange — a sample taken sixteen hours into its day, after an outage. The key must be
    # the day, and the instant beside it must be that day's start rather than the sample's.
    await _measure_and_file(sessions, at=datetime(2026, 9, 9, 16, 0, tzinfo=UTC))

    # Act
    async with sessions() as session:
        (point,) = await activity_history(session)

    # Assert — the text the grouping used travels to the wire, and `started_at` is its exact
    # inverse: aware, UTC, midnight. A naive datetime here is the bug `bucket_started_at`
    # exists to prevent, so the tzinfo is asserted and not only the wall clock.
    assert point.bucket == "2026-09-09"
    assert point.started_at == datetime(2026, 9, 9, 0, 0, tzinfo=UTC)
    assert point.started_at.tzinfo is not None


async def test_the_window_narrows_on_the_instant_sampled_and_not_on_the_day_it_is_filed_under(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    # Arrange — the routine 00:07 run on the 8th, and a run that limped in at 16:00 on the
    # 9th. Both are filed under their own UTC day; only their `taken_at` tells them apart
    # inside a day.
    await _measure_and_file(sessions, at=datetime(2026, 9, 8, 0, 7, tzinfo=UTC))
    await _measure_and_file(sessions, at=datetime(2026, 9, 9, 16, 0, tzinfo=UTC))
    morning = TimeWindow(
        start=datetime(2026, 9, 9, 0, 0, tzinfo=UTC), end=datetime(2026, 9, 9, 12, 0, tzinfo=UTC)
    )
    afternoon = TimeWindow(
        start=datetime(2026, 9, 9, 12, 0, tzinfo=UTC), end=datetime(2026, 9, 10, 0, 0, tzinfo=UTC)
    )

    # Act
    async with sessions() as session:
        before_noon = await activity_history(session, window=morning)
        after_noon = await activity_history(session, window=afternoon)

    # Assert — the window is a pair of INSTANTS, so it is compared against `taken_at` even
    # though `snapshot_date` is the indexed column. Comparing an instant against a DATE means
    # a cast Postgres resolves through the session `TimeZone`, which is the trap `UtcDay`
    # exists to close: on a server set to Asia/Tashkent it would admit or drop the boundary
    # day. Here the late sample is simply not in the morning, on either dialect.
    assert before_noon == ()
    assert [point.bucket for point in after_noon] == ["2026-09-09"]


async def test_the_hour_grain_rekeys_the_same_nightly_samples_and_interpolates_nothing(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    # Arrange — two nights, one of them anchored late.
    await _seen(sessions, who=90_070, ago=timedelta(hours=1))
    await _measure_and_file(sessions, at=datetime(2026, 9, 8, 0, 7, tzinfo=UTC))
    await _measure_and_file(sessions, at=datetime(2026, 9, 9, 16, 0, tzinfo=UTC))

    # Act
    async with sessions() as session:
        hourly = await activity_history(session, grain=SeriesGrain.HOUR)
        daily = await activity_history(session)

    # Assert — HOUR is accepted rather than refused, and it is honest precisely because it is
    # nearly pointless: the same two samples under finer keys, at the hour each was actually
    # taken. It does not manufacture the other forty hours between them, and the point count
    # is unchanged — a finer grain over a source with one row a night can only ever re-label.
    assert [point.bucket for point in hourly] == ["2026-09-08T00", "2026-09-09T16"]
    assert _point_counts(hourly) == _point_counts(daily)
    assert hourly[1].started_at == datetime(2026, 9, 9, 16, 0, tzinfo=UTC)


# ---------------------------------------------------------------------------
# The schema guard
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("column_name", _COUNT_COLUMNS)
def test_the_count_columns_carry_no_default_of_any_kind(column_name: str) -> None:
    # The null-never-zero rule in the form THIS table needs. The hazard here is not
    # nullability — a count that was taken is always a real number — it is a DEFAULT: give
    # one of these a ``default=0`` to make an INSERT convenient and a half-written row
    # becomes an authoritative "nobody was here". That is exactly what turned
    # ``generation_attempts.cost_usd`` unreadable.
    column = UserActivitySnapshotRow.__table__.c[column_name]
    assert column.nullable is False
    assert column.default is None
    assert column.server_default is None


def test_the_snapshot_day_is_unique_so_a_rerun_cannot_double_file() -> None:
    # The idempotence asserted above is bought by this constraint and by nothing in Python:
    # ``record_snapshot`` writes through ``insert_or_ignore``, and with the constraint gone
    # the ignore has nothing to fire on, so every test in the previous section would keep
    # passing while a restart silently re-anchored the night's point.
    #
    # The assertion is on the COLUMN SET rather than on the name, because the two names
    # legitimately differ: the model spells the constraint ``snapshot_date`` (a
    # ``UniqueConstraint`` given an explicit name bypasses ``NAMING_CONVENTION``, whose
    # ``uq`` template is keyed on ``%(column_0_N_name)s`` and only fires for an UNNAMED one),
    # while revision 0018 writes ``op.f("uq_user_activity_snapshots_snapshot_date")``. What
    # has to hold for the idempotence is that exactly one unique constraint covers exactly
    # ``snapshot_date``, on either path into the schema, and that is what is checked.
    table = UserActivitySnapshotRow.__table__
    assert isinstance(table, sa.Table)
    unique = [
        constraint
        for constraint in table.constraints
        if isinstance(constraint, sa.UniqueConstraint)
    ]
    assert [tuple(constraint.columns.keys()) for constraint in unique] == [("snapshot_date",)]
    ddl = str(sa.schema.CreateTable(table).compile(dialect=sqlite.dialect()))
    assert "UNIQUE (snapshot_date)" in ddl
