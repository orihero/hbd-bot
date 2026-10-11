"""Unit and integration tests for editing delivered songs.

Tests all 5 options of the edit flow:
1. Lyrics: copy text button + typing edited lyrics or keeping existing
2. Music: changing genre and returning to confirm
3. Voice: changing vocal gender and returning to confirm
4. Name: typing new name, confirming, and triggering lyrics regeneration
5. Regenerate all: rerolling lyrics
6. Cancel: returning to main menu
"""

from __future__ import annotations

from uuid import UUID

import pytest
from aiogram import Bot, Dispatcher
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.memory import MemoryStorage

from bayram.bot.app import build_dispatcher
from bayram.bot.callbacks import (
    EditAction,
    EditSongCB,
    GenreCB,
    LanguageCB,
    LanguageSlot,
    NavAction,
    NavCB,
    VocalGenderCB,
    pack_reference,
)
from bayram.bot.deps import BotDeps
from bayram.bot.handlers.common import read_draft
from bayram.bot.i18n import translate
from bayram.bot.states import Wizard
from bayram.config import Settings
from bayram.contracts import (
    Genre,
    Language,
    Order,
    Result,
    VoiceGender,
    err,
    ok,
)
from bayram.errors import NotFoundError
from tests.conftest import make_lyrics, make_order
from tests.test_bot.conftest import (
    USER_ID,
    FakeProfiles,
    RecordingContentWriter,
    RecordingSession,
    RecordingSubmitter,
    buttons,
    callback_update,
    message_update,
)


class FakeOrderReader:
    """An in-memory order reader returning canned orders."""

    def __init__(self, orders: dict[UUID, Order] | None = None) -> None:
        self.orders: dict[UUID, Order] = orders or {}

    async def get_order(self, order_id: UUID) -> Result[Order]:
        order = self.orders.get(order_id)
        if order is not None:
            return ok(order)
        return err(NotFoundError(f"Order {order_id} not found"))


@pytest.fixture
def order_reader() -> FakeOrderReader:
    return FakeOrderReader()


@pytest.fixture
def edit_deps(
    settings: Settings,
    submitter: RecordingSubmitter,
    content: RecordingContentWriter,
    profiles: FakeProfiles,
    order_reader: FakeOrderReader,
) -> BotDeps:
    return BotDeps(
        settings=settings,
        submitter=submitter,
        content=content,
        profiles=profiles,
        order_reader=order_reader,
    )


@pytest.fixture
def edit_dispatcher(edit_deps: BotDeps, storage: MemoryStorage) -> Dispatcher:
    return build_dispatcher(edit_deps, storage=storage)


async def press(dispatcher: Dispatcher, bot: Bot, data: str) -> None:
    await dispatcher.feed_update(bot, callback_update(data))


async def send(dispatcher: Dispatcher, bot: Bot, text: str) -> None:
    await dispatcher.feed_update(bot, message_update(text))


async def test_edit_menu_reconstructs_draft_from_delivered_order(
    edit_dispatcher: Dispatcher,
    bot: Bot,
    session: RecordingSession,
    state: FSMContext,
    order_reader: FakeOrderReader,
) -> None:
    """Tapping ✏️ on a delivered song fetches the order and presents the 5 edit options."""
    order = make_order(
        telegram_user_id=USER_ID,
        brief=make_order().brief.model_copy(
            update={
                "ui_language": Language.UZ_LATN,
                "output_language": Language.UZ_LATN,
                "approved_lyrics": make_lyrics(),
            }
        ),
    )
    order_reader.orders[order.id] = order

    # Customer starts and chooses language
    await send(edit_dispatcher, bot, "/start")
    await press(edit_dispatcher, bot, LanguageCB(slot=LanguageSlot.UI, code=Language.UZ_LATN).pack())

    # Customer taps edit button on delivered song
    await press(
        edit_dispatcher,
        bot,
        EditSongCB(action=EditAction.MENU, ref=pack_reference(order.id)).pack(),
    )

    # Assert edit prompt is displayed in Uzbek Latin
    assert session.last_screen.text == translate("edit.prompt", Language.UZ_LATN)

    # Assert all 5 edit options and Back to menu are present on the keyboard
    markup = session.last_screen.reply_markup
    callback_datas = [data for _, data in buttons(markup)]
    expected_actions = [
        EditAction.LYRICS,
        EditAction.MUSIC,
        EditAction.NAME,
        EditAction.VOICE,
        EditAction.REGENERATE,
    ]
    for action in expected_actions:
        expected_cb = EditSongCB(action=action, ref=pack_reference(order.id)).pack()
        assert expected_cb in callback_datas
    assert NavCB(action=NavAction.TO_MENU).pack() in callback_datas

    # Assert draft is reconstructed
    draft = await read_draft(state)
    assert draft is not None
    assert draft.genre == order.brief.genre
    assert draft.vocal_gender == order.brief.vocal_gender
    assert draft.occasion == order.brief.occasion
    assert draft.recipient == order.brief.recipient
    assert draft.output_language == order.brief.output_language
    assert draft.lyrics == order.brief.approved_lyrics


