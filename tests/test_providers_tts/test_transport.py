"""HTTP boundary: status classification, transport failures, body validation.

The classification table is the part with teeth — it decides whether the retry ladder gets
another go, so each status is asserted for both its error type and its retryability.
"""

from __future__ import annotations

import httpx
import pytest
from pydantic import BaseModel

from hbd.contracts import is_err, is_ok
from hbd.errors import (
    ErrorCode,
    ProviderInvalidResponseError,
    ProviderQuotaExhaustedError,
    ProviderRateLimitedError,
    ProviderRejectedContentError,
    ProviderTimeoutError,
    ProviderUnavailableError,
)
from hbd.providers.tts.transport import (
    classify_http_failure,
    health_from_error,
    http_status_of,
    parse_json_body,
    read_audio_body,
    send_request,
)
from tests.test_providers_tts.conftest import (
    MP3_BYTES,
    audio_response,
    build_client,
    error_response,
    fixed_clock,
    json_response,
    recording_client,
)

PROVIDER = "test_vendor"


class _Payload(BaseModel):
    text: str
    count: int = 0


# ---------------------------------------------------------------------------
# Status classification
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    ("status", "body", "expected_type", "expected_retryable"),
    [
        (401, "unauthorized", type(None), False),
        (402, "payment required", ProviderQuotaExhaustedError, False),
        (429, "slow down", ProviderRateLimitedError, True),
        (429, "quota exceeded", ProviderQuotaExhaustedError, False),
        (400, "content policy violation", ProviderRejectedContentError, False),
        (408, "took too long", ProviderTimeoutError, True),
        (503, "unavailable", ProviderUnavailableError, True),
    ],
)
def test_maps_each_status_to_its_own_operational_story(
    status: int, body: str, expected_type: type, expected_retryable: bool
) -> None:
    # Act
    error = classify_http_failure(provider=PROVIDER, status_code=status, body=body)

    # Assert
    assert error.is_retryable is expected_retryable
    if expected_type is not type(None):
        assert isinstance(error, expected_type)


def test_rejected_credentials_are_reported_as_a_configuration_problem() -> None:
    # Act
    error = classify_http_failure(provider=PROVIDER, status_code=403, body="forbidden")

    # Assert — no retry ladder can fix a bad key, and the operator must be told which one.
    assert error.error_code is ErrorCode.CONFIG_INVALID
    assert not error.is_retryable


def test_an_ordinary_bad_request_is_terminal_and_blames_our_payload() -> None:
    # Act
    error = classify_http_failure(provider=PROVIDER, status_code=400, body="missing field")

    # Assert
    assert error.error_code is ErrorCode.INVALID_INPUT
    assert not error.is_retryable


def test_the_status_survives_on_the_error_for_later_triage() -> None:
    # Act
    error = classify_http_failure(provider=PROVIDER, status_code=503, body="down")

    # Assert
    assert http_status_of(error) == 503


def test_status_lookup_returns_none_for_an_error_with_no_http_origin() -> None:
    # Arrange
    error = ProviderInvalidResponseError("not from HTTP", provider=PROVIDER)

    # Act / Assert
    assert http_status_of(error) is None


# ---------------------------------------------------------------------------
# Sending
# ---------------------------------------------------------------------------
async def test_returns_the_response_for_a_successful_call() -> None:
    # Arrange
    client, recorder = recording_client(audio_response())

    # Act
    result = await send_request(
        client, provider=PROVIDER, method="POST", url="https://vendor.test/x", timeout_s=1.0
    )

    # Assert
    assert is_ok(result)
    assert recorder.last.method == "POST"


async def test_turns_a_timeout_into_a_retryable_error() -> None:
    # Arrange
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("too slow", request=request)

    client = build_client(handler)

    # Act
    result = await send_request(
        client, provider=PROVIDER, method="GET", url="https://vendor.test/x", timeout_s=0.1
    )

    # Assert
    assert is_err(result)
    assert isinstance(result.error, ProviderTimeoutError)
    assert result.error.is_retryable


async def test_turns_a_connection_failure_into_a_vendor_outage() -> None:
    # Arrange
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("no route", request=request)

    client = build_client(handler)

    # Act
    result = await send_request(
        client, provider=PROVIDER, method="GET", url="https://vendor.test/x", timeout_s=1.0
    )

    # Assert
    assert is_err(result)
    assert isinstance(result.error, ProviderUnavailableError)


async def test_a_four_hundred_response_becomes_an_err_not_a_raised_status() -> None:
    # Arrange
    client, _ = recording_client(error_response(429, text="rate limited"))

    # Act
    result = await send_request(
        client, provider=PROVIDER, method="GET", url="https://vendor.test/x", timeout_s=1.0
    )

    # Assert
    assert is_err(result)
    assert isinstance(result.error, ProviderRateLimitedError)


