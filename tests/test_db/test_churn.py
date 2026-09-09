"""Churn writes, against a real database: the transition guard is the whole subject.

Every test here is about the same property from a different side — that a row on
``bot_membership_events`` records a PASSAGE and not a state, so a count of them never
changes retroactively. That property is what the events table exists for, and it is bought
entirely by the predicate-guarded ``UPDATE`` in :mod:`hbd.db.churn`; a refactor to
read-then-write would pass none of the second, third or last tests below.

The separation of ``users.is_blocked`` (the OPERATOR barred an account) from
``users.blocked_bot_at`` (the CUSTOMER blocked the bot) is asserted rather than documented,
because the two are one typo apart and the dashboard draws them as different cards.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from hbd.contracts import BotBlockSource, BotMembershipEvent, Ok
from hbd.db.churn import SqlBotBlocks, anonymise_bot_membership_events
from hbd.db.credits import set_blocked, touch
from hbd.db.models.bot_membership_event import BotMembershipEventRow
from hbd.db.models.user import UserRow
from hbd.db.users_sql import DEFAULT_UI_LANGUAGE

pytestmark = pytest.mark.anyio

#: Mid-day, so a test that advances by a day cannot pass by accident on a boundary.
_NOON: datetime = datetime(2026, 9, 7, 12, 0, tzinfo=UTC)
_LATER: datetime = _NOON + timedelta(hours=3)
_LATER_STILL: datetime = _NOON + timedelta(hours=6)

_ALICE = 71_001
_BOB = 71_002


async def _block(
    store: SqlBotBlocks,
    *,
    who: int = _ALICE,
    at: datetime = _NOON,
    source: BotBlockSource = BotBlockSource.MEMBERSHIP_UPDATE,
) -> bool:
    """One recorded block, unwrapped. Every call in this module expects an ``Ok``."""
    result = await store.record_bot_blocked(who, at=at, source=source)
    assert isinstance(result, Ok), result
    return result.value


async def _unblock(
    store: SqlBotBlocks,
    *,
    who: int = _ALICE,
    at: datetime = _LATER,
    source: BotBlockSource = BotBlockSource.MEMBERSHIP_UPDATE,
) -> bool:
    result = await store.record_bot_unblocked(who, at=at, source=source)
    assert isinstance(result, Ok), result
    return result.value


async def _events(
    sessions: async_sessionmaker[AsyncSession], *, who: int | None = _ALICE
) -> list[BotMembershipEventRow]:
    """Every event row for one account, oldest first."""
    async with sessions() as session:
        rows = await session.scalars(
            sa.select(BotMembershipEventRow)
            .where(
                BotMembershipEventRow.telegram_user_id.is_(None)
                if who is None
                else BotMembershipEventRow.telegram_user_id == who
            )
            .order_by(BotMembershipEventRow.at)
        )
        return list(rows)


async def _user(sessions: async_sessionmaker[AsyncSession], *, who: int = _ALICE) -> UserRow | None:
    async with sessions() as session:
        found: UserRow | None = await session.scalar(
            sa.select(UserRow).where(UserRow.telegram_user_id == who)
        )
        return found


async def _seed_user(sessions: async_sessionmaker[AsyncSession], *, who: int = _ALICE) -> None:
    """An ordinary account that has spoken to the bot, created the way traffic creates one."""
    async with sessions.begin() as session:
        await touch(session, telegram_user_id=who, ui_language=None, now=_NOON)


async def test_the_first_block_sets_the_column_and_writes_one_event(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    # Arrange
    await _seed_user(sessions)
    store = SqlBotBlocks(sessions)

    # Act
    recorded = await _block(store)

    # Assert
    assert recorded is True, "the first block is the passage and must say so"
    user = await _user(sessions)
    assert user is not None
    assert user.blocked_bot_at == _NOON
    (event,) = await _events(sessions)
    assert event.event is BotMembershipEvent.BLOCKED
    assert event.source is BotBlockSource.MEMBERSHIP_UPDATE
    assert event.at == _NOON


async def test_a_second_block_records_nothing_and_does_not_move_the_first_instant(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    """THE TRANSITION GUARD, which is also the abuse rail.

    The ``my_chat_member`` observer carries no throttle, so this is the only thing bounding
    a customer who toggles block/unblock — and it bounds it by the number of REAL passages,
    which is tighter than any counter. It is also what keeps the two writers (the handler
    and the worker's delivery arm) from both recording one departure.
    """
    # Arrange
    await _seed_user(sessions)
    store = SqlBotBlocks(sessions)
    await _block(store)

    # Act — the delivery arm, arriving after the membership update already recorded it.
    recorded = await _block(store, at=_LATER, source=BotBlockSource.DELIVERY_REFUSAL)

    # Assert
    assert recorded is False
    assert len(await _events(sessions)) == 1, "a second row would double-count one departure"
    user = await _user(sessions)
    assert user is not None
    assert user.blocked_bot_at == _NOON, "the ORIGINAL instant is the one worth keeping"


async def test_an_unblock_clears_the_column_and_writes_its_own_event(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    # Arrange
    await _seed_user(sessions)
    store = SqlBotBlocks(sessions)
    await _block(store)

    # Act
    recorded = await _unblock(store)

    # Assert
    assert recorded is True
    user = await _user(sessions)
    assert user is not None
    assert user.blocked_bot_at is None
    blocked, unblocked = await _events(sessions)
    assert blocked.event is BotMembershipEvent.BLOCKED
    assert unblocked.event is BotMembershipEvent.UNBLOCKED
    assert unblocked.at == _LATER


async def test_unblocking_an_account_that_is_not_blocked_records_nothing(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    """First contact is the ordinary case here, not an edge one.

    Telegram sends ``my_chat_member`` the first time anybody presses Start (``left`` →
    ``member``), so this path runs for people who have never blocked anything. An
    "unblocked" row for them would be a win-back the dashboard could not justify.
    """
    # Arrange
    await _seed_user(sessions)
    store = SqlBotBlocks(sessions)

    # Act
    recorded = await _unblock(store, at=_NOON)

    # Assert
    assert recorded is False
    assert await _events(sessions) == []


async def test_a_block_for_an_account_with_no_row_creates_one_and_still_records_the_event(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    """The population this write path exists for, and the branch a rowcount alone would miss.

    An account that has not spoken since the last deploy has no ``users`` row, and it is
    precisely the account whose block we need. The UPSERT inserts the row with the column
    already set, so the conditional ``UPDATE`` after it matches nothing — an implementation
    trusting that rowcount would create the row and write no event at all.
    """
    # Arrange — deliberately NO seeded user.
    store = SqlBotBlocks(sessions)

    # Act
    recorded = await _block(store, who=_BOB)

    # Assert
    assert recorded is True
    user = await _user(sessions, who=_BOB)
    assert user is not None
    assert user.blocked_bot_at == _NOON
    assert user.ui_language is DEFAULT_UI_LANGUAGE
    assert user.is_blocked is False, "learning of a block must never bar the account"
    assert len(await _events(sessions, who=_BOB)) == 1


async def test_an_unblock_for_an_account_with_no_row_creates_one_and_records_nothing(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    """The mirror of the test above, and deliberately NOT symmetrical with it."""
    # Arrange / Act
    store = SqlBotBlocks(sessions)
    recorded = await _unblock(store, who=_BOB, at=_NOON)

    # Assert
    assert recorded is False
    user = await _user(sessions, who=_BOB)
    assert user is not None, "we have now seen this account, so it gets a row"
    assert user.blocked_bot_at is None
    assert await _events(sessions, who=_BOB) == []


async def test_the_operator_bar_and_the_customer_block_never_touch_each_other(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    """One typo apart, opposite meanings, two separate cards on the dashboard.

    ``is_blocked`` is an operator barring an account; ``blocked_bot_at`` is a customer
    blocking the bot. Neither is derived from the other and no query may OR them, so the
    independence is asserted here rather than left to the docstrings that claim it.
    """
    # Arrange
    store = SqlBotBlocks(sessions)
    async with sessions.begin() as session:
        await set_blocked(session, telegram_user_id=_ALICE, is_blocked=True, now=_NOON)

    # Act — a DIFFERENT account blocks the bot of its own accord.
    await _block(store, who=_BOB)

    # Assert
    barred = await _user(sessions, who=_ALICE)
    assert barred is not None
    assert barred.is_blocked is True
    assert barred.blocked_bot_at is None, "an operator's bar is not a customer's block"
    left = await _user(sessions, who=_BOB)
    assert left is not None
    assert left.blocked_bot_at is not None
    assert left.is_blocked is False, "a customer's block is not an operator's bar"


async def test_an_ordinary_touch_never_clears_a_recorded_block(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    """Cheap insurance against the one leak that would be silent and total.

    ``credits.touch`` UPSERTs the ``users`` row on every inbound update. If
    ``blocked_bot_at`` ever reached its ``ON CONFLICT`` set clause, a customer's block would
    be cleared by their next message — the identical defect ``touch``'s own docstring
    records for ``is_blocked``, and the churn gauge would read zero for a reason nobody
    could see.
    """
    # Arrange
    await _seed_user(sessions)
    store = SqlBotBlocks(sessions)
    await _block(store)

    # Act
    async with sessions.begin() as session:
        await touch(session, telegram_user_id=_ALICE, ui_language=None, now=_LATER)

    # Assert
    user = await _user(sessions)
    assert user is not None
    assert user.blocked_bot_at == _NOON


async def test_a_block_an_unblock_and_a_re_block_leave_two_blocks_in_the_history(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    """THE TEST THAT PAYS FOR THE EVENTS TABLE.

    A column alone can only count SURVIVORS. This account blocked, came back and blocked
    again: the history says two departures and one win-back, and the gauge says one account
    unreachable right now. No column-only design can produce both numbers, and a churn
    series built from the column would have quietly lost the first departure the moment the
    customer returned.
    """
    # Arrange
    await _seed_user(sessions)
    store = SqlBotBlocks(sessions)

    # Act
    assert await _block(store, at=_NOON) is True
    assert await _unblock(store, at=_LATER) is True
    assert await _block(store, at=_LATER_STILL) is True

    # Assert — the passages.
    events = await _events(sessions)
    kinds = [event.event for event in events]
    assert kinds == [
        BotMembershipEvent.BLOCKED,
        BotMembershipEvent.UNBLOCKED,
        BotMembershipEvent.BLOCKED,
    ]
    # Assert — the gauge, which is a different question with a different answer.
    async with sessions() as session:
        unreachable = await session.scalar(
            sa.select(sa.func.count())
            .select_from(UserRow)
            .where(UserRow.blocked_bot_at.is_not(None))
        )
    assert unreachable == 1


async def test_the_source_of_each_passage_survives_beside_it(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    """An instant inferred from a refused send is a weaker fact than one Telegram stamped.

    The same provenance discipline ``vendor_usage.cost_source`` applies to money: a reader
    who cannot tell the two apart is reading a guess as a measurement.
    """
    # Arrange / Act
    store = SqlBotBlocks(sessions)
    await _block(store, who=_ALICE, source=BotBlockSource.MEMBERSHIP_UPDATE)
    await _block(store, who=_BOB, at=_LATER, source=BotBlockSource.DELIVERY_REFUSAL)

    # Assert
    (from_telegram,) = await _events(sessions, who=_ALICE)
    (from_a_refusal,) = await _events(sessions, who=_BOB)
    assert from_telegram.source is BotBlockSource.MEMBERSHIP_UPDATE
    assert from_a_refusal.source is BotBlockSource.DELIVERY_REFUSAL


async def test_erasure_removes_the_identity_and_keeps_every_passage(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    """The property the whole design turns on: a ``/forget`` must not shrink the history.

    Deleting these rows would make the churn series drop retroactively by the number of
    people who asked to be forgotten — which is exactly the defect (a historical count that
    changes after the fact) the events table was created to avoid. So the id comes off and
    the row stays, and the per-day counts are byte-identical either side of the erasure.
    """
    # Arrange
    store = SqlBotBlocks(sessions)
    await _block(store, at=_NOON)
    await _unblock(store, at=_LATER)
    before = [(row.event, row.source, row.at) for row in await _events(sessions)]

    # Act
    async with sessions.begin() as session:
        touched = await anonymise_bot_membership_events(session, telegram_user_id=_ALICE)

    # Assert
    assert touched == 2
    assert await _events(sessions, who=_ALICE) == []
    anonymous = await _events(sessions, who=None)
    assert [(row.event, row.source, row.at) for row in anonymous] == before

    # And it is idempotent: a second erasure matches nothing.
    async with sessions.begin() as session:
        assert await anonymise_bot_membership_events(session, telegram_user_id=_ALICE) == 0


async def test_erasure_leaves_the_gauge_alone(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    """A forgotten customer who still has the bot blocked is still unreachable.

    ``/forget`` deliberately does NOT clear ``users.blocked_bot_at``, on the same footing as
    ``is_blocked`` and ``last_seen_at``: the ``users`` row exists precisely so a block can
    outlive an erasure, and clearing it would make the gauge count them as reachable.
    """
    # Arrange
    store = SqlBotBlocks(sessions)
    await _block(store)

    # Act
    async with sessions.begin() as session:
        await anonymise_bot_membership_events(session, telegram_user_id=_ALICE)

    # Assert
    user = await _user(sessions)
    assert user is not None
    assert user.blocked_bot_at == _NOON
