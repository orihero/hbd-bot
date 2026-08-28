"""The migration chain is the schema. These tests keep that true.

Behavioural tests build their schema from ``Base.metadata.create_all``, which is fast and
lets them assert behaviour instead of DDL. The risk in that trade is a model changing
without a migration, so production and the test suite quietly diverge. That risk is closed
here, in one place:

* :func:`test_upgrade_then_downgrade_leaves_no_tables_behind` proves the chain is
  reversible — a migration that cannot be rolled back is one nobody dares deploy.
* :func:`test_the_migrated_schema_matches_the_model_metadata` proves the chain and the
  models agree, so ``create_all`` in the other tests is a faithful stand-in.

Every test here is **synchronous**, deliberately. ``env.py`` drives an async engine and
calls ``asyncio.run`` itself, which raises if a loop is already running — so an ``async
def`` test would fail on the first ``command.upgrade``. Inspection then gets its own
``asyncio.run``, which keeps the whole module free of a sync database driver and therefore
free of a dependency the project does not otherwise need.

The SQLite runs are unit tests. The Postgres run is marked ``integration`` and needs
``docker compose up -d``; SoW DAT-4 requires the migration to work on the real engine, and
SQLite's permissiveness is not evidence that it does.
"""

from __future__ import annotations

import asyncio
import os
from collections.abc import Iterator
from pathlib import Path
from typing import Final

import pytest
from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import Connection, inspect
from sqlalchemy.ext.asyncio import create_async_engine

from hbd.config import get_settings
from hbd.db.engine import ping as db_ping
from hbd.db.models import Base

_REPO_ROOT: Final[Path] = Path(__file__).resolve().parents[2]
_ALEMBIC_INI: Final[Path] = _REPO_ROOT / "migrations" / "alembic.ini"
_VERSIONS_DIR: Final[Path] = _ALEMBIC_INI.parent / "versions"

#: Alembic's own bookkeeping table, present after any upgrade and absent from our metadata.
_ALEMBIC_TABLE: Final[str] = "alembic_version"

#: Matches docker-compose.yml. Overridable so CI can point at its own instance.
_POSTGRES_URL: Final[str] = os.environ.get(
    "HBD_TEST_POSTGRES_URL", "postgresql+asyncpg://hbd:hbd@localhost:5432/hbd"
)

_REQUIRED_ENV: Final[tuple[str, ...]] = (
    "HBD_TELEGRAM_BOT_TOKEN",
    "HBD_ELEVENLABS_API_KEY",
    "HBD_LLM_API_KEY",
)

_EXPECTED_TABLES: Final[frozenset[str]] = frozenset(
    {"users", "orders", "briefs", "assets", "name_records", "generation_attempts"}
)


def _config() -> Config:
    config = Config(str(_ALEMBIC_INI))
    config.set_main_option("script_location", str(_ALEMBIC_INI.parent))
    return config


@pytest.fixture(autouse=True)
def _clean_settings_cache() -> Iterator[None]:
    """``get_settings`` is ``lru_cache``d, so a stale entry outlives any ``monkeypatch``.

    Without this the URL set by :func:`_prepare_env` is silently ignored and every run
    targets whatever database was cached first — the test cannot control its own target.
    """
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def _prepare_env(url: str, monkeypatch: pytest.MonkeyPatch) -> None:
    """Point ``env.py`` at ``url`` the same way production does — through ``hbd.config``."""
    monkeypatch.setenv("HBD_DATABASE_URL", url)
    for name in _REQUIRED_ENV:
        monkeypatch.setenv(name, "migration-test-value")
    # Settings are cached process-wide; the env above only takes effect once it is dropped.
    get_settings.cache_clear()


def _require_postgres(url: str) -> None:
    """Skip when no *project* Postgres answers at ``url``.

    A foreign Postgres on the same port authenticates as a different role, which is a
    missing dependency rather than a failing migration — so it skips, like the rest of the
    integration suite, instead of reporting a defect that is not there.
    """
    engine = create_async_engine(url)
    try:
        is_reachable = asyncio.run(db_ping(engine))
    finally:
        asyncio.run(engine.dispose())
    if not is_reachable:
        pytest.skip(f"no project Postgres at {url}; run `docker compose up -d`")


def _upgrade(url: str, monkeypatch: pytest.MonkeyPatch, *, to: str = "head") -> None:
    _prepare_env(url, monkeypatch)
    command.upgrade(_config(), to)


def _downgrade(url: str, monkeypatch: pytest.MonkeyPatch, *, to: str = "base") -> None:
    _prepare_env(url, monkeypatch)
    command.downgrade(_config(), to)


