"""``build_settings`` decides who must hold a vendor credential. That decision is tested.

The bot and the worker spend money and speak to customers as the bot; both must refuse to
start without ``telegram_bot_token``, ``elevenlabs_api_key`` and ``llm_api_key``, naming
the missing variable. The admin process must be able to build the same settings shape while
holding none of the three (ADMIN_PANEL_PLAN §4.2, D10). Those are opposite requirements on
one class, so the split between them is the thing worth asserting.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path
from typing import Final

import pytest

from bayram.config import (
    ENV_PREFIX,
    REQUIRED_VENDOR_SECRET_FIELDS,
    VENDOR_SECRET_FIELDS,
    Settings,
    build_settings,
    load_settings,
)
from bayram.errors import ConfigError

_DATABASE_URL: Final[str] = "postgresql+asyncpg://hbd:hbd@localhost:5432/hbd_test"

#: ``.env`` on a developer's machine would otherwise supply what the test is asserting is
#: absent, so every build here is run against a cleared environment and no file.
_NO_ENV_FILE: Final[dict[str, object]] = {"_env_file": None}


@pytest.fixture(autouse=True)
def _isolated_environment(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    for name in tuple(os.environ):
        if name.startswith(ENV_PREFIX):
            monkeypatch.delenv(name, raising=False)
    yield


def _overrides(**extra: object) -> dict[str, object]:
    return {**_NO_ENV_FILE, "database_url": _DATABASE_URL, **extra}


# ---------------------------------------------------------------------------
# The vendor-secret split
# ---------------------------------------------------------------------------
def test_a_process_that_needs_the_vendors_is_told_exactly_which_key_is_missing() -> None:
    # Act
    with pytest.raises(ConfigError) as caught:
        build_settings(_overrides())

    # Assert — the operator gets environment variable names, not field names. The required
    # set is narrower than VENDOR_SECRET_FIELDS: the LLM failover key is forbidden on the
    # admin host but optional for the bot and the worker.
    message = str(caught.value)
    for field in REQUIRED_VENDOR_SECRET_FIELDS:
        assert f"{ENV_PREFIX}{field.upper()}" in message


def test_load_settings_still_requires_them(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # Arrange — ``env_file=".env"`` is resolved relative to the working directory, so the
    # developer's own .env would otherwise supply exactly what this asserts is absent.
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("BAYRAM_DATABASE_URL", _DATABASE_URL)

    # Act / Assert — the bot's and the worker's boot path is unchanged by the refactor.
    with pytest.raises(ConfigError, match="TELEGRAM_BOT_TOKEN"):
        load_settings()


def test_a_process_that_must_not_hold_them_builds_without_them() -> None:
    # Act
    settings = build_settings(_overrides(), require_vendor_secrets=False)

    # Assert
    assert isinstance(settings, Settings)
    assert all(getattr(settings, field) == "" for field in VENDOR_SECRET_FIELDS)


def test_relaxing_the_vendor_keys_relaxes_nothing_else() -> None:
    # Arrange — database_url is required for every caller, admin included.
    # Act / Assert
    with pytest.raises(ConfigError, match="DATABASE_URL"):
        build_settings(_NO_ENV_FILE, require_vendor_secrets=False)


def test_an_empty_vendor_key_is_refused_as_loudly_as_a_missing_one() -> None:
    # Act / Assert — "" is what a half-filled .env produces, and it is not a credential.
    with pytest.raises(ConfigError, match="ELEVENLABS_API_KEY"):
        build_settings(_overrides(telegram_bot_token="t", elevenlabs_api_key="", llm_api_key="k"))


# ---------------------------------------------------------------------------
# Overrides and the typed log level
# ---------------------------------------------------------------------------
def test_an_override_wins_over_the_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    # Arrange
    monkeypatch.setenv("BAYRAM_SONG_LENGTH_MS", "60000")

    # Act — this is how the config overlay validates a candidate change.
    settings = build_settings(_overrides(song_length_ms=120_000), require_vendor_secrets=False)

    # Assert
    assert settings.song_length_ms == 120_000


def test_a_zero_music_rate_is_accepted_because_unpriced_is_a_thing_to_say() -> None:
    # Act — the bound is ``ge`` and not ``gt`` on purpose: every other cost leg says "no
    # rate is configured here" by shipping 0.0, and music must be able to say it too.
    settings = build_settings(_overrides(music_usd_per_minute=0.0), require_vendor_secrets=False)

    # Assert
    assert settings.music_usd_per_minute == 0.0


def test_the_music_rate_still_ships_priced_at_the_placeholder() -> None:
    # Act — the shipped default is deliberate, not an oversight this test would hide: an
    # unconfigured deployment reports an ESTIMATED music cost rather than none at all.
    settings = build_settings(_overrides(), require_vendor_secrets=False)

    # Assert
    assert settings.music_usd_per_minute == 0.15


def test_a_negative_music_rate_is_still_refused_at_startup() -> None:
    # Act / Assert — relaxing the floor to zero relaxed nothing below it; a negative rate
    # would credit the ledger for spending money.
    with pytest.raises(ConfigError, match="MUSIC_USD_PER_MINUTE"):
        build_settings(_overrides(music_usd_per_minute=-0.01), require_vendor_secrets=False)


def test_an_unknown_log_level_fails_at_startup_not_inside_a_running_worker() -> None:
    # Act / Assert — untyped, this reached root.setLevel("TRACE") and raised there, outside
    # the ConfigError contract every caller of build_settings relies on.
    with pytest.raises(ConfigError, match="LOG_LEVEL"):
        build_settings(_overrides(log_level="TRACE"), require_vendor_secrets=False)
