"""``db.admin.payme_transactions`` — the rail's side of the story, on the rail's own clock.

Two properties earn a file of their own.

**The window is on ``payme_time`` and never on ``created_at``.** Theirs is when Payme created
the transaction; ours is when we heard about it, and the two differ by the network, by a retry
and, on a bad day, by however long this process was unavailable. The twelve-hour timeout, the
statement endpoint and the stale sweep all measure from theirs, by specification — so a panel
grouping on ours would disagree with every one of them about which day a payment happened, most
visibly for exactly the transactions that had trouble reaching us. The test seeds a row whose
two clocks fall in different windows, which is the only way to tell the two implementations
apart.

**The per-intent read is a NARRATIVE, oldest first.** "Card declined at 14:02, retried at
14:04, performed at 14:05" is the sentence an operator is assembling, and this package's
newest-first list convention would make them read it backwards.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Final
from uuid import uuid4

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from bayram.db.admin.payme_transactions import (
    has_recorded_transaction,
    transaction_funnel,
    transactions_for_intent,
)
from bayram.db.admin.sql import TimeWindow
from bayram.db.enums import PaymeState
from bayram.payme.protocol import CancelReason
from tests.test_db.rail_helpers import add, make_intent, make_transaction

_NOW: Final[datetime] = datetime(2026, 9, 10, 12, 0, tzinfo=UTC)


async def test_the_probe_is_false_until_the_rail_opens_a_transaction(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    """False beside a TRUE inbound-call probe is this deployment's state right now.

    The gateway answers Payme's checks behind the tunnel long before ``CHECKOUT_PROVIDER`` is
    switched over, so "we have heard from them and nobody has bought anything" is a legible
    state and not a contradiction.
    """
    # Arrange
    async with sessions() as session:
        assert await has_recorded_transaction(session) is False

    intent = make_intent(now=_NOW)
    await add(sessions, intent)
    await add(sessions, make_transaction(intent_id=intent.id, payme_time=_NOW))

    # Act / Assert
    async with sessions() as session:
        assert await has_recorded_transaction(session) is True


async def test_the_funnel_omits_states_with_no_rows(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    """``cancelled_after_perform`` is written by nothing here — a permanent zero would be a
    heading describing something this system refuses to do."""
    # Arrange
    intent = make_intent(now=_NOW)
    await add(sessions, intent)
    await add(
        sessions,
        make_transaction(intent_id=intent.id, payme_time=_NOW, state=PaymeState.CREATED),
        make_transaction(intent_id=intent.id, payme_time=_NOW, state=PaymeState.PERFORMED),
    )

    # Act
    async with sessions() as session:
        funnel = await transaction_funnel(session)

    # Assert
    assert {row.state for row in funnel} == {"created", "performed"}
    assert all(row.count == 1 for row in funnel)


async def test_the_funnel_windows_on_the_rails_clock_and_not_on_ours(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    """**The assertion that separates the two implementations.**

    The transaction was created by Payme ten days ago and reached us today. Windowing on
    ``created_at`` would count it; windowing on ``payme_time`` — which is what the timeout, the
    statement endpoint and the sweep all use — does not.
    """
    # Arrange
    intent = make_intent(now=_NOW)
    await add(sessions, intent)
    await add(
        sessions,
        make_transaction(
            intent_id=intent.id,
            payme_time=_NOW - timedelta(days=10),
            created_at=_NOW,
            updated_at=_NOW,
        ),
    )

    # Act
    async with sessions() as session:
        recent = await transaction_funnel(
            session,
            window=TimeWindow(start=_NOW - timedelta(days=1), end=_NOW + timedelta(days=1)),
        )
        wide = await transaction_funnel(
            session,
            window=TimeWindow(start=_NOW - timedelta(days=30), end=_NOW + timedelta(days=1)),
        )

    # Assert
    assert recent == ()
    assert sum(row.count for row in wide) == 1


async def test_an_intents_transactions_read_oldest_first_with_every_clock(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    """The narrative, and the three persisted instants a replay has to be able to repeat."""
    # Arrange — a declined card, then a successful charge.
    intent = make_intent(now=_NOW)
    await add(sessions, intent)
    declined_at = _NOW - timedelta(minutes=3)
    await add(
        sessions,
        make_transaction(
            intent_id=intent.id,
            payme_time=_NOW,
            state=PaymeState.PERFORMED,
        ),
        make_transaction(
            intent_id=intent.id,
            payme_time=declined_at,
            state=PaymeState.CANCELLED,
            cancel_time=declined_at,
            cancel_reason=int(CancelReason.DEBIT_ERROR),
        ),
    )

    # Act
    async with sessions() as session:
        rows = await transactions_for_intent(session, intent_id=intent.id)

    # Assert
    assert [row.state for row in rows] == ["cancelled", "performed"]
    assert rows[0].cancel_time == declined_at
    # A BARE INTEGER by argued decision: the rail's vocabulary, named only at the presentation
    # edge, with the raw number always carried so a code they add tomorrow still renders.
    assert rows[0].cancel_reason == int(CancelReason.DEBIT_ERROR)
    assert rows[0].perform_time is None
    assert rows[1].perform_time == _NOW
    assert rows[1].cancel_reason is None


async def test_an_intent_the_rail_never_touched_returns_an_empty_tuple(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    """ "Payme has never opened a transaction against this" is itself the support answer."""
    # Act
    async with sessions() as session:
        rows = await transactions_for_intent(session, intent_id=uuid4())

    # Assert
    assert rows == ()
