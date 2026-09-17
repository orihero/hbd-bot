"""``settlement_snapshot`` — the identity an operator is allowed to assert, and its fourth term.

Two things are being pinned and they are different in kind.

**One: the first three numbers ARE ``payme_sql.settlement_counts``.** Not "agree with" — are.
The panel and the five-minute sweep must report the same three numbers about the same minute,
and the only way to guarantee that is to call the same statement. A test that merely checked
plausible values would pass on the day somebody re-derived them here with a boundary one
microsecond off, and the difference would be blamed on the money. So the assertion is a direct
comparison of the two functions' output over the same window.

**Two: the identity is ``performed + operator == receipts``, not ``performed == receipts``.**
A force-settled intent has no performed transaction at all. ``settlement_counts``' own
docstring states the two-way form because it describes the rail-only path; a panel that
rendered that form would make every use of the recovery button read as a defect, which is how
a monitoring alert gets muted. ``grants <= receipts`` is expected — a plan grants nothing at
purchase — and only ``grants > receipts`` is strictly impossible.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Final

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from bayram.db.admin.payment_intents import settlement_snapshot
from bayram.db.enums import IntentProduct, PaymeState
from bayram.db.payme_sql import settlement_counts
from bayram.payme.ports import OPERATOR_SETTLE_PREFIX
from tests.test_db.rail_helpers import (
    RAIL_NOTE,
    add,
    make_grant,
    make_intent,
    make_plan_receipt,
    make_topup_receipt,
    make_transaction,
    settle,
)

_NOW: Final[datetime] = datetime(2026, 9, 10, 12, 0, tzinfo=UTC)
_SINCE: Final[datetime] = _NOW - timedelta(hours=24)


async def test_every_number_is_zero_on_an_empty_table(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    """All four at zero — which is NOT a pass, and is why ``has_settled_any_intent`` exists."""
    # Act
    async with sessions() as session:
        snapshot = await settlement_snapshot(session, since=_SINCE, until=_NOW)

    # Assert
    assert (
        snapshot.transactions_performed,
        snapshot.receipts_written,
        snapshot.grants_written,
        snapshot.operator_settlements,
    ) == (0, 0, 0, 0)


async def test_the_first_three_numbers_are_settlement_counts_verbatim(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    """**Not "agree with" — ARE.** The panel and the sweep must not be two implementations."""
    # Arrange — a rail settlement with its receipt and its grant, and a plan sale beside it.
    single = settle(make_intent(now=_NOW), at=_NOW)
    plan = settle(make_intent(now=_NOW, product=IntentProduct.STARTER), at=_NOW)
    await add(sessions, single, plan)
    await add(
        sessions,
        make_transaction(intent_id=single.id, payme_time=_NOW, state=PaymeState.PERFORMED),
        make_topup_receipt(single, at=_NOW),
        make_grant(single, at=_NOW),
        make_plan_receipt(plan, at=_NOW),
    )

    # Act
    async with sessions() as session:
        snapshot = await settlement_snapshot(session, since=_SINCE, until=_NOW)
        counts = await settlement_counts(session, frm=_SINCE, to=_NOW)

    # Assert
    assert (
        snapshot.transactions_performed,
        snapshot.receipts_written,
        snapshot.grants_written,
    ) == counts


async def test_grants_are_the_single_song_subset_of_receipts(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    """``grants < receipts`` after a plan sale. Only ``grants > receipts`` is impossible."""
    # Arrange
    single = settle(make_intent(now=_NOW), at=_NOW)
    plan = settle(make_intent(now=_NOW, product=IntentProduct.STARTER), at=_NOW)
    await add(sessions, single, plan)
    await add(
        sessions,
        make_topup_receipt(single, at=_NOW),
        make_grant(single, at=_NOW),
        make_plan_receipt(plan, at=_NOW),
    )

    # Act
    async with sessions() as session:
        snapshot = await settlement_snapshot(session, since=_SINCE, until=_NOW)

    # Assert
    assert snapshot.receipts_written == 2
    assert snapshot.grants_written == 1


async def test_only_an_operator_note_counts_as_an_operator_settlement(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    """``settle_note LIKE 'operator:%'`` and nothing else. ``'payme'`` is the rail's own."""
    # Arrange
    by_rail = settle(make_intent(now=_NOW), at=_NOW, note=RAIL_NOTE)
    by_hand = settle(make_intent(now=_NOW), at=_NOW, note=f"{OPERATOR_SETTLE_PREFIX}INC-1")
    await add(sessions, by_rail, by_hand)

    # Act
    async with sessions() as session:
        snapshot = await settlement_snapshot(session, since=_SINCE, until=_NOW)

    # Assert
    assert snapshot.operator_settlements == 1


