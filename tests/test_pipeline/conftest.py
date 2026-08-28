"""Fakes for the whole pipeline, wired into one ``Studio``.

Every fake satisfies a frozen Protocol structurally and returns ``Result`` — none of them
raise, exactly like the real adapters must not. Nothing here touches the network, Redis,
Postgres or ffmpeg.

The interesting trick is how the name loop is faked end to end: the music fake encodes the
*submitted* orthography into the audio bytes, and the STT fake decodes it and looks it up
in ``pronunciations``. That makes "this spelling is heard as that sound" a one-line test
fixture, which is the only way to drive the re-roll path deterministically.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Callable, Sequence
from datetime import datetime, timedelta
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any
from uuid import UUID

import pytest
from pydantic import BaseModel

from hbd.config import Settings
from hbd.contracts import (
    AudioProbe,
    Brief,
    CostSource,
    Err,
    HealthState,
    Kit,
    Language,
    LlmRequest,
    LyricDraft,
    Order,
    OrderState,
    PaymentAuthorization,
    ProviderHealth,
    RenderedAudio,
    Result,
    SpeechRequest,
    SpokenScript,
    StoredObject,
    Transcript,
    VoiceDescriptor,
    VoiceGender,
    err,
    ok,
)
from hbd.errors import (
    HbdError,
    PipelineError,
    ProviderUnavailableError,
    StorageError,
)
from hbd.pipeline.content import LlmContentWriter
from hbd.pipeline.events import ProgressEvent
from hbd.pipeline.orchestrator import KitPipeline
from hbd.pipeline.ports import ContentWriter
from tests.conftest import FIXED_NOW, make_order

SONG_PREFIX = "song:"
GREETING_PREFIX = "greeting:"
#: Marks the name a name-chunk carried, so the STT fake can find it in the "audio".
_NAME_QUOTE = re.compile(r'The recipient is named "([^"]+)"')
_PERSONA_LINE = re.compile(r'- persona_id "([^"]+)"')


# ---------------------------------------------------------------------------
# Name similarity (stands in for the name subsystem)
# ---------------------------------------------------------------------------
_MODIFIERS = str.maketrans(dict.fromkeys("\u02bb\u02bc\u2018\u2019'`\u00b4-", ""))


def fold_name(value: str) -> str:
    return value.translate(_MODIFIERS).casefold().replace(" ", "")


def fake_similarity(heard: str, expected: str) -> float:
    return SequenceMatcher(None, fold_name(heard), fold_name(expected)).ratio()


# ---------------------------------------------------------------------------
# Providers
# ---------------------------------------------------------------------------
def _health(name: str) -> Result[ProviderHealth]:
    return ok(ProviderHealth(name=name, state=HealthState.HEALTHY, as_of=FIXED_NOW))


class FakeMusicProvider:
    """Encodes the submitted name into the audio bytes so STT can 'hear' it."""

    name = "fake-music"

    def __init__(self) -> None:
        self.compose_calls: list[str] = []
        self.inpaint_calls: list[tuple[str, int]] = []
        self.idempotency_keys: list[str] = []
        self.failures: list[HbdError | None] = []
        self.remote_id: str | None = "song-remote-1"
        self.cost_usd = 0.30

    def _next_failure(self) -> HbdError | None:
        """Pop the scripted outcome for this call. A ``None`` entry means 'succeed'."""
        return self.failures.pop(0) if self.failures else None

    def _audio(self, name_text: str) -> RenderedAudio:
        return RenderedAudio(
            data=f"{SONG_PREFIX}{name_text}".encode(),
            mime="audio/mpeg",
            duration_s=120.0,
            remote_id=self.remote_id,
            cost_usd=self.cost_usd,
            cost_source=CostSource.DERIVED,
        )

    @staticmethod
    def _name_text(plan: Any) -> str:
        index = plan.name_chunk_index
        return plan.chunks[index].text if index is not None else ""

    async def compose(
        self, plan: Any, *, idempotency_key: str, timeout_s: float
    ) -> Result[RenderedAudio]:
        self.idempotency_keys.append(idempotency_key)
        failure = self._next_failure()
        if failure is not None:
            return err(failure)
        name_text = self._name_text(plan)
        self.compose_calls.append(name_text)
        return ok(self._audio(name_text))

    async def inpaint(
        self,
        plan: Any,
        *,
        source_song_id: str,
        chunk_index: int,
        idempotency_key: str,
        timeout_s: float,
    ) -> Result[RenderedAudio]:
        self.idempotency_keys.append(idempotency_key)
        failure = self._next_failure()
        if failure is not None:
            return err(failure)
        name_text = plan.chunks[chunk_index].text
        self.inpaint_calls.append((source_song_id, chunk_index))
        return ok(self._audio(name_text))

    async def health(self) -> Result[ProviderHealth]:
        return _health(self.name)


class FakeSttProvider:
    """Decodes the fake audio and reports what ``pronunciations`` says it sounds like."""

    name = "fake-stt"

    def __init__(self) -> None:
        self.pronunciations: dict[str, str] = {}
        self.failures: list[HbdError] = []
        self.calls: list[str] = []

    async def transcribe(
        self,
        audio: bytes,
        *,
        mime: str,
        language: Language,
        keyterms: Sequence[str] = (),
        timeout_s: float,
    ) -> Result[Transcript]:
        if self.failures:
            return err(self.failures.pop(0))
        payload = audio.decode("utf-8", errors="ignore").removeprefix(SONG_PREFIX)
        submitted = payload.splitlines()[-1] if payload else ""
        self.calls.append(submitted)
        heard = self.pronunciations.get(submitted, submitted)
        return ok(
            Transcript(
                text=f"bugun quyosh porlaydi {heard} yashasin",
                language=language,
                confidence=0.9,
            )
        )

    async def health(self) -> Result[ProviderHealth]:
        return _health(self.name)


class FakeTtsProvider:
    name = "fake-tts"

    def __init__(self) -> None:
        self.catalogue: tuple[VoiceDescriptor, ...] = _default_voices()
        self.failing_personas: set[str] = set()
        self.voices_failure: HbdError | None = None
        self.calls: list[SpeechRequest] = []
        self.idempotency_keys: list[str] = []

    async def synthesize(
        self, request: SpeechRequest, *, idempotency_key: str, timeout_s: float
    ) -> Result[RenderedAudio]:
        self.idempotency_keys.append(idempotency_key)
        self.calls.append(request)
        if request.persona_id in self.failing_personas:
            return err(
                ProviderUnavailableError("fake tts is down for this persona", provider=self.name)
            )
        payload = f"{GREETING_PREFIX}{request.persona_id}:{request.name_submitted}"
        return ok(
            RenderedAudio(
                data=payload.encode(),
                mime="audio/mpeg",
                duration_s=30.0,
                cost_usd=0.02,
                cost_source=CostSource.ESTIMATED,
            )
        )

    async def voices(self) -> Result[tuple[VoiceDescriptor, ...]]:
        if self.voices_failure is not None:
            return err(self.voices_failure)
        return ok(self.catalogue)

    async def health(self) -> Result[ProviderHealth]:
        return _health(self.name)


def _default_voices() -> tuple[VoiceDescriptor, ...]:
    genders = (
        VoiceGender.FEMALE,
        VoiceGender.MALE,
        VoiceGender.FEMALE,
        VoiceGender.MALE,
    )
    return tuple(
        VoiceDescriptor(persona_id=f"persona-{index + 1}", language=Language.UZ_LATN, gender=gender)
        for index, gender in enumerate(genders)
    )


class FakeLlmProvider:
    """Answers from the prompt itself, so a test never hand-writes a lyric payload."""

    name = "fake-llm"

    def __init__(self) -> None:
        self.failures: dict[str, list[HbdError]] = {}
        self.overrides: dict[str, list[BaseModel]] = {}
        self.requests: list[LlmRequest] = []

    def fail_next(self, model_name: str, error: HbdError) -> None:
        self.failures.setdefault(model_name, []).append(error)

    def respond_with(self, model_name: str, payload: BaseModel) -> None:
        self.overrides.setdefault(model_name, []).append(payload)

    async def generate_json[M: BaseModel](
        self, request: LlmRequest, response_model: type[M], *, timeout_s: float
    ) -> Result[M]:
        self.requests.append(request)
        key = response_model.__name__
        queued = self.failures.get(key)
        if queued:
            return err(queued.pop(0))
        override = self.overrides.get(key)
        if override:
            return ok(response_model.model_validate(override.pop(0).model_dump()))
        return ok(response_model.model_validate(_synthesise(key, request)))

    async def health(self) -> Result[ProviderHealth]:
        return _health(self.name)


def _synthesise(model_name: str, request: LlmRequest) -> dict[str, Any]:
    prompt = request.user_prompt
    name_match = _NAME_QUOTE.search(prompt)
    name = name_match.group(1) if name_match else "Someone"
    if model_name == "ModerationPayload":
        return {"is_allowed": "bomb" not in prompt.casefold(), "reason": ""}
    if model_name == "LyricsPayload":
        return {
            "title": "Tugʻilgan kun",
            "sections": [
                {"label": "verse-1", "lines": ["Bugun quyosh boshqacha porlaydi"]},
                {"label": "hook", "lines": [name], "is_name_hook": True},
                {"label": "chorus", "lines": ["Yillar oʻtsa ham qoʻshigʻing yangraydi"]},
                {"label": "verse-2", "lines": ["Doʻstlaring yoningda kulib turibdi"]},
            ],
        }
    if model_name == "GreetingsPayload":
        personas = _PERSONA_LINE.findall(prompt)
        return {
            "greetings": [
                {"persona_id": persona, "text": f"Assalomu alaykum {name}, bayram muborak!"}
                for persona in personas
            ]
        }
    raise AssertionError(f"the fake LLM has no answer for {model_name}")


class SpyContentWriter:
    """The real writer, plus a record of what it was actually asked to write.

    A lyric the customer approved and a lyric written just now are the same type, so the
    short circuit in ``KitPipeline._lyrics_for`` is invisible from the outcome alone —
    a kit comes back either way. Counting the calls is the only honest proof that the
    writer was never asked. It delegates rather than replaces because a run still has to
    finish: the greetings must be written for the pipeline to reach a kit at all.
    """

    def __init__(self, inner: ContentWriter) -> None:
        self._inner = inner
        self.lyric_briefs: list[Brief] = []
        self.script_briefs: list[Brief] = []

    async def write_lyrics(self, brief: Brief) -> Result[LyricDraft]:
        self.lyric_briefs.append(brief)
        return await self._inner.write_lyrics(brief)

    async def write_scripts(
        self,
        brief: Brief,
        lyrics: LyricDraft,
        *,
        voices: tuple[VoiceDescriptor, ...],
        name_submitted: str,
        target_duration_s: float,
    ) -> Result[tuple[SpokenScript, ...]]:
        self.script_briefs.append(brief)
        return await self._inner.write_scripts(
            brief,
            lyrics,
            voices=voices,
            name_submitted=name_submitted,
            target_duration_s=target_duration_s,
        )


class FakePaymentProvider:
    name = "noop-fake"

    def __init__(self) -> None:
        self.is_authorized = True
        self.calls: list[UUID] = []
        #: What the pipeline actually asked to be charged, so a test can assert it came
        #: from configuration rather than from a constant baked into the orchestrator.
        self.charges: list[tuple[int, str]] = []

    async def authorize(
        self, *, order_id: UUID, amount_minor: int, currency: str
    ) -> Result[PaymentAuthorization]:
        self.calls.append(order_id)
        self.charges.append((amount_minor, currency))
        return ok(
            PaymentAuthorization(
                order_id=order_id,
                provider=self.name,
                reference=f"noop-{order_id}",
                amount_minor=amount_minor,
                currency=currency,
                is_authorized=self.is_authorized,
            )
        )


class FakeAudioPostProcessor:
    """Copies bytes around with a marker suffix. Stands in for ffmpeg."""

    def __init__(self) -> None:
        self.should_fail_normalize = False
        self.should_fail_voice_note = False
        self.should_fail_probe = False
        self.normalized: list[Path] = []
        self.voice_notes: list[Path] = []

    async def probe(self, source: Path) -> Result[AudioProbe]:
        if self.should_fail_probe:
            return err(StorageError("fake probe refused"))
        return ok(
            AudioProbe(
                duration_s=30.0 if source.suffix == ".ogg" else 120.0,
                loudness_lufs=-14.0,
                sample_rate_hz=48_000,
                channels=1,
            )
        )

    async def normalize_loudness(
        self, source: Path, *, destination: Path, target_lufs: float
    ) -> Result[Path]:
        if self.should_fail_normalize:
            return err(StorageError("fake loudnorm refused"))
        destination.write_bytes(source.read_bytes() + b"|norm")
        self.normalized.append(destination)
        return ok(destination)

    async def to_voice_note(self, source: Path, *, destination: Path) -> Result[Path]:
        if self.should_fail_voice_note:
            return err(StorageError("fake opus transcode refused"))
        destination.write_bytes(source.read_bytes() + b"|opus")
        self.voice_notes.append(destination)
        return ok(destination)


class FakeStorage:
    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}
        self.should_fail = False

    async def put(self, key: str, data: bytes, *, content_type: str) -> Result[StoredObject]:
        if self.should_fail:
            return err(StorageError("fake storage refused a put"))
        self.objects[key] = data
        return ok(
            StoredObject(
                key=key,
                size_bytes=len(data),
                sha256=hashlib.sha256(data).hexdigest(),
                content_type=content_type,
            )
        )

    async def get(self, key: str) -> Result[bytes]:
        if key not in self.objects:
            return err(StorageError("no such object"))
        return ok(self.objects[key])

    async def signed_url(self, key: str, *, ttl_s: int) -> Result[str]:
        return ok(f"https://fake.local/{key}?ttl={ttl_s}")

    async def delete(self, key: str) -> Result[None]:
        self.objects.pop(key, None)
        return ok(None)


class FakeKitRepository:
    def __init__(self) -> None:
        self.orders: dict[UUID, Order] = {}
        self.kits: dict[UUID, Kit] = {}
        self.states: list[OrderState] = []
        self.save_failures: list[HbdError] = []

    async def create_order(self, order: Order) -> Result[Order]:
        self.orders[order.id] = order
        return ok(order)

    async def get_order(self, order_id: UUID) -> Result[Order]:
        found = self.orders.get(order_id)
        if found is None:
            return err(PipelineError("no such order"))
        return ok(found)

    async def set_order_state(
        self, order_id: UUID, state: OrderState, *, now: datetime
    ) -> Result[Order]:
        found = self.orders.get(order_id)
        if found is None:
            return err(PipelineError("no such order"))
        updated = found.with_state(state, now=now)
        self.orders[order_id] = updated
        self.states.append(state)
        return ok(updated)

    async def save_kit(self, kit: Kit) -> Result[Kit]:
        if self.save_failures:
            return err(self.save_failures.pop(0))
        self.kits[kit.order_id] = kit
        return ok(kit)

    async def get_kit(self, order_id: UUID) -> Result[Kit]:
        found = self.kits.get(order_id)
        if found is None:
            return err(PipelineError("no kit yet"))
        return ok(found)

    async def list_orders_for_user(
        self, telegram_user_id: int, *, limit: int
    ) -> Result[tuple[Order, ...]]:
        matching = tuple(
            order for order in self.orders.values() if order.telegram_user_id == telegram_user_id
        )
        return ok(matching[:limit])


class RecordingSink:
    def __init__(self) -> None:
        self.events: list[ProgressEvent] = []
        self.should_raise = False

    async def emit(self, event: ProgressEvent) -> None:
        if self.should_raise:
            raise RuntimeError("the sink is on fire")
        self.events.append(event)

    def stages(self) -> list[tuple[str, str]]:
        return [(event.stage.value, event.status.value) for event in self.events]


# ---------------------------------------------------------------------------
# Clock, sleeper, studio
# ---------------------------------------------------------------------------
def ticking_clock(step_ms: int = 10) -> Callable[[], datetime]:
    """A clock that advances on every read, so stage durations are never zero."""
    ticks = iter(range(1_000_000))
    return lambda: FIXED_NOW + timedelta(milliseconds=step_ms * next(ticks))


async def no_sleep(seconds: float) -> None:
    return None


class Studio:
    """Every fake plus the pipeline they are wired into."""

    def __init__(self, settings: Settings, workspace: Path) -> None:
        self.settings = settings
        self.music = FakeMusicProvider()
        self.tts = FakeTtsProvider()
        self.llm = FakeLlmProvider()
        self.stt = FakeSttProvider()
        self.payment = FakePaymentProvider()
        self.post = FakeAudioPostProcessor()
        self.storage = FakeStorage()
        self.repository = FakeKitRepository()
        self.sink = RecordingSink()
        self.workspace = workspace
        self.clock = ticking_clock()

    def pipeline(self, **overrides: Any) -> KitPipeline:
        kwargs: dict[str, Any] = {
            "settings": self.settings,
            "music": self.music,
            "tts": self.tts,
            "llm": self.llm,
            "stt": self.stt,
            "payment": self.payment,
            "post": self.post,
            "storage": self.storage,
            "repository": self.repository,
            "similarity": fake_similarity,
            "workspace_root": self.workspace,
            "sink": self.sink,
            "clock": self.clock,
            "sleeper": no_sleep,
        }
        return KitPipeline(**{**kwargs, **overrides})

    def content_spy(self) -> SpyContentWriter:
        """A writer that records its calls, wrapped around the real one over the fake LLM.

        Pass it to ``pipeline(content_writer=...)`` when a test needs to know *whether*
        the words were written, not just what they say.
        """
        return SpyContentWriter(LlmContentWriter(self.llm, self.settings))

    def enrol(self, order: Order) -> Order:
        self.repository.orders[order.id] = order
        return order


@pytest.fixture
def pipeline_settings(settings: Settings) -> Settings:
    """Defaults tuned for fast, deterministic tests."""
    return settings.model_copy(
        update={
            "provider_max_attempts": 2,
            "provider_backoff_base_s": 0.01,
            "llm_parse_max_attempts": 2,
            "greetings_per_kit": 3,
        }
    )


@pytest.fixture
def studio(pipeline_settings: Settings, tmp_path: Path) -> Studio:
    return Studio(pipeline_settings, tmp_path / "workspace")


@pytest.fixture
def ready_order(studio: Studio) -> Order:
    return studio.enrol(make_order())


@pytest.fixture
def brief(ready_order: Order) -> Brief:
    return ready_order.brief


def failure_of(result: Result[Any]) -> HbdError:
    """Assert a result failed and hand back the error."""
    assert isinstance(result, Err), f"expected a failure, got {result!r}"
    return result.error


def value_of[T](result: Result[T]) -> T:
    assert not isinstance(result, Err), f"expected success, got {result.error!r}"
    return result.value


__all__ = [
    "Studio",
    "fake_similarity",
    "fold_name",
    "failure_of",
    "value_of",
    "no_sleep",
    "ticking_clock",
    "RecordingSink",
    "FakeMusicProvider",
    "FakeSttProvider",
    "FakeTtsProvider",
    "FakeLlmProvider",
    "FakeAudioPostProcessor",
    "FakeStorage",
    "FakeKitRepository",
    "FakePaymentProvider",
    "SpyContentWriter",
]
