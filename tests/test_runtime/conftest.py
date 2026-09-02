"""Fixtures and fakes shared by the runtime tests.

The one thing that lives here rather than in a test module is
:class:`RecordingEntitlementStore`. Three modules need the same fake — ``test_jobs`` builds
a container with it, ``test_payments`` drives the render gate through it, and the settlement
tests assert what the worker wrote through it — and a fake that exists in three copies is a
fake that drifts in two of them.

It is a *working* store, not a stub: it keeps a balance, refuses when the balance is spent,
and is idempotent per order in exactly the way the real ledger is (by net position, not by
row presence). That matters because the point of handing it to ``_Container`` is that the
worker's settlement paths can be exercised against something that can actually tell a
double-settle from a first one — a ``None`` there made every one of those paths untestable.

The ``session``/``bot`` pair moved up here for the same reason: ``test_jobs`` and
``test_settlement`` drive the SAME job function through the SAME recording transport, and
two module-local copies of a bot fixture is two places to forget ``parse_mode`` in.
"""

from __future__ import annotations

from uuid import UUID

import pytest
from aiogram import Bot
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

from hbd.contracts import Language, Result, err, ok
from hbd.entitlements import (
    ChargeOutcome,
    CreditBalance,
    EntitlementError,
    InsufficientCreditsError,
    SettlementOutcome,
)
from hbd.errors import HbdError
from tests.test_bot.conftest import BOT_TOKEN, RecordingSession

__all__ = ["RecordingEntitlementStore", "Movement"]


@pytest.fixture
def session() -> RecordingSession:
    return RecordingSession()


@pytest.fixture
def bot(session: RecordingSession) -> Bot:
    """A bot whose every call is recorded rather than sent.

    ``parse_mode=HTML`` is not decoration: the delivery captions and every locale string
    are written as HTML, so a bot built without it renders tags as literal text and a test
    comparing against ``translate(...)`` passes while production shows markup.
    """
    return Bot(
        token=BOT_TOKEN, session=session, default=DefaultBotProperties(parse_mode=ParseMode.HTML)
    )


#: One thing that happened to the ledger, in the order it happened. A tuple rather than a
#: model because every assertion on it is an equality against a literal, and a literal is
#: the most legible form of "exactly one CONSUME, and it was for this order".
type Movement = tuple[str, UUID | None, int]


