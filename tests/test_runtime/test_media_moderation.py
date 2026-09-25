"""Moderation in the stage chain (IMAGE_VIDEO_SPEC §6.4, §6.7, §10 M3.1), over fakes.

The M3.1 acceptance list that needs the job row, each a test below:

* a guard timeout → ``unavailable`` → ``media.busy``, no quote;
* a review before payment → refused, not struck;
* an L0 denylist hit → refused with no guard call, one strike;
* a youth term in the words + ``sexual`` on a photo → the hard rule: rejected, every input
  held **and sealed**, and the held rows and objects survive ``media_cleanup`` and the purge;
  the account suspended until an operator clears it;
* a slogan in an uploaded photo reaches G1 through G8 and refuses the request;
* one of two output images blocked → nothing delivered, one credit, two strikes;
* a CSAM-class output → the outputs held as well;
* strikes suspend, and a suspended account is refused before anything is downloaded;
* the per-account screening budget.
"""

from __future__ import annotations

import dataclasses
from collections.abc import AsyncIterator
from datetime import timedelta
from pathlib import Path
from typing import Final
from uuid import UUID

import httpx
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
from bayram.contracts import is_ok, ok
from bayram.db.engine import create_session_factory
from bayram.db.enums import (
    MediaJobState,
    MediaLegalHoldDecision,
    MediaPaidVia,
    MediaScreenDecision,
)
from bayram.db.media import (
    clear_csam_blocks,
    load_job,
    mark_paid,
    media_balance,
    record_legal_hold_decision,
)
from bayram.db.models import Base
from bayram.db.models.media_input import MediaInputRow, MediaOutputRow
from bayram.db.models.media_job import MediaJobRow
from bayram.db.purge import purge_expired
from bayram.db.retention import RetentionClass
from bayram.media.stages import MEDIA_SCREEN_JOB, MEDIA_START_JOB, screen_job_id, sku_deadline
from bayram.moderation.contracts import CategoryCode
from bayram.moderation.gateway import G1_TEXT_PATH, GatewayGuardModerator
from bayram.moderation.legal_hold import generate_keypair, is_sealed, open_sealed
from bayram.moderation.strikes import SuspensionReason
from bayram.runtime.media_jobs import media_cleanup
from tests.conftest import FIXED_NOW
from tests.test_media.test_guard_moderator import Gateway
from tests.test_runtime.media_fakes import (
    USER,
    Harness,
    build_harness,
    freeze_job,
    jpeg_bytes,
    media_settings,
)

PRIVATE_KEY, PUBLIC_KEY = generate_keypair()
_PHOTO: Final[bytes] = jpeg_bytes((10, 120, 200))


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
        media_settings(settings, media_legal_hold_recipient=PUBLIC_KEY),
        sessions,
        tmp_path,
        FIXED_NOW,
    )


def _use_gateway(harness: Harness, gateway: Gateway) -> None:
    """Swap the fake for the real guard client over a scripted transport."""
    moderator = GatewayGuardModerator(
        base_url="https://guards.example.test",
        api_key="k",
        client=httpx.AsyncClient(transport=httpx.MockTransport(gateway)),
    )
    harness.rt = dataclasses.replace(harness.rt, moderator=moderator)


async def _job(harness: Harness, job_id: UUID) -> MediaJobRow:
    async with harness.sessions() as session:
        job = await load_job(session, job_id)
    assert job is not None
    return job


async def _screen(harness: Harness, job_id: UUID) -> None:
    await harness.queue.enqueue_job(MEDIA_SCREEN_JOB, str(job_id), 0, _job_id=screen_job_id(job_id))
    await harness.drain()


async def _inputs(harness: Harness, job_id: UUID) -> list[MediaInputRow]:
    async with harness.sessions() as session:
        found = await session.scalars(
            sa.select(MediaInputRow).where(MediaInputRow.job_id == job_id)
        )
        return list(found.all())


async def _outputs(harness: Harness, job_id: UUID) -> list[MediaOutputRow]:
    async with harness.sessions() as session:
        found = await session.scalars(
            sa.select(MediaOutputRow).where(MediaOutputRow.job_id == job_id)
        )
        return list(found.all())


async def _strikes(harness: Harness) -> int:
    return len(harness.strikes.strikes.get(USER, {}))


async def _quote_and_pay(harness: Harness, job_id: UUID) -> None:
    await _screen(harness, job_id)
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
    await harness.drain()


