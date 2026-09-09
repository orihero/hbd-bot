"""First contact: which language to speak, and the phone number. Two screens, one gate.

**Why this is a ROUTER and not a middleware.** A middleware can refuse an update with a
sentence; it cannot set an FSM state and it cannot render a screen. "Please tell me which
language to speak" is not a refusal, it is a screen — and the customer's answer has to land
in a state that the next update is dispatched by. The specification this replaces argued the
opposite from aiogram's FSM isolation lock, and that argument does not hold:
``FSMContextMiddleware`` is an OUTER middleware on the ``update`` observer, so it holds the
lock across the entire router tree and a filter here runs inside exactly the lock that was
cited as the reason to stay out of the handler layer. The real cost of being a router is
therefore stated instead of hidden: :class:`NotOnboarded` pays one ``profiles.get`` per update
whenever the FSM cache is cold, inside that lock. :data:`~hbd.bot.draft.ONBOARDED_KEY`
surviving ``common.clear_keeping_identity`` is what keeps that rare.

**Why it is registered THIRD**, and what each neighbour would do to it:

* **Above ``commands``** it would swallow ``/privacy`` and ``/forget``. That re-creates at the
  router layer precisely the denial ``gate.ERASURE_COMMANDS`` exists to prevent — a customer
  who has not finished onboarding could not exercise a data-subject request about the data
  onboarding is asking them for.
* **Above ``start``** it would make ``/start`` unreachable, and ``/start`` is the one command
  a person who is stuck will always try.
* **Below ``navigation``** a stale Back tapped during onboarding would reach
  ``navigation.handle_back``, whose ``step_for_state`` answers ``None`` for an ``Onboarding.*``
  state name and therefore calls ``expire`` — "your session expired", said to somebody in the
  middle of their first two questions, which then clears the FSM and drops them back to the
  language screen. That is why this router answers stale callbacks itself.
* **Below the step routers** the catch-all would stop being what blocks the wizard, which is
  its entire job.

**There is no ``/cancel`` handler here, and that is not an omission.**
``start.handle_cancel_command`` is registered with ``Command("cancel")`` and NO state filter
from the router immediately above this one, so it claims the update first: ``/cancel`` typed
mid-onboarding answers ``wizard.cancelled`` and the next tap is claimed by the catch-all,
which re-enters at the step the profile row says. A handler written here could never run. The
same is true of ``/help``, ``/balance``, ``/privacy``, ``/support`` and ``/forget``, all
claimed by ``commands`` at position one — which is the whole reason this router is not
registered above it.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

from aiogram import Bot, F, Router
from aiogram.filters import Filter, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message, TelegramObject

from hbd.bot.avatar import fetch_and_store_avatar
from hbd.bot.callbacks import LanguageCB, LanguageSlot
from hbd.bot.deps import BotDeps
from hbd.bot.draft import ONBOARDED_KEY, UI_LANGUAGE_KEY
from hbd.bot.handlers.common import (
    Event,
    clear_keeping_identity,
    error_text,
    present,
    say,
    ui_language,
)
from hbd.bot.i18n import translate
from hbd.bot.keyboards import contact_request_keyboard
from hbd.bot.middleware import resolve_language
from hbd.bot.screens import (
    Screen,
    menu_screen,
    onboarding_contact_screen,
    onboarding_language_screen,
)
from hbd.bot.states import Onboarding, Wizard
from hbd.contracts import Err, Language
from hbd.logging import get_logger
from hbd.user_profiles import normalise_phone

__all__ = ["build_router", "Identity", "NotOnboarded", "load_identity"]

_LOG = get_logger(__name__)

#: What is written into :data:`~hbd.bot.draft.ONBOARDED_KEY`, and the one direction of this
#: cache that cannot be corrected by waiting.
#:
#: It is written ONLY when a real profile row said so — never when the store was absent and
#: never when it returned an ``Err``. Both of those fail OPEN, and caching a fail-open answer
#: would turn a five-second database blip into a permanent mark: the customer would be treated
#: as onboarded for the fourteen-day life of their FSM data, the contact screen would never be
#: shown again, and there would be no phone number to fall back to when a delivery could not
#: reach them. A missing key costs one read; a wrongly written one costs a song.
ONBOARDED_VALUE: Final[bool] = True


@dataclass(frozen=True, slots=True)
class Identity:
    """What the routers need to know about a customer before anything else happens.

    Three flat fields rather than the :class:`~hbd.user_profiles.UserProfile` itself, and the
    difference is not cosmetic: the FSM cache can answer the first two with no row at all, so
    a type that required a profile would force :func:`load_identity` to invent one on the
    cheap path — and would put a phone number into the hands of two handlers and a ``/start``
    that have no business holding one.
    """

    #: ``False`` only when a profile row exists and its phone number is missing. An absent
    #: store, an ``Err`` from it and a cache hit ALL say ``True`` — see :func:`load_identity`
    #: for why that direction is the safe one.
    is_onboarded: bool
    #: Whether the language question has been answered. Meaningless when
    #: :attr:`is_onboarded` is true, because a customer cannot have reached the contact step
    #: without answering it.
    is_language_chosen: bool
    #: The persisted or cached interface language, or ``None`` when nobody has chosen one and
    #: the caller must fall back to ``deps.settings.default_ui_language``. ``None`` rather
    #: than a fallback for the reason ``middleware.resolve_language_or_none`` gives: a guess
    #: that is indistinguishable from a choice gets written down as one.
    ui_language: Language | None


def _language_from(data: dict[str, object]) -> Language | None:
    """The cached interface language in an FSM data dict, or ``None``.

    A private mirror of ``middleware._language_or_none`` over
    :data:`~hbd.bot.draft.UI_LANGUAGE_KEY` rather than a call into it, and the reason is that
    the middleware's version reads the DRAFT first. Here there is no draft to read — this runs
    before any wizard exists — and going through the public ``resolve_language_or_none`` would
    mean a second ``state.get_data()`` inside the FSM isolation lock for a dict this function
    is already holding.

    Anything that is not a string naming a real :class:`~hbd.contracts.Language` member is
    "nobody has chosen": the value comes out of a store a previous release, a hand-edited
    Redis key or a future migration could have put anything into.
    """
    raw = data.get(UI_LANGUAGE_KEY)
    if not isinstance(raw, str):
        return None
    try:
        return Language(raw)
    except ValueError:
        _LOG.info("ignoring an unrecognised cached interface language", extra={"raw": raw})
        return None


async def load_identity(state: FSMContext, deps: BotDeps, telegram_user_id: int | None) -> Identity:
    """Answer "do we already know this person?", cheaply, and write the answer down.

    **FAIL OPEN, deliberately and in three places**: no ``from_user`` on the update, no store
    on the container, and an ``Err`` from the store all mean *treat them as onboarded and let
    them through*. The posture is ``gate.InboundGateMiddleware``'s and the reason is the same
    — a database blip must not stop the bot selling songs — and it is safe here because this
    function only ever decides whether to SKIP work. It is never the sole enforcement of
    anything that costs money: the credit gate and the payment gate are, and both are below
    this router.

    **The cache write is why this is not a pure function.** Every update that gets past
    ``commands`` and ``start`` passes through the :class:`NotOnboarded` filter, so this is the
    one place in the tree that both pays for the read and sees every update — which makes it
    the only place that can repair :data:`~hbd.bot.draft.UI_LANGUAGE_KEY` after something
    outside this process wipes the FSM dict. ``hbd.runtime.jobs`` does exactly that when a
    song is delivered, so without the write-back a customer's very first message after their
    song arrived would come back in the fallback language.

    **The language write-back is NON-CLOBBERING**, and that guard is load-bearing two files
    away. ``handlers.menu.handle_settings_language_chosen`` swallows an ``Err`` from
    ``record_language`` on the grounds that the FSM cache has already made the change real for
    this session. That is only true if nothing overwrites the cache from the stale row — so
    :data:`~hbd.bot.draft.UI_LANGUAGE_KEY` is written only when the key is ABSENT, and the
    repair above is unaffected because the ``jobs`` wipe is exactly the case where it is.
    ``ONBOARDED_KEY`` is written unconditionally: a boolean derived from a row cannot
    contradict a session the way a language can.

    **THE WHOLE BODY IS INSIDE ``try/except Exception``, and that is not belt-and-braces.**
    This is called from a FILTER, and in aiogram 3.31.0 ``TelegramEventObserver.trigger`` runs
    ``handler.check(...)`` BEFORE wrapping the handler in its inner middlewares — so
    ``middleware.ErrorGuardMiddleware`` (registered inner in ``bot.app``) does not wrap it, and
    ``InboundGateMiddleware`` is outer and has already returned. A Redis blip inside
    ``state.get_data()`` would propagate out of the filter and the chat would simply go
    silent: exactly the failure the error guard exists to prevent, and the precise opposite of
    the fail-open posture the first paragraph promises. A filter is its own last line of
    defence. The work is a private function purely so that the ``try`` has one statement in
    it and cannot grow a step that quietly sits outside the guard.
    """
    try:
        return await _identify(state, deps, telegram_user_id)
    except Exception:
        _LOG.warning(
            "could not establish the customer's identity; failing open",
            extra={"telegram_user_id": telegram_user_id},
            exc_info=True,
        )
        return Identity(True, True, None)


async def _identify(state: FSMContext, deps: BotDeps, telegram_user_id: int | None) -> Identity:
    """The six branches :func:`load_identity` wraps. Free to raise; nothing else calls it.

    Ordered cheapest first, and the order is the cost model: the cache hit answers most
    updates with one Redis read, the two fail-open guards answer the rest without touching the
    database, and only a customer we have never confirmed reaches ``profiles.get``.
    """
    data = await state.get_data()
    if data.get(ONBOARDED_KEY) is True:
        # The cheap path, and the one almost every update takes. Onboarded implies the
        # language question was answered, so there is nothing left for the store to say.
        return Identity(True, True, _language_from(data))
    if telegram_user_id is None or deps.profiles is None:
        _LOG.debug(
            "no way to identify the customer; treating them as onboarded",
            extra={
                "has_user": telegram_user_id is not None,
                "has_store": deps.profiles is not None,
            },
        )
        return Identity(True, True, _language_from(data))
    result = await deps.profiles.get(telegram_user_id)
    if isinstance(result, Err):
        # NO CACHE WRITE on this branch. See ``ONBOARDED_VALUE``: caching a fail-open answer
        # turns a five-second outage into a permanent state.
        _LOG.warning(
            "the profile store could not be read; treating the customer as onboarded",
            extra=result.error.to_log_dict(),
        )
        return Identity(True, True, _language_from(data))
    profile = result.value
    if profile is None:
        # Somebody we have never met, or somebody who has used /forget. The two are
        # indistinguishable by design (PD-3) and both mean "ask both questions". The FSM may
        # still hold a language if they picked one in Settings during a session that never
        # finished, so it is read rather than assumed absent.
        return Identity(False, False, _language_from(data))
    cache: dict[str, object] = {}
    if UI_LANGUAGE_KEY not in data:
        cache[UI_LANGUAGE_KEY] = profile.ui_language.value
    if profile.is_onboarded:
        cache[ONBOARDED_KEY] = ONBOARDED_VALUE
    if cache:
        # One write, not two, and skipped entirely when there is nothing to say: every
        # ``update_data`` is a round trip to Redis inside the FSM isolation lock.
        await state.update_data(cache)
    return Identity(profile.is_onboarded, True, profile.ui_language)


class NotOnboarded(Filter):
    """The catch-all's guard, and the thing that actually blocks the wizard.

    It returns a DICT rather than ``True``, because aiogram merges a filter's dict result into
    the handler's keyword arguments. That is the difference between one database round trip
    per cold update and two: the handler learns which step to enter — the language question or
    the contact question — without a second ``profiles.get`` and without a second
    ``state.get_data()`` inside the FSM isolation lock. Making a filter do work is unusual and
    is done here deliberately, because this filter is the one place in the tree that already
    pays for the read AND sees every update.

    ``state`` and ``deps`` are injected by NAME out of the handler data, exactly as they are
    into a handler; aiogram passes the same kwargs to a filter's ``__call__``.
    """

    async def __call__(
        self, event: TelegramObject, state: FSMContext, deps: BotDeps
    ) -> dict[str, Identity] | bool:
        user = getattr(event, "from_user", None)
        identity = await load_identity(state, deps, getattr(user, "id", None))
        if identity.is_onboarded:
            return False
        return {"identity": identity}


async def handle_language_chosen(
    callback: CallbackQuery, callback_data: LanguageCB, state: FSMContext, deps: BotDeps
) -> None:
    """The first answer a customer ever gives. Cache it, persist it, ask for the number.

    **The cache is written FIRST, before any store call**, so that a failed row write still
    leaves the interface speaking the language they just picked. The alternative — persist,
    then cache only on success — answers a customer in Uzbek half a second after they tapped
    "Русский", which is the single worst first impression this product can make.

    **An ``Err`` from ``record_language`` is logged and the flow CONTINUES.** The FSM state
    drives the rest of this session and the contact handlers claim every update in
    ``Onboarding.contact``, so a failed row write costs a repeated language question on the
    NEXT session and never a loop inside this one. Refusing to advance would trap the customer
    on a screen whose only button is the one that just failed.
    """
    language = callback_data.code
    await callback.answer()
    await state.update_data({UI_LANGUAGE_KEY: language.value})
    user = callback.from_user
    if deps.profiles is not None:
        recorded = await deps.profiles.record_language(user.id, ui_language=language)
        if isinstance(recorded, Err):
            _LOG.error(
                "the chosen interface language could not be persisted",
                extra=recorded.error.to_log_dict(),
            )
    await state.set_state(Onboarding.contact)
    # ``settings.language.saved`` and not an onboarding-only twin of it: "✅ Language saved."
    # is exactly what happened, and inventing a second sentence for one event is how two
    # catalogues start disagreeing about the same thing. Markup ``None``, so ``_edit_or_send``
    # EDITS the language screen in place and the four dead language buttons go with it.
    await present(callback, Screen(text=translate("settings.language.saved", language)))
    # A new message, necessarily: this screen carries a ``ReplyKeyboardMarkup`` and Telegram's
    # ``editMessageText`` accepts inline markup only. ``common._edit_or_send`` knows that and
    # sends; the contact button cannot arrive any other way.
    await present(callback, onboarding_contact_screen(language))


async def _reprompt_language(event: Event, state: FSMContext) -> None:
    """Re-render the language question. The only honest answer to a stale tap during it.

    A Back button from a screen the customer left behind, or an occasion button from a draft
    that predates this table, must not fall through to ``navigation``: ``handle_back``'s
    ``step_for_state`` answers ``None`` for an ``Onboarding.*`` state name and calls
    ``expire``, which tells somebody mid-onboarding that their session expired and then clears
    the FSM. Re-drawing the question they are being asked says something true instead, and
    ``common._edit_or_send`` already survives Telegram's "message is not modified" by sending
    a new message.
    """
    await present(event, onboarding_language_screen(await resolve_language(state)))


async def handle_language_reprompt_message(message: Message, state: FSMContext) -> None:
    """Typed text at the language step. There is nothing to type; the buttons are the answer."""
    _LOG.info("text at the language step", extra={"content_type": message.content_type})
    await _reprompt_language(message, state)


async def handle_language_reprompt_callback(callback: CallbackQuery, state: FSMContext) -> None:
    """A button that is not one of the four languages, pressed at the language step.

    The ``callback.answer()`` is not optional and is not politeness: without it the client
    spins its loading indicator until Telegram times the query out, which reads as a hung bot
    on the very first screen.
    """
    await callback.answer()
    _LOG.info("an unmatched button at the language step", extra={"data": callback.data})
    await _reprompt_language(callback, state)


async def _ask_for_contact(event: Event, language: Language, key: str) -> None:
    """Say one sentence with the 📱 button under it, from either update kind.

    Every refusal on the contact step goes through here — the foreign card, the unusable
    number, the typed answer, the stale button — because all four have the same remedy and a
    screen whose sentence changed but whose button did not would read as four different
    problems. It is a ``Screen`` rather than four ``answer`` calls so that
    ``common._edit_or_send``'s "a reply keyboard is sent, never edited" rule is applied in one
    place instead of being remembered in four.
    """
    await present(event, Screen(translate(key, language), contact_request_keyboard(language)))


async def handle_contact_shared(
    message: Message, state: FSMContext, deps: BotDeps, bot: Bot
) -> None:
    """The shared contact card: verify it is theirs, store it, end onboarding, fetch the face.

    **The foreign-card check is the security control on this screen.** Telegram lets anyone
    forward any card out of their address book, so without comparing ``contact.user_id``
    against ``from_user.id`` the bot would store a STRANGER's number under this account — and
    every later erasure, notification and delivery fallback would then be aimed at somebody who
    never asked for any of it, using a number they never gave us.

    **An ``Err`` from ``record_contact`` is the one store failure in this module that must not
    advance.** The row is what the next session reads, so answering "thank you, saved" over a
    failed write promises a delivery fallback that does not exist and guarantees the customer
    is asked for the same number again with no explanation. The state stays at
    ``Onboarding.contact`` and the customer sees the error and the button.

    The avatar fetch is LAST, after the customer already has their menu, so nothing about it
    is on their critical path — see :func:`~hbd.bot.avatar.fetch_and_store_avatar`.
    """
    language = await ui_language(state, deps)
    contact = message.contact
    user = message.from_user
    if contact is None:
        # Unreachable through the registration below, which filters on ``F.contact``. Guarded
        # rather than asserted because an assertion in a handler is an update that dies.
        await _ask_for_contact(message, language, "onboarding.contact.required")
        return
    if user is None or contact.user_id is None or contact.user_id != user.id:
        # Nothing is persisted and no state changes: a card that is not theirs leaves the
        # account exactly as it was, still on the contact step, still being asked.
        _LOG.info(
            "a contact card belonging to somebody else was shared; refusing it",
            extra={"is_attributed": contact.user_id is not None},
        )
        await _ask_for_contact(message, language, "onboarding.contact.foreign")
        return
    phone = normalise_phone(contact.phone_number)
    if phone is None:
        _LOG.info("the shared number is not in a shape we can store")
        await _ask_for_contact(message, language, "onboarding.contact.required")
        return
    if deps.profiles is None:
        # Nearly unreachable: with no store, ``NotOnboarded`` fails open and never routes
        # anybody to this state in the first place. Written anyway so that "unwired" is a
        # logged fact and never a crash, and so a customer who reached here through an old
        # parked state is not stranded on a screen that cannot answer them.
        _LOG.warning("no profile store is wired; the shared number is not being stored")
    else:
        # The identity fields come off ``from_user`` and NOT off ``Contact``: the card carries
        # no username at all, and its first and last names are whatever the sharer typed into
        # their own address book. ``from_user`` is the account this bot will be talking to.
        stored = await deps.profiles.record_contact(
            user.id,
            phone_e164=phone,
            telegram_username=user.username,
            first_name=user.first_name,
            last_name=user.last_name,
        )
        if isinstance(stored, Err):
            _LOG.error("the shared contact could not be stored", extra=stored.error.to_log_dict())
            await message.answer(
                error_text(stored.error, language),
                reply_markup=contact_request_keyboard(language),
            )
            return
    # This is what ends onboarding: ``clear_keeping_identity`` sets the state to ``None`` as
    # well as emptying the session, and the two caches are written back immediately so the
    # next update takes the cheap path in ``load_identity`` rather than a store read.
    await clear_keeping_identity(state)
    await state.update_data({ONBOARDED_KEY: ONBOARDED_VALUE, UI_LANGUAGE_KEY: language.value})
    await say(message, translate("onboarding.contact.saved", language))
    # The reply keyboard arrives attached to the screen that EXPLAINS it rather than to the
    # receipt above, and that same message is what replaces the pinned 📱 contact button.
    # ``is_first_time`` draws the welcome paragraph, here and nowhere else.
    await present(message, menu_screen(language, is_first_time=True))
    await fetch_and_store_avatar(bot, telegram_user_id=user.id, profiles=deps.profiles)


async def handle_contact_missing(message: Message, state: FSMContext, deps: BotDeps) -> None:
    """Anything at the contact step that is not a contact: typed text, a sticker, a photo.

    This is the answer to "what if they type the number instead of pressing the button". The
    button is the only route, because it is the only one Telegram lets us verify against
    ``from_user.id`` — a typed number is unattributable, and an unattributable number is
    exactly the stranger's-card failure :func:`handle_contact_shared` refuses.

    It matches a ``/halp`` too. The six real commands are claimed by ``commands`` and
    ``start`` above this router; a misspelled one lands here and is answered with the question
    the customer is actually being asked, rather than vanishing into the fallback's "that
    session expired".
    """
    _LOG.info("no contact at the contact step", extra={"content_type": message.content_type})
    await _ask_for_contact(message, await ui_language(state, deps), "onboarding.contact.required")


async def handle_contact_missing_callback(
    callback: CallbackQuery, state: FSMContext, deps: BotDeps
) -> None:
    """A stale inline button pressed during the contact step.

    It exists so that a Back tapped on a screen the customer has scrolled past does not reach
    ``navigation.handle_back`` and get answered "your session expired" — which would also
    clear the FSM and lose the language they had just chosen.
    """
    await callback.answer()
    _LOG.info("an unmatched button at the contact step", extra={"data": callback.data})
    await _ask_for_contact(callback, await ui_language(state, deps), "onboarding.contact.required")


async def _resume_onboarding(
    event: Event, state: FSMContext, deps: BotDeps, identity: Identity
) -> None:
    """Put the customer back on the step their profile row says they are on.

    ``set_state`` and NOT a clear. A half-finished draft belonging to a customer whose profile
    was erased mid-wizard is left exactly where it is: the wizard is unreachable until they
    finish onboarding, and whether to re-enter it afterwards is not this handler's decision to
    make — throwing the draft away here would be an irreversible choice made on behalf of
    somebody who never asked for it.
    """
    language = identity.ui_language or deps.settings.default_ui_language
    if not identity.is_language_chosen:
        await state.set_state(Onboarding.language)
        await present(event, onboarding_language_screen(language))
        return
    await state.set_state(Onboarding.contact)
    await present(event, onboarding_contact_screen(language))


async def handle_blocked_message(
    message: Message, state: FSMContext, deps: BotDeps, identity: Identity
) -> None:
    """Any message from a customer who has not finished onboarding.

    ``identity`` arrives as a keyword argument merged in by :class:`NotOnboarded`, so this
    handler costs neither a store read nor an FSM read of its own.
    """
    _LOG.info(
        "an update from a customer who has not finished onboarding",
        extra={"is_language_chosen": identity.is_language_chosen},
    )
    await _resume_onboarding(message, state, deps, identity)


async def handle_blocked_callback(
    callback: CallbackQuery, state: FSMContext, deps: BotDeps, identity: Identity
) -> None:
    """The same, for a button — answered first so the client's spinner stops."""
    await callback.answer()
    _LOG.info(
        "a button from a customer who has not finished onboarding",
        extra={"is_language_chosen": identity.is_language_chosen},
    )
    await _resume_onboarding(callback, state, deps, identity)


