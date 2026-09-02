"""Add lyric_budgets.

Revision ID: 0013
Revises: 0012
Create Date: 2026-08-30

The lyric write is the first vendor spend in the product and it happens before every other
gate — the render gate, the credit balance and the in-flight cap all guard the worker, which
a customer who never presses Confirm never reaches. Until this table existed the only bound
on it was ``handlers.lyrics.MAX_LYRIC_WRITES``, which counts writes per DRAFT and is reset
by ``reset_to_welcome``: ``/start`` gave the counter back, so the free tier was uncapped per
person. This is where the per-account daily ceiling is kept, and it is a row rather than a
process-local counter precisely so that a restart does not hand it back either.

Two shape decisions worth stating, because neither is schema taste:

* **One row per account, not one per account per day.** ``day_index`` says which day the
  count belongs to and a claim on a later day overwrites both columns in the same statement
  that increments them, so the table has the cardinality of ``credit_accounts`` and needs no
  retention clock, no purge predicate and no sweep. Nothing here accumulates.
* **A natural primary key with ``autoincrement=False`` and no foreign key to ``users``**,
  exactly as ``credit_accounts`` in ``0006``. ``users`` rows are written only from
  ``_create_order``, and this counter is charged several screens earlier — an FK would make
  the first lyric of a session depend on a row that does not exist yet. Without
  ``autoincrement=False`` SQLite would treat the column as a ROWID alias and renumber an
  insert that supplied Telegram's own id.

``ck_lyric_budgets_writes_not_negative`` mirrors the model's constraint literally rather
than importing it: migrations must not import application code, and a test asserts that.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0013"
down_revision: str | None = "0012"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None

_TABLE = "lyric_budgets"


def upgrade() -> None:
    op.create_table(
        _TABLE,
        sa.Column("telegram_user_id", sa.BigInteger(), autoincrement=False, nullable=False),
        sa.Column("day_index", sa.Integer(), nullable=False),
        sa.Column("writes", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("writes >= 0", name=op.f("ck_lyric_budgets_writes_not_negative")),
        sa.PrimaryKeyConstraint("telegram_user_id", name=op.f("pk_lyric_budgets")),
    )
    with op.batch_alter_table(_TABLE, schema=None) as batch_op:
        # TimestampMixin indexes created_at on every table that uses it; omitting it here
        # would make the migrated schema and Base.metadata disagree, which
        # tests/test_db/test_migrations.py compares column by column.
        batch_op.create_index(
            batch_op.f("ix_lyric_budgets_created_at"), ["created_at"], unique=False
        )


def downgrade() -> None:
    with op.batch_alter_table(_TABLE, schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_lyric_budgets_created_at"))

    op.drop_table(_TABLE)
