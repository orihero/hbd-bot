"""Gemini adapter — the primary LLM. Implements ``bayram.contracts.LlmProvider``.

Structured mode is requested properly (``responseMimeType`` + ``responseSchema``), and
the parse is *still* defended, because a schema-constrained model that hits the output
token cap returns a truncated object with ``finishReason: MAX_TOKENS`` and a 200 status.
That case is a parse problem, not a transport problem, and it is why ``parse_model_json``
exists downstream of a successful HTTP call.

Usage is measured on the same terms as the OpenAI-compatible adapter, through the same
``UsageSink`` seam, but with one difference worth naming: Gemini's ``usageMetadata``
reports token counts and no price. There is no ``usage.cost`` equivalent to prefer, so a
Gemini row is DERIVED when this deployment configured a rate card and carries no cost at
all when it did not. Never a zero — see ``bayram.providers.llm.pricing``.
"""

from __future__ import annotations

from time import perf_counter
from typing import Any, Final

import httpx
from pydantic import BaseModel

from bayram.contracts import (
    CostSource,
    Err,
    HealthState,
    LlmRequest,
    ProviderHealth,
    Result,
    Vendor,
    VendorOperation,
    err,
    ok,
)
from bayram.errors import BayramError, ProviderRejectedContentError
from bayram.logging import get_logger
from bayram.providers.llm.json_schema import to_gemini_schema
from bayram.providers.llm.parsing import parse_model_json
from bayram.providers.llm.pricing import TokenPricing
from bayram.providers.llm.transport import read_path, read_str, request_json
from bayram.providers.llm.utils import health_state_for, utc_now
from bayram.usage import LOGGING_USAGE_SINK, UsageSink, VendorUsage

__all__ = ["GeminiLlmProvider", "PROVIDER_NAME"]

_LOG = get_logger(__name__)

PROVIDER_NAME: Final[str] = "gemini"

_GENERATE_PATH: Final[str] = "/v1beta/models/{model}:generateContent"
_MODEL_PATH: Final[str] = "/v1beta/models/{model}"
_API_KEY_HEADER: Final[str] = "x-goog-api-key"

#: The accounting block on a ``generateContent`` response. Always returned; never asked
#: for, which is why there is no Gemini counterpart to OpenRouter's ``usage.include``.
_USAGE_METADATA: Final[str] = "usageMetadata"

#: Finish reasons that mean "we stopped you", not "you ran out of room".
_REFUSAL_FINISH_REASONS: Final[frozenset[str]] = frozenset(
    {"SAFETY", "RECITATION", "BLOCKLIST", "PROHIBITED_CONTENT", "SPII"}
)
_HEALTH_TIMEOUT_S: Final[float] = 10.0

_MS_PER_S: Final[float] = 1_000.0

#: ``request_json`` hands back a decoded body rather than a response, so the success path
#: has no status object to read. See the same constant in ``openai_compat``.
_HTTP_OK: Final[int] = 200


def _elapsed_ms(started: float) -> int:
    """Whole milliseconds since ``started``. The unit ``vendor_usage.latency_ms`` stores."""
    return int((perf_counter() - started) * _MS_PER_S)


def _token_count(value: Any) -> int | None:
    """A usage integer we are willing to store, or ``None`` when nobody counted.

    ``bool`` is excluded because it is an ``int`` in Python. Absent stays absent: a
    response with no ``usageMetadata`` records ``None``, not ``0``.
    """
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        return None
    # Re-stated as an int rather than returned straight from the untyped payload: the
    # value is one an operator will read as a token count, and it leaves here typed.
    return int(value)


def _status_from(error: BayramError | None) -> int | None:
    """The HTTP status the transport recorded on a typed error, if it saw one."""
    if error is None:
        return None
    status = error.context.get("status_code")
    return status if isinstance(status, int) and not isinstance(status, bool) else None


