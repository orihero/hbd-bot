"""``bot_chats`` — every group the bot knows it is in, and the one that receives tickets.

Until this table, the Telegram support group was ``BAYRAM_SUPPORT_GROUP_CHAT_ID``: an
environment variable, changed by editing a unit file and redeploying. This table is what
replaces it, and the whole shape of it follows from one fact about Telegram that no amount of
engineering moves.

**TELEGRAM HAS NO "LIST MY GROUPS" API, AND THAT CONSTRAINT IS THE DESIGN.** A bot cannot
enumerate the chats it belongs to. The only way it ever learns a group exists is a
``my_chat_member`` update, which Telegram delivers when its OWN membership changes — so a
group the bot was already in when this feature shipped produces no event, appears nowhere, and
cannot be backfilled from anything. There is no historical source to reconstruct it from
either: ``support_tickets.group_chat_id`` records the chat a card was posted INTO, which is
the id the old setting held, and inventing a row from it would fabricate a title, a type and a
membership status nobody ever observed. Consequently this table is created EMPTY and fills
forward, and the manual paste is not a convenience — it is the only route that exists for a
group that already has the bot in it. :class:`~bayram.contracts.BotChatSource` is what keeps
the two routes visibly different, because they carry different amounts of truth.

**EVERY COLUMN ON THIS TABLE IS ABOUT A GROUP, AND ONE AVAILABLE COLUMN IS DELIBERATELY NOT
STORED.** ``my_chat_member`` carries ``from_user`` — the actual person who added the bot,
with their Telegram id, their name and their ``@handle``. It is right there, it would be
mildly interesting in the panel, and it is not written anywhere, because writing it would
make this a table ABOUT A PERSON: it would need an erasure route, a place in one of
``tests/test_db/test_privacy_constraints.py``'s two sets, and an answer to what ``/forget``
does to a group somebody else still uses. Leaving it out is what lets that file's paragraph
say, without qualification, that this table holds nothing about a customer. The one human
name here is :attr:`BotChatRow.selected_by_username` — an OPERATOR's own login, denormalised
exactly as ``admin_audit_log.actor_username`` and ``broadcasts.created_by_username`` are, and
for the identical reason: a rename must not silently rewrite who repointed the support inbox.

**AT MOST ONE SELECTED GROUP, ENFORCED BY THE DATABASE AND NOT BY THE WRITER.** See
:data:`SELECTED_SUPPORT_GROUP_PREDICATE`. The partial unique index is the invariant; the
select endpoint's single-transaction "clear the old, set the new" is what stops the common
path from depending on a failure. Both halves are needed and neither substitutes for the
other — ``admin_users``' active-OWNER index makes exactly this argument, and it was written
after two overlapping transactions really did commit two OWNERs.

**THE SELECTION IS NOT A CAPABILITY, WHICH IS WHY ``verified_at`` AND ``verification_error``
ARE COLUMNS.** Selecting a chat records an intent; it proves nothing. A pasted id may be a
typo, a group the bot was thrown out of, or a supergroup where an administrator has had
``can_post_messages`` taken away without any membership transition being sent. So the panel
never claims success on the POST: the ``support:verify_group`` job calls Telegram, posts a
confirmation, and writes one of these two columns. They are mutually exclusive by convention
and not by a ``CheckConstraint``, deliberately — ``vendor_usage``'s call about its
``error_code``/``is_success`` pairing, restated: over-constraining a record loses rows, and
the row we would lose here is the one that says why an operator's group does not work.

**WHY BOTH ``created_at`` AND ``first_seen_at`` EXIST, WHICH LOOKS REDUNDANT AND IS NOT.**
``created_at`` is OUR clock — when this process wrote the row. ``first_seen_at`` and
``last_seen_at`` are TELEGRAM's: they come from ``ChatMemberUpdated.date``, the instant
Telegram stamped the transition itself. ``bayram.bot.handlers.membership`` already refuses to
substitute ``deps.clock()`` for ``event.date`` for this reason, and the gap between the two is
real — every membership update that arrived while the bot was down is discarded by
``delete_webhook(drop_pending_updates=True)`` on the next start, so a row can be written long
after the event it describes, or never. Collapsing them would quietly downgrade Telegram's own
stamp to the accuracy of whenever our worker next happened to be running.

**THE BASIC-GROUP TO SUPERGROUP MIGRATION IS A REAL EVENT, AND THIS TABLE DOES NOT REWRITE
ITSELF WHEN IT HAPPENS.** Telegram upgrades a basic group to a supergroup on its own and the
chat id CHANGES; the new chat arrives here as a NEW ROW through its own membership event, and
the old row is left exactly as it is, still selected, still pointing at an id that no longer
accepts a message. That is deliberate, and the alternative — an ``UPDATE`` that moves
``chat_id`` to the new value — is refused on two grounds. First, ``chat_id`` is the primary
key and other tables already hold it as a value: ``support_tickets.group_chat_id`` records
which chat each card was posted into, and revision ``0027``'s card latch is unique per chat
precisely BECAUSE that id changes — rewriting the id here would make those rows claim cards
were posted somewhere they were not. Second, it would move the selection to a chat no operator
chose, silently, on Telegram's initiative. So the dead selection stands and the verification
job is what says so, in words: the sweep sees ``getChat`` report the migration, writes a
:attr:`verification_error` naming the new id, and an operator selects it. A stale selection
that announces itself is recoverable; a selection that moved on its own is not auditable at
all.

**NO FOREIGN KEY ANYWHERE ON THIS TABLE.** Not to ``admin_users`` (the operator who selected a
group must be deletable without the selection's history going with them — ``admin_audit_log``'s
rule) and not from ``support_tickets.group_chat_id`` to this table's primary key, which is the
tempting one. A ticket's card was posted into whatever chat was selected at the time, and that
chat may since have been removed from this table by an operator tidying up; a foreign key would
either block that tidy-up or cascade away the record of where a customer's complaint was
handled. The two columns hold the same kind of value and answer different questions.

**IN NEITHER OF ``tests/test_db/test_privacy_constraints.py``'s TWO SETS**, argued there rather
than left silent, on the footing this module's second paragraph establishes: a chat id, a chat
title, a public ``@handle``, three closed enums, a boolean, two clocks from Telegram, an
operator's login and a bounded error string. Nothing on this row is text about a customer, and
the one field that would have been is the one that is not stored.
"""

