"""Add user_activity_snapshots.

Revision ID: 0018
Revises: 0017
Create Date: 2026-09-08

**WHY A TABLE AT ALL.** ``users.last_seen_at`` is UPSERTed IN PLACE by ``credits.touch``,
driven from ``bot/gate.py``'s ``TouchDrain``, so the column is a GAUGE whose past is
overwritten every minute an account is alive. No historical active-user series is derivable
from anything in this schema today, and none of the past is recoverable: the values that
would have answered "how many people were active last Tuesday" were written over, and there
is no log, no event table and no audit row holding them.

**WHY DAY-GRAIN COUNTS AND NOT (day, user).** A per-day per-user presence row would buy
retroactive cohorts, which nothing on the dashboard asks for, at DAU rows per day instead of
365 a year. Decisively, it would BE personal data — a movement record about an identified
person — so it would need a retention clock, a sweep, a ``RetentionPolicy`` period and an
erasure decision, and it would build precisely the per-customer surveillance record the
panel already refuses by withholding ``last_seen_at`` from every ``/users`` view "so an
operator cannot watch one customer minute by minute". Aggregate counts over the whole
population answer every card on the mock and hold nothing about anybody.

**WHY THE COUNTS ARE NOT NULL BUT CARRY NO DEFAULT OF ANY KIND.** The row IS the
measurement: all five counts come from ONE statement in one transaction, and the row is
written only if that statement returned, so a row cannot exist with some of them unmeasured
and ``NOT NULL`` simply states that. What the null-never-zero rule actually forbids is the
DEFAULT — a ``server_default`` of ``0`` is what made ``generation_attempts.cost_usd``
unreadable — so there is none, and an ``INSERT`` that omitted a count fails loudly instead
of writing a fabricated zero.

**THE FORWARD RULE, stated here because a later revision will need it.** ANY count column
added to this table by a LATER revision MUST be nullable with no default, because rows
already written never measured it. Revision 0016's ``purge_runs.vendor_usage_deleted``
carve-out does NOT transfer: that column could be back-filled with 0 because zero was the
TRUE answer for old sweeps (the table did not exist), whereas "how many accounts were active
30 days ago" has no true value for a night nobody counted. The concrete case is already
visible — a ``bot_blocked_accounts`` column matching revision 0017's ``users.blocked_bot_at``
must be nullable, because every snapshot taken before 0017 measured no such thing.

**WHY ``UNIQUE(snapshot_date)`` AND NOT A COMPOSITE PRIMARY KEY.** The unique constraint is
the idempotency authority, exactly as ``credit_ledger.idempotency_key``'s unique index is for
the ledger: the writer goes through ``insert_or_ignore``, so two racing writers produce one
row and one detectable loser, and a re-run later the same day is an ignored no-op rather
than a silent re-anchoring of that day's measurement by several hours. The surrogate ``id``
keeps the table shaped like every other in this schema.

**WHY THERE IS NO OTHER INDEX.** Every read is "the last N days by date", which the unique
index already serves. Nothing filters or orders on ``taken_at``, on ``created_at`` or on any
count, and an index on a table that gains one row a night would be DDL a future reader has to
re-derive the harmlessness of.

**WHY NO RETENTION CLOCK AND NO ``*_expires_at`` — a deliberate departure from
``vendor_usage`` (400 days) and ``purge_runs`` (365), argued rather than omitted.** Growth is
365 rows a year, so there is nothing to bound; the long history IS the product, and a cutoff
would delete exactly the year-over-year comparison the table exists to make possible; and
there is no personal data here, so no legal schedule applies. Nothing is added to
``hbd.db.purge`` — no constant, no ``PurgeReport`` field, no ``purge_runs`` column, no entry
in ``rows_past_expiry_statements`` — and that module's own docstring names this table as
deliberately unswept, exactly as it already does for ``user_profiles``. The ``*_expires_at``
suffix is avoided for the usual reason: it obliges a sweep BY NAME in
``tests/test_db/test_audit_retention.py``. The table sits in NEITHER of
``tests/test_db/test_privacy_constraints.py``'s sets and that omission is recorded there.

**THIS REVISION SEEDS NOTHING, AND THE TABLE CANNOT BE BACKFILLED.** The first row appears
the first night the cron runs. ``active_30d_accounts`` is bounded by deployment age for its
first thirty days — a ramp that looks like growth and is not — and a day the worker was down
gets NO ROW, never a zero. Anyone who later "fixes" the empty chart by seeding rows from
``users.created_at`` will have fabricated the metric.

**No application imports anywhere in this file.** ``sa.DateTime(timezone=True)`` is spelled
literally because that is what ``UtcDateTime`` renders (see ``migrations/env.py``), and
``test_no_migration_imports_application_code`` fails a migration that reaches into ``hbd.*``.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0018"
down_revision: str | None = "0017"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLE = "user_activity_snapshots"


def upgrade() -> None:
    op.create_table(
        _TABLE,
        sa.Column("id", sa.Uuid(), nullable=False),
        # The UTC calendar day this sample is filed under.
        sa.Column("snapshot_date", sa.Date(), nullable=False),
        # The instant the counts were evaluated at — the anchor of every window on the row.
        sa.Column("taken_at", sa.DateTime(timezone=True), nullable=False),
        # Every count: NOT NULL, and NO server_default. See the module docstring.
        sa.Column("total_accounts", sa.Integer(), nullable=False),
        sa.Column("blocked_accounts", sa.Integer(), nullable=False),
        sa.Column("active_24h_accounts", sa.Integer(), nullable=False),
        sa.Column("active_7d_accounts", sa.Integer(), nullable=False),
        sa.Column("active_30d_accounts", sa.Integer(), nullable=False),
        # When the ROW was written, which differs from taken_at by the duration of the job,
        # exactly as purge_runs separates ran_at from created_at. Unindexed.
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_user_activity_snapshots")),
        sa.UniqueConstraint("snapshot_date", name=op.f("uq_user_activity_snapshots_snapshot_date")),
    )


def downgrade() -> None:
    op.drop_table(_TABLE)
