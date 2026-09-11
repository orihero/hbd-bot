"""The first-account CLI: what it refuses, and what it must never print.

Two of these are the reason the command exists in this shape rather than as a one-liner:

* :func:`test_a_password_in_argv_is_refused_and_nothing_is_created` — a password on a command
  line is in ``ps`` and in the shell history, so the flag is accepted only to be refused.
* :func:`test_a_group_readable_password_file_is_refused` — the non-interactive channel is
  only as private as the file's mode.

:func:`test_two_runs_that_both_pass_the_pre_check_create_exactly_one_owner` models the
concurrency case by patching the pre-check to report an empty table while a row exists — which
is exactly the interleaving two simultaneous runs produce. The guarantee then has to come from
the unique index, which is the point.

The database is a **file**-backed SQLite in ``tmp_path`` rather than ``:memory:``: the CLI
opens its own engine through ``build_admin_settings``, and two engines cannot share an
in-memory database.
"""

from __future__ import annotations

from pathlib import Path
from typing import Final

import pytest
import sqlalchemy as sa

from bayram.admin.bootstrap import EXIT_CONFIG, EXIT_OK, EXIT_REFUSED, main
from bayram.db.base import Base
from bayram.db.enums import AdminRole
from bayram.db.models.admin_user import AdminUserRow
from tests.test_admin.conftest import HMAC_KEY, ORIGIN

_PASSWORD: Final[str] = "a-long-enough-bootstrap-password"
_OTHER: Final[str] = "another-long-enough-password"
_OWNER_MODE: Final[int] = 0o600
_GROUP_READABLE_MODE: Final[int] = 0o640


@pytest.fixture
def admin_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> sa.Engine:
    """Point the CLI at a throwaway SQLite file, and hand back a synchronous reader."""
    path = tmp_path / "admin.db"
    monkeypatch.setenv("BAYRAM_DATABASE_URL", f"sqlite+aiosqlite:///{path}")
    monkeypatch.setenv("BAYRAM_ADMIN_AUDIT_HMAC_KEY", HMAC_KEY)
    monkeypatch.setenv("BAYRAM_ADMIN_PUBLIC_ORIGIN", ORIGIN)
    monkeypatch.setenv("BAYRAM_ADMIN_ARGON2_TIME_COST", "2")
    monkeypatch.setenv("BAYRAM_ADMIN_ARGON2_MEMORY_KIB", "32768")
    monkeypatch.setenv("BAYRAM_ADMIN_ARGON2_PARALLELISM", "1")
    engine = sa.create_engine(f"sqlite:///{path}")
    # Created up front so a refusal that never opens the database is still readable here.
    Base.metadata.create_all(engine)
    return engine


def _accounts(engine: sa.Engine) -> list[tuple[str, str, bool, bool]]:
    with engine.connect() as connection:
        rows = connection.execute(
            sa.select(
                AdminUserRow.username,
                AdminUserRow.role,
                AdminUserRow.is_active,
                AdminUserRow.must_change_password,
            )
        ).all()
    return [(str(r[0]), str(r[1]), bool(r[2]), bool(r[3])) for r in rows]


def _password_file(tmp_path: Path, password: str, *, mode: int = _OWNER_MODE) -> Path:
    path = tmp_path / "password.txt"
    path.write_text(f"{password}\n", encoding="utf-8")
    path.chmod(mode)
    return path


def _answer_prompts(monkeypatch: pytest.MonkeyPatch, *answers: str) -> list[str]:
    """Replace ``getpass`` with a scripted reader, recording every prompt it was given."""
    prompts: list[str] = []
    queued = list(answers)

    def fake_getpass(prompt: str = "") -> str:
        prompts.append(prompt)
        return queued.pop(0)

    monkeypatch.setattr("bayram.admin.bootstrap.getpass.getpass", fake_getpass)
    return prompts


# ---------------------------------------------------------------------------
# The password channel
# ---------------------------------------------------------------------------
def test_a_password_in_argv_is_refused_and_nothing_is_created(
    admin_db: sa.Engine, capsys: pytest.CaptureFixture[str]
) -> None:
    # Act
    code = main(["--username", "owner", "--password", _PASSWORD])

    # Assert
    assert code == EXIT_REFUSED
    printed = capsys.readouterr().out
    assert "--password" in printed
    assert "ps" in printed
    assert _PASSWORD not in printed


