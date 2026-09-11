"""Who speaks. The persona catalogue is **data**, never a branch in an adapter.

Three characters per language, four languages, twelve entries. An adapter looks a persona
up; it never contains a voice id. Swapping a voice, renaming a character or moving a
persona to a different vendor is a data edit, and the whole table can be replaced from the
environment with :func:`parse_voice_registry` without touching code.

Two design points worth stating once:

* **The key is (language, persona_id), not persona_id alone.** Uzbek Latin and Uzbek
  Cyrillic are the same spoken language in two scripts, so they share a character cast;
  forcing globally unique ids would mean inventing ``bobo-latn``/``bobo-cyrl`` twins that
  differ in nothing a listener can hear.
* **``supports_phoneme_override`` is honest, not aspirational.** ElevenLabs v3 does not
  accept ``<phoneme>`` markup, so every entry here declares ``False`` and pronunciation
  rides entirely on the ranked candidate orthographies. That flag exists for a future
  engine, and lying in it would silently disable the ranking that the product depends on.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import Final

from pydantic import BaseModel, ConfigDict, Field
from pydantic import ValidationError as PydanticValidationError

from bayram.contracts import Language, Result, VoiceDescriptor, VoiceGender, err, ok
from bayram.errors import ConfigError

__all__ = [
    "VoiceEntry",
    "VoiceRegistry",
    "DEFAULT_VOICE_ENTRIES",
    "default_registry",
    "parse_voice_registry",
    "MAX_REGISTRY_JSON_CHARS",
]

#: An environment-supplied registry is a config value, not a document.
MAX_REGISTRY_JSON_CHARS: Final[int] = 20_000


@dataclass(frozen=True, slots=True)
class VoiceEntry:
    """One character, bound to one vendor voice.

    ``persona_id`` is ours and stable across vendors; ``vendor_voice_id`` is the vendor's
    and appears nowhere outside this table. ``display_name`` and ``persona_label`` are the
    two halves a user sees: a name to pick from a list, and a one-line description of the
    character. ``substitute_persona_id`` names the same-language stand-in used when this
    voice is unavailable.
    """

    persona_id: str
    vendor_voice_id: str
    display_name: str
    persona_label: str
    language: Language
    gender: VoiceGender
    supports_phoneme_override: bool = False
    substitute_persona_id: str | None = None
    default_mood: str | None = None

    def to_descriptor(self) -> VoiceDescriptor:
        """The vendor-neutral view the pipeline selects from."""
        return VoiceDescriptor(
            persona_id=self.persona_id,
            language=self.language,
            gender=self.gender,
            supports_phoneme_override=self.supports_phoneme_override,
            substitute_persona_id=self.substitute_persona_id,
        )


class VoiceEntrySpec(BaseModel):
    """Schema for an entry arriving as JSON. Unknown keys are a configuration mistake."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    persona_id: str = Field(min_length=1, max_length=64)
    vendor_voice_id: str = Field(min_length=1, max_length=128)
    display_name: str = Field(min_length=1, max_length=64)
    persona_label: str = Field(min_length=1, max_length=200)
    language: Language
    gender: VoiceGender
    supports_phoneme_override: bool = False
    substitute_persona_id: str | None = Field(default=None, max_length=64)
    default_mood: str | None = Field(default=None, max_length=40)

    def to_entry(self) -> VoiceEntry:
        return VoiceEntry(
            persona_id=self.persona_id,
            vendor_voice_id=self.vendor_voice_id,
            display_name=self.display_name,
            persona_label=self.persona_label,
            language=self.language,
            gender=self.gender,
            supports_phoneme_override=self.supports_phoneme_override,
            substitute_persona_id=self.substitute_persona_id,
            default_mood=self.default_mood,
        )


