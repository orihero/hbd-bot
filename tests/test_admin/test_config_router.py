"""``GET /api/config`` over the real ASGI stack, with real credentials in the settings.

The container this file builds is deliberately configured with DSNs that carry passwords, an
audit HMAC key and a probe token — otherwise the assertion that matters here would be
asserting against nothing. :data:`DSN_WITH_USERINFO` is checked against the raw
``database_url`` first, so a regex that had stopped matching could not pass this file
silently, and only then against the response body.

There is no 403 case in this file, and that is the matrix rather than an omission: §12.2
gives CONFIG_READ as **M** to all four roles, so every role is asserted to get the identical
body instead. The role-refusal case for this slice lives in ``test_admins_router``.

The engine is built from the in-memory URL and the credentialed ``database_url`` is written
onto the settings object afterwards. The endpoint reports ``container.settings``, so that is
enough to serve a real DSN, and it avoids pointing a pool at a Postgres host that does not
exist — this route sits behind a login, and the login reads ``admin_users``.
"""

from __future__ import annotations

import dataclasses
import re
from collections.abc import AsyncIterator
from typing import Final

import httpx
import pytest

from bayram.admin.container import AdminContainer
from bayram.admin.routers.config import CONFIG_PATH
from bayram.admin.schemas.config_view import endpoint_of, to_config_view
from bayram.admin.settings import AdminSettings
from bayram.db.enums import AdminRole
from tests.test_admin.conftest import (
    ORIGIN,
    PASSWORD,
    FakeRedis,
    MemoryRateLimits,
    create_account,
    make_settings,
    open_client,
    open_container,
    sign_in,
)

#: A DSN with userinfo, which is the shape §12.4 says must never reach a response body. The
#: acceptance criterion of this slice is that the whole body fails to match it.
DSN_WITH_USERINFO: Final[re.Pattern[str]] = re.compile(r"://[^/\s:@]+:[^/\s@]+@")

DATABASE_DSN: Final[str] = "postgresql+asyncpg://bayram_admin:sup3r-s3cret-pw@db.internal:6432/hbd"
REDIS_DSN: Final[str] = "redis://bayram_cache:cache-s3cret-pw@cache.internal:6380/2"
AUDIT_DSN: Final[str] = "postgresql+asyncpg://bayram_owner:owner-r0le-pw@db.internal:6432/hbd"
AUDIT_HMAC_KEY: Final[str] = "audit-hmac-key-that-must-never-be-shipped"
PROBE_TOKEN: Final[str] = "probe-token-nobody-outside-the-fleet-monitor-may-read"

#: Every secret in one place, so a new field on ``AdminSettings`` can be added here and the
#: substring sweep below picks it up without a new test.
SECRETS: Final[tuple[str, ...]] = (
    DATABASE_DSN,
    REDIS_DSN,
    AUDIT_DSN,
    AUDIT_HMAC_KEY,
    PROBE_TOKEN,
    "sup3r-s3cret-pw",
    "cache-s3cret-pw",
    "owner-r0le-pw",
)

#: The camelCase names of the settings that must not appear as fields at all.
FORBIDDEN_KEYS: Final[frozenset[str]] = frozenset(
    {"databaseUrl", "redisUrl", "adminAuditDsn", "adminAuditHmacKey", "adminProbeToken"}
)


@pytest.fixture
def admin_settings() -> AdminSettings:
    """Settings whose secrets are recognisable, so the sweep below has something to catch."""
    return make_settings(
        redis_url=REDIS_DSN,
        admin_audit_dsn=AUDIT_DSN,
        admin_audit_hmac_key=AUDIT_HMAC_KEY,
        admin_probe_token=PROBE_TOKEN,
    )


@pytest.fixture
async def container(
    admin_settings: AdminSettings, fake_redis: FakeRedis, rate_limits: MemoryRateLimits
) -> AsyncIterator[AdminContainer]:
    """The standard container, with the credentialed ``database_url`` swapped in after.

    See the module docstring: the engine has to be the in-memory one, and the settings
    object has to be the one carrying a password.
    """
    async with open_container(admin_settings, fake_redis, rate_limits) as built:
        yield dataclasses.replace(
            built, settings=built.settings.model_copy(update={"database_url": DATABASE_DSN})
        )


async def signed_in(
    container: AdminContainer, client: httpx.AsyncClient, *, role: AdminRole
) -> None:
    username = f"{role.value}-account"
    await create_account(container, username=username, role=role)
    response = await sign_in(client, username=username, password=PASSWORD)
    assert response.status_code == 200


# ---------------------------------------------------------------------------
# Who may read it
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "role", [AdminRole.VIEWER, AdminRole.SUPPORT, AdminRole.ADMIN, AdminRole.OWNER]
)
async def test_every_role_in_the_matrix_row_may_read_the_configuration(
    container: AdminContainer, client: httpx.AsyncClient, role: AdminRole
) -> None:
    # Arrange — §12.2 gives CONFIG_READ as M to all four roles.
    await signed_in(container, client, role=role)

    # Act
    response = await client.get(CONFIG_PATH)

    # Assert
    assert response.status_code == 200
    assert response.json()["environment"] == "dev"


