"""The seam for BUYING — distinct from ``bayram.payments``, which authorises a RENDER.

Two questions look like one and are not. ``bayram.payments.PaymentProvider.authorize`` answers
"may this order be rendered?", is called once per order by the render gate, and is already
faked three ways in the suite. What this module answers is "did money change hands for a
product?", which happens on a button tap, may happen many times per customer, and has a
receipt. Overloading ``authorize`` with purchases would give one seam two meanings, and the
first person to fake it for one meaning would silently disable the other.

**The charge is a STUB. No provider is contacted.** :class:`StubCheckoutProvider` imports no
HTTP client, opens no socket and always reports the purchase paid. That is the decided scope:
real buttons, real prices, real plan and credit semantics, and a narrow seam — but nothing
that talks to a payment rail. What ships is the shape a real rail will need, exercised end to
end, rather than a half-integration nobody can test.

**The ONLY thing a Payme integration replaces is :meth:`CheckoutProvider.charge`.** Two
fields exist purely so that swap needs no protocol change:

* ``PurchaseRequest.idempotency_key`` is on the REQUEST, so a real receipt can be keyed on
  the same string the ledger deduplicates on. A rail that generated its own key would leave
  the bot unable to recognise its own retry.
* ``Purchase.checkout_url`` is on the RESPONSE and nullable, so a redirect rail — which is
  what Payme actually is — can be expressed by returning a URL to send the customer to,
  without ``charge`` having to grow a second return shape or a state machine.

**The redirect half now has a vocabulary of its own**, at the bottom of this file:
:class:`PaymentIntentState`, :class:`PaymentIntent` and :class:`PaymentIntentOpener`. A rail
that settles inline needs nothing beyond ``charge``, because the answer arrives on the same
call; a redirect rail needs a row that outlives the call, so that the settlement arriving
minutes later on a completely different process can be matched back to the button that was
pressed. That row's shape lives HERE rather than in ``bayram.db`` or in a rail package for the
one reason that governs this whole module: this is the leaf both of them may import, so
putting the shape here is what lets persistence and a rail adapter agree on it without either
one depending on the other. Note that a redirect rail's ``charge`` still contacts nobody —
opening an intent is a database write and building the customer's URL is string work — so the
"no socket" property above is a property of the SEAM, not a temporary property of the stub.

``charge`` returns ``Result`` even though the stub can never fail, for the same reason
``NoopPaymentProvider.authorize`` does: the failure branch at every call site is written and
exercised from day one instead of being invented under pressure the day billing lands.

This module sits at the same depth as :mod:`bayram.entitlements` and imports only leaves —
``bayram.contracts``, ``bayram.logging`` (which itself imports nothing but ``bayram.errors``) and
``bayram.entitlements``, for the ``CreditBalance`` a fulfilled single song hands back. **It may
never import ``bayram.db``.** The persistence side implements :class:`PurchaseFulfiller` from
the other direction, exactly the way ``bayram.db.credits.SqlCreditLedger`` implements
``EntitlementStore`` — which is what keeps ``bayram.db`` free to import this module without the
cycle that putting these types in ``bayram.contracts`` reproduced for the entitlement types.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Final, Protocol, runtime_checkable
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field

from bayram.contracts import Result, ok
from bayram.entitlements import CreditBalance
from bayram.logging import get_logger

__all__ = [
    # Vocabulary
    "Product",
    "Plan",
    # Values
    "PurchaseRequest",
    "Purchase",
    "PlanState",
    "PlanStatus",
    # Seams
    "CheckoutProvider",
    "PurchaseFulfiller",
    # The stub rail
    "STUB_PROVIDER_NAME",
    "StubCheckoutProvider",
    # The redirect rail's vocabulary
    "PaymentIntentState",
    "PaymentIntent",
    "PaymentIntentOpener",
]

_LOG = get_logger(__name__)


class Product(StrEnum):
    """What the customer pressed a button to buy.

    Deliberately kept separate from :class:`Plan` even though ``STARTER`` appears in both.
    ``Product`` is the catalogue — the set of things with a price on a button — while
    ``Plan`` is the set of things that have a duration and a song count. A second plan
    (a yearly, say) adds a member to both; a second one-off product (a re-render, a longer
    song) adds a member only here. Collapsing them would make every ``Plan`` consumer have
    to handle ``SINGLE``, which is not a plan and has no end date.
    """

    SINGLE = "single"
    STARTER = "starter"


class Plan(StrEnum):
    """A subscription-shaped product: a song count that runs out on a date.

    One member today. The value is well under the 32-character ``ENUM_LENGTH`` the database
    layer stores these in, which is what lets ``bayram.db.enums.PlanKind`` mirror it as a plain
    ``VARCHAR(32)`` with no migration when a second plan lands.
    """

    STARTER = "starter"


@dataclass(frozen=True, slots=True)
class PurchaseRequest:
    """What the bot asks a checkout provider to charge for.

    A dataclass rather than a pydantic model because nothing external ever constructs one:
    it is built in a handler from settings and an FSM counter, handed straight to a provider,
    and never crosses a serialisation boundary. ``Purchase`` — which a real rail WILL build
    from a webhook payload one day — is a validated model for exactly that reason.
    """

    #: Who is buying. Carried on the request so a real rail can attach it to its own
    #: customer record; the stub ignores it.
    telegram_user_id: int
    product: Product
    #: Minor units (UZS tiyin), never major. ``kit_price_amount_minor`` and
    #: ``PaymentAuthorization.amount_minor`` are already minor units and Payme quotes tiyin,
    #: so this is already the number a real rail sends. Storing 7000 and multiplying at the
    #: rail is how a rounding bug becomes a pricing bug.
    amount_minor: int
    #: ISO-4217, three letters.
    currency: str
    #: The string BOTH the rail's receipt and this system's ledger are keyed on. A double
    #: tap, a stale message and a redelivered Telegram update all collapse onto one key, and
    #: the unique index on the write side turns the second one into a no-op.
    idempotency_key: str


class Purchase(BaseModel):
    """A charge that a provider has answered for — the receipt, not the request.

    Frozen and validated because this is the value a real integration will build from a
    webhook body. ``provider`` and ``reference`` together are what an operator needs to find
    the charge in somebody else's dashboard, so both are bounded to the widths the ledger
    stores them at rather than left open — a reference that does not fit its column fails at
    the last possible moment, inside the transaction that was granting the credit.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    product: Product
    #: Which rail answered. ``"stub"`` today; a real name the day one lands.
    provider: str = Field(min_length=1, max_length=32)
    #: The rail's own identifier for this charge. Never generated by us for a real rail.
    reference: str = Field(min_length=1, max_length=64)
    amount_minor: int = Field(ge=0)
    currency: str = Field(min_length=3, max_length=3)
    #: Whether money actually moved. **The fulfiller refuses to grant anything when this is
    #: False**, which is what makes a redirect rail safe: a ``charge`` that returns a
    #: ``checkout_url`` and ``is_paid=False`` has started a payment, not completed one.
    is_paid: bool
    #: Where to send the customer, when the rail is a redirect rail. ``None`` for a rail that
    #: settles inline, which is what the stub is.
    #:
    #: **This field has a reader now.** ``bayram.bot.handlers.checkout._settle`` branches on it:
    #: an unpaid receipt WITH a URL is a payment that has started and the customer is shown
    #: the button, while an unpaid receipt WITHOUT one is a rail that declined. Those are two
    #: different sentences to a customer, and until this field was read they were one.
    #:
    #: On a redirect rail the sibling ``reference`` is OURS, not the rail's, and that asymmetry
    #: is deliberate rather than an oversight of the "never generated by us" note above. At
    #: charge time the rail has minted no identifier — no transaction exists yet, because the
    #: customer has not tapped anything — so the only reference that can be recorded is the
    #: opaque public reference of the :class:`PaymentIntent` this charge opened, which is also
    #: the value embedded in ``checkout_url`` and therefore the value the rail will quote back
    #: at us. The RAIL's own identifier appears on the paid ``Purchase`` built later, at
    #: settlement, in the process that owns that half of the protocol — and that is the one
    #: that reaches a receipt. A reader of ``topup_purchases.reference`` must therefore expect
    #: the rail's id on a paid row, never this one.
    checkout_url: str | None = None


