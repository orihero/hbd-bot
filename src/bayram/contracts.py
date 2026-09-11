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

from collections.abc import AsyncIterator, Sequence
from datetime import datetime
from enum import StrEnum
from pathlib import Path
from typing import Final, Protocol, runtime_checkable
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from typing_extensions import TypeIs

from bayram.errors import BayramError

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
    "Vendor",
    "VendorOperation",
    "UsageTask",
    "BalanceUnit",
    "BalanceEstimateBasis",
    "BotMembershipEvent",
    "BotBlockSource",
    "BroadcastKind",
    "BroadcastState",
    "BroadcastRecipientState",
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
# tunables — tunables live in bayram.config.
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
    """What the song is FOR. Declaration order is the order the wizard draws them in.

    The list is the offer, not a taxonomy: every member has to be a reason somebody
    actually opens this bot with, because the occasion is the first question asked and a
    customer who finds nothing that fits presses ``CUSTOM`` and tells the writer nothing.
    That is why the three-member version was widened — birthday, anniversary and "something
    else" sent everyone who wanted a roast, an apology or a song for a two-year-old down the
    escape hatch, and ``OCCASION_BRIEFS`` turned all of them into "a personal celebration".

    ``CUSTOM`` stays LAST and stays the escape hatch. ``keyboards.OWN_LYRICS_SITS_ABOVE``
    is pinned to it, so a member added after it would silently move the
    "I will write the words myself" button; add new occasions ABOVE it.

    Values are what the database stores, so they are renamed only with a migration —
    ``briefs.occasion`` is a plain ``VARCHAR(32)`` with no CHECK constraint (see
    ``db.base.enum_type``), which is why ADDING a member needs no migration at all.
    """

    BIRTHDAY = "birthday"
    #: A declaration of love or a thank-you said out loud — Bro.Hit's "Признание".
    LOVE = "love"
    #: For somebody having a hard time: encouragement, not celebration.
    SUPPORT = "support"
    #: A good-natured roast. The writer is told to keep it affectionate; the shared rules
    #: in ``pipeline.prompts`` still forbid anything cruel.
    PRANK = "prank"
    #: A calendar holiday (New Year, 8 March, a professional day) rather than a personal one.
    HOLIDAY = "holiday"
    WEDDING = "wedding"
    ANNIVERSARY = "anniversary"
    #: A song for a child, which is a register instruction as much as an occasion.
    KIDS = "kids"
    #: No reason at all, which is a reason. Kept distinct from ``CUSTOM``: this one says
    #: "nothing to celebrate, just sing", while ``CUSTOM`` says "something you have not
    #: listed".
    NO_OCCASION = "no_occasion"
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


class Vendor(StrEnum):
    """Who was billed for one call, at the granularity an invoice arrives at.

    Coarser than the adapter name on purpose. ``vendor_usage.provider`` records which
    adapter made the call (``elevenlabs_music`` vs ``elevenlabs_tts``) and both roll up to
    ``ELEVENLABS`` here, because one invoice arrives from ElevenLabs and an operator
    reconciling it needs the total, not three of them.

    ``OPENAI_COMPATIBLE`` is the honest member for a self-hosted or third-party
    OpenAI-shaped endpoint that is not OpenRouter: the wire protocol is the same, the
    billing relationship is not, and ``usage.cost`` is an OpenRouter extension nobody else
    returns. ``FAKE`` exists so a ``BAYRAM_USE_FAKE_PROVIDERS`` run is RECORDED and visibly
    excluded rather than invisible — ``vendor_usage.is_fake`` carries the same fact on the
    row, and a demo that wrote no rows at all would be indistinguishable from a deployment
    nobody instrumented.

    This lives here and not in ``bayram.db.enums`` because a provider adapter records usage
    and a provider adapter must never import ``bayram.db``.
    """

    ELEVENLABS = "elevenlabs"
    OPENROUTER = "openrouter"
    GEMINI = "gemini"
    OPENAI_COMPATIBLE = "openai_compatible"
    FAKE = "fake"