async def test_the_identity_holds_across_one_rail_settlement_and_one_force_settle(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    """**The whole point of the fourth number.**

    Two settlements, two receipts, and only ONE performed transaction — because a force-settled
    intent never had one. The two-way form would read as a mismatch here, and an operator who
    saw the recovery button reported as a defect would stop trusting the card.
    """
    # Arrange
    by_rail = settle(make_intent(now=_NOW), at=_NOW)
    by_hand = settle(make_intent(now=_NOW), at=_NOW, note=f"{OPERATOR_SETTLE_PREFIX}INC-2")
    await add(sessions, by_rail, by_hand)
    await add(
        sessions,
        make_transaction(intent_id=by_rail.id, payme_time=_NOW, state=PaymeState.PERFORMED),
        make_topup_receipt(by_rail, at=_NOW),
        make_grant(by_rail, at=_NOW),
        make_topup_receipt(by_hand, at=_NOW),
        make_grant(by_hand, at=_NOW),
    )

    # Act
    async with sessions() as session:
        snapshot = await settlement_snapshot(session, since=_SINCE, until=_NOW)

    # Assert — the honest identity, and the dishonest one stated so its failure is visible.
    assert (
        snapshot.transactions_performed + snapshot.operator_settlements == snapshot.receipts_written
    )
    assert snapshot.transactions_performed != snapshot.receipts_written
    assert snapshot.grants_written <= snapshot.receipts_written


async def test_a_settlement_outside_the_window_is_not_counted(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    """The window is on the settlement clocks — ``settled_at`` and ``perform_time``.

    Both indexed by revision 0025 for exactly this read.
    """
    # Arrange — settled two days ago, well outside a 24-hour window.
    old = settle(make_intent(now=_NOW), at=_NOW - timedelta(days=2))
    await add(sessions, old)
    await add(
        sessions,
        make_transaction(
            intent_id=old.id, payme_time=_NOW - timedelta(days=2), state=PaymeState.PERFORMED
        ),
        make_topup_receipt(old, at=_NOW - timedelta(days=2)),
    )

    # Act
    async with sessions() as session:
        snapshot = await settlement_snapshot(session, since=_SINCE, until=_NOW)

    # Assert
    assert (snapshot.transactions_performed, snapshot.receipts_written) == (0, 0)


async def test_an_erased_buyers_settlement_shows_as_a_performed_charge_with_no_receipt(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    """**The legitimate mismatch, pinned so nobody "repairs" it.**

    ``_settle`` claims the intent and writes NO sale when ``telegram_user_id IS NULL``: the
    money moved and there is nobody left to grant a credit to. The identity therefore does not
    balance, and the honest rendering is "buyer erased" with the money intact — never a
    discrepancy to fix, and never fraud.
    """
    # Arrange
    erased = settle(make_intent(now=_NOW, telegram_user_id=None), at=_NOW)
    await add(sessions, erased)
    await add(
        sessions,
        make_transaction(intent_id=erased.id, payme_time=_NOW, state=PaymeState.PERFORMED),
    )

    # Act
    async with sessions() as session:
        snapshot = await settlement_snapshot(session, since=_SINCE, until=_NOW)

    # Assert
    assert snapshot.transactions_performed == 1
    assert snapshot.receipts_written == 0
    assert (
        snapshot.transactions_performed + snapshot.operator_settlements != snapshot.receipts_written
    )
