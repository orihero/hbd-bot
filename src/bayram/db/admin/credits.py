"""``/users/{telegramUserId}/credits`` — one account's balance and the movements behind it.

**This module reads the entitlement subsystem; it never writes to it.** Every write path —
``charge``, ``settle``, ``refund``, ``consume``, ``grant``, the hourly sweep — already exists
in :mod:`bayram.db.credits` and :mod:`bayram.db.credit_settlement` behind statements that hold the
balance and the ledger in one transaction. An admin read layer that grew its own writer would
be a second place the two representations can drift apart, and the whole design of
``credit_accounts.balance`` (a deliberate duplicate of ``SUM(credit_ledger.delta)``, argued in
``models/credit_account.py``) rests on there being exactly one.

**Nothing here re-derives a balance.** The number a customer is shown comes from
:func:`bayram.db.credit_sql.read_balance` and reaches the panel through
``db.admin.users.get_user_detail``; two spellings of "how many songs does this account have?"
is how the panel ends up disagreeing with the bot, which is a failure ``read_balance``'s own
docstring records happening once already between ``/balance`` and the worker.
:func:`get_credit_account` deliberately reports something narrower and says so on the wire:
the three columns of the row, exactly as stored.

That read is one statement rather than a call to :func:`bayram.db.credit_sql.account_state`, and
the deviation is argued in :func:`get_credit_account` — that primitive cannot answer the
question this endpoint is asked (*does the row exist?*: it returns ``(0, None)`` for a missing
account, which is also what a live account that has spent everything looks like) and does not
carry ``lifetime_granted``, so reusing it would mean three round trips for three columns of one
row.

**The keyset matches the index that exists.** ``ix_credit_ledger_user_created`` is
``(telegram_user_id, created_at)`` (``models/credit_ledger.py:87``) and was put there for
exactly this screen: the leading column is the equality predicate, ``created_at`` is the range
scan, and the ``id`` tie-break §6.1 requires is a total-order fallback over the handful of rows
that share a microsecond — every write in one transaction stamps the same instant, so it is not
a theoretical case. Ordering on anything else would sort a hot account's whole history to return
fifty rows.

**Erased rows are unreachable here, and that is correct rather than a gap.** ``/forget`` nulls
``credit_ledger.telegram_user_id`` and keeps the row (``bayram.db.credit_erasure``: the count is
what answers a billing question months later, and it does not need to be *about* anyone to do
that). Those rows therefore match no ``telegram_user_id`` predicate and appear on nobody's
screen — which is the erasure working, not a query that forgot a branch.
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql import Select

from bayram.db.admin.page import (
    BoundedTotal,
    Cursor,
    Page,
    PageRequest,
    bounded_total,
    build_page,
    keyset_order,
    keyset_predicate,
)
from bayram.db.admin.views import CreditAccountState, CreditLedgerItem, PaymentGrant
from bayram.db.models.credit_account import CreditAccountRow
from bayram.db.models.credit_ledger import CreditLedgerRow

__all__ = [
    "get_credit_account",
    "list_credit_entries",
    "count_credit_entries",
    "ledger_for_key",
]


async def get_credit_account(
    session: AsyncSession, telegram_user_id: int
) -> CreditAccountState | None:
    """This account's row, or ``None`` when ``credit_accounts`` has none.

    **``None`` is the answer, not a zero, and telling the two apart is the whole reason this
    is not a call to :func:`~bayram.db.credit_sql.account_state`.** That primitive answers
    ``(0, None)`` for a missing row, which is byte-identical to a live account that has spent
    everything — and the two mean opposite things to an operator looking at a refused
    customer. Distinguishing them through ``account_state`` would take
    :func:`~bayram.db.credit_sql.account_exists` as well, and ``lifetime_granted`` is on neither,
    so the reuse costs three round trips to read three columns of one row addressed by its own
    primary key.

    Columns rather than the ORM row, which is the half of ``account_state``'s shape that
    *does* apply here: this endpoint reads inside a request transaction that may already have
    issued Core statements, and ``session.get`` would hand back the identity map's copy.
    """
    row = (
        await session.execute(
            sa.select(
                CreditAccountRow.balance,
                CreditAccountRow.lifetime_granted,
                CreditAccountRow.allowance_period_index,
            ).where(CreditAccountRow.telegram_user_id == telegram_user_id)
        )
    ).one_or_none()
    if row is None:
        return None
    balance, lifetime_granted, allowance_period_index = row
    return CreditAccountState(
        telegram_user_id=telegram_user_id,
        balance=balance,
        lifetime_granted=lifetime_granted,
        allowance_period_index=allowance_period_index,
    )


async def list_credit_entries(
    session: AsyncSession, *, telegram_user_id: int, request: PageRequest
) -> Page[CreditLedgerItem]:
    """One keyset page of this account's ledger, newest movement first."""
    statement = _filtered(telegram_user_id)
    resume = keyset_predicate(CreditLedgerRow.created_at, CreditLedgerRow.id, request.cursor)
    if resume is not None:
        statement = statement.where(resume)
    statement = statement.order_by(
        *keyset_order(CreditLedgerRow.created_at, CreditLedgerRow.id)
    ).limit(request.fetch_limit)
    rows = (await session.execute(statement)).scalars().all()
    return build_page([_ledger_item(row) for row in rows], request, _cursor_of)


