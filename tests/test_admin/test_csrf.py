"""CSRF, and the token material it compares — the stored-value half of §12.1 T8.

The test this file exists for is
:func:`test_a_header_matching_the_cookie_but_not_the_session_row_is_refused`. Plain
double-submit passes it by accident when cookie and header agree, which is exactly the
state an attacker who can write a cookie for the registrable domain arranges. Comparing
against ``admin_sessions.csrf_token`` is the difference, so the test hands the verifier a
cookie-shaped value that is not the session's and requires a refusal.

The token generators live in ``security/tokens.py`` and are asserted here because that is
where their output is consumed: a CSRF token that does not fit ``String(64)``, or a session
token whose stored digest is not the digest of the raw value, breaks this control and the
session lookup respectively.
"""

from __future__ import annotations

from typing import Final

import pytest

from bayram.admin.csrf import (
    ANY_ORIGIN,
    CSRF_COOKIE_NAME,
    CSRF_EXEMPT_METHODS,
    CSRF_HEADER_NAME,
    SESSION_COOKIE_NAME,
    CsrfDecision,
    is_csrf_protected_method,
    verify_csrf_request,
    verify_csrf_token,
    verify_origin,
)
from bayram.admin.security.tokens import (
    generate_csrf_token,
    issue_session_token,
    sha256_hex,
)
from bayram.db.base import SHA256_LENGTH

_ORIGIN: Final[str] = "https://admin.bayram.example"
_STORED: Final[str] = "s7Q1m_stored-session-csrf-token"
_CSRF_COLUMN_CHARS: Final[int] = 64


def _verify(
    *,
    method: str = "POST",
    origin: str | None = _ORIGIN,
    header_token: str | None = _STORED,
    stored_token: str | None = _STORED,
) -> CsrfDecision:
    return verify_csrf_request(
        method=method,
        origin=origin,
        accepted_origins=frozenset({_ORIGIN}),
        header_token=header_token,
        stored_token=stored_token,
    )


# ---------------------------------------------------------------------------
# Which methods are covered
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("method", ["GET", "HEAD", "get", "head"])
def test_safe_methods_are_exempt_because_they_change_nothing(method: str) -> None:
    assert is_csrf_protected_method(method) is False
    assert _verify(method=method, origin=None, header_token=None) is CsrfDecision.ALLOWED


@pytest.mark.parametrize("method", ["POST", "PUT", "PATCH", "DELETE", "OPTIONS", "post"])
def test_every_state_changing_method_is_covered(method: str) -> None:
    """ "Every non-GET" includes OPTIONS: this API is same-origin and serves no preflight."""
    assert is_csrf_protected_method(method) is True
    assert _verify(method=method, header_token=None) is CsrfDecision.TOKEN_MISSING


def test_the_exempt_set_is_exactly_get_and_head() -> None:
    assert frozenset({"GET", "HEAD"}) == CSRF_EXEMPT_METHODS


# ---------------------------------------------------------------------------
# The stored comparison
# ---------------------------------------------------------------------------
def test_a_header_matching_the_session_row_is_accepted() -> None:
    assert _verify() is CsrfDecision.ALLOWED


def test_a_header_matching_the_cookie_but_not_the_session_row_is_refused() -> None:
    """The acceptance criterion, and the whole reason the column exists.

    ``injected`` stands in for a cookie an attacker set from a sibling subdomain and then
    echoed in the header. Plain double-submit sees two equal strings and allows it.
    """
    injected = "attacker-planted-cookie-value"

    assert _verify(header_token=injected, stored_token=_STORED) is CsrfDecision.TOKEN_MISMATCH


def test_a_missing_header_is_refused() -> None:
    assert _verify(header_token=None) is CsrfDecision.TOKEN_MISSING


def test_an_empty_header_is_refused() -> None:
    assert _verify(header_token="") is CsrfDecision.TOKEN_MISSING


def test_a_request_with_no_stored_token_is_refused_rather_than_falling_back() -> None:
    assert _verify(stored_token=None) is CsrfDecision.SESSION_TOKEN_MISSING
    assert _verify(stored_token="") is CsrfDecision.SESSION_TOKEN_MISSING


