"""The branch a REDIRECT rail added: a payment that started, told apart from one that failed.

``test_checkout.py`` drives the inline rail — charge, fulfil, receipt, redraw — and every one
of its assertions still holds unchanged. This file drives the third answer, which that file
had no way to express until ``bayram.payme`` landed: ``Ok`` with ``is_paid=False`` and a
``checkout_url``, which is what a redirect rail returns EVERY time it successfully opens a
payment. Read as a decline — which is what the handler did before the pending branch existed —
it told a customer "That did not go through, and nothing was charged" at the exact moment their
money was on its way.

Four properties are what this file is for, and each is one deliberate failure away from being
false:

* **an unpaid purchase grants NOTHING.** The fulfiller is never called, ``topup_purchases``
  never gets a row and the meter never moves, because a redirect rail returns an unpaid receipt
  for every checkout anyone ever abandoned and granting against one would be a free song per
  abandonment. Asserted through ``FakePurchases.grants``, which records EVERY key handed in
  including replays, so "the store was never asked" is distinguishable from "the store refused";
* **the counter does not move.** ``PURCHASE_SEQ_KEY`` is what makes a press mint a new
  idempotency key, and a new key on this rail means a second intent, a second ``public_ref``
  and a second live payment page in one chat for one purchase. So a deliberate press after the
  double-tap window re-mints the IDENTICAL key and gets the IDENTICAL link back;
* **the refusals stay apart.** A paused rail, a declined charge and a rail that answered
  neither yes nor here-is-where are three different sentences now, and only the last two say
  "nothing was charged";
* **the FSM is left where the inline path leaves it.** ``Wizard.confirm``, never
  ``Wizard.submitting`` — the state a customer stranded in would be blocked behind
  ``handlers.submitting`` forever, and the redirect path is the one that returns while the
  purchase is still open.

Everything is driven through a real ``Dispatcher`` with real keyboards and real callback data,
for the reason ``test_checkout.py`` gives: the properties are properties of the ROUTING and the
FSM, and a handler called by hand exercises neither. The ``BotDeps`` come from that file's
``selling`` helper rather than being built here, which is also what keeps this module inside
``test_walker_preconditions.py``'s rule about ``profiles=``.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import datetime

import pytest
from aiogram import Bot
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.memory import MemoryStorage

from bayram.bot.app import build_dispatcher
from bayram.bot.callbacks import NavAction, NavCB
from bayram.bot.handlers.checkout import DOUBLE_TAP_WINDOW, PURCHASE_SEQ_KEY, SettleOutcome
from bayram.bot.handlers.start import PAID_DEEP_LINK
from bayram.bot.i18n import translate
from bayram.bot.pricing import Pricing
from bayram.bot.screens import checkout_link_screen
from bayram.bot.states import Wizard
from bayram.checkout import Purchase, PurchaseRequest
from bayram.config import Settings
from bayram.contracts import Language, Result, err
from bayram.errors import CheckoutPausedError
from tests.test_bot.conftest import (
    FakePurchases,
    RecordingCheckout,
    RecordingSession,
    RecordingSubmitter,
    callback_update,
)
from tests.test_bot.test_checkout import (
    PAY,
    SUBSCRIBE,
    MovingClock,
    balance_screen,
    screen_texts,
    selling,
)
from tests.test_bot.test_wizard_flow import complete_onboarding, press, send, walk_to_confirm

#: What ``RecordingCheckout`` builds its links on top of. A real-shaped Payme checkout host, so
#: a reader of a failure message sees the string a customer would have tapped; the per-intent
#: suffix is appended by the fake and is derived from the idempotency key, never from the call
#: count — see :class:`~tests.test_bot.conftest.RecordingCheckout`.
REDIRECT_BASE = "https://checkout.paycom.uz"

HOME = NavCB(action=NavAction.TO_MENU).pack()


class PausedCheckout:
    """A rail an operator has closed. Returns ``Err(CheckoutPausedError)`` and charges nothing.

    Its own class rather than a ``failure=`` switch on ``RecordingCheckout``, because the two
    fakes stand for genuinely different things: that one is a rail that ANSWERED, and this one
    is a rail that refused before an intent existed. Keeping them apart is what makes the
    assertion below — that the customer reads ``checkout.paused`` and NOT ``checkout.failed`` —
    an assertion about the handler's branch rather than about a flag.
    """

    def __init__(self) -> None:
        self.name = "paused"
        self.requests: list[PurchaseRequest] = []

    async def charge(self, request: PurchaseRequest) -> Result[Purchase]:
        self.requests.append(request)
        return err(CheckoutPausedError("the rail is paused", context={"product": "single"}))


def redirect_rail() -> RecordingCheckout:
    """A rail that starts payments and settles none of them, which is what a redirect rail is."""
    return RecordingCheckout(is_paid=False, checkout_url=REDIRECT_BASE)


def link_for(rail: RecordingCheckout) -> str:
    """The URL the fake issued, read back through the key the handler actually minted.

    Read from the rail rather than reconstructed from a constant, so a handler that quietly
    sent the customer a different link than the one it was given would fail here instead of
    matching a string this file made up.
    """
    assert len(rail.opened) == 1, f"the rail opened {len(rail.opened)} intents: {rail.opened}"
    return f"{REDIRECT_BASE}/{next(iter(rail.opened.values()))}"


def screens_reading(session: RecordingSession, text: str) -> int:
    """How many times exactly this text was put on the customer's screen, sent or edited."""
    return sum(1 for call in session.calls if getattr(call, "text", None) == text)


