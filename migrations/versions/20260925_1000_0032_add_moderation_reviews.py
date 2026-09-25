"""The media review queue (IMAGE_VIDEO_SPEC §6.6, M3.2).

Revision ID: 0032
Revises: 0031
Create Date: 2026-09-25

One new table, ``moderation_reviews``, and nothing else. Nothing is backfilled: a job held
before this revision (none exist outside beta) is picked up by nobody and ends at its SKU
deadline like any other stuck paid job.

* One row per time a paid media job is held for a person: the L4 guard answered ``review``, the
  guard did not answer for 30 minutes, or an operator held it. ``decision`` NULL is pending.
* ``ix_moderation_reviews_one_pending_per_job`` — partial UNIQUE (job_id) WHERE decision IS
  NULL: at most one pending review per job, so two holds racing open one row.
* ``ix_moderation_reviews_decision_created`` — the queue's read and the 24 h SLA sweep's.
* ``job_id`` → ``media_jobs.id`` ON DELETE CASCADE: the review lives as long as its job.

The table holds no customer text (closed category codes, an operator name snapshot, a closed
reason code), so no retention clock and no ``purge_runs`` counter: it is bounded by its job.

The ``decision IS NULL`` predicate renders identically on SQLite and Postgres (0010/0028/0031's
precedent). Enums are spelled literally and clocks are plain ``sa.DateTime(timezone=True)``: no
migration imports application code.

**The downgrade drops every review decision ever recorded.** The audit log keeps who released
or refunded what (``moderation.approve`` / ``moderation.refund``), so the loss is the queue's
own history, not the accountability record.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0032"
down_revision: str | None = "0031"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLE = "moderation_reviews"

#: Spelled identically on ``ModerationReviewRow``.
_ONE_PENDING_INDEX = "ix_moderation_reviews_one_pending_per_job"
_ONE_PENDING_PREDICATE = "decision IS NULL"
_QUEUE_INDEX = "ix_moderation_reviews_decision_created"

_REASON_CODES = (
    "customer_request",
    "gdpr_erasure",
    "abuse_report",
    "support_investigation",
    "incident",
    "bake_off",
    "routine_ops",
    "other",
)


def _enum(name: str, *values: str, length: int = 32) -> sa.Enum:
    """A ``VARCHAR`` enum as ``enum_type`` renders it: no native type, no CHECK."""
    return sa.Enum(*values, name=name, native_enum=False, length=length)


def upgrade() -> None:
    op.create_table(
        _TABLE,
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("job_id", sa.Uuid(), nullable=False),
        sa.Column(
            "source",
            _enum("mediareviewsource", "output_review", "guard_unavailable", "manual", length=24),
            nullable=False,
        ),
        sa.Column("subject", sa.String(length=16), nullable=False),
        sa.Column("categories", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("due_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "decision",
            _enum("mediareviewdecision", "released", "blocked", "expired", length=24),
            nullable=True,
        ),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("actor_id", sa.Uuid(), nullable=True),
        sa.Column("actor", sa.String(length=64), nullable=True),
        sa.Column("reason_code", _enum("auditreasoncode", *_REASON_CODES), nullable=True),
        sa.Column("applied_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["job_id"],
            ["media_jobs.id"],
            name=op.f("fk_moderation_reviews_job_id_media_jobs"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_moderation_reviews")),
    )
    with op.batch_alter_table(_TABLE, schema=None) as batch_op:
        batch_op.create_index(batch_op.f(f"ix_{_TABLE}_job_id"), ["job_id"], unique=False)
        batch_op.create_index(_QUEUE_INDEX, ["decision", "created_at", "id"], unique=False)
    op.create_index(
        _ONE_PENDING_INDEX,
        _TABLE,
        ["job_id"],
        unique=True,
        postgresql_where=sa.text(_ONE_PENDING_PREDICATE),
        sqlite_where=sa.text(_ONE_PENDING_PREDICATE),
    )


def downgrade() -> None:
    op.drop_index(_ONE_PENDING_INDEX, table_name=_TABLE)
    with op.batch_alter_table(_TABLE, schema=None) as batch_op:
        batch_op.drop_index(_QUEUE_INDEX)
        batch_op.drop_index(batch_op.f(f"ix_{_TABLE}_job_id"))
    op.drop_table(_TABLE)
