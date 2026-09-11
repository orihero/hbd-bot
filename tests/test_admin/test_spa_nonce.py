"""The style nonce, end to end: minted per response, spent in exactly one document.

``SecurityHeadersMiddleware`` has always minted a fresh nonce and put it in the CSP. Until
:mod:`bayram.admin.shell` existed, nothing ever read it — the policy promised
``style-src 'self' 'nonce-<per-response>'`` and the bundle never learned the value, so every
``<style>`` element the SPA injects at runtime was blocked. The observable symptom was one
``style-src-elem`` violation on opening any Radix modal and a scroll lock that silently did
not apply: ``document.body`` kept ``overflow: visible`` and ``padding-right: 0px`` while a
dialog was open.

Three properties are asserted here and each of them is a way the fix could rot:

* **The body carries the same nonce as the header.** A nonce in the document that does not
  match the policy is worse than none: it looks correct in a diff and is blocked in a
  browser.
* **It is fresh per response.** A nonce reused across two responses is not a nonce — it is a
  constant an injected script can read once and reuse forever, which is the entire reason
  ``'unsafe-inline'`` is not simply written into the policy.
* **The two spellings of the placeholder agree.** The token lives in Python and in
  ``admin-ui/index.html``; renaming it on one side alone would substitute nothing, and the
  only symptom would be in a browser under a policy no unit test applies.
"""

from __future__ import annotations

import re
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Final

import httpx
import pytest

from bayram.admin import app as app_module
from bayram.admin.app import create_app
from bayram.admin.container import AdminContainer
from bayram.admin.middleware.security_headers import build_csp
from bayram.admin.shell import CSP_NONCE_META_NAME, CSP_NONCE_PLACEHOLDER, render_shell
from tests.test_admin.conftest import ORIGIN

#: Shaped like the real shell: the meta element carries the literal placeholder.
_SHELL: Final[str] = (
    "<!doctype html><html><head>"
    f'<meta name="{CSP_NONCE_META_NAME}" content="{CSP_NONCE_PLACEHOLDER}" />'
    "<title>Bayram Admin</title></head><body><div id=root></div></body></html>"
)

#: The repository's own shell, the one ``vite build`` copies into the wheel verbatim.
_SOURCE_INDEX: Final[Path] = Path(__file__).resolve().parents[2] / "admin-ui" / "index.html"

_META_NONCE: Final[re.Pattern[str]] = re.compile(
    rf'<meta name="{CSP_NONCE_META_NAME}" content="([^"]*)"'
)
_HEADER_NONCE: Final[re.Pattern[str]] = re.compile(r"style-src 'self' 'nonce-([^']+)'")


