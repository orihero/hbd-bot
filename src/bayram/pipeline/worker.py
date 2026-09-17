"""The ARQ seam: one job function, and the settings object that hosts it.

The job itself is thin on purpose. It looks the order up, hands it to ``KitPipeline`` and
translates the ``Result`` into something ARQ understands. All the judgement lives in the
orchestrator, so the queue can be swapped without touching a decision.

Job-level retry is reserved for *retryable* failures only, and it is safe precisely because
the pipeline replays a finished kit instead of rebuilding one: a deferred re-run of a job
whose song already landed costs a database read.

Enqueue with ``job_id_for(order_id)``. ARQ refuses to queue a job whose id is already
present, which makes double-tapping the button in Telegram a no-op rather than two songs.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from typing import Any, Final
from uuid import UUID

from arq.connections import RedisSettings
from arq.worker import Retry

from bayram.config import Settings
from bayram.contracts import Err, KitRepository
from bayram.errors import PipelineError
from bayram.logging import get_logger
from bayram.pipeline.orchestrator import KitPipeline

__all__ = [
    "JOB_NAME",
    "KIT_JOB_NAME",
    "job_id_for",
    "generate_kit",
    "build_worker_settings",
    "PIPELINE_CTX_KEY",
    "REPOSITORY_CTX_KEY",
]

_LOGGER = get_logger(__name__)

JOB_NAME: Final[str] = "generate_kit"

#: The name of the RUNTIME job that renders a kit and delivers it — ``runtime.jobs``'s
#: ``generate_and_deliver``, which wraps :func:`generate_kit` with delivery and the session
#: un-park. ARQ dispatches by function NAME, so every process that enqueues one and the
#: process that runs them must agree on this exact string, and ``runtime.jobs`` asserts it
#: against the function itself at import.
#:
#: **It lives HERE, in a module that imports nothing from ``bayram.runtime``, to keep an
#: import cycle from existing.** It was defined in ``runtime.jobs`` while that module was the
#: only producer. ``runtime.submitter`` imports it at module scope; ``runtime.jobs`` imports
#: ``runtime.payme_jobs``, which imports ``runtime.render_resume``, which needs the submitter
#: — so with the constant still in ``jobs``, the submitter's import would run while ``jobs``
#: was half-executed and had not yet reached the assignment. The alternative to moving it was
#: for ``render_resume`` to restate the name and hand-roll persist-then-enqueue, which is
#: exactly what ``runtime.submitter``'s docstring forbids: an enqueue that races the write
#: produces a job that cannot find its own order. **The constant moves so that the SEQUENCE
#: is not duplicated.**
KIT_JOB_NAME: Final[str] = "generate_and_deliver"
PIPELINE_CTX_KEY: Final[str] = "pipeline"
REPOSITORY_CTX_KEY: Final[str] = "repository"
SETTINGS_CTX_KEY: Final[str] = "settings"


def job_id_for(order_id: UUID | str) -> str:
    """Deterministic ARQ job id, so one order can only ever be queued once."""
    return f"{JOB_NAME}:{order_id}"


def _require[T](ctx: Mapping[str, Any], key: str, expected: type[T]) -> T:
    value = ctx.get(key)
    if not isinstance(value, expected):
        raise PipelineError(
            f"worker context is missing a usable '{key}'",
            context={"key": key, "found": type(value).__name__},
        )
    return value


def _defer_seconds(ctx: Mapping[str, Any], settings: Settings) -> float:
    attempt = ctx.get("job_try", 1)
    tries = attempt if isinstance(attempt, int) and attempt > 0 else 1
    return settings.provider_backoff_base_s * tries


async def generate_kit(ctx: Mapping[str, Any], order_id: str) -> dict[str, Any]:
    """Build the celebration kit for one order. Returns a JSON-safe summary.

    Raises only ``arq.worker.Retry`` (deliberately, to defer a retryable failure) and
    ``PipelineError`` when the worker was wired up wrong — a startup bug, not a run-time one.
    """
    pipeline = _require(ctx, PIPELINE_CTX_KEY, KitPipeline)
    settings = _require(ctx, SETTINGS_CTX_KEY, Settings)
    repository = ctx.get(REPOSITORY_CTX_KEY)
    if not isinstance(repository, KitRepository):
        raise PipelineError(
            "worker context is missing a usable 'repository'",
            context={"found": type(repository).__name__},
        )

    try:
        identifier = UUID(order_id)
    except ValueError as exc:
        raise PipelineError(
            "job was queued with an order id that is not a UUID",
            context={"order_id": order_id},
            cause=exc,
        ) from exc

    found = await repository.get_order(identifier)
    if isinstance(found, Err):
        _LOGGER.error("order not found for job", extra=found.error.to_log_dict())
        return {"order_id": order_id, "is_delivered": False, "error": found.error.error_code}

    outcome = await pipeline.run(found.value)
    if isinstance(outcome, Err):
        if outcome.error.is_retryable:
            raise Retry(defer=_defer_seconds(ctx, settings))
        return {
            "order_id": order_id,
            "is_delivered": False,
            "error": outcome.error.error_code,
            "user_message_key": outcome.error.user_message_key,
        }

    result = outcome.value
    return {
        "order_id": order_id,
        "is_delivered": True,
        "gaps": len(result.gaps),
        "total_duration_ms": result.total_duration_ms,
        "total_cost_usd": round(result.total_cost_usd, 6),
        "is_name_verified": all(verdict.is_match for verdict in result.name_verdicts),
    }


def build_worker_settings(
    *,
    settings: Settings,
    build_dependencies: Callable[[], Awaitable[Mapping[str, Any]]],
) -> type[Any]:
    """Assemble an ARQ ``WorkerSettings`` class around this project's configuration.

    ``build_dependencies`` returns the providers, repository and pipeline; it is awaited
    once at worker startup so no connection is opened at import time.
    """

    async def startup(ctx: dict[str, Any]) -> None:
        ctx.update(await build_dependencies())
        ctx.setdefault(SETTINGS_CTX_KEY, settings)
        _LOGGER.info("worker started", extra={"concurrency": settings.worker_concurrency})

    class WorkerSettings:
        functions = [generate_kit]
        redis_settings = RedisSettings.from_dsn(settings.redis_url)
        max_jobs = settings.worker_concurrency
        job_timeout = settings.queue_job_timeout_s
        keep_result = settings.queue_result_ttl_s
        on_startup = staticmethod(startup)

    return WorkerSettings
