"""First contact, through the real router tree. The only gate between a stranger and a sale.

Onboarding is two screens and one filter, and the three of them fail independently — which is
why this file exists rather than a handful of assertions bolted onto the wizard's tests:

* **A router that must beat every step router without beating ``submitting``.** Registered
  third, it claims any update from a customer with no phone number; registered one place lower
  it would stop blocking the wizard, and one place higher it would swallow ``/privacy`` and
  ``/forget`` from the very people whose data it is collecting. Its stand-down for
  ``Wizard.submitting`` is the other half: without it, ``/forget``'s re-park of a running order
  is overwritten by the catch-all and the next ``/cancel`` says "nothing was made" about a song
  that then arrives.
* **A store whose absence must not lock anyone out.** ``deps.profiles`` is ``None`` on a
  deployment that has not wired one and answers ``Err`` on any deployment whose database
  hiccups. Both fail OPEN, and the tests for that are here (14, 15) because this is the only
  file where the fail-open branch is the subject rather than an accident — everywhere else in
  the suite the store is wired, deliberately (C1-4 / C2-1).
* **A contact button whose ``request_contact`` flag is the only thing that makes it work.** A
  button with the right label and the flag missing looks correct in every screenshot, sends its
  own text back, and strands the customer on the one screen that gates the product.

The number is not collected for its own sake: it is the delivery fallback for a song Telegram
could not hand over. That is why a card belonging to somebody else is refused rather than
stored, why a typed number is refused rather than parsed, and why both of those have a test
here that names the person who would otherwise receive a stranger's song.
"""

from __future__ import annotations

from typing import Final

import pytest
from aiogram import Bot, Dispatcher
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.base import StorageKey
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import Update

from bayram.bot.app import build_dispatcher
from bayram.bot.callbacks import LanguageCB, LanguageSlot, NavAction, NavCB
from bayram.bot.deps import BotDeps
from bayram.bot.draft import DRAFT_KEY, ONBOARDED_KEY, UI_LANGUAGE_KEY
from bayram.bot.handlers.common import privacy_text, support_text
from bayram.bot.i18n import FALLBACK_LANGUAGE, translate
from bayram.bot.states import Onboarding, Wizard, WizardStep, state_for, step_for_state
from bayram.config import Settings
from bayram.contracts import Language
from bayram.db.retention import DEFAULT_RETENTION_POLICY
from bayram.errors import StorageError
from bayram.user_profiles import AVATAR_MIME, UserProfileStore
from tests.test_bot.conftest import (
    AVATAR_BYTES,
    BOT_ID,
    CHAT_ID,
    SEEDED_PHONE,
    USER_ID,
    FakeProfiles,
    RecordingContentWriter,
    RecordingSession,
    RecordingSubmitter,
    arm_avatar,
    buttons,
    contact_update,
    last_reply_keyboard,
    profile_photos,
    reply_buttons,
    requests_contact,
)
from tests.test_bot.test_wizard_flow import complete_onboarding, press, send, tap

#: The ``@username`` Telegram reports for the account under test.
#:
#: It is put on ``from_user`` by :func:`contact_update_from_a_named_account` rather than taken
#: from the shared builder, because the identity fields are read off ``from_user`` and NEVER
#: off the ``Contact`` card: a card carries no username at all, and its names are whatever the
#: sharer typed into their own address book. A test whose sender had no username could not tell
#: "the handler read the right object" from "the handler read nothing".
SENDER_USERNAME: Final[str] = "dilnoza"

#: The surname on the account. U+02BB, as every Uzbek Latin string in this tree is: an
#: apostrophe here would pass every assertion below and still be the wrong character in the
#: admin console, which is the one place a human reads it back.
SENDER_LAST_NAME: Final[str] = "Yoʻldosheva"

#: A number typed as text instead of shared with the button. Deliberately the SAME digits the
#: button would have sent, so the test that refuses it cannot be passing because the number was
#: malformed — what makes it unusable is that nothing attributes it to the sender.
TYPED_NUMBER: Final[str] = SEEDED_PHONE


def contact_update_from_a_named_account(**kwargs: object) -> Update:
    """A shared contact whose SENDER carries a username and a surname.

    The shared builder's ``from_user`` has a first name and nothing else, which is honest —
    most Telegram accounts are exactly that — but it cannot exercise the branch that copies
    ``user.username`` into the row. Copying the whole builder to add two fields would fork the
    one place ``Contact.user_id`` is explained, so the update is rebuilt from it instead.
    """
    update = contact_update(**kwargs)
    message = update.message
    assert message is not None and message.from_user is not None
    sender = message.from_user.model_copy(
        update={"username": SENDER_USERNAME, "last_name": SENDER_LAST_NAME}
    )
    return update.model_copy(update={"message": message.model_copy(update={"from_user": sender})})


