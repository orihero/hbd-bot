"""Two ways to hand a finished order to the generator, behind one protocol.

Both do the same two things, in the same order, and the order matters: **persist, then
enqueue.** The job receives an order *id*, and its first act is to read that order back
out of the database. An enqueue that races the write produces a job that cannot find its
own order — which is exactly the failure the bot layer could not see, because it holds no
repository by design.

* :class:`ArqOrderSubmitter` is production: Redis, a deterministic job id, and ARQ's own
  refusal to queue a duplicate id, so double-tapping Confirm costs nothing.
* :class:`InProcessOrderSubmitter` runs the job as a background task in the bot process.
  It exists so the whole product can be demonstrated with no Redis and no worker — one
  command, one terminal — and it is refused outright in production.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import Final
from uuid import UUID

from arq import ArqRedis

from hbd.contracts import Err, KitRepository, Order, Result, err, ok
from hbd.errors import ConfigError, StorageError
from hbd.logging import get_logger
from hbd.pipeline.worker import job_id_for
from hbd.runtime.jobs import KIT_JOB_NAME

__all__ = ["ArqOrderSubmitter", "InProcessOrderSubmitter", "JobRunner"]

_LOG = get_logger(__name__)

#: What an in-process run is handed back instead of an ARQ job handle.
_INLINE_HANDLE: Final[str] = "inline"

#: ``(order_id, chat_id, progress_message_id) -> None``. What the queue would have called.
type JobRunner = Callable[[str, int, int], Awaitable[None]]


async def _persist(repository: KitRepository, order: Order) -> Result[Order]:
    """Write the order before anyone can be asked to read it."""
    created = await repository.create_order(order)
    if isinstance(created, Err):
        _LOG.error("order could not be persisted", extra=created.error.to_log_dict())
    return created


class ArqOrderSubmitter:
    """Persists the order, then enqueues it. Satisfies ``hbd.bot.ports.OrderSubmitter``."""

    def __init__(self, redis: ArqRedis, repository: KitRepository) -> None:
        self._redis = redis
        self._repository = repository

    async def submit(self, order: Order, *, chat_id: int, progress_message_id: int) -> Result[str]:
        created = await _persist(self._repository, order)
        if isinstance(created, Err):
            return created

        job_id = job_id_for(order.id)
        try:
            job = await self._redis.enqueue_job(
                KIT_JOB_NAME,
                str(order.id),
                chat_id,
                progress_message_id,
                _job_id=job_id,
            )
        except (TimeoutError, OSError) as exc:
            return err(
                StorageError(
                    "could not reach Redis to enqueue the order",
                    context={"order_id": str(order.id), "job_id": job_id},
                    cause=exc,
                )
            )
        if job is None:
            # ARQ returns None when the id is already queued. That is the idempotency
            # guarantee doing its job, not a failure: the first press is already running.
            _LOG.info(
                "order was already queued; ignoring the duplicate",
                extra={"order_id": str(order.id), "job_id": job_id},
            )
            return ok(job_id)
        return ok(job.job_id)


class InProcessOrderSubmitter:
    """Runs the job inline, in a background task. Demo and local development only."""

    def __init__(
        self,
        repository: KitRepository,
        runner: JobRunner,
        *,
        is_production: bool = False,
    ) -> None:
        if is_production:
            raise ConfigError(
                "the in-process submitter cannot run in production; configure Redis and "
                "run the ARQ worker instead",
                context={"submitter": type(self).__name__},
            )
        self._repository = repository
        self._runner = runner
        self._tasks: set[asyncio.Task[None]] = set()

    @property
    def in_flight(self) -> int:
        return len(self._tasks)

    async def submit(self, order: Order, *, chat_id: int, progress_message_id: int) -> Result[str]:
        created = await _persist(self._repository, order)
        if isinstance(created, Err):
            return created

        task = asyncio.create_task(
            self._run(order.id, chat_id, progress_message_id),
            name=f"{KIT_JOB_NAME}:{order.id}",
        )
        # Held so the loop cannot garbage-collect a running task mid-flight, and
        # discarded on completion so the set does not grow for the life of the process.
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
        return ok(_INLINE_HANDLE)

    async def drain(self) -> None:
        """Wait for every in-flight job. Used by the demo; harmless anywhere else."""
        if self._tasks:
            await asyncio.gather(*tuple(self._tasks), return_exceptions=True)

    async def _run(self, order_id: UUID, chat_id: int, progress_message_id: int) -> None:
        """A background task must never die silently, so its failure is logged in full."""
        try:
            await self._runner(str(order_id), chat_id, progress_message_id)
        except Exception:
            _LOG.exception(
                "in-process job failed",
                extra={"order_id": str(order_id), "chat_id": chat_id},
            )
