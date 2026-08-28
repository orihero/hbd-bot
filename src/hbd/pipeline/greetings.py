"""Rendering the three spoken greetings, concurrently and forgivingly.

Concurrency is bounded by a semaphore the caller owns, so every order running in the
worker shares one budget of provider slots rather than each order politely limiting itself
while fifteen of them stampede the vendor together.

Partial failure is the whole point of this module's return type. A greeting is cheap; the
song is not. If one voice 500s, the other two ship, the gap is reported, and the caller
decides what to tell the customer. Nothing here raises and nothing here throws away a
success because a sibling failed.
"""

from __future__ import annotations

import asyncio
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from hbd.config import Settings
from hbd.contracts import (
    Err,
    RenderedAudio,
    Result,
    SpeechRequest,
    SpokenScript,
    TtsProvider,
)
from hbd.errors import HbdError
from hbd.logging import get_logger
from hbd.pipeline.events import PipelineStage
from hbd.pipeline.idempotency import idempotency_key
from hbd.pipeline.ports import Sleeper
from hbd.pipeline.retry import RetryPolicy, call_with_retry

__all__ = ["GreetingRender", "GreetingFailure", "GreetingBatch", "render_greetings"]

_LOGGER = get_logger(__name__)


class GreetingRender(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    index: int = Field(ge=0)
    script: SpokenScript
    audio: RenderedAudio


class GreetingFailure(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", arbitrary_types_allowed=True)

    index: int = Field(ge=0)
    persona_id: str = Field(min_length=1)
    error: HbdError


class GreetingBatch(BaseModel):
    """Whatever came back. ``renders`` may be shorter than the scripts asked for."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    renders: tuple[GreetingRender, ...] = ()
    failures: tuple[GreetingFailure, ...] = ()

    @property
    def cost_usd(self) -> float:
        return sum(render.audio.cost_usd for render in self.renders)

    @property
    def is_complete(self) -> bool:
        return not self.failures


async def _render_one(
    script: SpokenScript,
    *,
    index: int,
    order_id: UUID,
    tts: TtsProvider,
    settings: Settings,
    policy: RetryPolicy,
    sleeper: Sleeper,
    slots: asyncio.Semaphore,
) -> GreetingRender | GreetingFailure:
    request = SpeechRequest(
        text=script.text,
        persona_id=script.persona_id,
        language=script.language,
        name_submitted=script.name_submitted,
    )
    key = idempotency_key(order_id, PipelineStage.RENDERING_GREETINGS, script.persona_id, index)

    async def call() -> Result[RenderedAudio]:
        async with slots:
            return await tts.synthesize(
                request, idempotency_key=key, timeout_s=settings.tts_timeout_s
            )

    result, _report = await call_with_retry(
        call, label=f"tts.{tts.name}[{script.persona_id}]", policy=policy, sleeper=sleeper
    )
    if isinstance(result, Err):
        _LOGGER.warning(
            "greeting render failed; the rest of the kit continues",
            extra={"persona_id": script.persona_id, "index": index, **result.error.to_log_dict()},
        )
        return GreetingFailure(index=index, persona_id=script.persona_id, error=result.error)
    return GreetingRender(index=index, script=script, audio=result.value)


async def render_greetings(
    scripts: tuple[SpokenScript, ...],
    *,
    order_id: UUID,
    tts: TtsProvider,
    settings: Settings,
    policy: RetryPolicy,
    sleeper: Sleeper,
    slots: asyncio.Semaphore,
) -> GreetingBatch:
    """Render every script concurrently within ``slots``. Never raises, never all-or-nothing."""
    if not scripts:
        return GreetingBatch()

    outcomes = await asyncio.gather(
        *(
            _render_one(
                script,
                index=index,
                order_id=order_id,
                tts=tts,
                settings=settings,
                policy=policy,
                sleeper=sleeper,
                slots=slots,
            )
            for index, script in enumerate(scripts)
        )
    )
    renders = tuple(item for item in outcomes if isinstance(item, GreetingRender))
    failures = tuple(item for item in outcomes if isinstance(item, GreetingFailure))
    _LOGGER.info(
        "greeting batch finished",
        extra={"requested": len(scripts), "rendered": len(renders), "failed": len(failures)},
    )
    return GreetingBatch(renders=renders, failures=failures)