def wire(settings: Settings, *, profiles: FakeProfiles | None) -> tuple[Dispatcher, FSMContext]:
    """A dispatcher and its FSM handle, for the two cases the shared fixture cannot express.

    Those two are ``profiles=None`` (nothing wired) and a store that answers ``Err``, and
    CONTRACTS §7 scopes both to this file: the shared ``deps`` fixture carries a working
    ``FakeProfiles`` precisely so the rest of the suite drives the screens that ship, and a
    module-level override would take that away from every test here as well.
    """
    deps = BotDeps(
        settings=settings,
        submitter=RecordingSubmitter(),
        content=RecordingContentWriter(),
        profiles=profiles,
    )
    storage = MemoryStorage()
    state = FSMContext(
        storage=storage, key=StorageKey(bot_id=BOT_ID, chat_id=CHAT_ID, user_id=USER_ID)
    )
    return build_dispatcher(deps, storage=storage), state


def texts(session: RecordingSession) -> list[str]:
    """Every sentence the customer was shown, in order. Sends and edits alike.

    Read through ``getattr`` rather than off ``call.text``: ``session.calls`` is a list of
    ``TelegramMethod``, and most of the methods in it — ``AnswerCallbackQuery``, ``GetFile``,
    ``GetUserProfilePhotos`` — have no ``text`` at all.
    """
    shown: list[str] = []
    for call in session.calls:
        if type(call).__name__ not in {"SendMessage", "EditMessageText"}:
            continue
        text = getattr(call, "text", None)
        if isinstance(text, str):
            shown.append(text)
    return shown


def index_of_text(session: RecordingSession, needle: str) -> int:
    """Where in ``session.calls`` the message carrying ``needle`` was sent.

    An index into the WHOLE call list rather than into the screens, because what the ordering
    assertions compare it against is a ``getUserProfilePhotos`` — a call that puts nothing on
    screen and therefore has no position among the screens at all.
    """
    for position, call in enumerate(session.calls):
        text = getattr(call, "text", None)
        if isinstance(text, str) and needle in text:
            return position
    raise AssertionError(f"nothing on screen contained {needle!r}; sent {texts(session)}")


# ---------------------------------------------------------------------------
# The language question
# ---------------------------------------------------------------------------
async def test_a_stranger_is_asked_their_language_before_anything_else(
    dispatcher: Dispatcher, bot: Bot, session: RecordingSession, state: FSMContext
) -> None:
    """The first screen, and the two buttons that must NOT be on it (C0-6).

    ``_with_nav`` appends Cancel unconditionally, so ``is_back_enabled=False`` alone would put
    ✖️ Cancel on the first screen anybody ever sees — a button that reaches
    ``navigation.handle_cancel`` and answers "Cancelled — nothing was made, and nothing was
    kept" to somebody who has started nothing. Back is worse: it reaches ``handle_back``, whose
    ``step_for_state`` answers ``None`` for an ``Onboarding.*`` name and expires the session
    the customer is halfway through creating.

    The sentence is drawn in the operator's configured default because nobody has chosen yet.
    That guess is survivable only because the four buttons are drawn in each language's own
    name, which is what the completeness assertion below pins.
    """
    # Arrange / Act
    await send(dispatcher, bot, "/start")

    # Assert
    screen = session.last_screen
    offered = {data for _, data in buttons(screen.reply_markup)}
    assert await state.get_state() == Onboarding.language.state
    assert screen.text == translate("onboarding.language.prompt", Language.UZ_LATN)
    assert len([data for data in offered if data.startswith("lang:ui")]) == len(Language)
    assert NavCB(action=NavAction.CANCEL).pack() not in offered
    assert NavCB(action=NavAction.BACK).pack() not in offered


async def test_choosing_a_language_persists_it_and_asks_for_the_number(
    dispatcher: Dispatcher,
    bot: Bot,
    session: RecordingSession,
    state: FSMContext,
    profiles: FakeProfiles,
) -> None:
    """One tap writes the row, moves the state on, and changes the language of everything.

    The row is what makes the answer outlive this session; the state is what makes the next
    update land on the contact handlers rather than back here. Asserting only the screen would
    let a build that renders the contact prompt without persisting anything pass, and that
    build re-asks the language on every single session for ever.

    The reply keyboard is read off the recorded call rather than off the canned reply, because
    ``Message.reply_markup`` cannot carry one — see ``RecordingSession._message_for``.
    """
    # Arrange
    await send(dispatcher, bot, "/start")

    # Act
    await press(dispatcher, bot, LanguageCB(slot=LanguageSlot.UI, code=Language.RU).pack())

    # Assert — the row, the state, and the screen, in that order of importance
    row = profiles.rows[USER_ID]
    assert row.ui_language is Language.RU
    assert row.language_chosen_at is not None
    assert await state.get_state() == Onboarding.contact.state
    assert translate("onboarding.contact.prompt", Language.RU) in session.last_screen.text
    markup = last_reply_keyboard(session)
    assert reply_buttons(markup) == ((translate("button.share_contact", Language.RU),),)
    assert requests_contact(markup) is True


