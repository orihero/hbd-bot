# Latin ones are the SUBJECT of this module, not a typo in it.
"""Syllabification, hyphenated respelling and final-syllable stress."""

from __future__ import annotations

import pytest

from hbd.contracts import Language
from hbd.names.syllables import hyphenate, stress_index, syllabify

UZBEK_LATIN_CASES = [
    ("Gulomjon", ("Gu", "lom", "jon")),
    ("Gʻulomjon", ("Gʻu", "lom", "jon")),
    ("Shohruh", ("Shoh", "ruh")),
    ("Nigora", ("Ni", "go", "ra")),
    ("Gulnora", ("Gul", "no", "ra")),
    ("Yangibek", ("Yan", "gi", "bek")),
    ("Iskandar", ("Is", "kan", "dar")),
    ("Zebo", ("Ze", "bo")),
    ("Bekzod", ("Bek", "zod")),
    ("Oʻktam", ("Oʻk", "tam")),
]

CYRILLIC_CASES = [
    ("Ғуломжон", ("Ғу", "лом", "жон")),
    ("Алёна", ("А", "лё", "на")),
    ("Ольга", ("Оль", "га")),
    ("Дмитрий", ("Дмит", "рий")),
    ("Санъат", ("Санъ", "ат")),
]


@pytest.mark.parametrize(("name", "expected"), UZBEK_LATIN_CASES)
def test_splits_uzbek_latin_names_into_syllables(name: str, expected: tuple[str, ...]) -> None:
    assert syllabify(name) == expected


@pytest.mark.parametrize(("name", "expected"), CYRILLIC_CASES)
def test_splits_cyrillic_names_into_syllables(name: str, expected: tuple[str, ...]) -> None:
    assert syllabify(name) == expected


def test_a_single_intervocalic_consonant_opens_the_next_syllable() -> None:
    # Arrange — Ni-go-ra, never Nig-o-ra
    assert syllabify("Nigora") == ("Ni", "go", "ra")


def test_two_intervocalic_consonants_split_between_the_syllables() -> None:
    assert syllabify("Gulnora") == ("Gul", "no", "ra")


def test_adjacent_vowels_are_split_between_syllables() -> None:
    assert syllabify("Saida") == ("Sa", "i", "da")


def test_the_o_turned_comma_digraph_counts_as_one_vowel() -> None:
    # Arrange — Oʻ is a single vowel, so Oʻktam has two syllables, not three
    assert syllabify("Oʻktam") == ("Oʻk", "tam")


def test_the_sh_digraph_counts_as_one_consonant() -> None:
    assert syllabify("Shohruh") == ("Shoh", "ruh")


def test_ng_is_not_a_digraph_because_uzbek_splits_between_them() -> None:
    assert syllabify("Yangibek") == ("Yan", "gi", "bek")


def test_a_soft_sign_never_opens_a_syllable() -> None:
    assert syllabify("Наталья") == ("На", "таль", "я")


def test_a_hard_sign_never_opens_a_syllable() -> None:
    assert syllabify("Санъат") == ("Санъ", "ат")


def test_a_single_syllable_name_is_returned_whole() -> None:
    assert syllabify("Nur") == ("Nur",)


def test_empty_text_produces_no_syllables() -> None:
    assert syllabify("") == ()


def test_word_separators_are_preserved_as_their_own_units() -> None:
    assert syllabify("Ali Vali") == ("A", "li", " ", "Va", "li")


def test_hyphenate_joins_syllables_with_a_hyphen() -> None:
    assert hyphenate("Gulomjon") == "Gu-lom-jon"


def test_hyphenate_does_not_double_up_an_existing_separator() -> None:
    assert hyphenate("Ali Vali") == "A-li Va-li"


def test_hyphenate_preserves_an_existing_hyphen_between_words() -> None:
    assert hyphenate("Ali-Vali") == "A-li-Va-li"


def test_hyphenate_accepts_a_custom_separator() -> None:
    assert hyphenate("Gulomjon", separator="·") == "Gu·lom·jon"


def test_a_typed_apostrophe_variant_is_canonicalised_before_splitting() -> None:
    assert syllabify("G‘ulomjon") == ("Gʻu", "lom", "jon")


@pytest.mark.parametrize("language", [Language.UZ_LATN, Language.UZ_CYRL])
def test_uzbek_stress_falls_on_the_final_syllable(language: Language) -> None:
    # Arrange
    syllables = syllabify("Gulomjon")

    # Act
    index = stress_index(syllables, language=language)

    # Assert
    assert index == len(syllables) - 1


@pytest.mark.parametrize("language", [Language.RU, Language.EN])
def test_lexical_stress_languages_report_no_stress_rather_than_guessing(
    language: Language,
) -> None:
    assert stress_index(syllabify("Екатерина"), language=language) is None


def test_stress_index_ignores_trailing_separators() -> None:
    # Arrange — a separator is not a syllable and cannot carry stress
    syllables = syllabify("Ali Vali")

    # Act
    index = stress_index(syllables, language=Language.UZ_LATN)

    # Assert
    assert index is not None
    assert syllables[index] == "li"


def test_stress_index_of_no_syllables_is_none() -> None:
    assert stress_index((), language=Language.UZ_LATN) is None
