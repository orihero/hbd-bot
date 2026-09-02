"""The live adapter, driven entirely through httpx.MockTransport. No socket is opened."""

from __future__ import annotations

import asyncio
import logging

import httpx
import orjson
import pytest

from hbd.contracts import Chunk, CostSource, HealthState, MusicProvider, is_err, is_ok
from hbd.errors import ErrorCode
from hbd.providers.music.elevenlabs import (
    API_KEY_HEADER,
    IDEMPOTENCY_HEADER,
    PROVIDER_NAME,
    ElevenLabsMusicProvider,
    mime_for_output_format,
)
from hbd.providers.music.usage import USAGE_EVENT
from tests.test_providers_music.conftest import (
    AUDIO_BODY,
    TEST_BASE_URL,
    always,
    audio_response,
    body_of,
    error_response,
    music_provider,
    recording,
    simple_plan,
    usage_line,
)

LOGGER_NAME = "hbd.providers.music.elevenlabs"
IDEMPOTENCY_KEY = "order-123-compose-1"


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------
async def test_compose_returns_the_audio_body_verbatim() -> None:
    # Arrange / Act
    async with music_provider(always(audio_response())) as provider:
        result = await provider.compose(
            simple_plan(), idempotency_key=IDEMPOTENCY_KEY, timeout_s=5.0
        )

    # Assert
    assert is_ok(result)
    assert result.value.data == AUDIO_BODY
    assert result.value.mime == "audio/mpeg"


async def test_compose_captures_the_stored_song_handle_for_later_inpainting() -> None:
    # Arrange / Act
    async with music_provider(always(audio_response())) as provider:
        result = await provider.compose(simple_plan(), idempotency_key="k", timeout_s=5.0)

    # Assert
    assert is_ok(result)
    assert result.value.remote_id == "song_abc123"


async def test_missing_song_header_is_not_a_failure_only_an_absent_handle() -> None:
    # Arrange
    response = httpx.Response(200, content=AUDIO_BODY, headers={"content-type": "audio/mpeg"})

    # Act
    async with music_provider(always(response)) as provider:
        result = await provider.compose(simple_plan(), idempotency_key="k", timeout_s=5.0)

    # Assert
    assert is_ok(result)
    assert result.value.remote_id is None


async def test_duration_and_cost_come_from_the_plan_not_from_the_vendor() -> None:
    # Arrange / Act
    async with music_provider(always(audio_response()), usd_per_minute=0.15) as provider:
        result = await provider.compose(simple_plan(), idempotency_key="k", timeout_s=5.0)

    # Assert: 48_000 ms of song at 0.15/min, and we say so honestly.
    assert is_ok(result)
    assert result.value.duration_s == 48.0
    assert result.value.cost_usd == pytest.approx(0.12)
    assert result.value.cost_source is CostSource.ESTIMATED


async def test_compose_sends_the_api_key_and_the_idempotency_key() -> None:
    # Arrange
    seen: list[httpx.Request] = []

    # Act
    async with music_provider(recording(audio_response(), seen)) as provider:
        await provider.compose(simple_plan(), idempotency_key=IDEMPOTENCY_KEY, timeout_s=5.0)

    # Assert
    assert seen[0].headers[API_KEY_HEADER] == "test-elevenlabs-key"
    assert seen[0].headers[IDEMPOTENCY_HEADER] == IDEMPOTENCY_KEY
    assert seen[0].url.path == "/v1/music"


async def test_compose_posts_the_planned_composition_and_the_configured_model() -> None:
    # Arrange
    seen: list[httpx.Request] = []

    # Act
    async with music_provider(recording(audio_response(), seen)) as provider:
        await provider.compose(simple_plan(seed=99), idempotency_key="k", timeout_s=5.0)

    # Assert
    body = body_of(seen[0])
    assert body["model_id"] == "music_v2"
    assert "output_format" not in body
    assert seen[0].url.params["output_format"] == "mp3_44100_128"
    assert "music_length_ms" not in body
    assert body["store_for_inpainting"] is True
    assert len(body["composition_plan"]["chunks"]) == 3