async def test_the_privacy_line_is_shown_with_the_contact_request(
    dispatcher: Dispatcher, bot: Bot, session: RecordingSession
) -> None:
    """A number asked for without saying what happens to it is a notice failure.

    ``privacy.text`` exists so nobody has to guess what this product keeps, and the whole of it
    is one command away — but the moment the answer matters to the person deciding is THIS
    screen, with their thumb over the button. The promise and the request therefore travel
    together, in one message, and a build that moved the line into ``/privacy`` alone would
    leave the decision uninformed at the only point it is being made.
    """
    # Arrange / Act
    await send(dispatcher, bot, "/start")
    await press(dispatcher, bot, LanguageCB(slot=LanguageSlot.UI, code=Language.EN).pack())

    # Assert — one screen carries both halves
    screen = session.last_screen.text
    assert translate("onboarding.contact.prompt", Language.EN) in screen
    assert translate("onboarding.contact.privacy_line", Language.EN) in screen


# ---------------------------------------------------------------------------
# The contact question
# ---------------------------------------------------------------------------
async def test_sharing_a_contact_stores_the_number_the_username_and_the_name(
    dispatcher: Dispatcher,
    bot: Bot,
    session: RecordingSession,
    state: FSMContext,
    profiles: FakeProfiles,
) -> None:
    """The write that ends onboarding, field by field.

    Four fields and each has its own failure. The number is the delivery fallback and is stored
    NORMALISED, because a store that kept "+998 90 123 45 42" as typed would hand the notifier
    a string no dialler accepts. The username, the first name and the last name come off
    ``from_user`` — the account this bot is talking to — and not off the ``Contact`` card, whose
    names are whatever the SHARER once typed into their address book and whose username field
    does not exist at all.

    ``is_onboarded`` is derived from the phone number rather than stored, so asserting it here
    is asserting that the one property every other gate in the tree reads has actually flipped.
    """
    # Arrange
    await send(dispatcher, bot, "/start")
    await press(dispatcher, bot, LanguageCB(slot=LanguageSlot.UI, code=Language.EN).pack())

    # Act
    await dispatcher.feed_update(bot, contact_update_from_a_named_account())

    # Assert — the row
    row = profiles.rows[USER_ID]
    assert row.phone_e164 == SEEDED_PHONE
    assert row.telegram_username == SENDER_USERNAME, "the '@' is not part of the username"
    assert row.first_name == "Dilnoza"
    assert row.last_name == SENDER_LAST_NAME
    assert row.is_onboarded is True

    # Assert — the receipt, then the menu, and nothing left of the onboarding state
    shown = texts(session)
    assert translate("onboarding.contact.saved", Language.EN) in shown
    assert translate("menu.prompt", Language.EN) in shown[-1]
    assert await state.get_state() is None


async def test_a_number_belonging_to_somebody_else_is_refused_and_the_step_stands(
    dispatcher: Dispatcher,
    bot: Bot,
    session: RecordingSession,
    state: FSMContext,
    profiles: FakeProfiles,
) -> None:
    """The security control on this screen, and the song it stops from reaching a stranger.

    Telegram lets anyone forward any card out of their address book. A forwarded card has the
    same phone shape, arrives through the same button and differs in exactly one field —
    ``Contact.user_id``, which is set only when the card IS a Telegram account and equals the
    sender only when it is THEIR account. Store one without comparing it and every delivery
    fallback, every notification and every erasure this product performs is aimed at a person
    who never spoke to it, using a number they never gave anybody here.

    Nothing is persisted and the state does not move: the customer is still being asked, which
    is the only true thing to say to somebody who has not yet answered.
    """
    # Arrange
    await send(dispatcher, bot, "/start")
    await press(dispatcher, bot, LanguageCB(slot=LanguageSlot.UI, code=Language.EN).pack())

    # Act — a card that belongs to somebody else
    await dispatcher.feed_update(bot, contact_update(contact_user_id=999))

    # Assert
    assert session.last_screen.text == translate("onboarding.contact.foreign", Language.EN)
    assert await state.get_state() == Onboarding.contact.state
    assert profiles.rows[USER_ID].phone_e164 is None


