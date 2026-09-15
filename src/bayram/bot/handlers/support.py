"""Support tickets: the customer's half in private, and the staff group's half in the group.

Two routers, one feature, and they are two routers because they answer different people in
different chats with different authority. :func:`build_router` is the customer's — the ⚠️ tap,
``/support`` and the reply that fills in what went wrong. :func:`build_group_router` is the
staff room's — a reply relayed back to the customer, ``✋ Claim`` and ``✅ Resolve``. Nothing in
the second one can be reached from a private chat and nothing in the first can be reached from
the group; :class:`InSupportGroup` and the private-chat filters are what make that structural
rather than a habit each handler has to remember.

**There is no FSM state in this flow at all, and that is the load-bearing decision.** The ⚠️
button is drawn by the WORKER onto a delivered song's closing message, which sits on the
customer's message roll for ever: it can be tapped a month later, from three screens into a
half-finished wizard, and ``state.set_state(...)`` would throw that draft away — the recipient's
name, the note about them, the approved lyric. So "which question is this customer answering?"
is not held in the FSM. It is held in the ROW: the bot sends a
:class:`~aiogram.types.ForceReply` prompt, records that prompt's ``message_id`` on the ticket,
and a private message whose ``reply_to_message`` matches it belongs to that ticket. Telegram's
own reply threading does the work an FSM key would have done, and because the match is "is a
reply to *that* message" rather than "is text", ordinary wizard input is never swallowed.
Nothing is added to ``bot/draft.py``'s key list and there is nothing for
``clear_keeping_identity`` to preserve.

**``prompt_message_id`` is "the message this ticket is listening on", not "the ForceReply we
sent once", and reading it the narrow way was a critical bug.** ``support.ticket.reply`` — the
relay a customer reads when a staffer answers — ends with *"Reply here if there is more to
say."* When the column only ever held the original prompt and the lookup only ever matched
``described_at IS NULL``, that sentence was an invitation to a dead end: the follow-up matched
no ticket, fell straight past this router, and was claimed by whichever wizard step the
customer happened to be parked in. At ``Wizard.name`` "thanks, it is fine now" was stored as
the RECIPIENT'S NAME and the pipeline SANG IT; at ``Wizard.note`` it became free text about a
real third party. So :func:`_relay_to_customer` re-points the column at each relay
(``SupportTicketStore.listen_on``), the lookup matches described rows too, and
:func:`handle_customer_message` branches on :attr:`~bayram.support.TicketSnapshot.is_described`
— an undescribed ticket takes the body, a described one appends a ``REPLY`` event authored by
the CUSTOMER, relays it into the group under the card, and applies
:data:`~bayram.support.REOPEN_STATUS` so ``waiting`` and ``resolved`` come back to
``in_progress``. That is also the only exit ``waiting`` has ever had: the column means *waiting
on the customer*, and before this there was no way for the customer to end the wait.

**The customer router's MESSAGE observer does NOT stand down for ``Wizard.submitting``, and
that is a deliberate exception to a real rule.** The rule is real: ``handlers.submitting``
claims every message and every callback in that state, ``commands.handle_forget`` re-parks a
running order there on purpose, and a router that swallowed the park would blind
``order_in_flight`` — after which the next ``/cancel`` answers "nothing was made, and nothing
was kept" about a song that then arrives. ``onboarding`` and ``menu`` carry the stand-down for
exactly that reason and must keep it. It does not apply HERE because those two are catch-alls
and this observer is not: its single registration is filtered by :class:`ListeningTicket`,
"this private message is a reply to a message id some ticket of this account's has recorded",
which no wizard input can satisfy — the customer would have to reply to our own support prompt
for it to match. With the stand-down in place the observer stood down for a state it could not
have harmed, and the cost was concrete: ``/support`` typed mid-render (``commands`` is above
everything, so the command itself always worked) sent the ForceReply prompt, and the
customer's answer to it was swallowed by ``submitting.handle_message_while_working`` — a ticket
opened, prompted, and then deliberately deafened. The CALLBACK observer keeps its stand-down:
⚠️ pressed while a song is rendering still answers ``wizard.queued``, which is the accepted
cost recorded when this shipped and is not a routing hole, because a tap that opens no ticket
loses nothing a customer typed.

**The customer is confirmed before the card is posted, and never after it.** A ticket is a
promise that a person will read this; the group post is how that person finds out. If Telegram
refuses the group — rate limit, the bot removed from the room, a chat id typed wrong — the
ticket is still written, still on the panel's board and still answerable, and the customer must
not be told otherwise because a send failed. So :func:`_post_card` catches
``TelegramAPIError``, logs it, leaves the once-only latch UNSET so a later retry can still
claim it, and returns. The one thing that must never happen is a complaint that exists
nowhere, and that is why nothing in this module makes the row conditional on the send.

**The group post is claimed, not assumed.** ARQ runs ``retry_jobs=True`` and SIGTERM cancels
running jobs, so every job in this system is replayed on every deploy and "I already posted
this" may not live in a job. It lives in ``support_tickets.group_message_id``, and
:meth:`~bayram.support.SupportTicketStore.claim_group_post` is the conditional ``UPDATE`` whose
rowcount is the lock. The honest limit of that guarantee, because the seam's own docstring
states it rather than overselling it: Telegram hands out a ``message_id`` only in the RESPONSE
to ``sendMessage``, so the claim cannot precede the send the way ``payment_intents.resumed_at``
precedes its call. What the latch guarantees is that exactly ONE racing sender's message id is
ever recorded, so the relay has exactly one card to listen to; a loser deletes the card it just
sent (:func:`_undo_duplicate_card`).

**The group router claims EVERY update from the support chat, including the ones it cannot
resolve.** :class:`ReplyToCard` answering ``False`` used to mean "not ours, pass it down the
tree" — and the tree below is the CUSTOMER's. A reply to an erased ticket's card, to a
duplicate card whose delete Telegram refused, to the bot's own :data:`_RELAY_FAILED` warning
(the most natural thing in the room for a triager to reply to) or to a card answered with a
sticker therefore reached ``onboarding``'s catch-all, which claims every update from an account
with no ``user_profiles`` row — which is every staffer, because a triager has never ordered a
song from this bot. The result was the onboarding language screen and a phone-number keyboard
posted INTO THE SUPPORT GROUP while the staffer believed they had answered a customer and the
customer heard nothing. So both observers end in a catch-all
(:func:`handle_unresolved_group_message`, :func:`handle_unresolved_group_callback`) and nothing
from that chat id ever falls through to a customer-facing router. The other half of that hole
is closed one layer up, in ``handlers.build_router``: the customer-facing routers are nested
under a private-chat filter, so they cannot act in ANY group, selected or not.

**Nothing here writes the complaint through ``ChatRecorder``.** ``offer()`` is explicitly lossy
— it returns ``False`` when its bounded queue is full — and ``flush_batch`` swallows every
exception, so a chat log is the wrong place for the one message this feature exists to keep.
The ticket row is the record. Chat logging still captures the message incidentally, which is
fine and is not the same thing.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Final
from uuid import UUID

from aiogram import Bot, F, Router
from aiogram.enums import ChatType
from aiogram.exceptions import TelegramAPIError
from aiogram.filters import Filter, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import (
    CallbackQuery,
    ForceReply,
    InaccessibleMessage,
    InlineKeyboardMarkup,
    Message,
    ReactionTypeEmoji,
    TelegramObject,
)

from bayram.bot.callbacks import SupportAction, SupportCB, read_reference
from bayram.bot.delivery import MAX_MESSAGE_CHARS, is_blocked_by_customer, order_reference
from bayram.bot.deps import BotDeps
from bayram.bot.handlers.common import COMMAND_PREFIX, Event, say, support_text
from bayram.bot.i18n import escape_html, translate
from bayram.bot.middleware import resolve_language
from bayram.bot.states import Wizard
from bayram.bot.support_card import card_keyboard, render_card
from bayram.bot_chats import BotChatDirectory, SupportGroupTarget
from bayram.config import Settings
from bayram.contracts import (
    Language,
    SupportTicketEventKind,
    SupportTicketSource,
    SupportTicketStatus,
    is_err,
    is_ok,
)
from bayram.logging import get_logger
from bayram.support import (
    EventAuthor,
    RelayAddressee,
    SupportTicketStore,
    TicketQuotaVerdict,
    TicketSnapshot,
    reopen_target,
)

__all__ = [
    "build_router",
    "build_group_router",
    "open_ticket",
    "post_card",
    "support_group_target",
    "InSupportGroup",
    "ListeningTicket",
    "ReplyToCard",
    "relay_text_for",
    "MAX_BODY_CHARS",
    "MAX_STAFF_NAME_CHARS",
]

_LOG = get_logger(__name__)

#: The longest complaint this bot will store, restated from ``support_tickets.body``.
#:
#: Restated rather than imported for the reason ``handlers/common.py`` guards its one
#: ``bayram.db`` name behind ``if TYPE_CHECKING:``: SQLAlchemy must not enter the bot through a
#: handler module, and a ``Final`` int is not worth an import that drags the ORM in. The two
#: numbers agree by construction rather than by luck — both are Telegram's own single-message
#: ceiling, chosen so the column can never truncate a complaint that was physically sendable.
#: A longer message cannot arrive: Telegram refuses it at the customer's client.
MAX_BODY_CHARS: Final[int] = 4_096

#: ``support_tickets.assigned_admin_username`` and
#: ``support_ticket_events.author_display_name`` are both ``VARCHAR(64)``. A Telegram
#: ``first_name`` is bounded at 64 by Telegram and a ``username`` at 32, so this only bites on a
#: composed label — but SQLite enforces no length at all, so an over-long value would be an
#: ``IntegrityError`` from inside a half-written transaction on Postgres and a silent pass in
#: the suite. Cut here, where the value is made.
MAX_STAFF_NAME_CHARS: Final[int] = 64

#: The catalogue key the relay is rendered from, named so it is one string and so the locale
#: contract's constant scan (``*_KEY`` holding a dotted literal) enrols it automatically.
_RELAY_KEY: Final[str] = "support.ticket.reply"

#: What the customer is told when their follow-up joined a ticket that already has a body.
_FOLLOW_UP_KEY: Final[str] = "support.ticket.follow_up"

#: The re-prompt a customer gets at the undescribed ceiling, naming the ticket they hold.
_STILL_OPEN_KEY: Final[str] = "support.ticket.still_open"

#: What the group is told when a relay could not be delivered. English, in the group, for the
#: reason ``bayram.bot.support_card`` gives: staff copy never enters the customer catalogues.
#:
#: **Two constants and not one, because "blocked" and "refused" send a staffer to two different
#: places.** A ``Forbidden: bot was blocked by the user`` is a fact about the customer and there
#: is nothing to do but stop writing to them. Everything else — most often a 400 because the
#: finished message ran past Telegram's ceiling — is a fact about US, and reporting it as a
#: block sent the staffer off to investigate a customer who had blocked nobody while the real
#: cause (a long answer that never fitted) went unlooked-at. :func:`is_blocked_by_customer` is
#: the one place that classification lives; it is imported rather than re-derived here.
_RELAY_FAILED: Final[str] = (
    "⚠️ I could not deliver that to the customer — they have blocked the bot. "
    "The reply is recorded on the ticket."
)
_RELAY_REFUSED: Final[str] = (
    "⚠️ Telegram refused that message, so the customer has not seen it. This is not a block — "
    "the reply is recorded on the ticket, so try it again, shorter."
)
_RELAY_NEEDS_TEXT: Final[str] = (
    "✍️ I can only relay text. Type the answer as a reply to the card and I will send it on."
)
_RELAY_NO_TICKET: Final[str] = (
    "⚠️ I have lost track of that ticket. Open it in the panel and answer from there."
)

#: What a staffer is told when their reply resolves to no card at all.
#:
#: Said rather than swallowed, because the alternative shipped and was worse than silence: an
#: unresolved reply fell through to the CUSTOMER routers and the onboarding catch-all answered
#: it with the language screen, in the staff room. Answering here is what keeps that update
#: inside this router — and a staffer who has just typed a paragraph is owed the news that it
#: went nowhere, which no log line delivers.
_NO_TICKET_MATCH: Final[str] = (
    "⚠️ I could not match that to a ticket. Reply to the ticket card itself, or open the "
    "ticket in the panel and answer from there."
)
_MOVE_REFUSED: Final[str] = "Somebody got there first — the card above is the current state."

#: What a staffer replying to a card in a room the inbox has MOVED OUT OF is told.
#:
#: **It exists because the alternative was silence, and silence here is a customer who is never
#: answered.** When the inbox moves (or is cleared), every card already posted stays where it
#: is and ``support:card_sync`` goes on repainting it, so the old room looks like a working
#: queue. A triager who replies to one of those cards has written an answer to a real person;
#: before :func:`_touches_a_card_in` that update was claimed by no router at all and they got
#: nothing back.
#:
#: **It says the reply was NOT sent, in those words, before it says anything else.** A staffer
#: who reads "the inbox moved" and nothing else will reasonably assume the message went
#: through and that only future cards are affected. The one fact they must leave with is that
#: this customer has not heard from them.
#:
#: Staff copy, so an English literal and not a catalogue key, for the reason
#: ``bayram.bot.support_card`` argues in full: the four customer catalogues are held in exact
#: key parity, and one internal triage sentence in them is four translations, for ever.
_INBOX_MOVED: Final[str] = (
    "📦 I did NOT send that to the customer — this chat is no longer the support inbox. "
    "The ticket is still open: answer it from the panel, or in the chat that is selected now."
)

#: The same news in a callback answer, which Telegram cuts at 200 characters.
#:
#: A separate literal rather than a trim of :data:`_INBOX_MOVED`, because it reports the
#: opposite outcome: the button DID work. Claiming and resolving are internal triage that any
#: operator could do from the panel, so they are not refused in a room that still holds the
#: card — see :class:`InSupportGroup`. What the staffer needs to know is that they are working
#: out of a room new tickets no longer arrive in.
_INBOX_MOVED_TOAST: Final[str] = (
    "Done — but this chat is no longer the support inbox, so new tickets arrive elsewhere. "
    "Check the panel for the chat that is selected now."
)

#: What a staffer typing a command in the support group is told.
#:
#: ``commands`` and ``start`` were moved under the private-chat umbrella
#: (``handlers.build_router``) because ``/start`` in a group posted a ``request_contact``
#: keyboard in front of everyone in the room. That closes a leak and costs the one thing the
#: old arrangement was FOR: a staffer's ``/privacy`` or ``/forget`` typed in this room used to
#: reach its handler. It cannot any more — and it must not, because the answer to ``/privacy``
#: is a statement about the person asking and this room is other people. So the request is not
#: denied, it is redirected: the same command in a DM with the bot does exactly what it always
#: did. ``gate.ERASURE_COMMANDS`` is untouched; nothing about a blocked account changes.
_COMMANDS_ARE_PRIVATE: Final[str] = (
    "🔒 I answer commands in a private chat only — /privacy and /forget are about YOUR own "
    "account, and this room is other people. Send it to me in a direct message instead."
)

#: What a trimmed relay ends with, so a customer can tell a cut answer from a complete one.
_RELAY_ELLIPSIS: Final[str] = "…"

#: How a customer's follow-up appears in the group, under the card it belongs to.
#:
#: A literal rather than a catalogue key, and NOT named ``*_KEY``, because it is staff copy —
#: ``bayram.bot.support_card`` argues that in full: ``translate`` falls back across four
#: locales and the catalogues are held in exact key parity, so one staff-facing string in a
#: customer catalogue obliges four translations of an internal triage message, for ever.
#:
#: ``<blockquote>`` is in ``test_locale_contract.SUPPORTED_TAGS`` and matches the card's own
#: treatment of the body, so a triager reads the customer's two messages in one visual shape.
_FOLLOW_UP_CARD_TEMPLATE: Final[str] = (
    "💬 <b>The customer added to ticket {ref}</b>\n<blockquote>{body}</blockquote>"
)

#: The acknowledgement a delivered relay gets. A REACTION rather than a message, because the
#: group is a working queue: one bot message per staff reply would double its traffic and push
#: the cards a triager is scanning off the screen. A reaction is attached to the staffer's own
#: message, so "did that go out?" is answerable by looking at what you just sent.
#:
#: Reactions can be refused — the bot may lack the right, and a supergroup can restrict which
#: emoji are allowed — so the call is best-effort and its failure is a debug line. The failure
#: that MATTERS is the undelivered relay, and that one is always a message.
_RELAY_ACK: Final[str] = "👌"


# ---------------------------------------------------------------------------
# Opening a ticket: the ⚠️ button, /support, and the ForceReply prompt
# ---------------------------------------------------------------------------
async def open_ticket(
    event: Event,
    state: FSMContext,
    deps: BotDeps,
    *,
    source: SupportTicketSource,
    order_id: UUID | None,
) -> None:
    """Write the row a complaint starts as, then ask for the words. The one entry point.

    Called from three places that must not become three flows: the ⚠️ button carrying an order
    id (``handlers.support.handle_open``), the order-less ⚠️ on a degraded screen
    (``handlers.navigation.handle_report_problem``) and ``/support``
    (``handlers.commands.handle_support``). That convergence is the product decision
    ``common.support_text`` was originally extracted to keep — a customer who tries the button
    and then the command must not be given two different routes to one inbox — carried forward
    now that the route is a table rather than a sentence.

    **With no store wired it degrades to exactly what shipped before this feature**, the
    ``common.support_text`` sentence, rather than to an apology. ``BotDeps.support`` is ``None``
    on a deployment with no database, and that is a supported configuration; a customer there
    is still told where to write.

    **The quota is advisory and this function fails OPEN on a broken meter.** A count that
    cannot be read is not a reason to refuse a complaint — the same posture
    ``gate.InboundGateMiddleware`` takes, for a stronger reason: the person being refused is
    already unhappy, and the cost of one ticket over the line is a row.

    **The two ceilings get opposite answers, and collapsing them was a real denial of
    service.** The DAILY ceiling is a refusal: a sixth ticket in one UTC day is a script, not a
    person with six problems, and there is nothing useful to hand back because the five they
    opened today may all be described and working. The UNDESCRIBED ceiling is not a refusal at
    all — §1.4 of the specification says a customer who taps ⚠️ four times without typing
    "gets the prompt for the ticket they already have, not a fourth row", and this build
    answered it with ``support.ticket.too_many`` instead. That mattered most to the customer
    least able to work around it: ``/support`` is in ``gate.ERASURE_COMMANDS`` so a BLOCKED
    account could open tickets, its descriptions were refused by the block gate, and after
    three taps it held three empty tickets and was locked out of support permanently. The gate
    half of that loop is fixed in ``bayram.bot.gate``; this half is
    :func:`_reprompt_the_open_ticket`, which re-points the ticket they are holding at a fresh
    ForceReply rather than minting a row they will never be able to fill.

    The prompt is sent as a NEW message via :func:`~bayram.bot.handlers.common.say` and is never
    edited over the screen it was tapped from. That screen is the closing message, and it
    carries the customer's order number and their Make-another button — the two things they
    would lose.
    """
    language = await resolve_language(state)
    store = deps.support
    telegram_user_id = _sender_id(event)
    if store is None or telegram_user_id is None:
        # No ticketing on this deployment, or an update with nobody behind it. Both get the
        # pre-feature sentence: the destination is never faked, and a customer is never left
        # with an apology and no route.
        await say(event, support_text(language, deps.settings.support_contact))
        return
    now = deps.clock()
    verdict = await _quota_verdict(store, telegram_user_id, now=now)
    if verdict is not None and verdict.is_over_daily:
        await say(event, translate("support.ticket.too_many", language))
        return
    if verdict is not None and verdict.is_holding_too_many:
        if await _reprompt_the_open_ticket(event, store, telegram_user_id, language, now=now):
            return
        # No row came back for a count that said there was one — a delete between the two
        # statements, or a read replica disagreeing with itself. Fall through and open a new
        # ticket rather than leave a customer holding a refusal we cannot justify: one row
        # over the line is the cheap error, and silence is the expensive one.
        _LOG.info(
            "the undescribed ceiling was reached but no open ticket could be handed back",
            extra={"telegram_user_id": telegram_user_id, "undescribed": verdict.undescribed},
        )
    opened = await store.open_ticket(
        telegram_user_id=telegram_user_id,
        language=language,
        source=source,
        order_id=order_id,
        now=now,
    )
    if is_err(opened):
        _LOG.error("a support ticket could not be opened", extra=opened.error.to_log_dict())
        await say(event, translate("support.ticket.unavailable", language))
        return
    ticket = opened.value
    _LOG.info(
        "support ticket opened",
        extra={
            "ticket_id": str(ticket.id),
            "public_ref": ticket.public_ref,
            "source": source.value,
            "has_order": order_id is not None,
        },
    )
    await _ask_for_the_words(event, store, ticket, language=language, now=now)


async def _quota_verdict(
    store: SupportTicketStore, telegram_user_id: int, *, now: datetime
) -> TicketQuotaVerdict | None:
    """The meter's answer, or ``None`` when the meter could not be read.

    ``None`` rather than a fabricated "allowed" verdict, because the caller has two ceilings
    to branch on and a made-up verdict would have to lie about both. Fails open at the call
    site — see :func:`open_ticket` — and the unreadable case is a WARNING, not a refusal.

    A verdict at a ceiling is logged at INFO with both counts rather than only the boolean,
    because a person at the line and a script holding the button down want different responses
    from an operator and the boolean cannot tell them apart; that is the reasoning
    ``TicketQuotaVerdict`` carries both numbers for.
    """
    result = await store.check_open_quota(telegram_user_id, now=now)
    if is_err(result):
        _LOG.warning("the support quota could not be read", extra=result.error.to_log_dict())
        return None
    verdict = result.value
    if not verdict.is_allowed:
        _LOG.info(
            "a support ticket reached a quota ceiling",
            extra={
                "undescribed": verdict.undescribed,
                "opened_today": verdict.opened_today,
                "max_undescribed": verdict.quota.max_undescribed,
                "max_per_day": verdict.quota.max_per_day,
                "is_over_daily": verdict.is_over_daily,
            },
        )
    return verdict


async def _reprompt_the_open_ticket(
    event: Event,
    store: SupportTicketStore,
    telegram_user_id: int,
    language: Language,
    *,
    now: datetime,
) -> bool:
    """Hand back the undescribed ticket this account already holds. ``False`` if there is none.

    §1.4's rule, implemented: the fourth tap gets the third ticket's prompt rather than a
    fourth row or a refusal. Two things happen and both matter.

    The copy names the reference (:data:`_STILL_OPEN_KEY`), so the customer can see this is
    the same complaint rather than a bot that has forgotten them — a bare re-prompt reads as
    the previous tap having done nothing.

    And the ticket is RE-POINTED at the new prompt (``listen_on``) rather than left listening
    on the old one. The old prompt may be a week up their chat and Telegram will happily let
    them reply to either, but only one message is on screen, and the one on screen has to be
    the one that resolves. ``listen_on`` is unconditional for exactly this: ``attach_prompt``
    would refuse, because the column is not NULL.
    """
    found = await store.latest_undescribed_ticket(telegram_user_id)
    if is_err(found):
        _LOG.warning("the open support ticket could not be read", extra=found.error.to_log_dict())
        return False
    ticket = found.value
    if ticket is None:
        return False
    prompt = await _send_prompt(event, translate(_STILL_OPEN_KEY, language, ref=ticket.public_ref))
    if prompt is None:
        _LOG.error(
            "the support re-prompt could not be sent; the ticket is still undescribed",
            extra={"ticket_id": str(ticket.id), "public_ref": ticket.public_ref},
        )
        # Answered nothing, but the customer is not owed a second refusal on top of a send
        # that failed; returning True keeps this from also minting a row.
        return True
    listening = await store.listen_on(ticket.id, prompt_message_id=prompt, now=now)
    if is_err(listening):
        _LOG.error(
            "the support re-prompt could not be recorded", extra=listening.error.to_log_dict()
        )
    return True


async def _ask_for_the_words(
    event: Event,
    store: SupportTicketStore,
    ticket: TicketSnapshot,
    *,
    language: Language,
    now: datetime,
) -> None:
    """Send the ForceReply prompt and record which message the ticket is waiting on.

    **The row exists before the prompt does**, which is why this is a second statement rather
    than a column filled in by ``open_ticket``: a prompt whose ticket failed to write is a
    message asking somebody to describe a problem into nothing.

    ``ForceReply`` rather than a keyboard or an FSM state because it is the only one of the
    three that survives the customer doing something else first. It pops the reply composer
    open with the prompt quoted above it, and if they wander off and come back a day later the
    quote is still there — and ``reply_to_message.message_id`` still identifies which ticket
    they are answering. ``selective=True`` so the composer opens for this customer only, which
    matters not at all in a private chat and costs nothing to be right about.

    A send that Telegram refuses leaves an undescribed ticket, which is a real row that the
    board deliberately excludes (``described_at IS NULL``) and the quota deliberately counts.
    It is logged and nothing else is attempted: there is no second channel to apologise
    through, since the failure is precisely that we cannot message this chat.
    """
    prompt = await _send_prompt(event, translate("support.ticket.prompt", language))
    if prompt is None:
        _LOG.error(
            "the support prompt could not be sent; the ticket is open and undescribed",
            extra={"ticket_id": str(ticket.id), "public_ref": ticket.public_ref},
        )
        return
    attached = await store.attach_prompt(ticket.id, prompt_message_id=prompt, now=now)
    if is_err(attached):
        _LOG.error("the support prompt could not be recorded", extra=attached.error.to_log_dict())
        return
    if not attached.value:
        # ``False`` is "this ticket already had a prompt", which can only be a replay. Do NOT
        # send a second prompt: the customer would be looking at two identical questions and
        # only one of them would resolve to the row.
        _LOG.info(
            "the support prompt was already recorded; not prompting twice",
            extra={"ticket_id": str(ticket.id)},
        )


async def _send_prompt(event: Event, text: str) -> int | None:
    """Put the ForceReply up and return its ``message_id``, or ``None`` if it did not go.

    Mirrors :func:`~bayram.bot.handlers.common.say` — a new message, never an edit — and differs
    from it in the one way this flow needs: it returns the sent message, because the whole
    mechanism depends on knowing which message the customer will be replying to. ``say`` cannot
    be reused for that reason and is deliberately not changed to return one; every other caller
    of it has no use for the value, and a helper that returns something all but one caller
    ignores is a helper whose return value goes unchecked.
    """
    target = event.message if isinstance(event, CallbackQuery) else event
    if not isinstance(target, Message):
        return None
    try:
        sent = await target.answer(text, reply_markup=ForceReply(selective=True))
    except TelegramAPIError as exc:
        _LOG.warning("the support prompt was refused", extra={"failure": repr(exc)})
        return None
    return sent.message_id


def _sender_id(event: TelegramObject) -> int | None:
    """The account behind an update, or ``None`` for one Telegram attributes to nobody."""
    user = getattr(event, "from_user", None)
    return getattr(user, "id", None)


# ---------------------------------------------------------------------------
# The customer's words
# ---------------------------------------------------------------------------
class ListeningTicket(Filter):
    """Is this private message a reply to a message one of this account's tickets is on?

    Returns a DICT rather than ``True``, so the ticket travels into the handler and the lookup
    is paid for once — the idiom ``handlers.onboarding.NotOnboarded`` establishes and the
    reason it is a filter at all. Doing the work in the filter is also what keeps this router
    from SWALLOWING updates it has no business claiming: a handler that had to answer "this
    reply is not ours" by returning would have already consumed the message, and every reply to
    any bot message — a progress frame, a lyric sheet, a closing message — would stop reaching
    the wizard steps below.

    **Both keys are required and the account is not decoration.** ``message_id`` is a per-chat
    counter, so two customers hold the value ``41`` routinely; a lookup on the message id alone
    would attach one person's complaint to another person's ticket, which is the worst single
    failure this feature could have.

    **It used to be called ``AwaitingDescription`` and to match undescribed tickets only, and
    the rename records the bug that narrowness was.** It is not "awaiting a description"; it is
    "a ticket is listening on this message". A reply to the RELAY of a staff answer — which the
    relay copy ends by asking for — matched nothing under the old name, fell past this router,
    and was taken as wizard input; at ``Wizard.name`` the customer's follow-up became the
    recipient's name and was sung to them. The narrowness that protects a filed complaint from
    being overwritten lives in ``describe_ticket``'s own conditional ``UPDATE``, which is the
    statement that would do the overwriting, and not here.

    **The filter is still narrow in the one way that matters for routing**, which is why the
    customer router's message observer needs no ``Wizard.submitting`` stand-down: the message
    must be a REPLY, to a message id this account's own ticket has recorded. Ordinary wizard
    input — a typed name, a pasted lyric, a note — cannot satisfy that.
    """

    async def __call__(
        self, event: TelegramObject, deps: BotDeps
    ) -> dict[str, TicketSnapshot] | bool:
        if not isinstance(event, Message) or deps.support is None:
            return False
        replied_to = event.reply_to_message
        telegram_user_id = _sender_id(event)
        if replied_to is None or telegram_user_id is None or not (event.text or "").strip():
            return False
        found = await deps.support.ticket_listening_on(
            telegram_user_id, prompt_message_id=replied_to.message_id
        )
        if is_err(found):
            _LOG.error("a support ticket lookup failed", extra=found.error.to_log_dict())
            return False
        if found.value is None:
            return False
        return {"ticket": found.value}


async def handle_customer_message(
    message: Message, state: FSMContext, deps: BotDeps, ticket: TicketSnapshot
) -> None:
    """The customer said something to a ticket. Which something depends on the ticket.

    One handler and not two registrations, because the two cases are told apart by a column
    (``described_at``) and not by anything in the update, and a second filter would have to
    repeat the whole lookup to read it. The branch is one line and the two halves are two
    functions below.
    """
    if ticket.is_described:
        await _handle_follow_up(message, state, deps, ticket)
        return
    await _handle_description(message, state, deps, ticket)


async def _handle_description(
    message: Message, state: FSMContext, deps: BotDeps, ticket: TicketSnapshot
) -> None:
    """The complaint itself: fill the body, confirm, then put the card in front of staff.

    **The confirmation goes out BEFORE the group post is attempted**, and the order is the
    whole point. What the customer is owed is the knowledge that a person now has this; that
    becomes true when the row is written, not when Telegram accepts a message into a room they
    cannot see. A confirmation sent after a successful post would be a confirmation the
    customer does not get on exactly the deploys where the group is rate-limited.

    ``describe_ticket`` returning ``None`` is the race between two messages sent in the same
    second: the row stopped being undescribed between the filter's read and this write. The
    first complaint stands and the second is NOT written over it — a follow-up sentence
    replacing the original is how the only description of a problem gets lost — so they are
    told it is already in. The ORDINARY second message no longer arrives here at all; it is a
    follow-up now, and :func:`_handle_follow_up` relays it to the people working the ticket
    instead of answering "we already have that" and dropping it.
    """
    language = await resolve_language(state)
    store = deps.support
    if store is None:  # pragma: no cover - the filter cannot match with no store
        return
    body = (message.text or "").strip()[:MAX_BODY_CHARS]
    now = deps.clock()
    described = await store.describe_ticket(ticket.id, body=body, now=now)
    if is_err(described):
        _LOG.error("a support ticket could not be described", extra=described.error.to_log_dict())
        await message.answer(translate("support.ticket.unavailable", language))
        return
    if described.value is None:
        await message.answer(
            translate("support.ticket.already_filed", language, ref=ticket.public_ref)
        )
        return
    filled = described.value
    await message.answer(translate("support.ticket.filed", language, ref=filled.public_ref))
    # Resolved AFTER the customer has been confirmed, and that ordering is the same one the
    # paragraph above states about the send: what the customer is owed became true when the row
    # was written. A directory read that fails, or a deployment where nobody has selected a
    # group, must not delay or change the sentence they have already been shown.
    await post_card(
        message.bot,
        store,
        deps.settings,
        filled,
        target=await support_group_target(deps.bot_chats),
        now=now,
    )


async def _handle_follow_up(
    message: Message, state: FSMContext, deps: BotDeps, ticket: TicketSnapshot
) -> None:
    """A second message about a ticket that already has a body. Three writes and one send.

    **This is the path that did not exist**, and its absence was this feature's worst bug: the
    relay copy ends "Reply here if there is more to say", nothing claimed that reply, and it
    was taken as wizard input and sung. It is also the only exit ``waiting`` has — that column
    means *waiting on the customer*, and until the customer could speak nothing could end the
    wait but an operator dragging the card.

    The order is: record, acknowledge, relay, move.

    * **Record first.** The ``REPLY`` event carries ``author_kind=CUSTOMER``, so the panel's
      timeline reads as the conversation it is rather than as a list of things we did. It is
      written before the group send for the same reason a staffer's reply is: the record of
      what a customer said may not depend on a Telegram call succeeding.
    * **Acknowledge before the group post is attempted**, which is :func:`_handle_description`'s
      rule one message later in the same conversation. What the customer is owed is the
      knowledge that this is on the ticket, and that became true when the event was written —
      not when Telegram accepted a message into a room they cannot see.
    * **Relay as a threaded reply to the card**, so a triager scanning the room sees it under
      the complaint it belongs to instead of as a loose message. A ticket whose card never
      reached the group (``group_message_id IS NULL`` — no group selected, or a refused
      send) is not a failure here: the event is on the timeline and the panel has it, so this
      returns quietly rather than posting a rootless message into a room.
    * **Move last, and only from the two statuses a customer's own words may move.**
      :func:`~bayram.support.reopen_target` is the whole grammar; ``new`` and ``in_progress``
      stay put. A customer adding a sentence to a ticket nobody has read has not made
      "somebody is working this" true.

    The customer is acknowledged from the row they already hold, never with a new reference: a
    follow-up that minted a second ticket number is how one conversation becomes two work
    items with half the story each.
    """
    language = await resolve_language(state)
    store = deps.support
    if store is None:  # pragma: no cover - the filter cannot match with no store
        return
    body = (message.text or "").strip()[:MAX_BODY_CHARS]
    now = deps.clock()
    recorded = await store.append_event(
        ticket.id,
        kind=SupportTicketEventKind.REPLY,
        author=EventAuthor.customer(ticket.telegram_user_id),
        now=now,
        body=body,
    )
    if is_err(recorded):
        _LOG.error("a customer follow-up could not be recorded", extra=recorded.error.to_log_dict())
        await message.answer(translate("support.ticket.unavailable", language))
        return
    await message.answer(translate(_FOLLOW_UP_KEY, language, ref=ticket.public_ref))
    await _relay_to_group(message.bot, ticket, body)
    await _reopen_by_answering(store, ticket, now=now)


async def _relay_to_group(bot: Bot | None, ticket: TicketSnapshot, body: str) -> None:
    """Put the customer's follow-up under its card. Best effort; the event is the record.

    ``reply_to_message_id`` is what makes it land in the card's thread. The wrapper is an
    English literal and the customer's words go through ``escape_html`` — both for the reasons
    ``bayram.bot.support_card`` gives: staff copy never enters the customer catalogues, and an
    unescaped ``<`` in a ``parse_mode=HTML`` send is a 400 that loses the whole message. It is
    bounded against Telegram's ceiling the same way the outbound relay is, by
    :func:`_fit_to_one_message`, because a customer can type 4096 characters and the wrapper
    is not free.

    A refused send is logged and swallowed. The customer has already been acknowledged and the
    event is already on the timeline, so the panel shows the follow-up either way; telling the
    customer their sentence failed because our group is misselected is the one answer that
    would be wrong.
    """
    if bot is None or ticket.group_chat_id is None or ticket.group_message_id is None:
        return
    try:
        await bot.send_message(
            chat_id=ticket.group_chat_id,
            text=_fit_to_one_message(
                lambda words: _FOLLOW_UP_CARD_TEMPLATE.format(
                    ref=escape_html(ticket.public_ref), body=escape_html(words)
                ),
                body,
            ),
            reply_to_message_id=ticket.group_message_id,
        )
    except TelegramAPIError as exc:
        _LOG.warning(
            "a customer follow-up could not be posted under its card",
            extra={"ticket_id": str(ticket.id), "failure": repr(exc)},
        )


async def _reopen_by_answering(
    store: SupportTicketStore, ticket: TicketSnapshot, *, now: datetime
) -> None:
    """Move a ``waiting`` or ``resolved`` ticket back to ``in_progress``. Silent otherwise.

    The move is attributed to :meth:`~bayram.support.EventAuthor.customer` and not to
    ``system``: it happened because a person wrote something, and the timeline should say so.

    ``None`` from the move is the ordinary lost race — an operator dragged the card in the
    same instant — and is logged, not reported: the customer has already been acknowledged and
    the follow-up is already recorded, and there is nothing they could do about a status
    anyway.
    """
    to_status = reopen_target(ticket.status)
    if to_status is None:
        return
    moved = await store.move_status(
        ticket.id,
        expected=ticket.status,
        to_status=to_status,
        author=EventAuthor.customer(ticket.telegram_user_id),
        now=now,
    )
    if is_err(moved):
        _LOG.error(
            "a support ticket could not be reopened by a customer reply",
            extra=moved.error.to_log_dict(),
        )
        return
    if moved.value is None:
        _LOG.info(
            "the ticket had already moved when the customer's follow-up landed",
            extra={"ticket_id": str(ticket.id)},
        )


# ---------------------------------------------------------------------------
# The group card
# ---------------------------------------------------------------------------
async def support_group_target(directory: BotChatDirectory | None) -> SupportGroupTarget | None:
    """Where ticket cards go right now, or ``None`` when nothing should be posted.

    **One function and not a lookup at each door**, because there are two doors — this module's
    ``_handle_description`` and the worker's ``support_jobs._post_first_card`` — and all three
    of the reasons not to post have to be answered identically by both. ``None`` folds together
    a deployment with no directory wired, a directory that could not be read, and a deployment
    where nobody has selected a group yet, and the folding is the decision: not one of the three
    is a reason to fail a customer's complaint, and a door that told them apart would be a door
    with three branches that all do the same thing.

    **A read failure is a WARNING and not an error, and it is not retried here.** The ticket is
    already written and the customer is already answered by the time this is asked; the worst
    case is a card that has to be posted later by the panel's ``support:card_sync`` button,
    which is the same recovery an outright Telegram refusal gets.

    **It is asked EVERY TIME and the answer is never held.** See
    :meth:`~bayram.bot_chats.BotChatDirectory.selected_support_group`: the feature exists so an
    operator can move the inbox and watch it move, and a cache is precisely a window in which
    the tickets keep arriving in the room they just stopped using.
    """
    if directory is None:
        return None
    found = await directory.selected_support_group()
    if is_err(found):
        _LOG.warning(
            "the selected support group could not be read; no card will be posted",
            extra=found.error.to_log_dict(),
        )
        return None
    return found.value


async def post_card(
    bot: Bot | None,
    store: SupportTicketStore,
    settings: Settings,
    ticket: TicketSnapshot,
    *,
    target: SupportGroupTarget | None,
    now: datetime,
) -> None:
    """Put the ticket in front of staff, once, and never at the cost of the ticket.

    Returns quietly in three ordinary cases, each of which is a configuration or a replay
    rather than a fault: no group selected (``target is None``, which switches off ONLY this
    leg — the row is written, the customer is answered, the panel board is populated), a
    snapshot that already carries a card, and a lost race for the latch.

    **The target is a PARAMETER and not something this function looks up**, which is what lets
    the same sequence serve both doors: the bot resolves it from ``deps.bot_chats`` and the
    worker's card-sync job from its own container, and neither has to hold a session factory
    the other does not have. It is also what keeps the lookup honest about being per-call —
    a function that resolved the target itself would be one refactor away from remembering it.

    **``settings`` stays, and it is no longer the group.** The only thing read from it here is
    ``support_panel_base_url``, the deep link on the card's button. The group and its topic left
    the environment entirely (``SUPPORT_TICKETS_SPEC §3.8``); they are a ``bot_chats`` row an
    operator selected, and there is no fallback to a setting because there is no setting.

    **The order is send → claim → settle**, and the seam's docstring is honest about why the
    claim cannot come first: Telegram issues the ``message_id`` in the response to
    ``sendMessage``, so there is nothing to write before the call. What the latch still buys is
    that exactly one racing sender's id is recorded, which is what the relay needs — one card
    to listen to. The loser deletes the card it just sent, so the group does not accumulate
    duplicates; if that delete fails, the surplus card is inert (its buttons carry the same
    ticket id) and a staffer replying to it is answered by
    :data:`_RELAY_NO_TICKET` rather than silently ignored.

    Every failure path leaves the latch UNSET on purpose. An unposted ticket is visible on the
    board, retryable by the panel's ``support:card_sync`` job, and answerable by an operator;
    a ticket marked posted whose card never arrived is invisible to everybody.
    """
    if bot is None or target is None or ticket.is_posted:
        return
    sent = await _send_card(bot, settings, target, ticket)
    if sent is None:
        return
    claimed = await store.claim_group_post(
        ticket.id, group_chat_id=target.chat_id, group_message_id=sent
    )
    if is_err(claimed):
        _LOG.error("the support card claim failed", extra=claimed.error.to_log_dict())
        return
    if not claimed.value:
        await _undo_duplicate_card(bot, target.chat_id, sent, ticket)
        return
    settled = await store.settle_group_post(ticket.id, now=now)
    if is_err(settled):
        # The card is in the group and the id is recorded; only the clock is missing. That is
        # a row worth being able to SEE — a message id with no ``group_posted_at`` is a send
        # that crashed mid-flight — so it is logged and not repaired by guessing.
        _LOG.error("the support card clock was not stamped", extra=settled.error.to_log_dict())


async def _send_card(
    bot: Bot, settings: Settings, target: SupportGroupTarget, ticket: TicketSnapshot
) -> int | None:
    """One ``sendMessage`` into the support group. ``None`` when Telegram refused it.

    ``message_thread_id`` is ``None`` — which aiogram omits from the request entirely — unless
    a forum topic was chosen with the group, because Telegram rejects the parameter with ``0``
    on a group that is not a forum, and a rejected card is the failure this whole function is
    shaped to avoid. ``bot_chats.thread_id`` is nullable rather than defaulted to zero for
    exactly that reason, and :class:`~bayram.bot_chats.SupportGroupTarget` carries the chat and
    the topic as ONE value so the two cannot be read from different places and disagree — as
    two environment variables eventually would have, which is a card posted into a thread that
    does not exist in the group it was sent to.

    **Group sends deserve their own pacing budget, and they do not have one yet.** Telegram
    rate-limits a SINGLE chat at roughly twenty messages a minute — far tighter than the ~30/s
    across different chats that ``BAYRAM_BROADCAST_SEND_RATE_PER_S`` is sized against — and the
    shared ``SendPacer`` bucket (``bayram:send:budget``) meters the TOKEN, not the chat. A burst
    of tickets into one group can therefore earn a ``retry_after`` on the bot token, which
    stops customer ORDERS and not merely tickets. Pacing that on its own key belongs in the
    worker's send path (``bayram.runtime``), which owns the pacer; it is recorded here because
    this is the call site that will cause it.
    """
    order_ref = order_reference(ticket.order_id) if ticket.order_id is not None else None
    try:
        sent = await bot.send_message(
            chat_id=target.chat_id,
            text=render_card(ticket, order_ref=order_ref),
            reply_markup=card_keyboard(ticket, panel_base_url=settings.support_panel_base_url),
            message_thread_id=target.thread_id,
        )
    except TelegramAPIError as exc:
        _LOG.error(
            "the support card could not be posted; the ticket is unaffected",
            extra={
                "ticket_id": str(ticket.id),
                "public_ref": ticket.public_ref,
                "failure": repr(exc),
            },
        )
        return None
    return sent.message_id


async def _undo_duplicate_card(
    bot: Bot, chat_id: int, message_id: int, ticket: TicketSnapshot
) -> None:
    """Take back a card that lost the latch. Best effort, and a failure is not an error.

    The losing send is the one that must be withdrawn rather than the winner: the winner's id
    is what the relay resolves a staff reply through, so deleting it would leave the ticket
    listening on a message that no longer exists. A delete Telegram refuses (older than 48
    hours, or the bot lacks the right) leaves a second, inert card in the group, which is
    cosmetic — both cards carry the same ticket id in their buttons, and a reply to the wrong
    one is answered rather than lost.
    """
    try:
        await bot.delete_message(chat_id=chat_id, message_id=message_id)
    except TelegramAPIError as exc:
        _LOG.info(
            "a duplicate support card could not be withdrawn",
            extra={"ticket_id": str(ticket.id), "failure": repr(exc)},
        )


async def _rerender_card(callback: CallbackQuery, ticket: TicketSnapshot, *, base_url: str) -> None:
    """Redraw the card in place so it always reads as the ticket's current state.

    Edited rather than re-posted: the card is a row in a working queue, and appending a new one
    per state change would turn a scannable list of open tickets into a scroll of history the
    panel already keeps. Telegram refuses an edit that would change nothing, which is why this
    swallows ``TelegramAPIError`` — a redraw that was already correct is a success, not a
    failure worth telling a staffer about.
    """
    message = callback.message
    if not isinstance(message, Message):
        return
    order_ref = order_reference(ticket.order_id) if ticket.order_id is not None else None
    markup: InlineKeyboardMarkup = card_keyboard(ticket, panel_base_url=base_url)
    try:
        await message.edit_text(render_card(ticket, order_ref=order_ref), reply_markup=markup)
    except TelegramAPIError as exc:
        _LOG.info(
            "the support card could not be redrawn",
            extra={"ticket_id": str(ticket.id), "failure": repr(exc)},
        )


# ---------------------------------------------------------------------------
# The staff group
# ---------------------------------------------------------------------------
class InSupportGroup(Filter):
    """The router-level guard: this update is in a chat this feature is entitled to act in.

    **It answers a DICT rather than ``True``, and ``inbox_is_here`` is the whole point of it.**
    Two kinds of chat reach the handlers below: the room an operator has SELECTED, and a room
    that is not selected any more but still HOLDS CARDS. ``inbox_is_here`` tells them apart, and
    every handler that can speak to a customer branches on it. See :func:`_touches_a_card_in`
    for why the second kind is claimed at all; in one line, it is claimed because the
    alternative was an update that no router in the tree would take, which is a staffer's
    paragraph disappearing with no reply of any kind.

    **The line between the two rooms is "does this act reach the CUSTOMER".** A relay does, so
    :func:`handle_group_reply` refuses it outside the selected inbox and says where the inbox
    went — relaying out of a room the operator stopped using is the exact failure the picker
    exists to prevent, and is why this filter is uncached. A claim or a resolve does not: it is
    internal triage that any operator could do from the panel, so the buttons on an old card go
    on working and the toast carries the news. Keeping the old room's cards answerable is not
    an accident of this design, it is the requirement: ``support:card_sync`` keeps repainting
    them, so they LOOK live, and a card that looks live and does nothing is worse than no card.

    **It used to compare against a frozen ``Settings`` int and now it asks the database, per
    update.** That is the whole shape of the change: the support group is a ``bot_chats`` row
    chosen in the panel (``SUPPORT_TICKETS_SPEC §3.8``), not an environment variable, so the
    answer can change between one message and the next and a filter that had been handed an
    integer at build time would go on relaying staff conversation out of a room the operator
    stopped using. The boot-order argument the old docstring made still holds and still matters:
    ``handlers.build_router()`` takes no arguments, so the lookup has to happen at FILTER time
    against the ``deps`` it is handed — which is now also what makes it current.

    **DELIBERATELY UNCACHED, and this is the one place in the feature where a cache would be
    actively harmful rather than merely unnecessary.** The reason the group left the environment
    is that changing it required a redeploy; a five-minute TTL here would reintroduce a smaller
    version of exactly that — an operator repoints the inbox, the panel says it worked, and
    staff replies in the new room go unclaimed while replies in the old room are still being
    relayed to customers. The read is a single row off a partial unique index. See
    :meth:`~bayram.bot_chats.BotChatDirectory.selected_support_group`, which argues it from the
    seam's side.

    **A non-negative chat id short-circuits before any I/O**, and that is a fact rather than an
    optimisation dressed as one. A positive Telegram chat id is a PRIVATE chat — a person —
    and :class:`~bayram.contracts.BotChatType` has no ``private`` member precisely so that a
    person can never be a row in ``bot_chats``; a private chat therefore cannot be the selected
    support group in any state of the database. Without this line every customer message and
    every button press in the product would pay for a database round trip on its way past this
    router, because ``support_group`` sits above the customer routers. With it, the query is
    paid only by updates that arrive from a room.

    ``None`` from the lookup — nothing selected, nothing wired, or a read that failed —
    switches off the staff half entirely and switches off NOTHING else: the ticket is still
    written, the customer still confirmed, the board still populated. That asymmetry is
    ``support_contact``'s own rule (never point at a destination nobody reads) applied to a room
    instead of an address.

    The comparison is on CHAT IDS rather than on the chat type, so this can never fire in some
    OTHER group the bot was added to — which, now that the bot records every such group, is a
    larger set than it used to be. Relaying an internal triage conversation into the marketing
    group would be the failure; ids are what prevent it. The second id is not a second
    configured room: it is "a chat some ticket's ``group_chat_id`` column already names", which
    only a card this bot itself posted can put there.
    """

    async def __call__(self, event: TelegramObject, deps: BotDeps) -> bool | dict[str, bool]:
        if deps.support is None:
            return False
        chat = _chat_of(event)
        # See the docstring: a private chat cannot be a ``bot_chats`` row, so this is the
        # answer without asking, for every customer-facing update in the product.
        if chat is None or chat >= 0:
            return False
        target = await support_group_target(deps.bot_chats)
        if target is not None and target.chat_id == chat:
            return {"inbox_is_here": True}
        if await _touches_a_card_in(event, deps, chat):
            return {"inbox_is_here": False}
        return False


async def _touches_a_card_in(event: TelegramObject, deps: BotDeps, chat: int) -> bool:
    """Does this update act on a ticket card that LIVES in ``chat``? The room-holds-cards test.

    **This is the half of :class:`InSupportGroup` that makes moving the inbox survivable, and
    its absence was a silent-loss bug.** Eleven tickets have cards in group A; an operator
    selects group B. Every card in A instantly stopped being claimed by this router — while
    ``support:card_sync`` went on repainting those same cards, so the room looked alive. A
    triager replying to one of them matched nothing, no router below claimed it (the customer
    routers are nested under a private-chat filter), and the update was UNHANDLED: nothing was
    written, the customer heard nothing, and the staffer was told nothing at all — not even
    :data:`_NO_TICKET_MATCH`, the sentence this module was given for exactly that shape.

    **A chat that holds a card is a support chat FOR THAT UPDATE, and that is the narrowest
    widening that closes it.** The alternatives were both worse. "Claim every group chat" makes
    this router the catch-all for the marketing group and every other room the bot was ever
    added to, which is precisely the reasoning :class:`InSupportGroup` compares on a chat id
    rather than on a chat type. "Remember the previous selection" needs a history nothing keeps
    and answers wrongly the second time the inbox moves. Asking the card table is exact: the
    update is claimed if and only if it touches a row whose ``group_chat_id`` is this chat.

    **No new store method, and the lookup is the one :class:`ReplyToCard` already makes.**
    ``ticket_for_group_message`` is keyed on ``(chat, message)`` — which is exactly the
    question "does THIS chat hold this card" — so the message id is read from whichever part of
    the update points at a card: the message a reply answers, or the message a button was
    pressed on. That second one is why :func:`_carrier_of` must tolerate an
    ``InaccessibleMessage``: an old card's buttons are the commonest thing left in a room the
    inbox has moved out of.

    **The SELECTED room pays nothing for this.** The caller returns before reaching here
    whenever the chat is the current inbox, so the hot path keeps the single ``bot_chats``
    read it had. The cost falls on replies and button presses in OTHER negative chats, and it
    is one indexed lookup. The duplicate lookup :class:`ReplyToCard` then makes in the old room
    is accepted for the same reason: the alternative is threading a snapshot out of a root
    filter to save a query on the path nobody is supposed to be using any more.

    A read failure is ``False`` — this router declines and the update goes nowhere, which is
    what it did before this function existed. Claiming a room on a failed read would be the
    worse error: it would relay staff conversation out of a chat we could not prove holds
    anything.
    """
    store = deps.support
    if store is None:  # pragma: no cover - the caller checks this first
        return False
    message_id = _card_message_id_touched_by(event)
    if message_id is None:
        return False
    found = await store.ticket_for_group_message(group_chat_id=chat, group_message_id=message_id)
    if is_err(found):
        _LOG.error(
            "a card lookup for a chat that is not the inbox failed",
            extra=found.error.to_log_dict(),
        )
        return False
    return found.value is not None


def _card_message_id_touched_by(event: TelegramObject) -> int | None:
    """Which message in this chat the update points at, if it points at one at all.

    Two shapes and no third: a staffer REPLIES to a card, or PRESSES a button on one. Ordinary
    group chatter points at nothing and is answered ``None`` here, which is what keeps
    :func:`_touches_a_card_in` from spending a query on every "anyone around?" in every room
    the bot sits in.
    """
    if isinstance(event, CallbackQuery):
        carrier = _carrier_of(event)
        return carrier.message_id if carrier is not None else None
    if isinstance(event, Message):
        replied = event.reply_to_message
        return replied.message_id if replied is not None else None
    return None


def _carrier_of(event: TelegramObject) -> Message | InaccessibleMessage | None:
    """The message an update is attached to: what a callback was PRESSED on, or the message.

    **``InaccessibleMessage`` belongs in this union and leaving it out made every button on an
    older card inert.** aiogram models Telegram's "the message carrying this button is too old,
    or was deleted" as :class:`~aiogram.types.InaccessibleMessage`, which is a SIBLING of
    :class:`~aiogram.types.Message` and emphatically not a subclass of it — its MRO is
    ``MaybeInaccessibleMessage``, ``TelegramObject``. It still carries ``chat`` and
    ``message_id``, because those are the two things Telegram can always say about a message it
    will not hand back; only the BODY is gone.

    An ``isinstance(message, Message)`` test therefore answered ``False`` for a real press in
    the real support group, :class:`InSupportGroup` answered ``False`` with it, and the update
    fell out of this router — into nothing, because every customer router below is nested under
    a private-chat filter and the chat is a supergroup. Nothing answered the callback query, so
    the spinner turned until Telegram gave up and said "query is too old", and
    :func:`handle_unresolved_group_callback` — written precisely so an unanswered spinner can
    never happen in this room — sat inside the router the filter had just closed.

    **"The body is unavailable" and "this is not the support chat" are different facts and this
    function must only ever answer the second.** Editing an inaccessible message is genuinely
    impossible, so :func:`_rerender_card` keeps its own ``isinstance(..., Message)`` guard and
    degrades to "the move happened, the card was not redrawn". Do not unify the two checks: the
    guard that protects an edit and the test that decides a ROUTE are asking different
    questions, and collapsing them is how this bug happened in the first place.
    """
    message = event.message if isinstance(event, CallbackQuery) else event
    if isinstance(message, Message | InaccessibleMessage):
        return message
    return None


def _chat_of(event: TelegramObject) -> int | None:
    """The chat an update happened in, for the two observers this module registers on.

    Resolved through :func:`_carrier_of`, so an inaccessible message — which knows its chat
    perfectly well — is routed by the chat it is in rather than dropped. See that function:
    conflating the two was this router's highest-severity defect.
    """
    carrier = _carrier_of(event)
    return carrier.chat.id if carrier is not None else None


class ReplyToCard(Filter):
    """Is this group message a reply to one of our cards? If so, hand the handler its ticket.

    A filter for the same two reasons :class:`ListeningTicket` is one: the lookup is paid
    once, and the ticket travels into the handler. What it is NO LONGER for is keeping this
    router's hands off updates it cannot resolve — that job moved to
    :func:`handle_unresolved_group_message`, because falling through was the bug. See the
    module docstring: below this router sit the CUSTOMER routers, and an unresolved reply
    reaching ``onboarding``'s catch-all put the language screen and a phone-number keyboard
    into the staff room.

    **The lookup is keyed on the chat id AND the message id, because neither identifies a card
    on its own.** A Telegram message id is a counter within one chat, which is why the unique
    index is over ``(group_chat_id, group_message_id)`` and why there is deliberately no unique
    index on the message id alone — one on that column asserts a global uniqueness Telegram
    never promised and breaks the latch the first time the support group moves. Two tickets can
    therefore legally carry message id 5, so a match on the message id alone would resolve a
    stranger's reply in a second group to a ticket posted in the first one.

    **It no longer requires text, and that is deliberate.** A staffer answering a card with a
    sticker, a photo or a voice note used to make this answer ``False`` — indistinguishable
    from "not one of our cards" — and the update went down the tree. It resolves the ticket
    now and :func:`handle_group_reply` says plainly that only text can be relayed, which is
    both true and actionable; "not ours" was neither.
    """

    async def __call__(
        self, event: TelegramObject, deps: BotDeps
    ) -> dict[str, TicketSnapshot] | bool:
        if not isinstance(event, Message) or deps.support is None:
            return False
        replied_to = event.reply_to_message
        if replied_to is None:
            return False
        found = await deps.support.ticket_for_group_message(
            group_chat_id=event.chat.id, group_message_id=replied_to.message_id
        )
        if is_err(found):
            _LOG.error("a support card lookup failed", extra=found.error.to_log_dict())
            return False
        if found.value is None:
            return False
        return {"ticket": found.value}


async def handle_group_reply(
    message: Message, deps: BotDeps, ticket: TicketSnapshot, inbox_is_here: bool
) -> None:
    """A staffer answered. Record it, send it to the customer, then move the ticket along.

    **Unless this room is not the inbox any more, in which case NOTHING is recorded and nothing
    is sent.** ``inbox_is_here`` arrives from :class:`InSupportGroup`, and ``False`` means the
    card is here but the selection has moved on (or been cleared). The relay is the one act in
    this module that reaches the customer, and performing it out of a deselected room is
    exactly what an operator repointing the inbox asked us to stop doing — the reasoning
    :class:`InSupportGroup` refuses to cache its lookup for, applied to the messages already in
    flight rather than to the next one.

    **Refused and ANSWERED, never refused silently**, and the answer is checked first so that
    no side effect happens on the way to it. Writing the ``REPLY`` event anyway was considered
    and rejected twice over: it would put a paragraph on the timeline that the customer never
    received and that nothing will ever retry, and it would move a ``new`` ticket to
    ``in_progress`` on the strength of an answer that was not delivered — a ticket that looks
    worked and is not. The staffer keeps their text on their own screen and is told, in
    :data:`_INBOX_MOVED`, that the customer has not heard it and where the ticket now lives.

    ``inbox_is_here`` has no default on purpose. A caller that does not know which room it is
    in must fail loudly rather than relay by default: the default that reads as harmless is
    precisely "send it to the customer".

    **Recorded before it is sent, and stamped ``relayed_at`` only after it lands.** The event
    row says a reply was COMPOSED; the clock says it was DELIVERED. Writing both at once would
    make a reply that Telegram refused — a customer who has since blocked the bot is the common
    case — indistinguishable in the timeline from one the customer read, which is the single
    fact an operator picking up the ticket tomorrow most needs.

    **The customer is answered in the language the TICKET was opened in**, never in whatever
    the account is set to today. An account that switched language in between would otherwise
    receive the one message where being understood is the entire point in a language it no
    longer reads.

    **A reply out of ``new`` IS the claim.** Somebody who has typed an answer is working the
    ticket, and making them press ``✋`` afterwards to say so is a step that would simply not be
    taken, leaving a worked ticket sitting in the unlooked-at column. The move is conditional
    on the status still being ``new``, so a reply to a ticket somebody else has already claimed
    changes nothing and writes no event.

    An undeliverable relay is reported IN THE GROUP rather than only logged: the staffer has
    just written a paragraph believing it reached somebody, and a log line is not a way to tell
    them it did not. **Which report they get is decided by the failure and not by the most
    likely guess**: see :data:`_RELAY_FAILED` and :data:`_RELAY_REFUSED`.

    A reply with no text at all — a sticker, a photo, a voice note — is answered and nothing
    else: there is nothing to relay and nothing worth putting on the timeline, and the staffer
    is told plainly what will work instead of being ignored.
    """
    store = deps.support
    bot = message.bot
    if store is None or bot is None:  # pragma: no cover - the filter cannot match without both
        return
    if not inbox_is_here:
        _LOG.info(
            "a staff reply arrived in a room that is no longer the support inbox; not relayed",
            extra={"ticket_id": str(ticket.id), "chat_id": message.chat.id},
        )
        await message.reply(_INBOX_MOVED)
        return
    body = (message.text or "").strip()[:MAX_BODY_CHARS]
    if not body:
        await message.reply(_RELAY_NEEDS_TEXT)
        return
    author = EventAuthor.staff_group(_sender_id(message) or 0, display_name=_staff_name(message))
    now = deps.clock()
    recorded = await store.append_event(
        ticket.id, kind=SupportTicketEventKind.REPLY, author=author, now=now, body=body
    )
    if is_err(recorded):
        _LOG.error("a staff reply could not be recorded", extra=recorded.error.to_log_dict())
        await message.reply(_RELAY_NO_TICKET)
        return
    outcome = await _relay_to_customer(bot, ticket, body)
    if outcome.is_delivered:
        await store.mark_relayed(recorded.value, now=now)
        await _acknowledge(message)
        await _listen_on_the_relay(store, ticket, outcome.message_id, now=now)
    else:
        await message.reply(_RELAY_FAILED if outcome.is_block else _RELAY_REFUSED)
    await _claim_by_answering(store, deps, ticket, author=author, now=now)


def relay_text_for(ticket: RelayAddressee, body: str) -> str:
    """The relay, rendered and GUARANTEED to fit in one Telegram message.

    **The bound is computed against the FINISHED message and not against the raw body, which
    is the whole fix.** The old code cut the staffer's words at
    :data:`MAX_BODY_CHARS` — Telegram's own 4096 ceiling, and the right bound for the
    ``support_tickets.body`` COLUMN — and then wrapped them in a header, a ``<blockquote>`` and
    a closing line. Every one of those characters counts towards the same 4096, so a long
    answer produced a message Telegram refused with a 400: the customer got nothing,
    ``relayed_at`` stayed NULL, and the group was told the customer "may have blocked the bot",
    sending the staffer to investigate a block that did not exist.

    HTML escaping is the second reason the raw length cannot be the bound. ``translate``
    escapes every parameter, so one ``&`` the staffer types becomes five characters and one
    ``<`` becomes four; a body measured before escaping can be a fifth of its rendered size.
    :func:`_fit_to_one_message` therefore measures the RENDERED string and trims the raw body
    until it fits, which is correct whatever the template and the locale do.

    Exported because it is testable without a Bot and because the worker's operator-reply job
    (``bayram.runtime.support_jobs.relay_support_reply``) renders the same key and needs the
    same bound; see the report filed with this change.

    **And the parameter is :class:`~bayram.support.RelayAddressee` rather than
    :class:`~bayram.support.TicketSnapshot` so that the export is actually usable, which is the
    half that was missing.** The worker does not hold a snapshot: it reads the ticket through
    the panel's own ``get_ticket``, so what it has is a
    ``bayram.db.admin.views.SupportTicketListItem``, and for a while that type mismatch was the
    whole reason the worker went on bounding the RAW body and shipping the defect this function
    was written to remove. Only two fields are read here and both types carry them, so the seam
    is a two-member structural protocol that ``mypy --strict`` checks at each call site — not a
    widening to ``Any`` (which would make a rename of either field an ``AttributeError`` in the
    one job that answers an unhappy customer) and not a second copy of
    :func:`_fit_to_one_message` living in ``bayram.runtime``.
    """
    return _fit_to_one_message(
        lambda words: translate(_RELAY_KEY, ticket.language, ref=ticket.public_ref, body=words),
        body,
    )


def _fit_to_one_message(render: Callable[[str], str], body: str) -> str:
    """Render ``body`` through ``render`` and trim it until the RESULT fits one message.

    Trims the raw body and re-renders rather than truncating the rendered string, because the
    rendered string contains HTML: cutting it can land inside ``&amp;`` or between ``<b>`` and
    its close, and Telegram answers a malformed entity with the same 400 this exists to avoid.

    **A binary search on the raw length rather than "subtract the overflow and retry", and the
    difference is how much of the answer survives.** Escaping is not a constant cost per
    character: an ``&`` becomes five characters and a plain letter stays one, so an overflow
    measured in RENDERED characters says nothing about how many RAW ones to drop. Subtracting
    it directly is correct but wildly over-eager on escape-heavy text — a body of four thousand
    ampersands overflows by sixteen thousand and the first subtraction deletes the entire
    message, handing the customer a header with nothing under it. The search keeps the longest
    prefix that actually fits, at the cost of a dozen renders of a string we were about to
    send anyway.

    Monotone, which is what makes the search valid: the template and the escaper only ever ADD
    characters, so the rendered length is non-decreasing in the raw prefix length. Terminates
    in ``log2(len(body))`` steps.

    The empty-body render is the floor — a header with nothing under it, which is still a
    message the customer can act on — and is returned rather than raising even if it too is
    over the ceiling, because refusing to send is the failure mode this whole function exists
    to remove.
    """
    text = render(body)
    if len(text) <= MAX_MESSAGE_CHARS:
        return text
    shortest = render("")
    #: Invariant: ``low`` raw characters are known to fit and ``high`` is the largest count not
    #: yet ruled out. ``low`` starts at zero because ``shortest`` is the fallback answer.
    low, high = 0, len(body)
    while low < high:
        mid = (low + high + 1) // 2
        candidate = render(body[:mid].rstrip() + _RELAY_ELLIPSIS)
        if len(candidate) <= MAX_MESSAGE_CHARS:
            shortest, low = candidate, mid
        else:
            high = mid - 1
    return shortest


@dataclass(frozen=True, slots=True)
class _RelayOutcome:
    """What one relay attempt did, in the three facts the caller has to act on.

    A value rather than a bare ``bool`` because the caller now makes three decisions from one
    call — stamp ``relayed_at``, re-point ``prompt_message_id``, and choose WHICH failure to
    report — and a boolean can only answer the first. The third is the one that shipped wrong:
    every refusal was reported as a customer block.
    """

    #: The relay's own ``message_id``, so the ticket can start listening on it. ``None`` on a
    #: refusal: the customer never saw it, so nothing should point at it.
    message_id: int | None
    is_delivered: bool
    #: ``True`` only for ``Forbidden: bot was blocked by the user``. A 400 for length is not a
    #: block and must never be reported as one.
    is_block: bool


async def _relay_to_customer(bot: Bot, ticket: TicketSnapshot, body: str) -> _RelayOutcome:
    """Send the staffer's words to the customer's private chat.

    The ``message_id`` is what the ticket starts LISTENING on, so the
    "Reply here if there is more to say" the relay ends with resolves back to this ticket
    rather than falling into the wizard — see the module docstring. ``None`` accompanies a
    refusal and nothing is re-pointed, which leaves the ticket listening on whatever it heard
    last: the right answer, because the customer never saw the message that failed.

    The prefix is not decoration: an unannounced paragraph arriving in a bot chat reads as the
    bot talking, and the customer needs to know a person is answering — which is also why the
    ticket reference travels with it, so a follow-up can be tied to the same row.

    **The failure is classified HERE, where the exception is, and travels in the value.** A
    caller that re-derived it would need the exception, and an exception carried out of the
    ``except`` block to be re-inspected later is how a classification drifts from the thing it
    classifies. :func:`~bayram.bot.delivery.is_blocked_by_customer` is the one place that
    judgement lives in this codebase and it is imported rather than re-written: a
    ``Forbidden: bot was blocked by the user`` is a block, a deactivated account is not, and a
    400 about message length is emphatically not.
    """
    try:
        sent = await bot.send_message(
            chat_id=ticket.telegram_user_id, text=relay_text_for(ticket, body)
        )
    except TelegramAPIError as exc:
        blocked = is_blocked_by_customer(exc)
        _LOG.warning(
            "a staff reply could not be delivered to the customer",
            extra={
                "ticket_id": str(ticket.id),
                "failure": repr(exc),
                "is_blocked_by_customer": blocked,
            },
        )
        return _RelayOutcome(message_id=None, is_delivered=False, is_block=blocked)
    return _RelayOutcome(message_id=sent.message_id, is_delivered=True, is_block=False)


async def _listen_on_the_relay(
    store: SupportTicketStore, ticket: TicketSnapshot, message_id: int | None, *, now: datetime
) -> None:
    """Point the ticket at the relay the customer is now looking at. Logged, never reported.

    This single statement is what makes ``support.ticket.reply``'s closing sentence true. It
    must not be conditional on the column being empty (``attach_prompt`` is, on purpose), or
    the ticket would go on listening to the original ForceReply while the customer replies to
    the answer in front of them — and that reply would fall through this router into the
    wizard, which is exactly the failure this whole path exists to close.

    A failure here is logged and nothing else: the reply HAS reached the customer, which is
    what the staffer needs to know, and re-reporting a bookkeeping miss as a delivery problem
    would send them to look at the wrong thing.
    """
    if message_id is None:  # pragma: no cover - the caller only reaches here on success
        return
    listening = await store.listen_on(ticket.id, prompt_message_id=message_id, now=now)
    if is_err(listening):
        _LOG.error(
            "the ticket could not be pointed at its relay; a follow-up will not resolve",
            extra=listening.error.to_log_dict(),
        )


async def _acknowledge(message: Message) -> None:
    """Put :data:`_RELAY_ACK` on the staffer's message. Best effort; see the constant."""
    try:
        await message.react([ReactionTypeEmoji(emoji=_RELAY_ACK)])
    except TelegramAPIError as exc:
        _LOG.debug("the relay acknowledgement was refused", extra={"failure": repr(exc)})


