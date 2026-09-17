"""Add credit_accounts and credit_ledger.

Revision ID: 0006
Revises: 0005
Create Date: 2026-08-30

The render gate needs somewhere to keep what a customer is entitled to and a record of how
it got that way. Both tables land in one revision because neither is usable alone: the
balance in ``credit_accounts`` is only trustworthy if every movement that produced it is in
``credit_ledger``, and a ledger with no account has nothing to authorise a render against.

Three things here are correctness decisions rather than schema taste:

* ``credit_accounts.telegram_user_id`` is a NATURAL primary key with
  ``autoincrement=False``. SQLAlchemy treats an Integer-family primary key as
  autoincrementing by default, which on SQLite would make the column a ROWID alias and
  renumber an insert that supplied Telegram's own id. There is deliberately no foreign key
  to ``users``: that row is written only by ``_ensure_user`` from ``_create_order``, so the
  people the gate must open an account for are exactly the ones who have no ``users`` row.
* ``ck_credit_accounts_balance_not_negative`` is the second layer under the conditional
  ``UPDATE … WHERE balance >= :cost`` that every debit runs. If a writer ever omits that
  predicate the row refuses rather than going quietly negative and rendering free songs.
* ``ck_credit_ledger_delta_matches_kind`` pins the sign of every movement to its kind, and
  pins ``consume`` to exactly zero. A ``consume`` that moved the balance would desynchronise
  ``credit_accounts.balance`` from ``SUM(credit_ledger.delta)`` with no other symptom.
* ``credit_ledger.telegram_user_id`` is NULLABLE, which is not a data-quality lapse: it is
  the only shape in which ``/forget`` can be honoured against an append-only table. The
  erasure nulls the column and keeps the row, so the anonymous aggregate still answers a
  billing question while nothing in it is about a person any more. Note that
  ``idempotency_key`` deliberately keeps the id it was built from — that is what stops a
  ``/forget`` from re-opening an allowance that has already been minted.

``uq``-style uniqueness on ``idempotency_key`` is expressed as a UNIQUE INDEX rather than a
UNIQUE constraint because it is also the lookup key on the write path, exactly like
``admin_sessions.token_sha256`` in ``0005``.

Both enums are spelled out as non-native ``VARCHAR``s rather than imported from
``bayram.db.enums``: migrations must not import application code (a test asserts it), and a
native Postgres enum would make every later member a lock-taking ``ALTER TYPE``.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None

_ACCOUNTS = "credit_accounts"
_LEDGER = "credit_ledger"

#: Matches ``bayram.db.models.credit_ledger._DELTA_MATCHES_KIND``, spelled literally because a
#: migration must keep working after the enum it mirrors is refactored or deleted.
_DELTA_MATCHES_KIND = (
    "(kind IN ('grant', 'refund') AND delta > 0)"
    " OR (kind = 'debit' AND delta < 0)"
    " OR (kind = 'consume' AND delta = 0)"
)


def upgrade() -> None:
    op.create_table(
        _ACCOUNTS,
        sa.Column("telegram_user_id", sa.BigInteger(), autoincrement=False, nullable=False),
        sa.Column("balance", sa.Integer(), nullable=False),
        sa.Column("lifetime_granted", sa.Integer(), nullable=False),
        sa.Column("allowance_period_index", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("balance >= 0", name=op.f("ck_credit_accounts_balance_not_negative")),
        sa.PrimaryKeyConstraint("telegram_user_id", name=op.f("pk_credit_accounts")),
    )
    with op.batch_alter_table(_ACCOUNTS, schema=None) as batch_op:
        # TimestampMixin indexes created_at on every table that uses it; omitting it here
        # would make the migrated schema and Base.metadata disagree.
        batch_op.create_index(
            batch_op.f("ix_credit_accounts_created_at"), ["created_at"], unique=False
        )

    op.create_table(
        _LEDGER,
        sa.Column("id", sa.Uuid(), nullable=False),
        # Nullable only so that erasure has somewhere to go: every writer supplies an id,
        # and a NULL means `/forget` ran and stripped this row of its owner while leaving
        # the movement itself behind. See `bayram.db.credit_erasure.forget_account`.
        sa.Column("telegram_user_id", sa.BigInteger(), nullable=True),
        sa.Column(
            "kind",
            sa.Enum(
                "grant",
                "debit",
                "refund",
                "consume",
                name="creditentrykind",
                native_enum=False,
                length=32,
            ),
            nullable=False,
        ),
        sa.Column(
            "reason",
            sa.Enum(
                "signup_allowance",
                "period_allowance",
                "admin_grant",
                "order_render",
                "order_failed",
                "order_delivered",
                "order_not_delivered",
                "stale_settlement",
                name="creditreason",
                native_enum=False,
                length=32,
            ),
            nullable=False,
        ),
        sa.Column("delta", sa.Integer(), nullable=False),
        sa.Column("order_id", sa.Uuid(), nullable=True),
        sa.Column("generation", sa.Integer(), nullable=False),
        sa.Column("idempotency_key", sa.String(length=128), nullable=False),
        sa.Column("actor", sa.String(length=32), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(_DELTA_MATCHES_KIND, name=op.f("ck_credit_ledger_delta_matches_kind")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_credit_ledger")),
    )
    with op.batch_alter_table(_LEDGER, schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_credit_ledger_created_at"), ["created_at"], unique=False
        )
        # UNIQUE, and an index rather than a constraint: this is the lookup key the writer
        # probes before it inserts, and the thing that makes two racing writers of the same
        # movement produce one row instead of two.
        batch_op.create_index(
            batch_op.f("ix_credit_ledger_idempotency_key"), ["idempotency_key"], unique=True
        )
        batch_op.create_index(batch_op.f("ix_credit_ledger_order_id"), ["order_id"], unique=False)
        batch_op.create_index(
            batch_op.f("ix_credit_ledger_telegram_user_id"), ["telegram_user_id"], unique=False
        )
        # Hand-named: the naming convention would render this as
        # ix_credit_ledger_telegram_user_id_created_at, and one account's history read
        # newest-first needs both columns in one index or it sorts a full scan.
        batch_op.create_index(
            "ix_credit_ledger_user_created", ["telegram_user_id", "created_at"], unique=False
        )


def downgrade() -> None:
    # Ledger first: it is the child fact, and dropping the account table while the history
    # explaining it still exists would leave a ledger nothing can be reconciled against.
    with op.batch_alter_table(_LEDGER, schema=None) as batch_op:
        batch_op.drop_index("ix_credit_ledger_user_created")
        batch_op.drop_index(batch_op.f("ix_credit_ledger_telegram_user_id"))
        batch_op.drop_index(batch_op.f("ix_credit_ledger_order_id"))
        batch_op.drop_index(batch_op.f("ix_credit_ledger_idempotency_key"))
        batch_op.drop_index(batch_op.f("ix_credit_ledger_created_at"))

    op.drop_table(_LEDGER)

    with op.batch_alter_table(_ACCOUNTS, schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_credit_accounts_created_at"))

    op.drop_table(_ACCOUNTS)
