"""The Content-Security-Policy's *shape*, asserted token by token rather than searched for.

``tests/test_admin/test_security_headers.py`` already asserts every directive is **present**
and ``tests/test_admin/test_spa_nonce.py`` already asserts the style nonce is fresh and
reaches the document. Both check with ``in``, and that is the hole this file closes:
``"script-src 'self'" in policy`` is equally true of ``script-src 'self' 'unsafe-inline'``.
A policy that has been *widened* — the only direction a CSP regression ever goes — passes
every containment assertion in this suite while handing an injected ``<script>`` the origin
the policy was written to deny it.

Two properties, both of which a browser enforces and neither of which was asserted here:

* **Every directive carries exactly the source list it is meant to carry.** Not "contains";
  equals. A directive that gains ``'unsafe-inline'``, gains a wildcard or a bare scheme, or
  is listed a second time — browsers honour a directive's first occurrence and ignore every
  later one, so a duplicated widened copy reads as permissive and behaves as it did — fails
  here and nowhere else.
* **The document that policy governs asks for nothing the policy would refuse.**
  ``script-src`` is ``'self'`` with no nonce of its own and :mod:`bayram.admin.shell` says it
  must stay that way, so an inline ``<script>`` added to the shell is not a weakened policy:
  it is a *dead script*, run nowhere, failing in a browser only. The same reasoning reaches
  past ``<script>``: an off-origin ``<img>`` (``img-src`` is ``'self' data:``), an off-origin
  ``<iframe>`` (no ``frame-src``, so ``default-src 'self'`` decides), an off-origin
  ``<link rel="modulepreload">`` (``script-src`` again) and **any** ``<base href>``
  (``base-uri 'none'``) are all refused by this policy, and the last of those is the one that
  breaks the panel *silently* — no console script error, just a blank page whose relative
  URLs resolved against the wrong path.

  And the converse, which costs as much: ``script-src`` polices **executable** scripts. A
  ``<script type="application/json">`` is a data block the browser never runs, so flagging it
  is a false failure with no fix available short of deleting a legitimate element.

**WHAT THIS FILE CANNOT SEE.** No browser runs here. These assertions prove the header is the
string it is meant to be and that the shell asks for nothing that string forbids. They do not
prove a real engine parsed and **enforced** the policy, and they are blind to the opposite
regression — a policy too *strict*, silently refusing something the app needs at runtime.
Only a browser collecting ``securitypolicyviolation`` events sees that class, and today it is
an empty set: nothing in ``admin-dashboard`` injects a ``<style>`` element, reads the
``csp-nonce`` meta element, calls ``new Function``, opens a Worker or fetches off-origin. The
day one of those arrives — any of Radix, Headless UI, ``react-remove-scroll``, emotion,
styled-components, a Worker, or a ``connect-src`` that leaves this origin — a browser gate
becomes worth its cost again, and this file is not a substitute for it.
"""

from __future__ import annotations

import re
import secrets
from collections.abc import AsyncIterator
from html.parser import HTMLParser
from pathlib import Path
from typing import Final

import httpx
import pytest

from bayram.admin import app as app_module
from bayram.admin.app import create_app
from bayram.admin.container import AdminContainer
from bayram.admin.middleware.security_headers import NONCE_BYTES, build_csp
from bayram.admin.shell import CSP_NONCE_PLACEHOLDER
from tests.test_admin.conftest import ORIGIN

#: The same four response shapes ``test_security_headers.py`` covers: a handler, a readiness
#: probe, an authenticated API route and a 404 from the router are four different code paths.
_PATHS: Final[tuple[str, ...]] = ("/healthz", "/readyz", "/api/auth/me", "/api/nothing-here")

#: The shell `vite build` copies into the wheel verbatim — the real document, not a stand-in.
_SOURCE_INDEX: Final[Path] = Path(__file__).resolve().parents[2] / "admin-dashboard" / "index.html"

#: Every directive whose source list is a constant. ``style-src`` is the sole exception and is
#: asserted separately, because one of its two sources changes on every response.
_EXPECTED_SOURCES: Final[dict[str, tuple[str, ...]]] = {
    "default-src": ("'self'",),
    "script-src": ("'self'",),
    "img-src": ("'self'", "data:"),
    "media-src": ("'self'",),
    "connect-src": ("'self'",),
    "object-src": ("'none'",),
    "base-uri": ("'none'",),
    "frame-ancestors": ("'none'",),
    "form-action": ("'none'",),
    "worker-src": ("'none'",),
}

