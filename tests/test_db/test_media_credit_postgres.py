"""Two 🎟 taps racing on real Postgres (IMAGE_VIDEO_SPEC §3.2.2, §10 M5.2). ``integration``.

SQLite serialises every writer, so the unit suite can only show the second tap arriving
after the first. Here the two spends run on two connections at once, and the only thing
between them is what §3.2.2 says is the concurrency control: ``balance = balance - 1 WHERE
balance >= 1`` (row-locked by Postgres) and the job's conditional ``quoted → paid``. No
``SELECT … FOR UPDATE`` exists to lean on.

Requires ``docker compose up -d`` (or ``BAYRAM_TEST_POSTGRES_URL``).
"""

from __future__ import annotations

import asyncio
import os
from collections.abc import AsyncIterator
from datetime import timedelta
from typing import Final
from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from bayram.contracts import Language
from bayram.db.engine import create_engine, create_session_factory, ping
from bayram.db.enums import (
    MediaAspect,
    MediaCreditReason,
    MediaJobState,
    MediaKind,
    MediaPaidVia,
    MediaSku,
)
from bayram.db.media import (
    create_job,
    grant_refund,
    load_job,
    mark_paid,
    media_balance,
    spend_credit,
    transition,
)
from bayram.db.models import Base, MediaCreditLedgerRow, MediaPurchaseRow, UserRow
from tests.test_db.conftest import MovableClock

pytestmark = pytest.mark.integration

_POSTGRES_URL: Final[str] = os.environ.get(
    "BAYRAM_TEST_POSTGRES_URL", "postgresql+asyncpg://hbd:hbd@localhost:5432/hbd_test"
)
_USER: Final[int] = 8_912_345_678_903
_DEADLINE: Final[timedelta] = timedelta(minutes=45)


@pytest.fixture
async def pg_engine() -> AsyncIterator[AsyncEngine]:
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


async def _quoted(sessions: async_sessionmaker[AsyncSession], clock: MovableClock) -> UUID:
    async with sessions.begin() as session:
        user_id = await session.scalar(
            sa.select(UserRow.id).where(UserRow.telegram_user_id == _USER)
        )
        if user_id is None:
            user_id = uuid4()
            session.add(UserRow(id=user_id, telegram_user_id=_USER))
            await session.flush()
        job_id = await create_job(
            session,
            user_id=user_id,
            telegram_user_id=_USER,
            kind=MediaKind.IMAGE,
            sku=MediaSku.IMAGE,
            state=MediaJobState.SCREENING,
            chat_id=_USER,
            outputs_requested=2,
            aspect=MediaAspect.PORTRAIT,
            language=Language.EN,
            prompt="a cake on a rooftop at dusk",
            price_minor=500_000,
            currency="UZS",
            now=clock.now,
            quote_ttl=timedelta(hours=24),
        )
        assert await transition(
            session,
            job_id,
            expected=(MediaJobState.SCREENING,),
            to=MediaJobState.QUOTED,
            now=clock.now,
        )
    return job_id


async def _credits(
    sessions: async_sessionmaker[AsyncSession], clock: MovableClock, count: int
) -> None:
    """``count`` refunded image failures, one after another (one open request per kind)."""
    for _ in range(count):
        job_id = await _quoted(sessions, clock)
        async with sessions.begin() as session:
            assert await mark_paid(
                session, job_id, paid_via=MediaPaidVia.PAYME, now=clock.now, deadline=_DEADLINE
            )
            assert await transition(
                session,
                job_id,
                expected=(MediaJobState.PAID,),
                to=MediaJobState.FAILED,
                now=clock.now,
            )
            assert await grant_refund(
                session, job_id, reason=MediaCreditReason.GENERATION_FAILED, now=clock.now
            )


async def _tap(
    sessions: async_sessionmaker[AsyncSession], job_id: UUID, clock: MovableClock
) -> bool:
    async with sessions.begin() as session:
        return await spend_credit(session, job_id, now=clock.now, deadline=_DEADLINE)


@pytest.mark.parametrize("held", [1, 2])
async def test_two_concurrent_taps_spend_one_credit_and_pay_the_job_once(
    pg_sessions: async_sessionmaker[AsyncSession], clock: MovableClock, held: int
) -> None:
    # Arrange — ``held`` credits and one quoted request. With two credits the balance
    # predicate lets both debits through and the job's own conditional move decides.
    await _credits(pg_sessions, clock, held)
    job_id = await _quoted(pg_sessions, clock)

    # Act — two genuinely concurrent connections.
    outcomes = await asyncio.gather(
        _tap(pg_sessions, job_id, clock), _tap(pg_sessions, job_id, clock)
    )

    # Assert — one spend, one receipt, one paid job; the ledger still sums to the balance.
    assert sorted(outcomes) == [False, True]
    async with pg_sessions() as session:
        job = await load_job(session, job_id)
        balance = await media_balance(session, telegram_user_id=_USER, sku=MediaSku.IMAGE)
        total = await session.scalar(
            sa.select(sa.func.sum(MediaCreditLedgerRow.delta)).where(
                MediaCreditLedgerRow.telegram_user_id == _USER
            )
        )
        spends = await session.scalar(
            sa.select(sa.func.count())
            .select_from(MediaCreditLedgerRow)
            .where(MediaCreditLedgerRow.reason == MediaCreditReason.SPENT)
        )
        receipts = await session.scalar(
            sa.select(sa.func.count())
            .select_from(MediaPurchaseRow)
            .where(MediaPurchaseRow.job_id == job_id)
        )
    assert job is not None and job.state is MediaJobState.PAID
    assert job.paid_via is MediaPaidVia.CREDIT
    assert balance == total == held - 1
    assert (spends, receipts) == (1, 1)
