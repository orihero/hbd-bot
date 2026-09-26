"""``attention_counts`` — the three populations, their boundaries, and the parity that binds
them to the list they link to.

The file exists for three specific regressions, each of which ships a screen that is wrong in
a way nobody notices:

* **The stale boundary is EXCLUSIVE.** ``bayram.payme.rules.is_expired`` compares with a strict
  ``>`` because Payme's own reference implementations do, and the two readings differ in
  DIRECTION. An inclusive boundary lists a payment as stuck at the instant the rail would still
  perform it, and an operator acting on that is intervening in a live charge.
* **An erased buyer is NOT in the unannounced backlog.** There is nobody to tell, so
  ``notified_at`` will never be stamped and the row would sit in the count for the life of the
  deployment. A count that never drains is a count operators learn to ignore, on the one screen
  where every other number is actionable.
* **The chip and the list compute ONE predicate.** Each population's clause is a module-private
  helper called by both :func:`attention_counts` and :func:`list_intents`, and the last test
  here asserts the two agree for every population on one seeded database. Spelling the
  predicate twice is how a board reads "4 stuck" and the list behind it shows three.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Final

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from bayram.db.admin.page import PageRequest
from bayram.db.admin.payment_intents import (
    AttentionPopulation,
    IntentFilters,
    attention_counts,
    count_intents,
    list_intents,
)
from bayram.db.enums import IntentProduct, PaymentIntentState, PaymeState
from tests.test_db.rail_helpers import (
    add,
    make_intent,
    make_plan_receipt,
    make_transaction,
    settle,
)

_NOW: Final[datetime] = datetime(2026, 9, 10, 12, 0, tzinfo=UTC)
#: The rail's default transaction window. Twelve hours, spelled as a timedelta because that is
#: what the read takes; ``DEFAULT_TRANSACTION_TIMEOUT_MS`` is where the number comes from.
_STALE_AFTER: Final[timedelta] = timedelta(hours=12)


async def _population_page(session: AsyncSession, *, population: AttentionPopulation) -> int:
    """How many rows the LIST returns for one population. See the parity test."""
    page = await list_intents(
        session,
        filters=IntentFilters(attention=population, now=_NOW, stale_after=_STALE_AFTER),
        request=PageRequest(limit=200),
    )
    return len(page.items)


async def _held(sessions: async_sessionmaker[AsyncSession], *, payme_time: datetime) -> None:
    """An ``awaiting`` intent whose holder transaction was created at ``payme_time``."""
    intent = make_intent(now=_NOW, state=PaymentIntentState.PENDING)
    await add(sessions, intent)
    transaction = make_transaction(intent_id=intent.id, payme_time=payme_time)
    await add(sessions, transaction)
    async with sessions.begin() as session:
        stored = await session.get(type(intent), intent.id)
        assert stored is not None
        stored.state = PaymentIntentState.AWAITING
        stored.active_transaction_id = transaction.id


async def test_a_holder_exactly_at_the_timeout_is_not_yet_stale(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    """**The boundary, and it is exclusive.** At exactly the timeout the window is still open.

    Matching :func:`bayram.payme.rules.is_expired`'s strict ``>``. The two readings differ by
    one millisecond and in direction: an inclusive boundary refuses — or here, ALARMS about — a
    payment the rail would still perform.
    """
    # Arrange
    await _held(sessions, payme_time=_NOW - _STALE_AFTER)

    # Act
    async with sessions() as session:
        counts = await attention_counts(session, now=_NOW, stale_after=_STALE_AFTER)

    # Assert
    assert counts.awaiting_held_past_timeout == 0


async def test_a_holder_one_second_past_the_timeout_is_stale(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    """The other side of the same boundary, so neither direction can regress alone."""
    # Arrange
    await _held(sessions, payme_time=_NOW - _STALE_AFTER - timedelta(seconds=1))

    # Act
    async with sessions() as session:
        counts = await attention_counts(session, now=_NOW, stale_after=_STALE_AFTER)

    # Assert
    assert counts.awaiting_held_past_timeout == 1


async def test_a_performed_holder_is_never_stale(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    """The population is ``created`` holders. A charge that went through is not stuck."""
    # Arrange — old enough to be stale on time alone, but the transaction succeeded.
    intent = make_intent(now=_NOW)
    await add(sessions, intent)
    transaction = make_transaction(
        intent_id=intent.id,
        payme_time=_NOW - timedelta(days=2),
        state=PaymeState.PERFORMED,
    )
    await add(sessions, transaction)
    async with sessions.begin() as session:
        stored = await session.get(type(intent), intent.id)
        assert stored is not None
        stored.state = PaymentIntentState.AWAITING
        stored.active_transaction_id = transaction.id

    # Act
    async with sessions() as session:
        counts = await attention_counts(session, now=_NOW, stale_after=_STALE_AFTER)

    # Assert
    assert counts.awaiting_held_past_timeout == 0


async def test_an_erased_buyer_is_excluded_from_the_unannounced_backlog(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    """**The one that produces an undrainable backlog.** Assert it explicitly.

    ``/forget`` ran, so ``telegram_user_id`` is NULL, so there is nobody to tell and
    ``notified_at`` will never be stamped. Mirrors ``payme_sql.unnotified_settled_intents``
    exactly, and the mirroring is the reason a second reader is acceptable at all.
    """
    # Arrange — one erased paid intent and one identified one, both never announced.
    erased = settle(make_intent(now=_NOW, telegram_user_id=None), at=_NOW)
    identified = settle(make_intent(now=_NOW), at=_NOW)
    await add(sessions, erased, identified)

    # Act
    async with sessions() as session:
        counts = await attention_counts(session, now=_NOW, stale_after=_STALE_AFTER)

    # Assert
    assert counts.paid_never_announced == 1


async def test_an_announced_payment_leaves_the_backlog(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    """``notified_at`` is a second clock and not a flag on the first — stamping it is the exit."""
    # Arrange
    told = settle(make_intent(now=_NOW), at=_NOW)
    told.notified_at = _NOW
    await add(sessions, told)

    # Act
    async with sessions() as session:
        counts = await attention_counts(session, now=_NOW, stale_after=_STALE_AFTER)

    # Assert
    assert counts.paid_never_announced == 0


async def test_a_paid_intent_with_no_receipt_in_either_table_is_counted(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    """**Not a defect list.** This is what an erased buyer's settlement looks like.

    ``db/payme.py::_settle`` claims the intent and writes no sale when the buyer is gone: the
    money moved and there is nobody left to grant a credit to. It is also exactly what trips the
    settlement identity, which is why the two numbers are read together.
    """
    # Arrange
    orphan = settle(make_intent(now=_NOW, telegram_user_id=None), at=_NOW)
    with_plan = settle(make_intent(now=_NOW, product=IntentProduct.STARTER), at=_NOW)
    await add(sessions, orphan, with_plan)
    await add(sessions, make_plan_receipt(with_plan, at=_NOW))

    # Act
    async with sessions() as session:
        counts = await attention_counts(session, now=_NOW, stale_after=_STALE_AFTER)

    # Assert — the plan receipt counts as a receipt; only the orphan is in the population.
    assert counts.paid_with_no_receipt == 1


async def test_the_three_counts_are_all_zero_on_an_empty_table(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    """One statement, three subqueries, and a legible zero state — nothing stuck, nothing run."""
    # Act
    async with sessions() as session:
        counts = await attention_counts(session, now=_NOW, stale_after=_STALE_AFTER)

    # Assert
    assert (
        counts.awaiting_held_past_timeout,
        counts.paid_never_announced,
        counts.paid_with_no_receipt,
    ) == (0, 0, 0)


async def test_every_count_equals_the_list_it_links_to(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    """**The parity that justifies the shared predicate helpers.**

    A board chip is a link into the list; if the two computed the population separately, one
    would eventually be edited and the other not, and an operator would click "4 stuck" and be
    shown three rows with nothing on the page to explain the fourth.
    """
    # Arrange — one of each population, plus noise that belongs to none of them.
    await _held(sessions, payme_time=_NOW - _STALE_AFTER - timedelta(minutes=1))
    await _held(sessions, payme_time=_NOW - timedelta(minutes=1))
    unannounced = settle(make_intent(now=_NOW), at=_NOW)
    orphan = settle(make_intent(now=_NOW, telegram_user_id=None), at=_NOW)
    told = settle(make_intent(now=_NOW), at=_NOW)
    told.notified_at = _NOW
    await add(sessions, unannounced, orphan, told, make_intent(now=_NOW))

    # Act
    async with sessions() as session:
        counts = await attention_counts(session, now=_NOW, stale_after=_STALE_AFTER)
        totals = {
            population: (
                await count_intents(
                    session,
                    filters=IntentFilters(attention=population, now=_NOW, stale_after=_STALE_AFTER),
                )
            ).total
            for population in AttentionPopulation
        }
        listed = {
            population: await _population_page(session, population=population)
            for population in AttentionPopulation
        }

    # Assert — the count, its bounded total and the page all agree, for all three.
    assert counts.awaiting_held_past_timeout == totals[AttentionPopulation.AWAITING_STALE]
    assert counts.paid_never_announced == totals[AttentionPopulation.PAID_UNNOTIFIED]
    assert counts.paid_with_no_receipt == totals[AttentionPopulation.PAID_NO_RECEIPT]
    assert listed == totals


async def test_the_stale_population_refuses_a_filter_with_no_clock(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    """The backstop the router's 422 duplicates. Without it the failure is a ``TypeError``
    from inside a money query, whose traceback names arithmetic rather than the missing
    parameter."""
    # Act / Assert
    async with sessions() as session:
        with pytest.raises(ValueError, match="now and stale_after"):
            await count_intents(
                session, filters=IntentFilters(attention=AttentionPopulation.AWAITING_STALE)
            )
