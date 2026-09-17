"""``my_chat_member``: the churn source that must never raise and must never guess.

Every update here is fed through a REAL dispatcher built by ``build_dispatcher``, not handed
straight to the handler function, because two of the four things that can silently break this
source live in the wiring rather than in the body: the private-chat filter, and whether
Telegram is asked for the update type at all.

The other two are in the body and are asserted the same way: an unrecognised status must be
loud and write nothing, and a store that fails must not take the handler down with it — there
is no ``ErrorGuardMiddleware`` on this observer, so an escaping exception would be logged by
aiogram and lost, in a chat where the customer has just blocked the bot and would see nothing
either way.
"""

from __future__ import annotations

from dataclasses import dataclass, field, fields
from datetime import UTC, datetime

import pytest
from aiogram import Bot
from aiogram.enums import ChatMemberStatus, ChatType
from aiogram.types import (
    Chat,
    ChatMemberBanned,
    ChatMemberLeft,
    ChatMemberMember,
    ChatMemberOwner,
    ChatMemberRestricted,
    ChatMemberUpdated,
    Update,
    User,
)

from bayram.bot.app import build_dispatcher
from bayram.bot.deps import BotDeps
from bayram.bot.gate import InboundGateMiddleware
from bayram.bot.handlers.membership import GROUP_CHAT_TYPES
from bayram.bot_chats import BotChatSnapshot, MembershipSighting, SupportGroupTarget
from bayram.config import Settings
from bayram.contracts import (
    BotBlockSource,
    BotChatStatus,
    BotChatType,
    Result,
    err,
    ok,
)
from bayram.errors import StorageError
from tests.test_bot.conftest import (
    BOT_ID,
    CHAT_ID,
    FIXED_MOMENT,
    RecordingContentWriter,
    RecordingSubmitter,
)

pytestmark = pytest.mark.anyio

#: Telegram's own stamp on the transition, deliberately NOT ``FIXED_MOMENT``: the handler must
#: use the update's instant and not the bot's clock, and two different values are the only way
#: to tell those apart.
_TRANSITION_AT: datetime = datetime(2026, 3, 21, 11, 30, tzinfo=UTC)


@dataclass
class RecordingBlocks:
    """A ``BotBlockRecorder`` that writes nothing and remembers everything.

    ``answer`` is what the store returns, so one fake covers all three outcomes the handler
    logs differently: a recorded transition, an account already in that state, and a failure.
    """

    answer: Result[bool] = field(default_factory=lambda: ok(True))
    blocked: list[tuple[int, datetime, BotBlockSource]] = field(default_factory=list)
    unblocked: list[tuple[int, datetime, BotBlockSource]] = field(default_factory=list)

    async def record_bot_blocked(
        self, telegram_user_id: int, *, at: datetime, source: BotBlockSource
    ) -> Result[bool]:
        self.blocked.append((telegram_user_id, at, source))
        return self.answer

    async def record_bot_unblocked(
        self, telegram_user_id: int, *, at: datetime, source: BotBlockSource
    ) -> Result[bool]:
        self.unblocked.append((telegram_user_id, at, source))
        return self.answer

    @property
    def calls(self) -> int:
        return len(self.blocked) + len(self.unblocked)


def _deps(settings: Settings, recorder: RecordingBlocks | None) -> BotDeps:
    """Deliberately WITHOUT ``profiles``: this observer never reaches onboarding."""
    return BotDeps(
        settings=settings,
        submitter=RecordingSubmitter(),
        content=RecordingContentWriter(),
        bot_blocks=recorder,
    )


