
# Latin ones are the SUBJECT of this module, not a typo in it.
"""Uzbek Latin <-> Cyrillic, both directions, with the digraphs and the Russian differences."""

from __future__ import annotations

import pytest

from hbd.contracts import Language, Script
from hbd.names.translit import cyrillic_to_latin, latin_to_cyrillic, transliterate

LATIN_TO_CYRILLIC_CASES = [
    ("Gʻulomjon", "Ғуломжон"),
    ("Oʻktam", "Ўктам"),
    ("Ulugʻbek", "Улуғбек"),
    ("Toʻlqin", "Тўлқин"),
    ("Shohruh", "Шоҳруҳ"),
    ("Chorshanba", "Чоршанба"),
    ("Xurshid", "Хуршид"),
    ("Qodir", "Қодир"),
    ("Nigora", "Нигора"),
    ("Jasur", "Жасур"),
    ("Yulduz", "Юлдуз"),
    ("Ziyoda", "Зиёда"),
    ("Yaqub", "Яқуб"),
    ("Sanʼat", "Санъат"),
    ("Elyor", "Элёр"),
]

CYRILLIC_TO_LATIN_CASES = [
    ("Ғуломжон", "Gʻulomjon"),
    ("Ўктам", "Oʻktam"),
    ("Улуғбек", "Ulugʻbek"),
    ("Шоҳруҳ", "Shohruh"),
    ("Хуршид", "Xurshid"),
    ("Қодир", "Qodir"),
    ("Нигора", "Nigora"),
    ("Жасур", "Jasur"),
    ("Юлдуз", "Yulduz"),
    ("Зиёда", "Ziyoda"),
    ("Санъат", "Sanʼat"),
]


@pytest.mark.parametrize(("latin", "cyrillic"), LATIN_TO_CYRILLIC_CASES)
def test_latin_transliterates_to_uzbek_cyrillic(latin: str, cyrillic: str) -> None:
    assert latin_to_cyrillic(latin) == cyrillic


@pytest.mark.parametrize(("cyrillic", "latin"), CYRILLIC_TO_LATIN_CASES)
def test_uzbek_cyrillic_transliterates_back_to_latin(cyrillic: str, latin: str) -> None:
    assert cyrillic_to_latin(cyrillic, language=Language.UZ_CYRL) == latin


@pytest.mark.parametrize(("latin", "cyrillic"), LATIN_TO_CYRILLIC_CASES)
def test_a_round_trip_through_cyrillic_returns_the_original_latin(
    latin: str, cyrillic: str
) -> None:
    # Arrange / Act
    round_tripped = cyrillic_to_latin(latin_to_cyrillic(latin), language=Language.UZ_CYRL)

    # Assert
    assert round_tripped == latin


def test_the_digraph_mark_survives_the_round_trip_as_u02bb() -> None:
    # Arrange — the whole product depends on this one character coming back intact
    assert cyrillic_to_latin("Ғуломжон", language=Language.UZ_CYRL) == "Gʻulomjon"


def test_word_initial_e_becomes_cyrillic_e_with_a_diaeresis_free_form() -> None:
    # Arrange — Uzbek Cyrillic writes a word-initial /e/ as э, not е
    assert latin_to_cyrillic("Elyor") == "Элёр"


def test_non_initial_e_stays_a_plain_cyrillic_e() -> None:
    assert latin_to_cyrillic("Bekzod") == "Бекзод"


def test_word_initial_cyrillic_e_romanises_with_the_y_glide() -> None:
    assert cyrillic_to_latin("Елена", language=Language.RU) == "Yelena"


def test_non_initial_cyrillic_e_romanises_without_the_glide() -> None:
    assert cyrillic_to_latin("Сергей", language=Language.RU) == "Sergey"


def test_russian_romanisation_uses_kh_not_x() -> None:
    # Arrange — the Uzbek convention would produce the unreadable "Mixail"
    assert cyrillic_to_latin("Михаил", language=Language.RU) == "Mikhail"


def test_russian_romanisation_uses_zh_for_zhe() -> None:
    assert cyrillic_to_latin("Жанна", language=Language.RU) == "Zhanna"


def test_uzbek_romanisation_uses_j_for_zhe() -> None:
    assert cyrillic_to_latin("Жасур", language=Language.UZ_CYRL) == "Jasur"


def test_yo_is_preserved_when_romanising_a_russian_name() -> None:
    # Arrange — Алёна is /ɐˈlʲɵnə/; losing the ё makes it a different name
    assert cyrillic_to_latin("Алёна", language=Language.RU) == "Alyona"


def test_the_romanisation_table_is_inferred_from_a_russian_only_letter() -> None:
    # Arrange — щ is effectively Russian-only, so no language argument is needed
    assert cyrillic_to_latin("Щербак") == "Shcherbak"


def test_uzbek_only_letters_are_folded_when_the_target_language_is_russian() -> None:
    # Arrange — Ў Қ Ғ Ҳ do not exist in the Russian alphabet. ў folds to the o-vowel that
    # gets it pronounced, not to the у of conventional Russian spelling.
    assert latin_to_cyrillic("Toʻlqin", language=Language.RU) == "Толкин"


def test_uzbek_cyrillic_target_keeps_the_uzbek_only_letters() -> None:
    assert latin_to_cyrillic("Toʻlqin", language=Language.UZ_CYRL) == "Тўлқин"


def test_uppercase_is_preserved_across_a_digraph() -> None:
    assert latin_to_cyrillic("SHOHRUH") == "ШОҲРУҲ"


def test_title_case_is_preserved_across_a_digraph() -> None:
    assert latin_to_cyrillic("Shohruh") == "Шоҳруҳ"


def test_casing_of_the_turned_comma_digraph_is_preserved() -> None:
    assert latin_to_cyrillic("Gʻulomjon")[0] == "Ғ"


def test_spaces_and_hyphens_pass_through_untouched() -> None:
    assert latin_to_cyrillic("Ali-Vali Nur") == "Али-Вали Нур"


def test_transliterate_leaves_text_already_in_the_target_script_alone() -> None:
    assert transliterate("Nigora", target=Script.LATIN) == "Nigora"
    assert transliterate("Нигора", target=Script.CYRILLIC) == "Нигора"


def test_transliterate_converts_into_the_requested_script() -> None:
    assert transliterate("Нигора", target=Script.LATIN) == "Nigora"
    assert transliterate("Nigora", target=Script.CYRILLIC) == "Нигора"


def test_a_typed_apostrophe_variant_is_canonicalised_before_transliteration() -> None:
    # Arrange — the user typed U+2018, which is not in any transliteration table
    assert latin_to_cyrillic("G‘ulomjon") == "Ғуломжон"
