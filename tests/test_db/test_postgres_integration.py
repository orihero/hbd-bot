"""The full write path against real Postgres. Marked ``integration``; excluded from ``make test``.

SQLite is a good stand-in for behaviour and a poor one for types. It accepts a string where
Postgres wants a ``uuid``, stores ``JSON`` as text, and does not care about ``timestamptz``
at all — so a query that works there can still fail on the engine that matters. This module
runs the whole lifecycle (order → kit → purge) on the schema Alembic actually built, on
Postgres 16, through asyncpg.

Requires ``docker compose up -d``. Point ``HBD_TEST_POSTGRES_URL`` elsewhere if 5432 is
already taken on the host.
"""

from __future__ import annotations

import asyncio
import os
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Final
from uuid import uuid4

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from hbd.contracts import NameStrategy, OrderState, is_err, is_ok
from hbd.db.attempts import GenerationAttemptRepository
from hbd.db.credit_sql import verify_balances
from hbd.db.credits import SqlCreditLedger
from hbd.db.engine import create_engine, create_session_factory, ping
from hbd.db.enums import CreditEntryKind
from hbd.db.models import Base, BriefRow, CreditAccountRow, CreditLedgerRow
from hbd.db.purge import purge_expired
from hbd.db.repository import SqlKitRepository
from hbd.db.retention import RetentionClass
from hbd.entitlements import ChargeOutcome, EntitlementPolicy, InsufficientCreditsError
from tests.conftest import UZBEK_NAME_CANONICAL, recipient_of
from tests.test_db.conftest import MovableClock, build_kit, new_order

pytestmark = pytest.mark.integration

_POSTGRES_URL: Final[str] = os.environ.get(
    "HBD_TEST_POSTGRES_URL", "postgresql+asyncpg://hbd:hbd@localhost:5432/hbd_test"
)


@pytest.fixture
async def pg_engine() -> AsyncIterator[AsyncEngine]:
    """A real Postgres engine with a freshly created schema, dropped afterwards."""
    engine = create_engine(_POSTGRES_URL)
    if not await ping(engine):
        await engine.dispose()
        pytest.skip(f"no Postgres at {_POSTGRES_URL}; run `docker compose up -d`")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.drop_all)
        await connection.run_sync(Base.metadata.create_all)
    yield engine
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.drop_all)
    await engine.dispose()


