"""The ``SECURITY DEFINER`` sweep, against a real two-role Postgres built by Alembic.

§12.4 asks for "an integration test that asserts the sweep actually deletes under the
revoked role", and there was none. The nearest test built its schema with
``Base.metadata.create_all``, so ``hbd_purge_audit_log`` was never created and the whole
definer path had zero coverage — which is why nobody noticed that the function it stood in
for handed the application role an **unbounded** ``DELETE`` against the one table the
``REVOKE`` exists to protect. ``SELECT public.hbd_purge_audit_log('9999-01-01', 1000000)``
returned 30 and left 0 rows, and ``/audit/verify`` went on reporting ``revoke+hmac``.

These tests run the real migration chain, as the owner, with the two-role environment set,
and then act as the application role. Marked ``integration``: they need a Postgres with a
second role, which ``make test-all`` provides and the unit suite deliberately does not.

The three properties, in the order they matter:

1. the legacy two-argument signature does not exist any more, anywhere;
2. the app role's call cannot reach a row that is not already past its own ``expires_at``,
   however it is called — there is no cutoff argument left to aim;
3. the sweep still deletes what IS due, despite the ``REVOKE``, which is the whole reason
   the function exists.
"""

from __future__ import annotations

import os
import subprocess
import sys
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Final

import pytest
import sqlalchemy as sa
from sqlalchemy.exc import ProgrammingError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from bayram.db.admin.audit import PURGE_FUNCTION_NAME, REASON_PURGE_FUNCTION_NAME
from bayram.db.engine import create_engine, create_session_factory, ping
from bayram.db.models import Base
from tests.test_db.conftest import refuse_a_foreign_database

pytestmark = pytest.mark.integration

_ROOT: Final[Path] = Path(__file__).resolve().parents[2]
#: The owner role — the one migrations run as.
_OWNER_URL: Final[str] = os.environ.get(
    "BAYRAM_TEST_POSTGRES_URL", "postgresql+asyncpg://hbd:hbd@localhost:5432/hbd_test"
)
#: The application role, created by ``docker/initdb/10-two-roles.sql``.
_APP_URL: Final[str] = os.environ.get(
    "BAYRAM_TEST_POSTGRES_APP_URL", "postgresql+asyncpg://hbd_app:hbd_app@localhost:5432/hbd_test"
)
_APP_ROLE: Final[str] = "hbd_app"
_NOW: Final[datetime] = datetime(2026, 8, 30, 12, 0, tzinfo=UTC)


def _run_alembic(command: str, target: str | None = None) -> None:
    """Drive Alembic in a subprocess with the two-role environment set.

    A subprocess rather than the API: ``BAYRAM_ADMIN_AUDIT_DSN`` and ``BAYRAM_DB_APP_ROLE`` are
    read by migration 0007 from ``os.environ`` at upgrade time, and the point of this test
    is to exercise the branch a real two-role deployment takes.
    """
    env = {
        **os.environ,
        "BAYRAM_DB_MIGRATION_URL": _OWNER_URL,
        "BAYRAM_DATABASE_URL": _APP_URL,
        "BAYRAM_ADMIN_AUDIT_DSN": _OWNER_URL,
        "BAYRAM_DB_APP_ROLE": _APP_ROLE,
    }
    subprocess.run(
        [
            sys.executable,
            "-m",
            "alembic",
            "-c",
            str(_ROOT / "migrations" / "alembic.ini"),
            command,
            target or ("head" if command == "upgrade" else "base"),
        ],
        cwd=_ROOT,
        env=env,
        check=True,
        capture_output=True,
    )


