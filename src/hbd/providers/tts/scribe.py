"""ElevenLabs Scribe behind ``SttProvider``. The ear that closes the loop.

This adapter exists for one purpose: hear what the music model actually sang, so a
mispronounced name can be re-rolled with the next candidate orthography *before* the
customer hears it. It never transcribes a user's speech.

That purpose shapes two choices:

* **Keyterms are passed through.** Scribe accepts a list of terms to bias toward, and the
  intended name plus its candidate spellings is exactly that list. Biasing toward the name
  we hope to hear makes the check *more* forgiving, which is the correct direction: we are
  looking for evidence the render is wrong, and a false alarm costs a wasted re-render.
* **Confidence is derived, not invented.** Scribe reports a per-word log-probability; we
  average the real words and exponentiate. When it reports nothing we say so with a
  documented neutral value rather than fabricating certainty. The re-roll decision is made
  on string similarity elsewhere — this number is diagnostic.
"""

from __future__ import annotations

import math
from collections.abc import Callable, Mapping, Sequence
from datetime import datetime
from typing import Final

import httpx
from pydantic import BaseModel, ConfigDict

from hbd.contracts import (
    Err,
    Language,
    ProviderHealth,
    Result,
    Transcript,
    err,
    ok,
)
from hbd.errors import ValidationError
from hbd.logging import get_logger
from hbd.providers.tts.elevenlabs_api import (
    API_KEY_HEADER,
    DEFAULT_HEALTH_TIMEOUT_S,
    subscription_health,
)
from hbd.providers.tts.transport import parse_json_body, send_request, utc_now

__all__ = [
    "ElevenLabsScribe",
    "PROVIDER_NAME",
    "TRANSCRIPTION_PATH",
    "MAX_KEYTERMS",
    "MAX_KEYTERM_CHARS",
    "UNREPORTED_CONFIDENCE",
    "resolve_language",
    "SCRIBE_LANGUAGE_CODES",
    "scribe_language_code_for",
]

_LOG = get_logger(__name__)

PROVIDER_NAME: Final[str] = "elevenlabs_scribe"
TRANSCRIPTION_PATH: Final[str] = "/v1/speech-to-text"

#: Scribe accepts a bounded keyterm list; we send the name's candidate spellings and stop.
MAX_KEYTERMS: Final[int] = 20
MAX_KEYTERM_CHARS: Final[int] = 80

#: What we report when the vendor gives us no probability at all. Neither trusted nor
#: dismissed — the re-roll decision is made on string similarity, not on this.
UNREPORTED_CONFIDENCE: Final[float] = 0.5

#: A word's log-probability below this is treated as zero confidence rather than underflowing.
_MIN_LOGPROB: Final[float] = -20.0
_WORD_ENTRY_TYPE: Final[str] = "word"

_FIELD_MODEL_ID: Final[str] = "model_id"
_FIELD_LANGUAGE: Final[str] = "language_code"

#: Scribe speaks ISO 639-3, NOT the two-letter codes ``/v1/text-to-speech`` takes. Two
#: vocabularies, one vendor: sending the TTS code here earns
#: ``Invalid language code received`` and fails the name-verification loop for EVERY
#: language. Both Uzbek scripts are one spoken language, so both ask for ``uzb``.
SCRIBE_LANGUAGE_CODES: Final[Mapping[Language, str]] = {
    Language.UZ_LATN: "uzb",
    Language.UZ_CYRL: "uzb",
    Language.RU: "rus",
    Language.EN: "eng",
}

#: What the vendor may report back, in either vocabulary, folded to our language family.
_REPORTED_ALIASES: Final[Mapping[str, tuple[Language, ...]]] = {
    "uz": (Language.UZ_LATN, Language.UZ_CYRL),
    "uzb": (Language.UZ_LATN, Language.UZ_CYRL),
    "ru": (Language.RU,),
    "rus": (Language.RU,),
    "en": (Language.EN,),
    "eng": (Language.EN,),
}


def scribe_language_code_for(language: Language) -> str:
    """The ISO 639-3 code Scribe expects. Total over ``Language``."""
    return SCRIBE_LANGUAGE_CODES[language]
_FIELD_KEYTERMS: Final[str] = "keyterms"
_FIELD_DIARIZE: Final[str] = "diarize"
_FIELD_AUDIO_EVENTS: Final[str] = "tag_audio_events"

_CYRILLIC_RANGE: Final[tuple[str, str]] = ("Ѐ", "ӿ")


class ScribeWord(BaseModel):
    """One token of the transcript. ``spacing`` entries carry no probability worth averaging."""

    model_config = ConfigDict(frozen=True, extra="ignore")

    text: str = ""
    type: str = _WORD_ENTRY_TYPE
    logprob: float | None = None


class ScribePayload(BaseModel):
    """The fields of a Scribe response we read. Unknown keys are the vendor's business."""

    model_config = ConfigDict(frozen=True, extra="ignore")

    text: str = ""
    language_code: str | None = None
    language_probability: float | None = None
    words: tuple[ScribeWord, ...] = ()


def _has_cyrillic(text: str) -> bool:
    low, high = _CYRILLIC_RANGE
    return any(low <= char <= high for char in text)


