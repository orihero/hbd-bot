"""``checkoutuz_sql`` — the statements the checkout.uz rail's poller and settlement are made of.

The policy that sequences these lives in ``bayram.checkoutuz`` and is tested there with a fake
client. This file pins the half a fake cannot: what each statement selects, in what order, and
that every write is a conditional ``UPDATE`` exactly one caller can win (DECISIONS.md D28).

In-memory SQLite with ``StaticPool``, through this package's ``sessions`` fixture, and the
intent rows come from ``rail_helpers`` with ``provider="checkoutuz"`` — the same builders every
admin read test uses — so a column the settlement relies on cannot differ between the two
suites. Every order id is above 2**31: checkout.uz's ids are theirs to grow, and a column that
quietly became an ``Integer`` would truncate them on Postgres while SQLite stored them anyway.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Final
from uuid import UUID

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from bayram.checkoutuz.ports import CHECKOUTUZ_PROVIDER_NAME
from bayram.contracts import is_ok
from bayram.db.checkoutuz_sql import (
    CHECKOUTUZ_INTENT_PROVIDER,
    claim_intent_for_checkoutuz,
    final_check_payments,
    insert_payment,
    live_payment_for_intent,
    mark_payment,
    payment_by_order,
    payment_with_intent,
    pollable_payments,
    stamp_polled,
)
from bayram.db.enums import CheckoutUzPaymentState, PaymentIntentState
from bayram.db.models import CheckoutUzPaymentRow
from bayram.db.models.payment_intent import PaymentIntentRow
from bayram.db.purge import purge_expired
from tests.test_db.conftest import MovableClock
from tests.test_db.rail_helpers import add, make_intent

#: Above 2**31 on purpose — see the module docstring.
_ORDER: Final[int] = 3_000_000_001
_LINK_LIFETIME: Final[timedelta] = timedelta(hours=1)
_GRACE_S: Final[int] = 900
_MARGIN_S: Final[int] = 60


async def _intent(
    sessions: async_sessionmaker[AsyncSession],
    clock: MovableClock,
    *,
    provider: str = CHECKOUTUZ_INTENT_PROVIDER,
    state: PaymentIntentState = PaymentIntentState.PENDING,
) -> UUID:
    intent = make_intent(now=clock.now, state=state, provider=provider, merchant_id="checkoutuz")
    await add(sessions, intent)
    return intent.id


async def _record(
    sessions: async_sessionmaker[AsyncSession],
    *,
    order_id: int,
    intent_id: UUID,
    now: datetime,
    valid_until: datetime | None = None,
) -> bool:
    async with sessions.begin() as session:
        return await insert_payment(
            session,
            order_id=order_id,
            intent_id=intent_id,
            payment_uuid=f"uuid-{order_id}",
            pay_url=f"https://checkout.uz/pay/{order_id}",
            amount_som=7_000,
            link_valid_until=valid_until if valid_until is not None else now + _LINK_LIFETIME,
            now=now,
        )


async def _payment(
    sessions: async_sessionmaker[AsyncSession], order_id: int
) -> CheckoutUzPaymentRow:
    async with sessions() as session:
        found = await payment_by_order(session, order_id)
    assert found is not None
    return found


async def _intent_row(
    sessions: async_sessionmaker[AsyncSession], intent_id: UUID
) -> PaymentIntentRow:
    async with sessions() as session:
        return (
            await session.execute(
                sa.select(PaymentIntentRow).where(PaymentIntentRow.id == intent_id)
            )
        ).scalar_one()


# ---------------------------------------------------------------------------
# Spelling
# ---------------------------------------------------------------------------
def test_the_persisted_provider_name_is_the_rails_own() -> None:
    """Persistence spells ``'checkoutuz'`` itself rather than importing the rail; this pins the
    two together, so a rename on one side is a red test and not an intent no claim can match."""
    assert CHECKOUTUZ_INTENT_PROVIDER == CHECKOUTUZ_PROVIDER_NAME


# ---------------------------------------------------------------------------
# insert_payment / payment_by_order / payment_with_intent
# ---------------------------------------------------------------------------
async def test_an_inserted_payment_reads_back_pending_with_every_column(
    sessions: async_sessionmaker[AsyncSession], clock: MovableClock
) -> None:
    # Arrange
    intent_id = await _intent(sessions, clock)

    # Act
    wrote = await _record(sessions, order_id=_ORDER, intent_id=intent_id, now=clock.now)

    # Assert
    assert wrote is True
    row = await _payment(sessions, _ORDER)
    assert row.order_id == _ORDER
    assert row.intent_id == intent_id
    assert row.state is CheckoutUzPaymentState.PENDING
    assert row.amount_som == 7_000
    assert row.pay_url == f"https://checkout.uz/pay/{_ORDER}"
    assert row.link_valid_until == clock.now + _LINK_LIFETIME
    assert row.last_polled_at is None
    assert row.paid_at is None


async def test_a_second_insert_of_the_same_order_is_ignored_and_rewinds_nothing(
    sessions: async_sessionmaker[AsyncSession], clock: MovableClock
) -> None:
    """A row that has already moved on must not be put back to ``pending`` by a retried record."""
    # Arrange
    intent_id = await _intent(sessions, clock)
    await _record(sessions, order_id=_ORDER, intent_id=intent_id, now=clock.now)
    async with sessions.begin() as session:
        assert await mark_payment(
            session,
            _ORDER,
            frm=CheckoutUzPaymentState.PENDING,
            to=CheckoutUzPaymentState.PAID,
            now=clock.now,
            paid_at=clock.now,
        )

    # Act
    wrote = await _record(
        sessions, order_id=_ORDER, intent_id=intent_id, now=clock.advance(seconds=5)
    )

    # Assert
    assert wrote is False
    assert (await _payment(sessions, _ORDER)).state is CheckoutUzPaymentState.PAID


async def test_an_unknown_order_is_none_not_an_exception(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    async with sessions() as session:
        assert await payment_by_order(session, 42) is None
        assert await payment_with_intent(session, 42) is None


async def test_payment_with_intent_returns_the_pair_in_one_read(
    sessions: async_sessionmaker[AsyncSession], clock: MovableClock
) -> None:
    # Arrange
    intent_id = await _intent(sessions, clock)
    await _record(sessions, order_id=_ORDER, intent_id=intent_id, now=clock.now)

    # Act
    async with sessions() as session:
        pair = await payment_with_intent(session, _ORDER)

    # Assert
    assert pair is not None
    payment, intent = pair
    assert payment.order_id == _ORDER
    assert intent.id == intent_id
    assert intent.provider == CHECKOUTUZ_INTENT_PROVIDER


# ---------------------------------------------------------------------------
# live_payment_for_intent
# ---------------------------------------------------------------------------
async def test_pay_via_round_trips_in_order_and_empty_is_null(
    sessions: async_sessionmaker[AsyncSession], clock: MovableClock
) -> None:
    """The per-method pages come back in checkout.uz's order; none is SQL NULL, not ``'null'``."""
    # Arrange
    intent_id = await _intent(sessions, clock)
    pages = (
        ("click", "https://checkout.uz/pay/u/click"),
        ("payme", "https://checkout.uz/pay/u/payme"),
        ("card", "https://checkout.uz/pay/u/card"),
    )
    async with sessions.begin() as session:
        await insert_payment(
            session,
            order_id=_ORDER,
            intent_id=intent_id,
            payment_uuid="uuid",
            pay_url="https://checkout.uz/pay/u",
            amount_som=7_000,
            link_valid_until=clock.now + _LINK_LIFETIME,
            now=clock.now,
            pay_via=pages,
        )
    await _record(sessions, order_id=_ORDER + 1, intent_id=intent_id, now=clock.now)

    # Act
    with_pages = await _payment(sessions, _ORDER)
    without = await _payment(sessions, _ORDER + 1)
    async with sessions() as session:
        nulls = (
            (
                await session.execute(
                    sa.select(CheckoutUzPaymentRow.order_id).where(
                        CheckoutUzPaymentRow.pay_via.is_(None)
                    )
                )
            )
            .scalars()
            .all()
        )

    # Assert
    assert with_pages.pay_via == [list(page) for page in pages]
    assert without.pay_via is None
    assert list(nulls) == [_ORDER + 1]


