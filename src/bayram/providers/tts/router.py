"""Which vendor speaks which language. A table, not a chain of ``if``s.

ElevenLabs v3 serves all four languages, so today the table has one destination. Which
vendor speaks which language is a commercial judgement rather than a technical one, and it
changes without the pipeline caring — so the mapping stays a ``Language -> provider name``
table that :func:`parse_routes` can rebuild from a single environment string. Adding a
second vendor the day ElevenLabs has an outage is a config edit plus one adapter, not a
change to anything that calls TTS.

The router is itself a ``TtsProvider``, so the pipeline injects one object and never learns
whether there is more than one vendor behind it.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping, Sequence
from datetime import datetime
from typing import Final

from bayram.contracts import (
    Err,
    HealthState,
    Language,
    NarrationProvider,
    NarrationRequest,
    ProviderHealth,
    RenderedAudio,
    Result,
    SpeechRequest,
    TtsProvider,
    VoiceDescriptor,
    err,
    ok,
)
from bayram.errors import ConfigError, ErrorCode
from bayram.logging import get_logger
from bayram.providers.tts.elevenlabs import PROVIDER_NAME as ELEVENLABS_PROVIDER_NAME
from bayram.providers.tts.transport import utc_now

__all__ = [
    "LanguageRoutingTts",
    "NarrationRouter",
    "DEFAULT_NARRATION_ROUTES",
    "DEFAULT_NARRATION_FALLBACK",
    "NARRATION_ROUTER_NAME",
    "build_narration_router",
    "DEFAULT_TTS_ROUTES",
    "ROUTER_NAME",
    "build_router",
    "parse_routes",
]

_LOG = get_logger(__name__)

ROUTER_NAME: Final[str] = "tts_router"

#: The shipped split. Override with ``parse_routes`` rather than editing this.
#:
#: ElevenLabs serves all four. It does not list Uzbek on its published TTS roster, but a
#: listening test found its Uzbek acceptable, and one vendor means one key, one bill and
#: one failure mode.
DEFAULT_TTS_ROUTES: Final[Mapping[Language, str]] = {
    Language.UZ_LATN: ELEVENLABS_PROVIDER_NAME,
    Language.UZ_CYRL: ELEVENLABS_PROVIDER_NAME,
    Language.RU: ELEVENLABS_PROVIDER_NAME,
    Language.EN: ELEVENLABS_PROVIDER_NAME,
}

NARRATION_ROUTER_NAME: Final[str] = "narration_router"

#: Video narration's own table (IMAGE_VIDEO_SPEC §5.1): every language to the Gemini pool,
#: ElevenLabs behind it. Songs keep ``DEFAULT_TTS_ROUTES``; the two never share a table.
#: Spelled rather than imported so this module does not depend on the Gemini adapter.
DEFAULT_NARRATION_ROUTES: Final[Mapping[Language, str]] = {
    Language.UZ_LATN: "gemini_tts",
    Language.UZ_CYRL: "gemini_tts",
    Language.RU: "gemini_tts",
    Language.EN: "gemini_tts",
}
DEFAULT_NARRATION_FALLBACK: Final[str] = ELEVENLABS_PROVIDER_NAME

#: Worst first: an aggregate must never read better than its unhealthiest member.
_SEVERITY_ORDER: Final[tuple[HealthState, ...]] = (
    HealthState.UNAVAILABLE,
    HealthState.DEGRADED,
    HealthState.UNKNOWN,
    HealthState.HEALTHY,
)


def parse_routes(spec: str) -> Result[Mapping[Language, str]]:
    """Read ``uz_latn=elevenlabs_tts,ru=elevenlabs_tts`` into a route table. Never raises."""
    routes: dict[Language, str] = {}
    for clause in spec.split(","):
        trimmed = clause.strip()
        if not trimmed:
            continue
        language, separator, provider = trimmed.partition("=")
        if not separator or not provider.strip():
            return err(
                ConfigError(
                    f"route clause '{trimmed}' is not in language=provider form",
                    context={"clause": trimmed},
                )
            )
        try:
            parsed = Language(language.strip().casefold())
        except ValueError as exc:
            return err(
                ConfigError(
                    f"route clause '{trimmed}' names an unknown language",
                    context={"clause": trimmed, "known": [item.value for item in Language]},
                    cause=exc,
                )
            )
        routes[parsed] = provider.strip()
    if not routes:
        return err(ConfigError("the TTS route table is empty", context={"spec": spec[:200]}))
    return ok(routes)


def build_router(
    providers: Sequence[TtsProvider],
    *,
    routes: Mapping[Language, str] = DEFAULT_TTS_ROUTES,
    clock: Callable[[], datetime] = utc_now,
) -> Result[LanguageRoutingTts]:
    """Bind a route table to concrete adapters, or say exactly which binding is missing."""
    by_name: dict[str, TtsProvider] = {provider.name: provider for provider in providers}
    if len(by_name) != len(providers):
        return err(
            ConfigError(
                "two TTS providers share a name; routes cannot be resolved unambiguously",
                context={"names": [provider.name for provider in providers]},
            )
        )
    bound: dict[Language, TtsProvider] = {}
    for language, provider_name in routes.items():
        provider = by_name.get(provider_name)
        if provider is None:
            return err(
                ConfigError(
                    f"route for {language.value} names unknown provider '{provider_name}'",
                    context={
                        "language": language.value,
                        "provider": provider_name,
                        "available": sorted(by_name),
                    },
                )
            )
        bound[language] = provider
    return ok(LanguageRoutingTts(bound, clock=clock))


class LanguageRoutingTts:
    """A ``TtsProvider`` that delegates by output language."""

    name: str = ROUTER_NAME

    def __init__(
        self,
        routes: Mapping[Language, TtsProvider],
        *,
        clock: Callable[[], datetime] = utc_now,
    ) -> None:
        if not routes:
            raise ConfigError("a TTS router needs at least one route")
        self._routes = dict(routes)
        self._clock = clock

    @property
    def languages(self) -> tuple[Language, ...]:
        return tuple(self._routes)

    def provider_for(self, language: Language) -> TtsProvider | None:
        return self._routes.get(language)

    # -- TtsProvider --------------------------------------------------------
    async def synthesize(
        self, request: SpeechRequest, *, idempotency_key: str, timeout_s: float
    ) -> Result[RenderedAudio]:
        provider = self._routes.get(request.language)
        if provider is None:
            return err(
                ConfigError(
                    f"no TTS provider is routed for {request.language.value}",
                    context={
                        "language": request.language.value,
                        "routed": sorted(language.value for language in self._routes),
                    },
                )
            )
        return await provider.synthesize(
            request, idempotency_key=idempotency_key, timeout_s=timeout_s
        )

    async def voices(self) -> Result[tuple[VoiceDescriptor, ...]]:
        """Every routed voice, and only the ones the route table actually reaches.

        A vendor may offer languages we buy elsewhere. Listing those here would let the
        pipeline pick a persona the router would then refuse to synthesise, so each
        provider contributes exactly the languages routed to it.
        """
        collected: list[VoiceDescriptor] = []
        seen: frozenset[tuple[Language, str]] = frozenset()
        for provider in self._distinct_providers():
            languages = frozenset(
                language for language, routed in self._routes.items() if routed is provider
            )
            result = await provider.voices()
            if isinstance(result, Err):
                _LOG.warning(
                    "a routed TTS provider could not list its voices; continuing without it",
                    extra={"provider": provider.name, **result.error.to_log_dict()},
                )
                continue
            accepted, seen = _accept_voices(result.value, languages=languages, seen=seen)
            collected.extend(accepted)
        if not collected:
            return err(
                ConfigError(
                    "no routed TTS provider offered a usable voice",
                    context={"routed": sorted(language.value for language in self._routes)},
                )
            )
        return ok(tuple(collected))

    async def health(self) -> Result[ProviderHealth]:
        """One line for the whole leg, no better than its unhealthiest member."""
        states: list[HealthState] = []
        details: list[str] = []
        failures: list[Result[ProviderHealth]] = []
        for provider in self._distinct_providers():
            result = await provider.health()
            if isinstance(result, Err):
                failures.append(result)
                details.append(f"{provider.name}: {result.error.operator_message}")
                continue
            states.append(result.value.state)
            if result.value.detail:
                details.append(f"{provider.name}: {result.value.detail}")
        if not states:
            # A router is built with at least one route, so an empty state list means
            # every probe failed. The first reason is authoritative; an aggregate that
            # said "unknown" would hide it.
            return failures[0]
        if failures:
            states.append(HealthState.UNAVAILABLE)
        return ok(
            ProviderHealth(
                name=self.name,
                state=_worst(states),
                as_of=self._clock(),
                detail="; ".join(details) or None,
            )
        )

    # -- internals ----------------------------------------------------------
    def _distinct_providers(self) -> tuple[TtsProvider, ...]:
        """Each backing provider once, in route order — two languages often share one."""
        distinct: list[TtsProvider] = []
        for provider in self._routes.values():
            if not any(provider is existing for existing in distinct):
                distinct.append(provider)
        return tuple(distinct)


def _accept_voices(
    voices: tuple[VoiceDescriptor, ...],
    *,
    languages: frozenset[Language],
    seen: frozenset[tuple[Language, str]],
) -> tuple[tuple[VoiceDescriptor, ...], frozenset[tuple[Language, str]]]:
    """Voices this provider contributes, plus the NEW seen-set including them.

    ``seen`` is taken and returned by value rather than mutated in place: the caller's set
    is an input, and inputs are not modified here.
    """
    accepted: list[VoiceDescriptor] = []
    taken = seen
    for voice in voices:
        key = (voice.language, voice.persona_id)
        if voice.language in languages and key not in taken:
            taken = taken | {key}
            accepted.append(voice)
    return tuple(accepted), taken


def _worst(states: Iterable[HealthState]) -> HealthState:
    """Severity order covers every member, so a non-empty list always resolves."""
    present = frozenset(states)
    return next((state for state in _SEVERITY_ORDER if state in present), HealthState.UNKNOWN)


# ---------------------------------------------------------------------------
# Narration (IMAGE_VIDEO_SPEC §5.1, §5.2; D23)
# ---------------------------------------------------------------------------
def build_narration_router(
    providers: Sequence[NarrationProvider],
    *,
    routes: Mapping[Language, str] = DEFAULT_NARRATION_ROUTES,
    fallback: str | None = DEFAULT_NARRATION_FALLBACK,
    clock: Callable[[], datetime] = utc_now,
) -> Result[NarrationRouter]:
    """Bind the narration table and its fallback, or say which binding is missing."""
    by_name: dict[str, NarrationProvider] = {provider.name: provider for provider in providers}
    if len(by_name) != len(providers):
        return err(
            ConfigError(
                "two narration providers share a name",
                context={"names": [provider.name for provider in providers]},
            )
        )
    wanted = [*routes.values(), *([fallback] if fallback else [])]
    missing = sorted({name for name in wanted if name not in by_name})
    if missing:
        return err(
            ConfigError(
                f"the narration table names unknown provider(s): {', '.join(missing)}",
                context={"missing": missing, "available": sorted(by_name)},
            )
        )
    if not routes:
        return err(ConfigError("the narration route table is empty"))
    bound = {language: by_name[name] for language, name in routes.items()}
    return ok(NarrationRouter(bound, fallback=by_name[fallback] if fallback else None, clock=clock))


class NarrationRouter:
    """A ``NarrationProvider`` that routes by language and falls back on any vendor fault.

    **A content refusal is final** (§5.1, §5.2): the line is not offered to a second vendor,
    because a refused line that another vendor speaks is a moderation bypass, and the job
    fails with a refund instead. Every other failure — the pool exhausted, a missing house
    voice, a vendor outage — is the fallback's to answer. A failing fallback fails the job
    (O13: paid for voice, voice failed).
    """

    name: str = NARRATION_ROUTER_NAME

    def __init__(
        self,
        routes: Mapping[Language, NarrationProvider],
        *,
        fallback: NarrationProvider | None,
        clock: Callable[[], datetime] = utc_now,
    ) -> None:
        if not routes:
            raise ConfigError("a narration router needs at least one route")
        self._routes = dict(routes)
        self._fallback = fallback
        self._clock = clock

    def provider_for(self, language: Language) -> NarrationProvider | None:
        return self._routes.get(language, self._fallback)

    async def narrate(
        self, request: NarrationRequest, *, idempotency_key: str, timeout_s: float
    ) -> Result[RenderedAudio]:
        primary = self._routes.get(request.language)
        if primary is None:
            if self._fallback is None:
                return err(
                    ConfigError(
                        f"no narration provider is routed for {request.language.value}",
                        context={"language": request.language.value},
                    )
                )
            primary = self._fallback
        result = await primary.narrate(
            request, idempotency_key=idempotency_key, timeout_s=timeout_s
        )
        if not isinstance(result, Err):
            return result
        fallback = self._fallback
        if (
            result.error.error_code is ErrorCode.CONTENT_REJECTED
            or fallback is None
            or fallback is primary
        ):
            return result
        _LOG.warning(
            "narration falling back",
            extra={
                "provider": primary.name,
                "fallback": fallback.name,
                "language": request.language.value,
                "reason": result.error.error_code.value,
                "pool_exhausted": result.error.context.get("pool_exhausted") is True,
            },
        )
        return await fallback.narrate(request, idempotency_key=idempotency_key, timeout_s=timeout_s)

    async def health(self) -> Result[ProviderHealth]:
        """The leg is as healthy as its best path: a sick primary with a fallback degrades it."""
        primaries: list[NarrationProvider] = []
        for provider in self._routes.values():
            if not any(provider is seen for seen in primaries):
                primaries.append(provider)
        primary_states: list[HealthState] = []
        details: list[str] = []
        for provider in primaries:
            result = await provider.health()
            if isinstance(result, Err):
                primary_states.append(HealthState.UNAVAILABLE)
                details.append(f"{provider.name}: {result.error.operator_message}")
                continue
            primary_states.append(result.value.state)
            if result.value.detail:
                details.append(f"{provider.name}: {result.value.detail}")
        state = _worst(primary_states)
        if state is not HealthState.HEALTHY and self._fallback is not None:
            fallback = await self._fallback.health()
            fallback_ok = (
                not isinstance(fallback, Err) and fallback.value.state is HealthState.HEALTHY
            )
            details.append(f"fallback {self._fallback.name}: {'ok' if fallback_ok else 'down'}")
            state = HealthState.DEGRADED if fallback_ok else HealthState.UNAVAILABLE
        return ok(
            ProviderHealth(
                name=self.name,
                state=state,
                as_of=self._clock(),
                detail="; ".join(details) or None,
            )
        )
