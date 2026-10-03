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
import sqlalchemy as sa

from bayram.admin.container import AdminContainer
from bayram.admin.routers.config import (
    CONFIG_CHECKOUT_RAILS_PATH,
    CONFIG_MUSIC_PROVIDER_PATH,
    CONFIG_PATH,
    CONFIG_TEACHERS_DAY_PATH,
)
from bayram.admin.schemas.config_view import endpoint_of, to_config_view
from bayram.admin.settings import AdminSettings
from bayram.checkout_rails import WIRED_RAILS_KEY, rail_switch_key
from bayram.db.enums import AdminRole, AuditAction, AuditReasonCode
from bayram.db.models.admin_audit import AdminAuditRow
from bayram.providers.music.switch import read_music_provider
from bayram.teachers_day import read_teachers_day_enabled
from tests.test_admin.conftest import (
    ORIGIN,
    PASSWORD,
    FakeRedis,
    MemoryRateLimits,
    create_account,
    csrf_headers,
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


# ---------------------------------------------------------------------------
# Music provider configuration and runtime switching
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "role", [AdminRole.VIEWER, AdminRole.SUPPORT, AdminRole.ADMIN, AdminRole.OWNER]
)
async def test_every_role_in_the_matrix_row_may_read_music_provider_config(
    container: AdminContainer, client: httpx.AsyncClient, role: AdminRole
) -> None:
    await signed_in(container, client, role=role)

    response = await client.get(CONFIG_MUSIC_PROVIDER_PATH)

    assert response.status_code == 200
    body = response.json()
    assert body["activeProvider"] == "elevenlabs"
    assert body["defaultProvider"] == "elevenlabs"
    assert sorted(body["availableProviders"]) == ["elevenlabs", "gemini"]


async def test_unauthenticated_caller_cannot_read_or_write_music_provider(
    client: httpx.AsyncClient,
) -> None:
    get_res = await client.get(CONFIG_MUSIC_PROVIDER_PATH)
    assert get_res.status_code == 401
    assert get_res.json()["error"]["code"] == "UNAUTHENTICATED"

    post_res = await client.post(
        CONFIG_MUSIC_PROVIDER_PATH,
        json={"provider": "gemini", "reasonCode": AuditReasonCode.ROUTINE_OPS.value},
    )
    assert post_res.status_code == 401
    assert post_res.json()["error"]["code"] == "UNAUTHENTICATED"


@pytest.mark.parametrize("role", [AdminRole.VIEWER, AdminRole.SUPPORT, AdminRole.ADMIN])
async def test_non_owner_roles_cannot_set_music_provider(
    container: AdminContainer, client: httpx.AsyncClient, role: AdminRole
) -> None:
    await signed_in(container, client, role=role)

    response = await client.post(
        CONFIG_MUSIC_PROVIDER_PATH,
        json={
            "provider": "gemini",
            "reasonCode": AuditReasonCode.ROUTINE_OPS.value,
            "reasonText": "switch attempt",
        },
        headers=csrf_headers(client) | {"Origin": ORIGIN},
    )

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "FORBIDDEN"


