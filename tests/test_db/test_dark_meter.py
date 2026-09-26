"""What ``BAYRAM_CREDITS_ENFORCED=false`` actually means, at the layer that decides it.

This is the configuration that merges, so it is the one that has to be pinned. The flag used
to live on ``CreditGatedPaymentProvider``, which returned before it ever called the store —
and because that decorator is the ONLY caller of ``charge`` in the tree, the shipped
deployment wrote no DEBIT rows at all. Three things followed, none of them intended:

* ``credit_sql.count_in_flight`` counts unsettled debits, so ``CreditBalance.in_flight`` was
  permanently 0 and the one-song-at-a-time cap refused nobody — one account could hold
  unlimited concurrent renders, which is the queue-filling abuse the cap exists to stop;
* the worker's block check lives inside the same skipped call, so an account an operator
  blocked AFTER its job was queued rendered and shipped a full kit;
* every claim to the contrary — ``config.py``, the provider docstring, the locale comments —
  was false in the only configuration anyone runs.

The flag now sits on ``EntitlementPolicy.is_balance_enforced`` and reaches exactly one
branch: what a shortfall means. Everything else runs identically. Each test below is one
half of that sentence.
"""

from __future__ import annotations

from typing import Any, Final
from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from bayram.contracts import Err, Result, is_ok
from bayram.db.credit_sql import verify_balances
from bayram.db.credits import UNENFORCED_ACTOR, SqlCreditLedger
from bayram.db.enums import CreditReason
from bayram.entitlements import (
    ChargeOutcome,
    CreditBalance,
    EntitlementPolicy,
    InsufficientCreditsError,
    SettlementOutcome,
)
from bayram.errors import BayramError, ErrorCode, TooManyOrdersInFlightError, ValidationError
from tests.test_db.conftest import MovableClock

_USER: Final[int] = 8_912_345_670_001
_ACTOR: Final[str] = "pipeline"
#: No free allowance, so "this account has run out" is reachable without moving a month.
_DARK: Final[EntitlementPolicy] = EntitlementPolicy(allowance_credits=0, is_balance_enforced=False)
_ENFORCED: Final[EntitlementPolicy] = EntitlementPolicy(allowance_credits=0)


def _ledger(
    sessions: async_sessionmaker[AsyncSession],
    clock: MovableClock,
    *,
    policy: EntitlementPolicy,
) -> SqlCreditLedger:
    return SqlCreditLedger(sessions, clock=clock, policy=policy)


async def _reasons(sessions: async_sessionmaker[AsyncSession]) -> list[str]:
    """Every ledger row's reason, oldest first. Raw SQL — see Rule 15 in ``bayram/db``."""
    async with sessions() as session:
        rows = (
            await session.execute(
                sa.text("SELECT reason FROM credit_ledger ORDER BY created_at, idempotency_key")
            )
        ).all()
    return [str(row[0]) for row in rows]


async def _charge(
    ledger: SqlCreditLedger, order_id: UUID
) -> Result[tuple[ChargeOutcome, CreditBalance]]:
    return await ledger.charge(telegram_user_id=_USER, order_id=order_id, actor=_ACTOR)


def _refusal(result: Result[Any]) -> BayramError:
    """Assert a charge was refused and hand back the error the customer would have met."""
    assert isinstance(result, Err), f"expected a refusal, got {result!r}"
    return result.error


# ---------------------------------------------------------------------------
# What "dark" switches off — and what it does not
# ---------------------------------------------------------------------------
async def test_a_dark_meter_covers_an_empty_account_instead_of_refusing_it(
    sessions: async_sessionmaker[AsyncSession], clock: MovableClock
) -> None:
    """Nobody is turned away for having run out. That is the whole purpose of the flag.

    The cover is a GRANT of exactly what the render costs, so the balance ends where it
    started and ``credit_accounts.balance == SUM(credit_ledger.delta)`` — the invariant
    ``verify_balances`` polices — survives a dark render exactly as it survives an enforced
    one. Writing the debit and skipping the balance move would have broken it silently on
    every over-allowance render.
    """
    # Arrange
    ledger = _ledger(sessions, clock, policy=_DARK)

    # Act
    charged = await _charge(ledger, uuid4())

    # Assert
    assert is_ok(charged), charged
    assert await _reasons(sessions) == [
        CreditReason.ORDER_RENDER.value,
        CreditReason.UNENFORCED_RENDER.value,
    ]
    async with sessions() as session:
        assert await verify_balances(session) == ()


