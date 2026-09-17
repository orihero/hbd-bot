"""Everything a handler is allowed to reach for, in one frozen container.

Handlers take ``deps: BotDeps`` as a parameter; aiogram injects it from the dispatcher's
workflow data by name. No handler imports a provider, reads the environment, or calls
``get_settings()`` — which is what makes every one of them testable with a fake queue and a
fixed clock.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Final

from bayram.bot.chatlog import ChatRecorder
from bayram.bot.payment import DEFAULT_CURRENCY, FREE_AMOUNT_MINOR, NoopPaymentProvider
from bayram.bot.ports import Clock, OrderSubmitter, SupportTicketEraser, utc_now
from bayram.bot.pricing import Pricing
from bayram.bot_chats import BotChatDirectory
from bayram.checkout import (
    CheckoutProvider,
    PaymentIntentOpener,
    PurchaseFulfiller,
    StubCheckoutProvider,
)
from bayram.churn import BotBlockRecorder
from bayram.config import Settings
from bayram.contracts import PaymentProvider
from bayram.entitlements import EntitlementStore
from bayram.lyric_budget import LyricBudgetStore
from bayram.pipeline.ports import ContentWriter
from bayram.support import SupportTicketStore
from bayram.user_profiles import UserProfileStore

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
    #: ``bayram.main`` passes ``container.credits`` here and ``container.payment`` — the plain
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
    #: configuration exercises none of the onboarding flow. ``bayram.demo`` is unaffected
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
    #: patching an import. ``bayram.main`` resolves it once, at the composition root.
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
    #: Where a complaint is written down. The ⚠️ button under a delivered song, ``/support``,
    #: the customer's answer to the ForceReply prompt and every staff action taken in the
    #: support group all end in this port.
    #:
    #: A WRITE port, and the third one on this container — ``lyric_budget``, ``purchases`` and
    #: now this — so the rule stated on ``entitlements`` is worth restating rather than
    #: assuming: the bar is not "the bot writes nothing", it is that the bot may not SPEND.
    #: This port cannot express a charge, a grant or a refusal; the most it can do is record
    #: that somebody has a problem and what was said about it. Note what it also cannot do:
    #: there is no "list this customer's tickets" method, so no screen in this bot is one
    #: refactor away from showing a customer a row an operator wrote about them.
    #:
    #: TRAILING and DEFAULTED for the reason measured on ``profiles``: the whole bot suite
    #: builds ``BotDeps`` by keyword, and a field inserted anywhere but the end, or without a
    #: default, breaks every construction site at once.
    #:
    #: ``None`` means NO TICKETING AT ALL, and it is a supported configuration rather than a
    #: degraded one: the ⚠️ button and ``/support`` fall back to exactly the sentence they
    #: rendered before this feature existed (``handlers.common.support_text``), which is the
    #: unwired-not-broken posture ``profiles`` takes. It is NOT the same thing as no support
    #: group being SELECTED (``bot_chats`` below) — that switches off only the GROUP POST,
    #: leaving the ticket written, the customer answered and the panel board populated.
    support: SupportTicketStore | None = None
    #: The ``/forget`` arm for the table above. SEPARATE from ``support`` on purpose; see
    #: :class:`~bayram.bot.ports.SupportTicketEraser` for why a delete does not belong on the
    #: seam every support handler holds.
    #:
    #: ``None`` means this deployment cannot erase tickets, and ``handle_forget`` then reports
    #: the same "nothing to erase it in" success the profile and credit arms report when their
    #: store is unwired — never a false claim that the bodies are gone. The privacy exemption
    #: written into ``tests/test_db/test_privacy_constraints.py`` names ``/forget`` as this
    #: table's erasure route, so a deployment that stores tickets and leaves this unwired has
    #: an exemption whose route does not run. ``bayram.main`` says so at boot.
    support_erasure: SupportTicketEraser | None = None
    #: WHICH GROUPS THE BOT IS IN, AND WHICH ONE OF THEM THE TICKET CARDS GO TO.
    #:
    #: This replaced two ``Settings`` fields — ``support_group_chat_id`` and
    #: ``support_group_thread_id`` — which were deleted outright rather than kept as a fallback
    #: (``SUPPORT_TICKETS_SPEC §3.8``, the 2026-09-15 amendment to D18). There is no precedence
    #: rule to reason about: the selected row is the only authority, and a host whose dotenv
    #: still carries the old variables boots fine and ignores them.
    #:
    #: A WRITE port, and the fourth on this container, so the rule ``entitlements`` states is
    #: worth checking against it once more: the bar is that the bot may not SPEND, and this
    #: port cannot express a charge, a grant or a refusal. Note what it also cannot express —
    #: SELECTING a support group. That write belongs to the admin panel, where it lands in the
    #: same transaction as the ``admin_audit_log`` row naming who made it, and
    #: :class:`~bayram.bot_chats.BotChatDirectory` deliberately has no method for it: a bot
    #: process able to repoint the support inbox is one bug away from repointing it with
    #: nothing in the audit trail to say so.
    #:
    #: Read by :class:`~bayram.bot.handlers.support.InSupportGroup` on every group update and
    #: by the card poster on every filed complaint — both UNCACHED, which the protocol argues
    #: at length: the whole point of the feature is that an operator can move the inbox and see
    #: it move, and a cache is a window in which the tickets keep arriving in the old room.
    #:
    #: TRAILING and DEFAULTED for the reason measured on ``profiles``: the whole bot suite
    #: builds ``BotDeps`` by keyword, and a field inserted anywhere but the end, or without a
    #: default, breaks every construction site at once.
    #:
    #: ``None`` means this deployment records no chat directory. The group registration on
    #: ``handlers.membership`` then writes nothing, no chat is ever selectable, and the group
    #: half of the support feature is simply off — the ticket is still written, the customer is
    #: still answered and the panel board is still populated.
    bot_chats: BotChatDirectory | None = None
