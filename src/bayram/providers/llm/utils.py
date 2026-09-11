"""Small shared helpers for the LLM adapters. Pure functions, no I/O, no state."""

from __future__ import annotations

from datetime import UTC, datetime

from bayram.contracts import HealthState
from bayram.errors import BayramError

__all__ = ["utc_now", "health_state_for", "clip"]


def utc_now() -> datetime:
    """Timezone-aware now. One definition so every ``ProviderHealth.as_of`` agrees."""
    return datetime.now(UTC)


def health_state_for(error: BayramError) -> HealthState:
    """A retryable failure is a wobble; a terminal one means the provider is unusable."""
    return HealthState.DEGRADED if error.is_retryable else HealthState.UNAVAILABLE


def clip(text: str, limit: int) -> str:
    """Trim to ``limit`` characters on a word boundary where one is close enough.

    Generated text overshooting a contract's ``max_length`` must not fail an order, and
    a mid-word cut in a lyric title looks like a bug to the customer.
    """
    stripped = text.strip()
    if len(stripped) <= limit:
        return stripped
    head = stripped[:limit]
    cut = head.rfind(" ")
    return (head[:cut] if cut > limit // 2 else head).rstrip()
