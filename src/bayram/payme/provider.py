"""The bot's half of the Payme rail: the ``CheckoutProvider`` that starts a payment.

**THIS CLASS OPENS NO SOCKET.** That is the single most surprising true claim in this whole
integration and it is stated first, in capitals, because it is the one a reader will assume
is wrong and the one a later contributor will silently break.

Payme has **no create-payment-link API for the standard checkout**. The link is
CONSTRUCTED — ``<base>/<base64('m=…;ac.<field>=…;a=…;l=…;cr=…')>`` — from values this process
already holds, and the customer's browser is what first contacts Payme. So a redirect rail's
"charge" is a database row and a base64 string, and the pooled ``httpx.AsyncClient`` that
every other vendor adapter in this repository owns, closes and health-probes has no
counterpart here. There is nothing to time out, nothing to retry and nothing to rate-limit.
``tests/test_payme/test_provider.py::test_the_payme_provider_holds_no_http_client`` scans
``vars(provider)`` and fails if an HTTP client ever appears on one, because "contacts
nothing" is a property that rots the first time somebody reaches for ``httpx`` inside
:meth:`PaymeCheckoutProvider.charge` to "check whether the payment went through".

**How the money actually arrives, since it does not arrive here.** ``charge`` returns an
UNPAID :class:`~bayram.checkout.Purchase` carrying a ``checkout_url``. Nothing is granted. Some
minutes later Payme calls ``PerformTransaction`` against a DIFFERENT PROCESS — the gateway,
the only holder of the merchant key — which writes the receipt, the credit grant, the
transaction state and the intent claim in one commit. This class therefore cannot report a
sale and must not pretend to: ``is_paid`` is ``False`` on every ``Purchase`` it ever builds,
and the handler's job is to say "here is where you pay", not "that did not work". See
``PAYME_INTEGRATION §1`` for the two seams and ``§3`` for the settlement.

**The order inside ``charge`` is fixed and is not a preference.** The intent is opened FIRST
and the URL is built from what comes back, because the URL has to carry an identifier the
settlement can be matched to — a link handed out before its row exists is a payment nobody
can claim, and Payme's own ``CheckPerformTransaction`` would answer ``-31050`` for an account
we have never heard of. The identifier embedded in the link is the intent's opaque
``public_ref`` and never its ``idempotency_key``: that key is structured as
``topup:{telegram_user_id}:{scope}:{seq}`` and putting it in a URL would publish a customer's
Telegram id to a third party and render it in a browser address bar.

**Idempotency is inherited, not implemented.** This class holds no state and deduplicates
nothing. It passes the bot-minted ``request.idempotency_key`` straight through, and
``PaymentIntentOpener.open_intent`` is contractually insert-or-ignore on that key and returns
the SAME ``public_ref`` for a replay. Because :func:`~bayram.payme.link.build_checkout_link` is
a pure, total function with a FIXED parameter order, the same ``public_ref`` yields the
byte-identical URL — so a customer who taps the button twice gets one payment page twice,
rather than two live payment pages for one purchase with no way to tell which one their money
went into. That property lives in two places (a unique index and a deterministic encoder) and
in neither of them is it a comment.

**Layering.** This module is in ``bayram.payme``, so it may never import ``bayram.db`` (see this
package's ``__init__``). It receives a :class:`~bayram.checkout.PaymentIntentOpener` — the
ADDITIVE-ONLY port, which declares ``open_intent`` and nothing else — so the bot process
holding this object structurally cannot settle, cancel or force-settle a payment. That is the
same carve-out ``PurchaseFulfiller`` makes one level down, and it is enforced by the type of
the reference rather than by a guard somebody has to remember to write.

See ``DECISIONS.md D11`` for why this rail exists at all and ``PAYME_INTEGRATION §8`` for the
go-live sequence that makes it reachable.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Final

from bayram.checkout import PaymentIntentOpener, Product, Purchase, PurchaseRequest
from bayram.contracts import Language, Result, err, is_err, ok
from bayram.errors import CheckoutPausedError
from bayram.logging import get_logger
from bayram.payme.link import build_checkout_link
from bayram.payme.ports import PAYME_PROVIDER_NAME

__all__ = ["PAYME_PROVIDER_NAME", "PaymeCheckoutProvider"]

_LOG = get_logger(__name__)

#: What a customer is told when an operator has closed the rail. The sentence itself lives in
#: the four catalogues under ``CheckoutPausedError``'s user message key; this is the operator
#: half, which is what lands in the journal and is never shown to anybody.
_PAUSED_MESSAGE: Final[str] = "the checkout rail is paused; no intent was opened"


class PaymeCheckoutProvider:
    """Starts a Payme payment by writing one row and building one URL. Contacts nothing.

    Structurally satisfies :class:`~bayram.checkout.CheckoutProvider` and deliberately does NOT
    inherit from it, matching ``StubCheckoutProvider`` and ``NoopPaymentProvider``. The reason
    is the same every time and it is worth restating because inheriting looks tidier: with a
    ``Protocol`` as a base class, a method this class fails to implement is a runtime
    ``NotImplementedError`` at the moment a customer presses a button, while with structural
    typing it is a ``mypy --strict`` error at the composition root, on the line that assigns
    this object to a ``CheckoutProvider`` field.

    ``name`` is a plain class attribute rather than a frozen-dataclass field on purpose: the
    Protocol declares ``name: str``, which is a SETTABLE variable, and a frozen dataclass's
    field is read-only — mypy rejects the assignment with "cannot assign to a read-only
    attribute" and the error names the wrong thing entirely.

    **Everything it needs is injected and nothing is read from ambient settings**, so a test
    can point one at a sandbox host, a different cashbox or a different plan size without
    patching an import — and so the composition root stays the one place that reads
    :class:`bayram.config.Settings`.
    """

    name: str = PAYME_PROVIDER_NAME

    def __init__(
        self,
        opener: PaymentIntentOpener,
        *,
        merchant_id: str,
        base_url: str,
        account_field: str,
        return_url: str,
        is_sandbox: bool,
        plan_songs: int,
        plan_days: int,
        language_of: Callable[[], Language],
        paused: Callable[[], Awaitable[bool]],
    ) -> None:
        """Bind the rail's configuration once. No I/O; construction is field assignment.

        ``plan_songs`` and ``plan_days`` are the CATALOGUE's numbers, taken here so they can be
        SNAPSHOTTED onto the intent at the moment of sale. The alternative — reading the plan
        size again at settlement — would let a package change between the tap and the payment
        retroactively shrink what somebody has already paid for, which is the argument
        ``plan_purchases.songs_included`` already makes one layer down.

        ``language_of`` is a callable rather than a value, and that is the honest shape of an
        unfinished thing. ``PurchaseRequest`` carries no language — WS-B deliberately did not
        add one, because the neutral vocabulary must not grow a field for one rail's URL
        parameter — so today the composition root binds this to the deployment's default UI
        language, and the ``l=`` parameter is that rather than the individual customer's
        choice. It is a callable so that the day a per-update language becomes reachable
        (a context variable bound by the bot's middleware, or a field on the request) the fix
        is one line at the wiring site and not a change to this class's shape. The cost, stated
        plainly rather than discovered: a Russian-speaking customer on a ``uz_latn`` deployment
        sees Payme's own page in Uzbek. Nothing about settlement depends on it.

        ``paused`` is a callable returning an awaitable rather than a Redis handle, so this
        class holds no client, imports no Redis and can be tested with ``async def: return
        True``. See :meth:`charge` for why a failure to read it is not a refusal.
        """
        self._opener = opener
        self._merchant_id = merchant_id
        self._base_url = base_url
        self._account_field = account_field
        self._return_url = return_url
        self._is_sandbox = is_sandbox
        self._plan_songs = plan_songs
        self._plan_days = plan_days
        self._language_of = language_of
        self._paused = paused

    async def charge(self, request: PurchaseRequest) -> Result[Purchase]:
        """Open an intent and answer with the URL to pay at. **Never raises.**

        Returns ``Ok(Purchase(is_paid=False, checkout_url=...))`` — a payment STARTED, not a
        payment taken. ``reference`` is our own ``public_ref`` and not a rail-side id, because
        at this instant Payme has minted nothing: no transaction exists until the customer
        opens the link. The rail's own 24-character id appears on the paid ``Purchase`` the
        gateway builds at settlement, and that is the one that reaches a receipt.

        **Nothing in this method can raise, and that is established rather than hoped for.**
        ``open_intent`` is a ``Result``-returning seam whose implementation runs inside
        ``run_guarded``; :func:`~bayram.payme.link.build_checkout_link` is pure and total;
        ``Purchase``'s field bounds are all satisfied by construction (a 24-hex ``public_ref``
        against ``max_length=64``, a five-character provider name, an amount and a currency
        that came from a validated ``Settings``). The one genuinely fallible call is
        ``paused()``, which reaches Redis, and it is wrapped — see below. So there is no
        blanket ``except Exception`` here: one would hide the next real bug, and the seam's
        never-raise property would then be a promise made by a swallow rather than by an
        argument.

        **A Redis failure is NOT a pause.** If the switch cannot be read, the sale proceeds
        and a WARNING is logged. The asymmetry is deliberate: an unreachable Redis silently
        stopping every sale is a far worse outage than a paused rail briefly taking a payment,
        and the pause switch's whole purpose is to be an operator's deliberate act. It follows
        that the switch is not a security control and is not documented as one.
        """
        if await self._is_rail_paused():
            _LOG.info(
                "a purchase was refused because the checkout rail is paused",
                extra={
                    "telegram_user_id": request.telegram_user_id,
                    "product": request.product.value,
                    "idempotency_key": request.idempotency_key,
                },
            )
            return err(
                CheckoutPausedError(
                    _PAUSED_MESSAGE,
                    context={
                        "product": request.product.value,
                        "idempotency_key": request.idempotency_key,
                    },
                )
            )

        language = self._language_of()
        # The plan snapshot travels only for the plan product. A single song has neither a
        # duration nor a song count, and the intent's own CHECK constraint spells that out
        # (``product <> 'starter' OR (plan_songs IS NOT NULL AND plan_days IS NOT NULL)``), so
        # sending numbers for a single would be sending numbers nothing may read back.
        is_plan = request.product is Product.STARTER
        opened = await self._opener.open_intent(
            telegram_user_id=request.telegram_user_id,
            product=request.product,
            amount_minor=request.amount_minor,
            currency=request.currency,
            idempotency_key=request.idempotency_key,
            language=language.value,
            merchant_id=self._merchant_id,
            is_sandbox=self._is_sandbox,
            plan_songs=self._plan_songs if is_plan else None,
            plan_days=self._plan_days if is_plan else None,
        )
        if is_err(opened):
            # Straight through, unwrapped. The store already said what went wrong in the
            # vocabulary the handler renders from; re-wrapping it here would replace a
            # specific sentence with a generic one at the only point where the specific one
            # was still available.
            return opened

        intent = opened.value
        link = build_checkout_link(
            base_url=self._base_url,
            merchant_id=self._merchant_id,
            account_field=self._account_field,
            public_ref=intent.public_ref,
            amount_minor=intent.amount_minor,
            language=language,
            return_url=self._return_url,
        )
        _LOG.info(
            "a payment intent was opened and a checkout link was built; no rail was contacted",
            extra={
                "telegram_user_id": request.telegram_user_id,
                "product": request.product.value,
                # The amount from the INTENT, not from the request: on a replay the row is
                # what was quoted, and a log line that reported today's price for a link
                # issued at yesterday's would make a pricing change unreconcilable.
                "amount_minor": intent.amount_minor,
                "currency": intent.currency,
                "public_ref": intent.public_ref,
                "idempotency_key": request.idempotency_key,
                "merchant_id": self._merchant_id,
                "is_sandbox": self._is_sandbox,
                "language": language.value,
                # Never the link itself: it is a payable URL and the journal is not the place
                # for one. ``public_ref`` above is what ties a log line to an intent anyway.
            },
        )
        return ok(
            Purchase(
                product=request.product,
                provider=PAYME_PROVIDER_NAME,
                # OURS, and the asymmetry is argued on ``Purchase.checkout_url``: the rail has
                # minted no identifier yet, so the only reference that exists is the one we
                # put in the link and will be quoted back at.
                reference=intent.public_ref,
                amount_minor=intent.amount_minor,
                currency=intent.currency,
                # THE WHOLE POINT. Money has not moved; a page has been prepared. The
                # fulfiller refuses to grant anything against an unpaid purchase, so even a
                # handler that mishandled this branch could not mint a credit from it.
                is_paid=False,
                checkout_url=link,
            )
        )

    async def _is_rail_paused(self) -> bool:
        """The pause switch, read defensively. A read that fails answers "not paused".

        Broad ``except Exception`` and it is the right tool exactly once: the callable is
        injected, so the set of exceptions it can raise is open by construction — a Redis
        client raises ``RedisError``, a test double raises whatever it likes, and a
        connection pool exhausted at the socket layer raises ``OSError``. Enumerating them
        would be a list that goes stale silently, and the answer is the same for every member
        of it: keep selling and say so in the journal.
        """
        try:
            return await self._paused()
        except Exception as exc:
            _LOG.warning(
                "the checkout pause switch could not be read; treating the rail as open",
                extra={"detail": repr(exc)},
            )
            return False