async def test_a_re_press_finds_the_newest_live_link(
    sessions: async_sessionmaker[AsyncSession], clock: MovableClock
) -> None:
    # Arrange — two live links for one intent, minted a minute apart.
    intent_id = await _intent(sessions, clock)
    await _record(sessions, order_id=_ORDER, intent_id=intent_id, now=clock.now)
    await _record(sessions, order_id=_ORDER + 1, intent_id=intent_id, now=clock.advance(seconds=60))

    # Act
    async with sessions() as session:
        found = await live_payment_for_intent(session, intent_id, now=clock.now, margin_s=_MARGIN_S)

    # Assert
    assert found is not None
    assert found.order_id == _ORDER + 1


async def test_a_link_inside_the_margin_is_not_reused(
    sessions: async_sessionmaker[AsyncSession], clock: MovableClock
) -> None:
    """Thirty seconds left is live on paper and useless to a customer typing a card number."""
    # Arrange
    intent_id = await _intent(sessions, clock)
    await _record(
        sessions,
        order_id=_ORDER,
        intent_id=intent_id,
        now=clock.now,
        valid_until=clock.now + timedelta(seconds=30),
    )

    # Act
    async with sessions() as session:
        found = await live_payment_for_intent(session, intent_id, now=clock.now, margin_s=_MARGIN_S)

    # Assert
    assert found is None


