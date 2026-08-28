"""The vendor seam: a CompositionPlan becomes Eleven Music's documented request body."""

from __future__ import annotations

from hbd.contracts import (
    MIN_CHUNK_DURATION_MS,
    AudioRange,
    Chunk,
    CompositionPlan,
    ConditionStrength,
    ContextAdherence,
    Language,
    SongReference,
    is_err,
    is_ok,
)
from hbd.providers.music.payload import (
    MUSIC_PATH,
    build_compose_body,
    build_inpaint_body,
    guard_plan,
)
from tests.test_providers_music.conftest import TEST_MODEL_ID, TEST_OUTPUT_FORMAT, simple_plan


def _compose(plan: CompositionPlan) -> dict[str, object]:
    return build_compose_body(plan, model_id=TEST_MODEL_ID, output_format=TEST_OUTPUT_FORMAT)


def test_body_uses_the_vendors_documented_field_names() -> None:
    # Arrange / Act
    body = _compose(simple_plan())

    # Assert
    assert set(body) >= {
        "composition_plan",
        "model_id",
        "output_format",
        "force_instrumental",
        "store_for_inpainting",
    }


def test_music_length_ms_is_never_sent_alongside_a_composition_plan() -> None:
    """The two are mutually exclusive at the vendor; the plan's chunks carry the length.

    Learned from a live 422: ``You must not provide `music_length_ms` when passing
    `composition_plan```.
    """
    # Arrange
    plan = simple_plan()

    # Act
    body = _compose(plan)

    # Assert
    assert "music_length_ms" not in body
    chunks = body["composition_plan"]["chunks"]  # type: ignore[index]
    assert sum(c["duration_ms"] for c in chunks) == 48_000


def test_every_chunk_is_serialised_in_order() -> None:
    # Arrange
    plan = simple_plan(name_text="Gulomjon")

    # Act
    chunks = _compose(plan)["composition_plan"]["chunks"]  # type: ignore[index]

    # Assert
    assert [chunk["text"] for chunk in chunks] == ["intro line", "Gulomjon", "outro line"]
    assert [chunk["duration_ms"] for chunk in chunks] == [20_000, 8_000, 20_000]


def test_optional_chunk_fields_are_omitted_rather_than_sent_as_null() -> None:
    # Arrange: the conftest plan sets none of the optional conditioning fields.
    chunks = _compose(simple_plan())["composition_plan"]["chunks"]  # type: ignore[index]

    # Assert
    assert "context_adherence" not in chunks[0]
    assert "conditioning_ref" not in chunks[0]
    assert "condition_strength" not in chunks[0]


def test_optional_chunk_fields_are_sent_when_present() -> None:
    # Arrange
    plan = CompositionPlan(
        chunks=(
            Chunk(
                text="a",
                duration_ms=10_000,
                context_adherence=ContextAdherence.LOW,
                conditioning_ref=SongReference(
                    song_id="song_1", range=AudioRange(start_ms=0, end_ms=5_000)
                ),
                condition_strength=ConditionStrength.LOW,
            ),
        ),
        language=Language.UZ_LATN,
    )

    # Act
    chunk = _compose(plan)["composition_plan"]["chunks"][0]  # type: ignore[index]

    # Assert
    assert chunk["context_adherence"] == "low"
    assert chunk["conditioning_ref"] == {
        "song_id": "song_1",
        "range": {"start_ms": 0, "end_ms": 5_000},
    }
    assert chunk["condition_strength"] == "low"


def test_seed_is_sent_when_set_and_omitted_when_not() -> None:
    # Arrange / Act
    with_seed = _compose(simple_plan(seed=7))
    without_seed = _compose(simple_plan(seed=None))

    # Assert
    assert with_seed["seed"] == 7
    assert "seed" not in without_seed


def test_inpaint_keeps_the_song_stored_so_a_second_re_roll_is_possible() -> None:
    # Arrange: a plan that had storage turned off.
    plan = simple_plan().model_copy(update={"should_store_for_inpainting": False})

    # Act
    body = build_inpaint_body(
        plan,
        source_song_id="song_abc123",
        chunk_index=1,
        model_id=TEST_MODEL_ID,
        output_format=TEST_OUTPUT_FORMAT,
    )

    # Assert
    assert body["store_for_inpainting"] is True


def test_building_a_body_does_not_mutate_the_plan() -> None:
    # Arrange
    plan = simple_plan()
    before = plan.model_dump()

    # Act
    build_inpaint_body(
        plan,
        source_song_id="song_abc123",
        chunk_index=0,
        model_id=TEST_MODEL_ID,
        output_format=TEST_OUTPUT_FORMAT,
    )

    # Assert
    assert plan.model_dump() == before


def test_music_path_is_the_documented_endpoint() -> None:
    assert MUSIC_PATH == "/v1/music"


# ---------------------------------------------------------------------------
# guard_plan
# ---------------------------------------------------------------------------
def test_guard_accepts_a_well_formed_plan() -> None:
    # Arrange / Act
    result = guard_plan(simple_plan())

    # Assert
    assert is_ok(result)


def test_guard_rejects_a_blank_name_chunk_before_a_request_is_made() -> None:
    # Arrange: a name chunk that lost its name would render a nameless song.
    plan = simple_plan().with_chunk_replaced(
        1, Chunk(text="   ", duration_ms=8_000, is_name_chunk=True)
    )

    # Act
    result = guard_plan(plan)

    # Assert
    assert is_err(result)
    assert result.error.context["name_chunk_index"] == 1
    assert not result.error.is_retryable


