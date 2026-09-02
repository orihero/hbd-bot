"""``admin_sessions`` persistence — the half of admin authentication that can be stolen.

The tests that matter here are the negative ones. A session store that returns rows is
easy; one that refuses to return a revoked, expired or unknown session — in SQL, with no
Python branch to invert — is the control that makes "log out everywhere" and "the cookie
you copied last month is useless" true.

Time is injected, so "expired one second ago" costs microseconds and is asserted exactly
rather than approximately.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from uuid import UUID

import pytest
import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from hbd.db.admin import accounts
from hbd.db.admin import sessions as admin_sessions
from hbd.db.enums import AdminRole
from hbd.db.models import AdminSessionRow
from tests.test_db.conftest import MovableClock

_HASH = "$argon2id$v=19$m=65536,t=3,p=4$c29tZXNhbHQ$fake-digest-for-tests"
_SESSION_TTL = timedelta(hours=8)
_CSRF = "c" * 64


def _digest(label: str) -> str:
    """A 64-character stand-in for ``sha256(token)`` — the column length is the point."""
    return label.ljust(64, "0")[:64]


async def _new_admin(
    factory: async_sessionmaker[AsyncSession],
    clock: MovableClock,
    *,
    username: str = "owner",
    role: AdminRole = AdminRole.OWNER,
) -> UUID:
    """One operator row.

    ``role`` is a parameter because ``ix_admin_users_active_owner`` allows exactly one
    active OWNER: a test that needs a *second* operator has to ask for a second role.
    """
    async with factory.begin() as session:
        row = await accounts.create(
            session,
            username=username,
            password_hash=_HASH,
            role=role,
            must_change_password=False,
            now=clock.now,
        )
        return row.id


async def _open_session(
    factory: async_sessionmaker[AsyncSession],
    *,
    admin_user_id: UUID,
    token: str,
    now: datetime,
    expires_at: datetime | None = None,
    created_ip: str | None = "203.0.113.7",
    user_agent: str | None = "Mozilla/5.0",
) -> UUID:
    async with factory.begin() as session:
        row = await admin_sessions.create(
            session,
            admin_user_id=admin_user_id,
            token_sha256=_digest(token),
            csrf_token=_CSRF,
            created_ip=created_ip,
            user_agent=user_agent,
            now=now,
            expires_at=expires_at if expires_at is not None else now + _SESSION_TTL,
        )
        return row.id


# ---------------------------------------------------------------------------
# Create and fetch
# ---------------------------------------------------------------------------
async def test_a_new_session_is_live_and_records_where_it_came_from(
    sessions: async_sessionmaker[AsyncSession], clock: MovableClock
) -> None:
    # Arrange
    admin_id = await _new_admin(sessions, clock)
    session_id = await _open_session(sessions, admin_user_id=admin_id, token="a", now=clock.now)

    # Act
    async with sessions() as session:
        live = await admin_sessions.get_live(session, token_sha256=_digest("a"), now=clock.now)

    # Assert
    assert live is not None
    assert live.id == session_id
    assert live.admin_user_id == admin_id
    assert live.csrf_token == _CSRF
    assert live.created_at == clock.now
    assert live.last_seen_at == clock.now
    assert live.expires_at == clock.now + _SESSION_TTL
    assert live.revoked_at is None
    assert live.created_ip == "203.0.113.7"
    assert live.last_ip == "203.0.113.7"
    assert live.user_agent == "Mozilla/5.0"
    assert live.step_up_scope is None
    assert live.step_up_at is None


async def test_an_unknown_token_digest_is_not_live(
    sessions: async_sessionmaker[AsyncSession], clock: MovableClock
) -> None:
    # Arrange
    admin_id = await _new_admin(sessions, clock)
    await _open_session(sessions, admin_user_id=admin_id, token="a", now=clock.now)

    # Act
    async with sessions() as session:
        live = await admin_sessions.get_live(session, token_sha256=_digest("stolen"), now=clock.now)

    # Assert
    assert live is None


async def test_a_revoked_session_is_not_live(
    sessions: async_sessionmaker[AsyncSession], clock: MovableClock
) -> None:
    # Arrange
    admin_id = await _new_admin(sessions, clock)
    session_id = await _open_session(sessions, admin_user_id=admin_id, token="a", now=clock.now)
    revoked_at = clock.advance(seconds=1)
    async with sessions.begin() as session:
        await admin_sessions.revoke(session, session_id=session_id, now=revoked_at)

    # Act — the row is still well within its TTL, so only the revocation can exclude it.
    async with sessions() as session:
        live = await admin_sessions.get_live(session, token_sha256=_digest("a"), now=revoked_at)

    # Assert
    assert live is None


async def test_an_expired_session_is_not_live_at_or_after_its_cap(
    sessions: async_sessionmaker[AsyncSession], clock: MovableClock
) -> None:
    # Arrange — the cap is exactly ``now``: a session whose horizon has arrived has run out.
    admin_id = await _new_admin(sessions, clock)
    cap = clock.now + _SESSION_TTL
    await _open_session(sessions, admin_user_id=admin_id, token="a", now=clock.now)

    # Act
    async with sessions() as session:
        at_cap = await admin_sessions.get_live(session, token_sha256=_digest("a"), now=cap)
        after_cap = await admin_sessions.get_live(
            session, token_sha256=_digest("a"), now=cap + timedelta(seconds=1)
        )
        before_cap = await admin_sessions.get_live(
            session, token_sha256=_digest("a"), now=cap - timedelta(seconds=1)
        )

    # Assert
    assert at_cap is None
    assert after_cap is None
    assert before_cap is not None


# ---------------------------------------------------------------------------
# Touch, revoke, step-up
# ---------------------------------------------------------------------------
async def test_touching_advances_the_idle_window_and_records_the_new_address(
    sessions: async_sessionmaker[AsyncSession], clock: MovableClock
) -> None:
    # Arrange
    admin_id = await _new_admin(sessions, clock)
    session_id = await _open_session(sessions, admin_user_id=admin_id, token="a", now=clock.now)
    later = clock.advance(seconds=120)

    # Act
    async with sessions.begin() as session:
        await admin_sessions.touch(session, session_id=session_id, now=later, ip="198.51.100.4")

    # Assert
    async with sessions() as session:
        live = await admin_sessions.get_live(session, token_sha256=_digest("a"), now=later)
    assert live is not None
    assert live.last_seen_at == later
    assert live.last_ip == "198.51.100.4"
    assert live.created_ip == "203.0.113.7"


async def test_touching_without_an_address_keeps_the_last_known_one(
    sessions: async_sessionmaker[AsyncSession], clock: MovableClock
) -> None:
    # Arrange — an unresolvable client IP is an absence of evidence, not evidence of none.
    admin_id = await _new_admin(sessions, clock)
    session_id = await _open_session(sessions, admin_user_id=admin_id, token="a", now=clock.now)
    later = clock.advance(seconds=30)

    # Act
    async with sessions.begin() as session:
        await admin_sessions.touch(session, session_id=session_id, now=later, ip=None)

    # Assert
    async with sessions() as session:
        live = await admin_sessions.get_live(session, token_sha256=_digest("a"), now=later)
    assert live is not None
    assert live.last_seen_at == later
    assert live.last_ip == "203.0.113.7"


async def test_revoking_twice_keeps_the_first_revocation_instant(
    sessions: async_sessionmaker[AsyncSession], clock: MovableClock
) -> None:
    # Arrange
    admin_id = await _new_admin(sessions, clock)
    session_id = await _open_session(sessions, admin_user_id=admin_id, token="a", now=clock.now)
    first = clock.advance(seconds=10)
    second = clock.advance(seconds=10)

    # Act
    async with sessions.begin() as session:
        await admin_sessions.revoke(session, session_id=session_id, now=first)
        await admin_sessions.revoke(session, session_id=session_id, now=second)

    # Assert — when a session died is evidence; a re-revoke must not rewrite it.
    async with sessions() as session:
        row = await session.get(AdminSessionRow, session_id)
    assert row is not None
    assert row.revoked_at == first


async def test_revoking_every_session_counts_only_the_ones_still_open(
    sessions: async_sessionmaker[AsyncSession], clock: MovableClock
) -> None:
    # Arrange — three sessions for one operator, one already revoked, plus another
    # operator's session that must survive.
    admin_id = await _new_admin(sessions, clock, username="owner")
    other_id = await _new_admin(sessions, clock, username="admin", role=AdminRole.ADMIN)
    for token in ("a", "b", "c"):
        await _open_session(sessions, admin_user_id=admin_id, token=token, now=clock.now)
    survivor = await _open_session(sessions, admin_user_id=other_id, token="z", now=clock.now)
    async with sessions.begin() as session:
        first = await admin_sessions.get_live(session, token_sha256=_digest("a"), now=clock.now)
        assert first is not None
        await admin_sessions.revoke(session, session_id=first.id, now=clock.now)
    later = clock.advance(seconds=60)

    # Act
    async with sessions.begin() as session:
        revoked = await admin_sessions.revoke_all_for_user(
            session, admin_user_id=admin_id, now=later
        )

    # Assert
    assert revoked == 2
    async with sessions() as session:
        still_live = await admin_sessions.get_live(session, token_sha256=_digest("z"), now=later)
        for token in ("a", "b", "c"):
            assert (
                await admin_sessions.get_live(session, token_sha256=_digest(token), now=later)
            ) is None
    assert still_live is not None
    assert still_live.id == survivor


async def test_revoking_every_session_of_an_operator_with_none_is_zero(
    sessions: async_sessionmaker[AsyncSession], clock: MovableClock
) -> None:
    # Arrange
    admin_id = await _new_admin(sessions, clock)

    # Act
    async with sessions.begin() as session:
        revoked = await admin_sessions.revoke_all_for_user(
            session, admin_user_id=admin_id, now=clock.now
        )

    # Assert
    assert revoked == 0


async def test_a_step_up_grant_records_its_scope_and_replaces_the_previous_one(
    sessions: async_sessionmaker[AsyncSession], clock: MovableClock
) -> None:
    # Arrange
    admin_id = await _new_admin(sessions, clock)
    session_id = await _open_session(sessions, admin_user_id=admin_id, token="a", now=clock.now)
    granted = clock.advance(seconds=15)

    # Act
    async with sessions.begin() as session:
        await admin_sessions.grant_step_up(
            session, session_id=session_id, scope="reveal:order-1", now=granted
        )

    # Assert — the scope is stored, so a guard for a different action can refuse it.
    async with sessions() as session:
        live = await admin_sessions.get_live(session, token_sha256=_digest("a"), now=granted)
    assert live is not None
    assert live.step_up_scope == "reveal:order-1"
    assert live.step_up_at == granted

    # Act — a second grant for a different action class.
    regranted = clock.advance(seconds=15)
    async with sessions.begin() as session:
        await admin_sessions.grant_step_up(
            session, session_id=session_id, scope="user.block", now=regranted
        )

    # Assert — scopes replace, they do not accumulate.
    async with sessions() as session:
        live = await admin_sessions.get_live(session, token_sha256=_digest("a"), now=regranted)
    assert live is not None
    assert live.step_up_scope == "user.block"
    assert live.step_up_at == regranted


# ---------------------------------------------------------------------------
# The sweep
# ---------------------------------------------------------------------------
async def test_the_sweep_deletes_expired_rows_and_leaves_live_ones(
    sessions: async_sessionmaker[AsyncSession], clock: MovableClock
) -> None:
    # Arrange — two sessions that expire in an hour, one that lasts a week.
    admin_id = await _new_admin(sessions, clock)
    short = clock.now + timedelta(hours=1)
    for token in ("a", "b"):
        await _open_session(
            sessions, admin_user_id=admin_id, token=token, now=clock.now, expires_at=short
        )
    await _open_session(
        sessions,
        admin_user_id=admin_id,
        token="long",
        now=clock.now,
        expires_at=clock.now + timedelta(days=7),
    )
    later = clock.advance(days=1)

    # Act
    async with sessions.begin() as session:
        deleted = await admin_sessions.purge_expired_sessions(session, now=later, batch_size=100)

    # Assert
    assert deleted == 2
    async with sessions() as session:
        remaining = await session.scalar(sa.select(sa.func.count()).select_from(AdminSessionRow))
    assert remaining == 1


async def test_the_sweep_is_bounded_by_its_batch_size(
    sessions: async_sessionmaker[AsyncSession], clock: MovableClock
) -> None:
    # Arrange — a first run against a backlog must not take a lock on the whole table.
    admin_id = await _new_admin(sessions, clock)
    cap = clock.now + timedelta(hours=1)
    for index in range(5):
        await _open_session(
            sessions,
            admin_user_id=admin_id,
            token=f"tok{index}",
            now=clock.now,
            expires_at=cap,
        )
    later = clock.advance(days=1)

    # Act
    async with sessions.begin() as session:
        first_pass = await admin_sessions.purge_expired_sessions(session, now=later, batch_size=2)
    async with sessions.begin() as session:
        second_pass = await admin_sessions.purge_expired_sessions(session, now=later, batch_size=2)

    # Assert
    assert first_pass == 2
    assert second_pass == 2
    async with sessions() as session:
        remaining = await session.scalar(sa.select(sa.func.count()).select_from(AdminSessionRow))
    assert remaining == 1


async def test_the_sweep_reports_nothing_when_every_session_is_live(
    sessions: async_sessionmaker[AsyncSession], clock: MovableClock
) -> None:
    # Arrange
    admin_id = await _new_admin(sessions, clock)
    await _open_session(sessions, admin_user_id=admin_id, token="a", now=clock.now)

    # Act
    async with sessions.begin() as session:
        deleted = await admin_sessions.purge_expired_sessions(
            session, now=clock.now, batch_size=100
        )

    # Assert
    assert deleted == 0


async def test_two_sessions_cannot_share_a_token_digest(
    sessions: async_sessionmaker[AsyncSession], clock: MovableClock
) -> None:
    # Arrange — the digest is the lookup key, so a duplicate would make one cookie
    # ambiguous between two operators.
    admin_id = await _new_admin(sessions, clock, username="owner")
    other_id = await _new_admin(sessions, clock, username="admin", role=AdminRole.ADMIN)
    await _open_session(sessions, admin_user_id=admin_id, token="a", now=clock.now)

    # Act / Assert
    with pytest.raises(IntegrityError):
        await _open_session(sessions, admin_user_id=other_id, token="a", now=clock.now)


def test_the_digest_helper_produces_a_full_length_column_value() -> None:
    # Arrange / Act
    value = _digest("a")

    # Assert — a helper that quietly produced a short value would make the uniqueness
    # tests above pass for the wrong reason.
    assert len(value) == 64
