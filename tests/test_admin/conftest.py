"""Fixtures for the admin API: in-memory SQLite, a fake Redis, and an ASGI client.

**No server of any kind.** The database is the same in-memory SQLite the ``test_db`` suite
uses, Redis is a dictionary, and the HTTP client speaks to the application through
``httpx.ASGITransport`` — the app object, in this process, with no socket. That is what lets
an authentication test assert on a Redis key and a database row in the same three lines.

The argon2 parameters are dropped to the model's floors. A real verify is ~50 ms by design,
and the login path is exercised dozens of times here; the floors keep the suite fast without
changing a single branch, because nothing in the code reads the cost.

Every ``HBD_`` variable is stripped from the environment and ``.env.admin`` is disabled, so a
developer's shell cannot change a test outcome — the same isolation ``tests/conftest.py``
applies to ``Settings``.
"""

from __future__ import annotations

import dataclasses
import os
from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Any, Final, cast

import httpx
import pytest
from fastapi import APIRouter, FastAPI
from fastapi.routing import APIRoute
from redis.asyncio import Redis

from hbd.admin.app import create_app
from hbd.admin.container import AdminContainer, build_admin_container
from hbd.admin.csrf import CSRF_COOKIE_NAME, CSRF_HEADER_NAME
from hbd.admin.security.passwords import hash_password
from hbd.admin.security.ratelimit import WindowCounterStore
from hbd.admin.settings import AdminSettings
from hbd.config import ENV_PREFIX
from hbd.db.admin import accounts
from hbd.db.enums import AdminRole
from hbd.db.models.admin_user import AdminUserRow

#: A fixed instant so a test that asserts on a TTL or a window is not a race.
NOW: Final[datetime] = datetime(2026, 3, 21, 9, 0, 0, tzinfo=UTC)

#: ``https`` even though ``ASGITransport`` never opens a socket: the session and CSRF cookies
#: carry ``Secure`` in every environment (the ``__Host-`` prefix requires it), and httpx's
#: cookie jar — like a browser, but stricter than Chrome and Firefox, which treat
#: ``127.0.0.1`` as a secure context over plain HTTP — will not send a ``Secure`` cookie to an
#: ``http://`` URL. With ``http`` here, every signed-in request in this package silently
#: arrives with no cookies at all and 401s.
ORIGIN: Final[str] = "https://127.0.0.1:8080"
PASSWORD: Final[str] = "correct-horse-battery-staple"
USERNAME: Final[str] = "owner"
#: 32 characters is the model's floor for the audit key.
HMAC_KEY: Final[str] = "x" * 48
PROBE_TOKEN: Final[str] = "probe-token-for-tests"

_MEMORY_URL: Final[str] = "sqlite+aiosqlite:///:memory:"
_ARGON2_TIME_COST: Final[int] = 2
_ARGON2_MEMORY_KIB: Final[int] = 32_768
_ARGON2_PARALLELISM: Final[int] = 1


class FakeRedis:
    """The five commands this package issues, over a dictionary.

    ``is_down`` makes every command raise, which is how the fail-open-towards-the-database
    and fail-closed-on-the-limiter paths are asserted without unplugging anything.
    """

    def __init__(self) -> None:
        self.values: dict[str, str] = {}
        self.ttls: dict[str, int] = {}
        self.is_down = False

    def _guard(self) -> None:
        if self.is_down:
            raise ConnectionError("fake redis is down")

    async def get(self, key: str) -> str | None:
        self._guard()
        return self.values.get(key)

    async def set(self, key: str, value: str, *, ex: int | None = None) -> bool:
        self._guard()
        self.values[key] = value
        if ex is not None:
            self.ttls[key] = ex
        return True

    async def delete(self, *keys: str) -> int:
        self._guard()
        removed = 0
        for key in keys:
            removed += 1 if self.values.pop(key, None) is not None else 0
            self.ttls.pop(key, None)
        return removed

    async def ping(self) -> bool:
        self._guard()
        return True

    async def aclose(self) -> None:
        return None


class MemoryRateLimits:
    """A :class:`WindowCounterStore` over a dictionary. Records TTLs so they can be asserted."""

    def __init__(self) -> None:
        self.counts: dict[str, int] = {}
        self.hashes_before_trip = 0

    async def increment(self, key: str, *, ttl_s: int) -> int:
        return await self.increment_by(key, 1, ttl_s=ttl_s)

    async def increment_by(self, key: str, amount: int, *, ttl_s: int) -> int:
        del ttl_s
        self.counts[key] = self.counts.get(key, 0) + amount
        return self.counts[key]

    async def refund(self, key: str, *, ttl_s: int) -> None:
        del ttl_s
        self.counts[key] = max(0, self.counts.get(key, 0) - 1)