from __future__ import annotations

from datetime import datetime
from typing import Final

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from bayram.contracts import BotChatSource, BotChatStatus, BotChatType
from bayram.db.base import Base, TimestampMixin, UtcDateTime, enum_type
from bayram.db.models.admin_audit import ACTOR_USERNAME_LENGTH

__all__ = [
    "BotChatRow",
    "BOT_CHAT_TITLE_LENGTH",
    "BOT_CHAT_USERNAME_LENGTH",
    "VERIFICATION_ERROR_LENGTH",
    "SELECTED_SUPPORT_GROUP_INDEX",
    "SELECTED_SUPPORT_GROUP_PREDICATE",
]

#: Telegram's own ceiling on a chat title is 128 characters. Sized to the vendor's bound
#: rather than to a guess, so the column cannot truncate a title that really exists — which
#: matters here because the title is the ONLY way an operator recognises which of four
#: negative numbers is the group they meant.
BOT_CHAT_TITLE_LENGTH: Final[int] = 128
#: A Telegram ``@handle`` is at most 32 characters. Public supergroups only; NULL is the
#: ordinary case, not a missing value.
BOT_CHAT_USERNAME_LENGTH: Final[int] = 32
#: The last verification failure, in words an operator can act on ("the bot is not a member of
#: this chat", "this group became supergroup -100…"). Bounded because it is rendered in a list
#: row, and short because a message longer than this is a stack trace somebody pasted rather
#: than an instruction somebody can follow. It is never a vendor exception's ``repr``.
VERIFICATION_ERROR_LENGTH: Final[int] = 200

#: The partial unique index that makes "at most one selected support group" true rather than
#: intended. Named here so the select endpoint can recognise the violation it raises without
#: parsing a driver's prose, and so revision ``0028`` and this model cannot drift apart —
#: ``test_the_migrated_indexes_match_the_model_metadata`` compares index NAMES byte for byte,
#: so a templated name on one side would leave the model declaring an index the chain never
#: builds. ``ACTIVE_OWNER_INDEX`` on ``admin_users`` is the exemplar for both the shape and
#: the export.
SELECTED_SUPPORT_GROUP_INDEX: Final[str] = "ix_bot_chats_selected_support_group"

