"""Add purge_runs.

Revision ID: 0008
Revises: 0007
Create Date: 2026-08-30

The retention design was complete and had never executed. This revision creates the table
that makes the schedule auditable: one row per sweep, written by
``hbd.runtime.retention_job.run_retention_sweep`` on the hourly cron.

Three things here are correctness decisions rather than schema taste:

* ``ran_at`` carries the only index. Every read of this table is "the last N runs", which
  is one ordered scan of that column, and the 365-day self-sweep is a single bounded
  predicate against the same column. A second index would cost every hourly write and buy
  no query.
* ``storage_keys_returned`` and ``storage_keys_deleted`` are TWO columns, not one. The
  purge hands keys back for the caller to delete after the transaction commits, so a
  mismatch between them is an object-store leak — the exact failure this table exists to
  surface. Collapsing them into a single "objects cleaned up" count would make that leak
  arithmetically invisible.
* No retention clock column, and none is wanted. The rows hold counts and no personal
  data, which is what lets them outlive every clock they record: an audit trail on a
  30-day schedule cannot answer "was the 90-day identity sweep running last quarter?".
  They are still bounded, at 365 days, by ``_purge_purge_runs`` in the same job.

The enum is spelled out as a non-native ``VARCHAR`` rather than imported from
``hbd.db.enums``: migrations must not import application code (a test asserts it), and a
native Postgres enum would make every later member a lock-taking ``ALTER TYPE``.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0008"
down_revision: str | None = "0007"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None

_PURGE_RUNS = "purge_runs"

#: Mirrors ``hbd.db.enums.PurgeTrigger``, spelled literally because a migration must keep
#: working after the enum it mirrors is refactored or deleted.
_TRIGGER_VALUES = ("cron", "manual", "user_request")


def _counter(name: str) -> sa.Column[int]:
    """A non-null count column. Every sweep contributes one and they all look alike."""
    return sa.Column(name, sa.Integer(), nullable=False)


def upgrade() -> None:
    op.create_table(
        _PURGE_RUNS,
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("ran_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "trigger",
            sa.Enum(*_TRIGGER_VALUES, name="purgetrigger", native_enum=False, length=32),
            nullable=False,
        ),
        sa.Column("triggered_by_username", sa.String(length=64), nullable=True),
        _counter("duration_ms"),
        _counter("assets_deleted"),
        _counter("brief_notes_purged"),
        _counter("brief_identities_purged"),
        _counter("attempt_identities_purged"),
        _counter("attempt_transcripts_purged"),
        _counter("name_records_deleted"),
        _counter("abandoned_orders_deleted"),
        _counter("purge_runs_deleted"),
        _counter("storage_keys_returned"),
        _counter("storage_keys_deleted"),
        _counter("storage_delete_failures"),
        _counter("batch_size"),
        sa.Column("is_batch_full", sa.Boolean(), nullable=False),
        sa.Column("error_code", sa.String(length=48), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_purge_runs")),
    )
    with op.batch_alter_table(_PURGE_RUNS, schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_purge_runs_ran_at"), ["ran_at"], unique=False)


def downgrade() -> None:
    with op.batch_alter_table(_PURGE_RUNS, schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_purge_runs_ran_at"))

    op.drop_table(_PURGE_RUNS)
