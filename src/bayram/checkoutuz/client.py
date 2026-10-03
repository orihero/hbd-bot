"""The outbound HTTP client for checkout.uz — two calls, both strict, neither ever raising.

checkout.uz is a hosted page in front of Click and Payme. This rail needs exactly two of its
endpoints (``DECISIONS.md D28``):

* ``POST /create_payment`` — mint a payment for an amount in SOM and get back the ``_id`` the
  webhook and the status call will name it by, and the ``_url`` the customer opens.
* ``POST /status_payment`` — ask what happened to one ``_id``. **This is the only answer money
  is ever moved on.** The webhook is unsigned and arrives from the open internet, so the
  settlement asks here and checks the reply before it grants anything.

The other documented endpoints (direct card capture, fiscal receipts, balance, history) are
deliberately absent: a method that is not on this class cannot be called by mistake.

**Strict parsing is the security property, not pedantry.** A reply is accepted only when the
HTTP status is 2xx, the top-level ``status`` is ``"success"``, every id is a real integer and
``status_payment``'s ``data.id`` names the order that was asked about. Anything else is an
``Err(CheckoutError)``; the caller treats it as "no answer" and asks again later. A lenient
parser here would be the one place where a malformed reply could be read as "paid".

**The API key never leaves this object.** It is sent in the ``Authorization`` header and is
put into no log line, no error message and no error context — ``CheckoutError.context`` is
logged verbatim by every caller, so anything placed there is published.

Amounts here are SOM, the unit checkout.uz speaks. The tiyin/som boundary is crossed in
:func:`bayram.checkoutuz.ports.som_from_minor` and nowhere in this module.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Final, Protocol

import httpx

from bayram.contracts import Err, Result, err, ok
from bayram.errors import CheckoutError
from bayram.logging import get_logger

__all__ = [
    "DEFAULT_BASE_URL",
    "DEFAULT_LINK_LIFETIME_S",
    "DEFAULT_TIMEOUT_S",
    "MAX_PAY_VIA_ENTRIES",
    "CheckoutUzApi",
    "CheckoutUzClient",
    "CheckoutUzPayment",
    "CheckoutUzPaymentStatus",
]

_LOG = get_logger(__name__)

#: What a numeric field may look like when the API sends it as a string (it does; see
#: :func:`_positive_int` and :func:`_whole_number`).
_DIGITS: Final[re.Pattern[str]] = re.compile(r"[0-9]{1,18}")
_DECIMAL: Final[re.Pattern[str]] = re.compile(r"[0-9]{1,15}(?:\.[0-9]{1,4})?")

#: The production API root. There is no documented sandbox. Mirrors the
#: ``Settings.checkoutuz_base_url`` default, which is what is actually read in production.
DEFAULT_BASE_URL: Final[str] = "https://checkout.uz/api/v1"

DEFAULT_TIMEOUT_S: Final[float] = 10.0

#: What ``_lifteme._second`` says today. Used only when a reply omits it or garbles it: the
#: payment exists at checkout.uz by then, and refusing to record a real, payable link over a
#: missing lifetime would turn a cosmetic field into an unrecorded payment. The lifetime only
#: decides when a link stops being REUSED and when the poller stops asking about it.
DEFAULT_LINK_LIFETIME_S: Final[int] = 3600

#: The one value of the top-level ``status`` field that means the call itself worked.
_SUCCESS: Final[str] = "success"

#: How much of a non-JSON body an error context may carry. Enough to recognise an HTML error
#: page from a proxy; not enough to turn a log line into a dump.
_BODY_EXCERPT_CHARS: Final[int] = 200

#: How many per-method pages a link screen will carry. The live merchant has seven methods;
#: the cap only keeps a vendor defect from drawing a wall of buttons.
MAX_PAY_VIA_ENTRIES: Final[int] = 12

#: A ``_pay_via`` key is a method slug (``click``, ``payme``, ``card``…). It is shown, after
#: ``capitalize()``, as a button label when the bot has no brand name for it, so anything
#: that is not a short lowercase slug is dropped rather than drawn.
_PAY_VIA_KEY: Final[re.Pattern[str]] = re.compile(r"^[a-z0-9_]{1,32}$")


@dataclass(frozen=True, slots=True)
class CheckoutUzPayment:
    """A payment checkout.uz has just minted. ``order_id`` is its ``_id``; ``url`` is the page.

    ``raw`` is the parsed reply, kept for the one log line that records a failure to store the
    payment — the operator then has everything checkout.uz said, and can find it in the
    merchant dashboard by id.
    """

    order_id: int
    uuid: str
    url: str
    amount_som: int
    status: str
    lifetime_s: int
    raw: Mapping[str, Any]
    #: ``_pay_via``: ``(method, url)`` pairs, one page per enabled payment method, in the
    #: order checkout.uz sent them. Empty when the reply carried none — the link screen then
    #: falls back to the single general page in ``url``.
    pay_via: tuple[tuple[str, str], ...] = ()


@dataclass(frozen=True, slots=True)
class CheckoutUzPaymentStatus:
    """checkout.uz's current answer about one payment.

    ``status`` is passed through verbatim (``pending`` and ``paid`` are documented; anything
    else is undocumented and is treated as not paid by the settlement). ``paid_at`` is the
    vendor's own string, in an undocumented timezone, and is kept for the record only — the
    settlement stamps its own clock.
    """

    order_id: int
    amount_som: int
    status: str
    paid_at: str | None
    raw: Mapping[str, Any]


class CheckoutUzApi(Protocol):
    """The two calls the provider and the settlement make. The fakes in tests satisfy this."""

    async def create_payment(
        self,
        *,
        amount_som: int,
        description: str,
        webhook_url: str,
        return_url: str,
    ) -> Result[CheckoutUzPayment]: ...

    async def status_payment(self, *, order_id: int) -> Result[CheckoutUzPaymentStatus]: ...


class CheckoutUzClient:
    """Async client for checkout.uz. Satisfies :class:`CheckoutUzApi`. **Never raises.**

    Built per use by the worker (one per job run, closed in ``finally``) and once per process
    by the bot. ``http_client`` is injectable for tests; a client this object built itself is
    closed by :meth:`aclose`, and one it was handed is left to its owner.
    """

    def __init__(
        self,
        *,
        api_key: str,
        base_url: str = DEFAULT_BASE_URL,
        timeout_s: float = DEFAULT_TIMEOUT_S,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        self._api_key = api_key.strip()
        self._base_url = (base_url or DEFAULT_BASE_URL).rstrip("/")
        self._http = http_client or httpx.AsyncClient(timeout=timeout_s)
        self._owns_http = http_client is None

    @property
    def base_url(self) -> str:
        return self._base_url

    def __repr__(self) -> str:
        # Spelled out so a debugger, a traceback's locals or an f-string never prints the key.
        return f"CheckoutUzClient(base_url={self._base_url!r})"

    async def aclose(self) -> None:
        """Close the underlying HTTP client if this object built it."""
        if self._owns_http:
            await self._http.aclose()

    async def create_payment(
        self,
        *,
        amount_som: int,
        description: str,
        webhook_url: str,
        return_url: str,
    ) -> Result[CheckoutUzPayment]:
        """Mint one payment for ``amount_som``. Every call mints a NEW payment at checkout.uz.

        There is no idempotency key on this endpoint, which is why the provider looks for a
        live link of its own before calling it, and why a retry of this call is never made
        here: a timeout after checkout.uz created the payment would mint a second one.
        """
        payload: dict[str, Any] = {
            "amount": int(amount_som),
            "description": description,
            "webhook_url": webhook_url,
        }
        # Omitted when blank (the boot could not learn the bot's username): checkout.uz then
        # shows its own receipt page instead of being handed an empty URL to refuse.
        if return_url.strip():
            payload["return_url"] = return_url
        body = await self._post("/create_payment", payload)
        if isinstance(body, Err):
            return body
        payment = body.value.get("payment")
        if not isinstance(payment, Mapping):
            return err(_malformed("/create_payment", "the reply has no 'payment' object"))

        order_id = _positive_int(payment.get("_id"))
        uuid = payment.get("_uuid")
        url = payment.get("_url")
        amount = _whole_number(payment.get("_amount"))
        status = payment.get("_status")
        if order_id is None:
            return err(_malformed("/create_payment", "'payment._id' is not a positive integer"))
        if not isinstance(uuid, str) or not uuid.strip():
            return err(_malformed("/create_payment", "'payment._uuid' is missing"))
        if not isinstance(url, str) or not url.startswith("https://"):
            return err(_malformed("/create_payment", "'payment._url' is not an https URL"))
        if amount is None:
            return err(_malformed("/create_payment", "'payment._amount' is not a whole number"))
        if not isinstance(status, str):
            return err(_malformed("/create_payment", "'payment._status' is missing"))

        return ok(
            CheckoutUzPayment(
                order_id=order_id,
                uuid=uuid.strip(),
                url=url,
                amount_som=amount,
                status=status.strip().lower(),
                lifetime_s=_lifetime_s(payment, order_id=order_id),
                raw=body.value,
                pay_via=_pay_via(payment, order_id=order_id),
            )
        )

    async def status_payment(self, *, order_id: int) -> Result[CheckoutUzPaymentStatus]:
        """Ask checkout.uz what happened to ``order_id``. The settlement's only source of truth.

        A reply about a DIFFERENT order is refused rather than returned: it can only be a
        vendor defect, and reading it as an answer about ours is how one customer's payment
        would be credited to another.
        """
        body = await self._post("/status_payment", {"id": int(order_id)})
        if isinstance(body, Err):
            return body
        data = body.value.get("data")
        if not isinstance(data, Mapping):
            return err(_malformed("/status_payment", "the reply has no 'data' object"))

        answered_id = _positive_int(data.get("id"))
        amount = _whole_number(data.get("amount"))
        status = data.get("status")
        paid_at = data.get("paid_at")
        if answered_id is None:
            return err(_malformed("/status_payment", "'data.id' is not a positive integer"))
        if answered_id != order_id:
            return err(
                CheckoutError(
                    "checkout.uz answered about a different order than the one asked",
                    is_retryable=False,
                    context={"asked": order_id, "answered": answered_id},
                )
            )
        if amount is None:
            return err(_malformed("/status_payment", "'data.amount' is not a whole number"))
        if not isinstance(status, str):
            return err(_malformed("/status_payment", "'data.status' is missing"))

        return ok(
            CheckoutUzPaymentStatus(
                order_id=answered_id,
                amount_som=amount,
                status=status.strip().lower(),
                paid_at=paid_at if isinstance(paid_at, str) and paid_at.strip() else None,
                raw=body.value,
            )
        )

    # -- Internals ---------------------------------------------------------
    async def _post(self, path: str, payload: Mapping[str, Any]) -> Result[dict[str, Any]]:
        """POST ``payload`` and return the parsed body when the call itself succeeded.

        Transport failures and 5xx replies are retryable; everything else is not. The
        ``Authorization`` header is built here and only here.
        """
        url = f"{self._base_url}{path}"
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Accept": "application/json",
            "Content-Type": "application/json",
        }
        try:
            response = await self._http.post(url, json=dict(payload), headers=headers)
        except Exception as exc:
            # ``repr`` of the exception type only: an httpx error's message can quote the
            # request, and the request carries the header.
            _LOG.warning(
                "checkout.uz request failed in transport",
                extra={
                    "event": "checkoutuz.client.transport_failed",
                    "path": path,
                    "failure": type(exc).__name__,
                },
            )
            return err(
                CheckoutError(
                    "checkout.uz could not be reached",
                    is_retryable=True,
                    context={"path": path, "failure": type(exc).__name__},
                    cause=exc,
                )
            )

        try:
            body = response.json()
        except Exception:
            return err(
                CheckoutError(
                    "checkout.uz replied with a body that is not JSON",
                    is_retryable=response.status_code >= 500,
                    context={
                        "path": path,
                        "status_code": response.status_code,
                        "body_excerpt": response.text[:_BODY_EXCERPT_CHARS],
                    },
                )
            )

        vendor_status = body.get("status") if isinstance(body, dict) else None
        if not response.is_success or not isinstance(body, dict) or vendor_status != _SUCCESS:
            return err(
                CheckoutError(
                    "checkout.uz refused the request",
                    is_retryable=response.status_code >= 500,
                    context={
                        "path": path,
                        "status_code": response.status_code,
                        "vendor_status": vendor_status if isinstance(vendor_status, str) else None,
                        "vendor_message": _vendor_message(body),
                    },
                )
            )
        return ok(body)


def _malformed(path: str, reason: str) -> CheckoutError:
    return CheckoutError(
        "checkout.uz replied with a body this client does not accept",
        is_retryable=False,
        context={"path": path, "reason": reason},
    )


def _positive_int(value: object) -> int | None:
    """An id is a positive integer: an ``int``, or a string of ASCII digits.

    **The live API sends ids as strings** (``"id": "103389"`` from ``/status_payment``, seen
    2026-10-03) although its docs show numbers, and a parser that refused them left a paid
    order unsettled. A ``bool``, a float, a signed or padded string are still refused.
    """
    if isinstance(value, bool):
        return None
    if isinstance(value, str) and _DIGITS.fullmatch(value):
        value = int(value)
    if not isinstance(value, int) or value <= 0:
        return None
    return value


def _whole_number(value: object) -> int | None:
    """An amount is a whole number of som. ``50000``, ``50000.0`` and ``"15000.00"`` are;
    ``50000.5`` and ``"15000.50"`` are not.

    JSON has one number type and the docs call the field "number", so an integral float is
    accepted. **The live API sends amounts as decimal strings** (``"amount": "15000.00"``,
    seen 2026-10-03), so a plain decimal string is accepted too, parsed exactly. Anything
    fractional is refused rather than truncated, for the reason
    :func:`~bayram.checkoutuz.ports.som_from_minor` refuses to round.
    """
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    if isinstance(value, str) and _DECIMAL.fullmatch(value):
        whole, _, fraction = value.partition(".")
        if fraction.strip("0"):
            return None
        return int(whole)
    return None


def _lifetime_s(payment: Mapping[str, Any], *, order_id: int) -> int:
    """Read ``_lifteme._second`` (the vendor's spelling). Falls back to the documented hour.

    ``_lifetime`` is accepted too, in case the vendor ever corrects the typo; the default is
    logged so an operator can see a changed reply shape before it matters.
    """
    for key in ("_lifteme", "_lifetime"):
        block = payment.get(key)
        if isinstance(block, Mapping):
            seconds = _positive_int(block.get("_second"))
            if seconds is not None:
                return seconds
    _LOG.warning(
        "checkout.uz did not say how long a payment link lives; assuming the documented hour",
        extra={"event": "checkoutuz.client.lifetime_missing", "order_id": order_id},
    )
    return DEFAULT_LINK_LIFETIME_S


def _pay_via(payment: Mapping[str, Any], *, order_id: int) -> tuple[tuple[str, str], ...]:
    """Read ``_pay_via`` leniently: the per-method pages are a convenience, never a refusal.

    The payment already exists at checkout.uz by now and ``_url`` is a complete way to pay it,
    so a missing or garbled ``_pay_via`` costs the customer one extra tap, not the sale. An
    entry is kept only when its key is a short slug and its value an https URL; anything else
    is dropped, and one WARNING says so, so a changed reply shape is visible before it matters.
    """
    block = payment.get("_pay_via")
    if not isinstance(block, Mapping):
        _LOG.warning(
            "checkout.uz sent no per-method payment pages; only the general page is shown",
            extra={"event": "checkoutuz.client.pay_via_missing", "order_id": order_id},
        )
        return ()
    kept: list[tuple[str, str]] = []
    dropped = 0
    for key, url in block.items():
        if (
            isinstance(key, str)
            and _PAY_VIA_KEY.fullmatch(key)
            and isinstance(url, str)
            and url.startswith("https://")
            and len(kept) < MAX_PAY_VIA_ENTRIES
        ):
            kept.append((key, url))
        else:
            dropped += 1
    if dropped:
        _LOG.warning(
            "checkout.uz sent per-method payment pages this client does not draw; dropped",
            extra={
                "event": "checkoutuz.client.pay_via_dropped",
                "order_id": order_id,
                "dropped": dropped,
                "kept": len(kept),
            },
        )
    return tuple(kept)


def _vendor_message(body: object) -> str | None:
    """The vendor's own error text, if it sent one, cut short. Never the request."""
    if not isinstance(body, Mapping):
        return None
    for key in ("message", "error", "msg"):
        value = body.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()[:_BODY_EXCERPT_CHARS]
    return None
