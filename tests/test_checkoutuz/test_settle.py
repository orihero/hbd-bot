"""``settle_checkoutuz_order`` — the only code that grants for checkout.uz.

Real ``SqlPaymeLedger.open_intent(provider="checkoutuz")`` on SQLite, a scripted vendor. Money
moves only when checkout.uz itself says ``paid`` for the exact order and amount; every other
answer leaves the ledger untouched (``DECISIONS.md D28``).
"""

from __future__ import annotations

import logging
from typing import Any

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from bayram.checkout import Product
from bayram.checkoutuz.settle import SettleStatus, settle_checkoutuz_order, settle_note
from bayram.db.enums import CheckoutUzPaymentState, PaymentIntentState
from bayram.db.models import (
    CheckoutUzPaymentRow,
    CreditLedgerRow,
    PaymentIntentRow,
    PlanPurchaseRow,
    TopupPurchaseRow,
)
from bayram.db.payme import SqlPaymeLedger
from bayram.errors import CheckoutError
from tests.test_checkoutuz.conftest import (
    ORDER,
    PLAN_MINOR,
    USER,
    Clock,
    FakeCheckoutUz,
    open_intent,
    record_payment,
)


class Notifier:
    def __init__(self, *, raises: bool = False) -> None:
        self.calls: list[str] = []
        self.raises = raises

    async def __call__(self, public_ref: str) -> None:
        self.calls.append(public_ref)
        if self.raises:
            raise ConnectionError("redis down")


async def _count(sessions: async_sessionmaker[AsyncSession], table: type[Any]) -> int:
    async with sessions() as session:
        return int(await session.scalar(sa.select(sa.func.count()).select_from(table)) or 0)


async def _payment(sessions: async_sessionmaker[AsyncSession], order_id: int = ORDER) -> Any:
    async with sessions() as session:
        return (
            await session.execute(
                sa.select(CheckoutUzPaymentRow).where(CheckoutUzPaymentRow.order_id == order_id)
            )
        ).scalar_one()


async def _intent(sessions: async_sessionmaker[AsyncSession], public_ref: str) -> Any:
    async with sessions() as session:
        return (
            await session.execute(
                sa.select(PaymentIntentRow).where(PaymentIntentRow.public_ref == public_ref)
            )
        ).scalar_one()


async def _settle(
    sessions: async_sessionmaker[AsyncSession],
    vendor: FakeCheckoutUz,
    clock: Clock,
    *,
    order_id: int = ORDER,
    notifier: Notifier | None = None,
) -> Any:
    return await settle_checkoutuz_order(
        sessions, vendor, order_id=order_id, notifier=notifier, now=clock.now
    )


async def test_a_paid_order_settles_once_grants_once_and_notifies(
    sessions: async_sessionmaker[AsyncSession],
    ledger: SqlPaymeLedger,
    vendor: FakeCheckoutUz,
    clock: Clock,
) -> None:
    intent = await open_intent(ledger)
    await record_payment(sessions, intent)
    vendor.pay(ORDER, 7_000)
    notifier = Notifier()

    outcome = await _settle(sessions, vendor, clock, notifier=notifier)

    assert outcome.status is SettleStatus.SETTLED
    assert outcome.public_ref == intent.public_ref
    assert notifier.calls == [intent.public_ref]
    row = await _intent(sessions, intent.public_ref)
    assert row.state is PaymentIntentState.PAID
    assert row.settle_note == settle_note(ORDER) == f"checkoutuz:{ORDER}"
    payment = await _payment(sessions)
    assert payment.state is CheckoutUzPaymentState.PAID
    assert payment.paid_at == clock.now
    async with sessions() as session:
        receipt = (await session.execute(sa.select(TopupPurchaseRow))).scalar_one()
    assert receipt.provider == "checkoutuz"
    assert receipt.idempotency_key == intent.idempotency_key
    assert await _count(sessions, CreditLedgerRow) == 1


