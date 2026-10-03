"""Tests for RhmtCheckoutProvider and CompositeCheckoutProvider."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from bayram.checkout import (
    CompositeCheckoutProvider,
    PaymentIntent,
    PaymentIntentOpener,
    PaymentIntentState,
    Product,
    Purchase,
    PurchaseRequest,
)
from bayram.contracts import Err, Language, Ok, Result, err, ok
from bayram.errors import CheckoutPausedError, PaymentError
from bayram.rhmt.client import RhmtInvoice
from bayram.rhmt.ports import RHMT_PROVIDER_NAME
from bayram.rhmt.provider import RhmtCheckoutProvider


class FakeOpener(PaymentIntentOpener):
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []
        self.should_fail = False

    async def open_intent(
        self,
        *,
        telegram_user_id: int,
        product: Product,
        amount_minor: int,
        currency: str,
        idempotency_key: str,
        language: str,
        merchant_id: str,
        is_sandbox: bool,
        plan_songs: int | None = None,
        plan_days: int | None = None,
        resume_order_id: Any | None = None,
        provider: str = "payme",
    ) -> Result[PaymentIntent]:
        self.calls.append(
            {
                "telegram_user_id": telegram_user_id,
                "product": product,
                "amount_minor": amount_minor,
                "currency": currency,
                "idempotency_key": idempotency_key,
                "language": language,
                "merchant_id": merchant_id,
                "is_sandbox": is_sandbox,
                "plan_songs": plan_songs,
                "plan_days": plan_days,
                "resume_order_id": resume_order_id,
                "provider": provider,
            }
        )
        if self.should_fail:
            return err(PaymentError("Failed to open intent in DB"))

        now = datetime.now(UTC)
        return ok(
            PaymentIntent(
                public_ref="ref_rhmt_123456",
                idempotency_key=idempotency_key,
                telegram_user_id=telegram_user_id,
                product=product,
                amount_minor=amount_minor,
                currency=currency,
                language=language,
                merchant_id=merchant_id,
                is_sandbox=is_sandbox,
                plan_songs=plan_songs,
                plan_days=plan_days,
                state=PaymentIntentState.PENDING,
                valid_until=now,
                settled_at=None,
                notified_at=None,
                resume_order_id=resume_order_id,
            )
        )


class FakeRhmtClient:
    def __init__(self) -> None:
        self.invoice_calls: list[dict[str, Any]] = []
        self.should_fail = False

    async def create_invoice(
        self,
        *,
        store_id: int,
        amount_minor: int,
        invoice_id: str,
        callback_url: str,
        return_url: str,
        language: str = "uz",
        ofd: list[dict[str, Any]] | None = None,
    ) -> Result[RhmtInvoice]:
        self.invoice_calls.append(
            {
                "store_id": store_id,
                "amount_minor": amount_minor,
                "invoice_id": invoice_id,
                "callback_url": callback_url,
                "return_url": return_url,
                "language": language,
            }
        )
        if self.should_fail:
            return err(PaymentError("Rahmat API refused invoice creation"))

        return ok(
            RhmtInvoice(
                uuid="uuid-rhmt-xyz",
                invoice_id=invoice_id,
                amount_minor=amount_minor,
                checkout_url="https://app.rhmt.uz/uuid-rhmt-xyz",
                status="created",
                raw={},
            )
        )


async def _not_paused() -> bool:
    return False


async def _is_paused() -> bool:
    return True


async def test_rhmt_checkout_provider_charge_single_song_success() -> None:
    opener = FakeOpener()
    client = FakeRhmtClient()

    provider = RhmtCheckoutProvider(
        opener=opener,
        client=client,  # type: ignore[arg-type]
        store_id=1010,
        callback_url="https://pay.bayrambot.uz/rhmt/callback",
        return_url="https://t.me/BayramBot",
        is_sandbox=True,
        plan_songs=12,
        plan_days=30,
        language_of=lambda: Language.UZ_LATN,
        paused=_not_paused,
    )

    req = PurchaseRequest(
        telegram_user_id=12345,
        product=Product.SINGLE,
        amount_minor=700000,
        currency="UZS",
        idempotency_key="topup:12345:s1:0",
    )

    res = await provider.charge(req)
    assert isinstance(res, Ok)
    purchase = res.value
    assert isinstance(purchase, Purchase)
    assert purchase.is_paid is False
    assert purchase.provider == RHMT_PROVIDER_NAME
    assert purchase.reference == "ref_rhmt_123456"
    assert purchase.checkout_url == "https://app.rhmt.uz/uuid-rhmt-xyz"

    # Verify opener call
    assert len(opener.calls) == 1
    assert opener.calls[0]["provider"] == RHMT_PROVIDER_NAME
    assert opener.calls[0]["merchant_id"] == "1010"

    # Verify invoice call
    assert len(client.invoice_calls) == 1
    assert client.invoice_calls[0]["invoice_id"] == "ref_rhmt_123456"
    assert client.invoice_calls[0]["amount_minor"] == 700000


async def test_rhmt_checkout_provider_charge_starter_plan() -> None:
    opener = FakeOpener()
    client = FakeRhmtClient()

    provider = RhmtCheckoutProvider(
        opener=opener,
        client=client,  # type: ignore[arg-type]
        store_id=1010,
        callback_url="https://pay.bayrambot.uz/rhmt/callback",
        return_url="https://t.me/BayramBot",
        is_sandbox=False,
        plan_songs=12,
        plan_days=30,
        language_of=lambda: Language.RU,
        paused=_not_paused,
    )

    req = PurchaseRequest(
        telegram_user_id=12345,
        product=Product.STARTER,
        amount_minor=4900000,
        currency="UZS",
        idempotency_key="plan:starter:12345:s1:0",
    )

    res = await provider.charge(req)
    assert isinstance(res, Ok)
    assert opener.calls[0]["plan_songs"] == 12
    assert opener.calls[0]["plan_days"] == 30
    assert opener.calls[0]["is_sandbox"] is False
    assert opener.calls[0]["language"] == "ru"


async def test_rhmt_checkout_provider_paused_rail_refuses() -> None:
    opener = FakeOpener()
    client = FakeRhmtClient()

    provider = RhmtCheckoutProvider(
        opener=opener,
        client=client,  # type: ignore[arg-type]
        store_id=1010,
        callback_url="https://pay.bayrambot.uz/rhmt/callback",
        return_url="https://t.me/BayramBot",
        is_sandbox=True,
        plan_songs=12,
        plan_days=30,
        language_of=lambda: Language.UZ_LATN,
        paused=_is_paused,
    )

    req = PurchaseRequest(
        telegram_user_id=12345,
        product=Product.SINGLE,
        amount_minor=700000,
        currency="UZS",
        idempotency_key="topup:12345:s1:0",
    )

    res = await provider.charge(req)
    assert isinstance(res, Err)
    assert isinstance(res.error, CheckoutPausedError)
    assert len(opener.calls) == 0
    assert len(client.invoice_calls) == 0


async def test_rhmt_checkout_provider_opener_failure() -> None:
    opener = FakeOpener()
    opener.should_fail = True
    client = FakeRhmtClient()

    provider = RhmtCheckoutProvider(
        opener=opener,
        client=client,  # type: ignore[arg-type]
        store_id=1010,
        callback_url="https://pay.bayrambot.uz/rhmt/callback",
        return_url="https://t.me/BayramBot",
        is_sandbox=True,
        plan_songs=12,
        plan_days=30,
        language_of=lambda: Language.UZ_LATN,
        paused=_not_paused,
    )

    req = PurchaseRequest(
        telegram_user_id=12345,
        product=Product.SINGLE,
        amount_minor=700000,
        currency="UZS",
        idempotency_key="topup:12345:s1:0",
    )

    res = await provider.charge(req)
    assert isinstance(res, Err)
    assert len(client.invoice_calls) == 0


async def test_composite_checkout_provider_routing() -> None:
    class StubProvider:
        def __init__(self, name: str) -> None:
            self.name = name
            self.calls: list[PurchaseRequest] = []

        async def charge(self, request: PurchaseRequest) -> Result[Purchase]:
            self.calls.append(request)
            return ok(
                Purchase(
                    product=request.product,
                    amount_minor=request.amount_minor,
                    currency=request.currency,
                    is_paid=False,
                    provider=self.name,
                    reference="ref",
                    checkout_url=f"https://{self.name}.example.com",
                )
            )

    primary = StubProvider("rhmt")
    secondary = StubProvider("payme")
    composite = CompositeCheckoutProvider(primary=primary, secondary=secondary)

    # 1. No preferred_provider -> primary (Rahmat)
    req1 = PurchaseRequest(
        telegram_user_id=1,
        product=Product.SINGLE,
        amount_minor=700000,
        currency="UZS",
        idempotency_key="k1",
        preferred_provider=None,
    )
    res1 = await composite.charge(req1)
    assert isinstance(res1, Ok)
    assert res1.value.provider == "rhmt"
    assert len(primary.calls) == 1
    assert len(secondary.calls) == 0

    # 2. Explicit preferred_provider="rhmt" -> primary (Rahmat)
    req2 = PurchaseRequest(
        telegram_user_id=1,
        product=Product.SINGLE,
        amount_minor=700000,
        currency="UZS",
        idempotency_key="k2",
        preferred_provider="rhmt",
    )
    res2 = await composite.charge(req2)
    assert isinstance(res2, Ok)
    assert res2.value.provider == "rhmt"
    assert len(primary.calls) == 2
    assert len(secondary.calls) == 0

    # 3. Explicit preferred_provider="payme" -> secondary (Payme)
    req3 = PurchaseRequest(
        telegram_user_id=1,
        product=Product.SINGLE,
        amount_minor=700000,
        currency="UZS",
        idempotency_key="k3",
        preferred_provider="payme",
    )
    res3 = await composite.charge(req3)
    assert isinstance(res3, Ok)
    assert res3.value.provider == "payme"
    assert len(primary.calls) == 2
    assert len(secondary.calls) == 1