async def test_edit_lyrics_displays_formatted_lyrics_and_copy_button(
    edit_dispatcher: Dispatcher,
    bot: Bot,
    session: RecordingSession,
    state: FSMContext,
    order_reader: FakeOrderReader,
) -> None:
    """Choosing Lyrics displays lyrics in monospace with CopyTextButton and accepts modifications."""
    lyrics = make_lyrics()
    order = make_order(
        telegram_user_id=USER_ID,
        brief=make_order().brief.model_copy(
            update={
                "ui_language": Language.EN,
                "output_language": Language.EN,
                "approved_lyrics": lyrics,
            }
        ),
    )
    order_reader.orders[order.id] = order

    await send(edit_dispatcher, bot, "/start")
    await press(edit_dispatcher, bot, LanguageCB(slot=LanguageSlot.UI, code=Language.EN).pack())
    await press(
        edit_dispatcher,
        bot,
        EditSongCB(action=EditAction.MENU, ref=pack_reference(order.id)).pack(),
    )

    # Tap Lyrics edit
    await press(
        edit_dispatcher,
        bot,
        EditSongCB(action=EditAction.LYRICS, ref=pack_reference(order.id)).pack(),
    )

    # Assert state is Wizard.lyrics
    assert await state.get_state() == Wizard.lyrics.state

    # Assert screen contains lyrics
    plain_lyrics = lyrics.as_plain_text()
    assert plain_lyrics in session.last_screen.text

    # Assert reply markup contains CopyTextButton
    markup = session.last_screen.reply_markup
    has_copy_button = False
    for row in markup.inline_keyboard:
        for btn in row:
            if btn.copy_text is not None and btn.copy_text.text == plain_lyrics:
                has_copy_button = True
    assert has_copy_button is True, "Keyboard must provide CopyTextButton with the lyric text"

    # User types new lyrics
    new_lyrics_text = "Happy birthday to you!\nWishing you all the best!\nHave a great year ahead!"
    await send(edit_dispatcher, bot, new_lyrics_text)

    # Draft has updated lyrics
    updated_draft = await read_draft(state)
    assert updated_draft is not None
    assert updated_draft.lyrics is not None
    assert "Happy birthday to you!" in updated_draft.lyrics.as_plain_text()


async def test_edit_music_updates_genre_and_returns_to_confirm(
    edit_dispatcher: Dispatcher,
    bot: Bot,
    session: RecordingSession,
    state: FSMContext,
    order_reader: FakeOrderReader,
) -> None:
    """Changing music / genre on complete draft routes directly to Confirm screen."""
    order = make_order(
        telegram_user_id=USER_ID,
        brief=make_order().brief.model_copy(
            update={
                "genre": Genre.UZBEK_POP,
                "output_language": Language.EN,
                "approved_lyrics": make_lyrics(),
            }
        ),
    )
    order_reader.orders[order.id] = order

    await send(edit_dispatcher, bot, "/start")
    await press(edit_dispatcher, bot, LanguageCB(slot=LanguageSlot.UI, code=Language.EN).pack())
    await press(
        edit_dispatcher,
        bot,
        EditSongCB(action=EditAction.MENU, ref=pack_reference(order.id)).pack(),
    )

    # Tap Music edit
    await press(
        edit_dispatcher,
        bot,
        EditSongCB(action=EditAction.MUSIC, ref=pack_reference(order.id)).pack(),
    )

    # Select alternative genre
    new_genre = Genre.POP
    await press(edit_dispatcher, bot, GenreCB(value=new_genre).pack())

    # Assert updated genre is reflected in draft
    draft = await read_draft(state)
    assert draft is not None
    assert draft.genre == new_genre

    # Assert confirm screen is presented
    confirm_texts = [text for text, _ in buttons(session.last_screen.reply_markup)]
    assert translate("button.confirm", Language.EN) in confirm_texts