async def test_a_replay_grants_nothing_twice(
    sessions: async_sessionmaker[AsyncSession],
    ledger: SqlPaymeLedger,
    vendor: FakeCheckoutUz,
    clock: Clock,
) -> None:
    intent = await open_intent(ledger)
    await record_payment(sessions, intent)
    vendor.pay(ORDER, 7_000)
    notifier = Notifier()

    first = await _settle(sessions, vendor, clock, notifier=notifier)
    second = await _settle(sessions, vendor, clock, notifier=notifier)

    assert first.status is SettleStatus.SETTLED
    assert second.status is SettleStatus.REPLAY
    assert await _count(sessions, TopupPurchaseRow) == 1
    assert await _count(sessions, CreditLedgerRow) == 1
    assert notifier.calls == [intent.public_ref]
    # The replay does not even ask checkout.uz: the row has already left ``pending``.
    assert vendor.asked == [ORDER]


async def test_a_forged_webhook_for_a_pending_payment_grants_nothing(
    sessions: async_sessionmaker[AsyncSession],
    ledger: SqlPaymeLedger,
    vendor: FakeCheckoutUz,
    clock: Clock,
) -> None:
    intent = await open_intent(ledger)
    await record_payment(sessions, intent)
    # checkout.uz says pending — whatever the webhook claimed.

    outcome = await _settle(sessions, vendor, clock)

    assert outcome.status is SettleStatus.NOT_PAID
    payment = await _payment(sessions)
    assert payment.state is CheckoutUzPaymentState.PENDING
    assert payment.last_polled_at == clock.now
    assert (await _intent(sessions, intent.public_ref)).state is PaymentIntentState.PENDING
    assert await _count(sessions, CreditLedgerRow) == 0


@pytest.mark.parametrize("paid_som", [70, 700_000, 6_999])
async def test_a_som_tiyin_or_amount_mismatch_is_not_granted(
    sessions: async_sessionmaker[AsyncSession],
    ledger: SqlPaymeLedger,
    vendor: FakeCheckoutUz,
    clock: Clock,
    paid_som: int,
    caplog: pytest.LogCaptureFixture,
) -> None:
    intent = await open_intent(ledger)
    await record_payment(sessions, intent)
    vendor.pay(ORDER, paid_som)

    outcome = await _settle(sessions, vendor, clock)

    assert outcome.status is SettleStatus.MISMATCH
    assert (await _payment(sessions)).state is CheckoutUzPaymentState.ORPHAN_PAID
    assert (await _intent(sessions, intent.public_ref)).state is PaymentIntentState.PENDING
    assert await _count(sessions, CreditLedgerRow) == 0
    assert any(getattr(r, "event", None) == "checkoutuz.amount_mismatch" for r in caplog.records)


async def test_a_recorded_amount_that_disagrees_with_the_intent_is_not_granted(
    sessions: async_sessionmaker[AsyncSession],
    ledger: SqlPaymeLedger,
    vendor: FakeCheckoutUz,
    clock: Clock,
) -> None:
    intent = await open_intent(ledger)
    await record_payment(sessions, intent, amount_som=70)
    vendor.pay(ORDER, 70)

    outcome = await _settle(sessions, vendor, clock)

    assert outcome.status is SettleStatus.MISMATCH
    assert await _count(sessions, CreditLedgerRow) == 0


async def test_an_unknown_order_asks_nothing_and_writes_nothing(
    sessions: async_sessionmaker[AsyncSession], vendor: FakeCheckoutUz, clock: Clock
) -> None:
    outcome = await _settle(sessions, vendor, clock, order_id=999)

    assert outcome.status is SettleStatus.UNKNOWN
    assert vendor.asked == []


async def test_an_order_attached_to_another_rails_intent_is_refused(
    sessions: async_sessionmaker[AsyncSession],
    ledger: SqlPaymeLedger,
    vendor: FakeCheckoutUz,
    clock: Clock,
) -> None:
    intent = await open_intent(ledger, provider="payme")
    await record_payment(sessions, intent)
    vendor.pay(ORDER, 7_000)

    outcome = await _settle(sessions, vendor, clock)

    assert outcome.status is SettleStatus.UNKNOWN
    assert vendor.asked == []
    assert await _count(sessions, CreditLedgerRow) == 0


