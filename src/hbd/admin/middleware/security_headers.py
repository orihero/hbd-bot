"""The response headers that make a stored name, note or lyric un-executable in a browser.

``X-Content-Type-Options: nosniff`` on **every** response, not only on the ones that look
dangerous. §12.1 T7 is explicit about why: the panel's bodies are customer-written free text
served same-origin, and a body the browser is allowed to sniff as HTML runs at the panel's
origin under the operator's session cookie. ``script-src 'self'`` does not stop an inline
event handler inside such a document, so the sniff has to be refused rather than survived.

``Cache-Control: no-store`` on every response, for the same reason at rest (§12.1 T10): a
disk cache is a copy of personal data that outlives every retention clock in this system and
that ``hbd.db.purge`` cannot reach.

The one exception is :data:`IMMUTABLE_PATH_PREFIX`, the SPA bundle Slice 1d mounts. Those
files hold no data — they are the JavaScript and CSS that *renders* it — and Vite gives every
one of them a content hash in its filename, so a changed file is a changed URL and a
year-long immutable cache can never serve a stale bundle. The carve-out is a prefix match on
the request path and nothing else: it cannot be widened by a handler, and every byte outside
it is still ``no-store``.

``Referrer-Policy: no-referrer`` because a panel URL carries order and user ids in its path.

The CSP is §12.1 T7's, verbatim, with a **fresh style nonce per response**. The nonce is
published on the request state under :data:`STYLE_NONCE_STATE_KEY`, and it has exactly one
consumer: :func:`hbd.admin.shell.render_shell` stamps it into the SPA shell's ``csp-nonce``
meta element so the bundle can hand it to the libraries that inject a ``<style>`` element at
runtime (``react-remove-scroll``'s modal scroll lock, mounted by every Radix dialog). Nothing
else may use it, and a nonce reused across responses is not a nonce.
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
    "IMMUTABLE_PATH_PREFIX",
    "IMMUTABLE_CACHE_CONTROL",
    "NO_STORE",
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

#: The SPA bundle's own prefix, and the only path under which a response may be cached.
#: Matched with a trailing slash so a future ``/assets-of-customers`` route cannot inherit
#: the exemption by sharing a prefix.
IMMUTABLE_PATH_PREFIX: Final[str] = "/assets/"

#: One year, immutable. Safe only because every filename under the prefix carries a content
#: hash: a changed file is a changed URL, so there is nothing for a cache to hold stale.
IMMUTABLE_CACHE_CONTROL: Final[bytes] = b"public, max-age=31536000, immutable"

#: What everything else gets, whatever produced it.
NO_STORE: Final[bytes] = b"no-store"

_RESPONSE_START: Final[str] = "http.response.start"
_HTTP: Final[str] = "http"
_CSP_HEADER: Final[bytes] = b"content-security-policy"
_CACHE_CONTROL_HEADER: Final[bytes] = b"cache-control"

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
        await self._app(scope, receive, _hardening(send, nonce, cache_control_for(scope)))


def cache_control_for(scope: Scope) -> bytes:
    """``no-store``, unless this is the SPA bundle.

    Read off the raw request path rather than off a matched route, because the decision must
    not depend on which handler answered — a 404 for a missing chunk under the prefix is as
    cacheable as the chunk would have been, and a handler cannot opt a data-bearing path in.
    """
    path = scope.get("path", "")
    if isinstance(path, str) and path.startswith(IMMUTABLE_PATH_PREFIX):
        return IMMUTABLE_CACHE_CONTROL
    return NO_STORE


def _hardening(send: Send, nonce: str, cache_control: bytes) -> Send:
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
            kept.extend(
                (name, value) for name, value in SECURITY_HEADERS if name != _CACHE_CONTROL_HEADER
            )
            kept.append((_CACHE_CONTROL_HEADER, cache_control))
            kept.append((_CSP_HEADER, csp))
            message = {**message, "headers": kept}
        await send(message)

    return send_hardened
