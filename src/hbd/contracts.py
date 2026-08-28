"""The central contract file. Frozen models + Protocol interfaces.

Rules that hold for everything below and are not restated per item:

* Every model is frozen. Collections are tuples. Nothing mutates an input.
* Every Protocol method is ``async`` and returns ``Result[...]``. **No protocol method
  raises as part of its contract.** An adapter that lets an exception escape is a bug.
* Nothing here imports a vendor SDK, a vendor hostname or a vendor field name.

The one distinction that carries the whole product: a name has a **display** form and a
**submitted** form, and they are different values that must never be conflated.
``RecipientName.display`` is what a human reads (perfect U+02BB). ``NameCandidate.text``
is what we post to a vendor; nobody ever sees it.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from enum import StrEnum
from pathlib import Path
from typing import Final, Protocol, runtime_checkable
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from typing_extensions import TypeIs

from hbd.errors import HbdError

__all__ = [
    # Enums
    "Language",
    "Script",
    "Occasion",
    "Genre",
    "VoiceGender",
    "OrderState",
    "AssetKind",
    "NameStrategy",
    "ContextAdherence",
    "ConditionStrength",
    "AudioRange",
    "MIN_AUDIO_RANGE_MS",
    "SongReference",
    "CostSource",
    "HealthState",
    # Result
    "Ok",
    "Err",
    "Result",
    "ok",
    "err",
    "is_ok",
    "is_err",
    "unwrap_or",
    # Name subsystem
    "NameCandidate",
    "RecipientName",
    "NameVerdict",
    # Brief and text
    "Brief",
    "LyricSection",
    "LyricDraft",
    "SpokenScript",
    # Music
    "Chunk",
    "CompositionPlan",
    # Provider value objects
    "RenderedAudio",
    "SpeechRequest",
    "VoiceDescriptor",
    "LlmRequest",
    "Transcript",
    "ProviderHealth",
    "AudioProbe",
    "StoredObject",
    "PaymentAuthorization",
    # Deliverables
    "GeneratedAsset",
    "Kit",
    "Order",
    # Protocols
    "MusicProvider",
    "TtsProvider",
    "LlmProvider",
    "SttProvider",
    "PaymentProvider",
    "AudioPostProcessor",
    "Storage",
    "KitRepository",
    # Vendor hard limits
    "MIN_CHUNK_DURATION_MS",
    "MAX_CHUNK_DURATION_MS",
    "MIN_SONG_DURATION_MS",
    "MAX_SONG_DURATION_MS",
    "MAX_CHUNKS_PER_PLAN",
    "MAX_RECIPIENT_NAME_CHARS",
    "MAX_CANDIDATE_CHARS",
]

# ---------------------------------------------------------------------------
# Vendor hard limits. These are validation bounds published by the vendor, not
# tunables — tunables live in hbd.config.
# ---------------------------------------------------------------------------
MIN_CHUNK_DURATION_MS: Final[int] = 3_000
MAX_CHUNK_DURATION_MS: Final[int] = 120_000
MIN_SONG_DURATION_MS: Final[int] = 3_000
MAX_SONG_DURATION_MS: Final[int] = 600_000
MAX_CHUNKS_PER_PLAN: Final[int] = 30
#: Shortest slice of a stored song the vendor will replay in an inpaint plan.
MIN_AUDIO_RANGE_MS: Final[int] = 50
MAX_RECIPIENT_NAME_CHARS: Final[int] = 40
#: A derived orthography can be longer than the typed name — hyphenation inserts
#: separators and a phonetic respelling expands digraphs — so candidates get their
#: own, looser bound. Binding this to MAX_RECIPIENT_NAME_CHARS rejects valid candidates
#: for long names.
MAX_CANDIDATE_CHARS: Final[int] = 80


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------
class Language(StrEnum):
    """Interface language and output language are chosen INDEPENDENTLY."""

    UZ_LATN = "uz_latn"
    UZ_CYRL = "uz_cyrl"
    RU = "ru"
    EN = "en"

    @property
    def script(self) -> Script:
        return Script.CYRILLIC if self in (Language.UZ_CYRL, Language.RU) else Script.LATIN


class Script(StrEnum):
    LATIN = "latin"
    CYRILLIC = "cyrillic"


class Occasion(StrEnum):
    BIRTHDAY = "birthday"
    ANNIVERSARY = "anniversary"
    CUSTOM = "custom"


class Genre(StrEnum):
    POP = "pop"
    RETRO_ESTRADA = "retro_estrada"
    HIP_HOP = "hip_hop"
    ROCK = "rock"
    ACOUSTIC_BALLAD = "acoustic_ballad"
    DANCE_ELECTRONIC = "dance_electronic"
    UZBEK_POP = "uzbek_pop"
    UZBEK_FOLK = "uzbek_folk"
    SHASHMAQOM = "shashmaqom"
    JAZZ_LOUNGE = "jazz_lounge"


class VoiceGender(StrEnum):
    FEMALE = "female"
    MALE = "male"
    DUET = "duet"
    ANY = "any"


class OrderState(StrEnum):
    """Forward-only. ``FAILED`` and ``DELIVERED`` are terminal."""

    DRAFT = "draft"
    BRIEF_READY = "brief_ready"
    LYRICS_READY = "lyrics_ready"
    AUTHORIZED = "authorized"
    GENERATING = "generating"
    DELIVERED = "delivered"
    FAILED = "failed"
    CANCELLED = "cancelled"


class AssetKind(StrEnum):
    SONG = "song"
    GREETING = "greeting"
    LYRIC_SHEET = "lyric_sheet"
    COVER = "cover"


class NameStrategy(StrEnum):
    """How one candidate orthography was derived from the typed name.

    The ORDER in which these are tried is configuration (``Settings.name_candidate_order``),
    never code. A bake-off reorders the list; no module changes.
    """

    CANONICAL = "canonical"  # U+02BB preserved: Gulnoraʼ style, oʻ / gʻ intact
    STRIPPED = "stripped"  # modifier letters removed entirely: Gulnora, Ozod
    ASCII = "ascii"  # U+0027 apostrophe: O'zod
    CYRILLIC = "cyrillic"  # transliterated to Cyrillic
    HYPHENATED = "hyphenated"  # syllable boundaries: Gul-no-ra
    PHONETIC = "phonetic"  # respelling aimed at the vendor's grapheme model


class ConditionStrength(StrEnum):
    """How strongly a generation chunk is conditioned on referenced stored audio.

    A four-value enum at the vendor, not a 0..1 float.
    """

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    XHIGH = "xhigh"


class ContextAdherence(StrEnum):
    """How literally Eleven Music should follow a chunk's text.

    The vendor takes a three-value enum here, NOT a 0..1 float — a float earns a 422 that
    rejects every chunk in the plan. Learned live; see the payload test that pins it.
    """

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class CostSource(StrEnum):
    VENDOR_REPORTED = "vendor_reported"
    DERIVED = "derived"
    ESTIMATED = "estimated"


class HealthState(StrEnum):
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNAVAILABLE = "unavailable"
    UNKNOWN = "unknown"


# ---------------------------------------------------------------------------
# Result — the never-throw boundary type
# ---------------------------------------------------------------------------
class _Frozen(BaseModel):
    """Base for every domain model: frozen, strict about unknown keys."""

    model_config = ConfigDict(frozen=True, extra="forbid", str_strip_whitespace=False)


class Ok[T](BaseModel):
    """A successful outcome. ``value`` may be ``None`` for void operations."""

    model_config = ConfigDict(frozen=True, extra="forbid", arbitrary_types_allowed=True)

    value: T


class Err(BaseModel):
    """A failed outcome carrying a typed error. Never an exception in flight."""

    model_config = ConfigDict(frozen=True, extra="forbid", arbitrary_types_allowed=True)

    error: HbdError

    @property
    def is_retryable(self) -> bool:
        return self.error.is_retryable


type Result[T] = Ok[T] | Err


def ok[T](value: T) -> Ok[T]:
    return Ok(value=value)


def err(error: HbdError) -> Err:
    return Err(error=error)


def is_ok[T](result: Result[T]) -> TypeIs[Ok[T]]:
    """True when ``result`` succeeded, narrowing BOTH branches for the type checker.

    ``TypeIs`` (PEP 742), not ``TypeGuard``: ``TypeGuard`` narrows only the positive
    branch, so the idiomatic early return ``if is_err(r): return r`` left ``r`` as the
    full union afterwards and every ``r.value`` failed ``mypy --strict``. Six modules
    independently worked around that with ``isinstance(r, Err)``; this is the fix.
    """
    return isinstance(result, Ok)


def is_err[T](result: Result[T]) -> TypeIs[Err]:
    """True when ``result`` failed. Narrows both branches — see :func:`is_ok`."""
    return isinstance(result, Err)


def unwrap_or[T](result: Result[T], default: T) -> T:
    """Read a result without branching. Never raises."""
    return result.value if isinstance(result, Ok) else default


# ---------------------------------------------------------------------------
# The name subsystem
# ---------------------------------------------------------------------------
class NameCandidate(_Frozen):
    """One orthography of the recipient's name as SUBMITTED to a vendor.

    Never rendered to a user. ``rank`` 0 is tried first; ties are impossible because
    the builder assigns ranks from the configured strategy order.
    """

    text: str = Field(min_length=1, max_length=MAX_CANDIDATE_CHARS)
    strategy: NameStrategy
    rank: int = Field(ge=0)


class RecipientName(_Frozen):
    """The typed name, resolved into everything downstream needs.

    ``raw`` is byte-preserved user input. ``display`` is the canonicalised form with
    U+02BB MODIFIER LETTER TURNED COMMA, and it is the ONLY form that ever appears in
    message copy or on the lyric sheet. ``lookup_key`` is the case-folded, mark-stripped,
    script-unified key used for dictionary and cache hits.
    """

    raw: str = Field(min_length=1, max_length=MAX_RECIPIENT_NAME_CHARS)
    display: str = Field(min_length=1, max_length=MAX_RECIPIENT_NAME_CHARS)
    lookup_key: str = Field(min_length=1)
    script: Script
    language: Language
    candidates: tuple[NameCandidate, ...] = Field(min_length=1)

    @field_validator("candidates")
    @classmethod
    def _ranks_must_be_dense_and_ordered(
        cls, value: tuple[NameCandidate, ...]
    ) -> tuple[NameCandidate, ...]:
        expected = tuple(range(len(value)))
        actual = tuple(candidate.rank for candidate in value)
        if actual != expected:
            raise ValueError(f"candidate ranks must be 0..n-1 in order, got {actual}")
        return value

    def candidate_at(self, rank: int) -> NameCandidate | None:
        """Return the candidate at ``rank``, or ``None`` once the list is exhausted."""
        if 0 <= rank < len(self.candidates):
            return self.candidates[rank]
        return None


class NameVerdict(_Frozen):
    """Outcome of closing the loop acoustically: STT of the rendered name chunk.

    ``is_match`` is computed against the intended name AFTER normalisation, so a
    transcript in a different script or with a different apostrophe still matches.
    A non-match silently re-rolls that chunk with the next candidate; the customer
    never hears the rejected take.
    """

    candidate: NameCandidate
    transcript: str
    is_match: bool
    confidence: float = Field(ge=0.0, le=1.0)
    attempt: int = Field(ge=0)


# ---------------------------------------------------------------------------
# Brief and generated text
# ---------------------------------------------------------------------------
class Brief(_Frozen):
    """Everything the user told us. Four structured answers plus a free-text note."""

    recipient: RecipientName
    occasion: Occasion
    genre: Genre
    vocal_gender: VoiceGender
    note: str = Field(default="", max_length=600)
    ui_language: Language
    output_language: Language


class LyricSection(_Frozen):
    """One structural block. ``is_name_hook`` marks the section that carries the name.

    Exactly the sections flagged here become their own composition chunk, so a bad
    pronunciation costs one chunk to re-render, not the whole track.
    """

    label: str = Field(min_length=1, max_length=40)
    lines: tuple[str, ...] = Field(min_length=1)
    is_name_hook: bool = False


class LyricDraft(_Frozen):
    """A complete lyric. ``name_display`` is what the lyric SHEET shows."""

    title: str = Field(min_length=1, max_length=120)
    language: Language
    sections: tuple[LyricSection, ...] = Field(min_length=1)
    name_display: str = Field(min_length=1)

    @property
    def name_hook_sections(self) -> tuple[LyricSection, ...]:
        return tuple(section for section in self.sections if section.is_name_hook)

    def as_plain_text(self) -> str:
        blocks = ("\n".join(section.lines) for section in self.sections)
        return "\n\n".join(blocks)


class SpokenScript(_Frozen):
    """One character greeting, before TTS.

    ``text`` uses the DISPLAY name. ``name_submitted`` is the orthography actually fed to
    the engine; when a TTS provider supports phoneme markup the adapter compiles it,
    otherwise it substitutes this string for the display form.
    """

    persona_id: str = Field(min_length=1, max_length=64)
    language: Language
    text: str = Field(min_length=1, max_length=2_000)
    name_submitted: str = Field(min_length=1)
    target_duration_s: float = Field(gt=0)


# ---------------------------------------------------------------------------
# Music composition (vendor-neutral)
# ---------------------------------------------------------------------------
class AudioRange(_Frozen):
    """A half-open slice of a stored song, in milliseconds.

    The vendor rejects a range shorter than :data:`MIN_AUDIO_RANGE_MS`, so a caller that
    would emit a zero-length slice must omit the reference entirely instead.
    """

    start_ms: int = Field(ge=0)
    end_ms: int = Field(ge=0)

    @model_validator(mode="after")
    def _range_is_long_enough(self) -> AudioRange:
        span = self.end_ms - self.start_ms
        if span < MIN_AUDIO_RANGE_MS:
            raise ValueError(
                f"an audio range must span at least {MIN_AUDIO_RANGE_MS}ms, got {span}ms"
            )
        return self


class SongReference(_Frozen):
    """A named slice of a stored song: what inpainting replays instead of regenerating."""

    song_id: str = Field(min_length=1)
    range: AudioRange


class Chunk(_Frozen):
    """One composition-plan chunk.

    ``is_name_chunk`` is the load-bearing flag: exactly one short chunk holds the name so
    it can be re-rendered alone via inpainting.
    """

    text: str
    duration_ms: int = Field(ge=MIN_CHUNK_DURATION_MS, le=MAX_CHUNK_DURATION_MS)
    positive_styles: tuple[str, ...] = ()
    negative_styles: tuple[str, ...] = ()
    context_adherence: ContextAdherence | None = None
    conditioning_ref: SongReference | None = None
    condition_strength: ConditionStrength | None = None
    is_name_chunk: bool = False


class CompositionPlan(_Frozen):
    """An ordered chunk list plus render intent. No vendor field names appear here."""

    chunks: tuple[Chunk, ...] = Field(min_length=1, max_length=MAX_CHUNKS_PER_PLAN)
    language: Language
    seed: int | None = None
    is_instrumental: bool = False
    should_store_for_inpainting: bool = True
    source_song_id: str | None = Field(
        default=None,
        description="Set when re-rendering: the stored song this plan conditions on.",
    )

    @property
    def total_duration_ms(self) -> int:
        return sum(chunk.duration_ms for chunk in self.chunks)

    @property
    def name_chunk_index(self) -> int | None:
        for index, chunk in enumerate(self.chunks):
            if chunk.is_name_chunk:
                return index
        return None

    @field_validator("chunks")
    @classmethod
    def _at_most_one_name_chunk(cls, value: tuple[Chunk, ...]) -> tuple[Chunk, ...]:
        count = sum(1 for chunk in value if chunk.is_name_chunk)
        if count > 1:
            raise ValueError(f"exactly one chunk may carry the name, found {count}")
        return value

    @field_validator("chunks")
    @classmethod
    def _total_within_vendor_bounds(cls, value: tuple[Chunk, ...]) -> tuple[Chunk, ...]:
        total = sum(chunk.duration_ms for chunk in value)
        if not MIN_SONG_DURATION_MS <= total <= MAX_SONG_DURATION_MS:
            raise ValueError(
                f"total duration {total}ms outside [{MIN_SONG_DURATION_MS}, {MAX_SONG_DURATION_MS}]"
            )
        return value

    def with_chunk_replaced(self, index: int, chunk: Chunk) -> CompositionPlan:
        """Return a NEW plan with one chunk swapped. Used by the re-roll loop."""
        if not 0 <= index < len(self.chunks):
            raise IndexError(f"chunk index {index} out of range for {len(self.chunks)} chunks")
        replaced = (*self.chunks[:index], chunk, *self.chunks[index + 1 :])
        return CompositionPlan(
            chunks=replaced,
            language=self.language,
            seed=self.seed,
            is_instrumental=self.is_instrumental,
            should_store_for_inpainting=self.should_store_for_inpainting,
            source_song_id=self.source_song_id,
        )


# ---------------------------------------------------------------------------
# Provider value objects
# ---------------------------------------------------------------------------
class RenderedAudio(_Frozen):
    """Raw audio as a vendor returned it, before post-processing."""

    data: bytes
    mime: str = Field(min_length=1)
    duration_s: float = Field(gt=0)
    remote_id: str | None = Field(
        default=None, description="Vendor handle for later inpainting, when offered."
    )
    cost_usd: float = Field(ge=0.0)
    cost_source: CostSource


class VoiceDescriptor(_Frozen):
    """Our stable persona id mapped to a vendor voice. Vendor ids live only in adapters."""

    persona_id: str = Field(min_length=1)
    language: Language
    gender: VoiceGender
    supports_phoneme_override: bool = False
    substitute_persona_id: str | None = None


class SpeechRequest(_Frozen):
    """Vendor-neutral TTS request.

    ``name_submitted`` is passed separately from ``text`` so an adapter that supports
    phoneme markup can compile it, and one that does not can substitute it verbatim.
    The caller never formats vendor markup.
    """

    text: str = Field(min_length=1, max_length=2_000)
    persona_id: str = Field(min_length=1)
    language: Language
    name_submitted: str = Field(min_length=1)
    name_ipa: str | None = None
    mood: str | None = None


class LlmRequest(_Frozen):
    """Every LLM call in this system returns JSON. There is no free-text path."""

    system_prompt: str = Field(min_length=1)
    user_prompt: str = Field(min_length=1)
    temperature: float = Field(default=0.7, ge=0.0, le=2.0)
    max_output_tokens: int = Field(default=2_048, gt=0)


class Transcript(_Frozen):
    """STT output. Used to VERIFY a rendered name, not to transcribe user speech."""

    text: str
    language: Language
    confidence: float = Field(ge=0.0, le=1.0)


class ProviderHealth(_Frozen):
    name: str = Field(min_length=1)
    state: HealthState
    as_of: datetime
    balance_remaining_usd: float | None = None
    quota_remaining: int | None = None
    detail: str | None = None


class AudioProbe(_Frozen):
    duration_s: float = Field(gt=0)
    loudness_lufs: float | None = None
    sample_rate_hz: int = Field(gt=0)
    channels: int = Field(gt=0)


class StoredObject(_Frozen):
    key: str = Field(min_length=1)
    size_bytes: int = Field(ge=0)
    sha256: str = Field(min_length=64, max_length=64)
    content_type: str = Field(min_length=1)


class PaymentAuthorization(_Frozen):
    """Out of scope for this build. ``NoopPaymentProvider`` always returns one."""

    order_id: UUID
    provider: str = Field(min_length=1)
    reference: str = Field(min_length=1)
    amount_minor: int = Field(ge=0)
    currency: str = Field(min_length=3, max_length=3)
    is_authorized: bool


# ---------------------------------------------------------------------------
# Deliverables
# ---------------------------------------------------------------------------
class GeneratedAsset(_Frozen):
    """A finished, post-processed file ready to send."""

    kind: AssetKind
    path: Path
    duration_s: float = Field(ge=0)
    mime: str = Field(min_length=1)
    sha256: str = Field(min_length=64, max_length=64)
    name_candidate: NameCandidate | None = Field(
        default=None, description="Which orthography produced this asset. None for text assets."
    )
    loudness_lufs: float | None = None
    persona_id: str | None = None


class Kit(_Frozen):
    """The full deliverable: one song, three greetings, a lyric sheet, an optional cover."""

    order_id: UUID
    song: GeneratedAsset
    greetings: tuple[GeneratedAsset, ...] = Field(min_length=1)
    lyric_sheet: GeneratedAsset
    lyrics: LyricDraft
    cover: GeneratedAsset | None = None
    name_verdicts: tuple[NameVerdict, ...] = ()

    @property
    def all_assets(self) -> tuple[GeneratedAsset, ...]:
        cover = (self.cover,) if self.cover is not None else ()
        return (self.song, *self.greetings, self.lyric_sheet, *cover)


class Order(_Frozen):
    id: UUID
    telegram_user_id: int
    brief: Brief
    state: OrderState
    correlation_id: str = Field(min_length=1)
    created_at: datetime
    updated_at: datetime

    def with_state(self, state: OrderState, *, now: datetime) -> Order:
        """Return a NEW order in the given state. Never mutates."""
        return self.model_copy(update={"state": state, "updated_at": now})


# ---------------------------------------------------------------------------
# Protocols. Every method is async and returns Result. None of them raise.
# ---------------------------------------------------------------------------
@runtime_checkable
class MusicProvider(Protocol):
    """Song generation. One track per order."""

    name: str

    async def compose(
        self,
        plan: CompositionPlan,
        *,
        idempotency_key: str,
        timeout_s: float,
    ) -> Result[RenderedAudio]:
        """Render a full track. ``RenderedAudio.remote_id`` is set when the vendor stored it."""
        ...

    async def inpaint(
        self,
        plan: CompositionPlan,
        *,
        source_song_id: str,
        chunk_index: int,
        idempotency_key: str,
        timeout_s: float,
    ) -> Result[RenderedAudio]:
        """Re-render exactly one chunk of a stored song and return the whole track."""
        ...

    async def health(self) -> Result[ProviderHealth]: ...


@runtime_checkable
class TtsProvider(Protocol):
    """Spoken greetings and the name-preview clip. Synchronous by contract."""

    name: str

    async def synthesize(
        self, request: SpeechRequest, *, idempotency_key: str, timeout_s: float
    ) -> Result[RenderedAudio]: ...

    async def voices(self) -> Result[tuple[VoiceDescriptor, ...]]:
        """Our persona ids for this provider, with their same-language substitutes."""
        ...

    async def health(self) -> Result[ProviderHealth]: ...


@runtime_checkable
class LlmProvider(Protocol):
    """Intake normalisation, lyric writing, name respelling.

    ``generate_json`` MUST request the provider's structured/JSON mode AND still defend
    the parse: strip fences -> parse -> repair -> validate against ``response_model`` ->
    return ``Err(LlmParseError)`` with the raw payload and finish reason in context.
    """

    name: str

    async def generate_json[M: BaseModel](
        self,
        request: LlmRequest,
        response_model: type[M],
        *,
        timeout_s: float,
    ) -> Result[M]: ...

    async def health(self) -> Result[ProviderHealth]: ...


@runtime_checkable
class SttProvider(Protocol):
    """Verification only. We never transcribe user speech with this."""

    name: str

    async def transcribe(
        self,
        audio: bytes,
        *,
        mime: str,
        language: Language,
        keyterms: Sequence[str] = (),
        timeout_s: float,
    ) -> Result[Transcript]: ...

    async def health(self) -> Result[ProviderHealth]: ...


@runtime_checkable
class PaymentProvider(Protocol):
    """Out of scope for this build. Implemented once by ``NoopPaymentProvider``, which
    always authorises, so a real rail drops in without touching a call site.
    """

    name: str

    async def authorize(
        self, *, order_id: UUID, amount_minor: int, currency: str
    ) -> Result[PaymentAuthorization]: ...


@runtime_checkable
class AudioPostProcessor(Protocol):
    """ffmpeg behind a seam so unit tests never need the binary."""

    async def probe(self, source: Path) -> Result[AudioProbe]: ...

    async def normalize_loudness(
        self, source: Path, *, destination: Path, target_lufs: float
    ) -> Result[Path]:
        """Two-pass loudnorm, silence trim, fades. Returns ``destination``."""
        ...

    async def to_voice_note(self, source: Path, *, destination: Path) -> Result[Path]:
        """Transcode to OGG/libopus mono. ``sendVoice`` renders anything else as a file."""
        ...


@runtime_checkable
class Storage(Protocol):
    """Object storage. Keys are unguessable and assigned by the caller."""

    async def put(self, key: str, data: bytes, *, content_type: str) -> Result[StoredObject]: ...

    async def get(self, key: str) -> Result[bytes]: ...

    async def signed_url(self, key: str, *, ttl_s: int) -> Result[str]: ...

    async def delete(self, key: str) -> Result[None]: ...


@runtime_checkable
class KitRepository(Protocol):
    """Persistence for orders and their finished kits."""

    async def create_order(self, order: Order) -> Result[Order]: ...

    async def get_order(self, order_id: UUID) -> Result[Order]: ...

    async def set_order_state(
        self, order_id: UUID, state: OrderState, *, now: datetime
    ) -> Result[Order]: ...

    async def save_kit(self, kit: Kit) -> Result[Kit]: ...

    async def get_kit(self, order_id: UUID) -> Result[Kit]: ...

    async def list_orders_for_user(
        self, telegram_user_id: int, *, limit: int
    ) -> Result[tuple[Order, ...]]: ...
