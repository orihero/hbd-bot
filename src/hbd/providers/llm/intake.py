"""Intake normalisation: tidy the typed name and note, extract facts, screen the brief.

This runs before anything is generated and before anything is charged, so it is the
cheapest place to catch an unusable brief. Two outputs matter downstream:

* ``removed_artist_terms`` — a real band name inside a style or note is a documented
  provider rejection that burns a paid generation. It goes before the music call, not after.
* ``is_safe`` — a refusal here becomes ``ModerationRejectedError``, which the bot layer
  already knows how to phrase for a customer.

What this deliberately does NOT do is canonicalise the Uzbek apostrophe or build candidate
orthographies. That is the name subsystem's job and it is deterministic; asking a model to
do it would make the one thing the product exists to get right depend on a coin flip.
"""

from __future__ import annotations

from typing import Final

from hbd.contracts import (
    MAX_RECIPIENT_NAME_CHARS,
    Err,
    Language,
    LlmProvider,
    LlmRequest,
    Result,
    err,
    ok,
)
from hbd.errors import LlmParseError, ModerationRejectedError
from hbd.logging import get_logger
from hbd.providers.llm.prompt_loader import language_guide, render_prompt
from hbd.providers.llm.retry import generate_with_retry
from hbd.providers.llm.schemas import IntakeDraft, IntakePayload
from hbd.providers.llm.task_settings import LlmTaskSettings
from hbd.providers.llm.utils import clip

__all__ = [
    "normalise_intake",
    "map_intake_payload",
    "build_intake_request",
    "INTAKE_SYSTEM_PROMPT",
    "INTAKE_USER_PROMPT",
]

_LOG = get_logger(__name__)

INTAKE_SYSTEM_PROMPT: Final[str] = "intake_system"
INTAKE_USER_PROMPT: Final[str] = "intake_user"

_MAX_NOTE_CHARS: Final[int] = 600
_EMPTY_NOTE: Final[str] = "(the buyer left no note)"


def build_intake_request(
    *,
    raw_name: str,
    raw_note: str,
    ui_language: Language,
    output_language: Language,
    settings: LlmTaskSettings,
) -> LlmRequest:
    """Render both intake prompts. Pure — no I/O."""
    system = render_prompt(
        INTAKE_SYSTEM_PROMPT, {"language_guide": language_guide(output_language)}
    )
    user = render_prompt(
        INTAKE_USER_PROMPT,
        {
            "raw_name": raw_name.strip(),
            "raw_note": raw_note.strip() or _EMPTY_NOTE,
            "ui_language": ui_language.value,
            "output_language": output_language.value,
        },
    )
    return LlmRequest(
        system_prompt=system,
        user_prompt=user,
        temperature=settings.llm_temperature,
        max_output_tokens=settings.llm_max_output_tokens,
    )


async def normalise_intake(
    provider: LlmProvider,
    *,
    raw_name: str,
    raw_note: str,
    ui_language: Language,
    output_language: Language,
    settings: LlmTaskSettings,
) -> Result[IntakeDraft]:
    """Clean and screen one brief. Never raises.

    Returns ``Err(ModerationRejectedError)`` when the model refuses the brief on policy
    grounds — a terminal, user-facing outcome, not a retryable provider fault.
    """
    if not raw_name.strip():
        return err(
            LlmParseError(
                "intake normalisation needs a non-empty recipient name",
                provider=provider.name,
                is_retryable=False,
            )
        )
    request = build_intake_request(
        raw_name=raw_name,
        raw_note=raw_note,
        ui_language=ui_language,
        output_language=output_language,
        settings=settings,
    )
    outcome = await generate_with_retry(
        provider,
        request,
        IntakePayload,
        timeout_s=settings.llm_timeout_s,
        max_attempts=settings.llm_parse_max_attempts,
    )
    if isinstance(outcome, Err):
        return outcome
    return map_intake_payload(outcome.value, raw_name=raw_name, provider_name=provider.name)


def map_intake_payload(
    payload: IntakePayload, *, raw_name: str, provider_name: str
) -> Result[IntakeDraft]:
    """Validated payload -> ``IntakeDraft``, or a typed refusal. Never raises."""
    if not payload.is_safe:
        reason = payload.rejection_reason.strip() or "unspecified policy refusal"
        _LOG.warning(
            "intake screening refused a brief", extra={"provider": provider_name, "reason": reason}
        )
        return err(
            ModerationRejectedError(
                f"intake screening refused the brief: {reason}",
                context={"provider": provider_name, "reason": reason},
            )
        )

    display_name = clip(payload.display_name, MAX_RECIPIENT_NAME_CHARS) or clip(
        raw_name, MAX_RECIPIENT_NAME_CHARS
    )
    if not display_name:
        return err(
            LlmParseError(
                f"{provider_name} returned no usable display name",
                provider=provider_name,
                context={"provider": provider_name, "raw_name": raw_name},
            )
        )

    return ok(
        IntakeDraft(
            display_name=display_name,
            cleaned_note=clip(payload.cleaned_note, _MAX_NOTE_CHARS),
            facts=payload.facts,
            removed_artist_terms=payload.removed_artist_terms,
            detected_language=_coerce_language(payload.detected_language),
        )
    )


def _coerce_language(value: str) -> Language | None:
    """An unrecognised label is ``None``, never an exception and never a wrong guess."""
    try:
        return Language(value.strip().lower())
    except ValueError:
        return None
