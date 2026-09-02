"""Add the composite indexes the admin read layer's list queries need.

Revision ID: 0009
Revises: 0008
Create Date: 2026-08-30

Four indexes, no columns, no tables. Each one exists because a specific query in
``src/hbd/db/admin`` would otherwise scan a table that only grows, and each is justified
below by that query — *and verified against Postgres*, not against SQLite, whose planner
is much readier to take a composite index than Postgres is.

Nothing here is speculative: there is no ``ix_orders_delivered_at``,
even though §5.11 sketches one, because the latency metric filters
``delivered_at IS NOT NULL`` *inside* a ``created_at`` window and is already served by
``ix_orders_created_at`` — an index on a column used only for a NOT NULL test would be
pure write cost. The same reasoning keeps ``generation_attempts.name_candidate_strategy``
off this list: ``ix_generation_attempts_tuning`` already leads with it.

**The leading column is the filter, then ``created_at``, then ``id``.** Every admin list
endpoint is keyset-paginated on ``(created_at DESC, id DESC)`` (``hbd.db.admin.page``), so
the shape each query wants is "seek into one filter value, then walk backwards through
time". ``id`` is the third column because without it the trailing sort term is not covered
and every page plan carries a sort node — Postgres ``Incremental Sort … Presorted Key:
created_at``, SQLite ``USE TEMP B-TREE FOR LAST TERM OF ORDER BY``. It costs one column on
indexes that are being created anyway and removes the sort outright.

**What each index serves**

* ``ix_orders_state_created_at`` — ``orders.list_orders`` with a ``state[]`` filter
  (``WHERE state IN (…) AND (created_at, id) < (…) ORDER BY created_at DESC``), which is
  the failure triage page an operator lives on; and ``metrics.delivery_outcome`` /
  ``metrics.orders_per_day``, which count by state inside a window.
* ``ix_orders_telegram_user_id_created_at`` — ``orders.list_orders`` filtered to one
  customer and ``GET /users/{telegramUserId}/orders``, plus ``users._rollups``, which takes
  ``MIN``/``MAX``/``COUNT`` of ``created_at`` grouped by ``telegram_user_id`` for every user
  on a page. The existing single-column index finds the rows; this one hands them over
  already ordered, which is what the ``MAX`` and the keyset walk both want.
* ``ix_generation_attempts_error_code_created_at`` — ``attempts.list_attempts`` filtered to
  ONE error code, and only when that code is rare. It is deliberately **not** claimed for
  ``metrics.failure_breakdown``: that query supplies no equality predicate on the leading
  column (it filters ``is_success`` and ``created_at`` and groups by ``error_code``), so a
  ``(error_code, …)`` b-tree has no usable range and Postgres never picks it, not even with
  ``enable_seqscan=off``. The earlier docstring claimed it did.
* ``ix_generation_attempts_failures_created_at`` — the index
  ``metrics.failure_breakdown`` actually wants: ``created_at`` leading, partial on
  ``is_success = false``, which is the query's own predicate. Without it the failure panel
  was a full scan of an only-grows table on every dashboard refresh.
* ``ix_generation_attempts_provider_created_at`` — ``attempts.list_attempts`` filtered by
  vendor, the query asked when one provider starts failing and the question is whether it
  is only that one. Selective values only, same caveat as the error code.

**What is deliberately absent.** There is no ``(kind, created_at)``. ``kind`` has four
values, so a single-kind filter selects roughly a quarter of the table and Postgres walks
``ix_generation_attempts_created_at`` backwards with a filter instead — it refuses the
composite even with ``enable_seqscan=off``, so it is not a costing preference that better
statistics would fix. On the second-largest, only-grows table in the schema that index was
pure write cost, which is exactly what this file's own rule forbids. It shipped because the
unit suite runs on SQLite, whose planner does take it.

**Locking.** ``CREATE INDEX`` takes a ``SHARE`` lock on Postgres, blocking writes to the
table for the duration. At current row counts that is milliseconds; if this ever runs
against a table large enough to matter, re-run it as ``CREATE INDEX CONCURRENTLY`` outside
a transaction — which Alembic cannot do inside its migration transaction, so it would be a
hand-run change and a stamp, not an edit to this file.

**They are declared on the models, and created here.** ``__table_args__`` on ``OrderRow``
and ``GenerationAttemptRow`` carries the same declarations, so
``Base.metadata.create_all`` — which is how the unit suite and the admin container's schema
shortcut build a database — produces the same indexes the migration chain does. The earlier
version declared them only here, which meant every unit test and every ``create_all``
environment exercised query plans production would not have. That divergence is how three
of the five original indexes reached review without anyone noticing Postgres never chose
them.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Final

from alembic import op

revision: str = "0009"
down_revision: str | None = "0008"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None

_ORDERS = "orders"
_ATTEMPTS = "generation_attempts"

#: ``(index name, table, columns)``. A list rather than five call pairs so ``upgrade`` and
#: ``downgrade`` cannot drift — a downgrade that forgets one index leaves the database in a
#: state no revision describes.
_INDEXES: tuple[tuple[str, str, list[str]], ...] = (
    ("ix_orders_state_created_at", _ORDERS, ["state", "created_at", "id"]),
    ("ix_orders_telegram_user_id_created_at", _ORDERS, ["telegram_user_id", "created_at", "id"]),
    (
        "ix_generation_attempts_error_code_created_at",
        _ATTEMPTS,
        ["error_code", "created_at", "id"],
    ),
    ("ix_generation_attempts_provider_created_at", _ATTEMPTS, ["provider", "created_at", "id"]),
)

#: The partial index, kept out of ``_INDEXES`` because its ``WHERE`` clause is spelled
#: differently per dialect — SQLite has no ``false`` literal.
_FAILURES_INDEX: Final[str] = "ix_generation_attempts_failures_created_at"


def _failure_predicate() -> str:
    return "is_success = false" if op.get_bind().dialect.name == "postgresql" else "is_success = 0"


def upgrade() -> None:
    for name, table, columns in _INDEXES:
        # ``op.f`` marks the name as already following NAMING_CONVENTION, so Alembic does not
        # apply the convention a second time and produce ``ix_orders_ix_orders_…``.
        op.create_index(op.f(name), table, columns, unique=False)
    op.execute(
        f"CREATE INDEX {_FAILURES_INDEX} ON {_ATTEMPTS} (created_at) "
        f"WHERE {_failure_predicate()}"
    )


def downgrade() -> None:
    op.execute(f"DROP INDEX IF EXISTS {_FAILURES_INDEX}")
    for name, table, _ in reversed(_INDEXES):
        op.drop_index(op.f(name), table_name=table)
