"""``/support`` — the board, the queue behind it, and one ticket with everything said on it.

**This module READS. It never moves a ticket and never sends anything.** Both are structural
rather than tidy. A panel-side status change, note or reply has to reach Telegram, and
``bayram.admin.*`` may not import ``bayram.runtime.*`` at all — that import drags in
``aiogram.Bot``, and ``test_admin/test_queue.py``'s
``test_the_seam_can_reach_nothing_that_sends_a_message`` reads ``admin/queue.py``'s import
statements to prove it cannot happen. So a mutation is an ``AdminQueue`` job plus a write
composed from :mod:`bayram.db.support_tickets` into the request's own transaction, and this
file is the other half: what the screen shows.

**THE BOARD AND THE LIST ARE TWO QUERIES OVER ONE FILTER SET, AND THE BOARD HIDES A ROW THE
LIST DOES NOT.** A ticket whose ``described_at`` is NULL is a customer who tapped ⚠️ and never
typed. Those rows are real and are kept on purpose — they are the only measure of how many
people started to complain and gave up, and deleting them would make the count of attempts
equal the count of complaints by construction. What they are not is *work*: there is nothing
in them for an operator to read or answer. So :func:`ticket_board` excludes them always, and
:class:`TicketFilters` lets the list include or exclude them by asking. The two functions
share ``_filtered`` so a filter can never narrow one and not the other; the description
predicate is the one thing the board adds on top, and it is added in one place.

**Nothing here is bounded to a page's worth of rows and then extrapolated.** The board is a
``GROUP BY`` over ``ix_support_tickets_status_created_at_id`` — the index declared for exactly
this and for the keyset page beside it — for the reason ``count_orders_by_state`` spells out:
:func:`~bayram.db.admin.page.bounded_total`'s ``LIMIT`` trick cannot be borrowed for a
distribution, because an arbitrary ten thousand rows have an arbitrary distribution and the
column counts would be *differently* wrong with no way to see that they were. The list's
``?withTotal=true`` IS bounded, because that number answers "how long is this list".

**What crosses, and the one rule it breaks.** ``db/admin/views.py``'s standing rule is that a
customer's free text crosses as a length and a flag, with plaintext behind an audited,
step-up-gated reveal. The ticket body crosses whole, and the argument for the exception is
written out on :class:`~bayram.db.admin.views.SupportTicketListItem` rather than here — it is
a property of the shape, not of the query. Raw Telegram ids are carried exactly as
``GET /api/users`` already carries them and are masked by the serializer (§6.5).

No relationship is ever traversed. Every model in this schema is ``lazy="raise"``, so an
accidental ``ticket.events`` would surface as a greenlet error at an unrelated await;
:func:`get_ticket` issues its own two statements instead, the shape ``get_broadcast`` uses.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Final
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql import Select

from bayram.contracts import Language, SupportTicketSource, SupportTicketStatus
from bayram.db.admin.page import (
    BoundedTotal,
    Cursor,
    Page,
    PageRequest,
    bounded_total,
    build_page,
    keyset_order,
    keyset_predicate,
)
from bayram.db.admin.sql import TimeWindow, apply_in, apply_search, apply_window
from bayram.db.admin.views import (
    SupportTicketColumnTotal,
    SupportTicketDetail,
    SupportTicketEventItem,
    SupportTicketListItem,
)
from bayram.db.models.support_ticket import SupportTicketRow
from bayram.db.models.support_ticket_event import SupportTicketEventRow

__all__ = [
    "TicketFilters",
    "list_tickets",
    "count_tickets",
    "ticket_board",
    "get_ticket",
    "ticket_list_item",
    "ticket_event_item",
]

#: How many timeline rows a ticket has, as a correlated ``COUNT``.
#:
#: A subquery and not a join, for the reason ``orders._ASSET_COUNT`` gives: joining a
#: one-to-many child multiplies the page's rows, and a keyset ``LIMIT`` over multiplied rows is
#: a page that silently drops tickets. It is an index probe on
#: ``ix_support_ticket_events_ticket_id_created_at_id`` per row of a fifty-row page, against a
#: table whose rows-per-ticket is counted in tens.
#:
#: It rides in the ``SELECT`` list, which is why :func:`count_tickets` does not pay for it:
#: ``bounded_total`` replaces the column list with ``literal(1)`` and the subquery goes too.
_EVENT_COUNT: Final[sa.ScalarSelect[int]] = (
    sa.select(sa.func.count())
    .select_from(SupportTicketEventRow)
    .where(SupportTicketEventRow.ticket_id == SupportTicketRow.id)
    .correlate(SupportTicketRow)
    .scalar_subquery()
)

#: What ``?q=`` may substring-match on the ticket queue.
#:
#: ``public_ref`` is the obvious half: it is the string a customer reads down a phone line and
#: the whole reason the column exists, so a search box that could not find it would leave
#: support unable to answer the call it was designed for.
#:
#: ``body`` is the arguable half, and it is included deliberately. The rule this package keeps
#: — ``db/admin/broadcasts.py`` states it — is **search what is on the screen**: a ``LIKE`` over
#: a column the response does not show returns rows with no visible reason for being there,
#: and a ``LIKE`` over a column the caller could not otherwise read is an oracle that leaks it
#: a character at a time. Neither applies here, because the body is published in full on every
#: row of this same list (:class:`~bayram.db.admin.views.SupportTicketListItem` argues why). So
#: matching a substring of it discloses nothing the caller was not already handed, and it is
#: what makes "find every ticket that mentions the wrong name" a query rather than a scroll.
#:
#: ``assigned_admin_username`` is deliberately absent: "show me mine" is a FILTER, exact and
#: indexed, not a substring match, and offering both would make ``q=ali`` return Alisher's
#: tickets and every complaint containing the word.
#:
#: ``Any`` rather than ``str`` as the element type because ``body`` is nullable. A NULL body
#: matches nothing — ``LIKE`` over NULL is NULL — which is what an undescribed ticket ought to
#: do in a text search.
_SEARCHABLE_COLUMNS: Final[tuple[sa.SQLColumnExpression[Any], ...]] = (
    SupportTicketRow.public_ref,
    SupportTicketRow.body,
)


@dataclass(frozen=True, slots=True)
class TicketFilters:
    """The queue's filter set. Repeated values are OR within a field, AND across fields."""

    statuses: tuple[SupportTicketStatus, ...] = ()
    sources: tuple[SupportTicketSource, ...] = ()
    #: The language the ticket was OPENED in, which is the language the reply must be written
    #: in — not the account's language today. An operator who speaks Russian filters on this
    #: to find the tickets they can actually answer.
    languages: tuple[Language, ...] = ()
    #: Exact, never a substring. ``None`` means no filter; see :data:`_SEARCHABLE_COLUMNS` for
    #: why this is not folded into ``q``.
    assigned_admin_username: str | None = None
    #: Exact. The first question of any complaint that arrives by another route ("this
    #: customer says they wrote to you") and the read a ``/forget`` audit would start from.
    telegram_user_id: int | None = None
    #: Applied to ``created_at`` — when the customer TAPPED, half-open. Deliberately not
    #: ``described_at``: a window on a nullable column would silently drop every
    #: tapped-and-never-typed ticket from a range an operator believes covers everything,
    #: which is precisely the population that window would be used to measure.
    window: TimeWindow | None = None
    #: Substring over :data:`_SEARCHABLE_COLUMNS`. Blank or ``None`` means no filter, never an
    #: empty page — :func:`~bayram.db.admin.sql.search_clause`'s asymmetry.
    search: str | None = None
    #: Drop the tickets nobody described. ``False`` by default, so the QUEUE shows everything
    #: and the row that measures abandonment is visible somewhere; :func:`ticket_board` forces
    #: it on, because a board column full of unanswerable rows is a queue length that lies.
    only_described: bool = False


