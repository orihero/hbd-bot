"""The FIL-7 retention schedule, asserted clock by clock.

Every test here advances a fake clock instead of waiting, so "thirteen months later" costs
microseconds. The periods under test are legal obligations (SoW FIL-7, LR-52), which is why
each one gets its own test rather than a single "purge works" assertion: a regression that
silently keeps recipient names for twelve months instead of ninety days is not a bug that
should be able to hide inside a passing suite.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path, PurePosixPath
from typing import Final
from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from bayram.contracts import (
    BroadcastKind,
    BroadcastRecipientState,
    BroadcastState,
    Language,
    Order,
    OrderState,
    Script,
    is_err,
    is_ok,
)
from bayram.db.attempts import GenerationAttempt, GenerationAttemptRepository
from bayram.db.enums import GenerationKind, NameSource
from bayram.db.models import (
    AssetRow,
    BriefRow,
    BroadcastRecipientRow,
    BroadcastRow,
    GenerationAttemptRow,
    NameRecordRow,
    OrderRow,
)
from bayram.db.names import NameRecordDraft, NameRecordRepository
from bayram.db.purge import purge_expired
from bayram.db.repository import SqlKitRepository
from bayram.db.retention import DEFAULT_RETENTION_POLICY, RetentionClass, RetentionPolicy
from bayram.storage import archive_key
from tests.conftest import make_brief, make_candidates, make_lyrics
from tests.test_db.conftest import MovableClock, build_kit, new_order

_DAYS_IN_A_YEAR = 365


async def _delivered_order_with_kit(
    repository: SqlKitRepository, tmp_path: Path, clock: MovableClock, *, is_paid: bool = True
) -> Order:
    """Create an order, optionally authorise it, and save its kit.

    A helper rather than a fixture on purpose: whether the order was authorised decides its
    retention class, so every caller states it out loud instead of inheriting it.
    """
    order = new_order(state=OrderState.BRIEF_READY)
    await repository.create_order(order)
    if is_paid:
        await repository.set_order_state(order.id, OrderState.AUTHORIZED, now=clock.now)
    await repository.save_kit(build_kit(tmp_path, order.id))
    return order


# ---------------------------------------------------------------------------
# Paid audio — 12 months
# ---------------------------------------------------------------------------
async def test_paid_audio_survives_eleven_months(
    repository: SqlKitRepository,
    sessions: async_sessionmaker[AsyncSession],
    tmp_path: Path,
    clock: MovableClock,
) -> None:
    # Arrange
    order = await _delivered_order_with_kit(repository, tmp_path, clock)

    # Act
    result = await purge_expired(sessions, now=clock.advance(days=330))

    # Assert
    assert is_ok(result)
    async with sessions() as session:
        remaining = await session.scalar(
            sa.select(sa.func.count()).select_from(AssetRow).where(AssetRow.order_id == order.id)
        )
    assert remaining == 5


async def test_paid_audio_is_purged_after_twelve_months(
    repository: SqlKitRepository,
    sessions: async_sessionmaker[AsyncSession],
    tmp_path: Path,
    clock: MovableClock,
) -> None:
    # Arrange
    order = await _delivered_order_with_kit(repository, tmp_path, clock)

    # Act
    result = await purge_expired(sessions, now=clock.advance(days=_DAYS_IN_A_YEAR + 1))

    # Assert
    assert is_ok(result)
    assert result.value.assets_deleted == 5
    async with sessions() as session:
        remaining = await session.scalar(
            sa.select(sa.func.count()).select_from(AssetRow).where(AssetRow.order_id == order.id)
        )
    assert remaining == 0


async def test_free_tier_output_is_purged_at_thirty_days(
    repository: SqlKitRepository,
    sessions: async_sessionmaker[AsyncSession],
    tmp_path: Path,
    clock: MovableClock,
) -> None:
    # Arrange — never authorised, so it is free-tier output, not paid audio.
    order = await _delivered_order_with_kit(repository, tmp_path, clock, is_paid=False)

    # Act
    result = await purge_expired(sessions, now=clock.advance(days=31))

    # Assert
    assert is_ok(result)
    assert result.value.assets_deleted == 5
    async with sessions() as session:
        remaining = await session.scalar(
            sa.select(sa.func.count()).select_from(AssetRow).where(AssetRow.order_id == order.id)
        )
    assert remaining == 0


async def test_free_and_paid_assets_get_different_retention_classes(
    repository: SqlKitRepository,
    sessions: async_sessionmaker[AsyncSession],
    tmp_path: Path,
    clock: MovableClock,
) -> None:
    # Arrange
    paid = await _delivered_order_with_kit(repository, tmp_path, clock, is_paid=True)
    free = await _delivered_order_with_kit(repository, tmp_path, clock, is_paid=False)

    # Act
    async with sessions() as session:
        paid_class = await session.scalar(
            sa.select(AssetRow.retention_class).where(AssetRow.order_id == paid.id).limit(1)
        )
        free_class = await session.scalar(
            sa.select(AssetRow.retention_class).where(AssetRow.order_id == free.id).limit(1)
        )

    # Assert
    assert paid_class is RetentionClass.PAID_AUDIO
    assert free_class is RetentionClass.FREE_OUTPUT


async def test_purge_returns_storage_keys_rather_than_deleting_objects_itself(
    repository: SqlKitRepository,
    sessions: async_sessionmaker[AsyncSession],
    tmp_path: Path,
    clock: MovableClock,
) -> None:
    # Arrange
    order = await _delivered_order_with_kit(repository, tmp_path, clock)
    async with sessions.begin() as session:
        await session.execute(
            sa.update(AssetRow)
            .where(AssetRow.order_id == order.id)
            .values(storage_key="kits/abc/song.mp3")
        )

    # Act
    result = await purge_expired(sessions, now=clock.advance(days=_DAYS_IN_A_YEAR + 1))

    # Assert — this module owns rows, not buckets; the caller deletes the bytes.
    assert is_ok(result)
    assert "kits/abc/song.mp3" in result.value.storage_keys


async def test_a_row_written_before_storage_key_existed_still_yields_its_archive_key(
    repository: SqlKitRepository,
    sessions: async_sessionmaker[AsyncSession],
    tmp_path: Path,
    clock: MovableClock,
) -> None:
    """The historical half of the archive-orphan fix.

    Every row written before ``_replace_assets`` recorded ``storage_key`` has NULL there
    and bytes sitting in the archive under a key nobody wrote down. The pairing is still
    recoverable from ``order_id`` and ``path``, so the sweep reconstructs it — through the
    same function the ``put`` used, because two spellings of the key is the bug itself.
    """
    # Arrange — a legacy row: the key is nulled back out after ``save_kit`` wrote it.
    order = await _delivered_order_with_kit(repository, tmp_path, clock)
    async with sessions.begin() as session:
        await session.execute(
            sa.update(AssetRow).where(AssetRow.order_id == order.id).values(storage_key=None)
        )
        kit_assets = list(
            (
                await session.scalars(sa.select(AssetRow.path).where(AssetRow.order_id == order.id))
            ).all()
        )

    # Act
    result = await purge_expired(sessions, now=clock.advance(days=_DAYS_IN_A_YEAR + 1))

    # Assert — one reconstructed key per row, spelled exactly as the archive spelled it.
    assert is_ok(result)
    assert set(result.value.storage_keys) == {
        archive_key(order.id, PurePosixPath(path).name) for path in kit_assets
    }


async def test_a_recorded_key_is_handed_over_verbatim_rather_than_reconstructed(
    repository: SqlKitRepository,
    sessions: async_sessionmaker[AsyncSession],
    tmp_path: Path,
    clock: MovableClock,
) -> None:
    """A row that knows where its bytes are is believed, even when the guess would differ."""
    # Arrange
    order = await _delivered_order_with_kit(repository, tmp_path, clock)
    async with sessions.begin() as session:
        await session.execute(
            sa.update(AssetRow)
            .where(AssetRow.order_id == order.id)
            .values(storage_key="legacy/bucket/somewhere-else.mp3")
        )

    # Act
    result = await purge_expired(sessions, now=clock.advance(days=_DAYS_IN_A_YEAR + 1))

    # Assert
    assert is_ok(result)
    assert set(result.value.storage_keys) == {"legacy/bucket/somewhere-else.mp3"}


@pytest.mark.parametrize(
    "stored_path",
    [
        "C:\\Users\\bayram\\song.mp3",  # a Windows path: the whole string is one "name"
        "/var/lib/bayram/song file.mp3",  # a space is not a shape the pipeline produces
        "",  # a corrupt row: no path at all
        "/var/lib/bayram/" + "x" * 129 + ".mp3",  # longer than any name it writes
    ],
)
async def test_a_legacy_path_that_is_not_a_pipeline_filename_yields_no_key(
    repository: SqlKitRepository,
    sessions: async_sessionmaker[AsyncSession],
    tmp_path: Path,
    clock: MovableClock,
    stored_path: str,
) -> None:
    """Stored data is untrusted on read, and this output is handed straight to a delete.

    Reporting "no key" is recoverable. Reporting a key assembled out of an unrecognised
    filename is a retention sweep aimed at whatever else the key namespace can address, so
    an unrecognised shape withholds the guess instead of making one.
    """
    # Arrange
    order = await _delivered_order_with_kit(repository, tmp_path, clock)
    async with sessions.begin() as session:
        await session.execute(
            sa.update(AssetRow)
            .where(AssetRow.order_id == order.id)
            .values(storage_key=None, path=stored_path)
        )

    # Act
    result = await purge_expired(sessions, now=clock.advance(days=_DAYS_IN_A_YEAR + 1))

    # Assert — the rows are still deleted; only the guess is withheld.
    assert is_ok(result)
    assert result.value.storage_keys == ()
    assert result.value.assets_deleted == 5


async def test_a_reconstructed_key_is_built_from_the_filename_and_nothing_else(
    repository: SqlKitRepository,
    sessions: async_sessionmaker[AsyncSession],
    tmp_path: Path,
    clock: MovableClock,
) -> None:
    """A traversing directory part cannot travel into the key: only the basename is used."""
    # Arrange
    order = await _delivered_order_with_kit(repository, tmp_path, clock)
    async with sessions.begin() as session:
        await session.execute(
            sa.update(AssetRow)
            .where(AssetRow.order_id == order.id)
            .values(storage_key=None, path="/var/lib/bayram/../../../etc/song.mp3")
        )

    # Act
    result = await purge_expired(sessions, now=clock.advance(days=_DAYS_IN_A_YEAR + 1))

    # Assert
    assert is_ok(result)
    assert set(result.value.storage_keys) == {archive_key(order.id, "song.mp3")}


# ---------------------------------------------------------------------------
# Free-text brief — 30 days
# ---------------------------------------------------------------------------
async def test_free_text_note_survives_twenty_nine_days(
    repository: SqlKitRepository,
    sessions: async_sessionmaker[AsyncSession],
    tmp_path: Path,
    clock: MovableClock,
) -> None:
    # Arrange
    order = await _delivered_order_with_kit(repository, tmp_path, clock)

    # Act
    await purge_expired(sessions, now=clock.advance(days=29))

    # Assert
    async with sessions() as session:
        note = await session.scalar(sa.select(BriefRow.note).where(BriefRow.order_id == order.id))
    assert note is not None


async def test_free_text_note_is_cleared_at_thirty_days(
    repository: SqlKitRepository,
    sessions: async_sessionmaker[AsyncSession],
    tmp_path: Path,
    clock: MovableClock,
) -> None:
    # Arrange
    order = await _delivered_order_with_kit(repository, tmp_path, clock)

    # Act
    result = await purge_expired(sessions, now=clock.advance(days=31))

    # Assert
    assert is_ok(result)
    assert result.value.brief_notes_purged == 1
    async with sessions() as session:
        row = (
            await session.execute(sa.select(BriefRow).where(BriefRow.order_id == order.id))
        ).scalar_one()
    assert row.note is None
    assert row.note_purged_at is not None


async def test_clearing_the_note_leaves_the_structured_answers_intact(
    repository: SqlKitRepository,
    sessions: async_sessionmaker[AsyncSession],
    tmp_path: Path,
    clock: MovableClock,
) -> None:
    # Arrange
    order = await _delivered_order_with_kit(repository, tmp_path, clock)

    # Act
    await purge_expired(sessions, now=clock.advance(days=31))

    # Assert — occasion and genre are not personal data and the order still needs them.
    async with sessions() as session:
        row = (
            await session.execute(sa.select(BriefRow).where(BriefRow.order_id == order.id))
        ).scalar_one()
    assert row.occasion is not None
    assert row.genre is not None


async def test_the_approved_lyric_is_cleared_by_the_same_thirty_day_clock(
    repository: SqlKitRepository,
    sessions: async_sessionmaker[AsyncSession],
    clock: MovableClock,
) -> None:
    # Arrange — the lyric names the recipient in its hook, so it is free text about them.
    order = new_order(brief=make_brief(approved_lyrics=make_lyrics()))
    await repository.create_order(order)

    # Act
    result = await purge_expired(sessions, now=clock.advance(days=31))

    # Assert
    assert is_ok(result)
    assert result.value.brief_notes_purged == 1
    async with sessions() as session:
        row = (
            await session.execute(sa.select(BriefRow).where(BriefRow.order_id == order.id))
        ).scalar_one()
    assert row.approved_lyrics is None
    assert row.note is None
    assert row.note_purged_at is not None


async def test_the_approved_lyric_survives_twenty_nine_days(
    repository: SqlKitRepository,
    sessions: async_sessionmaker[AsyncSession],
    clock: MovableClock,
) -> None:
    # Arrange
    order = new_order(brief=make_brief(approved_lyrics=make_lyrics()))
    await repository.create_order(order)

    # Act
    await purge_expired(sessions, now=clock.advance(days=29))

    # Assert — a re-send inside the window must still deliver the words that were approved.
    async with sessions() as session:
        stored = await session.scalar(
            sa.select(BriefRow.approved_lyrics).where(BriefRow.order_id == order.id)
        )
    assert stored is not None


async def test_a_brief_with_a_lyric_and_no_note_is_still_swept(
    repository: SqlKitRepository,
    sessions: async_sessionmaker[AsyncSession],
    clock: MovableClock,
) -> None:
    # Arrange — a customer who skipped the note but approved a lyric. The sweep's predicate
    # is an OR precisely so this row is not left behind holding a person's name.
    order = new_order(brief=make_brief(note="", approved_lyrics=make_lyrics()))
    await repository.create_order(order)
    async with sessions() as session:
        assert (
            await session.scalar(sa.select(BriefRow.note).where(BriefRow.order_id == order.id))
        ) is None

    # Act
    result = await purge_expired(sessions, now=clock.advance(days=31))

    # Assert
    assert is_ok(result)
    assert result.value.brief_notes_purged == 1
    async with sessions() as session:
        row = (
            await session.execute(sa.select(BriefRow).where(BriefRow.order_id == order.id))
        ).scalar_one()
    assert row.approved_lyrics is None
    assert row.note_purged_at is not None


async def test_a_purged_brief_is_not_re_purged_on_the_next_run(
    repository: SqlKitRepository,
    sessions: async_sessionmaker[AsyncSession],
    clock: MovableClock,
) -> None:
    # Arrange — one brief with both free-text columns, one with only the lyric. Nulling one
    # column and not the other would make the nightly job churn these rows forever.
    with_both = new_order(brief=make_brief(approved_lyrics=make_lyrics()))
    lyric_only = new_order(brief=make_brief(note="", approved_lyrics=make_lyrics()))
    await repository.create_order(with_both)
    await repository.create_order(lyric_only)
    first = await purge_expired(sessions, now=clock.advance(days=31))

    # Act
    second = await purge_expired(sessions, now=clock.advance(days=1))

    # Assert — idempotent: the widened OR predicate must not re-select a cleared row.
    assert is_ok(first)
    assert first.value.brief_notes_purged == 2
    assert is_ok(second)
    assert second.value.brief_notes_purged == 0


async def test_the_identity_clock_also_clears_the_lyric_when_it_runs_first(
    sessions: async_sessionmaker[AsyncSession],
    clock: MovableClock,
) -> None:
    # Arrange — a policy whose note clock outlives its identity clock. Nothing forbids it,
    # and the recipient's name is sung verbatim in the lyric's hook section.
    policy = RetentionPolicy(brief_text_days=60, recipient_identity_days=30)
    repository = SqlKitRepository(sessions, policy=policy, clock=clock)
    order = new_order(brief=make_brief(approved_lyrics=make_lyrics()))
    await repository.create_order(order)

    # Act
    result = await purge_expired(sessions, now=clock.advance(days=31), policy=policy)

    # Assert — the name is gone from every column it lived in, on its own clock.
    assert is_ok(result)
    assert result.value.brief_identities_purged == 1
    assert result.value.brief_notes_purged == 0
    async with sessions() as session:
        row = (
            await session.execute(sa.select(BriefRow).where(BriefRow.order_id == order.id))
        ).scalar_one()
    assert row.approved_lyrics is None
    assert row.recipient_name_display is None
    # The note clock has not run, so its audit column must not claim that it has.
    assert row.note is not None
    assert row.note_purged_at is None


# ---------------------------------------------------------------------------
# Recipient identity — 90 days
# ---------------------------------------------------------------------------
async def test_recipient_identity_survives_eighty_nine_days(
    repository: SqlKitRepository,
    sessions: async_sessionmaker[AsyncSession],
    tmp_path: Path,
    clock: MovableClock,
) -> None:
    # Arrange
    order = await _delivered_order_with_kit(repository, tmp_path, clock)

    # Act
    await purge_expired(sessions, now=clock.advance(days=89))
    fetched = await repository.get_order(order.id)

    # Assert
    assert is_ok(fetched)


async def test_recipient_identity_is_cleared_at_ninety_days(
    repository: SqlKitRepository,
    sessions: async_sessionmaker[AsyncSession],
    tmp_path: Path,
    clock: MovableClock,
) -> None:
    # Arrange
    order = await _delivered_order_with_kit(repository, tmp_path, clock)

    # Act
    result = await purge_expired(sessions, now=clock.advance(days=91))

    # Assert
    assert is_ok(result)
    assert result.value.brief_identities_purged == 1
    async with sessions() as session:
        row = (
            await session.execute(sa.select(BriefRow).where(BriefRow.order_id == order.id))
        ).scalar_one()
    assert row.recipient_name_display is None
    assert row.recipient_name_raw is None
    assert row.recipient_candidates is None
    assert row.identity_purged_at is not None


async def test_reading_an_order_after_the_identity_purge_fails_terminally(
    repository: SqlKitRepository,
    sessions: async_sessionmaker[AsyncSession],
    tmp_path: Path,
    clock: MovableClock,
) -> None:
    # Arrange
    order = await _delivered_order_with_kit(repository, tmp_path, clock)
    await purge_expired(sessions, now=clock.advance(days=91))

    # Act
    fetched = await repository.get_order(order.id)

    # Assert — the data is gone; inventing a placeholder would misreport a deletion.
    assert is_err(fetched)
    assert fetched.error.is_retryable is False


async def test_the_order_row_survives_the_identity_purge(
    repository: SqlKitRepository,
    sessions: async_sessionmaker[AsyncSession],
    tmp_path: Path,
    clock: MovableClock,
) -> None:
    # Arrange
    order = await _delivered_order_with_kit(repository, tmp_path, clock)

    # Act — SoW DAT-3: the transaction record outlives the personal-data record.
    await purge_expired(sessions, now=clock.advance(days=91))

    # Assert
    async with sessions() as session:
        stored = await session.get(OrderRow, order.id)
    assert stored is not None
    assert stored.state is OrderState.AUTHORIZED


# ---------------------------------------------------------------------------
# generation_attempts — identity nulled, tuning signal kept
# ---------------------------------------------------------------------------
async def test_attempt_identity_is_nulled_but_the_tuning_signal_survives(
    repository: SqlKitRepository,
    attempts: GenerationAttemptRepository,
    sessions: async_sessionmaker[AsyncSession],
    tmp_path: Path,
    clock: MovableClock,
) -> None:
    # Arrange
    order = await _delivered_order_with_kit(repository, tmp_path, clock)

    # Act
    result = await purge_expired(sessions, now=clock.advance(days=91))

    # Assert — the person is deleted; the measurement remains.
    assert is_ok(result)
    assert result.value.attempt_identities_purged >= 1
    async with sessions() as session:
        row = (
            (
                await session.execute(
                    sa.select(GenerationAttemptRow).where(GenerationAttemptRow.order_id == order.id)
                )
            )
            .scalars()
            .first()
        )
    assert row is not None
    assert row.name_candidate_text is None
    assert row.stt_transcript is None
    assert row.name_candidate_strategy is not None
    assert row.is_name_verified is not None


async def test_the_song_transcript_goes_at_thirty_days_while_the_name_text_stays(
    repository: SqlKitRepository,
    sessions: async_sessionmaker[AsyncSession],
    tmp_path: Path,
    clock: MovableClock,
) -> None:
    """The transcript is the SONG, so it rides the free-text clock, not the identity one.

    Inpainting is enterprise-gated, so verification transcribes the whole track — which
    means ``stt_transcript`` holds the lyric, and since the wizard's preview step the lyric
    may be words the customer wrote. Those words expire from ``briefs.approved_lyrics`` at
    thirty days; a copy of them surviving here until day ninety would be a retention
    schedule nobody promised. The candidate ladder is still tuned from the name text, so
    that half keeps the ninety-day clock.
    """
    # Arrange
    order = await _delivered_order_with_kit(repository, tmp_path, clock)

    # Act
    result = await purge_expired(sessions, now=clock.advance(days=31))

    # Assert
    assert is_ok(result)
    assert result.value.attempt_transcripts_purged >= 1
    assert result.value.attempt_identities_purged == 0
    async with sessions() as session:
        row = (
            (
                await session.execute(
                    sa.select(GenerationAttemptRow).where(GenerationAttemptRow.order_id == order.id)
                )
            )
            .scalars()
            .first()
        )
    assert row is not None
    assert row.stt_transcript is None
    assert row.name_candidate_text is not None


async def test_a_purged_transcript_is_not_re_purged_on_the_next_run(
    repository: SqlKitRepository,
    sessions: async_sessionmaker[AsyncSession],
    tmp_path: Path,
    clock: MovableClock,
) -> None:
    # Arrange
    await _delivered_order_with_kit(repository, tmp_path, clock)
    await purge_expired(sessions, now=clock.advance(days=31))

    # Act
    second = await purge_expired(sessions, now=clock.advance(days=1))

    # Assert — a nightly job must not churn the same rows forever.
    assert is_ok(second)
    assert second.value.attempt_transcripts_purged == 0


async def test_a_purged_attempt_is_not_re_purged_on_the_next_run(
    repository: SqlKitRepository,
    sessions: async_sessionmaker[AsyncSession],
    tmp_path: Path,
    clock: MovableClock,
) -> None:
    # Arrange
    await _delivered_order_with_kit(repository, tmp_path, clock)
    await purge_expired(sessions, now=clock.advance(days=91))

    # Act
    second = await purge_expired(sessions, now=clock.advance(days=1))

    # Assert — idempotent: a nightly job must not churn the same rows forever.
    assert is_ok(second)
    assert second.value.attempt_identities_purged == 0


# ---------------------------------------------------------------------------
# Dictionary entries and abandoned drafts
# ---------------------------------------------------------------------------
async def test_curated_dictionary_entries_never_expire(
    names: NameRecordRepository,
    sessions: async_sessionmaker[AsyncSession],
    clock: MovableClock,
) -> None:
    # Arrange — a curated entry is a licensed work product, not personal data.
    await names.upsert(
        NameRecordDraft(
            grapheme="Gʻulomjon",
            grapheme_normalized="gulomjon",
            language=Language.UZ_LATN,
            script=Script.LATIN,
            display_form="Gʻulomjon",
            source=NameSource.CURATED,
            expires_at=None,
        )
    )

    # Act
    result = await purge_expired(sessions, now=clock.advance(days=10 * _DAYS_IN_A_YEAR))

    # Assert
    assert is_ok(result)
    assert result.value.name_records_deleted == 0
    async with sessions() as session:
        remaining = await session.scalar(sa.select(sa.func.count()).select_from(NameRecordRow))
    assert remaining == 1


async def test_abandoned_drafts_are_deleted_after_fourteen_days(
    repository: SqlKitRepository,
    sessions: async_sessionmaker[AsyncSession],
    clock: MovableClock,
) -> None:
    # Arrange
    draft = new_order(state=OrderState.DRAFT, created_at=clock.now)
    await repository.create_order(draft)

    # Act
    result = await purge_expired(sessions, now=clock.advance(days=15))

    # Assert
    assert is_ok(result)
    assert result.value.abandoned_orders_deleted == 1
    async with sessions() as session:
        assert await session.get(OrderRow, draft.id) is None


async def test_a_completed_order_is_never_treated_as_an_abandoned_draft(
    repository: SqlKitRepository,
    sessions: async_sessionmaker[AsyncSession],
    clock: MovableClock,
) -> None:
    # Arrange
    order = new_order(state=OrderState.DELIVERED, created_at=clock.now)
    await repository.create_order(order)

    # Act
    result = await purge_expired(sessions, now=clock.advance(days=20))

    # Assert
    assert is_ok(result)
    assert result.value.abandoned_orders_deleted == 0


async def test_deleting_a_draft_detaches_its_attempts_rather_than_deleting_them(
    repository: SqlKitRepository,
    attempts: GenerationAttemptRepository,
    sessions: async_sessionmaker[AsyncSession],
    clock: MovableClock,
) -> None:
    # Arrange
    draft = new_order(state=OrderState.DRAFT, created_at=clock.now)
    await repository.create_order(draft)
    await attempts.record(
        GenerationAttempt(
            kind=GenerationKind.NAME_PREVIEW,
            order_id=draft.id,
            candidate=make_candidates()[0],
            is_name_verified=True,
            is_success=True,
        )
    )

    # Act
    await purge_expired(sessions, now=clock.advance(days=15))

    # Assert — the tuning signal must outlive the order it came from.
    async with sessions() as session:
        rows = (await session.execute(sa.select(GenerationAttemptRow))).scalars().all()
    assert len(rows) == 1
    assert rows[0].order_id is None


# ---------------------------------------------------------------------------
# Policy plumbing and reporting
# ---------------------------------------------------------------------------
async def test_a_shorter_policy_purges_sooner(
    sessions: async_sessionmaker[AsyncSession], tmp_path: Path, clock: MovableClock
) -> None:
    # Arrange — the schedule is configuration, so a test can shorten it.
    aggressive = RetentionPolicy(paid_audio_days=2, brief_text_days=1, recipient_identity_days=1)
    repository = SqlKitRepository(sessions, policy=aggressive, clock=clock)
    order = new_order(state=OrderState.AUTHORIZED)
    await repository.create_order(order)
    await repository.save_kit(build_kit(tmp_path, order.id))

    # Act
    result = await purge_expired(sessions, now=clock.advance(days=3), policy=aggressive)

    # Assert
    assert is_ok(result)
    assert result.value.assets_deleted == 5
    assert result.value.brief_identities_purged == 1


async def test_a_purge_with_nothing_due_reports_zero_and_succeeds(
    sessions: async_sessionmaker[AsyncSession], clock: MovableClock
) -> None:
    # Act
    result = await purge_expired(sessions, now=clock.now)

    # Assert
    assert is_ok(result)
    assert result.value.total_rows_affected == 0
    assert result.value.has_work_remaining is False


async def test_purge_respects_its_batch_size(
    repository: SqlKitRepository,
    sessions: async_sessionmaker[AsyncSession],
    tmp_path: Path,
    clock: MovableClock,
) -> None:
    # Arrange — a first run against a year of backlog must not lock the whole table.
    await _delivered_order_with_kit(repository, tmp_path, clock)

    # Act
    result = await purge_expired(
        sessions, now=clock.advance(days=_DAYS_IN_A_YEAR + 1), batch_size=2
    )

    # Assert
    assert is_ok(result)
    assert result.value.assets_deleted == 2


def test_default_policy_matches_the_published_retention_schedule() -> None:
    # Arrange / Act
    policy = DEFAULT_RETENTION_POLICY

    # Assert — these numbers are published to users and to a regulator.
    assert policy.paid_audio_days == _DAYS_IN_A_YEAR
    assert policy.free_output_days == 30
    assert policy.brief_text_days == 30
    assert policy.recipient_identity_days == 90


async def test_a_user_confirmed_dictionary_entry_is_deleted_when_its_clock_runs_out(
    names: NameRecordRepository,
    sessions: async_sessionmaker[AsyncSession],
    clock: MovableClock,
) -> None:
    # Arrange — a user-confirmed entry is a real person's name, so it expires.
    await names.upsert(
        NameRecordDraft(
            grapheme="Alyona",
            grapheme_normalized="alyona",
            language=Language.RU,
            script=Script.CYRILLIC,
            display_form="Алёна",
            source=NameSource.USER_CONFIRMED,
            expires_at=DEFAULT_RETENTION_POLICY.identity_expires_at(clock.now),
        )
    )

    # Act
    result = await purge_expired(sessions, now=clock.advance(days=91))

    # Assert
    assert is_ok(result)
    assert result.value.name_records_deleted == 1
    async with sessions() as session:
        remaining = await session.scalar(sa.select(sa.func.count()).select_from(NameRecordRow))
    assert remaining == 0


async def test_a_dictionary_entry_survives_until_its_clock_runs_out(
    names: NameRecordRepository,
    sessions: async_sessionmaker[AsyncSession],
    clock: MovableClock,
) -> None:
    # Arrange
    await names.upsert(
        NameRecordDraft(
            grapheme="Alyona",
            grapheme_normalized="alyona",
            language=Language.RU,
            script=Script.CYRILLIC,
            display_form="Алёна",
            source=NameSource.USER_CONFIRMED,
            expires_at=DEFAULT_RETENTION_POLICY.identity_expires_at(clock.now),
        )
    )

    # Act
    result = await purge_expired(sessions, now=clock.advance(days=89))

    # Assert — the ё must still be there; Алёна is not Алена.
    assert is_ok(result)
    assert result.value.name_records_deleted == 0
    lookup = await names.lookup("alyona", Language.RU)
    assert is_ok(lookup)
    assert lookup.value[0].display_form == "Алёна"


# ---------------------------------------------------------------------------
# Broadcast delivery rows — a 400-day CUTOFF, not a clock
# ---------------------------------------------------------------------------
_BROADCAST_READER: Final[int] = 8_912_345_678_903


def _campaign(clock: MovableClock) -> BroadcastRow:
    """A completed campaign. Its counters are the rollup the sweep must not disturb."""
    return BroadcastRow(
        # The id is minted here rather than left to the column default: the helper's callers
        # read ``campaign.id`` to build the child rows in the same ``session.add`` batch, and
        # the ORM default is not applied until the flush that INSERTs them.
        id=uuid4(),
        title="September announcement",
        kind=BroadcastKind.SERVICE,
        state=BroadcastState.COMPLETED,
        segment={"v": 1, "match": "all", "rules": []},
        segment_hash="0" * 64,
        audience_size=1,
        audience_evaluated_at=clock.now,
        recipient_count=1,
        sent_count=1,
        created_at=clock.now,
        updated_at=clock.now,
    )


def _delivery(
    broadcast_id: UUID, *, at: datetime, telegram_user_id: int | None = _BROADCAST_READER
) -> BroadcastRecipientRow:
    return BroadcastRecipientRow(
        broadcast_id=broadcast_id,
        telegram_user_id=telegram_user_id,
        language=Language.RU,
        state=BroadcastRecipientState.SENT,
        settled_at=at,
        created_at=at,
        updated_at=at,
    )


async def test_a_delivery_row_survives_three_hundred_and_ninety_nine_days(
    sessions: async_sessionmaker[AsyncSession], clock: MovableClock
) -> None:
    """A year-over-year comparison needs last spring's send to still be there."""
    # Arrange
    campaign = _campaign(clock)
    async with sessions.begin() as session:
        session.add(campaign)
        session.add(_delivery(campaign.id, at=clock.now))

    # Act
    result = await purge_expired(sessions, now=clock.advance(days=399))

    # Assert
    assert is_ok(result)
    assert result.value.broadcast_recipients_deleted == 0
    async with sessions() as session:
        remaining = await session.scalar(
            sa.select(sa.func.count()).select_from(BroadcastRecipientRow)
        )
    assert remaining == 1


