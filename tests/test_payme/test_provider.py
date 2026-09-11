"""The bot-side rail: one row, one URL, no socket, and an unpaid receipt on purpose.

Four claims are pinned here and each of them is one a reasonable reader doubts:

1. **``charge`` reports the purchase UNPAID.** Every other provider in this repository that
   returns ``Ok`` has taken the money. This one has not, and must not — the credit is granted
   in another process, minutes later, by ``PerformTransaction``. A ``Purchase`` with
   ``is_paid=True`` coming out of here would be a free song per press.
2. **A replayed idempotency key produces the same reference AND the same URL.** The store
   guarantees the first half; the pure, fixed-order link builder guarantees the second. Two
   different-looking links for one purchase in one chat is a customer with no way to tell
   which page their money went into.
3. **It contacts nothing.** ``test_the_payme_provider_holds_no_http_client`` scans the
   object's own attributes, because "contacts nothing" is a property that rots silently the
   first time somebody reaches for ``httpx`` inside ``charge`` to poll a payment's status.
4. **A Redis failure is not a pause.** The switch stops sales when an operator says so and
   never when infrastructure hiccups, and the direction of that default is a business
   decision rather than an implementation detail.

The opener is a hand-written fake rather than a real ``SqlPaymeLedger``, so nothing here needs
a database: this file is about the PROVIDER's behaviour, and the ledger's own replay
guarantees are proved against real SQL in ``tests/test_db/test_payme_ledger.py``. The fake
implements the same insert-or-ignore-on-the-key contract, which is what makes the replay test
below a test of this class and not of a mock.
"""

from __future__ import annotations

import base64
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Final

import pytest

import bayram.payme.provider as provider_module
from bayram.checkout import (
    CheckoutProvider,
    PaymentIntent,
    PaymentIntentOpener,
    PaymentIntentState,
    Product,
    PurchaseRequest,
)
from bayram.contracts import Err, Language, Ok, Result, err, ok
from bayram.errors import CheckoutPausedError, StorageError
from bayram.payme.link import PROD_CHECKOUT_URL, SANDBOX_CHECKOUT_URL, encode_payload
from bayram.payme.provider import PAYME_PROVIDER_NAME, PaymeCheckoutProvider

_MERCHANT_ID: Final[str] = "587f72c72cac0d162c722ae2"
_ACCOUNT_FIELD: Final[str] = "order_id"
_SINGLE_TIYIN: Final[int] = 700_000
_PLAN_TIYIN: Final[int] = 4_900_000
_CURRENCY: Final[str] = "UZS"
_PLAN_SONGS: Final[int] = 12
_PLAN_DAYS: Final[int] = 30
_NOW: Final[datetime] = datetime(2026, 9, 9, 9, 0, tzinfo=UTC)


@dataclass
class FakeOpener:
    """An in-memory :class:`PaymentIntentOpener` with the real one's idempotency contract.

    ``open_intent`` is insert-or-ignore on ``idempotency_key`` and returns the STORED intent
    for a replay, which is the guarantee the SQL implementation gets from a unique index. It
    matters that the fake honours it rather than minting a fresh reference each call: the
    replay test below is asserting that the PROVIDER passes the key through and rebuilds the
    URL from what comes back, and a fake that returned a new ``public_ref`` every time would
    make that test pass for the wrong reason.

    ``failure`` makes the next call return ``Err``, which is how the store reports a write it
    could not make. ``calls`` counts every invocation, including the ones that found an
    existing row, so a test can distinguish "was not called" from "was called and wrote
    nothing".
    """

    #: Deterministic references, so an assertion can name the expected URL.
    next_ref: str = "9f2c4d6a8b0e1f3c5d7a9b0c"
    failure: Exception | None = None
    calls: int = 0
    stored: dict[str, PaymentIntent] = field(default_factory=dict)
    seen: list[dict[str, object]] = field(default_factory=list)

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
    ) -> Result[PaymentIntent]:
        self.calls += 1
        self.seen.append(
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
            }
        )
        if self.failure is not None:
            return err(StorageError("the intent could not be written", cause=self.failure))
        existing = self.stored.get(idempotency_key)
        if existing is not None:
            return ok(existing)
        intent = PaymentIntent(
            public_ref=f"{self.next_ref[:-1]}{len(self.stored)}",
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
            valid_until=_NOW + timedelta(hours=12),
            settled_at=None,
            notified_at=None,
        )
        self.stored[idempotency_key] = intent
        return ok(intent)


