"""A video request's screening before payment (IMAGE_VIDEO_SPEC §2.4.1, §5.3, §5.4; M4.1).

The worker half of M4.1, over the fakes of ``media_fakes`` plus a scripted voice probe (no
ffmpeg in the unit suite). The acceptance tests that need the stage chain:

* the prescreen of a ``drafting`` row: allow → the shape screen, block → refused;
* a 5.6 s note (Telegram says 5) is refused by ffprobe before payment — the draft goes back
  for 🎙 record again, nothing is quoted, the note is deleted;
* whisper low ``avg_logprob`` / a wrong language / a low word rate → refused;
* an edited script with a denylisted term is refused at the screen;
* a line over its language's budget is refused (the backstop to the bot's check);
* a clean own note is stored, transcribed and screened as ``transcript``, and quoted with
  the video quote.
"""

from __future__ import annotations

import dataclasses
from collections.abc import AsyncIterator
from datetime import timedelta
from pathlib import Path
from typing import Any, Final
from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import StaticPool

from bayram.bot.callbacks import MediaAction, MediaCB
from bayram.bot.i18n import translate
from bayram.config import Settings
from bayram.contracts import Language, Result, ok
from bayram.db.engine import create_session_factory
from bayram.db.enums import (
    MediaAspect,
    MediaInputRole,
    MediaJobState,
    MediaKind,
    MediaScreenDecision,
    MediaSku,
    MediaTier,
    MediaVoiceMode,
)
from bayram.db.media import add_input, create_job, load_job
from bayram.db.models import Base, UserRow
from bayram.db.models.media_input import MediaInputRow
from bayram.db.models.media_job import MediaJobRow
from bayram.media.gate import QuoteBlock
from bayram.media.stages import (
    MEDIA_CLEANUP_JOB,
    MEDIA_PRESCREEN_JOB,
    MEDIA_SCREEN_JOB,
    prescreen_job_id,
    screen_job_id,
)
from bayram.media.voice_probe import VoiceMeasure
from bayram.moderation.contracts import MEDIA_POLICY_VERSION, VoiceTranscript
from bayram.runtime import media_jobs
from bayram.runtime.media_jobs import MediaErrorCode
from bayram.runtime.media_sweep import sweep_media
from tests.conftest import FIXED_NOW
from tests.test_runtime.media_fakes import (
    PROMPT,
    TRAY_ID,
    USER,
    Harness,
    build_harness,
    jpeg_bytes,
    media_settings,
)

_NOTE_FILE: Final[str] = "voice-file-1"
_OGG: Final[bytes] = b"OggS" + b"\x00" * 64


@dataclasses.dataclass
class ScriptedProbe:
    """ffprobe + silencedetect, as numbers."""

    duration_s: float = 4.0
    voiced_s: float = 3.5
    calls: int = 0

    async def measure(self, path: Path) -> Result[VoiceMeasure]:
        assert path.exists()
        self.calls += 1
        return ok(VoiceMeasure(duration_s=self.duration_s, voiced_s=self.voiced_s))


@pytest.fixture
async def engine() -> AsyncIterator[AsyncEngine]:
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    yield engine
    await engine.dispose()


