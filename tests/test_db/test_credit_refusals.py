"""Every way the ledger says no — and the proof that saying no writes nothing.

Split out of ``test_credits.py``, which had grown past the repo's 800-line cap. The seam is
the natural one: that module is about what the ledger DOES, this one is about what it
REFUSES and what a refusal costs.

The shared property, asserted in every test here rather than once at the end: a refusal is
raised inside the transaction, so the account it had just opened, the allowance it had just
minted and the debit it had just written all roll back with it. There is no compensating
write anywhere in this layer, and these assertions on the empty tables are why there does
not need to be.
"""

from __future__ import annotations

from uuid import uuid4

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from bayram.contracts import is_err, is_ok
from bayram.db.enums import CreditEntryKind, CreditReason
from bayram.entitlements import (
    ChargeOutcome,
    EntitlementPolicy,
    InsufficientCreditsError,
    SettlementOutcome,
    TooManyOrdersInFlightError,
    period_index_for,
    period_start,
)
from bayram.errors import EntitlementError, ErrorCode
from tests.test_db.conftest import MovableClock
from tests.test_db.credit_helpers import (
    _ACTOR,
    _OTHER_USER,
    _PERIOD_DAYS,
    _USER,
    _assert_no_drift,
    _charge,
    _entries,
    _ledger,
    _of_kind,
    _settle,
    _stored_balance,
)


# ---------------------------------------------------------------------------
# Refusals
# ---------------------------------------------------------------------------
async def test_a_spent_allowance_is_refused_with_a_date_and_leaves_no_trace(
    sessions: async_sessionmaker[AsyncSession], clock: MovableClock
) -> None:
    # Arrange — spend the whole window the honest way: three renders, each settled so the
    # in-flight cap is not what refuses the fourth.
    ledger = _ledger(sessions, clock)
    for _ in range(3):
        order_id = uuid4()
        await _charge(ledger, order_id)
        await _settle(ledger, order_id, SettlementOutcome.DELIVERED)
    assert await _stored_balance(sessions) == 0
    before = await _entries(sessions)

    # Act
    result = await ledger.charge(telegram_user_id=_USER, order_id=uuid4(), actor=_ACTOR)

    # Assert — terminal, carries scalars a locale string can interpolate, and says WHEN the
    # next credit opens; the allowance is rolling, so that date is actionable and true.
    assert is_err(result)
    error = result.error
    assert isinstance(error, InsufficientCreditsError)
    assert error.error_code is ErrorCode.CREDITS_EXHAUSTED
    assert error.is_retryable is False
    assert error.context["balance"] == 0
    assert error.context["needed"] == 1
    expected_open = period_start(
        period_index_for(clock.now, period_days=_PERIOD_DAYS) + 1, period_days=_PERIOD_DAYS
    )
    assert error.context["next_grant_at"] == expected_open.isoformat()
    # Nothing was written: no partial debit, no phantom allowance.
    assert await _entries(sessions) == before
    assert await _stored_balance(sessions) == 0
    await _assert_no_drift(sessions)


async def test_an_insufficient_balance_rolls_back_the_account_it_just_opened(
    sessions: async_sessionmaker[AsyncSession], clock: MovableClock
) -> None:
    # Arrange — a deployment whose allowance is zero is the cleanest way to reach the
    # conditional UPDATE with nothing to take, and it proves the rollback also removes the
    # account row opened moments earlier in the same transaction.
    ledger = _ledger(sessions, clock, policy=EntitlementPolicy(allowance_credits=0))

    # Act
    result = await ledger.charge(telegram_user_id=_USER, order_id=uuid4(), actor=_ACTOR)

    # Assert
    assert is_err(result)
    assert isinstance(result.error, InsufficientCreditsError)
    assert await _entries(sessions) == []
    assert await _stored_balance(sessions) is None
    await _assert_no_drift(sessions)


async def test_a_blocked_account_is_refused_even_with_credits(
    sessions: async_sessionmaker[AsyncSession], clock: MovableClock
) -> None:
    # Arrange — a block must stop a render, not merely a message: the worker gate reads it
    # too, so a job queued before the block never spends vendor money. The first order is
    # settled first so the in-flight cap cannot be what refuses the second.
    ledger = _ledger(sessions, clock)
    order_id = uuid4()
    await _charge(ledger, order_id)
    await _settle(ledger, order_id, SettlementOutcome.DELIVERED)
    assert is_ok(await ledger.set_blocked(_USER, is_blocked=True))
    before = await _entries(sessions)

    # Act
    result = await ledger.charge(telegram_user_id=_USER, order_id=uuid4(), actor=_ACTOR)

    # Assert — the base class, not a credit refusal: this account has two credits left.
    assert is_err(result)
    assert type(result.error) is EntitlementError
    assert result.error.error_code is ErrorCode.ACCOUNT_BLOCKED
    assert result.error.is_retryable is False
    assert await _entries(sessions) == before
    assert await _stored_balance(sessions) == 2
    await _assert_no_drift(sessions)


