"""Add broadcasts, broadcast_bodies and broadcast_recipients.

Revision ID: 0024
Revises: 0023
Create Date: 2026-09-09

Implements the schema half of ``BROADCAST_SPEC §2.1``–``§2.2``.

Every message this schema has sent so far was aimed at ONE person and caused by something
that person did: an order finished, a payment settled, a wizard step needed an answer. A
campaign inverts all three. It is aimed at a POPULATION nobody has enumerated yet, it is
caused by an operator opening a screen, and the send outlives the request that started it by
minutes or hours while a rate limiter feeds it forty thousand accounts at thirty a second.
These three tables are the only durable thing that send has.

**WHY THE AUDIENCE IS A TABLE AND NOT A QUERY, WHICH IS THE WHOLE DESIGN.** The obvious
shape stores the segment document on the campaign and re-compiles it in the worker at send
time, saving a table and forty thousand rows. It also makes "who was this sent to?"
unanswerable and "has this account already been messaged?" unaskable. ARQ ships with
``retry_jobs=True`` and SIGTERM cancels a running job so it runs again on the next boot, so a
worker that re-derives its audience from a live query resumes against a DIFFERENT population
than the one it was halfway through — everyone who signed up in the meantime is new, everyone
who was erased is gone, and the accounts already messaged are indistinguishable from the ones
still owed a message. ``broadcast_recipients`` exists so that question has a row to answer it:
the audience is materialised when the campaign is CREATED, the send delivers to exactly those
rows, and a campaign scheduled for Friday reaches whoever matched on Tuesday. That is a
product decision, and this revision is where it is kept.

**WHY ``audience_size`` AND ``recipient_count`` ARE TWO COLUMNS AND NOT ONE.** The first is
the exact ``SELECT count(*)`` the segment returned at creation; the second is how many rows
the expansion actually wrote. They are equal on every healthy campaign, and the only reason to
store both is the campaign that is not healthy: a half-written expansion — the worker killed
between chunks — is otherwise INVISIBLE, because a single counter recomputed from the rows
that exist always agrees with itself. It is the ``purge_runs.storage_keys_returned`` /
``storage_keys_deleted`` split, one table along: the number we intended and the number we
achieved are different measurements, and collapsing them into one destroys the only evidence
that they disagreed. ``audience_evaluated_at`` beside them is the ``now`` the segment was
compiled against, which is what turns "why did twelve fewer people get this than the preview
said" from an incident into a sentence — they joined after Tuesday.

**WHY THE BODIES ARE A CHILD TABLE AND NOT A JSON COLUMN ON ``broadcasts``.** A blob cannot
carry ``UNIQUE (broadcast_id, language)``, cannot carry a length ``CHECK`` and cannot carry an
emptiness one. Those three constraints are the entire difference between a campaign that
cannot ship with an empty Russian body and one that ships an empty Russian body to eleven
thousand people, and the alternative to them is validation in whichever writer happens to run
— which is the validation every writer added later forgets.

**WHY THE MEDIA ATTACHMENT IS TWO COLUMNS.** ``media_storage_key`` is the operator's upload in
OUR object store, because the admin process is denied a Telegram bot token by
``FORBIDDEN_ENV_VARS`` and therefore cannot mint a ``file_id`` at compose time;
``media_file_id`` is what Telegram hands back on the FIRST send, cached so the remaining
thirty-nine thousand nine hundred and ninety-nine reuse it. That is ``assets.tg_file_id``'s
cost control (SoW FIL-4) applied to the one message shape that multiplies it by the size of an
audience. ``ck_broadcast_bodies_media_pair`` refuses the cached handle without the stored
original, because a ``file_id`` Telegram has since forgotten and no file to re-upload is a
campaign that cannot be re-sent at all.

**WHY ``ck_broadcast_bodies_caption_length`` IS DDL AND NOT A CONVENTION.** Telegram accepts
4 096 characters in a message and 1 024 in a photo caption. A longer body WITH an image is a
``TelegramBadRequest`` for every recipient alike — a dead campaign, discovered one message at
a time, after the send has started. The pydantic layer enforces the same ceiling so the
operator sees a 422; this CHECK is what makes that ceiling unbypassable by any other writer.

**WHY ``UNIQUE (broadcast_id, telegram_user_id)`` IS THE IDEMPOTENCY AUTHORITY, AND WHY IT IS
DELIBERATELY NULL-HOSTILE.** It makes a second row for the same account in the same campaign
impossible at the database, so a replayed expansion chunk is an ``insert_or_ignore`` no-op —
the ``user_activity_snapshots`` pattern — rather than a branch some future writer forgets.
Note what it does and does not buy: the constraint makes a duplicate ROW impossible, and the
committed ``pending -> sending`` claim makes a duplicate SEND impossible; both halves are
needed and neither substitutes for the other. ``telegram_user_id`` becomes NULL when
``/forget`` runs, and both engines permit any number of NULLs in a unique index — so
anonymised rows stop participating in uniqueness and keep their counts. The campaign's
arithmetic survives; the person does not.

**WHY THERE ARE FOREIGN KEYS HERE WHEN 0023 HAD NONE.** The rule this codebase actually
follows is not "no foreign keys": it is that a customer-facing fact must outlive the account
it is about, which is why ``telegram_user_id`` never has one. A body and a recipient row are
not facts about a customer at all — they are PARTS of a campaign, meaningless without the
parent row, and there is no state of the world in which one should survive it.
``ON DELETE CASCADE`` on both is therefore correctness rather than convenience: deleting a
campaign that left forty thousand orphaned recipient rows behind would leave the largest table
in the schema growing on rows no query can reach.

**WHY EACH NULLABLE COLUMN IS NULLABLE.** On ``broadcasts``: ``expand_cursor`` is NULL before
expansion starts and again once it finishes, and it is the resume point in between;
``scheduled_for`` is NULL on a campaign sent immediately, which is half the product;
``started_at`` and ``finished_at`` are NULL until the events they record happen; the four
``*_by_*`` columns are NULL when no admin has taken that action yet, and are denormalised
pairs so the list screen can render "created by / scheduled by" without a join — the ROLE at
the time of the action lives on the tamper-evident ``admin_audit_log`` row, not here;
``reason_code`` and ``reason_ref`` are NULL where no reason was demanded; ``error_code`` is
NULL on every campaign that has not failed. On ``broadcast_recipients``: ``telegram_user_id``
is nullable ONLY so erasure has somewhere to go — every writer supplies it, and a NULL means
one thing, ``/forget`` ran — ``error_code`` is NULL until something goes wrong, and
``settled_at`` is NULL until the row reaches a terminal state.

**WHY THE RECIPIENT CLOCK IS ``settled_at`` AND NOT ``sent_at``.** A ``sent_at`` cannot stamp a
skip or a refusal, so "never settled" and "settled, but not by a send" would share one NULL
and the difference between an unfinished campaign and a completely skipped one would be
unrecoverable. The send instant is ``state = 'sent' AND settled_at``, which is one column
saying one thing.

**WHY THE FREE-TEXT HALF OF THE REASON IS NOT COPIED HERE.** ``reason_code`` and ``reason_ref``
are stored; ``reason_text`` is not. ``admin_audit_log.reason_text`` owns the 90-day clock
(``reason_expires_at``) and the sweep that nulls it, and a second copy on this table would be
unswept operator prose with no clock at all. Adding a ``reason_expires_at`` here instead would
be worse: ``tests/test_db/test_audit_retention.py`` collects every column whose name ends in
that suffix and demands ``bayram.db.purge.rows_past_expiry_statements`` read it, so the column
would claim a published retention schedule this table does not have.

**WHY EACH INDEX EXISTS — AND, MORE IMPORTANTLY, WHICH ONES DO NOT.**
``ix_broadcasts_state_scheduled_for`` is the one scan a scheduler runs,
``WHERE state = 'ready' AND scheduled_for <= :now``, and it is hand-named because
``test_the_migrated_indexes_match_the_model_metadata`` compares index NAMES and a templated
name would leave the model declaring an index the chain never builds. It is also the ONLY
declared index on ``broadcasts``: a single-column index on ``state`` would be redundant with
this one's leading column and a single-column index on ``scheduled_for`` serves no query at
all, on a table that gains a handful of rows a week — precisely the "three unused read
indexes shipped" mistake revision 0012 had to reconcile. ``broadcast_bodies`` gets NO index on
``broadcast_id`` for the same reason: ``uq_broadcast_bodies_broadcast_id_language`` leads with
that column and already serves the only read anybody performs against it.
``ix_broadcast_recipients_broadcast_id_state`` serves the two hot queries, which are the same
shape — the chunk claim ``WHERE broadcast_id = :id AND state = 'pending' LIMIT :n`` and the
progress rollup ``SELECT state, count(*) … GROUP BY state`` — and ``broadcast_id`` alone does
not narrow either: on a completed campaign every row shares it, so the pending scan would read
all forty thousand to find none. ``ix_broadcast_recipients_telegram_user_id`` exists for the
anonymising ``UPDATE`` that runs inside the transaction a customer's ``/forget`` is waiting
on. The three ``created_at`` indexes come from ``TimestampMixin``; on the recipients they are
also the retention cutoff's predicate.

**PRIVACY — ALL THREE TABLES ARE IN NEITHER OF
``tests/test_db/test_privacy_constraints.py``'s TWO SETS, and the argument is written down
there rather than left silent.** ``broadcasts`` and ``broadcast_bodies`` hold no personal data
at all: UUIDs, closed enums, counters, clocks, a segment document describing a population, and
operator-authored copy addressed to that population. The bodies are text FROM us and never
text ABOUT a person — there is no ``{placeholder}`` interpolation at any layer, so a body
cannot contain a customer's name, number or order — which is the distinction ``vendor_usage``
(0016) turns on. ``broadcast_recipients`` may NOT borrow that argument, because it carries a
``telegram_user_id`` and is therefore about an identified person; its route is
``bot_membership_events``', ``credit_ledger``'s and ``plan_purchases``': erasure by
ANONYMISATION, nulling the id in place. It is not in ``tables_erased_on_request``, whose stated
semantics are "the absence of a row IS the erasure record", because deleting these rows would
silently rewrite the delivery record of a campaign that has already gone out.

**THE RETENTION SHAPES, AND WHY NO COLUMN USES THE ``*_expires_at`` SUFFIX.** That suffix is
this codebase's word for a published legal clock stamped per row by its writer, and none of
these three columns is one. ``broadcasts`` and ``broadcast_bodies`` are bounded by nothing at
all, on ``topup_purchases``' argument: a campaign is an audit fact about something we said to
a population, and a few rows a week is not growth. ``broadcast_recipients`` is by far the
fastest-growing table in this schema — one row per account per campaign — and is bounded by a
CUTOFF on ``created_at``, counted into ``purge_runs.broadcast_recipients_deleted``, which is
defence in depth beside the erasure arm and never a substitute for it. A sweep whose count is
not stored is a backlog the panel reports as zero.

**THERE IS NO CONSENT TABLE AND NO OPT-OUT COLUMN, ANYWHERE IN THIS REVISION.** The only
suppression signal in this product is a BLOCK — ``users.is_blocked`` (our bar) and
``users.blocked_bot_at`` or a ``TelegramForbiddenError`` at send time (theirs) — and both land
in ``broadcast_recipients.state`` as ``skipped_blocked``, because neither is a delivery
attempt. A standing preference that outlives a campaign would belong on a table of its own
keyed to the account and would not belong on a row that is swept with the campaign; none is
created here.

**WHY THERE IS NO BACKFILL, AND WHY THERE CAN NEVER BE ONE.** All three tables are created
EMPTY. No campaign has ever been composed, so there is no past send to reconstruct, and
inventing one per historical ``chat_messages`` row would fabricate a segment, an audience size
and an evaluation instant that never existed. Consequently no column on the three new tables
carries a ``server_default``, including the six counters and ``attempts``: their zero is
written by the row's own creator. ``purge_runs.broadcast_recipients_deleted`` DOES carry one —
0016's precedent, restated by 0023 — because that table has existing rows which must answer
something, and for that column zero is the TRUE answer: those sweeps genuinely deleted
nothing, because the table did not exist when they ran. It is dropped FIRST on the way down,
before the tables it counts.

**Every enum is spelled literally, and every clock is a plain ``sa.DateTime(timezone=True)``.**
A migration that imports application code breaks historically, on a revision that already ran
everywhere; ``env.py`` renders ``UtcDateTime`` as a timezone-aware ``DateTime`` precisely so
our own column types never have to be named here. ``enum_type`` renders ``VARCHAR(32)`` with
``create_constraint`` off, so a ninth campaign state needs no migration at all. The CHECK
constraints name no enum value for the same reason from the other direction: a CHECK is DDL,
it outlives the Python class, and a member renamed in code must never silently change what the
database enforces.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0024"
down_revision: str | None = "0023"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_BROADCASTS = "broadcasts"
_BODIES = "broadcast_bodies"
_RECIPIENTS = "broadcast_recipients"
_PURGE_RUNS = "purge_runs"

#: The caption ceiling, spelled once. Telegram accepts 4 096 characters in a message and
#: 1 024 in a photo caption; the models spell the same number as ``BROADCAST_CAPTION_LENGTH``.
_CAPTION_LENGTH = 1024

#: ``(column, unique)`` per table, created through ``batch_op.f()`` so they take
#: ``NAMING_CONVENTION``'s ``ix`` template and match the models' ``index=True`` declarations.
#: Dropped in ``reversed()`` order on the way down.
_BROADCAST_INDEXES: tuple[tuple[str, bool], ...] = (("created_at", False),)
_BODY_INDEXES: tuple[tuple[str, bool], ...] = (("created_at", False),)
_RECIPIENT_INDEXES: tuple[tuple[str, bool], ...] = (
    ("telegram_user_id", False),
    ("created_at", False),
)

#: The two composites, hand-named rather than templated because each is a decision about a
#: specific query rather than a column's own index. Spelled identically in the models, because
#: ``test_the_migrated_indexes_match_the_model_metadata`` compares index names.
_BROADCAST_SCHEDULER_INDEX = "ix_broadcasts_state_scheduled_for"
_RECIPIENT_CHUNK_INDEX = "ix_broadcast_recipients_broadcast_id_state"

#: The counter added to the existing sweep-record table.
_PURGE_RUNS_COLUMN = "broadcast_recipients_deleted"


def upgrade() -> None:
    op.create_table(
        _BROADCASTS,
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("title", sa.String(length=120), nullable=False),
        sa.Column(
            "kind",
            sa.Enum("service", "marketing", name="broadcastkind", native_enum=False, length=32),
            nullable=False,
        ),
        sa.Column(
            "state",
            sa.Enum(
                "draft",
                "expanding",
                "ready",
                "sending",
                "paused",
                "completed",
                "cancelled",
                "failed",
                name="broadcaststate",
                native_enum=False,
                length=32,
            ),
            nullable=False,
        ),
        # -- the frozen audience: the segment is STORED, never re-evaluated --------------
        sa.Column("segment", sa.JSON(), nullable=False),
        sa.Column("segment_hash", sa.String(length=64), nullable=False),
        # The exact count the segment returned at creation, beside the number of rows the
        # expansion actually wrote. See the module docstring on why both exist.
        sa.Column("audience_size", sa.Integer(), nullable=False),
        # UtcDateTime renders as a timezone-aware DateTime; env.py exists so our own column
        # types never have to be named here.
        sa.Column("audience_evaluated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expand_cursor", sa.String(length=256), nullable=True),
        # -- the clocks ------------------------------------------------------------------
        # NULL on a campaign sent immediately, which is half the product.
        sa.Column("scheduled_for", sa.DateTime(timezone=True), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        # -- the rollup: recomputed FROM broadcast_recipients, which stay the truth -------
        sa.Column("recipient_count", sa.Integer(), nullable=False),
        sa.Column("sent_count", sa.Integer(), nullable=False),
        sa.Column("failed_count", sa.Integer(), nullable=False),
        sa.Column("skipped_count", sa.Integer(), nullable=False),
        sa.Column("undeliverable_count", sa.Integer(), nullable=False),
        # Its own number rather than a fold into failed_count: an UNKNOWN outcome may well
        # have been delivered, and reporting it as a failure misstates what happened.
        sa.Column("unknown_count", sa.Integer(), nullable=False),
        # -- who: denormalised pairs so the list screen renders without a join ------------
        sa.Column("created_by_admin_id", sa.Uuid(), nullable=True),
        sa.Column("created_by_username", sa.String(length=64), nullable=True),
        sa.Column("scheduled_by_admin_id", sa.Uuid(), nullable=True),
        sa.Column("scheduled_by_username", sa.String(length=64), nullable=True),
        # -- why: the CODED half only. The free text lives on admin_audit_log, which has the
        # 90-day clock and the sweep that nulls it. See the module docstring.
        sa.Column(
            "reason_code",
            sa.Enum(
                "customer_request",
                "gdpr_erasure",
                "abuse_report",
                "support_investigation",
                "incident",
                "bake_off",
                "routine_ops",
                "other",
                name="auditreasoncode",
                native_enum=False,
                length=32,
            ),
            nullable=True,
        ),
        sa.Column("reason_ref", sa.String(length=64), nullable=True),
        sa.Column("error_code", sa.String(length=48), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        # No ForeignKeyConstraint on either admin id: an admin who leaves must not take the
        # record of what they sent with them. The users precedent, one actor along.
        sa.PrimaryKeyConstraint("id", name=op.f("pk_broadcasts")),
    )

    op.create_table(
        _BODIES,
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("broadcast_id", sa.Uuid(), nullable=False),
        sa.Column(
            "language",
            sa.Enum(
                "uz_latn", "uz_cyrl", "ru", "en", name="language", native_enum=False, length=32
            ),
            nullable=False,
        ),
        sa.Column("text", sa.String(length=4096), nullable=False),
        # The operator's upload in OUR object store: the admin process is denied a bot token
        # and cannot mint a file_id. The cached handle below is written by the WORKER, after
        # the first send, and is worthless without the original beside it.
        sa.Column("media_storage_key", sa.String(length=512), nullable=True),
        sa.Column("media_file_id", sa.String(length=128), nullable=True),
        sa.Column("button_label", sa.String(length=64), nullable=True),
        sa.Column("button_url", sa.String(length=512), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        # An empty body is a message that says nothing to everybody.
        sa.CheckConstraint("length(text) > 0", name=op.f("ck_broadcast_bodies_text_not_empty")),
        # A label with no URL renders a dead button; a URL with no label renders nothing.
        sa.CheckConstraint(
            "(button_label IS NULL) = (button_url IS NULL)",
            name=op.f("ck_broadcast_bodies_button_pair"),
        ),
        # With an image attached the body is a CAPTION, and Telegram refuses a caption over
        # 1 024 characters for every recipient alike. See the module docstring.
        sa.CheckConstraint(
            f"media_storage_key IS NULL OR length(text) <= {_CAPTION_LENGTH}",
            name=op.f("ck_broadcast_bodies_caption_length"),
        ),
        sa.CheckConstraint(
            "media_file_id IS NULL OR media_storage_key IS NOT NULL",
            name=op.f("ck_broadcast_bodies_media_pair"),
        ),
        sa.ForeignKeyConstraint(
            ["broadcast_id"],
            ["broadcasts.id"],
            name=op.f("fk_broadcast_bodies_broadcast_id_broadcasts"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_broadcast_bodies")),
        # One body per language per campaign. Its leading column is broadcast_id, which is
        # why this table gets no separate index on it.
        sa.UniqueConstraint(
            "broadcast_id", "language", name=op.f("uq_broadcast_bodies_broadcast_id_language")
        ),
    )

    op.create_table(
        _RECIPIENTS,
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("broadcast_id", sa.Uuid(), nullable=False),
        # Nullable ONLY so erasure has somewhere to go — a NULL means /forget ran.
        sa.Column("telegram_user_id", sa.BigInteger(), nullable=True),
        sa.Column(
            "language",
            sa.Enum(
                "uz_latn", "uz_cyrl", "ru", "en", name="language", native_enum=False, length=32
            ),
            nullable=False,
        ),
        sa.Column(
            "state",
            sa.Enum(
                "pending",
                "sending",
                "sent",
                "failed",
                "skipped_blocked",
                "undeliverable",
                "unknown",
                name="broadcastrecipientstate",
                native_enum=False,
                length=32,
            ),
            nullable=False,
        ),
        sa.Column("attempts", sa.SmallInteger(), nullable=False),
        sa.Column("error_code", sa.String(length=48), nullable=True),
        # NOT sent_at: one clock for every terminal state. See the module docstring.
        sa.Column("settled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["broadcast_id"],
            ["broadcasts.id"],
            name=op.f("fk_broadcast_recipients_broadcast_id_broadcasts"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_broadcast_recipients")),
        # THE IDEMPOTENCY AUTHORITY, and deliberately NULL-tolerant: both engines permit any
        # number of NULLs in a unique index, so anonymised rows stop participating in
        # uniqueness and keep their counts.
        sa.UniqueConstraint(
            "broadcast_id",
            "telegram_user_id",
            name=op.f("uq_broadcast_recipients_broadcast_id_telegram_user_id"),
        ),
    )

    # SQLite cannot ALTER an existing table to add an index without a rebuild, so every
    # index in this project is created inside batch_alter_table (render_as_batch=True).
    with op.batch_alter_table(_BROADCASTS, schema=None) as batch_op:
        for column, unique in _BROADCAST_INDEXES:
            batch_op.create_index(batch_op.f(f"ix_{_BROADCASTS}_{column}"), [column], unique=unique)
        batch_op.create_index(_BROADCAST_SCHEDULER_INDEX, ["state", "scheduled_for"], unique=False)

    with op.batch_alter_table(_BODIES, schema=None) as batch_op:
        for column, unique in _BODY_INDEXES:
            batch_op.create_index(batch_op.f(f"ix_{_BODIES}_{column}"), [column], unique=unique)

    with op.batch_alter_table(_RECIPIENTS, schema=None) as batch_op:
        for column, unique in _RECIPIENT_INDEXES:
            batch_op.create_index(batch_op.f(f"ix_{_RECIPIENTS}_{column}"), [column], unique=unique)
        batch_op.create_index(_RECIPIENT_CHUNK_INDEX, ["broadcast_id", "state"], unique=False)

    with op.batch_alter_table(_PURGE_RUNS, schema=None) as batch_op:
        # NOT NULL with a server default because existing rows have to answer something, and
        # for THIS column zero is the true answer: those sweeps genuinely deleted nothing,
        # because the table did not exist when they ran. That is the one shape of zero this
        # design allows — a measured count, not an unmeasured quantity — as 0016 argued.
        batch_op.add_column(
            sa.Column(_PURGE_RUNS_COLUMN, sa.Integer(), nullable=False, server_default=sa.text("0"))
        )


def downgrade() -> None:
    # The counter goes first: it counts rows in a table that is about to stop existing.
    with op.batch_alter_table(_PURGE_RUNS, schema=None) as batch_op:
        batch_op.drop_column(_PURGE_RUNS_COLUMN)

    with op.batch_alter_table(_RECIPIENTS, schema=None) as batch_op:
        batch_op.drop_index(_RECIPIENT_CHUNK_INDEX)
        for column, _ in reversed(_RECIPIENT_INDEXES):
            batch_op.drop_index(batch_op.f(f"ix_{_RECIPIENTS}_{column}"))

    with op.batch_alter_table(_BODIES, schema=None) as batch_op:
        for column, _ in reversed(_BODY_INDEXES):
            batch_op.drop_index(batch_op.f(f"ix_{_BODIES}_{column}"))

    with op.batch_alter_table(_BROADCASTS, schema=None) as batch_op:
        batch_op.drop_index(_BROADCAST_SCHEDULER_INDEX)
        for column, _ in reversed(_BROADCAST_INDEXES):
            batch_op.drop_index(batch_op.f(f"ix_{_BROADCASTS}_{column}"))

    # Children first: both carry ON DELETE CASCADE to broadcasts.
    op.drop_table(_RECIPIENTS)
    op.drop_table(_BODIES)
    op.drop_table(_BROADCASTS)
