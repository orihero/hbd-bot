"""The wizard draft: immutable, round-trippable, and suspicious of what storage returns."""

from __future__ import annotations

from hbd.bot.draft import DRAFT_KEY, MAX_NOTE_CHARS, REQUIRED_ANSWERS, WizardDraft, load_draft
from hbd.contracts import Brief, Err, Genre, Language, Occasion, Ok, VoiceGender
from tests.conftest import make_name


def complete_draft() -> WizardDraft:
    return WizardDraft(
        ui_language=Language.RU,
        occasion=Occasion.BIRTHDAY,
        genre=Genre.RETRO_ESTRADA,
        vocal_gender=VoiceGender.MALE,
        note="Loves the mountains",
        recipient=make_name(),
        output_language=Language.UZ_LATN,
    )


def test_note_limit_matches_the_brief_contract() -> None:
    # Arrange
    field = Brief.model_fields["note"]

    # Act
    limits = [meta for meta in field.metadata if hasattr(meta, "max_length")]

    # Assert — the wizard must not accept a note the contract will reject
    assert limits and limits[0].max_length == MAX_NOTE_CHARS


def test_updated_returns_a_new_object_and_leaves_the_original_alone() -> None:
    # Arrange
    original = WizardDraft()

    # Act
    changed = original.updated(genre=Genre.ROCK)

    # Assert
    assert changed is not original
    assert original.genre is None
    assert changed.genre is Genre.ROCK


def test_missing_answers_lists_every_unanswered_requirement() -> None:
    # Arrange
    draft = WizardDraft()

    # Act
    missing = draft.missing_answers

    # Assert
    assert missing == REQUIRED_ANSWERS
    assert not draft.is_complete


def test_to_brief_fails_with_the_missing_answers_in_context() -> None:
    # Arrange
    draft = complete_draft().updated(genre=None)

    # Act
    result = draft.to_brief()

    # Assert
    assert isinstance(result, Err)
    assert result.error.context["missing_answers"] == ["genre"]


def test_to_brief_builds_the_contract_model_when_complete() -> None:
    # Arrange
    draft = complete_draft()

    # Act
    result = draft.to_brief()

    # Assert
    assert isinstance(result, Ok)
    assert result.value.ui_language is Language.RU
    assert result.value.output_language is Language.UZ_LATN


def test_draft_round_trips_through_json_state_data() -> None:
    # Arrange
    draft = complete_draft()

    # Act
    restored = load_draft(draft.to_state_data())

    # Assert
    assert isinstance(restored, Ok)
    assert restored.value == draft


def test_load_draft_reports_a_missing_key_instead_of_raising() -> None:
    # Arrange / Act
    result = load_draft({})

    # Assert
    assert isinstance(result, Err)
    assert result.error.context["key"] == DRAFT_KEY


def test_load_draft_rejects_a_payload_of_the_wrong_shape() -> None:
    # Arrange / Act
    result = load_draft({DRAFT_KEY: "not-an-object"})

    # Assert
    assert isinstance(result, Err)
    assert result.error.context["actual_type"] == "str"


def test_load_draft_rejects_a_draft_written_by_an_incompatible_build() -> None:
    # Arrange — an unknown field, exactly what an older or newer schema looks like
    payload = {DRAFT_KEY: {"ui_language": "en", "unexpected_field": 1}}

    # Act
    result = load_draft(payload)

    # Assert
    assert isinstance(result, Err)
    assert result.error.context["issue_count"] >= 1


def test_load_draft_rejects_an_unknown_enum_value() -> None:
    # Arrange
    payload = {DRAFT_KEY: {"ui_language": "klingon"}}

    # Act
    result = load_draft(payload)

    # Assert
    assert isinstance(result, Err)
