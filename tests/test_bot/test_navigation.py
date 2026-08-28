"""Back, Retype and Cancel — the buttons that make the wizard safe to explore."""

from __future__ import annotations

from itertools import pairwise

from aiogram import Bot, Dispatcher
from aiogram.fsm.context import FSMContext

from hbd.bot.callbacks import (
    NavAction,
    NavCB,
)
from hbd.bot.draft import DRAFT_KEY
from hbd.bot.i18n import translate
from hbd.bot.states import WIZARD_ORDER, Wizard, WizardStep, previous_step
from hbd.contracts import Genre, Language, Occasion
from tests.test_bot.conftest import RecordingSession, buttons
from tests.test_bot.test_wizard_flow import UZBEK_DISPLAY, UZBEK_TYPED, press, send, walk_to_name


async def test_every_step_after_the_first_offers_a_back_button(
    dispatcher: Dispatcher, bot: Bot, session: RecordingSession
) -> None:
    # Arrange / Act
    await walk_to_name(dispatcher, bot)

    # Assert — the name step is mid-wizard, so Back must be on screen
    back = NavCB(action=NavAction.BACK).pack()
    assert back in {data for _, data in buttons(session.last_screen.reply_markup)}


async def test_back_from_the_name_step_returns_to_the_note_step(
    dispatcher: Dispatcher, bot: Bot, session: RecordingSession, state: FSMContext
) -> None:
    # Arrange
    await walk_to_name(dispatcher, bot)

    # Act
    await press(dispatcher, bot, NavCB(action=NavAction.BACK).pack())

    # Assert
    assert await state.get_state() == Wizard.note.state
    assert translate("wizard.note.prompt", Language.EN).split("{")[0][:20] in (
        session.last_screen.text
    )


async def test_back_preserves_answers_already_given(
    dispatcher: Dispatcher, bot: Bot, state: FSMContext
) -> None:
    # Arrange
    await walk_to_name(dispatcher, bot)

    # Act — walk all the way back to the occasion step
    for _ in range(3):
        await press(dispatcher, bot, NavCB(action=NavAction.BACK).pack())

    # Assert — the genre chosen earlier is still in the draft
    draft = (await state.get_data())[DRAFT_KEY]
    assert draft["genre"] == Genre.UZBEK_POP.value
    assert draft["occasion"] == Occasion.BIRTHDAY.value


async def test_back_on_the_first_step_re_renders_that_step(
    dispatcher: Dispatcher, bot: Bot, session: RecordingSession, state: FSMContext
) -> None:
    # Arrange
    await send(dispatcher, bot, "/start")

    # Act
    await press(dispatcher, bot, NavCB(action=NavAction.BACK).pack())

    # Assert
    assert await state.get_state() == Wizard.ui_language.state
    assert translate("start.choose_ui_language", Language.UZ_LATN) in session.last_screen.text


async def test_retype_clears_the_resolved_name_and_asks_again(
    dispatcher: Dispatcher, bot: Bot, session: RecordingSession, state: FSMContext
) -> None:
    # Arrange
    await walk_to_name(dispatcher, bot)
    await send(dispatcher, bot, UZBEK_TYPED)

    # Act
    await press(dispatcher, bot, NavCB(action=NavAction.RETYPE).pack())

    # Assert
    assert await state.get_state() == Wizard.name.state
    assert (await state.get_data())[DRAFT_KEY]["recipient"] is None
    assert UZBEK_DISPLAY not in session.last_screen.text


async def test_cancel_clears_the_session(
    dispatcher: Dispatcher, bot: Bot, session: RecordingSession, state: FSMContext
) -> None:
    # Arrange
    await walk_to_name(dispatcher, bot)

    # Act
    await press(dispatcher, bot, NavCB(action=NavAction.CANCEL).pack())

    # Assert
    assert await state.get_state() is None
    assert await state.get_data() == {}
    assert session.last_screen.text == translate("wizard.cancelled", Language.EN)


async def test_start_mid_wizard_starts_over(
    dispatcher: Dispatcher, bot: Bot, state: FSMContext
) -> None:
    # Arrange
    await walk_to_name(dispatcher, bot)

    # Act
    await send(dispatcher, bot, "/start")

    # Assert — a fresh draft, back at the first step, with no answers carried over
    assert await state.get_state() == Wizard.ui_language.state
    assert (await state.get_data())[DRAFT_KEY]["genre"] is None


async def test_previous_step_is_derived_from_the_declared_order() -> None:
    # Arrange
    pairs = tuple(pairwise(WIZARD_ORDER))

    # Act / Assert
    assert previous_step(WIZARD_ORDER[0]) is None
    for earlier, later in pairs:
        assert previous_step(later) is earlier
    assert previous_step(WizardStep.CONFIRM) is WizardStep.OUTPUT_LANGUAGE
