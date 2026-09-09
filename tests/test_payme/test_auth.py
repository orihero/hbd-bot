"""Basic-auth verification, and the specific weakening this file exists to keep out.

The test that matters most is
:func:`test_the_right_key_under_the_wrong_login_is_refused`. PayTechUz's Python package — the
one an Uzbek merchant is most likely to install first — decodes the credential, splits it on
``':'`` and compares only the trailing half, so it accepts ANY username. Every test in that
package passes. Every payment works. The login has simply stopped being part of the
credential, and a key learned from a log, a backup or a former employee is by itself enough to
call ``PerformTransaction`` against a live cashbox.

That is a regression test rather than a behaviour test: nothing in this repository has ever
had the bug, and the point is to make writing it into a review comment instead of an incident.
It is written so that the obvious "simplification" — split, compare the key — turns it red.

**The credential in this file is a placeholder and that is not a limitation.** The merchant key
is only ever compared against itself, so a made-up 36-character string exercises the identical
code path a real one would. This suite needs no credential, no marker, no network and no
fixture, which is precisely why the whole authorisation half of the gateway could be finished
and certified before Payme handed anything over.

The last two tests are about what may be WRITTEN DOWN after a failure. ``presented_login``
exists so a certification call's first authentication failure names the login Payme actually
sent — a fact that is not reliably documented and that a support ticket takes days to
establish — while making it structurally impossible for key material to ride along.
"""

from __future__ import annotations

import ast
import base64
import logging
from pathlib import Path
from typing import Final

import pytest

import hbd.payme.auth
from hbd.payme.auth import MAX_LOGGED_LOGIN, presented_login, verify_basic
from hbd.payme.protocol import DEFAULT_AUTH_LOGIN

#: A placeholder cashbox key of the documented length. Not a real credential and it does not
#: need to be — see the module docstring.
_KEY: Final[str] = "aBcDeFgH1234567890ijkLmNoPqRsTuVwXyZ"

#: The login both official merchant templates hard-code.
_LOGIN: Final[str] = DEFAULT_AUTH_LOGIN


def _header(credential: str) -> str:
    """``credential`` as a well-formed ``Authorization: Basic`` header value."""
    return f"Basic {base64.b64encode(credential.encode('utf-8')).decode('ascii')}"


def test_the_configured_pair_is_accepted() -> None:
    # Arrange
    header = _header(f"{_LOGIN}:{_KEY}")

    # Act / Assert
    assert verify_basic(header, login=_LOGIN, key=_KEY) is True


def test_the_right_key_under_the_wrong_login_is_refused() -> None:
    # Arrange — the PayTechUz weakening, pinned. An implementation that splits on ':' and
    # compares only the trailing half returns True here, and every one of its own tests still
    # passes. See the module docstring.
    header = _header(f"admin:{_KEY}")

    # Act / Assert
    assert verify_basic(header, login=_LOGIN, key=_KEY) is False


def test_the_right_login_with_the_wrong_key_is_refused() -> None:
    # Arrange — the companion direction, so a comparison that had quietly become a comparison
    # of the LOGIN half only would fail too. One of the two tests alone leaves half the
    # credential unchecked.
    header = _header(f"{_LOGIN}:not-the-key")

    # Act / Assert
    assert verify_basic(header, login=_LOGIN, key=_KEY) is False


def test_a_key_containing_a_colon_is_compared_whole_and_never_on_a_prefix() -> None:
    # Arrange — a colon inside the key is legal, and a ``split(':')`` implementation would
    # compare only up to the first one. Sending the truncated prefix must NOT authenticate.
    colonised = "part-one:part-two:part-three"
    good = _header(f"{_LOGIN}:{colonised}")
    truncated = _header(f"{_LOGIN}:part-one")

    # Act / Assert
    assert verify_basic(good, login=_LOGIN, key=colonised) is True
    assert verify_basic(truncated, login=_LOGIN, key=colonised) is False