class VendorOperation(StrEnum):
    """What the vendor was ASKED to do — the unit a rate card is quoted in.

    Split finer than :class:`Vendor` because that is where the money is: ElevenLabs bills
    music by the rendered minute, speech by the character and transcription by the minute of
    audio, so a single "elevenlabs" total would mix three units and be reconcilable against
    nothing.

    ``HEALTH`` is a member rather than an omission. A quota probe is a real call with real
    latency and a real HTTP status, and dropping it would make the failure rate of a vendor
    that is down look better than it is — but it is never priced, so a probe can never be
    read as spend.
    """

    MUSIC_COMPOSE = "music_compose"
    MUSIC_INPAINT = "music_inpaint"
    SPEECH_SYNTHESIS = "speech_synthesis"
    TRANSCRIPTION = "transcription"
    CHAT_COMPLETION = "chat_completion"
    HEALTH = "health"


class UsageTask(StrEnum):
    """What the call was FOR, in product terms rather than pipeline terms.

    Deliberately not ``PipelineStage``. This enum is stamped on a row by an adapter that
    must not know a pipeline exists, so the stage-to-task mapping lives once in
    ``bayram.pipeline.orchestrator`` and the vendor layer never imports ``bayram.pipeline``.

    ``LYRICS_PREVIEW`` is separate from ``LYRICS`` for the same reason: the wizard writes a
    draft lyric BEFORE an order row exists, so those calls carry a task and no ``order_id``.
    Folding them into ``LYRICS`` would hide the one class of spend that has no order to
    charge it to, which is exactly the spend an operator wants to see.
    """

    MODERATION = "moderation"
    LYRICS = "lyrics"
    LYRICS_PREVIEW = "lyrics_preview"
    GREETING_SCRIPTS = "greeting_scripts"
    SONG = "song"
    NAME_VERIFICATION = "name_verification"
    GREETING_SPEECH = "greeting_speech"


class BalanceUnit(StrEnum):
    """What a ``vendor_balances`` row's quantities are counted in.

    A balance with no unit is unreadable in the same way a cost with no
    :class:`CostSource` is: "4 312 remaining" is a fortune in dollars and an afternoon in
    ElevenLabs characters, and the two vendors this system polls report in one each. It
    lives beside :class:`Vendor` rather than in ``bayram.db.enums`` for that class's stated
    reason — the probe that reads a vendor's own body is a provider-shaped module, and a
    provider must never import ``bayram.db``.
    """

    USD = "usd"
    CHARACTERS = "characters"


class BalanceEstimateBasis(StrEnum):
    """How a "songs remaining" estimate was arrived at — and therefore how far to trust it.

    The same discipline :class:`CostSource` applies to a dollar figure, applied to a
    division. ``TRAILING_SPEND_USD`` divides a measured USD balance by measured USD spend
    per delivered song. ``TRAILING_TTS_CHARACTERS`` divides a character balance by the
    characters TTS billed us per delivered song — and its NAME carries the bias, because
    ElevenLabs music renders draw on the same credit pool while writing ``audio_ms`` rather
    than ``billed_characters``, so that divisor undercounts and the estimate is an UPPER
    BOUND. A tile that renders the number without the basis is rendering a guess as a fact,
    which is why ``ck_vendor_balances_estimate_carries_its_basis`` makes the two inseparable
    in the database rather than in a convention.
    """

    TRAILING_SPEND_USD = "trailing_spend_usd"
    TRAILING_TTS_CHARACTERS = "trailing_tts_characters"


class BotMembershipEvent(StrEnum):
    """A transition in whether a CUSTOMER can be messaged — never the operator's bar.

    ``users.is_blocked`` has the customer as the OBJECT ("an operator barred this account").
    These have the customer as the SUBJECT: they record the customer blocking, or
    unblocking, the bot. The two are separate cards on the dashboard, they are never OR-ed,
    and neither is derived from the other.

    "Membership" is Telegram's own word for the fact (``my_chat_member`` /
    ``ChatMemberUpdated``) and is used deliberately in place of "block", which in this
    schema already means the operator's bar.
    """

    BLOCKED = "blocked"
    UNBLOCKED = "unblocked"


