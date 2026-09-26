"""Add user_profiles.

Revision ID: 0014
Revises: 0013
Create Date: 2026-09-04

The bot now asks a customer two questions before it will make anything: which language to
speak, and what number to deliver to. This is where those answers live, together with the
``@username``, the name and the profile photo Telegram hands over with the shared contact.
Until this revision the product knew a customer only as an integer, so a song that could
not be delivered in-chat could not be delivered at all.

Three shape decisions, each stated as a decision against a named failure rather than as
schema taste:

* **A table, not columns on ``users``.** ``docs/product/ADMIN_PANEL_PLAN.md:674`` records "No DDL"
  on ``users`` as a standing commitment, and ``credits.set_blocked`` UPSERTs a ``users``
  row so an operator can bar an account that never ordered — so that row must be able to
  outlive everything else we know about a person, which means ``/forget`` must never delete
  it. A phone number and a photograph of a face are exactly what ``/forget`` exists to
  delete. On ``users`` they would quietly survive an erasure, with nothing in the suite
  positioned to notice, because the privacy guards walk tables and not columns.
* **Keyed on ``users.id``, not on ``telegram_user_id``** — deliberately unlike
  ``credit_accounts`` (0006) and ``lyric_budgets`` (0013), which key on Telegram's own id
  because they are charged before any ``users`` row exists. The audited unmask path carries
  a ``UUID`` subject id and scopes its step-up as ``reveal:<str(uuid)>``, so ``users.id`` is
  the identifier that path already speaks; keying on the Telegram id would buy a join on
  every unmask, forever, to answer what the primary key answers for free. The "onboarding
  happens before any order" objection is answered by a ``users`` writer that runs at first
  contact, not by changing the key.
* **No ``avatar_storage_key`` column.** The object key is derived from ``user_id`` at every
  site that needs it. That is the shape in which the archive-orphan bug ``_replace_assets``
  documents — a row naming one spelling of a key while the bytes sit under another, so the
  sweep deletes the record and the bytes stay forever — is structurally impossible rather
  than merely fixed.

**There is no retention clock on this table: no ``profile_expires_at``, no
``profile_purged_at``, and no new ``purge_runs`` column.** The product owner chose "kept
while the account exists" (PD-2), so there is no date to store and no sweep to run:
``/forget`` DELETEs the row and its absence *is* the erasure record. That is enforced and
not merely asserted — ``tests/test_db/test_privacy_constraints.py`` names this table in a
``tables_erased_on_request`` set beside the ``tables_with_personal_data`` set that demands
an ``*_expires_at`` of every member, and asserts the two disjoint, so a personal-data table
is either on a clock or named as erased on request and never silently absent from both.
``tests/test_db/test_audit_retention.py`` ignores this table by construction: both of its
derivations filter on ``name.endswith("expires_at")``.

**There is no backfill INSERT, and that is a decision with three reasons.**

1. A backfill could at best skip the language question. Every existing customer still has a
   NULL phone number, so they still land on the contact question; it would save one tap,
   not the flow.
2. It would have to synthesise ``language_chosen_at`` from ``users.last_seen_at``, which is
   not evidence that anybody chose anything. ``users.ui_language`` is written by the
   inbound touch from the draft's language, and that value is frequently a fallback rather
   than a choice — the language-clobber fix landing alongside this revision exists because
   of exactly that. Backfilling it as a *choice* would enshrine the defect this change
   removes.
3. Onboarding is decided by the phone number, not the language, so a backfilled row
   un-blocks nobody.

The operator-visible consequence, written down so nobody has to infer it: **on the deploy
after this revision every existing customer is asked the language question once and the
contact question once, and never again.**
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0014"
down_revision: str | None = "0013"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None

_TABLE = "user_profiles"


def upgrade() -> None:
    op.create_table(
        _TABLE,
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("telegram_user_id", sa.BigInteger(), nullable=False),
        sa.Column("phone_e164", sa.String(length=16), nullable=True),
        sa.Column("telegram_username", sa.String(length=32), nullable=True),
        sa.Column("first_name", sa.String(length=64), nullable=True),
        sa.Column("last_name", sa.String(length=64), nullable=True),
        sa.Column("avatar_file_unique_id", sa.String(length=64), nullable=True),
        sa.Column("avatar_mime", sa.String(length=64), nullable=True),
        sa.Column("avatar_stored_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("language_chosen_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("phone_shared_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("onboarded_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        # ON DELETE CASCADE although nothing deletes a ``users`` row today: it is the
        # cheapest guarantee that a profile cannot outlive the account it describes, and a
        # profile pointing at a stranger's account is the worst answer this table can give.
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_user_profiles_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("user_id", name=op.f("pk_user_profiles")),
        # Inside create_table, exactly as ``users.telegram_user_id`` is written in 0001:
        # one account can only ever have one profile, so a retried onboarding cannot open a
        # second row that disagrees with the first about the same person's number.
        sa.UniqueConstraint("telegram_user_id", name=op.f("uq_user_profiles_telegram_user_id")),
    )
    with op.batch_alter_table(_TABLE, schema=None) as batch_op:
        # TimestampMixin indexes created_at on every table that uses it; omitting it here
        # would make the migrated schema and Base.metadata disagree, which
        # tests/test_db/test_migrations.py compares index by index.
        batch_op.create_index(
            batch_op.f("ix_user_profiles_created_at"), ["created_at"], unique=False
        )


def downgrade() -> None:
    with op.batch_alter_table(_TABLE, schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_user_profiles_created_at"))

    op.drop_table(_TABLE)
