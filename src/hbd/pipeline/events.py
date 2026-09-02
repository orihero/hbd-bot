"""Progress events. The bot subscribes to these to edit one message in place.

The pipeline never formats user copy: an event carries a ``detail_key`` locale key and a
``step_index`` / ``step_count`` pair, and the bot renders that into whatever language the
user picked. ``ProgressReporter`` is the only thing the pipeline talks to, and it swallows
nothing — a sink that fails is logged with full context and the run carries on, because a
broken progress bar must never destroy a paid-for kit.

The fraction is measured against the stages this run will *actually* enter, not against
every stage that exists. With the shipped default of no spoken greetings two stages are
skipped outright, so a denominator of ``len(STAGE_ORDER)`` promised eleven steps and
delivered nine — the bar could never reach a stage it had already counted. Each event
therefore carries the ``stage_plan`` it was measured against, which keeps the ratio a
property of the event rather than of whoever renders it later.
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
    "GREETING_STAGES",
    "scheduled_stages",
]

_LOGGER = get_logger(__name__)


class PipelineStage(StrEnum):
    """Every step the orchestrator can be inside. Ordered by ``STAGE_ORDER``."""

    VALIDATING = "validating"
    AUTHORIZING = "authorizing"
    MODERATING = "moderating"
    WRITING_LYRICS = "writing_lyrics"
    WRITING_SCRIPTS = "writing_scripts"
    COMPOSING_SONG = "composing_song"
    VERIFYING_NAME = "verifying_name"
    RENDERING_GREETINGS = "rendering_greetings"
    POST_PROCESSING = "post_processing"
    PERSISTING = "persisting"
    DELIVERING = "delivering"


#: Display order. The denominator is a *subset* of this — see ``scheduled_stages``.
#:
#: AUTHORIZING sits SECOND, and that position is a money decision rather than a cosmetic
#: one. It used to come fifth, after MODERATING and WRITING_SCRIPTS, so two LLM calls were
#: already paid for by the time the render gate decided whether this account was allowed a
#: render at all — an account with no credits could still spend vendor money, once per
#: attempt, for as long as it kept confirming. The gate now runs against nothing more
#: expensive than local validation, so a refusal costs a database round trip.
#:
#: Everything after it keeps its relative order, and this tuple is the ONLY place the
#: sequence is written down: ``scheduled_stages`` filters it, ``_position`` measures the
#: progress fraction against it and ``STAGE_MESSAGE_KEYS`` is derived from it, so the bar
#: and the locale keys followed the move with nothing to keep in step by hand.
STAGE_ORDER: Final[tuple[PipelineStage, ...]] = (
    PipelineStage.VALIDATING,
    PipelineStage.AUTHORIZING,
    PipelineStage.MODERATING,
    PipelineStage.WRITING_LYRICS,
    PipelineStage.WRITING_SCRIPTS,
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

#: The two stages that exist only when the kit carries spoken greetings. With
#: ``greetings_per_kit`` at zero the orchestrator skips both rather than running them
#: empty, so counting them would promise the customer work nobody is going to do.
GREETING_STAGES: Final[frozenset[PipelineStage]] = frozenset(
    {PipelineStage.WRITING_SCRIPTS, PipelineStage.RENDERING_GREETINGS}
)


def scheduled_stages(*, has_greetings: bool) -> tuple[PipelineStage, ...]:
    """The stages a run will actually enter, in display order.

    This is the denominator of the progress fraction. Callers pass what the run was
    configured to do (``settings.greetings_per_kit > 0``), never what it has done so far —
    a denominator that changes mid-run is how a bar starts moving backwards.
    """
    if has_greetings:
        return STAGE_ORDER
    return tuple(stage for stage in STAGE_ORDER if stage not in GREETING_STAGES)


def _position(stage: PipelineStage, plan: tuple[PipelineStage, ...]) -> int:
    """How many planned stages come before ``stage``. Total: an unplanned stage still fits.

    A stage the plan skipped can still emit — ``VERIFYING_NAME`` is announced from inside
    the composing wrapper — and a ``KeyError`` in a property the bot renders on every
    frame would take the progress message down, so this counts rather than looks up.
    """
    ordinal = _STAGE_INDEX[stage]
    return sum(1 for planned in plan if _STAGE_INDEX[planned] < ordinal)


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
    #: The stages this run was scheduled to enter. Defaults to all of them so an event
    #: built by hand — a test, a replay off the bus — still reads sensibly.
    stage_plan: tuple[PipelineStage, ...] = STAGE_ORDER

    @property
    def _plan(self) -> tuple[PipelineStage, ...]:
        return self.stage_plan or STAGE_ORDER

    @property
    def step_index(self) -> int:
        """Zero-based position of this stage among the stages this run will enter."""
        return _position(self.stage, self._plan)

    @property
    def step_count(self) -> int:
        return len(self._plan)

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

    Immutable: it holds only the sink, the order id, the correlation id and the stage plan
    this run was scheduled against, and builds a new ``ProgressEvent`` per call.

    ``stage_plan`` is fixed for the life of the reporter on purpose. It is what the run
    intends to do, decided before the first frame, so the denominator the customer is
    watching cannot change underneath them.
    """

    def __init__(
        self,
        sink: ProgressSink,
        *,
        order_id: UUID,
        correlation_id: str,
        stage_plan: tuple[PipelineStage, ...] = STAGE_ORDER,
    ) -> None:
        self._sink = sink
        self._order_id = order_id
        self._correlation_id = correlation_id
        self._stage_plan = stage_plan or STAGE_ORDER

    @property
    def stage_plan(self) -> tuple[PipelineStage, ...]:
        """The stages every event from this reporter is measured against."""
        return self._stage_plan

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
            stage_plan=self._stage_plan,
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
