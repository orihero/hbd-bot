"""The lyric preview step, driven the way a customer drives it.

This step is the reason the wizard now holds a ``ContentWriter``: the words are written,
shown and approved before anything is queued or charged. Three answers reach it — approve,
regenerate, paste your own — and each one has to leave the draft in a state the summary and
the worker can both trust. So everything here goes through a real ``Dispatcher``, pressing
the callback data the real keyboards drew, and asserts on the draft that comes back out of
FSM storage rather than on an internal call.
"""

from __future__ import annotations

import pytest
from aiogram import Bot, Dispatcher
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import Update

from hbd.bot.app import build_dispatcher
from hbd.bot.callbacks import LanguageCB, LanguageSlot, NavAction, NavCB
from hbd.bot.deps import BotDeps
from hbd.bot.draft import WizardDraft, load_draft
from hbd.bot.handlers.common import show_step
from hbd.bot.handlers.lyrics import MAX_LYRIC_WRITES
from hbd.bot.i18n import translate
from hbd.bot.keyboards import lyrics_keyboard
from hbd.bot.lyrics_entry import MAX_LYRIC_CHARS, MIN_LYRIC_CHARS
from hbd.bot.states import Wizard, WizardStep
from hbd.config import Settings
from hbd.contracts import Brief, Genre, Language, LyricDraft, Occasion, Ok, Result, VoiceGender
from hbd.errors import ProviderTimeoutError
from tests.conftest import make_name
from tests.test_bot.conftest import (
    LYRIC_VERSE,
    RecordingContentWriter,
    RecordingSession,
    RecordingSubmitter,
    buttons,
    make_message,
    make_non_text_message,
)
from tests.test_bot.test_wizard_flow import (
    UZBEK_DISPLAY,
    approve_lyrics,
    press,
    send,
    walk_to_confirm,
    walk_to_lyrics,
)

#: Long enough to clear ``MIN_LYRIC_CHARS``, and split over two verses by a blank line.
PASTED = "Aunt Zulfiya wrote these words\nfor tonight\n\nand we have sung them for years"


async def current_draft(state: FSMContext) -> WizardDraft:
    """The draft as it actually survives a round trip through FSM storage."""
    result = load_draft(await state.get_data())
    assert isinstance(result, Ok), "the wizard must leave a readable draft behind"
    return result.value


def screen_texts(session: RecordingSession) -> tuple[str, ...]:
    """Every text the user was shown, in order — screens and one-off sentences alike."""
    return tuple(call.text or "" for call in session.calls if hasattr(call, "text"))


# ---------------------------------------------------------------------------
# arriving at the step
# ---------------------------------------------------------------------------
async def test_choosing_the_output_language_writes_a_lyric_and_shows_it(
    dispatcher: Dispatcher,
    bot: Bot,
    session: RecordingSession,
    content: RecordingContentWriter,
    state: FSMContext,
) -> None:
    # Arrange / Act
    await walk_to_lyrics(dispatcher, bot)

    # Assert — one lyric written, and its title and words are on the screen
    assert content.calls == 1
    assert await state.get_state() == Wizard.lyrics.state
    lyrics = (await current_draft(state)).lyrics
    assert lyrics is not None
    assert lyrics.title in session.last_screen.text
    assert LYRIC_VERSE in session.last_screen.text


async def test_the_writing_frame_is_shown_before_the_preview(
    dispatcher: Dispatcher, bot: Bot, session: RecordingSession, state: FSMContext
) -> None:
    """Writing is a live vendor call on the customer's screen, so it must not look frozen."""
    # Arrange / Act
    await walk_to_lyrics(dispatcher, bot)

    # Assert — the "writing…" frame goes up, and the preview replaces it afterwards
    texts = screen_texts(session)
    lyrics = (await current_draft(state)).lyrics
    assert lyrics is not None
    writing_at = texts.index(translate("wizard.lyrics.writing", Language.EN))
    preview_at = next(index for index, text in enumerate(texts) if lyrics.title in text)
    assert writing_at < preview_at


