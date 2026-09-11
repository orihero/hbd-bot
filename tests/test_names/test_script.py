"""Script detection and the Uzbek-vs-Russian Cyrillic distinction."""

from __future__ import annotations

import pytest

from bayram.contracts import Language, Script
from bayram.names.script import (
    detect_script,
    infer_name_language,
    is_russian_cyrillic,
    is_uzbek_cyrillic,
)


def test_detects_latin_for_an_uzbek_latin_name() -> None:
    # Arrange
    name = "Gʻulomjon"

    # Act
    profile = detect_script(name)

    # Assert
    assert profile.script is Script.LATIN
    assert profile.cyrillic_letters == 0
    assert profile.is_mixed is False


def test_the_uzbek_mark_is_not_counted_as_a_letter_of_either_script() -> None:
    # Arrange — U+02BB is category Lm and belongs to neither alphabet's census
    with_mark = detect_script("Gʻulomjon")
    without_mark = detect_script("Gulomjon")

    # Assert
    assert with_mark.latin_letters == without_mark.latin_letters


def test_detects_cyrillic_for_a_cyrillic_name() -> None:
    assert detect_script("Ғуломжон").script is Script.CYRILLIC


def test_reports_mixed_when_both_alphabets_appear() -> None:
    # Arrange — a paste artefact, not a name anyone typed on purpose
    profile = detect_script("Alisher Навоий")

    # Assert
    assert profile.is_mixed is True
    assert profile.latin_letters == 7
    assert profile.cyrillic_letters == 6


def test_dominant_script_wins_when_mixed() -> None:
    assert detect_script("Aли").script is Script.CYRILLIC


def test_empty_text_reports_latin_with_no_letters() -> None:
    # Act
    profile = detect_script("")

    # Assert
    assert profile.script is Script.LATIN
    assert profile.has_letters is False


def test_a_letter_from_a_third_script_is_counted_separately() -> None:
    # Arrange — neither alphabet, and the caller rejects it before it reaches a vendor
    profile = detect_script("Δημήτρης")

    # Assert
    assert profile.other_letters == 8
    assert profile.latin_letters == 0
    assert profile.cyrillic_letters == 0


def test_digits_and_punctuation_are_not_letters() -> None:
    assert detect_script("-. 123").has_letters is False


@pytest.mark.parametrize("name", ["Ўктам", "Қодир", "Ғуломжон", "Шоҳруҳ"])
def test_uzbek_only_cyrillic_letters_identify_uzbek_cyrillic(name: str) -> None:
    assert is_uzbek_cyrillic(name) is True
    assert is_russian_cyrillic(name) is False


@pytest.mark.parametrize("name", ["Кыргыз", "Щербак"])
def test_russian_only_cyrillic_letters_identify_russian(name: str) -> None:
    assert is_russian_cyrillic(name) is True
    assert is_uzbek_cyrillic(name) is False


def test_a_cyrillic_name_with_no_marker_is_ambiguous_to_both_predicates() -> None:
    # Arrange — Нигора is spelled identically in both Cyrillic alphabets
    name = "Нигора"

    # Assert
    assert is_uzbek_cyrillic(name) is False
    assert is_russian_cyrillic(name) is False


def test_uzbek_marker_beats_a_russian_marker_in_the_same_string() -> None:
    assert is_russian_cyrillic("Ўлыш") is False


def test_infers_uzbek_cyrillic_from_a_marker_letter() -> None:
    assert infer_name_language("Ғуломжон", fallback=Language.RU) is Language.UZ_CYRL


def test_infers_russian_from_a_russian_marker_letter() -> None:
    assert infer_name_language("Щербак", fallback=Language.UZ_CYRL) is Language.RU


def test_unmarked_cyrillic_falls_back_to_the_ui_language_when_it_is_cyrillic() -> None:
    assert infer_name_language("Нигора", fallback=Language.UZ_CYRL) is Language.UZ_CYRL


def test_unmarked_cyrillic_defaults_to_russian_when_the_ui_language_is_latin() -> None:
    # Arrange — a Latin interface says nothing about which Cyrillic alphabet was typed,
    # and Russian is the safer read of an unmarked Cyrillic string.
    assert infer_name_language("Нигора", fallback=Language.EN) is Language.RU


def test_latin_text_keeps_a_latin_ui_language() -> None:
    assert infer_name_language("Mikhail", fallback=Language.EN) is Language.EN


def test_latin_text_under_a_cyrillic_ui_language_reads_as_uzbek_latin() -> None:
    # Arrange — a Russian-speaking user typing Latin is, in this market, typing Uzbek Latin
    assert infer_name_language("Alyona", fallback=Language.RU) is Language.UZ_LATN
