"""``/start`` and ``/cancel``: the two ways in and out of the wizard."""

from __future__ import annotations

from typing import Final

from aiogram import Router
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import Message

from hbd.bot.deps import BotDeps
from hbd.bot.handlers.common import finish_with, reset_to_welcome, say
from hbd.bot.handlers.submitting import (
    STILL_IN_STUDIO_KEY,
    order_in_flight,
    say_still_working,
)
from hbd.bot.i18n import translate
from hbd.bot.middleware import resolve_language
from hbd.logging import get_logger

__all__ = ["build_router"]

_LOG = get_logger(__name__)

#: Said when ``/cancel`` arrives after the order has already gone to the studio.
_TOO_LATE_KEY: Final[str] = "wizard.cancel_too_late"


async def handle_start(message: Message, state: FSMContext, deps: BotDeps) -> None:
    """Always a clean slate: a half-finished draft from last week helps nobody.

    The reset itself lives in ``common`` because three entry points perform it — this
    command, the Start-over button and a first message from someone with no session — and
    three copies of "clear, build a draft, show the first screen" is three places for them
    to drift apart.
    """
    _LOG.info(
        "wizard started",
        extra={"user_id": message.from_user.id if message.from_user else None},
    )
    await reset_to_welcome(message, state, deps)


async def handle_cancel_command(message: Message, state: FSMContext) -> None:
    """Stop the wizard — unless there is nothing left to stop.

    The same guard ``navigation.handle_cancel`` applies to the Cancel BUTTON, for the same
    reason: once the order is with the studio, clearing the session and answering
    "Cancelled" is a lie about a song that is still being made and will still be delivered.
    Dequeuing a running job is out of scope for this build; saying something untrue is not.
    ``order_in_flight`` rather than the state name, because a lyric write parks in the same
    state and cancelling one of those really does cancel.
    """
    order_id = await order_in_flight(state)
    if order_id is not None:
        _LOG.info("/cancel refused; the order is already being made", extra={"order_id": order_id})
        if not await say_still_working(message, state, _TOO_LATE_KEY):
            # No draft left to name the song with — say it without the name. NOT the expiry
            # screen: that clears the FSM, which would un-park the order this refusal just
            # declined to cancel and leave the next /cancel free to claim nothing was made.
            await say(message, translate(STILL_IN_STUDIO_KEY, await resolve_language(state)))
        return
    await finish_with(message, state, "wizard.cancelled")


def build_router() -> Router:
    """A fresh router. Built per dispatcher, never shared — aiogram routers are single-use."""
    router = Router(name="start")
    router.message.register(handle_start, CommandStart())
    router.message.register(handle_cancel_command, Command("cancel"))
    return router
