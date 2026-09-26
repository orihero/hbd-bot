"""The two facts the Rail Board computes on the server, asserted without a server.

:func:`~bayram.admin.schemas.billing.settlement_verdict` and
:func:`~bayram.admin.schemas.billing.build_lifeline` are pure functions over frozen view models,
and that is deliberate: they are the only logic in this section that turns five tables into a
sentence an operator acts on, so they have to be assertable against fixtures rather than through
a router, a session and a seeded database. Everything here runs with none of the three.

Three of the assertions below are regressions rather than coverage, and each is written out
where it lives:

* **all-zero is ``never_settled`` and never ``balanced``.** That is the state this deployment
  is in today, and a zero-equals-zero green tick on a rail that has never taken a payment is
  the worst lie the settlement card can tell.
* **a plan sale's credit step is ``not_applicable``, never ``missing``.** A plan mints songs as
  they are used and grants nothing at purchase, so the naive renderer reports every healthy
  plan sale as a broken chain.
* **an erased buyer is ``not_applicable`` with a reason, never ``missing`` and never a fault.**
  ``db/payme.py::_settle`` claims the intent and writes no sale when ``/forget`` has run: the
  money moved and there is nobody left to grant to, which is a state and not a discrepancy.

The last two tests are structural rather than behavioural: they introspect ``model_fields`` for
two field names that must never exist on this surface. There is no behaviour to catch a
re-added ``idempotencyKey`` — it would simply start appearing in responses, in DOM nodes and in
screenshots — so the absence is asserted directly.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Final
from uuid import UUID

import pytest

from bayram.admin.schemas.billing import (
    IntentDetailView,
    IntentDossierView,
    IntentListItemView,
    LifelineNote,
    LifelineStatus,
    LifelineStep,
    LifelineStepView,
    NotifyRefusal,
    SettlementVerdict,
    build_lifeline,
    notify_refusal,
    settle_command,
    settle_source_of,
    settlement_verdict,
    to_chain_stop_view,
    to_intent_detail_view,
)
from bayram.db.admin.payment_intents import SettleSource
from bayram.db.admin.views import (
    IntentDetail,
    PaymentGrant,
    PaymentReceipt,
    RailTransaction,
    SettlementSnapshot,
)
from bayram.db.enums import IntentProduct, PaymentIntentState

INTENT_ID: Final[UUID] = UUID("3f2b9c1e-0a5d-4f61-9c2a-7b18d4e6f0a3")
#: 24 lowercase hex, exactly as ``secrets.token_hex(12)`` mints them.
PUBLIC_REF: Final[str] = "9f13c0a72b4e8d5610fa37cc"
#: Shaped as ``bot/handlers/checkout.py`` mints it — Telegram id and all, which is precisely
#: why the two structural tests at the bottom of this file exist. It is NOT a field on
#: :class:`~bayram.db.admin.views.IntentDetail` and never was: the dossier handler fetches it
#: through ``payment_intents.idempotency_key_for``, hands it to three queries and drops it, so
#: it cannot ride into a ``repr``, a log line or an error context on the way past. This
#: constant exists here only to be asserted ABSENT.
IDEMPOTENCY_KEY: Final[str] = "topup:770000123:kit:1"
TELEGRAM_ID: Final[int] = 770_000_123

OPENED_AT: Final[datetime] = datetime(2026, 9, 10, 9, 0, tzinfo=UTC)
RAIL_AT: Final[datetime] = OPENED_AT + timedelta(minutes=2)
PERFORMED_AT: Final[datetime] = OPENED_AT + timedelta(minutes=3)
SETTLED_AT: Final[datetime] = OPENED_AT + timedelta(minutes=3)
TOLD_AT: Final[datetime] = OPENED_AT + timedelta(minutes=4)


def intent(
    *,
    state: str = PaymentIntentState.PENDING.value,
    product: str = IntentProduct.SINGLE.value,
    telegram_user_id: int | None = TELEGRAM_ID,
    settled_at: datetime | None = None,
    settle_note: str | None = None,
    notified_at: datetime | None = None,
    has_receipt: bool = False,
    has_grant: bool = False,
) -> IntentDetail:
    """One intent, with only the fields any test here varies exposed as keywords.

    Explicit keywords rather than a ``**overrides`` dict, because ``mypy --strict`` runs over
    ``tests/`` too and a dict splatted into a frozen dataclass types as ``object``.
    """
    return IntentDetail(
        intent_id=INTENT_ID,
        public_ref=PUBLIC_REF,
        created_at=OPENED_AT,
        valid_until=OPENED_AT + timedelta(minutes=30),
        state=state,
        product=product,
        plan_songs=5 if product == IntentProduct.STARTER.value else None,
        plan_days=30 if product == IntentProduct.STARTER.value else None,
        amount_minor=1_200_000,
        currency="UZS",
        provider="payme",
        merchant_id="placeholder",
        is_sandbox=True,
        telegram_user_id=telegram_user_id,
        transaction_count=0,
        latest_transaction_state=None,
        latest_perform_time=None,
        has_receipt=has_receipt,
        has_grant=has_grant,
        settled_at=settled_at,
        settle_note=settle_note,
        notified_at=notified_at,
    )


def performed_transaction() -> RailTransaction:
    return RailTransaction(
        payme_transaction_id="65f0a1b2c3d4e5f601234567",
        state="performed",
        payme_time=RAIL_AT,
        create_time=RAIL_AT,
        perform_time=PERFORMED_AT,
        cancel_time=None,
        cancel_reason=None,
    )


def open_transaction() -> RailTransaction:
    """A transaction the rail opened and has not come back about. The ``awaiting`` hold."""
    return RailTransaction(
        payme_transaction_id="65f0a1b2c3d4e5f60123abcd",
        state="created",
        payme_time=RAIL_AT,
        create_time=RAIL_AT,
        perform_time=None,
        cancel_time=None,
        cancel_reason=None,
    )


def single_receipt() -> PaymentReceipt:
    return PaymentReceipt(
        source="topup_purchases",
        amount_minor=1_200_000,
        currency="UZS",
        provider="payme",
        reference="65f0a1b2c3d4e5f601234567",
        credits_granted=1,
        songs_included=None,
        songs_used=None,
        plan_ends_at=None,
        created_at=SETTLED_AT,
    )


def plan_receipt() -> PaymentReceipt:
    return PaymentReceipt(
        source="plan_purchases",
        amount_minor=3_500_000,
        currency="UZS",
        provider="payme",
        reference="65f0a1b2c3d4e5f601234567",
        credits_granted=None,
        songs_included=5,
        songs_used=2,
        plan_ends_at=SETTLED_AT + timedelta(days=30),
        created_at=SETTLED_AT,
    )


def grant() -> PaymentGrant:
    return PaymentGrant(
        kind="grant", delta=1, reason="topup_purchase", actor="checkout", created_at=SETTLED_AT
    )


def steps_by_key(steps: list[LifelineStepView]) -> dict[LifelineStep, LifelineStepView]:
    """The six steps as a mapping, so an assertion names the step rather than an index."""
    return {step.key: step for step in steps}


# ---------------------------------------------------------------------------
# The settlement identity
# ---------------------------------------------------------------------------
def snapshot(
    *, performed: int = 0, operator: int = 0, receipts: int = 0, grants: int = 0
) -> SettlementSnapshot:
    return SettlementSnapshot(
        transactions_performed=performed,
        receipts_written=receipts,
        grants_written=grants,
        operator_settlements=operator,
    )


def test_an_untouched_rail_is_never_settled_and_not_balanced() -> None:
    """THE assertion of this file. Four zeros on a rail that has never settled anything must
    not render as a pass: it is indistinguishable from a healthy quiet week, and it is the
    state of this deployment right now."""
    # Arrange / Act
    verdict = settlement_verdict(snapshot(), has_recorded_settlement=False)

    # Assert
    assert verdict is SettlementVerdict.NEVER_SETTLED
    # And the SLUG, which is the half the console branches on: a rename here would be a
    # silent SCHEMA_DRIFT banner over the whole card rather than a failing import.
    assert verdict.value == "never_settled"


def test_four_zeros_on_a_rail_that_has_settled_before_are_balanced() -> None:
    # Arrange / Act — the same four numbers, and the probe is what makes them readable: a
    # window with nothing in it on a rail that HAS taken payments really is balanced.
    verdict = settlement_verdict(snapshot(), has_recorded_settlement=True)

    # Assert
    assert verdict is SettlementVerdict.BALANCED


def test_the_identity_counts_hand_settlements_as_settlements() -> None:
    # Arrange — one rail settlement and one press of the recovery button. The two-way equality
    # ``performed == receipts`` would call this a defect, which is how an alert gets muted.
    verdict = settlement_verdict(
        snapshot(performed=1, operator=1, receipts=2, grants=2), has_recorded_settlement=True
    )

    # Assert
    assert verdict is SettlementVerdict.BALANCED


def test_a_plan_sale_grants_nothing_and_that_is_still_balanced() -> None:
    # Arrange — grants are the single-song SUBSET of receipts, so ``grants < receipts`` is the
    # ordinary state of a deployment that sells plans.
    verdict = settlement_verdict(
        snapshot(performed=2, receipts=2, grants=1), has_recorded_settlement=True
    )

    # Assert
    assert verdict is SettlementVerdict.BALANCED


def test_more_grants_than_receipts_is_the_one_impossible_state() -> None:
    # Arrange / Act
    verdict = settlement_verdict(
        snapshot(performed=1, receipts=1, grants=2), has_recorded_settlement=True
    )

    # Assert
    assert verdict is SettlementVerdict.GRANTS_OVER_RECEIPTS


def test_the_impossible_state_wins_over_an_arithmetic_mismatch() -> None:
    """Precedence, asserted rather than implied: on a database showing both, the impossible
    fact is the one to investigate and the arithmetic one is probably its consequence."""
    # Arrange — ``performed + operator`` (5) also disagrees with ``receipts`` (1).
    verdict = settlement_verdict(
        snapshot(performed=5, receipts=1, grants=2), has_recorded_settlement=True
    )

    # Assert
    assert verdict is SettlementVerdict.GRANTS_OVER_RECEIPTS


def test_fewer_receipts_than_settlements_reads_as_receipts_short() -> None:
    # Arrange — the erased-buyer case: money moved, no sale was written.
    verdict = settlement_verdict(
        snapshot(performed=3, receipts=2, grants=2), has_recorded_settlement=True
    )

    # Assert
    assert verdict is SettlementVerdict.RECEIPTS_SHORT


def test_more_receipts_than_settlements_reads_as_receipts_over() -> None:
    # Arrange — usually the window's edge: a sale settled just inside it against a transaction
    # performed just outside.
    verdict = settlement_verdict(
        snapshot(performed=1, receipts=2, grants=1), has_recorded_settlement=True
    )

    # Assert
    assert verdict is SettlementVerdict.RECEIPTS_OVER


# ---------------------------------------------------------------------------
# The lifeline
# ---------------------------------------------------------------------------
def test_a_pending_intent_nobody_has_paid_shows_one_done_step_and_five_waiting() -> None:
    # Arrange — a link was handed out and Payme has never called about it.
    lifeline = build_lifeline(intent(), transactions=(), receipt=None, grants=())

    # Act
    steps = steps_by_key(lifeline.steps)

    # Assert — the note sits on the step that actually stopped; the ones merely waiting on it
    # carry none, because four identical sentences down a six-row list is noise.
    assert [step.key for step in lifeline.steps] == list(LifelineStep)
    assert steps[LifelineStep.OPENED].status is LifelineStatus.DONE
    assert steps[LifelineStep.OPENED].at == OPENED_AT
    assert steps[LifelineStep.RAIL_TRANSACTION].status is LifelineStatus.PENDING
    assert steps[LifelineStep.RAIL_TRANSACTION].note_code is LifelineNote.NEVER_OPENED
    assert steps[LifelineStep.PERFORMED].status is LifelineStatus.PENDING
    assert steps[LifelineStep.PERFORMED].note_code is None
    assert steps[LifelineStep.RECEIPT].status is LifelineStatus.PENDING
    assert steps[LifelineStep.CREDIT_GRANTED].status is LifelineStatus.PENDING
    assert steps[LifelineStep.CUSTOMER_TOLD].status is LifelineStatus.PENDING


def test_a_held_intent_is_waiting_on_the_rail_rather_than_late() -> None:
    # Arrange — a transaction is open and Payme has not come back. Our clock and theirs are
    # not the same clock, so this is waiting.
    lifeline = build_lifeline(
        intent(state=PaymentIntentState.AWAITING.value),
        transactions=(open_transaction(),),
        receipt=None,
        grants=(),
    )

    # Act
    steps = steps_by_key(lifeline.steps)

    # Assert
    assert steps[LifelineStep.RAIL_TRANSACTION].status is LifelineStatus.DONE
    assert steps[LifelineStep.RAIL_TRANSACTION].at == RAIL_AT
    assert steps[LifelineStep.PERFORMED].status is LifelineStatus.PENDING
    assert steps[LifelineStep.PERFORMED].note_code is LifelineNote.AWAITING_RAIL


def test_a_fully_settled_single_song_sale_is_six_done_steps() -> None:
    # Arrange — the happy path, end to end.
    lifeline = build_lifeline(
        intent(
            state=PaymentIntentState.PAID.value,
            settled_at=SETTLED_AT,
            settle_note="payme",
            notified_at=TOLD_AT,
            has_receipt=True,
            has_grant=True,
        ),
        transactions=(performed_transaction(),),
        receipt=single_receipt(),
        grants=(grant(),),
    )

    # Act
    steps = steps_by_key(lifeline.steps)

    # Assert
    assert all(step.status is LifelineStatus.DONE for step in lifeline.steps)
    assert steps[LifelineStep.PERFORMED].at == PERFORMED_AT
    assert steps[LifelineStep.CUSTOMER_TOLD].at == TOLD_AT
    assert steps[LifelineStep.CUSTOMER_TOLD].note_code is LifelineNote.ALREADY_TOLD


def test_a_paid_plan_grants_no_credit_and_that_is_not_applicable() -> None:
    """The regression this function's four-state design exists for: a plan sale writes a
    receipt and no ``credit_ledger`` row at all, so a three-state renderer reports every
    healthy plan sale as a broken chain."""
    # Arrange
    lifeline = build_lifeline(
        intent(
            state=PaymentIntentState.PAID.value,
            product=IntentProduct.STARTER.value,
            settled_at=SETTLED_AT,
            settle_note="payme",
            notified_at=TOLD_AT,
            has_receipt=True,
        ),
        transactions=(performed_transaction(),),
        receipt=plan_receipt(),
        grants=(),
    )

    # Act
    step = steps_by_key(lifeline.steps)[LifelineStep.CREDIT_GRANTED]

    # Assert
    assert step.status is LifelineStatus.NOT_APPLICABLE
    # The wire slugs, for the reason the settlement verdict's are asserted: the console
    # renders a sentence per note code and a rename would silently render nothing.
    assert (step.status.value, step.note_code) == (
        "not_applicable",
        LifelineNote.PLAN_GRANTS_NOTHING,
    )


def test_an_erased_buyer_is_a_state_and_never_a_discrepancy() -> None:
    """``/forget`` ran between paying and settling: the money moved, ``_settle`` claimed the
    intent and wrote no sale, and there is nobody left to grant to or tell. Every one of the
    three downstream steps must read as not-applicable with its OWN reason — never missing,
    never a fault, and never a blank the operator reads as fraud."""
    # Arrange
    lifeline = build_lifeline(
        intent(
            state=PaymentIntentState.PAID.value,
            telegram_user_id=None,
            settled_at=SETTLED_AT,
            settle_note="payme",
        ),
        transactions=(performed_transaction(),),
        receipt=None,
        grants=(),
    )

    # Act
    steps = steps_by_key(lifeline.steps)

    # Assert
    for key in (LifelineStep.RECEIPT, LifelineStep.CREDIT_GRANTED, LifelineStep.CUSTOMER_TOLD):
        assert steps[key].status is LifelineStatus.NOT_APPLICABLE, key
        assert steps[key].note_code is LifelineNote.BUYER_ERASED, key
    # The money half of the row is untouched: the two steps above it still happened.
    assert steps[LifelineStep.PERFORMED].status is LifelineStatus.DONE


def test_a_settled_payment_nobody_announced_is_missing_with_a_remedy() -> None:
    # Arrange — the ``paidNeverAnnounced`` population, one row of it.
    lifeline = build_lifeline(
        intent(
            state=PaymentIntentState.PAID.value,
            settled_at=SETTLED_AT,
            settle_note="payme",
            has_receipt=True,
            has_grant=True,
        ),
        transactions=(performed_transaction(),),
        receipt=single_receipt(),
        grants=(grant(),),
    )

    # Act
    step = steps_by_key(lifeline.steps)[LifelineStep.CUSTOMER_TOLD]

    # Assert — MISSING and not NOT_APPLICABLE: this one asks for work, and the work is the
    # notify button beside it.
    assert step.status is LifelineStatus.MISSING
    assert step.at is None


def test_a_hand_settled_payment_never_had_a_rail_transaction() -> None:
    # Arrange — ``settle`` claims an intent an operator saw charged in the Payme cabinet, so
    # there is no transaction of ours and none is missing.
    lifeline = build_lifeline(
        intent(
            state=PaymentIntentState.PAID.value,
            settled_at=SETTLED_AT,
            settle_note="operator:INC-441",
            notified_at=TOLD_AT,
            has_receipt=True,
        ),
        transactions=(),
        receipt=single_receipt(),
        grants=(grant(),),
    )

    # Act
    steps = steps_by_key(lifeline.steps)

    # Assert
    assert steps[LifelineStep.RAIL_TRANSACTION].status is LifelineStatus.NOT_APPLICABLE
    assert steps[LifelineStep.RAIL_TRANSACTION].note_code is LifelineNote.NEVER_OPENED
    assert steps[LifelineStep.PERFORMED].status is LifelineStatus.NOT_APPLICABLE
    assert steps[LifelineStep.PERFORMED].note_code is LifelineNote.NEVER_OPENED


def test_a_rail_settled_payment_with_no_transaction_row_reads_as_purged() -> None:
    """There are no foreign keys anywhere on the rail's three tables and their retention
    clocks differ, so a paid intent can outlive the evidence beneath it. That is a row that is
    GONE, not an event that never happened, and the two must not render alike."""
    # Arrange
    lifeline = build_lifeline(
        intent(
            state=PaymentIntentState.PAID.value,
            settled_at=SETTLED_AT,
            settle_note="payme",
            notified_at=TOLD_AT,
            has_receipt=True,
        ),
        transactions=(),
        receipt=single_receipt(),
        grants=(grant(),),
    )

    # Act
    step = steps_by_key(lifeline.steps)[LifelineStep.RAIL_TRANSACTION]

    # Assert
    assert step.status is LifelineStatus.MISSING
    assert step.note_code is LifelineNote.PURGED


def test_an_expired_intent_stops_at_not_settled() -> None:
    # Arrange — the customer never paid, so nothing downstream was ever going to happen.
    lifeline = build_lifeline(
        intent(state=PaymentIntentState.EXPIRED.value), transactions=(), receipt=None, grants=()
    )

    # Act
    steps = steps_by_key(lifeline.steps)

    # Assert
    assert steps[LifelineStep.PERFORMED].note_code is LifelineNote.NOT_SETTLED
    for key in (LifelineStep.RECEIPT, LifelineStep.CREDIT_GRANTED, LifelineStep.CUSTOMER_TOLD):
        assert steps[key].status is LifelineStatus.NOT_APPLICABLE, key


def test_every_note_the_server_can_send_is_reachable_from_some_fixture() -> None:
    """The closed vocabulary has no dead members.

    A slug nothing can produce is a locale key nobody writes and a branch nobody reviews; the
    console's own test asserts the other half — that every slug the server can send has a
    rendered string in ``en``.
    """
    # Arrange — every lifeline this file builds, in one place.
    lifelines = [
        build_lifeline(intent(), transactions=(), receipt=None, grants=()),
        build_lifeline(
            intent(state=PaymentIntentState.AWAITING.value),
            transactions=(open_transaction(),),
            receipt=None,
            grants=(),
        ),
        build_lifeline(
            intent(
                state=PaymentIntentState.PAID.value,
                product=IntentProduct.STARTER.value,
                settled_at=SETTLED_AT,
                settle_note="payme",
                notified_at=TOLD_AT,
            ),
            transactions=(performed_transaction(),),
            receipt=plan_receipt(),
            grants=(),
        ),
        build_lifeline(
            intent(
                state=PaymentIntentState.PAID.value,
                telegram_user_id=None,
                settled_at=SETTLED_AT,
                settle_note="payme",
            ),
            transactions=(performed_transaction(),),
            receipt=None,
            grants=(),
        ),
        build_lifeline(
            intent(state=PaymentIntentState.EXPIRED.value),
            transactions=(),
            receipt=None,
            grants=(),
        ),
        build_lifeline(
            intent(state=PaymentIntentState.PAID.value, settled_at=SETTLED_AT, settle_note="payme"),
            transactions=(),
            receipt=single_receipt(),
            grants=(grant(),),
        ),
    ]

    # Act
    seen = {
        step.note_code
        for lifeline in lifelines
        for step in lifeline.steps
        if step.note_code is not None
    }

    # Assert
    assert seen == set(LifelineNote)


# ---------------------------------------------------------------------------
# The smaller projections
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    ("note", "expected"),
    [
        (None, None),
        ("payme", SettleSource.RAIL),
        ("operator:INC-441", SettleSource.OPERATOR),
        # A future rail whose note is neither classifies as ``rail``, which is the honest
        # direction: anything that is not a hand-settlement was written by the settlement path.
        ("some-future-rail", SettleSource.RAIL),
    ],
)
def test_who_moved_the_money_is_decided_by_the_operator_prefix_alone(
    note: str | None, expected: SettleSource | None
) -> None:
    # Arrange / Act / Assert
    assert settle_source_of(note) is expected


@pytest.mark.parametrize(
    ("state", "telegram_user_id", "notified_at", "expected"),
    [
        (PaymentIntentState.PENDING.value, TELEGRAM_ID, None, NotifyRefusal.NOT_PAID),
        (PaymentIntentState.PAID.value, None, None, NotifyRefusal.BUYER_ERASED),
        (PaymentIntentState.PAID.value, TELEGRAM_ID, TOLD_AT, NotifyRefusal.ALREADY_NOTIFIED),
        (PaymentIntentState.PAID.value, TELEGRAM_ID, None, None),
    ],
)
def test_the_three_notify_refusals_are_checked_in_the_cli_s_order(
    state: str,
    telegram_user_id: int | None,
    notified_at: datetime | None,
    expected: NotifyRefusal | None,
) -> None:
    # Arrange — an unpaid intent has nothing to announce whatever else is true of it, so the
    # state is checked first; an erased buyer has nobody to announce it to; the stamp is last
    # because it is the only one of the three that means "this already worked".
    detail = intent(state=state, telegram_user_id=telegram_user_id, notified_at=notified_at)

    # Act / Assert
    assert notify_refusal(detail) is expected


def test_the_chain_stops_at_the_grant_for_a_single_song() -> None:
    # Arrange — whether the purchased credit became a song is unanswerable by construction:
    # ``credit_accounts.balance`` is a fungible scalar with no lot structure.
    view = to_chain_stop_view(intent(), receipt=single_receipt())

    # Assert — the panel says so rather than leaving a blank that reads as broken.
    assert view.kind.value == "single_song"
    assert (view.songs_used, view.songs_included, view.plan_ends_at) == (None, None, None)


def test_the_chain_continues_past_the_receipt_for_a_plan() -> None:
    # Arrange — ``plan_purchases.songs_used`` is the ONE place fulfilment stays answerable.
    view = to_chain_stop_view(intent(product=IntentProduct.STARTER.value), receipt=plan_receipt())

    # Assert
    assert view.kind.value == "plan"
    assert (view.songs_used, view.songs_included) == (2, 5)


def test_the_settle_command_carries_the_public_reference_and_nothing_else() -> None:
    """The dossier renders this as selectable text with no submit path, so the one property
    that matters is that an operator pasting it into a ticket pastes no customer data."""
    # Arrange / Act
    rendered = settle_command(PUBLIC_REF)

    # Assert
    assert rendered == f"python -m bayram.payme.cli settle --ref {PUBLIC_REF} --note '{PUBLIC_REF}'"
    assert str(TELEGRAM_ID) not in rendered
    assert IDEMPOTENCY_KEY not in rendered


# ---------------------------------------------------------------------------
# The two absences, asserted directly because no behaviour would catch them
# ---------------------------------------------------------------------------
def test_no_billing_response_model_carries_an_idempotency_key() -> None:
    """``topup:{telegram_user_id}:{scope}:{seq}`` contains a customer's Telegram id, which is
    the precise leak ``public_ref`` was minted to prevent. Shipping it behind a warning tooltip
    was the rejected alternative: a tooltip does not stop a value reaching a DOM node, a
    screenshot and a support ticket."""
    # Arrange — the two models a dossier renders, and the page row behind them.
    models = (IntentDetailView, IntentListItemView, IntentDossierView)

    # Act / Assert — by field NAME, so a re-add under any alias still fails here.
    for model in models:
        offenders = [name for name in model.model_fields if "idempotency" in name.lower()]
        assert offenders == [], (model.__name__, offenders)


def test_no_billing_response_model_carries_a_plaintext_telegram_id() -> None:
    """A payer's identity is a ``POST /api/reveal`` question, with a step-up, a budget and its
    own audit row. A billing field that answered it would be a second reveal path with none of
    the three — so the surface carries the MASK plus an explicit ``isBuyerErased`` and has no
    plaintext field for a serializer to fill by accident."""
    # Arrange
    models = (IntentDetailView, IntentListItemView)

    # Act / Assert
    for model in models:
        assert "telegram_user_id" not in model.model_fields, model.__name__
        assert "telegram_user_id_masked" in model.model_fields, model.__name__
        assert "is_buyer_erased" in model.model_fields, model.__name__


def test_an_erased_buyer_projects_to_a_null_mask_and_an_explicit_flag() -> None:
    # Arrange — ``null`` (erased) and ``"•••"`` (masked) are two different facts, and
    # collapsing them is the bug the pair of fields exists to prevent.
    erased = to_intent_detail_view(intent(telegram_user_id=None))
    known = to_intent_detail_view(intent())

    # Assert
    assert (erased.telegram_user_id_masked, erased.is_buyer_erased) == (None, True)
    assert known.is_buyer_erased is False
    assert known.telegram_user_id_masked is not None
    assert str(TELEGRAM_ID) not in known.telegram_user_id_masked


def test_the_wire_names_are_camel_case_and_generated_rather_than_spelled() -> None:
    # Arrange — ``ApiModel``'s alias generator is what keeps a Python field from drifting from
    # its wire name; this asserts the generation actually reaches this module's models.
    payload = to_intent_detail_view(intent()).model_dump(by_alias=True)

    # Assert
    assert "telegramUserIdMasked" in payload
    assert "isBuyerErased" in payload
    assert "publicRef" in payload
    assert "telegram_user_id_masked" not in payload
