"""The in-process stand-ins, including the round trip that closes the name loop."""

from __future__ import annotations

from bayram.contracts import CostSource, HealthState, Language, is_err, is_ok
from bayram.errors import ProviderRateLimitedError, ValidationError
from bayram.providers.tts.fakes import (
    FakeSttProvider,
    FakeTtsProvider,
    decode_fake_audio,
    encode_fake_audio,
)
from tests.conftest import UZBEK_NAME_CANONICAL
from tests.test_providers_tts.conftest import make_speech_request

TIMEOUT_S = 5.0
IDEMPOTENCY_KEY = "order-1:greeting:0"


# ---------------------------------------------------------------------------
# The payload codec
# ---------------------------------------------------------------------------
def test_a_fake_render_round_trips_through_the_codec() -> None:
    # Arrange
    data = encode_fake_audio("Hello Ann", persona_id="bestie", language=Language.EN)

    # Act
    decoded = decode_fake_audio(data)

    # Assert
    assert decoded is not None
    assert decoded.text == "Hello Ann"
    assert decoded.persona_id == "bestie"
    assert decoded.language is Language.EN


def test_real_audio_is_not_mistaken_for_a_fake_render() -> None:
    # Act / Assert
    assert decode_fake_audio(b"\xff\xfb\x90\x64 real mp3") is None


def test_a_corrupt_fake_payload_decodes_to_nothing_rather_than_raising() -> None:
    # Arrange
    data = encode_fake_audio("x", persona_id="bestie", language=Language.EN)[:12]

    # Act / Assert
    assert decode_fake_audio(data) is None


def test_a_payload_naming_an_unknown_language_decodes_to_nothing() -> None:
    # Act / Assert
    assert decode_fake_audio(b'BAYRAMFAKE1\n{"text": "x", "language": "klingon"}') is None


# ---------------------------------------------------------------------------
# The TTS fake
# ---------------------------------------------------------------------------
async def test_renders_the_submitted_orthography_into_the_bytes() -> None:
    # Arrange
    provider = FakeTtsProvider()
    request = make_speech_request(
        text=f"Happy birthday, {UZBEK_NAME_CANONICAL}!", name_submitted="Gulomjon"
    )

    # Act
    result = await provider.synthesize(
        request, idempotency_key=IDEMPOTENCY_KEY, timeout_s=TIMEOUT_S
    )

    # Assert
    assert is_ok(result)
    decoded = decode_fake_audio(result.value.data)
    assert decoded is not None
    assert decoded.text == "Happy birthday, Gulomjon!"


async def test_records_every_call_for_inspection() -> None:
    # Arrange
    provider = FakeTtsProvider()

    # Act
    await provider.synthesize(
        make_speech_request(), idempotency_key=IDEMPOTENCY_KEY, timeout_s=TIMEOUT_S
    )

    # Assert
    assert len(provider.calls) == 1
    assert provider.calls[0].idempotency_key == IDEMPOTENCY_KEY


async def test_reports_estimated_cost_because_a_fake_bills_nothing() -> None:
    # Arrange
    provider = FakeTtsProvider()

    # Act
    result = await provider.synthesize(
        make_speech_request(), idempotency_key=IDEMPOTENCY_KEY, timeout_s=TIMEOUT_S
    )

    # Assert
    assert is_ok(result)
    assert result.value.cost_source is CostSource.ESTIMATED


async def test_refuses_a_language_it_was_not_configured_to_serve() -> None:
    # Arrange
    provider = FakeTtsProvider(languages=(Language.EN,))

    # Act
    result = await provider.synthesize(
        make_speech_request(language=Language.RU, persona_id="podruga"),
        idempotency_key=IDEMPOTENCY_KEY,
        timeout_s=TIMEOUT_S,
    )

    # Assert
    assert is_err(result)
    assert isinstance(result.error, ValidationError)


async def test_refuses_a_persona_outside_the_catalogue() -> None:
    # Arrange
    provider = FakeTtsProvider()

    # Act
    result = await provider.synthesize(
        make_speech_request(persona_id="nobody"),
        idempotency_key=IDEMPOTENCY_KEY,
        timeout_s=TIMEOUT_S,
    )

    # Assert
    assert is_err(result)


async def test_fails_persistently_when_scripted_to() -> None:
    # Arrange
    provider = FakeTtsProvider(error=ProviderRateLimitedError("busy", provider="fake_tts"))

    # Act
    first = await provider.synthesize(
        make_speech_request(), idempotency_key=IDEMPOTENCY_KEY, timeout_s=TIMEOUT_S
    )
    second = await provider.synthesize(
        make_speech_request(), idempotency_key=IDEMPOTENCY_KEY, timeout_s=TIMEOUT_S
    )

    # Assert
    assert is_err(first)
    assert is_err(second)