# ---------------------------------------------------------------------------
# Fail closed
# ---------------------------------------------------------------------------
async def test_a_guard_timeout_is_busy_and_quotes_nothing(harness: Harness) -> None:
    gateway = Gateway()
    gateway.fail[G1_TEXT_PATH] = httpx.ReadTimeout("slow")
    _use_gateway(harness, gateway)
    job_id = await freeze_job(harness)

    await _screen(harness, job_id)

    job = await _job(harness, job_id)
    assert job.state is MediaJobState.SCREENING
    assert job.screen_decision is MediaScreenDecision.UNAVAILABLE
    assert "fully booked" in harness.messenger.tray_texts()[-1]
    assert await _strikes(harness) == 0


async def test_a_controversial_prompt_is_refused_before_payment_and_not_struck(
    harness: Harness,
) -> None:
    gateway = Gateway()
    gateway.g1_safety["prompt"] = "controversial"
    gateway.g1_categories["prompt"] = ["Politically Sensitive Topics"]
    _use_gateway(harness, gateway)
    job_id = await freeze_job(harness)

    await _screen(harness, job_id)

    job = await _job(harness, job_id)
    assert job.state is MediaJobState.REJECTED
    assert job.screen_decision is MediaScreenDecision.REVIEW
    assert job.screen_categories == ["politics_officials"]
    assert "can't make this one" in harness.messenger.tray_texts()[-1]
    assert await _strikes(harness) == 0


async def test_a_denylisted_prompt_is_refused_with_no_guard_call_and_struck(
    harness: Harness,
) -> None:
    job_id = await freeze_job(harness, prompt="a woman, n​aked, on a beach")

    await _screen(harness, job_id)

    job = await _job(harness, job_id)
    assert job.state is MediaJobState.REJECTED and job.error_code == "screen_refused"
    assert job.screen_categories == ["sexual"]
    assert harness.moderator.calls == []
    assert await _strikes(harness) == 1


async def test_a_slogan_in_an_uploaded_photo_is_refused_through_g8(harness: Harness) -> None:
    gateway = Gateway()
    gateway.g8["photo-0"] = {"ocr_text": "KILL THEM ALL", "caption": "a banner"}
    _use_gateway(harness, gateway)
    job_id = await freeze_job(harness, photos=[_PHOTO])

    await _screen(harness, job_id)

    job = await _job(harness, job_id)
    assert job.state is MediaJobState.REJECTED
    assert job.screen_categories == ["violence"]  # L0 over the OCR text, before G1


# ---------------------------------------------------------------------------
# The hard rule and the legal hold (§6.4, §6.7)
# ---------------------------------------------------------------------------
async def test_a_youth_term_and_a_sexual_photo_hold_the_bytes_through_cleanup_and_purge(
    harness: Harness,
) -> None:
    harness.moderator.decisions["upload"] = MediaScreenDecision.BLOCK
    harness.moderator.categories["upload"] = (CategoryCode.SEXUAL,)
    job_id = await freeze_job(harness, photos=[_PHOTO], prompt="a schoolgirl at the beach")

    await _screen(harness, job_id)

    # Rejected like any other refusal — nothing tells the customer why (SEC-3).
    job = await _job(harness, job_id)
    assert job.state is MediaJobState.REJECTED and job.error_code == "csam_blocked"
    assert set(job.screen_categories or []) == {"sexual", "sexual_minors"}
    assert "can't make this one" in harness.messenger.tray_texts()[-1]
    # Held in the verdict's transaction, and sealed to the escalation owner.
    held = await _inputs(harness, job_id)
    assert held and all(row.retention_class is RetentionClass.LEGAL_HOLD for row in held)
    for row in held:
        assert row.storage_key is not None
        blob = (harness.storage.root / row.storage_key).read_bytes()
        assert is_sealed(blob)
        opened = open_sealed(blob, PRIVATE_KEY)
        assert is_ok(opened) and opened.value[:3] == b"\xff\xd8\xff"
    # Struck three times and suspended until an operator clears it.
    assert await _strikes(harness) == 3
    suspended = await harness.strikes.suspension(USER, now=harness.clock())
    assert suspended is not None and suspended.reason is SuspensionReason.CSAM

    # Cleanup ran already; run it again, then the purge two days on (inside the 72 h).
    await media_cleanup(harness.ctx(), str(job_id))
    report = await purge_expired(harness.sessions, now=FIXED_NOW + timedelta(days=2))
    assert is_ok(report)

    after = await _inputs(harness, job_id)
    assert [row.id for row in after] == [row.id for row in held]
    assert all((harness.storage.root / str(row.storage_key)).exists() for row in after)


