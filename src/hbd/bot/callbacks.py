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
