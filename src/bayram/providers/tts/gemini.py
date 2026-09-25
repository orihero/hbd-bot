"""Gemini 3.8 Flash TTS behind ``NarrationProvider`` (IMAGE_VIDEO_SPEC §5.1, §5.2; D23).

One call speaks one short video line in a house voice. The wire shape, re-checked against the
speech-generation docs page at M4 build time (2026-09-25) and pinned by a recorded-fixture
test:

* ``POST {base}/v1beta/interactions`` with the key in ``x-goog-api-key`` — never in the URL;
* ``input`` is one ``user_input`` turn whose single text part is the line, with the delivery
  style as a ``speech_metadata`` annotation — **never in the text**, where it would be spoken;
* ``response_format`` asks for ``audio/wav`` at 24 kHz, ``generation_config.speech_config``
  names the house voice;
* the answer is JSON whose ``steps[].content[]`` holds an ``audio`` part with base64 ``data``
  (a unary WAV, 24 kHz mono 16-bit, RIFF header included). A raw ``audio/*`` body is accepted
  too, so a proxy that unwraps it does not break us.

**Keys come from :class:`~bayram.providers.tts.key_pool.GeminiKeyPool`** and appear in exactly
one place, the request header. A 429 cools the key and the next is tried; a 401/403 (or
Google's invalid-key 400) disables it for a day; a 5xx or timeout gets one more key. When no
key is usable the call returns ``Err`` with :data:`POOL_EXHAUSTED_CONTEXT_KEY` set, and the
narration router falls back to ElevenLabs. **A content refusal is not a key fault**: it is
``ProviderRejectedContentError``, final, and never offered to another key or vendor (§5.2).

**No paid-tier gate** (owner, Q17, 2026-09-24): pool keys may be free-tier and serve every
job, beta and paying alike. Google may train on the narration text; the Privacy notice says
so (Appendix A).

**Every HTTP call is measured**, per key attempt, as a ``gemini_tts`` speech row. Cost is
audio output tokens (25 per second) plus input tokens at the date-effective rate, which
doubles on 2027-01-01. The vendor's own ``usage`` token counts make the cost ``DERIVED``; with
none, tokens are computed from the WAV duration and the cost is ``ESTIMATED``.
"""

from __future__ import annotations

import base64
import binascii
import io
import wave
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import date, datetime
from time import perf_counter
from typing import Any, Final

import httpx
from pydantic import BaseModel, ConfigDict

from bayram.contracts import (
    CostSource,
    Err,
    HealthState,
    Language,
    NarrationRequest,
    ProviderHealth,
    RenderedAudio,
    Result,
    Script,
    Vendor,
    VendorOperation,
    VoiceGender,
    err,
    ok,
)
from bayram.errors import (
    BayramError,
    ConfigError,
    ProviderInvalidResponseError,
    ProviderRateLimitedError,
    ProviderRejectedContentError,
    ProviderTimeoutError,
    ProviderUnavailableError,
)
from bayram.logging import get_logger
from bayram.names.translit import transliterate
from bayram.providers.tts.key_pool import GeminiKeyPool, KeyState, PoolKey, parse_retry_after
from bayram.providers.tts.transport import (
    RETRY_AFTER_CONTEXT_KEY,
    http_status_of,
    send_request,
    utc_now,
)
from bayram.usage import LOGGING_USAGE_SINK, UsageSink, VendorUsage

__all__ = [
    "PROVIDER_NAME",
    "DEFAULT_BASE_URL",
    "DEFAULT_MODEL",
    "INTERACTIONS_PATH",
    "API_KEY_HEADER",
    "SAMPLE_RATE_HZ",
    "AUDIO_TOKENS_PER_SECOND",
    "POOL_EXHAUSTED_CONTEXT_KEY",
    "GeminiTtsPricing",
    "GeminiTtsProvider",
    "is_pool_exhausted",
]

_LOG = get_logger(__name__)

