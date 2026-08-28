"""Helpers every handler uses: read the draft, write the draft, put a screen up.

Navigation lives here rather than in each handler, so "go to step X" is one code path.
That is what makes Back work at every step: Back is not a special case, it is
``show_step(event, state, draft, previous_step(current))``.
"""

from __future__ import annotations

from aiogram.exceptions import TelegramBadRequest
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from hbd.bot.draft import WizardDraft, load_draft
from hbd.bot.i18n import FALLBACK_LANGUAGE, translate
from hbd.bot.screens import Screen, render_step, resolve_step
from hbd.bot.states import WizardStep, state_for
from hbd.contracts import Err, Language
from hbd.errors import HbdError
from hbd.logging import get_logger

__all__ = [
    "Event",
    "read_draft",
    "write_draft",
    "show_step",
    "present",
    "say",
    "finish_with",
    "expire",
    "error_text",
]

_LOG = get_logger(__name__)

#: The two update kinds this wizard accepts. Everything else the fallback handles.
type Event = Message | CallbackQuery


async def read_draft(state: FSMContext) -> WizardDraft | None:
    """The current draft, or ``None`` when the session is gone or unreadable."""
    data = await state.get_data()
    result = load_draft(data)
    if isinstance(result, Err):
        _LOG.info("wizard draft unavailable", extra=result.error.to_log_dict())
        return None
    return result.value


async def write_draft(state: FSMContext, draft: WizardDraft) -> None:
    await state.update_data(**draft.to_state_data())


async def show_step(
    event: Event,
    state: FSMContext,
    draft: WizardDraft,
    step: WizardStep,
) -> WizardStep:
    """Persist the draft, move the FSM to ``step`` and put its screen up.

    Returns the step actually shown, which can differ from ``step`` when the draft is not
    complete enough to render it.

    ``resolve_step`` downgrades by one rule at a time, and one downgrade is not always
    enough: a summary whose lyric was never approved resolves to the preview, and a preview
    with no lyric in it resolves further to the language question. Stopping after the first
    rule would set the FSM to ``Wizard.lyrics`` and then render the language picker, whose
    buttons are filtered to ``Wizard.output_language`` — a screen whose every button is
    dead. So the downgrade runs to a fixpoint. It terminates because every rule moves
    strictly earlier in ``WIZARD_ORDER``.
    """
    shown = resolve_step(step, draft)
    while (further := resolve_step(shown, draft)) is not shown:
        shown = further
    await write_draft(state, draft)
    await state.set_state(state_for(shown))
    await present(event, render_step(shown, draft))
    return shown


async def present(event: Event, screen: Screen) -> None:
    """Edit in place when we came from a button; send a new message otherwise."""
    if isinstance(event, CallbackQuery):
        await _edit_or_send(event, screen)
        return
    await event.answer(screen.text, reply_markup=screen.markup)


async def say(event: Event, text: str) -> None:
    """Send one plain sentence without disturbing the screen the user is on."""
    if isinstance(event, CallbackQuery):
        if isinstance(event.message, Message):
            await event.message.answer(text)
        return
    await event.answer(text)


async def _edit_or_send(callback: CallbackQuery, screen: Screen) -> None:
    message = callback.message
    if not isinstance(message, Message):
        return
    try:
        await message.edit_text(screen.text, reply_markup=screen.markup)
    except TelegramBadRequest as exc:
        # Unchanged text, or a message too old to edit. Neither is worth failing over.
        _LOG.info("could not edit in place, sending a new message", extra={"failure": repr(exc)})
        await message.answer(screen.text, reply_markup=screen.markup)


async def finish_with(event: Event, state: FSMContext, key: str) -> None:
    """Clear the session and say one localised sentence. Used by cancel and by expiry."""
    draft = await read_draft(state)
    language = draft.ui_language if draft is not None else FALLBACK_LANGUAGE
    await state.clear()
    await present(event, Screen(text=translate(key, language)))


async def expire(event: Event, state: FSMContext) -> None:
    """The draft is gone. Say so plainly and let the user restart."""
    await finish_with(event, state, "wizard.expired")


def error_text(error: HbdError, language: Language) -> str:
    """Render an error the way the customer should read it.

    Scalar values from the error's context are passed through as template parameters, so a
    message like "keep it under {limit} characters" gets its number from the error that
    knew it, and a template that does not use them is unaffected.
    """
    params = {
        name: value
        for name, value in error.context.items()
        if isinstance(value, str | int | float | bool)
    }
    return translate(error.user_message_key, language, **params)
