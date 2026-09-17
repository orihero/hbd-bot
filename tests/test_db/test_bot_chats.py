"""The ``bot_chats`` schema, asserted against a real database rather than a model file.

Revision 0028 carries exactly one constraint that matters, and it is the whole feature: AT
MOST ONE ROW MAY BE THE SUPPORT GROUP. Everything else on the table is storage. So most of
this file is about that index, from both sides — one selected chat is accepted, a second is
refused, and any number of UNSELECTED chats coexist, which is the half a plain unique
constraint would silently break.

None of that is provable by reading the model. SQLAlchemy will happily construct an object
violating every constraint it declares, ``__table_args__`` is a declaration rather than DDL
until something builds it, and a partial unique index and a total one are indistinguishable in
any reflection that reports only columns and uniqueness. The assertion that matters is the one
the ENGINE makes on ``flush``, so the tests that can write real rows do, through a real
session, and assert a real ``IntegrityError``. That also makes each one a live check that the
constraint survived ``create_all`` — the schema the whole unit suite runs on — while
``test_migrations.py`` separately proves that schema matches the chain.

**WHAT THIS FILE CANNOT PROVE, SAID OUT LOUD RATHER THAN QUIETLY OMITTED.** It cannot prove
the index renders on Postgres. The predicate is a bare column name precisely so that one
string serves both engines (revision ``0010``'s call for ``ix_admin_users_active_owner``), but
SQLite's tolerance is not evidence about Postgres — that is
``test_migration_applies_and_reverses_against_postgres``'s job, and
``test_the_support_group_selection_index_is_unique_and_partial`` beside it is what asserts the
``WHERE`` clause reached the database at all. It also cannot prove the race the index exists
for: two overlapping transactions each clearing and re-setting the selection commit both rows
under Postgres' READ COMMITTED, and SQLite's write lock serialises them so the unit suite
passes either way. ``admin_users`` carries that measurement (five trials out of five on
Postgres 16); this file asserts the guard, not the race.

**Every chat id in this file is NEGATIVE and outside the 32-bit range.** A group id is
negative and a supergroup id begins ``-100``, which is the shape ``test_support_tickets.py``
already writes out for the same reason: an accidental ``Integer`` column on this path would
not fail loudly, it would truncate a real supergroup id, and the panel would then select a
chat that does not exist.
"""

from __future__ import annotations

from typing import Any, Final

import pytest
import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from bayram.contracts import BotChatSource, BotChatStatus, BotChatType
from bayram.db.models.bot_chat import BotChatRow
from tests.test_db.conftest import MovableClock

#: The support group in use today, and the one before it. Both well outside 2**31, and both
#: negative; see the module docstring.
_GROUP: Final[int] = -1_002_345_678_901
_OTHER_GROUP: Final[int] = -1_009_876_543_210
#: A basic group, which Telegram numbers differently and upgrades to a supergroup on its own —
#: the event that gives a chat a NEW id and leaves the old one selected and dead.
_BASIC_GROUP: Final[int] = -876_543_210


def _chat(chat_id: int, *, at: MovableClock, **overrides: Any) -> BotChatRow:
    """A chat the bot was added to and nobody has selected.

    Unselected is the DEFAULT here on purpose. It is the state every chat is recorded in, it is
    the state all but one of them stay in forever, and a factory that quietly selected the row
    would make the ordinary chat the awkward special case — and would hide the half of the
    index that permits any number of them.
    """
    values: dict[str, Any] = {
        "chat_id": chat_id,
        "chat_type": BotChatType.SUPERGROUP,
        "title": "Bayram support",
        "bot_status": BotChatStatus.MEMBER,
        "source": BotChatSource.MEMBERSHIP_EVENT,
        "first_seen_at": at.now,
        "last_seen_at": at.now,
    }
    values.update(overrides)
    return BotChatRow(**values)


async def _add(sessions: async_sessionmaker[AsyncSession], *rows: object) -> None:
    async with sessions.begin() as session:
        session.add_all(list(rows))


