"""What the music leg tells the spend panel, on every path it can return from.

Three properties are pinned here and each one is a way the panel could be lied to. Every
call writes exactly one record — a leg that recorded only its successes would make a vendor
that is failing look cheap. A failure carries the typed error code and no cost — nothing
was rendered, so nothing was billed. And a deployment with no rate configured records
``cost_usd=None``, never ``0.0``: a zero would be summed as "this render was free", which
is the fabricated number the whole ``vendor_usage`` design exists to keep out of a column.

The adapter's own ``music.usage`` log line is asserted alongside the record, because the
vendor row is an addition to it and not a replacement.
"""

from __future__ import annotations

import logging

import httpx
import pytest

from bayram.contracts import CostSource, HealthState, Vendor, VendorOperation
from bayram.errors import ErrorCode, ProviderRateLimitedError
from bayram.providers.music.elevenlabs import PROVIDER_NAME
from bayram.providers.music.fake import FAKE_PROVIDER_NAME, FakeMusicProvider
from bayram.providers.music.usage import USAGE_EVENT
from bayram.usage import VendorUsage
from tests.test_providers_music.conftest import (
    AUDIO_BODY,
    TEST_MODEL_ID,
    always,
    audio_response,
    error_response,
    music_provider,
    simple_plan,
    usage_line,
)

LOGGER_NAME = "bayram.providers.music.elevenlabs"
IDEMPOTENCY_KEY = "order-123-compose-1"
TIMEOUT_S = 30.0

#: 20s + 8s + 20s of plan, at the default rate: 48/60 * 0.15.
PLAN_DURATION_MS = 48_000
EXPECTED_COST_USD = 0.12


class CollectingSink:
    """A ``UsageSink`` that keeps every record. The contract forbids raising, so it cannot."""

    def __init__(self) -> None:
        self.records: list[VendorUsage] = []

    async def record(self, usage: VendorUsage) -> None:
        self.records.append(usage)

    @property
    def only(self) -> VendorUsage:
        assert len(self.records) == 1, f"expected exactly one record, got {len(self.records)}"
        return self.records[0]


async def test_a_successful_compose_records_one_measured_call() -> None:
    # Arrange
    sink = CollectingSink()

    # Act
    async with music_provider(always(audio_response()), usage=sink) as provider:
        await provider.compose(simple_plan(), idempotency_key=IDEMPOTENCY_KEY, timeout_s=TIMEOUT_S)

    # Assert
    record = sink.only
    assert record.vendor is Vendor.ELEVENLABS
    assert record.operation is VendorOperation.MUSIC_COMPOSE
    assert record.provider == PROVIDER_NAME
    assert record.model_id == TEST_MODEL_ID
    assert record.is_success is True
    assert record.http_status == 200
    assert record.response_bytes == len(AUDIO_BODY)
    assert record.audio_ms == PLAN_DURATION_MS
    assert record.error_code is None


async def test_an_inpaint_is_recorded_as_its_own_operation() -> None:
    # Arrange — compose and inpaint bill differently, so they must not roll up as one.
    sink = CollectingSink()

    # Act
    async with music_provider(always(audio_response()), usage=sink) as provider:
        await provider.inpaint(
            simple_plan(),
            source_song_id="song_abc123",
            chunk_index=1,
            idempotency_key=IDEMPOTENCY_KEY,
            timeout_s=TIMEOUT_S,
        )

    # Assert
    assert sink.only.operation is VendorOperation.MUSIC_INPAINT


async def test_the_latency_of_the_vendor_call_is_measured() -> None:
    # Arrange
    sink = CollectingSink()

    # Act
    async with music_provider(always(audio_response()), usage=sink) as provider:
        await provider.compose(simple_plan(), idempotency_key=IDEMPOTENCY_KEY, timeout_s=TIMEOUT_S)

    # Assert — a real measurement, so only "present and not negative" is assertable.
    assert sink.only.latency_ms is not None
    assert sink.only.latency_ms >= 0


async def test_the_cost_is_estimated_because_the_rate_and_the_duration_are_both_ours() -> None:
    # Arrange
    sink = CollectingSink()

    # Act
    async with music_provider(always(audio_response()), usage=sink) as provider:
        await provider.compose(simple_plan(), idempotency_key=IDEMPOTENCY_KEY, timeout_s=TIMEOUT_S)

    # Assert — the vendor returned audio and no price; claiming DERIVED would overstate it.
    assert sink.only.cost_usd == pytest.approx(EXPECTED_COST_USD)
    assert sink.only.cost_source is CostSource.ESTIMATED


async def test_a_deployment_with_no_rate_records_no_cost_rather_than_zero() -> None:
    # Arrange
    sink = CollectingSink()

    # Act
    async with music_provider(always(audio_response()), usage=sink, usd_per_minute=0.0) as provider:
        await provider.compose(simple_plan(), idempotency_key=IDEMPOTENCY_KEY, timeout_s=TIMEOUT_S)

    # Assert — 0.0 would sum as spend and read as "this render was free".
    assert sink.only.cost_usd is None
    assert sink.only.cost_source is None


