"""Progress frames: real events in, one edited message out."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

import pytest
from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest
from aiogram.methods import EditMessageText, TelegramMethod

from bayram.bot.i18n import translate
from bayram.bot.progress import (
    EMPTY_BLOCK,
    FILLED_BLOCK,
    PROGRESS_BAR_WIDTH,
    TelegramProgressSink,
    queued_text,
    render_progress,
    timed_out_text,
)
from bayram.contracts import Language
from bayram.pipeline.events import (
    STAGE_MESSAGE_KEYS,
    STAGE_ORDER,
    PipelineStage,
    ProgressEvent,
    ProgressStatus,
    scheduled_stages,
)
from tests.test_bot.conftest import CHAT_ID, RecordingSession

NOW = datetime(2026, 3, 21, 9, 0, tzinfo=UTC)

RECIPIENT = "Gʻulomjon"


def event(
    stage: PipelineStage = PipelineStage.COMPOSING_SONG,
    status: ProgressStatus = ProgressStatus.STARTED,
    *,
    attempt: int = 0,
    stage_plan: tuple[PipelineStage, ...] = STAGE_ORDER,
) -> ProgressEvent:
    return ProgressEvent(
        order_id=uuid4(),
        correlation_id="corr-1",
        stage=stage,
        status=status,
        at=NOW,
        attempt=attempt,
        detail_key=STAGE_MESSAGE_KEYS[stage],
        stage_plan=stage_plan,
    )


def percent(text: str) -> int:
    """The percentage a frame is showing, read back off the screen."""
    return int(text.split("\n")[0].split(" ")[1].rstrip("%"))


def screen_text(call: TelegramMethod[Any]) -> str:
    """The text of a recorded edit, narrowed so a wrong call type fails loudly."""
    assert isinstance(call, EditMessageText)
    return call.text or ""


def sink(bot: Bot, language: Language = Language.EN) -> TelegramProgressSink:
    return TelegramProgressSink(bot, chat_id=CHAT_ID, message_id=99, language=language)


@pytest.mark.parametrize("stage", list(STAGE_ORDER))
@pytest.mark.parametrize("language", list(Language))
def test_every_stage_renders_localised_copy(stage: PipelineStage, language: Language) -> None:
    # Arrange / Act
    text = render_progress(event(stage), language)

    # Assert
    assert translate(STAGE_MESSAGE_KEYS[stage], language) in text
    assert STAGE_MESSAGE_KEYS[stage] not in text  # never the raw key


def test_bar_is_always_the_configured_width() -> None:
    # Arrange / Act
    frames = [render_progress(event(stage), Language.EN) for stage in STAGE_ORDER]

    # Assert
    for frame in frames:
        bar = frame.split(" ")[0]
        assert len(bar) == PROGRESS_BAR_WIDTH
        assert set(bar) <= {FILLED_BLOCK, EMPTY_BLOCK}


def test_progress_only_moves_forward_through_the_stages() -> None:
    # Arrange
    events = [event(stage, ProgressStatus.SUCCEEDED) for stage in STAGE_ORDER]

    # Act
    ratios = [item.progress_ratio for item in events]

    # Assert
    assert ratios == sorted(ratios)
    assert ratios[-1] == pytest.approx(1.0)


def test_failure_frame_says_it_failed() -> None:
    # Arrange / Act
    text = render_progress(event(PipelineStage.COMPOSING_SONG, ProgressStatus.FAILED), Language.EN)

    # Assert
    assert translate("progress.failed", Language.EN) in text


def test_final_delivery_success_says_it_is_ready() -> None:
    # Arrange / Act
    text = render_progress(event(PipelineStage.DELIVERING, ProgressStatus.SUCCEEDED), Language.EN)

    # Assert
    assert translate("progress.done", Language.EN) in text


def test_retry_frame_shows_a_human_attempt_number() -> None:
    # Arrange / Act
    text = render_progress(
        event(PipelineStage.COMPOSING_SONG, ProgressStatus.RETRYING, attempt=1), Language.EN
    )

    # Assert — attempt is zero-based on the wire, one-based on screen
    assert "2" in text


def test_queued_text_is_the_empty_bar() -> None:
    # Arrange / Act
    text = queued_text(Language.EN, name=RECIPIENT)

    # Assert
    assert text.startswith(EMPTY_BLOCK * PROGRESS_BAR_WIDTH)


@pytest.mark.parametrize("language", list(Language))
def test_the_queued_frame_names_the_recipient(language: Language) -> None:
    # Arrange / Act
    text = queued_text(language, name=RECIPIENT)

    # Assert — whose song this is, on the one screen that stays up for minutes
    assert RECIPIENT in text
    assert "{name}" not in text


# ---------------------------------------------------------------------------
# the denominator: only stages this run will actually enter
# ---------------------------------------------------------------------------
def test_skipped_stages_are_not_counted_against_the_customer() -> None:
    # Arrange — the shipped default runs no spoken greetings
    plan = scheduled_stages(has_greetings=False)

    # Act
    frame = render_progress(
        event(PipelineStage.COMPOSING_SONG, ProgressStatus.SUCCEEDED, stage_plan=plan),
        Language.EN,
    )
    full = render_progress(
        event(PipelineStage.COMPOSING_SONG, ProgressStatus.SUCCEEDED), Language.EN
    )

    # Assert — nine real steps, not eleven with two that never happen
    assert len(plan) == len(STAGE_ORDER) - 2
    assert percent(frame) > percent(full)


def test_the_last_scheduled_stage_finishes_at_a_hundred_percent() -> None:
    # Arrange
    plan = scheduled_stages(has_greetings=False)

    # Act
    text = render_progress(
        event(PipelineStage.DELIVERING, ProgressStatus.SUCCEEDED, stage_plan=plan), Language.EN
    )

    # Assert
    assert percent(text) == 100


def test_a_stage_outside_the_plan_still_renders() -> None:
    # Arrange — VERIFYING_NAME is announced from inside the composing wrapper, and a
    # greeting stage can surface on a plan that skipped it. Neither may raise.
    plan = scheduled_stages(has_greetings=False)

    # Act
    text = render_progress(
        event(PipelineStage.RENDERING_GREETINGS, ProgressStatus.STARTED, stage_plan=plan),
        Language.EN,
    )

    # Assert
    assert 0 <= percent(text) <= 100


# ---------------------------------------------------------------------------
# the bar never runs backwards
# ---------------------------------------------------------------------------
async def test_the_bar_never_runs_backwards(bot: Bot, session: RecordingSession) -> None:
    # Arrange — the real emission order: the name check reports from inside composing,
    # so the honest per-event fraction genuinely drops on the next frame.
    plan = scheduled_stages(has_greetings=False)
    target = sink(bot)
    frames = (
        event(PipelineStage.COMPOSING_SONG, ProgressStatus.STARTED, stage_plan=plan),
        event(PipelineStage.VERIFYING_NAME, ProgressStatus.SUCCEEDED, stage_plan=plan),
        event(PipelineStage.COMPOSING_SONG, ProgressStatus.SUCCEEDED, stage_plan=plan),
    )

    # Act
    for frame in frames:
        await target.emit(frame)

    # Assert — the raw events dip; nothing the customer saw did
    assert frames[2].progress_ratio < frames[1].progress_ratio
    shown = [percent(screen_text(call)) for call in session.named("EditMessageText")]
    assert shown == sorted(shown)


async def test_the_clamp_invents_no_progress(bot: Bot, session: RecordingSession) -> None:
    # Arrange
    target = sink(bot)

    # Act
    await target.emit(event(PipelineStage.WRITING_LYRICS, ProgressStatus.STARTED))

    # Assert — exactly what the event said, no rounding it forward
    frame = session.last_named("EditMessageText")
    assert percent(frame.text) == round(
        event(PipelineStage.WRITING_LYRICS, ProgressStatus.STARTED).progress_ratio * 100
    )


async def test_a_failure_after_a_dip_keeps_the_furthest_bar(
    bot: Bot, session: RecordingSession
) -> None:
    # Arrange
    target = sink(bot)
    await target.emit(event(PipelineStage.PERSISTING, ProgressStatus.SUCCEEDED))

    # Act
    await target.emit(event(PipelineStage.COMPOSING_SONG, ProgressStatus.FAILED))

    # Assert — the headline is the failure; the bar stays where the run got to
    frame = session.last_named("EditMessageText")
    assert translate("progress.failed", Language.EN) in frame.text
    assert percent(frame.text) == round(target.high_water * 100)


# ---------------------------------------------------------------------------
# the queue timeout
# ---------------------------------------------------------------------------
async def test_a_cancelled_run_gets_one_terminal_frame(bot: Bot, session: RecordingSession) -> None:
    # Arrange
    target = sink(bot)
    await target.emit(event(PipelineStage.COMPOSING_SONG, ProgressStatus.STARTED))
    session.clear()

    # Act
    await target.emit_timed_out()

    # Assert
    edits = session.named("EditMessageText")
    assert len(edits) == 1
    assert translate("progress.timed_out", Language.EN) in screen_text(edits[0])


@pytest.mark.parametrize("language", list(Language))
def test_the_timed_out_frame_never_claims_the_song_is_ready(language: Language) -> None:
    # Arrange / Act
    text = timed_out_text(language, ratio=0.5)

    # Assert
    assert translate("progress.timed_out", language) in text
    assert translate("progress.done", language) not in text
    assert percent(text) == 50


async def test_the_timed_out_frame_survives_telegram_refusing_it(
    bot: Bot, session: RecordingSession
) -> None:
    # Arrange
    session.failures["EditMessageText"] = TelegramBadRequest(
        method=EditMessageText(chat_id=CHAT_ID, message_id=99, text="x"), message="boom"
    )
    target = sink(bot)

    # Act — a dying job must not die twice
    await target.emit_timed_out()

    # Assert
    assert target.last_text is None


async def test_sink_edits_the_message_in_place(bot: Bot, session: RecordingSession) -> None:
    # Arrange
    reporter = sink(bot)

    # Act
    await reporter.emit(event(PipelineStage.WRITING_LYRICS))

    # Assert
    edit = session.last_named("EditMessageText")
    assert isinstance(edit, EditMessageText)
    assert edit.message_id == 99
    assert edit.chat_id == CHAT_ID


async def test_sink_never_sends_the_same_frame_twice(bot: Bot, session: RecordingSession) -> None:
    # Arrange
    reporter = sink(bot)
    same = event(PipelineStage.WRITING_LYRICS)

    # Act
    await reporter.emit(same)
    await reporter.emit(same)

    # Assert
    assert len(session.named("EditMessageText")) == 1


async def test_sink_swallows_a_telegram_rejection(bot: Bot, session: RecordingSession) -> None:
    # Arrange
    session.failures["EditMessageText"] = TelegramBadRequest(
        method=EditMessageText(chat_id=CHAT_ID, message_id=99, text="x"),
        message="message is not modified",
    )
    reporter = sink(bot)

    # Act — must not raise: a broken progress bar cannot kill a paid run
    await reporter.emit(event())

    # Assert
    assert reporter.last_text is None


async def test_sink_retries_the_next_frame_after_a_rejection(
    bot: Bot, session: RecordingSession
) -> None:
    # Arrange
    session.failures["EditMessageText"] = TelegramBadRequest(
        method=EditMessageText(chat_id=CHAT_ID, message_id=99, text="x"), message="boom"
    )
    reporter = sink(bot)
    await reporter.emit(event(PipelineStage.WRITING_LYRICS))
    session.failures.clear()

    # Act
    await reporter.emit(event(PipelineStage.COMPOSING_SONG))

    # Assert
    assert reporter.last_text is not None
    assert len(session.named("EditMessageText")) == 2
