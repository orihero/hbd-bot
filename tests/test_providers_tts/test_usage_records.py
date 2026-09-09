"""What the speech and transcription legs tell the spend panel.

The two ElevenLabs legs share an account and share nothing else about how they are billed,
and the records they write say so. Speech is billed per character, so its cost carries the
provenance of the *count*: ``DERIVED`` when the vendor's ``character-cost`` header supplied
it, ``ESTIMATED`` when we counted the submitted string ourselves, and absent entirely when
no rate is configured — which is the shipped default, so the out-of-the-box row is
``cost_usd=None`` and never ``$0.00``.

Transcription is billed per minute of audio and this system never measures a duration, so
Scribe records its calls and its latency and refuses to record a cost at all. The test that
pins that is the most important one in this file: bytes multiplied by an assumed bitrate
would look exactly like a real figure on the panel.
"""

from __future__ import annotations

import httpx

from hbd.contracts import CostSource, Language, Vendor, VendorOperation
from hbd.errors import ErrorCode, ProviderRateLimitedError
from hbd.providers.tts.elevenlabs import ElevenLabsTts
from hbd.providers.tts.fakes import FakeSttProvider, FakeTtsProvider
from hbd.providers.tts.metering import CharacterPricing
from hbd.providers.tts.scribe import ElevenLabsScribe
from hbd.usage import VendorUsage
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
SPEECH_MODEL_ID = "eleven_v3"
SCRIBE_MODEL_ID = "scribe_v2"
TIMEOUT_S = 5.0
IDEMPOTENCY_KEY = "order-1:greeting:0"

#: A rate that makes the arithmetic readable: 100 characters cost one cent.
USD_PER_CHARACTER = 0.0001


class CollectingSink:
    """A ``UsageSink`` that keeps every record. The contract forbids raising, so it cannot."""

    def __init__(self) -> None:
        self.records: list[VendorUsage] = []

    async def record(self, usage: VendorUsage) -> None:
        self.records.append(usage)

    @property
    def only(self) -> VendorUsage:
        assert len(self.records) == 1, f"expected exactly one record, got {len(self.records)}"
        return self.records[0]


def _tts(
    client: httpx.AsyncClient, *, sink: CollectingSink, pricing: CharacterPricing | None = None
) -> ElevenLabsTts:
    return ElevenLabsTts(
        api_key=API_KEY,
        base_url=BASE_URL,
        model_id=SPEECH_MODEL_ID,
        pricing=pricing,
        client=client,
        clock=fixed_clock,
        usage=sink,
    )


def _scribe(client: httpx.AsyncClient, *, sink: CollectingSink) -> ElevenLabsScribe:
    return ElevenLabsScribe(
        api_key=API_KEY,
        base_url=BASE_URL,
        model_id=SCRIBE_MODEL_ID,
        client=client,
        clock=fixed_clock,
        usage=sink,
    )


def _transcript_body() -> dict[str, object]:
    return {
        "text": "Gulomjon",
        "language_code": "uz",
        "language_probability": 0.97,
        "words": [{"text": "Gulomjon", "type": "word", "logprob": -0.1}],
    }


# ---------------------------------------------------------------------------
# Speech synthesis
# ---------------------------------------------------------------------------
async def test_a_rendered_greeting_records_one_measured_call() -> None:
    # Arrange
    client, _ = recording_client(audio_response(headers={"character-cost": "100"}))
    provider = _tts(client, sink=(sink := CollectingSink()))

    # Act
    await provider.synthesize(
        make_speech_request(), idempotency_key=IDEMPOTENCY_KEY, timeout_s=TIMEOUT_S
    )

    # Assert
    record = sink.only
    assert record.vendor is Vendor.ELEVENLABS
    assert record.operation is VendorOperation.SPEECH_SYNTHESIS
    assert record.provider == "elevenlabs_tts"
    assert record.model_id == SPEECH_MODEL_ID
    assert record.is_success is True
    assert record.billed_characters == 100
    assert record.response_bytes == len(MP3_BYTES)


async def test_the_success_path_records_the_status_the_vendor_answered_with() -> None:
    # Arrange — the status used to be captured only inside an error's context.
    client, _ = recording_client(audio_response())
    provider = _tts(client, sink=(sink := CollectingSink()))

    # Act
    await provider.synthesize(
        make_speech_request(), idempotency_key=IDEMPOTENCY_KEY, timeout_s=TIMEOUT_S
    )

    # Assert
    assert sink.only.http_status == 200


async def test_the_latency_of_the_speech_call_is_measured() -> None:
    # Arrange — this leg had no timer at all before vendor usage existed.
    client, _ = recording_client(audio_response())
    provider = _tts(client, sink=(sink := CollectingSink()))

    # Act
    await provider.synthesize(
        make_speech_request(), idempotency_key=IDEMPOTENCY_KEY, timeout_s=TIMEOUT_S
    )

    # Assert
    assert sink.only.latency_ms is not None
    assert sink.only.latency_ms >= 0