async def test_an_expired_intent_is_still_settled(
    sessions: async_sessionmaker[AsyncSession],
    ledger: SqlPaymeLedger,
    vendor: FakeCheckoutUz,
    clock: Clock,
) -> None:
    intent = await open_intent(ledger)
    await record_payment(sessions, intent)
    async with sessions.begin() as session:
        await session.execute(
            sa.update(PaymentIntentRow)
            .where(PaymentIntentRow.public_ref == intent.public_ref)
            .values(state=PaymentIntentState.EXPIRED)
        )
    vendor.pay(ORDER, 7_000)

    outcome = await _settle(sessions, vendor, clock)

    assert outcome.status is SettleStatus.SETTLED
    assert (await _intent(sessions, intent.public_ref)).state is PaymentIntentState.PAID
    assert await _count(sessions, CreditLedgerRow) == 1


async def test_a_link_paid_after_the_final_check_closed_it_is_still_settled(
    sessions: async_sessionmaker[AsyncSession],
    ledger: SqlPaymeLedger,
    vendor: FakeCheckoutUz,
    clock: Clock,
    caplog: pytest.LogCaptureFixture,
) -> None:
    # The final check closed the link as ``expired``; the customer then paid on the page they
    # left open. The one webhook for it is never retried, so dropping it would lose the money.
    intent = await open_intent(ledger)
    await record_payment(sessions, intent)
    async with sessions.begin() as session:
        await session.execute(
            sa.update(CheckoutUzPaymentRow).values(state=CheckoutUzPaymentState.EXPIRED)
        )
    vendor.pay(ORDER, 7_000)

    outcome = await _settle(sessions, vendor, clock)

    assert outcome.status is SettleStatus.SETTLED
    assert (await _payment(sessions)).state is CheckoutUzPaymentState.PAID
    assert (await _intent(sessions, intent.public_ref)).state is PaymentIntentState.PAID
    assert await _count(sessions, CreditLedgerRow) == 1
    assert any(
        getattr(r, "event", None) == "checkoutuz.paid_after_expiry" and r.levelno == logging.ERROR
        for r in caplog.records
    )


async def test_an_expired_link_checkout_uz_still_calls_pending_stays_expired(
    sessions: async_sessionmaker[AsyncSession],
    ledger: SqlPaymeLedger,
    vendor: FakeCheckoutUz,
    clock: Clock,
) -> None:
    intent = await open_intent(ledger)
    await record_payment(sessions, intent)
    async with sessions.begin() as session:
        await session.execute(
            sa.update(CheckoutUzPaymentRow).values(state=CheckoutUzPaymentState.EXPIRED)
        )

    outcome = await _settle(sessions, vendor, clock)

    assert outcome.status is SettleStatus.NOT_PAID
    assert (await _payment(sessions)).state is CheckoutUzPaymentState.EXPIRED
    assert await _count(sessions, CreditLedgerRow) == 0


async def test_a_second_paid_order_for_one_intent_is_orphaned_not_granted(
    sessions: async_sessionmaker[AsyncSession],
    ledger: SqlPaymeLedger,
    vendor: FakeCheckoutUz,
    clock: Clock,
    caplog: pytest.LogCaptureFixture,
) -> None:
    intent = await open_intent(ledger)
    await record_payment(sessions, intent, order_id=ORDER)
    await record_payment(sessions, intent, order_id=ORDER + 1)
    vendor.pay(ORDER, 7_000)
    vendor.pay(ORDER + 1, 7_000)
    notifier = Notifier()

    first = await _settle(sessions, vendor, clock, order_id=ORDER, notifier=notifier)
    second = await _settle(sessions, vendor, clock, order_id=ORDER + 1, notifier=notifier)

    assert first.status is SettleStatus.SETTLED
    assert second.status is SettleStatus.ORPHAN
    assert (await _payment(sessions, ORDER + 1)).state is CheckoutUzPaymentState.ORPHAN_PAID
    assert await _count(sessions, TopupPurchaseRow) == 1
    assert await _count(sessions, CreditLedgerRow) == 1
    assert notifier.calls == [intent.public_ref]
    assert any(getattr(r, "event", None) == "checkoutuz.double_payment" for r in caplog.records)


