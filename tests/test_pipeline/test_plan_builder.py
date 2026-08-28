"""The plan isolates the name and swaps display orthography for submitted orthography."""

from __future__ import annotations

import logging
from uuid import UUID

import pytest

from hbd.config import Settings
from hbd.contracts import (
    MAX_CHUNKS_PER_PLAN,
    MIN_SONG_DURATION_MS,
    Brief,
    CompositionPlan,
    Err,
    LyricDraft,
    LyricSection,
    NameCandidate,
    NameStrategy,
    Result,
)
from hbd.pipeline.plan_builder import (
    build_composition_plan,
    derive_seed,
    substitute_name,
    with_name_candidate,
)
from tests.conftest import UZBEK_NAME_CANONICAL, make_brief, make_lyrics
from tests.test_pipeline.conftest import failure_of, value_of

STRIPPED = NameCandidate(text="Gulomjon", strategy=NameStrategy.STRIPPED, rank=0)
CANONICAL = NameCandidate(text=UZBEK_NAME_CANONICAL, strategy=NameStrategy.CANONICAL, rank=1)


def _plan(
    settings: Settings, *, lyrics: LyricDraft | None = None, brief: Brief | None = None
) -> Result[CompositionPlan]:
    return build_composition_plan(
        lyrics or make_lyrics(),
        brief=brief or make_brief(),
        candidate=STRIPPED,
        settings=settings,
        seed=42,
    )


def test_puts_the_name_in_a_chunk_of_its_own(settings: Settings) -> None:
    # Arrange / Act
    plan = value_of(_plan(settings))

    # Assert
    assert plan.name_chunk_index is not None
    name_chunk = plan.chunks[plan.name_chunk_index]
    assert name_chunk.duration_ms == settings.name_chunk_duration_ms
    assert sum(1 for chunk in plan.chunks if chunk.is_name_chunk) == 1


def test_the_name_chunk_carries_the_submitted_orthography_not_the_display_one(
    settings: Settings,
) -> None:
    # Arrange / Act
    plan = value_of(_plan(settings))
    name_chunk = plan.chunks[plan.name_chunk_index or 0]

    # Assert
    assert name_chunk.text == STRIPPED.text
    assert UZBEK_NAME_CANONICAL not in name_chunk.text


def test_total_duration_stays_inside_the_vendor_bounds(settings: Settings) -> None:
    # Arrange / Act
    plan = value_of(_plan(settings))

    # Assert
    assert MIN_SONG_DURATION_MS <= plan.total_duration_ms <= settings.song_length_ms
    assert len(plan.chunks) <= MAX_CHUNKS_PER_PLAN


def test_stores_the_song_for_inpainting_when_verification_is_enabled(
    settings: Settings,
) -> None:
    # Arrange
    disabled = settings.model_copy(update={"is_name_verification_enabled": False})

    # Act
    with_verification = value_of(_plan(settings))
    without = value_of(_plan(disabled))

    # Assert
    assert with_verification.should_store_for_inpainting is True
    assert without.should_store_for_inpainting is False


def test_returns_an_error_when_no_section_is_flagged_as_the_name_hook(
    settings: Settings,
) -> None:
    # Arrange
    hookless = make_lyrics(
        sections=(LyricSection(label="verse", lines=("bir ikki uch",)),),
    )

    # Act
    result = _plan(settings, lyrics=hookless)

    # Assert
    assert isinstance(result, Err)
    assert "name-hook" in failure_of(result).operator_message


def test_drops_trailing_sections_that_do_not_fit_the_song_length(
    settings: Settings,
) -> None:
    # Arrange: a very short song leaves room for only one body chunk
    short = settings.model_copy(update={"song_length_ms": 12_000, "name_chunk_duration_ms": 8_000})

    # Act
    plan = value_of(_plan(short))

    # Assert
    assert len(plan.chunks) == 2
    assert plan.total_duration_ms <= 12_000