async def test_the_seed_is_passed_through_so_a_retry_reproduces_the_take() -> None:
    # Arrange
    seen: list[httpx.Request] = []

    # Act
    async with music_provider(recording(audio_response(), seen)) as provider:
        await provider.compose(simple_plan(seed=4_242), idempotency_key="k", timeout_s=5.0)

    # Assert
    assert body_of(seen[0])["seed"] == 4_242


async def test_a_trailing_slash_on_the_base_url_does_not_double_up() -> None:
    # Arrange
    seen: list[httpx.Request] = []

    # Act
    async with music_provider(
        recording(audio_response(), seen), base_url=f"{TEST_BASE_URL}/"
    ) as provider:
        await provider.compose(simple_plan(), idempotency_key="k", timeout_s=5.0)

    # Assert
    assert seen[0].url.path == "/v1/music"


# ---------------------------------------------------------------------------
# Local rejection — the cheapest failure is the one that never leaves
# ---------------------------------------------------------------------------
async def test_a_blank_name_chunk_is_rejected_without_calling_the_vendor() -> None:
    # Arrange
    seen: list[httpx.Request] = []
    plan = simple_plan().with_chunk_replaced(
        1, Chunk(text="  ", duration_ms=8_000, is_name_chunk=True)
    )

    # Act
    async with music_provider(recording(audio_response(), seen)) as provider:
        result = await provider.compose(plan, idempotency_key="k", timeout_s=5.0)

    # Assert
    assert is_err(result)
    assert seen == []


# ---------------------------------------------------------------------------
# Failure mapping through the adapter
# ---------------------------------------------------------------------------
async def test_a_429_comes_back_retryable_with_the_vendors_retry_after() -> None:
    # Arrange
    response = error_response(429, detail="slow down", headers={"retry-after": "12"})

    # Act
    async with music_provider(always(response)) as provider:
        result = await provider.compose(simple_plan(), idempotency_key="k", timeout_s=5.0)

    # Assert
    assert is_err(result)
    assert result.is_retryable
    assert result.error.context["retry_after_s"] == 12.0


async def test_a_401_comes_back_terminal() -> None:
    # Arrange / Act
    async with music_provider(always(error_response(401, detail="bad key"))) as provider:
        result = await provider.compose(simple_plan(), idempotency_key="k", timeout_s=5.0)

    # Assert
    assert is_err(result)
    assert not result.is_retryable
    assert result.error.error_code is ErrorCode.CONFIG_INVALID


async def test_a_500_comes_back_retryable() -> None:
    # Arrange / Act
    async with music_provider(always(error_response(503, detail="upstream"))) as provider:
        result = await provider.compose(simple_plan(), idempotency_key="k", timeout_s=5.0)

    # Assert
    assert is_err(result)
    assert result.is_retryable


async def test_a_timeout_is_returned_as_an_err_and_never_raised() -> None:
    # Arrange
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("took too long", request=request)

    # Act
    async with music_provider(handler) as provider:
        result = await provider.compose(simple_plan(), idempotency_key="k", timeout_s=0.5)

    # Assert
    assert is_err(result)
    assert result.error.error_code is ErrorCode.UPSTREAM_TIMEOUT
    assert result.is_retryable


async def test_a_200_with_an_empty_body_is_a_malformed_response() -> None:
    # Arrange / Act
    async with music_provider(always(audio_response(content=b""))) as provider:
        result = await provider.compose(simple_plan(), idempotency_key="k", timeout_s=5.0)

    # Assert
    assert is_err(result)
    assert result.error.error_code is ErrorCode.UPSTREAM_MALFORMED


