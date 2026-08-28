"""ElevenLabs v3 behind ``TtsProvider``. All four languages.

v3 does not list Uzbek on its published TTS roster, but a listening test found its Uzbek
good enough to ship, and it is the only TTS vendor here — see ``router`` for where that
choice is expressed.

The pronunciation story on this leg is worth being blunt about: **v3 does not support
``<phoneme>`` markup**, IPA, lexicons or stress marks. There is no vendor feature to reach
for. Pronunciation is therefore carried entirely by the ranked candidate orthography in
``SpeechRequest.name_submitted``, which this adapter substitutes into the script verbatim.
The registry declares ``supports_phoneme_override=False`` for exactly that reason, and if a
future model gains the feature, flipping the flag is the whole change.

What v3 *does* offer is bracketed audio tags — ``[excited]``, ``[warmly]`` — which is how a
persona's mood is expressed. Unknown moods are dropped rather than injected, because an
unrecognised bracket is read aloud as words.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import datetime
from typing import Any, Final

import httpx

from hbd.contracts import (
    Err,
    Language,
    ProviderHealth,
    RenderedAudio,
    Result,
    SpeechRequest,
    VoiceDescriptor,
    ok,
)
from hbd.logging import get_logger
from hbd.providers.tts.elevenlabs_api import (
    API_KEY_HEADER,
    DEFAULT_HEALTH_TIMEOUT_S,
    IDEMPOTENCY_HEADER,
    language_code_for,
    subscription_health,
)
from hbd.providers.tts.markup import apply_mood_tag
from hbd.providers.tts.metering import (
    DEFAULT_SPEECH_CHARS_PER_SECOND,
    CharacterPricing,
    estimate_speech_duration_s,
)
from hbd.providers.tts.preparation import prepare_speech
from hbd.providers.tts.registry import VoiceRegistry, default_registry
from hbd.providers.tts.transport import read_audio_body, send_request, utc_now

__all__ = [
    "ElevenLabsTts",
    "PROVIDER_NAME",
    "SUPPORTED_LANGUAGES",
    "SPEECH_PATH_TEMPLATE",
    "DEFAULT_OUTPUT_FORMAT",
    "DEFAULT_VOICE_SETTINGS",
    "mime_for_output_format",
]

_LOG = get_logger(__name__)

PROVIDER_NAME: Final[str] = "elevenlabs_tts"

#: Every language, because every language routes here. Narrowing this silently drops the
#: excluded cast from the registry AND makes ``prepare`` refuse the request, so a language
#: missing from this tuple loses all three of its greetings without an error anyone sees
#: until delivery.
SUPPORTED_LANGUAGES: Final[tuple[Language, ...]] = (
    Language.UZ_LATN,
    Language.UZ_CYRL,
    Language.RU,
    Language.EN,
)

SPEECH_PATH_TEMPLATE: Final[str] = "/v1/text-to-speech/{voice_id}"
DEFAULT_OUTPUT_FORMAT: Final[str] = "mp3_44100_128"

#: Deliberately steady rather than expressive: a greeting that swerves in delivery also
#: swerves in how it pronounces an unfamiliar name, and the name is the product.
DEFAULT_VOICE_SETTINGS: Final[Mapping[str, Any]] = {
    "stability": 0.5,
    "similarity_boost": 0.75,
    "style": 0.35,
    "use_speaker_boost": True,
}

#: Some accounts return a billed-character count on the response. When absent we count the
#: submitted string ourselves, which is the same figure the vendor's own docs describe.
_CHARACTER_COST_HEADERS: Final[tuple[str, ...]] = ("character-cost", "x-character-cost")
_REQUEST_ID_HEADERS: Final[tuple[str, ...]] = ("request-id", "x-request-id")

_MIME_BY_FORMAT_PREFIX: Final[Mapping[str, str]] = {
    "mp3": "audio/mpeg",
    "opus": "audio/ogg",
    "ogg": "audio/ogg",
    "pcm": "audio/wave",
    "ulaw": "audio/basic",
    "alaw": "audio/basic",
}
_FALLBACK_MIME: Final[str] = "application/octet-stream"


def mime_for_output_format(output_format: str) -> str:
    """Best-effort MIME for a vendor format string such as ``mp3_44100_128``."""
    prefix = output_format.split("_", maxsplit=1)[0].casefold()
    return _MIME_BY_FORMAT_PREFIX.get(prefix, _FALLBACK_MIME)


def _first_header(headers: httpx.Headers, names: tuple[str, ...]) -> str | None:
    for name in names:
        value: str | None = headers.get(name)
        if value:
            return value
    return None


def _billed_characters(headers: httpx.Headers, *, submitted: str) -> int:
    """What we will be charged for: the vendor's count when offered, else our own."""
    reported = _first_header(headers, _CHARACTER_COST_HEADERS)
    if reported is None:
        return len(submitted)
    try:
        parsed = int(reported)
    except ValueError:
        _LOG.warning(
            "vendor reported a non-numeric character cost; counting the submitted text",
            extra={"provider": PROVIDER_NAME, "reported": reported},
        )
        return len(submitted)
    return max(parsed, 0)


