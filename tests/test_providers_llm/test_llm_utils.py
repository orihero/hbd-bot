"""The small shared helpers. Pure functions, so the tests are pure too."""

from __future__ import annotations

from datetime import UTC

import pytest

from hbd.contracts import HealthState
from hbd.errors import ProviderQuotaExhaustedError, ProviderTimeoutError
from hbd.providers.llm.schemas import NameRespellingPayload
from hbd.providers.llm.task_settings import LlmTaskSettings
from hbd.providers.llm.utils import clip, health_state_for, utc_now


def test_utc_now_is_timezone_aware() -> None:
    assert utc_now().tzinfo is UTC


def test_a_retryable_failure_reads_as_degraded_not_unavailable() -> None:
    assert health_state_for(ProviderTimeoutError("slow")) is HealthState.DEGRADED


def test_a_terminal_failure_reads_as_unavailable() -> None:
    assert health_state_for(ProviderQuotaExhaustedError("broke")) is HealthState.UNAVAILABLE


def test_clip_returns_short_text_unchanged_but_stripped() -> None:
    assert clip("  hello  ", 40) == "hello"


def test_clip_cuts_on_a_word_boundary_when_one_is_close_enough() -> None:
    result = clip("one two three four five six seven", 20)

    assert len(result) <= 20
    assert not result.endswith(" ")
    assert " " in result
    assert result == "one two three four"


def test_clip_hard_cuts_a_single_long_word_rather_than_returning_nothing() -> None:
    result = clip("a" * 100, 10)

    assert result == "a" * 10


def test_clip_of_an_empty_string_is_empty() -> None:
    assert clip("   ", 10) == ""


def test_task_settings_are_frozen(settings_slice: LlmTaskSettings) -> None:
    with pytest.raises(AttributeError):
        settings_slice.llm_temperature = 1.0  # type: ignore[misc]


def test_task_settings_copy_every_value_from_settings() -> None:
    from hbd.config import Settings

    full = Settings(
        _env_file=None,
        telegram_bot_token="t",
        database_url="postgresql+asyncpg://x/y",
        elevenlabs_api_key="e",
        llm_api_key="l",
        llm_temperature=0.3,
        name_chunk_duration_ms=9_000,
    )

    slice_ = LlmTaskSettings.from_settings(full)

    assert slice_.llm_temperature == pytest.approx(0.3)
    assert slice_.name_chunk_duration_ms == 9_000
    assert slice_.greeting_max_duration_s == pytest.approx(full.greeting_max_duration_s)


@pytest.fixture
def settings_slice() -> LlmTaskSettings:
    return LlmTaskSettings(
        llm_temperature=0.7,
        llm_max_output_tokens=2_048,
        llm_timeout_s=45.0,
        llm_parse_max_attempts=2,
        name_chunk_duration_ms=8_000,
        greeting_min_duration_s=20.0,
        greeting_max_duration_s=45.0,
    )


@pytest.mark.parametrize("value", ["very confident", None, [], {}])
def test_a_non_numeric_confidence_falls_back_to_a_neutral_score(value: object) -> None:
    payload = NameRespellingPayload.model_validate({"text": "Gulomjon", "confidence": value})

    assert payload.confidence == pytest.approx(0.5)


def test_a_confidence_written_as_a_string_is_still_read_as_a_number() -> None:
    payload = NameRespellingPayload.model_validate({"text": "Gulomjon", "confidence": "0.42"})

    assert payload.confidence == pytest.approx(0.42)
