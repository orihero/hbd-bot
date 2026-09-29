"""✨ Create, the image compose and the post-freeze buttons (IMAGE_VIDEO_SPEC §2.2–§2.6, M2.5).

Driven through the real router tree with a real ``SqlMediaDesk`` over in-memory SQLite and an
ARQ-shaped queue that records what the bot enqueued — the worker is not run here; the stage
chain has its own suite. The M2.5 acceptance list, each a test below:

* an album of ten → one tray showing the final count, deduped, capped;
* an album to the stray-message fallback → one reply;
* the old 🎵 label still routes;
* an account off the allowlist sees no Image;
* the re-push fires once, not after every song;
* ✏️ Edit after a quote → a new row, screened before any quote;
* a second ✅ Done with a pre-pay row open cancels the old one;
* with a paid row open → ``media.open_request``;
* 🎁 re-checks the allowlist at press time;
* 💳 hidden on the stub, 🎁 hidden on a live-paid rail — the worker draws the quote, so
  ``tests/test_runtime/test_media_stages.py`` holds both halves;
* the locale contract covers ``button.media.*`` (``test_locale_contract.py`` walks the new
  keyboards through ``test_keyboards.every_keyboard``).
"""

from __future__ import annotations

import itertools
from collections.abc import AsyncIterator, Awaitable, Callable
from datetime import datetime, timedelta
from typing import Any, Final
from uuid import UUID

import pytest
import sqlalchemy as sa
from aiogram import Bot, Dispatcher
from aiogram.exceptions import TelegramBadRequest
from aiogram.fsm.storage.base import StorageKey
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.methods import DeleteMessage, EditMessageText, SendMessage
from aiogram.types import Chat, InlineKeyboardMarkup, Message, PhotoSize, Update, User
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from bayram.bot.app import build_dispatcher
from bayram.bot.callbacks import (
    AspectPick,
    CreatePick,
    MediaAction,
    MediaCB,
    OccasionCB,
    pack_job_ref,
)
from bayram.bot.deps import BotDeps
from bayram.bot.i18n import translate
from bayram.bot.keyboards import MENU_VERSION
from bayram.bot.media_draft import load_media_draft
from bayram.bot.menu_version import menu_version_key
from bayram.bot.states import ImageOrder
from bayram.config import Settings
from bayram.contracts import Language, Occasion, Result, ok
from bayram.db.engine import create_session_factory
from bayram.db.enums import MediaJobState, MediaPaidVia
from bayram.db.media import load_job, transition
from bayram.db.models import Base
from bayram.db.models.media_input import MediaInputRow
from bayram.db.models.media_job import MediaJobRow
from bayram.db.models.media_purchase import MediaPurchaseRow
from bayram.errors import StorageError
from bayram.media.desk import JobView, SqlMediaDesk
from bayram.media.overrides import GPU_RESERVED_KEY
from bayram.media.payment import MediaPayLink
from bayram.media.stages import MEDIA_CLEANUP_JOB, MEDIA_SCREEN_JOB, MEDIA_START_JOB
from bayram.moderation.lexicon import PROMPT_MAX_WORDS
from bayram.moderation.strikes import MemoryStrikeStore, SuspensionReason
from bayram.terms import InMemoryTermsCache, TermsGate, TermsVersions
from tests.test_bot.conftest import (
    BOT_ID,
    CHAT_ID,
    FIXED_MOMENT,
    USER_ID,
    FakeProfiles,
    RecordingContentWriter,
    RecordingSession,
    RecordingSubmitter,
    buttons,
    callback_update,
    data_with_prefix,
    last_reply_keyboard,
    make_callback,
    reply_buttons,
)
from tests.test_bot.test_terms_gate import FakeTermsLedger
from tests.test_bot.test_wizard_flow import complete_onboarding, send, tap
from tests.test_runtime.media_fakes import ArqLikeQueue, MemoryKV

PROMPT: Final[str] = "a lantern-lit courtyard in Samarkand at dusk"
#: The message the picker is drawn on and every tray button is pressed from: ``make_callback``'s
#: default message id. The tray is edited over the picker, so it is the tray's id too.
TRAY: Final[int] = 20


# ---------------------------------------------------------------------------
# Harness
# ---------------------------------------------------------------------------
@pytest.fixture
async def sessions() -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    yield create_session_factory(engine)
    await engine.dispose()


def media_on(settings: Settings, **update: Any) -> Settings:
    """Image offered to the beta allowlist on the stub rail — the M2 shape (§2.5, O9)."""
    values: dict[str, Any] = {
        "is_image_offered": True,
        "media_beta_enabled": True,
        "media_beta_allowlist": (USER_ID,),
    }
    values.update(update)
    return settings.model_copy(update=values)


class Rig:
    """One chat: a dispatcher, its desk, the queue it enqueues to and the Redis it reads."""

    def __init__(
        self,
        settings: Settings,
        sessions: async_sessionmaker[AsyncSession],
        *,
        storage: MemoryStorage | None = None,
        kv: MemoryKV | None = None,
        queue: ArqLikeQueue | None = None,
        profiles: FakeProfiles | None = None,
        media_charge: Callable[[JobView], Awaitable[Result[MediaPayLink]]] | None = None,
        strikes: MemoryStrikeStore | None = None,
        terms: TermsGate | None = None,
    ) -> None:
        self.settings = settings
        self.strikes = strikes if strikes is not None else MemoryStrikeStore()
        self.sessions = sessions
        self.queue = queue if queue is not None else ArqLikeQueue()
        self.kv = kv if kv is not None else MemoryKV()
        self.storage = storage if storage is not None else MemoryStorage()
        self.profiles = profiles if profiles is not None else FakeProfiles()
        clock: Callable[[], datetime] = lambda: FIXED_MOMENT  # noqa: E731
        self.deps = BotDeps(
            settings=settings,
            submitter=RecordingSubmitter(),
            content=RecordingContentWriter(),
            clock=clock,
            profiles=self.profiles,
            media=SqlMediaDesk(sessions, queue=self.queue, settings=settings, clock=clock),
            media_kv=self.kv,
            media_charge=media_charge,
            media_strikes=self.strikes,
            terms=terms,
        )
        self.dispatcher: Dispatcher = build_dispatcher(self.deps, storage=self.storage)

    def again(self, settings: Settings) -> Rig:
        """The same chat, database, queue and Redis behind a dispatcher with other settings."""
        return Rig(
            settings,
            self.sessions,
            storage=self.storage,
            kv=self.kv,
            queue=self.queue,
            profiles=self.profiles,
            strikes=self.strikes,
        )

    async def fsm(self) -> dict[str, Any]:
        return await self.storage.get_data(
            StorageKey(bot_id=BOT_ID, chat_id=CHAT_ID, user_id=USER_ID)
        )

    async def fsm_state(self) -> str | None:
        return await self.storage.get_state(
            StorageKey(bot_id=BOT_ID, chat_id=CHAT_ID, user_id=USER_ID)
        )

    async def jobs(self) -> list[MediaJobRow]:
        async with self.sessions() as session:
            return list(
                (await session.scalars(sa.select(MediaJobRow).order_by(MediaJobRow.created_at)))
                .unique()
                .all()
            )

    async def move(self, job_id: UUID, to: MediaJobState, **values: Any) -> None:
        async with self.sessions.begin() as session:
            job = await load_job(session, job_id)
            assert job is not None
            assert await transition(
                session, job_id, expected=(job.state,), to=to, now=FIXED_MOMENT, values=values
            )


