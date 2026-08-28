"""The persona catalogue: shape, invariants, and the environment override."""

from __future__ import annotations

import json

import pytest

from hbd.contracts import Language, VoiceGender, is_err, is_ok
from hbd.errors import ConfigError
from hbd.providers.tts.registry import (
    DEFAULT_VOICE_ENTRIES,
    VoiceEntry,
    VoiceRegistry,
    default_registry,
    parse_voice_registry,
)

GREETINGS_PER_KIT = 3


def _entry(
    *,
    persona_id: str = "bobo",
    vendor_voice_id: str = "voice-1",
    language: Language = Language.UZ_LATN,
    gender: VoiceGender = VoiceGender.MALE,
    substitute_persona_id: str | None = None,
) -> VoiceEntry:
    return VoiceEntry(
        persona_id=persona_id,
        vendor_voice_id=vendor_voice_id,
        display_name="Bobo",
        persona_label="A warm grandfather",
        language=language,
        gender=gender,
        substitute_persona_id=substitute_persona_id,
    )


# ---------------------------------------------------------------------------
# The shipped cast
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("language", list(Language))
def test_every_language_ships_three_distinct_characters(language: Language) -> None:
    # Arrange
    registry = default_registry()

    # Act
    entries = registry.for_language(language)

    # Assert
    assert len(entries) == GREETINGS_PER_KIT
    assert len({entry.persona_id for entry in entries}) == GREETINGS_PER_KIT


@pytest.mark.parametrize("language", list(Language))
def test_every_language_offers_more_than_one_gender(language: Language) -> None:
    # Arrange
    registry = default_registry()

    # Act
    genders = {entry.gender for entry in registry.for_language(language)}

    # Assert — three identical-sounding grandfathers is the failure this prevents.
    assert len(genders) > 1


def test_no_entry_claims_phoneme_support_because_v3_has_none() -> None:
    # Arrange / Act
    claiming = [entry for entry in DEFAULT_VOICE_ENTRIES if entry.supports_phoneme_override]

    # Assert
    assert claiming == []


def test_both_uzbek_scripts_share_one_character_cast() -> None:
    # Arrange
    registry = default_registry()

    # Act
    latin = {entry.persona_id for entry in registry.for_language(Language.UZ_LATN)}
    cyrillic = {entry.persona_id for entry in registry.for_language(Language.UZ_CYRL)}

    # Assert
    assert latin == cyrillic


def test_descriptors_carry_the_substitute_for_voice_selection() -> None:
    # Arrange
    registry = default_registry()

    # Act
    descriptor = registry.descriptors(languages=(Language.RU,))[0]

    # Assert
    assert descriptor.substitute_persona_id is not None
    assert descriptor.language is Language.RU


# ---------------------------------------------------------------------------
# Invariants
# ---------------------------------------------------------------------------
def test_rejects_two_personas_with_the_same_id_in_one_language() -> None:
    # Arrange
    entries = (_entry(), _entry(vendor_voice_id="voice-2"))

    # Act / Assert
    with pytest.raises(ConfigError, match="duplicate persona"):
        VoiceRegistry(entries)


def test_accepts_the_same_persona_id_in_two_languages() -> None:
    # Arrange
    entries = (_entry(), _entry(language=Language.UZ_CYRL))

    # Act
    registry = VoiceRegistry(entries)

    # Assert
    assert registry.get("bobo", language=Language.UZ_CYRL) is not None


def test_rejects_a_substitute_that_does_not_exist() -> None:
    # Arrange
    entries = (_entry(substitute_persona_id="ghost"),)

    # Act / Assert
    with pytest.raises(ConfigError, match="unknown substitute"):
        VoiceRegistry(entries)


def test_rejects_a_substitute_in_a_different_language() -> None:
    # Arrange
    entries = (
        _entry(substitute_persona_id="opa"),
        _entry(persona_id="opa", language=Language.RU, gender=VoiceGender.FEMALE),
    )

    # Act / Assert
    with pytest.raises(ConfigError, match="unknown substitute"):
        VoiceRegistry(entries)


def test_rejects_a_persona_that_substitutes_for_itself() -> None:
    # Arrange
    entries = (_entry(substitute_persona_id="bobo"),)

    # Act / Assert
    with pytest.raises(ConfigError, match="substitutes for itself"):
        VoiceRegistry(entries)


