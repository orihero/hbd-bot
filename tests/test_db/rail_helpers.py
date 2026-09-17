"""Builders for the three redirect-rail tables, shared by every admin read test.

Kept beside the tests rather than in ``conftest.py`` because they are not fixtures: a test
needs three intents in three states with three different chains behind them, and a fixture
that produced one shape would be re-parameterised into unreadability by the second caller.
``tests/test_db/credit_helpers.py`` is the precedent.

**Every Telegram id here is outside the 32-bit range**, matching ``test_payme_tables.py`` and
``test_credits.py``. A column that quietly became an ``Integer`` would not fail loudly; it
would silently truncate the id of whoever is paying, and the row would then be anonymised on
somebody else's ``/forget`` or missed entirely on their own.

**The receipt and the grant are written under the INTENT's key, verbatim.** That single string
is the entire join between money and fulfilment — ``payment_intents.idempotency_key`` is
copied into ``topup_purchases.idempotency_key`` / ``plan_purchases.idempotency_key`` and into
``credit_ledger.idempotency_key`` inside the one commit that also flips the intent to ``paid``
— so a helper that minted a fresh key per table would build a database in which the correct
query returns nothing and an incorrect one might.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Final
from uuid import UUID, uuid4

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from bayram.db.enums import (
    CreditEntryKind,
    CreditReason,
    IntentProduct,
    PaymentIntentState,
    PaymeState,
    PlanKind,
    TopupKind,
)
from bayram.db.models.credit_ledger import CreditLedgerRow
from bayram.db.models.payme_rpc_log import PaymeRpcLogRow
from bayram.db.models.payme_transaction import PaymeTransactionRow
from bayram.db.models.payment_intent import PaymentIntentRow
from bayram.db.models.plan_purchase import PlanPurchaseRow
from bayram.db.models.topup_purchase import TopupPurchaseRow

#: Well outside 2**31. See the module docstring.
USER: Final[int] = 8_912_345_678_901
#: A second buyer, so a test that seeds two payments does not accidentally prove something
#: about one account's history when it meant to prove something about two payments.
OTHER_USER: Final[int] = 8_912_345_678_902
#: A 24-character Mongo ObjectId, the width a real cashbox id is, so nothing here depends on
#: the merchant credential being the literal ``placeholder`` the deployment boots with today.
MERCHANT: Final[str] = "587f72c72cac0d162c722ae2"
SINGLE_MINOR: Final[int] = 700_000
PLAN_MINOR: Final[int] = 4_900_000
#: What ``db/payme.py`` writes into ``settle_note`` when the RAIL performed the settlement.
#: Spelled here rather than imported because these helpers stand in for the writer.
RAIL_NOTE: Final[str] = "payme"


def make_intent(
    *,
    now: datetime,
    state: PaymentIntentState = PaymentIntentState.PENDING,
    product: IntentProduct = IntentProduct.SINGLE,
    telegram_user_id: int | None = USER,
    created_at: datetime | None = None,
    **overrides: Any,
) -> PaymentIntentRow:
    """One intent, valid in every respect the schema's three CHECK constraints can see.

    ``created_at`` is supplied explicitly rather than left to ``TimestampMixin``'s default so a
    window test can place a row in the past; the default clock would stamp every seeded row
    with the same instant and make every window either match all of them or none.
    """
    values: dict[str, Any] = {
        "public_ref": uuid4().hex[:24],
        # The real shape, ``topup:{tg}:{scope}:{seq}``, so a test can prove it never reaches a
        # view model by looking for the prefix.
        "idempotency_key": f"topup:{telegram_user_id}:single:{uuid4().hex[:8]}",
        "telegram_user_id": telegram_user_id,
        "product": product,
        "amount_minor": SINGLE_MINOR if product is IntentProduct.SINGLE else PLAN_MINOR,
        "currency": "UZS",
        "provider": "payme",
        "merchant_id": MERCHANT,
        "is_sandbox": True,
        "language": "uz_latn",
        "state": state,
        "valid_until": now + timedelta(hours=12),
        "created_at": now if created_at is None else created_at,
        "updated_at": now if created_at is None else created_at,
    }
    if product is IntentProduct.STARTER:
        # The CHECK makes both mandatory the moment the product is a plan.
        values["plan_songs"] = 12
        values["plan_days"] = 30
    values.update(overrides)
    return PaymentIntentRow(**values)


def settle(intent: PaymentIntentRow, *, at: datetime, note: str = RAIL_NOTE) -> PaymentIntentRow:
    """Mark an intent paid the way ``_settle`` does: state, clock and note from one instant."""
    intent.state = PaymentIntentState.PAID
    intent.settled_at = at
    intent.settle_note = note
    return intent


def make_transaction(
    *,
    intent_id: UUID,
    payme_time: datetime,
    state: PaymeState = PaymeState.CREATED,
    **overrides: Any,
) -> PaymeTransactionRow:
    """One rail-side transaction against ``intent_id``, on the RAIL's clock.

    ``perform_time`` is set whenever ``state`` is ``performed``, because that is the only shape
    the settlement writes and a test seeded with a performed transaction and a NULL
    ``perform_time`` would be asserting against a row the production path cannot produce.
    """
    values: dict[str, Any] = {
        "payme_transaction_id": uuid4().hex[:24],
        "intent_id": intent_id,
        "payme_time": payme_time,
        "amount_minor": SINGLE_MINOR,
        "state": state,
        "create_time": payme_time,
        "created_at": payme_time,
        "updated_at": payme_time,
    }
    if state is PaymeState.PERFORMED:
        values["perform_time"] = payme_time
    values.update(overrides)
    return PaymeTransactionRow(**values)


def make_topup_receipt(intent: PaymentIntentRow, *, at: datetime) -> TopupPurchaseRow:
    """The single-song receipt written under this intent's own key. See the module docstring."""
    return TopupPurchaseRow(
        telegram_user_id=intent.telegram_user_id,
        product=TopupKind.SINGLE,
        credits_granted=1,
        amount_minor=intent.amount_minor,
        currency=intent.currency,
        provider=intent.provider,
        reference=uuid4().hex[:24],
        idempotency_key=intent.idempotency_key,
        created_at=at,
    )


