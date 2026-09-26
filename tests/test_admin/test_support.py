"""``/api/support/tickets`` over the real ASGI stack — the queue, the board, and the four acts.

Five properties carry this file, and each of them is a thing that would be invisible if it
broke.

**1. The board is reachable at all.** ``/board`` and ``/{ticket_id}`` are both one segment
under ``/support/tickets``, so a registration order that put the parameterised route first
would answer an operator's board with a 422 about a malformed UUID — a failure that looks
like a client bug and is a routing bug. It is asserted directly rather than inferred from the
route table, because the route table would be identical either way.

**2. The conditional move is really conditional.** ``expectedStatus`` is named in the
``UPDATE``'s ``WHERE`` clause and the rowcount is the lock, so a stale expectation must be a
409 and must leave the row alone. A test that only exercised the winning side could not tell a
conditional write from an unconditional one — which is precisely the bug that makes two
operators' drags both "succeed" and the timeline contradict itself.

**3. Every action writes BOTH records, in one transaction.** An ``admin_audit_log`` row naming
an audited actor and a ``support_ticket_events`` row naming the author, and the two are
asserted together because they answer different questions: the audit row says an operator with
a role and an IP did it, the event row says what the customer's timeline shows. An action that
wrote one and not the other is the failure §9.1's first rule exists to make impossible.

**4. A reply is written before it is delivered, and the seam is asserted on its ARGUMENTS.**
The queue is a recording :class:`~bayram.admin.queue.NullAdminQueue`, so "did it ask the worker
to relay THIS event of THIS ticket" is a claim about ids rather than a counter that a wrong id
would satisfy. ``relayedAt`` is null on the freshly written event on purpose — the worker
stamps it when the message lands — and the test says so, because an operator reading that
column as "we answered them" when nothing landed is the worst mistake this screen offers.

**5. The rows are COMMITTED before the worker is told they exist.** This replaces the property
that used to sit here ("a refusing queue rolls the whole action back"), and the replacement is
a bug fix rather than a relaxation. The enqueue used to run inside the request's transaction so
that a dead worker could undo the write; ``get_db_session`` commits on a clean exit of the
REQUEST, so a live worker could pick the job up, open its own session, and find no such row —
and the relay job answered that by completing successfully with the reply undelivered.
``CommitProbeQueue`` at the bottom of this file asserts the ordering the way the worker
experiences it, from a second connection, which is why those two tests need a FILE database.
A refusing queue is still a 503, and the two tests that cover it now assert what it LEAVES.

Roles are swept over all four for every route, because the two cells here are rulings §12.2 has
no rows for — ``SUPPORT_WRITE`` is the only write cell in the matrix that starts at SUPPORT —
and a narrowed or widened cell should fail here rather than in review.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path
from typing import Any, Final
from uuid import UUID, uuid4

import httpx
import pytest
import sqlalchemy as sa

from bayram.admin.container import AdminContainer
from bayram.admin.errors import AdminErrorCode
from bayram.admin.queue import SUPPORT_CARD_JOB_NAME, SUPPORT_RELAY_JOB_NAME, NullAdminQueue
from bayram.admin.routers.support import (
    SUPPORT_BOARD_PATH,
    SUPPORT_REASON,
    SUPPORT_TICKET_ASSIGN_PATH,
    SUPPORT_TICKET_NOTES_PATH,
    SUPPORT_TICKET_PATH,
    SUPPORT_TICKET_REPLY_PATH,
    SUPPORT_TICKET_STATUS_PATH,
    SUPPORT_TICKETS_PATH,
    TICKET_SUBJECT_TYPE,
)
from bayram.admin.schemas.tickets import MAX_TICKET_BODY_CHARS
from bayram.contracts import (
    Language,
    SupportAuthorKind,
    SupportTicketEventKind,
    SupportTicketSource,
    SupportTicketStatus,
)
from bayram.db.admin.support_tickets import get_ticket
from bayram.db.enums import AdminRole, AuditAction
from bayram.db.models.admin_audit import AdminAuditRow
from bayram.db.models.support_ticket import SupportTicketRow
from bayram.db.models.support_ticket_event import SupportTicketEventRow
from tests.test_admin.conftest import (
    NOW,
    PASSWORD,
    FakeRedis,
    MemoryRateLimits,
    create_account,
    csrf_headers,
    make_settings,
    open_client,
    open_container,
    sign_in,
)

#: Every role in the matrix, so a widened or narrowed cell fails here rather than in review.
EVERY_ROLE: Final[tuple[AdminRole, ...]] = (
    AdminRole.VIEWER,
    AdminRole.SUPPORT,
    AdminRole.ADMIN,
    AdminRole.OWNER,
)

#: The three roles §12.2's new row gives ``SUPPORT_WRITE``, and the one it does not. SUPPORT
#: being on the WRITE list is the whole point of the row and is the cell most worth a witness.
WRITE_ROLES: Final[tuple[AdminRole, ...]] = (AdminRole.SUPPORT, AdminRole.ADMIN, AdminRole.OWNER)
READ_ONLY_ROLES: Final[tuple[AdminRole, ...]] = (AdminRole.VIEWER,)

TICKET_ID: Final[UUID] = UUID("11111111-0000-4000-8000-000000000001")
OTHER_TICKET_ID: Final[UUID] = UUID("11111111-0000-4000-8000-000000000002")
UNKNOWN_ID: Final[UUID] = UUID("99999999-0000-4000-8000-0000000000ff")

#: Distinctive enough that a substring hit in a response body is a real find. The mask keeps
#: the LAST three digits (§12.3), so ``987`` appears in the masked form too — which is why the
#: leak assertions look for the WHOLE id and the tests that want the mask ask for it by name.
REPORTER_ID: Final[int] = 987_654_321
#: A staffer in the support group, whose id is masked on the timeline and never published raw.
STAFFER_ID: Final[int] = 555_444_333

PUBLIC_REF: Final[str] = "11111111"
#: The customer's own words. Long enough to be searched for by substring, and containing
#: nothing that could match a reference or a username by accident.
COMPLAINT: Final[str] = "The song said Dilnoza and her name is Dilnora"

TICKET_URL: Final[str] = SUPPORT_TICKET_PATH.format(ticket_id=TICKET_ID)
STATUS_URL: Final[str] = SUPPORT_TICKET_STATUS_PATH.format(ticket_id=TICKET_ID)
NOTES_URL: Final[str] = SUPPORT_TICKET_NOTES_PATH.format(ticket_id=TICKET_ID)
REPLY_URL: Final[str] = SUPPORT_TICKET_REPLY_PATH.format(ticket_id=TICKET_ID)
ASSIGN_URL: Final[str] = SUPPORT_TICKET_ASSIGN_PATH.format(ticket_id=TICKET_ID)


@dataclass(frozen=True, slots=True)
class Panel:
    container: AdminContainer
    http: httpx.AsyncClient
    queue: NullAdminQueue


@asynccontextmanager
async def open_panel(*, refusing: bool = False, **settings: Any) -> AsyncIterator[Panel]:
    """One panel, with its queue chosen by the caller.

    A context manager rather than a parametrised fixture, for the reason
    ``test_broadcasts_router``'s own ``open_panel`` gives: exactly one test needs a deployment
    with no worker, and parametrising would put that configuration in front of every test here.
    """
    queue = NullAdminQueue(refusing=refusing)
    async with (
        open_container(
            make_settings(**settings), FakeRedis(), MemoryRateLimits(), queue
        ) as container,
        open_client(container) as http,
    ):
        yield Panel(container=container, http=http, queue=queue)


@pytest.fixture
async def panel() -> AsyncIterator[Panel]:
    async with open_panel() as opened:
        yield opened


async def signed_in(panel: Panel, *, role: AdminRole = AdminRole.SUPPORT) -> str:
    """Sign in as ``role``. **SUPPORT by default**, and that default is an assertion.

    Every other router test in this package signs in as ADMIN or OWNER, because those are
    where its write cells start. This namespace is the one whose write cell starts at SUPPORT,
    so running the whole file at that role is what would notice the cell narrowing to ADMIN —
    a change that would leave the support desk unable to answer a customer while every
    OWNER-driven test still passed.
    """
    username = f"{role.value}-account"
    await create_account(panel.container, username=username, role=role)
    assert (await sign_in(panel.http, username=username, password=PASSWORD)).status_code == 200
    return username


# ---------------------------------------------------------------------------
# Seeding, through the real models
# ---------------------------------------------------------------------------
async def seed_ticket(panel: Panel, **overrides: Any) -> SupportTicketRow:
    """One described ticket, with every column the model does not default in Python set.

    Seeded directly rather than opened through the bot's flow, because that flow lives in
    another process entirely — the ⚠️ button is drawn by the worker and answered by the bot —
    and a panel test that had to run it would be testing the bot.

    Described by default: an undescribed ticket is the interesting minority, so the tests that
    want one say so, and the board's exclusion rule gets a witness instead of a default.
    """
    values: dict[str, Any] = {
        "id": TICKET_ID,
        "public_ref": PUBLIC_REF,
        "telegram_user_id": REPORTER_ID,
        "language": Language.UZ_LATN,
        "source": SupportTicketSource.DELIVERY_BUTTON,
        "order_id": None,
        "status": SupportTicketStatus.NEW,
        "body": COMPLAINT,
        "prompt_message_id": 4242,
        "described_at": NOW,
        "assigned_admin_username": None,
        "assigned_at": None,
        "group_chat_id": None,
        "group_message_id": None,
        "group_posted_at": None,
        "resolved_at": None,
        "created_at": NOW,
        "updated_at": NOW,
    }
    values.update(overrides)
    row = SupportTicketRow(**values)
    async with panel.container.session_factory.begin() as db:
        db.add(row)
    return row


async def seed_event(panel: Panel, **overrides: Any) -> SupportTicketEventRow:
    """One timeline row. ``created_at`` is stated on every call; nothing here reads a clock."""
    values: dict[str, Any] = {
        "id": uuid4(),
        "ticket_id": TICKET_ID,
        "kind": SupportTicketEventKind.OPENED,
        "author_kind": SupportAuthorKind.SYSTEM,
        "author_admin_username": None,
        "author_telegram_user_id": None,
        "author_display_name": None,
        "from_status": None,
        "to_status": None,
        "body": None,
        "relayed_at": None,
        "created_at": NOW,
    }
    values.update(overrides)
    row = SupportTicketEventRow(**values)
    async with panel.container.session_factory.begin() as db:
        db.add(row)
    return row


async def ticket_row(panel: Panel, ticket_id: UUID = TICKET_ID) -> SupportTicketRow:
    """The row as it now stands, read outside the request that may have changed it."""
    async with panel.container.session_factory.begin() as db:
        statement = sa.select(SupportTicketRow).where(SupportTicketRow.id == ticket_id)
        return (await db.execute(statement)).scalar_one()


async def events_of(panel: Panel, ticket_id: UUID = TICKET_ID) -> list[SupportTicketEventRow]:
    """This ticket's timeline, oldest first — the order the detail route promises."""
    async with panel.container.session_factory.begin() as db:
        statement = (
            sa.select(SupportTicketEventRow)
            .where(SupportTicketEventRow.ticket_id == ticket_id)
            .order_by(SupportTicketEventRow.created_at, SupportTicketEventRow.id)
        )
        return list((await db.execute(statement)).scalars().all())


