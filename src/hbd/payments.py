"""The payment seam — deliberately a no-op for this build.

Payment is out of scope: no Stars, no Click, no Payme, no invoices, no ledger. What *is*
in scope is the seam, so the real rail drops in later without touching a handler or the
orchestrator. Both call ``PaymentProvider.authorize`` and both already branch on the
result; swapping this class for a real one is a wiring change in the composition root.

``NoopPaymentProvider`` therefore authorises everything, records nothing and charges
nothing — and it still returns a ``Result``, so the failure path at every call site is
written and exercised from day one instead of being invented under pressure the day
billing lands.

What *is* metered in this build is entitlement, not money, and it rides the same seam:
:class:`CreditGatedPaymentProvider` decorates the no-op provider rather than replacing it,
so ADMIN_PANEL_PLAN D9 survives intact (``NoopPaymentProvider`` is untouched, and Phase 5's
``LedgerPaymentProvider`` stacks on the same seam later) while one credit is spent per
render. Two facts, two decorators, one ``authorize`` call.

This module is the canonical home. ``hbd.bot.payment`` re-exports it so the bot package
keeps its historical import path without owning a second copy.
"""

from __future__ import annotations

from typing import Final
from uuid import UUID, uuid4

from hbd.contracts import Err, Ok, PaymentAuthorization, PaymentProvider, Result, ok
from hbd.entitlements import ChargeOutcome, EntitlementStore
from hbd.logging import get_logger

__all__ = [
    "NoopPaymentProvider",
    "NOOP_PROVIDER_NAME",
    "FREE_AMOUNT_MINOR",
    "DEFAULT_CURRENCY",
    "CreditGatedPaymentProvider",
    "CREDIT_GATED_PROVIDER_NAME",
    "PIPELINE_ACTOR",
]

_LOG = get_logger(__name__)

NOOP_PROVIDER_NAME: Final[str] = "noop"
CREDIT_GATED_PROVIDER_NAME: Final[str] = "credit_gated"
#: What the ledger records as the author of a debit made by the render gate. The worker is
#: the only process that writes one (see the class docstring below), so this is the only
#: actor a debit row can carry; ``bot`` never appears against a DEBIT by construction.
PIPELINE_ACTOR: Final[str] = "pipeline"
#: Nothing is charged in this build. The field exists because the protocol has it.
FREE_AMOUNT_MINOR: Final[int] = 0
#: Uzbek sum. ISO-4217, three letters, as ``PaymentAuthorization`` requires.
DEFAULT_CURRENCY: Final[str] = "UZS"


class NoopPaymentProvider:
    """Always authorises. Structurally satisfies ``hbd.contracts.PaymentProvider``."""

    name: str = NOOP_PROVIDER_NAME

    async def authorize(
        self, *, order_id: UUID, amount_minor: int, currency: str, telegram_user_id: int
    ) -> Result[PaymentAuthorization]:
        # ``telegram_user_id`` is accepted and logged but never consulted: this provider
        # authorises everyone by construction. It is on the signature because the protocol
        # has it (``hbd.contracts.PaymentProvider.authorize``), and in the log line because
        # that is the only record tying an authorisation to a payer while the seam is a
        # no-op — ``PaymentAuthorization`` carries the order, not the person.
        reference = f"{NOOP_PROVIDER_NAME}-{uuid4().hex}"
        _LOG.info(
            "payment authorised by the no-op provider",
            extra={
                "order_id": str(order_id),
                "telegram_user_id": telegram_user_id,
                "amount_minor": amount_minor,
                "currency": currency,
                "reference": reference,
            },
        )
        return ok(
            PaymentAuthorization(
                order_id=order_id,
                provider=NOOP_PROVIDER_NAME,
                reference=reference,
                amount_minor=amount_minor,
                currency=currency,
                is_authorized=True,
            )
        )


