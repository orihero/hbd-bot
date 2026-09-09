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
from hbd.bot.draft import DRAFT_KEY, ONBOARDED_KEY, UI_LANGUAGE_KEY
from hbd.bot.handlers.submitting import ORDER_ID_KEY
from hbd.bot.i18n import translate
from hbd.bot.keyboards import MENU_BUTTON_KEYS
from hbd.bot.states import (
    PARKED_ONLY_STEPS,
    WIZARD_ORDER,
    Wizard,
    WizardStep,
    previous_step,
    state_for,
    step_for_state,
)
from hbd.contracts import Genre, Language, Occasion
from tests.test_bot.conftest import (
    RecordingSession,
    RecordingSubmitter,
    buttons,
    last_reply_keyboard,
    reply_buttons,
)
from tests.test_bot.test_wizard_flow import (
    UZBEK_DISPLAY,
    UZBEK_TYPED,
    complete_onboarding,
    press,
    send,
    tap,
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


async def test_the_first_wizard_step_draws_no_back_button_and_a_stale_back_re_renders_it(
    dispatcher: Dispatcher, bot: Bot, session: RecordingSession, state: FSMContext
) -> None:
    """Back on the head of the order is not drawn, and pressing an old one is harmless.

    Back used to lead from the first step to the language picker, because the picker WAS the
    first step. The picker has moved in front of the wizard entirely, so ``previous_step``
    answers ``None`` for ``WIZARD_ORDER[0]`` and there is nothing to go back to: the button
    is therefore not drawn at all (``occasion_keyboard(is_back_enabled=False)``).

    Both halves are asserted because Telegram leaves every screen the bot ever drew in the
    message roll. A customer who scrolls up and taps a Back from a previous run must be
    re-shown the question they are on — not answered "your session expired", which is what a
    fall-through to ``expire`` would say to somebody whose session is perfectly alive.
    """
    # Arrange — an onboarded customer, one tap into a fresh wizard
    await complete_onboarding(dispatcher, bot, language=Language.EN)
    await tap(dispatcher, bot, "menu.generate", Language.EN)
    assert await state.get_state() == Wizard.occasion.state
    back = NavCB(action=NavAction.BACK).pack()
    assert back not in {data for _, data in buttons(session.last_screen.reply_markup)}

    # Act — a Back from an older screen, pressed anyway
    await press(dispatcher, bot, back)

    # Assert — the same step, re-rendered, and no talk of an expiry
    assert await state.get_state() == Wizard.occasion.state
    assert translate("wizard.occasion.prompt", Language.EN) in session.last_screen.text


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


async def test_cancel_clears_the_session_and_keeps_only_who_the_customer_is(
    dispatcher: Dispatcher, bot: Bot, session: RecordingSession, state: FSMContext
) -> None:
    """Cancel empties the session down to exactly two keys, and both are load-bearing (C2-8).

    A bare ``state.clear()`` here would take ``UI_LANGUAGE_KEY`` and ``ONBOARDED_KEY`` with
    the draft, and the very next update would find no cached identity: the onboarding
    catch-all would pay for a store read, and — worse — a customer whose store read failed or
    whose deployment has no store would be answered in the fallback language and asked for
    their number again, one tap after cancelling a song. Cancelling a wizard run is not a
    request to be forgotten; ``/forget`` is, and it is the one place that still clears bare.

    The assertion is exact rather than a pair of ``in`` checks, because the failure this
    guards is a THIRD key surviving — a draft, an order id or a progress-message id left
    behind by a future edit is a half-cancelled session that the next screen would read as
    a live one.
    """
    # Arrange
    await walk_to_name(dispatcher, bot)

    # Act
    await press(dispatcher, bot, NavCB(action=NavAction.CANCEL).pack())

    # Assert
    assert await state.get_state() is None
    assert await state.get_data() == {
        UI_LANGUAGE_KEY: Language.EN.value,
        ONBOARDED_KEY: True,
    }
    assert session.last_screen.text == translate("wizard.cancelled", Language.EN)


async def test_start_mid_wizard_returns_an_onboarded_customer_to_the_menu(
    dispatcher: Dispatcher, bot: Bot, session: RecordingSession, state: FSMContext
) -> None:
    """``/start`` from somebody the bot already knows is the MENU, not a wizard.

    It used to re-open the wizard at the language picker, which asked a settled question:
    a customer who has already told us which language to speak and left us their number must
    never be made to answer anything again to reach the thing they came for. Landing on the
    menu also leaves the half-finished draft's state cleared rather than replaced by a second
    one, so ``/start`` stays the reliable way out of any screen.

    The welcome paragraph is asserted ABSENT (C1-13). It runs to well over two hundred
    characters and is a greeting: drawn on every ``/start`` it becomes a wall of text a
    returning customer scrolls past to find four buttons, so ``menu_screen`` draws it only on
    the first menu after onboarding.
    """
    # Arrange
    await walk_to_name(dispatcher, bot)

    # Act
    await send(dispatcher, bot, "/start")

    # Assert — no wizard state, the menu on screen, and its four buttons pinned under it
    assert await state.get_state() is None
    assert translate("menu.prompt", Language.EN) in session.last_screen.text
    assert translate("start.welcome", Language.EN) not in session.last_screen.text
    labels = {label for row in reply_buttons(last_reply_keyboard(session)) for label in row}
    assert {translate(key, Language.EN) for key in MENU_BUTTON_KEYS} <= labels


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


async def test_start_over_opens_a_fresh_wizard_and_carries_nothing_over(
    dispatcher: Dispatcher, bot: Bot, session: RecordingSession, state: FSMContext
) -> None:
    """↩️ Start over is a NEW SONG, and it is no longer the same thing ``/start`` is.

    The two used to be one code path because the wizard began with the language question, so
    "clean slate" and "first screen" were the same screen. They have come apart: ``/start``
    from an onboarded customer is the menu, and this button — drawn on the screens that end a
    flow, beside a ``TO_MENU`` row that is the way home — is the one that opens the wizard.
    Both still funnel through ``common.reset_to_welcome``, which is what keeps "begin a song"
    one implementation rather than three that drift.

    The clean slate is asserted on the DRAFT rather than on the absence of one: a genre
    carried over from the abandoned run would be a silent answer the customer never gave, and
    they would only find out when the song came back in the wrong style.
    """
    # Arrange
    await walk_to_name(dispatcher, bot)

    # Act
    await press(dispatcher, bot, NavCB(action=NavAction.START_OVER).pack())

    # Assert — the head of the order again, with nothing carried over
    assert await state.get_state() == state_for(WIZARD_ORDER[0]).state
    assert (await state.get_data())[DRAFT_KEY]["genre"] is None
    assert translate("wizard.occasion.prompt", Language.EN) in session.last_screen.text


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
    # Arrange / Act
    # Assert — a step may leave the order only by being NAMED in ``states.PARKED_ONLY_STEPS``,
    # which is why that constant is exported rather than subtracted here: the exception lives
    # in the source, where the next author will meet it, and this assertion reads it. It still
    # fails when a step is forgotten from the order by accident, which is its whole job.
    # ``UI_LANGUAGE`` keeps its state, its ``_STATE_BY_STEP`` entry and its ``render_step``
    # case so ``render_step`` stays TOTAL and ``step_for_state`` resolves a state name Redis
    # hands back for fourteen days — not because anyone can walk to it.
    assert set(WIZARD_ORDER) | PARKED_ONLY_STEPS == set(WizardStep)
    # The loop deliberately covers ALL members, ``UI_LANGUAGE`` included: that is what proves
    # the state table was not half-deleted along with the step's place in the order.
    for step in WizardStep:
        assert state_for(step) is not None
        assert step_for_state(state_for(step).state) is step
