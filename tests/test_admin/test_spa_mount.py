"""The SPA mount — §11.1's "same origin, always", asserted at the ASGI layer.

The panel and its API share one origin. That is a security decision before it is a
convenience one: it removes CORS entirely (there is no ``allow_credentials`` plus origin-list
combination left to get wrong), it lets the CSP be ``default-src 'self'``, and it lets a
future ``<audio src>`` carry the session cookie as a same-site subresource with no token in
the URL. Serving the bundle from the API process is what buys all three, so the mount is part
of the security surface and not merely a deployment nicety.

Four properties are asserted here, and each of them is a way the mount could go wrong
silently:

* **It does not widen the route table.** ``StaticFiles`` is a ``Mount`` and the fallback is a
  plain Starlette ``Route``; neither is an ``APIRoute``, so §12.1 T8's frozen table is
  untouched. A ``@app.get("/{path:path}")`` would have been an ``APIRoute`` and would have
  failed ``test_routes_enumeration``. This file asserts the *reason* that test still passes.
* **It never answers for ``/api``.** A catch-all that returned the HTML shell for a typo'd
  endpoint would hand a JSON client a 200 full of markup where a ``NOT_FOUND`` envelope
  belongs.
* **It does not swallow a wrong method.** ``POST /healthz`` must stay a 405.
* **The bundle is the only cacheable thing in the process.** Everything else is ``no-store``,
  because a disk cache is a copy of personal data that outlives every retention clock and
  that ``hbd.db.purge`` cannot reach (§12.1 T10).
"""

from __future__ import annotations

import re
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Final

import httpx
import pytest
from fastapi.routing import APIRoute

from hbd.admin import app as app_module
from hbd.admin.app import create_app
from hbd.admin.container import AdminContainer
from hbd.admin.middleware.security_headers import IMMUTABLE_CACHE_CONTROL
from hbd.admin.shell import CSP_NONCE_META_NAME, CSP_NONCE_PLACEHOLDER
from hbd.errors import ErrorCode
from tests.test_admin.conftest import ORIGIN, api_routes

#: Shaped like the real shell: the ``csp-nonce`` meta element carries the placeholder the
#: server substitutes per response (``hbd.admin.shell``). Without it every assertion below
#: would still pass while the served document carried a dead nonce, so it is here rather
#: than only in ``test_spa_nonce.py``.
_SHELL: Final[str] = (
    "<!doctype html><title>hbd admin</title>"
    f'<meta name="{CSP_NONCE_META_NAME}" content="{CSP_NONCE_PLACEHOLDER}" />'
    "<div id=root></div>"
)
_CHUNK: Final[str] = "console.log('the bundle')"