@dataclass(frozen=True, slots=True)
class PlanState:
    """One customer's running plan, as every gate and every screen sees it.

    The two predicates below are different questions and both are load-bearing, which is why
    they are named rather than left as inline comparisons at each call site:

    * :meth:`is_live` — "can this plan still mint a song?" The render gate asks this.
    * :meth:`is_current` — "is a plan running at all?" The checkout screen asks this, and it
      is what stops a second plan being sold on top of a spent-but-unexpired one. A customer
      who has used all twelve songs on day three still HAS the starter plan; selling them
      another one would silently overwrite the end date they already paid for.

    A spent plan is therefore ``is_current`` and not ``is_live``, and the difference between
    those two is the entire top-up story: such a customer is offered the single song and told
    the plan brings nothing more until it ends.
    """

    plan: Plan
    songs_included: int
    songs_used: int
    #: When the plan stops minting. Named ``ends_at`` and not ``expires_at`` throughout,
    #: because the ``*_expires_at`` suffix is reserved for RETENTION clocks that a sweep
    #: reads; a plan's end date is a business clock nothing sweeps.
    ends_at: datetime

    @property
    def songs_left(self) -> int:
        """Songs still mintable, floored at zero.

        Floored rather than asserted non-negative: the database CHECK is what keeps the row
        honest, and a reader that raised on a drifted row would turn a reporting problem into
        an outage exactly when an operator needs to see the drift.
        """
        return max(0, self.songs_included - self.songs_used)

    def is_live(self, now: datetime) -> bool:
        """True when this plan can still mint a song right now."""
        return now < self.ends_at and self.songs_left > 0

    def is_current(self, now: datetime) -> bool:
        """True while this is THE running plan, spent or not. See the class docstring."""
        return now < self.ends_at


