"""The top-up RECEIPT: the only record that a single song was ever sold for a price.

``credit_ledger`` records that a credit arrived and can never record what it cost — it has
no amount column, no currency and no rail, and by design it never will. So every guarantee
about the money on a single-song sale lives on ``topup_purchases`` and on nothing else, and
each one below is a property no other suite covers:

* **One row per sale, none for a replay.** Both writes are insert-or-ignore on ONE key, so
  the two statements that now carry ``PurchaseFulfiller``'s additive-and-idempotent
  invariant are pinned together rather than separately — a receipt that deduplicated while
  the grant did not would sell a song and record half of it.
* **One key and one clock across both rows.** The admin surface counts the sales recorded
  before amounts were with a correlated ``NOT EXISTS`` on that shared key, and compares two
  windowed populations; both break silently if the two writes drift apart on either.
* **Nothing is written for a purchase that was not paid, or for a product this table cannot
  record.** The plan refusal is the one that would otherwise escape as a bare ``ValueError``
  from ``TopupKind(...)``, past a ``Result`` boundary that promises never to raise.
* **``amount_minor = 0`` is a real sale and is distinguishable from a sale whose amount was
  never recorded.** The first is a row with a zero on it; the second is the ABSENCE of a row
  beside a ledger GRANT. That discrimination is the entire reason there is no backfill, so
  it is asserted structurally here rather than assumed.

The schema's own refusals are asserted as real ``IntegrityError``s around real inserts,
following ``test_credit_schema.py`` and ``test_plan_purchases.py``: the writer never
produces a non-positive ``credits_granted`` or a negative amount, which is precisely why the
CHECK — the thing that will still be there when a future writer does — needs its own test.
"""

from __future__ import annotations

from typing import Final

import pytest
import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from hbd.checkout import Product, Purchase
from hbd.contracts import is_err, is_ok
from hbd.db.enums import CreditEntryKind, CreditReason, TopupKind
from hbd.db.models import CreditLedgerRow, TopupPurchaseRow
from hbd.db.purchases import CHECKOUT_ACTOR, SqlPurchaseLedger
from hbd.db.topup_sql import insert_topup, topup_by_key
from hbd.entitlements import EntitlementPolicy
from hbd.errors import ErrorCode
from tests.test_db.conftest import MovableClock

#: Outside the 32-bit range, so a column that quietly became an ``Integer`` on either engine
#: fails here rather than in production.
_USER: Final[int] = 8_912_345_678_901
_SINGLE_MINOR: Final[int] = 700_000
_PLAN_MINOR: Final[int] = 4_900_000
_REFERENCE: Final[str] = "stub-8f21c0"

#: The allowance is off in every test here so a balance assertion is about the purchase and
#: nothing else — the shipped configuration too, since the free half of this product is the
#: lyric rather than a song.
_NO_ALLOWANCE: Final[EntitlementPolicy] = EntitlementPolicy(allowance_credits=0)


def _purchase(
    product: Product = Product.SINGLE,
    *,
    is_paid: bool = True,
    amount_minor: int | None = None,
    reference: str = _REFERENCE,
) -> Purchase:
    return Purchase(
        product=product,
        provider="stub",
        reference=reference,
        amount_minor=(
            amount_minor
            if amount_minor is not None
            else (_SINGLE_MINOR if product is Product.SINGLE else _PLAN_MINOR)
        ),
        currency="UZS",
        is_paid=is_paid,
    )


def _purchases(
    sessions: async_sessionmaker[AsyncSession], clock: MovableClock
) -> SqlPurchaseLedger:
    return SqlPurchaseLedger(sessions, policy=_NO_ALLOWANCE, clock=clock)


async def _topup_rows(
    sessions: async_sessionmaker[AsyncSession],
) -> list[TopupPurchaseRow]:
    async with sessions() as session:
        return list(
            (
                await session.execute(
                    sa.select(TopupPurchaseRow).order_by(TopupPurchaseRow.idempotency_key)
                )
            )
            .scalars()
            .all()
        )


async def _ledger_rows(sessions: async_sessionmaker[AsyncSession]) -> list[CreditLedgerRow]:
    async with sessions() as session:
        return list(
            (
                await session.execute(
                    sa.select(CreditLedgerRow).order_by(CreditLedgerRow.idempotency_key)
                )
            )
            .scalars()
            .all()
        )


