"""A video from payment to delivery, and the 🤖 script writer (IMAGE_VIDEO_SPEC §3.3, §5; M4.3).

Over the fakes of ``media_fakes``: the fake render (a real, vendored 5.06 s clip), the fake
narration (silent WAV), a :class:`FakeVideoTools` in ffmpeg's place and a scripted writer. The
§10 M4.3 acceptance tests that need the stage chain:

* **the fan-in fires once regardless of order** — narration first or render first, the mux
  runs exactly once, and a late second call changes nothing;
* a silent video is re-wrapped, screened frame by frame and delivered by ``sendVideo``;
* an AI voice is spoken, muxed (``atempo`` allowed) and delivered; an own note is prepared
  from the SCREENED copy and muxed as-is (no speed-up);
* a line that runs long is asked for again, brisk; a vendor refusal fails the job with a
  strike; a lost voice or mux is re-driven by the sweep;
* the writer: the prescreened prompt only, L3 on every line, a refused line written again,
  a writer or guard that cannot answer leaves no line and says so.

The real ffmpeg (mux output duration = video duration) is ``test_media_mux.py``.
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

from bayram.bot.callbacks import MediaCB, ScriptPick
from bayram.bot.i18n import translate
from bayram.config import Settings
from bayram.contracts import (
    CostSource,
    Language,
    NarrationRequest,
    ProviderHealth,
    RenderedAudio,
    Result,
    err,
    ok,
)
from bayram.db.engine import create_session_factory
from bayram.db.enums import (
    MediaAspect,
    MediaInputRole,
    MediaJobState,
    MediaKind,
    MediaOutputRole,
    MediaScreenDecision,
    MediaSku,
    MediaTier,
    MediaVoiceGender,
    MediaVoiceMode,
)
from bayram.db.media import add_input, create_job, load_job
from bayram.db.models import Base, UserRow
from bayram.db.models.media_input import MediaOutputRow
from bayram.db.models.media_job import MediaJobRow
from bayram.errors import ProviderRejectedContentError, ProviderUnavailableError
from bayram.media.mux import AudioFit, audio_fit
from bayram.media.service import BetaStart, start_free_beta
from bayram.media.stages import (
    MEDIA_FETCH_JOB,
    MEDIA_MUX_JOB,
    MEDIA_SCREEN_JOB,
    MEDIA_SCRIPT_JOB,
    MEDIA_TTS_JOB,
    MEDIA_VOICE_PREPARE_JOB,
    screen_job_id,
    script_job_id,
)
from bayram.media.voice_probe import VoiceMeasure
from bayram.moderation.contracts import MEDIA_POLICY_VERSION, VoiceTranscript
from bayram.moderation.strikes import OUTPUT_BLOCK_STRIKES
from bayram.providers.tts.fakes import silent_wav
from bayram.runtime.media_jobs import MediaErrorCode, video_fan_in
from bayram.runtime.media_sweep import STALE_HEARTBEAT, sweep_media
from tests.conftest import FIXED_NOW
from tests.test_runtime.media_fakes import (
    PROMPT,
    TRAY_ID,
    USER,
    Harness,
    QueuedStage,
    build_harness,
    media_settings,
)

_NOTE_FILE: Final[str] = "voice-file-1"
_OGG: Final[bytes] = b"OggS" + b"\x00" * 64
_LINE: Final[str] = "Happy birthday, dear friend"


@dataclasses.dataclass
class _Probe:
    duration_s: float = 4.0
    voiced_s: float = 3.5

    async def measure(self, path: Path) -> Result[VoiceMeasure]:
        return ok(VoiceMeasure(duration_s=self.duration_s, voiced_s=self.voiced_s))


@dataclasses.dataclass
class _ScriptedNarration:
    """A narration vendor whose lines last :attr:`seconds` in turn, or that refuses."""

    seconds: list[float] = dataclasses.field(default_factory=lambda: [3.0])
    refuse: bool = False
    down: bool = False
    name: str = "scripted_narration"
    requests: list[tuple[NarrationRequest, str]] = dataclasses.field(default_factory=list)

    async def narrate(
        self, request: NarrationRequest, *, idempotency_key: str, timeout_s: float
    ) -> Result[RenderedAudio]:
        self.requests.append((request, idempotency_key))
        if self.refuse:
            return err(ProviderRejectedContentError("SAFETY", provider=self.name))
        if self.down:
            return err(ProviderUnavailableError("down", provider=self.name))
        seconds = self.seconds[min(len(self.requests), len(self.seconds)) - 1]
        return ok(
            RenderedAudio(
                data=silent_wav(seconds),
                mime="audio/wav",
                duration_s=seconds,
                cost_usd=0.0,
                cost_source=CostSource.ESTIMATED,
            )
        )

    async def health(self) -> Result[ProviderHealth]:  # pragma: no cover - unused
        raise NotImplementedError


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
def harness(
    settings: Settings, sessions: async_sessionmaker[AsyncSession], tmp_path: Path
) -> Harness:
    built = build_harness(
        media_settings(settings, is_video_standard_offered=True, video_standard_backend="fake"),
        sessions,
        tmp_path,
        FIXED_NOW,
    )
    built.rt = dataclasses.replace(built.rt, voice_probe=_Probe())
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
    state: MediaJobState = MediaJobState.SCREENING,
    voice_mode: MediaVoiceMode = MediaVoiceMode.NONE,
    narration: str | None = None,
    gender: MediaVoiceGender | None = None,
    voice_note: bool = False,
    prescreened: bool = False,
) -> UUID:
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
            language=Language.EN,
            prompt=PROMPT,
            price_minor=2_500_000,
            currency="UZS",
            now=now,
            quote_ttl=timedelta(seconds=86_400),
            tier=MediaTier.STANDARD,
            voice_mode=voice_mode,
            voice_gender=gender,
            narration_text=narration,
            tray_message_id=TRAY_ID,
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
        if prescreened:
            await session.execute(
                sa.update(MediaJobRow)
                .where(MediaJobRow.id == job_id)
                .values(
                    screen_decision=MediaScreenDecision.ALLOW,
                    screen_policy_version=MEDIA_POLICY_VERSION,
                )
            )
    return job_id


async def _job(harness: Harness, job_id: UUID) -> MediaJobRow:
    async with harness.sessions() as session:
        job = await load_job(session, job_id)
    assert job is not None
    return job


async def _outputs(harness: Harness, job_id: UUID) -> dict[MediaOutputRole, MediaOutputRow]:
    async with harness.sessions() as session:
        rows = await session.scalars(
            sa.select(MediaOutputRow).where(MediaOutputRow.job_id == job_id)
        )
        return {row.role: row for row in rows.all()}


async def _drain_holding(harness: Harness, name: str) -> None:
    """Run every queued stage except ``name``'s, which wait at the back until the next drain."""
    held: list[QueuedStage] = []
    while True:
        await harness.drain(stop=lambda stage: stage.name == name)
        if not harness.queue.pending:
            break
        held.append(harness.queue.pending.popleft())
    harness.queue.pending.extend(held)