async def _claim_by_answering(
    store: SupportTicketStore,
    deps: BotDeps,
    ticket: TicketSnapshot,
    *,
    author: EventAuthor,
    now: datetime,
) -> None:
    """Move a ``new`` ticket to ``in_progress`` because somebody answered it. Silent otherwise.

    Deliberately does NOT re-render the card. The card is attached to a message in this group
    and this handler holds the staffer's reply, not the card — editing it would need a second
    round trip to fetch it — and the status badge is refreshed the next time anybody presses a
    button on it. The panel is the surface that must be current, and it reads the row.
    """
    if ticket.status is not SupportTicketStatus.NEW:
        return
    moved = await store.move_status(
        ticket.id,
        expected=SupportTicketStatus.NEW,
        to_status=SupportTicketStatus.IN_PROGRESS,
        author=author,
        now=now,
    )
    if is_err(moved):
        _LOG.error(
            "a support ticket could not be claimed by a reply", extra=moved.error.to_log_dict()
        )
        return
    if moved.value is None:
        _LOG.info(
            "the ticket had already left `new` when the reply landed",
            extra={"ticket_id": str(ticket.id)},
        )


def _staff_name(message: Message) -> str:
    """How a staffer is recorded on the timeline: their ``@handle``, else their first name.

    Denormalised onto the event row on purpose — a staffer who renames must not rewrite what
    the timeline says they said — and bounded at :data:`MAX_STAFF_NAME_CHARS`, which is the
    column. The fallback chain ends in a non-empty literal because an empty string in a display
    column is a row that reads as though nobody said it.
    """
    user = message.from_user
    if user is None:
        return "someone"
    name = f"@{user.username}" if user.username else (user.full_name or "someone")
    return name[:MAX_STAFF_NAME_CHARS]


