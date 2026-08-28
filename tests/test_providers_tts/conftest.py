"""Fixtures for the speech adapters. No socket is ever opened.

Every adapter here takes its ``httpx.AsyncClient`` by injection, so a test hands it a
``MockTransport`` and inspects the exact request that would have gone to the vendor. That
is the boundary we own: below it is httpx's problem, above it is ours.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

import httpx
import pytest

from hbd.contracts import Language, SpeechRequest

#: A stable instant so a health report is byte-comparable between runs.
PROBE_NOW = datetime(2026, 3, 21, 9, 0, 0, tzinfo=UTC)

#: Bytes that begin with a real MP3 frame header, so mime sniffing has something to find.
MP3_BYTES = b"\xff\xfb\x90\x64" + b"audio-payload"

type Handler = Callable[[httpx.Request], httpx.Response]


def fixed_clock() -> datetime:
    return PROBE_NOW


class RequestRecorder:
    """Captures every request a mocked client sends, and replies from a script."""

    def __init__(self, responses: list[httpx.Response]) -> None:
        self._responses = responses
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if not self._responses:
            return httpx.Response(500, text="no scripted response left")
        if len(self._responses) == 1:
            return self._responses[0]
        return self._responses.pop(0)

    @property
    def last(self) -> httpx.Request:
        assert self.requests, "no request was sent"
        return self.requests[-1]

    def body_json(self, index: int = -1) -> dict[str, Any]:
        payload: dict[str, Any] = json.loads(self.requests[index].content.decode("utf-8"))
        return payload


def build_client(handler: Handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def recording_client(*responses: httpx.Response) -> tuple[httpx.AsyncClient, RequestRecorder]:
    """A client that replies with the given responses in order, keeping the last one."""
    recorder = RequestRecorder(list(responses))
    return (build_client(recorder), recorder)


def audio_response(
    data: bytes = MP3_BYTES,
    *,
    content_type: str = "audio/mpeg",
    headers: dict[str, str] | None = None,
    status: int = 200,
) -> httpx.Response:
    merged = {"content-type": content_type, **(headers or {})}
    return httpx.Response(status, content=data, headers=merged)


def json_response(payload: Any, *, status: int = 200) -> httpx.Response:
    return httpx.Response(status, json=payload)


def error_response(status: int, *, text: str = "upstream said no") -> httpx.Response:
    return httpx.Response(status, text=text)


def make_speech_request(**overrides: Any) -> SpeechRequest:
    defaults: dict[str, Any] = {
        "text": "Happy birthday, Gʻulomjon! Have a wonderful day.",
        "persona_id": "showman",
        "language": Language.EN,
        "name_submitted": "Gulomjon",
        "target_duration_s": None,
    }
    defaults.pop("target_duration_s")
    return SpeechRequest(**{**defaults, **overrides})


@pytest.fixture
def speech_request() -> SpeechRequest:
    return make_speech_request()


@pytest.fixture
def uzbek_speech_request() -> SpeechRequest:
    return make_speech_request(
        text="Assalomu alaykum, Gʻulomjon! Tugʻilgan kuningiz bilan!",
        persona_id="bobo",
        language=Language.UZ_LATN,
    )