class RecordingEntitlementStore:
    """In-memory ``hbd.entitlements.EntitlementStore``. Never raises, never touches a DB.

    ``runtime_checkable`` verifies member PRESENCE only, so an ``isinstance`` assertion will
    happily accept this class after the protocol has drifted away from it. ``mypy --strict``
    over ``tests`` is what actually keeps the two in step — which is why the container field
    it is assigned to is typed and not ``Any``.
    """

    def __init__(self, *, credits: int = 3, is_blocked: bool = False) -> None:
        self.credits = credits
        self.is_blocked = is_blocked
        #: Set to make ``charge`` fail with something that is NOT a business refusal — a
        #: database outage, which is retryable. The distinction is what the ARQ ladder reads
        #: off ``Err.is_retryable``, so a test that only ever sees an entitlement refusal
        #: cannot prove the gate stopped second-guessing it.
        self.charge_failure: HbdError | None = None
        #: Every write, in order: ("debit"|"refund"|"consume"|"grant", order_id, delta).
        self.movements: list[Movement] = []
        #: Net position per order, which is what decides replay in the real ledger too.
        self._net: dict[UUID, int] = {}
        self._settled: set[UUID] = set()
        self.touched: list[tuple[int, Language]] = []
        self.blocked: list[tuple[int, bool]] = []
        #: Every account this store was asked to erase.
        self.forgotten: list[int] = []

    # -- EntitlementStore ---------------------------------------------------
    async def charge(
        self, *, telegram_user_id: int, order_id: UUID, actor: str, cost: int = 1
    ) -> Result[tuple[ChargeOutcome, CreditBalance]]:
        if self.charge_failure is not None:
            return err(self.charge_failure)
        if self._net.get(order_id, 0) < 0:
            return ok((ChargeOutcome.ALREADY_PAID, self._balance(telegram_user_id)))
        if self.is_blocked:
            # The BASE class, not the out-of-credits subclass: a block is the one
            # entitlement refusal with no number attached, and it renders "error.blocked".
            return err(
                EntitlementError(
                    "the fake store refused a blocked account",
                    context={"telegram_user_id": telegram_user_id},
                )
            )
        if self.credits < cost:
            return err(
                InsufficientCreditsError(
                    "the fake store has nothing left to spend",
                    context={
                        "telegram_user_id": telegram_user_id,
                        "balance": self.credits,
                        "needed": cost,
                    },
                )
            )
        self.credits -= cost
        self._net[order_id] = self._net.get(order_id, 0) - cost
        self.movements.append(("debit", order_id, -cost))
        return ok((ChargeOutcome.CHARGED, self._balance(telegram_user_id)))

    async def settle(
        self, *, telegram_user_id: int, order_id: UUID, outcome: SettlementOutcome, actor: str
    ) -> Result[bool]:
        # Both halves of "writes nothing" are real answers, not failures: an order that was
        # never debited must never mint a credit, and a redelivered job must not settle
        # twice. Ok(False) is how the real store says so, so this says it the same way.
        if self._net.get(order_id, 0) >= 0 or order_id in self._settled:
            return ok(False)
        self._settled.add(order_id)
        if outcome is SettlementOutcome.FAILED:
            self.credits += 1
            self._net[order_id] = 0
            self.movements.append(("refund", order_id, 1))
            return ok(True)
        self.movements.append(("consume", order_id, 0))
        return ok(True)

    async def grant(
        self, *, telegram_user_id: int, credits: int, idempotency_key: str, actor: str
    ) -> Result[CreditBalance]:
        self.credits += credits
        self.movements.append(("grant", None, credits))
        return ok(self._balance(telegram_user_id))

    async def balance_for(
        self, telegram_user_id: int, *, exclude_order_id: UUID | None = None
    ) -> Result[CreditBalance]:
        return ok(self._balance(telegram_user_id, exclude_order_id=exclude_order_id))

    async def set_blocked(self, telegram_user_id: int, *, is_blocked: bool) -> Result[None]:
        self.is_blocked = is_blocked
        self.blocked.append((telegram_user_id, is_blocked))
        return ok(None)

    async def touch(self, telegram_user_id: int, *, ui_language: Language) -> Result[None]:
        self.touched.append((telegram_user_id, ui_language))
        return ok(None)

    async def forget(self, telegram_user_id: int) -> Result[None]:
        """The erasure, modelled the way the real store behaves: the balance goes, the
        history stays. ``movements`` is deliberately NOT cleared — that list is this fake's
        stand-in for the append-only ledger, and a fake that dropped it would let a worker
        test pass while the real ``/forget`` destroyed the audit trail."""
        self.forgotten.append(telegram_user_id)
        self.credits = 0
        return ok(None)

    # -- helpers for the tests ----------------------------------------------
    def _balance(
        self, telegram_user_id: int, *, exclude_order_id: UUID | None = None
    ) -> CreditBalance:
        in_flight = sum(
            1
            for order_id, net in self._net.items()
            if net < 0 and order_id not in self._settled and order_id != exclude_order_id
        )
        return CreditBalance(
            telegram_user_id=telegram_user_id,
            credits=self.credits,
            in_flight=in_flight,
            is_blocked=self.is_blocked,
        )

    def kinds_for(self, order_id: UUID) -> list[str]:
        """Every movement recorded against one order, in order. The settlement assertion."""
        return [kind for kind, recorded, _ in self.movements if recorded == order_id]
