"""The retention sweep, as a job that actually runs and actually deletes files.

Everything under this was already tested and none of it had ever executed: ``purge_expired``
had no caller, so the storage keys it hands back were never deleted and no record of a
sweep existed anywhere. These tests are the ones that would have failed before the job
existed, which is why they are deliberately end-to-end rather than mocked:

* the container is a REAL one (SQLite on disk, ``LocalFileStorage`` on a real temp path);
* the expired asset's archive file is a REAL file, and the assertion is that it is gone
  from the filesystem afterwards — not that ``delete`` was called;
* the failure test uses a storage that really returns ``Err``, and asserts the mismatch is
  still legible on the stored row afterwards.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
import sqlalchemy as sa

from hbd.config import Settings
from hbd.contracts import AssetKind, OrderState, Result, err
from hbd.db.admin import retention as retention_queries
from hbd.db.enums import PurgeTrigger
from hbd.db.models import AssetRow
from hbd.db.models.purge_run import PurgeRunRow
from hbd.db.purge import DEFAULT_PURGE_BATCH_SIZE, PurgeReport
from hbd.errors import StorageError
from hbd.runtime.container import ARCHIVE_DIRNAME, AppContainer, build_container
from hbd.runtime.jobs import build_kit_worker_settings
from hbd.runtime.retention_job import (
    RETENTION_CRON_MINUTE,
    RETENTION_JOB_NAME,
    run_retention_sweep,
)
from tests.test_db.conftest import build_kit, new_order

_A_YEAR_AND_A_BIT = 400
_KEY = "kits/expired/song.mp3"


def _settings(tmp_path: Path) -> Settings:
    return Settings(
        _env_file=None,
        telegram_bot_token="t",
        database_url=f"sqlite+aiosqlite:///{tmp_path / 'retention.db'}",
        elevenlabs_api_key="k",
        llm_api_key="k",
    )


async def _container(tmp_path: Path) -> AppContainer:
    """A real container with no vendors — exactly the §4.3 shape the sweep needs."""
    return await build_container(
        _settings(tmp_path), data_root=tmp_path / "var", with_providers=False
    )


async def _expired_kit_with_one_archived_object(
    container: AppContainer, tmp_path: Path
) -> tuple[Path, datetime]:
    """One paid, delivered order whose song has a real file in the archive.

    Returns the archive path and an instant past every clock on it. The file is written by
    hand because nothing writes ``assets.storage_key`` yet (that is a later phase); the
    point of the test is that the JOB is correct the day it does.
    """
    order = new_order(state=OrderState.BRIEF_READY)
    await container.repository.create_order(order)
    await container.repository.set_order_state(
        order.id, OrderState.AUTHORIZED, now=datetime.now(UTC)
    )
    await container.repository.save_kit(build_kit(tmp_path, order.id))

    async with container.require_session_factory().begin() as session:
        await session.execute(
            sa.update(AssetRow)
            # The SONG only: ``variant_index == 0`` alone would also catch the first
            # greeting and the lyric sheet, and the point of the assertions downstream is
            # that ONE key is handed over and ONE file disappears.
            .where(AssetRow.order_id == order.id, AssetRow.kind == AssetKind.SONG)
            .values(storage_key=_KEY)
        )

    archived = tmp_path / "var" / ARCHIVE_DIRNAME / _KEY
    archived.parent.mkdir(parents=True, exist_ok=True)
    archived.write_bytes(b"an expired birthday song")
    return archived, datetime.now(UTC) + timedelta(days=_A_YEAR_AND_A_BIT)


async def _stored_runs(container: AppContainer) -> tuple[PurgeRunRow, ...]:
    async with container.require_session_factory()() as session:
        return await retention_queries.recent_runs(session)


class _RefusingStorage:
    """A ``Storage`` whose ``delete`` always fails. Everything else is unreachable here."""

    def __init__(self) -> None:
        self.attempted: list[str] = []

    async def put(self, key: str, data: bytes, *, content_type: str) -> Result[Any]:
        raise NotImplementedError

    async def get(self, key: str) -> Result[bytes]:
        raise NotImplementedError

    async def signed_url(self, key: str, *, ttl_s: int) -> Result[str]:
        raise NotImplementedError

    async def delete(self, key: str) -> Result[None]:
        self.attempted.append(key)
        return err(StorageError("the bucket refused", context={"key": key}))


# ---------------------------------------------------------------------------
# The cron entry itself
# ---------------------------------------------------------------------------
def test_the_worker_registers_an_hourly_cron_that_fires_the_retention_sweep(
    tmp_path: Path,
) -> None:
    """Before this entry existed, every retention clock in the schema was decorative."""

    # Arrange
    async def _dependencies() -> dict[str, Any]:
        return {}

    # Act
    worker = build_kit_worker_settings(
        settings=_settings(tmp_path), build_dependencies=_dependencies
    )

    # Assert — one cron, pointing at the sweep, once an hour.
    assert [job.coroutine for job in worker.cron_jobs] == [run_retention_sweep]
    entry = worker.cron_jobs[0]
    assert entry.name == RETENTION_JOB_NAME
    assert entry.minute == RETENTION_CRON_MINUTE
    # ``hour is None`` is arq's "every hour"; a number here would make it daily.
    assert entry.hour is None
    assert entry.month is None and entry.day is None and entry.weekday is None


def test_the_sweep_is_also_dispatchable_by_name_for_the_manual_run(tmp_path: Path) -> None:
    """``POST /api/retention/run`` enqueues by name; the worker must answer to it."""

    # Arrange
    async def _dependencies() -> dict[str, Any]:
        return {}

    # Act
    worker = build_kit_worker_settings(
        settings=_settings(tmp_path), build_dependencies=_dependencies
    )

    # Assert
    assert run_retention_sweep in worker.functions
    assert run_retention_sweep.__name__ == RETENTION_JOB_NAME


# ---------------------------------------------------------------------------
# The bytes actually go
# ---------------------------------------------------------------------------
async def test_an_expired_assets_archive_file_is_gone_from_disk_after_one_sweep(
    tmp_path: Path,
) -> None:
    """The bug: rows expired on schedule and the files behind them stayed forever."""
    # Arrange
    container = await _container(tmp_path)
    try:
        archived, later = await _expired_kit_with_one_archived_object(container, tmp_path)
        assert archived.exists(), "the fixture must start from a real file on disk"

        # Act
        summary = await run_retention_sweep({"container": container}, now=later)

        # Assert — the file is gone, and the counts say so without rounding.
        assert not archived.exists()
        assert summary["storage_keys_returned"] == 1
        assert summary["storage_keys_deleted"] == 1
        assert summary["storage_delete_failures"] == 0
    finally:
        await container.aclose()


async def test_the_run_is_recorded_with_returned_and_deleted_matching(tmp_path: Path) -> None:
    # Arrange
    container = await _container(tmp_path)
    try:
        _, later = await _expired_kit_with_one_archived_object(container, tmp_path)

        # Act
        await run_retention_sweep({"container": container}, now=later)

        # Assert — a record, not a log line.
        runs = await _stored_runs(container)
        assert len(runs) == 1
        row = runs[0]
        assert row.trigger is PurgeTrigger.CRON
        assert row.triggered_by_username is None
        assert row.assets_deleted == 5
        assert row.storage_keys_returned == row.storage_keys_deleted == 1
        assert row.is_storage_leaking is False
        assert row.error_code is None
        assert row.batch_size == DEFAULT_PURGE_BATCH_SIZE
    finally:
        await container.aclose()


async def test_a_sweep_with_nothing_due_still_writes_a_row_of_zeros(tmp_path: Path) -> None:
    """Silence and "nothing was due" must not look the same to an operator."""
    # Arrange
    container = await _container(tmp_path)
    try:
        # Act
        await run_retention_sweep({"container": container}, now=datetime.now(UTC))

        # Assert
        runs = await _stored_runs(container)
        assert len(runs) == 1
        assert runs[0].assets_deleted == 0
        assert runs[0].is_batch_full is False
    finally:
        await container.aclose()


# ---------------------------------------------------------------------------
# A failing delete stays visible
# ---------------------------------------------------------------------------
async def test_a_storage_delete_that_fails_is_counted_logged_and_left_visible(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """A leak that is averaged away is a leak nobody ever fixes."""
    # Arrange
    container = await _container(tmp_path)
    try:
        _, later = await _expired_kit_with_one_archived_object(container, tmp_path)
        refusing = _RefusingStorage()
        failing = replace(container, storage=refusing)

        # Act
        with caplog.at_level(logging.ERROR, logger="hbd.runtime.retention_job"):
            summary = await run_retention_sweep({"container": failing}, now=later)

        # Assert — the attempt happened, the failure was counted, and it was said out loud.
        assert refusing.attempted == [_KEY]
        assert summary["storage_keys_returned"] == 1
        assert summary["storage_keys_deleted"] == 0
        assert summary["storage_delete_failures"] == 1
        assert any(
            "could not be deleted from storage" in record.message for record in caplog.records
        )

        # Assert — and the mismatch survives on the row, not only in the log.
        runs = await _stored_runs(container)
        assert runs[0].storage_keys_returned == 1
        assert runs[0].storage_keys_deleted == 0
        assert runs[0].storage_delete_failures == 1
        assert runs[0].is_storage_leaking is True
    finally:
        await container.aclose()


# ---------------------------------------------------------------------------
# A failed purge is recorded, not swallowed
# ---------------------------------------------------------------------------
async def test_a_purge_that_returns_err_still_writes_a_row_carrying_the_error_code(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Arrange
    container = await _container(tmp_path)
    try:

        async def _explode(*args: Any, **kwargs: Any) -> Result[PurgeReport]:
            return err(StorageError("the database went away"))

        monkeypatch.setattr("hbd.runtime.retention_job.purge_expired", _explode)

        # Act
        summary = await run_retention_sweep({"container": container}, now=datetime.now(UTC))

        # Assert
        assert summary["error"] == "STORAGE_FAILED"
        runs = await _stored_runs(container)
        assert len(runs) == 1
        assert runs[0].error_code == "STORAGE_FAILED"
        assert runs[0].assets_deleted == 0
    finally:
        await container.aclose()


async def test_a_record_that_cannot_be_written_is_logged_rather_than_swallowed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """The sweep already happened; raising here would get real deletions retried."""
    # Arrange
    container = await _container(tmp_path)
    try:

        async def _refuse(*args: Any, **kwargs: Any) -> None:
            raise RuntimeError("the record table is unreachable")

        monkeypatch.setattr("hbd.runtime.retention_job.retention_queries.record_run", _refuse)

        # Act
        with caplog.at_level(logging.ERROR, logger="hbd.runtime.retention_job"):
            summary = await run_retention_sweep({"container": container}, now=datetime.now(UTC))

        # Assert — the job still reports what it did, and the loss is said out loud.
        assert summary["error"] is None
        assert any("record could not be written" in record.message for record in caplog.records)
        assert await _stored_runs(container) == ()
    finally:
        await container.aclose()


# ---------------------------------------------------------------------------
# The trigger is recorded, because the three are accountable differently
# ---------------------------------------------------------------------------
async def test_a_manual_run_records_the_operator_who_asked_for_it(tmp_path: Path) -> None:
    # Arrange
    container = await _container(tmp_path)
    try:
        # Act
        await run_retention_sweep(
            {"container": container},
            trigger=PurgeTrigger.MANUAL,
            triggered_by_username="owner",
            now=datetime.now(UTC),
        )

        # Assert
        runs = await _stored_runs(container)
        assert runs[0].trigger is PurgeTrigger.MANUAL
        assert runs[0].triggered_by_username == "owner"
    finally:
        await container.aclose()


async def test_a_trigger_that_arrives_as_a_plain_string_is_still_recorded(
    tmp_path: Path,
) -> None:
    """ARQ round-trips kwargs through a serializer; the boundary must not trust the type."""
    # Arrange
    container = await _container(tmp_path)
    try:
        # Act
        await run_retention_sweep(
            {"container": container},
            trigger="manual",  # type: ignore[arg-type]
            now=datetime.now(UTC),
        )

        # Assert
        runs = await _stored_runs(container)
        assert runs[0].trigger is PurgeTrigger.MANUAL
    finally:
        await container.aclose()


async def test_an_unrecognised_trigger_is_recorded_as_cron_rather_than_skipping_the_purge(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """A mislabelled trigger must not be a reason to skip a legally required sweep."""
    # Arrange
    container = await _container(tmp_path)
    try:
        # Act
        with caplog.at_level(logging.WARNING, logger="hbd.runtime.retention_job"):
            await run_retention_sweep(
                {"container": container},
                trigger="whatever",  # type: ignore[arg-type]
                now=datetime.now(UTC),
            )

        # Assert
        runs = await _stored_runs(container)
        assert len(runs) == 1
        assert runs[0].trigger is PurgeTrigger.CRON
        assert any("unrecognised purge trigger" in record.message for record in caplog.records)
    finally:
        await container.aclose()


# ---------------------------------------------------------------------------
# Wiring failures name themselves
# ---------------------------------------------------------------------------
async def test_a_context_without_a_container_names_the_wiring_bug() -> None:
    # Act / Assert — a startup bug, not a run-time condition.
    with pytest.raises(Exception, match="missing a usable 'container'"):
        await run_retention_sweep({})


async def test_a_provider_free_container_still_closes_and_still_refuses_to_render(
    tmp_path: Path,
) -> None:
    """§4.3: the provider-free shape must be usable, and must fail by NAME when misused."""
    # Arrange
    container = await _container(tmp_path)

    # Act / Assert
    assert container.providers is None
    with pytest.raises(Exception, match="container built without providers"):
        container.pipeline()
    await container.aclose()


def test_a_container_without_a_session_factory_names_that_too() -> None:
    # Arrange — the frozen dataclass makes this the only way to build one.
    settings = Settings(
        _env_file=None,
        telegram_bot_token="t",
        database_url="sqlite+aiosqlite:///:memory:",
        elevenlabs_api_key="k",
        llm_api_key="k",
    )
    container = AppContainer(
        settings=settings,
        providers=None,
        repository=None,  # type: ignore[arg-type]
        storage=None,  # type: ignore[arg-type]
        post=None,  # type: ignore[arg-type]
        payment=None,  # type: ignore[arg-type]
        workspace_root=Path(),
        engine=None,  # type: ignore[arg-type]
        music_slots=asyncio.Semaphore(1),
        tts_slots=asyncio.Semaphore(1),
    )

    # Act / Assert
    with pytest.raises(Exception, match="without a session factory"):
        container.require_session_factory()
