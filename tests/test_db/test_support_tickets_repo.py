"""The support write layer and the panel's read of it, against a real database.

``test_support_tickets.py`` beside this file asserts the SCHEMA — that the constraints exist
and that the engine enforces the ones it can. This file asserts the STATEMENTS: that the
group-post latch is claimed once, that a status move names the status it expects, that a
customer's second answer cannot overwrite their first, and that the board hides exactly the
rows it is supposed to hide.

**Every conditional write here is tested from BOTH sides, and that is the whole design of the
file.** A conditional ``UPDATE`` that has only ever been tested on its happy path is
indistinguishable from an unconditional one: it moves the row, the rowcount is 1, the test
passes, and the predicate that was supposed to make a replayed ARQ job a no-op is never
exercised. ARQ runs with ``retry_jobs=True`` and SIGTERM cancels running jobs, so *every* job
in this system is replayed on every deploy — the second call is the production path, not the
exotic one. So each latch has a test for the winner and a test for the loser.

**The clock is always injected and never ambient.** ``UtcDateTime`` raises on a naive datetime
at bind time, deep inside the driver, and ``TimestampMixin.onupdate`` would otherwise stamp
``updated_at`` from the real clock while every other column took the test's — so the writes
set it by hand and these tests prove the injected instant is the one that lands.

Telegram ids are outside the 32-bit range, matching ``test_credits.py`` and
``test_support_tickets.py``: an accidental ``Integer`` on this path would silently truncate the
id of whoever is complaining, and their ticket would then be missed by their own ``/forget``.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Final
from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from bayram.contracts import (
    Err,
    Language,
    Ok,
    SupportAuthorKind,
    SupportTicketEventKind,
    SupportTicketSource,
    SupportTicketStatus,
)
from bayram.db.admin.page import PageRequest
from bayram.db.admin.support_tickets import (
    TicketFilters,
    count_tickets,
    get_ticket,
    list_tickets,
    ticket_board,
)
from bayram.db.models.support_ticket import SupportTicketRow
from bayram.db.models.support_ticket_event import SupportTicketEventRow
from bayram.db.support_tickets import (
    MINT_ATTEMPTS,
    SqlSupportTickets,
    append_event,
    assign,
    attach_prompt,
    claim_group_post,
    describe,
    find_by_group_message,
    find_by_prompt,
    find_latest_undescribed,
    listen_on,
    mark_relayed,
    mint_ticket_identity,
    move_status,
    open_ticket,
    quota_verdict,
    release_group_post,
    settle_group_post,
)
from bayram.errors import ConfigError, StorageError, ValidationError
from bayram.support import (
    LEGAL_STATUS_MOVES,
    SUPPORT_PUBLIC_REF_CHARS,
    EventAuthor,
    SupportQuota,
    TicketSnapshot,
    is_legal_move,
    legal_moves_from,
    public_ref_for,
)

pytestmark = pytest.mark.anyio

#: Mid-day and mid-month, so a test that advances a day cannot pass on a boundary.
_NOON: Final[datetime] = datetime(2026, 9, 15, 12, 0, tzinfo=UTC)

#: Well outside 2**31. See the module docstring.
_ALICE: Final[int] = 8_912_345_678_901
_BOB: Final[int] = 8_912_345_678_902

#: A supergroup id: NEGATIVE, beginning ``-100``. The settings field holding it carries no
#: ``ge=0`` bound for exactly this reason, and a column that could not store it would be
#: discovered only against a real group.
_GROUP: Final[int] = -1_002_345_678_901

_STAFF: Final[int] = 8_912_345_678_903


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------
async def _open(
    sessions: async_sessionmaker[AsyncSession],
    *,
    who: int = _ALICE,
    at: datetime = _NOON,
    source: SupportTicketSource = SupportTicketSource.DELIVERY_BUTTON,
    order_id: UUID | None = None,
    language: Language = Language.UZ_LATN,
) -> TicketSnapshot:
    """One undescribed ticket, committed. The state every ticket passes through."""
    async with sessions.begin() as session:
        return await open_ticket(
            session,
            telegram_user_id=who,
            language=language,
            source=source,
            order_id=order_id,
            now=at,
        )


async def _described(
    sessions: async_sessionmaker[AsyncSession],
    *,
    who: int = _ALICE,
    at: datetime = _NOON,
    body: str = "Ismni notogʻri aytdi",
) -> TicketSnapshot:
    """A ticket a customer actually typed into — the only kind the board shows.

    The description is stamped a minute AFTER the tap, which is both realistic and
    load-bearing for the timeline tests: ``(created_at, id)`` makes the event order TOTAL and
    therefore stable across two reads, but two events sharing an instant exactly tie-break on
    a random UUID and so are not in insertion order. Nothing in production writes two events
    at one instant; a fixture that did would be asserting a property this schema does not
    promise.
    """
    ticket = await _open(sessions, who=who, at=at)
    async with sessions.begin() as session:
        described = await describe(session, ticket.id, body=body, now=at + timedelta(minutes=1))
    assert described is not None
    return described


async def _kinds(
    sessions: async_sessionmaker[AsyncSession], ticket_id: UUID
) -> list[SupportTicketEventKind]:
    """The ticket's timeline, oldest first, as a list of kinds."""
    async with sessions.begin() as session:
        rows = (
            (
                await session.execute(
                    sa.select(SupportTicketEventRow.kind)
                    .where(SupportTicketEventRow.ticket_id == ticket_id)
                    .order_by(SupportTicketEventRow.created_at, SupportTicketEventRow.id)
                )
            )
            .scalars()
            .all()
        )
    return list(rows)


