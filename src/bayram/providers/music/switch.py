"""The music provider switch: reads and writes the active provider in Redis.

Shares the exact pattern of ``bayram.payme.pause``:
- One key: ``MUSIC_PROVIDER_KEY``.
- Two allowed values: ``"elevenlabs"`` and ``"gemini"``.
- Read never raises: if Redis is unreachable or the key is absent, returns the default.
- Write returns a ``Result`` so admin handlers unwrap it into a ProblemError.
"""

from __future__ import annotations

from typing import Any, Final

from bayram.contracts import Result, err, ok
from bayram.errors import StorageError, ValidationError

__all__ = [
    "MUSIC_PROVIDER_KEY",
    "PROVIDER_ELEVENLABS",
    "PROVIDER_GEMINI",
    "ALLOWED_MUSIC_PROVIDERS",
    "read_music_provider",
    "write_music_provider",
]

MUSIC_PROVIDER_KEY: Final[str] = "bayram:config:music_provider"

PROVIDER_ELEVENLABS: Final[str] = "elevenlabs"
PROVIDER_GEMINI: Final[str] = "gemini"

ALLOWED_MUSIC_PROVIDERS: Final[frozenset[str]] = frozenset({PROVIDER_ELEVENLABS, PROVIDER_GEMINI})


async def read_music_provider(redis: Any | None, *, default: str = PROVIDER_ELEVENLABS) -> str:
    """Read the active provider from Redis, falling back to ``default`` on any failure."""
    if redis is None:
        return default
    try:
        val = await redis.get(MUSIC_PROVIDER_KEY)
        if val is None:
            return default
        decoded = val.decode() if isinstance(val, bytes) else str(val)
    except Exception:
        return default
    return decoded if decoded in ALLOWED_MUSIC_PROVIDERS else default


async def write_music_provider(redis: Any, provider: str) -> Result[None]:
    """Store the chosen provider in Redis. Never writes an unknown provider."""
    normalized = provider.strip().lower()
    if normalized not in ALLOWED_MUSIC_PROVIDERS:
        return err(
            ValidationError(
                f"unknown music provider '{provider}', "
                f"must be one of {sorted(ALLOWED_MUSIC_PROVIDERS)}",
                context={"provider": provider, "allowed": list(ALLOWED_MUSIC_PROVIDERS)},
            )
        )
    try:
        await redis.set(MUSIC_PROVIDER_KEY, normalized)
    except Exception as exc:
        return err(
            StorageError(
                f"failed to write music provider '{normalized}' to redis: {exc}",
                context={"provider": normalized, "key": MUSIC_PROVIDER_KEY},
                cause=exc,
            )
        )
    return ok(None)
