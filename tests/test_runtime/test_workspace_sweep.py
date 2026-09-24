"""The workspace sweep (IMAGE_VIDEO_SPEC §3.3, M0.3): idle AND finished, or it stays.

Two layers are tested. :func:`sweep_workspace` against a real directory tree with the owner
lookups faked, which is where the rule lives; and :func:`run_workspace_sweep` — the cron's own
entry point — over a real container and a real (SQLite) ``orders`` table, which is the proof
that the rule is wired to the states the pipeline actually writes.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Final
from uuid import UUID, uuid4

import pytest

from bayram.config import ENV_PREFIX, Settings
from bayram.contracts import OrderState, is_ok
from bayram.errors import PipelineError
from bayram.runtime.container import build_container
from bayram.runtime.jobs import build_kit_worker_settings
from bayram.runtime.workspace_sweep import (
    MEDIA_WORKSPACE_DIRNAME,
    WORKSPACE_MIN_AGE,
    WORKSPACE_SWEEP_CRON_MINUTE,
    WORKSPACE_SWEEP_JOB_NAME,
    finished_media_jobs_before_m2,
    run_workspace_sweep,
    sweep_workspace,
)
from tests.test_db.conftest import new_order

_NOW: Final[datetime] = datetime(2026, 9, 24, 12, 0, tzinfo=UTC)
_USER: Final[int] = 6_100_000_000_077


@pytest.fixture(autouse=True)
def _isolated_environment(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    for name in tuple(os.environ):
        if name.startswith(ENV_PREFIX):
            monkeypatch.delenv(name, raising=False)
    yield


def _settings(tmp_path: Path) -> Settings:
    return Settings(
        _env_file=None,
        telegram_bot_token="t",
        database_url=f"sqlite+aiosqlite:///{tmp_path / 'sweep.db'}",
        elevenlabs_api_key="k",
        llm_api_key="k",
    )


def _workspace(parent: Path, owner: UUID, *, age: timedelta, now: datetime = _NOW) -> Path:
    """A workspace dir with a nested file, every entry's mtime set ``age`` before ``now``."""
    directory = parent / str(owner)
    (directory / "nested").mkdir(parents=True)
    (directory / "song-raw.mp3").write_bytes(b"\x00" * 1000)
    (directory / "nested" / "frame.png").write_bytes(b"\x00" * 24)
    stamp = (now - age).timestamp()
    for path in (directory / "nested" / "frame.png", directory / "song-raw.mp3"):
        os.utime(path, (stamp, stamp))
    for path in (directory / "nested", directory):
        os.utime(path, (stamp, stamp))
    return directory


def _lookup(finished: set[UUID]) -> Any:
    calls: list[frozenset[UUID]] = []

    async def lookup(ids: frozenset[UUID]) -> frozenset[UUID]:
        calls.append(ids)
        return frozenset(ids & finished)

    lookup.calls = calls  # type: ignore[attr-defined]
    return lookup


_OLD: Final[timedelta] = WORKSPACE_MIN_AGE + timedelta(hours=1)
_FRESH: Final[timedelta] = timedelta(hours=1)


# ---------------------------------------------------------------------------
# The rule
# ---------------------------------------------------------------------------
async def test_an_idle_finished_workspace_goes_and_a_live_one_stays(tmp_path: Path) -> None:
    # Arrange — four legacy order workspaces covering the two conditions' truth table.
    done_old, done_fresh, live_old, live_fresh = (uuid4() for _ in range(4))
    for owner, age in (
        (done_old, _OLD),
        (done_fresh, _FRESH),
        (live_old, _OLD),
        (live_fresh, _FRESH),
    ):
        _workspace(tmp_path, owner, age=age)
    orders = _lookup({done_old, done_fresh})

    # Act
    report = await sweep_workspace(
        tmp_path,
        now=_NOW,
        finished_orders=orders,
        finished_media_jobs=finished_media_jobs_before_m2,
    )

    # Assert — only the one that is both idle and finished is gone.
    assert not (tmp_path / str(done_old)).exists()
    assert (tmp_path / str(done_fresh)).is_dir()
    assert (tmp_path / str(live_old)).is_dir()
    assert (tmp_path / str(live_fresh)).is_dir()
    assert report.deleted == 1
    assert report.bytes_freed == 1024
    assert report.kept_live == 1
    assert report.kept_recent == 2
    assert report.examined == 4
    # A fresh directory is never even asked about: the database is not read for it.
    assert orders.calls == [frozenset({done_old, live_old})]


