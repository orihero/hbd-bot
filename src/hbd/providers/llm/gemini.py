"""Gemini adapter — the primary LLM. Implements ``hbd.contracts.LlmProvider``.

Structured mode is requested properly (``responseMimeType`` + ``responseSchema``), and
the parse is *still* defended, because a schema-constrained model that hits the output
token cap returns a truncated object with ``finishReason: MAX_TOKENS`` and a 200 status.
That case is a parse problem, not a transport problem, and it is why ``parse_model_json``
exists downstream of a successful HTTP call.
"""

from __future__ import annotations

from typing import Any, Final

import httpx
from pydantic import BaseModel

from hbd.contracts import (
    Err,
    HealthState,
    LlmRequest,
    ProviderHealth,
    Result,
    err,
    ok,
)
from hbd.errors import ProviderRejectedContentError
from hbd.logging import get_logger
from hbd.providers.llm.json_schema import to_gemini_schema
from hbd.providers.llm.parsing import parse_model_json
from hbd.providers.llm.transport import read_path, read_str, request_json
from hbd.providers.llm.utils import health_state_for, utc_now

__all__ = ["GeminiLlmProvider", "PROVIDER_NAME"]

_LOG = get_logger(__name__)

PROVIDER_NAME: Final[str] = "gemini"

_GENERATE_PATH: Final[str] = "/v1beta/models/{model}:generateContent"
_MODEL_PATH: Final[str] = "/v1beta/models/{model}"
_API_KEY_HEADER: Final[str] = "x-goog-api-key"

#: Finish reasons that mean "we stopped you", not "you ran out of room".
_REFUSAL_FINISH_REASONS: Final[frozenset[str]] = frozenset(
    {"SAFETY", "RECITATION", "BLOCKLIST", "PROHIBITED_CONTENT", "SPII"}
)
_HEALTH_TIMEOUT_S: Final[float] = 10.0


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
    ) -> None:
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")
        self._model_id = model_id
        self._client = client if client is not None else httpx.AsyncClient()

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
        response = await request_json(
            self._client,
            method="POST",
            url=url,
            headers={_API_KEY_HEADER: self._api_key, "content-type": "application/json"},
            provider=self.name,
            timeout_s=timeout_s,
            json_body=body,
        )
        if isinstance(response, Err):
            return response

        payload = response.value
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

    async def health(self) -> Result[ProviderHealth]:
        url = self._base_url + _MODEL_PATH.format(model=self._model_id)
        response = await request_json(
            self._client,
            method="GET",
            url=url,
            headers={_API_KEY_HEADER: self._api_key},
            provider=self.name,
            timeout_s=_HEALTH_TIMEOUT_S,
        )
        if isinstance(response, Err):
            return ok(
                ProviderHealth(
                    name=self.name,
                    state=health_state_for(response.error),
                    as_of=utc_now(),
                    detail=response.error.operator_message,
                )
            )
        return ok(ProviderHealth(name=self.name, state=HealthState.HEALTHY, as_of=utc_now()))

    # -- internals ----------------------------------------------------------
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
