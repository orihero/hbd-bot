"""The chat keeps the song and its lyrics, and nothing of ours that has been acted on.

``bot.cleanup`` and ``handlers.common.present`` retire the screen a customer has just
answered — deleted, or stripped of its keyboard when Telegram will no longer delete it — and
these tests pin the four rules that make that safe:

* the delivered song is NEVER deleted, even though 🏠 and 🎂 are pressed on it;
* the message carrying the reply keyboard goes only AFTER a newer one is up;
* a notice survives the update that said it and goes with the next one;
* a refused delete degrades to stripping the keyboard, never to an error.

``RecordingSession`` answers every method with a canned ``Message``, so a 400 Telegram would
raise on an edit of an audio is invisible here — which is why the media guard has its own
test with a message that really carries an ``Audio``.
"""

from __future__ import annotations

from aiogram import Bot, Dispatcher
from aiogram.exceptions import TelegramBadRequest
from aiogram.fsm.context import FSMContext
from aiogram.methods import DeleteMessage, EditMessageReplyMarkup, SendMessage
from aiogram.types import Audio, CallbackQuery, Chat, Message, Update, User

from bayram.bot.callbacks import (
    GenreCB,
    LanguageCB,
    LanguageSlot,
    NavAction,
    NavCB,
    OccasionCB,
    VocalGenderCB,
)
from bayram.bot.cleanup import (
    MENU_MESSAGE_ID_KEY,
    NOTICE_MESSAGE_IDS_KEY,
    PROGRESS_MESSAGE_ID_KEY,
    SCREEN_MESSAGE_ID_KEY,
    retire_message,
)
from bayram.bot.draft import ONBOARDED_KEY, UI_LANGUAGE_KEY
from bayram.bot.handlers.common import clear_keeping_identity
from bayram.bot.i18n import translate
from bayram.contracts import Genre, Language, Occasion, VoiceGender
from tests.test_bot.conftest import (
    BOT_ID,
    CHAT_ID,
    FIXED_MOMENT,
    USER_ID,
    RecordingSession,
)
from tests.test_bot.test_wizard_flow import complete_onboarding, press, send, tap

#: ``make_callback``'s message id: every pressed button arrives on this message in this harness.
PRESSED_ON = 20

#: A delivered song's message id, far from anything the session hands out.
SONG_ID = 4242


def deleted_ids(session: RecordingSession) -> list[int]:
    return [call.message_id for call in session.calls if isinstance(call, DeleteMessage)]


def stripped_ids(session: RecordingSession) -> list[int]:
    return [call.message_id for call in session.calls if isinstance(call, EditMessageReplyMarkup)]


def index_of(session: RecordingSession, method: type, **fields: object) -> int:
    for position, call in enumerate(session.calls):
        if isinstance(call, method) and all(getattr(call, k) == v for k, v in fields.items()):
            return position
    raise AssertionError(f"no {method.__name__} with {fields}; calls were {session.call_names}")


def song_message() -> Message:
    """The delivered audio, as Telegram hands it back: a caption, no text, an ``Audio``."""
    return Message(
        message_id=SONG_ID,
        date=FIXED_MOMENT,
        chat=Chat(id=CHAT_ID, type="private"),
        from_user=User(id=BOT_ID, is_bot=True, first_name="Bayram"),
        audio=Audio(file_id="song", file_unique_id="u-song", duration=95),
        caption="Your song",
    )


def pressed_on_the_song(data: str) -> Update:
    callback = CallbackQuery(
        id=f"cb-song-{data}",
        from_user=User(id=USER_ID, is_bot=False, first_name="Dilnoza"),
        chat_instance="chat-instance",
        data=data,
        message=song_message(),
    )
    return Update(update_id=90_000, callback_query=callback)


async def test_picking_the_language_retires_the_picker_after_the_menu_is_up(
    dispatcher: Dispatcher, bot: Bot, session: RecordingSession
) -> None:
    """The owner's own report: the language picker stayed in the chat with four live buttons."""
    # Arrange
    await send(dispatcher, bot, "/start")
    session.clear()

    # Act
    await press(dispatcher, bot, LanguageCB(slot=LanguageSlot.UI, code=Language.EN).pack())

    # Assert — the menu first, then the picker goes
    menu_at = next(
        position
        for position, call in enumerate(session.calls)
        if isinstance(call, SendMessage) and translate("menu.prompt", Language.EN) in call.text
    )
    assert PRESSED_ON in deleted_ids(session)
    assert menu_at < index_of(session, DeleteMessage, message_id=PRESSED_ON)


async def test_a_typed_answer_retires_the_prompt_it_answered(
    dispatcher: Dispatcher, bot: Bot, session: RecordingSession
) -> None:
    """The prompt asking for typed text goes once the text has arrived and the next screen is up.

    Whichever text step follows the voice question (the note, or the name), the rule is the
    same, so the answer is one that both accept.
    """
    # Arrange — the voice screen is the tracked one, drawn on the pressed message
    await complete_onboarding(dispatcher, bot)
    await tap(dispatcher, bot, "menu.generate", Language.EN)
    await press(dispatcher, bot, OccasionCB(value=Occasion.BIRTHDAY).pack())
    await press(dispatcher, bot, GenreCB(value=Genre.UZBEK_POP).pack())
    await press(dispatcher, bot, VocalGenderCB(value=VoiceGender.FEMALE).pack())
    session.clear()

    # Act
    await send(dispatcher, bot, "Dilnoza")

    # Assert
    assert deleted_ids(session) == [PRESSED_ON]
    assert index_of(session, SendMessage) < index_of(session, DeleteMessage)