async def test_a_paid_link_is_never_offered_again(
    sessions: async_sessionmaker[AsyncSession], clock: MovableClock
) -> None:
    # Arrange
    intent_id = await _intent(sessions, clock)
    await _record(sessions, order_id=_ORDER, intent_id=intent_id, now=clock.now)
    async with sessions.begin() as session:
        await mark_payment(
            session,
            _ORDER,
            frm=CheckoutUzPaymentState.PENDING,
            to=CheckoutUzPaymentState.PAID,
            now=clock.now,
            paid_at=clock.now,
        )

    # Act
    async with sessions() as session:
        found = await live_payment_for_intent(session, intent_id, now=clock.now, margin_s=_MARGIN_S)

    # Assert
    assert found is None


async def test_another_intents_link_is_not_this_intents(
    sessions: async_sessionmaker[AsyncSession], clock: MovableClock
) -> None:
    # Arrange
    mine = await _intent(sessions, clock)
    theirs = await _intent(sessions, clock)
    await _record(sessions, order_id=_ORDER, intent_id=theirs, now=clock.now)

    # Act
    async with sessions() as session:
        found = await live_payment_for_intent(session, mine, now=clock.now, margin_s=_MARGIN_S)

    # Assert
    assert found is None


# ---------------------------------------------------------------------------
# pollable_payments / final_check_payments
# ---------------------------------------------------------------------------
async def test_the_poll_batch_and_the_final_check_split_pending_on_the_grace_boundary(
    sessions: async_sessionmaker[AsyncSession], clock: MovableClock
) -> None:
    """Every pending link is in exactly one of the two batches; settled links are in neither."""
    # Arrange
    intent_id = await _intent(sessions, clock)
    now = clock.now
    grace = timedelta(seconds=_GRACE_S)
    live = _ORDER
    in_grace = _ORDER + 1
    on_boundary = _ORDER + 2
    long_gone = _ORDER + 3
    settled = _ORDER + 4
    await _record(sessions, order_id=live, intent_id=intent_id, now=now)
    await _record(
        sessions, order_id=in_grace, intent_id=intent_id, now=now, valid_until=now - grace / 2
    )
    await _record(
        sessions, order_id=on_boundary, intent_id=intent_id, now=now, valid_until=now - grace
    )
    await _record(
        sessions,
        order_id=long_gone,
        intent_id=intent_id,
        now=now,
        valid_until=now - timedelta(days=1),
    )
    await _record(sessions, order_id=settled, intent_id=intent_id, now=now)
    async with sessions.begin() as session:
        await mark_payment(
            session,
            settled,
            frm=CheckoutUzPaymentState.PENDING,
            to=CheckoutUzPaymentState.PAID,
            now=now,
            paid_at=now,
        )

    # Act
    async with sessions() as session:
        polled = {
            row.order_id
            for row in await pollable_payments(session, now=now, grace_s=_GRACE_S, limit=50)
        }
        final = {
            row.order_id
            for row in await final_check_payments(session, now=now, grace_s=_GRACE_S, limit=50)
        }

    # Assert
    assert polled == {live, in_grace}
    assert final == {on_boundary, long_gone}