# ---------------------------------------------------------------------------
# The staff buttons
# ---------------------------------------------------------------------------
async def handle_claim(
    callback: CallbackQuery, callback_data: SupportCB, deps: BotDeps, inbox_is_here: bool
) -> None:
    """``✋ Claim``: put a name on the ticket, move it to ``in_progress``, redraw the card.

    Two writes, in that order, because they answer two questions and either may be wanted alone
    — the panel assigns without moving, and a reply moves without assigning. Doing the ASSIGN
    first means a ticket that is claimed but whose move lost a race still shows who has it,
    which is the more useful half; the reverse ordering would leave a ticket in progress with
    nobody's name on it.

    ``None`` from the move is the second press — two staffers reaching for the same card, which
    is the common case rather than the exotic one — and it is answered as an ordinary refusal
    in the callback's own toast, not as an error. ``LEGAL_STATUS_MOVES`` has no ``X -> X`` edge
    for exactly this: a second claim must be a refused move, not a second event on the timeline
    and a bumped ``updated_at`` that makes an untouched ticket look worked.
    """
    await _staff_move(
        callback,
        callback_data,
        deps,
        to_status=SupportTicketStatus.IN_PROGRESS,
        inbox_is_here=inbox_is_here,
    )


async def handle_resolve(
    callback: CallbackQuery, callback_data: SupportCB, deps: BotDeps, inbox_is_here: bool
) -> None:
    """``✅ Resolve``: close the ticket and redraw the card without a Resolve button on it.

    Terminal but reopenable — the panel can put it back to ``in_progress`` — and ``resolved_at``
    is not cleared by that reopen, because "this was answered once already" is the most useful
    thing to know about a complaint that came back.
    """
    await _staff_move(
        callback,
        callback_data,
        deps,
        to_status=SupportTicketStatus.RESOLVED,
        inbox_is_here=inbox_is_here,
    )


