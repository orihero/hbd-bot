"""``has_work_remaining``, the sweep's own sweep, and the queries ``/retention`` reads.

Three separate things, all of them shipped in the slice that made the purge job run:

* :class:`hbd.db.purge.PurgeReport`'s ``has_work_remaining`` used to be
  ``total_rows_affected > 0``, which is a different predicate wearing that name's
  docstring. The tests below pin the real meaning — a batch came back FULL — from both
  sides, because a property that is always true and a property that is always false both
  pass a single-sided test.
* ``purge_runs`` is swept by the run it records, or the bookkeeping outgrows the data.
* ``rows_past_expiry`` is the backlog number the panel shows, and it is counted from the
  SAME predicates the sweep uses. A count that drifts from the sweep is a dashboard
  confidently reporting a clean schedule over rows nobody is deleting.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from hbd.contracts import OrderState, is_ok
from hbd.db.admin import retention as retention_queries
from hbd.db.enums import PurgeTrigger
from hbd.db.models.purge_run import PurgeRunRow
from hbd.db.purge import (
    DEFAULT_PURGE_BATCH_SIZE,
    PURGE_RUN_RETENTION_DAYS,
    PurgeReport,
    purge_expired,
)
from hbd.db.repository import SqlKitRepository
from tests.test_db.conftest import MovableClock, build_kit, new_order

_A_YEAR = 365
#: Any aware instant. The report tests are pure arithmetic; the value is irrelevant,
#: the tzinfo is not — ``UtcDateTime`` rejects naive datetimes at every boundary.
_AWARE: datetime = datetime(2026, 1, 1, tzinfo=UTC)


async def _delivered_paid_kit(
    repository: SqlKitRepository, tmp_path: Path, clock: MovableClock
) -> None:
    """One paid order with a five-asset kit, so a sweep has something to fill a batch with."""
    order = new_order(state=OrderState.BRIEF_READY)
    await repository.create_order(order)
    await repository.set_order_state(order.id, OrderState.AUTHORIZED, now=clock.now)
    await repository.save_kit(build_kit(tmp_path, order.id))


def _run(ran_at: datetime, **overrides: object) -> PurgeRunRow:
    """A ``purge_runs`` row with every non-null column filled. Counts only, no personal data."""
    values: dict[str, object] = {
        "ran_at": ran_at,
        "trigger": PurgeTrigger.CRON,
        "duration_ms": 12,
        "assets_deleted": 0,
        "brief_notes_purged": 0,
        "brief_identities_purged": 0,
        "attempt_identities_purged": 0,
        "attempt_transcripts_purged": 0,
        "name_records_deleted": 0,
        "abandoned_orders_deleted": 0,
        "purge_runs_deleted": 0,
        "storage_keys_returned": 0,
        "storage_keys_deleted": 0,
        "storage_delete_failures": 0,
        "batch_size": DEFAULT_PURGE_BATCH_SIZE,
        "is_batch_full": False,
        "created_at": ran_at,
    }
    values.update(overrides)
    return PurgeRunRow(**values)


# ---------------------------------------------------------------------------
# has_work_remaining means what its docstring says
# ---------------------------------------------------------------------------
async def test_a_sweep_that_touched_fewer_rows_than_its_batch_reports_no_work_remaining(
    repository: SqlKitRepository,
    sessions: async_sessionmaker[AsyncSession],
    tmp_path: Path,
    clock: MovableClock,
) -> None:
    """Five assets against a batch of five hundred: work was done, and none is left."""
    # Arrange
    await _delivered_paid_kit(repository, tmp_path, clock)

    # Act
    result = await purge_expired(sessions, now=clock.advance(days=_A_YEAR + 1))

    # Assert — the old implementation returned True here, forever.
    assert is_ok(result)
    assert result.value.assets_deleted == 5
    assert result.value.total_rows_affected > 0
    assert result.value.has_work_remaining is False


async def test_a_sweep_that_filled_its_batch_reports_work_remaining(
    repository: SqlKitRepository,
    sessions: async_sessionmaker[AsyncSession],
    tmp_path: Path,
    clock: MovableClock,
) -> None:
    """Two assets against a batch of two: the LIMIT was hit, so more is due."""
    # Arrange
    await _delivered_paid_kit(repository, tmp_path, clock)

    # Act
    result = await purge_expired(sessions, now=clock.advance(days=_A_YEAR + 1), batch_size=2)

    # Assert
    assert is_ok(result)
    assert result.value.batch_size == 2
    assert result.value.assets_deleted == 2
    assert result.value.has_work_remaining is True


def test_one_saturated_sweep_is_enough_even_when_every_other_clock_was_idle() -> None:
    """The counts are compared one by one, not summed: a sum would mask a full table."""
    # Arrange / Act
    report = PurgeReport(
        ran_at=_AWARE,
        batch_size=3,
        assets_deleted=0,
        brief_notes_purged=3,
    )

    # Assert
    assert report.total_rows_affected == 3
    assert report.has_work_remaining is True


def test_an_idle_sweep_reports_no_work_remaining() -> None:
    # Arrange / Act
    report = PurgeReport(ran_at=_AWARE, batch_size=3)

    # Assert — zero is not "a full batch", however small the batch.
    assert report.total_rows_affected == 0
    assert report.has_work_remaining is False


# ---------------------------------------------------------------------------
# The sweep sweeps its own records
# ---------------------------------------------------------------------------
async def test_purge_run_records_older_than_a_year_are_deleted(
    sessions: async_sessionmaker[AsyncSession], clock: MovableClock
) -> None:
    # Arrange — one just inside the window, one just outside it.
    now = clock.now
    async with sessions.begin() as session:
        session.add(_run(now - timedelta(days=PURGE_RUN_RETENTION_DAYS + 1)))
        session.add(_run(now - timedelta(days=PURGE_RUN_RETENTION_DAYS - 1)))

    # Act
    result = await purge_expired(sessions, now=now)

    # Assert
    assert is_ok(result)
    assert result.value.purge_runs_deleted == 1
    async with sessions() as session:
        surviving = await session.scalar(sa.select(sa.func.count()).select_from(PurgeRunRow))
    assert surviving == 1


async def test_a_fresh_purge_run_record_is_left_alone(
    sessions: async_sessionmaker[AsyncSession], clock: MovableClock
) -> None:
    # Arrange
    async with sessions.begin() as session:
        session.add(_run(clock.now))

    # Act
    result = await purge_expired(sessions, now=clock.now)

    # Assert — a record that could still be shown on /retention must not vanish.
    assert is_ok(result)
    assert result.value.purge_runs_deleted == 0


# ---------------------------------------------------------------------------
# What GET /api/retention reads
# ---------------------------------------------------------------------------
async def test_recent_runs_come_back_newest_first_and_bounded(
    sessions: async_sessionmaker[AsyncSession], clock: MovableClock
) -> None:
    # Arrange
    async with sessions.begin() as session:
        for hours in range(5):
            session.add(_run(clock.now - timedelta(hours=hours), duration_ms=hours))

    # Act
    async with sessions() as session:
        runs = await retention_queries.recent_runs(session, limit=3)

    # Assert — newest first is what "the last run" on the panel means.
    assert [row.duration_ms for row in runs] == [0, 1, 2]


async def test_a_limit_of_zero_still_returns_something_rather_than_an_empty_page(
    sessions: async_sessionmaker[AsyncSession], clock: MovableClock
) -> None:
    """A query string cannot talk the panel into showing nothing, or into a table scan."""
    # Arrange
    async with sessions.begin() as session:
        session.add(_run(clock.now))

    # Act
    async with sessions() as session:
        floored = await retention_queries.recent_runs(session, limit=0)
        capped = await retention_queries.recent_runs(session, limit=10_000)

    # Assert
    assert len(floored) == 1
    assert len(capped) == 1


async def test_rows_past_expiry_counts_the_backlog_the_sweep_would_take(
    repository: SqlKitRepository,
    sessions: async_sessionmaker[AsyncSession],
    tmp_path: Path,
    clock: MovableClock,
) -> None:
    """The number the panel shows, counted from the sweep's OWN predicates."""
    # Arrange
    await _delivered_paid_kit(repository, tmp_path, clock)
    later = clock.advance(days=_A_YEAR + 1)

    # Act
    async with sessions() as session:
        before = dict(await retention_queries.rows_past_expiry(session, now=later))
    result = await purge_expired(sessions, now=later)
    async with sessions() as session:
        after = dict(await retention_queries.rows_past_expiry(session, now=later))

    # Assert — the backlog is exactly what the sweep then took, and it drains to zero.
    assert is_ok(result)
    assert before["assets_deleted"] == 5
    assert before["assets_deleted"] == result.value.assets_deleted
    assert after["assets_deleted"] == 0


