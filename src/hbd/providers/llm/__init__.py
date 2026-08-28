"""The LLM layer: intake normalisation, lyric writing, spoken scripts, name respelling.

Everything a caller needs:

    from hbd.providers.llm import build_llm_provider, write_kit, LlmTaskSettings

    provider = build_llm_provider(settings)
    result = await write_kit(provider, brief, personas, LlmTaskSettings.from_settings(settings))

Two promises hold across every entry point here. Nothing raises out of a task or an
adapter — failure is an ``Err`` carrying a typed ``HbdError``. And nothing returns data
that has not been validated against a pydantic schema, however malformed the model's
answer was.
"""

from __future__ import annotations

from hbd.providers.llm.factory import build_fallback_llm_provider, build_llm_provider
from hbd.providers.llm.gemini import GeminiLlmProvider
from hbd.providers.llm.intake import build_intake_request, map_intake_payload, normalise_intake
from hbd.providers.llm.json_schema import to_gemini_schema, to_openai_strict_schema
from hbd.providers.llm.openai_compat import OpenAiCompatLlmProvider
from hbd.providers.llm.parsing import parse_model_json
from hbd.providers.llm.prompt_loader import language_guide, load_prompt, render_prompt
from hbd.providers.llm.retry import generate_with_retry
from hbd.providers.llm.schemas import (
    IntakeDraft,
    IntakePayload,
    KitDraft,
    KitPlanPayload,
    NameRespelling,
    PersonaBrief,
)
from hbd.providers.llm.task_settings import LlmTaskSettings
from hbd.providers.llm.writer import build_kit_request, map_kit_payload, write_kit

__all__ = [
    # Providers
    "GeminiLlmProvider",
    "OpenAiCompatLlmProvider",
    "build_llm_provider",
    "build_fallback_llm_provider",
    # Tasks
    "normalise_intake",
    "write_kit",
    "build_intake_request",
    "build_kit_request",
    "map_intake_payload",
    "map_kit_payload",
    "generate_with_retry",
    # Data
    "LlmTaskSettings",
    "PersonaBrief",
    "IntakeDraft",
    "IntakePayload",
    "KitDraft",
    "KitPlanPayload",
    "NameRespelling",
    # Boundary utilities
    "parse_model_json",
    "to_gemini_schema",
    "to_openai_strict_schema",
    "load_prompt",
    "render_prompt",
    "language_guide",
]
