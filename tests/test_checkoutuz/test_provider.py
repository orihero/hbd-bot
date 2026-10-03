"""``CheckoutUzCheckoutProvider.charge`` — refusals first, one link per live window, never a grant.

A fake opener, a fake vendor and an in-memory store, so each test can say exactly what was
opened, created and recorded. The store's SQL half is exercised once at the bottom against the
real ledger on SQLite (``DECISIONS.md D28``).
"""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta
from typing import Any
from uuid import UUID

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from bayram.checkout import (
    PaymentIntent,
    PaymentIntentState,
    Product,
    PurchaseRequest,
)
from bayram.checkoutuz.ports import CHECKOUTUZ_PROVIDER_NAME, LINK_REUSE_MARGIN_S
from bayram.checkoutuz.provider import (
    CheckoutUzCheckoutProvider,
    CheckoutUzLink,
    SqlCheckoutUzPaymentStore,
    _stored_pay_via,
)
from bayram.contracts import Err, Language, Ok, Result, err, ok
from bayram.db.payme import SqlPaymeLedger
from bayram.errors import (
    CheckoutError,
    CheckoutPausedError,
    CheckoutRailDisabledError,
    StorageError,
)
from tests.test_checkoutuz.conftest import (
    ORDER,
    PLAN_MINOR,
    SINGLE_MINOR,
    USER,
    Clock,
    FakeCheckoutUz,
)

_WEBHOOK_BASE = "https://pay.bayrambot.uz/checkoutuz/callback/"
_RETURN = "https://t.me/BayramBot"


class FakeOpener:
    def __init__(self, clock: Clock) -> None:
        self._clock = clock
        self.calls: list[dict[str, Any]] = []
        self.provider_override: str | None = None
        self.state_override: PaymentIntentState | None = None
        self.intents: dict[str, PaymentIntent] = {}

    async def open_intent(self, **kwargs: Any) -> Result[PaymentIntent]:
        self.calls.append(kwargs)
        key = kwargs["idempotency_key"]
        intent = self.intents.get(key)
        if intent is None:
            intent = PaymentIntent(
                public_ref=f"ref{len(self.intents):021d}",
                idempotency_key=key,
                telegram_user_id=kwargs["telegram_user_id"],
                product=kwargs["product"],
                amount_minor=kwargs["amount_minor"],
                currency=kwargs["currency"],
                language=kwargs["language"],
                merchant_id=kwargs["merchant_id"],
                is_sandbox=kwargs["is_sandbox"],
                plan_songs=kwargs["plan_songs"],
                plan_days=kwargs["plan_days"],
                state=PaymentIntentState.PENDING,
                valid_until=self._clock.now + timedelta(hours=12),
                settled_at=None,
                notified_at=None,
                resume_order_id=kwargs["resume_order_id"],
                provider=kwargs["provider"],
            )
            self.intents[key] = intent
        if self.provider_override is not None:
            intent = replace(intent, provider=self.provider_override)
        if self.state_override is not None:
            intent = replace(intent, state=self.state_override)
        return ok(intent)


class MemoryStore:
    def __init__(self) -> None:
        self.rows: list[dict[str, Any]] = []
        self.fail_record = False
        self.duplicate = False

    async def live_link(
        self, *, public_ref: str, now: datetime, margin_s: int
    ) -> Result[CheckoutUzLink | None]:
        live = [
            r
            for r in self.rows
            if r["public_ref"] == public_ref
            and r["link_valid_until"] > now + timedelta(seconds=margin_s)
        ]
        if not live:
            return ok(None)
        r = live[-1]
        return ok(
            CheckoutUzLink(
                r["order_id"], r["pay_url"], r["link_valid_until"], tuple(r.get("pay_via", ()))
            )
        )

    async def record_link(self, **kwargs: Any) -> Result[bool]:
        if self.fail_record:
            return err(StorageError("db down"))
        if self.duplicate:
            return ok(False)
        self.rows.append(kwargs)
        return ok(True)


class Switch:
    def __init__(self, value: bool = True) -> None:
        self.value = value
        self.raises = False

    async def __call__(self) -> bool:
        if self.raises:
            raise ConnectionError("redis down")
        return self.value


@pytest.fixture
def opener(clock: Clock) -> FakeOpener:
    return FakeOpener(clock)


