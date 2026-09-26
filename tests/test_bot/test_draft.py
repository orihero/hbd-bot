"""The wizard draft: immutable, round-trippable, and suspicious of what storage returns.

It no longer has that dict to itself, which is what the last three tests here are about. FSM
data now holds EIGHT keys — the draft, the in-flight order id, its progress message id, the
checkout's three purchase markers, and the two identity caches ``clear_keeping_identity``
preserves. That count has been wrong in a comment three times: ``submitting.py`` once claimed
there were two, and this docstring itself said five until the checkout's keys were counted.
``src/bayram/bot/draft.py``'s module docstring is the list of record; this line exists only so a
reader here knows the dict is shared. A draft reader that assumed it was alone in it would
report an expired session to a customer whose draft is sitting right there.
"""

from __future__ import annotations

from bayram.bot.draft import (
    DRAFT_KEY,
    MAX_NOTE_CHARS,
    ONBOARDED_KEY,
    REQUIRED_ANSWERS,
    UI_LANGUAGE_KEY,
    WizardDraft,
    load_draft,
)
from bayram.contracts import Brief, Err, Genre, Language, Occasion, Ok, VoiceGender
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


# ---------------------------------------------------------------------------
# Sharing the FSM dict with the two identity caches
# ---------------------------------------------------------------------------
def test_the_three_state_keys_this_module_owns_are_distinct_strings() -> None:
    """One dict, three names, and a collision would be silent in both directions.

    ``UI_LANGUAGE_KEY`` and ``ONBOARDED_KEY`` are new neighbours of ``DRAFT_KEY``, and they are
    the two that survive ``handlers.common.clear_keeping_identity`` while the draft does not.
    Give any two of them the same string and the survivor overwrites the other: a cancelled run
    would leave a language where a draft is looked for, ``load_draft`` would report the wrong
    shape, and the customer would be told their session expired one tap after cancelling one.

    Asserted on the CONSTANTS rather than on their current values, because the values are
    storage keys a future release may want to rename and the invariant is that they differ.
    """
    # Arrange / Act / Assert
    assert len({DRAFT_KEY, UI_LANGUAGE_KEY, ONBOARDED_KEY}) == 3


def test_load_draft_ignores_the_identity_caches_sitting_beside_it() -> None:
    """The draft reader must not care what else is in the dict, and now something else is.

    Every read goes through ``load_draft(await state.get_data())`` — the whole dict, not the one
    key — so a reader that validated the dict rather than the value under ``DRAFT_KEY`` would
    start failing the moment onboarding began caching an identity next to it. The failure would
    not read as "an extra key": it would read as ``wizard.expired``, said to somebody whose
    draft is intact, at whichever step they happened to be on.
    """
    # Arrange — a live draft with both caches beside it, exactly as the FSM holds it
    draft = complete_draft()
    data = {
        **draft.to_state_data(),
        UI_LANGUAGE_KEY: Language.RU.value,
        ONBOARDED_KEY: True,
    }

    # Act
    restored = load_draft(data)

    # Assert
    assert isinstance(restored, Ok)
    assert restored.value == draft


def test_the_identity_caches_alone_are_not_mistaken_for_a_draft() -> None:
    """The state a cancelled run leaves behind: two caches and no draft.

    That is the ordinary resting state of an onboarded customer between songs, so it must
    report the MISSING KEY rather than an unreadable draft. The distinction is not cosmetic —
    ``read_draft`` answering ``None`` is what routes an update to the step router's expiry
    path, and a corrupt-payload error here would name a key the dict never contained.
    """
    # Arrange
    data = {UI_LANGUAGE_KEY: Language.RU.value, ONBOARDED_KEY: True}

    # Act
    result = load_draft(data)

    # Assert
    assert isinstance(result, Err)
    assert result.error.context["key"] == DRAFT_KEY
