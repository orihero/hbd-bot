"""One structured log line per request — of the route **template**, never the raw path.

§12.1 T6 is the whole design here. ``JsonFormatter`` escapes newlines because it serialises
one object per record, but that only protects the *shape* of a line; it does not stop a URL
from carrying data into it. An admin path carries order ids, Telegram user ids and query
strings, and the redaction layer matches on the **extra key**, not on URL substrings, so a
``?token=…`` in a logged path would sail straight through unmasked.

So the logged path is ``scope["route"].path`` — ``/api/auth/login``, ``/orders/{order_id}``
— which is a compile-time constant of this codebase, and an unmatched request is logged as a
single constant rather than as whatever was asked for. The status, the duration and the
correlation id are what make the line useful; the raw target is what makes it a liability.

Nothing here logs a body, a header or a cookie.
"""

from __future__ import annotations

import time
from typing import Final

from starlette.routing import Route
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from hbd.logging import get_logger

__all__ = ["UNMATCHED_ROUTE", "RequestLogMiddleware"]

_LOGGER: Final = get_logger(__name__)

#: What an unrouted request is logged as. A constant, so a 404 sweep cannot write the
#: attacker's chosen paths into the log for someone to read back later.
UNMATCHED_ROUTE: Final[str] = "<unmatched>"

_RESPONSE_START: Final[str] = "http.response.start"
_HTTP: Final[str] = "http"
_MS_PER_S: Final[int] = 1_000
_SERVER_ERROR: Final[int] = 500


class RequestLogMiddleware:
    """Log method, route template, status and duration once per request."""

    __slots__ = ("_app",)

    def __init__(self, app: ASGIApp) -> None:
        self._app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != _HTTP:
            await self._app(scope, receive, send)
            return
        started = time.perf_counter()
        seen: list[int] = []

        async def send_watching_status(message: Message) -> None:
            if message["type"] == _RESPONSE_START:
                seen.append(int(message["status"]))
            await send(message)

        try:
            await self._app(scope, receive, send_watching_status)
        finally:
            # In a ``finally`` so a request that dies mid-stream is still accounted for; an
            # unfinished response is the one that most needs a line.
            _log(scope, status=seen[0] if seen else None, started=started)


def _route_template(scope: Scope) -> str:
    route = scope.get("route")
    return route.path if isinstance(route, Route) else UNMATCHED_ROUTE


def _log(scope: Scope, *, status: int | None, started: float) -> None:
    duration_ms = round((time.perf_counter() - started) * _MS_PER_S, 2)
    payload = {
        "event": "admin.request",
        "method": scope.get("method", ""),
        "route": _route_template(scope),
        "status": status,
        "duration_ms": duration_ms,
    }
    # This branch was a coverage mirage until the catch-all moved into the stack. The only
    # thing that produces a 500 here is an unhandled exception, and Starlette answered those
    # in ``ServerErrorMiddleware`` — outside this middleware — so no ``response.start`` ever
    # reached the wrapper above and every real 500 was logged by the INFO line below with
    # ``status: null``. The green coverage came from a synthetic ASGI app that merely *sent*
    # a 500. ``UnhandledErrorMiddleware`` now sits inside this one, so a real failure reaches
    # here; assert that with a route that raises, never with an app that sends.
    if status is not None and status >= _SERVER_ERROR:
        _LOGGER.error("admin request failed", extra=payload)
        return
    _LOGGER.info("admin request", extra=payload)
