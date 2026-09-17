"""``support_tickets`` — one complaint, from the tap that opened it to the reply that closed it.

The ⚠️ button under a delivered song used to render a sentence and nothing else. A customer
who pressed it was told where to write, and whatever they wrote landed in a chat nobody owned:
there was no row, no reference to quote back, no queue to work and no way to answer "how many
people told us the name was wrong last month?" This table is that missing row, and everything
about its shape follows from the three places the same ticket has to be legible at once — the
customer's private chat, the staff group, and the operator's board.

**THE TICKET IS DB-BACKED AND DELIBERATELY FSM-FREE, WHICH IS WHY ``prompt_message_id``
EXISTS.** The obvious flow parks the customer in an aiogram state and reads their next message.
That would be wrong here, and quietly: ⚠️ sits under a delivery message that may be a month
old, ``navigation``'s handlers are deliberately not state-filtered, and a customer can tap it
while a NEW wizard is half-finished — so ``set_state`` would clobber a draft they are still
typing into. Instead the ForceReply prompt's own ``message_id`` is written here, and the
customer's description is recognised by ``reply_to_message.message_id`` matching it. The
consequence is the point: ordinary wizard input is never swallowed, no FSM key is added to
``bot/draft.py``'s nine, and ``clear_keeping_identity`` has nothing new to drop.

**``described_at`` IS NULL FOR A REAL AND COMMON ROW, NOT A MISSING VALUE.** A customer taps ⚠️
and never types — they changed their mind, the prompt scrolled away, they were on the bus.
That row is data: it is the only measure of how many people started to complain and gave up,
and it is the number the rate limiter meters against. It is excluded from the board by
``described_at IS NOT NULL`` rather than deleted, because deleting it would make the count of
attempts equal to the count of complaints by construction, which is the one arithmetic this
table exists to disprove. :attr:`SupportTicketRow.body` is NULL beside it for the same reason
and always in step.

**``group_chat_id`` AND ``group_message_id`` ARE A ONCE-ONLY LATCH, NOT A CACHE.** ARQ runs
with ``retry_jobs=True`` and SIGTERM cancels a running job, so every job in this system is
replayed on every deploy; a record of "the card was posted" that lives in the job is a record
that posts the card again. The pair is therefore claimed with a conditional ``UPDATE`` whose
rowcount is the lock, BEFORE the Telegram call, and settled after — exactly the shape
``payment_intents.resumed_at`` (revision 0026) takes for a resumed render, and for the
identical reason. The unique index over the PAIR is the other half: a staffer replying to a
card must resolve to exactly one ticket, and two rows claiming one message would relay a
stranger's answer to the wrong customer.

**AND THE UNIQUENESS IS PER CHAT, WHICH IS THE CORRECTION WORTH READING BEFORE TOUCHING IT.**
A Telegram ``message_id`` is a counter within one chat, not an identifier across Telegram, so
``UNIQUE (group_message_id)`` on its own is a claim Telegram never made. It is also actively
harmful: move the support group — a new group, or Telegram auto-upgrading a basic group to a
supergroup, which CHANGES the chat id — and the next card Telegram numbers 5 in the new chat
collides with a card numbered 5 in the old one. The post succeeded and the latch fails, which
leaves a ticket permanently un-latched and an orphan card in the group that nothing can edit
or relay from. The uniqueness is therefore ``(group_chat_id, group_message_id)``, declared in
``__table_args__``, which is also the shape ``find_by_group_message`` reads on.

**A FAILED GROUP POST MUST NEVER LOSE THE TICKET.** The latch is left unset when Telegram
refuses, so the ticket is still written, still appears on the board, and can still be posted by
the next panel action or a sweep. The customer is confirmed either way. The group is where
tickets are convenient to work; it is never where they are kept.

**RETENTION — THE BODY IS KEPT INDEFINITELY, AND THAT IS AN ARGUED EXEMPTION.** The body is
free text a customer wrote about their own order, so it is genuinely personal data, and this
table is nevertheless in NEITHER of ``tests/test_db/test_privacy_constraints.py``'s two sets.
Its erasure route is ``/forget``, which deletes this customer's ticket bodies outright; the
written paragraph naming this table, revision ``0027`` and that route lives in that file, so
the exemption is a decision rather than the silence the file's own comment warns about. There
is deliberately NO ``*_expires_at`` column on either support table: in this codebase that
suffix is a published legal clock, and it obliges a sweep BY NAME in
``tests/test_db/test_audit_retention.py``, a ``RetentionPolicy`` field, a ``PurgeReport`` entry
and a ``purge_runs`` column. A support history that deleted itself on a schedule would also
delete the evidence in the one dispute it was kept for.

**NO FOREIGN KEY TO ``admin_users``**, and ``assigned_admin_username`` is denormalised for
``admin_audit_log``'s reason restated: a rename must not silently rewrite who worked a ticket,
and an operator who leaves must not take the queue's history with them.
"""

