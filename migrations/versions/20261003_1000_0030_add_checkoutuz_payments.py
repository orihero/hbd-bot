"""Add checkoutuz_payments: every payment link checkout.uz minted for one of our intents.

Revision ID: 0030
Revises: 0029
Create Date: 2026-10-03

One new table and no change to any existing one. See ``DECISIONS.md D28`` for the rail and
``bayram.db.models.checkoutuz_payment`` for the argument behind every column; what belongs
HERE is the part a migration is responsible for.

**A side table, not columns on ``payment_intents``.** A checkout.uz link lives an hour and an
intent twelve, so one intent accumulates links. Replacing a column in place when a link
lapsed would forget the old order id, and a page left open and paid late would then arrive as
an order nobody recognises — money taken, nothing granted. One row per link keeps every order
id pollable.

**``order_id`` is the primary key and is THEIRS** — checkout.uz's integer ``_id`` — so it is
created without autoincrement. A ``BigInteger`` because it is theirs to grow.

**The one foreign key in the payment area**, to ``payment_intents.id`` with ``ON DELETE
RESTRICT``. The Payme tables refuse one because their rows share a commit with the intent;
this row is written in a LATER transaction, after an HTTP call, so there is no shared commit to
lean on. RESTRICT, never CASCADE: the only delete of an intent is the 400-day sweep of terminal
intents, and an ``expired`` intent can sit behind an ``orphan_paid`` link — the only record of
a refund owed. The sweep skips such intents and deletes the other links child-first; RESTRICT
makes any other path fail rather than take the money record with it.

**``link_valid_until``, not ``link_expires_at``.** The ``expires_at`` suffix enlists a column in
the retention inventory ``tests/test_db/test_audit_retention.py`` enforces; this is a business
clock, named as ``payment_intents.valid_until`` is.

**Index names are spelled out**, both the templated ones (through ``batch_op.f``, as every
revision since 0023 does) and the one composite, which is hand-named in the model's
``__table_args__``: ``test_the_migrated_indexes_match_the_model_metadata`` compares NAMES.

**Branch note.** ``feat/media-products`` carries its own 0029–0033 and already clashes with this
branch's 0029. This revision chains onto this branch's 0029; whichever branch merges second
re-chains, and ``test_exactly_one_migration_head_exists`` is what will say so.

**The downgrade drops the table**, and is safe only once nothing is mid-payment through
checkout.uz: a dropped row is an order id the poller can no longer ask about. Turn
``BAYRAM_CHECKOUTUZ_ENABLED`` off, wait out the link lifetime plus the poller's grace window,
then downgrade.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0030"
down_revision: str | None = "0029"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLE = "checkoutuz_payments"

#: Literal widths rather than the model's constants: **no migration in this project imports
#: application code** (``test_no_migration_imports_application_code``), because a revision that
#: already ran everywhere must keep meaning what it meant.
_PAYMENT_UUID_LENGTH = 64
_PAY_URL_LENGTH = 512
_STATE_LENGTH = 16

#: ``(column, unique)``, created through ``batch_op.f()`` so they take the templated names
#: ``create_all`` derives from the model's ``index=True``.
_INDEXES: tuple[tuple[str, bool], ...] = (
    ("intent_id", False),
    ("created_at", False),
)
#: Hand-named in the model's ``__table_args__``; spelled identically here.
_STATE_VALID_UNTIL_INDEX = "ix_checkoutuz_payments_state_valid_until"


def upgrade() -> None:
    op.create_table(
        _TABLE,
        sa.Column("order_id", sa.BigInteger(), autoincrement=False, nullable=False),
        sa.Column("intent_id", sa.Uuid(), nullable=False),
        sa.Column("payment_uuid", sa.String(length=_PAYMENT_UUID_LENGTH), nullable=False),
        sa.Column("pay_url", sa.String(length=_PAY_URL_LENGTH), nullable=False),
        # ``_pay_via`` as ``[[method, url], ...]``; display-only, NULL when none was sent.
        sa.Column("pay_via", sa.JSON(), nullable=True),
        sa.Column("amount_som", sa.Integer(), nullable=False),
        # Literal values, not a rendered enum class: the column outlives the Python class.
        sa.Column(
            "state",
            sa.Enum(
                "pending",
                "paid",
                "expired",
                "orphan_paid",
                name="checkoutuzpaymentstate",
                native_enum=False,
                length=_STATE_LENGTH,
            ),
            nullable=False,
        ),
        # Plain timezone-aware DateTime, never UtcDateTime — see the note on application code.
        sa.Column("link_valid_until", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_polled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("paid_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("amount_som > 0", name=op.f("ck_checkoutuz_payments_amount_positive")),
        sa.ForeignKeyConstraint(
            ["intent_id"],
            ["payment_intents.id"],
            name=op.f("fk_checkoutuz_payments_intent_id_payment_intents"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("order_id", name=op.f("pk_checkoutuz_payments")),
    )

    # SQLite cannot ALTER an existing table to add an index without a rebuild, so every index
    # in this project is created inside batch_alter_table (render_as_batch=True).
    with op.batch_alter_table(_TABLE, schema=None) as batch_op:
        for column, unique in _INDEXES:
            batch_op.create_index(batch_op.f(f"ix_{_TABLE}_{column}"), [column], unique=unique)
        batch_op.create_index(_STATE_VALID_UNTIL_INDEX, ["state", "link_valid_until"], unique=False)


def downgrade() -> None:
    with op.batch_alter_table(_TABLE, schema=None) as batch_op:
        batch_op.drop_index(_STATE_VALID_UNTIL_INDEX)
        for column, _ in reversed(_INDEXES):
            batch_op.drop_index(batch_op.f(f"ix_{_TABLE}_{column}"))

    op.drop_table(_TABLE)
