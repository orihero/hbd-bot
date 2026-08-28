"""Inline keyboards, one builder per screen.

Two rules hold everywhere:

* Every keyboard is built from the enum it offers, so a new :class:`Genre` appears as a
  button without anyone editing this file — only its label has to exist in the catalogues.
* Every screen past the first carries a working Back button, and every screen carries
  Cancel. The Back button's *behaviour* comes from ``WIZARD_ORDER``; this module only draws
  it, so the two can never disagree.
"""

from __future__ import annotations

from typing import Final

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from hbd.bot.callbacks import (
    GenreCB,
    LanguageCB,
    LanguageSlot,
    NavAction,
    NavCB,
    OccasionCB,
    VocalGenderCB,
)
from hbd.bot.i18n import (
    SUPPORTED_LANGUAGES,
    genre_label,
    language_label,
    occasion_label,
    translate,
    vocal_gender_label,
)
from hbd.contracts import Genre, Language, Occasion, VoiceGender

__all__ = [
    "language_keyboard",
    "occasion_keyboard",
    "genre_keyboard",
    "vocal_gender_keyboard",
    "note_keyboard",
    "name_prompt_keyboard",
    "name_confirm_keyboard",
    "confirm_keyboard",
    "LANGUAGE_COLUMNS",
    "GENRE_COLUMNS",
    "OCCASION_COLUMNS",
    "VOCAL_GENDER_COLUMNS",
    "VOCAL_GENDER_CHOICES",
]

#: Layout widths. Telegram truncates a row that is too wide on a narrow phone, and Uzbek
#: labels are long, so nothing here goes past two columns.
LANGUAGE_COLUMNS: Final[int] = 2
GENRE_COLUMNS: Final[int] = 2
OCCASION_COLUMNS: Final[int] = 1
VOCAL_GENDER_COLUMNS: Final[int] = 2

#: Vocal options offered in the wizard. ``ANY`` is deliberately last: it is the escape
#: hatch, not the default.
VOCAL_GENDER_CHOICES: Final[tuple[VoiceGender, ...]] = (
    VoiceGender.FEMALE,
    VoiceGender.MALE,
    VoiceGender.DUET,
    VoiceGender.ANY,
)


def _nav_button(action: NavAction, language: Language) -> InlineKeyboardButton:
    return InlineKeyboardButton(
        text=translate(f"button.{action.value}", language),
        callback_data=NavCB(action=action).pack(),
    )


def _nav_row(
    language: Language,
    *,
    is_back_enabled: bool,
    is_skip_enabled: bool = False,
) -> tuple[InlineKeyboardButton, ...]:
    """Back / Skip / Cancel, in that reading order, omitting what does not apply."""
    buttons: list[InlineKeyboardButton] = []
    if is_back_enabled:
        buttons.append(_nav_button(NavAction.BACK, language))
    if is_skip_enabled:
        buttons.append(_nav_button(NavAction.SKIP, language))
    buttons.append(_nav_button(NavAction.CANCEL, language))
    return tuple(buttons)


def _with_nav(
    builder: InlineKeyboardBuilder,
    language: Language,
    *,
    is_back_enabled: bool,
    is_skip_enabled: bool = False,
) -> InlineKeyboardMarkup:
    builder.row(
        *_nav_row(language, is_back_enabled=is_back_enabled, is_skip_enabled=is_skip_enabled)
    )
    return builder.as_markup()


def language_keyboard(
    slot: LanguageSlot,
    language: Language,
    *,
    is_back_enabled: bool,
    offered: tuple[Language, ...] = SUPPORTED_LANGUAGES,
) -> InlineKeyboardMarkup:
    """The same widget serves both slots; ``slot`` is what tells the handlers apart.

    On the very first screen the interface language is not chosen yet, so labels are drawn
    in each language's own name — which is why ``language_label`` is asked for the label of
    ``value`` rather than a translation of the current locale's word for it.
    """
    builder = InlineKeyboardBuilder()
    for value in offered:
        builder.button(
            text=language_label(value, language),
            callback_data=LanguageCB(slot=slot, code=value),
        )
    builder.adjust(LANGUAGE_COLUMNS)
    return _with_nav(builder, language, is_back_enabled=is_back_enabled)


def occasion_keyboard(language: Language) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for value in Occasion:
        builder.button(text=occasion_label(value, language), callback_data=OccasionCB(value=value))
    builder.adjust(OCCASION_COLUMNS)
    return _with_nav(builder, language, is_back_enabled=True)


def genre_keyboard(language: Language) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for value in Genre:
        builder.button(text=genre_label(value, language), callback_data=GenreCB(value=value))
    builder.adjust(GENRE_COLUMNS)
    return _with_nav(builder, language, is_back_enabled=True)


def vocal_gender_keyboard(language: Language) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for value in VOCAL_GENDER_CHOICES:
        builder.button(
            text=vocal_gender_label(value, language), callback_data=VocalGenderCB(value=value)
        )
    builder.adjust(VOCAL_GENDER_COLUMNS)
    return _with_nav(builder, language, is_back_enabled=True)


def note_keyboard(language: Language) -> InlineKeyboardMarkup:
    """The note is typed, so this screen offers only navigation — including Skip."""
    return _with_nav(
        InlineKeyboardBuilder(), language, is_back_enabled=True, is_skip_enabled=True
    )


def name_prompt_keyboard(language: Language) -> InlineKeyboardMarkup:
    """The name is TYPED. There is no Skip: a kit without a name is not a product."""
    return _with_nav(InlineKeyboardBuilder(), language, is_back_enabled=True)


def name_confirm_keyboard(language: Language) -> InlineKeyboardMarkup:
    """Confirm the canonical DISPLAY spelling before a single token is generated."""
    builder = InlineKeyboardBuilder()
    builder.row(_nav_button(NavAction.NAME_OK, language))
    builder.row(_nav_button(NavAction.RETYPE, language))
    return _with_nav(builder, language, is_back_enabled=True)


def confirm_keyboard(language: Language) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(_nav_button(NavAction.CONFIRM, language))
    return _with_nav(builder, language, is_back_enabled=True)