@pytest.fixture
async def two_role_database() -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    """A migrated two-role database, and a session factory for the APPLICATION role."""
    owner = create_engine(_OWNER_URL)
    if not await ping(owner):
        await owner.dispose()
        pytest.skip(f"no Postgres at {_OWNER_URL}; run `docker compose up -d`")
    app = create_engine(_APP_URL)
    if not await ping(app):
        await owner.dispose()
        await app.dispose()
        pytest.skip(f"no {_APP_ROLE} role at {_APP_URL}; this needs docker/initdb to have run")
    # Reset to a known-empty state from ANY starting point, including a half-migrated one.
    # ``drop_all`` alone is not enough: it does not touch ``alembic_version``, so a database
    # left at head with no tables makes the upgrade below a silent no-op — and it does not
    # touch the definer functions either, which would let a stale one survive into a test
    # written to prove it is gone.
    await refuse_a_foreign_database(owner)
    async with owner.begin() as connection:
        await connection.run_sync(Base.metadata.drop_all)
        await connection.execute(sa.text("DROP TABLE IF EXISTS alembic_version"))
        for signature in (
            f"{PURGE_FUNCTION_NAME}(timestamptz, integer)",
            f"{PURGE_FUNCTION_NAME}(integer)",
            f"{REASON_PURGE_FUNCTION_NAME}(integer)",
        ):
            await connection.execute(sa.text(f"DROP FUNCTION IF EXISTS public.{signature}"))
    _run_alembic("upgrade")
    try:
        yield create_session_factory(app)
    finally:
        _run_alembic("downgrade")
        await app.dispose()
        await owner.dispose()


async def _seed(sessions: async_sessionmaker[AsyncSession], *, expired: int, live: int) -> None:
    """Rows written as the app role — which may INSERT, and only INSERT."""
    rows: list[tuple[datetime, int]] = [
        (_NOW - timedelta(days=1), expired),
        (_NOW + timedelta(days=365), live),
    ]
    async with sessions.begin() as db:
        seq = 0
        for expires_at, count in rows:
            for _ in range(count):
                seq += 1
                await db.execute(
                    sa.text(
                        "INSERT INTO admin_audit_log "
                        "(id, at, actor_username, actor_role, action, subject_type, "
                        " reason_code, outcome, expires_at, chain_hmac) "
                        "VALUES (gen_random_uuid(), :at, 'owner', 'owner', 'login.success', "
                        "'admin', 'routine_ops', 'ok', :expires_at, :hmac)"
                    ),
                    {"at": _NOW, "expires_at": expires_at, "hmac": f"{seq:064d}"},
                )


async def _count(sessions: async_sessionmaker[AsyncSession]) -> int:
    async with sessions.begin() as db:
        return int(await db.scalar(sa.text("SELECT count(*) FROM admin_audit_log")) or 0)


async def test_the_unbounded_legacy_purge_function_no_longer_exists(
    two_role_database: async_sessionmaker[AsyncSession],
) -> None:
    # Arrange / Act — the signature that took a caller-supplied cutoff.
    async with two_role_database.begin() as db:
        found = await db.scalar(
            sa.text("SELECT to_regprocedure('public.hbd_purge_audit_log(timestamptz, integer)')")
        )

    # Assert — one compromised application credential could call it with a cutoff in the
    # year 9999 and erase the entire record of its own use.
    assert found is None


async def test_the_app_role_cannot_delete_a_row_that_is_not_yet_due(
    two_role_database: async_sessionmaker[AsyncSession],
) -> None:
    # Arrange — thirty rows, none of them expired.
    await _seed(two_role_database, expired=0, live=30)

    # Act — every primitive the revoked role has against this table.
    async with two_role_database.begin() as db:
        swept = await db.scalar(
            sa.text(f"SELECT public.{PURGE_FUNCTION_NAME}(:lim)"), {"lim": 1_000_000}
        )
    for statement in (
        "DELETE FROM admin_audit_log",
        "UPDATE admin_audit_log SET actor_username = 'someone else'",
        "TRUNCATE admin_audit_log",
    ):
        # A fresh transaction per statement: the first refusal poisons the one it was made
        # in, and a test that reused it would be asserting on the poison, not the privilege.
        with pytest.raises(ProgrammingError):
            async with two_role_database.begin() as db:
                await db.execute(sa.text(statement))

    # Assert
    assert swept == 0
    assert await _count(two_role_database) == 30


async def test_the_sweep_still_deletes_what_is_due_despite_the_revoke(
    two_role_database: async_sessionmaker[AsyncSession],
) -> None:
    # Arrange
    await _seed(two_role_database, expired=5, live=3)

    # Act
    async with two_role_database.begin() as db:
        swept = await db.scalar(sa.text(f"SELECT public.{PURGE_FUNCTION_NAME}(:lim)"), {"lim": 500})

    # Assert — this is the path §12.4 requires a test for, and the reason the REVOKE and
    # the function ship in one migration.
    assert swept == 5
    assert await _count(two_role_database) == 3