class PlanStatus(StrEnum):
    """Where one account stands on plans, as an audience the panel can be pointed at.

    Four cases, mutually exclusive and exhaustive over every account, and each one is
    :class:`PlanState`'s two predicates read across an account's whole history rather than a
    new rule::

        NONE       no plan was ever bought
        ACTIVE     some plan is_live      — running, and still has a song to mint
        EXHAUSTED  some plan is_current, none is_live — running, spent
        LAPSED     a plan was bought, none is_current

    Derived from those predicates and not restated beside them, because the day
    ``is_live`` changes, an audience compiled from a second definition of "live" would keep
    targeting the old one — and the failure would be silent, in a message that already went
    out.

    **``LAPSED`` is not "did not renew".** There is no renewal in this product: no
    auto-renew, no recurring billing, no ``renewed_at``. The only truthful reading is "their
    plan ended and they have not bought another", and the operator-facing label must say
    that — a campaign that opens "your subscription lapsed" reaches people who never had one
    to lapse.

    Not persisted anywhere: it is computed per account by the segment compiler, which is why
    it lives beside :class:`PlanState` rather than in ``bayram.db.enums``.
    """

    NONE = "none"
    ACTIVE = "active"
    EXHAUSTED = "exhausted"
    LAPSED = "lapsed"


@runtime_checkable
class CheckoutProvider(Protocol):
    """The one method a real payment rail has to implement. Nothing else moves.

    ``runtime_checkable`` verifies member PRESENCE only, never signatures, so an
    ``isinstance`` assertion in a wiring test will happily accept a fake that has drifted.
    ``mypy --strict`` over ``tests`` is what actually catches that.
    """

    #: What the ledger records against the receipt. An attribute rather than a method so a
    #: caller can name the rail in a log line without awaiting anything.
    name: str

    async def charge(self, request: PurchaseRequest) -> Result[Purchase]:
        """Take money for ``request``, or say why not. **Never raises.**

        A rail that settles inline returns a paid :class:`Purchase`. A redirect rail returns
        an unpaid one carrying ``checkout_url``, and completes it later through its own
        webhook by calling :class:`PurchaseFulfiller` server-side. Both shapes fit here,
        which is the point of the protocol having exactly one method.

        **The redirect branch is no longer hypothetical, and the sequence inside it is fixed
        by this protocol having one method.** A redirect implementation opens a
        :class:`PaymentIntent` through :class:`PaymentIntentOpener` FIRST and builds the URL
        from what comes back, because the URL has to carry an identifier the settlement can be
        matched to and a URL handed out before that row exists is a payment nobody can claim.
        It still opens no socket: this seam's contract is "answer for the charge", and for a
        redirect rail the answer is a row and a string. A caller that awaits ``charge`` and
        finds ``is_paid`` false with a URL set has therefore not failed at anything — it has
        started something, and must say so rather than apologise.
        """
        ...