# ---------------------------------------------------------------------------
# a payment that started
# ---------------------------------------------------------------------------
async def test_a_started_payment_shows_the_link_and_never_says_nothing_was_charged(
    settings: Settings,
    bot: Bot,
    session: RecordingSession,
    storage: MemoryStorage,
    submitter: RecordingSubmitter,
    clock: Callable[[], datetime],
    purchases: FakePurchases,
) -> None:
    """The sentence this whole branch exists to stop being shown, and the screen that replaces it.

    Asserted against ``checkout_link_screen`` rather than against a hand-written string,
    because two different things are under test and only one of them is the copy: that the
    handler passed the rail's OWN url through untouched, and that it quoted the amount it had
    just handed the rail rather than re-reading a price. Both would survive a copy edit and
    neither would survive a mix-up, which is the right way round.
    """
    # Arrange
    rail = redirect_rail()
    pricing = Pricing.from_settings(settings)
    deps = selling(settings, submitter, clock, purchases, checkout=rail)
    dispatcher = build_dispatcher(deps, storage=storage)
    await walk_to_confirm(dispatcher, bot)

    # Act
    await press(dispatcher, bot, PAY)

    # Assert
    expected = checkout_link_screen(
        Language.EN, url=link_for(rail), amount_minor=pricing.single_amount_minor
    )
    assert session.last_screen.text == expected.text
    assert translate("checkout.failed", Language.EN) not in screen_texts(session)
    assert translate("checkout.paid_single", Language.EN, credits=1) not in screen_texts(session)


async def test_the_link_screen_carries_a_url_button_and_a_way_home(
    settings: Settings,
    bot: Bot,
    session: RecordingSession,
    storage: MemoryStorage,
    submitter: RecordingSubmitter,
    clock: Callable[[], datetime],
    purchases: FakePurchases,
) -> None:
    """A 🔗 that leaves Telegram, and one button that does not. See ``checkout_link_keyboard``.

    The URL is read off the markup the bot actually drew, which is the only place a wrong link
    could hide: ``translate`` renders the LABEL and nothing checks the href.
    """
    # Arrange
    rail = redirect_rail()
    deps = selling(settings, submitter, clock, purchases, checkout=rail)
    dispatcher = build_dispatcher(deps, storage=storage)
    await walk_to_confirm(dispatcher, bot)

    # Act
    await press(dispatcher, bot, PAY)

    # Assert
    rows = session.last_screen.reply_markup.inline_keyboard
    assert [button.url for button in rows[0]] == [link_for(rail)]
    assert [button.callback_data for button in rows[1]] == [HOME]
    assert rows[0][0].text == translate("button.pay_now", Language.EN)


