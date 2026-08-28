"""The one call: lyrics + spoken scripts + name respellings from a single ``Brief``.

Two responsibilities, kept apart:

1. Build the prompt and call the provider (``write_kit``).
2. Turn the validated payload into frozen domain contracts (``map_kit_payload``).

Step 2 is where the product's central rule is enforced mechanically rather than hoped
for: **exactly one section carries the name, and it holds exactly one line** — the line
the music provider isolates in its own chunk. A model that flags two hook sections, or
writes four lines into the hook, is corrected deterministically here rather than costing
an order a re-prompt. Genuine structural failures still return ``Err``.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Final

from pydantic import ValidationError as PydanticValidationError

from hbd.contracts import (
    MAX_CANDIDATE_CHARS,
    Brief,
    Err,
    LlmProvider,
    LlmRequest,
    LyricDraft,
    LyricSection,
    NameStrategy,
    Result,
    SpokenScript,
    err,
    ok,
)
from hbd.errors import LlmParseError
from hbd.logging import get_logger
from hbd.providers.llm.prompt_loader import language_guide, render_prompt
from hbd.providers.llm.retry import generate_with_retry
from hbd.providers.llm.schemas import (
    MAX_RESPELLINGS,
    KitDraft,
    KitPlanPayload,
    NameRespelling,
    PersonaBrief,
    SpokenScriptPayload,
)
from hbd.providers.llm.task_settings import LlmTaskSettings
from hbd.providers.llm.utils import clip

__all__ = [
    "write_kit",
    "map_kit_payload",
    "build_kit_request",
    "KIT_SYSTEM_PROMPT",
    "KIT_USER_PROMPT",
]

_LOG = get_logger(__name__)

KIT_SYSTEM_PROMPT: Final[str] = "kit_system"
KIT_USER_PROMPT: Final[str] = "kit_user"

_MAX_TITLE_CHARS: Final[int] = 120
_MAX_LABEL_CHARS: Final[int] = 40
_MAX_SCRIPT_CHARS: Final[int] = 2_000
_MS_PER_SECOND: Final[int] = 1_000
_EMPTY_NOTE: Final[str] = "(the buyer left no note)"

#: What a model may write in ``strategy``. Anything else falls back to PHONETIC, which is
#: the honest label for "a respelling we cannot otherwise classify".
_STRATEGY_FALLBACK: Final[NameStrategy] = NameStrategy.PHONETIC


def build_kit_request(
    brief: Brief, personas: Sequence[PersonaBrief], settings: LlmTaskSettings
) -> LlmRequest:
    """Render both prompts for this brief. Pure — no I/O, no provider."""
    name_line_seconds = settings.name_chunk_duration_ms / _MS_PER_SECOND
    shared = {
        "recipient_display": brief.recipient.display,
        "greeting_count": str(len(personas)),
        "name_line_seconds": f"{name_line_seconds:.0f}",
        "output_language": brief.output_language.value,
    }
    system = render_prompt(
        KIT_SYSTEM_PROMPT,
        {
            **shared,
            "language_guide": language_guide(brief.output_language),
            "greeting_min_s": f"{settings.greeting_min_duration_s:.0f}",
            "greeting_max_s": f"{settings.greeting_max_duration_s:.0f}",
            "max_respellings": str(MAX_RESPELLINGS),
            "strategy_vocabulary": ", ".join(strategy.value for strategy in NameStrategy),
        },
    )
    user = render_prompt(
        KIT_USER_PROMPT,
        {
            **shared,
            "occasion": brief.occasion.value,
            "genre": brief.genre.value.replace("_", " "),
            "vocal_gender": brief.vocal_gender.value,
            "note": brief.note.strip() or _EMPTY_NOTE,
            "personas": _format_personas(personas),
        },
    )
    return LlmRequest(
        system_prompt=system,
        user_prompt=user,
        temperature=settings.llm_temperature,
        max_output_tokens=settings.llm_max_output_tokens,
    )


async def write_kit(
    provider: LlmProvider,
    brief: Brief,
    personas: Sequence[PersonaBrief],
    settings: LlmTaskSettings,
) -> Result[KitDraft]:
    """Produce a whole kit's text in one call. Never raises."""
    if not personas:
        return err(
            LlmParseError(
                "write_kit needs at least one persona to write a greeting for",
                provider=provider.name,
                is_retryable=False,
            )
        )
    request = build_kit_request(brief, personas, settings)
    outcome = await generate_with_retry(
        provider,
        request,
        KitPlanPayload,
        timeout_s=settings.llm_timeout_s,
        max_attempts=settings.llm_parse_max_attempts,
    )
    if isinstance(outcome, Err):
        return outcome
    return map_kit_payload(outcome.value, brief, personas, settings, provider_name=provider.name)


