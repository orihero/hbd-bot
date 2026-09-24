"""The image and video products' tables (IMAGE_VIDEO_SPEC §3.2.2, M2.1).

Revision ID: 0031
Revises: 0030
Create Date: 2026-09-24

Seven new tables, two nullable columns on existing tables, and nine counters on
``purge_runs``. Nothing is backfilled: no media request has ever been made.

* ``media_jobs`` — one customer request; the job state machine (§3.3) lives on this row.
  The partial unique ``ix_media_jobs_one_open_request`` allows one OPEN request per
  (account, kind) (§7.6).
* ``media_inputs`` / ``media_outputs`` — where the bytes are; each carries the
  ``legal_hold_has_expiry`` CHECK so a CSAM-class hold (§6.7) can never be kept for ever.
* ``media_attempts`` — one row per vendor call, written BEFORE the POST (R7).
* ``media_purchases`` — the append-only receipt.
* ``media_credit_ledger`` / ``media_credit_balances`` — the kind-scoped refund credit, with
  two partial unique indexes making "a job refunds at most once" a database fact.
* ``payment_intents.resume_media_job_id`` (§7.2) and ``vendor_usage.media_job_id`` + index.

**Every partial index predicate is a string of literals that renders on both engines**, the
0010/0028 precedent: ``IN ('…')``, ``<>`` and ``>`` over plain columns mean the same thing to
SQLite and Postgres. The open-request predicate spells the ten open states in the order the
model renders them (sorted), so the two strings are byte-identical.

**Hand-named indexes** are the composite and partial ones; every single-column index goes
through ``batch_op.f()`` and takes ``NAMING_CONVENTION``'s ``ix`` template, matching the models'
``index=True``. Enums are spelled literally and clocks are plain
``sa.DateTime(timezone=True)``: no migration imports application code.

``purge_runs``' nine counters are NOT NULL with a server default of zero, 0024's and 0030's
precedent: a sweep recorded before these tables existed truly deleted nothing from them.

**The downgrade drops every media request, upload record, receipt and refund credit.** Run it
only on a deployment that never sold media; the receipts have no other copy.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0031"
down_revision: str | None = "0030"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_JOBS = "media_jobs"
_INPUTS = "media_inputs"
_OUTPUTS = "media_outputs"
_ATTEMPTS = "media_attempts"
_PURCHASES = "media_purchases"
_LEDGER = "media_credit_ledger"
_BALANCES = "media_credit_balances"
_INTENTS = "payment_intents"
_USAGE = "vendor_usage"
_PURGE_RUNS = "purge_runs"

_RESUME_MEDIA_JOB_ID = "resume_media_job_id"
_MEDIA_JOB_ID = "media_job_id"

#: Spelled identically on ``MediaJobRow``; see the module docstring on the order.
_OPEN_REQUEST_INDEX = "ix_media_jobs_one_open_request"
_OPEN_REQUEST_PREDICATE = (
    "state IN ('awaiting_payment', 'delivering', 'drafting', 'generating', 'held', 'paid', "
    "'post', 'queued', 'quoted', 'screening')"
)
_ONE_REFUND_INDEX = "ix_media_credit_ledger_one_refund_per_job"
_ONE_REFUND_PREDICATE = "delta > 0 AND reason <> 'admin_correction'"
_ONE_SPEND_INDEX = "ix_media_credit_ledger_one_spend_per_job"
_ONE_SPEND_PREDICATE = "reason = 'spent'"

_LEGAL_HOLD_HAS_EXPIRY = "retention_class <> 'legal_hold' OR legal_hold_expires_at IS NOT NULL"
_DELTA_MATCHES_REASON = (
    "(reason = 'spent' AND delta = -1)"
    " OR (reason = 'admin_correction' AND delta IN (-1, 1))"
    " OR (reason NOT IN ('spent', 'admin_correction') AND delta = 1)"
)

#: Hand-named composite indexes: ``(table, name, columns)``.
_COMPOSITE_INDEXES: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    (_JOBS, "ix_media_jobs_state_created", ("state", "created_at", "id")),
    (_JOBS, "ix_media_jobs_user_created", ("telegram_user_id", "created_at", "id")),
    (_JOBS, "ix_media_jobs_sku_created", ("sku", "created_at", "id")),
)

#: Templated single-column indexes: ``(table, column, unique)``.
_TEMPLATED_INDEXES: tuple[tuple[str, str, bool], ...] = (
    (_JOBS, "user_id", False),
    (_JOBS, "text_expires_at", False),
    (_INPUTS, "expires_at", False),
    (_OUTPUTS, "expires_at", False),
    (_ATTEMPTS, "created_at", False),
    (_PURCHASES, "telegram_user_id", False),
    (_PURCHASES, "created_at", False),
    (_LEDGER, "telegram_user_id", False),
    (_LEDGER, "created_at", False),
)

_PURGE_RUNS_COLUMNS: tuple[str, ...] = (
    "media_inputs_deleted",
    "media_outputs_deleted",
    "media_input_holds_deleted",
    "media_output_holds_deleted",
    "media_job_texts_purged",
    "media_jobs_deleted",
    "media_attempts_deleted",
    "media_purchases_deleted",
    "media_credit_entries_deleted",
)


def _enum(name: str, *values: str, length: int = 32) -> sa.Enum:
    """A ``VARCHAR`` enum as ``enum_type`` renders it: no native type, no CHECK."""
    return sa.Enum(*values, name=name, native_enum=False, length=length)


_SKU = ("image", "video_standard", "video_fast")
_RETENTION = (
    "paid_audio",
    "free_output",
    "ephemeral",
    "media_input",
    "media_output",
    "legal_hold",
)
_DECISIONS = ("allow", "review", "block", "unavailable")


def _media_jobs() -> None:
    op.create_table(
        _JOBS,
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("telegram_user_id", sa.BigInteger(), nullable=False),
        sa.Column("kind", _enum("mediakind", "image", "video", length=16), nullable=False),
        sa.Column("tier", _enum("mediatier", "standard", "fast", length=16), nullable=True),
        sa.Column("sku", _enum("mediasku", *_SKU), nullable=False),
        sa.Column(
            "state",
            _enum(
                "mediajobstate",
                "drafting",
                "screening",
                "quoted",
                "awaiting_payment",
                "paid",
                "queued",
                "generating",
                "post",
                "held",
                "delivering",
                "delivered",
                "failed",
                "rejected",
                "cancelled",
                "abandoned",
                length=24,
            ),
            nullable=False,
        ),
        sa.Column("chat_id", sa.BigInteger(), nullable=False),
        sa.Column("tray_message_id", sa.Integer(), nullable=True),
        sa.Column("status_message_id", sa.Integer(), nullable=True),
        sa.Column("content_sha256", sa.String(length=64), nullable=True),
        sa.Column("submit_seq", sa.SmallInteger(), nullable=False, server_default=sa.text("0")),
        sa.Column("oscreen_seq", sa.SmallInteger(), nullable=False, server_default=sa.text("0")),
        sa.Column("outputs_requested", sa.SmallInteger(), nullable=False),
        sa.Column("aspect", _enum("mediaaspect", "9:16", "1:1", "16:9", length=8), nullable=False),
        sa.Column("params", sa.JSON(), nullable=False),
        sa.Column(
            "backend",
            _enum("mediabackend", "local", "higgsfield", "fal", "fake", length=16),
            nullable=True,
        ),
        sa.Column("model_id", sa.String(length=64), nullable=True),
        sa.Column(
            "language",
            _enum("language", "uz_latn", "uz_cyrl", "ru", "en", length=8),
            nullable=False,
        ),
        sa.Column("prompt", sa.String(length=800), nullable=True),
        sa.Column(
            "voice_mode",
            _enum("mediavoicemode", "none", "ai_user", "ai_llm", "own", length=16),
            nullable=False,
        ),
        sa.Column(
            "voice_gender", _enum("mediavoicegender", "female", "male", length=8), nullable=True
        ),
        sa.Column("narration_text", sa.String(length=160), nullable=True),
        sa.Column("voice_transcript", sa.String(length=400), nullable=True),
        sa.Column("text_expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("text_purged_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "screen_decision", _enum("mediascreendecision", *_DECISIONS, length=16), nullable=True
        ),
        sa.Column("screen_categories", sa.JSON(), nullable=True),
        sa.Column("screen_policy_version", sa.String(length=32), nullable=True),
        sa.Column(
            "output_decision", _enum("mediascreendecision", *_DECISIONS, length=16), nullable=True
        ),
        sa.Column("output_categories", sa.JSON(), nullable=True),
        sa.Column("price_minor", sa.Integer(), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("payment_intent_id", sa.Uuid(), nullable=True),
        sa.Column(
            "paid_via", _enum("mediapaidvia", "payme", "credit", "beta", length=16), nullable=True
        ),
        sa.Column("render_ready_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("audio_ready_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_code", sa.String(length=48), nullable=True),
        sa.Column("failed_reason", sa.String(length=256), nullable=True),
        sa.Column(
            "refund_state", _enum("mediarefundstate", "due", "granted", length=16), nullable=True
        ),
        sa.Column("forget_requested_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("quoted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("paid_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("delivered_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "outputs_requested BETWEEN 1 AND 4",
            name=op.f("ck_media_jobs_outputs_requested_in_range"),
        ),
        sa.CheckConstraint("price_minor >= 0", name=op.f("ck_media_jobs_price_not_negative")),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_media_jobs_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_media_jobs")),
    )


def _media_bytes(table: str, role_enum: sa.Enum, *, is_output: bool) -> None:
    """``media_inputs`` and ``media_outputs`` share every column but a handful."""
    shaped: list[sa.Column[object] | sa.Constraint] = [
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("job_id", sa.Uuid(), nullable=False),
    ]
    if is_output:
        shaped += [
            sa.Column("role", role_enum, nullable=False),
            sa.Column("variant", sa.SmallInteger(), nullable=False),
            sa.Column("storage_key", sa.String(length=512), nullable=False),
        ]
    else:
        shaped += [
            sa.Column("ordinal", sa.SmallInteger(), nullable=False),
            sa.Column("role", role_enum, nullable=False),
            sa.Column("tg_file_id", sa.String(length=256), nullable=True),
            sa.Column("tg_file_unique_id", sa.String(length=64), nullable=True),
            sa.Column("storage_key", sa.String(length=512), nullable=True),
        ]
    shaped += [
        sa.Column("mime", sa.String(length=64), nullable=True),
        sa.Column("size_bytes", sa.BigInteger(), nullable=True),
        sa.Column("sha256", sa.String(length=64), nullable=True),
        sa.Column("width", sa.Integer(), nullable=True),
        sa.Column("height", sa.Integer(), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
    ]
    if is_output:
        shaped.append(sa.Column("tg_file_id", sa.String(length=256), nullable=True))
    shaped += [
        sa.Column("retention_class", _enum("retentionclass", *_RETENTION), nullable=False),
        sa.Column("legal_hold_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
    ]
    if not is_output:
        shaped.append(sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True))
    shaped += [
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(_LEGAL_HOLD_HAS_EXPIRY, name=op.f(f"ck_{table}_legal_hold_has_expiry")),
        sa.ForeignKeyConstraint(
            ["job_id"],
            [f"{_JOBS}.id"],
            name=op.f(f"fk_{table}_job_id_media_jobs"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f(f"pk_{table}")),
        (
            sa.UniqueConstraint(
                "job_id", "role", "variant", name=op.f(f"uq_{table}_job_id_role_variant")
            )
            if is_output
            else sa.UniqueConstraint(
                "job_id", "role", "ordinal", name=op.f(f"uq_{table}_job_id_role_ordinal")
            )
        ),
    ]
    op.create_table(table, *shaped)


def _media_attempts() -> None:
    op.create_table(
        _ATTEMPTS,
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("job_id", sa.Uuid(), nullable=True),
        sa.Column(
            "stage",
            _enum(
                "mediaattemptstage",
                "screen",
                "script",
                "image",
                "video",
                "tts",
                "stt",
                "mux",
                "output_screen",
                length=16,
            ),
            nullable=False,
        ),
        sa.Column("variant", sa.SmallInteger(), nullable=False),
        sa.Column("provider", sa.String(length=32), nullable=False),
        sa.Column("model_id", sa.String(length=64), nullable=True),
        sa.Column("remote_id", sa.String(length=128), nullable=True),
        sa.Column("attempt", sa.Integer(), nullable=False),
        sa.Column(
            "status",
            _enum(
                "mediaattemptstatus",
                "submitting",
                "submitted",
                "succeeded",
                "failed",
                "rejected",
                "ambiguous",
                length=16,
            ),
            nullable=False,
        ),
        sa.Column("error_code", sa.String(length=48), nullable=True),
        sa.Column("queue_ms", sa.Integer(), nullable=True),
        sa.Column("run_ms", sa.Integer(), nullable=True),
        sa.Column("gpu_seconds", sa.Float(), nullable=True),
        sa.Column("cost_usd", sa.Float(), nullable=True),
        sa.Column(
            "cost_source",
            _enum("costsource", "vendor_reported", "derived", "estimated", length=16),
            nullable=True,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "(cost_usd IS NULL AND cost_source IS NULL)"
            " OR (cost_usd IS NOT NULL AND cost_source IS NOT NULL)",
            name=op.f("ck_media_attempts_cost_carries_its_source"),
        ),
        sa.ForeignKeyConstraint(
            ["job_id"],
            [f"{_JOBS}.id"],
            name=op.f("fk_media_attempts_job_id_media_jobs"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_media_attempts")),
        sa.UniqueConstraint(
            "job_id",
            "stage",
            "variant",
            "attempt",
            name=op.f("uq_media_attempts_job_id_stage_variant_attempt"),
        ),
    )


def _media_money() -> None:
    op.create_table(
        _PURCHASES,
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("telegram_user_id", sa.BigInteger(), nullable=True),
        sa.Column("job_id", sa.Uuid(), nullable=False),
        sa.Column("sku", _enum("mediasku", *_SKU), nullable=False),
        sa.Column("amount_minor", sa.Integer(), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column(
            "provider",
            _enum("mediapurchaseprovider", "payme", "beta", "credit", length=16),
            nullable=False,
        ),
        sa.Column("reference", sa.String(length=64), nullable=False),
        sa.Column("idempotency_key", sa.String(length=128), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "amount_minor >= 0", name=op.f("ck_media_purchases_amount_not_negative")
        ),
        # No ForeignKeyConstraint to media_jobs: the receipt outlives the job row.
        sa.PrimaryKeyConstraint("id", name=op.f("pk_media_purchases")),
        sa.UniqueConstraint("idempotency_key", name=op.f("uq_media_purchases_idempotency_key")),
    )
    op.create_table(
        _LEDGER,
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("telegram_user_id", sa.BigInteger(), nullable=True),
        sa.Column("sku", _enum("mediasku", *_SKU), nullable=False),
        sa.Column("delta", sa.SmallInteger(), nullable=False),
        sa.Column(
            "reason",
            _enum(
                "mediacreditreason",
                "generation_failed",
                "output_blocked",
                "deadline",
                "late_settlement",
                "spent",
                "admin_correction",
            ),
            nullable=False,
        ),
        sa.Column("job_id", sa.Uuid(), nullable=True),
        sa.Column("actor", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            _DELTA_MATCHES_REASON, name=op.f("ck_media_credit_ledger_delta_matches_reason")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_media_credit_ledger")),
    )
    op.create_table(
        _BALANCES,
        sa.Column("telegram_user_id", sa.BigInteger(), autoincrement=False, nullable=False),
        sa.Column("sku", _enum("mediasku", *_SKU), nullable=False),
        sa.Column("balance", sa.Integer(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "balance >= 0", name=op.f("ck_media_credit_balances_balance_not_negative")
        ),
        sa.PrimaryKeyConstraint("telegram_user_id", "sku", name=op.f("pk_media_credit_balances")),
    )


def upgrade() -> None:
    _media_jobs()
    _media_bytes(
        _INPUTS,
        _enum("mediainputrole", "photo", "voice_note", "collage", length=16),
        is_output=False,
    )
    _media_bytes(
        _OUTPUTS,
        _enum("mediaoutputrole", "image", "video_raw", "narration", "video", length=16),
        is_output=True,
    )
    _media_attempts()
    _media_money()

    # Every index through batch mode (render_as_batch=True), as in every revision here.
    for table, column, unique in _TEMPLATED_INDEXES:
        with op.batch_alter_table(table, schema=None) as batch_op:
            batch_op.create_index(batch_op.f(f"ix_{table}_{column}"), [column], unique=unique)
    for table, name, columns in _COMPOSITE_INDEXES:
        with op.batch_alter_table(table, schema=None) as batch_op:
            batch_op.create_index(name, list(columns), unique=False)

    # The partial unique indexes: bare ``op.create_index``, 0010's and 0028's shape — an
    # index needs no table rewrite, and the predicate renders on both engines.
    op.create_index(
        _OPEN_REQUEST_INDEX,
        _JOBS,
        ["telegram_user_id", "kind"],
        unique=True,
        postgresql_where=sa.text(_OPEN_REQUEST_PREDICATE),
        sqlite_where=sa.text(_OPEN_REQUEST_PREDICATE),
    )
    op.create_index(
        _ONE_REFUND_INDEX,
        _LEDGER,
        ["job_id"],
        unique=True,
        postgresql_where=sa.text(_ONE_REFUND_PREDICATE),
        sqlite_where=sa.text(_ONE_REFUND_PREDICATE),
    )
    op.create_index(
        _ONE_SPEND_INDEX,
        _LEDGER,
        ["job_id"],
        unique=True,
        postgresql_where=sa.text(_ONE_SPEND_PREDICATE),
        sqlite_where=sa.text(_ONE_SPEND_PREDICATE),
    )

    with op.batch_alter_table(_INTENTS, schema=None) as batch_op:
        batch_op.add_column(sa.Column(_RESUME_MEDIA_JOB_ID, sa.Uuid(), nullable=True))
    with op.batch_alter_table(_USAGE, schema=None) as batch_op:
        batch_op.add_column(sa.Column(_MEDIA_JOB_ID, sa.Uuid(), nullable=True))
        batch_op.create_index(
            batch_op.f(f"ix_{_USAGE}_{_MEDIA_JOB_ID}"), [_MEDIA_JOB_ID], unique=False
        )

    with op.batch_alter_table(_PURGE_RUNS, schema=None) as batch_op:
        for column in _PURGE_RUNS_COLUMNS:
            batch_op.add_column(
                sa.Column(column, sa.Integer(), nullable=False, server_default=sa.text("0"))
            )


def downgrade() -> None:
    with op.batch_alter_table(_PURGE_RUNS, schema=None) as batch_op:
        for column in reversed(_PURGE_RUNS_COLUMNS):
            batch_op.drop_column(column)

    with op.batch_alter_table(_USAGE, schema=None) as batch_op:
        batch_op.drop_index(batch_op.f(f"ix_{_USAGE}_{_MEDIA_JOB_ID}"))
        batch_op.drop_column(_MEDIA_JOB_ID)
    with op.batch_alter_table(_INTENTS, schema=None) as batch_op:
        batch_op.drop_column(_RESUME_MEDIA_JOB_ID)

    op.drop_index(_ONE_SPEND_INDEX, table_name=_LEDGER)
    op.drop_index(_ONE_REFUND_INDEX, table_name=_LEDGER)
    op.drop_index(_OPEN_REQUEST_INDEX, table_name=_JOBS)
    for table, name, _ in reversed(_COMPOSITE_INDEXES):
        with op.batch_alter_table(table, schema=None) as batch_op:
            batch_op.drop_index(name)
    for table, column, _ in reversed(_TEMPLATED_INDEXES):
        with op.batch_alter_table(table, schema=None) as batch_op:
            batch_op.drop_index(batch_op.f(f"ix_{table}_{column}"))

    # Children before the parent they reference.
    for table in (_BALANCES, _LEDGER, _PURCHASES, _ATTEMPTS, _OUTPUTS, _INPUTS, _JOBS):
        op.drop_table(table)
