"""Concrete vendors, assembled from ``Settings``. The one file that names all of them.

``BAYRAM_USE_FAKE_PROVIDERS=1`` swaps every adapter for its fake in a single branch. That is
deliberately one decision rather than six: a half-fake run — real ElevenLabs music with a
fake STT, say — spends money to produce a result nobody can trust, so the flag is
all-or-nothing.

Nothing here opens a connection at import time, and every HTTP adapter shares one pooled
``httpx.AsyncClient`` per vendor host so a worker with fifteen concurrent jobs does not
open fifteen TLS sessions to the same endpoint.

**One usage sink, handed to every adapter.** Measurement is a collaborator, not a global:
``build_provider_set`` takes a :class:`~bayram.usage.UsageSink` and threads the SAME object
into all five live adapters, so every vendor call in a process lands in one place and an
operator reading ``vendor_usage`` is reading one table, not five half-instrumented ones.
The parameter DEFAULTS to :data:`~bayram.usage.LOGGING_USAGE_SINK` because a caller with no
database — a test, a one-shot operator tool, ``bayram.demo`` — must still get a correct
provider set and a log line for each call; ``bayram.runtime.container`` is what substitutes
the persisting ``DbUsageSink``. Attribution (which order, which task) is NOT passed here:
it arrives at the call site through ``usage_scope()``, which is why not one adapter
constructor below is handed an order id.

**The fakes are handed the sink too, and that is the point.** A fake run stamps
``is_fake=True`` on every row it writes, so a demo is RECORDED and then visibly excluded
from spend. Skipping the sink in fake mode would make an offline demo indistinguishable
from a deployment nobody ever instrumented — the exact confusion ``isVendorUsage`` exists
to resolve.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

import httpx

from bayram.config import Settings
from bayram.contracts import (
    Err,
    Language,
    LlmProvider,
    MusicProvider,
    SttProvider,
    TtsProvider,
)
from bayram.errors import ConfigError
from bayram.logging import get_logger
from bayram.providers.llm.factory import build_fallback_llm_provider, build_llm_provider
from bayram.providers.llm.fake import FakeLlmProvider
from bayram.providers.music.factory import build_music_provider
from bayram.providers.music.fake import FakeMusicProvider
from bayram.providers.tts.elevenlabs import ElevenLabsTts
from bayram.providers.tts.fakes import FakeTtsProvider
from bayram.providers.tts.metering import CharacterPricing
from bayram.providers.tts.registry import VoiceRegistry, default_registry, parse_voice_registry
from bayram.providers.tts.router import DEFAULT_TTS_ROUTES, build_router, parse_routes
from bayram.providers.tts.scribe import ElevenLabsScribe
from bayram.runtime.fakes import KeytermSttProvider
from bayram.usage import LOGGING_USAGE_SINK, UsageSink

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


def build_provider_set(settings: Settings, *, usage: UsageSink = LOGGING_USAGE_SINK) -> ProviderSet:
    """Build the vendors. Raises ``ConfigError`` and nothing else.

    ``usage`` is where every vendor call this set makes will be recorded. It defaults to
    the logging sink so that a caller holding no database still builds a working, measured
    provider set; the real processes pass ``DbUsageSink`` from the container.
    """
    if settings.use_fake_providers:
        return _fake_set(settings, usage=usage)
    return _live_set(settings, usage=usage)


# ---------------------------------------------------------------------------
# Fake
# ---------------------------------------------------------------------------
def _fake_set(settings: Settings, *, usage: UsageSink) -> ProviderSet:
    if settings.is_production:
        raise ConfigError(
            "BAYRAM_USE_FAKE_PROVIDERS is on while BAYRAM_ENVIRONMENT=prod; refusing to serve "
            "customers silence and template lyrics",
            context={"environment": settings.environment},
        )
    _LOG.warning(
        "running with FAKE providers: no vendor is contacted and nothing is spent",
        extra={"environment": settings.environment},
    )
    registry = _registry(settings)
    # The sink is handed to the fakes as well: each of them stamps ``is_fake=True`` on the
    # row it writes, so an offline demo is measured and then excluded from spend rather
    # than leaving a hole nobody can tell from an uninstrumented deployment.
    return ProviderSet(
        music=FakeMusicProvider(usage=usage),
        tts=FakeTtsProvider(registry=registry, languages=settings.supported_languages, usage=usage),
        stt=KeytermSttProvider(mishear_first=DEMO_MISHEARD_ATTEMPTS, usage=usage),
        llm=FakeLlmProvider(usage=usage),
        llm_fallback=None,
        is_fake=True,
    )


# ---------------------------------------------------------------------------
# Live
# ---------------------------------------------------------------------------
def _live_set(settings: Settings, *, usage: UsageSink) -> ProviderSet:
    registry = _registry(settings)
    elevenlabs = httpx.AsyncClient()
    llm_client = httpx.AsyncClient()

    # ONE sink object reaches all five adapters. Not five sinks over one factory: the
    # sink owns its own transaction per row, and giving each adapter its own would buy
    # nothing while making "is everything writing to the same table?" a question.
    tts = _router(settings, registry=registry, elevenlabs=elevenlabs, usage=usage)
    return ProviderSet(
        music=build_music_provider(settings, client=elevenlabs, usage=usage),
        tts=tts,
        stt=ElevenLabsScribe(
            api_key=settings.elevenlabs_api_key,
            base_url=settings.elevenlabs_base_url,
            model_id=settings.stt_model_id,
            client=elevenlabs,
            usage=usage,
        ),
        llm=build_llm_provider(settings, client=llm_client, usage=usage),
        llm_fallback=build_fallback_llm_provider(settings, client=llm_client, usage=usage),
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
            "BAYRAM_TTS_VOICE_REGISTRY_JSON is not a usable voice registry",
            context={"detail": parsed.error.operator_message},
            cause=parsed.error,
        )
    return parsed.value


def _router(
    settings: Settings,
    *,
    registry: VoiceRegistry,
    elevenlabs: httpx.AsyncClient,
    usage: UsageSink,
) -> TtsProvider:
    adapters: tuple[TtsProvider, ...] = (
        ElevenLabsTts(
            api_key=settings.elevenlabs_api_key,
            base_url=settings.elevenlabs_base_url,
            model_id=settings.tts_model_id,
            registry=registry,
            # Ships at 0.0, which is "no rate configured" and not "free": every speech row
            # then carries its billed characters and a NULL cost.
            pricing=CharacterPricing(rate_per_character=settings.elevenlabs_usd_per_character),
            client=elevenlabs,
            usage=usage,
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
            "BAYRAM_TTS_ROUTES is not a usable route table",
            context={"detail": parsed.error.operator_message},
            cause=parsed.error,
        )
    return dict(parsed.value)
