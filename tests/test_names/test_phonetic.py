"""English-orthography respelling — the spelling aimed at the vendor's grapheme model."""

from __future__ import annotations

import pytest

from bayram.contracts import Language
from bayram.names.phonetic import respell_phonetically

CASES = [
    ("Gʻulomjon", "Ghoolomjon"),
    ("Ulugʻbek", "Oolooghbek"),
    ("Xurshid", "Khoorsheed"),
    ("Qodir", "Kodeer"),
    ("Nigora", "Neegora"),
    ("Jasur", "Jasoor"),
    ("Aziza", "Azeeza"),
    ("Oʻktam", "Oktam"),
    ("Maʼruf", "Maroof"),
    ("Shohruh", "Shohrooh"),
]


@pytest.mark.parametrize(("name", "expected"), CASES)
def test_respells_uzbek_latin_for_an_english_grapheme_model(name: str, expected: str) -> None:
    assert respell_phonetically(name) == expected


def test_the_gh_digraph_replaces_the_turned_comma_after_g() -> None:
    # Arrange — a model that ignores U+02BB reads "gh" correctly
    assert respell_phonetically("Gʻulomjon").startswith("Gh")


def test_the_turned_comma_after_o_collapses_into_a_plain_o() -> None:
    assert respell_phonetically("Oʻktam") == "Oktam"


def test_the_tutuq_belgisi_is_dropped_entirely() -> None:
    assert respell_phonetically("Raʼno") == "Rano"


def test_uzbek_x_becomes_kh() -> None:
    assert respell_phonetically("Xurshid").startswith("Kh")


def test_uzbek_q_becomes_k() -> None:
    assert respell_phonetically("Qodir").startswith("K")


def test_cyrillic_input_is_romanised_before_respelling() -> None:
    assert respell_phonetically("Ғуломжон") == "Ghoolomjon"


def test_a_russian_name_respells_through_the_russian_romanisation() -> None:
    assert respell_phonetically("Михаил", language=Language.RU) == "Meekhaeel"


def test_capitalisation_of_the_first_unit_is_preserved() -> None:
    assert respell_phonetically("nigora") == "neegora"
    assert respell_phonetically("Nigora") == "Neegora"


def test_each_word_of_a_two_part_name_is_capitalised_independently() -> None:
    assert respell_phonetically("Ali Vali") == "Alee Valee"


def test_a_hyphen_is_preserved_and_starts_a_new_word() -> None:
    assert respell_phonetically("Ali-Vali") == "Alee-Valee"


def test_respelling_a_name_with_no_respellable_letters_returns_it_unchanged() -> None:
    assert respell_phonetically("Zebo") == "Zebo"


def test_empty_input_returns_empty() -> None:
    assert respell_phonetically("") == ""