#: The one directive that carries the per-response nonce.
_NONCE_BEARING: Final[str] = "style-src"

#: Each of these turns a directive back into ``'unsafe-inline'`` by another name. None of them
#: belongs in any directive of this policy, which is why the check is over all of them at once.
_RE_ENABLES_INLINE_CODE: Final[frozenset[str]] = frozenset(
    {
        "'unsafe-inline'",
        "'unsafe-eval'",
        "'unsafe-hashes'",
        "'wasm-unsafe-eval'",
        "'strict-dynamic'",
    }
)

#: The only bare scheme source this policy is allowed to carry, and where.
_PERMITTED_SCHEME_SOURCE: Final[tuple[str, str]] = ("img-src", "data:")

_NONCE_SOURCE: Final[re.Pattern[str]] = re.compile(r"'nonce-([A-Za-z0-9_-]+)'")

#: The entropy floor, as a LITERAL: the CSP spec asks for at least 128 bits and this is that
#: number in bytes. It is written out rather than read from :data:`NONCE_BYTES` because a floor
#: derived from the value it polices is not a floor.
_MINIMUM_NONCE_BYTES: Final[int] = 16

#: ``secrets.token_urlsafe(16)`` is base64url of 16 bytes with its padding stripped: **22**
#: characters. Spelled as a LITERAL, and this is the whole point of the constant. The previous
#: spelling here was ``-(-NONCE_BYTES * 4 // 3)``, which recomputed the expected length from
#: the very constant it was auditing and so tracked every change to it: shrinking
#: ``NONCE_BYTES`` to 4 — 32 guessable bits, brute-forceable by an injected ``<style>`` in
#: microseconds — left every one of this file's thirty assertions passing, because the
#: "expected" length shrank with it. A length that moves with the thing it measures pins
#: nothing. 22 is what a correct policy carries; if ``NONCE_BYTES`` ever changes on purpose,
#: this line changes with it, deliberately and in the same diff.
_NONCE_LENGTH: Final[int] = 22

#: A URL that names a scheme or a protocol-relative host is off-origin, whatever it resolves
#: to. ``script-src`` and ``style-src`` are both ``'self'`` — and ``style-src``'s nonce
#: authorises an inline element, never a host — so both refuse every one of them.
_OFF_ORIGIN: Final[re.Pattern[str]] = re.compile(r"\A(?:[A-Za-z][A-Za-z0-9+.-]*:|//)")

#: A fetch directive that is absent falls back to ``default-src``, so ``<iframe src=…>`` is
#: governed by ``default-src 'self'`` here even though this policy names no ``frame-src``.
#: ``base-uri`` is NOT a fetch directive and has no fallback: absent, it restricts nothing —
#: which is precisely why the policy spells it ``'none'`` rather than omitting it.
_FALLS_BACK_TO_DEFAULT: Final[frozenset[str]] = frozenset(
    {"script-src", "style-src", "img-src", "media-src", "font-src", "connect-src", "frame-src"}
)

#: ``rel="preload"`` declares the directive that governs the fetch in its ``as`` attribute; a
#: preload is checked against the same directive as the load it is warming up, so an off-origin
#: one fails at preload time and again at use time.
_PRELOAD_AS_DIRECTIVE: Final[dict[str, str]] = {
    "script": "script-src",
    "style": "style-src",
    "image": "img-src",
    "font": "font-src",
    "audio": "media-src",
    "video": "media-src",
    "track": "media-src",
    "fetch": "connect-src",
}

#: The ``type`` values that make a ``<script>`` executable, and therefore something
#: ``script-src`` has an opinion about. Every OTHER value makes it a *data block*: the browser
#: parses the element, hands the text to whatever reads it, and never executes it — so
#: ``<script type="application/json">`` is markup, not code, and flagging it is a false
#: positive that a Vite plugin emitting a config block would hit with no way to be permitted.
#: ``importmap`` and ``speculationrules`` are in the set on purpose: they are not JavaScript,
#: but the browser acts on them and ``script-src`` does police them.
_EXECUTABLE_SCRIPT_TYPES: Final[frozenset[str]] = frozenset(
    {
        "",
        "module",
        "importmap",
        "speculationrules",
        # The JavaScript MIME types, from the HTML Standard's "JavaScript MIME type essence
        # match". Spelled out rather than pattern-matched: `text/json-script` contains
        # "script" and is a data block, and `application/javascript+xml` is not on the list.
        "application/ecmascript",
        "application/javascript",
        "application/x-ecmascript",
        "application/x-javascript",
        "text/ecmascript",
        "text/javascript",
        "text/javascript1.0",
        "text/javascript1.1",
        "text/javascript1.2",
        "text/javascript1.3",
        "text/javascript1.4",
        "text/javascript1.5",
        "text/jscript",
        "text/livescript",
        "text/x-ecmascript",
        "text/x-javascript",
    }
)

