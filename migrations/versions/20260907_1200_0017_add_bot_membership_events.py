"""Add bot_membership_events, users.blocked_bot_at and the sweep's counter for it.

Revision ID: 0017
Revises: 0016
Create Date: 2026-09-07

A customer blocking the bot was recorded NOWHERE. ``src/bayram/bot/delivery.py`` catches
``TelegramForbiddenError`` only to skip a retry and persists nothing, aiogram's
``my_chat_member`` observer has no handler anywhere in ``src/``, and ``users`` has no column
for it. So the one number that says whether the product is losing its customers — the Churn
card, a period count with a delta and a twelve-bucket sparkline — could not be drawn from
anything in this schema, honestly or otherwise.

**WHY A COLUMN ON ``users`` *AND* A NEW TABLE, rather than either alone.** The column
records the CURRENT state and the LAST transition; the card counts PASSAGES. A column-only
design can only ever count SURVIVORS: an account that blocks on Monday and comes back on
Wednesday has its column set and then cleared, so Monday's bucket silently shrinks and
every historical churn number drifts DOWNWARD exactly when win-backs happen — yesterday's
number stops being yesterday's number. It also conflates three different accounts under one
``NULL`` (never blocked, blocked-and-returned, never observed), so repeat churn and win-back
are invisible. This repo has already named that defect twice, on funnels ("survivors, not
passages") and on order states ("an order that passed through AUTHORIZED and then failed
retains no record of the passage"). The split is not novel either: it is
``credit_accounts.balance`` (current) beside ``credit_ledger`` (history), and it is why the
gauge needs no window function over the event table and why a forgotten account's current
state survives its own anonymisation.

**WHY THE COLUMN IS NULLABLE WITH NO DEFAULT AND NO BACKFILL.** A ``FALSE``, an epoch or a
``now()`` server default would assert something about every row that existed before this
revision ran, and what it would assert is "this account has not blocked us" — when the truth
is that nobody had ever looked. That is ``generation_attempts.cost_usd DEFAULT 0.0`` in
timestamp form: the same substitution of a fabricated fact for an absent measurement, on the
same table this schema's conventions exist to protect. ``NULL`` is also the only honest
encoding of the current state, and it deliberately conflates "never blocked" with "blocked
and came back" — both mean "reachable right now", which is all the gauge asks, and it is
precisely why the column cannot double as the churn history.

**WHY IT IS NOT NAMED ``is_blocked_by_user`` OR ANYTHING CONTAINING ``is_blocked``.**
``users.is_blocked`` already means the OPERATOR's bar, written by ``credits.set_blocked``
from the admin panel. The new column has the customer as the SUBJECT rather than the object:
``WHERE blocked_bot_at IS NOT NULL`` reads "accounts that blocked the bot", ``WHERE
is_blocked`` reads "accounts we blocked". The dashboard draws them as two separate cards, no
query may OR them together, and a name that can be misread is a metric that will be. The
table is ``bot_membership_events`` and deliberately not ``bot_block_events`` for the same
reason: "membership" is Telegram's own word for the fact (``my_chat_member``) and cannot be
mistaken for the operator bar, which is not a membership at all.

**WHY NO PARTIAL INDEX on ``blocked_bot_at``**, even though ``WHERE blocked_bot_at IS NOT
NULL`` is the only predicate it will ever serve and a partial index would be far smaller.
Revision 0016 already records the reason: SQLite and Postgres both accept partial indexes
but they do not round-trip identically through ``inspector.get_indexes``, and
``test_the_migrated_indexes_match_the_model_metadata`` compares migrated schema against
model metadata for a living. The plain index earns its keep anyway — the gauge is
``SELECT count(*) FROM users WHERE blocked_bot_at IS NOT NULL`` on a table that grows with
every person who has ever messaged the bot, and Postgres b-trees index NULLs, so the
``IS NOT NULL`` scan stays on the index.

**WHY ``bot_membership_events`` HAS NO FOREIGN KEY AND NO CHECK CONSTRAINTS.** No FK to
``users``, following ``credit_ledger`` and ``vendor_usage``: the row records a passage that
must outlive any future deletion of the account row, and a cascade would delete the churn
history that explains why the account went. No CHECKs at all, following ``vendor_usage``'s
refusal to tie ``error_code`` to ``is_success``: over-constraining a telemetry table loses
rows, and a lost row is a hole in the churn record where an odd pairing is merely confusing.
The null-never-zero rule is satisfied VACUOUSLY rather than by policy — there is no quantity
column here to default to zero, because the measurement is the EXISTENCE of a row, and a row
is either present or absent.

**WHY ``telegram_user_id`` IS NULLABLE.** Not because it is sometimes unknown — the writer
always knows the account — but because ``/forget`` nulls it in place, exactly as it does on
``credit_ledger`` and ``plan_purchases``. So ``NULL`` means "erased on request" and never "we
did not look", and the day counts survive the erasure that removed the identity. It is
indexed for that ``UPDATE``, which runs inside the transaction a customer's ``/forget`` is
waiting on and must not scan.

**WHY ``purge_runs`` GAINS A COUNTER.** Revision 0016's own reason: a sweep whose count is
not stored is a backlog the panel reports as zero. NOT NULL with ``server_default="0"``
because existing rows have to answer something and for this column zero is the TRUE answer —
those sweeps genuinely deleted no ``bot_membership_events`` rows, because the table did not
exist when they ran. That is the one shape of zero this design allows: a measured count,
never an unmeasured quantity.

**WHY NO ``*_expires_at``.** That suffix obliges a sweep BY NAME in
``tests/test_db/test_audit_retention.py`` and would claim a legal schedule this table does not
have. Its bound is a 400-day CUTOFF on ``at``
(``bayram.db.purge.BOT_MEMBERSHIP_RETENTION_DAYS``) — thirteen months rather than twelve for
``vendor_usage``'s stated reason, that a year-over-year churn comparison needs last March to
still be there on the day it is asked. The table is in NEITHER of
``tests/test_db/test_privacy_constraints.py``'s two sets, and it may not borrow
``vendor_usage``'s argument for that, because unlike ``vendor_usage`` it carries a
``telegram_user_id``; its route is anonymisation, and the omission is recorded in that file as a
comment.

**THIS REVISION BREAKS ``docs/product/ADMIN_PANEL_PLAN.md``'s "No DDL on ``users``" COMMITMENT, and
does so knowingly.** That commitment was made when the panel's phases needed no column, and
the Churn card cannot be built without one. Both model docstrings that cite it —
``models/user.py`` and ``models/user_profile.py`` — are amended in the same change, because
a codebase that argues against its own column teaches the next person to design around a
rule nobody is following. Neither of their arguments actually collapses: the load-bearing
half of each was always the erasure asymmetry (the ``users`` row must survive ``/forget``),
not the DDL freeze.

**Every enum is spelled literally.** A migration that imports application code breaks when
that code is refactored, and it breaks historically, on a revision that already ran
everywhere (``test_no_migration_imports_application_code``). ``enum_type`` renders a plain
``VARCHAR(32)`` with ``create_constraint`` off, so a later member needs no migration at all.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0017"
down_revision: str | None = "0016"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLE = "bot_membership_events"
_USERS_TABLE = "users"
_USERS_COLUMN = "blocked_bot_at"

#: The sweep's own record gains the counter for the sweep this revision creates work for.
_PURGE_RUNS_TABLE = "purge_runs"
_PURGE_RUNS_COLUMN = "membership_events_deleted"

#: Both created through ``batch_op.f()`` so they take ``NAMING_CONVENTION``'s ``ix``
#: template and match exactly what the model's ``index=True`` declares.
_INDEXES = ("telegram_user_id", "at")


def upgrade() -> None:
    with op.batch_alter_table(_USERS_TABLE, schema=None) as batch_op:
        # NULLABLE, NO server default, NO backfill. See the module docstring.
        batch_op.add_column(sa.Column(_USERS_COLUMN, sa.DateTime(timezone=True), nullable=True))
        batch_op.create_index(
            batch_op.f(f"ix_{_USERS_TABLE}_{_USERS_COLUMN}"), [_USERS_COLUMN], unique=False
        )

    op.create_table(
        _TABLE,
        sa.Column("id", sa.Uuid(), nullable=False),
        # Nullable ONLY so that erasure has somewhere to go — see the module docstring.
        sa.Column("telegram_user_id", sa.BigInteger(), nullable=True),
        sa.Column(
            "event",
            sa.Enum(
                "blocked",
                "unblocked",
                name="botmembershipevent",
                native_enum=False,
                length=32,
            ),
            nullable=False,
        ),
        sa.Column(
            "source",
            sa.Enum(
                "membership_update",
                "delivery_refusal",
                name="botblocksource",
                native_enum=False,
                length=32,
            ),
            nullable=False,
        ),
        # UtcDateTime renders as a timezone-aware DateTime; env.py exists so our own column
        # types never have to be named here.
        sa.Column("at", sa.DateTime(timezone=True), nullable=False),
        # No ForeignKeyConstraint and no CheckConstraint. See the module docstring.
        sa.PrimaryKeyConstraint("id", name=op.f("pk_bot_membership_events")),
    )
    with op.batch_alter_table(_TABLE, schema=None) as batch_op:
        # SQLite cannot ALTER an existing table to add an index without a rebuild, so every
        # index in this project is created inside batch_alter_table (render_as_batch=True).
        for column in _INDEXES:
            batch_op.create_index(batch_op.f(f"ix_{_TABLE}_{column}"), [column], unique=False)

    with op.batch_alter_table(_PURGE_RUNS_TABLE, schema=None) as batch_op:
        # The one shape of zero this design allows: a measured count of rows a past sweep
        # really did delete (none — the table did not exist), not an unmeasured quantity.
        batch_op.add_column(
            sa.Column(_PURGE_RUNS_COLUMN, sa.Integer(), nullable=False, server_default="0")
        )


def downgrade() -> None:
    with op.batch_alter_table(_PURGE_RUNS_TABLE, schema=None) as batch_op:
        batch_op.drop_column(_PURGE_RUNS_COLUMN)

    with op.batch_alter_table(_TABLE, schema=None) as batch_op:
        for column in reversed(_INDEXES):
            batch_op.drop_index(batch_op.f(f"ix_{_TABLE}_{column}"))

    op.drop_table(_TABLE)

    with op.batch_alter_table(_USERS_TABLE, schema=None) as batch_op:
        batch_op.drop_index(batch_op.f(f"ix_{_USERS_TABLE}_{_USERS_COLUMN}"))
        batch_op.drop_column(_USERS_COLUMN)