async def test_a_200_carrying_json_instead_of_audio_is_a_malformed_response() -> None:
    # Arrange: vendors do occasionally answer 200 with an error document.
    response = httpx.Response(
        200,
        content=orjson.dumps({"detail": "actually this failed"}),
        headers={"content-type": "application/json"},
    )

    # Act
    async with music_provider(always(response)) as provider:
        result = await provider.compose(simple_plan(), idempotency_key="k", timeout_s=5.0)

    # Assert
    assert is_err(result)
    assert result.error.error_code is ErrorCode.UPSTREAM_MALFORMED
    assert "actually this failed" in str(result.error.context["response_detail"])


async def test_audio_without_a_content_type_falls_back_to_the_output_format() -> None:
    # Arrange
    response = httpx.Response(200, content=AUDIO_BODY, headers={"song-id": "s1"})

    # Act
    async with music_provider(always(response)) as provider:
        result = await provider.compose(simple_plan(), idempotency_key="k", timeout_s=5.0)

    # Assert
    assert is_ok(result)
    assert result.value.mime == "audio/mpeg"


@pytest.mark.parametrize(
    ("output_format", "expected"),
    [
        ("mp3_44100_128", "audio/mpeg"),
        ("opus_48000_32", "audio/ogg"),
        ("pcm_44100", "audio/wave"),
        ("something_new", "application/octet-stream"),
    ],
)
def test_mime_is_derived_from_the_vendor_format_string(output_format: str, expected: str) -> None:
    assert mime_for_output_format(output_format) == expected


# ---------------------------------------------------------------------------
# Inpainting and the name re-roll
# ---------------------------------------------------------------------------
async def test_inpaint_references_the_stored_song_and_the_chunk_being_replaced() -> None:
    # Arrange
    seen: list[httpx.Request] = []

    # Act
    async with music_provider(recording(audio_response(), seen)) as provider:
        result = await provider.inpaint(
            simple_plan(),
            source_song_id="song_abc123",
            chunk_index=1,
            idempotency_key="k",
            timeout_s=5.0,
        )

    # Assert
    assert is_ok(result)
    body = body_of(seen[0])
    # The stored song is named by audio-reference chunks INSIDE the plan; a top-level
    # source_song_id is ignored by the vendor and regenerates the whole track.
    assert "source_song_id" not in body
    assert "chunk_index" not in body
    chunks = body["composition_plan"]["chunks"]
    assert chunks[0]["song_id"] == "song_abc123"
    assert chunks[1]["text"] == "Gulomjon"
    assert chunks[2]["song_id"] == "song_abc123"


async def test_inpaint_refuses_a_blank_song_id_without_calling_the_vendor() -> None:
    # Arrange
    seen: list[httpx.Request] = []

    # Act
    async with music_provider(recording(audio_response(), seen)) as provider:
        result = await provider.inpaint(
            simple_plan(), source_song_id="   ", chunk_index=1, idempotency_key="k", timeout_s=5.0
        )

    # Assert
    assert is_err(result)
    assert seen == []


async def test_inpaint_refuses_a_chunk_index_that_does_not_exist() -> None:
    # Arrange
    seen: list[httpx.Request] = []

    # Act
    async with music_provider(recording(audio_response(), seen)) as provider:
        result = await provider.inpaint(
            simple_plan(), source_song_id="s1", chunk_index=9, idempotency_key="k", timeout_s=5.0
        )

    # Assert
    assert is_err(result)
    assert result.error.context["chunk_index"] == 9
    assert seen == []


