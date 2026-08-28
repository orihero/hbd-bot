"""Three greetings must sound like three different people, and a thin catalogue must not fail."""

from __future__ import annotations

from hbd.contracts import Language, VoiceDescriptor, VoiceGender
from hbd.pipeline.personas import select_voices
from tests.test_pipeline.conftest import failure_of, value_of


def _voice(
    persona_id: str, gender: VoiceGender, language: Language = Language.UZ_LATN
) -> VoiceDescriptor:
    return VoiceDescriptor(persona_id=persona_id, language=language, gender=gender)


CATALOGUE = (
    _voice("uz-f1", VoiceGender.FEMALE),
    _voice("uz-f2", VoiceGender.FEMALE),
    _voice("uz-m1", VoiceGender.MALE),
    _voice("uz-m2", VoiceGender.MALE),
    _voice("ru-f1", VoiceGender.FEMALE, Language.RU),
)


def test_alternates_genders_so_the_characters_differ() -> None:
    # Arrange / Act
    chosen = value_of(
        select_voices(
            CATALOGUE,
            language=Language.UZ_LATN,
            preferred_gender=VoiceGender.FEMALE,
            count=3,
        )
    )

    # Assert
    assert [voice.persona_id for voice in chosen] == ["uz-f1", "uz-m1", "uz-f2"]


def test_leads_with_the_requested_gender() -> None:
    # Arrange / Act
    chosen = value_of(
        select_voices(
            CATALOGUE, language=Language.UZ_LATN, preferred_gender=VoiceGender.MALE, count=2
        )
    )

    # Assert
    assert chosen[0].gender is VoiceGender.MALE


def test_never_crosses_the_output_language() -> None:
    # Arrange / Act
    chosen = value_of(
        select_voices(CATALOGUE, language=Language.RU, preferred_gender=VoiceGender.ANY, count=3)
    )

    # Assert
    assert [voice.persona_id for voice in chosen] == ["ru-f1"]


def test_returns_fewer_voices_rather_than_failing_on_a_thin_catalogue() -> None:
    # Arrange
    thin = (_voice("uz-f1", VoiceGender.FEMALE),)

    # Act
    chosen = value_of(
        select_voices(thin, language=Language.UZ_LATN, preferred_gender=VoiceGender.MALE, count=3)
    )

    # Assert
    assert len(chosen) == 1


def test_fails_when_the_language_has_no_voice_at_all() -> None:
    # Arrange / Act
    result = select_voices(
        CATALOGUE, language=Language.EN, preferred_gender=VoiceGender.ANY, count=3
    )

    # Assert
    assert failure_of(result).user_message_key == "error.service_unavailable"
