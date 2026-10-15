"""The name step. The one screen this whole product is built around.

Three things make it different from every other step:

* the name is **typed**. It is never transcribed from a voice message — a speech model's
  guess at a name is exactly the error we are here to eliminate — so a voice note at this
  step gets a polite "please type it";
* what comes back is resolved into the canonical **display** spelling (U+02BB intact) and
  the ranked vendor-facing candidates in one go, and the wizard moves straight on. There
  used to be a confirmation screen echoing the display spelling; the owner removed it. It
  computed nothing — every candidate the pipeline reads is built by
  ``name_entry.resolve_typed_name`` at the moment the name is TYPED — so dropping the
  screen drops a tap, not a check. The spelling is still shown back: in the note prompt
  that follows ("Tell me about Gulnora!"), on the lyric preview and on the summary;
* an unreadable name is a normal outcome, not an error page: the user is told what is wrong
  and stays on the step.
"""

from __future__ import annotations

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from bayram.bot.callbacks import NavAction, NavCB
from bayram.bot.deps import BotDeps
from bayram.bot.handlers.common import (
    COMMAND_PREFIX,
    error_text,
    expire,
    is_menu_label,
    read_draft,
    say,
    show_step,
)
from bayram.bot.handlers.lyrics import enter_lyrics_step
from bayram.bot.i18n import translate
from bayram.bot.name_entry import resolve_typed_name
from bayram.bot.states import Wizard, WizardStep, next_step
from bayram.contracts import Err
from bayram.logging import get_logger

__all__ = ["build_router"]

_LOG = get_logger(__name__)


async def handle_name_typed(message: Message, state: FSMContext, deps: BotDeps) -> None:
    """The typed name. Commands and menu labels never reach the validator.

    This step had no guard at all until now, and it is the step that most needed one: the
    word stored here is the word the whole product exists to pronounce correctly. It is
    transliterated into vendor-facing candidates, sung in the hook
    and printed on the card. "🎵 Qoʻshiq yasash" going through as somebody's name is not a
    validation error with a nice message — it is a birthday song addressed to a button.

    Before this, ``/halp`` at the name step was handed straight to ``resolve_typed_name``
    and was rejected only by accident, by whatever that validator happened to say about a
    leading slash; a menu label, being ordinary letters, would have sailed through it. Both
    now get the same remedy the note and lyric steps use — log it, re-show the step, store
    nothing — rather than an error sentence about a message the customer never meant as an
    answer.

    As at the other two steps, the router order is the real defence (``commands`` and
    ``menu`` are both registered above the step routers) and this is the second brace,
    because that order is one line in ``handlers/__init__``.
    """
    draft = await read_draft(state)
    if draft is None:
        await expire(message, state)
        return
    typed = (message.text or "").strip()
    if typed.startswith(COMMAND_PREFIX) or is_menu_label(typed):
        _LOG.info("command- or menu-shaped text at the name step; not stored")
        await show_step(message, state, draft, WizardStep.NAME)
        return
    result = resolve_typed_name(
        message.text or "",
        ui_language=draft.ui_language,
        candidate_order=deps.settings.name_candidate_order,
    )
    if isinstance(result, Err):
        _LOG.info("typed name rejected", extra=result.error.to_log_dict())
        await say(message, error_text(result.error, draft.ui_language))
        return
    recipient = result.value
    _LOG.info(
        "name accepted",
        extra={
            "lookup_key": recipient.lookup_key,
            "name_language": str(recipient.language),
            "candidate_count": len(recipient.candidates),
        },
    )
    updated = draft.updated(recipient=recipient)
    if updated.output_language is not None:
        # Every other answer is already in hand — ✏️ Edit → Name on a finished song, or Back
        # all the way here from the preview — so the lyric is rewritten for the new name
        # rather than walking the customer through the note and the language again. This is
        # what ✅ on the old confirmation screen did, minus the screen.
        await enter_lyrics_step(message, state, deps, updated.updated(lyrics=None))
        return
    following = next_step(WizardStep.NAME) or WizardStep.OUTPUT_LANGUAGE
    await show_step(message, state, updated, following)


async def handle_name_not_typed(message: Message, state: FSMContext) -> None:
    """A voice note, a photo, a sticker. We need letters, so we ask for letters."""
    draft = await read_draft(state)
    if draft is None:
        await expire(message, state)
        return
    _LOG.info("non-text message at the name step", extra={"content_type": message.content_type})
    await say(message, translate("wizard.name.type_only", draft.ui_language))


async def handle_name_confirmed(
    callback: CallbackQuery, state: FSMContext, deps: BotDeps
) -> None:
    """✅ on a confirmation screen drawn by a release that still had one.

    No screen draws this button now. It stays registered for the customer parked in
    ``Wizard.name_confirm`` when this deployed (see ``states.PARKED_ONLY_STEPS``): on the
    old order the note had ALREADY been answered by then, so the way forward is the
    language question, exactly as before — not the note.
    """
    await callback.answer()
    draft = await read_draft(state)
    if draft is None:
        await expire(callback, state)
        return
    if draft.recipient is None:
        await show_step(callback, state, draft, WizardStep.NAME)
        return
    if draft.output_language is not None:
        await enter_lyrics_step(callback, state, deps, draft.updated(lyrics=None))
        return
    await show_step(callback, state, draft, WizardStep.OUTPUT_LANGUAGE)


def build_router() -> Router:
    router = Router(name="name")
    router.message.register(handle_name_typed, Wizard.name, F.text)
    router.message.register(handle_name_not_typed, Wizard.name)
    router.callback_query.register(
        handle_name_confirmed, Wizard.name_confirm, NavCB.filter(F.action == NavAction.NAME_OK)
    )
    return router