def _membership_update(
    *,
    status: ChatMemberStatus,
    chat_type: str = "private",
    chat_id: int = CHAT_ID,
) -> Update:
    """One ``my_chat_member`` update, as Telegram sends it for a one-to-one chat."""
    chat = Chat(id=chat_id, type=chat_type)
    who = User(id=chat_id, is_bot=False, first_name="Dilnoza")
    me = User(id=BOT_ID, is_bot=True, first_name="Bayram")
    old = ChatMemberMember(user=me, status=ChatMemberStatus.MEMBER)
    new: ChatMemberBanned | ChatMemberMember | ChatMemberLeft | ChatMemberRestricted
    if status is ChatMemberStatus.KICKED:
        new = ChatMemberBanned(user=me, status=status, until_date=_TRANSITION_AT)
    elif status is ChatMemberStatus.MEMBER:
        new = ChatMemberMember(user=me, status=status)
    elif status is ChatMemberStatus.LEFT:
        new = ChatMemberLeft(user=me, status=status)
    else:
        new = ChatMemberRestricted(
            user=me,
            status=ChatMemberStatus.RESTRICTED,
            is_member=True,
            until_date=_TRANSITION_AT,
            can_send_messages=False,
            can_send_audios=False,
            can_send_documents=False,
            can_send_photos=False,
            can_send_videos=False,
            can_send_video_notes=False,
            can_send_voice_notes=False,
            can_send_polls=False,
            can_send_other_messages=False,
            can_add_web_page_previews=False,
            can_change_info=False,
            can_invite_users=False,
            can_pin_messages=False,
            can_manage_topics=False,
            can_react_to_messages=False,
            can_edit_tag=False,
        )
    return Update(
        update_id=90_001,
        my_chat_member=ChatMemberUpdated(
            chat=chat,
            from_user=who,
            date=_TRANSITION_AT,
            old_chat_member=old,
            new_chat_member=new,
        ),
    )


async def test_a_customer_blocking_the_bot_is_recorded_once_with_telegrams_own_instant(
    settings: Settings, bot: Bot
) -> None:
    """``KICKED`` in a private chat is Telegram's wording for "the user blocked the bot"."""
    # Arrange
    recorder = RecordingBlocks()
    dispatcher = build_dispatcher(_deps(settings, recorder))

    # Act
    await dispatcher.feed_update(bot, _membership_update(status=ChatMemberStatus.KICKED))

    # Assert
    assert recorder.unblocked == []
    assert recorder.blocked == [(CHAT_ID, _TRANSITION_AT, BotBlockSource.MEMBERSHIP_UPDATE)]
    # The instant is Telegram's, not the bot's clock — the two differ on purpose here.
    assert _TRANSITION_AT != FIXED_MOMENT


async def test_a_customer_coming_back_is_recorded_as_an_unblock(
    settings: Settings, bot: Bot
) -> None:
    # Arrange
    recorder = RecordingBlocks()
    dispatcher = build_dispatcher(_deps(settings, recorder))

    # Act
    await dispatcher.feed_update(bot, _membership_update(status=ChatMemberStatus.MEMBER))

    # Assert
    assert recorder.blocked == []
    assert recorder.unblocked == [(CHAT_ID, _TRANSITION_AT, BotBlockSource.MEMBERSHIP_UPDATE)]


@pytest.mark.parametrize("chat_type", ["group", "supergroup", "channel"])
async def test_a_group_membership_change_records_nothing(
    settings: Settings, bot: Bot, chat_type: str
) -> None:
    """THE FILTER IS THE CORRECTNESS CONDITION, so it is asserted and not assumed.

    Only in a PRIVATE chat is ``chat.id`` a Telegram user id. A group's is a negative number,
    and recording it would mint a phantom ``users`` row that no customer corresponds to —
    polluting the churn gauge and every account-shaped aggregate the panel draws.
    """
    # Arrange
    recorder = RecordingBlocks()
    dispatcher = build_dispatcher(_deps(settings, recorder))

    # Act
    await dispatcher.feed_update(
        bot,
        _membership_update(status=ChatMemberStatus.KICKED, chat_type=chat_type, chat_id=-100_777),
    )

    # Assert
    assert recorder.calls == 0


@pytest.mark.parametrize("status", [ChatMemberStatus.LEFT, ChatMemberStatus.RESTRICTED])
async def test_a_status_this_handler_does_not_understand_writes_nothing(
    settings: Settings, bot: Bot, status: ChatMemberStatus
) -> None:
    """One handler and not two filtered registrations, so this case is LOUD rather than lost.

    Telegram's member statuses are not a closed set this code controls. Two status-filtered
    registrations would let an unrecognised one fall through with no trace at all; one
    handler makes it a warning naming the status.
    """
    # Arrange
    recorder = RecordingBlocks()
    dispatcher = build_dispatcher(_deps(settings, recorder))

    # Act
    await dispatcher.feed_update(bot, _membership_update(status=status))

    # Assert
    assert recorder.calls == 0


async def test_an_unwired_deployment_records_nothing_and_raises_nothing(
    settings: Settings, bot: Bot
) -> None:
    """``bot_blocks=None`` is "this deployment does not record churn", not a degraded state."""
    # Arrange
    dispatcher = build_dispatcher(_deps(settings, None))

    # Act / Assert — the absence of an exception IS the assertion.
    await dispatcher.feed_update(bot, _membership_update(status=ChatMemberStatus.KICKED))


