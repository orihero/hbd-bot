"""Index the two settlement clocks: payment_intents.settled_at, payme_transactions.perform_time.

Revision ID: 0025
Revises: 0024
Create Date: 2026-09-10

Revision 0023 created the rail's three tables and indexed every column that had a reader:
``public_ref`` and ``idempotency_key`` (the two unique joins), ``telegram_user_id`` (erasure),
``created_at`` (the lists), ``payme_time`` (the twelve-hour timeout), and the two hand-named
composites the expiry and stale-transaction sweeps ride. It deliberately indexed neither
SETTLEMENT clock, and that was correct at the time: nothing read them except
``payme_sql.settlement_counts``, which ran once every five minutes from a worker whose latency
nobody watches.

**What changed is who asks.** The admin panel's rail board recomputes the same three-way
invariant — ``transactions_performed + operator_settlements == receipts_written`` — on every
load of a screen that polls, and adds a fourth count (``settle_note LIKE 'operator:%'``) that
filters ``settled_at`` as well. Those are the only two columns in the whole identity, they sit
on the two fastest-growing tables on the payment path, and unindexed each request is two full
scans. A dashboard card that costs a table scan is a card somebody eventually removes.

**Both columns are highly selective, which is why an index pays for itself twice over.**
``settled_at`` is NULL for every intent nobody paid — most of them, since opening a payment page
and closing it is the commonest thing a customer does with one — and ``perform_time`` is NULL
for every transaction that was created and then cancelled. So each index is small relative to
its table and the range scan it enables replaces a scan of rows that could never have matched.

**Why plain single-column indexes and not composites.** The obvious alternative is
``(state, settled_at)``, mirroring ``ix_payment_intents_state_valid_until``. It was rejected:
the settlement predicates always name ``settled_at`` and only sometimes name ``state``, the
window is by far the more selective term once ``settled_at IS NOT NULL`` has excluded the
unpaid, and a composite leading with a five-valued column would be the wider index for the
narrower set of queries. ``ix_payment_intents_state_valid_until`` leads with ``state`` because
its query is an equality on ``pending`` — a different shape entirely.

**No data changes and no backfill.** Two ``CREATE INDEX`` statements and their two drops. The
downgrade is exact, so this revision is safe to roll back with the panel still deployed: the
queries keep answering, more slowly.

Spelled identically to ``index=True`` in ``models/payment_intent.py`` and
``models/payme_transaction.py``, because ``test_the_migrated_indexes_match_the_model_metadata``
compares index NAMES — a migration-only index is one ``create_all`` does not build, so the whole
unit suite would run against a query plan production never has.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0025"
down_revision: str | None = "0024"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_INTENTS = "payment_intents"
_TRANSACTIONS = "payme_transactions"

#: The column each table gains an index on. Templated through ``batch_op.f()`` so both take
#: ``NAMING_CONVENTION``'s ``ix`` shape and match the models' ``index=True`` declarations —
#: hand-naming would be a second spelling of a name a test compares.
_INTENT_SETTLED_COLUMN = "settled_at"
_TRANSACTION_PERFORM_COLUMN = "perform_time"


def upgrade() -> None:
    # SQLite cannot ALTER an existing table to add an index without a rebuild, so every index
    # in this project is created inside batch_alter_table (render_as_batch=True).
    with op.batch_alter_table(_INTENTS, schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f(f"ix_{_INTENTS}_{_INTENT_SETTLED_COLUMN}"),
            [_INTENT_SETTLED_COLUMN],
            unique=False,
        )

    with op.batch_alter_table(_TRANSACTIONS, schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f(f"ix_{_TRANSACTIONS}_{_TRANSACTION_PERFORM_COLUMN}"),
            [_TRANSACTION_PERFORM_COLUMN],
            unique=False,
        )


def downgrade() -> None:
    with op.batch_alter_table(_TRANSACTIONS, schema=None) as batch_op:
        batch_op.drop_index(batch_op.f(f"ix_{_TRANSACTIONS}_{_TRANSACTION_PERFORM_COLUMN}"))

    with op.batch_alter_table(_INTENTS, schema=None) as batch_op:
        batch_op.drop_index(batch_op.f(f"ix_{_INTENTS}_{_INTENT_SETTLED_COLUMN}"))
