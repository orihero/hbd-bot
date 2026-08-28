"""Progress frames: real events in, one edited message out."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest
from aiogram.methods import EditMessageText

from hbd.bot.i18n import translate
from hbd.bot.progress import (
    EMPTY_BLOCK,
    FILLED_BLOCK,
    PROGRESS_BAR_WIDTH,
    TelegramProgressSink,
    queued_text,
    render_progress,
)
from hbd.contracts import Language
from hbd.pipeline.events import (
    STAGE_MESSAGE_KEYS,
    STAGE_ORDER,
    PipelineStage,
    ProgressEvent,
    ProgressStatus,
)
from tests.test_bot.conftest import CHAT_ID, RecordingSession

NOW = datetime(2026, 3, 21, 9, 0, tzinfo=UTC)


def event(
    stage: PipelineStage = PipelineStage.COMPOSING_SONG,
    status: ProgressStatus = ProgressStatus.STARTED,
    *,
    attempt: int = 0,
) -> ProgressEvent:
    return ProgressEvent(
        order_id=uuid4(),
        correlation_id="corr-1",
        stage=stage,
        status=status,
        at=NOW,
        attempt=attempt,
        detail_key=STAGE_MESSAGE_KEYS[stage],
    )


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
    text = queued_text(Language.EN)

    # Assert
    assert text.startswith(EMPTY_BLOCK * PROGRESS_BAR_WIDTH)


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


async def test_sink_never_sends_the_same_frame_twice(
    bot: Bot, session: RecordingSession
) -> None:
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
