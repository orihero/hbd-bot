"""The four structured questions, plus the two language pickers.

Every handler here is bound to the state it belongs to, so a button tapped on an old
message that has scrolled away cannot jump the wizard sideways — it simply does not match,
and the fallback tells the user the session moved on.
"""

from __future__ import annotations

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

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
from hbd.bot.draft import MAX_NOTE_CHARS
from hbd.bot.handlers.common import COMMAND_PREFIX, expire, read_draft, say, show_step
from hbd.bot.handlers.lyrics import enter_lyrics_step
from hbd.bot.i18n import translate
from hbd.bot.states import Wizard, WizardStep
from hbd.logging import get_logger

__all__ = ["build_router"]

_LOG = get_logger(__name__)


async def handle_ui_language(
    callback: CallbackQuery, callback_data: LanguageCB, state: FSMContext
) -> None:
    """Interface language. Chosen independently of the language the kit is sung in."""
    await callback.answer()
    draft = await read_draft(state)
    if draft is None:
        await expire(callback, state)
        return
    await show_step(
        callback, state, draft.updated(ui_language=callback_data.code), WizardStep.OCCASION
    )


async def handle_occasion(
    callback: CallbackQuery, callback_data: OccasionCB, state: FSMContext
) -> None:
    await callback.answer()
    draft = await read_draft(state)
    if draft is None:
        await expire(callback, state)
        return
    await show_step(callback, state, draft.updated(occasion=callback_data.value), WizardStep.GENRE)


async def handle_genre(callback: CallbackQuery, callback_data: GenreCB, state: FSMContext) -> None:
    await callback.answer()
    draft = await read_draft(state)
    if draft is None:
        await expire(callback, state)
        return
    await show_step(
        callback, state, draft.updated(genre=callback_data.value), WizardStep.VOCAL_GENDER
    )


async def handle_vocal_gender(
    callback: CallbackQuery, callback_data: VocalGenderCB, state: FSMContext
) -> None:
    await callback.answer()
    draft = await read_draft(state)
    if draft is None:
        await expire(callback, state)
        return
    await show_step(
        callback, state, draft.updated(vocal_gender=callback_data.value), WizardStep.NOTE
    )


async def handle_note_skipped(callback: CallbackQuery, state: FSMContext) -> None:
    """The note is the only optional answer, so it is the only step with a Skip.

    The draft is passed through UNCHANGED, which is the whole behaviour. The button is one
    callback with two labels: "Skip" on an empty note, "Keep this note" once one has been
    written — ``note_keyboard`` relabels it so Back-into-the-note-step has an obvious way
    onwards that is not "type it all again". Writing ``note=""`` here made that second
    label a lie: the customer pressed Keep and the note was deleted. An empty note needs no
    write either, because the field already defaults to the empty string.
    """
    await callback.answer()
    draft = await read_draft(state)
    if draft is None:
        await expire(callback, state)
        return
    await show_step(callback, state, draft, WizardStep.NAME)


async def handle_note(message: Message, state: FSMContext) -> None:
    """The one free-text answer about the recipient. Commands are not answers.

    The command guard is the fix for a defect, not a nicety: this handler is bound to any
    text at the note step, so before it a customer who typed ``/help`` here had "/help"
    stored as the fact we knew about their mother and sung back to her. Re-showing the step
    puts the prompt and its Skip button back rather than leaving the chat silent.
    """
    draft = await read_draft(state)
    if draft is None:
        await expire(message, state)
        return
    note = (message.text or "").strip()
    if note.startswith(COMMAND_PREFIX):
        _LOG.info("command-shaped text at the note step; not stored", extra={"length": len(note)})
        await show_step(message, state, draft, WizardStep.NOTE)
        return
    if len(note) > MAX_NOTE_CHARS:
        _LOG.info("note rejected: too long", extra={"length": len(note), "limit": MAX_NOTE_CHARS})
        await say(
            message, translate("wizard.note.too_long", draft.ui_language, limit=MAX_NOTE_CHARS)
        )
        return
    await show_step(message, state, draft.updated(note=note), WizardStep.NAME)


async def handle_output_language(
    callback: CallbackQuery, callback_data: LanguageCB, state: FSMContext, deps: BotDeps
) -> None:
    """The language the song and the greetings are IN. Unrelated to the interface language.

    This is the last answer, so it is also where the lyric gets written: every input the
    writer needs is now in the draft, and the customer goes straight from the last question
    to the words themselves rather than to a summary of a song nobody has read.

    Re-picking the SAME language is not an answer, it is navigation — Back from the preview
    lands here, and the obvious way onwards is to press the button that is already ticked.
    Treating that as a fresh answer would call the writer again and throw away whatever
    lyric the draft holds, which for a customer who pasted their aunt's poem means losing
    it with no warning and no way back. So an unchanged language with a lyric already in
    hand simply returns to the preview; changing the language still rewrites, because a
    lyric in the wrong language is not the lyric they asked for.
    """
    await callback.answer()
    draft = await read_draft(state)
    if draft is None:
        await expire(callback, state)
        return
    if callback_data.code == draft.output_language and draft.lyrics is not None:
        _LOG.info("output language re-picked unchanged; keeping the lyric already in hand")
        await show_step(callback, state, draft, WizardStep.LYRICS)
        return
    await enter_lyrics_step(
        callback, state, deps, draft.updated(output_language=callback_data.code)
    )


def build_router() -> Router:
    router = Router(name="questions")
    router.callback_query.register(
        handle_ui_language, Wizard.ui_language, LanguageCB.filter(F.slot == LanguageSlot.UI)
    )
    router.callback_query.register(handle_occasion, Wizard.occasion, OccasionCB.filter())
    router.callback_query.register(handle_genre, Wizard.genre, GenreCB.filter())
    router.callback_query.register(handle_vocal_gender, Wizard.vocal_gender, VocalGenderCB.filter())
    router.callback_query.register(
        handle_note_skipped, Wizard.note, NavCB.filter(F.action == NavAction.SKIP)
    )
    router.message.register(handle_note, Wizard.note, F.text)
    router.callback_query.register(
        handle_output_language,
        Wizard.output_language,
        LanguageCB.filter(F.slot == LanguageSlot.OUTPUT),
    )
    return router