async def test_the_preview_offers_approve_regenerate_and_a_back_button(
    dispatcher: Dispatcher, bot: Bot, session: RecordingSession
) -> None:
    # Arrange / Act
    await walk_to_lyrics(dispatcher, bot)

    # Assert
    offered = {data for _, data in buttons(session.last_screen.reply_markup)}
    assert NavCB(action=NavAction.LYRICS_OK).pack() in offered
    assert NavCB(action=NavAction.REGENERATE).pack() in offered
    assert NavCB(action=NavAction.BACK).pack() in offered
    assert NavCB(action=NavAction.SKIP).pack() not in offered


def test_the_regenerate_button_is_labelled_not_left_as_a_raw_key() -> None:
    """``NavAction.REGENERATE`` packs as ``regen`` but its label key spells the word out.

    Every other nav button derives its label from ``button.{action.value}``; this one
    cannot, and ``translate`` returns the key itself rather than raising when a lookup
    misses, so a wrong key here would ship as a button reading "button.regen".
    """
    # Arrange / Act
    labels = {data: text for text, data in buttons(lyrics_keyboard(Language.EN))}

    # Assert
    label = labels[NavCB(action=NavAction.REGENERATE).pack()]
    assert label == translate("button.regenerate", Language.EN)
    assert not label.startswith("button.")


# ---------------------------------------------------------------------------
# approving
# ---------------------------------------------------------------------------
async def test_approving_moves_on_to_the_summary(
    dispatcher: Dispatcher, bot: Bot, session: RecordingSession, state: FSMContext
) -> None:
    # Arrange
    await walk_to_lyrics(dispatcher, bot)

    # Act
    await approve_lyrics(dispatcher, bot)

    # Assert
    assert await state.get_state() == Wizard.confirm.state
    assert UZBEK_DISPLAY in session.last_screen.text


async def test_the_submitted_order_carries_the_lyric_the_customer_approved(
    dispatcher: Dispatcher,
    bot: Bot,
    submitter: RecordingSubmitter,
    content: RecordingContentWriter,
    state: FSMContext,
) -> None:
    # Arrange
    await walk_to_lyrics(dispatcher, bot)
    approved = (await current_draft(state)).lyrics

    # Act
    await approve_lyrics(dispatcher, bot)
    await press(dispatcher, bot, NavCB(action=NavAction.CONFIRM).pack())

    # Assert — verbatim, not a lyric the worker will write again for itself
    order, _, _ = submitter.submitted[0]
    assert order.brief.approved_lyrics == approved
    assert content.calls == 1


# ---------------------------------------------------------------------------
# regenerating
# ---------------------------------------------------------------------------
async def test_regenerating_asks_the_writer_again_and_shows_the_new_lyric(
    dispatcher: Dispatcher,
    bot: Bot,
    session: RecordingSession,
    content: RecordingContentWriter,
    state: FSMContext,
) -> None:
    # Arrange
    await walk_to_lyrics(dispatcher, bot)
    first = (await current_draft(state)).lyrics

    # Act
    await press(dispatcher, bot, NavCB(action=NavAction.REGENERATE).pack())

    # Assert
    assert content.calls == 2
    second = (await current_draft(state)).lyrics
    assert second is not None
    assert second != first
    assert second.title in session.last_screen.text


async def test_a_regenerate_asks_the_writer_for_a_lyric_not_for_the_one_it_already_gave(
    dispatcher: Dispatcher, bot: Bot, content: RecordingContentWriter
) -> None:
    """A brief still carrying the old lyric would short-circuit the pipeline's writer."""
    # Arrange
    await walk_to_lyrics(dispatcher, bot)

    # Act
    await press(dispatcher, bot, NavCB(action=NavAction.REGENERATE).pack())

    # Assert
    assert [brief.approved_lyrics for brief in content.briefs] == [None, None]


async def test_regenerating_keeps_every_other_answer(
    dispatcher: Dispatcher, bot: Bot, state: FSMContext
) -> None:
    # Arrange
    await walk_to_lyrics(dispatcher, bot)
    before = await current_draft(state)

    # Act
    await press(dispatcher, bot, NavCB(action=NavAction.REGENERATE).pack())

    # Assert — ``lyric_writes`` is expected to move; it is the spend counter, not an answer
    after = await current_draft(state)
    ignored = {"lyrics", "lyric_writes"}
    assert after.model_dump(exclude=ignored) == before.model_dump(exclude=ignored)
    assert after.lyric_writes == before.lyric_writes + 1


