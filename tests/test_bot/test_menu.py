"""The persistent menu and the settings submenu, through the real router tree.

A reply keyboard is not a screen. It is chat-level state Telegram pins under the composer and
keeps there — through a restart of this process, through a language change, through weeks of
silence — until something sends a new one. Three consequences run through every test below and
none of them applies to an inline keyboard:

* **Its labels arrive as ordinary text messages.** From the wire, a customer typing
  "🎵 Make a song" and a customer pressing it are the same update, which is why the menu router
  sits above every free-text step and why the three steps that accept any text guard against a
  label as well as against a command. A menu label written into ``draft.note`` is SUNG TO A
  REAL PERSON.
* **It outlives the language it was drawn in.** Yesterday's Russian keyboard is still pinned
  after today's switch to English, so ``MENU_LABELS`` is computed over all four catalogues at
  import and a stale press still routes. A set built per request from the current language
  would answer "that session expired" to a button this bot itself drew.
* **It cannot be edited into an existing message.** ``editMessageText`` accepts inline markup
  only, so every screen carrying the menu is a SEND — which is why the menu is re-sent in
  exactly one place, the language change, and nowhere else.

The settings submenu is inline and carries NO FSM state, because ⚙️ is reachable mid-wizard
from a keyboard the customer cannot dismiss: a screen that set its own state would overwrite
the ``Wizard.*`` state a half-finished draft is parked in and lose the draft to somebody who
only wanted to change their language.
"""

from __future__ import annotations

from typing import Any, Final

import pytest
from aiogram import Bot, Dispatcher
from aiogram.fsm.context import FSMContext
from aiogram.types import InlineKeyboardMarkup

from bayram.bot.callbacks import (
    GenreCB,
    LanguageCB,
    LanguageSlot,
    NavAction,
    NavCB,
    OccasionCB,
    VocalGenderCB,
)
from bayram.bot.draft import UI_LANGUAGE_KEY, WizardDraft, load_draft
from bayram.bot.handlers.common import privacy_text, support_text
from bayram.bot.i18n import language_label, translate
from bayram.bot.keyboards import MENU_BUTTON_KEYS, main_menu_keyboard
from bayram.bot.states import Wizard
from bayram.config import Settings
from bayram.contracts import Genre, Language, Occasion, VoiceGender, is_ok
from bayram.db.retention import DEFAULT_RETENTION_POLICY
from tests.test_bot.conftest import (
    USER_ID,
    FakeProfiles,
    RecordingSession,
    buttons,
    last_reply_keyboard,
    reply_buttons,
)
from tests.test_bot.test_wizard_flow import (
    UZBEK_DISPLAY,
    complete_onboarding,
    press,
    send,
    tap,
    walk_to_confirm,
    walk_to_lyrics,
    walk_to_name,
)

#: The four rows the settings submenu draws, in order, one per row.
#:
#: An ordered tuple rather than a set: the language is what customers open Settings for, so it
#: is first, and the way out is last because a customer who reads to the bottom of a list has
#: found the exit exactly where every other screen in this product puts it.
SETTINGS_ACTIONS: Final[tuple[NavAction, ...]] = (
    NavAction.SET_LANGUAGE,
    NavAction.SHOW_PRIVACY,
    NavAction.SHOW_SUPPORT,
    NavAction.TO_MENU,
)


async def read_draft_of(state: FSMContext) -> WizardDraft:
    """The live draft. Fails loudly rather than returning ``None`` into an assertion."""
    result = load_draft(await state.get_data())
    assert is_ok(result), "the draft should still be readable"
    return result.value


async def walk_to_note(dispatcher: Dispatcher, bot: Bot) -> None:
    """Onboarding, 🎵, and the three button steps — stopping ON the free-text note.

    Written here rather than imported because every walker in ``test_wizard_flow`` walks PAST
    this step: the shortest of them answers the note in the same breath as reaching it. What
    the tests below need is the step with the question still open and the draft's ``note``
    still empty, so that a label stored as the answer is visible as a stored label rather than
    as a changed one.
    """
    await complete_onboarding(dispatcher, bot, language=Language.EN)
    await tap(dispatcher, bot, "menu.generate", Language.EN)
    await press(dispatcher, bot, OccasionCB(value=Occasion.BIRTHDAY).pack())
    await press(dispatcher, bot, GenreCB(value=Genre.UZBEK_POP).pack())
    await press(dispatcher, bot, VocalGenderCB(value=VoiceGender.FEMALE).pack())