async def test_a_delivery_row_is_deleted_after_four_hundred_days(
    sessions: async_sessionmaker[AsyncSession], clock: MovableClock
) -> None:
    """The cutoff is on ``created_at`` — when the audience was frozen — and takes the row whole.

    Nothing is nulled in place here, unlike the identity sweeps: ``/forget`` has already
    nulled the only column that could be, months or years earlier, and what is left is a
    state, a count and two clocks.
    """
    # Arrange
    campaign = _campaign(clock)
    async with sessions.begin() as session:
        session.add(campaign)
        session.add(_delivery(campaign.id, at=clock.now))

    # Act
    result = await purge_expired(sessions, now=clock.advance(days=401))

    # Assert
    assert is_ok(result)
    assert result.value.broadcast_recipients_deleted == 1
    async with sessions() as session:
        remaining = await session.scalar(
            sa.select(sa.func.count()).select_from(BroadcastRecipientRow)
        )
    assert remaining == 0


async def test_the_campaign_and_its_counters_survive_the_delivery_sweep(
    sessions: async_sessionmaker[AsyncSession], clock: MovableClock
) -> None:
    """A completed campaign's arithmetic must not change because its ledger aged out.

    ``broadcasts`` holds the rollup an operator has already read and acted on; the sweep
    bounds the ledger behind it and touches neither the parent row nor its bodies.
    """
    # Arrange
    campaign = _campaign(clock)
    async with sessions.begin() as session:
        session.add(campaign)
        session.add(_delivery(campaign.id, at=clock.now))

    # Act
    result = await purge_expired(sessions, now=clock.advance(days=401))

    # Assert
    assert is_ok(result)
    async with sessions() as session:
        after = await session.get(BroadcastRow, campaign.id)
    assert after is not None
    assert (after.audience_size, after.recipient_count, after.sent_count) == (1, 1, 1)


