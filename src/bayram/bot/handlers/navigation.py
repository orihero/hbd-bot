"""Back and Cancel — the buttons that decide whether the wizard feels safe to use.

Back is derived from the draft's step order and nothing else. There is no per-step back
handler to forget to write, and no step can end up with a Back button that goes somewhere
wrong: it goes to the step before it, with every answer already given still in the draft.

*Which* order is the draft's own answer — there are two, and they fork at the occasion step
— so the lookup is asked ``is_own_lyrics`` rather than assuming the writer's. See
``bayram.bot.states``.

None of these three are state-filtered, and that is deliberate: Telegram leaves every
screen the wizard has ever drawn sitting on the user's message roll, and a Back button that
only worked on the newest one would be a button that mostly does nothing. The cost of that
choice is :func:`_refuse_while_running`. Once an order is actually being made, a Cancel
tapped on an old screen used to clear the session and answer "Cancelled" while the song it
claimed to have stopped ran to completion and was delivered. Dequeuing a running job is out
of scope for this build; telling the customer something untrue is not.

The last two handlers are not navigation in the wizard sense at all — they are the way OUT
of a screen that ends a flow. Start over and Make another both perform the same clean-slate
reset that 🎵 Make a song on the persistent menu performs, through the same helper
(``common.reset_to_welcome``), so the three cannot drift apart.

It used to be ``/start`` named in that sentence, and it is worth saying why it no longer is:
``/start`` shows the MENU now. A returning customer who has already told us their language
and their number must not be asked either question again to reach the thing they came for,
so the command that used to begin a wizard begins nothing — 🎵 does. The helper, its
signature and its semantics are unchanged; only which three doors open onto it.
"""

from __future__ import annotations

from typing import Final

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery

from bayram.bot.callbacks import NavAction, NavCB
from bayram.bot.deps import BotDeps
from bayram.bot.handlers.common import (
    Event,
    expire,
    finish_with,
    read_draft,
    reset_to_welcome,
    say,
    show_step,
)
from bayram.bot.handlers.submitting import (
    STILL_IN_STUDIO_KEY,
    order_in_flight,
    say_still_working,
)
from bayram.bot.handlers.support import open_ticket
from bayram.bot.i18n import translate
from bayram.bot.middleware import resolve_language
from bayram.bot.states import WizardStep, previous_step, step_for_state
from bayram.contracts import SupportTicketSource
from bayram.logging import get_logger

__all__ = ["build_router"]

_LOG = get_logger(__name__)

#: Said when an order is already being made and the button asked us to undo it.
_TOO_LATE_KEY: Final[str] = "wizard.cancel_too_late"


async def _refuse_while_running(event: Event, state: FSMContext) -> bool:
    """``True`` when an order is in flight — in which case the user has just been told so.

    Asked by every button that would otherwise throw the session away. It consults
    ``order_in_flight`` rather than the state name because ``Wizard.submitting`` is also
    where a lyric write parks, and Cancel during a lyric write still means what it says:
    nothing has been ordered yet.

    The no-name fallback says the same thing without the name rather than expiring. The
    expiry it used to run cleared the FSM — un-parking the very order this guard had just
    refused to cancel — so the NEXT press of Cancel found no session, answered "Cancelled —
    nothing was made, and nothing was kept", and the song arrived anyway. A guard that
    dismantles itself on its own fallback path is not a guard.
    """
    order_id = await order_in_flight(state)
    if order_id is None:
        return False
    _LOG.info("navigation refused; the order is already being made", extra={"order_id": order_id})
    if not await say_still_working(event, state, _TOO_LATE_KEY):
        await say(event, translate(STILL_IN_STUDIO_KEY, await resolve_language(state)))
    return True


