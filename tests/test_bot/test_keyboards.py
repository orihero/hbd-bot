"""Layout is a contract, so it is tested like one.

Every other bot test asserts that a button EXISTS. None of them could see the defect that
prompted this file: Back / Skip / Cancel packed into one row rendered as thirty-eight
characters in the default locale, wrapped on a phone, and looked broken — while passing
every "is the Skip button offered" assertion in the suite. A layout rule that only lives in
a docstring is a rule that gets broken by the next translator, in a locale the author does
not read.

So the rules are numbers in ``bayram.bot.keyboards`` and this module walks EVERY keyboard in
EVERY locale against them. That walk is the durable half of the fix; moving Skip onto its
own row was the easy half.

There are now TWO walks, because there are two kinds of keyboard. An inline markup rides on
one message and is laid out inside the bubble; a REPLY markup is chat-level state drawn at
full viewport width under the composer. They are read through different attributes
(``inline_keyboard`` versus ``keyboard``), carry different button types (a
:class:`KeyboardButton` has no ``callback_data`` at all) and are measured against different
budgets. Keeping the two registers apart is what stops a width test from having to ask what
kind of thing it is holding — the ``isinstance`` branch that is how a walk quietly stops
covering one half.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup

from bayram.bot.callbacks import LanguageSlot, NavAction, NavCB
from bayram.bot.i18n import translate
from bayram.bot.keyboards import (
    KEEP_NOTE_LABEL_KEY,
    MAX_REPLY_ROW_LABEL_CHARS,
    MAX_ROW_BUTTONS,
    MAX_ROW_LABEL_CHARS,
    SKIP_LABEL_KEY,
    checkout_keyboard,
    checkout_link_keyboard,
    confirm_keyboard,
    contact_request_keyboard,
    genre_keyboard,
    language_keyboard,
    lyrics_failed_keyboard,
    lyrics_keyboard,
    lyrics_writing_keyboard,
    main_menu_keyboard,
    name_confirm_keyboard,
    name_prompt_keyboard,
    note_keyboard,
    occasion_keyboard,
    own_lyrics_keyboard,
    paid_late_keyboard,
    post_delivery_keyboard,
    settings_keyboard,
    start_over_keyboard,
    vocal_gender_keyboard,
)
from bayram.bot.pricing import CheckoutOffer, Pricing
from bayram.contracts import Language
from tests.test_bot.conftest import buttons

#: The prefix ``NavCB`` packs. A row whose every button carries it is a row this module
#: composed out of its own labels, as opposed to one generated from an enum whose labels
#: are translated content — see ``MAX_ROW_LABEL_CHARS`` for why the two are measured apart.
NAV_PREFIX = "nav:"

#: The prices these registers measure the two purchase labels against.
#:
#: The SHIPPED defaults, written out rather than read from a ``Settings`` fixture, because
#: this register is imported at module scope by ``test_locale_contract.py`` and a fixture
#: cannot be reached from there. Written out rather than invented, because the width rule is
#: the thing under test and a label is only as wide as the digits in it:
#: "💳 49 000 soʻm — 1 qoʻshiq" is five characters wider than "💳 700 soʻm — 1 qoʻshiq", so a
#: register priced at 700 would pass while the shipped build wrapped on a phone. If
#: ``Settings``' defaults move, ``tests/test_bot/test_pricing.py`` is what fails.
SAMPLE_PRICING: Pricing = Pricing(
    single_amount_minor=700_000,
    plan_amount_minor=4_900_000,
    plan_songs=12,
    plan_days=30,
    currency="UZS",
    # `True` although the shipped default is now False, and the two prices above are the
    # pre-2026-09-14 ones for the same reason: these are KEYBOARD tests, and the row they
    # exist to measure is the plan row. A fixture that mirrored the live catalogue would draw
    # one button and quietly stop testing the two-row width rule the module docstring argues
    # for. What the deployment sells is `Settings.is_starter_plan_offered`; what this file
    # tests is what the builder draws when asked to draw it.
    is_plan_sold=True,
)


#: The URL the redirect register's 🔗 button points at.
#:
#: Payme's own documented golden vector — ``m=587f72c72cac0d162c722ae2;ac.order_id=197;a=500``
#: base64-encoded onto the production checkout host — rather than an invented
#: ``https://example.com``. It costs nothing and it means a reader of this register sees the
#: actual shape of the thing the button carries: a host and one opaque blob, with no query
#: string and nothing percent-encoded. Written out rather than imported from
#: ``bayram.payme.link``, because this module is imported at MODULE SCOPE by
#: ``test_locale_contract.py`` and the keyboard register must not drag a payment package into
#: the import graph of the catalogue tests.
SAMPLE_CHECKOUT_URL = (
    "https://checkout.paycom.uz/bT01ODdmNzJjNzJjYWMwZDE2MmM3MjJhZTI7YWMub3JkZXJfaWQ9MTk3O2E9NTAw"
)


def sample_offer(*, is_plan_offered: bool) -> CheckoutOffer:
    """A paywalled offer, with and without the plan button.

    Both shapes are registered below because they are different KEYBOARDS — one row or
    two — and the second one is what a customer with a spent-but-running plan sees. A
    register that yielded only the two-button shape would leave the top-up screen
    unmeasured in all four locales, which is the exact gap ``every_keyboard`` exists to
    close.
    """
    return CheckoutOffer(
        is_paywalled=True,
        credits=0,
        plan_songs_left=0,
        plan_ends_on=None if is_plan_offered else "2026-04-20",
        is_plan_offered=is_plan_offered,
        pricing=SAMPLE_PRICING,
    )


def every_keyboard(language: Language) -> Iterator[tuple[str, InlineKeyboardMarkup]]:
    """Every INLINE keyboard this bot can draw, named, in one language.

    Listed by hand on purpose. A generated list would silently skip a new builder — which
    is the one case these tests exist for — so a keyboard added without a line here fails
    ``test_every_keyboard_builder_is_covered`` instead of going unmeasured.

    Four of these entries come out of ONE builder. ``language_keyboard`` serves four screens
    that differ only in the navigation drawn around the same four buttons, and the register
    names all four because the differences are the thing under test: ``language_ui`` is the
    wizard shape (Cancel, no Back), ``language_output`` is the step inside a run (both),
    ``language_onboarding`` is the very first screen a customer sees (neither) and
    ``language_settings`` is the picker inside Settings (neither, plus a ``TO_SETTINGS`` row).
    Yield only one of them and ``is_cancel_enabled`` goes unmeasured on the two screens it
    was added for. The names are also load-bearing beyond this file: the duplicate-emoji
    carve-out in ``test_locale_contract.py`` is COMPUTED from the ``language_`` prefix, so a
    fifth language shape added here inherits the carve-out instead of needing a new entry in
    a hand-listed set that nobody would remember to update.

    ``settings_language_keyboard`` is deliberately absent because it does not exist: the
    settings picker is a screen (``screens.settings_language_screen``) composed from
    ``language_keyboard``, and a screen is not a builder.
    """
    yield "language_ui", language_keyboard(LanguageSlot.UI, language, is_back_enabled=False)
    yield "language_output", language_keyboard(LanguageSlot.OUTPUT, language, is_back_enabled=True)
    yield (
        "language_onboarding",
        language_keyboard(
            LanguageSlot.UI, language, is_back_enabled=False, is_cancel_enabled=False
        ),
    )
    yield (
        "language_settings",
        language_keyboard(
            LanguageSlot.SETTINGS,
            language,
            is_back_enabled=False,
            is_cancel_enabled=False,
            tail_action=NavAction.TO_SETTINGS,
        ),
    )
    yield "occasion", occasion_keyboard(language)
    yield "genre", genre_keyboard(language)
    yield "vocal_gender", vocal_gender_keyboard(language)
    yield "note", note_keyboard(language)
    yield "note_with_a_note_already_written", note_keyboard(language, is_note_present=True)
    yield "name_prompt", name_prompt_keyboard(language)
    yield "name_confirm", name_confirm_keyboard(language)
    yield "lyrics", lyrics_keyboard(language)
    yield "lyrics_the_customer_wrote", lyrics_keyboard(language, is_own_lyrics=True)
    yield "own_lyrics_prompt", own_lyrics_keyboard(language)
    yield "lyrics_writing", lyrics_writing_keyboard(language)
    yield "lyrics_failed", lyrics_failed_keyboard(language)
    yield "confirm", confirm_keyboard(language)
    yield "checkout", checkout_keyboard(language, sample_offer(is_plan_offered=True))
    yield (
        "checkout_with_a_plan_already_running",
        checkout_keyboard(language, sample_offer(is_plan_offered=False)),
    )
    yield "checkout_link", checkout_link_keyboard(language, SAMPLE_CHECKOUT_URL)
    yield "start_over", start_over_keyboard(language)
    yield "paid_late", paid_late_keyboard(language)
    yield "post_delivery", post_delivery_keyboard(language)
    yield "settings", settings_keyboard(language)


def every_reply_keyboard(language: Language) -> Iterator[tuple[str, ReplyKeyboardMarkup]]:
    """Every REPLY keyboard this bot can draw, named, in one language.

    Separate from :func:`every_keyboard` rather than a union, because the two kinds are
    measured against different budgets and read through different attributes: an inline row
    is ``markup.inline_keyboard`` and lives inside ``MAX_ROW_LABEL_CHARS``, while a reply row
    is ``markup.keyboard``, is drawn by Telegram's own keyboard chrome at full viewport
    width, and gets the wider ``MAX_REPLY_ROW_LABEL_CHARS``. A single generator returning
    both would have forced an ``isinstance`` into every width test, which is how a walk
    quietly stops covering one half.

    Both registers are unioned by ``test_every_keyboard_builder_is_covered``, so a reply
    builder that enters ``keyboards.__all__`` without a line here still fails loudly.
    """
    yield "main_menu", main_menu_keyboard(language)
    yield "contact_request", contact_request_keyboard(language)


def is_nav_row(row: list[InlineKeyboardButton]) -> bool:
    """True when every button in this INLINE row carries ``NavCB`` data.

    Do not call this from the reply-keyboard tests and do not make it defensive. A
    :class:`aiogram.types.KeyboardButton` has no ``callback_data`` attribute at all, so the
    obvious "fix" — a ``getattr(button, "callback_data", "")`` — would make every reply row
    read as an all-``nav:`` row and therefore as a NAVIGATION row, silently measuring the
    main menu against the inline budget it was given its own number to escape. The reply
    tests below deliberately measure every row instead of classifying them.
    """
    return all((button.callback_data or "").startswith(NAV_PREFIX) for button in row)


def row_width(row: list[InlineKeyboardButton]) -> int:
    return sum(len(button.text) for button in row)


# ---------------------------------------------------------------------------
# the layout rules, over every keyboard in every locale
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("language", list(Language))
def test_no_row_carries_more_than_two_buttons(language: Language) -> None:
    """The two-column rule the module docstring has always claimed, now enforced."""
    # Arrange / Act / Assert
    for name, markup in every_keyboard(language):
        for row in markup.inline_keyboard:
            assert len(row) <= MAX_ROW_BUTTONS, (
                f"{name} in {language.value} has a row of {len(row)}: "
                f"{[button.text for button in row]}"
            )


@pytest.mark.parametrize("language", list(Language))
def test_no_navigation_row_is_wider_than_the_budget(language: Language) -> None:
    """The regression fence. Back / Skip / Cancel in uz_latn was 38 characters wide.

    Measured on the RENDERED labels, in every locale, because the number that broke was a
    translation's and not the author's: ``Skip`` is four characters and
    ``Oʻtkazib yuborish`` is seventeen. A future label that needs more room than this fails
    here, in a locale nobody on the team reads, rather than on a customer's phone.
    """
    # Arrange / Act / Assert
    for name, markup in every_keyboard(language):
        for row in markup.inline_keyboard:
            if not is_nav_row(row):
                continue
            assert row_width(row) <= MAX_ROW_LABEL_CHARS, (
                f"{name} in {language.value} draws a {row_width(row)}-character row: "
                f"{[button.text for button in row]}"
            )


@pytest.mark.parametrize("language", list(Language))
def test_no_genre_row_is_wider_than_the_budget(language: Language) -> None:
    """The genre labels are the longest translated content the wizard shows.

    ``MAX_ROW_LABEL_CHARS`` exempts enum rows as a class, because a genre is called what it
    is called in each language and no budget should force a worse word. That exemption is
    not permission to truncate: at two columns
    ``Акустическая баллада | Танцевальная / электронная`` was 46 characters and
    ``Oʻzbek estradasi | Oʻzbek xalq qoʻshigʻi`` was 37, and Telegram splits a row evenly
    and cuts whatever does not fit — so the second button of each lost its tail mid-word.
    ``GENRE_COLUMNS`` is the lever the module names for exactly this, and at one column the
    row is the label. This fails if anyone widens it back.
    """
    # Arrange / Act / Assert
    _name, markup = next(pair for pair in every_keyboard(language) if pair[0] == "genre")
    for row in markup.inline_keyboard:
        if is_nav_row(row):
            continue
        assert row_width(row) <= MAX_ROW_LABEL_CHARS, (
            f"the genre keyboard in {language.value} draws a {row_width(row)}-character "
            f"row: {[button.text for button in row]}"
        )


@pytest.mark.parametrize("language", list(Language))
def test_no_reply_row_carries_more_than_two_buttons(language: Language) -> None:
    """The two-column rule again, on the surface where breaking it is permanent.

    A reply keyboard is not redrawn per message: ``is_persistent=True`` pins it under the
    composer and it stays there, in the shape it was last sent, until something sends a new
    one. An inline row that wraps is one ugly message; a menu row that wraps is every screen
    the customer sees from then on, including the ones that never mention the menu.
    """
    # Arrange / Act / Assert
    for name, markup in every_reply_keyboard(language):
        for row in markup.keyboard:
            assert len(row) <= MAX_ROW_BUTTONS, (
                f"{name} in {language.value} has a row of {len(row)}: "
                f"{[button.text for button in row]}"
            )


@pytest.mark.parametrize("language", list(Language))
def test_no_reply_row_is_wider_than_the_budget(language: Language) -> None:
    """Every reply row, not just the hand-composed ones, because every one of them is.

    The inline walk skips rows generated from an enum, whose labels are translated CONTENT
    this codebase does not get to shorten. A reply keyboard has no such rows: the menu's
    four labels and the contact button's one are all phrases chosen here, so all of them are
    measured and the ``is_nav_row`` classification is deliberately not consulted.

    ``MAX_REPLY_ROW_LABEL_CHARS`` is 34 rather than the inline 30 because the row is laid
    out at full viewport width instead of inside a message bubble. The widest row this build
    draws is ru ``🎵 Сделать песню`` + ``🎫 Мой лимит`` at 26, then uz_latn and en at 25. A
    translation that needs more room than 34 makes the keyboard one column; it does not make
    the number bigger, and this fails when somebody tries the latter.
    """
    # Arrange / Act / Assert
    for name, markup in every_reply_keyboard(language):
        for row in markup.keyboard:
            width = sum(len(button.text) for button in row)
            assert width <= MAX_REPLY_ROW_LABEL_CHARS, (
                f"{name} in {language.value} draws a {width}-character row: "
                f"{[button.text for button in row]}"
            )


@pytest.mark.parametrize("language", list(Language))
def test_no_reply_button_is_left_showing_a_raw_locale_key(language: Language) -> None:
    """The same ``translate``-returns-the-key hazard, on labels no inline walk can see.

    ``buttons()`` refuses a reply markup by design, so the check below reads ``keyboard``
    directly. Without it a typo in ``MENU_GENERATE_LABEL_KEY`` would pin a button reading
    ``menu.generat`` under the composer of every customer who has ever opened the bot — and
    because ``MENU_LABELS`` is computed from the same key, the button would even route.
    """
    # Arrange / Act / Assert
    for name, markup in every_reply_keyboard(language):
        for row in markup.keyboard:
            for button in row:
                assert not button.text.startswith(("menu.", "button.")), (
                    f"{name} in {language.value}: {button.text}"
                )
                assert button.text.strip(), f"{name} in {language.value} has a blank label"


@pytest.mark.parametrize("language", list(Language))
def test_no_button_is_left_showing_a_raw_locale_key(language: Language) -> None:
    """``translate`` returns the key rather than raising, so a typo ships as a label.

    Two builders override the ``button.{action.value}`` convention — regenerate and the
    note step's keep-this-note — and an override is exactly where a wrong key hides.
    """
    # Arrange / Act / Assert
    for name, markup in every_keyboard(language):
        for text, _ in buttons(markup):
            assert not text.startswith("button."), f"{name} in {language.value}: {text}"
            assert text.strip(), f"{name} in {language.value} has a blank label"


# ---------------------------------------------------------------------------
# the navigation row itself
# ---------------------------------------------------------------------------
def test_skip_sits_on_its_own_row_above_back_and_cancel() -> None:
    """Skip is an answer to the question, not navigation, and it is what made three."""
    # Arrange / Act
    rows = note_keyboard(Language.UZ_LATN).inline_keyboard

    # Assert
    skip, tail = rows[-2], rows[-1]
    assert [button.callback_data for button in skip] == [NavCB(action=NavAction.SKIP).pack()]
    assert [button.callback_data for button in tail] == [
        NavCB(action=NavAction.BACK).pack(),
        NavCB(action=NavAction.CANCEL).pack(),
    ]


def test_a_wizard_language_screen_draws_cancel_without_back() -> None:
    """Back at the top of a RUN would have nowhere to go, so the row is one button.

    This is the parked-draft shape — a draft sitting in ``Wizard:ui_language`` from before
    onboarding existed. It is inside a wizard run, so Cancel is the honest offer and stays;
    what it does not have is a previous step. The sibling below is the screen where Cancel
    itself had to go.
    """
    # Arrange / Act
    rows = language_keyboard(LanguageSlot.UI, Language.EN, is_back_enabled=False).inline_keyboard

    # Assert
    assert [button.callback_data for button in rows[-1]] == [NavCB(action=NavAction.CANCEL).pack()]


def test_the_onboarding_language_screen_draws_neither() -> None:
    """``is_back_enabled=False`` alone was not enough, and the leftover button lied.

    ``_with_nav`` used to append Cancel unconditionally, so switching Back off still left
    ✖️ Cancel on the very FIRST screen a customer ever sees and on the Settings language
    picker. Neither is a wizard run. Pressing it reaches ``navigation.handle_cancel``, which
    is stateless by design, so somebody who had opened the bot for the first time — or who
    had gone to Settings to change their language — was answered "Cancelled — nothing was
    made, and nothing was kept" about a run they never started. ``is_cancel_enabled`` exists
    for exactly these two screens, and the assertion is that the LAST row is still languages:
    no navigation was appended at all.
    """
    # Arrange / Act
    rows = language_keyboard(
        LanguageSlot.UI, Language.EN, is_back_enabled=False, is_cancel_enabled=False
    ).inline_keyboard

    # Assert — every row, the last one included, is a language row and not a nav row
    assert rows
    assert not any(is_nav_row(row) for row in rows)
    assert all((button.callback_data or "").startswith("lang:") for row in rows for button in row)


# ---------------------------------------------------------------------------
# the note step's Skip, which used to lie
# ---------------------------------------------------------------------------
def test_the_note_step_offers_skip_when_there_is_no_note_to_keep() -> None:
    # Arrange / Act
    labels = {data: text for text, data in buttons(note_keyboard(Language.EN))}

    # Assert
    assert labels[NavCB(action=NavAction.SKIP).pack()] == translate(SKIP_LABEL_KEY, Language.EN)


def test_the_note_step_offers_to_keep_a_note_that_already_exists() -> None:
    """Reached again through Back there IS a note, and Skip preserves it — so it says so.

    Same action and same callback data: the handler's job did not change, only the promise
    the label makes. It had been making the wrong one over six hundred characters the
    customer would have had to retype from memory.
    """
    # Arrange / Act
    labels = {
        data: text for text, data in buttons(note_keyboard(Language.EN, is_note_present=True))
    }

    # Assert
    assert labels[NavCB(action=NavAction.SKIP).pack()] == translate(
        KEEP_NOTE_LABEL_KEY, Language.EN
    )


@pytest.mark.parametrize("language", list(Language))
def test_keeping_and_skipping_are_worded_differently_in_every_locale(
    language: Language,
) -> None:
    """A translation that reuses one word for both puts the old, destructive promise back."""
    # Arrange / Act
    skip = translate(SKIP_LABEL_KEY, language)
    keep = translate(KEEP_NOTE_LABEL_KEY, language)

    # Assert
    assert skip != keep


# ---------------------------------------------------------------------------
# the keyboards that exist so no message is a dead end
# ---------------------------------------------------------------------------
def test_start_over_offers_a_fresh_run_and_the_way_home() -> None:
    """Every flow-ending message carries this. There is no state left to go back to.

    It used to offer ONE thing, and that was the defect: "start another wizard run" is not
    what somebody wants after a cancellation, an expiry or a credit refusal half as often as
    they want their balance, their settings or the help text. Until 🏠 Back to menu the only
    route to any of those was a tap on a persistent reply keyboard the customer is free to
    collapse — which made this builder one of the last two dead ends in the product.

    Asserted as an exact ordered list rather than a membership check, because the ORDER is
    the decision: Start over first, because it is what most readers of a dead-end message
    came back for.
    """
    # Arrange / Act
    offered = buttons(start_over_keyboard(Language.EN))

    # Assert
    assert [data for _, data in offered] == [
        NavCB(action=NavAction.START_OVER).pack(),
        NavCB(action=NavAction.TO_MENU).pack(),
    ]


def test_post_delivery_offers_another_song_a_way_to_complain_and_the_way_home() -> None:
    # Arrange / Act
    markup = post_delivery_keyboard(Language.EN)

    # Assert — one per row: a next purchase and a complaint are not a matched pair, and the
    # way home sits BELOW the complaint so the three read as "again / something was wrong /
    # done" rather than putting an exit between an order and a grievance
    assert [[button.callback_data for button in row] for row in markup.inline_keyboard] == [
        [NavCB(action=NavAction.MAKE_ANOTHER).pack()],
        [NavCB(action=NavAction.REPORT_PROBLEM).pack()],
        [NavCB(action=NavAction.TO_MENU).pack()],
    ]


@pytest.mark.parametrize("language", list(Language))
def test_a_dead_end_offers_the_way_home(language: Language) -> None:
    """In every locale, both dead ends. The exact-shape tests above only cover ``en``.

    The two assertions are not redundant: those pin the ORDER of the rows in one language,
    this pins the EXISTENCE of the exit in all four. A locale is exactly where the row would
    go missing, because the only way to lose it is a builder that branches on something —
    and nothing here should ever branch on the language.

    Both keyboards end a flow. ``start_over_keyboard`` closes a cancellation, an expiry or a
    credit refusal; ``post_delivery_keyboard`` closes a delivered song. Neither has a Back
    or a Cancel, because there is no state left and no run left, so without ``TO_MENU`` the
    only exit is a typed command or a reply keyboard the customer may have collapsed. On a
    phone, that is not an exit.
    """
    # Arrange
    home = NavCB(action=NavAction.TO_MENU).pack()

    # Act
    dead_ends = {
        "start_over": buttons(start_over_keyboard(language)),
        "post_delivery": buttons(post_delivery_keyboard(language)),
        "paid_late": buttons(paid_late_keyboard(language)),
    }

    # Assert
    for name, offered in dead_ends.items():
        assert home in [data for _, data in offered], f"{name} in {language.value}"


@pytest.mark.parametrize("language", list(Language))
def test_the_paid_late_keyboard_offers_the_confirm_button_the_wizard_draws(
    language: Language,
) -> None:
    """Byte-equal callback data, and that equality is the design rather than a coincidence.

    The 🎬 under "your payment landed" must be the customer's OWN press reached from another
    message, not a second route to a render: ``handlers.confirm.handle_confirm`` is registered
    on ``Wizard.confirm`` plus this exact filter, so an equal ``callback_data`` lands in the
    ordinary handler, inside the dispatcher's per-chat lock, with all four ordered double-tap
    defences intact. A button carrying anything else would need defences of its own.
    """
    # Arrange
    confirm = [data for _, data in buttons(confirm_keyboard(language))]

    # Act
    offered = [data for _, data in buttons(paid_late_keyboard(language))]

    # Assert
    assert offered[0] == NavCB(action=NavAction.CONFIRM).pack()
    assert offered[0] in confirm


@pytest.mark.parametrize("language", list(Language))
def test_the_paid_late_keyboard_carries_nothing_that_throws_the_draft_away(
    language: Language,
) -> None:
    """**The standing regression guard**, and the reason this builder exists at all.

    ``start_over_keyboard`` was what the settlement message used to carry, and its ↩️ routes
    ``NavAction.START_OVER`` to ``common.reset_to_welcome`` — "a clean slate, every time". So
    the only prominent button under a 15 000 soʻm receipt destroyed the draft it had been paid
    for. ``CANCEL`` is checked for the same reason wearing a politer label.
    """
    # Act
    offered = [data for _, data in buttons(paid_late_keyboard(language))]

    # Assert
    assert NavCB(action=NavAction.START_OVER).pack() not in offered
    assert NavCB(action=NavAction.CANCEL).pack() not in offered


# ---------------------------------------------------------------------------
# the one keyboard that leaves Telegram
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("language", list(Language))
def test_the_pay_link_row_is_deliberately_not_a_navigation_row(language: Language) -> None:
    """The exemption the URL button buys, pinned as a decision instead of an accident.

    :func:`is_nav_row` classifies by ``button.callback_data or ""``, and a ``url=`` button has
    none at all — so this row is silently invisible to
    ``test_no_navigation_row_is_wider_than_the_budget``. That is fine and it is not a hole,
    but "fine" has to be written down: the day somebody gives this builder a second URL button
    beside the first, or a long label, no existing rule would notice. So the classification is
    asserted rather than assumed, in both directions — the pay row is NOT navigation, and the
    🏠 row underneath it IS, which is what keeps it inside the budget that already exists.
    """
    # Arrange / Act
    rows = checkout_link_keyboard(language, SAMPLE_CHECKOUT_URL).inline_keyboard

    # Assert
    assert len(rows) == 2, [[button.text for button in row] for row in rows]
    pay, home = rows
    assert not is_nav_row(pay)
    assert [button.url for button in pay] == [SAMPLE_CHECKOUT_URL]
    assert [button.callback_data for button in pay] == [None]
    assert is_nav_row(home)
    assert [button.callback_data for button in home] == [NavCB(action=NavAction.TO_MENU).pack()]


@pytest.mark.parametrize("language", list(Language))
def test_the_pay_link_row_is_measured_even_though_the_nav_budget_skips_it(
    language: Language,
) -> None:
    """The width rule the exemption above removed, put back by hand for this one row.

    Telegram splits a row's width evenly and truncates the overflow whether the button carries
    a URL or a callback, so the physics ``MAX_ROW_LABEL_CHARS`` describes apply here exactly as
    they do to a nav row — only the CLASSIFIER cannot see this one. A truncated 🔗 label is the
    worst place in the product to have one: it is the last thing a customer reads before
    leaving Telegram with money in hand.
    """
    # Arrange / Act
    pay = checkout_link_keyboard(language, SAMPLE_CHECKOUT_URL).inline_keyboard[0]

    # Assert
    assert row_width(pay) <= MAX_ROW_LABEL_CHARS, (
        f"the pay-link row in {language.value} is {row_width(pay)} characters: "
        f"{[button.text for button in pay]}"
    )


def test_a_screen_whose_only_control_left_telegram_would_strand_the_customer() -> None:
    """Two rows, and the second one is the whole reason this is not a one-button keyboard.

    A customer who taps 🔗, looks at the payment page and decides against it comes back to
    this message. With only the link on it there is nothing to press: the way out would be a
    typed command or a persistent reply keyboard they are free to have collapsed, which is the
    dead end ``start_over_keyboard`` and ``post_delivery_keyboard`` both grew 🏠 for.

    ``TO_MENU`` and not ``BACK`` or ``CANCEL``, asserted here because the choice is invisible
    in the markup: Back's destination is a function of the FSM and this screen is drawn from
    ``/balance`` as well, where there is no wizard state to go back through, while Cancel is
    stateless and would answer "nothing was made, and nothing was kept" to somebody returning
    from a payment that went through.
    """
    # Arrange / Act
    offered = buttons(checkout_link_keyboard(Language.EN, SAMPLE_CHECKOUT_URL))

    # Assert
    assert [data for _, data in offered] == ["", NavCB(action=NavAction.TO_MENU).pack()]


def test_the_writing_screen_can_be_escaped() -> None:
    """Forty-five seconds with nothing to press is indistinguishable from a hung bot."""
    # Arrange / Act
    offered = buttons(lyrics_writing_keyboard(Language.EN))

    # Assert
    assert [data for _, data in offered] == [NavCB(action=NavAction.CANCEL).pack()]


def test_a_failed_write_names_the_retry_instead_of_implying_it() -> None:
    """The old failure path left "press the button already ticked" as the undocumented retry."""
    # Arrange / Act
    offered = {data for _, data in buttons(lyrics_failed_keyboard(Language.EN))}

    # Assert
    assert offered == {
        NavCB(action=NavAction.TRY_AGAIN).pack(),
        NavCB(action=NavAction.CANCEL).pack(),
    }


# ---------------------------------------------------------------------------
# the coverage this file's own rules depend on
# ---------------------------------------------------------------------------
def test_every_keyboard_builder_is_covered() -> None:
    """The registers are hand-written, so they can fall behind the module they measure.

    The rules above are only as good as the lists they walk. This compares BOTH registers
    against the module's own ``__all__``, so a builder added without a line in
    ``every_keyboard`` or ``every_reply_keyboard`` fails here rather than shipping
    unmeasured — which is the whole reason a new builder and its measurement have to land in
    one commit. Split them and the fastest route to green is to drop the name from
    ``__all__``, which defeats the one test whose purpose is that a keyboard cannot ship
    unmeasured.

    The union is over both registers rather than one widened one for the reason
    ``every_reply_keyboard``'s docstring gives: the two kinds are measured differently
    everywhere else, and only this test cares that they are the same population.
    """
    # Arrange
    from bayram.bot import keyboards

    exported = {
        name
        for name in keyboards.__all__
        if name.endswith("_keyboard") and callable(getattr(keyboards, name))
    }

    # Act
    covered = {name for name, _ in every_keyboard(Language.EN)}
    covered |= {name for name, _ in every_reply_keyboard(Language.EN)}

    # Assert — every builder appears at least once, under its own name minus the suffix
    missing = {
        name
        for name in exported
        if not any(entry.startswith(name[: -len("_keyboard")]) for entry in covered)
    }
    assert not missing, f"keyboards built but never measured: {sorted(missing)}"