#: "Every ticket" as a value, so :func:`ticket_board` can default to it without constructing a
#: dataclass in an argument default — a mutable default in all but name, and the one thing
#: ``ruff``'s ``B008`` is watching for. Frozen and shared, which is safe precisely because
#: :class:`TicketFilters` is.
_ALL_TICKETS: Final[TicketFilters] = TicketFilters()


async def list_tickets(
    session: AsyncSession, *, filters: TicketFilters, request: PageRequest
) -> Page[SupportTicketListItem]:
    """One keyset page of tickets, newest first. One row per ticket.

    ``(created_at, id)`` descending, the ordering every list in this package defaults to. The
    primary key is carried as the tie-break and is not decoration: a group of tickets opened in
    the same second by one outage is exactly the tie group a keyset without it pages over and
    repeats, and it is also the third column of
    ``ix_support_tickets_status_created_at_id`` — so a page filtered to one status is an index
    range scan with no sort at all, which is what the board's columns are made of.

    There is no sorted-cursor variant and no ``sort=`` parameter. The sorted walk in
    ``db/admin/users.py`` exists because a segment's field registry offers keys to sort by;
    a queue is read newest-first or by column, and a sort key that is not carried in the cursor
    cannot be resumed.
    """
    statement = _filtered(filters)
    resume = keyset_predicate(SupportTicketRow.created_at, SupportTicketRow.id, request.cursor)
    if resume is not None:
        statement = statement.where(resume)
    statement = statement.order_by(
        *keyset_order(SupportTicketRow.created_at, SupportTicketRow.id)
    ).limit(request.fetch_limit)
    rows = (await session.execute(statement)).all()
    items = [ticket_list_item(row, event_count=event_count) for row, event_count in rows]
    return build_page(items, request, _cursor_of)


