"""Router assembly. Order matters, so it is stated once, here.

``membership`` is the one router in this tree whose position is NOT load-bearing, and it is
listed first to say so out loud. Everything below this paragraph is an argument about two
observers — ``message`` and ``callback_query`` — and ``membership`` registers on neither: it
claims ``my_chat_member``, a third observer no other router touches, so it can neither
swallow an update from the ladder below nor be swallowed by it. It goes FIRST rather than
last because sitting beside ``fallback`` would imply it is a catch-all, and it is the exact
opposite — the narrowest registration in the tree, one handler behind a private-chat filter,
answering nobody and writing one fact. See ``hbd.bot.handlers.membership`` for why that
observer deliberately has neither the inbound gate nor the error guard.

``commands`` first (``/help``, ``/privacy``, ``/support`` and ``/forget`` have to work from
any state, and the note step accepts any text, so a command reaching it would be sung), then
``start`` (a ``/start`` must work from anywhere, including mid-wizard), then ``onboarding``,
then ``menu``, then the navigation buttons, then the step handlers, then ``submitting``, and
``fallback`` last — it matches everything, so anything registered after it would be dead code.

``onboarding`` is THIRD, and every neighbour is a decision. Above ``commands`` its catch-all
would swallow ``/privacy`` and ``/forget``, re-creating at the router layer exactly the denial
``gate.ERASURE_COMMANDS`` exists to prevent — the customer who has not finished answering the
questions is the one who most needs to be able to ask what we keep. Above ``start`` it would
make ``/start`` unreachable, and ``/start`` is what a stuck person types. Below ``navigation``
a stale Back tapped mid-onboarding would reach ``handle_back``, whose ``step_for_state``
answers ``None`` for an ``Onboarding.*`` state name and calls ``expire`` — "your session
expired", said to somebody two screens into their first conversation with the bot. And below
the step routers it would stop being what blocks the wizard, which is its whole job.

``menu`` is FOURTH, immediately under it. The main menu is a REPLY keyboard: its labels arrive
as ordinary text messages, and the note step and the lyric step both accept any text, so a
🎵 pressed at either would be stored as the customer's answer and sung to a real person unless
the menu router sees it first. It sits below ``onboarding`` because a keyboard pinned by an
earlier session must not let a customer who has since been forgotten start a wizard.

**Both new routers stand down for ``Wizard.submitting`` at the ROUTER level**, with one
``~StateFilter(Wizard.submitting)`` on each of their two observers rather than a guard inside
each handler. That is what keeps ``submitting``'s claim on that state complete even though it
is registered four routers below them: it claims every message and every button while a song
is being made, and ``commands.handle_forget`` re-parks a running order there deliberately. A
catch-all or a menu label that swallowed the park would blind ``order_in_flight``, after which
the next ``/cancel`` answers "Cancelled — nothing was made, and nothing was kept" about a song
that then arrives in the chat. Moving ``submitting`` above them instead was rejected: it would
put it above ``navigation``, which owns Cancel, and change who answers that button.

``checkout`` sits between ``confirm`` and ``submitting``, and BOTH neighbours are now a
constraint. That paragraph used to say only the second one was, on the grounds that "both of
its registrations are state-filtered to ``Wizard.confirm``, so it could sit anywhere below
``navigation``" — and that stopped being true the moment the ``/balance`` purchase buttons
were made to work. ``checkout.build_router`` makes FOUR registrations now, and two of them
are filtered only by ``~StateFilter(Wizard.submitting)``: they match in almost every state,
including no state at all, which is the whole point of a button that has to work on a
``/balance`` answer sent mid-wizard.

So its position below ``onboarding`` and ``menu`` is load-bearing rather than free. A stale
💳 pressed by an account that has not finished onboarding must be claimed by onboarding's
catch-all and answered with the phone-number screen, not charged; moving ``checkout`` above
``onboarding`` would sell to an account that has no row yet. It MUST also sit above
``submitting``, which claims every message and every callback in ``Wizard.submitting``. That
matters here more than anywhere else in this file: the WIZARD half of ``handlers.checkout``
parks the FSM in ``Wizard.submitting`` as its first await, precisely so that a second tap on
a price button falls to ``submitting`` and is answered "still being made" instead of charging
the customer twice. Put it below ``submitting`` and the FIRST tap would be answered that way
too, and nothing would ever be sold. The ``/balance`` half parks nothing — it must not, since
it answers mid-wizard without disturbing the draft — which is exactly why its two
registrations carry the ``~StateFilter(Wizard.submitting)`` that keeps them from claiming the
tap the wizard half is shedding.

``submitting`` sits second to last for the same reason ``fallback`` is last: it claims every
message and every button in one state, so a step router placed after it would never see an
update. Ahead of ``fallback`` because that is the whole point of it — while a song is being
made, "nobody claimed this" must not be answered with "your session expired".
"""

from __future__ import annotations

from aiogram import Router

from hbd.bot.handlers import (
    checkout,
    commands,
    confirm,
    fallback,
    lyrics,
    membership,
    menu,
    name,
    navigation,
    onboarding,
    questions,
    start,
    submitting,
)

__all__ = ["build_router"]


def build_router() -> Router:
    """A fresh, fully wired router tree. Called once by the composition root."""
    router = Router(name="hbd")
    router.include_routers(
        membership.build_router(),
        commands.build_router(),
        start.build_router(),
        onboarding.build_router(),
        menu.build_router(),
        navigation.build_router(),
        questions.build_router(),
        name.build_router(),
        lyrics.build_router(),
        confirm.build_router(),
        checkout.build_router(),
        submitting.build_router(),
        fallback.build_router(),
    )
    return router
