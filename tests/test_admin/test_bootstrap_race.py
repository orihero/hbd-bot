"""Exactly one active OWNER — asserted against the constraint that actually enforces it.

**What was here before did not test anything.** Both this module and
``test_bootstrap.py`` monkeypatched ``hbd.admin.bootstrap.accounts.count_all`` to model "the
second run reads the table as it was before the first committed". ``count_all`` has **zero
call sites in bootstrap.py** — its own docstring says the pre-check was deleted — so the
arrangement was inert and both tests were plain sequential double-runs, which the
conditional ``INSERT … SELECT … WHERE NOT EXISTS`` has always handled. Neither could ever
have caught the defect they were named after.

The defect is real and was measured. Under Postgres' READ COMMITTED that conditional insert
is atomic against every *committed* row and nothing else: two transactions that overlap each
see an empty table and each insert, and ``uq_admin_users_username`` does not rescue that
because it constrains the username rather than the table — two runs choosing ``alice`` and
``bob`` both commit. Two engines behind an :class:`asyncio.Barrier` produced **two OWNER rows
in five trials out of five on Postgres 16**.

So the fix is a constraint — ``ix_admin_users_active_owner``, migration ``0010``, unique on
``role`` where ``role = 'owner' AND is_active`` — and these tests are split to match what
each engine can actually prove:

* the **unit** tests below assert the constraint's behaviour: it refuses a second active
  OWNER, and it permits one beside a *deactivated* one, which is the half that keeps
  ``--reset-owner`` usable. They run on SQLite, which supports partial indexes;
* the **race** itself is marked ``integration`` and needs Postgres, because SQLite
  structurally cannot host it: one write lock serialises the two inserts, so the unit suite
  would report green against a database with no constraint at all. That is exactly why the
  old tests were able to look like they passed.

The CLI's database is a **file**-backed SQLite in ``tmp_path`` for the reason
``test_bootstrap.py`` states: the CLI opens its own engine, and two engines cannot share an
in-memory database.
"""

from __future__ import annotations

import asyncio
import os
from pathlib import Path
from typing import Any, Final, cast

import pytest
import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from hbd.admin.bootstrap import EXIT_OK, EXIT_REFUSED, main
from hbd.admin.container import AdminContainer
from hbd.db.admin import accounts
from hbd.db.base import Base
from hbd.db.enums import AdminRole
from hbd.db.models.admin_user import (
    ACTIVE_OWNER_INDEX,
    ACTIVE_OWNER_PREDICATE,
    AdminUserRow,
)
from tests.test_admin.conftest import HMAC_KEY, NOW, ORIGIN, create_account

_PASSWORD: Final[str] = "a-long-enough-bootstrap-password"
_OWNER_MODE: Final[int] = 0o600
#: Shape-valid but meaningless; nothing in these tests verifies a password.
_HASH: Final[str] = "$argon2id$v=19$m=65536,t=3,p=4$c29tZXNhbHQ$notarealdigest"

#: Matches docker-compose.yml. Overridable so CI can point at its own instance.
_POSTGRES_URL: Final[str] = os.environ.get(
    "HBD_TEST_POSTGRES_URL", "postgresql+asyncpg://hbd:hbd@localhost:5432/hbd"
)
#: Five, because five out of five is what the defect scored. One trial that happens to
#: serialise proves nothing.
_TRIALS: Final[int] = 5

#: ``__table__`` is typed ``FromClause``, which has neither ``indexes`` nor ``create``.
_ADMIN_USERS: Final[sa.Table] = cast("sa.Table", AdminUserRow.__table__)


@pytest.fixture
def admin_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> sa.Engine:
    """Point the CLI at a throwaway SQLite file, and hand back a synchronous reader."""
    path = tmp_path / "admin.db"
    monkeypatch.setenv("HBD_DATABASE_URL", f"sqlite+aiosqlite:///{path}")
    monkeypatch.setenv("HBD_ADMIN_AUDIT_HMAC_KEY", HMAC_KEY)
    monkeypatch.setenv("HBD_ADMIN_PUBLIC_ORIGIN", ORIGIN)
    monkeypatch.setenv("HBD_ADMIN_ARGON2_TIME_COST", "2")
    monkeypatch.setenv("HBD_ADMIN_ARGON2_MEMORY_KIB", "32768")
    monkeypatch.setenv("HBD_ADMIN_ARGON2_PARALLELISM", "1")
    engine = sa.create_engine(f"sqlite:///{path}")
    Base.metadata.create_all(engine)
    return engine


def _usernames(engine: sa.Engine) -> list[str]:
    with engine.connect() as connection:
        rows = connection.execute(sa.select(AdminUserRow.username).order_by(AdminUserRow.username))
        return [str(row[0]) for row in rows]


def _password_file(tmp_path: Path) -> Path:
    path = tmp_path / "password.txt"
    path.write_text(f"{_PASSWORD}\n", encoding="utf-8")
    path.chmod(_OWNER_MODE)
    return path


