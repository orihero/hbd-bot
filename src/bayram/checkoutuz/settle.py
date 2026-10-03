"""Settle one checkout.uz order — the ONLY code that grants anything for this rail.

Called by the worker, from the five-minute poll and from the job the webhook gate enqueues.
Both paths arrive here with nothing but an ``order_id``, and that is deliberate: the webhook
body is unsigned and comes from the open internet, so nothing it says is believed. This
function asks checkout.uz itself (``status_payment``) and moves money only when every one of
these holds (``DECISIONS.md D28``):

* the order is on file and its intent was opened for THIS rail;
* checkout.uz says ``status == "paid"`` about that exact ``id``;
* the paid amount equals the som amount we recorded when the link was minted;
* that som amount, in tiyin, equals the intent's ``amount_minor``.

**Network outside, money inside.** The vendor call happens before any transaction is opened, so
a slow checkout.uz never holds a database connection. The writes then happen in ONE
transaction, in this order, each a conditional ``UPDATE`` whose rowcount is the lock:

1. the payment ``pending -> paid``. Losing that means another run already settled it: ``replay``.
2. the intent ``pending | awaiting | expired -> paid``. Losing that means the intent was already
   paid through an EARLIER link of the same purchase: the payment becomes ``orphan_paid``, an
   ERROR is logged for a manual refund, and nothing is granted a second time.
3. the receipt and the credit (or the plan), under the intent's own idempotency key — the same
   unique indexes a double tap in the bot or an operator's force-settle would land on.

``EXPIRED`` is claimable for this rail only, and on purpose: checkout.uz takes the money on its
own page without asking us first, so refusing a late payment would not refuse the payment — it
would only make sure the customer got nothing for it.

**After the commit**, the "your payment went through" job is enqueued. Its failure is swallowed:
the Payme sweep's notification arm re-enqueues every settled, unannounced intent of any rail,
so a Redis blip here delays the message rather than losing it.

Never raises: every outcome, including a database failure, is a :class:`SettleOutcome`.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Final

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from bayram.checkout import Product, Purchase
from bayram.checkoutuz.client import CheckoutUzApi
from bayram.checkoutuz.ports import (
    CHECKOUTUZ_PROVIDER_NAME,
    TIYIN_PER_SOM,
    CheckoutUzStatus,
)
from bayram.contracts import Err
from bayram.db.checkoutuz_sql import (
    claim_intent_for_checkoutuz,
    mark_payment,
    payment_with_intent,
    stamp_polled,
)
from bayram.db.enums import CheckoutUzPaymentState, IntentProduct
from bayram.db.fulfilment import write_plan_sale, write_single_sale
from bayram.db.models.payment_intent import PaymentIntentRow
from bayram.errors import StorageError
from bayram.logging import get_logger

__all__ = [
    "Notifier",
    "SettleOutcome",
    "SettleStatus",
    "settle_checkoutuz_order",
    "settle_note",
]

_LOG = get_logger(__name__)

#: The link states a settlement may move to ``paid``. See :func:`_settle` step 1.
_SETTLEABLE_PAYMENT_STATES: Final[frozenset[CheckoutUzPaymentState]] = frozenset(
    {CheckoutUzPaymentState.PENDING, CheckoutUzPaymentState.EXPIRED}
)

#: "Tell the buyer of ``public_ref`` their payment landed." In the worker this is
#: :class:`bayram.payme.container.QueuedNotifier`, whose deterministic job id collapses this
#: enqueue and the sweep's backstop enqueue into one message.
type Notifier = Callable[[str], Awaitable[None]]

_NOTE_PREFIX: Final[str] = f"{CHECKOUTUZ_PROVIDER_NAME}:"


class SettleStatus(StrEnum):
    """What one settlement attempt concluded. Closed: the poll counts each one separately."""

    #: Money confirmed, intent claimed, sale written (or skipped for an erased buyer).
    SETTLED = "settled"
    #: The payment had already left ``pending`` — settled, expired or orphaned by an earlier run.
    REPLAY = "replay"
    #: No such order, or it belongs to an intent of another rail. Nothing was asked or written.
    UNKNOWN = "unknown"
    #: checkout.uz says the payment is not paid (yet). ``last_polled_at`` was stamped.
    NOT_PAID = "not_paid"
    #: Paid, but not the amount we asked for. Recorded ``orphan_paid`` for a manual refund.
    MISMATCH = "mismatch"
    #: Paid, but the intent was already paid through another link. ``orphan_paid``, no grant.
    ORPHAN = "orphan"
    #: checkout.uz or the database could not be asked right now. Nothing was settled; ask again.
    #: When checkout.uz answered with an error, ``last_polled_at`` was stamped so the row
    #: rotates to the back of both poll batches rather than blocking their heads.
    RETRY_LATER = "retry_later"


@dataclass(frozen=True, slots=True)
class SettleOutcome:
    """The result of :func:`settle_checkoutuz_order`. ``public_ref`` is set once it is known."""

    status: SettleStatus
    order_id: int
    public_ref: str | None = None
    #: Meaningful on ``RETRY_LATER`` only: ``False`` when checkout.uz's error is one that asking
    #: again will not change (a 4xx, a malformed reply, an answer about another order).
    retryable: bool = True


def settle_note(order_id: int) -> str:
    """The ``payment_intents.settle_note`` a checkout.uz settlement writes: ``checkoutuz:<id>``."""
    return f"{_NOTE_PREFIX}{order_id}"


async def settle_checkoutuz_order(
    session_factory: async_sessionmaker[AsyncSession],
    client: CheckoutUzApi,
    *,
    order_id: int,
    notifier: Notifier | None,
    now: datetime,
) -> SettleOutcome:
    """Ask checkout.uz about ``order_id`` and, if it is paid as agreed, grant it. Never raises."""
    try:
        return await _settle(session_factory, client, order_id=order_id, notifier=notifier, now=now)
    except Exception as exc:
        # The transaction rolled back with the exception, so nothing was half-written; the next
        # poll asks again. Logged at ERROR because the expected failures are all handled below.
        _LOG.error(
            "a checkout.uz settlement failed and was rolled back",
            extra={"event": "checkoutuz.settle_failed", "order_id": order_id},
            exc_info=exc,
        )
        return SettleOutcome(SettleStatus.RETRY_LATER, order_id)


async def _settle(
    session_factory: async_sessionmaker[AsyncSession],
    client: CheckoutUzApi,
    *,
    order_id: int,
    notifier: Notifier | None,
    now: datetime,
) -> SettleOutcome:
    # 1. What do we have on file? A read-only session, closed before the network call.
    async with session_factory() as session:
        found = await payment_with_intent(session, order_id)
        if found is None:
            _LOG.warning(
                "checkout.uz settlement was asked about an order that is not on file",
                extra={"event": "checkoutuz.unknown_order", "order_id": order_id},
            )
            return SettleOutcome(SettleStatus.UNKNOWN, order_id)
        payment, intent = found
        public_ref = intent.public_ref
        if intent.provider != CHECKOUTUZ_PROVIDER_NAME:
            _LOG.error(
                "a checkout.uz order points at an intent of another rail; refusing to settle",
                extra={
                    "event": "checkoutuz.foreign_intent",
                    "order_id": order_id,
                    "public_ref": public_ref,
                    "intent_provider": intent.provider,
                },
            )
            return SettleOutcome(SettleStatus.UNKNOWN, order_id, public_ref)
        # ``expired`` is still settleable: the final check closes a link checkout.uz kept
        # saying was pending, but a page left open can be paid after that, and the webhook for
        # it is never retried. Only ``paid`` and ``orphan_paid`` are final.
        if payment.state not in _SETTLEABLE_PAYMENT_STATES:
            return SettleOutcome(SettleStatus.REPLAY, order_id, public_ref)
        from_state = payment.state
        intent_id = intent.id
        recorded_som = payment.amount_som
        intent_amount_minor = intent.amount_minor

    # 2. Ask checkout.uz — outside any transaction.
    answer = await client.status_payment(order_id=order_id)
    if isinstance(answer, Err):
        retryable = answer.error.is_retryable
        # A non-retryable error (a 4xx, a malformed reply, an answer about another order) will
        # not cure itself, and the order behind it may be paid: ERROR, so a human looks.
        _LOG.log(
            logging.WARNING if retryable else logging.ERROR,
            "checkout.uz could not say whether an order is paid; will ask again",
            extra={
                "event": "checkoutuz.status_unavailable",
                "order_id": order_id,
                "public_ref": public_ref,
                **answer.error.to_log_dict(),
            },
        )
        # Stamp the attempt, in its own small transaction, conditional on ``pending``: without
        # it a row that keeps failing keeps ``last_polled_at`` NULL / oldest and sits at the
        # head of every poll and final-check batch, starving the rows behind it.
        await _stamp_attempt(session_factory, order_id, now)
        return SettleOutcome(SettleStatus.RETRY_LATER, order_id, public_ref, retryable=retryable)
    status = answer.value

    # 3. The checks. ``status_payment`` already refused a reply about another id; the equality
    #    is restated here because this is the function whose correctness depends on it.
    if status.order_id != order_id or status.status != CheckoutUzStatus.PAID.value:
        async with session_factory.begin() as session:
            await stamp_polled(session, order_id, now)
        return SettleOutcome(SettleStatus.NOT_PAID, order_id, public_ref)
    if (
        status.amount_som != recorded_som
        or status.amount_som * TIYIN_PER_SOM != intent_amount_minor
    ):
        # Real money (the answer came from checkout.uz, not from the webhook) for the wrong
        # amount. Granting is wrong and so is polling it forever, so it is closed as
        # ``orphan_paid`` — the state that already means "paid, not granted, refund by hand".
        async with session_factory.begin() as session:
            await mark_payment(
                session,
                order_id,
                frm=from_state,
                to=CheckoutUzPaymentState.ORPHAN_PAID,
                now=now,
                paid_at=now,
            )
        _LOG.error(
            "checkout.uz reports a payment for a different amount; not granted, refund by hand",
            extra={
                "event": "checkoutuz.amount_mismatch",
                "order_id": order_id,
                "public_ref": public_ref,
                "paid_som": status.amount_som,
                "recorded_som": recorded_som,
                "intent_amount_minor": intent_amount_minor,
            },
        )
        return SettleOutcome(SettleStatus.MISMATCH, order_id, public_ref)

    # 4. The money, in one transaction.
    async with session_factory.begin() as session:
        won = await mark_payment(
            session,
            order_id,
            frm=from_state,
            to=CheckoutUzPaymentState.PAID,
            now=now,
            paid_at=now,
        )
        if not won:
            return SettleOutcome(SettleStatus.REPLAY, order_id, public_ref)
        if from_state is CheckoutUzPaymentState.EXPIRED:
            _LOG.error(
                "a checkout.uz link was paid after the final check closed it; settling it now",
                extra={
                    "event": "checkoutuz.paid_after_expiry",
                    "order_id": order_id,
                    "public_ref": public_ref,
                },
            )
        claimed = await claim_intent_for_checkoutuz(
            session, intent_id=intent_id, now=now, note=settle_note(order_id)
        )
        if not claimed:
            await mark_payment(
                session,
                order_id,
                frm=CheckoutUzPaymentState.PAID,
                to=CheckoutUzPaymentState.ORPHAN_PAID,
                now=now,
                paid_at=now,
            )
            _LOG.error(
                "a checkout.uz order was paid for an intent that is already paid; refund by hand",
                extra={
                    "event": "checkoutuz.double_payment",
                    "order_id": order_id,
                    "public_ref": public_ref,
                },
            )
            return SettleOutcome(SettleStatus.ORPHAN, order_id, public_ref)
        # Re-read inside the transaction: ``telegram_user_id`` may have been erased since step 1,
        # and the claim above is a Core UPDATE the step-1 objects know nothing about.
        reread = await payment_with_intent(session, order_id)
        if reread is None:  # pragma: no cover - the row was just updated in this transaction
            raise StorageError(
                "a checkout.uz order vanished inside its own settlement",
                context={"order_id": order_id},
            )
        fresh = reread[1]
        if fresh.telegram_user_id is None:
            _LOG.warning(
                "a checkout.uz payment settled for a buyer who has since been forgotten",
                extra={
                    "event": "checkoutuz.paid_after_forget",
                    "order_id": order_id,
                    "public_ref": public_ref,
                },
            )
        else:
            await _write_sale(
                session,
                intent=fresh,
                telegram_user_id=fresh.telegram_user_id,
                order_id=order_id,
                now=now,
            )

    _LOG.info(
        "a checkout.uz payment was settled",
        extra={
            "event": "checkoutuz.settled",
            "order_id": order_id,
            "public_ref": public_ref,
            "amount_som": status.amount_som,
        },
    )

    # 5. Tell the buyer — after the commit, best-effort.
    if notifier is not None:
        try:
            await notifier(public_ref)
        except Exception as exc:
            _LOG.error(
                "a settled checkout.uz payment could not be queued for announcement; "
                "the sweep will re-enqueue it",
                extra={
                    "event": "checkoutuz.notify_enqueue_failed",
                    "order_id": order_id,
                    "public_ref": public_ref,
                    "failure": repr(exc),
                },
            )
    return SettleOutcome(SettleStatus.SETTLED, order_id, public_ref)


async def _stamp_attempt(
    session_factory: async_sessionmaker[AsyncSession], order_id: int, now: datetime
) -> None:
    """Best-effort ``last_polled_at`` stamp after a failed ask. A failure here is only logged:
    the outcome is RETRY_LATER either way, and the next run stamps again."""
    try:
        async with session_factory.begin() as session:
            await stamp_polled(session, order_id, now)
    except Exception as exc:
        _LOG.warning(
            "a failed checkout.uz status check could not be stamped",
            extra={"event": "checkoutuz.stamp_failed", "order_id": order_id},
            exc_info=exc,
        )


async def _write_sale(
    session: AsyncSession,
    *,
    intent: PaymentIntentRow,
    telegram_user_id: int,
    order_id: int,
    now: datetime,
) -> None:
    """The receipt and the grant, through the shared primitives, under the intent's key.

    The same routing ``bayram.db.payme.SqlPaymeLedger._write_sale`` performs: the product on the
    INTENT decides. ``reference`` is checkout.uz's order id, which is what an operator searches
    for in the checkout.uz dashboard.
    """
    purchase = Purchase(
        product=Product(intent.product.value),
        provider=CHECKOUTUZ_PROVIDER_NAME,
        reference=str(order_id),
        amount_minor=intent.amount_minor,
        currency=intent.currency,
        is_paid=True,
    )
    if intent.product is IntentProduct.SINGLE:
        await write_single_sale(
            session,
            telegram_user_id=telegram_user_id,
            purchase=purchase,
            idempotency_key=intent.idempotency_key,
            now=now,
        )
        return
    if intent.plan_songs is None or intent.plan_days is None:
        # Unreachable through any write this system performs (a CHECK constraint holds it), and
        # raised rather than defaulted so the transaction unwinds the claim with it.
        raise StorageError(
            "a plan intent reached checkout.uz settlement without its plan snapshot",
            context={"public_ref": intent.public_ref, "order_id": order_id},
        )
    await write_plan_sale(
        session,
        telegram_user_id=telegram_user_id,
        purchase=purchase,
        songs=intent.plan_songs,
        days=intent.plan_days,
        idempotency_key=intent.idempotency_key,
        now=now,
    )
