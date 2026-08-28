"""Historical import path for the no-op payment provider.

The implementation moved to :mod:`hbd.payments`, because the orchestrator authorises too
and neither of them should have to import the other's package to do it. Re-exported here
rather than duplicated: two copies of an "always authorises" class is exactly how the day
billing lands turns into a bug hunt.
"""

from __future__ import annotations

from hbd.payments import (
    DEFAULT_CURRENCY,
    FREE_AMOUNT_MINOR,
    NOOP_PROVIDER_NAME,
    NoopPaymentProvider,
)

__all__ = ["NoopPaymentProvider", "NOOP_PROVIDER_NAME", "FREE_AMOUNT_MINOR", "DEFAULT_CURRENCY"]
