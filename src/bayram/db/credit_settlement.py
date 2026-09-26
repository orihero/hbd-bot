"""Closing a debit: what a finished render, a dead one and a vanished one each mean.

Split out of :mod:`bayram.db.credits` on the seam the two halves already had — that module
DECIDES whether an account may render, this one decides what happens to the credit
afterwards — and because the combined file went past the repo's 800-line cap. Nothing here
opens a transaction: every function takes the session first, takes ``now`` as a parameter and
lets exceptions propagate, so the hourly sweep can compose inside ``purge_expired``'s
existing transaction and :class:`bayram.db.credits.SqlCreditLedger` can wrap the rest.

**The policy, in one place.** Only a TERMINAL FAILURE refunds. A delivered kit and a kit the
customer's own Telegram client refused are both CONSUMED, because the thing the credit bought
exists and is redeliverable — refunding the undelivered case is directly exploitable by
blocking the bot mid-render, which is one full LLM + ElevenLabs render per credit, unbounded.

Both movements are no-ops on an order whose net position is already zero. That single guard
is what makes every settlement here safe to run twice, from the job and from the sweep, in
either order.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime, timedelta
from typing import Final
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from bayram.contracts import OrderState
from bayram.db.credit_sql import (
    StaleDebit,
    account_exists,
    add_credits,
    generation_for,
    net_position,
    stale_debits,
    write_entry,
)
from bayram.db.enums import CreditEntryKind, CreditReason
from bayram.entitlements import (
    DEFAULT_ENTITLEMENT_POLICY,
    EntitlementPolicy,
    SettlementOutcome,
)
from bayram.logging import get_logger

__all__ = [
    "refund",
    "consume",
    "settle",
    "settle_stale_debits",
    "SWEEP_ACTOR",
    "CONSUME_REASONS",
]

_log = get_logger(__name__)

#: Who the stale-debit sweep signs its rows as. A settlement written by the sweep means the
#: job that owed it never came back, and that is worth being able to count in the ledger
#: without joining anything.
SWEEP_ACTOR: Final[str] = "sweep"

#: How each end-of-order outcome is written down. Split from the settle branch so the two
#: consuming outcomes cannot drift apart from each other by accident.
CONSUME_REASONS: Final[Mapping[SettlementOutcome, CreditReason]] = {
    SettlementOutcome.DELIVERED: CreditReason.ORDER_DELIVERED,
    SettlementOutcome.NOT_DELIVERED: CreditReason.ORDER_NOT_DELIVERED,
}


async def refund(
    session: AsyncSession,
    *,
    telegram_user_id: int,
    order_id: UUID,
    reason: CreditReason,
    actor: str,
    now: datetime,
) -> bool:
    """Give back whatever ``order_id`` is currently holding. ``True`` when a refund was written.

    A net position of 0 is a NO-OP, not an error: the order was never debited, or it was
    already refunded. Refunding it anyway would mint a credit that was never spent — free
    songs for anyone who can make a settlement run twice.

    The amount is the net position rather than a fixed cost, so a future variable price
    refunds what was actually taken.

    An account that has since run ``/forget`` is a NO-OP too, and that branch is the reason
    this function reads the account row at all. ``forget_account`` deletes
    ``credit_accounts`` while the debit stays on the (now anonymous) ledger, so a render
    that fails terminally after an erasure used to write the REFUND row, reach
    ``add_credits``, find no row to credit and raise ``StorageError`` — which rolled the
    whole settlement back, logged an ERROR with a traceback on every attempt, and left the
    debit open forever, since ``credit_sql.stale_debits`` deliberately skips erased debits.
    There is nothing to give back and nobody to give it to: the balance that credit belonged
    to was deleted at the customer's own request. Refusing to re-create it is the erasure
    working, so it is INFO, not a fault.
    """
    net = await net_position(session, order_id)
    if net >= 0:
        _log.debug(
            "refund skipped: order holds no credit",
            extra={"order_id": str(order_id), "net": net},
        )
        return False
    if not await account_exists(session, telegram_user_id):
        _log.info(
            "refund skipped: the account was erased before its render ended",
            extra={"order_id": str(order_id), "telegram_user_id": telegram_user_id},
        )
        return False
    generation = await generation_for(session, order_id)
    if not await write_entry(
        session,
        telegram_user_id=telegram_user_id,
        kind=CreditEntryKind.REFUND,
        reason=reason,
        delta=-net,
        idempotency_key=f"refund:{order_id}:{generation}",
        actor=actor,
        now=now,
        order_id=order_id,
        generation=generation,
    ):
        return False
    await add_credits(session, telegram_user_id=telegram_user_id, credits=-net, lifetime=0, now=now)
    return True


async def consume(
    session: AsyncSession,
    *,
    telegram_user_id: int,
    order_id: UUID,
    reason: CreditReason,
    actor: str,
    now: datetime,
) -> bool:
    """Mark ``order_id``'s debit spent. Moves no balance; frees the in-flight slot.

    Same net-position guard as :func:`refund`, for the mirror reason: an order that holds
    no credit has nothing to consume, and writing a settlement for it would make a
    never-charged order look like a completed sale in the audit trail.
    """
    net = await net_position(session, order_id)
    if net >= 0:
        _log.debug(
            "consume skipped: order holds no credit",
            extra={"order_id": str(order_id), "net": net},
        )
        return False
    generation = await generation_for(session, order_id)
    return await write_entry(
        session,
        telegram_user_id=telegram_user_id,
        kind=CreditEntryKind.CONSUME,
        reason=reason,
        delta=0,
        idempotency_key=f"consume:{order_id}:{generation}",
        actor=actor,
        now=now,
        order_id=order_id,
        generation=generation,
    )


async def settle(
    session: AsyncSession,
    *,
    telegram_user_id: int,
    order_id: UUID,
    outcome: SettlementOutcome,
    actor: str,
    now: datetime,
) -> bool:
    """Close ``order_id``'s debit according to how the order ended.

    The policy in one place: only a terminal failure refunds. A delivered kit and a kit the
    customer's own client refused are both consumed, because the thing the credit bought
    exists and is redeliverable — refunding the undelivered case is directly exploitable by
    blocking the bot mid-render.
    """
    if outcome is SettlementOutcome.FAILED:
        return await refund(
            session,
            telegram_user_id=telegram_user_id,
            order_id=order_id,
            reason=CreditReason.ORDER_FAILED,
            actor=actor,
            now=now,
        )
    return await consume(
        session,
        telegram_user_id=telegram_user_id,
        order_id=order_id,
        reason=CONSUME_REASONS[outcome],
        actor=actor,
        now=now,
    )


async def settle_stale_debits(
    session: AsyncSession,
    *,
    now: datetime,
    limit: int,
    policy: EntitlementPolicy = DEFAULT_ENTITLEMENT_POLICY,
) -> int:
    """Close every open debit whose order is dead or long past coming back. Returns how many.

    This is the backstop for the one thing :func:`settle` cannot cover: ``jobs._settle`` runs
    inside the job, so a worker that is SIGKILLed, an order whose enqueue never happened and
    a settlement the database refused all leave a debit open with nobody left to close it.
    Until this ran on a clock, "the sweep closes it" was a sentence in a docstring — see
    ``jobs.py:478`` and ``credit_sql.count_in_flight``, both of which point here.

    Written in the ``bayram.db.admin`` idiom — session first, ``now`` injected, exceptions
    propagate, nothing commits — because it runs INSIDE ``purge_expired``'s transaction. A
    function that opened its own would either nest a transaction on a session that already
    has one or commit half a purge.

    Two settlements, not one, and the split is the same policy :func:`settle` enforces:

    * an order the pipeline finished (``DELIVERED``, which ``orchestrator`` writes when the
      kit is PERSISTED, before the Telegram send) is CONSUMED. Refunding it would hand back
      a credit for a kit that exists and is redeliverable — the free-song path WU5 exists to
      close, reachable here by anyone who can make one settle call fail;
    * everything else — a dead order, an order still in flight long past the queue's own
      ladder, an order that was never persisted at all — is REFUNDED, because nothing was
      delivered and ``progress.failed`` already promised the customer they lost nothing.

    ``limit`` is required rather than defaulted: the caller owns its own statement-timeout
    budget, and a bound this sweep chose for itself would drift from the one every other
    sweep in the same transaction is running under.
    """
    cutoff = now - timedelta(seconds=policy.settlement_grace_s)
    closed = 0
    for stale in await stale_debits(session, cutoff=cutoff, limit=limit):
        if await _close_one_stale_debit(session, stale, now=now):
            closed += 1
    if closed:
        # Loud on purpose. Every row here is a job that ended without settling, which is a
        # worker crash, a lost enqueue or a database refusal — the sweep making it right is
        # not a reason for it to be invisible.
        _log.warning("the sweep closed debits nobody else did", extra={"closed": closed})
    return closed


async def _close_one_stale_debit(
    session: AsyncSession, stale: StaleDebit, *, now: datetime
) -> bool:
    """Settle one open debit the way its order deserves. ``False`` means it was already closed.

    Both branches go through the same :func:`refund` / :func:`consume` the worker uses, so
    the sweep cannot invent a movement the ordinary path could not have written: each
    re-derives the generation and the amount from the ledger, and each is a no-op on an order
    that holds no credit. ``STALE_SETTLEMENT`` is what says the sweep — not the job — is who
    closed it, which is the only fact this path adds to the audit trail.
    """
    if stale.order_state is OrderState.DELIVERED:
        return await consume(
            session,
            telegram_user_id=stale.telegram_user_id,
            order_id=stale.order_id,
            reason=CreditReason.STALE_SETTLEMENT,
            actor=SWEEP_ACTOR,
            now=now,
        )
    return await refund(
        session,
        telegram_user_id=stale.telegram_user_id,
        order_id=stale.order_id,
        reason=CreditReason.STALE_SETTLEMENT,
        actor=SWEEP_ACTOR,
        now=now,
    )
