"""Intake normalisation: cleaning, fact extraction, artist stripping, moderation."""

from __future__ import annotations

import json

import pytest

from bayram.contracts import MAX_RECIPIENT_NAME_CHARS, Err, Language, Ok, Result, err
from bayram.errors import ErrorCode, ProviderUnavailableError
from bayram.providers.llm.intake import build_intake_request, map_intake_payload, normalise_intake
from bayram.providers.llm.schemas import IntakeDraft, IntakePayload
from bayram.providers.llm.task_settings import LlmTaskSettings
from tests.conftest import UZBEK_NAME_CANONICAL, UZBEK_NAME_TYPED
from tests.test_providers_llm.conftest import StubLlmProvider, intake_payload_dict

PROVIDER = "stub-llm"


def mapped(**overrides: object) -> Ok[IntakeDraft] | Err:
    payload = IntakePayload.model_validate(intake_payload_dict(**overrides))
    return map_intake_payload(payload, raw_name=UZBEK_NAME_TYPED, provider_name=PROVIDER)


async def run(
    response: Result[IntakePayload] | str, settings: LlmTaskSettings
) -> Ok[IntakeDraft] | Err:
    provider = StubLlmProvider([response])
    return await normalise_intake(
        provider,
        raw_name=UZBEK_NAME_TYPED,
        raw_note="He loves mountains",
        ui_language=Language.RU,
        output_language=Language.UZ_LATN,
        settings=settings,
    )


# ---------------------------------------------------------------------------
# End to end
# ---------------------------------------------------------------------------
async def test_returns_a_cleaned_draft_from_a_well_formed_answer(
    task_settings: LlmTaskSettings,
) -> None:
    # Arrange
    raw = json.dumps(intake_payload_dict(), ensure_ascii=False)

    # Act
    result = await run(raw, task_settings)

    # Assert
    assert isinstance(result, Ok)
    assert result.value.display_name == UZBEK_NAME_CANONICAL
    assert result.value.detected_language is Language.UZ_LATN
    assert len(result.value.facts) == 2


async def test_refuses_to_call_the_model_for_a_blank_name(
    task_settings: LlmTaskSettings,
) -> None:
    provider = StubLlmProvider([])
    result = await normalise_intake(
        provider,
        raw_name="   ",
        raw_note="",
        ui_language=Language.EN,
        output_language=Language.EN,
        settings=task_settings,
    )

    assert isinstance(result, Err)
    assert provider.call_count == 0


async def test_passes_a_provider_failure_straight_through(
    task_settings: LlmTaskSettings,
) -> None:
    result = await run(err(ProviderUnavailableError("down", provider=PROVIDER)), task_settings)

    assert isinstance(result, Err)
    assert result.error.error_code is ErrorCode.UPSTREAM_5XX


# ---------------------------------------------------------------------------
# Moderation
# ---------------------------------------------------------------------------
def test_an_unsafe_brief_becomes_a_terminal_moderation_rejection() -> None:
    result = mapped(is_safe=False, rejection_reason="targets the recipient with slurs")

    assert isinstance(result, Err)
    assert result.error.error_code is ErrorCode.CONTENT_REJECTED
    assert result.error.is_retryable is False
    assert result.error.user_message_key == "error.content_not_allowed"


def test_an_unsafe_brief_without_a_stated_reason_still_produces_a_usable_error() -> None:
    result = mapped(is_safe=False, rejection_reason="")

    assert isinstance(result, Err)
    assert "unspecified" in result.error.operator_message


# ---------------------------------------------------------------------------
# Cleaning and coercion
# ---------------------------------------------------------------------------
def test_an_over_long_display_name_is_clipped_to_the_contract_bound() -> None:
    result = mapped(display_name="Abdurahmon " * 12)

    assert isinstance(result, Ok)
    assert len(result.value.display_name) <= MAX_RECIPIENT_NAME_CHARS


def test_an_unrecognised_language_label_becomes_none_rather_than_a_guess() -> None:
    result = mapped(detected_language="klingon")

    assert isinstance(result, Ok)
    assert result.value.detected_language is None


def test_blank_facts_are_dropped_and_the_list_is_bounded() -> None:
    result = mapped(facts=["one", "  ", "", "two", "three", "four", "five", "six"])

    assert isinstance(result, Ok)
    assert "" not in result.value.facts
    assert len(result.value.facts) <= 5


def test_stripped_artist_terms_are_carried_forward_for_the_music_payload() -> None:
    # A real band name in a note is a documented provider rejection, so it must be
    # visible to the caller, not silently deleted.
    result = mapped(removed_artist_terms=["Yalla", "Sevara Nazarkhan"])

    assert isinstance(result, Ok)
    assert result.value.removed_artist_terms == ("Yalla", "Sevara Nazarkhan")


def test_an_over_long_cleaned_note_is_clipped_to_the_brief_bound() -> None:
    result = mapped(cleaned_note="word " * 400)

    assert isinstance(result, Ok)
    assert len(result.value.cleaned_note) <= 600


# ---------------------------------------------------------------------------
# Prompt construction
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("language", list(Language))
def test_the_intake_prompt_renders_for_every_supported_language(
    language: Language, task_settings: LlmTaskSettings
) -> None:
    request = build_intake_request(
        raw_name=UZBEK_NAME_TYPED,
        raw_note="loves plov",
        ui_language=Language.EN,
        output_language=language,
        settings=task_settings,
    )

    assert "{{" not in request.system_prompt
    assert "{{" not in request.user_prompt
    assert language.value in request.user_prompt


def test_the_intake_prompt_carries_the_raw_typed_name_verbatim(
    task_settings: LlmTaskSettings,
) -> None:
    request = build_intake_request(
        raw_name=UZBEK_NAME_TYPED,
        raw_note="",
        ui_language=Language.UZ_LATN,
        output_language=Language.UZ_LATN,
        settings=task_settings,
    )

    assert UZBEK_NAME_TYPED in request.user_prompt
    assert "no note" in request.user_prompt


def test_a_whitespace_only_name_from_both_sides_is_a_typed_error() -> None:
    payload = IntakePayload.model_validate(intake_payload_dict(display_name=" "))

    result = map_intake_payload(payload, raw_name="   ", provider_name=PROVIDER)

    assert isinstance(result, Err)
    assert result.error.error_code is ErrorCode.PARSE_FAILED


def test_a_blank_display_name_falls_back_to_the_name_the_buyer_typed() -> None:
    payload = IntakePayload.model_validate(intake_payload_dict(display_name=" "))

    result = map_intake_payload(payload, raw_name=UZBEK_NAME_TYPED, provider_name=PROVIDER)

    assert isinstance(result, Ok)
    assert result.value.display_name == UZBEK_NAME_TYPED
