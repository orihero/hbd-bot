"""Shared fixtures for the checkout.uz rail: an in-memory database, a clock and a fake vendor.

The fake client is a scripted :class:`~bayram.checkoutuz.client.CheckoutUzApi`: a test says what
``status_payment`` answers for which order, and reads back what was asked. Nothing in this
package makes a network call (``DECISIONS.md D28``); the real client is tested against an
``httpx.MockTransport`` in ``test_client.py`` and nowhere else.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from typing import Any, Final

import pytest
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import StaticPool

from bayram.checkout import PaymentIntent, Product
from bayram.checkoutuz.client import CheckoutUzPayment, CheckoutUzPaymentStatus
from bayram.checkoutuz.ports import CHECKOUTUZ_PROVIDER_NAME
from bayram.contracts import Result, err, is_ok, ok
from bayram.db.base import Base
from bayram.db.checkoutuz_sql import insert_payment
from bayram.db.engine import create_session_factory
from bayram.db.payme import SqlPaymeLedger
from bayram.db.payme_sql import intent_by_ref
from bayram.errors import CheckoutError

#: Outside the 32-bit range, as every Telegram id in the money tests is.
USER: Final[int] = 8_912_345_678_901
SINGLE_MINOR: Final[int] = 700_000  # 7 000 som
PLAN_MINOR: Final[int] = 4_900_000  # 49 000 som
#: Above 2**31, as checkout.uz's ids are theirs to grow.
ORDER: Final[int] = 3_000_000_001
FIXED_NOW: Final[datetime] = datetime(2026, 10, 3, 9, 0, tzinfo=UTC)


class Clock:
    def __init__(self, start: datetime = FIXED_NOW) -> None:
        self.now = start

    def __call__(self) -> datetime:
        return self.now

    def advance(self, *, seconds: int) -> datetime:
        self.now = self.now + timedelta(seconds=seconds)
        return self.now


class FakeCheckoutUz:
    """Scripted ``CheckoutUzApi``. ``statuses[order_id]`` is the answer; missing means pending."""

    def __init__(self) -> None:
        self.next_order_id = ORDER
        self.lifetime_s = 3600
        #: What ``_pay_via`` the next created payment carries.
        self.pay_via: tuple[tuple[str, str], ...] = ()
        self.echo_amount_delta = 0
        self.create_error: CheckoutError | None = None
        self.status_error: CheckoutError | None = None
        self.statuses: dict[int, tuple[str, int]] = {}
        self.created: list[dict[str, Any]] = []
        self.asked: list[int] = []

    async def create_payment(
        self, *, amount_som: int, description: str, webhook_url: str, return_url: str
    ) -> Result[CheckoutUzPayment]:
        self.created.append(
            {
                "amount_som": amount_som,
                "description": description,
                "webhook_url": webhook_url,
                "return_url": return_url,
            }
        )
        if self.create_error is not None:
            return err(self.create_error)
        order_id = self.next_order_id
        self.next_order_id += 1
        return ok(
            CheckoutUzPayment(
                order_id=order_id,
                uuid=f"uuid-{order_id}",
                url=f"https://checkout.uz/pay/uuid-{order_id}",
                amount_som=amount_som + self.echo_amount_delta,
                status="pending",
                lifetime_s=self.lifetime_s,
                raw={},
                pay_via=self.pay_via,
            )
        )

    async def status_payment(self, *, order_id: int) -> Result[CheckoutUzPaymentStatus]:
        self.asked.append(order_id)
        if self.status_error is not None:
            return err(self.status_error)
        status, amount = self.statuses.get(order_id, ("pending", 0))
        return ok(
            CheckoutUzPaymentStatus(
                order_id=order_id, amount_som=amount, status=status, paid_at=None, raw={}
            )
        )

    def pay(self, order_id: int, amount_som: int) -> None:
        self.statuses[order_id] = ("paid", amount_som)


@pytest.fixture
async def engine() -> AsyncIterator[AsyncEngine]:
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    yield engine
    await engine.dispose()


@pytest.fixture
def sessions(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return create_session_factory(engine)


@pytest.fixture
def clock() -> Clock:
    return Clock()


@pytest.fixture
def ledger(sessions: async_sessionmaker[AsyncSession], clock: Clock) -> SqlPaymeLedger:
    return SqlPaymeLedger(sessions, merchant_id=CHECKOUTUZ_PROVIDER_NAME, clock=clock)


@pytest.fixture
def vendor() -> FakeCheckoutUz:
    return FakeCheckoutUz()


async def open_intent(
    ledger: SqlPaymeLedger,
    *,
    key: str = f"topup:{USER}:single:1",
    product: Product = Product.SINGLE,
    amount_minor: int = SINGLE_MINOR,
    provider: str = CHECKOUTUZ_PROVIDER_NAME,
    telegram_user_id: int = USER,
) -> PaymentIntent:
    is_plan = product is Product.STARTER
    opened = await ledger.open_intent(
        telegram_user_id=telegram_user_id,
        product=product,
        amount_minor=amount_minor,
        currency="UZS",
        idempotency_key=key,
        language="uz_latn",
        merchant_id=CHECKOUTUZ_PROVIDER_NAME,
        is_sandbox=False,
        plan_songs=12 if is_plan else None,
        plan_days=30 if is_plan else None,
        provider=provider,
    )
    assert is_ok(opened), opened
    return opened.value


async def record_payment(
    sessions: async_sessionmaker[AsyncSession],
    intent: PaymentIntent,
    *,
    order_id: int = ORDER,
    amount_som: int | None = None,
    now: datetime = FIXED_NOW,
    lifetime_s: int = 3600,
) -> None:
    async with sessions.begin() as session:
        row = await intent_by_ref(session, intent.public_ref)
        assert row is not None
        wrote = await insert_payment(
            session,
            order_id=order_id,
            intent_id=row.id,
            payment_uuid=f"uuid-{order_id}",
            pay_url=f"https://checkout.uz/pay/uuid-{order_id}",
            amount_som=amount_som if amount_som is not None else intent.amount_minor // 100,
            link_valid_until=now + timedelta(seconds=lifetime_s),
            now=now,
        )
        assert wrote
