"""Three rails on one paywall, and the owner's per-rail switch deciding which of them sell.

``DECISIONS.md D28``. The bot is told two things at the composition root: which rails are
WIRED (``BotDeps.checkout_rails``, in the order the composite routes them) and how to read the
owner's switch for each one (``BotDeps.rail_enabled_reader``). The price buttons are drawn from
both, and a button that names a rail carries that name all the way into
``PurchaseRequest.preferred_provider`` and into a rail-qualified idempotency key.

Every rail here is a :class:`RecordingCheckout` behind a real ``CompositeCheckoutProvider``,
so routing is the production router's and nothing contacts a vendor.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import replace
from datetime import datetime

import pytest
from aiogram import Bot
from aiogram.fsm.storage.memory import MemoryStorage

from bayram.bot.app import build_dispatcher
from bayram.bot.callbacks import NavAction, NavCB
from bayram.bot.deps import BotDeps
from bayram.bot.handlers import checkout as checkout_handlers
from bayram.bot.i18n import translate
from bayram.bot.pricing import Pricing
from bayram.bot.screens import checkout_link_screen
from bayram.checkout import CompositeCheckoutProvider, Product
from bayram.checkoutuz import CHECKOUTUZ_PROVIDER_NAME
from bayram.config import Settings
from bayram.contracts import Language
from tests.test_bot.conftest import (
    FakePurchases,
    RecordingCheckout,
    RecordingSession,
    RecordingSubmitter,
)
from tests.test_bot.test_checkout import selling
from tests.test_bot.test_wizard_flow import complete_onboarding, press, send, walk_to_confirm

PAY = NavCB(action=NavAction.PAY).pack()
PAY_PAYME = NavCB(action=NavAction.PAY_PAYME).pack()
PAY_CHECKOUTUZ = NavCB(action=NavAction.PAY_CHECKOUTUZ).pack()
SUBSCRIBE = NavCB(action=NavAction.SUBSCRIBE).pack()
SUBSCRIBE_PAYME = NavCB(action=NavAction.SUBSCRIBE_PAYME).pack()
SUBSCRIBE_CHECKOUTUZ = NavCB(action=NavAction.SUBSCRIBE_CHECKOUTUZ).pack()
PRICE_BUTTONS = {PAY, PAY_PAYME, PAY_CHECKOUTUZ, SUBSCRIBE, SUBSCRIBE_PAYME, SUBSCRIBE_CHECKOUTUZ}

ALL_RAILS = ("rhmt", "payme", "checkoutuz")
BASES = {
    "rhmt": "https://pay.rhmt.uz",
    "payme": "https://checkout.paycom.uz",
    "checkoutuz": "https://checkout.uz/pay",
}


class Rails:
    """Three named recording rails behind the production composite."""

    def __init__(self) -> None:
        self.by_name: dict[str, RecordingCheckout] = {}
        for name in ALL_RAILS:
            rail = RecordingCheckout(is_paid=False, checkout_url=BASES[name])
            rail.name = name
            self.by_name[name] = rail
        self.composite = CompositeCheckoutProvider([self.by_name[name] for name in ALL_RAILS])

    def __getitem__(self, name: str) -> RecordingCheckout:
        return self.by_name[name]


class Switches:
    """A fake owner switch: a dict, with a count of how often it was read."""

    def __init__(self, **enabled: bool) -> None:
        self.enabled = enabled
        self.reads: list[str] = []

    async def __call__(self, rail: str) -> bool:
        self.reads.append(rail)
        return self.enabled.get(rail, True)


def multi_rail(
    settings: Settings,
    submitter: RecordingSubmitter,
    clock: Callable[[], datetime],
    purchases: FakePurchases,
    rails: Rails,
    *,
    reader: Callable[[str], Awaitable[bool]] | None = None,
    plan: bool = False,
) -> BotDeps:
    if plan:
        settings = settings.model_copy(update={"is_starter_plan_offered": True})
    return replace(
        selling(settings, submitter, clock, purchases, checkout=rails.composite),
        checkout_rails=ALL_RAILS,
        rail_enabled_reader=reader,
    )


def drawn(session: RecordingSession) -> list[str]:
    markup = session.last_screen.reply_markup
    if markup is None:
        return []
    return [str(button.callback_data) for row in markup.inline_keyboard for button in row]


def price_buttons(session: RecordingSession) -> list[str]:
    return [data for data in drawn(session) if data in PRICE_BUTTONS]


# ---------------------------------------------------------------------------
# BotDeps.enabled_rails
# ---------------------------------------------------------------------------
@pytest.mark.anyio
async def test_enabled_rails_without_a_reader_is_every_wired_rail(
    settings: Settings,
    submitter: RecordingSubmitter,
    clock: Callable[[], datetime],
    purchases: FakePurchases,
) -> None:
    deps = multi_rail(settings, submitter, clock, purchases, Rails())

    assert await deps.enabled_rails() == ALL_RAILS


@pytest.mark.anyio
async def test_enabled_rails_filters_through_the_switch_in_wired_order(
    settings: Settings,
    submitter: RecordingSubmitter,
    clock: Callable[[], datetime],
    purchases: FakePurchases,
) -> None:
    switches = Switches(payme=False)
    deps = multi_rail(settings, submitter, clock, purchases, Rails(), reader=switches)

    assert await deps.enabled_rails() == ("rhmt", "checkoutuz")
    assert switches.reads == list(ALL_RAILS)


@pytest.mark.anyio
async def test_enabled_rails_fails_open_when_the_switch_cannot_be_read(
    settings: Settings,
    submitter: RecordingSubmitter,
    clock: Callable[[], datetime],
    purchases: FakePurchases,
) -> None:
    async def broken(rail: str) -> bool:
        raise ConnectionError("redis is down")

    deps = multi_rail(settings, submitter, clock, purchases, Rails(), reader=broken)

    assert await deps.enabled_rails() == ALL_RAILS


@pytest.mark.anyio
async def test_a_stub_deployment_never_reads_the_switch(
    settings: Settings,
    submitter: RecordingSubmitter,
    clock: Callable[[], datetime],
    purchases: FakePurchases,
) -> None:
    switches = Switches()
    deps = replace(selling(settings, submitter, clock, purchases), rail_enabled_reader=switches)

    assert await deps.enabled_rails() == ()
    assert switches.reads == []


# ---------------------------------------------------------------------------
# Which buttons are drawn
# ---------------------------------------------------------------------------
@pytest.mark.anyio
async def test_every_rail_on_draws_the_generic_pair_and_both_named_rails(
    settings: Settings,
    bot: Bot,
    session: RecordingSession,
    storage: MemoryStorage,
    submitter: RecordingSubmitter,
    clock: Callable[[], datetime],
    purchases: FakePurchases,
) -> None:
    deps = multi_rail(settings, submitter, clock, purchases, Rails(), reader=Switches(), plan=True)
    await walk_to_confirm(build_dispatcher(deps, storage=storage), bot)

    assert price_buttons(session) == [
        PAY,
        PAY_PAYME,
        PAY_CHECKOUTUZ,
        SUBSCRIBE,
        SUBSCRIBE_PAYME,
        SUBSCRIBE_CHECKOUTUZ,
    ]


@pytest.mark.anyio
async def test_the_button_set_follows_the_switches(
    settings: Settings,
    bot: Bot,
    session: RecordingSession,
    storage: MemoryStorage,
    submitter: RecordingSubmitter,
    clock: Callable[[], datetime],
    purchases: FakePurchases,
) -> None:
    deps = multi_rail(
        settings, submitter, clock, purchases, Rails(), reader=Switches(checkoutuz=False)
    )
    await walk_to_confirm(build_dispatcher(deps, storage=storage), bot)

    assert price_buttons(session) == [PAY, PAY_PAYME]


@pytest.mark.anyio
async def test_rahmat_switched_off_hides_the_generic_button(
    settings: Settings,
    bot: Bot,
    session: RecordingSession,
    storage: MemoryStorage,
    submitter: RecordingSubmitter,
    clock: Callable[[], datetime],
    purchases: FakePurchases,
) -> None:
    # A generic press names no rail and the composite sends it to Rahmat, which would only
    # refuse. The two rails still on are drawn under their own names instead.
    deps = multi_rail(
        settings, submitter, clock, purchases, Rails(), reader=Switches(rhmt=False), plan=True
    )
    await walk_to_confirm(build_dispatcher(deps, storage=storage), bot)

    assert price_buttons(session) == [
        PAY_PAYME,
        PAY_CHECKOUTUZ,
        SUBSCRIBE_PAYME,
        SUBSCRIBE_CHECKOUTUZ,
    ]


@pytest.mark.anyio
async def test_every_rail_switched_off_draws_no_price_and_says_why(
    settings: Settings,
    bot: Bot,
    session: RecordingSession,
    storage: MemoryStorage,
    submitter: RecordingSubmitter,
    clock: Callable[[], datetime],
    purchases: FakePurchases,
) -> None:
    switches = Switches(rhmt=False, payme=False, checkoutuz=False)
    deps = multi_rail(settings, submitter, clock, purchases, Rails(), reader=switches)
    await walk_to_confirm(build_dispatcher(deps, storage=storage), bot)

    assert price_buttons(session) == []
    assert translate("checkout.unavailable", Language.EN) in session.last_screen.text


@pytest.mark.anyio
async def test_the_balance_screen_follows_the_switches_too(
    settings: Settings,
    bot: Bot,
    session: RecordingSession,
    storage: MemoryStorage,
    submitter: RecordingSubmitter,
    clock: Callable[[], datetime],
    purchases: FakePurchases,
) -> None:
    deps = multi_rail(settings, submitter, clock, purchases, Rails(), reader=Switches(payme=False))
    dispatcher = build_dispatcher(deps, storage=storage)
    await complete_onboarding(dispatcher, bot, language=Language.EN)
    session.clear()

    await send(dispatcher, bot, "/balance")

    assert price_buttons(session) == [PAY, PAY_CHECKOUTUZ]


@pytest.mark.anyio
async def test_the_balance_screen_with_every_rail_off_has_no_keyboard(
    settings: Settings,
    bot: Bot,
    session: RecordingSession,
    storage: MemoryStorage,
    submitter: RecordingSubmitter,
    clock: Callable[[], datetime],
    purchases: FakePurchases,
) -> None:
    switches = Switches(rhmt=False, payme=False, checkoutuz=False)
    deps = multi_rail(settings, submitter, clock, purchases, Rails(), reader=switches)
    dispatcher = build_dispatcher(deps, storage=storage)
    await complete_onboarding(dispatcher, bot, language=Language.EN)
    session.clear()

    await send(dispatcher, bot, "/balance")

    assert session.last_screen.reply_markup is None
    assert translate("checkout.unavailable", Language.EN) in session.last_screen.text


# ---------------------------------------------------------------------------
# What a press does
# ---------------------------------------------------------------------------
@pytest.mark.anyio
async def test_the_checkoutuz_button_routes_to_checkoutuz_with_the_one_hour_hint(
    settings: Settings,
    bot: Bot,
    session: RecordingSession,
    storage: MemoryStorage,
    submitter: RecordingSubmitter,
    clock: Callable[[], datetime],
    purchases: FakePurchases,
) -> None:
    rails = Rails()
    deps = multi_rail(settings, submitter, clock, purchases, rails, reader=Switches())
    dispatcher = build_dispatcher(deps, storage=storage)
    await walk_to_confirm(dispatcher, bot)

    await press(dispatcher, bot, PAY_CHECKOUTUZ)

    assert rails["rhmt"].requests == [] and rails["payme"].requests == []
    (request,) = rails["checkoutuz"].requests
    assert request.preferred_provider == "checkoutuz"
    assert request.product is Product.SINGLE
    assert request.idempotency_key.endswith(":checkoutuz")
    link = session.last_screen.reply_markup.inline_keyboard[0][0].url
    assert link.startswith(BASES["checkoutuz"])
    expected = checkout_link_screen(
        Language.EN,
        url=link,
        amount_minor=Pricing.from_settings(settings).single_amount_minor,
        provider="checkoutuz",
    )
    assert session.last_screen.text == expected.text
    assert translate("checkout.pending_hint_checkoutuz", Language.EN) in expected.text
    assert translate("checkout.pending_hint", Language.EN) not in expected.text


@pytest.mark.anyio
async def test_the_checkoutuz_link_screen_draws_one_button_per_pay_method(
    settings: Settings,
    bot: Bot,
    session: RecordingSession,
    storage: MemoryStorage,
    submitter: RecordingSubmitter,
    clock: Callable[[], datetime],
    purchases: FakePurchases,
) -> None:
    """The pending branch hands the rail's ``pay_options`` to the link screen untouched."""
    rails = Rails()
    options = (
        ("click", "https://checkout.uz/pay/u/click"),
        ("payme", "https://checkout.uz/pay/u/payme"),
        ("card", "https://checkout.uz/pay/u/card"),
    )
    rails["checkoutuz"].pay_options = options
    deps = multi_rail(settings, submitter, clock, purchases, rails, reader=Switches())
    dispatcher = build_dispatcher(deps, storage=storage)
    await walk_to_confirm(dispatcher, bot)

    await press(dispatcher, bot, PAY_CHECKOUTUZ)

    rows = session.last_screen.reply_markup.inline_keyboard
    general = rows[-2][0].url
    assert general is not None and general.startswith(BASES["checkoutuz"])
    expected = checkout_link_screen(
        Language.EN,
        url=general,
        amount_minor=Pricing.from_settings(settings).single_amount_minor,
        provider="checkoutuz",
        pay_options=options,
    )
    assert session.last_screen.text == expected.text
    assert session.last_screen.reply_markup == expected.markup
    assert [[button.url for button in row] for row in rows[:2]] == [
        [options[0][1], options[1][1]],
        [options[2][1]],
    ]


