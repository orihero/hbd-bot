"""The planner: a LyricDraft becomes a plan with the name isolated in one chunk."""

from __future__ import annotations

from hbd.config import Settings
from hbd.contracts import (
    MAX_CHUNKS_PER_PLAN,
    CompositionPlan,
    Genre,
    Language,
    LyricDraft,
    LyricSection,
    Result,
    is_err,
    is_ok,
)
from hbd.providers.music.planner import (
    INTRO_CHUNK_TEXT,
    PlanShape,
    build_composition_plan,
    plan_shape_from_settings,
    plan_with_chunk_text,
    plan_with_name_text,
)
from hbd.providers.music.styles import NAME_CHUNK_CONTEXT_ADHERENCE, NAME_CHUNK_POSITIVE_STYLES
from tests.test_providers_music.conftest import DEFAULT_SHAPE, make_lyrics, simple_plan

DISPLAY = "Gʻulomjon"
SUBMITTED = "Gulomjon"


def _build(
    *,
    lyrics: LyricDraft | None = None,
    shape: PlanShape = DEFAULT_SHAPE,
    genre: Genre = Genre.UZBEK_POP,
    name_submitted: str = SUBMITTED,
    seed: int | None = None,
) -> Result[CompositionPlan]:
    return build_composition_plan(
        lyrics if lyrics is not None else make_lyrics(name_display=DISPLAY),
        shape=shape,
        genre=genre,
        name_submitted=name_submitted,
        seed=seed,
    )


# ---------------------------------------------------------------------------
# The load-bearing invariants
# ---------------------------------------------------------------------------
def test_plan_contains_exactly_one_name_chunk() -> None:
    # Arrange / Act
    result = _build()

    # Assert
    assert is_ok(result)
    name_chunks = [chunk for chunk in result.value.chunks if chunk.is_name_chunk]
    assert len(name_chunks) == 1


def test_name_chunk_carries_the_submitted_orthography_not_the_display_form() -> None:
    # Arrange / Act
    result = _build()

    # Assert
    assert is_ok(result)
    index = result.value.name_chunk_index
    assert index is not None
    assert SUBMITTED in result.value.chunks[index].text


def test_display_orthography_never_reaches_any_chunk_text() -> None:
    # Arrange: the display form uses U+02BB, which no music model can pronounce.
    result = _build()

    # Assert
    assert is_ok(result)
    for chunk in result.value.chunks:
        assert DISPLAY not in chunk.text


def test_name_chunk_duration_comes_from_the_configured_shape() -> None:
    # Arrange
    shape = PlanShape(song_length_ms=90_000, name_chunk_duration_ms=6_000, body_chunk_target_ms=15_000)

    # Act
    result = _build(shape=shape)

    # Assert
    assert is_ok(result)
    index = result.value.name_chunk_index
    assert index is not None
    assert result.value.chunks[index].duration_ms == 6_000


def test_total_duration_matches_the_configured_song_length() -> None:
    # Arrange / Act
    result = _build()

    # Assert
    assert is_ok(result)
    assert result.value.total_duration_ms == DEFAULT_SHAPE.song_length_ms


def test_first_chunk_is_an_instrumental_intro() -> None:
    # Arrange / Act
    result = _build()

    # Assert
    assert is_ok(result)
    assert result.value.chunks[0].text == INTRO_CHUNK_TEXT
    assert not result.value.chunks[0].is_name_chunk


def test_name_chunk_asks_for_clear_diction() -> None:
    # Arrange / Act
    result = _build()

    # Assert
    assert is_ok(result)
    index = result.value.name_chunk_index
    assert index is not None
    chunk = result.value.chunks[index]
    assert set(NAME_CHUNK_POSITIVE_STYLES).issubset(chunk.positive_styles)
    assert chunk.context_adherence == NAME_CHUNK_CONTEXT_ADHERENCE
    assert "mumbled vocals" in chunk.negative_styles


def test_store_for_inpainting_is_on_so_the_name_can_be_re_rolled() -> None:
    # Arrange / Act
    result = _build()

    # Assert
    assert is_ok(result)
    assert result.value.should_store_for_inpainting is True


def test_seed_is_carried_through_for_reproducible_retries() -> None:
    # Arrange / Act
    result = _build(seed=9_001)

    # Assert
    assert is_ok(result)
    assert result.value.seed == 9_001


# ---------------------------------------------------------------------------
# Shape arithmetic
# ---------------------------------------------------------------------------
def test_section_texts_cycle_when_the_budget_wants_more_chunks_than_sections() -> None:
    # Arrange: 3 sections, one of which is the hook, leaves two lyric texts.
    result = _build(lyrics=make_lyrics(section_count=3, name_display=DISPLAY))

    # Assert: the body still fills the configured length, so texts repeat.
    assert is_ok(result)
    body = [chunk for chunk in result.value.chunks if not chunk.is_name_chunk]
    assert len(body) > 3
    assert len({chunk.text for chunk in body}) < len(body)


