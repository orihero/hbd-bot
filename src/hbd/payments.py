"""The payment seam — deliberately a no-op for this build.

Payment is out of scope: no Stars, no Click, no Payme, no invoices, no ledger. What *is*
in scope is the seam, so the real rail drops in later without touching a handler or the
orchestrator. Both call ``PaymentProvider.authorize`` and both already branch on the
result; swapping this class for a real one is a wiring change in the composition root.

``NoopPaymentProvider`` therefore authorises everything, records nothing and charges
nothing — and it still returns a ``Result``, so the failure path at every call site is
written and exercised from day one instead of being invented under pressure the day
billing lands.

This module is the canonical home. ``hbd.bot.payment`` re-exports it so the bot package
keeps its historical import path without owning a second copy.
"""

from __future__ import annotations

from typing import Final
from uuid import UUID, uuid4

from hbd.contracts import PaymentAuthorization, Result, ok
from hbd.logging import get_logger

__all__ = ["NoopPaymentProvider", "NOOP_PROVIDER_NAME", "FREE_AMOUNT_MINOR", "DEFAULT_CURRENCY"]

_LOG = get_logger(__name__)

NOOP_PROVIDER_NAME: Final[str] = "noop"
#: Nothing is charged in this build. The field exists because the protocol has it.
FREE_AMOUNT_MINOR: Final[int] = 0
#: Uzbek sum. ISO-4217, three letters, as ``PaymentAuthorization`` requires.
DEFAULT_CURRENCY: Final[str] = "UZS"


class NoopPaymentProvider:
    """Always authorises. Structurally satisfies ``hbd.contracts.PaymentProvider``."""

    name: str = NOOP_PROVIDER_NAME

    async def authorize(
        self, *, order_id: UUID, amount_minor: int, currency: str
    ) -> Result[PaymentAuthorization]:
        reference = f"{NOOP_PROVIDER_NAME}-{uuid4().hex}"
        _LOG.info(
            "payment authorised by the no-op provider",
            extra={
                "order_id": str(order_id),
                "amount_minor": amount_minor,
                "currency": currency,
                "reference": reference,
            },
        )
        return ok(
            PaymentAuthorization(
                order_id=order_id,
                provider=NOOP_PROVIDER_NAME,
                reference=reference,
                amount_minor=amount_minor,
                currency=currency,
                is_authorized=True,
            )
        )
