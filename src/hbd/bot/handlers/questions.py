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
from hbd.bot.draft import MAX_NOTE_CHARS, LyricSource, WizardDraft
from hbd.bot.handlers.balance import show_confirm
from hbd.bot.handlers.common import (
    COMMAND_PREFIX,
    expire,
    is_menu_label,
    read_draft,
    say,
    show_step,
)
from hbd.bot.handlers.lyrics import enter_lyrics_step, retagged
from hbd.bot.i18n import translate
from hbd.bot.states import Wizard, WizardStep, next_step
from hbd.contracts import Occasion
from hbd.logging import get_logger

__all__ = ["build_router"]

_LOG = get_logger(__name__)


def _after(draft: WizardDraft, step: WizardStep) -> WizardStep:
    """The step that follows ``step`` on THIS draft's path.

    The two paths diverge after the voice question — the writer's asks for a note and a
    name, the customer's goes straight to the language — so a handler that named its own
    successor would be right for one of them and wrong for the other. ``states.next_step``
    owns the answer; this only supplies the fallback for the last step, which no handler
    here can reach because CONFIRM is nobody's successor.
    """
    following = next_step(step, is_own_lyrics=draft.is_own_lyrics)
    return following if following is not None else step


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
    # This is the un-press for the own-lyrics button, and the reason that button needs no
    # "no, go back" of its own: picking a real occasion puts the draft back on the writer's
    # path, whatever it was on before. The occasion step is the ONE place ``lyrics_source``
    # is ever written, and that is what makes the wizard's order stable — see
    # ``handlers.lyrics`` for why nothing downstream may move it.
    await show_step(
        callback,
        state,
        draft.updated(occasion=callback_data.value, lyrics_source=LyricSource.WRITER),
        WizardStep.GENRE,
    )


async def handle_genre(callback: CallbackQuery, callback_data: GenreCB, state: FSMContext) -> None:
    await callback.answer()
    draft = await read_draft(state)
    if draft is None:
        await expire(callback, state)
        return
    await show_step(
        callback, state, draft.updated(genre=callback_data.value), _after(draft, WizardStep.GENRE)
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
        callback,
        state,
        draft.updated(vocal_gender=callback_data.value),
        _after(draft, WizardStep.VOCAL_GENDER),
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
    """The one free-text answer about the recipient. Commands and menu labels are not answers.

    The command guard is the fix for a defect, not a nicety: this handler is bound to any
    text at the note step, so before it a customer who typed ``/help`` here had "/help"
    stored as the fact we knew about their mother and sung back to her. Re-showing the step
    puts the prompt and its Skip button back rather than leaving the chat silent.

    The menu guard beside it closes the same hole from the other side, and the stakes at
    THIS step are the highest of the three that carry it: what lands in ``draft.note`` is a
    fact we claim to know about somebody's mother, and the writer turns it into a line that
    is sung to her. "🎫 Limitim" is not a fact about anybody. The persistent reply keyboard
    is chat-level state Telegram keeps pinned under the text box, so its labels arrive as
    ordinary text messages and reach exactly the steps that accept any text.

    The real defence is the router order — ``menu`` is registered above every step router,
    so a label is claimed before this handler is offered it — and the router order is one
    line in ``handlers/__init__``. This is the second brace, kept because that one line is
    the kind of thing a later refactor reorders without noticing what it was holding up.
    """
    draft = await read_draft(state)
    if draft is None:
        await expire(message, state)
        return
    note = (message.text or "").strip()
    if note.startswith(COMMAND_PREFIX) or is_menu_label(note):
        _LOG.info(
            "command- or menu-shaped text at the note step; not stored",
            extra={"length": len(note)},
        )
        await show_step(message, state, draft, WizardStep.NOTE)
        return
    if len(note) > MAX_NOTE_CHARS:
        _LOG.info("note rejected: too long", extra={"length": len(note), "limit": MAX_NOTE_CHARS})
        await say(
            message, translate("wizard.note.too_long", draft.ui_language, limit=MAX_NOTE_CHARS)
        )
        return
    await show_step(message, state, draft.updated(note=note), WizardStep.NAME)


async def handle_own_lyrics(callback: CallbackQuery, state: FSMContext) -> None:
    """ "I will write the words myself", chosen from the occasion list.

    It answers two things at once, and the second is the reason it can live on that screen
    at all. It records the lyric source — which is what makes the preview step prompt for
    the customer's words instead of calling the writer — and it settles the occasion as
    ``CUSTOM``, because the question on screen still has to be answered: ``Brief.occasion``
    is not optional, and somebody bringing their own lyric has told us the song is not a
    birthday card by not saying it is one. ``CUSTOM`` is that answer's existing name
    ("something else"), so nothing downstream meets a value it has never seen.

    It also switches the wizard onto :data:`~hbd.bot.states.OWN_LYRICS_ORDER`, and the very
    next screen is the one asking for the words. That is the whole shape of this path: the
    customer said they have the lyric, so nothing is asked before the lyric. The genre, the
    voice and the language follow it, because they are about the music and can be answered
    just as well after the words as before them.

    What is NOT asked, on this path, is the note and the name — see the states module for
    why each stops meaning anything here.

    The occasion stays overridable: this is the FIRST question, Back returns to it, and
    picking a real occasion afterwards leaves ``lyrics_source`` alone — the two answers are
    independent once given, and somebody who wants their own words at a birthday should get
    both. What that costs is that the button cannot be un-pressed from this screen; the way
    back to the writer is the offer the lyric step itself makes, which is where a customer
    is actually looking at the choice.
    """
    await callback.answer()
    draft = await read_draft(state)
    if draft is None:
        await expire(callback, state)
        return
    _LOG.info("customer chose to write the lyric themselves; the writer will not be called")
    await show_step(
        callback,
        state,
        draft.updated(occasion=Occasion.CUSTOM, lyrics_source=LyricSource.OWN),
        WizardStep.LYRICS,
    )


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
    hand simply returns to the preview.

    CHANGING the language rewrites, because a lyric in the wrong language is not the lyric
    they asked for. That holds for a pasted lyric too: on this path the language is answered
    BEFORE the words exist, so changing it is changing an input the lyric is derived from.

    **On the own-lyrics path none of the above applies**, because the question sits on the
    other side of the lyric there: it is the LAST answer, the words were typed five screens
    ago, and the only thing a language choice can still do to them is re-tag the language
    the composer sings them under. So that branch re-tags and moves to the summary, and the
    writer is not in the picture at all.
    """
    await callback.answer()
    draft = await read_draft(state)
    if draft is None:
        await expire(callback, state)
        return
    answered = draft.updated(output_language=callback_data.code)
    if answered.is_own_lyrics:
        _LOG.info("output language answered on the own-lyrics path; going to the summary")
        await show_confirm(callback, state, deps, retagged(answered))
        return
    if callback_data.code == draft.output_language and draft.lyrics is not None:
        _LOG.info("output language re-picked unchanged; keeping the lyric already in hand")
        await show_step(callback, state, draft, WizardStep.LYRICS)
        return
    await enter_lyrics_step(callback, state, deps, answered)


def build_router() -> Router:
    router = Router(name="questions")
    router.callback_query.register(
        handle_ui_language, Wizard.ui_language, LanguageCB.filter(F.slot == LanguageSlot.UI)
    )
    router.callback_query.register(handle_occasion, Wizard.occasion, OccasionCB.filter())
    router.callback_query.register(
        handle_own_lyrics, Wizard.occasion, NavCB.filter(F.action == NavAction.OWN_LYRICS)
    )
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
