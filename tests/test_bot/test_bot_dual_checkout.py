"""Tests for bot dual-checkout UI and provider routing (Rahmat primary, Payme secondary).

The buttons follow ``BotDeps.checkout_rails`` — the rails ``bayram.main`` wired — and not
``Settings.checkout_provider`` (``DECISIONS.md D28``), so every deps below names its rails.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace
from datetime import datetime

import pytest
from aiogram import Bot
from aiogram.fsm.storage.memory import MemoryStorage

from bayram.bot.app import build_dispatcher
from bayram.bot.callbacks import NavAction, NavCB
from bayram.checkout import CompositeCheckoutProvider, Product
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
SUBSCRIBE = NavCB(action=NavAction.SUBSCRIBE).pack()
SUBSCRIBE_PAYME = NavCB(action=NavAction.SUBSCRIBE_PAYME).pack()

RHMT_BASE = "https://pay.rhmt.uz"
PAYME_BASE = "https://checkout.paycom.uz"


def build_dual_rail() -> tuple[CompositeCheckoutProvider, RecordingCheckout, RecordingCheckout]:
    primary = RecordingCheckout(is_paid=False, checkout_url=RHMT_BASE)
    primary.name = "rhmt"
    secondary = RecordingCheckout(is_paid=False, checkout_url=PAYME_BASE)
    secondary.name = "payme"
    composite = CompositeCheckoutProvider(primary=primary, secondary=secondary)
    return composite, primary, secondary


@pytest.mark.anyio
async def test_confirm_screen_renders_both_buttons_when_provider_is_both(
    settings: Settings,
    bot: Bot,
    session: RecordingSession,
    storage: MemoryStorage,
    submitter: RecordingSubmitter,
    clock: Callable[[], datetime],
    purchases: FakePurchases,
) -> None:
    dual_settings = settings.model_copy(update={"checkout_provider": "both"})
    composite, primary, secondary = build_dual_rail()
    deps = replace(
        selling(dual_settings, submitter, clock, purchases, checkout=composite),
        checkout_rails=("rhmt", "payme"),
    )
    dispatcher = build_dispatcher(deps, storage=storage)

    await walk_to_confirm(dispatcher, bot)

    keyboard = session.last_screen.reply_markup.inline_keyboard
    callbacks = [btn.callback_data for row in keyboard for btn in row]
    assert PAY in callbacks
    assert PAY_PAYME in callbacks

    # Check button leading emojis
    pay_btn = next(btn for row in keyboard for btn in row if btn.callback_data == PAY)
    payme_btn = next(btn for row in keyboard for btn in row if btn.callback_data == PAY_PAYME)
    assert pay_btn.text.startswith("💳")
    assert payme_btn.text.startswith("📲")


@pytest.mark.anyio
async def test_confirm_screen_with_plan_renders_both_single_and_plan_buttons(
    settings: Settings,
    bot: Bot,
    session: RecordingSession,
    storage: MemoryStorage,
    submitter: RecordingSubmitter,
    clock: Callable[[], datetime],
    purchases: FakePurchases,
) -> None:
    dual_settings = settings.model_copy(
        update={
            "checkout_provider": "both",
            "is_starter_plan_offered": True,
        }
    )
    composite, primary, secondary = build_dual_rail()
    deps = replace(
        selling(dual_settings, submitter, clock, purchases, checkout=composite),
        checkout_rails=("rhmt", "payme"),
    )
    dispatcher = build_dispatcher(deps, storage=storage)

    await walk_to_confirm(dispatcher, bot)

    keyboard = session.last_screen.reply_markup.inline_keyboard
    callbacks = [btn.callback_data for row in keyboard for btn in row]
    assert PAY in callbacks
    assert PAY_PAYME in callbacks
    assert SUBSCRIBE in callbacks
    assert SUBSCRIBE_PAYME in callbacks

    # Check emoji distinctions
    sub_btn = next(btn for row in keyboard for btn in row if btn.callback_data == SUBSCRIBE)
    sub_payme_btn = next(
        btn for row in keyboard for btn in row if btn.callback_data == SUBSCRIBE_PAYME
    )
    assert sub_btn.text.startswith("🌟")
    assert sub_payme_btn.text.startswith("💎")


@pytest.mark.anyio
async def test_tapping_primary_pay_button_routes_to_rhmt(
    settings: Settings,
    bot: Bot,
    session: RecordingSession,
    storage: MemoryStorage,
    submitter: RecordingSubmitter,
    clock: Callable[[], datetime],
    purchases: FakePurchases,
) -> None:
    dual_settings = settings.model_copy(update={"checkout_provider": "both"})
    composite, primary, secondary = build_dual_rail()
    deps = replace(
        selling(dual_settings, submitter, clock, purchases, checkout=composite),
        checkout_rails=("rhmt", "payme"),
    )
    dispatcher = build_dispatcher(deps, storage=storage)
    await walk_to_confirm(dispatcher, bot)

    # Tap primary Pay button (💳)
    await press(dispatcher, bot, PAY)

    assert len(primary.requests) == 1
    assert primary.requests[0].preferred_provider is None
    assert primary.requests[0].product == Product.SINGLE
    assert len(secondary.requests) == 0

    # Screen shows primary URL
    url_btn = session.last_screen.reply_markup.inline_keyboard[0][0]
    assert url_btn.url.startswith(RHMT_BASE)


@pytest.mark.anyio
async def test_tapping_secondary_payme_button_routes_to_payme(
    settings: Settings,
    bot: Bot,
    session: RecordingSession,
    storage: MemoryStorage,
    submitter: RecordingSubmitter,
    clock: Callable[[], datetime],
    purchases: FakePurchases,
) -> None:
    dual_settings = settings.model_copy(update={"checkout_provider": "both"})
    composite, primary, secondary = build_dual_rail()
    deps = replace(
        selling(dual_settings, submitter, clock, purchases, checkout=composite),
        checkout_rails=("rhmt", "payme"),
    )
    dispatcher = build_dispatcher(deps, storage=storage)
    await walk_to_confirm(dispatcher, bot)

    # Tap secondary Payme button (📲)
    await press(dispatcher, bot, PAY_PAYME)

    assert len(secondary.requests) == 1
    assert secondary.requests[0].preferred_provider == "payme"
    assert secondary.requests[0].product == Product.SINGLE
    assert len(primary.requests) == 0

    # Screen shows Payme URL
    url_btn = session.last_screen.reply_markup.inline_keyboard[0][0]
    assert url_btn.url.startswith(PAYME_BASE)


@pytest.mark.anyio
async def test_tapping_plan_buttons_routes_correctly(
    settings: Settings,
    bot: Bot,
    session: RecordingSession,
    storage: MemoryStorage,
    submitter: RecordingSubmitter,
    clock: Callable[[], datetime],
    purchases: FakePurchases,
) -> None:
    dual_settings = settings.model_copy(
        update={
            "checkout_provider": "both",
            "is_starter_plan_offered": True,
        }
    )
    composite, primary, secondary = build_dual_rail()
    deps = replace(
        selling(dual_settings, submitter, clock, purchases, checkout=composite),
        checkout_rails=("rhmt", "payme"),
    )
    dispatcher = build_dispatcher(deps, storage=storage)
    await walk_to_confirm(dispatcher, bot)

    # Tap secondary Payme plan button (💎)
    await press(dispatcher, bot, SUBSCRIBE_PAYME)

    assert len(secondary.requests) == 1
    assert secondary.requests[0].preferred_provider == "payme"
    assert secondary.requests[0].product == Product.STARTER
    assert len(primary.requests) == 0

    url_btn = session.last_screen.reply_markup.inline_keyboard[0][0]
    assert url_btn.url.startswith(PAYME_BASE)


@pytest.mark.anyio
async def test_balance_screen_renders_both_buttons_and_payme_works(
    settings: Settings,
    bot: Bot,
    session: RecordingSession,
    storage: MemoryStorage,
    submitter: RecordingSubmitter,
    clock: Callable[[], datetime],
    purchases: FakePurchases,
) -> None:
    dual_settings = settings.model_copy(
        update={
            "checkout_provider": "both",
            "credits_enforced": True,
        }
    )
    composite, primary, secondary = build_dual_rail()
    deps = replace(
        selling(dual_settings, submitter, clock, purchases, checkout=composite),
        checkout_rails=("rhmt", "payme"),
    )
    dispatcher = build_dispatcher(deps, storage=storage)

    await complete_onboarding(dispatcher, bot, language=Language.EN)
    session.clear()

    # Call /balance with 0 credits
    await send(dispatcher, bot, "/balance")

    keyboard = session.last_screen.reply_markup.inline_keyboard
    callbacks = [btn.callback_data for row in keyboard for btn in row]
    assert PAY in callbacks
    assert PAY_PAYME in callbacks

    # Tap secondary Payme from balance screen
    await press(dispatcher, bot, PAY_PAYME)

    assert len(secondary.requests) == 1
    assert secondary.requests[0].preferred_provider == "payme"
    assert len(primary.requests) == 0


@pytest.mark.anyio
async def test_single_rail_rhmt_does_not_render_secondary_payme(
    settings: Settings,
    bot: Bot,
    session: RecordingSession,
    storage: MemoryStorage,
    submitter: RecordingSubmitter,
    clock: Callable[[], datetime],
    purchases: FakePurchases,
) -> None:
    rhmt_settings = settings.model_copy(update={"checkout_provider": "rhmt"})
    composite, primary, secondary = build_dual_rail()
    deps = replace(
        selling(rhmt_settings, submitter, clock, purchases, checkout=composite),
        checkout_rails=("rhmt",),
    )
    dispatcher = build_dispatcher(deps, storage=storage)

    await walk_to_confirm(dispatcher, bot)

    keyboard = session.last_screen.reply_markup.inline_keyboard
    callbacks = [btn.callback_data for row in keyboard for btn in row]
    assert PAY in callbacks
    assert PAY_PAYME not in callbacks
