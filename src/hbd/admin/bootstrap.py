"""``python -m hbd.admin.bootstrap`` — the first OWNER, and the way back from losing one.

There is no signup route, so this CLI is the only thing that creates an operator account. It
requires host and database access, which grants nothing the database does not already grant,
and it is deliberately awkward about exactly one thing: **the password never travels through
``argv``.**

``--password`` is accepted by the parser only so it can be **refused with a reason.** A
password on a command line is visible in ``ps`` to every user on the host, it is in the
shell's history file afterwards, and it is in whatever shipped that shell's telemetry. The
two supported channels are a ``getpass`` prompt and ``--password-file``, and the file is
refused when its mode is group- or world-readable — a file anybody on the box can read is
the same disclosure with an extra step.

**Concurrency, and where the guarantee actually lives.** Two operators running this at the
same moment must produce one OWNER, not two. Three things were tried and only the third
works:

* a "refuse if any row exists" pre-check is a read-then-insert, and both runs pass it;
* ``admin_users.username``'s unique index does not rescue that either, because it
  constrains the username rather than the table — two runs choosing ``alice`` and ``bob``
  both pass the read and both insert an OWNER;
* folding the guard into the write (:func:`hbd.db.admin.accounts.insert_first_owner`,
  §12.6) — ``INSERT … SELECT … WHERE NOT EXISTS (SELECT 1 FROM admin_users)`` with a
  rowcount of zero as the refusal — closes the *committed* case and nothing more. Under
  Postgres' READ COMMITTED two overlapping transactions each see an empty table and each
  insert. Two engines behind an ``asyncio`` barrier produced **two OWNER rows in five trials
  out of five on Postgres 16**; SQLite passed only because its write lock serialises the
  insert, which is why the unit suite structurally could not have caught it.

The guarantee is therefore a constraint, not a query: ``ix_admin_users_active_owner``
(migration ``0010``), a partial unique index on ``role = 'owner' AND is_active`` — partial
so that ``--reset-owner`` stays possible when every OWNER has been deactivated. The
conditional insert stays, because it is what turns the ordinary sequential second run into
a sentence an operator can read instead of a driver error; the index is what makes the
simultaneous one impossible. Its ``IntegrityError`` is caught in :func:`_run` and reported
as one line naming what happened and what to do, never as a traceback.

Nothing here prints the password, echoes it back, or logs it — asserted by test.
"""

from __future__ import annotations

import argparse
import asyncio
import getpass
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Final

import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from hbd.admin.container import AdminContainer, admin_container
from hbd.admin.schemas.common import MAX_PASSWORD_CHARS, MIN_PASSWORD_CHARS
from hbd.admin.security.passwords import hash_password
from hbd.admin.sessions import revoke_sessions_for_user
from hbd.admin.settings import build_admin_settings
from hbd.db.admin import accounts
from hbd.db.admin.audit import AuditEntry, append
from hbd.db.base import utc_now
from hbd.db.enums import AdminRole, AuditAction, AuditReasonCode
from hbd.db.models.admin_audit import AuditOutcome
from hbd.db.models.admin_user import AdminUserRow
from hbd.errors import HbdError

__all__ = ["EXIT_OK", "EXIT_REFUSED", "EXIT_CONFIG", "GROUP_AND_WORLD_BITS", "main"]

EXIT_OK: Final[int] = 0
EXIT_REFUSED: Final[int] = 1
EXIT_CONFIG: Final[int] = 2

#: ``0o077`` — any group or other permission bit at all. Not just "readable": a file the
#: group can *write* is a file the group can replace before this command reads it.
GROUP_AND_WORLD_BITS: Final[int] = 0o077

_ARGV_PASSWORD_REFUSAL: Final[str] = (
    "Refusing --password: a password in argv is visible in `ps` to every user on this host "
    "and is written to your shell history. Run without it to be prompted, or use "
    "--password-file with a file only you can read (chmod 600)."
)


class _RefusedError(Exception):
    """An operator-facing refusal. Its message is printed; nothing else is."""


@dataclass(frozen=True, slots=True)
class _Request:
    """What the operator asked for, already validated. Never carries the password."""

    username: str
    is_reset: bool
    password_file: Path | None