async def test_the_backlog_keys_line_up_with_the_report_fields(
    sessions: async_sessionmaker[AsyncSession], clock: MovableClock
) -> None:
    """The panel zips the two together; a renamed field must break here, not in the UI."""
    # Act
    async with sessions() as session:
        counted = await retention_queries.rows_past_expiry(session, now=clock.now)

    # Assert
    assert [name for name, _ in counted] == [
        "assets_deleted",
        "brief_notes_purged",
        "brief_identities_purged",
        "attempt_identities_purged",
        "attempt_transcripts_purged",
        "name_records_deleted",
        "abandoned_orders_deleted",
        "audit_reasons_purged",
        "audit_rows_deleted",
        "admin_sessions_deleted",
        "purge_runs_deleted",
        "vendor_usage_deleted",
        "membership_events_deleted",
        "chat_bodies_purged",
        "chat_messages_deleted",
        "payme_rpc_rows_deleted",
        "payment_intents_deleted",
        "broadcast_recipients_deleted",
    ]
    assert {name for name, _ in counted} <= set(PurgeReport.model_fields)


async def test_the_overview_answers_every_question_the_panel_asks(
    sessions: async_sessionmaker[AsyncSession], clock: MovableClock
) -> None:
    # Arrange
    async with sessions.begin() as session:
        session.add(_run(clock.now - timedelta(hours=1)))
        session.add(_run(clock.now, is_batch_full=True, assets_deleted=500))

    # Act
    async with sessions() as session:
        view = await retention_queries.overview(session, now=clock.now)

    # Assert
    assert view.last_run is not None
    assert view.last_run.assets_deleted == 500
    assert view.is_batch_full is True
    assert view.total_rows_past_expiry == 0