# ---------------------------------------------------------------------------
# What one paid button writes
# ---------------------------------------------------------------------------
async def test_a_paid_single_song_records_the_price_the_rail_actually_answered_for(
    sessions: async_sessionmaker[AsyncSession], clock: MovableClock
) -> None:
    # Arrange
    purchases = _purchases(sessions, clock)

    # Act
    result = await purchases.fulfil_single(
        telegram_user_id=_USER,
        purchase=_purchase(),
        idempotency_key=f"topup:{_USER}:session:0",
    )

    # Assert — every money field is byte-identical to the Purchase the provider returned.
    # Nothing on this path may read a price from Settings: that is what the checkout QUOTES,
    # and a sale priced from it would move every historical figure the next time it changed.
    assert is_ok(result), result
    rows = await _topup_rows(sessions)
    assert len(rows) == 1
    row = rows[0]
    assert row.telegram_user_id == _USER
    assert row.product is TopupKind.SINGLE
    assert (row.amount_minor, row.currency) == (_SINGLE_MINOR, "UZS")
    assert (row.provider, row.reference) == ("stub", _REFERENCE)
    # The receipt says how many credits the sale put on the balance, and the ledger agrees.
    ledger = await _ledger_rows(sessions)
    assert [(entry.reason, entry.delta, entry.actor) for entry in ledger] == [
        (CreditReason.TOPUP_PURCHASE, row.credits_granted, CHECKOUT_ACTOR)
    ]
    assert result.value.credits == row.credits_granted


async def test_the_receipt_and_the_grant_share_one_key_and_one_clock(
    sessions: async_sessionmaker[AsyncSession], clock: MovableClock
) -> None:
    # Arrange — the admin surface joins these two populations on the key and windows both on
    # created_at, so a drift on either is silent and permanent.
    purchases = _purchases(sessions, clock)
    key = f"topup:{_USER}:session:0"

    # Act
    result = await purchases.fulfil_single(
        telegram_user_id=_USER, purchase=_purchase(), idempotency_key=key
    )

    # Assert
    assert is_ok(result), result
    receipt = (await _topup_rows(sessions))[0]
    grant = (await _ledger_rows(sessions))[0]
    assert receipt.idempotency_key == grant.idempotency_key == key
    assert receipt.created_at == grant.created_at == clock.now


async def test_a_replayed_key_writes_neither_a_second_receipt_nor_a_second_grant(
    sessions: async_sessionmaker[AsyncSession], clock: MovableClock
) -> None:
    # Arrange — a double tap, a stale message and a redelivered Telegram update all look
    # like this, and all three arrive in production.
    purchases = _purchases(sessions, clock)
    key = f"topup:{_USER}:session:0"

    # Act
    first = await purchases.fulfil_single(
        telegram_user_id=_USER, purchase=_purchase(), idempotency_key=key
    )
    second = await purchases.fulfil_single(
        telegram_user_id=_USER,
        purchase=_purchase(reference="stub-a-second-charge"),
        idempotency_key=key,
    )

    # Assert — the UNCHANGED balance is the correct answer: nothing went wrong, and the
    # customer has exactly what they paid for. One sale, at the price of the FIRST charge.
    assert is_ok(first) and first.value.credits == 1
    assert is_ok(second) and second.value.credits == 1
    rows = await _topup_rows(sessions)
    assert len(rows) == 1
    assert rows[0].reference == _REFERENCE
    assert len(await _ledger_rows(sessions)) == 1


async def test_a_deliberate_second_purchase_under_a_new_key_records_a_second_sale(
    sessions: async_sessionmaker[AsyncSession], clock: MovableClock
) -> None:
    # Arrange — buy-as-many-as-you-like is the product; only a REPLAY collapses.
    purchases = _purchases(sessions, clock)

    # Act
    for seq in range(2):
        result = await purchases.fulfil_single(
            telegram_user_id=_USER,
            purchase=_purchase(reference=f"stub-{seq}"),
            idempotency_key=f"topup:{_USER}:session:{seq}",
        )
        assert is_ok(result), result

    # Assert — two sales, two grants, and the revenue is the sum of both.
    rows = await _topup_rows(sessions)
    assert [row.amount_minor for row in rows] == [_SINGLE_MINOR, _SINGLE_MINOR]
    assert len(await _ledger_rows(sessions)) == 2


# ---------------------------------------------------------------------------
# Refusals
# ---------------------------------------------------------------------------
async def test_an_unpaid_purchase_records_no_sale_and_grants_nothing(
    sessions: async_sessionmaker[AsyncSession], clock: MovableClock
) -> None:
    # Arrange — the shape a redirect rail returns while a payment is merely STARTED. The
    # refusal happens before any session opens, so there is nothing to roll back.
    purchases = _purchases(sessions, clock)

    # Act
    result = await purchases.fulfil_single(
        telegram_user_id=_USER,
        purchase=_purchase(is_paid=False),
        idempotency_key=f"topup:{_USER}:session:0",
    )

    # Assert — a recorded sale for an abandoned checkout would be revenue that never existed.
    assert is_err(result) and result.error.code is ErrorCode.PAYMENT_FAILED
    assert await _topup_rows(sessions) == []
    assert await _ledger_rows(sessions) == []


