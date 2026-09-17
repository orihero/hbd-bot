"""Router assembly. Order matters, so it is stated once, here.

``membership`` is the one router in this tree whose position is NOT load-bearing, and it is
listed first to say so out loud. Everything below this paragraph is an argument about two
observers — ``message`` and ``callback_query`` — and ``membership`` registers on neither: it
claims ``my_chat_member``, a third observer no other router touches, so it can neither
swallow an update from the ladder below nor be swallowed by it. It goes FIRST rather than
last because sitting beside ``fallback`` would imply it is a catch-all, and it is the exact
opposite — the narrowest registration in the tree, one handler behind a private-chat filter,
answering nobody and writing one fact. See ``bayram.bot.handlers.membership`` for why that
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

**``onboarding`` and ``menu`` stand down for ``Wizard.submitting`` at the ROUTER level**, with
one ``~StateFilter(Wizard.submitting)`` on each of their two observers rather than a guard
inside each handler. That is what keeps ``submitting``'s claim on that state complete even
though it is registered four routers below them: it claims every message and every button
while a song is being made, and ``commands.handle_forget`` re-parks a running order there
deliberately. A catch-all or a menu label that swallowed the park would blind
``order_in_flight``, after which the next ``/cancel`` answers "Cancelled — nothing was made,
and nothing was kept" about a song that then arrives in the chat. Moving ``submitting`` above
them instead was rejected: it would put it above ``navigation``, which owns Cancel, and change
who answers that button.

**The stand-down belongs to CATCH-ALLS, and is not a tax every router above ``submitting``
pays.** ``onboarding`` claims every update from an un-onboarded account and ``menu`` claims
any text equal to a reply-keyboard label; both can swallow the park, so both stand down.
``support``'s message observer can not: its one registration is filtered by
"a ticket of this account's is listening on the message this is a reply to", which no wizard
input can satisfy. It carried the filter anyway when it shipped, and the cost was a customer
who typed ``/support`` mid-render getting a prompt whose answer ``submitting`` then ate. See
``handlers.support.build_router``, which argues the exception where the exception is made.

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

**The two support routers are the first pair in this tree that sit in two different places,
and both positions are arguments.**

``support_group`` is THIRD, above ``onboarding`` and below ``commands``/``start``. Above
``onboarding`` because that router's catch-all claims every update from an account with no
``user_profiles`` row — which is every staffer in the support group, since a triager has never
ordered a song from this bot. Below it, a reply to a ticket card would be answered with the
phone-number screen, in the staff room, in a language nobody there chose. Below ``commands``
and ``start`` **for a reason that has changed rather than gone**: those two are private-only
now, so in the staff room they no longer claim anything and this router's position relative to
them costs nothing either way. It is kept where it is because the ordering above them is what
``tests/test_bot/test_app.py`` pins, and because the day either of them grows a registration
that must work in a group, a router that claims EVERY update from the support chat must not
already be sitting above it. What replaced the old reason is in ``handlers.support``: a command
typed in the support group is claimed by ``handle_unresolved_group_message`` and answered with
"I answer commands in a private chat only", so a staffer's data-subject request is redirected
into a DM rather than swallowed here or disclosed to the room.

It claims EVERYTHING from that one chat id — every message and every button — and the change
from "only a reply to a card we posted" is a fix rather than a widening for its own sake. An
update it declined fell through to the customer routers below, where ``onboarding``'s catch-all
answered a staffer with the language screen and a phone-number keyboard, in the staff room,
while the customer heard nothing. Placing it high still costs the routers below it nothing,
because the only thing it takes from them is a chat none of them may act in.

``support`` (the customer half) is SIXTH, immediately under ``menu`` and above ``navigation``.
Under ``menu`` for the reason ``menu`` is under ``onboarding``: a label on the persistent reply
keyboard has to beat everything that accepts free text. Above the step routers for the same
reason seen from the other end — the note step and the lyric step accept ANY text, so the
customer's reply to a support prompt reaching one of them would be stored as their answer and
SUNG TO A REAL PERSON, which is the ``/help``-at-the-note-step failure in a new shape. Its
position relative to ``navigation`` is genuinely free (that router registers on
``callback_query`` only, filtered on ``NavCB``, which cannot collide with ``SupportCB``), and
it is placed above so the message registrations stay together.

Only the customer router's CALLBACK observer stands down for ``Wizard.submitting``; its
message observer deliberately does not, for the reason argued four paragraphs up and in
``handlers.support.build_router``. The group router stands down on neither, and
``handlers.support.build_group_router`` says why: FSM state is keyed by chat, so a staffer in
the group is never in that state and the filter would guard nothing.

**EVERY CUSTOMER-FACING ROUTER IS NESTED UNDER A PRIVATE-CHAT FILTER, and that nesting is the
structural half of a fix rather than a tidy-up.** The support group's catch-alls
(``handlers.support.build_group_router``) stop updates from THE CONFIGURED ROOM reaching
these routers. This stops them reaching these routers from ANY room — a group somebody added
the bot to, a channel it was made an admin of, a supergroup that used to be the support group
before the chat id was changed. Without it, one group message reaching ``onboarding``'s
catch-all is the bot posting "Which language should I speak?" and a phone-number keyboard into
a room full of strangers, and one reaching ``fallback`` is the main menu in the same place.
Neither half alone closes the hole: the group catch-alls do not know about other rooms, and
the private-chat filter cannot answer the staffer whose reply matched no card.

**``commands`` and ``start`` are UNDER the umbrella as of today, and the reason they were kept
out of it has been withdrawn rather than forgotten.** The withdrawn reason read: "a staffer
typing ``/privacy`` or ``/forget`` in the support group is making a data-subject request about
their own account and ``gate.ERASURE_COMMANDS`` may not be undone at the router layer." It was
written when this bot was in no groups at all. It is now in every group anybody adds it to —
the support-group picker actively asks operators to add it to more — and outside the umbrella
those two routers fire in all of them.

What that cost is not a tidiness complaint. ``/start`` typed by anybody in any such room takes
``handle_start``'s ``not identity.is_onboarded`` branch and ``present()`` posts
``onboarding_contact_screen`` INTO THE GROUP: a ``ReplyKeyboardMarkup`` whose button carries
``request_contact=True`` (``keyboards.py``). Anyone who taps it publishes their own phone
number to the whole room, and their answer then reaches nothing, because ``onboarding`` IS
under the umbrella. ``/balance`` and ``/support`` had the same shape with smaller blast radii.
The old reason also argued against itself on inspection: the answer to ``/privacy`` is a
statement about the person who typed it, and posting it into a room full of colleagues is a
disclosure, not a service. So the data-subject surface is REDIRECTED and not denied — the same
command in a DM does exactly what it always did, ``gate.ERASURE_COMMANDS`` is untouched, and
``handlers.support.handle_unresolved_group_message`` answers a command typed in the support
group with "I answer commands in a private chat only", so the request cannot evaporate.

``membership`` and ``support_group`` still sit outside the umbrella, and those two reasons DO
still hold. ``membership`` claims ``my_chat_member``, which is a fact about a chat of any kind
and is the one observer that must hear about groups — it is what records them. ``support_group``
is the router whose entire subject is a group.

The filter is written as two magic filters rather than one, because a callback query has no
chat of its own — it carries the message it was pressed on. A callback whose message is
absent (Telegram's inline mode, which this bot does not use) therefore matches neither and is
dropped; that is the safe direction, and the day inline mode is added this is the line to
revisit.
"""

