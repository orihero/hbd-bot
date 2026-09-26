"""Wire models for ``/api/support/tickets`` — the queue, one ticket, and the four acts.

**This module is NOT re-exported from ``bayram.admin.schemas.__init__``, and that is a rule
rather than an omission.** That package re-exports only modules importing no web framework,
because ``test_the_worker_decodes_a_stored_segment_without_importing_a_web_framework`` runs in
a subprocess and fails if one appears. :class:`~bayram.admin.schemas.page.PageMeta` is imported
below for :class:`SupportTicketsPage`, and ``page.py`` pulls in ``fastapi``; adding a line for
this module to that ``__init__`` would take FastAPI into the worker through a door nobody
opened deliberately. ``schemas/broadcasts.py`` carries the identical restriction.

**Every column bound is restated here as a pydantic constraint, and the reason is where the
tests run.** ``tests/test_admin`` is on in-memory SQLite, which enforces neither CHECK
constraints nor ``VARCHAR`` lengths — it stores a 9 000-character body in a ``String(4096)``
column without complaint — so a bound that lives only in the schema is a bound this suite
cannot see and Postgres discovers in production, as an ``IntegrityError`` raised from inside a
transaction that has already written an event row and an audit row. Restated here it is a 422
naming the field, before anything opens. ``_checked_bodies`` in ``schemas/broadcasts.py`` is
the precedent and makes the same argument at length.

**The status grammar is restated here too, against the same table the writer consults.**
:func:`~bayram.support.is_legal_move` is the authority and ``bayram.db.support_tickets.move_status``
raises on an illegal move, which the envelope renders as 422 — so this validator changes no
status code. What it changes is *when*: a ``RESOLVED -> WAITING`` is refused before a session
is opened, before ``expectedStatus`` is compared to a row, and with the two statuses named in
the message. The duplication is the one ``schemas/page.py`` defends explicitly — "the bounds
are declared twice on purpose and the duplication is not a smell" — and here it is cheaper
than there, because both copies read the SAME ``LEGAL_STATUS_MOVES`` mapping and cannot drift.

**The four request bodies do NOT inherit :class:`~bayram.admin.schemas.actions.ReasonedRequest`,
which is a departure from every other operator action in this API and is argued rather than
assumed.** §12.4's rule is that every *destructive* action requires a reason code, and the
actions it was written for delete a record, disclose a customer's name, bar an account or
mint spendable credit. None of these four is any of those: moving a ticket between columns,
claiming it, writing an internal note and answering the person who wrote to us are the
ordinary work of the queue, performed dozens of times a shift by the role the queue exists
for. A mandatory ``reasonCode`` on each would be answered with the same member every time —
which is the accountability control switching itself off while continuing to look enabled, and
it would make :class:`~bayram.db.enums.AuditReasonCode`'s modal value meaningless for every
*other* action that shares the column. What carries the accountability instead is stronger
than a code an operator picks from a list: every one of the four writes an
``admin_audit_log`` row naming the actor, their role, their IP and the ticket, AND an
append-only ``support_ticket_events`` row that the customer-facing timeline renders. The
audit row's reason is :data:`~bayram.admin.routers.support.SUPPORT_REASON`, stamped by the
server, which is the honest answer: this was support work.

**The customer's Telegram id is published in the clear beside its mask**, exactly as
:class:`~bayram.admin.schemas.users.UserView` publishes it and pointedly unlike
``BroadcastRecipientView``, which carries the mask alone. The distinction those two draw is
whether the list is a *membership decision about people* that can be paged through in bulk —
"these are the accounts we classed as lapsed" — or a set of records each keyed by that id. A
campaign's recipient ledger is the first; the support queue is the second, and it is the
second twice over: every ``/users/**`` route keys on the raw id, and the first thing an
operator does with a complaint is open the customer's order history to answer it. A mask the
SPA cannot dereference would make the ticket detail a dead end at exactly that moment. The
customer's NAME is not here and cannot be: a ticket holds no name column at all.

**The ticket body and the event bodies cross in full.** That exception is argued where the
data is shaped — :class:`~bayram.db.admin.views.SupportTicketListItem` — and not restated
here; what this module must not do is quietly widen it. Nothing else on a ticket is free text.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Final
from uuid import UUID

from pydantic import Field, field_validator, model_validator

from bayram.admin.schemas.admins import ADMIN_USERNAME_PATTERN
from bayram.admin.schemas.common import ApiModel
from bayram.admin.schemas.page import PageMeta
from bayram.admin.serializers.redaction import mask_telegram_user_id
from bayram.contracts import (
    Language,
    SupportAuthorKind,
    SupportTicketEventKind,
    SupportTicketSource,
    SupportTicketStatus,
)
from bayram.db.admin.views import (
    SupportTicketColumnTotal,
    SupportTicketDetail,
    SupportTicketEventItem,
    SupportTicketListItem,
)
from bayram.db.models.admin_audit import ACTOR_USERNAME_LENGTH
from bayram.db.models.support_ticket import SUPPORT_BODY_LENGTH, SUPPORT_PUBLIC_REF_LENGTH
from bayram.db.models.support_ticket_event import SUPPORT_AUTHOR_DISPLAY_NAME_LENGTH
from bayram.support import is_legal_move, legal_moves_from

__all__ = [
    "MAX_TICKET_BODY_CHARS",
    "MAX_ASSIGNEE_CHARS",
    "TicketAssignRequest",
    "TicketNoteRequest",
    "TicketReplyRequest",
    "TicketStatusRequest",
    "SupportTicketView",
    "SupportTicketsPage",
    "SupportTicketEventView",
    "SupportTicketDetailView",
    "SupportBoardColumnView",
    "SupportBoardView",
    "ordered_transitions",
    "to_board_view",
    "to_ticket_view",
    "to_event_view",
    "to_ticket_detail_view",
]

#: What an operator may write in a note or a reply, and it is the COLUMN's bound rather than
#: a number chosen here: ``support_ticket_events.body`` is ``String(4096)``. It happens to be
#: Telegram's own single-message ceiling as well, which is not a coincidence — the column was
#: sized so that a reply this API accepts is a message Telegram will carry, and the two bounds
#: being one number is what stops a 4 096-character reply being stored and then refused at
#: send time with nobody to tell.
#:
#: Unlike ``schemas/broadcasts.py`` there is no second, RENDERED length to check. A broadcast
#: body is authored as Telegram HTML, so an ampersand costs one character in the editor and
#: five on the wire; a ticket reply is plain text that the worker escapes on the way out, so
#: the operator's count and Telegram's are the same count.
MAX_TICKET_BODY_CHARS: Final[int] = SUPPORT_BODY_LENGTH

#: ``support_tickets.assigned_admin_username`` is ``String(ACTOR_USERNAME_LENGTH)``, which is
#: the same 64 ``admin_audit_log.actor_username`` and ``admin_users.username`` use. Named here
#: rather than used inline so the constraint below reads as the column's and not as a guess.
MAX_ASSIGNEE_CHARS: Final[int] = ACTOR_USERNAME_LENGTH

_BLANK_BODY: Final[str] = "a note or a reply cannot be blank"
_ILLEGAL_MOVE: Final[str] = "a ticket in that status cannot be moved to that one"


def ordered_transitions(status: SupportTicketStatus) -> tuple[SupportTicketStatus, ...]:
    """Every column this ticket may move to, in the board's own left-to-right order.

    :func:`~bayram.support.legal_moves_from` answers with a ``frozenset``, whose iteration
    order is a hash artefact — publishing it raw would give the SPA a button row that reorders
    itself between two renders of the same ticket, and would make a response body that is
    byte-comparable in a test only by accident. Declaration order is the order the Kanban
    columns are drawn in, so the buttons read ``In progress · Waiting · Resolved`` and never
    ``Resolved · In progress · Waiting``.
    """
    allowed = legal_moves_from(status)
    return tuple(candidate for candidate in SupportTicketStatus if candidate in allowed)


# ---------------------------------------------------------------------------
# requests
# ---------------------------------------------------------------------------
class TicketStatusRequest(ApiModel):
    """Move one ticket between columns. Carries BOTH ends of the move, which is the point.

    ``expectedStatus`` is not a convenience and is not optional. ``move_status``' ``UPDATE``
    names it in its ``WHERE`` clause and the rowcount is the lock, so this field is what turns
    two operators dragging the same card at once into one move and one refusal instead of two
    moves and a timeline that contradicts itself. The SPA sends the status it DREW the card
    in; if the row has moved since, the handler answers 409 and the board re-reads. A request
    that omitted it would be "set this ticket to resolved whatever it says now", which is the
    lost-update every conditional write in ``bayram.db.support_tickets`` exists to refuse.

    There is no ``reasonCode`` — see the module docstring for the argument, which is the one
    departure this namespace takes from §12.4.
    """

    expected_status: SupportTicketStatus
    to_status: SupportTicketStatus

    @model_validator(mode="after")
    def _is_a_legal_move(self) -> TicketStatusRequest:
        """The board's grammar, refused here as well as in the writer.

        Both copies read :data:`~bayram.support.LEGAL_STATUS_MOVES`, so they cannot disagree;
        what this one buys is a 422 before a transaction opens and before a row is read. It
        also catches the two shapes a client most easily sends by accident: a move to the
        status the ticket is already in — nothing moves to itself, so a second ``✋ Claim``
        press is a refusal rather than a duplicate event — and a return to ``NEW``, which the
        grammar forbids from everywhere because a ticket somebody has touched is not new.
        """
        if not is_legal_move(self.expected_status, self.to_status):
            raise ValueError(_ILLEGAL_MOVE)
        return self


class TicketNoteRequest(ApiModel):
    """An internal line on the timeline. **The customer never sees this.**

    Its own request model rather than a shared body with :class:`TicketReplyRequest`, whose
    single field is identical, and the duplication is deliberate: the two differ in the one
    way that matters — whether the words reach a person — and one model behind two routes is
    one refactor away from one route behind one model. The audit taxonomy keeps them apart for
    the same reason (``ticket.note`` and ``ticket.reply``), and so does
    :class:`~bayram.contracts.SupportTicketEventKind`.
    """

    body: Annotated[str, Field(min_length=1, max_length=MAX_TICKET_BODY_CHARS)]

    @field_validator("body")
    @classmethod
    def _is_not_blank(cls, body: str) -> str:
        return _checked_body(body)


class TicketReplyRequest(ApiModel):
    """What to say to the customer. **These words are put in somebody's phone.**

    Bounded by :data:`MAX_TICKET_BODY_CHARS`, which is both the column's length and Telegram's
    single-message ceiling — see that constant. Nothing here is escaped, trimmed or
    canonicalised: the worker escapes on the way out, where the escaping belongs, and an
    operator's reply is stored as the artefact they wrote, exactly as ``BroadcastBodyInput``
    stores a campaign body verbatim.

    No ``reasonCode``, and this is the field of the four where its absence deserves the most
    thought: a reply is the only one of them that leaves the building. The module docstring
    makes the case; the short version is that ONE message to ONE person who asked us a
    question is not the act §12.4 was written about, and the ``ticket.reply`` audit row plus
    the append-only event carry more than a picked-from-a-list code would.
    """

    body: Annotated[str, Field(min_length=1, max_length=MAX_TICKET_BODY_CHARS)]

    @field_validator("body")
    @classmethod
    def _is_not_blank(cls, body: str) -> str:
        return _checked_body(body)


class TicketAssignRequest(ApiModel):
    """Hand the ticket to an operator — possibly oneself, possibly somebody else.

    ``adminUsername`` is a field and not "whoever is calling", because handing a ticket over
    is the normal case and a route that could only claim would need a second route to assign.
    ``bayram.db.support_tickets.assign`` is unconditional on the current holder for the same
    reason: a reassignment must not be refused because somebody claimed it first, and the
    append-only event is what keeps the history of who has had it.

    The username is **not** checked against ``admin_users`` here and deliberately not at the
    handler either. ``support_tickets.assigned_admin_username`` is denormalised with no foreign
    key — the same posture ``admin_audit_log.actor_username`` takes — precisely so that a
    deactivated or renamed operator does not rewrite who worked a queue; a validity check at
    write time would be a rule the column does not keep and could not keep tomorrow. What IS
    checked is the shape: the column's length, and the same pattern
    ``POST /api/admins`` accepts, so a value that could never name an operator is a 422
    rather than a row that quietly means nothing.
    """

    admin_username: Annotated[
        str,
        Field(min_length=1, max_length=MAX_ASSIGNEE_CHARS, pattern=ADMIN_USERNAME_PATTERN),
    ]


def _checked_body(body: str) -> str:
    """Refuse text that is only whitespace. Never trims — what is stored is what was typed.

    ``min_length=1`` alone accepts a single space, which reaches the customer as an empty
    message bubble or, on some clients, as a ``TelegramBadRequest`` the operator never sees.
    """
    if not body.strip():
        raise ValueError(_BLANK_BODY)
    return body


# ---------------------------------------------------------------------------
# responses
# ---------------------------------------------------------------------------
class SupportTicketView(ApiModel):
    """One ticket, as a queue row and as a board card. The same shape serves both.

    Two projections were the alternative — a thin card and a fat row — and it was rejected for
    the reason the board and the list already share ``TicketFilters``: they describe ONE
    population, and two shapes over it is two places for "what does a card show?" to be
    answered differently. The card renders a subset of these fields; nothing here is expensive
    enough to justify a second query shape to avoid sending it.
    """

    id: UUID
    #: The short reference the customer was given, quoted back on the phone and matched by
    #: ``?q=``. Bounded by the column at :data:`SUPPORT_PUBLIC_REF_LENGTH`; there is no
    #: validator because nothing accepts one on the way IN — it is minted, never supplied.
    public_ref: Annotated[str, Field(max_length=SUPPORT_PUBLIC_REF_LENGTH)]
    #: Raw AND masked, the way ``UserView`` publishes them. See the module docstring for why
    #: this namespace follows ``/users`` rather than ``BroadcastRecipientView``.
    telegram_user_id: int
    telegram_user_id_masked: str
    #: The locale the ticket was OPENED in, which is the language the reply must be written
    #: in — not the account's language today.
    language: Language
    source: SupportTicketSource
    #: ``None`` for every ``/support`` ticket. The panel links to the order when it is there.
    order_id: UUID | None
    status: SupportTicketStatus
    #: **Published in full**, and the exception is argued on
    #: :class:`~bayram.db.admin.views.SupportTicketListItem` rather than restated here.
    #: ``None`` is not a redaction: it is a customer who tapped ⚠️ and never typed.
    body: str | None
    described_at: datetime | None
    #: Where this ticket may go next, from the server's own grammar rather than from a copy
    #: in TypeScript. Publishing it is the same decision ``GET /api/segments/fields`` takes:
    #: the SPA renders exactly the moves it will not be refused for, instead of offering four
    #: buttons and discovering which three are guaranteed 422s. Empty for a status with
    #: nowhere to go, which the panel renders as a card with no actions rather than as an
    #: error. Ordered by :func:`ordered_transitions`; never a set.
    allowed_transitions: tuple[SupportTicketStatus, ...]
    #: Denormalised, no foreign key. ``None`` is unclaimed — the first column an operator
    #: filters on when they want their own queue.
    assigned_admin_username: str | None
    assigned_at: datetime | None
    #: Whether the card reached the support group. The chat and message ids are deliberately
    #: absent: the admin process is structurally forbidden from talking to Telegram
    #: (``ADMIN_PANEL_PLAN D10 / §4.2``), so they are a routing detail this API has no use for
    #: and publishing them would invite a future screen to try. ``False`` beside a described
    #: body means the post is still owed, never that it was lost.
    is_posted_to_group: bool
    group_posted_at: datetime | None
    #: Stamped on the way into ``resolved`` and never cleared by a reopen. A ticket with a
    #: ``resolvedAt`` and a non-resolved status is a ticket that came back, which is the most
    #: useful thing this row can say.
    resolved_at: datetime | None
    #: How many timeline rows exist. What tells an operator at a glance which tickets have
    #: been talked about and which have had nothing said.
    event_count: int
    created_at: datetime
    #: Last move of any kind — the column a "nothing has happened here for four days" filter
    #: reads.
    updated_at: datetime


class SupportTicketsPage(ApiModel):
    """One keyset page of the queue, newest first."""

    items: list[SupportTicketView]
    meta: PageMeta


class SupportTicketEventView(ApiModel):
    """One thing that happened to one ticket — a row of the append-only timeline.

    The three author columns travel separately rather than flattened into one ``author``
    string, exactly as the table stores them and for the reason the view model states: an
    ``authorAdminUsername`` is an actor with an ``admin_users`` row, a session and an audit
    entry behind them, while a Telegram id is somebody whose only credential is membership of
    a chat. One string would let a row claim an audited actor for an act nobody audited.
    """

    id: UUID
    ticket_id: UUID
    kind: SupportTicketEventKind
    author_kind: SupportAuthorKind
    #: Set for ``operator``. Denormalised; a rename must not rewrite history.
    author_admin_username: str | None
    #: Set for ``customer`` and ``staff_group``. **Masked and never raw**, which is the one
    #: place this namespace departs from :class:`SupportTicketView` above. The reporter's id
    #: is published in the clear because the panel navigates to their record; the author of a
    #: timeline line is a staffer in a Telegram group or the customer already named on the
    #: ticket, and neither is a record this API can route to — so there is nothing for the
    #: raw value to buy and it stays out of the bytes.
    author_telegram_user_id_masked: str | None
    #: The staffer's ``@handle`` or first name, so the timeline reads as prose rather than as
    #: a column of numbers. Bounded by the column at
    #: :data:`SUPPORT_AUTHOR_DISPLAY_NAME_LENGTH`. Written by the bot, never accepted here.
    author_display_name: Annotated[
        str | None, Field(default=None, max_length=SUPPORT_AUTHOR_DISPLAY_NAME_LENGTH)
    ] = None
    #: Both ends of a move, set only on ``status_change``. Two fields and not one: "it went to
    #: waiting" and "it went to waiting FROM resolved" are different events, and the second is
    #: a reopened ticket.
    from_status: SupportTicketStatus | None = None
    to_status: SupportTicketStatus | None = None
    #: A note or a reply; ``None`` on the kinds that carry no prose.
    body: str | None = None
    #: **Published because its absence is the point.** A ``reply`` row with no relay clock is
    #: a sentence that was composed and never reached anybody — the customer blocked the bot,
    #: or the relay job was refused by a deployment with no worker. An operator who cannot see
    #: the difference reads the timeline as "we answered them" when nothing landed, which is
    #: the single worst mistake available on this screen.
    relayed_at: datetime | None = None
    created_at: datetime


class SupportTicketDetailView(ApiModel):
    """One ticket and its whole timeline. The response every mutation here answers with.

    **Unpaged, and oldest first.** Both are departures from this API's defaults and both are
    the view model's decisions rather than this module's: a ticket is a conversation between
    one customer and a handful of staff, so its event count is tens at the very worst, and a
    conversation is read forwards. :class:`~bayram.db.admin.views.SupportTicketDetail` argues
    each at length.
    """

    ticket: SupportTicketView
    events: list[SupportTicketEventView]


class SupportBoardColumnView(ApiModel):
    """One Kanban column and how many described tickets are in it."""

    status: SupportTicketStatus
    count: int


class SupportBoardView(ApiModel):
    """The board's four column lengths — always four, always in the same order.

    A wrapper object rather than a bare JSON array, because a top-level array is a response
    shape nothing can be added to later without breaking every client that indexed it, and the
    board is the screen most likely to want a second number beside its columns (an oldest-
    unanswered age, an unassigned count). Every other collection in this API is an object for
    the same reason; this one has no ``meta`` because it is not paged and must never be —
    ``ticket_board`` returns the whole distribution by construction.
    """

    columns: list[SupportBoardColumnView]


# ---------------------------------------------------------------------------
# record -> wire. Pure, and the only place a ticket becomes bytes.
# ---------------------------------------------------------------------------
def to_ticket_view(item: SupportTicketListItem) -> SupportTicketView:
    """One queue row on the wire, with the mask computed here and the id carried beside it.

    :attr:`SupportTicketView.allowed_transitions` is derived from the status rather than
    stored: the grammar is code, it has no per-ticket state, and a column holding it would be
    a cached copy that goes stale the moment ``LEGAL_STATUS_MOVES`` changes.
    """
    return SupportTicketView(
        id=item.id,
        public_ref=item.public_ref,
        telegram_user_id=item.telegram_user_id,
        telegram_user_id_masked=mask_telegram_user_id(item.telegram_user_id),
        language=item.language,
        source=item.source,
        order_id=item.order_id,
        status=item.status,
        body=item.body,
        described_at=item.described_at,
        allowed_transitions=ordered_transitions(item.status),
        assigned_admin_username=item.assigned_admin_username,
        assigned_at=item.assigned_at,
        is_posted_to_group=item.is_posted_to_group,
        group_posted_at=item.group_posted_at,
        resolved_at=item.resolved_at,
        event_count=item.event_count,
        created_at=item.created_at,
        updated_at=item.updated_at,
    )


def to_event_view(item: SupportTicketEventItem) -> SupportTicketEventView:
    """One timeline row on the wire. The author's Telegram id is masked and never echoed raw."""
    return SupportTicketEventView(
        id=item.id,
        ticket_id=item.ticket_id,
        kind=item.kind,
        author_kind=item.author_kind,
        author_admin_username=item.author_admin_username,
        author_telegram_user_id_masked=(
            None
            if item.author_telegram_user_id is None
            else mask_telegram_user_id(item.author_telegram_user_id)
        ),
        author_display_name=item.author_display_name,
        from_status=item.from_status,
        to_status=item.to_status,
        body=item.body,
        relayed_at=item.relayed_at,
        created_at=item.created_at,
    )


def to_ticket_detail_view(detail: SupportTicketDetail) -> SupportTicketDetailView:
    """The ticket and its timeline, in the order the reader reads them."""
    return SupportTicketDetailView(
        ticket=to_ticket_view(detail.ticket),
        events=[to_event_view(event) for event in detail.events],
    )


def to_board_view(columns: tuple[SupportTicketColumnTotal, ...]) -> SupportBoardView:
    """The four columns, in the order ``ticket_board`` returned them.

    Not re-sorted and not zero-filled here: both are guaranteed by ``ticket_board``, which
    walks :class:`~bayram.contracts.SupportTicketStatus` in declaration order and reports every
    member including the empty ones. Re-doing either here would be a second implementation of
    a promise that already has one, and the two would eventually disagree about a status added
    later.
    """
    return SupportBoardView(
        columns=[
            SupportBoardColumnView(status=column.status, count=column.count) for column in columns
        ]
    )
