"""The ElevenLabs bits that both the speech adapter and the Scribe adapter need.

Two ElevenLabs adapters live in this package — text-to-speech and speech-to-text — and
they share one account, one auth header and one subscription endpoint. Duplicating the
health probe in both would guarantee that one of them eventually reports a different
state for the same account, so it lives here once.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import datetime
from typing import Final

import httpx
from pydantic import BaseModel, ConfigDict

from bayram.contracts import (
    Err,
    HealthState,
    Language,
    ProviderHealth,
    Result,
    ok,
)
from bayram.providers.tts.transport import (
    health_from_error,
    parse_json_body,
    send_request,
    utc_now,
)

__all__ = [
    "API_KEY_HEADER",
    "IDEMPOTENCY_HEADER",
    "SUBSCRIPTION_PATH",
    "DEFAULT_HEALTH_TIMEOUT_S",
    "ELEVENLABS_LANGUAGE_CODES",
    "language_code_for",
    "subscription_health",
]

API_KEY_HEADER: Final[str] = "xi-api-key"
IDEMPOTENCY_HEADER: Final[str] = "idempotency-key"
SUBSCRIPTION_PATH: Final[str] = "/v1/user/subscription"
DEFAULT_HEALTH_TIMEOUT_S: Final[float] = 10.0

#: Our four languages in the vendor's BCP-47-ish codes, or ``None`` where the vendor has
#: no code for one. ``eleven_v3`` rejects ``language_code: 'uz'`` outright — Uzbek is not on
#: its published roster — so both Uzbek scripts map to ``None`` and the adapter omits the
#: field, leaving v3 to auto-detect. That is how its Uzbek was auditioned and accepted.
#:
#: Mapping Uzbek to ``"uz"`` instead 400s every Uzbek greeting, and Uzbek is the default
#: language. If a future model gains an Uzbek code, put it here and nothing else changes.
ELEVENLABS_LANGUAGE_CODES: Final[Mapping[Language, str | None]] = {
    Language.UZ_LATN: None,
    Language.UZ_CYRL: None,
    Language.RU: "ru",
    Language.EN: "en",
}

#: Subscription statuses that mean the account can actually be billed.
_LIVE_STATUSES: Final[frozenset[str]] = frozenset({"active", "trialing", "free"})


def language_code_for(language: Language) -> str | None:
    """Vendor language code, or ``None`` when the vendor has none for this language.

    Total over ``Language`` — no adapter needs a fallback branch, but every caller must
    omit the field on ``None`` rather than sending a guess.
    """
    return ELEVENLABS_LANGUAGE_CODES[language]


class SubscriptionPayload(BaseModel):
    """The fields of ``GET /v1/user/subscription`` we actually read.

    ``extra="ignore"``: the vendor adds fields freely and a new one must not fail a health
    probe. Every field defaults, because a partial body is a degraded signal, not a crash.
    """

    model_config = ConfigDict(frozen=True, extra="ignore")

    character_count: int = 0
    character_limit: int = 0
    status: str | None = None

    @property
    def characters_remaining(self) -> int:
        return max(self.character_limit - self.character_count, 0)


def _state_for(payload: SubscriptionPayload) -> tuple[HealthState, str | None]:
    if payload.status is not None and payload.status.casefold() not in _LIVE_STATUSES:
        return (HealthState.DEGRADED, f"subscription status is '{payload.status}'")
    if payload.character_limit > 0 and payload.characters_remaining == 0:
        return (HealthState.UNAVAILABLE, "character quota exhausted")
    return (HealthState.HEALTHY, None)


async def subscription_health(
    client: httpx.AsyncClient,
    *,
    provider: str,
    base_url: str,
    api_key: str,
    timeout_s: float = DEFAULT_HEALTH_TIMEOUT_S,
    clock: Callable[[], datetime] = utc_now,
) -> Result[ProviderHealth]:
    """Probe the shared account. Returns ``Err`` only when the credentials are rejected."""
    response = await send_request(
        client,
        provider=provider,
        method="GET",
        url=f"{base_url.rstrip('/')}{SUBSCRIPTION_PATH}",
        timeout_s=timeout_s,
        headers={API_KEY_HEADER: api_key, "accept": "application/json"},
        context={"operation": "health"},
    )
    if isinstance(response, Err):
        return health_from_error(response, provider=provider, clock=clock)

    parsed = parse_json_body(
        response.value, SubscriptionPayload, provider=provider, context={"operation": "health"}
    )
    if isinstance(parsed, Err):
        return ok(
            ProviderHealth(
                name=provider,
                state=HealthState.UNKNOWN,
                as_of=clock(),
                detail=parsed.error.operator_message,
            )
        )

    payload = parsed.value
    state, detail = _state_for(payload)
    return ok(
        ProviderHealth(
            name=provider,
            state=state,
            as_of=clock(),
            quota_remaining=payload.characters_remaining if payload.character_limit else None,
            detail=detail,
        )
    )