class BotBlockSource(StrEnum):
    """Where a :class:`BotMembershipEvent` was observed, because the two are not equal.

    ``MEMBERSHIP_UPDATE`` is Telegram telling us, on its own ``my_chat_member`` update, at
    the instant it happened. ``DELIVERY_REFUSAL`` is a send that came back
    ``TelegramForbiddenError``, which tells us only that the block had ALREADY happened by
    then. Recording which is which is the same provenance discipline
    ``vendor_usage.cost_source`` applies to money: an instant inferred from a refusal is a
    weaker fact than one the vendor stamped, and a reader must be able to tell them apart.

    The second source is not redundant. ``run_polling`` calls
    ``delete_webhook(drop_pending_updates=True)`` on every start, so every membership update
    that arrived while the bot was down is discarded permanently and Telegram never resends
    it — the delivery refusal is the only source that survives a deploy window.
    """

    MEMBERSHIP_UPDATE = "membership_update"
    DELIVERY_REFUSAL = "delivery_refusal"


class BroadcastKind(StrEnum):
    """What a campaign IS, declared at composition and frozen for the run.

    ``SERVICE`` is a message the product owes the customer — an outage, a price change, a
    song about to be deleted. ``MARKETING`` is a message the product wants to send them.
    The two are one column and never one predicate: the eligibility rule they select is the
    difference between a notice a customer cannot reasonably refuse and a promotion they
    must have agreed to, and collapsing them would make the day someone widens the first a
    day they quietly widened the second.

    Marketing consent is not built in this phase, so today the kind is recorded and
    ``MARKETING`` is gated by a settings flag alone. It is declared here rather than when
    consent lands because the kind is a property of the campaign a reader needs a year from
    now, and a column added later cannot answer "what was that message?" about the ones
    already sent.
    """

    SERVICE = "service"
    MARKETING = "marketing"


class BroadcastState(StrEnum):
    """Where a campaign is in its one run. ``COMPLETED``/``CANCELLED``/``FAILED`` terminate.

    ``DRAFT -> EXPANDING -> READY -> SENDING -> COMPLETED``, with ``PAUSED`` the only state
    that goes back (to ``SENDING``, on resume). ``EXPANDING`` and ``READY`` are separate
    because materialising the audience is a resumable multi-chunk job: a campaign whose rows
    are half-written must be distinguishable from one whose audience is frozen and complete,
    or a crash mid-expansion resumes as a send to whoever happened to be inserted.

    ``FAILED`` grades the RUN, never the recipients. A campaign in which 12 of 40 000
    messages were refused is ``COMPLETED`` — the per-account outcome lives on the recipient
    row, and rolling those two facts into one column is how "did it go out?" stops having an
    answer.
    """

    DRAFT = "draft"
    EXPANDING = "expanding"
    READY = "ready"
    SENDING = "sending"
    PAUSED = "paused"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    FAILED = "failed"


class BroadcastRecipientState(StrEnum):
    """One account's outcome in one campaign — the ledger a replayed job is settled against.

    Every send job is replayed on every deploy (ARQ retries, SIGTERM cancels), so this
    column and not the job is the record of who has been messaged. ``SENDING`` is written
    and committed BEFORE the message leaves, which is what makes the claim exclusive.

    **``UNKNOWN`` is the deliberate hole.** A row left in ``SENDING`` by a killed job may or
    may not have reached Telegram, and it is never retried: the sweep ages it to ``UNKNOWN``,
    where it counts as neither sent nor failed and the panel shows it as its own number.
    Messaging a customer twice is worse than an unresolved three in forty thousand, and a
    counter that quietly rounded the hole away would hide exactly the case an operator needs
    to see.

    The two skips are not one. ``SKIPPED_BLOCKED`` covers both directions of a block — the
    operator's bar and the customer's own — because neither is a delivery attempt;
    ``UNDELIVERABLE`` is Telegram saying the chat is gone. A skipped row is inserted rather
    than filtered out, so the funnel from audience to messages is arithmetic in the table
    instead of a filter someone has to remember.
    """

    PENDING = "pending"
    SENDING = "sending"
    SENT = "sent"
    FAILED = "failed"
    SKIPPED_BLOCKED = "skipped_blocked"
    UNDELIVERABLE = "undeliverable"
    UNKNOWN = "unknown"


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

    error: BayramError

    @property
    def is_retryable(self) -> bool:
        return self.error.is_retryable


