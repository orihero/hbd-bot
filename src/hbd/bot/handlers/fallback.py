"""What happens to everything nobody else claimed.

Registered last. Without it a stale button spins forever and a stray message vanishes into
silence, which is the same experience as a crashed bot even when nothing is wrong.

"Nobody claimed it" is three different situations, and telling a customer the wrong one is
how this module used to do damage:

* a button from a screen the wizard has moved past. The toast alone left the dead keyboard
  sitting there to be pressed again, so the message it came from is edited into the expired
  copy with a way forward on it, and the toast stays as the immediate cue;
* text where a button was expected. The session is alive; say which.
* text from someone with no session at all. This is almost always FIRST CONTACT — a person
  who typed "hello" before they found ``/start`` — and answering "that session expired" to
  a session that never existed is both untrue and a dead end. They get the welcome screen,
  which is what they were trying to reach.

Nothing here runs while a song is being made: ``handlers.submitting`` is registered
immediately before this router and claims both update kinds for ``Wizard.submitting``.
"""

from __future__ import annotations

from typing import Final

from aiogram import Router
from aiogram.exceptions import TelegramAPIError
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from hbd.bot.deps import BotDeps
from hbd.bot.handlers.common import reset_to_welcome, say
from hbd.bot.i18n import translate
from hbd.bot.keyboards import start_over_keyboard
from hbd.bot.middleware import resolve_language
from hbd.bot.screens import Screen
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
        await _retire(message, Screen(text=text, markup=start_over_keyboard(language)))


async def _retire(message: Message, screen: Screen) -> None:
    """Edit a dead screen into a live one. A refused edit is not worth failing over."""
    try:
        await message.edit_text(screen.text, reply_markup=screen.markup)
    except TelegramAPIError as exc:
        _LOG.info("could not retire the stale screen", extra={"failure": repr(exc)})


async def handle_stray_message(message: Message, state: FSMContext, deps: BotDeps) -> None:
    """Text where a button was expected, or text from someone with no session at all."""
    current = await state.get_state()
    _LOG.info("unmatched message", extra={"content_type": message.content_type, "state": current})
    if current is None:
        # No session to have expired. Almost always someone saying hello before they have
        # found /start, so give them the screen they were looking for rather than a
        # sentence about a session they never had.
        _LOG.info("first contact with no session; showing the welcome screen")
        await reset_to_welcome(message, state, deps)
        return
    await say(message, translate(_USE_BUTTONS_KEY, await resolve_language(state)))


def build_router() -> Router:
    """Registered last: both handlers match everything left over."""
    router = Router(name="fallback")
    router.callback_query.register(handle_stale_callback)
    router.message.register(handle_stray_message)
    return router