@pytest.mark.parametrize(
    "answer",
    [
        ok(False),
        err(StorageError("the database is unreachable")),
    ],
    ids=["already_in_that_state", "storage_failed"],
)
async def test_neither_a_no_op_nor_a_failure_escapes_the_handler(
    settings: Settings, bot: Bot, answer: Result[bool]
) -> None:
    """This observer has no error guard, so the handler must be incapable of raising.

    ``Ok(False)`` is the ordinary outcome once the worker's delivery arm has already claimed
    the transition; an ``Err`` is a storage failure. Both are logged and neither may reach
    aiogram's error middleware, where they would be swallowed in a chat the customer can no
    longer see anyway.
    """
    # Arrange
    recorder = RecordingBlocks(answer=answer)
    dispatcher = build_dispatcher(_deps(settings, recorder))

    # Act
    await dispatcher.feed_update(bot, _membership_update(status=ChatMemberStatus.KICKED))

    # Assert — it was attempted, and nothing blew up.
    assert recorder.calls == 1


def test_the_dispatcher_asks_telegram_for_my_chat_member_updates(settings: Settings) -> None:
    """The wiring fact that keeps this whole source alive, and would kill it silently.

    ``start_polling`` resolves ``allowed_updates`` from the registered observers when it is
    left UNSET, so registering the handler is what makes Telegram send the update at all. A
    future change that passes an explicit list without this entry stops churn being recorded
    from this source with no error anywhere — the numbers just stop rising.
    """
    # Arrange / Act
    dispatcher = build_dispatcher(_deps(settings, RecordingBlocks()))

    # Assert
    assert "my_chat_member" in dispatcher.resolve_used_update_types()


def test_the_inbound_gate_is_not_installed_on_the_membership_observer(
    settings: Settings,
) -> None:
    """Two reasons, each sufficient, and both silent if this ever changes.

    The gate's ``TouchDrain`` would stamp ``last_seen_at`` from a BLOCK — feeding the
    active-user series with the one event that disproves it — and its block check would
    refuse the update outright for a barred account, so the churn of exactly the accounts an
    operator most wants to see leave would go unrecorded.
    """
    # Arrange / Act
    dispatcher = build_dispatcher(_deps(settings, RecordingBlocks()))

    def gates(observer_middlewares: object) -> list[object]:
        return [
            middleware
            for middleware in getattr(observer_middlewares, "_middlewares", [])
            if isinstance(middleware, InboundGateMiddleware)
        ]

    # Assert — present on the two customer-facing observers, absent on the third.
    assert gates(dispatcher.message.outer_middleware) != []
    assert gates(dispatcher.callback_query.outer_middleware) != []
    assert gates(dispatcher.my_chat_member.outer_middleware) == []
    assert gates(dispatcher.my_chat_member.middleware) == []


def test_the_membership_router_is_the_only_one_on_that_observer(settings: Settings) -> None:
    """Its position in the include list is not load-bearing, and this is why.

    Every other ordering argument in ``bayram.bot.handlers`` is about ``message`` and
    ``callback_query``. This router touches neither, so it can neither swallow an update from
    that ladder nor be swallowed by it — which is what makes it safe to list first.
    """
    # Arrange / Act
    dispatcher = build_dispatcher(_deps(settings, RecordingBlocks()))
    (root,) = dispatcher.sub_routers

    # Assert
    with_handlers = [router.name for router in root.sub_routers if router.my_chat_member.handlers]
    assert with_handlers == ["membership"]


# ---------------------------------------------------------------------------
# The other half: which rooms the bot is standing in
# ---------------------------------------------------------------------------
#: The group the bot is added to. NEGATIVE, because that is what a supergroup id is, and a
#: fixture using a positive one would be a fixture about a private chat.
_GROUP_ID: int = -1_002_345_678_901
_GROUP_TITLE: str = "Bayram support"
_GROUP_USERNAME: str = "bayram_support"


