"""``/healthz`` touches nothing, and ``/readyz`` says one word to a stranger.

The first test is the one that matters operationally: ``/healthz`` is asserted against a
container whose database engine has been disposed **and** whose Redis raises on every
command. If it still answers 200, it cannot participate in the failure mode it exists to
avoid — an orchestrator restarting every replica because Postgres blinked, which turns a
database incident into a full outage.

The rest assert the §6.3 gate: a stranger learns ``ok`` or ``degraded`` and nothing else, and
the detailed body needs either a session or a probe token.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import timedelta

import httpx
import pytest
import sqlalchemy as sa

from bayram.admin.container import AdminContainer
from bayram.admin.csrf import SESSION_COOKIE_NAME
from bayram.admin.routers.health import (
    CONFIG_VERSION_KEY,
    PROBE_TOKEN_HEADER,
    STATUS_DEGRADED,
    STATUS_OK,
)
from bayram.admin.security.tokens import sha256_hex
from bayram.admin.sessions import mirror_key
from bayram.db.base import utc_now
from bayram.db.models.admin_session import AdminSessionRow
from tests.test_admin.conftest import (
    PROBE_TOKEN,
    FakeRedis,
    MemoryRateLimits,
    create_account,
    make_settings,
    open_client,
    open_container,
    sign_in,
)

_DETAIL_KEYS = {"database", "redis", "configVersion"}


async def test_healthz_answers_with_an_empty_body_and_touches_nothing(
    client: httpx.AsyncClient, container: AdminContainer, fake_redis: FakeRedis
) -> None:
    # Arrange - both backing services are gone
    fake_redis.is_down = True
    await container.engine.dispose()

    # Act
    response = await client.get("/healthz")

    # Assert
    assert response.status_code == 200
    assert response.content == b""


async def test_readyz_tells_a_stranger_the_status_and_nothing_else(
    client: httpx.AsyncClient,
) -> None:
    # Act
    response = await client.get("/readyz")

    # Assert
    assert response.status_code == 200
    assert response.json() == {"status": STATUS_OK}


async def test_readyz_tells_a_stranger_ok_even_while_it_is_degraded(
    client: httpx.AsyncClient, fake_redis: FakeRedis
) -> None:
    # Arrange - the deployment is degraded, and the caller has neither a session nor a token
    fake_redis.is_down = True

    # Act
    response = await client.get("/readyz")

    # Assert - §6.3's rationale covers the one-word answer too: "degraded" is the same fleet
    # telemetry as ``{"database": false}``, one word shorter
    assert response.json() == {"status": STATUS_OK}


async def test_readyz_reports_degraded_to_an_authorised_caller(
    client: httpx.AsyncClient, container: AdminContainer, fake_redis: FakeRedis
) -> None:
    # Arrange - sign in first; only then does Redis go away
    await create_account(container)
    await sign_in(client)
    fake_redis.is_down = True

    # Act
    body = (await client.get("/readyz")).json()

    # Assert
    assert body["status"] == STATUS_DEGRADED
    assert body["redis"] is False


async def test_readyz_is_a_get_that_writes_nothing(
    client: httpx.AsyncClient, container: AdminContainer, fake_redis: FakeRedis
) -> None:
    """§12.1 T8: no state change on a GET, which is also what makes ``SameSite=Lax`` safe.

    The session check on this route runs the whole authentication path, and that path
    advances ``last_seen_at``. The arrangement makes such a write certain if one is going to
    happen: the mirror is dropped so the row is read, and ``last_seen_at`` is pushed well
    past the touch interval.
    """
    # Arrange
    await create_account(container)
    await sign_in(client)
    stale = utc_now() - timedelta(minutes=5)
    async with container.session_factory.begin() as db:
        await db.execute(sa.update(AdminSessionRow).values(last_seen_at=stale))
    fake_redis.values.pop(mirror_key(sha256_hex(client.cookies[SESSION_COOKIE_NAME])), None)

    # Act
    response = await client.get("/readyz")

    # Assert - authorised (so the check really ran), and the row is untouched
    assert set(response.json()) >= _DETAIL_KEYS
    async with container.session_factory.begin() as db:
        seen = await db.scalar(sa.select(AdminSessionRow.last_seen_at))
    assert seen == stale


async def test_readyz_gives_a_signed_in_operator_the_detail(
    client: httpx.AsyncClient, container: AdminContainer, fake_redis: FakeRedis
) -> None:
    # Arrange
    await create_account(container)
    await sign_in(client)
    fake_redis.values[CONFIG_VERSION_KEY] = "42"

    # Act
    body = (await client.get("/readyz")).json()

    # Assert
    assert set(body) >= _DETAIL_KEYS
    assert body["database"] is True
    assert body["configVersion"] == 42


@pytest.fixture
async def probe_client(
    fake_redis: FakeRedis, rate_limits: MemoryRateLimits
) -> AsyncIterator[httpx.AsyncClient]:
    """A client whose deployment has a probe token configured."""
    settings = make_settings(admin_probe_token=PROBE_TOKEN)
    async with (
        open_container(settings, fake_redis, rate_limits) as container,
        open_client(container) as http,
    ):
        yield http


async def test_readyz_gives_a_matching_probe_token_the_detail(
    probe_client: httpx.AsyncClient,
) -> None:
    # Act
    body = (await probe_client.get("/readyz", headers={PROBE_TOKEN_HEADER: PROBE_TOKEN})).json()

    # Assert
    assert set(body) >= _DETAIL_KEYS


async def test_readyz_refuses_the_detail_for_a_wrong_probe_token(
    probe_client: httpx.AsyncClient,
) -> None:
    body = (await probe_client.get("/readyz", headers={PROBE_TOKEN_HEADER: "not-the-token"})).json()
    assert body == {"status": STATUS_OK}


async def test_an_empty_probe_token_setting_authorises_nobody(
    client: httpx.AsyncClient,
) -> None:
    # Arrange - the default settings leave admin_probe_token empty
    # Act
    body = (await client.get("/readyz", headers={PROBE_TOKEN_HEADER: ""})).json()

    # Assert
    assert body == {"status": STATUS_OK}


async def test_a_malformed_config_version_reads_as_null_rather_than_failing(
    client: httpx.AsyncClient, container: AdminContainer, fake_redis: FakeRedis
) -> None:
    # Arrange
    await create_account(container)
    await sign_in(client)
    fake_redis.values[CONFIG_VERSION_KEY] = "not-a-number"

    # Act
    body = (await client.get("/readyz")).json()

    # Assert - a bad cache value degrades to "unknown", never to a 500 on a readiness probe
    assert body["configVersion"] is None
