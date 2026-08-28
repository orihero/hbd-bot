"""The ARQ worker process. ``python -m arq hbd.worker.WorkerSettings``.

``WorkerSettings`` is built at import time because that is how ARQ's CLI finds it. It
reads configuration (so importing this module requires a valid environment) but opens no
connection: the container, the provider pools and the bot session are all created inside
``on_startup``, once, and released in ``on_shutdown``.

The worker owns a ``Bot`` of its own. It never polls — it only sends — because progress
edits and the finished kit have to reach the customer from the process that produced them.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from hbd.bot.app import build_bot
from hbd.config import Settings, load_settings
from hbd.logging import configure_logging, get_logger
from hbd.runtime.container import build_container
from hbd.runtime.jobs import BOT_CTX_KEY, CONTAINER_CTX_KEY, build_kit_worker_settings
from hbd.runtime.startup import verify_host

__all__ = ["WorkerSettings", "build_dependencies", "shutdown"]

_LOG = get_logger(__name__)


def _settings() -> Settings:
    settings = load_settings()
    configure_logging(level=settings.log_level, is_json=not settings.is_debug)
    return settings


_SETTINGS = _settings()


async def build_dependencies() -> Mapping[str, Any]:
    """Awaited once, at worker startup. Everything expensive is created here."""
    verify_host(_SETTINGS)
    container = await build_container(_SETTINGS)
    _LOG.info(
        "worker dependencies built",
        extra={"is_fake": _SETTINGS.use_fake_providers, "environment": _SETTINGS.environment},
    )
    return {CONTAINER_CTX_KEY: container, BOT_CTX_KEY: build_bot(_SETTINGS)}


async def shutdown(ctx: Mapping[str, Any]) -> None:
    """Release the pools the worker opened. Failures are reported, never masked."""
    container = ctx.get(CONTAINER_CTX_KEY)
    bot = ctx.get(BOT_CTX_KEY)
    for label, close in (
        ("bot", getattr(getattr(bot, "session", None), "close", None)),
        ("container", getattr(container, "aclose", None)),
    ):
        if close is None:
            continue
        try:
            await close()
        except Exception as exc:
            _LOG.warning("could not close cleanly", extra={"resource": label, "detail": repr(exc)})


WorkerSettings = build_kit_worker_settings(
    settings=_SETTINGS,
    build_dependencies=build_dependencies,
    shutdown=shutdown,
)
