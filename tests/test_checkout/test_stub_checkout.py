"""The buying seam: what the stub rail promises, and the two plan predicates that differ.

The stub is not a mock. It is what the shipped composition root wires — the decided scope is
"just put the buttons, we will implement Payme later" — so its behaviour is production
behaviour and is pinned as such. Two of its properties are easy to get wrong in the direction
that only shows up in production:

* **It deduplicates NOTHING.** Two charges with the same idempotency key both succeed and
  both get their own reference. Deduplication belongs to the ledger's unique index, one layer
  down, and a provider that quietly returned the same receipt twice would hide the fact that
  it had been called twice — which is precisely the signal an operator needs when a customer
  says they were billed twice. A real rail behaves this way too, so the tests are written
  against the real shape rather than against the stub's convenience.
* **``is_live`` and ``is_current`` are different questions.** ``is_live`` asks "can this plan
  still mint a song?"; ``is_current`` asks "is a plan running at all?". A customer who spent
  all twelve songs on day three still OWNS the starter plan, and selling them a second one
  would silently overwrite an end date they have already paid for. The gap between those two
  predicates is the whole top-up story.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from hbd.checkout import (
    STUB_PROVIDER_NAME,
    CheckoutProvider,
    Plan,
    PlanState,
    Product,
    PurchaseRequest,
    StubCheckoutProvider,
)
from hbd.contracts import is_ok

#: A fixed instant. Every predicate below is a pure function of an injected clock, so nothing
#: here needs wall time and nothing here can go red at midnight.
_NOW = datetime(2026, 9, 6, 12, 0, tzinfo=UTC)


def _request(*, key: str = "topup:1:sess:0") -> PurchaseRequest:
    """One single-song purchase request, priced the way the shipped settings price it."""
    return PurchaseRequest(
        telegram_user_id=1,
        product=Product.SINGLE,
        amount_minor=700_000,
        currency="UZS",
        idempotency_key=key,
    )


# ---------------------------------------------------------------------------
# The seam
# ---------------------------------------------------------------------------
async def test_the_stub_provider_satisfies_the_checkout_protocol() -> None:
    # Arrange / Act / Assert — ``runtime_checkable`` verifies member PRESENCE only, never
    # signatures, so this asserts the wiring will not blow up at the composition root and
    # ``mypy --strict`` over ``tests`` is what actually catches a drifted signature.
    assert isinstance(StubCheckoutProvider(), CheckoutProvider)
    assert StubCheckoutProvider().name == STUB_PROVIDER_NAME


async def test_a_charge_echoes_the_amount_currency_and_product_it_was_asked_for() -> None:
    # Arrange — the receipt has to quote back exactly what was requested, because it is what
    # the fulfiller writes into the ledger and what an operator later reconciles against.
    provider = StubCheckoutProvider()
    request = _request()

    # Act
    result = await provider.charge(request)

    # Assert
    assert is_ok(result)
    purchase = result.value
    assert purchase.product is Product.SINGLE
    assert purchase.amount_minor == request.amount_minor
    assert purchase.currency == request.currency
    assert purchase.provider == STUB_PROVIDER_NAME
    assert purchase.reference.startswith("stub-")
    assert purchase.checkout_url is None


async def test_the_stub_always_reports_the_purchase_paid() -> None:
    # Arrange — ``is_paid`` is what the fulfiller refuses on, and the stub contacts nothing,
    # so it can only ever answer True. The ``Result`` return type exists for the rail that
    # will one day answer otherwise, not for this class.
    provider = StubCheckoutProvider()

    # Act
    result = await provider.charge(_request())

    # Assert
    assert is_ok(result)
    assert result.value.is_paid is True


async def test_two_charges_with_one_idempotency_key_both_succeed_at_the_provider() -> None:
    # Arrange — deduplication is the LEDGER's job, on its own unique index. A provider that
    # collapsed the second call would hide a double tap instead of letting the write side
    # absorb it, and would give an operator no way to see that it happened.
    provider = StubCheckoutProvider()
    request = _request(key="topup:1:sess:0")

    # Act
    first = await provider.charge(request)
    second = await provider.charge(request)

    # Assert — both Ok, and two distinct references, which is exactly what a real rail does.
    assert is_ok(first)
    assert is_ok(second)
    assert first.value.reference != second.value.reference


# ---------------------------------------------------------------------------
# The plan predicates
# ---------------------------------------------------------------------------
async def test_an_expired_plan_is_neither_live_nor_current() -> None:
    # Arrange — the calendar ran out. Nothing is minted and nothing is offered as a top-up,
    # because there is no plan any more; the customer is sold a fresh one.
    plan = PlanState(
        plan=Plan.STARTER,
        songs_included=12,
        songs_used=3,
        ends_at=_NOW - timedelta(seconds=1),
    )

    # Act / Assert
    assert plan.songs_left == 9
    assert not plan.is_live(_NOW)
    assert not plan.is_current(_NOW)


async def test_a_spent_but_unexpired_plan_is_current_and_not_live() -> None:
    # Arrange — the case the two predicates exist for. Twelve songs used on day three: the
    # plan can mint nothing, so it is not live, but it is still THE running plan, so a second
    # one must not be sold over the end date this customer already paid for.
    plan = PlanState(
        plan=Plan.STARTER,
        songs_included=12,
        songs_used=12,
        ends_at=_NOW + timedelta(days=27),
    )

    # Act / Assert
    assert plan.songs_left == 0
    assert not plan.is_live(_NOW)
    assert plan.is_current(_NOW)


async def test_songs_left_is_floored_at_zero_rather_than_reported_negative() -> None:
    # Arrange — the database CHECK is what keeps the row honest. A reader that raised, or
    # returned a negative, would turn a reporting problem into an outage at the exact moment
    # an operator needs to look at the drift.
    plan = PlanState(
        plan=Plan.STARTER,
        songs_included=12,
        songs_used=15,
        ends_at=_NOW + timedelta(days=1),
    )

    # Act / Assert
    assert plan.songs_left == 0
    assert not plan.is_live(_NOW)
    assert plan.is_current(_NOW)


async def test_a_fresh_plan_is_both_live_and_current() -> None:
    # Arrange / Act / Assert — the ordinary case, pinned so the two predicates cannot both
    # drift to the same answer without something going red.
    plan = PlanState(
        plan=Plan.STARTER, songs_included=12, songs_used=0, ends_at=_NOW + timedelta(days=30)
    )
    assert plan.songs_left == 12
    assert plan.is_live(_NOW)
    assert plan.is_current(_NOW)
