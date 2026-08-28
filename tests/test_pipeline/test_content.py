"""The second parse boundary: valid JSON that is still unusable must be repaired or refused."""

from __future__ import annotations

from hbd.config import Settings
from hbd.contracts import (
    Brief,
    Err,
    Language,
    Result,
    SpokenScript,
    VoiceDescriptor,
    VoiceGender,
)
from hbd.errors import ErrorCode, ProviderTimeoutError
from hbd.pipeline.content import (
    GreetingPayload,
    GreetingsPayload,
    LlmContentWriter,
    LyricSectionPayload,
    LyricsPayload,
)
from tests.conftest import UZBEK_NAME_CANONICAL, make_brief
from tests.test_pipeline.conftest import FakeLlmProvider, failure_of, value_of

VOICES = (
    VoiceDescriptor(persona_id="bobo", language=Language.UZ_LATN, gender=VoiceGender.MALE),
    VoiceDescriptor(persona_id="opa", language=Language.UZ_LATN, gender=VoiceGender.FEMALE),
)


def _writer(llm: FakeLlmProvider, settings: Settings) -> LlmContentWriter:
    return LlmContentWriter(llm, settings)


async def test_writes_lyrics_with_exactly_one_name_hook(settings: Settings) -> None:
    # Arrange
    llm = FakeLlmProvider()

    # Act
    draft = value_of(await _writer(llm, settings).write_lyrics(make_brief()))

    # Assert
    assert len(draft.name_hook_sections) == 1
    assert draft.name_display == UZBEK_NAME_CANONICAL
    assert draft.language is Language.UZ_LATN


async def test_flags_the_section_that_mentions_the_name_when_the_model_flagged_none(
    settings: Settings,
) -> None:
    # Arrange
    llm = FakeLlmProvider()
    llm.respond_with(
        "LyricsPayload",
        LyricsPayload(
            title="Bayram",
            sections=(
                LyricSectionPayload(label="verse", lines=("quyosh porlaydi",)),
                LyricSectionPayload(label="hook", lines=(UZBEK_NAME_CANONICAL,)),
            ),
        ),
    )

    # Act
    draft = value_of(await _writer(llm, settings).write_lyrics(make_brief()))

    # Assert
    hook = draft.name_hook_sections[0]
    assert hook.label == "hook"


async def test_forces_the_name_into_a_hook_that_forgot_it(settings: Settings) -> None:
    # Arrange
    llm = FakeLlmProvider()
    llm.respond_with(
        "LyricsPayload",
        LyricsPayload(
            title="Bayram",
            sections=(
                LyricSectionPayload(label="hook", lines=("bayram muborak",), is_name_hook=True),
            ),
        ),
    )

    # Act
    draft = value_of(await _writer(llm, settings).write_lyrics(make_brief()))

    # Assert
    assert UZBEK_NAME_CANONICAL in draft.name_hook_sections[0].lines


async def test_rejects_a_lyric_payload_with_no_usable_section(settings: Settings) -> None:
    # Arrange
    llm = FakeLlmProvider()
    llm.respond_with(
        "LyricsPayload",
        LyricsPayload(
            title="Bayram",
            sections=(LyricSectionPayload(label="verse", lines=("   ", "")),),
        ),
    )

    # Act
    result = await _writer(llm, settings).write_lyrics(make_brief())

    # Assert
    assert failure_of(result).error_code is ErrorCode.PARSE_FAILED


async def test_passes_a_transport_failure_straight_through(settings: Settings) -> None:
    # Arrange
    llm = FakeLlmProvider()
    llm.fail_next("LyricsPayload", ProviderTimeoutError("gemini timed out", provider="fake"))

    # Act
    result = await _writer(llm, settings).write_lyrics(make_brief())

    # Assert
    assert failure_of(result).error_code is ErrorCode.UPSTREAM_TIMEOUT


async def _scripts(
    llm: FakeLlmProvider, settings: Settings, brief: Brief | None = None
) -> Result[tuple[SpokenScript, ...]]:
    writer = _writer(llm, settings)
    resolved = brief or make_brief()
    lyrics = value_of(await writer.write_lyrics(resolved))
    return await writer.write_scripts(
        resolved,
        lyrics,
        voices=VOICES,
        name_submitted="Gulomjon",
        target_duration_s=30.0,
    )


async def test_writes_one_script_per_voice_using_the_submitted_orthography(
    settings: Settings,
) -> None:
    # Arrange
    llm = FakeLlmProvider()

    # Act
    scripts = value_of(await _scripts(llm, settings))

    # Assert
    assert [script.persona_id for script in scripts] == ["bobo", "opa"]
    assert all(script.name_submitted == "Gulomjon" for script in scripts)
    assert all(UZBEK_NAME_CANONICAL in script.text for script in scripts)


async def test_rejects_a_short_greeting_payload(settings: Settings) -> None:
    # Arrange
    llm = FakeLlmProvider()
    llm.respond_with(
        "GreetingsPayload",
        GreetingsPayload(greetings=(GreetingPayload(persona_id="bobo", text="salom"),)),
    )

    # Act
    result = await _scripts(llm, settings)

    # Assert
    error = failure_of(result)
    assert error.error_code is ErrorCode.PARSE_FAILED
    assert error.context["requested"] == 2


async def test_reassigns_a_persona_the_provider_has_never_heard_of(
    settings: Settings,
) -> None:
    # Arrange
    llm = FakeLlmProvider()
    llm.respond_with(
        "GreetingsPayload",
        GreetingsPayload(
            greetings=(
                GreetingPayload(persona_id="an-invented-voice", text="salom Gʻulomjon"),
                GreetingPayload(persona_id="opa", text="salom Gʻulomjon"),
            )
        ),
    )

    # Act
    scripts = value_of(await _scripts(llm, settings))

    # Assert
    assert scripts[0].persona_id == "bobo"


async def test_prepends_the_name_to_a_greeting_that_omitted_it(settings: Settings) -> None:
    # Arrange
    llm = FakeLlmProvider()
    llm.respond_with(
        "GreetingsPayload",
        GreetingsPayload(
            greetings=(
                GreetingPayload(persona_id="bobo", text="bayram muborak"),
                GreetingPayload(persona_id="opa", text="bayram muborak"),
            )
        ),
    )

    # Act
    scripts = value_of(await _scripts(llm, settings))

    # Assert
    assert scripts[0].text.startswith(f"{UZBEK_NAME_CANONICAL}!")


async def test_refuses_to_write_greetings_without_a_voice(settings: Settings) -> None:
    # Arrange
    llm = FakeLlmProvider()
    writer = _writer(llm, settings)
    brief = make_brief()
    lyrics = value_of(await writer.write_lyrics(brief))

    # Act
    result = await writer.write_scripts(
        brief, lyrics, voices=(), name_submitted="Gulomjon", target_duration_s=30.0
    )

    # Assert
    assert isinstance(result, Err)
