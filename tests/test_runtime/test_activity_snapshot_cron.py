"""The nightly snapshot's HOST, and the entry point arq actually dispatches.

``tests/test_db/test_activity_snapshots.py`` proves the query and the writer are right. This
file proves they RUN, which is a different claim and the one that was false before this
work: ``cron_jobs`` is where a correct job goes to be dead code, and the retention sweep is
already on record as having spent a release with no caller at all.

Three things are asserted here that no test of ``bayram.db.activity`` can reach.

* The cron entry EXISTS, is named the string arq dispatches by, and carries the schedule the
  module documents. arq matches ``functions`` to ``cron_jobs`` by function NAME, so a rename
  on either side is a job that never fires and raises nothing while not firing.
* The real entry point, over a real container and a real database, writes the numbers the
  ``users`` table actually holds — and a second call the same UTC day writes nothing, does
  not error, and leaves the first sample where it was.
* A failure is REPORTED rather than raised into the scheduler, with one deliberate
  exception: a context with no container is a startup wiring bug, and swallowing that into a
  nightly silence is how a series stops without anybody noticing.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Final

import pytest
import sqlalchemy as sa

from bayram.config import ENV_PREFIX, Settings
from bayram.contracts import Language
from bayram.db.credits import touch
from bayram.db.models.user_activity_snapshot import UserActivitySnapshotRow
from bayram.errors import PipelineError
from bayram.runtime.activity_job import (
    ACTIVITY_SNAPSHOT_CRON_HOUR,
    ACTIVITY_SNAPSHOT_CRON_MINUTE,
    ACTIVITY_SNAPSHOT_JOB_NAME,
    record_activity_snapshot,
)
from bayram.runtime.container import AppContainer, build_container
from bayram.runtime.jobs import build_kit_worker_settings

pytestmark = pytest.mark.anyio

#: Just after midnight, where the cron actually fires, so ``anchor_offset_s`` on the row this
#: writes is the routine few-hundred rather than a number no production run would produce.
_MIDNIGHT_ISH: Final[datetime] = datetime(2026, 9, 8, 0, 7, tzinfo=UTC)


@pytest.fixture(autouse=True)
def _isolated_environment(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """A developer's own ``BAYRAM_`` variables must not decide what the shipped default is."""
    for name in tuple(os.environ):
        if name.startswith(ENV_PREFIX):
            monkeypatch.delenv(name, raising=False)
    yield


def _settings(tmp_path: Path, **overrides: Any) -> Settings:
    return Settings(
        _env_file=None,
        telegram_bot_token="t",
        database_url=f"sqlite+aiosqlite:///{tmp_path / 'snapshot.db'}",
        elevenlabs_api_key="k",
        llm_api_key="k",
        **overrides,
    )


async def _touch(container: AppContainer, *, who: int, at: datetime) -> None:
    """Make one account live, through the store the bot's gate actually drains into."""
    async with container.require_session_factory().begin() as session:
        await touch(session, telegram_user_id=who, ui_language=Language.UZ_LATN, now=at)


async def _snapshot_rows(container: AppContainer) -> list[UserActivitySnapshotRow]:
    async with container.require_session_factory()() as session:
        rows = await session.scalars(
            sa.select(UserActivitySnapshotRow).order_by(UserActivitySnapshotRow.taken_at)
        )
        return list(rows)


# ---------------------------------------------------------------------------
# The host
# ---------------------------------------------------------------------------
def test_the_snapshot_has_a_cron_to_run_on_at_all(tmp_path: Path) -> None:
    # Arrange — the defect this mirrors is the one ``retention_job`` was written to fix: a
    # job registered nowhere. ``build_kit_worker_settings`` is the only place that can be
    # wrong about it, so it is the thing under test rather than the module constant.
    async def _dependencies() -> dict[str, Any]:
        return {}

    # Act
    worker = build_kit_worker_settings(
        settings=_settings(tmp_path), build_dependencies=_dependencies
    )

    # Assert — the entry is there, named the string arq dispatches by, on the schedule the
    # module documents. ``max_tries=1`` because the unique constraint makes a duplicate
    # harmless and a retry ladder buys nothing; ``run_at_startup=False`` because a rolling
    # deploy would otherwise take one sample per replica.
    entry = next(job for job in worker.cron_jobs if job.name == ACTIVITY_SNAPSHOT_JOB_NAME)
    assert entry.coroutine is record_activity_snapshot
    assert entry.hour == ACTIVITY_SNAPSHOT_CRON_HOUR
    assert entry.minute == ACTIVITY_SNAPSHOT_CRON_MINUTE
    assert entry.max_tries == 1
    assert entry.unique is True
    assert entry.run_at_startup is False


def test_the_job_is_registered_under_the_name_the_cron_dispatches_by(tmp_path: Path) -> None:
    # arq resolves a cron entry to a coroutine through ``functions``, BY NAME. An entry whose
    # function is not in that list is a job that silently never runs, and the failure mode is
    # an empty series nobody is alerted about.
    async def _dependencies() -> dict[str, Any]:
        return {}

    worker = build_kit_worker_settings(
        settings=_settings(tmp_path), build_dependencies=_dependencies
    )

    assert record_activity_snapshot in worker.functions
    assert record_activity_snapshot.__name__ == ACTIVITY_SNAPSHOT_JOB_NAME


