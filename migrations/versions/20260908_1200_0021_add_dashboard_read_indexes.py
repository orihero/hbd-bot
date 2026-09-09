"""Add the two indexes the dashboard's aggregates read on.

Revision ID: 0021
Revises: 0020
Create Date: 2026-09-08

Two indexes, no columns, no tables — revision 0009's shape exactly, and this revision is
best read beside it, because it OVERTURNS one of that revision's stated refusals.

**IT OVERTURNS 0009 BY NAME, and the reversal is legitimate because the query changed.**
0009's docstring says, in prose: "there is no ``ix_orders_delivered_at``, even though §5.11
sketches one, because the latency metric filters ``delivered_at IS NOT NULL`` *inside* a
``created_at`` window and is already served by ``ix_orders_created_at`` — an index on a
column used only for a NOT NULL test would be pure write cost." That was true of the only
query that then existed. It is void now: the dashboard's throughput series, its
songs-delivered count, its delivered-cohort latency percentiles and the outer leg of its
cost-per-song join all put a half-open RANGE predicate on ``delivered_at``
(``>= from AND < to``), which is precisely what a b-tree serves and what a ``NOT NULL`` test
is not. This is written down rather than left implicit because otherwise the chain holds two
docstrings that appear to argue with each other, and the next reader deletes one of them.

**WHICH QUERY EACH INDEX EARNS ITS KEEP ON.**

``ix_orders_delivered_at`` — the throughput series (``GROUP BY`` a UTC day of
``delivered_at`` over a window), the delivered count, the delivered-cohort latency
percentiles, and the outer leg of the cost-per-song join (range-scan ``orders`` on
``delivered_at``, nested-loop into ``ix_vendor_usage_order_id``). Without it every one of
those is a sequential scan of the only-ever-growing ``orders`` table, on a screen that polls.
``ix_orders_created_at`` cannot serve them — the predicate is on a different column — and
``ix_orders_state_created_at`` leads with ``state``, so a ``created_at`` range against it is
at best a full index scan and a ``delivered_at`` range is not expressible against it at all.
The column is safe to range-scan alone, without a ``state = 'delivered'`` predicate beside
it, because ``delivered_at`` has exactly ONE writer — ``repository.set_state``, only under
``state is OrderState.DELIVERED`` — and is never cleared, so the column IS the delivery
event and the extra predicate could only cost a heap fetch.

``ix_users_last_seen_at`` — the active-accounts aggregate, ONE query whose predicate is
``WHERE last_seen_at >= now - 30d`` with the 7-day and 1-day cutoffs taken as conditional
counts inside it. **The index is earned by that WHERE clause and by nothing else**: the
obvious refactor — three bare cutoff counts and no predicate at all — scans ``users`` end to
end however it is indexed, which is exactly the failure 0009's own docstring is a post-mortem
of. Narrowing to the widest cutoff first is what turns the tile into a range scan over the
active tail instead of a scan of every account that ever said hello.

**THE WRITE COST, STATED HONESTLY AND THEN BOUNDED.** ``credits.touch`` UPSERTs
``last_seen_at`` from the inbound Telegram path, so this is an index on the hottest-written
column in the schema, and on Postgres an UPDATE that moves an indexed column loses
HOT-update eligibility: each touch now also writes a b-tree entry and leaves a dead one. What
makes it affordable already exists in the tree — ``TouchDrain`` (``src/hbd/bot/gate.py``)
coalesces to ONE upsert per account per MINUTE, because "a minute is the resolution
``last_seen_at`` is actually read at" — so the index takes at most one entry per active
account per minute, against a polled dashboard query it saves a full scan on. If that
coalescer is ever removed or its interval shortened, this index must be re-argued from
scratch.

**PLAIN, NOT PARTIAL.** A partial ``WHERE delivered_at IS NOT NULL`` would be smaller and
would skip the NULL entry every DRAFT insert writes. It is refused for 0016's already-recorded
reason — SQLite and Postgres both accept partial indexes but they do not round-trip
identically through ``inspector.get_indexes``, and
``test_the_migrated_indexes_match_the_model_metadata`` compares migrated schema against model
metadata for a living — and for a second one: 0009's own partial failures index is raw SQL
declared on NO model, so ``create_all`` (the unit suite, the admin container's schema
shortcut) never builds it, which is the exact divergence 0009's last paragraph is an apology
for. A plain index declared with ``index=True`` is built by both paths and needs no
dialect-specific ``_where`` kwarg.

**DDL ON ``users`` IS NOT THE DDL THAT WAS FROZEN.** ``UserRow``'s docstring cites
ADMIN_PANEL_PLAN §5.11's "no DDL on this table", written about a mutable money counter on the
one row the erasure design keeps alive after ``/forget``. An index adds no column, changes no
row's meaning, and leaves "survives erasure, content erasable" exactly as it was. (Revision
0017 does add a column there, deliberately and with its own argument; this revision does not.)
Nor is indexing ``last_seen_at`` permission to expose it: that column is withheld from every
per-row ``/users`` projection so an operator cannot watch one customer minute by minute, and
the read this index serves is an AGGREGATE and only an aggregate.

**LOCKING.** The same paragraph 0009 carries: ``CREATE INDEX`` takes a SHARE lock on
Postgres, which is milliseconds at current row counts. If it ever matters, re-run as
``CREATE INDEX CONCURRENTLY`` by hand plus a stamp — Alembic cannot do that inside its
transaction.

**NO PRIVACY CLASSIFICATION IS DUE.** No table is created and no column is added, so
``tests/test_db/test_privacy_constraints.py``'s two sets are untouched and no
``*_expires_at`` column is introduced. Stated in one line so nobody goes looking for the
classification ``vendor_usage`` needed.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0021"
down_revision: str | None = "0020"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

#: ``(table, column)`` for each index. Both plain, non-unique, single-column, created
#: through ``batch_op.f()`` so they take ``NAMING_CONVENTION``'s ``ix`` template and match
#: what each model's ``index=True`` declares.
_INDEXES: tuple[tuple[str, str], ...] = (
    ("orders", "delivered_at"),
    ("users", "last_seen_at"),
)


def upgrade() -> None:
    for table, column in _INDEXES:
        # Batch mode: SQLite cannot ALTER an existing table to add an index without a
        # rebuild, and render_as_batch=True is how every index in this chain is made.
        with op.batch_alter_table(table, schema=None) as batch_op:
            batch_op.create_index(batch_op.f(f"ix_{table}_{column}"), [column], unique=False)


def downgrade() -> None:
    for table, column in reversed(_INDEXES):
        with op.batch_alter_table(table, schema=None) as batch_op:
            batch_op.drop_index(batch_op.f(f"ix_{table}_{column}"))