async def test_a_viewer_and_an_owner_see_the_identical_body(
    container: AdminContainer, client: httpx.AsyncClient
) -> None:
    # Arrange — the M cell has no redacted variant here: the fields that would need
    # redacting are not on the response in any form, at any role.
    await signed_in(container, client, role=AdminRole.VIEWER)
    as_viewer = await client.get(CONFIG_PATH)
    client.cookies.clear()
    await signed_in(container, client, role=AdminRole.OWNER)

    # Act
    as_owner = await client.get(CONFIG_PATH)

    # Assert
    assert as_viewer.status_code == 200
    assert as_owner.json() == as_viewer.json()


async def test_an_unauthenticated_caller_gets_401_not_the_configuration(
    client: httpx.AsyncClient,
) -> None:
    # Act
    response = await client.get(CONFIG_PATH)

    # Assert
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "UNAUTHENTICATED"


# ---------------------------------------------------------------------------
# The acceptance criterion: secrets are absent, not masked
# ---------------------------------------------------------------------------
async def test_no_credential_bearing_dsn_survives_to_the_response_body(
    container: AdminContainer, client: httpx.AsyncClient
) -> None:
    # Arrange — assert the guard has teeth before asserting it does not fire.
    assert DSN_WITH_USERINFO.search(DATABASE_DSN) is not None
    assert DSN_WITH_USERINFO.search(REDIS_DSN) is not None
    await signed_in(container, client, role=AdminRole.OWNER)

    # Act
    response = await client.get(CONFIG_PATH)

    # Assert — nothing shaped like a DSN with userinfo, and no secret as a raw substring.
    # A masked value would pass the regex and fail the substring sweep; both must hold.
    assert response.status_code == 200
    assert DSN_WITH_USERINFO.search(response.text) is None
    for secret in SECRETS:
        assert secret not in response.text


async def test_the_secret_settings_are_not_field_names_either(
    container: AdminContainer, client: httpx.AsyncClient
) -> None:
    # Arrange — absent, not masked: a ``databaseUrl: "postgres://…:***@…"`` would still
    # publish the user, the host, the port and the database name.
    await signed_in(container, client, role=AdminRole.OWNER)

    # Act
    body = (await client.get(CONFIG_PATH)).json()

    # Assert
    assert FORBIDDEN_KEYS.isdisjoint(body)


async def test_the_dsns_are_reported_as_a_host_and_a_port_instead(
    container: AdminContainer, client: httpx.AsyncClient
) -> None:
    # Arrange — an operator still has to be able to tell which database this points at.
    await signed_in(container, client, role=AdminRole.OWNER)

    # Act
    body = (await client.get(CONFIG_PATH)).json()

    # Assert
    assert body["databaseHost"] == "db.internal"
    assert body["databasePort"] == 6432
    assert body["redisHost"] == "cache.internal"
    assert body["redisPort"] == 6380


async def test_a_configured_secret_is_reported_as_a_boolean(
    container: AdminContainer, client: httpx.AsyncClient
) -> None:
    # Arrange — whether §4.5's owner-role DSN is deployed is an operational fact; the DSN
    # is a credential. The boolean carries the first and none of the second.
    await signed_in(container, client, role=AdminRole.OWNER)

    # Act
    body = (await client.get(CONFIG_PATH)).json()

    # Assert
    assert body["isAuditDsnConfigured"] is True
    assert body["isProbeTokenConfigured"] is True


def test_an_unconfigured_secret_reads_as_false_rather_than_going_missing() -> None:
    # Arrange / Act — the empty default of both fields is a supported deployment, and the
    # panel must be able to render "not deployed" rather than an absent key.
    view = to_config_view(make_settings())

    # Assert
    assert view.is_audit_dsn_configured is False
    assert view.is_probe_token_configured is False


# ---------------------------------------------------------------------------
# What it does report
# ---------------------------------------------------------------------------
async def test_the_non_secret_settings_are_reported_verbatim(
    container: AdminContainer, client: httpx.AsyncClient
) -> None:
    # Arrange — every field name is an ``AdminSettings`` attribute name, so a number on the
    # panel names the BAYRAM_ADMIN_* variable an operator would edit.
    await signed_in(container, client, role=AdminRole.ADMIN)
    settings = container.settings

    # Act
    body = (await client.get(CONFIG_PATH)).json()

    # Assert
    assert body["environment"] == settings.environment
    assert body["logLevel"] == settings.log_level
    assert body["isDebug"] is False
    assert body["isProduction"] is False
    assert body["adminEnabled"] is True
    assert body["adminConfigEnabled"] is True
    assert body["adminPublicOrigin"] == ORIGIN
    assert body["isCookieSecure"] is True
    assert body["adminSessionTtlS"] == settings.admin_session_ttl_s
    assert body["adminSessionIdleTtlS"] == settings.admin_session_idle_ttl_s
    assert body["adminStepUpGraceSeconds"] == settings.admin_step_up_grace_seconds
    assert body["adminArgon2TimeCost"] == settings.admin_argon2_time_cost
    assert body["adminArgon2MemoryKib"] == settings.admin_argon2_memory_kib
    assert body["adminArgon2Parallelism"] == settings.admin_argon2_parallelism
    assert body["adminTrustedProxyHops"] == settings.admin_trusted_proxy_hops
    assert body["adminTrustedProxyCidrs"] == []
    assert body["adminRevealRecordsPerHour"] == settings.admin_reveal_records_per_hour
    assert body["adminRevealConversationsPerDay"] == settings.admin_reveal_conversations_per_day
    # Unset in this deployment, and reported as unset. §11.2 links the similarity histogram
    # straight here, so an operator arriving from that link sees either the number the
    # marker was drawn from or the fact that this panel has not been told one.
    assert body["adminNameMatchMinSimilarity"] is None


