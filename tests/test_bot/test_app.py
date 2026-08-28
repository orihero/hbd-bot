"""Composition root and the catch-all router: no silence, no dead buttons."""

from __future__ import annotations

from aiogram import Bot, Dispatcher
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage

from hbd.bot.app import build_bot, build_dispatcher
from hbd.bot.deps import DEPS_KEY, BotDeps
from hbd.bot.i18n import translate
from hbd.config import Settings
from hbd.contracts import Language
from tests.test_bot.conftest import (
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


def test_build_dispatcher_exposes_the_dependencies_to_handlers(settings: Settings) -> None:
    # Arrange
    deps = BotDeps(settings=settings, submitter=RecordingSubmitter())

    # Act
    dispatcher = build_dispatcher(deps, storage=MemoryStorage())

    # Assert
    assert dispatcher[DEPS_KEY] is deps


def test_two_dispatchers_can_be_built_in_one_process(settings: Settings) -> None:
    # Arrange
    deps = BotDeps(settings=settings, submitter=RecordingSubmitter())

    # Act
    first = build_dispatcher(deps, storage=MemoryStorage())
    second = build_dispatcher(deps, storage=MemoryStorage())

    # Assert — routers are built per dispatcher, never shared
    assert first is not second


async def test_a_stray_message_with_no_session_points_at_start(
    dispatcher: Dispatcher, bot: Bot, session: RecordingSession
) -> None:
    # Arrange / Act
    await send(dispatcher, bot, "hello?")

    # Assert
    assert session.last_screen.text == translate("wizard.expired", Language.UZ_LATN)


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