async def audit_rows(panel: Panel) -> list[AdminAuditRow]:
    """Every ticket audit row, oldest first. Login rows and refusals are filtered out."""
    async with panel.container.session_factory.begin() as db:
        statement = (
            sa.select(AdminAuditRow)
            .where(AdminAuditRow.subject_type == TICKET_SUBJECT_TYPE)
            .order_by(AdminAuditRow.seq)
        )
        return list((await db.execute(statement)).scalars().all())


def post(panel: Panel, url: str, body: dict[str, Any]) -> Any:
    """A CSRF-bearing POST, since every mutation here goes through ``get_current_admin``."""
    return panel.http.post(url, json=body, headers=csrf_headers(panel.http))


# ---------------------------------------------------------------------------
# Routing — the property the route table cannot see
# ---------------------------------------------------------------------------
async def test_the_board_route_is_not_swallowed_by_the_ticket_detail_route(
    panel: Panel,
) -> None:
    # Arrange — ``/board`` and ``/{ticket_id}`` are both ONE segment under
    # ``/support/tickets``, so whichever is registered first wins. If the parameterised route
    # won, this would be a 422 about a malformed UUID and the frozen route table would be
    # completely unchanged — which is why the assertion is here and not there.
    await signed_in(panel)

    # Act
    response = await panel.http.get(SUPPORT_BOARD_PATH)

    # Assert
    assert response.status_code == 200
    assert [column["status"] for column in response.json()["columns"]] == [
        status.value for status in SupportTicketStatus
    ]


