"""The Scribe adapter: keyterm biasing, derived confidence, language resolution."""

from __future__ import annotations

import math

import httpx
import pytest

from hbd.contracts import HealthState, Language, is_err, is_ok
from hbd.errors import ProviderUnavailableError, ValidationError
from hbd.providers.tts.scribe import (
    MAX_KEYTERMS,
    UNREPORTED_CONFIDENCE,
    ElevenLabsScribe,
    resolve_language,
)
from tests.test_providers_tts.conftest import (
    MP3_BYTES,
    error_response,
    fixed_clock,
    json_response,
    recording_client,
)

API_KEY = "test-elevenlabs-key"
BASE_URL = "https://api.elevenlabs.io"
MODEL_ID = "scribe_v2"
TIMEOUT_S = 5.0


def _provider(client: httpx.AsyncClient) -> ElevenLabsScribe:
    return ElevenLabsScribe(
        api_key=API_KEY,
        base_url=BASE_URL,
        model_id=MODEL_ID,
        client=client,
        clock=fixed_clock,
    )


def _body_text(content: bytes) -> str:
    """The multipart envelope as text. The audio part is binary, so it is replaced."""
    return content.decode("utf-8", errors="replace")


def _transcript_body(**overrides: object) -> dict[str, object]:
    defaults: dict[str, object] = {
        "text": "Gulomjon",
        "language_code": "uz",
        "language_probability": 0.97,
        "words": [{"text": "Gulomjon", "type": "word", "logprob": -0.1}],
    }
    return {**defaults, **overrides}


# ---------------------------------------------------------------------------
# The request
# ---------------------------------------------------------------------------
async def test_uploads_the_audio_with_the_configured_model() -> None:
    # Arrange
    client, recorder = recording_client(json_response(_transcript_body()))
    provider = _provider(client)

    # Act
    result = await provider.transcribe(
        MP3_BYTES, mime="audio/mpeg", language=Language.UZ_LATN, timeout_s=TIMEOUT_S
    )

    # Assert
    assert is_ok(result)
    assert recorder.last.url.path == "/v1/speech-to-text"
    assert MODEL_ID.encode() in recorder.last.content


async def test_biases_the_engine_toward_the_name_we_hope_to_hear() -> None:
    # Arrange
    client, recorder = recording_client(json_response(_transcript_body()))
    provider = _provider(client)

    # Act
    await provider.transcribe(
        MP3_BYTES,
        mime="audio/mpeg",
        language=Language.UZ_LATN,
        keyterms=("Gulomjon", "Gʻulomjon"),
        timeout_s=TIMEOUT_S,
    )

    # Assert — keyterm prompting is the whole reason this call takes a hint.
    body = _body_text(recorder.last.content)
    assert "Gulomjon" in body
    assert "Gʻulomjon" in body


async def test_drops_blank_and_duplicate_keyterms_before_sending() -> None:
    # Arrange
    client, recorder = recording_client(json_response(_transcript_body()))
    provider = _provider(client)

    # Act
    await provider.transcribe(
        MP3_BYTES,
        mime="audio/mpeg",
        language=Language.UZ_LATN,
        keyterms=("Ann", "  ", "Ann", ""),
        timeout_s=TIMEOUT_S,
    )

    # Assert
    assert _body_text(recorder.last.content).count('name="keyterms"') == 1


async def test_caps_an_unbounded_keyterm_list() -> None:
    # Arrange
    client, recorder = recording_client(json_response(_transcript_body()))
    provider = _provider(client)

    # Act
    await provider.transcribe(
        MP3_BYTES,
        mime="audio/mpeg",
        language=Language.UZ_LATN,
        keyterms=tuple(f"term-{index}" for index in range(MAX_KEYTERMS * 3)),
        timeout_s=TIMEOUT_S,
    )

    # Assert
    body = _body_text(recorder.last.content)
    assert body.count('name="keyterms"') == MAX_KEYTERMS


async def test_sends_no_keyterm_field_when_the_caller_gave_none() -> None:
    # Arrange
    client, recorder = recording_client(json_response(_transcript_body()))
    provider = _provider(client)

    # Act
    await provider.transcribe(
        MP3_BYTES, mime="audio/mpeg", language=Language.RU, timeout_s=TIMEOUT_S
    )

    # Assert
    assert 'name="keyterms"' not in _body_text(recorder.last.content)


