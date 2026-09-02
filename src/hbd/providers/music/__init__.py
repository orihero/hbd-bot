"""Song generation: Eleven Music behind ``MusicProvider``.

Import from here, not from the submodules — the file split is an implementation detail.

    audio = await provider.compose(plan, idempotency_key=..., timeout_s=...)
    # name failed acoustic verification? one chunk, not one track:
    audio = await provider.inpaint(
        plan, source_song_id=..., chunk_index=..., idempotency_key=..., timeout_s=...
    )

Plans are built by ``hbd.pipeline.plan_builder``, which owns the one-chunk-carries-the-name
invariant. This package renders a plan; it does not decide one.
"""

from __future__ import annotations

from hbd.providers.music.elevenlabs import (
    DEFAULT_MUSIC_MAX_CONCURRENCY,
    PROVIDER_NAME,
    SCALE_TIER_MAX_CONCURRENCY,
    ElevenLabsMusicProvider,
)
from hbd.providers.music.factory import build_music_provider
from hbd.providers.music.fake import FakeMusicProvider, silent_mp3
from hbd.providers.music.payload import build_compose_body, build_inpaint_body, guard_plan
from hbd.providers.music.usage import MusicUsage, estimate_cost_usd

__all__ = [
    # provider
    "ElevenLabsMusicProvider",
    "FakeMusicProvider",
    "build_music_provider",
    "PROVIDER_NAME",
    "DEFAULT_MUSIC_MAX_CONCURRENCY",
    "SCALE_TIER_MAX_CONCURRENCY",
    # payload
    "build_compose_body",
    "build_inpaint_body",
    "guard_plan",
    # observability + test support
    "MusicUsage",
    "estimate_cost_usd",
    "silent_mp3",
]
