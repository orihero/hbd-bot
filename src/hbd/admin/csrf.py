"""CSRF: an ``Origin`` match plus a header compared against the **stored** session token.

Plain double-submit — header equals cookie — is the design this replaces. It never reads
the column it defines, and it falls to anything that can write a cookie for the panel's
registrable domain: a sibling subdomain, or a machine-in-the-middle on any ``http://`` host
under it, both of which can set a cookie the browser will send and then echo the same value
in a header. So the header is compared against ``admin_sessions.csrf_token`` — a value the
attacker cannot read and cannot set — and the cookie is demoted to what it always was: the
transport that hands the SPA its token (ADMIN_PANEL_PLAN §12.1 T8).

Two of T8's three layers live here; the third, ``SameSite=Lax``, lives on the cookie. The
``Origin`` check is exact-match against the configured public origin, and a **missing**
``Origin`` on a state-changing request is a refusal: every browser that can reach this panel
sends it on non-GET, so absent means "not a browser we recognise".

Applies to every method that can change state. ``GET`` and ``HEAD`` are exempt because they
must be side-effect-free — asserted by the Slice 1c route-enumeration test, and that
assertion is also what makes ``SameSite=Lax`` safe here. ``OPTIONS`` is not exempt: this API
is same-origin and serves no CORS preflight, so an ``OPTIONS`` arriving without a token has
nothing to be doing.

Pure functions over primitives: the caller reads the header, the row and the settings, and
maps the returned :class:`CsrfDecision` onto the error envelope.
"""

from __future__ import annotations

import secrets
from enum import StrEnum
from typing import Final

__all__ = [
    "CSRF_HEADER_NAME",
    "CSRF_COOKIE_NAME",
    "SESSION_COOKIE_NAME",
    "CSRF_EXEMPT_METHODS",
    "CsrfDecision",
    "is_csrf_protected_method",
    "verify_origin",
    "verify_csrf_token",
    "verify_csrf_request",
]

CSRF_HEADER_NAME: Final[str] = "X-CSRF-Token"
#: ``__Host-`` is not cosmetic: the prefix makes the browser refuse the cookie unless it is
#: ``Secure``, ``Path=/`` and has no ``Domain``, which structurally prevents exactly the
#: sibling-subdomain injection that broke plain double-submit.
CSRF_COOKIE_NAME: Final[str] = "__Host-hbd_csrf"
SESSION_COOKIE_NAME: Final[str] = "__Host-hbd_session"

#: Everything else — POST, PUT, PATCH, DELETE, OPTIONS — must carry a token.
CSRF_EXEMPT_METHODS: Final[frozenset[str]] = frozenset({"GET", "HEAD"})


class CsrfDecision(StrEnum):
    """Why a state-changing request was accepted or refused.

    Separate reasons because they are separate incidents: a missing header is usually a
    stale SPA build, a mismatch after a session rotation is a stale tab, and an origin
    mismatch is a cross-site attempt worth logging as one.
    """

    ALLOWED = "allowed"
    ORIGIN_MISSING = "origin_missing"
    ORIGIN_MISMATCH = "origin_mismatch"
    TOKEN_MISSING = "token_missing"
    SESSION_TOKEN_MISSING = "session_token_missing"
    TOKEN_MISMATCH = "token_mismatch"


def is_csrf_protected_method(method: str) -> bool:
    """True for every method that may change state."""
    return method.upper() not in CSRF_EXEMPT_METHODS


def verify_origin(origin: str | None, *, expected_origin: str) -> CsrfDecision:
    """Exact string match against the configured public origin. Absent is a refusal."""
    if not origin:
        return CsrfDecision.ORIGIN_MISSING
    if origin != expected_origin:
        return CsrfDecision.ORIGIN_MISMATCH
    return CsrfDecision.ALLOWED


def _is_comparable(token: str) -> bool:
    """``compare_digest`` raises on non-ASCII ``str``; a non-ASCII token cannot be ours."""
    return bool(token) and token.isascii()


def verify_csrf_token(header_token: str | None, *, stored_token: str | None) -> CsrfDecision:
    """Compare the ``X-CSRF-Token`` header against the session row's stored token.

    ``stored_token`` comes from ``admin_sessions.csrf_token``, never from a cookie. The
    comparison is constant-time: the token is a per-session secret, and a timing oracle on
    it would hand an attacker the one value this control depends on.
    """
    if header_token is None or not _is_comparable(header_token):
        return CsrfDecision.TOKEN_MISSING
    if stored_token is None or not _is_comparable(stored_token):
        # No live session token to compare against: refuse rather than fall back to the
        # cookie, which is the failure mode this whole design exists to remove.
        return CsrfDecision.SESSION_TOKEN_MISSING
    if not secrets.compare_digest(header_token, stored_token):
        return CsrfDecision.TOKEN_MISMATCH
    return CsrfDecision.ALLOWED


def verify_csrf_request(
    *,
    method: str,
    origin: str | None,
    expected_origin: str,
    header_token: str | None,
    stored_token: str | None,
) -> CsrfDecision:
    """Both layers, in order, for one request. ``ALLOWED`` only when every layer passes.

    Safe methods return ``ALLOWED`` without inspecting anything, because they change
    nothing; a GET that changes state is a routing bug, caught by the route-enumeration
    test rather than papered over here.
    """
    if not is_csrf_protected_method(method):
        return CsrfDecision.ALLOWED
    origin_decision = verify_origin(origin, expected_origin=expected_origin)
    if origin_decision is not CsrfDecision.ALLOWED:
        return origin_decision
    return verify_csrf_token(header_token, stored_token=stored_token)