async def test_a_rejected_status_is_recorded_as_a_failure_with_its_typed_code() -> None:
    # Arrange
    sink = CollectingSink()

    # Act
    async with music_provider(always(error_response(429)), usage=sink) as provider:
        await provider.compose(simple_plan(), idempotency_key=IDEMPOTENCY_KEY, timeout_s=TIMEOUT_S)

    # Assert
    record = sink.only
    assert record.is_success is False
    assert record.http_status == 429
    assert record.error_code == ErrorCode.RATE_LIMITED.value
    assert record.cost_usd is None
    assert record.audio_ms is None


async def test_a_transport_failure_is_recorded_with_no_status_and_no_cost() -> None:
    # Arrange
    sink = CollectingSink()

    def refuse(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    # Act
    async with music_provider(refuse, usage=sink) as provider:
        await provider.compose(simple_plan(), idempotency_key=IDEMPOTENCY_KEY, timeout_s=TIMEOUT_S)

    # Assert — nothing reached the vendor, so there is no status to report and none invented.
    record = sink.only
    assert record.is_success is False
    assert record.http_status is None
    assert record.error_code == ErrorCode.UPSTREAM_5XX.value
    assert record.cost_usd is None
    assert record.latency_ms is not None


async def test_a_two_hundred_that_is_not_audio_is_recorded_as_a_failure() -> None:
    # Arrange — the status was fine and we still have nothing to sing.
    sink = CollectingSink()
    body = httpx.Response(200, json={"detail": "not audio"})

    # Act
    async with music_provider(always(body), usage=sink) as provider:
        await provider.compose(simple_plan(), idempotency_key=IDEMPOTENCY_KEY, timeout_s=TIMEOUT_S)

    # Assert
    record = sink.only
    assert record.is_success is False
    assert record.http_status == 200
    assert record.error_code == ErrorCode.UPSTREAM_MALFORMED.value
    assert record.cost_usd is None


async def test_the_music_usage_log_line_survives_beside_the_vendor_record(
    caplog: pytest.LogCaptureFixture,
) -> None:
    # Arrange
    sink = CollectingSink()

    # Act
    with caplog.at_level(logging.INFO, logger=LOGGER_NAME):
        async with music_provider(always(audio_response()), usage=sink) as provider:
            await provider.compose(
                simple_plan(), idempotency_key=IDEMPOTENCY_KEY, timeout_s=TIMEOUT_S
            )

    # Assert — the richer render line is an ancestor of this work, not a casualty of it.
    line = usage_line(caplog.records, USAGE_EVENT)
    assert line["chunk_count"] == 3
    assert line["outcome"] == "ok"
    assert len(sink.records) == 1


async def test_a_health_probe_is_recorded_and_is_never_priced() -> None:
    # Arrange
    sink = CollectingSink()
    subscription = httpx.Response(200, json={"character_count": 10, "character_limit": 1_000})

    # Act
    async with music_provider(always(subscription), usage=sink) as provider:
        await provider.health()

    # Assert — a quota probe has a latency and a status but can never read as spend.
    record = sink.only
    assert record.operation is VendorOperation.HEALTH
    assert record.is_success is True
    assert record.http_status == 200
    assert record.cost_usd is None
    assert record.cost_source is None


async def test_a_failed_health_probe_keeps_the_vendors_failure_visible() -> None:
    # Arrange
    sink = CollectingSink()

    # Act
    async with music_provider(always(error_response(503)), usage=sink) as provider:
        await provider.health()

    # Assert — dropping this row would flatter the failure rate of a vendor that is down.
    record = sink.only
    assert record.is_success is False
    assert record.http_status == 503
    assert record.error_code == ErrorCode.UPSTREAM_5XX.value


async def test_the_fake_provider_records_its_calls_as_fake_and_unpriced() -> None:
    # Arrange
    sink = CollectingSink()
    provider = FakeMusicProvider(usage=sink)

    # Act
    await provider.compose(simple_plan(), idempotency_key=IDEMPOTENCY_KEY, timeout_s=TIMEOUT_S)

    # Assert — a demo run must be visibly excluded, never invisible.
    record = sink.only
    assert record.vendor is Vendor.FAKE
    assert record.provider == FAKE_PROVIDER_NAME
    assert record.is_fake is True
    assert record.is_success is True
    assert record.cost_usd is None
    assert record.cost_source is None


async def test_the_fake_provider_records_an_injected_failure() -> None:
    # Arrange
    sink = CollectingSink()
    provider = FakeMusicProvider(
        usage=sink, failure=ProviderRateLimitedError("scripted", provider=FAKE_PROVIDER_NAME)
    )

    # Act
    await provider.compose(simple_plan(), idempotency_key=IDEMPOTENCY_KEY, timeout_s=TIMEOUT_S)

    # Assert
    record = sink.only
    assert record.is_success is False
    assert record.error_code == ErrorCode.RATE_LIMITED.value


async def test_the_fake_health_probe_reports_the_state_it_was_configured_with() -> None:
    # Arrange
    sink = CollectingSink()
    provider = FakeMusicProvider(usage=sink, health_state=HealthState.UNAVAILABLE)

    # Act
    await provider.health()

    # Assert
    record = sink.only
    assert record.operation is VendorOperation.HEALTH
    assert record.is_success is False
    assert record.is_fake is True
