"""The single character this product exists to get right, guarded in interface copy."""

from __future__ import annotations

import pytest

from bayram.i18n.orthography import (
    FORBIDDEN_UZ_LATN_CHARS,
    UZ_LATN_MODIFIER_APOSTROPHE,
    UZ_LATN_TURNED_COMMA,
    describe_chars,
    find_forbidden_chars,
)


def test_correct_uzbek_characters_are_the_expected_code_points() -> None:
    # Arrange / Act / Assert — these two constants are the whole contract.
    assert ord(UZ_LATN_TURNED_COMMA) == 0x02BB
    assert ord(UZ_LATN_MODIFIER_APOSTROPHE) == 0x02BC


def test_returns_empty_when_string_uses_canonical_orthography() -> None:
    # Arrange
    clean = "Oʻzbekcha toʻgʻri, maʼlumot ham toʻgʻri"

    # Act
    found = find_forbidden_chars(clean)

    # Assert
    assert found == ()


@pytest.mark.parametrize(
    ("char", "code_point"),
    [
        ("'", 0x0027),
        ("`", 0x0060),
        ("\u00b4", 0x00B4),
        ("‘", 0x2018),
        ("’", 0x2019),
    ],
)
def test_detects_each_forbidden_look_alike(char: str, code_point: int) -> None:
    # Arrange
    text = f"To{char}gʻri emas"

    # Act
    found = find_forbidden_chars(text)

    # Assert
    assert found == (char,)
    assert ord(char) == code_point


def test_reports_every_offender_when_several_are_present() -> None:
    # Arrange
    text = "O'zbek ‘tirnoq’ va `teskari`"

    # Act
    found = find_forbidden_chars(text)

    # Assert
    assert set(found) == {"'", "`", "‘", "’"}
    assert list(found) == [char for char in FORBIDDEN_UZ_LATN_CHARS if char in found]


def test_describe_chars_renders_code_points_for_operators() -> None:
    # Arrange
    chars = ("'", "‘")

    # Act
    described = describe_chars(chars)

    # Assert
    assert described == "U+0027, U+2018"


def test_describe_chars_returns_empty_string_for_no_offenders() -> None:
    assert describe_chars(()) == ""
