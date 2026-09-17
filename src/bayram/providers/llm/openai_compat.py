"""OpenAI-compatible adapter — the documented fallback (GPT-5.6 Luna).

Behind the identical ``LlmProvider`` contract as Gemini: same method signatures, same
``Result`` types, same never-raises promise, same tolerant parse. Swapping the two is a
configuration change, and no caller can tell which one answered.

Structured mode here is ``response_format: {"type": "json_schema", strict: true}``, whose
schema dialect differs from Gemini's — that difference is confined to ``json_schema.py``.

This adapter also carries the largest hole the system had in its accounting. It is the one
that talks to OpenRouter, it is instantiated TWICE (a primary and a fallback account) and
until now both instances reported ``name = "openai-compat"``, logged no model id and no
token count at all, so "what did the LLM cost this month" had no answer anywhere in the
codebase. Three things fix that, and all three are visible below:

* ``vendor`` and ``is_fallback`` are constructor facts, so the two accounts are finally
  distinguishable on a row. The adapter *name* stays shared on purpose — it is the wire
  dialect, not the billing relationship, and :class:`bayram.contracts.Vendor` is the axis an
  invoice arrives on.
* ``usage.include`` is requested of OpenRouter and of nobody else. Gating on the vendor
  rather than on a setting is deliberate: a strict OpenAI-compatible host 400s on an
  unknown top-level key, and a deployment must not have to know to turn a telemetry field
  off before its gateway will answer at all. Same reasoning as ``reasoning`` below.
* Every return path records exactly one :class:`bayram.usage.VendorUsage` — including the
  failures, because a rate-limited call still happened and a vendor whose failures vanish
  from the record looks healthier than it is. Cost precedence is OpenRouter's reported
  figure first (VENDOR_REPORTED), our own rate-card arithmetic second (DERIVED), and
  ``None`` third. Never zero: see ``bayram.providers.llm.pricing``.
"""

from __future__ import annotations

import math
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
from bayram.providers.llm.json_schema import to_openai_strict_schema
from bayram.providers.llm.parsing import parse_model_json
from bayram.providers.llm.pricing import TokenPricing
from bayram.providers.llm.transport import read_path, read_str, request_json
from bayram.providers.llm.utils import health_state_for, utc_now
from bayram.usage import LOGGING_USAGE_SINK, UsageSink, VendorUsage

__all__ = ["OpenAiCompatLlmProvider", "PROVIDER_NAME", "DEFAULT_BASE_URL"]

_LOG = get_logger(__name__)

PROVIDER_NAME: Final[str] = "openai-compat"

#: ``Settings`` has no ``llm_fallback_base_url`` yet, so the adapter carries the default
#: and the factory passes an override when one appears.
DEFAULT_BASE_URL: Final[str] = "https://api.openai.com"

_CHAT_PATH: Final[str] = "/v1/chat/completions"
_MODELS_PATH: Final[str] = "/v1/models"
_SCHEMA_NAME_SUFFIX: Final[str] = "_response"

#: OpenRouter's switch for a model whose reasoning trace is optional. Not OpenAI's — see
#: ``_build_body`` for why it is sent only on request.
_REASONING_FIELD: Final[str] = "reasoning"

#: OpenRouter's opt-in for the accounting block on the response. Also not OpenAI's.
_USAGE_FIELD: Final[str] = "usage"
_HEALTH_TIMEOUT_S: Final[float] = 10.0

_MS_PER_S: Final[float] = 1_000.0

#: ``request_json`` returns ``Ok`` only for a status below 400 and hands back the decoded
#: body rather than the response, so a success path has no status object to read. 200 is
#: what a chat completion answers with; recording it flatly is more useful than recording
#: ``None`` and less honest than pretending we saw the header.
_HTTP_OK: Final[int] = 200

#: ``finish_reason`` values that mean the model declined, not that it ran long.
_REFUSAL_FINISH_REASONS: Final[frozenset[str]] = frozenset({"content_filter"})

#: This adapter appends ``/v1/...`` itself, so its base URL is a HOST. Gateways document
#: theirs WITH the version already on it — OpenRouter's own quickstart says
#: ``https://openrouter.ai/api/v1`` — and pasting that verbatim yields ``/api/v1/v1/...``
#: and a 404 whose HTML body then defeats any attempt to read the real cause. Accepting
#: both spellings costs one line and removes a failure nobody debugs quickly.
_VERSION_SUFFIX: Final[str] = "/v1"


def _normalize_base_url(base_url: str) -> str:
    """Strip a trailing ``/v1`` so the caller may pass a host or a versioned endpoint."""
    trimmed = base_url.rstrip("/")
    if trimmed.endswith(_VERSION_SUFFIX):
        return trimmed[: -len(_VERSION_SUFFIX)]
    return trimmed


