"""Keeping the chat clean: the bot's own screens are retired once they have been acted on.

The owner's rule, verbatim in spirit: once the customer has answered a screen, the message
that asked — and every button on it — must be edited into the next screen or deleted. What
stays in the chat at the end of a run is the delivered song and its lyrics, and nothing
else of ours with a button on it.

**How it works.** Every screen goes up through ``handlers.common.present``, so that one
function records the id of the message now showing the screen (:data:`SCREEN_MESSAGE_ID_KEY`)
and retires the one it recorded before. One-sentence notices go up through
``handlers.common.say`` and are recorded in :data:`NOTICE_MESSAGE_IDS_KEY`; they are retired
on the NEXT update, never the one that sent them, because a notice is routinely followed in
the same handler by a redraw of the screen it is about — retiring it there would delete it
the instant it was read. The reply-keyboard menu is recorded in :data:`MENU_MESSAGE_ID_KEY`
and is the one message that is never deleted until a NEWER menu has been sent: Telegram
clients bind the persistent keyboard to the message that installed it and can hide it when
that message goes, so the order is always send-new, then delete-old.

**Why a context variable rather than a parameter.** ``present`` and ``say`` have sixty-odd
call sites between them and take no ``FSMContext``; threading one through every caller would
be a large diff whose only effect is the same thing this does, with a call site that forgets
it silently leaving a live screen behind. :class:`ScreenTrackingMiddleware` binds the
update's ``FSMContext`` for the duration of one handler, and a ``present`` called outside a
dispatcher (a unit test, a worker) sees no scope and simply tracks nothing — the old
behaviour, never a crash.

**What can never be deleted, by construction.** Only ``present`` and ``say`` write the ids,
and the worker sends the song, the lyric card and the lyric sheet with ``bot.send_*``
directly, so a delivered song is never a tracked id. The one place a song could still reach
a delete is as the message a button was pressed ON — ``post_delivery_keyboard`` rides on the
audio — which is what :func:`is_media` guards: every retire of a message object checks it
first. The in-flight progress message is the other exception: ``handlers.confirm`` edits the
Confirm screen INTO it, so its id can be the tracked screen's id, and it is skipped by
comparing against :data:`PROGRESS_MESSAGE_ID_KEY`.

**Every delete is best effort.** ``deleteMessage`` fails after 48 hours and on a message
that is already gone; the fallback is to strip the inline keyboard, which has no time limit,
and that fallback is itself guarded. A chat-cleanup step must never fail the handler it
rides on.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Iterable
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import Any, Final

from aiogram import BaseMiddleware, Bot
from aiogram.exceptions import TelegramAPIError
from aiogram.fsm.context import FSMContext
from aiogram.types import Message, TelegramObject

from bayram.logging import get_logger

__all__ = [
    "SCREEN_MESSAGE_ID_KEY",
    "MENU_MESSAGE_ID_KEY",
    "NOTICE_MESSAGE_IDS_KEY",
    "PROGRESS_MESSAGE_ID_KEY",
    "TRACKING_KEYS",
    "ScreenTrackingMiddleware",
    "current_state",
    "ids_of",
    "is_media",
    "note_sent",
    "retire_message",
    "retire_message_id",
    "sent_this_update",
    "sweep_notices",
    "track_notice",
]

_LOG = get_logger(__name__)

#: The inline screen the customer is looking at — the last message ``present`` drew.
SCREEN_MESSAGE_ID_KEY: Final[str] = "screen_message_id"

#: The last message that carried the persistent reply keyboard (``menu_screen``).
MENU_MESSAGE_ID_KEY: Final[str] = "menu_message_id"

#: One-sentence notices ``say`` sent that have not been retired yet. A list, because one
#: handler can say two things.
NOTICE_MESSAGE_IDS_KEY: Final[str] = "notice_message_ids"

#: FSM-data key holding the message the worker is editing its progress frames into. Kept
#: because a session that outlives its own progress message is a session nobody can find
#: their way back to, and an operator reading a log wants both ids together.
#:
#: Declared here rather than in ``handlers.submitting`` (which re-exports it) because the
#: tracker has to skip it and this module must not import the handlers package.
PROGRESS_MESSAGE_ID_KEY: Final[str] = "progress_message_id"

#: The three keys above that are chat layout rather than session state. They survive
#: ``handlers.common.clear_keeping_identity``: a cancelled run's last screen is still on the
#: customer's chat, and forgetting its id is exactly how it would become a leftover.
TRACKING_KEYS: Final[tuple[str, ...]] = (
    SCREEN_MESSAGE_ID_KEY,
    MENU_MESSAGE_ID_KEY,
    NOTICE_MESSAGE_IDS_KEY,
)


@dataclass(slots=True)
class _UpdateScope:
    state: FSMContext
    #: Message ids sent or drawn while handling THIS update, which the notice sweep spares.
    sent: set[int] = field(default_factory=set)


_SCOPE: ContextVar[_UpdateScope | None] = ContextVar("bayram_screen_scope", default=None)


class ScreenTrackingMiddleware(BaseMiddleware):
    """Bind the update's ``FSMContext`` so ``present``/``say`` can track what they draw."""

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        state = data.get("state")
        if not isinstance(state, FSMContext):
            return await handler(event, data)
        token = _SCOPE.set(_UpdateScope(state=state))
        try:
            return await handler(event, data)
        finally:
            _SCOPE.reset(token)


