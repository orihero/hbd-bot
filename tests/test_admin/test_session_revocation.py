"""Revoke-then-request answers 401 **with the Redis mirror still warm** (§12.1 T2, §12.5).

That is a Slice 1a acceptance criterion, and until this module existed nothing asserted it.
The two ways it can be violated are covered separately, because they fail independently:

* :func:`test_a_session_revoked_directly_in_the_database_401s_with_the_mirror_warm` writes
  ``revoked_at`` with a bare ``UPDATE``, touching neither ``sessions.revoke_session`` nor
  Redis — the shape of a session sweep, of ``psql``, and of Slice 1b's "revoke another
  admin's sessions". The mirror is asserted to be **still there** before the request, so the
  test is about the database being authoritative rather than about a lucky cache eviction.
* :func:`test_resolve_session_refuses_a_mirror_value_that_carries_a_revocation` covers the
  mirror itself: a snapshot that carries a revocation is refused and the key is dropped,
  so a future writer that mirrors a row it did not check cannot hand out a dead session.
"""

from __future__ import annotations

import dataclasses
from typing import Final

import httpx
import sqlalchemy as sa

from bayram.admin.container import AdminContainer
from bayram.admin.csrf import SESSION_COOKIE_NAME
from bayram.admin.security.tokens import sha256_hex
from bayram.admin.sessions import issue_session, mirror_key, resolve_session, write_mirror
from bayram.db.base import utc_now
from bayram.db.models.admin_session import AdminSessionRow
from tests.test_admin.conftest import NOW, FakeRedis, create_account, sign_in

_ABSOLUTE_TTL_S: Final[int] = 43_200
_IDLE_TTL_S: Final[int] = 3_600


def _digest(client: httpx.AsyncClient) -> str:
    return sha256_hex(client.cookies[SESSION_COOKIE_NAME])


async def test_a_session_revoked_directly_in_the_database_401s_with_the_mirror_warm(
    client: httpx.AsyncClient, container: AdminContainer, fake_redis: FakeRedis
) -> None:
    # Arrange - sign in and warm the mirror with a real request
    await create_account(container)
    await sign_in(client)
    assert (await client.get("/api/auth/me")).status_code == 200
    key = mirror_key(_digest(client))
    assert key in fake_redis.values

    # Act - revoke by writing the column, past sessions.revoke_session; Redis is untouched
    async with container.session_factory.begin() as db:
        await db.execute(sa.update(AdminSessionRow).values(revoked_at=utc_now()))

    # Assert - the mirror is still warm, and the request is refused anyway
    assert key in fake_redis.values
    assert (await client.get("/api/auth/me")).status_code == 401
    assert key not in fake_redis.values


async def test_resolve_session_refuses_a_mirror_value_that_carries_a_revocation(
    container: AdminContainer, fake_redis: FakeRedis
) -> None:
    # Arrange - a live session whose mirror was overwritten with a revoked snapshot, which
    # is what any writer that mirrors a row without re-checking ``revoked_at`` produces
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
        await write_mirror(
            container.redis,
            issued.token.sha256,
            dataclasses.replace(issued.snapshot, revoked_at=NOW),
            now=NOW,
            idle_ttl_s=_IDLE_TTL_S,
        )
        assert mirror_key(issued.token.sha256) in fake_redis.values

        # Act
        resolved = await resolve_session(
            db,
            container.redis,
            token_sha256=issued.token.sha256,
            now=NOW,
            idle_ttl_s=_IDLE_TTL_S,
        )

    # Assert - refused, and the poisoned key is gone rather than left to time out
    assert resolved is None
    assert mirror_key(issued.token.sha256) not in fake_redis.values


async def test_a_snapshot_read_from_a_live_row_carries_no_revocation(
    container: AdminContainer,
) -> None:
    # Arrange / Act
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

    # Assert
    assert issued.snapshot.revoked_at is None