def _parse(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="python -m hbd.admin.bootstrap",
        description="Create the first admin OWNER, or recover one that was lost.",
    )
    parser.add_argument("--username", required=True, help="the login to create or reset")
    parser.add_argument(
        "--password-file",
        default=None,
        help="read the password from this file; refused unless it is mode 0600 or stricter",
    )
    parser.add_argument(
        "--reset-owner",
        action="store_true",
        help="recover ownership; refused while another active OWNER exists",
    )
    parser.add_argument(
        "--password",
        default=None,
        help=argparse.SUPPRESS,  # accepted only so it can be refused with an explanation
    )
    return parser.parse_args(argv)


def _read_password_file(path: Path) -> str:
    """The password from a file, or a refusal naming what is wrong with it."""
    if not path.is_file():
        raise _RefusedError(f"{path} is not a file")
    mode = path.stat().st_mode
    if mode & GROUP_AND_WORLD_BITS:
        raise _RefusedError(
            f"Refusing {path}: mode {mode & 0o777:o} lets the group or other users read or "
            "replace it. Run `chmod 600` on it first."
        )
    return path.read_text(encoding="utf-8").strip("\r\n")


def _prompt_password() -> str:
    """Ask twice on the TTY. ``getpass`` does not echo, and neither does anything here."""
    first = getpass.getpass("New admin password: ")
    second = getpass.getpass("Repeat it: ")
    if first != second:
        raise _RefusedError("The two passwords do not match.")
    return first


def _validate_password(password: str) -> str:
    if not MIN_PASSWORD_CHARS <= len(password) <= MAX_PASSWORD_CHARS:
        raise _RefusedError(
            f"The password must be between {MIN_PASSWORD_CHARS} and {MAX_PASSWORD_CHARS} "
            "characters."
        )
    return password


async def _create_owner(
    db: AsyncSession, container: AdminContainer, request: _Request, password: str
) -> str:
    """Insert the first OWNER, guarded inside the statement rather than before it.

    There is no ``count_all`` pre-check any more: it decided nothing the conditional insert
    does not decide, and having one invited the reading that the pre-check was the guarantee.
    The refusal is the rowcount.
    """
    row = await accounts.insert_first_owner(
        db,
        username=request.username,
        password_hash=hash_password(password, hasher=container.hasher),
        now=utc_now(),
    )
    if row is None:
        raise _RefusedError(
            "This database already has an admin account, so an OWNER already exists. Use "
            "--reset-owner to recover ownership when no active OWNER remains."
        )
    return f"Created OWNER {row.username!r}. It must change its password at first sign-in."


async def _reset_owner(
    db: AsyncSession, container: AdminContainer, request: _Request, password: str
) -> str:
    """Recover ownership, but only into a panel that has no active OWNER left.

    Refusing while another active OWNER exists is what keeps this from being a privilege
    escalation for anyone who reaches the host: recovery is for the locked-out case, and the
    locked-out case is exactly "no active OWNER" (§12.6).
    """
    if await accounts.count_active_owners(db) > 0:
        raise _RefusedError(
            "Refusing --reset-owner: this panel still has an active OWNER. Ask them to reset "
            "the account instead — recovery exists for the case where nobody can sign in."
        )
    now = utc_now()
    existing = await accounts.get_by_username(db, request.username)
    password_hash = hash_password(password, hasher=container.hasher)
    if existing is None:
        row = await accounts.create(
            db,
            username=request.username,
            password_hash=password_hash,
            role=AdminRole.OWNER,
            must_change_password=True,
            now=now,
        )
        return f"Created OWNER {row.username!r} by recovery."
    # One statement, so no window exists in which the account is an OWNER with the old
    # password. Sessions go too: recovery must not leave anything outstanding.
    await db.execute(
        sa.update(AdminUserRow)
        .where(AdminUserRow.id == existing.id)
        .values(
            password_hash=password_hash,
            password_changed_at=now,
            must_change_password=True,
            role=AdminRole.OWNER,
            is_active=True,
            updated_at=now,
        )
    )
    await revoke_sessions_for_user(db, container.redis, admin_user_id=existing.id, now=now)
    return f"Reset OWNER {existing.username!r}. It must change its password at next sign-in."


#: What a constraint violation means on each path, in the operator's terms. Both messages
#: cover the two indexes that can fire — ``uq_admin_users_username`` and
#: ``ix_admin_users_active_owner`` — because on both paths they mean the same thing to the
#: person reading: somebody else's write landed first and this run wrote nothing.
_RACED_ON_CREATE: Final[str] = (
    "The database refused this insert: another run created the first admin account at the "
    "same moment, so this one wrote nothing. Exactly one OWNER exists — sign in with it, or "
    "use --reset-owner if nobody can."
)
_RACED_ON_RESET: Final[str] = (
    "The database refused this recovery: an active OWNER now exists, or that username was "
    "just taken. This run wrote nothing. Check with `SELECT username FROM admin_users WHERE "
    "role = 'owner' AND is_active;` and sign in, or re-run with a different --username."
)