async def _never_paused() -> bool:
    return False


async def _always_paused() -> bool:
    return True


async def _redis_is_down() -> bool:
    raise ConnectionError("connection refused")


def _provider(
    opener: PaymentIntentOpener,
    *,
    base_url: str = PROD_CHECKOUT_URL,
    return_url: str = "",
    is_sandbox: bool = False,
    language: Language = Language.UZ_LATN,
    paused: Callable[[], Awaitable[bool]] = _never_paused,
) -> PaymeCheckoutProvider:
    """A provider pointed at production with everything else defaulted sensibly for a test."""
    return PaymeCheckoutProvider(
        opener,
        merchant_id=_MERCHANT_ID,
        base_url=base_url,
        account_field=_ACCOUNT_FIELD,
        return_url=return_url,
        is_sandbox=is_sandbox,
        plan_songs=_PLAN_SONGS,
        plan_days=_PLAN_DAYS,
        language_of=lambda: language,
        paused=paused,
    )


def _request(
    *,
    product: Product = Product.SINGLE,
    amount_minor: int = _SINGLE_TIYIN,
    idempotency_key: str = "topup:8589934592:single:1",
) -> PurchaseRequest:
    return PurchaseRequest(
        # Deliberately outside the 32-bit range: a real Telegram id can be, and a helper that
        # used a small number would let an accidental narrowing pass unnoticed.
        telegram_user_id=8_589_934_592,
        product=product,
        amount_minor=amount_minor,
        currency=_CURRENCY,
        idempotency_key=idempotency_key,
    )


def _payload_of(link: str, *, base_url: str = PROD_CHECKOUT_URL) -> str:
    """The ``key=value;…`` payload back out of a built link, as Payme's parser would see it."""
    return base64.b64decode(link.removeprefix(f"{base_url}/")).decode("utf-8")


# ---------------------------------------------------------------------------
# The shape of the answer: started, not taken
# ---------------------------------------------------------------------------
async def test_a_charge_opens_exactly_one_intent_and_answers_with_a_link() -> None:
    """One row, one URL, and the purchase reports UNPAID — because it is."""
    # Arrange
    opener = FakeOpener()
    provider = _provider(opener)

    # Act
    charged = await provider.charge(_request())

    # Assert
    assert isinstance(charged, Ok)
    purchase = charged.value
    assert opener.calls == 1
    assert purchase.is_paid is False
    assert purchase.checkout_url is not None
    assert purchase.checkout_url.startswith(f"{PROD_CHECKOUT_URL}/")
    assert purchase.provider == PAYME_PROVIDER_NAME
    assert purchase.amount_minor == _SINGLE_TIYIN
    assert purchase.currency == _CURRENCY


async def test_the_reference_is_our_opaque_public_ref_and_never_the_idempotency_key() -> None:
    """The key is structured and names a customer; the ref is minted to be given away.

    ``topup:{telegram_user_id}:{scope}:{seq}`` in a URL would publish who bought what to
    anyone who can read a browser address bar, and the whole point of ``public_ref`` is that
    it can be handed to a third party.
    """
    # Arrange
    opener = FakeOpener()
    request = _request()

    # Act
    charged = await _provider(opener).charge(request)

    # Assert
    assert isinstance(charged, Ok)
    intent = opener.stored[request.idempotency_key]
    assert charged.value.reference == intent.public_ref
    assert request.idempotency_key not in (charged.value.checkout_url or "")
    assert str(request.telegram_user_id) not in (charged.value.checkout_url or "")


