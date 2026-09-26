"""The SQL primitives the entitlement layer is built out of — one statement per function.

Split out of :mod:`bayram.db.credits` so that the *policy* (when to mint, when to refuse, what
a settlement means) reads as a short sequence of named steps rather than as three hundred
lines of ``sa.select``. Everything here is deliberately dumb: no function decides anything,
each one performs exactly one statement and reports what the database did.

Two of them carry the whole concurrency story and are worth reading before anything else:

* :func:`upsert_statement` is the ONE place a dialect is named. ``ON CONFLICT`` has no
  portable spelling, and the alternative — ``session.begin_nested()`` — was reproduced
  failing: a SAVEPOINT taken as the first statement of a transaction does not roll back on
  ``aiosqlite`` while it does on Postgres, so the unit suite could never have validated
  production semantics.
* :func:`debit_balance` is ``UPDATE … SET balance = balance - :cost WHERE balance >= :cost``
  with a rowcount check. Two concurrent charges cannot both see a rowcount of 1 under
  Postgres READ COMMITTED, which is why there is no ``SELECT … FOR UPDATE`` (verified a
  silent no-op in SQLAlchemy's SQLite dialect) and no per-user retry loop anywhere.

These names are public to the ``bayram.db`` package and to nothing else: ``bayram/db/__init__.py``
exports ``SqlCreditLedger`` and ``verify_balances``, and a caller outside persistence has no
business holding a session in the first place (Rule 15).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Final, cast
from uuid import UUID, uuid4

import sqlalchemy as sa
from sqlalchemy import CursorResult
from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from bayram.contracts import OrderState
from bayram.db.base import Base
from bayram.db.enums import CreditEntryKind, CreditReason
from bayram.db.models.credit_account import CreditAccountRow
from bayram.db.models.credit_ledger import ACTOR_LENGTH, CreditLedgerRow
from bayram.db.models.order import OrderRow
from bayram.db.models.user import UserRow
from bayram.entitlements import (
    DEFAULT_ENTITLEMENT_POLICY,
    BalanceDrift,
    CreditBalance,
    EntitlementPolicy,
    period_index_for,
)
from bayram.errors import ConfigError, StorageError

__all__ = [
    "upsert_statement",
    "rowcount_of",
    "insert_or_ignore",
    "account_state",
    "account_exists",
    "has_period_grant",
    "period_grant_key",
    "is_blocked",
    "net_position",
    "generation_for",
    "count_in_flight",
    "read_balance",
    "write_entry",
    "debit_balance",
    "add_credits",
    "open_account",
    "verify_balances",
    "SETTLING_KINDS",
    "StaleDebit",
    "stale_debits",
    "DEAD_ORDER_STATES",
]

#: Which ledger kinds close a debit. A refund gives the credit back, a consume merely marks
#: the debit spent — both free the in-flight slot, and neither may happen twice for one
#: (order, generation) because the idempotency key carries both.
SETTLING_KINDS: Final[tuple[CreditEntryKind, ...]] = (
    CreditEntryKind.CONSUME,
    CreditEntryKind.REFUND,
)


# ---------------------------------------------------------------------------
# Dialect plumbing
# ---------------------------------------------------------------------------
def upsert_statement(
    session: AsyncSession,
    table: type[Base],
    values: Mapping[str, Any],
    *,
    index_elements: Sequence[str],
    set_: Mapping[str, Any] | None,
) -> sa.Executable:
    """``INSERT … ON CONFLICT`` for whichever engine this session is bound to.

    ``ON CONFLICT`` is dialect-specific syntax, so SQLAlchemy exposes it only on the
    dialect's own ``insert()`` — there is no portable construct to hide behind. One
    dispatch, here, is the whole cost of running the unit suite on SQLite and production on
    Postgres. ``set_`` chooses the shape: ``None`` means DO NOTHING (an idempotent write
    whose loser must be detectable by rowcount), a mapping means DO UPDATE (an upsert).

    An unknown dialect raises rather than falling back to a plain ``INSERT``: a silent
    fallback would turn every idempotency guarantee in the entitlement layer into a
    duplicate-key crash on the first replay, in production, on an engine nobody tested.
    """
    dialect = session.get_bind().dialect.name
    columns = list(index_elements)
    if dialect == "postgresql":
        statement = postgresql_insert(table).values(dict(values))
        if set_ is None:
            return statement.on_conflict_do_nothing(index_elements=columns)
        return statement.on_conflict_do_update(index_elements=columns, set_=dict(set_))
    if dialect == "sqlite":
        lite = sqlite_insert(table).values(dict(values))
        if set_ is None:
            return lite.on_conflict_do_nothing(index_elements=columns)
        return lite.on_conflict_do_update(index_elements=columns, set_=dict(set_))
    # The message names the TABLE rather than "the entitlement ledger": this helper is
    # general, it gained a second caller outside the entitlement layer when the vendor
    # balance poll started upserting through it, and an operator debugging a balance cache
    # should not be sent reading the credit ledger. The behaviour is unchanged — an unknown
    # dialect still raises rather than falling back to a plain INSERT, for the reason this
    # function's docstring gives.
    raise ConfigError(
        f"{getattr(table, '__tablename__', '?')} has no ON CONFLICT dialect for {dialect!r}",
        context={"dialect": dialect, "table": getattr(table, "__tablename__", "?")},
    )


def rowcount_of(result: object) -> int:
    """Rows the last statement actually touched.

    Exact after an ``INSERT`` and after a single-row ``UPDATE`` on both drivers, which is
    all this module relies on — ``bayram.db.purge`` counts ids instead precisely because it
    issues bulk updates where the number is driver-dependent.
    """
    return cast("CursorResult[Any]", result).rowcount


async def insert_or_ignore(
    session: AsyncSession,
    table: type[Base],
    values: Mapping[str, Any],
    *,
    index_elements: Sequence[str],
) -> bool:
    """Insert one row. ``True`` when THIS caller wrote it, ``False`` when it already existed.

    The boolean is the concurrency primitive: two writers of the same movement both succeed
    at the statement level and exactly one is told it won, so the balance move that follows
    happens once.
    """
    result = await session.execute(
        upsert_statement(session, table, values, index_elements=index_elements, set_=None)
    )
    return rowcount_of(result) == 1


# ---------------------------------------------------------------------------
# Reads
# ---------------------------------------------------------------------------
async def account_state(session: AsyncSession, telegram_user_id: int) -> tuple[int, int | None]:
    """``(balance, allowance_period_index)``; ``(0, None)`` when no account row exists.

    Columns rather than the ORM row on purpose: this is read AFTER Core ``UPDATE``s in the
    same transaction, and a ``session.get`` would hand back the identity map's stale copy.
    """
    row = (
        await session.execute(
            sa.select(CreditAccountRow.balance, CreditAccountRow.allowance_period_index).where(
                CreditAccountRow.telegram_user_id == telegram_user_id
            )
        )
    ).one_or_none()
    return (0, None) if row is None else (row[0], row[1])


async def account_exists(session: AsyncSession, telegram_user_id: int) -> bool:
    """Whether this account still has a ``credit_accounts`` row.

    Distinct from ``account_state`` returning a balance of 0, which is also what a live
    account that has spent everything looks like. The one caller that needs the difference
    is :func:`bayram.db.credits.refund`: after ``/forget`` the row is gone while the debit it
    would credit is still on the ledger, and crediting a row that is not there is a
    ``StorageError`` that rolls the whole settlement back.
    """
    found = await session.scalar(
        sa.select(sa.literal(1)).where(CreditAccountRow.telegram_user_id == telegram_user_id)
    )
    return found is not None


def period_grant_key(telegram_user_id: int, index: int) -> str:
    """The idempotency key one window's rolling allowance is minted under.

    One function rather than two format strings, because the mint
    (:func:`bayram.db.credits._mint_due_allowance`) and the read that predicts it
    (:func:`read_balance`) MUST agree character for character. They disagreed once already:
    the read decided an allowance was due from ``credit_accounts.allowance_period_index``,
    which ``/forget`` deletes, while the mint deferred to this key, which ``/forget``
    deliberately keeps — so ``/balance`` promised three songs the worker then refused.
    """
    return f"grant:period:{telegram_user_id}:{index}"


async def has_period_grant(session: AsyncSession, telegram_user_id: int, index: int) -> bool:
    """Has this window's allowance already been minted for this account?

    The unique index on ``credit_ledger.idempotency_key`` is the sole authority on that
    question — ``credit_accounts.allowance_period_index`` is a convenience that erasure
    removes — so this asks the authority directly.
    """
    found = await session.scalar(
        sa.select(sa.literal(1)).where(
            CreditLedgerRow.idempotency_key == period_grant_key(telegram_user_id, index)
        )
    )
    return found is not None


async def is_blocked(session: AsyncSession, telegram_user_id: int) -> bool:
    """Whether an operator has barred this account. No ``users`` row means not blocked."""
    blocked = await session.scalar(
        sa.select(UserRow.is_blocked).where(UserRow.telegram_user_id == telegram_user_id)
    )
    return bool(blocked)


async def net_position(session: AsyncSession, order_id: UUID) -> int:
    """``SUM(delta)`` over every ledger row for ``order_id``. Negative means paid for.

    Not filtered by user: an order id is a UUID5 over one draft, so it belongs to exactly
    one account, and filtering by both would mask a bug (a debit attributed to the wrong
    account) by making it look like an unpaid order rather than a broken one.
    """
    total = await session.scalar(
        sa.select(sa.func.coalesce(sa.func.sum(CreditLedgerRow.delta), 0)).where(
            CreditLedgerRow.order_id == order_id
        )
    )
    return int(total or 0)


async def generation_for(session: AsyncSession, order_id: UUID) -> int:
    """Which charge attempt this order is on: one per refund it has already had.

    Counting refunds rather than debits is what keeps the debit and its settlement on the
    same generation — ``debit:{order}:{gen}`` and ``refund:{order}:{gen}`` name the same
    attempt, and the next debit lands on ``gen + 1`` because the refund incremented it.
    """
    total = await session.scalar(
        sa.select(sa.func.count())
        .select_from(CreditLedgerRow)
        .where(
            CreditLedgerRow.order_id == order_id,
            CreditLedgerRow.kind == CreditEntryKind.REFUND,
        )
    )
    return int(total or 0)


async def count_in_flight(
    session: AsyncSession,
    *,
    telegram_user_id: int,
    cutoff: datetime,
    exclude_order_id: UUID | None,
) -> int:
    """Debits this account has not settled yet, newer than ``cutoff``.

    A debit is in flight when no ``CONSUME`` or ``REFUND`` exists for its own
    ``(order_id, generation)``. Matching the generation matters: after charge → refund →
    charge, the first debit is settled by that refund while the second is genuinely open,
    and a predicate that only matched ``order_id`` would call the second one settled and let
    the account stack another render.

    ``cutoff`` is what stops a debit whose worker died from wedging its customer out
    forever; WU6's sweep is what closes such a debit properly.
    """
    debit = aliased(CreditLedgerRow)
    settlement = aliased(CreditLedgerRow)
    is_settled = sa.exists(
        sa.select(sa.literal(1)).where(
            settlement.order_id == debit.order_id,
            settlement.generation == debit.generation,
            settlement.kind.in_(SETTLING_KINDS),
        )
    )
    statement = (
        sa.select(sa.func.count())
        .select_from(debit)
        .where(
            debit.telegram_user_id == telegram_user_id,
            debit.kind == CreditEntryKind.DEBIT,
            debit.created_at >= cutoff,
            ~is_settled,
        )
    )
    if exclude_order_id is not None:
        statement = statement.where(debit.order_id != exclude_order_id)
    return int(await session.scalar(statement) or 0)


async def read_balance(
    session: AsyncSession,
    *,
    telegram_user_id: int,
    now: datetime,
    policy: EntitlementPolicy = DEFAULT_ENTITLEMENT_POLICY,
    exclude_order_id: UUID | None = None,
) -> CreditBalance:
    """Everything a gate needs about one account, writing NOTHING.

    ``credits`` includes an allowance that is due but unminted. That projection is not
    cosmetic: the bot-side gate is read-only by design, so without it every brand-new
    customer would be refused on the Confirm screen by a balance of 0 that ``charge`` would
    have topped up to three a second later — the gate would refuse exactly the people the
    allowance exists for.

    It is projected only when the mint would ACTUALLY succeed, and that second condition is
    what the account row alone cannot answer. ``/forget`` deletes ``credit_accounts`` —
    ``allowance_period_index`` with it — while deliberately keeping the grant's idempotency
    key on the anonymised ledger row (``bayram.db.credit_erasure``, which argues why: the key
    is the only thing stopping ``/forget`` from being "reset my free songs"). Reading the
    account row alone therefore said "due" for a window already paid for, and ``/balance``,
    the Confirm-screen note and the read-only gate all promised three songs that
    :func:`bayram.db.credits._mint_due_allowance` would then decline to mint — leaving the
    customer refused in the WORKER, after the progress bar, for the rest of the window.
    Asking the ledger costs one indexed lookup and only on the branch that would project.

    **A LIVE PLAN'S UNMINTED SONGS ARE PROJECTED FOR EXACTLY THE SAME REASON, VERBATIM.**
    Buying the starter plan writes one ``plan_purchases`` row and no credits at all —
    :mod:`bayram.db.plan_sql` argues why an eager twelve-credit grant cannot express expiry on a
    fungible balance — so a customer who has just paid 49 000 soʻm has a stored balance of 0
    and twelve songs coming. Without this projection the read-only Confirm gate would
    paywall them in the same message that had thanked them for paying, and the paywall would
    stay up for thirty days while ``charge`` cheerfully minted a song every time. The
    projection is bounded by the same predicate the mint uses (``plan_ends_at > now`` AND
    ``songs_used < songs_included``, both inside :func:`bayram.db.plan_sql.live_plan`), so the
    two cannot drift.

    ``plan_ends_at`` is populated even when nothing is mintable — that is the
    :func:`bayram.db.plan_sql.current_plan` fallback below — because "no plan" and "a plan with
    nothing left" are different offers: the first is sold a plan, the second is sold a single
    song and told the plan brings nothing more until it ends. A caller cannot tell them apart
    from a fungible ``credits`` total, so the fields say it outright.
    """
    balance, minted_index = await account_state(session, telegram_user_id)
    current_index = period_index_for(now, period_days=policy.allowance_period_days)
    is_due = (minted_index is None or minted_index < current_index) and not await has_period_grant(
        session, telegram_user_id, current_index
    )
    # THE ONE DEFERRED IMPORT IN THIS PACKAGE, and it closes a real cycle rather than a
    # stylistic one. :mod:`bayram.db.plan_sql` is built ON this module's primitives — it calls
    # ``insert_or_ignore`` and ``rowcount_of``, which is the correct direction for a
    # higher-level statement set — while this one function needs to READ a plan. Importing
    # ``plan_sql`` at module scope closes the loop: whichever module Python reaches first
    # begins executing, reaches its import of the other, and that other's import of the first
    # resolves against a half-initialised module whose names do not exist yet. Deferring the
    # edge to the single call site costs one dict lookup per read and is confined to the one
    # place the layering genuinely reverses.
    from bayram.db.plan_sql import current_plan, live_plan

    plan = await live_plan(session, telegram_user_id=telegram_user_id, now=now)
    if plan is None:
        # Spent-but-unexpired, or nothing at all. Costs a second indexed lookup only on the
        # branch that has no songs to project, which is the branch that is not on the hot
        # charge path.
        spent = await current_plan(session, telegram_user_id=telegram_user_id, now=now)
        plan_songs_left = 0
        plan_ends_at = None if spent is None else spent.plan_ends_at
    else:
        plan_songs_left = plan.songs_included - plan.songs_used
        plan_ends_at = plan.plan_ends_at
    return CreditBalance(
        telegram_user_id=telegram_user_id,
        credits=balance + (policy.allowance_credits if is_due else 0) + plan_songs_left,
        in_flight=await count_in_flight(
            session,
            telegram_user_id=telegram_user_id,
            cutoff=now - timedelta(seconds=policy.settlement_grace_s),
            exclude_order_id=exclude_order_id,
        ),
        is_blocked=await is_blocked(session, telegram_user_id),
        plan_songs_left=plan_songs_left,
        plan_ends_at=plan_ends_at,
    )


# ---------------------------------------------------------------------------
# Writes
# ---------------------------------------------------------------------------
async def write_entry(
    session: AsyncSession,
    *,
    telegram_user_id: int,
    kind: CreditEntryKind,
    reason: CreditReason,
    delta: int,
    idempotency_key: str,
    actor: str,
    now: datetime,
    order_id: UUID | None = None,
    generation: int = 0,
) -> bool:
    """Append one movement. ``False`` means an identical movement was already recorded.

    Every column is passed explicitly because this is a Core ``INSERT``: the Python-side
    ``default=`` on ``generation``, ``created_at`` and ``id`` only fires on an ORM flush, so
    omitting one earns a NOT NULL violation on Postgres and a surprise on SQLite.
    """
    return await insert_or_ignore(
        session,
        CreditLedgerRow,
        {
            "id": uuid4(),
            "telegram_user_id": telegram_user_id,
            "kind": kind,
            "reason": reason,
            "delta": delta,
            "order_id": order_id,
            "generation": generation,
            "idempotency_key": idempotency_key,
            # Diagnostic attribution, not a key: an over-long operator name is truncated
            # rather than allowed to fail a write that is otherwise perfectly valid.
            "actor": actor[:ACTOR_LENGTH],
            "created_at": now,
        },
        index_elements=["idempotency_key"],
    )


async def debit_balance(
    session: AsyncSession, *, telegram_user_id: int, cost: int, now: datetime
) -> bool:
    """Take ``cost`` credits if and only if they are there. ``False`` means they were not.

    The ``balance >= :cost`` predicate is the concurrency control for the whole module;
    ``ck_credit_accounts_balance_not_negative`` is the second layer that turns a future
    writer forgetting it into a loud failure instead of a negative balance nobody notices.
    ``updated_at`` is set by hand because ``TimestampMixin``'s ``onupdate`` fires on an ORM
    flush only, and this is Core.
    """
    result = await session.execute(
        sa.update(CreditAccountRow)
        .where(
            CreditAccountRow.telegram_user_id == telegram_user_id,
            CreditAccountRow.balance >= cost,
        )
        .values(balance=CreditAccountRow.balance - cost, updated_at=now)
    )
    return rowcount_of(result) == 1


async def add_credits(
    session: AsyncSession,
    *,
    telegram_user_id: int,
    credits: int,
    lifetime: int,
    now: datetime,
    period_index: int | None = None,
) -> None:
    """Put credits back (a refund) or in (a grant), and stamp the allowance window.

    ``lifetime`` is separate from ``credits`` because a refund restores spendable credits
    without the account having been *given* anything — ``lifetime_granted`` answers "has
    this account already been comped?" and a refund must not inflate it.

    A rowcount of 0 means the account row vanished between opening it and crediting it,
    inside one transaction. That cannot happen today, so it is reported as a storage fault
    rather than ignored: swallowing it would silently break ``balance == SUM(delta)``.
    """
    values: dict[str, Any] = {
        "balance": CreditAccountRow.balance + credits,
        "lifetime_granted": CreditAccountRow.lifetime_granted + lifetime,
        "updated_at": now,
    }
    if period_index is not None:
        values["allowance_period_index"] = period_index
    result = await session.execute(
        sa.update(CreditAccountRow)
        .where(CreditAccountRow.telegram_user_id == telegram_user_id)
        .values(**values)
    )
    if rowcount_of(result) != 1:
        raise StorageError(
            "credit account disappeared while being credited",
            context={"telegram_user_id": telegram_user_id, "credits": credits},
        )


async def open_account(session: AsyncSession, *, telegram_user_id: int, now: datetime) -> bool:
    """Ensure an account row exists. ``True`` when this call created it.

    No ``users`` row is required or created: a person who has walked the wizard but never
    confirmed an order has none, and they are exactly who is about to be charged.
    """
    return await insert_or_ignore(
        session,
        CreditAccountRow,
        {
            "telegram_user_id": telegram_user_id,
            "balance": 0,
            "lifetime_granted": 0,
            "allowance_period_index": None,
            "created_at": now,
            "updated_at": now,
        },
        index_elements=["telegram_user_id"],
    )


# ---------------------------------------------------------------------------
# The stale-debit sweep's one query
# ---------------------------------------------------------------------------
#: Order states in which no job can possibly still be running, so the debit under them is
#: closable IMMEDIATELY without waiting out the grace.
#:
#: ``FAILED`` used to be in here and that was a free-song bug, not a nuance.
#: ``orchestrator._fail`` (orchestrator.py) writes ``FAILED`` for RETRYABLE failures too —
#: ``jobs._run_pipeline`` only afterwards raises ``Retry`` — so a row reading ``FAILED``
#: means "the last attempt failed", never "the job is gone". Sweeping it on sight refunded
#: a debit whose job was sitting in arq's backoff; that job then delivered, its ``CONSUME``
#: found ``net_position == 0`` and wrote nothing, and the customer kept both the song and
#: the credit. The design's own ``rejected[]`` records ``orders.state`` as unusable for
#: exactly this reason, and this constant was the one place it had crept back in.
#:
#: ``CANCELLED`` stays because nothing in the pipeline ever writes it: it can only arrive
#: from an operator or a future explicit cancellation, both of which mean the run is over.
#: ``DELIVERED`` is deliberately absent — refunding a delivered order is a free song — and
#: reaches the sweep only through the quiet branch below, where
#: :func:`bayram.db.credits.settle_stale_debits` CONSUMES it instead.
DEAD_ORDER_STATES: Final[tuple[OrderState, ...]] = (OrderState.CANCELLED,)


@dataclass(frozen=True, slots=True)
class StaleDebit:
    """One open debit the sweep has decided to close, and the little it needs to do so.

    Not a ``*Row`` and deliberately so (Rule 15): the sweep hands these to
    ``bayram.db.credits``, which re-derives the amount and the generation from the ledger
    itself rather than trusting numbers carried across a function boundary.

    ``order_state`` is ``None`` when there is no ``orders`` row at all — the gate can charge
    before the order is persisted, so an orphaned debit is a real shape and not a join bug.
    """

    telegram_user_id: int
    order_id: UUID
    order_state: OrderState | None


async def stale_debits(
    session: AsyncSession, *, cutoff: datetime, limit: int
) -> tuple[StaleDebit, ...]:
    """Open debits that are safe to close: a cancelled order, or one that has gone quiet.

    "Open" is the same predicate :func:`count_in_flight` uses — no ``CONSUME`` or ``REFUND``
    for this debit's own ``(order_id, generation)`` — and matching the generation is what
    keeps a charge → refund → charge history from looking settled at its second attempt.

    **"Quiet" means the ORDER ROW has not moved either, and that half is load-bearing.**
    Waiting out the grace on the debit alone makes the sweep's correctness depend on the
    grace being longer than the deployment's whole retry ladder — and it is not, whenever
    the cron caller and the ledger resolve different policies (``bayram.runtime.retention_job``
    passes only ``policy=``, so the sweep runs on ``DEFAULT_ENTITLEMENT_POLICY`` while
    ``AppContainer`` resolves the ledger's from ``Settings``). Requiring
    ``orders.updated_at <= cutoff`` closes that gap from this side: every stage transition
    stamps that column (``repository._set_order_state``), so a job that is still working —
    or sitting between attempts — is visibly alive whatever the grace happens to be, and a
    row that has said nothing for a whole grace has outlived its own job timeout.

    A debit with NO order row at all needs only its own age: the row was never persisted (or
    has since been purged as an abandoned draft), so there is nothing left to be quiet.

    The ``LIMIT`` is the whole reason the caller can run this hourly against a year of
    backlog: a first pass takes ``limit`` rows, closes them, and the next pass sees the rest.
    Ordered oldest-first so a bounded run always works on the debits that have been open
    longest, and tie-broken on the idempotency key so two passes over rows written in the
    same transaction cannot interleave differently.
    """
    debit = aliased(CreditLedgerRow)
    settlement = aliased(CreditLedgerRow)
    is_settled = sa.exists(
        sa.select(sa.literal(1)).where(
            settlement.order_id == debit.order_id,
            settlement.generation == debit.generation,
            settlement.kind.in_(SETTLING_KINDS),
        )
    )
    rows = (
        await session.execute(
            sa.select(debit.telegram_user_id, debit.order_id, OrderRow.state)
            .select_from(debit)
            # OUTER, not inner: a debit whose order row was never written (or has since been
            # purged as an abandoned draft) is exactly the debit most in need of closing, and
            # an inner join would hide it from the sweep forever.
            .outerjoin(OrderRow, OrderRow.id == debit.order_id)
            .where(
                debit.kind == CreditEntryKind.DEBIT,
                debit.order_id.is_not(None),
                # An erased debit has no owner to refund and holds nobody's in-flight slot
                # (`count_in_flight` filters on the id, so a NULL matches no account), and
                # settling it would write a FRESH row carrying the very id `/forget` just
                # removed. Leaving it open costs nothing and re-identifies nobody. Without
                # this the sweep would also try to build a `StaleDebit` with a NULL owner
                # and blow up the whole hourly purge transaction on a pydantic error.
                debit.telegram_user_id.is_not(None),
                ~is_settled,
                sa.or_(
                    OrderRow.state.in_(DEAD_ORDER_STATES),
                    sa.and_(
                        debit.created_at <= cutoff,
                        sa.or_(OrderRow.id.is_(None), OrderRow.updated_at <= cutoff),
                    ),
                ),
            )
            .order_by(debit.created_at, debit.idempotency_key)
            .limit(limit)
        )
    ).all()
    return tuple(
        StaleDebit(telegram_user_id=row[0], order_id=row[1], order_state=row[2]) for row in rows
    )


# ---------------------------------------------------------------------------
# Integrity
# ---------------------------------------------------------------------------
async def _ledger_only_drifts(session: AsyncSession) -> list[BalanceDrift]:
    """Accounts with ledger movement and no account row — a balance of 0 that should not be.

    Erased rows are excluded, and the exclusion is load-bearing twice over. An account that
    ran ``/forget`` has exactly this shape by design — ledger movement, no account row — so
    without the filter every erasure would be reported to an operator as balance drift, and
    the report itself would raise: ``BalanceDrift.telegram_user_id`` is an ``int``, and the
    ``NULL`` group would fail its own validation before anyone could read it.
    """
    has_account = sa.exists(
        sa.select(sa.literal(1)).where(
            CreditAccountRow.telegram_user_id == CreditLedgerRow.telegram_user_id
        )
    )
    rows = (
        await session.execute(
            sa.select(
                CreditLedgerRow.telegram_user_id,
                sa.func.coalesce(sa.func.sum(CreditLedgerRow.delta), 0),
            )
            .where(~has_account, CreditLedgerRow.telegram_user_id.is_not(None))
            .group_by(CreditLedgerRow.telegram_user_id)
            .having(sa.func.coalesce(sa.func.sum(CreditLedgerRow.delta), 0) != 0)
        )
    ).all()
    return [
        BalanceDrift(telegram_user_id=row[0], balance=0, ledger_total=int(row[1])) for row in rows
    ]


async def verify_balances(session: AsyncSession) -> tuple[BalanceDrift, ...]:
    """Every account whose stored balance disagrees with ``SUM(credit_ledger.delta)``.

    An empty tuple is the only healthy answer. This is the check that makes the
    two-representation trade-off honest: the tests assert it after every operation, and an
    operator can run it against production without taking a lock or writing anything.
    """
    ledger_total = (
        sa.select(sa.func.coalesce(sa.func.sum(CreditLedgerRow.delta), 0))
        .where(CreditLedgerRow.telegram_user_id == CreditAccountRow.telegram_user_id)
        .scalar_subquery()
    )
    rows = (
        await session.execute(
            sa.select(
                CreditAccountRow.telegram_user_id, CreditAccountRow.balance, ledger_total
            ).where(CreditAccountRow.balance != ledger_total)
        )
    ).all()
    drifts = [
        BalanceDrift(telegram_user_id=row[0], balance=int(row[1]), ledger_total=int(row[2]))
        for row in rows
    ]
    drifts.extend(await _ledger_only_drifts(session))
    return tuple(sorted(drifts, key=lambda drift: drift.telegram_user_id))