def test_rejects_an_empty_registry() -> None:
    # Act / Assert
    with pytest.raises(ConfigError, match="empty"):
        VoiceRegistry(())


def test_returns_none_for_an_unknown_persona() -> None:
    # Arrange
    registry = default_registry()

    # Act / Assert
    assert registry.get("nobody", language=Language.EN) is None


def test_restricting_returns_a_new_registry_and_leaves_the_original_whole() -> None:
    # Arrange
    registry = default_registry()

    # Act
    narrowed = registry.restricted_to((Language.RU,))

    # Assert
    assert narrowed.languages == (Language.RU,)
    assert len(registry.entries) == len(DEFAULT_VOICE_ENTRIES)


# ---------------------------------------------------------------------------
# The environment override
# ---------------------------------------------------------------------------
def test_parses_a_json_registry_from_configuration() -> None:
    # Arrange
    raw = json.dumps(
        [
            {
                "persona_id": "guest",
                "vendor_voice_id": "voice-9",
                "display_name": "Guest",
                "persona_label": "A guest of honour",
                "language": "ru",
                "gender": "female",
            }
        ]
    )

    # Act
    result = parse_voice_registry(raw)

    # Assert
    assert is_ok(result)
    assert result.value.get("guest", language=Language.RU) is not None


def test_returns_err_when_the_registry_json_is_malformed() -> None:
    # Act
    result = parse_voice_registry("[{not json")

    # Assert
    assert is_err(result)
    assert result.error.error_code.value == "CONFIG_INVALID"


def test_returns_err_when_the_registry_is_not_an_array() -> None:
    # Act
    result = parse_voice_registry('{"persona_id": "guest"}')

    # Assert
    assert is_err(result)
    assert "array" in result.error.operator_message


def test_returns_err_when_an_entry_is_missing_a_required_field() -> None:
    # Act
    result = parse_voice_registry('[{"persona_id": "guest"}]')

    # Assert
    assert is_err(result)
    assert "invalid" in result.error.operator_message


def test_returns_err_when_an_entry_carries_an_unknown_field() -> None:
    # Arrange — a typo in a config file must fail loudly, not be silently ignored.
    raw = json.dumps(
        [
            {
                "persona_id": "guest",
                "vendor_voice_id": "voice-9",
                "display_name": "Guest",
                "persona_label": "A guest of honour",
                "language": "ru",
                "gender": "female",
                "vioce_settings": {},
            }
        ]
    )

    # Act
    result = parse_voice_registry(raw)

    # Assert
    assert is_err(result)


def test_returns_err_when_the_registry_json_is_absurdly_large() -> None:
    # Act
    result = parse_voice_registry("[]" + " " * 21_000)

    # Assert
    assert is_err(result)
    assert "over the" in result.error.operator_message


def test_returns_err_when_a_parsed_registry_breaks_an_invariant() -> None:
    # Arrange — schema-valid entries that still violate the substitute rule.
    raw = json.dumps(
        [
            {
                "persona_id": "guest",
                "vendor_voice_id": "voice-9",
                "display_name": "Guest",
                "persona_label": "A guest of honour",
                "language": "ru",
                "gender": "female",
                "substitute_persona_id": "ghost",
            }
        ]
    )

    # Act
    result = parse_voice_registry(raw)

    # Assert
    assert is_err(result)
    assert "unknown substitute" in result.error.operator_message


def test_every_shipped_voice_id_is_an_elevenlabs_id_not_a_vendor_name() -> None:
    """Every language routes to ElevenLabs, so every id must be an ElevenLabs id.

    The Uzbek entries once carried ``davron``/``gulnoza``/``aziz`` — another vendor's voice
    NAMES, left behind when Uzbek moved to ElevenLabs. Routing still sent them there, which
    404s with ``voice_not_found``. Uzbek is the default language, so every Uzbek kit would
    have lost all three greetings. An ElevenLabs id is a 20-character opaque token.
    """
    # Arrange
    expected_length = 20

    # Act
    offenders = [
        (entry.language.value, entry.persona_id, entry.vendor_voice_id)
        for entry in DEFAULT_VOICE_ENTRIES
        if len(entry.vendor_voice_id) != expected_length
        or not entry.vendor_voice_id.isalnum()
    ]

    # Assert
    assert offenders == []
