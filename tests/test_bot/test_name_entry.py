"""Resolving a typed name — the step the whole product hangs on."""


# every apostrophe variant a real keyboard emits, plus a zero-width/no-break space.

from __future__ import annotations

import pytest

from bayram.bot.name_entry import (
    NAME_INVALID_KEY,
    NAME_TOO_LONG_KEY,
    NAME_TOO_MANY_WORDS_KEY,
    NAME_UNRESOLVED_KEY,
    resolve_typed_name,
)
from bayram.contracts import Err, Language, NameStrategy, Ok, RecipientName, Result, Script
from bayram.names.resolve import MAX_NAME_WORDS, resolve_name

DEFAULT_ORDER = (
    NameStrategy.STRIPPED,
    NameStrategy.CANONICAL,
    NameStrategy.HYPHENATED,
    NameStrategy.ASCII,
    NameStrategy.PHONETIC,
)

CANONICAL = "Gʻulomjon"  # U+02BB


def resolve(
    typed: str,
    *,
    language: Language = Language.UZ_LATN,
    order: tuple[NameStrategy, ...] = DEFAULT_ORDER,
) -> Result[RecipientName]:
    return resolve_typed_name(typed, ui_language=language, candidate_order=order)


@pytest.mark.parametrize(
    "typed",
    ["G‘ulomjon", "G’ulomjon", "G'ulomjon", "G`ulomjon", "G´ulomjon", CANONICAL],
)
def test_every_apostrophe_variant_canonicalises_to_the_same_display_form(typed: str) -> None:
    # Arrange / Act
    result = resolve(typed)

    # Assert
    assert isinstance(result, Ok)
    assert result.value.display == CANONICAL


def test_raw_input_is_preserved_alongside_the_display_form() -> None:
    # Arrange
    typed = "G‘ulomjon"

    # Act
    result = resolve(typed)

    # Assert
    assert isinstance(result, Ok)
    assert result.value.raw == typed
    assert result.value.display != typed


def test_candidate_ranks_are_dense_and_follow_the_configured_order() -> None:
    # Arrange
    order = (NameStrategy.CANONICAL, NameStrategy.STRIPPED, NameStrategy.HYPHENATED)

    # Act
    result = resolve("G‘ulomjon", order=order)

    # Assert
    assert isinstance(result, Ok)
    candidates = result.value.candidates
    assert tuple(c.rank for c in candidates) == tuple(range(len(candidates)))
    assert candidates[0].strategy is NameStrategy.CANONICAL
    assert candidates[0].text == CANONICAL


def test_reordering_the_configuration_reorders_the_candidates() -> None:
    # Arrange
    forward = (NameStrategy.STRIPPED, NameStrategy.CANONICAL)
    reversed_order = (NameStrategy.CANONICAL, NameStrategy.STRIPPED)

    # Act
    first = resolve("G‘ulomjon", order=forward)
    second = resolve("G‘ulomjon", order=reversed_order)

    # Assert — the ranking is configuration, not code
    assert isinstance(first, Ok)
    assert isinstance(second, Ok)
    assert first.value.candidates[0].strategy is NameStrategy.STRIPPED
    assert second.value.candidates[0].strategy is NameStrategy.CANONICAL


def test_duplicate_spellings_are_collapsed_so_no_retry_is_wasted() -> None:
    # Arrange — a name with no marks: stripped and canonical are identical
    order = (NameStrategy.STRIPPED, NameStrategy.CANONICAL)

    # Act
    result = resolve("Aziza", order=order)

    # Assert
    assert isinstance(result, Ok)
    assert len({candidate.text for candidate in result.value.candidates}) == len(
        result.value.candidates
    )


def test_lookup_key_is_script_and_mark_insensitive() -> None:
    # Arrange / Act
    latin = resolve("G‘ulomjon")
    stripped = resolve("Gulomjon")

    # Assert
    assert isinstance(latin, Ok)
    assert isinstance(stripped, Ok)
    assert latin.value.lookup_key == stripped.value.lookup_key


