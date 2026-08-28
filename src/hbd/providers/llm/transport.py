"""HTTP plumbing shared by every LLM adapter. Nothing here raises.

One job: turn "an HTTP call to a vendor" into ``Result[dict]`` with the right typed error,
so an adapter contains prompt-building and payload-reading and nothing else. The status
mapping is the interesting part — it decides whether the retry ladder gets another go, and
that decision belongs here rather than being re-guessed at three call sites.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Final

import httpx

from hbd.contracts import Err, Result, err, ok
from hbd.errors import (
    HbdError,
    ProviderError,
    ProviderQuotaExhaustedError,
    ProviderRateLimitedError,
    ProviderRejectedContentError,
    ProviderTimeoutError,
    ProviderUnavailableError,
)
from hbd.errors import ProviderInvalidResponseError as InvalidResponse
from hbd.logging import get_logger

__all__ = ["request_json", "read_path", "read_str", "MAX_ERROR_BODY_CHARS"]

_LOG = get_logger(__name__)

#: A vendor error body is diagnostic, not a document. Keep it bounded before it reaches
#: an error context that may be carried through several retry frames.
MAX_ERROR_BODY_CHARS: Final[int] = 1_000

_HTTP_TOO_MANY_REQUESTS: Final[int] = 429
_HTTP_PAYMENT_REQUIRED: Final[int] = 402
_HTTP_FORBIDDEN: Final[int] = 403
_HTTP_NOT_FOUND: Final[int] = 404
_HTTP_BAD_REQUEST: Final[int] = 400
_HTTP_UNPROCESSABLE: Final[int] = 422
_HTTP_CLIENT_ERROR_FLOOR: Final[int] = 400
_HTTP_SERVER_ERROR_FLOOR: Final[int] = 500

#: Only these statuses can plausibly carry a content refusal. Matching refusal words
#: against any 4xx body is how a 404 whose HTML happens to contain "violate" — a footer
#: link to an acceptable-use policy — gets reported as a moderation block, sending whoever
#: reads it to rewrite a perfectly good prompt instead of fixing the URL.
_CONTENT_REFUSAL_STATUSES: Final[frozenset[int]] = frozenset(
    {_HTTP_BAD_REQUEST, _HTTP_FORBIDDEN, _HTTP_UNPROCESSABLE}
)

#: Substrings that mean "we refused your content", not "we are broken". Vendors return
#: these under 400 alongside ordinary validation failures, so the body decides.
_CONTENT_REFUSAL_MARKERS: Final[tuple[str, ...]] = (
    "safety",
    "blocked",
    "content polic",
    "content_polic",
    "prohibited",
    "violat",
)

#: Substrings that mean the account is out of money or plan quota, which no retry fixes.
_QUOTA_MARKERS: Final[tuple[str, ...]] = (
    "quota",
    "insufficient",
    "billing",
    "credit",
    "exceeded your current",
)


def read_path(payload: Any, *path: str | int) -> Any:
    """Walk a decoded JSON payload defensively. Returns ``None`` at the first mismatch.

    Never casts, never indexes something that is not indexable. This is the only way
    vendor JSON is read in this package.
    """
    node = payload
    for step in path:
        if isinstance(step, int):
            if not isinstance(node, list) or not -len(node) <= step < len(node):
                return None
            node = node[step]
            continue
        if not isinstance(node, Mapping) or step not in node:
            return None
        node = node[step]
    return node


def read_str(payload: Any, *path: str | int) -> str | None:
    """``read_path`` narrowed to a non-empty string."""
    value = read_path(payload, *path)
    return value if isinstance(value, str) and value else None


def _classify(status: int, body: str, *, provider: str) -> HbdError:
    """Map a 4xx/5xx status and body to a typed error. Only called for status >= 400."""
    lowered = body.lower()
    has_quota_marker = any(marker in lowered for marker in _QUOTA_MARKERS)
    context = {"status_code": status, "response_body": body[:MAX_ERROR_BODY_CHARS]}

    if status == _HTTP_TOO_MANY_REQUESTS:
        if has_quota_marker:
            return ProviderQuotaExhaustedError(
                f"{provider} reports the plan quota or balance is exhausted",
                provider=provider,
                context=context,
            )
        return ProviderRateLimitedError(
            f"{provider} rate-limited the request", provider=provider, context=context
        )
    if status in (_HTTP_PAYMENT_REQUIRED, _HTTP_FORBIDDEN) and has_quota_marker:
        return ProviderQuotaExhaustedError(
            f"{provider} refused the request for billing reasons",
            provider=provider,
            context=context,
        )
    if status >= _HTTP_SERVER_ERROR_FLOOR:
        return ProviderUnavailableError(
            f"{provider} returned HTTP {status}", provider=provider, context=context
        )
    if status == _HTTP_NOT_FOUND:
        return ProviderError(
            f"{provider} has no endpoint at the configured URL (HTTP 404). Check the base "
            "URL and the model id — a gateway base URL that already ends in '/v1' is the "
            "usual cause. No retry can fix this.",
            provider=provider,
            is_retryable=False,
            context=context,
        )
    if status in _CONTENT_REFUSAL_STATUSES and any(
        marker in lowered for marker in _CONTENT_REFUSAL_MARKERS
    ):
        return ProviderRejectedContentError(
            f"{provider} refused the payload on content grounds",
            provider=provider,
            context=context,
        )
    return ProviderError(
        f"{provider} rejected the request with HTTP {status}",
        provider=provider,
        context=context,
    )


async def _send(
    client: httpx.AsyncClient,
    *,
    method: str,
    url: str,
    headers: Mapping[str, str],
    provider: str,
    timeout_s: float,
    json_body: Mapping[str, Any] | None,
) -> Result[httpx.Response]:
    """One HTTP round trip. Every transport failure becomes a typed ``Err``; none escape."""
    try:
        return ok(
            await client.request(
                method,
                url,
                headers=dict(headers),
                json=dict(json_body) if json_body is not None else None,
                timeout=timeout_s,
            )
        )
    except httpx.TimeoutException as exc:
        return err(
            ProviderTimeoutError(
                f"{provider} did not respond within {timeout_s}s",
                provider=provider,
                context={"timeout_s": timeout_s, "url": url},
                cause=exc,
            )
        )
    except httpx.HTTPError as exc:
        return err(
            ProviderUnavailableError(
                f"{provider} transport failure: {exc}",
                provider=provider,
                context={"url": url},
                cause=exc,
            )
        )
    except Exception as exc:  # an unexpected client bug must still be a Result
        _LOG.exception("unexpected failure calling %s", provider, extra={"url": url})
        return err(
            ProviderError(
                f"{provider} call failed unexpectedly: {exc}",
                provider=provider,
                context={"url": url},
                cause=exc,
            )
        )


async def request_json(
    client: httpx.AsyncClient,
    *,
    method: str,
    url: str,
    headers: Mapping[str, str],
    provider: str,
    timeout_s: float,
    json_body: Mapping[str, Any] | None = None,
) -> Result[Any]:
    """Perform one HTTP call and decode its JSON envelope.

    ``Ok`` carries the decoded body — which is still untrusted data, read only through
    ``read_path``. Every failure mode below is a typed ``Err``; none of them escape.
    """
    sent = await _send(
        client,
        method=method,
        url=url,
        headers=headers,
        provider=provider,
        timeout_s=timeout_s,
        json_body=json_body,
    )
    if isinstance(sent, Err):
        return sent
    response = sent.value

    if response.status_code >= _HTTP_CLIENT_ERROR_FLOOR:
        return err(_classify(response.status_code, response.text, provider=provider))

    try:
        return ok(response.json())
    except ValueError as exc:
        return err(
            InvalidResponse(
                f"{provider} returned HTTP {response.status_code} with a non-JSON body",
                provider=provider,
                context={
                    "status_code": response.status_code,
                    "response_body": response.text[:MAX_ERROR_BODY_CHARS],
                },
                cause=exc,
            )
        )