_photo_message_id = 500


def photo_update(unique: str, *, group: str | None = None, caption: str | None = None) -> Update:
    """A photo as Telegram sends one: an ascending size ladder, one item of an album or alone."""
    global _photo_message_id
    _photo_message_id += 1
    ladder = [
        PhotoSize(file_id=f"s-{unique}", file_unique_id=f"s-{unique}", width=90, height=160),
        PhotoSize(file_id=f"f-{unique}", file_unique_id=unique, width=720, height=1280),
    ]
    return Update(
        update_id=_photo_message_id,
        message=Message(
            message_id=_photo_message_id,
            date=FIXED_MOMENT,
            chat=Chat(id=CHAT_ID, type="private"),
            from_user=User(id=USER_ID, is_bot=False, first_name="Dilnoza"),
            photo=ladder,
            media_group_id=group,
            caption=caption,
        ),
    )


async def live_tray(dispatcher: Dispatcher) -> int:
    """The message the compose's tray is on now. A photo or a prompt MOVES the tray under
    itself (§2.3.2), so after one the tray is a message the bot sent, not :data:`TRAY`."""
    data = await dispatcher.storage.get_data(
        StorageKey(bot_id=BOT_ID, chat_id=CHAT_ID, user_id=USER_ID)
    )
    draft = load_media_draft(data)
    if draft is None or draft.tray_message_id is None:
        return TRAY
    return draft.tray_message_id


async def press(dispatcher: Dispatcher, bot: Bot, data: str) -> None:
    """A press on the LIVE tray — where a customer's finger is — or on :data:`TRAY` when no
    compose is open. The wizard's ``press`` always presses message 20."""
    message_id = await live_tray(dispatcher)
    await dispatcher.feed_update(
        bot,
        Update(
            update_id=next(_press_ids),
            callback_query=make_callback(data, message_id=message_id),
        ),
    )


_press_ids = itertools.count(900_000)


def tray_edits(session: RecordingSession, message_id: int | None = None) -> list[str]:
    """Every screen drawn OVER a message — the tray's, since a photo moves it (§2.3.2) — or
    over ``message_id`` only."""
    return [
        call.text
        for call in session.named("EditMessageText")
        if isinstance(call, EditMessageText)
        and call.text is not None
        and (message_id is None or call.message_id == message_id)
    ]


def deleted_ids(session: RecordingSession) -> list[int]:
    return [
        call.message_id
        for call in session.named("DeleteMessage")
        if isinstance(call, DeleteMessage)
    ]


def sent_texts(session: RecordingSession) -> list[str]:
    return [call.text for call in session.named("SendMessage") if isinstance(call, SendMessage)]


def med(action: MediaAction, *, job: UUID | None = None, arg: str = "") -> str:
    return MediaCB(action=action, job="" if job is None else pack_job_ref(job), arg=arg).pack()


async def open_image_compose(rig: Rig, bot: Bot) -> None:
    await complete_onboarding(rig.dispatcher, bot)
    await tap(rig.dispatcher, bot, "menu.generate", Language.EN)
    await press(rig.dispatcher, bot, med(MediaAction.PICK, arg=CreatePick.IMAGE))


async def freeze(rig: Rig, bot: Bot, *, prompt: str = PROMPT) -> None:
    await send(rig.dispatcher, bot, prompt)
    await press(rig.dispatcher, bot, med(MediaAction.DONE))
    await press(rig.dispatcher, bot, med(MediaAction.ASPECT, arg=AspectPick.SQUARE))


async def new_compose(rig: Rig, bot: Bot) -> None:
    """✨ → 🖼 again, from an onboarded chat."""
    await tap(rig.dispatcher, bot, "menu.generate", Language.EN)
    await press(rig.dispatcher, bot, med(MediaAction.PICK, arg=CreatePick.IMAGE))


# ---------------------------------------------------------------------------
# ✨ and the picker (§2.2)
# ---------------------------------------------------------------------------
async def test_create_opens_the_picker_with_image_for_the_allowlist(
    settings: Settings,
    sessions: async_sessionmaker[AsyncSession],
    bot: Bot,
    session: RecordingSession,
) -> None:
    rig = Rig(media_on(settings), sessions)
    await complete_onboarding(rig.dispatcher, bot)

    await tap(rig.dispatcher, bot, "menu.generate", Language.EN)

    labels = [text for text, _ in buttons(session.last_screen.reply_markup)]
    assert session.last_screen.text == translate("create.pick", Language.EN)
    assert labels == [
        translate("button.create.song", Language.EN),
        translate("button.create.image", Language.EN),
    ]


async def test_an_account_off_the_allowlist_sees_no_image_and_goes_straight_to_the_song(
    settings: Settings,
    sessions: async_sessionmaker[AsyncSession],
    bot: Bot,
    session: RecordingSession,
) -> None:
    rig = Rig(media_on(settings, media_beta_allowlist=(USER_ID + 1,)), sessions)
    await complete_onboarding(rig.dispatcher, bot)

    await tap(rig.dispatcher, bot, "menu.generate", Language.EN)

    # The occasion question, with no picker in between.
    data_with_prefix(session.last_screen.reply_markup, OccasionCB.__prefix__)
    assert translate("create.pick", Language.EN) not in sent_texts(session)
    # And a hand-made 🖼 press is refused at the press, not trusted.
    await press(rig.dispatcher, bot, med(MediaAction.PICK, arg=CreatePick.IMAGE))
    assert session.last_named("AnswerCallbackQuery").text == translate("media.stale", Language.EN)
    assert await rig.fsm_state() != ImageOrder.compose.state


