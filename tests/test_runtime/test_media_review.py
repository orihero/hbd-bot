"""The review queue's worker half, over fakes (IMAGE_VIDEO_SPEC §6.6, §10 M3.2).

The M3.2 acceptance list's worker side, each a test below:

* **hold → release → deliver** — an L4 ``review`` holds the job and opens ONE pending review
  in the same transaction; a release applied by ``media_review_apply`` delivers the album;
* **hold 24 h → refund** — ``media_sweep`` decides an unreviewed hold ``expired`` at its SLA,
  and the job fails with exactly one SKU-scoped credit;
* a confirmed block fails with one credit attributed to the operator, and none for beta;
* a decision whose apply enqueue was lost is re-driven by the sweep, and applying twice is a
  no-op;
* an operator's hold makes a delivery that was already queued stand down.

The panel half — the step-up on the refund, the audit rows, the 409 — is
``tests/test_admin/test_media_reviews_router.py``.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
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
from bayram.db.engine import create_session_factory
from bayram.db.enums import (
    AuditReasonCode,
    MediaCreditReason,
    MediaJobState,
    MediaPaidVia,
    MediaReviewDecision,
    MediaReviewSource,
    MediaScreenDecision,
)
from bayram.db.media import MEDIA_REVIEW_SLA, load_job, mark_paid, media_balance
from bayram.db.media_reviews import decide_review, hold_job
from bayram.db.models import Base
from bayram.db.models.media_credit import MediaCreditLedgerRow
from bayram.db.models.media_job import MediaJobRow
from bayram.db.models.moderation_review import ModerationReviewRow
from bayram.media.stages import (
    MEDIA_DELIVER_JOB,
    MEDIA_REVIEW_JOB,
    MEDIA_SCREEN_JOB,
    MEDIA_START_JOB,
    review_job_id,
    screen_job_id,
    sku_deadline,
)
from bayram.moderation.contracts import CategoryCode
from bayram.runtime.media_sweep import sweep_media
from tests.conftest import FIXED_NOW
from tests.test_runtime.media_fakes import (
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
    return build_harness(media_settings(settings), sessions, tmp_path, FIXED_NOW)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
async def _job(harness: Harness, job_id: UUID) -> MediaJobRow:
    async with harness.sessions() as session:
        job = await load_job(session, job_id)
    assert job is not None
    return job


async def _reviews(harness: Harness, job_id: UUID) -> list[ModerationReviewRow]:
    async with harness.sessions() as session:
        return list(
            (
                await session.scalars(
                    sa.select(ModerationReviewRow)
                    .where(ModerationReviewRow.job_id == job_id)
                    .order_by(ModerationReviewRow.created_at)
                )
            ).all()
        )


async def _ledger(harness: Harness) -> list[MediaCreditLedgerRow]:
    async with harness.sessions() as session:
        return list((await session.scalars(sa.select(MediaCreditLedgerRow))).all())


async def _paid_job(harness: Harness, *, via: MediaPaidVia = MediaPaidVia.PAYME) -> UUID:
    """Screened, quoted and paid; ``media_start`` queued — the settlement path in one move."""
    job_id = await freeze_job(harness, photos=())
    await harness.queue.enqueue_job(MEDIA_SCREEN_JOB, str(job_id), 0, _job_id=screen_job_id(job_id))
    await harness.drain()
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
    await harness.queue.enqueue_job(
        MEDIA_START_JOB, str(job_id), 0, _job_id=f"media:{job_id}:start:0"
    )
    return job_id


async def _held_job(harness: Harness, *, via: MediaPaidVia = MediaPaidVia.PAYME) -> UUID:
    """A paid job whose L4 screen answered ``review`` — the job is ``held``."""
    harness.moderator.decisions["output_image"] = MediaScreenDecision.REVIEW
    harness.moderator.categories["output_image"] = (CategoryCode.VIOLENCE,)
    job_id = await _paid_job(harness, via=via)
    await harness.drain()
    assert (await _job(harness, job_id)).state is MediaJobState.HELD
    return job_id


async def _decide(
    harness: Harness, review_id: UUID, decision: MediaReviewDecision, *, actor: str = "alice"
) -> None:
    """What the panel does: record the decision. The apply is enqueued by the caller."""
    async with harness.sessions.begin() as session:
        assert await decide_review(
            session,
            review_id,
            decision=decision,
            now=harness.clock(),
            actor_id=None,
            actor=actor,
            reason_code=AuditReasonCode.ABUSE_REPORT,
        )


async def _apply(harness: Harness, review_id: UUID) -> None:
    await harness.queue.enqueue_job(
        MEDIA_REVIEW_JOB, str(review_id), _job_id=review_job_id(review_id)
    )
    await harness.drain()


# ---------------------------------------------------------------------------
# hold → release → deliver
# ---------------------------------------------------------------------------
async def test_a_held_output_opens_one_review_and_a_release_delivers_it(harness: Harness) -> None:
    # Arrange — the L4 guard answers ``review``.
    job_id = await _held_job(harness)

    # Assert — one pending review, opened with the move, carrying the guard's codes.
    [review] = await _reviews(harness, job_id)
    assert review.decision is None and review.applied_at is None
    assert review.source is MediaReviewSource.OUTPUT_REVIEW
    assert (review.subject, review.categories) == ("output_image", ["violence"])
    assert review.due_at == review.created_at + MEDIA_REVIEW_SLA
    assert harness.messenger.albums == []

    # Act — an operator releases it, and the worker applies the decision.
    await _decide(harness, review.id, MediaReviewDecision.RELEASED)
    await _apply(harness, review.id)

    # Assert — delivered, the decision stamped applied, no credit.
    job = await _job(harness, job_id)
    assert job.state is MediaJobState.DELIVERED
    assert job.output_decision is MediaScreenDecision.ALLOW
    assert len(harness.messenger.albums) == 1 and len(harness.messenger.albums[0].photos) == 2
    [review] = await _reviews(harness, job_id)
    assert review.applied_at is not None
    assert await _ledger(harness) == []


async def test_applying_a_decision_twice_changes_nothing(harness: Harness) -> None:
    job_id = await _held_job(harness)
    [review] = await _reviews(harness, job_id)
    await _decide(harness, review.id, MediaReviewDecision.RELEASED)
    await _apply(harness, review.id)

    again = await harness.run(MEDIA_REVIEW_JOB, str(review.id))

    assert again["outcome"] == "noop_applied"
    assert len(harness.messenger.albums) == 1


# ---------------------------------------------------------------------------
# hold 24 h → refund
# ---------------------------------------------------------------------------
async def test_an_unreviewed_hold_expires_at_its_sla_and_refunds_one_credit(
    harness: Harness,
) -> None:
    # Arrange
    job_id = await _held_job(harness)
    [review] = await _reviews(harness, job_id)

    # Act — a sweep inside the SLA does nothing to it…
    harness.clock.advance(hours=23)
    await sweep_media(harness.rt)
    await harness.drain()
    assert (await _job(harness, job_id)).state is MediaJobState.HELD

    # …and the first one past it expires it; the worker fails the job with one credit.
    harness.clock.advance(hours=1, minutes=1)
    summary = await sweep_media(harness.rt)
    await harness.drain()

    # Assert
    assert summary["reviews"] >= 1 and summary["errors"] == []
    [review] = await _reviews(harness, job_id)
    assert review.decision is MediaReviewDecision.EXPIRED and review.actor == "system"
    assert review.applied_at is not None
    job = await _job(harness, job_id)
    assert (job.state, job.error_code) == (MediaJobState.FAILED, "review_expired")
    assert [(row.delta, row.reason, row.actor) for row in await _ledger(harness)] == [
        (1, MediaCreditReason.OUTPUT_BLOCKED, "worker")
    ]
    async with harness.sessions() as session:
        assert await media_balance(session, telegram_user_id=USER, sku=job.sku) == 1
    assert harness.messenger.albums == []
    # A later sweep neither re-decides nor refunds again.
    harness.clock.advance(hours=1)
    await sweep_media(harness.rt)
    await harness.drain()
    assert len(await _ledger(harness)) == 1


# ---------------------------------------------------------------------------
# Confirmed block
# ---------------------------------------------------------------------------
async def test_a_confirmed_block_fails_with_one_credit_attributed_to_the_operator(
    harness: Harness,
) -> None:
    job_id = await _held_job(harness)
    [review] = await _reviews(harness, job_id)

    await _decide(harness, review.id, MediaReviewDecision.BLOCKED, actor="alice")
    await _apply(harness, review.id)

    job = await _job(harness, job_id)
    assert (job.state, job.error_code) == (MediaJobState.FAILED, "review_blocked")
    assert [(row.delta, row.actor) for row in await _ledger(harness)] == [(1, "admin:alice")]
    assert harness.messenger.albums == []
    # Two strikes, as for an L4 block (§6.4).
    assert len(harness.strikes.strikes.get(USER, {})) == 2


async def test_a_confirmed_block_of_a_beta_job_mints_no_credit(harness: Harness) -> None:
    job_id = await _held_job(harness, via=MediaPaidVia.BETA)
    [review] = await _reviews(harness, job_id)

    await _decide(harness, review.id, MediaReviewDecision.BLOCKED)
    await _apply(harness, review.id)

    assert (await _job(harness, job_id)).state is MediaJobState.FAILED
    assert await _ledger(harness) == []


# ---------------------------------------------------------------------------
# Lost enqueues and the operator's hold
# ---------------------------------------------------------------------------
async def test_a_decision_whose_apply_was_lost_is_redriven_by_the_sweep(harness: Harness) -> None:
    # Arrange — decided, and the panel's enqueue never happened.
    job_id = await _held_job(harness)
    [review] = await _reviews(harness, job_id)
    await _decide(harness, review.id, MediaReviewDecision.RELEASED)

    # Act
    harness.clock.advance(minutes=3)
    await sweep_media(harness.rt)
    await harness.drain()

    # Assert
    assert (await _job(harness, job_id)).state is MediaJobState.DELIVERED
    assert len(harness.messenger.albums) == 1


async def test_an_operator_hold_makes_a_queued_delivery_stand_down(harness: Harness) -> None:
    # Arrange — screened and allowed; the delivery is queued but has not run.
    job_id = await _paid_job(harness)
    await harness.drain(stop=lambda stage: stage.name == MEDIA_DELIVER_JOB)
    job = await _job(harness, job_id)
    assert (job.state, job.output_decision) == (MediaJobState.POST, MediaScreenDecision.ALLOW)

    # Act — the panel holds it, then the queued delivery runs.
    async with harness.sessions.begin() as session:
        review_id = await hold_job(
            session,
            job_id,
            now=harness.clock(),
            actor_id=None,
            actor="alice",
            reason_code=AuditReasonCode.ABUSE_REPORT,
        )
    await harness.drain()

    # Assert — nothing delivered; one pending manual review; a release then delivers.
    assert review_id is not None
    assert harness.messenger.albums == []
    job = await _job(harness, job_id)
    assert (job.state, job.output_decision) == (MediaJobState.HELD, MediaScreenDecision.REVIEW)
    [review] = await _reviews(harness, job_id)
    assert (review.source, review.decision) == (MediaReviewSource.MANUAL, None)
    await _decide(harness, review_id, MediaReviewDecision.RELEASED)
    await _apply(harness, review_id)
    assert (await _job(harness, job_id)).state is MediaJobState.DELIVERED
    assert len(harness.messenger.albums) == 1


async def test_a_guard_that_never_answers_holds_the_job_for_review(harness: Harness) -> None:
    harness.moderator.decisions["output_image"] = MediaScreenDecision.UNAVAILABLE
    job_id = await _paid_job(harness)

    await harness.drain()

    [review] = await _reviews(harness, job_id)
    assert review.source is MediaReviewSource.GUARD_UNAVAILABLE
    assert (await _job(harness, job_id)).state is MediaJobState.HELD