@pytest.mark.parametrize(
    ("header", "why"),
    [
        (None, "no header at all — the commonest inbound request on a public endpoint"),
        ("", "an empty header value"),
        ("Basic", "the scheme with no credential and no space"),
        ("Basic ", "the scheme with an empty credential"),
        ("Bearer " + base64.b64encode(b"Paycom:x").decode("ascii"), "a non-Basic scheme"),
        ("Basic !!!not-base64!!!", "a credential that is not base64 at all"),
        ("Basic UGF5Y29tOn", "base64 with broken padding"),
        ("Basic " + base64.b64encode(bytes([0xFF, 0xFE, 0xFD])).decode("ascii"), "not UTF-8"),
        (base64.b64encode(b"Paycom:x").decode("ascii"), "a bare blob with no scheme"),
    ],
)
def test_every_malformed_header_is_refused_without_raising(*, header: str | None, why: str) -> None:
    # Arrange — an internet-facing endpoint is scanned continuously, so every one of these is a
    # routine event rather than an incident. All of them answer -32504 at HTTP 200; none of
    # them may raise, because an exception here becomes a 500 that Payme reads as -32300 and
    # retries.

    # Act
    verdict = verify_basic(header, login=_LOGIN, key=_KEY)

    # Assert
    assert verdict is False, why
    assert presented_login(header) is None, why


def test_a_scheme_in_any_casing_is_accepted_because_the_http_grammar_says_so() -> None:
    # Arrange — the scheme token is case-insensitive per RFC 7235 and clients disagree about
    # it. Refusing "basic" would be a certification failure caused by our own pedantry.
    credential = base64.b64encode(f"{_LOGIN}:{_KEY}".encode()).decode("ascii")

    # Act / Assert
    for scheme in ("Basic", "basic", "BASIC", "BaSiC"):
        assert verify_basic(f"{scheme} {credential}", login=_LOGIN, key=_KEY) is True


def test_presented_login_returns_only_the_half_before_the_first_colon() -> None:
    # Arrange — the value that goes into the failure log line, so that a certification call's
    # first 401 names the login Payme actually sent.
    header = _header("someone-else:secret-key-material:with-colons")

    # Act
    login = presented_login(header)

    # Assert — the login, and nothing that follows it, under any nesting of separators.
    assert login == "someone-else"
    assert "secret-key-material" not in (login or "")


def test_a_credential_with_no_separator_presents_no_login_at_all() -> None:
    # Arrange — the dangerous case, and the reason this returns None rather than the whole
    # string: a client misconfigured with the KEY as its entire credential would, under the
    # obvious implementation, hand us our own key to write into a log line.
    header = _header(_KEY)

    # Act
    login = presented_login(header)

    # Assert
    assert login is None


def test_an_absurdly_long_login_is_truncated_before_it_reaches_a_log_line() -> None:
    # Arrange — the header is attacker-controlled and its decoded form becomes a JSON log
    # record somebody pays per gigabyte to ship.
    header = _header(f"{'a' * 5_000}:{_KEY}")

    # Act
    login = presented_login(header)

    # Assert — still identifies a misconfigured client, which is all the line exists for.
    assert login is not None
    assert len(login) == MAX_LOGGED_LOGIN


def test_no_emitted_log_record_can_contain_the_key(caplog: pytest.LogCaptureFixture) -> None:
    # Arrange — every path, right and wrong, with the root logger wide open.
    caplog.set_level(logging.DEBUG)
    headers = [
        _header(f"{_LOGIN}:{_KEY}"),
        _header(f"admin:{_KEY}"),
        _header(_KEY),
        _header(f"{_LOGIN}:wrong"),
        "Basic !!!",
        None,
    ]

    # Act
    for header in headers:
        verify_basic(header, login=_LOGIN, key=_KEY)
        presented_login(header)

    # Assert — nothing was emitted at all, and in particular nothing carrying the key. The log
    # line belongs to the dispatcher, which knows the peer address and the correlation id;
    # emitting it here would either duplicate that line or split it in half.
    assert caplog.records == []
    assert _KEY not in caplog.text


def test_the_auth_module_contains_no_logging_call_at_all() -> None:
    # Arrange — the structural companion to the caplog assertion above, and the stronger of the
    # two: a caplog test passes for as long as nobody has added a log call YET, and goes on
    # passing the moment somebody adds one that happens not to fire on the inputs listed above.
    # Parsing the source catches the call itself, including one added inside a branch no test
    # reaches — which is exactly where a debug line printing the expected credential would go.
    source = Path(hbd.payme.auth.__file__).read_text(encoding="utf-8")
    tree = ast.parse(source)

    # Act
    imported = {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    } | {node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom) and node.module}

    # Assert — no logging machinery is reachable from this module, so there is nothing here for
    # a secret to be written to. ``hbd.logging`` is barred by the same rule as ``logging``.
    assert "logging" not in imported
    assert "hbd.logging" not in imported
