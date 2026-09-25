"""The stage chain on a backend that bills per call (IMAGE_VIDEO_SPEC §4.3, §10 M6.1).

Over the fakes of ``media_fakes``, with the job re-stamped onto ``higgsfield`` the way the
reconcile tests do it — the adapter itself is ``tests/test_media/test_higgsfield.py``:

* **the per-request ceiling covers every variant and every retry**: each attempt's
  ``/estimate`` is recorded with it, and an attempt that would take the request past
  ``image_max_cost_usd`` is never posted;
* an estimate that cannot be read refuses the POST — an unknown cost is not zero;
* the vendor's own moderation (``nsfw``) is a refusal with one credit, never a retry, and on
  an image request it fails the whole request (Q3's rule for our own block);
* a paid backend's clip is normalised to the job's exact geometry (Kling drifts); the local
  gateway's is not asked to be.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import timedelta
from pathlib import Path
from uuid import UUID, uuid4

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
from bayram.contracts import CostSource, Language
from bayram.db.engine import create_session_factory
from bayram.db.enums import (
    MediaAspect,
    MediaAttemptStatus,
    MediaBackend,
    MediaCreditReason,
    MediaJobState,
    MediaKind,
    MediaPaidVia,
    MediaSku,
    MediaTier,
    MediaVoiceMode,
)
from bayram.db.media import create_job, load_job, mark_paid, media_balance
from bayram.db.models import Base, UserRow
from bayram.db.models.media_attempt import MediaAttemptRow
from bayram.db.models.media_credit import MediaCreditLedgerRow
from bayram.db.models.media_job import MediaJobRow
from bayram.errors import ProviderUnavailableError
from bayram.media.contracts import JobPhase
from bayram.media.stages import (
    MEDIA_SCREEN_JOB,
    MEDIA_START_JOB,
    MEDIA_SUBMIT_JOB,
    screen_job_id,
    sku_deadline,
)
from tests.conftest import FIXED_NOW
from tests.test_runtime.media_fakes import (
    PROMPT,
    TRAY_ID,
    USER,
    Harness,
    build_harness,
    freeze_job,
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
    return build_harness(
        media_settings(
            settings,
            is_video_standard_offered=True,
            video_standard_backend="fake",
            image_max_cost_usd=0.20,
            video_fast_max_cost_usd=1.00,
        ),
        sessions,
        tmp_path,
        FIXED_NOW,
    )


async def _job(harness: Harness, job_id: UUID) -> MediaJobRow:
    async with harness.sessions() as session:
        job = await load_job(session, job_id)
    assert job is not None
    return job


async def _video_job(harness: Harness) -> UUID:
    """A silent Standard video in ``screening``, as the bot's ✅ Done leaves it (§2.4)."""
    async with harness.sessions.begin() as session:
        existing = await session.scalar(
            sa.select(UserRow.id).where(UserRow.telegram_user_id == USER)
        )
        user_id = existing if existing is not None else uuid4()
        if existing is None:
            session.add(UserRow(id=user_id, telegram_user_id=USER))
            await session.flush()
        return await create_job(
            session,
            user_id=user_id,
            telegram_user_id=USER,
            kind=MediaKind.VIDEO,
            sku=MediaSku.VIDEO_STANDARD,
            state=MediaJobState.SCREENING,
            chat_id=USER,
            outputs_requested=1,
            aspect=MediaAspect.PORTRAIT,
            language=Language.EN,
            prompt=PROMPT,
            price_minor=2_500_000,
            currency="UZS",
            now=harness.clock(),
            quote_ttl=timedelta(seconds=86_400),
            tier=MediaTier.STANDARD,
            voice_mode=MediaVoiceMode.NONE,
            tray_message_id=TRAY_ID,
        )


async def _paid(
    harness: Harness, *, kind: MediaKind = MediaKind.IMAGE, higgsfield: bool = True
) -> UUID:
    """Screen, quote, pay on Payme, start — and, for ``higgsfield``, re-stamp the job onto the
    paid backend before any submit runs, as an operator override would have (§4.5)."""
    if kind is MediaKind.IMAGE:
        job_id = await freeze_job(harness, photos=())
    else:
        job_id = await _video_job(harness)
    await harness.queue.enqueue_job(MEDIA_SCREEN_JOB, str(job_id), 0, _job_id=screen_job_id(job_id))
    await harness.drain()
    assert (await _job(harness, job_id)).state is MediaJobState.QUOTED
    async with harness.sessions.begin() as session:
        job = await load_job(session, job_id)
        assert job is not None
        assert await mark_paid(
            session,
            job_id,
            paid_via=MediaPaidVia.PAYME,
            now=harness.clock(),
            deadline=sku_deadline(harness.rt.settings, job.sku),
            expected=(MediaJobState.QUOTED,),
        )
    await harness.queue.enqueue_job(
        MEDIA_START_JOB, str(job_id), 0, _job_id=f"media:{job_id}:start:0"
    )
    if not higgsfield:
        return job_id
    await harness.drain(stop=lambda stage: stage.name == MEDIA_SUBMIT_JOB)
    async with harness.sessions.begin() as session:
        await session.execute(
            sa.update(MediaJobRow)
            .where(MediaJobRow.id == job_id)
            .values(backend=MediaBackend.HIGGSFIELD)
        )
    return job_id


async def _attempts(harness: Harness, job_id: UUID) -> list[MediaAttemptRow]:
    async with harness.sessions() as session:
        rows = await session.scalars(
            sa.select(MediaAttemptRow)
            .where(MediaAttemptRow.job_id == job_id)
            .order_by(MediaAttemptRow.variant, MediaAttemptRow.attempt)
        )
        return list(rows.all())