async def test_a_plan_routed_through_the_single_song_path_is_refused_and_writes_nothing(
    sessions: async_sessionmaker[AsyncSession], clock: MovableClock
) -> None:
    # Arrange — a caller that sent a starter plan to the wrong method. TopupKind mirrors only
    # the one-off half of Product, so the conversion would raise a bare ValueError, which
    # run_guarded does not catch and which would escape the Result boundary entirely.
    purchases = _purchases(sessions, clock)

    # Act
    result = await purchases.fulfil_single(
        telegram_user_id=_USER,
        purchase=_purchase(Product.STARTER),
        idempotency_key=f"topup:{_USER}:session:0",
    )

    # Assert — a typed Err, and no half-written purchase behind it.
    assert is_err(result) and result.error.code is ErrorCode.PAYMENT_FAILED
    assert await _topup_rows(sessions) == []
    assert await _ledger_rows(sessions) == []


# ---------------------------------------------------------------------------
# Zero is a price, and an absent row is a different fact
# ---------------------------------------------------------------------------
async def test_a_sale_priced_at_zero_is_recorded_as_a_sale_with_a_zero_on_it(
    sessions: async_sessionmaker[AsyncSession], clock: MovableClock
) -> None:
    # Arrange — Settings.single_song_price_minor ships ge=0, so a promo priced at zero is a
    # real sale and not an unmeasured quantity. This is the one shape of zero the design
    # allows, and it is why amount_minor is NOT NULL.
    purchases = _purchases(sessions, clock)

    # Act
    result = await purchases.fulfil_single(
        telegram_user_id=_USER,
        purchase=_purchase(amount_minor=0),
        idempotency_key=f"topup:{_USER}:promo",
    )

    # Assert
    assert is_ok(result), result
    rows = await _topup_rows(sessions)
    assert len(rows) == 1
    assert rows[0].amount_minor == 0


async def test_a_sale_recorded_before_amounts_existed_is_an_absent_row_and_not_a_zero(
    sessions: async_sessionmaker[AsyncSession], clock: MovableClock
) -> None:
    # Arrange — the historical shape: _fulfil_single used to write only the ledger GRANT, so
    # every top-up sold before this landed has a key and a clock and no price anywhere. It
    # cannot be back-priced, because the only price available is the one the checkout quotes
    # TODAY, and pricing history from it moves every past figure the next time it changes.
    async with sessions.begin() as session:
        session.add(
            CreditLedgerRow(
                telegram_user_id=_USER,
                kind=CreditEntryKind.GRANT,
                reason=CreditReason.TOPUP_PURCHASE,
                delta=1,
                idempotency_key="topup:legacy:session:0",
                actor=CHECKOUT_ACTOR,
                created_at=clock.now,
            )
        )
    purchases = _purchases(sessions, clock)
    priced = await purchases.fulfil_single(
        telegram_user_id=_USER,
        purchase=_purchase(amount_minor=0),
        idempotency_key="topup:priced:session:0",
    )
    assert is_ok(priced), priced

    # Act — the two states, asked of the table the same way the admin count asks.
    async with sessions() as session:
        legacy = await topup_by_key(session, "topup:legacy:session:0")
        zero_priced = await topup_by_key(session, "topup:priced:session:0")

    # Assert — "sold before we recorded amounts" is the ABSENCE of a row; "sold for zero" is
    # a row carrying a zero. Two different facts, told apart structurally and never by a null.
    assert legacy is None
    assert zero_priced is not None and zero_priced.amount_minor == 0


# ---------------------------------------------------------------------------
# What the schema refuses, whatever a future writer does
# ---------------------------------------------------------------------------
async def test_the_schema_refuses_a_receipt_that_granted_no_credits(
    sessions: async_sessionmaker[AsyncSession], clock: MovableClock
) -> None:
    # Arrange / Act / Assert — a charge with no entitlement: the customer would have paid for
    # silence, and nothing downstream would ever notice.
    with pytest.raises(IntegrityError):
        async with sessions.begin() as session:
            await insert_topup(
                session,
                telegram_user_id=_USER,
                product=TopupKind.SINGLE,
                credits_granted=0,
                amount_minor=_SINGLE_MINOR,
                currency="UZS",
                provider="stub",
                reference=_REFERENCE,
                idempotency_key="topup:no-credits",
                now=clock.now,
            )


async def test_the_schema_refuses_a_negative_amount(
    sessions: async_sessionmaker[AsyncSession], clock: MovableClock
) -> None:
    # Arrange / Act / Assert — a refund wearing a receipt's shape. Refunds have no row type
    # here yet, and a negative amount inside a SUM is a silently wrong revenue figure.
    with pytest.raises(IntegrityError):
        async with sessions.begin() as session:
            await insert_topup(
                session,
                telegram_user_id=_USER,
                product=TopupKind.SINGLE,
                credits_granted=1,
                amount_minor=-1,
                currency="UZS",
                provider="stub",
                reference=_REFERENCE,
                idempotency_key="topup:negative",
                now=clock.now,
            )
