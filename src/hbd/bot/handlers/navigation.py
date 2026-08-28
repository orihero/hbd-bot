"""Back and Cancel — the buttons that decide whether the wizard feels safe to use.

Back is derived from ``WIZARD_ORDER`` and nothing else. There is no per-step back handler
to forget to write, and no step can end up with a Back button that goes somewhere wrong: it
goes to the step before it, with every answer already given still in the draft.
"""

from __future__ import annotations

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery

from hbd.bot.callbacks import NavAction, NavCB
from hbd.bot.handlers.common import expire, finish_with, read_draft, show_step
from hbd.bot.states import WizardStep, previous_step, step_for_state
from hbd.logging import get_logger

__all__ = ["build_router"]

_LOG = get_logger(__name__)



async def handle_cancel(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    await finish_with(callback, state, "wizard.cancelled")


async def handle_back(callback: CallbackQuery, state: FSMContext) -> None:
    """Re-render the previous step. At the first step, re-render that step."""
    await callback.answer()
    draft = await read_draft(state)
    if draft is None:
        await expire(callback, state)
        return
    current = step_for_state(await state.get_state())
    if current is None:
        await expire(callback, state)
        return
    target = previous_step(current) or current
    _LOG.info("wizard back", extra={"from_step": current.value, "to_step": target.value})
    await show_step(callback, state, draft, target)


async def handle_retype(callback: CallbackQuery, state: FSMContext) -> None:
    """Drop the resolved name and ask for it again. Nothing else in the draft is touched."""
    await callback.answer()
    draft = await read_draft(state)
    if draft is None:
        await expire(callback, state)
        return
    await show_step(callback, state, draft.updated(recipient=None), WizardStep.NAME)


def build_router() -> Router:
    router = Router(name="navigation")
    router.callback_query.register(handle_cancel, NavCB.filter(F.action == NavAction.CANCEL))
    router.callback_query.register(handle_back, NavCB.filter(F.action == NavAction.BACK))
    router.callback_query.register(handle_retype, NavCB.filter(F.action == NavAction.RETYPE))
    return router