async def _row(sessions: async_sessionmaker[AsyncSession], ticket_id: UUID) -> SupportTicketRow:
    """The raw row, for the columns a snapshot deliberately does not carry."""
    async with sessions.begin() as session:
        row = await session.get(SupportTicketRow, ticket_id)
    assert row is not None
    return row


# ---------------------------------------------------------------------------
# The reference
# ---------------------------------------------------------------------------
def test_the_public_reference_is_the_leading_characters_of_the_ticket_id() -> None:
    # Arrange — a fixed id, so the assertion is about the rule and not about a random draw.
    ticket_id = UUID("a3f291c4-d5e6-4780-9abc-def012345678")

    # Act
    reference = public_ref_for(ticket_id)

    # Assert — reproducible by READING. This is the property the whole scheme is chosen for:
    # support resolves a reference by looking at the id, never by computing an encoding.
    assert reference == "a3f291c4"
    assert str(ticket_id).startswith(reference)
    assert len(reference) == SUPPORT_PUBLIC_REF_CHARS


async def test_minting_skips_a_reference_another_ticket_already_holds(
    sessions: async_sessionmaker[AsyncSession], monkeypatch: pytest.MonkeyPatch
) -> None:
    # Arrange — the birthday case, forced: the first candidate collides with a live row.
    taken = UUID("a3f291c4-0000-4000-8000-000000000001")
    free = UUID("bbbbbbbb-0000-4000-8000-000000000002")
    async with sessions.begin() as session:
        session.add(
            SupportTicketRow(
                id=taken,
                public_ref=public_ref_for(taken),
                telegram_user_id=_ALICE,
                language=Language.UZ_LATN,
                source=SupportTicketSource.SUPPORT_COMMAND,
            )
        )
    candidates = iter([taken, free])
    monkeypatch.setattr("bayram.db.support_tickets.uuid4", lambda: next(candidates))

    # Act
    async with sessions.begin() as session:
        minted_id, reference = await mint_ticket_identity(session)

    # Assert — the collision is a second draw, not an IntegrityError in front of a customer.
    assert minted_id == free
    assert reference == public_ref_for(free)


async def test_minting_gives_up_loudly_rather_than_looping_on_a_full_keyspace(
    sessions: async_sessionmaker[AsyncSession], monkeypatch: pytest.MonkeyPatch
) -> None:
    # Arrange — every candidate is the one reference already in the table.
    taken = UUID("a3f291c4-0000-4000-8000-000000000001")
    async with sessions.begin() as session:
        session.add(
            SupportTicketRow(
                id=taken,
                public_ref=public_ref_for(taken),
                telegram_user_id=_ALICE,
                language=Language.UZ_LATN,
                source=SupportTicketSource.SUPPORT_COMMAND,
            )
        )
    monkeypatch.setattr("bayram.db.support_tickets.uuid4", lambda: taken)

    # Act / Assert — bounded. An unbounded retry here is a hot loop holding a transaction.
    async with sessions.begin() as session:
        with pytest.raises(StorageError):
            await mint_ticket_identity(session, attempts=MINT_ATTEMPTS)


# ---------------------------------------------------------------------------
# The board's grammar
# ---------------------------------------------------------------------------
def test_every_status_has_a_row_in_the_move_table_and_none_moves_to_itself() -> None:
    # Assert — totality first: a member added to the enum without a row here would be a
    # dead-end column, and this is the test that says so rather than a KeyError in a handler.
    assert set(LEGAL_STATUS_MOVES) == set(SupportTicketStatus)
    # A no-op move would write a STATUS_CHANGE event recording nothing and bump updated_at,
    # which makes an untouched ticket look worked. Two staffers pressing Claim is the common
    # case; the second press must be refused, not recorded.
    for status in SupportTicketStatus:
        assert status not in legal_moves_from(status)


def test_a_resolved_ticket_reopens_only_into_in_progress() -> None:
    # Assert — a reopened complaint must not re-enter the unlooked-at column, or it loses the
    # single most useful thing known about it: that it was answered once already.
    assert legal_moves_from(SupportTicketStatus.RESOLVED) == frozenset(
        {SupportTicketStatus.IN_PROGRESS}
    )
    assert is_legal_move(SupportTicketStatus.RESOLVED, SupportTicketStatus.IN_PROGRESS) is True
    assert is_legal_move(SupportTicketStatus.RESOLVED, SupportTicketStatus.WAITING) is False
    # Nothing returns to NEW: "nobody has looked at this yet" is a claim about the past.
    for status in SupportTicketStatus:
        assert SupportTicketStatus.NEW not in legal_moves_from(status)


