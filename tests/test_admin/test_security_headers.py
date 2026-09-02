"""The response headers, asserted on **every** kind of response this app can produce.

The headers are stamped onto the raw ``http.response.start`` message rather than onto a
``Response`` object, and this file is why: a 200 from a handler, a 401 from the error
envelope, a 404 from the router and an empty 200 from ``/healthz`` are produced by four
different code paths, and ``nosniff`` missing from any one of them is the stored-XSS primitive
§12.1 T7 describes. A test that only checked a happy-path 200 would have said the control was
present.
"""

from __future__ import annotations

import httpx
import pytest

from hbd.admin.container import AdminContainer
from hbd.admin.middleware.security_headers import CSP_TEMPLATE
from tests.test_admin.conftest import ORIGIN, create_account, csrf_headers, sign_in

_PATHS = ("/healthz", "/readyz", "/api/auth/me", "/api/nothing-here")

_EXPECTED_DIRECTIVES = (
    "default-src 'self'",
    "script-src 'self'",
    "img-src 'self' data:",
    "media-src 'self'",
    "connect-src 'self'",
    "object-src 'none'",
    "base-uri 'none'",
    "frame-ancestors 'none'",
    "form-action 'none'",
    "worker-src 'none'",
)


@pytest.mark.parametrize("path", _PATHS)
async def test_every_response_carries_the_three_constant_headers(
    client: httpx.AsyncClient, path: str
) -> None:
    # Act
    response = await client.get(path)

    # Assert
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["referrer-policy"] == "no-referrer"
    assert response.headers["cache-control"] == "no-store"


@pytest.mark.parametrize("path", _PATHS)
async def test_every_response_carries_the_full_content_security_policy(
    client: httpx.AsyncClient, path: str
) -> None:
    # Act
    policy = (await client.get(path)).headers["content-security-policy"]

    # Assert
    for directive in _EXPECTED_DIRECTIVES:
        assert directive in policy
    assert "style-src 'self' 'nonce-" in policy


async def test_the_style_nonce_is_fresh_on_every_response(client: httpx.AsyncClient) -> None:
    # Act
    first = (await client.get("/healthz")).headers["content-security-policy"]
    second = (await client.get("/healthz")).headers["content-security-policy"]

    # Assert - a nonce reused across responses is not a nonce
    assert first != second


def test_the_policy_template_has_exactly_one_nonce_slot() -> None:
    # A second ``{nonce}`` would still format, and would put the same value in two places
    # where only the style directive is meant to carry one.
    assert CSP_TEMPLATE.count("{nonce}") == 1


async def test_the_headers_survive_a_204_with_no_body(
    client: httpx.AsyncClient, container: AdminContainer
) -> None:
    # Arrange
    await create_account(container)
    await sign_in(client)

    # Act
    response = await client.post("/api/auth/logout", headers=csrf_headers(client))

    # Assert
    assert response.status_code == 204
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["cache-control"] == "no-store"


async def test_the_headers_are_on_a_login_response_that_sets_cookies(
    client: httpx.AsyncClient, container: AdminContainer
) -> None:
    # Arrange
    await create_account(container)

    # Act
    response = await sign_in(client)

    # Assert - the one response that carries a credential must not be cacheable
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["x-content-type-options"] == "nosniff"


async def test_a_rejected_cross_origin_request_is_still_hardened(
    client: httpx.AsyncClient,
) -> None:
    # Act
    response = await client.post(
        "/api/auth/login",
        json={"username": "x", "password": "y"},
        headers={"Origin": f"{ORIGIN}.evil.example"},
    )

    # Assert
    assert response.status_code == 403
    assert response.headers["x-content-type-options"] == "nosniff"
