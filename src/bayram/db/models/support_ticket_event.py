"""``support_ticket_events`` — append-only, because a support timeline nobody amends is the
only kind an operator can paste from.

A ticket has a status, and a status answers "where is this now?". It cannot answer the two
questions that actually come up months later: what did we tell this customer, and who decided
that? So the status lives on ``support_tickets`` and the history lives here — the split
``credit_accounts.balance`` and ``credit_ledger`` already make, and for the same reason. A
window function over an event table is not a board, and a column is not a record.

**APPEND-ONLY, WITH NO ``TimestampMixin``.** :attr:`SupportTicketEventRow.created_at` is the
one instant this row is about. An ``updated_at`` could never be true here, and offering one
would invite a writer to amend a record whose entire value is that nobody amends it —
``bot_membership_events`` and ``credit_ledger`` state it the same way. The one clock that does
move after insert is :attr:`relayed_at`, and it is not an amendment: see below.

**``NOTE`` AND ``REPLY`` ARE TWO KINDS AND NEVER ONE COLUMN WITH A FLAG.** An internal note is
something we said to each other; a reply is something the customer read. When a ticket is
re-opened six weeks later the only question that matters is which sentences they actually saw,
and a timeline that cannot separate the two is a timeline an operator has to guess at — which
in practice means quoting an internal note back to a customer. ``relayed_at`` is the proof for
the second kind: it is stamped when the message really reached the private chat, so a reply
written but never delivered (the customer blocked us, Telegram refused) is visibly different
from one that landed, instead of both reading as "we answered them".

**THREE AUTHOR COLUMNS, NOT ONE.** ``author_admin_username`` identifies an operator who has an
``admin_users`` row, a session and an ``admin_audit_log`` entry behind them;
``author_telegram_user_id`` identifies a customer or a group staffer, who have none of those;
``author_display_name`` is the staffer's ``@handle`` or first name, denormalised so the
timeline reads as prose rather than as a column of numbers. They are three columns because
:class:`bayram.contracts.SupportAuthorKind`'s members are authenticated by different things
entirely, and a single ``author`` string would let a row claim an audited actor for an act
nobody audited. ``author_display_name`` is denormalised for ``admin_audit_log``'s reason: a
staffer who changes their handle must not silently rewrite what the timeline says they said.

**DELIBERATELY NO CHECK CONSTRAINTS** tying ``author_kind`` to the column it populates, or
``from_status``/``to_status`` to ``STATUS_CHANGE``. Over-constraining a log loses rows, and a
lost row is a hole in the record of what a customer was told; ``vendor_usage`` makes the same
call about its ``error_code``/``is_success`` pairing, and ``bot_membership_events`` restates
it. The writer is one module, the invariants are asserted in its tests, and a refused ``INSERT``
here would drop the evidence rather than protect it.

**NO ``*_expires_at``, AND THE BODY IS KEPT INDEFINITELY**, exactly as on the parent table.
This table's erasure route is ``/forget``, which deletes a customer's tickets and — through
``ON DELETE CASCADE`` on :attr:`ticket_id` — their timeline with them. The written paragraph
naming both tables, revision ``0027`` and that route is in
``tests/test_db/test_privacy_constraints.py``; the cascade is what makes the route one
statement instead of two that can disagree.
"""

from __future__ import annotations

from datetime import datetime
from typing import Final
from uuid import UUID, uuid4

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from bayram.contracts import SupportAuthorKind, SupportTicketEventKind, SupportTicketStatus
from bayram.db.base import Base, UtcDateTime, enum_type, utc_now
from bayram.db.models.admin_audit import ACTOR_USERNAME_LENGTH
from bayram.db.models.support_ticket import SUPPORT_BODY_LENGTH

__all__ = ["SupportTicketEventRow", "SUPPORT_AUTHOR_DISPLAY_NAME_LENGTH"]

#: A Telegram ``@handle`` is at most 32 characters and a first name at most 64, so this is
#: the wider of the two and the bound is the real one rather than a guess. Bounded because it
#: is rendered in a timeline row, and a name that wraps a card is a card nobody skims.
SUPPORT_AUTHOR_DISPLAY_NAME_LENGTH: Final[int] = 64


