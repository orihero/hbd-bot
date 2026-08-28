"""The one call that writes a whole kit, and the mapping that makes it safe to use.

The load-bearing assertion in this file is the name-hook rule: exactly one section, one
line, and that line returned separately so the music provider can isolate it in its own
chunk. If that ever regresses, the product's differentiator regresses with it.
"""

from __future__ import annotations

import pytest

from hbd.contracts import Err, Language, NameStrategy, Ok, err
from hbd.errors import ErrorCode, ProviderTimeoutError
from hbd.providers.llm.schemas import KitDraft, KitPlanPayload, PersonaBrief
from hbd.providers.llm.task_settings import LlmTaskSettings
from hbd.providers.llm.writer import build_kit_request, map_kit_payload, write_kit
from tests.conftest import UZBEK_NAME_CANONICAL, make_brief, make_name
from tests.test_providers_llm.conftest import (
    StubLlmProvider,
    kit_payload_dict,
    kit_payload_json,
)

PROVIDER = "stub-llm"


def payload(**overrides: object) -> KitPlanPayload:
    return KitPlanPayload.model_validate(kit_payload_dict(**overrides))


def mapped(
    personas: tuple[PersonaBrief, ...],
    settings: LlmTaskSettings,
    **overrides: object,
) -> Ok[KitDraft] | Err:
    return map_kit_payload(
        payload(**overrides), make_brief(), personas, settings, provider_name=PROVIDER
    )


# ---------------------------------------------------------------------------
# End to end through a stubbed provider
# ---------------------------------------------------------------------------
async def test_produces_lyrics_scripts_and_respellings_from_one_call(
    personas: tuple[PersonaBrief, ...], task_settings: LlmTaskSettings
) -> None:
    # Arrange
    provider = StubLlmProvider([kit_payload_json()])

    # Act
    result = await write_kit(provider, make_brief(), personas, task_settings)

    # Assert
    assert isinstance(result, Ok)
    assert provider.call_count == 1
    assert result.value.lyrics.title
    assert len(result.value.scripts) == len(personas)
    assert result.value.respellings


async def test_refuses_to_call_the_model_when_no_persona_was_requested(
    task_settings: LlmTaskSettings,
) -> None:
    provider = StubLlmProvider([])

    result = await write_kit(provider, make_brief(), (), task_settings)

    assert isinstance(result, Err)
    assert provider.call_count == 0


async def test_passes_a_provider_failure_straight_through(
    personas: tuple[PersonaBrief, ...], task_settings: LlmTaskSettings
) -> None:
    provider = StubLlmProvider([err(ProviderTimeoutError("too slow", provider=PROVIDER))])

    result = await write_kit(provider, make_brief(), personas, task_settings)

    assert isinstance(result, Err)
    assert result.error.error_code is ErrorCode.UPSTREAM_TIMEOUT


# ---------------------------------------------------------------------------
# The name-hook rule
# ---------------------------------------------------------------------------
def test_the_name_line_is_returned_separately_for_the_music_chunk(
    personas: tuple[PersonaBrief, ...], task_settings: LlmTaskSettings
) -> None:
    result = mapped(personas, task_settings)

    assert isinstance(result, Ok)
    assert result.value.name_line == UZBEK_NAME_CANONICAL


def test_exactly_one_section_is_flagged_as_the_name_hook(
    personas: tuple[PersonaBrief, ...], task_settings: LlmTaskSettings
) -> None:
    # Arrange: a model that flagged three hooks, which the plan builder cannot accept.
    sections = [
        {"label": "verse-1", "lines": ["one"], "is_name_hook": True},
        {"label": "hook", "lines": ["Gʻulomjon"], "is_name_hook": True},
        {"label": "chorus", "lines": ["three"], "is_name_hook": True},
    ]

    result = mapped(personas, task_settings, sections=sections)

    assert isinstance(result, Ok)
    assert len(result.value.lyrics.name_hook_sections) == 1


def test_the_hook_section_holds_exactly_the_name_line_and_nothing_else(
    personas: tuple[PersonaBrief, ...], task_settings: LlmTaskSettings
) -> None:
    # Arrange: a model that crammed four lines into the hook.
    sections = [
        {"label": "verse-1", "lines": ["one"]},
        {
            "label": "hook",
            "lines": ["Gʻulomjon", "and some more", "and more", "and more"],
            "is_name_hook": True,
        },
    ]

    result = mapped(personas, task_settings, sections=sections)

    assert isinstance(result, Ok)
    hook = result.value.lyrics.name_hook_sections[0]
    assert hook.lines == (UZBEK_NAME_CANONICAL,)


def test_non_hook_sections_keep_the_lines_the_model_wrote(
    personas: tuple[PersonaBrief, ...], task_settings: LlmTaskSettings
) -> None:
    result = mapped(personas, task_settings)

    assert isinstance(result, Ok)
    verse = result.value.lyrics.sections[0]
    assert verse.lines == ("Bugun quyosh boshqacha porlaydi",)