async def test_a_never_polled_link_goes_first_and_a_stamped_one_goes_last(
    sessions: async_sessionmaker[AsyncSession], clock: MovableClock
) -> None:
    """``last_polled_at NULLS FIRST, created_at``: fresh links are never starved by old ones."""
    # Arrange — three links minted in order; the oldest two have been polled, newest first.
    intent_id = await _intent(sessions, clock)
    start = clock.now
    await _record(sessions, order_id=_ORDER, intent_id=intent_id, now=start)
    await _record(sessions, order_id=_ORDER + 1, intent_id=intent_id, now=clock.advance(seconds=1))
    await _record(sessions, order_id=_ORDER + 2, intent_id=intent_id, now=clock.advance(seconds=1))
    async with sessions.begin() as session:
        assert await stamp_polled(session, _ORDER + 1, clock.advance(seconds=10))
        assert await stamp_polled(session, _ORDER, clock.advance(seconds=10))

    # Act
    async with sessions() as session:
        batch = await pollable_payments(session, now=clock.now, grace_s=_GRACE_S, limit=50)
        first_two = await pollable_payments(session, now=clock.now, grace_s=_GRACE_S, limit=2)

    # Assert
    assert [row.order_id for row in batch] == [_ORDER + 2, _ORDER + 1, _ORDER]
    assert [row.order_id for row in first_two] == [_ORDER + 2, _ORDER + 1]


async def test_the_final_check_batch_rotates_past_rows_it_already_asked_about(
    sessions: async_sessionmaker[AsyncSession], clock: MovableClock
) -> None:
    """``last_polled_at NULLS FIRST, link_valid_until``: the oldest lapsed rows — which a
    failing status call stamps without closing — must not fill every final-check batch."""
    # Arrange — two lapsed links; the OLDER one has already been asked about (and failed).
    intent_id = await _intent(sessions, clock)
    start = clock.now
    await _record(sessions, order_id=_ORDER, intent_id=intent_id, now=start)
    await _record(sessions, order_id=_ORDER + 1, intent_id=intent_id, now=clock.advance(seconds=1))
    clock.advance(seconds=int(_LINK_LIFETIME.total_seconds()) + _GRACE_S + 60)
    async with sessions.begin() as session:
        assert await stamp_polled(session, _ORDER, clock.now)

    # Act
    async with sessions() as session:
        head = await final_check_payments(session, now=clock.now, grace_s=_GRACE_S, limit=1)
        both = await final_check_payments(session, now=clock.now, grace_s=_GRACE_S, limit=50)

    # Assert — the never-asked newer link goes first despite its later link_valid_until.
    assert [row.order_id for row in head] == [_ORDER + 1]
    assert [row.order_id for row in both] == [_ORDER + 1, _ORDER]