@pytest.mark.parametrize(
    ("wired", "stale_button"),
    [
        # The D28 fallback: checkout.uz switched off by env, Payme left alone.
        (("payme",), PAY_CHECKOUTUZ),
        # The reverse: a Rahmat-only deployment and an old 📲 Payme button.
        (("rhmt",), PAY_PAYME),
    ],
)
@pytest.mark.anyio
async def test_a_stale_named_rail_button_is_refused_when_one_bare_rail_is_wired(
    settings: Settings,
    bot: Bot,
    session: RecordingSession,
    storage: MemoryStorage,
    submitter: RecordingSubmitter,
    clock: Callable[[], datetime],
    purchases: FakePurchases,
    wired: tuple[str, ...],
    stale_button: str,
) -> None:
    """One wired rail means ``bayram.main`` wires the BARE provider, which ignores
    ``preferred_provider`` — so the handler must refuse a button naming another rail, or the
    customer is silently sent to a rail they never chose."""
    rails = Rails()
    (only,) = wired
    deps = replace(
        selling(settings, submitter, clock, purchases, checkout=rails[only]),
        checkout_rails=wired,
    )
    dispatcher = build_dispatcher(deps, storage=storage)
    await walk_to_confirm(dispatcher, bot)

    await press(dispatcher, bot, stale_button)

    assert all(rails[name].requests == [] for name in ALL_RAILS)
    said = [getattr(method, "text", None) for method in session.named("SendMessage")]
    assert translate("checkout.unavailable", Language.EN) in said


