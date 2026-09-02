# Latin ones are the SUBJECT of this module, not a typo in it.
"""Unicode canonicalisation: one test per apostrophe variant a real keyboard emits."""

from __future__ import annotations

import pytest

from hbd.names.marks import (
    APOSTROPHE_VARIANTS,
    MODIFIER_APOSTROPHE,
    TURNED_COMMA,
    canonicalize_marks,
    has_mark,
    normalize_input,
    strip_marks,
    to_ascii_marks,
)

# Every variant, named, so a failure report says WHICH character broke.
VARIANTS = [
    pytest.param("'", id="U+0027-apostrophe"),
    pytest.param("`", id="U+0060-grave"),
    pytest.param("´", id="U+00B4-acute"),
    pytest.param("ʹ", id="U+02B9-prime"),
    pytest.param("ʻ", id="U+02BB-turned-comma"),
    pytest.param("ʼ", id="U+02BC-modifier-apostrophe"),
    pytest.param("ʽ", id="U+02BD-reversed-comma"),
    pytest.param("ˈ", id="U+02C8-vertical-line"),
    pytest.param("՚", id="U+055A-armenian"),
    pytest.param("‘", id="U+2018-left-single-quote"),
    pytest.param("’", id="U+2019-right-single-quote"),
    pytest.param("‚", id="U+201A-low-9"),
    pytest.param("‛", id="U+201B-high-reversed-9"),
    pytest.param("′", id="U+2032-prime"),
    pytest.param("‵", id="U+2035-reversed-prime"),
    pytest.param("＇", id="U+FF07-fullwidth"),
]


@pytest.mark.parametrize("variant", VARIANTS)
def test_every_variant_after_g_becomes_turned_comma(variant: str) -> None:
    # Arrange
    typed = f"G{variant}ulomjon"

    # Act
    canonical = canonicalize_marks(typed)

    # Assert
    assert canonical == f"G{TURNED_COMMA}ulomjon"


@pytest.mark.parametrize("variant", VARIANTS)
def test_every_variant_after_o_becomes_turned_comma(variant: str) -> None:
    # Arrange
    typed = f"O{variant}ktam"

    # Act
    canonical = canonicalize_marks(typed)

    # Assert
    assert canonical == f"O{TURNED_COMMA}ktam"


@pytest.mark.parametrize("variant", VARIANTS)
def test_every_variant_after_any_other_letter_becomes_tutuq_belgisi(variant: str) -> None:
    # Arrange — Maʼruf is a real name and the mark is a tutuq belgisi, not a digraph
    typed = f"Ma{variant}ruf"

    # Act
    canonical = canonicalize_marks(typed)

    # Assert
    assert canonical == f"Ma{MODIFIER_APOSTROPHE}ruf"


def test_lowercase_digraph_base_letters_also_take_the_turned_comma() -> None:
    assert canonicalize_marks("go'zal") == f"go{TURNED_COMMA}zal"


def test_canonicalisation_is_idempotent() -> None:
    # Arrange
    once = canonicalize_marks("G‘ulomjon va Ma'ruf")

    # Act
    twice = canonicalize_marks(once)

    # Assert
    assert once == twice


def test_leading_mark_is_dropped_because_it_has_no_base_letter() -> None:
    assert canonicalize_marks("'Aziza") == "Aziza"


def test_strip_marks_removes_every_variant() -> None:
    # Arrange
    typed = "".join(f"a{variant}" for variant in sorted(APOSTROPHE_VARIANTS))

    # Act
    stripped = strip_marks(typed)

    # Assert
    assert stripped == "a" * len(APOSTROPHE_VARIANTS)


def test_to_ascii_marks_uses_a_plain_apostrophe() -> None:
    assert to_ascii_marks(f"G{TURNED_COMMA}ulomjon") == "G'ulomjon"


def test_has_mark_is_true_for_a_typed_variant_and_false_for_a_plain_name() -> None:
    assert has_mark("G‘ulomjon") is True
    assert has_mark("Gulomjon") is False


def test_normalize_input_strips_zero_width_characters() -> None:
    # Arrange — a zero-width space pasted from a web page
    typed = "Gul\u200bnora"

    # Act
    normalized = normalize_input(typed)

    # Assert
    assert normalized == "Gulnora"


def test_normalize_input_collapses_whitespace_and_trims() -> None:
    assert normalize_input("  Ali   Vali \n") == "Ali Vali"


def test_normalize_input_folds_a_non_breaking_space_to_a_plain_space() -> None:
    assert normalize_input("Ali Vali") == "Ali Vali"


def test_normalize_input_folds_an_em_dash_to_a_hyphen() -> None:
    assert normalize_input("Anna—Maria") == "Anna-Maria"


def test_normalize_input_composes_a_decomposed_letter() -> None:
    # Arrange — Cyrillic ё typed as е + U+0308 COMBINING DIAERESIS
    decomposed = "\u0410\u043b\u0435\u0308\u043d\u0430"

    # Act
    normalized = normalize_input(decomposed)

    # Assert
    assert normalized == "Алёна"


def test_normalize_input_drops_a_control_character() -> None:
    assert normalize_input("Aziza") == "Aziza"


def test_normalize_input_is_idempotent() -> None:
    once = normalize_input(" G\u2018ulom\u200bjon ")
    assert normalize_input(once) == once


def test_normalize_input_returns_empty_for_whitespace_only_input() -> None:
    assert normalize_input("   \t  ") == ""