def test_the_interactive_prompt_creates_an_owner_that_must_rotate(
    admin_db: sa.Engine, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    # Arrange
    _answer_prompts(monkeypatch, _PASSWORD, _PASSWORD)

    # Act
    code = main(["--username", "Owner"])

    # Assert
    assert code == EXIT_OK
    assert _accounts(admin_db) == [("owner", AdminRole.OWNER.value, True, True)]
    assert _PASSWORD not in capsys.readouterr().out


def test_mismatched_prompts_are_refused(
    admin_db: sa.Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Arrange
    _answer_prompts(monkeypatch, _PASSWORD, _OTHER)

    # Act / Assert
    assert main(["--username", "owner"]) == EXIT_REFUSED
    assert _accounts(admin_db) == []


def test_a_short_password_is_refused(admin_db: sa.Engine, monkeypatch: pytest.MonkeyPatch) -> None:
    _answer_prompts(monkeypatch, "short", "short")
    assert main(["--username", "owner"]) == EXIT_REFUSED
    assert _accounts(admin_db) == []


def test_a_password_file_readable_only_by_its_owner_is_accepted(
    admin_db: sa.Engine, tmp_path: Path
) -> None:
    # Arrange
    path = _password_file(tmp_path, _PASSWORD)

    # Act
    code = main(["--username", "owner", "--password-file", str(path)])

    # Assert
    assert code == EXIT_OK
    assert _accounts(admin_db) == [("owner", AdminRole.OWNER.value, True, True)]


def test_a_group_readable_password_file_is_refused(
    admin_db: sa.Engine, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # Arrange
    path = _password_file(tmp_path, _PASSWORD, mode=_GROUP_READABLE_MODE)

    # Act
    code = main(["--username", "owner", "--password-file", str(path)])

    # Assert
    assert code == EXIT_REFUSED
    assert "chmod 600" in capsys.readouterr().out
    assert _accounts(admin_db) == []


def test_a_missing_password_file_is_refused(admin_db: sa.Engine, tmp_path: Path) -> None:
    assert main(["--username", "owner", "--password-file", str(tmp_path / "absent")]) == (
        EXIT_REFUSED
    )


def test_an_empty_username_is_refused(admin_db: sa.Engine, tmp_path: Path) -> None:
    path = _password_file(tmp_path, _PASSWORD)
    assert main(["--username", "   ", "--password-file", str(path)]) == EXIT_REFUSED


# ---------------------------------------------------------------------------
# Bootstrapping once, and only once
# ---------------------------------------------------------------------------
def test_a_second_bootstrap_is_refused_once_an_account_exists(
    admin_db: sa.Engine, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # Arrange
    path = _password_file(tmp_path, _PASSWORD)
    assert main(["--username", "owner", "--password-file", str(path)]) == EXIT_OK
    capsys.readouterr()

    # Act
    code = main(["--username", "second", "--password-file", str(path)])

    # Assert
    assert code == EXIT_REFUSED
    assert "--reset-owner" in capsys.readouterr().out
    assert len(_accounts(admin_db)) == 1


def test_a_second_run_reusing_the_first_login_is_refused_by_the_conditional_insert(
    admin_db: sa.Engine, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The same login twice. Not a concurrency test, and no longer pretending to be one.

    This used to monkeypatch ``bayram.admin.bootstrap.accounts.count_all`` to model "the second
    run reads the table as the first left it". ``count_all`` has **zero call sites** in
    ``bootstrap.py`` — the pre-check was deleted — so the arrangement was inert and this was
    always a plain sequential double-run. The genuine two-connection race lives in
    ``test_bootstrap_race.py``, marked ``integration``, because SQLite's write lock makes it
    unobservable here.

    What is left is still worth pinning: the second run is refused by the *table* being
    non-empty rather than by the username colliding, so the message says "already
    bootstrapped" rather than "that name is taken".
    """
    # Arrange
    path = _password_file(tmp_path, _PASSWORD)
    assert main(["--username", "owner", "--password-file", str(path)]) == EXIT_OK
    capsys.readouterr()

    # Act
    code = main(["--username", "owner", "--password-file", str(path)])

    # Assert
    assert code == EXIT_REFUSED
    assert "already has an admin account" in capsys.readouterr().out
    assert len(_accounts(admin_db)) == 1


# ---------------------------------------------------------------------------
# Recovery
# ---------------------------------------------------------------------------
def test_reset_owner_is_refused_while_another_active_owner_exists(
    admin_db: sa.Engine, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # Arrange
    path = _password_file(tmp_path, _PASSWORD)
    assert main(["--username", "owner", "--password-file", str(path)]) == EXIT_OK
    capsys.readouterr()

    # Act
    code = main(["--username", "rescuer", "--password-file", str(path), "--reset-owner"])

    # Assert
    assert code == EXIT_REFUSED
    assert "active OWNER" in capsys.readouterr().out
    assert len(_accounts(admin_db)) == 1


def test_reset_owner_restores_a_deactivated_owner_and_forces_a_rotation(
    admin_db: sa.Engine, tmp_path: Path
) -> None:
    # Arrange - the only OWNER has been deactivated, so nobody can sign in
    path = _password_file(tmp_path, _PASSWORD)
    assert main(["--username", "owner", "--password-file", str(path)]) == EXIT_OK
    with admin_db.begin() as connection:
        connection.execute(sa.update(AdminUserRow).values(is_active=False))

    # Act - a different password file, so the recovery credential is genuinely new
    other = tmp_path / "second.txt"
    other.write_text(f"{_OTHER}\n", encoding="utf-8")
    other.chmod(_OWNER_MODE)
    code = main(["--username", "owner", "--password-file", str(other), "--reset-owner"])

    # Assert
    assert code == EXIT_OK
    assert _accounts(admin_db) == [("owner", AdminRole.OWNER.value, True, True)]


def test_reset_owner_creates_the_account_when_the_table_is_empty(
    admin_db: sa.Engine, tmp_path: Path
) -> None:
    # Arrange
    path = _password_file(tmp_path, _PASSWORD)

    # Act
    code = main(["--username", "rescuer", "--password-file", str(path), "--reset-owner"])

    # Assert
    assert code == EXIT_OK
    assert _accounts(admin_db) == [("rescuer", AdminRole.OWNER.value, True, True)]


# ---------------------------------------------------------------------------
# Configuration failures are messages, not tracebacks
# ---------------------------------------------------------------------------
def test_a_missing_database_url_is_reported_as_a_configuration_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    # Arrange
    monkeypatch.setattr("bayram.admin.settings.ADMIN_ENV_FILE", str(tmp_path / "absent.env"))
    monkeypatch.delenv("BAYRAM_DATABASE_URL", raising=False)
    monkeypatch.setenv("BAYRAM_ADMIN_AUDIT_HMAC_KEY", HMAC_KEY)
    path = _password_file(tmp_path, _PASSWORD)

    # Act
    code = main(["--username", "owner", "--password-file", str(path)])

    # Assert
    assert code == EXIT_CONFIG
    assert "BAYRAM_DATABASE_URL" in capsys.readouterr().out
