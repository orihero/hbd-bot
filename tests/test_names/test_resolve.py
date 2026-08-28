"""The front door: validation at the boundary, and a Result that never raises."""

from __future__ import annotations

import pytest

from hbd.config import DEFAULT_NAME_CANDIDATE_ORDER
from hbd.contracts import (
    MAX_RECIPIENT_NAME_CHARS,
    Language,
    NameStrategy,
    RecipientName,
    Result,
    Script,
    is_err,
    is_ok,
)
from hbd.errors import ErrorCode
from hbd.names.resolve import MAX_NAME_WORDS, display_form, resolve_name

ORDER = DEFAULT_NAME_CANDIDATE_ORDER


def _resolve(
    raw: str, ui_language: Language = Language.UZ_LATN
) -> Result[RecipientName]:
    return resolve_name(raw, candidate_order=ORDER, ui_language=ui_language)


def test_a_typed_smart_quote_resolves_to_the_canonical_display_form() -> None:
    # Arrange — what a phone keyboard actually sends
    typed = "G‘ulomjon"

    # Act
    result = _resolve(typed)

    # Assert
    assert is_ok(result)
    assert result.value.display == "Gʻulomjon"
    assert result.value.raw == typed


def test_the_raw_input_is_preserved_alongside_the_display_form() -> None:
    # Act
    result = _resolve("g'ulomjon")

    # Assert
    assert is_ok(result)
    assert result.value.raw == "g'ulomjon"
    assert result.value.display == "Gʻulomjon"


def test_an_all_lowercase_name_is_capitalised() -> None:
    result = _resolve("nigora")
    assert is_ok(result)
    assert result.value.display == "Nigora"


def test_deliberate_internal_casing_is_left_alone() -> None:
    # Arrange — a name's casing belongs to its owner
    result = _resolve("McDonald")
    assert is_ok(result)
    assert result.value.display == "McDonald"


def test_each_word_of_a_two_part_name_is_capitalised() -> None:
    result = _resolve("ali vali")
    assert is_ok(result)
    assert result.value.display == "Ali Vali"


def test_the_script_is_detected_from_the_name_not_the_interface_language() -> None:
    # Arrange — a Russian-speaking user naming an Uzbek recipient in Latin
    result = _resolve("Gʻulomjon", ui_language=Language.RU)

    # Assert
    assert is_ok(result)
    assert result.value.script is Script.LATIN


def test_a_cyrillic_name_reports_the_cyrillic_script() -> None:
    result = _resolve("Ғуломжон", ui_language=Language.UZ_CYRL)
    assert is_ok(result)
    assert result.value.script is Script.CYRILLIC
    assert result.value.language is Language.UZ_CYRL


def test_the_lookup_key_is_script_and_case_independent() -> None:
    # Arrange
    latin = _resolve("Gʻulomjon")
    cyrillic = _resolve("Ғуломжон", ui_language=Language.UZ_CYRL)

    # Assert
    assert is_ok(latin)
    assert is_ok(cyrillic)
    assert latin.value.lookup_key == cyrillic.value.lookup_key == "gulomjon"


def test_the_candidates_follow_the_configured_order() -> None:
    # Arrange
    order = (NameStrategy.PHONETIC, NameStrategy.STRIPPED)

    # Act
    result = resolve_name("Gʻulomjon", candidate_order=order, ui_language=Language.UZ_LATN)

    # Assert
    assert is_ok(result)
    assert [candidate.strategy for candidate in result.value.candidates] == list(order)


def test_candidate_at_walks_the_ranks_and_stops_at_the_end() -> None:
    # Arrange
    result = _resolve("Gʻulomjon")
    assert is_ok(result)
    name = result.value

    # Act / Assert
    assert name.candidate_at(0) is name.candidates[0]
    assert name.candidate_at(len(name.candidates)) is None


