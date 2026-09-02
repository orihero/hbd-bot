"""What every step does when the draft is gone — an evicted key, a flushed Redis, a redeploy.

The rule is the same everywhere: say so in the user's language, clear the state, and never
let a handler read a half-present draft.
"""

from __future__ import annotations

import pytest
from aiogram import Bot, Dispatcher
from aiogram.exceptions import TelegramForbiddenError
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.methods import SendMessage

from hbd.bot.app import build_dispatcher
from hbd.bot.callbacks import (
    GenreCB,
    LanguageCB,
    LanguageSlot,
    NavAction,
    NavCB,
    OccasionCB,
    VocalGenderCB,
)
from hbd.bot.deps import BotDeps
from hbd.bot.i18n import translate
from hbd.bot.states import Wizard
from hbd.config import Settings
from hbd.contracts import MAX_RECIPIENT_NAME_CHARS, Genre, Language, Occasion, VoiceGender
from tests.test_bot.conftest import (
    CHAT_ID,
    RecordingContentWriter,
    RecordingSession,
    RecordingSubmitter,
    buttons,
    callback_update,
    message_update,
)
from tests.test_bot.test_wizard_flow import press, walk_to_confirm

EXPIRED = translate("wizard.expired", Language.UZ_LATN)


@pytest.mark.parametrize(
    ("state_value", "data"),
    [
        (Wizard.ui_language, LanguageCB(slot=LanguageSlot.UI, code=Language.EN).pack()),
        (Wizard.occasion, OccasionCB(value=Occasion.BIRTHDAY).pack()),
        (Wizard.genre, GenreCB(value=Genre.POP).pack()),
        (Wizard.vocal_gender, VocalGenderCB(value=VoiceGender.MALE).pack()),
        (Wizard.note, NavCB(action=NavAction.SKIP).pack()),
        (Wizard.name_confirm, NavCB(action=NavAction.NAME_OK).pack()),
        (Wizard.confirm, NavCB(action=NavAction.CONFIRM).pack()),
        (Wizard.occasion, NavCB(action=NavAction.BACK).pack()),
        (Wizard.name_confirm, NavCB(action=NavAction.RETYPE).pack()),
        (
            Wizard.output_language,
            LanguageCB(slot=LanguageSlot.OUTPUT, code=Language.RU).pack(),
        ),
        (Wizard.lyrics, NavCB(action=NavAction.LYRICS_OK).pack()),
        (Wizard.lyrics, NavCB(action=NavAction.REGENERATE).pack()),
    ],
)
async def test_a_button_with_no_draft_reports_an_expired_session(
    dispatcher: Dispatcher,
    bot: Bot,
    session: RecordingSession,
    state: FSMContext,
    state_value: State,
    data: str,
) -> None:
    # Arrange — a live state with no draft behind it
    await state.set_state(state_value)

    # Act
    await dispatcher.feed_update(bot, callback_update(data))

    # Assert
    assert session.last_screen.text == EXPIRED
    assert await state.get_state() is None


@pytest.mark.parametrize("state_value", [Wizard.note, Wizard.name, Wizard.lyrics])
async def test_typed_text_with_no_draft_reports_an_expired_session(
    dispatcher: Dispatcher,
    bot: Bot,
    session: RecordingSession,
    state: FSMContext,
    state_value: State,
) -> None:
    # Arrange
    await state.set_state(state_value)

    # Act
    await dispatcher.feed_update(bot, message_update("Aziza"))

    # Assert
    assert session.last_screen.text == EXPIRED


async def test_a_non_text_message_with_no_draft_reports_an_expired_session(
    dispatcher: Dispatcher, bot: Bot, session: RecordingSession, state: FSMContext
) -> None:
    # Arrange
    from aiogram.types import Update

    from tests.test_bot.conftest import make_non_text_message

    await state.set_state(Wizard.name)

    # Act
    await dispatcher.feed_update(bot, Update(update_id=8_100, message=make_non_text_message()))

    # Assert
    assert session.last_screen.text == EXPIRED