#: The one refusal whose consequence is not a console error. Appended to its message because a
#: reader who has only ever seen CSP break a script will not guess what this one does.
_ALSO: Final[dict[str, str]] = {
    "base-uri": (
        " — and this is the refusal with NO console script error behind it: the browser drops "
        "the element, every relative URL in the shell then resolves against the document's own "
        "path, and the panel loads a blank page with no clue why"
    ),
}


def _script_is_executable(attrs: dict[str, str]) -> bool:
    """Does ``script-src`` police this ``<script>``, or is it a data block?"""
    # A MIME type may carry parameters: `text/javascript; charset=utf-8` is still JavaScript.
    essence = attrs.get("type", "").strip().lower().split(";", 1)[0].strip()
    return essence in _EXECUTABLE_SCRIPT_TYPES


def _effective_sources(
    directives: dict[str, tuple[str, ...]], name: str
) -> tuple[str, tuple[str, ...]] | None:
    """``(directive actually applied, its sources)``, or ``None`` when the policy is silent.

    The name comes back with the sources because the two differ for the case that matters
    most here: this policy names no ``frame-src``, so an ``<iframe>`` is judged by
    ``default-src``, and a failure message saying ``frame-src`` would send its reader looking
    for a directive that is not in the header.
    """
    if name in directives:
        return name, directives[name]
    if name in _FALLS_BACK_TO_DEFAULT and "default-src" in directives:
        return "default-src", directives["default-src"]
    return None


def _permits(sources: tuple[str, ...], url: str) -> bool:
    """Would ``sources`` allow a subresource at ``url``?

    Only the two answers a document can settle on its own: a RELATIVE URL is same-origin and
    ``'self'`` covers it, and an ABSOLUTE one is allowed only where the policy lists its scheme
    as a bare scheme source — ``img-src``'s ``data:`` being the single instance here. The rest
    of CSP's matching algorithm (host sources, ports, paths) is out of scope because this
    policy carries none of them, and
    :func:`test_no_directive_carries_a_keyword_that_re_enables_inline_code` is what keeps it
    that way.
    """
    if "'none'" in sources:
        return False
    if url.strip().lower() == "about:blank":
        # Not a fetch at all: an about:blank frame inherits the embedder's own policy.
        return True
    if not _OFF_ORIGIN.match(url):
        return "'self'" in sources
    if url.startswith("//"):
        # Protocol-relative: a different host, reached over this document's scheme.
        return False
    return url.split(":", 1)[0].lower() + ":" in sources


# ---------------------------------------------------------------------------
# Reading a policy as directives and sources, rather than as a string
# ---------------------------------------------------------------------------
def _parse(policy: str) -> dict[str, tuple[str, ...]]:
    """``"a 'self'; b 'none'"`` -> ``{"a": ("'self'",), "b": ("'none'",)}``.

    Directive NAMES become keys and SOURCE LISTS become values, so a comparison can be an
    equality instead of a search. A directive listed twice raises rather than overwriting: a
    browser honours the first occurrence and ignores the rest, so a duplicated widened copy
    is invisible both to a reader and to a containment check.
    """
    parsed: dict[str, tuple[str, ...]] = {}
    for serialised in policy.split(";"):
        tokens = serialised.split()
        if not tokens:
            continue
        name = tokens[0].lower()
        if name in parsed:
            raise AssertionError(
                f"{name!r} is listed twice in the policy; a browser applies the first "
                f"occurrence and ignores the second, so the two never both take effect"
            )
        parsed[name] = tuple(tokens[1:])
    return parsed


def _policy_of(response: httpx.Response) -> dict[str, tuple[str, ...]]:
    return _parse(response.headers["content-security-policy"])


