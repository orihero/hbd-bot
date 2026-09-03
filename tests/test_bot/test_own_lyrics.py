"""The bring-your-own-lyrics path, driven the way a customer drives it.

The product's premise is that the customer reads the words before anything is recorded.
This path goes further: they *write* them, and the bot writes nothing. Somebody arrives with
a poem an aunt wrote, or a verse from a family song, and the wizard's job is to take it —
not to sell them a machine's attempt first, and not to interview them about a recipient
whose name they have already put wherever they wanted it.

So this is a second wizard behind one bot, and the tests below are mostly about the ways two
paths through one set of handlers can go wrong:

* the ORDER. It asks for the words SECOND, then only the questions that still mean
  something — genre, voice, language. No note (it existed to feed the writer) and no name
  (there is no name subsystem on this path at all).
* the COST. Nothing here calls a vendor. The assertions that count writer calls and expect
  zero are the ones worth keeping if the rest were ever cut.
* the NAMELESSNESS. ``Brief.recipient`` is ``None`` all the way to the queue, which is a
  state most of this codebase had never seen before.
* the BOUNDARY. ``lyrics_source`` decides which order a draft walks, so anything that could
  move it mid-wizard would strand a customer on a step their path does not contain.

Everything is driven through a real ``Dispatcher``, pressing the callback data the real
keyboards drew, and asserts on the draft that comes back out of FSM storage.
"""

from __future__ import annotations

import pytest
from aiogram import Bot, Dispatcher
from aiogram.fsm.context import FSMContext
from aiogram.types import Update

from hbd.bot.callbacks import (
    GenreCB,
    LanguageCB,
    LanguageSlot,
    NavAction,
    NavCB,
    OccasionCB,
    VocalGenderCB,
)
from hbd.bot.draft import LyricSource
from hbd.bot.i18n import translate
from hbd.bot.keyboards import OWN_LYRICS_LABEL_KEY, occasion_keyboard
from hbd.bot.lyrics_entry import MAX_LYRIC_CHARS, MIN_LYRIC_CHARS
from hbd.bot.states import OWN_LYRICS_ORDER, WIZARD_ORDER, Wizard, WizardStep
from hbd.contracts import Genre, Language, Occasion, VoiceGender
from tests.test_bot.conftest import (
    RecordingContentWriter,
    RecordingSession,
    RecordingSubmitter,
    buttons,
    make_non_text_message,
)
from tests.test_bot.test_lyrics_step import PASTED, current_draft, screen_texts
from tests.test_bot.test_wizard_flow import press, send, walk_to_lyrics

OWN_LYRICS = NavCB(action=NavAction.OWN_LYRICS).pack()
BACK = NavCB(action=NavAction.BACK).pack()
APPROVE = NavCB(action=NavAction.LYRICS_OK).pack()


async def start_own_lyrics(dispatcher: Dispatcher, bot: Bot) -> None:
    """/start, English, then the pen. Lands on the screen that asks for the words."""
    await send(dispatcher, bot, "/start")
    await press(dispatcher, bot, LanguageCB(slot=LanguageSlot.UI, code=Language.EN).pack())
    await press(dispatcher, bot, OWN_LYRICS)


async def walk_to_own_confirm(dispatcher: Dispatcher, bot: Bot) -> None:
    """The whole path, end to end: five screens after /start and no vendor call."""
    await start_own_lyrics(dispatcher, bot)
    await send(dispatcher, bot, PASTED)
    await press(dispatcher, bot, APPROVE)
    await press(dispatcher, bot, GenreCB(value=Genre.UZBEK_POP).pack())
    await press(dispatcher, bot, VocalGenderCB(value=VoiceGender.FEMALE).pack())
    await press(dispatcher, bot, LanguageCB(slot=LanguageSlot.OUTPUT, code=Language.UZ_LATN).pack())


# ---------------------------------------------------------------------------
# the entry point: a button in the occasion list
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("language", list(Language))
def test_the_occasion_list_offers_the_customer_the_pen(language: Language) -> None:
    """In every locale, and labelled — a raw key here would ship as the button's text."""
    # Arrange / Act
    labels = {data: text for text, data in buttons(occasion_keyboard(language))}

    # Assert
    assert labels[OWN_LYRICS] == translate(OWN_LYRICS_LABEL_KEY, language)