def test_sections_are_merged_when_they_exceed_the_available_chunks() -> None:
    # Arrange: far more sections than the body budget can hold as separate chunks.
    result = _build(lyrics=make_lyrics(section_count=40, name_display=DISPLAY))

    # Assert
    assert is_ok(result)
    assert len(result.value.chunks) <= MAX_CHUNKS_PER_PLAN
    body_text = "\n".join(chunk.text for chunk in result.value.chunks)
    assert "line body number 0" in body_text
    assert "line body number 37" in body_text


def test_a_very_short_song_still_produces_a_legal_plan() -> None:
    # Arrange: the smallest song the vendor accepts.
    shape = PlanShape(song_length_ms=6_000, name_chunk_duration_ms=3_000, body_chunk_target_ms=3_000)

    # Act
    result = _build(shape=shape)

    # Assert
    assert is_ok(result)
    assert result.value.total_duration_ms == 6_000
    assert all(chunk.duration_ms >= 3_000 for chunk in result.value.chunks)


def test_lyrics_without_a_hook_section_still_get_a_name_chunk() -> None:
    # Arrange
    lyrics = LyricDraft(
        title="No hook",
        language=Language.UZ_LATN,
        sections=(LyricSection(label="verse", lines=("just a verse",)),),
        name_display=DISPLAY,
    )

    # Act
    result = _build(lyrics=lyrics)

    # Assert
    assert is_ok(result)
    index = result.value.name_chunk_index
    assert index is not None
    assert result.value.chunks[index].text == SUBMITTED


def test_hook_that_does_not_contain_the_name_falls_back_to_the_bare_name() -> None:
    # Arrange: a hook flagged as the name hook but with no name in it.
    lyrics = LyricDraft(
        title="Odd hook",
        language=Language.UZ_LATN,
        sections=(
            LyricSection(label="verse", lines=("a verse",)),
            LyricSection(label="hook", lines=("la la la",), is_name_hook=True),
        ),
        name_display=DISPLAY,
    )

    # Act
    result = _build(lyrics=lyrics)

    # Assert
    assert is_ok(result)
    index = result.value.name_chunk_index
    assert index is not None
    assert result.value.chunks[index].text == SUBMITTED


def test_plan_shape_reads_every_duration_from_settings(settings: Settings) -> None:
    # Arrange / Act
    shape = plan_shape_from_settings(settings)

    # Assert
    assert shape.song_length_ms == settings.song_length_ms
    assert shape.name_chunk_duration_ms == settings.name_chunk_duration_ms
    assert shape.body_chunk_target_ms == settings.song_body_chunk_duration_ms


# ---------------------------------------------------------------------------
# Failure paths
# ---------------------------------------------------------------------------
def test_returns_err_when_the_submitted_name_is_blank() -> None:
    # Arrange / Act
    result = _build(name_submitted="   ")

    # Assert
    assert is_err(result)
    assert result.error.error_code.value == "INVALID_INPUT"
    assert not result.error.is_retryable


def test_build_does_not_mutate_the_lyrics_it_was_given() -> None:
    # Arrange
    lyrics = make_lyrics(name_display=DISPLAY)
    before = lyrics.model_dump()

    # Act
    _build(lyrics=lyrics)

    # Assert
    assert lyrics.model_dump() == before


# ---------------------------------------------------------------------------
# Re-roll helpers
# ---------------------------------------------------------------------------
def test_plan_with_name_text_replaces_only_the_name_chunk() -> None:
    # Arrange
    plan = simple_plan(name_text="Gulomjon")

    # Act
    result = plan_with_name_text(plan, "Gu-lom-jon")

    # Assert
    assert is_ok(result)
    assert result.value.chunks[1].text == "Gu-lom-jon"
    assert result.value.chunks[0].text == plan.chunks[0].text
    assert result.value.chunks[2].text == plan.chunks[2].text


def test_plan_with_name_text_leaves_the_original_plan_untouched() -> None:
    # Arrange
    plan = simple_plan(name_text="Gulomjon")

    # Act
    plan_with_name_text(plan, "Ghoolomjon")

    # Assert
    assert plan.chunks[1].text == "Gulomjon"


def test_plan_with_name_text_returns_err_when_there_is_no_name_chunk() -> None:
    # Arrange
    plan = simple_plan().with_chunk_replaced(
        1, simple_plan().chunks[1].model_copy(update={"is_name_chunk": False})
    )

    # Act
    result = plan_with_name_text(plan, "Anything")

    # Assert
    assert is_err(result)


def test_plan_with_chunk_text_returns_err_for_an_out_of_range_index() -> None:
    # Arrange / Act
    result = plan_with_chunk_text(simple_plan(), 99, "text")

    # Assert
    assert is_err(result)
    assert result.error.context["chunk_index"] == 99


def test_plan_with_chunk_text_returns_err_for_blank_text() -> None:
    # Arrange / Act
    result = plan_with_chunk_text(simple_plan(), 1, "  ")

    # Assert
    assert is_err(result)


def test_a_name_that_needs_no_respelling_is_left_exactly_as_written() -> None:
    # Arrange: an ASCII name where display and submitted forms already agree.
    lyrics = make_lyrics(name_display="Aziza")

    # Act
    result = _build(lyrics=lyrics, name_submitted="Aziza")

    # Assert
    assert is_ok(result)
    index = result.value.name_chunk_index
    assert index is not None
    assert "Aziza" in result.value.chunks[index].text
