"""``admin_users`` — one row per operator who may sign in to the admin panel.

Three properties of this table are security decisions rather than schema preferences:

* **Only the argon2id PHC string is stored.** ``password_hash`` is the whole credential
  record — salt and parameters live inside the PHC string — so there is no second column
  for anything an attacker with a dump could use. The plaintext never reaches this layer.
* **An operator is deactivated, never deleted.** The audit log points at these rows, and a
  deleted operator would turn every action they ever took into an unattributable entry.
  ``is_active`` is the switch every request re-reads; there is no cached copy of it.
* **No customer personal data.** An operator is staff, so this table carries no retention
  clock and is deliberately absent from ``tables_with_personal_data`` in
  ``tests/test_db/test_privacy_constraints.py`` — the FIL-7 sweep must not delete the
  accounts that operate it.

``password_changed_at`` is not bookkeeping either: a session issued before that instant is
no longer trustworthy, so the value is what makes "change the password and every stolen
session dies" enforceable rather than aspirational.
"""

from __future__ import annotations

from datetime import datetime
from typing import Final
from uuid import UUID, uuid4

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from hbd.db.base import Base, TimestampMixin, UtcDateTime, enum_type, utc_now
from hbd.db.enums import AdminRole

__all__ = [
    "AdminUserRow",
    "USERNAME_LENGTH",
    "PASSWORD_HASH_LENGTH",
    "ACTIVE_OWNER_INDEX",
    "ACTIVE_OWNER_PREDICATE",
]

#: Long enough for an email-shaped login, short enough that the unique index stays small.
USERNAME_LENGTH: Final[int] = 64
#: An argon2id PHC string is ~100 characters; the margin covers a parameter change.
PASSWORD_HASH_LENGTH: Final[int] = 255

#: The partial unique index that makes "exactly one OWNER" true rather than intended.
#: Named here so the bootstrap CLI can recognise the violation it raises without parsing a
#: driver's prose, and so migration ``0010`` and this model cannot drift apart.
ACTIVE_OWNER_INDEX: Final[str] = "ix_admin_users_active_owner"

#: ``role = 'owner' AND is_active`` — deliberately **not** every OWNER row.
#:
#: The literal ``'owner'`` is :attr:`AdminRole.OWNER`'s *value*, which is what
#: ``enum_type`` persists; it is spelled out rather than interpolated because the identical
#: string has to appear in a migration, and a migration may not import application code.
#:
#: **Why the predicate stops at ``is_active``.** Recovery is the case that decides it.
#: ``--reset-owner`` runs precisely when no OWNER can sign in — deactivated or demoted — and
#: it then either reactivates that row or creates a new OWNER beside it. An index that
#: counted inactive owners would refuse the second of those, so the one command that exists
#: for "nobody can get in" would itself need somebody to get in and delete a row first. It
#: would also disagree with every other guard in the system: ``count_active_owners`` is what
#: refuses the last demotion and gates recovery, so "an OWNER" means "an OWNER who can sign
#: in" everywhere else, and a constraint using a different definition is a trap rather than
#: a guarantee. Deactivated ex-owners are history, and history is allowed to repeat.
ACTIVE_OWNER_PREDICATE: Final[str] = "role = 'owner' AND is_active"


class AdminUserRow(TimestampMixin, Base):
    """An operator account.

    ``must_change_password`` defaults to ``True`` because the two ways a row is created —
    the bootstrap CLI and an owner-issued reset — both hand the operator a password
    somebody else chose. Defaulting the other way would make the safe case the one that
    has to be remembered.
    """

    __tablename__ = "admin_users"

    id: Mapped[UUID] = mapped_column(sa.Uuid, primary_key=True, default=uuid4)
    #: Stored casefolded by :func:`hbd.db.admin.accounts.normalize_username`, so ``Owner``
    #: and ``owner`` cannot become two accounts with two different roles.
    username: Mapped[str] = mapped_column(sa.String(USERNAME_LENGTH), nullable=False, unique=True)
    #: argon2id PHC string. Never leaves the process, at any role.
    password_hash: Mapped[str] = mapped_column(sa.String(PASSWORD_HASH_LENGTH), nullable=False)
    role: Mapped[AdminRole] = mapped_column(enum_type(AdminRole), nullable=False)
    is_active: Mapped[bool] = mapped_column(sa.Boolean, nullable=False, default=True)
    must_change_password: Mapped[bool] = mapped_column(sa.Boolean, nullable=False, default=True)
    #: Every session issued before this instant is void. See the module docstring.
    password_changed_at: Mapped[datetime] = mapped_column(
        UtcDateTime, nullable=False, default=utc_now
    )
    last_login_at: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)

    #: At most one active OWNER, enforced by the database.
    #:
    #: The bootstrap CLI's conditional ``INSERT … SELECT … WHERE NOT EXISTS`` is not this
    #: guarantee and never was: under Postgres' READ COMMITTED two overlapping transactions
    #: each see an empty table and each insert, and ``uq_admin_users_username`` does not
    #: rescue that because it constrains the *username* — two runs choosing ``alice`` and
    #: ``bob`` both commit. Measured, not theorised: two engines behind an ``asyncio``
    #: barrier produced two OWNER rows in five trials out of five on Postgres 16. SQLite
    #: passed only because its write lock serialises the insert, which is why the unit suite
    #: could never have caught it.
    #:
    #: A unique index is the only thing that closes it, because it is the only guard the
    #: second transaction is forced to consult. Partial, so that recovery stays possible —
    #: see :data:`ACTIVE_OWNER_PREDICATE`.
    __table_args__ = (
        sa.Index(
            ACTIVE_OWNER_INDEX,
            "role",
            unique=True,
            postgresql_where=sa.text(ACTIVE_OWNER_PREDICATE),
            sqlite_where=sa.text(ACTIVE_OWNER_PREDICATE),
        ),
    )