# ---------------------------------------------------------------------------
# mark_payment / stamp_polled
# ---------------------------------------------------------------------------
async def test_mark_payment_has_exactly_one_winner(
    sessions: async_sessionmaker[AsyncSession], clock: MovableClock
) -> None:
    """The replay answer: the second ``pending -> paid`` writes nothing and says so."""
    # Arrange
    intent_id = await _intent(sessions, clock)
    await _record(sessions, order_id=_ORDER, intent_id=intent_id, now=clock.now)
    paid_at = clock.advance(seconds=30)

    # Act
    async with sessions.begin() as session:
        first = await mark_payment(
            session,
            _ORDER,
            frm=CheckoutUzPaymentState.PENDING,
            to=CheckoutUzPaymentState.PAID,
            now=paid_at,
            paid_at=paid_at,
        )
    async with sessions.begin() as session:
        second = await mark_payment(
            session,
            _ORDER,
            frm=CheckoutUzPaymentState.PENDING,
            to=CheckoutUzPaymentState.EXPIRED,
            now=clock.advance(seconds=30),
        )

    # Assert
    assert (first, second) == (True, False)
    row = await _payment(sessions, _ORDER)
    assert row.state is CheckoutUzPaymentState.PAID
    assert row.paid_at == paid_at
    assert row.last_polled_at == paid_at


async def test_expiring_a_link_writes_no_paid_clock(
    sessions: async_sessionmaker[AsyncSession], clock: MovableClock
) -> None:
    # Arrange
    intent_id = await _intent(sessions, clock)
    await _record(sessions, order_id=_ORDER, intent_id=intent_id, now=clock.now)

    # Act
    async with sessions.begin() as session:
        moved = await mark_payment(
            session,
            _ORDER,
            frm=CheckoutUzPaymentState.PENDING,
            to=CheckoutUzPaymentState.EXPIRED,
            now=clock.advance(seconds=5),
        )

    # Assert
    assert moved is True
    row = await _payment(sessions, _ORDER)
    assert row.state is CheckoutUzPaymentState.EXPIRED
    assert row.paid_at is None


async def test_a_stamp_cannot_touch_a_link_that_has_moved_on(
    sessions: async_sessionmaker[AsyncSession], clock: MovableClock
) -> None:
    # Arrange
    intent_id = await _intent(sessions, clock)
    await _record(sessions, order_id=_ORDER, intent_id=intent_id, now=clock.now)
    async with sessions.begin() as session:
        await mark_payment(
            session,
            _ORDER,
            frm=CheckoutUzPaymentState.PENDING,
            to=CheckoutUzPaymentState.EXPIRED,
            now=clock.now,
        )

    # Act
    async with sessions.begin() as session:
        stamped = await stamp_polled(session, _ORDER, clock.advance(seconds=60))

    # Assert
    assert stamped is False
    assert (await _payment(sessions, _ORDER)).last_polled_at == clock.now - timedelta(seconds=60)


# ---------------------------------------------------------------------------
# claim_intent_for_checkoutuz
# ---------------------------------------------------------------------------
async def test_a_claim_settles_a_pending_intent_once(
    sessions: async_sessionmaker[AsyncSession], clock: MovableClock
) -> None:
    # Arrange
    intent_id = await _intent(sessions, clock)
    now = clock.advance(seconds=120)

    # Act
    async with sessions.begin() as session:
        first = await claim_intent_for_checkoutuz(
            session, intent_id=intent_id, now=now, note=f"checkoutuz:{_ORDER}"
        )
    async with sessions.begin() as session:
        second = await claim_intent_for_checkoutuz(
            session, intent_id=intent_id, now=clock.advance(seconds=1), note="checkoutuz:2"
        )

    # Assert — the second claim is the double payment: it writes nothing.
    assert (first, second) == (True, False)
    row = await _intent_row(sessions, intent_id)
    assert row.state is PaymentIntentState.PAID
    assert row.settled_at == now
    assert row.settle_note == f"checkoutuz:{_ORDER}"