class ElevenLabsTts:
    """``TtsProvider`` over ``POST /v1/text-to-speech/{voice_id}``.

    No method raises: an exception escaping here would bypass the retry ladder's
    ``is_retryable`` decision, which is the only thing telling "try again" from "stop".
    """

    name: str = PROVIDER_NAME

    def __init__(
        self,
        *,
        api_key: str,
        base_url: str,
        model_id: str,
        output_format: str = DEFAULT_OUTPUT_FORMAT,
        registry: VoiceRegistry | None = None,
        pricing: CharacterPricing | None = None,
        voice_settings: Mapping[str, Any] | None = None,
        chars_per_second: float = DEFAULT_SPEECH_CHARS_PER_SECOND,
        health_timeout_s: float = DEFAULT_HEALTH_TIMEOUT_S,
        client: httpx.AsyncClient | None = None,
        clock: Callable[[], datetime] = utc_now,
    ) -> None:
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")
        self._model_id = model_id
        self._output_format = output_format
        self._registry = (registry or default_registry()).restricted_to(SUPPORTED_LANGUAGES)
        self._pricing = pricing or CharacterPricing()
        self._voice_settings = dict(voice_settings or DEFAULT_VOICE_SETTINGS)
        self._chars_per_second = chars_per_second
        self._health_timeout_s = health_timeout_s
        self._clock = clock
        self._owns_client = client is None
        self._client = client if client is not None else httpx.AsyncClient()

    async def aclose(self) -> None:
        """Close the HTTP client, but only the one we created."""
        if self._owns_client:
            await self._client.aclose()

    # -- TtsProvider --------------------------------------------------------
    async def synthesize(
        self, request: SpeechRequest, *, idempotency_key: str, timeout_s: float
    ) -> Result[RenderedAudio]:
        prepared = prepare_speech(
            request,
            registry=self._registry,
            provider=self.name,
            supported_languages=SUPPORTED_LANGUAGES,
        )
        if isinstance(prepared, Err):
            return prepared
        speech = prepared.value

        submitted, is_mood_applied = self._with_mood(speech.text, speech.mood)
        response = await send_request(
            self._client,
            provider=self.name,
            method="POST",
            url=self._base_url + SPEECH_PATH_TEMPLATE.format(voice_id=speech.entry.vendor_voice_id),
            timeout_s=timeout_s,
            headers={
                API_KEY_HEADER: self._api_key,
                IDEMPOTENCY_HEADER: idempotency_key,
                "accept": "audio/mpeg",
            },
            params={"output_format": self._output_format},
            json_body=self._body(submitted, language=request.language),
            context={
                "operation": "synthesize",
                "persona_id": speech.entry.persona_id,
                "language": request.language.value,
            },
        )
        if isinstance(response, Err):
            return response

        audio = read_audio_body(
            response.value, provider=self.name, context={"persona_id": speech.entry.persona_id}
        )
        if isinstance(audio, Err):
            return audio

        return ok(
            self._rendered(
                audio.value,
                headers=response.value.headers,
                submitted=submitted,
                spoken=speech.spoken_text,
                persona_id=speech.entry.persona_id,
                is_mood_applied=is_mood_applied,
                is_name_applied=speech.is_name_applied,
            )
        )

    async def voices(self) -> Result[tuple[VoiceDescriptor, ...]]:
        """Our personas for this vendor. The catalogue is ours, so this never fails."""
        return ok(self._registry.descriptors())

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
    def _with_mood(self, text: str, mood: str | None) -> tuple[str, bool]:
        if mood is None:
            return (text, False)
        tagged, is_applied = apply_mood_tag(text, mood)
        if not is_applied:
            _LOG.info(
                "mood is not a v3 audio tag and was dropped rather than spoken aloud",
                extra={"provider": self.name, "mood": mood},
            )
        return (tagged, is_applied)

    def _body(self, text: str, *, language: Language) -> dict[str, Any]:
        body: dict[str, Any] = {
            "text": text,
            "model_id": self._model_id,
            "voice_settings": dict(self._voice_settings),
        }
        # Omitted, never sent as null: the vendor validates the field's VALUE, so a null
        # is a rejected request rather than "you decide". Absent means auto-detect.
        code = language_code_for(language)
        if code is not None:
            body["language_code"] = code
        return body

    def _rendered(
        self,
        data: bytes,
        *,
        headers: httpx.Headers,
        submitted: str,
        spoken: str,
        persona_id: str,
        is_mood_applied: bool,
        is_name_applied: bool,
    ) -> RenderedAudio:
        characters = _billed_characters(headers, submitted=submitted)
        cost_usd, cost_source = self._pricing.cost_for(characters)
        _LOG.info(
            "speech rendered",
            extra={
                "provider": self.name,
                "persona_id": persona_id,
                "billed_characters": characters,
                "cost_usd": cost_usd,
                "cost_source": cost_source.value,
                "is_mood_applied": is_mood_applied,
                "is_name_applied": is_name_applied,
                "bytes": len(data),
            },
        )
        return RenderedAudio(
            data=data,
            mime=mime_for_output_format(self._output_format),
            duration_s=estimate_speech_duration_s(spoken, chars_per_second=self._chars_per_second),
            remote_id=_first_header(headers, _REQUEST_ID_HEADERS),
            cost_usd=cost_usd,
            cost_source=cost_source,
        )
