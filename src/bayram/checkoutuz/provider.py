"""The checkout provider for checkout.uz: open an intent, hand the customer a payment page.

Implements ``bayram.checkout.CheckoutProvider`` structurally. ``charge`` NEVER grants anything:
it returns an unpaid ``Purchase`` carrying a ``checkout_url``, and the money is settled later,
in the worker, by :func:`bayram.checkoutuz.settle.settle_checkoutuz_order` after it has asked
checkout.uz itself (``DECISIONS.md D28``).

**One intent, possibly several payments.** A checkout.uz link lives an hour (``_lifteme``); an
intent lives twelve. A re-press within the hour hands back the SAME link, so a double tap
cannot put two live pages for one purchase in a chat. A press after the link has lapsed (or
is about to — :data:`~bayram.checkoutuz.ports.LINK_REUSE_MARGIN_S`) mints a fresh payment
BESIDE the old one, and the old row stays on file and stays pollable: a page left open past
its advertised end can still be paid, and an ``order_id`` we had forgotten would be money with
no credit. Both rows point at one intent, so whichever is paid first settles it and a second
is recorded as ``orphan_paid`` rather than granted twice.

**The order of the refusals is the contract**, and every one of them happens before anything
is written or any money-shaped call is made:

1. the owner's per-rail switch (:class:`~bayram.errors.CheckoutRailDisabledError`, its own
   copy, because "payments are paused" would be false while the other rails sell);
2. the global pause (:class:`~bayram.errors.CheckoutPausedError`);
3. the amount — checkout.uz takes whole SOM in ``1_000..10_000_000`` and this system stores
   tiyin, so a price that does not convert exactly is refused before an intent is opened.

Both switches FAIL OPEN on a read error, like the Payme pause: a Redis blip must not take a
working rail off sale, and the settlement never reads either switch, so a payment already in
flight is settled whatever they say.

**A foreign or finished intent is refused, never re-used.** One ``payment_intents`` table serves
every redirect rail and the idempotency key is unique across all of them, so a replayed key can
return another rail's intent (refused: we could never settle it) or an intent that is already
PAID, CANCELLED or EXPIRED (refused: answering a paid intent with ``is_paid=True`` would send
the bot down its fulfil path under the request key, and minting a page for a finished intent
sells something twice).
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Final, Protocol

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from bayram.checkout import (
    PaymentIntent,
    PaymentIntentOpener,
    PaymentIntentState,
    Product,
    Purchase,
    PurchaseRequest,
)
from bayram.checkoutuz.client import CheckoutUzApi
from bayram.checkoutuz.ports import CHECKOUTUZ_PROVIDER_NAME, LINK_REUSE_MARGIN_S, som_from_minor
from bayram.contracts import Err, Language, Result, err, ok
from bayram.db.base import utc_now
from bayram.db.checkoutuz_sql import insert_payment, live_payment_for_intent
from bayram.db.guard import not_found, run_guarded
from bayram.db.payme_sql import intent_by_ref
from bayram.errors import CheckoutError, CheckoutPausedError, CheckoutRailDisabledError
from bayram.logging import get_logger

__all__ = [
    "CHECKOUTUZ_MERCHANT_ID",
    "CHECKOUTUZ_PROVIDER_NAME",
    "CheckoutUzCheckoutProvider",
    "CheckoutUzLink",
    "CheckoutUzPaymentStore",
    "SqlCheckoutUzPaymentStore",
]

_LOG = get_logger(__name__)

#: What ``payment_intents.merchant_id`` holds for a checkout.uz intent. checkout.uz identifies
#: the merchant by the API key, which must never be written to a row, so the rail's own name
#: stands in for an account id here.
CHECKOUTUZ_MERCHANT_ID: Final[str] = CHECKOUTUZ_PROVIDER_NAME

#: The only currency checkout.uz takes.
_CURRENCY: Final[str] = "UZS"

#: How much of ``public_ref`` the payment description quotes. Enough for an operator to find
#: the intent from the checkout.uz dashboard; the description is shown to the customer too.
_DESCRIPTION_REF_CHARS: Final[int] = 8


@dataclass(frozen=True, slots=True)
class CheckoutUzLink:
    """One recorded checkout.uz payment, as the provider sees it. Never a ``*Row`` (Rule 15)."""

    order_id: int
    pay_url: str
    link_valid_until: datetime
    #: The per-method pages stored beside the link, so a re-press draws the same buttons.
    pay_via: tuple[tuple[str, str], ...] = ()


class CheckoutUzPaymentStore(Protocol):
    """The two writes-and-reads the bot side needs over ``checkoutuz_payments``. Never raises.

    Keyed by ``public_ref`` because that is what :class:`~bayram.checkout.PaymentIntent`
    carries; the intent's row id deliberately never crosses the ``bayram.db`` boundary.
    """

    async def live_link(
        self, *, public_ref: str, now: datetime, margin_s: int
    ) -> Result[CheckoutUzLink | None]: ...

    async def record_link(
        self,
        *,
        public_ref: str,
        order_id: int,
        payment_uuid: str,
        pay_url: str,
        amount_som: int,
        link_valid_until: datetime,
        now: datetime,
        pay_via: Sequence[tuple[str, str]] = (),
    ) -> Result[bool]: ...


class SqlCheckoutUzPaymentStore:
    """:class:`CheckoutUzPaymentStore` over the WP1 statements in :mod:`bayram.db.checkoutuz_sql`.

    Each method is one short transaction behind :func:`bayram.db.guard.run_guarded`, which is
    what turns a database failure into an ``Err`` instead of an exception in the bot.
    """

    __slots__ = ("_sessions",)

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._sessions = session_factory

    async def live_link(
        self, *, public_ref: str, now: datetime, margin_s: int
    ) -> Result[CheckoutUzLink | None]:
        async def _read() -> CheckoutUzLink | None:
            async with self._sessions() as session:
                intent = await intent_by_ref(session, public_ref)
                if intent is None:
                    return None
                row = await live_payment_for_intent(session, intent.id, now=now, margin_s=margin_s)
                if row is None:
                    return None
                return CheckoutUzLink(
                    order_id=row.order_id,
                    pay_url=row.pay_url,
                    link_valid_until=row.link_valid_until,
                    pay_via=_stored_pay_via(row.pay_via),
                )

        return await run_guarded("checkoutuz.live_link", _read, public_ref=public_ref)

    async def record_link(
        self,
        *,
        public_ref: str,
        order_id: int,
        payment_uuid: str,
        pay_url: str,
        amount_som: int,
        link_valid_until: datetime,
        now: datetime,
        pay_via: Sequence[tuple[str, str]] = (),
    ) -> Result[bool]:
        async def _write() -> bool:
            async with self._sessions.begin() as session:
                intent = await intent_by_ref(session, public_ref)
                if intent is None:
                    raise not_found("payment_intent", public_ref=public_ref)
                return await insert_payment(
                    session,
                    order_id=order_id,
                    intent_id=intent.id,
                    payment_uuid=payment_uuid,
                    pay_url=pay_url,
                    amount_som=amount_som,
                    link_valid_until=link_valid_until,
                    now=now,
                    pay_via=pay_via,
                )

        return await run_guarded(
            "checkoutuz.record_link", _write, public_ref=public_ref, order_id=order_id
        )


class CheckoutUzCheckoutProvider:
    """Starts a checkout.uz payment. Satisfies ``bayram.checkout.CheckoutProvider``.

    ``enabled`` is the owner's per-rail switch and ``paused`` the global one; both are read on
    every ``charge`` and on nothing else. ``webhook_base_url`` gets ``/{public_ref}`` appended,
    so the gateway can cross-check the path against the order it is told about.
    """

    name: str = CHECKOUTUZ_PROVIDER_NAME

    def __init__(
        self,
        opener: PaymentIntentOpener,
        client: CheckoutUzApi,
        payments: CheckoutUzPaymentStore,
        *,
        webhook_base_url: str,
        return_url: str,
        plan_songs: int,
        plan_days: int,
        language_of: Callable[[], Language],
        paused: Callable[[], Awaitable[bool]],
        enabled: Callable[[], Awaitable[bool]],
        clock: Callable[[], datetime] = utc_now,
    ) -> None:
        self._opener = opener
        self._client = client
        self._payments = payments
        self._webhook_base_url = webhook_base_url.rstrip("/")
        self._return_url = return_url
        self._plan_songs = plan_songs
        self._plan_days = plan_days
        self._language_of = language_of
        self._paused = paused
        self._enabled = enabled
        self._clock = clock

    async def charge(self, request: PurchaseRequest) -> Result[Purchase]:
        """Open (or re-open) the intent and return its payment page. Never raises."""
        log_context = {
            "product": request.product.value,
            "idempotency_key": request.idempotency_key,
        }
        if not await self._switch_reads_true(self._enabled, which="rail_switch", default=True):
            _LOG.info(
                "a checkout.uz purchase was refused because the rail is switched off",
                extra={"event": "checkoutuz.rail_disabled", **log_context},
            )
            return err(
                CheckoutRailDisabledError(
                    "the checkout.uz rail is switched off for new sales; no intent was opened",
                    context=log_context,
                )
            )
        if await self._switch_reads_true(self._paused, which="pause", default=False):
            _LOG.info(
                "a checkout.uz purchase was refused because checkout is paused",
                extra={"event": "checkoutuz.paused", **log_context},
            )
            return err(
                CheckoutPausedError(
                    "the checkout rail is paused; no intent was opened", context=log_context
                )
            )
        if request.currency.upper() != _CURRENCY:
            return err(
                CheckoutError(
                    "checkout.uz takes UZS only",
                    context={**log_context, "currency": request.currency},
                )
            )
        converted = som_from_minor(request.amount_minor)
        if isinstance(converted, Err):
            _LOG.error(
                "a price cannot be charged through checkout.uz; no intent was opened",
                extra={"event": "checkoutuz.unpayable_amount", **converted.error.to_log_dict()},
            )
            return converted

        language = self._language_of()
        is_plan = request.product is Product.STARTER
        opened = await self._opener.open_intent(
            telegram_user_id=request.telegram_user_id,
            product=request.product,
            amount_minor=request.amount_minor,
            currency=request.currency,
            idempotency_key=request.idempotency_key,
            language=language.value if isinstance(language, Language) else str(language),
            merchant_id=CHECKOUTUZ_MERCHANT_ID,
            is_sandbox=False,
            plan_songs=self._plan_songs if is_plan else None,
            plan_days=self._plan_days if is_plan else None,
            resume_order_id=request.resume_order_id,
            provider=CHECKOUTUZ_PROVIDER_NAME,
        )
        if isinstance(opened, Err):
            _LOG.error(
                "a checkout.uz payment intent could not be opened",
                extra={"event": "checkoutuz.intent_unopened", **opened.error.to_log_dict()},
            )
            return opened
        intent = opened.value

        refusal = _refuse_intent(intent)
        if refusal is not None:
            _LOG.warning(
                "a checkout.uz press landed on an intent this rail must not sell against",
                extra={"event": "checkoutuz.intent_refused", **refusal.to_log_dict()},
            )
            return err(refusal)

        # The INTENT's amount from here on, not the request's: a replayed key returns the first
        # press's intent, and the settlement matches the payment against the intent.
        amount = som_from_minor(intent.amount_minor)
        if isinstance(amount, Err):
            return amount
        amount_som = amount.value

        now = self._clock()
        live = await self._payments.live_link(
            public_ref=intent.public_ref, now=now, margin_s=LINK_REUSE_MARGIN_S
        )
        if isinstance(live, Err):
            # Not "mint a new one anyway": a read failure is exactly when we cannot tell whether
            # a live page already exists, and a second page is a second payment to reconcile.
            return live
        if live.value is not None:
            _LOG.info(
                "a checkout.uz link was handed out again",
                extra={
                    "event": "checkoutuz.link_reused",
                    "public_ref": intent.public_ref,
                    "order_id": live.value.order_id,
                },
            )
            return ok(self._purchase(request, intent, live.value.pay_url, live.value.pay_via))

        created = await self._client.create_payment(
            amount_som=amount_som,
            description=f"Bayram #{intent.public_ref[:_DESCRIPTION_REF_CHARS]}",
            webhook_url=f"{self._webhook_base_url}/{intent.public_ref}",
            return_url=self._return_url,
        )
        if isinstance(created, Err):
            _LOG.error(
                "checkout.uz did not create a payment",
                extra={
                    "event": "checkoutuz.create_failed",
                    "public_ref": intent.public_ref,
                    **created.error.to_log_dict(),
                },
            )
            return created
        payment = created.value
        if payment.amount_som != amount_som:
            # Nothing is stored: the settlement would refuse this order anyway, and a page that
            # quotes the customer a different number must not be handed to them.
            _LOG.error(
                "checkout.uz echoed a different amount than it was asked to charge",
                extra={
                    "event": "checkoutuz.amount_echo_mismatch",
                    "public_ref": intent.public_ref,
                    "order_id": payment.order_id,
                    "asked_som": amount_som,
                    "echoed_som": payment.amount_som,
                },
            )
            return err(
                CheckoutError(
                    "checkout.uz echoed a different amount; the payment page was withheld",
                    context={"order_id": payment.order_id, "asked_som": amount_som},
                )
            )

        recorded = await self._payments.record_link(
            public_ref=intent.public_ref,
            order_id=payment.order_id,
            payment_uuid=payment.uuid,
            pay_url=payment.url,
            amount_som=payment.amount_som,
            link_valid_until=now + timedelta(seconds=payment.lifetime_s),
            now=now,
            pay_via=payment.pay_via,
        )
        if isinstance(recorded, Err) or not recorded.value:
            # A payment exists at checkout.uz that nothing here will poll. It is not handed out,
            # so it can only be paid by somebody who already has the URL — nobody — but the id
            # is logged in full so an operator can find it if that ever proves wrong.
            _LOG.error(
                "a checkout.uz payment was created and could not be recorded; not handed out",
                extra={
                    "event": "checkoutuz.payment_unrecorded",
                    "public_ref": intent.public_ref,
                    "order_id": payment.order_id,
                    "duplicate": not isinstance(recorded, Err),
                },
            )
            if isinstance(recorded, Err):
                return recorded
            return err(
                CheckoutError(
                    "checkout.uz returned an order id that is already on file",
                    context={"order_id": payment.order_id},
                )
            )

        _LOG.info(
            "a checkout.uz payment link was created",
            extra={
                "event": "checkoutuz.link_created",
                "public_ref": intent.public_ref,
                "order_id": payment.order_id,
                "amount_som": payment.amount_som,
            },
        )
        return ok(self._purchase(request, intent, payment.url, payment.pay_via))

    def _purchase(
        self,
        request: PurchaseRequest,
        intent: PaymentIntent,
        url: str,
        pay_via: tuple[tuple[str, str], ...],
    ) -> Purchase:
        return Purchase(
            product=request.product,
            provider=CHECKOUTUZ_PROVIDER_NAME,
            reference=intent.public_ref,
            amount_minor=intent.amount_minor,
            currency=intent.currency,
            is_paid=False,
            checkout_url=url,
            pay_options=pay_via,
        )

    @staticmethod
    async def _switch_reads_true(
        reader: Callable[[], Awaitable[bool]], *, which: str, default: bool
    ) -> bool:
        """Read one switch; on any failure answer ``default`` — which is always "keep selling"."""
        try:
            return bool(await reader())
        except Exception as exc:
            _LOG.warning(
                "a checkout.uz sale switch could not be read; failing open",
                extra={
                    "event": "checkoutuz.switch_unreadable",
                    "switch": which,
                    "failure": repr(exc),
                },
            )
            return default


def _stored_pay_via(stored: object) -> tuple[tuple[str, str], ...]:
    """``checkoutuz_payments.pay_via`` back as ``(method, url)`` pairs. Never raises.

    The column is display-only, so NULL or a value of the wrong shape reads as "no per-method
    pages" and the link screen falls back to the general page; a malformed entry is skipped,
    never guessed at.
    """
    if not isinstance(stored, list):
        return ()
    return tuple(
        (entry[0], entry[1])
        for entry in stored
        if isinstance(entry, list)
        and len(entry) == 2
        and isinstance(entry[0], str)
        and isinstance(entry[1], str)
        and entry[1].startswith("https://")
    )


def _refuse_intent(intent: PaymentIntent) -> CheckoutError | None:
    """Why this rail must not mint a page for ``intent``, or ``None`` when it may."""
    if intent.provider != CHECKOUTUZ_PROVIDER_NAME:
        return CheckoutError(
            "the idempotency key already belongs to another rail's intent",
            context={"public_ref": intent.public_ref, "intent_provider": intent.provider},
        )
    if intent.state != PaymentIntentState.PENDING:
        return CheckoutError(
            "the intent for this key is no longer open for payment",
            context={"public_ref": intent.public_ref, "intent_state": intent.state.value},
        )
    return None
