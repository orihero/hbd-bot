"""Cross-cutting ASGI middleware: a correlation id, and the response security headers.

Both are written as raw ASGI callables rather than as
``starlette.middleware.base.BaseHTTPMiddleware`` subclasses. That base class wraps every
response in an anyio task group and buffers it through a memory stream, which changes the
shape of streaming responses — and Phase 2 streams range-served audio through exactly this
stack. A raw middleware wraps ``send``, touches the ``http.response.start`` message, and
leaves every byte after it alone.

:class:`~hbd.admin.middleware.unhandled.UnhandledErrorMiddleware` is here for a different
reason: a catch-all registered through ``add_exception_handler(Exception, ...)`` runs in
``ServerErrorMiddleware``, *outside* the two above, so its 500 carried none of their headers
and none of their correlation id. Written as a middleware, it sits inside them instead.
"""

from __future__ import annotations

from hbd.admin.middleware.correlation import (
    CORRELATION_HEADER,
    CorrelationIdMiddleware,
    is_valid_correlation_id,
)
from hbd.admin.middleware.security_headers import (
    CSP_TEMPLATE,
    SecurityHeadersMiddleware,
    build_csp,
)
from hbd.admin.middleware.unhandled import ErrorRenderer, UnhandledErrorMiddleware

__all__ = [
    "CORRELATION_HEADER",
    "CorrelationIdMiddleware",
    "is_valid_correlation_id",
    "CSP_TEMPLATE",
    "SecurityHeadersMiddleware",
    "build_csp",
    "ErrorRenderer",
    "UnhandledErrorMiddleware",
]
