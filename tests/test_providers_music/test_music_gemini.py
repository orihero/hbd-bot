"""Tests for GeminiMusicProvider using httpx.MockTransport. No socket opened."""

from __future__ import annotations

import base64
from typing import Any

import httpx
import orjson
import pytest

from bayram.contracts import CostSource, HealthState, Vendor, is_err, is_ok
from bayram.errors import (
    ProviderInvalidResponseError,
    ProviderQuotaExhaustedError,
    ProviderRateLimitedError,
    ProviderRejectedContentError,
    ProviderUnavailableError,
)
from bayram.providers.music.gemini import (
    API_KEY_HEADER,
    LYRIA_USD_PER_REQUEST,
    PROVIDER_NAME,
    GeminiMusicProvider,
    build_gemini_music_prompt,
)
from bayram.usage import LOGGING_USAGE_SINK, VendorUsage
from tests.test_providers_music.conftest import (
    AUDIO_BODY,
    simple_plan,
)

TEST_GEMINI_KEY = "test-gemini-api-key"
TEST_BASE_URL = "https://generativelanguage.test"
TEST_MODEL_ID = "lyria-3.5"


def gemini_audio_response(
    *,
    status: int = 200,
    audio_bytes: bytes = AUDIO_BODY,
    finish_reason: str = "STOP",
    block_reason: str | None = None,
    include_audio: bool = True,
    corrupt_audio: bool = False,
    prompt_tokens: int = 150,
    candidates_tokens: int = 1000,
) -> httpx.Response:
    parts: list[dict[str, Any]] = [{"text": "Lyrics and music generated successfully."}]
    if include_audio:
        if corrupt_audio:
            b64_str = "not_valid_base64_!@#"
        else:
            b64_str = base64.b64encode(audio_bytes).decode("ascii")
        parts.append({"inlineData": {"mimeType": "audio/mpeg", "data": b64_str}})

    body: dict[str, Any] = {
        "candidates": [
            {
                "content": {"parts": parts, "role": "model"},
                "finishReason": finish_reason,
            }
        ],
        "usageMetadata": {
            "promptTokenCount": prompt_tokens,
            "candidatesTokenCount": candidates_tokens,
            "totalTokenCount": prompt_tokens + candidates_tokens,
        },
    }
    if block_reason is not None:
        body["promptFeedback"] = {"blockReason": block_reason}

    return httpx.Response(
        status_code=status,
        content=orjson.dumps(body),
        headers={"content-type": "application/json"},
    )


class CollectingSink:
    def __init__(self) -> None:
        self.rows: list[VendorUsage] = []

    async def record(self, usage: VendorUsage) -> None:
        self.rows.append(usage)


def gemini_provider(
    handler: Any,
    *,
    usd_per_request: float | None = None,
    max_concurrency: int = 2,
    model_id: str = TEST_MODEL_ID,
    usage: CollectingSink | None = None,
) -> GeminiMusicProvider:
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return GeminiMusicProvider(
        api_key=TEST_GEMINI_KEY,
        base_url=TEST_BASE_URL,
        model_id=model_id,
        max_concurrency=max_concurrency,
        usd_per_request=usd_per_request,
        client=client,
        usage=usage if usage is not None else LOGGING_USAGE_SINK,
    )


async def test_gemini_compose_success() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return gemini_audio_response()

    provider = gemini_provider(handler)
    plan = simple_plan()
    result = await provider.compose(plan, idempotency_key="gemini-idemp-1", timeout_s=10.0)

    assert is_ok(result)
    assert result.value.data == AUDIO_BODY
    assert result.value.mime == "audio/mpeg"
    assert result.value.remote_id is None
    assert result.value.duration_s == 48.0
    # Lyria bills per request, not per minute: a 48 s song costs the flat $0.08.
    assert result.value.cost_usd == pytest.approx(0.08)
    assert result.value.cost_source is CostSource.ESTIMATED

    assert len(seen) == 1
    assert seen[0].headers[API_KEY_HEADER] == TEST_GEMINI_KEY
    assert "/v1beta/interactions" in str(
        seen[0].url
    ) or f"/models/{TEST_MODEL_ID}:generateContent" in str(seen[0].url)


async def test_build_gemini_music_prompt() -> None:
    plan = simple_plan(name_text="Gʻulomjon")
    prompt = build_gemini_music_prompt(plan)
    assert "uzbek pop" in prompt
    assert "Gʻulomjon" in prompt
    assert "Lyrics:" in prompt
    assert "Duration:" in prompt


async def test_gemini_inpaint_recomposes_plan() -> None:
    provider = gemini_provider(lambda req: gemini_audio_response())
    plan = simple_plan()
    result = await provider.inpaint(
        plan,
        source_song_id="unused",
        chunk_index=1,
        idempotency_key="inpaint-idemp-1",
        timeout_s=10.0,
    )

    assert is_ok(result)
    assert result.value.data == AUDIO_BODY
    assert result.value.remote_id is None


async def test_gemini_safety_refusal() -> None:
    provider = gemini_provider(lambda req: gemini_audio_response(finish_reason="SAFETY"))
    result = await provider.compose(simple_plan(), idempotency_key="k", timeout_s=5.0)

    assert is_err(result)
    assert isinstance(result.error, ProviderRejectedContentError)


async def test_gemini_missing_audio_inline_data() -> None:
    provider = gemini_provider(lambda req: gemini_audio_response(include_audio=False))
    result = await provider.compose(simple_plan(), idempotency_key="k", timeout_s=5.0)

    assert is_err(result)
    assert isinstance(result.error, ProviderInvalidResponseError)


