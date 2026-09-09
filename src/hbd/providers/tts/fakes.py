"""In-process stand-ins for the speech vendors. Tests and local dev, never production.

The interesting property here is that the two fakes **fit together**. ``FakeTtsProvider``
encodes the text it was asked to speak into the bytes it returns, and ``FakeSttProvider``
decodes those bytes back into a transcript. Run the name-verification loop against the
pair and it genuinely closes: a candidate orthography that reaches the engine comes back
out of the ear, a mismatch re-rolls, and none of it needs a network, a key or a wallet.

Feeding a fake a real recording is fine too — it simply falls back to the scripted
transcript, because a fake that pretended to recognise arbitrary audio would be lying.

**The bytes are real audio.** The script rides in an ID3v2 tag in front of a genuine
silent MP3 stream, because every decoder skips an ID3v2 tag by its declared length. An
earlier revision returned the marker alone; it satisfied every unit test in this package
and then failed the first time the pipeline handed it to ffmpeg — ``to_voice_note`` is a
hard failure, so a whole kit died on a fake that only looked like audio to its own tests.

**The fakes measure themselves too**, with ``vendor=FAKE``, ``is_fake=True`` and no cost.
A ``HBD_USE_FAKE_PROVIDERS`` run that recorded nothing would look exactly like a deployment
where the worker was never instrumented, and telling those two apart is the whole point of
the vendor panel's capability flags. Nothing here is priced or timed: there is no vendor,
so there is no spend and no vendor latency, and inventing either would be a fabricated
number in the one place this design refuses them.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Final

from hbd.contracts import (
    CostSource,
    HealthState,
    Language,
    ProviderHealth,
    RenderedAudio,
    Result,
    SpeechRequest,
    Transcript,
    Vendor,
    VendorOperation,
    VoiceDescriptor,
    err,
    ok,
)
from hbd.errors import HbdError, ValidationError

# The one MP3 frame table in the codebase. Duplicating it here so the tts package did
# not import the music package is exactly how two silent-MP3 generators drift apart.
from hbd.providers.music.fake import silent_mp3
from hbd.providers.tts.markup import apply_name
from hbd.providers.tts.metering import estimate_speech_duration_s
from hbd.providers.tts.registry import VoiceRegistry, default_registry
from hbd.providers.tts.transport import utc_now
from hbd.usage import LOGGING_USAGE_SINK, UsageSink, VendorUsage

__all__ = [
    "FAKE_AUDIO_MAGIC",
    "FakeAudioPayload",
    "FakeSttProvider",
    "FakeTtsProvider",
    "SynthesisCall",
    "TranscriptionCall",
    "decode_fake_audio",
    "encode_fake_audio",
]

#: Marks a payload as ours, so a real recording is never mistaken for an encoded script.
FAKE_AUDIO_MAGIC: Final[bytes] = b"HBDFAKE1"
_HEADER_SEPARATOR: Final[bytes] = b"\n"
_DEFAULT_MIME: Final[str] = "audio/mpeg"
_DEFAULT_CONFIDENCE: Final[float] = 0.92

#: ID3v2.3, no flags. Ten bytes of header, then ``size`` bytes every decoder skips.
_ID3_MAGIC: Final[bytes] = b"ID3"
_ID3_HEADER_BYTES: Final[int] = 10
_ID3_VERSION: Final[bytes] = b"\x03\x00"
_ID3_FLAGS: Final[bytes] = b"\x00"
#: ID3 sizes are "syncsafe": seven bits per byte, so no byte can look like a frame sync.
_SYNCSAFE_BITS: Final[int] = 7
_SYNCSAFE_MASK: Final[int] = 0x7F
_SYNCSAFE_BYTES: Final[int] = 4
_MAX_TAG_BYTES: Final[int] = (1 << (_SYNCSAFE_BITS * _SYNCSAFE_BYTES)) - 1


def _syncsafe(size: int) -> bytes:
    return bytes(
        (size >> (_SYNCSAFE_BITS * shift)) & _SYNCSAFE_MASK
        for shift in reversed(range(_SYNCSAFE_BYTES))
    )


def _unsyncsafe(raw: bytes) -> int:
    size = 0
    for byte in raw:
        size = (size << _SYNCSAFE_BITS) | (byte & _SYNCSAFE_MASK)
    return size


@dataclass(frozen=True, slots=True)
class FakeAudioPayload:
    """What a fake render carried: the exact string that was going to be spoken."""

    text: str
    persona_id: str
    language: Language


def encode_fake_audio(
    text: str, *, persona_id: str, language: Language, duration_s: float | None = None
) -> bytes:
    """Pack a script into a genuine, decodable, silent MP3 that also carries the script."""
    header = json.dumps(
        {"text": text, "persona_id": persona_id, "language": language.value},
        ensure_ascii=False,
    ).encode("utf-8")
    marker = FAKE_AUDIO_MAGIC + _HEADER_SEPARATOR + header
    if len(marker) > _MAX_TAG_BYTES:  # pragma: no cover - a 256 MB script is not a thing
        marker = marker[:_MAX_TAG_BYTES]
    tag = _ID3_MAGIC + _ID3_VERSION + _ID3_FLAGS + _syncsafe(len(marker)) + marker
    seconds = duration_s if duration_s is not None else estimate_speech_duration_s(text)
    return tag + silent_mp3(seconds)


def _marker_of(data: bytes) -> bytes | None:
    """The ID3v2 payload, or the whole buffer for the pre-ID3 marker-only form."""
    if data.startswith(FAKE_AUDIO_MAGIC + _HEADER_SEPARATOR):
        return data
    if not data.startswith(_ID3_MAGIC) or len(data) < _ID3_HEADER_BYTES:
        return None
    size = _unsyncsafe(data[6:_ID3_HEADER_BYTES])
    end = _ID3_HEADER_BYTES + size
    if end > len(data):
        return None
    payload = data[_ID3_HEADER_BYTES:end]
    return payload if payload.startswith(FAKE_AUDIO_MAGIC + _HEADER_SEPARATOR) else None


def decode_fake_audio(data: bytes) -> FakeAudioPayload | None:
    """Unpack a fake render, or ``None`` for anything we did not produce."""
    marker = _marker_of(data)
    if marker is None:
        return None
    raw = marker[len(FAKE_AUDIO_MAGIC) + len(_HEADER_SEPARATOR) :]
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        return None
    if not isinstance(payload, dict):
        return None
    try:
        language = Language(str(payload.get("language", "")))
    except ValueError:
        return None
    return FakeAudioPayload(
        text=str(payload.get("text", "")),
        persona_id=str(payload.get("persona_id", "")),
        language=language,
    )


@dataclass(frozen=True, slots=True)
class SynthesisCall:
    """One recorded ``synthesize`` invocation."""

    request: SpeechRequest
    idempotency_key: str
    timeout_s: float


@dataclass(frozen=True, slots=True)
class TranscriptionCall:
    """One recorded ``transcribe`` invocation."""

    audio: bytes
    mime: str
    language: Language
    keyterms: tuple[str, ...]
    timeout_s: float


def _fake_usage(
    *,
    operation: VendorOperation,
    provider: str,
    is_success: bool,
    error: HbdError | None = None,
    request_bytes: int | None = None,
    response_bytes: int | None = None,
) -> VendorUsage:
    """The record a fake writes: what it did, and nothing it did not measure.

    ``cost_usd``, ``latency_ms`` and ``billed_characters`` are absent by construction and
    not by oversight. No vendor was contacted, so no money was spent, no round trip was
    timed and nothing was billed per character — and a fake that reported plausible-looking
    figures for those would be the most convincing fabricated number in the system.
    """
    return VendorUsage(
        vendor=Vendor.FAKE,
        operation=operation,
        provider=provider,
        is_success=is_success,
        is_fake=True,
        error_code=error.error_code.value if error is not None else None,
        request_bytes=request_bytes,
        response_bytes=response_bytes,
    )


class _Failing:
    """Shared failure script: fail every call, or only the first, or never."""

    def __init__(self, error: HbdError | None, *, is_persistent: bool) -> None:
        self._error = error
        self._is_persistent = is_persistent
        self._served = 0

    def next_error(self) -> HbdError | None:
        if self._error is None:
            return None
        if self._is_persistent:
            return self._error
        self._served += 1
        return self._error if self._served == 1 else None


class FakeTtsProvider:
    """A ``TtsProvider`` that renders scripts into inspectable bytes."""

    def __init__(
        self,
        *,
        name: str = "fake_tts",
        registry: VoiceRegistry | None = None,
        languages: Sequence[Language] | None = None,
        error: HbdError | None = None,
        is_persistent_failure: bool = True,
        mime: str = _DEFAULT_MIME,
        cost_usd: float = 0.0,
        clock: Callable[[], datetime] = utc_now,
        usage: UsageSink = LOGGING_USAGE_SINK,
    ) -> None:
        self.name = name
        base = registry or default_registry()
        self._registry = base if languages is None else base.restricted_to(languages)
        self._languages = frozenset(languages if languages is not None else base.languages)
        self._mime = mime
        self._cost_usd = cost_usd
        self._usage = usage
        self._clock = clock
        self._failures = _Failing(error, is_persistent=is_persistent_failure)
        self._calls: list[SynthesisCall] = []

    @property
    def calls(self) -> tuple[SynthesisCall, ...]:
        """Everything asked of this provider, oldest first."""
        return tuple(self._calls)

    async def synthesize(
        self, request: SpeechRequest, *, idempotency_key: str, timeout_s: float
    ) -> Result[RenderedAudio]:
        self._calls.append(
            SynthesisCall(request=request, idempotency_key=idempotency_key, timeout_s=timeout_s)
        )
        failure = self._failures.next_error()
        if failure is not None:
            await self._record(is_success=False, error=failure)
            return err(failure)
        if request.language not in self._languages:
            return err(
                ValidationError(
                    f"{self.name} does not serve {request.language.value}",
                    context={"provider": self.name, "language": request.language.value},
                )
            )
        if self._registry.get(request.persona_id, language=request.language) is None:
            return err(
                ValidationError(
                    f"unknown persona '{request.persona_id}' for {request.language.value}",
                    context={"provider": self.name, "persona_id": request.persona_id},
                )
            )

        spoken = _substitute_name(request)
        duration_s = estimate_speech_duration_s(spoken)
        data = encode_fake_audio(
            spoken,
            persona_id=request.persona_id,
            language=request.language,
            duration_s=duration_s,
        )
        await self._record(is_success=True, response_bytes=len(data))
        return ok(
            RenderedAudio(
                data=data,
                mime=self._mime,
                duration_s=duration_s,
                cost_usd=self._cost_usd,
                cost_source=CostSource.ESTIMATED,
            )
        )

    async def voices(self) -> Result[tuple[VoiceDescriptor, ...]]:
        return ok(self._registry.descriptors())

    async def health(self) -> Result[ProviderHealth]:
        await self._usage.record(
            _fake_usage(operation=VendorOperation.HEALTH, provider=self.name, is_success=True)
        )
        return ok(ProviderHealth(name=self.name, state=HealthState.HEALTHY, as_of=self._clock()))

    # -- internals ----------------------------------------------------------
    async def _record(
        self,
        *,
        is_success: bool,
        error: HbdError | None = None,
        response_bytes: int | None = None,
    ) -> None:
        await self._usage.record(
            _fake_usage(
                operation=VendorOperation.SPEECH_SYNTHESIS,
                provider=self.name,
                is_success=is_success,
                error=error,
                response_bytes=response_bytes,
            )
        )


class FakeSttProvider:
    """An ``SttProvider`` that hears what :class:`FakeTtsProvider` rendered."""

    def __init__(
        self,
        *,
        name: str = "fake_stt",
        transcript: str | None = None,
        transcripts: Sequence[str] = (),
        confidence: float = _DEFAULT_CONFIDENCE,
        error: HbdError | None = None,
        is_persistent_failure: bool = True,
        clock: Callable[[], datetime] = utc_now,
        usage: UsageSink = LOGGING_USAGE_SINK,
    ) -> None:
        self.name = name
        self._transcript = transcript
        self._queue = list(transcripts)
        self._confidence = confidence
        self._usage = usage
        self._clock = clock
        self._failures = _Failing(error, is_persistent=is_persistent_failure)
        self._calls: list[TranscriptionCall] = []

    @property
    def calls(self) -> tuple[TranscriptionCall, ...]:
        return tuple(self._calls)

    async def transcribe(
        self,
        audio: bytes,
        *,
        mime: str,
        language: Language,
        keyterms: Sequence[str] = (),
        timeout_s: float,
    ) -> Result[Transcript]:
        self._calls.append(
            TranscriptionCall(
                audio=audio,
                mime=mime,
                language=language,
                keyterms=tuple(keyterms),
                timeout_s=timeout_s,
            )
        )
        failure = self._failures.next_error()
        if failure is not None:
            await self._record(is_success=False, request_bytes=len(audio), error=failure)
            return err(failure)
        if not audio:
            return err(
                ValidationError(
                    "cannot transcribe an empty audio payload", context={"provider": self.name}
                )
            )
        await self._record(is_success=True, request_bytes=len(audio))
        return ok(
            Transcript(
                text=self._heard(audio),
                language=language,
                confidence=self._confidence,
            )
        )

    async def health(self) -> Result[ProviderHealth]:
        await self._usage.record(
            _fake_usage(operation=VendorOperation.HEALTH, provider=self.name, is_success=True)
        )
        return ok(ProviderHealth(name=self.name, state=HealthState.HEALTHY, as_of=self._clock()))

    # -- internals ----------------------------------------------------------
    async def _record(
        self,
        *,
        is_success: bool,
        request_bytes: int,
        error: HbdError | None = None,
    ) -> None:
        await self._usage.record(
            _fake_usage(
                operation=VendorOperation.TRANSCRIPTION,
                provider=self.name,
                is_success=is_success,
                error=error,
                request_bytes=request_bytes,
            )
        )

    def _heard(self, audio: bytes) -> str:
        """A scripted line wins; otherwise decode our own render; otherwise hear nothing."""
        if self._queue:
            return self._queue.pop(0)
        if self._transcript is not None:
            return self._transcript
        decoded = decode_fake_audio(audio)
        return decoded.text if decoded is not None else ""


def _substitute_name(request: SpeechRequest) -> str:
    """Mirror the real adapters: the submitted orthography replaces the display name."""
    return apply_name(request.text, name_submitted=request.name_submitted).text