async def test_recovers_after_one_failure_when_scripted_to() -> None:
    # Arrange — the shape a retry-ladder test needs.
    provider = FakeTtsProvider(
        error=ProviderRateLimitedError("busy", provider="fake_tts"),
        is_persistent_failure=False,
    )

    # Act
    first = await provider.synthesize(
        make_speech_request(), idempotency_key=IDEMPOTENCY_KEY, timeout_s=TIMEOUT_S
    )
    second = await provider.synthesize(
        make_speech_request(), idempotency_key=IDEMPOTENCY_KEY, timeout_s=TIMEOUT_S
    )

    # Assert
    assert is_err(first)
    assert is_ok(second)


async def test_lists_voices_and_reports_healthy() -> None:
    # Arrange
    provider = FakeTtsProvider(languages=(Language.EN,))

    # Act
    voices = await provider.voices()
    health = await provider.health()

    # Assert
    assert is_ok(voices)
    assert {voice.language for voice in voices.value} == {Language.EN}
    assert is_ok(health)
    assert health.value.state is HealthState.HEALTHY


# ---------------------------------------------------------------------------
# The STT fake
# ---------------------------------------------------------------------------
async def test_hears_what_the_tts_fake_rendered() -> None:
    # Arrange — the pair closes the acoustic loop with no network at all.
    tts = FakeTtsProvider()
    stt = FakeSttProvider()
    rendered = await tts.synthesize(
        make_speech_request(text="{name}", name_submitted="Gulomjon"),
        idempotency_key=IDEMPOTENCY_KEY,
        timeout_s=TIMEOUT_S,
    )
    assert is_ok(rendered)

    # Act
    heard = await stt.transcribe(
        rendered.value.data,
        mime=rendered.value.mime,
        language=Language.EN,
        keyterms=("Gulomjon",),
        timeout_s=TIMEOUT_S,
    )

    # Assert
    assert is_ok(heard)
    assert heard.value.text == "Gulomjon"


async def test_a_scripted_queue_drives_successive_verification_attempts() -> None:
    # Arrange — attempt one mishears, attempt two gets it right.
    stt = FakeSttProvider(transcripts=("Golom John", "Gulomjon"))
    audio = encode_fake_audio("Gulomjon", persona_id="bobo", language=Language.UZ_LATN)

    # Act
    first = await stt.transcribe(
        audio, mime="audio/mpeg", language=Language.UZ_LATN, timeout_s=TIMEOUT_S
    )
    second = await stt.transcribe(
        audio, mime="audio/mpeg", language=Language.UZ_LATN, timeout_s=TIMEOUT_S
    )

    # Assert
    assert is_ok(first)
    assert first.value.text == "Golom John"
    assert is_ok(second)
    assert second.value.text == "Gulomjon"


async def test_hears_nothing_from_audio_it_did_not_produce() -> None:
    # Arrange
    stt = FakeSttProvider()

    # Act
    result = await stt.transcribe(
        b"\xff\xfb real audio", mime="audio/mpeg", language=Language.RU, timeout_s=TIMEOUT_S
    )

    # Assert — a fake that pretended to recognise real audio would be lying.
    assert is_ok(result)
    assert result.value.text == ""


async def test_records_the_keyterms_it_was_biased_with() -> None:
    # Arrange
    stt = FakeSttProvider(transcript="Gulomjon")

    # Act
    await stt.transcribe(
        b"anything",
        mime="audio/mpeg",
        language=Language.UZ_LATN,
        keyterms=("Gulomjon", "Gʻulomjon"),
        timeout_s=TIMEOUT_S,
    )

    # Assert
    assert stt.calls[0].keyterms == ("Gulomjon", "Gʻulomjon")


async def test_refuses_empty_audio() -> None:
    # Arrange
    stt = FakeSttProvider()

    # Act
    result = await stt.transcribe(b"", mime="audio/mpeg", language=Language.RU, timeout_s=TIMEOUT_S)

    # Assert
    assert is_err(result)


async def test_stt_fails_when_scripted_to_and_reports_healthy_otherwise() -> None:
    # Arrange
    failing = FakeSttProvider(error=ProviderRateLimitedError("busy", provider="fake_stt"))
    healthy = FakeSttProvider()

    # Act
    result = await failing.transcribe(
        b"x", mime="audio/mpeg", language=Language.EN, timeout_s=TIMEOUT_S
    )
    health = await healthy.health()

    # Assert
    assert is_err(result)
    assert is_ok(health)
    assert health.value.state is HealthState.HEALTHY
