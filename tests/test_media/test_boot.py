"""The media boot refusals (IMAGE_VIDEO_SPEC §4.5, §7.4, §10 M2.2)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from bayram.config import ENV_FILE_VAR, Settings, build_settings
from bayram.errors import ConfigError
from bayram.main import refuse_an_unsafe_checkout_rail
from bayram.media.boot import refuse_unsafe_media_config
from bayram.moderation.legal_hold import generate_keypair

OWNER_ID = 1_000_001
_, PUBLIC_KEY = generate_keypair()


@pytest.fixture
def base(settings: Settings, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Settings:
    """Settings with the gateway configured and the boot check's dotenv scan pointed nowhere."""
    monkeypatch.setenv(ENV_FILE_VAR, str(tmp_path / "no-such.env"))
    return settings.model_copy(
        update={
            "genai_base_url": "https://genai.example.test",
            "genai_api_key": "k",
            "media_legal_hold_recipient": PUBLIC_KEY,
        }
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
        "terms_version": "2026-10-01",
        "privacy_version": "2026-10-01",
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


# -- M5.3: the go-live set (IMAGE_VIDEO_SPEC §7.1, §7.4, §10 M5.3) -------------


def test_the_go_live_flag_set_boots_on_the_shipped_prices(base: Settings) -> None:
    # Image + Standard for everyone, beta off, the owner's prices left at their defaults.
    go_live = _live_paid(base, is_video_standard_offered=True)

    refuse_unsafe_media_config(go_live)
    refuse_an_unsafe_checkout_rail(go_live)


@pytest.mark.parametrize(
    ("offered", "price"),
    [
        ("is_image_offered", "image_price_minor"),
        ("is_video_standard_offered", "video_standard_price_minor"),
        ("is_video_fast_offered", "video_fast_price_minor"),
    ],
)
def test_boot_refuses_an_offered_sku_with_no_price_on_the_live_rail(
    base: Settings, offered: str, price: str
) -> None:
    # The owner flips the flags at M5.3; a SKU switched on with its price variable left empty
    # would quote nothing sellable, so neither the bot nor the worker comes up.
    go_live = _live_paid(base, **{"is_image_offered": False, offered: True, price: None})

    with pytest.raises(ConfigError, match=f"BAYRAM_{price.upper()} is unset"):
        refuse_unsafe_media_config(go_live)
    with pytest.raises(ConfigError, match=f"BAYRAM_{price.upper()} is unset"):
        refuse_an_unsafe_checkout_rail(go_live)


def test_video_fast_ships_without_a_price_so_offering_it_refuses(base: Settings) -> None:
    # Fast is unset until M6 (Q1): flipping only its flag is refused on the price, before
    # the backend is even looked at.
    with pytest.raises(ConfigError, match="BAYRAM_VIDEO_FAST_PRICE_MINOR is unset"):
        refuse_unsafe_media_config(_live_paid(base, is_video_fast_offered=True))


def test_an_empty_price_variable_with_its_sku_on_refuses_end_to_end(
    base: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The documented spelling of "not sellable" is an empty variable (.env.example).
    monkeypatch.setenv("BAYRAM_VIDEO_STANDARD_PRICE_MINOR", "")
    parsed = build_settings(
        {"_env_file": None, "database_url": "postgresql+asyncpg://u:p@localhost/db"},
        require_vendor_secrets=False,
    )
    assert parsed.video_standard_price_minor is None

    go_live = _live_paid(
        base,
        is_video_standard_offered=True,
        video_standard_price_minor=parsed.video_standard_price_minor,
    )
    with pytest.raises(ConfigError, match="BAYRAM_VIDEO_STANDARD_PRICE_MINOR"):
        refuse_unsafe_media_config(go_live)


def test_media_for_everyone_without_the_terms_gate_refuses(base: Settings) -> None:
    # O4/D26: the Terms acceptance is the whole real-person mitigation once anyone can order.
    ungated = _live_paid(base, terms_version="", privacy_version="")

    with pytest.raises(ConfigError, match="BAYRAM_TERMS_VERSION"):
        refuse_unsafe_media_config(ungated)


def test_the_beta_runs_before_the_terms_are_signed_off(base: Settings) -> None:
    refuse_unsafe_media_config(_beta(base, terms_version="", privacy_version=""))


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
        refuse_unsafe_media_config(_beta(base, image_backend="fal"))


# ---------------------------------------------------------------------------
# Higgsfield (§4.3, M6.1): built, but only with its keys, an HTTPS host and a known cost
# ---------------------------------------------------------------------------
def _on_higgsfield(settings: Settings, **update: Any) -> Settings:
    values: dict[str, Any] = {
        "image_backend": "higgsfield",
        "higgsfield_api_key_id": "id",
        "higgsfield_api_secret": "s",
        "higgsfield_image_usd_per_output": 0.02,
        "media_uzs_per_usd": 12_500.0,
    }
    values.update(update)
    return _beta(settings, **values)


def test_an_offered_sku_on_a_configured_higgsfield_boots(base: Settings) -> None:
    refuse_unsafe_media_config(_on_higgsfield(base))


def test_an_offered_sku_on_higgsfield_without_its_secret_refuses(base: Settings) -> None:
    with pytest.raises(ConfigError, match="BAYRAM_HIGGSFIELD_API_SECRET"):
        refuse_unsafe_media_config(_on_higgsfield(base, higgsfield_api_secret=""))


def test_an_offered_sku_on_higgsfield_over_plain_http_refuses(base: Settings) -> None:
    with pytest.raises(ConfigError, match="BAYRAM_HIGGSFIELD_BASE_URL"):
        refuse_unsafe_media_config(
            _on_higgsfield(base, higgsfield_base_url="http://platform.example.test")
        )


def test_an_offered_sku_on_higgsfield_with_no_known_cost_refuses(base: Settings) -> None:
    with pytest.raises(ConfigError, match="no known cost for higgsfield"):
        refuse_unsafe_media_config(_on_higgsfield(base, higgsfield_image_usd_per_output=None))


def test_an_offered_sku_on_higgsfield_above_the_margin_refuses(base: Settings) -> None:
    # Higgsfield's documented image figure: ~73% of net revenue at 5 000 UZS (research §6).
    with pytest.raises(ConfigError, match="margin check fails"):
        refuse_unsafe_media_config(_on_higgsfield(base, higgsfield_image_usd_per_output=0.14))


@pytest.mark.parametrize(
    ("field", "model"),
    [
        ("higgsfield_video_model", "veo3"),
        ("higgsfield_video_model", "soul_standard"),  # an image model as the video model
        ("higgsfield_image_model", "kling3_0_std"),
    ],
)
def test_a_higgsfield_model_off_the_allowlist_refuses_even_unoffered(
    base: Settings, field: str, model: str
) -> None:
    with pytest.raises(ConfigError, match=field.upper()):
        refuse_unsafe_media_config(_with(base, **{field: model}))


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


@pytest.mark.parametrize(
    ("update", "missing"),
    [
        ({"genai_access_client_id": "id.access"}, "BAYRAM_GENAI_ACCESS_CLIENT_SECRET"),
        ({"genai_access_client_secret": "s"}, "BAYRAM_GENAI_ACCESS_CLIENT_ID"),
    ],
)
def test_half_an_access_token_refuses_even_with_media_off(
    base: Settings, update: dict[str, str], missing: str
) -> None:
    with pytest.raises(ConfigError, match=missing):
        refuse_unsafe_media_config(_with(base, **update))


def test_a_whole_access_token_boots(base: Settings) -> None:
    refuse_unsafe_media_config(
        _with(base, genai_access_client_id="id.access", genai_access_client_secret="s")
    )


@pytest.mark.parametrize(
    "base_url",
    [
        "http://203.0.113.7:5174",
        "https://genai.example.test/?api_key=leaked",
    ],
)
def test_a_gateway_url_that_would_leak_the_key_or_the_photos_refuses(
    base: Settings, base_url: str
) -> None:
    # §9.1 items 2-3: plain HTTP off the host, or the key in the URL.
    with pytest.raises(ConfigError, match="BAYRAM_GENAI_BASE_URL"):
        refuse_unsafe_media_config(_beta(base, genai_base_url=base_url))


def test_plain_http_on_loopback_is_a_development_gateway(base: Settings) -> None:
    refuse_unsafe_media_config(_beta(base, genai_base_url="http://127.0.0.1:5174"))


def test_a_plain_http_gateway_with_no_sku_on_it_boots(base: Settings) -> None:
    # Nothing is sent to it: media is off.
    refuse_unsafe_media_config(_with(base, genai_base_url="http://203.0.113.7:5174"))


# ---------------------------------------------------------------------------
# M3.1: the guards and the legal hold (IMAGE_VIDEO_SPEC §6.2, §6.7)
# ---------------------------------------------------------------------------
def test_an_offered_sku_whose_legal_hold_cannot_be_sealed_refuses(base: Settings) -> None:
    for key in ("", "not-base64!", "c2hvcnQ="):
        with pytest.raises(ConfigError, match="BAYRAM_MEDIA_LEGAL_HOLD_RECIPIENT"):
            refuse_unsafe_media_config(_beta(base, media_legal_hold_recipient=key))


def test_the_guards_default_to_the_gateway_and_may_live_elsewhere(base: Settings) -> None:
    refuse_unsafe_media_config(_beta(base))
    refuse_unsafe_media_config(
        _beta(
            base,
            media_moderator_base_url="https://guards.example.test",
            media_moderator_api_key="hosted-guard-key",
        )
    )


def test_a_guard_host_that_is_not_the_gateway_needs_its_own_key(base: Settings) -> None:
    # M3.R: the gateway's key is never sent to another host, so that host needs its own.
    with pytest.raises(ConfigError, match="BAYRAM_MEDIA_MODERATOR_API_KEY"):
        refuse_unsafe_media_config(
            _beta(base, media_moderator_base_url="https://guards.example.test")
        )
    with pytest.raises(ConfigError, match="ACCESS_CLIENT_ID"):
        refuse_unsafe_media_config(
            _beta(
                base,
                media_moderator_base_url="https://guards.example.test",
                media_moderator_api_key="k",
                media_moderator_access_client_id="half-a-token",
            )
        )


def test_a_guard_address_on_plain_http_refuses(base: Settings) -> None:
    with pytest.raises(ConfigError, match="guard address"):
        refuse_unsafe_media_config(
            _beta(
                base,
                media_moderator_base_url="http://203.0.113.9:8000",
                media_moderator_api_key="k",
            )
        )


def test_a_fake_moderator_with_media_offered_still_refuses(base: Settings) -> None:
    with pytest.raises(ConfigError, match="BAYRAM_MEDIA_MODERATOR"):
        refuse_unsafe_media_config(_beta(base, media_moderator="fake"))


# ---------------------------------------------------------------------------
# A configured fallback backend (IMAGE_VIDEO_SPEC §3.3, M6.2)
# ---------------------------------------------------------------------------
def test_a_fallback_that_passes_the_same_checks_boots(base: Settings) -> None:
    # Local primary, Higgsfield fallback with its key pair and a cost inside the margin.
    refuse_unsafe_media_config(
        _on_higgsfield(base, image_backend="local", image_fallback_backend="higgsfield")
    )


def test_a_fallback_is_held_to_the_same_checks_as_the_backend(base: Settings) -> None:
    # The primary is fine; the fallback has no secret, so a moved job could never render.
    fallback = _on_higgsfield(
        base, image_backend="local", image_fallback_backend="higgsfield", higgsfield_api_secret=""
    )

    with pytest.raises(ConfigError, match="BAYRAM_HIGGSFIELD_API_SECRET"):
        refuse_unsafe_media_config(fallback)


def test_a_fallback_above_the_margin_refuses_naming_the_fallback(base: Settings) -> None:
    fallback = _on_higgsfield(
        base,
        image_backend="local",
        image_fallback_backend="higgsfield",
        higgsfield_image_usd_per_output=0.14,
    )

    with pytest.raises(ConfigError, match="margin check fails on BAYRAM_IMAGE_FALLBACK_BACKEND"):
        refuse_unsafe_media_config(fallback)


def test_an_unbuilt_or_fake_fallback_refuses(base: Settings) -> None:
    with pytest.raises(ConfigError, match="BAYRAM_IMAGE_FALLBACK_BACKEND is 'fal'"):
        refuse_unsafe_media_config(_beta(base, image_fallback_backend="fal"))
    with pytest.raises(ConfigError, match="BAYRAM_IMAGE_FALLBACK_BACKEND is 'fake'"):
        refuse_unsafe_media_config(_beta(base, image_fallback_backend="fake"))


def test_production_refuses_a_fake_fallback_even_unoffered(base: Settings) -> None:
    with pytest.raises(ConfigError, match="BAYRAM_VIDEO_FAST_FALLBACK_BACKEND"):
        refuse_unsafe_media_config(
            _with(base, environment="prod", video_fast_fallback_backend="fake")
        )


def test_an_empty_fallback_variable_is_no_fallback(base: Settings) -> None:
    # ``BAYRAM_IMAGE_FALLBACK_BACKEND=`` as ``.env.example`` ships it.
    parsed = Settings.model_validate({**base.model_dump(), "image_fallback_backend": ""})

    assert parsed.image_fallback_backend is None
