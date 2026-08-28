"""The queue seam. The ordering here is the bug the parallel build could not see.

The bot builds an ``Order`` and hands it to a submitter; the job's first act is to read
that order back out of the database. Nobody owned the write, so nobody wrote it, and every
job would have failed with "order not found". These tests pin the fix: **persist, then
enqueue**, and never enqueue at all if the write failed.
"""

from __future__ import annotations

import asyncio
from typing import Any
from uuid import UUID

import pytest

from hbd.contracts import Err, Ok, Order, Result, err, ok
from hbd.errors import ConfigError, ErrorCode, StorageError
from hbd.pipeline.worker import job_id_for
from hbd.runtime.jobs import KIT_JOB_NAME
from hbd.runtime.submitter import ArqOrderSubmitter, InProcessOrderSubmitter

CHAT_ID = 555
MESSAGE_ID = 42


class RecordingRepository:
    """Only the one method a submitter is allowed to touch."""

    def __init__(self, *, failure: StorageError | None = None) -> None:
        self.created: list[Order] = []
        self._failure = failure

    async def create_order(self, order: Order) -> Result[Order]:
        if self._failure is not None:
            return err(self._failure)
        self.created.append(order)
        return ok(order)


class FakeJob:
    def __init__(self, job_id: str) -> None:
        self.job_id = job_id


class RecordingRedis:
    """Stands in for ``ArqRedis``, recording exactly what was enqueued."""

    def __init__(self, *, result: FakeJob | None = None, failure: Exception | None = None) -> None:
        self.calls: list[tuple[tuple[Any, ...], dict[str, Any]]] = []
        self._result = result
        self._failure = failure

    async def enqueue_job(self, *args: Any, **kwargs: Any) -> FakeJob | None:
        self.calls.append((args, kwargs))
        if self._failure is not None:
            raise self._failure
        return self._result


# ---------------------------------------------------------------------------
# ArqOrderSubmitter
# ---------------------------------------------------------------------------
async def test_the_order_is_written_before_it_is_enqueued(order: Order) -> None:
    # Arrange
    repository = RecordingRepository()
    redis = RecordingRedis(result=FakeJob("job-1"))
    submitter = ArqOrderSubmitter(redis, repository)  # type: ignore[arg-type]

    # Act
    result = await submitter.submit(order, chat_id=CHAT_ID, progress_message_id=MESSAGE_ID)

    # Assert
    assert isinstance(result, Ok)
    assert repository.created == [order]
    args, kwargs = redis.calls[0]
    assert args == (KIT_JOB_NAME, str(order.id), CHAT_ID, MESSAGE_ID)
    assert kwargs["_job_id"] == job_id_for(order.id)


async def test_nothing_is_enqueued_when_the_order_could_not_be_persisted(order: Order) -> None:
    # Arrange: a job for an unwritten order can only ever fail.
    repository = RecordingRepository(failure=StorageError("database is down"))
    redis = RecordingRedis(result=FakeJob("job-1"))
    submitter = ArqOrderSubmitter(redis, repository)  # type: ignore[arg-type]

    # Act
    result = await submitter.submit(order, chat_id=CHAT_ID, progress_message_id=MESSAGE_ID)

    # Assert
    assert isinstance(result, Err)
    assert redis.calls == []


async def test_a_duplicate_job_id_is_success_not_failure(order: Order) -> None:
    # Arrange: ARQ answers None when the id is already queued — double-tapped Confirm.
    submitter = ArqOrderSubmitter(RecordingRedis(result=None), RecordingRepository())  # type: ignore[arg-type]

    # Act
    result = await submitter.submit(order, chat_id=CHAT_ID, progress_message_id=MESSAGE_ID)

    # Assert
    assert isinstance(result, Ok)
    assert result.value == job_id_for(order.id)