class VoiceRegistry:
    """An immutable, validated catalogue. Built once at startup, read everywhere."""

    def __init__(self, entries: Sequence[VoiceEntry]) -> None:
        """Validate and freeze. Raises ``ConfigError`` — this is startup, not a request."""
        if not entries:
            raise ConfigError("the voice registry is empty; at least one voice is required")
        frozen = tuple(entries)
        index: dict[tuple[Language, str], VoiceEntry] = {}
        for entry in frozen:
            key = (entry.language, entry.persona_id)
            if key in index:
                raise ConfigError(
                    f"duplicate persona '{entry.persona_id}' for language {entry.language.value}",
                    context={"persona_id": entry.persona_id, "language": entry.language.value},
                )
            index[key] = entry
        _guard_substitutes(frozen, index)
        self._entries = frozen
        self._index = index

    # -- reading ------------------------------------------------------------
    @property
    def entries(self) -> tuple[VoiceEntry, ...]:
        return self._entries

    @property
    def languages(self) -> tuple[Language, ...]:
        """Languages with at least one voice, in first-seen order."""
        return tuple(dict.fromkeys(entry.language for entry in self._entries))

    def get(self, persona_id: str, *, language: Language) -> VoiceEntry | None:
        """The entry for one character in one language, or ``None`` when unknown."""
        return self._index.get((language, persona_id))

    def for_language(self, language: Language) -> tuple[VoiceEntry, ...]:
        return tuple(entry for entry in self._entries if entry.language is language)

    def descriptors(
        self, *, languages: Iterable[Language] | None = None
    ) -> tuple[VoiceDescriptor, ...]:
        """Vendor-neutral descriptors, optionally narrowed to the languages a vendor serves."""
        if languages is None:
            return tuple(entry.to_descriptor() for entry in self._entries)
        wanted = frozenset(languages)
        return tuple(entry.to_descriptor() for entry in self._entries if entry.language in wanted)

    def restricted_to(self, languages: Iterable[Language]) -> VoiceRegistry:
        """A NEW registry holding only the given languages. Never mutates this one."""
        wanted = frozenset(languages)
        return VoiceRegistry(tuple(entry for entry in self._entries if entry.language in wanted))


def _guard_substitutes(
    entries: tuple[VoiceEntry, ...], index: dict[tuple[Language, str], VoiceEntry]
) -> None:
    """A substitute must exist, share the language, and not be the voice itself."""
    for entry in entries:
        substitute = entry.substitute_persona_id
        if substitute is None:
            continue
        if substitute == entry.persona_id:
            raise ConfigError(
                f"persona '{entry.persona_id}' substitutes for itself",
                context={"persona_id": entry.persona_id},
            )
        if (entry.language, substitute) not in index:
            raise ConfigError(
                f"persona '{entry.persona_id}' names an unknown substitute '{substitute}' "
                f"for language {entry.language.value}",
                context={"persona_id": entry.persona_id, "substitute_persona_id": substitute},
            )


# ---------------------------------------------------------------------------
# The default cast.
#
# ElevenLabs ids are the vendor's public multilingual voices; the same id speaks Uzbek,
# Russian and English, so the character, not the id, is what differs between the rows.
#
# Every row here is an ElevenLabs id because every language routes to ElevenLabs. The
# The Uzbek rows once held another vendor's voice NAMES (``davron``/``gulnoza``/``aziz``)
# left over from when Uzbek was bought elsewhere; ElevenLabs 404s those with
# ``voice_not_found``, which silently cost every Uzbek kit all three greetings. Adding a
# second vendor means supplying its ids through ``BAYRAM_TTS_VOICE_REGISTRY_JSON`` at the same
# time as the route — the id and the route travel together.
# ---------------------------------------------------------------------------
_ELEVEN_MALE_ELDER: Final[str] = "pqHfZKP75CvOlQylNhV4"
_ELEVEN_MALE_ANNOUNCER: Final[str] = "JBFqnCBsd6RMkjVDRZzb"
_ELEVEN_FEMALE_WARM: Final[str] = "XB0fDUnXU5powFXDhCwa"
_ELEVEN_MALE_CASUAL: Final[str] = "iP95p4xoKVk53GoZ742B"
_ELEVEN_FEMALE_YOUNG: Final[str] = "cgSgspJ2msm6clMCkdW9"
_ELEVEN_MALE_NARRATOR: Final[str] = "nPczCjzI2devNBz1zQrb"
#: Matilda — upbeat middle-aged female, for the teasing elder sister.
_ELEVEN_FEMALE_UPBEAT: Final[str] = "XrExE9yKIg1WjnnlVkGX"
#: Liam — energetic young male, for the town crier.
_ELEVEN_MALE_ENERGETIC: Final[str] = "TX3LPaxmHKxFdv7VOQHJ"


def _uzbek_cast(language: Language) -> tuple[VoiceEntry, ...]:
    """The same three characters in both Uzbek scripts — one cast, two orthographies."""
    return (
        VoiceEntry(
            persona_id="bobo",
            vendor_voice_id=_ELEVEN_MALE_ELDER,
            display_name="Bobo",
            persona_label="Mehribon bobo — a warm grandfather giving a blessing",
            language=language,
            gender=VoiceGender.MALE,
            substitute_persona_id="jarchi",
            default_mood="neutral",
        ),
        VoiceEntry(
            persona_id="opa",
            vendor_voice_id=_ELEVEN_FEMALE_UPBEAT,
            display_name="Opa",
            persona_label="Quvnoq opa — a cheerful older sister teasing affectionately",
            language=language,
            gender=VoiceGender.FEMALE,
            substitute_persona_id="bobo",
            default_mood="happy",
        ),
        VoiceEntry(
            persona_id="jarchi",
            vendor_voice_id=_ELEVEN_MALE_ENERGETIC,
            display_name="Jarchi",
            persona_label="Jarchi — a town crier announcing the day at full volume",
            language=language,
            gender=VoiceGender.MALE,
            substitute_persona_id="opa",
            default_mood="happy",
        ),
    )


