"""LLM-backed ``ContentWriter``: lyrics and in-character spoken greetings.

The transport-level defence (strip fences, repair, validate) belongs to the
``LlmProvider`` adapter and is guaranteed by its contract. What lives here is the *second*
boundary, which is just as important and is easy to forget: a payload can be perfectly
valid JSON of the right shape and still be unusable — no sections, a hook that forgot the
name, five greetings when three were asked for, a persona the TTS provider has never heard
of. Every one of those is repaired where repair is safe and reported as a typed ``Err``
where it is not.

Payload models use ``extra="ignore"`` on purpose. A model that adds a helpful
``"explanation"`` key should not fail the order; a model that omits ``sections`` must.
"""

from __future__ import annotations

from typing import Final

from pydantic import BaseModel, ConfigDict

from hbd.config import Settings
from hbd.contracts import (
    Brief,
    Err,
    Language,
    LlmProvider,
    LlmRequest,
    LyricDraft,
    LyricSection,
    Result,
    SpokenScript,
    VoiceDescriptor,
    err,
    ok,
)
from hbd.errors import LlmParseError
from hbd.logging import get_logger
from hbd.pipeline.prompts import (
    lyrics_system_prompt,
    lyrics_user_prompt,
    scripts_system_prompt,
    scripts_user_prompt,
)

__all__ = [
    "LyricsPayload",
    "LyricSectionPayload",
    "GreetingsPayload",
    "GreetingPayload",
    "LlmContentWriter",
    "MAX_LYRIC_SECTIONS",
    "MAX_LINES_PER_SECTION",
]

_LOGGER = get_logger(__name__)

#: A composition plan tops out at 30 chunks; a lyric never needs anywhere near that.
MAX_LYRIC_SECTIONS: Final[int] = 8
MAX_LINES_PER_SECTION: Final[int] = 8
MAX_LINE_CHARS: Final[int] = 160
MAX_TITLE_CHARS: Final[int] = 120
MAX_LABEL_CHARS: Final[int] = 40
MAX_SCRIPT_CHARS: Final[int] = 2_000
#: Fallback label when the model returns a blank one.
DEFAULT_SECTION_LABEL: Final[str] = "section"
DEFAULT_TITLE: Final[str] = "Tabrik"


class _Payload(BaseModel):
    """Base for model-generated payloads: tolerant of extra keys, strict about types."""

    model_config = ConfigDict(extra="ignore", frozen=True)


class LyricSectionPayload(_Payload):
    label: str = ""
    lines: tuple[str, ...] = ()
    is_name_hook: bool = False


class LyricsPayload(_Payload):
    title: str = ""
    sections: tuple[LyricSectionPayload, ...] = ()


class GreetingPayload(_Payload):
    persona_id: str = ""
    text: str = ""


class GreetingsPayload(_Payload):
    greetings: tuple[GreetingPayload, ...] = ()


def _clean_lines(lines: tuple[str, ...]) -> tuple[str, ...]:
    trimmed = (line.strip()[:MAX_LINE_CHARS] for line in lines)
    return tuple(line for line in trimmed if line)[:MAX_LINES_PER_SECTION]


def _clean_label(label: str, *, index: int) -> str:
    cleaned = label.strip()[:MAX_LABEL_CHARS]
    return cleaned or f"{DEFAULT_SECTION_LABEL}-{index + 1}"


def _usable_sections(payload: LyricsPayload) -> tuple[tuple[str, tuple[str, ...], bool], ...]:
    """Drop empty sections and normalise the survivors into plain tuples."""
    usable: list[tuple[str, tuple[str, ...], bool]] = []
    for index, section in enumerate(payload.sections[:MAX_LYRIC_SECTIONS]):
        lines = _clean_lines(section.lines)
        if lines:
            usable.append((_clean_label(section.label, index=index), lines, section.is_name_hook))
    return tuple(usable)


def _hook_index(sections: tuple[tuple[str, tuple[str, ...], bool], ...], name: str) -> int:
    """Pick exactly one hook: the model's first flag, else the first mention of the name."""
    for index, (_, _, is_hook) in enumerate(sections):
        if is_hook:
            return index
    folded = name.casefold()
    for index, (_, lines, _) in enumerate(sections):
        if any(folded in line.casefold() for line in lines):
            return index
    return 0