# ---------------------------------------------------------------------------
# The invariant: at most one selected support group
# ---------------------------------------------------------------------------
async def test_two_chats_cannot_both_be_the_support_group(
    sessions: async_sessionmaker[AsyncSession], clock: MovableClock
) -> None:
    """The one thing this table has to guarantee, guaranteed by the database.

    The write path clears the previous selection and sets the new one in a single transaction,
    and on the ordinary path that is genuinely the mechanism. This index is what closes the
    path the transaction cannot — two operators pressing Select at the same instant, each
    reading one selected row, each clearing the row they read, each setting their own. Without
    it the failure is not an error anybody sees: tickets simply start arriving in two groups,
    and the operator who notices has nothing to tell them which one is correct.
    """
    # Arrange
    await _add(sessions, _chat(_GROUP, at=clock, is_support_group=True))

    # Act / Assert
    with pytest.raises(IntegrityError):
        await _add(sessions, _chat(_OTHER_GROUP, at=clock, is_support_group=True))


async def test_any_number_of_chats_may_be_unselected(
    sessions: async_sessionmaker[AsyncSession], clock: MovableClock
) -> None:
    """The half a plain ``UNIQUE (is_support_group)`` would break, and break silently.

    A total unique index on that column permits one ``true`` row AND one ``false`` row — a
    schema in which the bot can be added to exactly two groups, ever, and the third is refused
    by the database with an integrity error nobody can read. The index is PARTIAL for this
    reason: rows outside the predicate are outside the index entirely.

    Three unselected chats is also the ordinary state of this table. The bot sits in a
    developer group, an old support group and the current one, and only one of them is the
    inbox.
    """
    # Arrange / Act
    await _add(
        sessions,
        _chat(_GROUP, at=clock),
        _chat(_OTHER_GROUP, at=clock),
        _chat(_BASIC_GROUP, at=clock, chat_type=BotChatType.GROUP),
    )

    # Assert
    async with sessions() as session:
        unselected = await session.scalar(
            sa.select(sa.func.count())
            .select_from(BotChatRow)
            .where(BotChatRow.is_support_group.is_(False))
        )
    assert unselected == 3


async def test_the_selection_moves_when_the_previous_one_is_cleared_first(
    sessions: async_sessionmaker[AsyncSession], clock: MovableClock
) -> None:
    """Repointing the inbox is clear-then-set in ONE transaction, and the index permits it.

    This is the shape the select endpoint has to use, asserted here so that the constraint
    above cannot be read as "the selection can never change". Both statements land before the
    commit, so the index sees one selected row at commit time and the move succeeds — whereas
    setting the new one first would trip the index against a row the same transaction was about
    to clear.
    """
    # Arrange — the group we used last month is the one currently selected.
    await _add(
        sessions,
        _chat(_OTHER_GROUP, at=clock, is_support_group=True, selected_by_username="dilnoza"),
        _chat(_GROUP, at=clock),
    )

    # Act — clear, then set, in one transaction.
    async with sessions.begin() as session:
        await session.execute(
            sa.update(BotChatRow)
            .where(BotChatRow.is_support_group.is_(True))
            .values(is_support_group=False)
        )
        await session.execute(
            sa.update(BotChatRow)
            .where(BotChatRow.chat_id == _GROUP)
            .values(
                is_support_group=True,
                selected_by_username="sardor",
                selected_at=clock.now,
                thread_id=41,
            )
        )

    # Assert — exactly one selected chat, and it is the new one, with its topic beside it.
    async with sessions() as session:
        selected = (
            await session.scalars(
                sa.select(BotChatRow).where(BotChatRow.is_support_group.is_(True))
            )
        ).all()
    assert [row.chat_id for row in selected] == [_GROUP]
    assert selected[0].thread_id == 41
    assert selected[0].selected_by_username == "sardor"


async def test_a_chat_is_unselected_without_losing_who_selected_it(
    sessions: async_sessionmaker[AsyncSession], clock: MovableClock
) -> None:
    """Clearing the selection does not clear ``selected_at`` or ``selected_by_username``.

    "This was once the support group, and Dilnoza pointed it here on the 15th" is the most
    useful thing to know about a chat an operator is staring at while wondering where last
    month's tickets went. Nulling the pair on clear would be tidier and would destroy exactly
    that answer.
    """
    # Arrange
    await _add(
        sessions,
        _chat(
            _GROUP,
            at=clock,
            is_support_group=True,
            selected_by_username="dilnoza",
            selected_at=clock.now,
        ),
    )

    # Act
    async with sessions.begin() as session:
        await session.execute(
            sa.update(BotChatRow).where(BotChatRow.chat_id == _GROUP).values(is_support_group=False)
        )

    # Assert
    async with sessions() as session:
        row = await session.get(BotChatRow, _GROUP)
    assert row is not None
    assert row.is_support_group is False
    assert row.selected_by_username == "dilnoza"
    assert row.selected_at is not None