#: ``is_support_group`` — the whole predicate, and the reason the index is PARTIAL.
#:
#: A plain ``UNIQUE (is_support_group)`` would allow one selected row AND one unselected row,
#: which is a schema that permits at most two chats to exist. The predicate is what narrows
#: the uniqueness to the rows that make a claim: every ``false`` row is outside the index and
#: unconstrained, and the ``true`` rows are constrained to one.
#:
#: **Spelled as a bare column name, on purpose, because it has to render on BOTH engines.**
#: The unit suite is SQLite and the migration test is Postgres. SQLite has had partial indexes
#: since 3.8.0 and evaluates a bare integer column as a boolean; Postgres accepts a boolean
#: column as a predicate directly. One string therefore serves both, with no ``= true`` and no
#: ``= 1`` — either of those renders on one engine and is a portability bug on the other.
#: ``ACTIVE_OWNER_PREDICATE`` makes the same call for the same pair of engines.
#:
#: It is a literal string here and a literal string again in revision ``0028`` rather than
#: being imported: a migration may never import application code
#: (``test_no_migration_imports_application_code``), and a revision that has already run
#: everywhere has to keep meaning what it meant after this module is renamed.
SELECTED_SUPPORT_GROUP_PREDICATE: Final[str] = "is_support_group"