async def _quote_and_start(harness: Harness, job_id: UUID) -> None:
    """``media_screen`` → the quote → 🎁 (the free beta), with the start queued."""
    await harness.queue.enqueue_job(MEDIA_SCREEN_JOB, str(job_id), 0, _job_id=screen_job_id(job_id))
    await harness.drain()
    assert (await _job(harness, job_id)).state is MediaJobState.QUOTED
    outcome = await start_free_beta(
        harness.sessions,
        harness.queue,
        harness.rt.settings,
        job_id=job_id,
        telegram_user_id=USER,
        is_paused=False,
        now=harness.clock(),
    )
    assert outcome is BetaStart.STARTED


# ---------------------------------------------------------------------------
# Whole runs
# ---------------------------------------------------------------------------
async def test_a_silent_video_is_rewrapped_screened_by_frames_and_sent_as_a_video(
    harness: Harness,
) -> None:
    job_id = await _video_row(harness)

    await _quote_and_start(harness, job_id)
    await harness.drain()

    job = await _job(harness, job_id)
    assert job.state is MediaJobState.DELIVERED, (job.state, job.error_code)
    assert job.render_ready_at is not None and job.audio_ready_at is None
    # No voice: no narration, the clip re-wrapped rather than muxed (§5.6).
    assert harness.queue.ran_named(MEDIA_TTS_JOB) == []
    assert len(harness.video.rewraps) == 1 and harness.video.muxes == []
    # L4 looked at frames of the clip (§6.4).
    assert "output_frame" in harness.moderator.subjects_screened("image")
    # Delivered by sendVideo with the measured shape and the video caption.
    assert len(harness.messenger.videos) == 1 and harness.messenger.albums == []
    sent = harness.messenger.videos[0]
    assert (sent.width, sent.height) == (144, 256)
    assert sent.duration_s == pytest.approx(5.0625, abs=0.001)
    assert sent.caption == translate("media.video.delivered", Language.EN)
    # The delivered clip stays on its clock; the render intermediate went with the cleanup.
    outputs = await _outputs(harness, job_id)
    assert set(outputs) == {MediaOutputRole.VIDEO}
    assert outputs[MediaOutputRole.VIDEO].tg_file_id == "tg-video-1"