class SupportTicketEventRow(Base):
    """One thing that happened to one ticket, written once and never rewritten.

    No ORM relationship back to :class:`~bayram.db.models.support_ticket.SupportTicketRow`,
    following every other model in this package: an implicit lazy load inside async
    SQLAlchemy surfaces as a confusing greenlet error at a random await point, so the read
    layer names its statements instead. If one is ever added it takes ``lazy="raise"``.
    """

    __tablename__ = "support_ticket_events"
    __table_args__ = (
        # THE ONLY READ ANYBODY PERFORMS: one ticket's timeline, oldest first —
        # ``WHERE ticket_id = :id ORDER BY created_at, id``. ``id`` is the third column for
        # ``ix_orders_state_created_at``'s reason: without it Postgres sorts the trailing term
        # at runtime, and two events written in one transaction share an instant exactly.
        #
        # Hand-named, because ``test_the_migrated_indexes_match_the_model_metadata`` compares
        # index NAMES and a templated name would leave the model declaring an index the chain
        # never builds.
        #
        # There is NO separate index on ``ticket_id`` and that is deliberate, not an omission:
        # this composite leads with it and already serves every lookup by ticket, including
        # the cascading delete's. ``broadcast_bodies`` declines an index on ``broadcast_id``
        # for exactly the same reason, and revision 0012 records what shipping the redundant
        # one costs. There is no index on ``created_at`` alone either — nothing reads this
        # table across tickets, and no sweep runs over it at all.
        sa.Index(
            "ix_support_ticket_events_ticket_id_created_at_id", "ticket_id", "created_at", "id"
        ),
    )

    id: Mapped[UUID] = mapped_column(sa.Uuid, primary_key=True, default=uuid4)
    #: The ticket this happened to. ``ON DELETE CASCADE``: an event is a PART of a ticket and
    #: is meaningless without it, so there is no state of the world in which one should
    #: survive the other — ``broadcast_bodies`` and ``broadcast_recipients`` take the same
    #: posture for the same reason. It is also what makes ``/forget`` one statement: deleting
    #: the customer's tickets takes their timeline with them, rather than leaving orphaned
    #: rows that still quote the customer's own words back.
    ticket_id: Mapped[UUID] = mapped_column(
        sa.Uuid, sa.ForeignKey("support_tickets.id", ondelete="CASCADE"), nullable=False
    )
    #: What happened. NOT NULL — an event with no kind is not a fact about anything.
    kind: Mapped[SupportTicketEventKind] = mapped_column(
        enum_type(SupportTicketEventKind), nullable=False
    )
    #: Which sort of actor did it. NOT NULL for the reason ``vendor_usage.cost_source`` is
    #: bound to its figure: a sentence whose author's provenance is unknown is a sentence a
    #: reader has to guess about, and here the guess decides whether a customer saw it.
    author_kind: Mapped[SupportAuthorKind] = mapped_column(
        enum_type(SupportAuthorKind), nullable=False
    )
    #: Set for ``OPERATOR``. Denormalised, no foreign key — ``admin_audit_log``'s rule: a
    #: rename must not rewrite history, and an operator who leaves must not take it with them.
    author_admin_username: Mapped[str | None] = mapped_column(
        sa.String(ACTOR_USERNAME_LENGTH), nullable=True
    )
    #: Set for ``CUSTOMER`` and ``STAFF_GROUP``. The customer's id is the same value the
    #: parent row carries; it is repeated here so a single event row is legible on its own.
    author_telegram_user_id: Mapped[int | None] = mapped_column(sa.BigInteger, nullable=True)
    #: The group staffer's ``@handle`` or first name, so the timeline reads as a conversation.
    #: NULL for ``SYSTEM`` and for a customer, whose name this schema deliberately does not
    #: hold on a ticket at all.
    author_display_name: Mapped[str | None] = mapped_column(
        sa.String(SUPPORT_AUTHOR_DISPLAY_NAME_LENGTH), nullable=True
    )

    #: Both ends of a move, set ONLY on ``STATUS_CHANGE`` and NULL on every other kind. Two
    #: columns rather than one, because "it went to ``waiting``" and "it went to ``waiting``
    #: from ``resolved``" are different events: the second is a reopened ticket, which is the
    #: one shape of this row anybody goes looking for.
    from_status: Mapped[SupportTicketStatus | None] = mapped_column(
        enum_type(SupportTicketStatus), nullable=True
    )
    to_status: Mapped[SupportTicketStatus | None] = mapped_column(
        enum_type(SupportTicketStatus), nullable=True
    )

    #: The note or the reply text. NULL on the kinds that carry no prose (``OPENED``,
    #: ``ASSIGNED``, ``GROUP_POSTED``, and a bare ``STATUS_CHANGE``). Bounded at the same
    #: ceiling as the ticket body, which is Telegram's own single-message limit and therefore
    #: the widest thing that can be typed into either end of this conversation.
    body: Mapped[str | None] = mapped_column(sa.String(SUPPORT_BODY_LENGTH), nullable=True)
    #: When a ``REPLY`` actually reached the customer's private chat — NULL until it did, and
    #: NULL for ever on one that never could. The one column on this append-only table that is
    #: written after insert, and it is not an amendment of the record: the row records that a
    #: reply was COMPOSED, this clock records that it was DELIVERED, and they are two events
    #: separated by a network call that fails often enough to be worth telling apart.
    relayed_at: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)

    #: When this happened. Declared by hand rather than taken from ``TimestampMixin`` — see
    #: the module docstring — and NOT indexed on its own: it is the second column of the one
    #: composite this table declares, and nothing reads the table across tickets.
    created_at: Mapped[datetime] = mapped_column(UtcDateTime, nullable=False, default=utc_now)
