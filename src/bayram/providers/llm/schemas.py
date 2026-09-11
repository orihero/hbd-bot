"""Response shapes for every LLM call, plus the domain objects they map to.

Two families live here and they are deliberately not the same objects:

* ``*Payload`` models are what a **model** is asked to emit. They are permissive about
  values (a strategy label is a plain ``str``, a confidence may arrive as ``"0.9"``)
  and strict about *structure*. Nothing downstream consumes them directly.
* ``KitDraft``, ``IntakeDraft`` and ``NameRespelling`` are ours. Enums are real enums,
  numbers are clamped, and the mapping that produces them lives in ``writer``/``intake``.

The permissiveness is the point of the project's parsing rule: a wrong enum spelling in
one field must not throw away an otherwise perfect lyric. Coerce and default, then log.
"""

from __future__ import annotations

from typing import Any, Final

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from bayram.contracts import (
    MAX_CANDIDATE_CHARS,
    Language,
    LyricDraft,
    NameCandidate,
    NameStrategy,
    SpokenScript,
)

__all__ = [
    "PersonaBrief",
    "IntakePayload",
    "KitPlanPayload",
    "LyricSectionPayload",
    "NameRespellingPayload",
    "SpokenScriptPayload",
    "NameRespelling",
    "KitDraft",
    "IntakeDraft",
    "MIN_LYRIC_SECTIONS",
    "MAX_LYRIC_SECTIONS",
    "MAX_FACTS",
    "MAX_RESPELLINGS",
]

#: Structural bounds on generated text. Not vendor limits — editorial ones — but they
#: are the difference between a malformed generation and a two-hour debugging session.
MIN_LYRIC_SECTIONS: Final[int] = 2
MAX_LYRIC_SECTIONS: Final[int] = 12
MAX_LINES_PER_SECTION: Final[int] = 16
MAX_FACTS: Final[int] = 5
MAX_RESPELLINGS: Final[int] = 6
MAX_SPOKEN_SCRIPTS: Final[int] = 5

_DEFAULT_CONFIDENCE: Final[float] = 0.5


class PersonaBrief(BaseModel):
    """A character voice the greeting writer must write for. INPUT, not model output.

    The persona catalogue belongs to the TTS layer; this is the slice the writer needs.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    persona_id: str = Field(min_length=1, max_length=64)
    description: str = Field(min_length=1, max_length=400)


class _Payload(BaseModel):
    """Base for model-emitted shapes: frozen, tolerant of extra keys.

    ``extra="ignore"`` on purpose — a model that adds a helpful ``"notes"`` key has not
    failed, and rejecting the whole generation over it would be the opposite of robust.
    Our own domain models keep ``extra="forbid"``.
    """

    model_config = ConfigDict(frozen=True, extra="ignore")


class LyricSectionPayload(_Payload):
    label: str = Field(min_length=1)
    lines: tuple[str, ...] = Field(min_length=1, max_length=MAX_LINES_PER_SECTION)
    is_name_hook: bool = False

    @field_validator("lines")
    @classmethod
    def _drop_blank_lines(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        kept = tuple(line.strip() for line in value if line.strip())
        if not kept:
            raise ValueError("section has no non-blank lines")
        return kept


class SpokenScriptPayload(_Payload):
    """One character greeting. ``persona_id`` is an echo used to re-align order."""

    persona_id: str = ""
    text: str = Field(min_length=1)
    target_duration_s: float = 30.0


class NameRespellingPayload(_Payload):
    """A candidate orthography for the recipient's name, as the model proposes it."""

    text: str = Field(min_length=1)
    strategy: str = ""
    ipa: str = ""
    confidence: float = _DEFAULT_CONFIDENCE

    @field_validator("confidence", mode="before")
    @classmethod
    def _clamp_confidence(cls, value: Any) -> Any:
        """Clamp instead of reject: a model that answers ``1.2`` is confident, not broken."""
        try:
            number = float(value)
        except (TypeError, ValueError):
            return _DEFAULT_CONFIDENCE
        return min(1.0, max(0.0, number))


class KitPlanPayload(_Payload):
    """The single call: lyrics + spoken scripts + name respellings, one object.

    ``name_line`` is returned *separately* from the sections because the music provider
    isolates it in its own 8-second chunk; a re-render then costs one chunk, not a track.
    """

    title: str = Field(min_length=1)
    sections: tuple[LyricSectionPayload, ...] = Field(
        min_length=MIN_LYRIC_SECTIONS, max_length=MAX_LYRIC_SECTIONS
    )
    name_line: str = Field(min_length=1)
    spoken_scripts: tuple[SpokenScriptPayload, ...] = Field(
        min_length=1, max_length=MAX_SPOKEN_SCRIPTS
    )
    name_respellings: tuple[NameRespellingPayload, ...] = Field(
        min_length=1, max_length=MAX_RESPELLINGS
    )
    address_form_used: str = ""

    @model_validator(mode="after")
    def _must_mark_a_name_hook(self) -> KitPlanPayload:
        if not any(section.is_name_hook for section in self.sections):
            raise ValueError("no section is flagged is_name_hook; the name has no chunk to own")
        return self


class IntakePayload(_Payload):
    """Normalised intake: a cleaned brief plus the safety verdict."""

    display_name: str = Field(min_length=1)
    detected_language: str = ""
    cleaned_note: str = ""
    facts: tuple[str, ...] = ()
    removed_artist_terms: tuple[str, ...] = ()
    is_safe: bool = True
    rejection_reason: str = ""

    @field_validator("facts", "removed_artist_terms")
    @classmethod
    def _tidy(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        return tuple(item.strip() for item in value if item.strip())[:MAX_FACTS]


# ---------------------------------------------------------------------------
# Domain side: what the rest of the system consumes
# ---------------------------------------------------------------------------
class _Domain(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class NameRespelling(_Domain):
    """A respelling suggestion with the extra evidence ``NameCandidate`` has no room for.

    The name subsystem ranks candidates by CONFIGURATION, not by this confidence score;
    ``ipa`` and ``confidence`` exist for the TTS phoneme path and the admin review queue.
    """

    text: str = Field(min_length=1, max_length=MAX_CANDIDATE_CHARS)
    strategy: NameStrategy
    ipa: str | None = None
    confidence: float = Field(ge=0.0, le=1.0)

    def as_candidate(self, rank: int) -> NameCandidate:
        return NameCandidate(text=self.text, strategy=self.strategy, rank=rank)


class KitDraft(_Domain):
    """Everything one LLM call produced, in domain form.

    ``name_line`` is the single dedicated line carrying the name. It is also the sole
    line of the one section flagged ``is_name_hook``, guaranteed by the mapping layer.
    """

    lyrics: LyricDraft
    scripts: tuple[SpokenScript, ...] = Field(min_length=1)
    respellings: tuple[NameRespelling, ...] = Field(min_length=1)
    name_line: str = Field(min_length=1)
    address_form_used: str = ""

    def candidates(self) -> tuple[NameCandidate, ...]:
        """Respellings as ranked ``NameCandidate``s, in the order the model returned them."""
        return tuple(item.as_candidate(rank) for rank, item in enumerate(self.respellings))


class IntakeDraft(_Domain):
    """Normalised intake in domain form. ``detected_language`` is ``None`` when unusable."""

    display_name: str = Field(min_length=1)
    cleaned_note: str = ""
    facts: tuple[str, ...] = ()
    removed_artist_terms: tuple[str, ...] = ()
    detected_language: Language | None = None