def test_cyrillic_name_is_detected_as_cyrillic() -> None:
    # Arrange / Act
    result = resolve("Алёна", language=Language.RU)

    # Assert
    assert isinstance(result, Ok)
    assert result.value.script is Script.CYRILLIC
    assert result.value.language is Language.RU


def test_russian_yo_is_preserved_in_the_display_form() -> None:
    # Arrange / Act
    result = resolve("Алёна", language=Language.RU)

    # Assert — Алёна is not Алена; the vowel carries the pronunciation
    assert isinstance(result, Ok)
    assert result.value.display == "Алёна"


def test_returns_invalid_when_the_input_has_no_letters() -> None:
    # Arrange / Act
    result = resolve("12345 !!")

    # Assert
    assert isinstance(result, Err)
    assert result.error.user_message_key == NAME_INVALID_KEY


def test_returns_too_long_with_the_limit_in_context() -> None:
    # Arrange / Act
    result = resolve("A" * 41)

    # Assert
    assert isinstance(result, Err)
    assert result.error.user_message_key == NAME_TOO_LONG_KEY
    assert result.error.context["limit"] == 40


def test_surrounding_whitespace_is_normalised_away() -> None:
    # Arrange / Act
    result = resolve("   Aziza ​  ")

    # Assert
    assert isinstance(result, Ok)
    assert result.value.display == "Aziza"


def test_never_raises_on_hostile_input() -> None:
    # Arrange
    hostile = ["", " ", "​", "<b>x</b>", "🙂", "\x00Aziza"]

    # Act / Assert — every one of these returns a Result, none of them raise
    for typed in hostile:
        assert isinstance(resolve(typed), Ok | Err)


# ---------------------------------------------------------------------------
# The bot must reject exactly what the golden-set resolver rejects.
#
# This module used to carry a second, weaker implementation, so `Bekzod123`, `王小明` and
# `Ali <script>` reached the lyric sheet and the vendor prompt, and `gulomjon` was shown
# to the customer uncapitalised. These tests are the fence against that regressing.
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    ("typed", "expected_key"),
    [
        ("Bekzod123", NAME_INVALID_KEY),
        ("Aziza 😀", NAME_INVALID_KEY),
        ("Ali <script>alert(1)</script>", NAME_INVALID_KEY),
        ("Дилноза!!!", NAME_INVALID_KEY),
        ("Ahmad Bek Toshmat Ali Vali Aka", NAME_TOO_MANY_WORDS_KEY),
        ("王小明", NAME_UNRESOLVED_KEY),
    ],
)
def test_rejects_what_the_core_resolver_rejects(typed: str, expected_key: str) -> None:
    # Arrange / Act
    result = resolve(typed)

    # Assert
    assert isinstance(result, Err)
    assert result.error.user_message_key == expected_key


def test_too_many_words_carries_the_word_limit_for_its_message() -> None:
    # Arrange / Act
    result = resolve("Ahmad Bek Toshmat Ali Vali Aka")

    # Assert
    assert isinstance(result, Err)
    assert result.error.context["limit"] == MAX_NAME_WORDS


def test_a_lower_case_name_is_capitalised_before_a_customer_reads_it() -> None:
    # Arrange / Act — the display form is what goes on the lyric sheet
    result = resolve("gulomjon")

    # Assert
    assert isinstance(result, Ok)
    assert result.value.display == "Gulomjon"


def test_the_machine_readable_reason_survives_into_the_operator_log() -> None:
    # Arrange / Act — the locale key is for the customer; `reason` is for triage
    result = resolve("Bekzod123")

    # Assert
    assert isinstance(result, Err)
    assert result.error.context["reason"] == "unsupported_character"


@pytest.mark.parametrize("typed", ["G‘ulomjon", "Алёна", "Aziza"])
def test_the_bot_and_the_golden_set_resolver_agree_exactly(typed: str) -> None:
    # Arrange / Act — one resolver, so an accepted name must be identical either way
    through_bot = resolve(typed)
    through_core = resolve_name(typed, candidate_order=DEFAULT_ORDER, ui_language=Language.UZ_LATN)

    # Assert
    assert isinstance(through_bot, Ok)
    assert isinstance(through_core, Ok)
    assert through_bot.value == through_core.value