# ---------------------------------------------------------------------------
# pasting your own
# ---------------------------------------------------------------------------
async def test_a_pasted_lyric_replaces_ours_and_keeps_the_previous_title(
    dispatcher: Dispatcher, bot: Bot, session: RecordingSession, state: FSMContext
) -> None:
    # Arrange
    await walk_to_lyrics(dispatcher, bot)
    generated = (await current_draft(state)).lyrics
    assert generated is not None

    # Act
    await send(dispatcher, bot, PASTED)

    # Assert — the words are theirs, the title is the one they had already seen
    pasted = (await current_draft(state)).lyrics
    assert pasted is not None
    assert pasted.title == generated.title
    assert "Aunt Zulfiya wrote these words" in pasted.as_plain_text()
    assert LYRIC_VERSE not in pasted.as_plain_text()
    assert translate("wizard.lyrics.updated", Language.EN) in screen_texts(session)
    assert await state.get_state() == Wizard.lyrics.state


async def test_a_pasted_lyric_still_gets_a_name_hook_carrying_the_recipient(
    dispatcher: Dispatcher, bot: Bot, state: FSMContext
) -> None:
    """The composition plan cuts the hook into its own chunk, so a paste cannot skip it."""
    # Arrange
    await walk_to_lyrics(dispatcher, bot)

    # Act — a lyric that never mentions the recipient
    await send(dispatcher, bot, PASTED)

    # Assert
    pasted = (await current_draft(state)).lyrics
    assert pasted is not None
    hooks = pasted.name_hook_sections
    assert len(hooks) == 1
    assert any(UZBEK_DISPLAY in line for line in hooks[0].lines)
    assert pasted.name_display == UZBEK_DISPLAY


async def test_a_pasted_lyric_is_split_into_a_section_per_blank_line(
    dispatcher: Dispatcher, bot: Bot, state: FSMContext
) -> None:
    # Arrange
    await walk_to_lyrics(dispatcher, bot)

    # Act
    await send(dispatcher, bot, PASTED)

    # Assert — two blocks in, two sections out
    pasted = (await current_draft(state)).lyrics
    assert pasted is not None
    assert len(pasted.sections) == 2


async def test_an_approved_paste_is_what_reaches_the_queue(
    dispatcher: Dispatcher, bot: Bot, submitter: RecordingSubmitter, state: FSMContext
) -> None:
    # Arrange
    await walk_to_lyrics(dispatcher, bot)
    await send(dispatcher, bot, PASTED)
    pasted = (await current_draft(state)).lyrics

    # Act
    await approve_lyrics(dispatcher, bot)
    await press(dispatcher, bot, NavCB(action=NavAction.CONFIRM).pack())

    # Assert
    order, _, _ = submitter.submitted[0]
    assert order.brief.approved_lyrics == pasted


@pytest.mark.parametrize(
    ("typed", "expected_key", "limit"),
    [
        ("too short", "wizard.lyrics.too_short", MIN_LYRIC_CHARS),
        ("la " * MAX_LYRIC_CHARS, "wizard.lyrics.too_long", MAX_LYRIC_CHARS),
    ],
)
async def test_an_unusable_paste_is_refused_and_the_previous_lyric_survives(
    dispatcher: Dispatcher,
    bot: Bot,
    session: RecordingSession,
    state: FSMContext,
    typed: str,
    expected_key: str,
    limit: int,
) -> None:
    # Arrange
    await walk_to_lyrics(dispatcher, bot)
    before = (await current_draft(state)).lyrics
    session.clear()

    # Act
    await send(dispatcher, bot, typed)

    # Assert — told why, in their language, still on the step, lyric untouched
    assert session.last_screen.text == translate(expected_key, Language.EN, limit=limit)
    assert str(limit) in session.last_screen.text
    assert await state.get_state() == Wizard.lyrics.state
    assert (await current_draft(state)).lyrics == before


