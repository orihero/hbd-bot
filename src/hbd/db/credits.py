"""The entitlement operations: mint, charge, grant, block, touch, forget — and the facade.

Two shapes live here on purpose, and the split is the same one ``hbd.db.admin`` makes:

* **Module-level functions take an ``AsyncSession`` first, take ``now`` as a parameter, let
  exceptions propagate and never commit.** They are the composable half: WU6's stale-debit
  sweep has to run inside ``purge_expired``'s existing transaction, and a function that
  opened its own would either nest a transaction or commit half a purge.
* **:class:`SqlCreditLedger` is the never-throw facade** in the ``SqlKitRepository`` idiom —
  one ``run_guarded`` delegation per method, each owning exactly one
  ``async with self._sessions.begin()``. A refusal raised inside that block rolls the whole
  transaction back, which is precisely how "an insufficient balance leaves NO ledger row and
  NO balance movement" is achieved without a single compensating write.

The statements themselves live in :mod:`hbd.db.credit_sql`, the two-statement erasure
``/forget`` runs in :mod:`hbd.db.credit_erasure` (its asymmetry — delete the balance, keep
the count anonymous — is argued there), and everything that CLOSES a debit — ``settle``,
``refund``, ``consume`` and the hourly sweep — is in :mod:`hbd.db.credit_settlement`, split
off on that seam to keep both files under the repo's line cap and re-exported here so a
caller still sees one module. What follows is the policy for deciding whether to charge.

**Why ``charge`` looks the way it does.** Every step was chosen against a failure mode that
was reproduced rather than imagined:

1. *Open the account with a dialect-dispatched ``INSERT … ON CONFLICT DO NOTHING``, never
   ``session.begin_nested()``.* A SAVEPOINT taken as the FIRST statement of a transaction —
   exactly the shape of a first charge — does not roll back on ``aiosqlite`` while it does
   on Postgres.
2. *Decide replay from the order's NET position (``SUM(delta) WHERE order_id``), not from
   the presence of a debit row.* Net < 0 means "currently paid for" — the bot/worker pair
   and every ARQ retry converge on one charge. Net == 0 means unpaid, INCLUDING an order
   that was charged and then refunded, which must be chargeable again at the next
   generation. Keying replay on "was this order ever debited" renders every
   refunded-then-reauthorised order for free; that is the single sharpest defect this module
   exists to avoid, and ``tests/test_db/test_credits.py`` pins it.
3. *Move the balance with a conditional ``UPDATE`` and a rowcount check* — see
   ``credit_sql.debit_balance``. The balance is deliberately NOT pre-checked with a
   ``SELECT``: a read-then-write is the very race the predicate removes.
4. *Derive the in-flight count from unsettled ledger debits, not from ``orders.state``.*
   ``orchestrator._fail`` writes ``FAILED`` on retryable failures too, so an order sitting in
   ARQ backoff is invisible to a state predicate and a user can stack a second render.

``credit_accounts.balance`` is a second representation of ``SUM(credit_ledger.delta)``. Both
writes always happen in one transaction, and ``verify_balances`` exists because that makes
drift *detectable* rather than impossible — an operator's hand-written ``UPDATE`` can still
desynchronise them.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from typing import Final
from uuid import UUID, uuid4

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from hbd.contracts import Language, Result
from hbd.db.base import utc_now
from hbd.db.credit_erasure import forget_account
from hbd.db.credit_settlement import (
    SWEEP_ACTOR,
    consume,
    refund,
    settle,
    settle_stale_debits,
)
from hbd.db.credit_sql import (
    account_state,
    add_credits,
    debit_balance,
    generation_for,
    net_position,
    open_account,
    period_grant_key,
    read_balance,
    upsert_statement,
    write_entry,
)
from hbd.db.enums import CreditEntryKind, CreditReason
from hbd.db.guard import run_guarded
from hbd.db.models.user import UserRow
from hbd.entitlements import (
    DEFAULT_ENTITLEMENT_POLICY,
    ChargeOutcome,
    CreditBalance,
    EntitlementError,
    EntitlementPolicy,
    InsufficientCreditsError,
    SettlementOutcome,
    TooManyOrdersInFlightError,
    period_index_for,
    period_start,
)
from hbd.errors import StorageError, ValidationError
from hbd.logging import get_logger

#: ``settle``, ``refund``, ``consume`` and the sweep live in :mod:`hbd.db.credit_settlement`
#: and are re-exported here, because "the entitlement operations" is one seam to a caller
#: even though the file had to be two to stay under the line cap.
__all__ = [
    "SqlCreditLedger",
    "charge",
    "settle",
    "settle_stale_debits",
    "refund",
    "consume",
    "grant",
    "set_blocked",
    "touch",
    "DEFAULT_COST",
    "SWEEP_ACTOR",
    "UNENFORCED_ACTOR",
]

_log = get_logger(__name__)

#: One render costs one credit. A parameter rather than a literal because the operator CLI
#: and a future paid tier will price differently. It must be at least 1: a DEBIT row is
#: pinned by ``ck_credit_ledger_delta_matches_kind`` to ``delta < 0``, so ``cost=0`` writes
#: ``delta = 0`` and fails that CHECK inside the customer's transaction. :func:`charge`
#: refuses it at the boundary instead, the way :func:`grant` already refuses a non-positive
#: grant — a comped render is a grant, not a zero-priced charge.
DEFAULT_COST: Final[int] = 1

#: Who signs the shortfall grant a dark deployment writes so that nobody is refused for
#: having run out. Not an operator and not the pipeline: a configuration flag did this, and
#: the audit trail should say so in one word.
UNENFORCED_ACTOR: Final[str] = "unenforced"


async def _mint_due_allowance(
    session: AsyncSession, *, telegram_user_id: int, now: datetime, policy: EntitlementPolicy
) -> bool:
    """Mint this window's allowance unless it has already been minted. ``True`` when minted.

    Idempotent on ``grant:period:{telegram_user_id}:{index}``: the unique index on
    ``credit_ledger.idempotency_key`` is the sole authority, so two racing charges produce
    one grant and one loser even though both read the same account state a moment earlier.
    The account's ``allowance_period_index`` is advanced in the SAME statement that moves
    the balance, so the two can never disagree about which window was paid for.

    The window comparison is ``<``, not ``!=``: a clock that jumped backwards must not mint
    a second allowance for a window this account has already been paid for.

    An allowance of zero — how an operator closes the free tier without touching code —
    writes nothing at all rather than a zero-delta GRANT. The delta constraint on
    ``credit_ledger`` reserves ``delta == 0`` for CONSUME alone, and an empty grant is not a
    movement anyone should have to read past in an audit trail.
    """
    if policy.allowance_credits < 1:
        return False
    _, minted_index = await account_state(session, telegram_user_id)
    index = period_index_for(now, period_days=policy.allowance_period_days)
    if minted_index is not None and minted_index >= index:
        return False
    is_first_ever = minted_index is None
    if not await write_entry(
        session,
        telegram_user_id=telegram_user_id,
        kind=CreditEntryKind.GRANT,
        reason=(CreditReason.SIGNUP_ALLOWANCE if is_first_ever else CreditReason.PERIOD_ALLOWANCE),
        delta=policy.allowance_credits,
        idempotency_key=period_grant_key(telegram_user_id, index),
        actor="allowance",
        now=now,
    ):
        return False
    await add_credits(
        session,
        telegram_user_id=telegram_user_id,
        credits=policy.allowance_credits,
        lifetime=policy.allowance_credits,
        now=now,
        period_index=index,
    )
    return True


async def charge(
    session: AsyncSession,
    *,
    telegram_user_id: int,
    order_id: UUID,
    actor: str,
    now: datetime,
    cost: int = DEFAULT_COST,
    policy: EntitlementPolicy = DEFAULT_ENTITLEMENT_POLICY,
) -> tuple[ChargeOutcome, CreditBalance]:
    """Pay for ``order_id`` exactly once. See the module docstring for why each step exists.

    Raises an :class:`EntitlementError` subclass on refusal, which the caller's transaction
    boundary turns into a full rollback — so a refused charge leaves no account row it just
    opened, no allowance it just minted and no debit it just wrote.

    ``state`` is read once, with this order left out of its own in-flight count, and reused
    by both refusals. Its BALANCE never decides affordability — that is the conditional
    UPDATE's job — it only explains the refusal to the customer.

    **Every step below runs whether or not ``policy.is_balance_enforced`` is set.** The flag
    reaches exactly one branch: the shortfall at the very end. That is the narrowest reading
    of "the balance check ships dark", and it is the only one that works, because the
    in-flight cap counts unsettled DEBIT rows — a dark mode that skipped this function
    wrote none, so the cap and the block gate silently did nothing in the configuration that
    ships. See ``EntitlementPolicy.is_balance_enforced``.
    """
    if cost < 1:
        raise ValidationError(
            "a render must cost at least one credit",
            context={"telegram_user_id": telegram_user_id, "cost": cost},
        )
    await open_account(session, telegram_user_id=telegram_user_id, now=now)
    await _mint_due_allowance(session, telegram_user_id=telegram_user_id, now=now, policy=policy)
    state = await read_balance(
        session,
        telegram_user_id=telegram_user_id,
        now=now,
        policy=policy,
        exclude_order_id=order_id,
    )
    _refuse_a_blocked_account(state, order_id=order_id)
    if await net_position(session, order_id) < 0:
        return ChargeOutcome.ALREADY_PAID, await _snapshot(session, state, now=now, policy=policy)
    _refuse_a_stacked_account(state, policy=policy)
    generation = await generation_for(session, order_id)
    if not await _write_debit(
        session,
        telegram_user_id=telegram_user_id,
        order_id=order_id,
        generation=generation,
        cost=cost,
        actor=actor,
        now=now,
    ):
        # Another writer took this exact debit while we were deciding. It owns the balance
        # move; charging again here is the double-charge the unique index exists to stop.
        return ChargeOutcome.ALREADY_PAID, await _snapshot(session, state, now=now, policy=policy)
    if not await debit_balance(session, telegram_user_id=telegram_user_id, cost=cost, now=now):
        if policy.is_balance_enforced:
            raise _insufficient_credits(state, cost=cost, now=now, policy=policy)
        await _cover_the_shortfall(
            session,
            telegram_user_id=telegram_user_id,
            order_id=order_id,
            generation=generation,
            cost=cost,
            now=now,
        )
    return ChargeOutcome.CHARGED, await _snapshot(session, state, now=now, policy=policy)


async def _snapshot(
    session: AsyncSession, state: CreditBalance, *, now: datetime, policy: EntitlementPolicy
) -> CreditBalance:
    """Re-read the account after a charge decision, counting every order including this one.

    A fresh read rather than arithmetic on ``state``: the returned balance is what a customer
    is shown, and deriving it would make the display right only for as long as nobody adds a
    second write to the transaction.
    """
    return await read_balance(
        session, telegram_user_id=state.telegram_user_id, now=now, policy=policy
    )


def _refuse_a_blocked_account(state: CreditBalance, *, order_id: UUID) -> None:
    """A barred account may not render, however many credits it is holding."""
    if state.is_blocked:
        raise EntitlementError(
            "blocked account attempted a render",
            context={"telegram_user_id": state.telegram_user_id, "order_id": str(order_id)},
        )


def _refuse_a_stacked_account(state: CreditBalance, *, policy: EntitlementPolicy) -> None:
    """One render at a time. The cap refuses abuse, not customers, so it is never flagged off.

    ``charge`` calls this AFTER its replay probe on purpose: an order that is already paid
    for must stay replayable even when the account is at its cap, or the worker would fail a
    render the customer has already been charged for.
    """
    if state.in_flight >= policy.max_orders_in_flight:
        raise TooManyOrdersInFlightError(
            "account already has an unsettled render",
            context={
                "telegram_user_id": state.telegram_user_id,
                "in_flight": state.in_flight,
                "limit": policy.max_orders_in_flight,
            },
        )


def _insufficient_credits(
    state: CreditBalance, *, cost: int, now: datetime, policy: EntitlementPolicy
) -> InsufficientCreditsError:
    """The refusal, with the three scalars the locale string needs to be worth reading.

    ``next_grant_at`` is what makes the copy actionable: the allowance is rolling, so there
    is a real date on which this customer can render again. ``balance`` is the snapshot taken
    before the failed UPDATE, which under a lost race is one credit stale — the number is
    explanatory context, never the decision.
    """
    index = period_index_for(now, period_days=policy.allowance_period_days)
    return InsufficientCreditsError(
        "account cannot afford this render",
        context={
            "telegram_user_id": state.telegram_user_id,
            "balance": state.credits,
            "needed": cost,
            "next_grant_at": period_start(
                index + 1, period_days=policy.allowance_period_days
            ).isoformat(),
        },
    )


async def _cover_the_shortfall(
    session: AsyncSession,
    *,
    telegram_user_id: int,
    order_id: UUID,
    generation: int,
    cost: int,
    now: datetime,
) -> None:
    """Grant exactly what this render costs, so a dark deployment refuses nobody.

    Reached only when ``policy.is_balance_enforced`` is False and the account could not
    afford the debit that has just been written. Two things are true and both matter:

    * the balance ends where it started (a grant of ``cost`` followed by a debit of
      ``cost``), so ``credit_accounts.balance == SUM(credit_ledger.delta)`` — the invariant
      ``verify_balances`` exists to police — survives a dark render exactly as it survives
      an enforced one. Writing the debit and *skipping* the balance move would have broken
      it silently on every over-allowance render;
    * ``lifetime_granted`` is NOT moved. It answers "has this account been comped?", and a
      deployment-wide flag being off is not a comp.

    The grant is KEYED on the render's ``(order, generation)`` so that a replay writes one
    row, but it deliberately carries no ``order_id`` COLUMN. That column is what
    ``net_position`` sums, and an order whose grant and debit both hung off it would net to
    zero — which reads as "never paid for" everywhere it matters: ``charge`` would debit the
    same order a second time on its next attempt, and ``settle`` would find nothing to close
    and leave the in-flight slot held until the grace expired. The top-up belongs to the
    ACCOUNT, not to the render, and the ledger has to say so.

    It is also the only row that names the flag — an operator counting ``unenforced_render``
    sees precisely how many renders enforcement would have refused.

    A second failed debit is impossible (this transaction is the only writer that has
    touched the row, and the grant it just made covers the cost exactly), so it is reported
    as a storage fault rather than swallowed into a free render nobody can see.
    """
    _log.warning(
        "the balance check is dark: covering a render this account could not afford",
        extra={
            "telegram_user_id": telegram_user_id,
            "order_id": str(order_id),
            "cost": cost,
        },
    )
    await write_entry(
        session,
        telegram_user_id=telegram_user_id,
        kind=CreditEntryKind.GRANT,
        reason=CreditReason.UNENFORCED_RENDER,
        delta=cost,
        idempotency_key=f"unenforced:{order_id}:{generation}",
        actor=UNENFORCED_ACTOR,
        now=now,
    )
    await add_credits(session, telegram_user_id=telegram_user_id, credits=cost, lifetime=0, now=now)
    if not await debit_balance(session, telegram_user_id=telegram_user_id, cost=cost, now=now):
        raise StorageError(
            "the covered balance still could not pay for the render",
            context={"telegram_user_id": telegram_user_id, "order_id": str(order_id)},
        )


async def _write_debit(
    session: AsyncSession,
    *,
    telegram_user_id: int,
    order_id: UUID,
    generation: int,
    cost: int,
    actor: str,
    now: datetime,
) -> bool:
    """Append the debit entry. ``False`` means a concurrent writer got there first."""
    return await write_entry(
        session,
        telegram_user_id=telegram_user_id,
        kind=CreditEntryKind.DEBIT,
        reason=CreditReason.ORDER_RENDER,
        delta=-cost,
        idempotency_key=f"debit:{order_id}:{generation}",
        actor=actor,
        now=now,
        order_id=order_id,
        generation=generation,
    )


async def grant(
    session: AsyncSession,
    *,
    telegram_user_id: int,
    credits: int,
    idempotency_key: str,
    actor: str,
    now: datetime,
    reason: CreditReason = CreditReason.ADMIN_GRANT,
) -> bool:
    """Add credits on an operator's say-so. ``True`` when this call wrote the grant.

    The key belongs to the caller so a CLI run retried after a timeout tops the account up
    once. A non-positive grant is rejected at the boundary rather than left to
    ``ck_credit_ledger_delta_matches_kind``, so the operator gets a message about their
    input instead of a constraint name.
    """
    if credits < 1:
        raise ValidationError(
            "a grant must add at least one credit",
            context={"telegram_user_id": telegram_user_id, "credits": credits},
        )
    await open_account(session, telegram_user_id=telegram_user_id, now=now)
    if not await write_entry(
        session,
        telegram_user_id=telegram_user_id,
        kind=CreditEntryKind.GRANT,
        reason=reason,
        delta=credits,
        idempotency_key=idempotency_key,
        actor=actor,
        now=now,
    ):
        return False
    await add_credits(
        session, telegram_user_id=telegram_user_id, credits=credits, lifetime=credits, now=now
    )
    return True


async def set_blocked(
    session: AsyncSession, *, telegram_user_id: int, is_blocked: bool, now: datetime
) -> None:
    """Bar or unbar an account, creating its ``users`` row if there is none.

    An UPSERT rather than an ``UPDATE`` with a rowcount check, because ``users`` rows are
    written only by ``repository._ensure_user`` when an order is created — so the accounts
    most worth blocking (someone abusing the wizard without ever confirming) are precisely
    the ones an ``UPDATE`` would silently miss. ``ui_language`` is only supplied for the
    insert; blocking someone must never change the language they read.
    """
    await session.execute(
        upsert_statement(
            session,
            UserRow,
            {
                "id": uuid4(),
                "telegram_user_id": telegram_user_id,
                "ui_language": Language.UZ_LATN,
                "is_blocked": is_blocked,
                "last_seen_at": now,
                "created_at": now,
                "updated_at": now,
            },
            index_elements=["telegram_user_id"],
            set_={"is_blocked": is_blocked, "updated_at": now},
        )
    )


async def touch(
    session: AsyncSession, *, telegram_user_id: int, ui_language: Language, now: datetime
) -> None:
    """Record that this account is alive and which language it is reading.

    ``is_blocked`` is deliberately absent from the update clause: a touch arrives on every
    inbound update, and one that reset the flag would unblock an abuser the moment they
    sent their next message.
    """
    await session.execute(
        upsert_statement(
            session,
            UserRow,
            {
                "id": uuid4(),
                "telegram_user_id": telegram_user_id,
                "ui_language": ui_language,
                "is_blocked": False,
                "last_seen_at": now,
                "created_at": now,
                "updated_at": now,
            },
            index_elements=["telegram_user_id"],
            set_={"ui_language": ui_language, "last_seen_at": now, "updated_at": now},
        )
    )


class SqlCreditLedger:
    """``EntitlementStore`` over Postgres (or SQLite in tests). Never raises, never leaks a row.

    Structural implementation, not a subclass: the protocol is ``@runtime_checkable`` and
    satisfied structurally, so persistence does not import an ABC to be substitutable.

    One transaction per public method, opened here and nowhere else. Every refusal raised
    by the functions above therefore rolls its whole transaction back before ``run_guarded``
    converts it into an ``Err``, which is what makes "no ledger row, no balance movement"
    true without a single compensating write.
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

    @property
    def policy(self) -> EntitlementPolicy:
        """The numbers this store enforces. Read-only: a policy is injected, never edited."""
        return self._policy

    # -- EntitlementStore ---------------------------------------------------
    async def charge(
        self, *, telegram_user_id: int, order_id: UUID, actor: str, cost: int = DEFAULT_COST
    ) -> Result[tuple[ChargeOutcome, CreditBalance]]:
        return await run_guarded(
            "credits.charge",
            lambda: self._charge(telegram_user_id, order_id, actor, cost),
            telegram_user_id=telegram_user_id,
            order_id=str(order_id),
        )

    async def settle(
        self, *, telegram_user_id: int, order_id: UUID, outcome: SettlementOutcome, actor: str
    ) -> Result[bool]:
        return await run_guarded(
            "credits.settle",
            lambda: self._settle(telegram_user_id, order_id, outcome, actor),
            telegram_user_id=telegram_user_id,
            order_id=str(order_id),
            outcome=str(outcome),
        )

    async def grant(
        self, *, telegram_user_id: int, credits: int, idempotency_key: str, actor: str
    ) -> Result[CreditBalance]:
        return await run_guarded(
            "credits.grant",
            lambda: self._grant(telegram_user_id, credits, idempotency_key, actor),
            telegram_user_id=telegram_user_id,
            credits=credits,
        )

    async def balance_for(
        self, telegram_user_id: int, *, exclude_order_id: UUID | None = None
    ) -> Result[CreditBalance]:
        return await run_guarded(
            "credits.balance_for",
            lambda: self._balance_for(telegram_user_id, exclude_order_id),
            telegram_user_id=telegram_user_id,
        )

    async def set_blocked(self, telegram_user_id: int, *, is_blocked: bool) -> Result[None]:
        return await run_guarded(
            "credits.set_blocked",
            lambda: self._set_blocked(telegram_user_id, is_blocked),
            telegram_user_id=telegram_user_id,
            is_blocked=is_blocked,
        )

    async def touch(self, telegram_user_id: int, *, ui_language: Language) -> Result[None]:
        return await run_guarded(
            "credits.touch",
            lambda: self._touch(telegram_user_id, ui_language),
            telegram_user_id=telegram_user_id,
        )

    async def forget(self, telegram_user_id: int) -> Result[None]:
        return await run_guarded(
            "credits.forget",
            lambda: self._forget(telegram_user_id),
            telegram_user_id=telegram_user_id,
        )

    # -- implementations ----------------------------------------------------
    async def _charge(
        self, telegram_user_id: int, order_id: UUID, actor: str, cost: int
    ) -> tuple[ChargeOutcome, CreditBalance]:
        async with self._sessions.begin() as session:
            return await charge(
                session,
                telegram_user_id=telegram_user_id,
                order_id=order_id,
                actor=actor,
                now=self._clock(),
                cost=cost,
                policy=self._policy,
            )

    async def _settle(
        self, telegram_user_id: int, order_id: UUID, outcome: SettlementOutcome, actor: str
    ) -> bool:
        async with self._sessions.begin() as session:
            return await settle(
                session,
                telegram_user_id=telegram_user_id,
                order_id=order_id,
                outcome=outcome,
                actor=actor,
                now=self._clock(),
            )

    async def _grant(
        self, telegram_user_id: int, credits: int, idempotency_key: str, actor: str
    ) -> CreditBalance:
        now = self._clock()
        async with self._sessions.begin() as session:
            await grant(
                session,
                telegram_user_id=telegram_user_id,
                credits=credits,
                idempotency_key=idempotency_key,
                actor=actor,
                now=now,
            )
            return await read_balance(
                session, telegram_user_id=telegram_user_id, now=now, policy=self._policy
            )

    async def _balance_for(
        self, telegram_user_id: int, exclude_order_id: UUID | None
    ) -> CreditBalance:
        async with self._sessions.begin() as session:
            return await read_balance(
                session,
                telegram_user_id=telegram_user_id,
                now=self._clock(),
                policy=self._policy,
                exclude_order_id=exclude_order_id,
            )

    async def _set_blocked(self, telegram_user_id: int, is_blocked: bool) -> None:
        async with self._sessions.begin() as session:
            await set_blocked(
                session,
                telegram_user_id=telegram_user_id,
                is_blocked=is_blocked,
                now=self._clock(),
            )

    async def _touch(self, telegram_user_id: int, ui_language: Language) -> None:
        async with self._sessions.begin() as session:
            await touch(
                session,
                telegram_user_id=telegram_user_id,
                ui_language=ui_language,
                now=self._clock(),
            )

    async def _forget(self, telegram_user_id: int) -> None:
        """One transaction, so the ledger cannot end up anonymous with the balance intact.

        Logged at INFO with both counts because this is a data-subject request: when
        someone asks later whether their erasure ran, the answer has to be in the log of
        the process that ran it and not inferred from the absence of a row.
        """
        async with self._sessions.begin() as session:
            erased = await forget_account(session, telegram_user_id=telegram_user_id)
        _log.info(
            "credit record erased on request",
            extra={
                "telegram_user_id": telegram_user_id,
                "accounts_deleted": erased.accounts_deleted,
                "entries_anonymised": erased.entries_anonymised,
            },
        )
