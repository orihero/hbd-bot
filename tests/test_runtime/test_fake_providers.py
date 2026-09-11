"""The offline stand-ins: they must satisfy the protocols and answer usefully.

A fake that returns something the real pipeline cannot use is worse than no fake at all —
it turns a demo into a debugging session and, worse, lets a wiring bug hide behind a
plausible-looking failure. So these tests check the two things that actually matter: the
protocol is satisfied structurally, and what comes back is the shape the next stage needs.
"""

from __future__ import annotations

import pytest
from pydantic import BaseModel

from bayram.contracts import (
    Err,
    Language,
    LlmProvider,
    LlmRequest,
    Ok,
    SttProvider,
)
from bayram.errors import ErrorCode
from bayram.pipeline.content import GreetingsPayload, LyricsPayload
from bayram.pipeline.moderation import ModerationPayload
from bayram.providers.llm.fake import FakeLlmProvider
from bayram.runtime.fakes import MISHEARD_TRANSCRIPT, KeytermSttProvider

LYRICS_PROMPT = (
    'The recipient is named "Gʻulomjon".\n'
    "Language of the lyrics: Uzbek written in the Latin alphabet.\n"
)
GREETINGS_PROMPT = (
    'The recipient is named "Gʻulomjon".\n'
    "Language of the lyrics: Uzbek written in the Latin alphabet.\n"
    'Characters:\n- persona_id "bobo" (voice gender: male)\n'
    '- persona_id "opa" (voice gender: female)\n'
)


def _request(user_prompt: str) -> LlmRequest:
    return LlmRequest(system_prompt="you write songs", user_prompt=user_prompt)


# ---------------------------------------------------------------------------
# FakeLlmProvider
# ---------------------------------------------------------------------------
def test_the_fake_llm_satisfies_the_protocol() -> None:
    assert isinstance(FakeLlmProvider(), LlmProvider)


async def test_it_writes_a_lyric_with_exactly_one_name_hook_carrying_the_name() -> None:
    # Arrange
    provider = FakeLlmProvider()

    # Act
    result = await provider.generate_json(_request(LYRICS_PROMPT), LyricsPayload, timeout_s=1.0)

    # Assert
    assert isinstance(result, Ok)
    hooks = [section for section in result.value.sections if section.is_name_hook]
    assert len(hooks) == 1
    assert hooks[0].lines == ("Gʻulomjon",)


async def test_it_writes_one_greeting_per_persona_named_in_the_prompt() -> None:
    # Arrange
    provider = FakeLlmProvider()

    # Act
    result = await provider.generate_json(
        _request(GREETINGS_PROMPT), GreetingsPayload, timeout_s=1.0
    )

    # Assert
    assert isinstance(result, Ok)
    assert [greeting.persona_id for greeting in result.value.greetings] == ["bobo", "opa"]
    assert all("Gʻulomjon" in greeting.text for greeting in result.value.greetings)


@pytest.mark.parametrize(
    ("marker", "expected_fragment"),
    [
        ("Uzbek written in the Latin alphabet", "Tugʻilgan"),
        ("Uzbek written in the Cyrillic alphabet", "Туғилган"),
        ("Russian", "рождения"),
        ("English", "Happy"),
    ],
)
async def test_the_lyric_language_follows_the_brief(marker: str, expected_fragment: str) -> None:
    # Arrange
    provider = FakeLlmProvider()
    prompt = f'The recipient is named "Anna".\nLanguage of the lyrics: {marker}.\n'

    # Act
    result = await provider.generate_json(_request(prompt), LyricsPayload, timeout_s=1.0)

    # Assert
    assert isinstance(result, Ok)
    assert expected_fragment in result.value.title


async def test_it_allows_content_when_asked_for_a_moderation_verdict() -> None:
    # Arrange
    provider = FakeLlmProvider()

    # Act
    result = await provider.generate_json(
        _request('Recipient name: "Anna"'), ModerationPayload, timeout_s=1.0
    )

    # Assert
    assert isinstance(result, Ok)
    assert result.value.is_allowed


async def test_an_unrecognised_response_shape_is_a_typed_error_not_a_raise() -> None:
    # Arrange
    class Unknown(BaseModel):
        nothing_we_know_about: str = ""

    provider = FakeLlmProvider()

    # Act
    result = await provider.generate_json(_request("hello"), Unknown, timeout_s=1.0)

    # Assert
    assert isinstance(result, Err)
    assert result.error.error_code is ErrorCode.PARSE_FAILED


async def test_the_fake_llm_reports_itself_healthy() -> None:
    result = await FakeLlmProvider().health()

    assert isinstance(result, Ok)
    assert result.value.name == FakeLlmProvider.name


# ---------------------------------------------------------------------------
# KeytermSttProvider
# ---------------------------------------------------------------------------
def test_the_keyterm_stt_satisfies_the_protocol() -> None:
    assert isinstance(KeytermSttProvider(), SttProvider)


async def test_it_hears_the_first_keyterm_which_is_the_intended_name() -> None:
    # Arrange
    provider = KeytermSttProvider()

    # Act
    result = await provider.transcribe(
        b"\xff\xfb",
        mime="audio/mpeg",
        language=Language.UZ_LATN,
        keyterms=("Gʻulomjon", "Gulomjon"),
        timeout_s=1.0,
    )

    # Assert
    assert isinstance(result, Ok)
    assert result.value.text == "Gʻulomjon"


async def test_the_first_takes_are_misheard_so_the_re_roll_is_actually_exercised() -> None:
    # Arrange
    provider = KeytermSttProvider(mishear_first=2)

    async def hear() -> str:
        result = await provider.transcribe(
            b"\xff\xfb",
            mime="audio/mpeg",
            language=Language.UZ_LATN,
            keyterms=("Gʻulomjon",),
            timeout_s=1.0,
        )
        assert isinstance(result, Ok)
        return result.value.text

    # Act / Assert
    assert await hear() == MISHEARD_TRANSCRIPT
    assert await hear() == MISHEARD_TRANSCRIPT
    assert await hear() == "Gʻulomjon"


async def test_empty_audio_is_refused_rather_than_transcribed_as_nothing() -> None:
    # Act
    result = await KeytermSttProvider().transcribe(
        b"", mime="audio/mpeg", language=Language.RU, timeout_s=1.0
    )

    # Assert
    assert isinstance(result, Err)
    assert result.error.error_code is ErrorCode.INVALID_INPUT


async def test_blank_keyterms_yield_an_empty_transcript_rather_than_a_crash() -> None:
    # Act
    result = await KeytermSttProvider().transcribe(
        b"\xff\xfb", mime="audio/mpeg", language=Language.EN, keyterms=("", "   "), timeout_s=1.0
    )

    # Assert
    assert isinstance(result, Ok)
    assert result.value.text == ""


def test_a_negative_mishear_count_is_refused_at_construction() -> None:
    with pytest.raises(ValueError, match="mishear_first"):
        KeytermSttProvider(mishear_first=-1)


async def test_the_keyterm_stt_reports_itself_healthy() -> None:
    result = await KeytermSttProvider().health()

    assert isinstance(result, Ok)
    assert result.value.detail is not None
