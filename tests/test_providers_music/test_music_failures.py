"""401 vs 422 vs 429 vs 5xx are four different situations with four different fixes."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import orjson
import pytest

from bayram.errors import (
    ErrorCode,
    ProviderError,
    ProviderInvalidResponseError,
    ProviderQuotaExhaustedError,
    ProviderRateLimitedError,
    ProviderRejectedContentError,
    ProviderTimeoutError,
    ProviderUnavailableError,
)
from bayram.providers.music.failures import (
    MAX_ERROR_BODY_CHARS,
    describe_error_body,
    map_status_error,
    map_transport_error,
    parse_retry_after,
)

PROVIDER = "elevenlabs_music"


def _response(
    status: int, *, detail: Any = "boom", headers: dict[str, str] | None = None
) -> httpx.Response:
    return httpx.Response(
        status_code=status, content=orjson.dumps({"detail": detail}), headers=headers or {}
    )


def _map(
    status: int, *, detail: Any = "boom", headers: dict[str, str] | None = None
) -> ProviderError:
    return map_status_error(
        _response(status, detail=detail, headers=headers),
        provider=PROVIDER,
        operation="compose",
    )


# ---------------------------------------------------------------------------
# Status mapping
# ---------------------------------------------------------------------------
def test_429_is_retryable_and_surfaces_the_retry_after_the_vendor_asked_for() -> None:
    # Arrange / Act
    error = _map(429, headers={"retry-after": "17"})

    # Assert
    assert isinstance(error, ProviderRateLimitedError)
    assert error.is_retryable
    assert error.context["retry_after_s"] == 17.0


def test_429_without_a_retry_after_header_reports_none_rather_than_guessing() -> None:
    # Arrange / Act
    error = _map(429)

    # Assert
    assert error.context["retry_after_s"] is None


def test_401_is_terminal_and_reads_as_a_configuration_problem() -> None:
    # Arrange / Act
    error = _map(401, detail="Invalid API key")

    # Assert
    assert error.error_code is ErrorCode.CONFIG_INVALID
    assert not error.is_retryable
    assert error.user_message_key == "error.service_unavailable"


def test_401_that_mentions_quota_is_reported_as_exhausted_quota() -> None:
    # Arrange / Act
    error = _map(401, detail={"status": "quota_exceeded", "message": "no credits"})

    # Assert
    assert isinstance(error, ProviderQuotaExhaustedError)
    assert not error.is_retryable


def test_402_is_exhausted_quota_and_never_retried() -> None:
    # Arrange / Act
    error = _map(402)

    # Assert
    assert isinstance(error, ProviderQuotaExhaustedError)
    assert not error.is_retryable


def test_422_is_our_payloads_fault_and_terminal() -> None:
    # Arrange / Act
    error = _map(422, detail=[{"loc": ["body", "music_length_ms"], "msg": "too long"}])

    # Assert
    assert error.error_code is ErrorCode.INVALID_INPUT
    assert not error.is_retryable


def test_a_style_field_that_names_a_real_artist_gets_its_own_code() -> None:
    # Arrange / Act
    error = _map(400, detail={"status": "prompt_rejected", "message": "artist name detected"})

    # Assert
    assert isinstance(error, ProviderRejectedContentError)
    assert error.error_code is ErrorCode.ARTIST_NAME_IN_STYLE


def test_a_moderation_refusal_is_reported_as_rejected_content() -> None:
    # Arrange / Act
    error = _map(400, detail={"status": "moderation_failed", "message": "unsafe lyric"})

    # Assert
    assert isinstance(error, ProviderRejectedContentError)
    assert error.error_code is ErrorCode.CONTENT_REJECTED
    assert error.user_message_key == "error.content_not_allowed"


@pytest.mark.parametrize("status", [500, 502, 503, 504])
def test_server_errors_are_retryable(status: int) -> None:
    # Arrange / Act
    error = _map(status)

    # Assert
    assert isinstance(error, ProviderUnavailableError)
    assert error.is_retryable


def test_an_unexpected_status_is_treated_as_a_malformed_response() -> None:
    # Arrange / Act
    error = _map(418)

    # Assert
    assert isinstance(error, ProviderInvalidResponseError)


def test_every_mapped_error_carries_the_provider_and_the_status() -> None:
    # Arrange / Act
    error = _map(503)

    # Assert
    assert error.provider == PROVIDER
    assert error.context["http_status"] == 503
    assert error.context["operation"] == "compose"


# ---------------------------------------------------------------------------
# Body reading — nothing here may raise
# ---------------------------------------------------------------------------
def test_describe_reads_a_nested_detail_object() -> None:
    assert "quota_exceeded" in describe_error_body(
        orjson.dumps({"detail": {"status": "quota_exceeded", "message": "gone"}})
    )


def test_describe_survives_an_html_error_page() -> None:
    assert "502 Bad Gateway" in describe_error_body(b"<html><h1>502 Bad Gateway</h1></html>")


def test_describe_survives_an_empty_body() -> None:
    assert describe_error_body(b"") == "<empty body>"


def test_describe_survives_a_json_list_of_validation_errors() -> None:
    body = orjson.dumps({"detail": [{"msg": "field required"}, {"msg": "too long"}]})
    described = describe_error_body(body)
    assert "field required" in described
    assert "too long" in described


def test_describe_survives_a_scalar_detail() -> None:
    assert describe_error_body(orjson.dumps({"detail": 42})) == "42"


def test_a_null_detail_never_becomes_the_literal_string_none() -> None:
    # Arrange / Act: an operator reading "None" in a log learns nothing.
    described = describe_error_body(orjson.dumps({"detail": None}))

    # Assert
    assert described
    assert described != "None"


def test_describe_truncates_a_flood_of_text() -> None:
    described = describe_error_body(b"x" * 50_000)
    assert len(described) == MAX_ERROR_BODY_CHARS


def test_describe_survives_invalid_utf8() -> None:
    assert describe_error_body(b"\xff\xfe\x00garbage")


# ---------------------------------------------------------------------------
# Retry-After
# ---------------------------------------------------------------------------
def test_retry_after_reads_plain_seconds() -> None:
    assert parse_retry_after(httpx.Headers({"retry-after": " 30 "})) == 30.0


def test_retry_after_reads_an_http_date() -> None:
    # Arrange
    when = datetime.now(tz=UTC) + timedelta(seconds=60)
    header = when.strftime("%a, %d %b %Y %H:%M:%S GMT")

    # Act
    seconds = parse_retry_after(httpx.Headers({"retry-after": header}))

    # Assert
    assert seconds is not None
    assert 50 <= seconds <= 61


def test_retry_after_never_returns_a_negative_wait() -> None:
    # Arrange: a date already in the past.
    header = (datetime.now(tz=UTC) - timedelta(hours=1)).strftime("%a, %d %b %Y %H:%M:%S GMT")

    # Act / Assert
    assert parse_retry_after(httpx.Headers({"retry-after": header})) == 0.0


def test_retry_after_returns_none_for_nonsense() -> None:
    assert parse_retry_after(httpx.Headers({"retry-after": "soon-ish"})) is None


def test_retry_after_returns_none_when_absent() -> None:
    assert parse_retry_after(httpx.Headers({})) is None


# ---------------------------------------------------------------------------
# Transport
# ---------------------------------------------------------------------------
def test_a_timeout_maps_to_a_retryable_timeout_error() -> None:
    # Arrange / Act
    error = map_transport_error(
        httpx.ReadTimeout("timed out"), provider=PROVIDER, operation="compose", timeout_s=420.0
    )

    # Assert
    assert isinstance(error, ProviderTimeoutError)
    assert error.is_retryable
    assert error.context["timeout_s"] == 420.0


def test_a_connection_reset_maps_to_a_retryable_unavailable_error() -> None:
    # Arrange / Act
    error = map_transport_error(
        httpx.ConnectError("reset"), provider=PROVIDER, operation="compose", timeout_s=1.0
    )

    # Assert
    assert isinstance(error, ProviderUnavailableError)
    assert error.is_retryable
    assert error.context["exception_type"] == "ConnectError"
