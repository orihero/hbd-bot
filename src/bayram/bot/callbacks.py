"""Typed callback payloads.

Telegram gives 64 bytes of callback data; these factories keep every payload well inside
it and, more importantly, make an unparseable payload simply not match a handler instead
of raising inside one. That is the boundary validation for everything a button can send.
"""

from __future__ import annotations

from enum import StrEnum

from aiogram.filters.callback_data import CallbackData

from bayram.contracts import Genre, Language, Occasion, VoiceGender

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
    #: "I will write the words myself", offered in the occasion list. It is a NAV button
    #: sitting among the occasion buttons rather than a fourth :class:`Occasion`, because it
    #: is not an answer to "what are we celebrating?" — it answers who writes the lyric, and
    #: an enum member would have had to be given a label, a prompt and a place in every
    #: brief the pipeline reasons about in order to say something the occasion is not about.
    OWN_LYRICS = "own_lyrics"
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
    #: The settings submenu, and the two ways back up out of it. They spell their action out
    #: for the reason the four above do: ``nav:set_language`` is 16 of the 64 bytes, so the
    #: payload budget buys nothing by abbreviating and an abbreviation costs a reader a
    #: lookup. All five follow the ``button.{action.value}`` convention, so none of them
    #: belongs in ``keyboards.py``'s documented exception block — which is where a reader
    #: goes to find out whether a button's label key was hand-picked, and finding nothing
    #: there is the answer.
    #:
    #: ``TO_MENU`` is drawn in three places and it is the same button in all three: the last
    #: row of the settings submenu, and one row of its own on ``start_over_keyboard`` and
    #: ``post_delivery_keyboard``. Those last two were the product's remaining dead ends —
    #: the only route home from a cancelled, expired or delivered flow was a tap on a
    #: persistent reply keyboard the customer may have collapsed.
    SET_LANGUAGE = "set_language"
    SHOW_PRIVACY = "show_privacy"
    SHOW_SUPPORT = "show_support"
    TO_MENU = "to_menu"
    TO_SETTINGS = "to_settings"
    #: The two buttons the Confirm screen wears when the account cannot afford a render:
    #: buy one song, or take the plan. They pack as ``nav:pay`` and ``nav:subscribe`` — 7
    #: and 13 of the 64 bytes — so there is nothing to abbreviate and both follow the
    #: ``button.{action.value}`` convention, which is why neither appears in
    #: ``keyboards.py``'s hand-picked-label exception block.
    #:
    #: They are NAV actions rather than a step of their own for the reason
    #: :class:`~bayram.bot.pricing.CheckoutOffer` sets out: the checkout is the Confirm screen
    #: wearing a second face, not a new place in the wizard, so nothing about
    #: ``WIZARD_ORDER``, ``previous_step`` or ``resolve_step``'s fixpoint moves for them.
    #:
    #: Their labels are also the FIRST in this product to interpolate a value — the price —
    #: which is why ``_nav_button`` grew ``label_params``. A price baked into four
    #: catalogues would silently disagree with ``BAYRAM_SINGLE_SONG_PRICE_MINOR`` the day an
    #: operator changed it; a price interpolated from ``Settings`` cannot.
    PAY = "pay"
    SUBSCRIBE = "subscribe"


class LanguageSlot(StrEnum):
    """Interface language and output language are chosen INDEPENDENTLY, by the same widget."""

    UI = "ui"
    OUTPUT = "out"
    #: The settings language picker. The settings screen carries NO FSM state — see
    #: ``keyboards.settings_keyboard`` — so the FSM can no longer tell the settings picker
    #: from the wizard's OUTPUT picker, and the payload has to. ``"set"`` rather than
    #: ``"settings"`` for the same reason ``NavAction.REGENERATE`` is ``"regen"``.
    SETTINGS = "set"


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