from __future__ import annotations

from aiogram import F, Router
from aiogram.enums import ChatType

from bayram.bot.handlers import (
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
    support,
)

__all__ = ["build_router", "only_in_private"]


def only_in_private(router: Router) -> Router:
    """Stamp a customer-facing router so neither of its observers can fire outside a DM.

    A ROOT filter on the router rather than an argument to every ``.register(...)`` inside it,
    because aiogram checks a router's own filters before it reaches any handler
    (``Router._propagate_event`` calls ``check_root_filters`` and returns ``UNHANDLED`` on a
    miss). That makes the guarantee structural: there is no handler in these routers that can
    be reached from a group, including ones added later by somebody who has not read this
    file. Applied HERE rather than inside each router's own ``build_router`` for the same
    reason the ORDER lives here: it is a property of the assembled tree, and eleven copies of
    it is eleven places for the twelfth to be forgotten.

    Applied by wrapping rather than by nesting the eleven under one parent router, and that is
    deliberate: the flat list in :func:`build_router` is what this module's docstring is ABOUT,
    it is what ``tests/test_bot/test_app.py`` reads to assert that ``commands`` precedes the
    free-text steps, and a documented ordering that can only be seen by walking into a
    sub-router is a documented ordering nobody checks.

    ``callback_query`` needs its own spelling because a callback has no chat of its own — it
    carries the message it was pressed on. A callback whose message is absent (Telegram's
    inline mode, which this bot does not use) matches neither and is dropped; that is the safe
    direction, and the day inline mode arrives this is the line to revisit.
    """
    router.message.filter(F.chat.type == ChatType.PRIVATE)
    router.callback_query.filter(F.message.chat.type == ChatType.PRIVATE)
    return router


def build_router() -> Router:
    """A fresh, fully wired router tree. Called once by the composition root."""
    router = Router(name="bayram")
    router.include_routers(
        membership.build_router(),
        # Under the umbrella since 2026-09-15. See the module docstring: outside it, ``/start``
        # in any group the bot was added to posted a ``request_contact`` keyboard in front of
        # the whole room. The ORDER is unchanged and is still load-bearing — ``only_in_private``
        # stamps a filter on the router it is handed and returns that same router.
        only_in_private(commands.build_router()),
        only_in_private(start.build_router()),
        support.build_group_router(),
        only_in_private(onboarding.build_router()),
        only_in_private(menu.build_router()),
        only_in_private(support.build_router()),
        only_in_private(navigation.build_router()),
        only_in_private(questions.build_router()),
        only_in_private(name.build_router()),
        only_in_private(lyrics.build_router()),
        only_in_private(confirm.build_router()),
        only_in_private(checkout.build_router()),
        only_in_private(submitting.build_router()),
        only_in_private(fallback.build_router()),
    )
    return router