def test_the_pen_sits_directly_above_the_catch_all_occasion() -> None:
    """Placement is the request, and it is not decoration.

    ``CUSTOM`` is the list's escape hatch ("something else"), and anything drawn beneath an
    escape hatch reads as a kind of it.
    """
    # Arrange / Act
    offered = [data for _, data in buttons(occasion_keyboard(Language.EN))]

    # Assert
    assert offered.index(OWN_LYRICS) == offered.index(OccasionCB(value=Occasion.CUSTOM).pack()) - 1


def test_every_occasion_is_still_offered_beside_it() -> None:
    """The button is an addition to the list, never a replacement for part of it."""
    # Arrange / Act
    offered = {data for _, data in buttons(occasion_keyboard(Language.EN))}

    # Assert
    assert {OccasionCB(value=value).pack() for value in Occasion} <= offered


# ---------------------------------------------------------------------------
# the order: the words come SECOND
# ---------------------------------------------------------------------------
async def test_the_very_next_screen_asks_for_the_words(
    dispatcher: Dispatcher, bot: Bot, session: RecordingSession, state: FSMContext
) -> None:
    """The whole point of the request. Nothing is asked before the lyric.

    It names nobody and states both bounds: the two rejections are the only other place a
    customer would learn them, and being told a limit after breaking it is a worse way to
    find out.
    """
    # Arrange / Act
    await start_own_lyrics(dispatcher, bot)

    # Assert
    assert await state.get_state() == Wizard.lyrics.state
    assert session.last_screen.text == translate(
        "wizard.lyrics.own_prompt", Language.EN, minimum=MIN_LYRIC_CHARS, limit=MAX_LYRIC_CHARS
    )


async def test_choosing_it_records_the_source_and_answers_the_question_on_screen(
    dispatcher: Dispatcher, bot: Bot, state: FSMContext
) -> None:
    """``Brief.occasion`` is not optional, so the occasion still has to be settled.

    ``CUSTOM`` is the honest value and, more to the point, an existing one: nothing
    downstream meets a value it has never been given.
    """
    # Arrange / Act
    await start_own_lyrics(dispatcher, bot)

    # Assert
    draft = await current_draft(state)
    assert draft.lyrics_source is LyricSource.OWN
    assert draft.occasion is Occasion.CUSTOM


async def test_the_note_and_the_name_are_never_asked(
    dispatcher: Dispatcher, bot: Bot, state: FSMContext
) -> None:
    """The two questions this path drops, asserted as an absence of state, not of copy.

    The note fed the writer and the name fed a subsystem that does not run here, so being
    asked either would be the bot making a promise it cannot keep.
    """
    # Arrange / Act
    await walk_to_own_confirm(dispatcher, bot)

    # Assert
    draft = await current_draft(state)
    assert draft.note == ""
    assert draft.recipient is None
    assert WizardStep.NOTE not in OWN_LYRICS_ORDER
    assert WizardStep.NAME not in OWN_LYRICS_ORDER
    assert WizardStep.NAME_CONFIRM not in OWN_LYRICS_ORDER


def test_the_short_order_is_a_subsequence_of_the_long_one() -> None:
    """One set of handlers serves both, which only holds while every step is shared.

    A step invented for the own-lyrics path alone would have no screen on the other, and
    ``render_step`` is total over the enum rather than over either order.
    """
    # Arrange / Act
    positions = [WIZARD_ORDER.index(step) for step in OWN_LYRICS_ORDER]

    # Assert — present in the long order, though deliberately NOT in the same relative order
    assert set(OWN_LYRICS_ORDER) <= set(WIZARD_ORDER)
    assert positions != sorted(positions), "LYRICS is meant to have moved earlier"


async def test_approving_the_words_goes_on_to_the_genre_not_the_summary(
    dispatcher: Dispatcher, bot: Bot, state: FSMContext
) -> None:
    """On this order the lyric is the second answer, so approving it is not the last act."""
    # Arrange
    await start_own_lyrics(dispatcher, bot)
    await send(dispatcher, bot, PASTED)

    # Act
    await press(dispatcher, bot, APPROVE)

    # Assert
    assert await state.get_state() == Wizard.genre.state


