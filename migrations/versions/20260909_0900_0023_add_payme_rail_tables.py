"""Add payment_intents, payme_transactions and payme_rpc_log.

Revision ID: 0023
Revises: 0022
Create Date: 2026-09-09

Implements the schema half of ``DECISIONS.md D11`` and ``PAYME_INTEGRATION §2``.

Every sale this schema has recorded was settled INSIDE the request that started it: the
stub checkout provider reports ``is_paid=True`` and the same coroutine writes the receipt
and the credit grant microseconds later. A redirect rail breaks that in half. The customer
is handed a URL, leaves for a bank's own page, and the answer arrives minutes later on an
inbound HTTPS request to a DIFFERENT PROCESS which has never heard of the Telegram update
that started it. These three tables are the only things the two halves share.

**WHY THREE TABLES AND NOT COLUMNS ON ``topup_purchases``.** That table is a RECEIPT. It is
append-only by explicit design — its own model docstring pre-empts the reviewer who would
"restore symmetry" by adding ``TimestampMixin`` — it is written once at the moment a
COMPLETED sale is recorded, and every reader of it is a windowed revenue rollup. An intent
is the opposite of all three. It MUTATES (pending, held, paid), it is written before any
money exists, and **most intents never become sales at all**, because people open a payment
page and close it. A pre-emptive receipt per intent would make every revenue figure in the
panel count money nobody paid, and the only repair would be a ``WHERE paid_at IS NOT NULL``
that every future reader has to remember to write. It would also make one table mean two
things — "this sale happened" for some rows and "this sale was offered" for the rest — which
is precisely the objection revision 0020 rejected money-on-``credit_ledger`` for, restated
one table along.

**WHY NOT A ``plan_purchases`` ROW.** Revision 0020 raised this objection and it is
unchanged, only sharper. ``plan_sql.current_plan`` and ``live_plan`` would SEE the row: an
UNPAID intent for a starter plan would block the sale of a real plan for the life of an
invented end date, while ``claim_plan_song`` minted songs out of a purchase nobody had paid
for. An unpaid row that mints entitlement is not a schema-reuse inconvenience; it is free
songs, granted by a stranger who merely opened a payment page.

**WHY ``public_ref`` EXISTS INSTEAD OF PUTTING ``idempotency_key`` IN THE ACCOUNT FIELD.**
The obvious design hands the rail the idempotency key as its account number and saves a
column. That key is ``topup:{telegram_user_id}:{scope}:{seq}`` — it CONTAINS the customer's
Telegram id — and the account number is rendered in the customer's browser address bar,
logged by the rail, printed on the rail's receipt and visible to anyone the customer
forwards the link to. ``public_ref`` is 24 lowercase hex characters from
``secrets.token_hex(12)``: opaque by construction, identifying nothing on its own, and
containing neither a ``;`` nor an ``=``, which the checkout link's own parser treats as a
field separator and a key/value split and would silently truncate the value at. The two
identifiers are split by AUDIENCE — one is ours and never leaves, one is theirs and says
nothing — and the column that looks redundant is what keeps a Telegram id out of a third
party's logs.

**WHY ``cancel_reason`` IS A BARE INTEGER, a deliberate exception to this package's own
closed-enum rule.** The reason codes are the RAIL's vocabulary: defined by them, echoed back
to them numerically on the wire, extendable by them without asking us. A ``VARCHAR`` mirror
would be a translation table with two failure modes and no upside — an unknown incoming code
would either be rejected (losing a cancellation the rail has already applied) or mapped to
"unknown" (destroying the only evidence of what happened), and on the way out a
mistranslation would emit a value the rail does not recognise. Their integer, stored
verbatim, cannot be wrong. Where a name IS needed, it is a Python ``IntEnum`` at the wire
boundary, not a column type.

**WHY THERE IS NO FOREIGN KEY ANYWHERE IN THIS REVISION.** ``telegram_user_id`` follows
``credit_ledger`` (0006), ``plan_purchases`` (0015) and ``topup_purchases`` (0020): a
customer can pay before any ``users`` row exists, and a payment must outlive the account.
``payment_intents.active_transaction_id`` and ``payme_transactions.intent_id`` omit one for a
sharper reason: both rows are written inside ONE commit by conditional ``UPDATE``s whose
``rowcount`` is the lock, so a constraint would add a second and weaker opinion about an
ordering the commit already guarantees, while forcing the erasure arm and both retention
sweeps to care about delete order for no benefit at all.

**WHY EACH NULLABLE COLUMN IS NULLABLE.** ``telegram_user_id`` is nullable ONLY so erasure
has somewhere to go — every writer supplies it, and a NULL means one thing: ``/forget`` ran.
``plan_songs``/``plan_days`` are NULL for a one-off product, which has neither a duration nor
a song count, and the CHECK below makes them mandatory the moment the product is a plan.
``active_transaction_id`` is NULL in every state except ``awaiting``, where the CHECK makes
it mandatory. ``settled_at``, ``notified_at`` and ``settle_note`` are NULL until the events
they record have happened; ``perform_time`` and ``cancel_time`` likewise. ``cancel_reason``
is NULL rather than 0 under the null-never-zero rule: zero is not a reason code, and a
default of it would say "cancelled for reason zero" about every transaction never cancelled.
On the journal, both identifier columns are nullable because a call that failed
authentication carries neither, and ``peer_ip`` is NULL when the transport reported none.

**WHY EACH INDEX EXISTS.** ``public_ref`` and ``idempotency_key`` are UNIQUE: the first
because the rail's account number must resolve to exactly one intent, the second because a
replayed open must return the SAME intent and therefore the SAME URL — two live payment
pages for one purchase is a customer who cannot tell which took their money.
``payme_transaction_id`` is UNIQUE, and that index is the ENTIRE retry story: the rail
resends every call until answered, and a duplicate create must collide rather than open a
second charge. ``telegram_user_id`` is indexed for the anonymising ``UPDATE`` that runs
inside the transaction a customer's ``/forget`` is waiting on. ``created_at`` on both
mutable tables is indexed because every read of them is a window, and on the intent it is
also the retention cutoff's predicate. ``intent_id`` is indexed and deliberately NOT unique:
the protocol lets an intent accumulate a cancelled transaction and then a live one, which is
what makes a declined card retryable in seconds rather than dead for twelve hours.
``payme_time`` is indexed because the statement endpoint filters on it INCLUSIVELY and sorts
ascending by it. The two hand-named composites serve the two sweeps —
``ix_payment_intents_state_valid_until`` for the expiry predicate and
``ix_payme_transactions_state_payme_time`` for the stale-transaction one — and are spelled
here EXACTLY as the models spell them, because
``test_the_migrated_indexes_match_the_model_metadata`` compares index names and a templated
name would leave the models declaring an index the chain never builds. On the journal, ``at``
is indexed for its cutoff sweep and both references for the one query anybody runs against
it under pressure: everything that happened to this transaction, or to this payment page.

**PRIVACY — ALL THREE TABLES ARE IN NEITHER OF
``tests/test_db/test_privacy_constraints.py``'s TWO SETS, and the argument is written down
there rather than left silent.** ``payment_intents`` takes the third route ``credit_ledger``,
``plan_purchases`` and ``topup_purchases`` already take: not personal data, because every
column is a Telegram id, an integer, a three-letter ISO currency, a closed enum, a
machine-built key, a hex token, a merchant account id, a boolean or a clock — no name, no
note, no lyric, no free text of any kind; and not erased-on-request, because that set means
"the absence of a row IS the erasure record" while this table is erased by ANONYMISATION.
**A deleted intent would be worse than useless**: the rail can still see its own transaction
and can still ask about it through a statement call months later, and answering "that payment
never existed" about money somebody really paid is the answer that loses them a dispute.
``payme_transactions`` holds NO Telegram id at all and is reachable to a person only by
joining through the intent — the very join ``/forget`` breaks. ``payme_rpc_log``'s claim is
stronger still: no id, no request body, no header, so every column is a method name, an
opaque reference, a machine id, an integer or the address of THEIR server, which is exactly
the argument ``vendor_usage`` (0016) makes for itself.

**THE RETENTION SHAPES, AND WHY NO COLUMN USES THE ``*_expires_at`` SUFFIX.**
``tests/test_db/test_audit_retention.py::_clocks_in_the_schema`` collects every column in
``Base.metadata`` whose name ends in ``expires_at`` and demands
``bayram.db.purge.rows_past_expiry_statements`` read it: that suffix is this codebase's word for
a published legal RETENTION clock stamped per row by its writer. ``valid_until`` is a
BUSINESS clock — how long a payment page stays payable — exactly like
``plan_purchases.plan_ends_at``, and naming it with that suffix would claim a schedule it
does not have. The three tables are bounded differently and on purpose: ``payme_rpc_log`` on
a 90-day CUTOFF on ``at`` (chatter, disposable), terminal UNPAID intents on a 400-day CUTOFF
on ``created_at`` (bounded growth over a table that gets a row every time anybody opens a
payment page), and ``payme_transactions`` on NOTHING AT ALL, on ``topup_purchases``'
argument: it is an audit fact about money, and the rail may ask about any transaction it has
ever created.

**WHY THERE IS NO BACKFILL, AND WHY THERE CAN NEVER BE ONE.** All three tables are created
EMPTY and no history is touched. The stub rail never opened an intent — it reports a charge
paid inside the same coroutine, having contacted nobody — so there is no past payment that
HAD an intent, a rail-side transaction or an inbound call to reconstruct. Inventing one per
historical ``topup_purchases`` row would fabricate a rail reference, a merchant id and three
clocks that never existed, which is LR-63's "retrofitting revenue recognition corrupts every
prior reported period" applied to a table that has not recognised any revenue yet. The two
populations are told apart STRUCTURALLY, as in 0020: a sale with no intent sharing its
``idempotency_key`` was sold before this rail existed. Consequently no column carries a
``server_default`` on the three new tables. The two ``purge_runs`` counters DO — 0016's
precedent — because that table has existing rows which must answer something, and for those
columns zero is the TRUE answer: those sweeps genuinely deleted nothing, because the tables
did not exist when they ran.

**Every enum is spelled literally, and every clock is a plain ``sa.DateTime(timezone=True)``.**
A migration that imports application code breaks historically, on a revision that already ran
everywhere; ``env.py`` renders ``UtcDateTime`` as a timezone-aware ``DateTime`` precisely so
our own column types never have to be named here. ``enum_type`` renders ``VARCHAR(32)`` with
``create_constraint`` off, so a second product or a sixth intent state needs no migration at
all. The two CHECK constraints spell their enum values as literal strings for the same
reason from the other direction: a CHECK is DDL, it outlives the Python enum, and a member
renamed in code must never silently change what the database enforces.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0023"
down_revision: str | None = "0022"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_INTENTS = "payment_intents"
_TRANSACTIONS = "payme_transactions"
_RPC_LOG = "payme_rpc_log"
_PURGE_RUNS = "purge_runs"

#: ``(column, unique)`` per table, created through ``batch_op.f()`` so they take
#: ``NAMING_CONVENTION``'s ``ix`` template and match the models' ``index=True`` declarations.
#: Dropped in ``reversed()`` order on the way down.
_INTENT_INDEXES: tuple[tuple[str, bool], ...] = (
    ("public_ref", True),
    ("idempotency_key", True),
    ("telegram_user_id", False),
    ("created_at", False),
)
_TRANSACTION_INDEXES: tuple[tuple[str, bool], ...] = (
    ("payme_transaction_id", True),
    ("intent_id", False),
    ("payme_time", False),
    ("created_at", False),
)
_RPC_LOG_INDEXES: tuple[tuple[str, bool], ...] = (
    ("at", False),
    ("payme_transaction_id", False),
    ("public_ref", False),
)

#: The two composites, hand-named rather than templated because each is a decision about a
#: specific sweep rather than a column's own index. Spelled identically in the models.
_INTENT_EXPIRY_INDEX = "ix_payment_intents_state_valid_until"
_TRANSACTION_STALE_INDEX = "ix_payme_transactions_state_payme_time"

#: The two counters added to the existing sweep-record table. Order matters on the way down.
_PURGE_RUNS_COLUMNS = ("payme_rpc_rows_deleted", "payment_intents_deleted")


def upgrade() -> None:
    op.create_table(
        _INTENTS,
        sa.Column("id", sa.Uuid(), nullable=False),
        # The only identifier that ever crosses to a third party. Opaque by construction.
        sa.Column("public_ref", sa.String(length=32), nullable=False),
        sa.Column("idempotency_key", sa.String(length=128), nullable=False),
        # Nullable ONLY so that erasure has somewhere to go — see the module docstring.
        sa.Column("telegram_user_id", sa.BigInteger(), nullable=True),
        sa.Column(
            "product",
            sa.Enum("single", "starter", name="intentproduct", native_enum=False, length=32),
            nullable=False,
        ),
        # A term of the contract, not a measurement. NOT NULL, no server default.
        sa.Column("amount_minor", sa.Integer(), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        # NULL for a one-off product; both required for a plan by the CHECK below.
        sa.Column("plan_songs", sa.Integer(), nullable=True),
        sa.Column("plan_days", sa.Integer(), nullable=True),
        sa.Column("provider", sa.String(length=32), nullable=False),
        # The cashbox this link was issued for. Stored, never re-derived at settlement.
        sa.Column("merchant_id", sa.String(length=64), nullable=False),
        sa.Column("is_sandbox", sa.Boolean(), nullable=False),
        sa.Column("language", sa.String(length=16), nullable=False),
        sa.Column(
            "state",
            sa.Enum(
                "pending",
                "awaiting",
                "paid",
                "cancelled",
                "expired",
                name="paymentintentstate",
                native_enum=False,
                length=32,
            ),
            nullable=False,
        ),
        sa.Column("active_transaction_id", sa.Uuid(), nullable=True),
        # UtcDateTime renders as a timezone-aware DateTime; env.py exists so our own column
        # types never have to be named here. A BUSINESS clock: see the module docstring on
        # why it is not named with the *_expires_at suffix.
        sa.Column("valid_until", sa.DateTime(timezone=True), nullable=False),
        sa.Column("settled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("notified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("settle_note", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "amount_minor >= 0", name=op.f("ck_payment_intents_amount_not_negative")
        ),
        # Literal 'starter', not a rendered enum member: a CHECK outlives the Python class.
        sa.CheckConstraint(
            "product <> 'starter' OR (plan_songs IS NOT NULL AND plan_days IS NOT NULL)",
            name=op.f("ck_payment_intents_plan_fields_present"),
        ),
        # An 'awaiting' row with no holder is a hold nobody can release: every conditional
        # UPDATE names the transaction id, and the expiry predicate reads 'pending' only.
        sa.CheckConstraint(
            "state <> 'awaiting' OR active_transaction_id IS NOT NULL",
            name=op.f("ck_payment_intents_holder_present"),
        ),
        # No ForeignKeyConstraint. See the module docstring.
        sa.PrimaryKeyConstraint("id", name=op.f("pk_payment_intents")),
    )

    op.create_table(
        _TRANSACTIONS,
        sa.Column("id", sa.Uuid(), nullable=False),
        # Payme's own id: a 24-character Mongo ObjectId, stored and compared as TEXT.
        sa.Column("payme_transaction_id", sa.String(length=24), nullable=False),
        # Indexed, no FK, and deliberately not unique — see the module docstring.
        sa.Column("intent_id", sa.Uuid(), nullable=False),
        # The RAIL's creation instant, which the twelve-hour timeout is measured from.
        sa.Column("payme_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("amount_minor", sa.Integer(), nullable=False),
        sa.Column(
            "state",
            sa.Enum(
                "created",
                "performed",
                "cancelled",
                "cancelled_after_perform",
                name="paymestate",
                native_enum=False,
                length=32,
            ),
            nullable=False,
        ),
        # Their vocabulary, echoed numerically. NULL until cancelled, never 0.
        sa.Column("cancel_reason", sa.Integer(), nullable=True),
        # Three persisted instants, so a replayed method returns the ORIGINAL answer.
        sa.Column("create_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("perform_time", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cancel_time", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "amount_minor >= 0", name=op.f("ck_payme_transactions_amount_not_negative")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_payme_transactions")),
    )

    op.create_table(
        _RPC_LOG,
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("at", sa.DateTime(timezone=True), nullable=False),
        # A string and not an enum: an UNKNOWN method is one of the things this records.
        sa.Column("method", sa.String(length=32), nullable=False),
        sa.Column("payme_transaction_id", sa.String(length=24), nullable=True),
        sa.Column("public_ref", sa.String(length=32), nullable=True),
        # 0 for success, otherwise the JSON-RPC code, which is negative for every fault.
        sa.Column("reply_code", sa.Integer(), nullable=False),
        # THEIR server's address, never a customer's. See the module docstring.
        sa.Column("peer_ip", sa.String(length=45), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=False),
        # No telegram id, no request body, no header — that absence is the design.
        sa.PrimaryKeyConstraint("id", name=op.f("pk_payme_rpc_log")),
    )

    # SQLite cannot ALTER an existing table to add an index without a rebuild, so every
    # index in this project is created inside batch_alter_table (render_as_batch=True).
    with op.batch_alter_table(_INTENTS, schema=None) as batch_op:
        for column, unique in _INTENT_INDEXES:
            batch_op.create_index(batch_op.f(f"ix_{_INTENTS}_{column}"), [column], unique=unique)
        batch_op.create_index(_INTENT_EXPIRY_INDEX, ["state", "valid_until"], unique=False)

    with op.batch_alter_table(_TRANSACTIONS, schema=None) as batch_op:
        for column, unique in _TRANSACTION_INDEXES:
            batch_op.create_index(
                batch_op.f(f"ix_{_TRANSACTIONS}_{column}"), [column], unique=unique
            )
        batch_op.create_index(_TRANSACTION_STALE_INDEX, ["state", "payme_time"], unique=False)

    with op.batch_alter_table(_RPC_LOG, schema=None) as batch_op:
        for column, unique in _RPC_LOG_INDEXES:
            batch_op.create_index(batch_op.f(f"ix_{_RPC_LOG}_{column}"), [column], unique=unique)

    with op.batch_alter_table(_PURGE_RUNS, schema=None) as batch_op:
        # NOT NULL with a server default because existing rows have to answer something, and
        # for THESE columns zero is the true answer: those sweeps genuinely deleted nothing,
        # because neither table existed when they ran. That is the one shape of zero this
        # design allows — a measured count, not an unmeasured quantity — as 0016 argued.
        for column in _PURGE_RUNS_COLUMNS:
            batch_op.add_column(
                sa.Column(column, sa.Integer(), nullable=False, server_default=sa.text("0"))
            )


def downgrade() -> None:
    with op.batch_alter_table(_PURGE_RUNS, schema=None) as batch_op:
        for column in reversed(_PURGE_RUNS_COLUMNS):
            batch_op.drop_column(column)

    with op.batch_alter_table(_RPC_LOG, schema=None) as batch_op:
        for column, _ in reversed(_RPC_LOG_INDEXES):
            batch_op.drop_index(batch_op.f(f"ix_{_RPC_LOG}_{column}"))

    with op.batch_alter_table(_TRANSACTIONS, schema=None) as batch_op:
        batch_op.drop_index(_TRANSACTION_STALE_INDEX)
        for column, _ in reversed(_TRANSACTION_INDEXES):
            batch_op.drop_index(batch_op.f(f"ix_{_TRANSACTIONS}_{column}"))

    with op.batch_alter_table(_INTENTS, schema=None) as batch_op:
        batch_op.drop_index(_INTENT_EXPIRY_INDEX)
        for column, _ in reversed(_INTENT_INDEXES):
            batch_op.drop_index(batch_op.f(f"ix_{_INTENTS}_{column}"))

    op.drop_table(_RPC_LOG)
    op.drop_table(_TRANSACTIONS)
    op.drop_table(_INTENTS)