type Result[T] = Ok[T] | Err


def ok[T](value: T) -> Ok[T]:
    return Ok(value=value)


def err(error: BayramError) -> Err:
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
class LyricSection(_Frozen):
    """One structural block. ``is_name_hook`` marks the section that carries the name.

    Exactly the sections flagged here become their own composition chunk, so a bad
    pronunciation costs one chunk to re-render, not the whole track.
    """

    label: str = Field(min_length=1, max_length=40)
    lines: tuple[str, ...] = Field(min_length=1)
    is_name_hook: bool = False


class LyricDraft(_Frozen):
    """A complete lyric. ``name_display`` is what the lyric SHEET shows.

    ``name_display`` is ``None`` for a lyric written by the customer on the bring-your-own
    path, where the wizard never asks who the song is for. Such a lyric has NO name-hook
    section either — the two go together, and ``pipeline.lyric_shape`` is what keeps them in
    step. Everything that renders a name therefore has to ask first: the sheet's signature
    line, the delivery captions, and the composition plan's name chunk.

    It is ``None`` rather than an empty string so that "there is no name" cannot be confused
    with "the name is blank", which was the bug the ``min_length=1`` bound was there to
    prevent and which this field must keep preventing for every lyric that does have one.
    """

    title: str = Field(min_length=1, max_length=120)
    language: Language
    sections: tuple[LyricSection, ...] = Field(min_length=1)
    name_display: str | None = Field(default=None, min_length=1)

    @property
    def name_hook_sections(self) -> tuple[LyricSection, ...]:
        return tuple(section for section in self.sections if section.is_name_hook)

    def as_plain_text(self) -> str:
        blocks = ("\n".join(section.lines) for section in self.sections)
        return "\n\n".join(blocks)


class Brief(_Frozen):
    """Everything the user told us. Four structured answers plus a free-text note.

    ``LyricSection`` and ``LyricDraft`` are defined above rather than below so this class
    reads top-down: a brief may already carry the lyric it will be sung with.
    """

    #: Who the song is for, or ``None`` when nobody asked. The wizard's bring-your-own
    #: lyric path does not ask for a name — the customer's own words are the song, and a
    #: name we invented for them would be SUNG — so the whole name subsystem is skipped for
    #: those orders: no hook section, no name chunk, no acoustic verification.
    #:
    #: A ``None`` here is not the same as an identity that has been PURGED. A purged brief
    #: cannot be reconstructed at all and ``db.mapping.to_recipient_name`` still raises for
    #: one; this field being ``None`` means the question was never asked. The two are told
    #: apart by ``briefs.identity_purged_at``, which only the purge job ever sets.
    recipient: RecipientName | None = None
    occasion: Occasion
    genre: Genre
    vocal_gender: VoiceGender
    note: str = Field(default="", max_length=600)
    ui_language: Language
    output_language: Language
    #: The lyric the user previewed and approved in the wizard; ``None`` means the pipeline
    #: writes one itself. It is user-visible free text about the recipient — a pasted lyric
    #: is whatever the customer typed — so it lives on the 30-day note clock, not the
    #: 90-day identity clock.
    approved_lyrics: LyricDraft | None = None


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
    """The full deliverable: one song, a lyric sheet, an optional cover, and greetings.

    ``greetings`` may be EMPTY, and empty is not a failure: ``BAYRAM_GREETINGS_PER_KIT=0``
    sells a song-only kit. The "every greeting failed" case is caught in ``assembly``,
    which knows how many were asked for; this contract cannot tell the two apart.
    """

    order_id: UUID
    song: GeneratedAsset
    greetings: tuple[GeneratedAsset, ...] = ()
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
        self, *, order_id: UUID, amount_minor: int, currency: str, telegram_user_id: int
    ) -> Result[PaymentAuthorization]:
        """``telegram_user_id`` is the payer, which ``order_id`` alone cannot supply: an
        order id is a UUID5 over one draft (``bayram.bot.handlers.confirm._order_id_for``), so
        no provider that meters, blocks or bills per person can recover who is buying from
        it. Both call sites already hold an ``Order`` carrying the field, so this costs no
        plumbing — see ``confirm._is_authorized`` and ``orchestrator._authorize``.
        """
        ...


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

    async def brand(
        self,
        source: Path,
        *,
        destination: Path,
        cover: Path | None,
        tags: tuple[tuple[str, str], ...],
    ) -> Result[Path]:
        """Attach the cover picture and write the metadata tags, without re-encoding.

        **Best-effort, and the only method here whose failure the caller is expected to
        ignore.** A watermark is worth less than the song: on ``Err`` the caller ships the
        unbranded file it already had, exactly as it ships a raw render when loudness
        normalisation fails. That is why this is a separate protocol method rather than a
        step inside :meth:`normalize_loudness` — folding it in would make a lost tag cost
        the customer their mastering.

        ``tags`` is an ordered tuple of ``(key, value)`` pairs and not a mapping because
        each pair becomes two argv elements, and argv is ordered. ``cover`` may be ``None``
        when the picture could not be drawn; the implementation must then write the tags
        alone rather than refusing the whole pass.
        """
        ...