# ---------------------------------------------------------------------------
# The board
# ---------------------------------------------------------------------------
async def test_the_board_reports_every_column_including_the_empty_ones(panel: Panel) -> None:
    # Arrange — one ticket in one column. A board that only reported columns with rows in them
    # would re-lay-out under the operator's cursor as work arrived, and an empty board would
    # be indistinguishable from a failed request.
    await signed_in(panel)
    await seed_ticket(panel, status=SupportTicketStatus.WAITING)

    # Act
    body = (await panel.http.get(SUPPORT_BOARD_PATH)).json()

    # Assert
    assert {column["status"]: column["count"] for column in body["columns"]} == {
        SupportTicketStatus.NEW.value: 0,
        SupportTicketStatus.IN_PROGRESS.value: 0,
        SupportTicketStatus.WAITING.value: 1,
        SupportTicketStatus.RESOLVED.value: 0,
    }


async def test_the_board_excludes_the_tickets_nobody_described(panel: Panel) -> None:
    # Arrange — two tickets in the same column, one of which is a customer who tapped ⚠️ and
    # never typed. That row is real data and stays in the QUEUE; what it is not is work, and a
    # column length that counted it would send an operator to look at a card with nothing in
    # it to read.
    await signed_in(panel)
    await seed_ticket(panel)
    await seed_ticket(
        panel, id=OTHER_TICKET_ID, public_ref="22222222", body=None, described_at=None
    )

    # Act
    board = (await panel.http.get(SUPPORT_BOARD_PATH)).json()
    queue = (await panel.http.get(SUPPORT_TICKETS_PATH)).json()

    # Assert — the board counts one and the queue lists both, which is the whole distinction.
    assert {column["status"]: column["count"] for column in board["columns"]}[
        SupportTicketStatus.NEW.value
    ] == 1
    assert len(queue["items"]) == 2


async def test_the_board_and_the_queue_answer_the_same_filter(panel: Panel) -> None:
    # Arrange — a board summing to more than its own queue is a real bug and not a cosmetic
    # one, and sharing ``TicketFilters`` between the two is what makes it impossible. Two
    # tickets in different languages, filtered to one.
    await signed_in(panel)
    await seed_ticket(panel, language=Language.UZ_LATN)
    await seed_ticket(panel, id=OTHER_TICKET_ID, public_ref="22222222", language=Language.RU)

    # Act
    board = (await panel.http.get(f"{SUPPORT_BOARD_PATH}?language=ru")).json()
    queue = (await panel.http.get(f"{SUPPORT_TICKETS_PATH}?language=ru")).json()

    # Assert
    assert sum(column["count"] for column in board["columns"]) == 1
    assert len(queue["items"]) == 1


# ---------------------------------------------------------------------------
# The queue
# ---------------------------------------------------------------------------
async def test_a_queue_row_carries_the_complaint_and_the_moves_it_may_make(
    panel: Panel,
) -> None:
    # Arrange — the two things this list publishes that no other list in the panel does: a
    # customer's free text in full, and the server's own status grammar. The first is argued on
    # ``SupportTicketListItem``; the second is what stops the SPA shipping buttons that are
    # guaranteed 422s.
    await signed_in(panel)
    await seed_ticket(panel)

    # Act
    item = (await panel.http.get(SUPPORT_TICKETS_PATH)).json()["items"][0]

    # Assert
    assert item["body"] == COMPLAINT
    assert item["publicRef"] == PUBLIC_REF
    # Declaration order, never a set's iteration order — a button row that reordered itself
    # between two renders of the same ticket would be the symptom of publishing the frozenset.
    assert item["allowedTransitions"] == [
        SupportTicketStatus.IN_PROGRESS.value,
        SupportTicketStatus.WAITING.value,
        SupportTicketStatus.RESOLVED.value,
    ]


async def test_a_resolved_ticket_offers_exactly_one_way_back(panel: Panel) -> None:
    # Arrange — ``resolved`` is terminal but reopenable, and only to ``in_progress``: a ticket
    # that came back is being worked, not waiting and certainly not new.
    await signed_in(panel)
    await seed_ticket(panel, status=SupportTicketStatus.RESOLVED, resolved_at=NOW)

    # Act
    item = (await panel.http.get(SUPPORT_TICKETS_PATH)).json()["items"][0]

    # Assert
    assert item["allowedTransitions"] == [SupportTicketStatus.IN_PROGRESS.value]


async def test_the_queue_publishes_the_reporter_by_id_and_by_mask(panel: Panel) -> None:
    # Arrange — this namespace follows ``/users`` rather than ``BroadcastRecipientView``: the
    # raw id is on the wire because every ``/users/**`` route keys on it and the first thing an
    # operator does with a complaint is open the customer's record to answer it. A mask the SPA
    # cannot dereference would make the ticket a dead end at that exact moment.
    await signed_in(panel)
    await seed_ticket(panel)

    # Act
    item = (await panel.http.get(SUPPORT_TICKETS_PATH)).json()["items"][0]

    # Assert
    assert item["telegramUserId"] == REPORTER_ID
    assert item["telegramUserIdMasked"].endswith("321")
    assert str(REPORTER_ID) not in item["telegramUserIdMasked"]