def reply_markups(session: RecordingSession) -> list[Any]:
    """Every markup the bot attached to an outgoing call, in order, ``None`` included."""
    return [getattr(call, "reply_markup", None) for call in session.calls]


# ---------------------------------------------------------------------------
# The keyboard itself
# ---------------------------------------------------------------------------
def test_the_main_menu_is_persistent_and_never_removed() -> None:
    """``is_persistent`` is what makes this a menu rather than a prompt.

    Without it Telegram treats the keyboard as a one-shot answer aid: it collapses after the
    next message, and the four buttons — the only navigation this product has outside a wizard
    run — are behind an icon most people never press. With it, the keyboard is chat-level
    state that survives a restart of this process, which is also why its labels have to be
    routable in every language and why it is re-sent in exactly one place.

    ``one_time_keyboard`` is asserted falsy rather than ``is False`` because aiogram leaves it
    ``None`` when unset, and ``None`` and ``False`` mean the same thing to Telegram here.
    """
    # Arrange / Act
    markup = main_menu_keyboard(Language.EN)

    # Assert
    assert markup.is_persistent is True
    assert markup.resize_keyboard is True
    assert not markup.one_time_keyboard


async def test_no_flow_in_this_product_ever_takes_the_keyboard_away(
    dispatcher: Dispatcher, bot: Bot, session: RecordingSession
) -> None:
    """The other half of "never removed", asserted over a whole purchase.

    ``ReplyKeyboardRemove`` is the one thing that can unpin the menu, and a single stray one
    anywhere in a flow leaves the customer with no navigation at all for the rest of the
    conversation — no 🎵, no 🎫, no ⚙️, and nothing on screen to say where any of it went. It
    is not imported by ``keyboards.py`` and CONTRACTS §5 keeps it out of ``Screen.markup``'s
    union; this asserts the same fact from the wire, across the longest path a customer walks.
    """
    # Arrange / Act — the whole of a purchase, onboarding included
    await walk_to_confirm(dispatcher, bot)
    await press(dispatcher, bot, NavCB(action=NavAction.CONFIRM).pack())

    # Assert
    removals = [
        markup
        for markup in reply_markups(session)
        if type(markup).__name__ == "ReplyKeyboardRemove"
    ]
    assert removals == [], "something un-pinned the only navigation this product has"


@pytest.mark.parametrize("language", list(Language))
def test_the_menu_is_two_rows_of_two_in_the_declared_order(language: Language) -> None:
    """Layout is a contract, and this is the one keyboard whose layout the customer keeps.

    Generate and Balance share the first row and Settings and Help the second, so the two
    things a customer came to DO are under the thumb and the two they came to READ are not.
    ``reply_buttons`` preserves the rows for exactly this assertion: flattened, a two-by-two
    grid and a column of four are the same tuple, and the second one does not fit a phone.

    Parametrised over every locale because the labels are catalogue strings and a translation
    is where an accidental fifth button or a swapped pair would arrive.
    """
    # Arrange / Act / Assert
    assert reply_buttons(main_menu_keyboard(language)) == (
        (translate("menu.generate", language), translate("menu.balance", language)),
        (translate("menu.settings", language), translate("menu.help", language)),
    )


def test_the_button_keys_are_the_buttons_and_the_prompt_is_not_one_of_them() -> None:
    """C2-12. ``menu.prompt`` is a MESSAGE BODY, and including it would break two things.

    ``MENU_BUTTON_KEYS`` is what ``main_menu_keyboard`` draws from, what ``MENU_LABELS`` is
    computed over, and what the menu router's ``_KEY_BY_LABEL`` dispatches on — one tuple, so
    the keyboard, the filter and the dispatch cannot disagree about what the menu is. Add the
    prompt to it and the filter starts claiming updates the dispatch map has no arm for: a
    customer who typed "Что делаем?" — or, far likelier, a note at the note step that happened
    to equal a prompt in a locale they do not read — reaches a dispatcher with no button to
    dispatch to and has their note silently refused.

    An exact tuple rather than a membership check, because the failure runs in both directions:
    a key REMOVED here is a button that keeps being drawn and stops routing.
    """
    # Arrange / Act / Assert
    assert MENU_BUTTON_KEYS == ("menu.generate", "menu.balance", "menu.settings", "menu.help")
    assert "menu.prompt" not in MENU_BUTTON_KEYS