async def test_the_old_song_label_still_routes(
    settings: Settings,
    sessions: async_sessionmaker[AsyncSession],
    bot: Bot,
    session: RecordingSession,
) -> None:
    rig = Rig(media_on(settings), sessions)
    await complete_onboarding(rig.dispatcher, bot)

    await tap(rig.dispatcher, bot, "menu.generate_legacy", Language.RU)

    assert session.last_screen.text == translate("create.pick", Language.EN)


async def test_the_menu_draws_create_and_not_the_legacy_label(
    settings: Settings,
    sessions: async_sessionmaker[AsyncSession],
    bot: Bot,
    session: RecordingSession,
) -> None:
    rig = Rig(media_on(settings), sessions)
    await complete_onboarding(rig.dispatcher, bot)

    rows = reply_buttons(last_reply_keyboard(session))
    labels = [label for row in rows for label in row]
    assert translate("menu.generate", Language.EN) == "✨ Create"
    assert "✨ Create" in labels
    assert translate("menu.generate_legacy", Language.EN) not in labels
    assert len(labels) == 4


# ---------------------------------------------------------------------------
# The tray and albums (§2.3.2)
# ---------------------------------------------------------------------------
async def test_an_album_of_ten_ends_as_one_tray_with_the_final_count_deduped_and_capped(
    settings: Settings,
    sessions: async_sessionmaker[AsyncSession],
    bot: Bot,
    session: RecordingSession,
) -> None:
    rig = Rig(media_on(settings), sessions)
    await open_image_compose(rig, bot)
    session.clear()

    # Ten items, two of them the same photo again; the cap is four.
    for unique in ("a", "b", "a", "c", "b", "d", "e", "f", "g", "h"):
        await rig.dispatcher.feed_update(bot, photo_update(unique, group="album-1"))

    draft = load_media_draft(await rig.fsm())
    assert draft is not None
    assert [ref.file_unique_id for ref in draft.refs] == ["a", "b", "c", "d"]
    # The largest size of each was taken.
    assert draft.refs[0].file_id == "f-a"
    # The album's first photo moved the tray under the album: one new tray, the old deleted.
    sent = sent_texts(session)
    assert len(sent) == 2, "one tray for the album and one cap notice, nothing else"
    assert sent[0].startswith(translate("media.tray.got_photo", Language.EN, n=1, max=4))
    assert sent[1] == translate("media.tray.cap_reached", Language.EN, max=4)
    assert deleted_ids(session) == [TRAY]
    # Its later accepted photos edited THAT tray; none per duplicate or refusal.
    edits = tray_edits(session, draft.tray_message_id)
    assert len(edits) == 3
    assert "Photos: 4/4" in edits[-1]
    assert translate("media.tray.got_photo", Language.EN, n=4, max=4) in edits[-1]
    assert tray_edits(session) == edits


async def test_a_caption_sets_the_prompt_and_text_replaces_it(
    settings: Settings,
    sessions: async_sessionmaker[AsyncSession],
    bot: Bot,
    session: RecordingSession,
) -> None:
    rig = Rig(media_on(settings), sessions)
    await open_image_compose(rig, bot)

    await rig.dispatcher.feed_update(bot, photo_update("a", caption="a cat in a garden"))
    first = load_media_draft(await rig.fsm())
    await send(rig.dispatcher, bot, PROMPT)
    second = load_media_draft(await rig.fsm())

    assert first is not None and first.prompt == "a cat in a garden"
    assert second is not None and second.prompt == PROMPT
    assert "«a lantern-lit courtyard" in sent_texts(session)[-1]


# ---------------------------------------------------------------------------
# The tray answers under what was sent (§2.3.2, changed 2026-09-26)
# ---------------------------------------------------------------------------
async def test_a_photo_is_answered_by_a_new_tray_under_it_that_asks_for_the_prompt(
    settings: Settings,
    sessions: async_sessionmaker[AsyncSession],
    bot: Bot,
    session: RecordingSession,
) -> None:
    rig = Rig(media_on(settings), sessions)
    await open_image_compose(rig, bot)
    session.clear()

    await rig.dispatcher.feed_update(bot, photo_update("a"))

    (answer,) = session.named("SendMessage")
    assert isinstance(answer, SendMessage)
    text = answer.text
    assert text.startswith(translate("media.tray.got_photo", Language.EN, n=1, max=4))
    assert "Photos: 1/4" in text
    assert text.endswith(translate("media.tray.ask_prompt.image", Language.EN))
    # The same keyboard as the tray, now with 🗑 since there is a photo.
    assert isinstance(answer.reply_markup, InlineKeyboardMarkup)
    labels = [label for label, _ in buttons(answer.reply_markup)]
    assert translate("button.media.done", Language.EN) in labels
    assert translate("button.media.clear_photos", Language.EN) in labels
    # Exactly one live tray: the old one is deleted, nothing is edited.
    assert deleted_ids(session) == [TRAY]
    assert tray_edits(session) == []
    assert await live_tray(rig.dispatcher) != TRAY


async def test_a_photo_with_the_prompt_in_offers_more_photos_or_done(
    settings: Settings,
    sessions: async_sessionmaker[AsyncSession],
    bot: Bot,
    session: RecordingSession,
) -> None:
    rig = Rig(media_on(settings, media_max_reference_images=2), sessions)
    await open_image_compose(rig, bot)
    await send(rig.dispatcher, bot, PROMPT)

    await rig.dispatcher.feed_update(bot, photo_update("a"))
    under_cap = sent_texts(session)[-1]
    await rig.dispatcher.feed_update(bot, photo_update("b"))
    at_cap = sent_texts(session)[-1]

    assert under_cap.endswith(translate("media.tray.more_or_done", Language.EN))
    assert translate("media.tray.ask_prompt.image", Language.EN) not in under_cap
    # At the cap there is no room left: only ✅ Done is offered.
    assert at_cap.startswith(translate("media.tray.got_photo", Language.EN, n=2, max=2))
    assert at_cap.endswith(translate("media.tray.press_done", Language.EN))


