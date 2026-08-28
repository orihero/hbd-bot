"""``/start`` and ``/cancel``: the two ways in and out of the wizard."""

from __future__ import annotations

from aiogram import Router
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import Message

from hbd.bot.deps import BotDeps
from hbd.bot.draft import WizardDraft
from hbd.bot.handlers.common import finish_with, show_step
from hbd.bot.states import WizardStep
from hbd.logging import get_logger

__all__ = ["build_router"]

_LOG = get_logger(__name__)



async def handle_start(message: Message, state: FSMContext, deps: BotDeps) -> None:
    """Always a clean slate: a half-finished draft from last week helps nobody."""
    await state.clear()
    draft = WizardDraft(ui_language=deps.settings.default_ui_language)
    _LOG.info(
        "wizard started",
        extra={"user_id": message.from_user.id if message.from_user else None},
    )
    await show_step(message, state, draft, WizardStep.UI_LANGUAGE)


async def handle_cancel_command(message: Message, state: FSMContext) -> None:
    await finish_with(message, state, "wizard.cancelled")


def build_router() -> Router:
    """A fresh router. Built per dispatcher, never shared — aiogram routers are single-use."""
    router = Router(name="start")
    router.message.register(handle_start, CommandStart())
    router.message.register(handle_cancel_command, Command("cancel"))
    return router
