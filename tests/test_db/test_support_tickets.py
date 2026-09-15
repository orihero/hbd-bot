"""The support-ticket schema, asserted against a real database rather than a model file.

Revision 0027 carries two unique indexes, two foreign keys with opposite ``ON DELETE``
postures and one deliberately-nullable pair, and each of them is the difference between a
working support queue and a specific, nameable failure: a staffer's answer relayed to the
wrong customer, a card posted into the group twice on every deploy, a complaint deleted by a
purge run on the song it was about, or a count of complaints that can never disagree with the
count of taps. None of that is provable by reading the model: SQLAlchemy will happily
construct an object violating every constraint it declares, and the assertion that matters is
the one the ENGINE makes on ``flush``.

So the tests that can write real rows do, through a real session, and assert a real
``IntegrityError``. That also makes each one a live check that the constraint survived
``create_all`` — the schema the whole unit suite runs on — while ``test_migrations.py``
separately proves that schema matches the chain.

**WHAT THIS FILE CANNOT PROVE, SAID OUT LOUD RATHER THAN QUIETLY OMITTED.** SQLite does not
enforce foreign keys unless ``PRAGMA foreign_keys=ON`` is issued per connection, and nothing
in this project issues it. So ``ON DELETE SET NULL`` on ``order_id`` and ``ON DELETE CASCADE``
on ``ticket_id`` cannot be exercised here at all — a test that deleted an order and asserted
the ticket survived would pass on an engine that was never going to delete anything, which is
worse than no test because it reads like evidence. Those two postures are asserted as DDL
instead, off the metadata, and the runtime behaviour belongs in the Postgres integration
suite. The postures are load-bearing in opposite directions and that is the whole reason they
are named: a ticket must OUTLIVE the order it was about (or retention on ``orders`` silently
becomes retention on complaints), and a timeline must NOT outlive its ticket (or ``/forget``
leaves rows still quoting a customer's own words).

**Every Telegram id in this file is outside the 32-bit range**, matching ``test_credits.py``,
``test_credit_erasure.py`` and ``test_payme_tables.py``. An accidental ``Integer`` column on
this path would not fail loudly; it would silently truncate the id of whoever is complaining,
and their ticket would then be deleted by somebody else's ``/forget`` or missed by their own.
"""

from __future__ import annotations

from typing import Any, Final
from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from bayram.contracts import (
    Language,
    SupportAuthorKind,
    SupportTicketEventKind,
    SupportTicketSource,
    SupportTicketStatus,
)
from bayram.db.models import Base
from bayram.db.models.support_ticket import SupportTicketRow
from bayram.db.models.support_ticket_event import SupportTicketEventRow
from tests.test_db.conftest import MovableClock

#: Well outside 2**31. See the module docstring.
_USER: Final[int] = 8_912_345_678_901
#: A supergroup id, which is NEGATIVE and begins ``-100``. Written out because the settings
#: field holding it deliberately carries no ``ge=0`` bound, and a column that could not store
#: it would be discovered only against a real group.
_GROUP: Final[int] = -1_002_345_678_901


def _ticket(**overrides: Any) -> SupportTicketRow:
    """An undescribed ticket: the row a customer creates by tapping ⚠️ and nothing more.

    Undescribed is the DEFAULT here on purpose. It is the state every ticket passes through,
    it is the state a large minority of them stay in, and a factory that quietly filled in a
    body would make the "tapped and never typed" row — the one this schema goes out of its way
    to keep — the awkward special case instead of the ordinary one.
    """
    values: dict[str, Any] = {
        "public_ref": uuid4().hex[:8].upper(),
        "telegram_user_id": _USER,
        "language": Language.UZ_LATN,
        "source": SupportTicketSource.DELIVERY_BUTTON,
    }
    values.update(overrides)
    return SupportTicketRow(**values)


