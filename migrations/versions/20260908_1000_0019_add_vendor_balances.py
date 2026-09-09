"""Add vendor_balances.

Revision ID: 0019
Revises: 0018
Create Date: 2026-09-08

Nothing in this system polls OpenRouter or ElevenLabs for remaining credit. The one quota
call that exists reads ``characters_remaining`` into a live, in-memory ``ProviderHealth``
verdict that is never persisted and never reaches the admin, so "are we about to run out"
is a question the panel cannot answer at all. This revision adds the table the answer can
be cached in.

**WHY A TABLE AND NOT A SETTING OR A REDIS KEY.** A balance is a MEASUREMENT with a
provenance and an age, and both must survive a worker restart and be readable by a process
that is FORBIDDEN from taking the measurement itself: the admin must never hold an HTTP
client and a vendor key (ADMIN_PANEL_PLAN §4.2), which is the entire reason the panel runs
as a third process. A setting cannot hold a measurement. Redis is where this would naturally
go and is wrong twice: the admin would then need a Redis client on a key the worker writes
with no schema and no constraint, and the null-never-zero and estimate-carries-its-basis
rules below would become two more things application code has to remember instead of two
things the database refuses.

**WHY EVERY QUANTITY IS NULLABLE WITH NO DEFAULT — 0016's paragraph, sharpened for money
not yet spent rather than money already spent.** A ``balance_remaining`` DEFAULT 0 says "the
account is empty". OBS-10 raises SEV-1 when a capability's last healthy provider hits zero
and SEV-2 below seven days of cover, so a defaulted zero pages an on-call engineer about a
deployment that was merely never polled — and the third such page is the one nobody reads.
It is the same defect as ``generation_attempts.cost_usd DEFAULT 0.0``, except that one reads
as "free" and this one reads as "stop shipping". ``NULL`` means "not polled", or "polled and
not reported"; both are true statements about a measurement nobody has.

``is_unbounded`` is three-valued for the same discipline: TRUE means the vendor said this key
has no cap, FALSE means it said there is one, NULL means it did not say. A two-valued NOT
NULL column would force "we do not know" to be spelled as one of the two answers, and both
spellings invent a fact.

**THE TWO CLOCKS.** ``fetched_at`` is when the quantities were MEASURED; ``checked_at`` is
when the poller last TRIED. A failed poll advances only ``checked_at``, increments
``consecutive_failures``, records ``http_status``/``error_code``, and touches no quantity and
not ``fetched_at``. The row then reads "$12.40, measured 5h ago, last 4 probes failed" — the
operationally useful sentence. One ``polled_at`` would force a choice between a timestamp
that lies about a figure's age and a figure deleted the moment the vendor goes down, which
is exactly when an operator wants the last known number.

**THE THREE CHECK CONSTRAINTS.**

``ck_vendor_balances_estimate_carries_its_basis`` is the direct descendant of
``ck_vendor_usage_cost_carries_its_source``, one step further on. An estimate with no basis
is unreadable — nobody can tell a figure derived from measured USD spend from one derived
from TTS characters that exclude the music leg, and the two deserve different trust — and an
estimate with no divisor cannot be reproduced when somebody asks why the tile said forty
songs. Three columns move together or none of them do, enforced here rather than trusted to
the one writer, because the writer will eventually be two.

``ck_vendor_balances_a_measured_balance_carries_its_time`` is the schema-level guarantee
that makes the whole failure design safe: a quantity may not exist without the instant it
was measured at. It forbids the plausible-looking bug — a failure path that clears
``fetched_at`` while leaving the last known balance behind, producing a number with no age
that a tile renders as current. It is written as a one-directional implication and not a
biconditional on purpose: ``fetched_at`` may legitimately be set with every quantity NULL,
which is a vendor that answered 200 with a body reporting nothing — a different fact from a
failed poll, and one that must remain expressible.

``ck_vendor_balances_consecutive_failures_is_not_negative`` guards the only column whose
UPDATE clause carries an increment expression. It costs nothing and turns an arithmetic
mistake in the upsert into a write failure rather than a nonsense number on a tile.

Deliberately NO constraint tying ``error_code`` to ``is_last_poll_ok``, following
``vendor_usage`` exactly: over-constraining a telemetry table loses rows, and a lost row is a
hole in the record where a nonsensical pairing is merely confusing. And deliberately none
tying ``is_unbounded`` to ``balance_total``, because the honest combinations include ones a
naive rule would reject.

**THE ONE PERMITTED ZERO.** ``consecutive_failures`` is NOT NULL with ``server_default="0"``
because it is a COUNT, and "no probe has failed" IS a measurement — the identical carve-out
0016 makes for ``purge_runs.vendor_usage_deleted``. ``checked_at`` and ``is_last_poll_ok``
are NOT NULL for a different reason: no row is ever created except by a poll attempt, so both
are known facts at write time rather than measurements that might be missing. ``vendor``,
``is_fallback``, ``provider`` and ``balance_unit`` are NOT NULL because none is a measurement
at all — they are the identity and shape of the account, known from ``Settings`` before any
request leaves the box.

**WHY THE PRIMARY KEY IS COMPOSITE AND THERE IS NO SURROGATE ID.** One row per billing
account, so a duplicate should be IMPOSSIBLE rather than merely unusual. The writer's
``INSERT … ON CONFLICT`` names exactly ``(vendor, is_fallback)`` as its conflict target, so
the primary key IS that target and no separate unique index is needed. ``is_fallback`` is the
same axis ``vendor_usage`` uses to tell the two OpenRouter accounts apart, for the same
stated reason: both LLM adapters report ``name="openai-compat"``.

**THE ONLY INDEX IS THE ONE THE MODEL DECLARES, AND IT EARNS NOTHING.**
``TimestampMixin.created_at`` carries ``index=True``, and
``test_the_migrated_indexes_match_the_model_metadata`` compares migrated schema against model
metadata by name — so omitting ``ix_vendor_balances_created_at`` would leave the model
declaring an index the chain never builds, which is a worse defect than a useless index on a
three-row table. Everything else is deliberately unindexed: the admin read is ``SELECT *
ORDER BY vendor, is_fallback`` over at most ten rows, smaller than one page on either engine;
there is no window predicate because the table holds no history; and nothing filters on
``fetched_at``, because staleness is judged per row by the reader. Contrast 0016, which
indexed ``cost_usd`` for a query that finds NOTHING twelve times a minute: an index earns its
keep on the rows it does not find only when the table is large, and this one never will be.

**NO RETENTION CUTOFF, AND NOTHING IS ADDED TO ``hbd.db.purge`` — read the absence as a
decision, not an oversight.** The table is bounded BY CONSTRUCTION: its primary key is a
five-member enum crossed with a boolean, so it can hold at most ten rows ever and holds three
in this deployment, and a row is UPDATEd in place rather than appended. Registering a cutoff
would schedule a predicate over a three-row table — a no-op whose harmlessness every future
reader has to re-derive — and would add a ``purge_runs`` counter that is permanently zero,
exactly the kind of unmeasured-looking number these conventions exist to prevent. The history
a cache discards is not lost and is not unclocked: every probe also writes a ``vendor_usage``
row with ``operation=HEALTH``, and that table already carries the 400-day cutoff, so the
retention story lives in one place and in the table that actually grows.
``quota_resets_at`` is NOT a retention clock — it is a fact the VENDOR reports about ITS
billing period, and its name deliberately avoids the ``*_expires_at`` suffix, which obliges a
sweep BY NAME in ``tests/test_db/test_audit_retention.py``.

**NOT PERSONAL DATA.** Every column is a closed enum, a number, a boolean, an instant, a
machine id, a bounded string from the vendor's own vocabulary or a bounded error code from
the ``hbd.errors`` taxonomy — the row is about OUR account with a vendor, not about a
customer. One field was available and is deliberately NOT stored: OpenRouter's ``data.label``
is the operator's own free-text name for the key and reads in practice like "Sardor laptop
dev key". It is the only field on either vendor's response that could carry a person's name,
it buys no tile anything, and refusing it is what keeps this classification true rather than
nearly true. The omission from both sets in
``tests/test_db/test_privacy_constraints.py`` is recorded there as a comment.

**Every enum is spelled literally**, never imported: a migration that imports application
code breaks historically, on a revision that already ran everywhere. ``enum_type`` renders
``VARCHAR(32)`` with ``create_constraint`` off, so a later ``BalanceEstimateBasis`` member
needs no migration at all.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0019"
down_revision: str | None = "0018"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLE = "vendor_balances"

#: The only index, and it exists only because ``TimestampMixin`` declares it. See above.
_INDEXES = ("created_at",)


def upgrade() -> None:
    op.create_table(
        _TABLE,
        # -- identity: the composite primary key --------------------------------
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
        sa.Column("is_fallback", sa.Boolean(), nullable=False),
        # -- shape: known before any poll, so NOT NULL --------------------------
        sa.Column("provider", sa.String(length=64), nullable=False),
        sa.Column(
            "balance_unit",
            sa.Enum("usd", "characters", name="balanceunit", native_enum=False, length=32),
            nullable=False,
        ),
        # -- quantities: every one nullable, no server default ------------------
        sa.Column("balance_remaining", sa.Float(), nullable=True),
        sa.Column("balance_total", sa.Float(), nullable=True),
        sa.Column("balance_used", sa.Float(), nullable=True),
        sa.Column("is_unbounded", sa.Boolean(), nullable=True),
        sa.Column("quota_resets_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("quota_reset_hint", sa.String(length=32), nullable=True),
        sa.Column("plan_tier", sa.String(length=48), nullable=True),
        sa.Column("subscription_status", sa.String(length=32), nullable=True),
        sa.Column("songs_remaining", sa.Integer(), nullable=True),
        sa.Column("per_song_rate", sa.Float(), nullable=True),
        sa.Column(
            "estimate_basis",
            sa.Enum(
                "trailing_spend_usd",
                "trailing_tts_characters",
                name="balanceestimatebasis",
                native_enum=False,
                length=32,
            ),
            nullable=True,
        ),
        # -- the two clocks ------------------------------------------------------
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("checked_at", sa.DateTime(timezone=True), nullable=False),
        # -- last-probe outcome --------------------------------------------------
        sa.Column("is_last_poll_ok", sa.Boolean(), nullable=False),
        sa.Column("http_status", sa.Integer(), nullable=True),
        sa.Column("error_code", sa.String(length=48), nullable=True),
        sa.Column("consecutive_failures", sa.Integer(), nullable=False, server_default="0"),
        # -- TimestampMixin ------------------------------------------------------
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "(songs_remaining IS NULL AND per_song_rate IS NULL AND estimate_basis IS NULL)"
            " OR (songs_remaining IS NOT NULL AND per_song_rate IS NOT NULL"
            " AND estimate_basis IS NOT NULL)",
            name=op.f("ck_vendor_balances_estimate_carries_its_basis"),
        ),
        sa.CheckConstraint(
            "(balance_remaining IS NULL AND balance_total IS NULL AND balance_used IS NULL)"
            " OR fetched_at IS NOT NULL",
            name=op.f("ck_vendor_balances_a_measured_balance_carries_its_time"),
        ),
        sa.CheckConstraint(
            "consecutive_failures >= 0",
            name=op.f("ck_vendor_balances_consecutive_failures_is_not_negative"),
        ),
        # No ForeignKeyConstraint anywhere: ``vendor`` is an enum value, not a row.
        sa.PrimaryKeyConstraint("vendor", "is_fallback", name=op.f("pk_vendor_balances")),
    )
    with op.batch_alter_table(_TABLE, schema=None) as batch_op:
        # Batch mode regardless of size: SQLite cannot ALTER an existing table to add an
        # index without a rebuild, and every index in this project is created this way.
        for column in _INDEXES:
            batch_op.create_index(batch_op.f(f"ix_{_TABLE}_{column}"), [column], unique=False)


def downgrade() -> None:
    with op.batch_alter_table(_TABLE, schema=None) as batch_op:
        for column in reversed(_INDEXES):
            batch_op.drop_index(batch_op.f(f"ix_{_TABLE}_{column}"))

    op.drop_table(_TABLE)