def _nonces_allowed_by(sources: tuple[str, ...]) -> frozenset[str]:
    """The nonce values a directive's source list permits — empty for every directive here
    except ``style-src``."""
    return frozenset(
        match.group(1) for source in sources if (match := _NONCE_SOURCE.fullmatch(source))
    )


# ---------------------------------------------------------------------------
# Reading a document for code the policy would refuse
# ---------------------------------------------------------------------------
class _InlineCode(HTMLParser):
    """Every place a document asks the browser to run code inline, or to fetch something.

    An ``html.parser`` rather than a regex over the markup, because the two documents that
    matter here are written by hand and by Vite: an attribute value containing ``<script``,
    a tag split across lines and a self-closing ``<script/>`` all defeat a regex, and each of
    them is a way a real inline script could hide from a check that claimed to look for one.
    """

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        #: Refusals that need no knowledge of the policy — nothing in it permits these.
        self.findings: list[str] = []
        #: ``(tag, attributes)`` for each ``<style>`` and each EXECUTABLE ``<script>`` with a
        #: non-empty body. A ``<script>`` the browser will not execute is a data block, and
        #: ``script-src`` polices no data block — see :func:`_script_is_executable`.
        self.inline: list[tuple[str, dict[str, str]]] = []
        #: The ``src`` of every executable ``<script>`` that has one.
        self.external_scripts: list[str] = []
        #: The ``href`` of every ``<link rel="stylesheet">``. ``style-src`` is ``'self'`` plus
        #: one nonce, and a nonce does not authorise an off-origin sheet — so an external
        #: stylesheet is refused by exactly the reasoning that refuses an external script, and
        #: leaving it unread was the one hole in this audit that the TypeScript half did check.
        self.external_styles: list[str] = []
        #: ``(description, directive, url)`` for every OTHER element that hands the browser a
        #: URL the policy has an opinion about. Scripts and stylesheets keep their own lists
        #: above because their refusal messages name the reasoning; these share one loop.
        self.urls: list[tuple[str, str, str]] = []
        self._element: str | None = None
        self._attrs: dict[str, str] = {}
        self._body: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        flat = {name.lower(): (value or "") for name, value in attrs}
        for name, value in flat.items():
            # `script-src` carries no `'unsafe-inline'`, so an event handler attribute is
            # markup the browser parses and then declines to run.
            if name.startswith("on"):
                self.findings.append(f"<{tag}> carries the inline event handler {name!r}")
            if value.strip().lower().startswith("javascript:"):
                self.findings.append(f'<{tag}> has {name}="javascript:…", which is inline code')
        # A `<script>` the browser will not execute is a data block, whatever it contains, and
        # `script-src` says nothing about it — including about its `src`, which a data block
        # does not even fetch.
        executable = tag == "script" and _script_is_executable(flat)
        if executable and "src" in flat:
            self.external_scripts.append(flat["src"])
        if tag == "link":
            # `rel` is a space-separated token list, so `rel="preload stylesheet"` is a
            # stylesheet too and a substring test would also match `rel="stylesheetish"`.
            rel = set(flat.get("rel", "").lower().split())
            href = flat.get("href", "")
            if "stylesheet" in rel:
                self.external_styles.append(href)
            elif "modulepreload" in rel:
                # An ES module fetched ahead of use. `script-src` governs it exactly as it
                # governs the `<script type="module" src=…>` that will later import it —
                # which is how an off-origin chunk gets in past a check that only reads
                # `<script>` elements.
                self.urls.append((f"<link rel=modulepreload href={href!r}>", "script-src", href))
            elif "preload" in rel and (
                directive := _PRELOAD_AS_DIRECTIVE.get(flat.get("as", "").strip().lower())
            ):
                self.urls.append(
                    (f"<link rel=preload as={flat.get('as', '')!r} href={href!r}>", directive, href)
                )
        if tag == "img" and "src" in flat:
            # `img-src` is `'self' data:` — the one directive here with a bare scheme, so the
            # check has to permit `data:` and refuse every other absolute URL rather than
            # treating "has a scheme" as the whole answer.
            self.urls.append((f"<img src={flat['src']!r}>", "img-src", flat["src"]))
        if tag in ("iframe", "frame") and "src" in flat:
            # No `frame-src` in this policy, so `default-src 'self'` decides. A checker that
            # only knew the directives the policy NAMES would find nothing to consult here.
            self.urls.append((f"<{tag} src={flat['src']!r}>", "frame-src", flat["src"]))
        if tag == "base" and "href" in flat:
            # `base-uri 'none'` refuses EVERY `<base href>`, same-origin included; there is no
            # off-origin test to apply, and that is why this one cannot ride on `_OFF_ORIGIN`.
            self.urls.append((f"<base href={flat['href']!r}>", "base-uri", flat["href"]))
        if tag == "style" or executable:
            self._element, self._attrs, self._body = tag, flat, []

    def handle_data(self, data: str) -> None:
        if self._element is not None:
            self._body.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag != self._element:
            return
        if "".join(self._body).strip():
            self.inline.append((tag, self._attrs))
        self._element, self._attrs, self._body = None, {}, []


