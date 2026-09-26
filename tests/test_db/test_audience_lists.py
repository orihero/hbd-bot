"""The two identified lists: what they RANK by, and who they must not silently drop.

These are the only two reads in ``bayram.db.admin`` that carry a customer's identity, so the
tests here are about the two things that go wrong on an identified list and produce no
error either time.

* **Ranking by the wrong count.** "Top generators" is a list of people the operator may
  message, and ranking it by orders OPENED rather than songs DELIVERED puts the account
  with forty abandoned drafts at the top — a support case wearing a best-customer badge.
  The fixture below builds exactly that account and asserts it ranks BELOW the quieter one
  that actually received songs, which is an assertion that fails the moment the ranking key
  moves from ``COUNT(delivered)`` to ``COUNT(*)``.
* **Dropping a row because a join found nothing.** Two different absences reach these
  reads and neither is an error: an account with no ``user_profiles`` row (most Telegram
  accounts have no ``@handle``, and the row is written at onboarding rather than at first
  contact), and a receipt whose ``telegram_user_id`` ``/forget`` nulled. An inner join or a
  ``WHERE telegram_user_id IS NOT NULL`` would make the first invisible and the second a
  hole in the money record — a sale that vanished from the ledger because somebody
  exercised a right is money this deployment can no longer account for. Both are asserted
  PRESENT, with null identity fields rather than absent rows.
* **Assuming ``/forget`` reaches both lists.** It does not, and the asymmetry is pinned
  here rather than left to be discovered. That command anonymises the RECEIPT and deletes
  the profile row, so a subscriber row loses its id; it writes nothing to ``orders`` — there
  is no per-user order erasure, only the time-based sweep — and ``orders.telegram_user_id``
  is ``NOT NULL``, so an erased account keeps ranking on the generators list under its real
  id with a blank name. Same command, two different outcomes, one test each.

A third test pins the tie-break, which exists for a reason that is invisible in a single
call: the card polls, and ``ORDER BY delivered DESC`` alone lets tied rows come back in
whatever order the plan produced, so an operator watching the screen sees movement that is
not there.

Rows are written through the ORM with every clock stated, following
``test_admin_queries.py`` and ``test_plan_churn.py``.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Final
from uuid import uuid4

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from bayram.checkout import STUB_PROVIDER_NAME
from bayram.contracts import Language, OrderState
from bayram.db.admin.audience_lists import (
    MAX_RECENT_SUBSCRIBERS,
    recent_subscribers,
    top_generators,
)
from bayram.db.admin.sql import TimeWindow
from bayram.db.enums import PlanKind
from bayram.db.models.order import OrderRow
from bayram.db.models.plan_purchase import PlanPurchaseRow
from bayram.db.models.user import UserRow
from bayram.db.models.user_profile import UserProfileRow
from tests.conftest import FIXED_NOW

_NOW: Final[datetime] = FIXED_NOW
#: Inside "yesterday" and well outside it, so a windowed call and an unwindowed one disagree.
_INSIDE: Final[datetime] = _NOW - timedelta(hours=3)
_OUTSIDE: Final[datetime] = _NOW - timedelta(days=40)
_WINDOW: Final[TimeWindow] = TimeWindow(start=_NOW - timedelta(days=1), end=_NOW)
#: What the starter plan costs in tiyin. Irrelevant to recency and fixed so it cannot drift.
_PLAN_MINOR: Final[int] = 30_000_00
_SONGS: Final[int] = 12


async def _account(
    sessions: async_sessionmaker[AsyncSession],
    *,
    telegram_user_id: int,
    created_at: datetime = _OUTSIDE,
    with_profile: bool = True,
    **kw: Any,
) -> None:
    """A ``users`` row, and a ``user_profiles`` row unless the test is about its absence."""
    async with sessions.begin() as session:
        user = UserRow(
            id=uuid4(),
            telegram_user_id=telegram_user_id,
            ui_language=kw.pop("ui_language", Language.UZ_LATN),
            is_blocked=False,
            last_seen_at=created_at,
            created_at=created_at,
            updated_at=created_at,
        )
        session.add(user)
        await session.flush()
        if with_profile:
            session.add(
                UserProfileRow(
                    user_id=user.id,
                    telegram_user_id=telegram_user_id,
                    phone_e164=None,
                    # Stored WITHOUT the ``@``: the sigil is drawn, never persisted.
                    telegram_username=kw.pop("telegram_username", f"user{telegram_user_id}"),
                    first_name=kw.pop("first_name", "Gʻulomjon"),
                    last_name=None,
                    created_at=created_at,
                    updated_at=created_at,
                )
            )


async def _orders(
    sessions: async_sessionmaker[AsyncSession],
    *,
    telegram_user_id: int,
    created: int,
    delivered: int,
    created_at: datetime = _INSIDE,
    delivered_at: datetime = _INSIDE,
) -> None:
    """``created`` orders for one account, the first ``delivered`` of them shipped."""
    async with sessions.begin() as session:
        user = (
            await session.execute(
                sa.select(UserRow).where(UserRow.telegram_user_id == telegram_user_id)
            )
        ).scalar_one()
        for index in range(created):
            is_delivered = index < delivered
            session.add(
                OrderRow(
                    id=uuid4(),
                    user_id=user.id,
                    telegram_user_id=telegram_user_id,
                    state=OrderState.DELIVERED if is_delivered else OrderState.FAILED,
                    correlation_id=f"corr-{telegram_user_id}-{index}",
                    is_paid=True,
                    delivered_at=delivered_at if is_delivered else None,
                    created_at=created_at,
                    updated_at=created_at,
                )
            )


async def _plan(
    sessions: async_sessionmaker[AsyncSession],
    *,
    telegram_user_id: int | None,
    bought: datetime,
    key: str,
    **kw: Any,
) -> None:
    """One receipt. ``telegram_user_id=None`` is what ``/forget`` leaves behind."""
    async with sessions.begin() as session:
        session.add(
            PlanPurchaseRow(
                telegram_user_id=telegram_user_id,
                plan=PlanKind.STARTER,
                songs_included=_SONGS,
                songs_used=kw.pop("songs_used", 0),
                amount_minor=_PLAN_MINOR,
                currency=kw.pop("currency", "UZS"),
                provider=kw.pop("provider", STUB_PROVIDER_NAME),
                reference=f"ref-{key}",
                idempotency_key=key,
                created_at=bought,
                updated_at=bought,
                plan_ends_at=bought + timedelta(days=30),
            )
        )


# ---------------------------------------------------------------------------
# The ranking key
# ---------------------------------------------------------------------------
async def test_the_list_ranks_by_songs_delivered_and_never_by_orders_opened(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    # Arrange — the exact account the view's docstring names: eight orders, one delivery.
    # It out-ORDERS everybody and must still rank below the quiet account that received
    # three songs. Ranking by `COUNT(*)` would invert this list and would put a support case
    # at the top of a screen an operator messages people from.
    await _account(sessions, telegram_user_id=8_001)
    await _orders(sessions, telegram_user_id=8_001, created=8, delivered=1)
    await _account(sessions, telegram_user_id=8_002)
    await _orders(sessions, telegram_user_id=8_002, created=3, delivered=3)

    # Act
    async with sessions() as session:
        rows = await top_generators(session)

    # Assert — deliveries decide the order, and `orders_created` is published on the row so
    # the gap is visible rather than inferable from another screen. The pair is deliberately
    # NOT a conversion rate: see the read's docstring on why the two counts do not divide.
    assert [row.telegram_user_id for row in rows] == [8_002, 8_001]
    assert [row.delivered_songs for row in rows] == [3, 1]
    assert [row.orders_created for row in rows] == [3, 8]
    assert rows[0].last_delivered_at == _INSIDE


async def test_two_accounts_tied_on_deliveries_come_back_in_the_same_order_on_every_call(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    # Arrange — three accounts, two deliveries each, inserted in an order that is neither
    # ascending nor descending so an accidental "whatever the plan produced" ordering has
    # something to differ from. The card polls on a timer; without the tie-break an operator
    # watching it sees rows swap places between ticks and reads that as movement.
    for telegram_user_id in (9_030, 9_010, 9_020):
        await _account(sessions, telegram_user_id=telegram_user_id)
        await _orders(sessions, telegram_user_id=telegram_user_id, created=2, delivered=2)

    # Act — twice, on two sessions, exactly as two polls of the card would.
    async with sessions() as session:
        first = await top_generators(session)
    async with sessions() as session:
        second = await top_generators(session)

    # Assert — identical, and ordered by the account id, which is the only total order this
    # shape has once the ranking key ties.
    assert [row.telegram_user_id for row in first] == [9_010, 9_020, 9_030]
    assert first == second


async def test_the_window_names_the_songs_that_shipped_in_it_and_the_orders_opened_in_it(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    # Arrange — one account, two orders. One was opened long before the window and shipped
    # inside it; the other was opened inside the window and has not shipped. A caption that
    # names a week is describing songs that shipped in that week, so the first is the
    # delivery this list ranks on — and `orders_created` counts the second, not the first.
    await _account(sessions, telegram_user_id=7_001)
    await _orders(
        sessions,
        telegram_user_id=7_001,
        created=1,
        delivered=1,
        created_at=_OUTSIDE,
        delivered_at=_INSIDE,
    )
    await _orders(sessions, telegram_user_id=7_001, created=1, delivered=0, created_at=_INSIDE)

    # Act
    async with sessions() as session:
        windowed = await top_generators(session, window=_WINDOW)
        lifetime = await top_generators(session)

    # Assert — the windowed pair is (1 shipped, 1 opened) and the two are NOT the same
    # order; unwindowed — the default — `orders_created` is the lifetime figure, because the
    # absent window narrows nothing. Nothing here may be rendered as a conversion rate.
    assert len(windowed) == 1
    assert windowed[0].delivered_songs == 1
    assert windowed[0].orders_created == 1
    assert lifetime[0].orders_created == 2


# ---------------------------------------------------------------------------
# Absent identity is a state on the row, never a missing row
# ---------------------------------------------------------------------------
async def test_a_customer_with_no_profile_row_is_listed_with_a_blank_name_rather_than_dropped(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    # Arrange — an account that ordered before it ever onboarded, so `users` has a row and
    # `user_profiles` has none. That is the ordinary state of a Telegram account with no
    # `@handle`, not a failed write, and an inner join here would silently shorten the list
    # by exactly the customers we know least about.
    await _account(sessions, telegram_user_id=6_001, with_profile=False)
    await _orders(sessions, telegram_user_id=6_001, created=1, delivered=1)

    # Act
    async with sessions() as session:
        rows = await top_generators(session)

    # Assert — one row, identified by the id that never goes missing, with the two profile
    # columns null. `ui_language` and `first_seen_at` come from `users` and are present,
    # which is why THAT join is inner: an outer one could only fill them by inventing a
    # language and a date of first contact.
    assert len(rows) == 1
    assert rows[0].telegram_user_id == 6_001
    assert rows[0].telegram_username is None
    assert rows[0].first_name is None
    assert rows[0].ui_language is Language.UZ_LATN
    assert rows[0].first_seen_at == _OUTSIDE


async def test_an_erased_customer_keeps_ranking_because_forget_does_not_reach_their_orders(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    # Arrange — the state an account is in AFTER `/forget`, built from what that command
    # actually writes: the `user_profiles` row is DELETED, the `users` row SURVIVES (an
    # operator's block must outlast a data-subject request), and `orders` is untouched
    # because there is no per-user order erasure — only the time-based sweep, with
    # `purge_user` planned and unwritten (ADMIN_PANEL_PLAN §9.3). `orders.telegram_user_id`
    # is NOT NULL, so the ranking key is still there.
    await _account(sessions, telegram_user_id=6_101, with_profile=False)
    await _orders(sessions, telegram_user_id=6_101, created=2, delivered=2)

    # Act
    async with sessions() as session:
        rows = await top_generators(session)

    # Assert — the row is PRESENT and carries the real id with no name beside it. This is
    # the surprising half of the erasure story and it is pinned here on purpose: the
    # subscriber list below renders an anonymous receipt, and this list cannot, because
    # `/forget` reaches the receipt and not the order. The id is the same one
    # `GET /api/users` already publishes from the surviving `users` row, so nothing is
    # disclosed here that the records screen does not disclose — but a reader who assumed
    # erasure removes an account from this card would be wrong, and this test says so. It
    # will start failing the day `purge_user` ships, which is the correct failure.
    assert len(rows) == 1
    assert rows[0].telegram_user_id == 6_101
    assert rows[0].telegram_username is None
    assert rows[0].first_name is None
    assert rows[0].delivered_songs == 2


async def test_an_erased_customers_receipt_stays_on_the_subscribers_list_with_its_identity_gone(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    # Arrange — three sales, the most recent one from a customer who has since used
    # `/forget`: the receipt survives with `telegram_user_id` nulled and the profile row
    # deleted outright. Filtering it out would be worse than a blank name — the receipt IS
    # the ledger, and a sale that disappears from it because somebody exercised a right is
    # money this deployment can no longer account for.
    await _account(sessions, telegram_user_id=5_001)
    await _plan(sessions, telegram_user_id=5_001, bought=_NOW - timedelta(days=3), key="known")
    await _plan(sessions, telegram_user_id=None, bought=_NOW - timedelta(days=1), key="erased")
    await _plan(sessions, telegram_user_id=5_001, bought=_NOW - timedelta(days=9), key="older")

    # Act
    async with sessions() as session:
        rows = await recent_subscribers(session)

    # Assert — newest first, the erased row among them, its three identity fields null and
    # every money column intact. A `None` id here is a lawful erasure, never a missing write.
    assert len(rows) == 3
    erased = rows[0]
    assert erased.telegram_user_id is None
    assert erased.telegram_username is None
    assert erased.first_name is None
    assert erased.amount_minor == _PLAN_MINOR
    assert erased.currency == "UZS"
    assert erased.songs_included == _SONGS
    # The identified rows are unaffected: the outer join matched no profile for the NULL id
    # because SQL equality never matches NULL to NULL, and it needed no special case to.
    assert rows[1].telegram_user_id == 5_001
    assert rows[1].telegram_username == "user5001"
    assert [row.telegram_user_id for row in rows] == [None, 5_001, 5_001]


async def test_the_rail_that_settled_nothing_is_flagged_on_the_row_beside_the_amount(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    # Arrange — one demo sale and one real one, identical on every column but `provider`.
    # `StubCheckoutProvider` stamps `is_paid=True` having contacted nobody, so without the
    # flag a demo run is revenue on a screen somebody makes decisions from.
    await _plan(
        sessions,
        telegram_user_id=4_001,
        bought=_NOW - timedelta(days=1),
        key="demo",
        provider=STUB_PROVIDER_NAME,
    )
    await _plan(
        sessions,
        telegram_user_id=4_002,
        bought=_NOW - timedelta(days=2),
        key="real",
        provider="payme",
    )

    # Act
    async with sessions() as session:
        rows = await recent_subscribers(session)

    # Assert — the flag is derived once, here, so no later layer has to know the constant to
    # stay honest, and the raw provider rides along because the rail's own name is half of
    # what an operator needs to find a charge in somebody else's dashboard.
    assert [(row.provider, row.is_stub_rail) for row in rows] == [
        (STUB_PROVIDER_NAME, True),
        ("payme", False),
    ]


async def test_a_caller_asking_for_a_hundred_thousand_receipts_is_clamped_to_the_card_ceiling(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    # Arrange — one more receipt than the ceiling. On an identified surface the clamp is not
    # tidiness: it is what stops `?limit=100000` from turning a dashboard card into a bulk
    # export of who bought what. The boundary validates too; this is the backstop behind it.
    for index in range(MAX_RECENT_SUBSCRIBERS + 1):
        await _plan(
            sessions,
            telegram_user_id=3_000 + index,
            bought=_NOW - timedelta(minutes=index),
            key=f"bulk-{index}",
        )

    # Act
    async with sessions() as session:
        greedy = await recent_subscribers(session, limit=100_000)
        # Zero is clamped UP rather than honoured: a card that asked for nothing asked
        # wrongly, and an empty list would read as "nobody has ever subscribed".
        none_at_all = await recent_subscribers(session, limit=0)

    # Assert
    assert len(greedy) == MAX_RECENT_SUBSCRIBERS
    assert len(none_at_all) == 1
