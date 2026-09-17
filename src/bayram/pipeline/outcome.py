"""What a run produced: the kit, the gaps in it, and how long every step took.

No vendor publishes latency for music generation, so ``StepTiming`` is the only number
that will ever exist for this system. It is emitted per stage, per run, always — including
for failures, which are the interesting tail.

``RunLedger`` is an accumulator the pipeline *creates and owns*; it never mutates a value
handed to it, and it hands back immutable tuples.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from bayram.contracts import Kit, NameVerdict
from bayram.errors import BayramError, ErrorCode
from bayram.pipeline.events import PipelineStage

__all__ = [
    "StepTiming",
    "PipelineGap",
    "RunLedger",
    "PipelineOutcome",
]


class StepTiming(BaseModel):
    """Wall-clock cost of one stage, including every retry it swallowed."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    stage: PipelineStage
    duration_ms: int = Field(ge=0)
    attempts: int = Field(default=1, ge=1)
    is_ok: bool = True


class PipelineGap(BaseModel):
    """Something the customer paid for and did not get, recorded rather than raised.

    A gap never blocks delivery. It exists so support can see that greeting #2 is missing
    without reading a log, and so the delivery layer can apologise precisely.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    stage: PipelineStage
    error_code: ErrorCode
    detail: str = Field(min_length=1)
    user_message_key: str = Field(min_length=1)


class PipelineOutcome(BaseModel):
    """A successful (possibly partial) run."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    kit: Kit
    gaps: tuple[PipelineGap, ...] = ()
    timings: tuple[StepTiming, ...] = ()
    name_verdicts: tuple[NameVerdict, ...] = ()
    total_cost_usd: float = Field(default=0.0, ge=0.0)

    @property
    def is_complete(self) -> bool:
        return not self.gaps

    @property
    def total_duration_ms(self) -> int:
        return sum(timing.duration_ms for timing in self.timings)


class RunLedger:
    """Append-only collector for one run. Owned by the orchestrator, shared with nobody."""

    def __init__(self) -> None:
        self._timings: list[StepTiming] = []
        self._gaps: list[PipelineGap] = []
        self._cost_usd: float = 0.0

    def record_timing(
        self,
        stage: PipelineStage,
        *,
        duration_ms: int,
        attempts: int = 1,
        is_ok: bool = True,
    ) -> StepTiming:
        timing = StepTiming(
            stage=stage, duration_ms=max(0, duration_ms), attempts=attempts, is_ok=is_ok
        )
        self._timings.append(timing)
        return timing

    def record_gap(
        self, stage: PipelineStage, error: BayramError, *, detail: str = ""
    ) -> PipelineGap:
        gap = PipelineGap(
            stage=stage,
            error_code=error.error_code,
            detail=detail or error.operator_message,
            user_message_key=error.user_message_key,
        )
        self._gaps.append(gap)
        return gap

    def record_cost(self, cost_usd: float) -> None:
        self._cost_usd += max(0.0, cost_usd)

    @property
    def timings(self) -> tuple[StepTiming, ...]:
        return tuple(self._timings)

    @property
    def gaps(self) -> tuple[PipelineGap, ...]:
        return tuple(self._gaps)

    @property
    def cost_usd(self) -> float:
        return self._cost_usd
