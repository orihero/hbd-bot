"""The inbound webhook handler and settlement service for Rahmat (rhmt.uz).

Processes callbacks sent by Rahmat:
  - Verifies HMAC / hash signature
  - Idempotently handles duplicate webhooks
  - Atomically claims the PaymentIntent, writes the receipt, and grants entitlement
  - Enqueues Telegram notification and render-resume background jobs
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Any

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from bayram.checkout import Product, Purchase
from bayram.db.credit_sql import rowcount_of
from bayram.db.enums import PaymentIntentState
from bayram.db.fulfilment import write_plan_sale, write_single_sale
from bayram.db.models.payment_intent import PaymentIntentRow
from bayram.db.payme_sql import intent_by_ref
from bayram.logging import get_logger
from bayram.rhmt.ports import (
    DEFAULT_CALLBACK_SCHEME,
    RHMT_PROVIDER_NAME,
    RhmtCallbackScheme,
    RhmtInvoiceStatus,
)
from bayram.rhmt.verify import verify_rhmt_webhook

#: Shown to the payer by Multicard on the failed-payment receipt. Uzbek and Russian, because
#: the intent's language is not threaded this far and these are the two the bot sells in most.
_NOT_PAYABLE_MESSAGE = (
    "Toʻlov havolasining muddati tugagan, pul kartangizga qaytariladi. / "
    "Срок ссылки на оплату истёк, деньги вернутся на карту."
)


def utc_now() -> datetime:
    return datetime.now(UTC)


__all__ = ["RhmtWebhookService"]

_LOG = get_logger(__name__)

type NotifyEnqueue = Callable[[str], Awaitable[None]]


class RhmtWebhookService:
    """Processes Rahmat payment callbacks and settles intents atomically."""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        *,
        secret: str,
        scheme: str = DEFAULT_CALLBACK_SCHEME,
        notify_enqueue: NotifyEnqueue | None = None,
        notifier: NotifyEnqueue | None = None,
        clock: Callable[[], datetime] = utc_now,
    ) -> None:
        self._sessions = session_factory
        self._secret = secret
        self._scheme = scheme
        self._notify_enqueue = notifier if notifier is not None else notify_enqueue
        self._clock = clock

    async def handle_callback(self, payload: dict[str, Any]) -> tuple[int, dict[str, Any]]:
        """Verify and settle an inbound Rahmat payment webhook.

        Returns (HTTP status code, response body dict).
        """
        # 1. Verify signature
        if not verify_rhmt_webhook(payload, secret=self._secret, scheme=self._scheme):
            _LOG.warning("rhmt webhook signature verification failed", extra={"payload": payload})
            return 400, {"success": False, "error": "invalid signature"}

        invoice_id = str(payload.get("invoice_id") or "").strip()
        uuid = str(payload.get("uuid") or "").strip()
        status_str = str(payload.get("status") or "").lower().strip()
        # The legacy 'success' callback carries no status field: Rahmat sends it only once a
        # payment has succeeded, so its arrival IS the success. Without this, a verified
        # payment fell through to the draft/progress no-op and was acknowledged unsettled.
        if not status_str and self._scheme == RhmtCallbackScheme.SUCCESS.value:
            status_str = RhmtInvoiceStatus.SUCCESS.value
        raw_amount = payload.get("amount")

        if not invoice_id:
            return 400, {"success": False, "error": "missing invoice_id"}

        try:
            amount_minor = int(raw_amount)  # type: ignore[arg-type]
        except (TypeError, ValueError):
            return 400, {"success": False, "error": "invalid amount"}

        now = self._clock()

        async with self._sessions.begin() as session:
            row = await intent_by_ref(session, invoice_id)
            if row is None:
                _LOG.error(
                    "rhmt callback arrived for unknown invoice_id",
                    extra={"invoice_id": invoice_id},
                )
                return 404, {"success": False, "error": "intent not found"}

            # Idempotency check: already paid?
            if row.state == PaymentIntentState.PAID:
                _LOG.info(
                    "rhmt callback for already-paid intent; acknowledging replay",
                    extra={"invoice_id": invoice_id},
                )
                return 200, {"success": True, "message": "already settled"}

            # Status handling
            if status_str == RhmtInvoiceStatus.SUCCESS.value:
                if row.amount_minor != amount_minor:
                    _LOG.error(
                        "rhmt callback amount mismatch",
                        extra={
                            "expected": row.amount_minor,
                            "received": amount_minor,
                            "invoice_id": invoice_id,
                        },
                    )
                    return 400, {"success": False, "error": "amount mismatch"}

                # Atomic settlement: update intent state
                res = await session.execute(
                    sa.update(PaymentIntentRow)
                    .where(
                        PaymentIntentRow.id == row.id,
                        PaymentIntentRow.state.in_(
                            (PaymentIntentState.PENDING, PaymentIntentState.AWAITING)
                        ),
                    )
                    .values(
                        state=PaymentIntentState.PAID,
                        settled_at=now,
                        settle_note=f"rhmt:{uuid}",
                        updated_at=now,
                    )
                )
                if rowcount_of(res) != 1:
                    state = await session.scalar(
                        sa.select(PaymentIntentRow.state).where(PaymentIntentRow.id == row.id)
                    )
                    if state == PaymentIntentState.PAID:
                        _LOG.info(
                            "rhmt intent was claimed by a concurrent callback; acknowledging",
                            extra={"invoice_id": invoice_id},
                        )
                        return 200, {"success": True, "message": "already claimed"}
                    # Expired or cancelled: nothing will be granted for this money. Answering
                    # success would let Multicard keep it; anything but success makes it
                    # refund the card, and ``message`` is shown to the payer on the receipt.
                    _LOG.error(
                        "rhmt payment arrived for an intent that is no longer payable; "
                        "refusing so Multicard refunds the card",
                        extra={"invoice_id": invoice_id, "state": str(state), "uuid": uuid},
                    )
                    return 409, {"success": False, "message": _NOT_PAYABLE_MESSAGE}

                # Write receipt & entitlement grant under the intent's idempotency key
                purchase = Purchase(
                    product=Product(row.product.value),
                    provider=RHMT_PROVIDER_NAME,
                    reference=uuid or invoice_id,
                    amount_minor=amount_minor,
                    currency=row.currency,
                    is_paid=True,
                )

                if row.telegram_user_id is not None:
                    if (
                        row.product.value == Product.STARTER.value
                        and row.plan_songs
                        and row.plan_days
                    ):
                        await write_plan_sale(
                            session,
                            telegram_user_id=row.telegram_user_id,
                            purchase=purchase,
                            songs=row.plan_songs,
                            days=row.plan_days,
                            idempotency_key=row.idempotency_key,
                            now=now,
                        )
                    else:
                        await write_single_sale(
                            session,
                            telegram_user_id=row.telegram_user_id,
                            purchase=purchase,
                            idempotency_key=row.idempotency_key,
                            now=now,
                        )

                _LOG.info(
                    "rhmt payment settled successfully",
                    extra={
                        "invoice_id": invoice_id,
                        "uuid": uuid,
                        "amount_minor": amount_minor,
                        "telegram_user_id": row.telegram_user_id,
                    },
                )
            elif status_str in (RhmtInvoiceStatus.ERROR.value, RhmtInvoiceStatus.REVERT.value):
                await session.execute(
                    sa.update(PaymentIntentRow)
                    .where(
                        PaymentIntentRow.id == row.id,
                        PaymentIntentRow.state.in_(
                            (PaymentIntentState.PENDING, PaymentIntentState.AWAITING)
                        ),
                    )
                    .values(
                        state=PaymentIntentState.CANCELLED,
                        updated_at=now,
                    )
                )
                _LOG.info(
                    "rhmt payment cancelled or reverted",
                    extra={"invoice_id": invoice_id, "status": status_str},
                )
                return 200, {"success": True}
            else:
                # Draft / progress / billing
                return 200, {"success": True}

        # After commit: enqueue notification and render resume
        if status_str == RhmtInvoiceStatus.SUCCESS.value and self._notify_enqueue is not None:
            try:
                await self._notify_enqueue(invoice_id)
            except Exception as exc:
                _LOG.error(
                    "failed to enqueue rhmt notification job",
                    extra={"invoice_id": invoice_id, "error": str(exc)},
                )

        return 200, {"success": True}