async def test_the_search_matches_the_reference_and_the_body(panel: Panel) -> None:
    # Arrange — the one search in this API that reaches a customer's own words, and it is
    # allowed to because the same rows publish those words in full on the response it returns.
    await signed_in(panel)
    await seed_ticket(panel)
    await seed_ticket(
        panel, id=OTHER_TICKET_ID, public_ref="22222222", body="Something else entirely"
    )

    # Act
    by_ref = (await panel.http.get(f"{SUPPORT_TICKETS_PATH}?q={PUBLIC_REF}")).json()
    by_body = (await panel.http.get(f"{SUPPORT_TICKETS_PATH}?q=Dilnora")).json()

    # Assert
    assert [item["id"] for item in by_ref["items"]] == [str(TICKET_ID)]
    assert [item["id"] for item in by_body["items"]] == [str(TICKET_ID)]


async def test_the_assignee_filter_is_exact_and_is_not_the_search(panel: Panel) -> None:
    # Arrange — "show me Dilnoza's tickets" and "find the ticket mentioning Dilnoza" are two
    # questions. A substring search that answered both would put every ticket whose BODY names
    # an operator into that operator's queue.
    await signed_in(panel)
    await seed_ticket(panel, assigned_admin_username="dilnoza", assigned_at=NOW)
    await seed_ticket(
        panel,
        id=OTHER_TICKET_ID,
        public_ref="22222222",
        body="dilnoza said it was fine",
        assigned_admin_username=None,
    )

    # Act
    assigned = (await panel.http.get(f"{SUPPORT_TICKETS_PATH}?assignedTo=dilnoza")).json()

    # Assert
    assert [item["id"] for item in assigned["items"]] == [str(TICKET_ID)]


async def test_the_total_is_reported_only_when_it_was_asked_for(panel: Panel) -> None:
    # Arrange — ``total`` and ``isTotalExact`` travel together or not at all: the count
    # saturates, so a bare number would be read as a measurement when it is a ceiling.
    await signed_in(panel)
    await seed_ticket(panel)

    # Act
    without = (await panel.http.get(SUPPORT_TICKETS_PATH)).json()["meta"]
    with_total = (await panel.http.get(f"{SUPPORT_TICKETS_PATH}?withTotal=true")).json()["meta"]

    # Assert
    assert without["total"] is None and without["isTotalExact"] is None
    assert with_total["total"] == 1 and with_total["isTotalExact"] is True


# ---------------------------------------------------------------------------
# The detail
# ---------------------------------------------------------------------------
async def test_the_detail_reads_its_timeline_forwards(panel: Panel) -> None:
    # Arrange — the one list in this package that is not newest-first, because a conversation
    # is read forwards. Two events a minute apart, inserted newest first so a test that passed
    # by insertion order would fail here.
    await signed_in(panel)
    await seed_ticket(panel)
    await seed_event(
        panel, kind=SupportTicketEventKind.DESCRIBED, created_at=NOW + timedelta(minutes=1)
    )
    await seed_event(panel, kind=SupportTicketEventKind.OPENED, created_at=NOW)

    # Act
    body = (await panel.http.get(TICKET_URL)).json()

    # Assert
    assert [event["kind"] for event in body["events"]] == [
        SupportTicketEventKind.OPENED.value,
        SupportTicketEventKind.DESCRIBED.value,
    ]


async def test_a_group_staffers_telegram_id_is_masked_on_the_timeline(panel: Panel) -> None:
    # Arrange — the one place this namespace departs from its own "publish the raw id" rule.
    # The reporter's id is published because the panel navigates to their record; the author of
    # a timeline line is a staffer in a chat, whom this API cannot route to at all, so there is
    # nothing for the raw value to buy and it stays out of the bytes.
    await signed_in(panel)
    await seed_ticket(panel)
    await seed_event(
        panel,
        kind=SupportTicketEventKind.REPLY,
        author_kind=SupportAuthorKind.STAFF_GROUP,
        author_telegram_user_id=STAFFER_ID,
        author_display_name="@ozod",
        body="We are on it",
    )

    # Act
    response = await panel.http.get(TICKET_URL)
    event = response.json()["events"][0]

    # Assert — on ``response.text`` and not only on the field list, because "the model has no
    # such field" is a weaker claim than "the digits are not in the bytes".
    assert str(STAFFER_ID) not in response.text
    assert event["authorTelegramUserIdMasked"].endswith("333")
    assert event["authorDisplayName"] == "@ozod"


async def test_an_unrelayed_reply_says_so_rather_than_looking_answered(panel: Panel) -> None:
    # Arrange — a ``reply`` row with no relay clock is a sentence that was composed and never
    # reached anybody. An operator who cannot see the difference reads the timeline as "we
    # answered them" when nothing landed, which is the single worst mistake on this screen.
    await signed_in(panel)
    await seed_ticket(panel)
    await seed_event(panel, kind=SupportTicketEventKind.REPLY, body="Sent", relayed_at=NOW)
    await seed_event(
        panel,
        kind=SupportTicketEventKind.REPLY,
        body="Never landed",
        relayed_at=None,
        created_at=NOW + timedelta(minutes=1),
    )

    # Act
    events = (await panel.http.get(TICKET_URL)).json()["events"]

    # Assert
    assert [event["relayedAt"] is None for event in events] == [False, True]


async def test_an_unknown_ticket_is_a_404_that_echoes_nothing(panel: Panel) -> None:
    # Arrange — an identifier is not a hint worth confirming.
    await signed_in(panel)

    # Act
    response = await panel.http.get(SUPPORT_TICKET_PATH.format(ticket_id=UNKNOWN_ID))

    # Assert
    assert response.status_code == 404
    assert str(UNKNOWN_ID) not in response.text


