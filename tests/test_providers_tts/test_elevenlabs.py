"""The ElevenLabs v3 speech adapter: payload, billing, failure mapping, health."""

from __future__ import annotations

import httpx

from bayram.contracts import CostSource, HealthState, Language, is_err, is_ok
from bayram.errors import ProviderRateLimitedError, ValidationError
from bayram.providers.tts.elevenlabs import (
    DEFAULT_OUTPUT_FORMAT,
    SUPPORTED_LANGUAGES,
    ElevenLabsTts,
    mime_for_output_format,
)
from bayram.providers.tts.metering import CharacterPricing
from tests.conftest import UZBEK_NAME_CANONICAL
from tests.test_providers_tts.conftest import (
    MP3_BYTES,
    audio_response,
    error_response,
    fixed_clock,
    json_response,
    make_speech_request,
    recording_client,
)

API_KEY = "test-elevenlabs-key"
BASE_URL = "https://api.elevenlabs.io"
MODEL_ID = "eleven_v3"
TIMEOUT_S = 5.0
IDEMPOTENCY_KEY = "order-1:greeting:0"

#: 'showman' in the shipped English cast.
SHOWMAN_VOICE_ID = "iP95p4xoKVk53GoZ742B"


def _provider(
    client: httpx.AsyncClient, *, pricing: CharacterPricing | None = None
) -> ElevenLabsTts:
    return ElevenLabsTts(
        api_key=API_KEY,
        base_url=BASE_URL,
        model_id=MODEL_ID,
        pricing=pricing,
        client=client,
        clock=fixed_clock,
    )


# ---------------------------------------------------------------------------
# The request we actually send
# ---------------------------------------------------------------------------
async def test_posts_to_the_voice_id_the_registry_holds() -> None:
    # Arrange
    client, recorder = recording_client(audio_response())
    provider = _provider(client)

    # Act
    result = await provider.synthesize(
        make_speech_request(), idempotency_key=IDEMPOTENCY_KEY, timeout_s=TIMEOUT_S
    )

    # Assert — a vendor voice id appears in exactly one place in this system.
    assert is_ok(result)
    assert recorder.last.url.path == f"/v1/text-to-speech/{SHOWMAN_VOICE_ID}"


async def test_sends_the_submitted_orthography_never_the_display_name() -> None:
    # Arrange
    client, recorder = recording_client(audio_response())
    provider = _provider(client)
    request = make_speech_request(
        text=f"Happy birthday, {UZBEK_NAME_CANONICAL}!", name_submitted="Gulomjon"
    )

    # Act
    await provider.synthesize(request, idempotency_key=IDEMPOTENCY_KEY, timeout_s=TIMEOUT_S)

    # Assert — this is the whole product in one assertion.
    body = recorder.body_json()
    assert "Gulomjon" in body["text"]
    assert UZBEK_NAME_CANONICAL not in body["text"]


async def test_carries_the_api_key_and_idempotency_key_in_headers() -> None:
    # Arrange
    client, recorder = recording_client(audio_response())
    provider = _provider(client)

    # Act
    await provider.synthesize(
        make_speech_request(), idempotency_key=IDEMPOTENCY_KEY, timeout_s=TIMEOUT_S
    )

    # Assert
    assert recorder.last.headers["xi-api-key"] == API_KEY
    assert recorder.last.headers["idempotency-key"] == IDEMPOTENCY_KEY


async def test_requests_the_configured_model_and_output_format() -> None:
    # Arrange
    client, recorder = recording_client(audio_response())
    provider = _provider(client)

    # Act
    await provider.synthesize(
        make_speech_request(), idempotency_key=IDEMPOTENCY_KEY, timeout_s=TIMEOUT_S
    )

    # Assert
    assert recorder.body_json()["model_id"] == MODEL_ID
    assert recorder.last.url.params["output_format"] == DEFAULT_OUTPUT_FORMAT


async def test_prefixes_the_personas_mood_as_a_v3_audio_tag() -> None:
    # Arrange
    client, recorder = recording_client(audio_response())
    provider = _provider(client)

    # Act
    await provider.synthesize(
        make_speech_request(), idempotency_key=IDEMPOTENCY_KEY, timeout_s=TIMEOUT_S
    )

    # Assert — 'showman' defaults to [excited].
    assert recorder.body_json()["text"].startswith("[excited] ")


async def test_drops_a_mood_v3_would_read_aloud_as_words() -> None:
    # Arrange
    client, recorder = recording_client(audio_response())
    provider = _provider(client)

    # Act
    await provider.synthesize(
        make_speech_request(mood="wistful"),
        idempotency_key=IDEMPOTENCY_KEY,
        timeout_s=TIMEOUT_S,
    )

    # Assert
    assert "[" not in recorder.body_json()["text"]


async def test_never_emits_phoneme_markup_because_v3_would_speak_it() -> None:
    # Arrange
    client, recorder = recording_client(audio_response())
    provider = _provider(client)
    request = make_speech_request(name_ipa="\u0261ulomd\u0292on", name_submitted="Gulomjon")

    # Act
    await provider.synthesize(request, idempotency_key=IDEMPOTENCY_KEY, timeout_s=TIMEOUT_S)

    # Assert
    assert "<phoneme" not in recorder.body_json()["text"]


