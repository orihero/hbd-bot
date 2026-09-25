"""A video request in the bot, from ✨ to the screen (IMAGE_VIDEO_SPEC §2.4, §5.3, §5.4; M4.1).

Driven through the real router tree with a real ``SqlMediaDesk`` over in-memory SQLite, as
``test_media_compose`` drives the image. The worker is not run: its prescreen is stood in
for by marking the ``drafting`` row allowed, which is all the bot reads of it. The M4.1
acceptance tests that are the bot's:

* a 6 s voice note is rejected before its row exists;
* typed words over the per-language budget are rejected;
* the tier screen is skipped with one tier (and shown with two);
* ✅ Done freezes a ``drafting`` row and enqueues the prescreen; ⬅️ walks the back map and
  ✖️ is on every screen and cancels the draft;
* 🎬 is in the ✨ picker when video is offered; the quote's price is the SKU's (25 000 soʻm).

The worker half (ffprobe, whisper, the prescreen itself) is ``test_media_video_screen``.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import timedelta
from typing import Any, Final
from uuid import UUID

import pytest
import sqlalchemy as sa
from aiogram import Bot
from aiogram.types import Chat, Message, Update, User, Voice
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from bayram.bot.callbacks import AspectPick, CreatePick, MediaAction, ScriptPick
from bayram.bot.handlers.media import video
from bayram.bot.i18n import translate
from bayram.bot.media_draft import load_media_draft
from bayram.bot.states import VideoOrder
from bayram.config import Settings
from bayram.contracts import Language
from bayram.db.engine import create_session_factory
from bayram.db.enums import (
    MediaAspect,
    MediaInputRole,
    MediaJobState,
    MediaKind,
    MediaScreenDecision,
    MediaSku,
    MediaTier,
    MediaVoiceGender,
    MediaVoiceMode,
)
from bayram.db.models import Base
from bayram.db.models.media_input import MediaInputRow
from bayram.db.models.media_job import MediaJobRow
from bayram.media.overrides import GPU_RESERVED_KEY
from bayram.media.stages import MEDIA_PRESCREEN_JOB, MEDIA_SCREEN_JOB, MEDIA_SCRIPT_JOB
from tests.test_bot.conftest import (
    CHAT_ID,
    FIXED_MOMENT,
    USER_ID,
    RecordingSession,
    buttons,
)
from tests.test_bot.test_media_compose import PROMPT, Rig, med, sent_texts
from tests.test_bot.test_wizard_flow import complete_onboarding, press, send, tap

#: 13 words: over English's twelve.
_THIRTEEN_WORDS: Final[str] = "one two three four five six seven eight nine ten eleven twelve 13"


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


def video_on(settings: Settings, **update: Any) -> Settings:
    """Video Standard offered to the beta allowlist on the stub rail (§2.5, O9)."""
    values: dict[str, Any] = {
        "is_video_standard_offered": True,
        "media_beta_enabled": True,
        "media_beta_allowlist": (USER_ID,),
    }
    values.update(update)
    return settings.model_copy(update=values)


_voice_message_id = 900


def voice_update(duration: int, *, unique: str = "note-1") -> Update:
    global _voice_message_id
    _voice_message_id += 1
    return Update(
        update_id=_voice_message_id,
        message=Message(
            message_id=_voice_message_id,
            date=FIXED_MOMENT,
            chat=Chat(id=CHAT_ID, type="private"),
            from_user=User(id=USER_ID, is_bot=False, first_name="Dilnoza"),
            voice=Voice(file_id=f"f-{unique}", file_unique_id=unique, duration=duration),
        ),
    )


async def open_video_compose(rig: Rig, bot: Bot) -> None:
    await complete_onboarding(rig.dispatcher, bot)
    await tap(rig.dispatcher, bot, "menu.generate", Language.EN)
    await press(rig.dispatcher, bot, med(MediaAction.PICK, arg=CreatePick.VIDEO))


async def the_job(rig: Rig) -> MediaJobRow:
    rows = [job for job in await rig.jobs() if job.kind is MediaKind.VIDEO]
    assert rows, "no video row"
    return rows[-1]


async def prescreen_allows(rig: Rig, job_id: UUID) -> None:
    """What ``media_prescreen`` records on an allow (the bot reads nothing else of it)."""
    async with rig.sessions.begin() as session:
        await session.execute(
            sa.update(MediaJobRow)
            .where(MediaJobRow.id == job_id)
            .values(screen_decision=MediaScreenDecision.ALLOW)
        )


async def done(rig: Rig, bot: Bot, *, prompt: str = PROMPT) -> MediaJobRow:
    """Type the prompt, ✅, and let the prescreen allow it."""
    await send(rig.dispatcher, bot, prompt)
    await press(rig.dispatcher, bot, med(MediaAction.DONE))
    job = await the_job(rig)
    await prescreen_allows(rig, job.id)
    return job


async def to_voice_screen(rig: Rig, bot: Bot) -> MediaJobRow:
    await open_video_compose(rig, bot)
    job = await done(rig, bot)
    await press(rig.dispatcher, bot, med(MediaAction.ASPECT, arg=AspectPick.SQUARE))
    return job


def labels(session: RecordingSession) -> list[str]:
    return [text for text, _ in buttons(session.last_screen.reply_markup)]


def last_answer(session: RecordingSession) -> str | None:
    answer: str | None = session.last_named("AnswerCallbackQuery").text
    return answer


async def voice_inputs(rig: Rig, job_id: UUID) -> list[MediaInputRow]:
    async with rig.sessions() as session:
        rows = await session.scalars(
            sa.select(MediaInputRow).where(
                MediaInputRow.job_id == job_id, MediaInputRow.role == MediaInputRole.VOICE_NOTE
            )
        )
        return list(rows.all())


def queued(rig: Rig, name: str) -> list[str]:
    return [stage.args[0] for stage in rig.queue.pending if stage.name == name]


# ---------------------------------------------------------------------------
# ✨, the tray and ✅ Done
# ---------------------------------------------------------------------------
async def test_video_is_in_the_picker_when_it_is_offered(
    settings: Settings,
    sessions: async_sessionmaker[AsyncSession],
    bot: Bot,
    session: RecordingSession,
) -> None:
    rig = Rig(video_on(settings), sessions)
    await complete_onboarding(rig.dispatcher, bot)

    await tap(rig.dispatcher, bot, "menu.generate", Language.EN)

    assert labels(session) == [
        translate("button.create.song", Language.EN),
        translate("button.create.video", Language.EN),
    ]
    await press(rig.dispatcher, bot, med(MediaAction.PICK, arg=CreatePick.VIDEO))
    assert await rig.fsm_state() == VideoOrder.compose.state
    assert session.last_screen.text.startswith(translate("media.video.compose", Language.EN, max=4))


async def test_done_freezes_a_drafting_row_and_asks_for_the_prescreen(
    settings: Settings,
    sessions: async_sessionmaker[AsyncSession],
    bot: Bot,
    session: RecordingSession,
) -> None:
    rig = Rig(video_on(settings), sessions)
    await open_video_compose(rig, bot)
    await send(rig.dispatcher, bot, PROMPT)

    await press(rig.dispatcher, bot, med(MediaAction.DONE))

    job = await the_job(rig)
    assert job.state is MediaJobState.DRAFTING
    assert (job.sku, job.tier, job.outputs_requested) == (
        MediaSku.VIDEO_STANDARD,
        MediaTier.STANDARD,
        1,
    )
    assert job.price_minor == 2_500_000
    assert job.prompt == PROMPT
    assert queued(rig, MEDIA_PRESCREEN_JOB) == [str(job.id)]
    assert queued(rig, MEDIA_SCREEN_JOB) == []
    assert await rig.fsm_state() == VideoOrder.aspect.state
    assert session.last_screen.text == translate("media.screening", Language.EN)


async def test_the_gpu_reserved_at_done_freezes_nothing(
    settings: Settings,
    sessions: async_sessionmaker[AsyncSession],
    bot: Bot,
    session: RecordingSession,
) -> None:
    rig = Rig(video_on(settings), sessions)
    rig.kv.values[GPU_RESERVED_KEY] = (FIXED_MOMENT + timedelta(hours=1)).isoformat()
    await open_video_compose(rig, bot)
    await send(rig.dispatcher, bot, PROMPT)

    await press(rig.dispatcher, bot, med(MediaAction.DONE))

    assert await rig.jobs() == []
    assert last_answer(session) == translate("media.busy", Language.EN)
    assert await rig.fsm_state() == VideoOrder.compose.state


# ---------------------------------------------------------------------------
# Shape and tier (§2.4.1)
# ---------------------------------------------------------------------------
async def test_the_tier_screen_is_skipped_with_one_tier(
    settings: Settings,
    sessions: async_sessionmaker[AsyncSession],
    bot: Bot,
    session: RecordingSession,
) -> None:
    rig = Rig(video_on(settings), sessions)

    await to_voice_screen(rig, bot)

    assert await rig.fsm_state() == VideoOrder.voice.state
    assert session.last_screen.text == translate(
        "media.voice.pick", Language.EN, seconds=5, words=12
    )
    shown = labels(session)
    assert translate("button.media.tier.standard", Language.EN) not in shown
    # All four voices (🤖 since the script writer, M4.3), ⬅️ and ✖️ are drawn.
    assert shown == [
        translate("button.media.voice.none", Language.EN),
        translate("button.media.voice.ai_mine", Language.EN),
        translate("button.media.voice.ai_llm", Language.EN),
        translate("button.media.voice.own", Language.EN),
        translate("button.media.back", Language.EN),
        translate("button.media.cancel", Language.EN),
    ]
    draft = load_media_draft(await rig.fsm())
    assert draft is not None and draft.tier is MediaTier.STANDARD


async def test_with_fast_offered_the_tier_screen_shows_both_and_fast_is_sold(
    settings: Settings,
    sessions: async_sessionmaker[AsyncSession],
    bot: Bot,
    session: RecordingSession,
) -> None:
    rig = Rig(
        video_on(settings, is_video_fast_offered=True, video_fast_price_minor=4_000_000),
        sessions,
    )

    await to_voice_screen(rig, bot)

    assert await rig.fsm_state() == VideoOrder.tier.state
    assert labels(session)[:2] == [
        translate("button.media.tier.standard", Language.EN),
        translate("button.media.tier.fast", Language.EN),
    ]
    await press(rig.dispatcher, bot, med(MediaAction.TIER, arg=MediaTier.FAST))
    await press(rig.dispatcher, bot, med(MediaAction.VOICE, arg=MediaVoiceMode.NONE))

    job = await the_job(rig)
    assert (job.sku, job.tier, job.price_minor) == (MediaSku.VIDEO_FAST, MediaTier.FAST, 4_000_000)


async def test_fast_offered_without_a_price_is_not_sellable_and_the_screen_is_skipped(
    settings: Settings,
    sessions: async_sessionmaker[AsyncSession],
    bot: Bot,
    session: RecordingSession,
) -> None:
    # §7.1: ``video_fast_price_minor`` unset (the default) = not sellable, whatever the flag.
    rig = Rig(video_on(settings, is_video_fast_offered=True), sessions)

    await to_voice_screen(rig, bot)

    assert await rig.fsm_state() == VideoOrder.voice.state
    assert translate("button.media.tier.fast", Language.EN) not in labels(session)
    draft = load_media_draft(await rig.fsm())
    assert draft is not None and draft.tier is MediaTier.STANDARD


async def test_with_the_gpu_reserved_fast_is_still_sold_and_standard_is_not_offered(
    settings: Settings,
    sessions: async_sessionmaker[AsyncSession],
    bot: Bot,
    session: RecordingSession,
) -> None:
    # O11 closes the local tier only; Fast renders on Higgsfield (M6.2).
    rig = Rig(
        video_on(settings, is_video_fast_offered=True, video_fast_price_minor=4_000_000),
        sessions,
    )
    rig.kv.values[GPU_RESERVED_KEY] = (FIXED_MOMENT + timedelta(hours=1)).isoformat()

    frozen = await to_voice_screen(rig, bot)

    # The draft row's placeholder is the open tier, and the tier screen is skipped.
    assert (frozen.sku, frozen.tier, frozen.price_minor) == (
        MediaSku.VIDEO_FAST,
        MediaTier.FAST,
        4_000_000,
    )
    assert await rig.fsm_state() == VideoOrder.voice.state
    await press(rig.dispatcher, bot, med(MediaAction.VOICE, arg=MediaVoiceMode.NONE))
    job = await the_job(rig)
    assert (job.sku, job.tier, job.state) == (
        MediaSku.VIDEO_FAST,
        MediaTier.FAST,
        MediaJobState.SCREENING,
    )


async def test_video_is_in_the_picker_with_fast_alone(
    settings: Settings,
    sessions: async_sessionmaker[AsyncSession],
    bot: Bot,
    session: RecordingSession,
) -> None:
    rig = Rig(
        video_on(
            settings,
            is_video_standard_offered=False,
            is_video_fast_offered=True,
            video_fast_price_minor=4_000_000,
        ),
        sessions,
    )
    await complete_onboarding(rig.dispatcher, bot)

    await tap(rig.dispatcher, bot, "menu.generate", Language.EN)

    assert translate("button.create.video", Language.EN) in labels(session)


# ---------------------------------------------------------------------------
# The voice (§2.4.2)
# ---------------------------------------------------------------------------
async def test_no_voice_sends_the_draft_to_screening_with_every_choice(
    settings: Settings,
    sessions: async_sessionmaker[AsyncSession],
    bot: Bot,
    session: RecordingSession,
) -> None:
    rig = Rig(video_on(settings), sessions)
    frozen = await to_voice_screen(rig, bot)

    await press(rig.dispatcher, bot, med(MediaAction.VOICE, arg=MediaVoiceMode.NONE))

    job = await the_job(rig)
    assert job.id == frozen.id
    assert job.state is MediaJobState.SCREENING
    assert (job.aspect, job.voice_mode, job.narration_text) == (
        MediaAspect.SQUARE,
        MediaVoiceMode.NONE,
        None,
    )
    assert job.price_minor == 2_500_000
    # The prescreen's verdict is cleared: the screen judges the whole request again.
    assert job.screen_decision is None
    assert queued(rig, MEDIA_SCREEN_JOB) == [str(job.id)]
    assert await rig.fsm_state() == VideoOrder.quote.state
    assert session.last_screen.text == translate("media.screening", Language.EN)


async def test_typed_words_over_the_budget_are_rejected_and_words_within_it_are_screened(
    settings: Settings,
    sessions: async_sessionmaker[AsyncSession],
    bot: Bot,
    session: RecordingSession,
) -> None:
    rig = Rig(video_on(settings), sessions)
    await to_voice_screen(rig, bot)
    await press(rig.dispatcher, bot, med(MediaAction.VOICE, arg=MediaVoiceMode.AI_USER))
    await press(rig.dispatcher, bot, med(MediaAction.GENDER, arg=MediaVoiceGender.FEMALE))
    assert session.last_screen.text == translate("media.voice.enter_text", Language.EN, words=12)

    await send(rig.dispatcher, bot, _THIRTEEN_WORDS)

    assert sent_texts(session)[-1] == translate(
        "media.voice.too_long", Language.EN, seconds=5, words=12
    )
    assert (await the_job(rig)).state is MediaJobState.DRAFTING
    assert await rig.fsm_state() == VideoOrder.voice_text.state

    await send(rig.dispatcher, bot, "  Happy   birthday, Dilnoza!  ")

    job = await the_job(rig)
    assert job.state is MediaJobState.SCREENING
    assert job.narration_text == "Happy birthday, Dilnoza!"
    assert (job.voice_mode, job.voice_gender) == (MediaVoiceMode.AI_USER, MediaVoiceGender.FEMALE)
    # The quote lands on a NEW message under the words, which the row now names.
    assert sent_texts(session)[-1] == translate("media.screening", Language.EN)
    assert job.tray_message_id is not None and job.tray_message_id != 20


async def test_the_budget_is_the_customers_language(
    settings: Settings,
    sessions: async_sessionmaker[AsyncSession],
    bot: Bot,
    session: RecordingSession,
) -> None:
    rig = Rig(video_on(settings), sessions)
    await complete_onboarding(rig.dispatcher, bot, language=Language.UZ_LATN)
    await tap(rig.dispatcher, bot, "menu.generate", Language.UZ_LATN)
    await press(rig.dispatcher, bot, med(MediaAction.PICK, arg=CreatePick.VIDEO))
    await done(rig, bot)
    await press(rig.dispatcher, bot, med(MediaAction.ASPECT, arg=AspectPick.PORTRAIT))
    await press(rig.dispatcher, bot, med(MediaAction.VOICE, arg=MediaVoiceMode.AI_USER))
    await press(rig.dispatcher, bot, med(MediaAction.GENDER, arg=MediaVoiceGender.MALE))

    # Nine words: inside English's twelve, over Uzbek's eight.
    await send(rig.dispatcher, bot, "bir ikki uch toʻrt besh olti yetti sakkiz toʻqqiz")

    assert sent_texts(session)[-1] == translate(
        "media.voice.too_long", Language.UZ_LATN, seconds=5, words=8
    )
    assert (await the_job(rig)).state is MediaJobState.DRAFTING


async def test_a_six_second_voice_note_is_rejected_before_its_row_exists(
    settings: Settings,
    sessions: async_sessionmaker[AsyncSession],
    bot: Bot,
    session: RecordingSession,
) -> None:
    rig = Rig(video_on(settings), sessions)
    frozen = await to_voice_screen(rig, bot)
    await press(rig.dispatcher, bot, med(MediaAction.VOICE, arg=MediaVoiceMode.OWN))
    assert session.last_screen.text == translate("media.voice.send_note", Language.EN, seconds=5)

    await rig.dispatcher.feed_update(bot, voice_update(6))

    assert sent_texts(session)[-1] == translate(
        "media.voice_note.too_long", Language.EN, dur="6.0", seconds=5
    )
    assert await voice_inputs(rig, frozen.id) == []
    assert (await the_job(rig)).state is MediaJobState.DRAFTING
    assert await rig.fsm_state() == VideoOrder.voice_note.state


async def test_a_five_second_note_goes_to_screening_by_its_telegram_ids(
    settings: Settings,
    sessions: async_sessionmaker[AsyncSession],
    bot: Bot,
    session: RecordingSession,
) -> None:
    rig = Rig(video_on(settings), sessions)
    frozen = await to_voice_screen(rig, bot)
    await press(rig.dispatcher, bot, med(MediaAction.VOICE, arg=MediaVoiceMode.OWN))

    # Telegram says 5; a 5.9 s note says 5 too — ffprobe decides in the worker (§5.4).
    await rig.dispatcher.feed_update(bot, voice_update(5))

    job = await the_job(rig)
    assert job.state is MediaJobState.SCREENING
    assert job.voice_mode is MediaVoiceMode.OWN
    (note,) = await voice_inputs(rig, frozen.id)
    assert (note.tg_file_id, note.tg_file_unique_id) == ("f-note-1", "note-1")
    assert note.storage_key is None  # bytes are the worker's to fetch
    assert queued(rig, MEDIA_SCREEN_JOB) == [str(job.id)]


async def test_the_wrong_kind_of_message_in_a_voice_step_is_answered(
    settings: Settings,
    sessions: async_sessionmaker[AsyncSession],
    bot: Bot,
    session: RecordingSession,
) -> None:
    rig = Rig(video_on(settings), sessions)
    await to_voice_screen(rig, bot)
    await press(rig.dispatcher, bot, med(MediaAction.VOICE, arg=MediaVoiceMode.OWN))

    await send(rig.dispatcher, bot, "hello there")
    assert sent_texts(session)[-1] == translate("media.voice_note.wrong_type", Language.EN)

    await press(rig.dispatcher, bot, med(MediaAction.BACK))
    await press(rig.dispatcher, bot, med(MediaAction.VOICE, arg=MediaVoiceMode.AI_USER))
    await press(rig.dispatcher, bot, med(MediaAction.GENDER, arg=MediaVoiceGender.FEMALE))
    await rig.dispatcher.feed_update(bot, voice_update(3))
    assert sent_texts(session)[-1] == translate("media.voice.enter_text", Language.EN, words=12)

    # And on a buttons-only screen, text is pointed at the buttons.
    await press(rig.dispatcher, bot, med(MediaAction.BACK))
    await send(rig.dispatcher, bot, "hello there")
    assert sent_texts(session)[-1] == translate("media.use_buttons", Language.EN)
    assert (await the_job(rig)).state is MediaJobState.DRAFTING


# ---------------------------------------------------------------------------
# ⬅️ and ✖️ (§2.4.1)
# ---------------------------------------------------------------------------
async def test_back_walks_the_map_and_back_to_compose_cancels_the_draft(
    settings: Settings,
    sessions: async_sessionmaker[AsyncSession],
    bot: Bot,
    session: RecordingSession,
) -> None:
    rig = Rig(video_on(settings), sessions)
    frozen = await to_voice_screen(rig, bot)
    await press(rig.dispatcher, bot, med(MediaAction.VOICE, arg=MediaVoiceMode.AI_USER))

    await press(rig.dispatcher, bot, med(MediaAction.BACK))  # gender → voice
    assert await rig.fsm_state() == VideoOrder.voice.state
    await press(rig.dispatcher, bot, med(MediaAction.BACK))  # voice → aspect (one tier)
    assert await rig.fsm_state() == VideoOrder.aspect.state
    assert session.last_screen.text == translate("media.aspect", Language.EN)
    assert (await the_job(rig)).state is MediaJobState.DRAFTING

    await press(rig.dispatcher, bot, med(MediaAction.BACK))  # aspect → compose

    assert await rig.fsm_state() == VideoOrder.compose.state
    assert (await the_job(rig)).state is MediaJobState.CANCELLED
    assert PROMPT in session.last_screen.text
    # A later ✅ freezes a NEW draft, prescreened again.
    await press(rig.dispatcher, bot, med(MediaAction.DONE))
    fresh = await the_job(rig)
    assert fresh.id != frozen.id and fresh.state is MediaJobState.DRAFTING
    assert queued(rig, MEDIA_PRESCREEN_JOB) == [str(frozen.id), str(fresh.id)]


async def test_cancel_on_a_voice_screen_cancels_the_draft(
    settings: Settings,
    sessions: async_sessionmaker[AsyncSession],
    bot: Bot,
    session: RecordingSession,
) -> None:
    rig = Rig(video_on(settings), sessions)
    await to_voice_screen(rig, bot)
    await press(rig.dispatcher, bot, med(MediaAction.VOICE, arg=MediaVoiceMode.OWN))

    await press(rig.dispatcher, bot, med(MediaAction.DROP))

    assert (await the_job(rig)).state is MediaJobState.CANCELLED
    assert session.last_screen.text == translate("media.cancelled", Language.EN)
    assert await rig.fsm_state() is None


async def test_a_draft_the_prescreen_never_allowed_is_not_finalised(
    settings: Settings,
    sessions: async_sessionmaker[AsyncSession],
    bot: Bot,
    session: RecordingSession,
) -> None:
    rig = Rig(video_on(settings), sessions)
    await open_video_compose(rig, bot)
    await send(rig.dispatcher, bot, PROMPT)
    await press(rig.dispatcher, bot, med(MediaAction.DONE))
    # No prescreen verdict; a hand-made shape and voice press.
    await press(rig.dispatcher, bot, med(MediaAction.ASPECT, arg=AspectPick.SQUARE))
    await press(rig.dispatcher, bot, med(MediaAction.VOICE, arg=MediaVoiceMode.NONE))

    job = await the_job(rig)
    assert job.state is MediaJobState.DRAFTING
    assert queued(rig, MEDIA_SCREEN_JOB) == []
    assert session.last_screen.text == translate("media.stale", Language.EN)


# ---------------------------------------------------------------------------
# 🎙 record again (§5.4) and 🤖 AI writes (§2.4.2)
# ---------------------------------------------------------------------------
async def test_record_again_reopens_the_same_draft_at_the_voice_note(
    settings: Settings,
    sessions: async_sessionmaker[AsyncSession],
    bot: Bot,
    session: RecordingSession,
) -> None:
    rig = Rig(video_on(settings), sessions)
    frozen = await to_voice_screen(rig, bot)
    await press(rig.dispatcher, bot, med(MediaAction.VOICE, arg=MediaVoiceMode.OWN))
    await rig.dispatcher.feed_update(bot, voice_update(5))
    # The worker's ffprobe found 5.6 s and sent the draft back (``_bounce_voice_note``):
    # the row to ``drafting`` with the prescreen's verdict, the note's row deleted.
    await rig.move(frozen.id, MediaJobState.DRAFTING, screen_decision=MediaScreenDecision.ALLOW)
    async with rig.sessions.begin() as db:
        await db.execute(sa.delete(MediaInputRow).where(MediaInputRow.job_id == frozen.id))

    await press(rig.dispatcher, bot, med(MediaAction.RECORD, job=frozen.id))

    assert await rig.fsm_state() == VideoOrder.voice_note.state
    assert session.last_screen.text == translate("media.voice.send_note", Language.EN, seconds=5)
    await rig.dispatcher.feed_update(bot, voice_update(4, unique="note-2"))
    job = await the_job(rig)
    assert job.id == frozen.id and job.state is MediaJobState.SCREENING
    assert job.aspect is MediaAspect.SQUARE


async def test_record_again_on_someone_elses_or_a_finished_row_is_stale(
    settings: Settings,
    sessions: async_sessionmaker[AsyncSession],
    bot: Bot,
    session: RecordingSession,
) -> None:
    rig = Rig(video_on(settings), sessions)
    frozen = await to_voice_screen(rig, bot)
    await press(rig.dispatcher, bot, med(MediaAction.VOICE, arg=MediaVoiceMode.NONE))
    await rig.move(frozen.id, MediaJobState.QUOTED)

    await press(rig.dispatcher, bot, med(MediaAction.RECORD, job=frozen.id))

    assert last_answer(session) == translate("media.stale", Language.EN)
    assert await rig.fsm_state() == VideoOrder.quote.state


async def test_ai_writes_asks_the_worker_and_uses_the_line_it_wrote(
    settings: Settings,
    sessions: async_sessionmaker[AsyncSession],
    bot: Bot,
    session: RecordingSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(video, "BUILT_VOICE_MODES", frozenset(MediaVoiceMode))
    rig = Rig(video_on(settings, media_script_max_regens=1), sessions)
    frozen = await to_voice_screen(rig, bot)
    assert translate("button.media.voice.ai_llm", Language.EN) in labels(session)
    await press(rig.dispatcher, bot, med(MediaAction.VOICE, arg=MediaVoiceMode.AI_LLM))

    await press(rig.dispatcher, bot, med(MediaAction.GENDER, arg=MediaVoiceGender.MALE))

    assert queued(rig, MEDIA_SCRIPT_JOB) == [str(frozen.id)]
    assert await rig.fsm_state() == VideoOrder.script_review.state
    assert session.last_screen.text == translate("media.voice.script_wait", Language.EN)
    # ✅ before the line exists waits.
    await press(rig.dispatcher, bot, med(MediaAction.SCRIPT, arg=ScriptPick.USE))
    assert last_answer(session) == translate("media.voice.script_wait", Language.EN)
    # 🔄 once is allowed (max 1); the second is stale.
    await press(rig.dispatcher, bot, med(MediaAction.SCRIPT, arg=ScriptPick.ANOTHER))
    await press(rig.dispatcher, bot, med(MediaAction.SCRIPT, arg=ScriptPick.ANOTHER))
    assert last_answer(session) == translate("media.stale", Language.EN)
    assert [stage.job_id for stage in rig.queue.pending if stage.name == MEDIA_SCRIPT_JOB] == [
        f"media:{frozen.id}:script:0",
        f"media:{frozen.id}:script:1",
    ]
    # The worker writes the line onto the draft (``media_script``, M4.3).
    async with rig.sessions.begin() as db:
        await db.execute(
            sa.update(MediaJobRow)
            .where(MediaJobRow.id == frozen.id)
            .values(narration_text="Happy birthday, dear friend")
        )

    await press(rig.dispatcher, bot, med(MediaAction.SCRIPT, arg=ScriptPick.USE))

    job = await the_job(rig)
    assert job.state is MediaJobState.SCREENING
    assert (job.voice_mode, job.voice_gender, job.narration_text) == (
        MediaVoiceMode.AI_LLM,
        MediaVoiceGender.MALE,
        "Happy birthday, dear friend",
    )


async def test_back_from_a_line_being_written_stops_the_draft_asking_for_it(
    settings: Settings,
    sessions: async_sessionmaker[AsyncSession],
    bot: Bot,
    session: RecordingSession,
) -> None:
    """⬅️ out of the 🤖 branch: the row stops being ``ai_llm``, so a ``media_script`` still in
    flight neither stores its line nor redraws the tray over the voice screen (§2.4.2)."""
    rig = Rig(video_on(settings), sessions)
    frozen = await to_voice_screen(rig, bot)
    await press(rig.dispatcher, bot, med(MediaAction.VOICE, arg=MediaVoiceMode.AI_LLM))
    await press(rig.dispatcher, bot, med(MediaAction.GENDER, arg=MediaVoiceGender.MALE))
    assert (await the_job(rig)).voice_mode is MediaVoiceMode.AI_LLM

    await press(rig.dispatcher, bot, med(MediaAction.BACK))

    assert await rig.fsm_state() == VideoOrder.voice.state
    job = await the_job(rig)
    assert job.id == frozen.id and job.state is MediaJobState.DRAFTING
    assert (job.voice_mode, job.narration_text) == (MediaVoiceMode.NONE, None)


async def test_words_typed_after_edit_are_the_customers_not_ours(
    settings: Settings,
    sessions: async_sessionmaker[AsyncSession],
    bot: Bot,
    session: RecordingSession,
) -> None:
    """✏️ under a 🤖 line: the typed words go to screening as ``ai_user`` — ``ai_llm`` means
    the unedited line we wrote, which a TTS refusal does not strike (§5.5)."""
    rig = Rig(video_on(settings), sessions)
    frozen = await to_voice_screen(rig, bot)
    await press(rig.dispatcher, bot, med(MediaAction.VOICE, arg=MediaVoiceMode.AI_LLM))
    await press(rig.dispatcher, bot, med(MediaAction.GENDER, arg=MediaVoiceGender.FEMALE))
    async with rig.sessions.begin() as db:
        await db.execute(
            sa.update(MediaJobRow)
            .where(MediaJobRow.id == frozen.id)
            .values(narration_text="Happy birthday, dear friend")
        )
    await press(rig.dispatcher, bot, med(MediaAction.SCRIPT, arg=ScriptPick.EDIT))

    await send(rig.dispatcher, bot, "Happy birthday, Dilnoza")

    job = await the_job(rig)
    assert job.state is MediaJobState.SCREENING
    assert (job.voice_mode, job.narration_text) == (
        MediaVoiceMode.AI_USER,
        "Happy birthday, Dilnoza",
    )


async def test_ai_writes_is_offered_now_that_the_writer_is_built(
    settings: Settings,
    sessions: async_sessionmaker[AsyncSession],
    bot: Bot,
    session: RecordingSession,
) -> None:
    # M4.3 registered ``media_script``, so 🤖 is drawn and leads to the voice choice.
    rig = Rig(video_on(settings), sessions)
    await to_voice_screen(rig, bot)
    assert translate("button.media.voice.ai_llm", Language.EN) in labels(session)

    await press(rig.dispatcher, bot, med(MediaAction.VOICE, arg=MediaVoiceMode.AI_LLM))

    assert await rig.fsm_state() == VideoOrder.voice_gender.state


async def test_edit_on_a_video_quote_reopens_a_video_compose(
    settings: Settings,
    sessions: async_sessionmaker[AsyncSession],
    bot: Bot,
    session: RecordingSession,
) -> None:
    rig = Rig(video_on(settings), sessions)
    frozen = await to_voice_screen(rig, bot)
    await press(rig.dispatcher, bot, med(MediaAction.VOICE, arg=MediaVoiceMode.NONE))
    await rig.move(frozen.id, MediaJobState.QUOTED)

    await press(rig.dispatcher, bot, med(MediaAction.EDIT, job=frozen.id))

    assert (await the_job(rig)).state is MediaJobState.CANCELLED
    assert await rig.fsm_state() == VideoOrder.compose.state
    draft = load_media_draft(await rig.fsm())
    assert draft is not None and draft.kind is MediaKind.VIDEO and draft.prompt == PROMPT
