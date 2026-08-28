"""Concrete vendors, assembled from ``Settings``. The one file that names all of them.

``HBD_USE_FAKE_PROVIDERS=1`` swaps every adapter for its fake in a single branch. That is
deliberately one decision rather than six: a half-fake run — real ElevenLabs music with a
fake STT, say — spends money to produce a result nobody can trust, so the flag is
all-or-nothing.

Nothing here opens a connection at import time, and every HTTP adapter shares one pooled
``httpx.AsyncClient`` per vendor host so a worker with fifteen concurrent jobs does not
open fifteen TLS sessions to the same endpoint.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

import httpx

from hbd.config import Settings
from hbd.contracts import (
    Err,
    Language,
    LlmProvider,
    MusicProvider,
    SttProvider,
    TtsProvider,
)
from hbd.errors import ConfigError
from hbd.logging import get_logger
from hbd.providers.llm.factory import build_fallback_llm_provider, build_llm_provider
from hbd.providers.llm.fake import FakeLlmProvider
from hbd.providers.music.factory import build_music_provider
from hbd.providers.music.fake import FakeMusicProvider
from hbd.providers.tts.elevenlabs import ElevenLabsTts
from hbd.providers.tts.fakes import FakeTtsProvider
from hbd.providers.tts.metering import CharacterPricing
from hbd.providers.tts.registry import VoiceRegistry, default_registry, parse_voice_registry
from hbd.providers.tts.router import DEFAULT_TTS_ROUTES, build_router, parse_routes
from hbd.providers.tts.scribe import ElevenLabsScribe
from hbd.runtime.fakes import KeytermSttProvider

__all__ = ["ProviderSet", "build_provider_set", "DEMO_MISHEARD_ATTEMPTS"]

_LOG = get_logger(__name__)

#: In fake mode the first name take is misheard on purpose, so the offline demo actually
#: exercises the re-roll rather than pretending the loop is never needed.
DEMO_MISHEARD_ATTEMPTS: Final[int] = 1


@dataclass(frozen=True, slots=True)
class ProviderSet:
    """Every vendor the pipeline needs, already wired. Immutable."""

    music: MusicProvider
    tts: TtsProvider
    stt: SttProvider
    llm: LlmProvider
    llm_fallback: LlmProvider | None
    is_fake: bool
    _clients: tuple[httpx.AsyncClient, ...] = ()

    async def aclose(self) -> None:
        """Close every pool this set created. Fakes own none, so this is a no-op for them."""
        for client in self._clients:
            await client.aclose()


def build_provider_set(settings: Settings) -> ProviderSet:
    """Build the vendors. Raises ``ConfigError`` and nothing else."""
    if settings.use_fake_providers:
        return _fake_set(settings)
    return _live_set(settings)


# ---------------------------------------------------------------------------
# Fake
# ---------------------------------------------------------------------------
def _fake_set(settings: Settings) -> ProviderSet:
    if settings.is_production:
        raise ConfigError(
            "HBD_USE_FAKE_PROVIDERS is on while HBD_ENVIRONMENT=prod; refusing to serve "
            "customers silence and template lyrics",
            context={"environment": settings.environment},
        )
    _LOG.warning(
        "running with FAKE providers: no vendor is contacted and nothing is spent",
        extra={"environment": settings.environment},
    )
    registry = _registry(settings)
    return ProviderSet(
        music=FakeMusicProvider(),
        tts=FakeTtsProvider(registry=registry, languages=settings.supported_languages),
        stt=KeytermSttProvider(mishear_first=DEMO_MISHEARD_ATTEMPTS),
        llm=FakeLlmProvider(),
        llm_fallback=None,
        is_fake=True,
    )


# ---------------------------------------------------------------------------
# Live
# ---------------------------------------------------------------------------
def _live_set(settings: Settings) -> ProviderSet:
    registry = _registry(settings)
    elevenlabs = httpx.AsyncClient()
    llm_client = httpx.AsyncClient()

    tts = _router(settings, registry=registry, elevenlabs=elevenlabs)
    return ProviderSet(
        music=build_music_provider(settings, client=elevenlabs),
        tts=tts,
        stt=ElevenLabsScribe(
            api_key=settings.elevenlabs_api_key,
            base_url=settings.elevenlabs_base_url,
            model_id=settings.stt_model_id,
            client=elevenlabs,
        ),
        llm=build_llm_provider(settings, client=llm_client),
        llm_fallback=build_fallback_llm_provider(settings, client=llm_client),
        is_fake=False,
        _clients=(elevenlabs, llm_client),
    )


def _registry(settings: Settings) -> VoiceRegistry:
    """The cast is data. A malformed override is a startup failure, not a silent default."""
    if not settings.tts_voice_registry_json.strip():
        return default_registry()
    parsed = parse_voice_registry(settings.tts_voice_registry_json)
    if isinstance(parsed, Err):
        raise ConfigError(
            "HBD_TTS_VOICE_REGISTRY_JSON is not a usable voice registry",
            context={"detail": parsed.error.operator_message},
            cause=parsed.error,
        )
    return parsed.value


def _router(
    settings: Settings,
    *,
    registry: VoiceRegistry,
    elevenlabs: httpx.AsyncClient,
) -> TtsProvider:
    adapters: tuple[TtsProvider, ...] = (
        ElevenLabsTts(
            api_key=settings.elevenlabs_api_key,
            base_url=settings.elevenlabs_base_url,
            model_id=settings.tts_model_id,
            registry=registry,
            pricing=CharacterPricing(rate_per_character=settings.elevenlabs_usd_per_character),
            client=elevenlabs,
        ),
    )
    routes = _routes(settings)
    # ElevenLabs is the only TTS vendor, so a route naming anything else cannot be bound.
    # build_router says exactly which binding is missing; failing here beats failing one
    # paying order at a time.
    built = build_router(adapters, routes=routes)
    if isinstance(built, Err):
        raise ConfigError(
            "the TTS route table could not be bound to the configured adapters",
            context={"detail": built.error.operator_message},
            cause=built.error,
        )
    return built.value


def _routes(settings: Settings) -> dict[Language, str]:
    if not settings.tts_routes.strip():
        return dict(DEFAULT_TTS_ROUTES)
    parsed = parse_routes(settings.tts_routes)
    if isinstance(parsed, Err):
        raise ConfigError(
            "HBD_TTS_ROUTES is not a usable route table",
            context={"detail": parsed.error.operator_message},
            cause=parsed.error,
        )
    return dict(parsed.value)
