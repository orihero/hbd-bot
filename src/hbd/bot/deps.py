"""Everything a handler is allowed to reach for, in one frozen container.

Handlers take ``deps: BotDeps`` as a parameter; aiogram injects it from the dispatcher's
workflow data by name. No handler imports a provider, reads the environment, or calls
``get_settings()`` — which is what makes every one of them testable with a fake queue and a
fixed clock.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Final

from hbd.bot.chatlog import ChatRecorder
from hbd.bot.payment import DEFAULT_CURRENCY, FREE_AMOUNT_MINOR, NoopPaymentProvider
from hbd.bot.ports import Clock, OrderSubmitter, utc_now
from hbd.bot.pricing import Pricing
from hbd.checkout import (
    CheckoutProvider,
    PaymentIntentOpener,
    PurchaseFulfiller,
    StubCheckoutProvider,
)
from hbd.churn import BotBlockRecorder
from hbd.config import Settings
from hbd.contracts import PaymentProvider
from hbd.entitlements import EntitlementStore
from hbd.lyric_budget import LyricBudgetStore
from hbd.pipeline.ports import ContentWriter
from hbd.user_profiles import UserProfileStore

__all__ = ["BotDeps", "DEPS_KEY"]

#: Workflow-data key. Also the handler parameter name, because aiogram injects by name.
DEPS_KEY: Final[str] = "deps"


@dataclass(frozen=True, slots=True)
class BotDeps:
    """Immutable handler dependencies.

    ``content`` is required and has no default: the wizard writes the lyric itself now,
    because the customer approves it before anything is queued. The worker is handed a
    decided lyric rather than a brief to write one from, so a bot built without a writer
    could not get a customer past the preview screen and should fail at the composition
    root instead of at the fifth screen of a live session.

    ``payment`` defaults to the no-op provider because authorising a RENDER is out of scope
    for this build; the field exists so the real rail is a wiring change and not a refactor.
    Buying is a separate question and has its own three fields at the bottom of this class —
    ``checkout``, ``purchases`` and ``pricing`` — for the reasons given there.
    """

    settings: Settings
    submitter: OrderSubmitter
    content: ContentWriter
    payment: PaymentProvider = field(default_factory=NoopPaymentProvider)
    clock: Clock = utc_now
    amount_minor: int = FREE_AMOUNT_MINOR
    currency: str = DEFAULT_CURRENCY
    #: The entitlement meter. Every GATE that reads it is read-only — ``balance_for`` is the
    #: only method ``handlers.confirm`` and ``handlers.balance`` call, because a gate that
    #: could DEBIT could double-charge. The two exceptions are not gates and neither can
    #: spend anything: ``gate.TouchDrain`` upserts a last-seen row off the hot path, and
    #: ``/forget`` calls ``forget`` to honour a data-subject request.
    #:
    #: DEBIT and not "write" is the accurate word since ``purchases`` below shipped: the bot
    #: can now cause exactly one credit movement, an additive grant a purchase paid for, and
    #: it causes it through a port that cannot express a debit. The rule this field states was
    #: never "the bot writes nothing"; it was "the bot spends nothing", which is still true.
    #:
    #: TRAILING and DEFAULTED because the whole bot suite builds ``BotDeps`` by keyword with
    #: the fields above and must keep running with the meter unwired
    #: (tests/test_bot/conftest.py:290).
    #:
    #: ``None`` means "no meter at all", which is not the same as
    #: ``Settings.credits_enforced=False``: unwired skips the read entirely, dark performs
    #: the read and enforces the block gate and the in-flight cap from it — both of which
    #: read rows the worker's charge writes whatever that flag says — while ignoring the
    #: balance. Both let a customer with no credits through to the queue; only the second is
    #: the shipped production configuration.
    #:
    #: ``hbd.main`` passes ``container.credits`` here and ``container.payment`` — the plain
    #: no-op provider, NOT the credit-gated one — to ``payment`` above. That asymmetry is
    #: the design: the bot reads and refuses, the worker DEBITS. See
    #: ``handlers.confirm._entitlement_refusal`` and ``runtime.container._render_gate``.
    entitlements: EntitlementStore | None = None
    #: The daily lyric-write ceiling. A meter the bot genuinely WRITES to, and a separate
    #: seam from ``entitlements`` for exactly that reason: a lyric write is not a credit,
    #: cannot become a free song, and putting it on the store above would be the moment
    #: "every gate that reads the meter cannot debit it" stopped being literally true.
    #: (``purchases`` below is the other write, and it is narrow for the same reason.)
    #:
    #: Charged in ``handlers.lyrics.enter_lyrics_step``, which is the first vendor spend in
    #: the product and sits BEFORE the payment and credit gates — those guard the worker,
    #: which a customer who never presses Confirm never reaches. It is durable (a row, not
    #: process memory) because ``MAX_LYRIC_WRITES`` counts per DRAFT and ``reset_to_welcome``
    #: throws the draft away, so a per-session counter is one ``/start`` from being reset.
    #:
    #: TRAILING and DEFAULTED for the same reason as ``entitlements``: the whole bot suite
    #: builds ``BotDeps`` by keyword without it. ``None`` means "no budget wired at all" and
    #: the lyric step then behaves exactly as it did before this field existed.
    lyric_budget: LyricBudgetStore | None = None
    #: Who the customer is: their language, their phone number, their name and their photo.
    #:
    #: The ONE store on this container the bot both READS and WRITES as a matter of course,
    #: and the comment on ``entitlements`` above must not be read as a container-wide
    #: no-writes policy. There is no rule being bent here: onboarding *is* a write — the
    #: customer chooses a language and shares a contact, and the two handlers that receive
    #: those answers are the only places in the process that record them. The rule
    #: ``entitlements`` states is narrower than it looks: a GATE may not write, because a
    #: gate that could write could double-charge. This field is not read by a gate at all.
    #:
    #: TRAILING and DEFAULTED for the same reason as the two fields above, and this time it
    #: is measured: ``grep -rn "BotDeps(" tests`` finds thirty construction sites, all by
    #: keyword, and ``tests/test_bot/conftest.py`` is the shared one. A field inserted
    #: anywhere but the end, or without a default, breaks every one of them at once.
    #:
    #: ``None`` means NO PERSISTENCE AT ALL, and that is a supported configuration rather
    #: than a degraded one. The onboarding router fails open — every customer is treated as
    #: already onboarded, so nobody is trapped behind a question the process cannot record
    #: the answer to — and the Settings language picker still works off the FSM cache, which
    #: is what stops an unwired deployment from being permanently ``uz_latn`` with a picker
    #: that does nothing. The honest cost, stated so nobody discovers it in production: that
    #: configuration exercises none of the onboarding flow. ``hbd.demo`` is unaffected
    #: either way, because it drives ``build_container`` directly and never constructs a
    #: ``BotDeps``.
    profiles: UserProfileStore | None = None
    #: THE SEAM THAT WILL BECOME PAYME. It authorises a PURCHASE, which is a different
    #: question from ``payment`` above: that one authorises a RENDER, per order, against an
    #: amount the worker's gate is quoted at. Conflating them would give one protocol two
    #: meanings, and ``PaymentProvider.authorize`` is already faked three ways in the suite.
    #:
    #: Defaulted rather than optional because a checkout screen that cannot be drawn is
    #: expressed by ``pricing``/``purchases`` being ``None``, not by the absence of a rail —
    #: there is no configuration in which a button is drawn and no provider exists to press
    #: it. The default contacts nothing and reports every charge paid, which is the decided
    #: scope: real buttons, real prices, real grants, a stubbed charge.
    checkout: CheckoutProvider = field(default_factory=StubCheckoutProvider)
    #: The ONE narrow write port the bot process holds, and the exception it carves out of
    #: the rule stated on ``entitlements`` above. The bot may now cause exactly one kind of
    #: credit movement: an additive, idempotent GRANT that a checkout provider has already
    #: reported paid. This port cannot express ``charge`` or ``settle``, so "only the worker
    #: may spend" is still literally true rather than merely conventional.
    #:
    #: Why a grant is safe here and a debit is not: a grant has nothing to compensate if the
    #: customer walks away mid-flow — the credit simply sits there, and the unique index on
    #: the idempotency key makes a double tap a no-op. A debit does have something to
    #: compensate, and the bot's early returns after a gate cannot reach a refund, which is
    #: exactly what the debit rule was protecting against.
    #:
    #: TRAILING and DEFAULTED for the reason measured on ``profiles``. ``None`` means "this
    #: deployment cannot grant", and with it unset no checkout screen is ever drawn.
    purchases: PurchaseFulfiller | None = None
    #: What the checkout screen quotes. ``None`` means "this deployment does not sell".
    #:
    #: With ``purchases`` or ``pricing`` unset the paywall face is never selected and every
    #: screen renders BYTE-IDENTICALLY to what it rendered before the paywall shipped. That
    #: is what keeps the thirty existing ``BotDeps(...)`` construction sites honest rather
    #: than merely passing: they assert on exact strings, and none of them wires either
    #: field, so an assertion that still holds is evidence the old face is untouched.
    #:
    #: Deliberately NOT derived from ``Settings`` inside the handler: a handler that reached
    #: for ambient settings would be a handler no test could price differently without
    #: patching an import. ``hbd.main`` resolves it once, at the composition root.
    pricing: Pricing | None = None
    #: Where "this customer blocked the bot" is written. A WRITE port the bot holds, and it
    #: is allowed for exactly the reason ``lyric_budget`` and ``purchases`` are: it cannot
    #: express a debit, a refusal or a grant. The only thing it can say is that a customer's
    #: membership of their own chat changed, which is a fact about them and not about money.
    #:
    #: Read by nothing in the bot — no gate, no screen and no copy branches on it. Its one
    #: caller is ``handlers.membership``, which registers on the ``my_chat_member`` observer
    #: and answers nobody; the same port is held by the WORKER, whose delivery arm learns the
    #: same fact from a refused ``sendAudio``.
    #:
    #: TRAILING and DEFAULTED for the reason measured on ``profiles``: thirty ``BotDeps(...)``
    #: construction sites in the suite build it by keyword, and a field inserted anywhere but
    #: the end, or without a default, breaks every one of them at once.
    #:
    #: ``None`` means "this deployment does not record churn". The handler then returns
    #: without writing rather than failing an update, which is the same unwired-not-degraded
    #: posture ``profiles`` takes.
    bot_blocks: BotBlockRecorder | None = None
    #: Captures chat history for the admin panel. TRAILING and DEFAULTED.
    chat_recorder: ChatRecorder | None = None
    #: The redirect rail's intent port, when the wired rail is one. ``None`` for a rail that
    #: settles inline, which is what the shipped stub is.
    #:
    #: **The bot holds it and no handler calls it**, which is worth stating rather than
    #: leaving to be discovered: ``PaymeCheckoutProvider`` already holds this same object and
    #: opens the intent inside ``charge``, so the checkout flow needs nothing from this field.
    #: It is here because the composition root is the only place that knows whether the rail
    #: is a redirect one, and because the next reader of a payment — an operator command, a
    #: "what happened to my payment?" reply — will need to ask about an intent from a handler
    #: rather than through a provider whose one method is ``charge``.
    #:
    #: The port is ADDITIVE ONLY by construction: it declares ``open_intent`` and nothing
    #: else, so this process cannot settle, cancel or force-settle a payment. That is the same
    #: carve-out ``purchases`` above makes — the bot may cause a grant it has been told was
    #: paid for, and may not cause a debit — one level further out, against a rail instead of
    #: against the meter.
    #:
    #: TRAILING and DEFAULTED for the reason measured on ``profiles``: thirty ``BotDeps(...)``
    #: construction sites in the suite build it by keyword, and a field inserted anywhere but
    #: the end, or without a default, breaks every one of them at once.
    intents: PaymentIntentOpener | None = None