def build_router() -> Router:
    """Registered THIRD. Both observers stand down for ``Wizard.submitting``.

    That stand-down is ONE declarative filter rather than a guard in each of the eight
    handlers below, because ``handlers.submitting`` claims every message and every callback in
    that state and its claim is load-bearing: ``commands.handle_forget`` re-parks a running
    order there on purpose, and a catch-all that swallowed the park would blind
    ``submitting.order_in_flight`` — after which the next ``/cancel`` answers "Cancelled —
    nothing was made, and nothing was kept" about a song that then arrives in the chat.

    Moving ``submitting`` above this router instead was considered and rejected: it would put
    it above ``navigation``, which owns Cancel, and change who answers that button. One filter
    here is cheaper than a re-ordering with a behaviour change hidden inside it.

    The accepted cost, stated out loud: 🎫 pressed while a song is rendering answers
    ``wizard.queued`` instead of the balance. ``/balance`` still works, because ``commands``
    is above everything.
    """
    router = Router(name="onboarding")
    router.message.filter(~StateFilter(Wizard.submitting))
    router.callback_query.filter(~StateFilter(Wizard.submitting))
    router.callback_query.register(
        handle_language_chosen,
        Onboarding.language,
        LanguageCB.filter(F.slot == LanguageSlot.UI),
    )
    router.callback_query.register(handle_language_reprompt_callback, Onboarding.language)
    router.message.register(handle_language_reprompt_message, Onboarding.language)
    router.message.register(handle_contact_shared, Onboarding.contact, F.contact)
    router.message.register(handle_contact_missing, Onboarding.contact)
    router.callback_query.register(handle_contact_missing_callback, Onboarding.contact)
    router.message.register(handle_blocked_message, NotOnboarded())
    router.callback_query.register(handle_blocked_callback, NotOnboarded())
    return router