async def test_the_cover_grant_names_the_flag_so_an_operator_can_count_what_it_hid(
    sessions: async_sessionmaker[AsyncSession], clock: MovableClock
) -> None:
    """The measurement, not just the mercy.

    Counting ``unenforced_render`` rows says exactly how many renders enforcement would have
    refused — which is the number an operator needs before switching the flag on. It is also
    why the cover is a ledger row rather than a silent branch.
    """
    # Arrange
    ledger = _ledger(sessions, clock, policy=_DARK)

    # Act
    await _charge(ledger, uuid4())

    # Assert
    async with sessions() as session:
        actor = await session.scalar(
            sa.text("SELECT actor FROM credit_ledger WHERE reason = :reason"),
            {"reason": CreditReason.UNENFORCED_RENDER.value},
        )
    assert actor == UNENFORCED_ACTOR


async def test_an_enforced_meter_refuses_the_same_account_and_writes_nothing_at_all(
    sessions: async_sessionmaker[AsyncSession], clock: MovableClock
) -> None:
    """The mirror. One flag, one branch, and the refusal still leaves no trace behind it."""
    # Arrange
    ledger = _ledger(sessions, clock, policy=_ENFORCED)

    # Act
    charged = await _charge(ledger, uuid4())

    # Assert — the refusal rolls its whole transaction back, so there is no half-charge.
    assert isinstance(_refusal(charged), InsufficientCreditsError)
    assert await _reasons(sessions) == []


async def test_a_blocked_account_is_refused_even_while_the_meter_is_dark(
    sessions: async_sessionmaker[AsyncSession], clock: MovableClock
) -> None:
    """A block refuses ABUSE, so D-B says it enforces from the day it merges.

    It did not: the block check lives inside ``charge``, and the dark path never called it.
    An operator blocking an account mid-render still got the render.
    """
    # Arrange
    ledger = _ledger(sessions, clock, policy=_DARK)
    blocked = await ledger.set_blocked(_USER, is_blocked=True)
    assert is_ok(blocked), blocked

    # Act
    charged = await _charge(ledger, uuid4())

    # Assert
    assert _refusal(charged).error_code is ErrorCode.ACCOUNT_BLOCKED
    assert await _reasons(sessions) == []


async def test_the_in_flight_cap_refuses_a_second_render_even_while_the_meter_is_dark(
    sessions: async_sessionmaker[AsyncSession], clock: MovableClock
) -> None:
    """The cap counts the rows a dark charge now writes, which is why it can count at all."""
    # Arrange — one render charged and never settled, so its debit is open.
    ledger = _ledger(sessions, clock, policy=_DARK)
    await _charge(ledger, uuid4())

    # Act
    second = await _charge(ledger, uuid4())

    # Assert
    assert isinstance(_refusal(second), TooManyOrdersInFlightError)


async def test_a_dark_render_is_settled_like_any_other(
    sessions: async_sessionmaker[AsyncSession], clock: MovableClock
) -> None:
    """The debit is real, so the settlement is real — and the slot is genuinely released."""
    # Arrange
    ledger = _ledger(sessions, clock, policy=_DARK)
    order_id = uuid4()
    await _charge(ledger, order_id)

    # Act
    settled = await ledger.settle(
        telegram_user_id=_USER,
        order_id=order_id,
        outcome=SettlementOutcome.DELIVERED,
        actor=_ACTOR,
    )

    # Assert
    assert is_ok(settled), settled
    assert settled.value is True
    balance = await ledger.balance_for(_USER)
    assert is_ok(balance), balance
    assert balance.value.in_flight == 0


# ---------------------------------------------------------------------------
# The price
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("cost", [0, -1])
async def test_a_render_priced_at_nothing_is_refused_at_the_boundary(
    sessions: async_sessionmaker[AsyncSession], clock: MovableClock, cost: int
) -> None:
    """``cost=0`` used to reach ``ck_credit_ledger_delta_matches_kind`` and fail there.

    A DEBIT row is pinned to ``delta < 0``, so a zero price is a CHECK-constraint violation
    inside a customer's transaction rather than the "free tier" the constant's comment used
    to promise. A comped render is a ``grant``, not a zero-priced charge, and this says so in
    the same place ``grant`` refuses a non-positive credit.
    """
    # Arrange
    ledger = _ledger(sessions, clock, policy=_ENFORCED)

    # Act
    charged = await ledger.charge(telegram_user_id=_USER, order_id=uuid4(), actor=_ACTOR, cost=cost)

    # Assert
    assert isinstance(_refusal(charged), ValidationError)
    assert await _reasons(sessions) == []