#: The rail that contacts nothing.
STUB_PROVIDER_NAME: Final[str] = "stub"


class StubCheckoutProvider:
    """Reports every charge paid, immediately, having spoken to nobody.

    **It is not a mock and it is not test-only** — it is what the shipped composition root
    wires, because the decided scope is "just put the buttons, we will implement Payme
    later". Everything downstream of it is real: real prices, a real receipt, a real
    idempotency key, a real grant written to a real ledger. The one thing that is not real is
    that no money moved.

    It never returns ``Err``. The ``Result`` return type is not for this class's benefit; it
    is so that the handler's failure branch — "that did not go through, and nothing was
    charged" — is written and covered before a rail that can actually decline exists.

    Structurally satisfies :class:`CheckoutProvider`; it does not inherit from it, matching
    ``NoopPaymentProvider``, so a Protocol change is a type error at the implementation
    rather than a silently-unimplemented method.
    """

    name: str = STUB_PROVIDER_NAME

    async def charge(self, request: PurchaseRequest) -> Result[Purchase]:
        """Mint a receipt for ``request`` without contacting anything.

        The reference is ``stub-<hex>`` and deliberately NOT derived from
        ``request.idempotency_key``: deduplication is the ledger's job, on its own unique
        index, and a provider that returned the same reference twice would hide the fact that
        it was called twice. Two charges with one key both succeed here and collapse into one
        grant downstream — which is the behaviour a real rail has too, and is therefore the
        behaviour the tests should be written against.
        """
        purchase = Purchase(
            product=request.product,
            provider=STUB_PROVIDER_NAME,
            reference=f"stub-{uuid4().hex}",
            amount_minor=request.amount_minor,
            currency=request.currency,
            is_paid=True,
        )
        _LOG.info(
            "purchase charged by the stub checkout provider; no rail was contacted",
            extra={
                "telegram_user_id": request.telegram_user_id,
                "product": request.product.value,
                "amount_minor": request.amount_minor,
                "currency": request.currency,
                "reference": purchase.reference,
                "idempotency_key": request.idempotency_key,
            },
        )
        return ok(purchase)


