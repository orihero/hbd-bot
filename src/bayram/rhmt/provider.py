"""The checkout provider for Rahmat (rhmt.uz / MultiCard).

Implements ``bayram.checkout.CheckoutProvider``:
  - Opens a PaymentIntent row (provider="rhmt", public_ref as invoice_id)
  - Contacts Rahmat REST API to create an invoice and get checkout_url
  - Returns unpaid Purchase(checkout_url=...) to redirect customer
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Final

from bayram.checkout import PaymentIntentOpener, Product, Purchase, PurchaseRequest
from bayram.contracts import Err, Language, Result, err, ok
from bayram.errors import CheckoutPausedError
from bayram.logging import get_logger
from bayram.rhmt.client import RhmtClient
from bayram.rhmt.ports import RHMT_PROVIDER_NAME

__all__ = ["RHMT_PROVIDER_NAME", "RhmtCheckoutProvider"]

_LOG = get_logger(__name__)

_PAUSED_MESSAGE: Final[str] = "the checkout rail is paused; no intent was opened"


class RhmtCheckoutProvider:
    """Starts a Rahmat payment by opening a PaymentIntent and calling Rahmat's invoice API.

    Satisfies ``bayram.checkout.CheckoutProvider`` structurally without subclassing it.
    """

    name: str = RHMT_PROVIDER_NAME

    def __init__(
        self,
        opener: PaymentIntentOpener,
        client: RhmtClient,
        *,
        store_id: int,
        callback_url: str,
        return_url: str,
        is_sandbox: bool,
        plan_songs: int,
        plan_days: int,
        language_of: Callable[[], Language],
        paused: Callable[[], Awaitable[bool]],
    ) -> None:
        self._opener = opener
        self._client = client
        self._store_id = store_id
        self._callback_url = callback_url
        self._return_url = return_url
        self._is_sandbox = is_sandbox
        self._plan_songs = plan_songs
        self._plan_days = plan_days
        self._language_of = language_of
        self._paused = paused

    async def charge(self, request: PurchaseRequest) -> Result[Purchase]:
        """Open an intent and call Rahmat API to obtain checkout_url. Never raises."""
        if await self._is_rail_paused():
            _LOG.info(
                "a purchase was refused because the checkout rail is paused",
                extra={
                    "telegram_user_id": request.telegram_user_id,
                    "product": request.product.value,
                    "idempotency_key": request.idempotency_key,
                },
            )
            return err(
                CheckoutPausedError(
                    _PAUSED_MESSAGE,
                    context={
                        "product": request.product.value,
                        "idempotency_key": request.idempotency_key,
                    },
                )
            )

        language = self._language_of()
        lang_code = language.value if isinstance(language, Language) else str(language)

        is_plan = request.product is Product.STARTER
        intent_res = await self._opener.open_intent(
            telegram_user_id=request.telegram_user_id,
            product=request.product,
            amount_minor=request.amount_minor,
            currency=request.currency,
            idempotency_key=request.idempotency_key,
            language=lang_code,
            merchant_id=str(self._store_id),
            is_sandbox=self._is_sandbox,
            plan_songs=self._plan_songs if is_plan else None,
            plan_days=self._plan_days if is_plan else None,
            resume_order_id=request.resume_order_id,
            provider=RHMT_PROVIDER_NAME,
        )

        if isinstance(intent_res, Err):
            _LOG.error(
                "failed to open payment intent for rhmt",
                extra={"error": intent_res.error.to_log_dict()},
            )
            return intent_res

        intent = intent_res.value

        invoice_res = await self._client.create_invoice(
            store_id=self._store_id,
            amount_minor=request.amount_minor,
            invoice_id=intent.public_ref,
            callback_url=self._callback_url,
            return_url=self._return_url,
            language=lang_code,
            ttl_s=_seconds_left(intent.valid_until),
        )
        if isinstance(invoice_res, Err):
            _LOG.error(
                "failed to create invoice at rhmt",
                extra={"error": invoice_res.error.to_log_dict()},
            )
            return invoice_res

        invoice = invoice_res.value
        _LOG.info(
            "rahmat invoice created successfully",
            extra={
                "public_ref": intent.public_ref,
                "rhmt_uuid": invoice.uuid,
                "checkout_url": invoice.checkout_url,
            },
        )

        return ok(
            Purchase(
                product=request.product,
                provider=RHMT_PROVIDER_NAME,
                reference=intent.public_ref,
                amount_minor=request.amount_minor,
                currency=request.currency,
                is_paid=False,
                checkout_url=invoice.checkout_url,
            )
        )

    async def _is_rail_paused(self) -> bool:
        """Read the pause switch, failing open if the check fails."""
        try:
            return bool(await self._paused())
        except Exception as exc:
            _LOG.warning(
                "failed to read checkout pause switch; failing open",
                extra={"error": str(exc)},
            )
            return False


#: Multicard's floor is not documented; a link that dies inside a minute is not a product.
_MIN_INVOICE_TTL_S: Final[int] = 60


def _seconds_left(valid_until: datetime) -> int:
    """How long the invoice may stay payable: exactly as long as our intent does.

    Multicard keeps an invoice payable for a day unless told otherwise, while the intent
    expires sooner. A payment in between reached a callback with nothing left to settle and
    the customer's money was kept. Matching the two closes that window at the source.
    """
    remaining = int((valid_until - datetime.now(UTC)).total_seconds())
    return max(_MIN_INVOICE_TTL_S, remaining)
