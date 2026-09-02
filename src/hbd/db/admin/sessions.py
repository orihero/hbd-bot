"""Reads and writes against ``admin_sessions``.

Two rules hold throughout and both are security properties rather than style:

* **Liveness is decided in SQL, never in Python.** :func:`get_live` filters revoked and
  expired rows in the ``WHERE`` clause, so there is no branch a future refactor can invert
  and no window in which a row is fetched, inspected, and used anyway. A revoked session
  is not "a row you must remember to check" — it is a row the query cannot return.
* **``now`` is always the caller's.** Sessions are tested by moving time (expired one
  second ago, revoked one second before the request), which only works if this module has
  no clock of its own.

Counting is done by selecting the ids first and then acting on them, matching
``hbd.db.purge``. ``rowcount`` after a bulk ``UPDATE`` is a driver-dependent number, and
the id list is also what bounds the statement to ``batch_size`` on a first sweep against a
year of accumulated rows.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from hbd.db.models.admin_session import AdminSessionRow

__all__ = [
    "create",
    "get_live",
    "touch",
    "revoke",
    "revoke_all_for_user",
    "grant_step_up",
    "purge_expired_sessions",
]


async def _ids(session: AsyncSession, statement: sa.Select[tuple[UUID]]) -> list[UUID]:
    """Materialise a bounded id list, so the statement that follows is index-driven."""
    return list((await session.execute(statement)).scalars().all())


async def create(
    session: AsyncSession,
    *,
    admin_user_id: UUID,
    token_sha256: str,
    csrf_token: str,
    created_ip: str | None,
    user_agent: str | None,
    now: datetime,
    expires_at: datetime,
) -> AdminSessionRow:
    """Open a session and return the flushed row.

    ``token_sha256`` is the digest of a token this layer never sees; ``expires_at`` is the
    caller's absolute cap rather than something computed here, because the TTL is admin
    configuration and a session must keep the horizon it was issued with.
    """
    row = AdminSessionRow(
        id=uuid4(),
        admin_user_id=admin_user_id,
        token_sha256=token_sha256,
        csrf_token=csrf_token,
        created_at=now,
        last_seen_at=now,
        expires_at=expires_at,
        created_ip=created_ip,
        last_ip=created_ip,
        user_agent=user_agent,
    )
    session.add(row)
    await session.flush()
    return row


async def get_live(
    session: AsyncSession, *, token_sha256: str, now: datetime
) -> AdminSessionRow | None:
    """The session behind this token digest, or ``None`` if it may not be used.

    ``None`` covers three cases the caller must treat identically — no such session,
    revoked, expired — because telling them apart tells an attacker whether a stolen token
    was ever valid. ``expires_at`` is compared strictly: a session whose cap is exactly
    ``now`` has run out.
    """
    statement = sa.select(AdminSessionRow).where(
        AdminSessionRow.token_sha256 == token_sha256,
        AdminSessionRow.revoked_at.is_(None),
        AdminSessionRow.expires_at > now,
    )
    return (await session.execute(statement)).scalar_one_or_none()


async def touch(session: AsyncSession, *, session_id: UUID, now: datetime, ip: str | None) -> None:
    """Advance the idle window, and record where the request came from.

    A missing ``ip`` leaves ``last_ip`` alone rather than nulling it: an unresolvable client
    address is an absence of evidence, and overwriting the last known one with ``NULL``
    would destroy the only forensic value the column has.
    """
    values: dict[str, Any] = {"last_seen_at": now}
    if ip is not None:
        values["last_ip"] = ip
    await session.execute(
        sa.update(AdminSessionRow).where(AdminSessionRow.id == session_id).values(**values)
    )


async def revoke(session: AsyncSession, *, session_id: UUID, now: datetime) -> None:
    """Kill one session. Idempotent — a second call keeps the first revocation's instant."""
    await session.execute(
        sa.update(AdminSessionRow)
        .where(AdminSessionRow.id == session_id, AdminSessionRow.revoked_at.is_(None))
        .values(revoked_at=now)
    )


async def revoke_all_for_user(session: AsyncSession, *, admin_user_id: UUID, now: datetime) -> int:
    """Kill every session this operator holds, returning how many were still open.

    Already-expired rows are revoked too when they have no ``revoked_at``: the caller is
    deactivating an account or changing a password, and "no unrevoked row survives" is a
    simpler thing to verify — in an incident, by hand — than a two-column liveness rule.
    """
    open_ids = await _ids(
        session,
        sa.select(AdminSessionRow.id).where(
            AdminSessionRow.admin_user_id == admin_user_id,
            AdminSessionRow.revoked_at.is_(None),
        ),
    )
    if not open_ids:
        return 0
    await session.execute(
        sa.update(AdminSessionRow).where(AdminSessionRow.id.in_(open_ids)).values(revoked_at=now)
    )
    return len(open_ids)


async def grant_step_up(
    session: AsyncSession, *, session_id: UUID, scope: str, now: datetime
) -> None:
    """Record a re-authentication as valid **for one action class only**.

    Scope and instant are written together because a grace window without a scope is a
    single reveal opening a five-minute door onto every step-up-gated action the role can
    reach. A new grant replaces the previous one; scopes do not accumulate.
    """
    await session.execute(
        sa.update(AdminSessionRow)
        .where(AdminSessionRow.id == session_id)
        .values(step_up_scope=scope, step_up_at=now)
    )


async def purge_expired_sessions(session: AsyncSession, *, now: datetime, batch_size: int) -> int:
    """Delete sessions past their absolute cap, at most ``batch_size`` of them.

    Bounded for the same reason every sweep in ``hbd.db.purge`` is: a first run against a
    year of unpurged rows must not take a lock on the whole table. Revoked-but-unexpired
    rows stay — they are evidence until their own cap passes.
    """
    due = await _ids(
        session,
        sa.select(AdminSessionRow.id)
        .where(AdminSessionRow.expires_at <= now)
        .order_by(AdminSessionRow.expires_at)
        .limit(batch_size),
    )
    if not due:
        return 0
    await session.execute(sa.delete(AdminSessionRow).where(AdminSessionRow.id.in_(due)))
    return len(due)
