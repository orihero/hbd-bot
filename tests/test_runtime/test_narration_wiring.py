"""The narration leg as the worker builds it (IMAGE_VIDEO_SPEC §5.1, §5.2, §9.5; D23)."""

from __future__ import annotations

from typing import Any

import httpx
import pytest

from bayram.config import REQUIRED_VENDOR_SECRET_FIELDS, VENDOR_SECRET_FIELDS, build_settings
from bayram.contracts import Language
from bayram.errors import ConfigError
from bayram.providers.tts.fakes import FakeNarrationProvider
from bayram.providers.tts.key_pool import MemoryKeyPoolStore
from bayram.providers.tts.router import NarrationRouter
from bayram.runtime.providers import build_narration_provider


def _settings(**overrides: Any) -> Any:
    values: dict[str, Any] = {
        "_env_file": None,
        "database_url": "postgresql+asyncpg://u:p@localhost/db",
    }
    values.update(overrides)
    return build_settings(values, require_vendor_secrets=False)


def _build(**overrides: Any) -> Any:
    return build_narration_provider(
        _settings(**overrides), store=MemoryKeyPoolStore(), client=httpx.AsyncClient()
    )


def _names(router: NarrationRouter) -> set[str]:
    names: set[str] = set()
    for language in Language:
        provider = router.provider_for(language)
        assert provider is not None
        names.add(provider.name)
    return names


def test_the_pool_is_a_secret_read_as_csv_and_not_required() -> None:
    settings = _settings(gemini_tts_api_keys=" k1, k2 ,k1,, ")

    assert settings.gemini_tts_key_list == ("k1", "k2")
    assert "gemini_tts_api_keys" in VENDOR_SECRET_FIELDS
    assert "gemini_tts_api_keys" not in REQUIRED_VENDOR_SECRET_FIELDS
    assert _settings().gemini_tts_key_list == ()


def test_with_a_pool_every_language_routes_to_gemini() -> None:
    router = _build(gemini_tts_api_keys="k1,k2")

    assert isinstance(router, NarrationRouter)
    assert _names(router) == {"gemini_tts"}


@pytest.mark.parametrize(
    "overrides",
    [{}, {"gemini_tts_api_keys": "k1", "gemini_tts_enabled": False}],
    ids=["empty-pool", "disabled"],
)
def test_no_pool_or_the_switch_off_routes_every_language_to_elevenlabs(
    overrides: dict[str, Any],
) -> None:
    router = _build(**overrides)

    assert isinstance(router, NarrationRouter)
    assert _names(router) == {"elevenlabs_tts"}


def test_a_route_to_elevenlabs_is_honoured() -> None:
    router = _build(gemini_tts_api_keys="k1", narration_routes="uz_latn=elevenlabs_tts")

    assert router.provider_for(Language.UZ_LATN).name == "elevenlabs_tts"
    # Languages the override does not name are not routed; they reach the fallback.
    assert router.provider_for(Language.RU).name == "elevenlabs_tts"


def test_a_bad_table_refuses_to_boot() -> None:
    with pytest.raises(ConfigError, match="NARRATION_ROUTES"):
        _build(narration_routes="klingon=gemini_tts")
    with pytest.raises(ConfigError, match="narration route table"):
        _build(gemini_tts_api_keys="k1", narration_fallback="azure_tts")


def test_fake_mode_narrates_with_the_fake() -> None:
    assert isinstance(_build(use_fake_providers=True), FakeNarrationProvider)
