"""Gemini Music adapter — song generation via Google Lyria behind ``MusicProvider``.

Follows the identical contract as ``ElevenLabsMusicProvider``:
- Shape of every call: acquire concurrency semaphore, POST generateContent, parse response,
  emit measurement usage line, return ``Result[RenderedAudio]``.
- **No method raises.** All exceptions are translated to typed ``BayramError`` variants.
- Audio is extracted from the candidate part's ``inlineData`` (base64-encoded).
- Inpainting: Google Lyria does not expose section-level inpainting handles (no stored-song audio
  reference chunk API), so ``inpaint`` cleanly falls back to recomposing the revised plan,
  leaving ``remote_id = None``.
"""

from __future__ import annotations

import asyncio
import base64
from collections.abc import Callable
from datetime import UTC, datetime
from time import perf_counter
from typing import Any, Final

import httpx
import orjson

from bayram.contracts import (
    CompositionPlan,
    CostSource,
    Err,
    HealthState,
    ProviderHealth,
    RenderedAudio,
    Result,
    Vendor,
    VendorOperation,
    err,
    ok,
)
from bayram.errors import (
    BayramError,
    ProviderError,
    ProviderInvalidResponseError,
    ProviderQuotaExhaustedError,
    ProviderRejectedContentError,
)
from bayram.logging import get_logger
from bayram.providers.music.failures import (
    describe_error_body,
    map_status_error,
    map_transport_error,
)
from bayram.providers.music.payload import guard_plan
from bayram.providers.music.usage import (
    MusicUsage,
    log_usage,
)
from bayram.usage import LOGGING_USAGE_SINK, UsageSink, VendorUsage

__all__ = [
    "GeminiMusicProvider",
    "PROVIDER_NAME",
    "DEFAULT_GEMINI_MUSIC_MAX_CONCURRENCY",
    "LYRIA_USD_PER_REQUEST",
    "build_gemini_music_prompt",
]

_LOGGER = get_logger(__name__)

PROVIDER_NAME: Final[str] = "gemini_music"

DEFAULT_GEMINI_MUSIC_MAX_CONCURRENCY: Final[int] = 2
#: Google's published price per Lyria REQUEST — https://ai.google.dev/gemini-api/docs/pricing,
#: read 2026-09-30. Lyria bills a song, not a minute, so a 2.5-minute render of
#: ``lyria-3.5`` costs $0.08, not 2.5 × $0.08. No Lyria model has a free tier. A model absent
#: from this table is recorded UNPRICED unless ``gemini_music_usd_per_request`` names a price:
#: a guessed rate on a vendor-spend card is worse than an empty one.
LYRIA_USD_PER_REQUEST: Final[dict[str, float]] = {
    "lyria-3.5": 0.08,
    "lyria-3-pro-preview": 0.08,
    "lyria-3-clip-preview": 0.04,
}
DEFAULT_HEALTH_TIMEOUT_S: Final[float] = 10.0

API_KEY_HEADER: Final[str] = "x-goog-api-key"
_GENERATE_PATH: Final[str] = "/v1beta/models/{model}:generateContent"
_MODEL_PATH: Final[str] = "/v1beta/models/{model}"
_INTERACTIONS_PATH: Final[str] = "/v1beta/interactions"

#: How Google words an empty prepay balance when it answers 429 rather than 402. Both have
#: been observed (discuss.ai.google.dev, 2026). The shared mapper reads every 429 as a
#: retryable rate limit, which would retry a render the account cannot pay for; these
#: markers turn it into ``ProviderQuotaExhaustedError`` so the router can fail over instead.
_DEPLETED_MARKERS: Final[tuple[str, ...]] = (
    "prepayment credits are depleted",
    "prepayment credit",
    "credits are depleted",
)

_REFUSAL_FINISH_REASONS: Final[frozenset[str]] = frozenset(
    {"SAFETY", "RECITATION", "BLOCKLIST", "PROHIBITED_CONTENT", "SPII"}
)

_OPERATION_COMPOSE: Final[str] = "compose"
_OPERATION_INPAINT: Final[str] = "inpaint"
_OPERATION_HEALTH: Final[str] = "health"

VENDOR_OPERATIONS: Final[dict[str, VendorOperation]] = {
    _OPERATION_COMPOSE: VendorOperation.MUSIC_COMPOSE,
    _OPERATION_INPAINT: VendorOperation.MUSIC_INPAINT,
}

_OUTCOME_OK: Final[str] = "ok"
_OUTCOME_HTTP_ERROR: Final[str] = "http_error"
_OUTCOME_TRANSPORT_ERROR: Final[str] = "transport_error"
_OUTCOME_MALFORMED: Final[str] = "malformed_response"

