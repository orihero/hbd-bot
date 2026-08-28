"""The net under every handler.

An unhandled exception inside an aiogram handler is logged by the framework and then
nothing happens: the user's chat simply goes quiet, which reads as "the bot is dead". That
is the failure mode this middleware exists to remove.

Every update is processed inside a correlation scope, so the operator log for one tap is
one searchable id, and any exception that escapes a handler becomes a localised, friendly
message plus a full-context ERROR log. Nothing is swallowed: the log carries the update
type, the user, the state and the exception.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import BaseMiddleware
from aiogram.exceptions import TelegramAPIError
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message, TelegramObject

from hbd.bot.draft import load_draft
from hbd.bot.i18n import FALLBACK_LANGUAGE, translate
from hbd.contracts import Language, is_ok
from hbd.errors import GENERIC_USER_MESSAGE_KEY, HbdError
from hbd.logging import correlation_scope, current_correlation_id, get_logger

__all__ = ["ErrorGuardMiddleware", "resolve_language"]

_LOG = get_logger(__name__)

async def resolve_language(state: FSMContext | None) -> Language:
    """The user's interface language, or the fallback. Never raises."""
    if state is None:
        return FALLBACK_LANGUAGE
    try:
        data = await state.get_data()
    except Exception as exc:
        _LOG.warning("could not read FSM data for language", extra={"failure": repr(exc)})
        return FALLBACK_LANGUAGE
    result = load_draft(data)
    return result.value.ui_language if is_ok(result) else FALLBACK_LANGUAGE


class ErrorGuardMiddleware(BaseMiddleware):
    """Wraps every handler: correlation scope in, friendly failure out."""

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        with correlation_scope():
            try:
                return await handler(event, data)
            except Exception as exc:
                await self._report(event, data, exc)
                return None

    async def _report(self, event: TelegramObject, data: dict[str, Any], exc: Exception) -> None:
        state = data.get("state") if isinstance(data.get("state"), FSMContext) else None
        language = await resolve_language(state)
        key = exc.user_message_key if isinstance(exc, HbdError) else GENERIC_USER_MESSAGE_KEY
        _LOG.error(
            "handler failed",
            extra={
                "event_type": type(event).__name__,
                "correlation_id": current_correlation_id(),
                "user_id": _user_id(event),
                "user_message_key": key,
                "failure": repr(exc),
            },
            exc_info=exc,
        )
        await _tell_user(event, translate(key, language))


def _user_id(event: TelegramObject) -> int | None:
    user = getattr(event, "from_user", None)
    return getattr(user, "id", None)


async def _tell_user(event: TelegramObject, text: str) -> None:
    """Best effort. If even this fails, the log above is all we get — and that is fine."""
    try:
        if isinstance(event, CallbackQuery):
            await event.answer()
            if isinstance(event.message, Message):
                await event.message.answer(text)
            return
        if isinstance(event, Message):
            await event.answer(text)
    except TelegramAPIError as exc:
        _LOG.error("could not deliver the failure message", extra={"failure": repr(exc)})
