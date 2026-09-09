"""Which vendor answers is a configuration decision, made in exactly one place.

The selector is explicit (``HBD_LLM_PROVIDER`` / ``HBD_LLM_FALLBACK_PROVIDER``). It used
to be inferred from a ``gemini-*`` model-id prefix; these tests now pin the declared
behaviour, including that the model id no longer changes the transport.
"""

from __future__ import annotations

import pytest

from hbd.config import Settings
from hbd.contracts import LlmProvider
from hbd.errors import ConfigError
from hbd.providers.llm.factory import build_fallback_llm_provider, build_llm_provider
from hbd.providers.llm.gemini import GeminiLlmProvider
from hbd.providers.llm.openai_compat import DEFAULT_BASE_URL, OpenAiCompatLlmProvider


def test_the_default_configuration_routes_to_the_openai_compatible_adapter(
    settings: Settings,
) -> None:
    # The default is OpenRouter, which speaks the OpenAI wire format — so the shipped
    # config selects that adapter with the base URL pointed elsewhere, not a new adapter.
    provider = build_llm_provider(settings)

    assert isinstance(provider, OpenAiCompatLlmProvider)
    assert isinstance(provider, LlmProvider)


def test_the_gemini_selector_still_routes_to_the_gemini_adapter(settings: Settings) -> None:
    # Gemini remains a first-class option; only the default moved.
    configured = settings.model_copy(
        update={"llm_provider": "gemini", "llm_model_id": "gemini-3.7-flash"}
    )

    assert isinstance(build_llm_provider(configured), GeminiLlmProvider)


def test_the_openai_selector_routes_to_the_openai_compatible_adapter(settings: Settings) -> None:
    configured = settings.model_copy(
        update={"llm_provider": "openai", "llm_model_id": "gpt-5.6-luna"}
    )

    provider = build_llm_provider(configured)

    assert isinstance(provider, OpenAiCompatLlmProvider)


@pytest.mark.parametrize("model_id", ["gemini-3.7-flash", "gpt-5.6-luna", "llama-4-scout"])
def test_the_model_id_no_longer_decides_the_transport(model_id: str, settings: Settings) -> None:
    # Arrange: selector says gemini, model id says anything at all.
    configured = settings.model_copy(update={"llm_provider": "gemini", "llm_model_id": model_id})

    # Act / Assert
    assert isinstance(build_llm_provider(configured), GeminiLlmProvider)


def test_an_unknown_selector_is_refused_by_config(settings: Settings) -> None:
    # Arrange / Act / Assert: the factory never sees a vendor it cannot build.
    with pytest.raises(ValueError):
        Settings(_env_file=None, **{**settings.model_dump(), "llm_provider": "anthropic"})


def test_a_missing_primary_key_is_a_config_error_naming_the_variable(
    settings: Settings,
) -> None:
    with pytest.raises(ConfigError, match="HBD_LLM_API_KEY"):
        build_llm_provider(settings.model_copy(update={"llm_api_key": ""}))


def test_no_fallback_is_built_when_no_fallback_key_is_configured(settings: Settings) -> None:
    # Running without a fallback is a supported posture, so this is None, not a raise.
    assert build_fallback_llm_provider(settings) is None


def test_the_default_fallback_is_the_openai_compatible_adapter(settings: Settings) -> None:
    configured = settings.model_copy(update={"llm_fallback_api_key": "fallback-key"})

    provider = build_fallback_llm_provider(configured)

    assert isinstance(provider, OpenAiCompatLlmProvider)
    assert isinstance(provider, LlmProvider)
    assert provider._base_url == DEFAULT_BASE_URL.rstrip("/")


def test_a_self_hosted_fallback_host_is_configurable(settings: Settings) -> None:
    # Arrange: the whole reason HBD_LLM_FALLBACK_BASE_URL exists.
    configured = settings.model_copy(
        update={
            "llm_fallback_api_key": "k",
            "llm_fallback_base_url": "https://gateway.internal",
        }
    )

    # Act
    provider = build_fallback_llm_provider(configured)

    # Assert
    assert isinstance(provider, OpenAiCompatLlmProvider)
    assert provider._base_url == "https://gateway.internal"


def test_a_gemini_fallback_selector_routes_to_the_gemini_adapter(settings: Settings) -> None:
    configured = settings.model_copy(
        update={
            "llm_fallback_api_key": "k",
            "llm_fallback_provider": "gemini",
            "llm_fallback_model_id": "gemini-2.5-flash",
        }
    )

    assert isinstance(build_fallback_llm_provider(configured), GeminiLlmProvider)


def test_two_different_adapters_expose_distinct_stable_names(settings: Settings) -> None:
    # Names are how a log line says which model answered, so two DIFFERENT adapters must
    # not share one. Stated with an explicit pair: primary and fallback now default to the
    # same adapter (both OpenRouter), which would make this assertion vacuous.
    primary = build_llm_provider(settings.model_copy(update={"llm_provider": "gemini"}))
    fallback = build_fallback_llm_provider(
        settings.model_copy(update={"llm_fallback_api_key": "k", "llm_fallback_provider": "openai"})
    )

    assert fallback is not None
    assert primary.name != fallback.name


def test_the_reasoning_switch_reaches_both_openai_compatible_providers(
    settings: Settings,
) -> None:
    """One setting, and the fallback is the half a per-provider flag would have missed.

    The failover exists to answer when the primary cannot, so a deployment that needs the
    switch needs it on the model it fails over TO — otherwise the fallback inherits exactly
    the truncation the primary was configured out of, and only under load.
    """
    # Arrange
    configured = settings.model_copy(
        update={
            "llm_disable_reasoning": True,
            "llm_fallback_api_key": "fallback-key",
            "llm_fallback_provider": "openai",
        }
    )

    # Act
    primary = build_llm_provider(configured)
    fallback = build_fallback_llm_provider(configured)

    # Assert
    assert isinstance(primary, OpenAiCompatLlmProvider)
    assert isinstance(fallback, OpenAiCompatLlmProvider)
    assert primary._is_reasoning_disabled is True
    assert fallback._is_reasoning_disabled is True


def test_the_reasoning_switch_is_off_by_default(settings: Settings) -> None:
    # Arrange / Act
    provider = build_llm_provider(settings)

    # Assert
    assert isinstance(provider, OpenAiCompatLlmProvider)
    assert provider._is_reasoning_disabled is False