async def handle_cancel(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    if await _refuse_while_running(callback, state):
        return
    await finish_with(callback, state, "wizard.cancelled")


async def handle_back(callback: CallbackQuery, state: FSMContext) -> None:
    """Re-render the previous step. At the first step, re-render that step."""
    await callback.answer()
    if await _refuse_while_running(callback, state):
        return
    draft = await read_draft(state)
    if draft is None:
        await expire(callback, state)
        return
    current = step_for_state(await state.get_state())
    if current is None:
        await expire(callback, state)
        return
    # The draft decides which ORDER Back walks. The two diverge from the occasion step
    # onwards, so a Back that always consulted ``WIZARD_ORDER`` would send an own-lyrics
    # customer from the words to the voice question — a step they have not reached — and
    # from the genre to a NOTE screen their path does not contain.
    target = previous_step(current, is_own_lyrics=draft.is_own_lyrics) or current
    _LOG.info(
        "wizard back",
        extra={
            "from_step": current.value,
            "to_step": target.value,
            "is_own_lyrics": draft.is_own_lyrics,
        },
    )
    await show_step(callback, state, draft, target)


async def handle_retype(callback: CallbackQuery, state: FSMContext) -> None:
    """Drop the resolved name and ask for it again. Nothing else in the draft is touched."""
    await callback.answer()
    if await _refuse_while_running(callback, state):
        return
    draft = await read_draft(state)
    if draft is None:
        await expire(callback, state)
        return
    await show_step(callback, state, draft.updated(recipient=None), WizardStep.NAME)


async def handle_start_over(callback: CallbackQuery, state: FSMContext, deps: BotDeps) -> None:
    """The exit from every screen that ends a flow: cancelled, expired, delivered.

    It does not refuse while an order is in flight, and matches ``/start`` in that. Starting
    a new song has never meant stopping the one being made — the running order still lands
    in this chat when it is done — and the customer who taps this is asking for a wizard,
    not for a cancellation.
    """
    await callback.answer()
    _LOG.info("wizard restarted from a button", extra={"action": callback.data})
    await reset_to_welcome(callback, state, deps)


async def handle_report_problem(callback: CallbackQuery, state: FSMContext, deps: BotDeps) -> None:
    """The ORDER-LESS ⚠️ door. Opens a support ticket, the same one every other door opens.

    **This member and this registration both stay, and that is worth stating because the ⚠️
    button on a delivered song no longer packs a ``NavCB`` at all** — it packs a
    :class:`~bayram.bot.callbacks.SupportCB` carrying the order id, and
    ``handlers.support.handle_open`` answers it. What still arrives here is every ⚠️ that was
    drawn without an order to name: the degraded screens, and every closing message Telegram
    is still holding from before this release. Removing the member would have made those
    buttons match no filter, which is the stale-callback path — "that screen has moved on" —
    shown to somebody whose song came out wrong. That is precisely how ``TRY_AGAIN`` once
    shipped, and ``test_every_nav_action_is_registered_to_a_handler`` exists because of it.

    **It opens a real ticket rather than rendering a sentence.** The behaviour it replaces —
    ``common.support_text``, an address or an invitation to describe it in the chat — is now
    the FALLBACK inside :func:`~bayram.bot.handlers.support.open_ticket`, taken only when no
    ticket store is wired. So the button and ``/support`` still cannot describe two different
    routes to one inbox, which is the rule ``support_text`` was extracted to keep; the route
    they share is simply a table now instead of a paragraph.

    The ticket carries no ``order_id``, because this door genuinely does not know one. That
    is a real distinction the row records rather than smooths over: a complaint filed against
    a named song and one filed from a screen that never had a song are different work items,
    and ``source`` plus a null ``order_id`` is how an operator tells them apart.
    """
    await callback.answer()
    # Said as a NEW message rather than edited over the screen it was tapped from: that
    # screen is the closing message, and it carries both the order number and the button
    # for the next song.
    await open_ticket(
        callback, state, deps, source=SupportTicketSource.DELIVERY_BUTTON, order_id=None
    )


def build_router() -> Router:
    router = Router(name="navigation")
    router.callback_query.register(handle_cancel, NavCB.filter(F.action == NavAction.CANCEL))
    router.callback_query.register(handle_back, NavCB.filter(F.action == NavAction.BACK))
    router.callback_query.register(handle_retype, NavCB.filter(F.action == NavAction.RETYPE))
    router.callback_query.register(
        handle_start_over,
        NavCB.filter(F.action.in_({NavAction.START_OVER, NavAction.MAKE_ANOTHER})),
    )
    router.callback_query.register(
        handle_report_problem, NavCB.filter(F.action == NavAction.REPORT_PROBLEM)
    )
    return router
