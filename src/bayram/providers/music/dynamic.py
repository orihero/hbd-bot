"""Dynamic Music Provider that delegates to an active underlying provider.

Allows runtime switching between ElevenLabs and Gemini without requiring process restarts.
The active provider is resolved per call through an async callable (e.g. reading from Redis).

**A failure on Gemini fails over to ElevenLabs, one call at a time.** When Gemini fails for
any reason (credits depleted, 5xx server downtime, rate limit, timeout, or policy refusal)
and ElevenLabs is available, the same call is re-issued there — a customer's song is
not lost. The switch in Redis is deliberately NOT flipped: the moment Gemini recovers or
the account is topped up, future calls go back to the chosen provider with nobody having
to remember to switch it back.
"""

from __future__ import annotations

import contextlib
from collections.abc import Awaitable, Callable, Mapping
from datetime import UTC, datetime
from typing import Final

from bayram.contracts import (
    CompositionPlan,
    Err,
    HealthState,
    MusicProvider,
    Ok,
    ProviderHealth,
    RenderedAudio,
    Result,
    ok,
)
from bayram.logging import get_logger

__all__ = ["DynamicMusicProvider", "ROUTER_PROVIDER_NAME"]

_LOGGER = get_logger(__name__)

ROUTER_PROVIDER_NAME: Final[str] = "dynamic_music"

_SEVERITY_ORDER: Final[tuple[HealthState, ...]] = (
    HealthState.UNAVAILABLE,
    HealthState.DEGRADED,
    HealthState.UNKNOWN,
    HealthState.HEALTHY,
)


class DynamicMusicProvider:
    """Delegating ``MusicProvider`` whose active backend is resolved at call time."""

    name: str = ROUTER_PROVIDER_NAME

    def __init__(
        self,
        providers: Mapping[str, MusicProvider],
        *,
        default_provider: str = "elevenlabs",
        resolver: Callable[[], Awaitable[str]] | None = None,
    ) -> None:
        if not providers:
            raise ValueError("DynamicMusicProvider requires at least one provider")
        self._providers = dict(providers)
        self._default_provider = (
            default_provider if default_provider in self._providers else next(iter(self._providers))
        )
        self._resolver = resolver

    @property
    def providers(self) -> Mapping[str, MusicProvider]:
        return self._providers

    @property
    def default_provider(self) -> str:
        return self._default_provider

    async def get_active_provider(self) -> MusicProvider:
        """Resolve which provider should serve the next render."""
        return self._providers[await self._resolve_name()]

    async def _resolve_name(self) -> str:
        target_name = self._default_provider
        if self._resolver is not None:
            try:
                resolved = await self._resolver()
                if resolved in self._providers:
                    target_name = resolved
                else:
                    _LOGGER.warning(
                        "resolved unknown music provider, falling back to default",
                        extra={"resolved": resolved, "fallback": self._default_provider},
                    )
            except Exception as exc:
                _LOGGER.exception(
                    "failed to resolve active music provider, falling back to default",
                    extra={"error": str(exc), "fallback": self._default_provider},
                )
        return target_name

    def _failover_for(self, active: str, result: Result[RenderedAudio]) -> MusicProvider | None:
        """The provider to re-issue a failed call on, or ``None`` to keep the result.

        In any case if Gemini fails (quota exhaustion, transport error, 5xx, policy refusal,
        timeout), fail over to ElevenLabs so the customer's render is not lost.
        """
        if not isinstance(result, Err):
            return None
        target = "elevenlabs" if active == "gemini" else self._default_provider
        if active == target or target not in self._providers:
            return None
        _LOGGER.error(
            "music provider failed; this render fails over to fallback provider",
            extra={
                "failed_provider": active,
                "fallback": target,
                "error": str(result.error),
                "error_code": getattr(result.error, "error_code", None),
            },
        )
        return self._providers[target]

    async def compose(
        self, plan: CompositionPlan, *, idempotency_key: str, timeout_s: float
    ) -> Result[RenderedAudio]:
        active = await self._resolve_name()
        result = await self._providers[active].compose(
            plan, idempotency_key=idempotency_key, timeout_s=timeout_s
        )
        fallback = self._failover_for(active, result)
        if fallback is None:
            if isinstance(result, Ok) and result.value.provider is None:
                provider_name = getattr(self._providers[active], "name", active)
                result = ok(result.value.model_copy(update={"provider": provider_name}))
            return result
        fallback_res = await fallback.compose(
            plan, idempotency_key=idempotency_key, timeout_s=timeout_s
        )
        if isinstance(fallback_res, Ok) and fallback_res.value.provider is None:
            provider_name = getattr(fallback, "name", self._default_provider)
            fallback_res = ok(fallback_res.value.model_copy(update={"provider": provider_name}))
        return fallback_res

    async def inpaint(
        self,
        plan: CompositionPlan,
        *,
        source_song_id: str,
        chunk_index: int,
        idempotency_key: str,
        timeout_s: float,
    ) -> Result[RenderedAudio]:
        active = await self._resolve_name()
        result = await self._providers[active].inpaint(
            plan,
            source_song_id=source_song_id,
            chunk_index=chunk_index,
            idempotency_key=idempotency_key,
            timeout_s=timeout_s,
        )
        fallback = self._failover_for(active, result)
        if fallback is None:
            if isinstance(result, Ok) and result.value.provider is None:
                provider_name = getattr(self._providers[active], "name", active)
                result = ok(result.value.model_copy(update={"provider": provider_name}))
            return result
        # The source song lives on the exhausted vendor, so the fallback cannot inpaint it by
        # handle; compose re-renders the revised plan, which is what Gemini's own inpaint does.
        fallback_res = await fallback.compose(
            plan, idempotency_key=idempotency_key, timeout_s=timeout_s
        )
        if isinstance(fallback_res, Ok) and fallback_res.value.provider is None:
            provider_name = getattr(fallback, "name", self._default_provider)
            fallback_res = ok(fallback_res.value.model_copy(update={"provider": provider_name}))
        return fallback_res

    async def health(self) -> Result[ProviderHealth]:
        """Aggregate health of configured providers."""
        states: list[HealthState] = []
        details: list[str] = []
        as_of: datetime | None = None

        for name, provider in self._providers.items():
            result = await provider.health()
            if isinstance(result, Ok):
                states.append(result.value.state)
                details.append(f"{name}:{result.value.state.value}")
                as_of = result.value.as_of
            else:
                states.append(HealthState.UNAVAILABLE)
                details.append(f"{name}:unavailable")

        worst_state = HealthState.HEALTHY
        for candidate in _SEVERITY_ORDER:
            if candidate in states:
                worst_state = candidate
                break

        return ok(
            ProviderHealth(
                name=self.name,
                state=worst_state,
                as_of=as_of or datetime.now(tz=UTC),
                detail=", ".join(details),
            )
        )

    async def aclose(self) -> None:
        """Close HTTP clients across all underlying providers."""
        for provider in self._providers.values():
            close_method = getattr(provider, "aclose", None)
            if callable(close_method):
                with contextlib.suppress(Exception):
                    await close_method()