async def _staff_move(
    callback: CallbackQuery,
    callback_data: SupportCB,
    deps: BotDeps,
    *,
    to_status: SupportTicketStatus,
    inbox_is_here: bool,
) -> None:
    """The body both staff buttons share: resolve the id, assign if claiming, move, redraw.

    The ticket is RE-READ rather than trusted from the payload, because the payload carries an
    id and nothing else and the card may have been sitting in the group for a week. ``expected``
    is taken from that fresh read, so the conditional ``UPDATE``'s rowcount is a lock against
    the other staffer pressing at the same moment rather than against a status nobody holds.

    **A press in a room the inbox has moved out of still MOVES the ticket, and that is the
    deliberate asymmetry with :func:`handle_group_reply`.** The line is whether the act reaches
    the customer. A relay does, so it is refused there. Claiming and resolving do not: they are
    internal triage that the same person could do from the panel in the same second, and the
    cards in the old room are kept current by ``support:card_sync``, so refusing the press
    would leave a live-looking card whose buttons do nothing — the failure this whole change
    exists to remove, reintroduced one layer up. What changes is the ANSWER: the staffer is
    told, in an alert they cannot miss, that this room is no longer where tickets arrive.
    """
    store = deps.support
    ticket_id = read_reference(callback_data.ref)
    if store is None or ticket_id is None:
        await callback.answer(_RELAY_NO_TICKET, show_alert=True)
        return
    loaded = await store.load_ticket(ticket_id)
    if is_err(loaded) or loaded.value is None:
        await callback.answer(_RELAY_NO_TICKET, show_alert=True)
        return
    ticket = loaded.value
    author = EventAuthor.staff_group(_sender_id(callback) or 0, display_name=_staff_actor(callback))
    now = deps.clock()
    if to_status is SupportTicketStatus.IN_PROGRESS:
        assigned = await store.assign_ticket(
            ticket.id, admin_username=_staff_actor(callback), author=author, now=now
        )
        if is_ok(assigned) and assigned.value is not None:
            ticket = assigned.value
    moved = await store.move_status(
        ticket.id, expected=ticket.status, to_status=to_status, author=author, now=now
    )
    if is_err(moved):
        # An ``Err`` here is an ILLEGAL move, not a lost race — the seam keeps those apart on
        # purpose. It means this card drew a button it should not have, so it is logged as our
        # bug and the staffer is told plainly rather than shown a stack of nothing.
        _LOG.error("a staff status move was refused", extra=moved.error.to_log_dict())
        await callback.answer(_MOVE_REFUSED, show_alert=True)
        await _rerender_card(callback, ticket, base_url=deps.settings.support_panel_base_url)
        return
    if moved.value is None:
        await callback.answer(_MOVE_REFUSED, show_alert=True)
        await _rerender_card(callback, ticket, base_url=deps.settings.support_panel_base_url)
        return
    if inbox_is_here:
        await callback.answer()
    else:
        # The move HAPPENED — see the docstring. ``show_alert`` rather than a toast because a
        # toast is exactly what a staffer working a stale room will not notice, and the one
        # thing they must learn from this press is that new tickets no longer arrive here.
        await callback.answer(_INBOX_MOVED_TOAST, show_alert=True)
    await _rerender_card(callback, moved.value, base_url=deps.settings.support_panel_base_url)