def _refused_by(policy: str, document: str) -> list[str]:
    """Everything in ``document`` that ``policy`` would refuse to run or apply.

    Returns the reasons rather than a bool so a failing assertion names what broke; an empty
    list is the only passing answer.
    """
    directives = _parse(policy)
    parser = _InlineCode()
    parser.feed(document)
    parser.close()

    refused = list(parser.findings)
    for tag, attrs in parser.inline:
        governing = "script-src" if tag == "script" else "style-src"
        sources = directives.get(governing, ())
        if attrs.get("nonce", "") not in _nonces_allowed_by(sources):
            refused.append(
                f"inline <{tag}> carries nonce={attrs.get('nonce', '')!r}, which "
                f"{governing} ({' '.join(sources) or 'absent'}) does not permit"
            )
    for src in parser.external_scripts:
        if _OFF_ORIGIN.match(src):
            refused.append(f"<script src={src!r}> is off-origin and script-src is 'self'")
    for href in parser.external_styles:
        if _OFF_ORIGIN.match(href):
            refused.append(
                f"<link rel=stylesheet href={href!r}> is off-origin and style-src is 'self' "
                f"plus one nonce, which authorises no host at all"
            )
    for description, directive, url in parser.urls:
        applicable = _effective_sources(directives, directive)
        if applicable is None:
            continue
        applied, sources = applicable
        if not _permits(sources, url):
            through = "" if applied == directive else f", which {directive} falls back to"
            refused.append(
                f"{description} is refused by {applied} "
                f"({' '.join(sources) or 'an empty source list'}{through})"
                f"{_ALSO.get(directive, '')}"
            )
    return refused


# ---------------------------------------------------------------------------
# The constant the policy's one secret is drawn from
# ---------------------------------------------------------------------------
def test_the_style_nonce_carries_at_least_the_128_bits_the_spec_asks_for() -> None:
    # A nonce is the only thing standing between an injected `<style>` and `style-src`, and it
    # stops nothing it cannot outrun a guess at. Both sides of this are literals on purpose:
    # the floor is a number this file chose, not a number it read out of the module it audits.
    assert NONCE_BYTES >= _MINIMUM_NONCE_BYTES, (
        f"NONCE_BYTES is {NONCE_BYTES}, which is {NONCE_BYTES * 8} bits of entropy; the CSP "
        f"spec's floor is {_MINIMUM_NONCE_BYTES * 8}, and a nonce under it is guessable"
    )
    # And the length the wire assertions compare against is the length this constant actually
    # produces, so the two cannot drift apart silently in either direction.
    assert len(secrets.token_urlsafe(NONCE_BYTES)) == _NONCE_LENGTH, (
        f"NONCE_BYTES={NONCE_BYTES} yields a {len(secrets.token_urlsafe(NONCE_BYTES))}-character"
        f" nonce, not the {_NONCE_LENGTH} this file pins; if that was deliberate, change"
        f" _NONCE_LENGTH in the same diff and say why"
    )


# ---------------------------------------------------------------------------
# The policy on the wire
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("path", _PATHS)
async def test_the_served_policy_lists_exactly_the_expected_directives(
    client: httpx.AsyncClient, path: str
) -> None:
    # Act
    directives = _policy_of(await client.get(path))

    # Assert - set equality, so a DROPPED directive and an ADDED one both fail. A containment
    # check over an expected list can only ever see the first.
    assert set(directives) == set(_EXPECTED_SOURCES) | {_NONCE_BEARING}


