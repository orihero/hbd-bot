"""Re-push the reply keyboard to chats still holding an old one (IMAGE_VIDEO_SPEC §2.2).

A reply keyboard is chat-level state in the customer's client, re-sent only by a handful of
flows (``/start``, onboarding's end, a language change, 🏠, the fallback). When a label
changes — 🎵 became ✨ Create — every other chat keeps the old one pinned indefinitely. So the
version a chat was last sent lives in Redis, **per account and outside FSM data**, under
``menu:v:{tg}`` with no TTL: FSM data is wiped after every song (``_release_session``),
expires after fourteen days and is cleared bare by ``/forget``, and a version kept there would
re-push after every song.

:class:`MenuRepushMiddleware` is the one post-handler hook: after a private message from an
onboarded account whose stored version is below :data:`~bayram.bot.keyboards.MENU_VERSION`,
it sends ONE separate ``menu_screen`` message carrying the new keyboard — an inline screen
cannot carry a reply keyboard — headed by ``notice.menu_updated`` when media is offered to
that account (others get the relabel silently), and stores the version. The flows that draw
the menu themselves stamp the version (:func:`stamp_menu_version`) so the hook does not send a
second one. ``/forget`` deletes the key.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any, Final

from aiogram import BaseMiddleware
from aiogram.enums import ChatType
from aiogram.fsm.context import FSMContext
from aiogram.types import Message, TelegramObject

from bayram.bot.deps import DEPS_KEY, BotDeps
from bayram.bot.draft import ONBOARDED_KEY
from bayram.bot.handlers.common import ui_language
from bayram.bot.i18n import translate
from bayram.bot.keyboards import MENU_VERSION, main_menu_keyboard
from bayram.bot.media_offer import offered_kinds
from bayram.bot.states import Onboarding
from bayram.contracts import Result, err, ok
from bayram.errors import StorageError
from bayram.logging import get_logger
from bayram.media.overrides import MediaSwitchStore

__all__ = [
    "MENU_VERSION_KEY_PREFIX",
    "MENU_UPDATED_KEY",
    "menu_version_key",
    "read_menu_version",
    "stamp_menu_version",
    "forget_menu_version",
    "MenuRepushMiddleware",
]

_LOG = get_logger(__name__)

MENU_VERSION_KEY_PREFIX: Final[str] = "menu:v:"
MENU_UPDATED_KEY: Final[str] = "notice.menu_updated"
_MENU_PROMPT_KEY: Final[str] = "menu.prompt"

#: Accounts known to hold the current keyboard, so a steady chat costs no Redis read per
#: message. Bounded: past the ceiling it is simply emptied and re-learned.
_KNOWN_CURRENT_CEILING: Final[int] = 50_000


def menu_version_key(telegram_user_id: int) -> str:
    return f"{MENU_VERSION_KEY_PREFIX}{telegram_user_id}"


async def read_menu_version(store: MediaSwitchStore, telegram_user_id: int) -> int | None:
    """The version last sent to this account; ``None`` for never (the 🎵 menu, version 1)
    and for an unreadable key — the caller then leaves the chat alone rather than guess."""
    raw = await store.get(menu_version_key(telegram_user_id))
    if raw is None:
        return None
    text = raw.decode("utf-8", "replace") if isinstance(raw, bytes | bytearray) else str(raw)
    try:
        return int(text.strip())
    except ValueError:
        return None


async def stamp_menu_version(store: MediaSwitchStore | None, telegram_user_id: int | None) -> None:
    """Record that this account now holds the current keyboard. Never raises."""
    if store is None or telegram_user_id is None:
        return
    try:
        await store.set(menu_version_key(telegram_user_id), str(MENU_VERSION))
    except Exception as exc:
        # The worst case is one extra keyboard message on the next message.
        _LOG.warning("the menu version could not be stored", extra={"failure": repr(exc)})


async def forget_menu_version(
    store: MediaSwitchStore | None, telegram_user_id: int | None
) -> Result[None]:
    """``/forget``'s arm (§2.2): the key names an account, so it goes with the rest."""
    if store is None or telegram_user_id is None:
        return ok(None)
    try:
        await store.delete(menu_version_key(telegram_user_id))
    except Exception as exc:
        _LOG.error("the menu version could not be erased", extra={"failure": repr(exc)})
        return err(
            StorageError(
                "the menu version could not be erased",
                context={"key_prefix": MENU_VERSION_KEY_PREFIX},
            )
        )
    return ok(None)


class MenuRepushMiddleware(BaseMiddleware):
    """INNER, on the message observer: runs the handler, then re-pushes at most once.

    Inner so it runs only for a message some handler claimed — after the gates, never for an
    update they refused — and after that handler, so the re-push is the last thing the
    customer sees rather than something the handler's own screen lands on top of.
    """

    def __init__(self) -> None:
        self._known_current: set[int] = set()

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        result = await handler(event, data)
        try:
            await self._after(event, data)
        except Exception:
            _LOG.exception("the menu re-push failed; it will be tried on the next message")
        return result

    async def _after(self, event: TelegramObject, data: dict[str, Any]) -> None:
        if not isinstance(event, Message) or event.chat.type != ChatType.PRIVATE:
            return
        user = event.from_user
        deps = data.get(DEPS_KEY)
        state = data.get("state")
        if user is None or not isinstance(deps, BotDeps) or not isinstance(state, FSMContext):
            return
        store = deps.media_kv
        if store is None or user.id in self._known_current:
            return
        # Onboarded only: the menu is what onboarding ENDS with, and a keyboard pushed at an
        # account mid-onboarding would offer buttons the onboarding router refuses.
        if (await state.get_data()).get(ONBOARDED_KEY) is not True:
            return
        current = await state.get_state()
        if current is not None and current in {s.state for s in Onboarding.__all_states__}:
            return
        stored = await read_menu_version(store, user.id)
        if stored is not None and stored >= MENU_VERSION:
            self._remember(user.id)
            return
        language = await ui_language(state, deps)
        body = translate(_MENU_PROMPT_KEY, language)
        if await offered_kinds(deps, user.id):
            body = f"{translate(MENU_UPDATED_KEY, language)}\n\n{body}"
        await event.answer(body, reply_markup=main_menu_keyboard(language))
        await stamp_menu_version(store, user.id)
        self._remember(user.id)
        _LOG.info("the menu keyboard was re-pushed", extra={"menu_version": MENU_VERSION})

    def _remember(self, telegram_user_id: int) -> None:
        if len(self._known_current) >= _KNOWN_CURRENT_CEILING:
            self._known_current.clear()
        self._known_current.add(telegram_user_id)
