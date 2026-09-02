"""Reads and writes against ``admin_users``.

Module-level functions rather than a repository class: there is no per-instance state to
hold — no clock, no policy — and every caller already has the session the admin request is
running in. A class here would only be a namespace with a constructor.

``now`` is a parameter everywhere a clock is needed. The repo tests authentication by
injecting time (a session that expired one second ago, a password changed one second after
a session was issued), and a hidden ``datetime.now()`` would make those tests impossible to
write without sleeping.

Nothing here commits or flushes more than it must: :func:`create` flushes so the caller
gets a populated row back, and that is all. The transaction belongs to the request.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, cast
from uuid import UUID, uuid4

import sqlalchemy as sa
from sqlalchemy import CursorResult
from sqlalchemy.ext.asyncio import AsyncSession

from hbd.db.enums import AdminRole
from hbd.db.models.admin_session import AdminSessionRow
from hbd.db.models.admin_user import AdminUserRow

__all__ = [
    "normalize_username",
    "get_by_username",
    "get_by_id",
    "get_for_live_session",
    "create",
    "insert_first_owner",
    "set_password",
    "touch_login",
    "count_active_owners",
    "count_all",
    "list_all",
    "MAX_ADMIN_ACCOUNTS",
]

#: ``/admins`` is a whole-table read, so it is bounded rather than paged: an operator
#: roster that outgrows this is a deployment nobody designed, and a silent truncation of it
#: would be worse than a page. The cap is asserted by test against the shape the panel
#: renders, and a deployment that reaches it has a problem the panel cannot fix.
MAX_ADMIN_ACCOUNTS: int = 500


def normalize_username(username: str) -> str:
    """Casefold and trim, so one operator cannot become two accounts.

    ``Owner`` and ``owner`` differ only to the database's unique index, which would happily
    hold both — one of them an OWNER, the other whatever a later invite made it. Every read
    and every write in this module goes through here so the stored form is the only form.
    """
    return username.strip().casefold()


async def get_by_username(session: AsyncSession, username: str) -> AdminUserRow | None:
    """The account with this login, active or not.

    Deactivated rows are returned deliberately: the login path must still perform its
    argon2 verify against a real hash, or "unknown user" and "deactivated user" become
    distinguishable by response time.
    """
    statement = sa.select(AdminUserRow).where(AdminUserRow.username == normalize_username(username))
    return (await session.execute(statement)).scalar_one_or_none()


async def get_by_id(session: AsyncSession, admin_user_id: UUID) -> AdminUserRow | None:
    """The account behind a session. Re-read on every request, never cached."""
    return await session.get(AdminUserRow, admin_user_id)


async def get_for_live_session(
    session: AsyncSession, *, admin_user_id: UUID, admin_session_id: UUID
) -> AdminUserRow | None:
    """The operator behind a session that is **still unrevoked** — both facts, one round trip.

    The join is what makes revocation authoritative on every request rather than only on the
    requests that miss the Redis mirror. ``role``, ``is_active`` and ``password_changed_at``
    already have to be re-read here (§12.1 T9), so adding ``admin_sessions.revoked_at`` to
    the same ``SELECT`` costs nothing and leaves the mirror's saving — the session lookup —
    fully intact. Checking it separately would have been a second round trip, which is the
    whole thing the mirror exists to remove.

    ``None`` is returned for an unknown operator and for a revoked session alike, because
    the one caller answers 401 to both and must not tell them apart. Liveness stays in the
    ``WHERE`` clause for the reason ``hbd.db.admin.sessions`` gives: a filter is not a branch
    a refactor can invert.
    """
    statement = (
        sa.select(AdminUserRow)
        .join(AdminSessionRow, AdminSessionRow.admin_user_id == AdminUserRow.id)
        .where(
            AdminUserRow.id == admin_user_id,
            AdminSessionRow.id == admin_session_id,
            AdminSessionRow.revoked_at.is_(None),
        )
    )
    return (await session.execute(statement)).scalar_one_or_none()


async def create(
    session: AsyncSession,
    *,
    username: str,
    password_hash: str,
    role: AdminRole,
    must_change_password: bool,
    now: datetime,
) -> AdminUserRow:
    """Insert an operator and return the flushed row.

    Uniqueness is left to the database rather than checked first: a pre-flight ``SELECT`` is
    a race. That constraint is about the *username*, though, so it is not what gives the
    bootstrap CLI "two concurrent runs create exactly one OWNER" — see
    :func:`insert_first_owner`, which is the call that guard belongs to.
    """
    row = AdminUserRow(
        username=normalize_username(username),
        password_hash=password_hash,
        role=role,
        is_active=True,
        must_change_password=must_change_password,
        password_changed_at=now,
        created_at=now,
        updated_at=now,
    )
    session.add(row)
    await session.flush()
    return row


async def insert_first_owner(
    session: AsyncSession, *, username: str, password_hash: str, now: datetime
) -> AdminUserRow | None:
    """Create the bootstrap OWNER **only into an empty table**. ``None`` means it was not.

    §12.6: ``INSERT … SELECT … WHERE NOT EXISTS (SELECT 1 FROM admin_users)`` with a rowcount
    check. The guard has to be part of the insert because the alternative — ``count_all()``
    and then :func:`create` — is a read-then-insert, and ``admin_users.username``'s unique
    index does not close it: that index constrains the *username*, not the *table*, so two
    runs choosing two different logins both pass the read and both insert an OWNER.

    **Portability.** The statement is plain ANSI: a ``VALUES``-free ``SELECT`` of bound
    parameters with a ``WHERE NOT EXISTS`` subquery, which SQLite and Postgres both accept
    unchanged. Every literal is bound with its own column's type, so the ``UUID``, the
    ``VARCHAR`` enum and the two aware timestamps go through the same bind processors an ORM
    insert would use — a plain ``sa.literal`` would render a naive datetime on SQLite and an
    ``uuid.UUID`` repr on both.

    **What it does and does not guarantee, and what does.** It is atomic against every
    *committed* row, so the read-then-insert window — which spanned two round trips and an
    argon2 hash — is gone, and a second run that starts after the first commits gets a clean
    ``None`` and a readable refusal instead of a driver error. That is the whole of its job.

    It is **not** the "exactly one OWNER" guarantee, and it was wrong to describe it as one.
    Two transactions that genuinely overlap under READ COMMITTED each see an empty table and
    each insert; ``uq_admin_users_username`` does not rescue that, because it constrains the
    username rather than the table. Two engines behind an ``asyncio`` barrier produced two
    OWNER rows in five trials out of five on Postgres 16. The guarantee is
    ``ix_admin_users_active_owner`` (migration ``0010``): a partial unique index on
    ``role = 'owner' AND is_active``, which the losing transaction is forced to consult
    before it can commit. This function raises that ``IntegrityError`` rather than hiding
    it; :mod:`hbd.admin.bootstrap` turns it into one operator-facing line.
    """
    table = AdminUserRow.__table__
    values: dict[str, Any] = {
        "id": uuid4(),
        "username": normalize_username(username),
        "password_hash": password_hash,
        "role": AdminRole.OWNER,
        "is_active": True,
        "must_change_password": True,
        "password_changed_at": now,
        "created_at": now,
        "updated_at": now,
    }
    names = tuple(values)
    source = sa.select(
        *(sa.literal(values[name], type_=table.c[name].type).label(name) for name in names)
    ).where(~sa.exists(sa.select(sa.literal(1)).select_from(table)))
    result = await session.execute(sa.insert(AdminUserRow).from_select(list(names), source))
    # ``rowcount`` after an ``INSERT`` is exact on both drivers — unlike after a bulk
    # ``UPDATE``, which is why ``hbd.db.admin.sessions`` counts ids instead.
    if cast("CursorResult[Any]", result).rowcount != 1:
        return None
    return await get_by_username(session, username)


async def set_password(
    session: AsyncSession, *, admin_user_id: UUID, password_hash: str, now: datetime
) -> None:
    """Replace the credential and clear the forced-change flag.

    ``password_changed_at`` moves to ``now`` in the same statement, which is what voids
    every session issued before it — splitting the two would leave a window in which the
    old password's sessions outlived the old password.
    """
    await session.execute(
        sa.update(AdminUserRow)
        .where(AdminUserRow.id == admin_user_id)
        .values(
            password_hash=password_hash,
            password_changed_at=now,
            must_change_password=False,
            updated_at=now,
        )
    )


async def touch_login(session: AsyncSession, *, admin_user_id: UUID, now: datetime) -> None:
    """Record a successful sign-in. Advisory only — the audit log is the record."""
    await session.execute(
        sa.update(AdminUserRow)
        .where(AdminUserRow.id == admin_user_id)
        .values(last_login_at=now, updated_at=now)
    )


async def count_active_owners(session: AsyncSession) -> int:
    """How many OWNERs can still sign in.

    The last one may not be deactivated or demoted, and ``--reset-owner`` refuses to run
    while this is non-zero, so the count is a guard rather than a statistic.
    """
    total = await session.scalar(
        sa.select(sa.func.count())
        .select_from(AdminUserRow)
        .where(AdminUserRow.role == AdminRole.OWNER, AdminUserRow.is_active.is_(True))
    )
    return int(total or 0)


async def count_all(session: AsyncSession) -> int:
    """Every operator row, including deactivated ones — zero means "not bootstrapped"."""
    total = await session.scalar(sa.select(sa.func.count()).select_from(AdminUserRow))
    return int(total or 0)


async def list_all(session: AsyncSession) -> tuple[AdminUserRow, ...]:
    """Every operator account, deactivated ones included, oldest first.

    Deactivated accounts are **in** the list on purpose. They still own audit rows, they can
    still be reactivated, and a roster that hides them answers "who has access?" with a
    number smaller than the number of credentials that exist. ``is_active`` is on the wire
    so the panel can grey them rather than omit them.

    Ordering is ``created_at`` and then ``id``: usernames are the thing an operator scans,
    but sorting by them would reshuffle the whole list every time somebody is added, and the
    total order the primary key supplies is what keeps two accounts created in the same
    transaction from swapping places between requests.
    """
    rows = await session.scalars(
        sa.select(AdminUserRow)
        .order_by(AdminUserRow.created_at.asc(), AdminUserRow.id.asc())
        .limit(MAX_ADMIN_ACCOUNTS)
    )
    return tuple(rows.all())