def test_a_non_ascii_header_is_refused_and_does_not_explode() -> None:
    """``compare_digest`` raises ``TypeError`` on non-ASCII ``str``; a 500 is not a refusal."""
    assert verify_csrf_token("токен", stored_token=_STORED) is CsrfDecision.TOKEN_MISSING
    assert verify_csrf_token(_STORED, stored_token="токен") is (CsrfDecision.SESSION_TOKEN_MISSING)


@pytest.mark.parametrize(
    "header_token",
    [_STORED + "x", _STORED[:-1], _STORED.upper(), " " + _STORED],
)
def test_a_near_miss_is_still_a_miss(header_token: str) -> None:
    assert verify_csrf_token(header_token, stored_token=_STORED) is CsrfDecision.TOKEN_MISMATCH


# ---------------------------------------------------------------------------
# The Origin layer
# ---------------------------------------------------------------------------
def test_a_missing_origin_on_a_state_change_is_refused() -> None:
    """Every browser that can reach this panel sends it; absent means "not one of those"."""
    assert _verify(origin=None) is CsrfDecision.ORIGIN_MISSING
    assert _verify(origin="") is CsrfDecision.ORIGIN_MISSING


@pytest.mark.parametrize(
    "origin",
    [
        "https://admin.bayram.example.attacker.test",
        "http://admin.bayram.example",
        "https://admin.bayram.example:8443",
        "https://evil.example",
        "https://admin.bayram.example/",
    ],
)
def test_the_origin_match_is_exact(origin: str) -> None:
    assert (
        verify_origin(origin, accepted_origins=frozenset({_ORIGIN})) is CsrfDecision.ORIGIN_MISMATCH
    )
    assert _verify(origin=origin) is CsrfDecision.ORIGIN_MISMATCH


def test_the_origin_is_checked_before_the_token() -> None:
    """A cross-site caller is told nothing about whether its token guess was close."""
    assert _verify(origin="https://evil.example", header_token=None) is (
        CsrfDecision.ORIGIN_MISMATCH
    )


@pytest.mark.parametrize(
    "origin",
    [_ORIGIN, "https://evil.example", "http://localhost:5174", None, ""],
)
def test_the_wildcard_accepts_every_origin_and_the_absent_one(origin: str | None) -> None:
    """`*` is a hole, not a wider pattern — including for the request that sends nothing.

    ``settings.accepted_origins`` only produces this set in ``dev``.
    """
    assert verify_origin(origin, accepted_origins=frozenset({ANY_ORIGIN})) is CsrfDecision.ALLOWED


def test_the_wildcard_leaves_the_token_layer_standing() -> None:
    """Only the pre-session half of T8 is switched off; a session still needs its token."""
    assert (
        verify_csrf_request(
            method="POST",
            origin="https://evil.example",
            accepted_origins=frozenset({ANY_ORIGIN}),
            header_token="not-the-stored-token",
            stored_token=_STORED,
        )
        is CsrfDecision.TOKEN_MISMATCH
    )


# ---------------------------------------------------------------------------
# Cookie names and token material
# ---------------------------------------------------------------------------
def test_the_cookies_carry_the_host_prefix() -> None:
    """``__Host-`` is what forces Secure, Path=/ and no Domain — see §12.1 T2."""
    assert CSRF_COOKIE_NAME == "__Host-bayram_csrf"
    assert SESSION_COOKIE_NAME == "__Host-bayram_session"
    assert CSRF_HEADER_NAME == "X-CSRF-Token"


def test_a_csrf_token_is_unguessable_and_fits_its_column() -> None:
    tokens = {generate_csrf_token() for _ in range(64)}

    assert len(tokens) == 64
    for token in tokens:
        assert 32 <= len(token) <= _CSRF_COLUMN_CHARS
        assert token.isascii()


def test_only_the_digest_of_a_session_token_is_ever_stored() -> None:
    issued = issue_session_token()

    assert issued.sha256 == sha256_hex(issued.raw)
    assert len(issued.sha256) == SHA256_LENGTH
    assert issued.raw != issued.sha256
    assert issue_session_token().raw != issued.raw


def test_a_session_token_cannot_be_leaked_by_a_stray_repr() -> None:
    issued = issue_session_token()

    assert issued.raw not in repr(issued)
    assert issued.raw not in str(issued)
    assert issued.raw not in f"{issued}"