from __future__ import annotations

from datetime import datetime
from typing import Final
from uuid import UUID, uuid4

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from bayram.contracts import Language, SupportTicketSource, SupportTicketStatus
from bayram.db.base import Base, TimestampMixin, UtcDateTime, enum_type
from bayram.db.models.admin_audit import ACTOR_USERNAME_LENGTH

__all__ = [
    "SupportTicketRow",
    "SUPPORT_PUBLIC_REF_LENGTH",
    "SUPPORT_BODY_LENGTH",
]

#: The short reference a customer reads down a phone line — ``A3F2-91`` is seven characters,
#: and the bound is 12 so a longer shape (a group prefix, a check character) can be minted
#: later without a migration. Bounded rather than free because this string is rendered in a
#: list row, on a card and in a confirmation message, and a reference that wraps is a
#: reference somebody transcribes wrongly.
SUPPORT_PUBLIC_REF_LENGTH: Final[int] = 12
#: The customer's own words. Sized at Telegram's own single-message ceiling, which is the
#: hard bound on what can physically arrive: a customer cannot send more than this in one
#: message, so the column cannot truncate a complaint that was actually made.
#: ``broadcast_bodies.text`` uses the same number from the other direction, for what we send.
SUPPORT_BODY_LENGTH: Final[int] = 4096