async def test_the_newest_file_decides_the_age_not_the_directory(tmp_path: Path) -> None:
    # Arrange — a re-run writes INTO an existing directory, touching a file but not the dir
    # entry's own mtime when it overwrites in place. That tree is live.
    owner = uuid4()
    directory = _workspace(tmp_path, owner, age=_OLD)
    recent = (_NOW - _FRESH).timestamp()
    os.utime(directory / "nested" / "frame.png", (recent, recent))

    # Act
    report = await sweep_workspace(
        tmp_path,
        now=_NOW,
        finished_orders=_lookup({owner}),
        finished_media_jobs=finished_media_jobs_before_m2,
    )

    # Assert
    assert directory.is_dir()
    assert report.kept_recent == 1 and report.deleted == 0


async def test_media_workspaces_are_kept_until_media_jobs_exist(tmp_path: Path) -> None:
    # Arrange — before M2 there is no media_jobs table, so no job can be proven finished.
    job = uuid4()
    media = tmp_path / MEDIA_WORKSPACE_DIRNAME
    directory = _workspace(media, job, age=_OLD)

    # Act
    report = await sweep_workspace(
        tmp_path,
        now=_NOW,
        finished_orders=_lookup(set()),
        finished_media_jobs=finished_media_jobs_before_m2,
    )

    # Assert — kept, and counted as live rather than as unrecognised.
    assert directory.is_dir()
    assert report.kept_live == 1
    assert report.skipped_unrecognised == 0


async def test_a_finished_media_job_goes_through_its_own_lookup(tmp_path: Path) -> None:
    # Arrange — the M2 lookup, faked. An order lookup that says "finished" for everything
    # must NOT be what decides a media directory: the namespaces are separate.
    job, other_job = uuid4(), uuid4()
    media = tmp_path / MEDIA_WORKSPACE_DIRNAME
    _workspace(media, job, age=_OLD)
    _workspace(media, other_job, age=_OLD)
    orders = _lookup({job, other_job})
    media_jobs = _lookup({job})

    # Act
    report = await sweep_workspace(
        tmp_path, now=_NOW, finished_orders=orders, finished_media_jobs=media_jobs
    )

    # Assert
    assert not (media / str(job)).exists()
    assert (media / str(other_job)).is_dir()
    assert media.is_dir(), "the namespace directory itself is never removed"
    assert report.deleted == 1 and report.kept_live == 1
    assert orders.calls == []


async def test_anything_not_named_by_an_id_is_left_alone(tmp_path: Path) -> None:
    # Arrange — a stray file, a directory with a non-id name, a non-canonical UUID spelling,
    # and a symlink named like an order that points at a directory outside the workspace.
    outside = tmp_path / "outside"
    _workspace(outside, uuid4(), age=_OLD)
    root = tmp_path / "workspace"
    root.mkdir()
    (root / "notes.txt").write_text("x")
    (root / "scratch").mkdir()
    owner = uuid4()
    (root / owner.hex).mkdir()
    linked = uuid4()
    (root / str(linked)).symlink_to(outside, target_is_directory=True)

    # Act
    report = await sweep_workspace(
        root,
        now=_NOW,
        finished_orders=_lookup({owner, linked}),
        finished_media_jobs=finished_media_jobs_before_m2,
    )

    # Assert — nothing removed, the symlink's target least of all.
    assert report.deleted == 0
    assert report.skipped_unrecognised == 4
    assert (root / "scratch").is_dir() and (root / owner.hex).is_dir()
    assert len(list(outside.iterdir())) == 1


