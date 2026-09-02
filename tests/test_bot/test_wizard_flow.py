"""The wizard, end to end, through a real Dispatcher.

Every step is driven the way a user drives it: an update goes in, and the next tap uses
callback data taken from the keyboard the bot actually drew. A routing bug, a state bug or
a keyboard that offers a button nobody handles all fail these tests.
"""

from __future__ import annotations

import pytest
from aiogram import Bot, Dispatcher
from aiogram.fsm.context import FSMContext

from hbd.bot.callbacks import (
    GenreCB,
    LanguageCB,
    LanguageSlot,
    NavAction,
    NavCB,
    OccasionCB,
    VocalGenderCB,
)
from hbd.bot.i18n import translate
from hbd.bot.states import Wizard
from hbd.contracts import (
    MAX_RECIPIENT_NAME_CHARS,
    Genre,
    Language,
    Occasion,
    OrderState,
    VoiceGender,
)
from tests.test_bot.conftest import (
    RecordingContentWriter,
    RecordingSession,
    RecordingSubmitter,
    buttons,
    callback_update,
    message_update,
)

UZBEK_TYPED = "G‘ulomjon"  # U+2018, what a phone keyboard actually sends
UZBEK_DISPLAY = "Gʻulomjon"  # U+02BB, what the user must be shown


async def press(dispatcher: Dispatcher, bot: Bot, data: str) -> None:
    await dispatcher.feed_update(bot, callback_update(data))


async def send(dispatcher: Dispatcher, bot: Bot, text: str) -> None:
    await dispatcher.feed_update(bot, message_update(text))


async def walk_to_name(dispatcher: Dispatcher, bot: Bot) -> None:
    """/start through to the name prompt, in English."""
    await send(dispatcher, bot, "/start")
    await press(dispatcher, bot, LanguageCB(slot=LanguageSlot.UI, code=Language.EN).pack())
    await press(dispatcher, bot, OccasionCB(value=Occasion.BIRTHDAY).pack())
    await press(dispatcher, bot, GenreCB(value=Genre.UZBEK_POP).pack())
    await press(dispatcher, bot, VocalGenderCB(value=VoiceGender.FEMALE).pack())
    await send(dispatcher, bot, "Loves plov and the mountains")


async def approve_lyrics(dispatcher: Dispatcher, bot: Bot) -> None:
    """Press ✅ on the lyric preview.

    Choosing the output language no longer lands on the summary: it writes a lyric and
    shows it. Every walk to CONFIRM therefore goes through this one press, and it lives
    here rather than being open-coded per test so a further change to the preview is one
    edit and not a dozen.
    """
    await press(dispatcher, bot, NavCB(action=NavAction.LYRICS_OK).pack())


async def walk_to_lyrics(dispatcher: Dispatcher, bot: Bot) -> None:
    """/start through to the lyric preview, with a lyric already on screen."""
    await walk_to_name(dispatcher, bot)
    await send(dispatcher, bot, UZBEK_TYPED)
    await press(dispatcher, bot, NavCB(action=NavAction.NAME_OK).pack())
    await press(dispatcher, bot, LanguageCB(slot=LanguageSlot.OUTPUT, code=Language.UZ_LATN).pack())


async def walk_to_confirm(dispatcher: Dispatcher, bot: Bot) -> None:
    await walk_to_lyrics(dispatcher, bot)
    await approve_lyrics(dispatcher, bot)


async def test_start_offers_every_supported_interface_language(
    dispatcher: Dispatcher, bot: Bot, session: RecordingSession
) -> None:
    # Arrange / Act
    await send(dispatcher, bot, "/start")

    # Assert
    screen = session.last_screen
    offered = {data for _, data in buttons(screen.reply_markup) if data.startswith("lang:ui")}
    assert len(offered) == len(Language)
    assert translate("start.choose_ui_language", Language.UZ_LATN) in screen.text


async def test_wizard_reaches_the_name_step_in_the_chosen_interface_language(
    dispatcher: Dispatcher, bot: Bot, session: RecordingSession, state: FSMContext
) -> None:
    # Arrange / Act
    await walk_to_name(dispatcher, bot)

    # Assert
    assert session.last_screen.text == translate(
        "wizard.name.prompt", Language.EN, limit=MAX_RECIPIENT_NAME_CHARS
    )
    assert await state.get_state() == Wizard.name.state