async def count_credit_entries(session: AsyncSession, *, telegram_user_id: int) -> BoundedTotal:
    """``?withTotal=true`` for one account's ledger. Bounded — see :func:`bounded_total`."""
    return await bounded_total(session, _filtered(telegram_user_id))


async def ledger_for_key(
    session: AsyncSession, *, idempotency_key: str
) -> tuple[PaymentGrant, ...]:
    """Every ledger movement written under one payment's key, **oldest first**.

    The dossier's fourth panel, and the only read in this module that is not addressed by a
    ``telegram_user_id``. It is here rather than in
    :mod:`bayram.db.admin.payment_intents` because ``credit_ledger`` is this module's table and
    the ROUTER is what joins two sources.

    **A tuple and not one row, even though the key is unique.** The uniqueness lives on
    ``ix_credit_ledger_idempotency_key`` and is what makes fulfilment exactly-once, but the
    ledger is also where a future correction would land under a related key, and a singular
    return would hide the second row on the day one exists. Zero rows is the ORDINARY answer
    for a plan sale, which grants nothing at purchase.

    Oldest first, matching the dossier's other narrative reads: an operator is reading what
    happened in the order it happened.

    **Nothing here re-derives a balance.** The account's number comes from
    ``credit_sql.read_balance`` and reaches the panel through ``users.get_user_detail``; a
    second spelling of "how many songs does this account have?" is how the panel ends up
    disagreeing with the bot. These are the MOVEMENTS under one purchase and nothing more —
    and the chain stops at them, because ``credit_accounts.balance`` is a fungible scalar with
    no lot structure, so no query can say which song this grant paid for.

    ``telegram_user_id`` is deliberately not projected: the caller already knows whose payment
    this is (or knows the buyer was erased), and repeating a Telegram id once per ledger row
    would put it into a response that has no need of it.

    INDEX: the unique ``ix_credit_ledger_idempotency_key`` — an index-only probe, and the one
    read on this table that does not ride ``ix_credit_ledger_user_created``.
    """
    rows = (
        await session.execute(
            sa.select(
                CreditLedgerRow.kind,
                CreditLedgerRow.delta,
                CreditLedgerRow.reason,
                CreditLedgerRow.actor,
                CreditLedgerRow.created_at,
            )
            .where(CreditLedgerRow.idempotency_key == idempotency_key)
            .order_by(CreditLedgerRow.created_at.asc(), CreditLedgerRow.id.asc())
        )
    ).all()
    return tuple(
        PaymentGrant(
            kind=str(row.kind),
            delta=int(row.delta),
            reason=str(row.reason),
            actor=None if row.actor is None else str(row.actor),
            created_at=row.created_at,
        )
        for row in rows
    )


# ---------------------------------------------------------------------------
# internals
# ---------------------------------------------------------------------------
def _filtered(telegram_user_id: int) -> Select[tuple[CreditLedgerRow]]:
    """Every movement belonging to one account.

    The equality is spelled against the column and not against ``IS NOT NULL AND =``: a
    ``NULL`` telegram id — the ``/forget`` marker — never equals anything, so the erased rows
    fall out of this predicate on their own rather than through a second clause somebody
    could delete without failing a test.
    """
    return sa.select(CreditLedgerRow).where(CreditLedgerRow.telegram_user_id == telegram_user_id)


def _cursor_of(item: CreditLedgerItem) -> Cursor:
    return Cursor(at=item.created_at, id=item.id)


def _ledger_item(row: CreditLedgerRow) -> CreditLedgerItem:
    """Project one row. Total over every column, because none of them is nullable by accident.

    ``telegram_user_id`` is deliberately **not** copied onto the view: the caller supplied it
    in the path, every row on this page has it by construction, and repeating it per row would
    put a Telegram id fifty times into a response that already carries it once.
    """
    return CreditLedgerItem(
        id=row.id,
        kind=row.kind,
        reason=row.reason,
        delta=row.delta,
        order_id=row.order_id,
        generation=row.generation,
        idempotency_key=row.idempotency_key,
        actor=row.actor,
        created_at=row.created_at,
    )