class BotChatRow(TimestampMixin, Base):
    """One chat the bot has been added to, or one an operator claims it is in.

    ``TimestampMixin`` IS used, unlike on this package's append-only tables. This row is
    mutable state in every direction — the bot's status changes when it is promoted or
    removed, the title changes when somebody renames the group, the selection moves when an
    operator repoints it, and the verification columns are rewritten on every sweep — so
    ``updated_at`` is true, and it is the cheapest evidence of when a chat last moved at all.

    **No ORM relationship to anything.** There is nothing to relate it to (see the module
    docstring on why ``support_tickets.group_chat_id`` carries no foreign key), and the
    standing rule in this package holds regardless: an implicit lazy load inside async
    SQLAlchemy surfaces as a greenlet error at a random await point, so a relationship added
    later takes ``lazy="raise"``.

    **THE UPSERT THAT THE BOT PERFORMS MUST NAME ITS COLUMNS, AND MUST NOT NAME THE OTHERS.**
    This is the one way to break the table from outside it, so it is written down here rather
    than left to the handler. A ``my_chat_member`` update knows six things: the id, the type,
    the title, the username, the bot's new status and the instant. Those are the columns its
    ``ON CONFLICT DO UPDATE`` may set, alongside :attr:`last_seen_at`. It must NOT touch
    :attr:`is_support_group`, :attr:`thread_id`, :attr:`selected_by_username`,
    :attr:`selected_at`, :attr:`verified_at` or :attr:`verification_error` — an update that
    reset them would mean that the bot being promoted to administrator in the selected group,
    or re-added to it after a restart, silently unselected the support inbox and the tickets
    stopped arriving with nothing in any log to say why.
    """

    __tablename__ = "bot_chats"
    __table_args__ = (
        # AT MOST ONE SELECTED SUPPORT GROUP, enforced by the database.
        #
        # The write path clears the previous selection and sets the new one in ONE
        # transaction, and that is genuinely the mechanism on the ordinary path — this index
        # is not a substitute for it. It is what closes the path the transaction cannot:
        # under Postgres' READ COMMITTED two operators pressing Select at the same moment
        # each read a table with one selected row, each clear the row they read, and each set
        # their own — and both commit, leaving two. ``admin_users`` carries the identical
        # index for the identical reason, and there it was not theorised: two engines behind
        # an ``asyncio`` barrier produced two active OWNERs in five trials out of five on
        # Postgres 16, while SQLite passed every time because its write lock serialises the
        # insert. The unit suite could not have caught it there and cannot here.
        #
        # What breaks if somebody "simplifies" this to a plain unique constraint: the second
        # UNSELECTED chat is rejected, and the panel can never list more than two groups. What
        # breaks if it is deleted in favour of "the transaction already handles it": nothing,
        # for months, and then two groups receive half the tickets each and the operator who
        # notices has no way to tell which one is correct.
        #
        # Hand-named, and spelled identically in revision 0028: see
        # :data:`SELECTED_SUPPORT_GROUP_INDEX`.
        sa.Index(
            SELECTED_SUPPORT_GROUP_INDEX,
            "is_support_group",
            unique=True,
            postgresql_where=sa.text(SELECTED_SUPPORT_GROUP_PREDICATE),
            sqlite_where=sa.text(SELECTED_SUPPORT_GROUP_PREDICATE),
        ),
        # NO OTHER INDEX ON THIS TABLE, and the omissions are decisions rather than an
        # oversight — revision 0012 had to reconcile three unused read indexes that were
        # shipped on exactly this reasoning being skipped.
        #
        # None on ``is_support_group`` by itself: the partial index above already serves the
        # one hot read there is, "which chat is selected", and on both engines it is a single
        # entry the planner goes straight to. None on ``chat_type``, ``bot_status`` or
        # ``source``: the panel's list is SELECT * over a table that holds as many rows as the
        # bot has been added to groups — a handful, ever — and an index on a three-valued
        # column over a handful of rows is a plan the planner will decline to use. None on
        # ``verified_at``: nothing sweeps this table, because there is nothing here to age out.
        # ``ix_bot_chats_created_at`` comes from ``TimestampMixin`` and is more index than the
        # row count earns, but it is the mixin's and not this table's to remove.
    )

    #: Telegram's own id for the chat, and the natural key — so it IS the primary key, with no
    #: surrogate UUID beside it. That is a departure from every other table added since
    #: revision 0014 and it is deliberate: a UUID here would be an id we minted for a row whose
    #: only purpose is to name something Telegram already named, and every writer would then
    #: have to look the row up by ``chat_id`` anyway to find it. ``credit_accounts`` takes the
    #: same shape for the same reason, keyed on the account it is about.
    #:
    #: ``BigInteger``, and the values are NEGATIVE: a group id is negative and a supergroup id
    #: begins ``-100``. An ``Integer`` column here would not fail loudly, it would silently
    #: truncate a real supergroup id and the panel would select a chat that does not exist.
    #:
    #: It is stable for the life of the chat with EXACTLY ONE exception — Telegram upgrading a
    #: basic group to a supergroup mints a new id — and the module docstring explains at
    #: length why that arrives as a new row rather than as an ``UPDATE`` of this column.
    chat_id: Mapped[int] = mapped_column(sa.BigInteger, primary_key=True, autoincrement=False)
    #: ``group`` / ``supergroup`` / ``channel``. Never ``private``; see
    #: :class:`bayram.contracts.BotChatType` for why that absence is load-bearing.
    chat_type: Mapped[BotChatType] = mapped_column(enum_type(BotChatType), nullable=False)
    #: What the group calls itself. NULL is tolerated rather than expected: Telegram supplies a
    #: title on every group and supergroup, but a MANUAL row is a bare id with no title behind
    #: it until the verification job's ``getChat`` fetches one — and refusing to store the row
    #: until then would mean an operator could not paste an id at all. It is refreshed on every
    #: membership update, so a renamed group is renamed here rather than showing the panel a
    #: name nobody uses any more.
    title: Mapped[str | None] = mapped_column(sa.String(BOT_CHAT_TITLE_LENGTH), nullable=True)
    #: The public ``@handle``, which only a public supergroup has. NULL for every private
    #: group, which is most of them and is not a gap.
    username: Mapped[str | None] = mapped_column(sa.String(BOT_CHAT_USERNAME_LENGTH), nullable=True)
    #: What Telegram last said about the bot's standing here. Includes ``unknown``, which is
    #: the member that keeps this column honest when Telegram's vocabulary grows — see
    #: :class:`bayram.contracts.BotChatStatus`. It is evidence, never permission: whether the
    #: bot can actually post is :attr:`verified_at`'s question and only the job that tried can
    #: answer it.
    bot_status: Mapped[BotChatStatus] = mapped_column(enum_type(BotChatStatus), nullable=False)
    #: Telegram's own word that the bot is here, or an operator's claim that it is. The panel
    #: MUST render this: a ``manual`` row is unverified until the job says otherwise, and
    #: showing the two identically would present a typo with the same confidence as a fact.
    source: Mapped[BotChatSource] = mapped_column(enum_type(BotChatSource), nullable=False)

    # -- the selection -------------------------------------------------------
    #: THE selection, and the only authority there is — there is no setting behind it, no
    #: seed, no pin and no precedence rule to reason about. ``BAYRAM_SUPPORT_GROUP_CHAT_ID``
    #: and ``BAYRAM_SUPPORT_GROUP_THREAD_ID`` are removed in this change rather than kept as a
    #: fallback, because a fallback is a second answer to a question that must have one: an
    #: operator who repoints the inbox and then sees tickets still arriving in the old group
    #: has no way to discover that a unit file is overriding them.
    #:
    #: At most one row may hold ``true``; see the table argument above. Defaulted in the mapper
    #: and given NO ``server_default`` — this table is created empty and has no backfill, so
    #: 0024's rule applies: the ``false`` is written by the row's own creator.
    is_support_group: Mapped[bool] = mapped_column(sa.Boolean, nullable=False, default=False)
    #: An optional forum topic within the selected group, set by the same call that selects.
    #: NULL means "post to the group itself", which is what a non-forum group can do and is the
    #: ordinary case. It lives beside the selection rather than on a settings object because a
    #: topic id is meaningless apart from the chat it is a topic OF — the two have always had
    #: to move together, and as two environment variables they could be edited apart.
    thread_id: Mapped[int | None] = mapped_column(sa.BigInteger, nullable=True)

    # -- what the verification job found -------------------------------------
    #: The last time the job PROVED it can post here — it called ``getChat`` and put a message
    #: in the chat. Not "the last time the bot was a member", which is :attr:`bot_status` and a
    #: weaker claim. NULL means nobody has checked since the row was written.
    verified_at: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)
    #: Why the last check failed, in an operator's language: chat not found, the bot is not a
    #: member, the bot cannot post there, the chat migrated to a new id. A single generic
    #: string here would defeat the purpose of the whole feature, because the four failures
    #: need four different things done about them and only the operator can do them.
    #: Mutually exclusive with a current :attr:`verified_at` by convention, not by a
    #: ``CheckConstraint``; see the module docstring.
    verification_error: Mapped[str | None] = mapped_column(
        sa.String(VERIFICATION_ERROR_LENGTH), nullable=True
    )

    # -- who repointed the inbox, and when -----------------------------------
    #: The operator's login, denormalised with no foreign key to ``admin_users``, exactly as
    #: ``admin_audit_log.actor_username`` and ``broadcasts.created_by_username`` are: an
    #: operator who leaves must not take the record of what they changed with them, and a
    #: rename must not rewrite it. This is the ONLY human name on this table, and it is an
    #: operator's rather than a customer's — the module docstring explains why the person who
    #: added the bot, whom Telegram hands us for free, is deliberately not stored beside it.
    #:
    #: The row here is a convenience for the list screen. The tamper-evident record of the act,
    #: with the role the operator held at the time, is the ``admin_audit_log`` entry.
    selected_by_username: Mapped[str | None] = mapped_column(
        sa.String(ACTOR_USERNAME_LENGTH), nullable=True
    )
    #: When the selection was last made. NOT cleared when a chat is unselected, deliberately:
    #: "this was once the support group" is the most useful thing to know about a chat an
    #: operator is looking at while wondering where last month's tickets went.
    selected_at: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)

    # -- Telegram's clocks, which are not ours --------------------------------
    #: ``ChatMemberUpdated.date`` from the first membership update we saw for this chat — or,
    #: for a ``manual`` row, the instant the operator pasted the id, which is the only instant
    #: that exists for it. NOT NULL: a chat we know about was known about at some moment.
    first_seen_at: Mapped[datetime] = mapped_column(UtcDateTime, nullable=False)
    #: The most recent one. Refreshed by every membership update, which is what makes it the
    #: answer to "is this group still live?" for a bot that cannot ask Telegram that question.
    #: Equal to :attr:`first_seen_at` on a row that has been seen exactly once.
    last_seen_at: Mapped[datetime] = mapped_column(UtcDateTime, nullable=False)