def _staff_actor(callback: CallbackQuery) -> str:
    """The staffer behind a button press, bounded at the column. See :func:`_staff_name`."""
    user = callback.from_user
    name = f"@{user.username}" if user.username else (user.full_name or "someone")
    return name[:MAX_STAFF_NAME_CHARS]


# ---------------------------------------------------------------------------
# Everything else that happens in the support group
# ---------------------------------------------------------------------------
async def handle_unresolved_group_message(message: Message, inbox_is_here: bool) -> None:
    """Claim every remaining message in the support group, and answer the ones that meant us.

    **Its existence is structural and its silence is selective**, and the two halves must not
    be confused. Being REGISTERED is what stops an update from the support chat reaching the
    customer routers below: :class:`ReplyToCard` returning ``False`` used to mean "fall
    through", and what it fell through to was ``onboarding``'s catch-all, which claims every
    update from an account with no ``user_profiles`` row — which is every staffer, because a
    triager has never ordered a song from this bot. The visible result was the onboarding
    language screen and a phone-number keyboard posted into the staff room, while the staffer
    believed they had answered a customer and the customer heard nothing.

    **Being registered is not the same as speaking.** The support group is a room where people
    also talk to each other, and a bot that answered "I could not match that to a ticket" to
    every "anyone around?" would be unusable — staff would mute it, which costs the feature its
    only notification channel. So the handler speaks only when the staffer was plainly talking
    to US: the message is a reply to one of the BOT's own messages that :class:`ReplyToCard`
    could not resolve to a ticket. That is exactly the set of failures the reviewers found — a
    card whose ticket was erased by ``/forget``, a duplicate card whose delete Telegram
    refused, and the bot's own :data:`_RELAY_FAILED` warning, which is the most natural thing
    in the room for a triager to answer.

    **A COMMAND is the third thing that is plainly aimed at us, and it became one today.**
    ``commands`` and ``start`` used to sit outside the private-chat umbrella specifically so a
    staffer's ``/privacy`` or ``/forget`` typed in this room reached its handler. They no
    longer do — ``handlers.build_router`` argues why at length, and the short form is that
    ``/start`` in a group posted a ``request_contact`` keyboard in front of everybody in it. A
    data-subject request must not simply evaporate because of that fix, so a command typed here
    is answered with :data:`_COMMANDS_ARE_PRIVATE`: the request is redirected, never denied.
    Keying on the prefix rather than on a list of command names is deliberate — the answer is
    the same for every command, and a list here would be a second place to forget one.

    Do not "tidy" this into a blanket reply, and do not delete it for being a no-op: the
    return path is the load-bearing half, and it is only a no-op in the sense that claiming an
    update and saying nothing about it is the correct outcome for staff conversation.

    ``inbox_is_here`` is taken because :class:`InSupportGroup` supplies it to every handler in
    this router, and it is ``True`` on every path that reaches here in practice: an update from
    a room that only HOLDS cards arrives here only if it touched a card, and a card that was
    touched is claimed by :class:`ReplyToCard` above. It is branched on anyway, because
    "unreachable" is a property of two filters agreeing and the sentence to say when they do
    not is :data:`_INBOX_MOVED`, not "I could not match that to a ticket".
    """
    if (message.text or message.caption or "").startswith(COMMAND_PREFIX):
        _LOG.info("a command was typed in the support group; answered with the private-only rule")
        await message.reply(_COMMANDS_ARE_PRIVATE)
        return
    replied_to = message.reply_to_message
    if replied_to is None or replied_to.from_user is None or not replied_to.from_user.is_bot:
        _LOG.debug("a support-group message was claimed and left alone")
        return
    if not inbox_is_here:  # pragma: no cover - see the docstring; ``ReplyToCard`` claims these
        await message.reply(_INBOX_MOVED)
        return
    _LOG.info(
        "a reply in the support group resolved to no ticket",
        extra={"replied_to_message_id": replied_to.message_id},
    )
    await message.reply(_NO_TICKET_MATCH)


