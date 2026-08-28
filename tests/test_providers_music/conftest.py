"""Shared helpers for the music provider tests. No network, ever.

Every test drives the adapter through ``httpx.MockTransport``, so the real request objects
the provider builds are asserted on directly — headers, URL and JSON body — without a
socket existing anywhere in the suite.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator, Callable, Coroutine
from contextlib import asynccontextmanager
from typing import Any

import httpx
import orjson

from hbd.contracts import Chunk, CompositionPlan, Language, LyricDraft, LyricSection
from hbd.providers.music.elevenlabs import ElevenLabsMusicProvider
from hbd.providers.music.planner import PlanShape

TEST_API_KEY = "test-elevenlabs-key"
TEST_BASE_URL = "https://api.elevenlabs.test"
TEST_MODEL_ID = "music_v2"
TEST_OUTPUT_FORMAT = "mp3_44100_128"

#: Enough bytes to be a body; the fake provider owns "real audio", not these transport tests.
AUDIO_BODY = b"\xff\xfb\x10\xc0" + bytes(100)

#: A mock transport handler may be sync or async; both are used below.
Handler = (
    Callable[[httpx.Request], httpx.Response]
    | Callable[[httpx.Request], Coroutine[Any, Any, httpx.Response]]
)

DEFAULT_SHAPE = PlanShape(
    song_length_ms=120_000, name_chunk_duration_ms=8_000, body_chunk_target_ms=20_000
)


def audio_response(
    *, status: int = 200, content: bytes = AUDIO_BODY, headers: dict[str, str] | None = None
) -> httpx.Response:
    """A successful vendor answer: the body IS the audio."""
    merged = {"content-type": "audio/mpeg", "song-id": "song_abc123"}
    merged.update(headers or {})
    return httpx.Response(status_code=status, content=content, headers=merged)


def error_response(
    status: int, *, detail: Any = "something went wrong", headers: dict[str, str] | None = None
) -> httpx.Response:
    return httpx.Response(
        status_code=status,
        content=orjson.dumps({"detail": detail}),
        headers={"content-type": "application/json", **(headers or {})},
    )


def always(response: httpx.Response) -> Callable[[httpx.Request], httpx.Response]:
    """A handler that answers everything the same way."""

    def handler(request: httpx.Request) -> httpx.Response:
        return response

    return handler


def recording(
    response: httpx.Response, sink: list[httpx.Request]
) -> Callable[[httpx.Request], httpx.Response]:
    """A handler that records each request before answering."""

    def handler(request: httpx.Request) -> httpx.Response:
        sink.append(request)
        return response

    return handler


def usage_line(records: list[logging.LogRecord], event: str) -> dict[str, Any]:
    """The fields the provider attached to its usage log line, as a plain mapping.

    ``extra=`` values land on the LogRecord itself, which is untyped; reading them
    through ``__dict__`` keeps the assertions honest without lying to the type checker.
    """
    record = next(item for item in records if item.getMessage() == event)
    return dict(record.__dict__)


def body_of(request: httpx.Request) -> dict[str, Any]:
    """The JSON the provider actually posted."""
    decoded: dict[str, Any] = orjson.loads(request.content)
    return decoded


@asynccontextmanager
async def music_provider(
    handler: Handler, **overrides: Any
) -> AsyncIterator[ElevenLabsMusicProvider]:
    """A provider wired to a mock transport, closed on exit."""
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    settings: dict[str, Any] = {
        "api_key": TEST_API_KEY,
        "base_url": TEST_BASE_URL,
        "model_id": TEST_MODEL_ID,
        "output_format": TEST_OUTPUT_FORMAT,
    }
    settings.update(overrides)
    try:
        yield ElevenLabsMusicProvider(client=client, **settings)
    finally:
        await client.aclose()


def make_lyrics(*, section_count: int = 3, name_display: str = "Gʻulomjon") -> LyricDraft:
    """A lyric whose SECOND section is the name hook."""
    sections: list[LyricSection] = [
        LyricSection(label="verse-1", lines=("Bugun quyosh boshqacha porlaydi",)),
        LyricSection(label="hook", lines=(f"{name_display}, tugʻilgan kuning bilan",), is_name_hook=True),
    ]
    for index in range(section_count - 2):
        sections.append(
            LyricSection(label=f"section-{index}", lines=(f"line body number {index}",))
        )
    return LyricDraft(
        title="Tugʻilgan kun",
        language=Language.UZ_LATN,
        sections=tuple(sections),
        name_display=name_display,
    )


def simple_plan(*, name_text: str = "Gulomjon", seed: int | None = 42) -> CompositionPlan:
    """A minimal three-chunk plan with the name in the middle."""
    return CompositionPlan(
        chunks=(
            Chunk(text="intro line", duration_ms=20_000, positive_styles=("uzbek pop",)),
            Chunk(text=name_text, duration_ms=8_000, is_name_chunk=True),
            Chunk(text="outro line", duration_ms=20_000),
        ),
        language=Language.UZ_LATN,
        seed=seed,
    )