DEFAULT_VOICE_ENTRIES: Final[tuple[VoiceEntry, ...]] = (
    *_uzbek_cast(Language.UZ_LATN),
    *_uzbek_cast(Language.UZ_CYRL),
    VoiceEntry(
        persona_id="ded-moroz",
        vendor_voice_id=_ELEVEN_MALE_ELDER,
        display_name="Дед Мороз",
        persona_label="Ded Moroz — the New Year grandfather, booming and benevolent",
        language=Language.RU,
        gender=VoiceGender.MALE,
        substitute_persona_id="diktor",
        default_mood="warmly",
    ),
    VoiceEntry(
        persona_id="diktor",
        vendor_voice_id=_ELEVEN_MALE_ANNOUNCER,
        display_name="Диктор",
        persona_label="Diktor — a retro radio announcer reading a solemn dedication",
        language=Language.RU,
        gender=VoiceGender.MALE,
        substitute_persona_id="podruga",
        default_mood="dramatic",
    ),
    VoiceEntry(
        persona_id="podruga",
        vendor_voice_id=_ELEVEN_FEMALE_WARM,
        display_name="Подруга",
        persona_label="Podruga — a best friend calling with the news",
        language=Language.RU,
        gender=VoiceGender.FEMALE,
        substitute_persona_id="ded-moroz",
        default_mood="excited",
    ),
    VoiceEntry(
        persona_id="showman",
        vendor_voice_id=_ELEVEN_MALE_CASUAL,
        display_name="The Showman",
        persona_label="A game-show host announcing the birthday like a grand prize",
        language=Language.EN,
        gender=VoiceGender.MALE,
        substitute_persona_id="narrator",
        default_mood="excited",
    ),
    VoiceEntry(
        persona_id="bestie",
        vendor_voice_id=_ELEVEN_FEMALE_YOUNG,
        display_name="The Bestie",
        persona_label="A close friend leaving an over-the-top voice note",
        language=Language.EN,
        gender=VoiceGender.FEMALE,
        substitute_persona_id="showman",
        default_mood="happy",
    ),
    VoiceEntry(
        persona_id="narrator",
        vendor_voice_id=_ELEVEN_MALE_NARRATOR,
        display_name="The Narrator",
        persona_label="A cinematic trailer narrator treating the day as an epic",
        language=Language.EN,
        gender=VoiceGender.MALE,
        substitute_persona_id="bestie",
        default_mood="dramatic",
    ),
)


def default_registry() -> VoiceRegistry:
    """The shipped cast. Built fresh so no caller can share mutable state."""
    return VoiceRegistry(DEFAULT_VOICE_ENTRIES)


def parse_voice_registry(raw_json: str) -> Result[VoiceRegistry]:
    """Build a registry from a JSON array of entries. Never raises.

    This is the seam that keeps the cast out of code: point a setting at a JSON array and
    the whole table is replaced. Defended the same way as any other external text — bounded
    length, real parse, schema validation, typed failure.
    """
    if len(raw_json) > MAX_REGISTRY_JSON_CHARS:
        return err(
            ConfigError(
                f"voice registry JSON is {len(raw_json)} chars, over the "
                f"{MAX_REGISTRY_JSON_CHARS} limit",
                context={"length": len(raw_json)},
            )
        )
    try:
        payload = json.loads(raw_json)
    except ValueError as exc:
        return err(
            ConfigError(
                f"voice registry is not valid JSON: {exc}",
                context={"excerpt": raw_json[:200]},
                cause=exc,
            )
        )
    if not isinstance(payload, list):
        return err(
            ConfigError(
                f"voice registry must be a JSON array, got {type(payload).__name__}",
                context={"excerpt": raw_json[:200]},
            )
        )
    try:
        specs = [VoiceEntrySpec.model_validate(item) for item in payload]
    except PydanticValidationError as exc:
        return err(
            ConfigError(
                f"voice registry entries are invalid: {exc.error_count()} issue(s)",
                context={"issues": exc.errors(include_url=False)[:5]},
                cause=exc,
            )
        )
    try:
        return ok(VoiceRegistry([spec.to_entry() for spec in specs]))
    except ConfigError as exc:
        return err(exc)