@pytest.fixture
def built_bundle(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A directory shaped like the one ``vite build`` writes.

    Patched onto the module rather than written into ``src/hbd/admin/static`` so the suite
    never depends on whether anybody has run ``make ui-build`` — and never leaves a bundle
    behind that a later test could accidentally serve.
    """
    static = tmp_path / "static"
    (static / "assets").mkdir(parents=True)
    (static / "index.html").write_text(_SHELL, encoding="utf-8")
    (static / "assets" / "index-abc123.js").write_text(_CHUNK, encoding="utf-8")
    monkeypatch.setattr(app_module, "STATIC_DIR", static)
    monkeypatch.setattr(app_module, "SPA_INDEX", static / "index.html")
    return static


@pytest.fixture
def no_bundle(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A checkout where nobody has run ``make ui-build``.

    Patched to a directory that does not exist rather than simply not patching, because a
    developer machine that HAS built the bundle would otherwise make the unbuilt case pass
    vacuously — and that case is the one every other test in this package runs under.
    """
    missing = tmp_path / "never-built"
    monkeypatch.setattr(app_module, "STATIC_DIR", missing)
    monkeypatch.setattr(app_module, "SPA_INDEX", missing / "index.html")
    return missing


def _served_nonce(response: httpx.Response) -> str:
    """The style nonce out of this response's own policy. See ``test_spa_nonce.py``."""
    match = re.search(
        r"style-src 'self' 'nonce-([^']+)'", response.headers["content-security-policy"]
    )
    assert match is not None
    return match.group(1)


async def _client(container: AdminContainer) -> AsyncIterator[httpx.AsyncClient]:
    """Build the application AFTER the bundle fixtures have patched the module.

    Order is load-bearing: ``StaticFiles(directory=...)`` reads ``STATIC_DIR`` once, at
    ``create_app`` time, so a client fixture that did not depend on the bundle fixture would
    mount the real ``src/hbd/admin/static`` and serve whatever happens to be on disk.
    """
    application = create_app(container=container)
    async with application.router.lifespan_context(application):
        transport = httpx.ASGITransport(app=application)
        async with httpx.AsyncClient(transport=transport, base_url=ORIGIN) as http:
            yield http


@pytest.fixture
async def served(container: AdminContainer, built_bundle: Path) -> AsyncIterator[httpx.AsyncClient]:
    """A client over an application whose SPA mount points at the fixture bundle."""
    assert built_bundle.is_dir()
    async for http in _client(container):
        yield http


@pytest.fixture
async def served_unbuilt(
    container: AdminContainer, no_bundle: Path
) -> AsyncIterator[httpx.AsyncClient]:
    """A client over an application with no bundle on disk at all."""
    assert not no_bundle.exists()
    async for http in _client(container):
        yield http


# ---------------------------------------------------------------------------
# The route table is untouched
# ---------------------------------------------------------------------------
async def test_the_spa_mount_adds_no_api_route(container: AdminContainer) -> None:
    # Arrange — the enumeration test asserts served == MOUNTED_ROUTES in BOTH directions, so
    # anything the mount contributed to that set would fail it. Assert the mechanism here so
    # a future refactor to `@app.get` fails with an explanation rather than a set diff.
    #
    # The lifespan is entered because that is what installs the mount: `create_app` leaves it
    # off so a route added to the returned application cannot be shadowed by a catch-all
    # registered before it.
    application = create_app(container=container)
    async with application.router.lifespan_context(application):
        templates = {route.path for route in api_routes(application)}
        names = {getattr(route, "name", None) for route in application.routes}
        route_objects = list(application.routes)

    # Assert — the two routes exist, and neither is an APIRoute.
    assert {"spa-assets", "spa-index"} <= names
    assert "/{spa_path:path}" not in templates
    assert not any(
        isinstance(route, APIRoute) and route.name in {"spa-assets", "spa-index"}
        for route in route_objects
    )


async def test_a_route_added_after_the_factory_is_not_shadowed_by_the_catch_all(
    container: AdminContainer, built_bundle: Path
) -> None:
    # Arrange — the reason the mount is deferred to the lifespan. A catch-all installed by
    # `create_app` would swallow this route with no error anywhere, and several tests in this
    # package (and any future `include_router` after the factory) depend on it not doing so.
    assert built_bundle.is_dir()
    application = create_app(container=container)

    @application.get("/api/added-later", include_in_schema=False)
    async def _added_later() -> dict[str, bool]:  # pragma: no cover - exercised below
        return {"reached": True}

    # Act
    async with application.router.lifespan_context(application):
        transport = httpx.ASGITransport(app=application)
        async with httpx.AsyncClient(transport=transport, base_url=ORIGIN) as http:
            response = await http.get("/api/added-later")

    # Assert
    assert response.status_code == 200
    assert response.json() == {"reached": True}


async def test_the_mount_is_idempotent_across_two_lifespans(
    container: AdminContainer, built_bundle: Path
) -> None:
    # Arrange — a second copy of the catch-all is dead weight the router walks on every
    # unmatched request, and two `/assets` mounts would make which one answers an accident.
    assert built_bundle.is_dir()
    application = create_app(container=container)

    # Act
    async with application.router.lifespan_context(application):
        pass
    async with application.router.lifespan_context(application):
        after = [
            route for route in application.routes if getattr(route, "name", None) == "spa-index"
        ]

    # Assert
    assert len(after) == 1


# ---------------------------------------------------------------------------
# /api is never the SPA's to answer
# ---------------------------------------------------------------------------
async def test_an_unknown_api_path_is_still_a_json_404(
    served: httpx.AsyncClient, built_bundle: Path
) -> None:
    # Arrange — the bundle EXISTS, which is the dangerous case: the catch-all has something
    # to serve and must still decline. `built_bundle` is requested for that reason alone.
    assert built_bundle.is_dir()

    # Act
    response = await served.get("/api/nothing-here")

    # Assert
    assert response.status_code == 404
    assert response.json()["error"]["code"] == ErrorCode.NOT_FOUND.value
    assert "text/html" not in response.headers.get("content-type", "")


async def test_the_bare_api_prefix_is_a_json_404_too(
    served: httpx.AsyncClient, built_bundle: Path
) -> None:
    # Arrange — `/api` has no trailing slash and so does not match the `/api/` prefix test.
    # It is written down because "startswith('/api')" and "startswith('/api/')" differ, and
    # only one of them also excludes a future `/apidocs` route.
    assert built_bundle.is_dir()

    # Act
    response = await served.get("/api")

    # Assert
    assert response.status_code == 404
    assert response.json()["error"]["code"] == ErrorCode.NOT_FOUND.value


# ---------------------------------------------------------------------------
# The shell
# ---------------------------------------------------------------------------
async def test_a_browser_url_gets_the_shell_so_a_deep_link_survives_a_cold_load(
    served: httpx.AsyncClient, built_bundle: Path
) -> None:
    # Arrange — this is what makes `/orders/<uuid>` pasteable into Slack: the server has no
    # such route, and answering the shell lets the client router resolve it.
    assert built_bundle.is_dir()

    # Act
    response = await served.get("/orders/3f2b9c1e-0a5d-4f61-9c2a-7b18d4e6f0a3")

    # Assert - the body is the shell with this response's style nonce spliced in, which is
    # the ONE thing that differs between the file on disk and what the browser receives.
    assert response.status_code == 200
    assert response.text == _SHELL.replace(CSP_NONCE_PLACEHOLDER, _served_nonce(response))
    assert response.headers["content-type"].startswith("text/html")


async def test_the_shell_is_never_cached(served: httpx.AsyncClient, built_bundle: Path) -> None:
    # Arrange — index.html is the one filename that does not change between builds, so a
    # cached copy would pin an operator to a bundle referencing chunks that no longer exist.
    assert built_bundle.is_dir()

    # Act
    response = await served.get("/orders")

    # Assert
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["x-content-type-options"] == "nosniff"


async def test_an_unbuilt_console_answers_404_rather_than_500(
    served_unbuilt: httpx.AsyncClient,
) -> None:
    # Arrange — `src/hbd/admin/static/` is gitignored, so a fresh checkout has no bundle at
    # all and the API must still be entirely usable. That is how every other test in this
    # package runs, and it is why a missing shell is a 404 rather than an unhandled OSError.

    # Act
    response = await served_unbuilt.get("/orders")

    # Assert
    assert response.status_code == 404
    assert (await served_unbuilt.get("/api/auth/me")).status_code == 401


# ---------------------------------------------------------------------------
# The hashed assets
# ---------------------------------------------------------------------------
async def test_a_hashed_chunk_is_served_immutable(
    served: httpx.AsyncClient, built_bundle: Path
) -> None:
    # Arrange — safe only because Vite puts a content hash in the filename: a changed file is
    # a changed URL, so a year-long cache can never be stale.
    assert built_bundle.is_dir()

    # Act
    response = await served.get("/assets/index-abc123.js")

    # Assert
    assert response.status_code == 200
    assert response.text == _CHUNK
    assert response.headers["cache-control"] == IMMUTABLE_CACHE_CONTROL.decode()


async def test_the_immutable_carve_out_is_a_prefix_match_and_nothing_wider(
    served: httpx.AsyncClient, built_bundle: Path
) -> None:
    # Arrange — the exemption must not be reachable from a data-bearing path. `/assets` is a
    # DIFFERENT namespace from `/api/assets`, which serves customer media metadata and is
    # exactly what must never be cacheable.
    assert built_bundle.is_dir()

    # Act
    api_assets = await served.get("/api/assets")

    # Assert — 401 (no session), and still no-store.
    assert api_assets.status_code == 401
    assert api_assets.headers["cache-control"] == "no-store"


# ---------------------------------------------------------------------------
# Methods
# ---------------------------------------------------------------------------
async def test_the_catch_all_does_not_swallow_a_wrong_method_on_a_real_route(
    served: httpx.AsyncClient, built_bundle: Path
) -> None:
    # Arrange — Starlette answers out of the first PARTIAL match it found, which is the real
    # route registered earlier. If the catch-all accepted every method it would FULL-match
    # here and turn a 405 into a 200 full of HTML.
    assert built_bundle.is_dir()

    # Act
    response = await served.post("/healthz")

    # Assert
    assert response.status_code == 405


async def test_a_non_get_to_an_unrouted_path_is_not_the_shell(
    served: httpx.AsyncClient, built_bundle: Path
) -> None:
    # Arrange — a browser only ever GETs a URL. Anything else reaching an unrouted path is a
    # client that has the wrong idea, and handing it the shell would hide that.
    assert built_bundle.is_dir()

    # Act
    response = await served.post("/orders")

    # Assert
    assert response.status_code in {404, 405}
    assert "text/html" not in response.headers.get("content-type", "")
