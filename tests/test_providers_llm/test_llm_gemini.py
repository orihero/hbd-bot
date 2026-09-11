"""The Gemini adapter: request shape, payload reading, refusals, health."""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest
from pydantic import BaseModel, Field

from bayram.contracts import Err, HealthState, LlmProvider, LlmRequest, Ok
from bayram.errors import ErrorCode
from bayram.providers.llm.gemini import GeminiLlmProvider
from tests.test_providers_llm.conftest import gemini_response, mock_client


class Sample(BaseModel):
    name: str = Field(min_length=1)


REQUEST = LlmRequest(system_prompt="be brief", user_prompt="name a person")


def provider(handler: Any) -> GeminiLlmProvider:
    return GeminiLlmProvider(
        api_key="test-key",
        base_url="https://gemini.example/",
        model_id="gemini-3.7-flash",
        client=mock_client(handler),
    )


def json_responder(payload: dict[str, Any], status: int = 200) -> Any:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(status, json=payload)

    return handler


# ---------------------------------------------------------------------------
# Contract conformance
# ---------------------------------------------------------------------------
def test_satisfies_the_llm_provider_protocol_structurally() -> None:
    assert isinstance(provider(json_responder({})), LlmProvider)


# ---------------------------------------------------------------------------
# Request shape — structured mode is requested, not hoped for
# ---------------------------------------------------------------------------
async def test_requests_json_mode_with_a_response_schema() -> None:
    # Arrange
    captured: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured.update(json.loads(request.content))
        return httpx.Response(200, json=gemini_response('{"name": "Alyona"}'))

    # Act
    await provider(handler).generate_json(REQUEST, Sample, timeout_s=5.0)

    # Assert
    config = captured["generationConfig"]
    assert config["responseMimeType"] == "application/json"
    assert config["responseSchema"]["type"] == "object"
    assert "$defs" not in json.dumps(config["responseSchema"])


async def test_sends_the_system_prompt_and_generation_settings_from_the_request() -> None:
    captured: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured.update(json.loads(request.content))
        return httpx.Response(200, json=gemini_response('{"name": "Alyona"}'))

    await provider(handler).generate_json(REQUEST, Sample, timeout_s=5.0)

    assert captured["systemInstruction"]["parts"][0]["text"] == "be brief"
    assert captured["contents"][0]["parts"][0]["text"] == "name a person"
    # The request is the single authority on generation settings; the adapter holds none.
    assert captured["generationConfig"]["temperature"] == pytest.approx(REQUEST.temperature)
    assert captured["generationConfig"]["maxOutputTokens"] == REQUEST.max_output_tokens


async def test_sends_the_api_key_in_the_google_header_and_never_in_the_url() -> None:
    seen: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["header"] = request.headers.get("x-goog-api-key")
        seen["url"] = str(request.url)
        return httpx.Response(200, json=gemini_response('{"name": "A"}'))

    await provider(handler).generate_json(REQUEST, Sample, timeout_s=5.0)

    assert seen["header"] == "test-key"
    assert "test-key" not in seen["url"]


async def test_targets_the_configured_model_and_strips_a_trailing_slash_from_the_base_url() -> None:
    seen: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        return httpx.Response(200, json=gemini_response('{"name": "A"}'))

    await provider(handler).generate_json(REQUEST, Sample, timeout_s=5.0)

    assert seen["url"] == ("https://gemini.example/v1beta/models/gemini-3.7-flash:generateContent")


# ---------------------------------------------------------------------------
# Reading the response
# ---------------------------------------------------------------------------
async def test_returns_a_validated_model_from_the_candidate_text() -> None:
    result = await provider(json_responder(gemini_response('{"name": "Gʻulomjon"}'))).generate_json(
        REQUEST, Sample, timeout_s=5.0
    )

    assert isinstance(result, Ok)
    assert result.value.name == "Gʻulomjon"