@pytest.fixture
def store() -> MemoryStore:
    return MemoryStore()


@pytest.fixture
def enabled() -> Switch:
    return Switch(True)


@pytest.fixture
def paused() -> Switch:
    return Switch(False)


def _provider(
    opener: Any,
    vendor: FakeCheckoutUz,
    store: Any,
    *,
    clock: Clock,
    enabled: Switch,
    paused: Switch,
) -> CheckoutUzCheckoutProvider:
    return CheckoutUzCheckoutProvider(
        opener,
        vendor,
        store,
        webhook_base_url=_WEBHOOK_BASE,
        return_url=_RETURN,
        plan_songs=12,
        plan_days=30,
        language_of=lambda: Language.UZ_LATN,
        paused=paused,
        enabled=enabled,
        clock=clock,
    )


@pytest.fixture
def provider(
    opener: FakeOpener,
    vendor: FakeCheckoutUz,
    store: MemoryStore,
    clock: Clock,
    enabled: Switch,
    paused: Switch,
) -> CheckoutUzCheckoutProvider:
    return _provider(opener, vendor, store, clock=clock, enabled=enabled, paused=paused)


def _request(
    *,
    product: Product = Product.SINGLE,
    amount_minor: int = SINGLE_MINOR,
    key: str = f"topup:{USER}:single:1:checkoutuz",
    resume_order_id: UUID | None = None,
) -> PurchaseRequest:
    return PurchaseRequest(
        telegram_user_id=USER,
        product=product,
        amount_minor=amount_minor,
        currency="UZS",
        idempotency_key=key,
        resume_order_id=resume_order_id,
        preferred_provider=CHECKOUTUZ_PROVIDER_NAME,
    )


async def test_a_press_opens_a_checkoutuz_intent_and_returns_an_unpaid_page(
    provider: CheckoutUzCheckoutProvider,
    opener: FakeOpener,
    vendor: FakeCheckoutUz,
    store: MemoryStore,
    clock: Clock,
) -> None:
    resume = UUID(int=7)

    result = await provider.charge(_request(resume_order_id=resume))

    assert isinstance(result, Ok)
    purchase = result.value
    assert purchase.is_paid is False
    assert purchase.provider == CHECKOUTUZ_PROVIDER_NAME
    assert purchase.checkout_url == f"https://checkout.uz/pay/uuid-{ORDER}"
    assert purchase.amount_minor == SINGLE_MINOR
    (call,) = opener.calls
    assert call["provider"] == CHECKOUTUZ_PROVIDER_NAME
    assert call["merchant_id"] == CHECKOUTUZ_PROVIDER_NAME
    assert call["is_sandbox"] is False
    assert call["resume_order_id"] == resume
    assert call["plan_songs"] is None
    ref = purchase.reference
    assert vendor.created == [
        {
            "amount_som": 7_000,
            "description": f"Bayram #{ref[:8]}",
            "webhook_url": f"https://pay.bayrambot.uz/checkoutuz/callback/{ref}",
            "return_url": _RETURN,
        }
    ]
    (row,) = store.rows
    assert row["order_id"] == ORDER
    assert row["amount_som"] == 7_000
    assert row["link_valid_until"] == clock.now + timedelta(seconds=3600)


async def test_a_plan_press_snapshots_the_plan(
    provider: CheckoutUzCheckoutProvider, opener: FakeOpener, vendor: FakeCheckoutUz
) -> None:
    result = await provider.charge(
        _request(product=Product.STARTER, amount_minor=PLAN_MINOR, key="topup:1:plan:1")
    )

    assert isinstance(result, Ok)
    assert opener.calls[0]["plan_songs"] == 12
    assert opener.calls[0]["plan_days"] == 30
    assert vendor.created[0]["amount_som"] == 49_000


async def test_a_re_press_reuses_the_live_link(
    provider: CheckoutUzCheckoutProvider, vendor: FakeCheckoutUz, clock: Clock
) -> None:
    first = await provider.charge(_request())
    clock.advance(seconds=600)
    second = await provider.charge(_request())

    assert isinstance(first, Ok) and isinstance(second, Ok)
    assert second.value.checkout_url == first.value.checkout_url
    assert len(vendor.created) == 1


