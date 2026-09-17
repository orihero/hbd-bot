"""Basic-auth verification for the Merchant API, and the one thing it is safe to log.

Two functions, thirty lines of logic, and one of the highest-consequence files in the
repository: it is the only thing standing between the public internet and a method that
writes a credit grant. Everything below is written against a specific, widely-installed
mistake.

**The WHOLE decoded ``login:key`` pair is compared, as one string, under
``hmac.compare_digest``.** PayTechUz's Python package — the one most Uzbek merchants install
first — splits the decoded credential on ``':'`` and compares only the trailing half, which
means it accepts ANY username. That is not a stylistic difference: it turns the login from a
second factor into decoration, and it means a merchant who learns the key from a log, a
backup or a former employee needs nothing else. Comparing the joined pair costs one string
concatenation and closes it. ``tests/test_payme/test_auth.py`` pins the weakening as a
regression: the right key under the login ``admin`` must FAIL.

**Constant time, and never ``==``.** ``hmac.compare_digest`` is used for the ordinary reason,
and both sides are encoded to UTF-8 bytes before the comparison rather than passed as
``str`` — ``compare_digest`` raises ``TypeError`` on a non-ASCII ``str``, and the credential
half of the header is attacker-controlled, so a byte comparison is the difference between a
failed authentication and a 500 that Payme would read as ``-32400`` and retry.

**Nothing here raises, and nothing here logs.** A malformed header, a missing header, a
non-Basic scheme, invalid base64 and bytes that are not UTF-8 all return ``False`` (or
``None``), because every one of them is an ordinary event on an internet-facing endpoint and
none of them is distinguishable to an attacker anyway. The log line belongs to the dispatcher,
which knows the peer address, the method and the correlation id; putting it here would either
duplicate that line or split it in half. What this module owes the dispatcher is
:func:`presented_login` — a value that is safe to write down.

**Why a failure logs the login at all.** The username Payme actually sends is not reliably
documented: both official templates hard-code ``Paycom``, the current docs hedge, and the
first thing that happens on a certification call is an authentication failure with a login
nobody at either company can name. Recording the RECEIVED login turns that into a fact
discoverable from our own journal in one grep, instead of a support ticket. The key is never
recorded, in any form, on any path — see :func:`presented_login` for what makes that
structural rather than careful.
"""

from __future__ import annotations

import base64
import hmac
from typing import Final

__all__ = ["verify_basic", "presented_login", "BASIC_SCHEME", "MAX_LOGGED_LOGIN"]

#: The only authorization scheme this endpoint accepts, compared case-insensitively because
#: the HTTP grammar says the scheme token is case-insensitive and clients disagree about it.
BASIC_SCHEME: Final[str] = "basic"

#: Longest login that :func:`presented_login` will hand back. The header is attacker-controlled
#: and its decoded form goes into a log line, so an unbounded value is an unbounded JSON record
#: in a shipper somebody pays per gigabyte for. 64 characters is far beyond any real login and
#: far below anything worth writing down; a truncated value still identifies a misconfigured
#: client, which is the only thing the line exists for.
MAX_LOGGED_LOGIN: Final[int] = 64

#: The separator inside a Basic credential. Split ONCE on it and never more — a key containing
#: a colon is legal, and a naive ``split(':')`` would silently truncate it and then compare a
#: prefix, which is a weakened comparison that passes every test written with a hex key.
_CREDENTIAL_SEPARATOR: Final[str] = ":"


def _decoded_credential(header: str | None) -> str | None:
    """The decoded ``login:key`` string, or ``None`` if the header is not usable at all.

    Every failure mode collapses to ``None`` deliberately. An internet-facing endpoint is
    scanned continuously, so "no header", "Bearer", "not base64" and "not UTF-8" are all
    routine, they are all answered with the same ``-32504``, and distinguishing them in the
    return type would only tempt a caller into distinguishing them in a reply.
    """
    if not header:
        return None
    scheme, separator, blob = header.partition(" ")
    if not separator or scheme.strip().lower() != BASIC_SCHEME:
        return None
    candidate = blob.strip()
    if not candidate:
        return None
    try:
        # ``validate=True`` so that a blob with stray characters is a refusal rather than
        # silently decoding to whatever survives the filter — the default discards anything
        # outside the alphabet, which would let a mangled header authenticate.
        raw = base64.b64decode(candidate, validate=True)
    except ValueError:
        # ``binascii.Error`` (bad padding, bad alphabet) and the non-ASCII ``str`` case both
        # subclass ``ValueError``. Nothing else can escape ``b64decode``.
        return None
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        return None


def verify_basic(header: str | None, *, login: str, key: str) -> bool:
    """Is this ``Authorization`` header the configured merchant credential? Never raises.

    ``login`` and ``key`` are joined into the exact string the header must decode to, and the
    comparison is made once, over the whole thing, in constant time. See the module docstring
    for why the join is the security property rather than an implementation detail.

    A missing or malformed header returns ``False`` without a comparison. That is a timing
    difference, and it is not a meaningful one: it distinguishes "sent something shaped like a
    credential" from "sent nothing", which an attacker already knows, and it leaks nothing
    about the key's contents. The comparison that could leak — the one against a well-formed
    credential of the right shape — is the one that is constant-time.
    """
    decoded = _decoded_credential(header)
    if decoded is None:
        return False
    expected = f"{login}{_CREDENTIAL_SEPARATOR}{key}"
    return hmac.compare_digest(decoded.encode("utf-8"), expected.encode("utf-8"))


def presented_login(header: str | None) -> str | None:
    """The LOGIN half of a presented credential, and nothing else. Safe to write to a log.

    **Structurally incapable of returning key material**, which is the entire reason it exists
    as a function rather than as two lines at the call site:

    * it splits ONCE, on the first colon, and returns the part BEFORE it — so no amount of
      colons, padding or nesting in the key can push key bytes into the returned value;
    * a credential with NO colon returns ``None`` rather than the whole string. That case is
      not hypothetical and it is the dangerous one: a client misconfigured with the key as its
      entire credential would, under the obvious implementation, hand us our own key to log.
      "No separator" means "no login was presented", which is both true and safe;
    * the result is truncated to :data:`MAX_LOGGED_LOGIN`, because the value is
      attacker-controlled and is about to become a line in a log shipper.

    Returns ``None`` for every unusable header, so a caller writing a structured log line gets
    an explicit "nothing was presented" rather than an empty string that reads as a login.
    """
    decoded = _decoded_credential(header)
    if decoded is None or _CREDENTIAL_SEPARATOR not in decoded:
        return None
    return decoded.split(_CREDENTIAL_SEPARATOR, 1)[0][:MAX_LOGGED_LOGIN]