@runtime_checkable
class Storage(Protocol):
    """Object storage. Keys are unguessable and assigned by the caller."""

    async def put(self, key: str, data: bytes, *, content_type: str) -> Result[StoredObject]: ...

    async def get(self, key: str) -> Result[bytes]: ...

    async def signed_url(self, key: str, *, ttl_s: int) -> Result[str]: ...

    async def delete(self, key: str) -> Result[None]: ...

    async def size(self, key: str) -> Result[int]:
        """How many bytes the object holds, so a caller can answer ``Content-Range``.

        Separate from :meth:`open_range` because HTTP needs the total *before* it can
        decide whether a range is satisfiable at all, and because ``assets.size_bytes``
        is not that number — it is what the pipeline produced, defaults to ``0`` on
        every row ever written, and says nothing about what is actually in the archive.
        A caller that wants "does this object exist" asks this and reads the error.
        """
        ...

    async def open_range(self, key: str, *, start: int, end: int) -> Result[AsyncIterator[bytes]]:
        """A bounded byte range, streamed. Confinement is the implementation's job.

        ``start`` and ``end`` are byte offsets into the object and ``end`` is INCLUSIVE,
        matching HTTP's ``Range: bytes=start-end`` exactly so no caller has to convert
        between two conventions and get it wrong by one. An open-ended ``bytes=N-`` is
        spelled ``start=N, end=size - 1`` using :meth:`size`; that is why ``end`` is not
        optional. ``end`` past the last byte is clamped rather than refused, because a
        client asking for more than there is has asked a satisfiable question.

        The iterator is chunked, never whole-object: an ``<audio>`` element issues many
        range requests and a backend that reads the entire song per request is a memory
        amplifier pointed at itself.

        Failures are returned, not raised — except a read that fails *after* the first
        chunk has been yielded, which has no ``Result`` left to return because the
        response is already in flight.
        """
        ...


@runtime_checkable
class KitRepository(Protocol):
    """Persistence for orders and their finished kits."""

    async def create_order(self, order: Order) -> Result[Order]: ...

    async def get_order(self, order_id: UUID) -> Result[Order]: ...

    async def set_order_state(
        self,
        order_id: UUID,
        state: OrderState,
        *,
        now: datetime,
        failed_reason: str | None = None,
    ) -> Result[Order]:
        """Move an order to ``state``, recording operator triage text on a failure.

        ``failed_reason`` lands on a row that OUTLIVES the brief purge, so it must carry
        no recipient name, no sender note, no lyric and no vendor prose quoting any of
        them — only a closed vocabulary an operator can grep. It is cleared on any
        transition out of ``FAILED``.
        """
        ...

    async def save_kit(self, kit: Kit) -> Result[Kit]: ...

    async def get_kit(self, order_id: UUID) -> Result[Kit]: ...

    async def list_orders_for_user(
        self, telegram_user_id: int, *, limit: int
    ) -> Result[tuple[Order, ...]]: ...
