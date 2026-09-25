"""The kind-scoped media credit and the daily caps, over fakes (IMAGE_VIDEO_SPEC §7.2, §7.5, §7.6).

The §10 M5.2 acceptance list, each a test below (the genuinely concurrent 🎟 race is also run
on Postgres, in ``tests/test_db/test_media_credit_postgres.py``):

* two 🎟 taps with a balance of one → one spend, one start;
* the deadline fails a job and a late generation failure follows → exactly one credit;
* a credit is SKU-scoped — an image credit never pays for a video;
* the song credit scalar is untouched by any of it;

and §7.6's daily cap: refused before a quote (no guard is asked), and again at every press.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import replace
from pathlib import Path
from typing import Any
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
from bayram.contracts import is_ok
from bayram.db.engine import create_session_factory
from bayram.db.enums import (
    MediaCreditReason,
    MediaJobState,
    MediaKind,
    MediaPaidVia,
    MediaPurchaseProvider,
    MediaSku,
)
from bayram.db.media import grant_refund, load_job, mark_paid, media_balance, transition
from bayram.db.models import Base, CreditAccountRow, CreditLedgerRow
from bayram.db.models.media_credit import MediaCreditLedgerRow
from bayram.db.models.media_purchase import MediaPurchaseRow
from bayram.media.contracts import JobPhase
from bayram.media.desk import CreditStart, SqlMediaDesk
from bayram.media.service import BetaStart, start_free_beta
from bayram.media.stages import (
    MEDIA_POLL_JOB,
    MEDIA_SCREEN_JOB,
    MEDIA_START_JOB,
    screen_job_id,
    sku_deadline,
)
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
    return build_harness(
        media_settings(settings, is_video_standard_offered=True, video_standard_backend="fake"),
        sessions,
        tmp_path,
        FIXED_NOW,
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
async def _job(harness: Harness, job_id: UUID):  # type: ignore[no-untyped-def]
    async with harness.sessions() as session:
        return await load_job(session, job_id)


def _cap(harness: Harness, **caps: int) -> None:
    harness.rt = replace(harness.rt, settings=harness.rt.settings.model_copy(update=caps))


def _desk(harness: Harness, **settings: Any) -> SqlMediaDesk:
    return SqlMediaDesk(
        harness.sessions,
        queue=harness.queue,
        settings=harness.rt.settings.model_copy(update=settings),
        clock=harness.clock,
    )


async def _screen(harness: Harness, job_id: UUID) -> MediaJobState:
    await harness.queue.enqueue_job(MEDIA_SCREEN_JOB, str(job_id), 0, _job_id=screen_job_id(job_id))
    await harness.drain()
    job = await _job(harness, job_id)
    assert job is not None
    return job.state  # type: ignore[no-any-return]


async def _quoted(harness: Harness, *, kind: MediaKind = MediaKind.IMAGE) -> UUID:
    """A ``quoted`` row, moved there directly (the screen is tested elsewhere)."""
    job_id = await freeze_job(harness, photos=(), kind=kind)
    async with harness.sessions.begin() as session:
        assert await transition(
            session,
            job_id,
            expected=(MediaJobState.SCREENING,),
            to=MediaJobState.QUOTED,
            now=harness.clock(),
        )
    return job_id


async def _paid_and_failed(harness: Harness, *, refund: bool = True) -> UUID:
    """A Payme-paid image that failed; with ``refund``, the one credit it earns."""
    job_id = await _quoted(harness)
    async with harness.sessions.begin() as session:
        assert await mark_paid(
            session,
            job_id,
            paid_via=MediaPaidVia.PAYME,
            now=harness.clock(),
            deadline=sku_deadline(harness.rt.settings, MediaSku.IMAGE),
            expected=(MediaJobState.QUOTED,),
        )
        assert await transition(
            session,
            job_id,
            expected=(MediaJobState.PAID,),
            to=MediaJobState.FAILED,
            now=harness.clock(),
        )
        if refund:
            assert await grant_refund(
                session, job_id, reason=MediaCreditReason.GENERATION_FAILED, now=harness.clock()
            )
    return job_id


async def _balance(harness: Harness, sku: MediaSku = MediaSku.IMAGE) -> int:
    async with harness.sessions() as session:
        return await media_balance(session, telegram_user_id=USER, sku=sku)


async def _ledger(harness: Harness, job_id: UUID) -> list[tuple[int, MediaCreditReason]]:
    async with harness.sessions() as session:
        rows = (
            await session.scalars(
                sa.select(MediaCreditLedgerRow).where(MediaCreditLedgerRow.job_id == job_id)
            )
        ).all()
    return [(row.delta, row.reason) for row in rows]


# ---------------------------------------------------------------------------
# 🎟
# ---------------------------------------------------------------------------
async def test_two_taps_with_one_credit_spend_it_once_and_start_once(harness: Harness) -> None:
    # Arrange
    await _paid_and_failed(harness)
    job_id = await _quoted(harness)
    desk = _desk(harness)

    # Act — the same 🎟 twice (a double tap, or the button on two devices).
    first = await desk.spend_credit(job_id, telegram_user_id=USER, is_paused=False)
    second = await desk.spend_credit(job_id, telegram_user_id=USER, is_paused=False)

    # Assert — one spend, one receipt, one start; the second tap is a stale no-op.
    assert is_ok(first) and first.value is CreditStart.STARTED
    assert is_ok(second) and second.value is CreditStart.STALE
    assert await _balance(harness) == 0
    assert await _ledger(harness, job_id) == [(-1, MediaCreditReason.SPENT)]
    job = await _job(harness, job_id)
    assert job.state is MediaJobState.PAID and job.paid_via is MediaPaidVia.CREDIT
    async with harness.sessions() as session:
        receipts = (
            await session.scalars(
                sa.select(MediaPurchaseRow).where(MediaPurchaseRow.job_id == job_id)
            )
        ).all()
    assert [(r.provider, r.amount_minor) for r in receipts] == [(MediaPurchaseProvider.CREDIT, 0)]
    assert len([i for i in harness.queue.seen if i.startswith(f"media:{job_id}:start")]) == 1


async def test_an_image_credit_never_pays_for_a_video(harness: Harness) -> None:
    # Arrange
    await _paid_and_failed(harness)
    video = await _quoted(harness, kind=MediaKind.VIDEO)

    # Act
    outcome = await _desk(harness).spend_credit(video, telegram_user_id=USER, is_paused=False)

    # Assert
    assert is_ok(outcome) and outcome.value is CreditStart.NO_CREDIT
    assert (await _job(harness, video)).state is MediaJobState.QUOTED
    assert (await _balance(harness), await _balance(harness, MediaSku.VIDEO_STANDARD)) == (1, 0)


async def test_media_credits_leave_the_song_credit_scalar_alone(harness: Harness) -> None:
    # Arrange — the account holds three song credits.
    async with harness.sessions.begin() as session:
        session.add(CreditAccountRow(telegram_user_id=USER, balance=3, lifetime_granted=3))
    await _paid_and_failed(harness)
    job_id = await _quoted(harness)

    # Act
    spent = await _desk(harness).spend_credit(job_id, telegram_user_id=USER, is_paused=False)

    # Assert
    assert is_ok(spent) and spent.value is CreditStart.STARTED
    async with harness.sessions() as session:
        account = await session.get(CreditAccountRow, USER)
        song_rows = await session.scalar(sa.select(sa.func.count()).select_from(CreditLedgerRow))
    assert account is not None and (account.balance, account.lifetime_granted) == (3, 3)
    assert song_rows == 0


# ---------------------------------------------------------------------------
# Refunds
# ---------------------------------------------------------------------------
async def test_the_deadline_then_a_late_generation_failure_grants_one_credit(
    harness: Harness,
) -> None:
    # Arrange — a paid render hangs in "running" past the deadline.
    harness.provider.polls_until_done = 10_000
    job_id = await freeze_job(harness, photos=())
    assert await _screen(harness, job_id) is MediaJobState.QUOTED
    async with harness.sessions.begin() as session:
        assert await mark_paid(
            session,
            job_id,
            paid_via=MediaPaidVia.PAYME,
            now=harness.clock(),
            deadline=sku_deadline(harness.rt.settings, MediaSku.IMAGE),
            expected=(MediaJobState.QUOTED,),
        )
    await harness.queue.enqueue_job(
        MEDIA_START_JOB, str(job_id), 0, _job_id=f"media:{job_id}:start:0"
    )
    await harness.drain(stop=lambda stage: stage.name == MEDIA_POLL_JOB)

    # Act — the sweep fails it on the deadline; then the render comes back FAILED, and the
    # retry policy runs out on a job that is already terminal.
    harness.clock.advance(seconds=harness.rt.settings.media_image_deadline_s + 60)
    summary = await sweep_media(harness.rt)
    harness.provider.polls_until_done = 0
    harness.provider.outcome = JobPhase.FAILED
    await harness.drain()

    # Assert — one credit, for the deadline; the late failure granted nothing.
    job = await _job(harness, job_id)
    assert summary["deadline_failed"] == 1
    assert job.state is MediaJobState.FAILED and job.error_code == "deadline"
    assert await _ledger(harness, job_id) == [(1, MediaCreditReason.DEADLINE)]
    assert await _balance(harness) == 1


# ---------------------------------------------------------------------------
# §7.6 daily caps
# ---------------------------------------------------------------------------
async def test_a_request_past_the_daily_cap_is_refused_before_it_is_screened(
    harness: Harness,
) -> None:
    # Arrange — a cap of one image a day, and one already paid (and failed) today.
    _cap(harness, media_daily_cap_image=1)
    await _paid_and_failed(harness, refund=False)
    screened_before = len(harness.moderator.subjects_screened("text"))
    job_id = await freeze_job(harness, photos=())

    # Act
    state = await _screen(harness, job_id)

    # Assert — refused with the cap's copy, no guard asked, no quote drawn.
    job = await _job(harness, job_id)
    assert state is MediaJobState.REJECTED and job.error_code == "daily_cap"
    assert "today's limit" in harness.messenger.tray_texts()[-1]
    assert len(harness.moderator.subjects_screened("text")) == screened_before

    # Act — the next UTC day, the same account is quoted again.
    harness.clock.advance(days=1)
    tomorrow = await freeze_job(harness, photos=())

    # Assert
    assert await _screen(harness, tomorrow) is MediaJobState.QUOTED


async def test_the_video_cap_does_not_spend_the_image_cap(harness: Harness) -> None:
    _cap(harness, media_daily_cap_image=1, media_daily_cap_video=1)
    await _paid_and_failed(harness, refund=False)

    video = await _quoted(harness, kind=MediaKind.VIDEO)
    started = await start_free_beta(
        harness.sessions,
        harness.queue,
        harness.rt.settings,
        job_id=video,
        telegram_user_id=USER,
        is_paused=False,
        now=harness.clock(),
    )

    assert started is BetaStart.STARTED


async def test_every_press_re_checks_the_daily_cap(harness: Harness) -> None:
    # Arrange — quoted under a cap of two with one paid today; the cap is then lowered to one
    # (a restart with a new env), so the drawn buttons are no longer good.
    await _paid_and_failed(harness)
    job_id = await _quoted(harness)
    capped = harness.rt.settings.model_copy(update={"media_daily_cap_image": 1})

    # Act
    credit = await _desk(harness, media_daily_cap_image=1).spend_credit(
        job_id, telegram_user_id=USER, is_paused=False
    )
    beta = await start_free_beta(
        harness.sessions,
        harness.queue,
        capped,
        job_id=job_id,
        telegram_user_id=USER,
        is_paused=False,
        now=harness.clock(),
    )

    # Assert — nothing paid, nothing spent, nothing started.
    assert is_ok(credit) and credit.value is CreditStart.AT_DAILY_CAP
    assert beta is BetaStart.AT_DAILY_CAP
    assert (await _job(harness, job_id)).state is MediaJobState.QUOTED
    assert await _balance(harness) == 1
    assert not [i for i in harness.queue.seen if i.startswith(f"media:{job_id}:start")]
