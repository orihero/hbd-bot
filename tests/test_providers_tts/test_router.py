"""Language routing: the table, its bindings, and aggregate health."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Final

import pytest

from bayram.contracts import (
    HealthState,
    Language,
    ProviderHealth,
    Result,
    TtsProvider,
    VoiceDescriptor,
    err,
    is_err,
    is_ok,
)
from bayram.errors import ConfigError, ProviderUnavailableError
from bayram.providers.tts.elevenlabs import PROVIDER_NAME as ELEVENLABS_NAME
from bayram.providers.tts.elevenlabs import SUPPORTED_LANGUAGES as ELEVENLABS_LANGUAGES
from bayram.providers.tts.fakes import FakeTtsProvider
from bayram.providers.tts.router import (
    DEFAULT_TTS_ROUTES,
    LanguageRoutingTts,
    build_router,
    parse_routes,
)
from tests.test_providers_tts.conftest import fixed_clock, make_speech_request

TIMEOUT_S = 5.0
IDEMPOTENCY_KEY = "order-1:greeting:0"


class _FailingLeg(FakeTtsProvider):
    """A routed provider whose catalogue and health probe both fail."""

    async def voices(self) -> Result[tuple[VoiceDescriptor, ...]]:
        return err(ProviderUnavailableError("catalogue down", provider=self.name))

    async def health(self) -> Result[ProviderHealth]:
        return err(ProviderUnavailableError("leg down", provider=self.name))


#: A deliberately SPLIT table, stated here rather than borrowed from ``DEFAULT_TTS_ROUTES``.
#: ElevenLabs is the only TTS vendor shipped, so the default table has a single
#: destination — which would leave the routing, merging and health-aggregation tests below
#: exercising one leg and quietly proving nothing. What those tests are about is behaviour
#: with more than one vendor, so they own a second, hypothetical vendor and a multi-vendor
#: table, and stay meaningful whatever the default becomes and whoever is added next.
OTHER_NAME: Final[str] = "other_tts"
OTHER_LANGUAGES: Final[tuple[Language, ...]] = (Language.UZ_LATN, Language.UZ_CYRL)
_SPLIT_ROUTES: Final[Mapping[Language, str]] = {
    Language.UZ_LATN: OTHER_NAME,
    Language.UZ_CYRL: OTHER_NAME,
    Language.RU: ELEVENLABS_NAME,
    Language.EN: ELEVENLABS_NAME,
}


def _fakes() -> tuple[FakeTtsProvider, FakeTtsProvider]:
    return (
        FakeTtsProvider(name=OTHER_NAME, languages=OTHER_LANGUAGES),
        FakeTtsProvider(name=ELEVENLABS_NAME, languages=ELEVENLABS_LANGUAGES),
    )


def _router() -> LanguageRoutingTts:
    other, eleven = _fakes()
    result = build_router([other, eleven], routes=_SPLIT_ROUTES, clock=fixed_clock)
    assert is_ok(result)
    return result.value


# ---------------------------------------------------------------------------
# The table
# ---------------------------------------------------------------------------
def test_the_default_table_routes_every_supported_language() -> None:
    # Act / Assert — a language with no route is a customer with no greeting.
    assert set(DEFAULT_TTS_ROUTES) == set(Language)


def test_the_default_table_sends_every_language_to_elevenlabs() -> None:
    # Act / Assert — one vendor is one key, one bill and one failure mode. A second vendor
    # is reachable through BAYRAM_TTS_ROUTES the day that judgement is revisited.
    assert set(DEFAULT_TTS_ROUTES.values()) == {ELEVENLABS_NAME}


def test_parses_a_route_table_from_one_configuration_string() -> None:
    # Act
    result = parse_routes("uz_latn=other_tts, ru=elevenlabs_tts")

    # Assert
    assert is_ok(result)
    assert result.value == {
        Language.UZ_LATN: "other_tts",
        Language.RU: "elevenlabs_tts",
    }


def test_returns_err_for_a_clause_that_is_not_a_pair() -> None:
    # Act
    result = parse_routes("uz_latn")

    # Assert
    assert is_err(result)
    assert isinstance(result.error, ConfigError)


def test_returns_err_for_a_clause_naming_no_provider() -> None:
    # Act
    result = parse_routes("ru=")

    # Assert
    assert is_err(result)


def test_returns_err_for_an_unknown_language() -> None:
    # Act
    result = parse_routes("klingon=elevenlabs_tts")

    # Assert
    assert is_err(result)
    assert "unknown language" in result.error.operator_message


def test_returns_err_for_an_empty_route_table() -> None:
    # Act
    result = parse_routes("  ,  ")

    # Assert
    assert is_err(result)


# ---------------------------------------------------------------------------
# Binding
# ---------------------------------------------------------------------------
def test_binds_the_table_to_concrete_adapters() -> None:
    # Arrange
    router = _router()

    # Act / Assert
    assert router.provider_for(Language.RU) is not None
    assert set(router.languages) == set(Language)


def test_returns_err_when_a_route_names_a_provider_that_was_not_supplied() -> None:
    # Arrange
    only_other = FakeTtsProvider(name=OTHER_NAME, languages=OTHER_LANGUAGES)

    # Act
    result = build_router([only_other])

    # Assert
    assert is_err(result)
    assert "unknown provider" in result.error.operator_message
    assert "available" in result.error.context


def test_returns_err_when_two_providers_share_a_name() -> None:
    # Arrange
    twins: list[TtsProvider] = [
        FakeTtsProvider(name="same"),
        FakeTtsProvider(name="same"),
    ]

    # Act
    result = build_router(twins, routes={Language.RU: "same"})

    # Assert
    assert is_err(result)
    assert "share a name" in result.error.operator_message


def test_refuses_to_build_a_router_with_no_routes_at_all() -> None:
    # Act / Assert
    with pytest.raises(ConfigError):
        LanguageRoutingTts({})


# ---------------------------------------------------------------------------
# Delegation
# ---------------------------------------------------------------------------
async def test_sends_uzbek_to_the_uzbek_vendor() -> None:
    # Arrange
    other, eleven = _fakes()
    built = build_router([other, eleven], routes=_SPLIT_ROUTES, clock=fixed_clock)
    assert is_ok(built)

    # Act
    result = await built.value.synthesize(
        make_speech_request(language=Language.UZ_LATN, persona_id="bobo"),
        idempotency_key=IDEMPOTENCY_KEY,
        timeout_s=TIMEOUT_S,
    )

    # Assert
    assert is_ok(result)
    assert len(other.calls) == 1
    assert eleven.calls == ()


async def test_sends_english_to_the_multilingual_vendor() -> None:
    # Arrange
    other, eleven = _fakes()
    built = build_router([other, eleven], routes=_SPLIT_ROUTES, clock=fixed_clock)
    assert is_ok(built)

    # Act
    result = await built.value.synthesize(
        make_speech_request(), idempotency_key=IDEMPOTENCY_KEY, timeout_s=TIMEOUT_S
    )

    # Assert
    assert is_ok(result)
    assert len(eleven.calls) == 1
    assert other.calls == ()


async def test_returns_err_for_a_language_the_table_does_not_cover() -> None:
    # Arrange
    eleven = FakeTtsProvider(name=ELEVENLABS_NAME, languages=ELEVENLABS_LANGUAGES)
    router = LanguageRoutingTts({Language.EN: eleven}, clock=fixed_clock)

    # Act
    result = await router.synthesize(
        make_speech_request(language=Language.RU, persona_id="podruga"),
        idempotency_key=IDEMPOTENCY_KEY,
        timeout_s=TIMEOUT_S,
    )

    # Assert
    assert is_err(result)
    assert isinstance(result.error, ConfigError)


async def test_passes_the_idempotency_key_and_timeout_through_untouched() -> None:
    # Arrange
    other, eleven = _fakes()
    built = build_router([other, eleven], routes=_SPLIT_ROUTES, clock=fixed_clock)
    assert is_ok(built)

    # Act
    await built.value.synthesize(
        make_speech_request(), idempotency_key=IDEMPOTENCY_KEY, timeout_s=TIMEOUT_S
    )

    # Assert
    assert eleven.calls[0].idempotency_key == IDEMPOTENCY_KEY
    assert eleven.calls[0].timeout_s == TIMEOUT_S


# ---------------------------------------------------------------------------
# The merged catalogue
# ---------------------------------------------------------------------------
async def test_merges_every_routed_voice_into_one_catalogue() -> None:
    # Arrange
    router = _router()

    # Act
    result = await router.voices()

    # Assert — three characters in each of four languages.
    assert is_ok(result)
    assert len({voice.language for voice in result.value}) == len(Language)
    assert len(result.value) == 3 * len(Language)


async def test_omits_voices_for_a_language_routed_to_another_vendor() -> None:
    # Arrange — this vendor offers Uzbek, but Uzbek is bought elsewhere.
    greedy = FakeTtsProvider(name=ELEVENLABS_NAME)
    router = LanguageRoutingTts({Language.EN: greedy}, clock=fixed_clock)

    # Act
    result = await router.voices()

    # Assert — a persona the router would refuse must never be offered.
    assert is_ok(result)
    assert {voice.language for voice in result.value} == {Language.EN}


async def test_continues_when_one_vendor_cannot_list_its_voices() -> None:
    # Arrange
    silent = _FailingLeg(name=OTHER_NAME, languages=OTHER_LANGUAGES)
    eleven = FakeTtsProvider(name=ELEVENLABS_NAME, languages=ELEVENLABS_LANGUAGES)
    built = build_router([silent, eleven], clock=fixed_clock)
    assert is_ok(built)

    # Act
    result = await built.value.voices()

    # Assert — a thin catalogue beats no kit at all.
    assert is_ok(result)
    assert {voice.language for voice in result.value} == set(ELEVENLABS_LANGUAGES)


# ---------------------------------------------------------------------------
# Aggregate health
# ---------------------------------------------------------------------------
async def test_reports_healthy_when_every_leg_is_healthy() -> None:
    # Arrange
    router = _router()

    # Act
    result = await router.health()

    # Assert
    assert is_ok(result)
    assert result.value.state is HealthState.HEALTHY
    assert result.value.name == "tts_router"


async def test_never_reads_better_than_its_unhealthiest_leg() -> None:
    # Arrange
    sick = _FailingLeg(name=OTHER_NAME, languages=OTHER_LANGUAGES)
    eleven = FakeTtsProvider(name=ELEVENLABS_NAME, languages=ELEVENLABS_LANGUAGES)
    built = build_router([sick, eleven], routes=_SPLIT_ROUTES, clock=fixed_clock)
    assert is_ok(built)

    # Act
    result = await built.value.health()

    # Assert
    assert is_ok(result)
    assert result.value.state is HealthState.UNAVAILABLE
    assert result.value.detail is not None
    assert OTHER_NAME in result.value.detail


async def test_propagates_the_reason_when_no_leg_answers_at_all() -> None:
    # Arrange
    router = LanguageRoutingTts({Language.EN: _FailingLeg(name=ELEVENLABS_NAME)}, clock=fixed_clock)

    # Act
    result = await router.health()

    # Assert — with nothing working, the reason is authoritative, not an aggregate.
    assert is_err(result)
    assert "leg down" in result.error.operator_message


async def test_returns_err_when_no_routed_provider_offers_a_voice() -> None:
    # Arrange
    router = LanguageRoutingTts({Language.EN: _FailingLeg(name=ELEVENLABS_NAME)}, clock=fixed_clock)

    # Act
    result = await router.voices()

    # Assert
    assert is_err(result)
    assert isinstance(result.error, ConfigError)
