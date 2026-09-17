"""Build the configured LLM provider(s) from ``Settings``.

Which vendor answers is a configuration decision, and the two adapters are behind the
identical contract, so this is the only place in the system that names either of them.

The choice is now *declared*, not inferred: ``BAYRAM_LLM_PROVIDER`` and
``BAYRAM_LLM_FALLBACK_PROVIDER`` name the adapter outright. An earlier revision guessed it
from a ``gemini-*`` model-id prefix, which quietly routed a self-hosted Gemini-compatible
gateway to the wrong transport. Guessing a vendor from a string is exactly the kind of
implicit rule this project keeps in config instead.

One thing IS derived here, and the distinction matters: the *billing* identity
(:class:`bayram.contracts.Vendor`) comes from the base URL's host. That is not a guess about
behaviour — the adapter is chosen by the setting, and nothing about the request changes
except which host it is addressed to. It is a statement about who sends the invoice, and
the host is the only fact in the configuration that knows. ``BAYRAM_LLM_PROVIDER=openai``
pointed at ``openrouter.ai`` is an OpenRouter bill however the wire format is spelled, and
a fifth setting asking a deployment to restate its own hostname would just be one more
thing to get out of step with the URL beside it.

The rate cards are read here for the same reason the adapters are: they arrive as four
settings that are read once at startup and then frozen onto the instance. Nothing about
pricing is live-editable — editing a rate mid-flight silently rewrites the meaning of
every future row against a ``cost_source`` that still claims "derived".
"""

from __future__ import annotations

from typing import Final
from urllib.parse import urlsplit

import httpx

from bayram.config import Settings
from bayram.contracts import LlmProvider, Vendor
from bayram.errors import ConfigError
from bayram.providers.llm.gemini import GeminiLlmProvider
from bayram.providers.llm.openai_compat import DEFAULT_BASE_URL, OpenAiCompatLlmProvider
from bayram.providers.llm.pricing import TokenPricing
from bayram.usage import LOGGING_USAGE_SINK, UsageSink

__all__ = ["build_llm_provider", "build_fallback_llm_provider"]

#: Registered domains whose invoices are not the generic OpenAI-compatible one. Matched on
#: the host itself or any subdomain of it, so a regional endpoint still bills to the same
#: account. Everything absent from this table is :data:`Vendor.OPENAI_COMPATIBLE`, which is
#: the honest answer for a self-hosted or third-party gateway: the protocol is OpenAI's,
#: the billing relationship is unknown to us, and ``usage.cost`` is not on offer.
_VENDOR_DOMAINS: Final[tuple[tuple[str, Vendor], ...]] = (
    ("openrouter.ai", Vendor.OPENROUTER),
    ("generativelanguage.googleapis.com", Vendor.GEMINI),
)


def _host_of(base_url: str) -> str:
    """The lowercased host of a configured base URL, or ``""`` when it has none.

    Tolerates a scheme-less value (``openrouter.ai/api``) because a base URL is typed by
    hand into an ``.env`` file and ``urlsplit`` would otherwise read the whole thing as a
    path and report no host at all.
    """
    candidate = base_url.strip()
    if "//" not in candidate:
        candidate = f"//{candidate}"
    return (urlsplit(candidate).hostname or "").lower()


def _vendor_for(base_url: str) -> Vendor:
    """Who bills for calls to this host. See the module docstring on why it is derived."""
    host = _host_of(base_url)
    for domain, vendor in _VENDOR_DOMAINS:
        if host == domain or host.endswith(f".{domain}"):
            return vendor
    return Vendor.OPENAI_COMPATIBLE


def _build(
    *,
    provider: str,
    api_key: str,
    base_url: str,
    model_id: str,
    client: httpx.AsyncClient | None,
    pricing: TokenPricing,
    usage: UsageSink,
    is_fallback: bool = False,
    is_reasoning_disabled: bool = False,
) -> LlmProvider:
    if provider == "gemini":
        # Not forwarded: the flag names an OpenRouter body field, and Gemini's own
        # thinking budget is a different knob on a different request shape. A Gemini
        # deployment that needs one gets its own setting rather than an overloaded name.
        return GeminiLlmProvider(
            api_key=api_key,
            base_url=base_url,
            model_id=model_id,
            client=client,
            is_fallback=is_fallback,
            pricing=pricing,
            usage=usage,
        )
    return OpenAiCompatLlmProvider(
        api_key=api_key,
        base_url=base_url,
        model_id=model_id,
        client=client,
        is_reasoning_disabled=is_reasoning_disabled,
        vendor=_vendor_for(base_url),
        is_fallback=is_fallback,
        pricing=pricing,
        usage=usage,
    )


def build_llm_provider(
    settings: Settings,
    *,
    client: httpx.AsyncClient | None = None,
    usage: UsageSink = LOGGING_USAGE_SINK,
) -> LlmProvider:
    """The primary provider. Raises ``ConfigError`` only when the key is missing."""
    if not settings.llm_api_key:
        raise ConfigError(
            "BAYRAM_LLM_API_KEY is required to build the primary LLM provider",
            context={"model_id": settings.llm_model_id},
        )
    return _build(
        provider=settings.llm_provider,
        api_key=settings.llm_api_key,
        base_url=settings.llm_base_url,
        model_id=settings.llm_model_id,
        client=client,
        pricing=TokenPricing(
            usd_per_million_prompt=settings.llm_usd_per_million_prompt_tokens,
            usd_per_million_completion=settings.llm_usd_per_million_completion_tokens,
        ),
        usage=usage,
        is_reasoning_disabled=settings.llm_disable_reasoning,
    )


def build_fallback_llm_provider(
    settings: Settings,
    *,
    client: httpx.AsyncClient | None = None,
    usage: UsageSink = LOGGING_USAGE_SINK,
) -> LlmProvider | None:
    """The documented fallback, or ``None`` when no fallback key is configured.

    Returning ``None`` rather than raising is deliberate: running without a fallback is a
    supported posture, and the caller decides whether that is acceptable today.

    The instance is stamped ``is_fallback=True``, which is the fact that finally makes the
    second OpenRouter account visible. Both instances answer to the same adapter name, so
    without the flag their spend is one undifferentiated number and "what is the failover
    costing us" cannot be asked at all.
    """
    if not settings.llm_fallback_api_key:
        return None
    provider = settings.llm_fallback_provider
    # An unset fallback host means "the usual home of that adapter": Google's endpoint for
    # Gemini, OpenAI's for the compatible one. BAYRAM_LLM_FALLBACK_BASE_URL overrides both,
    # which is what makes a self-hosted OpenAI-compatible gateway configurable at all.
    default_host = settings.llm_base_url if provider == "gemini" else DEFAULT_BASE_URL
    return _build(
        provider=provider,
        api_key=settings.llm_fallback_api_key,
        base_url=settings.llm_fallback_base_url or default_host,
        model_id=settings.llm_fallback_model_id,
        client=client,
        pricing=TokenPricing(
            usd_per_million_prompt=settings.llm_fallback_usd_per_million_prompt_tokens,
            usd_per_million_completion=settings.llm_fallback_usd_per_million_completion_tokens,
        ),
        usage=usage,
        is_fallback=True,
        is_reasoning_disabled=settings.llm_disable_reasoning,
    )