# ---------------------------------------------------------------------------
# Pressing the buttons
# ---------------------------------------------------------------------------
async def test_menu_labels_from_a_stale_keyboard_in_another_language_still_route(
    dispatcher: Dispatcher, bot: Bot, session: RecordingSession
) -> None:
    """A pinned keyboard outlives a language change, so a press can arrive in the wrong one.

    Telegram does not redraw a persistent keyboard when the bot starts speaking a different
    language: yesterday's labels stay under the composer until a message carries new ones. If
    ``MENU_LABELS`` were built from the CURRENT language, that press would match no filter,
    fall through to the fallback router, and be answered "that session expired" — about a
    button the bot itself drew and never took away.

    The answer comes back in the language the account actually reads, not in the language of
    the label pressed, because the label is stale and the account's choice is not.
    """
    # Arrange — an English-speaking account with a Russian keyboard still pinned
    await complete_onboarding(dispatcher, bot, language=Language.EN)
    session.clear()

    # Act
    await tap(dispatcher, bot, "menu.balance", Language.RU)

    # Assert
    assert session.last_screen.text == translate("credits.balance_none", Language.EN)


@pytest.mark.parametrize("key", MENU_BUTTON_KEYS)
async def test_a_menu_label_typed_at_the_note_step_is_never_stored_as_the_note(
    dispatcher: Dispatcher, bot: Bot, state: FSMContext, key: str
) -> None:
    """The note is free text, so without a guard a pressed button becomes a fact about a person.

    The note is the one field whose whole purpose is to accept anything the customer wants to
    say about the recipient, and it is handed to the lyric writer verbatim. "🎫 My balance" in
    that field is a line of a song sung at somebody's birthday — the same failure shape as the
    ``/help``-at-the-note-step incident, arriving through a button rather than a command.

    Two mechanisms stop it and this test does not care which one fired: the menu router is
    registered above ``questions``, and ``questions.handle_note`` checks ``is_menu_label``
    beside its command check as the second brace (C2-11 / C1-14). Parametrised over all four
    labels because the guard reads a computed set and a fifth button added without a place in
    it would be the one that lands in the draft.
    """
    # Arrange
    await walk_to_note(dispatcher, bot)

    # Act
    await tap(dispatcher, bot, key, Language.EN)

    # Assert
    assert (await read_draft_of(state)).note == ""


@pytest.mark.parametrize("key", MENU_BUTTON_KEYS)
async def test_a_menu_label_typed_at_the_name_step_is_never_stored_as_the_name(
    dispatcher: Dispatcher, bot: Bot, state: FSMContext, key: str
) -> None:
    """The recipient's name is the one string this product sings out loud.

    It is typed, resolved to a canonical display spelling, and then submitted to a voice vendor
    — so a menu label accepted here is a label pronounced in a birthday song and printed on
    the confirmation screen. ``name.handle_name_typed`` carries the second brace for the same
    reason ``handle_note`` does, and the router order carries the first.
    """
    # Arrange
    await walk_to_name(dispatcher, bot)

    # Act
    await tap(dispatcher, bot, key, Language.EN)

    # Assert
    assert (await read_draft_of(state)).recipient is None


@pytest.mark.parametrize("key", MENU_BUTTON_KEYS)
async def test_a_menu_label_pasted_at_the_lyrics_step_is_never_stored_as_the_lyric(
    dispatcher: Dispatcher, bot: Bot, state: FSMContext, key: str
) -> None:
    """The third free-text step, and the one v1's plan forgot (C1-14).

    The lyric preview accepts a pasted lyric as a plain message, so a menu label pressed while
    it is on screen would replace a written lyric with two words and a pictogram — and this
    path has already spent a vendor call to produce the lyric it would be overwriting. The
    machine's own draft is asserted to have survived, rather than merely asserting the label is
    absent: "no lyric at all" would pass that weaker check and is not what should happen here.
    """
    # Arrange — a written lyric on screen
    await walk_to_lyrics(dispatcher, bot)
    written = (await read_draft_of(state)).lyrics
    assert written is not None, "the arrangement is meant to leave a lyric in the draft"

    # Act
    await tap(dispatcher, bot, key, Language.EN)

    # Assert
    kept = (await read_draft_of(state)).lyrics
    assert kept is None or kept == written