async def test_a_paste_of_nothing_but_blank_lines_is_refused(
    dispatcher: Dispatcher, bot: Bot, session: RecordingSession, state: FSMContext
) -> None:
    """A long run of blank lines is a stray keystroke, not a lyric.

    It is caught by the length bound rather than by the "nothing survived cleaning" branch,
    because stripping empties it first — which is the point: the user gets the same
    sentence either way and the approved lyric is not lost to a slip of the thumb.
    """
    # Arrange
    await walk_to_lyrics(dispatcher, bot)
    before = (await current_draft(state)).lyrics
    session.clear()

    # Act
    await send(dispatcher, bot, "\n   \n" * 20)

    # Assert
    assert translate("wizard.lyrics.too_short", Language.EN, limit=MIN_LYRIC_CHARS) in (
        screen_texts(session)
    )
    assert (await current_draft(state)).lyrics == before


async def test_a_voice_message_at_the_lyrics_step_asks_for_typed_text(
    dispatcher: Dispatcher, bot: Bot, session: RecordingSession, state: FSMContext
) -> None:
    # Arrange
    await walk_to_lyrics(dispatcher, bot)
    session.clear()

    # Act
    await dispatcher.feed_update(bot, Update(update_id=9_101, message=make_non_text_message()))

    # Assert
    assert session.last_screen.text == translate("wizard.lyrics.type_only", Language.EN)
    assert await state.get_state() == Wizard.lyrics.state


# ---------------------------------------------------------------------------
# navigating away and back
# ---------------------------------------------------------------------------
async def test_back_from_the_preview_returns_to_the_output_language(
    dispatcher: Dispatcher, bot: Bot, session: RecordingSession, state: FSMContext
) -> None:
    # Arrange
    await walk_to_lyrics(dispatcher, bot)

    # Act
    await press(dispatcher, bot, NavCB(action=NavAction.BACK).pack())

    # Assert
    assert await state.get_state() == Wizard.output_language.state
    assert session.last_screen.text == translate("wizard.output_language.prompt", Language.EN)


async def test_back_from_the_summary_returns_to_the_preview_with_the_lyric_intact(
    dispatcher: Dispatcher,
    bot: Bot,
    session: RecordingSession,
    content: RecordingContentWriter,
    state: FSMContext,
) -> None:
    # Arrange
    await walk_to_confirm(dispatcher, bot)
    approved = (await current_draft(state)).lyrics
    assert approved is not None

    # Act
    await press(dispatcher, bot, NavCB(action=NavAction.BACK).pack())

    # Assert — the same words come back; Back must not spend another vendor call
    assert await state.get_state() == Wizard.lyrics.state
    assert approved.title in session.last_screen.text
    assert (await current_draft(state)).lyrics == approved
    assert content.calls == 1


async def test_choosing_the_language_again_writes_a_fresh_lyric(
    dispatcher: Dispatcher, bot: Bot, content: RecordingContentWriter, state: FSMContext
) -> None:
    """Back then forward is the documented retry after a writer failure."""
    # Arrange
    await walk_to_lyrics(dispatcher, bot)
    await press(dispatcher, bot, NavCB(action=NavAction.BACK).pack())

    # Act
    await press(dispatcher, bot, LanguageCB(slot=LanguageSlot.OUTPUT, code=Language.RU).pack())

    # Assert
    assert content.calls == 2
    draft = await current_draft(state)
    assert draft.output_language is Language.RU
    assert draft.lyrics is not None
    assert draft.lyrics.language is Language.RU


# ---------------------------------------------------------------------------
# the writer falling over
# ---------------------------------------------------------------------------
async def test_a_failing_writer_leaves_the_customer_on_the_previous_step(
    dispatcher: Dispatcher,
    bot: Bot,
    session: RecordingSession,
    content: RecordingContentWriter,
    submitter: RecordingSubmitter,
    state: FSMContext,
) -> None:
    # Arrange — the vendor times out on the customer's screen
    content.failure = ProviderTimeoutError("lyric writer timed out", provider="fake-llm")

    # Act
    await walk_to_lyrics(dispatcher, bot)

    # Assert — told plainly, put back where pressing again retries, nothing queued
    texts = screen_texts(session)
    assert translate("wizard.lyrics.failed", Language.EN) in texts
    assert await state.get_state() == Wizard.output_language.state
    assert (await current_draft(state)).lyrics is None
    assert submitter.submitted == []