class SupportTicketRow(TimestampMixin, Base):
    """One customer complaint: where it came from, what it says, and who has it.

    ``TimestampMixin`` IS used, unlike on this package's append-only tables. This row is a
    state machine — ``new -> in_progress -> waiting -> resolved``, with ``resolved`` reopening
    to ``in_progress`` — and every move is a conditional ``UPDATE``. ``updated_at`` is
    therefore true, and it is the cheapest evidence an operator has of when a ticket last
    moved, which is the number a "nothing has happened here for four days" filter reads.
    ``support_ticket_events`` beside it is the history; this row is the present.

    **No ORM relationship to the event table, and none to ``orders``.** Every other model in
    this package that could declare one declines for the same reason ``OrderRow`` states it:
    an implicit lazy load inside async SQLAlchemy surfaces as a confusing greenlet error at a
    random await point. The read layer runs separate statements — the shape ``get_broadcast``
    already uses to fetch a campaign, its bodies and its counters — so the detail a caller
    wants is the detail the caller asked for. If one is ever added it takes ``lazy="raise"``,
    as everywhere else in this schema.
    """

    __tablename__ = "support_tickets"
    __table_args__ = (
        # THE BOARD'S ONE SCAN, and every column of it earns its place:
        # ``WHERE status = :column ORDER BY created_at, id`` per Kanban column, paged by
        # keyset. ``id`` is the THIRD column and not an afterthought — without it Postgres
        # adds an ``Incremental Sort … Presorted Key: created_at`` on every page, and the sort
        # buffer grows with the size of the tie group, which a burst of tickets from one
        # outage is made of. ``ix_orders_state_created_at`` is the exemplar, and the mistake it
        # was written to avoid is the same one.
        #
        # Hand-named, because the migration must spell it identically:
        # ``test_the_migrated_indexes_match_the_model_metadata`` compares index NAMES, and a
        # templated name here would leave the model declaring an index the chain never builds.
        #
        # The omissions around it are deliberate. A single-column index on ``status`` would be
        # redundant with this one's leading column — the "three unused read indexes shipped"
        # mistake revision 0012 had to reconcile — and ``described_at`` gets none at all: the
        # board filters on it, but only ever alongside a status equality this index already
        # narrows to a few hundred rows.
        sa.Index("ix_support_tickets_status_created_at_id", "status", "created_at", "id"),
        #
        # THE CARD LATCH, AND THE UNIQUENESS IS PER CHAT — NEVER OVER THE MESSAGE ID ALONE.
        # This is the correction a reviewer traced end to end, and the reason it is spelled out
        # here at length is that "one column would do" is the exact simplification that put the
        # bug in: a Telegram ``message_id`` is a PER-CHAT counter, not a global identifier.
        # Message 5 in the support group we use today and message 5 in the group we used last
        # month are two different messages that happen to share a number.
        #
        # What a global ``UNIQUE (group_message_id)`` actually broke: the support group is
        # moved — a new group, or Telegram auto-upgrading a basic group to a supergroup, which
        # CHANGES the chat id — and an operator repoints ``BAYRAM_SUPPORT_GROUP_CHAT_ID``. Old
        # rows still hold ``group_message_id`` 2, 5, 9… from the old chat. The next customer
        # describes a ticket, the card is posted successfully, Telegram returns ``message_id=5``
        # in the NEW chat, and ``claim_group_post``'s UPDATE trips the global unique index. The
        # commit raises ``IntegrityError``, ``run_guarded`` turns it into an ``Err``, and the
        # latch fails for a card that WAS posted — leaving the ticket permanently un-latched and
        # an orphan card in the group that nothing can ever edit or relay from. The database
        # refused a write that was entirely correct, because it was asked to enforce a global
        # uniqueness that Telegram never promised.
        #
        # ``(group_chat_id, group_message_id)`` is the uniqueness that was wanted all along, and
        # it is also the shape of the read: ``find_by_group_message`` resolves a staffer's reply
        # by chat AND message id, so this composite leads with the column that query filters on
        # first and serves it end to end. The single-column index it replaces is therefore not
        # merely narrowed, it is subsumed — there is no lookup anywhere that keys on
        # ``group_message_id`` without a chat id beside it, and if one is ever written it is
        # the lookup that is wrong.
        #
        # STILL NULL-TOLERANT, which is what keeps a failed group post survivable: both engines
        # treat NULLs as distinct in a unique index, and a composite is unique only when every
        # column is non-NULL, so any number of un-posted tickets — ``(NULL, NULL)`` — and any
        # number of half-claimed ones coexist. Do not "tighten" this with a partial index or a
        # NOT NULL: the un-posted row is the ordinary case (§3.3), not the exception.
        #
        # Hand-named for the same reason the board index is, and the name is deliberately the
        # one ``NAMING_CONVENTION``'s ``ix`` template would mint for these two columns, so a
        # later autogenerate diff is empty rather than a rename.
        sa.Index(
            "ix_support_tickets_group_chat_id_group_message_id",
            "group_chat_id",
            "group_message_id",
            unique=True,
        ),
    )

    id: Mapped[UUID] = mapped_column(sa.Uuid, primary_key=True, default=uuid4)
    #: The reference the customer is given and the staffer quotes back. UNIQUE because a
    #: reference that resolves to two tickets is worse than no reference at all: support would
    #: answer about the wrong complaint while believing they had looked it up. Indexed through
    #: that uniqueness — ``unique=True, index=True`` builds one unique index rather than a
    #: constraint and an index — because the panel's search box reads on exactly this column,
    #: the same shape ``payment_intents.public_ref`` takes.
    public_ref: Mapped[str] = mapped_column(
        sa.String(SUPPORT_PUBLIC_REF_LENGTH), nullable=False, unique=True, index=True
    )
    #: Whose complaint it is. NOT NULL and NOT nullable-for-erasure, which is the departure
    #: from ``broadcast_recipients`` and ``credit_ledger`` worth naming: those rows are erased
    #: by ANONYMISATION because the aggregate has to survive the person, whereas ``/forget``
    #: DELETEs a ticket outright — the customer's own words are the row, and an anonymised
    #: complaint is not a statistic, it is somebody's sentence with the name filed off.
    #: Indexed for the erasure ``DELETE``, which runs inside the transaction a customer's
    #: ``/forget`` is waiting on and must not scan, and for the per-account history second.
    telegram_user_id: Mapped[int] = mapped_column(sa.BigInteger, nullable=False, index=True)
    #: The locale the ticket was opened in. Stored rather than re-read from ``users`` because
    #: the relay has to answer in the language the customer complained in, and an account that
    #: switched language in the meantime would otherwise get a staff reply in a language they
    #: no longer read — on the one message where being understood is the entire point.
    language: Mapped[Language] = mapped_column(enum_type(Language), nullable=False)
    #: Which door they came through. Recorded, never branched on: both doors file the same
    #: kind of ticket into the same inbox. See :class:`bayram.contracts.SupportTicketSource`.
    source: Mapped[SupportTicketSource] = mapped_column(
        enum_type(SupportTicketSource), nullable=False
    )
    #: The song they are complaining about, set ONLY when the ticket was opened from the
    #: post-delivery keyboard — ``/support`` has no order in hand and leaves this NULL, which
    #: is half the rows and not a defect.
    #:
    #: ``ON DELETE SET NULL``, matching ``generation_attempts.order_id`` exactly: the ticket
    #: must outlive the order it was about, or a purge run would silently delete the support
    #: history of every complaint ever made about a deleted song. A cascade here would make
    #: retention on ``orders`` into an undeclared retention policy on complaints.
    order_id: Mapped[UUID | None] = mapped_column(
        sa.Uuid, sa.ForeignKey("orders.id", ondelete="SET NULL"), nullable=True, index=True
    )
    #: Which Kanban column it sits in. Defaulted to ``NEW`` in the mapper, which is the
    #: opposite call from ``broadcasts.state`` and for a stated reason: a campaign's state is
    #: set by whichever of eight transitions is running and a default would be the one place
    #: it was chosen by omission, whereas a ticket has exactly one birth state and it is
    #: written by the customer's tap. Every LATER move is still an explicit conditional
    #: ``UPDATE`` naming the status it expects and the status it writes.
    status: Mapped[SupportTicketStatus] = mapped_column(
        enum_type(SupportTicketStatus), nullable=False, default=SupportTicketStatus.NEW
    )
    #: What the customer actually said, in their own words, unedited. NULL until they answer
    #: the ForceReply prompt — see the module docstring on why that NULL is a real row.
    #:
    #: **This is the one free-text column in this schema that crosses to the admin panel in
    #: full**, against ``db/admin/views.py``'s standing ``*_chars``/``has_*`` rule. The
    #: argument is made where the view is built, not asserted here.
    body: Mapped[str | None] = mapped_column(sa.String(SUPPORT_BODY_LENGTH), nullable=True)
    #: The ``message_id`` of the ForceReply prompt this ticket is waiting on. The whole of the
    #: FSM-free flow turns on this column; see the module docstring. NULL once answered is NOT
    #: how it works — the value is left in place, because it is also the evidence of which
    #: prompt a late reply belongs to when a customer answers two of them out of order.
    prompt_message_id: Mapped[int | None] = mapped_column(sa.BigInteger, nullable=True)
    #: When :attr:`body` arrived. NULL means the customer tapped and never typed. The board
    #: filters on ``described_at IS NOT NULL``; the row is kept either way.
    described_at: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)

    # -- who has it ----------------------------------------------------------
    #: The operator or staffer who claimed it. Denormalised with no foreign key; see the
    #: module docstring. NULL means nobody has claimed it, which is exactly what the ``new``
    #: column of the board means and is stored separately because a ticket can be claimed
    #: without being moved and moved without being claimed.
    assigned_admin_username: Mapped[str | None] = mapped_column(
        sa.String(ACTOR_USERNAME_LENGTH), nullable=True
    )
    assigned_at: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)

    # -- the group card: a once-only latch, never a cache ---------------------
    #: Where the card was posted. NULL when the group is unconfigured (the feature is off and
    #: the ticket still works), or when Telegram refused and the post is still owed.
    #:
    #: It is the LEADING column of the card index, and not decoration: it is what makes
    #: ``group_message_id`` mean anything at all (a message id is per-chat), it is what
    #: ``find_by_group_message`` filters on first, and it is what keeps a card from the group
    #: we used last month from being matched by a reply in the group we use today.
    group_chat_id: Mapped[int | None] = mapped_column(sa.BigInteger, nullable=True)
    #: The card's own ``message_id``, and the ticket's half of the two-way reply: a staffer's
    #: message whose ``reply_to_message.message_id`` equals this, IN THIS CHAT, belongs to this
    #: ticket.
    #:
    #: **Deliberately carries no uniqueness or index of its own.** A ``message_id`` is a
    #: per-chat counter, so "no two tickets hold message 5" is a claim about Telegram that is
    #: simply false the moment the support group changes — and the row that pays for it is the
    #: ticket whose card posted fine and then failed to latch. The uniqueness lives on
    #: ``ix_support_tickets_group_chat_id_group_message_id`` in ``__table_args__``, over the
    #: PAIR, where the argument for it is written out in full. Re-adding ``unique=True`` here
    #: would restore exactly that bug.
    group_message_id: Mapped[int | None] = mapped_column(sa.BigInteger, nullable=True)
    #: When the card reached the group. Settled AFTER the Telegram call returns, so a row with
    #: a message id and no clock is a send that crashed mid-flight and is worth looking at.
    group_posted_at: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)

    #: When it reached ``resolved``. NOT cleared on a reopen: it records that this ticket was
    #: once considered finished, which is the single most useful thing to know about a ticket
    #: that came back, and a column that a reopen erased would make repeat complaints
    #: invisible — ``orders.delivered_at``'s rule, one domain along.
    resolved_at: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)
