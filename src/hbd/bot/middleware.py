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

from hbd.bot.draft import UI_LANGUAGE_KEY, load_draft
from hbd.bot.i18n import FALLBACK_LANGUAGE, translate
from hbd.contracts import Language, is_ok
from hbd.errors import GENERIC_USER_MESSAGE_KEY, HbdError
from hbd.logging import correlation_scope, current_correlation_id, get_logger

__all__ = ["ErrorGuardMiddleware", "resolve_language", "resolve_language_or_none"]

_LOG = get_logger(__name__)


def _language_or_none(raw: object) -> Language | None:
    """A stored ``UI_LANGUAGE_KEY`` value, or ``None`` when it names no real language.

    Deliberately NOT :func:`~hbd.bot.i18n.parse_language`, which answers
    :data:`~hbd.bot.i18n.FALLBACK_LANGUAGE` for an unknown code. Borrowing it here would
    make :func:`resolve_language_or_none` structurally incapable of ever answering ``None``,
    which is the one thing it exists to do — and would re-introduce the exact clobber
    described there, this time hidden one call deeper.

    ``object`` rather than ``str | None`` because the value comes out of an FSM data dict
    that a previous release, a hand-edited Redis key or a future migration could have put
    anything into. Anything that is not a ``str`` naming a member is "nobody has chosen".
    """
    if not isinstance(raw, str):
        return None
    try:
        return Language(raw)
    except ValueError:
        _LOG.info("ignoring an unrecognised stored interface language", extra={"raw": raw})
        return None


async def resolve_language_or_none(state: FSMContext | None) -> Language | None:
    """The language the customer actually CHOSE, or ``None`` when nobody has asked yet.

    Two sources, in this order, and the order is the whole point. The draft is first because
    it is the live answer: a customer who changes the language in Settings mid-wizard has it
    written onto the draft in the same handler, and reading the cache first would leave the
    wizard screens and the error guard disagreeing. ``UI_LANGUAGE_KEY`` is second because it
    is what survives ``common.clear_keeping_identity`` — between flows there is no draft and
    the cache is the only thing that remembers a Russian speaker is a Russian speaker.

    ``None`` rather than :data:`~hbd.bot.i18n.FALLBACK_LANGUAGE` is the reason this function
    exists. ``gate.UserTouch`` carries the answer into ``users.ui_language``, and a fallback
    there is indistinguishable from a choice: within sixty seconds of any ``state.clear()``
    the drain used to stamp UZ_LATN over what the customer had actually picked. A caller that
    needs a concrete language derives one; a caller that is about to WRITE one must be able to
    tell "uz_latn" from "we never asked".

    Never raises. An unreadable FSM store is a reason to speak the fallback, never a reason to
    fail an update.
    """
    if state is None:
        return None
    try:
        data = await state.get_data()
    except Exception as exc:
        _LOG.warning("could not read FSM data for language", extra={"failure": repr(exc)})
        return None
    result = load_draft(data)
    if is_ok(result):
        return result.value.ui_language
    return _language_or_none(data.get(UI_LANGUAGE_KEY))


async def resolve_language(state: FSMContext | None) -> Language:
    """The user's interface language, or the fallback. Never raises.

    Kept under its own name and signature because seven callers hold no ``deps`` and want a
    language they can render with immediately — the error guard, the gate's refusal copy,
    ``start``, ``navigation``, ``fallback``, ``submitting`` and ``commands``. Behaviour is
    unchanged for all of them; the only new fact is that a customer who chose a language in
    Settings and has no draft in flight is now answered in it, because
    :func:`resolve_language_or_none` looks at the cache the draft used to be the only home
    for.
    """
    return await resolve_language_or_none(state) or FALLBACK_LANGUAGE


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
