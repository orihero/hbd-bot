"""Constants, protocols and enums for the Rahmat (rhmt.uz / MultiCard) acquiring rail.

Rahmat is operated by AO "MULTICARD PAYMENT".
Endpoints:
  Production: https://mesh.multicard.uz
  Sandbox:    https://dev-mesh.multicard.uz
  Checkout:   https://app.rhmt.uz/{uuid}
"""

from __future__ import annotations

from enum import StrEnum
from typing import Final

__all__ = [
    "RHMT_PROVIDER_NAME",
    "RHMT_PROD_BASE_URL",
    "RHMT_SANDBOX_BASE_URL",
    "DEFAULT_RHMT_RETURN_URL",
    "DEFAULT_CALLBACK_SCHEME",
    "RhmtCallbackScheme",
    "RhmtInvoiceStatus",
]

#: The provider identifier stored on payment_intents, topup_purchases and receipts.
RHMT_PROVIDER_NAME: Final[str] = "rhmt"

#: Base URLs for Multicard / Rahmat API.
RHMT_PROD_BASE_URL: Final[str] = "https://mesh.multicard.uz"
RHMT_SANDBOX_BASE_URL: Final[str] = "https://dev-mesh.multicard.uz"

#: Default return URL after customer completes payment on Rahmat checkout.
#: Blank: the bot fills in ``https://t.me/<its own username>`` at boot, so a dev bot never sends
#: its testers to the production bot (``bayram.main.resolve_return_urls``).
DEFAULT_RHMT_RETURN_URL: Final[str] = ""

#: Default webhook signature verification scheme.
DEFAULT_CALLBACK_SCHEME: Final[str] = "webhooks"


class RhmtCallbackScheme(StrEnum):
    """The two signature schemes supported by Multicard/Rahmat:

    - WEBHOOKS (default): sha1(uuid + invoice_id + amount + secret)
    - SUCCESS (legacy):   md5(store_id + invoice_id + amount + secret)
    """

    WEBHOOKS = "webhooks"
    SUCCESS = "success"


class RhmtInvoiceStatus(StrEnum):
    """Rahmat transaction / invoice statuses."""

    DRAFT = "draft"
    PROGRESS = "progress"
    BILLING = "billing"
    HOLD = "hold"
    SUCCESS = "success"
    ERROR = "error"
    REVERT = "revert"