async def test_a_starter_plan_writes_a_plan_purchase(
    sessions: async_sessionmaker[AsyncSession],
    ledger: SqlPaymeLedger,
    vendor: FakeCheckoutUz,
    clock: Clock,
) -> None:
    intent = await open_intent(
        ledger, key=f"topup:{USER}:plan:1", product=Product.STARTER, amount_minor=PLAN_MINOR
    )
    await record_payment(sessions, intent)
    vendor.pay(ORDER, 49_000)

    outcome = await _settle(sessions, vendor, clock)

    assert outcome.status is SettleStatus.SETTLED
    async with sessions() as session:
        plan = (await session.execute(sa.select(PlanPurchaseRow))).scalar_one()
    assert plan.provider == "checkoutuz"
    assert plan.songs_included == 12
    assert await _count(sessions, TopupPurchaseRow) == 0


async def test_a_forgotten_buyer_is_settled_without_a_sale(
    sessions: async_sessionmaker[AsyncSession],
    ledger: SqlPaymeLedger,
    vendor: FakeCheckoutUz,
    clock: Clock,
) -> None:
    intent = await open_intent(ledger)
    await record_payment(sessions, intent)
    async with sessions.begin() as session:
        await session.execute(
            sa.update(PaymentIntentRow)
            .where(PaymentIntentRow.public_ref == intent.public_ref)
            .values(telegram_user_id=None)
        )
    vendor.pay(ORDER, 7_000)

    outcome = await _settle(sessions, vendor, clock)

    assert outcome.status is SettleStatus.SETTLED
    assert (await _intent(sessions, intent.public_ref)).state is PaymentIntentState.PAID
    assert await _count(sessions, TopupPurchaseRow) == 0
    assert await _count(sessions, CreditLedgerRow) == 0


async def test_a_raising_notifier_leaves_the_payment_settled(
    sessions: async_sessionmaker[AsyncSession],
    ledger: SqlPaymeLedger,
    vendor: FakeCheckoutUz,
    clock: Clock,
) -> None:
    intent = await open_intent(ledger)
    await record_payment(sessions, intent)
    vendor.pay(ORDER, 7_000)
    notifier = Notifier(raises=True)

    outcome = await _settle(sessions, vendor, clock, notifier=notifier)

    assert outcome.status is SettleStatus.SETTLED
    assert notifier.calls == [intent.public_ref]
    assert (await _payment(sessions)).state is CheckoutUzPaymentState.PAID
    assert await _count(sessions, CreditLedgerRow) == 1


async def test_a_transport_error_changes_nothing(
    sessions: async_sessionmaker[AsyncSession],
    ledger: SqlPaymeLedger,
    vendor: FakeCheckoutUz,
    clock: Clock,
) -> None:
    intent = await open_intent(ledger)
    await record_payment(sessions, intent)
    vendor.status_error = CheckoutError("unreachable", is_retryable=True)

    outcome = await _settle(sessions, vendor, clock)

    assert outcome.status is SettleStatus.RETRY_LATER
    assert outcome.retryable is True
    payment = await _payment(sessions)
    assert payment.state is CheckoutUzPaymentState.PENDING
    # Stamped, so a row checkout.uz keeps failing on rotates to the back of both batches.
    assert payment.last_polled_at == clock.now
    assert payment.paid_at is None
    assert (await _intent(sessions, intent.public_ref)).state is PaymentIntentState.PENDING


async def test_a_non_retryable_status_error_is_stamped_and_logged_at_error(
    sessions: async_sessionmaker[AsyncSession],
    ledger: SqlPaymeLedger,
    vendor: FakeCheckoutUz,
    clock: Clock,
    caplog: pytest.LogCaptureFixture,
) -> None:
    intent = await open_intent(ledger)
    await record_payment(sessions, intent)
    vendor.status_error = CheckoutError("checkout.uz refused the request", is_retryable=False)

    with caplog.at_level(logging.WARNING, logger="bayram.checkoutuz.settle"):
        outcome = await _settle(sessions, vendor, clock)

    assert outcome.status is SettleStatus.RETRY_LATER
    assert outcome.retryable is False
    payment = await _payment(sessions)
    assert payment.state is CheckoutUzPaymentState.PENDING
    assert payment.last_polled_at == clock.now
    (record,) = [
        r for r in caplog.records if r.__dict__.get("event") == "checkoutuz.status_unavailable"
    ]
    assert record.levelno == logging.ERROR
    assert await _count(sessions, CreditLedgerRow) == 0
