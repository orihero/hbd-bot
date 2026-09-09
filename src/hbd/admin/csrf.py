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
    "ANY_ORIGIN",
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

#: Configured as ``HBD_ADMIN_PUBLIC_ORIGIN=*``: accept every ``Origin``, and accept a
#: request that carries none. This turns the pre-session half of T8 OFF — the origin check
#: is the ONLY CSRF layer a login has, so with it set, any page on the internet can POST
#: ``/api/auth/login`` and every other mutation at a panel the browser holds a cookie for.
#: :meth:`AdminSettings.accepted_origins` refuses it outside ``dev`` for that reason. It
#: exists so that a developer running the SPA on whatever port Vite picked today does not
#: have to restart the API to change one string.
ANY_ORIGIN: Final[str] = "*"

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


def verify_origin(origin: str | None, *, accepted_origins: frozenset[str]) -> CsrfDecision:
    """Exact string match against the accepted origins. Absent is a refusal.

    A set rather than one string only so that ``dev`` can accept ``localhost`` and
    ``127.0.0.1`` as the one machine they are (``settings.accepted_origins``). Membership is
    still exact — no prefix, suffix or subdomain matching — and outside ``dev`` the set holds
    exactly one element, so this is the same control it was.

    :data:`ANY_ORIGIN` in the set is the one exception, and it is a hole rather than a wider
    match: it allows every origin AND the absent one, because a check that waves through
    anything a browser sends but still refuses a request that sends nothing would keep
    blocking the ``curl`` and the alternate dev port this setting is reached for.
    ``accepted_origins`` only ever produces it in ``dev``.
    """
    if ANY_ORIGIN in accepted_origins:
        return CsrfDecision.ALLOWED
    if not origin:
        return CsrfDecision.ORIGIN_MISSING
    if origin not in accepted_origins:
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
    accepted_origins: frozenset[str],
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
    origin_decision = verify_origin(origin, accepted_origins=accepted_origins)
    if origin_decision is not CsrfDecision.ALLOWED:
        return origin_decision
    return verify_csrf_token(header_token, stored_token=stored_token)
