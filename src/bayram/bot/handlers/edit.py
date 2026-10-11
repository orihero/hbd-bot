"""Editing a delivered song.

Offers 5 options to edit a finished track:
1. Lyrics (shows copyable lyrics and enters Wizard.lyrics for customer to paste/edit)
2. Music (changes melody/genre style and returns to Confirm)
3. Name (changes recipient name, prompts confirmation, regenerates lyrics with the new name)
4. Voice (changes vocal gender and returns to Confirm)
5. Regenerate all (rerolls lyrics with fresh composition and returns to lyrics preview)
"""

from __future__ import annotations

from uuid import uuid4

from aiogram import F, Router
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery

from bayram.bot.callbacks import EditAction, EditSongCB, read_reference
from bayram.bot.deps import BotDeps
from bayram.bot.draft import LyricSource, WizardDraft
from bayram.bot.handlers.common import (
    expire,
    present,
    read_draft,
    show_step,
    write_draft,
)
from bayram.bot.handlers.lyrics import enter_lyrics_step
from bayram.bot.i18n import translate
from bayram.bot.keyboards import copy_lyrics_keyboard, edit_options_keyboard
from bayram.bot.middleware import resolve_language
from bayram.bot.screens import Screen, menu_screen
from bayram.bot.states import Wizard, WizardStep
from bayram.contracts import is_ok
from bayram.logging import get_logger

__all__ = ["build_router"]

_LOG = get_logger(__name__)


async def handle_edit_menu(
    callback: CallbackQuery, callback_data: EditSongCB, state: FSMContext, deps: BotDeps
) -> None:
    """The ✏️ button on a finished song: show edit options."""
    await callback.answer()
    language = await resolve_language(state)
    order_id = read_reference(callback_data.ref)

    if order_id is not None and deps.order_reader is not None:
        result = await deps.order_reader.get_order(order_id)
        if is_ok(result):
            order = result.value
            draft = WizardDraft(
                session_id=uuid4().hex,
                ui_language=language,
                occasion=order.brief.occasion,
                genre=order.brief.genre,
                vocal_gender=order.brief.vocal_gender,
                note=order.brief.note,
                recipient=order.brief.recipient,
                output_language=order.brief.output_language,
                lyrics=order.brief.approved_lyrics,
                lyrics_source=(
                    LyricSource.OWN
                    if (order.brief.recipient is None and order.brief.approved_lyrics is not None)
                    else LyricSource.WRITER
                ),
            )
            await write_draft(state, draft)
        else:
            draft = await read_draft(state)
            if draft is None:
                draft = WizardDraft(session_id=uuid4().hex, ui_language=language)
                await write_draft(state, draft)
    else:
        draft = await read_draft(state)
        if draft is None:
            draft = WizardDraft(session_id=uuid4().hex, ui_language=language)
            await write_draft(state, draft)

    await present(
        callback,
        Screen(
            translate("edit.prompt", language),
            edit_options_keyboard(language, order_id=order_id),
        ),
    )


async def handle_edit_lyrics(
    callback: CallbackQuery, callback_data: EditSongCB, state: FSMContext, deps: BotDeps
) -> None:
    """Lyrics edit chosen: display lyrics in a copyable format and await input."""
    await callback.answer()
    draft = await read_draft(state)
    if draft is None:
        await expire(callback, state)
        return

    language = await resolve_language(state)
    lyric_text = draft.lyrics.as_plain_text() if draft.lyrics is not None else ""
    await state.set_state(Wizard.lyrics)
    await present(
        callback,
        Screen(
            translate("edit.lyrics.prompt", language, lyrics=lyric_text),
            copy_lyrics_keyboard(language, lyric_text=lyric_text),
        ),
    )


async def handle_edit_music(
    callback: CallbackQuery, callback_data: EditSongCB, state: FSMContext, deps: BotDeps
) -> None:
    """Music edit chosen: show genre options."""
    await callback.answer()
    draft = await read_draft(state)
    if draft is None:
        await expire(callback, state)
        return
    await show_step(callback, state, draft, WizardStep.GENRE)


async def handle_edit_voice(
    callback: CallbackQuery, callback_data: EditSongCB, state: FSMContext, deps: BotDeps
) -> None:
    """Voice edit chosen: show vocal gender options."""
    await callback.answer()
    draft = await read_draft(state)
    if draft is None:
        await expire(callback, state)
        return
    await show_step(callback, state, draft, WizardStep.VOCAL_GENDER)


async def handle_edit_name(
    callback: CallbackQuery, callback_data: EditSongCB, state: FSMContext, deps: BotDeps
) -> None:
    """Name edit chosen: prompt for the new recipient name."""
    await callback.answer()
    draft = await read_draft(state)
    if draft is None:
        await expire(callback, state)
        return
    await show_step(callback, state, draft, WizardStep.NAME)


async def handle_edit_regenerate(
    callback: CallbackQuery, callback_data: EditSongCB, state: FSMContext, deps: BotDeps
) -> None:
    """Regenerate all: wipe lyrics and generate fresh lyrics for the brief."""
    await callback.answer()
    draft = await read_draft(state)
    if draft is None:
        await expire(callback, state)
        return
    await enter_lyrics_step(callback, state, deps, draft.updated(lyrics=None))


async def handle_edit_cancel(
    callback: CallbackQuery, callback_data: EditSongCB, state: FSMContext, deps: BotDeps
) -> None:
    """Cancel editing and return to main menu."""
    await callback.answer()
    language = await resolve_language(state)
    await present(callback, menu_screen(language))


def build_router() -> Router:
    """Router handling finished song edit choices."""
    router = Router(name="edit")
    router.callback_query.filter(~StateFilter(Wizard.submitting))
    router.callback_query.register(handle_edit_menu, EditSongCB.filter(F.action == EditAction.MENU))
    router.callback_query.register(
        handle_edit_lyrics, EditSongCB.filter(F.action == EditAction.LYRICS)
    )
    router.callback_query.register(
        handle_edit_music, EditSongCB.filter(F.action == EditAction.MUSIC)
    )
    router.callback_query.register(
        handle_edit_voice, EditSongCB.filter(F.action == EditAction.VOICE)
    )
    router.callback_query.register(
        handle_edit_name, EditSongCB.filter(F.action == EditAction.NAME)
    )
    router.callback_query.register(
        handle_edit_regenerate, EditSongCB.filter(F.action == EditAction.REGENERATE)
    )
    router.callback_query.register(
        handle_edit_cancel, EditSongCB.filter(F.action == EditAction.CANCEL)
    )
    return router