async def test_a_typed_number_is_not_accepted_in_place_of_the_button(
    dispatcher: Dispatcher,
    bot: Bot,
    session: RecordingSession,
    state: FSMContext,
    profiles: FakeProfiles,
) -> None:
    """The same digits, typed instead of shared, and the reason that is not the same thing.

    A typed number is unattributable. Nothing about it says it belongs to the person who typed
    it, which makes it the forwarded-card failure above with the evidence removed — so it is
    refused for the same reason and with the same screen, not parsed and stored. The digits
    here are exactly the ones the button would have sent, so a build that passed this test by
    rejecting a malformed number would still fail it.
    """
    # Arrange
    await send(dispatcher, bot, "/start")
    await press(dispatcher, bot, LanguageCB(slot=LanguageSlot.UI, code=Language.EN).pack())

    # Act
    await send(dispatcher, bot, TYPED_NUMBER)

    # Assert
    assert session.last_screen.text == translate("onboarding.contact.required", Language.EN)
    assert requests_contact(last_reply_keyboard(session)) is True
    assert await state.get_state() == Onboarding.contact.state
    assert profiles.rows[USER_ID].phone_e164 is None


async def test_the_wizard_is_unreachable_until_the_number_is_shared(
    dispatcher: Dispatcher, bot: Bot, session: RecordingSession, state: FSMContext
) -> None:
    """🎵 pressed mid-onboarding, from a keyboard an earlier session left pinned.

    The menu router sits BELOW onboarding for exactly this update. If it sat above, a reply
    keyboard the customer cannot dismiss would be a working shortcut past the one question
    this product promises to ask before it sells anything — and the draft it opened would
    belong to somebody the bot has no way of delivering to.
    """
    # Arrange
    await send(dispatcher, bot, "/start")
    await press(dispatcher, bot, LanguageCB(slot=LanguageSlot.UI, code=Language.EN).pack())

    # Act
    await tap(dispatcher, bot, "menu.generate", Language.EN)

    # Assert — the question again, no wizard, no draft
    assert session.last_screen.text == translate("onboarding.contact.required", Language.EN)
    assert await state.get_state() == Onboarding.contact.state
    assert DRAFT_KEY not in await state.get_data()


async def test_a_command_still_works_mid_onboarding(
    dispatcher: Dispatcher,
    bot: Bot,
    session: RecordingSession,
    state: FSMContext,
    settings: Settings,
) -> None:
    """Routers one and two claim every command, and this is C2-4 asserted rather than described.

    An onboarding router above ``commands`` would deny ``/privacy`` and ``/forget`` to the one
    population whose data it is in the middle of collecting — re-creating at the router layer
    exactly the denial ``gate.ERASURE_COMMANDS`` exists to prevent. Above ``start`` it would
    make ``/start`` unreachable, which is the command a stuck person always tries.

    ``/cancel`` is the interesting one and it is why this router writes no handler for it:
    ``start.handle_cancel_command`` claims it first from anywhere, so it answers
    ``wizard.cancelled``, and the catch-all re-enters onboarding on the very next update. A
    ``/cancel`` handler written inside the onboarding router would be dead code.
    """
    # Arrange
    await send(dispatcher, bot, "/start")
    await press(dispatcher, bot, LanguageCB(slot=LanguageSlot.UI, code=Language.EN).pack())

    # Act / Assert — the four read-only commands answer normally, in the chosen language
    for command, expected in (
        ("/help", translate("help.text", Language.EN)),
        ("/balance", translate("credits.balance_none", Language.EN)),
        ("/privacy", privacy_text(Language.EN, DEFAULT_RETENTION_POLICY)),
        ("/support", support_text(Language.EN, settings.support_contact)),
    ):
        session.clear()
        await send(dispatcher, bot, command)
        assert session.last_screen.text == expected, f"{command} was not answered"

    # Act / Assert — /cancel is answered by ``start``, and the next tap re-enters onboarding
    session.clear()
    await send(dispatcher, bot, "/cancel")
    # ``finish_with`` reads the DRAFT for its language and there is no draft before the wizard,
    # so this one sentence lands in the fallback locale rather than in the language chosen two
    # updates ago. Asserted as it ships rather than as it ought to read: pinning the fallback
    # here is what makes a later fix to ``common.finish_with`` show up as a failing test
    # instead of as a silent change to the one screen a mid-onboarding /cancel produces.
    assert session.last_screen.text == translate("wizard.cancelled", FALLBACK_LANGUAGE)
    await send(dispatcher, bot, "hello?")
    assert await state.get_state() == Onboarding.contact.state
    assert translate("onboarding.contact.prompt", Language.EN) in session.last_screen.text


