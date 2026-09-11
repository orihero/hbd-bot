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

from dataclasses import dataclass, field
from datetime import UTC, datetime

import pytest
from aiogram import Bot
from aiogram.enums import ChatMemberStatus
from aiogram.types import (
    Chat,
    ChatMemberBanned,
    ChatMemberLeft,
    ChatMemberMember,
    ChatMemberRestricted,
    ChatMemberUpdated,
    Update,
    User,
)

from bayram.bot.app import build_dispatcher
from bayram.bot.deps import BotDeps
from bayram.bot.gate import InboundGateMiddleware
from bayram.config import Settings
from bayram.contracts import BotBlockSource, Result, err, ok
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
