"""The checkout.uz webhook route: an ACCELERATOR, never a settlement (``DECISIONS.md D28``).

checkout.uz POSTs here when a payment succeeds. The call is unsigned, comes from the open
internet, and is never retried. So this route:

* **believes nothing in the body.** It reads one number, ``data.order_id``, and uses it only to
  decide whether a worker job is worth enqueueing. The job asks checkout.uz itself and checks
  the answer before any money moves (:func:`bayram.checkoutuz.settle.settle_checkoutuz_order`).
* **writes nothing.** :class:`CheckoutUzWebhookGate` does one SELECT and one queue push. A forged
  call can at worst make the worker ask checkout.uz about an order we already know is pending,
  which the five-minute poll would have done anyway. It cannot suppress the REAL webhook that
  follows: the reconcile keeps no ARQ result (``keep_result=0``), so its deterministic job id
  only dedupes reconciles queued at the same moment, not one that already finished.
* **always answers 200 ``{"ok": true}``**, whatever happened. checkout.uz does not retry, so a
  non-200 buys nothing, and a differentiated answer would only tell a prober which order ids
  exist. The poller is the source of truth; a lost webhook costs at most one poll interval.

Mounted on the Payme gateway's app (``bayram.payme.app``) at ``/checkoutuz``. The edge — the
Cloudflare Tunnel ingress for the pay host — must route ``/checkoutuz/*`` to that gateway.

``public_ref`` in the path is optional. The provider appends it to every ``webhook_url`` it
hands checkout.uz, so when it is present it must match the order's intent; a mismatch is
treated as a forgery and enqueues nothing. The bare ``/callback`` form exists for a webhook
URL configured globally in the checkout.uz dashboard, which cannot carry a per-order path.
"""

from __future__ import annotations

import json
from typing import Any, Final, Protocol

from fastapi import APIRouter, FastAPI, Request
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from starlette.responses import JSONResponse

from bayram.checkoutuz.jobs import CHECKOUTUZ_RECONCILE_JOB_NAME, reconcile_job_id
from bayram.checkoutuz.ports import CHECKOUTUZ_PROVIDER_NAME
from bayram.db.checkoutuz_sql import payment_with_intent
from bayram.db.enums import CheckoutUzPaymentState
from bayram.logging import get_logger

__all__ = [
    "CHECKOUTUZ_GATE_STATE_ATTR",
    "MAX_WEBHOOK_BODY_BYTES",
    "CheckoutUzWebhookGate",
    "WebhookGate",
    "build_checkoutuz_router",
    "create_checkoutuz_app",
]

_LOG = get_logger(__name__)

#: The ``app.state`` attribute the gateway's lifespan sets. Read per request rather than bound
#: at router build time, because the gateway builds its routes before its container exists.
CHECKOUTUZ_GATE_STATE_ATTR: Final[str] = "checkoutuz_gate"

#: A real webhook is a few hundred bytes. Anything larger is not from checkout.uz and is not
#: read past this point.
MAX_WEBHOOK_BODY_BYTES: Final[int] = 8 * 1024

#: The one answer this route ever gives.
_ACK: Final[dict[str, bool]] = {"ok": True}

#: ``checkoutuz_payments.order_id`` is a BigInteger; a larger number names nothing and would
#: only make the lookup fail.
_MAX_ORDER_ID: Final[int] = 2**63 - 1

#: ``public_ref`` is ours, URL-safe and short. Anything longer is refused without a query.
_MAX_REF_CHARS: Final[int] = 64


class _Enqueuer(Protocol):
    """The slice of ``arq.ArqRedis`` the gate uses."""

    async def enqueue_job(self, function: str, *args: Any, _job_id: str | None = None) -> Any: ...


class WebhookGate(Protocol):
    """Decides whether one webhook is worth a worker job, and enqueues it if so."""

    async def admit(self, *, order_id: int, public_ref: str | None) -> bool: ...


class CheckoutUzWebhookGate:
    """One SELECT, then at most one enqueue. Holds no secret and writes no row.

    The order must be on file, still ``pending``, attached to a checkout.uz intent, and — when
    the path carried one — attached to THAT ``public_ref``. Only then is the reconcile job
    enqueued, under a deterministic job id so a burst of identical webhooks queues one job.
    """

    __slots__ = ("_redis", "_sessions")

    def __init__(self, session_factory: async_sessionmaker[AsyncSession], redis: _Enqueuer) -> None:
        self._sessions = session_factory
        self._redis = redis

    async def admit(self, *, order_id: int, public_ref: str | None) -> bool:
        async with self._sessions() as session:
            found = await payment_with_intent(session, order_id)
        if found is None:
            _LOG.info(
                "a checkout.uz webhook named an order that is not on file",
                extra={"event": "checkoutuz.webhook_unknown_order", "order_id": order_id},
            )
            return False
        payment, intent = found
        if intent.provider != CHECKOUTUZ_PROVIDER_NAME:
            _LOG.warning(
                "a checkout.uz webhook named an order attached to another rail's intent",
                extra={"event": "checkoutuz.webhook_foreign_intent", "order_id": order_id},
            )
            return False
        if public_ref is not None and public_ref != intent.public_ref:
            _LOG.warning(
                "a checkout.uz webhook's path does not match its order; treated as forged",
                extra={"event": "checkoutuz.webhook_ref_mismatch", "order_id": order_id},
            )
            return False
        if payment.state is CheckoutUzPaymentState.EXPIRED:
            # The final check closed this link, yet checkout.uz says it was just paid. This
            # webhook is the only signal that will ever come, so it is not dropped: the
            # reconcile asks checkout.uz itself and settles it if the payment is real.
            _LOG.warning(
                "a checkout.uz webhook named a link already closed as expired; reconciling",
                extra={"event": "checkoutuz.webhook_after_expiry", "order_id": order_id},
            )
        elif payment.state is not CheckoutUzPaymentState.PENDING:
            return False
        job = await self._redis.enqueue_job(
            CHECKOUTUZ_RECONCILE_JOB_NAME, order_id, _job_id=reconcile_job_id(order_id)
        )
        _LOG.info(
            "a checkout.uz webhook queued a reconcile"
            if job is not None
            else "a checkout.uz webhook found a reconcile for its order already queued",
            extra={
                "event": "checkoutuz.webhook_enqueued"
                if job is not None
                else "checkoutuz.webhook_deduplicated",
                "order_id": order_id,
                "public_ref": intent.public_ref,
            },
        )
        return True