# ---------------------------------------------------------------------------
# The avatar: three round trips, all of them behind the confirmation
# ---------------------------------------------------------------------------
async def test_the_avatar_is_fetched_best_effort_after_the_number_lands(
    dispatcher: Dispatcher, bot: Bot, session: RecordingSession, profiles: FakeProfiles
) -> None:
    """The face is stored, and it is stored BEHIND the customer's confirmation.

    Three sequential Telegram round trips sit inside this fetch, on the update that has just
    told somebody their number was saved, inside aiogram's per-chat isolation lock. In front of
    the confirmation they are three chances for the product to appear to hang at the exact
    moment a customer is deciding whether to trust it; behind it they are invisible, and the
    worst outcome is a row with no picture on it in an operator's console.

    The MIME is asserted because ``record_avatar`` stores nothing for a content type it does not
    recognise and the admin route serves nothing outside ``AVATAR_MIMES``: three independent
    literals would drift in both directions at once and the result is "no avatars anywhere"
    with a fully green suite. ``AVATAR_MIME`` is the one spelling, and this reads it.
    """
    # Arrange
    arm_avatar(session)

    # Act
    await complete_onboarding(dispatcher, bot, language=Language.EN)

    # Assert — what was stored, and that it happened after the receipt
    assert profiles.avatars == [(USER_ID, AVATAR_MIME, "u-small", len(AVATAR_BYTES))]
    assert profiles.rows[USER_ID].avatar_stored_at is not None
    saved_at = index_of_text(session, translate("onboarding.contact.saved", Language.EN))
    fetched_at = session.calls.index(session.last_named("GetUserProfilePhotos"))
    assert fetched_at > saved_at, "the customer waited on three round trips for a picture"


async def test_a_profile_photo_the_account_does_not_have_stores_nothing_and_says_nothing(
    dispatcher: Dispatcher, bot: Bot, session: RecordingSession, profiles: FakeProfiles
) -> None:
    """No photo and photos hidden by privacy are the same event, and both are ordinary.

    Telegram answers ``getUserProfilePhotos`` for a restricted account with an EMPTY
    ``UserProfilePhotos`` rather than an error, so the fetcher cannot tell the two apart and
    must not try. Neither is a failure worth a word to the customer: an apology here would be an
    apology for something they did not ask for and cannot see, about a convenience that exists
    for an operator.
    """
    # Arrange — the account answers, and has nothing to give
    session.responses["GetUserProfilePhotos"] = profile_photos(total_count=0)

    # Act
    await complete_onboarding(dispatcher, bot, language=Language.EN)

    # Assert — nothing stored, no second round trip, and the menu is what is on screen
    assert profiles.avatars == []
    assert "GetFile" not in session.call_names
    assert translate("menu.prompt", Language.EN) in session.last_screen.text
    assert translate("error.generic", Language.EN) not in texts(session)


async def test_an_avatar_the_bot_could_not_download_is_not_stored_as_zero_bytes(
    dispatcher: Dispatcher, bot: Bot, session: RecordingSession, profiles: FakeProfiles
) -> None:
    """The empty download, which used to be indistinguishable from a successful one.

    ``stream_content`` yields ``b""`` for a path nobody registered — which is what an expired
    ``file_path`` does in production — so a fetcher that stored what it read would write a
    zero-byte object and a row saying there is a face to serve. The admin console would then
    request it, get nothing, and draw a broken image where the monogram belongs.

    Both hops are armed and only the bytes are taken away, so the failure under test is the
    download and not a missing ``file_path``.
    """
    # Arrange
    arm_avatar(session)
    session.files.clear()

    # Act
    await complete_onboarding(dispatcher, bot, language=Language.EN)

    # Assert
    assert profiles.avatars == []
    assert profiles.rows[USER_ID].avatar_stored_at is None


async def test_the_size_ladder_is_photos_zero_and_the_smallest_rung_is_taken(
    dispatcher: Dispatcher, bot: Bot, session: RecordingSession
) -> None:
    """``UserProfilePhotos.photos`` is ``list[list[PhotoSize]]``, and ``[0]`` is the LADDER.

    Iterating the outer list iterates PHOTOS and treats each ladder as one size (C0-15/C1-14),
    which type-checks, runs, and picks whichever rung happens to sort first. The rung actually
    wanted is the smallest one at least 320 px: the console draws a 3rem thumbnail, so the
    largest rung would drag a multi-megabyte original through this process, through
    ``AVATAR_MAX_BYTES``, and onto disk for a face nobody sees above 200 CSS pixels.
    """
    # Arrange
    arm_avatar(session)

    # Act
    await complete_onboarding(dispatcher, bot, language=Language.EN)

    # Assert — the cheap rung of the one photo's ladder
    assert session.last_named("GetFile").file_id == "small"