async def test_a_suspended_account_is_refused_before_anything_is_downloaded(
    harness: Harness,
) -> None:
    await harness.strikes.suspend(USER, reason=SuspensionReason.CSAM, now=harness.clock())
    job_id = await freeze_job(harness, photos=[_PHOTO])

    await _screen(harness, job_id)

    job = await _job(harness, job_id)
    assert job.state is MediaJobState.REJECTED and job.error_code == "screen_suspended"
    assert "paused for your account" in harness.messenger.tray_texts()[-1]
    assert harness.messenger.edits[-1][3] is None
    assert harness.moderator.calls == []
    assert all(row.storage_key is None for row in await _inputs(harness, job_id))


async def test_three_blocked_requests_suspend_the_account(harness: Harness) -> None:
    harness.moderator.decisions["prompt"] = MediaScreenDecision.BLOCK
    for _ in range(3):
        job_id = await freeze_job(harness)
        await _screen(harness, job_id)
        assert (await _job(harness, job_id)).state is MediaJobState.REJECTED

    harness.moderator.decisions.clear()
    job_id = await freeze_job(harness)
    await _screen(harness, job_id)

    assert (await _job(harness, job_id)).error_code == "screen_suspended"


async def test_the_screening_budget_refuses_unscreened(harness: Harness) -> None:
    harness.rt = dataclasses.replace(
        harness.rt,
        settings=harness.rt.settings.model_copy(update={"media_screen_daily_budget": 2}),
    )
    harness.moderator.decisions["prompt"] = MediaScreenDecision.REVIEW  # refused, not struck
    for _ in range(2):
        job_id = await freeze_job(harness)
        await _screen(harness, job_id)
    screened = len(harness.moderator.calls)

    job_id = await freeze_job(harness)
    await _screen(harness, job_id)

    job = await _job(harness, job_id)
    assert job.state is MediaJobState.REJECTED and job.error_code == "screen_budget"
    assert len(harness.moderator.calls) == screened
    assert await _strikes(harness) == 0


# ---------------------------------------------------------------------------
# L4 (§6.4)
# ---------------------------------------------------------------------------
async def test_one_blocked_output_delivers_nothing_grants_one_credit_and_strikes_twice(
    harness: Harness,
) -> None:
    harness.moderator.item_decisions["output-1"] = MediaScreenDecision.BLOCK
    harness.moderator.item_categories["output-1"] = (CategoryCode.VIOLENCE,)
    job_id = await freeze_job(harness)

    await _quote_and_pay(harness, job_id)

    job = await _job(harness, job_id)
    assert job.state is MediaJobState.FAILED and job.error_code == "output_blocked"
    assert harness.messenger.albums == []
    async with harness.sessions() as session:
        assert await media_balance(session, telegram_user_id=USER, sku=job.sku) == 1
    assert await _strikes(harness) == 2


async def test_a_csam_class_output_holds_the_outputs(harness: Harness) -> None:
    harness.moderator.decisions["output_image"] = MediaScreenDecision.REVIEW
    harness.moderator.categories["output_image"] = (CategoryCode.SEXUAL,)
    job_id = await freeze_job(harness, prompt="two kids at a birthday party")

    await _quote_and_pay(harness, job_id)

    job = await _job(harness, job_id)
    assert job.state is MediaJobState.FAILED and job.error_code == "csam_blocked"
    assert harness.messenger.albums == []
    outputs = await _outputs(harness, job_id)
    assert len(outputs) == 2
    assert all(row.retention_class is RetentionClass.LEGAL_HOLD for row in outputs)
    assert all(is_sealed((harness.storage.root / row.storage_key).read_bytes()) for row in outputs)
    assert await _strikes(harness) == 3


# ---------------------------------------------------------------------------
# M3.R review fixes
# ---------------------------------------------------------------------------
async def _csam_rejected(harness: Harness) -> UUID:
    harness.moderator.decisions["upload"] = MediaScreenDecision.BLOCK
    harness.moderator.categories["upload"] = (CategoryCode.SEXUAL,)
    job_id = await freeze_job(harness, photos=[_PHOTO], prompt="a schoolgirl at the beach")
    await _screen(harness, job_id)
    assert (await _job(harness, job_id)).error_code == "csam_blocked"
    harness.moderator.decisions.clear()
    harness.moderator.categories.clear()
    return job_id


