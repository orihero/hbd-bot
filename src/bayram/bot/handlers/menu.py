"""The persistent menu and the settings submenu behind ⚙️.

**Four buttons, and each one earns its slot on a keyboard the customer cannot dismiss.**
🎵 Make a song is the product. 🎫 My balance is the question a returning customer asks most
often and the one they used to have to know a command to ask. ⚙️ Settings is where the
interface language lives now that it is no longer the first screen of every wizard run. ❓ Help
is the thing a stuck person reaches for before they abandon a chat.

**``/forget`` is deliberately NOT one of them.** It erases a phone number, a name and a face,
and it cannot be undone. A pinned reply keyboard is one mis-tap away at all times — including
while a phone is in a pocket — and an irreversible operation may not live there. The privacy
screen names the command instead, which costs a customer who genuinely wants it one deliberate
act and costs everybody else nothing.

**``/privacy`` and ``/support`` sit one level down, inside Settings**, because they are read
once and not weekly, and because six buttons on a two-column reply keyboard truncate on a
360dp phone — the exact failure ``MAX_REPLY_ROW_LABEL_CHARS`` exists to keep out of the four
that remain.

**The settings screen carries NO FSM state, and that is the whole reason
``LanguageSlot`` needed a third member.** ⚙️ is reachable at any moment, including halfway
through a wizard run, so a screen that set its own state would overwrite the ``Wizard.*``
state a half-finished draft is parked in and lose the draft to somebody who only wanted to
change their language. It is therefore built the way ``handlers.navigation`` is built —
stateless callbacks dispatched purely on payload — and which picker a ``LanguageCB`` came from
is carried in ``LanguageSlot.SETTINGS`` rather than inferred from a state that is not there.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Final

from aiogram import F, Router
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from bayram.bot.callbacks import LanguageCB, LanguageSlot, NavAction, NavCB
from bayram.bot.deps import BotDeps
from bayram.bot.draft import UI_LANGUAGE_KEY
from bayram.bot.handlers.balance import handle_balance
from bayram.bot.handlers.common import (
    present,
    privacy_text,
    read_draft,
    reset_to_welcome,
    say,
    support_text,
    ui_language,
    write_draft,
)
from bayram.bot.i18n import SUPPORTED_LANGUAGES, translate
from bayram.bot.keyboards import MENU_BUTTON_KEYS, MENU_LABELS
from bayram.bot.screens import menu_screen, settings_language_screen, settings_screen
from bayram.bot.states import Wizard
from bayram.contracts import Err
from bayram.db.retention import DEFAULT_RETENTION_POLICY
from bayram.logging import get_logger

__all__ = ["build_router"]

_LOG = get_logger(__name__)

#: Label → catalogue key, over every supported language, computed once at import.
#:
#: A customer who changes language keeps the OLD keyboard pinned client-side until the next
#: message carries a new one, so a press can arrive in a language the account no longer reads.
#: Sixteen entries, and they must all be distinct — the locales package owns the test that
#: proves it, because a collision here would silently drop one button's dispatch and the
#: customer would press a button that does nothing at all.
#:
#: ``menu.prompt`` is absent on purpose: it is a MESSAGE BODY, not a button. Including it
#: would mean a customer who typed "Что делаем?" — or, far likelier, a note at the note step
#: that happened to equal a prompt in a locale they do not read — reached a dispatcher with no
#: button to dispatch to. The set is built from ``MENU_BUTTON_KEYS``, which is the same tuple
#: ``main_menu_keyboard`` draws from and ``MENU_LABELS`` is computed over, so the keyboard,
#: the router filter and this map cannot disagree about what the menu is.
_KEY_BY_LABEL: Final[Mapping[str, str]] = {
    translate(key, language): key for key in MENU_BUTTON_KEYS for language in SUPPORTED_LANGUAGES
}


async def handle_menu_label(message: Message, state: FSMContext, deps: BotDeps) -> None:
    """One of the four pinned buttons, pressed in any of the four languages.

    The dispatch is a map lookup rather than four ``F.text ==`` registrations because the
    labels are catalogue strings: four registrations would be sixteen filters, and a locale
    edit would silently unregister one of them.

    **Each arm delegates to the existing implementation rather than re-implementing it.** 🎵 is
    ``common.reset_to_welcome``, which is also what the ↩️ Start-over button and 🎂 Make another
    call; 🎫 is ``handlers.balance.handle_balance``, which ``/balance`` calls; ❓ renders the
    same ``help.text`` ``commands.handle_help`` renders. A button and a command that describe
    the same thing must not become two implementations of it — the rule ``common.support_text``
    was extracted to enforce.

    ``commands.handle_help`` itself is deliberately not called: its signature is
    ``(message, state)`` and it resolves the language through ``middleware.resolve_language``,
    whose last resort is the module constant. This handler holds ``deps`` and can fall back to
    the operator's configured default instead, which is the right answer on a deployment with
    no profile store. Rendering the same key is what keeps the two honest.
    """
    key = _KEY_BY_LABEL.get((message.text or "").strip())
    _LOG.info("a menu button was pressed", extra={"key": key})
    match key:
        case "menu.generate":
            await reset_to_welcome(message, state, deps)
        case "menu.balance":
            await handle_balance(message, state, deps)
        case "menu.help":
            await message.answer(translate("help.text", await ui_language(state, deps)))
        case "menu.settings":
            await present(message, settings_screen(await ui_language(state, deps)))
        case _:
            # Unreachable: the registration filter is ``F.text.in_(MENU_LABELS)`` and that set
            # is computed from the same ``MENU_BUTTON_KEYS`` this map is. Logged at ERROR
            # rather than ignored, because arriving here means the two have drifted and a
            # customer is pressing a button that does nothing.
            _LOG.error(
                "a menu label matched the filter but not the map",
                extra={"text": (message.text or "")[:64]},
            )


async def handle_set_language(callback: CallbackQuery, state: FSMContext, deps: BotDeps) -> None:
    """Open the language picker. Edits the settings screen in place; sets no state."""
    await callback.answer()
    await present(callback, settings_language_screen(await ui_language(state, deps)))


async def handle_show_privacy(callback: CallbackQuery, state: FSMContext, deps: BotDeps) -> None:
    """The retention notice, rendered by the same helper ``/privacy`` uses.

    Said as a NEW message rather than edited over the Settings screen, so the customer still
    has the Settings keyboard under it and can go straight on to the next thing — the same
    reason ``navigation.handle_report_problem`` gives for the identical choice.
    """
    await callback.answer()
    language = await ui_language(state, deps)
    await say(callback, privacy_text(language, DEFAULT_RETENTION_POLICY))


async def handle_show_support(callback: CallbackQuery, state: FSMContext, deps: BotDeps) -> None:
    """Where to write when something is wrong, from the same helper ``/support`` uses."""
    await callback.answer()
    language = await ui_language(state, deps)
    await say(callback, support_text(language, deps.settings.support_contact))


async def handle_to_settings(callback: CallbackQuery, state: FSMContext, deps: BotDeps) -> None:
    """Up one level, out of the language picker. The picker's only exit — see its screen."""
    await callback.answer()
    await present(callback, settings_screen(await ui_language(state, deps)))


