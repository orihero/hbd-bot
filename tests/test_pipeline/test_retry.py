"""The retry ladder reads ``is_retryable`` and never invents a decision of its own."""

from __future__ import annotations

from hbd.contracts import Err, Result, err, ok
from hbd.errors import (
    HbdError,
    ModerationRejectedError,
    ProviderRateLimitedError,
    ProviderTimeoutError,
)
from hbd.pipeline.retry import MAX_BACKOFF_S, RetryPolicy, call_with_retry
from tests.test_pipeline.conftest import no_sleep


def _policy(attempts: int = 3) -> RetryPolicy:
    return RetryPolicy(max_attempts=attempts, backoff_base_s=1.0, jitter=0.5)


async def test_returns_immediately_when_the_first_attempt_succeeds() -> None:
    # Arrange
    calls: list[int] = []

    async def operation() -> Result[str]:
        calls.append(1)
        return ok("done")

    # Act
    result, report = await call_with_retry(
        operation, label="test", policy=_policy(), sleeper=no_sleep
    )

    # Assert
    assert not isinstance(result, Err)
    assert result.value == "done"
    assert report.attempts == 1
    assert report.was_retried is False
    assert len(calls) == 1


async def test_retries_a_retryable_failure_until_it_succeeds() -> None:
    # Arrange
    attempts: list[int] = []

    async def operation() -> Result[str]:
        attempts.append(len(attempts))
        if len(attempts) < 3:
            return err(ProviderRateLimitedError("slow down", provider="fake"))
        return ok("finally")

    # Act
    result, report = await call_with_retry(
        operation, label="test", policy=_policy(), sleeper=no_sleep
    )

    # Assert
    assert not isinstance(result, Err)
    assert result.value == "finally"
    assert report.attempts == 3
    assert report.was_retried is True


async def test_does_not_retry_a_terminal_failure() -> None:
    # Arrange
    attempts: list[int] = []

    async def operation() -> Result[str]:
        attempts.append(1)
        return err(ModerationRejectedError("no"))

    # Act
    result, report = await call_with_retry(
        operation, label="test", policy=_policy(), sleeper=no_sleep
    )

    # Assert
    assert isinstance(result, Err)
    assert len(attempts) == 1
    assert report.attempts == 1


async def test_gives_up_after_the_attempt_budget_is_spent() -> None:
    # Arrange
    attempts: list[int] = []

    async def operation() -> Result[str]:
        attempts.append(1)
        return err(ProviderTimeoutError("too slow", provider="fake"))

    # Act
    result, report = await call_with_retry(
        operation, label="test", policy=_policy(attempts=2), sleeper=no_sleep
    )

    # Assert
    assert isinstance(result, Err)
    assert len(attempts) == 2
    assert report.attempts == 2


async def test_converts_a_raised_exception_into_a_terminal_error() -> None:
    # Arrange
    async def operation() -> Result[str]:
        raise ValueError("an adapter broke its contract")

    # Act
    result, report = await call_with_retry(
        operation, label="rude-adapter", policy=_policy(), sleeper=no_sleep
    )

    # Assert
    assert isinstance(result, Err)
    assert result.error.is_terminal is True
    assert "rude-adapter" in result.error.operator_message
    assert report.attempts == 1


async def test_reports_each_retry_to_the_callback_with_the_error() -> None:
    # Arrange
    seen: list[tuple[int, HbdError]] = []

    async def on_retry(attempt: int, error: HbdError) -> None:
        seen.append((attempt, error))

    async def operation() -> Result[str]:
        return err(ProviderTimeoutError("nope", provider="fake"))

    # Act
    await call_with_retry(
        operation,
        label="test",
        policy=_policy(attempts=3),
        sleeper=no_sleep,
        on_retry=on_retry,
    )

    # Assert
    assert [attempt for attempt, _ in seen] == [1, 2]


async def test_sleeps_for_an_increasing_backoff_between_attempts() -> None:
    # Arrange
    slept: list[float] = []

    async def sleeper(seconds: float) -> None:
        slept.append(seconds)

    async def operation() -> Result[str]:
        return err(ProviderTimeoutError("nope", provider="fake"))

    # Act
    await call_with_retry(
        operation,
        label="test",
        policy=RetryPolicy(max_attempts=3, backoff_base_s=2.0, jitter=0.0),
        sleeper=sleeper,
        roll=lambda: 0.0,
    )

    # Assert
    assert slept == [2.0, 4.0]


def test_caps_the_backoff_at_the_ceiling() -> None:
    # Arrange
    policy = RetryPolicy(max_attempts=10, backoff_base_s=30.0, jitter=1.0)

    # Act
    delay = policy.delay_for(9, roll=1.0)

    # Assert
    assert delay == MAX_BACKOFF_S


def test_single_attempt_policy_never_waits() -> None:
    # Arrange / Act
    policy = RetryPolicy.single_attempt()

    # Assert
    assert policy.max_attempts == 1
    assert policy.jitter == 0.0
