"""``PurchaseFulfiller`` over Postgres (or SQLite in tests): what a paid button writes.

The narrow write port the BOT process holds over the meter, and the whole reason it can be
held safely. The standing rule is that the bot may READ the meter and only the worker may
SPEND it, because a gate that could write could double-charge. Every method here is
ADDITIVE and IDEMPOTENT on a unique index, so nothing it does has anything to compensate if
the customer walks away: a grant that lands twice is one grant, whereas a charge that lands
twice is a stolen song and a settle that lands twice is a refund nobody asked for. Handing
the bot ``SqlCreditLedger`` would have handed it all three; this class exists so the rule
stays literally true with one stated, bounded exception. :class:`hbd.checkout.PurchaseFulfiller`
argues the same point from the protocol side.

Two purchases, two completely different writes, and the asymmetry is the design:

* **A single song writes ONE RECEIPT AND ONE CREDIT.** ``topup_purchases`` records what was
  sold — the amount, the currency, the rail and the rail's own reference — and the
  ``credit_ledger`` GRANT records the entitlement. Money already spent must never be lost to
  a clock, so the credit goes on the balance immediately as an ordinary, non-expiring one
  under ``CreditReason.TOPUP_PURCHASE``. Both rows are written in ONE transaction, stamped
  from ONE clock, under ONE ``idempotency_key``, and each is independently insert-or-ignore
  on its own unique index — which is what keeps the narrow-port invariant literally true
  while two statements carry it instead of one. :mod:`hbd.db.models.topup_purchase` argues
  why the money is a sibling receipt table and not four more columns on ``credit_ledger``.
* **A plan grants NOTHING and writes ONE ROW.** ``plan_purchases`` records what was bought,
  and songs leave it one at a time, lazily, inside the render debit's own transaction
  (:func:`hbd.db.credits._mint_plan_song`). An eager twelve-credit grant would need an expiry
  sweep writing a compensating DEBIT, and ``credit_accounts.balance`` is a single fungible
  scalar with no lot structure — so that sweep could only GUESS whether it was burning plan
  money or a top-up the customer paid cash for. :mod:`hbd.db.plan_sql` argues it at length.

Shape follows :class:`hbd.db.credits.SqlCreditLedger` exactly: built from an
``async_sessionmaker`` plus an injected clock, one ``async with self._sessions.begin()`` per
public method, every one of them wrapped in :func:`hbd.db.guard.run_guarded` so it returns
``Result`` and NEVER raises. A refusal raised inside that block rolls its whole transaction
back, which is how "an unpaid purchase leaves no row and no credit" is achieved without a
single compensating write.

**What this class is, now that :mod:`hbd.db.fulfilment` exists: a transaction, a clock, a
policy and a ``Result`` boundary — and nothing else.** The two sale-writing bodies moved out
verbatim, with both refusals travelling INSIDE them, because a redirect rail settles in a
different process and must write those same rows inside a transaction it opened itself for
its own reasons. What stayed is exactly what is specific to the BOT holding this port: the
session lifetime, the injected clock, the ``EntitlementPolicy`` the balance is projected
under, and the never-raise promise. The argument above — why the bot may hold this narrow
port at all when it may not hold ``SqlCreditLedger`` — is an argument about THIS class and
stays here; it does not follow the writes down, because a rail is not the bot and answers for
its own blast radius. ``CHECKOUT_ACTOR`` is re-exported below so the name every existing
caller and test imports from here keeps resolving.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from hbd.checkout import Plan, PlanState, Purchase
from hbd.contracts import Result
from hbd.db.base import utc_now
from hbd.db.credit_sql import read_balance
from hbd.db.fulfilment import CHECKOUT_ACTOR, write_plan_sale, write_single_sale
from hbd.db.guard import run_guarded
from hbd.db.models.plan_purchase import PlanPurchaseRow
from hbd.db.plan_sql import current_plan
from hbd.entitlements import DEFAULT_ENTITLEMENT_POLICY, CreditBalance, EntitlementPolicy

__all__ = ["SqlPurchaseLedger", "CHECKOUT_ACTOR"]


def _plan_state(row: PlanPurchaseRow) -> PlanState:
    """The frozen view of one plan row. A ``*Row`` never leaves this package (Rule 15).

    ``PlanKind`` and :class:`hbd.checkout.Plan` are separate enums that mirror each other
    value for value — persistence does not put an application type in a mapped column — so
    this is where one becomes the other, in the single place a plan row crosses the boundary.
    """
    return PlanState(
        plan=Plan(row.plan.value),
        songs_included=row.songs_included,
        songs_used=row.songs_used,
        ends_at=row.plan_ends_at,
    )


class SqlPurchaseLedger:
    """What a paid button writes. Never raises, never grants for a purchase that is not paid.

    Structural implementation of :class:`hbd.checkout.PurchaseFulfiller`, not a subclass: the
    protocol is ``@runtime_checkable`` and satisfied structurally, so persistence does not
    import an ABC to be substitutable — the same shape ``SqlCreditLedger`` uses for
    ``EntitlementStore``.

    The ``policy`` is carried for one reason only: :func:`hbd.db.credit_sql.read_balance`
    projects a due allowance and a live plan's unminted songs, and it can only do that
    correctly against the policy the WORKER will charge under. A store that defaulted the
    policy here while the worker ran on a configured one would hand the customer a balance
    the render gate then disagreed with, which is the exact class of defect ``read_balance``
    exists to prevent.
    """

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        *,
        policy: EntitlementPolicy = DEFAULT_ENTITLEMENT_POLICY,
        clock: Callable[[], datetime] = utc_now,
    ) -> None:
        self._sessions = session_factory
        self._policy = policy
        self._clock = clock

    # -- PurchaseFulfiller --------------------------------------------------
    async def fulfil_single(
        self, *, telegram_user_id: int, purchase: Purchase, idempotency_key: str
    ) -> Result[CreditBalance]:
        return await run_guarded(
            "purchases.fulfil_single",
            lambda: self._fulfil_single(telegram_user_id, purchase, idempotency_key),
            telegram_user_id=telegram_user_id,
            reference=purchase.reference,
        )

    async def start_plan(
        self,
        *,
        telegram_user_id: int,
        purchase: Purchase,
        songs: int,
        days: int,
        idempotency_key: str,
    ) -> Result[PlanState]:
        return await run_guarded(
            "purchases.start_plan",
            lambda: self._start_plan(telegram_user_id, purchase, songs, days, idempotency_key),
            telegram_user_id=telegram_user_id,
            reference=purchase.reference,
        )

    async def plan_for(self, telegram_user_id: int) -> Result[PlanState | None]:
        return await run_guarded(
            "purchases.plan_for",
            lambda: self._plan_for(telegram_user_id),
            telegram_user_id=telegram_user_id,
        )

    # -- implementations ----------------------------------------------------
    async def _fulfil_single(
        self, telegram_user_id: int, purchase: Purchase, idempotency_key: str
    ) -> CreditBalance:
        """One transaction, one clock, and the balance the customer is shown afterwards.

        The sale itself — the receipt, the grant, and the two refusals that guard them — is
        :func:`hbd.db.fulfilment.write_single_sale`, which every rail shares. What is left
        here is what only the bot needs: the transaction the write lands in, the injected
        clock that stamps both rows, and the read-back of the balance.

        **The balance read is INSIDE the same transaction and after the writes**, so the
        number put on the customer's screen is the one the sale just produced rather than a
        second, later truth. It is also why this method carries an
        :class:`hbd.entitlements.EntitlementPolicy` and ``write_single_sale`` does not:
        :func:`hbd.db.credit_sql.read_balance` projects a due allowance and a live plan's
        unminted songs against the policy the WORKER will charge under, so a store that
        defaulted it here would show a balance the render gate then disagreed with.

        A replayed key writes NEITHER row and the UNCHANGED balance is returned, which is the
        correct answer to a double tap: nothing went wrong, and the customer has exactly what
        they paid for. That falls out of the extracted write being insert-or-ignore on each of
        its own unique indexes; nothing here has to detect the replay to answer it correctly.
        """
        now = self._clock()
        async with self._sessions.begin() as session:
            await write_single_sale(
                session,
                telegram_user_id=telegram_user_id,
                purchase=purchase,
                idempotency_key=idempotency_key,
                now=now,
            )
            return await read_balance(
                session, telegram_user_id=telegram_user_id, now=now, policy=self._policy
            )

    async def _start_plan(
        self,
        telegram_user_id: int,
        purchase: Purchase,
        songs: int,
        days: int,
        idempotency_key: str,
    ) -> PlanState:
        """Open a plan, or hand back the one already running, and describe it to a screen.

        The sale is :func:`hbd.db.fulfilment.write_plan_sale`, which every rail shares and
        which carries the one-plan-at-a-time rule with it. What is left here is the
        transaction, the clock, and the one thing only this caller wants: turning the row
        into the frozen :class:`hbd.checkout.PlanState` a bot screen is drawn from, which is
        also the boundary a ``*Row`` may not cross (Rule 15).
        """
        now = self._clock()
        async with self._sessions.begin() as session:
            row = await write_plan_sale(
                session,
                telegram_user_id=telegram_user_id,
                purchase=purchase,
                songs=songs,
                days=days,
                idempotency_key=idempotency_key,
                now=now,
            )
            return _plan_state(row)

    async def _plan_for(self, telegram_user_id: int) -> PlanState | None:
        async with self._sessions.begin() as session:
            row = await current_plan(session, telegram_user_id=telegram_user_id, now=self._clock())
            return None if row is None else _plan_state(row)