# ---------------------------------------------------------------------------
# The entry point, against a real container
# ---------------------------------------------------------------------------
async def test_the_cron_entry_point_writes_exactly_one_row_against_a_real_container(
    tmp_path: Path,
) -> None:
    # Arrange — a real container over SQLite, and three accounts made live through the real
    # liveness writer at three different distances from the sample instant.
    container = await build_container(
        _settings(tmp_path), data_root=tmp_path / "var", with_providers=False
    )
    try:
        await _touch(container, who=93_001, at=_MIDNIGHT_ISH - timedelta(hours=2))
        await _touch(container, who=93_002, at=_MIDNIGHT_ISH - timedelta(days=3))
        await _touch(container, who=93_003, at=_MIDNIGHT_ISH - timedelta(days=45))
        ctx: dict[str, Any] = {"container": container}

        # Act — the cron's own entry point, with the context arq hands it.
        summary = await record_activity_snapshot(ctx, now=_MIDNIGHT_ISH)

        # Assert — the numbers the ``users`` table actually holds reach the table, and the
        # summary carries them so an operator reading the log sees a night's work rather
        # than a bare "ok".
        assert summary["is_written"] is True
        assert summary["error"] is None
        assert summary["snapshot_date"] == "2026-09-08"
        assert summary["total_accounts"] == 3
        assert summary["active_24h_accounts"] == 1
        assert summary["active_7d_accounts"] == 2
        assert summary["active_30d_accounts"] == 2

        rows = await _snapshot_rows(container)
        assert len(rows) == 1
        assert rows[0].total_accounts == 3
        assert rows[0].active_24h_accounts == 1
    finally:
        await container.engine.dispose()


async def test_a_second_run_the_same_day_is_a_restart_and_not_a_second_sample(
    tmp_path: Path,
) -> None:
    # Arrange — the 00:07 cron ran and the worker was restarted two hours later.
    container = await build_container(
        _settings(tmp_path), data_root=tmp_path / "var", with_providers=False
    )
    try:
        ctx: dict[str, Any] = {"container": container}
        first = await record_activity_snapshot(ctx, now=_MIDNIGHT_ISH)
        assert first["is_written"] is True
        await _touch(container, who=93_010, at=_MIDNIGHT_ISH + timedelta(hours=1))

        # Act
        second = await record_activity_snapshot(ctx, now=_MIDNIGHT_ISH + timedelta(hours=2))

        # Assert — nothing written, no error, and STILL ONE ROW carrying the 00:07 anchor.
        # ``is_written`` False is not a failure: it is the unique constraint doing its job,
        # and the run still measured the population, which is why the counts are reported
        # either way.
        assert second["is_written"] is False
        assert second["error"] is None
        assert second["total_accounts"] == 1

        rows = await _snapshot_rows(container)
        assert len(rows) == 1
        assert rows[0].taken_at == _MIDNIGHT_ISH
        assert rows[0].total_accounts == 0
    finally:
        await container.engine.dispose()


# ---------------------------------------------------------------------------
# Failure
# ---------------------------------------------------------------------------
async def test_a_failed_snapshot_is_reported_and_never_raised_into_the_scheduler(
    tmp_path: Path,
) -> None:
    # Arrange — a container whose database has gone away under it. The engine is disposed and
    # the file deleted, so opening a session fails inside the job rather than at build time.
    container = await build_container(
        _settings(tmp_path), data_root=tmp_path / "var", with_providers=False
    )
    await container.engine.dispose()
    (tmp_path / "snapshot.db").unlink()
    (tmp_path / "snapshot.db").mkdir()  # a directory where a database file must be

    # Act — no raise. A crashed cron is indistinguishable from one that stopped firing, and
    # retrying a failed count would only file the same day's sample minutes later anyway.
    summary = await record_activity_snapshot({"container": container}, now=_MIDNIGHT_ISH)

    # Assert — the error travels as data, and every count is NULL rather than 0. A zero here
    # would be a fabricated measurement on the one table whose whole purpose is real ones.
    assert summary["error"] is not None
    assert summary["is_written"] is False
    assert summary["total_accounts"] is None
    assert summary["active_24h_accounts"] is None
    assert summary["active_30d_accounts"] is None


async def test_a_context_with_no_container_is_a_wiring_bug_and_does_raise() -> None:
    # The one exception that escapes, deliberately. A missing container would be as true of
    # the next invocation as of this one, so reporting it as a quiet nightly summary would
    # hide a broken worker for as long as nobody read the logs.
    with pytest.raises(PipelineError):
        await record_activity_snapshot({}, now=_MIDNIGHT_ISH)

    with pytest.raises(PipelineError):
        await record_activity_snapshot({"container": object()}, now=_MIDNIGHT_ISH)