_PAGES = (
    ("click", "https://checkout.uz/pay/u/click"),
    ("payme", "https://checkout.uz/pay/u/payme"),
)


async def test_a_new_link_carries_its_pay_methods_into_the_purchase_and_the_store(
    provider: CheckoutUzCheckoutProvider, vendor: FakeCheckoutUz, store: MemoryStore
) -> None:
    vendor.pay_via = _PAGES

    result = await provider.charge(_request())

    assert isinstance(result, Ok)
    assert result.value.pay_options == _PAGES
    (row,) = store.rows
    assert tuple(row["pay_via"]) == _PAGES


async def test_a_reused_link_carries_the_same_pay_methods(
    provider: CheckoutUzCheckoutProvider, vendor: FakeCheckoutUz, clock: Clock
) -> None:
    vendor.pay_via = _PAGES
    first = await provider.charge(_request())
    vendor.pay_via = ()
    clock.advance(seconds=600)
    second = await provider.charge(_request())

    assert isinstance(first, Ok) and isinstance(second, Ok)
    assert len(vendor.created) == 1
    assert second.value.pay_options == _PAGES


async def test_a_reply_without_pay_methods_gives_an_empty_tuple(
    provider: CheckoutUzCheckoutProvider,
) -> None:
    result = await provider.charge(_request())

    assert isinstance(result, Ok)
    assert result.value.pay_options == ()


@pytest.mark.parametrize(
    ("stored", "expected"),
    [
        (None, ()),
        ("garbage", ()),
        ({"click": "https://x"}, ()),
        (
            [["click", "https://x/click"], ["bad"], [1, "https://x"], ["p", "http://x"], "s"],
            (("click", "https://x/click"),),
        ),
    ],
)
def test_a_stored_pay_via_of_the_wrong_shape_reads_as_none(
    stored: object, expected: tuple[tuple[str, str], ...]
) -> None:
    assert _stored_pay_via(stored) == expected


async def test_a_lapsing_link_is_replaced_and_the_old_row_kept(
    provider: CheckoutUzCheckoutProvider, vendor: FakeCheckoutUz, store: MemoryStore, clock: Clock
) -> None:
    first = await provider.charge(_request())
    clock.advance(seconds=3600 - LINK_REUSE_MARGIN_S)
    second = await provider.charge(_request())

    assert isinstance(first, Ok) and isinstance(second, Ok)
    assert second.value.checkout_url != first.value.checkout_url
    assert second.value.reference == first.value.reference
    assert len(vendor.created) == 2
    assert [r["order_id"] for r in store.rows] == [ORDER, ORDER + 1]


async def test_switched_off_refuses_before_opening_anything(
    provider: CheckoutUzCheckoutProvider,
    opener: FakeOpener,
    vendor: FakeCheckoutUz,
    enabled: Switch,
) -> None:
    enabled.value = False

    result = await provider.charge(_request())

    assert isinstance(result, Err)
    assert isinstance(result.error, CheckoutRailDisabledError)
    assert result.error.user_message_key == "checkout.rail_disabled"
    assert opener.calls == []
    assert vendor.created == []


async def test_paused_refuses_with_the_paused_error(
    provider: CheckoutUzCheckoutProvider, opener: FakeOpener, paused: Switch
) -> None:
    paused.value = True

    result = await provider.charge(_request())

    assert isinstance(result, Err)
    assert type(result.error) is CheckoutPausedError
    assert opener.calls == []


async def test_unreadable_switches_fail_open(
    provider: CheckoutUzCheckoutProvider, enabled: Switch, paused: Switch
) -> None:
    enabled.raises = True
    paused.raises = True

    result = await provider.charge(_request())

    assert isinstance(result, Ok)


@pytest.mark.parametrize("amount_minor", [700_050, 99_900, 1_000_000_100])
async def test_an_unpayable_amount_opens_no_intent(
    provider: CheckoutUzCheckoutProvider,
    opener: FakeOpener,
    vendor: FakeCheckoutUz,
    amount_minor: int,
) -> None:
    result = await provider.charge(_request(amount_minor=amount_minor))

    assert isinstance(result, Err)
    assert isinstance(result.error, CheckoutError)
    assert opener.calls == []
    assert vendor.created == []