def current_state() -> FSMContext | None:
    """The ``FSMContext`` of the update being handled, or ``None`` outside a dispatcher."""
    scope = _SCOPE.get()
    return scope.state if scope is not None else None


def note_sent(message_id: int) -> None:
    """Remember that this update put ``message_id`` up, so this update's sweep spares it."""
    scope = _SCOPE.get()
    if scope is not None:
        scope.sent.add(message_id)


def sent_this_update() -> frozenset[int]:
    scope = _SCOPE.get()
    return frozenset(scope.sent) if scope is not None else frozenset()


def is_media(message: Message) -> bool:
    """True for anything that is not a plain bot text message — the song above all.

    ``text is None`` alone would cover it (a captioned audio has ``caption``, not ``text``);
    the named fields are spelled out so a reader sees what is being protected.
    """
    return (
        message.text is None
        or message.audio is not None
        or message.voice is not None
        or message.photo is not None
        or message.document is not None
        or message.video is not None
        or message.animation is not None
    )


async def retire_message(message: Message) -> None:
    """Delete one of our text screens; strip its keyboard if it can no longer be deleted.

    Never touches media: the delivered song carries ``post_delivery_keyboard`` and is the
    message a 🏠 or 🎂 press arrives ON.
    """
    if is_media(message) or message.bot is None:
        return
    await retire_message_id(message.bot, message.chat.id, message.message_id)


async def retire_message_id(bot: Bot, chat_id: int, message_id: int) -> None:
    """Best-effort delete by id, falling back to removing the inline keyboard.

    Only ever called with ids ``present``/``say`` recorded (text messages of ours) or with a
    message :func:`retire_message` has already checked, so the id is never a song.
    """
    try:
        await bot.delete_message(chat_id=chat_id, message_id=message_id)
    except TelegramAPIError as exc:
        _LOG.debug(
            "could not delete a retired screen; stripping its keyboard",
            extra={"failure": repr(exc), "message_id": message_id},
        )
    else:
        return
    try:
        await bot.edit_message_reply_markup(
            chat_id=chat_id, message_id=message_id, reply_markup=None
        )
    except TelegramAPIError as exc:
        # "message is not modified" (it had no keyboard), "not found" (already gone): either
        # way there is nothing live left to retire.
        _LOG.debug(
            "could not strip a retired screen's keyboard",
            extra={"failure": repr(exc), "message_id": message_id},
        )


def ids_of(raw: object) -> tuple[int, ...]:
    """The ints in a stored list, ignoring anything a hand-edit or an old build left there."""
    if isinstance(raw, int) and not isinstance(raw, bool):
        return (raw,)
    if isinstance(raw, Iterable) and not isinstance(raw, str | bytes):
        return tuple(item for item in raw if isinstance(item, int) and not isinstance(item, bool))
    return ()


async def track_notice(sent: Message, bot: Bot | None) -> None:
    """Record a one-sentence notice, retiring the ones EARLIER updates left behind.

    ``bot`` is the INBOUND event's bot: a sent message's own ``bot`` is only set when the
    response was mounted, which an in-process session double does not do.
    """
    bot = bot or sent.bot
    state = current_state()
    if state is None or bot is None:
        return
    note_sent(sent.message_id)
    data = await state.get_data()
    kept = await sweep_notices(bot, sent.chat.id, data.get(NOTICE_MESSAGE_IDS_KEY))
    await state.update_data({NOTICE_MESSAGE_IDS_KEY: [*kept, sent.message_id]})


async def sweep_notices(bot: Bot, chat_id: int, raw: object) -> tuple[int, ...]:
    """Retire every notice an EARLIER update left; return the ones this update sent."""
    fresh = sent_this_update()
    kept: list[int] = []
    for notice in ids_of(raw):
        if notice in fresh:
            kept.append(notice)
        else:
            await retire_message_id(bot, chat_id, notice)
    return tuple(kept)
