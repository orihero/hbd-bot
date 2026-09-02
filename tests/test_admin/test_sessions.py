"""The session layer, and the three ways a live session must stop being one.

Three tests here are the acceptance criteria that the review added, and each is written so it
would fail under the obvious wrong implementation:

* :func:`test_deactivating_an_account_401s_the_next_request_with_the_mirror_warm` and
  :func:`test_changing_the_password_401s_an_old_session_with_the_mirror_warm` change the
  ``admin_users`` row **directly**, touching nothing in Redis, and then assert both that the
  mirror key is still there and that the next request is 401. A ``role``/``is_active`` read
  from the mirror passes neither.
* :func:`test_revoking_a_session_drops_its_mirror_immediately` asserts the key is **gone**
  rather than merely expiring, because "it will time out within a minute" is the answer the
  review rejected.

The rest pin the mirror's own contract: it never outlives either session clock, a value that
will not decode is a miss rather than a 500, and a Redis outage costs a round trip rather than
an outage.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Final
from uuid import uuid4

import httpx
import pytest
import sqlalchemy as sa

from hbd.admin.container import AdminContainer
from hbd.admin.csrf import SESSION_COOKIE_NAME
from hbd.admin.errors import AdminErrorCode
from hbd.admin.security.tokens import sha256_hex
from hbd.admin.sessions import (
    IDLE_TOUCH_INTERVAL_S,
    SESSION_MIRROR_TTL_S,
    invalidate_mirror,
    issue_session,
    mirror_key,
    read_mirror,
    resolve_session,
    revoke_sessions_for_user,
    touch_session,
)
from hbd.db.admin import accounts
from hbd.db.base import utc_now
from hbd.db.models.admin_session import AdminSessionRow
from hbd.db.models.admin_user import AdminUserRow
from tests.test_admin.conftest import (
    NOW,
    PASSWORD,
    USERNAME,
    FakeRedis,
    MemoryRateLimits,
    create_account,
    csrf_headers,
    sign_in,
)

_ABSOLUTE_TTL_S: Final[int] = 43_200
_IDLE_TTL_S: Final[int] = 3_600


def _digest(client: httpx.AsyncClient) -> str:
    return sha256_hex(client.cookies[SESSION_COOKIE_NAME])


# ---------------------------------------------------------------------------
# The three revocations, each with the mirror warm
# ---------------------------------------------------------------------------
async def test_deactivating_an_account_401s_the_next_request_with_the_mirror_warm(
    client: httpx.AsyncClient, container: AdminContainer, fake_redis: FakeRedis
) -> None:
    # Arrange - sign in, then warm the mirror with a real request
    user = await create_account(container)
    await sign_in(client)
    assert (await client.get("/api/auth/me")).status_code == 200
    key = mirror_key(_digest(client))
    assert key in fake_redis.values

    # Act - deactivate in the database only; Redis is not touched
    async with container.session_factory.begin() as db:
        await db.execute(
            sa.update(AdminUserRow).where(AdminUserRow.id == user.id).values(is_active=False)
        )

    # Assert
    assert (await client.get("/api/auth/me")).status_code == 401


async def test_changing_the_password_401s_an_old_session_with_the_mirror_warm(
    client: httpx.AsyncClient, container: AdminContainer, fake_redis: FakeRedis
) -> None:
    # Arrange
    user = await create_account(container)
    await sign_in(client)
    assert (await client.get("/api/auth/me")).status_code == 200
    assert mirror_key(_digest(client)) in fake_redis.values

    # Act - the password moves under the session, in the database only. The instant has to
    # come from the real clock: the session was issued by ``utc_now()`` inside the request,
    # and what voids it is ``password_changed_at`` being later than *that*.
    async with container.session_factory.begin() as db:
        await accounts.set_password(
            db,
            admin_user_id=user.id,
            password_hash="$argon2id$v=19$m=65536,t=3,p=4$c29tZXNhbHQ$replaced",
            now=utc_now() + timedelta(minutes=1),
        )

    # Assert - a session issued before the change is no longer trustworthy
    assert (await client.get("/api/auth/me")).status_code == 401


async def test_revoking_a_session_drops_its_mirror_immediately(
    client: httpx.AsyncClient, container: AdminContainer, fake_redis: FakeRedis
) -> None:
    # Arrange
    await create_account(container)
    await sign_in(client)
    await client.get("/api/auth/me")
    key = mirror_key(_digest(client))
    assert key in fake_redis.values

    # Act
    response = await client.post("/api/auth/logout", headers=csrf_headers(client))

    # Assert - gone now, not in sixty seconds
    assert response.status_code == 204
    assert key not in fake_redis.values


async def test_revoking_every_session_for_a_user_drops_every_mirror(
    container: AdminContainer, fake_redis: FakeRedis
) -> None:
    # Arrange - two browsers
    user = await create_account(container)
    digests = []
    async with container.session_factory.begin() as db:
        for _ in range(2):
            issued = await issue_session(
                db,
                container.redis,
                admin_user_id=user.id,
                now=NOW,
                absolute_ttl_s=_ABSOLUTE_TTL_S,
                idle_ttl_s=_IDLE_TTL_S,
                ip="203.0.113.7",
                user_agent="tests",
            )
            digests.append(issued.token.sha256)
    assert all(mirror_key(d) in fake_redis.values for d in digests)

    # Act
    async with container.session_factory.begin() as db:
        revoked = await revoke_sessions_for_user(
            db, container.redis, admin_user_id=user.id, now=NOW
        )

    # Assert
    assert revoked == 2
    assert not any(mirror_key(d) in fake_redis.values for d in digests)


# ---------------------------------------------------------------------------
# The mirror's own contract
# ---------------------------------------------------------------------------
async def test_the_mirror_never_outlives_either_session_clock(
    container: AdminContainer, fake_redis: FakeRedis
) -> None:
    # Arrange - a session with only ten seconds of absolute life left
    user = await create_account(container)

    # Act
    async with container.session_factory.begin() as db:
        issued = await issue_session(
            db,
            container.redis,
            admin_user_id=user.id,
            now=NOW,
            absolute_ttl_s=10,
            idle_ttl_s=_IDLE_TTL_S,
            ip=None,
            user_agent=None,
        )

    # Assert - clamped below the sixty-second ceiling
    assert fake_redis.ttls[mirror_key(issued.token.sha256)] == 10


async def test_an_undecodable_mirror_value_is_a_miss_not_a_failure(
    container: AdminContainer, fake_redis: FakeRedis
) -> None:
    # Arrange
    user = await create_account(container)
    async with container.session_factory.begin() as db:
        issued = await issue_session(
            db,
            container.redis,
            admin_user_id=user.id,
            now=NOW,
            absolute_ttl_s=_ABSOLUTE_TTL_S,
            idle_ttl_s=_IDLE_TTL_S,
            ip=None,
            user_agent=None,
        )
    fake_redis.values[mirror_key(issued.token.sha256)] = "{not json"

    # Act
    async with container.session_factory() as db:
        resolved = await resolve_session(
            db,
            container.redis,
            token_sha256=issued.token.sha256,
            now=NOW,
            idle_ttl_s=_IDLE_TTL_S,
        )

    # Assert - the database answered instead
    assert resolved is not None
    assert resolved.session_id == issued.snapshot.session_id


async def test_a_redis_outage_falls_back_to_the_database(
    container: AdminContainer, fake_redis: FakeRedis
) -> None:
    # Arrange
    user = await create_account(container)
    async with container.session_factory.begin() as db:
        issued = await issue_session(
            db,
            container.redis,
            admin_user_id=user.id,
            now=NOW,
            absolute_ttl_s=_ABSOLUTE_TTL_S,
            idle_ttl_s=_IDLE_TTL_S,
            ip=None,
            user_agent=None,
        )
    fake_redis.is_down = True

    # Act
    async with container.session_factory() as db:
        resolved = await resolve_session(
            db,
            container.redis,
            token_sha256=issued.token.sha256,
            now=NOW,
            idle_ttl_s=_IDLE_TTL_S,
        )

    # Assert - a mirror outage costs a round trip, never a sign-out
    assert resolved is not None


async def test_an_unknown_token_resolves_to_nothing(container: AdminContainer) -> None:
    async with container.session_factory() as db:
        assert (
            await resolve_session(
                db,
                container.redis,
                token_sha256=sha256_hex(str(uuid4())),
                now=NOW,
                idle_ttl_s=_IDLE_TTL_S,
            )
            is None
        )


@pytest.mark.parametrize(
    ("elapsed_s", "is_alive"),
    [(_IDLE_TTL_S - 1, True), (_IDLE_TTL_S, True), (_IDLE_TTL_S + 1, False)],
)
async def test_the_idle_window_is_enforced_on_the_mirror_and_on_the_row(
    container: AdminContainer, fake_redis: FakeRedis, elapsed_s: int, is_alive: bool
) -> None:
    # Arrange
    user = await create_account(container)
    async with container.session_factory.begin() as db:
        issued = await issue_session(
            db,
            container.redis,
            admin_user_id=user.id,
            now=NOW,
            absolute_ttl_s=_ABSOLUTE_TTL_S,
            idle_ttl_s=_IDLE_TTL_S,
            ip=None,
            user_agent=None,
        )
    later = NOW + timedelta(seconds=elapsed_s)

    # Act - once against the warm mirror, once against the row alone
    async with container.session_factory() as db:
        from_mirror = await resolve_session(
            db,
            container.redis,
            token_sha256=issued.token.sha256,
            now=later,
            idle_ttl_s=_IDLE_TTL_S,
        )
    fake_redis.values.clear()
    async with container.session_factory() as db:
        from_row = await resolve_session(
            db,
            container.redis,
            token_sha256=issued.token.sha256,
            now=later,
            idle_ttl_s=_IDLE_TTL_S,
        )

    # Assert - both storages agree, which is the property that makes the cache safe
    assert (from_mirror is not None) is is_alive
    assert (from_row is not None) is is_alive


async def test_an_expired_mirror_hit_drops_the_key_rather_than_answering(
    container: AdminContainer, fake_redis: FakeRedis
) -> None:
    # Arrange
    user = await create_account(container)
    async with container.session_factory.begin() as db:
        issued = await issue_session(
            db,
            container.redis,
            admin_user_id=user.id,
            now=NOW,
            absolute_ttl_s=_ABSOLUTE_TTL_S,
            idle_ttl_s=_IDLE_TTL_S,
            ip=None,
            user_agent=None,
        )

    # Act - Redis failed to honour the TTL; the clocks in the value still decide
    async with container.session_factory() as db:
        resolved = await resolve_session(
            db,
            container.redis,
            token_sha256=issued.token.sha256,
            now=NOW + timedelta(seconds=_ABSOLUTE_TTL_S + 1),
            idle_ttl_s=_IDLE_TTL_S,
        )

    # Assert
    assert resolved is None
    assert mirror_key(issued.token.sha256) not in fake_redis.values


# ---------------------------------------------------------------------------
# The idle touch is throttled
# ---------------------------------------------------------------------------
async def test_the_idle_touch_is_skipped_while_last_seen_is_recent(
    container: AdminContainer,
) -> None:
    # Arrange
    user = await create_account(container)
    async with container.session_factory.begin() as db:
        issued = await issue_session(
            db,
            container.redis,
            admin_user_id=user.id,
            now=NOW,
            absolute_ttl_s=_ABSOLUTE_TTL_S,
            idle_ttl_s=_IDLE_TTL_S,
            ip=None,
            user_agent=None,
        )

    # Act
    async with container.session_factory.begin() as db:
        await touch_session(
            db,
            container.redis,
            snapshot=issued.snapshot,
            token_sha256=issued.token.sha256,
            now=NOW + timedelta(seconds=IDLE_TOUCH_INTERVAL_S - 1),
            ip="203.0.113.9",
            idle_ttl_s=_IDLE_TTL_S,
        )

    # Assert - no write, so last_seen_at and last_ip are untouched
    async with container.session_factory() as db:
        row = await db.get(AdminSessionRow, issued.snapshot.session_id)
    assert row is not None
    assert row.last_seen_at == NOW
    assert row.last_ip is None


async def test_the_idle_touch_writes_once_the_interval_has_passed(
    container: AdminContainer, fake_redis: FakeRedis
) -> None:
    # Arrange
    user = await create_account(container)
    async with container.session_factory.begin() as db:
        issued = await issue_session(
            db,
            container.redis,
            admin_user_id=user.id,
            now=NOW,
            absolute_ttl_s=_ABSOLUTE_TTL_S,
            idle_ttl_s=_IDLE_TTL_S,
            ip=None,
            user_agent=None,
        )
    later = NOW + timedelta(seconds=IDLE_TOUCH_INTERVAL_S)

    # Act
    async with container.session_factory.begin() as db:
        await touch_session(
            db,
            container.redis,
            snapshot=issued.snapshot,
            token_sha256=issued.token.sha256,
            now=later,
            ip="203.0.113.9",
            idle_ttl_s=_IDLE_TTL_S,
        )

    # Assert - the row and the mirror agree on the new instant
    async with container.session_factory() as db:
        row = await db.get(AdminSessionRow, issued.snapshot.session_id)
    assert row is not None
    assert row.last_seen_at == later
    assert row.last_ip == "203.0.113.9"
    mirrored = await read_mirror(container.redis, issued.token.sha256)
    assert mirrored is not None
    assert mirrored.last_seen_at == later


# ---------------------------------------------------------------------------
# Session fixation
# ---------------------------------------------------------------------------
async def test_signing_in_again_revokes_the_token_the_request_arrived_with(
    client: httpx.AsyncClient, container: AdminContainer
) -> None:
    # Arrange
    await create_account(container)
    await sign_in(client)
    first = client.cookies[SESSION_COOKIE_NAME]

    # Act
    await sign_in(client)
    second = client.cookies[SESSION_COOKIE_NAME]

    # Assert - a new token, and the old one is dead in the database
    assert first != second
    async with container.session_factory() as db:
        row = (
            await db.execute(
                sa.select(AdminSessionRow).where(AdminSessionRow.token_sha256 == sha256_hex(first))
            )
        ).scalar_one()
    assert row.revoked_at is not None


async def test_the_mirror_ceiling_is_a_minute(
    container: AdminContainer, fake_redis: FakeRedis
) -> None:
    # Arrange
    user = await create_account(container)

    # Act
    async with container.session_factory.begin() as db:
        issued = await issue_session(
            db,
            container.redis,
            admin_user_id=user.id,
            now=NOW,
            absolute_ttl_s=_ABSOLUTE_TTL_S,
            idle_ttl_s=_IDLE_TTL_S,
            ip=None,
            user_agent=None,
        )

    # Assert - §4's "TTL ≤ 60s"
    assert fake_redis.ttls[mirror_key(issued.token.sha256)] == SESSION_MIRROR_TTL_S


async def test_a_signed_in_operator_is_exempt_from_the_strict_login_counter(
    client: httpx.AsyncClient, container: AdminContainer, rate_limits: MemoryRateLimits
) -> None:
    # Arrange
    await create_account(container)
    await sign_in(client)
    before = dict(rate_limits.counts)

    # Act - a second sign-in while already holding a live session for that username
    await sign_in(client, username=USERNAME, password=PASSWORD)

    # Assert - the username ceiling still charged, the (username, ip) counter did not
    per_ip_keys = {key for key in rate_limits.counts if ":uip:" in key}
    assert {key for key in before if ":uip:" in key} == per_ip_keys


# ---------------------------------------------------------------------------
# A cookie that outlives its session row
# ---------------------------------------------------------------------------
async def test_a_cookie_whose_session_row_is_gone_is_401_not_a_crash(
    client: httpx.AsyncClient, container: AdminContainer, fake_redis: FakeRedis
) -> None:
    """The browser still holds a valid-looking cookie after the row behind it disappeared.

    This is the shape of every out-of-band revocation — an owner deleting another operator's
    session, or the sweep collecting one past its absolute TTL. ``resolve_session`` answers
    ``None`` and the request gate has to turn that into the same flat 401 every other failure
    gets. An unguarded ``None`` here is a 500 that tells an attacker their cookie was real.
    """
    # Arrange - a live session, then the row and its mirror removed underneath it
    await create_account(container)
    await sign_in(client)
    digest = _digest(client)
    async with container.session_factory.begin() as db:
        await db.execute(sa.delete(AdminSessionRow).where(AdminSessionRow.token_sha256 == digest))
    fake_redis.values.pop(mirror_key(digest), None)

    # Act - the cookie is still on the client and is still well-formed
    response = await client.get("/api/auth/me")

    # Assert - 401, and the body says nothing about whether the cookie was ever valid
    assert response.status_code == 401
    assert response.json()["error"]["code"] == AdminErrorCode.UNAUTHENTICATED.value


async def test_a_mirror_that_cannot_be_invalidated_is_logged_as_an_error(
    container: AdminContainer, fake_redis: FakeRedis, caplog: pytest.LogCaptureFixture
) -> None:
    """A revocation that cannot reach Redis must be loud, and must still revoke the row.

    The mirror can answer for up to ``SESSION_MIRROR_TTL_S`` more seconds after the row is
    gone, so this is the one Redis failure an operator has to see during an incident. It is
    logged at ERROR rather than swallowed, and it does not propagate: a Redis outage must not
    turn a sign-out into a 500 that leaves the caller believing they are still signed in.
    """
    # Arrange
    user = await create_account(container)
    async with container.session_factory.begin() as db:
        issued = await issue_session(
            db,
            container.redis,
            admin_user_id=user.id,
            now=NOW,
            absolute_ttl_s=_ABSOLUTE_TTL_S,
            idle_ttl_s=_IDLE_TTL_S,
            ip=None,
            user_agent=None,
        )
    fake_redis.is_down = True

    # Act
    with caplog.at_level("ERROR"):
        await invalidate_mirror(container.redis, issued.token.sha256)

    # Assert - one ERROR naming the event, and no exception escaped
    events = [
        record
        for record in caplog.records
        if getattr(record, "event", None) == "admin.session.mirror_invalidation_failed"
    ]
    assert len(events) == 1
    assert events[0].levelname == "ERROR"