class CreditGatedPaymentProvider:
    """Spends one credit per authorised render. The **only** writer of a debit.

    Structurally a ``hbd.contracts.PaymentProvider``, so it drops into the seam wherever the
    no-op provider sat and neither call site changes. Three properties are load-bearing and
    each of them is a defect that was actually shipped by an earlier draft of this design:

    **It delegates to ``inner`` FIRST and charges only on an authorised result.** Today the
    inner provider authorises everyone, so the order looks academic — but the day a real
    rail lands inside this chain, charging first would let a declined card burn a credit
    that the customer cannot get back without an operator. Cheap to keep right now,
    impossible to notice later.

    **It refuses with an ``Err``, never with ``is_authorized=False``.** Both gates already
    render an ``Err`` through ``error_text`` / ``_tell_the_customer_why``, which reads
    ``HbdError.user_message_key`` and interpolates the scalars in ``context`` — so an
    out-of-credits customer is told which refusal it was and when the next credit opens,
    with no change to either gate body. The success-shaped decline renders
    ``wizard.payment_declined`` / ``error.payment_failed``, which would tell them the studio
    could not take their (free) payment.

    **It is the worker's provider, not the bot's.** ``AppContainer.pipeline`` wraps the
    provider per job; ``AppContainer.payment`` — which is what the bot's ``BotDeps`` is
    built from — stays ungated. The bot's gate has three early returns after it
    (``_authorize_and_submit``: declined, ``_start_progress`` returned ``None``,
    ``submitter.submit`` returned ``Err``) and none of them can reach a refund, because no
    order row and no ARQ job exist yet; and ``reset_to_welcome`` mints a fresh session id,
    hence a fresh UUID5, so the customer's second attempt would be charged again. The
    worker is the only process whose terminal paths can compensate, so the money lives
    there and the bot's check (WU7) reads without writing.

    **It no longer owns ``Settings.credits_enforced``, and that is a fix, not a tidy-up.**
    This class used to return before ``_take_one_credit`` whenever the flag was off, and
    since it is the ONLY caller of ``EntitlementStore.charge`` in the tree, the shipped
    configuration wrote no DEBIT rows at all. ``credit_sql.count_in_flight`` counts unsettled
    debits, so ``CreditBalance.in_flight`` was permanently 0 and the one-song-at-a-time cap
    refused nobody — and the worker's block check, which lives inside the same skipped call,
    let an account blocked AFTER its job was queued render and ship (reproduced). Both are
    abuse rails that D-B says enforce from the day they merge.
    The flag now lives on ``EntitlementPolicy.is_balance_enforced``, where it gates the one
    predicate it is about, and this decorator always charges.
    """

    #: Constant rather than derived from ``inner.name``: what the *authorisation* was made
    #: by is already carried by ``PaymentAuthorization.provider``, which this decorator
    #: passes through untouched, so deriving it here would only give the same fact two
    #: spellings in the logs. A plain class attribute rather than a frozen-dataclass field
    #: because ``PaymentProvider.name`` is declared as a settable variable, and mypy rejects
    #: the read-only attribute a frozen dataclass produces — the same shape
    #: ``NoopPaymentProvider`` above already uses.
    name: str = CREDIT_GATED_PROVIDER_NAME

    def __init__(
        self,
        inner: PaymentProvider,
        credits: EntitlementStore,
        *,
        actor: str = PIPELINE_ACTOR,
    ) -> None:
        self._inner = inner
        self._credits = credits
        self._actor = actor

    async def authorize(
        self, *, order_id: UUID, amount_minor: int, currency: str, telegram_user_id: int
    ) -> Result[PaymentAuthorization]:
        """Authorise through ``inner``, then take one credit. Never raises."""
        authorization = await self._inner.authorize(
            order_id=order_id,
            amount_minor=amount_minor,
            currency=currency,
            telegram_user_id=telegram_user_id,
        )
        if isinstance(authorization, Err) or not authorization.value.is_authorized:
            # Nothing was authorised, so nothing is owed. Returning before the store is
            # touched is what keeps a declined order from opening an account and minting a
            # rolling allowance for someone who never rendered anything.
            return authorization
        return await self._take_one_credit(
            authorization, order_id=order_id, telegram_user_id=telegram_user_id
        )

    async def _take_one_credit(
        self,
        authorization: Ok[PaymentAuthorization],
        *,
        order_id: UUID,
        telegram_user_id: int,
    ) -> Result[PaymentAuthorization]:
        """Spend the credit for an order the inner provider has already authorised.

        Reached only on the authorised path, which is what makes "a declined card cannot
        burn a credit" a property of the control flow rather than of a comment.
        """
        charged = await self._credits.charge(
            telegram_user_id=telegram_user_id, order_id=order_id, actor=self._actor
        )
        if isinstance(charged, Err):
            # A business refusal (no credits, blocked, too many in flight) and a database
            # outage both arrive here. Both are logged with the payer and the order, and
            # both are returned as-is: ``HbdError.is_retryable`` — False for every
            # ``EntitlementError``, True for a transport failure — is what decides whether
            # ARQ tries again, and second-guessing it here is how a permanent refusal turns
            # into a retry storm against one customer.
            _LOG.warning(
                "the render gate refused the order",
                extra={
                    "order_id": str(order_id),
                    "telegram_user_id": telegram_user_id,
                    **charged.error.to_log_dict(),
                },
            )
            return charged

        outcome, balance = charged.value
        _LOG.info(
            "one credit was taken for the render",
            extra={
                "order_id": str(order_id),
                "telegram_user_id": telegram_user_id,
                # ALREADY_PAID is the ordinary answer on every re-entry — the worker
                # re-running the gate the bot ran, and every ARQ retry of the same job —
                # not an anomaly, so it is INFO and it authorises.
                "charge_outcome": outcome.value,
                "credits_remaining": balance.credits,
                "is_replay": outcome is ChargeOutcome.ALREADY_PAID,
            },
        )
        return authorization