def resolve_language(*, requested: Language, reported: str | None, text: str) -> Language:
    """Which of our languages the transcript is in.

    The vendor reports a spoken language, and ``uz`` is one language in two scripts, so the
    transcript's own characters break the tie. When the vendor agrees with what we asked
    for, we keep what we asked for — re-deriving it could only introduce disagreement.
    """
    if reported is None:
        return requested
    base = reported.strip().casefold().replace("_", "-").split("-")[0]
    family = _REPORTED_ALIASES.get(base)
    if family is not None:
        if len(family) == 1:
            return family[0]
        # One spoken language in two scripts: the transcript's own characters break the tie.
        return Language.UZ_CYRL if _has_cyrillic(text) else Language.UZ_LATN
    _LOG.info(
        "Scribe reported a language outside our set; keeping the requested one",
        extra={"provider": PROVIDER_NAME, "reported": reported, "requested": requested.value},
    )
    return requested


def _confidence_of(payload: ScribePayload) -> float:
    """Mean word probability, else the language probability, else the neutral value."""
    probabilities = [
        math.exp(max(word.logprob, _MIN_LOGPROB))
        for word in payload.words
        if word.type == _WORD_ENTRY_TYPE and word.logprob is not None
    ]
    if probabilities:
        return min(sum(probabilities) / len(probabilities), 1.0)
    if payload.language_probability is not None:
        return min(max(payload.language_probability, 0.0), 1.0)
    return UNREPORTED_CONFIDENCE


def _clean_keyterms(keyterms: Sequence[str]) -> list[str]:
    """De-duplicate, bound and trim. Empty and oversized terms are dropped, not sent."""
    seen: dict[str, None] = {}
    for term in keyterms:
        trimmed = term.strip()
        if trimmed and len(trimmed) <= MAX_KEYTERM_CHARS:
            seen.setdefault(trimmed, None)
        if len(seen) >= MAX_KEYTERMS:
            break
    return list(seen)


class ElevenLabsScribe:
    """``SttProvider`` over ``POST /v1/speech-to-text``. No method raises."""

    name: str = PROVIDER_NAME

    def __init__(
        self,
        *,
        api_key: str,
        base_url: str,
        model_id: str,
        health_timeout_s: float = DEFAULT_HEALTH_TIMEOUT_S,
        client: httpx.AsyncClient | None = None,
        clock: Callable[[], datetime] = utc_now,
    ) -> None:
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")
        self._model_id = model_id
        self._health_timeout_s = health_timeout_s
        self._clock = clock
        self._owns_client = client is None
        self._client = client if client is not None else httpx.AsyncClient()

    async def aclose(self) -> None:
        """Close the HTTP client, but only the one we created."""
        if self._owns_client:
            await self._client.aclose()

    # -- SttProvider --------------------------------------------------------
    async def transcribe(
        self,
        audio: bytes,
        *,
        mime: str,
        language: Language,
        keyterms: Sequence[str] = (),
        timeout_s: float,
    ) -> Result[Transcript]:
        if not audio:
            return err(
                ValidationError(
                    "cannot transcribe an empty audio payload",
                    context={"provider": self.name, "language": language.value},
                )
            )

        terms = _clean_keyterms(keyterms)
        context = {
            "operation": "transcribe",
            "language": language.value,
            "keyterm_count": len(terms),
            "audio_bytes": len(audio),
        }
        response = await send_request(
            self._client,
            provider=self.name,
            method="POST",
            url=self._base_url + TRANSCRIPTION_PATH,
            timeout_s=timeout_s,
            headers={API_KEY_HEADER: self._api_key, "accept": "application/json"},
            data=self._form(language=language, keyterms=terms),
            files={"file": ("audio", audio, mime or "application/octet-stream")},
            context=context,
        )
        if isinstance(response, Err):
            return response

        parsed = parse_json_body(response.value, ScribePayload, provider=self.name, context=context)
        if isinstance(parsed, Err):
            return parsed

        payload = parsed.value
        transcript = Transcript(
            text=payload.text,
            language=resolve_language(
                requested=language, reported=payload.language_code, text=payload.text
            ),
            confidence=_confidence_of(payload),
        )
        _LOG.info(
            "name verification transcript received",
            extra={
                "provider": self.name,
                "confidence": transcript.confidence,
                "characters": len(transcript.text),
                **context,
            },
        )
        return ok(transcript)

    async def health(self) -> Result[ProviderHealth]:
        return await subscription_health(
            self._client,
            provider=self.name,
            base_url=self._base_url,
            api_key=self._api_key,
            timeout_s=self._health_timeout_s,
            clock=self._clock,
        )

    # -- internals ----------------------------------------------------------
    def _form(self, *, language: Language, keyterms: list[str]) -> dict[str, object]:
        """Multipart fields beside the audio part. Diarisation is off: one voice, one name."""
        form: dict[str, object] = {
            _FIELD_MODEL_ID: self._model_id,
            _FIELD_LANGUAGE: scribe_language_code_for(language),
            _FIELD_DIARIZE: "false",
            _FIELD_AUDIO_EVENTS: "false",
        }
        if keyterms:
            form[_FIELD_KEYTERMS] = keyterms
        return form