async def test_joins_multiple_text_parts_before_parsing() -> None:
    payload = {
        "candidates": [
            {
                "content": {"parts": [{"text": '{"name": "Al'}, {"text": 'yona"}'}]},
                "finishReason": "STOP",
            }
        ]
    }

    result = await provider(json_responder(payload)).generate_json(REQUEST, Sample, timeout_s=5.0)

    assert isinstance(result, Ok)
    assert result.value.name == "Alyona"


async def test_still_parses_a_response_truncated_at_the_token_cap() -> None:
    payload = gemini_response('{"name": "Alyona"', finish_reason="MAX_TOKENS")

    result = await provider(json_responder(payload)).generate_json(REQUEST, Sample, timeout_s=5.0)

    assert isinstance(result, Ok)


async def test_returns_a_parse_error_carrying_the_finish_reason() -> None:
    payload = gemini_response("here are some thoughts instead", finish_reason="STOP")

    result = await provider(json_responder(payload)).generate_json(REQUEST, Sample, timeout_s=5.0)

    assert isinstance(result, Err)
    assert result.error.error_code is ErrorCode.PARSE_FAILED
    assert result.error.context["finish_reason"] == "STOP"


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"candidates": []},
        {"candidates": [{"content": {}}]},
        {"candidates": [{"content": {"parts": []}}]},
        {"candidates": [{"content": {"parts": [{"inlineData": "x"}]}}]},
        {"candidates": "not-a-list"},
    ],
)
async def test_a_structurally_surprising_body_is_an_err_not_a_crash(payload: Any) -> None:
    result = await provider(json_responder(payload)).generate_json(REQUEST, Sample, timeout_s=5.0)

    assert isinstance(result, Err)


# ---------------------------------------------------------------------------
# Refusals
# ---------------------------------------------------------------------------
async def test_a_prompt_block_is_a_terminal_content_rejection() -> None:
    payload = {"promptFeedback": {"blockReason": "SAFETY"}}

    result = await provider(json_responder(payload)).generate_json(REQUEST, Sample, timeout_s=5.0)

    assert isinstance(result, Err)
    assert result.error.error_code is ErrorCode.CONTENT_REJECTED
    assert result.error.is_retryable is False


async def test_a_safety_finish_reason_is_a_content_rejection_not_a_parse_failure() -> None:
    payload = gemini_response("", finish_reason="SAFETY")

    result = await provider(json_responder(payload)).generate_json(REQUEST, Sample, timeout_s=5.0)

    assert isinstance(result, Err)
    assert result.error.error_code is ErrorCode.CONTENT_REJECTED


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------
async def test_health_is_healthy_when_the_model_endpoint_answers() -> None:
    result = await provider(json_responder({"name": "models/gemini-3.7-flash"})).health()

    assert isinstance(result, Ok)
    assert result.value.state is HealthState.HEALTHY
    assert result.value.name == "gemini"


async def test_health_reports_degraded_for_a_retryable_failure() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, text="unavailable")

    result = await provider(handler).health()

    assert isinstance(result, Ok)
    assert result.value.state is HealthState.DEGRADED
    assert result.value.detail


async def test_health_reports_unavailable_for_a_terminal_failure() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, text="invalid api key")

    result = await provider(handler).health()

    assert isinstance(result, Ok)
    assert result.value.state is HealthState.UNAVAILABLE


async def test_a_transport_failure_is_returned_untouched_by_the_adapter() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, text="unavailable")

    result = await provider(handler).generate_json(REQUEST, Sample, timeout_s=5.0)

    assert isinstance(result, Err)
    assert result.error.error_code is ErrorCode.UPSTREAM_5XX
    assert result.error.is_retryable is True


async def test_an_unfamiliar_finish_reason_is_logged_but_still_parsed() -> None:
    payload = gemini_response('{"name": "Alyona"}', finish_reason="OTHER")

    result = await provider(json_responder(payload)).generate_json(REQUEST, Sample, timeout_s=5.0)

    assert isinstance(result, Ok)
