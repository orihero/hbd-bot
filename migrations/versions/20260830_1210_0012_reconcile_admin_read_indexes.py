"""Bring an already-migrated database onto revision 0009's corrected index set.

Revision ID: 0012
Revises: 0011
Create Date: 2026-08-30

Revision 0009 was corrected in place — it is an unreleased revision on a feature branch, and
leaving a known-wrong index set in the chain for the sake of history is a trade nobody wants.
A database migrated from scratch therefore never builds the wrong indexes. This revision is
for the databases that already ran the original 0009, and it is a no-op on every other.

Three corrections, all verified with ``EXPLAIN`` against Postgres 16 rather than SQLite:

* ``ix_generation_attempts_kind_created_at`` is **dropped**. ``kind`` has four values, so a
  single-kind filter selects about a quarter of the table; Postgres walks
  ``ix_generation_attempts_created_at`` backwards with a filter instead and refuses the
  composite even with ``enable_seqscan=off``. It was pure write cost on the second-largest,
  only-grows table in the schema.
* The three surviving composites gain ``id`` as a trailing column. The keyset order is
  ``(created_at DESC, id DESC)`` and ``id`` was in no index, so every list page carried a
  runtime sort for its last term.
* A partial ``(created_at) WHERE is_success = false`` is added for
  ``metrics.failure_breakdown``, which the ``(error_code, created_at)`` index was justified
  by and could never serve: that query supplies no equality predicate on ``error_code``.

Everything is spelled with ``IF EXISTS`` / ``IF NOT EXISTS`` and raw SQL rather than
``op.create_index``, because this revision must be idempotent against three different
starting states: the original 0009, the corrected 0009, and a ``create_all`` schema. Both
Postgres and SQLite support both forms.

**The downgrade really reverses this revision**, back to the index set the original 0009
built: two-column composites, the ``kind`` index restored, the partial index removed. It
would have been easy to leave ``downgrade`` empty and argue that un-reconciling is not
something anyone wants — but an empty body is indistinguishable from a forgotten one, and
the repo's own guard against stub downgrades only greps for the literal ``pass``, so an
empty-but-documented body would slip past it. A revision that cannot be reversed is a
revision nobody can safely apply.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Final

from alembic import op

revision: str = "0012"
down_revision: str | None = "0011"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None

_ORDERS: Final[str] = "orders"
_ATTEMPTS: Final[str] = "generation_attempts"

#: ``(name, table, columns)`` for the index dropped outright — see the module docstring. The
#: column list is kept so ``downgrade`` can put back exactly what was there.
_RETIRED: Final[tuple[tuple[str, str, str], ...]] = (
    ("ix_generation_attempts_kind_created_at", "generation_attempts", "kind, created_at"),
)

#: ``(name, table, columns)`` in their corrected form. Dropped and recreated rather than
#: created conditionally: an index that already exists under the same name with the OLD
#: column list would survive a plain ``CREATE INDEX IF NOT EXISTS``, which is the one
#: outcome this revision exists to prevent.
_RESHAPED: Final[tuple[tuple[str, str, str], ...]] = (
    ("ix_orders_state_created_at", _ORDERS, "state, created_at, id"),
    ("ix_orders_telegram_user_id_created_at", _ORDERS, "telegram_user_id, created_at, id"),
    (
        "ix_generation_attempts_error_code_created_at",
        _ATTEMPTS,
        "error_code, created_at, id",
    ),
    ("ix_generation_attempts_provider_created_at", _ATTEMPTS, "provider, created_at, id"),
)

_FAILURES_INDEX: Final[str] = "ix_generation_attempts_failures_created_at"


def _failure_predicate() -> str:
    """SQLite has no ``false`` literal; the column is stored as 0/1 there."""
    return "is_success = false" if op.get_bind().dialect.name == "postgresql" else "is_success = 0"


def upgrade() -> None:
    for name, _, _ in _RETIRED:
        op.execute(f"DROP INDEX IF EXISTS {name}")
    for name, table, columns in _RESHAPED:
        op.execute(f"DROP INDEX IF EXISTS {name}")
        op.execute(f"CREATE INDEX {name} ON {table} ({columns})")
    op.execute(f"DROP INDEX IF EXISTS {_FAILURES_INDEX}")
    op.execute(
        f"CREATE INDEX {_FAILURES_INDEX} ON {_ATTEMPTS} (created_at) "
        f"WHERE {_failure_predicate()}"
    )


def downgrade() -> None:
    """Rebuild the index set the original 0009 created, exactly."""
    op.execute(f"DROP INDEX IF EXISTS {_FAILURES_INDEX}")
    for name, table, columns in _RESHAPED:
        op.execute(f"DROP INDEX IF EXISTS {name}")
        # The original shape: the same columns without the trailing ``id``.
        original = ", ".join(columns.split(", ")[:-1])
        op.execute(f"CREATE INDEX {name} ON {table} ({original})")
    for name, table, columns in _RETIRED:
        op.execute(f"DROP INDEX IF EXISTS {name}")
        op.execute(f"CREATE INDEX {name} ON {table} ({columns})")