async def test_typed_name_is_echoed_in_its_canonical_display_form(
    dispatcher: Dispatcher, bot: Bot, session: RecordingSession
) -> None:
    # Arrange
    await walk_to_name(dispatcher, bot)

    # Act — the user types the phone-keyboard apostrophe
    await send(dispatcher, bot, UZBEK_TYPED)

    # Assert — the confirmation shows U+02BB, never the typed variant
    text = session.last_screen.text
    assert UZBEK_DISPLAY in text
    assert UZBEK_TYPED not in text


async def test_confirming_the_name_moves_on_to_the_output_language(
    dispatcher: Dispatcher, bot: Bot, session: RecordingSession, state: FSMContext
) -> None:
    # Arrange
    await walk_to_name(dispatcher, bot)
    await send(dispatcher, bot, UZBEK_TYPED)

    # Act
    await press(dispatcher, bot, NavCB(action=NavAction.NAME_OK).pack())

    # Assert
    assert await state.get_state() == Wizard.output_language.state
    assert session.last_screen.text == translate(
        "wizard.output_language.prompt", Language.EN, name=UZBEK_DISPLAY
    )


async def test_repicking_the_same_song_language_keeps_the_lyric_already_approved(
    dispatcher: Dispatcher,
    bot: Bot,
    session: RecordingSession,
    content: RecordingContentWriter,
    state: FSMContext,
) -> None:
    """NAV-05. Back from the summary lands on the language picker, and the obvious way
    onwards is the button that is already ticked. Treating that as a fresh answer would
    call the writer again and silently destroy a lyric the customer had approved — or, far
    worse, one they had pasted in themselves and cannot get back.
    """
    # Arrange — a lyric is written, approved, and the user steps Back to the picker
    await walk_to_lyrics(dispatcher, bot)
    assert content.calls == 1
    approved = session.last_screen.text
    await press(dispatcher, bot, NavCB(action=NavAction.LYRICS_OK).pack())
    await press(dispatcher, bot, NavCB(action=NavAction.BACK).pack())
    await press(dispatcher, bot, NavCB(action=NavAction.BACK).pack())
    assert await state.get_state() == Wizard.output_language.state
    session.clear()

    # Act — re-tap the language that is already chosen
    await press(dispatcher, bot, LanguageCB(slot=LanguageSlot.OUTPUT, code=Language.UZ_LATN).pack())

    # Assert — the same words, and the writer was never asked again
    assert content.calls == 1
    assert await state.get_state() == Wizard.lyrics.state
    assert session.last_screen.text == approved


async def test_choosing_a_different_song_language_does_rewrite_the_lyric(
    dispatcher: Dispatcher, bot: Bot, content: RecordingContentWriter, state: FSMContext
) -> None:
    """The short circuit is about an UNCHANGED answer. A lyric in the wrong language is
    not the lyric they asked for, so changing the language must still write a new one."""
    # Arrange
    await walk_to_lyrics(dispatcher, bot)
    await press(dispatcher, bot, NavCB(action=NavAction.BACK).pack())
    assert await state.get_state() == Wizard.output_language.state

    # Act
    await press(dispatcher, bot, LanguageCB(slot=LanguageSlot.OUTPUT, code=Language.RU).pack())

    # Assert
    assert content.calls == 2
    assert content.briefs[-1].output_language is Language.RU
    assert await state.get_state() == Wizard.lyrics.state


async def test_summary_shows_the_display_name_and_every_answer(
    dispatcher: Dispatcher, bot: Bot, session: RecordingSession
) -> None:
    # Arrange / Act
    await walk_to_confirm(dispatcher, bot)

    # Assert
    text = session.last_screen.text
    assert UZBEK_DISPLAY in text
    assert translate("genre.uzbek_pop", Language.EN) in text
    assert translate("occasion.birthday", Language.EN) in text
    assert "Loves plov and the mountains" in text


