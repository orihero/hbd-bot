"""``name_records``: the pronunciation dictionary, its variants and its provenance."""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from hbd.contracts import Language, Script, is_ok
from hbd.db.enums import NameSource
from hbd.db.models import NameRecordRow
from hbd.db.names import NameRecordDraft, NameRecordRepository
from tests.conftest import UZBEK_NAME_CANONICAL
from tests.test_db.conftest import MovableClock

_LOOKUP_KEY = "gulomjon"


def _draft(**overrides: object) -> NameRecordDraft:
    defaults: dict[str, object] = {
        "grapheme": UZBEK_NAME_CANONICAL,
        "grapheme_normalized": _LOOKUP_KEY,
        "language": Language.UZ_LATN,
        "script": Script.LATIN,
        "display_form": UZBEK_NAME_CANONICAL,
        "source": NameSource.CURATED,
        "ipa": "ʁulomd͡ʒon",
        "licence": "CC-BY-4.0",
        "contributor": "seed-corpus",
        "confidence": 0.95,
    }
    return NameRecordDraft(**{**defaults, **overrides})  # type: ignore[arg-type]


async def test_upsert_then_lookup_returns_the_entry(names: NameRecordRepository) -> None:
    # Arrange
    await names.upsert(_draft())

    # Act
    result = await names.lookup(_LOOKUP_KEY, Language.UZ_LATN)

    # Assert
    assert is_ok(result)
    assert len(result.value) == 1
    assert result.value[0].display_form == UZBEK_NAME_CANONICAL


async def test_lookup_returns_empty_for_an_unknown_name(names: NameRecordRepository) -> None:
    # Act
    result = await names.lookup("nobody", Language.RU)

    # Assert
    assert is_ok(result)
    assert result.value == ()


async def test_lookup_is_scoped_to_one_language(names: NameRecordRepository) -> None:
    # Arrange — the same graphemes in two languages are two different words.
    await names.upsert(_draft(language=Language.UZ_LATN))
    await names.upsert(_draft(language=Language.RU, script=Script.CYRILLIC))

    # Act
    uzbek = await names.lookup(_LOOKUP_KEY, Language.UZ_LATN)

    # Assert
    assert is_ok(uzbek)
    assert len(uzbek.value) == 1
    assert uzbek.value[0].language is Language.UZ_LATN


async def test_two_stress_variants_are_two_rows_ordered_by_ordinal(
    names: NameRecordRepository,
) -> None:
    # Arrange — one name legitimately has more than one correct stress pattern.
    await names.upsert(_draft(variant_ordinal=1, stressed_form="Gulomjón"))
    await names.upsert(_draft(variant_ordinal=0, stressed_form="Gúlomjon"))

    # Act
    result = await names.lookup(_LOOKUP_KEY, Language.UZ_LATN)

    # Assert — the caller receives both and asks the user, rather than guessing.
    assert is_ok(result)
    assert [row.variant_ordinal for row in result.value] == [0, 1]


async def test_upsert_updates_the_existing_variant_rather_than_inserting_a_duplicate(
    names: NameRecordRepository, sessions: async_sessionmaker[AsyncSession]
) -> None:
    # Arrange
    await names.upsert(_draft(confidence=0.5))

    # Act
    await names.upsert(_draft(confidence=0.99))

    # Assert
    async with sessions() as session:
        rows = (await session.execute(sa.select(NameRecordRow))).scalars().all()
    assert len(rows) == 1
    assert rows[0].confidence == 0.99


async def test_upsert_returns_the_same_id_on_a_second_write(
    names: NameRecordRepository,
) -> None:
    # Arrange
    first = await names.upsert(_draft())

    # Act
    second = await names.upsert(_draft(confidence=0.7))

    # Assert
    assert is_ok(first)
    assert is_ok(second)
    assert first.value == second.value


async def test_a_user_confirmed_entry_carries_an_expiry_and_a_curated_one_does_not(
    names: NameRecordRepository,
    sessions: async_sessionmaker[AsyncSession],
    clock: MovableClock,
) -> None:
    # Arrange — provenance decides retention (SoW FIL-7, LR-65).
    await names.upsert(_draft(source=NameSource.CURATED, expires_at=None))
    await names.upsert(
        _draft(
            grapheme_normalized="alena",
            source=NameSource.USER_CONFIRMED,
            expires_at=clock.now,
        )
    )

    # Act
    async with sessions() as session:
        rows = (await session.execute(sa.select(NameRecordRow))).scalars().all()
    by_key = {row.grapheme_normalized: row for row in rows}

    # Assert
    assert by_key[_LOOKUP_KEY].expires_at is None
    assert by_key["alena"].expires_at is not None


async def test_record_outcome_increments_usage_and_success(
    names: NameRecordRepository, sessions: async_sessionmaker[AsyncSession]
) -> None:
    # Arrange
    created = await names.upsert(_draft())
    assert is_ok(created)

    # Act
    await names.record_outcome(created.value, is_verified=True)
    await names.record_outcome(created.value, is_verified=False)

    # Assert
    async with sessions() as session:
        row = await session.get(NameRecordRow, created.value)
    assert row is not None
    assert row.usage_count == 2
    assert row.success_count == 1
    assert row.success_rate == 0.5


async def test_record_outcome_counts_a_human_correction_separately(
    names: NameRecordRepository, sessions: async_sessionmaker[AsyncSession]
) -> None:
    # Arrange
    created = await names.upsert(_draft())
    assert is_ok(created)

    # Act
    await names.record_outcome(created.value, is_verified=False, is_correction=True)

    # Assert — a correction is the strongest signal the dictionary gets.
    async with sessions() as session:
        row = await session.get(NameRecordRow, created.value)
    assert row is not None
    assert row.correction_count == 1


def test_success_rate_is_zero_before_any_render() -> None:
    # Arrange
    row = NameRecordRow(usage_count=0, success_count=0)

    # Act / Assert
    assert row.success_rate == 0.0


def test_a_name_record_draft_cannot_be_mutated() -> None:
    # Arrange
    draft = _draft()

    # Act / Assert — the repository must not be able to alter its caller's value.
    try:
        draft.confidence = 0.1  # type: ignore[misc]
    except (AttributeError, TypeError):
        return
    raise AssertionError("NameRecordDraft must be frozen")
