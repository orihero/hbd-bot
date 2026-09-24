"""Record who accepted which Terms of Use and Privacy Notice (IMAGE_VIDEO_SPEC §3.2.1).

Revision ID: 0030
Revises: 0029
Create Date: 2026-09-24

One new table, ``terms_acceptances``, and one counter on ``purge_runs``. Nothing else.

``terms_acceptances`` is the lawful-basis record behind the Terms + Privacy gate every
account passes before first use (IMAGE_VIDEO_SPEC §2.1, D26): one APPEND-ONLY row per
(account, terms version, privacy version), made idempotent by
``UNIQUE (telegram_user_id, terms_version, privacy_version)`` so a double tap or a replayed
update writes one row. That constraint leads with ``telegram_user_id``, so it doubles as the
index the gate's lookup and ``/forget``'s anonymising ``UPDATE`` read; there is no separate
single-column index on it. ``accepted_at`` IS indexed, for the retention cutoff.

**``telegram_user_id`` is NULLABLE only so erasure has somewhere to go** — the third retention
route (IMAGE_VIDEO_SPEC §3.2.4), ``broadcast_recipients``' shape: ``/forget`` nulls the id and
keeps the row, and a 400-day cutoff over anonymised rows bounds growth. Both engines permit
any number of NULLs in a unique constraint, so an anonymised row stops participating in it.
No column ends in ``*_expires_at``: that suffix is this codebase's word for a published
per-row clock, and this table has none.

``purge_runs.terms_acceptances_deleted`` counts that cutoff. NOT NULL with a server default
of zero, 0024's precedent: existing sweep records must answer something, and zero is the true
answer — the table did not exist when they ran.

No backfill: the table is created EMPTY. Nobody has accepted a versioned text yet, and
inventing acceptances for existing accounts would fabricate the very record this table exists
to hold. Every existing account is therefore shown the terms screen on its next message
(M1.2's gate), which is the intended rollout.

Enums are spelled literally and clocks are plain ``sa.DateTime(timezone=True)``: no migration
in this project imports application code (``test_no_migration_imports_application_code``).

**The downgrade drops every acceptance ever recorded**, and nothing else holds a copy. Rolling
back past 0030 is a decision to lose the proof that any account agreed to the Terms.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0030"
down_revision: str | None = "0029"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLE = "terms_acceptances"
_PURGE_RUNS = "purge_runs"
_PURGE_RUNS_COLUMN = "terms_acceptances_deleted"

#: Spelled as literals rather than imported from ``bayram.db.models.terms_acceptance``, for
#: the reason stated in the module docstring.
_VERSION_LENGTH = 32
_LANGUAGE_LENGTH = 8
_SOURCE_LENGTH = 16

#: Hand-named rather than templated: ``uq_%(table_name)s_%(column_0_N_name)s`` renders 67
#: characters here, past Postgres's 63-character identifier limit, and Postgres would
#: truncate it silently where SQLite keeps it whole. Spelled identically on the model.
_UNIQUE_CONSTRAINT = "uq_terms_acceptances_account_versions"

#: ``(column, unique)``, created through ``batch_op.f()`` so it takes ``NAMING_CONVENTION``'s
#: ``ix`` template and matches the model's ``index=True``.
_INDEXES: tuple[tuple[str, bool], ...] = (("accepted_at", False),)


def upgrade() -> None:
    op.create_table(
        _TABLE,
        sa.Column("id", sa.Uuid(), nullable=False),
        # Nullable ONLY so erasure has somewhere to go — a NULL means /forget ran.
        sa.Column("telegram_user_id", sa.BigInteger(), nullable=True),
        sa.Column("terms_version", sa.String(length=_VERSION_LENGTH), nullable=False),
        sa.Column("privacy_version", sa.String(length=_VERSION_LENGTH), nullable=False),
        sa.Column(
            "language",
            sa.Enum(
                "uz_latn",
                "uz_cyrl",
                "ru",
                "en",
                name="language",
                native_enum=False,
                length=_LANGUAGE_LENGTH,
            ),
            nullable=False,
        ),
        sa.Column("accepted_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "source",
            sa.Enum(
                "onboarding",
                "gate",
                name="termsacceptancesource",
                native_enum=False,
                length=_SOURCE_LENGTH,
            ),
            nullable=True,
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_terms_acceptances")),
        # THE IDEMPOTENCY AUTHORITY, and deliberately NULL-tolerant. See the module docstring.
        # Hand-named: the templated name would be 67 characters, past Postgres's limit.
        sa.UniqueConstraint(
            "telegram_user_id",
            "terms_version",
            "privacy_version",
            name=_UNIQUE_CONSTRAINT,
        ),
    )

    # SQLite cannot ALTER an existing table to add an index without a rebuild, so every
    # index in this project is created inside batch_alter_table (render_as_batch=True).
    with op.batch_alter_table(_TABLE, schema=None) as batch_op:
        for column, unique in _INDEXES:
            batch_op.create_index(batch_op.f(f"ix_{_TABLE}_{column}"), [column], unique=unique)

    with op.batch_alter_table(_PURGE_RUNS, schema=None) as batch_op:
        batch_op.add_column(
            sa.Column(_PURGE_RUNS_COLUMN, sa.Integer(), nullable=False, server_default=sa.text("0"))
        )


def downgrade() -> None:
    # The counter goes first: it counts rows in a table that is about to stop existing.
    with op.batch_alter_table(_PURGE_RUNS, schema=None) as batch_op:
        batch_op.drop_column(_PURGE_RUNS_COLUMN)

    with op.batch_alter_table(_TABLE, schema=None) as batch_op:
        for column, _ in reversed(_INDEXES):
            batch_op.drop_index(batch_op.f(f"ix_{_TABLE}_{column}"))

    op.drop_table(_TABLE)