async def test_name_confirmation_with_a_draft_that_lost_its_name_asks_again(
    dispatcher: Dispatcher, bot: Bot, session: RecordingSession, state: FSMContext
) -> None:
    # Arrange — a draft that never got a name, parked on the confirmation step
    from hbd.bot.draft import WizardDraft

    await state.set_state(Wizard.name_confirm)
    await state.update_data(**WizardDraft(ui_language=Language.EN).to_state_data())

    # Act
    await press(dispatcher, bot, NavCB(action=NavAction.NAME_OK).pack())

    # Assert
    assert session.last_screen.text == translate(
        "wizard.name.prompt", Language.EN, limit=MAX_RECIPIENT_NAME_CHARS
    )
    assert await state.get_state() == Wizard.name.state


async def test_the_expired_screen_offers_a_way_back_in(
    dispatcher: Dispatcher, bot: Bot, session: RecordingSession, state: FSMContext
) -> None:
    """An expired session is the end of a flow, and a flow may not end in a dead end.

    Before this button the only exit was a ``/start`` the customer had to know about and
    type, which is the shape of a message people close instead of answering.
    """
    # Arrange — a live state with no draft behind it
    await state.set_state(Wizard.confirm)

    # Act
    await press(dispatcher, bot, NavCB(action=NavAction.CONFIRM).pack())

    # Assert
    offered = {data for _, data in buttons(session.last_screen.reply_markup)}
    assert NavCB(action=NavAction.START_OVER).pack() in offered


async def test_a_corrupt_draft_is_treated_as_expired(
    dispatcher: Dispatcher, bot: Bot, session: RecordingSession, state: FSMContext
) -> None:
    # Arrange — what a schema change or a hand-edited key looks like
    await state.set_state(Wizard.occasion)
    await state.update_data(draft={"ui_language": "klingon"})

    # Act
    await press(dispatcher, bot, OccasionCB(value=Occasion.BIRTHDAY).pack())

    # Assert
    assert session.last_screen.text == EXPIRED


async def test_confirm_falls_back_to_a_new_message_when_the_edit_is_refused(
    settings: Settings, bot: Bot, session: RecordingSession
) -> None:
    # Arrange
    submitter = RecordingSubmitter()
    dispatcher = build_dispatcher(
        BotDeps(settings=settings, submitter=submitter, content=RecordingContentWriter()),
        storage=MemoryStorage(),
    )
    await walk_to_confirm(dispatcher, bot)
    session.failures["EditMessageText"] = TelegramForbiddenError(
        method=SendMessage(chat_id=CHAT_ID, text="x"), message="message can't be edited"
    )

    # Act
    await press(dispatcher, bot, NavCB(action=NavAction.CONFIRM).pack())

    # Assert — the order still goes out, pointed at the freshly sent message
    assert len(submitter.submitted) == 1
    _, chat_id, progress_message_id = submitter.submitted[0]
    assert chat_id == CHAT_ID
    assert progress_message_id


async def test_confirm_reports_failure_when_no_progress_message_can_be_posted(
    settings: Settings, bot: Bot, session: RecordingSession
) -> None:
    # Arrange
    submitter = RecordingSubmitter()
    dispatcher = build_dispatcher(
        BotDeps(settings=settings, submitter=submitter, content=RecordingContentWriter()),
        storage=MemoryStorage(),
    )
    await walk_to_confirm(dispatcher, bot)
    blocked = TelegramForbiddenError(
        method=SendMessage(chat_id=CHAT_ID, text="x"), message="bot was blocked by the user"
    )
    session.failures["EditMessageText"] = blocked
    session.failures["SendMessage"] = blocked

    # Act — must not raise, and must not queue work nobody can receive
    await press(dispatcher, bot, NavCB(action=NavAction.CONFIRM).pack())

    # Assert
    assert submitter.submitted == []