@pytest.mark.anyio
async def test_the_checkoutuz_plan_button_routes_from_the_balance_screen(
    settings: Settings,
    bot: Bot,
    session: RecordingSession,
    storage: MemoryStorage,
    submitter: RecordingSubmitter,
    clock: Callable[[], datetime],
    purchases: FakePurchases,
) -> None:
    rails = Rails()
    deps = multi_rail(settings, submitter, clock, purchases, rails, reader=Switches(), plan=True)
    dispatcher = build_dispatcher(deps, storage=storage)
    await complete_onboarding(dispatcher, bot, language=Language.EN)

    await send(dispatcher, bot, "/balance")
    await press(dispatcher, bot, SUBSCRIBE_CHECKOUTUZ)

    (request,) = rails["checkoutuz"].requests
    assert request.preferred_provider == "checkoutuz"
    assert request.product is Product.STARTER


@pytest.mark.anyio
async def test_each_rail_gets_its_own_key_and_its_own_double_tap_window(
    settings: Settings,
    bot: Bot,
    session: RecordingSession,
    storage: MemoryStorage,
    submitter: RecordingSubmitter,
    clock: Callable[[], datetime],
    purchases: FakePurchases,
) -> None:
    # The clock is frozen, so every press below lands inside the five-second window. A
    # different rail's button is a different decision and is let through; the same rail's
    # button twice is a bounce and is shed.
    rails = Rails()
    deps = multi_rail(settings, submitter, clock, purchases, rails, reader=Switches())
    dispatcher = build_dispatcher(deps, storage=storage)
    await walk_to_confirm(dispatcher, bot)

    await press(dispatcher, bot, PAY)
    await press(dispatcher, bot, PAY_PAYME)
    await press(dispatcher, bot, PAY_CHECKOUTUZ)
    await press(dispatcher, bot, PAY_CHECKOUTUZ)

    keys = [rails[name].requests[0].idempotency_key for name in ALL_RAILS if rails[name].requests]
    assert len(keys) == 3
    assert len(set(keys)) == 3
    assert rails["rhmt"].requests[0].preferred_provider is None
    assert not rails["rhmt"].requests[0].idempotency_key.endswith((":payme", ":checkoutuz"))
    assert rails["payme"].requests[0].idempotency_key.endswith(":payme")
    assert len(rails["checkoutuz"].requests) == 1


# ---------------------------------------------------------------------------
# Pure pieces
# ---------------------------------------------------------------------------
def test_the_handler_rail_name_is_the_checkoutuz_provider_name() -> None:
    assert checkout_handlers._CHECKOUTUZ == CHECKOUTUZ_PROVIDER_NAME


def test_a_rail_qualified_key_differs_only_by_its_suffix() -> None:
    plain = checkout_handlers._idempotency_key(7, "s", product=Product.SINGLE, seq=0)
    railed = checkout_handlers._idempotency_key(
        7, "s", product=Product.SINGLE, seq=0, rail="checkoutuz"
    )

    assert plain == "topup:7:s:0"
    assert railed == "topup:7:s:0:checkoutuz"


@pytest.mark.parametrize("provider", [None, "payme", "rhmt"])
def test_every_other_rail_keeps_the_twelve_hour_hint(provider: str | None) -> None:
    screen = checkout_link_screen(
        Language.EN, url="https://example.invalid/x", amount_minor=700_000, provider=provider
    )

    assert translate("checkout.pending_hint", Language.EN) in screen.text
    assert (
        screen.text
        == checkout_link_screen(
            Language.EN, url="https://example.invalid/x", amount_minor=700_000
        ).text
    )
