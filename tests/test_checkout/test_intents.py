"""The redirect rail's vocabulary: five states, one frozen view, one deliberately tiny port.

Three properties are pinned here, and each of them is pinned because losing it is silent.

* **The state set is closed at five.** ``awaiting`` is the member a well-meaning simplifier
  removes, because from the outside it looks like "pending, but we are quite sure". It is not:
  it is the mutual exclusion that stops a second rail-side transaction being opened against an
  intent a card is already being charged for, and it is what puts an in-flight payment outside
  the set a merchant-side expiry sweep can even see. A test that only counted members would
  pass while somebody renamed the value under it, so the VALUES are asserted too — they are
  persisted in a column and read by a different process, so they are wire, not vocabulary.
* **:class:`PaymentIntent` is frozen and slotted.** It is a view of a database row handed
  across a package boundary; a caller that could edit the ``state`` on its copy would be
  reasoning about a payment that does not exist, and would find out by telling a customer the
  wrong thing rather than by raising.
* **:class:`PaymentIntentOpener` accepts a correctly-shaped object.** ``runtime_checkable``
  verifies member PRESENCE only, so this asserts the composition root will not blow up; the
  ``mypy --strict`` pass over ``tests`` is what actually holds the signature, which is why the
  fake below is bound to a variable ANNOTATED as the protocol. Deleting that annotation would
  quietly turn this file into a presence check.

The port's narrowness is asserted as a property in its own right. "It can open an intent and
nothing else" is a security claim — the bot process must not be able to settle a payment — and
a claim like that decays by accretion, one convenient method at a time.
"""

from __future__ import annotations

import dataclasses
from datetime import UTC, datetime
from uuid import UUID

import pytest

from bayram.checkout import PaymentIntent, PaymentIntentOpener, PaymentIntentState, Product
from bayram.contracts import Result, is_ok, ok

#: A fixed instant. Nothing here reads wall time, so nothing here can go red at midnight.
_NOW = datetime(2026, 9, 9, 12, 0, tzinfo=UTC)


def _intent(*, state: PaymentIntentState = PaymentIntentState.PENDING) -> PaymentIntent:
    """One pending single-song intent, priced the way the shipped settings price it."""
    return PaymentIntent(
        public_ref="9f2c4d6a8b0e1f3c5d7a9b0c",
        idempotency_key="topup:8589934592:sess:0",
        telegram_user_id=8_589_934_592,
        product=Product.SINGLE,
        amount_minor=700_000,
        currency="UZS",
        language="uz_latn",
        merchant_id="000000000000000000000000",
        is_sandbox=True,
        plan_songs=None,
        plan_days=None,
        state=state,
        valid_until=_NOW,
        settled_at=None,
        notified_at=None,
    )


class _RecordingOpener:
    """A correctly-shaped opener that writes nothing and remembers what it was asked.

    Structurally satisfies :class:`PaymentIntentOpener` and does NOT inherit from it, matching
    ``StubCheckoutProvider`` against ``CheckoutProvider``: inheritance would make a protocol
    change a runtime surprise, whereas structural conformance makes it a type error here.
    """

    def __init__(self) -> None:
        self.keys: list[str] = []

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
        # Added 2026-09-16 to match the protocol, which grew it with the resume path. The
        # drift was invisible until `mypy --strict` ran over tests/ for the first time in CI:
        # `runtime_checkable` checks member PRESENCE only, so the `isinstance` assertion
        # below kept passing against a fake whose signature no longer matched (checkout.py's
        # own docstring says this is what mypy is for).
        resume_order_id: UUID | None = None,
    ) -> Result[PaymentIntent]:
        self.keys.append(idempotency_key)
        return ok(_intent())


# ---------------------------------------------------------------------------
# The state machine's vocabulary
# ---------------------------------------------------------------------------
def test_the_intent_state_set_is_exactly_five_members_with_the_persisted_values() -> None:
    # Arrange / Act — the members as the database column and a second process see them.
    members = {state.name: state.value for state in PaymentIntentState}

    # Assert — a sixth state is a schema change and an enum-length change, never a quiet edit.
    assert members == {
        "PENDING": "pending",
        "AWAITING": "awaiting",
        "PAID": "paid",
        "CANCELLED": "cancelled",
        "EXPIRED": "expired",
    }


def test_the_states_are_plain_strings_so_a_column_can_hold_them() -> None:
    # Arrange / Act / Assert — ``StrEnum`` and not ``Enum``: the value is written to a
    # ``VARCHAR`` and compared against a literal in SQL, so it has to BE the string. The
    # interpolation is the load-bearing half — a plain ``Enum`` renders as
    # ``PaymentIntentState.AWAITING`` in an f-string, which is the shape that reaches a log
    # line, a query parameter or a URL before anybody notices.
    assert isinstance(PaymentIntentState.AWAITING, str)
    assert f"{PaymentIntentState.AWAITING}" == "awaiting"


