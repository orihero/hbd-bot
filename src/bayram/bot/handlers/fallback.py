"""What happens to everything nobody else claimed.

Registered last. Without it a stale button spins forever and a stray message vanishes into
silence, which is the same experience as a crashed bot even when nothing is wrong.

"Nobody claimed it" is three different situations, and telling a customer the wrong one is
how this module used to do damage:

* a button from a screen the wizard has moved past. The toast alone left the dead keyboard
  sitting there to be pressed again, so the message it came from is retired (deleted, or
  stripped of its keyboard) and the toast is the cue;
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
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from bayram.bot.cleanup import retire_message
from bayram.bot.deps import BotDeps
from bayram.bot.handlers.common import present, say, ui_language
from bayram.bot.i18n import translate
from bayram.bot.middleware import resolve_language
from bayram.bot.screens import menu_screen
from bayram.logging import get_logger

__all__ = ["build_router"]

_LOG = get_logger(__name__)

_EXPIRED_KEY: Final[str] = "wizard.expired"
_USE_BUTTONS_KEY: Final[str] = "wizard.use_buttons"


async def handle_stale_callback(callback: CallbackQuery, state: FSMContext) -> None:
    """A button from a screen the wizard has already moved past.

    The toast answers the press where the user is looking, and the dead screen is then
    RETIRED — deleted, or stripped of its keyboard once it is too old to delete — so the
    same dead button cannot be pressed a third time. It used to be edited into an "expired"
    screen with a Start-over keyboard, which was one more message with live buttons left on
    the chat for good; the persistent menu is the way on, and it is already there.
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
        # Media-guarded: a stale button on the delivered song leaves the song alone.
        await retire_message(message)


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
        await present(
            message,
            menu_screen(
                await ui_language(state, deps),
                teachers_day_enabled=await deps.is_teachers_day_enabled(),
            ),
        )
        return
    await say(message, translate(_USE_BUTTONS_KEY, await resolve_language(state)))


def build_router() -> Router:
    """Registered last: both handlers match everything left over."""
    router = Router(name="fallback")
    router.callback_query.register(handle_stale_callback)
    router.message.register(handle_stray_message)
    return router