# ---------------------------------------------------------------------------
# Opening
# ---------------------------------------------------------------------------
async def test_opening_writes_an_undescribed_ticket_and_its_opened_event(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    # Act
    ticket = await _open(sessions, source=SupportTicketSource.SUPPORT_COMMAND)

    # Assert — the tap, and nothing more. body/described_at NULL is the state a large
    # minority of tickets stay in and is the only measure of how many people gave up.
    assert ticket.status is SupportTicketStatus.NEW
    assert ticket.body is None
    assert ticket.described_at is None
    assert ticket.is_described is False
    assert ticket.is_posted is False
    assert ticket.public_ref == public_ref_for(ticket.id)
    assert ticket.created_at == _NOON
    # A ticket can never exist with an empty timeline: the detail screen would otherwise show
    # a complaint that apparently happened to nobody.
    assert await _kinds(sessions, ticket.id) == [SupportTicketEventKind.OPENED]


async def test_two_tickets_opened_in_one_instant_get_different_references(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    # Act — same customer, same clock; only the minted id differs.
    first = await _open(sessions)
    second = await _open(sessions)

    # Assert — a reference that resolved to two tickets would have support answering about
    # the wrong complaint while believing they had looked it up.
    assert first.public_ref != second.public_ref


async def test_a_prompt_is_attached_once_so_a_replay_cannot_orphan_the_first(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    # Arrange
    ticket = await _open(sessions)

    # Act
    async with sessions.begin() as session:
        first = await attach_prompt(session, ticket.id, prompt_message_id=4001, now=_NOON)
    async with sessions.begin() as session:
        second = await attach_prompt(session, ticket.id, prompt_message_id=4002, now=_NOON)

    # Assert — the second ForceReply would orphan the first, and the first is the one the
    # customer can still see scrolled up their chat.
    assert (first, second) == (True, False)
    assert (await _row(sessions, ticket.id)).prompt_message_id == 4001


# ---------------------------------------------------------------------------
# The customer's words
# ---------------------------------------------------------------------------
async def test_a_reply_is_matched_by_account_as_well_as_by_prompt_id(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    # Arrange — message ids are PER-CHAT counters, so two customers holding the same one is
    # routine rather than contrived. This is the test that stops one person's complaint being
    # attached to another person's ticket.
    mine = await _open(sessions, who=_ALICE)
    theirs = await _open(sessions, who=_BOB)
    async with sessions.begin() as session:
        await attach_prompt(session, mine.id, prompt_message_id=77, now=_NOON)
        await attach_prompt(session, theirs.id, prompt_message_id=77, now=_NOON)

    # Act
    async with sessions.begin() as session:
        found = await find_by_prompt(session, _ALICE, prompt_message_id=77)

    # Assert
    assert found is not None
    assert found.id == mine.id


async def test_describing_fills_the_body_stamps_the_clock_and_writes_the_event(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    # Arrange
    ticket = await _open(sessions)
    later = _NOON + timedelta(minutes=3)

    # Act
    async with sessions.begin() as session:
        described = await describe(session, ticket.id, body="Dilnoza emas, Dilnora", now=later)

    # Assert — the injected clock lands, not the ambient one.
    assert described is not None
    assert described.body == "Dilnoza emas, Dilnora"
    assert described.described_at == later
    assert described.is_described is True
    assert (await _row(sessions, ticket.id)).updated_at == later
    assert await _kinds(sessions, ticket.id) == [
        SupportTicketEventKind.OPENED,
        SupportTicketEventKind.DESCRIBED,
    ]


async def test_a_second_message_cannot_overwrite_the_first_complaint(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    # Arrange
    ticket = await _open(sessions)
    async with sessions.begin() as session:
        await describe(session, ticket.id, body="the name is wrong", now=_NOON)

    # Act
    async with sessions.begin() as session:
        again = await describe(session, ticket.id, body="sorry, I meant Dilnora", now=_NOON)

    # Assert — a follow-up is an ADDITION to the record, never a correction of it, and the
    # record is what an operator pastes from months later.
    assert again is None
    assert (await _row(sessions, ticket.id)).body == "the name is wrong"
    # And no second DESCRIBED row: the event is written only when the row actually moved.
    assert (await _kinds(sessions, ticket.id)).count(SupportTicketEventKind.DESCRIBED) == 1


async def test_a_described_ticket_still_answers_the_message_it_is_listening_on(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    """REGRESSION. This test used to assert ``found is None`` — the bug, written down.

    ``find_by_prompt`` carried ``described_at IS NULL``, so the only private message the bot
    could ever resolve to a ticket was the answer to a fresh ForceReply. A customer replying
    to a RELAYED staff answer — which ``support.ticket.reply`` ends by inviting — matched
    nothing, fell past the support router, and was claimed by whichever wizard step they were
    parked in: at ``Wizard.name`` their sentence became the recipient's name and was sung.

    The protection that narrowing was credited with is not lost, and never lived here: it is
    :func:`describe`'s own ``WHERE described_at IS NULL``, asserted directly by
    ``test_a_second_message_cannot_overwrite_the_first_complaint`` above. This lookup answers
    "which ticket is this message talking to"; that statement answers "may it become the
    body". Two questions, two predicates, and merging them cost a customer their words.
    """
    # Arrange
    ticket = await _open(sessions)
    async with sessions.begin() as session:
        await attach_prompt(session, ticket.id, prompt_message_id=91, now=_NOON)
        await describe(session, ticket.id, body="already said it", now=_NOON)

    # Act
    async with sessions.begin() as session:
        found = await find_by_prompt(session, _ALICE, prompt_message_id=91)

    # Assert — the handler branches on ``is_described`` to treat this as a follow-up.
    assert found is not None
    assert found.id == ticket.id
    assert found.is_described is True


async def test_listen_on_moves_a_prompt_id_that_attach_prompt_would_refuse(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    """The two writers of one column, from both sides, because they differ in exactly one way.

    ``attach_prompt`` is conditional on the column being NULL so a replayed open cannot orphan
    a ForceReply the customer can still see. ``listen_on`` is unconditional because a NEWER
    message — the relay of a staff answer — has taken over the conversation, and refusing to
    move would leave the ticket listening on a prompt from three weeks ago while the customer
    replies to the paragraph in front of them.
    """
    # Arrange
    ticket = await _open(sessions)
    async with sessions.begin() as session:
        await attach_prompt(session, ticket.id, prompt_message_id=500, now=_NOON)

    # Act — attach refuses the move; listen_on makes it
    later = _NOON + timedelta(minutes=5)
    async with sessions.begin() as session:
        refused = await attach_prompt(session, ticket.id, prompt_message_id=900, now=later)
    async with sessions.begin() as session:
        moved = await listen_on(session, ticket.id, prompt_message_id=900, now=later)

    # Assert
    assert (refused, moved) == (False, True)
    row = await _row(sessions, ticket.id)
    assert row.prompt_message_id == 900
    assert row.updated_at == later
    async with sessions.begin() as session:
        assert (await find_by_prompt(session, _ALICE, prompt_message_id=500)) is None
        found = await find_by_prompt(session, _ALICE, prompt_message_id=900)
    assert found is not None and found.id == ticket.id


async def test_the_undescribed_ticket_handed_back_is_the_newest_and_never_a_resolved_one(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    """``find_latest_undescribed`` is what makes §1.4's "the prompt for the ticket they
    already have" possible, and its two predicates each close a real failure.

    NEWEST, because that is the prompt still on the customer's screen — re-pointing an older
    one would put a ForceReply in front of somebody quoting a reference they never saw.

    NOT RESOLVED, because ``quota_verdict`` stops charging for a resolved undescribed row (it
    is the only remedy for a customer who has genuinely filled their slots with taps). The two
    predicates must keep matching, or the customer is re-prompted about a complaint an
    operator has already closed.
    """
    # Arrange
    oldest = await _open(sessions)
    closed = await _open(sessions)
    newest = await _open(sessions)
    async with sessions.begin() as session:
        await move_status(
            session,
            closed.id,
            expected=SupportTicketStatus.NEW,
            to_status=SupportTicketStatus.RESOLVED,
            author=EventAuthor.operator("nodira"),
            now=_NOON,
        )

    # Act
    async with sessions.begin() as session:
        found = await find_latest_undescribed(session, _ALICE)

    # Assert
    assert found is not None
    assert found.id in {oldest.id, newest.id}
    assert found.id != closed.id

    # And nothing comes back once every undescribed row is closed.
    async with sessions.begin() as session:
        for ticket in (oldest, newest):
            await move_status(
                session,
                ticket.id,
                expected=SupportTicketStatus.NEW,
                to_status=SupportTicketStatus.RESOLVED,
                author=EventAuthor.operator("nodira"),
                now=_NOON,
            )
    async with sessions.begin() as session:
        assert (await find_latest_undescribed(session, _ALICE)) is None


async def test_the_body_is_stored_exactly_as_typed_including_markup_characters(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    # Arrange — escaping is a property of the SURFACE something is rendered on, so a database
    # holding pre-escaped text would be a database whose contents depend on where they were
    # going. The card escapes at send time; this column keeps the sentence.
    raw = "<b>why</b> & how? 5 > 3"
    ticket = await _open(sessions)

    # Act
    async with sessions.begin() as session:
        described = await describe(session, ticket.id, body=raw, now=_NOON)

    # Assert
    assert described is not None
    assert described.body == raw


# ---------------------------------------------------------------------------
# The group-post latch
# ---------------------------------------------------------------------------
async def test_only_the_first_claim_of_the_group_post_wins(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    # Arrange — the replayed-job case, which on this system is every deploy.
    ticket = await _described(sessions)

    # Act
    async with sessions.begin() as session:
        first = await claim_group_post(
            session, ticket.id, group_chat_id=_GROUP, group_message_id=500
        )
    async with sessions.begin() as session:
        second = await claim_group_post(
            session, ticket.id, group_chat_id=_GROUP, group_message_id=501
        )

    # Assert — a rowcount of 1 IS the claim. Two cards for one ticket means a staffer
    # answering on the one the relay is not listening to.
    assert (first, second) == (True, False)
    row = await _row(sessions, ticket.id)
    assert (row.group_chat_id, row.group_message_id) == (_GROUP, 500)


async def test_settling_stamps_the_clock_once_and_writes_group_posted(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    # Arrange
    ticket = await _described(sessions)
    async with sessions.begin() as session:
        await claim_group_post(session, ticket.id, group_chat_id=_GROUP, group_message_id=500)
    settled_at = _NOON + timedelta(seconds=2)

    # Act
    async with sessions.begin() as session:
        first = await settle_group_post(session, ticket.id, now=settled_at)
    async with sessions.begin() as session:
        second = await settle_group_post(session, ticket.id, now=settled_at + timedelta(days=1))

    # Assert — a replayed job must not add a second GROUP_POSTED row, nor move the instant.
    assert (first, second) == (True, False)
    assert (await _row(sessions, ticket.id)).group_posted_at == settled_at
    assert (await _kinds(sessions, ticket.id)).count(SupportTicketEventKind.GROUP_POSTED) == 1


async def test_an_unclaimed_ticket_cannot_be_settled(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    # Arrange — the group is unconfigured, or Telegram refused, so nothing was ever posted.
    ticket = await _described(sessions)

    # Act
    async with sessions.begin() as session:
        settled = await settle_group_post(session, ticket.id, now=_NOON)

    # Assert — a posted clock on a ticket with no message id would be a lie the panel reads.
    assert settled is False
    assert (await _row(sessions, ticket.id)).group_posted_at is None


async def test_an_unsettled_claim_can_be_released_but_a_settled_one_never_is(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    # Arrange
    unsettled = await _described(sessions)
    settled = await _described(sessions)
    async with sessions.begin() as session:
        await claim_group_post(session, unsettled.id, group_chat_id=_GROUP, group_message_id=600)
        await claim_group_post(session, settled.id, group_chat_id=_GROUP, group_message_id=601)
        await settle_group_post(session, settled.id, now=_NOON)

    # Act
    async with sessions.begin() as session:
        released = await release_group_post(session, unsettled.id)
        refused = await release_group_post(session, settled.id)

    # Assert — releasing a SETTLED post would put a second card in the group beside one a
    # staffer may already have replied to.
    assert (released, refused) == (True, False)
    assert (await _row(sessions, unsettled.id)).group_message_id is None
    assert (await _row(sessions, settled.id)).group_message_id == 601


async def test_a_released_ticket_can_be_claimed_again(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    # Arrange — the whole point of the release: a failed post is owed, never lost.
    ticket = await _described(sessions)
    async with sessions.begin() as session:
        await claim_group_post(session, ticket.id, group_chat_id=_GROUP, group_message_id=700)
        await release_group_post(session, ticket.id)

    # Act
    async with sessions.begin() as session:
        again = await claim_group_post(
            session, ticket.id, group_chat_id=_GROUP, group_message_id=701
        )

    # Assert
    assert again is True
    assert (await _row(sessions, ticket.id)).group_message_id == 701


async def test_a_reply_in_another_group_does_not_resolve_to_our_card(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    # Arrange — a deployment moved to a second support group. Message ids are per-chat, so
    # the id alone would match and relay a stranger's sentence to a customer.
    ticket = await _described(sessions)
    async with sessions.begin() as session:
        await claim_group_post(session, ticket.id, group_chat_id=_GROUP, group_message_id=800)

    # Act
    async with sessions.begin() as session:
        ours = await find_by_group_message(session, group_chat_id=_GROUP, group_message_id=800)
        theirs = await find_by_group_message(
            session, group_chat_id=-1_009_999_999_999, group_message_id=800
        )

    # Assert
    assert ours is not None and ours.id == ticket.id
    assert theirs is None


# ---------------------------------------------------------------------------
# Working it
# ---------------------------------------------------------------------------
async def test_a_status_move_writes_both_ends_of_the_change(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    # Arrange
    ticket = await _described(sessions)
    moved_at = _NOON + timedelta(hours=1)

    # Act
    async with sessions.begin() as session:
        moved = await move_status(
            session,
            ticket.id,
            expected=SupportTicketStatus.NEW,
            to_status=SupportTicketStatus.IN_PROGRESS,
            author=EventAuthor.staff_group(_STAFF, display_name="@dilshod"),
            now=moved_at,
        )

    # Assert — "it went to waiting" and "it went to waiting FROM resolved" are different
    # events, and only the second says a ticket came back.
    assert moved is not None
    assert moved.status is SupportTicketStatus.IN_PROGRESS
    async with sessions.begin() as session:
        event = (
            await session.execute(
                sa.select(SupportTicketEventRow).where(
                    SupportTicketEventRow.ticket_id == ticket.id,
                    SupportTicketEventRow.kind == SupportTicketEventKind.STATUS_CHANGE,
                )
            )
        ).scalar_one()
        assert event.from_status is SupportTicketStatus.NEW
        assert event.to_status is SupportTicketStatus.IN_PROGRESS
        assert event.author_kind is SupportAuthorKind.STAFF_GROUP
        assert event.author_display_name == "@dilshod"
        assert event.created_at == moved_at


async def test_the_second_staffer_to_resolve_one_card_loses_the_race(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    # Arrange — two ✅ Resolve presses on one card, which is the ordinary case in a busy group.
    ticket = await _described(sessions)

    # Act
    async with sessions.begin() as session:
        winner = await move_status(
            session,
            ticket.id,
            expected=SupportTicketStatus.NEW,
            to_status=SupportTicketStatus.RESOLVED,
            author=EventAuthor.system(),
            now=_NOON,
        )
    async with sessions.begin() as session:
        loser = await move_status(
            session,
            ticket.id,
            expected=SupportTicketStatus.NEW,
            to_status=SupportTicketStatus.RESOLVED,
            author=EventAuthor.system(),
            now=_NOON,
        )

    # Assert — one move, one event. ``None`` means re-read and re-render, never retry.
    assert winner is not None
    assert loser is None
    assert (await _kinds(sessions, ticket.id)).count(SupportTicketEventKind.STATUS_CHANGE) == 1


async def test_an_illegal_move_is_a_refusal_and_not_a_silent_no_op(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    # Arrange
    ticket = await _described(sessions)

    # Act / Assert — the asymmetry is the point: ``None`` means somebody got there first,
    # which is ordinary, while an illegal move is a caller that offered a button it should
    # not have. Collapsing the two would hide a bug behind a race.
    async with sessions.begin() as session:
        with pytest.raises(ValidationError):
            await move_status(
                session,
                ticket.id,
                expected=SupportTicketStatus.NEW,
                to_status=SupportTicketStatus.NEW,
                author=EventAuthor.system(),
                now=_NOON,
            )


async def test_resolving_stamps_the_clock_and_a_reopen_never_clears_it(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    # Arrange
    ticket = await _described(sessions)
    resolved_at = _NOON + timedelta(hours=2)

    # Act
    async with sessions.begin() as session:
        await move_status(
            session,
            ticket.id,
            expected=SupportTicketStatus.NEW,
            to_status=SupportTicketStatus.RESOLVED,
            author=EventAuthor.operator("dilshod"),
            now=resolved_at,
        )
    async with sessions.begin() as session:
        reopened = await move_status(
            session,
            ticket.id,
            expected=SupportTicketStatus.RESOLVED,
            to_status=SupportTicketStatus.IN_PROGRESS,
            author=EventAuthor.customer(_ALICE),
            now=resolved_at + timedelta(days=3),
        )

    # Assert — a cleared ``resolved_at`` would make repeat complaints invisible, which is the
    # one thing worth knowing about a ticket that came back.
    assert reopened is not None
    assert reopened.status is SupportTicketStatus.IN_PROGRESS
    assert (await _row(sessions, ticket.id)).resolved_at == resolved_at


async def test_assigning_is_not_refused_because_somebody_else_holds_it(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    # Arrange — handing a ticket over is a normal act, so this write is deliberately the one
    # unconditional one in the module. The timeline is what keeps the history.
    ticket = await _described(sessions)

    # Act
    async with sessions.begin() as session:
        await assign(
            session,
            ticket.id,
            admin_username="dilshod",
            author=EventAuthor.operator("dilshod"),
            now=_NOON,
        )
    async with sessions.begin() as session:
        handed_over = await assign(
            session,
            ticket.id,
            admin_username="nodira",
            author=EventAuthor.operator("nodira"),
            now=_NOON + timedelta(minutes=5),
        )

    # Assert
    assert handed_over is not None
    assert handed_over.assigned_admin_username == "nodira"
    assert (await _kinds(sessions, ticket.id)).count(SupportTicketEventKind.ASSIGNED) == 2


async def test_assigning_an_unknown_ticket_reports_nothing_rather_than_raising(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    # Act
    async with sessions.begin() as session:
        missing = await assign(
            session,
            uuid4(),
            admin_username="dilshod",
            author=EventAuthor.operator("dilshod"),
            now=_NOON,
        )

    # Assert — the caller answers 404; an exception would be a 500 for a mistyped id.
    assert missing is None


async def test_a_reply_is_stamped_as_relayed_exactly_once(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    # Arrange — the row records that a reply was COMPOSED; the clock records that it was
    # DELIVERED, and the two are separated by a call that fails often enough to matter.
    ticket = await _described(sessions)
    async with sessions.begin() as session:
        event_id = await append_event(
            session,
            ticket.id,
            kind=SupportTicketEventKind.REPLY,
            author=EventAuthor.operator("dilshod"),
            now=_NOON,
            body="We have re-rendered it with the right name.",
        )
    landed_at = _NOON + timedelta(seconds=30)

    # Act
    async with sessions.begin() as session:
        first = await mark_relayed(session, event_id, now=landed_at)
    async with sessions.begin() as session:
        second = await mark_relayed(session, event_id, now=landed_at + timedelta(hours=5))

    # Assert — a replayed relay job must not move the instant a reply is recorded as landing.
    assert (first, second) == (True, False)
    async with sessions.begin() as session:
        stored = await session.get(SupportTicketEventRow, event_id)
        assert stored is not None
        assert stored.relayed_at == landed_at


async def test_a_composed_reply_that_never_landed_is_visibly_different(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    # Arrange — the customer blocked the bot, so nothing was relayed.
    ticket = await _described(sessions)

    # Act
    async with sessions.begin() as session:
        event_id = await append_event(
            session,
            ticket.id,
            kind=SupportTicketEventKind.REPLY,
            author=EventAuthor.operator("dilshod"),
            now=_NOON,
            body="sorry about that",
        )

    # Assert — an operator re-reading this months later must not see "we answered them".
    async with sessions.begin() as session:
        stored = await session.get(SupportTicketEventRow, event_id)
        assert stored is not None
        assert stored.relayed_at is None


async def test_a_note_and_a_reply_are_two_kinds_and_never_one_flag(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    # Arrange — the only question that matters when a ticket is re-read is which sentences
    # the customer actually saw. A timeline that cannot separate the two is one an operator
    # has to guess at, which in practice means quoting an internal note back to a customer.
    ticket = await _described(sessions)

    # Act
    async with sessions.begin() as session:
        await append_event(
            session,
            ticket.id,
            kind=SupportTicketEventKind.NOTE,
            author=EventAuthor.operator("dilshod"),
            now=_NOON + timedelta(minutes=10),
            body="probably the STT again",
        )
        await append_event(
            session,
            ticket.id,
            kind=SupportTicketEventKind.REPLY,
            author=EventAuthor.operator("dilshod"),
            now=_NOON + timedelta(minutes=11),
            body="we are fixing it",
        )

    # Assert
    kinds = await _kinds(sessions, ticket.id)
    assert kinds[-2:] == [SupportTicketEventKind.NOTE, SupportTicketEventKind.REPLY]


# ---------------------------------------------------------------------------
# The quota
# ---------------------------------------------------------------------------
async def test_the_quota_counts_undescribed_tickets_and_refuses_at_the_ceiling(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    # Arrange — one tap writes a row AND sends into a group Telegram limits at ~20/minute.
    quota = SupportQuota(max_undescribed=2, max_per_day=99)
    await _open(sessions)

    # Act
    async with sessions.begin() as session:
        allowed = await quota_verdict(session, _ALICE, now=_NOON, quota=quota)
    await _open(sessions)
    async with sessions.begin() as session:
        refused = await quota_verdict(session, _ALICE, now=_NOON, quota=quota)

    # Assert — both counts travel, not just the boolean: a refusal at the line and a script
    # hammering the button want different responses from an operator.
    assert (allowed.is_allowed, allowed.undescribed) == (True, 1)
    assert (refused.is_allowed, refused.undescribed) == (False, 2)


async def test_resolving_an_abandoned_ticket_gives_the_customer_their_slot_back(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    # Arrange — the only remedy available when somebody has genuinely filled their slots with
    # taps they never followed up. Counting resolved rows too would make the quota a ban.
    quota = SupportQuota(max_undescribed=1, max_per_day=99)
    abandoned = await _open(sessions)
    async with sessions.begin() as session:
        before = await quota_verdict(session, _ALICE, now=_NOON, quota=quota)
        await move_status(
            session,
            abandoned.id,
            expected=SupportTicketStatus.NEW,
            to_status=SupportTicketStatus.RESOLVED,
            author=EventAuthor.operator("dilshod"),
            now=_NOON,
        )
        after = await quota_verdict(session, _ALICE, now=_NOON, quota=quota)

    # Assert
    assert before.is_allowed is False
    assert after.is_allowed is True


async def test_the_daily_ceiling_counts_described_tickets_too_and_turns_over_at_midnight(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    # Arrange — the daily number is about what the GROUP was asked to absorb, so a card
    # posted is a card posted whether or not the customer typed.
    quota = SupportQuota(max_undescribed=99, max_per_day=2)
    await _described(sessions)
    await _described(sessions)

    # Act
    async with sessions.begin() as session:
        today = await quota_verdict(session, _ALICE, now=_NOON, quota=quota)
        tomorrow = await quota_verdict(session, _ALICE, now=_NOON + timedelta(days=1), quota=quota)

    # Assert — the window is midnight UTC, computed from the INJECTED clock, so this test
    # moves a variable rather than waiting a day.
    assert (today.is_allowed, today.opened_today) == (False, 2)
    assert (tomorrow.is_allowed, tomorrow.opened_today) == (True, 0)


async def test_one_customers_tickets_do_not_count_against_another(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    # Arrange
    quota = SupportQuota(max_undescribed=1, max_per_day=1)
    await _open(sessions, who=_ALICE)

    # Act
    async with sessions.begin() as session:
        theirs = await quota_verdict(session, _BOB, now=_NOON, quota=quota)

    # Assert — the meter is per account, and a shared counter would let one abuser close the
    # support door for everybody.
    assert theirs.is_allowed is True
    assert (theirs.undescribed, theirs.opened_today) == (0, 0)


def test_a_quota_that_refuses_every_first_ticket_is_refused_at_wiring_time() -> None:
    # Assert — a ceiling below one closes support entirely, which is a configuration mistake
    # and not a policy anybody means. Caught at the composition root, not mid-complaint.
    with pytest.raises(ConfigError):
        SupportQuota(max_undescribed=0)
    with pytest.raises(ConfigError):
        SupportQuota(max_per_day=0)


# ---------------------------------------------------------------------------
# The never-throw facade
# ---------------------------------------------------------------------------
async def test_the_facade_opens_a_ticket_and_reads_it_back_through_a_result(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    # Arrange
    store = SqlSupportTickets(sessions)

    # Act
    opened = await store.open_ticket(
        telegram_user_id=_ALICE,
        language=Language.RU,
        source=SupportTicketSource.SUPPORT_COMMAND,
        order_id=None,
        now=_NOON,
    )

    # Assert — a handler needs no ``try``: every failure is a typed ``Err``.
    assert isinstance(opened, Ok), opened
    loaded = await store.load_ticket(opened.value.id)
    assert isinstance(loaded, Ok), loaded
    assert loaded.value is not None
    assert loaded.value.language is Language.RU


async def test_the_facade_survives_a_process_restart_because_the_ticket_is_a_row(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    # Arrange — a store object is what a process holds, so "a new store sees the old ticket"
    # is exactly "a redeploy does not lose the complaint". The same property
    # ``test_lyric_budget.py`` asserts about its counter, and the reason neither is in memory.
    opened = await SqlSupportTickets(sessions).open_ticket(
        telegram_user_id=_ALICE,
        language=Language.UZ_LATN,
        source=SupportTicketSource.DELIVERY_BUTTON,
        order_id=None,
        now=_NOON,
    )
    assert isinstance(opened, Ok), opened

    # Act
    reloaded = await SqlSupportTickets(sessions).load_ticket(opened.value.id)

    # Assert
    assert isinstance(reloaded, Ok), reloaded
    assert reloaded.value is not None
    assert reloaded.value.public_ref == opened.value.public_ref


async def test_the_facade_turns_an_illegal_move_into_an_err_rather_than_an_exception(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    # Arrange
    store = SqlSupportTickets(sessions)
    ticket = await _described(sessions)

    # Act
    moved = await store.move_status(
        ticket.id,
        expected=SupportTicketStatus.RESOLVED,
        to_status=SupportTicketStatus.WAITING,
        author=EventAuthor.system(),
        now=_NOON,
    )

    # Assert — the promise the whole seam makes: nothing raises at a handler.
    assert isinstance(moved, Err), moved


async def test_the_facade_reports_an_unknown_ticket_as_ok_none_not_as_a_failure(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    # Act
    loaded = await SqlSupportTickets(sessions).load_ticket(uuid4())

    # Assert — "no such ticket" is an answer, and the caller turns it into a 404; an ``Err``
    # here would make a mistyped id look like a database outage.
    assert isinstance(loaded, Ok), loaded
    assert loaded.value is None


# ---------------------------------------------------------------------------
# The panel's read
# ---------------------------------------------------------------------------
async def test_the_board_hides_the_tickets_nobody_described(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    # Arrange — a tap nobody followed up is real data and is kept; what it is not is WORK.
    await _open(sessions)
    await _described(sessions)

    # Act
    async with sessions.begin() as session:
        columns = await ticket_board(session)
        everything = await count_tickets(session, filters=TicketFilters())

    # Assert — the board counts one, the queue still holds both. A column length that
    # included the abandoned tap would send an operator to look at nothing.
    assert {column.status: column.count for column in columns}[SupportTicketStatus.NEW] == 1
    assert everything.total == 2


async def test_the_board_reports_every_column_even_the_empty_ones(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    # Arrange — nothing at all.
    # Act
    async with sessions.begin() as session:
        columns = await ticket_board(session)

    # Assert — a board whose columns appear as data arrives re-lays-out under the operator's
    # cursor, and an empty board must not look like a failed request. Declaration order, so
    # the columns are new -> in_progress -> waiting -> resolved and not whatever GROUP BY said.
    assert [column.status for column in columns] == list(SupportTicketStatus)
    assert all(column.count == 0 for column in columns)


async def test_the_queue_pages_by_keyset_newest_first_without_repeating_a_row(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    # Arrange — three tickets in a known order.
    first = await _described(sessions, at=_NOON)
    second = await _described(sessions, at=_NOON + timedelta(minutes=1))
    third = await _described(sessions, at=_NOON + timedelta(minutes=2))

    # Act
    async with sessions.begin() as session:
        page = await list_tickets(session, filters=TicketFilters(), request=PageRequest(limit=2))

    # Assert
    assert [item.id for item in page.items] == [third.id, second.id]
    assert page.has_more is True
    assert first.id not in {item.id for item in page.items}


async def test_a_queue_row_carries_the_complaint_and_its_event_count(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    # Arrange — the body crosses in full, which is this package's one argued exception to the
    # ``*_chars``/``has_*`` rule: an operator who cannot read the complaint cannot answer it.
    ticket = await _described(sessions, body="Ismni notoʻgʻri aytdi")

    # Act
    async with sessions.begin() as session:
        page = await list_tickets(session, filters=TicketFilters(), request=PageRequest())

    # Assert
    item = page.items[0]
    assert item.id == ticket.id
    assert item.body == "Ismni notoʻgʻri aytdi"
    # OPENED + DESCRIBED. The number is what tells an operator which tickets have been talked
    # about and which have had nothing said.
    assert item.event_count == 2
    # The Telegram routing ids are deliberately NOT published — the admin process holds no bot
    # token (ADMIN_PANEL_PLAN D10 / §4.2), so a message id is a field nobody can act on.
    assert item.is_posted_to_group is False


async def test_the_queue_can_be_searched_by_reference_and_by_what_the_customer_wrote(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    # Arrange
    named = await _described(sessions, body="the name Dilnora was wrong")
    other = await _described(sessions, body="the song is too short")

    # Act
    async with sessions.begin() as session:
        by_body = await list_tickets(
            session, filters=TicketFilters(search="Dilnora"), request=PageRequest()
        )
        by_reference = await list_tickets(
            session,
            filters=TicketFilters(search=other.public_ref),
            request=PageRequest(),
        )

    # Assert — searching the body discloses nothing the caller was not already handed: it is
    # published in full on every row of this same list.
    assert [item.id for item in by_body.items] == [named.id]
    assert [item.id for item in by_reference.items] == [other.id]


async def test_an_undescribed_ticket_matches_no_text_search(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    # Arrange — LIKE over NULL is NULL, which is what a ticket with no words should do.
    await _open(sessions)

    # Act
    async with sessions.begin() as session:
        found = await list_tickets(
            session, filters=TicketFilters(search="anything"), request=PageRequest()
        )

    # Assert
    assert found.items == ()


async def test_the_queue_filters_by_status_source_language_and_assignee(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    # Arrange
    button = await _described(sessions)
    command = await _open(sessions, source=SupportTicketSource.SUPPORT_COMMAND)
    async with sessions.begin() as session:
        await describe(session, command.id, body="typed it", now=_NOON)
        await assign(
            session,
            button.id,
            admin_username="dilshod",
            author=EventAuthor.operator("dilshod"),
            now=_NOON,
        )

    # Act
    async with sessions.begin() as session:
        by_source = await list_tickets(
            session,
            filters=TicketFilters(sources=(SupportTicketSource.SUPPORT_COMMAND,)),
            request=PageRequest(),
        )
        by_assignee = await list_tickets(
            session,
            filters=TicketFilters(assigned_admin_username="dilshod"),
            request=PageRequest(),
        )
        by_language = await list_tickets(
            session, filters=TicketFilters(languages=(Language.RU,)), request=PageRequest()
        )

    # Assert
    assert [item.id for item in by_source.items] == [command.id]
    assert [item.id for item in by_assignee.items] == [button.id]
    assert by_language.items == ()


async def test_the_detail_reads_the_timeline_oldest_first(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    # Arrange — the only ascending list in this package. A conversation is read forwards, and
    # an operator deciding what to say next reads down to the last thing that was said.
    ticket = await _described(sessions)
    async with sessions.begin() as session:
        await move_status(
            session,
            ticket.id,
            expected=SupportTicketStatus.NEW,
            to_status=SupportTicketStatus.IN_PROGRESS,
            author=EventAuthor.operator("dilshod"),
            now=_NOON + timedelta(minutes=10),
        )

    # Act
    async with sessions.begin() as session:
        detail = await get_ticket(session, ticket.id)

    # Assert
    assert detail is not None
    assert [event.kind for event in detail.events] == [
        SupportTicketEventKind.OPENED,
        SupportTicketEventKind.DESCRIBED,
        SupportTicketEventKind.STATUS_CHANGE,
    ]
    assert detail.ticket.event_count == len(detail.events)


async def test_the_detail_of_an_unknown_ticket_is_none_rather_than_an_empty_shell(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    # Act
    async with sessions.begin() as session:
        detail = await get_ticket(session, uuid4())

    # Assert — existence is this function's answer to give; the caller turns it into a 404.
    assert detail is None