async def test_a_started_payment_grants_nothing_and_never_reaches_the_fulfiller(
    settings: Settings,
    bot: Bot,
    storage: MemoryStorage,
    submitter: RecordingSubmitter,
    clock: Callable[[], datetime],
    purchases: FakePurchases,
) -> None:
    """The load-bearing one: an unpaid purchase must not buy anything.

    ``grants`` records every key the store was HANDED, replays included, so an empty list is
    the strong claim — the fulfiller was never called at all, rather than called and refused.
    That distinction matters because the store's own ``_refuse_an_unpaid_purchase`` would have
    turned the second shape into an ``Err`` and the customer into a red error message about a
    payment that was going perfectly well.

    ``submitted`` is asserted too: nothing about a checkout may queue a render, and a redirect
    is the one path where the customer is left holding a screen for minutes with the wizard
    still alive behind it.
    """
    # Arrange
    rail = redirect_rail()
    deps = selling(settings, submitter, clock, purchases, checkout=rail)
    dispatcher = build_dispatcher(deps, storage=storage)
    await walk_to_confirm(dispatcher, bot)

    # Act
    await press(dispatcher, bot, PAY)

    # Assert
    assert len(rail.requests) == 1
    assert purchases.grants == []
    assert purchases.plans == []
    assert purchases.credits == 0
    assert submitter.submitted == []


async def test_a_started_payment_does_not_bump_the_purchase_counter(
    settings: Settings,
    bot: Bot,
    storage: MemoryStorage,
    state: FSMContext,
    submitter: RecordingSubmitter,
    clock: Callable[[], datetime],
    purchases: FakePurchases,
) -> None:
    """The counter is what mints a NEW key, and a new key would mint a second payment page.

    The two REPLAY markers are written and the counter is not, which is the whole shape of
    ``_remember_pending``: a redelivered update and a bounced thumb are still shed, while a
    deliberate press after the window collapses back onto the intent that is already open.
    """
    # Arrange
    rail = redirect_rail()
    deps = selling(settings, submitter, clock, purchases, checkout=rail)
    dispatcher = build_dispatcher(deps, storage=storage)
    await walk_to_confirm(dispatcher, bot)

    # Act
    await press(dispatcher, bot, PAY)

    # Assert
    data = await state.get_data()
    assert PURCHASE_SEQ_KEY not in data
    assert data["purchase_settled_updates"] != []
    assert data["purchase_settled_product"] == "single"


async def test_the_wizard_is_left_on_confirm_and_never_parked_in_submitting(
    settings: Settings,
    bot: Bot,
    storage: MemoryStorage,
    state: FSMContext,
    submitter: RecordingSubmitter,
    clock: Callable[[], datetime],
    purchases: FakePurchases,
) -> None:
    """Fact 5 in the module docstring, as the thing it protects rather than as a claim.

    ``Wizard.submitting`` is un-parked by exactly one other thing in the product
    (``runtime.jobs._release_session``, which runs only from a job), and no job exists on this
    path: the customer is in a browser and settlement arrives at a different process. A
    redirect that returned while still parked would leave them behind ``handlers.submitting``
    for ever, with every button on the screen they are holding refused.
    """
    # Arrange
    rail = redirect_rail()
    deps = selling(settings, submitter, clock, purchases, checkout=rail)
    dispatcher = build_dispatcher(deps, storage=storage)
    await walk_to_confirm(dispatcher, bot)

    # Act
    await press(dispatcher, bot, PAY)

    # Assert
    assert await state.get_state() == Wizard.confirm.state


async def test_a_started_plan_payment_quotes_the_plan_price_and_opens_no_plan(
    settings: Settings,
    bot: Bot,
    session: RecordingSession,
    storage: MemoryStorage,
    submitter: RecordingSubmitter,
    clock: Callable[[], datetime],
    purchases: FakePurchases,
) -> None:
    """🌟 takes the same branch as 💳 and must quote its own number.

    The two products differ in exactly two places — the amount quoted to the rail and which
    method of the fulfiller is called — and on this path the second one is not called at all,
    so the amount is the only thing left that can be wrong. A screen quoting the single-song
    price over a link for 49 000 is a customer who reads one number and is charged another.
    """
    # Arrange
    rail = redirect_rail()
    pricing = Pricing.from_settings(settings)
    deps = selling(settings, submitter, clock, purchases, checkout=rail)
    dispatcher = build_dispatcher(deps, storage=storage)
    await walk_to_confirm(dispatcher, bot)

    # Act
    await press(dispatcher, bot, SUBSCRIBE)

    # Assert
    expected = checkout_link_screen(
        Language.EN, url=link_for(rail), amount_minor=pricing.plan_amount_minor
    )
    assert session.last_screen.text == expected.text
    assert purchases.plans == []
    assert purchases.plan is None