def test_guard_rejects_a_vocal_plan_with_no_lyric_anywhere() -> None:
    # Arrange
    plan = CompositionPlan(
        chunks=(Chunk(text="", duration_ms=10_000), Chunk(text="  ", duration_ms=10_000)),
        language=Language.EN,
    )

    # Act
    result = guard_plan(plan)

    # Assert
    assert is_err(result)


def test_guard_allows_an_instrumental_plan_with_no_lyric() -> None:
    # Arrange
    plan = CompositionPlan(
        chunks=(Chunk(text="", duration_ms=10_000),),
        language=Language.EN,
        is_instrumental=True,
    )

    # Act
    result = guard_plan(plan)

    # Assert
    assert is_ok(result)


def test_a_plan_that_already_references_a_stored_song_carries_it_into_the_body() -> None:
    # Arrange
    plan = simple_plan().model_copy(update={"source_song_id": "song_prev"})

    # Act
    body = _compose(plan)

    # Assert
    assert body["source_song_id"] == "song_prev"


def test_context_adherence_serialises_as_the_vendor_enum_not_a_float() -> None:
    """Eleven Music rejects a float here: it wants 'low', 'medium' or 'high'.

    Learned from a live 422 — every chunk of a real compose was rejected with
    ``Input should be 'low', 'medium' or 'high'`` against inputs 0.7 and 1.0.
    """
    # Arrange
    plan = CompositionPlan(
        chunks=(
            Chunk(
                text="Gulnoza",
                duration_ms=MIN_CHUNK_DURATION_MS,
                context_adherence=ContextAdherence.HIGH,
                is_name_chunk=True,
            ),
        ),
        language=Language.UZ_LATN,
    )

    # Act
    body = build_compose_body(plan, model_id="music_v2", output_format="mp3_44100_128")

    # Assert
    sent = body["composition_plan"]["chunks"][0]["context_adherence"]
    assert sent in {"low", "medium", "high"}
    assert sent == "high"
    assert not isinstance(sent, float)


def test_inpaint_replays_untouched_sections_as_audio_reference_chunks() -> None:
    """The vendor's real inpaint shape: reference chunks either side of the new one.

    There is no top-level ``source_song_id``/``chunk_index``. Unchanged audio is named by
    ``{"song_id", "range": {"start_ms", "end_ms"}}`` chunks sitting in the plan itself, and
    only the target chunk is a generation chunk. Learned live: the old shape returned 200
    and regenerated the whole track, because the vendor ignores fields it does not honour.
    """
    # Arrange: 20_000 + 8_000 + 20_000, name in the middle.
    plan = simple_plan()

    # Act
    body = build_inpaint_body(
        plan,
        source_song_id="song_abc123",
        chunk_index=1,
        model_id=TEST_MODEL_ID,
        output_format=TEST_OUTPUT_FORMAT,
    )

    # Assert
    assert "source_song_id" not in body
    assert "chunk_index" not in body
    chunks = body["composition_plan"]["chunks"]
    assert len(chunks) == 3
    assert chunks[0] == {"song_id": "song_abc123", "range": {"start_ms": 0, "end_ms": 20_000}}
    assert chunks[1]["text"] == "Gulomjon"
    assert "song_id" not in chunks[1]
    assert chunks[2] == {
        "song_id": "song_abc123",
        "range": {"start_ms": 28_000, "end_ms": 48_000},
    }


def test_inpaint_omits_the_leading_reference_when_the_first_chunk_is_the_target() -> None:
    """A zero-length range is below the vendor's 50 ms floor, so it must not be sent."""
    # Arrange / Act
    body = build_inpaint_body(
        simple_plan(),
        source_song_id="song_abc123",
        chunk_index=0,
        model_id=TEST_MODEL_ID,
        output_format=TEST_OUTPUT_FORMAT,
    )

    # Assert
    chunks = body["composition_plan"]["chunks"]
    assert len(chunks) == 2
    assert chunks[0]["text"] == "intro line"
    assert chunks[1] == {
        "song_id": "song_abc123",
        "range": {"start_ms": 20_000, "end_ms": 48_000},
    }


def test_inpaint_omits_the_trailing_reference_when_the_last_chunk_is_the_target() -> None:
    # Arrange / Act
    body = build_inpaint_body(
        simple_plan(),
        source_song_id="song_abc123",
        chunk_index=2,
        model_id=TEST_MODEL_ID,
        output_format=TEST_OUTPUT_FORMAT,
    )

    # Assert
    chunks = body["composition_plan"]["chunks"]
    assert len(chunks) == 2
    assert chunks[0] == {"song_id": "song_abc123", "range": {"start_ms": 0, "end_ms": 28_000}}
    assert chunks[1]["text"] == "outro line"


def test_conditioning_ref_serialises_as_a_song_range_object_not_a_string() -> None:
    """``conditioning_ref`` is the same {song_id, range} object; ``condition_strength``
    is the vendor's enum, not a 0..1 float."""
    # Arrange
    plan = CompositionPlan(
        chunks=(
            Chunk(
                text="Gulnoza",
                duration_ms=MIN_CHUNK_DURATION_MS,
                conditioning_ref=SongReference(
                    song_id="song_abc123", range=AudioRange(start_ms=0, end_ms=20_000)
                ),
                condition_strength=ConditionStrength.XHIGH,
                is_name_chunk=True,
            ),
        ),
        language=Language.UZ_LATN,
    )

    # Act
    chunk = _compose(plan)["composition_plan"]["chunks"][0]  # type: ignore[index]

    # Assert
    assert chunk["conditioning_ref"] == {
        "song_id": "song_abc123",
        "range": {"start_ms": 0, "end_ms": 20_000},
    }
    assert chunk["condition_strength"] == "xhigh"
