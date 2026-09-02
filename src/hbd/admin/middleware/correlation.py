"""One correlation id per request: validated if supplied, generated if not, always echoed.

An inbound ``X-Correlation-ID`` is accepted **only** when it matches ``^[0-9a-f]{32}$`` —
the exact shape ``hbd.logging.new_correlation_id`` produces — and silently replaced
otherwise. This is not input hygiene for its own sake (§6.1). The id is the join key between
an operator's audit rows and an order's log stream, so a client-chosen string reflected into
a response header and later written to ``admin_audit_log.correlation_id`` would let anyone
with a session forge that join and poison the investigation surface the header exists for.
Silently, because telling a caller their id was rejected invites them to guess a shape that
is accepted.

The id is bound through ``hbd.logging.correlation_scope``, so every log line the request
produces carries it without any function taking it as an argument, and the binding is
restored on the way out — a leaked one would attach this request's id to whatever the event
loop ran next.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from typing import Final

from starlette.types import ASGIApp, Message, Receive, Scope, Send

from hbd.logging import correlation_scope

__all__ = [
    "CORRELATION_HEADER",
    "CORRELATION_PATTERN",
    "CorrelationIdMiddleware",
    "is_valid_correlation_id",
]

CORRELATION_HEADER: Final[str] = "X-Correlation-ID"

#: ``uuid4().hex`` and nothing else. Not case-insensitive: the generator emits lowercase, so
#: an uppercase variant is a different string that would index differently in a log search.
CORRELATION_PATTERN: Final[re.Pattern[str]] = re.compile(r"^[0-9a-f]{32}$")

_HEADER_KEY: Final[bytes] = b"x-correlation-id"
_RESPONSE_START: Final[str] = "http.response.start"
_HTTP: Final[str] = "http"


def is_valid_correlation_id(value: str | None) -> bool:
    """True only for the exact shape this system generates."""
    return value is not None and CORRELATION_PATTERN.fullmatch(value) is not None


def _inbound_id(scope: Scope) -> str | None:
    headers: Iterable[tuple[bytes, bytes]] = scope.get("headers", ())
    for key, value in headers:
        if key == _HEADER_KEY:
            return value.decode("latin-1")
    return None


class CorrelationIdMiddleware:
    """Bind a correlation id for the request, and echo it on the response."""

    __slots__ = ("_app",)

    def __init__(self, app: ASGIApp) -> None:
        self._app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != _HTTP:
            await self._app(scope, receive, send)
            return
        inbound = _inbound_id(scope)
        accepted = inbound if is_valid_correlation_id(inbound) else None
        with correlation_scope(accepted) as correlation_id:
            scope.setdefault("state", {})["correlation_id"] = correlation_id
            await self._app(scope, receive, _echoing(send, correlation_id))


def _echoing(send: Send, correlation_id: str) -> Send:
    """Wrap ``send`` so the response start carries the id this request was handled under."""
    encoded = correlation_id.encode("latin-1")

    async def send_with_header(message: Message) -> None:
        if message["type"] == _RESPONSE_START:
            headers: list[tuple[bytes, bytes]] = list(message.get("headers", []))
            headers.append((_HEADER_KEY, encoded))
            message = {**message, "headers": headers}
        await send(message)

    return send_with_header