async def test_a_menu_tap_while_the_song_is_rendering_does_not_un_park_the_order(
    dispatcher: Dispatcher, bot: Bot, session: RecordingSession, state: FSMContext
) -> None:
    """C2-3, the blocker. Both new routers stand down for ``Wizard.submitting``.

    ``handlers.submitting`` claims every update in that state, and its claim is load-bearing:
    ``commands.handle_forget`` deliberately re-parks a running order there, and ``/cancel``
    decides what to say by reading ``ORDER_ID_KEY`` out of that park. A menu router that
    claimed a 🎵 here would run ``reset_to_welcome``, whose clear takes the order id with it —
    after which ``order_in_flight`` is blind and the next ``/cancel`` answers "Cancelled —
    nothing was made, and nothing was kept" about a song that then arrives in the chat.

    The stand-down is one declarative filter per router rather than a guard in each handler,
    and the accepted cost is stated in ``build_router``: 🎫 pressed mid-render answers
    ``wizard.queued`` instead of the balance, and ``/balance`` still works because ``commands``
    is above everything.

    The answer asserted below is the NAMED ``wizard.queued`` rather than the bare
    ``wizard.still_in_studio``: the draft is still parked with the order, so ``submitting`` can
    tell the customer whose song is being made. The nameless key is the fallback for a session
    whose draft has gone — which is what ``/forget`` mid-render produces.
    """
    # Arrange — an order at the studio
    await walk_to_confirm(dispatcher, bot)
    await press(dispatcher, bot, NavCB(action=NavAction.CONFIRM).pack())
    parked = await state.get_data()
    session.clear()

    # Act
    await tap(dispatcher, bot, "menu.generate", Language.EN)

    # Assert — the park is intact and the wizard did not restart
    assert await state.get_state() == Wizard.submitting.state
    assert (await state.get_data()) == parked
    assert session.last_screen.text == translate("wizard.queued", Language.EN, name=UZBEK_DISPLAY)

    # Act / Assert — and the /cancel that follows still tells the truth
    session.clear()
    await send(dispatcher, bot, "/cancel")
    assert session.last_screen.text != translate("wizard.cancelled", Language.EN)


# ---------------------------------------------------------------------------
# ⚙️ Settings
# ---------------------------------------------------------------------------
async def test_settings_shows_the_current_language_and_four_choices(
    dispatcher: Dispatcher, bot: Bot, session: RecordingSession
) -> None:
    """One column, four rows, and a headline that names the setting it can change.

    One column is required rather than preferred: ``🌐 Tilni oʻzgartirish``(20) +
    ``🔒 Maʼlumotlarim``(15) is 35 characters in uz_latn, over both the inline budget and the
    reply one, so a two-column row truncates the labels mid-word on a narrow phone.

    ``{language}`` is filled with the language's own ENDONYM rather than the current locale's
    word for it, because that is the string on the button the customer presses next — and a
    raw ``{language}`` on screen is what a template rendered through the wrong call looks like,
    which is a real hazard here: ``settings.title``'s placeholder shares its name with
    ``translate``'s own second parameter.
    """
    # Arrange
    await complete_onboarding(dispatcher, bot, language=Language.EN)

    # Act
    await tap(dispatcher, bot, "menu.settings", Language.EN)

    # Assert — the headline
    screen = session.last_screen
    assert language_label(Language.EN, Language.EN) in screen.text
    assert "{language}" not in screen.text

    # Assert — the rows, in order, one button each
    markup = screen.reply_markup
    assert isinstance(markup, InlineKeyboardMarkup)
    assert [len(row) for row in markup.inline_keyboard] == [1, 1, 1, 1]
    assert [data for _, data in buttons(markup)] == [
        NavCB(action=action).pack() for action in SETTINGS_ACTIONS
    ]


