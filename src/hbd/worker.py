"""The ARQ worker process. ``python -m arq hbd.worker.WorkerSettings``.

``WorkerSettings`` is built at import time because that is how ARQ's CLI finds it. It
reads configuration (so importing this module requires a valid environment) but opens no
connection: the container, the provider pools and the bot session are all created inside
``on_startup``, once, and released in ``on_shutdown``.

The worker owns a ``Bot`` of its own. It never polls — it only sends — because progress
edits and the finished kit have to reach the customer from the process that produced them.

**That ``Bot`` is now also how a customer learns their PAYMENT landed, and the reason is a
boundary rather than a convenience.** The Payme Merchant API endpoint runs as a fourth
process (``hbd-payme.service``) holding exactly one credential — the cashbox key — and no
Telegram token at all, which is the whole point of it being separate: the key's blast radius
is "mints credits", not "impersonates us". So the settlement that happens over there enqueues
:func:`hbd.runtime.payme_jobs.notify_payment_settled` and this process, which already holds a
send-only ``Bot``, says the sentence. The same asymmetry the vendor-balance poll relies on,
pointed the other way: there the worker holds a credential the panel must not, here it holds
one the gateway must not.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from hbd.bot.app import build_bot, build_storage
from hbd.config import Settings, load_settings
from hbd.logging import configure_logging, get_logger
from hbd.runtime.container import build_container
from hbd.runtime.jobs import (
    BOT_CTX_KEY,
    CONTAINER_CTX_KEY,
    STORAGE_CTX_KEY,
    build_kit_worker_settings,
)
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
    # The wizard's FSM storage, so a finished run can un-park the session waiting on it.
    # Same URL and same default key builder as the bot process, which is what makes the
    # key this worker writes the key that process reads.
    return {
        CONTAINER_CTX_KEY: container,
        BOT_CTX_KEY: build_bot(_SETTINGS),
        STORAGE_CTX_KEY: build_storage(_SETTINGS),
    }


async def shutdown(ctx: Mapping[str, Any]) -> None:
    """Release the pools the worker opened. Failures are reported, never masked."""
    container = ctx.get(CONTAINER_CTX_KEY)
    bot = ctx.get(BOT_CTX_KEY)
    storage = ctx.get(STORAGE_CTX_KEY)
    for label, close in (
        ("fsm_storage", getattr(storage, "close", None)),
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
