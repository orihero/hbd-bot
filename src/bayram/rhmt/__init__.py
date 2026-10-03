"""Rahmat (rhmt.uz / MultiCard) acquiring rail integration for Bayram bot.

Only the leaf vocabulary is re-exported here, as in :mod:`bayram.checkoutuz`. Everything else
is imported from its own module, so importing this package never pulls in a web framework,
an HTTP client or the database — the worker imports the client and the provider, and
``tests/test_runtime/test_broadcast_expand.py`` pins that it loads no web framework:

* :mod:`bayram.rhmt.client` — ``RhmtClient``, the vendor calls.
* :mod:`bayram.rhmt.provider` — ``RhmtCheckoutProvider`` (the bot's ``charge``).
* :mod:`bayram.rhmt.settings` — ``RhmtSettings`` and ``build_rhmt_settings``.
* :mod:`bayram.rhmt.verify` — ``verify_rhmt_webhook``.
* :mod:`bayram.rhmt.service` — ``RhmtWebhookService``, which settles.
* :mod:`bayram.rhmt.app` — the FastAPI webhook router; imported by the payment process only.
"""

from bayram.rhmt.ports import (
    DEFAULT_CALLBACK_SCHEME,
    DEFAULT_RHMT_RETURN_URL,
    RHMT_PROD_BASE_URL,
    RHMT_PROVIDER_NAME,
    RHMT_SANDBOX_BASE_URL,
    RhmtCallbackScheme,
    RhmtInvoiceStatus,
)

__all__ = [
    "RHMT_PROVIDER_NAME",
    "RHMT_PROD_BASE_URL",
    "RHMT_SANDBOX_BASE_URL",
    "DEFAULT_RHMT_RETURN_URL",
    "DEFAULT_CALLBACK_SCHEME",
    "RhmtCallbackScheme",
    "RhmtInvoiceStatus",
]