# ---------------------------------------------------------------------------
# The move — both sides of the conditional write
# ---------------------------------------------------------------------------
async def test_a_move_writes_the_row_the_event_and_the_audit_row(panel: Panel) -> None:
    # Arrange — the three records one action leaves, asserted together because they answer
    # different questions and an action that wrote two of them is the failure §9.1's first rule
    # exists to make impossible.
    username = await signed_in(panel)
    await seed_ticket(panel)

    # Act
    response = await post(
        panel,
        STATUS_URL,
        {"expectedStatus": SupportTicketStatus.NEW.value, "toStatus": "in_progress"},
    )

    # Assert
    assert response.status_code == 200
    assert response.json()["ticket"]["status"] == SupportTicketStatus.IN_PROGRESS.value
    assert (await ticket_row(panel)).status is SupportTicketStatus.IN_PROGRESS

    events = await events_of(panel)
    assert [event.kind for event in events] == [SupportTicketEventKind.STATUS_CHANGE]
    # Both ends of the move, because "it went to in_progress" and "it went to in_progress FROM
    # resolved" are different events and the second is a reopened ticket.
    assert events[0].from_status is SupportTicketStatus.NEW
    assert events[0].to_status is SupportTicketStatus.IN_PROGRESS
    assert events[0].author_kind is SupportAuthorKind.OPERATOR
    assert events[0].author_admin_username == username

    rows = await audit_rows(panel)
    assert [row.action for row in rows] == [AuditAction.TICKET_STATUS]
    assert rows[0].subject_type == TICKET_SUBJECT_TYPE
    assert rows[0].subject_id == str(TICKET_ID)
    assert rows[0].actor_username == username
    assert rows[0].reason_code is SUPPORT_REASON
    # Columns, never their values. ``record_count`` is None because nobody was messaged.
    assert rows[0].field_names == ["support_tickets.status"]
    assert rows[0].record_count is None


async def test_a_move_against_a_stale_expectation_is_a_409_and_changes_nothing(
    panel: Panel,
) -> None:
    # Arrange — THE assertion this file exists for. A test that only drove the winning side
    # could not tell a conditional write from an unconditional one, which is exactly the bug
    # that lets two operators' drags both "succeed".
    await signed_in(panel)
    await seed_ticket(panel, status=SupportTicketStatus.WAITING)

    # Act — the SPA drew this card as ``new``; a staffer in the group has since moved it.
    response = await post(
        panel,
        STATUS_URL,
        {"expectedStatus": SupportTicketStatus.NEW.value, "toStatus": "in_progress"},
    )

    # Assert
    assert response.status_code == 409
    assert response.json()["error"]["code"] == AdminErrorCode.CONFLICT.value
    # The status IS published, unlike the id in the 404: an operator who lost the race needs to
    # know what it lost to.
    assert response.json()["error"]["details"]["status"] == SupportTicketStatus.WAITING.value
    assert (await ticket_row(panel)).status is SupportTicketStatus.WAITING
    assert await events_of(panel) == []
    assert await audit_rows(panel) == []


async def test_an_illegal_move_is_refused_before_anything_is_read(panel: Panel) -> None:
    # Arrange — ``RESOLVED -> WAITING`` is not in the grammar. The schema refuses it, the
    # writer would refuse it too, and both read one mapping so they cannot disagree.
    await signed_in(panel)
    await seed_ticket(panel, status=SupportTicketStatus.RESOLVED, resolved_at=NOW)

    # Act
    response = await post(
        panel,
        STATUS_URL,
        {"expectedStatus": SupportTicketStatus.RESOLVED.value, "toStatus": "waiting"},
    )

    # Assert
    assert response.status_code == 422
    assert (await ticket_row(panel)).status is SupportTicketStatus.RESOLVED


async def test_a_move_to_the_status_it_is_already_in_is_refused(panel: Panel) -> None:
    # Arrange — nothing moves to itself, so a second ``✋ Claim`` press is a refusal rather
    # than a duplicate event on somebody's timeline.
    await signed_in(panel)
    await seed_ticket(panel, status=SupportTicketStatus.IN_PROGRESS)

    # Act
    response = await post(
        panel,
        STATUS_URL,
        {"expectedStatus": "in_progress", "toStatus": "in_progress"},
    )

    # Assert
    assert response.status_code == 422
    assert await events_of(panel) == []


async def test_resolving_stamps_the_clock_and_reopening_never_clears_it(panel: Panel) -> None:
    # Arrange — ``resolved_at`` records that this ticket was once considered finished, which is
    # the most useful thing to know about one that came back. A column a reopen erased would
    # make repeat complaints invisible.
    await signed_in(panel)
    await seed_ticket(panel, status=SupportTicketStatus.IN_PROGRESS)

    # Act
    await post(panel, STATUS_URL, {"expectedStatus": "in_progress", "toStatus": "resolved"})
    resolved_at = (await ticket_row(panel)).resolved_at
    await post(panel, STATUS_URL, {"expectedStatus": "resolved", "toStatus": "in_progress"})

    # Assert
    reopened = await ticket_row(panel)
    assert resolved_at is not None
    assert reopened.status is SupportTicketStatus.IN_PROGRESS
    assert reopened.resolved_at == resolved_at


async def test_a_move_asks_the_worker_to_re_render_the_card(panel: Panel) -> None:
    # Arrange — the card in the support group is the one copy of this ticket the admin process
    # cannot reach (D10), and a board that says ``resolved`` beside a card that says ``🆕 New``
    # is two staff working from two truths. Asserted on the job's ARGUMENTS, because a counter
    # would pass on the wrong ticket id.
    await signed_in(panel)
    await seed_ticket(panel)

    # Act
    await post(panel, STATUS_URL, {"expectedStatus": "new", "toStatus": "waiting"})

    # Assert
    assert [call.job for call in panel.queue.calls] == [SUPPORT_CARD_JOB_NAME]
    assert panel.queue.calls[0].ticket_id == TICKET_ID
    # The ticket and nothing else: the worker re-reads the row, so a payload carrying the
    # status would repaint the card with whatever was true when the job was enqueued.
    assert panel.queue.calls[0].arguments == (str(TICKET_ID),)


async def test_a_refused_move_is_not_enqueued(panel: Panel) -> None:
    # Arrange — the enqueue is the LAST statement of the handler, after the 409. A card sync
    # for a move that did not happen would repaint a card that was already correct, and would
    # make the recorded-call assertions above meaningless.
    await signed_in(panel)
    await seed_ticket(panel, status=SupportTicketStatus.RESOLVED, resolved_at=NOW)

    # Act
    await post(panel, STATUS_URL, {"expectedStatus": "new", "toStatus": "in_progress"})

    # Assert
    assert panel.queue.calls == []


