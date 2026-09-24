"""``media_sweep``: the only backstop the media chain has (IMAGE_VIDEO_SPEC §3.3, §3.4, §2.6).

Each arm is driven by what a lost enqueue or a dead worker leaves behind, and each re-enqueue
must use a NEW id — the harness queue drops a seen one, as ARQ does.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path
from uuid import uuid4

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import StaticPool

from bayram.config import Settings
from bayram.db.engine import create_session_factory
from bayram.db.enums import MediaAttemptStage, MediaAttemptStatus, MediaJobState, MediaPaidVia
from bayram.db.media import insert_attempt, load_job, mark_paid, transition
from bayram.db.models import Base
from bayram.db.models.media_attempt import MediaAttemptRow
from bayram.db.models.media_input import MediaInputRow
from bayram.db.models.media_job import MediaJobRow
from bayram.media.stages import MEDIA_SCREEN_JOB, MEDIA_START_JOB, screen_job_id, sku_deadline
from bayram.runtime.gpu_lock import queue_member, queue_score
from bayram.runtime.media_sweep import sweep_media
from bayram.runtime.workspace_sweep import finished_media_jobs_lookup
from tests.conftest import FIXED_NOW
from tests.test_runtime.media_fakes import (
    Harness,
    build_harness,
    freeze_job,
    jpeg_bytes,
    media_settings,
)


@pytest.fixture
async def engine() -> AsyncIterator[AsyncEngine]:
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    yield engine
    await engine.dispose()


@pytest.fixture
def sessions(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return create_session_factory(engine)


@pytest.fixture
def harness(
    settings: Settings, sessions: async_sessionmaker[AsyncSession], tmp_path: Path
) -> Harness:
    return build_harness(media_settings(settings), sessions, tmp_path, FIXED_NOW)


async def _state(harness: Harness, job_id: object) -> MediaJobState:
    async with harness.sessions() as session:
        job = await load_job(session, job_id)  # type: ignore[arg-type]
    assert job is not None
    return job.state


async def _quoted(harness: Harness) -> object:
    job_id = await freeze_job(harness, photos=())
    await harness.queue.enqueue_job(MEDIA_SCREEN_JOB, str(job_id), 0, _job_id=screen_job_id(job_id))
    await harness.drain()
    assert await _state(harness, job_id) is MediaJobState.QUOTED
    return job_id


async def _paid_without_start(harness: Harness, via: MediaPaidVia = MediaPaidVia.BETA) -> object:
    job_id = await _quoted(harness)
    async with harness.sessions.begin() as session:
        job = await load_job(session, job_id)  # type: ignore[arg-type]
        assert job is not None
        await mark_paid(
            session,
            job.id,
            paid_via=via,
            now=harness.clock(),
            deadline=sku_deadline(harness.rt.settings, job.sku),
            expected=(MediaJobState.QUOTED,),
        )
    return job_id


async def test_a_stale_quote_is_abandoned_and_its_uploads_deleted(harness: Harness) -> None:
    job_id = await freeze_job(harness, photos=[jpeg_bytes()])
    await harness.queue.enqueue_job(MEDIA_SCREEN_JOB, str(job_id), 0, _job_id=screen_job_id(job_id))
    await harness.drain()
    fresh = await freeze_job(harness, photos=(), user=4_440_000_001)

    harness.clock.advance(seconds=harness.rt.settings.media_quote_ttl_s + 1)
    async with harness.sessions.begin() as session:
        # The fresh one was frozen "just now".
        await session.execute(
            sa.update(MediaJobRow).where(MediaJobRow.id == fresh).values(created_at=harness.clock())
        )
    summary = await sweep_media(harness.rt)
    await harness.drain()

    assert summary["abandoned"] == 1
    assert await _state(harness, job_id) is MediaJobState.ABANDONED
    assert await _state(harness, fresh) is MediaJobState.SCREENING
    async with harness.sessions() as session:
        left = await session.scalar(
            sa.select(sa.func.count())
            .select_from(MediaInputRow)
            .where(MediaInputRow.job_id == job_id)
        )
    assert left == 0


async def test_an_awaiting_payment_row_with_no_intent_waits_out_the_intent_lifetime(
    harness: Harness,
) -> None:
    job_id = await _quoted(harness)
    async with harness.sessions.begin() as session:
        await transition(
            session,
            job_id,  # type: ignore[arg-type]
            expected=(MediaJobState.QUOTED,),
            to=MediaJobState.AWAITING_PAYMENT,
            now=harness.clock(),
        )

    harness.clock.advance(seconds=harness.rt.settings.payme_intent_ttl_s)
    assert (await sweep_media(harness.rt))["abandoned"] == 0
    harness.clock.advance(minutes=11)
    assert (await sweep_media(harness.rt))["abandoned"] == 1
    assert await _state(harness, job_id) is MediaJobState.ABANDONED


async def test_a_paid_row_nothing_started_is_started_under_a_fresh_id(harness: Harness) -> None:
    job_id = await _paid_without_start(harness)
    # The payment path's own enqueue ran once and was lost; its id is still "remembered".
    harness.queue.seen.add(f"media:{job_id}:start:0")

    assert (await sweep_media(harness.rt))["started"] == 0  # too young: the payer may yet start it
    harness.clock.advance(minutes=3)
    summary = await sweep_media(harness.rt)
    await harness.drain()

    assert summary["started"] == 1
    assert await _state(harness, job_id) is MediaJobState.DELIVERED
    starts = [stage.job_id for stage in harness.queue.ran_named(MEDIA_START_JOB)]
    assert starts and all(not sid.endswith(":start:0") for sid in starts)


async def test_a_chain_whose_enqueue_was_lost_is_re_driven(harness: Harness) -> None:
    job_id = await _paid_without_start(harness)
    await harness.queue.enqueue_job(
        MEDIA_START_JOB, str(job_id), 0, _job_id=f"media:{job_id}:start:0"
    )
    await harness.drain(stop=lambda stage: stage.name == "media_submit")
    lost = list(harness.queue.pending)
    harness.queue.pending.clear()  # Redis lost both submits after the start committed.
    assert lost and await _state(harness, job_id) is MediaJobState.QUEUED

    harness.clock.advance(minutes=4)
    summary = await sweep_media(harness.rt)
    await harness.drain()

    assert summary["redriven"] >= 1
    assert await _state(harness, job_id) is MediaJobState.DELIVERED
    assert len(harness.provider.submits) == 2


async def test_a_screen_that_never_answered_is_run_again(harness: Harness) -> None:
    job_id = await freeze_job(harness, photos=())
    harness.clock.advance(minutes=11)

    await sweep_media(harness.rt)
    await harness.drain()

    assert await _state(harness, job_id) is MediaJobState.QUOTED


async def test_gpu_hygiene_drops_finished_members_and_frees_a_dead_submitters_lock(
    harness: Harness,
) -> None:
    job_id = await _paid_without_start(harness)
    stray = uuid4()
    await harness.gpu.join(queue_member(stray, 0), queue_score(harness.clock(), 0))
    attempt_id = uuid4()
    async with harness.sessions.begin() as session:
        await insert_attempt(
            session,
            job_id=job_id,  # type: ignore[arg-type]
            stage=MediaAttemptStage.IMAGE,
            variant=0,
            attempt=1,
            provider="fake_media",
            now=harness.clock(),
            attempt_id=attempt_id,
        )
    harness.gpu.now_ms = 0
    await harness.gpu.acquire(str(attempt_id), ttl_ms=10**9)

    harness.clock.advance(minutes=6)
    summary = await sweep_media(harness.rt)

    assert summary["gpu_fixed"] == 2
    assert await harness.gpu.members() == ()
    assert await harness.gpu.holder() is None
    async with harness.sessions() as session:
        row = await session.get(MediaAttemptRow, attempt_id)
    assert row is not None and row.status is MediaAttemptStatus.AMBIGUOUS


async def test_the_workspace_lookup_finishes_terminal_and_missing_jobs_only(
    harness: Harness,
) -> None:
    live = await freeze_job(harness, photos=())
    done = await freeze_job(harness, photos=(), user=4_440_000_002)
    async with harness.sessions.begin() as session:
        await transition(
            session,
            done,
            expected=(MediaJobState.SCREENING,),
            to=MediaJobState.REJECTED,
            now=harness.clock(),
        )
    gone = uuid4()

    finished = await finished_media_jobs_lookup(harness.sessions)(frozenset({live, done, gone}))

    assert finished == frozenset({done, gone})


async def test_a_paid_job_is_not_failed_before_its_deadline(harness: Harness) -> None:
    job_id = await _paid_without_start(harness, via=MediaPaidVia.PAYME)
    harness.clock.advance(seconds=harness.rt.settings.media_image_deadline_s - 60)

    summary = await sweep_media(harness.rt)

    assert summary["deadline_failed"] == 0
    harness.clock.advance(seconds=120)
    assert (await sweep_media(harness.rt))["deadline_failed"] == 1
    assert await _state(harness, job_id) is MediaJobState.FAILED