async def test_a_recovered_writer_lets_the_customer_carry_on(
    dispatcher: Dispatcher,
    bot: Bot,
    content: RecordingContentWriter,
    submitter: RecordingSubmitter,
    state: FSMContext,
) -> None:
    # Arrange
    content.failure = ProviderTimeoutError("lyric writer timed out", provider="fake-llm")
    await walk_to_lyrics(dispatcher, bot)
    content.failure = None

    # Act — the same button, pressed again
    await press(dispatcher, bot, LanguageCB(slot=LanguageSlot.OUTPUT, code=Language.UZ_LATN).pack())
    await approve_lyrics(dispatcher, bot)
    await press(dispatcher, bot, NavCB(action=NavAction.CONFIRM).pack())

    # Assert
    assert await state.get_state() is None
    order, _, _ = submitter.submitted[0]
    assert order.brief.approved_lyrics is not None


# ---------------------------------------------------------------------------
# the summary cannot outrun the preview
# ---------------------------------------------------------------------------
async def test_confirm_on_a_draft_with_no_approved_lyric_goes_back_to_the_preview(
    dispatcher: Dispatcher,
    bot: Bot,
    session: RecordingSession,
    submitter: RecordingSubmitter,
    content: RecordingContentWriter,
    state: FSMContext,
) -> None:
    """A draft written before the preview step existed, parked on the summary.

    ``REQUIRED_ANSWERS`` deliberately excludes the lyric, so ``to_brief()`` succeeds on such
    a draft and nothing else on the submit path consults ``is_complete``. Redis outlives a
    deploy, so this is a live session across a release, not a hypothetical: without the
    guard the order is queued with ``approved_lyrics=None`` and the worker sings words the
    customer never saw — no error, no log, just the wrong song.
    """
    # Arrange — every answer given, no lyric, sitting on the confirm screen
    await walk_to_lyrics(dispatcher, bot)
    parked = (await current_draft(state)).updated(lyrics=None)
    await state.set_state(Wizard.confirm)
    await state.update_data(**parked.to_state_data())
    session.clear()

    # Act
    await press(dispatcher, bot, NavCB(action=NavAction.CONFIRM).pack())

    # Assert — nothing queued, and the customer is looking at a lyric to approve
    assert submitter.submitted == []
    assert await state.get_state() == Wizard.lyrics.state
    written = (await current_draft(state)).lyrics
    assert written is not None
    assert written.title in session.last_screen.text
    assert content.calls == 2


# ---------------------------------------------------------------------------
# spending, and racing
# ---------------------------------------------------------------------------
class StateWatchingContentWriter(RecordingContentWriter):
    """Records the FSM state the session was parked in while the vendor call was in flight.

    The concurrency bug this exists to fence is invisible to a sequential test: writing is
    an ``await``, aiogram handles updates as concurrent tasks, and the preview the user is
    reading invites them to send their own lyric as a message. If ``Wizard.lyrics`` were
    still live during the write, that paste would be accepted, confirmed to the customer,
    and then overwritten by the machine's words when the call returned.
    """

    def __init__(self, state: FSMContext) -> None:
        super().__init__()
        self._state = state
        self.states_during_write: list[str | None] = []

    async def write_lyrics(self, brief: Brief) -> Result[LyricDraft]:
        self.states_during_write.append(await self._state.get_state())
        return await super().write_lyrics(brief)


async def test_the_session_is_not_accepting_input_while_the_writer_is_working(
    bot: Bot, settings: Settings, storage: MemoryStorage, state: FSMContext
) -> None:
    # Arrange
    watcher = StateWatchingContentWriter(state)
    deps = BotDeps(settings=settings, submitter=RecordingSubmitter(), content=watcher)
    dispatcher = build_dispatcher(deps, storage=storage)

    # Act
    await walk_to_lyrics(dispatcher, bot)

    # Assert — no wizard handler is registered on the busy state, so nothing can race
    assert watcher.states_during_write == [Wizard.submitting.state]
    assert await state.get_state() == Wizard.lyrics.state


async def test_a_message_sent_while_the_writer_is_working_cannot_overwrite_the_result(
    dispatcher: Dispatcher, bot: Bot, state: FSMContext
) -> None:
    """A paste that lands mid-write is not silently confirmed and then thrown away."""
    # Arrange — park the session where ``enter_lyrics_step`` parks it during the call
    await walk_to_lyrics(dispatcher, bot)
    written = (await current_draft(state)).lyrics
    await state.set_state(Wizard.submitting)

    # Act
    await send(dispatcher, bot, PASTED)

    # Assert — the paste was refused, not accepted and then lost
    assert (await current_draft(state)).lyrics == written