async def test_an_anonymised_delivery_row_is_still_swept_by_the_cutoff(
    sessions: async_sessionmaker[AsyncSession], clock: MovableClock
) -> None:
    """The two routes are independent: ``/forget`` takes the id, the cutoff takes the row.

    A row whose ``telegram_user_id`` is already ``NULL`` has nothing left to erase, but it
    still occupies the fastest-growing table in the schema — so the predicate is on
    ``created_at`` alone and never on the presence of an id.
    """
    # Arrange
    campaign = _campaign(clock)
    async with sessions.begin() as session:
        session.add(campaign)
        session.add(_delivery(campaign.id, at=clock.now, telegram_user_id=None))

    # Act
    result = await purge_expired(sessions, now=clock.advance(days=401))

    # Assert
    assert is_ok(result)
    assert result.value.broadcast_recipients_deleted == 1


async def test_the_delivery_sweep_respects_its_batch_size(
    sessions: async_sessionmaker[AsyncSession], clock: MovableClock
) -> None:
    """One campaign can write forty thousand rows in an afternoon."""
    # Arrange
    campaign = _campaign(clock)
    async with sessions.begin() as session:
        session.add(campaign)
        for offset in range(5):
            session.add(
                _delivery(
                    campaign.id,
                    at=clock.now,
                    telegram_user_id=_BROADCAST_READER + offset,
                )
            )

    # Act
    result = await purge_expired(sessions, now=clock.advance(days=401), batch_size=2)

    # Assert
    assert is_ok(result)
    assert result.value.broadcast_recipients_deleted == 2
    assert result.value.has_work_remaining is True