async def test_gemini_rate_limit_429() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            429,
            content=b'{"error": {"message": "Resource has been exhausted"}}',
            headers={"content-type": "application/json", "retry-after": "5"},
        )

    provider = gemini_provider(handler)
    result = await provider.compose(simple_plan(), idempotency_key="k", timeout_s=5.0)

    assert is_err(result)
    assert isinstance(result.error, ProviderRateLimitedError)


async def test_gemini_server_error_500() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, content=b"Internal server error")

    provider = gemini_provider(handler)
    result = await provider.compose(simple_plan(), idempotency_key="k", timeout_s=5.0)

    assert is_err(result)
    assert isinstance(result.error, ProviderUnavailableError)


async def test_gemini_health_ok() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b'{"name": "models/lyria-3.5"}')

    provider = gemini_provider(handler)
    health = await provider.health()

    assert is_ok(health)
    assert health.value.state is HealthState.HEALTHY
    assert health.value.name == PROVIDER_NAME


async def test_gemini_health_auth_failure() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, content=b'{"error": "API key not valid"}')

    provider = gemini_provider(handler)
    health = await provider.health()

    assert is_err(health)


async def test_gemini_interactions_response() -> None:
    b64_audio = base64.b64encode(AUDIO_BODY).decode("ascii")
    interactions_payload = {
        "steps": [
            {
                "type": "model_output",
                "content": [{"type": "text", "text": "Song ready"}],
            },
            {
                "type": "model_output",
                "content": [{"type": "audio", "mime_type": "audio/mpeg", "data": b64_audio}],
            },
        ],
        "usage": {"total_input_tokens": 15, "total_output_tokens": 120},
    }

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            content=orjson.dumps(interactions_payload),
            headers={"content-type": "application/json"},
        )

    provider = gemini_provider(handler)
    result = await provider.compose(simple_plan(), idempotency_key="interact-1", timeout_s=10.0)

    assert is_ok(result)
    assert result.value.data == AUDIO_BODY
    assert result.value.mime == "audio/mpeg"


async def test_gemini_price_is_per_request_whatever_the_duration() -> None:
    sink = CollectingSink()
    provider = gemini_provider(lambda _r: gemini_audio_response(), usage=sink)
    long_plan = simple_plan()
    long_plan = long_plan.model_copy(
        update={"chunks": [c.model_copy(update={"duration_ms": 150_000}) for c in long_plan.chunks]}
    )

    result = await provider.compose(long_plan, idempotency_key="k", timeout_s=5.0)

    assert is_ok(result)
    assert result.value.cost_usd == pytest.approx(0.08)
    assert sink.rows[-1].cost_usd == pytest.approx(0.08)
    assert sink.rows[-1].cost_source is CostSource.ESTIMATED


@pytest.mark.parametrize(
    ("model_id", "expected"),
    [("lyria-3-clip-preview", 0.04), ("lyria-3-pro-preview", 0.08), ("LYRIA-3.5", 0.08)],
)
async def test_gemini_price_follows_the_model(model_id: str, expected: float) -> None:
    provider = gemini_provider(lambda _r: gemini_audio_response(), model_id=model_id)

    result = await provider.compose(simple_plan(), idempotency_key="k", timeout_s=5.0)

    assert is_ok(result)
    assert result.value.cost_usd == pytest.approx(expected)
    assert LYRIA_USD_PER_REQUEST["lyria-3.5"] == 0.08


async def test_gemini_unknown_model_is_recorded_unpriced_not_guessed() -> None:
    sink = CollectingSink()
    provider = gemini_provider(
        lambda _r: gemini_audio_response(), model_id="lyria-9-experimental", usage=sink
    )

    result = await provider.compose(simple_plan(), idempotency_key="k", timeout_s=5.0)

    assert is_ok(result)
    assert sink.rows[-1].cost_usd is None
    assert sink.rows[-1].cost_source is None


async def test_gemini_price_override_wins_over_the_table() -> None:
    provider = gemini_provider(lambda _r: gemini_audio_response(), usd_per_request=0.05)

    result = await provider.compose(simple_plan(), idempotency_key="k", timeout_s=5.0)

    assert is_ok(result)
    assert result.value.cost_usd == pytest.approx(0.05)


async def test_gemini_failure_records_no_audio_and_no_cost() -> None:
    sink = CollectingSink()
    provider = gemini_provider(lambda _r: httpx.Response(500, content=b"boom"), usage=sink)

    result = await provider.compose(simple_plan(), idempotency_key="k", timeout_s=5.0)

    assert is_err(result)
    row = sink.rows[-1]
    assert row.vendor is Vendor.GEMINI
    assert row.is_success is False
    assert row.audio_ms is None
    assert row.cost_usd is None


async def test_gemini_402_is_quota_exhausted() -> None:
    provider = gemini_provider(
        lambda _r: httpx.Response(402, content=b'{"error": {"message": "payment required"}}')
    )

    result = await provider.compose(simple_plan(), idempotency_key="k", timeout_s=5.0)

    assert is_err(result)
    assert isinstance(result.error, ProviderQuotaExhaustedError)


async def test_gemini_429_with_depleted_prepay_is_quota_exhausted_not_rate_limit() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            429,
            content=b'{"error": {"code": 429, "message": "Your prepayment credits are depleted."}}',
            headers={"content-type": "application/json"},
        )

    provider = gemini_provider(handler)
    result = await provider.compose(simple_plan(), idempotency_key="k", timeout_s=5.0)

    assert is_err(result)
    assert isinstance(result.error, ProviderQuotaExhaustedError)
    assert result.error.is_retryable is False
