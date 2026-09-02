"""All configuration, in one place, validated at startup.

Two rules this module exists to enforce:

1. **No magic numbers anywhere else.** Timeouts, retry bounds, loudness targets, chunk
   durations and free-tier caps are settings, not literals buried in a worker.
2. **The name-candidate order is CONFIGURATION.** ``name_candidate_order`` is read by the
   name subsystem to rank orthographies. A bake-off result is applied by reordering this
   list in the environment — never by editing code.

``load_settings()`` never raises a pydantic error at a call site: it converts a failure
into a ``ConfigError`` whose operator message names every offending variable.

**Vendor credentials are required by the caller, not by the class.** The bot and the
worker cannot run without ``telegram_bot_token``, ``elevenlabs_api_key`` and
``llm_api_key``, and they must still fail at startup naming the missing variable. The
admin process holds none of them by design (see ``docs/ADMIN_PANEL_PLAN.md`` §4.2)
and the config editor validates a candidate override set in a process that has no vendor
key to offer. Making the three fields optional on ``Settings`` alone would weaken the
startup check that protects the two processes that spend money; so :class:`Settings`
declares them optional and :class:`_VendorBoundSettings` — the class
``build_settings(require_vendor_secrets=True)`` actually instantiates, which is what
``load_settings`` calls — re-declares them as required. Nothing about the bot's or the
worker's boot changes.

**Two tuples, because there are two different claims.** ``VENDOR_SECRET_FIELDS`` is every
credential the admin host must never hold — the admin lifespan derives its refusal list
from it — while ``REQUIRED_VENDOR_SECRET_FIELDS`` is the narrower set the bot and the
worker cannot start without. ``llm_fallback_api_key`` is in the first and not the second:
a deployment with no LLM failover configured is supported, but a prod admin host holding
that key is exactly the blast radius the third process exists to avoid. Conflating the two
is what let it reach a prod admin host with neither a refusal nor a warning.
"""

from __future__ import annotations

from collections.abc import Mapping
from functools import lru_cache
from typing import Annotated, Any, Final, Literal

from pydantic import Field, field_validator
from pydantic import ValidationError as PydanticValidationError
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict
from pydantic_settings.exceptions import SettingsError

from hbd.contracts import Language, NameStrategy
from hbd.errors import ConfigError

__all__ = [
    "Settings",
    "build_settings",
    "load_settings",
    "get_settings",
    "LogLevel",
    "VENDOR_SECRET_FIELDS",
    "REQUIRED_VENDOR_SECRET_FIELDS",
    "DEFAULT_NAME_CANDIDATE_ORDER",
    "ENV_PREFIX",
]

ENV_PREFIX: Final[str] = "HBD_"

#: Typed rather than ``str`` because ``configure_logging`` calls ``root.setLevel(value)``,
#: and an unknown level raises there — inside a running process, long after the point where
#: a configuration mistake is still cheap to report.
type LogLevel = Literal["DEBUG", "INFO", "WARNING", "ERROR"]

#: The credentials the admin process must never hold (ADMIN_PANEL_PLAN §4.2, D10). The admin
#: lifespan derives ``FORBIDDEN_ENV_VARS`` from this tuple, so a credential missing here is a
#: credential a prod admin host may hold with neither a refusal nor a warning. Every field on
#: :class:`Settings` whose name ends in a credential word belongs here, and a test in
#: ``tests/test_admin/test_settings_and_boot.py`` asserts exactly that, so the next one added
#: to the class cannot be forgotten.
VENDOR_SECRET_FIELDS: Final[tuple[str, ...]] = (
    "telegram_bot_token",
    "elevenlabs_api_key",
    "llm_api_key",
    "llm_fallback_api_key",
)

#: The subset the bot and the worker cannot run without — the ones
#: :class:`_VendorBoundSettings` re-declares as required. Strictly narrower than
#: ``VENDOR_SECRET_FIELDS``: "the admin host must never hold it" and "this process cannot
#: start without it" are different claims, and the documented LLM failover is a supported
#: deployment when it is left unconfigured.
REQUIRED_VENDOR_SECRET_FIELDS: Final[tuple[str, ...]] = (
    "telegram_bot_token",
    "elevenlabs_api_key",
    "llm_api_key",
)

