"""``/support/tickets`` — the queue an operator works, and the four things they do to a ticket.

**This is the only namespace in the panel whose subject is a conversation.** Every other
record here describes something that happened to the business — an order, a payment, a
campaign — and is read after the fact. A ticket is a person waiting for an answer, and it
exists simultaneously in two places this process cannot reconcile on its own: a row it owns,
and a card in a Telegram support group that only the worker can touch. The shape of this
module follows from that split rather than from REST tidiness.

**Two routers, two cells, and neither carries a step-up.** :func:`build_support_router` takes
``SUPPORT_READ`` — ``M`` at all four roles, because the queue is what the panel exists to
show. :func:`build_support_actions_router` takes ``SUPPORT_WRITE``, which is ``W`` at SUPPORT,
ADMIN and OWNER and is the only write cell in the matrix that starts at SUPPORT. There is no
ROLE-half/step-up split here, unlike ``/users/{id}/block``, ``/credits/grant``, ``/broadcasts``
and ``POST /admins`` — because there is no step-up to split off. ``Permission.SUPPORT_WRITE``
argues why replying is counted as an ordinary write rather than as a
``BROADCAST_SEND``-shaped one; the mechanical consequence is the good one, that both
permissions are safe as router guards and no handler in this file enforces authorisation.

**Nothing here talks to Telegram, and nothing here can.** The admin process is denied a bot
token (``ADMIN_PANEL_PLAN D10 / §4.2``), so every route below that must change what a customer
or a staffer SEES writes its rows and then enqueues an ARQ job through
:mod:`bayram.admin.queue` — a Redis write and nothing more. The enqueue is the last statement
of each handler, after the ticket row, its timeline event and its audit row are **committed**
— see the next paragraph, which is where that word is load-bearing.

**COMMIT, THEN ENQUEUE — and the order is the whole of what makes these two jobs work.** This
paragraph used to read "the enqueue is the last statement, after the rows are in the request's
transaction", and *in* the transaction is exactly the problem: :func:`bayram.admin.deps.
get_db_session` commits on a clean exit of the REQUEST, which is ten to thirty milliseconds
after the last statement of a handler — a ``_reload``, a projection, a response serialisation.
ARQ polls Redis every ``poll_delay`` (half a second by default), so a worker wins that window a
few percent of the time, opens its OWN session, and under READ COMMITTED sees a ``reply`` event
row that does not exist and a ticket still in its pre-move status. A relay job that finds no
event row has nothing to send; a card sync that reads the pre-move row repaints the card with
the status the operator has just moved away from and then swallows Telegram's "message is not
modified", freezing the card there. Both were invisible: the panel looked right, the job
"succeeded", and nobody was told. So every handler below finishes its reads, builds its
answer, calls :func:`_committed`, and enqueues after that. It is
``bayram.payme.service._perform``'s "one commit, then the notification" and
``broadcast_job``'s "claim, commit, then send", taken a third time — and it is what
:mod:`bayram.admin.queue` already claimed in prose ("the row and its audit entry are committed
before this is called") before any handler here actually did it.

**The enqueue is still ``unwrap``ed, but it no longer rolls the action back — that is the
price of the ordering and it is worth stating plainly.** SUPERSEDES the earlier position, which
was that a dead worker must refuse the whole request so the board and the group card could
never disagree. Both cannot be had: an enqueue that can undo the write must happen before the
commit, and an enqueue that happens before the commit is the race above. The race destroys a
customer's answer silently; a refused enqueue leaves an action committed and TELLS the operator
so, with a 503 from :class:`~bayram.errors.StorageError` — an unavailable dependency, not a
malformed request. What is left behind is visible in both cases and that is why this is the
tolerable half: a move whose card sync was never queued is a board that is right and a card one
status behind, repainted by the next action on that ticket; a reply whose relay was never
queued is a ``REPLY`` row with ``relayedAt`` null, which the timeline renders as
composed-and-not-delivered — the one state
:class:`~bayram.admin.schemas.tickets.SupportTicketEventView` exists to publish. The operator
who saw the 503 knows which it is. Do NOT "restore" the rollback by moving an enqueue above
:func:`_committed`; that is the bug, not the tidy-up.

**Three of the four actions enqueue, and the fourth deliberately does not.** A note changes no
rendered state and reaches nobody, so a card sync for it would be a Redis write, a
deploy-replayed coroutine and an edit to a Telegram message whose text is identical. A reply
enqueues the relay and NOT a card sync, for the same reason in the other direction: the card
renders the ticket's status and claim row, and answering a customer changes neither.

**A panel reply does not move the ticket.** In the support GROUP a reply to the card moves a
``new`` ticket to ``in_progress`` — "the reply is the claim" — because a staffer in a chat has
no other control to press. An operator in the panel has the column controls in front of them,
and an implicit move here would write a ``status_change`` event nobody asked for and race the
explicit one the operator is about to make. Stated rather than left as an inconsistency to be
discovered: the two surfaces differ because one of them has buttons.

**The board GET must not record that it was viewed.**
``tests/test_admin/test_routes_enumeration.py`` snapshots every domain table around every GET
this application serves and asserts nothing changed. Every function in
:mod:`bayram.db.admin.support_tickets` is a ``sa.select``; nothing in this module's read
router writes, and nothing in it may ever start to.

``routers/broadcasts.py`` is the style this file copies. ``routers/chats.py`` deliberately is
not.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Final
from uuid import UUID

from fastapi import APIRouter, Depends, Query

from bayram.admin import audit_sink
from bayram.admin.deps import API_PREFIX, Admin, Container, CurrentAdmin, Db, require_permission
from bayram.admin.errors import AdminErrorCode, AdminProblem, ProblemError, problem, unwrap
from bayram.admin.schemas.page import Paging, page_meta
from bayram.admin.schemas.tickets import (
    SupportBoardView,
    SupportTicketDetailView,
    SupportTicketsPage,
    TicketAssignRequest,
    TicketNoteRequest,
    TicketReplyRequest,
    TicketStatusRequest,
    to_board_view,
    to_ticket_detail_view,
    to_ticket_view,
)
from bayram.admin.security.permissions import Permission
from bayram.admin.window import resolve_window
from bayram.contracts import (
    Language,
    SupportTicketEventKind,
    SupportTicketSource,
    SupportTicketStatus,
)
from bayram.db.admin.audit import AuditEntry
from bayram.db.admin.sql import MAX_SEARCH_CHARS, TimeWindow
from bayram.db.admin.support_tickets import (
    TicketFilters,
    count_tickets,
    get_ticket,
    list_tickets,
    ticket_board,
)
from bayram.db.admin.views import SupportTicketDetail
from bayram.db.base import utc_now
from bayram.db.enums import AuditAction, AuditReasonCode
from bayram.db.models.admin_audit import ACTOR_USERNAME_LENGTH, AuditOutcome
from bayram.db.support_tickets import append_event, assign, move_status
from bayram.errors import ErrorCode, StorageError
from bayram.support import EventAuthor

__all__ = [
    "SUPPORT_TICKETS_PATH",
    "SUPPORT_BOARD_PATH",
    "SUPPORT_TICKET_PATH",
    "SUPPORT_TICKET_STATUS_PATH",
    "SUPPORT_TICKET_NOTES_PATH",
    "SUPPORT_TICKET_REPLY_PATH",
    "SUPPORT_TICKET_ASSIGN_PATH",
    "TICKET_SUBJECT_TYPE",
    "SUPPORT_REASON",
    "build_ticket_query",
    "build_support_router",
    "build_support_actions_router",
]

SUPPORT_TICKETS_PATH: Final[str] = f"{API_PREFIX}/support/tickets"

#: **Declared and mounted BEFORE :data:`SUPPORT_TICKET_PATH`, and here the ordering really is
#: load-bearing.** ``/board`` and ``{ticket_id}`` are both a single segment under
#: ``/support/tickets``, so whichever is registered first wins — and if the parameterised one
#: wins, an operator opening their board gets FastAPI's 422 about a malformed UUID instead of
#: their columns. ``ORDER_STATE_COUNTS_PATH`` carries this warning verbatim one namespace
#: along; ``BROADCAST_PATH``'s note is the opposite case (two segments to one, so order is
#: free) and the difference is why both are written down rather than assumed.
SUPPORT_BOARD_PATH: Final[str] = f"{SUPPORT_TICKETS_PATH}/board"
#: One identifier name for the whole namespace, typed ``UUID`` on every route below, so a
#: malformed id is FastAPI's 422 rather than a query that runs.
#: ``test_no_namespace_mixes_identifier_names`` is what keeps a second spelling out.
SUPPORT_TICKET_PATH: Final[str] = f"{SUPPORT_TICKETS_PATH}/{{ticket_id}}"
SUPPORT_TICKET_STATUS_PATH: Final[str] = f"{SUPPORT_TICKET_PATH}/status"
#: Plural, unlike the three verbs beside it, because it is a collection an operator appends
#: to rather than a property they set. The timeline is the resource; this is a POST onto it.
SUPPORT_TICKET_NOTES_PATH: Final[str] = f"{SUPPORT_TICKET_PATH}/notes"
SUPPORT_TICKET_REPLY_PATH: Final[str] = f"{SUPPORT_TICKET_PATH}/reply"
SUPPORT_TICKET_ASSIGN_PATH: Final[str] = f"{SUPPORT_TICKET_PATH}/assign"

#: ``admin_audit_log.subject_type`` for every row this module writes. Spelled once here and
#: imported by anything that later audits a ticket — the ``BROADCAST_SUBJECT_TYPE`` precedent
#: — because a second literal is a second way for one ticket's rows to end up under two
#: subjects. It is a member of the CLOSED ``bayram.db.admin.audit.SUBJECT_TYPES`` frozenset; a
#: value outside it raises ``AuditValueRejectedError`` inside ``append``, which ``audit_sink``
#: SWALLOWS and retries with ``subject_id=None`` — a 200 carrying a row that lost its subject.
TICKET_SUBJECT_TYPE: Final[str] = "ticket"

#: The reason every row this module writes carries, stamped by the server rather than asked
#: for. :class:`~bayram.db.admin.audit.AuditEntry` requires a reason code — deliberately,
#: because a row that could omit it is a row somebody omits it on — and none of the four
#: actions here takes a :class:`~bayram.admin.schemas.actions.ReasonedRequest`;
#: ``schemas/tickets.py`` argues why at length. ``SUPPORT_INVESTIGATION`` and not
#: ``ROUTINE_OPS``: this IS the support desk doing the thing the code is named for, and
#: filtering the audit log on it should return support work rather than the bucket everything
#: without a better home falls into.
SUPPORT_REASON: Final[AuditReasonCode] = AuditReasonCode.SUPPORT_INVESTIGATION

WithTotal = Annotated[bool, Query(alias="withTotal")]


def _no_such_ticket() -> ProblemError:
    """404 without echoing the id. An identifier is not a hint worth confirming."""
    return ProblemError(AdminProblem(code=ErrorCode.NOT_FOUND, message="no ticket with that id"))


def _window(since: datetime | None, until: datetime | None) -> TimeWindow | None:
    """``from``/``to`` as one half-open interval over ``support_tickets.created_at``.

    ``created_at`` and never ``described_at``: a window on a nullable column silently drops
    every tapped-and-never-typed ticket out of a range the operator believes covers
    everything, which is exactly the population somebody opens a date filter to measure.
    :class:`~bayram.db.admin.support_tickets.TicketFilters` states the same rule beside the field.
    """
    return resolve_window(since, until, now=utc_now())


def build_ticket_query(
    status: Annotated[list[SupportTicketStatus] | None, Query()] = None,
    source: Annotated[list[SupportTicketSource] | None, Query()] = None,
    language: Annotated[list[Language] | None, Query()] = None,
    assigned_to: Annotated[
        str | None, Query(alias="assignedTo", max_length=ACTOR_USERNAME_LENGTH)
    ] = None,
    telegram_user_id: Annotated[int | None, Query(alias="telegramUserId")] = None,
    since: Annotated[datetime | None, Query(alias="from")] = None,
    until: Annotated[datetime | None, Query(alias="to")] = None,
    search: Annotated[str | None, Query(alias="q", max_length=MAX_SEARCH_CHARS)] = None,
    only_described: Annotated[bool, Query(alias="onlyDescribed")] = False,
) -> TicketFilters:
    """The queue's filters, as a dependency so both handlers stay a straight line.

    Repeated ``status``, ``source`` and ``language`` are OR within the field and AND across
    fields, and each is typed as its enum so an unknown value is a 422 from FastAPI rather
    than a filter that quietly matches nothing.

    ``assignedTo`` is an EXACT match and is deliberately not folded into ``q``. "Show me
    Dilnoza's tickets" and "find the ticket mentioning Dilnoza" are two questions, and a
    substring search that answered both would put every ticket whose body names an operator
    into that operator's queue.

    ``q`` matches the public reference AND the body — the one search in this API that reaches
    a customer's own words, and it is allowed to because the same rows publish those words in
    full on the response it returns. :data:`~bayram.db.admin.support_tickets._SEARCHABLE_COLUMNS`
    is the authority on the pair.

    ``onlyDescribed`` defaults to ``False`` so the QUEUE shows everything, including the
    tickets nobody described — those rows are real data and the place abandonment is visible.
    :func:`~bayram.db.admin.support_tickets.ticket_board` forces it on regardless, because a
    board column counting rows with nothing in them to read is a queue length that lies.
    """
    return TicketFilters(
        statuses=tuple(status or ()),
        sources=tuple(source or ()),
        languages=tuple(language or ()),
        assigned_admin_username=assigned_to,
        telegram_user_id=telegram_user_id,
        window=_window(since, until),
        search=search,
        only_described=only_described,
    )


Filters = Annotated[TicketFilters, Depends(build_ticket_query)]


def build_support_router() -> APIRouter:
    """The queue an operator reads. One permission, declared once, on the router."""
    router = APIRouter(
        tags=["support"],
        dependencies=[Depends(require_permission(Permission.SUPPORT_READ))],
    )

    @router.get(SUPPORT_BOARD_PATH)
    async def support_board(db: Db, filters: Filters) -> SupportBoardView:
        """The four Kanban columns and how many described tickets are in each.

        **Declared before the detail route**, and this is the one place in this API where that
        ordering decides whether the route is reachable at all — see :data:`SUPPORT_BOARD_PATH`.

        **Not paged, and never derived from ``meta.total``.** A page's total is
        :func:`~bayram.db.admin.page.bounded_total`, which saturates at 10 000 and would make
        a busy column read as a ceiling; and a distribution cannot be sampled, because an
        arbitrary ten thousand rows have an arbitrary distribution. These four numbers are
        exact ``GROUP BY`` buckets over ``ix_support_tickets_status_created_at_id``, which is
        the index that exists for this and for the keyset page beside it.

        Takes the SAME filter set as the list below, so the board and the queue describe one
        population: a board summing to more than its own queue is a real bug, not a cosmetic
        one, and sharing the filters is what makes it impossible.

        **This route writes nothing, and must not start to.** It is the one read on this
        surface a "mark the queue as seen" feature would naturally attach itself to, and
        ``test_no_get_route_changes_domain_state`` snapshots every domain table around it.
        """
        return to_board_view(await ticket_board(db, filters=filters))

    @router.get(SUPPORT_TICKETS_PATH)
    async def list_ticket_page(
        db: Db, filters: Filters, paging: Paging, with_total: WithTotal = False
    ) -> SupportTicketsPage:
        """One keyset page of tickets, newest first, with the complaint on each row.

        The body travels on the LIST and not only on the detail, which is a departure from how
        every other free-text column in this API is handled and is argued on
        :class:`~bayram.db.admin.views.SupportTicketListItem`. The operational half of that
        argument is here: a queue whose rows say only "a ticket, 14:02, uz" cannot be triaged
        without opening fifty of them, which is fifty audited round trips to do the one thing
        the screen is for.
        """
        page = await list_tickets(db, filters=filters, request=paging)
        total = await count_tickets(db, filters=filters) if with_total else None
        return SupportTicketsPage(
            items=[to_ticket_view(item) for item in page.items], meta=page_meta(page, total)
        )

    @router.get(SUPPORT_TICKET_PATH)
    async def ticket_detail(db: Db, ticket_id: UUID) -> SupportTicketDetailView:
        """One ticket and its whole timeline, oldest first. Two statements, never a join."""
        return to_ticket_detail_view(await _found(db, ticket_id))

    return router


def build_support_actions_router() -> APIRouter:
    """Move, note, reply, assign — all four on ``SUPPORT_WRITE``, all four audited.

    One factory because one permission: §12.1 T3's rule is that the guard is declared on the
    router, and a second permission would be a second factory. There is no step-up to enforce
    in any handler below, which is the deliberate consequence of ``SUPPORT_WRITE`` being a
    plain ``W`` — see the permission's own note for why, and for the split this file would
    have to take if that ever changed.
    """
    router = APIRouter(
        tags=["support"],
        dependencies=[Depends(require_permission(Permission.SUPPORT_WRITE))],
    )

    @router.post(SUPPORT_TICKET_STATUS_PATH)
    async def move_ticket(
        body: TicketStatusRequest, db: Db, admin: Admin, container: Container, ticket_id: UUID
    ) -> SupportTicketDetailView:
        """Move a ticket between columns. **The conditional write is the concurrency control.**

        ``expectedStatus`` is named in the ``UPDATE``'s ``WHERE`` clause, so the rowcount is
        the lock: two operators dragging the same card produce one move and one 409, never two
        moves and a timeline that contradicts itself. The refusal reports the status read a
        moment before the write rather than pretending to have raced it — ``_wrong_status``
        makes the same distinction ``broadcasts._wrong_state`` does.

        The 404 read happens first, so an unknown id is a 404 and not a 409; the conditional
        ``UPDATE`` is still the authority on the status, because the ticket can move under this
        request — a staffer pressing ``✅ Resolve`` on the card in the group is another process.

        An ILLEGAL move never reaches here:
        :class:`~bayram.admin.schemas.tickets.TicketStatusRequest` refuses it as a 422 before a
        session opens, and ``move_status`` raises a ``ValidationError`` for the same case if a
        non-HTTP caller gets past it. The two read one grammar
        (:data:`~bayram.support.LEGAL_STATUS_MOVES`) and cannot disagree.
        """
        now = utc_now()
        detail = await _found(db, ticket_id)
        moved = await move_status(
            db,
            ticket_id,
            expected=body.expected_status,
            to_status=body.to_status,
            author=_author(admin),
            now=now,
        )
        if moved is None:
            raise _wrong_status(detail.ticket.status)
        await audit_sink.record(
            db,
            container,
            _entry(
                admin,
                action=AuditAction.TICKET_STATUS,
                ticket_id=ticket_id,
                field_names=("support_tickets.status",),
            ),
            now=now,
        )
        # COMMIT, then enqueue. The card in the group is the one copy of this ticket this
        # process cannot reach, so the worker is asked to re-render it FROM THE ROW — which
        # means the row must be visible to another session before the ask is. Read and
        # project first: ``db`` is unusable after ``_committed``.
        view = to_ticket_detail_view(await _reload(db, ticket_id))
        await _committed(db)
        unwrap(await container.queue.enqueue_support_card_sync(ticket_id))
        return view

    @router.post(SUPPORT_TICKET_ASSIGN_PATH)
    async def assign_ticket(
        body: TicketAssignRequest, db: Db, admin: Admin, container: Container, ticket_id: UUID
    ) -> SupportTicketDetailView:
        """Record who has this ticket. **Unconditional on the current holder, on purpose.**

        Handing a ticket over is ordinary work, so a reassignment must not be refused because
        somebody claimed it first — which is why this is not a second conditional write in the
        shape of the status move. ``assigned_admin_username`` is who has it NOW; the
        append-only ``assigned`` event is who has had it, and that is where the history lives.

        Assigning does **not** move the ticket. In the support group ``✋ Claim`` is both acts
        because a staffer has one button; here the operator has the column controls in front
        of them, and a hidden move would write a ``status_change`` nobody asked for.

        The card is re-rendered because it carries the claim row — the staffer reading it needs
        to know somebody has picked this up, which is most of what the card is for.
        """
        now = utc_now()
        await _found(db, ticket_id)
        assigned = await assign(
            db,
            ticket_id,
            admin_username=body.admin_username,
            author=_author(admin),
            now=now,
        )
        if assigned is None:  # pragma: no cover - read a moment ago in this transaction
            raise _no_such_ticket()
        await audit_sink.record(
            db,
            container,
            _entry(
                admin,
                action=AuditAction.TICKET_ASSIGN,
                ticket_id=ticket_id,
                field_names=("support_tickets.assigned_admin_username",),
            ),
            now=now,
        )
        # Read, project, COMMIT, enqueue — the order ``move_ticket`` explains and the module
        # docstring argues. The card carries the claim row, so a sync that read the row before
        # this commit would repaint it with the previous holder and then be told by Telegram
        # that nothing had changed.
        view = to_ticket_detail_view(await _reload(db, ticket_id))
        await _committed(db)
        unwrap(await container.queue.enqueue_support_card_sync(ticket_id))
        return view

    @router.post(SUPPORT_TICKET_NOTES_PATH)
    async def add_note(
        body: TicketNoteRequest, db: Db, admin: Admin, container: Container, ticket_id: UUID
    ) -> SupportTicketDetailView:
        """Append an internal line to the timeline. **The customer never sees this.**

        The only one of the four actions that enqueues NOTHING, and the only one that changes
        no state outside ``support_ticket_events``. A note reaches nobody and alters no
        rendered surface, so a card sync for it would ask the worker to edit a Telegram
        message to the text it already has — the seam carries work the worker must do, never
        news it might like (:class:`~bayram.admin.queue.AdminQueue`).

        The consequence to be clear-eyed about: a note is invisible to the staffers working
        from the group card. That is what an internal note IS, and the place to say something
        to them is the group itself.

        ``fieldNames`` names ``support_ticket_events.body`` — the column, never its contents.
        The prose stays on the append-only timeline, which has no retention clock and needs
        none; copying it into ``admin_audit_log`` would put operator text into the one table
        the purge deliberately cannot reach, which is exactly what ``broadcasts``' own audit
        note refuses for a campaign body.
        """
        now = utc_now()
        await _found(db, ticket_id)
        await append_event(
            db,
            ticket_id,
            kind=SupportTicketEventKind.NOTE,
            author=_author(admin),
            now=now,
            body=body.body,
        )
        await audit_sink.record(
            db,
            container,
            _entry(
                admin,
                action=AuditAction.TICKET_NOTE,
                ticket_id=ticket_id,
                field_names=("support_ticket_events.body",),
            ),
            now=now,
        )
        return to_ticket_detail_view(await _reload(db, ticket_id))

    @router.post(SUPPORT_TICKET_REPLY_PATH)
    async def reply_to_ticket(
        body: TicketReplyRequest, db: Db, admin: Admin, container: Container, ticket_id: UUID
    ) -> SupportTicketDetailView:
        """Answer the customer. **The one action on this surface that leaves the building.**

        Written first, delivered second, and the two are deliberately not the same fact. The
        ``reply`` event lands in this request's transaction with ``relayed_at`` NULL; the
        worker stamps that clock when the message actually reaches the customer's private
        chat. An operator reading a timeline can therefore tell "we answered them" from "we
        composed an answer that never landed" — the customer blocked the bot, Telegram refused
        the chat — which :class:`~bayram.admin.schemas.tickets.SupportTicketEventView` calls the
        single worst mistake available on this screen.

        The relay job is keyed on the EVENT id, deterministically, so a double-clicked Send
        collapses onto the job already queued rather than putting the same paragraph in
        somebody's phone twice (:func:`~bayram.admin.queue.job_id_for_support_relay`). That is
        why the event is written before the enqueue and why its id is threaded through rather
        than the text: the worker re-reads the row, and a payload carrying the words would put
        the conversation into Redis, where nothing sweeps it.

        **Written is not enough; it has to be COMMITTED.** The worker re-reads the event in a
        session of its own, so an enqueue that overtakes this request's commit hands ARQ the
        id of a row no other transaction can see — which is the race the module docstring
        describes and :func:`_committed` closes. The worker's half of the same defence is that
        a missing row is RETRYABLE rather than terminal
        (``bayram.runtime.support_jobs.relay_support_reply``); neither half is sufficient
        alone, because a retry ladder is not a correctness argument and a commit ordering
        cannot help a job that was replayed against an erased ticket.

        No card sync. The card renders the ticket's status and its claim row, and answering a
        customer changes neither — see the module docstring on why a panel reply, unlike a
        group reply, does not move the ticket either.

        ``recordCount`` is ``1`` here and ``None`` on the other three, and the column means
        what it means on a broadcast: how many people this authorised a message to. That is
        what makes "how many customers did we actually answer this month" a ``SUM`` over an
        indexed action filter rather than a count of rows that includes every internal note.
        """
        now = utc_now()
        await _found(db, ticket_id)
        event_id = await append_event(
            db,
            ticket_id,
            kind=SupportTicketEventKind.REPLY,
            author=_author(admin),
            now=now,
            body=body.body,
        )
        await audit_sink.record(
            db,
            container,
            _entry(
                admin,
                action=AuditAction.TICKET_REPLY,
                ticket_id=ticket_id,
                field_names=("support_ticket_events.body",),
                record_count=1,
            ),
            now=now,
        )
        # COMMIT, then enqueue, and nowhere in this file does the order matter more. The
        # worker is handed an EVENT ID and re-reads the row; a job that overtakes this
        # commit opens its own session, finds no such row, and the customer is never
        # answered while the timeline reads "composed". See the module docstring.
        view = to_ticket_detail_view(await _reload(db, ticket_id))
        await _committed(db)
        unwrap(await container.queue.enqueue_support_reply(ticket_id, event_id=event_id))
        return view

    return router


# ---------------------------------------------------------------------------
# The shared bodies
# ---------------------------------------------------------------------------
def _author(admin: CurrentAdmin) -> EventAuthor:
    """The timeline's record of who did it — an OPERATOR, with an audit row beside them.

    Truncated to ``ACTOR_USERNAME_LENGTH`` exactly as every ``AuditEntry`` in this package
    truncates its actor, so the two rows one action writes name the operator identically. They
    are two records of one act and a reader comparing them must not have to allow for one
    being cut and the other not.
    """
    return EventAuthor.operator(admin.username[:ACTOR_USERNAME_LENGTH])


def _wrong_status(status: SupportTicketStatus) -> ProblemError:
    """409 naming the status the ticket is actually in.

    The status IS published, unlike the id in the 404, and the difference is what the caller
    can do with it: an operator whose drag lost a race to a staffer pressing ``✅ Resolve`` in
    the group needs to know it was resolved, and the value is a closed enum this API already
    returns on every ticket. What is never published is which write refused — the conditional
    ``UPDATE`` in ``bayram.db.support_tickets`` is the authority on that, and this reports the
    status read a moment before it rather than pretending to have raced it.
    """
    return problem(
        AdminErrorCode.CONFLICT,
        "this ticket is not in the status that move expected",
        status=status.value,
    )


async def _found(db: Db, ticket_id: UUID) -> SupportTicketDetail:
    """The ticket and its timeline, or a 404. Read before every write, so an unknown id is
    never reported as a conflict."""
    detail = await get_ticket(db, ticket_id)
    if detail is None:
        raise _no_such_ticket()
    return detail


async def _committed(db: Db) -> None:
    """End the request's transaction HERE, so the enqueue that follows names committed rows.

    The one line of code in this module that exists purely for a process it cannot see. ARQ's
    worker opens its own session and reads under READ COMMITTED; a job enqueued while this
    transaction is still open is a job that can be dispatched, executed and completed against
    rows nothing outside this connection can read. :func:`bayram.admin.deps.get_db_session`
    commits on a clean exit of the REQUEST, which is far too late — the module docstring times
    the window and names what it destroyed.

    **Nothing may touch ``db`` after this call, and that is a hard constraint rather than a
    convention.** ``get_db_session`` holds the session inside ``async_sessionmaker.begin()``,
    and SQLAlchemy's ``TransactionalContext`` refuses any further statement on a transaction
    closed inside its own context manager — ``InvalidRequestError: Can't operate on closed
    transaction inside context manager``. Leaving the block afterwards is fine (the outer
    commit finds nothing to do) and so is raising out of it, which is what still lets
    :func:`~bayram.admin.errors.unwrap` answer a dead worker with a 503. So every handler here
    reads, projects its response, calls this, and enqueues last; a ``_reload`` moved below this
    line is a 500 at runtime and will not be caught by a type checker.

    Rejected: committing inside ``get_db_session`` before the ``yield`` handed the enqueue back
    (the dependency has no idea which handler enqueues, and would commit reads too), and a
    ``BackgroundTask`` (FastAPI runs those after the response is sent, so the operator could
    never be told the enqueue failed — and being told is the only thing left of the old
    rollback).
    """
    await db.commit()


async def _reload(db: Db, ticket_id: UUID) -> SupportTicketDetail:
    """Read the ticket back from the database rather than from arithmetic.

    Every mutation here answers with the record as it now stands, read in the same transaction
    that just wrote it — a response assembled from what the handler *believes* it wrote would
    be the panel telling an operator about a state nothing confirmed. It is also what puts the
    new timeline row on the response without the handler having to construct one.

    ``None`` is unreachable: the row was read a moment ago in this transaction and nothing here
    deletes it. Raised as a :class:`~bayram.errors.StorageError` so it lands in the shared
    envelope as a 503 rather than as a bare 500.
    """
    detail = await get_ticket(db, ticket_id)
    if detail is None:  # pragma: no cover - written in this very transaction
        raise ProblemError(
            StorageError(
                "the ticket this call wrote could not be read back",
                context={"ticket_id": str(ticket_id)},
            )
        )
    return detail


def _entry(
    admin: CurrentAdmin,
    *,
    action: AuditAction,
    ticket_id: UUID,
    field_names: tuple[str, ...],
    record_count: int | None = None,
) -> AuditEntry:
    """One row for one ticket action. Every handler in this module builds its row here.

    ``subjectType`` is :data:`TICKET_SUBJECT_TYPE` and ``subjectId`` the ticket's UUID — never
    the reporter's Telegram id and never ``public_ref``. A ticket has exactly one subject, and
    filing these rows under the customer would merge four operators working four different
    complaints from one account into one subject while putting an account identifier into the
    730-day table the purge deliberately cannot reach.

    ``reasonCode`` is :data:`SUPPORT_REASON` on every row, stamped rather than asked for; see
    that constant and ``schemas/tickets.py`` for the argument. ``reasonRef`` and ``reasonText``
    are absent for the same reason — there is no request field to carry them, so there is
    nothing to pass and no free text to put on a clocked column.

    ``fieldNames`` names columns and never their values, the rule every audit row in this
    package follows. ``support_ticket_events.body`` is named as a column on a note and a
    reply: what was said is on the append-only timeline, which the panel renders in full, and
    copying it here would put the conversation into ``admin_audit_log``.
    """
    return AuditEntry(
        action=action,
        actor_id=admin.admin_user_id,
        actor_username=admin.username[:ACTOR_USERNAME_LENGTH],
        actor_role=admin.role,
        subject_type=TICKET_SUBJECT_TYPE,
        subject_id=str(ticket_id),
        field_names=field_names,
        record_count=record_count,
        reason_code=SUPPORT_REASON,
        outcome=AuditOutcome.OK,
        ip=admin.client_ip,
    )
