"""The queue seam: thin, deterministic, and retry-safe."""

from __future__ import annotations

from typing import Any
from uuid import uuid4

import pytest
from arq.worker import Retry

from hbd.config import Settings
from hbd.contracts import Order
from hbd.errors import ErrorCode, PipelineError, StorageError
from hbd.pipeline.worker import (
    JOB_NAME,
    PIPELINE_CTX_KEY,
    REPOSITORY_CTX_KEY,
    build_worker_settings,
    generate_kit,
    job_id_for,
)
from tests.conftest import make_brief, make_order
from tests.test_pipeline.conftest import Studio


def _ctx(studio: Studio) -> dict[str, Any]:
    return {
        PIPELINE_CTX_KEY: studio.pipeline(),
        REPOSITORY_CTX_KEY: studio.repository,
        "settings": studio.settings,
        "job_try": 1,
    }


async def test_returns_a_delivered_summary(studio: Studio, ready_order: Order) -> None:
    # Arrange
    ctx = _ctx(studio)

    # Act
    summary = await generate_kit(ctx, str(ready_order.id))

    # Assert
    assert summary["is_delivered"] is True
    assert summary["gaps"] == 0
    assert summary["is_name_verified"] is True
    assert summary["total_cost_usd"] > 0


async def test_reports_gaps_in_the_summary(studio: Studio, ready_order: Order) -> None:
    # Arrange
    studio.tts.failing_personas = {"persona-2"}

    # Act
    summary = await generate_kit(_ctx(studio), str(ready_order.id))

    # Assert
    assert summary["is_delivered"] is True
    assert summary["gaps"] == 1


async def test_defers_the_job_when_the_failure_is_retryable(
    studio: Studio, ready_order: Order
) -> None:
    # Arrange
    studio.repository.save_failures = [
        StorageError("db down"),
        StorageError("db still down"),
    ]

    # Act / Assert
    with pytest.raises(Retry):
        await generate_kit(_ctx(studio), str(ready_order.id))


async def test_does_not_defer_a_terminal_failure(studio: Studio) -> None:
    # Arrange
    order = studio.enrol(make_order(brief=make_brief(note="I will kill him")))

    # Act
    summary = await generate_kit(_ctx(studio), str(order.id))

    # Assert
    assert summary["is_delivered"] is False
    assert summary["error"] is ErrorCode.CONTENT_REJECTED
    assert summary["user_message_key"] == "error.content_not_allowed"


async def test_reports_an_unknown_order_without_raising(studio: Studio) -> None:
    # Arrange
    missing = uuid4()

    # Act
    summary = await generate_kit(_ctx(studio), str(missing))

    # Assert
    assert summary["is_delivered"] is False


async def test_rejects_a_job_queued_with_a_non_uuid(studio: Studio) -> None:
    # Arrange / Act / Assert
    with pytest.raises(PipelineError):
        await generate_kit(_ctx(studio), "not-a-uuid")


async def test_rejects_a_worker_that_was_wired_up_without_a_pipeline(
    studio: Studio, ready_order: Order
) -> None:
    # Arrange
    ctx = _ctx(studio)
    del ctx[PIPELINE_CTX_KEY]

    # Act / Assert
    with pytest.raises(PipelineError):
        await generate_kit(ctx, str(ready_order.id))


async def test_rejects_a_worker_without_a_repository(studio: Studio, ready_order: Order) -> None:
    # Arrange
    ctx = _ctx(studio)
    ctx[REPOSITORY_CTX_KEY] = object()

    # Act / Assert
    with pytest.raises(PipelineError):
        await generate_kit(ctx, str(ready_order.id))


def test_job_ids_are_deterministic_per_order() -> None:
    # Arrange
    order_id = uuid4()

    # Act / Assert
    assert job_id_for(order_id) == job_id_for(str(order_id))
    assert job_id_for(order_id).startswith(f"{JOB_NAME}:")


async def test_worker_settings_carry_the_projects_limits(settings: Settings) -> None:
    # Arrange
    async def dependencies() -> dict[str, Any]:
        return {"marker": True}

    # Act
    worker = build_worker_settings(settings=settings, build_dependencies=dependencies)
    ctx: dict[str, Any] = {}
    await worker.on_startup(ctx)

    # Assert
    assert worker.max_jobs == settings.worker_concurrency
    assert worker.job_timeout == settings.queue_job_timeout_s
    assert generate_kit in worker.functions
    assert ctx["marker"] is True
    assert ctx["settings"] is settings