# ---------------------------------------------------------------------------
# The row itself
# ---------------------------------------------------------------------------
async def test_a_negative_supergroup_id_survives_the_32_bit_boundary(
    sessions: async_sessionmaker[AsyncSession], clock: MovableClock
) -> None:
    """``chat_id`` is a ``BigInteger`` primary key, and the values are negative.

    A supergroup id begins ``-100`` and is comfortably outside 32 bits. An ``Integer`` column
    here would not fail loudly; it would truncate the id, and the failure would surface as the
    panel selecting a chat that does not exist — discovered against a real group, in
    production, with the first ticket that never arrived.
    """
    # Arrange / Act
    await _add(sessions, _chat(_GROUP, at=clock, thread_id=-1_002_345_678_999))

    # Assert
    async with sessions() as session:
        row = await session.get(BotChatRow, _GROUP)
    assert row is not None
    assert row.chat_id == _GROUP
    assert row.thread_id == -1_002_345_678_999


async def test_a_recorded_chat_is_unselected_unverified_and_unblamed(
    sessions: async_sessionmaker[AsyncSession], clock: MovableClock
) -> None:
    """What the bot writes when it is added to a group: a chat, and no claims about it.

    ``is_support_group`` defaults to ``False`` in the mapper — being added to a group must
    never repoint the support inbox — and every verification and selection column is NULL,
    because nothing has verified anything and nobody has chosen it. The panel reads exactly
    this state as "known, not selected, never checked", and it is the state all but one row on
    this table is in.
    """
    # Arrange / Act
    await _add(sessions, _chat(_GROUP, at=clock))

    # Assert
    async with sessions() as session:
        row = await session.get(BotChatRow, _GROUP)
    assert row is not None
    assert row.is_support_group is False
    assert row.thread_id is None
    assert row.verified_at is None
    assert row.verification_error is None
    assert row.selected_by_username is None
    assert row.selected_at is None


async def test_a_pasted_chat_id_is_storable_with_nothing_else_known_about_it(
    sessions: async_sessionmaker[AsyncSession], clock: MovableClock
) -> None:
    """A ``manual`` row is a bare id, and the schema has to accept one.

    Telegram has no "list my groups" API, so a group the bot was ALREADY in before this feature
    shipped can never be discovered — the only route for it is an operator typing the id, and at
    that moment nothing is known beyond the number. ``title`` and ``username`` are therefore
    nullable rather than required: demanding a title would mean the one route that exists for an
    existing group could not be taken at all. ``bot_status`` is ``UNKNOWN``, which is the honest
    value, and the verification job is what replaces it with a fact.
    """
    # Arrange / Act
    await _add(
        sessions,
        _chat(
            _BASIC_GROUP,
            at=clock,
            chat_type=BotChatType.GROUP,
            title=None,
            username=None,
            bot_status=BotChatStatus.UNKNOWN,
            source=BotChatSource.MANUAL,
        ),
    )

    # Assert
    async with sessions() as session:
        row = await session.get(BotChatRow, _BASIC_GROUP)
    assert row is not None
    assert row.title is None
    assert row.source is BotChatSource.MANUAL
    assert row.bot_status is BotChatStatus.UNKNOWN


