"""``/start`` and ``/cancel``: the two ways in and out of the wizard.

Both are registered with no state filter at all, from the router directly under
``commands``, so they work from anywhere — including from inside onboarding, which is why
``handlers.onboarding`` writes no ``/cancel`` handler of its own. A ``/cancel`` typed between
the two onboarding questions is answered here with ``wizard.cancelled``, and the next update
is claimed by the onboarding catch-all, which re-enters at the step the profile row says.

``/start`` no longer opens a wizard. It answers "who is this?" and shows whichever of the two
onboarding screens is still unanswered, or the menu — see :func:`handle_start`. Opening a
wizard is 🎵's job, through ``common.reset_to_welcome``.

There is a THIRD way in now, and it is a deep link rather than a command: ``/start paid`` is
where the payment rail's browser tab sends a customer back to (``HBD_PAYME_RETURN_URL``). It
is a convenience and nothing rests on it — see :func:`handle_paid_return`.
"""

from __future__ import annotations

from typing import Final

from aiogram import F, Router
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import Message

from hbd.bot.deps import BotDeps
from hbd.bot.handlers.balance import show_balance
from hbd.bot.handlers.common import (
    clear_keeping_identity,
    finish_with,
    present,
    say,
    ui_language,
)
from hbd.bot.handlers.onboarding import load_identity
from hbd.bot.handlers.submitting import (
    STILL_IN_STUDIO_KEY,
    order_in_flight,
    say_still_working,
)
from hbd.bot.i18n import translate
from hbd.bot.middleware import resolve_language
from hbd.bot.screens import menu_screen, onboarding_contact_screen, onboarding_language_screen
from hbd.bot.states import Onboarding
from hbd.logging import get_logger

__all__ = ["build_router", "handle_paid_return", "PAID_DEEP_LINK"]

_LOG = get_logger(__name__)

#: Said when ``/cancel`` arrives after the order has already gone to the studio.
_TOO_LATE_KEY: Final[str] = "wizard.cancel_too_late"

#: The deep-link payload the checkout rail sends a paying customer back with, as the tail of
#: ``https://t.me/<bot>?start=paid``.
#:
#: A bare word rather than anything derived from the purchase — no ``public_ref``, no intent
#: id, no key. Two reasons, and the second is the one that decides it: a deep-link payload is
#: rendered in a browser address bar and pasteable by anyone, so putting our own reference in
#: it would hand a third party's page a token this bot then trusted; and nothing here NEEDS
#: one, because this handler reads the meter and never the payment (see
#: :func:`handle_paid_return`). Telegram's own limits also apply — the payload is 1..64
#: characters of ``A-Za-z0-9_-`` — and "paid" is inside every one of them.
PAID_DEEP_LINK: Final[str] = "paid"


async def handle_start(message: Message, state: FSMContext, deps: BotDeps) -> None:
    """Three ways in, and which one is taken is decided by what we already know.

    **A returning customer is never asked a question we already have the answer to.** This
    command used to re-ask the interface language on every single send, which made it the most
    repeated question in the product: a weekly customer answered "which language?" every week,
    forever, having answered it the week before. Now the language question is asked when
    nobody has chosen, the contact question when a language exists but no number does, and
    neither when the profile row says both are answered.

    **``/start`` inside ``Onboarding.contact`` is idempotent.** It re-renders the contact
    prompt; it does NOT re-ask the language and does NOT reset anything. That matters because
    ``/start`` is exactly what somebody types when the 📱 button has scrolled off their
    screen, and answering it by throwing away the language they just chose would be a loop
    they cannot escape.

    **``reset_to_welcome`` is no longer called from here.** Starting a wizard is 🎵's job now:
    a customer who has already told us their language and their number must reach the thing
    they came for without being walked through screens, and one who has not must not be walked
    into a purchase before onboarding. The last branch clears and shows the MENU.

    **``/start`` still does not refuse while an order is in flight**, matching
    ``navigation.handle_start_over`` — starting something new has never meant stopping the
    song being made, and the running order still lands in this chat. Exactly as before this
    change, the clear on the last branch un-parks ``ORDER_ID_KEY``, so a ``/cancel`` after a
    ``/start`` mid-render answers "cancelled" about a song that is still coming. That
    behaviour is unchanged and is not this handler's to fix; it is written down so nobody
    reads the new branch as having introduced it.
    """
    user = message.from_user
    _LOG.info("wizard started", extra={"user_id": user.id if user is not None else None})
    identity = await load_identity(state, deps, user.id if user is not None else None)
    # The identity's language when there is one, and the operator's configured default
    # otherwise: this is the one screen that must be drawn before anybody has chosen.
    language = identity.ui_language or deps.settings.default_ui_language
    if not identity.is_language_chosen:
        await state.set_state(Onboarding.language)
        await present(message, onboarding_language_screen(language))
        return
    if not identity.is_onboarded:
        await state.set_state(Onboarding.contact)
        await present(message, onboarding_contact_screen(language))
        return
    await clear_keeping_identity(state)
    await present(message, menu_screen(await ui_language(state, deps)))