async def test_returns_err_for_empty_audio_without_calling_the_vendor() -> None:
    # Arrange
    client, recorder = recording_client(json_response(_transcript_body()))
    provider = _provider(client)

    # Act
    result = await provider.transcribe(
        b"", mime="audio/mpeg", language=Language.RU, timeout_s=TIMEOUT_S
    )

    # Assert
    assert is_err(result)
    assert isinstance(result.error, ValidationError)
    assert recorder.requests == []


# ---------------------------------------------------------------------------
# Reading the answer
# ---------------------------------------------------------------------------
async def test_returns_the_transcript_text() -> None:
    # Arrange
    client, _ = recording_client(json_response(_transcript_body(text="Ghulomjon")))
    provider = _provider(client)

    # Act
    result = await provider.transcribe(
        MP3_BYTES, mime="audio/mpeg", language=Language.UZ_LATN, timeout_s=TIMEOUT_S
    )

    # Assert
    assert is_ok(result)
    assert result.value.text == "Ghulomjon"


async def test_derives_confidence_from_word_log_probabilities() -> None:
    # Arrange
    client, _ = recording_client(
        json_response(
            _transcript_body(
                words=[
                    {"text": "Gu", "type": "word", "logprob": -0.2},
                    {"text": " ", "type": "spacing", "logprob": -9.0},
                    {"text": "lomjon", "type": "word", "logprob": -0.4},
                ]
            )
        )
    )
    provider = _provider(client)

    # Act
    result = await provider.transcribe(
        MP3_BYTES, mime="audio/mpeg", language=Language.UZ_LATN, timeout_s=TIMEOUT_S
    )

    # Assert — spacing entries must not drag the score down.
    expected = (math.exp(-0.2) + math.exp(-0.4)) / 2
    assert is_ok(result)
    assert result.value.confidence == pytest.approx(expected)


async def test_falls_back_to_the_language_probability_when_no_words_carry_one() -> None:
    # Arrange
    client, _ = recording_client(
        json_response(_transcript_body(words=[], language_probability=0.61))
    )
    provider = _provider(client)

    # Act
    result = await provider.transcribe(
        MP3_BYTES, mime="audio/mpeg", language=Language.UZ_LATN, timeout_s=TIMEOUT_S
    )

    # Assert
    assert is_ok(result)
    assert result.value.confidence == pytest.approx(0.61)


async def test_reports_the_neutral_value_when_the_vendor_reports_nothing() -> None:
    # Arrange
    client, _ = recording_client(json_response({"text": "Gulomjon"}))
    provider = _provider(client)

    # Act
    result = await provider.transcribe(
        MP3_BYTES, mime="audio/mpeg", language=Language.UZ_LATN, timeout_s=TIMEOUT_S
    )

    # Assert — inventing certainty here would corrupt the re-roll decision.
    assert is_ok(result)
    assert result.value.confidence == UNREPORTED_CONFIDENCE


async def test_clamps_an_out_of_range_probability_the_vendor_sent() -> None:
    # Arrange
    client, _ = recording_client(
        json_response(_transcript_body(words=[], language_probability=1.4))
    )
    provider = _provider(client)

    # Act
    result = await provider.transcribe(
        MP3_BYTES, mime="audio/mpeg", language=Language.RU, timeout_s=TIMEOUT_S
    )

    # Assert — Transcript.confidence is bounded, and a vendor is not trusted to respect it.
    assert is_ok(result)
    assert result.value.confidence == 1.0


async def test_rejects_a_body_that_is_not_a_transcript() -> None:
    # Arrange
    client, _ = recording_client(json_response({"text": {"nested": "wrong"}}))
    provider = _provider(client)

    # Act
    result = await provider.transcribe(
        MP3_BYTES, mime="audio/mpeg", language=Language.RU, timeout_s=TIMEOUT_S
    )

    # Assert
    assert is_err(result)


async def test_maps_a_server_error_to_a_retryable_failure() -> None:
    # Arrange
    client, _ = recording_client(error_response(503))
    provider = _provider(client)

    # Act
    result = await provider.transcribe(
        MP3_BYTES, mime="audio/mpeg", language=Language.RU, timeout_s=TIMEOUT_S
    )

    # Assert
    assert is_err(result)
    assert isinstance(result.error, ProviderUnavailableError)