def _elapsed_ms(started: float) -> int:
    """Whole milliseconds since ``started``. The unit ``vendor_usage.latency_ms`` stores."""
    return int((perf_counter() - started) * _MS_PER_S)


def _token_count(value: Any) -> int | None:
    """A usage integer we are willing to store, or ``None``.

    ``bool`` is excluded because it is an ``int`` in Python and a vendor that answered
    ``"prompt_tokens": true`` has told us nothing. Absent stays absent: a malformed or
    missing usage block records ``None``, never ``0``, or the panel would sum a column of
    invented zeroes and report a cost of nothing for a deployment that spends money.
    """
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        return None
    # Re-stated as an int rather than returned straight from the untyped payload: the
    # value is one an operator will read as a token count, and it leaves here typed.
    return int(value)


def _reported_cost(value: Any) -> float | None:
    """OpenRouter's ``usage.cost`` in USD, when it is a real number.

    A reported ``0.0`` is KEPT. It is the vendor telling us a free-tier model cost
    nothing, which is a measurement and reconciles against an invoice line of zero — quite
    unlike the zero this module refuses, which is arithmetic nobody was able to do.
    """
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    number = float(value)
    return number if math.isfinite(number) and number >= 0.0 else None


def _status_from(error: BayramError | None) -> int | None:
    """The HTTP status the transport recorded on a typed error, if it saw one.

    A timeout or a DNS failure has no status and must record ``None`` — there is no
    number to put there and inventing one (0, 599) would be a fabricated measurement.
    """
    if error is None:
        return None
    status = error.context.get("status_code")
    return status if isinstance(status, int) and not isinstance(status, bool) else None