async def test_a_vendor_counted_character_total_yields_a_derived_cost() -> None:
    # Arrange
    client, _ = recording_client(audio_response(headers={"character-cost": "100"}))
    provider = _tts(
        client,
        sink=(sink := CollectingSink()),
        pricing=CharacterPricing(rate_per_character=USD_PER_CHARACTER),
    )

    # Act
    await provider.synthesize(
        make_speech_request(), idempotency_key=IDEMPOTENCY_KEY, timeout_s=TIMEOUT_S
    )

    # Assert — our rate over the vendor's own billed count.
    assert sink.only.cost_usd == 0.01
    assert sink.only.cost_source is CostSource.DERIVED


async def test_our_own_character_count_yields_an_estimated_cost() -> None:
    # Arrange — no character-cost header, so we counted the submitted text ourselves.
    client, _ = recording_client(audio_response())
    provider = _tts(
        client,
        sink=(sink := CollectingSink()),
        pricing=CharacterPricing(rate_per_character=USD_PER_CHARACTER),
    )
    request = make_speech_request(text="{name}", name_submitted="Ann")

    # Act
    await provider.synthesize(request, idempotency_key=IDEMPOTENCY_KEY, timeout_s=TIMEOUT_S)

    # Assert — the submitted string "[excited] Ann" is 13 characters, mood tag included,
    # because the tag is text the vendor is asked to read and therefore text it bills for.
    assert sink.only.billed_characters == 13
    assert sink.only.cost_source is CostSource.ESTIMATED


async def test_a_deployment_with_no_speech_rate_records_no_cost_rather_than_zero() -> None:
    # Arrange — elevenlabs_usd_per_character ships at 0.0, so this is the default deployment.
    client, _ = recording_client(audio_response(headers={"character-cost": "100"}))
    provider = _tts(client, sink=(sink := CollectingSink()))

    # Act
    await provider.synthesize(
        make_speech_request(), idempotency_key=IDEMPOTENCY_KEY, timeout_s=TIMEOUT_S
    )

    # Assert — the characters are measured; the money is not, and is absent rather than 0.0.
    assert sink.only.billed_characters == 100
    assert sink.only.cost_usd is None
    assert sink.only.cost_source is None


async def test_a_rejected_speech_request_is_recorded_as_a_failure() -> None:
    # Arrange
    client, _ = recording_client(error_response(429))
    provider = _tts(client, sink=(sink := CollectingSink()))

    # Act
    await provider.synthesize(
        make_speech_request(), idempotency_key=IDEMPOTENCY_KEY, timeout_s=TIMEOUT_S
    )

    # Assert
    record = sink.only
    assert record.is_success is False
    assert record.http_status == 429
    assert record.error_code == ErrorCode.RATE_LIMITED.value
    assert record.cost_usd is None
    assert record.billed_characters is None


async def test_a_two_hundred_that_is_not_audio_is_recorded_as_a_failure() -> None:
    # Arrange
    client, _ = recording_client(json_response({"detail": "not audio"}))
    provider = _tts(client, sink=(sink := CollectingSink()))

    # Act
    await provider.synthesize(
        make_speech_request(), idempotency_key=IDEMPOTENCY_KEY, timeout_s=TIMEOUT_S
    )

    # Assert
    record = sink.only
    assert record.is_success is False
    assert record.http_status == 200
    assert record.error_code == ErrorCode.UPSTREAM_MALFORMED.value


async def test_a_request_the_adapter_refuses_reaches_no_vendor_and_records_nothing() -> None:
    # Arrange — an unknown persona never becomes a call, so there is no call to describe.
    client, _ = recording_client(audio_response())
    provider = _tts(client, sink=(sink := CollectingSink()))

    # Act
    await provider.synthesize(
        make_speech_request(persona_id="nobody"),
        idempotency_key=IDEMPOTENCY_KEY,
        timeout_s=TIMEOUT_S,
    )

    # Assert
    assert sink.records == []


async def test_a_speech_health_probe_is_recorded_and_is_never_priced() -> None:
    # Arrange
    client, _ = recording_client(
        json_response({"character_count": 10, "character_limit": 1_000, "status": "active"})
    )
    provider = _tts(client, sink=(sink := CollectingSink()))

    # Act
    await provider.health()

    # Assert
    record = sink.only
    assert record.operation is VendorOperation.HEALTH
    assert record.is_success is True
    assert record.cost_usd is None
    assert record.cost_source is None


async def test_a_rejected_credential_makes_the_health_probe_a_recorded_failure() -> None:
    # Arrange
    client, _ = recording_client(error_response(401))
    provider = _tts(client, sink=(sink := CollectingSink()))

    # Act
    await provider.health()

    # Assert
    record = sink.only
    assert record.is_success is False
    assert record.http_status == 401
    assert record.error_code == ErrorCode.CONFIG_INVALID.value


