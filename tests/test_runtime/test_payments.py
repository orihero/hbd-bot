"""The payment seam. Out of scope means "always authorises", not "is not called"."""

from __future__ import annotations

from uuid import uuid4

from hbd.contracts import Ok, PaymentProvider
from hbd.payments import DEFAULT_CURRENCY, FREE_AMOUNT_MINOR, NoopPaymentProvider


def test_the_noop_provider_satisfies_the_protocol() -> None:
    assert isinstance(NoopPaymentProvider(), PaymentProvider)


async def test_it_authorises_and_echoes_back_what_it_was_asked_for() -> None:
    # Arrange
    order_id = uuid4()
    provider = NoopPaymentProvider()

    # Act
    result = await provider.authorize(
        order_id=order_id, amount_minor=FREE_AMOUNT_MINOR, currency=DEFAULT_CURRENCY
    )

    # Assert
    assert isinstance(result, Ok)
    assert result.value.is_authorized
    assert result.value.order_id == order_id
    assert result.value.currency == DEFAULT_CURRENCY


async def test_every_authorisation_carries_its_own_reference() -> None:
    # Arrange
    provider = NoopPaymentProvider()

    # Act
    first = await provider.authorize(order_id=uuid4(), amount_minor=0, currency="UZS")
    second = await provider.authorize(order_id=uuid4(), amount_minor=0, currency="UZS")

    # Assert: the field the real rail will populate is already unique per call.
    assert isinstance(first, Ok)
    assert isinstance(second, Ok)
    assert first.value.reference != second.value.reference


def test_the_bot_import_path_resolves_to_the_one_implementation() -> None:
    # Arrange / Act: two copies of "always authorises" is how billing day becomes a hunt.
    from hbd.bot.payment import NoopPaymentProvider as FromBot

    # Assert
    assert FromBot is NoopPaymentProvider
