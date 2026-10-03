"""``resolve_return_urls`` — the paid customer goes back to the bot they paid in.

A fixed default once named the production bot, so a tester paying through a dev bot was sent
to a different one. Blank now means "this bot", learned from Telegram at boot.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

import bayram.main
from bayram.config import Settings
from bayram.main import resolve_return_urls


class FakeBot:
    def __init__(self, *, username: str | None = "hbduzbot", fails: bool = False) -> None:
        self.username = username
        self.fails = fails
        self.calls = 0

    async def get_me(self) -> Any:
        self.calls += 1
        if self.fails:
            raise ConnectionError("telegram down")
        return SimpleNamespace(username=self.username)


def _wired(settings: Settings, **update: Any) -> Settings:
    return settings.model_copy(
        update={"checkoutuz_enabled": True, "checkoutuz_api_key": "k", **update}
    )


def test_the_default_is_blank(settings: Settings) -> None:
    assert settings.checkoutuz_return_url == ""


async def test_a_blank_url_becomes_this_bots_own_link(settings: Settings) -> None:
    resolved = await resolve_return_urls(_wired(settings), FakeBot())  # type: ignore[arg-type]

    assert resolved.checkoutuz_return_url == "https://t.me/hbduzbot"


async def test_an_explicit_url_is_kept_and_telegram_is_not_asked(settings: Settings) -> None:
    bot = FakeBot()
    configured = _wired(settings, checkoutuz_return_url="https://example.uz/thanks")

    resolved = await resolve_return_urls(configured, bot)  # type: ignore[arg-type]

    assert resolved.checkoutuz_return_url == "https://example.uz/thanks"
    assert bot.calls == 0


async def test_an_unwired_rail_asks_nothing(settings: Settings) -> None:
    bot = FakeBot()

    resolved = await resolve_return_urls(settings, bot)  # type: ignore[arg-type]

    assert resolved.checkoutuz_return_url == ""
    assert bot.calls == 0


async def test_a_failed_lookup_leaves_it_blank(settings: Settings) -> None:
    resolved = await resolve_return_urls(_wired(settings), FakeBot(fails=True))  # type: ignore[arg-type]

    assert resolved.checkoutuz_return_url == ""


def _rhmt_file_says(monkeypatch: pytest.MonkeyPatch, url: str) -> None:
    """Stand in for ``.env.rhmt``: the developer's real file must not decide a test."""
    monkeypatch.setattr(
        bayram.main, "build_rhmt_settings", lambda: SimpleNamespace(rhmt_return_url=url)
    )


async def test_a_blank_rahmat_url_becomes_this_bots_own_link(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    _rhmt_file_says(monkeypatch, "")
    configured = settings.model_copy(update={"checkout_provider": "rhmt"})

    resolved = await resolve_return_urls(configured, FakeBot())  # type: ignore[arg-type]

    assert resolved.rhmt_return_url == "https://t.me/hbduzbot"


async def test_a_rahmat_url_set_in_env_rhmt_is_left_to_win(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The container prefers bot.env's value, so filling it here would override .env.rhmt.
    _rhmt_file_says(monkeypatch, "https://example.uz/rhmt")
    bot = FakeBot()
    configured = settings.model_copy(update={"checkout_provider": "rhmt"})

    resolved = await resolve_return_urls(configured, bot)  # type: ignore[arg-type]

    assert resolved.rhmt_return_url == ""
    assert bot.calls == 0


async def test_both_rails_share_one_lookup(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    _rhmt_file_says(monkeypatch, "")
    bot = FakeBot()
    configured = _wired(settings, checkout_provider="rhmt")

    resolved = await resolve_return_urls(configured, bot)  # type: ignore[arg-type]

    assert resolved.rhmt_return_url == resolved.checkoutuz_return_url == "https://t.me/hbduzbot"
    assert bot.calls == 1