def build_checkoutuz_router(gate: WebhookGate | None = None) -> APIRouter:
    """The ``/checkoutuz/callback`` routes. ``gate`` overrides ``app.state`` (tests only)."""
    router = APIRouter(prefix="/checkoutuz", tags=["checkoutuz"])

    async def _handle(request: Request, public_ref: str | None) -> JSONResponse:
        try:
            await _admit(request, gate, public_ref)
        except Exception as exc:
            # Whatever went wrong, checkout.uz still gets its 200: it would not retry anyway,
            # and the poller will find the payment.
            _LOG.error(
                "a checkout.uz webhook could not be processed; the poller will catch it",
                extra={"event": "checkoutuz.webhook_failed", "failure": repr(exc)},
            )
        return JSONResponse(status_code=200, content=_ACK)

    @router.post("/callback")
    @router.post("/callback/")
    async def checkoutuz_callback(request: Request) -> JSONResponse:
        return await _handle(request, None)

    @router.post("/callback/{public_ref}")
    @router.post("/callback/{public_ref}/")
    async def checkoutuz_callback_for_ref(request: Request, public_ref: str) -> JSONResponse:
        return await _handle(request, public_ref)

    return router


def create_checkoutuz_app(gate: WebhookGate | None = None) -> FastAPI:
    """A standalone app with only the checkout.uz routes. For tests; production mounts the
    router on the Payme gateway."""
    app = FastAPI(title="Bayram checkout.uz webhook", docs_url=None, redoc_url=None)
    app.include_router(build_checkoutuz_router(gate))
    return app


async def _admit(request: Request, gate: WebhookGate | None, public_ref: str | None) -> None:
    ref = public_ref.strip() if public_ref is not None else None
    if ref is not None and (not ref or len(ref) > _MAX_REF_CHARS):
        return
    body = await _bounded_body(request)
    if body is None:
        _LOG.info(
            "a checkout.uz webhook body was over the size limit; ignored",
            extra={"event": "checkoutuz.webhook_too_large"},
        )
        return
    order_id = _order_id_of(body)
    if order_id is None:
        _LOG.info(
            "a checkout.uz webhook carried no usable order id; ignored",
            extra={"event": "checkoutuz.webhook_unparseable"},
        )
        return
    active = gate
    if active is None:
        active = getattr(request.app.state, CHECKOUTUZ_GATE_STATE_ATTR, None)
    if active is None:
        _LOG.warning(
            "a checkout.uz webhook arrived and no gate is configured; the poller will catch it",
            extra={"event": "checkoutuz.webhook_no_gate", "order_id": order_id},
        )
        return
    await active.admit(order_id=order_id, public_ref=ref)


async def _bounded_body(request: Request) -> bytes | None:
    """The body, or ``None`` once it passes :data:`MAX_WEBHOOK_BODY_BYTES`. Streams, so a huge
    body is never buffered whole."""
    declared = request.headers.get("content-length")
    if declared is not None and declared.isdigit() and int(declared) > MAX_WEBHOOK_BODY_BYTES:
        return None
    chunks: list[bytes] = []
    size = 0
    async for chunk in request.stream():
        size += len(chunk)
        if size > MAX_WEBHOOK_BODY_BYTES:
            return None
        chunks.append(chunk)
    return b"".join(chunks)


def _order_id_of(body: bytes) -> int | None:
    """``data.order_id`` as a positive int — an ``int``, or a string of ASCII digits."""
    try:
        parsed = json.loads(body)
    except (ValueError, UnicodeDecodeError):
        return None
    data = parsed.get("data") if isinstance(parsed, dict) else None
    raw = data.get("order_id") if isinstance(data, dict) else None
    if isinstance(raw, bool):
        return None
    if isinstance(raw, str) and raw.isascii() and raw.isdigit() and len(raw) <= 19:
        raw = int(raw)
    if isinstance(raw, int) and 0 < raw <= _MAX_ORDER_ID:
        return raw
    return None
