"""The bot process. ``python -m hbd.main``.

Two shapes, one code path:

* **Production** — Redis holds the wizard state and the queue; ARQ workers do the
  generating. ``HBD_USE_FAKE_PROVIDERS`` is off, real keys are read, real money is spent.
* **Offline demo** — ``HBD_USE_FAKE_PROVIDERS=1``. The FSM lives in memory, the order runs
  as a background task inside this process, and every vendor is a fake. One command, one
  terminal, no infrastructure, no keys, no spend.

The branch is exactly one decision (``use_fake_providers``), and everything downstream of
it is the same objects wired the same way, because a demo path that exercises different
code proves nothing about the thing you are demonstrating.
"""

from __future__ import annotations

import asyncio
import contextlib
from pathlib import Path

from aiogram import Bot
from aiogram.fsm.storage.base import BaseStorage
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.fsm.storage.redis import RedisStorage
from arq import create_pool
from arq.connections import RedisSettings

from hbd.bot.app import build_bot, build_dispatcher, run_polling
from hbd.bot.deps import BotDeps
from hbd.bot.ports import OrderSubmitter
from hbd.config import Settings, load_settings
from hbd.errors import HbdError
from hbd.logging import configure_logging, get_logger
from hbd.pipeline.content import LlmContentWriter
from hbd.runtime.container import AppContainer, build_container
from hbd.runtime.jobs import BOT_CTX_KEY, CONTAINER_CTX_KEY, generate_and_deliver
from hbd.runtime.startup import verify_host
from hbd.runtime.submitter import ArqOrderSubmitter, InProcessOrderSubmitter

__all__ = ["main", "run", "build_submitter"]

_LOG = get_logger(__name__)


def _fsm_storage(settings: Settings) -> BaseStorage:
    """Redis in production so a restart does not throw away a half-typed wizard."""
    if settings.use_fake_providers:
        return MemoryStorage()
    return RedisStorage.from_url(settings.redis_url)


async def build_submitter(
    settings: Settings, container: AppContainer, bot: Bot
) -> tuple[OrderSubmitter, object | None]:
    """The queue seam. Returns the submitter and whatever must be closed with it."""
    if settings.use_fake_providers:
        ctx = {CONTAINER_CTX_KEY: container, BOT_CTX_KEY: bot}

        async def run_inline(order_id: str, chat_id: int, progress_message_id: int) -> None:
            summary = await generate_and_deliver(ctx, order_id, chat_id, progress_message_id)
            _LOG.info("inline job finished", extra=summary)

        return (
            InProcessOrderSubmitter(
                container.repository, run_inline, is_production=settings.is_production
            ),
            None,
        )

    redis = await create_pool(RedisSettings.from_dsn(settings.redis_url))
    return ArqOrderSubmitter(redis, container.repository), redis


async def run(settings: Settings, *, data_root: Path | None = None) -> None:
    """Build everything, poll until interrupted, then release it all."""
    verify_host(settings)
    container = await build_container(settings, data_root=data_root)
    bot = build_bot(settings)
    submitter, closeable = await build_submitter(settings, container, bot)
    deps = BotDeps(
        settings=settings,
        submitter=submitter,
        # The wizard writes the lyric before the order is queued, so it needs the same
        # writer the pipeline uses. The primary provider only: the fallback exists for the
        # worker's unattended retries, and a customer waiting on a screen is better served
        # by a quick "please try again" than by a second slow vendor call.
        content=LlmContentWriter(container.providers.llm, settings),
        payment=container.payment,
        amount_minor=settings.kit_price_amount_minor,
        currency=settings.kit_currency,
    )
    dispatcher = build_dispatcher(deps, storage=_fsm_storage(settings))
    _LOG.info(
        "bot starting",
        extra={
            "environment": settings.environment,
            "is_fake": settings.use_fake_providers,
            "ui_language": settings.default_ui_language.value,
        },
    )
    try:
        await run_polling(bot, dispatcher)
    finally:
        await _shutdown(container, bot, closeable)


async def _shutdown(container: AppContainer, bot: Bot, closeable: object | None) -> None:
    """Release everything, reporting each failure rather than letting one hide the rest."""
    for label, close in (
        ("queue", getattr(closeable, "aclose", None)),
        ("bot", bot.session.close),
        ("container", container.aclose),
    ):
        if close is None:
            continue
        try:
            await close()
        except Exception as exc:
            _LOG.warning("could not close cleanly", extra={"resource": label, "detail": repr(exc)})


def main() -> int:
    """Console entry point. Returns a process exit code; never raises."""
    try:
        settings = load_settings()
    except HbdError as exc:
        # No logging is configured yet, so this is the one place stderr is the right sink.
        print(f"hbd: {exc.operator_message}")
        return 2

    configure_logging(level=settings.log_level, is_json=not settings.is_debug)
    try:
        asyncio.run(run(settings))
    except KeyboardInterrupt:
        _LOG.info("bot stopped by operator")
    except HbdError as exc:
        _LOG.error("bot could not start", extra=exc.to_log_dict())
        return 1
    return 0


if __name__ == "__main__":  # pragma: no cover - process entry point
    with contextlib.suppress(SystemExit):
        raise SystemExit(main())