# ---------------------------------------------------------------------------
# The frozen view
# ---------------------------------------------------------------------------
def test_a_payment_intent_cannot_be_mutated_after_it_is_built() -> None:
    # Arrange
    intent = _intent()

    # Act / Assert — a settled intent that a caller could flip back to pending is a receipt
    # that can be un-written; the boundary hands out values, not handles.
    with pytest.raises(dataclasses.FrozenInstanceError):
        intent.state = PaymentIntentState.PAID  # type: ignore[misc]


def test_a_payment_intent_carries_slots_and_therefore_no_instance_dictionary() -> None:
    # Arrange
    intent = _intent()

    # Assert — the half of the freeze ``FrozenInstanceError`` does not cover. Without slots a
    # typo'd field name is a silently-created attribute nobody reads, and on a value that
    # answers "was this paid?" a field nobody reads is the worst possible shape for a mistake
    # to take. Asserted structurally rather than by attempting an assignment, because a frozen
    # slotted dataclass answers an unknown name out of its generated ``__setattr__`` with a
    # refusal whose exact type is not worth pinning.
    assert not hasattr(intent, "__dict__")
    assert set(PaymentIntent.__slots__) == {f.name for f in dataclasses.fields(PaymentIntent)}


def test_the_intent_carries_both_identifiers_because_only_one_of_them_may_be_published() -> None:
    # Arrange
    intent = _intent()

    # Assert — ``public_ref`` is what goes into a URL a stranger can read; the idempotency key
    # is derived from a Telegram user id and must never leave this system. Carrying both on one
    # value is what lets a caller hand out the first while settling under the second.
    assert intent.public_ref != intent.idempotency_key
    assert str(intent.telegram_user_id) in intent.idempotency_key
    assert str(intent.telegram_user_id) not in intent.public_ref


def test_an_erased_intent_keeps_its_reference_and_its_money_and_loses_only_the_person() -> None:
    # Arrange — what ``/forget`` leaves behind: anonymised, never deleted, because a rail that
    # can still see its own transaction must still get an answer about it.
    erased = dataclasses.replace(_intent(), telegram_user_id=None)

    # Assert
    assert erased.telegram_user_id is None
    assert erased.public_ref and erased.amount_minor == 700_000 and erased.currency == "UZS"


# ---------------------------------------------------------------------------
# The port
# ---------------------------------------------------------------------------
def test_a_correctly_shaped_object_satisfies_the_intent_opener_port() -> None:
    # Arrange — ANNOTATED as the protocol on purpose: this line is what ``mypy --strict``
    # checks the signature against, and the ``isinstance`` below only checks presence.
    opener: PaymentIntentOpener = _RecordingOpener()

    # Act / Assert
    assert isinstance(opener, PaymentIntentOpener)


def test_an_object_without_the_method_does_not_satisfy_the_port() -> None:
    # Arrange / Act / Assert — the wiring assertion has to be able to fail, or it is decoration.
    assert not isinstance(object(), PaymentIntentOpener)


def test_the_port_exposes_exactly_one_method_and_it_is_the_additive_one() -> None:
    # Arrange / Act — the protocol's own declared members, ignoring the machinery ``Protocol``
    # adds to every subclass.
    declared = {
        name
        for name in vars(PaymentIntentOpener)
        if not name.startswith("_") and callable(vars(PaymentIntentOpener)[name])
    }

    # Assert — **this is a security property, not a style one.** Opening an intent grants
    # nothing and costs nothing to abandon. Settling one writes a receipt and a credit;
    # cancelling one releases a hold. The bot process cannot do either, because the methods are
    # absent from the object it is handed — not guarded on it, absent. A future edit that adds
    # ``settle`` "just for the admin CLI" must fail here and be made to add a second port.
    assert declared == {"open_intent"}


async def test_the_opener_returns_a_result_and_carries_the_key_the_bot_minted() -> None:
    # Arrange — two names for one object: the annotated one is what mypy checks the call
    # against, the concrete one is what the assertions can look inside.
    recorder = _RecordingOpener()
    opener: PaymentIntentOpener = recorder

    # Act
    opened = await opener.open_intent(
        telegram_user_id=8_589_934_592,
        product=Product.SINGLE,
        amount_minor=700_000,
        currency="UZS",
        idempotency_key="topup:8589934592:sess:0",
        language="uz_latn",
        merchant_id="000000000000000000000000",
        is_sandbox=True,
    )

    # Assert — the plan snapshot is optional because a one-off product has no duration and no
    # song count, and the key crosses the seam unchanged because it is the string the receipt
    # and the credit grant will both land on, in a different process, minutes later.
    assert is_ok(opened)
    assert opened.value.product is Product.SINGLE
    assert opened.value.plan_songs is None and opened.value.plan_days is None
    assert recorder.keys == ["topup:8589934592:sess:0"]