async def test_owner_can_switch_music_provider_and_audits_commit(
    container: AdminContainer, client: httpx.AsyncClient
) -> None:
    await signed_in(container, client, role=AdminRole.OWNER)

    # Initial state
    assert await read_music_provider(container.redis) == "elevenlabs"

    # Switch to gemini
    response = await client.post(
        CONFIG_MUSIC_PROVIDER_PATH,
        json={
            "provider": "gemini",
            "reasonCode": AuditReasonCode.ROUTINE_OPS.value,
            "reasonText": "Switching to Gemini Lyria for music gen",
        },
        headers=csrf_headers(client) | {"Origin": ORIGIN},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["activeProvider"] == "gemini"
    assert body["defaultProvider"] == "elevenlabs"
    assert sorted(body["availableProviders"]) == ["elevenlabs", "gemini"]

    # Verify Redis updated
    assert await read_music_provider(container.redis) == "gemini"

    # Verify GET returns updated active provider
    get_res = await client.get(CONFIG_MUSIC_PROVIDER_PATH)
    assert get_res.status_code == 200
    assert get_res.json()["activeProvider"] == "gemini"

    # Verify audit log row
    async with container.session_factory.begin() as db:
        rows = list(
            (
                await db.execute(
                    sa.select(AdminAuditRow).where(
                        AdminAuditRow.action == AuditAction.CONFIG_COMMIT
                    )
                )
            )
            .scalars()
            .all()
        )
    assert len(rows) == 1
    row = rows[0]
    assert row.subject_type == "config"
    assert row.subject_id == "music_provider"
    assert row.reason_code == AuditReasonCode.ROUTINE_OPS.value
    assert row.reason_text == "Switching to Gemini Lyria for music gen"
    assert row.actor_username == "owner-account"


async def test_set_music_provider_refuses_invalid_provider(
    container: AdminContainer, client: httpx.AsyncClient
) -> None:
    await signed_in(container, client, role=AdminRole.OWNER)

    response = await client.post(
        CONFIG_MUSIC_PROVIDER_PATH,
        json={
            "provider": "suno_unknown",
            "reasonCode": AuditReasonCode.ROUTINE_OPS.value,
        },
        headers=csrf_headers(client) | {"Origin": ORIGIN},
    )

    assert response.status_code == 422


async def test_set_music_provider_refuses_missing_reason_code(
    container: AdminContainer, client: httpx.AsyncClient
) -> None:
    await signed_in(container, client, role=AdminRole.OWNER)

    response = await client.post(
        CONFIG_MUSIC_PROVIDER_PATH,
        json={"provider": "gemini"},
        headers=csrf_headers(client) | {"Origin": ORIGIN},
    )

    assert response.status_code == 422


@pytest.mark.parametrize("role", list(AdminRole))
async def test_every_role_in_the_matrix_row_may_read_teachers_day_config(
    container: AdminContainer, client: httpx.AsyncClient, role: AdminRole
) -> None:
    await signed_in(container, client, role=role)

    response = await client.get(CONFIG_TEACHERS_DAY_PATH)

    assert response.status_code == 200
    body = response.json()
    assert body["enabled"] is False
    assert body["discountPercent"] == 30


async def test_unauthenticated_caller_cannot_read_or_write_teachers_day(
    client: httpx.AsyncClient,
) -> None:
    get_res = await client.get(CONFIG_TEACHERS_DAY_PATH)
    assert get_res.status_code == 401
    assert get_res.json()["error"]["code"] == "UNAUTHENTICATED"

    post_res = await client.post(
        CONFIG_TEACHERS_DAY_PATH,
        json={"enabled": True, "reasonCode": AuditReasonCode.ROUTINE_OPS.value},
    )
    assert post_res.status_code == 401
    assert post_res.json()["error"]["code"] == "UNAUTHENTICATED"


@pytest.mark.parametrize("role", [AdminRole.VIEWER, AdminRole.SUPPORT, AdminRole.ADMIN])
async def test_non_owner_roles_cannot_set_teachers_day(
    container: AdminContainer, client: httpx.AsyncClient, role: AdminRole
) -> None:
    await signed_in(container, client, role=role)

    response = await client.post(
        CONFIG_TEACHERS_DAY_PATH,
        json={
            "enabled": True,
            "reasonCode": AuditReasonCode.ROUTINE_OPS.value,
            "reasonText": "switch attempt",
        },
        headers=csrf_headers(client) | {"Origin": ORIGIN},
    )

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "FORBIDDEN"


async def test_owner_can_switch_teachers_day_and_audits_commit(
    container: AdminContainer, client: httpx.AsyncClient
) -> None:
    await signed_in(container, client, role=AdminRole.OWNER)

    # Initial state
    assert await read_teachers_day_enabled(container.redis) is False

    # Switch to True
    response = await client.post(
        CONFIG_TEACHERS_DAY_PATH,
        json={
            "enabled": True,
            "reasonCode": AuditReasonCode.ROUTINE_OPS.value,
            "reasonText": "Enabling Teachers Day promo",
        },
        headers=csrf_headers(client) | {"Origin": ORIGIN},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["enabled"] is True
    assert body["discountPercent"] == 30

    # Redis check
    assert await read_teachers_day_enabled(container.redis) is True

    # Audit log check
    async with container.session_factory() as session:
        rows = (
            (
                await session.execute(
                    sa.select(AdminAuditRow).where(
                        AdminAuditRow.action == AuditAction.CONFIG_COMMIT
                    )
                )
            )
            .scalars()
            .all()
        )
    assert len(rows) == 1
    row = rows[0]
    assert row.subject_type == "config"
    assert row.subject_id == "teachers_day"
    assert row.reason_code == AuditReasonCode.ROUTINE_OPS.value
    assert row.reason_text == "Enabling Teachers Day promo"
    assert row.actor_username == "owner-account"


async def test_set_teachers_day_refuses_missing_reason_code(
    container: AdminContainer, client: httpx.AsyncClient
) -> None:
    await signed_in(container, client, role=AdminRole.OWNER)

    response = await client.post(
        CONFIG_TEACHERS_DAY_PATH,
        json={"enabled": True},
        headers=csrf_headers(client) | {"Origin": ORIGIN},
    )

    assert response.status_code == 422


# ---------------------------------------------------------------------------
# The owner's per-rail checkout switch (DECISIONS.md D28)
# ---------------------------------------------------------------------------
_RAIL_BODY: Final[dict[str, object]] = {
    "rail": "checkoutuz",
    "enabled": False,
    "reasonCode": AuditReasonCode.ROUTINE_OPS.value,
    "reasonText": "pausing checkout.uz sales",
}


async def _rail_audit_rows(container: AdminContainer) -> list[AdminAuditRow]:
    async with container.session_factory() as session:
        return list(
            (
                await session.execute(
                    sa.select(AdminAuditRow).where(
                        AdminAuditRow.action == AuditAction.CONFIG_COMMIT
                    )
                )
            )
            .scalars()
            .all()
        )


@pytest.mark.parametrize("role", list(AdminRole))
async def test_every_role_may_read_the_checkout_rails_and_unset_reads_as_on_and_unknown(
    container: AdminContainer, client: httpx.AsyncClient, role: AdminRole
) -> None:
    # Arrange — nothing written: no switch keys, and the bot has not published its rails.
    await signed_in(container, client, role=role)

    # Act
    response = await client.get(CONFIG_CHECKOUT_RAILS_PATH)

    # Assert — a missing switch is ON (fail-open), and an unpublished list is unknown, not
    # "nothing is wired".
    assert response.status_code == 200
    assert response.json() == {
        "rails": [
            {"name": "rhmt", "enabled": True, "wired": None},
            {"name": "payme", "enabled": True, "wired": None},
            {"name": "checkoutuz", "enabled": True, "wired": None},
        ],
        "wiredKnown": False,
    }


async def test_the_checkout_rails_view_reports_the_published_wired_list_and_the_switches(
    container: AdminContainer, client: httpx.AsyncClient, fake_redis: FakeRedis
) -> None:
    # Arrange
    await signed_in(container, client, role=AdminRole.VIEWER)
    fake_redis.values[WIRED_RAILS_KEY] = "payme,checkoutuz"
    fake_redis.values[rail_switch_key("payme")] = "0"

    # Act
    response = await client.get(CONFIG_CHECKOUT_RAILS_PATH)

    # Assert
    assert response.status_code == 200
    assert response.json() == {
        "rails": [
            {"name": "rhmt", "enabled": True, "wired": False},
            {"name": "payme", "enabled": False, "wired": True},
            {"name": "checkoutuz", "enabled": True, "wired": True},
        ],
        "wiredKnown": True,
    }


async def test_a_stub_deployment_publishes_an_empty_list_which_is_known_and_wires_nothing(
    container: AdminContainer, client: httpx.AsyncClient, fake_redis: FakeRedis
) -> None:
    await signed_in(container, client, role=AdminRole.OWNER)
    fake_redis.values[WIRED_RAILS_KEY] = ""

    body = (await client.get(CONFIG_CHECKOUT_RAILS_PATH)).json()

    assert body["wiredKnown"] is True
    assert [rail["wired"] for rail in body["rails"]] == [False, False, False]


async def test_unauthenticated_caller_cannot_read_or_write_checkout_rails(
    client: httpx.AsyncClient,
) -> None:
    get_res = await client.get(CONFIG_CHECKOUT_RAILS_PATH)
    assert get_res.status_code == 401
    assert get_res.json()["error"]["code"] == "UNAUTHENTICATED"

    post_res = await client.post(CONFIG_CHECKOUT_RAILS_PATH, json=_RAIL_BODY)
    assert post_res.status_code == 401
    assert post_res.json()["error"]["code"] == "UNAUTHENTICATED"


@pytest.mark.parametrize("role", [AdminRole.VIEWER, AdminRole.SUPPORT, AdminRole.ADMIN])
async def test_non_owner_roles_cannot_switch_a_checkout_rail(
    container: AdminContainer,
    client: httpx.AsyncClient,
    fake_redis: FakeRedis,
    role: AdminRole,
) -> None:
    await signed_in(container, client, role=role)

    response = await client.post(
        CONFIG_CHECKOUT_RAILS_PATH,
        json=_RAIL_BODY,
        headers=csrf_headers(client) | {"Origin": ORIGIN},
    )

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "FORBIDDEN"
    assert rail_switch_key("checkoutuz") not in fake_redis.values


async def test_owner_can_switch_a_checkout_rail_off_and_on_and_each_commit_is_audited(
    container: AdminContainer, client: httpx.AsyncClient, fake_redis: FakeRedis
) -> None:
    # Arrange
    await signed_in(container, client, role=AdminRole.OWNER)

    # Act — off
    response = await client.post(
        CONFIG_CHECKOUT_RAILS_PATH,
        json=_RAIL_BODY,
        headers=csrf_headers(client) | {"Origin": ORIGIN},
    )

    # Assert — an explicit "0", never a deleted key (a missing key reads as ON).
    assert response.status_code == 200
    assert fake_redis.values[rail_switch_key("checkoutuz")] == "0"
    rails = {rail["name"]: rail["enabled"] for rail in response.json()["rails"]}
    assert rails == {"rhmt": True, "payme": True, "checkoutuz": False}
    rows = await _rail_audit_rows(container)
    assert len(rows) == 1
    row = rows[0]
    assert row.subject_type == "config"
    assert row.subject_id == "checkout_rail:checkoutuz:off"
    assert row.ip is not None
    assert row.reason_code == AuditReasonCode.ROUTINE_OPS.value
    assert row.reason_text == "pausing checkout.uz sales"
    assert row.actor_username == "owner-account"

    # Act — back on; the GET agrees with the POST's answer.
    response = await client.post(
        CONFIG_CHECKOUT_RAILS_PATH,
        json=_RAIL_BODY | {"enabled": True},
        headers=csrf_headers(client) | {"Origin": ORIGIN},
    )
    assert response.status_code == 200
    assert fake_redis.values[rail_switch_key("checkoutuz")] == "1"
    assert (await client.get(CONFIG_CHECKOUT_RAILS_PATH)).json() == response.json()
    # Off and on are distinguishable in the audit log alone — the Redis value is overwritten.
    assert sorted(str(row.subject_id) for row in await _rail_audit_rows(container)) == [
        "checkout_rail:checkoutuz:off",
        "checkout_rail:checkoutuz:on",
    ]


async def test_the_rail_name_is_normalised_before_it_is_written_or_audited(
    container: AdminContainer, client: httpx.AsyncClient, fake_redis: FakeRedis
) -> None:
    await signed_in(container, client, role=AdminRole.OWNER)

    response = await client.post(
        CONFIG_CHECKOUT_RAILS_PATH,
        json=_RAIL_BODY | {"rail": "  Payme "},
        headers=csrf_headers(client) | {"Origin": ORIGIN},
    )

    assert response.status_code == 200
    assert fake_redis.values[rail_switch_key("payme")] == "0"
    assert [row.subject_id for row in await _rail_audit_rows(container)] == [
        "checkout_rail:payme:off"
    ]


@pytest.mark.parametrize(
    "body",
    [
        _RAIL_BODY | {"rail": "stub"},
        _RAIL_BODY | {"rail": "click"},
        {key: value for key, value in _RAIL_BODY.items() if key != "reasonCode"},
        {key: value for key, value in _RAIL_BODY.items() if key != "enabled"},
    ],
    ids=["stub-is-not-switchable", "unknown-rail", "missing-reason-code", "missing-enabled"],
)
async def test_set_checkout_rail_refuses_a_malformed_body_and_writes_nothing(
    container: AdminContainer,
    client: httpx.AsyncClient,
    fake_redis: FakeRedis,
    body: dict[str, object],
) -> None:
    await signed_in(container, client, role=AdminRole.OWNER)

    response = await client.post(
        CONFIG_CHECKOUT_RAILS_PATH,
        json=body,
        headers=csrf_headers(client) | {"Origin": ORIGIN},
    )

    assert response.status_code == 422
    assert not any(key.startswith(rail_switch_key("")) for key in fake_redis.values)
    assert await _rail_audit_rows(container) == []


async def test_a_switch_that_cannot_be_written_is_a_503_and_is_not_audited(
    container: AdminContainer, client: httpx.AsyncClient, fake_redis: FakeRedis
) -> None:
    # Arrange — the owner must never be told (by the panel or the log) a rail is shut when
    # the write did not land.
    await signed_in(container, client, role=AdminRole.OWNER)
    fake_redis.is_down = True

    # Act
    response = await client.post(
        CONFIG_CHECKOUT_RAILS_PATH,
        json=_RAIL_BODY,
        headers=csrf_headers(client) | {"Origin": ORIGIN},
    )

    # Assert
    fake_redis.is_down = False
    assert response.status_code == 503
    assert rail_switch_key("checkoutuz") not in fake_redis.values
    assert await _rail_audit_rows(container) == []


async def test_an_unreachable_redis_reads_as_every_rail_on_and_wiring_unknown(
    container: AdminContainer, client: httpx.AsyncClient, fake_redis: FakeRedis
) -> None:
    await signed_in(container, client, role=AdminRole.VIEWER)
    fake_redis.is_down = True

    response = await client.get(CONFIG_CHECKOUT_RAILS_PATH)

    fake_redis.is_down = False
    assert response.status_code == 200
    body = response.json()
    assert body["wiredKnown"] is False
    assert all(rail["enabled"] is True and rail["wired"] is None for rail in body["rails"])