@runtime_checkable
class PurchaseFulfiller(Protocol):
    """The NARROW write port the bot process holds over the meter.

    The standing rule is that the bot may READ the meter and only the worker may SPEND it,
    because a gate that could write could double-charge. This port is the one carve-out, and
    it is narrow on purpose: **every method here is additive and idempotent on a unique
    index, so nothing it does has anything to compensate if the customer walks away.** A
    grant that lands twice is one grant. A charge that lands twice is a stolen song, and a
    settle that lands twice is a refund nobody asked for — which is exactly why handing the
    bot the whole ``EntitlementStore`` was rejected: that would have handed it all three.

    **``fulfil_single`` now writes TWO rows, and the invariant survives that.** A sale is
    recorded as a receipt (the amount, the currency, the rail) and the entitlement as a
    credit, in one transaction, under one key, each insert-or-ignore on its own unique index
    — so a replay writes nothing, twice. The invariant is nonetheless carried by two
    statements instead of one now, which a future refactor could split: the receipt is
    written FIRST so that a split leaves a recorded sale with no credit rather than a granted
    song with no record of the money. ``bayram.db.purchases`` states the same thing from the
    implementation side.

    Kept as its own protocol rather than three more methods on ``EntitlementStore`` for a
    second reason as well. The day a Payme webhook lands, it is a server-side handler in a
    third process that needs precisely these three calls and none of the gate's — so this is
    already the interface it will be written against.

    Every method returns ``Result`` and none of them raises, matching every other protocol in
    this codebase.
    """

    async def fulfil_single(
        self, *, telegram_user_id: int, purchase: Purchase, idempotency_key: str
    ) -> Result[CreditBalance]:
        """Turn one paid single-song purchase into a receipt and one credit. Idempotent.

        Refuses an unpaid :class:`Purchase` rather than granting optimistically: a redirect
        rail returns unpaid receipts as a normal part of starting a payment, and granting on
        one would hand out a free song for every abandoned checkout. It also refuses a
        ``Purchase`` whose ``product`` is not :attr:`Product.SINGLE`: a plan's receipt is a
        different table with a duration on it, and reshaping one into a top-up would grant a
        credit for a purchase whose songs are meant to be minted lazily.

        The receipt records what was PAID — amount, currency, rail, the rail's reference —
        which the credit ledger has nowhere to hold, so an operator can tell what a window of
        sales was worth. Note that a receipt means A SALE WAS RECORDED and not that money was
        banked, for as long as :class:`StubCheckoutProvider` is what answers ``charge``.

        A replayed key returns the UNCHANGED balance, which is the correct answer to a double
        tap — not an error, because nothing went wrong.
        """
        ...

    async def start_plan(
        self,
        *,
        telegram_user_id: int,
        purchase: Purchase,
        songs: int,
        days: int,
        idempotency_key: str,
    ) -> Result[PlanState]:
        """Open a plan running ``days`` days and holding ``songs`` songs.

        Writes NO credits. Plan songs are minted lazily, one per charge, from the plan row —
        an eager grant of all ``songs`` would need an expiry sweep to burn the unused ones,
        and the balance is a single fungible scalar with no lot structure, so that sweep
        could only guess whether it was burning plan money or a paid top-up.

        One plan at a time: if a plan is already ``is_current``, this returns THAT plan
        unchanged and writes nothing, rather than stacking a second end date over the one the
        customer already paid for.
        """
        ...

    async def plan_for(self, telegram_user_id: int) -> Result[PlanState | None]:
        """The running plan, spent or not, or ``None``. A pure read; writes nothing.

        ``is_current`` and not ``is_live``, because the screens that call this need to know
        whether to OFFER a plan, and a spent plan is still a plan the customer owns.
        """
        ...


# ---------------------------------------------------------------------------
# The redirect rail's vocabulary
#
# Everything below describes a payment that is STARTED on one process and FINISHED on
# another, minutes later, on an inbound request nobody in this process is awaiting. It lives
# in this module — the leaf that may never import ``bayram.db`` — precisely so that persistence
# and a rail adapter can both name the same value without either package importing the other,
# which is the same trick ``PurchaseFulfiller`` already plays for the inline case.
#
# Nothing here names a vendor, a hostname, a wire field or a rail's error code. That is not
# tidiness: the moment one of those leaks in, this module stops being the neutral vocabulary
# two packages can share and becomes a second, quieter copy of one rail's protocol.
# ---------------------------------------------------------------------------
class PaymentIntentState(StrEnum):
    """Where one started-but-unfinished payment has got to. Five states, one of them subtle.

    * ``PENDING`` — the customer has been handed a URL and nothing has happened since. This
      is the only state a merchant-side clock may ever act on.
    * ``AWAITING`` — **a live rail-side transaction holds this intent.** The rail has told us
      it is charging a card against this exact intent and has not yet said how that went. The
      hold is exclusive: a second rail-side transaction for an intent already in this state is
      refused, which is what makes a double charge impossible to reach rather than merely
      unlikely, because the refusal happens BEFORE a second card is touched instead of after.
    * ``PAID`` — the money is ours and the receipt and the entitlement were written in the
      same transaction that moved the intent here. Terminal.
    * ``CANCELLED`` — the rail gave up, or the customer's card declined. Terminal for THIS
      intent, and the reason ``AWAITING`` releases back to ``PENDING`` rather than landing
      here on every failure: a declined card should let the customer try another one within
      seconds, not sentence them to wait out a validity window they did not cause to lapse.
    * ``EXPIRED`` — the validity window lapsed with nobody paying. Terminal.

    **``AWAITING`` is what makes merchant-side expiry structurally unable to refuse a payment
    the rail still considers open.** The alternative — one clock, and an expiry predicate that
    reads only ``valid_until`` — is the failure this state exists to make unreachable: our
    clock and the rail's are not the same clock, and an intent expired here while a card was
    being charged there produces the single worst outcome this system has, a customer whose
    money moved against an order we have already refused. Expiry is therefore written as a
    predicate over ``PENDING`` alone. An intent under a live transaction is not "protected
    from" the sweep by a check somebody has to remember; it is not in the set the sweep can
    see, and the only way to put it back in that set is for the rail to release it.
    """

    PENDING = "pending"
    AWAITING = "awaiting"
    PAID = "paid"
    CANCELLED = "cancelled"
    EXPIRED = "expired"


