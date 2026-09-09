"""``subscription_churn`` — the four counts, and the five ways they can quietly go wrong.

The read infers a renewal from a later receipt, because nothing in the schema records one.
That inference has five failure modes, and there is a test here for each of them because
none of them shows up as an exception — each just produces a plausible percentage:

* **A running plan counted as an ending.** ``plan_ends_at`` is a business clock that runs
  into the future, so any predicate on it that is not capped at ``now`` files a customer
  who is still mid-plan as lapsed. An operator's ``?to=`` can be next month and an absent
  window has no upper bound at all, so the cap has to be its own predicate.
* **An erased customer counted as a lapse.** ``/forget`` nulls ``telegram_user_id`` on the
  receipt, and a row with no identity cannot be followed to a later purchase by anybody.
  Dropping those into ``lapsed`` would report an exercised right as a wave of churn.
* **The three arms no longer partitioning the denominator.** ``renewed + lapsed +
  anonymised_ended == ended_plans`` is what makes the pair beside the rate readable at all,
  and it is asserted on every fixture below rather than in one test of its own.
* **A renewal probe that finds the wrong row.** The ``EXISTS`` is correlated on
  ``telegram_user_id`` and compares ``created_at`` strictly, and each of the three ways to
  break that — matching the row against itself, reversing the comparison, losing the
  correlation so any later receipt in the table renews everything — reports MORE loyalty
  than the book holds. Two fixtures below (a three-plan run by one holder, and one holder
  beside a stranger who bought afterwards) tell all four spellings apart.
* **A clock that was not passed.** ``now`` is a required keyword precisely so its absence
  is a ``TypeError`` and not an unbounded predicate on ``plan_ends_at`` that files every
  mid-plan customer as lapsed. The test for it asserts the exception, because the signature
  is the guard.

Rows are inserted through the ORM with explicit ``created_at`` and ``plan_ends_at`` values,
following ``test_admin_queries.py``: these tests assert counts computed by hand from the
fixture, which only means anything if the fixture's clocks are exactly what the test says.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Final

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from hbd.db.admin.plan_purchases import plan_liability, subscription_churn
from hbd.db.admin.sql import TimeWindow
from hbd.db.enums import PlanKind
from hbd.db.models import PlanPurchaseRow
from tests.conftest import FIXED_NOW

#: The instant every assertion here is read at. Plans end before it or after it, and exactly
#: one fixture puts a plan ON it — the boundary ``subscription_churn`` and ``plan_liability``
#: must resolve the same way, since a plan they disagree about is counted twice or by neither.
_NOW: Final[datetime] = FIXED_NOW
#: What the starter plan costs in tiyin. Irrelevant to churn and fixed so it cannot drift.
_PLAN_MINOR: Final[int] = 30_000_00
_SONGS: Final[int] = 12


async def _plan(
    sessions: async_sessionmaker[AsyncSession],
    *,
    telegram_user_id: int | None,
    bought: datetime,
    ends: datetime,
    key: str,
) -> None:
    """One receipt, with both of its clocks stated rather than defaulted."""
    async with sessions.begin() as session:
        session.add(
            PlanPurchaseRow(
                telegram_user_id=telegram_user_id,
                plan=PlanKind.STARTER,
                songs_included=_SONGS,
                songs_used=0,
                amount_minor=_PLAN_MINOR,
                currency="UZS",
                provider="stub",
                reference="stub-raw",
                idempotency_key=key,
                created_at=bought,
                updated_at=bought,
                plan_ends_at=ends,
            )
        )


async def test_a_later_receipt_is_a_renewal_and_a_lone_ended_plan_is_a_lapse(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    # Arrange — one holder who came back, one who did not. Both plans ended before `now`.
    await _plan(
        sessions,
        telegram_user_id=11,
        bought=_NOW - timedelta(days=60),
        ends=_NOW - timedelta(days=30),
        key="renewer-first",
    )
    await _plan(
        sessions,
        telegram_user_id=11,
        bought=_NOW - timedelta(days=29),
        ends=_NOW + timedelta(days=1),
        key="renewer-second",
    )
    await _plan(
        sessions,
        telegram_user_id=22,
        bought=_NOW - timedelta(days=60),
        ends=_NOW - timedelta(days=30),
        key="lapser-only",
    )

    # Act
    async with sessions() as session:
        churn = await subscription_churn(session, now=_NOW)

    # Assert — the renewer's own second plan is still running and is NOT in the denominator.
    assert churn.ended_plans == 2
    assert churn.renewed == 1
    assert churn.lapsed == 1
    assert churn.anonymised_ended == 0
    assert churn.rate == 0.5
    assert churn.renewed + churn.lapsed + churn.anonymised_ended == churn.ended_plans


async def test_an_anonymised_ending_is_its_own_arm_and_never_a_lapse(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    # Arrange — `/forget` leaves the receipt and takes the identity: one ended row, no holder.
    await _plan(
        sessions,
        telegram_user_id=None,
        bought=_NOW - timedelta(days=60),
        ends=_NOW - timedelta(days=30),
        key="erased",
    )
    await _plan(
        sessions,
        telegram_user_id=33,
        bought=_NOW - timedelta(days=60),
        ends=_NOW - timedelta(days=30),
        key="lapser",
    )

    # Act
    async with sessions() as session:
        churn = await subscription_churn(session, now=_NOW)

    # Assert — the erased ending is published, not folded into the count beside it.
    assert churn.ended_plans == 2
    assert churn.renewed == 0
    assert churn.lapsed == 1
    assert churn.anonymised_ended == 1
    assert churn.renewed + churn.lapsed + churn.anonymised_ended == churn.ended_plans
    # The rate divides by the whole denominator, so it is a floor and never a fabrication.
    assert churn.rate == 0.5


async def test_a_running_plan_is_excluded_even_when_the_window_reaches_past_it(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    # Arrange — one plan still running, and a window whose `to` an operator typed as next
    # month. Only `now` can keep the running plan out of the denominator.
    await _plan(
        sessions,
        telegram_user_id=44,
        bought=_NOW - timedelta(days=1),
        ends=_NOW + timedelta(days=29),
        key="still-running",
    )
    future = TimeWindow(start=_NOW - timedelta(days=90), end=_NOW + timedelta(days=90))

    # Act
    async with sessions() as session:
        churn = await subscription_churn(session, now=_NOW, window=future)

    # Assert — nothing has ended, so there is no rate. `None`, never 0.0.
    assert churn.ended_plans == 0
    assert churn.renewed == 0
    assert churn.lapsed == 0
    assert churn.anonymised_ended == 0
    assert churn.rate is None


async def test_the_window_selects_endings_and_not_purchases(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    # Arrange — both plans were BOUGHT inside the window; only one ENDED inside it.
    await _plan(
        sessions,
        telegram_user_id=55,
        bought=_NOW - timedelta(days=20),
        ends=_NOW - timedelta(days=15),
        key="ended-inside",
    )
    await _plan(
        sessions,
        telegram_user_id=66,
        bought=_NOW - timedelta(days=19),
        ends=_NOW - timedelta(days=2),
        key="ended-outside",
    )
    window = TimeWindow(start=_NOW - timedelta(days=25), end=_NOW - timedelta(days=10))

    # Act
    async with sessions() as session:
        churn = await subscription_churn(session, now=_NOW, window=window)

    # Assert — a window on `created_at` would have counted both.
    assert churn.ended_plans == 1
    assert churn.lapsed == 1
    assert churn.renewed + churn.lapsed + churn.anonymised_ended == churn.ended_plans


async def test_an_empty_book_has_no_rate_at_all(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    # Act — nothing has ever been sold here.
    async with sessions() as session:
        churn = await subscription_churn(session, now=_NOW)

    # Assert — "0% churn" is the flattering lie the view refuses; `None` is the answer.
    assert churn.ended_plans == 0
    assert churn.rate is None


async def test_only_a_later_receipt_renews_so_the_last_plan_of_a_run_is_the_lapse(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    # Arrange — one loyal holder with three consecutive plans, all of them already ended.
    # This is the fixture that separates the three ways the correlated EXISTS can be wrong:
    # a self-match (`>=` instead of `>`) would renew all three, a reversed comparison would
    # renew only the last, and an uncorrelated probe would renew all three again.
    for index, (bought, ends) in enumerate(
        (
            (_NOW - timedelta(days=120), _NOW - timedelta(days=90)),
            (_NOW - timedelta(days=89), _NOW - timedelta(days=60)),
            (_NOW - timedelta(days=59), _NOW - timedelta(days=30)),
        )
    ):
        await _plan(sessions, telegram_user_id=77, bought=bought, ends=ends, key=f"run-{index}")

    # Act
    async with sessions() as session:
        churn = await subscription_churn(session, now=_NOW)

    # Assert — two renewals and one lapse from one customer who has been here four months.
    # The lapse is the CURRENT state of a holder who has not come back yet, and it will turn
    # into a renewal the day they do: the answer moves, which the read's docstring says out
    # loud rather than freezing an ending behind a grace period nobody was told about.
    assert churn.ended_plans == 3
    assert churn.renewed == 2
    assert churn.lapsed == 1
    assert churn.renewed + churn.lapsed + churn.anonymised_ended == churn.ended_plans


async def test_a_neighbours_purchase_never_renews_somebody_elses_plan(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    # Arrange — one holder whose plan ended and who has not come back, and a DIFFERENT
    # holder who bought afterwards. An EXISTS that lost its `telegram_user_id` equality —
    # or its `.correlate()` — would find that second receipt and report a renewal, which is
    # the one failure here that produces a flattering number rather than an exception.
    await _plan(
        sessions,
        telegram_user_id=88,
        bought=_NOW - timedelta(days=60),
        ends=_NOW - timedelta(days=30),
        key="did-not-return",
    )
    await _plan(
        sessions,
        telegram_user_id=99,
        bought=_NOW - timedelta(days=10),
        ends=_NOW + timedelta(days=20),
        key="a-stranger",
    )

    # Act
    async with sessions() as session:
        churn = await subscription_churn(session, now=_NOW)

    # Assert — one ending (the stranger's plan is still running), and it is a lapse.
    assert churn.ended_plans == 1
    assert churn.renewed == 0
    assert churn.lapsed == 1
    assert churn.rate == 1.0


async def test_two_erased_receipts_cannot_renew_each_other_because_null_is_not_a_holder(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    # Arrange — two `/forget`-ed receipts, the second bought later than the first. In SQL
    # `NULL = NULL` is unknown rather than true, so the probe could never match; the read
    # states that rather than relying on it and counts the anonymised arm explicitly, which
    # is what keeps the partition a partition if somebody later changes the join.
    await _plan(
        sessions,
        telegram_user_id=None,
        bought=_NOW - timedelta(days=120),
        ends=_NOW - timedelta(days=90),
        key="erased-first",
    )
    await _plan(
        sessions,
        telegram_user_id=None,
        bought=_NOW - timedelta(days=60),
        ends=_NOW - timedelta(days=30),
        key="erased-second",
    )

    # Act
    async with sessions() as session:
        churn = await subscription_churn(session, now=_NOW)

    # Assert — both endings are in their own arm and neither is a lapse or a renewal. The
    # rate is 0.0 and that is a MEASUREMENT of the identified population, which here is
    # empty: two plans ended, nothing is known about either, and nothing is claimed.
    assert churn.ended_plans == 2
    assert churn.anonymised_ended == 2
    assert churn.renewed == 0
    assert churn.lapsed == 0
    assert churn.renewed + churn.lapsed + churn.anonymised_ended == churn.ended_plans


async def test_a_plan_ending_exactly_at_now_has_ended_here_and_in_the_liability_read_alike(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    # Arrange — the one row the two reads could disagree about. `subscription_churn` cuts at
    # `plan_ends_at <= now` and `plan_liability` calls a plan live at `plan_ends_at > now`;
    # flip either to a strict or a loose comparison and this plan is either counted twice
    # across the two cards or by neither of them.
    await _plan(
        sessions,
        telegram_user_id=101,
        bought=_NOW - timedelta(days=30),
        ends=_NOW,
        key="ends-on-the-instant",
    )

    # Act
    async with sessions() as session:
        churn = await subscription_churn(session, now=_NOW)
        liability = await plan_liability(session, now=_NOW)

    # Assert — ended, once, on both sides. The boundary belongs to the past.
    assert churn.ended_plans == 1
    assert churn.lapsed == 1
    assert liability.ended_plans == 1
    assert liability.live_plans == 0


async def test_the_clock_is_required_so_a_forgotten_one_cannot_read_as_a_wave_of_churn(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    # Arrange — one plan bought today and running for another month.
    await _plan(
        sessions,
        telegram_user_id=111,
        bought=_NOW,
        ends=_NOW + timedelta(days=30),
        key="brand-new",
    )

    # Act / Assert — `now` is a required keyword and not defaulted to the window's end or to
    # `utc_now()`. This is the guard the signature exists to be: without a clock there is no
    # upper bound on `plan_ends_at`, every running plan is an ending, and the panel prints
    # 100% churn for a deployment whose customers are all still mid-plan. A `TypeError` is
    # the loud version of that, and loud is the whole point.
    async with sessions() as session:
        with pytest.raises(TypeError):
            await subscription_churn(session)  # type: ignore[call-arg]

        # And with the clock supplied, the same fixture is what it actually is: nothing has
        # ended, so there is no rate at all.
        churn = await subscription_churn(session, now=_NOW)
    assert churn.ended_plans == 0
    assert churn.rate is None