#: §12.6: ``bootstrap --reset-owner`` writes an audit row with a NULL ``actor_id``, because
#: the actor is the host and not an operator, and ``system:bootstrap`` as the username so a
#: reader can tell it apart from a login by an account that happens to be called "bootstrap".
_SYSTEM_ACTOR: Final[str] = "system:bootstrap"


async def _audit(db: AsyncSession, container: AdminContainer, *, action: AuditAction) -> None:
    """Record a bootstrap write in the same transaction that made it.

    Same transaction on purpose: an OWNER created without a trace and a trace without an
    OWNER are both worse than neither. This is a CLI, so a failure here surfaces as a
    non-zero exit and a message, which is the right outcome — the operator can re-run.
    """
    await append(
        db,
        AuditEntry(
            action=action,
            actor_id=None,
            actor_username=_SYSTEM_ACTOR,
            actor_role=AdminRole.OWNER,
            subject_type="admin",
            subject_id=None,
            field_names=("password_hash", "role", "is_active"),
            reason_code=(
                AuditReasonCode.INCIDENT
                if action is AuditAction.ADMIN_PASSWORD_CHANGE
                else AuditReasonCode.ROUTINE_OPS
            ),
            outcome=AuditOutcome.OK,
        ),
        key=container.settings.admin_audit_hmac_key.get_secret_value(),
        now=utc_now(),
    )


async def _perform(
    db: AsyncSession, container: AdminContainer, request: _Request, password: str
) -> str:
    if request.is_reset:
        message = await _reset_owner(db, container, request, password)
        await _audit(db, container, action=AuditAction.ADMIN_PASSWORD_CHANGE)
        return message
    message = await _create_owner(db, container, request, password)
    await _audit(db, container, action=AuditAction.ADMIN_CREATE)
    return message


async def _run(request: _Request, password: str) -> str:
    """Open the database, do the one write, and hand back what to print.

    The ``IntegrityError`` is caught **around** the session's context manager, not inside
    it: a violation can surface either at the statement or at the commit that closes the
    block, and a handler that only covered the first would let the second out as a
    traceback — carrying the DSN, which is the one thing this command must never print.
    """
    settings = build_admin_settings()
    try:
        async with admin_container(settings) as container, container.session_factory.begin() as db:
            return await _perform(db, container, request, password)
    except IntegrityError as exc:
        raise _RefusedError(_RACED_ON_RESET if request.is_reset else _RACED_ON_CREATE) from exc


def _collect(args: argparse.Namespace) -> tuple[_Request, str]:
    """Turn parsed arguments into a request and a password, refusing the argv channel."""
    if args.password is not None:
        raise _RefusedError(_ARGV_PASSWORD_REFUSAL)
    username = str(args.username).strip()
    if not username:
        raise _RefusedError("--username must not be empty.")
    file_path = None if args.password_file is None else Path(args.password_file)
    password = _validate_password(
        _read_password_file(file_path) if file_path is not None else _prompt_password()
    )
    return (
        _Request(username=username, is_reset=bool(args.reset_owner), password_file=file_path),
        password,
    )


def main(argv: Sequence[str] | None = None) -> int:
    """Console entry point. Returns an exit code and never raises.

    Every failure prints one line and nothing else — no traceback, because a traceback from
    this command would carry the DSN, and no echo, because the only other thing in scope is
    the password.
    """
    args = _parse(sys.argv[1:] if argv is None else argv)
    try:
        request, password = _collect(args)
    except _RefusedError as exc:
        print(str(exc))
        return EXIT_REFUSED
    try:
        print(asyncio.run(_run(request, password)))
    except _RefusedError as exc:
        # Every constraint violation has already been turned into one of these by ``_run``,
        # so there is no ``except IntegrityError`` here: a second one would be a second
        # wording for the same event, and only one of them would ever be read.
        print(str(exc))
        return EXIT_REFUSED
    except HbdError as exc:
        print(exc.operator_message)
        return EXIT_CONFIG
    return EXIT_OK


if __name__ == "__main__":  # pragma: no cover - process entry point
    raise SystemExit(main())