async def test_the_link_carries_the_public_ref_and_the_unmultiplied_amount() -> None:
    """Decode the blob and read it: ``ac.order_id`` is the ref, ``a`` is tiyin verbatim.

    The hundred-fold bug — 700 000 tiyin sent as 70 000 000 — is caught in the link module's
    own suite, and it is re-asserted here because THIS is the class that chooses which number
    to pass, and it passes the INTENT's amount rather than the request's.
    """
    # Arrange
    opener = FakeOpener()

    # Act
    charged = await _provider(opener).charge(_request())

    # Assert
    assert isinstance(charged, Ok)
    payload = _payload_of(charged.value.checkout_url or "")
    assert f"ac.{_ACCOUNT_FIELD}={charged.value.reference}" in payload
    assert f"a={_SINGLE_TIYIN}" in payload
    assert f"m={_MERCHANT_ID}" in payload


async def test_a_plan_purchase_snapshots_the_catalogue_and_a_single_song_does_not() -> None:
    """A single has neither a duration nor a song count, and the intent's CHECK says so.

    The plan numbers travel so a package change between the tap and the payment cannot
    retroactively shrink what somebody already paid for.
    """
    # Arrange
    opener = FakeOpener()
    provider = _provider(opener)

    # Act
    await provider.charge(_request(product=Product.STARTER, amount_minor=_PLAN_TIYIN))
    await provider.charge(_request(idempotency_key="topup:8589934592:single:2"))

    # Assert
    plan_call, single_call = opener.seen
    assert (plan_call["plan_songs"], plan_call["plan_days"]) == (_PLAN_SONGS, _PLAN_DAYS)
    assert (single_call["plan_songs"], single_call["plan_days"]) == (None, None)


async def test_the_intent_is_stamped_with_the_cashbox_and_the_environment_it_was_built_for() -> (
    None
):
    """A settlement quoting a different cashbox is refused, and this is where the stamp is set."""
    # Arrange
    opener = FakeOpener()
    provider = _provider(opener, is_sandbox=True, base_url=SANDBOX_CHECKOUT_URL)

    # Act
    charged = await provider.charge(_request())

    # Assert
    assert isinstance(charged, Ok)
    assert opener.seen[0]["merchant_id"] == _MERCHANT_ID
    assert opener.seen[0]["is_sandbox"] is True
    assert (charged.value.checkout_url or "").startswith(f"{SANDBOX_CHECKOUT_URL}/")


async def test_the_customers_language_is_stamped_on_the_intent_and_sent_to_the_rail() -> None:
    """The worker writes the settled-payment message in the language stored on the intent."""
    # Arrange
    opener = FakeOpener()
    provider = _provider(opener, language=Language.RU)

    # Act
    charged = await provider.charge(_request())

    # Assert
    assert isinstance(charged, Ok)
    assert opener.seen[0]["language"] == Language.RU.value
    assert "l=ru" in _payload_of(charged.value.checkout_url or "")


# ---------------------------------------------------------------------------
# Replay: the same key must produce the same page
# ---------------------------------------------------------------------------
async def test_a_replayed_idempotency_key_returns_the_same_reference_and_the_same_url() -> None:
    """Two taps, one payment page. The store deduplicates; the pure builder does the rest.

    ``opener.calls == 2`` and ``len(opener.stored) == 1`` together are the real assertion: the
    provider does NOT deduplicate, and must not — it forwards the key and the insert-or-ignore
    on the unique index is what makes the second call write nothing.
    """
    # Arrange
    opener = FakeOpener()
    provider = _provider(opener)
    request = _request()

    # Act
    first = await provider.charge(request)
    second = await provider.charge(request)

    # Assert
    assert isinstance(first, Ok)
    assert isinstance(second, Ok)
    assert first.value.reference == second.value.reference
    assert first.value.checkout_url == second.value.checkout_url
    assert opener.calls == 2
    assert len(opener.stored) == 1


# ---------------------------------------------------------------------------
# Refusals, and the ones that are not refusals
# ---------------------------------------------------------------------------
async def test_an_opener_error_becomes_an_err_and_never_an_exception() -> None:
    """A seam never raises across itself, and the store's own sentence is not re-wrapped."""
    # Arrange
    opener = FakeOpener(failure=RuntimeError("the database is unreachable"))
    provider = _provider(opener)

    # Act
    charged = await provider.charge(_request())

    # Assert
    assert isinstance(charged, Err)
    assert isinstance(charged.error, StorageError)