async def test_edit_voice_updates_vocal_gender_and_returns_to_confirm(
    edit_dispatcher: Dispatcher,
    bot: Bot,
    session: RecordingSession,
    state: FSMContext,
    order_reader: FakeOrderReader,
) -> None:
    """Changing vocal gender on complete draft routes directly to Confirm screen."""
    order = make_order(
        telegram_user_id=USER_ID,
        brief=make_order().brief.model_copy(
            update={
                "vocal_gender": VoiceGender.FEMALE,
                "output_language": Language.EN,
                "approved_lyrics": make_lyrics(),
            }
        ),
    )
    order_reader.orders[order.id] = order

    await send(edit_dispatcher, bot, "/start")
    await press(edit_dispatcher, bot, LanguageCB(slot=LanguageSlot.UI, code=Language.EN).pack())
    await press(
        edit_dispatcher,
        bot,
        EditSongCB(action=EditAction.MENU, ref=pack_reference(order.id)).pack(),
    )

    # Tap Voice edit
    await press(
        edit_dispatcher,
        bot,
        EditSongCB(action=EditAction.VOICE, ref=pack_reference(order.id)).pack(),
    )

    # Select Male voice
    new_voice = VoiceGender.MALE
    await press(edit_dispatcher, bot, VocalGenderCB(value=new_voice).pack())

    # Assert updated voice is reflected in draft
    draft = await read_draft(state)
    assert draft is not None
    assert draft.vocal_gender == new_voice

    # Assert confirm screen is presented
    confirm_texts = [text for text, _ in buttons(session.last_screen.reply_markup)]
    assert translate("button.confirm", Language.EN) in confirm_texts


async def test_edit_name_prompts_new_name_and_regenerates_lyrics(
    edit_dispatcher: Dispatcher,
    bot: Bot,
    session: RecordingSession,
    state: FSMContext,
    order_reader: FakeOrderReader,
) -> None:
    """Changing recipient name confirms candidate and regenerates lyrics for that name."""
    order = make_order(
        telegram_user_id=USER_ID,
        brief=make_order().brief.model_copy(
            update={
                "output_language": Language.UZ_LATN,
                "approved_lyrics": make_lyrics(name_display="Eshmat"),
            }
        ),
    )
    order_reader.orders[order.id] = order

    await send(edit_dispatcher, bot, "/start")
    await press(edit_dispatcher, bot, LanguageCB(slot=LanguageSlot.UI, code=Language.UZ_LATN).pack())
    await press(
        edit_dispatcher,
        bot,
        EditSongCB(action=EditAction.MENU, ref=pack_reference(order.id)).pack(),
    )

    # Tap Name edit
    await press(
        edit_dispatcher,
        bot,
        EditSongCB(action=EditAction.NAME, ref=pack_reference(order.id)).pack(),
    )

    # Send new name
    await send(edit_dispatcher, bot, "Toshmat")

    # Confirm candidate name
    await press(edit_dispatcher, bot, NavCB(action=NavAction.NAME_OK).pack())

    # Assert new name was set and lyrics step was entered with fresh lyrics
    draft = await read_draft(state)
    assert draft is not None
    assert draft.recipient is not None
    assert draft.recipient.display == "Toshmat"
    assert draft.lyrics is not None
    assert "Toshmat" in draft.lyrics.name_display


async def test_edit_regenerate_all_rerolls_lyrics(
    edit_dispatcher: Dispatcher,
    bot: Bot,
    session: RecordingSession,
    state: FSMContext,
    order_reader: FakeOrderReader,
    content: RecordingContentWriter,
) -> None:
    """Regenerate all wipes lyrics and invokes content writer for fresh lyrics."""
    order = make_order(
        telegram_user_id=USER_ID,
        brief=make_order().brief.model_copy(
            update={
                "output_language": Language.EN,
                "approved_lyrics": make_lyrics(),
            }
        ),
    )
    order_reader.orders[order.id] = order

    await send(edit_dispatcher, bot, "/start")
    await press(edit_dispatcher, bot, LanguageCB(slot=LanguageSlot.UI, code=Language.EN).pack())
    await press(
        edit_dispatcher,
        bot,
        EditSongCB(action=EditAction.MENU, ref=pack_reference(order.id)).pack(),
    )

    content_calls_before = content.calls
    # Tap Regenerate all
    await press(
        edit_dispatcher,
        bot,
        EditSongCB(action=EditAction.REGENERATE, ref=pack_reference(order.id)).pack(),
    )

    # Assert content writer was called for fresh take
    assert content.calls > content_calls_before
    draft = await read_draft(state)
    assert draft is not None
    assert draft.lyrics is not None


async def test_edit_cancel_returns_to_main_menu(
    edit_dispatcher: Dispatcher,
    bot: Bot,
    session: RecordingSession,
    order_reader: FakeOrderReader,
) -> None:
    """Tapping cancel returns customer to the main menu screen."""
    order = make_order(telegram_user_id=USER_ID)
    order_reader.orders[order.id] = order

    await send(edit_dispatcher, bot, "/start")
    await press(edit_dispatcher, bot, LanguageCB(slot=LanguageSlot.UI, code=Language.EN).pack())
    await press(
        edit_dispatcher,
        bot,
        EditSongCB(action=EditAction.MENU, ref=pack_reference(order.id)).pack(),
    )

    # Tap Back to menu / Cancel
    await press(
        edit_dispatcher,
        bot,
        EditSongCB(action=EditAction.CANCEL, ref=pack_reference(order.id)).pack(),
    )

    # Assert main menu prompt is shown
    assert translate("menu.prompt", Language.EN) in session.last_screen.text
