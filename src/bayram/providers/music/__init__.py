"""Song generation: Eleven Music and Gemini Music behind ``MusicProvider``.

Import from here, not from the submodules — the file split is an implementation detail.

    audio = await provider.compose(plan, idempotency_key=..., timeout_s=...)
    # name failed acoustic verification? one chunk, not one track:
    audio = await provider.inpaint(
        plan, source_song_id=..., chunk_index=..., idempotency_key=..., timeout_s=...
    )

Plans are built by ``bayram.pipeline.plan_builder``, which owns the one-chunk-carries-the-name
invariant. This package renders a plan; it does not decide one.
"""

from __future__ import annotations

from bayram.providers.music.dynamic import ROUTER_PROVIDER_NAME, DynamicMusicProvider
from bayram.providers.music.elevenlabs import (
    DEFAULT_MUSIC_MAX_CONCURRENCY,
    PROVIDER_NAME,
    SCALE_TIER_MAX_CONCURRENCY,
    ElevenLabsMusicProvider,
)
from bayram.providers.music.factory import (
    build_elevenlabs_provider,
    build_gemini_provider,
    build_music_provider,
)
from bayram.providers.music.fake import FakeMusicProvider, silent_mp3
from bayram.providers.music.gemini import (
    DEFAULT_GEMINI_MUSIC_MAX_CONCURRENCY,
    LYRIA_USD_PER_REQUEST,
    GeminiMusicProvider,
    build_gemini_music_prompt,
)
from bayram.providers.music.payload import build_compose_body, build_inpaint_body, guard_plan
from bayram.providers.music.switch import (
    ALLOWED_MUSIC_PROVIDERS,
    MUSIC_PROVIDER_KEY,
    read_music_provider,
    write_music_provider,
)
from bayram.providers.music.usage import MusicUsage, estimate_cost_usd

__all__ = [
    # providers
    "ElevenLabsMusicProvider",
    "GeminiMusicProvider",
    "DynamicMusicProvider",
    "FakeMusicProvider",
    "build_music_provider",
    "build_elevenlabs_provider",
    "build_gemini_provider",
    "PROVIDER_NAME",
    "ROUTER_PROVIDER_NAME",
    "DEFAULT_MUSIC_MAX_CONCURRENCY",
    "SCALE_TIER_MAX_CONCURRENCY",
    "DEFAULT_GEMINI_MUSIC_MAX_CONCURRENCY",
    "LYRIA_USD_PER_REQUEST",
    # payload & prompt
    "build_compose_body",
    "build_inpaint_body",
    "build_gemini_music_prompt",
    "guard_plan",
    # switch & persistence
    "MUSIC_PROVIDER_KEY",
    "ALLOWED_MUSIC_PROVIDERS",
    "read_music_provider",
    "write_music_provider",
    # observability + test support
    "MusicUsage",
    "estimate_cost_usd",
    "silent_mp3",
]