async def test_a_session_cannot_bill_the_writer_without_limit(
    dispatcher: Dispatcher,
    bot: Bot,
    session: RecordingSession,
    content: RecordingContentWriter,
    state: FSMContext,
) -> None:
    """Regenerate is pre-payment vendor spend on a button anyone reaching /start can press."""
    # Arrange — the walk to the preview spends the first write
    await walk_to_lyrics(dispatcher, bot)

    # Act — press regenerate until the cap is reached, then once more
    for _ in range(MAX_LYRIC_WRITES):
        await press(dispatcher, bot, NavCB(action=NavAction.REGENERATE).pack())

    # Assert — the writer stopped being called, and the customer was told why
    assert content.calls == MAX_LYRIC_WRITES
    assert (await current_draft(state)).lyric_writes == MAX_LYRIC_WRITES
    assert any(
        translate("wizard.lyrics.too_many", Language.EN, limit=MAX_LYRIC_WRITES) == text
        for text in screen_texts(session)
    )
    assert (await current_draft(state)).lyrics is not None


async def test_repicking_the_same_output_language_keeps_a_pasted_lyric(
    dispatcher: Dispatcher, bot: Bot, content: RecordingContentWriter, state: FSMContext
) -> None:
    """Back then forward is navigation, not a new answer, and must not destroy their words."""
    # Arrange — the customer pastes their own lyric, then steps back to check the language
    await walk_to_lyrics(dispatcher, bot)
    await send(dispatcher, bot, PASTED)
    pasted = (await current_draft(state)).lyrics
    await press(dispatcher, bot, NavCB(action=NavAction.BACK).pack())
    calls_before = content.calls

    # Act — pressing the language that is already chosen
    await press(
        dispatcher, bot, LanguageCB(slot=LanguageSlot.OUTPUT, code=Language.UZ_LATN).pack()
    )

    # Assert
    assert content.calls == calls_before
    assert (await current_draft(state)).lyrics == pasted
    assert await state.get_state() == Wizard.lyrics.state


async def test_choosing_a_different_output_language_still_rewrites(
    dispatcher: Dispatcher, bot: Bot, content: RecordingContentWriter, state: FSMContext
) -> None:
    """A lyric in the wrong language is not the lyric they asked for, pasted or not."""
    # Arrange
    await walk_to_lyrics(dispatcher, bot)
    await send(dispatcher, bot, PASTED)
    await press(dispatcher, bot, NavCB(action=NavAction.BACK).pack())
    calls_before = content.calls

    # Act
    await press(dispatcher, bot, LanguageCB(slot=LanguageSlot.OUTPUT, code=Language.RU).pack())

    # Assert
    assert content.calls == calls_before + 1
    lyrics = (await current_draft(state)).lyrics
    assert lyrics is not None
    assert lyrics.language is Language.RU


async def test_a_summary_with_no_lyric_lands_on_a_screen_whose_buttons_work(
    bot: Bot, state: FSMContext
) -> None:
    """``resolve_step`` downgrades one rule at a time; ``show_step`` has to run it to a fixpoint.

    A summary whose lyric was never approved resolves to the preview, and a preview with no
    lyric resolves further to the language question. Stopping after one rule would park the
    FSM in ``Wizard.lyrics`` while rendering the language picker, whose buttons are filtered
    to ``Wizard.output_language`` — every one of them dead, and only Back to recover.
    """
    # Arrange
    draft = WizardDraft(
        ui_language=Language.EN,
        occasion=Occasion.BIRTHDAY,
        genre=Genre.POP,
        vocal_gender=VoiceGender.FEMALE,
        recipient=make_name(),
        output_language=Language.EN,
    )

    # Act
    shown = await show_step(make_message("anything").as_(bot), state, draft, WizardStep.CONFIRM)

    # Assert — the state and the screen agree
    assert shown is WizardStep.OUTPUT_LANGUAGE
    assert await state.get_state() == Wizard.output_language.state