# ---------------------------------------------------------------------------
# Body validation
# ---------------------------------------------------------------------------
async def test_accepts_a_body_declared_as_audio() -> None:
    # Arrange
    client, _ = recording_client(audio_response())
    sent = await send_request(
        client, provider=PROVIDER, method="GET", url="https://vendor.test/a", timeout_s=1.0
    )
    assert is_ok(sent)

    # Act
    result = read_audio_body(sent.value, provider=PROVIDER)

    # Assert
    assert is_ok(result)
    assert result.value == MP3_BYTES


async def test_refuses_a_json_body_where_audio_was_promised() -> None:
    # Arrange
    client, _ = recording_client(json_response({"error": "nope"}))
    sent = await send_request(
        client, provider=PROVIDER, method="GET", url="https://vendor.test/a", timeout_s=1.0
    )
    assert is_ok(sent)

    # Act
    result = read_audio_body(sent.value, provider=PROVIDER)

    # Assert
    assert is_err(result)
    assert isinstance(result.error, ProviderInvalidResponseError)


async def test_refuses_an_empty_audio_body() -> None:
    # Arrange
    client, _ = recording_client(audio_response(b""))
    sent = await send_request(
        client, provider=PROVIDER, method="GET", url="https://vendor.test/a", timeout_s=1.0
    )
    assert is_ok(sent)

    # Act
    result = read_audio_body(sent.value, provider=PROVIDER)

    # Assert
    assert is_err(result)


async def test_validates_a_json_body_against_its_schema() -> None:
    # Arrange
    client, _ = recording_client(json_response({"text": "hi", "count": 2}))
    sent = await send_request(
        client, provider=PROVIDER, method="GET", url="https://vendor.test/j", timeout_s=1.0
    )
    assert is_ok(sent)

    # Act
    result = parse_json_body(sent.value, _Payload, provider=PROVIDER)

    # Assert
    assert is_ok(result)
    assert result.value.text == "hi"


async def test_rejects_json_that_does_not_match_the_schema() -> None:
    # Arrange
    client, _ = recording_client(json_response({"count": "many"}))
    sent = await send_request(
        client, provider=PROVIDER, method="GET", url="https://vendor.test/j", timeout_s=1.0
    )
    assert is_ok(sent)

    # Act
    result = parse_json_body(sent.value, _Payload, provider=PROVIDER)

    # Assert — shape, not just syntax.
    assert is_err(result)
    assert "_Payload" in result.error.operator_message


async def test_rejects_a_two_hundred_that_is_not_json_at_all() -> None:
    # Arrange
    client, _ = recording_client(httpx.Response(200, text="<html>oops</html>"))
    sent = await send_request(
        client, provider=PROVIDER, method="GET", url="https://vendor.test/j", timeout_s=1.0
    )
    assert is_ok(sent)

    # Act
    result = parse_json_body(sent.value, _Payload, provider=PROVIDER)

    # Assert
    assert is_err(result)
    assert isinstance(result.error, ProviderInvalidResponseError)


# ---------------------------------------------------------------------------
# Health translation
# ---------------------------------------------------------------------------
async def test_a_vendor_outage_becomes_a_health_state_not_a_failed_probe() -> None:
    # Arrange
    client, _ = recording_client(error_response(503))
    failure = await send_request(
        client, provider=PROVIDER, method="GET", url="https://vendor.test/h", timeout_s=1.0
    )
    assert is_err(failure)

    # Act
    result = health_from_error(failure, provider=PROVIDER, clock=fixed_clock)

    # Assert
    assert is_ok(result)
    assert result.value.state.value == "unavailable"


async def test_a_client_error_probe_reports_degraded() -> None:
    # Arrange
    client, _ = recording_client(error_response(404))
    failure = await send_request(
        client, provider=PROVIDER, method="GET", url="https://vendor.test/h", timeout_s=1.0
    )
    assert is_err(failure)

    # Act
    result = health_from_error(failure, provider=PROVIDER, clock=fixed_clock)

    # Assert
    assert is_ok(result)
    assert result.value.state.value == "degraded"


async def test_bad_credentials_propagate_instead_of_becoming_a_health_line() -> None:
    # Arrange
    client, _ = recording_client(error_response(401))
    failure = await send_request(
        client, provider=PROVIDER, method="GET", url="https://vendor.test/h", timeout_s=1.0
    )
    assert is_err(failure)

    # Act
    result = health_from_error(failure, provider=PROVIDER, clock=fixed_clock)

    # Assert — an operator must be told the key is wrong, not that the vendor is sad.
    assert is_err(result)
