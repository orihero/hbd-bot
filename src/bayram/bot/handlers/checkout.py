"""The two purchase buttons: buy one song, or take the plan.

**This is the entire payment integration.** One ``await deps.checkout.charge(...)``, whose
provider is :class:`~bayram.checkout.StubCheckoutProvider` by default — it contacts nothing,
opens no socket and reports every charge paid — and
:class:`~bayram.payme.provider.PaymeCheckoutProvider` when ``BAYRAM_CHECKOUT_PROVIDER=payme``.
Putting Payme in was a new ``CheckoutProvider`` class and one line in
``runtime/container.py``, which is what makes the seam a seam rather than an aspiration.

**The claim that "nothing in this module changes" was wrong, and this is the module that
found out.** It held for the charge, the key, the fulfiller and all three replay guards; it
did not hold for the ANSWER. A redirect rail returns ``Ok`` with ``is_paid=False`` and a
``checkout_url`` every time it successfully STARTS a payment, and this file used to collapse
that with ``Err`` into one branch that said "That did not go through, and nothing was
charged" — a sentence shown to a customer at the exact moment their payment had begun. One
branch and one return type is the whole of what a real rail cost here (``PAYME_INTEGRATION
§1``); the failure branch below is otherwise written and covered exactly as it was against a
provider that could not fail. Every defence in this file is sized for the real rail and not
for the stub, because a duplicate grant against the stub is a free song and the same
duplicate against Payme is 7 000 UZS taken twice.

Paying does NOT queue a render **in this process, and that half of the decision is
unchanged.** On an INLINE rail it buys the entitlement and redraws the screen the button was
pressed on, which then wears whatever the meter now says, and the customer presses 🎬 Record
it themselves. Folding the purchase into ``handlers.confirm.handle_confirm`` was rejected and
STAYS rejected: that handler's double-tap defence is four ordered facts, and three tests park
it on ``deps.payment.authorize`` specifically — an ``await`` inserted ahead of that suspension
point would gut what they measure without ever going red.

**On a REDIRECT rail the customer is not on that screen any more**, and may be hours away
with the phone in their pocket, so there is nobody there to press anything. The render is
therefore started at SETTLEMENT, by the worker, from a marker this handler records on the
payment intent when it builds the link — :func:`_resumable_order_id` below,
:mod:`bayram.runtime.render_resume`, ``DECISIONS.md D17``. That reverses "paying starts
nothing" for that rail and for that rail alone, behind ``BAYRAM_AUTO_RENDER_ON_PAYMENT``,
whose false value restores exactly the behaviour described above.

The next reader tempted to re-fold the purchase into ``handle_confirm`` on the strength of
that reversal should read the paragraph before it again: it is still true, and the reason the
resume lives in another module in another process is precisely that it must not be true of
this one.

TWO SURFACES, AND THE SECOND ONE WAS DEAD
-----------------------------------------
The buttons are drawn on two screens, not one. ``handlers.balance`` puts them on the
Confirm screen when the account cannot afford a render, and it puts the SAME two buttons on
the ``/balance`` answer — reachable by the ``/balance`` command and by the 🎫 button on the
persistent menu, in any FSM state and in none.

Both were registered behind a ``Wizard.confirm`` state filter, so only the first of them
ever worked. Pressing 💳 on the ``/balance`` screen fell through every router to
``fallback.handle_stale_callback``, which toasted "your session expired" and edited the
balance into a Start-over screen: the customer most likely to want to buy — the one who
just opened ``/balance`` to find out they had run out — could not. That is the defect the
four registrations at the bottom of this file exist to keep fixed, and it is why
:func:`_buy_from_balance` exists at all rather than the wizard handler simply losing its
filter. The two surfaces need genuinely different behaviour:

* **In the wizard** there is a draft, the customer is one tap from a render, and the screen
  to go back to is the Confirm screen. The FSM is flipped to ``Wizard.submitting`` for the
  duration (fact 1 below).
* **From ``/balance``** there is no draft and there may be no session at all — or there may
  be a half-answered wizard parked three screens back, because ``/balance`` deliberately
  answers mid-wizard without disturbing it. So this path TOUCHES NO FSM STATE. It writes
  FSM data (the counter and the two replay markers, which merge) and never calls
  ``set_state``, because flipping the state of somebody who is halfway through the note
  step would lose them their draft to a button they pressed to check their balance.

Five facts govern the WIZARD handler, and the first four may not be reordered. Four of them
defend it against a double tap; the fifth is what a REDIRECT rail does to the first of those,
and it is written down here because it is easier to read the four and assume they still hold
than to notice that one of them expires the moment the handler returns:

1. **The first await is** ``state.set_state(Wizard.submitting)``, before ``callback.answer()``.
   The wizard registrations below filter on ``Wizard.confirm``, so a second tap arriving
   after the flip matches neither of them; and because the dispatcher holds a per-chat lock
   for the whole update (``bot.app.build_dispatcher``), two taps in one ``getUpdates`` batch
   cannot both read ``Wizard:confirm``. Answering the callback first would clear the
   button's spinner and invite exactly the second press this is defending against. It is the
   same shape ``handlers.confirm`` uses and the same shape ``lyrics.enter_lyrics_step`` uses
   while a write is in progress. The ``/balance`` registrations are filtered to exclude
   ``Wizard.submitting`` for this reason and no other: without that exclusion they would
   claim the very tap fact 1 is shedding and charge for it.
2. **The whole body runs inside ``try``/``finally``, and the finally puts the state back**
   if it is still ``Wizard.submitting``. ``runtime.jobs._release_session`` is the ONLY other
   un-parker of that state and it runs only from a job — no job exists here — so a checkout
   that returned or raised while parked there would strand the customer behind
   ``handlers.submitting`` forever, with ``navigation._refuse_while_running`` blocking every
   button on the screen they were left holding. The guard is conditional because
   :func:`~bayram.bot.handlers.common.expire` clears the session outright and
   ``show_confirm`` has already restored ``Wizard.confirm`` on the paths that redraw: only a
   path that did neither may be rescued.
3. **The idempotency key is deterministic** per (telegram user, purchase scope, product,
   counter) and lands on a unique index in the ledger, so a key that reaches the store twice
   grants once. See :func:`_idempotency_key` for what the scope is on each surface and for
   why the counter may not be the whole defence.
4. **Every exit path ends in a REDRAW FROM THE METER** — ``balance.show_confirm`` in the
   wizard, ``balance.show_balance`` from ``/balance`` — so the screen the customer reads
   afterwards is drawn from the account rather than assumed. A paid purchase that failed to
   redraw would leave a paywall on screen over an account that could now afford a render,
   and the customer would pay twice. On the PENDING branch the meter has not moved in the
   wizard, so the redraw's real work there is fact 2's state restoration plus an edit that
   changes nothing and that ``common._edit_or_send`` now swallows in silence; the link
   screen is what removes the price button.
5. **A REDIRECT rail leaves ``Wizard.submitting`` the instant this handler returns**, and
   fact 1 is therefore gone for the whole of the customer's trip to the payment page. The
   ``finally`` restores ``Wizard.confirm`` before the browser has even opened, and settlement
   arrives minutes or hours later, inbound, at a different process — so for the entire life
   of the redirect the shed-the-second-tap property is carried by the five-second window and
   the settled-update list ALONE. That is why :func:`_remember_pending` writes both markers
   even though it granted nothing: on the settled path they are a second line behind a state
   flip, and on this one they are the only line there is. The DURABLE guarantee is elsewhere
   entirely and is not this module's — ``payment_intents.idempotency_key`` carries a unique
   index, so a key that reaches ``open_intent`` twice opens one intent, returns one
   ``public_ref`` and therefore produces one link, however many taps got there
   (``PAYME_INTEGRATION §5``). None of the three guards here is redundant for all that: they
   are what stops the bot re-sending the same link on a redelivered update, which the unique
   index has no opinion about. The durable guarantee against a DOUBLE RENDER is a different
   column again — ``payment_intents.resumed_at``, claimed by a conditional UPDATE before any
   side effect — and is likewise not this module's.

TWO THINGS THE COUNTER CANNOT SEE, AND WHAT CLOSES THEM
-------------------------------------------------------
Fact 3 used to be written as though the key caught everything ordering could not. It did
not, and both gaps sold a second song for one intent:

* **A REDELIVERED UPDATE that arrives after the counter moved.** The counter is bumped only
  after a successful write, which is the right shape for a FAILED write (see
  :func:`_fulfilment_failed`) and the wrong one for a successful one: if the handler
  completes — grant written and ``purchase_seq`` persisted — and the process then dies
  before ``getUpdates`` confirms the offset, Telegram redelivers the identical callback, the
  handler reads the NEW counter, mints a key the ledger has never seen, and charges again.
  Closed by :data:`PURCHASE_SETTLED_UPDATES_KEY`: the ``update_id`` of every update that
  settled a purchase is remembered, written in the SAME ``update_data`` call as the bump, and
  an update whose id is already in that list is a replay of work that has already landed.
  ``update_id`` is the right identity because it is what Telegram REPEATS — a redelivery is
  the same update, byte for byte, and two genuine presses are two ids.
* **A DOUBLE TAP.** The per-chat lock serialises the two taps completely, so tap two runs
  after the ``finally`` has restored ``Wizard.confirm``, reads the moved counter, mints a
  distinct key and charges again. That was documented as intended — top-ups on top of
  top-ups are decided behaviour — and it is intended for a DELIBERATE second purchase. It is
  not intended for a thumb that bounced, and on Payme that thumb costs 14 000 UZS instead of
  7 000. Closed by :data:`PURCHASE_SETTLED_AT_KEY`, :data:`PURCHASE_SETTLED_PRODUCT_KEY` and
  :data:`DOUBLE_TAP_WINDOW`: a press of THE SAME BUTTON arriving within a few seconds of a
  purchase that has just settled is the same intent, and is answered with a redraw instead of
  a charge. Keyed on the clock alone — which is how this shipped first — the guard also
  swallowed the customer who bought a song and immediately decided on the plan, refusing a
  larger sale in total silence. The product is half the key for that reason.

  **The deliberate case survives**, and that is the constraint the window is sized to: a
  customer who wants a second song reads the receipt, finds the paywall message the button
  is on (the redrawn screen no longer carries one) and presses again, which no human does
  inside five seconds. The window is measured from SETTLEMENT rather than from the first
  tap, so a slow rail cannot widen it — with Payme parked for eight seconds, tap two is held
  by the lock and runs at settlement plus milliseconds, which is exactly the reading that
  makes it a bounce.

  The window is deliberately NOT scoped to the product. 💳 and 🌟 are one row apart on the
  same keyboard, and a thumb that hits 💳 and then 🌟 has cost 56 000 UZS; making the guard
  product-blind costs a customer who genuinely wants both a five-second wait, which is a
  price worth paying in that direction.

Neither marker replaces the counter, and this is the ordering that makes all three work:
the counter is what a RETRY collapses onto (an unchanged counter re-mints the key the ledger
already refused to double), the update list is what a REDELIVERY collapses onto, and the
timestamp is what a BOUNCE collapses onto. Three different failures, three different
mechanisms, and the money moves once in all of them.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from enum import StrEnum
from typing import Final
from uuid import UUID

from aiogram import F, Router
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Update

from bayram.bot.callbacks import NavAction, NavCB
from bayram.bot.deps import BotDeps
from bayram.bot.draft import WizardDraft
from bayram.bot.handlers.balance import show_balance, show_confirm
from bayram.bot.handlers.common import error_text, expire, present, read_draft, say
from bayram.bot.i18n import translate
from bayram.bot.middleware import resolve_language
from bayram.bot.order_id import order_id_for
from bayram.bot.screens import checkout_link_screen, menu_screen
from bayram.bot.states import Wizard
from bayram.checkout import Product, PurchaseRequest
from bayram.contracts import Err, Language
from bayram.logging import get_logger

__all__ = [
    "build_router",
    "handle_pay",
    "handle_subscribe",
    "handle_pay_from_balance",
    "handle_subscribe_from_balance",
    "SettleOutcome",
    "PURCHASE_SEQ_KEY",
    "PURCHASE_SETTLED_UPDATES_KEY",
    "PURCHASE_SETTLED_AT_KEY",
    "PURCHASE_SETTLED_PRODUCT_KEY",
    "DOUBLE_TAP_WINDOW",
]

_LOG = get_logger(__name__)


class SettleOutcome(StrEnum):
    """What one press of a purchase button actually did. Three answers, not two.

    :func:`_settle` used to return ``bool``, and the boolean was honest while every rail
    settled inline: money moved on this press, or it did not. A REDIRECT rail is neither. It
    answers ``Ok`` with ``is_paid=False`` and a ``checkout_url`` — a payment that has begun,
    against which nothing may be granted and about which "nothing was charged" is already
    false. Squeezed into the old ``bool`` it would have had to be ``False``, which is the
    same value a declined charge carries, and the two call sites would have gone on treating
    them identically: that is precisely the bug this enum exists to make unrepresentable.

    An enum rather than a second boolean because ``mypy --strict`` then NAMES every call
    site that has to be reconsidered when the shape changes again — a ``bool`` widened to a
    third state silently keeps compiling everywhere it is read.

    ``SETTLED`` and ``NOTHING`` mean exactly what ``True`` and ``False`` meant, and behaviour
    on both is byte-identical to what it was: ``SETTLED`` is "a purchase settled ON THIS
    PRESS" and not "the customer has credits", so a swallowed replay is ``NOTHING`` even
    though the account is richer for it — the caller uses this to decide whether to say
    something new, and a replay has already said everything it has to say.
    """

    #: Money moved and the grant is written. The only value that may draw a receipt.
    SETTLED = "settled"
    #: A payment was STARTED at a redirect rail and the customer has been handed the link.
    #: Nothing is granted, nothing is owed to them yet, and the fulfiller was never called.
    PENDING = "pending"
    #: Nothing happened: a shed replay, a shed double tap, a refusal, a decline, or a
    #: deployment that cannot sell.
    NOTHING = "nothing"


# The actor a purchase grant is recorded against is deliberately NOT named in this module.
# It lives on the write side, as ``bayram.db.purchases.CHECKOUT_ACTOR``, because
# ``bayram.checkout.PurchaseFulfiller`` carries no ``actor`` parameter at all — the bot cannot
# choose who a ledger row is attributed to, which is one more thing the narrow port takes
# away from it. A constant here would be a second spelling of a value this module never
# sends, and a second spelling is how ``credit_ledger.actor`` comes to hold two words for one
# thing.

#: Where the per-scope purchase counter lives in the FSM data.
#:
#: In the FSM and not on ``WizardDraft``, deliberately. A field on the draft would change
#: ``confirm._order_fingerprint`` and therefore the UUID5 order id of every draft in flight,
#: which is the one value in this wizard that may not move — it is what makes a double tap a
#: duplicate. A bare key in ``state.get_data()`` is invisible to ``load_draft`` and costs the
#: fingerprint nothing.
PURCHASE_SEQ_KEY: Final[str] = "purchase_seq"

#: The ``update_id`` of each of the last few updates that actually settled a purchase.
#:
#: A LIST and not a single value, because Telegram redelivers from the last confirmed
#: offset: a process that dies with three updates unconfirmed replays all three, and a
#: one-slot memory would catch only the newest. Bounded at
#: :data:`_SETTLED_UPDATES_KEPT` because this dict is serialised into Redis on every write
#: and an unbounded list would grow for the life of the session — a customer with a running
#: plan buys for thirty days against one FSM key.
PURCHASE_SETTLED_UPDATES_KEY: Final[str] = "purchase_settled_updates"

#: When the last purchase settled, as epoch seconds off ``deps.clock()``.
#:
#: A float rather than an ISO string because it is arithmetic and never read by a human:
#: a string would need parsing on every press, and a parse failure inside a double-tap guard
#: fails in the expensive direction. ``deps.clock`` rather than a clock of this module's own,
#: so a test that freezes the wizard's clock freezes this window with it.
PURCHASE_SETTLED_AT_KEY: Final[str] = "purchase_settled_at"

#: WHICH product the purchase remembered by :data:`PURCHASE_SETTLED_AT_KEY` bought.
#:
#: The window is keyed on the pair, never on the clock alone, and the reason is a sale that
#: the first draft of this guard refused in silence. A customer who buys one song and then,
#: reading the receipt, decides they want the plan after all presses 🌟 within a second or
#: two — the two buttons sit side by side on the same screen, so this is a fast, ordinary
#: move, not a bounced thumb. Keyed on time alone that press was swallowed by a guard built
#: for a DIFFERENT button, redrawn with no toast and no "nothing was charged", and worked
#: again six seconds later with nothing to explain the gap. A double tap is the same button
#: twice; two different products are two decisions, and only the first is an accident.
#:
#: A session written before this key existed carries a timestamp and no product. That reads
#: as "matches whatever is being pressed", which is the pre-existing behaviour — the guard
#: stays as tight as it was for the few seconds such a session can still be inside a window,
#: rather than opening a hole at the deploy boundary to buy back a case measured in seconds.
PURCHASE_SETTLED_PRODUCT_KEY: Final[str] = "purchase_settled_product"

#: How long after a settled purchase a further press is read as the same intent, in seconds.
#:
#: Five, and the two bounds it sits between are worth writing down because a future edit will
#: want to move it. Below it lies a bounced thumb, which is measured from settlement and
#: therefore lands within milliseconds however slow the rail is. Above it lies a deliberate
#: second purchase, which needs the customer to read a receipt and go back to a paywall
#: message that the redraw has already replaced. Widening this refuses a real sale; removing
#: it charges twice for one thumb.
DOUBLE_TAP_WINDOW: Final[float] = 5.0

#: How many settled ``update_id`` values are remembered. See :data:`PURCHASE_SETTLED_UPDATES_KEY`.
_SETTLED_UPDATES_KEPT: Final[int] = 8


async def handle_pay(
    callback: CallbackQuery, state: FSMContext, deps: BotDeps, event_update: Update
) -> None:
    """💳 One song, at the single-song price, pressed on the Confirm screen."""
    await _buy_in_wizard(callback, state, deps, event_update, product=Product.SINGLE)


async def handle_subscribe(
    callback: CallbackQuery, state: FSMContext, deps: BotDeps, event_update: Update
) -> None:
    """🌟 The starter plan, pressed on the Confirm screen."""
    await _buy_in_wizard(callback, state, deps, event_update, product=Product.STARTER)


async def handle_pay_from_balance(
    callback: CallbackQuery, state: FSMContext, deps: BotDeps, event_update: Update
) -> None:
    """💳 One song, pressed on the ``/balance`` screen rather than inside the wizard."""
    await _buy_from_balance(callback, state, deps, event_update, product=Product.SINGLE)


async def handle_subscribe_from_balance(
    callback: CallbackQuery, state: FSMContext, deps: BotDeps, event_update: Update
) -> None:
    """🌟 The starter plan, pressed on the ``/balance`` screen rather than inside the wizard."""
    await _buy_from_balance(callback, state, deps, event_update, product=Product.STARTER)


async def _buy_in_wizard(
    callback: CallbackQuery,
    state: FSMContext,
    deps: BotDeps,
    event_update: Update,
    *,
    product: Product,
) -> None:
    """Charge from the Confirm screen and put the customer back on it, drawn from the meter.

    One function for both buttons because the five ordered facts in the module docstring are
    the same five for both, and two copies of a double-tap defence is one copy that drifts.
    The product is the only thing that differs, and it differs in exactly two places: the
    amount quoted to the rail, and which method of the fulfiller is called.
    """
    # Fact 1: nothing may be awaited before the flip. See the module docstring.
    await state.set_state(Wizard.submitting)
    await callback.answer()
    try:
        draft = await read_draft(state)
        if draft is None:
            # ``expire`` clears the session outright, so the finally below finds no
            # ``Wizard.submitting`` to restore and correctly leaves it cleared.
            await expire(callback, state)
            return

        async def redraw() -> None:
            await show_confirm(callback, state, deps, draft)

        await _settle(
            callback,
            state,
            deps,
            product=product,
            language=draft.ui_language,
            # ``session_id`` and not the draft fingerprint, because any new field on
            # ``WizardDraft`` would change ``confirm._order_fingerprint`` and therefore the
            # order id.
            scope=draft.session_id,
            update_id=event_update.update_id,
            redraw=redraw,
            # The render this payment buys, if it buys one. Computed HERE rather than at
            # settlement because the draft is HERE: the id is a UUID5 over these exact
            # answers, so one value is simultaneously the order's address and the proof, when
            # the money lands, that the draft has not moved since. See
            # :func:`_resumable_order_id` for the two refusals that make it ``None``.
            resume_order_id=_resumable_order_id(callback.from_user.id, draft),
        )
    finally:
        # Fact 2. Only a path that neither redrew nor cleared can still be parked here, and
        # leaving it parked would strand the customer behind ``handlers.submitting``.
        if await state.get_state() == Wizard.submitting.state:
            await state.set_state(Wizard.confirm)


async def _buy_from_balance(
    callback: CallbackQuery,
    state: FSMContext,
    deps: BotDeps,
    event_update: Update,
    *,
    product: Product,
) -> None:
    """Charge from the ``/balance`` screen, where there is no draft and maybe no session.

    **Nothing here touches the FSM STATE**, and that is the whole difference from the wizard
    path. ``/balance`` is answerable at any moment, including three screens into a wizard
    run, so this handler can be reached with a half-written draft parked behind it — and a
    ``set_state`` would overwrite the step that draft is waiting on and lose it to somebody
    who pressed a button to buy a song. Fact 1's flip is therefore replaced, for this
    surface, by the two markers in the module docstring: the settled-update list and the
    double-tap window, both of which are FSM DATA and merge rather than overwrite.

    **Where the customer lands afterwards is the other difference.** ``show_confirm`` needs
    a draft and there is none, so the redraw is ``show_balance``, which EDITS the balance
    message in place: the new count replaces the old one and the purchase buttons go with
    it, which is what stops the customer pressing a price they have already paid. That
    screen carries no button of its own, so a purchase made between flows also gets the menu
    under it — ``menu_screen`` is the persistent keyboard with 🎵 Make a song on it, which is
    the next step somebody who has just bought a song actually wants. It is drawn ONLY when
    there is no session, because a customer who is mid-wizard already has a live screen to go
    back to and "what are we making?" over the top of it would be the dead end this is
    avoiding, in the other direction. **And only when a purchase actually SETTLED** — a
    redirect rail's answer is a link, not a song, and the condition below says which.
    """
    await callback.answer()
    language = await resolve_language(state)

    async def redraw() -> None:
        await show_balance(callback, state, deps)

    outcome = await _settle(
        callback,
        state,
        deps,
        product=product,
        language=language,
        # There is no draft and therefore no ``session_id``. See :func:`_idempotency_key`.
        scope=_balance_scope(callback),
        update_id=event_update.update_id,
        redraw=redraw,
        # **No render marker is minted on this surface, and the omission is the decision.**
        # There is no draft here to take a fingerprint of, and reaching into the FSM for
        # whatever one happens to be parked would attach this money to a run the customer did
        # not buy it for — the scope of the idempotency key above is this BALANCE MESSAGE,
        # while the marker's scope would be some other wizard run entirely, and the two
        # disagreeing about which purchase belongs to which run is worse than not resuming.
        #
        # A customer who buys from ``/balance`` with a finished draft parked behind them is
        # not stranded by this: ``runtime.render_resume`` reads the session anyway to choose
        # the announcement's keyboard, so they are handed a live 🎬 on the draft they were
        # working on. One tap instead of none, and no guess about whose money it was.
        resume_order_id=None,
    )
    # ``SETTLED`` only, and ``PENDING`` deliberately not. The menu is drawn here as the next
    # step for somebody who has just bought a song — and a customer who has just been handed
    # a payment link has not bought one yet. It would also land ON TOP of the link screen:
    # ``menu_screen`` carries a REPLY keyboard, which ``present`` can only ever SEND (see
    # ``Screen.markup``), so "what are we making?" would be the last thing under a 🔗 button
    # the customer has not tapped.
    if outcome is SettleOutcome.SETTLED and await state.get_state() is None:
        await present(callback, menu_screen(language))


async def _settle(
    callback: CallbackQuery,
    state: FSMContext,
    deps: BotDeps,
    *,
    product: Product,
    language: Language,
    scope: str,
    update_id: int,
    redraw: Callable[[], Awaitable[None]],
    resume_order_id: UUID | None = None,
) -> SettleOutcome:
    """Charge, fulfil, remember, redraw — or hand over a link and grant nothing.

    The two surfaces share this because the sequence is not what differs between them: the
    key, the rail, the fulfiller, the three replay guards and the order they run in are one
    decision, and two copies of that decision is one copy that drifts. What differs is
    handed in — the scope the key is namespaced by, the language, and the screen to redraw —
    so a reader comparing the surfaces reads two short functions rather than diffing two
    long ones.

    **``deps.checkout.charge`` now has THREE answers and each gets its own branch**, in the
    order a reader should meet them. ``Err`` is a rail that refused — paused, unreachable,
    declined — and is rendered from the typed error, so a paused rail and a declined card do
    not read alike. ``Ok`` with ``is_paid=False`` AND a ``checkout_url`` is a payment that has
    successfully STARTED: it is the normal answer of a redirect rail, it must never reach the
    fulfiller, and the customer gets the link. ``Ok`` with ``is_paid=False`` and NO url is a
    rail that said neither yes nor here-is-where, which is a bug in the rail rather than a
    thing that happens to customers — it keeps the old ``checkout.failed`` sentence, which is
    still the correct one for an inline rail that declined, and logs loudly.

    See :class:`SettleOutcome` for what the return value means and why it is no longer a
    ``bool``.
    """
    user = callback.from_user
    store, pricing = deps.purchases, deps.pricing
    if store is None or pricing is None:
        # A button drawn by a deployment that could sell, pressed against one that
        # cannot — a stale message, or a rail withdrawn between deploys. Say so and
        # redraw; the redraw is what removes the button that should not be there.
        _LOG.info("a purchase button was pressed on a deployment that cannot sell")
        await say(callback, translate("checkout.unavailable", language))
        await redraw()
        return SettleOutcome.NOTHING
    data = await state.get_data()
    if update_id in _settled_updates(data):
        # Telegram sent this exact update again, and the purchase it carried has already
        # been written AND recorded. Redraw so the customer sees the truth, say nothing —
        # every sentence this press had to say was said the first time it arrived — and
        # above all do not charge.
        _LOG.info(
            "a settled update was redelivered; not charging again",
            extra={"update_id": update_id, "product": product.value},
        )
        await redraw()
        return SettleOutcome.NOTHING
    if _within_double_tap_window(data, now=deps.clock().timestamp(), product=product):
        _LOG.info(
            "a purchase button was pressed again within the double-tap window",
            extra={"update_id": update_id, "product": product.value},
        )
        await redraw()
        return SettleOutcome.NOTHING
    seq = int(data.get(PURCHASE_SEQ_KEY, 0))
    key = _idempotency_key(user.id, scope, product=product, seq=seq)
    amount_minor = (
        pricing.single_amount_minor if product is Product.SINGLE else pricing.plan_amount_minor
    )
    charged = await deps.checkout.charge(
        PurchaseRequest(
            telegram_user_id=user.id,
            product=product,
            amount_minor=amount_minor,
            currency=pricing.currency,
            idempotency_key=key,
            # Passed through untouched, and meaningful only to a REDIRECT rail: it records
            # which render this money buys, so the settlement — which happens in another
            # process, after the customer has put their phone away — can start it. An inline
            # rail ignores it, because there is nothing to resume when the answer arrives on
            # this very call.
            resume_order_id=resume_order_id,
        )
    )
    if isinstance(charged, Err):
        # The rail refused, and the typed error is what says which refusal it was. This used
        # to be a hardcoded ``translate("checkout.failed", ...)``, which was correct while the
        # only rail could not fail; a real one refuses for reasons a customer can act on
        # differently — ``CheckoutPausedError`` means "come back in a few minutes" and a
        # decline means "try again". The SHIPPED COPY IS UNCHANGED for the ordinary case,
        # because ``CheckoutError.default_user_message_key`` is ``checkout.failed``.
        _LOG.info(
            "a purchase did not settle",
            extra={"product": product.value, "idempotency_key": key, **charged.error.to_log_dict()},
        )
        await say(callback, error_text(charged.error, language))
        await redraw()
        return SettleOutcome.NOTHING
    link = charged.value.checkout_url
    if not charged.value.is_paid and link is not None:
        # **THE PENDING BRANCH: this is a SUCCESSFUL START, not a failure.** An unpaid
        # receipt carrying somewhere to pay is what a redirect rail returns every single time
        # it opens a payment, so the fulfiller is not called, nothing is granted, and the
        # customer is handed the link. Reaching ``store.fulfil_single`` from here would give
        # away a song for every checkout anybody ever abandoned.
        _LOG.info(
            "a purchase was started at a redirect rail",
            extra={
                "product": product.value,
                "idempotency_key": key,
                # Whether, and never WHICH. The marker is a fingerprint of the customer's own
                # words — a name, a note, a lyric — and the key above already identifies the
                # intent for anybody reading this line.
                "has_resume_marker": resume_order_id is not None,
            },
        )
        await _remember_pending(
            state, data, update_id=update_id, now=deps.clock().timestamp(), product=product
        )
        # Fact 4 holds on this branch too. The redraw re-reads the meter — which on the
        # ``/balance`` surface really can have moved, because a DIFFERENT intent may have
        # settled since that message was drawn — and in the wizard it is what puts the FSM
        # back in ``Wizard.confirm`` before a screen whose buttons are answered from that
        # state is drawn.
        #
        # In the wizard this branch grants nothing, so the redraw normally renders BYTE-
        # IDENTICAL text and markup and Telegram answers 400 "message is not modified".
        # ``common._edit_or_send`` swallows exactly that and draws nothing. It used to send a
        # clone instead, which is how ONE press produced a link message AND a second paywall
        # carrying a live 💳 button underneath it — the customer read a price under a link
        # they had already been handed. The link screen then replaces the paywall IN THE SAME
        # MESSAGE, which is what the customer should see: the price button becomes the Pay
        # button. On a message Telegram will no longer let us edit — a different 400 — the
        # fallback still sends, and the link arrives as a new message.
        await redraw()
        await present(callback, checkout_link_screen(language, url=link, amount_minor=amount_minor))
        return SettleOutcome.PENDING
    if not charged.value.is_paid:
        # Unpaid, and nowhere to pay. For an INLINE rail this is an ordinary decline and
        # ``checkout.failed`` — "nothing was charged" — is exactly right, which is why the
        # sentence is unchanged. For a REDIRECT rail it is impossible by construction and
        # therefore a defect in the rail: a provider that answered neither yes nor
        # here-is-where has left the customer with no way forward, so it is logged at ERROR
        # rather than at INFO, with the key that would identify the intent that was never
        # opened.
        _LOG.error(
            "a rail returned an unpaid purchase with nowhere to pay",
            extra={
                "product": product.value,
                "idempotency_key": key,
                "provider": charged.value.provider,
                "reference": charged.value.reference,
            },
        )
        await say(callback, translate("checkout.failed", language))
        await redraw()
        return SettleOutcome.NOTHING
    if product is Product.SINGLE:
        single = await store.fulfil_single(
            telegram_user_id=user.id, purchase=charged.value, idempotency_key=key
        )
        if isinstance(single, Err):
            await _fulfilment_failed(callback, deps, language, single, redraw)
            return SettleOutcome.NOTHING
        await _remember(
            state,
            data,
            seq=seq,
            update_id=update_id,
            now=deps.clock().timestamp(),
            product=product,
        )
        await say(
            callback,
            translate("checkout.paid_single", language, credits=single.value.credits),
        )
    else:
        plan = await store.start_plan(
            telegram_user_id=user.id,
            purchase=charged.value,
            songs=pricing.plan_songs,
            days=pricing.plan_days,
            idempotency_key=key,
        )
        if isinstance(plan, Err):
            await _fulfilment_failed(callback, deps, language, plan, redraw)
            return SettleOutcome.NOTHING
        await _remember(
            state,
            data,
            seq=seq,
            update_id=update_id,
            now=deps.clock().timestamp(),
            product=product,
        )
        await say(
            callback,
            translate(
                "checkout.paid_plan",
                language,
                songs=plan.value.songs_left,
                ends_on=plan.value.ends_at.date().isoformat(),
            ),
        )
    _LOG.info(
        "a purchase was fulfilled",
        extra={
            "product": product.value,
            "provider": charged.value.provider,
            "reference": charged.value.reference,
            "idempotency_key": key,
        },
    )
    await redraw()
    return SettleOutcome.SETTLED


async def _remember(
    state: FSMContext,
    data: dict[str, object],
    *,
    seq: int,
    update_id: int,
    now: float,
    product: Product,
) -> None:
    """Record that this press bought something, in ONE write. All four markers or none.

    One ``update_data`` call and not four, because a process that died between them would
    leave the markers disagreeing about what happened — a bumped counter with no settled
    update recorded is precisely the state that sold a second song to a redelivery, which is
    the defect this function exists to make unreachable. FSM storage gives no transaction
    across separate writes, so the atom has to be the write itself.

    The timestamp and the product are ONE marker in two keys and must never be written
    apart: :func:`_within_double_tap_window` reads a timestamp with no product beside it as
    "some purchase settled, assume this press is its double tap", so a write that landed the
    clock without the label would refuse the other button for five seconds.

    It is called only after a fulfilment has SUCCEEDED. A failed write must leave all four
    alone: see :func:`_fulfilment_failed` for why the counter in particular has to stay put.
    """
    kept = [*_settled_updates(data), update_id][-_SETTLED_UPDATES_KEPT:]
    await state.update_data(
        {
            PURCHASE_SEQ_KEY: seq + 1,
            PURCHASE_SETTLED_UPDATES_KEY: kept,
            PURCHASE_SETTLED_AT_KEY: now,
            PURCHASE_SETTLED_PRODUCT_KEY: product.value,
        }
    )


async def _remember_pending(
    state: FSMContext,
    data: dict[str, object],
    *,
    update_id: int,
    now: float,
    product: Product,
) -> None:
    """Record that this press opened a payment. Three markers of four, in ONE write.

    The same single ``update_data`` call as :func:`_remember` and for the same reason — FSM
    storage gives no transaction across separate writes, so the atom has to be the write
    itself, and the timestamp and the product in particular may never be written apart (see
    :func:`_within_double_tap_window`).

    **:data:`PURCHASE_SEQ_KEY` is deliberately NOT bumped, and that is the whole difference
    from :func:`_remember`.** The counter is what makes a press mint a NEW idempotency key,
    and a new key on a redirect rail means a new intent, a new ``public_ref`` and therefore a
    SECOND live payment page in one chat for one purchase — two links the customer cannot tell
    apart, only one of which their money would be in. Leaving it put means a deliberate press
    after the double-tap window re-mints the IDENTICAL key, ``open_intent`` insert-or-ignores
    on its unique index, and the SAME link comes back (``PAYME_INTEGRATION §5``). The two
    markers that ARE written still do their jobs: a redelivered update is shed by the update
    list so the bot does not re-send a link nobody asked for twice, and a bounced thumb is
    shed by the window.

    The cost is real and worth naming: within one SCOPE the counter now never moves on a
    redirect rail, so a second, genuinely deliberate purchase is not expressible from the same
    Confirm screen or the same ``/balance`` message — it needs a new scope, which is what a
    customer who wants a second song produces anyway by starting a new run or re-opening
    ``/balance`` (see :func:`_idempotency_key`). Pressing the stale button instead re-opens the
    intent they have already paid, and the rail answers that with a refusal rather than a
    charge. A bumped counter would have bought the second purchase at the price of a second
    payment page, which is the wrong trade at 7 000 UZS a page.
    """
    kept = [*_settled_updates(data), update_id][-_SETTLED_UPDATES_KEPT:]
    await state.update_data(
        {
            PURCHASE_SETTLED_UPDATES_KEY: kept,
            PURCHASE_SETTLED_AT_KEY: now,
            PURCHASE_SETTLED_PRODUCT_KEY: product.value,
        }
    )


def _settled_updates(data: dict[str, object]) -> list[int]:
    """The remembered ``update_id`` values, defensively.

    FSM data outlives a deploy and is round-tripped through JSON by ``RedisStorage``, so
    this key can be absent (a session that predates it), or a type this build does not
    expect (a rename, a hand edit, a future shape). Every one of those has to read as "no
    replay has been recorded" rather than raise: an exception here would fire INSIDE the
    guard that stops a double charge, and the error guard would leave the customer with a
    spinning button and no purchase.
    """
    raw = data.get(PURCHASE_SETTLED_UPDATES_KEY)
    if not isinstance(raw, list):
        return []
    return [item for item in raw if isinstance(item, int)]


def _within_double_tap_window(data: dict[str, object], *, now: float, product: Product) -> bool:
    """Did a purchase of THIS product settle within :data:`DOUBLE_TAP_WINDOW` seconds?

    Both halves are required, and the product half is the one that is easy to leave out —
    see :data:`PURCHASE_SETTLED_PRODUCT_KEY` for the sale that omitting it refused without
    saying anything. A press of the OTHER button is a second decision, not a bounced thumb,
    so it is let through to be charged.

    A missing or malformed marker answers ``False``, for the reason :func:`_settled_updates`
    gives. So does a marker in the FUTURE: an operator who moves the clock backwards, or a
    Redis value written by a host whose time was wrong, would otherwise put every press of
    that session behind a window that never closes and the customer could never buy again.
    Failing open on a nonsense timestamp costs at most one duplicate charge in a case nobody
    has ever seen; failing closed costs every sale for the life of the session.

    A missing PRODUCT marker is the one thing that does NOT fail open, because it is not a
    nonsense value: it is a session written by the build before this key existed, and the
    conservative reading of "something settled two seconds ago" is that this press is its
    double tap. That costs a refused second-product purchase for at most
    :data:`DOUBLE_TAP_WINDOW` seconds per session, once, at a deploy boundary.
    """
    raw = data.get(PURCHASE_SETTLED_AT_KEY)
    if not isinstance(raw, int | float) or isinstance(raw, bool):
        return False
    elapsed = now - float(raw)
    if not 0.0 <= elapsed < DOUBLE_TAP_WINDOW:
        return False
    settled = data.get(PURCHASE_SETTLED_PRODUCT_KEY)
    if not isinstance(settled, str):
        return True
    return settled == product.value


async def _fulfilment_failed(
    callback: CallbackQuery,
    deps: BotDeps,
    language: Language,
    result: Err,
    redraw: Callable[[], Awaitable[None]],
) -> None:
    """The write failed after the rail said paid. Say why, redraw, and remember NOTHING.

    Not remembering is the whole point of the branch, and the counter is the part that
    matters: it is unchanged, so the customer's next press retries the SAME idempotency key
    against the same unique index — a retry that can only ever produce one grant, however
    many times it happens, and which a real rail deduplicates on its side too because the key
    is what it was given. Bumping here would turn a database blip into a second charge for a
    song they have already paid for. The double-tap timestamp is left alone for the same
    reason in the opposite direction: a failed purchase must not put a five-second wall in
    front of the retry it is asking the customer to make.

    The error is rendered through ``error_text`` rather than as ``checkout.failed``, because
    money DID move on this path and "nothing was charged" would be false. The typed error
    says what actually happened, in the customer's language.
    """
    _LOG.error("a paid purchase could not be fulfilled", extra=result.error.to_log_dict())
    await say(callback, error_text(result.error, language))
    await redraw()


def _balance_scope(callback: CallbackQuery) -> str:
    """The key namespace for a purchase made outside the wizard. See :func:`_idempotency_key`.

    The message the button was drawn on, because that is the closest thing a wizard-less
    purchase has to a ``session_id``: every ``/balance`` and every 🎫 sends a NEW message, so
    one balance screen is one namespace, and a redelivered update carries the same message
    id it carried the first time. ``callback.message`` is ``None`` only for a button on an
    INLINE message, which this bot never sends; the constant it falls back to is therefore a
    namespace nothing reaches, and it is a constant rather than anything derived so that the
    fallback cannot itself mint a fresh key on every press.
    """
    message = callback.message
    return "balance" if message is None else f"balance:{message.message_id}"


def _resumable_order_id(telegram_user_id: int, draft: WizardDraft) -> UUID | None:
    """The render this draft would produce, or ``None`` if it would produce none.

    **The two refusals are ``handlers.confirm.handle_confirm``'s own, in its order**, and that
    is the point of this function existing rather than the id being computed inline: a payment
    must never record a render that the 🎬 button would itself have refused, because the
    settlement that reads this marker back runs in a process with no screen to refuse ON.

    * ``to_brief()`` is ``Err`` — the draft is incomplete (``confirm.py``'s first gate).
    * ``draft.lyrics is None`` — no lyric was approved. **This is the critical one.**
      ``REQUIRED_ANSWERS`` deliberately excludes the lyric, so ``to_brief()`` succeeds without
      one, and the pipeline writes its own lyric at ``WRITING_LYRICS`` and delivers it. A
      resume that skipped this check would deliver a song whose words nobody ever read, with
      no error anywhere to show for it — which is the exact failure the Confirm handler's
      comment on that gate describes, arriving by a route that has no customer watching.

    ``None`` is ordinary rather than exceptional: a customer can perfectly well buy a song
    with an unfinished draft on screen, and all that happens is that the settlement announces
    the payment and leaves them a button, which is what this product did for every purchase
    before the resume existed.
    """
    if isinstance(draft.to_brief(), Err) or draft.lyrics is None:
        return None
    return order_id_for(telegram_user_id, draft)


def _idempotency_key(telegram_user_id: int, scope: str, *, product: Product, seq: int) -> str:
    """The string a retry and a half-written purchase collapse onto.

    Shaped ``topup:{tg}:{scope}:{seq}`` and ``plan:starter:{tg}:{scope}:{seq}``. The product
    prefix keeps the two key spaces apart — a single song and a plan bought in the same scope
    at the same counter value must not deduplicate against each other — and ``seq`` is what
    makes a deliberate second purchase a genuinely different purchase.

    ``scope`` is the run this purchase belongs to. In the wizard it is
    ``WizardDraft.session_id``; from ``/balance`` there is no draft, so it is the balance
    message the button was drawn on (:func:`_balance_scope`). Both have the two properties
    the key needs: they are STABLE across a redelivery of the same update, and they change
    when the customer starts something genuinely new, so a key can never be reused across two
    unrelated intents. A scope derived from the update itself — the callback id, the update
    id — has the first property and not the second, and would break the retry below.

    **Be precise about which failure this defends, because it is not all of them.** What the
    key catches is a RETRY: a fulfilment that failed leaves the counter alone, so the
    customer's next press re-mints this exact string, the ledger's unique index turns the
    second write into a no-op and a real rail returns the receipt it already issued. It also
    catches a process restarted between the charge and the write, which is the same shape.

    It does NOT catch a redelivery that arrives after the counter has moved, and it does not
    catch a double tap: the counter has moved in both cases, so the key is honestly fresh.
    Those two are the module docstring's second section, and they are closed by
    :data:`PURCHASE_SETTLED_UPDATES_KEY` and :data:`PURCHASE_SETTLED_AT_KEY` rather than
    here. Reading this function as the whole defence is how the gap got shipped.
    """
    prefix = "topup" if product is Product.SINGLE else f"plan:{product.value}"
    return f"{prefix}:{telegram_user_id}:{scope}:{seq}"


def build_router() -> Router:
    """Both buttons, twice: once for the Confirm screen and once for everywhere else.

    **Order is load-bearing.** The ``Wizard.confirm`` registrations come first, so a press on
    the Confirm screen is claimed by the wizard handler and the wizard-less pair never sees
    it; aiogram takes the first registration whose filters match.

    **The ``Wizard.submitting`` exclusion is fact 1, and without it fact 1 is gone.** The
    wizard handler sheds a second tap by flipping the state out from under its own
    registration, and that tap then belongs to ``handlers.submitting`` — which is registered
    AFTER this router and answers "still being made". An unfiltered registration here would
    intercept it first and charge for it, which would make the flip a decoration. It is
    written as an inversion rather than as a list of every other state so that a step added
    to ``Wizard`` cannot silently fall out of the wizard-less surface.

    Everything else — no state at all, mid-wizard, mid-onboarding — reaches the wizard-less
    pair, which is the whole point: ``/balance`` draws these buttons in every one of those
    states, and a button that is drawn must work.
    """
    router = Router(name="checkout")
    router.callback_query.register(
        handle_pay, Wizard.confirm, NavCB.filter(F.action == NavAction.PAY)
    )
    router.callback_query.register(
        handle_subscribe, Wizard.confirm, NavCB.filter(F.action == NavAction.SUBSCRIBE)
    )
    router.callback_query.register(
        handle_pay_from_balance,
        ~StateFilter(Wizard.submitting),
        NavCB.filter(F.action == NavAction.PAY),
    )
    router.callback_query.register(
        handle_subscribe_from_balance,
        ~StateFilter(Wizard.submitting),
        NavCB.filter(F.action == NavAction.SUBSCRIBE),
    )
    return router