# ---------------------------------------------------------------------------
# pressing again
# ---------------------------------------------------------------------------
async def test_a_second_press_inside_the_double_tap_window_opens_no_second_payment(
    settings: Settings,
    bot: Bot,
    session: RecordingSession,
    storage: MemoryStorage,
    submitter: RecordingSubmitter,
    purchases: FakePurchases,
) -> None:
    """A bounced thumb must not put two payment pages in one chat, and does not reach the rail.

    The link screen replaces the paywall in the same message, so in the wizard the second press
    can only come from a tap already in flight — which is exactly the case, since the per-chat
    lock serialises them and the second runs at the first's settlement plus milliseconds.

    **The shed press redraws the paywall over the link, and that is deliberate rather than
    overlooked.** The shed branch has said everything it has to say and redraws from the meter,
    which on a rail that granted nothing is still the paywall; re-presenting the link instead
    would mean remembering it in FSM data, which is a fourth marker for a case the next test
    already answers — the customer's next press after the window gets the identical link back,
    because the counter never moved.
    """
    # Arrange
    clock = MovingClock()
    rail = redirect_rail()
    deps = selling(settings, submitter, clock, purchases, checkout=rail)
    dispatcher = build_dispatcher(deps, storage=storage)
    await walk_to_confirm(dispatcher, bot)
    await press(dispatcher, bot, PAY)
    link_text = checkout_link_screen(
        Language.EN,
        url=link_for(rail),
        amount_minor=Pricing.from_settings(settings).single_amount_minor,
    ).text
    assert screens_reading(session, link_text) == 1

    # Act — a second press one second later, well inside the window
    clock.advance(1.0)
    await press(dispatcher, bot, PAY)

    # Assert — the rail was never asked again and no second intent exists
    assert len(rail.requests) == 1
    assert len(rail.opened) == 1
    assert screens_reading(session, link_text) == 1
    assert purchases.grants == []


async def test_a_second_press_after_the_window_re_mints_the_same_key_and_the_same_link(
    settings: Settings,
    bot: Bot,
    session: RecordingSession,
    storage: MemoryStorage,
    submitter: RecordingSubmitter,
    purchases: FakePurchases,
) -> None:
    """The reason ``_remember_pending`` leaves the counter alone, driven end to end.

    A customer who tapped 💳, thought about it, and came back a minute later must get the
    payment they already have — not a second one. The key is derived from the counter, so an
    unbumped counter re-mints the identical string, ``open_intent`` insert-or-ignores on its
    unique index and the SAME ``public_ref`` — therefore the SAME URL — comes back. The fake
    mints its reference per KEY for exactly this reason, so a handler that bumped the counter
    would produce a visibly different link here rather than an identical one by luck.
    """
    # Arrange
    clock = MovingClock()
    rail = redirect_rail()
    deps = selling(settings, submitter, clock, purchases, checkout=rail)
    dispatcher = build_dispatcher(deps, storage=storage)
    await walk_to_confirm(dispatcher, bot)
    await press(dispatcher, bot, PAY)
    first = session.last_screen.reply_markup.inline_keyboard[0][0].url

    # Act — long after the window, from the paywall the redraw put back
    clock.advance(DOUBLE_TAP_WINDOW * 10)
    await press(dispatcher, bot, PAY)

    # Assert
    keys = [request.idempotency_key for request in rail.requests]
    assert len(keys) == 2
    assert keys[0] == keys[1]
    assert len(rail.opened) == 1
    assert session.last_screen.reply_markup.inline_keyboard[0][0].url == first
    assert purchases.grants == []


async def test_a_redelivered_update_does_not_send_the_link_a_second_time(
    settings: Settings,
    bot: Bot,
    session: RecordingSession,
    storage: MemoryStorage,
    submitter: RecordingSubmitter,
    purchases: FakePurchases,
) -> None:
    """The settled-update memory still works when nothing settled.

    Telegram redelivers from the last confirmed offset, so the identical callback can arrive
    again after the handler has already answered it. Nothing was granted, so there is no double
    charge to prevent here — what there is, is a customer who would be handed the same payment
    link twice by a bot that appears to be stuttering. The clock is pushed past the double-tap
    window first, so the ONLY guard that can catch this is the update list.
    """
    # Arrange
    clock = MovingClock()
    rail = redirect_rail()
    deps = selling(settings, submitter, clock, purchases, checkout=rail)
    dispatcher = build_dispatcher(deps, storage=storage)
    await walk_to_confirm(dispatcher, bot)
    replayed = callback_update(PAY)
    await dispatcher.feed_update(bot, replayed)
    link_text = checkout_link_screen(
        Language.EN,
        url=link_for(rail),
        amount_minor=Pricing.from_settings(settings).single_amount_minor,
    ).text

    # Act — the same update, arriving again long after the window would have closed
    clock.advance(DOUBLE_TAP_WINDOW * 10)
    await dispatcher.feed_update(bot, replayed)

    # Assert
    assert len(rail.requests) == 1
    assert screens_reading(session, link_text) == 1