class GeminiLlmProvider:
    """Gemini behind ``LlmProvider``. Holds no state beyond its client and its config."""

    name: str = PROVIDER_NAME

    def __init__(
        self,
        *,
        api_key: str,
        base_url: str,
        model_id: str,
        client: httpx.AsyncClient | None = None,
        is_fallback: bool = False,
        pricing: TokenPricing | None = None,
        usage: UsageSink = LOGGING_USAGE_SINK,
    ) -> None:
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")
        self._model_id = model_id
        self._client = client if client is not None else httpx.AsyncClient()
        self._is_fallback = is_fallback
        self._pricing = pricing if pricing is not None else TokenPricing()
        self._usage = usage

    # -- LlmProvider --------------------------------------------------------
    async def generate_json[M: BaseModel](
        self,
        request: LlmRequest,
        response_model: type[M],
        *,
        timeout_s: float,
    ) -> Result[M]:
        url = self._base_url + _GENERATE_PATH.format(model=self._model_id)
        body = self._build_body(request, response_model)
        started = perf_counter()
        response = await request_json(
            self._client,
            method="POST",
            url=url,
            headers={_API_KEY_HEADER: self._api_key, "content-type": "application/json"},
            provider=self.name,
            timeout_s=timeout_s,
            json_body=body,
        )
        # Measured before the parse: the figure means "how long Gemini took".
        latency_ms = _elapsed_ms(started)
        if isinstance(response, Err):
            await self._record_chat(
                payload=None, error=response.error, http_status=None, latency_ms=latency_ms
            )
            return response

        payload = response.value
        result = self._read(payload, response_model)
        # One record per call, after the outcome is known: a safety block and a truncated
        # object both arrived over a 200 that spent tokens, and that spend is real.
        await self._record_chat(
            payload=payload,
            error=result.error if isinstance(result, Err) else None,
            http_status=_HTTP_OK,
            latency_ms=latency_ms,
        )
        return result

    async def health(self) -> Result[ProviderHealth]:
        url = self._base_url + _MODEL_PATH.format(model=self._model_id)
        started = perf_counter()
        response = await request_json(
            self._client,
            method="GET",
            url=url,
            headers={_API_KEY_HEADER: self._api_key},
            provider=self.name,
            timeout_s=_HEALTH_TIMEOUT_S,
        )
        latency_ms = _elapsed_ms(started)
        if isinstance(response, Err):
            await self._record_health(error=response.error, latency_ms=latency_ms)
            return ok(
                ProviderHealth(
                    name=self.name,
                    state=health_state_for(response.error),
                    as_of=utc_now(),
                    detail=response.error.operator_message,
                )
            )
        await self._record_health(error=None, latency_ms=latency_ms)
        return ok(ProviderHealth(name=self.name, state=HealthState.HEALTHY, as_of=utc_now()))

    # -- internals ----------------------------------------------------------
    def _read[M: BaseModel](self, payload: Any, response_model: type[M]) -> Result[M]:
        """Turn one decoded 200 body into a model or a typed ``Err``. No I/O, no clock."""
        blocked = self._refusal(payload)
        if blocked is not None:
            return blocked

        finish_reason = read_str(payload, "candidates", 0, "finishReason")
        text = _join_parts(read_path(payload, "candidates", 0, "content", "parts"))
        if finish_reason and finish_reason not in ("STOP", "MAX_TOKENS"):
            _LOG.warning(
                "gemini finished with %s; attempting to parse anyway",
                finish_reason,
                extra={"provider": self.name, "finish_reason": finish_reason},
            )
        return parse_model_json(
            text, response_model, provider=self.name, finish_reason=finish_reason
        )

    async def _record_chat(
        self,
        *,
        payload: Any,
        error: BayramError | None,
        http_status: int | None,
        latency_ms: int,
    ) -> None:
        """Measure one ``generateContent`` call from ``usageMetadata``, defensively."""
        prompt_tokens = _token_count(read_path(payload, _USAGE_METADATA, "promptTokenCount"))
        completion_tokens = _token_count(
            read_path(payload, _USAGE_METADATA, "candidatesTokenCount")
        )
        cost_usd, cost_source = self._cost(prompt_tokens, completion_tokens)
        await self._usage.record(
            VendorUsage(
                vendor=Vendor.GEMINI,
                operation=VendorOperation.CHAT_COMPLETION,
                provider=self.name,
                is_success=error is None,
                model_id=self._model_id,
                is_fallback=self._is_fallback,
                http_status=http_status if http_status is not None else _status_from(error),
                error_code=error.error_code.value if error is not None else None,
                latency_ms=latency_ms,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                total_tokens=_token_count(read_path(payload, _USAGE_METADATA, "totalTokenCount")),
                cost_usd=cost_usd,
                cost_source=cost_source,
            )
        )

    async def _record_health(self, *, error: BayramError | None, latency_ms: int) -> None:
        """A probe is a real call with a real status, and never a priced one."""
        await self._usage.record(
            VendorUsage(
                vendor=Vendor.GEMINI,
                operation=VendorOperation.HEALTH,
                provider=self.name,
                is_success=error is None,
                model_id=self._model_id,
                is_fallback=self._is_fallback,
                http_status=_HTTP_OK if error is None else _status_from(error),
                error_code=error.error_code.value if error is not None else None,
                latency_ms=latency_ms,
            )
        )

    def _cost(
        self, prompt_tokens: int | None, completion_tokens: int | None
    ) -> tuple[float, CostSource] | tuple[None, None]:
        """Arithmetic over Gemini's own counts, or nothing. Gemini quotes no price."""
        return self._pricing.cost_for(prompt_tokens, completion_tokens)

    def _build_body(self, request: LlmRequest, response_model: type[BaseModel]) -> dict[str, Any]:
        return {
            "systemInstruction": {"parts": [{"text": request.system_prompt}]},
            "contents": [{"role": "user", "parts": [{"text": request.user_prompt}]}],
            "generationConfig": {
                "temperature": request.temperature,
                "maxOutputTokens": request.max_output_tokens,
                "responseMimeType": "application/json",
                "responseSchema": to_gemini_schema(response_model),
            },
        }

    def _refusal(self, payload: Any) -> Err | None:
        """Return an ``Err`` when Gemini refused on policy grounds, else ``None``."""
        block_reason = read_str(payload, "promptFeedback", "blockReason")
        finish_reason = read_str(payload, "candidates", 0, "finishReason")
        reason = block_reason or (
            finish_reason if finish_reason in _REFUSAL_FINISH_REASONS else None
        )
        if reason is None:
            return None
        return err(
            ProviderRejectedContentError(
                f"gemini refused to generate: {reason}",
                provider=self.name,
                context={"block_reason": block_reason, "finish_reason": finish_reason},
            )
        )


def _join_parts(parts: Any) -> str | None:
    """Concatenate the text parts of a candidate. Non-text parts are skipped."""
    if not isinstance(parts, list):
        return None
    texts = [part["text"] for part in parts if isinstance(part, dict) and _is_text(part)]
    joined = "".join(texts)
    return joined or None


def _is_text(part: dict[str, Any]) -> bool:
    return isinstance(part.get("text"), str)