async def test_an_album_of_three_draws_one_new_tray_and_edits_it(
    settings: Settings,
    sessions: async_sessionmaker[AsyncSession],
    bot: Bot,
    session: RecordingSession,
) -> None:
    rig = Rig(media_on(settings), sessions)
    await open_image_compose(rig, bot)
    session.clear()

    for unique in ("a", "b", "c"):
        await rig.dispatcher.feed_update(bot, photo_update(unique, group="album-3"))

    sends = session.named("SendMessage")
    assert len(sends) == 1, "one reply per album"
    tray = await live_tray(rig.dispatcher)
    edits = tray_edits(session)
    assert len(edits) == 2
    assert tray_edits(session, tray) == edits, "the later items edit the tray the album drew"
    assert translate("media.tray.got_photo", Language.EN, n=3, max=4) in edits[-1]
    assert "Photos: 3/4" in edits[-1]
    assert deleted_ids(session) == [TRAY]
    draft = load_media_draft(await rig.fsm())
    assert draft is not None and draft.tray_media_group_id == "album-3"

    # A second album is a new answer: it moves the tray again, under itself.
    session.clear()
    await rig.dispatcher.feed_update(bot, photo_update("d", group="album-4"))
    assert len(session.named("SendMessage")) == 1
    assert deleted_ids(session) == [tray]


async def test_a_duplicate_photo_draws_nothing(
    settings: Settings,
    sessions: async_sessionmaker[AsyncSession],
    bot: Bot,
    session: RecordingSession,
) -> None:
    rig = Rig(media_on(settings), sessions)
    await open_image_compose(rig, bot)
    await rig.dispatcher.feed_update(bot, photo_update("a"))
    session.clear()

    await rig.dispatcher.feed_update(bot, photo_update("a"))

    assert not session.named("SendMessage")
    assert not session.named("EditMessageText")
    assert not session.named("DeleteMessage")


async def test_the_prompt_is_confirmed_by_a_new_tray_under_it(
    settings: Settings,
    sessions: async_sessionmaker[AsyncSession],
    bot: Bot,
    session: RecordingSession,
) -> None:
    rig = Rig(media_on(settings), sessions)
    await open_image_compose(rig, bot)
    await rig.dispatcher.feed_update(bot, photo_update("a"))
    photo_tray = await live_tray(rig.dispatcher)
    session.clear()

    await send(rig.dispatcher, bot, PROMPT)

    (text,) = sent_texts(session)
    assert text.startswith(translate("media.tray.got_prompt", Language.EN))
    assert "«a lantern-lit courtyard" in text
    assert text.endswith(translate("media.tray.more_or_done", Language.EN))
    assert deleted_ids(session) == [photo_tray]
    assert await live_tray(rig.dispatcher) not in (TRAY, photo_tray)


async def test_an_old_tray_that_cannot_be_deleted_is_left_and_the_answer_stands(
    settings: Settings,
    sessions: async_sessionmaker[AsyncSession],
    bot: Bot,
    session: RecordingSession,
) -> None:
    rig = Rig(media_on(settings), sessions)
    await open_image_compose(rig, bot)
    session.failures_once["DeleteMessage"] = TelegramBadRequest(
        method=DeleteMessage(chat_id=CHAT_ID, message_id=TRAY),
        message="Bad Request: message to delete not found",
    )

    await rig.dispatcher.feed_update(bot, photo_update("a"))

    draft = load_media_draft(await rig.fsm())
    assert draft is not None and len(draft.refs) == 1
    assert draft.tray_message_id is not None and draft.tray_message_id != TRAY
    assert sent_texts(session)[-1].startswith(
        translate("media.tray.got_photo", Language.EN, n=1, max=4)
    )
    # The left-over tray's buttons are stale; the new one's work.
    await rig.dispatcher.feed_update(
        bot,
        Update(
            update_id=next(_press_ids),
            callback_query=make_callback(med(MediaAction.CLEAR), message_id=TRAY),
        ),
    )
    assert session.last_named("AnswerCallbackQuery").text == translate("media.stale", Language.EN)


async def test_a_button_on_the_moved_tray_still_edits_it_in_place(
    settings: Settings,
    sessions: async_sessionmaker[AsyncSession],
    bot: Bot,
    session: RecordingSession,
) -> None:
    rig = Rig(media_on(settings), sessions)
    await open_image_compose(rig, bot)
    await rig.dispatcher.feed_update(bot, photo_update("a"))
    tray = await live_tray(rig.dispatcher)
    session.clear()

    await press(rig.dispatcher, bot, med(MediaAction.CLEAR))

    assert not session.named("SendMessage")
    assert not session.named("DeleteMessage")
    assert "Photos: 0/4" in tray_edits(session, tray)[-1]
    assert await live_tray(rig.dispatcher) == tray


async def test_done_without_a_prompt_is_an_alert_and_moves_nothing(
    settings: Settings,
    sessions: async_sessionmaker[AsyncSession],
    bot: Bot,
    session: RecordingSession,
) -> None:
    rig = Rig(media_on(settings), sessions)
    await open_image_compose(rig, bot)

    await press(rig.dispatcher, bot, med(MediaAction.DONE))

    answer = session.last_named("AnswerCallbackQuery")
    assert answer.text == translate("media.need_prompt", Language.EN)
    assert answer.show_alert is True
    assert await rig.fsm_state() == ImageOrder.compose.state


async def test_done_while_the_gpu_is_reserved_is_busy_and_freezes_nothing(
    settings: Settings,
    sessions: async_sessionmaker[AsyncSession],
    bot: Bot,
    session: RecordingSession,
) -> None:
    # §4.5, O11: the operator's window refuses at Done, not after a row was frozen.
    rig = Rig(media_on(settings), sessions)
    await open_image_compose(rig, bot)
    await send(rig.dispatcher, bot, PROMPT)
    rig.kv.values[GPU_RESERVED_KEY] = (FIXED_MOMENT + timedelta(hours=1)).isoformat()

    await press(rig.dispatcher, bot, med(MediaAction.DONE))

    answer = session.last_named("AnswerCallbackQuery")
    assert answer.text == translate("media.busy", Language.EN)
    assert answer.show_alert is True
    assert await rig.fsm_state() == ImageOrder.compose.state
    assert await rig.jobs() == []

    # The window closes: the same tray goes on to the shape screen.
    rig.kv.values[GPU_RESERVED_KEY] = (FIXED_MOMENT - timedelta(minutes=1)).isoformat()
    await press(rig.dispatcher, bot, med(MediaAction.DONE))
    assert await rig.fsm_state() == ImageOrder.aspect.state


