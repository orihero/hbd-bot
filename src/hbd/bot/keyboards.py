"""Keyboards, one builder per screen.

Almost all of them are inline — markup that rides on a single message. Two are REPLY
keyboards, which are a different physical thing: they are chat-level state that sits under
the composer, survives between messages and is cached in the customer's client. That
difference is why they have their own width budget (:data:`MAX_REPLY_ROW_LABEL_CHARS`), why
:data:`MENU_LABELS` is computed over all four languages, and why ``Screen.markup`` carrying
one can only ever be SENT and never edited in place.

Three rules hold everywhere:

* Every keyboard is built from the enum it offers, so a new :class:`Genre` appears as a
  button without anyone editing this file — only its label has to exist in the catalogues.
* Every screen of a wizard RUN carries Cancel, and every one past the first carries a
  working Back. A screen OUTSIDE a run — the language question at first contact, the
  language picker inside Settings — carries neither, because there is no run to leave: a
  Cancel there reaches ``navigation.handle_cancel``, which is stateless by design and
  answers "Cancelled — nothing was made, and nothing was kept" to somebody who was only
  changing their language. The Back button's *behaviour* comes from ``WIZARD_ORDER``; this
  module only draws it, so the two can never disagree.
* No row is wider than :data:`MAX_ROW_LABEL_CHARS`. The column constants below used to be
  the whole of that rule and they only covered the *generated* rows, so the hand-built
  navigation row quietly broke it: Back / Skip / Cancel in the default locale is
  ``⬅️ Orqaga``, ``Oʻtkazib yuborish`` and ``Bekor qilish`` — thirty-eight characters that
  wrap on a phone. Skip is on its own row now, and ``test_keyboards.py`` measures every
  keyboard in every locale so the next long translation fails a test instead of a screen.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Final

from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
)
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
from hbd.bot.pricing import CheckoutOffer
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
    "checkout_keyboard",
    "checkout_link_keyboard",
    "start_over_keyboard",
    "post_delivery_keyboard",
    "main_menu_keyboard",
    "contact_request_keyboard",
    "settings_keyboard",
    "LANGUAGE_COLUMNS",
    "GENRE_COLUMNS",
    "OCCASION_COLUMNS",
    "VOCAL_GENDER_COLUMNS",
    "VOCAL_GENDER_CHOICES",
    "MAX_ROW_BUTTONS",
    "MAX_ROW_LABEL_CHARS",
    "MAX_REPLY_ROW_LABEL_CHARS",
    "MENU_BUTTON_KEYS",
    "MENU_LABELS",
    "MENU_GENERATE_LABEL_KEY",
    "MENU_BALANCE_LABEL_KEY",
    "MENU_SETTINGS_LABEL_KEY",
    "MENU_HELP_LABEL_KEY",
    "REGENERATE_LABEL_KEY",
    "OWN_LYRICS_LABEL_KEY",
    "SKIP_LABEL_KEY",
    "KEEP_NOTE_LABEL_KEY",
    "SHARE_CONTACT_LABEL_KEY",
    "PAY_NOW_LABEL_KEY",
]

#: Layout widths. Telegram truncates a row that is too wide on a narrow phone, and Uzbek
#: labels are long.
#:
#: One column, not two, and this is the same defect ``GENRE_COLUMNS`` was created to fix,
#: found on the one screen it mattered most. At two columns the language row was
#: ``Oʻzbekcha (lotin)``(17) + ``Ўзбекча (кирилл)``(16) = 33 characters in EVERY locale —
#: over the 30-character budget, on the first screen a customer ever sees, and measured by
#: nothing: the nav-row rule skips enum rows and the enum-row rule only ever inspected the
#: genre keyboard. With the flags now on these labels the two become 20 and 19, so a
#: two-column row is 39. One column makes the widest language row 20, and it has to stay
#: that way: both Uzbek buttons now carry the SAME 🇺🇿, so the endonym is the only thing
#: telling them apart and it may not be truncated.
LANGUAGE_COLUMNS: Final[int] = 1
#: One per row. The genre labels are the longest translated content this wizard shows, and
#: at two columns the widest rows blew straight through the width physics described under
#: ``MAX_ROW_LABEL_CHARS``: ``Акустическая баллада | Танцевальная / электронная`` is 46
#: characters and ``Oʻzbek estradasi | Oʻzbek xalq qoʻshigʻi`` is 37, so the second button
#: of each got about half the row and truncated mid-word. Shortening the labels was the
#: alternative and it is the wrong lever — a genre is called what it is called in each
#: language. One column gives every label the full width and cannot be broken by a longer
#: translation later.
GENRE_COLUMNS: Final[int] = 1
#: Two per row, unlike its two neighbours above, and the difference is arithmetic rather
#: than taste. The occasion list is now TEN entries plus the bring-your-own-lyrics offer,
#: and at one column that is eleven rows of keyboard above the composer — a screen a
#: customer has to scroll before they can see the option they came for. The labels afford
#: it where the genre labels did not: the widest pair in any locale is
#: ``🎂 День рождения`` + ``❤️ Признание`` at 27 characters and ``🎂 Tugʻilgan kun`` +
#: ``❤️ Sevgi izhori`` at exactly 30, so every row still fits inside the
#: ``MAX_ROW_LABEL_CHARS`` physics even though enum rows are formally exempt from it.
#: A translation that needs more room than that shortens the label or makes this 1 again.
OCCASION_COLUMNS: Final[int] = 2
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
#: lives on the row rather than on the button. It is a ratchet, and a translation that needs
#: more than this needs a shorter word rather than a bigger budget. Back / Skip / Cancel in
#: the default locale was thirty-eight.
#:
#: Measured, and it is EQUAL to the widest row this build draws rather than above it:
#: uz_latn ``🔄 Qayta urinish``(15) + ``✖️ Bekor qilish``(15) and ru
#: ``🔄 Попробовать ещё раз``(21) + ``✖️ Отмена``(9) are both exactly thirty. The ratchet is
#: therefore AT its stop, and that changes what a future author may do: a new navigation
#: button gets a row of its own rather than a seat in a pair — which is what ``_with_nav``
#: already does for Skip, and what the two ``TO_MENU`` rows below do.
#:
#: It is NOT applied to the rows built from an enum. Those carry translated CONTENT — nine
#: genres, four voices — whose length is a fact about the world rather than a layout choice
#: this module gets to make; ``GENRE_COLUMNS`` and its siblings are the lever there, and a
#: shared cap would only make this one fail for the wrong reason. ``test_keyboards.py``
#: tells the two kinds apart by callback prefix, which is exactly the distinction: a row of
#: ``nav:`` buttons is one this module composed.
MAX_ROW_LABEL_CHARS: Final[int] = 30

#: The same rule for a REPLY keyboard row, which is a different physical thing and needs its
#: own number. An inline row is laid out inside the message bubble; a reply row is laid out
#: below the composer at full viewport width, so it has materially more room and sharing one
#: budget would either truncate the inline rows or waste the reply ones. The widest row the
#: main menu draws is ru ``🎵 Сделать песню``(15) + ``🎫 Мой лимит``(11) = 26, then uz_latn and
#: en at 25 and uz_cyrl at 21. Thirty-four is the ratchet stop above those: a translation
#: that needs more than this makes the keyboard ONE column, it does not make the number
#: bigger.
MAX_REPLY_ROW_LABEL_CHARS: Final[int] = 34

#: The four keys the main menu draws, each named so ``test_locale_contract``'s key scan can
#: see it. That scan only collects a dotted string literal assigned to a name ending in
#: ``KEY``; a tuple of bare literals is invisible to it and ``menu.`` is not one of its
#: computed prefixes, so without these four names a typo would ship as a reply button
#: reading ``menu.generat`` with the whole suite green — the ``support.no_contact`` failure,
#: on the one surface a customer cannot avoid.
MENU_GENERATE_LABEL_KEY: Final[str] = "menu.generate"
MENU_BALANCE_LABEL_KEY: Final[str] = "menu.balance"
MENU_SETTINGS_LABEL_KEY: Final[str] = "menu.settings"
MENU_HELP_LABEL_KEY: Final[str] = "menu.help"

#: ``menu.prompt`` is a MESSAGE BODY and is deliberately absent. The menu router's filter is
#: ``F.text.in_(MENU_LABELS)`` and ``common.is_menu_label`` reads the same set, so a customer
#: who types "Что делаем?" — or, far likelier, a note at the note step that happens to equal
#: a prompt in a locale they do not read — would be routed into a dispatcher with no button
#: to dispatch to, or have their note silently refused.
MENU_BUTTON_KEYS: Final[tuple[str, ...]] = (
    MENU_GENERATE_LABEL_KEY,
    MENU_BALANCE_LABEL_KEY,
    MENU_SETTINGS_LABEL_KEY,
    MENU_HELP_LABEL_KEY,
)

#: Every menu label in every language, computed once at import.
#:
#: All four languages, not just the current one: ``is_persistent=True`` makes the keyboard
#: chat-level state that survives in the customer's client, so somebody who changes their
#: language still has yesterday's labels pinned and will press one. A set built per-request
#: from the current language would route those presses to the fallback handler and answer
#: "that session expired" to a button the bot itself drew.
MENU_LABELS: Final[frozenset[str]] = frozenset(
    translate(key, language) for key in MENU_BUTTON_KEYS for language in SUPPORTED_LANGUAGES
)

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
#: * ``SHARE_CONTACT_LABEL_KEY`` — the odd one out, and for a stronger reason than the rest:
#:   a ``request_contact`` button carries no callback data AT ALL. Telegram gives it its own
#:   button type, so there is no :class:`NavAction` behind it to borrow a label from and the
#:   convention has nothing to be applied to. That is also why it can never appear in a nav
#:   row and why the settings submenu's five new actions, which do all follow the
#:   convention, are deliberately NOT listed here;
#: * ``PAY_NOW_LABEL_KEY`` — the same shape as the one above, arrived at from the other
#:   direction. It labels a ``url=`` button, which carries no callback data either, so there
#:   is again no :class:`NavAction` to derive a key from. See :func:`checkout_link_keyboard`
#:   for why the product now has a button that leaves Telegram at all.
#:
#: The five settings and dead-end actions — ``set_language``, ``show_privacy``,
#: ``show_support``, ``to_menu``, ``to_settings`` — follow ``button.{action.value}`` exactly,
#: so their absence from this block is the statement that nothing was hand-picked for them.
#:
#: ``button.pay`` and ``button.subscribe`` are absent for the same reason and are noted here
#: only because they are an exception of a DIFFERENT kind: they are the first labels in this
#: product that INTERPOLATE. Every other button in the bot is a constant string per locale;
#: those two carry the price, which is why ``_nav_button`` grew ``label_params``. The number
#: comes from ``Settings`` through :class:`~hbd.bot.pricing.Pricing` rather than from the
#: catalogues, because a price written into four catalogues would silently disagree with
#: ``HBD_SINGLE_SONG_PRICE_MINOR`` the day an operator changed it — the customer would be
#: quoted one number on a button and charged another by the rail — while a price
#: interpolated from configuration cannot. The currency WORD still comes from the template,
#: since it differs per language and is the translators' to own.
REGENERATE_LABEL_KEY: Final[str] = "button.regenerate"
OWN_LYRICS_LABEL_KEY: Final[str] = "button.own_lyrics"
SKIP_LABEL_KEY: Final[str] = "button.skip"
KEEP_NOTE_LABEL_KEY: Final[str] = "button.keep_note"
SHARE_CONTACT_LABEL_KEY: Final[str] = "button.share_contact"
PAY_NOW_LABEL_KEY: Final[str] = "button.pay_now"

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
    action: NavAction,
    language: Language,
    *,
    label_key: str | None = None,
    label_params: Mapping[str, object] | None = None,
) -> InlineKeyboardButton:
    """One navigation button. ``label_key`` overrides the ``button.{action.value}`` default.

    The override exists for the two documented exceptions above and nothing else; passing
    a key that is not in the catalogues would ship a button reading ``button.something``,
    because ``translate`` returns the key rather than raising.

    ``label_params`` is the interpolation channel, and it is empty for every button but the
    two price ones — see the exception block above for why those two need it. A key whose
    template has no matching placeholder silently drops the value (``i18n._SafeParams``),
    so a params dict handed to the wrong button is invisible rather than loud; that is the
    reason this stays keyword-only and is passed at exactly two call sites.
    """
    return InlineKeyboardButton(
        text=translate(label_key or f"button.{action.value}", language, **(label_params or {})),
        callback_data=NavCB(action=action).pack(),
    )


def _nav_row(
    language: Language, *, is_back_enabled: bool, is_cancel_enabled: bool = True
) -> tuple[InlineKeyboardButton, ...]:
    """Back and Cancel — the two buttons every screen of a wizard RUN ends with.

    Cancel used to be unconditional, and that was the defect: it is not furniture, it is an
    offer to abandon a run. With both switches off this returns EMPTY, which is a real
    answer for the screens outside a run — see :func:`_with_nav` for who they are.

    Skip used to ride along here and no longer does; see :func:`_with_nav`.
    """
    buttons: list[InlineKeyboardButton] = []
    if is_back_enabled:
        buttons.append(_nav_button(NavAction.BACK, language))
    if is_cancel_enabled:
        buttons.append(_nav_button(NavAction.CANCEL, language))
    return tuple(buttons)


def _with_nav(
    builder: InlineKeyboardBuilder,
    language: Language,
    *,
    is_back_enabled: bool,
    is_cancel_enabled: bool = True,
    is_skip_enabled: bool = False,
    skip_label_key: str = SKIP_LABEL_KEY,
) -> InlineKeyboardMarkup:
    """Close a keyboard with its navigation: Skip on its own row, then Back and Cancel.

    Skip gets a row to itself because it is a third button on a row this module's own rule
    caps at two, and because it is not navigation — it is an answer to the question on
    screen ("no note", "keep the one I wrote"), so it reads as one of the step's options
    rather than as part of the Back/Cancel furniture.

    ``is_cancel_enabled`` exists because Cancel is not furniture either: it is an offer to
    abandon a wizard run. A screen that is not part of one — the language question at first
    contact, the language picker inside Settings — has nothing to cancel, and drawing the
    button there is not harmless. ``navigation.handle_cancel`` is stateless by design, so a
    customer who came to change their language would be answered "Cancelled — nothing was
    made, and nothing was kept" about a run they never started.

    Hence also the ``if nav:`` guard: with both switches off there is no navigation at all,
    and the guard says so where a reader will look. It prevents nothing today —
    ``builder.row()`` with no buttons is already a no-op in aiogram, because ``row`` extends
    by ``range(0, 0, width)``, which is empty — and it exists to be explicit. Do NOT write
    "Telegram rejects an empty row" here; that is not what happens, and a false argument in
    a docstring outlives the code it was written about.
    """
    if is_skip_enabled:
        builder.row(_nav_button(NavAction.SKIP, language, label_key=skip_label_key))
    nav = _nav_row(language, is_back_enabled=is_back_enabled, is_cancel_enabled=is_cancel_enabled)
    if nav:
        builder.row(*nav)
    return builder.as_markup()


def language_keyboard(
    slot: LanguageSlot,
    language: Language,
    *,
    is_back_enabled: bool,
    is_cancel_enabled: bool = True,
    tail_action: NavAction | None = None,
    offered: tuple[Language, ...] = SUPPORTED_LANGUAGES,
) -> InlineKeyboardMarkup:
    """The same widget serves every slot; ``slot`` is what tells the handlers apart.

    On the very first screen the interface language is not chosen yet, so labels are drawn
    in each language's own name — which is why ``language_label`` is asked for the label of
    ``value`` rather than a translation of the current locale's word for it.

    FOUR screens ask this question and they differ only in what is drawn around the buttons,
    so they are one widget with switches rather than four builders: the wizard's OUTPUT step
    (Back and Cancel), a draft parked at ``Wizard:ui_language`` from before onboarding
    existed (Cancel only — it IS a wizard run, so this module's own rule gives it one), the
    first screen a new customer sees (neither), and the Settings picker (neither, plus a
    ``TO_SETTINGS`` row instead of a way out of a run there is none of). ``tail_action`` is
    that last row, appended after the navigation so it reads as the exit rather than as a
    fifth language.

    One builder rather than four because every name ending in ``_keyboard`` that enters
    ``__all__`` costs a line in ``test_keyboards.every_keyboard`` and a red coverage test
    until somebody writes it — the test that exists so a keyboard cannot ship unmeasured.
    This module adds exactly three new builders and no more.
    """
    builder = InlineKeyboardBuilder()
    for value in offered:
        builder.button(
            text=language_label(value, language),
            callback_data=LanguageCB(slot=slot, code=value),
        )
    builder.adjust(LANGUAGE_COLUMNS)
    markup = _with_nav(
        builder, language, is_back_enabled=is_back_enabled, is_cancel_enabled=is_cancel_enabled
    )
    if tail_action is not None:
        markup.inline_keyboard.append([_nav_button(tail_action, language)])
    return markup


def occasion_keyboard(language: Language) -> InlineKeyboardMarkup:
    """The occasions, with the bring-your-own-lyrics offer sitting among them.

    That button is the one row here this module composes out of its own label rather than
    generating from the enum, so — unlike every occasion beside it — it is measured against
    ``MAX_ROW_LABEL_CHARS`` by ``test_keyboards.py``, which tells the two kinds apart by
    callback prefix. That is the right budget for it: its label is a phrase this codebase
    chose and can shorten, not the name of a thing in the world.

    It draws NO Back. The occasion is the FIRST step of both orders now that the interface
    language is asked once at first contact instead of at the top of every run, so
    ``previous_step(OCCASION)`` is ``None`` and a Back here would re-render the screen it is
    already on — a button that looks broken because it is. Cancel stays: this is a wizard
    run, and leaving it is exactly what Cancel is for.
    """
    builder = InlineKeyboardBuilder()
    #: Row sizes, accumulated as the buttons are added rather than handed to ``adjust`` as
    #: one repeated number. At two columns a bare ``adjust(OCCASION_COLUMNS)`` would seat
    #: the own-lyrics button beside whichever occasion happened to precede it, and that row
    #: would then be neither a nav row nor an enum row — which is exactly the distinction
    #: ``test_keyboards.py`` uses to decide what to measure, so the one button here whose
    #: label this codebase chose would stop being measured at all. It gets a row of its own,
    #: and the partial row before it is flushed so it stays directly above ``CUSTOM``.
    sizes: list[int] = []
    pending = 0
    for value in Occasion:
        if value is OWN_LYRICS_SITS_ABOVE:
            if pending:
                sizes.append(pending)
                pending = 0
            builder.button(
                text=translate(OWN_LYRICS_LABEL_KEY, language),
                callback_data=NavCB(action=NavAction.OWN_LYRICS),
            )
            sizes.append(1)
        builder.button(text=occasion_label(value, language), callback_data=OccasionCB(value=value))
        pending += 1
        if pending == OCCASION_COLUMNS:
            sizes.append(pending)
            pending = 0
    if pending:
        sizes.append(pending)
    builder.adjust(*sizes)
    return _with_nav(builder, language, is_back_enabled=False)


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


def checkout_keyboard(language: Language, offer: CheckoutOffer) -> InlineKeyboardMarkup:
    """The Confirm screen wearing its unpaid face: buy one song, or take the plan.

    The words above this keyboard are already written and already free — that is the half of
    the product the customer keeps whatever they do next — and these buttons are the only
    thing between them and a recording. Back therefore still leads to the lyric rather than
    out of the flow, which is what makes the free half a promise rather than a teaser.

    **There is no 🎬 Record it button here, and its absence is the enforcement.** A screen
    that offered both would leave "no render is queued unpaid" resting on a check somebody
    could reorder; leaving the button off makes it structural. ``handlers.confirm`` still
    re-checks, because a customer can be holding a keyboard drawn before they spent their
    last credit, but that check is the second line and not the first.

    ONE button per row, deliberately. ``MAX_ROW_LABEL_CHARS`` is documented as already at
    its ratchet stop, and these two labels carry a price as well as a noun — "🌟 49 000 soʻm
    — 12 ta" is 20 characters before any locale gets long — so pairing them would be a row
    over budget in at least one language on the day a price grew a digit. A single-button
    row satisfies the width rule by construction rather than by measurement.

    ``is_plan_offered`` is decided by the caller and not here: a plan that is already
    running, spent or not, must not be sold a second time, and this module has no clock and
    no ledger with which to know. See :class:`~hbd.bot.pricing.CheckoutOffer`.
    """
    builder = InlineKeyboardBuilder()
    builder.row(
        _nav_button(NavAction.PAY, language, label_params={"amount": offer.pricing.single_amount})
    )
    if offer.is_plan_offered:
        builder.row(
            _nav_button(
                NavAction.SUBSCRIBE,
                language,
                label_params={
                    "amount": offer.pricing.plan_amount,
                    "songs": offer.pricing.plan_songs,
                },
            )
        )
    return _with_nav(builder, language, is_back_enabled=True)


def checkout_link_keyboard(language: Language, url: str) -> InlineKeyboardMarkup:
    """The redirect rail's screen: pay over there, or go home. **The first ``url=`` button.**

    Every other button in this product carries ``NavCB`` data and comes back to this process.
    This one leaves Telegram entirely — the customer taps it, pays on the rail's own page and
    settlement arrives later, inbound, at a different process (``PAYME_INTEGRATION §1``). It is
    the first of its kind here: before this builder, ``grep -rn "url=" src/hbd/bot/`` returned
    nothing at all.

    **Two rows, and the second one is not decoration.** A screen whose only control leaves
    Telegram is a stranded customer: they tap 🔗, decide against paying, come back to a
    message with nothing on it but the link they just refused, and the only way out is a typed
    command or a persistent reply keyboard they are free to have collapsed. That is the dead
    end :func:`start_over_keyboard` and :func:`post_delivery_keyboard` were given 🏠 for, met
    on a third screen.

    **``TO_MENU`` rather than ``BACK``, and rather than ``CANCEL``.** Back's destination is a
    function of the FSM, and this keyboard is drawn on BOTH checkout surfaces — the wizard's
    Confirm screen and the ``/balance`` answer, which has no wizard state behind it at all — so
    on the second one a Back would fall through every router to ``fallback.handle_stale_callback``
    and answer "your session expired" to a customer with a live payment open. That is the exact
    defect ``handlers.checkout``'s four registrations exist to keep fixed, and it is not worth
    re-introducing one screen later. Cancel is worse than useless here: it is stateless by
    design, so it would clear a wizard run while a payment against it is still live at the rail,
    cancel NOTHING at the rail (the intent is a row in another process's table and no method we
    may call retracts it), and greet somebody returning from a successful payment with
    "Cancelled — nothing was made, and nothing was kept". ``TO_MENU`` is registered with no
    state filter at all (``handlers.menu``), so it is the one exit that works from either
    surface.

    **🔗 is chosen, not defaulted.** 💳 is ``button.pay`` and 🌟 is ``button.subscribe``, and
    ``test_no_two_buttons_on_one_screen_lead_with_the_same_emoji`` runs per screen per
    language; 🔗 is also the honest picture of what the button does, which is hand the customer
    off to somewhere else.

    **The cost, named rather than discovered later.** ``test_keyboards.is_nav_row`` classifies
    a row by ``button.callback_data or ""``, and a URL button has none — so the first row here
    is silently NOT a nav row and is exempt from the nav-row width budget. That exemption is
    now deliberate: the label is a constant per locale (no price, no name, no interpolation)
    sitting alone on its row, so the budget would be measuring a string that cannot grow
    without a translator's edit, and ``test_checkout_redirect.py`` asserts the row's width
    explicitly instead. The 🏠 row underneath IS a nav row and is measured by the existing
    rule, which is where a long translation would actually bite.

    :func:`_nav_button` is untouched and is not used for the first row: it packs a ``NavCB``
    into ``callback_data``, and a button carrying both a URL and callback data is not a thing
    Telegram has.
    """
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text=translate(PAY_NOW_LABEL_KEY, language), url=url))
    builder.row(_nav_button(NavAction.TO_MENU, language))
    return builder.as_markup()


def start_over_keyboard(language: Language) -> InlineKeyboardMarkup:
    """The two buttons a dead end owes the user: start again, or go home.

    Every message that ends a flow — an expired session, a cancellation, a job the queue
    timed out, a completed /forget — otherwise leaves the reader with nothing to press and
    a typed command as the only exit. On a phone that is not an exit. There is no Back and
    no Cancel around them: there is no state left to go back to and no run left to abandon.

    The second row is 🏠 Back to menu, and it exists because "start another wizard run" is
    not the only thing somebody wants after a cancellation, an expiry or a credit refusal —
    just as often they want their balance, their settings or the help text, and until this
    row the only route to any of those was a tap on a persistent reply keyboard they may
    have collapsed. That is what made this builder and :func:`post_delivery_keyboard` the
    last two dead ends in the product.

    Its own row rather than a seat beside Start over, because :data:`MAX_ROW_LABEL_CHARS` is
    at its stop; single-button rows satisfy the width rule by construction, and the widest
    of them is ``🏠 Menyuga qaytish``(17).
    """
    builder = InlineKeyboardBuilder()
    builder.row(_nav_button(NavAction.START_OVER, language))
    builder.row(_nav_button(NavAction.TO_MENU, language))
    return builder.as_markup()


def post_delivery_keyboard(language: Language) -> InlineKeyboardMarkup:
    """After the song lands: the next order, the complaint, and the way home.

    One button per row rather than the two the row budget would allow. The first two are not
    a pair — one is a delighted customer's next purchase and the other is a complaint — and
    setting them side by side sizes them as alternatives of equal weight while making the
    complaint the easier mis-tap on a moving thumb.

    🏠 Back to menu is last for the same reason it is on :func:`start_over_keyboard`: a
    delivered song is a dead end unless the customer still has the reply keyboard on screen,
    and it is chat-level state they are free to collapse. It sits below the complaint rather
    than between the two, so the order reads as "again / something was wrong / done".
    """
    builder = InlineKeyboardBuilder()
    builder.row(_nav_button(NavAction.MAKE_ANOTHER, language))
    builder.row(_nav_button(NavAction.REPORT_PROBLEM, language))
    builder.row(_nav_button(NavAction.TO_MENU, language))
    return builder.as_markup()


def main_menu_keyboard(language: Language) -> ReplyKeyboardMarkup:
    """The persistent menu. Two rows of two, and it is never taken away.

    ``is_persistent=True`` is what makes this a MENU rather than a prompt: the keyboard is
    chat-level state that stays on screen between messages and survives a restart of the
    bot, so the customer always has somewhere to go and no message is a dead end. The
    consequence is that its labels are cached in the customer's client, which is why
    :data:`MENU_LABELS` is computed over all four languages and why the menu is re-sent
    after a language change — those are the same fact seen from two sides.

    ``one_time_keyboard=False`` for the same reason; ``resize_keyboard=True`` because the
    default height is sized for a keyboard of five rows and this one has two.

    Generate and Balance share the first row and Settings and Help the second, so the two
    things a customer came to do are under the thumb and the two they came to read are not.
    """
    rows = [
        [
            KeyboardButton(text=translate(MENU_GENERATE_LABEL_KEY, language)),
            KeyboardButton(text=translate(MENU_BALANCE_LABEL_KEY, language)),
        ],
        [
            KeyboardButton(text=translate(MENU_SETTINGS_LABEL_KEY, language)),
            KeyboardButton(text=translate(MENU_HELP_LABEL_KEY, language)),
        ],
    ]
    return ReplyKeyboardMarkup(
        keyboard=rows, resize_keyboard=True, is_persistent=True, one_time_keyboard=False
    )


def contact_request_keyboard(language: Language) -> ReplyKeyboardMarkup:
    """One button, and it is the only way to answer the question above it.

    ``request_contact=True`` is what makes the answer trustworthy: Telegram sends the number
    attached to THIS account, with ``Contact.user_id`` set, rather than whatever the customer
    typed. A typed number is somebody else's as often as it is a typo, and the number exists
    so a song can be delivered when Telegram cannot — so a number we cannot attribute is
    worse than no number at all, because it makes a delivery promise to a stranger.

    It is a reply keyboard because ``request_contact`` has no inline equivalent: sharing a
    contact is a client-side action Telegram only offers under the composer. That is also
    why it temporarily replaces the main menu — two reply keyboards cannot both be on
    screen — and why the menu is re-sent the moment the number lands.

    Its label key is :data:`SHARE_CONTACT_LABEL_KEY` rather than a ``button.{action}``
    lookup, because this button carries no callback data and therefore has no
    :class:`NavAction` to derive one from.
    """
    return ReplyKeyboardMarkup(
        keyboard=[
            [
                KeyboardButton(
                    text=translate(SHARE_CONTACT_LABEL_KEY, language), request_contact=True
                )
            ]
        ],
        resize_keyboard=True,
    )


def settings_keyboard(language: Language) -> InlineKeyboardMarkup:
    """Settings, inline and one column, with no FSM state behind it.

    Inline rather than a second reply keyboard because the main menu is persistent: two
    reply keyboards cannot both be on screen, so a reply submenu would have to remove the
    menu to draw itself and put it back afterwards, and any dropped update in between leaves
    the customer with no keyboard at all.

    One column is required, not preferred: ``🌐 Tilni oʻzgartirish``(20) +
    ``🔒 Maʼlumotlarim``(15) is 35 in uz_latn, over the inline budget of 30 and over the
    reply budget of 34 as well.

    Stateless on purpose. Settings is reachable mid-wizard from the persistent keyboard, and
    a screen that set its own FSM state would clobber the ``Wizard.*`` state a half-finished
    draft is parked in. Which picker a ``LanguageCB`` came from is therefore carried in the
    payload (``LanguageSlot.SETTINGS``) rather than inferred from the state.

    ``TO_MENU`` is the last row and not a Cancel: there is no run here to abandon, so the
    only honest exit is upwards.
    """
    builder = InlineKeyboardBuilder()
    for action in (
        NavAction.SET_LANGUAGE,
        NavAction.SHOW_PRIVACY,
        NavAction.SHOW_SUPPORT,
        NavAction.TO_MENU,
    ):
        builder.row(_nav_button(action, language))
    return builder.as_markup()