async def test_an_overview_with_no_runs_at_all_is_not_a_crash(
    sessions: async_sessionmaker[AsyncSession], clock: MovableClock
) -> None:
    """The panel's first ever load, before the cron has fired once."""
    # Act
    async with sessions() as session:
        view = await retention_queries.overview(session, now=clock.now)

    # Assert
    assert view.runs == ()
    assert view.last_run is None
    assert view.is_batch_full is False


# ---------------------------------------------------------------------------
# Writing the record
# ---------------------------------------------------------------------------
async def test_a_recorded_run_keeps_returned_and_deleted_as_two_numbers(
    sessions: async_sessionmaker[AsyncSession], clock: MovableClock
) -> None:
    """Collapsing them would make an object-store leak arithmetically invisible."""
    # Arrange
    report = PurgeReport(
        ran_at=clock.now,
        batch_size=DEFAULT_PURGE_BATCH_SIZE,
        assets_deleted=3,
        storage_keys=("a", "b", "c"),
    )

    # Act
    async with sessions.begin() as session:
        row = await retention_queries.record_run(
            session,
            report=report,
            trigger=PurgeTrigger.USER_REQUEST,
            duration_ms=42,
            storage_keys_deleted=1,
            storage_delete_failures=2,
        )
        row_id = row.id

    # Assert
    async with sessions() as session:
        stored = await session.get(PurgeRunRow, row_id)
    assert stored is not None
    assert stored.trigger is PurgeTrigger.USER_REQUEST
    assert stored.storage_keys_returned == 3
    assert stored.storage_keys_deleted == 1
    assert stored.storage_delete_failures == 2
    assert stored.is_storage_leaking is True
    assert stored.duration_ms == 42