def test_a_payload_with_no_name_hook_at_all_fails_validation() -> None:
    # The schema refuses it, so it never reaches the mapper.
    sections = [
        {"label": "verse-1", "lines": ["one"]},
        {"label": "chorus", "lines": ["two"]},
    ]

    with pytest.raises(ValueError, match="is_name_hook"):
        payload(sections=sections)


def test_a_blank_name_line_is_a_typed_error(
    personas: tuple[PersonaBrief, ...], task_settings: LlmTaskSettings
) -> None:
    result = mapped(personas, task_settings, name_line="   ")

    assert isinstance(result, Err)
    assert result.error.error_code is ErrorCode.PARSE_FAILED


# ---------------------------------------------------------------------------
# Display vs submitted orthography — never conflated
# ---------------------------------------------------------------------------
def test_the_lyric_sheet_carries_the_display_name_not_a_respelling(
    personas: tuple[PersonaBrief, ...], task_settings: LlmTaskSettings
) -> None:
    result = mapped(personas, task_settings)

    assert isinstance(result, Ok)
    assert result.value.lyrics.name_display == UZBEK_NAME_CANONICAL


def test_each_script_submits_the_top_ranked_candidate_not_the_display_form(
    personas: tuple[PersonaBrief, ...], task_settings: LlmTaskSettings
) -> None:
    brief = make_brief()
    expected = brief.recipient.candidates[0].text

    result = map_kit_payload(payload(), brief, personas, task_settings, provider_name=PROVIDER)

    assert isinstance(result, Ok)
    assert expected != brief.recipient.display
    assert all(script.name_submitted == expected for script in result.value.scripts)


# ---------------------------------------------------------------------------
# Spoken scripts
# ---------------------------------------------------------------------------
def test_scripts_are_ordered_by_the_requested_personas_not_the_model_order(
    personas: tuple[PersonaBrief, ...], task_settings: LlmTaskSettings
) -> None:
    # Arrange: the model answered in the wrong order but echoed the ids correctly.
    scripts = list(reversed(kit_payload_dict()["spoken_scripts"]))

    result = mapped(personas, task_settings, spoken_scripts=scripts)

    assert isinstance(result, Ok)
    assert [script.persona_id for script in result.value.scripts] == [
        persona.persona_id for persona in personas
    ]
    assert result.value.scripts[0].text == "Assalomu alaykum, Gʻulomjon!"


def test_scripts_fall_back_to_positional_order_when_the_ids_were_not_echoed(
    personas: tuple[PersonaBrief, ...], task_settings: LlmTaskSettings
) -> None:
    scripts = [{**item, "persona_id": ""} for item in kit_payload_dict()["spoken_scripts"]]

    result = mapped(personas, task_settings, spoken_scripts=scripts)

    assert isinstance(result, Ok)
    assert [script.persona_id for script in result.value.scripts] == [
        persona.persona_id for persona in personas
    ]
    assert result.value.scripts[0].text == "Assalomu alaykum, Gʻulomjon!"


def test_too_few_scripts_is_a_typed_error(
    personas: tuple[PersonaBrief, ...], task_settings: LlmTaskSettings
) -> None:
    result = mapped(
        personas, task_settings, spoken_scripts=kit_payload_dict()["spoken_scripts"][:1]
    )

    assert isinstance(result, Err)
    assert result.error.error_code is ErrorCode.PARSE_FAILED


@pytest.mark.parametrize(("reported", "expected"), [(3.0, 20.0), (500.0, 45.0), (30.0, 30.0)])
def test_target_duration_is_clamped_into_the_configured_greeting_window(
    reported: float,
    expected: float,
    personas: tuple[PersonaBrief, ...],
    task_settings: LlmTaskSettings,
) -> None:
    scripts = [
        {**item, "target_duration_s": reported} for item in kit_payload_dict()["spoken_scripts"]
    ]

    result = mapped(personas, task_settings, spoken_scripts=scripts)

    assert isinstance(result, Ok)
    assert result.value.scripts[0].target_duration_s == pytest.approx(expected)


def test_a_script_longer_than_the_contract_allows_is_clipped_not_rejected(
    personas: tuple[PersonaBrief, ...], task_settings: LlmTaskSettings
) -> None:
    scripts = [{**item, "text": "word " * 800} for item in kit_payload_dict()["spoken_scripts"]]

    result = mapped(personas, task_settings, spoken_scripts=scripts)

    assert isinstance(result, Ok)
    assert len(result.value.scripts[0].text) <= 2_000


def test_a_title_longer_than_the_contract_allows_is_clipped_not_rejected(
    personas: tuple[PersonaBrief, ...], task_settings: LlmTaskSettings
) -> None:
    result = mapped(personas, task_settings, title="Tugʻilgan kun " * 40)

    assert isinstance(result, Ok)
    assert len(result.value.lyrics.title) <= 120


# ---------------------------------------------------------------------------
# Name respellings
# ---------------------------------------------------------------------------
def test_respellings_become_ranked_candidates_in_the_returned_order(
    personas: tuple[PersonaBrief, ...], task_settings: LlmTaskSettings
) -> None:
    result = mapped(personas, task_settings)

    assert isinstance(result, Ok)
    candidates = result.value.candidates()
    assert [candidate.rank for candidate in candidates] == list(range(len(candidates)))
    assert candidates[0].strategy is NameStrategy.STRIPPED