def _event(*, ticket_id: UUID, **overrides: Any) -> SupportTicketEventRow:
    values: dict[str, Any] = {
        "ticket_id": ticket_id,
        "kind": SupportTicketEventKind.OPENED,
        "author_kind": SupportAuthorKind.CUSTOMER,
        "author_telegram_user_id": _USER,
    }
    values.update(overrides)
    return SupportTicketEventRow(**values)


async def _add(sessions: async_sessionmaker[AsyncSession], *rows: object) -> None:
    async with sessions.begin() as session:
        session.add_all(list(rows))


# ---------------------------------------------------------------------------
# The two unique indexes — each closing a different way to answer the wrong person
# ---------------------------------------------------------------------------
async def test_two_tickets_cannot_share_a_public_ref(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    """The reference a customer reads down a phone line has to resolve to one ticket.

    Without the constraint the failure is silent and worse than a lookup miss: support finds
    *a* ticket, answers about it, and believes they looked the customer up.
    """
    # Arrange
    await _add(sessions, _ticket(public_ref="A3F2-91"))

    # Act / Assert
    with pytest.raises(IntegrityError):
        await _add(sessions, _ticket(public_ref="A3F2-91"))


async def test_two_tickets_cannot_claim_the_same_group_card(
    sessions: async_sessionmaker[AsyncSession], clock: MovableClock
) -> None:
    """Within ONE chat, ``group_message_id`` is the key a reply is matched back to a ticket by.

    Two rows claiming one card in one group is not a duplicate; it is one customer's complaint
    answered with the sentence a staffer wrote for somebody else. Both rows here name the same
    ``group_chat_id`` on purpose — that is the half of the pair that makes the message id mean
    anything, and the test below is its opposite number.
    """
    # Arrange
    await _add(
        sessions,
        _ticket(group_chat_id=_GROUP, group_message_id=4_812, group_posted_at=clock.now),
    )

    # Act / Assert
    with pytest.raises(IntegrityError):
        await _add(
            sessions,
            _ticket(group_chat_id=_GROUP, group_message_id=4_812, group_posted_at=clock.now),
        )


async def test_two_groups_may_each_number_a_card_the_same(
    sessions: async_sessionmaker[AsyncSession], clock: MovableClock
) -> None:
    """A Telegram ``message_id`` is a PER-CHAT counter, so the uniqueness has to be per chat.

    REGRESSION. The index shipped UNIQUE over ``group_message_id`` alone, which asserts
    something Telegram never promised. The failure it caused is not a rejected duplicate; it is
    a ticket that posted fine and then could not record it. Move the support group — a new
    group, or Telegram auto-upgrading a basic group to a supergroup, which CHANGES the chat id
    — repoint ``BAYRAM_SUPPORT_GROUP_CHAT_ID``, and the next card Telegram numbers 5 in the new
    chat collides with a card numbered 5 in the old one. ``claim_group_post``'s UPDATE raises
    ``IntegrityError``, ``run_guarded`` turns it into an ``Err``, and the ticket is left
    permanently un-latched beside an orphan card in the group that nothing can edit or relay
    from.

    The two rows below are the moved-group scenario in miniature: the same message id, two
    chats, and the database must accept both.
    """
    # Arrange — the group we used last month, and the one we use today.
    old_group = _GROUP
    new_group = -1_009_876_543_210
    shared_message_id = 5

    # Act
    await _add(
        sessions,
        _ticket(
            public_ref="G1X4-08",
            group_chat_id=old_group,
            group_message_id=shared_message_id,
            group_posted_at=clock.now,
        ),
        _ticket(
            public_ref="G2X4-09",
            group_chat_id=new_group,
            group_message_id=shared_message_id,
            group_posted_at=clock.now,
        ),
    )

    # Assert — and the reply lookup still resolves each to exactly one ticket, because it
    # filters on the chat id as well; that is the read this index was shaped around.
    async with sessions() as session:
        refs = (
            await session.scalars(
                sa.select(SupportTicketRow.public_ref)
                .where(SupportTicketRow.group_message_id == shared_message_id)
                .order_by(SupportTicketRow.public_ref)
            )
        ).all()
        in_new_group = await session.scalar(
            sa.select(SupportTicketRow.public_ref).where(
                SupportTicketRow.group_chat_id == new_group,
                SupportTicketRow.group_message_id == shared_message_id,
            )
        )
    assert list(refs) == ["G1X4-08", "G2X4-09"]
    assert in_new_group == "G2X4-09"


async def test_any_number_of_tickets_may_be_waiting_to_be_posted(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    """The latch is NULL-tolerant, and that is what makes a failed group post survivable.

    Both engines permit any number of NULLs in a unique index. If they did not, the second
    ticket opened while Telegram was refusing would be rejected by the database — and the
    complaint would be lost at exactly the moment the product was already misbehaving.
    """
    # Arrange / Act
    await _add(sessions, _ticket(), _ticket(), _ticket())

    # Assert
    async with sessions() as session:
        unposted = await session.scalar(
            sa.select(sa.func.count())
            .select_from(SupportTicketRow)
            .where(SupportTicketRow.group_message_id.is_(None))
        )
    assert unposted == 3


# ---------------------------------------------------------------------------
# The row a customer creates by tapping and walking away
# ---------------------------------------------------------------------------
async def test_a_ticket_with_no_description_is_a_storable_row(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    """Tapped and never typed. Real data, kept, and excluded from the board by a predicate.

    Deleting these rows would make the count of complaints equal the count of taps by
    construction — destroying the only measure of how many people started to complain and
    gave up, which is the number the rate limiter is sized against.
    """
    # Arrange
    await _add(sessions, _ticket(public_ref="B7K1-04", prompt_message_id=9_001))

    # Act
    async with sessions() as session:
        row = await session.scalar(
            sa.select(SupportTicketRow).where(SupportTicketRow.public_ref == "B7K1-04")
        )

    # Assert
    assert row is not None
    assert row.body is None
    assert row.described_at is None
    # The prompt id survives, because it is what a late reply is matched against.
    assert row.prompt_message_id == 9_001


async def test_a_new_ticket_starts_in_the_first_column(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    """``status`` is defaulted in the mapper, unlike ``broadcasts.state``.

    A ticket has exactly one birth state and it is written by the customer's tap, so a writer
    that had to name it would only ever name ``new``. Every LATER move is still an explicit
    conditional ``UPDATE``.
    """
    # Arrange / Act
    await _add(sessions, _ticket(public_ref="C2M9-77"))

    # Assert
    async with sessions() as session:
        status = await session.scalar(
            sa.select(SupportTicketRow.status).where(SupportTicketRow.public_ref == "C2M9-77")
        )
    assert status is SupportTicketStatus.NEW


async def test_the_group_and_customer_ids_survive_the_32_bit_boundary(
    sessions: async_sessionmaker[AsyncSession], clock: MovableClock
) -> None:
    """Both ids are ``BigInteger``, and the group's is NEGATIVE.

    A supergroup id begins ``-100``; the settings field holding it deliberately carries no
    ``ge=0`` bound for that reason, and a column that could not store it would be discovered
    only against a real group, in production, with the first ticket.
    """
    # Arrange / Act
    await _add(
        sessions,
        _ticket(
            public_ref="D8P3-12",
            telegram_user_id=_USER,
            group_chat_id=_GROUP,
            group_message_id=77_123,
            group_posted_at=clock.now,
        ),
    )

    # Assert
    async with sessions() as session:
        row = await session.scalar(
            sa.select(SupportTicketRow).where(SupportTicketRow.public_ref == "D8P3-12")
        )
    assert row is not None
    assert row.telegram_user_id == _USER
    assert row.group_chat_id == _GROUP


# ---------------------------------------------------------------------------
# The timeline
# ---------------------------------------------------------------------------
async def test_a_status_change_records_both_ends_of_the_move(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    """ "It went to ``in_progress``" and "it went to ``in_progress`` from ``resolved``" differ.

    The second is a reopened ticket, which is the one shape of this row anybody goes looking
    for, and it is unrecoverable from a single ``to_status`` column.
    """
    # Arrange
    ticket = _ticket(public_ref="E4T6-58", status=SupportTicketStatus.IN_PROGRESS)
    await _add(sessions, ticket)

    # Act
    await _add(
        sessions,
        _event(
            ticket_id=ticket.id,
            kind=SupportTicketEventKind.STATUS_CHANGE,
            author_kind=SupportAuthorKind.SYSTEM,
            author_telegram_user_id=None,
            from_status=SupportTicketStatus.RESOLVED,
            to_status=SupportTicketStatus.IN_PROGRESS,
        ),
    )

    # Assert
    async with sessions() as session:
        event = await session.scalar(
            sa.select(SupportTicketEventRow).where(SupportTicketEventRow.ticket_id == ticket.id)
        )
    assert event is not None
    assert event.from_status is SupportTicketStatus.RESOLVED
    assert event.to_status is SupportTicketStatus.IN_PROGRESS


async def test_a_reply_is_distinguishable_from_one_that_never_arrived(
    sessions: async_sessionmaker[AsyncSession], clock: MovableClock
) -> None:
    """``relayed_at`` is the proof a customer actually read it.

    A reply composed in the panel and refused by Telegram — the customer blocked us, the chat
    is gone — must not read as "we answered them". It is the one clock on this append-only
    table written after insert, and it records a second event rather than amending the first.
    """
    # Arrange
    ticket = _ticket(public_ref="F9W2-30")
    await _add(sessions, ticket)
    delivered = _event(
        ticket_id=ticket.id,
        kind=SupportTicketEventKind.REPLY,
        author_kind=SupportAuthorKind.STAFF_GROUP,
        author_display_name="@sardor",
        body="Kechirasiz, qayta yozib beramiz.",
        relayed_at=clock.now,
    )
    refused = _event(
        ticket_id=ticket.id,
        kind=SupportTicketEventKind.REPLY,
        author_kind=SupportAuthorKind.OPERATOR,
        author_telegram_user_id=None,
        author_admin_username="dilnoza",
        body="Sent from the panel; the customer had blocked the bot.",
    )

    # Act
    await _add(sessions, delivered, refused)

    # Assert
    async with sessions() as session:
        unrelayed = await session.scalar(
            sa.select(sa.func.count())
            .select_from(SupportTicketEventRow)
            .where(
                SupportTicketEventRow.ticket_id == ticket.id,
                SupportTicketEventRow.relayed_at.is_(None),
            )
        )
    assert unrelayed == 1


async def test_the_timeline_holds_no_updated_at(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    """Append-only, so the mixin is deliberately absent and an ``updated_at`` would be a lie.

    Asserted rather than left to a reader, because the cheap "simplification" is to add
    ``TimestampMixin`` to every table for symmetry — which here hands a future writer a column
    that invites amending the record of what a customer was told.
    """
    # Arrange / Act
    columns = {column.name for column in SupportTicketEventRow.__table__.columns}

    # Assert
    assert "created_at" in columns
    assert "updated_at" not in columns


# ---------------------------------------------------------------------------
# The DDL this engine cannot execute — see the module docstring
# ---------------------------------------------------------------------------
def test_a_ticket_outlives_the_order_it_was_about() -> None:
    """``order_id`` takes ``ON DELETE SET NULL``, matching ``generation_attempts.order_id``.

    A cascade here would turn any retention policy on ``orders`` into an undeclared retention
    policy on complaints: the support history of every song that aged out would go with it,
    silently, on a sweep nobody associated with support at all.
    """
    # Arrange
    (foreign_key,) = SupportTicketRow.__table__.c.order_id.foreign_keys

    # Assert
    assert foreign_key.column.table.name == "orders"
    assert foreign_key.ondelete == "SET NULL"


def test_a_timeline_does_not_outlive_its_ticket() -> None:
    """``ticket_id`` takes ``ON DELETE CASCADE``, which is what makes ``/forget`` one statement.

    An event is a PART of a ticket and meaningless without it. More sharply: these rows quote
    the customer's own words, so an orphan left behind by a deleted ticket is the erasure
    failing while appearing to have worked.
    """
    # Arrange
    (foreign_key,) = SupportTicketEventRow.__table__.c.ticket_id.foreign_keys

    # Assert
    assert foreign_key.column.table.name == "support_tickets"
    assert foreign_key.ondelete == "CASCADE"


@pytest.mark.parametrize(
    "table_name",
    ["support_tickets", "support_ticket_events"],
)
def test_no_support_column_claims_a_retention_clock(table_name: str) -> None:
    """The ``*_expires_at`` suffix is a published legal clock in this codebase, and obliges one.

    It demands a sweep BY NAME in ``test_audit_retention.py``, a ``RetentionPolicy`` field, a
    ``PurgeReport`` entry and a ``purge_runs`` column. The ticket body is kept INDEFINITELY and
    erased on request through ``/forget`` — the exemption is written out in
    ``test_privacy_constraints.py`` — so a column bearing that suffix here would claim a
    schedule nobody promised, and a support history that deleted itself on one would delete the
    evidence in the dispute it was kept for.
    """
    # Arrange / Act — read off the live metadata rather than the mapped class, so a table
    # that is created but never registered cannot make this check vacuously green.
    table = Base.metadata.tables[table_name]
    clocks = [column.name for column in table.columns if column.name.endswith("expires_at")]

    # Assert
    assert clocks == []


def test_the_board_index_carries_its_tiebreaker() -> None:
    """``(status, created_at, id)`` — and ``id`` is not an afterthought.

    Without the third column Postgres adds an ``Incremental Sort … Presorted Key: created_at``
    to every keyset page, and the sort buffer grows with the size of the tie group — which a
    burst of tickets from one outage is made of. The name is asserted too, because
    ``test_the_migrated_indexes_match_the_model_metadata`` compares index NAMES and the
    migration spells this one by hand.
    """
    # Arrange
    indexes = {str(index.name): index for index in Base.metadata.tables["support_tickets"].indexes}

    # Act
    board = indexes.get("ix_support_tickets_status_created_at_id")

    # Assert
    assert board is not None
    assert [column.name for column in board.columns] == ["status", "created_at", "id"]


def test_the_card_latch_is_unique_per_chat_and_not_per_message() -> None:
    """The uniqueness is ``(group_chat_id, group_message_id)``, in that order, and UNIQUE.

    REGRESSION, asserted off the metadata as well as off a live write, because the two catch
    different mistakes. The write test above proves the engine enforces it; this one pins the
    SHAPE — that the constraint is a composite leading with the chat id, and that no
    single-column unique index on ``group_message_id`` has crept back onto the column. A
    ``message_id`` is a per-chat counter, so a global unique index on it fails the latch for a
    card that posted successfully the moment the support group's chat id changes.

    The name is asserted too: ``test_the_migrated_indexes_match_the_model_metadata`` compares
    index NAMES, and revision 0027 spells this one by hand.
    """
    # Arrange — live metadata, not the mapped class, so an unregistered model cannot make this
    # vacuously green.
    table = Base.metadata.tables["support_tickets"]
    indexes = {str(index.name): index for index in table.indexes}

    # Act
    card = indexes.get("ix_support_tickets_group_chat_id_group_message_id")

    # Assert
    assert card is not None
    assert [column.name for column in card.columns] == ["group_chat_id", "group_message_id"]
    assert card.unique is True
    # And nothing unique keyed on the message id alone — neither a column-level ``unique=True``
    # (which SQLAlchemy renders as a UniqueConstraint) nor a second single-column index.
    assert not any(
        [column.name for column in index.columns] == ["group_message_id"] for index in table.indexes
    )
    assert not any(
        [column.name for column in constraint.columns] == ["group_message_id"]
        for constraint in table.constraints
        if isinstance(constraint, sa.UniqueConstraint)
    )
    assert table.c.group_message_id.index is not True
