"""The payment seam. Out of scope means "always authorises", not "is not called".

The second half of this module tests the ONE thing that is metered in this build. Payment
is still a no-op; entitlement is not, and it rides the same ``authorize`` call as a
decorator over the untouched no-op provider rather than as a second seam.
"""

from __future__ import annotations

from uuid import UUID, uuid4

from hbd.contracts import Err, Ok, PaymentAuthorization, PaymentProvider, Result, ok
from hbd.entitlements import InsufficientCreditsError
from hbd.errors import StorageError
from hbd.payments import (
    DEFAULT_CURRENCY,
    FREE_AMOUNT_MINOR,
    CreditGatedPaymentProvider,
    NoopPaymentProvider,
)
from tests.test_runtime.conftest import RecordingEntitlementStore

#: Any Telegram id will do: the no-op provider authorises everyone. It is a named constant
#: only so the three calls below agree, which is what makes "the payer never reaches the
#: authorisation" a visible difference rather than a coincidence of literals.
PAYER_ID: int = 99_000_111


def test_the_noop_provider_satisfies_the_protocol() -> None:
    assert isinstance(NoopPaymentProvider(), PaymentProvider)


async def test_it_authorises_and_echoes_back_what_it_was_asked_for() -> None:
    # Arrange
    order_id = uuid4()
    provider = NoopPaymentProvider()

    # Act
    result = await provider.authorize(
        order_id=order_id,
        amount_minor=FREE_AMOUNT_MINOR,
        currency=DEFAULT_CURRENCY,
        telegram_user_id=PAYER_ID,
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
    first = await provider.authorize(
        order_id=uuid4(), amount_minor=0, currency="UZS", telegram_user_id=PAYER_ID
    )
    second = await provider.authorize(
        order_id=uuid4(), amount_minor=0, currency="UZS", telegram_user_id=PAYER_ID
    )

    # Assert: the field the real rail will populate is already unique per call.
    assert isinstance(first, Ok)
    assert isinstance(second, Ok)
    assert first.value.reference != second.value.reference


def test_the_bot_import_path_resolves_to_the_one_implementation() -> None:
    # Arrange / Act: two copies of "always authorises" is how billing day becomes a hunt.
    from hbd.bot.payment import NoopPaymentProvider as FromBot

    # Assert
    assert FromBot is NoopPaymentProvider


# ---------------------------------------------------------------------------
# CreditGatedPaymentProvider — the render gate, decorating the seam above
# ---------------------------------------------------------------------------
class _DecliningProvider:
    """Authorises nobody. Stands in for the real rail this decorator will one day wrap."""

    name = "declining"

    def __init__(self) -> None:
        self.calls: list[UUID] = []

    async def authorize(
        self, *, order_id: UUID, amount_minor: int, currency: str, telegram_user_id: int
    ) -> Result[PaymentAuthorization]:
        self.calls.append(order_id)
        return ok(
            PaymentAuthorization(
                order_id=order_id,
                provider=self.name,
                reference="declined",
                amount_minor=amount_minor,
                currency=currency,
                is_authorized=False,
            )
        )


def _gate(
    store: RecordingEntitlementStore, *, inner: PaymentProvider | None = None
) -> CreditGatedPaymentProvider:
    return CreditGatedPaymentProvider(inner or NoopPaymentProvider(), store)


async def _authorize(
    gate: CreditGatedPaymentProvider, *, order_id: UUID | None = None
) -> Result[PaymentAuthorization]:
    return await gate.authorize(
        order_id=order_id or uuid4(),
        amount_minor=FREE_AMOUNT_MINOR,
        currency=DEFAULT_CURRENCY,
        telegram_user_id=PAYER_ID,
    )


def test_the_credit_gate_satisfies_the_same_protocol_it_decorates() -> None:
    # Arrange / Act / Assert: it has to drop into the seam without changing a call site.
    assert isinstance(_gate(RecordingEntitlementStore()), PaymentProvider)


async def test_the_gate_charges_whatever_the_enforcement_flag_says() -> None:
    """``credits_enforced`` no longer reaches this class, and that is the fix.

    It used to short-circuit here, which made the decorator the only caller of ``charge``
    that never ran — and since the in-flight cap counts unsettled DEBIT rows, and the
    worker's block check lives inside that same call, the shipped configuration enforced
    NEITHER. The flag now lives on ``EntitlementPolicy.is_balance_enforced``, where it gates
    the single predicate it is about; this decorator always charges, and the store decides
    what a shortfall means. ``tests/test_pipeline/test_render_gate.py`` proves the dark
    behaviour end to end against the real ``SqlCreditLedger``.
    """
    # Arrange
    store = RecordingEntitlementStore(credits=3)

    # Act
    result = await _authorize(_gate(store))

    # Assert
    assert isinstance(result, Ok)
    assert result.value.is_authorized
    assert len(store.movements) == 1
    assert store.credits == 2


async def test_an_enforced_gate_takes_exactly_one_credit_for_an_authorised_order() -> None:
    # Arrange
    store = RecordingEntitlementStore(credits=3)

    # Act
    result = await _authorize(_gate(store))

    # Assert
    assert isinstance(result, Ok)
    assert result.value.is_authorized
    assert store.credits == 2
    assert [kind for kind, _, _ in store.movements] == ["debit"]


async def test_a_declined_inner_provider_burns_no_credit() -> None:
    """The decorator delegates FIRST and charges only on an authorised result.

    Today the inner provider authorises everyone, so this looks academic — but the day a
    real rail lands inside the chain, charging first would take a credit for a card that was
    declined, and there is no path in this build by which the customer gets it back.
    """
    # Arrange
    inner = _DecliningProvider()
    store = RecordingEntitlementStore(credits=3)

    # Act
    result = await _authorize(_gate(store, inner=inner))

    # Assert: the inner rail was asked, and the ledger was not touched at all.
    assert len(inner.calls) == 1
    assert isinstance(result, Ok)
    assert not result.value.is_authorized
    assert store.movements == []
    assert store.credits == 3


async def test_an_exhausted_allowance_is_refused_as_an_error_not_as_a_polite_decline() -> None:
    """An out-of-credits customer must not be told the studio could not take their payment.

    ``is_authorized=False`` renders ``error.payment_failed`` at the worker and
    ``wizard.payment_declined`` at the bot — both of which describe a payment rail this
    build does not have. An ``Err`` carries its own locale key and its own scalars, so the
    refusal says which one it was and how much was left, with no change to either gate.
    """
    # Arrange
    store = RecordingEntitlementStore(credits=0)

    # Act
    result = await _authorize(_gate(store))

    # Assert
    assert isinstance(result, Err)
    assert isinstance(result.error, InsufficientCreditsError)
    assert result.error.user_message_key == "error.credits_exhausted"
    assert result.error.context["balance"] == 0
    # Non-retryable, or the ARQ ladder in hbd.runtime.jobs re-runs the whole pipeline on a
    # schedule for a customer whose answer cannot change until the calendar does.
    assert not result.is_retryable


async def test_a_blocked_account_is_refused_with_the_block_message_not_the_credit_one() -> None:
    # Arrange
    store = RecordingEntitlementStore(credits=3, is_blocked=True)

    # Act
    result = await _authorize(_gate(store))

    # Assert
    assert isinstance(result, Err)
    assert result.error.user_message_key == "error.blocked"
    assert store.credits == 3


async def test_the_same_order_authorised_twice_is_charged_once() -> None:
    """The gate runs at least twice per order: the worker, then every ARQ retry of the job.

    Replay is decided by the order's NET position rather than by the presence of a debit
    row, which is what lets a refunded order be charged again while a paid one is not.
    """
    # Arrange
    store = RecordingEntitlementStore(credits=3)
    gate = _gate(store)
    order_id = uuid4()

    # Act
    first = await _authorize(gate, order_id=order_id)
    second = await _authorize(gate, order_id=order_id)

    # Assert: ALREADY_PAID authorises, and it is not an error.
    assert isinstance(first, Ok)
    assert isinstance(second, Ok)
    assert second.value.is_authorized
    assert store.credits == 2
    assert [kind for kind, _, _ in store.movements] == ["debit"]


async def test_a_database_outage_at_the_gate_stays_retryable() -> None:
    """A refusal and an outage arrive by the same door and must not be flattened together.

    The gate returns the store's error untouched precisely so that ``Err.is_retryable`` —
    False for every entitlement refusal, True for a transport failure — keeps deciding
    whether ARQ tries again.
    """
    # Arrange
    store = RecordingEntitlementStore(credits=3)
    store.charge_failure = StorageError("the ledger is unreachable")

    # Act
    result = await _authorize(_gate(store))

    # Assert
    assert isinstance(result, Err)
    assert result.is_retryable


def test_the_bot_import_path_resolves_to_the_one_credit_gate() -> None:
    # Arrange / Act: the bot may name the gate; it may never wire one. See hbd.bot.payment.
    from hbd.bot.payment import CreditGatedPaymentProvider as FromBot

    # Assert
    assert FromBot is CreditGatedPaymentProvider