# ---------------------------------------------------------------------------
# Language resolution
# ---------------------------------------------------------------------------
def test_keeps_the_requested_language_when_the_vendor_agrees() -> None:
    # Act / Assert
    assert resolve_language(requested=Language.RU, reported="ru", text="Алёна") is Language.RU


def test_keeps_the_requested_language_when_the_vendor_reports_nothing() -> None:
    # Act / Assert
    assert resolve_language(requested=Language.EN, reported=None, text="Ann") is Language.EN


def test_picks_the_uzbek_script_from_the_transcripts_own_characters() -> None:
    # Act / Assert — 'uz' is one spoken language in two orthographies.
    assert (
        resolve_language(requested=Language.UZ_LATN, reported="uz", text="Ғуломжон")
        is Language.UZ_CYRL
    )
    assert (
        resolve_language(requested=Language.UZ_CYRL, reported="uz", text="Gulomjon")
        is Language.UZ_LATN
    )


def test_accepts_a_regional_language_tag() -> None:
    # Act / Assert
    assert resolve_language(requested=Language.EN, reported="en-US", text="Ann") is Language.EN


def test_maps_a_disagreeing_vendor_code_onto_our_own_set() -> None:
    # Act / Assert
    assert resolve_language(requested=Language.EN, reported="ru", text="Алёна") is Language.RU


def test_keeps_the_requested_language_when_the_vendor_names_one_we_do_not_speak() -> None:
    # Act / Assert
    assert resolve_language(requested=Language.EN, reported="fr", text="Anne") is Language.EN


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------
async def test_reports_health_from_the_shared_account() -> None:
    # Arrange
    client, _ = recording_client(
        json_response({"character_count": 10, "character_limit": 100, "status": "active"})
    )
    provider = _provider(client)

    # Act
    result = await provider.health()

    # Assert
    assert is_ok(result)
    assert result.value.state is HealthState.HEALTHY
    assert result.value.name == "elevenlabs_scribe"


def test_maps_a_vendor_uzbek_code_onto_the_script_it_actually_used() -> None:
    # Arrange / Act — we asked for Russian, the singer was clearly speaking Uzbek.
    resolved = resolve_language(requested=Language.RU, reported="uz", text="Gulomjon")

    # Assert
    assert resolved is Language.UZ_LATN


async def test_creates_and_closes_its_own_client_when_none_is_injected() -> None:
    # Arrange
    provider = ElevenLabsScribe(api_key=API_KEY, base_url=BASE_URL, model_id=MODEL_ID)

    # Act
    await provider.aclose()

    # Assert — no socket was ever opened; this only proves ownership is tracked.
    assert provider.name == "elevenlabs_scribe"


@pytest.mark.parametrize(
    ("language", "expected"),
    [
        (Language.UZ_LATN, "uzb"),
        (Language.UZ_CYRL, "uzb"),
        (Language.RU, "rus"),
        (Language.EN, "eng"),
    ],
)
async def test_sends_the_iso_639_3_code_scribe_demands(language: Language, expected: str) -> None:
    """Scribe takes ISO 639-3, NOT the two-letter codes the TTS endpoint takes.

    These are two different vocabularies on the same vendor. Sharing one map sent ``uz``,
    ``ru`` and ``en``, and Scribe 400s all three with ``Invalid language code received``.
    That broke the acoustic name-verification loop — the product's differentiator — for
    every language, not just Uzbek. Learned live.
    """
    # Arrange
    client, recorder = recording_client(json_response(_transcript_body()))
    provider = _provider(client)

    # Act
    result = await provider.transcribe(
        MP3_BYTES, language=language, mime="audio/mpeg", timeout_s=TIMEOUT_S
    )

    # Assert
    assert is_ok(result)
    assert f'name="language_code"\r\n\r\n{expected}' in _body_text(recorder.last.content)


def test_resolves_the_language_from_the_three_letter_code_the_vendor_reports() -> None:
    """Scribe answers in ISO 639-3 too, so the tie-breaker must read that form."""
    # Act / Assert
    assert resolve_language(requested=Language.RU, reported="rus", text="Гуломжон") is Language.RU
    assert resolve_language(requested=Language.EN, reported="eng", text="Gulomjon") is Language.EN
    assert (
        resolve_language(requested=Language.UZ_LATN, reported="uzb", text="Ғуломжон")
        is Language.UZ_CYRL
    )
    assert (
        resolve_language(requested=Language.UZ_CYRL, reported="uzb", text="Gulomjon")
        is Language.UZ_LATN
    )