@dataclass(frozen=True, slots=True)
class PaymentIntent:
    """One started payment, as everything outside persistence sees it.

    The frozen view that crosses the ``bayram.db`` boundary: a ``*Row`` never leaves that package
    (Rule 15), so the store reads its mapped row and hands back one of these. Frozen and
    slotted for the reason every value in this module is — a caller that could mutate the
    ``state`` on a copy it was handed would be reasoning about a payment that does not exist,
    and the mistake would surface as a wrong sentence to a customer rather than as an error.

    A dataclass rather than a pydantic model, matching :class:`PurchaseRequest` and unlike
    :class:`Purchase`: nothing external constructs one of these. It is built from a database
    row this system wrote, by code this system owns, and never parsed from a payload — so
    validation would be re-checking our own columns' CHECK constraints in Python.

    Three fields are worth arguing for individually, because each looks redundant:

    * ``public_ref`` is an opaque identifier minted for the sole purpose of being handed to a
      third party and rendered in a customer's browser address bar. It exists so that
      ``idempotency_key`` never has to be: that key is structured, derived from a Telegram
      user id, and giving it out would publish who bought what to anyone who can read a URL.
    * ``idempotency_key`` is nonetheless carried here, because it is the ONE string that
      crosses the process boundary intact — the bot mints it, the intent stores it, and the
      settlement writes the receipt and the credit grant under it, landing on exactly the
      unique indexes a double tap in the bot would have landed on. That is what makes a
      manual settlement by an operator and a late genuine settlement by the rail collapse
      into one grant instead of two.
    * ``merchant_id`` records WHICH merchant account this link was issued for. Without it, a
      deployment that has been pointed at a sandbox account while an old production link is
      still live in somebody's chat has no way to notice; with it, the mismatch is a refusal
      at settlement rather than a customer charged by an account we are not reconciling.

    ``telegram_user_id`` is nullable for one reason and one reason only: erasure. ``/forget``
    anonymises an intent rather than deleting it, because a rail that can still see its own
    transaction must still be able to ask us about it, and answering "that never existed"
    about a payment somebody made is worse than holding an anonymous row. Every money field,
    every clock and ``public_ref`` therefore survive erasure; the person does not.

    ``settled_at`` and ``notified_at`` are separate clocks on purpose. Money landing and the
    customer being TOLD the money landed are two events, they can be minutes apart when a
    delivery fails, and one column could not express "paid but nobody has said so yet" — which
    is exactly the population an operator needs to be able to list.
    """

    #: Opaque, structureless, and the only identifier that is ever shown to a third party.
    public_ref: str
    #: The string the bot minted and the ledger deduplicates on. Never leaves this system.
    idempotency_key: str
    #: ``None`` after erasure, and only after erasure. See the class docstring.
    telegram_user_id: int | None
    product: Product
    #: Minor units, never major, and never re-quoted later from settings: what the customer
    #: was shown is what the rail must be told and what the settlement must match against.
    amount_minor: int
    #: ISO-4217, three letters.
    currency: str
    #: The language the customer was buying in, stamped at open time so that a notification
    #: written by a different process minutes later is written in it.
    language: str
    #: Which merchant account issued the link. A settlement quoting a different one is refused.
    merchant_id: str
    #: Whether the link points at the rail's test environment. Stored beside ``merchant_id``
    #: rather than derived from settings at read time, because the answer must be the one that
    #: was true when the link was BUILT, not the one that is true when it is being settled.
    is_sandbox: bool
    #: The plan snapshot, for a plan product only: what this customer bought, frozen at the
    #: moment of sale so a later package change cannot retroactively shrink it. ``None`` for a
    #: one-off product, which has neither a duration nor a song count.
    plan_songs: int | None
    plan_days: int | None
    state: PaymentIntentState
    #: When an unpaid intent stops being payable. Named ``valid_until`` and NOT
    #: ``*_expires_at`` deliberately: that suffix is reserved throughout this codebase for
    #: RETENTION clocks that a purge sweep reads, and this is a business clock — the same
    #: distinction :attr:`PlanState.ends_at` is named for.
    valid_until: datetime
    #: When the money landed. ``None`` until it did.
    settled_at: datetime | None
    #: When the customer was told. ``None`` while they have not been. See the class docstring.
    notified_at: datetime | None