@pytest.fixture
def sessions(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return create_session_factory(engine)


@pytest.fixture
def probe() -> ScriptedProbe:
    return ScriptedProbe()


@pytest.fixture
def harness(
    settings: Settings,
    sessions: async_sessionmaker[AsyncSession],
    tmp_path: Path,
    probe: ScriptedProbe,
) -> Harness:
    built = build_harness(
        media_settings(
            settings,
            is_video_standard_offered=True,
            video_standard_backend="fake",
        ),
        sessions,
        tmp_path,
        FIXED_NOW,
    )
    built.rt = dataclasses.replace(built.rt, voice_probe=probe)
    built.moderator.transcript = VoiceTranscript(
        text="happy birthday my dear friend",
        language="en",
        avg_logprob=-0.2,
        no_speech_prob=0.01,
        max_compression_ratio=1.1,
    )
    return built


async def _video_row(
    harness: Harness,
    *,
    state: MediaJobState,
    photos: int = 0,
    voice_mode: MediaVoiceMode = MediaVoiceMode.NONE,
    narration: str | None = None,
    voice_note: bool = False,
    language: Language = Language.EN,
) -> UUID:
    """A video row as the bot leaves it: ``drafting`` after ✅ Done, or ``screening`` after
    the last voice step (``finalize_video``)."""
    now = harness.clock()
    async with harness.sessions.begin() as session:
        user_id = uuid4()
        session.add(UserRow(id=user_id, telegram_user_id=USER))
        await session.flush()
        job_id = await create_job(
            session,
            user_id=user_id,
            telegram_user_id=USER,
            kind=MediaKind.VIDEO,
            sku=MediaSku.VIDEO_STANDARD,
            state=state,
            chat_id=USER,
            outputs_requested=1,
            aspect=MediaAspect.PORTRAIT,
            language=language,
            prompt=PROMPT,
            price_minor=2_500_000,
            currency="UZS",
            now=now,
            quote_ttl=timedelta(seconds=86_400),
            tier=MediaTier.STANDARD,
            voice_mode=voice_mode,
            narration_text=narration,
            tray_message_id=TRAY_ID,
        )
        for ordinal in range(photos):
            file_id = f"photo-{ordinal}"
            harness.messenger.files[file_id] = jpeg_bytes((20 * ordinal, 90, 160))
            await add_input(
                session,
                job_id=job_id,
                ordinal=ordinal,
                role=MediaInputRole.PHOTO,
                now=now,
                tg_file_id=file_id,
                tg_file_unique_id=f"u-{ordinal}",
            )
        if voice_note:
            harness.messenger.files[_NOTE_FILE] = _OGG
            await add_input(
                session,
                job_id=job_id,
                ordinal=0,
                role=MediaInputRole.VOICE_NOTE,
                now=now,
                tg_file_id=_NOTE_FILE,
                tg_file_unique_id="note-u",
            )
    return job_id


async def _job(harness: Harness, job_id: UUID) -> MediaJobRow:
    async with harness.sessions() as session:
        job = await load_job(session, job_id)
    assert job is not None
    return job


async def _inputs(harness: Harness, job_id: UUID, role: MediaInputRole) -> list[MediaInputRow]:
    async with harness.sessions() as session:
        rows = await session.scalars(
            sa.select(MediaInputRow).where(
                MediaInputRow.job_id == job_id, MediaInputRow.role == role
            )
        )
        return list(rows.all())


async def _prescreen(harness: Harness, job_id: UUID) -> None:
    await harness.queue.enqueue_job(
        MEDIA_PRESCREEN_JOB, str(job_id), 0, _job_id=prescreen_job_id(job_id)
    )
    await harness.drain()


async def _screen(harness: Harness, job_id: UUID) -> None:
    await harness.queue.enqueue_job(MEDIA_SCREEN_JOB, str(job_id), 0, _job_id=screen_job_id(job_id))
    await harness.drain()


def _last_tray(harness: Harness) -> tuple[str, Any]:
    _, message_id, text, markup = harness.messenger.edits[-1]
    assert message_id == TRAY_ID
    return text, markup


def _actions(markup: Any) -> list[MediaAction]:
    return [
        MediaCB.unpack(button.callback_data).action
        for row in markup.inline_keyboard
        for button in row
    ]


# ---------------------------------------------------------------------------
# media_prescreen (§2.4.1)
# ---------------------------------------------------------------------------
async def test_a_draft_that_passes_the_prescreen_gets_the_shape_screen(harness: Harness) -> None:
    job_id = await _video_row(harness, state=MediaJobState.DRAFTING, photos=2)

    await _prescreen(harness, job_id)

    job = await _job(harness, job_id)
    assert job.state is MediaJobState.DRAFTING
    assert job.screen_decision is MediaScreenDecision.ALLOW
    assert job.screen_policy_version == MEDIA_POLICY_VERSION
    text, markup = _last_tray(harness)
    assert text == translate("media.aspect", Language.EN)
    assert _actions(markup).count(MediaAction.ASPECT) == 3
    assert MediaAction.BACK in _actions(markup) and MediaAction.DROP in _actions(markup)
    # The prompt and both photos were screened; nothing was quoted.
    assert harness.moderator.subjects_screened("text") == ("prompt",)
    assert harness.moderator.subjects_screened("image") == ("upload", "upload")


async def test_a_prompt_the_prescreen_blocks_is_refused_and_struck(harness: Harness) -> None:
    job_id = await _video_row(harness, state=MediaJobState.DRAFTING)
    harness.moderator.decisions["prompt"] = MediaScreenDecision.BLOCK

    await _prescreen(harness, job_id)

    job = await _job(harness, job_id)
    assert job.state is MediaJobState.REJECTED
    assert job.error_code == MediaErrorCode.SCREEN_REFUSED
    assert _last_tray(harness)[0] == translate("media.refused", Language.EN)


async def test_a_busy_guard_at_the_prescreen_leaves_the_draft_for_a_retry(
    harness: Harness,
) -> None:
    job_id = await _video_row(harness, state=MediaJobState.DRAFTING)
    harness.moderator.decisions["prompt"] = MediaScreenDecision.UNAVAILABLE

    await _prescreen(harness, job_id)

    job = await _job(harness, job_id)
    assert job.state is MediaJobState.DRAFTING
    assert job.screen_decision is MediaScreenDecision.UNAVAILABLE
    text, markup = _last_tray(harness)
    assert text == translate("media.busy", Language.EN)
    assert MediaAction.RETRY in _actions(markup)


# ---------------------------------------------------------------------------
# An own voice note (§5.4)
# ---------------------------------------------------------------------------
async def test_a_note_ffprobe_measures_over_the_clip_is_refused_before_payment(
    harness: Harness, probe: ScriptedProbe
) -> None:
    # Telegram said 5 (whole seconds), so the bot let it through; ffprobe says 5.6.
    probe.duration_s = 5.6
    job_id = await _video_row(
        harness, state=MediaJobState.SCREENING, voice_mode=MediaVoiceMode.OWN, voice_note=True
    )

    await _screen(harness, job_id)

    job = await _job(harness, job_id)
    # Back to the draft — not quoted, not terminal, and the prompt kept.
    assert job.state is MediaJobState.DRAFTING
    assert job.quoted_at is None
    assert job.screen_decision is MediaScreenDecision.ALLOW
    assert await _inputs(harness, job_id, MediaInputRole.VOICE_NOTE) == []
    text, markup = _last_tray(harness)
    assert text == translate("media.voice_note.too_long", Language.EN, dur="5.6", seconds=5)
    assert _actions(markup) == [MediaAction.RECORD, MediaAction.CANCEL]
    # Nothing was transcribed and nothing screened.
    assert harness.moderator.calls == []


async def test_a_note_within_the_quarter_second_is_heard_screened_and_quoted(
    harness: Harness, probe: ScriptedProbe
) -> None:
    probe.duration_s = 5.2
    job_id = await _video_row(
        harness, state=MediaJobState.SCREENING, voice_mode=MediaVoiceMode.OWN, voice_note=True
    )

    await _screen(harness, job_id)

    job = await _job(harness, job_id)
    assert job.state is MediaJobState.QUOTED
    assert job.voice_transcript == "happy birthday my dear friend"
    (note,) = await _inputs(harness, job_id, MediaInputRole.VOICE_NOTE)
    assert note.sha256 is not None and note.duration_ms == 5200
    assert note.mime == "audio/ogg"
    assert "transcript" in harness.moderator.subjects_screened("text")
    text, _ = _last_tray(harness)
    assert text.startswith("🎬")
    assert translate("media.voice_mode.own", Language.EN) in text
    assert translate("media.tier_name.standard", Language.EN) in text


@pytest.mark.parametrize(
    ("heard", "voiced"),
    [
        pytest.param({"avg_logprob": -1.3}, 3.5, id="low-avg-logprob"),
        pytest.param({"language": "de"}, 3.5, id="wrong-language"),
        pytest.param({"text": "mm"}, 4.5, id="low-word-rate"),
        pytest.param({"max_compression_ratio": 2.9}, 3.5, id="high-compression"),
        pytest.param({"text": ""}, 3.5, id="empty"),
    ],
)
async def test_a_transcript_whisper_made_up_refuses_the_note(
    harness: Harness, probe: ScriptedProbe, heard: dict[str, Any], voiced: float
) -> None:
    probe.voiced_s = voiced
    harness.moderator.transcript = dataclasses.replace(harness.moderator.transcript, **heard)
    job_id = await _video_row(
        harness, state=MediaJobState.SCREENING, voice_mode=MediaVoiceMode.OWN, voice_note=True
    )

    await _screen(harness, job_id)

    job = await _job(harness, job_id)
    assert job.state is MediaJobState.REJECTED
    assert job.error_code == MediaErrorCode.VOICE_UNTRUSTED
    assert job.screen_decision is MediaScreenDecision.REVIEW
    assert _last_tray(harness)[0] == translate("media.refused", Language.EN)
    # Refused before any guard judged it, and not struck (§6.4: a review is no strike).
    assert harness.moderator.subjects_screened("text") == ()
    assert await harness.strikes.suspension(USER, now=harness.clock()) is None


async def test_a_transcript_too_long_to_store_whole_refuses_the_note(
    harness: Harness, probe: ScriptedProbe
) -> None:
    """L1 screens only the stored transcript (varchar 400): one that would be cut would leave
    its tail in the delivered audio unscreened, so it is refused — never truncated."""
    long_text = "happy birthday my dear friend " * 15
    assert len(long_text) > 400
    harness.moderator.transcript = dataclasses.replace(harness.moderator.transcript, text=long_text)
    job_id = await _video_row(
        harness, state=MediaJobState.SCREENING, voice_mode=MediaVoiceMode.OWN, voice_note=True
    )

    await _screen(harness, job_id)

    job = await _job(harness, job_id)
    assert job.state is MediaJobState.REJECTED
    assert job.error_code == MediaErrorCode.VOICE_UNTRUSTED
    assert job.voice_transcript is None
    assert harness.moderator.subjects_screened("text") == ()
    assert await harness.strikes.suspension(USER, now=harness.clock()) is None


async def test_a_reserved_gpu_at_a_video_quote_cancels_the_row(
    harness: Harness, monkeypatch: pytest.MonkeyPatch
) -> None:
    """§2.4.1: reserved at the quote → ``cancelled`` and ``media.busy`` with no 🔁 — not held
    open in ``screening`` for the whole reserved window."""
    monkeypatch.setattr(media_jobs, "quote_block", lambda *_, **__: QuoteBlock.GPU_RESERVED)
    job_id = await _video_row(harness, state=MediaJobState.SCREENING)

    await _screen(harness, job_id)

    job = await _job(harness, job_id)
    assert job.state is MediaJobState.CANCELLED
    assert job.screen_decision is MediaScreenDecision.ALLOW
    text, markup = _last_tray(harness)
    assert text == translate("media.busy", Language.EN)
    assert markup is None
    assert harness.queue.ran_named(MEDIA_CLEANUP_JOB)


# ---------------------------------------------------------------------------
# The words an AI voice says (§2.4.1, §5.3)
# ---------------------------------------------------------------------------
async def test_an_edited_script_with_a_denylisted_term_is_refused_at_the_screen(
    harness: Harness,
) -> None:
    # A line the writer passed at L3 and the customer then edited (✏️) into this.
    job_id = await _video_row(
        harness,
        state=MediaJobState.SCREENING,
        voice_mode=MediaVoiceMode.AI_LLM,
        narration="happy birthday, now kill them all",
    )

    await _screen(harness, job_id)

    job = await _job(harness, job_id)
    assert job.state is MediaJobState.REJECTED
    assert job.error_code == MediaErrorCode.SCREEN_REFUSED
    assert job.screen_decision is MediaScreenDecision.BLOCK


async def test_a_clean_line_is_screened_as_narration_and_quoted(harness: Harness) -> None:
    job_id = await _video_row(
        harness,
        state=MediaJobState.SCREENING,
        voice_mode=MediaVoiceMode.AI_USER,
        narration="happy birthday Dilnoza",
    )

    await _screen(harness, job_id)

    assert (await _job(harness, job_id)).state is MediaJobState.QUOTED
    assert harness.moderator.subjects_screened("text") == ("prompt", "narration")


async def test_a_line_over_its_languages_budget_is_refused_by_the_backstop(
    harness: Harness,
) -> None:
    # Nine words: inside English's twelve, over Uzbek's eight.
    job_id = await _video_row(
        harness,
        state=MediaJobState.SCREENING,
        voice_mode=MediaVoiceMode.AI_USER,
        narration="bir ikki uch toʻrt besh olti yetti sakkiz toʻqqiz",
        language=Language.UZ_LATN,
    )

    await _screen(harness, job_id)

    job = await _job(harness, job_id)
    assert job.state is MediaJobState.REJECTED
    assert job.error_code == MediaErrorCode.SCREEN_CAPS
    assert harness.moderator.calls == []


async def test_the_sweep_redrives_a_prescreen_whose_enqueue_was_lost(harness: Harness) -> None:
    job_id = await _video_row(harness, state=MediaJobState.DRAFTING)
    harness.clock.advance(minutes=11)

    await sweep_media(harness.rt)
    await harness.drain()

    job = await _job(harness, job_id)
    assert job.screen_decision is MediaScreenDecision.ALLOW
    # A decided draft (allowed, or busy for the customer's 🔁) is left alone.
    ran = len(harness.queue.ran_named(MEDIA_PRESCREEN_JOB))
    harness.clock.advance(minutes=11)
    await sweep_media(harness.rt)
    await harness.drain()
    assert len(harness.queue.ran_named(MEDIA_PRESCREEN_JOB)) == ran
