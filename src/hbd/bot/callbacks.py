"""Typed callback payloads.

Telegram gives 64 bytes of callback data; these factories keep every payload well inside
it and, more importantly, make an unparseable payload simply not match a handler instead
of raising inside one. That is the boundary validation for everything a button can send.
"""

from __future__ import annotations

from enum import StrEnum

from aiogram.filters.callback_data import CallbackData

from hbd.contracts import Genre, Language, Occasion, VoiceGender

__all__ = [
    "NavAction",
    "LanguageSlot",
    "LanguageCB",
    "OccasionCB",
    "GenreCB",
    "VocalGenderCB",
    "NavCB",
]


class NavAction(StrEnum):
    """Navigation and confirmation buttons shared across steps."""

    BACK = "back"
    SKIP = "skip"
    CANCEL = "cancel"
    CONFIRM = "confirm"
    NAME_OK = "name_ok"
    RETYPE = "retype"
    LYRICS_OK = "lyrics_ok"
    #: Ask for a different lyric. Abbreviated because the value is packed into the 64-byte
    #: callback payload; its BUTTON LABEL lives under ``button.regenerate``, so
    #: ``lyrics_keyboard`` draws this one explicitly instead of via the ``button.{value}``
    #: convention every other nav button follows.
    REGENERATE = "regen"
    #: The four buttons that exist so no message is a dead end. A screen that ends a flow —
    #: cancelled, expired, delivered, or a lyric the writer could not produce — leaves the
    #: user with nothing to do, and "send /start" is not an answer. These are what it
    #: carries instead. They spell their action out because every one of them is well
    #: inside the payload budget: ``nav:report_problem`` is 18 of the 64 bytes.
    START_OVER = "start_over"
    MAKE_ANOTHER = "make_another"
    REPORT_PROBLEM = "report_problem"
    TRY_AGAIN = "try_again"


class LanguageSlot(StrEnum):
    """Interface language and output language are chosen INDEPENDENTLY, by the same widget."""

    UI = "ui"
    OUTPUT = "out"


class LanguageCB(CallbackData, prefix="lang"):
    slot: LanguageSlot
    code: Language


class OccasionCB(CallbackData, prefix="occ"):
    value: Occasion


class GenreCB(CallbackData, prefix="gen"):
    value: Genre


class VocalGenderCB(CallbackData, prefix="voc"):
    value: VoiceGender


class NavCB(CallbackData, prefix="nav"):
    action: NavAction