async def test_an_ai_voice_is_spoken_muxed_and_delivered(harness: Harness) -> None:
    job_id = await _video_row(
        harness,
        voice_mode=MediaVoiceMode.AI_USER,
        narration=_LINE,
        gender=MediaVoiceGender.FEMALE,
    )

    await _quote_and_start(harness, job_id)
    await harness.drain()

    job = await _job(harness, job_id)
    assert job.state is MediaJobState.DELIVERED, (job.state, job.error_code)
    assert job.audio_ready_at is not None and job.render_ready_at is not None
    (call,) = harness.narration.calls
    assert call.request.text == _LINE
    assert call.request.language is Language.EN
    assert call.request.gender.value == "female"
    assert call.request.style is None
    (mux,) = harness.video.muxes
    assert mux[2] is True  # an AI voice may be sped up by ≤ 15 % (§5.3)
    assert len(harness.messenger.videos) == 1
    assert len(harness.queue.ran_named(MEDIA_MUX_JOB)) == 1


async def test_an_own_voice_note_is_prepared_from_the_screened_copy_and_never_sped_up(
    harness: Harness,
) -> None:
    job_id = await _video_row(harness, voice_mode=MediaVoiceMode.OWN, voice_note=True)
    await _quote_and_start(harness, job_id)
    # The note was screened and stored; Telegram must not be asked for it again.
    harness.messenger.files.pop(_NOTE_FILE)

    await harness.drain()

    job = await _job(harness, job_id)
    assert job.state is MediaJobState.DELIVERED, (job.state, job.error_code)
    assert len(harness.queue.ran_named(MEDIA_VOICE_PREPARE_JOB)) == 1
    assert harness.queue.ran_named(MEDIA_TTS_JOB) == []
    (mux,) = harness.video.muxes
    assert mux[2] is False  # muxed as-is: trimmed with a fade, never sped up (§5.4)
    assert harness.narration.calls == ()


@pytest.mark.parametrize("voice_first", [True, False], ids=["voice-first", "render-first"])
async def test_the_fan_in_fires_once_whichever_finishes_second(
    harness: Harness, voice_first: bool
) -> None:
    job_id = await _video_row(
        harness,
        voice_mode=MediaVoiceMode.AI_USER,
        narration=_LINE,
        gender=MediaVoiceGender.MALE,
    )
    await _quote_and_start(harness, job_id)
    held = MEDIA_FETCH_JOB if voice_first else MEDIA_TTS_JOB

    # Run everything but the held producer; the fan-in must not fire on one of two.
    await _drain_holding(harness, held)
    job = await _job(harness, job_id)
    assert job.state is not MediaJobState.POST
    assert harness.queue.ran_named(MEDIA_MUX_JOB) == []
    ready = job.audio_ready_at if voice_first else job.render_ready_at
    assert ready is not None

    await harness.drain(duplicate=True)

    job = await _job(harness, job_id)
    assert job.state is MediaJobState.DELIVERED, (job.state, job.error_code)
    assert len(harness.queue.ran_named(MEDIA_MUX_JOB)) == 1
    assert len(harness.video.muxes) == 1
    assert len(harness.messenger.videos) == 1
    # A producer that reports again, late, changes nothing.
    assert await video_fan_in(harness.rt, job_id) is False


# ---------------------------------------------------------------------------
# The voice leg
# ---------------------------------------------------------------------------
async def test_a_line_that_runs_long_is_asked_for_again_brisk_and_the_shorter_kept(
    harness: Harness,
) -> None:
    narration = _ScriptedNarration(seconds=[6.5, 5.2])
    harness.rt = dataclasses.replace(harness.rt, narration=narration)
    job_id = await _video_row(
        harness, voice_mode=MediaVoiceMode.AI_USER, narration=_LINE, gender=MediaVoiceGender.MALE
    )

    await _quote_and_start(harness, job_id)
    await harness.drain()

    assert (await _job(harness, job_id)).state is MediaJobState.DELIVERED
    assert [req.style for req, _ in narration.requests] == [None, "brisk"]
    assert narration.requests[1][1].endswith(":brisk")
    narr = (await _outputs(harness, job_id)).get(MediaOutputRole.NARRATION)
    # The intermediate went with the cleanup; what was muxed was the brisk take.
    assert narr is None
    assert audio_fit(5.2, 5.0625, may_speed_up=True) is AudioFit.TEMPO