async def _refunds(harness: Harness, job_id: UUID) -> list[MediaCreditReason]:
    async with harness.sessions() as session:
        rows = await session.scalars(
            sa.select(MediaCreditLedgerRow.reason).where(MediaCreditLedgerRow.job_id == job_id)
        )
        return list(rows.all())


# ---------------------------------------------------------------------------
# §4.3: estimate before every POST, and the per-request ceiling
# ---------------------------------------------------------------------------
async def test_each_posted_attempt_records_its_estimate(harness: Harness) -> None:
    harness.hooked.estimate_usd = 0.05
    job_id = await _paid(harness)

    await harness.drain()

    attempts = await _attempts(harness, job_id)
    assert [(row.variant, row.attempt) for row in attempts] == [(0, 1), (1, 1)]
    assert all(row.cost_usd == pytest.approx(0.05) for row in attempts)
    assert all(row.cost_source is CostSource.ESTIMATED for row in attempts)
    assert (await _job(harness, job_id)).state is MediaJobState.DELIVERED


async def test_a_retry_that_would_cross_the_request_ceiling_is_never_posted(
    harness: Harness,
) -> None:
    # Arrange — two images at $0.08 fit the $0.20 ceiling; a third render would not.
    harness.hooked.estimate_usd = 0.08
    harness.provider.outcome = JobPhase.FAILED
    job_id = await _paid(harness)

    # Act
    await harness.drain()

    # Assert — both first attempts posted, neither retry was: the chain stopped at $0.16.
    assert len(harness.provider.submits) == 2
    retries = [row for row in await _attempts(harness, job_id) if row.attempt == 2]
    assert len(retries) == 2
    assert all(row.status is MediaAttemptStatus.FAILED for row in retries)
    assert all(row.error_code == "cost_ceiling" and row.cost_usd is None for row in retries)
    job = await _job(harness, job_id)
    assert job.state is MediaJobState.FAILED and job.error_code == "generation_failed"
    async with harness.sessions() as session:
        assert await media_balance(session, telegram_user_id=USER, sku=job.sku) == 1


async def test_an_estimate_above_the_ceiling_posts_nothing(harness: Harness) -> None:
    harness.hooked.estimate_usd = 0.25
    job_id = await _paid(harness)

    await harness.drain()

    assert harness.provider.submits == []
    job = await _job(harness, job_id)
    assert job.state is MediaJobState.FAILED
    assert await _refunds(harness, job_id) == [MediaCreditReason.GENERATION_FAILED]


async def test_an_unreadable_estimate_posts_nothing(harness: Harness) -> None:
    harness.hooked.estimate_error = ProviderUnavailableError("estimate down", provider="fake")
    job_id = await _paid(harness)

    await harness.drain()

    assert harness.provider.submits == []
    assert harness.hooked.estimates >= 2
    assert (await _job(harness, job_id)).state is MediaJobState.FAILED


async def test_the_local_gpu_is_never_asked_for_an_estimate(harness: Harness) -> None:
    job_id = await _paid(harness, higgsfield=False)
    harness.hooked.estimates = 0

    await harness.drain()

    assert harness.hooked.estimates == 0
    assert all(row.cost_usd is None for row in await _attempts(harness, job_id))


# ---------------------------------------------------------------------------
# §4.3: the vendor's moderation is a refusal, refunded, never retried
# ---------------------------------------------------------------------------
async def test_a_provider_content_refusal_fails_the_whole_image_request_with_one_credit(
    harness: Harness,
) -> None:
    harness.provider.outcome = JobPhase.REJECTED_CONTENT
    job_id = await _paid(harness)

    await harness.drain()

    assert len(harness.provider.submits) == 2  # one per variant; neither retried
    job = await _job(harness, job_id)
    assert job.state is MediaJobState.FAILED and job.error_code == "provider_rejected"
    assert await _refunds(harness, job_id) == [MediaCreditReason.OUTPUT_BLOCKED]
    assert harness.messenger.albums == []


async def test_a_provider_content_refusal_of_a_video_is_refunded_as_a_block(
    harness: Harness,
) -> None:
    harness.provider.outcome = JobPhase.REJECTED_CONTENT
    job_id = await _paid(harness, kind=MediaKind.VIDEO)

    await harness.drain()

    assert len(harness.provider.submits) == 1
    job = await _job(harness, job_id)
    assert job.state is MediaJobState.FAILED and job.error_code == "provider_rejected"
    assert await _refunds(harness, job_id) == [MediaCreditReason.OUTPUT_BLOCKED]
    assert harness.messenger.videos == []


# ---------------------------------------------------------------------------
# §4.3: a paid backend's geometry is measured and normalised; the GPU's is not asked
# ---------------------------------------------------------------------------
async def test_a_paid_backends_clip_is_normalised_to_the_jobs_exact_size(
    harness: Harness,
) -> None:
    job_id = await _paid(harness, kind=MediaKind.VIDEO)

    await harness.drain()

    assert harness.video.normalise_targets == [(720, 1280)]
    assert (await _job(harness, job_id)).state is MediaJobState.DELIVERED


async def test_the_local_gateways_clip_keeps_the_size_it_was_asked_for(harness: Harness) -> None:
    await _paid(harness, kind=MediaKind.VIDEO, higgsfield=False)

    await harness.drain()

    assert harness.video.normalise_targets == [None]