async def handle_to_menu(callback: CallbackQuery, state: FSMContext, deps: BotDeps) -> None:
    """🏠 Back to menu, from Settings and from the two dead-end keyboards.

    This necessarily arrives as a NEW message and leaves the inline screen it was tapped from
    sitting on the roll above it. That is not a compromise: an inline screen cannot become a
    reply-keyboard screen by editing, because ``editMessageText`` accepts inline markup only.
    ``common._edit_or_send`` makes that decision once, from the markup type, so no caller has
    to remember it.
    """
    await callback.answer()
    await present(callback, menu_screen(await ui_language(state, deps)))


async def handle_settings_language_chosen(
    callback: CallbackQuery, callback_data: LanguageCB, state: FSMContext, deps: BotDeps
) -> None:
    """Change the interface language. Three writes, then the two screens that show it took.

    **The confirmation is the TOAST**, not a message. One tap then costs one edit and one send
    instead of three messages stacking up in the chat, and Telegram truncates a callback
    answer at 200 characters, which ``settings.language.saved`` is far inside.

    **The FSM cache is written ALWAYS, even with no store wired.** This is the whole of the
    fail-open answer: with ``deps.profiles is None`` the cache is the only thing that remembers
    the choice, it survives ``common.clear_keeping_identity``, and without this line a
    deployment with no persistence would be permanently ``uz_latn`` with a language picker that
    visibly did nothing.

    **The live draft is written too, when there is one.**
    ``middleware.resolve_language_or_none`` reads the DRAFT first, so if the two disagree the
    error guard, the gate's refusals, the fallback and every ``submitting`` message keep
    speaking the old language while the wizard screens speak the new one — one customer, two
    languages, in the same conversation.

    **An ``Err`` from ``record_language`` is logged and swallowed**, because the two writes
    above have already made the change real for this session and a failed persistence must not
    undo something the customer can see happening. That claim is only true because
    ``onboarding.load_identity``'s write-back is NON-CLOBBERING: it writes
    ``UI_LANGUAGE_KEY`` only when the key is absent. Without that guard, the next cold read —
    after ``bayram.runtime.jobs`` wipes the FSM dict on delivery, or after the fourteen-day TTL —
    would overwrite the customer's visible choice from the stale row with no signal anywhere.
    This is the swallowing site and the guard is two files away, so it is written down here.
    """
    language = callback_data.code
    await callback.answer(translate("settings.language.saved", language))
    await state.update_data({UI_LANGUAGE_KEY: language.value})
    draft = await read_draft(state)
    if draft is not None:
        await write_draft(state, draft.updated(ui_language=language))
    if deps.profiles is not None:
        recorded = await deps.profiles.record_language(callback.from_user.id, ui_language=language)
        if isinstance(recorded, Err):
            _LOG.error(
                "the interface language could not be persisted",
                extra=recorded.error.to_log_dict(),
            )
    # Edits the picker in place back into the Settings screen, now in the new language, so the
    # change lands on the screen the customer is looking at.
    await present(callback, settings_screen(language))
    # THE ONE AND ONLY PLACE THE REPLY KEYBOARD IS RE-SENT. ``is_persistent=True`` makes it
    # chat-level state that survives on its own, so a re-send is needed exactly where the
    # LABELS changed and nowhere else; every other flow end is served by the 🏠 row on
    # ``start_over_keyboard`` and ``post_delivery_keyboard``. Re-sending it "whenever a flow
    # ends" would put a duplicate keyboard message after every cancellation and delivery.
    await present(callback, menu_screen(language))


