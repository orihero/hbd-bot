"""The media settings (IMAGE_VIDEO_SPEC §4.5, §7.1, §9.5)."""

from __future__ import annotations

import typing
from pathlib import Path
from typing import Any

import pytest

from bayram.config import (
    REQUIRED_VENDOR_SECRET_FIELDS,
    VENDOR_SECRET_FIELDS,
    MediaBackendName,
    Settings,
    build_settings,
)
from bayram.db.enums import MediaBackend
from bayram.errors import ConfigError

_ENV_EXAMPLE = Path(__file__).resolve().parents[2] / ".env.example"


def _build(**overrides: Any) -> Settings:
    values: dict[str, Any] = {
        "_env_file": None,
        "database_url": "postgresql+asyncpg://u:p@localhost/db",
    }
    values.update(overrides)
    return build_settings(values, require_vendor_secrets=False)


def test_media_ships_off_with_the_owner_prices(settings: Settings) -> None:
    assert not settings.is_any_media_offered
    assert settings.media_beta_enabled is False
    assert settings.media_beta_allowlist == ()
    assert settings.image_price_minor == 500_000
    assert settings.video_standard_price_minor == 2_500_000
    assert settings.video_fast_price_minor is None
    assert (settings.image_backend, settings.video_standard_backend) == ("local", "local")
    assert settings.video_fast_backend == "higgsfield"
    assert (settings.genai_image_model, settings.genai_video_model) == ("flux2", "wan")
    assert settings.media_moderator == "gateway"


def test_the_backend_literal_spells_the_stored_enum() -> None:
    assert set(typing.get_args(MediaBackendName.__value__)) == {b.value for b in MediaBackend}


def test_an_empty_price_variable_means_not_sellable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BAYRAM_VIDEO_FAST_PRICE_MINOR", "")
    monkeypatch.setenv("BAYRAM_IMAGE_PRICE_MINOR", " ")
    monkeypatch.setenv("BAYRAM_MEDIA_UZS_PER_USD", "")

    built = _build()

    assert built.video_fast_price_minor is None
    assert built.image_price_minor is None
    assert built.media_uzs_per_usd is None