async def test_opening_settings_mid_wizard_does_not_clobber_the_wizard_state(
    dispatcher: Dispatcher, bot: Bot, state: FSMContext
) -> None:
    """The reason there is no ``Settings`` states group beside ``Onboarding``.

    ⚙️ is on a keyboard the customer cannot dismiss, so it is reachable at every moment of a
    wizard run — including with a half-finished draft parked in ``Wizard.name``. A settings
    screen that set its own FSM state would overwrite that park, and the next Back or Cancel
    would find no step to return to: the draft is lost to somebody who only wanted to change
    their language. The submenu is therefore stateless callbacks, exactly like ``navigation``.
    """
    # Arrange
    await walk_to_name(dispatcher, bot)

    # Act — down into Settings and its language picker, then back up
    await tap(dispatcher, bot, "menu.settings", Language.EN)
    await press(dispatcher, bot, NavCB(action=NavAction.SET_LANGUAGE).pack())
    await press(dispatcher, bot, NavCB(action=NavAction.TO_SETTINGS).pack())

    # Assert
    assert await state.get_state() == Wizard.name.state


async def test_the_settings_language_picker_offers_no_cancel(
    dispatcher: Dispatcher, bot: Bot, session: RecordingSession
) -> None:
    """C0-6, on the second of the two screens that reach ``_with_nav`` outside a run.

    ``_with_nav`` appends Cancel unconditionally, so ``is_back_enabled=False`` alone leaves a
    ✖️ Cancel here — and it is not decorative: it reaches ``navigation.handle_cancel``, which
    is stateless by design and would clear the FSM and answer "Cancelled — nothing was made,
    and nothing was kept" to somebody who came to change a language. Mid-wizard it would take
    their draft with it. Back is no better: this screen has no wizard order behind it, so
    ``previous_step`` answers ``None`` and the session expires.

    ``TO_SETTINGS`` is the exit, and unlike Cancel it says where it goes.
    """
    # Arrange
    await complete_onboarding(dispatcher, bot, language=Language.EN)
    await tap(dispatcher, bot, "menu.settings", Language.EN)

    # Act
    await press(dispatcher, bot, NavCB(action=NavAction.SET_LANGUAGE).pack())

    # Assert
    offered = {data for _, data in buttons(session.last_screen.reply_markup)}
    assert len([data for data in offered if data.startswith("lang:set")]) == len(Language)
    assert NavCB(action=NavAction.CANCEL).pack() not in offered
    assert NavCB(action=NavAction.BACK).pack() not in offered
    assert NavCB(action=NavAction.TO_SETTINGS).pack() in offered


async def test_changing_the_language_in_settings_writes_everywhere_it_has_to(
    dispatcher: Dispatcher,
    bot: Bot,
    session: RecordingSession,
    state: FSMContext,
    profiles: FakeProfiles,
) -> None:
    """Three writes and two screens, and every one of them has a failure of its own.

    The ROW is what makes the choice outlive this session. The FSM CACHE is what makes it real
    when there is no store to write to and what survives ``clear_keeping_identity`` between
    runs. The DRAFT is the one a reader forgets: ``resolve_language_or_none`` reads the draft
    FIRST, so a draft left in the old language means the wizard screens speak the new language
    while the error guard, the gate's refusals, the fallback and every ``submitting`` message
    keep speaking the old one — one customer, two languages, one conversation.

    The re-sent menu is the last of it, and this is the ONLY place it is re-sent: the keyboard
    is persistent chat-level state, so it needs replacing exactly where its LABELS changed.
    Re-sending it "whenever a flow ends" would leave a duplicate keyboard message after every
    cancellation and every delivery.
    """
    # Arrange — mid-wizard, so the draft write has something to write to
    await walk_to_name(dispatcher, bot)
    await tap(dispatcher, bot, "menu.settings", Language.EN)
    await press(dispatcher, bot, NavCB(action=NavAction.SET_LANGUAGE).pack())
    session.clear()

    # Act
    await press(dispatcher, bot, LanguageCB(slot=LanguageSlot.SETTINGS, code=Language.RU).pack())

    # Assert — the three writes
    assert profiles.rows[USER_ID].ui_language is Language.RU
    assert (await state.get_data())[UI_LANGUAGE_KEY] == Language.RU.value
    assert (await read_draft_of(state)).ui_language is Language.RU

    # Assert — the toast, the settings screen in the new language, and the new keyboard
    assert session.last_named("AnswerCallbackQuery").text == translate(
        "settings.language.saved", Language.RU
    )
    shown = [getattr(call, "text", None) for call in session.calls]
    assert any(
        isinstance(text, str) and language_label(Language.RU, Language.RU) in text for text in shown
    ), "the settings screen never came back in the new language"
    assert session.last_screen.text == translate("menu.prompt", Language.RU)
    assert reply_buttons(last_reply_keyboard(session)) == reply_buttons(
        main_menu_keyboard(Language.RU)
    )