# ---------------------------------------------------------------------------
# the two refusals that are not this branch
# ---------------------------------------------------------------------------
async def test_a_paused_rail_says_so_rather_than_saying_the_payment_failed(
    settings: Settings,
    bot: Bot,
    session: RecordingSession,
    storage: MemoryStorage,
    state: FSMContext,
    submitter: RecordingSubmitter,
    clock: Callable[[], datetime],
    purchases: FakePurchases,
) -> None:
    """An ``Err`` is now rendered from the TYPED error, so two refusals read differently.

    Before this, the ``Err`` branch was a hardcoded ``translate("checkout.failed", ...)``, which
    was correct while the only rail could not fail. A paused rail is a deliberate operator
    action measured in minutes and "try again in a moment" is the wrong instruction for it —
    but "nothing was charged" is true of both, which is why the shipped copy for an ORDINARY
    failure is unchanged: ``CheckoutError.default_user_message_key`` IS ``checkout.failed``.
    """
    # Arrange
    rail = PausedCheckout()
    deps = selling(settings, submitter, clock, purchases, checkout=rail)
    dispatcher = build_dispatcher(deps, storage=storage)
    await walk_to_confirm(dispatcher, bot)

    # Act
    await press(dispatcher, bot, PAY)

    # Assert
    assert translate("checkout.paused", Language.EN) in screen_texts(session)
    assert translate("checkout.failed", Language.EN) not in screen_texts(session)
    assert purchases.grants == []
    assert await state.get_state() == Wizard.confirm.state


