"""The media runtime is built once per worker, not once per job.

ARQ runs each job on ``{**worker.ctx, job_id, ...}``, a fresh dict. The runtime cached into
that copy died with the job, so every stage built its own provider cache, and a stateful
adapter (the fake) answered ``media_poll`` for a job ``media_submit`` had given to another
instance. The poll read "unknown" and every request failed as an ambiguous submit. Found in
the owner's live review on 2026-09-26.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import pytest
from aiogram import Bot

from bayram.config import Settings
from bayram.db.enums import MediaBackend
from bayram.runtime.container import AppContainer, build_container
from bayram.runtime.media_jobs import MEDIA_CTX_KEY, media_runtime, prime_media_runtime


@pytest.fixture
async def container(tmp_path: Path) -> AsyncIterator[AppContainer]:
    built = await build_container(
        Settings(
            _env_file=None,
            telegram_bot_token="t",
            database_url=f"sqlite+aiosqlite:///{tmp_path / 'prime.db'}",
            elevenlabs_api_key="k",
            llm_api_key="k",
            use_fake_providers=True,
        ),
        data_root=tmp_path / "var",
        with_providers=False,
    )
    yield built
    await built.aclose()


def _worker_ctx(container: AppContainer) -> dict[str, Any]:
    return {"container": container, "bot": Bot(token="123:abc"), "redis": object()}


def _job_ctx(worker_ctx: dict[str, Any], job_id: str) -> dict[str, Any]:
    """What ARQ's ``run_job`` hands a job: a shallow copy plus the job's own keys."""
    return {**worker_ctx, "job_id": job_id, "job_try": 1}


async def test_two_jobs_share_one_runtime_and_one_provider(container: AppContainer) -> None:
    worker_ctx = _worker_ctx(container)
    prime_media_runtime(worker_ctx)

    submit_rt = media_runtime(_job_ctx(worker_ctx, "submit"))
    poll_rt = media_runtime(_job_ctx(worker_ctx, "poll"))

    assert submit_rt is poll_rt
    assert submit_rt.providers(MediaBackend.LOCAL) is poll_rt.providers(MediaBackend.LOCAL)


async def test_without_priming_each_job_builds_its_own(container: AppContainer) -> None:
    """The defect, pinned: the job copy's cache write never reaches the worker's dict."""
    worker_ctx = _worker_ctx(container)

    first = media_runtime(_job_ctx(worker_ctx, "a"))
    second = media_runtime(_job_ctx(worker_ctx, "b"))

    assert first is not second
    assert MEDIA_CTX_KEY not in worker_ctx


async def test_priming_is_idempotent(container: AppContainer) -> None:
    worker_ctx = _worker_ctx(container)
    prime_media_runtime(worker_ctx)
    runtime = worker_ctx[MEDIA_CTX_KEY]
    prime_media_runtime(worker_ctx)
    assert worker_ctx[MEDIA_CTX_KEY] is runtime


def test_a_context_without_a_container_is_left_alone() -> None:
    ctx: dict[str, Any] = {}
    prime_media_runtime(ctx)
    assert MEDIA_CTX_KEY not in ctx