async def test_the_voice_question_leads_to_the_language_and_skips_the_note(
    dispatcher: Dispatcher, bot: Bot, state: FSMContext
) -> None:
    """The one step where the two orders visibly fork."""
    # Arrange
    await start_own_lyrics(dispatcher, bot)
    await send(dispatcher, bot, PASTED)
    await press(dispatcher, bot, APPROVE)
    await press(dispatcher, bot, GenreCB(value=Genre.ROCK).pack())

    # Act
    await press(dispatcher, bot, VocalGenderCB(value=VoiceGender.MALE).pack())

    # Assert
    assert await state.get_state() == Wizard.output_language.state


async def test_the_language_answer_lands_on_the_summary(
    dispatcher: Dispatcher, bot: Bot, state: FSMContext
) -> None:
    """It is the last question on this path, so the next screen is the commit screen."""
    # Arrange / Act
    await walk_to_own_confirm(dispatcher, bot)

    # Assert
    assert await state.get_state() == Wizard.confirm.state
    assert (await current_draft(state)).is_complete


# ---------------------------------------------------------------------------
# the point of the whole path: it spends nothing
# ---------------------------------------------------------------------------
async def test_the_entire_path_calls_no_vendor_at_all(
    dispatcher: Dispatcher, bot: Bot, content: RecordingContentWriter, state: FSMContext
) -> None:
    """The reason this is a branch and not a button on the preview.

    On the writer's path the same walk costs one live LLM call, one write against
    ``MAX_LYRIC_WRITES`` and one charge against the daily budget — all before the payment
    gate. Somebody who arrived with the words already written pays none of it.
    """
    # Arrange / Act
    await walk_to_own_confirm(dispatcher, bot)

    # Assert
    assert content.calls == 0
    assert (await current_draft(state)).lyric_writes == 0


async def test_the_prompt_never_shows_a_writing_frame(
    dispatcher: Dispatcher, bot: Bot, session: RecordingSession
) -> None:
    """Nothing is being written, so a "writing…" screen would be a lie about a spend."""
    # Arrange / Act
    await walk_to_own_confirm(dispatcher, bot)

    # Assert
    assert not [text for text in screen_texts(session) if "Writing the words" in text]


# ---------------------------------------------------------------------------
# the words themselves
# ---------------------------------------------------------------------------
async def test_the_typed_words_become_the_lyric_verbatim(
    dispatcher: Dispatcher, bot: Bot, state: FSMContext
) -> None:
    # Arrange
    await start_own_lyrics(dispatcher, bot)

    # Act
    await send(dispatcher, bot, PASTED)

    # Assert
    lyrics = (await current_draft(state)).lyrics
    assert lyrics is not None
    assert "Aunt Zulfiya wrote these words" in lyrics.as_plain_text()


async def test_no_name_is_woven_into_words_the_customer_wrote(
    dispatcher: Dispatcher, bot: Bot, state: FSMContext
) -> None:
    """The nameless half of the request, at the one place it would otherwise be undone.

    On the writer's path ``build_lyric_draft`` guarantees a hook section carrying the
    recipient. Here there is no recipient, so there is nothing to guarantee — and inventing
    one would put a word the customer never typed into a song that gets sung.
    """
    # Arrange
    await start_own_lyrics(dispatcher, bot)

    # Act
    await send(dispatcher, bot, PASTED)

    # Assert
    lyrics = (await current_draft(state)).lyrics
    assert lyrics is not None
    assert lyrics.name_display is None
    assert lyrics.name_hook_sections == ()
    assert lyrics.as_plain_text().strip() == PASTED.strip()


async def test_a_lyric_too_short_to_sing_is_refused_and_the_step_stands(
    dispatcher: Dispatcher, bot: Bot, state: FSMContext
) -> None:
    """The same validator the paste path has always used; the customer stays on the step."""
    # Arrange
    await start_own_lyrics(dispatcher, bot)

    # Act
    await send(dispatcher, bot, "ok")

    # Assert
    assert (await current_draft(state)).lyrics is None
    assert await state.get_state() == Wizard.lyrics.state


