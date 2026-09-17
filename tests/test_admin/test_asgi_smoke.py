"""Boot, settings and the auth round trip — Slice 1a's acceptance list, in one file.

The load-bearing test here is
:func:`test_admin_settings_has_no_vendor_field_at_all`. Every other control in this package
assumes D10 holds; that one asserts it structurally, by enumerating the model's fields rather
than by checking a value. A test that only asserted "the key is not read" would keep passing
the day somebody adds an optional field for convenience.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Final
from uuid import uuid4

import httpx
import pytest
from fastapi import FastAPI

from bayram.admin.app import FORBIDDEN_ENV_VARS, create_app
from bayram.admin.container import AdminContainer
from bayram.admin.deps import CurrentAdmin, require_permission
from bayram.admin.errors import AdminErrorCode, AdminProblem, ProblemError
from bayram.admin.middleware import CORRELATION_HEADER
from bayram.admin.routers import auth as auth_router
from bayram.admin.security.passwords import verify_password_async
from bayram.admin.security.permissions import Permission
from bayram.admin.security.ratelimit import LOGIN_MAX_PER_USER_IP, LOGIN_WINDOW_S
from bayram.admin.sessions import SessionSnapshot
from bayram.admin.settings import AdminSettings, build_admin_settings
from bayram.config import VENDOR_SECRET_FIELDS
from bayram.db.base import utc_now
from bayram.db.enums import AdminRole
from bayram.errors import ConfigError, ErrorCode
from tests.test_admin.conftest import (
    ORIGIN,
    PASSWORD,
    USERNAME,
    FakeRedis,
    create_account,
    csrf_headers,
    make_settings,
    open_client,
    open_container,
    sign_in,
)

_VENDOR_SHAPED: Final[tuple[str, ...]] = ("token", "api_key", "apikey", "secret_key")
#: The two secrets that legitimately live on this model, neither of which is a vendor
#: credential: one protects the audit chain, the other lets a fleet monitor read /readyz.
#: Named individually so a *third* secret-shaped field cannot join them by accident.
_ALLOWED_SECRETS: Final[frozenset[str]] = frozenset({"admin_audit_hmac_key", "admin_probe_token"})
_HEX32: Final[str] = "a" * 32


# ---------------------------------------------------------------------------
# D10: the model that cannot hold a vendor credential
# ---------------------------------------------------------------------------
def test_admin_settings_has_no_vendor_field_at_all() -> None:
    # Arrange
    names = set(AdminSettings.model_fields)

    # Act
    vendor_named = names & set(VENDOR_SECRET_FIELDS)
    vendor_shaped = {
        name for name in names if any(marker in name for marker in _VENDOR_SHAPED)
    } - _ALLOWED_SECRETS

    # Assert
    assert vendor_named == set()
    assert vendor_shaped == set()
    # And the model cannot be *told* about one either: extra="ignore" drops it silently
    # rather than storing it somewhere a later refactor could read.
    assert "telegram_bot_token" not in make_settings().model_dump()


async def test_settings_and_app_boot_with_every_vendor_secret_unset(
    container: AdminContainer, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Arrange - the three variables are absent (the autouse fixture stripped them)
    for name in FORBIDDEN_ENV_VARS:
        monkeypatch.delenv(name, raising=False)

    # Act
    application = create_app(container=container)
    async with application.router.lifespan_context(application):
        transport = httpx.ASGITransport(app=application)
        async with httpx.AsyncClient(transport=transport, base_url=ORIGIN) as http:
            response = await http.get("/healthz")

    # Assert
    assert response.status_code == 200


@pytest.mark.parametrize("variable", FORBIDDEN_ENV_VARS)
async def test_prod_refuses_to_start_when_a_vendor_secret_is_in_the_environment(
    container: AdminContainer, monkeypatch: pytest.MonkeyPatch, variable: str
) -> None:
    # Arrange
    monkeypatch.setenv(variable, "a-value-that-must-not-be-here")
    prod = make_settings(environment="prod", admin_cookie_secure=True)
    application = create_app(prod)

    # Act / Assert
    with pytest.raises(ConfigError) as caught:
        async with application.router.lifespan_context(application):
            pass  # pragma: no cover - the lifespan must not reach here
    assert variable in caught.value.operator_message


@pytest.mark.parametrize("variable", FORBIDDEN_ENV_VARS)
async def test_dev_only_warns_when_a_vendor_secret_is_in_the_environment(
    admin_app: FastAPI,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    variable: str,
) -> None:
    # Arrange - the lifespan installs the real root handler, which would evict caplog's;
    # this test is about the warning, not about how logging is configured.
    monkeypatch.setenv(variable, "a-value-that-must-not-be-here")
    monkeypatch.setattr("bayram.admin.app.configure_logging", lambda **_: None)

    # Act
    with caplog.at_level("WARNING"):
        async with admin_app.router.lifespan_context(admin_app):
            pass

    # Assert - boots, and names the variable without ever carrying its value
    warnings = [r for r in caplog.records if r.levelname == "WARNING"]
    assert any(variable in str(getattr(r, "variables", "")) for r in warnings)
    assert not any("a-value-that-must-not-be-here" in r.getMessage() for r in warnings)


async def test_the_lifespan_refuses_while_the_panel_is_disabled(
    container: AdminContainer,
) -> None:
    # Arrange
    disabled = make_settings(admin_enabled=False)
    application = create_app(disabled)

    # Act / Assert
    with pytest.raises(ConfigError, match="BAYRAM_ADMIN_ENABLED"):
        async with application.router.lifespan_context(application):
            pass  # pragma: no cover - the lifespan must not reach here


# ---------------------------------------------------------------------------
# Settings bounds
# ---------------------------------------------------------------------------
def test_secure_cookies_may_not_be_switched_off_outside_dev() -> None:
    with pytest.raises(ValueError, match="admin_cookie_secure"):
        make_settings(environment="staging", admin_cookie_secure=False)


def test_secure_is_on_in_every_environment() -> None:
    # dev included: the cookies are __Host- prefixed, and a browser rejects that prefix
    # without Secure outright. See tests/test_admin/test_settings_and_boot.py.
    assert make_settings(environment="dev").is_cookie_secure is True
    assert make_settings(environment="staging").is_cookie_secure is True
    assert make_settings(environment="prod").is_cookie_secure is True


def test_debug_logging_is_refused_in_prod() -> None:
    with pytest.raises(ValueError, match="DEBUG"):
        make_settings(environment="prod", log_level="DEBUG")


def test_an_idle_window_longer_than_the_absolute_cap_is_refused() -> None:
    with pytest.raises(ValueError, match="idle"):
        make_settings(admin_session_ttl_s=3_600, admin_session_idle_ttl_s=7_200)


def test_a_public_origin_with_a_path_is_refused() -> None:
    with pytest.raises(ValueError, match="no path"):
        make_settings(admin_public_origin="https://admin.example.com/panel")


def test_a_malformed_trusted_proxy_cidr_fails_the_build_naming_the_variable() -> None:
    with pytest.raises(ConfigError, match="BAYRAM_ADMIN_TRUSTED_PROXY_CIDRS"):
        build_admin_settings(
            {
                "database_url": "sqlite+aiosqlite:///:memory:",
                "admin_audit_hmac_key": "x" * 48,
                "admin_trusted_proxy_cidrs": "not-a-cidr",
            }
        )


def test_a_comma_separated_cidr_list_is_parsed_from_the_environment() -> None:
    settings = make_settings(admin_trusted_proxy_cidrs="10.0.0.0/8, 192.168.1.5/32")
    assert len(settings.trusted_proxies) == 2


# ---------------------------------------------------------------------------
# The two taxonomies stay disjoint
# ---------------------------------------------------------------------------
def test_the_admin_taxonomy_shares_no_member_with_the_pipeline_taxonomy() -> None:
    assert set(AdminErrorCode) & set(ErrorCode) == set()


# ---------------------------------------------------------------------------
# The round trip
# ---------------------------------------------------------------------------
async def test_signing_in_sets_both_cookies_with_the_documented_flags(
    client: httpx.AsyncClient, container: AdminContainer
) -> None:
    # Arrange
    await create_account(container)

    # Act
    response = await sign_in(client)

    # Assert
    assert response.status_code == 200
    assert response.json() == {"mustChangePassword": False}
    cookies = "; ".join(response.headers.get_list("set-cookie"))
    assert "__Host-bayram_session=" in cookies
    assert "__Host-bayram_csrf=" in cookies
    assert cookies.count("SameSite=lax") == 2
    assert cookies.count("HttpOnly") == 1  # the session cookie only; the SPA reads the CSRF one
    assert "Domain=" not in cookies
    assert cookies.count("Path=/") == 2


async def test_me_reports_the_role_read_from_the_database(
    client: httpx.AsyncClient, container: AdminContainer
) -> None:
    # Arrange
    await create_account(container, role=AdminRole.SUPPORT)
    await sign_in(client)

    # Act
    response = await client.get("/api/auth/me")

    # Assert
    assert response.status_code == 200
    body = response.json()
    assert body["username"] == USERNAME
    assert body["role"] == AdminRole.SUPPORT.value
    assert body["mustChangePassword"] is False


async def test_an_unknown_username_and_a_wrong_password_are_indistinguishable(
    client: httpx.AsyncClient, container: AdminContainer
) -> None:
    # Arrange
    await create_account(container)

    # Act
    unknown = await sign_in(client, username="nobody", password=PASSWORD)
    wrong = await sign_in(client, password="not-the-password")

    # Assert
    assert unknown.status_code == wrong.status_code == 401
    assert unknown.json()["error"]["message"] == wrong.json()["error"]["message"]
    assert unknown.json()["error"]["code"] == AdminErrorCode.UNAUTHENTICATED.value


async def test_a_login_without_an_origin_header_is_refused(
    client: httpx.AsyncClient, container: AdminContainer
) -> None:
    # Arrange
    await create_account(container)

    # Act
    response = await client.post(
        "/api/auth/login", json={"username": USERNAME, "password": PASSWORD}
    )

    # Assert
    assert response.status_code == 403
    assert response.json()["error"]["code"] == AdminErrorCode.ORIGIN_REJECTED.value


async def test_a_request_without_a_session_is_401(client: httpx.AsyncClient) -> None:
    response = await client.get("/api/auth/me")
    assert response.status_code == 401
    assert response.json()["error"]["code"] == AdminErrorCode.UNAUTHENTICATED.value


# ---------------------------------------------------------------------------
# CSRF: the header is compared against the stored column, not against the cookie
# ---------------------------------------------------------------------------
async def test_a_header_matching_the_cookie_but_not_the_session_row_is_refused(
    client: httpx.AsyncClient, container: AdminContainer
) -> None:
    # Arrange - the attacker has written a cookie for the registrable domain and echoes it
    await create_account(container)
    await sign_in(client)
    forged = "forged-value-an-attacker-can-set"
    client.cookies.set("__Host-bayram_csrf", forged)

    # Act
    response = await client.post(
        "/api/auth/logout", headers={"Origin": ORIGIN, "X-CSRF-Token": forged}
    )

    # Assert
    assert response.status_code == 403
    assert response.json()["error"]["code"] == AdminErrorCode.CSRF_REJECTED.value


async def test_a_mutation_carrying_the_stored_token_is_accepted(
    client: httpx.AsyncClient, container: AdminContainer
) -> None:
    # Arrange
    await create_account(container)
    await sign_in(client)

    # Act
    response = await client.post("/api/auth/logout", headers=csrf_headers(client))

    # Assert
    assert response.status_code == 204


async def test_a_mutation_from_another_origin_is_refused(
    client: httpx.AsyncClient, container: AdminContainer
) -> None:
    # Arrange
    await create_account(container)
    await sign_in(client)
    headers = csrf_headers(client) | {"Origin": "https://evil.example"}

    # Act
    response = await client.post("/api/auth/logout", headers=headers)

    # Assert
    assert response.status_code == 403
    assert response.json()["error"]["code"] == AdminErrorCode.ORIGIN_REJECTED.value


# ---------------------------------------------------------------------------
# The forced-rotation gate
# ---------------------------------------------------------------------------
async def test_every_route_but_password_and_me_is_403_until_the_password_is_changed(
    client: httpx.AsyncClient, container: AdminContainer
) -> None:
    # Arrange
    await create_account(container, must_change_password=True)
    login = await sign_in(client)
    assert login.json() == {"mustChangePassword": True}

    # Act
    me = await client.get("/api/auth/me")
    logout = await client.post("/api/auth/logout", headers=csrf_headers(client))

    # Assert
    assert me.status_code == 200
    assert me.json()["mustChangePassword"] is True
    assert logout.status_code == 403
    assert logout.json()["error"]["details"]["reason"] == "password_change_required"


async def test_changing_the_password_lifts_the_gate_and_re_issues_the_session(
    client: httpx.AsyncClient, container: AdminContainer
) -> None:
    # Arrange
    await create_account(container, must_change_password=True)
    await sign_in(client)
    before = client.cookies.get("__Host-bayram_session")

    # Act
    changed = await client.post(
        "/api/auth/password",
        json={"currentPassword": PASSWORD, "newPassword": "a-much-longer-new-password"},
        headers=csrf_headers(client),
    )
    after = client.cookies.get("__Host-bayram_session")
    logout = await client.post("/api/auth/logout", headers=csrf_headers(client))

    # Assert
    assert changed.status_code == 200
    assert changed.json() == {"mustChangePassword": False}
    assert after != before
    assert logout.status_code == 204


async def test_the_wrong_current_password_does_not_sign_the_operator_out(
    client: httpx.AsyncClient, container: AdminContainer
) -> None:
    # Arrange
    await create_account(container)
    await sign_in(client)

    # Act
    response = await client.post(
        "/api/auth/password",
        json={"currentPassword": "wrong", "newPassword": "a-much-longer-new-password"},
        headers=csrf_headers(client),
    )

    # Assert - 403, not 401: mistyping your own password is not a session failure
    assert response.status_code == 403
    assert (await client.get("/api/auth/me")).status_code == 200


async def test_a_short_new_password_is_a_422_naming_the_field(
    client: httpx.AsyncClient, container: AdminContainer
) -> None:
    # Arrange
    await create_account(container)
    await sign_in(client)

    # Act
    response = await client.post(
        "/api/auth/password",
        json={"currentPassword": PASSWORD, "newPassword": "short"},
        headers=csrf_headers(client),
    )

    # Assert
    assert response.status_code == 422
    assert response.json()["error"]["code"] == ErrorCode.INVALID_INPUT.value
    assert "body.newPassword" in response.json()["error"]["details"]["fields"]


# ---------------------------------------------------------------------------
# Step-up
# ---------------------------------------------------------------------------
async def test_a_step_up_is_granted_for_one_action_on_one_subject(
    client: httpx.AsyncClient, container: AdminContainer
) -> None:
    # Arrange
    await create_account(container)
    await sign_in(client)

    # Act
    response = await client.post(
        "/api/auth/step-up",
        json={"password": PASSWORD, "scope": "reveal", "subjectId": "order-42"},
        headers=csrf_headers(client),
    )

    # Assert
    assert response.status_code == 200
    assert response.json()["scope"] == "reveal:order-42"


async def test_a_step_up_subject_that_could_not_be_stored_is_refused(
    client: httpx.AsyncClient, container: AdminContainer
) -> None:
    # Arrange
    await create_account(container)
    await sign_in(client)

    # Act
    response = await client.post(
        "/api/auth/step-up",
        json={"password": PASSWORD, "scope": "reveal", "subjectId": "has a space"},
        headers=csrf_headers(client),
    )

    # Assert - refused, never truncated: a truncated scope is a wider grant
    assert response.status_code == 422


async def test_a_step_up_with_the_wrong_password_grants_nothing(
    client: httpx.AsyncClient, container: AdminContainer
) -> None:
    # Arrange
    await create_account(container)
    await sign_in(client)

    # Act
    response = await client.post(
        "/api/auth/step-up",
        json={"password": "wrong", "scope": "user.block", "subjectId": "770000123"},
        headers=csrf_headers(client),
    )

    # Assert
    assert response.status_code == 403


# ---------------------------------------------------------------------------
# Correlation id
# ---------------------------------------------------------------------------
async def test_a_malformed_inbound_correlation_id_is_discarded_and_regenerated(
    client: httpx.AsyncClient,
) -> None:
    # Act
    response = await client.get("/healthz", headers={CORRELATION_HEADER: "abc"})

    # Assert
    echoed = response.headers[CORRELATION_HEADER]
    assert echoed != "abc"
    assert len(echoed) == 32
    assert int(echoed, 16) >= 0


async def test_a_well_shaped_inbound_correlation_id_is_reused(
    client: httpx.AsyncClient,
) -> None:
    response = await client.get("/healthz", headers={CORRELATION_HEADER: _HEX32})
    assert response.headers[CORRELATION_HEADER] == _HEX32


async def test_the_error_envelope_carries_the_same_correlation_id_as_the_header(
    client: httpx.AsyncClient,
) -> None:
    # Act
    response = await client.get("/api/auth/me", headers={CORRELATION_HEADER: _HEX32})

    # Assert
    assert response.status_code == 401
    assert response.json()["error"]["correlationId"] == _HEX32
    assert response.headers[CORRELATION_HEADER] == _HEX32


async def test_an_unknown_route_answers_in_the_error_envelope(
    client: httpx.AsyncClient,
) -> None:
    response = await client.get("/api/nothing-here")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == ErrorCode.NOT_FOUND.value


# ---------------------------------------------------------------------------
# The login limiter, at the route
# ---------------------------------------------------------------------------
async def test_the_eleventh_attempt_is_429_and_no_password_is_ever_hashed(
    client: httpx.AsyncClient, container: AdminContainer, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Arrange - count every argon2 verify the route performs
    await create_account(container)
    verifies = 0
    real = verify_password_async

    async def counting_verify(*args: object, **kwargs: object) -> object:
        nonlocal verifies
        verifies += 1
        return await real(*args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(auth_router, "verify_password_async", counting_verify)

    # Act - ten attempts are allowed, the eleventh is not
    for _ in range(LOGIN_MAX_PER_USER_IP):
        assert (await sign_in(client, password="wrong")).status_code == 401
    hashed_before_the_trip = verifies
    refused = await sign_in(client, password="wrong")

    # Assert - refused before the hash, which is what keeps the limiter from being the
    # CPU-exhaustion vector it exists to prevent
    assert refused.status_code == 429
    assert refused.json()["error"]["code"] == AdminErrorCode.LOGIN_RATE_LIMITED.value
    assert refused.headers["retry-after"] == str(LOGIN_WINDOW_S)
    assert verifies == hashed_before_the_trip


async def test_a_limiter_outage_refuses_the_sign_in_rather_than_waving_it_through(
    fake_redis: FakeRedis,
) -> None:
    # Arrange
    async with (
        open_container(make_settings(), fake_redis, _BrokenRateLimits()) as container,
        open_client(container) as http,
    ):
        await create_account(container)

        # Act
        response = await sign_in(http)

    # Assert - an unlimited login route is worse than an outage, and it reads as one
    assert response.status_code == 503
    assert response.json()["error"]["code"] == AdminErrorCode.SERVICE_UNAVAILABLE.value


class _BrokenRateLimits:
    """Redis is down. The limiter must fail closed rather than allow."""

    counts: dict[str, int] = {}

    async def increment(self, key: str, *, ttl_s: int) -> int:
        raise ConnectionError("the limiter store is unavailable")

    async def increment_by(self, key: str, amount: int, *, ttl_s: int) -> int:
        raise ConnectionError("the limiter store is unavailable")

    async def refund(self, key: str, *, ttl_s: int) -> None:
        raise ConnectionError("the limiter store is unavailable")


# ---------------------------------------------------------------------------
# The permission guard
# ---------------------------------------------------------------------------
async def test_a_role_without_the_permission_is_refused_by_the_router_guard(
    container: AdminContainer,
) -> None:
    # Arrange - a VIEWER has no cell for user.purge, and an absent cell is a denial
    guard = require_permission(Permission.USER_PURGE)
    viewer = CurrentAdmin(
        admin_user_id=uuid4(),
        username="viewer",
        role=AdminRole.VIEWER,
        must_change_password=False,
        last_login_at=None,
        session=_snapshot(),
        token_sha256="0" * 64,
        client_ip=None,
    )

    # Act / Assert
    with pytest.raises(ProblemError) as caught:
        await guard(viewer, container)
    failure = caught.value.failure
    assert isinstance(failure, AdminProblem)
    assert failure.code is AdminErrorCode.FORBIDDEN


async def test_a_role_that_holds_the_permission_is_let_through(
    container: AdminContainer,
) -> None:
    guard = require_permission(Permission.SESSION_SELF)
    viewer = CurrentAdmin(
        admin_user_id=uuid4(),
        username="viewer",
        role=AdminRole.VIEWER,
        must_change_password=False,
        last_login_at=None,
        session=_snapshot(),
        token_sha256="0" * 64,
        client_ip=None,
    )
    assert (await guard(viewer, container)) is viewer


def _snapshot() -> SessionSnapshot:
    """A session that is live by both clocks. Its contents do not matter to the guard."""
    now = utc_now()
    return SessionSnapshot(
        session_id=uuid4(),
        admin_user_id=uuid4(),
        csrf_token="csrf",
        created_at=now,
        last_seen_at=now,
        expires_at=now + timedelta(hours=1),
        step_up_scope=None,
        step_up_at=None,
    )