# ---------------------------------------------------------------------------
# The constraint itself — the thing that makes the guarantee true
# ---------------------------------------------------------------------------
async def test_a_second_active_owner_is_refused_by_the_database(
    container: AdminContainer,
) -> None:
    """The losing transaction's commit, modelled directly.

    ``accounts.create`` is used rather than ``insert_first_owner`` on purpose: the point is
    that the *table* refuses, not that one query noticed. Any write path that reaches an
    ``INSERT`` with ``role = owner`` — a raced bootstrap, a future admin-CRUD route, a hand
    ``INSERT`` in psql — has to be refused, and only a constraint refuses all three.
    """
    # Arrange
    await create_account(container, username="alice", role=AdminRole.OWNER)

    # Act / Assert
    with pytest.raises(IntegrityError):
        async with container.session_factory.begin() as db:
            await accounts.create(
                db,
                username="bob",
                password_hash=_HASH,
                role=AdminRole.OWNER,
                must_change_password=True,
                now=NOW,
            )


async def test_a_new_owner_is_allowed_beside_a_deactivated_one(
    container: AdminContainer,
) -> None:
    """Why the index is partial. Without this, ``--reset-owner`` would be impossible.

    Recovery runs precisely when no OWNER can sign in, and one of its two branches creates a
    new OWNER while the deactivated one is still on the table. An index that counted
    inactive rows would refuse that — leaving the command that exists for "nobody can get
    in" needing somebody to get in and delete a row first.
    """
    # Arrange - the panel's only OWNER, deactivated: nobody can sign in
    former = await create_account(container, username="alice", role=AdminRole.OWNER)
    async with container.session_factory.begin() as db:
        await db.execute(
            sa.update(AdminUserRow).where(AdminUserRow.id == former.id).values(is_active=False)
        )

    # Act
    rescued = await create_account(container, username="bob", role=AdminRole.OWNER)

    # Assert - two OWNER rows, one of them history
    assert rescued.role is AdminRole.OWNER
    async with container.session_factory.begin() as db:
        assert await accounts.count_active_owners(db) == 1
        assert await accounts.count_all(db) == 2


def test_the_constraint_is_declared_where_create_all_will_build_it() -> None:
    """The unit suite builds its schema from the metadata, so the index must live there.

    A constraint that existed only in migration ``0010`` would be absent from every test
    above, which is the arrangement that let the previous version of this file pass.
    """
    # Arrange
    indexes = {str(index.name): index for index in _ADMIN_USERS.indexes}

    # Assert
    index = indexes[ACTIVE_OWNER_INDEX]
    assert index.unique is True
    assert [column.name for column in index.columns] == ["role"]
    assert index.dialect_options["sqlite"]["where"].text == ACTIVE_OWNER_PREDICATE
    assert index.dialect_options["postgresql"]["where"].text == ACTIVE_OWNER_PREDICATE