async def test_back_to_menu_on_the_song_never_deletes_the_song(
    dispatcher: Dispatcher, bot: Bot, session: RecordingSession
) -> None:
    """🏠 rides on the delivered audio (``post_delivery_keyboard``) — the song must survive it."""
    # Arrange
    await complete_onboarding(dispatcher, bot)
    session.clear()

    # Act
    await dispatcher.feed_update(bot, pressed_on_the_song(NavCB(action=NavAction.TO_MENU).pack()))

    # Assert — a menu went up and nothing touched the song
    assert session.named("SendMessage")
    assert SONG_ID not in deleted_ids(session)
    assert SONG_ID not in stripped_ids(session)
    assert not [call for call in session.named("EditMessageText") if call.message_id == SONG_ID]


async def test_retire_message_refuses_media_outright(bot: Bot, session: RecordingSession) -> None:
    # Act
    await retire_message(song_message().as_(bot))

    # Assert
    assert session.calls == []


async def test_a_refused_delete_falls_back_to_stripping_the_keyboard(
    dispatcher: Dispatcher, bot: Bot, session: RecordingSession
) -> None:
    """Telegram refuses deletes after 48 hours; the buttons must still stop being live."""
    # Arrange
    await send(dispatcher, bot, "/start")
    session.failures["DeleteMessage"] = TelegramBadRequest(
        method=DeleteMessage(chat_id=CHAT_ID, message_id=PRESSED_ON),
        message="Bad Request: message can't be deleted",
    )
    session.clear()

    # Act
    await press(dispatcher, bot, LanguageCB(slot=LanguageSlot.UI, code=Language.EN).pack())

    # Assert
    stripped = [
        call for call in session.named("EditMessageReplyMarkup") if call.message_id == PRESSED_ON
    ]
    assert stripped
    assert stripped[0].reply_markup is None


async def test_the_old_menu_goes_only_after_the_new_one_is_up(
    dispatcher: Dispatcher, bot: Bot, session: RecordingSession, state: FSMContext
) -> None:
    """Deleting the keyboard's carrier first can hide the keyboard in official clients."""
    # Arrange
    await complete_onboarding(dispatcher, bot)
    old_menu = (await state.get_data())[MENU_MESSAGE_ID_KEY]
    session.clear()

    # Act
    await send(dispatcher, bot, "/start")

    # Assert
    new_menu = (await state.get_data())[MENU_MESSAGE_ID_KEY]
    assert new_menu != old_menu
    assert old_menu in deleted_ids(session)
    assert index_of(session, SendMessage) < index_of(session, DeleteMessage, message_id=old_menu)


async def test_a_notice_outlives_its_own_update_and_goes_with_the_next(
    dispatcher: Dispatcher, bot: Bot, session: RecordingSession, state: FSMContext
) -> None:
    """A notice is retired by a LATER update, never the one that said it.

    A handler routinely says a sentence and then redraws the screen it is about; retiring the
    sentence there would delete it the instant it was read.
    """
    # Arrange
    await complete_onboarding(dispatcher, bot)
    session.clear()
    await send(dispatcher, bot, "/help")
    first = (await state.get_data())[NOTICE_MESSAGE_IDS_KEY]
    assert len(first) == 1
    assert deleted_ids(session) == []

    # Act
    await send(dispatcher, bot, "/help")

    # Assert
    assert first[0] in deleted_ids(session)
    assert len((await state.get_data())[NOTICE_MESSAGE_IDS_KEY]) == 1


async def test_the_progress_message_is_never_retired_as_a_screen(
    dispatcher: Dispatcher, bot: Bot, session: RecordingSession, state: FSMContext
) -> None:
    """Confirm is edited INTO the progress frame, so its id can be the tracked screen's."""
    # Arrange
    await complete_onboarding(dispatcher, bot)
    await state.update_data({SCREEN_MESSAGE_ID_KEY: 777, PROGRESS_MESSAGE_ID_KEY: 777})
    session.clear()

    # Act
    await tap(dispatcher, bot, "menu.settings", Language.EN)

    # Assert
    assert 777 not in deleted_ids(session)
    assert 777 not in stripped_ids(session)


async def test_the_layout_ids_survive_the_end_of_a_run(state: FSMContext) -> None:
    """Forgetting the last screen's id at a cancel is how it would become a leftover."""
    # Arrange
    await state.update_data(
        {
            UI_LANGUAGE_KEY: Language.EN.value,
            ONBOARDED_KEY: True,
            SCREEN_MESSAGE_ID_KEY: 5,
            MENU_MESSAGE_ID_KEY: 6,
            NOTICE_MESSAGE_IDS_KEY: [7],
            "draft": {"anything": True},
        }
    )

    # Act
    await clear_keeping_identity(state)

    # Assert
    assert await state.get_data() == {
        UI_LANGUAGE_KEY: Language.EN.value,
        ONBOARDED_KEY: True,
        SCREEN_MESSAGE_ID_KEY: 5,
        MENU_MESSAGE_ID_KEY: 6,
        NOTICE_MESSAGE_IDS_KEY: [7],
    }
