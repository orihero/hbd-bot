"""The refusals, asserted through the NEW entry point rather than through the ledger.

``tests/test_db/test_plan_purchases.py`` already pins that an unpaid purchase grants nothing
— but it asserts it through ``SqlPurchaseLedger``, which is the caller that never needed the
guard. Those two refusals used to live in that caller, ABOVE the clock read and above
``begin()``, and the whole risk of extracting the sale-writing bodies was that a mechanical
"move the body" starts at ``now =`` and leaves them behind. Every test here calls
:func:`bayram.db.fulfilment.write_single_sale` and :func:`bayram.db.fulfilment.write_plan_sale`
DIRECTLY, against a real session, because that is the door a payment gateway settling an
inbound HTTP request comes through and the ledger's own suite would stay green with the
guards gone.

Each test asserts what is in the TABLES afterwards and not merely which exception came back:
a guard that raised after writing the receipt would still satisfy ``pytest.raises`` and would
still hand out a free song. And one of them deliberately does successful work in the same
transaction before tripping the refusal, because the extracted functions do not own their
transaction and the claim being made is that a refusal unwinds the caller's whole commit —
which, for the gateway, includes a rail transaction it had already flipped.
"""

from __future__ import annotations

from typing import Final

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from bayram.checkout import Product, Purchase
from bayram.db.fulfilment import write_plan_sale, write_single_sale
from bayram.db.models import CreditLedgerRow, PlanPurchaseRow, TopupPurchaseRow
from bayram.errors import ErrorCode, PaymentError
from tests.test_db.conftest import MovableClock

#: Outside the 32-bit range, so a column that quietly became an ``Integer`` on either engine
#: fails here rather than in production.
_USER: Final[int] = 8_912_345_678_901
_SINGLE_MINOR: Final[int] = 700_000
_PLAN_MINOR: Final[int] = 4_900_000
_PLAN_SONGS: Final[int] = 12
_PLAN_DAYS: Final[int] = 30


def _purchase(product: Product, *, is_paid: bool = True, reference: str = "stub-abc") -> Purchase:
    return Purchase(
        product=product,
        provider="stub",
        reference=reference,
        amount_minor=_SINGLE_MINOR if product is Product.SINGLE else _PLAN_MINOR,
        currency="UZS",
        is_paid=is_paid,
    )


async def _count(sessions: async_sessionmaker[AsyncSession], row: type[object]) -> int:
    async with sessions() as session:
        return int(
            (await session.execute(sa.select(sa.func.count()).select_from(row))).scalar_one()
        )


async def _money_rows_written(sessions: async_sessionmaker[AsyncSession]) -> tuple[int, int, int]:
    """Every table a paid sale can touch, counted together. Zero means nothing happened."""
    return (
        await _count(sessions, TopupPurchaseRow),
        await _count(sessions, CreditLedgerRow),
        await _count(sessions, PlanPurchaseRow),
    )


# ---------------------------------------------------------------------------
# write_single_sale
# ---------------------------------------------------------------------------
async def test_write_single_sale_refuses_an_unpaid_purchase_and_writes_nothing(
    sessions: async_sessionmaker[AsyncSession], clock: MovableClock
) -> None:
    # Arrange — the shape a redirect rail returns while a payment is merely STARTED.
    unpaid = _purchase(Product.SINGLE, is_paid=False)

    # Act
    with pytest.raises(PaymentError) as raised:
        async with sessions.begin() as session:
            await write_single_sale(
                session,
                telegram_user_id=_USER,
                purchase=unpaid,
                idempotency_key=f"topup:{_USER}:session:0",
                now=clock.now,
            )

    # Assert — a free song for every abandoned checkout is what this refusal prevents, and it
    # has to be prevented here because the gateway never goes through SqlPurchaseLedger.
    assert raised.value.code is ErrorCode.PAYMENT_FAILED
    assert await _money_rows_written(sessions) == (0, 0, 0)


async def test_write_single_sale_refuses_a_product_that_is_not_a_topup(
    sessions: async_sessionmaker[AsyncSession], clock: MovableClock
) -> None:
    # Arrange — a paid plan misrouted into the top-up write. `TopupKind('starter')` would
    # raise a bare ValueError, which run_guarded does not catch.
    misrouted = _purchase(Product.STARTER)

    # Act
    with pytest.raises(PaymentError) as raised:
        async with sessions.begin() as session:
            await write_single_sale(
                session,
                telegram_user_id=_USER,
                purchase=misrouted,
                idempotency_key=f"topup:{_USER}:session:0",
                now=clock.now,
            )

    # Assert
    assert raised.value.code is ErrorCode.PAYMENT_FAILED
    assert await _money_rows_written(sessions) == (0, 0, 0)


