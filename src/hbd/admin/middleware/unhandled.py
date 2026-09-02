"""The catch-all for an unexpected exception — placed *inside* the middleware stack.

``add_exception_handler(Exception, ...)`` is not a handler like the other three.
``Starlette.build_middleware_stack`` pulls the ``Exception``/``500`` key out of the handler
map and hands it to ``ServerErrorMiddleware``, which it installs **outside** every
``add_middleware`` layer. A 500 rendered there is a response no other middleware in this
package ever observes, and Slice 1a shipped with all three consequences:

* no ``X-Content-Type-Options: nosniff``, no CSP, no ``Cache-Control: no-store`` and no
  ``X-Correlation-ID`` — the headers were ``{content-length, content-type}`` and nothing
  else, contradicting §12.1 T7 and T10 and Slice 1a's acceptance criterion 10;
* the correlation scope had already unwound by the time the exception reached that far, so
  the envelope's ``correlationId`` **and** the incident log line both read ``-`` while the
  request line carried the real id — the one join an incident actually needs, broken;
* ``RequestLogMiddleware`` never saw an ``http.response.start``, so it logged the failure at
  INFO with ``status: null``.

So the catch-all is a middleware. Added **first** in ``create_app`` — Starlette inserts each
``add_middleware`` at position 0, so first-added is innermost — it lands just outside
Starlette's own ``ExceptionMiddleware``, which still answers every registered handler
(``ProblemError``, ``RequestValidationError``, ``HTTPException``) exactly as before. Only what
that middleware re-raises reaches here, and the response produced travels back out through the
request log, the security headers and the correlation echo like any other response.

``ServerErrorMiddleware`` stays where Starlette put it, now with no handler: it is the
backstop for a failure in this middleware itself, which is the one place it belongs.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Final

from starlette.requests import Request
from starlette.responses import Response
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from hbd.logging import correlation_scope, current_correlation_id

__all__ = ["CORRELATION_STATE_KEY", "ErrorRenderer", "UnhandledErrorMiddleware"]

#: Where :class:`~hbd.admin.middleware.correlation.CorrelationIdMiddleware` publishes the id
#: it bound. Read as a fallback so this middleware still renders a joinable envelope if it is
#: ever mounted outside that one.
CORRELATION_STATE_KEY: Final[str] = "correlation_id"

_RESPONSE_START: Final[str] = "http.response.start"
_HTTP: Final[str] = "http"

#: What renders an exception into the envelope. Injected rather than imported so this module
#: stays free of ``hbd.admin.errors`` and the two can be tested apart.
type ErrorRenderer = Callable[[Request, Exception], Awaitable[Response]]


def _bound_correlation_id(scope: Scope) -> str:
    """The id this request was handled under: the scope's, or whatever is bound now."""
    state = scope.get("state")
    if isinstance(state, dict):
        published = state.get(CORRELATION_STATE_KEY)
        if isinstance(published, str) and published:
            return published
    return current_correlation_id()


class UnhandledErrorMiddleware:
    """Render an unexpected exception as the API's own envelope, in-stack."""

    __slots__ = ("_app", "_render")

    def __init__(self, app: ASGIApp, *, render: ErrorRenderer) -> None:
        self._app = app
        self._render = render

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != _HTTP:
            await self._app(scope, receive, send)
            return
        started = _StartWatch()
        try:
            await self._app(scope, receive, started.watching(send))
        except Exception as exc:
            if started.has_started:
                # Bytes are already on the wire and a second ``http.response.start`` is a
                # protocol violation, so the only honest move is to let the server tear the
                # connection down. Never swallowed: it propagates to ServerErrorMiddleware.
                raise
            # Re-bound rather than assumed: the envelope, the incident line and the echoed
            # header must all be the same string, which is the whole point of the id.
            with correlation_scope(_bound_correlation_id(scope)):
                response = await self._render(Request(scope, receive), exc)
                await response(scope, receive, send)


class _StartWatch:
    """Remembers whether a response has begun. One bit, but it decides recoverability."""

    __slots__ = ("has_started",)

    def __init__(self) -> None:
        self.has_started = False

    def watching(self, send: Send) -> Send:
        async def send_watching(message: Message) -> None:
            if message["type"] == _RESPONSE_START:
                self.has_started = True
            await send(message)

        return send_watching
