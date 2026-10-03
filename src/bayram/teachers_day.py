"""The Teachers' Day feature switch: reads and writes the switch state in Redis.

Shares the exact pattern of ``bayram.providers.music.switch`` and ``bayram.payme.pause``:
- One key: ``TEACHERS_DAY_KEY``.
- Stored as "1" (enabled) or deleted / "0" (disabled).
- Read never raises: if Redis is unreachable or absent, falls back to default.
- Write returns a ``Result`` so admin handlers unwrap it into a ProblemError.
"""

from __future__ import annotations

from typing import Any, Final

from bayram.contracts import Result, err, ok
from bayram.errors import StorageError
from bayram.logging import get_logger

__all__ = [
    "TEACHERS_DAY_KEY",
    "TEACHERS_DAY_DISCOUNT_PERCENT",
    "read_teachers_day_enabled",
    "write_teachers_day_enabled",
]

_LOG = get_logger(__name__)

TEACHERS_DAY_KEY: Final[str] = "bayram:config:teachers_day"
TEACHERS_DAY_DISCOUNT_PERCENT: Final[int] = 30
_ENABLED_VALUES: Final[frozenset[str]] = frozenset({"1", "true", "yes", "on"})


async def read_teachers_day_enabled(redis: Any | None, *, default: bool = False) -> bool:
    """Read whether Teachers' Day is active from Redis, falling back to ``default``."""
    if redis is None:
        return default
    try:
        val = await redis.get(TEACHERS_DAY_KEY)
        if val is None:
            return default
        decoded = val.decode() if isinstance(val, bytes) else str(val)
        return decoded.strip().lower() in _ENABLED_VALUES
    except Exception as exc:
        _LOG.warning(
            "the teachers day switch could not be read; using default",
            extra={"key": TEACHERS_DAY_KEY, "detail": repr(exc)},
        )
        return default


async def write_teachers_day_enabled(redis: Any, enabled: bool) -> Result[None]:
    """Store the switch state in Redis."""
    try:
        if enabled:
            await redis.set(TEACHERS_DAY_KEY, "1")
        else:
            await redis.delete(TEACHERS_DAY_KEY)
    except Exception as exc:
        return err(
            StorageError(
                f"failed to write teachers day switch '{enabled}' to redis: {exc}",
                context={"enabled": enabled, "key": TEACHERS_DAY_KEY},
                cause=exc,
            )
        )
    return ok(None)
