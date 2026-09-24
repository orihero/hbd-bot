"""The media boot refusals (IMAGE_VIDEO_SPEC §4.5, §7.4, §10 M2.2)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from bayram.config import ENV_FILE_VAR, Settings
from bayram.errors import ConfigError
from bayram.main import refuse_an_unsafe_checkout_rail
from bayram.media.boot import refuse_unsafe_media_config

OWNER_ID = 1_000_001


@pytest.fixture
def base(settings: Settings, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Settings:
    """Settings with the gateway configured and the boot check's dotenv scan pointed nowhere."""
    monkeypatch.setenv(ENV_FILE_VAR, str(tmp_path / "no-such.env"))
    return settings.model_copy(
        update={"genai_base_url": "https://genai.example.test", "genai_api_key": "k"}
    )


def _with(settings: Settings, **update: Any) -> Settings:
    return settings.model_copy(update=update)


def _beta(settings: Settings, **update: Any) -> Settings:
    values: dict[str, Any] = {
        "is_image_offered": True,
        "media_beta_enabled": True,
        "media_beta_allowlist": (OWNER_ID,),
    }
    values.update(update)
    return _with(settings, **values)


def _live_paid(settings: Settings, **update: Any) -> Settings:
    values: dict[str, Any] = {
        "is_image_offered": True,
        "checkout_provider": "payme",
        "payme_merchant_id": "m",
        "credits_enforced": True,
        "payme_is_sandbox": False,
    }
    values.update(update)
    return _with(settings, **values)


def test_the_shipped_configuration_boots(base: Settings) -> None:
    refuse_unsafe_media_config(base)
    refuse_an_unsafe_checkout_rail(base)


def test_media_on_the_stub_without_the_beta_refuses(base: Settings) -> None:
    with pytest.raises(ConfigError, match="free rail"):
        refuse_unsafe_media_config(_with(base, is_image_offered=True))


def test_media_on_the_stub_with_the_flag_but_no_allowlist_refuses(base: Settings) -> None:
    offered = _with(base, is_image_offered=True, media_beta_enabled=True)

    with pytest.raises(ConfigError, match="BAYRAM_MEDIA_BETA_ALLOWLIST"):
        refuse_unsafe_media_config(offered)


def test_media_on_the_payme_sandbox_without_an_allowlist_refuses(base: Settings) -> None:
    # Sandbox money is not money (O9): the sandbox is not live-paid.
    sandbox = _live_paid(base, payme_is_sandbox=True)

    with pytest.raises(ConfigError, match="free rail"):
        refuse_unsafe_media_config(sandbox)


def test_the_bot_boot_path_runs_the_media_refusal(base: Settings) -> None:
    with pytest.raises(ConfigError, match="free rail"):
        refuse_an_unsafe_checkout_rail(_with(base, is_video_standard_offered=True))


def test_the_beta_on_the_stub_boots(base: Settings) -> None:
    refuse_unsafe_media_config(_beta(base))


def test_a_live_paid_rail_boots_and_warns_about_a_leftover_beta_flag(
    base: Settings, caplog: pytest.LogCaptureFixture
) -> None:
    refuse_unsafe_media_config(_live_paid(base, media_beta_enabled=True))

    assert "no effect on a live-paid rail" in caplog.text


def test_the_fake_moderator_with_media_offered_refuses(base: Settings) -> None:
    with pytest.raises(ConfigError, match="BAYRAM_MEDIA_MODERATOR"):
        refuse_unsafe_media_config(_beta(base, media_moderator="fake"))


def test_the_fake_backend_on_an_offered_sku_refuses(base: Settings) -> None:
    with pytest.raises(ConfigError, match="BAYRAM_IMAGE_BACKEND"):
        refuse_unsafe_media_config(_beta(base, image_backend="fake"))


def test_fakes_are_allowed_when_the_whole_process_is_on_fakes(base: Settings) -> None:
    refuse_unsafe_media_config(
        _beta(base, media_moderator="fake", image_backend="fake", use_fake_providers=True)
    )


def test_production_refuses_a_fake_media_setting_even_when_nothing_is_offered(
    base: Settings,
) -> None:
    for update in ({"video_fast_backend": "fake"}, {"media_moderator": "fake"}):
        with pytest.raises(ConfigError, match="production never runs a fake"):
            refuse_unsafe_media_config(_with(base, environment="prod", **update))


def test_an_offered_sku_with_no_price_refuses(base: Settings) -> None:
    with pytest.raises(ConfigError, match="BAYRAM_IMAGE_PRICE_MINOR"):
        refuse_unsafe_media_config(_beta(base, image_price_minor=None))


def test_an_offered_sku_on_an_unbuilt_backend_refuses(base: Settings) -> None:
    with pytest.raises(ConfigError, match="no adapter yet"):
        refuse_unsafe_media_config(_beta(base, image_backend="higgsfield"))


def test_an_offered_local_sku_without_the_gateway_refuses(base: Settings) -> None:
    with pytest.raises(ConfigError, match="BAYRAM_GENAI_BASE_URL"):
        refuse_unsafe_media_config(_beta(base, genai_api_key=""))


@pytest.mark.parametrize(
    ("field", "model"),
    [
        ("genai_image_model", "zootopia"),
        ("genai_image_model", "wan"),
        ("genai_video_model", "hunyuan"),
        ("genai_video_model", "storybook_wan"),
    ],
)
def test_a_gateway_model_off_the_allowlist_refuses_even_with_media_off(
    base: Settings, field: str, model: str
) -> None:
    with pytest.raises(ConfigError, match=field.upper()):
        refuse_unsafe_media_config(_with(base, **{field: model}))