async def test_a_voice_message_is_answered_with_a_request_for_text(
    dispatcher: Dispatcher, bot: Bot, session: RecordingSession
) -> None:
    """Lyrics are words. The screen asks for words."""
    # Arrange
    await start_own_lyrics(dispatcher, bot)
    session.clear()

    # Act
    await dispatcher.feed_update(bot, Update(update_id=9_201, message=make_non_text_message()))

    # Assert
    assert translate("wizard.lyrics.type_only", Language.EN) in screen_texts(session)


async def test_the_preview_calls_the_words_the_customers_own(
    dispatcher: Dispatcher, bot: Bot, session: RecordingSession, state: FSMContext
) -> None:
    """The writer's preview invites the reader to "send me your own", which they just did."""
    # Arrange
    await start_own_lyrics(dispatcher, bot)

    # Act
    await send(dispatcher, bot, PASTED)

    # Assert
    lyrics = (await current_draft(state)).lyrics
    assert lyrics is not None
    assert session.last_screen.text == translate(
        "wizard.lyrics.own_preview",
        Language.EN,
        title=lyrics.title,
        lyrics=lyrics.as_plain_text(),
    )


async def test_the_preview_offers_no_rewrite_of_words_the_bot_did_not_write(
    dispatcher: Dispatcher, bot: Bot, session: RecordingSession
) -> None:
    """Asking the writer needs a recipient, and this order never collects one.

    A regenerate button here would offer something the draft cannot supply, so it is not
    drawn. Back is the way out, and on this order it returns to the occasion list.
    """
    # Arrange
    await start_own_lyrics(dispatcher, bot)

    # Act
    await send(dispatcher, bot, PASTED)

    # Assert
    offered = {data for _, data in buttons(session.last_screen.reply_markup)}
    assert NavCB(action=NavAction.REGENERATE).pack() not in offered
    assert APPROVE in offered


# ---------------------------------------------------------------------------
# the summary and the queue
# ---------------------------------------------------------------------------
async def test_the_summary_is_headlined_by_the_song_because_there_is_no_one_to_name(
    dispatcher: Dispatcher, bot: Bot, session: RecordingSession, state: FSMContext
) -> None:
    """The named summary leads with ``{name}`` and carries a note row. Neither exists here."""
    # Arrange / Act
    await walk_to_own_confirm(dispatcher, bot)

    # Assert
    lyrics = (await current_draft(state)).lyrics
    assert lyrics is not None
    assert lyrics.title in session.last_screen.text
    assert translate("wizard.confirm.no_note", Language.EN) not in session.last_screen.text


async def test_the_queued_order_names_nobody_and_carries_their_words(
    dispatcher: Dispatcher,
    bot: Bot,
    content: RecordingContentWriter,
    submitter: RecordingSubmitter,
) -> None:
    """End to end: ``Brief.recipient`` is ``None`` at the queue and no writer was called."""
    # Arrange
    await walk_to_own_confirm(dispatcher, bot)

    # Act
    await press(dispatcher, bot, NavCB(action=NavAction.CONFIRM).pack())

    # Assert
    assert len(submitter.submitted) == 1
    order, _chat, _message = submitter.submitted[0]
    assert order.brief.recipient is None
    approved = order.brief.approved_lyrics
    assert approved is not None
    assert "Aunt Zulfiya wrote these words" in approved.as_plain_text()
    assert content.calls == 0


async def test_the_language_answer_retags_the_words_without_touching_them(
    dispatcher: Dispatcher, bot: Bot, state: FSMContext
) -> None:
    """The words were typed five screens before the language was chosen.

    They are built under the interface language as a provisional tag, so the tag has to move
    when the real answer arrives — and only the tag. Re-deriving the lyric would mean
    deleting what a person typed, which is what this path exists to avoid.
    """
    # Arrange
    await start_own_lyrics(dispatcher, bot)
    await send(dispatcher, bot, PASTED)
    typed = (await current_draft(state)).lyrics
    assert typed is not None
    assert typed.language is Language.EN
    await press(dispatcher, bot, APPROVE)
    await press(dispatcher, bot, GenreCB(value=Genre.UZBEK_POP).pack())
    await press(dispatcher, bot, VocalGenderCB(value=VoiceGender.FEMALE).pack())

    # Act
    await press(dispatcher, bot, LanguageCB(slot=LanguageSlot.OUTPUT, code=Language.RU).pack())

    # Assert
    lyrics = (await current_draft(state)).lyrics
    assert lyrics is not None
    assert lyrics.language is Language.RU
    assert lyrics.sections == typed.sections