async def test_a_vendor_refusal_of_the_line_fails_the_job_and_strikes(harness: Harness) -> None:
    harness.rt = dataclasses.replace(harness.rt, narration=_ScriptedNarration(refuse=True))
    job_id = await _video_row(
        harness, voice_mode=MediaVoiceMode.AI_LLM, narration=_LINE, gender=MediaVoiceGender.MALE
    )

    await _quote_and_start(harness, job_id)
    await harness.drain()

    job = await _job(harness, job_id)
    assert job.state is MediaJobState.FAILED
    assert job.error_code == MediaErrorCode.NARRATION_REFUSED.value
    assert harness.messenger.videos == []
    assert len(harness.strikes.strikes.get(USER, {})) == OUTPUT_BLOCK_STRIKES  # §6.4 L5
    assert harness.queue.ran_named(MEDIA_MUX_JOB) == []


async def test_a_voice_that_cannot_be_made_is_retried_then_fails_without_a_strike(
    harness: Harness,
) -> None:
    harness.rt = dataclasses.replace(harness.rt, narration=_ScriptedNarration(down=True))
    job_id = await _video_row(
        harness, voice_mode=MediaVoiceMode.AI_USER, narration=_LINE, gender=MediaVoiceGender.MALE
    )

    await _quote_and_start(harness, job_id)
    await harness.drain()

    job = await _job(harness, job_id)
    assert job.state is MediaJobState.FAILED
    assert job.error_code == MediaErrorCode.NARRATION_FAILED.value
    assert len(harness.queue.ran_named(MEDIA_TTS_JOB)) == 3  # MEDIA_STAGE_MAX_TRIES
    assert harness.strikes.strikes.get(USER, {}) == {}


async def test_the_sweep_redrives_a_lost_narration_and_a_lost_mux(harness: Harness) -> None:
    job_id = await _video_row(
        harness, voice_mode=MediaVoiceMode.AI_USER, narration=_LINE, gender=MediaVoiceGender.MALE
    )
    await _quote_and_start(harness, job_id)
    # The narration's enqueue is lost: the render finishes alone.
    await harness.drain(stop=lambda stage: stage.name == MEDIA_TTS_JOB)
    harness.queue.pending.clear()
    assert (await _job(harness, job_id)).state is MediaJobState.GENERATING

    harness.clock.advance(seconds=STALE_HEARTBEAT.total_seconds() + 60)
    await sweep_media(harness.rt, now=harness.clock())
    # The voice arrives; the fan-in fires; this time the mux's enqueue is lost.
    await harness.drain(stop=lambda stage: stage.name == MEDIA_MUX_JOB)
    harness.queue.pending.clear()
    assert (await _job(harness, job_id)).state is MediaJobState.POST

    harness.clock.advance(minutes=30)
    await sweep_media(harness.rt, now=harness.clock())
    await harness.drain()

    assert (await _job(harness, job_id)).state is MediaJobState.DELIVERED
    assert len(harness.messenger.videos) == 1


async def test_a_mux_that_keeps_failing_fails_the_job(harness: Harness) -> None:
    from bayram.errors import AudioProcessingError

    harness.video.failures.extend(AudioProcessingError(f"ffmpeg exited 1 ({n})") for n in range(3))
    job_id = await _video_row(harness)

    await _quote_and_start(harness, job_id)
    await harness.drain()

    job = await _job(harness, job_id)
    assert job.state is MediaJobState.FAILED
    assert job.error_code == MediaErrorCode.MUX_FAILED.value
    assert len(harness.queue.ran_named(MEDIA_MUX_JOB)) == 3


# ---------------------------------------------------------------------------
# media_script (§5.5)
# ---------------------------------------------------------------------------
async def _ask_script(harness: Harness, job_id: UUID, n: int = 0) -> dict[str, Any]:
    return await harness.run(MEDIA_SCRIPT_JOB, str(job_id), n)


def _tray(harness: Harness) -> tuple[str, list[ScriptPick]]:
    _, message_id, text, markup = harness.messenger.edits[-1]
    assert message_id == TRAY_ID and markup is not None
    picks = []
    for row in markup.inline_keyboard:
        for button in row:
            unpacked = MediaCB.unpack(button.callback_data or "")
            if unpacked.arg in {pick.value for pick in ScriptPick}:
                picks.append(ScriptPick(unpacked.arg))
    return text, picks