async def test_a_deployment_with_no_worker_tells_the_operator_and_keeps_the_move() -> None:
    # Arrange — SUPERSEDES "refuses the move and keeps the status". The enqueue used to run
    # inside the request's transaction so that a dead worker could roll the whole action back;
    # that ordering is precisely what let a live worker dispatch a job against rows nothing
    # else could see yet, so the commit now comes first and the rollback is gone. What is left
    # is the half that was always the point: the operator is TOLD, with a 503, and the state
    # they can see says what really happened.
    async with open_panel(refusing=True) as panel:
        await signed_in(panel)
        await seed_ticket(panel)

        # Act
        response = await post(panel, STATUS_URL, {"expectedStatus": "new", "toStatus": "waiting"})

        # Assert — 503 and not 500: a missing worker is an unavailable dependency. The move
        # stands, and so does its evidence; the group card is one status behind until the next
        # action on this ticket repaints it, which is the visible half of the trade.
        assert response.status_code == 503
        assert (await ticket_row(panel)).status is SupportTicketStatus.WAITING
        assert [event.kind for event in await events_of(panel)] == [
            SupportTicketEventKind.STATUS_CHANGE
        ]
        assert [row.action for row in await audit_rows(panel)] == [AuditAction.TICKET_STATUS]


# ---------------------------------------------------------------------------
# Assigning
# ---------------------------------------------------------------------------
async def test_assigning_records_the_holder_without_moving_the_ticket(panel: Panel) -> None:
    # Arrange — in the group ``✋ Claim`` is both acts because a staffer has one button. Here
    # the operator has the column controls in front of them, and a hidden move would write a
    # ``status_change`` nobody asked for and race the explicit one.
    await signed_in(panel)
    await seed_ticket(panel)

    # Act
    response = await post(panel, ASSIGN_URL, {"adminUsername": "dilnoza"})

    # Assert
    assert response.status_code == 200
    row = await ticket_row(panel)
    assert row.assigned_admin_username == "dilnoza"
    assert row.assigned_at is not None
    assert row.status is SupportTicketStatus.NEW
    assert [event.kind for event in await events_of(panel)] == [SupportTicketEventKind.ASSIGNED]
    assert [audit.action for audit in await audit_rows(panel)] == [AuditAction.TICKET_ASSIGN]


async def test_a_ticket_can_be_handed_from_one_operator_to_another(panel: Panel) -> None:
    # Arrange — unconditional on the current holder, unlike every other write here. Handing a
    # ticket over is ordinary work, so a reassignment must not be refused because somebody
    # claimed it first; the append-only events are what keep the history.
    await signed_in(panel)
    await seed_ticket(panel, assigned_admin_username="dilnoza", assigned_at=NOW)

    # Act
    response = await post(panel, ASSIGN_URL, {"adminUsername": "ozod"})

    # Assert
    assert response.status_code == 200
    assert (await ticket_row(panel)).assigned_admin_username == "ozod"
    assert len(await events_of(panel)) == 1


async def test_an_assignee_that_could_never_name_an_operator_is_a_422(panel: Panel) -> None:
    # Arrange — the shape is checked and the EXISTENCE deliberately is not: the column is
    # denormalised with no foreign key precisely so a deactivated or renamed operator does not
    # rewrite who worked a queue, and a validity check at write time would be a rule the column
    # cannot keep tomorrow.
    await signed_in(panel)
    await seed_ticket(panel)

    # Act
    response = await post(panel, ASSIGN_URL, {"adminUsername": "Not A Username!"})

    # Assert
    assert response.status_code == 422
    assert (await ticket_row(panel)).assigned_admin_username is None


# ---------------------------------------------------------------------------
# Notes — the action that reaches nobody
# ---------------------------------------------------------------------------
async def test_a_note_lands_on_the_timeline_and_enqueues_nothing(panel: Panel) -> None:
    # Arrange — the only one of the four actions that asks the worker for nothing. A note
    # reaches nobody and alters no rendered surface, so a card sync for it would be an edit to
    # a Telegram message whose text is identical.
    username = await signed_in(panel)
    await seed_ticket(panel)

    # Act
    response = await post(panel, NOTES_URL, {"body": "Vendor confirms the pronunciation bug"})

    # Assert
    assert response.status_code == 200
    events = await events_of(panel)
    assert [event.kind for event in events] == [SupportTicketEventKind.NOTE]
    assert events[0].body == "Vendor confirms the pronunciation bug"
    assert events[0].author_admin_username == username
    assert events[0].relayed_at is None
    assert panel.queue.calls == []
    # The audit row names the COLUMN and never the prose: copying operator text into
    # ``admin_audit_log`` would put it in the one table the purge cannot reach.
    rows = await audit_rows(panel)
    assert [row.action for row in rows] == [AuditAction.TICKET_NOTE]
    assert rows[0].field_names == ["support_ticket_events.body"]
    assert rows[0].reason_text is None


async def test_a_blank_note_is_refused(panel: Panel) -> None:
    # Arrange — ``min_length=1`` alone accepts a single space, which reaches a reader as an
    # empty bubble. Nothing is trimmed on the way in; what is stored is what was typed.
    await signed_in(panel)
    await seed_ticket(panel)

    # Act
    response = await post(panel, NOTES_URL, {"body": "   "})

    # Assert
    assert response.status_code == 422
    assert await events_of(panel) == []


async def test_an_over_long_body_is_a_422_naming_the_field_and_not_an_integrity_error(
    panel: Panel,
) -> None:
    # Arrange — THE reason the column bounds are restated as pydantic constraints. This suite
    # runs on in-memory SQLite, which stores a 9 000-character string in a ``String(4096)``
    # column without complaint; on Postgres the same request is an ``IntegrityError`` raised
    # from inside a transaction that has already written an event row and an audit row.
    await signed_in(panel)
    await seed_ticket(panel)

    # Act
    response = await post(panel, REPLY_URL, {"body": "x" * (MAX_TICKET_BODY_CHARS + 1)})

    # Assert
    assert response.status_code == 422
    assert await events_of(panel) == []
    assert panel.queue.calls == []


async def test_an_unknown_field_in_a_body_is_refused(panel: Panel) -> None:
    # Arrange — ``ApiModel`` sets ``extra="forbid"``, which is what stops a stale SPA build
    # from appearing to send a field the server silently ignores.
    await signed_in(panel)
    await seed_ticket(panel)

    # Act
    response = await post(panel, NOTES_URL, {"body": "Fine", "notifyCustomer": True})

    # Assert
    assert response.status_code == 422
    assert await events_of(panel) == []