async def handle_paid_return(message: Message, state: FSMContext, deps: BotDeps) -> None:
    """``/start paid`` — the customer is back from the payment page. Redraw the METER.

    **It says nothing about the payment, and that is the design rather than an omission.**
    This handler knows only that a browser tab closed; it does not know whether the money
    landed, and it cannot find out — settlement is inbound, it arrives at a different process
    minutes or hours later, and the only honest source for "did it work" is the credit meter
    itself. So the answer is the balance, drawn from the account, and the customer reads the
    number instead of a claim. A congratulation here would be a guess, and it would be wrong
    for every customer who opened the page and changed their mind.

    **Nothing depends on the customer coming back at all.** Settlement is driven by Payme's
    call to the gateway and the notification by ``runtime.payme_jobs.notify_payment_settled``,
    so this deep link is a convenience for the one who does return — which is also how the
    design sidesteps an unverified question it did not want to rest on: whether Payme's
    ``:transaction`` templating works in the GET ``c=`` callback form. ``HBD_PAYME_RETURN_URL``
    defaults to blank, so a deployment that never configures it loses nothing.

    ``show_balance`` rather than a screen of this module's own, for the reason
    ``handlers.balance`` gives about ``handlers.checkout``: a second renderer of one screen is
    free to disagree with the first about what the account holds. Reached with a ``Message``,
    so it SENDS — the customer has been away and the screen they left is scrolled off.

    It does NOT clear the session and does NOT touch the FSM state. ``/start`` proper does
    clear (``clear_keeping_identity``), and doing it here would throw away the draft of the
    customer who paid mid-wizard precisely so they could finish it — which is the single
    likeliest way to arrive at this handler.
    """
    _LOG.info("a customer came back from the payment page")
    await show_balance(message, state, deps)


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
    """A fresh router. Built per dispatcher, never shared — aiogram routers are single-use.

    **The deep link is registered FIRST and the order is load-bearing.** aiogram takes the
    first registration whose filters match, and a bare ``CommandStart()`` matches ``/start
    paid`` too — it does not care about the payload — so registering the plain command first
    would make the returning customer's deep link do nothing but redraw the menu, silently and
    in a way no type checker could see. The narrow filter therefore goes above the wide one,
    exactly as the two ``Wizard.confirm`` registrations sit above the wizard-less pair in
    ``handlers.checkout``.

    ``magic=F.args == PAID_DEEP_LINK`` and not ``deep_link=True`` alone: the second would
    claim EVERY payload, including any future one, and route a link this handler knows nothing
    about into the balance screen.
    """
    router = Router(name="start")
    router.message.register(
        handle_paid_return, CommandStart(deep_link=True, magic=F.args == PAID_DEEP_LINK)
    )
    router.message.register(handle_start, CommandStart())
    router.message.register(handle_cancel_command, Command("cancel"))
    return router
