"""The M2 review's stage-chain findings, each pinned (IMAGE_VIDEO_SPEC §3.3–§3.5, §4.2, §9.3).

* an ambiguous attempt is reconciled against the gateway's ``GET /queue`` before anything is
  resubmitted, holding the GPU slot while its render may still be there (§4.2, §3.4);
* a paid backend never re-posts an ambiguous submit: the job is held (§4.3);
* a job whose every submit failed fails at once, not at its deadline (§3.3 fan-in);
* the quote refuses an unhealthy backend and counts the gateway's non-bayram backlog (§7.2
  step 1, §3.4, NFR-20);
* ``/forget`` during a render leaves no output behind, and a forgotten job is never refunded
  (§9.3);
* ``BAYRAM_RETENTION_MEDIA_OUTPUT_DAYS`` reaches the rows the worker writes (§9.5).
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import timedelta
from pathlib import Path
from uuid import UUID

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
from bayram.contracts import Err, HealthState, err
from bayram.db.engine import create_session_factory
from bayram.db.enums import MediaAttemptStatus, MediaBackend, MediaJobState, MediaPaidVia
from bayram.db.media import load_job, mark_paid, media_balance
from bayram.db.media_erasure import SqlMediaEraser
from bayram.db.models import Base
from bayram.db.models.media_attempt import MediaAttemptRow
from bayram.db.models.media_credit import MediaCreditLedgerRow
from bayram.db.models.media_input import MediaOutputRow
from bayram.db.models.media_job import MediaJobRow
from bayram.errors import ProviderAmbiguousError, ProviderUnavailableError
from bayram.media.contracts import JobPhase, MediaRequest, QueuedJob
from bayram.media.stages import (
    MEDIA_CLEANUP_JOB,
    MEDIA_FETCH_JOB,
    MEDIA_POLL_JOB,
    MEDIA_SCREEN_JOB,
    MEDIA_START_JOB,
    MEDIA_SUBMIT_JOB,
    screen_job_id,
    sku_deadline,
)
from bayram.providers.media.local_gateway import CLIENT_TAG
from tests.conftest import FIXED_NOW
from tests.test_runtime.media_fakes import (
    USER,
    Harness,
    QueuedStage,
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
    return build_harness(media_settings(settings), sessions, tmp_path, FIXED_NOW)


async def _job(harness: Harness, job_id: UUID) -> MediaJobRow:
    async with harness.sessions() as session:
        job = await load_job(session, job_id)
    assert job is not None
    return job


async def _screen(harness: Harness, job_id: UUID) -> None:
    await harness.queue.enqueue_job(MEDIA_SCREEN_JOB, str(job_id), 0, _job_id=screen_job_id(job_id))
    await harness.drain()


async def _quoted_and_paid(
    harness: Harness, *, via: MediaPaidVia = MediaPaidVia.PAYME, start: bool = True
) -> UUID:
    job_id = await freeze_job(harness, photos=())
    await _screen(harness, job_id)
    assert (await _job(harness, job_id)).state is MediaJobState.QUOTED
    async with harness.sessions.begin() as session:
        job = await load_job(session, job_id)
        assert job is not None
        assert await mark_paid(
            session,
            job_id,
            paid_via=via,
            now=harness.clock(),
            deadline=sku_deadline(harness.rt.settings, job.sku),
            expected=(MediaJobState.QUOTED,),
        )
    if start:
        await harness.queue.enqueue_job(
            MEDIA_START_JOB, str(job_id), 0, _job_id=f"media:{job_id}:start:0"
        )
    return job_id


async def _run(harness: Harness, runs: int) -> None:
    """Run at most ``runs`` stages — for a chain that deliberately does not settle."""
    count = {"n": 0}

    def enough(stage: QueuedStage) -> bool:
        count["n"] += 1
        return count["n"] > runs

    await harness.drain(stop=enough)


async def _attempts(harness: Harness, job_id: UUID, variant: int) -> list[MediaAttemptRow]:
    async with harness.sessions() as session:
        return list(
            (
                await session.scalars(
                    sa.select(MediaAttemptRow)
                    .where(MediaAttemptRow.job_id == job_id, MediaAttemptRow.variant == variant)
                    .order_by(MediaAttemptRow.attempt)
                )
            ).all()
        )


async def _ledger(harness: Harness, job_id: UUID) -> list[MediaCreditLedgerRow]:
    async with harness.sessions() as session:
        return list(
            (
                await session.scalars(
                    sa.select(MediaCreditLedgerRow).where(MediaCreditLedgerRow.job_id == job_id)
                )
            ).all()
        )


# ---------------------------------------------------------------------------
# §4.2: an ambiguous attempt is reconciled before anything is resubmitted
# ---------------------------------------------------------------------------
async def test_an_ambiguous_submit_whose_job_is_on_the_gateway_posts_no_second_attempt(
    harness: Harness,
) -> None:
    # Arrange — variant 0's POST answers ambiguously, but the gateway DID queue it: GET /queue
    # lists a bayram job we hold no id for.
    job_id = await _quoted_and_paid(harness)
    orphan = QueuedJob(job_id="gw-orphan", model="flux2", client=CLIENT_TAG)
    posted_zero = {"n": 0}

    async def first_post_is_lost(request: MediaRequest, correlation_key: str) -> Err | None:
        if correlation_key.endswith(":0:1"):
            posted_zero["n"] += 1
            harness.provider.foreign_jobs.append(orphan)
            return err(ProviderAmbiguousError("read timeout after send", provider="fake"))
        return None

    harness.hooked.submit_hook = first_post_is_lost

    # Act — the chain runs a good while with the orphan still on the gateway.
    await _run(harness, 60)

    # Assert — no attempt 2 of variant 0; the slot is held by the ambiguous attempt, so
    # variant 1 has not been posted either (one job at a time on the GPU).
    zero = await _attempts(harness, job_id, 0)
    assert [(row.attempt, row.status) for row in zero] == [(1, MediaAttemptStatus.AMBIGUOUS)]
    assert await harness.gpu.holder() == str(zero[0].id)
    assert harness.provider.submits == []
    assert (await _job(harness, job_id)).state is MediaJobState.QUEUED

    # Act — the orphan leaves the gateway's queue.
    harness.provider.foreign_jobs.clear()
    await harness.drain()

    # Assert — exactly one automatic resubmit, and the request completes.
    job = await _job(harness, job_id)
    assert job.state is MediaJobState.DELIVERED, (job.state, job.error_code)
    assert posted_zero["n"] == 1
    assert [s.correlation_key.rsplit(":", 2)[-2:] for s in harness.provider.submits] == [
        ["0", "2"],
        ["1", "1"],
    ]


async def test_an_unknown_status_while_the_gateway_still_lists_the_job_is_not_resubmitted(
    harness: Harness,
) -> None:
    # Arrange — every poll answers ``unknown`` (the gateway lost track), yet /queue lists it.
    harness.provider.outcome = JobPhase.UNKNOWN
    job_id = await _quoted_and_paid(harness)
    await harness.drain(stop=lambda stage: stage.name == MEDIA_POLL_JOB)
    harness.provider.foreign_jobs.append(QueuedJob(job_id="fake-1"))

    # Act
    await _run(harness, 40)

    # Assert — still one POST: the render may be running, so nothing went on top of it.
    assert len(harness.provider.submits) == 1
    (first,) = await _attempts(harness, job_id, 0)
    assert first.status is MediaAttemptStatus.AMBIGUOUS
    assert await harness.gpu.holder() == str(first.id)


async def test_an_unreadable_gateway_queue_holds_the_slot_rather_than_guess(
    harness: Harness,
) -> None:
    job_id = await _quoted_and_paid(harness)
    await harness.drain(stop=lambda stage: stage.name == MEDIA_SUBMIT_JOB)
    harness.provider.submit_errors.append(ProviderAmbiguousError("5xx", provider="fake"))
    harness.provider.queue_error = ProviderUnavailableError("queue down", provider="fake")

    await _run(harness, 30)

    assert len(harness.provider.submits) == 0
    assert [row.status for row in await _attempts(harness, job_id, 0)] == [
        MediaAttemptStatus.AMBIGUOUS
    ]


async def test_a_render_timeout_keeps_the_slot_while_the_render_is_still_listed(
    harness: Harness,
) -> None:
    # Arrange — the render never finishes; there is no per-job cancel (§4.2).
    harness.provider.polls_until_done = 10_000
    job_id = await _quoted_and_paid(harness)
    await harness.drain(stop=lambda stage: stage.name == MEDIA_POLL_JOB)
    first_poll = harness.queue.pending.popleft()
    await harness.run(first_poll.name, *first_poll.args)  # "running": the render clock starts

    # Act — past the render timeout.
    harness.clock.advance(seconds=harness.rt.settings.media_image_render_timeout_s + 30)
    await _run(harness, 30)

    # Assert — the attempt is ambiguous and still owns the GPU; no attempt 2 was posted.
    (first,) = await _attempts(harness, job_id, 0)
    assert first.status is MediaAttemptStatus.AMBIGUOUS
    assert first.error_code == "render_timeout"
    assert await harness.gpu.holder() == str(first.id)
    assert len(harness.provider.submits) == 1


async def test_an_ambiguous_submit_on_a_paid_backend_holds_the_job_and_never_reposts(
    harness: Harness,
) -> None:
    # Arrange — the job was stamped with a backend that costs money (§4.3).
    job_id = await _quoted_and_paid(harness)
    await harness.drain(stop=lambda stage: stage.name == MEDIA_SUBMIT_JOB)
    async with harness.sessions.begin() as session:
        await session.execute(
            sa.update(MediaJobRow)
            .where(MediaJobRow.id == job_id)
            .values(backend=MediaBackend.HIGGSFIELD)
        )
    harness.provider.submit_errors.append(ProviderAmbiguousError("timeout", provider="fake"))

    # Act
    await harness.drain()

    # Assert — held for an operator, and variant 0 was never posted a second time.
    job = await _job(harness, job_id)
    assert job.state is MediaJobState.HELD and job.error_code == "ambiguous_submit"
    assert not [s for s in harness.provider.submits if s.correlation_key.endswith(":0:2")]


# ---------------------------------------------------------------------------
# §3.3 fan-in: every submit failing ends the job now, not at its deadline
# ---------------------------------------------------------------------------
async def test_a_job_whose_every_submit_fails_is_failed_without_waiting_for_the_deadline(
    harness: Harness,
) -> None:
    async def gateway_down(request: MediaRequest, correlation_key: str) -> Err | None:
        return err(ProviderUnavailableError("gateway down", provider="fake"))

    harness.hooked.submit_hook = gateway_down
    job_id = await _quoted_and_paid(harness)

    await harness.drain()

    job = await _job(harness, job_id)
    assert job.state is MediaJobState.FAILED and job.error_code == "generation_failed"
    async with harness.sessions() as session:
        assert await media_balance(session, telegram_user_id=USER, sku=job.sku) == 1
    assert await harness.gpu.holder() is None and await harness.gpu.members() == ()


# ---------------------------------------------------------------------------
# §7.2 step 1, §3.4: what the quote checks
# ---------------------------------------------------------------------------
async def test_an_unhealthy_backend_is_busy_at_quote_and_the_row_stays_screening(
    harness: Harness,
) -> None:
    harness.provider.health_state = HealthState.UNAVAILABLE
    job_id = await freeze_job(harness, photos=())

    await _screen(harness, job_id)

    assert (await _job(harness, job_id)).state is MediaJobState.SCREENING
    assert harness.messenger.tray_texts()[-1].startswith("⏳")


async def test_the_gateways_own_backlog_counts_toward_the_eta(harness: Harness) -> None:
    # Three marketing Wan clips queued on the gateway: ~52 min ahead of a 45-min deadline.
    harness.provider.foreign_jobs.extend(
        QueuedJob(job_id=f"marketing-{n}", model="wan", client="storybook") for n in range(3)
    )
    job_id = await freeze_job(harness, photos=())

    await _screen(harness, job_id)

    assert (await _job(harness, job_id)).state is MediaJobState.SCREENING
    harness.provider.foreign_jobs[:] = harness.provider.foreign_jobs[:1]
    await harness.queue.enqueue_job(
        MEDIA_SCREEN_JOB, str(job_id), 1, _job_id=screen_job_id(job_id, 1)
    )
    await harness.drain()
    job = await _job(harness, job_id)
    assert job.state is MediaJobState.QUOTED
    # One clip (~17.5 min) plus two images: the quote says so rather than "about 2 min".
    assert "19" in harness.messenger.tray_texts()[-1]


async def test_an_unreadable_gateway_queue_is_busy_at_quote(harness: Harness) -> None:
    harness.provider.queue_error = ProviderUnavailableError("queue down", provider="fake")
    job_id = await freeze_job(harness, photos=())

    await _screen(harness, job_id)

    assert (await _job(harness, job_id)).state is MediaJobState.SCREENING


# ---------------------------------------------------------------------------
# §9.3: /forget
# ---------------------------------------------------------------------------
async def test_forget_while_generating_leaves_no_output_row_or_object(harness: Harness) -> None:
    # Arrange — both renders are done and about to be fetched when /forget runs.
    job_id = await _quoted_and_paid(harness)
    await harness.drain(stop=lambda stage: stage.name == MEDIA_FETCH_JOB)
    eraser = SqlMediaEraser(
        harness.sessions, storage=harness.storage, queue=harness.queue, clock=harness.clock
    )
    assert not isinstance(await eraser.forget_media(USER), Err)

    # Act
    await harness.drain()

    # Assert — nothing delivered, nothing stored, no credit re-created.
    job = await _job(harness, job_id)
    assert job.state is MediaJobState.FAILED and job.error_code == "forget_requested"
    assert harness.messenger.albums == []
    async with harness.sessions() as session:
        outputs = await session.scalar(
            sa.select(sa.func.count())
            .select_from(MediaOutputRow)
            .where(MediaOutputRow.job_id == job_id)
        )
    assert outputs == 0
    assert not [p for p in (harness.storage.root / "media").rglob("*") if p.is_file()]
    assert await _ledger(harness, job_id) == []


async def test_a_job_forgotten_between_payment_and_start_is_never_refunded(
    harness: Harness,
) -> None:
    job_id = await _quoted_and_paid(harness)
    eraser = SqlMediaEraser(harness.sessions, storage=harness.storage, clock=harness.clock)
    assert not isinstance(await eraser.forget_media(USER), Err)

    await harness.drain()

    job = await _job(harness, job_id)
    assert job.state is MediaJobState.FAILED and job.error_code == "forget_requested"
    assert await _ledger(harness, job_id) == []
    async with harness.sessions() as session:
        assert await media_balance(session, telegram_user_id=USER, sku=job.sku) == 0


async def test_forget_cleans_up_a_cancelled_pre_pay_request_now(harness: Harness) -> None:
    job_id = await freeze_job(harness, photos=())
    await _screen(harness, job_id)
    harness.queue.pending.clear()
    eraser = SqlMediaEraser(
        harness.sessions, storage=harness.storage, queue=harness.queue, clock=harness.clock
    )

    assert not isinstance(await eraser.forget_media(USER), Err)

    assert (await _job(harness, job_id)).state is MediaJobState.CANCELLED
    assert [(s.name, s.args) for s in harness.queue.pending] == [
        (MEDIA_CLEANUP_JOB, (str(job_id),))
    ]


# ---------------------------------------------------------------------------
# §9.5: the output clock is configurable
# ---------------------------------------------------------------------------
async def test_the_output_retention_setting_reaches_the_rows_the_worker_writes(
    settings: Settings, sessions: async_sessionmaker[AsyncSession], tmp_path: Path
) -> None:
    harness = build_harness(
        media_settings(settings, retention_media_output_days=7), sessions, tmp_path, FIXED_NOW
    )
    job_id = await _quoted_and_paid(harness, via=MediaPaidVia.BETA)

    await harness.drain()

    job = await _job(harness, job_id)
    assert job.state is MediaJobState.DELIVERED
    async with harness.sessions() as session:
        outputs = (
            await session.scalars(sa.select(MediaOutputRow).where(MediaOutputRow.job_id == job_id))
        ).all()
    assert outputs
    assert all(o.expires_at <= harness.clock() + timedelta(days=7) for o in outputs)
    assert job.text_expires_at is not None
    assert job.text_expires_at <= harness.clock() + timedelta(days=7)
