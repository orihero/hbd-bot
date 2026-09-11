"""Database fixtures. In-memory SQLite only — no server, no Docker, no network.

The engine is created per test against a single shared in-memory connection, so the schema
built by ``create_all`` is the same one the repository queries. Without ``StaticPool`` each
new connection would get its own empty ``:memory:`` database and every test would fail on a
missing table for reasons that have nothing to do with the code under test.

The schema comes from ``Base.metadata.create_all`` rather than from Alembic, deliberately:
unit tests assert behaviour, and running the migration chain in each of them would make the
suite slow and would couple every behavioural test to migration history. That the migration
and the metadata agree is asserted once, explicitly, in
``test_migrations.py::test_migration_chain_matches_the_model_metadata``.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import StaticPool

from bayram.contracts import (
    AssetKind,
    Kit,
    NameCandidate,
    NameStrategy,
    NameVerdict,
    Order,
    OrderState,
)
from bayram.db.attempts import GenerationAttemptRepository
from bayram.db.engine import create_session_factory
from bayram.db.models import Base
from bayram.db.names import NameRecordRepository
from bayram.db.repository import SqlKitRepository
from bayram.db.retention import DEFAULT_RETENTION_POLICY, RetentionPolicy
from tests.conftest import FIXED_NOW, make_asset, make_lyrics, make_order


class MovableClock:
    """Test double for ``utc_now``. Advancing it is how a retention test skips a year."""

    def __init__(self, start: datetime) -> None:
        self._now = start

    def __call__(self) -> datetime:
        return self._now

    @property
    def now(self) -> datetime:
        return self._now

    def advance(self, *, days: int = 0, seconds: int = 0) -> datetime:
        """Move forward. Returns the new instant so a caller can pass it straight on."""
        self._now = self._now + timedelta(days=days, seconds=seconds)
        return self._now


@pytest.fixture
async def engine() -> AsyncIterator[AsyncEngine]:
    """A fresh in-memory database with the full schema, torn down after each test."""
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    yield engine
    await engine.dispose()


@pytest.fixture
def sessions(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return create_session_factory(engine)


@pytest.fixture
def clock() -> MovableClock:
    """A clock pinned to ``FIXED_NOW`` that a test can advance by whole days."""
    return MovableClock(FIXED_NOW)


@pytest.fixture
def policy() -> RetentionPolicy:
    return DEFAULT_RETENTION_POLICY


@pytest.fixture
def repository(
    sessions: async_sessionmaker[AsyncSession],
    policy: RetentionPolicy,
    clock: MovableClock,
) -> SqlKitRepository:
    return SqlKitRepository(sessions, policy=policy, clock=clock)


@pytest.fixture
def attempts(
    sessions: async_sessionmaker[AsyncSession],
    policy: RetentionPolicy,
    clock: MovableClock,
) -> GenerationAttemptRepository:
    return GenerationAttemptRepository(sessions, policy=policy, clock=clock)


@pytest.fixture
def names(sessions: async_sessionmaker[AsyncSession], clock: MovableClock) -> NameRecordRepository:
    return NameRecordRepository(sessions, clock=clock)


# ---------------------------------------------------------------------------
# Domain builders on top of the shared factories in tests/conftest.py
# ---------------------------------------------------------------------------
def build_kit(tmp_path: Path, order_id: UUID, *, greeting_count: int = 3) -> Kit:
    """A complete kit whose files exist on disk, so ``sha256`` is a real digest."""
    song = make_asset(tmp_path, path=tmp_path / f"{order_id}-song.mp3")
    greetings = tuple(
        make_asset(
            tmp_path,
            path=tmp_path / f"{order_id}-greeting-{index}.ogg",
            kind=AssetKind.GREETING,
            mime="audio/ogg",
            duration_s=30.0,
            persona_id=f"persona-{index}",
            loudness_lufs=-16.0,
        )
        for index in range(greeting_count)
    )
    sheet = make_asset(
        tmp_path,
        path=tmp_path / f"{order_id}-lyrics.txt",
        kind=AssetKind.LYRIC_SHEET,
        mime="text/plain",
        duration_s=0.0,
        loudness_lufs=None,
    )
    return Kit(
        order_id=order_id,
        song=song,
        greetings=greetings,
        lyric_sheet=sheet,
        lyrics=make_lyrics(),
        name_verdicts=(make_verdict(),),
    )


def make_verdict(
    *,
    strategy: NameStrategy = NameStrategy.STRIPPED,
    rank: int = 0,
    is_match: bool = True,
    attempt: int = 0,
    text: str = "Gulomjon",
    transcript: str = "Gulomjon",
) -> NameVerdict:
    return NameVerdict(
        candidate=NameCandidate(text=text, strategy=strategy, rank=rank),
        transcript=transcript,
        is_match=is_match,
        confidence=0.93,
        attempt=attempt,
    )


def new_order(*, state: OrderState = OrderState.BRIEF_READY, **overrides: Any) -> Order:
    """An order with a fresh id, so two orders in one test never collide."""
    return make_order(id=uuid4(), state=state, **overrides)


def utc(year: int, month: int, day: int) -> datetime:
    return datetime(year, month, day, tzinfo=UTC)


async def refuse_a_foreign_database(engine: AsyncEngine) -> None:
    """Raise unless every table in this database belongs to this project.

    Every Postgres fixture in the suite runs ``Base.metadata.drop_all`` against whatever
    answers at ``BAYRAM_TEST_POSTGRES_URL``, whose default is ``localhost:5432`` — the port a
    developer's unrelated Postgres is most likely to be on. ``drop_all`` only drops tables
    the metadata names, so the blast radius was always bounded, but "bounded" is not the
    same as "checked": a database that happens to contain a table called ``users`` or
    ``orders`` would lose it.

    The check is deliberately one-directional. An EMPTY database passes (that is a fresh
    container), and a database holding only this project's tables passes. Anything else is
    somebody's data.
    """
    import sqlalchemy as sa

    from bayram.db.models import Base

    async with engine.connect() as connection:
        found = await connection.run_sync(lambda sync: set(sa.inspect(sync).get_table_names()))
    unknown = found - set(Base.metadata.tables) - {"alembic_version"}
    if unknown:
        raise RuntimeError(
            "refusing to drop_all against a database this project did not create; it holds "
            f"{sorted(unknown)}. Point BAYRAM_TEST_POSTGRES_URL at the project's container "
            "(docker compose up -d), or set BAYRAM_POSTGRES_PORT to a free port."
        )
