"""Admin sessions: the database is the truth, Redis is a mirror that cannot outlive it.

Two things are being balanced. Every authenticated request needs the session row, and a
session row lookup plus a ``last_seen_at`` write on every request is two round trips to
Postgres for a panel whose whole point is dense, chatty screens. But a cache in front of an
authorisation decision is the classic way a revoked session keeps working, so the mirror is
built to be incapable of that:

* **The operator row is never mirrored.** ``role``, ``is_active`` and ``password_changed_at``
  are read from ``admin_users`` on **every** request by ``deps.get_current_admin`` — §12.1
  T9 — so a demotion, a deactivation or a password change takes effect on the next request
  whether the mirror is warm or not. Nothing in this module can extend any of the three.
* **Revocation invalidates the mirror in the same call.** :func:`revoke_session` and
  :func:`revoke_sessions_for_user` delete the mirror key as part of the revocation rather
  than leaving it to the TTL, which is the correction the review made: the key is derived
  from ``admin_sessions.token_sha256``, a column every revoker already has, so no revoker
  needs the raw token to invalidate.
* **Revocation is re-read from the database on every request, exactly like the operator
  row.** ``deps.get_current_admin`` loads the operator through
  ``accounts.get_for_live_session``, which joins ``admin_sessions`` and returns nothing for
  a revoked one. That read already had to happen for ``role`` and ``is_active``, so folding
  revocation into it costs no extra round trip and keeps the mirror's whole saving — and it
  is what makes "revoke, then request, get 401 with the mirror still warm" true for a
  revoker that writes ``revoked_at`` **without** going through this module: a sweep, a
  future "revoke another admin's sessions", or a hand-written ``UPDATE`` in ``psql``.
* **A mirrored snapshot that carries a revocation is refused.** :class:`SessionSnapshot`
  holds ``revoked_at`` and :func:`resolve_session` will not return a mirror hit that has
  one, so a writer that mirrors a row without re-checking the column cannot hand out a dead
  session either.
* **The TTL is a ceiling, not a lifetime.** :data:`SESSION_MIRROR_TTL_S` is 60 seconds and
  the key is additionally clamped to the session's own remaining absolute and idle windows,
  so a mirror can never answer for a session the database would already refuse.

The ``last_seen_at`` write is throttled to :data:`IDLE_TOUCH_INTERVAL_S`. Without it the
mirror would save a read and add a write, which is not a saving; with it the idle window is
accurate to thirty seconds, which is far finer than the one-hour window it feeds.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Final
from uuid import UUID

import sqlalchemy as sa
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from hbd.admin.security.tokens import SessionToken, generate_csrf_token, issue_session_token
from hbd.db.admin import sessions as session_rows
from hbd.db.models.admin_session import AdminSessionRow
from hbd.logging import get_logger

__all__ = [
    "SESSION_MIRROR_TTL_S",
    "IDLE_TOUCH_INTERVAL_S",
    "SessionSnapshot",
    "IssuedSession",
    "mirror_key",
    "read_mirror",
    "write_mirror",
    "invalidate_mirror",
    "issue_session",
    "resolve_session",
    "touch_session",
    "revoke_session",
    "revoke_sessions_for_user",
    "grant_step_up",
]

_LOGGER: Final = get_logger(__name__)

#: §4's "admin session mirror (TTL ≤ 60s)". A ceiling, clamped further per session below.
SESSION_MIRROR_TTL_S: Final[int] = 60
#: How stale ``last_seen_at`` is allowed to get before a request pays for a write.
IDLE_TOUCH_INTERVAL_S: Final[int] = 30

_MIRROR_PREFIX: Final[str] = "hbd:admin:session"
_MIRROR_VERSION: Final[int] = 1


@dataclass(frozen=True, slots=True)
class SessionSnapshot:
    """One admin session as the request path needs it. Never carries the operator's role.

    Holding a role here would be the privilege bug §12.1 T9 names: it would survive a
    demotion for as long as the mirror lives. The user id is the only link, and the row it
    points at is re-read every request.

    ``revoked_at`` is carried even though a snapshot built from a live row always has it
    ``None``: without the field, the mirror path has no way to *express* a revocation, so
    :func:`resolve_session` could not refuse one however it was written. It defaults to
    ``None`` so a caller that constructs a snapshot by hand cannot accidentally forge a
    revocation, and never the other way round.
    """

    session_id: UUID
    admin_user_id: UUID
    csrf_token: str
    created_at: datetime
    last_seen_at: datetime
    expires_at: datetime
    step_up_scope: str | None
    step_up_at: datetime | None
    revoked_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class IssuedSession:
    """What login hands back: the raw cookie values, and the row that was written.

    ``token`` is a :class:`SessionToken`, whose ``repr`` is redacted, so the one value that
    must never be logged cannot be logged by accident.
    """

    token: SessionToken
    csrf_token: str
    snapshot: SessionSnapshot


def mirror_key(token_sha256: str) -> str:
    """The mirror key for a session, derived from the digest the database already stores."""
    return f"{_MIRROR_PREFIX}:v{_MIRROR_VERSION}:{token_sha256}"


def _to_snapshot(row: AdminSessionRow) -> SessionSnapshot:
    return SessionSnapshot(
        session_id=row.id,
        admin_user_id=row.admin_user_id,
        csrf_token=row.csrf_token,
        created_at=row.created_at,
        last_seen_at=row.last_seen_at,
        expires_at=row.expires_at,
        step_up_scope=row.step_up_scope,
        step_up_at=row.step_up_at,
        revoked_at=row.revoked_at,
    )


def _encode(snapshot: SessionSnapshot) -> str:
    return json.dumps(
        {
            "session_id": str(snapshot.session_id),
            "admin_user_id": str(snapshot.admin_user_id),
            "csrf_token": snapshot.csrf_token,
            "created_at": snapshot.created_at.isoformat(),
            "last_seen_at": snapshot.last_seen_at.isoformat(),
            "expires_at": snapshot.expires_at.isoformat(),
            "step_up_scope": snapshot.step_up_scope,
            "step_up_at": None if snapshot.step_up_at is None else snapshot.step_up_at.isoformat(),
            "revoked_at": None if snapshot.revoked_at is None else snapshot.revoked_at.isoformat(),
        }
    )


def _instant(raw: Any) -> datetime:
    """Parse an ISO instant, forcing UTC. A mirror value is data we wrote, but not trusted."""
    parsed = datetime.fromisoformat(str(raw))
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=UTC)


def _optional_instant(raw: Any) -> datetime | None:
    return None if raw is None else _instant(raw)


def _optional_text(raw: Any) -> str | None:
    return None if raw is None else str(raw)


def _decode(payload: str) -> SessionSnapshot | None:
    """Never throws. A mirror value that will not parse is a miss, not a 500.

    The value came from Redis, which is a boundary like any other: a schema change, a
    truncated write or a key collision must degrade to "read the database" rather than
    taking down the request. The failure is logged with its cause, not swallowed.
    """
    try:
        raw: Any = json.loads(payload)
        return SessionSnapshot(
            session_id=UUID(str(raw["session_id"])),
            admin_user_id=UUID(str(raw["admin_user_id"])),
            csrf_token=str(raw["csrf_token"]),
            created_at=_instant(raw["created_at"]),
            last_seen_at=_instant(raw["last_seen_at"]),
            expires_at=_instant(raw["expires_at"]),
            step_up_scope=_optional_text(raw.get("step_up_scope")),
            step_up_at=_optional_instant(raw.get("step_up_at")),
            revoked_at=_optional_instant(raw.get("revoked_at")),
        )
    except (ValueError, TypeError, KeyError, AttributeError):
        _LOGGER.warning(
            "admin session mirror value could not be decoded; falling back to the database",
            extra={"event": "admin.session.mirror_undecodable"},
            exc_info=True,
        )
        return None


async def read_mirror(redis: Redis[str], token_sha256: str) -> SessionSnapshot | None:
    """The mirrored session, or ``None`` for a miss, a bad value or an unreachable Redis.

    Fails **open towards the database**, which is the safe direction here and only here: the
    mirror can never grant anything the database would refuse, so a Redis outage costs a
    round trip rather than an outage of its own.
    """
    try:
        payload = await redis.get(mirror_key(token_sha256))
    except Exception:
        _LOGGER.warning(
            "admin session mirror is unavailable; reading the database",
            extra={"event": "admin.session.mirror_unavailable"},
            exc_info=True,
        )
        return None
    return None if payload is None else _decode(payload)


def _mirror_ttl_s(snapshot: SessionSnapshot, *, now: datetime, idle_ttl_s: int) -> int:
    """The shortest of the ceiling, the absolute remainder and the idle remainder."""
    absolute_left = int((snapshot.expires_at - now).total_seconds())
    idle_left = int((snapshot.last_seen_at + timedelta(seconds=idle_ttl_s) - now).total_seconds())
    return min(SESSION_MIRROR_TTL_S, absolute_left, idle_left)


async def write_mirror(
    redis: Redis[str],
    token_sha256: str,
    snapshot: SessionSnapshot,
    *,
    now: datetime,
    idle_ttl_s: int,
) -> None:
    """Mirror a session for at most a minute, and never past either of its own clocks."""
    ttl_s = _mirror_ttl_s(snapshot, now=now, idle_ttl_s=idle_ttl_s)
    if ttl_s <= 0:
        return
    try:
        await redis.set(mirror_key(token_sha256), _encode(snapshot), ex=ttl_s)
    except Exception:
        # A mirror that cannot be written is a slower panel, not a broken one.
        _LOGGER.warning(
            "admin session mirror could not be written",
            extra={"event": "admin.session.mirror_write_failed"},
            exc_info=True,
        )


async def invalidate_mirror(redis: Redis[str], token_sha256: str) -> None:
    """Drop a mirrored session **now**, not when its TTL runs out.

    Called by every revocation path. A failure here is logged at ERROR rather than WARNING:
    it means a revoked session may answer for up to :data:`SESSION_MIRROR_TTL_S` more
    seconds, which is a security event an operator has to know about during an incident.
    """
    try:
        await redis.delete(mirror_key(token_sha256))
    except Exception:
        _LOGGER.error(
            "admin session mirror could not be invalidated; a revoked session may survive "
            "until its mirror expires",
            extra={
                "event": "admin.session.mirror_invalidation_failed",
                "mirror_ttl_s": SESSION_MIRROR_TTL_S,
            },
            exc_info=True,
        )


async def issue_session(
    session: AsyncSession,
    redis: Redis[str],
    *,
    admin_user_id: UUID,
    now: datetime,
    absolute_ttl_s: int,
    idle_ttl_s: int,
    ip: str | None,
    user_agent: str | None,
) -> IssuedSession:
    """Mint a token, write the row, and warm the mirror. The only way a session is born."""
    token = issue_session_token()
    csrf_token = generate_csrf_token()
    row = await session_rows.create(
        session,
        admin_user_id=admin_user_id,
        token_sha256=token.sha256,
        csrf_token=csrf_token,
        created_ip=ip,
        user_agent=user_agent,
        now=now,
        expires_at=now + timedelta(seconds=absolute_ttl_s),
    )
    snapshot = _to_snapshot(row)
    await write_mirror(redis, token.sha256, snapshot, now=now, idle_ttl_s=idle_ttl_s)
    return IssuedSession(token=token, csrf_token=csrf_token, snapshot=snapshot)


def _is_within_idle_window(snapshot: SessionSnapshot, *, now: datetime, idle_ttl_s: int) -> bool:
    return now - snapshot.last_seen_at <= timedelta(seconds=idle_ttl_s)


def _is_usable(snapshot: SessionSnapshot, *, now: datetime, idle_ttl_s: int) -> bool:
    """Every reason a mirrored snapshot may still be used, in one place.

    ``revoked_at`` leads because it is the one an expiry check cannot substitute for: a
    session revoked five minutes into a twelve-hour cap passes both clocks.
    """
    return (
        snapshot.revoked_at is None
        and snapshot.expires_at > now
        and _is_within_idle_window(snapshot, now=now, idle_ttl_s=idle_ttl_s)
    )


async def resolve_session(
    session: AsyncSession,
    redis: Redis[str],
    *,
    token_sha256: str,
    now: datetime,
    idle_ttl_s: int,
) -> SessionSnapshot | None:
    """The live session behind this digest, mirror first, or ``None``.

    ``None`` covers every reason a token may not be used — unknown, revoked, past its
    absolute cap, past its idle window — because distinguishing them tells an attacker
    whether a stolen token was ever valid. Revocation and both clocks are re-checked here
    even on a mirror hit, so neither a clamped TTL that Redis failed to honour nor a
    mirrored revoked row can extend a session.

    A mirror hit is **not** on its own proof that a session is live: nothing writes a
    revocation into an existing key, so the authoritative revocation check is the joined
    read in ``deps.get_current_admin``. What this refuses is the mirrored *value* that
    carries one.
    """
    mirrored = await read_mirror(redis, token_sha256)
    if mirrored is not None:
        if _is_usable(mirrored, now=now, idle_ttl_s=idle_ttl_s):
            return mirrored
        await invalidate_mirror(redis, token_sha256)
        return None
    row = await session_rows.get_live(session, token_sha256=token_sha256, now=now)
    if row is None:
        return None
    snapshot = _to_snapshot(row)
    if not _is_within_idle_window(snapshot, now=now, idle_ttl_s=idle_ttl_s):
        return None
    await write_mirror(redis, token_sha256, snapshot, now=now, idle_ttl_s=idle_ttl_s)
    return snapshot


async def touch_session(
    session: AsyncSession,
    redis: Redis[str],
    *,
    snapshot: SessionSnapshot,
    token_sha256: str,
    now: datetime,
    ip: str | None,
    idle_ttl_s: int,
) -> None:
    """Advance the idle window, at most once every :data:`IDLE_TOUCH_INTERVAL_S`.

    Returns without writing when the last touch is recent enough, which is what makes the
    mirror a saving rather than a swap of one round trip for another.
    """
    if now - snapshot.last_seen_at < timedelta(seconds=IDLE_TOUCH_INTERVAL_S):
        return
    await session_rows.touch(session, session_id=snapshot.session_id, now=now, ip=ip)
    refreshed = SessionSnapshot(
        session_id=snapshot.session_id,
        admin_user_id=snapshot.admin_user_id,
        csrf_token=snapshot.csrf_token,
        created_at=snapshot.created_at,
        last_seen_at=now,
        expires_at=snapshot.expires_at,
        step_up_scope=snapshot.step_up_scope,
        step_up_at=snapshot.step_up_at,
        revoked_at=snapshot.revoked_at,
    )
    await write_mirror(redis, token_sha256, refreshed, now=now, idle_ttl_s=idle_ttl_s)


async def revoke_session(
    session: AsyncSession,
    redis: Redis[str],
    *,
    session_id: UUID,
    token_sha256: str,
    now: datetime,
) -> None:
    """Kill one session and drop its mirror, in that order.

    Database first: if the process dies between the two, the session is already dead in the
    truth and merely warm in the cache for a minute. The other order would leave a live row
    with no mirror, which is not a failure at all — but it would also mean an unrevoked
    session had its cache dropped for nothing, and it hides the write that mattered.
    """
    await session_rows.revoke(session, session_id=session_id, now=now)
    await invalidate_mirror(redis, token_sha256)


async def _open_digests(session: AsyncSession, *, admin_user_id: UUID) -> list[str]:
    """The token digests of this operator's unrevoked sessions.

    Read before the bulk revoke because the mirror key is derived from the digest, and a
    revocation that leaves mirrors behind is the exact failure this module exists to
    prevent. It is a read of one indexed column, bounded by how many browsers one operator
    has open.
    """
    statement = sa.select(AdminSessionRow.token_sha256).where(
        AdminSessionRow.admin_user_id == admin_user_id,
        AdminSessionRow.revoked_at.is_(None),
    )
    return list((await session.execute(statement)).scalars().all())


async def revoke_sessions_for_user(
    session: AsyncSession,
    redis: Redis[str],
    *,
    admin_user_id: UUID,
    now: datetime,
) -> int:
    """Kill every session this operator holds, and every mirror of one. Returns the count.

    This is the call behind "change your password", "deactivate this account" and "revoke
    that admin's sessions". Each of those is only true if the mirrors go too (§6.3, §6.8).
    """
    digests = await _open_digests(session, admin_user_id=admin_user_id)
    revoked = await session_rows.revoke_all_for_user(session, admin_user_id=admin_user_id, now=now)
    for digest in digests:
        await invalidate_mirror(redis, digest)
    return revoked


async def grant_step_up(
    session: AsyncSession,
    redis: Redis[str],
    *,
    session_id: UUID,
    token_sha256: str,
    scope: str,
    now: datetime,
) -> None:
    """Record a scoped re-authentication, then drop the mirror so the next read sees it.

    Invalidating rather than rewriting: the grant must be readable immediately and it must
    be readable from the row, because that row is what an audit answers from.
    """
    await session_rows.grant_step_up(session, session_id=session_id, scope=scope, now=now)
    await invalidate_mirror(redis, token_sha256)