async def test_a_refusal_unwinds_a_sale_already_written_in_the_same_transaction(
    sessions: async_sessionmaker[AsyncSession], clock: MovableClock
) -> None:
    # Arrange — the gateway's shape: work already done in this commit, then a refusal. The
    # extracted functions do not own the transaction, so the rollback is the caller's.
    paid = _purchase(Product.SINGLE)
    unpaid = _purchase(Product.SINGLE, is_paid=False, reference="stub-def")

    # Act
    with pytest.raises(PaymentError):
        async with sessions.begin() as session:
            await write_single_sale(
                session,
                telegram_user_id=_USER,
                purchase=paid,
                idempotency_key=f"topup:{_USER}:session:0",
                now=clock.now,
            )
            await write_single_sale(
                session,
                telegram_user_id=_USER,
                purchase=unpaid,
                idempotency_key=f"topup:{_USER}:session:1",
                now=clock.now,
            )

    # Assert — raising inside the transaction rather than in front of it is not a weakening:
    # the first sale is gone too, which is exactly what a gateway needs from a mid-commit
    # refusal that has already flipped a rail transaction.
    assert await _money_rows_written(sessions) == (0, 0, 0)


# ---------------------------------------------------------------------------
# write_plan_sale
# ---------------------------------------------------------------------------
async def test_write_plan_sale_refuses_an_unpaid_purchase_and_writes_nothing(
    sessions: async_sessionmaker[AsyncSession], clock: MovableClock
) -> None:
    # Arrange
    unpaid = _purchase(Product.STARTER, is_paid=False)

    # Act
    with pytest.raises(PaymentError) as raised:
        async with sessions.begin() as session:
            await write_plan_sale(
                session,
                telegram_user_id=_USER,
                purchase=unpaid,
                songs=_PLAN_SONGS,
                days=_PLAN_DAYS,
                idempotency_key=f"plan:starter:{_USER}:session:0",
                now=clock.now,
            )

    # Assert
    assert raised.value.code is ErrorCode.PAYMENT_FAILED
    assert await _money_rows_written(sessions) == (0, 0, 0)


async def test_write_plan_sale_refuses_a_product_that_is_not_a_plan(
    sessions: async_sessionmaker[AsyncSession], clock: MovableClock
) -> None:
    # Arrange — a paid single song misrouted into the plan write. Nothing in the schema would
    # refuse it: `PlanKind.STARTER` is hard-coded and the end date is invented from `days`, so
    # the customer would silently hold a twelve-song plan they never bought.
    misrouted = _purchase(Product.SINGLE)

    # Act
    with pytest.raises(PaymentError) as raised:
        async with sessions.begin() as session:
            await write_plan_sale(
                session,
                telegram_user_id=_USER,
                purchase=misrouted,
                songs=_PLAN_SONGS,
                days=_PLAN_DAYS,
                idempotency_key=f"topup:{_USER}:session:0",
                now=clock.now,
            )

    # Assert — and the key is untouched, so the write that SHOULD have happened can still use
    # it. A guard that ran after the insert would have burned it.
    assert raised.value.code is ErrorCode.PAYMENT_FAILED
    assert await _money_rows_written(sessions) == (0, 0, 0)


# ---------------------------------------------------------------------------
# The happy paths, so the refusals above are not passing for the wrong reason
# ---------------------------------------------------------------------------
async def test_write_single_sale_writes_one_receipt_and_one_grant_in_the_callers_transaction(
    sessions: async_sessionmaker[AsyncSession], clock: MovableClock
) -> None:
    # Arrange
    paid = _purchase(Product.SINGLE)

    # Act — one transaction, opened by the caller, committed by the caller.
    async with sessions.begin() as session:
        await write_single_sale(
            session,
            telegram_user_id=_USER,
            purchase=paid,
            idempotency_key=f"topup:{_USER}:session:0",
            now=clock.now,
        )

    # Assert
    assert await _money_rows_written(sessions) == (1, 1, 0)


async def test_write_plan_sale_hands_back_the_running_plan_instead_of_writing_a_second(
    sessions: async_sessionmaker[AsyncSession], clock: MovableClock
) -> None:
    # Arrange — a deliberate second purchase, not a replay: a different key entirely.
    async with sessions.begin() as session:
        first = await write_plan_sale(
            session,
            telegram_user_id=_USER,
            purchase=_purchase(Product.STARTER),
            songs=_PLAN_SONGS,
            days=_PLAN_DAYS,
            idempotency_key=f"plan:starter:{_USER}:session:0",
            now=clock.now,
        )
        first_key = first.idempotency_key

    # Act
    async with sessions.begin() as session:
        second = await write_plan_sale(
            session,
            telegram_user_id=_USER,
            purchase=_purchase(Product.STARTER, reference="stub-def"),
            songs=_PLAN_SONGS,
            days=_PLAN_DAYS,
            idempotency_key=f"plan:starter:{_USER}:session:1",
            now=clock.now,
        )
        second_key = second.idempotency_key

    # Assert — one plan at a time, and the rule travelled with the write rather than staying
    # in the ledger, so a rail settling a second plan gets the same answer the bot does.
    assert second_key == first_key
    assert await _money_rows_written(sessions) == (0, 0, 1)