# ---------------------------------------------------------------------------
# Replies — the one action that leaves the building
# ---------------------------------------------------------------------------
async def test_a_reply_is_written_unrelayed_and_handed_to_the_worker_by_its_event_id(
    panel: Panel,
) -> None:
    # Arrange — written first, delivered second, and the two are deliberately not the same
    # fact. The row lands with ``relayed_at`` NULL; the worker stamps it when the message
    # actually reaches the customer's private chat.
    await signed_in(panel)
    await seed_ticket(panel)

    # Act
    response = await post(panel, REPLY_URL, {"body": "We are re-rendering it now"})

    # Assert
    assert response.status_code == 200
    events = await events_of(panel)
    assert [event.kind for event in events] == [SupportTicketEventKind.REPLY]
    assert events[0].body == "We are re-rendering it now"
    assert events[0].relayed_at is None
    assert response.json()["events"][0]["relayedAt"] is None

    # The seam, on its arguments: THIS event of THIS ticket, and no card sync — the card
    # renders the status and the claim row, and answering a customer changes neither.
    assert [call.job for call in panel.queue.calls] == [SUPPORT_RELAY_JOB_NAME]
    assert panel.queue.calls[0].ticket_id == TICKET_ID
    assert panel.queue.calls[0].arguments == (str(TICKET_ID), str(events[0].id))
    assert panel.queue.calls[0].job_id == f"support:relay:{events[0].id}"


async def test_a_reply_is_the_only_action_whose_audit_row_counts_a_person(panel: Panel) -> None:
    # Arrange — ``recordCount`` means the same thing it means on a broadcast: how many people
    # this authorised a message to. That is what makes "how many customers did we actually
    # answer this month" a SUM over an indexed action filter rather than a count of rows that
    # silently includes every internal note.
    await signed_in(panel)
    await seed_ticket(panel)

    # Act
    await post(panel, NOTES_URL, {"body": "Internal"})
    await post(panel, REPLY_URL, {"body": "External"})

    # Assert
    rows = await audit_rows(panel)
    assert [row.action for row in rows] == [AuditAction.TICKET_NOTE, AuditAction.TICKET_REPLY]
    assert [row.record_count for row in rows] == [None, 1]


async def test_a_reply_does_not_move_the_ticket(panel: Panel) -> None:
    # Arrange — in the support GROUP a reply to the card moves a ``new`` ticket to
    # ``in_progress``, because a staffer in a chat has no other control to press. Stated here
    # as a deliberate difference rather than left as an inconsistency to be discovered.
    await signed_in(panel)
    await seed_ticket(panel)

    # Act
    await post(panel, REPLY_URL, {"body": "On it"})

    # Assert
    assert (await ticket_row(panel)).status is SupportTicketStatus.NEW
    assert [event.kind for event in await events_of(panel)] == [SupportTicketEventKind.REPLY]


async def test_a_deployment_with_no_worker_says_so_rather_than_answering_silently() -> None:
    # Arrange — SUPERSEDES "does not leave a reply looking answered". The reply is committed
    # before the enqueue is attempted (see the router's ``_committed``), so a refused enqueue
    # can no longer take the row back with it. The row it leaves is not a lie: ``relayedAt``
    # is null, which the timeline renders as composed-and-not-delivered — exactly what
    # happened — and the 503 is what tells the operator that no job is coming, which is the
    # one thing the row itself cannot say.
    async with open_panel(refusing=True) as panel:
        await signed_in(panel)
        await seed_ticket(panel)

        # Act
        response = await post(panel, REPLY_URL, {"body": "Nobody will ever read this"})

        # Assert
        assert response.status_code == 503
        events = await events_of(panel)
        assert [event.kind for event in events] == [SupportTicketEventKind.REPLY]
        assert events[0].relayed_at is None
        assert [row.action for row in await audit_rows(panel)] == [AuditAction.TICKET_REPLY]


async def test_a_reply_to_an_unknown_ticket_writes_nothing(panel: Panel) -> None:
    # Arrange — the 404 read happens before the append. SQLite enforces no foreign keys in this
    # suite, so without that read an event would be written against a ticket that does not
    # exist and nothing would object.
    await signed_in(panel)

    # Act
    response = await post(
        panel, SUPPORT_TICKET_REPLY_PATH.format(ticket_id=UNKNOWN_ID), {"body": "Hello?"}
    )

    # Assert
    assert response.status_code == 404
    assert await events_of(panel, UNKNOWN_ID) == []
    assert panel.queue.calls == []


# ---------------------------------------------------------------------------
# The seam's ORDERING — committed before the worker is told, not merely written
# ---------------------------------------------------------------------------
class CommitProbeQueue(NullAdminQueue):
    """A queue that asks the WORKER'S question at the moment the worker would be told.

    Every other test in this file asserts what was enqueued. This one asserts *when*, and it
    does so by reading the ticket from a SESSION OF ITS OWN — a second connection, which is
    what an ARQ worker has — at the instant of the enqueue. Under READ COMMITTED (and under
    SQLite's own locking) a row the request has written but not committed is simply absent
    there, which is exactly what the worker saw during the window this probe exists to close.

    A recording double rather than a clock or a commit counter: "how many commits had happened
    by then" is a fact about SQLAlchemy, while "could another transaction see the reply" is the
    fact the customer's answer depends on. The subclass overrides only the two ticket methods,
    so everything the other tests assert on — ``calls``, the job ids, the arguments — is still
    the parent's.
    """

    def __init__(self) -> None:
        super().__init__()
        #: Set after the container exists; the queue has to be built before it.
        self.container: AdminContainer | None = None
        #: The ticket's status as another transaction saw it, per enqueue.
        self.visible_status: list[SupportTicketStatus | None] = []
        #: The timeline ids another transaction could see, per enqueue.
        self.visible_events: list[tuple[UUID, ...]] = []

    async def enqueue_support_card_sync(self, ticket_id: UUID) -> Any:
        await self._look(ticket_id)
        return await super().enqueue_support_card_sync(ticket_id)

    async def enqueue_support_reply(self, ticket_id: UUID, *, event_id: UUID) -> Any:
        await self._look(ticket_id)
        return await super().enqueue_support_reply(ticket_id, event_id=event_id)

    async def _look(self, ticket_id: UUID) -> None:
        assert self.container is not None, "the probe was never given its container"
        async with self.container.session_factory() as db:
            detail = await get_ticket(db, ticket_id)
        self.visible_status.append(None if detail is None else detail.ticket.status)
        self.visible_events.append(() if detail is None else tuple(e.id for e in detail.events))