async def handle_unresolved_group_callback(callback: CallbackQuery, inbox_is_here: bool) -> None:
    """Claim, and always clear the spinner, for a button in the group that is not ours.

    Same structural reason as :func:`handle_unresolved_group_message` — an unclaimed callback
    from the support chat would reach ``onboarding.handle_blocked_callback`` and answer a
    staffer with the language screen — plus the one rule every callback handler in this
    codebase keeps: a callback query that is never answered leaves a loading spinner on the
    button for Telegram's own timeout, which reads as a frozen bot rather than as a refusal.
    Unlike the message half this ALWAYS speaks, because a press is unambiguously aimed at us.
    """
    _LOG.info(
        "an unrecognised button was pressed in the support group",
        extra={"data": callback.data, "inbox_is_here": inbox_is_here},
    )
    await callback.answer(
        _NO_TICKET_MATCH if inbox_is_here else _INBOX_MOVED_TOAST, show_alert=True
    )


# ---------------------------------------------------------------------------
# Routers
# ---------------------------------------------------------------------------
async def handle_open(
    callback: CallbackQuery, callback_data: SupportCB, state: FSMContext, deps: BotDeps
) -> None:
    """The ⚠️ button under a delivered song, carrying the order it is about.

    The id is read defensively (:func:`~bayram.bot.callbacks.read_reference`): a payload from an
    older build, or one that never had an order, opens an order-less ticket rather than
    refusing. A complaint filed against no particular song is still a complaint; refusing it to
    protect a foreign key would be the product deciding its own bookkeeping matters more than
    the customer's problem.
    """
    await callback.answer()
    await open_ticket(
        callback,
        state,
        deps,
        source=SupportTicketSource.DELIVERY_BUTTON,
        order_id=read_reference(callback_data.ref),
    )


