"""Add bot_chats: the groups the bot knows about, and the one that receives tickets.

Revision ID: 0028
Revises: 0027
Create Date: 2026-09-15

Amends ``SUPPORT_TICKETS_SPEC §2.1``'s schema and the ``DECISIONS.md`` D18 amendment of the
same date: the Telegram support group stops being ``BAYRAM_SUPPORT_GROUP_CHAT_ID``, an
environment variable that needs a unit-file edit and a redeploy to change, and becomes a row
an operator picks in the panel. This table is the picker's whole storage.

**TELEGRAM HAS NO "LIST MY GROUPS" API, AND EVERYTHING BELOW FOLLOWS FROM IT.** A bot cannot
enumerate the chats it is in. The only way it learns a group exists is a ``my_chat_member``
update, delivered when its OWN membership changes — which means a group the bot was ALREADY
in when this revision lands produces no event, appears nowhere, and cannot be discovered.
That is Telegram's limitation and not a gap this schema can engineer around, so the table
fills FORWARD from membership events and carries ``source`` to mark the rows that arrived the
other way, as an operator's pasted id. The panel must render that column: a ``manual`` row is
an unverified claim, and showing it with the same confidence as a row Telegram sent us would
present a typo as a fact.

**THE TABLE IS CREATED EMPTY, AND THERE IS NO BACKFILL — NOT EVEN THE TEMPTING ONE.** The
tempting one is ``SELECT DISTINCT group_chat_id FROM support_tickets``: those ids are real
chats that really received cards. It is still refused, because a row minted from one would
have to invent a ``chat_type``, a ``bot_status``, a ``title`` and a ``first_seen_at`` that were
never observed — and it would write them with ``source = 'membership_event'``, which is a
claim that Telegram told us something it never told us. An id an operator recognises is
exactly what the manual field is for, so the honest backfill is one paste. Consequently NO
column here carries a ``server_default``, including ``is_support_group``: its ``false`` is
written by the row's own creator, which is 0024's and 0027's rule and for once has no existing
rows to argue about at all.

**THE SUBTLE PART IS THE PARTIAL UNIQUE INDEX, AND IT RENDERS ON BOTH ENGINES.**
``ix_bot_chats_selected_support_group`` is UNIQUE over ``is_support_group`` WHERE
``is_support_group`` — so at most one row may claim the selection, while any number of
unselected chats coexist. Three things about it are load-bearing:

* **It must be PARTIAL.** A plain ``UNIQUE (is_support_group)`` would permit one ``true`` row
  and one ``false`` row, which is a schema in which the panel can never list more than two
  groups at all.
* **The predicate is a bare column name.** SQLite has had partial indexes since 3.8.0 and
  evaluates an integer column as a boolean; Postgres accepts a boolean column as a predicate
  directly. One string therefore serves both engines, where ``= true`` and ``= 1`` each render
  on one and break on the other. Revision ``0010`` makes the identical call for
  ``ix_admin_users_active_owner``, and the unit suite runs on SQLite while
  ``test_migration_applies_and_reverses_against_postgres`` runs on the real engine — a
  predicate that rendered on only one of them would pass locally and fail on deploy.
* **It is the invariant, and the single-transaction write is the mechanism.** The select
  endpoint clears the previous selection and sets the new one in ONE transaction, and that is
  what makes the ordinary path not depend on a failure. This index is what closes the path the
  transaction cannot: under Postgres' READ COMMITTED two operators pressing Select at the same
  moment each read one selected row, each clear the row they read, each set their own, and
  both commit. Revision ``0010`` did not theorise that race — two engines behind an
  ``asyncio`` barrier produced two active OWNERs in five trials out of five on Postgres 16,
  and SQLite passed every time because its write lock serialises the insert. Neither half
  substitutes for the other.

It is created with a bare ``op.create_index`` rather than inside ``batch_alter_table``,
following ``0010``: an index needs no table rewrite on either dialect, and batch mode would
copy a table that was created four statements ago for nothing. The templated
``ix_bot_chats_created_at`` from ``TimestampMixin`` goes through batch mode like every other
index in this project, so it takes ``NAMING_CONVENTION``'s ``ix`` template and matches the
model's ``index=True`` exactly.

**WHY ``chat_id`` IS THE PRIMARY KEY AND THERE IS NO SURROGATE UUID.** Every table added since
revision ``0014`` keys on a ``sa.Uuid`` we mint. This one does not, because Telegram already
named the thing and a second id would mean every writer looked the row up by ``chat_id``
anyway. ``BigInteger`` and not ``Integer``: a group id is NEGATIVE and a supergroup id begins
``-100``, comfortably outside 32 bits, and an ``Integer`` column would not fail loudly — it
would truncate a real id and the panel would select a chat that does not exist.

**WHAT HAPPENS WHEN A BASIC GROUP BECOMES A SUPERGROUP, WHICH IS A REAL EVENT AND NOT A
HYPOTHETICAL.** Telegram performs the upgrade itself and the chat id CHANGES. This schema does
NOT rewrite the row: the new chat arrives as its own row through its own membership event, and
the old one is left selected, pointing at an id that no longer takes a message, until the
verification job writes a ``verification_error`` naming the new id and an operator selects it.
Moving ``chat_id`` in place was considered and refused twice over. It is the primary key, and
other tables already hold its value: ``support_tickets.group_chat_id`` records which chat each
card was posted INTO, and revision ``0027``'s card latch is unique per chat PRECISELY because
that id changes — so rewriting it here would make old ticket rows claim their cards were posted
somewhere they were not. And it would move the support inbox to a chat no operator chose, on
Telegram's initiative, with nothing in any log to say so. A stale selection that announces
itself is recoverable; one that moved on its own is not auditable at all. That is also why
there is no ``ForeignKeyConstraint`` from ``support_tickets.group_chat_id`` to this table: a
card was posted into whatever chat was selected at the time, and an operator tidying an old
chat out of this table must not take that record with it.

**WHY EACH NULLABLE COLUMN IS NULLABLE.** ``title`` and ``username`` are NULL on a ``manual``
row until ``getChat`` fetches them, and ``username`` is NULL forever on any private group,
which is most of them; ``thread_id`` is NULL whenever the destination is the group itself,
which is every non-forum group; ``verified_at`` is NULL until the job has proved it can post,
and ``verification_error`` is NULL while nothing has gone wrong; ``selected_by_username`` and
``selected_at`` are NULL on every chat nobody has ever selected, which is nearly all of them.
``first_seen_at`` and ``last_seen_at`` are NOT NULL because a chat we know about was known
about at some moment — and they hold TELEGRAM's instant (``ChatMemberUpdated.date``) rather
than ours, which is why they sit beside ``created_at`` instead of being folded into it.

**PRIVACY — THIS TABLE IS IN NEITHER OF ``tests/test_db/test_privacy_constraints.py``'s TWO
SETS, AND THE ARGUMENT IS WRITTEN DOWN THERE RATHER THAN LEFT SILENT.** Every column is about
a GROUP: a chat id, a chat title, a public ``@handle``, three closed enums, a boolean, a
thread id, two clocks and a bounded error string. The one human name is
``selected_by_username``, an OPERATOR's login, denormalised exactly as
``admin_audit_log.actor_username`` is. **ONE FIELD WAS AVAILABLE AND IS DELIBERATELY NOT
STORED, which is what keeps that claim true rather than nearly true:** ``my_chat_member``
carries ``from_user`` — the actual person who added the bot, with their id, name and handle —
and storing it would make this a personal-data table needing an erasure route and an answer to
what ``/forget`` does to a group somebody else still uses. Nothing here is on a retention clock
and no column ends in ``*_expires_at``: in this codebase that suffix is a published legal
schedule that obliges a sweep BY NAME in ``tests/test_db/test_audit_retention.py``, and a table
holding a handful of rows — one per group the bot has ever been added to — is not growth. No
``purge_runs`` counter is added for the same reason: nothing sweeps this table.

**Every enum is spelled literally, every clock is a plain ``sa.DateTime(timezone=True)``, and
every length is a literal int even where the model declares a ``Final``.** A migration that
imports application code breaks historically, on a revision that already ran everywhere, and
``test_no_migration_imports_application_code`` enforces it; ``env.py`` renders ``UtcDateTime``
as a timezone-aware ``DateTime`` precisely so our own column types never have to be named here.
``enum_type`` renders ``VARCHAR(32)`` with ``create_constraint`` off, so **a fourth chat type,
or a seventh bot status when Telegram invents one, needs NO follow-up revision at all** —
there is no native enum and no CHECK to alter.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0028"
down_revision: str | None = "0027"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLE = "bot_chats"

#: Spelled as literal ints even though the model declares them as ``Final`` constants, for the
#: reason revision 0024 re-declares ``_CAPTION_LENGTH`` and 0027 re-declares its four: this
#: file may never import ``bayram.*``, and a revision that already ran everywhere has to keep
#: meaning what it meant after that module is renamed.
#:
#: 128 is Telegram's own ceiling on a chat title; 32 is the longest ``@handle`` Telegram
#: issues; 200 is a sentence an operator can act on, not a pasted stack trace; 64 is
#: ``admin_audit_log.actor_username``'s width, restated for a denormalised operator name.
_TITLE_LENGTH = 128
_CHAT_USERNAME_LENGTH = 32
_VERIFICATION_ERROR_LENGTH = 200
_ACTOR_USERNAME_LENGTH = 64

#: ``(column, unique)``, created through ``batch_op.f()`` so it takes ``NAMING_CONVENTION``'s
#: ``ix`` template and matches the model's ``index=True`` declaration exactly. Only the
#: mixin's clock is here; every omission is argued in the model's ``__table_args__``.
_INDEXES: tuple[tuple[str, bool], ...] = (("created_at", False),)

#: THE INVARIANT: at most one selected support group. Hand-named, and spelled identically in
#: ``bayram.db.models.bot_chat.SELECTED_SUPPORT_GROUP_INDEX``, because
#: ``test_the_migrated_indexes_match_the_model_metadata`` compares index NAMES byte for byte —
#: a templated name on either side would leave the model declaring an index the chain never
#: builds.
_SELECTED_INDEX = "ix_bot_chats_selected_support_group"
#: Mirrors ``bayram.db.models.bot_chat.SELECTED_SUPPORT_GROUP_PREDICATE``. A bare column name,
#: so that one string renders on SQLite (which evaluates an integer column as a boolean) and
#: on Postgres (which takes a boolean column as a predicate) alike — see the module docstring.
_SELECTED_PREDICATE = "is_support_group"


def upgrade() -> None:
    op.create_table(
        _TABLE,
        # Telegram's own id, NEGATIVE for groups and supergroups, and the natural key — so it
        # is the primary key, with no surrogate UUID beside it. See the module docstring.
        sa.Column("chat_id", sa.BigInteger(), autoincrement=False, nullable=False),
        # ``private`` is deliberately absent: a private chat belongs to the OTHER
        # my_chat_member registration, the one that records churn against users, and a private
        # chat reaching this table would mean the two had stopped being disjoint.
        sa.Column(
            "chat_type",
            sa.Enum(
                "group",
                "supergroup",
                "channel",
                name="botchattype",
                native_enum=False,
                length=32,
            ),
            nullable=False,
        ),
        sa.Column("title", sa.String(length=_TITLE_LENGTH), nullable=True),
        # A public supergroup's @handle. NULL for every private group, which is most of them.
        sa.Column("username", sa.String(length=_CHAT_USERNAME_LENGTH), nullable=True),
        # ``unknown`` is a real member and not a placeholder: Telegram's member statuses are
        # not a closed set this code controls, and a status we cannot spell must become a
        # stored row plus a WARNING rather than a dropped update.
        sa.Column(
            "bot_status",
            sa.Enum(
                "member",
                "administrator",
                "restricted",
                "left",
                "kicked",
                "unknown",
                name="botchatstatus",
                native_enum=False,
                length=32,
            ),
            nullable=False,
        ),
        # Telegram's own word that the bot is here, or an operator's claim that it is. The
        # panel must show which; see the module docstring.
        sa.Column(
            "source",
            sa.Enum(
                "membership_event",
                "manual",
                name="botchatsource",
                native_enum=False,
                length=32,
            ),
            nullable=False,
        ),
        # -- the selection ----------------------------------------------------------------
        # At most one row may hold true, enforced by the partial unique index below. No
        # server_default: the table is created empty and has no backfill, so the false is
        # written by the row's own creator.
        sa.Column("is_support_group", sa.Boolean(), nullable=False),
        # An optional forum topic within the selected group. NULL means the group itself.
        sa.Column("thread_id", sa.BigInteger(), nullable=True),
        # -- what the verification job found ----------------------------------------------
        # The last time the job PROVED it can post here — not the last time the bot was a
        # member, which is bot_status and a weaker claim. UtcDateTime renders as a
        # timezone-aware DateTime; env.py exists so our own column types are never named here.
        sa.Column("verified_at", sa.DateTime(timezone=True), nullable=True),
        # Why the last check failed, in words an operator can act on. Four distinguishable
        # failures, because they need four different things done about them.
        sa.Column(
            "verification_error", sa.String(length=_VERIFICATION_ERROR_LENGTH), nullable=True
        ),
        # -- who repointed the inbox -------------------------------------------------------
        # Denormalised, with no ForeignKeyConstraint to admin_users: an operator who leaves
        # must not take the record of what they changed with them. The tamper-evident version
        # of this act, with the role held at the time, is the admin_audit_log row.
        sa.Column("selected_by_username", sa.String(length=_ACTOR_USERNAME_LENGTH), nullable=True),
        # NOT cleared when a chat is unselected: "this was once the support group" is the
        # useful thing to know about a chat somebody is looking at.
        sa.Column("selected_at", sa.DateTime(timezone=True), nullable=True),
        # -- Telegram's clocks, which are not ours -----------------------------------------
        # ChatMemberUpdated.date, the instant Telegram stamped the transition, beside
        # created_at which is the instant we wrote the row. The gap between them is real: every
        # membership update that arrived while the bot was down is dropped on the next start.
        sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        # Deliberately NO CheckConstraint pairing verified_at with verification_error. They are
        # mutually exclusive by convention and over-constraining the record would lose exactly
        # the row that says why an operator's group does not work — vendor_usage's call about
        # its error_code/is_success pairing, restated.
        sa.PrimaryKeyConstraint("chat_id", name=op.f("pk_bot_chats")),
    )

    # SQLite cannot ALTER an existing table to add an index without a rebuild, so every
    # templated index in this project is created inside batch_alter_table
    # (render_as_batch=True).
    with op.batch_alter_table(_TABLE, schema=None) as batch_op:
        for column, unique in _INDEXES:
            batch_op.create_index(batch_op.f(f"ix_{_TABLE}_{column}"), [column], unique=unique)

    # THE INVARIANT: at most one selected support group, on both engines.
    #
    # Not inside batch_alter_table, following revision 0010: creating an index needs no table
    # rewrite on either dialect, and batch mode would copy a table created four statements ago
    # for nothing. Bare ``_SELECTED_INDEX`` and not ``op.f(...)``: the name is hand-chosen
    # rather than templated, and the model spells the same literal.
    op.create_index(
        _SELECTED_INDEX,
        _TABLE,
        ["is_support_group"],
        unique=True,
        postgresql_where=sa.text(_SELECTED_PREDICATE),
        sqlite_where=sa.text(_SELECTED_PREDICATE),
    )


def downgrade() -> None:
    op.drop_index(_SELECTED_INDEX, table_name=_TABLE)

    with op.batch_alter_table(_TABLE, schema=None) as batch_op:
        for column, _ in reversed(_INDEXES):
            batch_op.drop_index(batch_op.f(f"ix_{_TABLE}_{column}"))

    op.drop_table(_TABLE)
