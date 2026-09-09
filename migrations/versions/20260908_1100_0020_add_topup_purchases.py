"""Add topup_purchases.

Revision ID: 0020
Revises: 0019
Create Date: 2026-09-08

``hbd.db.purchases._fulfil_single`` writes one ``credit_ledger`` GRANT
(``reason=topup_purchase``, ``delta=+1``) and nothing else. That row carries no amount, no
currency, no provider and no reference: **the price of every single song this product has
ever sold was discarded at the moment of sale**, and ``credit_ledger`` has no money column
to have held it. Meanwhile ``plan_purchases`` — the sibling receipt — records all four. This
revision gives the one-off sale the same receipt the subscription already has.

**WHY A NEW TABLE RATHER THAN MONEY COLUMNS ON ``credit_ledger``.** Putting
``amount_minor``/``currency``/``provider``/``reference`` there is genuinely attractive: the
money would land in the same statement as the entitlement, under the same unique key, with
perfect idempotency for free. Erasure is not the discriminator either — that table is
anonymised rather than deleted, so money on it would outlive ``/forget`` just as a receipt
does. Four reasons defeat it. (1) It makes one table mean two things: ``credit_ledger``'s own
docstring commits it to "one movement of one account's credits", and a money column would be
non-null on ONE ``CreditReason`` in twelve, so the column's meaning would live in a
different column and every future reader summing it would need to know which reasons may
carry it. (2) It cannot record a sale that grants no credit — and the schema has already met
one, since a plan grants nothing at purchase, so revenue would be permanently split between
a receipts table and a movements table at different grains and "total revenue" would be a
hand-aligned UNION forever. (3) It would put four nullable columns and a both-or-neither
CHECK on the hottest table in the entitlement schema, which takes a row per render debit,
per settle and per allowance mint. (4) Refunds: a REFUND row carries ``delta > 0``, so with
money on the ledger a refund either appears to carry money or needs another null, whereas a
receipt has an obvious place for a future ``refunded_at``.

**WHY NOT A ``plan_purchases`` ROW.** ``plan`` is NOT NULL, ``songs_included > 0`` is
CHECKed and ``plan_ends_at`` is NOT NULL — but the decisive objection is behavioural:
``plan_sql.current_plan`` and ``live_plan`` would SEE that row. A top-up would block the sale
of a starter plan for the life of an invented end date, while ``claim_plan_song`` minted a
SECOND song out of a purchase that had already granted a credit directly. A double-grant plus
a refused sale, out of a schema reuse.

**WHY THERE IS NO BACKFILL, AND WHY THERE CAN NEVER BE ONE.** This revision creates an EMPTY
table and touches no history. Past top-ups left only a ledger GRANT with an idempotency key
and a clock; they cannot be back-priced at ``Settings.single_song_price_minor``, because that
is a value read at QUERY time rather than the price that was charged, so every historical
figure would move the next time the price does. That is LR-63's "retrofitting revenue
recognition corrupts every prior reported period", and this codebase already refuses the same
shape twice in the two places nearest to it: revision 0015 stores ``songs_included`` on the
row rather than reading ``starter_plan_songs`` "so a price or package change tomorrow cannot
retroactively shrink a plan somebody already paid for", and revision 0016 leaves ``cost_usd``
NULL rather than 0 because a rate applied after the fact is a fabricated number.

The two states are therefore told apart STRUCTURALLY, never by a null. "Sold before we
recorded amounts" is a ``credit_ledger`` GRANT with ``reason='topup_purchase'`` and NO row
here sharing its ``idempotency_key`` — countable exactly, with a correlated ``NOT EXISTS`` on
the shared key. "Sold for zero" is a row here with ``amount_minor = 0``. Absence of a row,
not a null in one.

**WHY ``amount_minor`` IS NOT NULL WHERE EVERY QUANTITY ON ``vendor_usage`` IS NULLABLE.**
The null-never-zero rule governs columns recording a MEASUREMENT, where a default of 0 turns
"nobody measured this" into "this cost nothing". A sale amount is not a measurement; it is a
TERM OF THE CONTRACT, known to the writer at the instant it writes and supplied verbatim from
``hbd.checkout.Purchase`` (whose own ``amount_minor`` is ``Field(ge=0)``).
``plan_purchases.amount_minor`` is NOT NULL for exactly this reason. ``0`` here is a MEASURED
price and a legal one — ``single_song_price_minor`` ships ``ge=0`` and a promo priced at zero
is a real sale — which is the one shape of zero this design allows, exactly as 0016 argued
for ``purge_runs.vendor_usage_deleted``. No column carries a ``server_default``: the table is
created empty and there are no existing rows to answer for.

**WHY ``created_at`` IS INDEXED AND ``idempotency_key`` IS UNIQUE.** Every read of this table
is a windowed rollup, and the unique key is the sole thing that makes a double tap, a stale
message and a redelivered Telegram update collapse into ONE sale. It is also the SAME string
the ledger GRANT is written under, which is what makes the unpriced backlog countable — a
deterministic join key rather than a constraint, so a future rail that writes one and not the
other shows up as a countable discrepancy instead of a rejected INSERT.

**WHY ``telegram_user_id`` IS NULLABLE AND INDEXED.** Nullable ONLY so that erasure has
somewhere to go: every writer supplies it and a ``NULL`` means one thing only, that
``forget_account`` ran. Indexed for that same anonymising ``UPDATE``, which runs inside the
transaction the customer's ``/forget`` is waiting on. There is NO foreign key, following
``credit_ledger`` (0006) and ``plan_purchases`` (0015): a customer can buy before any
``users`` row exists, and the receipt must outlive the account.

**NO ``*_expires_at``, NO RETENTION CUTOFF AND NO ``purge_runs`` COUNTER.** ``vendor_usage``
gets a 400-day cutoff because it is telemetry whose growth must be bounded; a RECEIPT is an
audit fact that must outlive every purge — it answers "was this customer charged 7 000 soʻm
for a song they never got?" months after the recipient's name, the customer's note and the
rendered audio are lawfully gone, and an audit trail that deletes itself on a schedule cannot
answer a dispute about the period it just erased. ``plan_purchases`` and ``credit_ledger`` are
on no clock for the identical reason, and growth here is one row per song sold. The
``*_expires_at`` suffix is avoided deliberately: ``tests/test_db/test_audit_retention.py``
derives "every clock in the schema is read by a sweep" from that suffix alone. The table is in
NEITHER of ``tests/test_db/test_privacy_constraints.py``'s two sets — its erasure route is
anonymisation, which neither set names — and that omission is recorded there as a comment,
alongside ``plan_purchases``, which has been silently exempt since revision 0015.

**Every enum is spelled literally.** A migration that imports application code breaks
historically, on a revision that already ran everywhere. ``enum_type`` renders ``VARCHAR(32)``
with ``create_constraint`` off, so a second one-off product needs no migration at all.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0020"
down_revision: str | None = "0019"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLE = "topup_purchases"

#: Non-unique, created through ``batch_op.f()`` so they take ``NAMING_CONVENTION``'s ``ix``
#: template and match the model's ``index=True`` declarations.
_INDEXES = ("telegram_user_id", "created_at")

#: The unique one, on the key that makes a double tap one sale and the unpriced backlog
#: countable. Created in the same batch block, with ``unique=True``.
_IDEMPOTENCY_INDEX_COLUMN = "idempotency_key"


def upgrade() -> None:
    op.create_table(
        _TABLE,
        sa.Column("id", sa.Uuid(), nullable=False),
        # Nullable ONLY so that erasure has somewhere to go — see the module docstring.
        sa.Column("telegram_user_id", sa.BigInteger(), nullable=True),
        sa.Column(
            "product",
            sa.Enum("single", name="topupkind", native_enum=False, length=32),
            nullable=False,
        ),
        sa.Column("credits_granted", sa.Integer(), nullable=False),
        # A term of the contract, not a measurement. NOT NULL, no server default.
        sa.Column("amount_minor", sa.Integer(), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("provider", sa.String(length=32), nullable=False),
        sa.Column("reference", sa.String(length=64), nullable=False),
        sa.Column(_IDEMPOTENCY_INDEX_COLUMN, sa.String(length=128), nullable=False),
        # UtcDateTime renders as a timezone-aware DateTime; env.py exists so our own column
        # types never have to be named here.
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "credits_granted > 0", name=op.f("ck_topup_purchases_credits_granted_positive")
        ),
        sa.CheckConstraint(
            "amount_minor >= 0", name=op.f("ck_topup_purchases_amount_not_negative")
        ),
        # No ForeignKeyConstraint. See the module docstring.
        sa.PrimaryKeyConstraint("id", name=op.f("pk_topup_purchases")),
    )
    with op.batch_alter_table(_TABLE, schema=None) as batch_op:
        for column in _INDEXES:
            batch_op.create_index(batch_op.f(f"ix_{_TABLE}_{column}"), [column], unique=False)
        batch_op.create_index(
            batch_op.f(f"ix_{_TABLE}_{_IDEMPOTENCY_INDEX_COLUMN}"),
            [_IDEMPOTENCY_INDEX_COLUMN],
            unique=True,
        )


def downgrade() -> None:
    with op.batch_alter_table(_TABLE, schema=None) as batch_op:
        batch_op.drop_index(batch_op.f(f"ix_{_TABLE}_{_IDEMPOTENCY_INDEX_COLUMN}"))
        for column in reversed(_INDEXES):
            batch_op.drop_index(batch_op.f(f"ix_{_TABLE}_{column}"))

    op.drop_table(_TABLE)