async def test_confirming_submits_the_order_and_parks_the_session(
    dispatcher: Dispatcher,
    bot: Bot,
    session: RecordingSession,
    submitter: RecordingSubmitter,
    state: FSMContext,
) -> None:
    """Every answer reaches the queue, and the session stays parked while it runs.

    The FSM is deliberately NOT cleared here. Generation takes minutes, and a cleared
    session makes anything the customer types in the meantime look like no session at all —
    which the fallback would answer with "that expired, send /start", mid-run.
    """
    # Arrange
    await walk_to_confirm(dispatcher, bot)

    # Act
    await press(dispatcher, bot, NavCB(action=NavAction.CONFIRM).pack())

    # Assert
    assert len(submitter.submitted) == 1
    order, chat_id, progress_message_id = submitter.submitted[0]
    assert order.state is OrderState.AUTHORIZED
    assert order.brief.recipient.display == UZBEK_DISPLAY
    assert order.brief.output_language is Language.UZ_LATN
    assert order.brief.ui_language is Language.EN
    assert chat_id and progress_message_id
    assert await state.get_state() == Wizard.submitting.state


async def test_submitted_candidates_are_ranked_and_never_shown_to_the_user(
    dispatcher: Dispatcher, bot: Bot, submitter: RecordingSubmitter, session: RecordingSession
) -> None:
    # Arrange
    await walk_to_confirm(dispatcher, bot)

    # Act
    await press(dispatcher, bot, NavCB(action=NavAction.CONFIRM).pack())

    # Assert
    order, _, _ = submitter.submitted[0]
    candidates = order.brief.recipient.candidates
    assert tuple(candidate.rank for candidate in candidates) == tuple(range(len(candidates)))
    screen_text = " ".join(call.text or "" for call in session.calls if hasattr(call, "text"))
    submitted_only = [c.text for c in candidates if c.text != UZBEK_DISPLAY]
    assert submitted_only, "the fixture name must produce at least one distinct submit form"
    for spelling in submitted_only:
        assert spelling not in screen_text


@pytest.mark.parametrize(
    ("typed", "expected_key"),
    [("12345", "wizard.name.invalid"), ("x" * 60, "wizard.name.too_long")],
)
async def test_unusable_name_keeps_the_user_on_the_name_step(
    dispatcher: Dispatcher,
    bot: Bot,
    session: RecordingSession,
    state: FSMContext,
    typed: str,
    expected_key: str,
) -> None:
    # Arrange
    await walk_to_name(dispatcher, bot)
    session.clear()

    # Act
    await send(dispatcher, bot, typed)

    # Assert
    assert await state.get_state() == Wizard.name.state
    assert translate(expected_key, Language.EN).split("{")[0] in session.last_screen.text


async def test_voice_message_at_the_name_step_asks_for_typed_text(
    dispatcher: Dispatcher, bot: Bot, session: RecordingSession, state: FSMContext
) -> None:
    # Arrange
    from aiogram.types import Update

    from tests.test_bot.conftest import make_non_text_message

    await walk_to_name(dispatcher, bot)
    session.clear()

    # Act
    await dispatcher.feed_update(bot, Update(update_id=9_001, message=make_non_text_message()))

    # Assert
    assert session.last_screen.text == translate("wizard.name.type_only", Language.EN)
    assert await state.get_state() == Wizard.name.state


async def test_note_longer_than_the_limit_is_rejected_without_losing_the_step(
    dispatcher: Dispatcher, bot: Bot, session: RecordingSession, state: FSMContext
) -> None:
    # Arrange
    await send(dispatcher, bot, "/start")
    await press(dispatcher, bot, LanguageCB(slot=LanguageSlot.UI, code=Language.EN).pack())
    await press(dispatcher, bot, OccasionCB(value=Occasion.BIRTHDAY).pack())
    await press(dispatcher, bot, GenreCB(value=Genre.POP).pack())
    await press(dispatcher, bot, VocalGenderCB(value=VoiceGender.MALE).pack())

    # Act
    await send(dispatcher, bot, "x" * 601)

    # Assert
    assert await state.get_state() == Wizard.note.state
    assert "601" not in session.last_screen.text
    assert "600" in session.last_screen.text


