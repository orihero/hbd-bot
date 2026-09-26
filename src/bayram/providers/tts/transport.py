"""Shared HTTP transport for the speech adapters.

Three jobs, none of which belong in an adapter:

* Turn every httpx failure mode into a typed :class:`~bayram.errors.BayramError`. Nothing in
  this package raises across a Protocol boundary, so the mapping happens once, here.
* Classify an HTTP status into a *distinct* error class — auth, quota, rate limit,
  content policy, vendor outage and bad-request are five different operational stories
  and the retry ladder reads them differently.
* Validate a response body before anyone touches it: audio must actually be audio, and
  JSON must satisfy a pydantic model. Never an unchecked cast on a vendor payload.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from typing import Any, Final

import httpx
from pydantic import BaseModel
from pydantic import ValidationError as PydanticValidationError

from bayram.contracts import Err, HealthState, ProviderHealth, Result, err, ok
from bayram.errors import (
    BayramError,
    ErrorCode,
    ProviderError,
    ProviderInvalidResponseError,
    ProviderQuotaExhaustedError,
    ProviderRateLimitedError,
    ProviderRejectedContentError,
    ProviderTimeoutError,
    ProviderUnavailableError,
)
from bayram.logging import get_logger

__all__ = [
    "MAX_ERROR_BODY_CHARS",
    "classify_http_failure",
    "health_from_error",
    "http_status_of",
    "parse_json_body",
    "read_audio_body",
    "send_request",
    "utc_now",
]

_LOG = get_logger(__name__)

#: Vendor error bodies are echoed into logs; cap them so a stack trace cannot flood.
MAX_ERROR_BODY_CHARS: Final[int] = 500

_STATUS_UNAUTHORIZED: Final[int] = 401
_STATUS_PAYMENT_REQUIRED: Final[int] = 402
_STATUS_FORBIDDEN: Final[int] = 403
_STATUS_REQUEST_TIMEOUT: Final[int] = 408
_STATUS_TOO_MANY_REQUESTS: Final[int] = 429
_STATUS_CLIENT_ERROR_FLOOR: Final[int] = 400
_STATUS_SERVER_ERROR_FLOOR: Final[int] = 500

#: Substrings that mean "you are out of money", not "you are going too fast".
_QUOTA_MARKERS: Final[tuple[str, ...]] = (
    "quota",
    "credit",
    "insufficient",
    "out of characters",
    "payment required",
    "subscription",
)

#: Substrings that mean the vendor's policy layer refused the payload.
_POLICY_MARKERS: Final[tuple[str, ...]] = (
    "policy",
    "moderation",
    "prohibited",
    "unsafe",
    "violat",
    "blocked",
)

_AUDIO_CONTENT_TYPES: Final[tuple[str, ...]] = (
    "audio/",
    "application/octet-stream",
    "binary/",
)


def utc_now() -> datetime:
    """Timezone-aware now. Health reports must never carry a naive timestamp."""
    return datetime.now(UTC)


def _has_marker(body: str, markers: tuple[str, ...]) -> bool:
    lowered = body.casefold()
    return any(marker in lowered for marker in markers)


def _excerpt(response: httpx.Response) -> str:
    try:
        text = response.text
    except (UnicodeDecodeError, httpx.ResponseNotRead, httpx.StreamError):
        return "<unreadable body>"
    return text[:MAX_ERROR_BODY_CHARS]


def classify_http_failure(
    *,
    provider: str,
    status_code: int,
    body: str,
    context: Mapping[str, Any] | None = None,
) -> BayramError:
    """Map one HTTP status (plus its body) onto our closed error taxonomy.

    Ordered most-specific first; every branch is an early return so the ladder reads
    top to bottom exactly as an operator would triage it.
    """
    merged: dict[str, Any] = {
        **dict(context or {}),
        "http_status": status_code,
        "body_excerpt": body,
    }
    message = f"{provider} returned HTTP {status_code}"

    if status_code in (_STATUS_UNAUTHORIZED, _STATUS_FORBIDDEN):
        return ProviderError(
            f"{message}: credentials rejected",
            provider=provider,
            code=ErrorCode.CONFIG_INVALID,
            user_message_key="error.service_unavailable",
            is_retryable=False,
            context=merged,
        )
    if status_code == _STATUS_PAYMENT_REQUIRED:
        return ProviderQuotaExhaustedError(
            f"{message}: balance or plan quota exhausted", provider=provider, context=merged
        )
    if status_code == _STATUS_TOO_MANY_REQUESTS:
        if _has_marker(body, _QUOTA_MARKERS):
            return ProviderQuotaExhaustedError(
                f"{message}: quota exhausted, not a transient rate limit",
                provider=provider,
                context=merged,
            )
        return ProviderRateLimitedError(
            f"{message}: rate limited", provider=provider, context=merged
        )
    if status_code < _STATUS_SERVER_ERROR_FLOOR and _has_marker(body, _POLICY_MARKERS):
        return ProviderRejectedContentError(
            f"{message}: refused on content policy grounds", provider=provider, context=merged
        )
    if status_code == _STATUS_REQUEST_TIMEOUT:
        return ProviderTimeoutError(
            f"{message}: upstream timed out", provider=provider, context=merged
        )
    if status_code >= _STATUS_SERVER_ERROR_FLOOR:
        return ProviderUnavailableError(
            f"{message}: vendor error", provider=provider, context=merged
        )
    if status_code >= _STATUS_CLIENT_ERROR_FLOOR:
        return ProviderError(
            f"{message}: request rejected",
            provider=provider,
            code=ErrorCode.INVALID_INPUT,
            user_message_key="error.invalid_input",
            is_retryable=False,
            context=merged,
        )
    return ProviderError(f"{message}: unexpected status", provider=provider, context=merged)


def http_status_of(error: BayramError) -> int | None:
    """Recover the HTTP status an error was classified from, when there was one."""
    value = error.context.get("http_status")
    return value if isinstance(value, int) else None


def health_from_error(
    failure: Err, *, provider: str, clock: Callable[[], datetime]
) -> Result[ProviderHealth]:
    """Turn a failed probe into a health line — or propagate a credentials failure.

    A vendor outage is a *reportable state*, not a failure of the probe: the caller asked
    how the vendor is doing and "badly" is a valid answer. Bad credentials are different.
    That is our misconfiguration, it will not fix itself, and smoothing it into a health
    line would hide the one failure an operator must act on immediately.
    """
    error = failure.error
    status = http_status_of(error)
    if error.error_code is ErrorCode.CONFIG_INVALID or status in (
        _STATUS_UNAUTHORIZED,
        _STATUS_FORBIDDEN,
    ):
        return err(error)
    state = (
        HealthState.UNAVAILABLE
        if status is None or status >= _STATUS_SERVER_ERROR_FLOOR
        else HealthState.DEGRADED
    )
    return ok(
        ProviderHealth(name=provider, state=state, as_of=clock(), detail=error.operator_message)
    )


async def send_request(
    client: httpx.AsyncClient,
    *,
    provider: str,
    method: str,
    url: str,
    timeout_s: float,
    headers: Mapping[str, str] | None = None,
    params: Mapping[str, str] | None = None,
    json_body: Any = None,
    data: Any = None,
    files: Any = None,
    context: Mapping[str, Any] | None = None,
) -> Result[httpx.Response]:
    """Perform one request. Returns ``Err`` for transport failures and any 4xx/5xx."""
    call_context: dict[str, Any] = {**dict(context or {}), "method": method, "url": url}
    try:
        response = await client.request(
            method,
            url,
            headers=dict(headers) if headers else None,
            params=dict(params) if params else None,
            json=json_body,
            data=data,
            files=files,
            timeout=timeout_s,
        )
    except httpx.TimeoutException as exc:
        return err(
            ProviderTimeoutError(
                f"{provider} timed out after {timeout_s}s",
                provider=provider,
                context={**call_context, "timeout_s": timeout_s},
                cause=exc,
            )
        )
    except httpx.TransportError as exc:
        return err(
            ProviderUnavailableError(
                f"{provider} transport failure: {exc}",
                provider=provider,
                context=call_context,
                cause=exc,
            )
        )
    except httpx.HTTPError as exc:
        return err(
            ProviderError(
                f"{provider} request failed: {exc}",
                provider=provider,
                context=call_context,
                cause=exc,
            )
        )

    if response.status_code >= _STATUS_CLIENT_ERROR_FLOOR:
        error = classify_http_failure(
            provider=provider,
            status_code=response.status_code,
            body=_excerpt(response),
            context=call_context,
        )
        _LOG.warning("speech vendor call failed", extra=error.to_log_dict())
        return err(error)
    return ok(response)


def parse_json_body[M: BaseModel](
    response: httpx.Response,
    model: type[M],
    *,
    provider: str,
    context: Mapping[str, Any] | None = None,
) -> Result[M]:
    """Decode and shape-validate a vendor JSON body. Never raises, never casts blindly."""
    merged: dict[str, Any] = {**dict(context or {}), "body_excerpt": _excerpt(response)}
    try:
        payload = response.json()
    except ValueError as exc:
        return err(
            ProviderInvalidResponseError(
                f"{provider} returned a body that is not JSON",
                provider=provider,
                context=merged,
                cause=exc,
            )
        )
    try:
        return ok(model.model_validate(payload))
    except PydanticValidationError as exc:
        return err(
            ProviderInvalidResponseError(
                f"{provider} JSON did not match {model.__name__}: {exc.error_count()} issue(s)",
                provider=provider,
                context={**merged, "schema": model.__name__},
                cause=exc,
            )
        )


def read_audio_body(
    response: httpx.Response,
    *,
    provider: str,
    context: Mapping[str, Any] | None = None,
) -> Result[bytes]:
    """Accept a body only when it is non-empty and actually declared as audio."""
    content_type = response.headers.get("content-type", "").split(";")[0].strip().casefold()
    merged: dict[str, Any] = {**dict(context or {}), "content_type": content_type}
    if not content_type.startswith(_AUDIO_CONTENT_TYPES):
        return err(
            ProviderInvalidResponseError(
                f"{provider} returned {content_type or '<none>'} where audio was expected",
                provider=provider,
                context={**merged, "body_excerpt": _excerpt(response)},
            )
        )
    data = response.content
    if not data:
        return err(
            ProviderInvalidResponseError(
                f"{provider} returned an empty audio body", provider=provider, context=merged
            )
        )
    return ok(data)