async def test_a_lookup_that_fails_deletes_nothing(tmp_path: Path) -> None:
    # Arrange
    owner = uuid4()
    directory = _workspace(tmp_path, owner, age=_OLD)

    async def unreachable(ids: frozenset[UUID]) -> frozenset[UUID]:
        raise ConnectionError("database went away")

    # Act / Assert — the error propagates out of the rule; the cron turns it into a summary.
    with pytest.raises(ConnectionError):
        await sweep_workspace(
            tmp_path,
            now=_NOW,
            finished_orders=unreachable,
            finished_media_jobs=finished_media_jobs_before_m2,
        )
    assert directory.is_dir()


async def test_a_missing_workspace_root_is_an_empty_sweep(tmp_path: Path) -> None:
    report = await sweep_workspace(
        tmp_path / "never-made",
        now=_NOW,
        finished_orders=_lookup(set()),
        finished_media_jobs=finished_media_jobs_before_m2,
    )
    assert report.examined == 0


# ---------------------------------------------------------------------------
# The cron entry point, over a real container and real order states
# ---------------------------------------------------------------------------
async def test_the_cron_sweeps_terminal_orders_and_keeps_live_ones(tmp_path: Path) -> None:
    # Arrange — one order per state that matters, each with a day-old workspace, plus one
    # workspace whose order row no longer exists (purged by retention).
    container = await build_container(
        _settings(tmp_path), data_root=tmp_path / "var", with_providers=False
    )
    try:
        by_state: dict[OrderState, UUID] = {}
        for state in (
            OrderState.DELIVERED,
            OrderState.FAILED,
            OrderState.CANCELLED,
            OrderState.GENERATING,
            OrderState.AUTHORIZED,
        ):
            order = new_order(state=state, telegram_user_id=_USER)
            created = await container.repository.create_order(order)
            assert is_ok(created), created
            by_state[state] = order.id
        purged = uuid4()
        now = datetime.now(UTC)
        for owner in (*by_state.values(), purged):
            _workspace(container.workspace_root, owner, age=_OLD, now=now)

        # Act — the job exactly as arq calls it, plus the injectable clock.
        summary = await run_workspace_sweep({"container": container}, now=now)

        # Assert
        root = container.workspace_root
        for state in (OrderState.DELIVERED, OrderState.FAILED, OrderState.CANCELLED):
            assert not (root / str(by_state[state])).exists(), state
        assert not (root / str(purged)).exists()
        assert (root / str(by_state[OrderState.GENERATING])).is_dir()
        assert (root / str(by_state[OrderState.AUTHORIZED])).is_dir()
        assert summary["deleted"] == 4
        assert summary["kept_live"] == 2
        assert summary["error"] is None
    finally:
        await container.engine.dispose()


async def test_the_cron_fails_closed_when_the_database_is_gone(tmp_path: Path) -> None:
    # Arrange — a disposed engine over a deleted database file: every read fails.
    container = await build_container(
        _settings(tmp_path), data_root=tmp_path / "var", with_providers=False
    )
    order = new_order(state=OrderState.DELIVERED, telegram_user_id=_USER)
    now = datetime.now(UTC)
    directory = _workspace(container.workspace_root, order.id, age=_OLD, now=now)
    await container.engine.dispose()
    (tmp_path / "sweep.db").unlink()

    # Act
    summary = await run_workspace_sweep({"container": container}, now=now)
    await container.engine.dispose()

    # Assert — a summary carrying the failure, and the directory untouched.
    assert summary["error"] is not None
    assert summary["deleted"] == 0
    assert directory.is_dir()


async def test_a_context_with_no_container_is_a_wiring_error() -> None:
    with pytest.raises(PipelineError):
        await run_workspace_sweep({})


def test_the_sweep_has_an_hourly_cron_and_is_registered(tmp_path: Path) -> None:
    async def _dependencies() -> dict[str, Any]:
        return {}

    worker = build_kit_worker_settings(
        settings=_settings(tmp_path), build_dependencies=_dependencies
    )

    entries = [job for job in worker.cron_jobs if job.coroutine is run_workspace_sweep]
    assert len(entries) == 1
    entry = entries[0]
    assert entry.name == WORKSPACE_SWEEP_JOB_NAME
    assert entry.minute == WORKSPACE_SWEEP_CRON_MINUTE
    assert entry.hour is None, "hourly, not daily"
    assert entry.run_at_startup is False
    assert entry.max_tries == 1
    assert run_workspace_sweep in worker.functions
