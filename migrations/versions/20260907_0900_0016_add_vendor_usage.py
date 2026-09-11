"""Add vendor_usage.

Revision ID: 0016
Revises: 0015
Create Date: 2026-09-07

Nothing in this schema could say what a vendor call cost. The admin dashboard refuses to
draw a spend figure at all today, and it is right to: ``generation_attempts.cost_usd``
defaults to ``0.0`` and ``latency_ms`` to ``0``, so every row in that table carries numbers
nobody measured, and charting them would put a fabricated dollar figure on the screen an
operator uses to decide what to spend. This revision adds the table those numbers can
honestly live in.

**Why a new table rather than columns on ``generation_attempts``.** Two reasons, either
sufficient. That table sits on two retention clocks — identity at 90 days, free text at 30
— because it holds the recipient's name and the STT transcript, and spend history has to
outlive both: a billing question arrives long after the personal data on the row is lawfully
gone, and a year-over-year comparison needs thirteen months. And its only production writer
is the name-verdict path, so instrumenting every vendor call through it would mean widening
a table whose semantics are "one name-render attempt" into one meaning "any vendor call at
all". Nothing there can hold tokens, billed characters, billed milliseconds, an HTTP status
or a per-call vendor model id either.

**Every quantity column below is NULLABLE with no default, and that is the whole design.**
A default of ``0`` turns "nobody measured this" into "this cost nothing", and no reader
downstream can undo that — which is exactly how ``generation_attempts`` became unreadable.
With no defaults, ``SUM()`` over a group nobody measured returns SQL ``NULL``, the panel
renders "not priced", and the never-fabricate-a-number rule needs no application code to
enforce it.

**``ck_vendor_usage_cost_carries_its_source``.** ``cost_usd`` and ``cost_source`` are both
null or both set. A dollar figure with no provenance cannot be read: an operator has no way
to tell a number the vendor billed us (VENDOR_REPORTED) from arithmetic over token counts
(DERIVED) from our own rate against a duration we merely requested (ESTIMATED), and the
three deserve different trust. There is deliberately NO constraint tying ``error_code`` to
``is_success``: over-constraining a telemetry table loses rows, and a lost row is a hole in
the spend record where an odd pairing is only confusing.

**``cost_usd`` is indexed, and it is the one index here that earns its keep on the rows it
does NOT find.** ``has_priced_vendor_usage`` — the ``isVendorCost`` capability — asks
``SELECT 1 FROM vendor_usage WHERE cost_usd IS NOT NULL LIMIT 1``, and
``read_capabilities`` reaches it on every ``/api/ops/pulse``, which the Live screen polls
every five seconds. Where something is priced the ``LIMIT 1`` stops at the first hit and the
index changes nothing worth measuring; where NOTHING is priced there is no first hit, so an
unindexed table is scanned end to end twelve times a minute against the fastest-growing
table in this schema. A plain index and deliberately not a partial ``WHERE cost_usd IS NOT
NULL`` one: SQLite and Postgres both accept partial indexes but they do not round-trip
identically through ``inspector.get_indexes``, and
``test_the_migrated_indexes_match_the_model_metadata`` compares migrated schema against
model metadata for a living.

**No foreign key to ``orders``**, following ``credit_ledger`` (0006) and ``payments``
(plan §5.8). Spend outlives the order — an abandoned draft is deleted at 14 days and the
money was still spent — and the wizard's lyric-preview call happens BEFORE an order row
exists, so a constraint here would either reject a true row or force the bot to invent an
order id.

**Not personal data, and therefore no ``*_expires_at``.** Every column is a closed enum, an
integer, a machine id or a bounded error code: no name, no note, no transcript, no telegram
id, no free text of any kind. So the table belongs in neither of
``tests/test_db/test_privacy_constraints.py``'s two sets — that omission is recorded there
as a comment rather than left silent — and its growth is bounded by a 400-day CUTOFF in
``bayram.db.purge``, not by a per-row clock. The ``*_expires_at`` suffix is reserved:
``tests/test_db/test_audit_retention.py`` derives "every clock in the schema is read by a
sweep" from that suffix alone, and using it here would claim a legal schedule this table
does not have. The counter for that sweep is the ``purge_runs.vendor_usage_deleted`` column
this same revision adds, because a sweep whose count is not stored is a backlog the panel
reports as zero.

**Every enum is spelled literally.** A migration that imports application code breaks when
that code is refactored, and it breaks historically, on a revision that already ran
everywhere (``tests/test_db/test_migrations.py::test_no_migration_imports_application_code``).
``enum_type`` renders a plain ``VARCHAR(32)`` with ``create_constraint`` off, so the legal
value set is enforced in the mapper and nowhere in the database — which is also why a new
``Vendor`` or ``UsageTask`` member later needs no migration at all.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0016"
down_revision: str | None = "0015"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLE = "vendor_usage"

#: The table this revision also ALTERs: the sweep's own record gains the counter for the
#: sweep this revision creates work for.
_PURGE_RUNS_TABLE = "purge_runs"
_PURGE_RUNS_COLUMN = "vendor_usage_deleted"

#: The three single-column indexes, created through ``batch_op.f()`` so they take
#: ``NAMING_CONVENTION``'s ``ix`` template and match what the model's ``index=True`` declares.
_INDEXES = ("created_at", "order_id", "cost_usd")

#: The rollup's index: filter ``created_at``, group by ``vendor``, and carry ``id`` so the
#: window scan is index-only. Hand-named WITHOUT ``op.f`` — exactly like 0015's
#: ``_USER_ENDS_INDEX`` — because the ``ix`` template would render
#: ``ix_vendor_usage_vendor_created_at_id``, which the model does not declare, and
#: ``test_the_migrated_indexes_match_the_model_metadata`` compares the two by name.
_VENDOR_CREATED_INDEX = "ix_vendor_usage_vendor_created_at"


def upgrade() -> None:
    op.create_table(
        _TABLE,
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "vendor",
            sa.Enum(
                "elevenlabs",
                "openrouter",
                "gemini",
                "openai_compatible",
                "fake",
                name="vendor",
                native_enum=False,
                length=32,
            ),
            nullable=False,
        ),
        sa.Column(
            "operation",
            sa.Enum(
                "music_compose",
                "music_inpaint",
                "speech_synthesis",
                "transcription",
                "chat_completion",
                "health",
                name="vendoroperation",
                native_enum=False,
                length=32,
            ),
            nullable=False,
        ),
        sa.Column("provider", sa.String(length=64), nullable=False),
        sa.Column("model_id", sa.String(length=128), nullable=True),
        sa.Column("is_fallback", sa.Boolean(), nullable=False),
        sa.Column("is_fake", sa.Boolean(), nullable=False),
        sa.Column(
            "task",
            sa.Enum(
                "moderation",
                "lyrics",
                "lyrics_preview",
                "greeting_scripts",
                "song",
                "name_verification",
                "greeting_speech",
                name="usagetask",
                native_enum=False,
                length=32,
            ),
            nullable=True,
        ),
        # No ForeignKeyConstraint. See the module docstring.
        sa.Column("order_id", sa.Uuid(), nullable=True),
        sa.Column("correlation_id", sa.String(length=64), nullable=True),
        sa.Column("is_success", sa.Boolean(), nullable=False),
        sa.Column("http_status", sa.Integer(), nullable=True),
        sa.Column("error_code", sa.String(length=48), nullable=True),
        # Every quantity below: nullable, no server default. NULL is "not measured".
        sa.Column("latency_ms", sa.Integer(), nullable=True),
        sa.Column("prompt_tokens", sa.Integer(), nullable=True),
        sa.Column("completion_tokens", sa.Integer(), nullable=True),
        sa.Column("total_tokens", sa.Integer(), nullable=True),
        sa.Column("billed_characters", sa.Integer(), nullable=True),
        sa.Column("audio_ms", sa.Integer(), nullable=True),
        sa.Column("request_bytes", sa.Integer(), nullable=True),
        sa.Column("response_bytes", sa.Integer(), nullable=True),
        sa.Column("cost_usd", sa.Float(), nullable=True),
        sa.Column(
            "cost_source",
            sa.Enum(
                "vendor_reported",
                "derived",
                "estimated",
                name="costsource",
                native_enum=False,
                length=32,
            ),
            nullable=True,
        ),
        # UtcDateTime renders as a timezone-aware DateTime; env.py exists so our own column
        # types never have to be named here.
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "(cost_usd IS NULL AND cost_source IS NULL)"
            " OR (cost_usd IS NOT NULL AND cost_source IS NOT NULL)",
            name=op.f("ck_vendor_usage_cost_carries_its_source"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_vendor_usage")),
    )
    with op.batch_alter_table(_TABLE, schema=None) as batch_op:
        # SQLite cannot ALTER an existing table to add an index without a rebuild, so every
        # index in this project is created inside batch_alter_table (render_as_batch=True).
        for column in _INDEXES:
            batch_op.create_index(batch_op.f(f"ix_{_TABLE}_{column}"), [column], unique=False)
        batch_op.create_index(_VENDOR_CREATED_INDEX, ["vendor", "created_at", "id"], unique=False)

    with op.batch_alter_table(_PURGE_RUNS_TABLE, schema=None) as batch_op:
        # NOT NULL with a server default because existing rows have to answer something, and
        # for THIS column zero is the true answer: those sweeps genuinely deleted no
        # vendor_usage rows, because the table did not exist when they ran. That is the one
        # shape of zero this design allows — a measured count, not an unmeasured quantity.
        batch_op.add_column(
            sa.Column(_PURGE_RUNS_COLUMN, sa.Integer(), nullable=False, server_default="0")
        )


def downgrade() -> None:
    with op.batch_alter_table(_PURGE_RUNS_TABLE, schema=None) as batch_op:
        batch_op.drop_column(_PURGE_RUNS_COLUMN)

    with op.batch_alter_table(_TABLE, schema=None) as batch_op:
        batch_op.drop_index(_VENDOR_CREATED_INDEX)
        for column in reversed(_INDEXES):
            batch_op.drop_index(batch_op.f(f"ix_{_TABLE}_{column}"))

    op.drop_table(_TABLE)