# ---------------------------------------------------------------------------
# Coming back, and coming back to nothing
# ---------------------------------------------------------------------------
async def test_a_returning_customer_is_never_asked_again(
    dispatcher: Dispatcher,
    bot: Bot,
    session: RecordingSession,
    state: FSMContext,
    profiles: FakeProfiles,
) -> None:
    """``/start`` from somebody the bot knows is the MENU, in THEIR language, with no pitch.

    This is the defect the whole feature was built around: the interface language used to be
    the first screen of every wizard run, so a weekly customer answered a settled question every
    week for ever. ``start.welcome`` is 214-231 characters of product pitch and is drawn exactly
    once, on the first menu after onboarding — a returning customer reading it again would be
    reading it for the twelfth time, which is how a pitch becomes noise and then a skipped
    message.
    """
    # Arrange
    profiles.seed(USER_ID, ui_language=Language.RU)

    # Act
    await send(dispatcher, bot, "/start")

    # Assert
    assert session.last_screen.text == translate("menu.prompt", Language.RU)
    assert translate("start.welcome", Language.RU) not in session.last_screen.text
    assert await state.get_state() is None


async def test_with_no_store_at_all_the_bot_still_works_and_still_has_a_language_picker(
    settings: Settings, bot: Bot, session: RecordingSession
) -> None:
    """C1-5, one half: a deployment with no ``profiles`` wired sells songs and speaks Russian.

    With no store there is nothing that can answer "have we met?", and the answer this tree
    gives is *yes* — fail open, treat them as onboarded, let them through. The alternative
    fails CLOSED, which on an unwired deployment means every customer is stuck on a contact
    screen whose answer can never be stored and the product is simply down.

    The language picker still has to work, because with no row the FSM cache is the only place
    a choice can live, and ``handle_settings_language_chosen`` writes it unconditionally for
    exactly this configuration. Without that write a deployment with no persistence would be
    permanently ``uz_latn`` with a picker that visibly did nothing.
    """
    # Arrange
    dispatcher, state = wire(settings, profiles=None)

    # Act — straight to the menu, then change the language from Settings
    await send(dispatcher, bot, "/start")
    assert session.last_screen.text == translate("menu.prompt", settings.default_ui_language)
    await tap(dispatcher, bot, "menu.settings", settings.default_ui_language)
    await press(dispatcher, bot, NavCB(action=NavAction.SET_LANGUAGE).pack())
    await press(dispatcher, bot, LanguageCB(slot=LanguageSlot.SETTINGS, code=Language.EN).pack())

    # Assert — the choice is remembered and everything after it is in English
    assert (await state.get_data())[UI_LANGUAGE_KEY] == Language.EN.value
    assert translate("menu.prompt", Language.EN) in texts(session)[-1]
    assert await state.get_state() is None


async def test_a_store_that_errs_fails_open_the_same_way(
    settings: Settings, bot: Bot, session: RecordingSession
) -> None:
    """C1-5, the other half: a database blip must not look like a product refusal.

    An ``Err`` from ``profiles.get`` is the shape of a five-second outage, and the customer on
    the other end of it is in the middle of buying something. Treating them as onboarded costs
    at most a missing phone number for one session; treating them as a stranger costs the sale
    and shows an error for a fault they cannot act on and did not cause.

    Nothing is written on this branch, and that is the deliberate asymmetry: caching a
    fail-open answer would turn the blip into a permanent state for the fourteen-day life of
    the FSM data, and the contact screen would never be shown again.
    """
    # Arrange
    dispatcher, state = wire(settings, profiles=FakeProfiles(failure=StorageError("down")))

    # Act
    await send(dispatcher, bot, "/start")
    await tap(dispatcher, bot, "menu.settings", settings.default_ui_language)
    await press(dispatcher, bot, NavCB(action=NavAction.SET_LANGUAGE).pack())
    await press(dispatcher, bot, LanguageCB(slot=LanguageSlot.SETTINGS, code=Language.EN).pack())

    # Assert — the same outcome as no store at all, and not one word about the failure
    assert (await state.get_data())[UI_LANGUAGE_KEY] == Language.EN.value
    assert translate("menu.prompt", Language.EN) in texts(session)[-1]
    assert ONBOARDED_KEY not in await state.get_data(), "a fail-open answer must not be cached"
    for language in Language:
        assert translate("error.generic", language) not in texts(session)


