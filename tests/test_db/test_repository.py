"""``SqlKitRepository`` behaviour: round trips, idempotency, and the never-throw contract."""

from __future__ import annotations

from pathlib import Path
from uuid import uuid4

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from hbd.contracts import (
    AssetKind,
    KitRepository,
    Language,
    NameStrategy,
    Occasion,
    OrderState,
    is_err,
    is_ok,
)
from hbd.db.models import AssetRow, BriefRow, OrderRow, UserRow
from hbd.db.repository import MAX_ORDER_HISTORY, SqlKitRepository
from hbd.errors import ErrorCode
from tests.conftest import (
    UZBEK_NAME_CANONICAL,
    UZBEK_NAME_TYPED,
    make_brief,
    make_lyrics,
    make_name,
)
from tests.test_db.conftest import MovableClock, build_kit, make_verdict, new_order


# ---------------------------------------------------------------------------
# Protocol conformance
# ---------------------------------------------------------------------------
def test_repository_satisfies_the_kit_repository_protocol(
    repository: SqlKitRepository,
) -> None:
    # Arrange / Act
    is_conformant = isinstance(repository, KitRepository)

    # Assert
    assert is_conformant


# ---------------------------------------------------------------------------
# create_order / get_order
# ---------------------------------------------------------------------------
async def test_create_order_round_trips_through_get_order(
    repository: SqlKitRepository,
) -> None:
    # Arrange
    order = new_order()

    # Act
    created = await repository.create_order(order)
    fetched = await repository.get_order(order.id)

    # Assert
    assert is_ok(created)
    assert is_ok(fetched)
    assert fetched.value == order


async def test_create_order_preserves_the_typed_and_display_name_separately(
    repository: SqlKitRepository,
) -> None:
    # Arrange — a phone keyboard emits U+2018; the display form must be U+02BB.
    order = new_order(brief=make_brief(recipient=make_name()))

    # Act
    await repository.create_order(order)
    fetched = await repository.get_order(order.id)

    # Assert
    assert is_ok(fetched)
    recipient = fetched.value.brief.recipient
    assert recipient.raw == UZBEK_NAME_TYPED
    assert recipient.display == UZBEK_NAME_CANONICAL
    assert recipient.raw != recipient.display


async def test_create_order_stores_ranked_candidates_in_order(
    repository: SqlKitRepository,
) -> None:
    # Arrange
    order = new_order()

    # Act
    await repository.create_order(order)
    fetched = await repository.get_order(order.id)

    # Assert — rank order is the whole point of the candidate list.
    assert is_ok(fetched)
    candidates = fetched.value.brief.recipient.candidates
    assert tuple(candidate.rank for candidate in candidates) == (0, 1, 2)
    assert candidates[0].strategy is NameStrategy.STRIPPED


async def test_create_order_reuses_one_user_row_across_orders(
    repository: SqlKitRepository, sessions: async_sessionmaker[AsyncSession]
) -> None:
    # Arrange
    first = new_order(telegram_user_id=555)
    second = new_order(telegram_user_id=555)

    # Act
    await repository.create_order(first)
    await repository.create_order(second)

    # Assert
    async with sessions() as session:
        user_count = await session.scalar(
            sa.select(sa.func.count()).select_from(UserRow).where(UserRow.telegram_user_id == 555)
        )
    assert user_count == 1


async def test_create_order_returns_a_terminal_error_on_a_duplicate_id(
    repository: SqlKitRepository,
) -> None:
    # Arrange
    order = new_order()
    await repository.create_order(order)

    # Act
    duplicate = await repository.create_order(order)

    # Assert — a constraint violation will never succeed on retry.
    assert is_err(duplicate)
    assert duplicate.error.is_retryable is False
    assert duplicate.error.error_code is ErrorCode.STORAGE_FAILED


