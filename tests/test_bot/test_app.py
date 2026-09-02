"""Composition root and the catch-all router: no silence, no dead buttons."""

from __future__ import annotations

from datetime import timedelta

from aiogram import Bot, Dispatcher
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import (
    DisabledEventIsolation,
    MemoryStorage,
    SimpleEventIsolation,
)
from aiogram.fsm.storage.redis import RedisEventIsolation, RedisStorage

from hbd.bot.app import (
    WIZARD_STATE_TTL,
    build_bot,
    build_dispatcher,
    build_event_isolation,
    build_storage,
)
from hbd.bot.deps import DEPS_KEY, BotDeps
from hbd.bot.i18n import translate
from hbd.config import Settings
from hbd.contracts import Language
from hbd.db.retention import DEFAULT_RETENTION_POLICY
from tests.test_bot.conftest import (
    RecordingContentWriter,
    RecordingSession,
    RecordingSubmitter,
    callback_update,
)
from tests.test_bot.test_wizard_flow import send, walk_to_name


def test_build_bot_defaults_to_html_parse_mode(settings: Settings) -> None:
    # Arrange / Act
    bot = build_bot(settings)

    # Assert — every catalogue template and every escape assumes HTML
    assert bot.default.parse_mode == ParseMode.HTML


def test_wizard_state_expires_on_the_abandoned_draft_clock(settings: Settings) -> None:
    """FSM storage holds personal data, so it needs a clock like every other store.

    A draft carries the recipient's display name, the free-text note and the whole approved
    lyric. ``purge_expired`` only ever touches Postgres, so without a TTL an abandoned
    wizard would keep a second copy of all three in Redis forever — outliving both the
    14-day sweep that deletes the order it would have become and the 30-day sweep that
    nulls the lyric it holds.
    """
    # Arrange / Act
    storage = build_storage(settings)

    # Assert
    assert isinstance(storage, RedisStorage)
    assert timedelta(days=DEFAULT_RETENTION_POLICY.abandoned_draft_days) == WIZARD_STATE_TTL
    assert storage.state_ttl == WIZARD_STATE_TTL
    assert storage.data_ttl == WIZARD_STATE_TTL


def test_the_dispatcher_serialises_one_chat_s_updates(settings: Settings) -> None:
    """The lock that makes a state filter a gate rather than a hint.

    aiogram's FSM middleware reads ``raw_state`` once per update, INSIDE this lock, and
    hands it to every filter. With aiogram's default ``DisabledEventIsolation`` there is no
    lock, ``start_polling`` runs handlers as concurrent tasks, and two Confirm taps
    delivered in one ``getUpdates`` batch both read ``Wizard:confirm`` before either
    handler runs. No ordering of awaits inside ``handlers.confirm`` can close that window,
    which is why the fix is here and why this asserts on the wiring rather than on a race.
    """
    # Arrange
    deps = BotDeps(
        settings=settings, submitter=RecordingSubmitter(), content=RecordingContentWriter()
    )

    # Act
    dispatcher = build_dispatcher(deps, storage=MemoryStorage())

    # Assert
    isolation = dispatcher.fsm.events_isolation
    assert not isinstance(isolation, DisabledEventIsolation)
    assert isinstance(isolation, SimpleEventIsolation)


def test_production_locks_in_redis_so_the_lock_spans_processes(settings: Settings) -> None:
    # Arrange — the production branch is "not use_fake_providers"
    live = settings.model_copy(update={"use_fake_providers": False})

    # Act
    isolation = build_event_isolation(live)

    # Assert
    assert isinstance(isolation, RedisEventIsolation)


def test_build_dispatcher_exposes_the_dependencies_to_handlers(settings: Settings) -> None:
    # Arrange
    deps = BotDeps(
        settings=settings, submitter=RecordingSubmitter(), content=RecordingContentWriter()
    )

    # Act
    dispatcher = build_dispatcher(deps, storage=MemoryStorage())

    # Assert
    assert dispatcher[DEPS_KEY] is deps


def test_two_dispatchers_can_be_built_in_one_process(settings: Settings) -> None:
    # Arrange
    deps = BotDeps(
        settings=settings, submitter=RecordingSubmitter(), content=RecordingContentWriter()
    )

    # Act
    first = build_dispatcher(deps, storage=MemoryStorage())
    second = build_dispatcher(deps, storage=MemoryStorage())

    # Assert — routers are built per dispatcher, never shared
    assert first is not second


def test_commands_are_routed_before_the_free_text_steps(settings: Settings) -> None:
    """Ordering is the whole fix for TRUST-11, so it is asserted rather than assumed.

    ``handle_note`` matches any text at the note step. If the command router were included
    after the question router, a ``/help`` typed there would be stored as the fact we know
    about the recipient and sung back to them.
    """
    # Arrange
    deps = BotDeps(
        settings=settings, submitter=RecordingSubmitter(), content=RecordingContentWriter()
    )

    # Act
    dispatcher = build_dispatcher(deps, storage=MemoryStorage())
    (root,) = dispatcher.sub_routers
    names = [router.name for router in root.sub_routers]

    # Assert
    assert "commands" in names, "the command router is not wired into the tree"
    assert names.index("commands") < names.index("questions")
    assert names[-1] == "fallback", "the catch-all must stay last"


async def test_a_stray_message_with_no_session_gets_the_welcome_screen(
    dispatcher: Dispatcher, bot: Bot, session: RecordingSession
) -> None:
    """Text with no session at all is almost always first contact, not an expiry.

    Someone who typed "hello?" before they found ``/start`` has no session to have expired,
    so telling them one did is untrue and leaves them nowhere. They get the screen they
    were trying to reach.
    """
    # Arrange / Act
    await send(dispatcher, bot, "hello?")

    # Assert
    screen = session.last_screen
    assert translate("start.choose_ui_language", Language.UZ_LATN) in screen.text
    assert screen.reply_markup is not None


async def test_a_stray_message_mid_wizard_points_at_the_buttons(
    dispatcher: Dispatcher, bot: Bot, session: RecordingSession
) -> None:
    # Arrange
    await send(dispatcher, bot, "/start")
    session.clear()

    # Act — typing where a button is expected
    await send(dispatcher, bot, "English please")

    # Assert
    assert session.last_screen.text == translate("wizard.use_buttons", Language.UZ_LATN)


async def test_a_stale_button_is_answered_rather_than_left_spinning(
    dispatcher: Dispatcher, bot: Bot, session: RecordingSession
) -> None:
    # Arrange
    await walk_to_name(dispatcher, bot)
    session.clear()

    # Act — an occasion button from a screen the wizard has moved past
    await dispatcher.feed_update(bot, callback_update("occ:birthday"))

    # Assert
    answer = session.last_named("AnswerCallbackQuery")
    assert answer.text == translate("wizard.expired", Language.EN)


async def test_an_unparseable_callback_payload_does_not_reach_a_handler(
    dispatcher: Dispatcher, bot: Bot, session: RecordingSession
) -> None:
    # Arrange / Act
    await dispatcher.feed_update(bot, callback_update("garbage:not-a-payload"))

    # Assert — it lands in the fallback, not in an exception
    assert session.named("AnswerCallbackQuery")