@dataclass
class RecordingBotChats:
    """A ``BotChatDirectory`` that writes nothing and remembers every sighting.

    ``answer`` covers the three outcomes the handler logs differently — a first sighting, a
    repeat, and a storage failure — the way :class:`RecordingBlocks` does for churn. The other
    four protocol methods are never reached from this observer and say so by returning the
    emptiest true thing they can: a handler that started calling one of them would be a handler
    doing something this registration has no business doing.
    """

    answer: Result[bool] = field(default_factory=lambda: ok(True))
    sightings: list[MembershipSighting] = field(default_factory=list)
    clocks: list[datetime] = field(default_factory=list)

    async def record_membership(
        self, sighting: MembershipSighting, *, now: datetime
    ) -> Result[bool]:
        self.sightings.append(sighting)
        self.clocks.append(now)
        return self.answer

    async def selected_support_group(self) -> Result[SupportGroupTarget | None]:
        return ok(None)

    async def load_chat(self, chat_id: int) -> Result[BotChatSnapshot | None]:
        return ok(None)

    async def record_verified(
        self,
        chat_id: int,
        *,
        at: datetime,
        title: str | None = None,
        username: str | None = None,
        chat_type: BotChatType | None = None,
    ) -> Result[bool]:
        return ok(True)

    async def record_verification_failed(
        self, chat_id: int, *, message: str, at: datetime
    ) -> Result[bool]:
        return ok(True)

    @property
    def only(self) -> MembershipSighting:
        assert len(self.sightings) == 1, self.sightings
        return self.sightings[0]


def _deps_with_directory(
    settings: Settings,
    directory: RecordingBotChats | None,
    *,
    recorder: RecordingBlocks | None = None,
) -> BotDeps:
    """Both recorders on one container, because both registrations are on one router."""
    return BotDeps(
        settings=settings,
        submitter=RecordingSubmitter(),
        content=RecordingContentWriter(),
        clock=lambda: FIXED_MOMENT,
        bot_blocks=recorder,
        bot_chats=directory,
    )


def _group_update(
    *,
    status: ChatMemberStatus = ChatMemberStatus.MEMBER,
    chat_type: str = "supergroup",
    chat_id: int = _GROUP_ID,
    title: str | None = _GROUP_TITLE,
    username: str | None = _GROUP_USERNAME,
) -> Update:
    """One ``my_chat_member`` update about the BOT's own standing in a room.

    ``from_user`` is present and is a real person — the one who added the bot — because that is
    what Telegram actually sends. It is here so that the test asserting it never reaches storage
    has something to assert about.
    """
    me = User(id=BOT_ID, is_bot=True, first_name="Bayram")
    new: ChatMemberBanned | ChatMemberMember | ChatMemberLeft | ChatMemberOwner
    if status is ChatMemberStatus.KICKED:
        new = ChatMemberBanned(user=me, status=status, until_date=_TRANSITION_AT)
    elif status is ChatMemberStatus.LEFT:
        new = ChatMemberLeft(user=me, status=status)
    elif status is ChatMemberStatus.CREATOR:
        new = ChatMemberOwner(user=me, status=status, is_anonymous=False)
    else:
        new = ChatMemberMember(user=me, status=ChatMemberStatus.MEMBER)
    return Update(
        update_id=_next_update_id(),
        my_chat_member=ChatMemberUpdated(
            chat=Chat(id=chat_id, type=chat_type, title=title, username=username),
            from_user=User(id=777_001, is_bot=False, first_name="Aziz", username="aziz"),
            date=_TRANSITION_AT,
            old_chat_member=ChatMemberLeft(user=me, status=ChatMemberStatus.LEFT),
            new_chat_member=new,
        ),
    )


_group_update_id = 91_000


def _next_update_id() -> int:
    global _group_update_id
    _group_update_id += 1
    return _group_update_id


async def test_a_group_the_bot_is_added_to_is_recorded_with_both_clocks(
    settings: Settings, bot: Bot
) -> None:
    """THE ONLY AUTOMATIC ROUTE BY WHICH THIS SYSTEM EVER LEARNS A GROUP EXISTS.

    Telegram has no "list my groups" API, so this update is it. Both clocks are asserted because
    both are required and they are easy to collapse into one: ``event.date`` is Telegram's stamp
    on the transition and lands in ``first_seen_at``/``last_seen_at``, while ``deps.clock()`` is
    ours and lands in ``created_at``/``updated_at``. They differ here on purpose — in production
    they can differ by a whole deploy window, because ``delete_webhook(drop_pending_updates=True)``
    throws away every update that arrived while the bot was down.
    """
    # Arrange
    directory = RecordingBotChats()
    dispatcher = build_dispatcher(_deps_with_directory(settings, directory))

    # Act
    await dispatcher.feed_update(bot, _group_update())

    # Assert
    sighting = directory.only
    assert sighting.chat_id == _GROUP_ID
    assert sighting.chat_type is BotChatType.SUPERGROUP
    assert sighting.title == _GROUP_TITLE
    assert sighting.username == _GROUP_USERNAME
    assert sighting.bot_status is BotChatStatus.MEMBER
    assert sighting.at == _TRANSITION_AT
    assert directory.clocks == [FIXED_MOMENT]
    assert _TRANSITION_AT != FIXED_MOMENT