@runtime_checkable
class PaymentIntentOpener(Protocol):
    """The port the BOT holds over a redirect rail's intents: it can open one, and nothing else.

    **Deliberately ADDITIVE ONLY, and the shape is the security argument.** Opening an intent
    writes one row that grants nothing, promises nothing and costs nothing to abandon; a
    customer who walks away leaves a row that lapses. Settling one writes a receipt and a
    credit. Cancelling one releases a hold. Those last two are what a compromised or merely
    buggy bot process must not be able to do, so they are not on this protocol — not guarded
    on it, not present. The bot cannot settle a payment for the same reason it cannot spend a
    credit: the method does not exist on the object it was handed.

    This is the identical argument :class:`PurchaseFulfiller` makes one level down, and the
    two are consistent by construction: every method a bot-held port exposes is additive and
    idempotent on a unique index, so nothing it can do has anything to compensate.

    The other half of the protocol — settle, cancel, read back, statement — is a DIFFERENT
    port, held by a DIFFERENT process, the one that terminates the rail's inbound calls and is
    the sole holder of the credential those calls are authenticated with. One implementation
    may satisfy both protocols structurally; what matters is that the bot's reference to it is
    typed as this one, so the compiler is what stops the bot's half growing the other's.

    ``runtime_checkable`` verifies member PRESENCE only, never signatures — an ``isinstance``
    check in a wiring test will accept a drifted fake — so ``mypy --strict`` over ``tests`` is
    what actually holds the shape, exactly as for :class:`CheckoutProvider`.
    """

    async def open_intent(
        self,
        *,
        telegram_user_id: int,
        product: Product,
        amount_minor: int,
        currency: str,
        idempotency_key: str,
        language: str,
        merchant_id: str,
        is_sandbox: bool,
        plan_songs: int | None = None,
        plan_days: int | None = None,
    ) -> Result[PaymentIntent]:
        """Open — or re-open — the intent for ``idempotency_key``. **Never raises.**

        Idempotent on that key, and the guarantee is stronger than "writes one row": a
        replayed key must return the SAME intent, with the SAME ``public_ref``, and therefore
        produce the SAME URL. A double tap that minted a second reference would put two live
        payment pages in one customer's chat for one purchase, and the customer would have no
        way to tell which of them their money went into.

        ``plan_songs`` and ``plan_days`` default to ``None`` because a one-off product has
        neither. They are passed as a SNAPSHOT rather than looked up at settlement, so that a
        package change between the tap and the payment cannot shrink what somebody has
        already paid for — the argument the plan receipt table already makes for storing
        ``songs_included`` on the row.

        Returns ``Result`` and never raises, like every seam in this codebase: a store that
        could not write the row has told the caller something it must handle, and "the button
        did nothing and the process died" is not a way to handle it.
        """
        ...