async def test_a_paused_rail_refuses_before_it_opens_an_intent() -> None:
    """Pausing stops NEW checkouts, so nothing is written and the customer is told plainly."""
    # Arrange
    opener = FakeOpener()
    provider = _provider(opener, paused=_always_paused)

    # Act
    charged = await provider.charge(_request())

    # Assert
    assert isinstance(charged, Err)
    assert isinstance(charged.error, CheckoutPausedError)
    assert charged.error.user_message_key == "checkout.paused"
    assert opener.calls == 0


async def test_a_pause_switch_that_raises_is_not_a_pause(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A Redis blip must never silently stop sales, and it must never be silent either.

    The direction of this default is a business decision: an unreachable Redis stopping every
    sale is a worse outage than a paused rail briefly taking one payment. Both halves are
    asserted — the sale proceeds, AND a warning is emitted — because a fallback nobody can see
    in the journal is indistinguishable from a switch that was never armed.
    """
    # Arrange
    opener = FakeOpener()
    provider = _provider(opener, paused=_redis_is_down)

    # Act
    with caplog.at_level(logging.WARNING, logger="bayram.payme.provider"):
        charged = await provider.charge(_request())

    # Assert
    assert isinstance(charged, Ok)
    assert opener.calls == 1
    assert any(record.levelno == logging.WARNING for record in caplog.records)


# ---------------------------------------------------------------------------
# The claim most likely to rot
# ---------------------------------------------------------------------------
def test_the_payme_provider_holds_no_http_client() -> None:
    """ "Contacts nothing" is the most surprising true claim here, so it is asserted.

    Payme has no create-payment-link API for the standard checkout: the link is CONSTRUCTED
    and the customer's browser is what first reaches them. The failure this guards is a later
    contributor reaching for ``httpx`` inside ``charge`` to "check whether the payment went
    through" — which would give this process an outbound dependency on the rail, a timeout to
    tune, and a second, quieter answer to a question ``PerformTransaction`` already answers.

    Asserted by module NAME rather than against imported ``httpx`` types, so it also catches
    an ``aiohttp`` session, a ``requests`` adapter, or any other client somebody reaches for.
    """
    # Arrange
    provider = _provider(FakeOpener())

    # Act
    modules = {type(value).__module__.split(".")[0] for value in vars(provider).values()}

    # Assert
    assert modules.isdisjoint({"httpx", "aiohttp", "requests", "urllib3"})


def test_the_provider_satisfies_the_checkout_protocol_without_inheriting_it() -> None:
    """Structural, like ``StubCheckoutProvider`` — so a Protocol change is a type error here."""
    # Arrange / Act / Assert
    assert isinstance(_provider(FakeOpener()), CheckoutProvider)
    assert CheckoutProvider not in PaymeCheckoutProvider.__mro__
    assert PaymeCheckoutProvider.name == PAYME_PROVIDER_NAME


def test_the_link_is_never_written_to_the_journal() -> None:
    """A payable URL does not belong in a log line; ``public_ref`` ties the row to the intent.

    Asserted against the module's source rather than against emitted records, because the
    property is "no call site passes the link", and a behavioural test would only cover the
    paths a test happens to walk.
    """
    # Arrange
    assert provider_module.__file__ is not None
    source = Path(provider_module.__file__).read_text(encoding="utf-8")

    # Act
    logged_link = '"checkout_url":' in source or '"link":' in source

    # Assert
    assert not logged_link


def test_an_encoded_blob_is_a_pure_function_of_the_reference() -> None:
    """The stability the replay guarantee rests on, stated where a reader will look for it."""
    # Arrange
    payload = f"m={_MERCHANT_ID};ac.{_ACCOUNT_FIELD}=abc;a=1;l=uz;cr=860"

    # Act / Assert
    assert encode_payload(payload) == encode_payload(payload)
