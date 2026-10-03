"""Constants, the status vocabulary and the one money conversion for the checkout.uz rail.

checkout.uz is a hosted payment page in front of Click and Payme: ``POST /create_payment``
returns an ``_id`` and a ``_url`` the customer opens, and ``POST /status_payment`` reports
``pending`` or ``paid`` for that id. Its webhook is unsigned and never retried, so the worker's
poll of ``status_payment`` is the source of truth and the webhook only makes it arrive sooner
(``DECISIONS.md D28``).

This module is the rail's leaf: it imports nothing from the rest of the package, so the
provider, the client, the gateway route and the worker job can all share these names without
any of them importing another. It touches no network and no database.

**The rail quotes SOM; this system stores TIYIN.** Every amount in ``bayram.checkout`` is minor
units, so :func:`som_from_minor` is the one place the unit changes, and it REFUSES rather than
rounds. A price that is not a whole number of som, or lies outside the rail's documented
``1_000..10_000_000`` range, is a configuration error to surface before an intent is opened —
rounding it would charge the customer a different number from the one they were shown.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Final

from bayram.contracts import Result, err, ok
from bayram.errors import CheckoutError

__all__ = [
    "CHECKOUTUZ_PROVIDER_NAME",
    "MIN_AMOUNT_SOM",
    "MAX_AMOUNT_SOM",
    "LINK_REUSE_MARGIN_S",
    "FINAL_CHECK_GIVE_UP_S",
    "POLL_GRACE_S",
    "TIYIN_PER_SOM",
    "CheckoutUzStatus",
    "som_from_minor",
]

#: The identifier stored on ``payment_intents.provider`` and on every receipt, and this rail's
#: ``CheckoutProvider.name``. Spelled as a literal in ``bayram.checkout_rails`` too, because
#: that module may not import a rail package; a test pins the two together.
CHECKOUTUZ_PROVIDER_NAME: Final[str] = "checkoutuz"

#: The documented bounds of ``create_payment.amount``, in som, inclusive.
MIN_AMOUNT_SOM: Final[int] = 1_000
MAX_AMOUNT_SOM: Final[int] = 10_000_000

#: Minor units per major unit for UZS.
TIYIN_PER_SOM: Final[int] = 100

#: A payment link lives ``_lifteme`` seconds (3600 today). An existing link is handed out again
#: only while it has at least this long left, so a customer is never sent to a page that
#: expires while they are typing their card number; otherwise a fresh payment is created.
LINK_REUSE_MARGIN_S: Final[int] = 60

#: How long after a link's own expiry the poller keeps asking about it. Undocumented, but a
#: page left open past ``_lifteme`` can still be paid, and money taken with nobody polling
#: is money with no credit — so the poller looks a little past the end before giving up.
POLL_GRACE_S: Final[int] = 900

#: How long after a link's own expiry the final check keeps re-asking about an order
#: checkout.uz will not answer for (every attempt RETRY_LATER). Past this, the row is closed
#: ``expired`` with an ERROR ``checkoutuz.final_check_unresolved`` naming the order, for a
#: human to look up in the checkout.uz dashboard. A time cap rather than "close on the first
#: non-retryable error", because a revoked or mistyped API key makes EVERY answer a
#: non-retryable 401 — closing on that would expire every lapsed link in one run. A day gives an
#: operator room to notice and fix such a fault first.
FINAL_CHECK_GIVE_UP_S: Final[int] = 86_400


class CheckoutUzStatus(StrEnum):
    """The payment statuses checkout.uz documents. Anything else is treated as not paid."""

    PENDING = "pending"
    PAID = "paid"


def som_from_minor(amount_minor: int) -> Result[int]:
    """Convert a tiyin amount to the som checkout.uz takes, or refuse. **Never rounds.**

    ``Err(CheckoutError)`` when the amount is not a whole number of som or lies outside
    :data:`MIN_AMOUNT_SOM`..:data:`MAX_AMOUNT_SOM`. ``bool`` is refused too, since it is an
    ``int`` to Python and a price to nobody.
    """
    if isinstance(amount_minor, bool) or not isinstance(amount_minor, int):
        return err(
            CheckoutError(
                "checkout.uz amount is not an integer number of tiyin",
                context={"amount_minor": repr(amount_minor)},
            )
        )
    if amount_minor % TIYIN_PER_SOM != 0:
        return err(
            CheckoutError(
                "checkout.uz takes whole som; the amount has a tiyin remainder",
                context={"amount_minor": amount_minor},
            )
        )
    som = amount_minor // TIYIN_PER_SOM
    if not MIN_AMOUNT_SOM <= som <= MAX_AMOUNT_SOM:
        return err(
            CheckoutError(
                "checkout.uz amount is outside the rail's accepted range",
                context={
                    "amount_minor": amount_minor,
                    "amount_som": som,
                    "min_som": MIN_AMOUNT_SOM,
                    "max_som": MAX_AMOUNT_SOM,
                },
            )
        )
    return ok(som)
