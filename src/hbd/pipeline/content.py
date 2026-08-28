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

What a well-formed lyric *is* — the clamps, the labels, the one-hook-carries-the-name rule
— no longer lives here. It moved to ``hbd.pipeline.lyric_shape`` when the wizard gained a
paste-your-own path, so a written lyric and a pasted one cannot be shaped differently. This
module keeps only what is about the LLM payload: reading it, judging it usable, reporting
it unusable.
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
    Result,
    SpokenScript,
    VoiceDescriptor,
    err,
    ok,
)
from hbd.errors import LlmParseError
from hbd.logging import get_logger
from hbd.pipeline.lyric_shape import (
    MAX_LINES_PER_SECTION,
    MAX_LYRIC_SECTIONS,
    build_lyric_draft,
    clean_label,
    clean_lines,
)
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
    # Re-exported from ``lyric_shape`` so importers (and mypy's no_implicit_reexport)
    # that learned these names here keep working after the move.
    "MAX_LYRIC_SECTIONS",
    "MAX_LINES_PER_SECTION",
]

_LOGGER = get_logger(__name__)

MAX_SCRIPT_CHARS: Final[int] = 2_000


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


def _usable_sections(payload: LyricsPayload) -> tuple[tuple[str, tuple[str, ...], bool], ...]:
    """Drop empty sections and normalise the survivors into plain tuples.

    This one stays here rather than moving to ``lyric_shape``: it is about the *payload*
    shape, and only the LLM path ever has a ``LyricsPayload`` to normalise.
    """
    usable: list[tuple[str, tuple[str, ...], bool]] = []
    for index, section in enumerate(payload.sections[:MAX_LYRIC_SECTIONS]):
        lines = clean_lines(section.lines)
        if lines:
            usable.append((clean_label(section.label, index=index), lines, section.is_name_hook))
    return tuple(usable)


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

        draft = build_lyric_draft(
            sections,
            title=payload.title,
            language=brief.output_language,
            name_display=brief.recipient.display,
        )
        # ``build_sections`` flags exactly one hook, so this never comes up empty.
        hook_index = next(
            index for index, section in enumerate(draft.sections) if section.is_name_hook
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