#: The bake-off's winning arm is not yet fed back in, so this is a starting order,
#: not a finding. Override with HBD_NAME_CANDIDATE_ORDER without touching code.
DEFAULT_NAME_CANDIDATE_ORDER: Final[tuple[NameStrategy, ...]] = (
    NameStrategy.STRIPPED,
    NameStrategy.CANONICAL,
    NameStrategy.HYPHENATED,
    NameStrategy.ASCII,
    NameStrategy.PHONETIC,
)


def _split_csv(value: Any) -> Any:
    """Accept ``a,b,c`` from the environment for list-typed settings.

    pydantic-settings would otherwise demand JSON for a complex type, which is not what a
    human types into a ``.env`` file. Stray brackets and quotes are tolerated so a
    JSON-shaped value does not fail confusingly.
    """
    if not isinstance(value, str):
        return value
    stripped = value.strip().strip("[]")
    return [item.strip().strip("\"'") for item in stripped.split(",") if item.strip()]


class Settings(BaseSettings):
    """Every knob in the system. Immutable once loaded.

    Build one with :func:`build_settings`, never with ``Settings()`` in application code:
    only ``build_settings`` decides whether the vendor credentials are required, and only
    it converts a validation failure into a ``ConfigError`` that names the variable.
    """

    model_config = SettingsConfigDict(
        env_prefix=ENV_PREFIX,
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        frozen=True,
    )

    # -- runtime ------------------------------------------------------------
    environment: str = Field(default="dev", description="dev | staging | prod")
    log_level: LogLevel = Field(default="INFO")
    is_debug: bool = Field(default=False)
    use_fake_providers: bool = Field(
        default=False,
        description=(
            "Swap every vendor adapter for its Fake. No API key is read, nothing is spent, "
            "and the whole app runs offline. Never enable in prod."
        ),
    )

    # -- telegram -----------------------------------------------------------
    #: Empty is only legal in a process that builds settings with
    #: ``require_vendor_secrets=False``; every other caller gets it back as required.
    telegram_bot_token: str = Field(default="")

    # -- infrastructure -----------------------------------------------------
    database_url: str = Field(min_length=1, description="postgresql+asyncpg://…")
    redis_url: str = Field(default="redis://localhost:6379/0")

    # -- ElevenLabs (music + RU/EN TTS + STT) -------------------------------
    elevenlabs_api_key: str = Field(default="")  # required — see telegram_bot_token
    elevenlabs_base_url: str = Field(default="https://api.elevenlabs.io")
    music_model_id: str = Field(default="music_v2", description='"music_v1" | "music_v2"')
    music_output_format: str = Field(default="mp3_44100_128")
    music_max_concurrency: int = Field(
        default=2,
        ge=1,
        le=10,
        description="Vendor's simultaneous-render ceiling: 2 on Starter/Creator/Pro, 5 on Scale.",
    )
    music_usd_per_minute: float = Field(
        default=0.15, gt=0, description="Rate the usage line's cost estimate is derived from."
    )
    tts_max_concurrency: int = Field(default=3, ge=1, le=20)
    tts_model_id: str = Field(default="eleven_v3")
    stt_model_id: str = Field(default="scribe_v2")

    elevenlabs_usd_per_character: float = Field(default=0.0, ge=0.0)

    # -- TTS cast and routing (both are data, replaceable without a deploy) --
    tts_voice_registry_json: str = Field(
        default="", description="Non-empty JSON replaces the persona catalogue."
    )
    tts_routes: str = Field(
        default="",
        description='Non-empty overrides the split, e.g. "ru=elevenlabs_tts".',
    )

    # -- LLM ----------------------------------------------------------------
    llm_api_key: str = Field(default="")  # required — see telegram_bot_token
    llm_base_url: str = Field(default="https://openrouter.ai/api/v1")
    llm_model_id: str = Field(default="google/gemma-4-31b-it:free")
    llm_provider: Literal["gemini", "openai"] = Field(
        default="openai",
        description=(
            "Which adapter serves the primary model. OpenRouter is OpenAI-compatible, so it "
            "uses the 'openai' adapter with llm_base_url pointed at it."
        ),
    )
    #: Optional — an unconfigured failover is a supported deployment — but still a vendor
    #: credential, so it is in ``VENDOR_SECRET_FIELDS`` and the admin host is refused it.
    llm_fallback_api_key: str = Field(default="")
    llm_fallback_provider: Literal["gemini", "openai"] = Field(
        default="openai", description="Which adapter serves the documented failover model."
    )
    llm_fallback_base_url: str = Field(
        default="", description="Empty means the OpenAI-compatible adapter's own default host."
    )
    llm_fallback_model_id: str = Field(default="gpt-5.6-luna")
    llm_temperature: float = Field(default=0.7, ge=0.0, le=2.0)
    llm_max_output_tokens: int = Field(default=2_048, gt=0)

    # -- timeouts (seconds) -------------------------------------------------
    llm_timeout_s: float = Field(default=45.0, gt=0)
    music_timeout_s: float = Field(default=420.0, gt=0)
    tts_timeout_s: float = Field(default=60.0, gt=0)
    stt_timeout_s: float = Field(default=30.0, gt=0)

    # -- retry bounds -------------------------------------------------------
    provider_max_attempts: int = Field(default=4, ge=1, le=10)
    provider_backoff_base_s: float = Field(default=5.0, gt=0)
    provider_backoff_jitter: float = Field(default=0.2, ge=0.0, le=1.0)
    llm_parse_max_attempts: int = Field(default=2, ge=1, le=5)

    # -- the name subsystem -------------------------------------------------
    name_candidate_order: Annotated[tuple[NameStrategy, ...], NoDecode] = Field(
        default=DEFAULT_NAME_CANDIDATE_ORDER,
        min_length=1,
        description="Rank order for candidate orthographies. Reorder freely; do not edit code.",
    )
    name_verification_max_attempts: int = Field(
        default=3,
        ge=1,
        le=6,
        description="Acoustic re-rolls of the name chunk before we deliver the best attempt.",
    )
    name_match_min_similarity: float = Field(
        default=0.85,
        ge=0.0,
        le=1.0,
        description="Normalised-string similarity above which an STT transcript counts as a match.",
    )
    name_chunk_duration_ms: int = Field(
        default=8_000,
        ge=3_000,
        le=120_000,
        description="The name gets its own short chunk so a re-render costs one chunk.",
    )
    is_name_verification_enabled: bool = Field(default=True)

    # -- song shape ---------------------------------------------------------
    song_length_ms: int = Field(default=90_000, ge=3_000, le=600_000)
    greeting_min_duration_s: float = Field(default=20.0, gt=0)
    greeting_max_duration_s: float = Field(default=45.0, gt=0)
    greetings_per_kit: int = Field(
        default=0,
        ge=0,
        le=5,
        description="0 sells a song-only kit and buys no speech at all.",
    )

    # -- audio post ---------------------------------------------------------
    ffmpeg_binary: str = Field(default="ffmpeg")
    ffprobe_binary: str = Field(default="ffprobe")
    ffmpeg_timeout_s: float = Field(
        default=180.0, gt=0, description="Subprocess wall clock. Not a vendor timeout."
    )
    loudnorm_song_lufs: float = Field(default=-14.0)
    loudnorm_speech_lufs: float = Field(default=-16.0)
    loudnorm_true_peak_db: float = Field(default=-1.0)
    opus_bitrate_bps: int = Field(default=32_000, gt=0)
    opus_sample_rate_hz: int = Field(default=48_000, gt=0)
    fade_in_ms: int = Field(default=250, ge=0)
    fade_out_ms: int = Field(default=1_500, ge=0)
    silence_trim_threshold_db: float = Field(default=-50.0)

    # -- pricing (payment is out of scope; the seam is not) ------------------
    kit_price_amount_minor: int = Field(
        default=0, ge=0, description="Minor units. 0 until a real payment rail lands."
    )
    kit_currency: str = Field(default="UZS", min_length=3, max_length=3)

    # -- moderation ---------------------------------------------------------
    is_moderation_enabled: bool = Field(default=True)

    # -- entitlements -------------------------------------------------------
    #: Whether the credit balance is actually *enforced* at the render gate.
    #:
    #: Ships **False** on purpose, and the default is the shipped configuration. The merge
    #: that lands the meter must not also be the merge that starts turning paying-intent
    #: customers away, because there is no top-up path in this build (ADMIN_PANEL_PLAN D9
    #: forbids a payment rail) and the only way back for a refused customer is the calendar.
    #:
    #: This flag covers the BALANCE CHECK only, and it covers it as narrowly as one branch:
    #: ``hbd.db.credits.charge`` still opens the account, mints the rolling allowance, runs
    #: the block gate and the in-flight cap, writes the debit and is settled — the ONE thing
    #: it does differently is that a customer who has run out is covered by a
    #: ``CreditReason.UNENFORCED_RENDER`` grant instead of refused.
    #:
    #: It used to be read one level up, by ``CreditGatedPaymentProvider``, which skipped the
    #: store entirely. That looked more cautious and was strictly worse: the in-flight cap
    #: counts unsettled DEBIT rows, so with no charge there were no debits, the cap refused
    #: nobody, and an account blocked after its job was queued still rendered and shipped.
    #: The account block, the in-flight cap and the inbound throttle refuse *abuse*, not
    #: customers, so they are never behind this flag — and now they genuinely are not.
    credits_enforced: bool = Field(
        default=False,
        description="Enforce the credit balance at the render gate. False ships the meter dark.",
    )

    #: How long a debit may sit unsettled before the in-flight cap stops counting it and the
    #: stale-debit sweep may close it.
    #:
    #: ``None`` — the shipped value — means DERIVE it from this deployment's own queue
    #: ladder: ``queue_job_timeout_s * queue_max_tries`` plus every ``provider_backoff_base_s``
    #: deferral in between (see ``hbd.entitlements.derive_settlement_grace_s``). That is
    #: deliberately not a fixed number: a fixed hour is shorter than the 4500s of job
    #: timeouts arq alone will spend on one order under the shipped defaults, and a grace
    #: under the ladder makes the sweep refund orders that are still rendering — the customer
    #: keeps the credit AND gets the song. Raising ``HBD_QUEUE_JOB_TIMEOUT_S`` therefore moves
    #: this with it, and an operator who wants a different number has to say so on purpose.
    settlement_grace_s: int | None = Field(
        default=None,
        ge=1,
        description=(
            "Seconds a debit may stay unsettled before the sweep closes it. Unset derives "
            "it from the queue ladder, which is almost always what you want."
        ),
    )

    # -- inbound gate (the throttle and the block cache) ---------------------
    #: These three are **never** behind ``credits_enforced``. That flag covers the balance
    #: check, which refuses a paying-intent customer with no way to top up; the throttle and
    #: the block gate refuse abuse, and shipping an abuse rail dark is shipping no rail.
    #:
    #: The throttle is a FIXED window, so a burst can straddle a boundary and land up to
    #: twice ``inbound_max_updates`` inside one window's worth of wall time. That is
    #: deliberate — see ``hbd.ratelimit`` — because what this bounds is one human's tap rate,
    #: not a security boundary.
    inbound_window_s: int = Field(
        default=60, ge=1, description="Length of the inbound throttle's fixed window."
    )
    #: A full walk through the wizard is about ten updates and a customer who re-reads the
    #: lyric a few times is more, so the ceiling sits well clear of any honest session: too
    #: tight and the bot tells a paying customer to slow down mid-order, which costs a sale
    #: to save nothing. Thirty a minute still stops a script dead.
    inbound_max_updates: int = Field(
        default=30, ge=1, description="Updates one account may send per window."
    )
    #: How long a block answer is reused before ``balance_for`` is asked again. The cost is
    #: the lag on an UNBLOCK — an operator lifting a block waits up to this long, per
    #: process — and the thing it buys is that the block gate is not a database round trip
    #: on every inbound update, taken inside the FSM isolation lock.
    inbound_block_cache_s: int = Field(
        default=60, ge=1, description="Seconds a blocked/not-blocked answer is cached for."
    )
    #: ``/privacy``, ``/forget`` and ``/support`` skip the block gate and the ordinary
    #: ceiling — a data-subject request must never be refused by an abuse control — but they
    #: get a budget of their own rather than none. ``/forget`` opens a transaction that
    #: rewrites every ledger row for the account and deletes its balance; exempt from every
    #: limiter, it was an unmetered write amplifier for anyone willing to hold the key down.
    #: Three a minute is far past what a person needs, and the command is idempotent.
    inbound_erasure_max_updates: int = Field(
        default=3, ge=1, description="Data-subject commands one account may send per window."
    )

    # -- lyric budget (the daily ceiling on vendor spend before any gate) ----
    #: Lyric writes one account may be billed for per UTC day.
    #:
    #: **Never behind ``credits_enforced``**, for the same reason the throttle and the block
    #: gate are not: this refuses abuse, not customers. The lyric write is the FIRST vendor
    #: spend in the product and it happens before every gate that guards the worker, so a
    #: person who never presses Confirm meets none of them — and ``MAX_LYRIC_WRITES`` counts
    #: per DRAFT, which ``reset_to_welcome`` throws away, so ``/start`` used to give the
    #: counter back. Shipping this dark would be shipping no rail at all.
    #:
    #: Twenty, and the direction of the error is what chose it. Three songs every thirty
    #: days at five writes each — the per-draft ceiling — is fifteen for a customer who
    #: orders their whole month in one sitting and rerolls every song to the limit, so
    #: twenty leaves that person clear headroom. Too tight refuses a paying-intent customer
    #: at the one step the wizard cannot skip; too loose still turns unbounded spend into a
    #: bounded, observable number. See ``hbd.lyric_budget``.
    lyric_writes_per_day: int = Field(
        default=20,
        ge=1,
        le=1_000,
        description="Lyric writes one account may be billed for per UTC day.",
    )

    # -- support ------------------------------------------------------------
    #: Where ``/support`` sends a customer whose song came out wrong: an ``@handle``, a
    #: ``t.me`` link or an address. Deliberately defaulted to empty rather than to a
    #: plausible-looking placeholder — a destination nobody reads is worse than no
    #: destination, because the customer believes they have reported the problem. The
    #: handler renders different copy when it is empty and asks them to reply in the chat.
    support_contact: str = Field(default="")

    # -- languages ----------------------------------------------------------
    default_ui_language: Language = Field(default=Language.UZ_LATN)
    supported_languages: Annotated[tuple[Language, ...], NoDecode] = Field(
        default=(Language.UZ_LATN, Language.UZ_CYRL, Language.RU, Language.EN),
        min_length=1,
    )

    # -- queue --------------------------------------------------------------
    worker_concurrency: int = Field(default=15, ge=1, le=200)
    queue_job_timeout_s: float = Field(default=900.0, gt=0)
    queue_result_ttl_s: float = Field(
        default=3_600.0,
        gt=0,
        description="How long a finished job's result stays in Redis. Not a storage TTL.",
    )
    queue_max_tries: int = Field(
        default=5,
        ge=1,
        le=20,
        description=(
            "How many attempts one order gets before the queue abandons it. Set on the "
            "worker AND read by the job, which stops raising Retry on its last attempt so "
            "the customer is told and the wizard session is released. ARQ abandons an "
            "exhausted job inside its own runner and never re-enters the job function, so "
            "a job that leaves this to the queue leaves the customer parked for the life "
            "of the FSM state."
        ),
    )

    # -- validators ---------------------------------------------------------
    _normalize_lists = field_validator(
        "name_candidate_order", "supported_languages", mode="before"
    )(_split_csv)

    @field_validator("name_candidate_order")
    @classmethod
    def _candidates_must_be_unique(
        cls, value: tuple[NameStrategy, ...]
    ) -> tuple[NameStrategy, ...]:
        if len(set(value)) != len(value):
            raise ValueError(f"duplicate strategies in name_candidate_order: {value}")
        return value

    @field_validator("supported_languages")
    @classmethod
    def _languages_must_be_unique(cls, value: tuple[Language, ...]) -> tuple[Language, ...]:
        if len(set(value)) != len(value):
            raise ValueError(f"duplicate entries in supported_languages: {value}")
        return value

    @field_validator("greeting_max_duration_s")
    @classmethod
    def _greeting_window_must_be_ordered(cls, value: float, info: Any) -> float:
        minimum = info.data.get("greeting_min_duration_s")
        if minimum is not None and value <= minimum:
            raise ValueError(
                f"greeting_max_duration_s ({value}) must exceed greeting_min_duration_s ({minimum})"
            )
        return value

    @property
    def is_production(self) -> bool:
        return self.environment == "prod"


