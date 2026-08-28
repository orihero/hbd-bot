"""The error guard. A handler that explodes must produce a sentence, not silence."""

from __future__ import annotations

import logging

import pytest
from aiogram import Bot, Dispatcher, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import CallbackQuery, Message

from hbd.bot.deps import DEPS_KEY, BotDeps
from hbd.bot.draft import WizardDraft
from hbd.bot.i18n import translate
from hbd.bot.middleware import ErrorGuardMiddleware, resolve_language
from hbd.config import Settings
from hbd.contracts import Language
from hbd.errors import ModerationRejectedError, ProviderTimeoutError
from tests.test_bot.conftest import (
    RecordingContentWriter,
    RecordingSession,
    RecordingSubmitter,
    callback_update,
    message_update,
)


def exploding_dispatcher(deps: BotDeps, exception: Exception) -> Dispatcher:
    """A dispatcher whose only handler raises, wrapped in the real guard."""
    router = Router(name="exploding")

    async def boom(event: Message | CallbackQuery) -> None:
        raise exception

    router.message.register(boom, Command("boom"))
    router.callback_query.register(boom)

    dispatcher = Dispatcher(storage=MemoryStorage())
    dispatcher[DEPS_KEY] = deps
    guard = ErrorGuardMiddleware()
    dispatcher.message.middleware(guard)
    dispatcher.callback_query.middleware(guard)
    dispatcher.include_router(router)
    return dispatcher


@pytest.mark.parametrize(
    ("exception", "expected_key"),
    [
        (RuntimeError("unexpected"), "error.generic"),
        (ProviderTimeoutError("slow", provider="elevenlabs"), "error.provider_slow"),
        (ModerationRejectedError("nope"), "error.content_not_allowed"),
    ],
)
async def test_exception_becomes_a_localised_message(
    settings: Settings,
    bot: Bot,
    session: RecordingSession,
    exception: Exception,
    expected_key: str,
) -> None:
    # Arrange
    deps = BotDeps(
        settings=settings, submitter=RecordingSubmitter(), content=RecordingContentWriter()
    )
    dispatcher = exploding_dispatcher(deps, exception)

    # Act — must not raise out of feed_update
    await dispatcher.feed_update(bot, message_update("/boom"))

    # Assert
    assert session.last_screen.text == translate(expected_key, Language.UZ_LATN)


async def test_failure_is_logged_with_full_context(
    settings: Settings, bot: Bot, caplog: pytest.LogCaptureFixture
) -> None:
    # Arrange
    deps = BotDeps(
        settings=settings, submitter=RecordingSubmitter(), content=RecordingContentWriter()
    )
    dispatcher = exploding_dispatcher(deps, RuntimeError("kaboom"))

    # Act
    with caplog.at_level(logging.ERROR):
        await dispatcher.feed_update(bot, message_update("/boom"))

    # Assert
    record = next(record for record in caplog.records if record.message == "handler failed")
    assert record.failure.startswith("RuntimeError")  # type: ignore[attr-defined]
    assert record.event_type == "Message"  # type: ignore[attr-defined]
    assert record.exc_info is not None


async def test_a_failing_callback_still_gets_its_spinner_stopped(
    settings: Settings, bot: Bot, session: RecordingSession
) -> None:
    # Arrange
    deps = BotDeps(
        settings=settings, submitter=RecordingSubmitter(), content=RecordingContentWriter()
    )
    dispatcher = exploding_dispatcher(deps, RuntimeError("kaboom"))

    # Act
    await dispatcher.feed_update(bot, callback_update("anything"))

    # Assert
    assert session.named("AnswerCallbackQuery")
    assert session.named("SendMessage")


async def test_resolve_language_reads_the_draft(state: FSMContext) -> None:
    # Arrange
    await state.update_data(**WizardDraft(ui_language=Language.RU).to_state_data())

    # Act
    language = await resolve_language(state)

    # Assert
    assert language is Language.RU


async def test_resolve_language_falls_back_without_a_draft(state: FSMContext) -> None:
    # Arrange / Act
    language = await resolve_language(state)

    # Assert
    assert language is Language.UZ_LATN


async def test_resolve_language_falls_back_without_a_state() -> None:
    # Arrange / Act / Assert
    assert await resolve_language(None) is Language.UZ_LATN