async def test_the_skip_button_keeps_a_note_that_was_already_written(
    dispatcher: Dispatcher, bot: Bot, submitter: RecordingSubmitter
) -> None:
    """One callback, two labels — and pressing it must do what the label says.

    ``note_keyboard`` relabels Skip to "Keep this note" once a note exists, so Back into
    the note step has an obvious way onwards that is not retyping it. The handler wrote
    ``note=""`` regardless, which made the second label a lie: the customer pressed Keep
    and the note they had written was deleted on the way to the name step.
    """
    # Arrange — write a note, then come back to the step it was written on
    await walk_to_name(dispatcher, bot)
    await press(dispatcher, bot, NavCB(action=NavAction.BACK).pack())

    # Act — press the button that now reads "Keep this note"
    await press(dispatcher, bot, NavCB(action=NavAction.SKIP).pack())
    await send(dispatcher, bot, UZBEK_TYPED)
    await press(dispatcher, bot, NavCB(action=NavAction.NAME_OK).pack())
    await press(dispatcher, bot, LanguageCB(slot=LanguageSlot.OUTPUT, code=Language.EN).pack())
    await approve_lyrics(dispatcher, bot)
    await press(dispatcher, bot, NavCB(action=NavAction.CONFIRM).pack())

    # Assert
    order, _, _ = submitter.submitted[0]
    assert order.brief.note == "Loves plov and the mountains"


async def test_a_command_at_the_note_step_is_never_stored_as_the_note(
    dispatcher: Dispatcher, bot: Bot, state: FSMContext, session: RecordingSession
) -> None:
    # Arrange — at the note step, one answer short of the name
    await send(dispatcher, bot, "/start")
    await press(dispatcher, bot, LanguageCB(slot=LanguageSlot.UI, code=Language.EN).pack())
    await press(dispatcher, bot, OccasionCB(value=Occasion.BIRTHDAY).pack())
    await press(dispatcher, bot, GenreCB(value=Genre.POP).pack())
    await press(dispatcher, bot, VocalGenderCB(value=VoiceGender.MALE).pack())

    # Act — a command nothing else claims, so it reaches the free-text handler
    await send(dispatcher, bot, "/halp me write this")

    # Assert — the step is re-shown and nothing was written
    assert await state.get_state() == Wizard.note.state
    assert "/halp" not in session.last_screen.text


async def test_a_command_at_the_lyrics_step_is_never_accepted_as_the_lyric(
    dispatcher: Dispatcher, bot: Bot, state: FSMContext, submitter: RecordingSubmitter
) -> None:
    """The same hole the note step had. ``parse_typed_lyrics`` has no view on a slash.

    Only the twenty-character minimum rejected any of these, and only by accident — this
    command is longer than that, so before the guard it was accepted verbatim, previewed
    as the lyric and queued to be sung.
    """
    # Arrange
    await walk_to_lyrics(dispatcher, bot)
    command = "/halp me write this song about her please"

    # Act
    await send(dispatcher, bot, command)

    # Assert — still on the preview, and the queued lyric is the writer's, not the command
    assert await state.get_state() == Wizard.lyrics.state
    await approve_lyrics(dispatcher, bot)
    await press(dispatcher, bot, NavCB(action=NavAction.CONFIRM).pack())
    order, _, _ = submitter.submitted[0]
    approved = order.brief.approved_lyrics
    assert approved is not None
    assert command not in "\n".join(line for s in approved.sections for line in s.lines)


async def test_skip_leaves_the_note_empty(
    dispatcher: Dispatcher, bot: Bot, submitter: RecordingSubmitter
) -> None:
    # Arrange
    await send(dispatcher, bot, "/start")
    await press(dispatcher, bot, LanguageCB(slot=LanguageSlot.UI, code=Language.EN).pack())
    await press(dispatcher, bot, OccasionCB(value=Occasion.CUSTOM).pack())
    await press(dispatcher, bot, GenreCB(value=Genre.ROCK).pack())
    await press(dispatcher, bot, VocalGenderCB(value=VoiceGender.DUET).pack())

    # Act
    await press(dispatcher, bot, NavCB(action=NavAction.SKIP).pack())
    await send(dispatcher, bot, UZBEK_TYPED)
    await press(dispatcher, bot, NavCB(action=NavAction.NAME_OK).pack())
    await press(dispatcher, bot, LanguageCB(slot=LanguageSlot.OUTPUT, code=Language.RU).pack())
    await approve_lyrics(dispatcher, bot)
    await press(dispatcher, bot, NavCB(action=NavAction.CONFIRM).pack())

    # Assert
    order, _, _ = submitter.submitted[0]
    assert order.brief.note == ""