async def test_the_writer_writes_from_the_prescreened_prompt_and_l3_screens_the_line(
    harness: Harness,
) -> None:
    job_id = await _video_row(
        harness,
        state=MediaJobState.DRAFTING,
        voice_mode=MediaVoiceMode.AI_LLM,
        gender=MediaVoiceGender.FEMALE,
        prescreened=True,
    )

    result = await _ask_script(harness, job_id)

    assert result["outcome"] == "script_written"
    (call,) = harness.writer.calls
    assert call[0] == PROMPT and call[1] is Language.EN
    assert (call[2].words, call[2].chars) == (12, 80)
    assert harness.moderator.subjects_screened("text") == ("script",)
    job = await _job(harness, job_id)
    assert job.state is MediaJobState.DRAFTING and job.narration_text == _LINE
    text, picks = _tray(harness)
    assert text == translate("media.voice.script_review", Language.EN, script=_LINE)
    assert picks == [ScriptPick.USE, ScriptPick.EDIT, ScriptPick.ANOTHER]


async def test_a_line_l3_refuses_is_written_again_and_never_shown(harness: Harness) -> None:
    harness.writer.lines = ["a line the guard refuses", _LINE]
    harness.moderator.decisions["script"] = MediaScreenDecision.BLOCK
    job_id = await _video_row(
        harness,
        state=MediaJobState.DRAFTING,
        voice_mode=MediaVoiceMode.AI_LLM,
        gender=MediaVoiceGender.MALE,
        prescreened=True,
    )

    result = await _ask_script(harness, job_id)

    # Both tries were refused: no line is stored or shown, and ✏️ is offered instead of ✅.
    assert result["outcome"] == "script_failed"
    assert len(harness.writer.calls) == 2
    assert (await _job(harness, job_id)).narration_text is None
    text, picks = _tray(harness)
    assert text == translate("media.voice.script_failed", Language.EN)
    assert ScriptPick.USE not in picks and ScriptPick.EDIT in picks


async def test_the_last_regeneration_gets_one_try_and_no_more_regenerations(
    harness: Harness,
) -> None:
    job_id = await _video_row(
        harness,
        state=MediaJobState.DRAFTING,
        voice_mode=MediaVoiceMode.AI_LLM,
        gender=MediaVoiceGender.MALE,
        prescreened=True,
    )
    last = harness.rt.settings.media_script_max_regens

    await _ask_script(harness, job_id, last)

    _, picks = _tray(harness)
    assert picks == [ScriptPick.USE, ScriptPick.EDIT]


async def test_a_writer_or_guard_that_cannot_answer_leaves_no_line(harness: Harness) -> None:
    job_id = await _video_row(
        harness,
        state=MediaJobState.DRAFTING,
        voice_mode=MediaVoiceMode.AI_LLM,
        gender=MediaVoiceGender.MALE,
        prescreened=True,
    )
    harness.moderator.decisions["script"] = MediaScreenDecision.UNAVAILABLE

    guard_down = await _ask_script(harness, job_id)
    harness.moderator.decisions.clear()
    harness.writer.failure = ProviderUnavailableError("gateway and D5 both down", provider="x")
    writer_down = await _ask_script(harness, job_id, 1)

    assert guard_down["outcome"] == writer_down["outcome"] == "script_failed"
    assert (await _job(harness, job_id)).narration_text is None
    assert (await _job(harness, job_id)).state is MediaJobState.DRAFTING


async def test_the_writer_never_reads_a_prompt_the_prescreen_did_not_allow(
    harness: Harness,
) -> None:
    job_id = await _video_row(
        harness,
        state=MediaJobState.DRAFTING,
        voice_mode=MediaVoiceMode.AI_LLM,
        gender=MediaVoiceGender.MALE,
        prescreened=False,
    )

    result = await _ask_script(harness, job_id)

    assert result["outcome"] == "noop_not_prescreened"
    assert harness.writer.calls == []


async def test_each_line_counts_against_the_screening_budget(harness: Harness) -> None:
    job_id = await _video_row(
        harness,
        state=MediaJobState.DRAFTING,
        voice_mode=MediaVoiceMode.AI_LLM,
        gender=MediaVoiceGender.MALE,
        prescreened=True,
    )

    for n in range(2):
        async with harness.sessions.begin() as session:
            await session.execute(
                sa.update(MediaJobRow).where(MediaJobRow.id == job_id).values(narration_text=None)
            )
        await _ask_script(harness, job_id, n)

    assert await harness.strikes.screens_today(USER, now=harness.clock()) == 2
    assert script_job_id(job_id, 1).endswith(":script:1")