async def test_a_late_payment_settles_an_expired_intent(
    sessions: async_sessionmaker[AsyncSession], clock: MovableClock
) -> None:
    """checkout.uz cannot refuse a late payment, so neither may we (DECISIONS.md D28)."""
    # Arrange
    intent_id = await _intent(sessions, clock, state=PaymentIntentState.EXPIRED)

    # Act
    async with sessions.begin() as session:
        claimed = await claim_intent_for_checkoutuz(
            session, intent_id=intent_id, now=clock.now, note=f"checkoutuz:{_ORDER}"
        )

    # Assert
    assert claimed is True
    assert (await _intent_row(sessions, intent_id)).state is PaymentIntentState.PAID


async def test_a_claim_never_touches_another_rails_intent(
    sessions: async_sessionmaker[AsyncSession], clock: MovableClock
) -> None:
    """An order attached to a Payme intent must not be able to settle it."""
    # Arrange
    intent_id = await _intent(sessions, clock, provider="payme")

    # Act
    async with sessions.begin() as session:
        claimed = await claim_intent_for_checkoutuz(
            session, intent_id=intent_id, now=clock.now, note=f"checkoutuz:{_ORDER}"
        )

    # Assert
    assert claimed is False
    assert (await _intent_row(sessions, intent_id)).state is PaymentIntentState.PENDING


async def test_a_cancelled_intent_is_not_claimable(
    sessions: async_sessionmaker[AsyncSession], clock: MovableClock
) -> None:
    # Arrange
    intent_id = await _intent(sessions, clock, state=PaymentIntentState.CANCELLED)

    # Act
    async with sessions.begin() as session:
        claimed = await claim_intent_for_checkoutuz(
            session, intent_id=intent_id, now=clock.now, note=f"checkoutuz:{_ORDER}"
        )

    # Assert
    assert claimed is False


# ---------------------------------------------------------------------------
# Retention: the intent purge never takes a refund-owed link with it
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    ("link_state", "purged"),
    [
        (CheckoutUzPaymentState.ORPHAN_PAID, False),
        (CheckoutUzPaymentState.PAID, False),
        (CheckoutUzPaymentState.EXPIRED, True),
    ],
)
async def test_the_intent_purge_keeps_any_intent_behind_checkoutuz_money(
    sessions: async_sessionmaker[AsyncSession],
    clock: MovableClock,
    link_state: CheckoutUzPaymentState,
    purged: bool,
) -> None:
    """An amount mismatch closes the LINK ``orphan_paid`` and leaves the intent to expire; the
    400-day sweep must not then delete that intent — and, through the FK, the only record of a
    refund owed. A purely lapsed link goes with its intent, deleted child-first."""
    # Arrange — an EXPIRED intent old enough that the cutoff alone would take it.
    old = clock.now - timedelta(days=401)
    intent = make_intent(
        now=old,
        state=PaymentIntentState.EXPIRED,
        provider=CHECKOUTUZ_INTENT_PROVIDER,
        merchant_id="checkoutuz",
        created_at=old,
    )
    await add(sessions, intent)
    await _record(sessions, order_id=_ORDER, intent_id=intent.id, now=old)
    async with sessions.begin() as session:
        assert await mark_payment(
            session, _ORDER, frm=CheckoutUzPaymentState.PENDING, to=link_state, now=old
        )

    # Act
    outcome = await purge_expired(sessions, now=clock.now)

    # Assert
    assert is_ok(outcome), outcome
    assert outcome.value.payment_intents_deleted == (1 if purged else 0)
    async with sessions() as session:
        links = await session.scalar(sa.select(sa.func.count()).select_from(CheckoutUzPaymentRow))
        intents = await session.scalar(sa.select(sa.func.count()).select_from(PaymentIntentRow))
    assert links == (0 if purged else 1)
    assert intents == (0 if purged else 1)


def test_the_intent_foreign_key_restricts_rather_than_cascades() -> None:
    """RESTRICT is the backstop for any delete path that does not go through the purge."""
    (foreign_key,) = CheckoutUzPaymentRow.__table__.c.intent_id.foreign_keys
    assert foreign_key.ondelete == "RESTRICT"