class OpenAiCompatLlmProvider:
    """Any OpenAI-shaped chat-completions endpoint, behind ``LlmProvider``."""

    name: str = PROVIDER_NAME

    def __init__(
        self,
        *,
        api_key: str,
        model_id: str,
        base_url: str = DEFAULT_BASE_URL,
        client: httpx.AsyncClient | None = None,
        is_reasoning_disabled: bool = False,
        vendor: Vendor = Vendor.OPENAI_COMPATIBLE,
        is_fallback: bool = False,
        pricing: TokenPricing | None = None,
        usage: UsageSink = LOGGING_USAGE_SINK,
    ) -> None:
        self._api_key = api_key
        self._base_url = _normalize_base_url(base_url)
        self._model_id = model_id
        self._client = client if client is not None else httpx.AsyncClient()
        self._is_reasoning_disabled = is_reasoning_disabled
        self._vendor = vendor
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
        started = perf_counter()
        response = await request_json(
            self._client,
            method="POST",
            url=self._base_url + _CHAT_PATH,
            headers=self._headers(),
            provider=self.name,
            timeout_s=timeout_s,
            json_body=self._build_body(request, response_model),
        )
        # Measured before the parse, so the number means "how long the vendor took" and
        # not "how long the vendor took plus how slow our own pydantic model is".
        latency_ms = _elapsed_ms(started)
        if isinstance(response, Err):
            await self._record_chat(
                payload=None, error=response.error, http_status=None, latency_ms=latency_ms
            )
            return response

        payload = response.value
        result = self._read(payload, response_model)
        # One record per call, written after the outcome is known: a refusal and a
        # truncated object both arrived over a 200 that spent tokens, so their usage
        # belongs in the total even though the caller receives an ``Err``.
        await self._record_chat(
            payload=payload,
            error=result.error if isinstance(result, Err) else None,
            http_status=_HTTP_OK,
            latency_ms=latency_ms,
        )
        return result

    async def health(self) -> Result[ProviderHealth]:
        started = perf_counter()
        response = await request_json(
            self._client,
            method="GET",
            url=self._base_url + _MODELS_PATH,
            headers=self._headers(),
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
        refusal = self._refusal(payload)
        if refusal is not None:
            return refusal

        finish_reason = read_str(payload, "choices", 0, "finish_reason")
        text = read_path(payload, "choices", 0, "message", "content")
        if finish_reason == "length":
            _LOG.warning(
                "%s hit the output token cap; the object is probably truncated",
                self.name,
                extra={"provider": self.name, "finish_reason": finish_reason},
            )
        return parse_model_json(
            text if isinstance(text, str) else None,
            response_model,
            provider=self.name,
            finish_reason=finish_reason,
        )

    async def _record_chat(
        self,
        *,
        payload: Any,
        error: BayramError | None,
        http_status: int | None,
        latency_ms: int,
    ) -> None:
        """Measure one chat completion. Reads the vendor block defensively or not at all."""
        prompt_tokens = _token_count(read_path(payload, _USAGE_FIELD, "prompt_tokens"))
        completion_tokens = _token_count(read_path(payload, _USAGE_FIELD, "completion_tokens"))
        cost_usd, cost_source = self._cost(payload, prompt_tokens, completion_tokens)
        # A 200 that then refused still has its status; a transport failure only carries
        # one inside the typed error, and a timeout carries none at all.
        status = http_status if http_status is not None else _status_from(error)
        await self._usage.record(
            VendorUsage(
                vendor=self._vendor,
                operation=VendorOperation.CHAT_COMPLETION,
                provider=self.name,
                is_success=error is None,
                model_id=self._model_id,
                is_fallback=self._is_fallback,
                http_status=status,
                error_code=error.error_code.value if error is not None else None,
                latency_ms=latency_ms,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                total_tokens=_token_count(read_path(payload, _USAGE_FIELD, "total_tokens")),
                cost_usd=cost_usd,
                cost_source=cost_source,
            )
        )

    async def _record_health(self, *, error: BayramError | None, latency_ms: int) -> None:
        """A probe is a real call with a real status, and never a priced one."""
        await self._usage.record(
            VendorUsage(
                vendor=self._vendor,
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
        self, payload: Any, prompt_tokens: int | None, completion_tokens: int | None
    ) -> tuple[float, CostSource] | tuple[None, None]:
        """What the call cost and how confidently we know it.

        Precedence, strongest evidence first: the vendor's own figure, then arithmetic
        over the vendor's token counts against a rate this deployment configured, then
        nothing at all. The third branch is the common one out of the box — no rate ships
        set — and it must stay ``None``: an unpriced call has no cost, not a zero one.
        """
        reported = _reported_cost(read_path(payload, _USAGE_FIELD, "cost"))
        if reported is not None:
            return (reported, CostSource.VENDOR_REPORTED)
        return self._pricing.cost_for(prompt_tokens, completion_tokens)

    def _headers(self) -> dict[str, str]:
        return {
            "authorization": f"Bearer {self._api_key}",
            "content-type": "application/json",
        }

    def _build_body(self, request: LlmRequest, response_model: type[BaseModel]) -> dict[str, Any]:
        schema_name = f"{response_model.__name__.lower()}{_SCHEMA_NAME_SUFFIX}"
        body: dict[str, Any] = {
            "model": self._model_id,
            "messages": [
                {"role": "system", "content": request.system_prompt},
                {"role": "user", "content": request.user_prompt},
            ],
            "temperature": request.temperature,
            "max_completion_tokens": request.max_output_tokens,
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": schema_name,
                    "strict": True,
                    "schema": to_openai_strict_schema(response_model),
                },
            },
        }
        # OMITTED unless asked for. It is a gateway extension, not part of the OpenAI
        # schema, and a strict host 400s on an unknown top-level key — so the default
        # posture cannot be to send it. What it fixes when it IS sent: a hybrid reasoning
        # model spends `max_completion_tokens` on its own thinking before it writes a
        # character of the object, so the answer arrives truncated with finish_reason
        # 'length' and dies in the parser. Raising the cap does not help; the trace grows
        # to fill it. See ``Settings.llm_disable_reasoning``.
        if self._is_reasoning_disabled:
            body[_REASONING_FIELD] = {"enabled": False}
        # Also a gateway extension, and gated on the VENDOR rather than on a setting.
        # OpenRouter omits `usage.cost` and the token counts unless it is asked for them,
        # and asking is the difference between an LLM bill we can attribute and one we
        # cannot. But a non-OpenRouter OpenAI-compatible host has never heard of this key
        # and may reject the whole request over it, so it is sent to OpenRouter alone. A
        # setting would push that knowledge onto every deployment for no gain: which hosts
        # understand the field is a fact about the hosts, and it belongs in this file.
        if self._vendor is Vendor.OPENROUTER:
            body[_USAGE_FIELD] = {"include": True}
        return body

    def _refusal(self, payload: Any) -> Err | None:
        """An explicit ``refusal`` field or a content-filter stop is a policy refusal."""
        refusal = read_str(payload, "choices", 0, "message", "refusal")
        finish_reason = read_str(payload, "choices", 0, "finish_reason")
        if refusal is None and finish_reason not in _REFUSAL_FINISH_REASONS:
            return None
        return err(
            ProviderRejectedContentError(
                f"{self.name} declined to generate: {refusal or finish_reason}",
                provider=self.name,
                context={"refusal": refusal, "finish_reason": finish_reason},
            )
        )