async def test_the_approved_lyric_survives_the_round_trip_word_for_word(
    repository: SqlKitRepository,
) -> None:
    # Arrange — this is what the customer read on the preview screen and paid for.
    lyrics = make_lyrics()
    order = new_order(brief=make_brief(approved_lyrics=lyrics))

    # Act
    await repository.create_order(order)
    fetched = await repository.get_order(order.id)

    # Assert — the worker sings this back; a single dropped line is a wrong product.
    assert is_ok(fetched)
    approved = fetched.value.brief.approved_lyrics
    assert approved is not None
    assert approved == lyrics
    assert approved.title == lyrics.title
    assert approved.name_display == UZBEK_NAME_CANONICAL
    assert approved.sections == lyrics.sections
    assert tuple(section.is_name_hook for section in approved.sections) == (False, True, False)


async def test_an_order_without_an_approved_lyric_reads_back_as_none(
    repository: SqlKitRepository,
) -> None:
    # Arrange — a brief from before the preview step, or one the wizard never filled in.
    order = new_order(brief=make_brief())

    # Act
    await repository.create_order(order)
    fetched = await repository.get_order(order.id)

    # Assert — None, not an empty draft: it means "the pipeline writes its own".
    assert is_ok(fetched)
    assert fetched.value.brief.approved_lyrics is None


async def test_create_order_is_the_write_path_for_the_approved_lyric(
    repository: SqlKitRepository, sessions: async_sessionmaker[AsyncSession]
) -> None:
    # Arrange — there is no UPDATE path for briefs, and the queue payload carries only an
    # order id, so whatever this insert misses the worker can never learn.
    order = new_order(brief=make_brief(approved_lyrics=make_lyrics()))

    # Act
    await repository.create_order(order)

    # Assert
    async with sessions() as session:
        stored = await session.scalar(
            sa.select(BriefRow.approved_lyrics).where(BriefRow.order_id == order.id)
        )
    assert isinstance(stored, dict)
    assert stored["title"] == "Tugʻilgan kun"


async def test_a_brief_without_a_lyric_stores_sql_null_not_the_json_text_null(
    repository: SqlKitRepository, sessions: async_sessionmaker[AsyncSession]
) -> None:
    # Arrange — ``sa.JSON`` persists Python ``None`` as the JSON text ``'null'`` unless told
    # otherwise. That reads back as ``None``, so nothing in Python notices; but the purge
    # job's predicate is SQL, and ``'null' IS NOT NULL`` is true.
    order = new_order(brief=make_brief())

    # Act
    await repository.create_order(order)
    async with sessions() as session:
        matched = await session.scalar(
            sa.select(sa.func.count())
            .select_from(BriefRow)
            .where(BriefRow.approved_lyrics.is_not(None))
        )

    # Assert — otherwise the 30-day note sweep re-selects every brief ever written, forever.
    assert matched == 0


async def test_get_order_returns_err_for_an_unknown_id(repository: SqlKitRepository) -> None:
    # Arrange
    missing = uuid4()

    # Act
    result = await repository.get_order(missing)

    # Assert — an Err, not an exception: the protocol forbids raising.
    assert is_err(result)
    assert result.error.is_retryable is False


# ---------------------------------------------------------------------------
# set_order_state
# ---------------------------------------------------------------------------
async def test_set_order_state_returns_a_new_order_in_the_new_state(
    repository: SqlKitRepository, clock: MovableClock
) -> None:
    # Arrange
    order = new_order(state=OrderState.BRIEF_READY)
    await repository.create_order(order)
    later = clock.advance(days=1)

    # Act
    result = await repository.set_order_state(order.id, OrderState.GENERATING, now=later)

    # Assert
    assert is_ok(result)
    assert result.value.state is OrderState.GENERATING
    assert result.value.updated_at == later
    assert order.state is OrderState.BRIEF_READY  # the input was not mutated


async def test_set_order_state_stamps_delivered_at_on_delivery(
    repository: SqlKitRepository,
    sessions: async_sessionmaker[AsyncSession],
    clock: MovableClock,
) -> None:
    # Arrange
    order = new_order()
    await repository.create_order(order)
    delivered_at = clock.advance(days=2)

    # Act
    await repository.set_order_state(order.id, OrderState.DELIVERED, now=delivered_at)

    # Assert
    async with sessions() as session:
        stored = await session.get(OrderRow, order.id)
        assert stored is not None
        assert stored.delivered_at == delivered_at