async def test_a_suspended_accounts_done_freezes_no_row(
    settings: Settings,
    sessions: async_sessionmaker[AsyncSession],
    bot: Bot,
    session: RecordingSession,
) -> None:
    # §6.4 L0 "strike check" in the handler (M3.R): nothing is frozen, nothing downloaded.
    rig = Rig(media_on(settings), sessions)
    await open_image_compose(rig, bot)
    await send(rig.dispatcher, bot, PROMPT)
    await rig.dispatcher.feed_update(bot, photo_update("a"))
    await rig.strikes.suspend(USER_ID, reason=SuspensionReason.CSAM, now=FIXED_MOMENT)

    await press(rig.dispatcher, bot, med(MediaAction.DONE))

    assert tray_edits(session)[-1] == translate("media.refused.suspended", Language.EN)
    assert await rig.jobs() == []
    assert not rig.queue.pending
    assert await rig.fsm_state() != ImageOrder.aspect.state


async def test_a_suspension_between_done_and_the_shape_freezes_no_row(
    settings: Settings,
    sessions: async_sessionmaker[AsyncSession],
    bot: Bot,
    session: RecordingSession,
) -> None:
    rig = Rig(media_on(settings), sessions)
    await open_image_compose(rig, bot)
    await send(rig.dispatcher, bot, PROMPT)
    await press(rig.dispatcher, bot, med(MediaAction.DONE))
    await rig.strikes.suspend(USER_ID, reason=SuspensionReason.STRIKES, now=FIXED_MOMENT)

    await press(rig.dispatcher, bot, med(MediaAction.ASPECT, arg=AspectPick.SQUARE))

    assert await rig.jobs() == []
    assert not rig.queue.pending