async def test_sends_the_vendor_language_code() -> None:
    # Arrange
    client, recorder = recording_client(audio_response())
    provider = _provider(client)

    # Act
    await provider.synthesize(
        make_speech_request(language=Language.RU, persona_id="podruga"),
        idempotency_key=IDEMPOTENCY_KEY,
        timeout_s=TIMEOUT_S,
    )

    # Assert
    assert recorder.body_json()["language_code"] == "ru"


# ---------------------------------------------------------------------------
# The result we build
# ---------------------------------------------------------------------------
async def test_returns_the_audio_bytes_with_the_format_mime() -> None:
    # Arrange
    client, _ = recording_client(audio_response())
    provider = _provider(client)

    # Act
    result = await provider.synthesize(
        make_speech_request(), idempotency_key=IDEMPOTENCY_KEY, timeout_s=TIMEOUT_S
    )

    # Assert
    assert is_ok(result)
    assert result.value.data == MP3_BYTES
    assert result.value.mime == "audio/mpeg"
    assert result.value.duration_s > 0


async def test_reports_zero_estimated_cost_when_no_price_was_configured() -> None:
    # Arrange
    client, _ = recording_client(audio_response())
    provider = _provider(client)

    # Act
    result = await provider.synthesize(
        make_speech_request(), idempotency_key=IDEMPOTENCY_KEY, timeout_s=TIMEOUT_S
    )

    # Assert
    assert is_ok(result)
    assert result.value.cost_usd == 0.0
    assert result.value.cost_source is CostSource.ESTIMATED


async def test_derives_cost_from_the_vendors_reported_character_count() -> None:
    # Arrange
    client, _ = recording_client(audio_response(headers={"character-cost": "100"}))
    provider = _provider(client, pricing=CharacterPricing(rate_per_character=0.0001))

    # Act
    result = await provider.synthesize(
        make_speech_request(), idempotency_key=IDEMPOTENCY_KEY, timeout_s=TIMEOUT_S
    )

    # Assert
    assert is_ok(result)
    assert result.value.cost_usd == 0.01
    assert result.value.cost_source is CostSource.DERIVED


async def test_counts_the_submitted_text_when_the_vendor_reports_nonsense() -> None:
    # Arrange
    client, _ = recording_client(audio_response(headers={"character-cost": "lots"}))
    provider = _provider(client, pricing=CharacterPricing(rate_per_character=1.0))

    # Act
    result = await provider.synthesize(
        make_speech_request(text="{name}", name_submitted="Ann"),
        idempotency_key=IDEMPOTENCY_KEY,
        timeout_s=TIMEOUT_S,
    )

    # Assert — "[excited] Ann" is 13 characters.
    assert is_ok(result)
    assert result.value.cost_usd == 13.0


async def test_keeps_the_vendor_request_id_for_support_tickets() -> None:
    # Arrange
    client, _ = recording_client(audio_response(headers={"request-id": "req_abc"}))
    provider = _provider(client)

    # Act
    result = await provider.synthesize(
        make_speech_request(), idempotency_key=IDEMPOTENCY_KEY, timeout_s=TIMEOUT_S
    )

    # Assert
    assert is_ok(result)
    assert result.value.remote_id == "req_abc"


# ---------------------------------------------------------------------------
# Failure paths
# ---------------------------------------------------------------------------
async def test_refuses_an_unknown_persona_without_opening_a_socket() -> None:
    """Every language is served now, so the persona is what can still be unserved.

    The point of the check is that it happens before the request leaves: an unresolvable
    greeting must cost nothing to discover.
    """
    # Arrange
    client, recorder = recording_client(audio_response())
    provider = _provider(client)

    # Act
    result = await provider.synthesize(
        make_speech_request(language=Language.UZ_LATN, persona_id="no-such-persona"),
        idempotency_key=IDEMPOTENCY_KEY,
        timeout_s=TIMEOUT_S,
    )

    # Assert — and no money was spent finding out.
    assert is_err(result)
    assert isinstance(result.error, ValidationError)
    assert recorder.requests == []


async def test_maps_a_rate_limit_to_a_retryable_error() -> None:
    # Arrange
    client, _ = recording_client(error_response(429, text="too many requests"))
    provider = _provider(client)

    # Act
    result = await provider.synthesize(
        make_speech_request(), idempotency_key=IDEMPOTENCY_KEY, timeout_s=TIMEOUT_S
    )

    # Assert
    assert is_err(result)
    assert isinstance(result.error, ProviderRateLimitedError)
    assert result.error.is_retryable


async def test_rejects_a_two_hundred_that_is_not_audio() -> None:
    # Arrange
    client, _ = recording_client(json_response({"detail": "queued"}))
    provider = _provider(client)

    # Act
    result = await provider.synthesize(
        make_speech_request(), idempotency_key=IDEMPOTENCY_KEY, timeout_s=TIMEOUT_S
    )

    # Assert
    assert is_err(result)
    assert result.error.is_retryable


