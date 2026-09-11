"""Name substitution and audio tags — the one text transformation the product rests on."""

from __future__ import annotations

from bayram.providers.tts.markup import (
    NAME_PLACEHOLDER,
    apply_mood_tag,
    apply_name,
    normalize_for_match,
    render_name,
    strip_markup,
)
from tests.conftest import UZBEK_NAME_CANONICAL, UZBEK_NAME_TYPED


# ---------------------------------------------------------------------------
# Locating the name
# ---------------------------------------------------------------------------
def test_substitutes_into_an_explicit_placeholder() -> None:
    # Arrange
    text = f"Happy birthday, {NAME_PLACEHOLDER}!"

    # Act
    application = apply_name(text, name_submitted="Gulomjon")

    # Assert
    assert application.text == "Happy birthday, Gulomjon!"
    assert application.is_applied
    assert application.replacement_count == 1


def test_replaces_every_occurrence_of_the_placeholder() -> None:
    # Arrange
    text = f"{NAME_PLACEHOLDER}, oh {NAME_PLACEHOLDER}!"

    # Act
    application = apply_name(text, name_submitted="Alyona")

    # Assert
    assert application.replacement_count == 2
    assert NAME_PLACEHOLDER not in application.text


def test_matches_the_display_name_spelled_with_a_different_apostrophe() -> None:
    # Arrange — the copy uses U+02BB, the submitted candidate has no mark at all.
    text = f"Assalomu alaykum, {UZBEK_NAME_CANONICAL}!"

    # Act
    application = apply_name(text, name_submitted="Gulomjon")

    # Assert
    assert application.text == "Assalomu alaykum, Gulomjon!"
    assert application.is_applied


def test_matches_a_typed_name_carrying_a_curly_quote() -> None:
    # Arrange
    text = f"Tabriklaymiz, {UZBEK_NAME_TYPED}!"

    # Act
    application = apply_name(text, name_submitted="Gu-lom-jon")

    # Assert
    assert "Gu-lom-jon" in application.text


def test_reports_not_applied_when_the_name_is_absent_from_the_script() -> None:
    # Arrange
    text = "Happy birthday to you!"

    # Act
    application = apply_name(text, name_submitted="Gulomjon")

    # Assert — the text is returned untouched so the caller can still synthesise.
    assert application.text == text
    assert not application.is_applied
    assert application.replacement_count == 0


def test_reports_not_applied_when_the_submitted_name_has_no_letters() -> None:
    # Act
    application = apply_name("Hello Gulomjon", name_submitted="---")

    # Assert
    assert not application.is_applied


def test_leaves_a_longer_word_containing_the_name_alone() -> None:
    # Arrange — token matching, not substring matching.
    text = "The Gulomjonov family sends love"

    # Act
    application = apply_name(text, name_submitted="Gulomjon")

    # Assert
    assert not application.is_applied


# ---------------------------------------------------------------------------
# Phoneme markup
# ---------------------------------------------------------------------------
def test_renders_bare_orthography_when_the_engine_has_no_phoneme_support() -> None:
    # Act
    rendered = render_name("Gulomjon", name_ipa="\u0261ulomd\u0292on", is_phoneme_supported=False)

    # Assert — v3 would read the markup aloud, so it is never emitted.
    assert rendered == "Gulomjon"


def test_renders_a_phoneme_element_when_the_engine_supports_it() -> None:
    # Act
    rendered = render_name(
        "Alyona", name_ipa="\u0250\u02c8l\u02b2\u0275n\u0259", is_phoneme_supported=True
    )

    # Assert
    assert rendered.startswith('<phoneme alphabet="ipa" ph="')
    assert "Alyona</phoneme>" in rendered


def test_escapes_ipa_that_would_otherwise_break_the_attribute() -> None:
    # Act
    rendered = render_name("Ann", name_ipa='a"n', is_phoneme_supported=True)

    # Assert
    assert '"a&quot;n"' in rendered


def test_renders_bare_orthography_when_no_ipa_was_supplied() -> None:
    # Act
    rendered = render_name("Gulomjon", name_ipa=None, is_phoneme_supported=True)

    # Assert
    assert rendered == "Gulomjon"


# ---------------------------------------------------------------------------
# Mood tags
# ---------------------------------------------------------------------------
def test_prefixes_a_known_audio_tag() -> None:
    # Act
    text, is_applied = apply_mood_tag("Congratulations!", "excited")

    # Assert
    assert text == "[excited] Congratulations!"
    assert is_applied


def test_drops_an_unknown_mood_rather_than_speaking_it_aloud() -> None:
    # Act
    text, is_applied = apply_mood_tag("Congratulations!", "bewildered")

    # Assert
    assert text == "Congratulations!"
    assert not is_applied


def test_accepts_a_mood_already_written_in_brackets() -> None:
    # Act
    text, is_applied = apply_mood_tag("Hi", "[Happy]")

    # Assert
    assert text == "[happy] Hi"
    assert is_applied


# ---------------------------------------------------------------------------
# Normalisation and stripping
# ---------------------------------------------------------------------------
def test_normalisation_makes_every_spelling_of_one_name_compare_equal() -> None:
    # Act
    keys = {
        normalize_for_match(UZBEK_NAME_CANONICAL),
        normalize_for_match(UZBEK_NAME_TYPED),
        normalize_for_match("G'ulomjon"),
        normalize_for_match("GULOMJON"),
    }

    # Assert
    assert keys == {"gulomjon"}


def test_strip_markup_removes_tags_and_collapses_the_gap() -> None:
    # Act
    spoken = strip_markup('[excited] Hello <phoneme ph="x">Ann</phoneme>  today')

    # Assert
    assert spoken == "Hello Ann today"
