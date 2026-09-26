"""Initial schema: users, orders, briefs, assets, name_records, generation_attempts.

Revision ID: 0001
Revises: —
Create Date: 2026-08-27

Three properties of this schema are legal requirements rather than design preferences, and
a later migration that breaks any of them is a defect:

1. **No recipient birth year, in any column.** ``briefs.event_day`` and
   ``briefs.event_month`` are the whole of the occasion date (SoW FR-102, DAT-5, LR-69).
   ``tests/test_db/test_privacy_constraints.py`` scans both this file and the live metadata
   and fails the build if a year-shaped column ever appears.

2. **The personal-data record is separable from the transaction record** (SoW DAT-3). The
   recipient lives in ``briefs`` and nowhere else, so the 30-day note clock and the 90-day
   identity clock can run without touching ``orders``, which must survive for as long as
   tax law requires.

3. **Every table carrying personal data carries its own ``expires_at``**, indexed, so the
   FIL-7 purge is one bounded predicate per table rather than a join across the schema.

``generation_attempts.order_id`` is nullable with ``ON DELETE SET NULL`` on purpose: a name
preview happens before an order exists, and the tuning signal must outlive the order it
came from or it evaporates on the first purge run.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "name_records",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("grapheme", sa.String(length=40), nullable=False),
        sa.Column("grapheme_normalized", sa.String(length=80), nullable=False),
        sa.Column(
            "language",
            sa.Enum(
                "uz_latn", "uz_cyrl", "ru", "en", name="language", native_enum=False, length=32
            ),
            nullable=False,
        ),
        sa.Column(
            "script",
            sa.Enum("latin", "cyrillic", name="script", native_enum=False, length=32),
            nullable=False,
        ),
        sa.Column("variant_ordinal", sa.Integer(), nullable=False),
        sa.Column("display_form", sa.String(length=40), nullable=False),
        sa.Column("candidates", sa.JSON(), nullable=False),
        sa.Column("ipa", sa.String(length=160), nullable=True),
        sa.Column("stressed_form", sa.String(length=80), nullable=True),
        sa.Column("syllables", sa.String(length=80), nullable=True),
        sa.Column(
            "source",
            sa.Enum(
                "curated",
                "user_confirmed",
                "llm_generated",
                "g2p",
                name="namesource",
                native_enum=False,
                length=32,
            ),
            nullable=False,
        ),
        sa.Column("source_reference", sa.String(length=200), nullable=True),
        sa.Column("licence", sa.String(length=200), nullable=True),
        sa.Column("contributor", sa.String(length=200), nullable=True),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("usage_count", sa.Integer(), nullable=False),
        sa.Column("success_count", sa.Integer(), nullable=False),
        sa.Column("correction_count", sa.Integer(), nullable=False),
        sa.Column("verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_name_records")),
        sa.UniqueConstraint(
            "grapheme_normalized",
            "language",
            "variant_ordinal",
            name=op.f("uq_name_records_grapheme_normalized_language_variant_ordinal"),
        ),
    )
    with op.batch_alter_table("name_records", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_name_records_created_at"), ["created_at"], unique=False
        )
        batch_op.create_index(
            batch_op.f("ix_name_records_expires_at"), ["expires_at"], unique=False
        )
        batch_op.create_index(
            "ix_name_records_lookup", ["grapheme_normalized", "language"], unique=False
        )

    op.create_table(
        "users",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("telegram_user_id", sa.BigInteger(), nullable=False),
        sa.Column(
            "ui_language",
            sa.Enum(
                "uz_latn", "uz_cyrl", "ru", "en", name="language", native_enum=False, length=32
            ),
            nullable=False,
        ),
        sa.Column("is_blocked", sa.Boolean(), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_users")),
        sa.UniqueConstraint("telegram_user_id", name=op.f("uq_users_telegram_user_id")),
    )
    with op.batch_alter_table("users", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_users_created_at"), ["created_at"], unique=False)

    op.create_table(
        "orders",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("telegram_user_id", sa.BigInteger(), nullable=False),
        sa.Column(
            "state",
            sa.Enum(
                "draft",
                "brief_ready",
                "lyrics_ready",
                "authorized",
                "generating",
                "delivered",
                "failed",
                "cancelled",
                name="orderstate",
                native_enum=False,
                length=32,
            ),
            nullable=False,
        ),
        sa.Column("correlation_id", sa.String(length=128), nullable=False),
        sa.Column("is_paid", sa.Boolean(), nullable=False),
        sa.Column("delivered_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("failed_reason", sa.String(length=256), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("fk_orders_user_id_users"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_orders")),
    )
    with op.batch_alter_table("orders", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_orders_correlation_id"), ["correlation_id"], unique=False
        )
        batch_op.create_index(batch_op.f("ix_orders_created_at"), ["created_at"], unique=False)
        batch_op.create_index(batch_op.f("ix_orders_state"), ["state"], unique=False)
        batch_op.create_index(
            batch_op.f("ix_orders_telegram_user_id"), ["telegram_user_id"], unique=False
        )
        batch_op.create_index(batch_op.f("ix_orders_user_id"), ["user_id"], unique=False)

    op.create_table(
        "assets",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("order_id", sa.Uuid(), nullable=False),
        sa.Column(
            "kind",
            sa.Enum(
                "song",
                "greeting",
                "lyric_sheet",
                "cover",
                name="assetkind",
                native_enum=False,
                length=32,
            ),
            nullable=False,
        ),
        sa.Column("variant_index", sa.Integer(), nullable=False),
        sa.Column("path", sa.String(length=512), nullable=False),
        sa.Column("storage_key", sa.String(length=512), nullable=True),
        sa.Column("mime", sa.String(length=64), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("duration_s", sa.Float(), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("loudness_lufs", sa.Float(), nullable=True),
        sa.Column("persona_id", sa.String(length=64), nullable=True),
        sa.Column("tg_file_id", sa.String(length=128), nullable=True),
        sa.Column("name_candidate_text", sa.String(length=80), nullable=True),
        sa.Column(
            "name_candidate_strategy",
            sa.Enum(
                "canonical",
                "stripped",
                "ascii",
                "cyrillic",
                "hyphenated",
                "phonetic",
                name="namestrategy",
                native_enum=False,
                length=32,
            ),
            nullable=True,
        ),
        sa.Column("name_candidate_rank", sa.Integer(), nullable=True),
        sa.Column("payload", sa.JSON(), nullable=True),
        sa.Column(
            "retention_class",
            sa.Enum(
                "paid_audio",
                "free_output",
                "ephemeral",
                name="retentionclass",
                native_enum=False,
                length=32,
            ),
            nullable=False,
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["order_id"], ["orders.id"], name=op.f("fk_assets_order_id_orders"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_assets")),
        sa.UniqueConstraint(
            "order_id", "kind", "variant_index", name=op.f("uq_assets_order_id_kind_variant_index")
        ),
    )
    with op.batch_alter_table("assets", schema=None) as batch_op:
        batch_op.create_index("ix_assets_expiry_sweep", ["expires_at"], unique=False)
        batch_op.create_index(batch_op.f("ix_assets_order_id"), ["order_id"], unique=False)
        batch_op.create_index(batch_op.f("ix_assets_sha256"), ["sha256"], unique=False)

    op.create_table(
        "briefs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("order_id", sa.Uuid(), nullable=False),
        sa.Column(
            "occasion",
            sa.Enum(
                "birthday", "anniversary", "custom", name="occasion", native_enum=False, length=32
            ),
            nullable=False,
        ),
        sa.Column(
            "genre",
            sa.Enum(
                "pop",
                "retro_estrada",
                "hip_hop",
                "rock",
                "acoustic_ballad",
                "dance_electronic",
                "uzbek_pop",
                "uzbek_folk",
                "shashmaqom",
                "jazz_lounge",
                name="genre",
                native_enum=False,
                length=32,
            ),
            nullable=False,
        ),
        sa.Column(
            "vocal_gender",
            sa.Enum(
                "female", "male", "duet", "any", name="voicegender", native_enum=False, length=32
            ),
            nullable=False,
        ),
        sa.Column(
            "ui_language",
            sa.Enum(
                "uz_latn", "uz_cyrl", "ru", "en", name="language", native_enum=False, length=32
            ),
            nullable=False,
        ),
        sa.Column(
            "output_language",
            sa.Enum(
                "uz_latn", "uz_cyrl", "ru", "en", name="language", native_enum=False, length=32
            ),
            nullable=False,
        ),
        sa.Column("note", sa.String(length=600), nullable=True),
        sa.Column("note_expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("note_purged_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("recipient_name_raw", sa.String(length=40), nullable=True),
        sa.Column("recipient_name_display", sa.String(length=40), nullable=True),
        sa.Column("recipient_lookup_key", sa.String(length=80), nullable=True),
        sa.Column(
            "recipient_script",
            sa.Enum("latin", "cyrillic", name="script", native_enum=False, length=32),
            nullable=True,
        ),
        sa.Column(
            "recipient_language",
            sa.Enum(
                "uz_latn", "uz_cyrl", "ru", "en", name="language", native_enum=False, length=32
            ),
            nullable=True,
        ),
        sa.Column("recipient_candidates", sa.JSON(), nullable=True),
        sa.Column("identity_expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("identity_purged_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("event_day", sa.SmallInteger(), nullable=True),
        sa.Column("event_month", sa.SmallInteger(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "event_day IS NULL OR (event_day BETWEEN 1 AND 31)",
            name=op.f("ck_briefs_event_day_range"),
        ),
        sa.CheckConstraint(
            "event_month IS NULL OR (event_month BETWEEN 1 AND 12)",
            name=op.f("ck_briefs_event_month_range"),
        ),
        sa.ForeignKeyConstraint(
            ["order_id"], ["orders.id"], name=op.f("fk_briefs_order_id_orders"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_briefs")),
        sa.UniqueConstraint("order_id", name=op.f("uq_briefs_order_id")),
    )
    with op.batch_alter_table("briefs", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_briefs_created_at"), ["created_at"], unique=False)
        batch_op.create_index(
            batch_op.f("ix_briefs_identity_expires_at"), ["identity_expires_at"], unique=False
        )
        batch_op.create_index(
            batch_op.f("ix_briefs_note_expires_at"), ["note_expires_at"], unique=False
        )
        batch_op.create_index(
            batch_op.f("ix_briefs_recipient_lookup_key"), ["recipient_lookup_key"], unique=False
        )

    op.create_table(
        "generation_attempts",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("order_id", sa.Uuid(), nullable=True),
        sa.Column(
            "kind",
            sa.Enum(
                "song",
                "song_inpaint",
                "greeting",
                "lyrics",
                "name_preview",
                "name_verification",
                "cover",
                name="generationkind",
                native_enum=False,
                length=32,
            ),
            nullable=False,
        ),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("provider", sa.String(length=64), nullable=True),
        sa.Column("provider_remote_id", sa.String(length=128), nullable=True),
        sa.Column("attempt", sa.Integer(), nullable=False),
        sa.Column("is_success", sa.Boolean(), nullable=False),
        sa.Column(
            "language",
            sa.Enum(
                "uz_latn", "uz_cyrl", "ru", "en", name="language", native_enum=False, length=32
            ),
            nullable=True,
        ),
        sa.Column(
            "name_candidate_strategy",
            sa.Enum(
                "canonical",
                "stripped",
                "ascii",
                "cyrillic",
                "hyphenated",
                "phonetic",
                name="namestrategy",
                native_enum=False,
                length=32,
            ),
            nullable=True,
        ),
        sa.Column("name_candidate_rank", sa.Integer(), nullable=True),
        sa.Column("is_name_verified", sa.Boolean(), nullable=True),
        sa.Column("match_confidence", sa.Float(), nullable=True),
        sa.Column("name_candidate_text", sa.String(length=80), nullable=True),
        sa.Column("stt_transcript", sa.String(length=200), nullable=True),
        sa.Column("identity_expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("identity_purged_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_code", sa.String(length=48), nullable=True),
        sa.Column("error_message", sa.String(length=500), nullable=True),
        sa.Column("cost_usd", sa.Float(), nullable=False),
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
            nullable=False,
        ),
        sa.Column("latency_ms", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["order_id"],
            ["orders.id"],
            name=op.f("fk_generation_attempts_order_id_orders"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_generation_attempts")),
    )
    with op.batch_alter_table("generation_attempts", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_generation_attempts_created_at"), ["created_at"], unique=False
        )
        batch_op.create_index(
            "ix_generation_attempts_identity_sweep", ["identity_expires_at"], unique=False
        )
        batch_op.create_index(
            batch_op.f("ix_generation_attempts_order_id"), ["order_id"], unique=False
        )
        batch_op.create_index(
            "ix_generation_attempts_tuning",
            ["name_candidate_strategy", "is_name_verified"],
            unique=False,
        )


def downgrade() -> None:
    with op.batch_alter_table("generation_attempts", schema=None) as batch_op:
        batch_op.drop_index("ix_generation_attempts_tuning")
        batch_op.drop_index(batch_op.f("ix_generation_attempts_order_id"))
        batch_op.drop_index("ix_generation_attempts_identity_sweep")
        batch_op.drop_index(batch_op.f("ix_generation_attempts_created_at"))

    op.drop_table("generation_attempts")
    with op.batch_alter_table("briefs", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_briefs_recipient_lookup_key"))
        batch_op.drop_index(batch_op.f("ix_briefs_note_expires_at"))
        batch_op.drop_index(batch_op.f("ix_briefs_identity_expires_at"))
        batch_op.drop_index(batch_op.f("ix_briefs_created_at"))

    op.drop_table("briefs")
    with op.batch_alter_table("assets", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_assets_sha256"))
        batch_op.drop_index(batch_op.f("ix_assets_order_id"))
        batch_op.drop_index("ix_assets_expiry_sweep")

    op.drop_table("assets")
    with op.batch_alter_table("orders", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_orders_user_id"))
        batch_op.drop_index(batch_op.f("ix_orders_telegram_user_id"))
        batch_op.drop_index(batch_op.f("ix_orders_state"))
        batch_op.drop_index(batch_op.f("ix_orders_created_at"))
        batch_op.drop_index(batch_op.f("ix_orders_correlation_id"))

    op.drop_table("orders")
    with op.batch_alter_table("users", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_users_created_at"))

    op.drop_table("users")
    with op.batch_alter_table("name_records", schema=None) as batch_op:
        batch_op.drop_index("ix_name_records_lookup")
        batch_op.drop_index(batch_op.f("ix_name_records_expires_at"))
        batch_op.drop_index(batch_op.f("ix_name_records_created_at"))

    op.drop_table("name_records")
