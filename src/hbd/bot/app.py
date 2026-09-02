"""Composition root for the bot process. The only module here that knows a token exists.

Importing this module performs no I/O and opens no connection, so the whole bot is
importable in a unit test. ``run_polling`` is the one function that actually talks to
Telegram, and nothing else calls it.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Final

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramAPIError
from aiogram.fsm.storage.base import BaseEventIsolation, BaseStorage
from aiogram.fsm.storage.memory import MemoryStorage, SimpleEventIsolation
from aiogram.fsm.storage.redis import RedisEventIsolation, RedisStorage

from hbd.bot.deps import DEPS_KEY, BotDeps
from hbd.bot.gate import InboundGateMiddleware
from hbd.bot.handlers import build_router
from hbd.bot.handlers.commands import BOT_COMMANDS
from hbd.bot.middleware import ErrorGuardMiddleware
from hbd.config import Settings
from hbd.db.retention import DEFAULT_RETENTION_POLICY
from hbd.logging import get_logger
from hbd.ratelimit import resolve_inbound_policy

__all__ = [
    "build_bot",
    "build_storage",
    "build_event_isolation",
    "build_dispatcher",
    "install_inbound_gate",
    "publish_commands",
    "run_polling",
    "WIZARD_STATE_TTL",
]

_LOG = get_logger(__name__)

#: How long an untouched wizard session survives in Redis. Sized to
#: ``RetentionPolicy.abandoned_draft_days`` so the copy of the customer's free text in
#: FSM storage expires on the same clock as the ``orders`` row the wizard would have
#: written, rather than on no clock at all.
WIZARD_STATE_TTL: Final[timedelta] = timedelta(days=DEFAULT_RETENTION_POLICY.abandoned_draft_days)


def build_bot(settings: Settings) -> Bot:
    """HTML everywhere: every catalogue template is written for it, and ``hbd.bot.i18n``
    escapes every interpolated value on that assumption."""
    return Bot(
        token=settings.telegram_bot_token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )


def build_storage(settings: Settings) -> BaseStorage:
    """Redis in production so a restart does not throw away a half-typed wizard.

    The TTL is not a tidiness setting, it is the retention clock. A draft holds the
    recipient's display name, the free-text note and — since the preview step — the whole
    approved lyric, which is the same personal data ``hbd.db.purge`` is legally obliged to
    clear from Postgres. That job only ever touches Postgres, so an abandoned wizard would
    otherwise keep a second copy in Redis forever, outliving both the 14-day sweep that
    deletes the order it would have created and the 30-day sweep that nulls the lyric.
    Expiring on the abandoned-draft clock is what makes the two copies agree.
    """
    return RedisStorage.from_url(
        settings.redis_url, state_ttl=WIZARD_STATE_TTL, data_ttl=WIZARD_STATE_TTL
    )


def build_event_isolation(settings: Settings) -> BaseEventIsolation:
    """The per-chat lock the dispatcher serialises one user's updates with.

    Redis in production for the same reason the storage is: the lock has to hold across
    every process that handles this chat, and an in-process lock would only hold within
    one. See :func:`build_dispatcher` for what depends on it.
    """
    if settings.use_fake_providers:
        return SimpleEventIsolation()
    return RedisEventIsolation.from_url(settings.redis_url)


def build_dispatcher(
    deps: BotDeps,
    *,
    storage: BaseStorage | None = None,
    events_isolation: BaseEventIsolation | None = None,
) -> Dispatcher:
    """Wire middleware, dependencies and routers. In-memory storage unless told otherwise.

    ``events_isolation`` is not optional in the sense that it can be left off: aiogram
    defaults to ``DisabledEventIsolation``, and that default is what let a double tap on
    Confirm buy two songs. State filters read ``raw_state``, which aiogram's FSM middleware
    loads **inside this lock** and hands to every filter for the update; without the lock,
    two taps delivered in one ``getUpdates`` batch — ``start_polling`` runs handlers as
    concurrent tasks — both read ``Wizard:confirm`` before either handler has flipped it,
    and both pass the filter. No ordering of awaits inside the handler can close that
    window, because the read that loses the race happens before the handler is called.

    The default here is an in-process lock rather than none, so a test and the demo get
    the same serialisation production gets.

    Two consequences worth knowing before anything long-running is added to a handler.
    **One chat's updates are serialised for the whole of each update**, so the lyric write
    — the one handler that awaits a vendor for up to ``llm_timeout_s`` — makes the Cancel
    on its own writing frame wait for the write to return before it is processed. The
    session still ends cancelled with nothing kept; it is late, not wrong. Moving that
    vendor call off the locked update is the fix, and it is not this function's to make.
    **And no handler may feed an update for its own chat**: that is a re-entrant acquire
    and it deadlocks. Nothing in ``src`` does; a test that did now drives the second update
    through a second dispatcher, which is also the honest model of the case that survives
    the lock — ``RedisEventIsolation`` expires its lock after sixty seconds.
    """
    dispatcher = Dispatcher(
        storage=storage or MemoryStorage(),
        events_isolation=events_isolation or SimpleEventIsolation(),
    )
    dispatcher[DEPS_KEY] = deps
    guard = ErrorGuardMiddleware()
    dispatcher.message.middleware(guard)
    dispatcher.callback_query.middleware(guard)
    install_inbound_gate(dispatcher, deps)
    dispatcher.include_router(build_router())
    return dispatcher


def install_inbound_gate(dispatcher: Dispatcher, deps: BotDeps) -> InboundGateMiddleware:
    """Register the touch/block/throttle gate on both customer-facing observers.

    **OUTER**, and therefore ahead of ``ErrorGuardMiddleware`` — outer middlewares run
    before inner ones, so the gate is deliberately NOT wrapped by the error guard and has
    to fail open on its own. Outer is also the only layer that runs before a handler's
    filters, which is what lets it refuse an update no handler would have claimed.

    **ONE instance on both observers.** The counters, the block cache and the touch queue
    live on it, so two instances would hand every account two budgets. Registering per
    event type rather than once on ``update`` is what lets a refused callback be answered,
    which is the only way to stop the customer's button spinning.

    ``deps.entitlements`` is the READ-ONLY meter (``BotDeps.entitlements``): the gate calls
    ``balance_for`` for the block flag and ``touch`` from its background drain, and nothing
    else. ``deps.clock`` rather than a private one, so a test that fixes the wizard's clock
    fixes the throttle window with it.

    The drain is a background task, so it can only start once there is a loop and must be
    stopped before the process goes. ``start_polling`` fires both hooks — which also means
    a test that only calls ``feed_update`` never starts one, and the queue then fills and
    drops loudly and boundedly, the correct behaviour for a bot with no writer.
    """
    gate = InboundGateMiddleware(
        entitlements=deps.entitlements,
        policy=resolve_inbound_policy(deps.settings),
        clock=deps.clock,
    )
    dispatcher.message.outer_middleware(gate)
    dispatcher.callback_query.outer_middleware(gate)
    dispatcher.startup.register(gate.start)
    dispatcher.shutdown.register(gate.aclose)
    return gate


async def publish_commands(bot: Bot) -> None:
    """Fill Telegram's command menu with :data:`BOT_COMMANDS`. Never raises.

    Without this call the menu button in the chat is empty, so ``/privacy`` and ``/support``
    exist but are undiscoverable — which for a bot that collects a third party's name is
    the same as not offering them.

    Failure is logged and swallowed on purpose. The menu is a convenience; a Telegram
    hiccup while setting it must not stop a bot that is otherwise ready to take orders, and
    the next start tries again.

    Called from :func:`run_polling` rather than at import, because importing this module is
    guaranteed to perform no I/O.
    """
    try:
        await bot.set_my_commands(list(BOT_COMMANDS))
    except TelegramAPIError as exc:
        _LOG.error("could not publish the command menu", extra={"failure": repr(exc)})
        return
    _LOG.info("command menu published", extra={"command_count": len(BOT_COMMANDS)})


async def run_polling(bot: Bot, dispatcher: Dispatcher) -> None:  # pragma: no cover - live I/O
    """Long polling. Webhook mode is a deployment concern and is not built here."""
    _LOG.info("bot polling started")
    await publish_commands(bot)
    await bot.delete_webhook(drop_pending_updates=True)
    await dispatcher.start_polling(bot)