# ---------------------------------------------------------------------------
# The CLI's side: a violation is one sentence, never a traceback
# ---------------------------------------------------------------------------
def test_a_raced_bootstrap_prints_one_line_and_exits_refused(
    admin_db: sa.Engine,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """What the loser of the race sees. A traceback here would carry the DSN.

    The ``IntegrityError`` is injected rather than raced, because a race the CLI can lose is
    a two-connection Postgres event and this test runs on SQLite — what is under test here
    is the *handling*, which is dialect-independent.
    """

    # Arrange
    async def _raced(*_args: Any, **_kwargs: Any) -> None:
        raise IntegrityError("INSERT INTO admin_users", (), Exception("duplicate key"))

    monkeypatch.setattr("hbd.admin.bootstrap.accounts.insert_first_owner", _raced)
    path = _password_file(tmp_path)

    # Act
    code = main(["--username", "alice", "--password-file", str(path)])

    # Assert
    out = capsys.readouterr().out
    assert code == EXIT_REFUSED
    assert "another run created the first admin account" in out
    assert "Traceback" not in out
    assert _usernames(admin_db) == []


def test_a_raced_recovery_says_so_in_the_words_of_a_recovery(
    admin_db: sa.Engine,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """``--reset-owner`` loses the same race differently, and is told so differently."""

    # Arrange
    async def _raced(*_args: Any, **_kwargs: Any) -> int:
        raise IntegrityError("UPDATE admin_users", (), Exception("duplicate key"))

    monkeypatch.setattr("hbd.admin.bootstrap.accounts.count_active_owners", _raced)
    path = _password_file(tmp_path)

    # Act
    code = main(["--username", "alice", "--password-file", str(path), "--reset-owner"])

    # Assert
    out = capsys.readouterr().out
    assert code == EXIT_REFUSED
    assert "an active OWNER now exists" in out
    assert "Traceback" not in out


def test_the_ordinary_second_run_is_still_a_readable_refusal(
    admin_db: sa.Engine, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The conditional insert stays, because a sentence beats a constraint violation.

    A second run that starts after the first has committed is the common case — two
    operators taking turns, not colliding — and it should read as "already bootstrapped",
    not as a database error. A different username, so the unique index on ``username``
    cannot be what decided.
    """
    # Arrange
    path = _password_file(tmp_path)
    assert main(["--username", "alice", "--password-file", str(path)]) == EXIT_OK
    capsys.readouterr()

    # Act
    code = main(["--username", "bob", "--password-file", str(path)])

    # Assert
    assert code == EXIT_REFUSED
    assert "already has an admin account" in capsys.readouterr().out
    assert _usernames(admin_db) == ["alice"]


# ---------------------------------------------------------------------------
# The conditional insert's own contract
# ---------------------------------------------------------------------------
async def test_the_conditional_insert_creates_the_owner_when_the_table_is_empty(
    container: AdminContainer,
) -> None:
    # Act
    async with container.session_factory.begin() as db:
        row = await accounts.insert_first_owner(db, username="Alice", password_hash=_HASH, now=NOW)

    # Assert - normalised, OWNER, and holding a credential somebody else chose
    assert row is not None
    assert row.username == "alice"
    assert row.role is AdminRole.OWNER
    assert row.is_active is True
    assert row.must_change_password is True
    assert row.password_changed_at == NOW


async def test_the_conditional_insert_returns_none_when_any_row_exists(
    container: AdminContainer,
) -> None:
    # Arrange - one unrelated account, of a role that is not OWNER
    await create_account(container, username="alice", role=AdminRole.VIEWER)

    # Act
    async with container.session_factory.begin() as db:
        row = await accounts.insert_first_owner(db, username="bob", password_hash=_HASH, now=NOW)

    # Assert - "the table is empty", not "this username is free"
    assert row is None
    async with container.session_factory.begin() as db:
        assert await accounts.count_all(db) == 1


# ---------------------------------------------------------------------------
# The race, on the only engine that can host it
# ---------------------------------------------------------------------------
async def _reachable(url: str) -> bool:
    engine = create_async_engine(url, poolclass=NullPool)
    try:
        async with engine.connect() as connection:
            await connection.execute(sa.select(sa.literal(1)))
    except Exception:  # any failure at all means "no project Postgres here", so skip
        return False
    else:
        return True
    finally:
        await engine.dispose()


async def _insert_first_owner_at(engine: AsyncEngine, username: str) -> bool:
    """One bootstrap run's write, on its own connection. ``True`` when it created the row."""
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory.begin() as session:
        row = await accounts.insert_first_owner(
            session, username=username, password_hash=_HASH, now=NOW
        )
        return row is not None


async def _race_once(engines: tuple[AsyncEngine, ...]) -> list[bool | BaseException]:
    """Two runs, two connections, released together. Different logins, deliberately."""
    barrier = asyncio.Barrier(len(engines))

    async def attempt(engine: AsyncEngine, username: str) -> bool:
        await barrier.wait()
        return await _insert_first_owner_at(engine, username)

    outcomes = await asyncio.gather(
        attempt(engines[0], "alice"), attempt(engines[1], "bob"), return_exceptions=True
    )
    return list(outcomes)


@pytest.mark.integration
async def test_two_concurrent_bootstrap_runs_create_exactly_one_owner() -> None:
    """The measured defect, as a test. Needs Postgres; SQLite cannot lose this race.

    Two engines means two connections means two genuinely concurrent transactions, which is
    the only arrangement in which the conditional insert's ``WHERE NOT EXISTS`` can be true
    for both. Against the pre-``0010`` schema this produced two OWNER rows in five trials out
    of five; the constraint makes the loser raise instead.

    Each trial runs in a throwaway schema so a developer's own ``admin_users`` is never
    touched, and the whole thing skips rather than fails when no project Postgres answers —
    the same rule the rest of the integration suite follows.
    """
    # Arrange
    if not await _reachable(_POSTGRES_URL):
        pytest.skip(f"no project Postgres at {_POSTGRES_URL}; run `docker compose up -d`")
    schema = f"hbd_owner_race_{os.getpid()}"
    setup = create_async_engine(_POSTGRES_URL, poolclass=NullPool)
    engines = tuple(
        create_async_engine(
            _POSTGRES_URL,
            poolclass=NullPool,
            connect_args={"server_settings": {"search_path": schema}},
        )
        for _ in range(2)
    )
    try:
        async with setup.begin() as connection:
            await connection.execute(sa.text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
            await connection.execute(sa.text(f'CREATE SCHEMA "{schema}"'))
        async with engines[0].begin() as connection:
            await connection.run_sync(_ADMIN_USERS.create)

        # Act / Assert - one winner per trial, five trials
        for trial in range(_TRIALS):
            outcomes = await _race_once(engines)
            async with engines[0].connect() as connection:
                owners = await connection.scalar(
                    sa.select(sa.func.count()).select_from(AdminUserRow)
                )
                await connection.execute(sa.delete(AdminUserRow))
                await connection.commit()
            assert owners == 1, f"trial {trial} left {owners} OWNER rows"
            assert sum(1 for outcome in outcomes if outcome is True) == 1
    finally:
        for engine in engines:
            await engine.dispose()
        async with setup.begin() as connection:
            await connection.execute(sa.text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
        await setup.dispose()