PROVIDER_NAME: Final[str] = "gemini_tts"
DEFAULT_BASE_URL: Final[str] = "https://generativelanguage.googleapis.com"
DEFAULT_MODEL: Final[str] = "gemini-3.8-flash-tts"
INTERACTIONS_PATH: Final[str] = "/v1beta/interactions"
API_KEY_HEADER: Final[str] = "x-goog-api-key"
SAMPLE_RATE_HZ: Final[int] = 24_000
AUDIO_TOKENS_PER_SECOND: Final[int] = 25

#: Set on the ``Err`` returned when every key is cooling or disabled — the fallback trigger.
POOL_EXHAUSTED_CONTEXT_KEY: Final[str] = "pool_exhausted"

_WAV_MIME: Final[str] = "audio/wav"
_STATUS_BAD_REQUEST: Final[int] = 400
_STATUS_UNAUTHORIZED: Final[int] = 401
_STATUS_FORBIDDEN: Final[int] = 403
_STATUS_TOO_MANY_REQUESTS: Final[int] = 429
_MS_PER_S: Final[int] = 1_000
_BYTES_PER_SAMPLE: Final[int] = 2
_RIFF_HEADER_BYTES: Final[int] = 44
_TOKENS_PER_MILLION: Final[float] = 1_000_000.0
_USD_ROUNDING_PLACES: Final[int] = 6

#: Google answers a bad or expired key with 400 INVALID_ARGUMENT, not 401. It is a key fault.
_INVALID_KEY_MARKERS: Final[tuple[str, ...]] = (
    "api_key_invalid",
    "api key not valid",
    "api key expired",
)
#: How a Gemini safety refusal reads, on an error body or an answer with no audio (§5.1).
_REFUSAL_MARKERS: Final[tuple[str, ...]] = (
    "safety",
    "prohibited_content",
    "blocklist",
    "spii",
    "recitation",
)


def is_pool_exhausted(error: BayramError) -> bool:
    return error.context.get(POOL_EXHAUSTED_CONTEXT_KEY) is True


def _elapsed_ms(started: float) -> int:
    return int((perf_counter() - started) * _MS_PER_S)


def _has_marker(text: str, markers: tuple[str, ...]) -> bool:
    lowered = text.casefold()
    return any(marker in lowered for marker in markers)


@dataclass(frozen=True, slots=True)
class GeminiTtsPricing:
    """USD per million tokens, and the date the rate doubles (§5.1 "Metering").

    Paid-tier list prices; a free-tier key is billed nothing, but the row still carries what
    the call WOULD cost so a collapse to one billed project (D23 trigger) can be costed.
    """

    input_usd_per_m: float = 0.50
    audio_output_usd_per_m: float = 9.00
    doubles_on: date = date(2027, 1, 1)

    def cost_for(self, *, input_tokens: int, output_tokens: int, on: date) -> float:
        factor = 2.0 if on >= self.doubles_on else 1.0
        usd = (
            (input_tokens * self.input_usd_per_m + output_tokens * self.audio_output_usd_per_m)
            * factor
            / _TOKENS_PER_MILLION
        )
        return round(usd, _USD_ROUNDING_PLACES)


class _Usage(BaseModel):
    model_config = ConfigDict(extra="ignore")

    total_input_tokens: int | None = None
    total_output_tokens: int | None = None


class _ContentPart(BaseModel):
    model_config = ConfigDict(extra="ignore")

    type: str | None = None
    data: str | None = None
    mime_type: str | None = None


class _Step(BaseModel):
    model_config = ConfigDict(extra="ignore")

    type: str | None = None
    content: list[_ContentPart] | None = None


class _Fault(BaseModel):
    model_config = ConfigDict(extra="ignore")

    code: str | int | None = None
    message: str | None = None


class _Interaction(BaseModel):
    """The fields of an Interaction this adapter reads. Everything else is ignored."""

    model_config = ConfigDict(extra="ignore")

    id: str | None = None
    status: str | None = None
    steps: list[_Step] | None = None
    usage: _Usage | None = None
    errors: list[_Fault] | None = None


@dataclass(frozen=True, slots=True)
class _Speech:
    data: bytes
    remote_id: str | None
    input_tokens: int | None
    output_tokens: int | None


