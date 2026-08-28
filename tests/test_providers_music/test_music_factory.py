"""Wiring from Settings.

``music_max_concurrency`` and ``music_usd_per_minute`` are now real, bounded ``Settings``
fields, so the factory reads them directly and the *config layer* is where a nonsense value
is refused. These tests assert both halves of that: the wiring here, and the refusal there.
"""

from __future__ import annotations

from typing import Any

import pytest

from hbd.config import Settings
from hbd.errors import ConfigError
from hbd.providers.music.elevenlabs import (
    DEFAULT_MUSIC_MAX_CONCURRENCY,
    SCALE_TIER_MAX_CONCURRENCY,
)
from hbd.providers.music.factory import build_music_provider


def _reconfigured(settings: Settings, **extra: Any) -> Settings:
    payload: dict[str, Any] = {**settings.model_dump(), **extra}
    return Settings(_env_file=None, **payload)


def test_the_provider_is_wired_from_the_elevenlabs_settings(settings: Settings) -> None:
    # Arrange / Act
    provider = build_music_provider(settings)

    # Assert
    assert provider._model_id == settings.music_model_id
    assert provider._output_format == settings.music_output_format
    assert provider._base_url == settings.elevenlabs_base_url.rstrip("/")


def test_concurrency_defaults_to_the_safe_tier_ceiling(settings: Settings) -> None:
    # Arrange / Act
    provider = build_music_provider(settings)

    # Assert: two simultaneous renders, the Starter/Creator/Pro limit.
    assert provider._slots._value == DEFAULT_MUSIC_MAX_CONCURRENCY


def test_the_configured_ceiling_is_honoured(settings: Settings) -> None:
    # Arrange
    upgraded = _reconfigured(
        settings,
        music_max_concurrency=SCALE_TIER_MAX_CONCURRENCY,
        music_usd_per_minute=0.25,
    )

    # Act
    provider = build_music_provider(upgraded)

    # Assert
    assert provider._slots._value == SCALE_TIER_MAX_CONCURRENCY
    assert provider._usd_per_minute == 0.25


@pytest.mark.parametrize("bad_value", [0, -3, "many", 99])
def test_a_nonsense_ceiling_is_refused_by_config_not_the_factory(
    settings: Settings, bad_value: Any
) -> None:
    # Arrange / Act / Assert: the semaphore is never handed a bad value, because
    # Settings refuses to exist with one.
    with pytest.raises(ValueError):
        _reconfigured(settings, music_max_concurrency=bad_value)


@pytest.mark.parametrize("bad_value", [0, -1.0, "cheap"])
def test_a_nonsense_rate_is_refused_by_config(settings: Settings, bad_value: Any) -> None:
    # Arrange / Act / Assert
    with pytest.raises(ValueError):
        _reconfigured(settings, music_usd_per_minute=bad_value)


def test_load_settings_reports_a_bad_ceiling_as_a_config_error(
    settings_env: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    # Arrange
    from hbd.config import load_settings

    for name, value in settings_env.items():
        monkeypatch.setenv(name, value)
    monkeypatch.setenv("HBD_MUSIC_MAX_CONCURRENCY", "not-a-number")

    # Act / Assert: operators see one named variable, not a pydantic traceback.
    with pytest.raises(ConfigError) as caught:
        load_settings()
    assert "HBD_MUSIC_MAX_CONCURRENCY" in caught.value.operator_message


async def test_a_shared_client_is_used_when_one_is_passed(settings: Settings) -> None:
    # Arrange
    import httpx

    client = httpx.AsyncClient()

    # Act
    provider = build_music_provider(settings, client=client)
    await provider.aclose()

    # Assert: the pool belongs to the caller, so it stays open.
    assert not client.is_closed
    await client.aclose()