# ---------------------------------------------------------------------------
# Transcription
# ---------------------------------------------------------------------------
async def test_a_transcription_records_the_bytes_it_uploaded_and_its_latency() -> None:
    # Arrange
    client, _ = recording_client(json_response(_transcript_body()))
    provider = _scribe(client, sink=(sink := CollectingSink()))

    # Act
    await provider.transcribe(
        MP3_BYTES, mime="audio/mpeg", language=Language.UZ_LATN, timeout_s=TIMEOUT_S
    )

    # Assert
    record = sink.only
    assert record.vendor is Vendor.ELEVENLABS
    assert record.operation is VendorOperation.TRANSCRIPTION
    assert record.provider == "elevenlabs_scribe"
    assert record.model_id == SCRIBE_MODEL_ID
    assert record.is_success is True
    assert record.http_status == 200
    assert record.request_bytes == len(MP3_BYTES)
    assert record.latency_ms is not None


async def test_transcription_never_records_a_cost_or_an_audio_duration() -> None:
    # Arrange
    client, _ = recording_client(json_response(_transcript_body()))
    provider = _scribe(client, sink=(sink := CollectingSink()))

    # Act
    await provider.transcribe(
        MP3_BYTES, mime="audio/mpeg", language=Language.UZ_LATN, timeout_s=TIMEOUT_S
    )

    # Assert — Scribe bills per minute of audio and nothing here measures a minute.
    record = sink.only
    assert record.cost_usd is None
    assert record.cost_source is None
    assert record.audio_ms is None


async def test_a_failed_transcription_is_recorded_with_its_typed_code() -> None:
    # Arrange
    client, _ = recording_client(error_response(503))
    provider = _scribe(client, sink=(sink := CollectingSink()))

    # Act
    await provider.transcribe(
        MP3_BYTES, mime="audio/mpeg", language=Language.UZ_LATN, timeout_s=TIMEOUT_S
    )

    # Assert
    record = sink.only
    assert record.is_success is False
    assert record.http_status == 503
    assert record.error_code == ErrorCode.UPSTREAM_5XX.value
    assert record.request_bytes == len(MP3_BYTES)


async def test_an_unreadable_transcription_body_is_recorded_as_a_failure() -> None:
    # Arrange
    client, _ = recording_client(httpx.Response(200, text="not json at all"))
    provider = _scribe(client, sink=(sink := CollectingSink()))

    # Act
    await provider.transcribe(
        MP3_BYTES, mime="audio/mpeg", language=Language.UZ_LATN, timeout_s=TIMEOUT_S
    )

    # Assert
    record = sink.only
    assert record.is_success is False
    assert record.http_status == 200
    assert record.error_code == ErrorCode.UPSTREAM_MALFORMED.value


async def test_an_empty_audio_payload_reaches_no_vendor_and_records_nothing() -> None:
    # Arrange
    client, _ = recording_client(json_response(_transcript_body()))
    provider = _scribe(client, sink=(sink := CollectingSink()))

    # Act
    await provider.transcribe(
        b"", mime="audio/mpeg", language=Language.UZ_LATN, timeout_s=TIMEOUT_S
    )

    # Assert
    assert sink.records == []


# ---------------------------------------------------------------------------
# The fakes
# ---------------------------------------------------------------------------
async def test_the_fake_speech_provider_records_its_calls_as_fake_and_unpriced() -> None:
    # Arrange
    sink = CollectingSink()
    provider = FakeTtsProvider(usage=sink)

    # Act
    await provider.synthesize(
        make_speech_request(), idempotency_key=IDEMPOTENCY_KEY, timeout_s=TIMEOUT_S
    )

    # Assert — a demo run must be visibly excluded, never invisible.
    record = sink.only
    assert record.vendor is Vendor.FAKE
    assert record.provider == "fake_tts"
    assert record.is_fake is True
    assert record.is_success is True
    assert record.cost_usd is None
    assert record.cost_source is None


async def test_the_fake_speech_provider_records_an_injected_failure() -> None:
    # Arrange
    sink = CollectingSink()
    provider = FakeTtsProvider(
        usage=sink, error=ProviderRateLimitedError("scripted", provider="fake_tts")
    )

    # Act
    await provider.synthesize(
        make_speech_request(), idempotency_key=IDEMPOTENCY_KEY, timeout_s=TIMEOUT_S
    )

    # Assert
    record = sink.only
    assert record.is_success is False
    assert record.error_code == ErrorCode.RATE_LIMITED.value


async def test_the_fake_ear_records_a_transcription_it_never_paid_for() -> None:
    # Arrange
    sink = CollectingSink()
    provider = FakeSttProvider(usage=sink, transcript="Gulomjon")

    # Act
    await provider.transcribe(
        MP3_BYTES, mime="audio/mpeg", language=Language.UZ_LATN, timeout_s=TIMEOUT_S
    )

    # Assert
    record = sink.only
    assert record.operation is VendorOperation.TRANSCRIPTION
    assert record.is_fake is True
    assert record.request_bytes == len(MP3_BYTES)
    assert record.cost_usd is None