async def test_a_failed_language_persist_is_not_reverted_by_the_next_cold_read(
    dispatcher: Dispatcher,
    bot: Bot,
    session: RecordingSession,
    state: FSMContext,
    profiles: FakeProfiles,
) -> None:
    """D15: the swallowed ``Err``, and the guard two files away that makes swallowing it honest.

    ``handle_settings_language_chosen`` logs and swallows a failed ``record_language`` on the
    grounds that the FSM cache has already made the change real for this session. That claim
    holds only because ``load_identity``'s write-back is NON-CLOBBERING — it writes
    ``UI_LANGUAGE_KEY`` only when the key is ABSENT. Without the guard, the next COLD read
    overwrites the customer's visible choice from the stale row, and the language reverts with
    no signal anywhere: no error, no log the customer can see, no second confirmation. They
    simply get answered in the wrong language a few minutes after changing it.

    The cold read is forced by dropping ``ONBOARDED_KEY`` alone rather than by emptying the dict
    the way ``runtime/jobs.py`` does on delivery. Emptying it takes ``UI_LANGUAGE_KEY`` with it,
    and the repair from the row is then the CORRECT behaviour — so a test that wiped both would
    assert something no guard could ever satisfy, and would fail on a build that has it.
    """
    # Arrange — an onboarded Russian speaker whose store falls over mid-session
    profiles.seed(USER_ID, ui_language=Language.EN)
    await send(dispatcher, bot, "/start")
    profiles.failure = StorageError("down")
    await tap(dispatcher, bot, "menu.settings", Language.EN)
    await press(dispatcher, bot, NavCB(action=NavAction.SET_LANGUAGE).pack())
    await press(dispatcher, bot, LanguageCB(slot=LanguageSlot.SETTINGS, code=Language.RU).pack())
    assert profiles.rows[USER_ID].ui_language is Language.EN, "the write was meant to fail"

    # Arrange — the store recovers, and the cheap path expires
    profiles.failure = None
    data = await state.get_data()
    data.pop(ONBOARDED_KEY, None)
    await state.set_data(data)
    session.clear()

    # Act — one more update, taking the cold path through the stale row
    await tap(dispatcher, bot, "menu.help", Language.EN)

    # Assert — still Russian
    assert session.last_screen.text == translate("help.text", Language.RU)
    assert (await state.get_data())[UI_LANGUAGE_KEY] == Language.RU.value


# ---------------------------------------------------------------------------
# /forget: back to true first contact
# ---------------------------------------------------------------------------
async def test_forget_returns_the_account_to_true_first_contact(
    dispatcher: Dispatcher,
    bot: Bot,
    session: RecordingSession,
    state: FSMContext,
    profiles: FakeProfiles,
) -> None:
    """PD-3. The row is DELETED, the face goes with it, and BOTH questions come again.

    Blanking the columns would leave a row that still says somebody was here, and the promise
    of this command is that afterwards nothing distinguishes an erased customer from one who
    has never used the bot. There is no ``language_chosen_at`` survivor either: a bot that
    remembered the language would be contradicting its own confirmation, which says in so many
    words that it will ask which language to speak and for the number again next time.
    """
    # Arrange — an onboarded account with a face
    arm_avatar(session)
    await complete_onboarding(dispatcher, bot, language=Language.EN)
    assert profiles.avatars, "the arrangement is meant to store an avatar"

    # Act
    await send(dispatcher, bot, "/forget")

    # Assert — nothing left, anywhere
    assert profiles.forgotten == [USER_ID]
    assert USER_ID not in profiles.rows
    assert profiles.avatars == []

    # Assert — the very next /start asks the LANGUAGE question, not just the contact one
    await send(dispatcher, bot, "/start")
    assert await state.get_state() == Onboarding.language.state
    assert session.last_screen.text == translate("onboarding.language.prompt", Language.UZ_LATN), (
        "with no row there is no language, so the guess is the operator's default again"
    )


@pytest.mark.parametrize("language", list(Language))
async def test_forget_says_so_in_the_confirmation(
    dispatcher: Dispatcher,
    bot: Bot,
    session: RecordingSession,
    profiles: FakeProfiles,
    language: Language,
) -> None:
    """The confirmation is the erasure record, so it is asserted in all four locales.

    ``privacy.forgotten`` now promises that the number, the username, the name and the photo
    are gone and that both questions come again. A locale that skipped that edit ships a
    confirmation that is a paragraph short — and the person reading it is the one who just
    asked to be forgotten, in the language they asked in. Parametrised so that failure lands
    here rather than in front of them.
    """
    # Arrange — a returning customer who speaks this language
    profiles.seed(USER_ID, ui_language=language)
    await send(dispatcher, bot, "/start")
    session.clear()

    # Act
    await send(dispatcher, bot, "/forget")

    # Assert
    assert session.last_screen.text == translate("privacy.forgotten", language)


