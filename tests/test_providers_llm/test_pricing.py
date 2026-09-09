"""Token pricing. An unpriced call has NO cost, and that is the whole test file.

``CharacterPricing`` answers ``(0.0, ESTIMATED)`` when nobody configured a rate, and the
speech leg lives with that. This one must not: an LLM row's ``cost_usd`` is nullable, the
vendor panel sums it, and a column of defaulted zeroes would tell an operator the
deployment spent nothing when the truth is that nobody set a rate. So every assertion
below that could be written ``== 0.0`` is written ``is None`` deliberately.
"""

from __future__ import annotations

import pytest

from hbd.contracts import CostSource
from hbd.errors import ConfigError
from hbd.providers.llm.pricing import TokenPricing

USD_PER_MILLION_PROMPT = 0.15
USD_PER_MILLION_COMPLETION = 0.60


def test_an_unconfigured_rate_card_reports_no_cost_at_all() -> None:
    # Arrange — the shipped default: no HBD_LLM_USD_PER_MILLION_* is set anywhere.
    pricing = TokenPricing()

    # Act
    cost, source = pricing.cost_for(1_000, 500)

    # Assert — `is None`, never `== 0.0`: a zero would read as "this call was free".
    assert cost is None
    assert source is None
    assert pricing.is_priced is False


def test_derives_usd_from_the_two_configured_rates() -> None:
    # Arrange
    pricing = TokenPricing(
        usd_per_million_prompt=USD_PER_MILLION_PROMPT,
        usd_per_million_completion=USD_PER_MILLION_COMPLETION,
    )

    # Act
    cost, source = pricing.cost_for(1_000_000, 1_000_000)

    # Assert
    assert cost == pytest.approx(USD_PER_MILLION_PROMPT + USD_PER_MILLION_COMPLETION)
    assert source is CostSource.DERIVED


def test_the_arithmetic_is_rounded_to_six_decimal_places() -> None:
    """Six places, because a single cheap call is worth fractions of a cent.

    Rounding to cents here would collapse thousands of real calls to zero and the daily
    total would be built from a column of them.
    """
    # Arrange
    pricing = TokenPricing(usd_per_million_prompt=USD_PER_MILLION_PROMPT)

    # Act
    cost, _ = pricing.cost_for(1_234, None)

    # Assert — 1_234 * 0.15 / 1e6 = 0.0001851, before rounding to 0.000185.
    assert cost == 0.000185


def test_a_configured_rate_with_no_reported_counts_still_reports_nothing() -> None:
    # Arrange — a vendor that returned no usage block at all.
    pricing = TokenPricing(usd_per_million_prompt=USD_PER_MILLION_PROMPT)

    # Act
    cost, source = pricing.cost_for(None, None)

    # Assert — the rate is known and the consumption is not, so the cost is unknown.
    assert cost is None
    assert source is None


def test_one_missing_count_contributes_nothing_and_the_rest_is_still_derived() -> None:
    """A half-reported response yields a floor, not a refusal and not an invention.

    The matching token column on the row stays NULL beside the figure, so the partial
    measurement is visible rather than dressed up as a complete one.
    """
    # Arrange
    pricing = TokenPricing(
        usd_per_million_prompt=USD_PER_MILLION_PROMPT,
        usd_per_million_completion=USD_PER_MILLION_COMPLETION,
    )

    # Act
    cost, source = pricing.cost_for(1_000_000, None)

    # Assert
    assert cost == pytest.approx(USD_PER_MILLION_PROMPT)
    assert source is CostSource.DERIVED


def test_a_negative_count_is_read_as_no_measurement() -> None:
    # Arrange
    pricing = TokenPricing(usd_per_million_prompt=USD_PER_MILLION_PROMPT)

    # Act
    cost, source = pricing.cost_for(-5, None)

    # Assert — a negative token count is not a measurement, so it prices nothing.
    assert cost is None
    assert source is None


def test_zero_counts_against_a_real_rate_cost_zero() -> None:
    # Arrange — distinct from the unpriced case above: here the rate IS known and the
    # vendor genuinely reported no tokens, so zero is the measurement.
    pricing = TokenPricing(usd_per_million_prompt=USD_PER_MILLION_PROMPT)

    # Act
    cost, source = pricing.cost_for(0, 0)

    # Assert
    assert cost == 0.0
    assert source is CostSource.DERIVED


@pytest.mark.parametrize(
    "rates",
    [
        {"usd_per_million_prompt": -0.01},
        {"usd_per_million_completion": -1.0},
    ],
)
def test_a_negative_rate_is_refused_at_construction(rates: dict[str, float]) -> None:
    # Arrange / Act / Assert — a rate arrives from config at startup, where a raise is a
    # readable boot failure rather than a lost song mid-call.
    with pytest.raises(ConfigError):
        TokenPricing(**rates)


def test_either_rate_alone_makes_the_card_priced() -> None:
    # Arrange / Act / Assert — a completion-only rate is a real posture (some gateways
    # bill prompt tokens at zero) and must not be read as "unconfigured".
    assert TokenPricing(usd_per_million_completion=USD_PER_MILLION_COMPLETION).is_priced is True
    assert TokenPricing(usd_per_million_prompt=USD_PER_MILLION_PROMPT).is_priced is True