@pytest.fixture
def pg_sessions(pg_engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return create_session_factory(pg_engine)


@pytest.fixture
def pg_repository(
    pg_sessions: async_sessionmaker[AsyncSession], clock: MovableClock
) -> SqlKitRepository:
    return SqlKitRepository(pg_sessions, clock=clock)


async def test_the_full_order_lifecycle_works_on_postgres(
    pg_repository: SqlKitRepository, tmp_path: Path, clock: MovableClock
) -> None:
    # Arrange
    order = new_order()

    # Act
    created = await pg_repository.create_order(order)
    await pg_repository.set_order_state(order.id, OrderState.AUTHORIZED, now=clock.advance(days=1))
    saved = await pg_repository.save_kit(build_kit(tmp_path, order.id))
    fetched = await pg_repository.get_kit(order.id)

    # Assert
    assert is_ok(created)
    assert is_ok(saved)
    assert is_ok(fetched)
    assert len(fetched.value.greetings) == 3
    assert fetched.value.lyrics.name_display == UZBEK_NAME_CANONICAL


async def test_uzbek_orthography_survives_a_postgres_round_trip(
    pg_repository: SqlKitRepository,
) -> None:
    # Arrange — U+02BB is the character the whole product exists to get right.
    order = new_order()
    await pg_repository.create_order(order)

    # Act
    fetched = await pg_repository.get_order(order.id)

    # Assert
    assert is_ok(fetched)
    display = recipient_of(fetched.value.brief).display
    assert display == UZBEK_NAME_CANONICAL
    assert "ʻ" in display


async def test_the_candidate_jsonb_column_round_trips_on_postgres(
    pg_repository: SqlKitRepository,
) -> None:
    # Arrange — JSONB, not text: the type only matters on the real engine.
    order = new_order()
    await pg_repository.create_order(order)

    # Act
    fetched = await pg_repository.get_order(order.id)

    # Assert
    assert is_ok(fetched)
    candidates = recipient_of(fetched.value.brief).candidates
    assert tuple(c.rank for c in candidates) == (0, 1, 2)
    assert candidates[0].strategy is NameStrategy.STRIPPED


async def test_timestamps_come_back_timezone_aware_from_postgres(
    pg_repository: SqlKitRepository, clock: MovableClock
) -> None:
    # Arrange
    order = new_order()
    await pg_repository.create_order(order)

    # Act
    fetched = await pg_repository.get_order(order.id)

    # Assert — a naive datetime here would make every retention comparison wrong.
    assert is_ok(fetched)
    assert fetched.value.created_at.tzinfo is not None


async def test_the_retention_purge_runs_on_postgres(
    pg_repository: SqlKitRepository,
    pg_sessions: async_sessionmaker[AsyncSession],
    tmp_path: Path,
    clock: MovableClock,
) -> None:
    # Arrange
    order = new_order()
    await pg_repository.create_order(order)
    await pg_repository.set_order_state(order.id, OrderState.AUTHORIZED, now=clock.now)
    await pg_repository.save_kit(build_kit(tmp_path, order.id))

    # Act
    result = await purge_expired(pg_sessions, now=clock.advance(days=100))

    # Assert — identity gone at 90 days, audio still there until 12 months.
    assert is_ok(result)
    assert result.value.brief_identities_purged == 1
    assert result.value.assets_deleted == 0
    assert is_err(await pg_repository.get_order(order.id))
    async with pg_sessions() as session:
        row = (
            await session.execute(sa.select(BriefRow).where(BriefRow.order_id == order.id))
        ).scalar_one()
    assert row.recipient_name_display is None
    assert row.occasion is not None


async def test_the_retention_class_enum_round_trips_on_postgres(
    pg_repository: SqlKitRepository,
    pg_sessions: async_sessionmaker[AsyncSession],
    tmp_path: Path,
    clock: MovableClock,
) -> None:
    # Arrange
    order = new_order()
    await pg_repository.create_order(order)
    await pg_repository.set_order_state(order.id, OrderState.AUTHORIZED, now=clock.now)
    await pg_repository.save_kit(build_kit(tmp_path, order.id))

    # Act
    async with pg_sessions() as session:
        stored = await session.scalar(
            sa.text(
                "SELECT retention_class FROM assets WHERE order_id = :order_id LIMIT 1"
            ).bindparams(order_id=order.id)
        )

    # Assert — the VARCHAR stores the enum VALUE, which is what every other layer speaks.
    assert stored == RetentionClass.PAID_AUDIO.value


async def test_generation_attempts_survive_on_postgres(
    pg_repository: SqlKitRepository,
    pg_sessions: async_sessionmaker[AsyncSession],
    tmp_path: Path,
    clock: MovableClock,
) -> None:
    # Arrange
    attempts = GenerationAttemptRepository(pg_sessions, clock=clock)
    order = new_order()
    await pg_repository.create_order(order)
    await pg_repository.save_kit(build_kit(tmp_path, order.id))

    # Act
    stats = await attempts.strategy_stats()

    # Assert — the verdict written by save_kit is visible to the tuning query.
    assert is_ok(stats)
    assert stats.value[0].strategy is NameStrategy.STRIPPED
    assert stats.value[0].attempts == 1


# ---------------------------------------------------------------------------
# The entitlement race — the one guarantee SQLite structurally cannot prove
# ---------------------------------------------------------------------------
async def test_two_concurrent_charges_on_one_credit_produce_exactly_one_render(
    pg_sessions: async_sessionmaker[AsyncSession], clock: MovableClock
) -> None:
    # Arrange — the whole correctness argument for the entitlement layer rests on
    # `UPDATE … SET balance = balance - :cost WHERE balance >= :cost` being race-free under
    # Postgres READ COMMITTED (EvalPlanQual re-evaluates the predicate against the row the
    # winner committed). The unit suite CANNOT test this: tests/test_db/conftest.py runs
    # SQLite in-memory behind a StaticPool with one shared connection, so two AsyncSessions
    # there are never genuinely simultaneous. This is the only honest home for it.
    #
    # The allowance is switched off and the in-flight cap widened so that the BALANCE is
    # unambiguously the thing that refuses the loser: with the shipped cap of 1, the second
    # charge would be refused for being a second render rather than for being unaffordable.
    ledger = SqlCreditLedger(
        pg_sessions,
        clock=clock,
        policy=EntitlementPolicy(allowance_credits=0, max_orders_in_flight=5),
    )
    telegram_user_id = 8_912_345_678_901
    seeded = await ledger.grant(
        telegram_user_id=telegram_user_id,
        credits=1,
        idempotency_key="grant:admin:race-seed",
        actor="admin:test",
    )
    assert is_ok(seeded)

    # Act — two distinct orders, one credit, genuinely concurrent connections.
    first, second = await asyncio.gather(
        ledger.charge(telegram_user_id=telegram_user_id, order_id=uuid4(), actor="pipeline"),
        ledger.charge(telegram_user_id=telegram_user_id, order_id=uuid4(), actor="pipeline"),
    )

    # Assert — exactly one winner, one typed refusal, and no negative balance anywhere.
    outcomes = [first, second]
    winners = [result for result in outcomes if is_ok(result)]
    losers = [result for result in outcomes if is_err(result)]
    assert len(winners) == 1
    assert winners[0].value[0] is ChargeOutcome.CHARGED
    assert len(losers) == 1
    assert isinstance(losers[0].error, InsufficientCreditsError)
    async with pg_sessions() as session:
        assert await verify_balances(session) == ()
        balance = await session.scalar(
            sa.select(CreditAccountRow.balance).where(
                CreditAccountRow.telegram_user_id == telegram_user_id
            )
        )
        debits = await session.scalar(
            sa.select(sa.func.count())
            .select_from(CreditLedgerRow)
            .where(CreditLedgerRow.kind == CreditEntryKind.DEBIT)
        )
    assert balance == 0
    # The loser's whole transaction rolled back, so it left no half-written debit behind.
    assert debits == 1
