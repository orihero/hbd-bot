"""Build the music provider from ``Settings``. One place reads configuration.

Two knobs decide how this adapter behaves against the vendor:

* ``music_max_concurrency`` — the simultaneous-render ceiling (2 on Starter/Creator/Pro,
  5 on Scale). Exceeding it earns a 429, so it is a hard limit that belongs beside
  ``worker_concurrency``, not a literal in an adapter.
* ``music_usd_per_minute`` — the rate the usage line's cost estimate is derived from.

Both are now real ``Settings`` fields with ``ge``/``gt`` bounds, so a nonsense value is
rejected at startup by ``load_settings()`` and can never reach a semaphore. This module
therefore reads them straight: re-validating here would be a second, weaker copy of a
check that already happened at the only boundary that matters.
"""

from __future__ import annotations

import httpx

from hbd.config import Settings
from hbd.providers.music.elevenlabs import ElevenLabsMusicProvider

__all__ = ["build_music_provider"]


def build_music_provider(
    settings: Settings, *, client: httpx.AsyncClient | None = None
) -> ElevenLabsMusicProvider:
    """Wire the live Eleven Music adapter. Pass ``client`` to share a pooled connection."""
    return ElevenLabsMusicProvider(
        api_key=settings.elevenlabs_api_key,
        base_url=settings.elevenlabs_base_url,
        model_id=settings.music_model_id,
        output_format=settings.music_output_format,
        max_concurrency=settings.music_max_concurrency,
        usd_per_minute=settings.music_usd_per_minute,
        client=client,
    )
