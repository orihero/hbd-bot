"""Prices: the minor-unit convention, the separator, and what the screen is allowed to know.

Two defects are pinned here, and both are the kind that ship silently.

**The separator is U+00A0 and not a plain space.** Telegram wraps a message body and a button
label at whatever width the customer's phone happens to be, and "49" at the end of one line
with "000 soʻm" at the start of the next reads as a different, far cheaper product. A plain
space is exactly the character that wraps, so the test asserts the codepoint rather than
merely asserting that the digits are grouped.

**Prices live in MINOR units everywhere except the last inch.** ``PaymentAuthorization``
already carries minor units and Payme quotes tiyin, so 700_000 is already the number a real
rail is sent; the only division by 100 in the system is for display. Storing 7000 and
multiplying at the rail is how a rounding bug becomes a pricing bug, and a pricing bug is
invisible until somebody has been charged the wrong amount.

``format_amount`` also never renders a currency word. That word differs across the four
locales — UZS, сум, soʻm, сўм — and lives in the catalogues where translators can reach it;
a price baked into those catalogues would disagree with ``HBD_SINGLE_SONG_PRICE_MINOR`` the
day an operator changed it, while a price interpolated into them cannot.
"""

from __future__ import annotations

import pytest

from hbd.bot.pricing import GROUPING_SPACE, CheckoutOffer, Pricing, format_amount
from hbd.config import Settings

#: Any URL parses; nothing here touches a database. ``database_url`` is simply the one
#: required field on the settings model.
_DATABASE_URL = "sqlite+aiosqlite:///:memory:"


# ---------------------------------------------------------------------------
# Formatting
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    ("amount_minor", "expected"),
    [
        (0, "0"),
        # Truncation, not rounding: rounding 99 tiyin up to "1" would put a price on screen
        # that the rail then does not charge. Under-showing is the direction that cannot
        # overcharge anybody, and every real price here is a whole number of soʻm anyway.
        (99, "0"),
        (100, "1"),
        (99_900, "999"),
        (100_000, "1 000"),
        (700_000, "7 000"),
        (4_900_000, "49 000"),
        (100_000_000, "1 000 000"),
    ],
)
def test_format_amount_renders_grouped_major_units(amount_minor: int, expected: str) -> None:
    # Arrange / Act
    rendered = format_amount(amount_minor)

    # Assert
    assert rendered == expected


def test_the_thousands_separator_is_a_no_break_space() -> None:
    # Arrange — a plain space is the character that wraps, and a price split across two lines
    # reads as a different product. Asserted by codepoint, because the two are visually
    # identical in a diff.
    rendered = format_amount(4_900_000)

    # Act / Assert
    assert GROUPING_SPACE == " "
    assert rendered == "49 000"
    assert " " not in rendered


def test_a_formatted_price_never_carries_a_currency_word() -> None:
    # Arrange — the word is per-language and belongs to the four locale catalogues. If it
    # ever leaks in here, three of the four locales are quietly wrong.
    # Act / Assert
    assert format_amount(700_000).isdigit() is False  # it is grouped, hence not all digits
    assert format_amount(700_000).replace(GROUPING_SPACE, "").isdigit()


# ---------------------------------------------------------------------------
# The catalogue
# ---------------------------------------------------------------------------
def test_pricing_from_settings_reads_the_four_price_fields_and_the_currency() -> None:
    # Arrange — the ONE place these settings are read. Everything downstream is handed a
    # ``Pricing``, so a handler can be priced differently in a test without patching imports.
    settings = Settings(_env_file=None, database_url=_DATABASE_URL)

    # Act
    pricing = Pricing.from_settings(settings)

    # Assert
    assert pricing.single_amount_minor == settings.single_song_price_minor
    assert pricing.plan_amount_minor == settings.starter_plan_price_minor
    assert pricing.plan_songs == settings.starter_plan_songs
    assert pricing.plan_days == settings.starter_plan_days
    assert pricing.currency == settings.kit_currency


def test_the_shipped_settings_price_a_song_at_seven_thousand_and_a_plan_at_forty_nine() -> None:
    # Arrange — the decided product, pinned as a drift guard between the plan and the code:
    # 7 000 for one recording, 49 000 for twelve songs across thirty days.
    settings = Settings(_env_file=None, database_url=_DATABASE_URL)

    # Act
    pricing = Pricing.from_settings(settings)

    # Assert
    assert pricing.single_amount == "7 000"
    assert pricing.plan_amount == "49 000"
    assert pricing.plan_songs == 12
    assert pricing.plan_days == 30
    assert pricing.currency == "UZS"


def test_an_operator_who_reprices_moves_the_button_label_with_them() -> None:
    # Arrange — the reason the price is interpolated into the catalogues rather than written
    # into them: a number baked into four locale files disagrees with the environment the day
    # somebody changes it, and nothing goes red.
    settings = Settings(
        _env_file=None,
        database_url=_DATABASE_URL,
        single_song_price_minor=1_250_000,
        starter_plan_price_minor=9_900_000,
    )

    # Act
    pricing = Pricing.from_settings(settings)

    # Assert
    assert pricing.single_amount == "12 500"
    assert pricing.plan_amount == "99 000"


# ---------------------------------------------------------------------------
# The offer
# ---------------------------------------------------------------------------
def test_a_checkout_offer_carries_only_finished_renderable_values() -> None:
    # Arrange — this object exists so ``hbd.bot.screens`` stays a pure function of the draft.
    # ``plan_ends_on`` is a plain YYYY-MM-DD string and not a datetime, because formatting a
    # date is a rendering decision and this value object exists so the renderer makes none.
    settings = Settings(_env_file=None, database_url=_DATABASE_URL)

    # Act
    offer = CheckoutOffer(
        is_paywalled=True,
        credits=0,
        plan_songs_left=0,
        plan_ends_on=None,
        is_plan_offered=True,
        pricing=Pricing.from_settings(settings),
    )

    # Assert
    assert offer.is_paywalled
    assert offer.plan_ends_on is None
    assert offer.pricing.single_amount == "7 000"


def test_a_spent_plan_is_still_a_running_plan_and_is_offered_no_second_one() -> None:
    # Arrange — the shape the checkout screen renders for a customer who used all twelve
    # songs early: a date is present, nothing is left to mint, and the plan button is gone so
    # a second plan cannot overwrite an end date they already paid for.
    settings = Settings(_env_file=None, database_url=_DATABASE_URL)

    # Act
    offer = CheckoutOffer(
        is_paywalled=True,
        credits=0,
        plan_songs_left=0,
        plan_ends_on="2026-10-06",
        is_plan_offered=False,
        pricing=Pricing.from_settings(settings),
    )

    # Assert
    assert offer.plan_ends_on == "2026-10-06"
    assert offer.plan_songs_left == 0
    assert not offer.is_plan_offered