@asynccontextmanager
async def open_probed_panel(tmp_path: Path) -> AsyncIterator[Panel]:
    """A panel on a FILE database, because the probe needs a second real connection.

    The rest of this package runs on ``sqlite+aiosqlite:///:memory:``, which SQLAlchemy serves
    from a ``StaticPool`` — one connection shared by every session in the process. That is
    right for every other test here and useless for this one: with a single connection an
    uncommitted row is visible to the "other" session, so the race this file is closing cannot
    be reproduced at all. A file URL gets a pool that hands out separate connections, which is
    the only configuration in which "committed" and "written" are different facts.
    """
    probe = CommitProbeQueue()
    async with (
        open_container(
            make_settings(database_url=f"sqlite+aiosqlite:///{tmp_path / 'panel.db'}"),
            FakeRedis(),
            MemoryRateLimits(),
            probe,
        ) as container,
        open_client(container) as http,
    ):
        probe.container = container
        yield Panel(container=container, http=http, queue=probe)


async def test_a_reply_is_committed_before_the_worker_is_told_to_relay_it(
    tmp_path: Path,
) -> None:
    # Arrange — THE regression, and it is a race rather than a branch. The handler used to
    # enqueue while the ``reply`` row was still uncommitted: ``get_db_session`` commits on a
    # clean exit of the REQUEST, and ARQ polls every half second, so a worker really did
    # sometimes open its own session inside that window and find no such row. It then logged
    # "no timeline row answers this event id" and completed SUCCESSFULLY — the customer was
    # never answered and the timeline showed the reply composed with ``relayedAt`` null, which
    # an operator reads as "Telegram refused" and does not resend.
    async with open_probed_panel(tmp_path) as panel:
        await signed_in(panel)
        await seed_ticket(panel)

        # Act
        response = await post(panel, REPLY_URL, {"body": "We are re-rendering it now"})
        assert response.status_code == 200

        # Assert — the event the worker was handed was visible to another transaction at the
        # moment it was handed over. Asserted as the id, not as a count: a probe that saw
        # "some timeline" would pass on the OPENED row alone.
        probe = panel.queue
        assert isinstance(probe, CommitProbeQueue)
        events = await events_of(panel)
        assert [event.kind for event in events] == [SupportTicketEventKind.REPLY]
        assert probe.visible_events == [(events[0].id,)]
        assert probe.calls[0].arguments == (str(TICKET_ID), str(events[0].id))


async def test_a_move_is_committed_before_the_worker_is_told_to_repaint_the_card(
    tmp_path: Path,
) -> None:
    # Arrange — the same race, one job along, and its symptom is quieter. The card sync
    # re-reads the ticket and renders from the row; a job that overtook the commit rendered
    # the PRE-MOVE status, and Telegram then answered "message is not modified", which
    # ``_edit_card`` swallows at INFO by design. The card froze at the old status, the board
    # showed the new one, and nothing anywhere said so.
    async with open_probed_panel(tmp_path) as panel:
        await signed_in(panel)
        await seed_ticket(panel)

        # Act
        response = await post(panel, STATUS_URL, {"expectedStatus": "new", "toStatus": "waiting"})
        assert response.status_code == 200

        # Assert — the status another transaction could see at enqueue time is the one the
        # operator moved it to, not the one they moved it from.
        probe = panel.queue
        assert isinstance(probe, CommitProbeQueue)
        assert probe.visible_status == [SupportTicketStatus.WAITING]


# ---------------------------------------------------------------------------
# The two cells
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("role", EVERY_ROLE, ids=str)
async def test_every_role_may_read_the_queue(panel: Panel, role: AdminRole) -> None:
    # Arrange — ``SUPPORT_READ`` is ``M`` at all four roles for ``BROADCAST_READ``'s reason:
    # the queue is what the panel exists to show, and hiding it from the role whose whole job
    # is looking makes "who is waiting?" a question only the people answering can answer.
    await signed_in(panel, role=role)
    await seed_ticket(panel)

    # Act / Assert
    assert (await panel.http.get(SUPPORT_TICKETS_PATH)).status_code == 200
    assert (await panel.http.get(SUPPORT_BOARD_PATH)).status_code == 200
    assert (await panel.http.get(TICKET_URL)).status_code == 200


@pytest.mark.parametrize("role", WRITE_ROLES, ids=str)
async def test_the_three_write_roles_can_answer_a_customer(panel: Panel, role: AdminRole) -> None:
    # Arrange — SUPPORT being on this list is the entire reason ``SUPPORT_WRITE`` is its own
    # row. A matrix in which the role named SUPPORT may read the support queue and not reply to
    # it describes a person who can watch the work and not do it.
    await signed_in(panel, role=role)
    await seed_ticket(panel)

    # Act
    response = await post(panel, REPLY_URL, {"body": "We are looking into it"})

    # Assert
    assert response.status_code == 200, role


@pytest.mark.parametrize("role", READ_ONLY_ROLES, ids=str)
async def test_a_viewer_is_refused_flat_rather_than_prompted(panel: Panel, role: AdminRole) -> None:
    # Arrange — FORBIDDEN and not STEP_UP_REQUIRED. No grant would ever help a VIEWER here, and
    # an SPA that opened a re-authentication box at somebody permanently ineligible is the
    # confusion the two decisions are kept apart to prevent.
    await signed_in(panel, role=role)
    await seed_ticket(panel)

    # Act
    response = await post(panel, REPLY_URL, {"body": "Not mine to send"})

    # Assert
    assert response.status_code == 403
    assert response.json()["error"]["code"] == AdminErrorCode.FORBIDDEN.value
    assert await events_of(panel) == []