def build_router() -> Router:
    """The CUSTOMER half. Registered between ``menu`` and ``navigation``.

    Below ``menu`` because a label on the persistent reply keyboard must beat everything that
    accepts free text, and above the step routers for the same reason from the other side: the
    note step and the lyric step accept ANY text, so a reply to the support prompt reaching one
    of them would be stored as the customer's answer and sung to a real person. That is the
    ``/help``-at-the-note-step failure ``common.COMMAND_PREFIX`` exists for, in a new shape.

    Its position relative to ``navigation`` is free — that router registers on
    ``callback_query`` only, and on ``NavCB``, which cannot collide with ``SupportCB`` — and it
    is placed above it so that this file's one message registration sits with the other message
    routers rather than beneath a callback-only one.

    **Only the CALLBACK observer stands down for ``Wizard.submitting``, and the asymmetry is
    argued rather than accidental.** The module docstring makes the case in full; in one line:
    the stand-down exists so that catch-alls cannot swallow the park ``submitting`` owns, the
    message registration here is not a catch-all — it is
    ":class:`ListeningTicket` says a ticket of this account's is listening on the message this
    is a reply to" — and with the filter in place a customer who typed ``/support`` during a
    render was prompted and then had their answer eaten by
    ``submitting.handle_message_while_working``. The callback registration keeps the filter
    because a ⚠️ tap that opens no ticket loses nothing the customer typed, and reversing that
    would change what a customer sees when they press a stale button mid-render.

    The private-chat filter on the message registration is kept even though
    ``handlers.build_router`` now nests this router under one. Two independent statements of
    "this is customer-facing and belongs in a private chat" is the right number for the
    registration that reads free text from an account: if the umbrella is ever restructured,
    this handler must not start claiming group messages on the way past.
    """
    router = Router(name="support")
    router.callback_query.filter(~StateFilter(Wizard.submitting))
    router.callback_query.register(handle_open, SupportCB.filter(F.action == SupportAction.OPEN))
    router.message.register(
        handle_customer_message, F.chat.type == ChatType.PRIVATE, ListeningTicket()
    )
    return router


