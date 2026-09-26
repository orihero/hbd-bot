"""The step both adapters share: persona resolution and name substitution."""

from __future__ import annotations

import logging

import pytest

from bayram.contracts import Language, is_err, is_ok
from bayram.errors import ValidationError
from bayram.providers.tts.preparation import prepare_speech
from bayram.providers.tts.registry import default_registry
from tests.conftest import UZBEK_NAME_CANONICAL
from tests.test_providers_tts.conftest import make_speech_request

PROVIDER = "test_vendor"
ALL_LANGUAGES = tuple(Language)


def test_substitutes_the_submitted_orthography_for_the_display_name() -> None:
    # Arrange
    request = make_speech_request(
        text=f"Happy birthday, {UZBEK_NAME_CANONICAL}!", name_submitted="Gulomjon"
    )

    # Act
    result = prepare_speech(
        request,
        registry=default_registry(),
        provider=PROVIDER,
        supported_languages=ALL_LANGUAGES,
    )

    # Assert — the display form never reaches the vendor.
    assert is_ok(result)
    assert result.value.text == "Happy birthday, Gulomjon!"
    assert UZBEK_NAME_CANONICAL not in result.value.text
    assert result.value.is_name_applied


def test_falls_back_to_the_personas_default_mood() -> None:
    # Arrange
    request = make_speech_request(mood=None)

    # Act
    result = prepare_speech(
        request,
        registry=default_registry(),
        provider=PROVIDER,
        supported_languages=ALL_LANGUAGES,
    )

    # Assert
    assert is_ok(result)
    assert result.value.mood == "excited"


def test_an_explicit_mood_overrides_the_personas_default() -> None:
    # Arrange
    request = make_speech_request(mood="gently")

    # Act
    result = prepare_speech(
        request,
        registry=default_registry(),
        provider=PROVIDER,
        supported_languages=ALL_LANGUAGES,
    )

    # Assert
    assert is_ok(result)
    assert result.value.mood == "gently"


def test_returns_err_for_a_language_this_vendor_does_not_serve() -> None:
    # Arrange
    request = make_speech_request(language=Language.RU, persona_id="podruga")

    # Act
    result = prepare_speech(
        request,
        registry=default_registry(),
        provider=PROVIDER,
        supported_languages=(Language.EN,),
    )

    # Assert
    assert is_err(result)
    assert isinstance(result.error, ValidationError)
    assert not result.error.is_retryable


def test_returns_err_for_a_persona_that_is_not_in_the_catalogue() -> None:
    # Arrange
    request = make_speech_request(persona_id="nobody")

    # Act
    result = prepare_speech(
        request,
        registry=default_registry(),
        provider=PROVIDER,
        supported_languages=ALL_LANGUAGES,
    )

    # Assert
    assert is_err(result)
    assert "nobody" in result.error.operator_message
    assert "known" in result.error.context


def test_returns_err_when_the_persona_exists_only_in_another_language() -> None:
    # Arrange — 'showman' is English-only; asking for it in Russian is a caller bug.
    request = make_speech_request(persona_id="showman", language=Language.RU)

    # Act
    result = prepare_speech(
        request,
        registry=default_registry(),
        provider=PROVIDER,
        supported_languages=ALL_LANGUAGES,
    )

    # Assert
    assert is_err(result)


def test_warns_but_still_prepares_when_the_name_is_missing_from_the_script(
    caplog: pytest.LogCaptureFixture,
) -> None:
    # Arrange
    request = make_speech_request(text="Happy birthday to you!", name_submitted="Gulomjon")

    # Act
    with caplog.at_level(logging.WARNING):
        result = prepare_speech(
            request,
            registry=default_registry(),
            provider=PROVIDER,
            supported_languages=ALL_LANGUAGES,
        )

    # Assert — a greeting still ships, but the defect is loud in the log.
    assert is_ok(result)
    assert not result.value.is_name_applied
    assert "could not be located" in caplog.text


def test_spoken_text_drops_markup_so_estimates_are_not_inflated() -> None:
    # Arrange
    request = make_speech_request(
        text="[excited] Happy birthday, {name}!", name_submitted="Gulomjon"
    )

    # Act
    result = prepare_speech(
        request,
        registry=default_registry(),
        provider=PROVIDER,
        supported_languages=ALL_LANGUAGES,
    )

    # Assert
    assert is_ok(result)
    assert result.value.spoken_text == "Happy birthday, Gulomjon!"