def test_the_allowlist_is_read_as_csv_and_deduplicated(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BAYRAM_MEDIA_BETA_ALLOWLIST", "111, 222,111")

    assert _build().media_beta_allowlist == (111, 222)


@pytest.mark.parametrize("raw", ["0", "-5", "abc"])
def test_a_bad_allowlist_entry_refuses_to_boot(monkeypatch: pytest.MonkeyPatch, raw: str) -> None:
    monkeypatch.setenv("BAYRAM_MEDIA_BETA_ALLOWLIST", raw)

    with pytest.raises(ConfigError, match="BAYRAM_MEDIA_BETA_ALLOWLIST"):
        _build()


def test_an_unknown_backend_refuses_to_boot() -> None:
    with pytest.raises(ConfigError, match="BAYRAM_IMAGE_BACKEND"):
        _build(image_backend="replicate")


def test_the_gateway_key_is_a_vendor_secret_and_not_required() -> None:
    assert "genai_api_key" in VENDOR_SECRET_FIELDS
    assert "genai_api_key" not in REQUIRED_VENDOR_SECRET_FIELDS


def test_env_example_documents_every_media_setting_with_an_empty_secret() -> None:
    text = _ENV_EXAMPLE.read_text(encoding="utf-8")
    for field in (
        "is_image_offered",
        "is_video_standard_offered",
        "is_video_fast_offered",
        "media_beta_enabled",
        "media_beta_allowlist",
        "image_backend",
        "video_standard_backend",
        "video_fast_backend",
        "image_price_minor",
        "video_standard_price_minor",
        "video_fast_price_minor",
        "media_max_cost_share",
        "media_uzs_per_usd",
        "media_max_reference_images",
        "media_moderator",
        "media_moderator_base_url",
        "media_guard_text_route",
        "media_guard_timeout_s",
        "media_sexual_image_block_p",
        "media_screen_daily_budget",
        "media_daily_cap_image",
        "media_daily_cap_video",
        "media_legal_hold_recipient",
        "genai_base_url",
        "genai_api_key",
        "genai_image_model",
        "genai_video_model",
        "genai_script_model",
        "genai_script_timeout_s",
        "gemini_tts_enabled",
        "gemini_tts_api_keys",
        "gemini_tts_model",
        "gemini_tts_voice_female",
        "gemini_tts_voice_male",
        "narration_routes",
        "narration_fallback",
        "higgsfield_base_url",
        "higgsfield_api_key_id",
        "higgsfield_api_secret",
        "higgsfield_image_model",
        "higgsfield_video_model",
        "higgsfield_usd_per_credit",
        "higgsfield_image_usd_per_output",
        "higgsfield_video_usd_per_output",
        "image_max_cost_usd",
        "video_fast_max_cost_usd",
        "video_standard_max_cost_usd",
    ):
        assert f"\nBAYRAM_{field.upper()}=" in text, field
    assert "\nBAYRAM_GENAI_API_KEY=\n" in text
    assert "\nBAYRAM_GEMINI_TTS_API_KEYS=\n" in text
    assert "\nBAYRAM_HIGGSFIELD_API_SECRET=\n" in text


def test_the_higgsfield_secret_is_a_vendor_secret_and_not_required() -> None:
    # §9.5: the admin host is refused it; the bot boots without it (media is optional).
    assert "higgsfield_api_secret" in VENDOR_SECRET_FIELDS
    assert "higgsfield_api_secret" not in REQUIRED_VENDOR_SECRET_FIELDS
    assert "higgsfield_api_key_id" not in VENDOR_SECRET_FIELDS


def test_the_higgsfield_defaults_are_the_specs(settings: Settings) -> None:
    # §9.5: per-request ceilings; Kling 3.0 standard for Fast (§4.3); unknown costs unset.
    assert settings.image_max_cost_usd == 0.20
    assert settings.video_fast_max_cost_usd == 1.00
    assert settings.video_standard_max_cost_usd is None  # Standard is a GPU tier
    assert settings.higgsfield_video_model == "kling3_0_std"
    assert settings.higgsfield_usd_per_credit is None
    assert settings.higgsfield_video_usd_per_output is None


def test_env_example_ships_the_owner_prices_the_settings_default_to() -> None:
    # IMAGE_VIDEO_SPEC §7.1, M5.3: 5 000 soʻm per two-image request, 25 000 per Standard clip,
    # Fast unset until M6. The example and the default must not drift apart, or go-live day
    # sells at whichever one the host's env file happened to copy.
    lines = dict(
        line.split("=", 1)
        for line in _ENV_EXAMPLE.read_text(encoding="utf-8").splitlines()
        if line.startswith("BAYRAM_") and "=" in line
    )
    defaults = _build()

    assert lines["BAYRAM_IMAGE_PRICE_MINOR"] == str(defaults.image_price_minor) == "500000"
    assert (
        lines["BAYRAM_VIDEO_STANDARD_PRICE_MINOR"]
        == str(defaults.video_standard_price_minor)
        == "2500000"
    )
    assert lines["BAYRAM_VIDEO_FAST_PRICE_MINOR"] == ""
    assert defaults.video_fast_price_minor is None


def test_the_reference_cap_stops_where_the_collage_layouts_stop() -> None:
    # A 1-ref backend composites the photos, and §4.4 lays out at most four.
    from bayram.media.composite import MAX_COLLAGE_PHOTOS

    assert _build().media_max_reference_images == MAX_COLLAGE_PHOTOS
    assert _build(media_max_reference_images=MAX_COLLAGE_PHOTOS).media_max_reference_images == 4
    with pytest.raises(ConfigError):
        _build(media_max_reference_images=MAX_COLLAGE_PHOTOS + 1)