_MS_PER_S: Final[int] = 1_000
_HTTP_ERROR_FLOOR: Final[int] = 400


def _utc_now() -> datetime:
    return datetime.now(tz=UTC)


def _elapsed_ms(started: float) -> int:
    return int((perf_counter() - started) * _MS_PER_S)


def build_gemini_music_prompt(plan: CompositionPlan) -> str:
    """Compile a CompositionPlan into prompt text suitable for Google Lyria."""
    positive_tags: list[str] = []
    negative_tags: list[str] = []
    lyrics_lines: list[str] = []

    for chunk in plan.chunks:
        for tag in chunk.positive_styles:
            if tag and tag not in positive_tags:
                positive_tags.append(tag)
        for tag in chunk.negative_styles:
            if tag and tag not in negative_tags:
                negative_tags.append(tag)
        text = chunk.text.strip()
        if text:
            lyrics_lines.append(text)

    style_desc = ", ".join(positive_tags) if positive_tags else "celebration song, bright pop"
    duration_s = max(1, plan.total_duration_ms // 1000)

    if plan.is_instrumental:
        prompt = (
            f"Generate an instrumental music track.\n"
            f"Style: {style_desc}\n"
            f"Duration: approximately {duration_s} seconds."
        )
    else:
        lyrics = "\n".join(lyrics_lines)
        prompt = (
            f"Generate a full song with vocals.\n"
            f"Style: {style_desc}\n"
            f"Language: {plan.language.vendor_language.value}\n"
            f"Duration: approximately {duration_s} seconds.\n\n"
            f"Lyrics:\n{lyrics}"
        )

    if negative_tags:
        prompt += f"\n\nAvoid styles: {', '.join(negative_tags)}"

    return prompt


class GeminiMusicProvider:
    """Song generation via Google Lyria behind ``MusicProvider``."""

    name: str = PROVIDER_NAME

    def __init__(
        self,
        *,
        api_key: str,
        base_url: str = "https://generativelanguage.googleapis.com",
        model_id: str = "lyria-3.5",
        max_concurrency: int = DEFAULT_GEMINI_MUSIC_MAX_CONCURRENCY,
        usd_per_request: float | None = None,
        health_timeout_s: float = DEFAULT_HEALTH_TIMEOUT_S,
        client: httpx.AsyncClient | None = None,
        clock: Callable[[], datetime] = _utc_now,
        usage: UsageSink = LOGGING_USAGE_SINK,
    ) -> None:
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")
        self._model_id = model_id
        self._usage = usage
        self._usd_per_request = (
            usd_per_request
            if usd_per_request is not None
            else LYRIA_USD_PER_REQUEST.get(model_id.strip().lower())
        )
        self._health_timeout_s = health_timeout_s
        self._clock = clock
        self._owns_client = client is None
        self._client = client if client is not None else httpx.AsyncClient()
        self._slots = asyncio.Semaphore(max(1, max_concurrency))

    async def aclose(self) -> None:
        """Close the HTTP client if we created it."""
        if self._owns_client:
            await self._client.aclose()

    # -- MusicProvider protocol ---------------------------------------------
    async def compose(
        self, plan: CompositionPlan, *, idempotency_key: str, timeout_s: float
    ) -> Result[RenderedAudio]:
        guarded = guard_plan(plan)
        if isinstance(guarded, Err):
            return guarded
        return await self._post_generate(
            plan=plan,
            operation=_OPERATION_COMPOSE,
            timeout_s=timeout_s,
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
        """Lyria does not expose section inpainting with audio handles; re-composes the plan."""
        guarded = guard_plan(plan)
        if isinstance(guarded, Err):
            return guarded
        return await self._post_generate(
            plan=plan,
            operation=_OPERATION_INPAINT,
            timeout_s=timeout_s,
            idempotency_key=idempotency_key,
            source_song_id=source_song_id,
        )

    async def health(self) -> Result[ProviderHealth]:
        """Check if Gemini models endpoint is reachable."""
        url = f"{self._base_url}{_MODEL_PATH.format(model=self._model_id)}"
        headers = {API_KEY_HEADER: self._api_key, "accept": "application/json"}
        started = perf_counter()
        try:
            response = await self._client.get(
                url, headers=headers, timeout=httpx.Timeout(self._health_timeout_s)
            )
        except httpx.HTTPError as exc:
            transport = map_transport_error(
                exc,
                provider=self.name,
                operation=_OPERATION_HEALTH,
                timeout_s=self._health_timeout_s,
            )
            await self._record_health(
                is_success=False, elapsed_ms=_elapsed_ms(started), error=transport
            )
            return ok(self._health_state(HealthState.UNAVAILABLE, detail=str(exc)))

        if response.status_code >= _HTTP_ERROR_FLOOR:
            failure = map_status_error(response, provider=self.name, operation=_OPERATION_HEALTH)
            await self._record_health(
                is_success=False,
                elapsed_ms=_elapsed_ms(started),
                http_status=response.status_code,
                error=failure,
            )
            if response.status_code in (401, 403):
                return err(failure)
            return ok(self._health_state(HealthState.UNAVAILABLE, detail=str(failure)))

        await self._record_health(
            is_success=True, elapsed_ms=_elapsed_ms(started), http_status=response.status_code
        )
        return ok(self._health_state(HealthState.HEALTHY, detail="reachable"))

    # -- internal POST & processing -----------------------------------------
    async def _post_generate(
        self,
        *,
        plan: CompositionPlan,
        operation: str,
        timeout_s: float,
        idempotency_key: str,
        source_song_id: str | None = None,
    ) -> Result[RenderedAudio]:
        prompt = build_gemini_music_prompt(plan)
        if "lyria" in self._model_id.lower() or not self._model_id.startswith("gemini"):
            url = f"{self._base_url}{_INTERACTIONS_PATH}"
            request_body: dict[str, Any] = {
                "model": self._model_id,
                "input": prompt,
            }
        else:
            url = f"{self._base_url}{_GENERATE_PATH.format(model=self._model_id)}"
            request_body = {
                "contents": [
                    {
                        "role": "user",
                        "parts": [{"text": prompt}],
                    }
                ],
            }
        encoded_body = orjson.dumps(request_body)
        headers = {
            API_KEY_HEADER: self._api_key,
            "content-type": "application/json",
            "x-idempotency-key": idempotency_key,
        }

        started = perf_counter()
        async with self._slots:
            try:
                response = await self._client.post(
                    url,
                    headers=headers,
                    content=encoded_body,
                    timeout=httpx.Timeout(timeout_s),
                )
            except httpx.HTTPError as exc:
                elapsed = _elapsed_ms(started)
                transport = map_transport_error(
                    exc, provider=self.name, operation=operation, timeout_s=timeout_s
                )
                await self._emit_failure(
                    plan=plan,
                    operation=operation,
                    outcome=_OUTCOME_TRANSPORT_ERROR,
                    elapsed_ms=elapsed,
                    error=transport,
                    source_song_id=source_song_id,
                )
                return err(transport)

        elapsed = _elapsed_ms(started)

        if response.status_code >= _HTTP_ERROR_FLOOR:
            status_err = _map_gemini_status(response, provider=self.name, operation=operation)
            await self._emit_failure(
                plan=plan,
                operation=operation,
                outcome=_OUTCOME_HTTP_ERROR,
                elapsed_ms=elapsed,
                http_status=response.status_code,
                error=status_err,
                source_song_id=source_song_id,
            )
            return err(status_err)

        # Parse JSON and extract audio bytes
        try:
            payload = orjson.loads(response.content)
        except orjson.JSONDecodeError as exc:
            malformed = ProviderInvalidResponseError(
                f"vendor returned malformed JSON: {describe_error_body(response.content)}",
                provider=self.name,
                cause=exc,
            )
            await self._emit_failure(
                plan=plan,
                operation=operation,
                outcome=_OUTCOME_MALFORMED,
                elapsed_ms=elapsed,
                http_status=response.status_code,
                error=malformed,
                source_song_id=source_song_id,
            )
            return err(malformed)

        # Check for safety or policy refusal
        refusal = self._check_refusal(payload)
        if refusal is not None:
            await self._emit_failure(
                plan=plan,
                operation=operation,
                outcome=_OUTCOME_HTTP_ERROR,
                elapsed_ms=elapsed,
                http_status=response.status_code,
                error=refusal.error,
                source_song_id=source_song_id,
            )
            return refusal

        # Extract audio inlineData
        audio_data, mime_type = self._extract_audio(payload)
        if audio_data is None:
            no_audio_err = ProviderInvalidResponseError(
                "Gemini music response contained no audio data in parts",
                provider=self.name,
            )
            await self._emit_failure(
                plan=plan,
                operation=operation,
                outcome=_OUTCOME_MALFORMED,
                elapsed_ms=elapsed,
                http_status=response.status_code,
                error=no_audio_err,
                source_song_id=source_song_id,
            )
            return err(no_audio_err)

        # Extract token usage if returned
        prompt_tokens, completion_tokens = self._extract_tokens(payload)

        cost_usd, cost_source = self._estimated_cost()

        rendered = RenderedAudio(
            data=audio_data,
            mime=mime_type or "audio/mpeg",
            duration_s=float(plan.total_duration_ms) / 1000.0,
            remote_id=None,
            cost_usd=cost_usd or 0.0,
            cost_source=cost_source or CostSource.ESTIMATED,
            provider=self.name,
        )

        await self._emit_success(
            plan=plan,
            operation=operation,
            audio=rendered,
            elapsed_ms=elapsed,
            http_status=response.status_code,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            source_song_id=source_song_id,
        )
        return ok(rendered)

    def _check_refusal(self, payload: dict[str, Any]) -> Err | None:
        prompt_feedback = payload.get("promptFeedback")
        block_reason = (
            prompt_feedback.get("blockReason") if isinstance(prompt_feedback, dict) else None
        )

        error_info = payload.get("error")
        if isinstance(error_info, dict):
            msg = str(error_info.get("message") or "generation refused")
            code = str(error_info.get("code") or "error")
            return err(
                ProviderRejectedContentError(
                    f"gemini music refused to generate: {msg}",
                    provider=self.name,
                    context={"code": code, "message": msg},
                )
            )

        candidates = payload.get("candidates")
        finish_reason = None
        if isinstance(candidates, list) and candidates:
            first_candidate = candidates[0]
            if isinstance(first_candidate, dict):
                finish_reason = first_candidate.get("finishReason")

        reason = block_reason or (
            finish_reason if finish_reason in _REFUSAL_FINISH_REASONS else None
        )
        if reason is None:
            return None
        return err(
            ProviderRejectedContentError(
                f"gemini music refused to generate: {reason}",
                provider=self.name,
                context={"block_reason": block_reason, "finish_reason": finish_reason},
            )
        )

    def _extract_audio(self, payload: dict[str, Any]) -> tuple[bytes | None, str | None]:
        # Handle Interactions API output steps: steps[].content[].type == "audio"
        steps = payload.get("steps")
        if isinstance(steps, list):
            for step in steps:
                if not isinstance(step, dict):
                    continue
                content = step.get("content")
                if isinstance(content, list):
                    for item in content:
                        if isinstance(item, dict) and item.get("type") == "audio":
                            b64_data = item.get("data")
                            mime = item.get("mime_type", "audio/mpeg")
                            if isinstance(b64_data, str) and b64_data:
                                try:
                                    decoded = base64.b64decode(b64_data)
                                    if decoded:
                                        return decoded, mime
                                except Exception:
                                    pass

        # Handle generateContent candidates: candidates[0].content.parts[].inlineData
        candidates = payload.get("candidates")
        if isinstance(candidates, list) and candidates:
            first = candidates[0]
            if isinstance(first, dict):
                content = first.get("content")
                if isinstance(content, dict):
                    parts = content.get("parts")
                    if isinstance(parts, list):
                        for part in parts:
                            if not isinstance(part, dict):
                                continue
                            inline_data = part.get("inlineData")
                            if isinstance(inline_data, dict):
                                b64_data = inline_data.get("data")
                                mime = inline_data.get("mimeType", "audio/mpeg")
                                if isinstance(b64_data, str) and b64_data:
                                    try:
                                        decoded = base64.b64decode(b64_data)
                                        if decoded:
                                            return decoded, mime
                                    except Exception:
                                        pass
        return None, None

    def _extract_tokens(self, payload: dict[str, Any]) -> tuple[int | None, int | None]:
        usage = payload.get("usage")
        if isinstance(usage, dict):
            pt = usage.get("total_input_tokens")
            ct = usage.get("total_output_tokens")
            return (
                pt if isinstance(pt, int) and pt >= 0 else None,
                ct if isinstance(ct, int) and ct >= 0 else None,
            )

        metadata = payload.get("usageMetadata")
        if isinstance(metadata, dict):
            prompt_tokens = metadata.get("promptTokenCount")
            completion_tokens = metadata.get("candidatesTokenCount")
            pt = prompt_tokens if isinstance(prompt_tokens, int) and prompt_tokens >= 0 else None
            ct = (
                completion_tokens
                if isinstance(completion_tokens, int) and completion_tokens >= 0
                else None
            )
            return pt, ct
        return None, None

    def _estimated_cost(self) -> tuple[float, CostSource] | tuple[None, None]:
        """One flat price per SUCCESSFUL request. Failures are never priced.

        Google does not bill a refused or failed generation, so only the success path calls
        this. A zero or unknown price stays unpriced — ``NULL``, not ``0.0`` — so the row is
        not read as a free render.
        """
        if self._usd_per_request is None or self._usd_per_request <= 0:
            return (None, None)
        return (self._usd_per_request, CostSource.ESTIMATED)

    async def _emit_success(
        self,
        *,
        plan: CompositionPlan,
        operation: str,
        audio: RenderedAudio,
        elapsed_ms: int,
        http_status: int,
        prompt_tokens: int | None,
        completion_tokens: int | None,
        source_song_id: str | None = None,
    ) -> None:
        cost_usd, cost_source = self._estimated_cost()
        log_usage(
            _LOGGER,
            MusicUsage(
                provider=self.name,
                operation=operation,
                model_id=self._model_id,
                output_format=audio.mime,
                chunk_count=len(plan.chunks),
                total_duration_ms=plan.total_duration_ms,
                elapsed_ms=elapsed_ms,
                outcome=_OUTCOME_OK,
                http_status=http_status,
                response_bytes=len(audio.data),
                remote_id=None,
                estimated_cost_usd=cost_usd or 0.0,
                name_chunk_index=plan.name_chunk_index,
                source_song_id=source_song_id,
            ),
        )
        vendor_op = VENDOR_OPERATIONS.get(operation, VendorOperation.MUSIC_COMPOSE)
        await self._usage.record(
            VendorUsage(
                vendor=Vendor.GEMINI,
                operation=vendor_op,
                provider=self.name,
                is_success=True,
                model_id=self._model_id,
                http_status=http_status,
                latency_ms=elapsed_ms,
                audio_ms=plan.total_duration_ms,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                total_tokens=(prompt_tokens or 0) + (completion_tokens or 0)
                if prompt_tokens or completion_tokens
                else None,
                cost_usd=cost_usd,
                cost_source=cost_source,
            )
        )

    async def _emit_failure(
        self,
        *,
        plan: CompositionPlan,
        operation: str,
        outcome: str,
        elapsed_ms: int,
        http_status: int | None = None,
        error: BayramError | None = None,
        source_song_id: str | None = None,
    ) -> None:
        log_usage(
            _LOGGER,
            MusicUsage(
                provider=self.name,
                operation=operation,
                model_id=self._model_id,
                output_format="",
                chunk_count=len(plan.chunks),
                total_duration_ms=plan.total_duration_ms,
                elapsed_ms=elapsed_ms,
                outcome=outcome,
                http_status=http_status,
                response_bytes=0,
                remote_id=None,
                estimated_cost_usd=0.0,
                name_chunk_index=plan.name_chunk_index,
                source_song_id=source_song_id,
            ),
        )
        vendor_op = VENDOR_OPERATIONS.get(operation, VendorOperation.MUSIC_COMPOSE)
        await self._usage.record(
            VendorUsage(
                vendor=Vendor.GEMINI,
                operation=vendor_op,
                provider=self.name,
                is_success=False,
                model_id=self._model_id,
                http_status=http_status,
                error_code=error.error_code.value if error is not None else None,
                latency_ms=elapsed_ms,
                # No audio came back, so none is recorded: a failed render counted as
                # rendered minutes inflated the units-per-song figure.
            )
        )

    def _health_state(self, state: HealthState, *, detail: str) -> ProviderHealth:
        return ProviderHealth(name=self.name, state=state, as_of=self._clock(), detail=detail)

    async def _record_health(
        self,
        *,
        is_success: bool,
        elapsed_ms: int,
        http_status: int | None = None,
        error: ProviderError | None = None,
    ) -> None:
        await self._usage.record(
            VendorUsage(
                vendor=Vendor.GEMINI,
                operation=VendorOperation.HEALTH,
                provider=self.name,
                is_success=is_success,
                model_id=self._model_id,
                http_status=http_status,
                error_code=error.error_code.value if error is not None else None,
                latency_ms=elapsed_ms,
            )
        )


def _map_gemini_status(response: httpx.Response, *, provider: str, operation: str) -> ProviderError:
    """``map_status_error``, plus Google's 429 that means "prepay balance is empty"."""
    mapped = map_status_error(response, provider=provider, operation=operation)
    if response.status_code != 429:
        return mapped
    detail = describe_error_body(response.content).lower()
    if not any(marker in detail for marker in _DEPLETED_MARKERS):
        return mapped
    return ProviderQuotaExhaustedError(
        f"gemini prepay credits are depleted during {operation} ({detail})",
        provider=provider,
        context={"operation": operation, "http_status": 429},
    )