async def test_set_order_state_latches_is_paid_and_never_clears_it(
    repository: SqlKitRepository,
    sessions: async_sessionmaker[AsyncSession],
    clock: MovableClock,
) -> None:
    # Arrange
    order = new_order(state=OrderState.BRIEF_READY)
    await repository.create_order(order)

    # Act — authorise, then fail. A failed order still bought what it bought.
    await repository.set_order_state(order.id, OrderState.AUTHORIZED, now=clock.advance(days=1))
    await repository.set_order_state(order.id, OrderState.FAILED, now=clock.advance(days=1))

    # Assert
    async with sessions() as session:
        stored = await session.get(OrderRow, order.id)
        assert stored is not None
        assert stored.is_paid is True


async def test_set_order_state_returns_err_for_an_unknown_order(
    repository: SqlKitRepository, clock: MovableClock
) -> None:
    # Act
    result = await repository.set_order_state(uuid4(), OrderState.FAILED, now=clock.now)

    # Assert
    assert is_err(result)


# ---------------------------------------------------------------------------
# save_kit / get_kit
# ---------------------------------------------------------------------------
async def test_save_kit_round_trips_every_asset_and_the_lyrics(
    repository: SqlKitRepository, tmp_path: Path
) -> None:
    # Arrange
    order = new_order()
    await repository.create_order(order)
    kit = build_kit(tmp_path, order.id)

    # Act
    saved = await repository.save_kit(kit)
    fetched = await repository.get_kit(order.id)

    # Assert
    assert is_ok(saved)
    assert is_ok(fetched)
    restored = fetched.value
    assert restored.song.sha256 == kit.song.sha256
    assert len(restored.greetings) == 3
    assert restored.lyrics == kit.lyrics
    assert restored.lyric_sheet.kind is AssetKind.LYRIC_SHEET


async def test_save_kit_preserves_greeting_order(
    repository: SqlKitRepository, tmp_path: Path
) -> None:
    # Arrange
    order = new_order()
    await repository.create_order(order)
    kit = build_kit(tmp_path, order.id)

    # Act
    await repository.save_kit(kit)
    fetched = await repository.get_kit(order.id)

    # Assert — persona order is what the delivery message narrates.
    assert is_ok(fetched)
    personas = tuple(asset.persona_id for asset in fetched.value.greetings)
    assert personas == ("persona-0", "persona-1", "persona-2")


