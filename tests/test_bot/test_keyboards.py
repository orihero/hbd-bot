"""Layout is a contract, so it is tested like one.

Every other bot test asserts that a button EXISTS. None of them could see the defect that
prompted this file: Back / Skip / Cancel packed into one row rendered as thirty-eight
characters in the default locale, wrapped on a phone, and looked broken — while passing
every "is the Skip button offered" assertion in the suite. A layout rule that only lives in
a docstring is a rule that gets broken by the next translator, in a locale the author does
not read.

So the rules are numbers in ``hbd.bot.keyboards`` and this module walks EVERY keyboard in
EVERY locale against them. That walk is the durable half of the fix; moving Skip onto its
own row was the easy half.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from hbd.bot.callbacks import LanguageSlot, NavAction, NavCB
from hbd.bot.i18n import translate
from hbd.bot.keyboards import (
    KEEP_NOTE_LABEL_KEY,
    MAX_ROW_BUTTONS,
    MAX_ROW_LABEL_CHARS,
    SKIP_LABEL_KEY,
    confirm_keyboard,
    genre_keyboard,
    language_keyboard,
    lyrics_failed_keyboard,
    lyrics_keyboard,
    lyrics_writing_keyboard,
    name_confirm_keyboard,
    name_prompt_keyboard,
    note_keyboard,
    occasion_keyboard,
    own_lyrics_keyboard,
    post_delivery_keyboard,
    start_over_keyboard,
    vocal_gender_keyboard,
)
from hbd.contracts import Language
from tests.test_bot.conftest import buttons

#: The prefix ``NavCB`` packs. A row whose every button carries it is a row this module
#: composed out of its own labels, as opposed to one generated from an enum whose labels
#: are translated content — see ``MAX_ROW_LABEL_CHARS`` for why the two are measured apart.
NAV_PREFIX = "nav:"


def every_keyboard(language: Language) -> Iterator[tuple[str, InlineKeyboardMarkup]]:
    """Every keyboard this bot can draw, named, in one language.

    Listed by hand on purpose. A generated list would silently skip a new builder — which
    is the one case these tests exist for — so a keyboard added without a line here fails
    ``test_every_keyboard_builder_is_covered`` instead of going unmeasured.
    """
    yield "language_ui", language_keyboard(LanguageSlot.UI, language, is_back_enabled=False)
    yield "language_output", language_keyboard(LanguageSlot.OUTPUT, language, is_back_enabled=True)
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
    yield "start_over", start_over_keyboard(language)
    yield "post_delivery", post_delivery_keyboard(language)


def is_nav_row(row: list[InlineKeyboardButton]) -> bool:
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


def test_the_first_screen_draws_cancel_without_back() -> None:
    """Back on the first screen would have nowhere to go, so the row is one button."""
    # Arrange / Act
    rows = language_keyboard(LanguageSlot.UI, Language.EN, is_back_enabled=False).inline_keyboard

    # Assert
    assert [button.callback_data for button in rows[-1]] == [NavCB(action=NavAction.CANCEL).pack()]


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
def test_start_over_offers_exactly_one_way_out() -> None:
    """Every flow-ending message carries this. There is no state left to go back to."""
    # Arrange / Act
    offered = buttons(start_over_keyboard(Language.EN))

    # Assert
    assert [data for _, data in offered] == [NavCB(action=NavAction.START_OVER).pack()]


def test_post_delivery_offers_another_song_and_a_way_to_complain() -> None:
    # Arrange / Act
    markup = post_delivery_keyboard(Language.EN)

    # Assert — one per row: a next purchase and a complaint are not a matched pair
    assert [[button.callback_data for button in row] for row in markup.inline_keyboard] == [
        [NavCB(action=NavAction.MAKE_ANOTHER).pack()],
        [NavCB(action=NavAction.REPORT_PROBLEM).pack()],
    ]


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
    """``every_keyboard`` is hand-written, so it can fall behind the module it measures.

    The rules above are only as good as the list they walk. This compares that list against
    the module's own ``__all__``, so a builder added without a line in ``every_keyboard``
    fails here rather than shipping unmeasured.
    """
    # Arrange
    from hbd.bot import keyboards

    exported = {
        name
        for name in keyboards.__all__
        if name.endswith("_keyboard") and callable(getattr(keyboards, name))
    }

    # Act
    covered = {markup for markup, _ in every_keyboard(Language.EN)}

    # Assert — every builder appears at least once, under its own name minus the suffix
    missing = {
        name
        for name in exported
        if not any(entry.startswith(name[: -len("_keyboard")]) for entry in covered)
    }
    assert not missing, f"keyboards built but never measured: {sorted(missing)}"