@pytest.mark.parametrize(
    ("raw", "reason"),
    [
        pytest.param("", "empty", id="empty"),
        pytest.param("   ", "empty", id="whitespace-only"),
        pytest.param("a" * (MAX_RECIPIENT_NAME_CHARS + 1), "too_long", id="too-long"),
        pytest.param("123", "no_letters", id="digits-only"),
        pytest.param("Aziza2", "unsupported_character", id="digit-inside"),
        pytest.param("Aziza <3", "unsupported_character", id="symbol"),
        pytest.param("Aziza 🎂", "unsupported_character", id="emoji"),
        pytest.param("---", "no_letters", id="punctuation-only"),
        pytest.param("a b c d e", "too_many_words", id="sentence"),
    ],
)
def test_invalid_input_returns_a_validation_error_with_a_reason(raw: str, reason: str) -> None:
    # Act
    result = _resolve(raw)

    # Assert
    assert is_err(result)
    assert result.error.error_code is ErrorCode.INVALID_INPUT
    assert result.error.context["reason"] == reason


def test_an_invalid_name_is_never_retryable() -> None:
    result = _resolve("")
    assert is_err(result)
    assert result.error.is_retryable is False


def test_an_invalid_name_carries_a_user_facing_locale_key() -> None:
    result = _resolve("Aziza2")
    assert is_err(result)
    assert result.error.user_message_key == "error.invalid_input"


@pytest.mark.parametrize(
    "raw",
    [
        pytest.param("\x00", id="null-byte"),
        pytest.param("\u200b", id="zero-width-space"),
        pytest.param("'''", id="marks-only"),
        pytest.param("\U00013000", id="egyptian-hieroglyph"),
        pytest.param("\ufdfa", id="arabic-ligature"),
    ],
)
def test_hostile_input_comes_back_as_an_error_instead_of_an_exception(raw: str) -> None:
    # Arrange / Act
    result = _resolve(raw)

    # Assert
    assert is_err(result)
    assert result.error.error_code is ErrorCode.INVALID_INPUT


@pytest.mark.parametrize(
    "raw",
    [
        pytest.param("سمير", id="arabic"),
        pytest.param("美玲", id="han"),
        pytest.param("Δημήτρης", id="greek"),
    ],
)
def test_a_script_we_cannot_romanise_is_rejected_rather_than_silently_mangled(raw: str) -> None:
    # Arrange / Act — we cannot pronounce it, cannot verify it, and must not pretend
    result = _resolve(raw)

    # Assert
    assert is_err(result)
    assert result.error.context["reason"] == "unsupported_script"


def test_a_cyrillic_letter_we_cannot_romanise_is_rejected_not_silently_dropped() -> None:
    # Arrange — Serbian ђ is Cyrillic, so the script check passes, but no table romanises it
    result = _resolve("Ђорђе", ui_language=Language.RU)

    # Assert
    assert is_err(result)
    assert result.error.context["reason"] == "unsupported_script"


def test_a_karakalpak_name_resolves_because_karakalpakstan_is_in_uzbekistan() -> None:
    # Arrange — ә and ң are in the Karakalpak Cyrillic alphabet, not the Uzbek one
    result = _resolve("Гүлназ", ui_language=Language.UZ_CYRL)

    # Assert
    assert is_ok(result)
    assert result.value.lookup_key == "gulnaz"


def test_a_name_at_exactly_the_length_limit_is_accepted() -> None:
    # Arrange
    raw = "a" * MAX_RECIPIENT_NAME_CHARS

    # Act
    result = _resolve(raw)

    # Assert
    assert is_ok(result)


def test_a_name_with_exactly_the_maximum_word_count_is_accepted() -> None:
    # Arrange
    raw = " ".join(["Ali"] * MAX_NAME_WORDS)

    # Act / Assert
    assert is_ok(_resolve(raw))


def test_surrounding_whitespace_is_trimmed_rather_than_rejected() -> None:
    result = _resolve("  Nigora  ")
    assert is_ok(result)
    assert result.value.raw == "Nigora"


def test_a_hyphenated_double_name_is_accepted() -> None:
    result = _resolve("Ali-Vali")
    assert is_ok(result)
    assert result.value.display == "Ali-Vali"


def test_a_name_with_a_period_is_accepted() -> None:
    assert is_ok(_resolve("Ali V."))


def test_display_form_canonicalises_without_validating() -> None:
    assert display_form("g‘ulomjon").text == "Gʻulomjon"


def test_the_resolved_name_satisfies_the_frozen_contract_model() -> None:
    # Arrange / Act
    result = _resolve("Gʻulomjon")

    # Assert — RecipientName's own validator rejects non-dense ranks
    assert is_ok(result)
    assert [candidate.rank for candidate in result.value.candidates] == list(
        range(len(result.value.candidates))
    )
