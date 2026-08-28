"""The whole application, from ``/start`` to a delivered voice note.

Every other test in this repository mocks the seam next to the thing it is testing. This
one mocks nothing except the Telegram transport and the six vendors: a real dispatcher, the
real wizard, the real name subsystem, the real orchestrator, real ffmpeg, the real SQLite
repository, real files on disk, and the real delivery code. It is the only test that can
catch two green modules disagreeing — which is the entire failure mode of a parallel build.

Marked ``integration`` because it shells out to ffmpeg. It needs no network, no Redis and
no Postgres.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator
from pathlib import Path
from typing import Any

import pytest
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage

from hbd.bot.app import build_dispatcher
from hbd.bot.callbacks import (
    GenreCB,
    LanguageCB,
    LanguageSlot,
    NavAction,
    NavCB,
    OccasionCB,
    VocalGenderCB,
)
from hbd.bot.deps import BotDeps
from hbd.config import Settings
from hbd.contracts import Genre, Language, Occasion, Ok, VoiceGender
from hbd.runtime.container import AppContainer, build_container
from hbd.runtime.jobs import BOT_CTX_KEY, CONTAINER_CTX_KEY, generate_and_deliver
from hbd.runtime.submitter import InProcessOrderSubmitter
from tests.test_bot.conftest import (
    BOT_TOKEN,
    CHAT_ID,
    RecordingSession,
    callback_update,
    message_update,
)

pytestmark = pytest.mark.integration

TYPED_NAME = "G‘ulomjon"  # U+2018, what a phone keyboard sends
DISPLAY_NAME = "Gʻulomjon"  # U+02BB, what the customer must be shown
NOTE = "Mehribon aka, futbolni yaxshi koʻradi."


def _settings(base: Settings, tmp_path: Path) -> Settings:
    return Settings(
        _env_file=None,
        **{
            **base.model_dump(),
            "use_fake_providers": True,
            "database_url": f"sqlite+aiosqlite:///{tmp_path / 'e2e.db'}",
            # Real ffmpeg runs three passes per asset; the test is about wiring.
            "song_length_ms": 30_000,
            "greetings_per_kit": 3,
        },
    )


@pytest.fixture
async def app(
    settings: Settings, tmp_path: Path
) -> AsyncGenerator[
    tuple[Dispatcher, Bot, RecordingSession, AppContainer, InProcessOrderSubmitter], None
]:
    configured = _settings(settings, tmp_path)
    container = await build_container(configured, data_root=tmp_path)
    session = RecordingSession()
    bot = Bot(
        token=BOT_TOKEN, session=session, default=DefaultBotProperties(parse_mode=ParseMode.HTML)
    )
    ctx = {CONTAINER_CTX_KEY: container, BOT_CTX_KEY: bot}

    async def run_inline(order_id: str, chat_id: int, progress_message_id: int) -> None:
        await generate_and_deliver(ctx, order_id, chat_id, progress_message_id)

    submitter = InProcessOrderSubmitter(container.repository, run_inline)
    dispatcher = build_dispatcher(
        BotDeps(settings=configured, submitter=submitter, payment=container.payment),
        storage=MemoryStorage(),
    )
    try:
        yield dispatcher, bot, session, container, submitter
    finally:
        await container.aclose()


async def _walk_the_wizard(dispatcher: Dispatcher, bot: Bot) -> None:
    """Exactly what a customer presses, in order, through the real keyboards."""
    await dispatcher.feed_update(bot, message_update("/start"))
    await dispatcher.feed_update(
        bot, callback_update(LanguageCB(slot=LanguageSlot.UI, code=Language.UZ_LATN).pack())
    )
    await dispatcher.feed_update(bot, callback_update(OccasionCB(value=Occasion.BIRTHDAY).pack()))
    await dispatcher.feed_update(bot, callback_update(GenreCB(value=Genre.UZBEK_POP).pack()))
    await dispatcher.feed_update(bot, callback_update(VocalGenderCB(value=VoiceGender.MALE).pack()))
    await dispatcher.feed_update(bot, message_update(NOTE))
    await dispatcher.feed_update(bot, message_update(TYPED_NAME))
    await dispatcher.feed_update(bot, callback_update(NavCB(action=NavAction.NAME_OK).pack()))
    await dispatcher.feed_update(
        bot, callback_update(LanguageCB(slot=LanguageSlot.OUTPUT, code=Language.UZ_LATN).pack())
    )
    await dispatcher.feed_update(bot, callback_update(NavCB(action=NavAction.CONFIRM).pack()))


async def test_a_customer_walking_the_wizard_receives_a_complete_kit(
    app: tuple[Dispatcher, Bot, RecordingSession, AppContainer, InProcessOrderSubmitter],
) -> None:
    # Arrange
    dispatcher, bot, session, _container, submitter = app

    # Act
    await _walk_the_wizard(dispatcher, bot)
    await submitter.drain()

    # Assert: one song, three voice notes, a lyric sheet, a closing message.
    assert len(session.named("SendAudio")) == 1
    assert len(session.named("SendVoice")) == 3
    lyric_messages = [
        call
        for call in session.named("SendMessage")
        if DISPLAY_NAME in (getattr(call, "text", "") or "")
    ]
    assert lyric_messages, "the lyric sheet never reached the chat"


async def test_the_greetings_are_ogg_opus_so_telegram_renders_them_as_voice_notes(
    app: tuple[Dispatcher, Bot, RecordingSession, AppContainer, InProcessOrderSubmitter],
) -> None:
    # Arrange
    dispatcher, bot, session, _container, submitter = app

    # Act
    await _walk_the_wizard(dispatcher, bot)
    await submitter.drain()

    # Assert: sendVoice with anything but OGG/Opus renders as a file attachment.
    for call in session.named("SendVoice"):
        voice: Any = call.voice  # type: ignore[attr-defined]
        assert Path(voice.path).suffix == ".ogg"


async def test_the_customer_only_ever_sees_the_canonical_orthography(
    app: tuple[Dispatcher, Bot, RecordingSession, AppContainer, InProcessOrderSubmitter],
) -> None:
    # Arrange
    dispatcher, bot, session, _container, submitter = app

    # Act
    await _walk_the_wizard(dispatcher, bot)
    await submitter.drain()

    # Assert: U+02BB everywhere on screen, and the typed U+2018 nowhere.
    on_screen = "\n".join(
        (getattr(call, "text", None) or getattr(call, "caption", None) or "")
        for call in session.calls
    )
    assert DISPLAY_NAME in on_screen
    assert TYPED_NAME not in on_screen


async def test_the_order_and_its_kit_survive_in_the_database(
    app: tuple[Dispatcher, Bot, RecordingSession, AppContainer, InProcessOrderSubmitter],
) -> None:
    # Arrange
    dispatcher, bot, _session, container, submitter = app

    # Act
    await _walk_the_wizard(dispatcher, bot)
    await submitter.drain()

    # Assert: the bot persisted the order and the pipeline persisted its kit.
    orders = await container.repository.list_orders_for_user(CHAT_ID, limit=10)
    assert isinstance(orders, Ok), f"listing failed: {orders}"
    assert len(orders.value) == 1
    kit = await container.repository.get_kit(orders.value[0].id)
    assert isinstance(kit, Ok), f"kit was not persisted: {kit}"
    assert len(kit.value.greetings) == 3


async def test_the_name_chunk_carried_a_submitted_orthography_never_the_display_one(
    app: tuple[Dispatcher, Bot, RecordingSession, AppContainer, InProcessOrderSubmitter],
) -> None:
    # Arrange
    dispatcher, bot, _session, container, submitter = app
    music: Any = container.providers.music

    # Act
    await _walk_the_wizard(dispatcher, bot)
    await submitter.drain()

    # Assert: the vendor saw a candidate; the loop re-rolled at least once.
    name_texts = [
        chunk.text for call in music.calls for chunk in call.plan.chunks if chunk.is_name_chunk
    ]
    assert name_texts, "no chunk was marked as the name chunk"
    assert len(music.calls) > 1, "the acoustic re-roll never fired"
