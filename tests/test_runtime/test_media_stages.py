"""The media stage chain end to end, over fakes (IMAGE_VIDEO_SPEC §3.3–§3.5, §10 M2.4).

The M2.4 acceptance list, each a test below:

* a full fake run — screening → free beta → two photos delivered → uploads deleted;
* a duplicate of every stage is a no-op, **and a deliberate self-re-enqueue runs again**
  (the queue here drops a seen id, as ARQ does);
* a worker killed between the attempt insert and the POST, re-run → the provider sees ONE
  submit for that variant;
* the GPU lock's renew/release are compare-and-set (``test_gpu_lock.py``) and a terminal job
  leaves the queue; the lock is released on failure;
* the deadline fires, then the late success delivers nothing and exactly one credit exists.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Final
from uuid import UUID

import pytest
import sqlalchemy as sa
from PIL import Image
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import StaticPool

from bayram.config import Settings
from bayram.contracts import Err, err
from bayram.db.engine import create_session_factory
from bayram.db.enums import (
    MediaAttemptStatus,
    MediaCreditReason,
    MediaInputRole,
    MediaJobState,
    MediaPaidVia,
    MediaScreenDecision,
)
from bayram.db.media import load_job, mark_paid, media_balance
from bayram.db.models import Base
from bayram.db.models.media_attempt import MediaAttemptRow
from bayram.db.models.media_credit import MediaCreditLedgerRow
from bayram.db.models.media_input import MediaInputRow, MediaOutputRow
from bayram.db.models.media_purchase import MediaPurchaseRow
from bayram.errors import DeliveryError, ModerationUnavailableError, ProviderUnavailableError
from bayram.media.contracts import JobPhase, MediaRequest
from bayram.media.service import BetaStart, start_free_beta
from bayram.media.stages import (
    MEDIA_POLL_JOB,
    MEDIA_SCREEN_JOB,
    MEDIA_START_JOB,
    MEDIA_SUBMIT_JOB,
    screen_job_id,
    sku_deadline,
)
from bayram.moderation.contracts import MEDIA_POLICY_VERSION, CategoryCode
from bayram.runtime.gpu_lock import GPU_LOCK_ACQUIRE_TTL_MS
from bayram.runtime.media_sweep import sweep_media
from tests.conftest import FIXED_NOW
from tests.test_runtime.media_fakes import (
    PROMPT,
    TRAY_ID,
    USER,
    Harness,
    animated_gif_bytes,
    build_harness,
    freeze_job,
    jpeg_bytes,
    media_settings,
)

_TWO_PHOTOS: Final[tuple[bytes, bytes]] = (jpeg_bytes((200, 40, 40)), jpeg_bytes((40, 200, 40)))


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
async def _job(harness: Harness, job_id: UUID):  # type: ignore[no-untyped-def]
    async with harness.sessions() as session:
        return await load_job(session, job_id)


async def _count(harness: Harness, model: type[Base], job_id: UUID) -> int:
    async with harness.sessions() as session:
        value = await session.scalar(
            sa.select(sa.func.count()).select_from(model).where(model.job_id == job_id)  # type: ignore[attr-defined]
        )
    return int(value or 0)


async def _screen_and_quote(harness: Harness, job_id: UUID) -> None:
    await harness.queue.enqueue_job(MEDIA_SCREEN_JOB, str(job_id), 0, _job_id=screen_job_id(job_id))
    await harness.drain()
    job = await _job(harness, job_id)
    assert job is not None and job.state is MediaJobState.QUOTED, job and job.state


async def _pay(harness: Harness, job_id: UUID, *, via: MediaPaidVia = MediaPaidVia.PAYME) -> None:
    """The settlement path (M5) in one move: ``quoted → paid`` and ``media_start`` queued."""
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


# ---------------------------------------------------------------------------
# The whole chain
# ---------------------------------------------------------------------------
async def test_a_full_fake_run_screens_starts_free_delivers_two_photos_and_deletes_uploads(
    harness: Harness,
) -> None:
    # Arrange — two photos on a one-reference backend, so a collage is built and screened.
    job_id = await freeze_job(harness, photos=_TWO_PHOTOS)

    # Act — screening
    await _screen_and_quote(harness, job_id)

    # Assert — the tray became the quote, with 🎁 (stub rail, allowlisted) and no 💳.
    quote = harness.messenger.tray_texts()[-1]
    assert "2 images" in quote and "5\xa0000 UZS" in quote
    markup = harness.messenger.edits[-1][3]
    assert markup is not None
    callbacks = [row[0].callback_data or "" for row in markup.inline_keyboard]
    assert any(data.startswith("med:beta:") for data in callbacks)
    assert not any(data.startswith("med:pay:") for data in callbacks)
    assert set(harness.moderator.subjects_screened("image")) == {"upload", "collage"}
    assert harness.moderator.subjects_screened("text") == ("prompt",)
    job = await _job(harness, job_id)
    assert job.screen_decision is MediaScreenDecision.ALLOW
    assert job.screen_policy_version == MEDIA_POLICY_VERSION
    assert job.content_sha256 is not None

    # Act — 🎁, then the chain runs to the end.
    outcome = await start_free_beta(
        harness.sessions,
        harness.queue,
        harness.rt.settings,
        job_id=job_id,
        telegram_user_id=USER,
        is_paused=False,
        now=harness.clock(),
    )
    await harness.drain()

    # Assert — delivered: one album of two photos, the file ids kept, the uploads gone.
    assert outcome is BetaStart.STARTED
    job = await _job(harness, job_id)
    assert job.state is MediaJobState.DELIVERED, (job.state, job.error_code)
    assert job.paid_via is MediaPaidVia.BETA and job.delivered_at is not None
    assert len(harness.messenger.albums) == 1
    album = harness.messenger.albums[0]
    assert len(album.photos) == 2 and "@bayram_uzbot" in album.caption
    assert len(harness.provider.submits) == 2
    assert [s.request.seed for s in harness.provider.submits] == [
        harness.provider.submits[0].request.seed,
        harness.provider.submits[0].request.seed + 1,
    ]
    assert all(len(s.request.refs) == 1 for s in harness.provider.submits)
    assert set(harness.moderator.subjects_screened("image")) >= {"output_image"}
    async with harness.sessions() as session:
        outputs = (
            await session.scalars(sa.select(MediaOutputRow).where(MediaOutputRow.job_id == job_id))
        ).all()
        receipts = (
            await session.scalars(
                sa.select(MediaPurchaseRow).where(MediaPurchaseRow.job_id == job_id)
            )
        ).all()
    assert sorted(o.tg_file_id or "" for o in outputs) == ["tg-photo-0", "tg-photo-1"]
    assert [(r.provider.value, r.amount_minor) for r in receipts] == [("beta", 0)]
    assert await _count(harness, MediaInputRow, job_id) == 0
    assert not list((harness.storage.root / "media" / str(job_id) / "in").glob("*"))
    assert all((harness.storage.root / o.storage_key).exists() for o in outputs)
    assert not (harness.workspace / "media" / str(job_id)).exists()
    assert await harness.gpu.members() == () and await harness.gpu.holder() is None
    # The progress message was sent once and nothing went unhandled.
    assert any("in line" in text for _, text, _ in harness.messenger.sent)
    assert harness.queue.unhandled == []


async def test_uploads_are_stored_with_their_metadata_stripped(harness: Harness) -> None:
    # Arrange
    job_id = await freeze_job(harness, photos=_TWO_PHOTOS[:1])

    # Act
    await _screen_and_quote(harness, job_id)

    # Assert — the stored copy is the screened one: no EXIF, orientation applied (64x48 → 48x64).
    async with harness.sessions() as session:
        (row,) = (
            await session.scalars(sa.select(MediaInputRow).where(MediaInputRow.job_id == job_id))
        ).all()
    assert row.storage_key is not None and row.sha256 is not None
    stored = harness.storage.root / row.storage_key
    with Image.open(stored) as image:
        assert image.size == (48, 64)
        assert not image.getexif()
    assert b"PhoneMaker" not in stored.read_bytes()
    # One photo on a one-reference backend goes natively: no collage.
    assert harness.moderator.subjects_screened("image") == ("upload",)


async def test_a_duplicate_of_every_stage_changes_nothing(harness: Harness) -> None:
    # Arrange
    job_id = await freeze_job(harness, photos=_TWO_PHOTOS)
    await harness.queue.enqueue_job(MEDIA_SCREEN_JOB, str(job_id), 0, _job_id=screen_job_id(job_id))
    await harness.drain(duplicate=True)
    await _pay(harness, job_id, via=MediaPaidVia.BETA)

    # Act — every stage runs twice in a row, as a redelivered ARQ job would.
    await harness.drain(duplicate=True)

    # Assert — one render per variant, one album, one receipt of delivery.
    job = await _job(harness, job_id)
    assert job.state is MediaJobState.DELIVERED
    assert len(harness.provider.submits) == 2
    assert len(harness.messenger.albums) == 1
    quotes = [text for text in harness.messenger.tray_texts() if "2 images" in text]
    assert len(quotes) == 1
    async with harness.sessions() as session:
        attempts = (
            await session.scalars(
                sa.select(MediaAttemptRow).where(MediaAttemptRow.job_id == job_id)
            )
        ).all()
    assert sorted((a.variant, a.attempt, a.status.value) for a in attempts) == [
        (0, 1, "succeeded"),
        (1, 1, "succeeded"),
    ]


async def test_a_deliberate_self_re_enqueue_runs_again(harness: Harness) -> None:
    # Arrange — each render answers "running" three times, and variant 1 must wait for the GPU
    # while variant 0 renders: both self-re-enqueue paths are exercised, under ARQ's dedupe.
    harness.provider.polls_until_done = 3
    job_id = await freeze_job(harness, photos=())
    await _screen_and_quote(harness, job_id)
    await _pay(harness, job_id, via=MediaPaidVia.BETA)

    # Act
    await harness.drain()

    # Assert — it finished, which it could only do if every re-enqueue actually ran.
    job = await _job(harness, job_id)
    assert job.state is MediaJobState.DELIVERED
    polls = [stage.job_id for stage in harness.queue.ran_named(MEDIA_POLL_JOB)]
    assert [pid for pid in polls if pid.startswith(f"media:{job_id}:poll:0:1:")] == [
        f"media:{job_id}:poll:0:1:{tick}" for tick in range(4)
    ]
    waiting = [
        stage.job_id
        for stage in harness.queue.ran_named(MEDIA_SUBMIT_JOB)
        if stage.job_id.startswith(f"media:{job_id}:submit:1:1:")
    ]
    assert len(waiting) >= 2 and len(set(waiting)) == len(waiting)
    assert harness.queue.dropped == []
    assert job.submit_seq >= 1


async def test_a_worker_killed_between_the_attempt_row_and_the_post_is_never_reposted(
    harness: Harness,
) -> None:
    # Arrange — the first submit of variant 0 dies right after its attempt row committed.
    job_id = await freeze_job(harness, photos=())
    await _screen_and_quote(harness, job_id)
    await _pay(harness, job_id, via=MediaPaidVia.BETA)
    await harness.drain(stop=lambda stage: stage.name == MEDIA_SUBMIT_JOB)
    killed = {"done": False}

    async def dies_before_posting(request: MediaRequest, correlation_key: str) -> None:
        if not killed["done"]:
            killed["done"] = True
            raise asyncio.CancelledError  # the worker was killed mid-job

    harness.hooked.submit_hook = dies_before_posting
    first = harness.queue.pending.popleft()
    with pytest.raises(asyncio.CancelledError):
        await harness.run(first.name, *first.args)
    # The dead worker's short lock runs out (§3.4: two minutes).
    harness.gpu.now_ms = (harness.gpu.lock[1] if harness.gpu.lock else 0) + GPU_LOCK_ACQUIRE_TTL_MS

    # Act — ARQ re-runs the same job (same variant, same attempt), then the rest drains.
    await harness.run(first.name, *first.args)
    await harness.drain()

    # Assert — attempt 1 was never posted: it is ambiguous, and variant 0 posted exactly once.
    job = await _job(harness, job_id)
    assert job.state is MediaJobState.DELIVERED
    variant_zero = [s for s in harness.provider.submits if s.correlation_key.endswith(":0:2")]
    assert len(variant_zero) == 1
    assert not [s for s in harness.provider.submits if s.correlation_key.endswith(":0:1")]
    async with harness.sessions() as session:
        first_attempt = await session.scalar(
            sa.select(MediaAttemptRow).where(
                MediaAttemptRow.job_id == job_id,
                MediaAttemptRow.variant == 0,
                MediaAttemptRow.attempt == 1,
            )
        )
    assert first_attempt is not None
    assert first_attempt.status is MediaAttemptStatus.AMBIGUOUS
    assert first_attempt.remote_id is None


async def test_a_submit_whose_owner_still_holds_the_lock_is_not_a_crash(harness: Harness) -> None:
    # Arrange — a sibling copy of the submit is mid-POST: its row exists, its lock is live.
    job_id = await freeze_job(harness, photos=())
    await _screen_and_quote(harness, job_id)
    await _pay(harness, job_id, via=MediaPaidVia.BETA)
    await harness.drain(stop=lambda stage: stage.name == MEDIA_SUBMIT_JOB)
    first = harness.queue.pending[0]
    release = asyncio.Event()

    async def slow_submit(request: MediaRequest, correlation_key: str) -> None:
        await release.wait()

    harness.hooked.submit_hook = slow_submit
    in_flight = asyncio.create_task(harness.run(first.name, *first.args))
    await asyncio.sleep(0.05)

    # Act — the duplicate arrives while the first is waiting on the POST.
    duplicate = await harness.run(first.name, *first.args)
    release.set()
    await in_flight

    # Assert
    assert duplicate["outcome"] == "noop_in_flight"
    assert len(harness.provider.submits) == 1


# ---------------------------------------------------------------------------
# Failure paths: the lock, the queue and the money
# ---------------------------------------------------------------------------
async def test_a_generation_failure_releases_the_lock_and_leaves_the_queue(
    harness: Harness,
) -> None:
    # Arrange — every render fails, paid with Payme.
    harness.provider.outcome = JobPhase.FAILED
    job_id = await freeze_job(harness, photos=())
    await _screen_and_quote(harness, job_id)
    await _pay(harness, job_id)

    # Act
    await harness.drain()

    # Assert — two attempts per variant, then failed with one credit; GPU tidy; customer told.
    job = await _job(harness, job_id)
    assert job.state is MediaJobState.FAILED and job.error_code == "generation_failed"
    assert len(harness.provider.submits) == 2 * harness.rt.settings.media_max_attempts
    assert await harness.gpu.holder() is None
    assert await harness.gpu.members() == ()
    async with harness.sessions() as session:
        assert await media_balance(session, telegram_user_id=USER, sku=job.sku) == 1
    assert any("credit" in text for _, text, _ in harness.messenger.sent)
    assert harness.messenger.albums == []


async def test_a_beta_failure_mints_no_credit(harness: Harness) -> None:
    harness.provider.outcome = JobPhase.FAILED
    job_id = await freeze_job(harness, photos=())
    await _screen_and_quote(harness, job_id)
    await _pay(harness, job_id, via=MediaPaidVia.BETA)

    await harness.drain()

    job = await _job(harness, job_id)
    assert job.state is MediaJobState.FAILED
    async with harness.sessions() as session:
        assert await media_balance(session, telegram_user_id=USER, sku=job.sku) == 0
    assert any("free beta" in text for _, text, _ in harness.messenger.sent)


async def test_one_variant_failing_to_generate_delivers_the_other_and_refunds_one(
    harness: Harness,
) -> None:
    # Arrange — variant 1 is refused at submit, every time (a pre-submit failure).
    job_id = await freeze_job(harness, photos=())
    await _screen_and_quote(harness, job_id)
    await _pay(harness, job_id)

    async def variant_one_fails(request: MediaRequest, correlation_key: str) -> Err | None:
        if correlation_key.split(":")[-2] == "1":
            return err(ProviderUnavailableError("down", provider="fake"))
        return None

    harness.hooked.submit_hook = variant_one_fails

    # Act
    await harness.drain()

    # Assert — Q3: one photo delivered and one credit.
    job = await _job(harness, job_id)
    assert job.state is MediaJobState.DELIVERED
    assert len(harness.messenger.albums[0].photos) == 1
    async with harness.sessions() as session:
        assert await media_balance(session, telegram_user_id=USER, sku=job.sku) == 1


async def test_the_deadline_then_a_late_success_delivers_nothing_and_grants_one_credit(
    harness: Harness,
) -> None:
    # Arrange — the render hangs in "running" past the deadline.
    harness.provider.polls_until_done = 10_000
    job_id = await freeze_job(harness, photos=())
    await _screen_and_quote(harness, job_id)
    await _pay(harness, job_id)
    await harness.drain(stop=lambda stage: stage.name == MEDIA_POLL_JOB)
    assert (await _job(harness, job_id)).state is MediaJobState.GENERATING
    assert await harness.gpu.holder() is not None

    # Act — the deadline passes; the sweep fails the job. Then the render "finishes".
    harness.clock.advance(seconds=harness.rt.settings.media_image_deadline_s + 60)
    summary = await sweep_media(harness.rt)
    harness.provider.polls_until_done = 0
    await harness.drain()

    # Assert — failed by the deadline, never delivered, one credit, the GPU freed.
    job = await _job(harness, job_id)
    assert summary["deadline_failed"] == 1
    assert job.state is MediaJobState.FAILED and job.error_code == "deadline"
    assert harness.messenger.albums == []
    async with harness.sessions() as session:
        ledger = (
            await session.scalars(
                sa.select(MediaCreditLedgerRow).where(MediaCreditLedgerRow.job_id == job_id)
            )
        ).all()
        assert await media_balance(session, telegram_user_id=USER, sku=job.sku) == 1
    assert [(row.delta, row.reason) for row in ledger] == [(1, MediaCreditReason.DEADLINE)]
    assert await harness.gpu.holder() is None
    assert await harness.gpu.members() == ()
    assert await _count(harness, MediaOutputRow, job_id) == 0


async def test_an_output_block_fails_the_whole_request_with_one_credit(harness: Harness) -> None:
    harness.moderator.decisions["output_image"] = MediaScreenDecision.BLOCK
    harness.moderator.categories["output_image"] = (CategoryCode.VIOLENCE,)
    job_id = await freeze_job(harness, photos=())
    await _screen_and_quote(harness, job_id)
    await _pay(harness, job_id)

    await harness.drain()

    job = await _job(harness, job_id)
    assert job.state is MediaJobState.FAILED and job.error_code == "output_blocked"
    assert job.output_categories == ["violence"]
    assert harness.messenger.albums == []
    async with harness.sessions() as session:
        assert await media_balance(session, telegram_user_id=USER, sku=job.sku) == 1


async def test_an_unavailable_output_guard_retries_under_new_ids_then_holds(
    harness: Harness,
) -> None:
    harness.moderator.decisions["output_image"] = MediaScreenDecision.UNAVAILABLE
    job_id = await freeze_job(harness, photos=())
    await _screen_and_quote(harness, job_id)
    await _pay(harness, job_id, via=MediaPaidVia.BETA)

    await harness.drain()

    job = await _job(harness, job_id)
    assert job.state is MediaJobState.HELD
    screens = harness.queue.ran_ids(f"media:{job_id}:oscreen:")
    assert len(screens) == 15 and len(set(screens)) == 15  # every 2 min for 30 min
    assert harness.messenger.albums == []


async def test_a_customer_who_blocked_the_bot_ends_the_job_without_a_credit(
    harness: Harness,
) -> None:
    from bayram.bot.delivery import BLOCKED_BY_CUSTOMER_KEY

    harness.messenger.album_failures.append(
        DeliveryError("blocked", is_retryable=False, context={BLOCKED_BY_CUSTOMER_KEY: True})
    )
    job_id = await freeze_job(harness, photos=())
    await _screen_and_quote(harness, job_id)
    await _pay(harness, job_id)

    await harness.drain()

    job = await _job(harness, job_id)
    assert job.state is MediaJobState.FAILED and job.error_code == "customer_blocked"
    async with harness.sessions() as session:
        assert await media_balance(session, telegram_user_id=USER, sku=job.sku) == 0


async def test_a_transient_delivery_failure_is_retried_and_delivers_once(harness: Harness) -> None:
    harness.messenger.album_failures.append(DeliveryError("flaky", is_retryable=True))
    job_id = await freeze_job(harness, photos=())
    await _screen_and_quote(harness, job_id)
    await _pay(harness, job_id)

    await harness.drain()

    job = await _job(harness, job_id)
    assert job.state is MediaJobState.DELIVERED
    assert len(harness.messenger.albums) == 1


# ---------------------------------------------------------------------------
# Screening outcomes
# ---------------------------------------------------------------------------
async def test_a_blocked_prompt_is_refused_before_any_quote_and_its_uploads_deleted(
    harness: Harness,
) -> None:
    harness.moderator.decisions["prompt"] = MediaScreenDecision.BLOCK
    job_id = await freeze_job(harness, photos=_TWO_PHOTOS)

    await harness.queue.enqueue_job(MEDIA_SCREEN_JOB, str(job_id), 0, _job_id=screen_job_id(job_id))
    await harness.drain()

    job = await _job(harness, job_id)
    assert job.state is MediaJobState.REJECTED
    assert "can't make this one" in harness.messenger.tray_texts()[-1]
    assert await _count(harness, MediaInputRow, job_id) == 0
    assert not (harness.storage.root / "media" / str(job_id) / "in").exists() or not list(
        (harness.storage.root / "media" / str(job_id) / "in").iterdir()
    )


async def test_a_review_before_payment_is_a_refusal(harness: Harness) -> None:
    harness.moderator.decisions["upload"] = MediaScreenDecision.REVIEW
    job_id = await freeze_job(harness, photos=_TWO_PHOTOS[:1])

    await harness.queue.enqueue_job(MEDIA_SCREEN_JOB, str(job_id), 0, _job_id=screen_job_id(job_id))
    await harness.drain()

    assert (await _job(harness, job_id)).state is MediaJobState.REJECTED


async def test_a_guard_that_does_not_answer_is_busy_and_quotes_nothing(harness: Harness) -> None:
    harness.moderator.failure = ModerationUnavailableError("down")
    job_id = await freeze_job(harness, photos=())

    await harness.queue.enqueue_job(MEDIA_SCREEN_JOB, str(job_id), 0, _job_id=screen_job_id(job_id))
    await harness.drain()

    job = await _job(harness, job_id)
    assert job.state is MediaJobState.SCREENING
    assert job.screen_decision is MediaScreenDecision.UNAVAILABLE
    assert "fully booked" in harness.messenger.tray_texts()[-1]

    # 🔁 retry-later, once the guard is back: the SAME row is quoted.
    harness.moderator.failure = None
    await harness.queue.enqueue_job(
        MEDIA_SCREEN_JOB, str(job_id), 1, _job_id=screen_job_id(job_id, 1)
    )
    await harness.drain()
    assert (await _job(harness, job_id)).state is MediaJobState.QUOTED


async def test_an_animated_upload_is_refused_not_flattened(harness: Harness) -> None:
    job_id = await freeze_job(harness, photos=[animated_gif_bytes()])

    await harness.queue.enqueue_job(MEDIA_SCREEN_JOB, str(job_id), 0, _job_id=screen_job_id(job_id))
    await harness.drain()

    job = await _job(harness, job_id)
    assert job.state is MediaJobState.REJECTED and job.error_code == "unsupported_input"
    assert "can't be used" in harness.messenger.tray_texts()[-1]
    assert harness.moderator.calls == []


async def test_a_paused_sku_is_busy_at_quote(harness: Harness) -> None:
    harness.kv.values["media:paused:image"] = "1"
    job_id = await freeze_job(harness, photos=())

    await harness.queue.enqueue_job(MEDIA_SCREEN_JOB, str(job_id), 0, _job_id=screen_job_id(job_id))
    await harness.drain()

    job = await _job(harness, job_id)
    assert job.state is MediaJobState.SCREENING
    assert job.screen_decision is MediaScreenDecision.ALLOW
    assert "fully booked" in harness.messenger.tray_texts()[-1]


# ---------------------------------------------------------------------------
# media_start's re-checks
# ---------------------------------------------------------------------------
async def test_start_refuses_a_row_whose_prompt_changed_after_screening(harness: Harness) -> None:
    job_id = await freeze_job(harness, photos=())
    await _screen_and_quote(harness, job_id)
    async with harness.sessions.begin() as session:
        await session.execute(
            sa.text("UPDATE media_jobs SET prompt = :p WHERE id = :i"),
            {"p": PROMPT + " and something else", "i": job_id.hex},
        )
    await _pay(harness, job_id)

    await harness.drain()

    job = await _job(harness, job_id)
    assert job.state is MediaJobState.FAILED and job.error_code == "screen_stale"
    assert harness.provider.submits == []


async def test_start_re_checks_the_beta_allowlist_at_run_time(
    harness: Harness, settings: Settings
) -> None:
    job_id = await freeze_job(harness, photos=())
    await _screen_and_quote(harness, job_id)
    await _pay(harness, job_id, via=MediaPaidVia.BETA)
    object.__setattr__(harness.rt, "settings", media_settings(settings, media_beta_allowlist=(1,)))

    await harness.drain()

    job = await _job(harness, job_id)
    assert job.state is MediaJobState.FAILED and job.error_code == "not_entitled"
    assert harness.provider.submits == []


async def test_a_second_start_is_a_no_op(harness: Harness) -> None:
    job_id = await freeze_job(harness, photos=())
    await _screen_and_quote(harness, job_id)
    await _pay(harness, job_id, via=MediaPaidVia.BETA)
    await harness.drain(stop=lambda stage: stage.name == MEDIA_SUBMIT_JOB)

    again = await harness.run(MEDIA_START_JOB, str(job_id), 7)

    assert again["outcome"] == "noop_not_paid"


async def test_the_quote_offers_pay_only_on_a_live_paid_rail(
    harness: Harness, settings: Settings
) -> None:
    object.__setattr__(
        harness.rt,
        "settings",
        media_settings(
            settings,
            checkout_provider="payme",
            payme_merchant_id="m",
            credits_enforced=True,
            payme_is_sandbox=False,
        ),
    )
    job_id = await freeze_job(harness, photos=())

    await _screen_and_quote(harness, job_id)

    markup = harness.messenger.edits[-1][3]
    assert markup is not None
    callbacks = [row[0].callback_data or "" for row in markup.inline_keyboard]
    assert any(data.startswith("med:pay:") for data in callbacks)
    assert not any(data.startswith("med:beta:") for data in callbacks)
    assert harness.messenger.edits[-1][1] == TRAY_ID


async def test_a_beta_press_off_the_allowlist_starts_nothing(
    harness: Harness, settings: Settings
) -> None:
    job_id = await freeze_job(harness, photos=())
    await _screen_and_quote(harness, job_id)

    outcome = await start_free_beta(
        harness.sessions,
        harness.queue,
        media_settings(settings, media_beta_allowlist=(1,)),
        job_id=job_id,
        telegram_user_id=USER,
        is_paused=False,
        now=harness.clock(),
    )

    assert outcome is BetaStart.NOT_ENTITLED
    assert (await _job(harness, job_id)).state is MediaJobState.QUOTED
    assert harness.queue.pending == type(harness.queue.pending)()


async def test_a_video_job_is_refused_before_the_gpu_until_m4(harness: Harness) -> None:
    from bayram.db.enums import MediaKind

    job_id = await freeze_job(harness, photos=(), kind=MediaKind.VIDEO, price_minor=2_500_000)
    await harness.queue.enqueue_job(MEDIA_SCREEN_JOB, str(job_id), 0, _job_id=screen_job_id(job_id))
    object.__setattr__(
        harness.rt,
        "settings",
        media_settings(harness.rt.settings, is_video_standard_offered=True),
    )
    await harness.drain()
    await _pay(harness, job_id, via=MediaPaidVia.BETA)

    await harness.drain()

    job = await _job(harness, job_id)
    assert job.state is MediaJobState.FAILED and job.error_code == "video_not_built"
    assert harness.provider.submits == []


async def test_inputs_of_a_collage_are_recorded_with_their_role(harness: Harness) -> None:
    job_id = await freeze_job(harness, photos=_TWO_PHOTOS)

    await _screen_and_quote(harness, job_id)

    async with harness.sessions() as session:
        roles = (
            await session.scalars(
                sa.select(MediaInputRow.role).where(MediaInputRow.job_id == job_id)
            )
        ).all()
    assert sorted(role.value for role in roles) == ["collage", "photo", "photo"]
    assert MediaInputRole.COLLAGE in roles