async def test_an_unreachable_redis_is_a_typed_error_not_a_raise(order: Order) -> None:
    # Arrange
    redis = RecordingRedis(failure=OSError("connection refused"))
    submitter = ArqOrderSubmitter(redis, RecordingRepository())  # type: ignore[arg-type]

    # Act
    result = await submitter.submit(order, chat_id=CHAT_ID, progress_message_id=MESSAGE_ID)

    # Assert
    assert isinstance(result, Err)
    assert result.error.error_code is ErrorCode.STORAGE_FAILED


# ---------------------------------------------------------------------------
# InProcessOrderSubmitter
# ---------------------------------------------------------------------------
async def test_the_inline_submitter_runs_the_job_with_the_chat_it_was_given(
    order: Order,
) -> None:
    # Arrange
    seen: list[tuple[str, int, int]] = []

    async def runner(order_id: str, chat_id: int, message_id: int) -> None:
        seen.append((order_id, chat_id, message_id))

    submitter = InProcessOrderSubmitter(RecordingRepository(), runner)  # type: ignore[arg-type]

    # Act
    await submitter.submit(order, chat_id=CHAT_ID, progress_message_id=MESSAGE_ID)
    await submitter.drain()

    # Assert
    assert seen == [(str(order.id), CHAT_ID, MESSAGE_ID)]


async def test_the_inline_submitter_also_persists_before_running(order: Order) -> None:
    # Arrange
    repository = RecordingRepository()
    order_ids: list[UUID] = []

    async def runner(order_id: str, chat_id: int, message_id: int) -> None:
        order_ids.append(UUID(order_id))

    submitter = InProcessOrderSubmitter(repository, runner)  # type: ignore[arg-type]

    # Act
    await submitter.submit(order, chat_id=CHAT_ID, progress_message_id=MESSAGE_ID)
    await submitter.drain()

    # Assert
    assert repository.created == [order]
    assert order_ids == [order.id]


async def test_a_failed_persist_stops_the_inline_run_too(order: Order) -> None:
    # Arrange
    ran = False

    async def runner(order_id: str, chat_id: int, message_id: int) -> None:
        nonlocal ran
        ran = True

    submitter = InProcessOrderSubmitter(
        RecordingRepository(failure=StorageError("nope")),  # type: ignore[arg-type]
        runner,
    )

    # Act
    result = await submitter.submit(order, chat_id=CHAT_ID, progress_message_id=MESSAGE_ID)
    await submitter.drain()

    # Assert
    assert isinstance(result, Err)
    assert not ran


async def test_a_crashing_job_is_logged_rather_than_taking_the_bot_down(order: Order) -> None:
    # Arrange: a background task that dies silently is how a bot stops answering.
    async def runner(order_id: str, chat_id: int, message_id: int) -> None:
        raise RuntimeError("the pipeline exploded")

    submitter = InProcessOrderSubmitter(RecordingRepository(), runner)  # type: ignore[arg-type]

    # Act
    result = await submitter.submit(order, chat_id=CHAT_ID, progress_message_id=MESSAGE_ID)
    await submitter.drain()

    # Assert: the submit itself succeeded and the process is still standing.
    assert isinstance(result, Ok)
    assert submitter.in_flight == 0


async def test_the_task_set_does_not_grow_for_the_life_of_the_process(order: Order) -> None:
    # Arrange
    async def runner(order_id: str, chat_id: int, message_id: int) -> None:
        await asyncio.sleep(0)

    submitter = InProcessOrderSubmitter(RecordingRepository(), runner)  # type: ignore[arg-type]

    # Act
    for _ in range(5):
        await submitter.submit(order, chat_id=CHAT_ID, progress_message_id=MESSAGE_ID)
    await submitter.drain()

    # Assert
    assert submitter.in_flight == 0


def test_the_inline_submitter_is_refused_in_production() -> None:
    # Arrange / Act / Assert: one process quietly doing the work of a fleet is not a plan.
    async def runner(order_id: str, chat_id: int, message_id: int) -> None:
        return None

    with pytest.raises(ConfigError, match="production"):
        InProcessOrderSubmitter(
            RecordingRepository(),  # type: ignore[arg-type]
            runner,
            is_production=True,
        )
