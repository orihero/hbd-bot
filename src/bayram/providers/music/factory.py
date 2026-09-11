"""Build the music provider from ``Settings``. One place reads configuration.

Two knobs decide how this adapter behaves against the vendor:

* ``music_max_concurrency`` — the simultaneous-render ceiling (2 on Starter/Creator/Pro,
  5 on Scale). Exceeding it earns a 429, so it is a hard limit that belongs beside
  ``worker_concurrency``, not a literal in an adapter.
* ``music_usd_per_minute`` — the rate the usage line's cost estimate is derived from.
  ``0.0`` is a legal value and not a degenerate one: it says no music rate is configured
  here, and the adapter answers that by leaving ``cost_usd`` NULL rather than by billing
  the render at nothing (``ElevenLabsMusicProvider._estimated_cost``). Passing it through
  untouched is therefore the whole job — a guard here would turn "unpriced" into a startup
  failure and take the one honest way of saying it away from the operator.

Both are now real ``Settings`` fields with ``ge`` bounds, so a nonsense value — a negative
rate, a ceiling of zero — is rejected at startup by ``load_settings()`` and can never reach
a semaphore. This module therefore reads them straight: re-validating here would be a
second, weaker copy of a check that already happened at the only boundary that matters.

``usage`` is the third collaborator and the only one with a working default. It defaults to
the logging sink so a caller with no database — a test, a one-shot operator tool — still
gets the measurement on stdout; ``runtime.providers`` passes the persisting sink instead.
"""

from __future__ import annotations

import httpx

from bayram.config import Settings
from bayram.providers.music.elevenlabs import ElevenLabsMusicProvider
from bayram.usage import LOGGING_USAGE_SINK, UsageSink

__all__ = ["build_music_provider"]


def build_music_provider(
    settings: Settings,
    *,
    client: httpx.AsyncClient | None = None,
    usage: UsageSink = LOGGING_USAGE_SINK,
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
        usage=usage,
    )
