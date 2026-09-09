"""Add plan_purchases.

Revision ID: 0015
Revises: 0014
Create Date: 2026-09-06

The bot now sells. One song costs 7 000 soʻm and the starter plan costs 49 000 soʻm for
twelve songs in thirty days, and this table is where a bought plan lives.

**Why a table at all, rather than twelve credits on the balance.** The obvious shape — grant
``songs_included`` credits the moment the plan is paid for — cannot express "and they are
gone in thirty days". ``credit_accounts.balance`` (revision 0006) is a single fungible
scalar with NO lot structure, and ``credit_accounts.balance == SUM(credit_ledger.delta)`` is
an invariant the suite asserts after every operation, so expiring unused plan songs would
mean a sweep writing a compensating DEBIT — and with no lots that sweep could only GUESS
whether it was burning plan money or a 7 000 soʻm top-up the customer paid cash for. It
would guess wrong for exactly the customers who bought both. So nothing is granted up front:
``hbd.db.credits._mint_plan_song`` takes ONE song out of a row in this table inside the
render debit's own transaction, guarded by ``UPDATE … WHERE songs_used = :seen``, exactly
the way the rolling allowance has always been minted. Use-it-or-lose-it becomes a read-time
predicate on ``plan_ends_at``, and there is nothing to claw back, ever.

**The personal-data checklist item, head on.** ``telegram_user_id`` IS personal data, and it
is ``nullable=True`` for precisely that reason: ``hbd.db.credit_erasure.forget_account`` is
this table's erasure branch and it NULLs the column rather than deleting the row, following
``credit_ledger`` (0006) exactly. A receipt is an audit fact — it answers "was this customer
charged for songs that never arrived?" months later, including for a dispute the customer
themselves raises — so deleting it would make ``/forget`` mean "refund me" and would destroy
that answer for everyone. There is therefore no ``*_expires_at`` on this table and no branch
in ``hbd.db.purge``: the identity comes off on request, the anonymous aggregate stays, and
``tests/test_db/test_privacy_constraints.py`` is satisfied the same way it already is by
``credit_accounts`` and ``credit_ledger``.

**The business clock is ``plan_ends_at``, and the name is a decision.** The ``*_expires_at``
suffix is reserved for RETENTION clocks: ``tests/test_db/test_audit_retention.py`` derives
"every clock in the schema is read by a sweep" from that suffix alone. A plan's end date is
read by the two plan queries and by nothing else, so naming it ``plan_expires_at`` would
demand a retention branch for a date whose entire point is that nothing ever collects it.

**``CreditReason`` gains two members in this revision and there is no DDL for them.**
``TOPUP_PURCHASE`` and ``PLAN_SONG`` are stored through ``hbd.db.base.enum_type``, which
renders ``sa.Enum(..., native_enum=False, length=32)`` — a plain ``VARCHAR(32)`` with
``create_constraint`` off — so the set of legal values is enforced in the mapper and nowhere
in the database. That is not new and is not an oversight: it is why ``UNENFORCED_RENDER``
already exists in the enum while being absent from 0006's literal reason list. The same
property is what lets ``plan`` below be spelled as a literal one-member enum here and gain a
second plan later without a migration.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0015"
down_revision: str | None = "0014"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLE = "plan_purchases"

#: The composite index the two plan reads bound on. Hand-named, unlike every other
#: constraint here, because ``NAMING_CONVENTION``'s ``ix`` template would render it
#: ``ix_plan_purchases_telegram_user_id_plan_ends_at`` — which the model does not declare, so
#: ``test_the_migrated_indexes_match_the_model_metadata`` would report it missing.
_USER_ENDS_INDEX = "ix_plan_purchases_user_ends"


def upgrade() -> None:
    op.create_table(
        _TABLE,
        sa.Column("id", sa.Uuid(), nullable=False),
        # Nullable so that /forget has somewhere to go. See the module docstring.
        sa.Column("telegram_user_id", sa.BigInteger(), nullable=True),
        # Spelled literally rather than imported from hbd.db.enums: a migration that imports
        # application code breaks historically, on a revision that already ran everywhere
        # (tests/test_db/test_migrations.py::test_no_migration_imports_application_code).
        sa.Column(
            "plan",
            sa.Enum("starter", name="plankind", native_enum=False, length=32),
            nullable=False,
        ),
        sa.Column("songs_included", sa.Integer(), nullable=False),
        sa.Column("songs_used", sa.Integer(), nullable=False),
        sa.Column("amount_minor", sa.Integer(), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("provider", sa.String(length=32), nullable=False),
        sa.Column("reference", sa.String(length=64), nullable=False),
        sa.Column("idempotency_key", sa.String(length=128), nullable=False),
        # UtcDateTime renders as a timezone-aware DateTime; env.py exists so our own column
        # types never have to be named here.
        sa.Column("plan_ends_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        # Restated as literal strings mirroring the model. The counter IS the entitlement, so
        # a writer that lost the optimistic guard would hand out a thirteenth song with no
        # other symptom; the database refuses instead.
        sa.CheckConstraint(
            "songs_used >= 0 AND songs_used <= songs_included",
            name=op.f("ck_plan_purchases_songs_used_within_plan"),
        ),
        sa.CheckConstraint(
            "songs_included > 0", name=op.f("ck_plan_purchases_songs_included_positive")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_plan_purchases")),
    )
    with op.batch_alter_table(_TABLE, schema=None) as batch_op:
        # SQLite cannot ALTER an existing table to add an index without a rebuild, so every
        # index in this project is created inside batch_alter_table (render_as_batch=True).
        batch_op.create_index(
            batch_op.f("ix_plan_purchases_telegram_user_id"), ["telegram_user_id"], unique=False
        )
        # Unique, not merely indexed: this is the ONE thing that makes a double tap, a stale
        # message and a redelivered Telegram update collapse into a single plan rather than a
        # second end date written over the one the customer paid for.
        batch_op.create_index(
            batch_op.f("ix_plan_purchases_idempotency_key"), ["idempotency_key"], unique=True
        )
        batch_op.create_index(
            batch_op.f("ix_plan_purchases_plan_ends_at"), ["plan_ends_at"], unique=False
        )
        # TimestampMixin indexes created_at on every table that uses it; omitting it here
        # would make the migrated schema and Base.metadata disagree, which
        # tests/test_db/test_migrations.py compares index by index.
        batch_op.create_index(
            batch_op.f("ix_plan_purchases_created_at"), ["created_at"], unique=False
        )
        batch_op.create_index(_USER_ENDS_INDEX, ["telegram_user_id", "plan_ends_at"], unique=False)


def downgrade() -> None:
    with op.batch_alter_table(_TABLE, schema=None) as batch_op:
        batch_op.drop_index(_USER_ENDS_INDEX)
        batch_op.drop_index(batch_op.f("ix_plan_purchases_created_at"))
        batch_op.drop_index(batch_op.f("ix_plan_purchases_plan_ends_at"))
        batch_op.drop_index(batch_op.f("ix_plan_purchases_idempotency_key"))
        batch_op.drop_index(batch_op.f("ix_plan_purchases_telegram_user_id"))

    op.drop_table(_TABLE)
