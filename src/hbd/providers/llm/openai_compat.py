"""OpenAI-compatible adapter — the documented fallback (GPT-5.6 Luna).

Behind the identical ``LlmProvider`` contract as Gemini: same method signatures, same
``Result`` types, same never-raises promise, same tolerant parse. Swapping the two is a
configuration change, and no caller can tell which one answered.

Structured mode here is ``response_format: {"type": "json_schema", strict: true}``, whose
schema dialect differs from Gemini's — that difference is confined to ``json_schema.py``.
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
from hbd.providers.llm.json_schema import to_openai_strict_schema
from hbd.providers.llm.parsing import parse_model_json
from hbd.providers.llm.transport import read_path, read_str, request_json
from hbd.providers.llm.utils import health_state_for, utc_now

__all__ = ["OpenAiCompatLlmProvider", "PROVIDER_NAME", "DEFAULT_BASE_URL"]

_LOG = get_logger(__name__)

PROVIDER_NAME: Final[str] = "openai-compat"

#: ``Settings`` has no ``llm_fallback_base_url`` yet, so the adapter carries the default
#: and the factory passes an override when one appears.
DEFAULT_BASE_URL: Final[str] = "https://api.openai.com"

_CHAT_PATH: Final[str] = "/v1/chat/completions"
_MODELS_PATH: Final[str] = "/v1/models"
_SCHEMA_NAME_SUFFIX: Final[str] = "_response"
_HEALTH_TIMEOUT_S: Final[float] = 10.0

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
    ) -> None:
        self._api_key = api_key
        self._base_url = _normalize_base_url(base_url)
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
        response = await request_json(
            self._client,
            method="POST",
            url=self._base_url + _CHAT_PATH,
            headers=self._headers(),
            provider=self.name,
            timeout_s=timeout_s,
            json_body=self._build_body(request, response_model),
        )
        if isinstance(response, Err):
            return response

        payload = response.value
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

    async def health(self) -> Result[ProviderHealth]:
        response = await request_json(
            self._client,
            method="GET",
            url=self._base_url + _MODELS_PATH,
            headers=self._headers(),
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
    def _headers(self) -> dict[str, str]:
        return {
            "authorization": f"Bearer {self._api_key}",
            "content-type": "application/json",
        }

    def _build_body(self, request: LlmRequest, response_model: type[BaseModel]) -> dict[str, Any]:
        schema_name = f"{response_model.__name__.lower()}{_SCHEMA_NAME_SUFFIX}"
        return {
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
