"""What happens to everything nobody else claimed.

Registered last. Without it a stale button spins forever and a stray message vanishes into
silence, which is the same experience as a crashed bot even when nothing is wrong.

"Nobody claimed it" is three different situations, and telling a customer the wrong one is
how this module used to do damage:

* a button from a screen the wizard has moved past. The toast alone left the dead keyboard
  sitting there to be pressed again, so the message it came from is edited into the expired
  copy with a way forward on it, and the toast stays as the immediate cue;
* text where a button was expected. The session is alive; say which.
* text from someone with no session at all. This is NO LONGER first contact, and the change
  matters enough to be spelled out rather than left for a reader to infer: since the
  onboarding router landed, a customer who has not answered both onboarding questions is
  claimed by its catch-all three routers above this one, so nothing un-onboarded can reach
  here. What is left is somebody we already know, between flows, who typed something instead
  of tapping — and the honest answer to that is the menu.

Nothing here runs while a song is being made: ``handlers.submitting`` is registered
immediately before this router and claims both update kinds for ``Wizard.submitting``.
"""

from __future__ import annotations

from typing import Final

from aiogram import Router
from aiogram.exceptions import TelegramAPIError
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, Message

from hbd.bot.deps import BotDeps
from hbd.bot.handlers.common import present, say, ui_language
from hbd.bot.i18n import translate
from hbd.bot.keyboards import start_over_keyboard
from hbd.bot.middleware import resolve_language
from hbd.bot.screens import menu_screen
from hbd.logging import get_logger

__all__ = ["build_router"]

_LOG = get_logger(__name__)

_EXPIRED_KEY: Final[str] = "wizard.expired"
_USE_BUTTONS_KEY: Final[str] = "wizard.use_buttons"


async def handle_stale_callback(callback: CallbackQuery, state: FSMContext) -> None:
    """A button from a screen the wizard has already moved past.

    Both cues are wanted. The toast answers the press where the user is looking, and the
    edit retires the keyboard so the same dead button cannot be pressed a third time — and
    replaces it with one that works.

    ``start_over_keyboard`` now carries a 🏠 Back to menu row of its own beneath the
    Start-over button, so retiring a dead screen offers both the next song and the way home.
    That is what stops this from being one of the places a flow used to end with no exit at
    all: a customer who does not want another song had nothing to press, and "send /start" is
    not an answer a person reads on a screen that has just told them something went stale.
    """
    language = await resolve_language(state)
    _LOG.info(
        "unmatched callback",
        extra={"data": callback.data, "state": await state.get_state()},
    )
    text = translate(_EXPIRED_KEY, language)
    await callback.answer(text)
    message = callback.message
    if isinstance(message, Message):
        await _retire(message, text, start_over_keyboard(language))


async def _retire(message: Message, text: str, markup: InlineKeyboardMarkup) -> None:
    """Edit a dead screen into a live one. A refused edit is not worth failing over.

    It takes an :class:`~aiogram.types.InlineKeyboardMarkup` rather than a
    ``screens.Screen``, and that narrowing is deliberate rather than incidental. ``Screen.markup``
    widened to include ``ReplyKeyboardMarkup`` when the menu arrived, and Telegram's
    ``editMessageText`` accepts INLINE markup only — it answers 400 for anything else. This
    function edits and never falls back to sending (a dead screen that could not be retired is
    not worth a second message), so unlike ``common._edit_or_send`` it has nowhere to put a
    reply keyboard and must be unable to be handed one. The type is the guard.
    """
    try:
        await message.edit_text(text, reply_markup=markup)
    except TelegramAPIError as exc:
        _LOG.info("could not retire the stale screen", extra={"failure": repr(exc)})


async def handle_stray_message(message: Message, state: FSMContext, deps: BotDeps) -> None:
    """Text where a button was expected, or text from a known customer between flows.

    The two branches say different things because they ARE different things, and the module
    docstring above records what the second one stopped being when the onboarding router
    landed: it is no longer first contact and must no longer be answered with a wizard.
    """
    current = await state.get_state()
    _LOG.info("unmatched message", extra={"content_type": message.content_type, "state": current})
    if current is None:
        # No session to have expired — and, since the onboarding router landed, no possibility
        # that this is first contact: an un-onboarded customer is claimed by ``NotOnboarded``
        # three routers above this one. So this is somebody we already know, between flows,
        # who typed something instead of tapping. The menu is what they were reaching for; a
        # fresh wizard would put them four screens into a purchase they did not ask to start,
        # and would do it to somebody who may only have said "hello".
        _LOG.info("a known customer with no session; showing the menu")
        await present(message, menu_screen(await ui_language(state, deps)))
        return
    await say(message, translate(_USE_BUTTONS_KEY, await resolve_language(state)))


def build_router() -> Router:
    """Registered last: both handlers match everything left over."""
    router = Router(name="fallback")
    router.callback_query.register(handle_stale_callback)
    router.message.register(handle_stray_message)
    return router