async def test_the_in_flight_cap_refuses_a_second_order_but_never_the_one_being_charged(
    sessions: async_sessionmaker[AsyncSession], clock: MovableClock
) -> None:
    # Arrange — the cap is derived from unsettled ledger debits, not from orders.state,
    # which is verified broken for this: _fail writes FAILED on retryable failures too, so an
    # order in ARQ backoff would be invisible and the account could stack a second.
    ledger = _ledger(sessions, clock)
    first_order = uuid4()
    await _charge(ledger, first_order)

    # Act
    refused = await ledger.charge(telegram_user_id=_USER, order_id=uuid4(), actor=_ACTOR)
    replayed = await _charge(ledger, first_order)

    # Assert
    assert is_err(refused)
    assert isinstance(refused.error, TooManyOrdersInFlightError)
    assert refused.error.error_code is ErrorCode.TOO_MANY_IN_FLIGHT
    assert refused.error.is_retryable is False
    assert refused.error.context["in_flight"] == 1
    # The order under authorisation is excluded from its own count, so a retry of the same
    # order is never refused by the debit it wrote itself.
    assert replayed[0] is ChargeOutcome.ALREADY_PAID
    assert await _stored_balance(sessions) == 2
    await _assert_no_drift(sessions)


async def test_another_accounts_unsettled_render_does_not_fill_this_accounts_slot(
    sessions: async_sessionmaker[AsyncSession], clock: MovableClock
) -> None:
    # Arrange — the in-flight predicate filters on telegram_user_id; without it the first
    # busy account in the system would lock every other customer out.
    ledger = _ledger(sessions, clock)
    await _charge(ledger, uuid4(), telegram_user_id=_OTHER_USER)

    # Act
    outcome, balance = await _charge(ledger, uuid4())

    # Assert
    assert outcome is ChargeOutcome.CHARGED
    assert balance.in_flight == 1
    await _assert_no_drift(sessions)


async def test_a_consumed_debit_frees_the_in_flight_slot_without_moving_the_balance(
    sessions: async_sessionmaker[AsyncSession], clock: MovableClock
) -> None:
    # Arrange
    ledger = _ledger(sessions, clock)
    first_order = uuid4()
    await _charge(ledger, first_order)

    # Act
    settled = await _settle(ledger, first_order, SettlementOutcome.NOT_DELIVERED)
    outcome, balance = await _charge(ledger, uuid4())

    # Assert — NOT_DELIVERED consumes rather than refunds: the kit exists and is
    # redeliverable, and refunding it is what would let someone block the bot mid-render for
    # unlimited free songs.
    assert settled is True
    assert outcome is ChargeOutcome.CHARGED
    assert balance.in_flight == 1
    assert await _stored_balance(sessions) == 1
    assert _of_kind(await _entries(sessions), CreditEntryKind.CONSUME) == [
        (
            CreditEntryKind.CONSUME,
            CreditReason.ORDER_NOT_DELIVERED,
            0,
            0,
            f"consume:{first_order}:0",
        )
    ]
    await _assert_no_drift(sessions)


async def test_a_stale_debit_stops_counting_against_the_cap_after_the_grace(
    sessions: async_sessionmaker[AsyncSession], clock: MovableClock
) -> None:
    # Arrange — a worker that died without settling must not wedge its customer out forever.
    # The grace is a self-healing window, not a promise; WU6's sweep is what closes such a
    # debit properly and gives the credit back.
    ledger = _ledger(sessions, clock, policy=EntitlementPolicy(settlement_grace_s=60))
    await _charge(ledger, uuid4())

    # Act
    clock.advance(seconds=61)
    outcome, balance = await _charge(ledger, uuid4())

    # Assert
    assert outcome is ChargeOutcome.CHARGED
    assert balance.in_flight == 1
    assert await _stored_balance(sessions) == 1
    await _assert_no_drift(sessions)


# ---------------------------------------------------------------------------
# Settlement guards
# ---------------------------------------------------------------------------
async def test_a_refund_writes_nothing_when_the_order_holds_no_credit(
    sessions: async_sessionmaker[AsyncSession], clock: MovableClock
) -> None:
    # Arrange — a refund must never mint a credit that was never spent. Two ways in: an order
    # nobody charged, and an order whose refund has already happened.
    ledger = _ledger(sessions, clock)
    charged_order = uuid4()
    await _charge(ledger, charged_order)
    await _settle(ledger, charged_order, SettlementOutcome.FAILED)
    before = await _entries(sessions)

    # Act
    unknown = await _settle(ledger, uuid4(), SettlementOutcome.FAILED)
    again = await _settle(ledger, charged_order, SettlementOutcome.FAILED)

    # Assert
    assert unknown is False
    assert again is False
    assert await _entries(sessions) == before
    assert await _stored_balance(sessions) == 3
    await _assert_no_drift(sessions)


async def test_a_settlement_for_an_order_that_was_never_debited_writes_nothing(
    sessions: async_sessionmaker[AsyncSession], clock: MovableClock
) -> None:
    # Arrange — a consume for an unpaid order would make a never-charged order look like a
    # completed sale in the audit trail, and would free an in-flight slot nobody took.
    ledger = _ledger(sessions, clock)

    # Act
    settled = await _settle(ledger, uuid4(), SettlementOutcome.DELIVERED)

    # Assert
    assert settled is False
    assert await _entries(sessions) == []
    await _assert_no_drift(sessions)
