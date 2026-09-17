"""Add chat_messages.

Revision ID: 0022
Revises: 0021
Create Date: 2026-09-08

ADMIN_PANEL_PLAN §5.7, §7.
Captures inbound user updates and outbound bot/worker messages for full transcript replication.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0022"
down_revision: str | None = "0021"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLE = "chat_messages"

_INDEXES = (
    "telegram_user_id",
    "user_id",
    "order_id",
    "session_id",
    "correlation_id",
    "created_at",
    "text_expires_at",
    "expires_at",
)


def upgrade() -> None:
    op.create_table(
        _TABLE,
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("telegram_user_id", sa.BigInteger(), nullable=False),
        sa.Column("chat_id", sa.BigInteger(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=True),
        sa.Column("order_id", sa.Uuid(), nullable=True),
        sa.Column("session_id", sa.String(length=32), nullable=True),
        sa.Column(
            "direction",
            sa.Enum("inbound", "outbound", name="chatdirection", native_enum=False, length=32),
            nullable=False,
        ),
        sa.Column(
            "kind",
            sa.Enum(
                "text",
                "callback",
                "screen",
                "audio",
                "voice",
                "toast",
                "action",
                name="chatmessagekind",
                native_enum=False,
                length=32,
            ),
            nullable=False,
        ),
        sa.Column("wizard_step", sa.String(length=32), nullable=True),
        sa.Column("telegram_message_id", sa.BigInteger(), nullable=True),
        sa.Column("callback_data", sa.String(length=64), nullable=True),
        sa.Column("parse_mode", sa.String(length=16), nullable=True),
        sa.Column("body", sa.String(length=4000), nullable=True),
        sa.Column("is_truncated", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("is_from_worker", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("media_group_id", sa.String(length=32), nullable=True),
        sa.Column("error_code", sa.String(length=48), nullable=True),
        sa.Column("correlation_id", sa.String(length=128), nullable=True),
        sa.Column("text_expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("body_purged_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("fk_chat_messages_user_id_users"), ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_chat_messages")),
    )
    with op.batch_alter_table(_TABLE, schema=None) as batch_op:
        for column in _INDEXES:
            batch_op.create_index(batch_op.f(f"ix_{_TABLE}_{column}"), [column], unique=False)
        batch_op.create_index(
            "ix_chat_messages_user_timeline",
            ["telegram_user_id", "created_at"],
            unique=False,
        )
        batch_op.create_index(
            "ix_chat_messages_text_sweep",
            ["text_expires_at"],
            unique=False,
        )
        batch_op.create_index(
            "ix_chat_messages_expiry_sweep",
            ["expires_at"],
            unique=False,
        )

    with op.batch_alter_table("purge_runs", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column("chat_bodies_purged", sa.Integer(), nullable=False, server_default=sa.text("0"))
        )
        batch_op.add_column(
            sa.Column("chat_messages_deleted", sa.Integer(), nullable=False, server_default=sa.text("0"))
        )


def downgrade() -> None:
    with op.batch_alter_table("purge_runs", schema=None) as batch_op:
        batch_op.drop_column("chat_messages_deleted")
        batch_op.drop_column("chat_bodies_purged")

    with op.batch_alter_table(_TABLE, schema=None) as batch_op:
        batch_op.drop_index("ix_chat_messages_expiry_sweep")
        batch_op.drop_index("ix_chat_messages_text_sweep")
        batch_op.drop_index("ix_chat_messages_user_timeline")
        for column in reversed(_INDEXES):
            batch_op.drop_index(batch_op.f(f"ix_{_TABLE}_{column}"))

    op.drop_table(_TABLE)