@pytest.mark.parametrize(
    ("chat_type", "expected"),
    [
        ("group", BotChatType.GROUP),
        ("supergroup", BotChatType.SUPERGROUP),
        ("channel", BotChatType.CHANNEL),
    ],
)
async def test_every_room_telegram_has_is_claimed_by_this_registration(
    settings: Settings, bot: Bot, chat_type: str, expected: BotChatType
) -> None:
    """``channel`` is in the filter even though nobody would pick one as the support inbox.

    The bot can be promoted to administrator of a channel and Telegram sends this same update
    when it happens. A type the recorder dropped would be a room an operator added the bot to
    and then could not find any trace of — which is the "the vocabulary moved and nobody found
    out" failure the churn half of this module already argues against.
    """
    # Arrange
    directory = RecordingBotChats()
    dispatcher = build_dispatcher(_deps_with_directory(settings, directory))

    # Act
    await dispatcher.feed_update(bot, _group_update(chat_type=chat_type))

    # Assert
    assert directory.only.chat_type is expected


@pytest.mark.parametrize("status", [ChatMemberStatus.KICKED, ChatMemberStatus.LEFT])
async def test_a_departure_is_recorded_as_carefully_as_an_arrival(
    settings: Settings, bot: Bot, status: ChatMemberStatus
) -> None:
    """There is no status filter here, and its absence is the point.

    A group the bot was thrown out of is a group an operator needs to SEE in the picker —
    usually because it is the one the tickets stopped arriving in. A recorder that only wrote
    the good news would answer "where did the support inbox go?" with silence.
    """
    # Arrange
    directory = RecordingBotChats()
    dispatcher = build_dispatcher(_deps_with_directory(settings, directory))

    # Act
    await dispatcher.feed_update(bot, _group_update(status=status))

    # Assert
    assert directory.only.bot_status is BotChatStatus(status.value)


async def test_a_status_this_recorder_does_not_know_is_stored_rather_than_dropped(
    settings: Settings, bot: Bot
) -> None:
    """``creator`` is the concrete case: a real Telegram status a bot can never hold.

    Being sure of that is not the same as the code being safe when it arrives. Telegram's
    member statuses are not a closed set this code controls, and here the stake is higher than
    it is for churn: the row is the only evidence the chat exists at all, so an unrecognised
    status that dropped the update would take the whole room out of the picker. ``bot_status``
    is evidence and never permission anyway — ``verified_at`` is what says the bot can post —
    so storing a word we do not understand costs nothing.
    """
    # Arrange
    directory = RecordingBotChats()
    dispatcher = build_dispatcher(_deps_with_directory(settings, directory))

    # Act
    await dispatcher.feed_update(bot, _group_update(status=ChatMemberStatus.CREATOR))

    # Assert — recorded, under the member the enum carries for exactly this.
    assert directory.only.bot_status is BotChatStatus.UNKNOWN


async def test_the_sighting_carries_nothing_at_all_about_the_person_who_added_the_bot(
    settings: Settings, bot: Bot
) -> None:
    """``bot_chats`` is a table about ROOMS, and this is the line that keeps it one.

    Telegram sends ``from_user`` on every one of these updates and it is a real human being.
    Storing it would give this table an erasure route to write, a claim to make in
    ``tests/test_db/test_privacy_constraints.py``, and an answer to owe about what ``/forget``
    does to a group other people still use. ``MembershipSighting`` is a slotted frozen dataclass
    carrying six fields, so the field is not merely unwritten — there is nowhere to put it.
    """
    # Arrange
    directory = RecordingBotChats()
    dispatcher = build_dispatcher(_deps_with_directory(settings, directory))

    # Act
    await dispatcher.feed_update(bot, _group_update())

    # Assert
    sighting = directory.only
    carried = {f.name for f in fields(sighting)}
    assert carried == {"chat_id", "chat_type", "title", "username", "bot_status", "at"}
    assert not hasattr(sighting, "from_user")


