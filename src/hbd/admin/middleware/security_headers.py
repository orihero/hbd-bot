"""The response headers that make a stored name, note or lyric un-executable in a browser.

``X-Content-Type-Options: nosniff`` on **every** response, not only on the ones that look
dangerous. §12.1 T7 is explicit about why: the panel's bodies are customer-written free text
served same-origin, and a body the browser is allowed to sniff as HTML runs at the panel's
origin under the operator's session cookie. ``script-src 'self'`` does not stop an inline
event handler inside such a document, so the sniff has to be refused rather than survived.

``Cache-Control: no-store`` on every response, for the same reason at rest (§12.1 T10): a
disk cache is a copy of personal data that outlives every retention clock in this system and
that ``hbd.db.purge`` cannot reach. When Slice 1d mounts the SPA bundle, that prefix — and
only that prefix, because those files hold no data — gets normal immutable caching.

``Referrer-Policy: no-referrer`` because a panel URL carries order and user ids in its path.

The CSP is §12.1 T7's, verbatim, with a **fresh style nonce per response**. The nonce is
published on the request state so the SPA's HTML shell can stamp it into its one inline
style block; nothing else may use it, and a nonce reused across responses is not a nonce.
"""

from __future__ import annotations

import secrets
from typing import Final

from starlette.types import ASGIApp, Message, Receive, Scope, Send

__all__ = [
    "CSP_TEMPLATE",
    "NONCE_BYTES",
    "STYLE_NONCE_STATE_KEY",
    "SECURITY_HEADERS",
    "SecurityHeadersMiddleware",
    "build_csp",
]

#: 128 bits of CSPRNG output, base64url-encoded. The spec asks for at least 128.
NONCE_BYTES: Final[int] = 16

#: Where the per-response nonce is published for a template to read.
STYLE_NONCE_STATE_KEY: Final[str] = "style_nonce"

#: §12.1 T7, verbatim. ``object-src``, ``base-uri``, ``frame-ancestors``, ``form-action`` and
#: ``worker-src`` are all ``'none'`` rather than omitted: each defaults to something
#: permissive, and this panel needs none of them.
CSP_TEMPLATE: Final[str] = (
    "default-src 'self'; "
    "script-src 'self'; "
    "style-src 'self' 'nonce-{nonce}'; "
    "img-src 'self' data:; "
    "media-src 'self'; "
    "connect-src 'self'; "
    "object-src 'none'; "
    "base-uri 'none'; "
    "frame-ancestors 'none'; "
    "form-action 'none'; "
    "worker-src 'none'"
)

#: The three constants. The CSP is per-response and is added alongside them.
SECURITY_HEADERS: Final[tuple[tuple[bytes, bytes], ...]] = (
    (b"x-content-type-options", b"nosniff"),
    (b"referrer-policy", b"no-referrer"),
    (b"cache-control", b"no-store"),
)

_RESPONSE_START: Final[str] = "http.response.start"
_HTTP: Final[str] = "http"
_CSP_HEADER: Final[bytes] = b"content-security-policy"

#: The header names this middleware owns outright. Anything already carrying one of these is
#: replaced, never duplicated.
_MANAGED_HEADERS: Final[frozenset[bytes]] = frozenset(
    {name for name, _ in SECURITY_HEADERS} | {_CSP_HEADER}
)


def build_csp(nonce: str) -> str:
    """The policy for one response, carrying that response's style nonce."""
    return CSP_TEMPLATE.format(nonce=nonce)


class SecurityHeadersMiddleware:
    """Stamp the security headers onto every response this application produces."""

    __slots__ = ("_app",)

    def __init__(self, app: ASGIApp) -> None:
        self._app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != _HTTP:
            await self._app(scope, receive, send)
            return
        nonce = secrets.token_urlsafe(NONCE_BYTES)
        scope.setdefault("state", {})[STYLE_NONCE_STATE_KEY] = nonce
        await self._app(scope, receive, _hardening(send, nonce))


def _hardening(send: Send, nonce: str) -> Send:
    """Wrap ``send`` so the response start carries the headers, whatever produced it.

    Applied to the ``http.response.start`` message rather than to a ``Response`` object so
    that an exception handler's body, a 404 from the router and a streamed range response
    are all covered by exactly the same code.
    """
    csp = build_csp(nonce).encode("latin-1")

    async def send_hardened(message: Message) -> None:
        if message["type"] == _RESPONSE_START:
            # Replace rather than append: two Cache-Control headers is one header a proxy
            # may resolve either way, and the way that loses is the one that caches.
            kept = [
                (name, value)
                for name, value in message.get("headers", [])
                if name.lower() not in _MANAGED_HEADERS
            ]
            kept.extend(SECURITY_HEADERS)
            kept.append((_CSP_HEADER, csp))
            message = {**message, "headers": kept}
        await send(message)

    return send_hardened
