"""Opaque tokens: generated once, handed out once, stored only as a digest.

Why opaque and not a JWT: revocation is a stated product requirement (block, purge, config
commit, deactivate), and a JWT cannot be revoked without rebuilding the server-side store
that a JWT was chosen to avoid (ADMIN_PANEL_PLAN §12.1 T2).

Why only the digest is stored: ``admin_sessions`` is readable by anything holding the
application's database role, and a dump of that table must not be a set of usable session
cookies. The raw token exists in exactly two places — the ``Set-Cookie`` header and the
operator's browser — and :class:`SessionToken` is deliberately unprintable so a stray
``repr`` in a log line, a traceback frame or an audit context cannot leak it. SHA-256 with
no salt and no stretching is correct here and only here: the input is 256 bits of CSPRNG
output, so there is nothing to brute-force and a slow KDF would only add latency to every
authenticated request.
"""

from __future__ import annotations

import hashlib
import secrets
from dataclasses import dataclass
from typing import Final

__all__ = [
    "SESSION_TOKEN_BYTES",
    "CSRF_TOKEN_BYTES",
    "SessionToken",
    "issue_session_token",
    "generate_csrf_token",
    "sha256_hex",
]

#: 256 bits, per §12.1 T2. ``token_urlsafe(32)`` renders as 43 base64url characters.
SESSION_TOKEN_BYTES: Final[int] = 32
#: The CSRF token is not a bearer credential, but it is compared against a stored value,
#: so it is generated the same way. 43 characters fits ``admin_sessions.csrf_token``'s
#: ``String(64)`` with room to spare.
CSRF_TOKEN_BYTES: Final[int] = 32

_REDACTED_REPR: Final[str] = "SessionToken(raw=***, sha256=...)"


@dataclass(frozen=True, slots=True)
class SessionToken:
    """A freshly minted session token and the digest that is persisted for it.

    ``raw`` goes into the ``Set-Cookie`` header and is never written anywhere else;
    ``sha256`` is what ``admin_sessions.token_sha256`` holds. The two are returned together
    exactly once so no caller has to remember to hash before storing.
    """

    raw: str
    sha256: str

    def __repr__(self) -> str:
        """Never render the raw token — a traceback or a logged model must not carry it."""
        return _REDACTED_REPR

    def __str__(self) -> str:
        return _REDACTED_REPR


def sha256_hex(value: str) -> str:
    """Lowercase hex SHA-256 of ``value``, UTF-8 encoded. 64 characters, always."""
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def issue_session_token() -> SessionToken:
    """Mint a session token. The raw form is returned to the caller once and only once."""
    raw = secrets.token_urlsafe(SESSION_TOKEN_BYTES)
    return SessionToken(raw=raw, sha256=sha256_hex(raw))


def generate_csrf_token() -> str:
    """Mint the per-session CSRF token stored in ``admin_sessions.csrf_token``."""
    return secrets.token_urlsafe(CSRF_TOKEN_BYTES)
