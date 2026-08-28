"""What happens to everything nobody else claimed.

Registered last. Without it a stale button spins forever and a stray message vanishes into
silence, which is the same experience as a crashed bot even when nothing is wrong.
"""

from __future__ import annotations

from aiogram import Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from hbd.bot.handlers.common import say
from hbd.bot.i18n import translate
from hbd.bot.middleware import resolve_language
from hbd.logging import get_logger

__all__ = ["build_router"]

_LOG = get_logger(__name__)



async def handle_stale_callback(callback: CallbackQuery, state: FSMContext) -> None:
    """A button from a screen the wizard has already moved past."""
    language = await resolve_language(state)
    _LOG.info(
        "unmatched callback",
        extra={"data": callback.data, "state": await state.get_state()},
    )
    await callback.answer(translate("wizard.expired", language))


async def handle_stray_message(message: Message, state: FSMContext) -> None:
    """Text where a button was expected, or text with no session at all."""
    language = await resolve_language(state)
    current = await state.get_state()
    key = "wizard.use_buttons" if current is not None else "wizard.expired"
    _LOG.info("unmatched message", extra={"content_type": message.content_type, "state": current})
    await say(message, translate(key, language))


def build_router() -> Router:
    """Registered last: both handlers match everything left over."""
    router = Router(name="fallback")
    router.callback_query.register(handle_stale_callback)
    router.message.register(handle_stray_message)
    return router