@pytest.mark.parametrize("path", _PATHS)
async def test_every_constant_directive_carries_exactly_its_own_source_list(
    client: httpx.AsyncClient, path: str
) -> None:
    # Act
    directives = _policy_of(await client.get(path))

    # Assert - equality, not containment. This is the assertion that fails on
    # `script-src 'self' 'unsafe-inline'`, which every `in` check in this suite passes.
    for name, expected in _EXPECTED_SOURCES.items():
        assert directives[name] == expected, f"{name} widened or narrowed"


@pytest.mark.parametrize("path", _PATHS)
async def test_the_style_directive_is_self_plus_one_fresh_nonce_and_nothing_else(
    client: httpx.AsyncClient, path: str
) -> None:
    # Act
    sources = _policy_of(await client.get(path))[_NONCE_BEARING]

    # Assert - the source list is pinned as tightly as the constant ones; only the nonce's
    # 22 base64url characters are allowed to differ, and their COUNT is pinned too, because a
    # nonce shortened to something guessable leaves a policy that still reads correct.
    assert sources[0] == "'self'"
    assert len(sources) == 2, f"style-src gained a source: {sources}"
    match = _NONCE_SOURCE.fullmatch(sources[1])
    assert match is not None, f"style-src's second source is not a nonce: {sources[1]!r}"
    assert len(match.group(1)) == _NONCE_LENGTH


@pytest.mark.parametrize("path", _PATHS)
async def test_no_directive_carries_a_keyword_that_re_enables_inline_code(
    client: httpx.AsyncClient, path: str
) -> None:
    # This is redundant with the two equality assertions above, and it is kept anyway: it is
    # the one whose FAILURE MESSAGE names the security regression instead of printing two
    # tuples and leaving the reader to spot which token moved.
    for name, sources in _policy_of(await client.get(path)).items():
        for source in sources:
            assert source not in _RE_ENABLES_INLINE_CODE, (
                f"{name} carries {source}, which re-enables the inline code this policy exists"
                f" to refuse"
            )
            assert "*" not in source, f"{name} carries the wildcard source {source!r}"
            assert not source.endswith(":") or (name, source) == _PERMITTED_SCHEME_SOURCE, (
                f"{name} carries the bare scheme {source!r}, which permits every host on it"
            )


async def test_the_style_nonce_is_unique_on_every_single_request(
    client: httpx.AsyncClient,
) -> None:
    # Act - ten cold loads, which is ten operators opening the console.
    nonces = [
        _nonces_allowed_by(_policy_of(await client.get("/healthz"))[_NONCE_BEARING])
        for _ in range(10)
    ]

    # Assert - a nonce repeated even once is a constant, and a constant an injected script can
    # read once and spend forever. Two requests can collide by chance only at 2**-128.
    assert all(len(seen) == 1 for seen in nonces), nonces
    assert len(set().union(*nonces)) == len(nonces), f"a nonce was reused across requests: {nonces}"