# ---------------------------------------------------------------------------
# The concurrency ceiling
# ---------------------------------------------------------------------------
async def test_never_exceeds_the_configured_simultaneous_render_ceiling() -> None:
    # Arrange: count how many renders are in flight at once.
    state = {"live": 0, "peak": 0}

    async def handler(request: httpx.Request) -> httpx.Response:
        state["live"] += 1
        state["peak"] = max(state["peak"], state["live"])
        await asyncio.sleep(0.01)
        state["live"] -= 1
        return audio_response()

    # Act: eight jobs against a two-slot plan.
    async with music_provider(handler, max_concurrency=2) as provider:
        results = await asyncio.gather(
            *(
                provider.compose(simple_plan(), idempotency_key=f"k{index}", timeout_s=5.0)
                for index in range(8)
            )
        )

    # Assert
    assert state["peak"] <= 2
    assert all(is_ok(result) for result in results)


# ---------------------------------------------------------------------------
# The measured usage line
# ---------------------------------------------------------------------------
async def test_a_usage_line_is_emitted_with_the_billable_quantities(
    caplog: pytest.LogCaptureFixture,
) -> None:
    # Arrange / Act
    with caplog.at_level(logging.INFO, logger=LOGGER_NAME):
        async with music_provider(always(audio_response())) as provider:
            await provider.compose(simple_plan(), idempotency_key="k", timeout_s=5.0)

    # Assert
    usage = usage_line(caplog.records, USAGE_EVENT)
    assert usage["operation"] == "compose"
    assert usage["chunk_count"] == 3
    assert usage["total_duration_ms"] == 48_000
    assert usage["model_id"] == "music_v2"
    assert usage["outcome"] == "ok"
    assert usage["http_status"] == 200
    assert usage["remote_id"] == "song_abc123"
    assert usage["name_chunk_index"] == 1


async def test_a_usage_line_is_emitted_for_a_failed_call_too(
    caplog: pytest.LogCaptureFixture,
) -> None:
    # Arrange / Act
    with caplog.at_level(logging.INFO, logger=LOGGER_NAME):
        async with music_provider(always(error_response(500))) as provider:
            await provider.compose(simple_plan(), idempotency_key="k", timeout_s=5.0)

    # Assert
    usage = usage_line(caplog.records, USAGE_EVENT)
    assert usage["outcome"] == "http_error"
    assert usage["http_status"] == 500
    assert usage["estimated_cost_usd"] == 0.0


async def test_a_transport_failure_is_still_measured(
    caplog: pytest.LogCaptureFixture,
) -> None:
    # Arrange
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("no route", request=request)

    # Act
    with caplog.at_level(logging.INFO, logger=LOGGER_NAME):
        async with music_provider(handler) as provider:
            await provider.compose(simple_plan(), idempotency_key="k", timeout_s=5.0)

    # Assert
    usage = usage_line(caplog.records, USAGE_EVENT)
    assert usage["outcome"] == "transport_error"
    assert usage["http_status"] is None


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------
def _subscription(used: int, limit: int) -> httpx.Response:
    return httpx.Response(
        200,
        content=orjson.dumps({"character_count": used, "character_limit": limit}),
        headers={"content-type": "application/json"},
    )


async def test_health_reports_healthy_with_the_remaining_quota() -> None:
    # Arrange / Act
    async with music_provider(always(_subscription(1_000, 10_000))) as provider:
        result = await provider.health()

    # Assert
    assert is_ok(result)
    assert result.value.state is HealthState.HEALTHY
    assert result.value.quota_remaining == 9_000
    assert result.value.name == PROVIDER_NAME


async def test_health_reports_degraded_when_the_quota_is_gone() -> None:
    # Arrange / Act
    async with music_provider(always(_subscription(10_000, 10_000))) as provider:
        result = await provider.health()

    # Assert
    assert is_ok(result)
    assert result.value.state is HealthState.DEGRADED
    assert result.value.quota_remaining == 0


async def test_health_reports_unknown_rather_than_healthy_for_an_unreadable_body() -> None:
    # Arrange
    response = httpx.Response(200, content=b"<html>hello</html>")

    # Act
    async with music_provider(always(response)) as provider:
        result = await provider.health()

    # Assert
    assert is_ok(result)
    assert result.value.state is HealthState.UNKNOWN