# ---------------------------------------------------------------------------
# Catalogue and health
# ---------------------------------------------------------------------------
async def test_lists_only_the_languages_this_vendor_serves_for_us() -> None:
    # Arrange
    client, _ = recording_client(audio_response())
    provider = _provider(client)

    # Act
    result = await provider.voices()

    # Assert
    assert is_ok(result)
    assert {voice.language for voice in result.value} == set(SUPPORTED_LANGUAGES)


async def test_reports_healthy_with_the_characters_left_on_the_plan() -> None:
    # Arrange
    client, _ = recording_client(
        json_response({"character_count": 400, "character_limit": 1_000, "status": "active"})
    )
    provider = _provider(client)

    # Act
    result = await provider.health()

    # Assert
    assert is_ok(result)
    assert result.value.state is HealthState.HEALTHY
    assert result.value.quota_remaining == 600


async def test_reports_unavailable_when_the_character_quota_is_spent() -> None:
    # Arrange
    client, _ = recording_client(
        json_response({"character_count": 1_000, "character_limit": 1_000, "status": "active"})
    )
    provider = _provider(client)

    # Act
    result = await provider.health()

    # Assert
    assert is_ok(result)
    assert result.value.state is HealthState.UNAVAILABLE


async def test_reports_degraded_when_the_subscription_is_not_live() -> None:
    # Arrange
    client, _ = recording_client(
        json_response({"character_count": 0, "character_limit": 1_000, "status": "canceled"})
    )
    provider = _provider(client)

    # Act
    result = await provider.health()

    # Assert
    assert is_ok(result)
    assert result.value.state is HealthState.DEGRADED


async def test_reports_unknown_when_the_subscription_body_is_not_json() -> None:
    # Arrange
    client, _ = recording_client(httpx.Response(200, text="<html>maintenance</html>"))
    provider = _provider(client)

    # Act
    result = await provider.health()

    # Assert
    assert is_ok(result)
    assert result.value.state is HealthState.UNKNOWN


async def test_health_propagates_rejected_credentials() -> None:
    # Arrange
    client, _ = recording_client(error_response(401, text="invalid api key"))
    provider = _provider(client)

    # Act
    result = await provider.health()

    # Assert
    assert is_err(result)


async def test_health_stamps_the_injected_clock() -> None:
    # Arrange
    client, _ = recording_client(json_response({"character_count": 0, "character_limit": 10}))
    provider = _provider(client)

    # Act
    result = await provider.health()

    # Assert
    assert is_ok(result)
    assert result.value.as_of == fixed_clock()


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------
def test_maps_a_vendor_format_string_to_a_mime_type() -> None:
    # Act / Assert
    assert mime_for_output_format("mp3_44100_128") == "audio/mpeg"
    assert mime_for_output_format("opus_48000_32") == "audio/ogg"
    assert mime_for_output_format("mystery") == "application/octet-stream"


async def test_closes_only_the_client_it_created() -> None:
    # Arrange
    client, _ = recording_client(audio_response())
    provider = _provider(client)

    # Act
    await provider.aclose()

    # Assert — an injected client belongs to the caller.
    assert not client.is_closed


async def test_serves_uzbek_because_every_language_routes_here() -> None:
    """Uzbek is the default UI language and ElevenLabs is the only TTS vendor.

    This adapter once declared ``(RU, EN)`` only, from when Uzbek was bought elsewhere.
    That restricted the registry away from the Uzbek cast AND made ``prepare`` refuse the
    request, so every Uzbek kit silently lost all three greetings.
    """
    # Arrange
    client, recorder = recording_client(audio_response())
    provider = _provider(client)

    # Act
    result = await provider.synthesize(
        make_speech_request(
            text=f"Assalomu alaykum, {UZBEK_NAME_CANONICAL}!",
            persona_id="bobo",
            language=Language.UZ_LATN,
            name_submitted="Gulomjon",
        ),
        idempotency_key="order-1:greeting:1",
        timeout_s=5.0,
    )

    # Assert
    assert is_ok(result)
    assert Language.UZ_LATN in SUPPORTED_LANGUAGES
    assert Language.UZ_CYRL in SUPPORTED_LANGUAGES
    assert "Gulomjon" in recorder.last.content.decode("utf-8")


async def test_omits_the_language_code_for_uzbek_because_v3_rejects_it() -> None:
    """``eleven_v3`` 400s on ``language_code: 'uz'`` — it has no Uzbek code at all.

    Learned live: ``Model 'eleven_v3' does not support language_code 'uz'``. Dropping the
    key lets v3 auto-detect, which is how the Uzbek listening test was passed in the first
    place. Sending it fails all three greetings for the DEFAULT language.
    """
    # Arrange
    client, recorder = recording_client(audio_response())
    provider = _provider(client)

    # Act
    result = await provider.synthesize(
        make_speech_request(text="Assalomu alaykum!", persona_id="bobo", language=Language.UZ_LATN),
        idempotency_key=IDEMPOTENCY_KEY,
        timeout_s=TIMEOUT_S,
    )

    # Assert
    assert is_ok(result)
    assert "language_code" not in recorder.body_json()