async def test_saving_the_same_kit_twice_does_not_duplicate_assets(
    repository: SqlKitRepository,
    sessions: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    # Arrange — ARQ retries jobs, so this happens in production.
    order = new_order()
    await repository.create_order(order)
    kit = build_kit(tmp_path, order.id)

    # Act
    await repository.save_kit(kit)
    await repository.save_kit(kit)

    # Assert
    async with sessions() as session:
        asset_count = await session.scalar(
            sa.select(sa.func.count()).select_from(AssetRow).where(AssetRow.order_id == order.id)
        )
    assert asset_count == 5  # one song, three greetings, one lyric sheet


async def test_save_kit_persists_name_verdicts_for_later_tuning(
    repository: SqlKitRepository, tmp_path: Path
) -> None:
    # Arrange
    order = new_order()
    await repository.create_order(order)
    kit = build_kit(tmp_path, order.id).model_copy(
        update={
            "name_verdicts": (
                make_verdict(strategy=NameStrategy.STRIPPED, is_match=False, attempt=0),
                make_verdict(strategy=NameStrategy.CANONICAL, rank=1, is_match=True, attempt=1),
            )
        }
    )

    # Act
    await repository.save_kit(kit)
    fetched = await repository.get_kit(order.id)

    # Assert
    assert is_ok(fetched)
    verdicts = fetched.value.name_verdicts
    assert len(verdicts) == 2
    assert verdicts[0].is_match is False
    assert verdicts[1].candidate.strategy is NameStrategy.CANONICAL


async def test_save_kit_returns_err_when_the_order_does_not_exist(
    repository: SqlKitRepository, tmp_path: Path
) -> None:
    # Arrange
    orphan_id = uuid4()
    kit = build_kit(tmp_path, orphan_id)

    # Act
    result = await repository.save_kit(kit)

    # Assert
    assert is_err(result)


async def test_get_kit_returns_err_before_a_kit_is_saved(
    repository: SqlKitRepository,
) -> None:
    # Arrange
    order = new_order()
    await repository.create_order(order)

    # Act
    result = await repository.get_kit(order.id)

    # Assert
    assert is_err(result)


# ---------------------------------------------------------------------------
# list_orders_for_user
# ---------------------------------------------------------------------------
async def test_list_orders_for_user_returns_newest_first(
    repository: SqlKitRepository, clock: MovableClock
) -> None:
    # Arrange
    older = new_order(telegram_user_id=42, created_at=clock.now)
    newer = new_order(telegram_user_id=42, created_at=clock.advance(days=5))
    await repository.create_order(older)
    await repository.create_order(newer)

    # Act
    result = await repository.list_orders_for_user(42, limit=10)

    # Assert
    assert is_ok(result)
    assert [order.id for order in result.value] == [newer.id, older.id]


async def test_list_orders_for_user_excludes_other_users(
    repository: SqlKitRepository,
) -> None:
    # Arrange
    mine = new_order(telegram_user_id=1)
    theirs = new_order(telegram_user_id=2)
    await repository.create_order(mine)
    await repository.create_order(theirs)

    # Act
    result = await repository.list_orders_for_user(1, limit=10)

    # Assert
    assert is_ok(result)
    assert [order.id for order in result.value] == [mine.id]


async def test_list_orders_for_user_caps_an_absurd_limit(
    repository: SqlKitRepository,
) -> None:
    # Arrange
    await repository.create_order(new_order(telegram_user_id=7))

    # Act — an unbounded history query is how a database falls over.
    result = await repository.list_orders_for_user(7, limit=10_000_000)

    # Assert
    assert is_ok(result)
    assert len(result.value) <= MAX_ORDER_HISTORY


async def test_list_orders_for_user_returns_empty_for_an_unknown_user(
    repository: SqlKitRepository,
) -> None:
    # Act
    result = await repository.list_orders_for_user(999_999, limit=5)

    # Assert
    assert is_ok(result)
    assert result.value == ()


# ---------------------------------------------------------------------------
# Schema separability (SoW DAT-3)
# ---------------------------------------------------------------------------
async def test_recipient_data_lives_on_the_brief_not_the_order(
    repository: SqlKitRepository, sessions: async_sessionmaker[AsyncSession]
) -> None:
    # Arrange
    order = new_order()
    await repository.create_order(order)

    # Act
    order_columns = {column.name for column in OrderRow.__table__.columns}
    async with sessions() as session:
        brief = (
            await session.execute(sa.select(BriefRow).where(BriefRow.order_id == order.id))
        ).scalar_one()

    # Assert — the tax record must be purgeable-independent of the personal record.
    assert not any("recipient" in name or "note" in name for name in order_columns)
    assert brief.recipient_name_display == UZBEK_NAME_CANONICAL


async def test_brief_language_pair_is_stored_independently(
    repository: SqlKitRepository,
) -> None:
    # Arrange — interface language and output language are chosen independently.
    order = new_order(brief=make_brief(ui_language=Language.RU, output_language=Language.UZ_LATN))
    await repository.create_order(order)

    # Act
    fetched = await repository.get_order(order.id)

    # Assert
    assert is_ok(fetched)
    assert fetched.value.brief.ui_language is Language.RU
    assert fetched.value.brief.output_language is Language.UZ_LATN


async def test_empty_note_round_trips_as_empty_string(
    repository: SqlKitRepository,
) -> None:
    # Arrange
    order = new_order(brief=make_brief(note="", occasion=Occasion.ANNIVERSARY))
    await repository.create_order(order)

    # Act
    fetched = await repository.get_order(order.id)

    # Assert
    assert is_ok(fetched)
    assert fetched.value.brief.note == ""
    assert fetched.value.brief.occasion is Occasion.ANNIVERSARY