async def test_the_mirrored_similarity_threshold_is_published_when_the_deployment_sets_it(
    fake_redis: FakeRedis, rate_limits: MemoryRateLimits
) -> None:
    """The value the histogram's marker is drawn from, visible where it can be compared.

    It is the one setting on this page the admin process does not own — the worker's
    ``name_match_min_similarity``, mirrored — so publishing it is what makes a drifted
    mirror findable instead of silently drawing the marker in the wrong place.
    """
    # Arrange
    settings = make_settings(admin_name_match_min_similarity=0.72)
    async with (
        open_container(settings, fake_redis, rate_limits) as container,
        open_client(container) as client,
    ):
        await signed_in(container, client, role=AdminRole.VIEWER)

        # Act
        body = (await client.get(CONFIG_PATH)).json()

    # Assert
    assert body["adminNameMatchMinSimilarity"] == 0.72


async def test_the_mirrored_settlement_grace_is_published_and_null_when_unset(
    fake_redis: FakeRedis, rate_limits: MemoryRateLimits
) -> None:
    """The second mirrored value, and the reason it has to be visible here.

    ``inFlightRenderCount`` on ``/users/{id}`` is counted against this grace, and the number
    it produces is the only one on that screen that explains a refusal. When the deployment
    has not published the worker's grace the panel counts against the shipped default, which
    can disagree with the gate — so an operator holding an unexplained refusal needs to be
    able to see which of the two clocks produced the count.
    """
    # Arrange
    async with (
        open_container(make_settings(), fake_redis, rate_limits) as unset_container,
        open_client(unset_container) as unset_client,
    ):
        await signed_in(unset_container, unset_client, role=AdminRole.VIEWER)
        unpublished = (await unset_client.get(CONFIG_PATH)).json()

    async with (
        open_container(
            make_settings(admin_settlement_grace_s=300), fake_redis, rate_limits
        ) as container,
        open_client(container) as client,
    ):
        await signed_in(container, client, role=AdminRole.VIEWER)

        # Act
        body = (await client.get(CONFIG_PATH)).json()

    # Assert
    assert unpublished["adminSettlementGraceS"] is None
    assert body["adminSettlementGraceS"] == 300


async def test_the_reported_configuration_is_the_one_the_process_is_bound_to(
    container: AdminContainer, client: httpx.AsyncClient
) -> None:
    # Arrange — a re-read of the environment would answer a different question. The gap
    # between the two is exactly what an operator opens this page to find.
    await signed_in(container, client, role=AdminRole.OWNER)

    # Act
    body = (await client.get(CONFIG_PATH)).json()

    # Assert
    assert body == to_config_view(container.settings).model_dump(by_alias=True, mode="json")


# ---------------------------------------------------------------------------
# The DSN parser, on the shapes that would otherwise raise
# ---------------------------------------------------------------------------
def test_a_dsn_with_no_authority_reports_neither_host_nor_port() -> None:
    # Arrange / Act — the suite's own database URL. "Nowhere" is the honest answer.
    endpoint = endpoint_of("sqlite+aiosqlite:///:memory:")

    # Assert
    assert endpoint.host is None
    assert endpoint.port is None


def test_a_non_numeric_port_is_omitted_rather_than_raising() -> None:
    # Arrange / Act — ``urlsplit(...).port`` raises ValueError on this, and a route handler
    # is the one place that must not grow a try/except to survive a config value.
    endpoint = endpoint_of("postgresql+asyncpg://user:pw@db.internal:not-a-port/hbd")

    # Assert
    assert endpoint.host == "db.internal"
    assert endpoint.port is None


def test_an_ipv6_literal_keeps_its_own_colons_out_of_the_port() -> None:
    # Arrange / Act — the reason the port is taken from the last colon of the authority
    # rather than the first.
    endpoint = endpoint_of("redis://:pw@[2001:db8::1]:6379/0")

    # Assert
    assert endpoint.host == "2001:db8::1"
    assert endpoint.port == 6379


def test_a_password_containing_a_colon_does_not_become_the_port() -> None:
    # Arrange / Act — userinfo is dropped before the port is read, so a colon inside the
    # password cannot be mistaken for the separator.
    endpoint = endpoint_of("postgresql://user:pa:ss@db.internal/hbd")

    # Assert
    assert endpoint.host == "db.internal"
    assert endpoint.port is None
