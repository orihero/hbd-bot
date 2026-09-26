"""Greetings render concurrently, within a slot budget, and survive each other's failures."""

from __future__ import annotations

import asyncio
from uuid import uuid4

from bayram.config import Settings
from bayram.contracts import Language, RenderedAudio, Result, SpeechRequest, SpokenScript
from bayram.errors import ErrorCode
from bayram.pipeline.greetings import GreetingBatch, render_greetings
from bayram.pipeline.retry import RetryPolicy
from tests.conftest import UZBEK_NAME_CANONICAL
from tests.test_pipeline.conftest import FakeTtsProvider, no_sleep


def _script(persona_id: str) -> SpokenScript:
    return SpokenScript(
        persona_id=persona_id,
        language=Language.UZ_LATN,
        text=f"Assalomu alaykum {UZBEK_NAME_CANONICAL}!",
        name_submitted="Gulomjon",
        target_duration_s=30.0,
    )


SCRIPTS = (_script("persona-1"), _script("persona-2"), _script("persona-3"))


async def _render(
    tts: FakeTtsProvider,
    settings: Settings,
    *,
    slots: int = 3,
    scripts: tuple[SpokenScript, ...] = SCRIPTS,
) -> GreetingBatch:
    return await render_greetings(
        scripts,
        order_id=uuid4(),
        tts=tts,
        settings=settings,
        policy=RetryPolicy(max_attempts=1, backoff_base_s=0.01, jitter=0.0),
        sleeper=no_sleep,
        slots=asyncio.Semaphore(slots),
    )


async def test_renders_one_greeting_per_script(settings: Settings) -> None:
    # Arrange
    tts = FakeTtsProvider()

    # Act
    batch = await _render(tts, settings)

    # Assert
    assert len(batch.renders) == 3
    assert batch.is_complete is True
    assert [render.index for render in batch.renders] == [0, 1, 2]


async def test_keeps_the_successes_when_one_voice_fails(settings: Settings) -> None:
    # Arrange
    tts = FakeTtsProvider()
    tts.failing_personas = {"persona-2"}

    # Act
    batch = await _render(tts, settings)

    # Assert
    assert [render.script.persona_id for render in batch.renders] == [
        "persona-1",
        "persona-3",
    ]
    assert batch.failures[0].persona_id == "persona-2"
    assert batch.failures[0].error.error_code is ErrorCode.UPSTREAM_5XX


async def test_reports_every_failure_when_the_whole_provider_is_down(
    settings: Settings,
) -> None:
    # Arrange
    tts = FakeTtsProvider()
    tts.failing_personas = {"persona-1", "persona-2", "persona-3"}

    # Act
    batch = await _render(tts, settings)

    # Assert
    assert batch.renders == ()
    assert len(batch.failures) == 3


async def test_sums_the_cost_of_what_actually_rendered(settings: Settings) -> None:
    # Arrange
    tts = FakeTtsProvider()
    tts.failing_personas = {"persona-3"}

    # Act
    batch = await _render(tts, settings)

    # Assert
    assert batch.cost_usd == 0.04


async def test_never_exceeds_the_slot_budget(settings: Settings) -> None:
    # Arrange
    tts = FakeTtsProvider()
    in_flight = 0
    peak = 0
    original = tts.synthesize

    async def counting(
        request: SpeechRequest, *, idempotency_key: str, timeout_s: float
    ) -> Result[RenderedAudio]:
        nonlocal in_flight, peak
        in_flight += 1
        peak = max(peak, in_flight)
        await asyncio.sleep(0)
        result = await original(request, idempotency_key=idempotency_key, timeout_s=timeout_s)
        in_flight -= 1
        return result

    tts.synthesize = counting  # type: ignore[method-assign]

    # Act
    await _render(tts, settings, slots=1)

    # Assert
    assert peak == 1


async def test_carries_the_submitted_orthography_into_the_speech_request(
    settings: Settings,
) -> None:
    # Arrange
    tts = FakeTtsProvider()

    # Act
    await _render(tts, settings)

    # Assert
    assert {call.name_submitted for call in tts.calls} == {"Gulomjon"}
    assert all(UZBEK_NAME_CANONICAL in call.text for call in tts.calls)


async def test_each_greeting_gets_its_own_idempotency_key(settings: Settings) -> None:
    # Arrange
    tts = FakeTtsProvider()

    # Act
    await _render(tts, settings)

    # Assert
    assert len(set(tts.idempotency_keys)) == 3


async def test_an_empty_script_list_produces_an_empty_batch(settings: Settings) -> None:
    # Arrange
    tts = FakeTtsProvider()

    # Act
    batch = await _render(tts, settings, scripts=())

    # Assert
    assert batch.renders == ()
    assert batch.failures == ()
    assert tts.calls == []
