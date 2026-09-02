"""Back, Retype and Cancel — the buttons that make the wizard safe to explore.

None of the three is state-filtered, because Telegram leaves every screen the wizard ever
drew on the user's message roll and a button that only worked on the newest one would be a
button that mostly does nothing. The price of that is the guard tested at the bottom of
this file: once a song is actually being made, Cancel used to answer "Cancelled" and clear
the draft while the order it claimed to have stopped ran to completion and was delivered.
"""

from __future__ import annotations

from itertools import pairwise

from aiogram import Bot, Dispatcher
from aiogram.fsm.context import FSMContext

from hbd.bot.callbacks import (
    NavAction,
    NavCB,
)
from hbd.bot.draft import DRAFT_KEY
from hbd.bot.handlers.submitting import ORDER_ID_KEY
from hbd.bot.i18n import translate
from hbd.bot.states import (
    WIZARD_ORDER,
    Wizard,
    WizardStep,
    previous_step,
    state_for,
    step_for_state,
)
from hbd.contracts import Genre, Language, Occasion
from tests.test_bot.conftest import RecordingSession, RecordingSubmitter, buttons
from tests.test_bot.test_wizard_flow import (
    UZBEK_DISPLAY,
    UZBEK_TYPED,
    press,
    send,
    walk_to_confirm,
    walk_to_name,
)


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


async def test_the_cancelled_screen_offers_a_way_back_in(
    dispatcher: Dispatcher, bot: Bot, session: RecordingSession
) -> None:
    # Arrange
    await walk_to_name(dispatcher, bot)

    # Act
    await press(dispatcher, bot, NavCB(action=NavAction.CANCEL).pack())

    # Assert
    offered = {data for _, data in buttons(session.last_screen.reply_markup)}
    assert NavCB(action=NavAction.START_OVER).pack() in offered


async def test_start_over_is_the_same_clean_slate_start_is(
    dispatcher: Dispatcher, bot: Bot, session: RecordingSession, state: FSMContext
) -> None:
    # Arrange
    await walk_to_name(dispatcher, bot)

    # Act
    await press(dispatcher, bot, NavCB(action=NavAction.START_OVER).pack())

    # Assert — the first screen again, with nothing carried over
    assert await state.get_state() == Wizard.ui_language.state
    assert (await state.get_data())[DRAFT_KEY]["genre"] is None
    assert translate("start.choose_ui_language", Language.UZ_LATN) in session.last_screen.text


async def test_cancel_while_the_song_is_being_made_refuses_instead_of_lying(
    dispatcher: Dispatcher,
    bot: Bot,
    session: RecordingSession,
    state: FSMContext,
    submitter: RecordingSubmitter,
) -> None:
    """The order is running and cannot be stopped. Saying "Cancelled" would be a lie."""
    # Arrange — a Cancel button from an older screen, pressed after Confirm
    await walk_to_confirm(dispatcher, bot)
    await press(dispatcher, bot, NavCB(action=NavAction.CONFIRM).pack())
    assert len(submitter.submitted) == 1
    session.clear()

    # Act
    await press(dispatcher, bot, NavCB(action=NavAction.CANCEL).pack())

    # Assert — told the truth, and the session is still parked on its order
    assert session.last_screen.text == translate(
        "wizard.cancel_too_late", Language.EN, name=UZBEK_DISPLAY
    )
    assert await state.get_state() == Wizard.submitting.state
    assert (await state.get_data())[ORDER_ID_KEY]


async def test_back_while_the_song_is_being_made_does_not_throw_the_session_away(
    dispatcher: Dispatcher, bot: Bot, session: RecordingSession, state: FSMContext
) -> None:
    """Back is drawn on every screen too, and clears just as much as Cancel does."""
    # Arrange
    await walk_to_confirm(dispatcher, bot)
    await press(dispatcher, bot, NavCB(action=NavAction.CONFIRM).pack())
    session.clear()

    # Act
    await press(dispatcher, bot, NavCB(action=NavAction.BACK).pack())

    # Assert
    assert await state.get_state() == Wizard.submitting.state
    assert session.last_screen.text == translate(
        "wizard.cancel_too_late", Language.EN, name=UZBEK_DISPLAY
    )


