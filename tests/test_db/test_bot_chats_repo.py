"""The chat-directory statements and the panel's read of them, against a real database.

``test_bot_chats.py`` beside this file asserts the SCHEMA — that the partial unique index
exists and that the engine enforces it. This file asserts the STATEMENTS: that a membership
update cannot unselect the support group, that the selection clears before it sets, that a
pasted id becomes an honest ``manual`` row, and that a verification verdict never invents a row
it was not given.

**THE ONE TEST THIS FILE EXISTS FOR IS "A SIGHTING CANNOT UNSELECT THE SUPPORT GROUP".** Every
other failure here is loud. That one is not: an ``ON CONFLICT DO UPDATE`` that named one column
too many would mean the bot being promoted to administrator in the selected group — or simply
re-added after a deploy — silently clearing ``is_support_group``, and from then on tickets stop
arriving with no failed request, no exception and nothing in any log. The upsert's column list
is the whole guard, a column list is exactly the kind of thing a later edit widens without
thinking, and nothing else in the suite can see it happen.

**Every conditional write is exercised from BOTH sides.** A rowcount-claimed ``UPDATE`` tested
only on its happy path is indistinguishable from an unconditional one: it moves the row, the
rowcount is 1, the test passes, and the ``WHERE`` that was supposed to make a verdict about a
deleted chat a no-op is never run. So :func:`mark_verified` and :func:`mark_verification_failed`
each have a test for the row that is there and one for the row that is not.

**The clock is always injected and never ambient, and there are TWO of them.**
``first_seen_at``/``last_seen_at`` are TELEGRAM's (``ChatMemberUpdated.date``) and
``created_at``/``updated_at`` are ours; passing one for the other is the mistake these tests
pin, because it is invisible in production — both are plausible instants and neither is checked
by anything. ``UtcDateTime`` raises on a naive datetime deep inside the driver, and
``TimestampMixin.onupdate`` never fires on an upsert at all, so the writes set ``updated_at`` by
hand and these tests prove the injected instant is the one that lands.

**Every chat id here is NEGATIVE and outside the 32-bit range**, matching
``test_bot_chats.py`` and ``test_support_tickets_repo.py``: a group id is negative and a
supergroup id begins ``-100``, and an accidental ``Integer`` anywhere on this path would not
fail loudly — it would truncate a real supergroup id and the panel would select a chat that
does not exist.

What this file cannot prove is said out loud rather than quietly omitted: it cannot show the
race the partial index exists for. Two overlapping transactions each clearing and re-setting the
selection both commit under Postgres' READ COMMITTED, while SQLite's write lock serialises them
and the suite passes either way. ``admin_users`` carries that measurement; this file asserts
that the ordinary path never depends on the index firing.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Final

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from bayram.bot_chats import (
    BotChatDirectory,
    BotChatSnapshot,
    MembershipSighting,
    SelectionChange,
    chat_type_for_pasted_id,
)
from bayram.contracts import BotChatSource, BotChatStatus, BotChatType, Err, Ok
from bayram.db.admin.bot_chats import list_bot_chats, selected_bot_chat
from bayram.db.bot_chats import (
    SqlBotChats,
    clear_support_group,
    load_chat,
    mark_verification_failed,
    mark_verified,
    record_membership,
    select_support_group,
    selected_chat_id,
    selected_support_group,
)
from bayram.db.models.bot_chat import VERIFICATION_ERROR_LENGTH
from bayram.errors import ValidationError

#: Mid-day and mid-month, so a test that advances a day cannot pass on a boundary.
_NOON: Final[datetime] = datetime(2026, 9, 15, 12, 0, tzinfo=UTC)
#: Telegram's stamp on the transition — deliberately EARLIER than any of our own clocks below,
#: because the gap between the two is real: ``delete_webhook(drop_pending_updates=True)`` throws
#: away everything that arrived while the bot was down, so a row is often written long after the
#: event it describes. A test where the two clocks coincide could not tell them apart.
_EVENT_AT: Final[datetime] = _NOON - timedelta(hours=3)

#: Two supergroups: the inbox in use and the one before it. Well outside 2**31, both negative.
_GROUP: Final[int] = -1_002_345_678_901
_OTHER_GROUP: Final[int] = -1_009_876_543_210
#: A basic group, which Telegram numbers WITHOUT the ``-100`` prefix and upgrades to a
#: supergroup on its own — the event that mints a new id and leaves the old row selected.
_BASIC_GROUP: Final[int] = -876_543_210
#: An id nothing has ever recorded. The pasted-id path, which exists because Telegram has no
#: "list my groups" API and a group the bot was already in can arrive no other way.
_UNKNOWN_GROUP: Final[int] = -1_001_111_222_333

_OPERATOR: Final[str] = "dilnoza"
_SECOND_OPERATOR: Final[str] = "alisher"


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------
def _sighting(
    chat_id: int = _GROUP,
    *,
    chat_type: BotChatType = BotChatType.SUPERGROUP,
    title: str | None = "Bayram support",
    username: str | None = None,
    bot_status: BotChatStatus = BotChatStatus.MEMBER,
    at: datetime = _EVENT_AT,
) -> MembershipSighting:
    """One ``my_chat_member`` update about a group, as the handler would reduce it.

    ``member`` is the default because it is what the overwhelming majority of these updates
    say. A factory that defaulted to ``administrator`` would make the promotion tests — the ones
    that matter — look like the ordinary case.
    """
    return MembershipSighting(
        chat_id=chat_id,
        chat_type=chat_type,
        title=title,
        username=username,
        bot_status=bot_status,
        at=at,
    )


async def _record(
    sessions: async_sessionmaker[AsyncSession],
    sighting: MembershipSighting,
    *,
    now: datetime = _NOON,
) -> bool:
    """Commit one sighting, the way the facade does."""
    async with sessions.begin() as session:
        return await record_membership(session, sighting, now=now)


async def _select(
    sessions: async_sessionmaker[AsyncSession],
    chat_id: int,
    *,
    thread_id: int | None = None,
    who: str = _OPERATOR,
    now: datetime = _NOON,
) -> SelectionChange:
    """Commit one selection, the way the admin router does — one transaction, both halves."""
    async with sessions.begin() as session:
        return await select_support_group(
            session, chat_id, thread_id=thread_id, selected_by_username=who, now=now
        )


async def _load(sessions: async_sessionmaker[AsyncSession], chat_id: int) -> BotChatSnapshot:
    """Read one chat back through a FRESH transaction, and insist it is there.

    Fresh because a Core ``UPDATE`` does not touch the session's identity map: read inside the
    writing transaction, a stale object would answer every assertion below with the values the
    test wrote in the line before.
    """
    async with sessions.begin() as session:
        snapshot = await load_chat(session, chat_id)
    assert snapshot is not None
    return snapshot


# ---------------------------------------------------------------------------
# The membership upsert
# ---------------------------------------------------------------------------
async def test_a_first_sighting_stores_telegram_s_clock_beside_our_own(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    """Two clocks, two meanings, and the row keeps them apart.

    ``first_seen_at``/``last_seen_at`` come from ``ChatMemberUpdated.date`` — the instant
    TELEGRAM stamped the transition — and ``created_at``/``updated_at`` are ours. Collapsing
    them would quietly downgrade Telegram's own stamp to the accuracy of whenever our process
    next happened to be running, and nothing in production would ever notice: both values are
    plausible instants and no screen compares them.
    """
    # Act
    is_new = await _record(sessions, _sighting())

    # Assert
    chat = await _load(sessions, _GROUP)
    assert is_new is True
    assert chat.first_seen_at == _EVENT_AT
    assert chat.last_seen_at == _EVENT_AT
    assert chat.created_at == _NOON
    assert chat.updated_at == _NOON


async def test_a_first_sighting_is_recorded_as_telegram_s_own_word_and_unselected(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    """A recorded chat is a chat, not an inbox. Selection is an operator's act and only theirs.

    ``source`` is ``membership_event`` because Telegram said so, and ``is_support_group`` is
    ``False`` because nobody has chosen anything — the column carries no ``server_default``, so
    this assertion is also the one that would catch a Core ``INSERT`` that forgot to write it.
    """
    # Act
    await _record(sessions, _sighting())

    # Assert
    chat = await _load(sessions, _GROUP)
    assert chat.source is BotChatSource.MEMBERSHIP_EVENT
    assert chat.is_support_group is False
    assert chat.verified_at is None
    assert chat.selected_by_username is None


async def test_a_second_sighting_refreshes_what_telegram_now_says(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    """A renamed group is renamed here, and a promotion is recorded as a promotion.

    The title is the ONLY way an operator tells four negative numbers apart, so a directory that
    kept the name a group had when the bot joined would be a list of chats nobody recognises.
    ``last_seen_at`` moves with Telegram's clock; ``first_seen_at`` does not move at all.
    """
    # Arrange
    await _record(sessions, _sighting())
    later_event = _EVENT_AT + timedelta(days=2)
    later_write = _NOON + timedelta(days=2)

    # Act
    is_new = await _record(
        sessions,
        _sighting(
            title="Bayram support (24/7)",
            username="bayram_support",
            bot_status=BotChatStatus.ADMINISTRATOR,
            at=later_event,
        ),
        now=later_write,
    )

    # Assert
    chat = await _load(sessions, _GROUP)
    assert is_new is False
    assert chat.title == "Bayram support (24/7)"
    assert chat.username == "bayram_support"
    assert chat.bot_status is BotChatStatus.ADMINISTRATOR
    assert chat.first_seen_at == _EVENT_AT
    assert chat.last_seen_at == later_event
    assert chat.updated_at == later_write


async def test_a_sighting_cannot_unselect_the_support_group(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    """THE test in this file. A membership update may not touch the operator's six columns.

    The failure this pins has no symptom on the day it happens. The bot is promoted to
    administrator in the support group — an ordinary, welcome event — or it is simply re-added
    after a restart; the upsert names one column too many; ``is_support_group`` goes back to
    ``False``; and from that moment ticket cards stop being posted. No request failed, no
    exception was raised, nothing appears in any log, and the next person to look at the panel
    sees a directory in which nothing is selected and no reason why.

    So the assertion is over all six: the selection, the topic, who chose it, when they chose
    it, and both verification columns. Telegram's own six are asserted to have moved in the same
    breath, because a test that pinned the first set by accidentally writing nothing at all
    would pass just as well.
    """
    # Arrange: a selected, verified support group with a topic.
    await _record(sessions, _sighting())
    await _select(sessions, _GROUP, thread_id=42)
    async with sessions.begin() as session:
        assert await mark_verified(session, _GROUP, at=_NOON) is True

    # Act: the bot is promoted in that very group.
    promotion_at = _EVENT_AT + timedelta(days=1)
    await _record(
        sessions,
        _sighting(title="Bayram support", bot_status=BotChatStatus.ADMINISTRATOR, at=promotion_at),
        now=_NOON + timedelta(days=1),
    )

    # Assert: the operator's columns are exactly where they were.
    chat = await _load(sessions, _GROUP)
    assert chat.is_support_group is True
    assert chat.thread_id == 42
    assert chat.selected_by_username == _OPERATOR
    assert chat.selected_at == _NOON
    assert chat.verified_at == _NOON
    assert chat.verification_error is None
    # ... and Telegram's columns did move, so this is not a test of a write that never happened.
    assert chat.bot_status is BotChatStatus.ADMINISTRATOR
    assert chat.last_seen_at == promotion_at


async def test_a_sighting_promotes_an_operator_s_claim_to_telegram_s_own_word(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    """``manual`` is an unverified claim; a membership update is evidence that supersedes it.

    The promotion runs in exactly one direction, and only because the one caller of this path
    always passes ``membership_event``. What it buys is that a pasted id stops being rendered as
    a guess the moment Telegram confirms the bot really is in that chat — which is the whole
    difference the panel shows between the two sources.

    ``first_seen_at`` stays at the instant the operator pasted the id, because that is when this
    chat entered the directory; only ``last_seen_at`` moves.
    """
    # Arrange: an operator pastes an id nothing has ever heard of.
    await _select(sessions, _UNKNOWN_GROUP)
    pasted = await _load(sessions, _UNKNOWN_GROUP)
    assert pasted.source is BotChatSource.MANUAL

    # Act: Telegram finally says something about it.
    seen_at = _NOON + timedelta(hours=1)
    await _record(
        sessions,
        _sighting(_UNKNOWN_GROUP, title="Ops", at=seen_at),
        now=_NOON + timedelta(hours=1, minutes=1),
    )

    # Assert
    chat = await _load(sessions, _UNKNOWN_GROUP)
    assert chat.source is BotChatSource.MEMBERSHIP_EVENT
    assert chat.title == "Ops"
    assert chat.first_seen_at == _NOON
    assert chat.last_seen_at == seen_at
    # And the promotion did not take the selection with it.
    assert chat.is_support_group is True


async def test_a_migrated_group_arrives_as_a_second_row(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    """Telegram upgrading a basic group mints a NEW id, and the directory does not rewrite itself.

    ``chat_id`` is the primary key and other tables already hold its value —
    ``support_tickets.group_chat_id`` records which chat each card was posted into, and revision
    0027's card latch is unique per chat precisely BECAUSE this id changes. An ``UPDATE`` that
    moved the id here would make those rows claim cards were posted somewhere they were not, and
    would move the selection to a chat no operator chose.

    So the old row stays selected and dead, and the verification job is what makes that
    recoverable by writing an error naming the new id. This test pins the write layer's half:
    the new chat is a new row and the old selection is untouched.
    """
    # Arrange
    await _record(sessions, _sighting(_BASIC_GROUP, chat_type=BotChatType.GROUP, title="Ops"))
    await _select(sessions, _BASIC_GROUP)

    # Act: Telegram's upgrade arrives as a membership event about a different chat.
    await _record(
        sessions,
        _sighting(_GROUP, title="Ops", at=_EVENT_AT + timedelta(minutes=5)),
        now=_NOON + timedelta(minutes=5),
    )

    # Assert
    old = await _load(sessions, _BASIC_GROUP)
    new = await _load(sessions, _GROUP)
    assert old.is_support_group is True
    assert new.is_support_group is False
    assert new.chat_type is BotChatType.SUPERGROUP


# ---------------------------------------------------------------------------
# The selection
# ---------------------------------------------------------------------------
async def test_selecting_a_known_chat_records_who_chose_it_and_when(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    """The row carries the operator's login, denormalised, with no foreign key behind it.

    A rename must not rewrite who repointed the support inbox, and an operator who leaves must
    not take the record with them — ``admin_audit_log.actor_username``'s rule, and the reason
    this is a string rather than a reference.
    """
    # Arrange
    await _record(sessions, _sighting())

    # Act
    change = await _select(sessions, _GROUP, thread_id=7)

    # Assert
    chat = await _load(sessions, _GROUP)
    assert change == SelectionChange(
        chat_id=_GROUP, previous_chat_id=None, thread_id=7, created=False
    )
    assert change.moved is False
    assert chat.is_support_group is True
    assert chat.thread_id == 7
    assert chat.selected_by_username == _OPERATOR
    assert chat.selected_at == _NOON


async def test_the_selection_moves_and_exactly_one_row_survives_it(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    """Clear, then set, in one transaction — and the index is never the thing that fires.

    Written the other way round this is an ``IntegrityError`` on the ORDINARY path: the new row
    is set while the old one still holds ``true``, and ``ix_bot_chats_selected_support_group``
    refuses it. The index is still needed for the race two operators can run; it is not needed
    for this, and a write that depends on a constraint violation to do its ordinary work is a
    write that reports "somebody else got there first" every time it is used.
    """
    # Arrange
    await _record(sessions, _sighting(_GROUP))
    await _record(sessions, _sighting(_OTHER_GROUP, title="Old support"))
    await _select(sessions, _GROUP)

    # Act
    change = await _select(
        sessions, _OTHER_GROUP, who=_SECOND_OPERATOR, now=_NOON + timedelta(days=1)
    )

    # Assert
    async with sessions.begin() as session:
        assert await selected_chat_id(session) == _OTHER_GROUP
    assert change.previous_chat_id == _GROUP
    assert change.moved is True
    assert (await _load(sessions, _GROUP)).is_support_group is False
    assert (await _load(sessions, _OTHER_GROUP)).is_support_group is True


async def test_the_group_that_lost_the_selection_keeps_its_own_history(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    """Only the boolean moves. ``selected_at`` and ``selected_by_username`` stay where they were.

    "This was once the support group, chosen by this person, on that day" is the most useful
    thing to know about a chat an operator is looking at while wondering where last month's
    tickets went. Clearing those columns would leave the question unanswerable from the
    directory at all.
    """
    # Arrange
    await _record(sessions, _sighting(_GROUP))
    await _record(sessions, _sighting(_OTHER_GROUP, title="Old support"))
    await _select(sessions, _GROUP, thread_id=11)

    # Act
    await _select(sessions, _OTHER_GROUP, who=_SECOND_OPERATOR, now=_NOON + timedelta(days=1))

    # Assert
    demoted = await _load(sessions, _GROUP)
    assert demoted.is_support_group is False
    assert demoted.selected_by_username == _OPERATOR
    assert demoted.selected_at == _NOON
    assert demoted.thread_id == 11


async def test_selecting_an_id_nobody_has_seen_records_it_as_a_manual_claim(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    """One endpoint, not two — and the row it writes is honest about what it is.

    Telegram has no "list my groups" API, so a group the bot was already in when this feature
    shipped can never be discovered and a pasted id is the only route that exists for it. The
    row is born ``manual`` (an operator's claim), ``unknown`` (nobody has told us the bot's
    standing there) and unverified, and both clocks are OUR instant — the paste is the only
    moment this chat has, because there is no Telegram transition behind it to borrow one from.
    """
    # Act
    change = await _select(sessions, _UNKNOWN_GROUP, thread_id=3)

    # Assert
    chat = await _load(sessions, _UNKNOWN_GROUP)
    assert change.created is True
    assert chat.source is BotChatSource.MANUAL
    assert chat.bot_status is BotChatStatus.UNKNOWN
    assert chat.chat_type is BotChatType.SUPERGROUP
    assert chat.title is None
    assert chat.is_support_group is True
    assert chat.thread_id == 3
    assert chat.verified_at is None
    assert chat.first_seen_at == _NOON
    assert chat.last_seen_at == _NOON


async def test_a_pasted_basic_group_id_is_typed_from_its_shape(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    """``chat_type`` is NOT NULL and a bare id carries no type, so the id's shape is the guess.

    Every supergroup and channel id begins ``-100``; a basic group's does not. The guess is
    allowed to be wrong — a channel is indistinguishable from a supergroup here — only because
    the verification job's ``getChat`` overwrites the column with Telegram's own word. Without
    that job this becomes a lie the panel repeats forever, which is why they ship together.
    """
    # Act
    await _select(sessions, _BASIC_GROUP)

    # Assert
    assert (await _load(sessions, _BASIC_GROUP)).chat_type is BotChatType.GROUP
    assert chat_type_for_pasted_id(_GROUP) is BotChatType.SUPERGROUP


async def test_a_non_negative_chat_id_is_refused_before_anything_is_written(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    """A positive Telegram id is a PERSON, and the support inbox may not be pointed at one.

    ``BotChatType`` has no ``private`` member precisely so a private chat is unrepresentable
    here — the churn recorder's ``my_chat_member`` registration owns private chats and the two
    stay structurally disjoint. An operator who pastes their own user id is told they pasted a
    person, rather than having every ticket card quietly delivered to one human being's direct
    messages.

    The refusal happens before the clear, which is the half worth pinning: a validation that ran
    after it would take the inbox down on the way to rejecting the request.
    """
    # Arrange
    await _record(sessions, _sighting())
    await _select(sessions, _GROUP)

    # Act / Assert
    with pytest.raises(ValidationError):
        await _select(sessions, 8_912_345_678_901)
    async with sessions.begin() as session:
        assert await selected_chat_id(session) == _GROUP


async def test_a_selection_must_name_the_operator_who_made_it(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    """An anonymous selection is a repointed inbox nobody can be asked about.

    The tamper-evident record is the ``admin_audit_log`` row, and this column is the
    convenience copy the list screen renders — but a blank one would render as a chat that
    selected itself, which is the one thing that never happens.
    """
    # Act / Assert
    with pytest.raises(ValidationError):
        await _select(sessions, _GROUP, who="   ")


async def test_reselecting_the_same_chat_moves_its_topic_and_is_not_a_move(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    """The topic travels with the selection, because it is meaningless apart from the chat.

    As two environment variables the chat and the thread could be — and eventually would be —
    edited apart, which is a card posted into a topic that does not exist in the group it was
    sent to. One call sets both, and passing no topic means "the group itself" rather than
    "leave whatever was there".

    :attr:`SelectionChange.moved` is ``False``: the tickets are not arriving anywhere new, and
    an audit line saying the inbox moved would be wrong.
    """
    # Arrange
    await _record(sessions, _sighting())
    await _select(sessions, _GROUP, thread_id=11)

    # Act
    change = await _select(sessions, _GROUP, thread_id=None, now=_NOON + timedelta(hours=1))

    # Assert
    chat = await _load(sessions, _GROUP)
    assert change.previous_chat_id == _GROUP
    assert change.moved is False
    assert chat.is_support_group is True
    assert chat.thread_id is None
    assert chat.selected_at == _NOON + timedelta(hours=1)


async def test_a_chat_the_bot_was_thrown_out_of_can_still_be_selected(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    """``bot_status`` is evidence, not permission, so it does not gate the selection.

    The obvious guard — refuse unless the bot is a member — would block the ordinary recovery
    path. ``delete_webhook(drop_pending_updates=True)`` on every start throws away the
    membership updates that arrived while the bot was down, so a group the bot was re-added to
    during a deploy still reads ``kicked`` here and would be unselectable forever. The
    verification job is what says whether the selection actually works.
    """
    # Arrange
    await _record(sessions, _sighting(bot_status=BotChatStatus.KICKED))

    # Act
    await _select(sessions, _GROUP)

    # Assert
    chat = await _load(sessions, _GROUP)
    assert chat.is_support_group is True
    assert chat.bot_status is BotChatStatus.KICKED
    assert chat.verified_at is None


async def test_selecting_a_chat_retires_the_proof_it_earned_the_last_time_round(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    """A verdict describes the CURRENT selection. Selecting is what makes it stale.

    Every other select test in this file seeds a row whose verification columns are already
    null, which is why the first cut of this feature shipped without the reset and nothing
    noticed. This is the row that catches it: group A was the inbox in August and verified then,
    B replaced it, and somebody removed the bot from A meanwhile. An operator selects A today.

    Without the reset the row — and the "Ticket cards go to" header, which reads the same field
    — draw the accent "Posting works" badge for a room the bot was thrown out of. The panel
    deliberately does not poll, so the 403 the job writes a second later changes nothing on
    screen: the one surface that answers "where do my tickets go?" told the operator the room
    had been proved good, and every ticket card from that moment is refused and swallowed.

    ``updated_at`` is asserted so that a future ``select`` which somehow stopped writing the row
    at all could not pass this test by leaving two nulls it never touched.
    """
    # Arrange — A was the inbox in August and was PROVED to work then.
    august = _NOON - timedelta(days=45)
    await _record(sessions, _sighting(_GROUP))
    await _record(sessions, _sighting(_OTHER_GROUP, title="Old support"))
    await _select(sessions, _GROUP, now=august)
    async with sessions.begin() as session:
        assert await mark_verified(session, _GROUP, at=august) is True
    # ... then B took over, and A sat there with its green badge.
    await _select(sessions, _OTHER_GROUP, now=_NOON - timedelta(days=30))
    assert (await _load(sessions, _GROUP)).verified_at == august

    # Act — today, an operator points the inbox back at A.
    await _select(sessions, _GROUP, who=_SECOND_OPERATOR, now=_NOON)

    # Assert — nobody has checked THIS selection, and the row says so.
    chat = await _load(sessions, _GROUP)
    assert chat.is_support_group is True
    assert chat.verified_at is None
    assert chat.verification_error is None
    assert chat.is_verified is False
    assert chat.updated_at == _NOON


async def test_reselecting_a_failed_chat_retires_the_failure_so_a_recheck_is_visible(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    """The mirror case, and it is the one an operator hits on purpose.

    "Check again" is not a route of its own: it is this same call, pressed on the chat that is
    already selected. So an operator who has just restored ``can_post_messages`` in Telegram and
    pressed it must see the red sentence GO — otherwise the screen answers a fixed permission
    with the identical words it showed before, and there is no way to tell whether the check
    ran, whether the fix worked, or whether the button does anything at all.

    The stale error is the more dangerous half of the pair in one specific way: it survives a
    re-select of a chat that is now fine, so the operator's next move is to go looking for a
    problem that no longer exists.
    """
    # Arrange — the selected inbox, with the bot's posting right taken away.
    await _record(sessions, _sighting())
    await _select(sessions, _GROUP, thread_id=11)
    async with sessions.begin() as session:
        assert (
            await mark_verification_failed(
                session, _GROUP, message="the bot cannot post in this chat", at=_NOON
            )
            is True
        )

    # Act — the permission is fixed in Telegram and the operator presses "Check again", which is
    # a select of the chat that is already selected, topic and all.
    change = await _select(sessions, _GROUP, thread_id=11, now=_NOON + timedelta(minutes=5))

    # Assert — back to "checking…", with the selection itself untouched.
    chat = await _load(sessions, _GROUP)
    assert change.moved is False
    assert change.created is False
    assert chat.is_support_group is True
    assert chat.thread_id == 11
    assert chat.verification_error is None
    assert chat.verified_at is None


# ---------------------------------------------------------------------------
# Clearing
# ---------------------------------------------------------------------------
async def test_clearing_reports_what_it_cleared_and_leaves_the_history(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    """Tickets keep working with nothing selected; only the group post stops.

    The returned id is the ``before`` an audit row needs — after the statement it is
    unreadable, because the whole point of the write is that it is gone.
    """
    # Arrange
    await _record(sessions, _sighting())
    await _select(sessions, _GROUP, thread_id=5)

    # Act
    async with sessions.begin() as session:
        cleared = await clear_support_group(session, now=_NOON + timedelta(days=1))

    # Assert
    chat = await _load(sessions, _GROUP)
    assert cleared == _GROUP
    assert chat.is_support_group is False
    assert chat.selected_by_username == _OPERATOR
    assert chat.selected_at == _NOON
    assert chat.thread_id == 5


async def test_clearing_keeps_the_last_verdict_because_nothing_will_produce_another(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    """The boundary of the select's reset, pinned from the other side.

    :func:`select_support_group` nulls both verification columns because it enqueues a job and
    the null pair is what the panel renders as "checking…". Applying the same "tidy-up" here —
    which is exactly what a reader who has just learned the select's rule would do — would be a
    bug rather than consistency: clearing enqueues nothing, so the row would sit at "checking…"
    for ever with no verdict coming, which is the same lie the reset removes, told backwards.

    An unselected chat claims nothing about where tickets go, so its last verdict is history and
    belongs beside ``selected_at`` and ``selected_by_username``, which stay for the same reason.
    """
    # Arrange — a selected inbox that has been proved to work.
    await _record(sessions, _sighting())
    await _select(sessions, _GROUP)
    async with sessions.begin() as session:
        assert await mark_verified(session, _GROUP, at=_NOON) is True

    # Act
    async with sessions.begin() as session:
        assert await clear_support_group(session, now=_NOON + timedelta(days=1)) == _GROUP

    # Assert — unselected, and still carrying what the last check found.
    chat = await _load(sessions, _GROUP)
    assert chat.is_support_group is False
    assert chat.verified_at == _NOON
    assert chat.verification_error is None


async def test_clearing_nothing_is_an_answer_and_not_a_failure(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    """A fresh deployment has never selected anything, and a second clear is not an error.

    ``None`` lets the router answer "there was nothing to clear" without a second read, and
    without turning an idempotent request into a 404 an operator has to interpret.
    """
    # Arrange
    await _record(sessions, _sighting())

    # Act
    async with sessions.begin() as session:
        cleared = await clear_support_group(session, now=_NOON)

    # Assert
    assert cleared is None
    assert (await _load(sessions, _GROUP)).is_support_group is False


# ---------------------------------------------------------------------------
# What the verification job found
# ---------------------------------------------------------------------------
async def test_a_proof_clears_the_stored_failure(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    """The two verification columns are mutually exclusive, and the writers are what keep them so.

    A row showing yesterday's error beside today's proof would make an operator chase a problem
    that has already been fixed — and, in the other direction, trust an inbox that has since
    stopped working.
    """
    # Arrange
    await _record(sessions, _sighting())
    async with sessions.begin() as session:
        await mark_verification_failed(session, _GROUP, message="bot is not a member", at=_NOON)

    # Act
    proved_at = _NOON + timedelta(days=1)
    async with sessions.begin() as session:
        stamped = await mark_verified(session, _GROUP, at=proved_at, title="Bayram support")

    # Assert
    chat = await _load(sessions, _GROUP)
    assert stamped is True
    assert chat.verified_at == proved_at
    assert chat.verification_error is None
    assert chat.is_verified is True


async def test_a_failure_drops_the_stale_proof(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    """The direction that matters. A green badge earned yesterday must not survive today's failure.

    That badge is what an operator reads to decide the inbox is fine, so a chat whose last check
    failed has to stop showing one. What it costs is the instant of the last successful check,
    which is recoverable from ``updated_at`` and from the audit trail, and which nobody has ever
    needed to know.
    """
    # Arrange
    await _record(sessions, _sighting())
    async with sessions.begin() as session:
        await mark_verified(session, _GROUP, at=_NOON)

    # Act
    failed_at = _NOON + timedelta(days=1)
    async with sessions.begin() as session:
        recorded = await mark_verification_failed(
            session,
            _GROUP,
            message=f"this group became supergroup {_OTHER_GROUP}; select the new chat",
            at=failed_at,
        )

    # Assert
    chat = await _load(sessions, _GROUP)
    assert recorded is True
    assert chat.verified_at is None
    assert chat.is_verified is False
    assert chat.verification_error is not None
    # The new id is IN the message: a migrated group is a dead inbox that looks healthy, and the
    # id is the only thing an operator can act on.
    assert str(_OTHER_GROUP) in chat.verification_error


async def test_a_verdict_about_a_chat_that_is_gone_invents_nothing(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    """The loser's side of both conditional writes, which is the side that is never exercised
    by accident.

    A verification result about a chat no longer in the directory is a replayed job running
    against something an operator deleted. Re-creating the row would resurrect a chat somebody
    removed on purpose, and would do it with whatever partial information the job happened to
    hold — a title from ``getChat`` and nothing else.
    """
    # Act
    async with sessions.begin() as session:
        proved = await mark_verified(session, _UNKNOWN_GROUP, at=_NOON, title="Ghost")
        failed = await mark_verification_failed(
            session, _UNKNOWN_GROUP, message="chat not found", at=_NOON
        )
        missing = await load_chat(session, _UNKNOWN_GROUP)

    # Assert
    assert proved is False
    assert failed is False
    assert missing is None


async def test_an_over_long_failure_is_trimmed_to_fit_the_column(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    """A failure that could not be stored is a failure nobody ever sees.

    In-memory SQLite enforces no length whatsoever, so without the trim an over-long message
    would pass every unit test in this suite and raise a ``DataError`` the first time it met
    Postgres — in the job whose entire purpose is to explain why an operator's inbox is broken.
    The trim is visible in the stored value so a reader can tell it happened.
    """
    # Arrange
    await _record(sessions, _sighting())

    # Act
    async with sessions.begin() as session:
        await mark_verification_failed(session, _GROUP, message="x" * 400, at=_NOON)

    # Assert
    stored = (await _load(sessions, _GROUP)).verification_error
    assert stored is not None
    assert len(stored) == VERIFICATION_ERROR_LENGTH
    assert stored.endswith("…")


async def test_a_blank_failure_is_refused(sessions: async_sessionmaker[AsyncSession]) -> None:
    """A red row with nothing to act on is worse than either a real message or no error at all.

    The asymmetry with the trim above is deliberate: too much prose is cut down, because some of
    it is still useful; no prose at all is refused, because none of it is.
    """
    # Arrange
    await _record(sessions, _sighting())

    # Act / Assert
    with pytest.raises(ValidationError):
        async with sessions.begin() as session:
            await mark_verification_failed(session, _GROUP, message="  ", at=_NOON)


async def test_a_proof_touches_neither_the_membership_clock_nor_an_unsupplied_title(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    """A sweep is not a sighting, and a verification must not blank what it was not told.

    ``last_seen_at`` is the MEMBERSHIP clock — the nearest thing to "is this group still live?"
    available to a bot that cannot ask Telegram that question — so a job that stamped it would
    make a chat the bot was thrown out of last week look recently seen because something looked
    at it this morning. And a ``title=None`` that erased the stored name would make the row an
    operator is least able to recognise harder still.
    """
    # Arrange
    await _record(sessions, _sighting(title="Bayram support"))

    # Act
    async with sessions.begin() as session:
        await mark_verified(session, _GROUP, at=_NOON + timedelta(days=3))

    # Assert
    chat = await _load(sessions, _GROUP)
    assert chat.last_seen_at == _EVENT_AT
    assert chat.title == "Bayram support"


# ---------------------------------------------------------------------------
# The read the posting path makes
# ---------------------------------------------------------------------------
async def test_the_target_carries_the_chat_and_its_topic_and_nothing_else(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    """Two fields, because that is what the sender is allowed to know.

    Handed the whole row, a caller would have ``bot_status`` in scope at the exact moment it is
    deciding whether to send — and reading that column as a capability is the one misuse of this
    seam worth naming. There is nothing to decide: the operator chose where, the verification job
    said whether, and the sender sends.
    """
    # Arrange
    await _record(sessions, _sighting())
    await _select(sessions, _GROUP, thread_id=9)

    # Act
    async with sessions.begin() as session:
        target = await selected_support_group(session)

    # Assert
    assert target is not None
    assert (target.chat_id, target.thread_id) == (_GROUP, 9)


async def test_no_selection_is_an_ordinary_answer(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    """``None`` means "do not post", never "something went wrong".

    A fresh deployment has never selected anything and an operator may clear the selection
    deliberately; tickets keep being opened, worked and answered either way. A caller that
    treated this as a failure would surface an incident to a customer who is already complaining
    about something else.
    """
    # Arrange
    await _record(sessions, _sighting())

    # Act
    async with sessions.begin() as session:
        target = await selected_support_group(session)

    # Assert
    assert target is None


# ---------------------------------------------------------------------------
# The facade the bot and the worker hold
# ---------------------------------------------------------------------------
def test_the_sql_implementation_satisfies_the_port(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    """The annotation is the assertion; the ``isinstance`` is only the visible half.

    ``runtime_checkable`` verifies member PRESENCE and never signatures, so the ``isinstance``
    below would pass a facade whose ``record_membership`` took different arguments entirely.
    What actually proves conformance is the declared type of ``directory``: ``mypy --strict``
    checks every method's signature against :class:`~bayram.bot_chats.BotChatDirectory` at this
    line.

    It is here, in this file, rather than being left to the wiring in ``bayram.main`` — which is
    where every other port in this repo is first checked — because the wiring lands in a
    different change than the implementation does. A drift discovered at the wiring line is a
    drift discovered by whoever was doing something else.
    """
    directory: BotChatDirectory = SqlBotChats(sessions)
    assert isinstance(directory, BotChatDirectory)


async def test_the_facade_answers_with_a_result_and_does_not_raise(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    """``SqlBotChats`` is the never-throw boundary: both outcomes come back as values.

    The ``Err`` half is what matters. The ``my_chat_member`` observer carries neither
    ``InboundGateMiddleware`` nor ``ErrorGuardMiddleware``, so an exception escaping a handler is
    logged by aiogram and lost — invisibly, because nobody is waiting on that update. A seam that
    returned a ``Result`` on the happy path and raised on the unhappy one would be no seam at all.
    """
    # Arrange
    directory = SqlBotChats(sessions)

    # Act
    recorded = await directory.record_membership(_sighting(), now=_NOON)
    selected = await directory.selected_support_group()
    chat = await directory.load_chat(_GROUP)
    refused = await directory.record_verification_failed(_GROUP, message="", at=_NOON)

    # Assert
    assert isinstance(recorded, Ok) and recorded.value is True
    assert isinstance(selected, Ok) and selected.value is None
    assert isinstance(chat, Ok) and chat.value is not None
    assert isinstance(refused, Err)
    assert isinstance(refused.error, ValidationError)


async def test_the_facade_commits_each_call_on_its_own(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    """One transaction per method, committed — the bot has no request transaction to join.

    The check is that a SECOND, independent read sees the first call's write. A facade method
    that left its session uncommitted would pass every assertion made inside itself and persist
    nothing at all.
    """
    # Arrange
    directory = SqlBotChats(sessions)
    await directory.record_membership(_sighting(), now=_NOON)

    # Act
    await directory.record_verified(_GROUP, at=_NOON, username="bayram_support")

    # Assert
    chat = await _load(sessions, _GROUP)
    assert chat.verified_at == _NOON
    assert chat.username == "bayram_support"


# ---------------------------------------------------------------------------
# The panel's read
# ---------------------------------------------------------------------------
async def test_the_selected_chat_is_listed_first(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    """The ordering is the answer to the question the screen exists for.

    Ordered only by ``last_seen_at``, the selected group is pushed down the list the moment the
    bot is added to anything else — which is exactly when an operator comes to look, and exactly
    the row they came to check.
    """
    # Arrange
    await _record(sessions, _sighting(_GROUP, title="Support"))
    await _select(sessions, _GROUP)
    await _record(
        sessions,
        _sighting(_OTHER_GROUP, title="Marketing", at=_EVENT_AT + timedelta(days=5)),
        now=_NOON + timedelta(days=5),
    )

    # Act
    async with sessions.begin() as session:
        rows = await list_bot_chats(session)

    # Assert
    assert [row.chat_id for row in rows] == [_GROUP, _OTHER_GROUP]
    assert rows[0].is_support_group is True


async def test_the_panel_row_carries_every_column_the_screen_decides_with(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    """Source, status and the verification state all cross, and they answer different questions.

    ``source`` says whether this is Telegram's word or an operator's claim; ``bot_status`` says
    what Telegram last reported; ``verified_at``/``verification_error`` say whether the bot has
    actually been able to post. A screen that rendered a green badge from ``bot_status`` alone
    would claim a chat works that the bot cannot write a word into — which is the exact failure
    the verification job exists to make visible.
    """
    # Arrange
    await _select(sessions, _UNKNOWN_GROUP, thread_id=4)
    async with sessions.begin() as session:
        await mark_verification_failed(session, _UNKNOWN_GROUP, message="chat not found", at=_NOON)

    # Act
    async with sessions.begin() as session:
        row = await selected_bot_chat(session)

    # Assert
    assert row is not None
    assert row.chat_id == _UNKNOWN_GROUP
    assert row.source is BotChatSource.MANUAL
    assert row.bot_status is BotChatStatus.UNKNOWN
    assert row.is_support_group is True
    assert row.thread_id == 4
    assert row.verified_at is None
    assert row.verification_error == "chat not found"
    assert row.selected_by_username == _OPERATOR


async def test_the_panel_reads_an_empty_directory_without_inventing_one(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    """A deployment that has never been added to a group is the state this table starts in.

    There is no backfill and there cannot be one: Telegram has no "list my groups" API, so the
    table is created empty and fills forward. An empty list and a missing selection are both
    ordinary, and the screen renders them rather than failing.
    """
    # Act
    async with sessions.begin() as session:
        rows = await list_bot_chats(session)
        selected = await selected_bot_chat(session)

    # Assert
    assert rows == ()
    assert selected is None
