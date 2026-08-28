"""The retry ladder.

The decision to retry is never guessed here: it is read off ``HbdError.is_retryable``,
which the layer that produced the error set, because that layer knows whether the
identical call could succeed again. A rate limit is retried; a rejected lyric is not.

Two defences beyond the obvious:

* A protocol method is contractually forbidden from raising, but adapters are code written
  by humans. If one escapes, it is converted into a terminal ``PipelineError`` carrying the
  exception, never allowed to unwind the orchestrator.
* ``asyncio.CancelledError`` is re-raised untouched: a cancelled job is not a failed one.
"""

from __future__ import annotations

import asyncio
import random
from collections.abc import Awaitable, Callable
from typing import Final

from pydantic import BaseModel, ConfigDict, Field

from hbd.config import Settings
from hbd.contracts import Err, Result, err
from hbd.errors import HbdError, PipelineError
from hbd.logging import get_logger
from hbd.pipeline.ports import Sleeper

__all__ = ["RetryPolicy", "RetryReport", "call_with_retry", "DEFAULT_BACKOFF_MULTIPLIER"]

_LOGGER = get_logger(__name__)

#: Exponential base. Attempt n waits ``backoff_base_s * 2 ** n`` before attempt n+1.
DEFAULT_BACKOFF_MULTIPLIER: Final[float] = 2.0

#: Never wait longer than this between attempts, whatever the exponent says.
MAX_BACKOFF_S: Final[float] = 60.0


class RetryPolicy(BaseModel):
    """Bounded exponential backoff with proportional jitter."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    max_attempts: int = Field(ge=1, le=10)
    backoff_base_s: float = Field(gt=0)
    jitter: float = Field(ge=0.0, le=1.0)

    @classmethod
    def from_settings(cls, settings: Settings) -> RetryPolicy:
        return cls(
            max_attempts=settings.provider_max_attempts,
            backoff_base_s=settings.provider_backoff_base_s,
            jitter=settings.provider_backoff_jitter,
        )

    @classmethod
    def single_attempt(cls) -> RetryPolicy:
        """For calls whose failure is handled by the caller rather than repeated."""
        return cls(max_attempts=1, backoff_base_s=1.0, jitter=0.0)

    def delay_for(self, attempt: int, *, roll: float) -> float:
        """Seconds to wait after a failed zero-based ``attempt``. ``roll`` is in [0, 1)."""
        exponential = self.backoff_base_s * (DEFAULT_BACKOFF_MULTIPLIER**attempt)
        jittered = exponential * (1.0 + self.jitter * roll)
        return min(MAX_BACKOFF_S, jittered)


class RetryReport(BaseModel):
    """How many attempts a call actually consumed. Feeds ``StepTiming.attempts``."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    attempts: int = Field(ge=1)
    was_retried: bool = False


async def _invoke[T](operation: Callable[[], Awaitable[Result[T]]], *, label: str) -> Result[T]:
    """Run one attempt, converting a contract-breaking exception into an ``Err``."""
    try:
        return await operation()
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        _LOGGER.exception(
            "provider call raised instead of returning Err",
            extra={"operation": label, "failure": repr(exc)},
        )
        return err(
            PipelineError(
                f"{label} raised {type(exc).__name__} instead of returning a Result",
                context={"operation": label},
                cause=exc,
            )
        )


async def call_with_retry[T](
    operation: Callable[[], Awaitable[Result[T]]],
    *,
    label: str,
    policy: RetryPolicy,
    sleeper: Sleeper,
    on_retry: Callable[[int, HbdError], Awaitable[None]] | None = None,
    roll: Callable[[], float] = random.random,
) -> tuple[Result[T], RetryReport]:
    """Call ``operation`` until it succeeds, is terminal, or the budget runs out.

    ``operation`` takes no arguments so its idempotency key stays identical across
    attempts — that is the whole point of the key. Returns the last result plus a report,
    never raising anything except ``CancelledError``.
    """
    last: Result[T] = err(PipelineError(f"{label} was never attempted"))
    for attempt in range(policy.max_attempts):
        last = await _invoke(operation, label=label)
        if not isinstance(last, Err):
            return last, RetryReport(attempts=attempt + 1, was_retried=attempt > 0)

        failure: Err = last
        is_last_attempt = attempt == policy.max_attempts - 1
        if failure.error.is_terminal or is_last_attempt:
            _LOGGER.warning(
                "call failed and will not be retried",
                extra={
                    "operation": label,
                    "attempt": attempt + 1,
                    "max_attempts": policy.max_attempts,
                    "is_terminal": failure.error.is_terminal,
                    **failure.error.to_log_dict(),
                },
            )
            return last, RetryReport(attempts=attempt + 1, was_retried=attempt > 0)

        delay_s = policy.delay_for(attempt, roll=roll())
        _LOGGER.info(
            "retrying after a retryable failure",
            extra={"operation": label, "attempt": attempt + 1, "delay_s": delay_s},
        )
        if on_retry is not None:
            await on_retry(attempt + 1, failure.error)
        await sleeper(delay_s)

    return last, RetryReport(attempts=policy.max_attempts, was_retried=policy.max_attempts > 1)