def build_group_router() -> Router:
    """The STAFF half. Registered above ``onboarding``, and it has to be.

    ``onboarding``'s catch-all claims every message and every callback from an account with no
    ``user_profiles`` row — which is every staffer in the support group, because a triager has
    never ordered a song from this bot. Below it, a reply to a card would be answered with the
    phone-number screen, in the group, in Uzbek. So this router sits above it, and immediately
    below ``commands`` and ``start`` so that a staffer typing ``/privacy`` or ``/forget`` in the
    room still reaches the handler that answers it rather than having their message relayed to
    a customer.

    **Neither observer carries the ``Wizard.submitting`` stand-down the customer router's
    CALLBACK observer does**, and the omission is deliberate rather than forgotten. aiogram
    keys FSM state by
    ``(bot, chat, user)``, so a staffer's state in the GROUP chat is a different key from their
    own private wizard: a triager who happens to have a song rendering in their own chat with
    this bot is not in ``Wizard.submitting`` here, and a filter for it would be a line that
    reads as a guard while guarding nothing. What does the guarding is
    :class:`InSupportGroup`, which is stricter than any state filter — one chat id, read out of
    ``bot_chats`` on every update, and nothing at all when no group is selected.

    **Both observers END IN A CATCH-ALL, and that is the fix for this router's worst bug.**
    They used to end at ``ReplyToCard``/``SupportCB``, so anything in the room those two could
    not resolve "passed straight through" — and what it passed through to was the CUSTOMER
    routers, starting with ``onboarding``'s catch-all. A reply to an erased ticket's card, to a
    duplicate card whose delete was refused, to the bot's own :data:`_RELAY_FAILED` warning, or
    to a card answered with a sticker was therefore met with the onboarding language screen and
    a phone-number keyboard, posted into the staff group. Now ``InSupportGroup`` is a promise:
    the SELECTED chat id claims EVERY message and EVERY button in that room, and the two
    catch-alls decide whether to speak. :func:`handle_unresolved_group_message` deliberately
    says nothing to staff talking to each other; it answers only a reply to one of our own
    messages that resolved to no ticket.

    Do not re-order the registrations. The catch-alls must be last on each observer, because
    aiogram takes the first handler whose filters pass and a catch-all registered above
    ``ReplyToCard`` would answer "I could not match that to a ticket" to every relay in the
    room.

    **Every handler here takes ``inbox_is_here``, and it arrives from the ROOT filter.** aiogram
    merges a root filter's returned dict into the handler data before any handler is chosen
    (``Router._propagate_event`` calls ``check_root_filters`` and updates ``kwargs`` with what
    it answered), which is what lets :class:`InSupportGroup` claim two kinds of room in one
    registration and still let each handler behave differently in them. It is a required
    parameter everywhere rather than a defaulted one: the default that reads as harmless —
    "yes, this is the inbox" — is the one that relays a staff message out of a room an operator
    deliberately stopped using.
    """
    router = Router(name="support_group")
    router.message.filter(InSupportGroup())
    router.callback_query.filter(InSupportGroup())
    router.message.register(handle_group_reply, ReplyToCard())
    router.callback_query.register(handle_claim, SupportCB.filter(F.action == SupportAction.CLAIM))
    router.callback_query.register(
        handle_resolve, SupportCB.filter(F.action == SupportAction.RESOLVE)
    )
    router.message.register(handle_unresolved_group_message)
    router.callback_query.register(handle_unresolved_group_callback)
    return router
