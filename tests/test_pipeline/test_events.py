"""Progress events carry locale keys and a fraction — never copy, never a crash."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from hbd.errors import ProviderTimeoutError
from hbd.pipeline.events import (
    STAGE_MESSAGE_KEYS,
    STAGE_ORDER,
    NullProgressSink,
    PipelineStage,
    ProgressReporter,
    ProgressStatus,
)
from tests.test_pipeline.conftest import RecordingSink

NOW = datetime(2026, 3, 21, 9, 0, tzinfo=UTC)


def _reporter(sink: RecordingSink | NullProgressSink) -> ProgressReporter:
    return ProgressReporter(sink, order_id=uuid4(), correlation_id="corr-1")


async def test_emits_an_event_carrying_the_stage_locale_key() -> None:
    # Arrange
    sink = RecordingSink()
    reporter = _reporter(sink)

    # Act
    event = await reporter.emit(PipelineStage.WRITING_LYRICS, ProgressStatus.STARTED, now=NOW)

    # Assert
    assert event.detail_key == STAGE_MESSAGE_KEYS[PipelineStage.WRITING_LYRICS]
    assert sink.events == [event]


async def test_progress_ratio_counts_a_succeeded_stage_as_complete() -> None:
    # Arrange
    reporter = _reporter(NullProgressSink())

    # Act
    started = await reporter.emit(PipelineStage.VALIDATING, ProgressStatus.STARTED, now=NOW)
    finished = await reporter.emit(PipelineStage.DELIVERING, ProgressStatus.SUCCEEDED, now=NOW)

    # Assert
    assert started.progress_ratio == 0.0
    assert finished.progress_ratio == 1.0
    assert finished.step_count == len(STAGE_ORDER)


async def test_failure_events_carry_the_error_code_but_no_vendor_text() -> None:
    # Arrange
    reporter = _reporter(RecordingSink())
    error = ProviderTimeoutError("elevenlabs took 400 seconds", provider="elevenlabs")

    # Act
    event = await reporter.emit(
        PipelineStage.COMPOSING_SONG, ProgressStatus.FAILED, now=NOW, error=error
    )

    # Assert
    assert event.error_code is error.error_code
    assert "elevenlabs" not in event.detail_key


async def test_a_sink_that_raises_does_not_break_the_run() -> None:
    # Arrange
    sink = RecordingSink()
    sink.should_raise = True
    reporter = _reporter(sink)

    # Act
    event = await reporter.emit(PipelineStage.PERSISTING, ProgressStatus.STARTED, now=NOW)

    # Assert
    assert event.stage is PipelineStage.PERSISTING
    assert sink.events == []


async def test_context_keys_reach_the_event_verbatim() -> None:
    # Arrange
    reporter = _reporter(RecordingSink())

    # Act
    event = await reporter.emit(
        PipelineStage.VERIFYING_NAME,
        ProgressStatus.RETRYING,
        now=NOW,
        attempt=2,
        strategy="hyphenated",
    )

    # Assert
    assert event.attempt == 2
    assert event.context == {"strategy": "hyphenated"}


def test_every_stage_has_a_locale_key() -> None:
    # Arrange / Act / Assert
    assert set(STAGE_MESSAGE_KEYS) == set(STAGE_ORDER)
    assert all(key.startswith("progress.") for key in STAGE_MESSAGE_KEYS.values())
