"""Historical import path for the no-op payment provider.

The implementation moved to :mod:`bayram.payments`, because the orchestrator authorises too
and neither of them should have to import the other's package to do it. Re-exported here
rather than duplicated: two copies of an "always authorises" class is exactly how the day
billing lands turns into a bug hunt.

``CreditGatedPaymentProvider`` is re-exported for the same reason and with a caveat: the
bot must import it to *name* it (a test asserting the bot's provider is NOT gated has to
have the type in hand), never to wire it. The credit debit belongs to the worker alone —
see the class docstring in :mod:`bayram.payments` for the three uncompensated early returns in
``confirm._authorize_and_submit`` that make a bot-side charge unrecoverable.
"""

from __future__ import annotations

from bayram.payments import (
    CREDIT_GATED_PROVIDER_NAME,
    DEFAULT_CURRENCY,
    FREE_AMOUNT_MINOR,
    NOOP_PROVIDER_NAME,
    CreditGatedPaymentProvider,
    NoopPaymentProvider,
)

__all__ = [
    "NoopPaymentProvider",
    "NOOP_PROVIDER_NAME",
    "FREE_AMOUNT_MINOR",
    "DEFAULT_CURRENCY",
    "CreditGatedPaymentProvider",
    "CREDIT_GATED_PROVIDER_NAME",
]