def test_an_unknown_strategy_label_degrades_to_phonetic_rather_than_failing(
    personas: tuple[PersonaBrief, ...], task_settings: LlmTaskSettings
) -> None:
    respellings = [{"text": "Ghoolomjon", "strategy": "vibes-based", "confidence": 0.4}]

    result = mapped(personas, task_settings, name_respellings=respellings)

    assert isinstance(result, Ok)
    assert result.value.respellings[0].strategy is NameStrategy.PHONETIC


def test_a_confidence_outside_the_unit_interval_is_clamped(
    personas: tuple[PersonaBrief, ...], task_settings: LlmTaskSettings
) -> None:
    respellings = [
        {"text": "Gulomjon", "strategy": "stripped", "confidence": 9.5},
        {"text": "Ghoolomjon", "strategy": "phonetic", "confidence": -2},
    ]

    result = mapped(personas, task_settings, name_respellings=respellings)

    assert isinstance(result, Ok)
    assert result.value.respellings[0].confidence == pytest.approx(1.0)
    assert result.value.respellings[1].confidence == pytest.approx(0.0)


def test_duplicate_and_oversized_respellings_are_dropped(
    personas: tuple[PersonaBrief, ...], task_settings: LlmTaskSettings
) -> None:
    respellings = [
        {"text": "Gulomjon", "strategy": "stripped", "confidence": 0.9},
        {"text": "Gulomjon", "strategy": "phonetic", "confidence": 0.8},
        {"text": "G" * 200, "strategy": "phonetic", "confidence": 0.1},
    ]

    result = mapped(personas, task_settings, name_respellings=respellings)

    assert isinstance(result, Ok)
    assert len(result.value.respellings) == 1


def test_no_usable_respelling_is_a_typed_error(
    personas: tuple[PersonaBrief, ...], task_settings: LlmTaskSettings
) -> None:
    respellings = [{"text": "G" * 200, "strategy": "phonetic", "confidence": 0.1}]

    result = mapped(personas, task_settings, name_respellings=respellings)

    assert isinstance(result, Err)


def test_an_empty_ipa_string_becomes_none_rather_than_a_blank(
    personas: tuple[PersonaBrief, ...], task_settings: LlmTaskSettings
) -> None:
    respellings = [{"text": "Gulomjon", "strategy": "stripped", "ipa": "  ", "confidence": 0.9}]

    result = mapped(personas, task_settings, name_respellings=respellings)

    assert isinstance(result, Ok)
    assert result.value.respellings[0].ipa is None


# ---------------------------------------------------------------------------
# Prompt construction
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("language", list(Language))
def test_the_prompt_carries_the_language_guide_for_every_supported_language(
    language: Language, personas: tuple[PersonaBrief, ...], task_settings: LlmTaskSettings
) -> None:
    brief = make_brief(output_language=language, recipient=make_name(language=language))

    request = build_kit_request(brief, personas, task_settings)

    assert language.value in request.user_prompt
    assert len(request.system_prompt) > len(request.user_prompt)


def test_the_prompt_names_every_persona_in_order(
    personas: tuple[PersonaBrief, ...], task_settings: LlmTaskSettings
) -> None:
    request = build_kit_request(make_brief(), personas, task_settings)

    positions = [request.user_prompt.index(persona.persona_id) for persona in personas]
    assert positions == sorted(positions)


def test_the_prompt_states_the_display_spelling_and_the_name_chunk_length(
    personas: tuple[PersonaBrief, ...], task_settings: LlmTaskSettings
) -> None:
    request = build_kit_request(make_brief(), personas, task_settings)

    assert UZBEK_NAME_CANONICAL in request.system_prompt
    assert "8 seconds" in request.system_prompt


def test_an_empty_note_still_renders_a_complete_prompt(
    personas: tuple[PersonaBrief, ...], task_settings: LlmTaskSettings
) -> None:
    request = build_kit_request(make_brief(note=""), personas, task_settings)

    assert "{{" not in request.user_prompt
    assert "no note" in request.user_prompt


def test_generation_settings_come_from_the_task_settings(
    personas: tuple[PersonaBrief, ...], task_settings: LlmTaskSettings
) -> None:
    request = build_kit_request(make_brief(), personas, task_settings)

    assert request.temperature == pytest.approx(task_settings.llm_temperature)
    assert request.max_output_tokens == task_settings.llm_max_output_tokens


def test_a_draft_the_domain_contract_rejects_is_a_typed_error_not_a_crash(
    personas: tuple[PersonaBrief, ...], task_settings: LlmTaskSettings
) -> None:
    # A whitespace label passes the payload schema and then fails LyricSection's bound.
    sections = [
        {"label": "   ", "lines": ["one"]},
        {"label": "hook", "lines": ["Gʻulomjon"], "is_name_hook": True},
    ]

    result = mapped(personas, task_settings, sections=sections)

    assert isinstance(result, Err)
    assert result.error.error_code is ErrorCode.PARSE_FAILED
