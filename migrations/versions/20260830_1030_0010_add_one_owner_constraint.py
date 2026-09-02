"""Add the partial unique index that makes "exactly one active OWNER" true.

Revision ID: 0010
Revises: 0009
Create Date: 2026-08-30

``python -m hbd.admin.bootstrap`` guarded its first insert with
``INSERT … SELECT … WHERE NOT EXISTS (SELECT 1 FROM admin_users)`` and treated a rowcount of
zero as the refusal. That is atomic against every *committed* row and nothing else: under
Postgres' READ COMMITTED two overlapping transactions each see an empty table and each
insert. ``uq_admin_users_username`` does not close it either, because it constrains the
username rather than the table — two runs choosing ``alice`` and ``bob`` both pass the
subquery and both commit an OWNER. Two engines behind an ``asyncio`` barrier produced **two
OWNER rows in five trials out of five on Postgres 16**; SQLite passed only because its
write lock serialises the insert, which is why no unit test could ever have caught it.

A better query cannot fix a race that a better query is a party to. A unique index can,
because it is the one guard the second transaction is forced to consult before it commits.

**The predicate is ``role = 'owner' AND is_active``, and stopping there is the decision.**
Counting inactive owners too would break ``--reset-owner``, which exists for exactly the
case where no OWNER can sign in: recovery either reactivates the deactivated row or creates
a new OWNER beside it, and the second of those would then be refused — so the one command
for "nobody can get in" would need somebody to get in and delete a row first. It would also
disagree with ``count_active_owners``, which is what gates recovery and refuses the last
demotion, so "an OWNER" would mean two different things in two layers. Deactivated
ex-owners are history; history may repeat.

**This migration will fail on a database that already has two active OWNERs** — which is
the state the defect above produced, and the reason to run it. That failure is correct and
deliberate: deactivate the OWNER that should not be one (``UPDATE admin_users SET
is_active = false WHERE id = …``) and run it again. Silently picking a winner here would
mean an operator losing access without a record of why.

Both dialects get the same predicate. SQLite has supported partial indexes since 3.8.0 and
evaluates a bare integer column as a boolean, so one string serves both; it is spelled out
literally rather than imported from ``hbd.db.models.admin_user`` because a migration must
not import application code (a test asserts it) and must keep working after that module is
renamed.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0010"
down_revision: str | None = "0009"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None

_TABLE = "admin_users"
_INDEX = "ix_admin_users_active_owner"
#: Mirrors ``hbd.db.models.admin_user.ACTIVE_OWNER_PREDICATE``. ``'owner'`` is the *value*
#: ``enum_type(AdminRole)`` persists, not the Python member name.
_ACTIVE_OWNER = "role = 'owner' AND is_active"


def upgrade() -> None:
    # Not inside ``batch_alter_table``: creating an index needs no table rewrite on either
    # dialect, and batch mode would copy the table for nothing.
    op.create_index(
        op.f(_INDEX),
        _TABLE,
        ["role"],
        unique=True,
        postgresql_where=sa.text(_ACTIVE_OWNER),
        sqlite_where=sa.text(_ACTIVE_OWNER),
    )


def downgrade() -> None:
    op.drop_index(op.f(_INDEX), table_name=_TABLE)