# ---------------------------------------------------------------------------
# The document the policy governs
# ---------------------------------------------------------------------------
@pytest.fixture
def shipped_shell(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """``admin-dashboard/index.html`` itself, mounted as the bundle's shell.

    The real file, not a fixture shaped like it: the property under test is that *this*
    document asks for nothing the policy refuses, and a hand-written stand-in would keep
    passing while the checked-in one regressed. Copied into ``tmp_path`` for the reason
    ``test_spa_nonce.py`` gives for its own fixture — the suite must not depend on whether
    anybody has run ``make ui-build``, and must not leave a bundle behind for a later test.
    """
    assert _SOURCE_INDEX.is_file(), _SOURCE_INDEX
    static = tmp_path / "static"
    (static / "assets").mkdir(parents=True)
    (static / "index.html").write_text(_SOURCE_INDEX.read_text(encoding="utf-8"), encoding="utf-8")
    monkeypatch.setattr(app_module, "STATIC_DIR", static)
    monkeypatch.setattr(app_module, "SPA_INDEX", static / "index.html")
    return static


@pytest.fixture
async def served(
    container: AdminContainer, shipped_shell: Path
) -> AsyncIterator[httpx.AsyncClient]:
    """A client over an application built AFTER the shell fixture patched the module."""
    assert shipped_shell.is_dir()
    application = create_app(container=container)
    async with application.router.lifespan_context(application):
        transport = httpx.ASGITransport(app=application)
        async with httpx.AsyncClient(transport=transport, base_url=ORIGIN) as http:
            yield http


async def test_the_served_shell_contains_nothing_its_own_policy_would_refuse(
    served: httpx.AsyncClient,
) -> None:
    # Act - the shell exactly as an operator's browser receives it: the checked-in document,
    # rendered through `render_shell`, judged against the policy that same response carries.
    response = await served.get("/orders")

    # Assert
    assert response.status_code == 200
    assert CSP_NONCE_PLACEHOLDER not in response.text
    assert _refused_by(response.headers["content-security-policy"], response.text) == []


def test_an_inline_script_is_refused_even_when_it_carries_the_response_nonce() -> None:
    # Arrange - the mistake this is here to catch. `script-src` is `'self'` with no nonce of
    # its own and `bayram.admin.shell` says it must stay that way, so nonce-ing an inline
    # script buys nothing: the browser refuses it and the diff reads as correct.
    nonce = "A" * _NONCE_LENGTH

    # Act
    refused = _refused_by(build_csp(nonce), f'<script nonce="{nonce}">window.x = 1</script>')

    # Assert
    assert len(refused) == 1
    assert "inline <script>" in refused[0]


def test_a_style_element_carrying_the_response_nonce_is_permitted() -> None:
    # Arrange - the other half, without which the check above could pass by refusing
    # everything. The nonce in `style-src` is what makes a runtime stylesheet possible.
    nonce = "A" * _NONCE_LENGTH

    # Act / Assert
    assert _refused_by(build_csp(nonce), f'<style nonce="{nonce}">body{{margin:0}}</style>') == []


@pytest.mark.parametrize(
    ("markup", "named"),
    [
        ("<script>alert(1)</script>", "inline <script>"),
        ('<script nonce="wrong">alert(1)</script>', "inline <script>"),
        ("<style>body{margin:0}</style>", "inline <style>"),
        ('<style nonce="wrong">body{margin:0}</style>', "inline <style>"),
        ('<body onload="boot()"></body>', "inline event handler"),
        ('<a href="javascript:boot()">go</a>', 'href="javascript:'),
        ('<script src="https://cdn.evil.example/x.js"></script>', "<script src="),
        ('<script src="//cdn.evil.example/x.js"></script>', "<script src="),
        (
            '<link rel="stylesheet" href="https://fonts.googleapis.com/x.css" />',
            "<link rel=stylesheet",
        ),
        ('<link rel="stylesheet" href="//fonts.googleapis.com/x.css">', "<link rel=stylesheet"),
        (
            '<link rel="preload stylesheet" href="https://cdn.evil.example/x.css" />',
            "<link rel=stylesheet",
        ),
        # `img-src` is the one directive carrying a bare scheme, and `'self' data:` permits no
        # host: a tracking pixel or a hotlinked logo is refused exactly as a script would be.
        ('<img src="https://cdn.evil.example/pixel.png">', "<img src="),
        ('<img src="//cdn.evil.example/pixel.png">', "<img src="),
        # No `frame-src`, so `default-src 'self'` decides — the fallback a checker that read
        # only the directives the policy names would never consult.
        ('<iframe src="https://evil.example/embed"></iframe>', "<iframe src="),
        ('<iframe src="data:text/html,<b>x"></iframe>', "<iframe src="),
        # `base-uri 'none'` refuses EVERY base element, and this is the one refusal with no
        # console script error behind it: the panel just loads blank.
        ('<base href="https://evil.example/">', "<base href="),
        ('<base href="/panel/">', "<base href="),
        # The module graph's other entrance. `script-src` governs a modulepreload as much as
        # the `<script type="module">` that will import it.
        (
            '<link rel="modulepreload" href="https://cdn.evil.example/chunk.js">',
            "<link rel=modulepreload",
        ),
        (
            '<link rel="preload" as="script" href="https://cdn.evil.example/chunk.js">',
            "<link rel=preload",
        ),
        (
            '<link rel="preload" as="font" href="https://fonts.gstatic.com/x.woff2">',
            "<link rel=preload",
        ),
        # And the whole point of teaching this file about `type`: the values that still ARE
        # executed must still be refused, or the false-positive fix becomes the hole.
        ('<script type="text/javascript">alert(1)</script>', "inline <script>"),
        ('<script type="TEXT/JavaScript; charset=utf-8">alert(1)</script>', "inline <script>"),
        ('<script type="module">import "./x.js"</script>', "inline <script>"),
        ('<script type="">alert(1)</script>', "inline <script>"),
        ('<script type="  ">alert(1)</script>', "inline <script>"),
        ('<script type="importmap">{"imports":{}}</script>', "inline <script>"),
        ('<script type="speculationrules">{"prerender":[]}</script>', "inline <script>"),
        (
            '<script type="module" src="https://cdn.evil.example/x.js"></script>',
            "<script src=",
        ),
    ],
)
def test_the_audit_names_each_thing_the_policy_would_refuse(markup: str, named: str) -> None:
    # A checker that returns `[]` for every input passes the served-shell test above against
    # any document at all. This repository has shipped exactly that once — an i18n check that
    # matched the substring `t(` and so passed on any file containing `useEffect`. These
    # cases are what keep the one assertion that matters from being vacuous.
    refused = _refused_by(build_csp("A" * _NONCE_LENGTH), markup)

    assert any(named in line for line in refused), refused


def test_a_same_origin_stylesheet_link_is_permitted() -> None:
    # The other half of the check above, without which "refuse every <link>" would pass it.
    # `vite build` emits exactly this element, so a checker that refused it would fail the
    # served-shell test the moment the built shell were the one under audit.
    document = '<link rel="stylesheet" crossorigin href="/assets/index-CjYrft9g.css">'

    # Act / Assert
    assert _refused_by(build_csp("A" * _NONCE_LENGTH), document) == []


@pytest.mark.parametrize(
    "document",
    [
        # `img-src` names `data:` and this is the only element that may use it.
        '<img src="data:image/svg+xml;base64,PHN2Zy8+">',
        '<img src="/assets/logo-BQ2f9x.png">',
        '<img src="assets/logo-BQ2f9x.png">',
        # An iframe with no src, and the one absolute URL a frame may carry: about:blank is
        # not a fetch — the frame inherits the embedder's policy.
        "<iframe></iframe>",
        '<iframe src="about:blank"></iframe>',
        # `<base target>` without an href sets no base URL, so `base-uri` never sees it.
        '<base target="_blank">',
        # The preloads a Vite build actually emits.
        '<link rel="modulepreload" crossorigin href="/assets/vendor-D1x8sq.js">',
        '<link rel="preload" as="font" type="font/woff2" crossorigin href="/assets/i-a91.woff2">',
    ],
)
def test_the_same_origin_shapes_a_real_build_emits_are_permitted(document: str) -> None:
    # The other half of every refusal above. A checker that refused these would fail the
    # served-shell test the moment `vite build` added one — which is how a gate gets disabled
    # rather than fixed.
    assert _refused_by(build_csp("A" * _NONCE_LENGTH), document) == []


@pytest.mark.parametrize(
    "document",
    [
        # THE FALSE POSITIVE THIS CLOSES. A typed data block is not code: the browser parses
        # it, hands the text to whatever reads it, and never executes it — so `script-src` has
        # no opinion, and a Vite plugin emitting a JSON config block would otherwise fail this
        # gate with no way to be permitted and no security reason for the failure.
        '<script type="application/json">{"api":"/api"}</script>',
        '<script type="application/ld+json">{"@context":"https://schema.org"}</script>',
        '<script type="text/template"><div>{{ x }}</div></script>',
        # Including its `src`: a data block does not fetch one.
        '<script type="application/json" src="https://cdn.example/config.json"></script>',
    ],
)
def test_a_script_the_browser_will_not_execute_is_not_policed_by_script_src(
    document: str,
) -> None:
    assert _refused_by(build_csp("A" * _NONCE_LENGTH), document) == []


def test_the_audit_is_not_fooled_by_markup_that_only_looks_like_a_script() -> None:
    # Arrange - the false positive a regex over the markup would produce, and the reason this
    # is an html.parser: an attribute value is not an element.
    document = '<meta name="note" content="&lt;script&gt;alert(1)&lt;/script&gt;" />'

    # Act / Assert
    assert _refused_by(build_csp("A" * _NONCE_LENGTH), document) == []


def test_a_policy_that_lists_a_directive_twice_is_read_as_the_defect_it_is() -> None:
    # Arrange - appending a widened copy is the cheapest way to weaken a policy while every
    # containment assertion in this suite keeps passing. A browser applies the first and
    # ignores the second, so the two never both take effect and `_parse` refuses to average
    # them.
    with pytest.raises(AssertionError, match="listed twice"):
        _parse("script-src 'self'; img-src 'self'; script-src 'self' 'unsafe-inline'")