# ---------------------------------------------------------------------------
# the path boundary, which is where two orders through one wizard break
# ---------------------------------------------------------------------------
async def test_back_from_the_prompt_returns_to_the_occasion_list(
    dispatcher: Dispatcher, bot: Bot, state: FSMContext
) -> None:
    """Back must land on a step THIS order contains, and here that is where it began."""
    # Arrange
    await start_own_lyrics(dispatcher, bot)

    # Act
    await press(dispatcher, bot, BACK)

    # Assert
    assert await state.get_state() == Wizard.occasion.state


async def test_picking_a_real_occasion_hands_the_writing_back_to_the_bot(
    dispatcher: Dispatcher, bot: Bot, state: FSMContext
) -> None:
    """The un-press, and the reason the own-lyrics button needs no cancel of its own.

    The occasion step is the ONE place ``lyrics_source`` is ever written, which is what makes
    a draft's order stable for the rest of the wizard.
    """
    # Arrange
    await start_own_lyrics(dispatcher, bot)
    await press(dispatcher, bot, BACK)

    # Act
    await press(dispatcher, bot, OccasionCB(value=Occasion.BIRTHDAY).pack())

    # Assert
    draft = await current_draft(state)
    assert draft.lyrics_source is LyricSource.WRITER
    assert draft.occasion is Occasion.BIRTHDAY
    assert await state.get_state() == Wizard.genre.state


async def test_pasting_over_a_written_lyric_leaves_the_writers_path_alone(
    dispatcher: Dispatcher, bot: Bot, state: FSMContext
) -> None:
    """The boundary bug this test exists for, caught the first time the orders forked.

    A customer who types over a lyric the bot wrote is still on the writer's path — they
    answered the note and the name, and their draft has a name hook. Moving ``lyrics_source``
    with the words sent their Back button to the occasion step and jumped the language
    question straight to the summary.
    """
    # Arrange — the writer's path, all the way to a lyric on screen
    await walk_to_lyrics(dispatcher, bot)

    # Act
    await send(dispatcher, bot, PASTED)

    # Assert
    draft = await current_draft(state)
    assert draft.lyrics_source is LyricSource.WRITER
    assert draft.recipient is not None
    lyrics = draft.lyrics
    assert lyrics is not None
    assert lyrics.name_hook_sections, "the writer's path keeps its name-hook guarantee"


async def test_a_stale_regenerate_on_the_own_path_calls_nobody(
    dispatcher: Dispatcher, bot: Bot, content: RecordingContentWriter, state: FSMContext
) -> None:
    """The button is never drawn here, but Telegram keeps every old screen tappable.

    Pressing it must not call the writer — there is no recipient to write about — and must
    not move the draft onto an order whose NAME step it has never seen.
    """
    # Arrange
    await start_own_lyrics(dispatcher, bot)
    await send(dispatcher, bot, PASTED)

    # Act
    await press(dispatcher, bot, NavCB(action=NavAction.REGENERATE).pack())

    # Assert
    draft = await current_draft(state)
    assert content.calls == 0
    assert draft.lyrics_source is LyricSource.OWN
    assert await state.get_state() == Wizard.lyrics.state


async def test_confirm_without_words_lands_back_on_the_prompt(
    dispatcher: Dispatcher, bot: Bot, state: FSMContext
) -> None:
    """A stale Confirm has to resolve to a screen this order contains and can act on."""
    # Arrange
    await start_own_lyrics(dispatcher, bot)

    # Act
    await press(dispatcher, bot, NavCB(action=NavAction.CONFIRM).pack())

    # Assert
    assert await state.get_state() == Wizard.lyrics.state
