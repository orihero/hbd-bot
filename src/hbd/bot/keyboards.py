"""Inline keyboards, one builder per screen.

Three rules hold everywhere:

* Every keyboard is built from the enum it offers, so a new :class:`Genre` appears as a
  button without anyone editing this file — only its label has to exist in the catalogues.
* Every screen past the first carries a working Back button, and every screen carries
  Cancel. The Back button's *behaviour* comes from ``WIZARD_ORDER``; this module only draws
  it, so the two can never disagree.
* No row is wider than :data:`MAX_ROW_LABEL_CHARS`. The column constants below used to be
  the whole of that rule and they only covered the *generated* rows, so the hand-built
  navigation row quietly broke it: Back / Skip / Cancel in the default locale is
  ``⬅️ Orqaga``, ``Oʻtkazib yuborish`` and ``Bekor qilish`` — thirty-eight characters that
  wrap on a phone. Skip is on its own row now, and ``test_keyboards.py`` measures every
  keyboard in every locale so the next long translation fails a test instead of a screen.
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
    "lyrics_keyboard",
    "own_lyrics_keyboard",
    "lyrics_writing_keyboard",
    "lyrics_failed_keyboard",
    "confirm_keyboard",
    "start_over_keyboard",
    "post_delivery_keyboard",
    "LANGUAGE_COLUMNS",
    "GENRE_COLUMNS",
    "OCCASION_COLUMNS",
    "VOCAL_GENDER_COLUMNS",
    "VOCAL_GENDER_CHOICES",
    "MAX_ROW_BUTTONS",
    "MAX_ROW_LABEL_CHARS",
    "REGENERATE_LABEL_KEY",
    "OWN_LYRICS_LABEL_KEY",
    "SKIP_LABEL_KEY",
    "KEEP_NOTE_LABEL_KEY",
]

#: Layout widths. Telegram truncates a row that is too wide on a narrow phone, and Uzbek
#: labels are long, so nothing here goes past two columns.
LANGUAGE_COLUMNS: Final[int] = 2
#: One per row. The genre labels are the longest translated content this wizard shows, and
#: at two columns the widest rows blew straight through the width physics described under
#: ``MAX_ROW_LABEL_CHARS``: ``Акустическая баллада | Танцевальная / электронная`` is 46
#: characters and ``Oʻzbek estradasi | Oʻzbek xalq qoʻshigʻi`` is 37, so the second button
#: of each got about half the row and truncated mid-word. Shortening the labels was the
#: alternative and it is the wrong lever — a genre is called what it is called in each
#: language. One column gives every label the full width and cannot be broken by a longer
#: translation later.
GENRE_COLUMNS: Final[int] = 1
OCCASION_COLUMNS: Final[int] = 1
VOCAL_GENDER_COLUMNS: Final[int] = 2

#: The two-column rule at the top of this docstring, as a number a test can read. Applies
#: to EVERY row of every keyboard here, whether it was built from an enum or by hand: the
#: column constants above only constrain the former, which is how the hand-built navigation
#: row came to carry three.
MAX_ROW_BUTTONS: Final[int] = 2

#: How wide a hand-built row may be, measured as the sum of its labels' characters.
#:
#: Telegram splits a row's width evenly between its buttons and truncates whatever does not
#: fit, so what breaks a row is not one long label but the total — which is why the budget
#: lives on the row rather than on the button. The number is a few characters above the
#: widest such row this build actually draws in any of the four locales, and it is meant to
#: stay that way: it is a ratchet, and a translation that needs more than this needs a
#: shorter word rather than a bigger budget. Back / Skip / Cancel in the default locale was
#: thirty-eight.
#:
#: It is NOT applied to the rows built from an enum. Those carry translated CONTENT — nine
#: genres, four voices — whose length is a fact about the world rather than a layout choice
#: this module gets to make; ``GENRE_COLUMNS`` and its siblings are the lever there, and a
#: shared cap would only make this one fail for the wrong reason. ``test_keyboards.py``
#: tells the two kinds apart by callback prefix, which is exactly the distinction: a row of
#: ``nav:`` buttons is one this module composed.
MAX_ROW_LABEL_CHARS: Final[int] = 30

#: Label keys that do NOT follow the ``button.{action.value}`` convention, named here so
#: each exception stays visible instead of being buried in a call:
#:
#: * ``REGENERATE_LABEL_KEY`` — the callback value is abbreviated to ``regen`` to stay small
#:   on the wire, while the catalogue spells the key out;
#: * ``KEEP_NOTE_LABEL_KEY`` — the note step's Skip keeps an existing note rather than
#:   erasing it, so when there is one to keep the button says so. Same action, same
#:   handler, honest promise;
#: * ``OWN_LYRICS_LABEL_KEY`` — a nav button drawn among the OCCASION buttons, so it has no
#:   occasion label to borrow and cannot follow the convention either;
#: * ``OWN_LYRICS_LABEL_KEY`` — see above; it is drawn among the occasion buttons.
REGENERATE_LABEL_KEY: Final[str] = "button.regenerate"
OWN_LYRICS_LABEL_KEY: Final[str] = "button.own_lyrics"
SKIP_LABEL_KEY: Final[str] = "button.skip"
KEEP_NOTE_LABEL_KEY: Final[str] = "button.keep_note"

#: The occasion the "I will write the words myself" button is drawn directly ABOVE.
#:
#: It goes next to the occasions because that is the first screen with a question on it,
#: which makes it the last moment the choice is free: every step after it — the genre, the
#: voice, the note, the name — is answered the same way whoever writes the lyric, and the
#: note is the one question that stops being worth asking, so offering the choice here
#: costs the customer nothing and saves them a vendor call they never wanted.
#:
#: Above ``CUSTOM`` and not at the end, because ``CUSTOM`` is the list's escape hatch
#: ("something else") and a button placed under an escape hatch reads as a kind of it.
OWN_LYRICS_SITS_ABOVE: Final[Occasion] = Occasion.CUSTOM

#: Vocal options offered in the wizard. ``ANY`` is deliberately last: it is the escape
#: hatch, not the default.
VOCAL_GENDER_CHOICES: Final[tuple[VoiceGender, ...]] = (
    VoiceGender.FEMALE,
    VoiceGender.MALE,
    VoiceGender.DUET,
    VoiceGender.ANY,
)


def _nav_button(
    action: NavAction, language: Language, *, label_key: str | None = None
) -> InlineKeyboardButton:
    """One navigation button. ``label_key`` overrides the ``button.{action.value}`` default.

    The override exists for the two documented exceptions above and nothing else; passing
    a key that is not in the catalogues would ship a button reading ``button.something``,
    because ``translate`` returns the key rather than raising.
    """
    return InlineKeyboardButton(
        text=translate(label_key or f"button.{action.value}", language),
        callback_data=NavCB(action=action).pack(),
    )


def _nav_row(language: Language, *, is_back_enabled: bool) -> tuple[InlineKeyboardButton, ...]:
    """Back and Cancel — the two buttons every screen past the first ends with.

    Skip used to ride along here and no longer does; see :func:`_with_nav`.
    """
    buttons: list[InlineKeyboardButton] = []
    if is_back_enabled:
        buttons.append(_nav_button(NavAction.BACK, language))
    buttons.append(_nav_button(NavAction.CANCEL, language))
    return tuple(buttons)


def _with_nav(
    builder: InlineKeyboardBuilder,
    language: Language,
    *,
    is_back_enabled: bool,
    is_skip_enabled: bool = False,
    skip_label_key: str = SKIP_LABEL_KEY,
) -> InlineKeyboardMarkup:
    """Close a keyboard with its navigation: Skip on its own row, then Back and Cancel.

    Skip gets a row to itself because it is a third button on a row this module's own rule
    caps at two, and because it is not navigation — it is an answer to the question on
    screen ("no note", "keep the one I wrote"), so it reads as one of the step's options
    rather than as part of the Back/Cancel furniture.
    """
    if is_skip_enabled:
        builder.row(_nav_button(NavAction.SKIP, language, label_key=skip_label_key))
    builder.row(*_nav_row(language, is_back_enabled=is_back_enabled))
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
    """The occasions, with the bring-your-own-lyrics offer sitting among them.

    That button is the one row here this module composes out of its own label rather than
    generating from the enum, so — unlike every occasion beside it — it is measured against
    ``MAX_ROW_LABEL_CHARS`` by ``test_keyboards.py``, which tells the two kinds apart by
    callback prefix. That is the right budget for it: its label is a phrase this codebase
    chose and can shorten, not the name of a thing in the world.
    """
    builder = InlineKeyboardBuilder()
    for value in Occasion:
        if value is OWN_LYRICS_SITS_ABOVE:
            builder.button(
                text=translate(OWN_LYRICS_LABEL_KEY, language),
                callback_data=NavCB(action=NavAction.OWN_LYRICS),
            )
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


def note_keyboard(language: Language, *, is_note_present: bool = False) -> InlineKeyboardMarkup:
    """The note is typed, so this screen offers only navigation — plus the optional exit.

    That exit is labelled for what it will actually do. On the way in there is no note and
    it is Skip. Reached again through Back there IS one, and the same button now promises
    to keep it — because it does: the Skip handler leaves an existing note alone instead of
    writing an empty string over six hundred characters the user would have to retype from
    memory. Same action and same callback, because the handler's job did not change; only
    the promise the label makes did, and it had been the wrong one.
    """
    return _with_nav(
        InlineKeyboardBuilder(),
        language,
        is_back_enabled=True,
        is_skip_enabled=True,
        skip_label_key=KEEP_NOTE_LABEL_KEY if is_note_present else SKIP_LABEL_KEY,
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


def lyrics_keyboard(language: Language, *, is_own_lyrics: bool = False) -> InlineKeyboardMarkup:
    """Approve, ask for a different lyric, or ignore both and type your own.

    There is no Skip: past this screen the lyric is decided, and a kit whose words nobody
    ever looked at is exactly the outcome this step exists to prevent. Typing is the third,
    unlabelled option — the step accepts a pasted lyric as a plain message.

    ``is_own_lyrics`` drops the regenerate button, because on that path there is nothing for
    it to do. Asking the writer for a lyric needs a recipient, and the own-lyrics order never
    collects one — it has no NAME step — so a button offering to write would be offering
    something the draft cannot supply. The way out is Back, which on that order returns to
    the occasion list where the choice was made and where picking any real occasion un-makes
    it.
    """
    builder = InlineKeyboardBuilder()
    builder.row(_nav_button(NavAction.LYRICS_OK, language))
    if not is_own_lyrics:
        builder.row(_nav_button(NavAction.REGENERATE, language, label_key=REGENERATE_LABEL_KEY))
    return _with_nav(builder, language, is_back_enabled=True)


def own_lyrics_keyboard(language: Language) -> InlineKeyboardMarkup:
    """Waiting for the customer's words. Back and Cancel, and nothing else.

    There is deliberately no ``LYRICS_OK``: the draft holds no lyric at this point, so an
    approve button would approve nothing, and this codebase does not draw buttons that lead
    nowhere. There is no writer button either, for the reason ``lyrics_keyboard`` gives.

    Back is the escape, and it is a real one — on this order the previous step is the
    occasion list, which is where the path was chosen and where choosing an occasion instead
    hands the writing back to the bot.
    """
    return _with_nav(InlineKeyboardBuilder(), language, is_back_enabled=True)


def lyrics_writing_keyboard(language: Language) -> InlineKeyboardMarkup:
    """Cancel, and nothing else, while the writer is working.

    The writing frame used to carry no keyboard at all, on a screen that can sit still for
    the whole of ``llm_timeout_s``. A wait with no way out is indistinguishable from a
    hung bot, and the fallback's "use the buttons above" was a lie about a screen that had
    none. There is no Back: the draft is mid-flight, and the one thing a waiting customer
    is entitled to is the exit.
    """
    builder = InlineKeyboardBuilder()
    builder.row(_nav_button(NavAction.CANCEL, language))
    return builder.as_markup()


def lyrics_failed_keyboard(language: Language) -> InlineKeyboardMarkup:
    """The writer fell over: retry is one press, and the way out sits next to it.

    A vendor failure used to drop the customer back on the language picker with a sentence
    above it, leaving "press the button that is already ticked" as the undocumented retry.
    Naming the retry is the whole of the fix.
    """
    builder = InlineKeyboardBuilder()
    builder.row(
        _nav_button(NavAction.TRY_AGAIN, language),
        _nav_button(NavAction.CANCEL, language),
    )
    return builder.as_markup()


def confirm_keyboard(language: Language) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(_nav_button(NavAction.CONFIRM, language))
    return _with_nav(builder, language, is_back_enabled=True)


def start_over_keyboard(language: Language) -> InlineKeyboardMarkup:
    """The one button a dead end owes the user.

    Every message that ends a flow — an expired session, a cancellation, a job the queue
    timed out, a completed /forget — otherwise leaves the reader with nothing to press and
    a typed command as the only exit. On a phone that is not an exit. One button, no
    navigation around it: there is no state left to go back to.
    """
    builder = InlineKeyboardBuilder()
    builder.row(_nav_button(NavAction.START_OVER, language))
    return builder.as_markup()


def post_delivery_keyboard(language: Language) -> InlineKeyboardMarkup:
    """After the song lands: the next order, and the way to say this one came out wrong.

    One button per row rather than the two the row budget would allow. These two are not a
    pair — one is a delighted customer's next purchase and the other is a complaint — and
    setting them side by side sizes them as alternatives of equal weight while making the
    complaint the easier mis-tap on a moving thumb.
    """
    builder = InlineKeyboardBuilder()
    builder.row(_nav_button(NavAction.MAKE_ANOTHER, language))
    builder.row(_nav_button(NavAction.REPORT_PROBLEM, language))
    return builder.as_markup()