@pytest.fixture(autouse=True)
def _isolated_environment(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """No ``HBD_`` variable from the developer's shell reaches any test in this package."""
    for name in tuple(os.environ):
        if name.startswith(ENV_PREFIX):
            monkeypatch.delenv(name, raising=False)
    yield


def make_settings(**overrides: Any) -> AdminSettings:
    """A valid :class:`AdminSettings` with the panel on and the argon2 cost at its floor."""
    values: dict[str, Any] = {
        "environment": "dev",
        "database_url": _MEMORY_URL,
        "redis_url": "redis://localhost:6379/0",
        "admin_enabled": True,
        "admin_public_origin": ORIGIN,
        "admin_audit_hmac_key": HMAC_KEY,
        "admin_argon2_time_cost": _ARGON2_TIME_COST,
        "admin_argon2_memory_kib": _ARGON2_MEMORY_KIB,
        "admin_argon2_parallelism": _ARGON2_PARALLELISM,
    }
    values.update(overrides)
    return AdminSettings(_env_file=None, **values)


@pytest.fixture
def admin_settings() -> AdminSettings:
    return make_settings()


@pytest.fixture
def fake_redis() -> FakeRedis:
    return FakeRedis()


@pytest.fixture
def rate_limits() -> MemoryRateLimits:
    return MemoryRateLimits()


@asynccontextmanager
async def open_container(
    settings: AdminSettings, fake_redis: FakeRedis, rate_limits: WindowCounterStore
) -> AsyncIterator[AdminContainer]:
    """A real container over in-memory SQLite, with the two network resources faked.

    Built by ``build_admin_container`` and then narrowed with ``dataclasses.replace`` rather
    than assembled by hand: the engine, the pool arguments and the schema shortcut are then
    exactly the ones production uses, and only the two things a test cannot have are swapped.
    """
    built = await build_admin_container(settings)
    try:
        yield dataclasses.replace(
            built, redis=cast("Redis[str]", fake_redis), rate_limits=rate_limits
        )
    finally:
        await built.engine.dispose()


@asynccontextmanager
async def open_client(container: AdminContainer) -> AsyncIterator[httpx.AsyncClient]:
    """An ASGI client with the lifespan actually entered.

    ``ASGITransport`` does not run the lifespan, and the lifespan is where every boot refusal
    lives — a client that skipped it would test an application that never had to start.
    """
    application = create_app(container=container)
    async with application.router.lifespan_context(application):
        transport = httpx.ASGITransport(app=application)
        async with httpx.AsyncClient(transport=transport, base_url=ORIGIN) as http:
            yield http


@pytest.fixture
async def container(
    admin_settings: AdminSettings, fake_redis: FakeRedis, rate_limits: MemoryRateLimits
) -> AsyncIterator[AdminContainer]:
    async with open_container(admin_settings, fake_redis, rate_limits) as built:
        yield built


async def create_account(
    container: AdminContainer,
    *,
    username: str = USERNAME,
    password: str = PASSWORD,
    role: AdminRole = AdminRole.OWNER,
    must_change_password: bool = False,
) -> AdminUserRow:
    """Insert one operator with a real argon2 hash, so the login path is the real one."""
    async with container.session_factory.begin() as db:
        return await accounts.create(
            db,
            username=username,
            password_hash=hash_password(password, hasher=container.hasher),
            role=role,
            must_change_password=must_change_password,
            now=NOW,
        )


def api_routes(application: FastAPI) -> list[APIRoute]:
    """Every ``APIRoute`` the application serves, however it stores its included routers.

    ``app.routes`` is **not** flat on this FastAPI: ``include_router`` appends one wrapper
    per router and keeps the router it was built from on ``original_router``. A test that
    reads ``getattr(route, "path", None)`` off ``application.routes`` therefore sees ``None``
    for every included router and silently concludes nothing is mounted. Read tolerantly, so
    a caller asserts what the application serves rather than which of the two shapes the
    installed version happens to use.
    """
    found: list[APIRoute] = []
    for route in application.routes:
        if isinstance(route, APIRoute):
            found.append(route)
            continue
        included = getattr(route, "original_router", None)
        if isinstance(included, APIRouter):
            found.extend(nested for nested in included.routes if isinstance(nested, APIRoute))
    return found


@pytest.fixture
def admin_app(container: AdminContainer) -> FastAPI:
    """The application, wired to the test container. Its lifespan will not close it."""
    return create_app(container=container)


@pytest.fixture
async def client(admin_app: FastAPI) -> AsyncIterator[httpx.AsyncClient]:
    """The default client: the ``container`` fixture's application, lifespan entered."""
    async with admin_app.router.lifespan_context(admin_app):
        transport = httpx.ASGITransport(app=admin_app)
        async with httpx.AsyncClient(transport=transport, base_url=ORIGIN) as http:
            yield http


async def sign_in(
    client: httpx.AsyncClient, *, username: str = USERNAME, password: str = PASSWORD
) -> httpx.Response:
    """POST /api/auth/login with the ``Origin`` header a browser would send."""
    return await client.post(
        "/api/auth/login",
        json={"username": username, "password": password},
        headers={"Origin": ORIGIN},
    )


def csrf_headers(client: httpx.AsyncClient) -> dict[str, str]:
    """The headers a signed-in SPA sends on every mutation: ``Origin`` plus the CSRF token."""
    return {"Origin": ORIGIN, CSRF_HEADER_NAME: client.cookies.get(CSRF_COOKIE_NAME) or ""}