def test_re_roll_swaps_only_the_name_chunk(settings: Settings) -> None:
    # Arrange
    plan = value_of(_plan(settings))
    original_bodies = tuple(chunk.text for chunk in plan.chunks if not chunk.is_name_chunk)

    # Act
    rerolled = value_of(with_name_candidate(plan, previous=STRIPPED, candidate=CANONICAL))

    # Assert
    assert rerolled.chunks[rerolled.name_chunk_index or 0].text == CANONICAL.text
    assert tuple(c.text for c in rerolled.chunks if not c.is_name_chunk) == original_bodies
    assert plan.chunks[plan.name_chunk_index or 0].text == STRIPPED.text


def test_re_roll_falls_back_to_the_bare_candidate_when_the_old_spelling_is_absent(
    settings: Settings, caplog: pytest.LogCaptureFixture
) -> None:
    # Arrange — this fallback throws the hook's lyric away, so it must never be silent
    plan = value_of(_plan(settings))
    stranger = NameCandidate(text="Zamira", strategy=NameStrategy.PHONETIC, rank=1)
    ghost = NameCandidate(text="NotInTheChunk", strategy=NameStrategy.ASCII, rank=0)

    # Act
    with caplog.at_level(logging.WARNING, logger="hbd.pipeline.plan_builder"):
        rerolled = value_of(with_name_candidate(plan, previous=ghost, candidate=stranger))

    # Assert
    assert rerolled.chunks[rerolled.name_chunk_index or 0].text == "Zamira"
    assert [record.levelno for record in caplog.records] == [logging.WARNING]


def test_substitute_name_is_case_insensitive_and_leaves_other_text_alone() -> None:
    # Arrange
    line = "bugun GULOMJON bilan bayram"

    # Act
    swapped = substitute_name(line, display="Gulomjon", submitted="Gu-lom-jon")

    # Assert
    assert swapped == "bugun Gu-lom-jon bilan bayram"


def test_substitute_name_is_a_no_op_when_the_forms_are_identical() -> None:
    # Arrange / Act
    unchanged = substitute_name("salom Ali", display="Ali", submitted="Ali")

    # Assert
    assert unchanged == "salom Ali"


def test_seed_is_derived_from_the_order_so_a_retry_renders_the_same_song() -> None:
    # Arrange
    order_id = UUID("11111111-2222-3333-4444-555555555555")

    # Act
    first = derive_seed(order_id)
    second = derive_seed(order_id)

    # Assert
    assert first == second
    assert first != derive_seed(UUID("99999999-2222-3333-4444-555555555555"))


def test_a_single_section_lyric_still_fills_the_whole_song(settings: Settings) -> None:
    """A hook-only lyric must not become an eight-second song the customer paid two minutes for.

    The name normally gets a short chunk so a bad take costs one inpaint instead of a whole
    track, and the body carries the rest of ``song_length_ms``. A lyric with exactly one
    section has no body — which is what a customer gets when they paste four lines with no
    blank line between them, and what a sparse model payload produces too. Left alone the
    plan totals ``name_chunk_duration_ms``, validates cleanly because that is still above
    ``MIN_SONG_DURATION_MS``, logs nothing, and silently ships a fraction of the product.
    """
    # Arrange
    hook_only = make_lyrics(
        sections=(
            LyricSection(
                label="hook",
                lines=(f"Bugun {UZBEK_NAME_CANONICAL} tugʻilgan kun", "Yillar oʻtsa ham"),
                is_name_hook=True,
            ),
        )
    )

    # Act
    plan = value_of(_plan(settings, lyrics=hook_only))

    # Assert
    assert len(plan.chunks) == 1
    assert plan.total_duration_ms == settings.song_length_ms
    assert plan.total_duration_ms > settings.name_chunk_duration_ms


def test_a_multi_section_lyric_still_gets_the_short_name_chunk(settings: Settings) -> None:
    """The single-section rescue must not leak into the ordinary case."""
    # Arrange / Act
    plan = value_of(_plan(settings))

    # Assert
    assert plan.name_chunk_index is not None
    assert plan.chunks[plan.name_chunk_index].duration_ms == settings.name_chunk_duration_ms