@pytest.fixture
def shell_bundle(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A bundle whose shell carries the placeholder, patched onto the module.

    Never written into ``src/bayram/admin/static``: the suite must not depend on whether
    anybody has run ``make ui-build``, and must not leave a bundle behind for a later test.
    """
    static = tmp_path / "static"
    (static / "assets").mkdir(parents=True)
    (static / "index.html").write_text(_SHELL, encoding="utf-8")
    monkeypatch.setattr(app_module, "STATIC_DIR", static)
    monkeypatch.setattr(app_module, "SPA_INDEX", static / "index.html")
    return static


@pytest.fixture
async def served(container: AdminContainer, shell_bundle: Path) -> AsyncIterator[httpx.AsyncClient]:
    """A client over an application built AFTER the shell fixture patched the module."""
    assert shell_bundle.is_dir()
    application = create_app(container=container)
    async with application.router.lifespan_context(application):
        transport = httpx.ASGITransport(app=application)
        async with httpx.AsyncClient(transport=transport, base_url=ORIGIN) as http:
            yield http


def _nonces(response: httpx.Response) -> tuple[str, str]:
    """The nonce in the body and the nonce in the policy, in that order."""
    body = _META_NONCE.search(response.text)
    header = _HEADER_NONCE.search(response.headers["content-security-policy"])
    assert body is not None, "the served shell carries no csp-nonce meta element"
    assert header is not None, "the policy carries no style nonce"
    return body.group(1), header.group(1)


# ---------------------------------------------------------------------------
# The served shell
# ---------------------------------------------------------------------------
async def test_the_served_shell_carries_the_nonce_from_its_own_policy(
    served: httpx.AsyncClient,
) -> None:
    # Act
    response = await served.get("/orders")

    # Assert - a nonce that does not match the header is worse than none: it reads as
    # correct in a diff and is blocked in a browser.
    body_nonce, header_nonce = _nonces(response)
    assert body_nonce == header_nonce
    assert body_nonce != CSP_NONCE_PLACEHOLDER
    assert CSP_NONCE_PLACEHOLDER not in response.text


async def test_the_nonce_is_fresh_on_every_shell_response(served: httpx.AsyncClient) -> None:
    # Act - two cold loads of the console, as two operators (or two tabs) would produce.
    first = await served.get("/orders")
    second = await served.get("/orders")

    # Assert - a nonce reused across responses is a constant, and a constant an attacker can
    # read once is not a control. Both halves must move together.
    first_body, first_header = _nonces(first)
    second_body, second_header = _nonces(second)
    assert first_body != second_body
    assert first_header != second_header
    assert first_body == first_header
    assert second_body == second_header


async def test_the_shell_is_rendered_per_response_and_never_revalidatable(
    served: httpx.AsyncClient,
) -> None:
    # Arrange - a `FileResponse` would advertise `ETag`/`Last-Modified` for a body that is
    # different on every request, which is the one caching shape a per-response nonce cannot
    # survive: a 304 hands the browser a cached document carrying a dead nonce.
    response = await served.get("/orders")

    # Assert
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert "etag" not in response.headers
    assert "last-modified" not in response.headers
    assert response.headers["content-type"].startswith("text/html")


async def test_the_hashed_assets_are_not_made_dynamic_by_any_of_this(
    served: httpx.AsyncClient, shell_bundle: Path
) -> None:
    # Arrange - the nonce reaches exactly one document. `/assets/*` must stay byte-identical
    # and immutable, or the year-long cache the whole mount rests on becomes unsound.
    (shell_bundle / "assets" / "index-abc123.js").write_text("console.log(1)", encoding="utf-8")

    # Act
    first = await served.get("/assets/index-abc123.js")
    second = await served.get("/assets/index-abc123.js")

    # Assert
    assert first.text == second.text == "console.log(1)"
    assert first.headers["cache-control"] == "public, max-age=31536000, immutable"
    assert CSP_NONCE_PLACEHOLDER not in first.text


# ---------------------------------------------------------------------------
# The renderer itself
# ---------------------------------------------------------------------------
def test_render_shell_substitutes_every_occurrence() -> None:
    # Arrange
    html = f"{CSP_NONCE_PLACEHOLDER}|{CSP_NONCE_PLACEHOLDER}"

    # Act
    rendered = render_shell(html, "abc-123_XYZ")

    # Assert
    assert rendered == "abc-123_XYZ|abc-123_XYZ"


def test_render_shell_refuses_a_nonce_that_could_close_the_attribute() -> None:
    # Arrange - `secrets.token_urlsafe` cannot produce this. The guard is for the day
    # somebody changes how the nonce is minted, because the shell is the one document served
    # at the panel's own origin and a quote in an attribute is markup injection into it.
    with pytest.raises(ValueError, match="base64url"):
        render_shell(_SHELL, '"><script>alert(1)</script>')


def test_a_shell_with_no_placeholder_is_served_unchanged_and_logged(
    caplog: pytest.LogCaptureFixture,
) -> None:
    # Arrange - the shape of a bundle built before the placeholder existed. An operator
    # reaching for the console mid-incident is better served by a panel whose modals do not
    # lock the background than by a 500; the log line is what keeps it from being silent.
    stale = "<!doctype html><title>Bayram Admin</title>"

    # Act
    with caplog.at_level("WARNING"):
        rendered = render_shell(stale, "abc123")

    # Assert
    assert rendered == stale
    assert any(
        record.__dict__.get("event") == "admin.spa.nonce_placeholder_missing"
        for record in caplog.records
    )


# ---------------------------------------------------------------------------
# The two languages agree
# ---------------------------------------------------------------------------
def test_the_checked_in_shell_carries_the_placeholder_python_substitutes() -> None:
    # Arrange - the token is spelled in two files in two languages. Renaming it on one side
    # alone substitutes nothing, and the only symptom is in a browser under a policy no unit
    # test applies. `admin-ui/index.html` is the source `vite build` copies verbatim.
    assert _SOURCE_INDEX.is_file(), _SOURCE_INDEX

    # Act
    source = _SOURCE_INDEX.read_text(encoding="utf-8")

    # Assert
    assert f'<meta name="{CSP_NONCE_META_NAME}" content="{CSP_NONCE_PLACEHOLDER}" />' in source


def test_the_policy_and_the_document_use_the_same_nonce_spelling() -> None:
    # Arrange - the header writes `'nonce-<value>'` and the document writes the bare value.
    # A change to either format that the other does not follow is a silently dead control.
    nonce = "Yeycam3SdcOvMG1lzPXqmg"

    # Act
    policy = build_csp(nonce)
    document = render_shell(_SHELL, nonce)

    # Assert
    header_match = _HEADER_NONCE.search(policy)
    body_match = _META_NONCE.search(document)
    assert header_match is not None
    assert body_match is not None
    assert header_match.group(1) == body_match.group(1) == nonce
