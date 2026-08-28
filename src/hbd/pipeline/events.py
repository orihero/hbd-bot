"""Progress events. The bot subscribes to these to edit one message in place.

The pipeline never formats user copy: an event carries a ``detail_key`` locale key and a
``step_index`` / ``step_count`` pair, and the bot renders that into whatever language the
user picked. ``ProgressReporter`` is the only thing the pipeline talks to, and it swallows
nothing — a sink that fails is logged with full context and the run carries on, because a
broken progress bar must never destroy a paid-for kit.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any, Final, Protocol, runtime_checkable
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from hbd.errors import ErrorCode, HbdError
from hbd.logging import get_logger

__all__ = [
    "PipelineStage",
    "ProgressStatus",
    "ProgressEvent",
    "ProgressSink",
    "NullProgressSink",
    "ProgressReporter",
    "STAGE_ORDER",
    "STAGE_MESSAGE_KEYS",
]

_LOGGER = get_logger(__name__)


class PipelineStage(StrEnum):
    """Every step the orchestrator can be inside. Ordered by ``STAGE_ORDER``."""

    VALIDATING = "validating"
    MODERATING = "moderating"
    WRITING_LYRICS = "writing_lyrics"
    WRITING_SCRIPTS = "writing_scripts"
    AUTHORIZING = "authorizing"
    COMPOSING_SONG = "composing_song"
    VERIFYING_NAME = "verifying_name"
    RENDERING_GREETINGS = "rendering_greetings"
    POST_PROCESSING = "post_processing"
    PERSISTING = "persisting"
    DELIVERING = "delivering"


#: Display order, and the denominator of the progress fraction the bot shows.
STAGE_ORDER: Final[tuple[PipelineStage, ...]] = (
    PipelineStage.VALIDATING,
    PipelineStage.MODERATING,
    PipelineStage.WRITING_LYRICS,
    PipelineStage.WRITING_SCRIPTS,
    PipelineStage.AUTHORIZING,
    PipelineStage.COMPOSING_SONG,
    PipelineStage.VERIFYING_NAME,
    PipelineStage.RENDERING_GREETINGS,
    PipelineStage.POST_PROCESSING,
    PipelineStage.PERSISTING,
    PipelineStage.DELIVERING,
)

#: Locale keys the four catalogues must define. The pipeline never emits raw copy.
STAGE_MESSAGE_KEYS: Final[dict[PipelineStage, str]] = {
    stage: f"progress.{stage.value}" for stage in STAGE_ORDER
}

_STAGE_INDEX: Final[dict[PipelineStage, int]] = {
    stage: index for index, stage in enumerate(STAGE_ORDER)
}


class ProgressStatus(StrEnum):
    STARTED = "started"
    RETRYING = "retrying"
    SUCCEEDED = "succeeded"
    DEGRADED = "degraded"
    FAILED = "failed"
    SKIPPED = "skipped"


class ProgressEvent(BaseModel):
    """One immutable observation of the run. Safe to serialise straight onto a bus."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    order_id: UUID
    correlation_id: str = Field(min_length=1)
    stage: PipelineStage
    status: ProgressStatus
    at: datetime
    attempt: int = Field(default=0, ge=0)
    detail_key: str = Field(min_length=1)
    error_code: ErrorCode | None = None
    context: dict[str, str] = Field(default_factory=dict)

    @property
    def step_index(self) -> int:
        """Zero-based position of this stage in ``STAGE_ORDER``."""
        return _STAGE_INDEX[self.stage]

    @property
    def step_count(self) -> int:
        return len(STAGE_ORDER)

    @property
    def progress_ratio(self) -> float:
        """0.0 to 1.0, counting a succeeded stage as complete."""
        done = self.step_index + (1 if self.status is ProgressStatus.SUCCEEDED else 0)
        return min(1.0, done / self.step_count)


@runtime_checkable
class ProgressSink(Protocol):
    """Where events go. Implemented by the bot layer (Redis pub/sub, in practice)."""

    async def emit(self, event: ProgressEvent) -> None: ...


class NullProgressSink:
    """Drops events. The default when nobody is watching (a replay, a test)."""

    async def emit(self, event: ProgressEvent) -> None:
        return None


class ProgressReporter:
    """Binds an order to a sink and guarantees the pipeline cannot be killed by it.

    Immutable: it holds only the sink, the order id and the correlation id, and builds a
    new ``ProgressEvent`` per call.
    """

    def __init__(
        self,
        sink: ProgressSink,
        *,
        order_id: UUID,
        correlation_id: str,
    ) -> None:
        self._sink = sink
        self._order_id = order_id
        self._correlation_id = correlation_id

    async def emit(
        self,
        stage: PipelineStage,
        status: ProgressStatus,
        *,
        now: datetime,
        attempt: int = 0,
        error: HbdError | None = None,
        **context: str,
    ) -> ProgressEvent:
        """Build and publish an event. Returns it so callers can assert on it."""
        event = ProgressEvent(
            order_id=self._order_id,
            correlation_id=self._correlation_id,
            stage=stage,
            status=status,
            at=now,
            attempt=attempt,
            detail_key=STAGE_MESSAGE_KEYS[stage],
            error_code=error.error_code if error is not None else None,
            context=dict(context),
        )
        await self._publish(event)
        return event

    async def _publish(self, event: ProgressEvent) -> None:
        try:
            await self._sink.emit(event)
        except Exception as exc:
            detail: dict[str, Any] = {
                "order_id": str(self._order_id),
                "stage": event.stage.value,
                "status": event.status.value,
                "sink": type(self._sink).__name__,
                "failure": repr(exc),
            }
            _LOGGER.warning("progress sink rejected an event", extra=detail)