async def test_forget_clears_the_identity_cache_because_a_full_reset_is_the_point(
    dispatcher: Dispatcher, bot: Bot, state: FSMContext
) -> None:
    """The deliberate asymmetry with ``clear_keeping_identity``, asserted from the other side.

    Every other ``state.clear()`` in the tree became ``clear_keeping_identity``, which keeps the
    two cache keys. ``handle_forget`` keeps a BARE clear, because it is the one operation whose
    entire purpose is to return the account to first-contact state. A "simplification" that
    made all six sites use one helper would leave ``ONBOARDED_KEY`` behind after an erasure, and
    the catch-all would then take the cheap path and never ask for a number again — the bot
    would be quietly certain about a customer it has just promised to know nothing about.
    """
    # Arrange
    await complete_onboarding(dispatcher, bot, language=Language.EN)
    assert ONBOARDED_KEY in await state.get_data()

    # Act
    await send(dispatcher, bot, "/forget")

    # Assert
    data = await state.get_data()
    assert UI_LANGUAGE_KEY not in data
    assert ONBOARDED_KEY not in data


async def test_the_identity_cache_survives_a_flow_ending(
    dispatcher: Dispatcher,
    bot: Bot,
    session: RecordingSession,
    state: FSMContext,
    profiles: FakeProfiles,
) -> None:
    """C2-8, and the store is taken away afterwards so only the CACHE can be answering.

    ``finish_with`` reaches ``clear_keeping_identity``, which keeps ``UI_LANGUAGE_KEY`` and
    ``ONBOARDED_KEY``. A bare clear there would have two costs, and this asserts both are gone:
    the catch-all would go back to the database on essentially every idle update inside the FSM
    isolation lock, and a returning Russian speaker would be answered in Uzbek Latin from the
    first message after any cancelled run.

    Emptying ``profiles.rows`` before the last tap is what makes the assertion about the cache
    rather than about the store: with the row gone, a build that dropped the two keys sends this
    customer straight back to the language question.
    """
    # Arrange — onboarded, then a wizard run cancelled
    await complete_onboarding(dispatcher, bot, language=Language.EN)
    await tap(dispatcher, bot, "menu.generate", Language.EN)
    await press(dispatcher, bot, NavCB(action=NavAction.CANCEL).pack())

    # Assert — the two keys, and only the two
    assert await state.get_data() == {UI_LANGUAGE_KEY: Language.EN.value, ONBOARDED_KEY: True}

    # Act — the store forgets everything it knew, and the customer taps 🎵 again
    profiles.rows.clear()
    session.clear()
    await tap(dispatcher, bot, "menu.generate", Language.EN)

    # Assert — a wizard, not the onboarding catch-all
    assert await state.get_state() == Wizard.occasion.state
    assert translate("wizard.occasion.prompt", Language.EN) in session.last_screen.text


# ---------------------------------------------------------------------------
# The two structural facts the rest of this file rests on
# ---------------------------------------------------------------------------
def test_the_fake_profile_store_really_is_the_port() -> None:
    """A fake that has drifted from the Protocol proves things about a class nobody ships.

    ``UserProfileStore`` is ``runtime_checkable``, so this is a cheap check with an expensive
    absence: every onboarding assertion in the suite runs against ``FakeProfiles``, and a
    method whose name or shape has drifted from the port would leave all of them green while
    ``SqlUserProfiles`` fails at the first call in production. Named as a test rather than
    written as a module-level assertion so the drift arrives as a sentence instead of as an
    import error under a collection stack trace.
    """
    # Arrange / Act / Assert
    assert isinstance(FakeProfiles(), UserProfileStore)


def test_the_onboarding_states_are_not_wizard_steps() -> None:
    """CONTRACTS §4's reason for a second ``StatesGroup``, asserted rather than trusted.

    Everything in ``states.py`` treats a ``Wizard`` member as a step of an order:
    ``state_for`` is an UNDEFAULTED dict lookup, ``render_step``'s match is total over
    ``WizardStep``, and ``navigation`` reads ``step_for_state``. An ``Onboarding`` state
    smuggled into that machinery would be rendered as a wizard screen from a draft that does
    not exist — and, in the other direction, ``step_for_state`` answering a step for it would
    send Back into a wizard the customer has not started.
    """
    # Arrange
    wizard_state_names = {state_for(step).state for step in WizardStep}

    # Act / Assert
    assert step_for_state(Onboarding.language.state) is None
    assert step_for_state(Onboarding.contact.state) is None
    assert Onboarding.language.state not in wizard_state_names
    assert Onboarding.contact.state not in wizard_state_names
