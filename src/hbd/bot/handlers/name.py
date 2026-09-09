"""The name step. The one screen this whole product is built around.

Three things make it different from every other step:

* the name is **typed**. It is never transcribed from a voice message — a speech model's
  guess at a name is exactly the error we are here to eliminate — so a voice note at this
  step gets a polite "please type it";
* what comes back is echoed as the canonical **display** spelling (U+02BB intact) and must
  be confirmed before a single token is generated. The vendor-facing candidates are built
  at the same moment and are never shown;
* an unreadable name is a normal outcome, not an error page: the user is told what is wrong
  and stays on the step.
"""

from __future__ import annotations

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from hbd.bot.callbacks import NavAction, NavCB
from hbd.bot.deps import BotDeps
from hbd.bot.handlers.common import (
    COMMAND_PREFIX,
    error_text,
    expire,
    is_menu_label,
    read_draft,
    say,
    show_step,
)
from hbd.bot.i18n import translate
from hbd.bot.name_entry import resolve_typed_name
from hbd.bot.states import Wizard, WizardStep
from hbd.contracts import Err
from hbd.logging import get_logger

__all__ = ["build_router"]

_LOG = get_logger(__name__)


async def handle_name_typed(message: Message, state: FSMContext, deps: BotDeps) -> None:
    """The typed name. Commands and menu labels never reach the validator.

    This step had no guard at all until now, and it is the step that most needed one: the
    word stored here is the word the whole product exists to pronounce correctly. It is
    echoed for confirmation, transliterated into vendor-facing candidates, sung in the hook
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
        "name accepted, awaiting confirmation",
        extra={
            "lookup_key": recipient.lookup_key,
            "name_language": str(recipient.language),
            "candidate_count": len(recipient.candidates),
        },
    )
    await show_step(message, state, draft.updated(recipient=recipient), WizardStep.NAME_CONFIRM)


async def handle_name_not_typed(message: Message, state: FSMContext) -> None:
    """A voice note, a photo, a sticker. We need letters, so we ask for letters."""
    draft = await read_draft(state)
    if draft is None:
        await expire(message, state)
        return
    _LOG.info("non-text message at the name step", extra={"content_type": message.content_type})
    await say(message, translate("wizard.name.type_only", draft.ui_language))


async def handle_name_confirmed(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    draft = await read_draft(state)
    if draft is None:
        await expire(callback, state)
        return
    if draft.recipient is None:
        await show_step(callback, state, draft, WizardStep.NAME)
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