class GeminiTtsProvider:
    """``NarrationProvider`` over the Interactions API, drawing keys from the pool."""

    name: str = PROVIDER_NAME

    def __init__(
        self,
        *,
        pool: GeminiKeyPool,
        voices: Mapping[VoiceGender, str],
        model_id: str = DEFAULT_MODEL,
        base_url: str = DEFAULT_BASE_URL,
        pricing: GeminiTtsPricing | None = None,
        client: httpx.AsyncClient | None = None,
        clock: Callable[[], datetime] = utc_now,
        usage: UsageSink = LOGGING_USAGE_SINK,
    ) -> None:
        self._pool = pool
        self._voices = {gender: voice.strip() for gender, voice in voices.items() if voice.strip()}
        self._model_id = model_id
        self._base_url = base_url.rstrip("/")
        self._pricing = pricing or GeminiTtsPricing()
        self._clock = clock
        self._usage = usage
        self._owns_client = client is None
        self._client = client if client is not None else httpx.AsyncClient()

    def __repr__(self) -> str:
        return f"GeminiTtsProvider(model={self._model_id!r}, pool={self._pool!r})"

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    # -- NarrationProvider --------------------------------------------------
    async def narrate(
        self, request: NarrationRequest, *, idempotency_key: str, timeout_s: float
    ) -> Result[RenderedAudio]:
        voice = self._voices.get(request.gender)
        if voice is None:
            # The house voices are chosen in the M4 listening test (Q14); until then the
            # router's fallback speaks every line.
            return err(
                ConfigError(
                    f"no Gemini house voice is configured for {request.gender.value}",
                    context={"provider": self.name, "gender": request.gender.value},
                )
            )
        body = self._body(request, voice=voice)
        context: dict[str, Any] = {
            "operation": "narrate",
            "language": request.language.value,
            "gender": request.gender.value,
            "idempotency_key": idempotency_key,
        }
        tried: list[str] = []
        is_server_retry_spent = False
        while True:
            key = await self._pool.pick(exclude=tried)
            if key is None:
                return err(self._exhausted(tried))
            tried.append(key.ref)
            outcome = await self._attempt(key, body, timeout_s=timeout_s, context=context)
            if not isinstance(outcome, Err):
                return outcome
            error = outcome.error
            status = http_status_of(error)
            if status == _STATUS_TOO_MANY_REQUESTS:
                await self._pool.mark_rate_limited(
                    key, retry_after_s=parse_retry_after(error.context.get(RETRY_AFTER_CONTEXT_KEY))
                )
                continue
            if self._is_key_rejected(error, status):
                await self._pool.mark_disabled(key, reason=f"http_{status}")
                continue
            if isinstance(error, ProviderUnavailableError | ProviderTimeoutError):
                await self._pool.mark_server_error(key)
                if not is_server_retry_spent:
                    is_server_retry_spent = True  # §5.2: "5xx/timeout → try next key once"
                    continue
            return outcome

    async def health(self) -> Result[ProviderHealth]:
        """From the pool's own state — no call, so a probe never spends a key's quota."""
        rows = await self._pool.snapshot()
        available = sum(1 for row in rows if row.state is KeyState.AVAILABLE)
        if not rows or not self._voices:
            state = HealthState.UNAVAILABLE
        elif available == len(rows):
            state = HealthState.HEALTHY
        elif available:
            state = HealthState.DEGRADED
        else:
            state = HealthState.UNAVAILABLE
        detail = f"{available}/{len(rows)} keys available"
        if not self._voices:
            detail += "; no house voice configured"
        return ok(ProviderHealth(name=self.name, state=state, as_of=self._clock(), detail=detail))

    # -- one key, one call ----------------------------------------------------
    async def _attempt(
        self,
        key: PoolKey,
        body: Mapping[str, Any],
        *,
        timeout_s: float,
        context: Mapping[str, Any],
    ) -> Result[RenderedAudio]:
        call_context = {**context, "key_ref": key.ref}
        started = perf_counter()
        response = await send_request(
            self._client,
            provider=self.name,
            method="POST",
            url=self._base_url + INTERACTIONS_PATH,
            timeout_s=timeout_s,
            headers={API_KEY_HEADER: key.secret, "accept": "application/json"},
            json_body=body,
            context=call_context,
        )
        if isinstance(response, Err):
            error = self._refusal_or(response.error)
            await self._record_failure(error, latency_ms=_elapsed_ms(started))
            return err(error)

        speech = self._speech_of(response.value, context=call_context)
        if isinstance(speech, Err):
            await self._record_failure(
                speech.error,
                latency_ms=_elapsed_ms(started),
                http_status=response.value.status_code,
                response_bytes=len(response.value.content),
            )
            return speech
        await self._pool.mark_ok(key)
        return ok(
            await self._rendered(
                speech.value,
                http_status=response.value.status_code,
                latency_ms=_elapsed_ms(started),
            )
        )

    def _speech_of(
        self, response: httpx.Response, *, context: Mapping[str, Any]
    ) -> Result[_Speech]:
        content_type = response.headers.get("content-type", "").split(";")[0].strip().casefold()
        if content_type.startswith("audio/"):
            if not response.content:
                return err(self._invalid("an empty audio body", context))
            return ok(_Speech(response.content, None, None, None))
        try:
            interaction = _Interaction.model_validate(response.json())
        except ValueError as exc:  # JSONDecodeError and pydantic's ValidationError alike
            return err(self._invalid("a body that is not an Interaction", context, cause=exc))
        for step in interaction.steps or ():
            for part in step.content or ():
                if part.type == "audio" and part.data:
                    try:
                        data = base64.b64decode(part.data, validate=True)
                    except (binascii.Error, ValueError) as exc:
                        return err(self._invalid("audio that is not base64", context, cause=exc))
                    if not data:
                        return err(self._invalid("an empty audio part", context))
                    usage = interaction.usage or _Usage()
                    return ok(
                        _Speech(
                            data=data,
                            remote_id=interaction.id,
                            input_tokens=usage.total_input_tokens,
                            output_tokens=usage.total_output_tokens,
                        )
                    )
        # No audio at all. A refusal says so in its errors or status; anything else is a
        # malformed answer, which is retryable and not the customer's fault.
        faults = " ".join(
            f"{fault.code or ''} {fault.message or ''}" for fault in interaction.errors or ()
        )
        if _has_marker(f"{interaction.status or ''} {faults}", _REFUSAL_MARKERS):
            return err(
                ProviderRejectedContentError(
                    f"{self.name} refused the line on content grounds",
                    provider=self.name,
                    context={**context, "status": interaction.status, "faults": faults[:200]},
                )
            )
        return err(
            self._invalid(
                f"an Interaction with no audio (status {interaction.status or 'unknown'})",
                {**context, "faults": faults[:200]},
            )
        )

    # -- helpers ------------------------------------------------------------
    def _body(self, request: NarrationRequest, *, voice: str) -> dict[str, Any]:
        part: dict[str, Any] = {"type": "text", "text": _speakable(request)}
        if request.style:
            part["annotations"] = [{"type": "speech_metadata", "style": request.style}]
        return {
            "model": self._model_id,
            "input": [{"type": "user_input", "content": [part]}],
            "response_format": {
                "type": "audio",
                "mime_type": _WAV_MIME,
                "sample_rate": SAMPLE_RATE_HZ,
            },
            "generation_config": {"speech_config": [{"voice": voice}]},
        }

    def _is_key_rejected(self, error: BayramError, status: int | None) -> bool:
        if status in (_STATUS_UNAUTHORIZED, _STATUS_FORBIDDEN):
            return True
        excerpt = str(error.context.get("body_excerpt", ""))
        return status == _STATUS_BAD_REQUEST and _has_marker(excerpt, _INVALID_KEY_MARKERS)

    def _refusal_or(self, error: BayramError) -> BayramError:
        """A 4xx that is Gemini's safety block, typed as the refusal it is (§5.1)."""
        status = http_status_of(error)
        excerpt = str(error.context.get("body_excerpt", ""))
        if (
            status is not None
            and _STATUS_BAD_REQUEST <= status < _STATUS_TOO_MANY_REQUESTS
            and status not in (_STATUS_UNAUTHORIZED, _STATUS_FORBIDDEN)
            and not isinstance(error, ProviderRejectedContentError)
            and _has_marker(excerpt, _REFUSAL_MARKERS)
        ):
            return ProviderRejectedContentError(
                f"{self.name} refused the line on content grounds",
                provider=self.name,
                context=error.context,
                cause=error,
            )
        return error

    def _exhausted(self, tried: list[str]) -> BayramError:
        return ProviderRateLimitedError(
            f"every {self.name} key is cooling or disabled",
            provider=self.name,
            context={POOL_EXHAUSTED_CONTEXT_KEY: True, "tried_key_refs": list(tried)},
        )

    def _invalid(
        self, what: str, context: Mapping[str, Any], *, cause: BaseException | None = None
    ) -> BayramError:
        return ProviderInvalidResponseError(
            f"{self.name} returned {what}", provider=self.name, context=context, cause=cause
        )

    async def _rendered(
        self, speech: _Speech, *, http_status: int, latency_ms: int
    ) -> RenderedAudio:
        duration_s = _wav_duration_s(speech.data)
        output_tokens = speech.output_tokens
        input_tokens = speech.input_tokens
        is_vendor_counted = output_tokens is not None
        if output_tokens is None:
            output_tokens = max(round(duration_s * AUDIO_TOKENS_PER_SECOND), 1)
        cost_usd = self._pricing.cost_for(
            input_tokens=input_tokens or 0, output_tokens=output_tokens, on=self._clock().date()
        )
        cost_source = CostSource.DERIVED if is_vendor_counted else CostSource.ESTIMATED
        await self._usage.record(
            VendorUsage(
                vendor=Vendor.GEMINI_TTS,
                operation=VendorOperation.SPEECH_SYNTHESIS,
                provider=self.name,
                is_success=True,
                model_id=self._model_id,
                http_status=http_status,
                latency_ms=latency_ms,
                prompt_tokens=input_tokens,
                completion_tokens=output_tokens,
                audio_ms=int(duration_s * _MS_PER_S),
                response_bytes=len(speech.data),
                cost_usd=cost_usd,
                cost_source=cost_source,
            )
        )
        return RenderedAudio(
            data=speech.data,
            mime=_WAV_MIME,
            duration_s=duration_s,
            remote_id=speech.remote_id,
            cost_usd=cost_usd,
            cost_source=cost_source,
        )

    async def _record_failure(
        self,
        error: BayramError,
        *,
        latency_ms: int,
        http_status: int | None = None,
        response_bytes: int | None = None,
    ) -> None:
        await self._usage.record(
            VendorUsage(
                vendor=Vendor.GEMINI_TTS,
                operation=VendorOperation.SPEECH_SYNTHESIS,
                provider=self.name,
                is_success=False,
                model_id=self._model_id,
                http_status=http_status if http_status is not None else http_status_of(error),
                error_code=error.error_code.value,
                latency_ms=latency_ms,
                response_bytes=response_bytes,
            )
        )


def _speakable(request: NarrationRequest) -> str:
    """The text as synthesised: Uzbek Cyrillic goes to Latin first (§5.1)."""
    if request.language is Language.UZ_CYRL:
        return transliterate(request.text, target=Script.LATIN, language=Language.UZ_LATN)
    return request.text


def _wav_duration_s(data: bytes) -> float:
    """Measured from the RIFF header; estimated from 24 kHz 16-bit mono when it cannot be read.

    The §5.3 ffprobe step measures again before mux, so the estimate only feeds metering.
    """
    try:
        with wave.open(io.BytesIO(data), "rb") as reader:
            frames = reader.getnframes()
            rate = reader.getframerate()
        if frames > 0 and rate > 0:
            return frames / rate
    except (wave.Error, EOFError):
        pass
    samples = max(len(data) - _RIFF_HEADER_BYTES, _BYTES_PER_SAMPLE) / _BYTES_PER_SAMPLE
    return samples / SAMPLE_RATE_HZ
