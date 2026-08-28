"""Translate a vendor failure into one of OUR typed errors.

401, 422, 429 and 503 are four different situations with four different correct responses,
and the retry ladder reads ``is_retryable`` rather than pattern-matching a vendor string.
That is the whole reason this file exists:

* **401 / 403** — our key is wrong or revoked. Terminal, and an operator problem, so the
  customer sees ``error.service_unavailable`` rather than a "we're busy" fib.
* **402 / quota** — money or plan quota is gone. Terminal against this provider.
* **422 / 400** — the vendor rejected OUR payload. Terminal as-is; retrying byte-identical
  input is pure cost. A policy rejection is split out because naming a real artist in a
  style field has its own error code and its own fix.
* **429** — retryable, and it MUST surface ``Retry-After`` so the ladder waits the amount
  the vendor asked for instead of a number we invented.
* **5xx / transport** — the vendor is down, not our payload. Retryable.

Nothing here trusts the error body. A vendor having a bad day returns HTML, an empty body,
or JSON in a shape its own docs do not describe, and none of those may raise.
"""

from __future__ import annotations

from datetime import datetime
from email.utils import parsedate_to_datetime
from typing import Any, Final

import httpx
import orjson

from hbd.errors import (
    ErrorCode,
    ProviderError,
    ProviderInvalidResponseError,
    ProviderQuotaExhaustedError,
    ProviderRateLimitedError,
    ProviderRejectedContentError,
    ProviderTimeoutError,
    ProviderUnavailableError,
)

__all__ = [
    "parse_retry_after",
    "describe_error_body",
    "map_status_error",
    "map_transport_error",
    "MAX_ERROR_BODY_CHARS",
]

#: Enough of the body to diagnose, not enough to flood the log.
MAX_ERROR_BODY_CHARS: Final[int] = 1_000

_QUOTA_MARKERS: Final[tuple[str, ...]] = (
    "quota",
    "insufficient_credit",
    "payment",
    "billing",
    "subscription",
)
_ARTIST_MARKERS: Final[tuple[str, ...]] = ("artist", "copyright", "trademark")
_CONTENT_MARKERS: Final[tuple[str, ...]] = (
    "prompt_rejected",
    "moderation",
    "policy",
    "unsafe",
    "blocked",
    "violat",
)

_RATE_LIMIT_STATUS: Final[int] = 429
_PAYMENT_REQUIRED_STATUS: Final[int] = 402
_UNPROCESSABLE_STATUS: Final[int] = 422
_BAD_REQUEST_STATUS: Final[int] = 400
_AUTH_STATUSES: Final[tuple[int, ...]] = (401, 403)
_SERVER_ERROR_FLOOR: Final[int] = 500


# ---------------------------------------------------------------------------
# Body and header readers. None of these raise.
# ---------------------------------------------------------------------------
def _detail_text(payload: Any) -> str:
    """Flatten whatever sat under ``detail`` into searchable text."""
    if isinstance(payload, str):
        return payload
    if isinstance(payload, dict):
        # A key present with a null value must not become the literal string "None".
        parts = (
            str(payload[key])
            for key in ("status", "message", "detail", "error")
            if payload.get(key) is not None
        )
        joined = " ".join(part for part in parts if part)
        return joined or str(payload)
    if isinstance(payload, list):
        return " ".join(_detail_text(item) for item in payload)
    return "" if payload is None else str(payload)


def describe_error_body(body: bytes) -> str:
    """A short, log-safe description of an error body in ANY shape. Never raises."""
    if not body:
        return "<empty body>"
    try:
        payload = orjson.loads(body)
    except orjson.JSONDecodeError:
        text = body.decode("utf-8", errors="replace")
        return text[:MAX_ERROR_BODY_CHARS]
    detail = payload.get("detail") if isinstance(payload, dict) else None
    described = _detail_text(detail if detail is not None else payload)
    return described[:MAX_ERROR_BODY_CHARS] or "<no detail>"