def make_plan_receipt(intent: PaymentIntentRow, *, at: datetime) -> PlanPurchaseRow:
    """The plan receipt written under this intent's own key. Grants no credit, by design."""
    return PlanPurchaseRow(
        telegram_user_id=intent.telegram_user_id,
        plan=PlanKind.STARTER,
        songs_included=intent.plan_songs or 12,
        songs_used=0,
        amount_minor=intent.amount_minor,
        currency=intent.currency,
        provider=intent.provider,
        reference=uuid4().hex[:24],
        idempotency_key=intent.idempotency_key,
        plan_ends_at=at + timedelta(days=intent.plan_days or 30),
        created_at=at,
        updated_at=at,
    )


def make_grant(intent: PaymentIntentRow, *, at: datetime) -> CreditLedgerRow:
    """The ``+1`` credit a SINGLE-SONG sale mints. A plan sale writes nothing like this."""
    return CreditLedgerRow(
        telegram_user_id=intent.telegram_user_id,
        kind=CreditEntryKind.GRANT,
        reason=CreditReason.TOPUP_PURCHASE,
        delta=1,
        idempotency_key=intent.idempotency_key,
        actor="checkout",
        created_at=at,
    )


def make_call(
    *,
    at: datetime,
    method: str = "CheckPerformTransaction",
    reply_code: int = 0,
    public_ref: str | None = None,
    payme_transaction_id: str | None = None,
    duration_ms: int = 12,
    peer_ip: str | None = "185.8.212.10",
) -> PaymeRpcLogRow:
    """One journal row. Both identifier columns default to NULL — a failed-auth call."""
    return PaymeRpcLogRow(
        at=at,
        method=method,
        public_ref=public_ref,
        payme_transaction_id=payme_transaction_id,
        reply_code=reply_code,
        peer_ip=peer_ip,
        duration_ms=duration_ms,
    )


async def add(sessions: async_sessionmaker[AsyncSession], *rows: object) -> None:
    """Commit a batch of rows in one transaction, the way the settlement path would."""
    async with sessions.begin() as session:
        session.add_all(list(rows))
