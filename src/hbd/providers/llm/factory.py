"""Build the configured LLM provider(s) from ``Settings``.

Which vendor answers is a configuration decision, and the two adapters are behind the
identical contract, so this is the only place in the system that names either of them.

The choice is now *declared*, not inferred: ``HBD_LLM_PROVIDER`` and
``HBD_LLM_FALLBACK_PROVIDER`` name the adapter outright. An earlier revision guessed it
from a ``gemini-*`` model-id prefix, which quietly routed a self-hosted Gemini-compatible
gateway to the wrong transport. Guessing a vendor from a string is exactly the kind of
implicit rule this project keeps in config instead.
"""

from __future__ import annotations

import httpx

from hbd.config import Settings
from hbd.contracts import LlmProvider
from hbd.errors import ConfigError
from hbd.providers.llm.gemini import GeminiLlmProvider
from hbd.providers.llm.openai_compat import DEFAULT_BASE_URL, OpenAiCompatLlmProvider

__all__ = ["build_llm_provider", "build_fallback_llm_provider"]


def _build(
    *,
    provider: str,
    api_key: str,
    base_url: str,
    model_id: str,
    client: httpx.AsyncClient | None,
) -> LlmProvider:
    if provider == "gemini":
        return GeminiLlmProvider(
            api_key=api_key, base_url=base_url, model_id=model_id, client=client
        )
    return OpenAiCompatLlmProvider(
        api_key=api_key, base_url=base_url, model_id=model_id, client=client
    )


def build_llm_provider(
    settings: Settings, *, client: httpx.AsyncClient | None = None
) -> LlmProvider:
    """The primary provider. Raises ``ConfigError`` only when the key is missing."""
    if not settings.llm_api_key:
        raise ConfigError(
            "HBD_LLM_API_KEY is required to build the primary LLM provider",
            context={"model_id": settings.llm_model_id},
        )
    return _build(
        provider=settings.llm_provider,
        api_key=settings.llm_api_key,
        base_url=settings.llm_base_url,
        model_id=settings.llm_model_id,
        client=client,
    )


def build_fallback_llm_provider(
    settings: Settings, *, client: httpx.AsyncClient | None = None
) -> LlmProvider | None:
    """The documented fallback, or ``None`` when no fallback key is configured.

    Returning ``None`` rather than raising is deliberate: running without a fallback is a
    supported posture, and the caller decides whether that is acceptable today.
    """
    if not settings.llm_fallback_api_key:
        return None
    provider = settings.llm_fallback_provider
    # An unset fallback host means "the usual home of that adapter": Google's endpoint for
    # Gemini, OpenAI's for the compatible one. HBD_LLM_FALLBACK_BASE_URL overrides both,
    # which is what makes a self-hosted OpenAI-compatible gateway configurable at all.
    default_host = settings.llm_base_url if provider == "gemini" else DEFAULT_BASE_URL
    return _build(
        provider=provider,
        api_key=settings.llm_fallback_api_key,
        base_url=settings.llm_fallback_base_url or default_host,
        model_id=settings.llm_fallback_model_id,
        client=client,
    )
