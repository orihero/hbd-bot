"""``CompositeCheckoutProvider``: exact routing over an ordered list of rails.

The press names a rail and exactly that rail is charged; ``None`` (the generic button) goes to
the first rail; a name that matches no wired rail is a refusal, never a fall-through to a rail
the customer did not choose (``DECISIONS.md D28``). The ``primary=``/``secondary=`` keywords
the two-rail callers use must keep routing exactly as they always did.
"""

from __future__ import annotations

import pytest

from bayram.checkout import (
    CheckoutProvider,
    CompositeCheckoutProvider,
    Product,
    Purchase,
    PurchaseRequest,
)
from bayram.contracts import Err, Ok, Result, ok
from bayram.errors import CheckoutError


class _Rail:
    def __init__(self, name: str) -> None:
        self.name = name
        self.calls: list[PurchaseRequest] = []

    async def charge(self, request: PurchaseRequest) -> Result[Purchase]:
        self.calls.append(request)
        return ok(
            Purchase(
                product=request.product,
                provider=self.name,
                reference=f"{self.name}-ref",
                amount_minor=request.amount_minor,
                currency=request.currency,
                is_paid=False,
                checkout_url=f"https://{self.name}.example.com",
            )
        )


class _Raising(_Rail):
    async def charge(self, request: PurchaseRequest) -> Result[Purchase]:
        raise RuntimeError("a rail that broke its contract")


def _request(preferred: str | None) -> PurchaseRequest:
    return PurchaseRequest(
        telegram_user_id=1,
        product=Product.SINGLE,
        amount_minor=1_500_000,
        currency="UZS",
        idempotency_key="topup:1:sess:0",
        preferred_provider=preferred,
    )


def _three() -> tuple[CompositeCheckoutProvider, _Rail, _Rail, _Rail]:
    rhmt, payme, cuz = _Rail("rhmt"), _Rail("payme"), _Rail("checkoutuz")
    return CompositeCheckoutProvider([rhmt, payme, cuz]), rhmt, payme, cuz


def test_the_composite_names_its_rails_in_order() -> None:
    composite, rhmt, payme, _ = _three()

    assert isinstance(composite, CheckoutProvider)
    assert composite.name == "rhmt+payme+checkoutuz"
    assert composite.rail_names == ("rhmt", "payme", "checkoutuz")
    assert composite.primary is rhmt
    assert composite.secondary is payme
    assert len(composite.providers) == 3


@pytest.mark.parametrize("preferred", ["rhmt", "payme", "checkoutuz", " CheckoutUZ "])
async def test_a_named_rail_is_charged_and_no_other(preferred: str) -> None:
    composite, *rails = _three()

    result = await composite.charge(_request(preferred))

    assert isinstance(result, Ok)
    wanted = preferred.strip().lower()
    assert result.value.provider == wanted
    for rail in rails:
        assert len(rail.calls) == (1 if rail.name == wanted else 0)


async def test_no_preference_goes_to_the_first_rail() -> None:
    composite, rhmt, payme, cuz = _three()

    result = await composite.charge(_request(None))

    assert isinstance(result, Ok)
    assert result.value.provider == "rhmt"
    assert (len(rhmt.calls), len(payme.calls), len(cuz.calls)) == (1, 0, 0)


@pytest.mark.parametrize("preferred", ["stub", "click", ""])
async def test_an_unknown_preference_is_refused_and_charges_nothing(preferred: str) -> None:
    composite, *rails = _three()

    result = await composite.charge(_request(preferred))

    assert isinstance(result, Err)
    assert isinstance(result.error, CheckoutError)
    assert all(rail.calls == [] for rail in rails)


async def test_a_rail_that_raises_becomes_an_err() -> None:
    composite = CompositeCheckoutProvider([_Raising("rhmt"), _Rail("payme")])

    result = await composite.charge(_request(None))

    assert isinstance(result, Err)
    assert isinstance(result.error, CheckoutError)


async def test_the_two_rail_keyword_shim_still_routes_as_before() -> None:
    primary, secondary = _Rail("rhmt"), _Rail("payme")
    composite = CompositeCheckoutProvider(primary=primary, secondary=secondary)

    assert composite.name == "rhmt+payme"
    assert composite.rail_names == ("rhmt", "payme")
    assert composite.primary is primary
    assert composite.secondary is secondary
    for preferred, expected in ((None, "rhmt"), ("rhmt", "rhmt"), ("payme", "payme")):
        result = await composite.charge(_request(preferred))
        assert isinstance(result, Ok)
        assert result.value.provider == expected


def test_a_primary_only_shim_is_a_one_rail_composite() -> None:
    only = _Rail("payme")
    composite = CompositeCheckoutProvider(primary=only)

    assert composite.name == "payme"
    assert composite.secondary is None
    assert composite.rail_names == ("payme",)


def test_construction_refuses_no_rails_and_mixed_forms() -> None:
    with pytest.raises(ValueError):
        CompositeCheckoutProvider([])
    with pytest.raises(ValueError):
        CompositeCheckoutProvider()
    with pytest.raises(ValueError):
        CompositeCheckoutProvider([_Rail("rhmt")], primary=_Rail("payme"))
