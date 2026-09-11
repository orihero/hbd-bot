"""The LLM layer: intake normalisation, lyric writing, spoken scripts, name respelling.

Everything a caller needs:

    from bayram.providers.llm import build_llm_provider, write_kit, LlmTaskSettings

    provider = build_llm_provider(settings)
    result = await write_kit(provider, brief, personas, LlmTaskSettings.from_settings(settings))

Three promises hold across every entry point here. Nothing raises out of a task or an
adapter — failure is an ``Err`` carrying a typed ``BayramError``. Nothing returns data
that has not been validated against a pydantic schema, however malformed the model's
answer was. And every vendor call, successful or not, records exactly one
``bayram.usage.VendorUsage`` through the sink its adapter was built with — the LLM leg is
where the money goes, and until that seam existed nothing in this system could say how
much of it.
"""

from __future__ import annotations

from bayram.providers.llm.factory import build_fallback_llm_provider, build_llm_provider
from bayram.providers.llm.gemini import GeminiLlmProvider
from bayram.providers.llm.intake import build_intake_request, map_intake_payload, normalise_intake
from bayram.providers.llm.json_schema import to_gemini_schema, to_openai_strict_schema
from bayram.providers.llm.openai_compat import OpenAiCompatLlmProvider
from bayram.providers.llm.parsing import parse_model_json
from bayram.providers.llm.pricing import TokenPricing
from bayram.providers.llm.prompt_loader import language_guide, load_prompt, render_prompt
from bayram.providers.llm.retry import generate_with_retry
from bayram.providers.llm.schemas import (
    IntakeDraft,
    IntakePayload,
    KitDraft,
    KitPlanPayload,
    NameRespelling,
    PersonaBrief,
)
from bayram.providers.llm.task_settings import LlmTaskSettings
from bayram.providers.llm.writer import build_kit_request, map_kit_payload, write_kit

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
    "TokenPricing",
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