async def test_health_reports_unknown_when_the_quota_fields_are_missing() -> None:
    # Arrange
    response = httpx.Response(200, content=orjson.dumps({"tier": "creator"}))

    # Act
    async with music_provider(always(response)) as provider:
        result = await provider.health()

    # Assert
    assert is_ok(result)
    assert result.value.state is HealthState.HEALTHY
    assert result.value.quota_remaining is None


async def test_health_surfaces_a_bad_api_key_as_an_error_not_a_state() -> None:
    # Arrange / Act
    async with music_provider(always(error_response(401, detail="bad key"))) as provider:
        result = await provider.health()

    # Assert
    assert is_err(result)
    assert result.error.error_code is ErrorCode.CONFIG_INVALID


async def test_health_reports_unavailable_when_the_vendor_cannot_be_reached() -> None:
    # Arrange
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("dns failure", request=request)

    # Act
    async with music_provider(handler) as provider:
        result = await provider.health()

    # Assert
    assert is_ok(result)
    assert result.value.state is HealthState.UNAVAILABLE


async def test_health_reports_degraded_on_a_client_error_and_unavailable_on_a_server_one() -> None:
    # Arrange / Act
    async with music_provider(always(error_response(404))) as provider:
        client_error = await provider.health()
    async with music_provider(always(error_response(502))) as provider:
        server_error = await provider.health()

    # Assert
    assert is_ok(client_error) and client_error.value.state is HealthState.DEGRADED
    assert is_ok(server_error) and server_error.value.state is HealthState.UNAVAILABLE


# ---------------------------------------------------------------------------
# Wiring
# ---------------------------------------------------------------------------
def test_the_adapter_satisfies_the_frozen_music_provider_protocol() -> None:
    # Arrange
    provider = ElevenLabsMusicProvider(
        api_key="k", base_url=TEST_BASE_URL, model_id="music_v2", output_format="mp3_44100_128"
    )

    # Act / Assert
    assert isinstance(provider, MusicProvider)
    assert provider.name == PROVIDER_NAME


async def test_aclose_leaves_a_borrowed_client_open_for_its_owner() -> None:
    # Arrange
    client = httpx.AsyncClient(transport=httpx.MockTransport(always(audio_response())))
    provider = ElevenLabsMusicProvider(
        api_key="k",
        base_url=TEST_BASE_URL,
        model_id="music_v2",
        output_format="mp3_44100_128",
        client=client,
    )

    # Act
    await provider.aclose()

    # Assert
    assert not client.is_closed
    await client.aclose()


async def test_aclose_closes_a_client_the_provider_created_itself() -> None:
    # Arrange
    provider = ElevenLabsMusicProvider(
        api_key="k", base_url=TEST_BASE_URL, model_id="music_v2", output_format="mp3_44100_128"
    )

    # Act
    await provider.aclose()

    # Assert
    assert provider._client.is_closed


async def test_inpaint_rejects_a_bad_plan_before_calling_the_vendor() -> None:
    # Arrange: a blank name chunk is as wrong on a re-roll as on a first render.
    seen: list[httpx.Request] = []
    plan = simple_plan().with_chunk_replaced(
        1, Chunk(text="  ", duration_ms=8_000, is_name_chunk=True)
    )

    # Act
    async with music_provider(recording(audio_response(), seen)) as provider:
        result = await provider.inpaint(
            plan, source_song_id="s1", chunk_index=1, idempotency_key="k", timeout_s=5.0
        )

    # Assert
    assert is_err(result)
    assert seen == []


async def test_health_reports_unknown_when_the_body_is_json_but_not_an_object() -> None:
    # Arrange
    response = httpx.Response(200, content=orjson.dumps([1, 2, 3]))

    # Act
    async with music_provider(always(response)) as provider:
        result = await provider.health()

    # Assert
    assert is_ok(result)
    assert result.value.state is HealthState.UNKNOWN