async def test_a_prompt_over_the_word_cap_is_not_taken(
    settings: Settings,
    sessions: async_sessionmaker[AsyncSession],
    bot: Bot,
    session: RecordingSession,
) -> None:
    # Under 800 characters but over PROMPT_MAX_WORDS: the worker's L0 would refuse it, so
    # the tray does not accept it in the first place (M3.R).
    rig = Rig(media_on(settings), sessions)
    await open_image_compose(rig, bot)
    many_words = " ".join(["a b"] * (PROMPT_MAX_WORDS // 2 + 1))
    assert len(many_words) <= 800

    await send(rig.dispatcher, bot, many_words)

    assert sent_texts(session)[-1].startswith(
        translate("media.prompt.invalid", Language.EN, min=3, max=800)[:20]
    )
    draft = load_media_draft(await rig.fsm())
    assert draft is not None and draft.prompt is None


async def test_an_album_to_the_stray_message_fallback_draws_one_reply(
    settings: Settings,
    sessions: async_sessionmaker[AsyncSession],
    bot: Bot,
    session: RecordingSession,
) -> None:
    rig = Rig(media_on(settings), sessions)
    await complete_onboarding(rig.dispatcher, bot)
    session.clear()

    for unique in ("a", "b", "c", "d", "e"):
        await rig.dispatcher.feed_update(bot, photo_update(unique, group="stray-album"))

    assert len(session.named("SendMessage")) == 1


async def test_photos_after_done_draw_one_closed_notice_per_album(
    settings: Settings,
    sessions: async_sessionmaker[AsyncSession],
    bot: Bot,
    session: RecordingSession,
) -> None:
    rig = Rig(media_on(settings), sessions)
    await open_image_compose(rig, bot)
    await freeze(rig, bot)
    session.clear()

    for unique in ("x", "y", "z"):
        await rig.dispatcher.feed_update(bot, photo_update(unique, group="late-album"))

    assert sent_texts(session) == [translate("media.compose.closed", Language.EN)]


# ---------------------------------------------------------------------------
# Freezing (§2.3.1)
# ---------------------------------------------------------------------------
async def test_the_aspect_pick_freezes_a_screening_row_and_enqueues_its_screen(
    settings: Settings,
    sessions: async_sessionmaker[AsyncSession],
    bot: Bot,
    session: RecordingSession,
) -> None:
    rig = Rig(media_on(settings), sessions)
    await open_image_compose(rig, bot)
    await rig.dispatcher.feed_update(bot, photo_update("a"))
    await rig.dispatcher.feed_update(bot, photo_update("b"))

    await freeze(rig, bot)

    (job,) = await rig.jobs()
    assert job.state is MediaJobState.SCREENING
    assert job.prompt == PROMPT
    assert job.aspect.value == "1:1"
    assert job.outputs_requested == 2
    assert job.price_minor == settings.image_price_minor
    # The live tray — the one the prompt moved under itself — is the one the quote lands on.
    assert job.tray_message_id == await live_tray(rig.dispatcher) != TRAY
    assert job.chat_id == CHAT_ID
    async with rig.sessions() as db:
        inputs = list((await db.scalars(sa.select(MediaInputRow))).all())
    assert sorted(row.tg_file_id or "" for row in inputs) == ["f-a", "f-b"]
    assert [stage.name for stage in rig.queue.pending] == [MEDIA_SCREEN_JOB]
    # The tray read "checking" before the enqueue, so the worker's quote lands last.
    assert tray_edits(session)[-1] == translate("media.screening", Language.EN)
    assert await rig.fsm_state() == ImageOrder.quote.state


async def test_a_second_done_with_a_prepay_row_open_cancels_the_old_one(
    settings: Settings,
    sessions: async_sessionmaker[AsyncSession],
    bot: Bot,
    session: RecordingSession,
) -> None:
    rig = Rig(media_on(settings), sessions)
    await open_image_compose(rig, bot)
    await freeze(rig, bot)
    (first,) = await rig.jobs()
    await rig.move(first.id, MediaJobState.QUOTED)

    await new_compose(rig, bot)
    await freeze(rig, bot, prompt="a paper boat on a canal")

    old, new = await rig.jobs()
    assert old.id == first.id
    assert old.state is MediaJobState.CANCELLED
    assert new.state is MediaJobState.SCREENING
    names = [(stage.name, stage.args[0]) for stage in rig.queue.pending]
    assert (MEDIA_CLEANUP_JOB, str(old.id)) in names
    assert (MEDIA_SCREEN_JOB, str(new.id)) in names


async def test_a_paid_row_open_shows_the_open_request_and_freezes_nothing(
    settings: Settings,
    sessions: async_sessionmaker[AsyncSession],
    bot: Bot,
    session: RecordingSession,
) -> None:
    rig = Rig(media_on(settings), sessions)
    await open_image_compose(rig, bot)
    await freeze(rig, bot)
    (paid,) = await rig.jobs()
    await rig.move(paid.id, MediaJobState.QUOTED)
    await rig.move(paid.id, MediaJobState.PAID, paid_via=MediaPaidVia.BETA, paid_at=FIXED_MOMENT)

    # At the 🖼 press; the freeze's own check is the next test.
    await new_compose(rig, bot)
    shown = translate(
        "media.open_request.paid", Language.EN, kind=translate("media.kind.image", Language.EN)
    )
    assert session.last_screen.text == shown
    assert await rig.fsm_state() != ImageOrder.compose.state
    assert len(await rig.jobs()) == 1


async def test_a_compose_opened_before_a_payment_is_refused_at_the_freeze(
    settings: Settings,
    sessions: async_sessionmaker[AsyncSession],
    bot: Bot,
    session: RecordingSession,
) -> None:
    rig = Rig(media_on(settings), sessions)
    await open_image_compose(rig, bot)
    await freeze(rig, bot)
    (paid,) = await rig.jobs()
    await rig.move(paid.id, MediaJobState.QUOTED)
    # The customer opens a second compose while the first is still only quoted ...
    await new_compose(rig, bot)
    await send(rig.dispatcher, bot, "a second picture")
    await press(rig.dispatcher, bot, med(MediaAction.DONE))
    # ... and the first is paid for before they pick the shape.
    await rig.move(paid.id, MediaJobState.PAID, paid_via=MediaPaidVia.BETA, paid_at=FIXED_MOMENT)
    await press(rig.dispatcher, bot, med(MediaAction.ASPECT, arg=AspectPick.PORTRAIT))

    assert len(await rig.jobs()) == 1
    assert session.last_screen.text.startswith("📌")


async def test_edit_after_a_quote_opens_a_new_row_screened_before_any_quote(
    settings: Settings,
    sessions: async_sessionmaker[AsyncSession],
    bot: Bot,
    session: RecordingSession,
) -> None:
    rig = Rig(media_on(settings), sessions)
    await open_image_compose(rig, bot)
    await rig.dispatcher.feed_update(bot, photo_update("a"))
    await freeze(rig, bot)
    (quoted,) = await rig.jobs()
    await rig.move(quoted.id, MediaJobState.QUOTED)

    await press(rig.dispatcher, bot, med(MediaAction.EDIT, job=quoted.id))

    draft = load_media_draft(await rig.fsm())
    assert await rig.fsm_state() == ImageOrder.compose.state
    assert draft is not None and draft.prompt == PROMPT and len(draft.refs) == 1
    await send(rig.dispatcher, bot, "the same courtyard, at dawn")
    await press(rig.dispatcher, bot, med(MediaAction.DONE))
    await press(rig.dispatcher, bot, med(MediaAction.ASPECT, arg=AspectPick.PORTRAIT))

    old, new = await rig.jobs()
    assert old.state is MediaJobState.CANCELLED
    assert new.state is MediaJobState.SCREENING
    assert new.prompt == "the same courtyard, at dawn"
    assert new.screen_decision is None and new.quoted_at is None
    assert (MEDIA_SCREEN_JOB, str(new.id)) in [
        (stage.name, stage.args[0]) for stage in rig.queue.pending
    ]


# ---------------------------------------------------------------------------
# Post-freeze buttons (§2 "Callbacks", §2.5)
# ---------------------------------------------------------------------------
async def test_beta_starts_a_quoted_row_for_the_allowlist(
    settings: Settings,
    sessions: async_sessionmaker[AsyncSession],
    bot: Bot,
    session: RecordingSession,
) -> None:
    rig = Rig(media_on(settings), sessions)
    await open_image_compose(rig, bot)
    await freeze(rig, bot)
    (job,) = await rig.jobs()
    await rig.move(job.id, MediaJobState.QUOTED)

    await press(rig.dispatcher, bot, med(MediaAction.BETA, job=job.id))

    (started,) = await rig.jobs()
    assert started.state is MediaJobState.PAID
    assert started.paid_via is MediaPaidVia.BETA
    assert MEDIA_START_JOB in [stage.name for stage in rig.queue.pending]
    assert session.named("EditMessageReplyMarkup"), "the quote's buttons were not retired"
    assert await rig.fsm_state() is None


async def test_beta_re_checks_the_allowlist_at_press_time(
    settings: Settings,
    sessions: async_sessionmaker[AsyncSession],
    bot: Bot,
    session: RecordingSession,
) -> None:
    rig = Rig(media_on(settings), sessions)
    await open_image_compose(rig, bot)
    await freeze(rig, bot)
    (job,) = await rig.jobs()
    await rig.move(job.id, MediaJobState.QUOTED)
    # The owner takes the account off the beta list after the 🎁 was drawn.
    later = rig.again(media_on(settings, media_beta_allowlist=(USER_ID + 1,)))

    await press(later.dispatcher, bot, med(MediaAction.BETA, job=job.id))

    (still,) = await rig.jobs()
    assert still.state is MediaJobState.QUOTED
    assert MEDIA_START_JOB not in [stage.name for stage in rig.queue.pending]
    assert session.last_named("AnswerCallbackQuery").text == translate("media.stale", Language.EN)


# ---------------------------------------------------------------------------
# The Terms, read fail-CLOSED (§2.1, D20, D26, O4)
# ---------------------------------------------------------------------------
def _unreadable_terms() -> tuple[FakeTermsLedger, InMemoryTermsCache, TermsGate]:
    """A gate whose ledger cannot be read. The song flow's read fails OPEN on it (onboarding
    and ``TermsGateMiddleware`` let the chat through); a media request must not."""
    ledger = FakeTermsLedger()
    ledger.failure = StorageError("terms_acceptances is unreachable")
    cache = InMemoryTermsCache()
    return ledger, cache, TermsGate(ledger, TermsVersions("v1", "v1"), cache=cache)


async def test_an_unreadable_terms_ledger_freezes_no_image_request(
    settings: Settings,
    sessions: async_sessionmaker[AsyncSession],
    bot: Bot,
    session: RecordingSession,
) -> None:
    ledger, _, gate = _unreadable_terms()
    rig = Rig(media_on(settings), sessions, terms=gate)
    await open_image_compose(rig, bot)

    await freeze(rig, bot)

    assert await rig.jobs() == []
    assert rig.queue.pending == type(rig.queue.pending)()
    assert session.last_named("AnswerCallbackQuery").text == translate("media.busy", Language.EN)
    assert await rig.fsm_state() == ImageOrder.aspect.state
    # The ledger answers again, with the pair accepted: the same shape press freezes.
    ledger.failure = None
    await ledger.accept(USER_ID, gate.versions, language=Language.EN, source="gate")
    await press(rig.dispatcher, bot, med(MediaAction.ASPECT, arg=AspectPick.SQUARE))
    assert len(await rig.jobs()) == 1


async def test_an_unreadable_terms_ledger_starts_nothing_at_the_beta_press(
    settings: Settings,
    sessions: async_sessionmaker[AsyncSession],
    bot: Bot,
    session: RecordingSession,
) -> None:
    ledger, cache, gate = _unreadable_terms()
    ledger.failure = None
    await ledger.accept(USER_ID, gate.versions, language=Language.EN, source="gate")
    rig = Rig(media_on(settings), sessions, terms=gate)
    await open_image_compose(rig, bot)
    await freeze(rig, bot)
    (job,) = await rig.jobs()
    await rig.move(job.id, MediaJobState.QUOTED)
    # The day-long positive cache entry lapses and the ledger goes away.
    cache.values.clear()
    ledger.failure = StorageError("terms_acceptances is unreachable")

    await press(rig.dispatcher, bot, med(MediaAction.BETA, job=job.id))

    (still,) = await rig.jobs()
    assert still.state is MediaJobState.QUOTED
    assert MEDIA_START_JOB not in [stage.name for stage in rig.queue.pending]
    assert session.last_named("AnswerCallbackQuery").text == translate("media.busy", Language.EN)


async def test_a_press_on_somebody_elses_job_is_stale(
    settings: Settings,
    sessions: async_sessionmaker[AsyncSession],
    bot: Bot,
    session: RecordingSession,
) -> None:
    rig = Rig(media_on(settings), sessions)
    await open_image_compose(rig, bot)
    await freeze(rig, bot)
    (job,) = await rig.jobs()
    await rig.move(job.id, MediaJobState.QUOTED)
    async with rig.sessions.begin() as db:
        await db.execute(
            sa.update(MediaJobRow).where(MediaJobRow.id == job.id).values(telegram_user_id=1)
        )

    for action in (MediaAction.BETA, MediaAction.CANCEL, MediaAction.EDIT, MediaAction.PAY):
        await press(rig.dispatcher, bot, med(action, job=job.id))
        assert session.last_named("AnswerCallbackQuery").text == translate(
            "media.stale", Language.EN
        )
    (untouched,) = await rig.jobs()
    assert untouched.state is MediaJobState.QUOTED


class RecordingCharge:
    """A pay path that WOULD charge: every call is recorded, as a receipt would be written."""

    def __init__(self) -> None:
        self.charged: list[UUID] = []

    async def __call__(self, job: JobView) -> Result[MediaPayLink]:
        self.charged.append(job.id)
        return ok(MediaPayLink(url="https://checkout.test/pay", amount_minor=500_000))


async def test_pay_on_the_stub_rail_writes_no_receipt_and_starts_nothing(
    settings: Settings,
    sessions: async_sessionmaker[AsyncSession],
    bot: Bot,
    session: RecordingSession,
) -> None:
    # §10 M2.2: the charge itself is injected, so this fails if the stub guard goes away.
    charge = RecordingCharge()
    rig = Rig(media_on(settings), sessions, media_charge=charge)
    await open_image_compose(rig, bot)
    await freeze(rig, bot)
    (job,) = await rig.jobs()
    await rig.move(job.id, MediaJobState.QUOTED)

    await press(rig.dispatcher, bot, med(MediaAction.PAY, job=job.id))

    assert charge.charged == []
    (still,) = await rig.jobs()
    assert still.state is MediaJobState.QUOTED
    async with rig.sessions() as db:
        assert (await db.scalar(sa.select(sa.func.count()).select_from(MediaPurchaseRow))) == 0
    assert MEDIA_START_JOB not in [stage.name for stage in rig.queue.pending]
    assert session.last_named("AnswerCallbackQuery").show_alert is True


async def test_pay_on_a_live_paid_rail_reaches_the_charge(
    settings: Settings,
    sessions: async_sessionmaker[AsyncSession],
    bot: Bot,
    session: RecordingSession,
) -> None:
    # The contrast: the same press on a live-paid rail is handed to the charge, once.
    live = media_on(
        settings,
        checkout_provider="payme",
        credits_enforced=True,
        payme_is_sandbox=False,
    )
    charge = RecordingCharge()
    rig = Rig(live, sessions, media_charge=charge)
    await open_image_compose(rig, bot)
    await freeze(rig, bot)
    (job,) = await rig.jobs()
    await rig.move(job.id, MediaJobState.QUOTED)

    await press(rig.dispatcher, bot, med(MediaAction.PAY, job=job.id))

    assert charge.charged == [job.id]


async def test_cancel_on_a_quote_cancels_it_and_cleans_up(
    settings: Settings,
    sessions: async_sessionmaker[AsyncSession],
    bot: Bot,
    session: RecordingSession,
) -> None:
    rig = Rig(media_on(settings), sessions)
    await open_image_compose(rig, bot)
    await freeze(rig, bot)
    (job,) = await rig.jobs()
    await rig.move(job.id, MediaJobState.QUOTED)

    await press(rig.dispatcher, bot, med(MediaAction.CANCEL, job=job.id))

    (cancelled,) = await rig.jobs()
    assert cancelled.state is MediaJobState.CANCELLED
    assert (MEDIA_CLEANUP_JOB, str(job.id)) in [
        (stage.name, stage.args[0]) for stage in rig.queue.pending
    ]
    assert session.last_screen.text == translate("media.cancelled", Language.EN)


async def test_retry_on_a_busy_tray_re_screens_the_same_row_under_a_new_id(
    settings: Settings,
    sessions: async_sessionmaker[AsyncSession],
    bot: Bot,
    session: RecordingSession,
) -> None:
    rig = Rig(media_on(settings), sessions)
    await open_image_compose(rig, bot)
    await freeze(rig, bot)
    (job,) = await rig.jobs()

    await press(rig.dispatcher, bot, med(MediaAction.RETRY, job=job.id))

    screens = [stage for stage in rig.queue.pending if stage.name == MEDIA_SCREEN_JOB]
    assert len(screens) == 2
    assert len({stage.job_id for stage in screens}) == 2
    assert {stage.args[0] for stage in screens} == {str(job.id)}


async def test_again_opens_a_compose_with_the_prompt_and_shape_but_not_the_photos(
    settings: Settings,
    sessions: async_sessionmaker[AsyncSession],
    bot: Bot,
    session: RecordingSession,
) -> None:
    rig = Rig(media_on(settings), sessions)
    await open_image_compose(rig, bot)
    await rig.dispatcher.feed_update(bot, photo_update("a"))
    await freeze(rig, bot)
    (job,) = await rig.jobs()
    await rig.move(job.id, MediaJobState.QUOTED)
    await rig.move(job.id, MediaJobState.PAID, paid_via=MediaPaidVia.BETA, paid_at=FIXED_MOMENT)
    await rig.move(job.id, MediaJobState.FAILED)

    await press(rig.dispatcher, bot, med(MediaAction.AGAIN, job=job.id))

    draft = load_media_draft(await rig.fsm())
    assert draft is not None
    assert draft.prompt == PROMPT and draft.refs == () and draft.aspect is not None
    assert sent_texts(session)[-1].startswith(
        translate("media.compose.photos_not_kept", Language.EN)
    )


# ---------------------------------------------------------------------------
# /cancel (§2.6)
# ---------------------------------------------------------------------------
async def test_cancel_command_cancels_a_prepay_request(
    settings: Settings,
    sessions: async_sessionmaker[AsyncSession],
    bot: Bot,
    session: RecordingSession,
) -> None:
    rig = Rig(media_on(settings), sessions)
    await open_image_compose(rig, bot)
    await freeze(rig, bot)

    await send(rig.dispatcher, bot, "/cancel")

    (job,) = await rig.jobs()
    assert job.state is MediaJobState.CANCELLED
    assert sent_texts(session)[-1] == translate("media.cancelled", Language.EN)
    assert await rig.fsm_state() is None


async def test_cancel_command_on_a_paid_request_says_too_late(
    settings: Settings,
    sessions: async_sessionmaker[AsyncSession],
    bot: Bot,
    session: RecordingSession,
) -> None:
    rig = Rig(media_on(settings), sessions)
    await open_image_compose(rig, bot)
    await freeze(rig, bot)
    (job,) = await rig.jobs()
    await rig.move(job.id, MediaJobState.QUOTED)
    await rig.move(job.id, MediaJobState.PAID, paid_via=MediaPaidVia.BETA, paid_at=FIXED_MOMENT)

    await send(rig.dispatcher, bot, "/cancel")

    (still,) = await rig.jobs()
    assert still.state is MediaJobState.PAID
    assert sent_texts(session)[-1] == translate("media.cancel_too_late", Language.EN)
    assert translate("wizard.cancelled", Language.EN) not in sent_texts(session)[-1:]


# ---------------------------------------------------------------------------
# The menu re-push (§2.2)
# ---------------------------------------------------------------------------
async def test_the_repush_fires_once_and_not_after_every_song(
    settings: Settings,
    sessions: async_sessionmaker[AsyncSession],
    bot: Bot,
    session: RecordingSession,
) -> None:
    rig = Rig(media_on(settings), sessions)
    await complete_onboarding(rig.dispatcher, bot)
    # Onboarding drew the current keyboard and recorded it.
    assert rig.kv.values[menu_version_key(USER_ID)] == str(MENU_VERSION)
    # An account from before ✨ — no version on record — meeting a freshly deployed bot.
    del rig.kv.values[menu_version_key(USER_ID)]
    rig = rig.again(rig.settings)
    session.clear()

    await send(rig.dispatcher, bot, "/help")

    pushed = [text for text in sent_texts(session) if "✨ New" in text]
    assert len(pushed) == 1
    assert last_reply_keyboard(session) is not None
    assert rig.kv.values[menu_version_key(USER_ID)] == str(MENU_VERSION)

    # A song ends: the worker wipes the FSM data. And the bot restarts: a fresh middleware.
    key = StorageKey(bot_id=BOT_ID, chat_id=CHAT_ID, user_id=USER_ID)
    data = await rig.storage.get_data(key)
    await rig.storage.set_data(key, {k: v for k, v in data.items() if k != "draft"})
    restarted = rig.again(rig.settings)
    session.clear()
    await send(restarted.dispatcher, bot, "/help")
    await send(restarted.dispatcher, bot, "/help")

    assert not [text for text in sent_texts(session) if "✨ New" in text]
    assert last_reply_keyboard(session) is None


async def test_the_repush_is_silent_for_an_account_offered_no_media(
    settings: Settings,
    sessions: async_sessionmaker[AsyncSession],
    bot: Bot,
    session: RecordingSession,
) -> None:
    rig = Rig(settings, sessions)
    await complete_onboarding(rig.dispatcher, bot)
    del rig.kv.values[menu_version_key(USER_ID)]
    rig = rig.again(rig.settings)
    session.clear()

    await send(rig.dispatcher, bot, "/help")

    assert last_reply_keyboard(session) is not None
    assert not [text for text in sent_texts(session) if "✨ New" in text]


async def test_forget_deletes_the_menu_version(
    settings: Settings,
    sessions: async_sessionmaker[AsyncSession],
    bot: Bot,
    session: RecordingSession,
) -> None:
    rig = Rig(media_on(settings), sessions)
    await complete_onboarding(rig.dispatcher, bot)
    assert menu_version_key(USER_ID) in rig.kv.values

    await send(rig.dispatcher, bot, "/forget")

    assert menu_version_key(USER_ID) not in rig.kv.values


async def test_a_song_is_still_one_tap_away_through_the_picker(
    settings: Settings,
    sessions: async_sessionmaker[AsyncSession],
    bot: Bot,
    session: RecordingSession,
) -> None:
    rig = Rig(media_on(settings), sessions)
    await complete_onboarding(rig.dispatcher, bot)
    await tap(rig.dispatcher, bot, "menu.generate", Language.EN)

    await press(rig.dispatcher, bot, med(MediaAction.PICK, arg=CreatePick.SONG))

    data_with_prefix(session.last_screen.reply_markup, OccasionCB.__prefix__)
    await press(rig.dispatcher, bot, OccasionCB(value=Occasion.BIRTHDAY).pack())


def test_callback_update_is_the_harness_press() -> None:
    """The wizard's press sends from message ``TRAY`` — the tray a compose opens on, over the
    picker, until a photo or a prompt moves it."""
    update = callback_update("x")
    assert update.callback_query is not None
    assert update.callback_query.message is not None
    assert update.callback_query.message.message_id == TRAY
