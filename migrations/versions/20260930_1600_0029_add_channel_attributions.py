"""Add channel_attributions: marketing source tracking and campaign conversions.

Revision ID: 0029
Revises: 0028
Create Date: 2026-09-30

Tracks inbound /start parameters for marketing attribution.
- ``telegram_user_id`` is nullable for anonymisation upon /forget.
- ``channel`` is the extracted channel or campaign slug.
- ``raw_param`` is the unmodified start payload.
- ``is_first_touch`` marks the acquiring touchpoint for the customer.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0029"
down_revision: str | None = "0028"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLE = "channel_attributions"
_PARAM_LENGTH = 64

_INDEXES: tuple[tuple[str, bool], ...] = (
    ("telegram_user_id", False),
    ("channel", False),
    ("created_at", False),
)


def upgrade() -> None:
    op.create_table(
        _TABLE,
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("telegram_user_id", sa.BigInteger(), nullable=True),
        sa.Column("channel", sa.String(length=_PARAM_LENGTH), nullable=False),
        sa.Column("raw_param", sa.String(length=_PARAM_LENGTH), nullable=False),
        sa.Column("is_first_touch", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_channel_attributions")),
    )

    with op.batch_alter_table(_TABLE, schema=None) as batch_op:
        for column, unique in _INDEXES:
            batch_op.create_index(batch_op.f(f"ix_{_TABLE}_{column}"), [column], unique=unique)


def downgrade() -> None:
    with op.batch_alter_table(_TABLE, schema=None) as batch_op:
        for column, _ in reversed(_INDEXES):
            batch_op.drop_index(batch_op.f(f"ix_{_TABLE}_{column}"))

    op.drop_table(_TABLE)
