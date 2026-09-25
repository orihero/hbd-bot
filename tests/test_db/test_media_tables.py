"""The media tables: state guards, clocks, purge predicates, legal hold, ``/forget``, credits.

IMAGE_VIDEO_SPEC §3.2.2, §3.2.4, §9.3 and §10 M2.1. What is pinned here fails quietly if
nobody looks:

* **Every state move is conditional**, a terminal move sets the text clock, and nothing
  re-opens a terminal row (the one-open-request index would fire inside a money commit).
* **Each ``*_expires_at`` is read by a purge arm that actually deletes**, and the bytes' keys
  come back for the caller to unlink.
* **``legal_hold`` rows survive ``media_cleanup``, ``/forget`` and both ordinary predicates**,
  and leave only on their own clock.
* **``/forget`` removes the objects** and anonymises the receipts.
* **A job refunds at most once**, and ``balance = SUM(delta)``.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import timedelta
from pathlib import Path
from typing import Final
from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from bayram.contracts import Language, Result, StoredObject, is_ok, ok
from bayram.db.enums import (
    MediaAspect,
    MediaAttemptStage,
    MediaCreditReason,
    MediaInputRole,
    MediaJobState,
    MediaKind,
    MediaOutputRole,
    MediaPaidVia,
    MediaPurchaseProvider,
    MediaRefundState,
    MediaSku,
)
from bayram.db.media import (
    MEDIA_REVIEW_SLA,
    add_input,
    add_output,
    cleanup_job_media,
    create_job,
    grant_refund,
    insert_attempt,
    load_job,
    mark_paid,
    media_balance,
    place_legal_hold,
    record_input_stored,
    record_purchase,
    spend_credit,
    transition,
)
from bayram.db.media_erasure import SqlMediaEraser
from bayram.db.models import (
    MediaAttemptRow,
    MediaCreditBalanceRow,
    MediaCreditLedgerRow,
    MediaInputRow,
    MediaJobRow,
    MediaOutputRow,
    MediaPurchaseRow,
    UserRow,
)
from bayram.db.purge import (
    MEDIA_TELEMETRY_RETENTION_DAYS,
    PurgeReport,
    purge_expired,
    rows_past_expiry_statements,
)
from bayram.db.retention import DEFAULT_RETENTION_POLICY, RetentionClass
from bayram.storage import media_key
from tests.test_db.conftest import MovableClock

_USER: Final[int] = 8_912_345_678_901
_OTHER_USER: Final[int] = 7_112_345_678_902
_QUOTE_TTL: Final[timedelta] = timedelta(hours=24)
_IMAGE_DEADLINE: Final[timedelta] = timedelta(minutes=45)
_OUTPUT_DAYS: Final[int] = DEFAULT_RETENTION_POLICY.media_output_days


# ---------------------------------------------------------------------------
# Builders
# ---------------------------------------------------------------------------
async def _user(sessions: async_sessionmaker[AsyncSession], telegram_user_id: int) -> UUID:
    user_id = uuid4()
    async with sessions.begin() as session:
        session.add(UserRow(id=user_id, telegram_user_id=telegram_user_id))
    return user_id


async def _job(
    sessions: async_sessionmaker[AsyncSession],
    clock: MovableClock,
    *,
    user: int = _USER,
    kind: MediaKind = MediaKind.IMAGE,
    state: MediaJobState = MediaJobState.SCREENING,
) -> UUID:
    async with sessions() as session:
        user_id = await session.scalar(
            sa.select(UserRow.id).where(UserRow.telegram_user_id == user)
        )
    if user_id is None:
        user_id = await _user(sessions, user)
    async with sessions.begin() as session:
        return await create_job(
            session,
            user_id=user_id,
            telegram_user_id=user,
            kind=kind,
            sku=MediaSku.IMAGE if kind is MediaKind.IMAGE else MediaSku.VIDEO_STANDARD,
            state=state,
            chat_id=user,
            outputs_requested=2 if kind is MediaKind.IMAGE else 1,
            aspect=MediaAspect.PORTRAIT,
            language=Language.UZ_LATN,
            prompt="a cake on a rooftop at dusk",
            price_minor=500_000,
            currency="UZS",
            now=clock.now,
            quote_ttl=_QUOTE_TTL,
            params={"width": 768, "height": 1344},
        )


async def _move(
    sessions: async_sessionmaker[AsyncSession],
    clock: MovableClock,
    job_id: UUID,
    *path: MediaJobState,
) -> None:
    """Walk a job along ``path``, each step conditional on the previous state."""
    async with sessions.begin() as session:
        current = (await load_job(session, job_id)).state  # type: ignore[union-attr]
        for step in path:
            assert await transition(session, job_id, expected=(current,), to=step, now=clock.now), (
                f"{current} -> {step} was refused"
            )
            current = step


async def _input(
    sessions: async_sessionmaker[AsyncSession],
    clock: MovableClock,
    job_id: UUID,
    *,
    ordinal: int = 0,
    filename: str = "photo-0.jpg",
) -> tuple[UUID, str]:
    key = media_key(job_id, is_output=False, filename=filename)
    async with sessions.begin() as session:
        input_id = await add_input(
            session,
            job_id=job_id,
            ordinal=ordinal,
            role=MediaInputRole.PHOTO,
            tg_file_id="AgACAgIAAxkBAAI",
            tg_file_unique_id="AQADcb0",
            now=clock.now,
        )
        await record_input_stored(
            session, input_id, storage_key=key, mime="image/jpeg", size_bytes=10, sha256="a" * 64
        )
    return input_id, key


async def _output(
    sessions: async_sessionmaker[AsyncSession],
    clock: MovableClock,
    job_id: UUID,
    *,
    role: MediaOutputRole = MediaOutputRole.IMAGE,
    variant: int = 0,
) -> str:
    key = media_key(job_id, is_output=True, filename=f"{role.value}-{variant}.bin")
    async with sessions.begin() as session:
        assert await add_output(
            session, job_id=job_id, role=role, variant=variant, storage_key=key, now=clock.now
        )
    return key


async def _count(sessions: async_sessionmaker[AsyncSession], model: type[object]) -> int:
    async with sessions() as session:
        return int(await session.scalar(sa.select(sa.func.count()).select_from(model)) or 0)


async def _purge(sessions: async_sessionmaker[AsyncSession], clock: MovableClock) -> PurgeReport:
    result = await purge_expired(sessions, now=clock.now)
    assert is_ok(result), result
    return result.value


# ---------------------------------------------------------------------------
# State guards and the text clock
# ---------------------------------------------------------------------------
async def test_a_transition_moves_only_from_the_expected_state(
    sessions: async_sessionmaker[AsyncSession], clock: MovableClock
) -> None:
    # Arrange
    job_id = await _job(sessions, clock)

    # Act
    async with sessions.begin() as session:
        wrong = await transition(
            session,
            job_id,
            expected=(MediaJobState.PAID,),
            to=MediaJobState.QUEUED,
            now=clock.now,
        )
        right = await transition(
            session,
            job_id,
            expected=(MediaJobState.SCREENING,),
            to=MediaJobState.QUOTED,
            now=clock.now,
        )
        again = await transition(
            session,
            job_id,
            expected=(MediaJobState.SCREENING,),
            to=MediaJobState.QUOTED,
            now=clock.now,
        )

    # Assert — the loser of a race is told it lost, and becomes a no-op.
    assert (wrong, right, again) == (False, True, False)


async def test_a_terminal_move_restarts_the_text_clock_and_nothing_reopens_it(
    sessions: async_sessionmaker[AsyncSession], clock: MovableClock
) -> None:
    # Arrange
    job_id = await _job(sessions, clock)
    async with sessions() as session:
        born = (await load_job(session, job_id)).text_expires_at  # type: ignore[union-attr]
    clock.advance(days=2)

    # Act
    await _move(sessions, clock, job_id, MediaJobState.REJECTED)

    # Assert — created + TTL + 30 d at insert; terminal + 30 d once it ends.
    assert born == DEFAULT_RETENTION_POLICY.media_output_expires_at(
        clock.now - timedelta(days=2) + _QUOTE_TTL
    )
    async with sessions() as session:
        ended = (await load_job(session, job_id)).text_expires_at  # type: ignore[union-attr]
    assert ended == clock.now + timedelta(days=_OUTPUT_DAYS)
    async with sessions.begin() as session:
        with pytest.raises(ValueError, match="never moves back"):
            await transition(
                session,
                job_id,
                expected=(MediaJobState.REJECTED,),
                to=MediaJobState.QUOTED,
                now=clock.now,
            )


async def test_one_open_request_per_account_and_kind(
    sessions: async_sessionmaker[AsyncSession], clock: MovableClock
) -> None:
    # Arrange
    first = await _job(sessions, clock)

    # Act / Assert — a second open image request is refused by the database …
    with pytest.raises(IntegrityError):
        await _job(sessions, clock)
    # … a video beside it and another account's image are not …
    await _job(sessions, clock, kind=MediaKind.VIDEO, state=MediaJobState.DRAFTING)
    await _job(sessions, clock, user=_OTHER_USER)
    # … and once the first is over, a new one opens.
    await _move(sessions, clock, first, MediaJobState.CANCELLED)
    await _job(sessions, clock)


async def test_payment_resets_the_upload_clock_to_the_deadline_plus_review(
    sessions: async_sessionmaker[AsyncSession], clock: MovableClock
) -> None:
    # Arrange
    job_id = await _job(sessions, clock)
    input_id, _ = await _input(sessions, clock, job_id)
    await _move(sessions, clock, job_id, MediaJobState.QUOTED)
    clock.advance(seconds=20 * 3600)  # paid late in the 24-hour quote window

    # Act
    async with sessions.begin() as session:
        paid = await mark_paid(
            session, job_id, paid_via=MediaPaidVia.BETA, now=clock.now, deadline=_IMAGE_DEADLINE
        )

    # Assert
    assert paid
    async with sessions() as session:
        row = await session.get(MediaInputRow, input_id)
        job = await load_job(session, job_id)
    assert row is not None and job is not None
    assert row.expires_at == clock.now + _IMAGE_DEADLINE + MEDIA_REVIEW_SLA
    assert (job.state, job.paid_via, job.paid_at) == (
        MediaJobState.PAID,
        MediaPaidVia.BETA,
        clock.now,
    )


# ---------------------------------------------------------------------------
# media_cleanup, the purge and legal hold
# ---------------------------------------------------------------------------
async def test_cleanup_takes_uploads_and_intermediates_and_keeps_the_deliverables(
    sessions: async_sessionmaker[AsyncSession], clock: MovableClock
) -> None:
    # Arrange
    job_id = await _job(sessions, clock, kind=MediaKind.VIDEO, state=MediaJobState.DRAFTING)
    _, photo = await _input(sessions, clock, job_id)
    raw = await _output(sessions, clock, job_id, role=MediaOutputRole.VIDEO_RAW)
    narration = await _output(sessions, clock, job_id, role=MediaOutputRole.NARRATION)
    final = await _output(sessions, clock, job_id, role=MediaOutputRole.VIDEO)

    # Act
    async with sessions.begin() as session:
        keys = await cleanup_job_media(session, job_id)

    # Assert
    assert set(keys) == {photo, raw, narration}
    assert await _count(sessions, MediaInputRow) == 0
    async with sessions() as session:
        kept = (await session.scalars(sa.select(MediaOutputRow.storage_key))).all()
    assert kept == [final]


async def test_a_rejected_jobs_uploads_are_gone_after_cleanup(
    sessions: async_sessionmaker[AsyncSession], clock: MovableClock
) -> None:
    # Arrange
    job_id = await _job(sessions, clock)
    await _input(sessions, clock, job_id)
    await _move(sessions, clock, job_id, MediaJobState.REJECTED)

    # Act
    async with sessions.begin() as session:
        keys = await cleanup_job_media(session, job_id)

    # Assert
    assert len(keys) == 1
    assert await _count(sessions, MediaInputRow) == 0


async def test_every_media_clock_is_read_by_a_purge_that_deletes(
    sessions: async_sessionmaker[AsyncSession], clock: MovableClock
) -> None:
    # Arrange — an upload cleanup never reached, an intermediate and a delivered image.
    job_id = await _job(sessions, clock)
    _, photo = await _input(sessions, clock, job_id)
    raw = await _output(sessions, clock, job_id, role=MediaOutputRole.VIDEO_RAW)
    image = await _output(sessions, clock, job_id, role=MediaOutputRole.IMAGE)

    # Act — a day and a minute: the upload and the intermediate are past, the image is not.
    clock.advance(days=1, seconds=60)
    first = await _purge(sessions, clock)
    clock.advance(days=_OUTPUT_DAYS)
    second = await _purge(sessions, clock)

    # Assert
    assert (first.media_inputs_deleted, first.media_outputs_deleted) == (1, 1)
    assert {photo, raw} <= set(first.storage_keys)
    assert second.media_outputs_deleted == 1
    assert image in second.storage_keys
    assert await _count(sessions, MediaInputRow) == 0
    assert await _count(sessions, MediaOutputRow) == 0


async def test_legal_hold_rows_survive_cleanup_forget_and_purge_until_their_own_clock(
    sessions: async_sessionmaker[AsyncSession], clock: MovableClock
) -> None:
    # Arrange — a CSAM-class block at screening: the job is rejected, its bytes held.
    job_id = await _job(sessions, clock)
    _, photo = await _input(sessions, clock, job_id)
    held_output = await _output(sessions, clock, job_id)
    async with sessions.begin() as session:
        assert await place_legal_hold(session, job_id, now=clock.now) == 2
    await _move(sessions, clock, job_id, MediaJobState.REJECTED)
    storage = _MemoryStorage()

    # Act — cleanup, /forget and a purge 48 hours later: past ``expires_at``, inside the hold.
    async with sessions.begin() as session:
        cleaned = await cleanup_job_media(session, job_id)
    forgotten = await SqlMediaEraser(sessions, storage=storage, clock=clock).forget_media(_USER)
    clock.advance(days=2)
    during = await _purge(sessions, clock)

    # Assert — nothing touched the held rows.
    assert cleaned == ()
    assert is_ok(forgotten) and storage.deleted == []
    assert during.media_inputs_deleted == during.media_outputs_deleted == 0
    assert during.media_input_holds_deleted == during.media_output_holds_deleted == 0
    assert await _count(sessions, MediaInputRow) == 1
    assert await _count(sessions, MediaOutputRow) == 1

    # Act — past the 72-hour hold, and past the job's text clock.
    clock.advance(days=_OUTPUT_DAYS + 1)
    after = await _purge(sessions, clock)

    # Assert — the hold arm deletes both OBJECTS, and keeps both rows — the hash and
    # metadata a report quotes (§6.7, M3.R) — and so the job row above them stays too.
    assert (after.media_input_holds_deleted, after.media_output_holds_deleted) == (1, 1)
    assert {photo, held_output} <= set(after.storage_keys)
    assert after.media_jobs_deleted == 0
    assert await _count(sessions, MediaInputRow) == 1
    assert await _count(sessions, MediaOutputRow) == 1
    async with sessions() as session:
        stamps = [
            *(await session.scalars(sa.select(MediaInputRow.deleted_at))).all(),
            *(await session.scalars(sa.select(MediaOutputRow.deleted_at))).all(),
        ]
    assert stamps == [clock.now, clock.now]

    # And a later run deletes nothing twice.
    clock.advance(days=1)
    again = await _purge(sessions, clock)
    assert (again.media_input_holds_deleted, again.media_output_holds_deleted) == (0, 0)


async def test_a_held_rejection_keeps_its_job_row_past_the_text_clock(
    sessions: async_sessionmaker[AsyncSession], clock: MovableClock
) -> None:
    """Deleting the job row would cascade the held evidence away before its clock (§6.7)."""
    # Arrange — a hold whose clock is, unusually, longer than the job's text clock.
    job_id = await _job(sessions, clock)
    await _input(sessions, clock, job_id)
    await _move(sessions, clock, job_id, MediaJobState.REJECTED)
    async with sessions.begin() as session:
        await session.execute(
            sa.update(MediaInputRow).values(
                retention_class=RetentionClass.LEGAL_HOLD,
                legal_hold_expires_at=clock.now + timedelta(days=90),
            )
        )

    # Act
    clock.advance(days=_OUTPUT_DAYS + 1)
    report = await _purge(sessions, clock)

    # Assert — the text went, the row did not.
    assert report.media_job_texts_purged == 1
    assert report.media_jobs_deleted == 0
    assert await _count(sessions, MediaJobRow) == 1


async def test_the_words_go_on_their_clock_and_a_paid_row_stays(
    sessions: async_sessionmaker[AsyncSession], clock: MovableClock
) -> None:
    # Arrange — one unpaid abandoned request, one delivered paid one.
    abandoned = await _job(sessions, clock)
    await _move(sessions, clock, abandoned, MediaJobState.ABANDONED)
    delivered = await _job(sessions, clock)
    await _move(sessions, clock, delivered, MediaJobState.QUOTED)
    async with sessions.begin() as session:
        await mark_paid(
            session, delivered, paid_via=MediaPaidVia.BETA, now=clock.now, deadline=_IMAGE_DEADLINE
        )
    await _move(
        sessions,
        clock,
        delivered,
        MediaJobState.QUEUED,
        MediaJobState.GENERATING,
        MediaJobState.POST,
        MediaJobState.DELIVERING,
        MediaJobState.DELIVERED,
    )

    # Act
    clock.advance(days=_OUTPUT_DAYS + 1)
    report = await _purge(sessions, clock)

    # Assert — the unpaid row is gone whole; the paid one kept, word-less, with proof.
    assert report.media_jobs_deleted == 1
    async with sessions() as session:
        kept = await load_job(session, delivered)
        gone = await load_job(session, abandoned)
    assert gone is None
    assert kept is not None
    assert (kept.prompt, kept.narration_text, kept.voice_transcript) == (None, None, None)
    assert kept.text_purged_at == clock.now


async def test_telemetry_and_anonymised_receipts_leave_on_the_cutoff(
    sessions: async_sessionmaker[AsyncSession], clock: MovableClock
) -> None:
    # Arrange — an attempt, and two receipts of which one is anonymised.
    job_id = await _job(sessions, clock)
    async with sessions.begin() as session:
        assert await insert_attempt(
            session,
            job_id=job_id,
            stage=MediaAttemptStage.IMAGE,
            variant=0,
            attempt=1,
            provider="local_gateway",
            now=clock.now,
        )
        for user, key in ((_USER, "kept"), (_OTHER_USER, "swept")):
            await record_purchase(
                session,
                telegram_user_id=user,
                job_id=job_id,
                sku=MediaSku.IMAGE,
                amount_minor=500_000,
                currency="UZS",
                provider=MediaPurchaseProvider.PAYME,
                reference=key,
                idempotency_key=key,
                now=clock.now,
            )
        await session.execute(
            sa.update(MediaPurchaseRow)
            .where(MediaPurchaseRow.telegram_user_id == _OTHER_USER)
            .values(telegram_user_id=None)
        )

    # Act
    clock.advance(days=MEDIA_TELEMETRY_RETENTION_DAYS + 1)
    report = await _purge(sessions, clock)

    # Assert — an identified receipt is never swept.
    assert (report.media_attempts_deleted, report.media_purchases_deleted) == (1, 1)
    async with sessions() as session:
        left = (await session.scalars(sa.select(MediaPurchaseRow.reference))).all()
    assert left == ["kept"]


async def test_the_backlog_counts_line_up_with_the_sweeps(
    sessions: async_sessionmaker[AsyncSession], clock: MovableClock
) -> None:
    # Arrange
    job_id = await _job(sessions, clock)
    await _input(sessions, clock, job_id)
    clock.advance(days=2)

    # Act
    statements = dict(rows_past_expiry_statements(now=clock.now))
    async with sessions() as session:
        backlog = await session.scalar(statements["media_inputs_deleted"])
    report = await _purge(sessions, clock)

    # Assert
    assert backlog == report.media_inputs_deleted == 1


# ---------------------------------------------------------------------------
# /forget
# ---------------------------------------------------------------------------
class _MemoryStorage:
    """Records deletes; the rest of the protocol is never reached here."""

    def __init__(self) -> None:
        self.deleted: list[str] = []

    async def put(self, key: str, data: bytes, *, content_type: str) -> Result[StoredObject]:
        raise NotImplementedError

    async def put_file(self, key: str, src: Path, *, content_type: str) -> Result[StoredObject]:
        raise NotImplementedError

    async def get(self, key: str) -> Result[bytes]:
        raise NotImplementedError

    async def signed_url(self, key: str, *, ttl_s: int) -> Result[str]:
        raise NotImplementedError

    async def delete(self, key: str) -> Result[None]:
        self.deleted.append(key)
        return ok(None)

    async def size(self, key: str) -> Result[int]:
        raise NotImplementedError

    async def open_range(self, key: str, *, start: int, end: int) -> Result[AsyncIterator[bytes]]:
        raise NotImplementedError


async def test_forget_removes_the_objects_and_the_words_and_keeps_the_receipt(
    sessions: async_sessionmaker[AsyncSession], clock: MovableClock
) -> None:
    # Arrange — a quoted image (pre-pay) and a paid video in flight, each with bytes; a
    # receipt, a refund on the ledger and a balance; and another account's upload.
    quoted = await _job(sessions, clock)
    _, quoted_photo = await _input(sessions, clock, quoted)
    await _move(sessions, clock, quoted, MediaJobState.QUOTED)
    running = await _job(sessions, clock, kind=MediaKind.VIDEO, state=MediaJobState.DRAFTING)
    _, voice = await _input(sessions, clock, running, filename="voice.ogg")
    raw = await _output(sessions, clock, running, role=MediaOutputRole.VIDEO_RAW)
    await _move(sessions, clock, running, MediaJobState.SCREENING, MediaJobState.QUOTED)
    async with sessions.begin() as session:
        await mark_paid(
            session, running, paid_via=MediaPaidVia.PAYME, now=clock.now, deadline=_IMAGE_DEADLINE
        )
        await record_purchase(
            session,
            telegram_user_id=_USER,
            job_id=running,
            sku=MediaSku.VIDEO_STANDARD,
            amount_minor=2_500_000,
            currency="UZS",
            provider=MediaPurchaseProvider.PAYME,
            reference="payme-1",
            idempotency_key="payme-1",
            now=clock.now,
        )
        assert await grant_refund(
            session, running, reason=MediaCreditReason.GENERATION_FAILED, now=clock.now
        )
    other = await _job(sessions, clock, user=_OTHER_USER)
    _, other_photo = await _input(sessions, clock, other)
    storage = _MemoryStorage()

    # Act
    result = await SqlMediaEraser(sessions, storage=storage, clock=clock).forget_media(_USER)

    # Assert — the objects went, and only this account's.
    assert is_ok(result)
    assert set(storage.deleted) == {quoted_photo, voice, raw}
    assert other_photo not in storage.deleted
    async with sessions() as session:
        quoted_row = await load_job(session, quoted)
        running_row = await load_job(session, running)
        purchase = await session.scalar(sa.select(MediaPurchaseRow))
        ledger = await session.scalar(sa.select(MediaCreditLedgerRow))
    assert quoted_row is not None and running_row is not None
    assert purchase is not None and ledger is not None
    # The unpaid request is cancelled; the paid one is marked, not forced to a state.
    assert quoted_row.state is MediaJobState.CANCELLED
    assert running_row.state is MediaJobState.PAID
    assert running_row.forget_requested_at == clock.now
    for row in (quoted_row, running_row):
        assert (row.prompt, row.narration_text, row.voice_transcript) == (None, None, None)
        assert row.text_purged_at == clock.now
    # The receipt and the ledger survive, anonymous; the balance does not.
    assert (purchase.telegram_user_id, purchase.amount_minor) == (None, 2_500_000)
    assert (ledger.telegram_user_id, ledger.delta) == (None, 1)
    assert await _count(sessions, MediaCreditBalanceRow) == 0
    assert await _count(sessions, MediaInputRow) == 1  # the other account's

    # Act / Assert — idempotent.
    again = await SqlMediaEraser(sessions, storage=_MemoryStorage(), clock=clock).forget_media(
        _USER
    )
    assert is_ok(again) and again.value == 0


# ---------------------------------------------------------------------------
# The kind-scoped credit
# ---------------------------------------------------------------------------
async def _paid_job(
    sessions: async_sessionmaker[AsyncSession],
    clock: MovableClock,
    *,
    paid_via: MediaPaidVia = MediaPaidVia.PAYME,
    user: int = _USER,
) -> UUID:
    job_id = await _job(sessions, clock, user=user)
    await _move(sessions, clock, job_id, MediaJobState.QUOTED)
    async with sessions.begin() as session:
        assert await mark_paid(
            session, job_id, paid_via=paid_via, now=clock.now, deadline=_IMAGE_DEADLINE
        )
    return job_id


async def _reconciles(sessions: async_sessionmaker[AsyncSession], user: int) -> int:
    async with sessions() as session:
        balance = await media_balance(session, telegram_user_id=user, sku=MediaSku.IMAGE)
        total = await session.scalar(
            sa.select(sa.func.coalesce(sa.func.sum(MediaCreditLedgerRow.delta), 0)).where(
                MediaCreditLedgerRow.telegram_user_id == user,
                MediaCreditLedgerRow.sku == MediaSku.IMAGE,
            )
        )
    assert balance == total, f"balance {balance} but the ledger sums to {total}"
    return balance


async def test_a_job_refunds_at_most_once_whatever_the_reason(
    sessions: async_sessionmaker[AsyncSession], clock: MovableClock
) -> None:
    # Arrange
    job_id = await _paid_job(sessions, clock)

    # Act — the deadline fails it, then a late generation failure and an output block.
    granted = []
    for reason in (
        MediaCreditReason.DEADLINE,
        MediaCreditReason.GENERATION_FAILED,
        MediaCreditReason.OUTPUT_BLOCKED,
    ):
        async with sessions.begin() as session:
            granted.append(await grant_refund(session, job_id, reason=reason, now=clock.now))

    # Assert
    assert granted == [True, False, False]
    assert await _reconciles(sessions, _USER) == 1
    async with sessions() as session:
        job = await load_job(session, job_id)
    assert job is not None and job.refund_state is MediaRefundState.GRANTED


async def test_a_second_refund_row_for_a_job_is_refused_by_the_database(
    sessions: async_sessionmaker[AsyncSession], clock: MovableClock
) -> None:
    """The partial unique index is the second layer behind the ``refund_state`` claim."""
    # Arrange
    job_id = await _paid_job(sessions, clock)
    async with sessions.begin() as session:
        await grant_refund(session, job_id, reason=MediaCreditReason.DEADLINE, now=clock.now)

    # Act / Assert
    with pytest.raises(IntegrityError):
        async with sessions.begin() as session:
            session.add(
                MediaCreditLedgerRow(
                    telegram_user_id=_USER,
                    sku=MediaSku.IMAGE,
                    delta=1,
                    reason=MediaCreditReason.OUTPUT_BLOCKED,
                    job_id=job_id,
                    created_at=clock.now,
                )
            )


async def test_a_free_beta_failure_grants_nothing(
    sessions: async_sessionmaker[AsyncSession], clock: MovableClock
) -> None:
    # Arrange
    job_id = await _paid_job(sessions, clock, paid_via=MediaPaidVia.BETA)

    # Act
    async with sessions.begin() as session:
        granted = await grant_refund(
            session, job_id, reason=MediaCreditReason.GENERATION_FAILED, now=clock.now
        )

    # Assert
    assert not granted
    assert await _reconciles(sessions, _USER) == 0


async def test_a_credit_pays_for_exactly_one_quoted_job(
    sessions: async_sessionmaker[AsyncSession], clock: MovableClock
) -> None:
    # Arrange — one credit, from a paid job that failed, and a new quoted request.
    failed = await _paid_job(sessions, clock)
    async with sessions.begin() as session:
        await grant_refund(session, failed, reason=MediaCreditReason.DEADLINE, now=clock.now)
    await _move(sessions, clock, failed, MediaJobState.FAILED)
    first = await _job(sessions, clock)
    await _move(sessions, clock, first, MediaJobState.QUOTED)

    # Act
    async with sessions.begin() as session:
        spent = await spend_credit(session, first, now=clock.now, deadline=_IMAGE_DEADLINE)
    await _move(sessions, clock, first, MediaJobState.QUEUED, MediaJobState.GENERATING)
    await _move(sessions, clock, first, MediaJobState.FAILED)
    second = await _job(sessions, clock)
    await _move(sessions, clock, second, MediaJobState.QUOTED)
    async with sessions.begin() as session:
        broke = await spend_credit(session, second, now=clock.now, deadline=_IMAGE_DEADLINE)

    # Assert — spent once; the second tap found no balance and left its job quoted.
    assert (spent, broke) == (True, False)
    assert await _reconciles(sessions, _USER) == 0
    async with sessions() as session:
        paid = await load_job(session, first)
        still = await load_job(session, second)
        receipt = await session.scalar(sa.select(MediaPurchaseRow))
    assert paid is not None and paid.paid_via is MediaPaidVia.CREDIT
    assert still is not None and still.state is MediaJobState.QUOTED
    assert receipt is not None
    assert (receipt.provider, receipt.amount_minor) == (MediaPurchaseProvider.CREDIT, 0)


async def test_a_spend_on_a_job_that_is_no_longer_quoted_puts_the_credit_back(
    sessions: async_sessionmaker[AsyncSession], clock: MovableClock
) -> None:
    # Arrange
    failed = await _paid_job(sessions, clock)
    async with sessions.begin() as session:
        await grant_refund(session, failed, reason=MediaCreditReason.DEADLINE, now=clock.now)
    await _move(sessions, clock, failed, MediaJobState.FAILED)
    job_id = await _job(sessions, clock)
    await _move(sessions, clock, job_id, MediaJobState.CANCELLED)

    # Act
    async with sessions.begin() as session:
        spent = await spend_credit(session, job_id, now=clock.now, deadline=_IMAGE_DEADLINE)

    # Assert
    assert not spent
    assert await _reconciles(sessions, _USER) == 1


async def test_an_attempt_is_written_once_so_a_crash_is_never_posted_twice(
    sessions: async_sessionmaker[AsyncSession], clock: MovableClock
) -> None:
    # Arrange
    job_id = await _job(sessions, clock)

    # Act
    async with sessions.begin() as session:
        first = await insert_attempt(
            session,
            job_id=job_id,
            stage=MediaAttemptStage.IMAGE,
            variant=0,
            attempt=1,
            provider="local_gateway",
            now=clock.now,
        )
        replay = await insert_attempt(
            session,
            job_id=job_id,
            stage=MediaAttemptStage.IMAGE,
            variant=0,
            attempt=1,
            provider="local_gateway",
            now=clock.now,
        )

    # Assert
    assert first is not None and replay is None
    assert await _count(sessions, MediaAttemptRow) == 1
