"""Who sees, quotes and pays for media (IMAGE_VIDEO_SPEC §2.5, §4.3, §4.5, §7.2)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from bayram.config import Settings
from bayram.contracts import Result, is_err, ok
from bayram.db.enums import MediaBackend, MediaSku
from bayram.errors import CheckoutError
from bayram.media.gate import QuoteBlock, quote_block
from bayram.media.margin import check_margin
from bayram.media.offering import (
    effective_backend,
    guarded_media_charge,
    is_live_paid,
    media_offered,
)
from bayram.media.overrides import MediaOverrides

OWNER = 42
STRANGER = 99
NOW = datetime(2026, 9, 24, 12, 0, tzinfo=UTC)
NO_OVERRIDES = MediaOverrides(backend=None, is_paused=False, gpu_reserved_until=None)


def _with(settings: Settings, **update: Any) -> Settings:
    return settings.model_copy(update=update)


def _beta(settings: Settings) -> Settings:
    return _with(
        settings, is_image_offered=True, media_beta_enabled=True, media_beta_allowlist=(OWNER,)
    )


def _live(settings: Settings) -> Settings:
    return _with(
        settings,
        is_image_offered=True,
        checkout_provider="payme",
        credits_enforced=True,
        payme_is_sandbox=False,
    )


# ---------------------------------------------------------------------------
# media_offered and live-paid
# ---------------------------------------------------------------------------
def test_the_sandbox_is_not_live_paid(settings: Settings) -> None:
    assert not is_live_paid(settings)
    assert not is_live_paid(_with(_live(settings), payme_is_sandbox=True))
    assert not is_live_paid(_with(_live(settings), credits_enforced=False))
    assert is_live_paid(_live(settings))


def test_during_beta_only_the_allowlist_is_offered_media(settings: Settings) -> None:
    beta = _beta(settings)

    assert media_offered(beta, MediaSku.IMAGE, OWNER, is_paused=False)
    assert not media_offered(beta, MediaSku.IMAGE, STRANGER, is_paused=False)
    assert not media_offered(beta, MediaSku.VIDEO_STANDARD, OWNER, is_paused=False)


def test_a_live_paid_rail_offers_everyone_and_a_pause_hides_it(settings: Settings) -> None:
    live = _live(settings)

    assert media_offered(live, MediaSku.IMAGE, STRANGER, is_paused=False)
    assert not media_offered(live, MediaSku.IMAGE, STRANGER, is_paused=True)


def test_use_fake_providers_pins_every_backend_to_the_fake(settings: Settings) -> None:
    faked = _with(settings, use_fake_providers=True)

    assert effective_backend(faked, MediaSku.IMAGE, MediaBackend.LOCAL) is MediaBackend.FAKE
    assert effective_backend(settings, MediaSku.IMAGE, None) is MediaBackend.LOCAL
    assert effective_backend(settings, MediaSku.IMAGE, MediaBackend.FAL) is MediaBackend.FAL


def test_a_fake_override_outside_a_fake_deployment_resolves_to_the_env_backend(
    settings: Settings,
) -> None:
    # §4.5: boot sees only the env backend, so a Redis key naming the fake must not route
    # paying customers to placeholder renders.
    assert not settings.use_fake_providers

    assert effective_backend(settings, MediaSku.IMAGE, MediaBackend.FAKE) is MediaBackend.LOCAL
    assert effective_backend(
        _with(settings, image_backend="fal"), MediaSku.IMAGE, MediaBackend.FAKE
    ) is (MediaBackend.FAL)


# ---------------------------------------------------------------------------
# The 💳 gate
# ---------------------------------------------------------------------------
async def test_a_media_pay_press_on_the_stub_charges_nothing(settings: Settings) -> None:
    """§10 M2.2: no receipt is written and nothing starts, because charge is never reached."""
    calls: list[str] = []

    async def charge() -> Result[str]:
        calls.append("charged")
        return ok("receipt")

    result = await guarded_media_charge(_beta(settings), MediaSku.IMAGE, charge)

    assert is_err(result)
    assert isinstance(result.error, CheckoutError)
    assert calls == []


async def test_a_media_pay_press_on_the_sandbox_charges_nothing(settings: Settings) -> None:
    calls: list[str] = []

    async def charge() -> Result[str]:
        calls.append("charged")
        return ok("receipt")

    sandbox = _with(_live(settings), payme_is_sandbox=True)
    result = await guarded_media_charge(sandbox, MediaSku.IMAGE, charge)

    assert is_err(result)
    assert calls == []


async def test_a_media_pay_press_on_a_live_rail_reaches_the_charge(settings: Settings) -> None:
    async def charge() -> Result[str]:
        return ok("receipt")

    result = await guarded_media_charge(_live(settings), MediaSku.IMAGE, charge)

    assert result == ok("receipt")


# ---------------------------------------------------------------------------
# The quote gate
# ---------------------------------------------------------------------------
def test_an_allowlisted_user_can_be_quoted(settings: Settings) -> None:
    assert quote_block(_beta(settings), MediaSku.IMAGE, OWNER, NO_OVERRIDES, now=NOW) is None


def test_a_stranger_learns_nothing_about_a_pause(settings: Settings) -> None:
    paused = MediaOverrides(backend=None, is_paused=True, gpu_reserved_until=None)

    assert quote_block(_beta(settings), MediaSku.IMAGE, STRANGER, paused, now=NOW) is (
        QuoteBlock.NOT_OFFERED
    )
    assert quote_block(_beta(settings), MediaSku.IMAGE, OWNER, paused, now=NOW) is (
        QuoteBlock.PAUSED
    )


def test_a_reserved_gpu_refuses_local_quotes_until_the_window_ends(settings: Settings) -> None:
    reserved = MediaOverrides(
        backend=None, is_paused=False, gpu_reserved_until=NOW + timedelta(minutes=30)
    )

    assert quote_block(_beta(settings), MediaSku.IMAGE, OWNER, reserved, now=NOW) is (
        QuoteBlock.GPU_RESERVED
    )
    later = NOW + timedelta(hours=1)
    assert quote_block(_beta(settings), MediaSku.IMAGE, OWNER, reserved, now=later) is None


def test_a_reserved_gpu_does_not_block_a_sku_routed_off_the_gpu(settings: Settings) -> None:
    # Routed to fal, the window is not this SKU's business (fal then fails on its margin,
    # which has no known cost — a different reason, asserted below).
    rerouted = MediaOverrides(
        backend=MediaBackend.FAL, is_paused=False, gpu_reserved_until=NOW + timedelta(hours=1)
    )

    assert quote_block(_beta(settings), MediaSku.IMAGE, OWNER, rerouted, now=NOW) is (
        QuoteBlock.MARGIN
    )


def test_an_override_to_a_backend_with_no_known_cost_fails_the_margin(settings: Settings) -> None:
    to_fal = MediaOverrides(backend=MediaBackend.FAL, is_paused=False, gpu_reserved_until=None)

    assert quote_block(_beta(settings), MediaSku.IMAGE, OWNER, to_fal, now=NOW) is (
        QuoteBlock.MARGIN
    )


# ---------------------------------------------------------------------------
# The margin rule (§4.3, research §6)
# ---------------------------------------------------------------------------
def test_the_local_backend_always_clears_the_margin(settings: Settings) -> None:
    assert check_margin(settings, MediaSku.IMAGE, MediaBackend.LOCAL).is_ok


def test_a_paid_backend_needs_an_exchange_rate(settings: Settings) -> None:
    verdict = check_margin(settings, MediaSku.IMAGE, MediaBackend.FAL, usd_per_output=0.045)

    assert not verdict.is_ok
    assert verdict.reason is not None and "UZS_PER_USD" in verdict.reason


@pytest.mark.parametrize(
    ("usd_per_output", "is_ok"),
    [
        (0.045, True),  # fal Seedream v4: ~23% of net revenue at 12 800 UZS/USD
        (0.014, True),  # Higgsfield Soul 2 (third-party figure): ~7%
        (0.14, False),  # Higgsfield's documented figure: ~73%
        (0.225, False),  # Nano Banana Pro edit: a loss
    ],
)
def test_the_research_table_is_reproduced_for_a_5000_uzs_image(
    settings: Settings, usd_per_output: float, is_ok: bool
) -> None:
    # Two images × 1.5 attempts each; 5 000 UZS less 2% at 12 800 UZS/USD ≈ $0.383 net.
    priced = _with(settings, media_uzs_per_usd=12_800.0)

    verdict = check_margin(priced, MediaSku.IMAGE, MediaBackend.FAL, usd_per_output=usd_per_output)

    assert verdict.is_ok is is_ok


def test_a_sku_with_no_price_fails_the_margin(settings: Settings) -> None:
    verdict = check_margin(settings, MediaSku.VIDEO_FAST, MediaBackend.LOCAL)

    assert not verdict.is_ok