async def test_a_foreign_rails_intent_is_refused(
    provider: CheckoutUzCheckoutProvider, opener: FakeOpener, vendor: FakeCheckoutUz
) -> None:
    opener.provider_override = "payme"

    result = await provider.charge(_request())

    assert isinstance(result, Err)
    assert result.error.context["intent_provider"] == "payme"
    assert vendor.created == []


@pytest.mark.parametrize(
    "state",
    [PaymentIntentState.PAID, PaymentIntentState.EXPIRED, PaymentIntentState.AWAITING],
)
async def test_a_non_pending_intent_creates_no_payment_and_is_never_a_paid_receipt(
    provider: CheckoutUzCheckoutProvider,
    opener: FakeOpener,
    vendor: FakeCheckoutUz,
    state: PaymentIntentState,
) -> None:
    opener.state_override = state

    result = await provider.charge(_request())

    assert isinstance(result, Err)
    assert vendor.created == []


async def test_an_amount_echo_mismatch_stores_nothing_and_hands_out_nothing(
    provider: CheckoutUzCheckoutProvider, vendor: FakeCheckoutUz, store: MemoryStore
) -> None:
    vendor.echo_amount_delta = 1

    result = await provider.charge(_request())

    assert isinstance(result, Err)
    assert store.rows == []


async def test_a_vendor_failure_is_returned(
    provider: CheckoutUzCheckoutProvider, vendor: FakeCheckoutUz
) -> None:
    vendor.create_error = CheckoutError("down", is_retryable=True)

    result = await provider.charge(_request())

    assert isinstance(result, Err)
    assert result.error is vendor.create_error


@pytest.mark.parametrize("failure", ["error", "duplicate"])
async def test_an_unrecorded_payment_is_not_handed_out(
    provider: CheckoutUzCheckoutProvider,
    store: MemoryStore,
    failure: str,
    caplog: pytest.LogCaptureFixture,
) -> None:
    store.fail_record = failure == "error"
    store.duplicate = failure == "duplicate"

    result = await provider.charge(_request())

    assert isinstance(result, Err)
    assert any(getattr(r, "event", None) == "checkoutuz.payment_unrecorded" for r in caplog.records)


async def test_the_sql_store_records_and_reuses_against_the_real_ledger(
    sessions: async_sessionmaker[AsyncSession],
    ledger: SqlPaymeLedger,
    vendor: FakeCheckoutUz,
    clock: Clock,
    enabled: Switch,
    paused: Switch,
) -> None:
    provider = _provider(
        ledger,
        vendor,
        SqlCheckoutUzPaymentStore(sessions),
        clock=clock,
        enabled=enabled,
        paused=paused,
    )
    vendor.pay_via = _PAGES

    first = await provider.charge(_request())
    second = await provider.charge(_request())
    clock.advance(seconds=3600)
    third = await provider.charge(_request())

    assert isinstance(first, Ok) and isinstance(second, Ok) and isinstance(third, Ok)
    assert first.value.checkout_url == second.value.checkout_url
    assert first.value.pay_options == second.value.pay_options == _PAGES
    assert third.value.checkout_url != first.value.checkout_url
    assert len(vendor.created) == 2
    found = await ledger.intent(public_ref=first.value.reference)
    assert isinstance(found, Ok) and found.value is not None
    assert found.value.provider == CHECKOUTUZ_PROVIDER_NAME


async def test_the_sql_store_refuses_a_payme_intent_under_the_same_key(
    sessions: async_sessionmaker[AsyncSession],
    ledger: SqlPaymeLedger,
    vendor: FakeCheckoutUz,
    clock: Clock,
    enabled: Switch,
    paused: Switch,
) -> None:
    key = f"topup:{USER}:single:1"
    await ledger.open_intent(
        telegram_user_id=USER,
        product=Product.SINGLE,
        amount_minor=SINGLE_MINOR,
        currency="UZS",
        idempotency_key=key,
        language="uz_latn",
        merchant_id="m",
        is_sandbox=True,
        provider="payme",
    )
    provider = _provider(
        ledger,
        vendor,
        SqlCheckoutUzPaymentStore(sessions),
        clock=clock,
        enabled=enabled,
        paused=paused,
    )

    result = await provider.charge(_request(key=key))

    assert isinstance(result, Err)
    assert vendor.created == []
