"""Fixtures for the LLM layer. Nothing here touches a network, a queue or a disk."""

from __future__ import annotations

import json
from collections.abc import Sequence
from typing import Any

import httpx
import pytest
from pydantic import BaseModel

from bayram.contracts import (
    HealthState,
    LlmRequest,
    ProviderHealth,
    Result,
    ok,
)
from bayram.providers.llm.parsing import parse_model_json
from bayram.providers.llm.schemas import PersonaBrief
from bayram.providers.llm.task_settings import LlmTaskSettings
from bayram.providers.llm.utils import utc_now

STUB_PROVIDER_NAME = "stub-llm"


class StubLlmProvider:
    """Satisfies ``LlmProvider`` structurally and records what it was asked.

    Each queued response is either a ready-made ``Result`` or a raw model string, which is
    run through the real ``parse_model_json`` so a test can exercise the true boundary.
    """

    name: str = STUB_PROVIDER_NAME

    def __init__(self, responses: Sequence[Result[Any] | str]) -> None:
        self._responses = list(responses)
        self.requests: list[LlmRequest] = []

    @property
    def call_count(self) -> int:
        return len(self.requests)

    async def generate_json[M: BaseModel](
        self, request: LlmRequest, response_model: type[M], *, timeout_s: float
    ) -> Result[M]:
        self.requests.append(request)
        if not self._responses:
            raise AssertionError("StubLlmProvider ran out of queued responses")
        queued = self._responses.pop(0)
        if isinstance(queued, str):
            return parse_model_json(queued, response_model, provider=self.name)
        return queued

    async def health(self) -> Result[ProviderHealth]:
        return ok(ProviderHealth(name=self.name, state=HealthState.HEALTHY, as_of=utc_now()))


def mock_client(handler: Any) -> httpx.AsyncClient:
    """An ``AsyncClient`` whose transport is a plain function over requests."""
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def gemini_response(text: str, *, finish_reason: str = "STOP") -> dict[str, Any]:
    return {"candidates": [{"content": {"parts": [{"text": text}]}, "finishReason": finish_reason}]}


def openai_response(text: str, *, finish_reason: str = "stop") -> dict[str, Any]:
    return {"choices": [{"message": {"content": text}, "finish_reason": finish_reason}]}


@pytest.fixture
def personas() -> tuple[PersonaBrief, ...]:
    return (
        PersonaBrief(persona_id="ovozli-bobo", description="a warm village grandfather"),
        PersonaBrief(persona_id="quvnoq-opa", description="a mischievous older sister"),
        PersonaBrief(persona_id="shoir", description="a solemn poet"),
    )


@pytest.fixture
def task_settings() -> LlmTaskSettings:
    return LlmTaskSettings(
        llm_temperature=0.7,
        llm_max_output_tokens=2_048,
        llm_timeout_s=45.0,
        llm_parse_max_attempts=2,
        name_chunk_duration_ms=8_000,
        greeting_min_duration_s=20.0,
        greeting_max_duration_s=45.0,
    )


def kit_payload_dict(**overrides: Any) -> dict[str, Any]:
    """A well-formed kit payload, keyword-overridable one field at a time."""
    payload: dict[str, Any] = {
        "title": "Tugʻilgan kun qoʻshigʻi",
        "sections": [
            {"label": "verse-1", "lines": ["Bugun quyosh boshqacha porlaydi"]},
            {"label": "hook", "lines": ["Gʻulomjon"], "is_name_hook": True},
            {"label": "chorus", "lines": ["Yillar oʻtsa ham qoʻshigʻing yangraydi"]},
        ],
        "name_line": "Gʻulomjon",
        "spoken_scripts": [
            {
                "persona_id": "ovozli-bobo",
                "text": "Assalomu alaykum, Gʻulomjon!",
                "target_duration_s": 30.0,
            },
            {
                "persona_id": "quvnoq-opa",
                "text": "Gʻulomjon, tabriklayman!",
                "target_duration_s": 28.0,
            },
            {
                "persona_id": "shoir",
                "text": "Gʻulomjon, yulduzlar senga kuylaydi.",
                "target_duration_s": 35.0,
            },
        ],
        "name_respellings": [
            {"text": "Gulomjon", "strategy": "stripped", "ipa": "ɡulomˈdʒon", "confidence": 0.9},
            {"text": "Gʻulomjon", "strategy": "canonical", "ipa": "ɣulomˈdʒon", "confidence": 0.7},
        ],
        "address_form_used": "formal",
    }
    payload.update(overrides)
    return payload


def kit_payload_json(**overrides: Any) -> str:
    return json.dumps(kit_payload_dict(**overrides), ensure_ascii=False)


def intake_payload_dict(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "display_name": "Gʻulomjon",
        "detected_language": "uz_latn",
        "cleaned_note": "Loves mountains and his grandmother's plov.",
        "facts": ["loves mountains", "loves his grandmother's plov"],
        "removed_artist_terms": [],
        "is_safe": True,
        "rejection_reason": "",
    }
    payload.update(overrides)
    return payload