async def test_a_private_chat_never_reaches_the_directory_and_a_group_never_reaches_churn(
    settings: Settings, bot: Bot
) -> None:
    """THE DISJOINTNESS, asserted in both directions on one dispatcher.

    The two registrations split on the one axis that decides what ``event.chat.id`` MEANS — a
    person or a room. A group reaching the churn recorder mints a phantom ``users`` row keyed on
    a negative number; a private chat reaching the directory would put a person in a table whose
    every column is about a group, and would need a ``private`` member on an enum that
    deliberately has none.
    """
    # Arrange
    directory = RecordingBotChats()
    churn = RecordingBlocks()
    dispatcher = build_dispatcher(_deps_with_directory(settings, directory, recorder=churn))

    # Act
    await dispatcher.feed_update(bot, _membership_update(status=ChatMemberStatus.KICKED))
    await dispatcher.feed_update(bot, _group_update(status=ChatMemberStatus.KICKED))

    # Assert — one each, and neither saw the other's update.
    assert churn.calls == 1
    assert churn.blocked == [(CHAT_ID, _TRANSITION_AT, BotBlockSource.MEMBERSHIP_UPDATE)]
    assert directory.only.chat_id == _GROUP_ID


async def test_an_unwired_directory_records_nothing_and_raises_nothing(
    settings: Settings, bot: Bot
) -> None:
    """``bot_chats=None`` is "this deployment records no chat directory", not a degraded state.

    The same unwired-not-broken posture ``profiles``, ``lyric_budget`` and ``bot_blocks`` take.
    No group is then ever selectable, and the group leg of support is simply off.
    """
    # Arrange
    dispatcher = build_dispatcher(_deps_with_directory(settings, None))

    # Act / Assert — the absence of an exception IS the assertion.
    await dispatcher.feed_update(bot, _group_update())


@pytest.mark.parametrize(
    "answer",
    [ok(False), err(StorageError("the database is unreachable"))],
    ids=["already_known", "storage_failed"],
)
async def test_neither_a_repeat_sighting_nor_a_failure_escapes_the_group_handler(
    settings: Settings, bot: Bot, answer: Result[bool]
) -> None:
    """This observer has no error guard either, so this handler must be incapable of raising.

    ``Ok(False)`` is the ordinary answer for every sighting after the first — a promotion, a
    re-add after a deploy, a redelivered update — and an ``Err`` is a storage failure. Both are
    logged, and neither may reach aiogram's error middleware, where it would be swallowed in a
    room nobody is waiting on an answer in.
    """
    # Arrange
    directory = RecordingBotChats(answer=answer)
    dispatcher = build_dispatcher(_deps_with_directory(settings, directory))

    # Act
    await dispatcher.feed_update(bot, _group_update())

    # Assert — it was attempted, and nothing blew up.
    assert len(directory.sightings) == 1


def test_both_registrations_live_on_one_router_and_partition_the_chat_types(
    settings: Settings,
) -> None:
    """One router, two handlers, and the filters between them claim every chat type.

    One router rather than two because ``test_the_membership_router_is_the_only_one_on_that
    _observer`` above is what makes this router's position in ``handlers.build_router`` provably
    not load-bearing — a second router on the same observer would have an ordering, and an
    ordering is a thing somebody has to reason about. The partition is what makes that safe: no
    ``my_chat_member`` update can match both handlers or neither.
    """
    # Arrange / Act
    dispatcher = build_dispatcher(_deps_with_directory(settings, RecordingBotChats()))
    (root,) = dispatcher.sub_routers
    (membership_router,) = [r for r in root.sub_routers if r.my_chat_member.handlers]

    # Assert
    assert len(membership_router.my_chat_member.handlers) == 2
    assert {ChatType.GROUP, ChatType.SUPERGROUP, ChatType.CHANNEL} == GROUP_CHAT_TYPES
    assert ChatType.PRIVATE not in GROUP_CHAT_TYPES
    # Every type a ``Chat`` can actually carry. ``ChatType.SENDER`` is excluded deliberately:
    # it is aiogram's marker for ``InlineQuery.chat_type`` ("the user's own private chat with
    # a bot they are not in a chat with"), it never appears on ``ChatMemberUpdated.chat.type``,
    # and a filter that claimed it would be claiming an update this observer cannot receive.
    assert {ChatType.PRIVATE} | GROUP_CHAT_TYPES == set(ChatType) - {ChatType.SENDER}