def _build_sections(
    sections: tuple[tuple[str, tuple[str, ...], bool], ...], *, name: str, hook_index: int
) -> tuple[LyricSection, ...]:
    """Materialise domain sections, guaranteeing the hook actually carries the name."""
    built: list[LyricSection] = []
    for index, (label, lines, _) in enumerate(sections):
        is_hook = index == hook_index
        final_lines = lines
        if is_hook and not any(name.casefold() in line.casefold() for line in lines):
            final_lines = (name, *lines)[:MAX_LINES_PER_SECTION]
        built.append(LyricSection(label=label, lines=final_lines, is_name_hook=is_hook))
    return tuple(built)


def _assign_persona(
    greeting: GreetingPayload, voices: tuple[VoiceDescriptor, ...], *, index: int
) -> str:
    """Honour the model's persona when it is real; otherwise fall back to position."""
    known = {voice.persona_id for voice in voices}
    if greeting.persona_id in known:
        return greeting.persona_id
    return voices[index].persona_id


def _ensure_name_present(text: str, name: str) -> str:
    if name.casefold() in text.casefold():
        return text
    return f"{name}! {text}"[:MAX_SCRIPT_CHARS]


def _build_scripts(
    greetings: tuple[GreetingPayload, ...],
    *,
    voices: tuple[VoiceDescriptor, ...],
    language: Language,
    name_display: str,
    name_submitted: str,
    target_duration_s: float,
) -> tuple[SpokenScript, ...]:
    return tuple(
        SpokenScript(
            persona_id=_assign_persona(greeting, voices, index=index),
            language=language,
            text=_ensure_name_present(greeting.text.strip()[:MAX_SCRIPT_CHARS], name_display),
            name_submitted=name_submitted,
            target_duration_s=target_duration_s,
        )
        for index, greeting in enumerate(greetings)
    )


class LlmContentWriter:
    """Concrete ``ContentWriter``. Holds no state beyond its collaborators."""

    def __init__(self, llm: LlmProvider, settings: Settings) -> None:
        self._llm = llm
        self._settings = settings

    def _request(self, system_prompt: str, user_prompt: str) -> LlmRequest:
        return LlmRequest(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            temperature=self._settings.llm_temperature,
            max_output_tokens=self._settings.llm_max_output_tokens,
        )

    async def write_lyrics(self, brief: Brief) -> Result[LyricDraft]:
        request = self._request(
            lyrics_system_prompt(brief.output_language), lyrics_user_prompt(brief)
        )
        result = await self._llm.generate_json(
            request, LyricsPayload, timeout_s=self._settings.llm_timeout_s
        )
        if isinstance(result, Err):
            return result

        payload = result.value
        sections = _usable_sections(payload)
        if not sections:
            return err(
                LlmParseError(
                    "lyric payload contained no usable section",
                    provider=self._llm.name,
                    context={"section_count": len(payload.sections), "title": payload.title},
                )
            )

        name = brief.recipient.display
        hook_index = _hook_index(sections, name)
        draft = LyricDraft(
            title=(payload.title.strip()[:MAX_TITLE_CHARS] or DEFAULT_TITLE),
            language=brief.output_language,
            sections=_build_sections(sections, name=name, hook_index=hook_index),
            name_display=name,
        )
        _LOGGER.info(
            "lyrics written",
            extra={"sections": len(draft.sections), "hook_index": hook_index},
        )
        return ok(draft)

    async def write_scripts(
        self,
        brief: Brief,
        lyrics: LyricDraft,
        *,
        voices: tuple[VoiceDescriptor, ...],
        name_submitted: str,
        target_duration_s: float,
    ) -> Result[tuple[SpokenScript, ...]]:
        if not voices:
            return err(
                LlmParseError(
                    "cannot write greetings without at least one voice",
                    provider=self._llm.name,
                )
            )

        request = self._request(
            scripts_system_prompt(brief.output_language, len(voices)),
            scripts_user_prompt(brief, lyrics, voices=voices, target_duration_s=target_duration_s),
        )
        result = await self._llm.generate_json(
            request, GreetingsPayload, timeout_s=self._settings.llm_timeout_s
        )
        if isinstance(result, Err):
            return result

        greetings = tuple(greeting for greeting in result.value.greetings if greeting.text.strip())[
            : len(voices)
        ]
        if len(greetings) < len(voices):
            return err(
                LlmParseError(
                    "greeting payload was short of the requested count",
                    provider=self._llm.name,
                    context={"requested": len(voices), "received": len(greetings)},
                )
            )

        scripts = _build_scripts(
            greetings,
            voices=voices,
            language=brief.output_language,
            name_display=brief.recipient.display,
            name_submitted=name_submitted,
            target_duration_s=target_duration_s,
        )
        _LOGGER.info("greeting scripts written", extra={"count": len(scripts)})
        return ok(scripts)