async def test_an_unpaid_receipt_with_nowhere_to_pay_still_says_nothing_was_charged(
    settings: Settings,
    bot: Bot,
    session: RecordingSession,
    storage: MemoryStorage,
    state: FSMContext,
    submitter: RecordingSubmitter,
    clock: Callable[[], datetime],
    purchases: FakePurchases,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """The old branch is still correct and is still covered, for an INLINE rail that declined.

    ``checkout.failed`` was never wrong — it was wrong for the redirect shape only. A rail that
    answers unpaid with no url has declined, and "nothing was charged" is exactly true.

    For a REDIRECT rail the same shape is impossible by construction, so it is a defect in the
    provider: the customer has been left with no way forward. That is why it is logged at
    ERROR, and the level is asserted rather than the message — a log line nobody can find is
    the difference between a diagnosable outage and a support ticket saying "the button does
    nothing".
    """
    # Arrange
    rail = RecordingCheckout(is_paid=False)
    deps = selling(settings, submitter, clock, purchases, checkout=rail)
    dispatcher = build_dispatcher(deps, storage=storage)
    await walk_to_confirm(dispatcher, bot)

    # Act
    with caplog.at_level(logging.ERROR, logger="bayram.bot.handlers.checkout"):
        await press(dispatcher, bot, PAY)

    # Assert
    assert translate("checkout.failed", Language.EN) in screen_texts(session)
    assert purchases.grants == []
    assert await state.get_state() == Wizard.confirm.state
    assert [record.message for record in caplog.records if record.levelno >= logging.ERROR] == [
        "a rail returned an unpaid purchase with nowhere to pay"
    ]


# ---------------------------------------------------------------------------
# the other surface, and the way back
# ---------------------------------------------------------------------------
async def test_a_payment_started_from_the_balance_screen_is_not_covered_by_the_menu(
    settings: Settings,
    bot: Bot,
    session: RecordingSession,
    storage: MemoryStorage,
    state: FSMContext,
    submitter: RecordingSubmitter,
    clock: Callable[[], datetime],
    purchases: FakePurchases,
) -> None:
    """``/balance`` draws the same buttons, and only a SETTLED purchase earns the menu under it.

    The menu is the next step for somebody who has just bought a song, and a customer holding a
    payment link has not bought one. It would also land on top of the link: ``menu_screen``
    carries a REPLY keyboard, which ``present`` can only ever SEND, so "what are we making?"
    would be the last message under a 🔗 the customer has not tapped yet.
    """
    # Arrange
    rail = redirect_rail()
    deps = selling(settings, submitter, clock, purchases, checkout=rail)
    dispatcher = build_dispatcher(deps, storage=storage)
    await balance_screen(dispatcher, bot, session)

    # Act
    await press(dispatcher, bot, PAY)

    # Assert
    assert session.last_screen.reply_markup.inline_keyboard[0][0].url == link_for(rail)
    assert translate("menu.prompt", Language.EN) not in screen_texts(session)
    assert purchases.grants == []
    assert await state.get_state() is None


async def test_coming_back_through_the_paid_deep_link_redraws_the_meter_and_claims_nothing(
    settings: Settings,
    bot: Bot,
    session: RecordingSession,
    storage: MemoryStorage,
    submitter: RecordingSubmitter,
    clock: Callable[[], datetime],
) -> None:
    """``/start paid`` answers with the BALANCE, and says not one word about the payment.

    The handler knows only that a browser tab closed. Whether the money landed is a question
    only the meter can answer — settlement is inbound and arrives at another process — so the
    customer is shown the number rather than a guess, and the sentence that does announce a
    settled payment (``checkout.paid_late_single``) is sent from the worker or not at all.

    The account is seeded with a credit so the assertion is about a number that could only have
    come from the meter, rather than about the empty-account wording every other path renders.
    """
    # Arrange
    purchases = FakePurchases(credits=1)
    deps = selling(settings, submitter, clock, purchases)
    dispatcher = build_dispatcher(deps, storage=storage)
    await complete_onboarding(dispatcher, bot, language=Language.EN)
    session.clear()

    # Act
    await send(dispatcher, bot, f"/start {PAID_DEEP_LINK}")

    # Assert
    assert translate("credits.balance_metered", Language.EN, credits=1) in screen_texts(session)
    assert translate("checkout.paid_late_single", Language.EN, credits=1) not in screen_texts(
        session
    )
    assert translate("menu.prompt", Language.EN) not in screen_texts(session)


async def test_a_plain_start_still_reaches_the_menu(
    settings: Settings,
    bot: Bot,
    session: RecordingSession,
    storage: MemoryStorage,
    submitter: RecordingSubmitter,
    clock: Callable[[], datetime],
    purchases: FakePurchases,
) -> None:
    """The deep link is registered ABOVE the bare command, so the bare command must still work.

    aiogram takes the first registration whose filters match and ``CommandStart()`` matches a
    payload-carrying ``/start`` too, which is why the narrow filter goes first. This is the
    other half of that ordering: with the magic filter written wrongly — matching everything,
    or matching by prefix — an ordinary ``/start`` would silently answer with a balance screen
    instead of the menu, in a way no type checker could see.
    """
    # Arrange
    deps = selling(settings, submitter, clock, purchases)
    dispatcher = build_dispatcher(deps, storage=storage)
    await complete_onboarding(dispatcher, bot, language=Language.EN)
    session.clear()

    # Act
    await send(dispatcher, bot, "/start")

    # Assert
    assert translate("menu.prompt", Language.EN) in screen_texts(session)


# ---------------------------------------------------------------------------
# the vocabulary itself
# ---------------------------------------------------------------------------
def test_no_settle_outcome_may_be_read_as_a_boolean() -> None:
    """``_settle`` returns three answers, and a ``bool`` could only ever carry two.

    The enum is the mechanism and not the documentation — it is what makes ``mypy --strict``
    name every call site the day a fourth answer appears — and the hazard it replaced is
    pinned here rather than described. Every member is a NON-EMPTY string, so all three are
    truthy: a call site that reverted to the old ``if settled:`` would compile, pass type
    checking, and read a started payment and a shed replay as a completed purchase, which on
    the ``/balance`` surface means drawing "what are we making?" over a customer's unpaid
    link. That is why ``_buy_from_balance`` compares with ``is`` and why this assertion is
    about truthiness rather than about the members' names.
    """
    # Arrange / Act / Assert
    assert [member.value for member in SettleOutcome] == ["settled", "pending", "nothing"]
    assert [member for member in SettleOutcome if not member] == []
