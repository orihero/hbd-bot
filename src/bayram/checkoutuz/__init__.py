"""checkout.uz (Click / Payme aggregator) hosted-checkout rail. See ``DECISIONS.md D28``.

Only the leaf vocabulary is re-exported here. Everything else is imported from its own
module, so importing this package never pulls in an HTTP client or the database:

* :mod:`bayram.checkoutuz.client` — the two vendor calls, strict and never raising.
* :mod:`bayram.checkoutuz.provider` — ``CheckoutUzCheckoutProvider`` (the bot's ``charge``) and
  the payment store it records links in.
* :mod:`bayram.checkoutuz.settle` — ``settle_checkoutuz_order``, the ONLY code that grants.
* :mod:`bayram.checkoutuz.app` — the unsigned webhook route; it enqueues, never settles.
* :mod:`bayram.checkoutuz.jobs` — the worker's reconcile job and the poll cron.
"""

from bayram.checkoutuz.ports import (
    CHECKOUTUZ_PROVIDER_NAME,
    LINK_REUSE_MARGIN_S,
    MAX_AMOUNT_SOM,
    MIN_AMOUNT_SOM,
    POLL_GRACE_S,
    TIYIN_PER_SOM,
    CheckoutUzStatus,
    som_from_minor,
)

__all__ = [
    "CHECKOUTUZ_PROVIDER_NAME",
    "MIN_AMOUNT_SOM",
    "MAX_AMOUNT_SOM",
    "LINK_REUSE_MARGIN_S",
    "POLL_GRACE_S",
    "TIYIN_PER_SOM",
    "CheckoutUzStatus",
    "som_from_minor",
]
