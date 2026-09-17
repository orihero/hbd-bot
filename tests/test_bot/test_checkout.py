"""The paywall and the two buttons that clear it, driven through a real Dispatcher.

Every test here walks the wizard the way a customer does — real onboarding screens, real
keyboards, real callback data taken off the markup the bot actually drew — because the
properties under test are properties of the ROUTING and the FSM, and neither shows up in a
unit test of a handler called by hand. Six of them are worth naming, since they are what
the whole checkout was shaped around:

* **Nothing is queued unpaid.** The paywall face carries no 🎬 Record it button at all, so
  the customer cannot reach the submitter from it, and ``submitter.submitted`` stays empty
  for the whole unpaid flow. That is structural rather than a check, which is why it is
  asserted directly rather than inferred from an error message;
* **and nothing is queued because the meter could not be READ, either.** On a selling
  deployment both of the Confirm gate's reads fail closed: an unreadable balance ends in
  "temporarily unavailable" and a customer still holding their lyric, never in a render. It
  used to fail open, which on the shipped ``credits_enforced=false`` was a 7 000 UZS song
  given away for one bad row — so the refusal is asserted for a failure on EACH of the two
  reads, and the old fail-open is asserted to survive where nothing is sold;
* **one intent buys one song, and three different failures are kept apart.** A redelivered
  update, a bounced thumb and a retry after a failed write all reach the handler looking
  similar and are stopped by three different mechanisms — the settled-update memory, the
  double-tap window and the idempotency key. Each has its own test, and the DELIBERATE
  second purchase has one too, because a guard that also stopped that would be a purchase
  cap wearing a safety label;
* **no path strands the customer in ``Wizard.submitting``.** That state is un-parked by
  exactly one other thing in the product (``runtime.jobs._release_session``, which runs only
  from a job), so a checkout that returned while parked there would leave the customer
  behind ``handlers.submitting`` forever. Every test below ends by reading the state;
* **a button that is drawn works, wherever it is drawn.** The same two buttons appear on the
  ``/balance`` answer, in any FSM state and in none, and they were dead there — the press
  fell through to the fallback router and was answered "your session expired". The second
  half of this file drives them from that screen: between flows, mid-wizard, and against a
  deployment that has stopped selling;
* **a deployment that wires no purchase store renders yesterday's screen, byte for byte.**
  Thirty-odd ``BotDeps(`` sites in this suite wire neither ``purchases`` nor ``pricing``, so
  that property is what makes their assertions honest rather than merely passing — and it is
  asserted here by comparing the two screens as strings.

Every ``BotDeps`` built in this file passes ``profiles=``. The walkers drive the real
onboarding screens, so a dispatcher with no profile store answers the walker's very first
press with "that session expired" — and ``tests/test_bot/test_walker_preconditions.py`` is
an AST scan that fails this file if one is ever dropped.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from datetime import datetime, timedelta
from uuid import UUID

from aiogram import Bot, Dispatcher
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.memory import MemoryStorage

from bayram.bot.app import build_dispatcher
from bayram.bot.callbacks import NavAction, NavCB
from bayram.bot.deps import BotDeps
from bayram.bot.handlers.checkout import DOUBLE_TAP_WINDOW, PURCHASE_SEQ_KEY
from bayram.bot.i18n import translate
from bayram.bot.pricing import Pricing
from bayram.bot.states import Wizard
from bayram.checkout import CheckoutProvider, Product, Purchase, PurchaseFulfiller, PurchaseRequest
from bayram.config import Settings
from bayram.contracts import Err, Language, Result, err, ok
from bayram.entitlements import CreditBalance
from bayram.errors import StorageError
from tests.test_bot.conftest import (
    FAKE_PLAN_ENDS_AT,
    FIXED_MOMENT,
    USER_ID,
    FakeProfiles,
    FakePurchases,
    RecordingCheckout,
    RecordingContentWriter,
    RecordingSession,
    RecordingSubmitter,
    buttons,
    callback_update,
)
from tests.test_bot.test_credit_gate import FakeEntitlements
from tests.test_bot.test_wizard_flow import (
    complete_onboarding,
    press,
    send,
    tap,
    walk_to_confirm,
    walk_to_name,
)

PAY = NavCB(action=NavAction.PAY).pack()
SUBSCRIBE = NavCB(action=NavAction.SUBSCRIBE).pack()
CONFIRM = NavCB(action=NavAction.CONFIRM).pack()

#: Event-loop turns to burn before both racing tasks are parked. Copied from
#: ``test_submitting.py``: a single ``sleep(0)`` is not enough, because the dispatcher's
#: middleware chain and the FSM isolation lock each await on the way in.
_YIELDS = 12


async def _settle() -> None:
    for _ in range(_YIELDS):
        await asyncio.sleep(0)


class MovingClock:
    """A clock a test can push forward, for the one guard that measures time.

    The shared ``clock`` fixture is frozen at ``FIXED_MOMENT``, which is right for every
    other assertion in this suite and wrong for exactly one thing: the checkout's double-tap
    window is "did a purchase settle within the last few seconds", and under a frozen clock
    every press in a test is a double tap of every press before it. A test that means to
    drive a DELIBERATE second purchase therefore has to say so by moving the clock, which is
    also the honest model of what it is standing for — a customer reading a receipt and
    pressing again.

    It advances only when a test asks. An auto-advancing clock would make the window a
    function of how many times the handlers happen to read the time, which is a number no
    assertion should depend on.
    """

    def __init__(self) -> None:
        self.now = FIXED_MOMENT

    def __call__(self) -> datetime:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += timedelta(seconds=seconds)


class GatedCheckout:
    """A rail that charges, but only once the test lets it — the suspension a real one has.

    Every other fake in this file answers without yielding to the event loop, so nothing else
    here can put two updates in flight at once. This is the one place ``handlers.checkout``
    genuinely parks, which is where a double tap has to be measured: the first tap is
    suspended INSIDE ``charge`` with the FSM already flipped to ``Wizard.submitting``, which
    is the exact window the state filter on the registrations has to close.
    """

    def __init__(self) -> None:
        self.name = "gated"
        self.requests: list[PurchaseRequest] = []
        self.gate = asyncio.Event()

    async def charge(self, request: PurchaseRequest) -> Result[Purchase]:
        self.requests.append(request)
        await self.gate.wait()
        return ok(
            Purchase(
                product=request.product,
                provider=self.name,
                reference=f"gated-{len(self.requests)}",
                amount_minor=request.amount_minor,
                currency=request.currency,
                is_paid=True,
            )
        )


class LinkedMeter(FakeEntitlements):
    """A meter that reads the SAME account the purchase store writes.

    Two fakes standing for one database, which is what production is: ``SqlCreditLedger``
    and ``SqlPurchaseLedger`` read and write the same two tables, and ``read_balance``
    projects a live plan's unminted songs into ``credits`` so the read-only Confirm gate
    agrees with what the worker's charge will do a second later.

    Keeping them unlinked was tried first and is a trap: a test could then buy a song, watch
    the balance stay at zero, and "prove" that the paywall survives a purchase — which is a
    green test for the single worst bug this feature could have.
    """

    def __init__(self, purchases: FakePurchases) -> None:
        super().__init__(credits=0)
        self.purchases = purchases

    async def balance_for(
        self, telegram_user_id: int, *, exclude_order_id: UUID | None = None
    ) -> Result[CreditBalance]:
        self.reads.append(exclude_order_id)
        if self.failure is not None:
            return err(self.failure)
        plan = self.purchases.plan
        plan_left = 0 if plan is None else plan.songs_left
        others = [order for order in self.open_orders if order != exclude_order_id]
        return ok(
            CreditBalance(
                telegram_user_id=telegram_user_id,
                # The projection ``credit_sql.read_balance`` performs: a live plan's
                # unminted songs count as spendable, because the charge will mint one.
                credits=self.purchases.credits + plan_left,
                in_flight=len(others),
                is_blocked=self.is_blocked,
                plan_songs_left=plan_left,
                plan_ends_at=None if plan is None else plan.ends_at,
            )
        )


def selling(
    settings: Settings,
    submitter: RecordingSubmitter,
    clock: Callable[[], datetime],
    purchases: FakePurchases,
    *,
    checkout: CheckoutProvider | None = None,
    meter: LinkedMeter | None = None,
) -> BotDeps:
    """A deployment that sells: a purchase store, a price list and a checkout rail.

    ``credits_enforced`` is deliberately left at its shipped default of False. The paywall
    does NOT consult that flag — it governs whether the WORKER refuses a render, while the
    paywall is the product — and leaving it off here is what proves that: every assertion
    below about a price on screen holds on a deployment whose credit gate is dark.

    ``meter`` overrides the linked one for the tests that need a meter which BREAKS partway
    through. It is typed as the linked meter rather than as the protocol so that a substitute
    still has to read the same account the purchase store writes: an unlinked one would let a
    test buy a song, watch the balance stay at zero and call the paywall proven.
    """
    return BotDeps(
        settings=settings,
        submitter=submitter,
        content=RecordingContentWriter(),
        clock=clock,
        entitlements=meter or LinkedMeter(purchases),
        profiles=FakeProfiles(),
        checkout=checkout or RecordingCheckout(),
        purchases=purchases,
        pricing=Pricing.from_settings(settings),
    )


def not_selling(
    settings: Settings,
    submitter: RecordingSubmitter,
    clock: Callable[[], datetime],
    purchases: FakePurchases,
) -> BotDeps:
    """The same meter and the same empty account, with no way to sell anything.

    The control for the byte-identical-screen property. It wires the meter so the two screens
    differ in exactly one thing — whether this deployment can take money — rather than in
    whether a balance exists at all.
    """
    return BotDeps(
        settings=settings,
        submitter=submitter,
        content=RecordingContentWriter(),
        clock=clock,
        entitlements=LinkedMeter(purchases),
        profiles=FakeProfiles(),
    )


def screen_texts(session: RecordingSession) -> str:
    """Everything put in front of the customer, sent or edited, as one string."""
    return " ".join(call.text or "" for call in session.calls if hasattr(call, "text"))


async def test_the_two_fakes_satisfy_the_protocols_they_stand_for() -> None:
    """A drifted fake is a green suite over a port nothing implements.

    ``runtime_checkable`` verifies member PRESENCE only and never signatures, so this catches
    a deleted method and ``mypy --strict`` over ``tests`` catches the rest — which is why the
    two assignments below are annotated rather than left bare.
    """
    # Arrange / Act
    store: PurchaseFulfiller = FakePurchases()
    rail: CheckoutProvider = RecordingCheckout()

    # Assert
    assert isinstance(store, PurchaseFulfiller)
    assert isinstance(rail, CheckoutProvider)


async def test_an_account_with_no_credits_is_offered_prices_instead_of_a_record_button(
    settings: Settings,
    bot: Bot,
    session: RecordingSession,
    storage: MemoryStorage,
    submitter: RecordingSubmitter,
    clock: Callable[[], datetime],
    purchases: FakePurchases,
) -> None:
    """The structural half of "no render is queued unpaid": the button is simply not drawn."""
    # Arrange
    dispatcher = build_dispatcher(selling(settings, submitter, clock, purchases), storage=storage)

    # Act
    await walk_to_confirm(dispatcher, bot)

    # Assert — one price button and no Record it. SUBSCRIBE is absent because the shipped
    # catalogue withdrew the plan on 2026-09-14 (`Settings.is_starter_plan_offered` is False);
    # the test below re-enables it and asserts the button comes back, so this assertion is
    # about the shipped product rather than about the button having been deleted.
    offered = {data for _text, data in buttons(session.last_screen.reply_markup)}
    assert PAY in offered
    assert SUBSCRIBE not in offered
    assert CONFIRM not in offered
    assert submitter.submitted == []


async def test_a_deployment_that_still_sells_the_plan_draws_its_button(
    settings: Settings,
    bot: Bot,
    session: RecordingSession,
    storage: MemoryStorage,
    submitter: RecordingSubmitter,
    clock: Callable[[], datetime],
    purchases: FakePurchases,
) -> None:
    """The plan path is withdrawn, not deleted, and this is what keeps it exercised.

    `is_plan_offered` is an AND of two things — the deployment sells the plan, and this
    customer has none running. Without this test the first half could be hard-coded to False
    and every remaining assertion would still pass.
    """
    # Arrange
    selling_plans = settings.model_copy(update={"is_starter_plan_offered": True})
    dispatcher = build_dispatcher(
        selling(selling_plans, submitter, clock, purchases), storage=storage
    )

    # Act
    await walk_to_confirm(dispatcher, bot)

    # Assert
    offered = {data for _text, data in buttons(session.last_screen.reply_markup)}
    assert PAY in offered
    assert SUBSCRIBE in offered
    assert CONFIRM not in offered


async def test_the_paywall_says_the_words_are_free_and_names_the_price(
    settings: Settings,
    bot: Bot,
    session: RecordingSession,
    storage: MemoryStorage,
    submitter: RecordingSubmitter,
    clock: Callable[[], datetime],
    purchases: FakePurchases,
) -> None:
    """The copy is the product decision, so it is asserted rather than assumed.

    The customer has already been given something — the lyric — and the screen has to say so,
    or a price arriving after a free preview reads as a bait.
    """
    # Arrange
    pricing = Pricing.from_settings(settings)
    dispatcher = build_dispatcher(selling(settings, submitter, clock, purchases), storage=storage)

    # Act
    await walk_to_confirm(dispatcher, bot)

    # Assert — `paywall_single`, not `paywall_topup`. The distinction is the point: this
    # customer has no plan because the deployment sells none, and the top-up wording would
    # tell them *their* plan has no songs left on it, inventing a purchase they never made.
    expected = translate(
        "checkout.paywall_single",
        Language.EN,
        single_amount=pricing.single_amount,
    )
    assert session.last_screen.text == expected
    assert pricing.plan_amount not in session.last_screen.text


async def test_a_customer_who_can_afford_a_song_sees_the_confirm_screen_unchanged(
    settings: Settings,
    bot: Bot,
    session: RecordingSession,
    storage: MemoryStorage,
    submitter: RecordingSubmitter,
    clock: Callable[[], datetime],
    purchases: FakePurchases,
) -> None:
    """The paywall is a face, not a step. With a credit in hand nothing about it appears."""
    # Arrange
    purchases.credits = 1
    dispatcher = build_dispatcher(selling(settings, submitter, clock, purchases), storage=storage)

    # Act
    await walk_to_confirm(dispatcher, bot)

    # Assert
    offered = {data for _text, data in buttons(session.last_screen.reply_markup)}
    assert CONFIRM in offered
    assert PAY not in offered
    assert SUBSCRIBE not in offered


async def test_a_deployment_that_sells_nothing_draws_the_screen_it_drew_yesterday(
    settings: Settings,
    bot: Bot,
    storage: MemoryStorage,
    submitter: RecordingSubmitter,
    clock: Callable[[], datetime],
) -> None:
    """The property the other thirty ``BotDeps(`` sites in this suite rest on.

    Both deployments have the SAME empty account behind the same meter, and the account
    cannot afford a render in either. The only difference is whether ``purchases`` and
    ``pricing`` are wired — so the screens are compared as STRINGS, and any difference at all
    is the checkout leaking into a deployment that does not sell.

    The comparison is against a deployment that also wires a credit-buying customer's own
    second run, rather than against a hard-coded expected string, because the point is not
    what the summary says: it is that this change did not move it.
    """
    # Arrange — one dispatcher that could sell but is handed a customer with a credit, and
    # one that cannot sell at all. Both must draw the ordinary summary.
    quiet = RecordingSession()
    quiet_bot = Bot(token=bot.token, session=quiet, default=bot.default)
    loud = RecordingSession()
    loud_bot = Bot(token=bot.token, session=loud, default=bot.default)
    await walk_to_confirm(
        build_dispatcher(
            not_selling(settings, submitter, clock, FakePurchases()), storage=MemoryStorage()
        ),
        quiet_bot,
    )

    # Act
    await walk_to_confirm(
        build_dispatcher(
            selling(settings, submitter, clock, FakePurchases(credits=1)), storage=storage
        ),
        loud_bot,
    )

    # Assert — the ordinary summary, with no price and a working Confirm button, both times
    assert quiet.last_screen.text == loud.last_screen.text
    assert buttons(quiet.last_screen.reply_markup) == buttons(loud.last_screen.reply_markup)
    assert {data for _text, data in buttons(quiet.last_screen.reply_markup)} == {
        CONFIRM,
        NavCB(action=NavAction.BACK).pack(),
        NavCB(action=NavAction.CANCEL).pack(),
    }
    assert "UZS" not in quiet.last_screen.text


async def test_paying_for_one_song_grants_one_credit_and_leaves_the_customer_on_confirm(
    settings: Settings,
    bot: Bot,
    session: RecordingSession,
    storage: MemoryStorage,
    submitter: RecordingSubmitter,
    state: FSMContext,
    clock: Callable[[], datetime],
    purchases: FakePurchases,
) -> None:
    """One press, one key, one credit — and a screen that now carries 🎬 Record it.

    Paying deliberately does not queue anything: the customer presses Confirm themselves on
    the redrawn screen, which is why the redraw is asserted here and not merely the message.
    """
    # Arrange
    dispatcher = build_dispatcher(selling(settings, submitter, clock, purchases), storage=storage)
    await walk_to_confirm(dispatcher, bot)

    # Act
    await press(dispatcher, bot, PAY)

    # Assert
    assert len(purchases.grants) == 1
    assert purchases.credits == 1
    assert translate("checkout.paid_single", Language.EN, credits=1) in screen_texts(session)
    assert CONFIRM in {data for _text, data in buttons(session.last_screen.reply_markup)}
    assert await state.get_state() == Wizard.confirm.state
    assert submitter.submitted == []


async def test_two_taps_in_one_batch_buy_exactly_one_song(
    settings: Settings,
    bot: Bot,
    storage: MemoryStorage,
    state: FSMContext,
    submitter: RecordingSubmitter,
    clock: Callable[[], datetime],
    purchases: FakePurchases,
) -> None:
    """Two taps delivered in one ``getUpdates`` batch, with the rail parked between them.

    **The per-chat lock is not the defence here, and that is worth stating precisely, because
    it is not what a reader coming from ``test_submitting.py`` will expect.**
    ``build_dispatcher`` wires an event isolation that serialises one chat's updates
    COMPLETELY: the second tap's filters are not evaluated until the first tap's handler has
    returned. So the second tap never observes ``Wizard.submitting`` — the ``finally`` has
    already restored ``Wizard.confirm`` — and the state filter that sheds a concurrent tap
    sheds nothing at all. Ordering the two taps perfectly is exactly what makes them two
    fully formed intents, each with its own counter value and its own key.

    That used to be the shipped behaviour and it was documented as intended, on the grounds
    that top-ups on top of top-ups are the decided product. It is intended for a customer who
    MEANT it; it is not intended for a thumb that bounced, and on the Payme rail this seam
    exists for, a bounce would take 14 000 UZS for one song. So the second tap is now
    swallowed by the double-tap window and the assertions say so directly: one request
    reached the rail, one grant reached the ledger, one credit reached the customer.

    The deliberate second purchase is the next-but-one test, and it differs from this one in
    exactly one thing: the clock has moved.
    """
    # Arrange
    rail = GatedCheckout()
    deps = selling(settings, submitter, clock, purchases, checkout=rail)
    dispatcher = build_dispatcher(deps, storage=storage)
    await walk_to_confirm(dispatcher, bot)

    # Act — both taps enter before either is dispatched, which is what one ``getUpdates``
    # batch delivers.
    first = asyncio.create_task(dispatcher.feed_update(bot, callback_update(PAY)))
    second = asyncio.create_task(dispatcher.feed_update(bot, callback_update(PAY)))
    await _settle()
    rail.gate.set()
    await asyncio.gather(first, second)

    # Assert — the second tap never reached the rail, so nothing could be charged for it
    assert [request.idempotency_key for request in rail.requests] == purchases.grants
    assert len(rail.requests) == 1
    assert purchases.credits == 1
    assert await state.get_state() == Wizard.confirm.state


async def test_a_redelivered_update_that_already_settled_never_buys_a_second_song(
    settings: Settings,
    bot: Bot,
    storage: MemoryStorage,
    state: FSMContext,
    submitter: RecordingSubmitter,
    purchases: FakePurchases,
) -> None:
    """The gap the idempotency key could not see, driven as the thing that actually happens.

    Telegram redelivers from the last confirmed offset, so a bot that completed a purchase —
    grant written, counter bumped — and then died before ``getUpdates`` confirmed the offset
    gets the IDENTICAL callback again. The key is derived from the counter, and the counter
    moved, so the replayed update mints a string the ledger has never written and the unique
    index waves it through: one intent, two songs, and on a real rail two charges.

    The same ``Update`` object is fed twice, which is exactly what a redelivery is. The clock
    is pushed well past the double-tap window first, so the ONLY thing that can catch the
    second delivery is the settled-update memory — if it were caught by the time window
    instead, this test would pass without testing anything, which is the failure mode that
    made it worth writing the clock helper.
    """
    # Arrange
    clock = MovingClock()
    dispatcher = build_dispatcher(selling(settings, submitter, clock, purchases), storage=storage)
    await walk_to_confirm(dispatcher, bot)
    replayed = callback_update(PAY)
    await dispatcher.feed_update(bot, replayed)
    assert purchases.credits == 1

    # Act — the same update, arriving again long after the window would have closed
    clock.advance(DOUBLE_TAP_WINDOW * 10)
    await dispatcher.feed_update(bot, replayed)

    # Assert — the rail was never asked a second time and the balance did not move
    assert len(purchases.grants) == 1
    assert purchases.credits == 1
    assert await state.get_state() == Wizard.confirm.state


async def test_a_replayed_key_is_handed_to_the_store_twice_and_moves_the_balance_once(
    purchases: FakePurchases,
) -> None:
    """The last line: a key that reaches the store twice may only ever grant once.

    A redelivered Telegram update or a bot process restarted mid-charge can reach the
    fulfiller with a key it has already written, and the tap-level defences above are both
    gone by then. What is left is the unique index on ``idempotency_key`` — which
    ``FakePurchases`` stands for here — so this asserts the property directly rather than
    through a dispatcher that cannot reproduce the cause.
    """
    # Arrange
    paid = await RecordingCheckout().charge(
        PurchaseRequest(
            telegram_user_id=USER_ID,
            product=Product.SINGLE,
            amount_minor=700_000,
            currency="UZS",
            idempotency_key="topup:1:s:0",
        )
    )
    assert not isinstance(paid, Err)

    # Act
    for _ in range(2):
        settled = await purchases.fulfil_single(
            telegram_user_id=USER_ID, purchase=paid.value, idempotency_key="topup:1:s:0"
        )
        assert not isinstance(settled, Err)

    # Assert — two calls, one key, one credit
    assert len(purchases.grants) == 2
    assert len(set(purchases.grants)) == 1
    assert purchases.credits == 1


async def test_buying_a_second_song_after_the_first_settled_uses_a_fresh_key(
    settings: Settings,
    bot: Bot,
    storage: MemoryStorage,
    state: FSMContext,
    submitter: RecordingSubmitter,
    purchases: FakePurchases,
) -> None:
    """Buy-as-many-as-you-like has to work, or the double-tap guard becomes a purchase cap.

    The distinction from the double tap above is the counter AND the clock, and both halves
    are load-bearing. The counter moved because the first write succeeded, so the second
    press is a genuinely different purchase and gets a genuinely different key; and the
    clock has moved past the double-tap window, which is what tells the handler that this is
    a customer who read the receipt and came back rather than a thumb that bounced.

    Moving the clock is not a workaround for the guard, it is the test saying which of the
    two cases it means. The window is measured from the moment the previous purchase
    SETTLED, so pushing it past that moment is exactly the customer behaviour this test
    stands for — and a build that dropped the guard entirely would still pass here, which is
    why the bounce has a test of its own rather than sharing this one.
    """
    # Arrange
    clock = MovingClock()
    dispatcher = build_dispatcher(selling(settings, submitter, clock, purchases), storage=storage)
    await walk_to_confirm(dispatcher, bot)
    await press(dispatcher, bot, PAY)

    # Act — the screen has been redrawn with Confirm on it; come back and press Pay again
    clock.advance(DOUBLE_TAP_WINDOW + 1)
    await press(dispatcher, bot, PAY)

    # Assert
    assert len(set(purchases.grants)) == 2
    assert purchases.credits == 2
    assert (await state.get_data())[PURCHASE_SEQ_KEY] == 2


async def test_subscribing_opens_a_plan_and_redraws_the_screen_with_record_it_on_it(
    settings: Settings,
    bot: Bot,
    session: RecordingSession,
    storage: MemoryStorage,
    state: FSMContext,
    submitter: RecordingSubmitter,
    clock: Callable[[], datetime],
    purchases: FakePurchases,
) -> None:
    """A plan grants no credits, and the customer can still order — that is the lazy mint.

    ``read_balance`` projects a live plan's unminted songs into the balance, so the read-only
    gate agrees with what the worker's charge will do. Without that projection this screen
    would paywall a customer in the same breath as thanking them for subscribing.
    """
    # Arrange
    dispatcher = build_dispatcher(selling(settings, submitter, clock, purchases), storage=storage)
    await walk_to_confirm(dispatcher, bot)

    # Act
    await press(dispatcher, bot, SUBSCRIBE)

    # Assert
    assert len(purchases.plans) == 1
    assert purchases.credits == 0
    expected = translate(
        "checkout.paid_plan",
        Language.EN,
        songs=settings.starter_plan_songs,
        ends_on=FAKE_PLAN_ENDS_AT.date().isoformat(),
    )
    assert expected in screen_texts(session)
    assert CONFIRM in {data for _text, data in buttons(session.last_screen.reply_markup)}
    assert await state.get_state() == Wizard.confirm.state


async def test_a_spent_plan_is_offered_the_single_song_and_never_a_second_plan(
    settings: Settings,
    bot: Bot,
    session: RecordingSession,
    storage: MemoryStorage,
    submitter: RecordingSubmitter,
    clock: Callable[[], datetime],
    purchases: FakePurchases,
) -> None:
    """Selling a second plan would overwrite an end date the customer has already paid for.

    So the button that would take that money is not drawn, and the copy says what is actually
    true: the plan brings nothing more until it ends.
    """
    # Arrange — a plan that is running and has nothing left on it
    dispatcher = build_dispatcher(selling(settings, submitter, clock, purchases), storage=storage)
    await walk_to_confirm(dispatcher, bot)
    await press(dispatcher, bot, SUBSCRIBE)
    plan = purchases.plan
    assert plan is not None
    purchases.plan = type(plan)(
        plan=plan.plan,
        songs_included=plan.songs_included,
        songs_used=plan.songs_included,
        ends_at=plan.ends_at,
    )

    # Act — come back to the Confirm screen with the plan spent
    await press(dispatcher, bot, NavCB(action=NavAction.BACK).pack())
    await press(dispatcher, bot, NavCB(action=NavAction.LYRICS_OK).pack())

    # Assert
    offered = {data for _text, data in buttons(session.last_screen.reply_markup)}
    assert PAY in offered
    assert SUBSCRIBE not in offered
    assert session.last_screen.text == translate(
        "checkout.paywall_topup",
        Language.EN,
        single_amount=Pricing.from_settings(settings).single_amount,
    )


async def test_a_rail_that_does_not_settle_grants_nothing_and_says_nothing_was_charged(
    settings: Settings,
    bot: Bot,
    session: RecordingSession,
    storage: MemoryStorage,
    state: FSMContext,
    submitter: RecordingSubmitter,
    clock: Callable[[], datetime],
    purchases: FakePurchases,
) -> None:
    """An unpaid receipt is the NORMAL answer from a redirect rail, not an exotic failure.

    Granting against one would hand out a free song for every abandoned checkout, so the
    handler stops before the fulfiller — ``grants`` is empty, not merely un-settled.
    """
    # Arrange
    rail = RecordingCheckout(is_paid=False)
    deps = selling(settings, submitter, clock, purchases, checkout=rail)
    dispatcher = build_dispatcher(deps, storage=storage)
    await walk_to_confirm(dispatcher, bot)

    # Act
    await press(dispatcher, bot, PAY)

    # Assert
    assert rail.requests != []
    assert purchases.grants == []
    assert translate("checkout.failed", Language.EN) in screen_texts(session)
    assert await state.get_state() == Wizard.confirm.state


async def test_a_store_that_cannot_write_says_why_in_the_customers_language_and_holds_the_key(
    settings: Settings,
    bot: Bot,
    session: RecordingSession,
    storage: MemoryStorage,
    state: FSMContext,
    submitter: RecordingSubmitter,
    clock: Callable[[], datetime],
) -> None:
    """Money moved and the write failed, so "nothing was charged" would be a lie.

    The typed error is rendered instead, and the counter does NOT move — so the customer's
    next press retries the same key against the same unique index and can only ever produce
    one grant, however many times it happens.
    """
    # Arrange
    purchases = FakePurchases(failure=StorageError("the ledger is unavailable"))
    dispatcher = build_dispatcher(selling(settings, submitter, clock, purchases), storage=storage)
    await walk_to_confirm(dispatcher, bot)

    # Act
    await press(dispatcher, bot, PAY)

    # Assert
    assert purchases.credits == 0
    assert translate(StorageError("x").user_message_key, Language.EN) in screen_texts(session)
    assert PURCHASE_SEQ_KEY not in await state.get_data()
    assert await state.get_state() == Wizard.confirm.state


async def test_the_paywall_speaks_the_language_the_customer_chose(
    settings: Settings,
    bot: Bot,
    session: RecordingSession,
    storage: MemoryStorage,
    submitter: RecordingSubmitter,
    clock: Callable[[], datetime],
    purchases: FakePurchases,
) -> None:
    """A price screen in the wrong language is the one screen nobody guesses their way through."""
    # Arrange
    dispatcher = build_dispatcher(selling(settings, submitter, clock, purchases), storage=storage)
    await complete_onboarding(dispatcher, bot, language=Language.RU)

    # Act
    await tap(dispatcher, bot, "menu.balance", Language.RU)

    # Assert
    assert translate("credits.balance_metered", Language.RU, credits=0) in screen_texts(session)
    assert PAY in {data for _text, data in buttons(session.last_screen.reply_markup)}


async def test_a_stale_confirm_button_cannot_queue_a_render_it_cannot_pay_for(
    settings: Settings,
    bot: Bot,
    session: RecordingSession,
    storage: MemoryStorage,
    state: FSMContext,
    submitter: RecordingSubmitter,
    clock: Callable[[], datetime],
    purchases: FakePurchases,
) -> None:
    """The second line of the defence, for the screen this build did not draw.

    The customer reaches Confirm with a credit, the credit disappears underneath them — a
    song ordered from another device, an operator adjustment — and they press the button they
    are still holding. Nothing is queued and they land back on the buy screen.
    """
    # Arrange
    purchases.credits = 1
    dispatcher = build_dispatcher(selling(settings, submitter, clock, purchases), storage=storage)
    await walk_to_confirm(dispatcher, bot)
    purchases.credits = 0

    # Act
    await press(dispatcher, bot, CONFIRM)

    # Assert
    assert submitter.submitted == []
    offered = {data for _text, data in buttons(session.last_screen.reply_markup)}
    assert PAY in offered
    assert CONFIRM not in offered
    assert await state.get_state() == Wizard.confirm.state


async def test_no_purchase_path_leaves_the_session_parked_in_submitting(
    settings: Settings,
    bot: Bot,
    storage: MemoryStorage,
    state: FSMContext,
    submitter: RecordingSubmitter,
) -> None:
    """``Wizard.submitting`` has exactly one other un-parker, and it runs only from a job.

    So a checkout that returned while parked there would strand the customer behind
    ``handlers.submitting`` forever, with every button on their screen refused. Each of the
    four exits is driven here and the state is read after every one.

    The clock is pushed past the double-tap window between the two presses, so the 🌟 press
    genuinely reaches the rail instead of being swallowed as a bounce off the 💳 before it.
    Without that this would still go green while exercising half of what it names — the
    swallow has its own ``finally`` to run through, but it is not the plan exit.
    """
    # Arrange
    clock = MovingClock()
    failing = FakePurchases(failure=StorageError("down"))
    unpaid = RecordingCheckout(is_paid=False)
    cases = (
        selling(settings, submitter, clock, FakePurchases()),
        selling(settings, submitter, clock, failing),
        selling(settings, submitter, clock, FakePurchases(), checkout=unpaid),
    )

    # Act / Assert
    for deps in cases:
        dispatcher = build_dispatcher(deps, storage=MemoryStorage())
        fresh = FSMContext(storage=dispatcher.storage, key=state.key)
        await walk_to_confirm(dispatcher, bot)
        await press(dispatcher, bot, PAY)
        clock.advance(DOUBLE_TAP_WINDOW + 1)
        await press(dispatcher, bot, SUBSCRIBE)
        assert await fresh.get_state() == Wizard.confirm.state


# ---------------------------------------------------------------------------
# The second surface: the buttons drawn on /balance
# ---------------------------------------------------------------------------
async def balance_screen(dispatcher: Dispatcher, bot: Bot, session: RecordingSession) -> None:
    """Onboard, then ask for the balance, so the two purchase buttons are on screen.

    Through ``/balance`` rather than through the 🎫 menu button because the command is the
    surface with no state at all behind it: ``complete_onboarding`` leaves the FSM cleared,
    which is precisely the state in which every purchase button used to be dead.
    """
    await complete_onboarding(dispatcher, bot, language=Language.EN)
    session.clear()
    await send(dispatcher, bot, "/balance")
    assert PAY in {data for _text, data in buttons(session.last_screen.reply_markup)}


async def test_the_buy_button_on_the_balance_screen_actually_buys(
    settings: Settings,
    bot: Bot,
    session: RecordingSession,
    storage: MemoryStorage,
    state: FSMContext,
    submitter: RecordingSubmitter,
    clock: Callable[[], datetime],
    purchases: FakePurchases,
) -> None:
    """The defect this whole surface exists to keep fixed, driven end to end.

    ``/balance`` draws 💳 and 🌟 whenever the account cannot afford a render, in any FSM
    state and in none. Both handlers were registered behind a ``Wizard.confirm`` filter, so
    outside the wizard the press fell all the way through to ``fallback.handle_stale_callback``
    and the customer was toasted "that session expired" and left holding nothing — the
    customer who had just opened ``/balance`` to find out they had run out, which is the one
    most likely to want to buy.

    So this asserts the money, not the screen: a grant, a credit, and NOT the expiry text
    that was the whole symptom.
    """
    # Arrange
    dispatcher = build_dispatcher(selling(settings, submitter, clock, purchases), storage=storage)
    await balance_screen(dispatcher, bot, session)

    # Act
    await press(dispatcher, bot, PAY)

    # Assert
    assert len(purchases.grants) == 1
    assert purchases.credits == 1
    assert translate("wizard.expired", Language.EN) not in screen_texts(session)
    assert translate("checkout.paid_single", Language.EN, credits=1) in screen_texts(session)
    assert await state.get_state() is None


async def test_a_purchase_from_the_balance_screen_retires_the_price_and_offers_the_next_step(
    settings: Settings,
    bot: Bot,
    session: RecordingSession,
    storage: MemoryStorage,
    submitter: RecordingSubmitter,
    clock: Callable[[], datetime],
    purchases: FakePurchases,
) -> None:
    """Paying must not leave the customer on a screen with nowhere to go.

    Two things have to happen and neither is the receipt. The balance message is EDITED in
    place, so the price the customer has just paid is gone from the message they are looking
    at rather than sitting there to be pressed again; and because a purchase made between
    flows ends on a screen with no button of its own, the menu is put underneath it — which
    is where 🎵 Make a song lives, and is the thing somebody who has just bought a song
    wants next.
    """
    # Arrange
    dispatcher = build_dispatcher(selling(settings, submitter, clock, purchases), storage=storage)
    await balance_screen(dispatcher, bot, session)

    # Act
    await press(dispatcher, bot, PAY)

    # Assert — the edited balance carries the new count and no price at all
    edited = session.last_named("EditMessageText")
    assert translate("credits.balance_metered", Language.EN, credits=1) in (edited.text or "")
    assert buttons(edited.reply_markup) == ()
    assert translate("menu.prompt", Language.EN) in screen_texts(session)


async def test_the_plan_button_on_the_balance_screen_opens_a_plan(
    settings: Settings,
    bot: Bot,
    session: RecordingSession,
    storage: MemoryStorage,
    submitter: RecordingSubmitter,
    clock: Callable[[], datetime],
    purchases: FakePurchases,
) -> None:
    """🌟 was dead outside the wizard for the same reason 💳 was, so it is proven separately.

    One registration per button, and a fix that wired only the one the bug report named
    would leave the more expensive button broken.
    """
    # Arrange
    dispatcher = build_dispatcher(selling(settings, submitter, clock, purchases), storage=storage)
    await balance_screen(dispatcher, bot, session)

    # Act
    await press(dispatcher, bot, SUBSCRIBE)

    # Assert
    assert len(purchases.plans) == 1
    expected = translate(
        "checkout.paid_plan",
        Language.EN,
        songs=settings.starter_plan_songs,
        ends_on=FAKE_PLAN_ENDS_AT.date().isoformat(),
    )
    assert expected in screen_texts(session)


async def test_buying_from_the_balance_screen_mid_wizard_leaves_the_draft_where_it_was(
    settings: Settings,
    bot: Bot,
    session: RecordingSession,
    storage: MemoryStorage,
    state: FSMContext,
    submitter: RecordingSubmitter,
    clock: Callable[[], datetime],
    purchases: FakePurchases,
) -> None:
    """``/balance`` answers mid-wizard, so its buttons are pressed mid-wizard too.

    That is the reason this surface may not borrow the wizard handler's defence: flipping the
    FSM state of somebody who is three screens into a draft would lose them the step they
    were answering, to a button they pressed in order to buy the song that draft is FOR. The
    state is read after the purchase and must be exactly where the walk left it, and the
    menu — which is the right landing for a purchase made between flows — must not be drawn
    over a live wizard screen.
    """
    # Arrange
    dispatcher = build_dispatcher(selling(settings, submitter, clock, purchases), storage=storage)
    await walk_to_name(dispatcher, bot)
    parked = await state.get_state()
    assert parked == Wizard.name.state
    session.clear()
    await send(dispatcher, bot, "/balance")

    # Act
    await press(dispatcher, bot, PAY)

    # Assert
    assert purchases.credits == 1
    assert await state.get_state() == parked
    assert translate("menu.prompt", Language.EN) not in screen_texts(session)


async def test_a_bounced_thumb_on_the_balance_screen_buys_one_song_and_not_two(
    settings: Settings,
    bot: Bot,
    session: RecordingSession,
    storage: MemoryStorage,
    submitter: RecordingSubmitter,
    purchases: FakePurchases,
) -> None:
    """The double-tap guard has to hold on the surface with no FSM state to flip.

    The wizard handler sheds a concurrent tap by moving out from under its own state filter.
    This one cannot — it must not touch a mid-wizard session's state — so the window is the
    only thing standing between a bounced thumb and 14 000 UZS. Two presses under a frozen
    clock is what a bounce looks like from inside the handler.
    """
    # Arrange
    clock = MovingClock()
    dispatcher = build_dispatcher(selling(settings, submitter, clock, purchases), storage=storage)
    await balance_screen(dispatcher, bot, session)

    # Act
    await press(dispatcher, bot, PAY)
    await press(dispatcher, bot, PAY)

    # Assert
    assert len(purchases.grants) == 1
    assert purchases.credits == 1


async def test_a_purchase_button_pressed_on_a_deployment_that_cannot_sell_says_so(
    settings: Settings,
    bot: Bot,
    session: RecordingSession,
    storage: MemoryStorage,
    submitter: RecordingSubmitter,
    clock: Callable[[], datetime],
    purchases: FakePurchases,
) -> None:
    """A stale price button on a bot that has since stopped selling. Say it, do not toast it.

    The wizard-less registrations claim every state, so they also claim the press that used
    to be answered by the fallback router. That means this branch is now reachable from a
    screen the customer kept, and it has to answer with the checkout's own sentence rather
    than with "your session expired" — which was never true and which is the copy this whole
    surface was rescued from.
    """
    # Arrange — the price screen is drawn by a selling dispatcher, then pressed against one
    # that wires no purchase store at all.
    selling_dispatcher = build_dispatcher(
        selling(settings, submitter, clock, purchases), storage=storage
    )
    await balance_screen(selling_dispatcher, bot, session)
    withdrawn = build_dispatcher(
        not_selling(settings, submitter, clock, purchases), storage=storage
    )

    # Act
    session.clear()
    await press(withdrawn, bot, PAY)

    # Assert
    assert purchases.grants == []
    assert translate("checkout.unavailable", Language.EN) in screen_texts(session)
    assert translate("wizard.expired", Language.EN) not in screen_texts(session)


# ---------------------------------------------------------------------------
# The paywall when the meter cannot be read at all
# ---------------------------------------------------------------------------
class FlakyMeter(LinkedMeter):
    """A meter that answers happily and then stops, from the ``fails_from``-th read on.

    ``handlers.confirm`` reads the meter TWICE on a selling deployment — once for the
    business refusals and once for the paywall — and a fake that failed from the first read
    can only ever drive the first of the two gates. This one can park the failure between
    them, which is the only way to exercise the second: with ``credits_enforced`` off, a
    zero-credit account sails through the first gate, so a second read that failed silently
    was a free render on an empty account.
    """

    def __init__(self, purchases: FakePurchases, *, healthy_gate_reads: int) -> None:
        super().__init__(purchases)
        #: How many of the CONFIRM GATE's reads answer before the meter goes down.
        self.healthy_gate_reads = healthy_gate_reads
        #: Gate reads seen so far. The assertion that the second gate really ran.
        self.gate_reads = 0

    async def balance_for(
        self, telegram_user_id: int, *, exclude_order_id: UUID | None = None
    ) -> Result[CreditBalance]:
        # Counted on ``exclude_order_id``, which is the one thing that tells the gate's reads
        # apart from everybody else's. ``InboundGateMiddleware`` reads this meter for the
        # block flag on EVERY update and ``show_confirm`` reads it on every redraw, both with
        # no order to exclude — counting raw calls would make "which read fails" a function
        # of how many screens the walker drew, which is a number no assertion should rest on.
        if exclude_order_id is not None:
            self.gate_reads += 1
            if self.gate_reads > self.healthy_gate_reads:
                self.failure = StorageError("the meter is down")
        return await super().balance_for(telegram_user_id, exclude_order_id=exclude_order_id)


async def test_a_paid_render_is_never_queued_because_the_meter_could_not_be_read(
    settings: Settings,
    bot: Bot,
    session: RecordingSession,
    storage: MemoryStorage,
    state: FSMContext,
    submitter: RecordingSubmitter,
    clock: Callable[[], datetime],
    purchases: FakePurchases,
) -> None:
    """The paywall used to fail OPEN, and on the shipped configuration that was a free song.

    ``build_offer`` answers ``None`` for a failed read, so the Confirm screen kept its
    ordinary summary and its 🎬 Record it button; the second-line check read the same failing
    meter through the same helper and also said "not paywalled"; and because
    ``BAYRAM_CREDITS_ENFORCED`` ships false, the worker covers the shortfall with an
    ``UNENFORCED_RENDER`` grant and sings. One unreadable row, one 7 000 UZS render given
    away — with the customer's balance untouched, so nobody could even tell afterwards.

    The meter is broken AFTER the walk, which is what actually happens: the screen is drawn
    from a database that was up and pressed against one that is not. Note ``credits`` on the
    account is 1 — this customer could afford the render — so a build that refused them by
    calling it "no credits" would be lying about a number it could not read, and the
    assertion on the copy is what pins that.
    """
    # Arrange
    purchases.credits = 1
    deps = selling(settings, submitter, clock, purchases)
    dispatcher = build_dispatcher(deps, storage=storage)
    await walk_to_confirm(dispatcher, bot)
    assert CONFIRM in {data for _text, data in buttons(session.last_screen.reply_markup)}
    meter = deps.entitlements
    assert isinstance(meter, LinkedMeter)
    meter.failure = StorageError("the meter is down")

    # Act
    session.clear()
    await press(dispatcher, bot, CONFIRM)

    # Assert — nothing queued, an honest sentence, and the customer still on Confirm
    assert submitter.submitted == []
    assert translate(StorageError("x").user_message_key, Language.EN) in screen_texts(session)
    assert translate("error.credits_exhausted", Language.EN) not in screen_texts(session)
    assert await state.get_state() == Wizard.confirm.state


async def test_a_meter_that_fails_only_on_the_second_read_still_refuses(
    settings: Settings,
    bot: Bot,
    session: RecordingSession,
    storage: MemoryStorage,
    state: FSMContext,
    submitter: RecordingSubmitter,
    clock: Callable[[], datetime],
    purchases: FakePurchases,
) -> None:
    """Two reads means two chances to fail, and the second one used to be the unguarded one.

    Fixing only the first gate would leave this: the business refusals never look at the
    balance while ``credits_enforced`` is off, so a zero-credit account passes read one, and
    read two returning ``Err`` used to collapse into "not paywalled". A render nobody paid
    for, queued.
    """
    # Arrange — a credit in hand, so read one passes the business gate on its own terms, and
    # a meter that dies immediately afterwards.
    purchases.credits = 1
    meter = FlakyMeter(purchases, healthy_gate_reads=1)
    dispatcher = build_dispatcher(
        selling(settings, submitter, clock, purchases, meter=meter), storage=storage
    )
    await walk_to_confirm(dispatcher, bot)

    # Act
    session.clear()
    await press(dispatcher, bot, CONFIRM)

    # Assert
    assert meter.gate_reads == 2, "the first gate must have passed and the second must have run"
    assert submitter.submitted == []
    assert translate(StorageError("x").user_message_key, Language.EN) in screen_texts(session)
    assert await state.get_state() == Wizard.confirm.state


async def test_a_deployment_that_sells_nothing_still_fails_open_on_an_unreadable_meter(
    settings: Settings,
    bot: Bot,
    storage: MemoryStorage,
    submitter: RecordingSubmitter,
    clock: Callable[[], datetime],
    purchases: FakePurchases,
) -> None:
    """The old fail-open is still right where nothing has been paid for, and it is kept.

    With no purchase store the worker's gate really is the defence — it reads the same rows
    inside the transaction that charges — so refusing every order in the product because one
    read failed would be an outage bought for nothing. The change is scoped to deployments
    that SELL, and this is the assertion that keeps it scoped.
    """
    # Arrange
    deps = not_selling(settings, submitter, clock, purchases)
    dispatcher = build_dispatcher(deps, storage=storage)
    await walk_to_confirm(dispatcher, bot)
    meter = deps.entitlements
    assert isinstance(meter, LinkedMeter)
    meter.failure = StorageError("the meter is down")

    # Act
    await press(dispatcher, bot, CONFIRM)

    # Assert
    assert len(submitter.submitted) == 1


async def test_an_unreadable_meter_never_puts_a_price_in_front_of_the_customer(
    settings: Settings,
    bot: Bot,
    session: RecordingSession,
    storage: MemoryStorage,
    submitter: RecordingSubmitter,
    clock: Callable[[], datetime],
    purchases: FakePurchases,
) -> None:
    """The other half of the fix, and the half that is deliberately still fail-OPEN.

    Refusing the render was the easy direction. The screen may not go the same way: "you
    must pay" is a claim about a balance, and the whole premise here is that nobody could
    read one — a customer holding ten credits would be shown a bill for a song they have
    already bought. So ``build_offer`` keeps answering ``None`` on a failed read, the
    Confirm screen keeps its ordinary summary, and the customer only learns anything is
    wrong if they press.

    Asserted on both surfaces the buttons are drawn on, because they are two call sites of
    one decision and a fix applied to one of them is a fix that will drift.
    """
    # Arrange
    deps = selling(settings, submitter, clock, purchases)
    dispatcher = build_dispatcher(deps, storage=storage)
    await complete_onboarding(dispatcher, bot, language=Language.EN)
    meter = deps.entitlements
    assert isinstance(meter, LinkedMeter)
    meter.failure = StorageError("the meter is down")

    # Act — the balance screen, then the Confirm screen
    session.clear()
    await send(dispatcher, bot, "/balance")
    balance = session.last_screen
    await tap(dispatcher, bot, "menu.generate", Language.EN)

    # Assert — no price, no purchase buttons, on either
    assert buttons(balance.reply_markup) == ()
    assert str(Pricing.from_settings(settings).single_amount) not in screen_texts(session)
    assert PAY not in {data for _text, data in buttons(session.last_screen.reply_markup)}


async def test_a_customer_who_has_paid_can_actually_queue_the_render(
    settings: Settings,
    bot: Bot,
    session: RecordingSession,
    storage: MemoryStorage,
    submitter: RecordingSubmitter,
    clock: Callable[[], datetime],
    purchases: FakePurchases,
) -> None:
    """The happy path the two fail-closed gates are measured against, driven end to end.

    Every other assertion in this half of the file is that something did NOT happen — no
    render, no second grant, no price. A file of those alone stays green for a build that
    refuses everybody, which is exactly the shape a fail-closed change can take by accident.
    So: buy the song, press 🎬 Record it, and watch it reach the submitter.
    """
    # Arrange
    dispatcher = build_dispatcher(selling(settings, submitter, clock, purchases), storage=storage)
    await walk_to_confirm(dispatcher, bot)
    await press(dispatcher, bot, PAY)
    assert purchases.credits == 1

    # Act
    await press(dispatcher, bot, CONFIRM)

    # Assert
    assert len(submitter.submitted) == 1
    assert translate(StorageError("x").user_message_key, Language.EN) not in screen_texts(session)


async def test_a_purchase_button_pressed_while_a_song_is_being_made_charges_nothing(
    settings: Settings,
    bot: Bot,
    session: RecordingSession,
    storage: MemoryStorage,
    state: FSMContext,
    submitter: RecordingSubmitter,
    clock: Callable[[], datetime],
    purchases: FakePurchases,
) -> None:
    """Fact 1 survived the wizard-less registrations, and this is what proves it did.

    The wizard handler sheds a second tap by flipping the FSM out from under its own
    ``Wizard.confirm`` filter, leaving the tap to ``handlers.submitting`` — which is
    registered AFTER this router. An unfiltered wizard-less registration would have
    intercepted that tap first and charged for it, turning fact 1 into a decoration that
    every existing test would still have called green.

    So the session is parked in ``Wizard.submitting`` by hand — the state a tap sees in the
    window fact 1 opens — and the press must reach neither checkout handler.
    """
    # Arrange
    dispatcher = build_dispatcher(selling(settings, submitter, clock, purchases), storage=storage)
    await walk_to_confirm(dispatcher, bot)
    await state.set_state(Wizard.submitting)
    session.clear()

    # Act
    await press(dispatcher, bot, PAY)

    # Assert
    assert purchases.grants == []
    assert purchases.credits == 0
    assert translate("checkout.paid_single", Language.EN, credits=1) not in screen_texts(session)
    assert await state.get_state() == Wizard.submitting.state


async def test_deciding_on_the_plan_seconds_after_buying_a_song_is_a_real_second_sale(
    settings: Settings,
    bot: Bot,
    storage: MemoryStorage,
    submitter: RecordingSubmitter,
    purchases: FakePurchases,
) -> None:
    """The double-tap window is keyed on the BUTTON as well as the clock, not the clock alone.

    The two price buttons sit side by side on one screen, so "buy the song, read the receipt,
    decide on the plan after all" happens in a second or two — faster than the bounced thumb
    the window exists to swallow. Keyed on time alone, which is how the guard shipped first,
    that press was eaten by a defence built for the OTHER button: redrawn with no toast, no
    "nothing was charged", and working again six seconds later with nothing on screen to
    explain the gap. A refused sale is the expensive direction for a guard whose whole
    purpose is to protect a sale.

    The clock deliberately does NOT move here. That is the entire point: at ``now`` exactly,
    deep inside the window, a press of the other button must still be charged. The
    same-button case one test above still must not be, and both are asserted against the same
    fake so a build that simply removed the guard cannot pass both.
    """
    # Arrange
    clock = MovingClock()
    dispatcher = build_dispatcher(selling(settings, submitter, clock, purchases), storage=storage)
    await walk_to_confirm(dispatcher, bot)
    await press(dispatcher, bot, PAY)

    # Act — the other button, inside the window, with no time passing at all
    await press(dispatcher, bot, SUBSCRIBE)

    # Assert — the song AND the plan. ``grants`` records singles and ``plans`` records plans,
    # so "the second press was not swallowed" is a plan entry existing at all.
    assert len(purchases.grants) == 1
    assert purchases.credits == 1
    assert len(purchases.plans) == 1
    assert purchases.plan is not None


async def test_pressing_the_same_price_button_twice_inside_the_window_still_buys_once(
    settings: Settings,
    bot: Bot,
    storage: MemoryStorage,
    submitter: RecordingSubmitter,
    purchases: FakePurchases,
) -> None:
    """The guard the test above narrows must still hold for the case it was written for.

    Paired with it deliberately: making the window product-aware is exactly the kind of edit
    that widens a defence into uselessness, and one test asserting "the other button works"
    would pass just as happily against a build with no window at all.
    """
    # Arrange
    clock = MovingClock()
    dispatcher = build_dispatcher(selling(settings, submitter, clock, purchases), storage=storage)
    await walk_to_confirm(dispatcher, bot)
    await press(dispatcher, bot, SUBSCRIBE)

    # Act — the same button, inside the window
    await press(dispatcher, bot, SUBSCRIBE)

    # Assert — the second press bought nothing
    assert len(purchases.plans) == 1
