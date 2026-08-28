"""Composition root for the bot process. The only module here that knows a token exists.

Importing this module performs no I/O and opens no connection, so the whole bot is
importable in a unit test. ``run_polling`` is the one function that actually talks to
Telegram, and nothing else calls it.
"""

from __future__ import annotations

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.base import BaseStorage
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.fsm.storage.redis import RedisStorage

from hbd.bot.deps import DEPS_KEY, BotDeps
from hbd.bot.handlers import build_router
from hbd.bot.middleware import ErrorGuardMiddleware
from hbd.config import Settings
from hbd.logging import get_logger

__all__ = ["build_bot", "build_storage", "build_dispatcher", "run_polling"]

_LOG = get_logger(__name__)


def build_bot(settings: Settings) -> Bot:
    """HTML everywhere: every catalogue template is written for it, and ``hbd.bot.i18n``
    escapes every interpolated value on that assumption."""
    return Bot(
        token=settings.telegram_bot_token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )


def build_storage(settings: Settings) -> BaseStorage:
    """Redis in production so a restart does not throw away a half-typed wizard."""
    return RedisStorage.from_url(settings.redis_url)


def build_dispatcher(deps: BotDeps, *, storage: BaseStorage | None = None) -> Dispatcher:
    """Wire middleware, dependencies and routers. In-memory storage unless told otherwise."""
    dispatcher = Dispatcher(storage=storage or MemoryStorage())
    dispatcher[DEPS_KEY] = deps
    guard = ErrorGuardMiddleware()
    dispatcher.message.middleware(guard)
    dispatcher.callback_query.middleware(guard)
    dispatcher.include_router(build_router())
    return dispatcher


async def run_polling(bot: Bot, dispatcher: Dispatcher) -> None:  # pragma: no cover - live I/O
    """Long polling. Webhook mode is a deployment concern and is not built here."""
    _LOG.info("bot polling started")
    await bot.delete_webhook(drop_pending_updates=True)
    await dispatcher.start_polling(bot)
