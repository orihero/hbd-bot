"""``/forget`` against the credit tables: drop the balance, keep the count, lose the name.

``/privacy`` enumerates four retention clocks and promises that everything on them is
deleted on a schedule. The entitlement layer arrived with two tables that are on no clock
at all — ``credit_accounts``, which is a live balance, and ``credit_ledger``, which is an
append-only audit trail — so the notice became false the moment WU1 landed. This module is
half of making it true again; the other half is the copy in the four catalogues that now
names both.

**The two tables get opposite treatment, and the asymmetry is the whole design.**

*A balance is not an audit fact.* ``credit_accounts`` holds what someone may spend right
now. Nobody needs it after they have asked to be forgotten, and keeping it would leave a
row that says "this Telegram account exists and has two songs left" — an identity record
with no purpose. It is DELETED.

*A receipt is.* ``credit_ledger`` is what answers "why does this account have two credits?"
and "was this customer charged for a song that never arrived?" months later, including for
a dispute the customer themselves raises. Deleting it would destroy that answer for
everyone, and an audit trail that erases itself on request is not an audit trail. So the
rows STAY and the identity comes off them: ``telegram_user_id`` is nulled and everything
else — the movement, its reason, its clock — survives as an anonymous aggregate.

**Why ``idempotency_key`` deliberately keeps the id it was built from.** The rolling
allowance is minted once per window on ``grant:period:{telegram_user_id}:{index}``, and the
unique index on that key is the ONLY thing that makes the mint idempotent. Rewriting the
key here would delete that memory, and because :func:`hbd.db.credits._mint_due_allowance`
reads ``credit_accounts.allowance_period_index`` — a row this function has just removed —
the very next order would mint a fresh allowance for a window already paid for. ``/forget``
would become "reset my free songs", repeatable, forever. Keeping the key is what makes
:func:`forget_account` an erasure rather than an exploit, and it is asserted by test.

The cost of that choice is stated rather than hidden: one machine-built string per grant
still contains the account id. It is a replay marker, not a record about a person — it
carries no balance, no order and no history on its own — but a reader of this module should
know it is there.

Shape follows :mod:`hbd.db.admin` and :func:`hbd.db.purge.purge_expired`: session first and
positional, exceptions propagate, and **nothing is committed here**. The caller owns the
transaction, which is what lets the two statements below be atomic — an erasure that
deleted the balance and then failed to anonymise the ledger would be the worst of both.
"""

from __future__ import annotations

from dataclasses import dataclass

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from hbd.db.credit_sql import rowcount_of
from hbd.db.models.credit_account import CreditAccountRow
from hbd.db.models.credit_ledger import CreditLedgerRow

__all__ = ["CreditErasure", "forget_account"]


@dataclass(frozen=True, slots=True)
class CreditErasure:
    """What one ``/forget`` actually removed. Two numbers, so the log is not a guess.

    Both being zero is a perfectly ordinary answer — most people who send ``/forget`` never
    confirmed an order, so they have no account row and no ledger history — and it is
    reported as such rather than treated as a failure. The handler's confirmation to the
    customer does not depend on it: it says the same thing either way, because "there was
    nothing of yours to delete" and "I deleted it" are the same promise kept.

    Both numbers come from the driver's ``rowcount`` over a bulk statement, which
    :func:`hbd.db.credit_sql.rowcount_of` documents as exact only for single-row writes.
    They are therefore DIAGNOSTIC — they go in a log line and nothing branches on them.
    """

    #: ``credit_accounts`` rows removed. Zero or one; the id is that table's primary key.
    accounts_deleted: int
    #: ``credit_ledger`` rows that lost their owner and kept everything else.
    entries_anonymised: int


async def forget_account(session: AsyncSession, *, telegram_user_id: int) -> CreditErasure:
    """Erase what the credit tables hold about one Telegram account.

    Ordered ledger-first on purpose. Both statements run in the caller's transaction, so
    they either both land or neither does; but if a future caller ever splits them, the
    half that leaves the ledger anonymous and the balance behind is far less bad than the
    half that deletes the balance and leaves a fully identified history.

    Idempotent by construction: a second call matches nothing and returns two zeroes.

    **What this does not reach.** A song already in the studio settles after the erasure,
    and the worker writes that settlement from the ``orders`` row — which keeps its own id
    on the ``/privacy`` schedule — so one ledger entry can appear afterwards carrying the
    account id again. ``privacy.forgotten`` already tells the customer that a song at the
    studio keeps the dates in ``/privacy``; sending ``/forget`` once it has arrived clears
    that entry too. Named here because a reader must not have to discover it.
    """
    anonymised = await session.execute(
        sa.update(CreditLedgerRow)
        .where(CreditLedgerRow.telegram_user_id == telegram_user_id)
        .values(telegram_user_id=None)
    )
    deleted = await session.execute(
        sa.delete(CreditAccountRow).where(CreditAccountRow.telegram_user_id == telegram_user_id)
    )
    return CreditErasure(
        accounts_deleted=rowcount_of(deleted), entries_anonymised=rowcount_of(anonymised)
    )
