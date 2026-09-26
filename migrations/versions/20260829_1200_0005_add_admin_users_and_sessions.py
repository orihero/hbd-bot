"""Add admin_users and admin_sessions.

Revision ID: 0005
Revises: 0004
Create Date: 2026-08-29

The admin panel needs somewhere to keep operator accounts and their signed-in browsers.
Both tables land in one revision because neither is usable alone: ``admin_sessions`` has a
``CASCADE`` foreign key into ``admin_users``, and an account with no way to hold a session
authenticates nobody.

Three things here are security decisions rather than schema taste:

* ``admin_sessions.token_sha256`` is the ONLY copy of the session token, uniquely indexed
  because the digest is the lookup key on every authenticated request. A dump of this
  table yields nothing replayable as a cookie.
* ``expires_at`` carries its own index: the session sweep is a single bounded predicate
  against it, not a scan.
* ``admin_users`` has no retention clock, deliberately. An operator is staff, not a
  customer, so the FIL-7 purge must not reach these rows — deleting the accounts that
  operate the panel is not a privacy control.

The enum is spelled out as a non-native ``VARCHAR`` rather than imported from
``bayram.db.enums``: migrations must not import application code (a test asserts it), and a
native Postgres enum would make every later member a lock-taking ``ALTER TYPE``.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None

_USERS = "admin_users"
_SESSIONS = "admin_sessions"


def upgrade() -> None:
    op.create_table(
        _USERS,
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("username", sa.String(length=64), nullable=False),
        sa.Column("password_hash", sa.String(length=255), nullable=False),
        sa.Column(
            "role",
            sa.Enum(
                "owner",
                "admin",
                "support",
                "viewer",
                name="adminrole",
                native_enum=False,
                length=32,
            ),
            nullable=False,
        ),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("must_change_password", sa.Boolean(), nullable=False),
        sa.Column("password_changed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_admin_users")),
        sa.UniqueConstraint("username", name=op.f("uq_admin_users_username")),
    )
    with op.batch_alter_table(_USERS, schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_admin_users_created_at"), ["created_at"], unique=False)

    op.create_table(
        _SESSIONS,
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("admin_user_id", sa.Uuid(), nullable=False),
        sa.Column("token_sha256", sa.String(length=64), nullable=False),
        sa.Column("csrf_token", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_ip", sa.String(length=45), nullable=True),
        sa.Column("last_ip", sa.String(length=45), nullable=True),
        sa.Column("step_up_scope", sa.String(length=128), nullable=True),
        sa.Column("step_up_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("user_agent", sa.String(length=256), nullable=True),
        sa.ForeignKeyConstraint(
            ["admin_user_id"],
            ["admin_users.id"],
            name=op.f("fk_admin_sessions_admin_user_id_admin_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_admin_sessions")),
    )
    with op.batch_alter_table(_SESSIONS, schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_admin_sessions_admin_user_id"), ["admin_user_id"], unique=False
        )
        batch_op.create_index(
            batch_op.f("ix_admin_sessions_expires_at"), ["expires_at"], unique=False
        )
        batch_op.create_index(
            batch_op.f("ix_admin_sessions_token_sha256"), ["token_sha256"], unique=True
        )


def downgrade() -> None:
    # Sessions first: the CASCADE points this way, and dropping the parent while a child
    # index still names it fails on Postgres.
    with op.batch_alter_table(_SESSIONS, schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_admin_sessions_token_sha256"))
        batch_op.drop_index(batch_op.f("ix_admin_sessions_expires_at"))
        batch_op.drop_index(batch_op.f("ix_admin_sessions_admin_user_id"))

    op.drop_table(_SESSIONS)

    with op.batch_alter_table(_USERS, schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_admin_users_created_at"))

    op.drop_table(_USERS)
