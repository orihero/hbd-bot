"""Eleven Music behind ``MusicProvider``. The only file here that opens a socket.

Shape of every call: acquire a concurrency slot, POST, translate the outcome, emit one
measured usage line, return a ``Result``. **No method raises.** An ``httpx`` exception that
escaped would bypass the retry ladder's ``is_retryable`` decision, which is the entire
mechanism the pipeline uses to tell "try again" from "stop".

Concurrency is a hard vendor ceiling, not a tuning knob: Eleven allows two simultaneous
music renders on Starter/Creator/Pro and five on Scale, and exceeding it earns a 429 that
costs a retry. The semaphore here holds this process to that ceiling regardless of how many
ARQ workers pick up jobs at once.

The name re-roll path is ``regenerate_chunk``: it swaps one chunk's text and inpaints the
stored song, so a mispronounced name costs one chunk instead of a whole track. The stored
handle is kept alive across re-rolls because attempt two needs it as much as attempt one.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from time import perf_counter
from typing import Any, Final

import httpx
import orjson

from hbd.contracts import (
    CompositionPlan,
    CostSource,
    Err,
    HealthState,
    ProviderHealth,
    RenderedAudio,
    Result,
    err,
    ok,
)
from hbd.errors import ProviderInvalidResponseError, ValidationError
from hbd.logging import get_logger
from hbd.providers.music.failures import (
    describe_error_body,
    map_status_error,
    map_transport_error,
)
from hbd.providers.music.payload import (
    MUSIC_PATH,
    SUBSCRIPTION_PATH,
    build_compose_body,
    build_inpaint_body,
    guard_plan,
)
from hbd.providers.music.planner import plan_with_chunk_text
from hbd.providers.music.usage import (
    DEFAULT_MUSIC_USD_PER_MINUTE,
    MusicUsage,
    estimate_cost_usd,
    log_usage,
)

__all__ = [
    "ElevenLabsMusicProvider",
    "PROVIDER_NAME",
    "DEFAULT_MUSIC_MAX_CONCURRENCY",
    "SCALE_TIER_MAX_CONCURRENCY",
    "SONG_ID_HEADERS",
]

_logger = get_logger(__name__)

PROVIDER_NAME: Final[str] = "elevenlabs_music"

#: Simultaneous music renders allowed on Starter / Creator / Pro.
DEFAULT_MUSIC_MAX_CONCURRENCY: Final[int] = 2
#: …and on Scale. Set the config knob to this when the account is upgraded.
SCALE_TIER_MAX_CONCURRENCY: Final[int] = 5

DEFAULT_HEALTH_TIMEOUT_S: Final[float] = 10.0
API_KEY_HEADER: Final[str] = "xi-api-key"
IDEMPOTENCY_HEADER: Final[str] = "idempotency-key"

#: Where the stored-song handle for inpainting is looked for, in order. The vendor does not
#: document this header name for the raw-audio endpoint, so we accept the plausible spellings
#: and treat "absent" as "this track cannot be inpainted" rather than as a failure.
SONG_ID_HEADERS: Final[tuple[str, ...]] = ("song-id", "x-song-id", "elevenlabs-song-id")

_MIME_BY_FORMAT_PREFIX: Final[Mapping[str, str]] = {
    "mp3": "audio/mpeg",
    "opus": "audio/ogg",
    "ogg": "audio/ogg",
    "pcm": "audio/wave",
    "ulaw": "audio/basic",
    "alaw": "audio/basic",
}
_FALLBACK_MIME: Final[str] = "application/octet-stream"

_OPERATION_COMPOSE: Final[str] = "compose"
_OPERATION_INPAINT: Final[str] = "inpaint"
_OPERATION_HEALTH: Final[str] = "health"

_OUTCOME_OK: Final[str] = "ok"
_OUTCOME_HTTP_ERROR: Final[str] = "http_error"
_OUTCOME_TRANSPORT_ERROR: Final[str] = "transport_error"
_OUTCOME_MALFORMED: Final[str] = "malformed_response"

_MS_PER_S: Final[int] = 1_000
_HTTP_ERROR_FLOOR: Final[int] = 400
_SERVER_ERROR_FLOOR: Final[int] = 500


def _utc_now() -> datetime:
    return datetime.now(tz=UTC)


def mime_for_output_format(output_format: str) -> str:
    """Best-effort MIME for a vendor format string such as ``mp3_44100_128``."""
    prefix = output_format.split("_", maxsplit=1)[0].lower()
    return _MIME_BY_FORMAT_PREFIX.get(prefix, _FALLBACK_MIME)


def _remote_id(headers: httpx.Headers) -> str | None:
    for header in SONG_ID_HEADERS:
        value: str | None = headers.get(header)
        if value:
            return value
    return None


class ElevenLabsMusicProvider:
    """``MusicProvider`` over ``POST /v1/music``. The response body is the audio itself."""

    name: str = PROVIDER_NAME

    def __init__(
        self,
        *,
        api_key: str,
        base_url: str,
        model_id: str,
        output_format: str,
        max_concurrency: int = DEFAULT_MUSIC_MAX_CONCURRENCY,
        usd_per_minute: float = DEFAULT_MUSIC_USD_PER_MINUTE,
        health_timeout_s: float = DEFAULT_HEALTH_TIMEOUT_S,
        client: httpx.AsyncClient | None = None,
        clock: Callable[[], datetime] = _utc_now,
    ) -> None:
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")
        self._model_id = model_id
        self._output_format = output_format
        self._usd_per_minute = usd_per_minute
        self._health_timeout_s = health_timeout_s
        self._clock = clock
        self._owns_client = client is None
        self._client = client if client is not None else httpx.AsyncClient()
        self._slots = asyncio.Semaphore(max(1, max_concurrency))

    # -- lifecycle ----------------------------------------------------------
    async def aclose(self) -> None:
        """Close the HTTP client, but only the one we created."""
        if self._owns_client:
            await self._client.aclose()

    # -- MusicProvider ------------------------------------------------------
    async def compose(
        self, plan: CompositionPlan, *, idempotency_key: str, timeout_s: float
    ) -> Result[RenderedAudio]:
        guarded = guard_plan(plan)
        if isinstance(guarded, Err):
            return guarded
        body = build_compose_body(
            plan, model_id=self._model_id, output_format=self._output_format
        )
        return await self._post_music(
            body, plan=plan, operation=_OPERATION_COMPOSE, timeout_s=timeout_s,
            idempotency_key=idempotency_key,
        )

    async def inpaint(
        self,
        plan: CompositionPlan,
        *,
        source_song_id: str,
        chunk_index: int,
        idempotency_key: str,
        timeout_s: float,
    ) -> Result[RenderedAudio]:
        if not source_song_id.strip():
            return err(ValidationError("cannot inpaint without a stored song id"))
        if not 0 <= chunk_index < len(plan.chunks):
            return err(
                ValidationError(
                    f"chunk index {chunk_index} is out of range for a "
                    f"{len(plan.chunks)}-chunk plan",
                    context={"chunk_index": chunk_index, "chunk_count": len(plan.chunks)},
                )
            )
        guarded = guard_plan(plan)
        if isinstance(guarded, Err):
            return guarded
        body = build_inpaint_body(
            plan,
            source_song_id=source_song_id,
            chunk_index=chunk_index,
            model_id=self._model_id,
            output_format=self._output_format,
        )
        return await self._post_music(
            body, plan=plan, operation=_OPERATION_INPAINT, timeout_s=timeout_s,
            idempotency_key=idempotency_key, source_song_id=source_song_id,
        )

    async def regenerate_chunk(
        self,
        plan: CompositionPlan,
        *,
        source_song_id: str,
        chunk_index: int,
        new_text: str,
        idempotency_key: str,
        timeout_s: float,
    ) -> Result[RenderedAudio]:
        """Re-render ONE chunk with new text. The name re-roll path.

        The caller supplies the next candidate orthography; this swaps it into the plan and
        inpaints, so a rejected pronunciation costs a single chunk.
        """
        updated = plan_with_chunk_text(plan, chunk_index, new_text)
        if isinstance(updated, Err):
            return updated
        return await self.inpaint(
            updated.value,
            source_song_id=source_song_id,
            chunk_index=chunk_index,
            idempotency_key=idempotency_key,
            timeout_s=timeout_s,
        )

    async def health(self) -> Result[ProviderHealth]:
        """Never reports a healthy vendor optimistically, and never raises."""
        url = f"{self._base_url}{SUBSCRIPTION_PATH}"
        headers = {API_KEY_HEADER: self._api_key, "accept": "application/json"}
        try:
            response = await self._client.get(
                url, headers=headers, timeout=httpx.Timeout(self._health_timeout_s)
            )
        except httpx.HTTPError as exc:
            return ok(self._health_state(HealthState.UNAVAILABLE, detail=str(exc)))

        if response.status_code in (401, 403):
            return err(
                map_status_error(response, provider=self.name, operation=_OPERATION_HEALTH)
            )
        if response.status_code >= _HTTP_ERROR_FLOOR:
            state = (
                HealthState.UNAVAILABLE
                if response.status_code >= _SERVER_ERROR_FLOOR
                else HealthState.DEGRADED
            )
            return ok(self._health_state(state, detail=describe_error_body(response.content)))
        return ok(self._health_from_body(response.content))

    # -- internals ----------------------------------------------------------
    def _health_state(
        self, state: HealthState, *, detail: str | None, quota_remaining: int | None = None
    ) -> ProviderHealth:
        return ProviderHealth(
            name=self.name,
            state=state,
            as_of=self._clock(),
            quota_remaining=quota_remaining,
            detail=detail,
        )

    def _health_from_body(self, body: bytes) -> ProviderHealth:
        """A 200 with an unreadable body means UNKNOWN, not HEALTHY. Never raises."""
        try:
            payload = orjson.loads(body)
        except orjson.JSONDecodeError:
            return self._health_state(HealthState.UNKNOWN, detail="subscription body is not JSON")
        if not isinstance(payload, dict):
            return self._health_state(
                HealthState.UNKNOWN, detail="subscription body is not an object"
            )
        used = payload.get("character_count")
        limit = payload.get("character_limit")
        remaining = (
            limit - used if isinstance(used, int) and isinstance(limit, int) else None
        )
        if remaining is not None and remaining <= 0:
            return self._health_state(
                HealthState.DEGRADED, detail="character quota exhausted", quota_remaining=0
            )
        return self._health_state(HealthState.HEALTHY, detail=None, quota_remaining=remaining)

    def _headers(self, idempotency_key: str) -> dict[str, str]:
        return {
            API_KEY_HEADER: self._api_key,
            IDEMPOTENCY_HEADER: idempotency_key,
            "accept": "audio/*",
            "content-type": "application/json",
        }

    async def _send(
        self, body: dict[str, Any], *, timeout_s: float, idempotency_key: str, operation: str
    ) -> Result[httpx.Response]:
        """POST inside a concurrency slot. Transport failures come back typed."""
        url = f"{self._base_url}{MUSIC_PATH}"
        try:
            async with self._slots:
                response = await self._client.post(
                    url,
                    json=body,
                    headers=self._headers(idempotency_key),
                    timeout=httpx.Timeout(timeout_s),
                )
        except httpx.HTTPError as exc:
            return err(
                map_transport_error(
                    exc, provider=self.name, operation=operation, timeout_s=timeout_s
                )
            )
        return ok(response)

    def _to_audio(
        self, response: httpx.Response, *, plan: CompositionPlan, operation: str
    ) -> Result[RenderedAudio]:
        """A 200 is not a success until the body is actually audio."""
        content_type = response.headers.get("content-type", "")
        if not response.content:
            return err(
                ProviderInvalidResponseError(
                    f"vendor returned 200 with an empty body for {operation}",
                    provider=self.name,
                    context={"operation": operation, "content_type": content_type},
                )
            )
        if content_type and not content_type.startswith("audio/"):
            return err(
                ProviderInvalidResponseError(
                    f"vendor returned 200 with content-type {content_type!r}, expected audio",
                    provider=self.name,
                    context={
                        "operation": operation,
                        "content_type": content_type,
                        "response_detail": describe_error_body(response.content),
                    },
                )
            )
        return ok(
            RenderedAudio(
                data=response.content,
                mime=content_type or mime_for_output_format(self._output_format),
                duration_s=plan.total_duration_ms / _MS_PER_S,
                remote_id=_remote_id(response.headers),
                cost_usd=estimate_cost_usd(
                    plan.total_duration_ms, usd_per_minute=self._usd_per_minute
                ),
                cost_source=CostSource.ESTIMATED,
            )
        )

    def _usage(
        self,
        *,
        plan: CompositionPlan,
        operation: str,
        outcome: str,
        elapsed_ms: int,
        http_status: int | None = None,
        audio: RenderedAudio | None = None,
        source_song_id: str | None = None,
    ) -> MusicUsage:
        return MusicUsage(
            provider=self.name,
            operation=operation,
            model_id=self._model_id,
            output_format=self._output_format,
            chunk_count=len(plan.chunks),
            total_duration_ms=plan.total_duration_ms,
            elapsed_ms=elapsed_ms,
            outcome=outcome,
            http_status=http_status,
            response_bytes=len(audio.data) if audio is not None else 0,
            remote_id=audio.remote_id if audio is not None else None,
            estimated_cost_usd=audio.cost_usd if audio is not None else 0.0,
            name_chunk_index=plan.name_chunk_index,
            source_song_id=source_song_id,
        )

    async def _post_music(
        self,
        body: dict[str, Any],
        *,
        plan: CompositionPlan,
        operation: str,
        timeout_s: float,
        idempotency_key: str,
        source_song_id: str | None = None,
    ) -> Result[RenderedAudio]:
        """One vendor call, one usage line, one ``Result``. Never raises."""
        started = perf_counter()

        def elapsed_ms() -> int:
            return int((perf_counter() - started) * _MS_PER_S)

        def record(outcome: str, *, status: int | None, audio: RenderedAudio | None) -> None:
            log_usage(
                _logger,
                self._usage(
                    plan=plan,
                    operation=operation,
                    outcome=outcome,
                    elapsed_ms=elapsed_ms(),
                    http_status=status,
                    audio=audio,
                    source_song_id=source_song_id,
                ),
            )

        sent = await self._send(
            body, timeout_s=timeout_s, idempotency_key=idempotency_key, operation=operation
        )
        if isinstance(sent, Err):
            record(_OUTCOME_TRANSPORT_ERROR, status=None, audio=None)
            return sent

        response = sent.value
        if response.status_code >= _HTTP_ERROR_FLOOR:
            record(_OUTCOME_HTTP_ERROR, status=response.status_code, audio=None)
            return err(map_status_error(response, provider=self.name, operation=operation))

        audio = self._to_audio(response, plan=plan, operation=operation)
        if isinstance(audio, Err):
            record(_OUTCOME_MALFORMED, status=response.status_code, audio=None)
            return audio
        record(_OUTCOME_OK, status=response.status_code, audio=audio.value)
        return audio
