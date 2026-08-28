"""The job: generate the kit, then deliver it to the chat that asked for it.

``hbd.pipeline.worker.generate_kit`` stops at "kit persisted". Delivery is a Telegram
concern and the pipeline does not know Telegram exists — correctly. Something has to join
them, and this is that something: the only module in the system that imports both the
orchestrator and ``aiogram``.

The chat and the progress message travel *with the job*, not on the pipeline, because the
pipeline is shared across concurrent orders and a progress sink is aimed at exactly one
message. A per-job sink is the difference between fifteen customers watching their own
order and fifteen customers watching the fifteenth.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from typing import Any, Final
from uuid import UUID

from aiogram import Bot
from arq.connections import RedisSettings
from arq.worker import Retry

from hbd.bot.delivery import deliver_kit
from hbd.bot.progress import TelegramProgressSink
from hbd.config import Settings
from hbd.contracts import Err, Order
from hbd.errors import PipelineError
from hbd.logging import correlation_scope, get_logger
from hbd.pipeline.outcome import PipelineOutcome
from hbd.runtime.container import AppContainer

__all__ = [
    "generate_and_deliver",
    "build_kit_worker_settings",
    "KIT_JOB_NAME",
    "CONTAINER_CTX_KEY",
    "BOT_CTX_KEY",
]

_LOG = get_logger(__name__)

#: ARQ dispatches by function name, so the enqueue side and the worker side must agree
#: on this exact string. It is asserted against the function itself at import.
KIT_JOB_NAME: Final[str] = "generate_and_deliver"

CONTAINER_CTX_KEY: Final[str] = "container"
BOT_CTX_KEY: Final[str] = "bot"

#: Job-level retry backoff. Multiplied by the attempt number, as ARQ counts them from 1.
_DEFAULT_JOB_TRY: Final[int] = 1


def _require[T](ctx: Mapping[str, Any], key: str, expected: type[T]) -> T:
    value = ctx.get(key)
    if not isinstance(value, expected):
        raise PipelineError(
            f"worker context is missing a usable '{key}'",
            context={"key": key, "found": type(value).__name__},
        )
    return value


def _defer_seconds(ctx: Mapping[str, Any], settings: Settings) -> float:
    attempt = ctx.get("job_try", _DEFAULT_JOB_TRY)
    tries = attempt if isinstance(attempt, int) and attempt > 0 else _DEFAULT_JOB_TRY
    return settings.provider_backoff_base_s * tries


def _order_uuid(order_id: str) -> UUID:
    """Parse the queued id. A non-UUID means the enqueue side is broken, so it raises."""
    try:
        return UUID(order_id)
    except ValueError as exc:
        raise PipelineError(
            "job was queued with an order id that is not a UUID",
            context={"order_id": order_id},
            cause=exc,
        ) from exc


async def _run_pipeline(
    container: AppContainer,
    bot: Bot,
    order: Order,
    *,
    ctx: Mapping[str, Any],
    chat_id: int,
    progress_message_id: int,
) -> PipelineOutcome | dict[str, Any]:
    """The outcome, or the JSON summary to return when the run failed terminally.

    The progress sink is built here, per job, because it is aimed at exactly one message.
    """
    sink = TelegramProgressSink(
        bot,
        chat_id=chat_id,
        message_id=progress_message_id,
        language=order.brief.ui_language,
    )
    outcome = await container.pipeline(sink=sink).run(order)
    if not isinstance(outcome, Err):
        return outcome.value
    if outcome.error.is_retryable:
        raise Retry(defer=_defer_seconds(ctx, container.settings))
    _LOG.error("order failed terminally", extra=outcome.error.to_log_dict())
    return {
        "order_id": str(order.id),
        "is_delivered": False,
        "error": outcome.error.error_code,
        "user_message_key": outcome.error.user_message_key,
    }


async def _send_kit(
    bot: Bot,
    order: Order,
    result: PipelineOutcome,
    *,
    ctx: Mapping[str, Any],
    settings: Settings,
    chat_id: int,
) -> bool:
    """Send the finished kit. ``False`` means it was not delivered but must not be retried."""
    delivered = await deliver_kit(
        bot,
        chat_id=chat_id,
        kit=result.kit,
        language=order.brief.ui_language,
        gaps=result.gaps,
    )
    if not isinstance(delivered, Err):
        return True
    # The kit exists and is persisted; only the send failed. Retryable failures get
    # another pass, and the replay short-circuit means that costs a read.
    _LOG.error("kit could not be delivered", extra=delivered.error.to_log_dict())
    if delivered.error.is_retryable:
        raise Retry(defer=_defer_seconds(ctx, settings))
    return False


async def generate_and_deliver(
    ctx: Mapping[str, Any],
    order_id: str,
    chat_id: int,
    progress_message_id: int,
) -> dict[str, Any]:
    """Run one order end to end and send the kit. Returns a JSON-safe summary.

    Raises only ``arq.worker.Retry`` (deliberately, to defer a retryable failure) and
    ``PipelineError`` when the worker was wired up wrong — a startup bug, not a run-time one.
    """
    container = _require(ctx, CONTAINER_CTX_KEY, AppContainer)
    bot = _require(ctx, BOT_CTX_KEY, Bot)

    found = await container.repository.get_order(_order_uuid(order_id))
    if isinstance(found, Err):
        _LOG.error("order not found for job", extra=found.error.to_log_dict())
        return {"order_id": order_id, "is_delivered": False, "error": found.error.error_code}

    order = found.value
    with correlation_scope(order.correlation_id):
        outcome = await _run_pipeline(
            container,
            bot,
            order,
            ctx=ctx,
            chat_id=chat_id,
            progress_message_id=progress_message_id,
        )
        if isinstance(outcome, dict):
            return outcome

        is_delivered = await _send_kit(
            bot, order, outcome, ctx=ctx, settings=container.settings, chat_id=chat_id
        )
        return {
            "order_id": order_id,
            "is_delivered": is_delivered,
            "gaps": len(outcome.gaps),
            "total_duration_ms": outcome.total_duration_ms,
            "total_cost_usd": round(outcome.total_cost_usd, 6),
            "is_name_verified": all(verdict.is_match for verdict in outcome.name_verdicts),
        }


def build_kit_worker_settings(
    *,
    settings: Settings,
    build_dependencies: Callable[[], Awaitable[Mapping[str, Any]]],
    shutdown: Callable[[Mapping[str, Any]], Awaitable[None]] | None = None,
) -> type[Any]:
    """ARQ's ``WorkerSettings`` for this project, hosting the one job.

    ``build_dependencies`` is awaited once at startup, so no pool is opened at import time
    and ``python -m hbd.worker`` stays importable in a test.
    """

    async def startup(ctx: dict[str, Any]) -> None:
        ctx.update(await build_dependencies())
        _LOG.info(
            "worker started",
            extra={"concurrency": settings.worker_concurrency, "job": KIT_JOB_NAME},
        )

    async def teardown(ctx: dict[str, Any]) -> None:
        if shutdown is not None:
            await shutdown(ctx)

    class WorkerSettings:
        functions = [generate_and_deliver]
        redis_settings = RedisSettings.from_dsn(settings.redis_url)
        max_jobs = settings.worker_concurrency
        job_timeout = settings.queue_job_timeout_s
        keep_result = settings.queue_result_ttl_s
        on_startup = staticmethod(startup)
        on_shutdown = staticmethod(teardown)

    return WorkerSettings


assert generate_and_deliver.__name__ == KIT_JOB_NAME, (
    "the enqueue name and the job function have drifted apart; ARQ would never dispatch"
)
