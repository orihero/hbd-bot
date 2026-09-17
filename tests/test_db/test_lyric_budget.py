"""The daily lyric-write budget, against a real database.

The property that matters is DURABILITY, and it is asserted the only way it can honestly be
asserted at this layer: by building a second :class:`~bayram.db.lyric_budget.SqlLyricBudget`
over the same engine and showing the count is still there. A store object is what a process
holds, so "a new store sees the old count" is exactly "a restart does not hand the budget
back" — which is the whole reason this is a row and not the in-memory window
``bayram.ratelimit`` uses for the inbound throttle.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from bayram.contracts import Ok
from bayram.db.lyric_budget import SqlLyricBudget
from bayram.db.models.lyric_budget import LyricBudgetRow
from bayram.lyric_budget import LyricBudgetPolicy, LyricBudgetVerdict

pytestmark = pytest.mark.anyio

#: Mid-day, so a test that advances by a day cannot pass by accident on a boundary.
_NOON: datetime = datetime(2026, 8, 30, 12, 0, tzinfo=UTC)

_ALICE = 51_001
_BOB = 51_002


def _budget(
    sessions: async_sessionmaker[AsyncSession], *, writes_per_day: int = 3
) -> SqlLyricBudget:
    return SqlLyricBudget(sessions, policy=LyricBudgetPolicy(writes_per_day=writes_per_day))


async def _claim(store: SqlLyricBudget, *, at: datetime, who: int = _ALICE) -> LyricBudgetVerdict:
    """One claim, unwrapped. Every call in this module expects an ``Ok``."""
    result = await store.claim_lyric_write(who, now=at)
    assert isinstance(result, Ok), result
    return result.value


async def test_the_first_write_of_the_day_opens_a_row_and_is_allowed(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    # Arrange
    store = _budget(sessions)

    # Act
    verdict = await _claim(store, at=_NOON)

    # Assert — the account had no row at all; the claim is what opens one.
    assert verdict.is_allowed is True
    assert verdict.used == 1
    assert verdict.limit == 3


async def test_each_write_of_the_same_day_increments_the_same_row(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    # Arrange
    store = _budget(sessions)

    # Act
    counts = [(await _claim(store, at=_NOON)).used for _ in range(3)]

    # Assert — one row, not one per claim.
    assert counts == [1, 2, 3]
    async with sessions() as session:
        rows = await session.scalar(sa.select(sa.func.count()).select_from(LyricBudgetRow))
    assert rows == 1


async def test_the_write_that_passes_the_ceiling_is_refused(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    # Arrange
    store = _budget(sessions, writes_per_day=2)
    await _claim(store, at=_NOON)
    await _claim(store, at=_NOON)

    # Act
    verdict = await _claim(store, at=_NOON)

    # Assert
    assert verdict.is_allowed is False
    assert verdict.used == 3
    assert verdict.limit == 2


async def test_a_refused_write_still_counts_so_the_ceiling_cannot_be_sat_on(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    # Arrange — one over the line already.
    store = _budget(sessions, writes_per_day=1)
    await _claim(store, at=_NOON)
    await _claim(store, at=_NOON)

    # Act
    verdict = await _claim(store, at=_NOON)

    # Assert — the count keeps climbing, which is what makes the refusal permanent for the
    # day rather than a line a caller can keep re-testing at zero cost.
    assert verdict.used == 3
    assert verdict.is_allowed is False


async def test_the_budget_opens_again_the_next_day(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    # Arrange — spent, and refused, today.
    store = _budget(sessions, writes_per_day=1)
    await _claim(store, at=_NOON)
    spent = await _claim(store, at=_NOON)
    assert spent.is_allowed is False

    # Act — the same account, one day later.
    tomorrow = await _claim(store, at=_NOON + timedelta(days=1))

    # Assert — rolled over in place: the count restarts, no sweep required.
    assert tomorrow.is_allowed is True
    assert tomorrow.used == 1


async def test_the_refusal_names_the_moment_the_budget_comes_back(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    # Arrange
    store = _budget(sessions, writes_per_day=1)
    await _claim(store, at=_NOON)

    # Act
    verdict = await _claim(store, at=_NOON)

    # Assert — midnight UTC after the day the claim was made in, which is exactly when the
    # next claim starts a new count. That instant is what the refusal copy renders.
    assert verdict.resets_at == datetime(2026, 8, 31, tzinfo=UTC)


async def test_two_accounts_do_not_share_a_budget(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    # Arrange
    store = _budget(sessions, writes_per_day=1)
    await _claim(store, at=_NOON, who=_ALICE)

    # Act
    bob = await _claim(store, at=_NOON, who=_BOB)

    # Assert
    assert bob.is_allowed is True
    assert bob.used == 1


async def test_a_new_store_over_the_same_database_sees_the_count_already_spent(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    """A restart must not hand the budget back. This is the whole reason it is a row."""
    # Arrange — spend the day through one store, then throw that store away.
    first = _budget(sessions, writes_per_day=2)
    await _claim(first, at=_NOON)
    await _claim(first, at=_NOON)

    # Act — a brand-new store, as a restarted process would build.
    restarted = _budget(sessions, writes_per_day=2)
    verdict = await _claim(restarted, at=_NOON)

    # Assert — the count continued rather than starting over.
    assert verdict.used == 3
    assert verdict.is_allowed is False


async def test_a_store_that_cannot_reach_its_database_returns_an_err_and_never_raises(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    # Arrange — the table the claim writes is gone under it.
    store = _budget(sessions)
    async with sessions.begin() as session:
        await session.execute(sa.text("DROP TABLE lyric_budgets"))

    # Act
    result = await store.claim_lyric_write(_ALICE, now=_NOON)

    # Assert — a typed Err, because the gate at the lyric step must not need a ``try``.
    assert not isinstance(result, Ok)