async def test_past_the_hold_the_bytes_go_and_the_row_keeps_the_hash(harness: Harness) -> None:
    # §6.7: "at expiry the bytes are deleted (hash + metadata kept)".
    job_id = await _csam_rejected(harness)
    (held,) = await _inputs(harness, job_id)
    assert held.sha256 is not None and held.storage_key is not None

    report = await purge_expired(harness.sessions, now=FIXED_NOW + timedelta(days=4))
    assert is_ok(report)

    # The purge hands the object back for deletion; the row stays, with its hash.
    assert held.storage_key in report.value.storage_keys
    assert report.value.media_input_holds_deleted == 1
    (after,) = await _inputs(harness, job_id)
    assert after.id == held.id and after.sha256 == held.sha256
    assert after.size_bytes == held.size_bytes and after.deleted_at is not None
    # The request row above it is the record too: the unpaid-request arm leaves it, even
    # past its own 30-day text clock.
    later = await purge_expired(harness.sessions, now=FIXED_NOW + timedelta(days=40))
    assert is_ok(later) and later.value.media_input_holds_deleted == 0
    assert (await _job(harness, job_id)).error_code == "csam_blocked"
    assert [row.id for row in await _inputs(harness, job_id)] == [held.id]


async def test_a_handover_decision_keeps_the_bytes_past_the_clock(harness: Harness) -> None:
    job_id = await _csam_rejected(harness)
    (held,) = await _inputs(harness, job_id)
    async with harness.sessions.begin() as session:
        assert await record_legal_hold_decision(
            session, job_id, MediaLegalHoldDecision.HANDOVER, now=FIXED_NOW
        )

    report = await purge_expired(harness.sessions, now=FIXED_NOW + timedelta(days=4))
    assert is_ok(report)

    assert held.storage_key not in report.value.storage_keys
    (after,) = await _inputs(harness, job_id)
    assert after.deleted_at is None
    assert (harness.storage.root / str(held.storage_key)).exists()

    # The handover done, a delete decision lets the next purge take the bytes.
    async with harness.sessions.begin() as session:
        await record_legal_hold_decision(
            session, job_id, MediaLegalHoldDecision.DELETE, now=FIXED_NOW + timedelta(days=5)
        )
    later = await purge_expired(harness.sessions, now=FIXED_NOW + timedelta(days=5))
    assert is_ok(later) and held.storage_key in later.value.storage_keys
    (gone,) = await _inputs(harness, job_id)
    assert gone.deleted_at is not None and gone.sha256 == held.sha256


async def test_a_csam_suspension_outlives_a_redis_restart_until_an_operator_clears_it(
    harness: Harness,
) -> None:
    await _csam_rejected(harness)
    # Redis restarted without persistence: the counters and the suspension key are gone.
    harness.strikes.suspended.clear()
    harness.strikes.strikes.clear()

    job_id = await freeze_job(harness)
    await _screen(harness, job_id)
    assert (await _job(harness, job_id)).error_code == "screen_suspended"

    async with harness.sessions.begin() as session:
        assert await clear_csam_blocks(session, USER, now=harness.clock()) == 1
    job_id = await freeze_job(harness)
    await _screen(harness, job_id)
    assert (await _job(harness, job_id)).state is MediaJobState.QUOTED


async def test_a_seal_that_raises_does_not_skip_the_suspension(
    harness: Harness, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def broken(*args: object, **kwargs: object) -> object:
        raise RuntimeError("storage exploded")

    monkeypatch.setattr("bayram.runtime.media_jobs.seal_held_objects", broken)

    await _csam_rejected(harness)

    suspended = await harness.strikes.suspension(USER, now=harness.clock())
    assert suspended is not None and suspended.reason is SuspensionReason.CSAM


async def test_a_prompt_over_the_word_cap_is_refused_unstruck_and_unscreened(
    harness: Harness,
) -> None:
    # A length is not a verdict (§6.4 L0): refused, no strike, no guard call.
    job_id = await freeze_job(harness, prompt=" ".join(["a b"] * 81))

    await _screen(harness, job_id)

    job = await _job(harness, job_id)
    assert job.state is MediaJobState.REJECTED and job.error_code == "screen_caps"
    assert harness.moderator.calls == []
    assert await _strikes(harness) == 0


async def test_the_requests_language_reaches_every_guard_call(harness: Harness) -> None:
    job_id = await freeze_job(harness, photos=[_PHOTO])

    await _quote_and_pay(harness, job_id)

    assert harness.moderator.calls
    assert {call.lang_hint for call in harness.moderator.calls} == {"en"}


async def test_an_output_screen_with_no_outputs_delivers_nothing(
    harness: Harness, monkeypatch: pytest.MonkeyPatch
) -> None:
    # §6.3 fail closed: nothing looked at is never an allow.
    async def none(*args: object, **kwargs: object) -> object:
        return ok([])

    monkeypatch.setattr("bayram.runtime.media_jobs._output_paths", none)
    job_id = await freeze_job(harness)

    await _quote_and_pay(harness, job_id)

    job = await _job(harness, job_id)
    assert job.output_decision is not MediaScreenDecision.ALLOW
    assert harness.messenger.albums == []
