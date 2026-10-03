"""Tests for DynamicMusicProvider and Redis music switch."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock

from bayram.contracts import (
    CompositionPlan,
    HealthState,
    ProviderHealth,
    RenderedAudio,
    err,
    is_err,
    is_ok,
    ok,
)
from bayram.errors import (
    ProviderQuotaExhaustedError,
    ProviderUnavailableError,
    StorageError,
    ValidationError,
)
from bayram.providers.music.dynamic import DynamicMusicProvider
from bayram.providers.music.switch import (
    PROVIDER_ELEVENLABS,
    PROVIDER_GEMINI,
    read_music_provider,
    write_music_provider,
)
from tests.test_providers_music.conftest import simple_plan


class StubProvider:
    def __init__(self, name: str, audio_bytes: bytes) -> None:
        self.name = name
        self._audio = audio_bytes
        self.compose_calls: list[CompositionPlan] = []
        self.inpaint_calls: list[CompositionPlan] = []

    async def compose(
        self, plan: CompositionPlan, *, idempotency_key: str, timeout_s: float
    ) -> Any:
        self.compose_calls.append(plan)
        return ok(
            RenderedAudio(
                data=self._audio,
                mime="audio/mpeg",
                duration_s=48.0,
                cost_usd=0.1,
                cost_source="estimated",
            )
        )

    async def inpaint(
        self,
        plan: CompositionPlan,
        *,
        source_song_id: str,
        chunk_index: int,
        idempotency_key: str,
        timeout_s: float,
    ) -> Any:
        self.inpaint_calls.append(plan)
        return ok(
            RenderedAudio(
                data=self._audio,
                mime="audio/mpeg",
                duration_s=48.0,
                cost_usd=0.05,
                cost_source="estimated",
            )
        )

    async def health(self) -> Any:
        from bayram.db.base import utc_now

        return ok(ProviderHealth(name=self.name, state=HealthState.HEALTHY, as_of=utc_now()))


async def test_dynamic_provider_routes_to_default() -> None:
    eleven = StubProvider("elevenlabs", b"eleven-audio")
    gemini = StubProvider("gemini", b"gemini-audio")

    dynamic = DynamicMusicProvider(
        {"elevenlabs": eleven, "gemini": gemini},
        default_provider="elevenlabs",
    )

    plan = simple_plan()
    result = await dynamic.compose(plan, idempotency_key="k", timeout_s=5.0)
    assert is_ok(result)
    assert result.value.data == b"eleven-audio"
    assert len(eleven.compose_calls) == 1
    assert len(gemini.compose_calls) == 0


async def test_dynamic_provider_routes_dynamically() -> None:
    eleven = StubProvider("elevenlabs", b"eleven-audio")
    gemini = StubProvider("gemini", b"gemini-audio")

    active = "elevenlabs"

    async def resolver() -> str:
        return active

    dynamic = DynamicMusicProvider(
        {"elevenlabs": eleven, "gemini": gemini},
        default_provider="elevenlabs",
        resolver=resolver,
    )

    plan = simple_plan()

    # First call: elevenlabs
    res1 = await dynamic.compose(plan, idempotency_key="k1", timeout_s=5.0)
    assert is_ok(res1)
    assert res1.value.data == b"eleven-audio"

    # Switch to gemini
    active = "gemini"
    res2 = await dynamic.compose(plan, idempotency_key="k2", timeout_s=5.0)
    assert is_ok(res2)
    assert res2.value.data == b"gemini-audio"
    assert len(gemini.compose_calls) == 1


async def test_dynamic_provider_resolver_failure_fallback() -> None:
    eleven = StubProvider("elevenlabs", b"eleven-audio")
    gemini = StubProvider("gemini", b"gemini-audio")

    async def failing_resolver() -> str:
        raise RuntimeError("Redis connection lost")

    dynamic = DynamicMusicProvider(
        {"elevenlabs": eleven, "gemini": gemini},
        default_provider="elevenlabs",
        resolver=failing_resolver,
    )

    plan = simple_plan()
    res = await dynamic.compose(plan, idempotency_key="k", timeout_s=5.0)
    assert is_ok(res)
    assert res.value.data == b"eleven-audio"
    assert len(eleven.compose_calls) == 1


class MockRedis:
    def __init__(self) -> None:
        self.data: dict[str, bytes] = {}

    async def get(self, key: str) -> bytes | None:
        return self.data.get(key)

    async def set(self, key: str, value: str) -> None:
        self.data[key] = value.encode("utf-8")


async def test_redis_music_switch() -> None:
    redis = MockRedis()

    # Default when key is absent
    val = await read_music_provider(redis, default=PROVIDER_ELEVENLABS)
    assert val == PROVIDER_ELEVENLABS

    # Write gemini
    write_res = await write_music_provider(redis, PROVIDER_GEMINI)
    assert is_ok(write_res)
    assert await read_music_provider(redis) == PROVIDER_GEMINI

    # Write elevenlabs
    write_res2 = await write_music_provider(redis, PROVIDER_ELEVENLABS)
    assert is_ok(write_res2)
    assert await read_music_provider(redis) == PROVIDER_ELEVENLABS

    # Refuse unknown provider
    bad_res = await write_music_provider(redis, "unknown_vendor")
    assert is_err(bad_res)
    assert isinstance(bad_res.error, ValidationError)


async def test_redis_music_switch_storage_error() -> None:
    broken_redis = AsyncMock()
    broken_redis.set.side_effect = ConnectionError("Redis is down")

    result = await write_music_provider(broken_redis, PROVIDER_GEMINI)
    assert is_err(result)
    assert isinstance(result.error, StorageError)


class FailingProvider(StubProvider):
    def __init__(self, name: str, error: Any) -> None:
        super().__init__(name, b"")
        self._error = error

    async def compose(
        self, plan: CompositionPlan, *, idempotency_key: str, timeout_s: float
    ) -> Any:
        self.compose_calls.append(plan)
        return err(self._error)

    async def inpaint(
        self,
        plan: CompositionPlan,
        *,
        source_song_id: str,
        chunk_index: int,
        idempotency_key: str,
        timeout_s: float,
    ) -> Any:
        self.inpaint_calls.append(plan)
        return err(self._error)


def _gemini_active(providers: dict[str, Any]) -> DynamicMusicProvider:
    async def resolver() -> str:
        return "gemini"

    return DynamicMusicProvider(providers, default_provider="elevenlabs", resolver=resolver)


async def test_out_of_credit_gemini_fails_over_to_the_default_for_that_call() -> None:
    eleven = StubProvider("elevenlabs", b"eleven-audio")
    gemini = FailingProvider("gemini", ProviderQuotaExhaustedError("depleted", provider="gemini"))
    dynamic = _gemini_active({"elevenlabs": eleven, "gemini": gemini})

    result = await dynamic.compose(simple_plan(), idempotency_key="k", timeout_s=5.0)

    assert is_ok(result)
    assert result.value.data == b"eleven-audio"
    assert len(gemini.compose_calls) == 1
    assert len(eleven.compose_calls) == 1


async def test_out_of_credit_inpaint_recomposes_on_the_default() -> None:
    eleven = StubProvider("elevenlabs", b"eleven-audio")
    gemini = FailingProvider("gemini", ProviderQuotaExhaustedError("depleted", provider="gemini"))
    dynamic = _gemini_active({"elevenlabs": eleven, "gemini": gemini})

    result = await dynamic.inpaint(
        simple_plan(), source_song_id="s", chunk_index=1, idempotency_key="k", timeout_s=5.0
    )

    assert is_ok(result)
    assert len(eleven.compose_calls) == 1
    assert len(eleven.inpaint_calls) == 0


async def test_any_gemini_failure_fails_over_to_elevenlabs() -> None:
    eleven = StubProvider("elevenlabs", b"eleven-audio")
    gemini = FailingProvider("gemini", ProviderUnavailableError("down", provider="gemini"))
    dynamic = _gemini_active({"elevenlabs": eleven, "gemini": gemini})

    result = await dynamic.compose(simple_plan(), idempotency_key="k", timeout_s=5.0)

    assert is_ok(result)
    assert result.value.data == b"eleven-audio"
    assert len(gemini.compose_calls) == 1
    assert len(eleven.compose_calls) == 1


async def test_gemini_fails_over_to_elevenlabs_even_when_gemini_is_default() -> None:
    eleven = StubProvider("elevenlabs", b"eleven-audio")
    gemini = FailingProvider("gemini", ProviderUnavailableError("server error", provider="gemini"))
    dynamic = DynamicMusicProvider(
        {"elevenlabs": eleven, "gemini": gemini},
        default_provider="gemini",
    )

    result = await dynamic.compose(simple_plan(), idempotency_key="k", timeout_s=5.0)

    assert is_ok(result)
    assert result.value.data == b"eleven-audio"
    assert len(gemini.compose_calls) == 1
    assert len(eleven.compose_calls) == 1


async def test_out_of_credit_default_has_nowhere_to_fail_over_to() -> None:
    gemini = FailingProvider("gemini", ProviderQuotaExhaustedError("depleted", provider="gemini"))
    dynamic = DynamicMusicProvider({"gemini": gemini}, default_provider="gemini")

    result = await dynamic.compose(simple_plan(), idempotency_key="k", timeout_s=5.0)

    assert is_err(result)
    assert len(gemini.compose_calls) == 1


async def test_health_aggregates_underlying_providers() -> None:
    eleven = StubProvider("elevenlabs", b"")
    gemini = StubProvider("gemini", b"")
    dynamic = DynamicMusicProvider({"elevenlabs": eleven, "gemini": gemini})

    result = await dynamic.health()

    assert is_ok(result)
    assert result.value.state is HealthState.HEALTHY
    assert result.value.detail == "elevenlabs:healthy, gemini:healthy"
