"""HTTP boundary. Every failure class must come back as the right typed error."""

from __future__ import annotations

import httpx
import pytest

from hbd.contracts import Err, Ok
from hbd.errors import ErrorCode
from hbd.providers.llm.transport import (
    MAX_ERROR_BODY_CHARS,
    read_path,
    read_str,
    request_json,
)
from tests.test_providers_llm.conftest import mock_client

PROVIDER = "test-vendor"


async def call(handler: object) -> Ok[object] | Err:
    async with mock_client(handler) as client:
        return await request_json(
            client,
            method="POST",
            url="https://vendor.example/v1/thing",
            headers={"authorization": "Bearer secret"},
            provider=PROVIDER,
            timeout_s=1.0,
            json_body={"hello": "world"},
        )


def responder(status: int, body: str, *, content_type: str = "application/json") -> object:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(status, text=body, headers={"content-type": content_type})

    return handler


# ---------------------------------------------------------------------------
# Success
# ---------------------------------------------------------------------------
async def test_returns_the_decoded_body_on_success() -> None:
    result = await call(responder(200, '{"ok": true, "n": 3}'))

    assert isinstance(result, Ok)
    assert result.value == {"ok": True, "n": 3}


async def test_sends_the_supplied_headers_and_json_body() -> None:
    seen: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["auth"] = request.headers.get("authorization")
        seen["body"] = request.content
        return httpx.Response(200, json={})

    await call(handler)

    assert seen["auth"] == "Bearer secret"
    assert b"world" in seen["body"]  # type: ignore[operator]


# ---------------------------------------------------------------------------
# Status mapping — the retry ladder reads is_retryable, so it must be right
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    ("status", "body", "code", "is_retryable"),
    [
        (429, "rate limit exceeded", ErrorCode.RATE_LIMITED, True),
        (429, "you exceeded your current quota", ErrorCode.QUOTA_EXHAUSTED, False),
        (402, "billing account required", ErrorCode.QUOTA_EXHAUSTED, False),
        (403, "insufficient credit", ErrorCode.QUOTA_EXHAUSTED, False),
        (400, "blocked by the safety filter", ErrorCode.CONTENT_REJECTED, False),
        (400, "invalid argument: bad field", ErrorCode.UNKNOWN, False),
        (401, "invalid api key", ErrorCode.UNKNOWN, False),
        # A 404 is a wrong URL, never a moderation block. Its HTML error page may well
        # contain "violate" in an acceptable-use footer link, which used to classify it
        # as CONTENT_REJECTED and send the reader off to rewrite an innocent prompt.
        (
            404,
            "<html><a href='/terms'>you may not violate our policies</a></html>",
            ErrorCode.UNKNOWN,
            False,
        ),
        (500, "internal error", ErrorCode.UPSTREAM_5XX, True),
        (503, "service unavailable", ErrorCode.UPSTREAM_5XX, True),
    ],
)
async def test_maps_status_to_typed_error(
    status: int, body: str, code: ErrorCode, is_retryable: bool
) -> None:
    result = await call(responder(status, body))

    assert isinstance(result, Err)
    assert result.error.error_code is code
    assert result.error.is_retryable is is_retryable


async def test_error_context_carries_the_status_and_a_bounded_body() -> None:
    result = await call(responder(500, "e" * (MAX_ERROR_BODY_CHARS * 2)))

    assert isinstance(result, Err)
    assert result.error.context["status_code"] == 500
    assert len(result.error.context["response_body"]) == MAX_ERROR_BODY_CHARS


# ---------------------------------------------------------------------------
# Transport and decode failures
# ---------------------------------------------------------------------------
async def test_maps_a_timeout_to_a_retryable_timeout_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("too slow", request=request)

    result = await call(handler)

    assert isinstance(result, Err)
    assert result.error.error_code is ErrorCode.UPSTREAM_TIMEOUT
    assert result.error.is_retryable is True


async def test_maps_a_connection_failure_to_provider_unavailable() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("dns failure", request=request)

    result = await call(handler)

    assert isinstance(result, Err)
    assert result.error.error_code is ErrorCode.UPSTREAM_5XX


async def test_maps_a_two_hundred_with_a_non_json_body_to_malformed() -> None:
    # The observed trap: HTTP 200 with an HTML error page or a plaintext leak.
    result = await call(responder(200, "<html>gateway</html>", content_type="text/html"))

    assert isinstance(result, Err)
    assert result.error.error_code is ErrorCode.UPSTREAM_MALFORMED
    assert result.error.is_retryable is True


async def test_an_unexpected_client_exception_is_still_a_result() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        raise RuntimeError("something nobody predicted")

    result = await call(handler)

    assert isinstance(result, Err)
    assert result.error.error_code is ErrorCode.UNKNOWN


# ---------------------------------------------------------------------------
# Defensive reading — never an unchecked index into vendor data
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "path",
    [
        ("candidates", 0, "text"),
        ("missing",),
        ("candidates", 9),
        ("candidates", 0, "text", "deeper"),
    ],
)
def test_read_path_returns_none_for_any_shape_mismatch(path: tuple[object, ...]) -> None:
    payload = {"candidates": [{"content": "hi"}]}

    assert read_path(payload, *path) is None  # type: ignore[arg-type]


def test_read_path_walks_maps_and_lists_including_negative_indexes() -> None:
    payload = {"a": [{"b": "found"}, {"b": "last"}]}

    assert read_path(payload, "a", 0, "b") == "found"
    assert read_path(payload, "a", -1, "b") == "last"


def test_read_str_rejects_a_non_string_and_an_empty_string() -> None:
    payload = {"n": 5, "blank": "", "good": "yes"}

    assert read_str(payload, "n") is None
    assert read_str(payload, "blank") is None
    assert read_str(payload, "good") == "yes"
