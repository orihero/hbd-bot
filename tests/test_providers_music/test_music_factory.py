"""Wiring from Settings.

``music_max_concurrency`` and ``music_usd_per_minute`` are now real, bounded ``Settings``
fields, so the factory reads them directly and the *config layer* is where a nonsense value
is refused. These tests assert both halves of that: the wiring here, and the refusal there.

They also pin what counts as nonsense, because the two fields disagree about zero. A
ceiling of zero is a semaphore that never opens; a RATE of zero is an operator saying no
music rate is configured, which the adapter answers with a NULL cost rather than a free
render. Only one of the two may be refused at startup, and a test that refused both would
have taken the one honest way of leaving music unpriced away from the operator.
"""

from __future__ import annotations

from typing import Any

import pytest

from hbd.config import Settings
from hbd.contracts import CostSource
from hbd.errors import ConfigError
from hbd.providers.music.elevenlabs import (
    DEFAULT_MUSIC_MAX_CONCURRENCY,
    SCALE_TIER_MAX_CONCURRENCY,
)
from hbd.providers.music.factory import build_music_provider
from tests.test_providers_music.conftest import simple_plan


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


# 0 is deliberately absent here and asserted as ACCEPTED below: it is the only way an
# operator can say "I do not know the music rate", which every other cost leg says by
# shipping 0.0, and a rate that cannot be zero is a rate somebody is forced to invent.
@pytest.mark.parametrize("bad_value", [-1.0, "cheap"])
def test_a_nonsense_rate_is_refused_by_config(settings: Settings, bad_value: Any) -> None:
    # Arrange / Act / Assert
    with pytest.raises(ValueError):
        _reconfigured(settings, music_usd_per_minute=bad_value)


def test_a_zero_rate_is_accepted_and_reaches_the_provider(settings: Settings) -> None:
    # Arrange — the deployment that would rather record no price than a placeholder one.
    unpriced = _reconfigured(settings, music_usd_per_minute=0.0)

    # Act
    provider = build_music_provider(unpriced)

    # Assert — it arrives unaltered, and the adapter reads it as "not priced": no cost and
    # no provenance, which is what keeps SUM(cost_usd) honest for this deployment.
    assert provider._usd_per_minute == 0.0
    assert provider._estimated_cost(simple_plan()) == (None, None)


def test_the_shipped_rate_prices_a_render_and_says_the_figure_is_estimated(
    settings: Settings,
) -> None:
    # Arrange — nothing configured. This is the out-of-the-box deployment, and music is the
    # one leg it prices: the panel's "nothing is priced yet" state is NOT what it ships in.
    provider = build_music_provider(settings)

    # Act
    cost, source = provider._estimated_cost(simple_plan())

    # Assert — a real figure from a placeholder rate, wearing the label that says so.
    assert cost is not None and cost > 0
    assert source is CostSource.ESTIMATED


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