async def count_tickets(session: AsyncSession, *, filters: TicketFilters) -> BoundedTotal:
    """``?withTotal=true`` for the same filter set. Bounded — see :func:`bounded_total`.

    Bounded even though support volume is small, because the cap is what makes the count's
    cost independent of the table it counts, and "10,000+" is honest where a number stated
    from a full scan is merely confident. The numbers an operator actually steers by are
    :func:`ticket_board`'s, which are exact and never saturate.
    """
    return await bounded_total(session, _filtered(filters))


async def ticket_board(
    session: AsyncSession, *, filters: TicketFilters = _ALL_TICKETS
) -> tuple[SupportTicketColumnTotal, ...]:
    """The four Kanban columns and how many described tickets are in each. Exact, zero-filled.

    ``described_at IS NOT NULL`` is forced on regardless of what the caller passed, and it is
    the one predicate this function adds: an undescribed ticket is a tap nobody followed up,
    and a column length that counted them would send an operator to look at rows with nothing
    in them to read. The same rows are still reachable from the queue, which is where the
    question "how many people gave up?" is asked.

    Every status is reported, always, including the ones with no rows — a board whose columns
    appear as data arrives re-lays-out under the operator's cursor, and an empty board and a
    failed request must not look alike. Declaration order, so the columns are
    ``new -> in_progress -> waiting -> resolved`` and not whatever the ``GROUP BY`` returned.

    Takes the SAME filter set as the list so the two describe one population: a board summing
    to more than its own queue is the bug this sharing removes, not a cosmetic one.
    """
    statement = (
        _filtered(filters, only_described=True)
        .with_only_columns(
            SupportTicketRow.status, sa.func.count().label("total"), maintain_column_froms=True
        )
        .group_by(SupportTicketRow.status)
    )
    counted = {status: int(total) for status, total in (await session.execute(statement)).all()}
    return tuple(
        SupportTicketColumnTotal(status=status, count=counted.get(status, 0))
        for status in SupportTicketStatus
    )


async def get_ticket(session: AsyncSession, ticket_id: UUID) -> SupportTicketDetail | None:
    """One ticket and every event on it. ``None`` for an unknown id — the caller answers 404.

    Two statements rather than a join, for ``get_broadcast``'s reason: joining a one-to-many
    child multiplies the parent row by its children and hands Python a shape to un-multiply.
    The relationship that would have made it one statement does not exist on the model at all,
    and would be ``lazy="raise"`` if it did.

    The ticket is read through the same ``_filtered`` the list uses, with an empty filter set,
    so the detail and the row that led to it are built by the same code — including the event
    count, which would otherwise be a field the detail quietly reported differently.
    """
    row = (
        await session.execute(_filtered(_ALL_TICKETS).where(SupportTicketRow.id == ticket_id))
    ).first()
    if row is None:
        return None
    ticket, event_count = row
    return SupportTicketDetail(
        ticket=ticket_list_item(ticket, event_count=event_count),
        events=await _load_events(session, ticket_id),
    )


