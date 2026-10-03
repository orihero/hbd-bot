"""Build the music provider from ``Settings``. One place reads configuration.

Supports ElevenLabs Music and Gemini Music (Google Lyria). When dynamic switching
is enabled via ``provider_resolver``, returns a ``DynamicMusicProvider`` that
delegates calls to the active vendor resolved at runtime (e.g. from Redis).
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable

import httpx

from bayram.config import Settings
from bayram.contracts import MusicProvider
from bayram.providers.music.dynamic import DynamicMusicProvider
from bayram.providers.music.elevenlabs import ElevenLabsMusicProvider
from bayram.providers.music.gemini import GeminiMusicProvider
from bayram.usage import LOGGING_USAGE_SINK, UsageSink

__all__ = [
    "build_music_provider",
    "build_elevenlabs_provider",
    "build_gemini_provider",
]


def build_elevenlabs_provider(
    settings: Settings,
    *,
    client: httpx.AsyncClient | None = None,
    usage: UsageSink = LOGGING_USAGE_SINK,
) -> ElevenLabsMusicProvider:
    """Wire the live Eleven Music adapter."""
    return ElevenLabsMusicProvider(
        api_key=settings.elevenlabs_api_key,
        base_url=settings.elevenlabs_base_url,
        model_id=settings.music_model_id,
        output_format=settings.music_output_format,
        max_concurrency=settings.music_max_concurrency,
        usd_per_minute=settings.music_usd_per_minute,
        client=client,
        usage=usage,
    )


def build_gemini_provider(
    settings: Settings,
    *,
    client: httpx.AsyncClient | None = None,
    usage: UsageSink = LOGGING_USAGE_SINK,
) -> GeminiMusicProvider:
    """Wire the live Gemini Music (Lyria) adapter."""
    api_key = settings.gemini_api_key or (
        settings.llm_api_key if settings.llm_provider == "gemini" else ""
    )
    return GeminiMusicProvider(
        api_key=api_key,
        base_url=settings.gemini_music_base_url,
        model_id=settings.gemini_music_model_id,
        max_concurrency=settings.gemini_music_max_concurrency,
        usd_per_request=settings.gemini_music_usd_per_request,
        client=client,
        usage=usage,
    )


def build_music_provider(
    settings: Settings,
    *,
    client: httpx.AsyncClient | None = None,
    gemini_client: httpx.AsyncClient | None = None,
    usage: UsageSink = LOGGING_USAGE_SINK,
    provider_resolver: Callable[[], Awaitable[str]] | None = None,
) -> MusicProvider:
    """Wire the music provider according to settings and optional runtime resolver."""
    eleven = build_elevenlabs_provider(settings, client=client, usage=usage)

    if provider_resolver is not None:
        gemini = build_gemini_provider(settings, client=gemini_client or client, usage=usage)
        return DynamicMusicProvider(
            {"elevenlabs": eleven, "gemini": gemini},
            default_provider=settings.music_provider,
            resolver=provider_resolver,
        )

    if settings.music_provider == "gemini":
        gemini = build_gemini_provider(settings, client=gemini_client or client, usage=usage)
        return DynamicMusicProvider(
            {"elevenlabs": eleven, "gemini": gemini},
            default_provider="gemini",
        )

    return eleven