def _schema_of(url: str) -> dict[str, set[str]]:
    """Table -> column names, read back from a live database. Its own event loop."""

    def _read(connection: Connection) -> dict[str, set[str]]:
        inspector = inspect(connection)
        return {
            table: {column["name"] for column in inspector.get_columns(table)}
            for table in inspector.get_table_names()
            if table != _ALEMBIC_TABLE
        }

    async def _run() -> dict[str, set[str]]:
        engine = create_async_engine(url)
        try:
            async with engine.connect() as connection:
                return await connection.run_sync(_read)
        finally:
            await engine.dispose()

    return asyncio.run(_run())


def _sqlite_url(tmp_path: Path, name: str) -> str:
    return f"sqlite+aiosqlite:///{tmp_path / name}"


# ---------------------------------------------------------------------------
# Static checks — no engine at all
# ---------------------------------------------------------------------------
def test_exactly_one_migration_head_exists() -> None:
    # Arrange
    script = ScriptDirectory.from_config(_config())

    # Act
    heads = script.get_heads()

    # Assert — two heads means someone branched and nobody merged.
    assert len(heads) == 1


def test_every_migration_defines_a_real_downgrade() -> None:
    # Arrange
    versions = sorted(_VERSIONS_DIR.glob("*.py"))
    assert versions, "expected at least the initial migration to exist"

    # Act
    stubs = [
        path.name
        for path in versions
        if "def downgrade() -> None:\n    pass" in path.read_text(encoding="utf-8")
    ]

    # Assert
    assert stubs == [], f"migrations without a working downgrade: {stubs}"


def test_no_migration_imports_application_code() -> None:
    # Arrange — a migration importing hbd.* breaks when hbd.* is refactored, and it breaks
    # historically, on a revision that already ran everywhere. env.py renders our own
    # column types as plain SQLAlchemy ones precisely so this stays true.
    versions = sorted(_VERSIONS_DIR.glob("*.py"))

    # Act
    offenders = [
        path.name
        for path in versions
        if any(
            line.startswith(("import hbd", "from hbd"))
            for line in path.read_text(encoding="utf-8").splitlines()
        )
    ]

    # Assert
    assert offenders == [], f"migrations importing application code: {offenders}"


# ---------------------------------------------------------------------------
# SQLite — runs everywhere, no Docker
# ---------------------------------------------------------------------------
def test_upgrade_creates_every_expected_table(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Arrange
    url = _sqlite_url(tmp_path, "migrate.db")

    # Act
    _upgrade(url, monkeypatch)

    # Assert
    assert set(_schema_of(url)) == set(_EXPECTED_TABLES)


def test_the_migrated_schema_matches_the_model_metadata(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Arrange
    url = _sqlite_url(tmp_path, "compare.db")
    _upgrade(url, monkeypatch)

    # Act
    migrated = _schema_of(url)
    expected = {
        name: {column.name for column in table.columns}
        for name, table in Base.metadata.tables.items()
    }

    # Assert — this is what licenses every other test to build its schema with create_all.
    assert migrated == expected


def test_upgrade_then_downgrade_leaves_no_tables_behind(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Arrange
    url = _sqlite_url(tmp_path, "reverse.db")
    _upgrade(url, monkeypatch)

    # Act
    _downgrade(url, monkeypatch)

    # Assert
    assert _schema_of(url) == {}


def test_upgrade_is_idempotent_when_already_at_head(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Arrange
    url = _sqlite_url(tmp_path, "twice.db")
    _upgrade(url, monkeypatch)

    # Act — a redeploy re-runs `alembic upgrade head`; it must be a no-op.
    _upgrade(url, monkeypatch)

    # Assert
    assert set(_schema_of(url)) == set(_EXPECTED_TABLES)


def test_the_migration_records_its_revision(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Arrange
    url = _sqlite_url(tmp_path, "stamp.db")

    # Act
    _upgrade(url, monkeypatch)

    # Assert — without the version table, the next upgrade would re-run everything.
    def _read(connection: Connection) -> list[str]:
        return inspect(connection).get_table_names()

    async def _run() -> list[str]:
        engine = create_async_engine(url)
        try:
            async with engine.connect() as connection:
                return await connection.run_sync(_read)
        finally:
            await engine.dispose()

    assert _ALEMBIC_TABLE in asyncio.run(_run())


# ---------------------------------------------------------------------------
# Postgres — the engine production actually runs on (SoW DAT-4)
# ---------------------------------------------------------------------------
@pytest.mark.integration
def test_migration_applies_and_reverses_against_postgres(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Arrange — requires `docker compose up -d`.
    _require_postgres(_POSTGRES_URL)
    _downgrade(_POSTGRES_URL, monkeypatch)

    # Act
    _upgrade(_POSTGRES_URL, monkeypatch)
    applied = _schema_of(_POSTGRES_URL)
    _downgrade(_POSTGRES_URL, monkeypatch)
    reversed_schema = _schema_of(_POSTGRES_URL)

    # Assert
    expected = {
        name: {column.name for column in table.columns}
        for name, table in Base.metadata.tables.items()
    }
    assert applied == expected
    assert reversed_schema == {}