# ---------------------------------------------------------------------------
# Row -> view model. Pure.
# ---------------------------------------------------------------------------
def ticket_list_item(row: SupportTicketRow, *, event_count: int) -> SupportTicketListItem:
    """Build one queue row. ``event_count`` is keyword-only: it is a bare integer that would
    transpose silently against any other, which is the mistake ``broadcast_list_item`` names.

    ``group_message_id`` is collapsed to a boolean here rather than published. The panel has
    no use for a Telegram routing id it can never act on — the admin process holds no bot
    token by design (``ADMIN_PANEL_PLAN D10 / §4.2``) — and a field nobody needs is a field
    some future screen tries to use.
    """
    return SupportTicketListItem(
        id=row.id,
        public_ref=row.public_ref,
        telegram_user_id=row.telegram_user_id,
        language=row.language,
        source=row.source,
        order_id=row.order_id,
        status=row.status,
        body=row.body,
        described_at=row.described_at,
        assigned_admin_username=row.assigned_admin_username,
        assigned_at=row.assigned_at,
        is_posted_to_group=row.group_message_id is not None,
        group_posted_at=row.group_posted_at,
        resolved_at=row.resolved_at,
        event_count=event_count,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def ticket_event_item(row: SupportTicketEventRow) -> SupportTicketEventItem:
    """Build one timeline row. Every column crosses; see the view's docstring for why."""
    return SupportTicketEventItem(
        id=row.id,
        ticket_id=row.ticket_id,
        kind=row.kind,
        author_kind=row.author_kind,
        author_admin_username=row.author_admin_username,
        author_telegram_user_id=row.author_telegram_user_id,
        author_display_name=row.author_display_name,
        from_status=row.from_status,
        to_status=row.to_status,
        body=row.body,
        relayed_at=row.relayed_at,
        created_at=row.created_at,
    )


# ---------------------------------------------------------------------------
# internals
# ---------------------------------------------------------------------------
def _filtered(
    filters: TicketFilters, *, only_described: bool = False
) -> Select[tuple[SupportTicketRow, int]]:
    """The shared ``FROM``/``WHERE`` every ticket query starts from, keyset excluded.

    Shared by the page, its count, the board and the detail so no two of them can describe
    different populations. ``only_described`` is an argument rather than a fifth filter field
    because the board FORCES it and the queue merely offers it — a caller that could turn the
    board's own predicate off would be a board that counted rows it cannot show.

    The event count rides in the ``SELECT`` list, so ``bounded_total`` drops it. The search
    predicate is a ``WHERE`` and narrows both, which it must: otherwise ``?withTotal=true``
    would label a two-row page with the unfiltered count.
    """
    statement = sa.select(SupportTicketRow, _EVENT_COUNT.label("event_count"))
    statement = apply_in(statement, SupportTicketRow.status, filters.statuses)
    statement = apply_in(statement, SupportTicketRow.source, filters.sources)
    statement = apply_in(statement, SupportTicketRow.language, filters.languages)
    if filters.assigned_admin_username is not None:
        statement = statement.where(
            SupportTicketRow.assigned_admin_username == filters.assigned_admin_username
        )
    if filters.telegram_user_id is not None:
        statement = statement.where(SupportTicketRow.telegram_user_id == filters.telegram_user_id)
    if only_described or filters.only_described:
        statement = statement.where(SupportTicketRow.described_at.is_not(None))
    statement = apply_window(statement, SupportTicketRow.created_at, filters.window)
    return apply_search(statement, filters.search, _SEARCHABLE_COLUMNS)


async def _load_events(
    session: AsyncSession, ticket_id: UUID
) -> tuple[SupportTicketEventItem, ...]:
    """One ticket's whole timeline, OLDEST FIRST — the only ascending list in this package.

    A conversation is read forwards, and an operator deciding what to say next reads down to
    the last thing that was said. ``(created_at, id)`` is the order
    ``ix_support_ticket_events_ticket_id_created_at_id`` was declared to serve, and the id is
    the tie-break that matters here more than anywhere: a status change and the note that
    explains it are written in one transaction and share an instant exactly, so without it the
    two would swap places between two reads of the same ticket.

    Unpaged, deliberately. See :class:`~bayram.db.admin.views.SupportTicketDetail`.
    """
    rows = (
        (
            await session.execute(
                sa.select(SupportTicketEventRow)
                .where(SupportTicketEventRow.ticket_id == ticket_id)
                .order_by(SupportTicketEventRow.created_at, SupportTicketEventRow.id)
            )
        )
        .scalars()
        .all()
    )
    return tuple(ticket_event_item(row) for row in rows)


def _cursor_of(item: SupportTicketListItem) -> Cursor:
    return Cursor(at=item.created_at, id=item.id)
