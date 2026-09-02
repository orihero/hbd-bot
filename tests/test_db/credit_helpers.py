"""Shared fixtures-in-function-form for the entitlement-ledger test modules.

Not a test module: it holds the constants and the four helpers that
``test_credits.py`` and ``test_credit_refusals.py`` both need, so that splitting the
original 890-line file across the repo's 800-line cap did not mean two copies of
``_assert_no_drift`` drifting apart. A ``*Row`` import is permitted here for the same
reason it is permitted in the rest of ``tests/test_db``: this package IS the persistence
layer's own test surface (Rule 15, ``hbd/db/__init__.py``).
"""

from __future__ import annotations

from typing import Final
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from hbd.contracts import is_ok
from hbd.db.credit_sql import verify_balances
from hbd.db.credits import SqlCreditLedger
from hbd.db.enums import CreditEntryKind, CreditReason
from hbd.db.models import CreditAccountRow, CreditLedgerRow, UserRow
from hbd.entitlements import (
    ChargeOutcome,
    CreditBalance,
    EntitlementPolicy,
    SettlementOutcome,
)
from tests.test_db.conftest import MovableClock

#: Outside the 32-bit range on purpose: every id here travels through the account primary
#: key, the ledger column and the ``users`` upsert, and a narrowed column anywhere on that
#: path would corrupt identity rather than fail loudly.
_USER: Final[int] = 8_912_345_678_901
#: A second account, so "this user's in-flight renders" cannot silently mean "anyone's".
_OTHER_USER: Final[int] = 7_112_345_678_902

_ACTOR: Final[str] = "pipeline"
_PERIOD_DAYS: Final[int] = 30

#: One ledger row, flattened to everything an assertion in this file cares about.
type Entry = tuple[CreditEntryKind, CreditReason, int, int, str]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _ledger(
    sessions: async_sessionmaker[AsyncSession],
    clock: MovableClock,
    *,
    policy: EntitlementPolicy | None = None,
) -> SqlCreditLedger:
    return SqlCreditLedger(sessions, clock=clock, policy=policy or EntitlementPolicy())


async def _assert_no_drift(sessions: async_sessionmaker[AsyncSession]) -> None:
    """The invariant. Called after every act in this module, never only at the end."""
    async with sessions() as session:
        assert await verify_balances(session) == ()


async def _entries(sessions: async_sessionmaker[AsyncSession]) -> list[Entry]:
    """Every ledger row as a comparable tuple, ordered so an assertion cannot be flaky.

    Rows written in one transaction share ``created_at`` to the microsecond, so the
    idempotency key — unique by construction — is the only stable sort.
    """
    async with sessions() as session:
        rows = (
            await session.execute(
                sa.select(CreditLedgerRow).order_by(CreditLedgerRow.idempotency_key)
            )
        ).scalars()
        return [
            (row.kind, row.reason, row.delta, row.generation, row.idempotency_key) for row in rows
        ]


def _of_kind(entries: list[Entry], kind: CreditEntryKind) -> list[Entry]:
    return [entry for entry in entries if entry[0] is kind]


async def _stored_balance(
    sessions: async_sessionmaker[AsyncSession], *, telegram_user_id: int = _USER
) -> int | None:
    """The account's own column, read fresh. ``None`` when no account row exists."""
    async with sessions() as session:
        # Annotated local rather than a bare return: ``scalar`` is typed ``Any``, and
        # ``--strict`` refuses to let that widen the declared ``int | None``.
        balance: int | None = await session.scalar(
            sa.select(CreditAccountRow.balance).where(
                CreditAccountRow.telegram_user_id == telegram_user_id
            )
        )
        return balance


async def _user_row(sessions: async_sessionmaker[AsyncSession]) -> UserRow | None:
    async with sessions() as session:
        return (
            await session.execute(sa.select(UserRow).where(UserRow.telegram_user_id == _USER))
        ).scalar_one_or_none()


async def _charge(
    ledger: SqlCreditLedger, order_id: UUID, *, telegram_user_id: int = _USER
) -> tuple[ChargeOutcome, CreditBalance]:
    """Charge and unwrap, for the many tests where a failure is not the thing under test."""
    result = await ledger.charge(telegram_user_id=telegram_user_id, order_id=order_id, actor=_ACTOR)
    assert is_ok(result), result
    return result.value


async def _settle(
    ledger: SqlCreditLedger,
    order_id: UUID,
    outcome: SettlementOutcome,
    *,
    telegram_user_id: int = _USER,
) -> bool:
    result = await ledger.settle(
        telegram_user_id=telegram_user_id, order_id=order_id, outcome=outcome, actor=_ACTOR
    )
    assert is_ok(result), result
    return result.value


def _grant_key(index: int, *, telegram_user_id: int = _USER) -> str:
    return f"grant:period:{telegram_user_id}:{index}"