async def test_the_batch_limit_is_clamped_inside_the_function(
    two_role_database: async_sessionmaker[AsyncSession],
) -> None:
    # Arrange — a caller asking for more than the ceiling gets the ceiling, not an error and
    # not a table-emptying statement.
    await _seed(two_role_database, expired=4, live=0)

    # Act
    async with two_role_database.begin() as db:
        swept = await db.scalar(
            sa.text(f"SELECT public.{PURGE_FUNCTION_NAME}(:lim)"), {"lim": 10_000_000}
        )

    # Assert
    assert swept == 4


async def test_the_reason_sweep_exists_and_only_touches_rows_past_their_own_clock(
    two_role_database: async_sessionmaker[AsyncSession],
) -> None:
    # Arrange — the 90-day reason clock is an UPDATE, which the REVOKE also blocks, and
    # 0007 originally shipped no definer function for it at all.
    async with two_role_database.begin() as db:
        for expires, text in (
            (_NOW - timedelta(days=1), "due"),
            (_NOW + timedelta(days=30), "not due"),
        ):
            await db.execute(
                sa.text(
                    "INSERT INTO admin_audit_log "
                    "(id, at, actor_username, actor_role, action, subject_type, reason_code, "
                    " reason_text, reason_expires_at, outcome, expires_at, chain_hmac) "
                    "VALUES (gen_random_uuid(), :at, 'owner', 'owner', 'login.success', "
                    "'admin', 'routine_ops', :text, :reason_expires_at, 'ok', :expires_at, "
                    ":hmac)"
                ),
                {
                    "at": _NOW,
                    "text": text,
                    "reason_expires_at": expires,
                    "expires_at": _NOW + timedelta(days=730),
                    "hmac": f"{hash(text) & 0xFFFF:064d}",
                },
            )

    # Act
    async with two_role_database.begin() as db:
        purged = await db.scalar(
            sa.text(f"SELECT public.{REASON_PURGE_FUNCTION_NAME}(:lim)"), {"lim": 500}
        )
        surviving = list(
            (
                await db.execute(
                    sa.text(
                        "SELECT reason_text, reason_purged_at FROM admin_audit_log ORDER BY seq"
                    )
                )
            ).all()
        )

    # Assert
    assert purged == 1
    assert surviving[0][0] is None and surviving[0][1] is not None
    assert surviving[1][0] == "not due" and surviving[1][1] is None


async def test_revision_0011_removes_a_legacy_function_a_database_already_has() -> None:
    """The repair path, tested on a database that really holds the vulnerable function.

    The ``two_role_database`` fixture sterilises the database before migrating, which proves
    a fresh chain never *creates* the legacy signature — a different property, and not the
    one that matters for a deployment already sitting at 0010. This plants the function the
    way 0007 originally did, then runs 0010 -> head, and asserts the primitive is gone.
    """
    # Arrange
    owner = create_engine(_OWNER_URL)
    if not await ping(owner):
        await owner.dispose()
        pytest.skip(f"no Postgres at {_OWNER_URL}; run `docker compose up -d`")
    try:
        async with owner.begin() as connection:
            await connection.run_sync(Base.metadata.drop_all)
            await connection.execute(sa.text("DROP TABLE IF EXISTS alembic_version"))
        _run_alembic("upgrade", "0010")
        async with owner.begin() as connection:
            await connection.execute(
                sa.text(
                    "CREATE OR REPLACE FUNCTION public.hbd_purge_audit_log"
                    "(cutoff timestamptz, lim integer) RETURNS integer LANGUAGE sql "
                    "SECURITY DEFINER SET search_path = pg_catalog, public AS $$ "
                    "SELECT 0 $$"
                )
            )

        # Act
        _run_alembic("upgrade", "head")

        # Assert
        async with owner.begin() as connection:
            still_there = await connection.scalar(
                sa.text(
                    "SELECT to_regprocedure('public.hbd_purge_audit_log(timestamptz, integer)')"
                )
            )
        assert still_there is None
    finally:
        _run_alembic("downgrade")
        await owner.dispose()