def parse_retry_after(headers: httpx.Headers) -> float | None:
    """Seconds to wait, from a numeric or HTTP-date ``Retry-After``. Never raises."""
    raw = headers.get("retry-after")
    if not raw:
        return None
    try:
        return max(0.0, float(raw.strip()))
    except ValueError:
        pass
    try:
        when = parsedate_to_datetime(raw)
    except (TypeError, ValueError):
        return None
    return max(0.0, (when - datetime.now(tz=when.tzinfo)).total_seconds())


def _matches(text: str, markers: tuple[str, ...]) -> bool:
    lowered = text.lower()
    return any(marker in lowered for marker in markers)


# ---------------------------------------------------------------------------
# Mapping
# ---------------------------------------------------------------------------
def _payload_rejection(detail: str, context: dict[str, Any], provider: str) -> ProviderError:
    if _matches(detail, _ARTIST_MARKERS):
        return ProviderRejectedContentError(
            f"vendor rejected the request: a style field looks like a real artist ({detail})",
            provider=provider,
            code=ErrorCode.ARTIST_NAME_IN_STYLE,
            context=context,
        )
    if _matches(detail, _CONTENT_MARKERS):
        return ProviderRejectedContentError(
            f"vendor refused the payload on policy grounds ({detail})",
            provider=provider,
            context=context,
        )
    return ProviderError(
        f"vendor rejected our payload as invalid ({detail})",
        provider=provider,
        code=ErrorCode.INVALID_INPUT,
        is_retryable=False,
        context=context,
    )


def map_status_error(
    response: httpx.Response, *, provider: str, operation: str
) -> ProviderError:
    """Map a non-2xx response to a typed error. Never raises, never reads a stream twice."""
    status = response.status_code
    detail = describe_error_body(response.content)
    context: dict[str, Any] = {
        "operation": operation,
        "http_status": status,
        "response_detail": detail,
        "request_id": response.headers.get("request-id"),
    }

    if status == _RATE_LIMIT_STATUS:
        retry_after = parse_retry_after(response.headers)
        return ProviderRateLimitedError(
            f"vendor rate-limited {operation} ({detail})",
            provider=provider,
            context={**context, "retry_after_s": retry_after},
        )
    if status == _PAYMENT_REQUIRED_STATUS or (
        status in _AUTH_STATUSES and _matches(detail, _QUOTA_MARKERS)
    ):
        return ProviderQuotaExhaustedError(
            f"vendor quota or balance exhausted during {operation} ({detail})",
            provider=provider,
            context=context,
        )
    if status in _AUTH_STATUSES:
        return ProviderError(
            f"vendor rejected our credentials during {operation} ({detail})",
            provider=provider,
            code=ErrorCode.CONFIG_INVALID,
            user_message_key="error.service_unavailable",
            is_retryable=False,
            context=context,
        )
    if status in (_BAD_REQUEST_STATUS, _UNPROCESSABLE_STATUS):
        return _payload_rejection(detail, context, provider)
    if status >= _SERVER_ERROR_FLOOR:
        return ProviderUnavailableError(
            f"vendor returned {status} during {operation} ({detail})",
            provider=provider,
            context=context,
        )
    return ProviderInvalidResponseError(
        f"vendor returned unexpected status {status} during {operation} ({detail})",
        provider=provider,
        context=context,
    )


def map_transport_error(
    exc: Exception, *, provider: str, operation: str, timeout_s: float
) -> ProviderError:
    """Map an httpx transport failure. A timeout and a reset are both retryable."""
    context: dict[str, Any] = {
        "operation": operation,
        "timeout_s": timeout_s,
        "exception_type": type(exc).__name__,
    }
    if isinstance(exc, httpx.TimeoutException):
        return ProviderTimeoutError(
            f"{operation} exceeded {timeout_s}s against the vendor",
            provider=provider,
            context=context,
            cause=exc,
        )
    return ProviderUnavailableError(
        f"transport failure during {operation}: {exc}",
        provider=provider,
        context=context,
        cause=exc,
    )
