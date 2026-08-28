"""The fallback adapter. Same contract, same promises, a different wire dialect."""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest
from pydantic import BaseModel, Field

from hbd.contracts import Err, HealthState, LlmProvider, LlmRequest, Ok
from hbd.errors import ErrorCode
from hbd.providers.llm.openai_compat import OpenAiCompatLlmProvider
from tests.test_providers_llm.conftest import mock_client, openai_response


class Sample(BaseModel):
    name: str = Field(min_length=1)


REQUEST = LlmRequest(system_prompt="be brief", user_prompt="name a person")


def provider(handler: Any) -> OpenAiCompatLlmProvider:
    return OpenAiCompatLlmProvider(
        api_key="test-key",
        base_url="https://luna.example",
        model_id="gpt-5.6-luna",
        client=mock_client(handler),
    )


def json_responder(payload: dict[str, Any]) -> Any:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=payload)

    return handler


def test_satisfies_the_llm_provider_protocol_structurally() -> None:
    assert isinstance(provider(json_responder({})), LlmProvider)


# ---------------------------------------------------------------------------
# Request shape
# ---------------------------------------------------------------------------
async def test_requests_strict_json_schema_mode() -> None:
    captured: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured.update(json.loads(request.content))
        return httpx.Response(200, json=openai_response('{"name": "Alyona"}'))

    await provider(handler).generate_json(REQUEST, Sample, timeout_s=5.0)

    response_format = captured["response_format"]
    assert response_format["type"] == "json_schema"
    assert response_format["json_schema"]["strict"] is True
    assert response_format["json_schema"]["schema"]["additionalProperties"] is False


async def test_sends_system_and_user_messages_and_a_bearer_token() -> None:
    captured: dict[str, Any] = {}
    seen: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured.update(json.loads(request.content))
        seen["auth"] = request.headers.get("authorization")
        seen["url"] = str(request.url)
        return httpx.Response(200, json=openai_response('{"name": "Alyona"}'))

    await provider(handler).generate_json(REQUEST, Sample, timeout_s=5.0)

    assert captured["messages"][0] == {"role": "system", "content": "be brief"}
    assert captured["messages"][1] == {"role": "user", "content": "name a person"}
    assert captured["model"] == "gpt-5.6-luna"
    assert seen["auth"] == "Bearer test-key"
    assert seen["url"] == "https://luna.example/v1/chat/completions"


# ---------------------------------------------------------------------------
# Reading the response
# ---------------------------------------------------------------------------
async def test_returns_a_validated_model_from_the_message_content() -> None:
    result = await provider(json_responder(openai_response('{"name": "Alyona"}'))).generate_json(
        REQUEST, Sample, timeout_s=5.0
    )

    assert isinstance(result, Ok)
    assert result.value.name == "Alyona"


async def test_recovers_a_fenced_object_the_model_wrapped_despite_strict_mode() -> None:
    payload = openai_response('```json\n{"name": "Alyona"}\n```')

    result = await provider(json_responder(payload)).generate_json(REQUEST, Sample, timeout_s=5.0)

    assert isinstance(result, Ok)


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"choices": []},
        {"choices": [{"message": {}}]},
        {"choices": [{"message": {"content": None}}]},
        {"choices": "not-a-list"},
    ],
)
async def test_a_structurally_surprising_body_is_an_err_not_a_crash(payload: Any) -> None:
    result = await provider(json_responder(payload)).generate_json(REQUEST, Sample, timeout_s=5.0)

    assert isinstance(result, Err)
    assert result.error.error_code is ErrorCode.PARSE_FAILED


async def test_an_explicit_refusal_field_is_a_content_rejection() -> None:
    payload = {"choices": [{"message": {"refusal": "I cannot help with that"}}]}

    result = await provider(json_responder(payload)).generate_json(REQUEST, Sample, timeout_s=5.0)

    assert isinstance(result, Err)
    assert result.error.error_code is ErrorCode.CONTENT_REJECTED
    assert result.error.is_retryable is False


async def test_a_content_filter_stop_is_a_content_rejection() -> None:
    payload = openai_response("", finish_reason="content_filter")

    result = await provider(json_responder(payload)).generate_json(REQUEST, Sample, timeout_s=5.0)

    assert isinstance(result, Err)
    assert result.error.error_code is ErrorCode.CONTENT_REJECTED


async def test_a_length_stop_still_attempts_the_parse_and_recovers() -> None:
    payload = openai_response('{"name": "Alyona"', finish_reason="length")

    result = await provider(json_responder(payload)).generate_json(REQUEST, Sample, timeout_s=5.0)

    assert isinstance(result, Ok)


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------
async def test_health_is_healthy_when_the_models_endpoint_answers() -> None:
    result = await provider(json_responder({"data": []})).health()

    assert isinstance(result, Ok)
    assert result.value.state is HealthState.HEALTHY


async def test_health_is_degraded_when_rate_limited() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(429, text="slow down")

    result = await provider(handler).health()

    assert isinstance(result, Ok)
    assert result.value.state is HealthState.DEGRADED


async def test_a_transport_failure_is_returned_untouched_by_the_adapter() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(429, text="you exceeded your current quota")

    result = await provider(handler).generate_json(REQUEST, Sample, timeout_s=5.0)

    assert isinstance(result, Err)
    assert result.error.error_code is ErrorCode.QUOTA_EXHAUSTED
    assert result.error.is_retryable is False


# ---------------------------------------------------------------------------
# Base-URL normalisation (regression: a 404 against OpenRouter)
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "configured",
    [
        "https://openrouter.ai/api/v1",
        "https://openrouter.ai/api/v1/",
        "https://openrouter.ai/api",
    ],
)
def test_a_gateway_base_url_reaches_one_v1_however_it_was_written(configured: str) -> None:
    # Arrange / Act — gateways document their base URL WITH /v1 on it and this adapter
    # appends /v1 itself, so pasting the documented value produced /api/v1/v1/... and a
    # 404 whose HTML body then masked the cause completely.
    provider = OpenAiCompatLlmProvider(api_key="k", model_id="m", base_url=configured)

    # Assert
    assert provider._base_url == "https://openrouter.ai/api"


def test_a_plain_host_base_url_is_left_alone() -> None:
    # Arrange / Act
    provider = OpenAiCompatLlmProvider(api_key="k", model_id="m", base_url="https://api.openai.com")

    # Assert
    assert provider._base_url == "https://api.openai.com"
