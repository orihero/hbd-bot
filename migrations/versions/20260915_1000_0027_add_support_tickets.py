"""Add support_tickets and support_ticket_events.

Revision ID: 0027
Revises: 0026
Create Date: 2026-09-15

Implements the schema half of ``SUPPORT_TICKETS_SPEC §2.1``–``§2.2``.

The ⚠️ button under a delivered song has, until this revision, rendered a sentence and written
nothing. A customer who pressed it was told where to write; whatever they wrote landed in a
chat nobody owned. There was no row, so there was no reference to quote back, no queue to
work, no way to answer "how many people told us the name was wrong last month?", and no way
for two staff to avoid answering the same person twice. These two tables are that missing row
and its history.

**WHY THE TIMELINE IS A SECOND TABLE AND NOT A JSON COLUMN ON THE FIRST.** A blob cannot be
appended to by two writers without a read-modify-write, and there are three of them here —
the bot (the customer's description), the group router (a staffer's reply) and the admin API
(an operator's note or status change) — all of which can land in the same second. It also
cannot be indexed, cannot be paged, and cannot carry ``ON DELETE CASCADE``, which is what
makes erasure one statement instead of two that can disagree. The split is
``credit_accounts`` beside ``credit_ledger`` in a different domain: the parent row says where
the ticket is NOW, the child rows say how it got there, and neither can be derived from the
other.

**WHY ``group_chat_id`` AND ``group_message_id`` ARE COLUMNS AT ALL, WHICH IS THE WHOLE
DESIGN.** The obvious shape posts the card to the support group inside the job that creates
the ticket and remembers nothing. ARQ in this project runs with ``retry_jobs=True`` and SIGTERM
cancels a running job, so EVERY job is replayed on the next boot: a card whose only record of
having been posted is the job that posted it is a card that is posted again on every deploy,
into a group where staff are already replying to the first copy. So the pair is a LATCH —
claimed by a conditional ``UPDATE`` whose rowcount is the lock, BEFORE the Telegram call, and
settled by ``group_posted_at`` after — which is exactly the shape revision 0026 gave
``payment_intents.resumed_at`` for a resumed render, for the identical reason. The record of
"this was posted" lives in the row, never in the job.

The unique index over the pair — ``ix_support_tickets_group_chat_id_group_message_id`` — is
the second half of that latch and closes a different hole: a staffer's reply is matched to a
ticket by ``reply_to_message.message_id``, so two tickets claiming one card would relay a
stranger's answer to the wrong customer. It is NULL-tolerant by construction — both engines
treat NULLs as distinct in a unique index, and a composite is unique only when every column is
non-NULL — which is what makes it safe to leave the latch unset when Telegram refuses. **A
failed group post must never lose the ticket:** the row is written, the board shows it, the
customer is confirmed, and the post is still owed.

**THE UNIQUENESS IS OVER THE PAIR AND NEVER OVER ``group_message_id`` ALONE, AND THAT IS NOT A
NARROWING TO BE TIDIED BACK UP.** A Telegram ``message_id`` is a PER-CHAT counter. A global
unique index on that column alone asserts something Telegram never promised, and the assertion
breaks the first time the support group moves — a new group, or Telegram auto-upgrading a
basic group to a supergroup, which CHANGES the chat id. Old rows still hold message ids 2, 5,
9… from the old chat; the next card Telegram numbers 5 in the NEW chat collides with them, the
latch UPDATE raises ``IntegrityError`` for a card that was in fact posted, and the ticket is
left permanently un-latched beside an orphan card in the group that nothing can edit or relay
from. The pair is also exactly what the reply lookup reads on (``find_by_group_message``
filters chat id AND message id), so the composite leads with the column that query narrows on
first and serves it end to end. There is no lookup anywhere in this codebase that keys on a
message id without a chat id beside it.

**WHY ``described_at`` AND ``body`` ARE NULLABLE, AND WHY THOSE ROWS ARE KEPT.** A customer
taps ⚠️ and never types. That is not a half-written row to be cleaned up; it is the only
measure of how many people started to complain and gave up, and it is the number the rate
limiter meters against. The board hides those rows with ``described_at IS NOT NULL`` rather
than deleting them, because deleting them would make the count of attempts equal the count of
complaints by construction — which is precisely the arithmetic this table exists to disprove.
``prompt_message_id`` beside them is the ForceReply message the ticket is waiting on, and the
reason this flow touches no FSM state at all: ⚠️ can be tapped from a month-old delivery
message while a NEW wizard is half-finished, and parking the customer in a state would clobber
a draft they are still typing into.

**WHY EACH OTHER NULLABLE COLUMN IS NULLABLE.** ``order_id`` is NULL on every ticket opened by
``/support``, which has no order in hand — half the rows, and not a defect;
``assigned_admin_username``/``assigned_at`` are NULL until somebody claims it, which is what
the ``new`` column of the board means; ``resolved_at`` is NULL until it is resolved, and is NOT
cleared by a reopen, because "this was once considered finished" is the single most useful
thing to know about a ticket that came back. On ``support_ticket_events``: the three author
columns are NULL for the kinds of author they do not describe, ``from_status``/``to_status``
are set only on a status change, ``body`` is NULL on the kinds that carry no prose, and
``relayed_at`` is NULL until a reply really reached the customer's chat — which is what makes a
reply that was written but never delivered visibly different from one that landed.

**WHY ``order_id`` TAKES ``ON DELETE SET NULL`` AND ``ticket_id`` TAKES ``ON DELETE CASCADE``.**
They are two different relationships and the postures are not interchangeable. A ticket must
OUTLIVE the order it was about — ``generation_attempts.order_id`` takes ``SET NULL`` for the
same reason — or a retention sweep on ``orders`` would silently become an undeclared retention
policy on complaints, deleting the support history of every song that has aged out. An event,
by contrast, is a PART of a ticket and is meaningless without it, which is
``broadcast_recipients``' posture one table along; the cascade is also what makes ``/forget``
one statement rather than two that can disagree about whether the timeline went with the row.

**WHY THERE IS NO FOREIGN KEY TO ``admin_users`` OR ``users``.** The rule this codebase
follows is that a customer-facing fact must outlive the account it is about, which is why
``telegram_user_id`` never carries one, and ``admin_audit_log``'s rule that history must
survive the operator who made it — so ``assigned_admin_username`` and
``author_admin_username`` are denormalised strings. A rename must not rewrite who worked a
ticket.

**WHY EACH INDEX EXISTS, AND WHICH ONES DELIBERATELY DO NOT.**
``ix_support_tickets_status_created_at_id`` is the board's one scan,
``WHERE status = :column ORDER BY created_at, id`` paged by keyset, and ``id`` is the third
column for ``ix_orders_state_created_at``'s stated reason: without it Postgres adds an
``Incremental Sort … Presorted Key: created_at`` to every page and the sort buffer grows with
the size of the tie group, which a burst of tickets from one outage is made of. It is hand-named
because ``test_the_migrated_indexes_match_the_model_metadata`` compares index NAMES, and a
templated name would leave the model declaring an index the chain never builds.
``ix_support_ticket_events_ticket_id_created_at_id`` is the only read anybody performs against
the child table — one ticket's timeline, oldest first — and is hand-named for the same reason;
two events written in one transaction share an instant exactly, which is what the trailing
``id`` settles. ``ix_support_tickets_group_chat_id_group_message_id`` is the card latch and the
reply lookup in one UNIQUE composite, argued at length above; its name is deliberately the one
``NAMING_CONVENTION``'s ``ix`` template mints for those two columns, so the model's hand-spelled
``sa.Index`` and a later autogenerate diff agree rather than proposing a rename.
``public_ref`` is UNIQUE because a reference resolving to two tickets is worse
than no reference: support would answer about the wrong complaint while believing they had
looked it up. ``telegram_user_id`` is indexed for the erasure ``DELETE``, which runs inside the
transaction a customer's ``/forget`` is waiting on and must not scan.

The omissions: NO single-column index on ``status`` (redundant with the composite's leading
column — the "three unused read indexes shipped" mistake revision 0012 had to reconcile), NO
index on ``described_at`` (the board only ever filters it alongside a status equality the
composite has already narrowed), NO index on ``group_message_id`` alone (the card composite
leads with ``group_chat_id`` and serves the only lookup there is; a single-column one would be
both redundant and, if made unique, the bug argued above), NO separate index on ``ticket_id``
(the child composite leads
with it and serves the cascade too — ``broadcast_bodies`` declines one on ``broadcast_id`` for
exactly this reason), and NO index on the child's ``created_at`` at all, because nothing reads
that table across tickets and no sweep runs over it.

**PRIVACY — BOTH TABLES ARE IN NEITHER OF ``tests/test_db/test_privacy_constraints.py``'s TWO
SETS, AND THE ARGUMENT IS WRITTEN DOWN THERE RATHER THAN LEFT SILENT.** The ticket body is
free text a customer wrote about their own order, so unlike ``broadcasts`` this table cannot
claim to hold no personal data. Its route is the THIRD one: erasure on request by DELETION,
through ``/forget``, which removes this customer's tickets and — by the cascade above — their
timelines with them. It is not in ``tables_erased_on_request`` even so, because that set is
asserted to have no ``*_expires_at`` column and is read as the complete list of tables
``/forget`` truncates for a full reset to first-contact state; a ticket is deleted for the
person who wrote it, which is the same act with a different ownership. **NO COLUMN ON EITHER
TABLE USES THE ``*_expires_at`` SUFFIX**, and that is the deliberate part: in this codebase
that suffix is a published legal clock, and ``tests/test_db/test_audit_retention.py`` collects
every column bearing it and demands ``bayram.db.purge.rows_past_expiry_statements`` read it —
so adding one would claim a retention schedule nobody has promised, and a support history that
deleted itself on a schedule would delete the evidence in the one dispute it was kept for. The
body is kept indefinitely, on ``topup_purchases``' footing: a few rows a week is not growth.

**THERE IS NO BACKFILL, AND THERE CAN NEVER BE ONE.** Both tables are created EMPTY. No
ticket has ever been filed, so there is no past complaint to reconstruct, and inventing one
per historical ``chat_messages`` row would fabricate a description, a source and an instant
that never existed. Consequently no column carries a ``server_default``: ``status`` is written
by the row's own creator, which is the customer's tap. No ``purge_runs`` counter is added
either, because — unlike revision 0024's recipients — nothing sweeps these tables.

**Every enum is spelled literally, every clock is a plain ``sa.DateTime(timezone=True)``, and
every length is a literal int.** A migration that imports application code breaks historically,
on a revision that already ran everywhere, and
``test_no_migration_imports_application_code`` enforces it; ``env.py`` renders ``UtcDateTime``
as a timezone-aware ``DateTime`` precisely so our own column types never have to be named
here, and revision 0024 re-declares its caption length locally for the identical reason.
``enum_type`` renders ``VARCHAR(32)`` with ``create_constraint`` off, so **a fifth ticket
status, or a new event kind, needs NO follow-up revision at all** — there is no native enum
and no CHECK to alter, and a reviewer asking for one is asking for a migration this design
does not need.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0027"
down_revision: str | None = "0026"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TICKETS = "support_tickets"
_EVENTS = "support_ticket_events"

#: Spelled as literal ints even though the models declare them as ``Final`` constants, for the
#: reason revision 0024 re-declares ``_CAPTION_LENGTH``: this file may never import
#: ``bayram.*``, and a revision that already ran everywhere has to keep meaning what it meant.
#: ``A3F2-91`` is seven characters and the bound leaves room for a longer shape later.
_PUBLIC_REF_LENGTH = 12
#: Telegram's own single-message ceiling — the hard bound on what can physically arrive.
_BODY_LENGTH = 4096
#: ``admin_audit_log.actor_username``'s width, restated. A denormalised operator name.
_USERNAME_LENGTH = 64
#: A Telegram ``@handle`` is at most 32 characters and a first name at most 64.
_DISPLAY_NAME_LENGTH = 64

#: ``(column, unique)`` per table, created through ``batch_op.f()`` so they take
#: ``NAMING_CONVENTION``'s ``ix`` template and match the models' ``index=True`` declarations
#: exactly. Dropped in ``reversed()`` order on the way down.
#:
#: ``group_message_id`` is deliberately ABSENT from this tuple. It used to sit here as
#: ``("group_message_id", True)`` — a global unique index on a per-chat counter — and that is
#: the defect this revision was corrected in place to remove; the uniqueness now lives on
#: ``_TICKET_CARD_INDEX`` below, over the pair. See the module docstring.
_TICKET_INDEXES: tuple[tuple[str, bool], ...] = (
    ("public_ref", True),
    ("telegram_user_id", False),
    ("order_id", False),
    ("created_at", False),
)
#: The child table declares no templated index at all — see the module docstring on the
#: omissions. Named as an empty tuple rather than left out so the symmetry with the upgrade
#: above is visible to the next person adding one.
_EVENT_INDEXES: tuple[tuple[str, bool], ...] = ()

#: The three composites, hand-named rather than templated because each is a decision about a
#: specific query rather than a column's own index. Spelled identically in the models, because
#: ``test_the_migrated_indexes_match_the_model_metadata`` compares index names.
_TICKET_BOARD_INDEX = "ix_support_tickets_status_created_at_id"
#: UNIQUE, and the only uniqueness the card latch has. Over the PAIR, because a Telegram
#: ``message_id`` is a per-chat counter — the module docstring argues this at length, and the
#: one-line version is that a global unique index here fails the latch for a card that posted
#: successfully as soon as the support group's chat id changes.
_TICKET_CARD_INDEX = "ix_support_tickets_group_chat_id_group_message_id"
_EVENT_TIMELINE_INDEX = "ix_support_ticket_events_ticket_id_created_at_id"


def upgrade() -> None:
    op.create_table(
        _TICKETS,
        sa.Column("id", sa.Uuid(), nullable=False),
        # The reference the customer reads down a phone line. UNIQUE through the index
        # created below; see the module docstring.
        sa.Column("public_ref", sa.String(length=_PUBLIC_REF_LENGTH), nullable=False),
        # NOT nullable-for-erasure, unlike broadcast_recipients and credit_ledger: /forget
        # DELETEs a ticket rather than anonymising it, because an anonymised complaint is not
        # a statistic, it is somebody's sentence with the name filed off.
        sa.Column("telegram_user_id", sa.BigInteger(), nullable=False),
        # The locale the ticket was opened in: the relay has to answer in the language the
        # customer complained in, not in whatever they have since switched the bot to.
        sa.Column(
            "language",
            sa.Enum(
                "uz_latn", "uz_cyrl", "ru", "en", name="language", native_enum=False, length=32
            ),
            nullable=False,
        ),
        sa.Column(
            "source",
            sa.Enum(
                "delivery_button",
                "support_command",
                name="supportticketsource",
                native_enum=False,
                length=32,
            ),
            nullable=False,
        ),
        # NULL on every /support ticket, which has no order in hand. ON DELETE SET NULL: the
        # ticket outlives the order it was about.
        sa.Column("order_id", sa.Uuid(), nullable=True),
        sa.Column(
            "status",
            sa.Enum(
                "new",
                "in_progress",
                "waiting",
                "resolved",
                name="supportticketstatus",
                native_enum=False,
                length=32,
            ),
            nullable=False,
        ),
        # The customer's own words, NULL until they answer the ForceReply prompt.
        sa.Column("body", sa.String(length=_BODY_LENGTH), nullable=True),
        # The prompt this ticket is waiting on. The whole FSM-free flow turns on it.
        sa.Column("prompt_message_id", sa.BigInteger(), nullable=True),
        # NULL means the customer tapped and never typed — a real row, excluded from the
        # board and counted by the rate limiter. See the module docstring.
        sa.Column("described_at", sa.DateTime(timezone=True), nullable=True),
        # -- who has it ------------------------------------------------------------------
        # Denormalised, with no ForeignKeyConstraint to admin_users: an operator who leaves
        # must not take the queue's history with them.
        sa.Column("assigned_admin_username", sa.String(length=_USERNAME_LENGTH), nullable=True),
        sa.Column("assigned_at", sa.DateTime(timezone=True), nullable=True),
        # -- the group card: a once-only latch, claimed before the send and settled after ---
        sa.Column("group_chat_id", sa.BigInteger(), nullable=True),
        sa.Column("group_message_id", sa.BigInteger(), nullable=True),
        sa.Column("group_posted_at", sa.DateTime(timezone=True), nullable=True),
        # Not cleared by a reopen: "this was once considered finished" is the most useful
        # thing to know about a ticket that came back.
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        # UtcDateTime renders as a timezone-aware DateTime; env.py exists so our own column
        # types never have to be named here.
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["order_id"],
            ["orders.id"],
            name=op.f("fk_support_tickets_order_id_orders"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_support_tickets")),
    )

    op.create_table(
        _EVENTS,
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("ticket_id", sa.Uuid(), nullable=False),
        sa.Column(
            "kind",
            sa.Enum(
                "opened",
                "described",
                "status_change",
                "note",
                "reply",
                "assigned",
                "group_posted",
                name="supportticketeventkind",
                native_enum=False,
                length=32,
            ),
            nullable=False,
        ),
        sa.Column(
            "author_kind",
            sa.Enum(
                "customer",
                "operator",
                "staff_group",
                "system",
                name="supportauthorkind",
                native_enum=False,
                length=32,
            ),
            nullable=False,
        ),
        # Three author columns, not one: an operator has an admin_users row, a session and an
        # audit entry behind them; a group staffer has only membership of a chat.
        sa.Column("author_admin_username", sa.String(length=_USERNAME_LENGTH), nullable=True),
        sa.Column("author_telegram_user_id", sa.BigInteger(), nullable=True),
        sa.Column("author_display_name", sa.String(length=_DISPLAY_NAME_LENGTH), nullable=True),
        # Both ends of a move, set only on a status change. "It went to waiting from resolved"
        # is a reopened ticket, which is the one shape anybody goes looking for.
        sa.Column(
            "from_status",
            sa.Enum(
                "new",
                "in_progress",
                "waiting",
                "resolved",
                name="supportticketstatus",
                native_enum=False,
                length=32,
            ),
            nullable=True,
        ),
        sa.Column(
            "to_status",
            sa.Enum(
                "new",
                "in_progress",
                "waiting",
                "resolved",
                name="supportticketstatus",
                native_enum=False,
                length=32,
            ),
            nullable=True,
        ),
        sa.Column("body", sa.String(length=_BODY_LENGTH), nullable=True),
        # Stamped when a reply really reached the private chat. The one column on this
        # append-only table written after insert, and not an amendment: composing a reply and
        # delivering it are two events separated by a call that fails often enough to matter.
        sa.Column("relayed_at", sa.DateTime(timezone=True), nullable=True),
        # No updated_at: this table is append-only, so the clock could never be true.
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        # Deliberately NO CheckConstraint tying author_kind to the column it populates, or
        # from_status/to_status to a status change. Over-constraining a log loses rows, and a
        # lost row is a hole in the record of what a customer was told — vendor_usage's call
        # about its error_code/is_success pairing, restated.
        sa.ForeignKeyConstraint(
            ["ticket_id"],
            ["support_tickets.id"],
            name=op.f("fk_support_ticket_events_ticket_id_support_tickets"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_support_ticket_events")),
    )

    # SQLite cannot ALTER an existing table to add an index without a rebuild, so every index
    # in this project is created inside batch_alter_table (render_as_batch=True).
    with op.batch_alter_table(_TICKETS, schema=None) as batch_op:
        for column, unique in _TICKET_INDEXES:
            batch_op.create_index(batch_op.f(f"ix_{_TICKETS}_{column}"), [column], unique=unique)
        batch_op.create_index(_TICKET_BOARD_INDEX, ["status", "created_at", "id"], unique=False)
        # UNIQUE over the pair. NULL-tolerant on both engines, which is what lets every
        # un-posted ticket — ``(NULL, NULL)`` — coexist while still permitting exactly one row
        # per real card.
        batch_op.create_index(
            _TICKET_CARD_INDEX, ["group_chat_id", "group_message_id"], unique=True
        )

    with op.batch_alter_table(_EVENTS, schema=None) as batch_op:
        for column, unique in _EVENT_INDEXES:
            batch_op.create_index(batch_op.f(f"ix_{_EVENTS}_{column}"), [column], unique=unique)
        batch_op.create_index(
            _EVENT_TIMELINE_INDEX, ["ticket_id", "created_at", "id"], unique=False
        )


def downgrade() -> None:
    with op.batch_alter_table(_EVENTS, schema=None) as batch_op:
        batch_op.drop_index(_EVENT_TIMELINE_INDEX)
        for column, _ in reversed(_EVENT_INDEXES):
            batch_op.drop_index(batch_op.f(f"ix_{_EVENTS}_{column}"))

    with op.batch_alter_table(_TICKETS, schema=None) as batch_op:
        batch_op.drop_index(_TICKET_CARD_INDEX)
        batch_op.drop_index(_TICKET_BOARD_INDEX)
        for column, _ in reversed(_TICKET_INDEXES):
            batch_op.drop_index(batch_op.f(f"ix_{_TICKETS}_{column}"))

    # The child first: it carries ON DELETE CASCADE to support_tickets.
    op.drop_table(_EVENTS)
    op.drop_table(_TICKETS)
