"""Character billing and duration estimates. No price is ever invented, and no price is zero.

The unpriced case is the one that matters most here. ``cost_for`` answers ``(None, None)``
rather than ``(0.0, ESTIMATED)`` when no rate was configured, because a zero-dollar figure
and an unknown-dollar figure are different facts and only one of them is true. The
provenance tests pin the other half of the rule: a cost is ``DERIVED`` only when the
vendor's own header supplied the character count.
"""

from __future__ import annotations

import pytest

from hbd.contracts import CostSource
from hbd.errors import ConfigError
from hbd.providers.tts.metering import (
    MIN_ESTIMATED_DURATION_S,
    CharacterPricing,
    estimate_speech_duration_s,
)

UZS_PER_USD = 12_500.0
UZS_PER_CHARACTER = 25.0


def test_an_unpriced_call_has_no_cost_at_all_rather_than_a_cost_of_zero() -> None:
    # Arrange
    pricing = CharacterPricing()

    # Act
    cost, source = pricing.cost_for(1_000, is_vendor_counted=True)

    # Assert — zero would be summed as spend; absent is the truth and stays absent.
    assert cost is None
    assert source is None


def test_derives_usd_from_a_uzs_rate() -> None:
    # Arrange
    pricing = CharacterPricing(rate_per_character=UZS_PER_CHARACTER, units_per_usd=UZS_PER_USD)

    # Act
    cost, source = pricing.cost_for(500, is_vendor_counted=True)

    # Assert
    assert cost == pytest.approx(500 * UZS_PER_CHARACTER / UZS_PER_USD)
    assert source is CostSource.DERIVED


def test_a_cost_over_our_own_character_count_is_estimated_not_derived() -> None:
    # Arrange
    pricing = CharacterPricing(rate_per_character=UZS_PER_CHARACTER, units_per_usd=UZS_PER_USD)

    # Act — the vendor sent no character-cost header, so we counted the text ourselves.
    cost, source = pricing.cost_for(500, is_vendor_counted=False)

    # Assert — same arithmetic, weaker provenance, and the row must say so.
    assert cost == pytest.approx(500 * UZS_PER_CHARACTER / UZS_PER_USD)
    assert source is CostSource.ESTIMATED


def test_reports_the_vendor_currency_figure_an_invoice_will_show() -> None:
    # Arrange
    pricing = CharacterPricing(rate_per_character=UZS_PER_CHARACTER, units_per_usd=UZS_PER_USD)

    # Act / Assert
    assert pricing.units_for(200) == pytest.approx(5_000.0)


def test_zero_characters_cost_nothing() -> None:
    # Arrange
    pricing = CharacterPricing(rate_per_character=1.0)

    # Act
    cost, _ = pricing.cost_for(0, is_vendor_counted=True)

    # Assert
    assert cost == 0.0


def test_rejects_a_negative_rate() -> None:
    # Act / Assert
    with pytest.raises(ConfigError, match="rate_per_character"):
        CharacterPricing(rate_per_character=-1.0)


def test_rejects_a_non_positive_conversion_rate() -> None:
    # Act / Assert
    with pytest.raises(ConfigError, match="units_per_usd"):
        CharacterPricing(units_per_usd=0.0)


def test_rejects_a_negative_character_count() -> None:
    # Arrange
    pricing = CharacterPricing()

    # Act / Assert
    with pytest.raises(ConfigError, match="character_count"):
        pricing.cost_for(-1, is_vendor_counted=True)


def test_estimates_duration_from_the_spoken_length() -> None:
    # Arrange
    text = "a" * 140

    # Act
    duration = estimate_speech_duration_s(text, chars_per_second=14.0)

    # Assert
    assert duration == pytest.approx(10.0)


def test_a_very_short_line_still_has_a_positive_duration() -> None:
    # Act
    duration = estimate_speech_duration_s("Hi")

    # Assert — RenderedAudio.duration_s must be > 0 or the model rejects it.
    assert duration == MIN_ESTIMATED_DURATION_S


def test_rejects_a_non_positive_speaking_rate() -> None:
    # Act / Assert
    with pytest.raises(ConfigError, match="chars_per_second"):
        estimate_speech_duration_s("hello", chars_per_second=0.0)
