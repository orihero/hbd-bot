"""Tests for marketing channel parameter parsing and bot attribution."""

from dataclasses import replace

import pytest
from aiogram import Bot
from aiogram.fsm.storage.memory import MemoryStorage

from bayram.bot.app import build_dispatcher
from bayram.bot.deps import BotDeps
from bayram.bot.handlers.start import PAID_DEEP_LINK
from bayram.channels import parse_channel_param
from tests.test_bot.conftest import (
    USER_ID,
    RecordingSession,
)
from tests.test_bot.test_wizard_flow import send


class FakeChannelAttributions:
    """Records attribution calls in memory for test assertions."""

    def __init__(self) -> None:
        self.calls: list[tuple[int, str, str]] = []

    async def record_attribution(
        self,
        telegram_user_id: int,
        *,
        raw_param: str,
        channel: str,
    ) -> bool:
        self.calls.append((telegram_user_id, raw_param, channel))
        return len(self.calls) == 1


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("utm_source=kanallanidodasi", "kanallanidodasi"),
        ("utm_source_kanallanidodasi", "kanallanidodasi"),
        ("c_kanallanidodasi", "kanallanidodasi"),
        ("c=kanallanidodasi", "kanallanidodasi"),
        ("src_instagram", "instagram"),
        ("src=instagram", "instagram"),
        ("ref_telegram_ads", "telegram_ads"),
        ("kanallanidodasi", "kanallanidodasi"),
        ("utm_source=channel1&utm_medium=cpc", "channel1"),
        ("utm_source=channel1;utm_campaign=winter", "channel1"),
        ("paid", None),
        ("PAID", None),
        ("", None),
        ("   ", None),
        (None, None),
    ],
)
def test_parse_channel_param(raw: str | None, expected: str | None) -> None:
    assert parse_channel_param(raw) == expected


async def test_start_with_channel_param_records_attribution(
    deps: BotDeps,
    bot: Bot,
    session: RecordingSession,
    storage: MemoryStorage,
) -> None:
    attributions = FakeChannelAttributions()
    custom_deps = replace(deps, channel_attributions=attributions)
    dispatcher = build_dispatcher(custom_deps, storage=storage)

    await send(dispatcher, bot, "/start utm_source=kanallanidodasi")

    assert len(attributions.calls) == 1
    user_id, raw_param, channel = attributions.calls[0]
    assert user_id == USER_ID
    assert raw_param == "utm_source=kanallanidodasi"
    assert channel == "kanallanidodasi"


async def test_plain_start_records_no_attribution(
    deps: BotDeps,
    bot: Bot,
    session: RecordingSession,
    storage: MemoryStorage,
) -> None:
    attributions = FakeChannelAttributions()
    custom_deps = replace(deps, channel_attributions=attributions)
    dispatcher = build_dispatcher(custom_deps, storage=storage)

    await send(dispatcher, bot, "/start")

    assert attributions.calls == []


async def test_paid_start_bypasses_channel_attribution(
    deps: BotDeps,
    bot: Bot,
    session: RecordingSession,
    storage: MemoryStorage,
) -> None:
    attributions = FakeChannelAttributions()
    custom_deps = replace(deps, channel_attributions=attributions)
    dispatcher = build_dispatcher(custom_deps, storage=storage)

    await send(dispatcher, bot, f"/start {PAID_DEEP_LINK}")

    assert attributions.calls == []