def build_router() -> Router:
    """Registered FOURTH. Both observers stand down for ``Wizard.submitting``.

    Fourth because a label on a keyboard the customer cannot dismiss must beat every free-text
    step: the note and the pasted lyric accept ANY text, so a 🎵 pressed at either would
    otherwise be stored as the answer and sung. It sits below ``onboarding`` because a customer
    who has not given us a number must not be able to start a wizard from a keyboard left
    pinned by an earlier session.

    The ``Wizard.submitting`` stand-down is the same one declarative filter
    ``handlers.onboarding.build_router`` explains, for the same reason: ``handlers.submitting``
    claims every update in that state and its claim is load-bearing for ``/forget``'s re-park.
    The accepted cost is that 🎫 pressed while a song is rendering answers ``wizard.queued``
    rather than the balance; ``/balance`` still works, because ``commands`` is above
    everything.
    """
    router = Router(name="menu")
    router.message.filter(~StateFilter(Wizard.submitting))
    router.callback_query.filter(~StateFilter(Wizard.submitting))
    router.message.register(handle_menu_label, F.text.in_(MENU_LABELS))
    router.callback_query.register(
        handle_set_language, NavCB.filter(F.action == NavAction.SET_LANGUAGE)
    )
    router.callback_query.register(
        handle_show_privacy, NavCB.filter(F.action == NavAction.SHOW_PRIVACY)
    )
    router.callback_query.register(
        handle_show_support, NavCB.filter(F.action == NavAction.SHOW_SUPPORT)
    )
    router.callback_query.register(
        handle_to_settings, NavCB.filter(F.action == NavAction.TO_SETTINGS)
    )
    router.callback_query.register(handle_to_menu, NavCB.filter(F.action == NavAction.TO_MENU))
    router.callback_query.register(
        handle_settings_language_chosen, LanguageCB.filter(F.slot == LanguageSlot.SETTINGS)
    )
    return router