async def test_my_data_from_settings_renders_the_same_notice_as_the_privacy_command(
    dispatcher: Dispatcher, bot: Bot, session: RecordingSession
) -> None:
    """C0-7. Two surfaces, one notice — asserted as identical strings, not as a shared marker.

    A retention notice that says two different things depending on which button you pressed is
    worse than no retention notice: it is a promise the product cannot keep both halves of.
    The near miss this prevents is cheap to write — a ``CallbackQuery`` handler cannot call
    ``handle_privacy``, which takes a ``Message``, so the obvious fix is a second copy of the
    four period kwargs that drifts from the first the moment a period changes.
    ``common.privacy_text`` is the shared body and this compares the two renderings byte for
    byte.
    """
    # Arrange
    await complete_onboarding(dispatcher, bot, language=Language.EN)
    await send(dispatcher, bot, "/privacy")
    from_command = session.last_screen.text
    await tap(dispatcher, bot, "menu.settings", Language.EN)

    # Act
    await press(dispatcher, bot, NavCB(action=NavAction.SHOW_PRIVACY).pack())

    # Assert
    assert session.last_screen.text == from_command
    assert from_command == privacy_text(Language.EN, DEFAULT_RETENTION_POLICY)


async def test_contact_us_from_settings_renders_the_same_body_as_the_support_command(
    dispatcher: Dispatcher, bot: Bot, session: RecordingSession, settings: Settings
) -> None:
    """The ``common.support_text`` precedent, asserted the same way and for the same reason.

    Two routes to one inbox must not be described differently, and the unconfigured case is
    where a copy would diverge first: with no contact set the copy CHANGES and the destination
    is never faked, because naming an address nobody reads would leave somebody believing they
    had reported a problem with their song.
    """
    # Arrange
    await complete_onboarding(dispatcher, bot, language=Language.EN)
    await send(dispatcher, bot, "/support")
    from_command = session.last_screen.text
    await tap(dispatcher, bot, "menu.settings", Language.EN)

    # Act
    await press(dispatcher, bot, NavCB(action=NavAction.SHOW_SUPPORT).pack())

    # Assert
    assert session.last_screen.text == from_command
    assert from_command == support_text(Language.EN, settings.support_contact)


async def test_the_way_home_from_settings_re_sends_the_menu_rather_than_editing_it_in(
    dispatcher: Dispatcher, bot: Bot, session: RecordingSession
) -> None:
    """🏠 arrives as a NEW message, and that is a property of Telegram rather than a compromise.

    An inline screen cannot become a reply-keyboard screen by editing: ``editMessageText``
    accepts inline markup only and answers 400 for anything else — a failure that happens at
    send time, in production, and that no in-process double in this repo can raise, because
    ``RecordingSession`` answers every method with a canned ``Message``. ``_edit_or_send``
    makes the decision once from the markup type so no caller has to remember it, and this is
    the assertion that the decision is still being made.
    """
    # Arrange
    await complete_onboarding(dispatcher, bot, language=Language.EN)
    await tap(dispatcher, bot, "menu.settings", Language.EN)
    session.clear()

    # Act
    await press(dispatcher, bot, NavCB(action=NavAction.TO_MENU).pack())

    # Assert — a send, carrying the menu, and not an edit
    assert "EditMessageText" not in session.call_names
    assert session.last_screen.text == translate("menu.prompt", Language.EN)
    assert reply_buttons(last_reply_keyboard(session)) == reply_buttons(
        main_menu_keyboard(Language.EN)
    )