def map_kit_payload(
    payload: KitPlanPayload,
    brief: Brief,
    personas: Sequence[PersonaBrief],
    settings: LlmTaskSettings,
    *,
    provider_name: str,
) -> Result[KitDraft]:
    """Validated payload -> frozen domain objects. Never raises, never mutates ``payload``."""
    name_line = payload.name_line.strip()
    if not name_line:
        return _shape_error("name_line is blank", provider_name, brief)
    if len(payload.spoken_scripts) < len(personas):
        return _shape_error(
            f"expected {len(personas)} spoken scripts, got {len(payload.spoken_scripts)}",
            provider_name,
            brief,
        )

    respellings = _map_respellings(payload)
    if not respellings:
        return _shape_error("no usable name respelling survived validation", provider_name, brief)

    try:
        lyrics = LyricDraft(
            title=clip(payload.title, _MAX_TITLE_CHARS),
            language=brief.output_language,
            sections=_map_sections(payload, name_line),
            name_display=brief.recipient.display,
        )
        scripts = _map_scripts(payload, brief, personas, settings)
    except (PydanticValidationError, ValueError) as exc:
        return _shape_error(f"domain mapping rejected the draft: {exc}", provider_name, brief)

    return ok(
        KitDraft(
            lyrics=lyrics,
            scripts=scripts,
            respellings=respellings,
            name_line=name_line,
            address_form_used=payload.address_form_used,
        )
    )


# ---------------------------------------------------------------------------
# Mapping helpers
# ---------------------------------------------------------------------------
def _map_sections(payload: KitPlanPayload, name_line: str) -> tuple[LyricSection, ...]:
    """Rebuild sections so exactly one hook exists and it holds exactly the name line."""
    hook_index = next(
        (index for index, section in enumerate(payload.sections) if section.is_name_hook), 0
    )
    return tuple(
        LyricSection(
            label=clip(section.label, _MAX_LABEL_CHARS),
            lines=(name_line,) if index == hook_index else section.lines,
            is_name_hook=index == hook_index,
        )
        for index, section in enumerate(payload.sections)
    )


def _map_scripts(
    payload: KitPlanPayload,
    brief: Brief,
    personas: Sequence[PersonaBrief],
    settings: LlmTaskSettings,
) -> tuple[SpokenScript, ...]:
    """One script per requested persona, in the requested order.

    The persona id is always OURS — the echoed one only decides which script goes where.
    """
    ordered = _align_to_personas(payload.spoken_scripts, personas)
    name_submitted = brief.recipient.candidates[0].text
    return tuple(
        SpokenScript(
            persona_id=persona.persona_id,
            language=brief.output_language,
            text=clip(script.text, _MAX_SCRIPT_CHARS),
            name_submitted=name_submitted,
            target_duration_s=min(
                settings.greeting_max_duration_s,
                max(settings.greeting_min_duration_s, script.target_duration_s),
            ),
        )
        for persona, script in zip(personas, ordered, strict=True)
    )


def _align_to_personas(
    scripts: Sequence[SpokenScriptPayload], personas: Sequence[PersonaBrief]
) -> tuple[SpokenScriptPayload, ...]:
    """Reorder by echoed ``persona_id`` when that is unambiguous, else keep model order."""
    by_id = {script.persona_id: script for script in scripts if script.persona_id}
    if len(by_id) == len(scripts) and all(persona.persona_id in by_id for persona in personas):
        return tuple(by_id[persona.persona_id] for persona in personas)
    _LOG.warning(
        "spoken scripts did not echo the requested persona ids; falling back to positional order",
        extra={
            "requested": [persona.persona_id for persona in personas],
            "echoed": [script.persona_id for script in scripts],
        },
    )
    return tuple(scripts[: len(personas)])


def _map_respellings(payload: KitPlanPayload) -> tuple[NameRespelling, ...]:
    """Coerce each suggestion, dropping the unusable rather than failing the order."""
    seen: set[str] = set()
    mapped: list[NameRespelling] = []
    for item in payload.name_respellings:
        text = item.text.strip()
        if not text or len(text) > MAX_CANDIDATE_CHARS or text in seen:
            continue
        seen.add(text)
        mapped.append(
            NameRespelling(
                text=text,
                strategy=_coerce_strategy(item.strategy),
                ipa=item.ipa.strip() or None,
                confidence=item.confidence,
            )
        )
    return tuple(mapped)


def _coerce_strategy(value: str) -> NameStrategy:
    """Never let one bad enum spelling discard a whole generation."""
    try:
        return NameStrategy(value.strip().lower())
    except ValueError:
        _LOG.warning(
            "unknown name strategy %r from the model; recording it as %s",
            value,
            _STRATEGY_FALLBACK.value,
            extra={"strategy": value},
        )
        return _STRATEGY_FALLBACK


def _format_personas(personas: Sequence[PersonaBrief]) -> str:
    return "\n".join(
        f"{index}. id={persona.persona_id} — {persona.description}"
        for index, persona in enumerate(personas, start=1)
    )


def _shape_error(reason: str, provider_name: str, brief: Brief) -> Result[KitDraft]:
    context = {
        "provider": provider_name,
        "reason": reason,
        "output_language": brief.output_language.value,
    }
    _LOG.error("kit draft failed structural mapping: %s", reason, extra=context)
    return err(
        LlmParseError(
            f"{provider_name} produced a kit draft this system cannot use: {reason}",
            provider=provider_name,
            context=context,
        )
    )