async def test_cancel_during_a_lyric_write_still_cancels(
    dispatcher: Dispatcher, bot: Bot, session: RecordingSession, state: FSMContext
) -> None:
    """``Wizard.submitting`` is shared with the lyric write, and nothing is ordered there.

    The guard keys on the order id in FSM data rather than on the state name precisely so
    that Cancel keeps meaning what it says everywhere no money and no vendor time is
    committed.
    """
    # Arrange — parked in the write state with no order behind it
    await walk_to_confirm(dispatcher, bot)
    await state.set_state(Wizard.submitting)

    # Act
    await press(dispatcher, bot, NavCB(action=NavAction.CANCEL).pack())

    # Assert
    assert await state.get_state() is None
    assert session.last_screen.text == translate("wizard.cancelled", Language.EN)


async def test_the_cancel_command_while_the_song_is_being_made_refuses_too(
    dispatcher: Dispatcher,
    bot: Bot,
    session: RecordingSession,
    state: FSMContext,
    submitter: RecordingSubmitter,
) -> None:
    """``/cancel`` had the guard the Cancel BUTTON has, and nothing else.

    The two are the same promise made through two surfaces. ``handlers.start`` is
    registered ahead of ``handlers.navigation`` so the command never reaches the button's
    guard, which is why the check has to be repeated there rather than inherited.
    """
    # Arrange
    await walk_to_confirm(dispatcher, bot)
    await press(dispatcher, bot, NavCB(action=NavAction.CONFIRM).pack())
    assert len(submitter.submitted) == 1
    session.clear()

    # Act
    await send(dispatcher, bot, "/cancel")

    # Assert — the same sentence the button gives, and the session still on its order
    assert session.last_screen.text == translate(
        "wizard.cancel_too_late", Language.EN, name=UZBEK_DISPLAY
    )
    assert await state.get_state() == Wizard.submitting.state
    assert (await state.get_data())[ORDER_ID_KEY]


async def test_the_cancel_command_during_a_lyric_write_still_cancels(
    dispatcher: Dispatcher, bot: Bot, session: RecordingSession, state: FSMContext
) -> None:
    # Arrange — parked in the write state with no order behind it
    await walk_to_confirm(dispatcher, bot)
    await state.set_state(Wizard.submitting)

    # Act
    await send(dispatcher, bot, "/cancel")

    # Assert
    assert await state.get_state() is None
    assert session.last_screen.text == translate("wizard.cancelled", Language.EN)


async def test_previous_step_is_derived_from_the_declared_order() -> None:
    # Arrange
    pairs = tuple(pairwise(WIZARD_ORDER))

    # Act / Assert
    assert previous_step(WIZARD_ORDER[0]) is None
    for earlier, later in pairs:
        assert previous_step(later) is earlier
    assert previous_step(WizardStep.LYRICS) is WizardStep.OUTPUT_LANGUAGE
    assert previous_step(WizardStep.CONFIRM) is WizardStep.LYRICS


def test_every_step_has_a_state_and_a_place_in_the_order() -> None:
    """The two hand-written tables in ``states.py`` are the easiest thing to half-update.

    Neither is exhaustiveness-checked by mypy: a step missing from ``_STATE_BY_STEP`` is a
    ``KeyError`` inside ``show_step`` for the first customer who reaches it, and one missing
    from ``WIZARD_ORDER`` is a ``ValueError`` out of ``previous_step``.
    """
    # Arrange / Act / Assert
    assert set(WIZARD_ORDER) == set(WizardStep)
    for step in WizardStep:
        assert state_for(step) is not None
        assert step_for_state(state_for(step).state) is step