async def test_a_migrated_group_becomes_a_second_row_and_the_old_one_stays_selected(
    sessions: async_sessionmaker[AsyncSession], clock: MovableClock
) -> None:
    """Telegram upgrading a basic group to a supergroup gives it a NEW id. Nothing is rewritten.

    This is a real event, not a hypothetical, and the schema's answer is deliberately passive:
    the new chat arrives as its own row through its own membership update, and the old row is
    left selected, pointing at an id that no longer takes a message, until an operator selects
    the new one. Rewriting ``chat_id`` in place was refused twice over — it is the primary key,
    and ``support_tickets.group_chat_id`` already holds its value, so moving it would make old
    ticket rows claim their cards were posted somewhere they were not (revision 0027's latch is
    unique PER CHAT precisely because this id changes); and it would move the support inbox on
    Telegram's initiative, with nothing in any log to say so.

    What makes the dead selection recoverable rather than merely broken is
    ``verification_error``: the job that tries to post says, in words, that this chat migrated
    and names the id it migrated to. This test is the state the operator is looking at when they
    read it.
    """
    # Arrange — the basic group is the support inbox.
    await _add(sessions, _chat(_BASIC_GROUP, at=clock, chat_type=BotChatType.GROUP))
    async with sessions.begin() as session:
        await session.execute(
            sa.update(BotChatRow)
            .where(BotChatRow.chat_id == _BASIC_GROUP)
            .values(is_support_group=True, selected_by_username="dilnoza", selected_at=clock.now)
        )

    # Act — Telegram upgrades it. A new chat id appears, and the verification job explains the
    # old one. Both rows coexist, because only one of them claims the selection.
    clock.advance(days=3)
    await _add(sessions, _chat(_GROUP, at=clock))
    async with sessions.begin() as session:
        await session.execute(
            sa.update(BotChatRow)
            .where(BotChatRow.chat_id == _BASIC_GROUP)
            .values(
                verification_error=f"this group became supergroup {_GROUP}; select it instead",
                verified_at=None,
            )
        )

    # Assert — the selection has NOT moved, and the row says why it cannot work.
    async with sessions() as session:
        old = await session.get(BotChatRow, _BASIC_GROUP)
        new = await session.get(BotChatRow, _GROUP)
    assert old is not None and new is not None
    assert old.is_support_group is True
    assert new.is_support_group is False
    assert old.verified_at is None
    assert old.verification_error is not None
    assert str(_GROUP) in old.verification_error


async def test_telegrams_clock_is_stored_beside_our_own(
    sessions: async_sessionmaker[AsyncSession], clock: MovableClock
) -> None:
    """``first_seen_at`` / ``last_seen_at`` are ``ChatMemberUpdated.date``, not ``utc_now``.

    ``bayram.bot.handlers.membership`` already refuses to substitute our clock for Telegram's on
    the identical update, and the gap is real rather than theoretical: ``run_polling`` calls
    ``delete_webhook(drop_pending_updates=True)`` on every start, so updates that arrived while
    the bot was down are discarded and a row can be written long after the event it describes.
    Two columns, because "when did we first hear about this chat" and "is it still live" are two
    questions and the second has to move while the first does not.
    """
    # Arrange — the bot was added three days before the row below is updated.
    added_at = clock.now
    await _add(sessions, _chat(_GROUP, at=clock))

    # Act — it is promoted to administrator later, which refreshes only the second clock.
    seen_again = clock.advance(days=3)
    async with sessions.begin() as session:
        await session.execute(
            sa.update(BotChatRow)
            .where(BotChatRow.chat_id == _GROUP)
            .values(bot_status=BotChatStatus.ADMINISTRATOR, last_seen_at=seen_again)
        )

    # Assert
    async with sessions() as session:
        row = await session.get(BotChatRow, _GROUP)
    assert row is not None
    assert row.first_seen_at == added_at
    assert row.last_seen_at == seen_again
    assert row.bot_status is BotChatStatus.ADMINISTRATOR


async def test_the_table_holds_nothing_about_the_person_who_added_the_bot(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    """``my_chat_member`` carries ``from_user``. It is not stored, and that is enforced here.

    This is the assertion behind ``test_privacy_constraints.py``'s paragraph naming this table
    as being in NEITHER of its two sets. That exemption rests on every column being about a
    GROUP, and the field that would break it is handed to us for free by the update that creates
    these rows: the Telegram id, first name and ``@handle`` of the person who added the bot.
    Storing it would make this a personal-data table needing an erasure route and an answer to
    what ``/forget`` does to a group somebody else still uses.

    Checked by column NAME rather than by reading the model, because the failure mode is a
    future writer adding "just the id" — and a test that only read the docstring would not
    notice. The one human name permitted is ``selected_by_username``, an operator's own login.
    """
    # Arrange / Act
    columns = {column.name for column in BotChatRow.__table__.columns}

    # Assert — no column names a person, and none holds a customer's Telegram id.
    assert "telegram_user_id" not in columns
    assert not [name for name in columns if "added_by" in name or "from_user" in name]
    assert {name for name in columns if name.endswith("_username")} == {"selected_by_username"}
    # And no retention clock: the suffix is a published legal schedule in this codebase, and
    # nothing sweeps this table. See the paragraph in test_privacy_constraints.py.
    assert not [name for name in columns if name.endswith("expires_at")]