class _VendorBoundSettings(Settings):
    """``Settings`` with ``REQUIRED_VENDOR_SECRET_FIELDS`` required again.

    A subclass rather than a validator flag: the requirement is expressed in the same
    place, and by the same mechanism, as every other constraint in this module, so the
    failure message an operator reads is the one pydantic already produces.
    """

    telegram_bot_token: str = Field(min_length=1)
    elevenlabs_api_key: str = Field(min_length=1)
    llm_api_key: str = Field(min_length=1)


_FAILURE_PREAMBLE: Final[str] = (
    "Configuration is invalid or incomplete. Fix these environment variables (see .env.example):"
)


def _describe_failure(exc: PydanticValidationError) -> str:
    lines: list[str] = []
    for issue in exc.errors():
        field = ".".join(str(part) for part in issue["loc"]) or "<root>"
        env_var = f"{ENV_PREFIX}{field.upper()}"
        lines.append(f"  {env_var}: {issue['msg']}")
    return "\n".join(lines)


def build_settings(
    overrides: Mapping[str, object] | None = None,
    *,
    require_vendor_secrets: bool = True,
) -> Settings:
    """Build settings from the environment, with ``overrides`` layered on top.

    ``overrides`` wins over the environment and over ``.env``; it is how the runtime
    config overlay validates a candidate change without writing it anywhere, and how a
    test builds a variant without touching the process environment.

    ``require_vendor_secrets=False`` builds the same model with the three vendor
    credentials left optional — for a process that must not hold them at all (the admin
    API) or that is only checking whether a set of values *would* validate. It never
    relaxes anything else, and ``load_settings`` — the path the bot and the worker boot
    through — always passes ``True``.

    Raises ``ConfigError`` and nothing else — callers never see a pydantic exception.
    """
    model = _VendorBoundSettings if require_vendor_secrets else Settings
    values: dict[str, Any] = dict(overrides or {})
    try:
        return model(**values)  # remaining values come from the environment and .env
    except PydanticValidationError as exc:
        raise ConfigError(
            f"{_FAILURE_PREAMBLE}\n{_describe_failure(exc)}",
            context={"issue_count": len(exc.errors())},
            cause=exc,
        ) from exc
    except SettingsError as exc:
        raise ConfigError(
            f"{_FAILURE_PREAMBLE}\n  {exc}",
            context={"issue_count": 1},
            cause=exc,
        ) from exc


def load_settings() -> Settings:
    """The bot's and the worker's boot path: the environment, vendor secrets required."""
    return build_settings(require_vendor_secrets=True)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Process-wide singleton. Tests should build ``Settings(...)`` directly instead."""
    return load_settings()
