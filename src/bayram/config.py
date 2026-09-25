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
admin process holds none of them by design (see ``docs/product/ADMIN_PANEL_PLAN.md`` §4.2)
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

**And a third tuple, which is not a list of fields at all.** ``FOREIGN_SECRET_ENV_VARS``
names environment VARIABLES belonging to a settings model in another process — today just
``BAYRAM_PAYME_MERCHANT_KEY``, which lives on ``bayram.payme.settings.PaymeSettings`` and is
deliberately absent from :class:`Settings`. A secret can be one this process must refuse to
hold without being one this process can be configured with, and the two lists above could not
express that: both are keyed on field names, and this credential has no field here to name.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from functools import lru_cache
from typing import Annotated, Any, Final, Literal

from pydantic import Field, field_validator
from pydantic import ValidationError as PydanticValidationError
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict
from pydantic_settings.exceptions import SettingsError

from bayram.contracts import Language, NameStrategy
from bayram.errors import ConfigError

__all__ = [
    "Settings",
    "build_settings",
    "load_settings",
    "get_settings",
    "LogLevel",
    "CheckoutRail",
    "MediaBackendName",
    "MediaModeratorName",
    "VENDOR_SECRET_FIELDS",
    "REQUIRED_VENDOR_SECRET_FIELDS",
    "FOREIGN_SECRET_ENV_VARS",
    "DEFAULT_NAME_CANDIDATE_ORDER",
    "ENV_PREFIX",
    "ENV_FILE",
    "ENV_FILE_VAR",
    "env_file",
    "resolve_env_file",
]

ENV_PREFIX: Final[str] = "BAYRAM_"

#: The dotenv file the bot and the worker read when nothing selects another. Unchanged from
#: what it has always been, so a checkout with a ``.env`` and no ``BAYRAM_ENV_FILE`` behaves
#: exactly as before.
ENV_FILE: Final[str] = ".env"

#: The variable that selects a different one — ``BAYRAM_ENV_FILE=.env.prod``, which is how
#: ``ENV=prod make dev`` exercises a production configuration from a development machine, and
#: how a systemd unit points at ``/etc/bayram/bot.env`` outside the checkout.
#:
#: **Read from the process environment ONLY**, and it has to be: a dotenv file cannot name
#: the dotenv file that is about to be read. Writing ``BAYRAM_ENV_FILE`` *into* ``.env`` is
#: therefore a line with no effect, not a redirect — the same chicken-and-egg every dotenv
#: loader has, stated here because the failure is silent.
ENV_FILE_VAR: Final[str] = f"{ENV_PREFIX}ENV_FILE"


def resolve_env_file(variable: str, default: str) -> str:
    """``os.environ[variable]`` when it holds a path, else ``default``.

    Blank is "not set". An exported-but-empty variable is what a shell script produces from
    an unset interpolation, and resolving that to the empty path would silently read no
    dotenv file at all — the failure mode being avoided is a process that boots on defaults
    because a deploy script had a typo.
    """
    return os.environ.get(variable, "").strip() or default


def env_file() -> str:
    """Which dotenv file :func:`build_settings` reads. See :data:`ENV_FILE_VAR`."""
    return resolve_env_file(ENV_FILE_VAR, ENV_FILE)


#: Typed rather than ``str`` because ``configure_logging`` calls ``root.setLevel(value)``,
#: and an unknown level raises there — inside a running process, long after the point where
#: a configuration mistake is still cheap to report.
type LogLevel = Literal["DEBUG", "INFO", "WARNING", "ERROR"]

#: Which checkout rail sells a credit. Closed rather than a free ``str`` so that an operator's
#: typo is a boot failure naming ``BAYRAM_CHECKOUT_PROVIDER`` instead of a silent fall-through to
#: the stub — a deployment that thinks it went live and is quietly selling nothing.
#:
#: **The two strings are spelled here as literals and are also canonical constants elsewhere** —
#: ``bayram.checkout.STUB_PROVIDER_NAME`` and ``bayram.payme.ports.PAYME_PROVIDER_NAME``, which
#: is what the composition root compares against and what the ledger writes onto every receipt.
#: A ``Literal`` cannot be built from imported names, and this module must not import either
#: package anyway (``bayram.checkout`` is a leaf ``bayram.db`` depends on; ``bayram.payme`` is a
#: rail). ``tests/test_runtime/test_wiring.py`` asserts the three spellings agree, so the
#: duplication is pinned rather than merely noticed.
type CheckoutRail = Literal["stub", "payme"]

#: Which generation backend renders a media SKU (IMAGE_VIDEO_SPEC §4.5, O18). Closed for the
#: same reason as :data:`CheckoutRail`: a typo is a boot failure naming the variable, not a
#: silent fall-through. The spellings equal ``bayram.db.enums.MediaBackend``'s values, which
#: is what ``media_jobs.backend`` stores; ``tests/test_media/test_settings.py`` pins the two.
type MediaBackendName = Literal["local", "higgsfield", "fal", "fake"]

#: Who screens media (IMAGE_VIDEO_SPEC §6). ``fake`` refuses to boot with any SKU offered
#: outside the test suite (§4.5, §7.4).
type MediaModeratorName = Literal["gateway", "fake"]

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
    "openrouter_management_key",
    # The local generation gateway's key (IMAGE_VIDEO_SPEC §9.5). Optional — media is off by
    # default — so it is here and not in REQUIRED_VENDOR_SECRET_FIELDS.
    "genai_api_key",
    # The Cloudflare Access service token in front of that gateway (IMAGE_VIDEO_SPEC §9.1
    # item 2). The client id is not secret-shaped; the secret is.
    "genai_access_client_secret",
    # A hosted guard endpoint's own credentials (IMAGE_VIDEO_SPEC §6.2, the D24 fallback):
    # the gateway's key and Access token are never sent to a host that is not the gateway.
    "media_moderator_api_key",
    "media_moderator_access_client_secret",
    # The Gemini TTS key pool (IMAGE_VIDEO_SPEC §5.2, §9.5; D23). Optional: an empty pool
    # narrates through ElevenLabs.
    "gemini_tts_api_keys",
    # Higgsfield's REST secret (IMAGE_VIDEO_SPEC §4.3, §9.5; M6). The key id beside it is not
    # secret-shaped and is not listed; the pair is useless without this half.
    "higgsfield_api_secret",
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

#: **A THIRD tuple, because there is a third claim, and it is about a secret that is not a
#: field on this class at all.** The two tuples above are lists of ``Settings`` FIELDS; this
#: one is a list of ENVIRONMENT VARIABLE NAMES belonging to a settings model in another
#: process — ``bayram.payme.settings.PaymeSettings`` — which the admin host must still never
#: hold, and which the BOT must never hold either.
#:
#: ``BAYRAM_PAYME_MERCHANT_KEY`` is the Payme cashbox key: an INBOUND VERIFICATION secret, whose
#: blast radius is different in kind from the five outbound credentials above. Stealing an
#: outbound key spends our money at a vendor or impersonates our bot; stealing this one lets
#: the thief mint credits by forging settlements at our own gateway. Three blast radii, three
#: containers — and the bot builds checkout links with the PUBLIC merchant id and has no
#: business being able to read the key that verifies them.
#:
#: It is a separate tuple rather than a fifth entry in ``VENDOR_SECRET_FIELDS`` for a
#: mechanical reason as well as a conceptual one: ``tests/test_admin/test_settings_and_boot.py``
#: asserts SET EQUALITY between that tuple and every secret-shaped field name on
#: :class:`Settings`, so a name with no field behind it would fail a test whose whole purpose
#: is to stop the NEXT credential being forgotten. Consumers that refuse an environment — the
#: admin lifespan, and ``bayram.main``'s prod boot check — read both.
FOREIGN_SECRET_ENV_VARS: Final[tuple[str, ...]] = (f"{ENV_PREFIX}PAYME_MERCHANT_KEY",)

#: The bake-off's winning arm is not yet fed back in, so this is a starting order,
#: not a finding. Override with BAYRAM_NAME_CANDIDATE_ORDER without touching code.
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
        env_file=ENV_FILE,
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
    #: The only rate on this class that ships non-zero, and the bound is ``ge`` rather than
    #: ``gt`` so that "I do not know what a minute of music costs" stays sayable. Every other
    #: leg can say it — ``elevenlabs_usd_per_character`` and the four
    #: ``llm_*_usd_per_million_*`` fields all ship ``0.0`` — and a floor that forbids zero
    #: would leave music the one vendor call an operator is FORCED to put a price on, which
    #: is the shape that fabricates numbers.
    music_usd_per_minute: float = Field(
        default=0.15,
        ge=0.0,
        description=(
            "Rate the usage line's cost estimate is derived from. The shipped 0.15 is a "
            "placeholder list price, so a fresh deployment's music rows carry a real figure "
            "labelled ESTIMATED — reconcile it against the dashboard. Set 0.0 to mean NOT "
            "PRICED: the render is still measured and logged, cost_usd stays NULL and the "
            "panel prints 'not priced', which is not the same claim as a free render."
        ),
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
    #: An OpenRouter **management** key, held for one purpose: ``GET /api/v1/credits``, the
    #: only endpoint that reports the account's prepaid balance rather than the cap on one
    #: inference key. ``GET /api/v1/key`` — what the balance poller has always used — answers
    #: ``limit: null`` for an uncapped key, which is an honest "no figure" and cannot be
    #: turned into a percentage; this key is what makes the panel's balance ring a fraction
    #: of something real.
    #:
    #: **It is the most dangerous credential this deployment holds, and it is optional.** A
    #: management key can create and revoke API keys and read the account, so its blast
    #: radius is larger than the spend it reports: leaked, it does not merely bill us, it
    #: locks the workers out. It is therefore in ``VENDOR_SECRET_FIELDS`` (a prod admin host
    #: is refused it outright) and NOT in ``REQUIRED_VENDOR_SECRET_FIELDS`` — every process
    #: starts without it and the poller simply reports the uncapped key it always did. Only
    #: the balance poller in the worker ever reads it; no inference path touches it.
    openrouter_management_key: str = Field(default="")
    llm_fallback_provider: Literal["gemini", "openai"] = Field(
        default="openai", description="Which adapter serves the documented failover model."
    )
    llm_fallback_base_url: str = Field(
        default="", description="Empty means the OpenAI-compatible adapter's own default host."
    )
    llm_fallback_model_id: str = Field(default="gpt-5.6-luna")
    llm_temperature: float = Field(default=0.7, ge=0.0, le=2.0)
    llm_max_output_tokens: int = Field(default=2_048, gt=0)
    llm_disable_reasoning: bool = Field(
        default=False,
        description=(
            "Ask the gateway to turn the model's reasoning trace OFF. Needed for a hybrid "
            "reasoning model behind an OpenRouter-shaped endpoint: the trace is billed and "
            "capped as OUTPUT, so it eats llm_max_output_tokens and the JSON object is cut "
            "off mid-string — finish_reason 'length', then LlmParseError, measured at 1,931 "
            "reasoning tokens of a 2,048 cap on nemotron-3-super. Default off because the "
            "field is an OpenRouter extension that a strict OpenAI host rejects outright, "
            "and because a non-reasoning model does not need it. Ignored by the Gemini "
            "adapter, which has its own thinking controls."
        ),
    )

    # -- LLM token rates (per MILLION tokens) -------------------------------
    #
    # A ZERO rate is the shipped default and it does not mean "free". It means no rate is
    # configured in this deployment, so the chat-completion leg records its token counts
    # and NO dollar figure at all — ``vendor_usage.cost_usd`` stays NULL and the panel
    # prints "not priced" rather than "$0.00". The two readings are different facts and
    # only one of them is true.
    #
    # None of the four is live-editable, deliberately (``docs/product/ADMIN_PANEL_PLAN.md`` §8.4):
    # a rate edited while the system is running silently rewrites what every row already
    # written means, against a ``cost_source`` that still claims the figure was DERIVED
    # from the rate card. Changing a rate is a deploy, and the rows either side of it are
    # then honestly attributable to the rate that was in force.
    #
    # Rates apply only where the vendor did not bill us directly. OpenRouter returns its
    # own ``usage.cost`` and that number always wins (VENDOR_REPORTED); these settings are
    # the fallback arithmetic for a host that reports tokens and nothing else.
    llm_usd_per_million_prompt_tokens: float = Field(default=0.0, ge=0.0)
    llm_usd_per_million_completion_tokens: float = Field(default=0.0, ge=0.0)
    #: The FAILOVER account's own rate card. Separate from the primary's because the
    #: fallback is usually a different model on a different account, and averaging the two
    #: would make "what is the fallback costing us" unanswerable — which is the same reason
    #: ``vendor_usage.is_fallback`` exists.
    llm_fallback_usd_per_million_prompt_tokens: float = Field(default=0.0, ge=0.0)
    llm_fallback_usd_per_million_completion_tokens: float = Field(default=0.0, ge=0.0)

    # NO STT RATE IS DECLARED, AND THE ABSENCE IS THE DECISION. ElevenLabs bills Scribe per
    # MINUTE OF AUDIO, and nothing in this system measures audio duration: the transcription
    # leg knows how many bytes it uploaded and nothing else. A rate multiplied by a guessed
    # bitrate is a fabricated number, so transcription carries no cost at all — its rows are
    # recorded with cost NULL and the panel says so.

    # -- vendor balance polling ---------------------------------------------
    #
    # Read ONLY inside the ARQ worker. The admin process must never hold an HTTP client and
    # a vendor key (ADMIN_PANEL_PLAN §4.2), so the worker polls and writes ``vendor_balances``
    # and the panel reads a table whose numbers are already computed. NONE of the four below
    # is a credential, so ``VENDOR_SECRET_FIELDS`` is untouched and the admin's
    # ``FORBIDDEN_ENV_VARS`` derives the same four names it does today — the poller
    # authenticates with ``llm_api_key``, ``llm_fallback_api_key`` and ``elevenlabs_api_key``,
    # all three already in that tuple. The one endpoint that WOULD have needed a fifth secret
    # (OpenRouter's ``/api/v1/credits``, documented "Management key required") is deliberately
    # not used, and that non-change is the security boundary's receipt.
    vendor_balance_poll_enabled: bool = Field(
        default=True,
        description=(
            "Poll OpenRouter and ElevenLabs hourly for remaining credit and quota. Off means "
            "the balance table is never written and the dashboard's balance tiles render "
            "'not polled', which is the honest empty state. Separate from "
            "BAYRAM_USE_FAKE_PROVIDERS: that says 'contact no vendor at all', this says 'do not "
            "call this one surface'."
        ),
    )
    vendor_balance_timeout_s: float = Field(
        default=10.0,
        gt=0,
        le=60.0,
        description=(
            "Per-request timeout for one balance probe. Matches "
            "providers/tts/elevenlabs_api.DEFAULT_HEALTH_TIMEOUT_S, the timeout the existing "
            "probe of the very same ElevenLabs endpoint already uses — two different timeouts "
            "against one URL would be a difference nobody could explain. Upper bound 60 "
            "because a balance nobody can fetch in a minute is a vendor outage, and reporting "
            "it as one is more useful than waiting."
        ),
    )
    vendor_balance_job_timeout_s: float = Field(
        default=60.0,
        gt=0,
        le=600.0,
        description=(
            "Whole-cron ceiling for the balance poll. Deliberately NOT queue_job_timeout_s "
            "(900.0), which is sized for a music render: this job makes at most three GETs "
            "and runs two small aggregates, and a cron holding a worker slot for fifteen "
            "minutes over a hung probe would starve the job a paying customer is waiting on, "
            "hourly, forever. Not derived from vendor_balance_timeout_s either — the job also "
            "queries the database, and a derived ceiling would silently tighten the moment "
            "somebody lowered the HTTP timeout."
        ),
    )
    vendor_balance_estimate_window_days: int = Field(
        default=30,
        ge=1,
        le=365,
        description=(
            "Trailing window the per-song divisor behind 'songs remaining' is measured over: "
            "vendor spend (or billed characters) attributed to orders delivered in this "
            "window, divided by those orders. 30 days because shorter lets a quiet week "
            "produce a divisor from three orders and longer averages across a rate-card "
            "change. Bounded so a typo cannot put a full scan of the largest table in the "
            "schema on an hourly cron."
        ),
    )

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

    #: What the CHECKOUT quotes, as distinct from ``kit_price_amount_minor``, which is what
    #: the RENDER gate is quoted at. They are the same number today and are allowed to
    #: diverge — the render gate's amount is what a future ``PaymentProvider`` authorises per
    #: order, while these are what a customer sees on a button before any order exists.
    #:
    #: Minor units throughout (UZS tiyin, exponent 2), because that is already what
    #: ``PaymentAuthorization.amount_minor`` carries and already what Payme quotes. Storing
    #: 7000 here and multiplying by 100 at the rail is how a rounding bug becomes a pricing
    #: bug, and a pricing bug is invisible until somebody has been charged the wrong amount.
    #: ``bayram.bot.pricing.format_amount`` divides back down for display; nothing else does.
    single_song_price_minor: int = Field(
        default=1_500_000,
        ge=0,
        description="One render, in minor units (UZS tiyin). 1_500_000 == 15 000 soʻm.",
    )
    #: The plan's price is KEPT even though the plan is not offered — see
    #: :attr:`is_starter_plan_offered`. Zeroing it to express "not for sale" would make a plan
    #: FREE to anyone holding a checkout link minted before the switch, which is the one
    #: failure a price field must not have; the offer is withdrawn by the boolean instead.
    starter_plan_price_minor: int = Field(
        default=4_900_000,
        ge=0,
        description="The starter plan, in minor units. 4_900_000 == 49 000 soʻm.",
    )
    #: Whether the twelve-song starter plan is part of the catalogue at all.
    #:
    #: **Ships False: the owner withdrew the plan on 2026-09-14, leaving the single song as
    #: the only product.** This is a catalogue decision, not a rail one — the plan's code
    #: path, its price, its fulfiller and its `plan_purchases` rows all remain, because
    #: customers who already bought one still have a running plan that must keep minting and
    #: a receipt that must keep reading back. What this turns off is the BUTTON.
    #:
    #: `False` therefore means "sell no new plans", never "forget the plans that exist".
    #: :func:`bayram.bot.handlers.balance` ANDs it with "no plan is already running", so the
    #: two reasons a plan is not offered stay distinguishable in the code that decides it.
    is_starter_plan_offered: bool = Field(
        default=False,
        description="Draw the starter-plan button. False sells single songs only.",
    )
    #: The plan is "twelve songs within thirty days", and both halves are configuration
    #: because both are quoted on the button and in the paywall copy. They are bounded rather
    #: than open: a plan of 0 songs is a product that cannot be delivered, and a plan longer
    #: than a year outlives the retention window its receipt is kept under.
    starter_plan_songs: int = Field(
        default=12,
        ge=1,
        le=1_000,
        description="Songs the starter plan mints, lazily, one per render.",
    )
    starter_plan_days: int = Field(
        default=30,
        ge=1,
        le=365,
        description="How long the starter plan keeps minting, from the instant it is bought.",
    )

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
    #: ``bayram.db.credits.charge`` still opens the account, mints the rolling allowance, runs
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

    #: Songs given away per rolling 30-day window, before anybody pays for anything.
    #:
    #: **Ships 0, and the 0 is the product decision, not a conservative default.** The free
    #: half of this product is the LYRIC: the wizard writes it, shows it and lets the customer
    #: keep it without charging. The recording is what is sold. A non-zero allowance here
    #: means the pay and subscribe buttons do not appear at all until the allowance is spent,
    #: so the first customers of a paywalled deployment would meet a screen that says nothing
    #: about price and then, three songs later, a screen that does — which is not the product
    #: and is not something a customer can be told in advance.
    #:
    #: It moved out of ``EntitlementPolicy``'s dataclass default (still 3) rather than
    #: changing it, because ``DEFAULT_ENTITLEMENT_POLICY`` is what every caller with no
    #: settings object in hand uses — the data layer's own tests and the sweep's fallback.
    #: Only ``resolve_entitlement_policy`` reads this field, so only a deployment that
    #: actually has ``Settings`` is repriced.
    #:
    #: **That last sentence cost the admin panel a bug, so read it precisely.** The panel
    #: cannot import :mod:`bayram.config` at all, and it used to be listed here as a caller that
    #: legitimately took the dataclass default. It is not one: it projects a balance a
    #: customer is shown, so it must arrive at the SAME number this setting resolves to, and
    #: while it defaulted the allowance it added 3 credits to every account forever — a
    #: permanent overstatement, because a 0 allowance never stamps an allowance period and so
    #: never stops being due. It now mirrors this value as ``admin_free_allowance_credits``
    #: (:mod:`bayram.admin.settings`) and must be moved with it.
    #:
    #: 0 is a valid policy and not a degenerate one: ``EntitlementPolicy.__post_init__``
    #: refuses only negatives, and 0 makes ``bayram.db.credits._mint_due_allowance`` return
    #: immediately, which is exactly "every song is sold".
    free_allowance_credits: int = Field(
        default=0,
        ge=0,
        le=100,
        description=(
            "Free songs granted per rolling window. 0 since the paywall shipped: the lyric "
            "is the free half of the product."
        ),
    )

    #: How long a debit may sit unsettled before the in-flight cap stops counting it and the
    #: stale-debit sweep may close it.
    #:
    #: ``None`` — the shipped value — means DERIVE it from this deployment's own queue
    #: ladder: ``queue_job_timeout_s * queue_max_tries`` plus every ``provider_backoff_base_s``
    #: deferral in between (see ``bayram.entitlements.derive_settlement_grace_s``). That is
    #: deliberately not a fixed number: a fixed hour is shorter than the 4500s of job
    #: timeouts arq alone will spend on one order under the shipped defaults, and a grace
    #: under the ladder makes the sweep refund orders that are still rendering — the customer
    #: keeps the credit AND gets the song. Raising ``BAYRAM_QUEUE_JOB_TIMEOUT_S`` therefore moves
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
    #: deliberate — see ``bayram.ratelimit`` — because what this bounds is one human's tap rate,
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
    #: bounded, observable number. See ``bayram.lyric_budget``.
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

    # THE SUPPORT GROUP IS NOT A SETTING. ``support_group_chat_id`` and
    # ``support_group_thread_id`` stood here until 2026-09-15 and were REMOVED — not renamed,
    # not deprecated, not kept as a fallback. The Telegram group that receives ticket cards is
    # now a row in ``bot_chats`` selected from the admin panel: SUPPORT_TICKETS_SPEC §3.8, and
    # the 2026-09-15 amendment to D18. Repointing the staff inbox was a unit-file edit, a
    # redeploy and a bot restart, which is why in practice it never moved.
    #
    # **Do not put either variable back, in any form — seed, pin, default or override.** The
    # database row is the ONLY authority by design. A setting that seeded or overrode the
    # selection would be a second source of truth needing a precedence rule, and the first
    # question asked in every support incident — "which room is this actually posting into?" —
    # would have two answers, one of them invisible to the panel screen that exists to show it.
    # Both fields were added and deleted inside the same day and are deployed nowhere, so
    # nothing here is a compatibility shim: there is no operator to warn and no value to carry.
    #
    # The two readers reach the selection through a port rather than through ``Settings``. The
    # bot resolves it per update, because the group filter is now dynamic: a cached answer keeps
    # claiming messages in a room an operator has just stopped using, and posts the next
    # customer's complaint there. The worker reads it inside the job, after the transaction that
    # chose it has committed. "No group selected" is the same state ``0`` used to mean — the
    # ticket is still written, the customer is still answered, the board still fills, only the
    # group post is skipped — and it remains the shipped default, because an empty table is what
    # a fresh deployment has.
    #
    # :attr:`support_panel_base_url` below STAYS a setting. It is a display string pasted into a
    # URL button, not the group, and nothing selects it.

    #: Base URL of the admin panel, used for one thing: the ``🔗 Open in panel`` URL button on
    #: the group card. Empty is the default and means the button is OMITTED ENTIRELY — not
    #: rendered pointing at a relative path, not pointed at ``localhost``. Telegram validates a
    #: URL button at send time, so a half-configured link is not a dead button but a 400 that
    #: loses the whole card; and a button that opens nothing is the same broken promise
    #: :attr:`support_contact` refuses to make.
    #:
    #: The bot and the worker never *call* the panel — they only paste this string into a
    #: button — so this is a display value, not a service address, and no credential travels
    #: with it.
    support_panel_base_url: str = Field(
        default="",
        description=(
            "Base URL of the admin panel for the ticket card's Open-in-panel button. "
            "Empty omits the button rather than linking nowhere."
        ),
    )

    # -- terms of use + privacy notice (IMAGE_VIDEO_SPEC §2.1, D26) ---------
    #: The version pair every customer must have accepted, and THE FLAG for the whole gate.
    #: Both empty — the default — means no gate: nothing asks, nothing blocks, and the bot runs
    #: exactly as it did before M1.2. The spec's default until counsel signs the draft text off
    #: (IMAGE_VIDEO_SPEC Q6, M1.3). Setting a pair turns the gate on; changing either value
    #: re-prompts every account, because acceptance is recorded per exact pair
    #: (``terms_acceptances``' UNIQUE). Owner-written, typically a date such as ``2026-10-01``;
    #: 32 characters because that is the column.
    terms_version: str = Field(default="", max_length=32)
    privacy_version: str = Field(default="", max_length=32, validate_default=True)
    #: Optional link to the full text on the web, drawn under the terms screen. Empty: no link.
    terms_url: str = Field(default="", max_length=255)

    # -- media: offering and rail (IMAGE_VIDEO_SPEC §4.5, §7.1, §7.4) ---------
    #: Whether each media SKU is part of the catalogue at all. All three ship **False**: with
    #: them off the ✨ button routes straight to songs and nothing below is read. Turning one
    #: on is checked at boot by ``bayram.media.boot`` — a free rail needs the beta flag and
    #: a non-empty allowlist, an offered SKU needs a price and a margin (§7.4).
    is_image_offered: bool = Field(default=False)
    is_video_standard_offered: bool = Field(default=False)
    #: The Higgsfield tier (O2, D22). Off until M6.
    is_video_fast_offered: bool = Field(default=False)
    #: The free beta (O9, O12): on a rail that is not live-paid, media is offered to the
    #: allowlist only, as 🎁, and recorded ``paid_via='beta'``. No effect on a live-paid rail
    #: beyond a boot warning — beta ends at live-paid (§2.5).
    media_beta_enabled: bool = Field(default=False)
    #: Telegram ids, comma-separated. Admins are listed explicitly; the bot does not know
    #: panel roles (§2.5).
    media_beta_allowlist: Annotated[tuple[int, ...], NoDecode] = Field(default=())
    #: The env backend per SKU. A Redis override (``media:backend:<sku>``) wins for new
    #: submits; the effective backend is stamped on ``media_jobs.backend`` (§4.5).
    image_backend: MediaBackendName = Field(default="local")
    video_standard_backend: MediaBackendName = Field(default="local")
    video_fast_backend: MediaBackendName = Field(default="higgsfield")
    #: Where a SKU's job moves when its backend refuses a submit BEFORE anything was created
    #: there — unavailable, quota, rate-limited, a 502 with no job id — and nothing of the
    #: job was ever posted (IMAGE_VIDEO_SPEC §3.3, §4.1). Never after an ambiguous submit.
    #: Empty (the default) = no fallback: the job retries on its own backend. A configured
    #: fallback for an offered SKU is held to the same boot checks as its backend (§4.5).
    image_fallback_backend: MediaBackendName | None = Field(default=None)
    video_standard_fallback_backend: MediaBackendName | None = Field(default=None)
    video_fast_fallback_backend: MediaBackendName | None = Field(default=None)
    #: Prices in minor units (UZS tiyin), hand-set per currency, no FX (§7.1). ``None`` —
    #: an empty variable — means "not sellable", and an offered SKU with no price refuses to
    #: boot. 500_000 == 5 000 soʻm for ONE request yielding two images (O5).
    image_price_minor: int | None = Field(default=500_000, gt=0)
    #: 2_500_000 == 25 000 soʻm (owner, 2026-09-24): ~17.5 GPU-minutes and a long wait,
    #: priced above the song.
    video_standard_price_minor: int | None = Field(default=2_500_000, gt=0)
    #: Unset until M6; 35 000–45 000 soʻm recommended (§7.1).
    video_fast_price_minor: int | None = Field(default=None, gt=0)
    #: The per-request cash cost of a backend may be at most this share of the SKU's price
    #: net of the Payme fee, or the SKU is not offered on it (§4.3 margin check).
    media_max_cost_share: float = Field(default=0.5, gt=0.0, le=1.0)
    #: UZS per USD, for the margin check only. **Unset is safe for the local backend**, whose
    #: cash cost is zero; a SKU on a backend that costs money refuses to boot without it,
    #: because a margin cannot be proved in two currencies with no rate between them. The
    #: admin panel's ``BAYRAM_ADMIN_UZS_PER_USD`` lives in another process's dotenv (D19).
    media_uzs_per_usd: float | None = Field(default=None, gt=0, le=1_000_000)
    #: Photos a customer may attach to one request (§1.3). A 1-ref backend gets a collage,
    #: whose layouts stop at four (§4.4, ``media.composite.MAX_COLLAGE_PHOTOS``).
    media_max_reference_images: int = Field(default=4, ge=0, le=4)
    #: ``gateway`` screens on the owner's 5090 (D24, M3); ``fake`` allows everything and is
    #: for tests — boot refuses it with any SKU offered unless ``use_fake_providers`` (§4.5).
    media_moderator: MediaModeratorName = Field(default="gateway")
    #: Where the guards (G1–G3, G8) answer. Empty means ``genai_base_url``: they run on the
    #: same 5090. A hosted endpoint serving the same contract is the D24 fallback (§6.2).
    #: On the gateway's own host the gateway's key and Access token are used; on any OTHER
    #: host only the three ``media_moderator_*`` credentials below are, so the 5090's key is
    #: never handed to a third party (``moderation.factory.guard_credentials``).
    media_moderator_base_url: str = Field(default="", max_length=255)
    #: The hosted guard endpoint's key, sent as the same header. Required (boot) when
    #: ``media_moderator_base_url`` is on another host than ``genai_base_url``. Secret.
    media_moderator_api_key: str = Field(default="")
    #: An optional Cloudflare Access service token in front of that endpoint; both or neither.
    media_moderator_access_client_id: str = Field(default="", max_length=128)
    media_moderator_access_client_secret: str = Field(default="")
    #: How G1 is reached (§6.5): ``moderate`` is the dedicated ``POST /v1/moderate/text``;
    #: ``chat`` is the interim — Qwen3Guard exposed on ``/v1/chat/completions`` and its
    #: ``Safety: … / Categories: …`` text parsed strictly by us.
    media_guard_text_route: Literal["moderate", "chat"] = Field(default="moderate")
    #: One guard call. G7 asks for ≤ 10 s p95 while Wan renders; past this it is
    #: ``unavailable`` — ``media.busy`` before payment (§6.4).
    media_guard_timeout_s: float = Field(default=15.0, gt=0.0, le=120.0)
    #: Zero-tolerance nudity (§6.4): ShieldGemma's ``sexually_explicit`` at or above this on
    #: ANY image blocks, whatever else is known. Low and fixed until M3.3 recalibrates it.
    media_sexual_image_block_p: float = Field(default=0.2, gt=0.0, lt=1.0)
    #: Screenings one account may run per UTC day (§6.4 L0): a guard that answers without
    #: limit is an oracle for probing the policy. Over it the request is refused unscreened.
    media_screen_daily_budget: int = Field(default=10, ge=1, le=1_000)
    #: PAID requests (Payme, 🎟 credit or 🎁 beta) one account may start per UTC day, per kind
    #: (§7.6). Counted from ``media_jobs.paid_at``, so a restart cannot reset it; checked
    #: before a quote is drawn and again at every pay/credit/beta press.
    media_daily_cap_image: int = Field(default=10, ge=1, le=1_000)
    media_daily_cap_video: int = Field(default=3, ge=1, le=1_000)
    #: The escalation owner's X25519 PUBLIC key, base64 (§6.7). CSAM-class bytes are sealed
    #: to it; only the matching private key — held by the owner, never by this host — opens
    #: them (``python -m bayram.tools.legal_hold``). Not a secret. Required with media offered.
    media_legal_hold_recipient: str = Field(default="", max_length=64)

    # -- media: the stage chain (IMAGE_VIDEO_SPEC §3.3–§3.5) ------------------
    #: How long a frozen, unpaid request (``drafting``/``screening``/``quoted``) lives before
    #: ``media_sweep`` abandons it and ``media_cleanup`` deletes its uploads (§2.6, §3.5).
    media_quote_ttl_s: int = Field(default=86_400, ge=600, le=7 * 86_400)
    #: Paid → delivered, per SKU (§3.5). Past it the job fails and, if it was paid for, one
    #: SKU-scoped credit is granted. Every ETA shown at quote must fit inside it (NFR-20).
    media_image_deadline_s: int = Field(default=2_700, ge=300, le=86_400)
    media_video_standard_deadline_s: int = Field(default=14_400, ge=600, le=86_400)
    media_video_fast_deadline_s: int = Field(default=1_800, ge=300, le=86_400)
    #: Generation attempts per variant on the same backend (§3.3 "Retries"). An ambiguous
    #: attempt counts as one, so a second ``unknown`` ends the variant (§4.2).
    media_max_attempts: int = Field(default=2, ge=1, le=5)
    #: Counted from the gateway reporting ``running`` only — queue time is not render time
    #: (§3.5). Past it the attempt is ``failed`` and the retry policy decides.
    media_image_render_timeout_s: int = Field(default=300, ge=30, le=3_600)
    media_video_render_timeout_s: int = Field(default=2_400, ge=60, le=7_200)
    #: Sampler steps sent to the gateway; always explicit (§4.2). 25 is the step count the
    #: 31–43 s flux2 measurement was taken at.
    media_image_steps: int = Field(default=25, ge=1, le=100)
    media_video_steps: int = Field(default=20, ge=1, le=100)
    #: img2img strength for a request with photos (§1.3): 0.5–0.7 keeps the subject.
    media_image_denoise: float = Field(default=0.6, gt=0.0, le=1.0)
    #: Days a delivered image or video (and its ``tg_file_id``) is kept, and the words of a
    #: finished request (§3.2.4, §9.3). Open question Q2, so tunable; ``/forget`` ends it
    #: sooner. Read through ``bayram.db.retention.resolve_retention_policy``.
    retention_media_output_days: int = Field(default=30, ge=1, le=3_650)

    # -- media: video narration (IMAGE_VIDEO_SPEC §2.4.2, §5.3, §5.4; O14, D23) -------
    #: The clip length, and so the longest narration: text we accept before payment must be
    #: speakable in it, and an own voice note longer than it (+0.25 s, §5.4) is refused.
    narration_max_seconds: int = Field(default=5, ge=1, le=10)
    #: Per-language word and character budgets under the owner's ~12-word ceiling (O14).
    #: Starting points, calibrated in the M4.4 listening test. Uzbek covers both scripts.
    narration_max_words_uz: int = Field(default=8, ge=1, le=12)
    narration_max_words_ru: int = Field(default=10, ge=1, le=12)
    narration_max_words_en: int = Field(default=12, ge=1, le=12)
    #: ``media_jobs.narration_text`` is varchar(160); a budget cannot exceed its column.
    narration_max_chars_uz: int = Field(default=60, ge=10, le=160)
    narration_max_chars_ru: int = Field(default=70, ge=10, le=160)
    narration_max_chars_en: int = Field(default=80, ge=10, le=160)
    #: 🔄 regenerations of an LLM-written line per draft (§2.4.2); each costs a screening.
    media_script_max_regens: int = Field(default=2, ge=0, le=5)

    # -- media: narration voice (IMAGE_VIDEO_SPEC §5.1, §5.2; O8, D23) ------------------
    #: Off sends every line to the fallback (ElevenLabs) without touching the pool.
    gemini_tts_enabled: bool = Field(default=True)
    #: The owner's key pool, comma-separated. Secret — see VENDOR_SECRET_FIELDS. Keys are
    #: named everywhere by ``sha256(key)[:8]`` and never logged. No paid-tier gate (Q17):
    #: free-tier keys serve every job. Empty narrates through the fallback. A plain string
    #: rather than a tuple so it reads like every other secret (``""`` is unset); split it
    #: with :attr:`gemini_tts_key_list`.
    gemini_tts_api_keys: str = Field(default="")
    gemini_tts_model: str = Field(default="gemini-3.8-flash-tts", min_length=1, max_length=64)
    #: Two of the 30 prebuilt voices, chosen in the M4 listening test (Q14). A gender with
    #: no voice here is spoken by the fallback.
    gemini_tts_voice_female: str = Field(default="", max_length=32)
    gemini_tts_voice_male: str = Field(default="", max_length=32)
    #: The narration route table in ``parse_routes`` form; empty is every language to
    #: ``gemini_tts``. Separate from ``tts_routes``: songs keep theirs.
    narration_routes: str = Field(default="")
    #: What speaks when the routed provider cannot (pool exhausted, no voice, outage). A
    #: content refusal is never offered to it (§5.2).
    narration_fallback: str = Field(default="elevenlabs_tts", max_length=32)

    # -- the local generation gateway (IMAGE_VIDEO_SPEC §4.2, §9.1) ----------
    #: HTTPS through the tunnel (§9.1). Empty with a SKU offered on ``local`` refuses to boot.
    genai_base_url: str = Field(default="", max_length=255)
    #: Sent as a header only, never ``?api_key=`` (§4.2). Secret — see VENDOR_SECRET_FIELDS.
    genai_api_key: str = Field(default="")
    #: The Cloudflare Access service token for the tunnel in front of the gateway (§9.1 item 2),
    #: sent as ``CF-Access-Client-Id`` / ``CF-Access-Client-Secret`` headers. Both or neither:
    #: boot refuses one without the other. Empty is a gateway with no Access policy, which
    #: ``python -m bayram.tools.media doctor`` reports as a warning (12-media-gateway §2.4).
    genai_access_client_id: str = Field(default="", max_length=128)
    genai_access_client_secret: str = Field(default="")
    #: Must be members of ``LOCAL_MODEL_ALLOWLIST`` (flux2, wan); boot refuses anything else,
    #: so ``zootopia``, ``storybook`` and ``hunyuan`` are unreachable from bayram (§1.2).
    genai_image_model: str = Field(default="flux2", min_length=1, max_length=32)
    genai_video_model: str = Field(default="wan", min_length=1, max_length=32)
    #: The model the 🤖 "AI writes" line is asked of on the gateway's
    #: ``/v1/chat/completions`` (IMAGE_VIDEO_SPEC §5.5). A local model only: a ``:cloud`` tag
    #: would send the customer's prompt off the box, so it is refused here.
    genai_script_model: str = Field(default="qwen3.8:27b-q4_K_M", min_length=1, max_length=64)
    #: How long the gateway may take to write a line before the D5 LLM stack is asked
    #: instead (§5.5: "unavailable or busy > 20 s"). A Wan render holds the GPU for minutes.
    genai_script_timeout_s: float = Field(default=20.0, gt=0.0, le=120.0)

    # -- Higgsfield: the Fast tier and D21's paid image fallback (IMAGE_VIDEO_SPEC §4.3) ----
    #: The REST platform. Only this host ever receives the ``Authorization`` header.
    higgsfield_base_url: str = Field(default="https://platform.higgsfield.ai", max_length=255)
    #: ``Authorization: Key <id>:<secret>``. The id is not secret; the secret is (see
    #: VENDOR_SECRET_FIELDS). Both are required, at boot, for a SKU offered on ``higgsfield``.
    higgsfield_api_key_id: str = Field(default="", max_length=128)
    higgsfield_api_secret: str = Field(default="")
    #: Keys of ``providers.media.higgsfield.HIGGSFIELD_MODELS``; boot refuses anything else.
    #: Kling 3.0 standard is the Fast tier's default (§4.3).
    higgsfield_image_model: str = Field(default="soul_standard", min_length=1, max_length=32)
    higgsfield_video_model: str = Field(default="kling3_0_std", min_length=1, max_length=32)
    #: USD per Higgsfield credit, for an ``/estimate`` that answers in credits. Unset, such an
    #: estimate is "unknown" and the submit is refused — never read as free.
    higgsfield_usd_per_credit: float | None = Field(default=None, gt=0.0, le=10.0)
    #: The static per-output figures the boot margin check reads (§4.3 "from ``/estimate`` or
    #: the static table"): boot does no IO, so the operator records the measured
    #: ``/estimate`` here. Unset, a SKU on ``higgsfield`` refuses to boot — no known cost.
    higgsfield_image_usd_per_output: float | None = Field(default=None, gt=0.0, le=100.0)
    higgsfield_video_usd_per_output: float | None = Field(default=None, gt=0.0, le=100.0)
    #: Per-REQUEST hard ceilings covering every variant and every retry (§4.3): the image
    #: figure is both images × all attempts. The stage chain sums each attempt's estimate
    #: against it before the POST; an attempt that would cross it is never posted.
    image_max_cost_usd: float = Field(default=0.20, gt=0.0, le=100.0)
    video_fast_max_cost_usd: float = Field(default=1.00, gt=0.0, le=100.0)
    #: Standard is a GPU tier and has no paid ceiling unless one is set here: unset, boot
    #: refuses a Standard route onto a paid backend, and a runtime override onto one is
    #: quoted ``busy`` and never posted (§4.3).
    video_standard_max_cost_usd: float | None = Field(default=None, gt=0.0, le=100.0)

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

    # -- outbound pacing (broadcasts, and every fan-out after them) ---------
    #: HOW FAST THIS DEPLOYMENT MAY TALK TO TELEGRAM, across every worker process.
    #:
    #: Telegram publishes ~30 messages/second to *different* chats as the point at which a
    #: bot starts being rate limited (and 20/minute into one group; a broadcast sends one
    #: message per account, so only the first applies). That figure is a soft threshold the
    #: API documents in prose, not a contract, and exceeding it earns a ``retry_after`` on
    #: the BOT TOKEN — which stops the orders, not merely the campaign.
    #:
    #: Twelve, therefore: NFR-23 caps reminders **plus** broadcasts together at half of the
    #: published ceiling, and twelve sits under that half with headroom for the reminder
    #: fan-out that shares the same Redis bucket by name (``bayram.runtime.pacer``). The cost
    #: of being wrong upwards is an outage of the paid product; the cost of being wrong
    #: downwards is that a 50 000-recipient campaign takes 70 minutes instead of 45.
    #:
    #: Capped at 30 rather than left open: a number above the published ceiling is not a
    #: tuning choice, it is a flood wait with extra steps.
    broadcast_send_rate_per_s: int = Field(
        default=12,
        ge=1,
        le=30,
        description=(
            "Outbound Telegram messages per second, shared across all worker processes "
            "through Redis. Telegram limits at ~30/s per bot token; this stays well under."
        ),
    )

    #: HOW LONG ONE SEND CHUNK MAY HOLD A WORKER SLOT.
    #:
    #: Its own knob and deliberately not ``queue_job_timeout_s``: 900 seconds is sized for a
    #: music render, and a campaign is 250 chunks — a chunk that could hold one of fifteen
    #: slots for a quarter of an hour would starve the paying customer queued behind it, 250
    #: times. At the shipped rate a 200-message chunk is under twenty seconds of sending, so
    #: 120 leaves room for a slow Telegram without ever being the normal case.
    #:
    #: **The timeout is a cancellation and the cancellation is not free.** ARQ cancels the
    #: coroutine, which leaves whatever rows it had claimed in ``sending`` — counted as
    #: neither sent nor failed until the sweep ages them to ``unknown``. That is the correct
    #: trade (a message sent twice is worse than a hole in a counter) and it is also why this
    #: number should not be tuned downwards to "keep chunks snappy": every cancellation buys
    #: an unresolved row.
    broadcast_chunk_timeout_s: float = Field(
        default=120.0,
        gt=0,
        description=(
            "Seconds one broadcast send chunk may run before arq cancels it. A cancelled "
            "chunk leaves its claimed rows unresolved, so this is not a knob to shorten."
        ),
    )
    #: HOW LONG A CLAIMED RECIPIENT MAY SIT IN ``sending`` BEFORE IT IS WRITTEN OFF.
    #:
    #: A row moves to ``sending`` and is committed *before* the message leaves, so a job
    #: killed between the two leaves a row nobody can classify: it may or may not have
    #: reached Telegram. It is never retried — that is the never-double-send rule — and after
    #: this lease the sweep retires it to ``unknown``, where the panel shows it as its own
    #: number rather than folding it into "failed".
    #:
    #: Five minutes: comfortably longer than :attr:`broadcast_chunk_timeout_s`, so a chunk
    #: that is merely slow is never written off underneath itself, and short enough that a
    #: campaign whose last worker died finishes within a sweep or two instead of hanging on
    #: ``outstanding > 0`` forever. The same number bounds "this campaign has stalled" in the
    #: due sweep, because it is the same question asked of the row above the recipients.
    broadcast_sending_lease_s: float = Field(
        default=300.0,
        gt=0,
        description=(
            "Seconds a claimed recipient may stay 'sending' before the sweep retires it to "
            "'unknown'. Must exceed BAYRAM_BROADCAST_CHUNK_TIMEOUT_S."
        ),
    )

    # -- checkout rail (Payme) ----------------------------------------------
    #: WHICH RAIL SELLS A CREDIT. Ships ``"stub"``, and the default is the shipped
    #: configuration rather than a conservative placeholder: with it, production behaviour is
    #: byte-identical to what it was before any of this landed. ``StubCheckoutProvider`` stays
    #: wired, stays constructed and stays under test whatever this says, so the rollback from
    #: a live rail is this value plus one restart and nothing else (DECISIONS.md D11).
    #:
    #: A ``Literal`` and not a ``str``, so a typo is a named boot failure — ``BAYRAM_CHECKOUT_
    #: PROVIDER: Input should be 'stub' or 'payme'`` — rather than a container that silently
    #: falls through to the stub and sells nothing while the operator watches for orders.
    checkout_provider: CheckoutRail = Field(
        default="stub",
        description="stub | payme. Flip to payme WITH credits_enforced; see bayram.main's refusal.",
    )
    #: The cashbox id, from Кассы -> the kassa -> Настройки -> Инструменты разработчика.
    #:
    #: **Public by design, and that is why it is on THIS model.** It is rendered inside a
    #: base64 blob in a URL a customer's browser opens, so it is neither a credential nor
    #: secret-shaped, and the bot needs it because the BOT is what builds the link. The
    #: Merchant API KEY is a different animal entirely — an inbound verification secret held
    #: by one process — and is deliberately not a field here at all; see
    #: :data:`FOREIGN_SECRET_ENV_VARS`.
    #:
    #: Blank is allowed so that a deployment on the stub boots with no Payme configuration
    #: whatsoever. The refusal happens where the rail is BUILT, in
    #: ``bayram.runtime.container._build_checkout``, which is the ``build_llm_provider``
    #: precedent: a credential is required by the thing that needs it, not by every boot.
    payme_merchant_id: str = Field(default="", max_length=64)
    #: An override for the checkout host. Blank derives it: ``https://checkout.paycom.uz`` in
    #: production, ``https://test.paycom.uz`` when :attr:`payme_is_sandbox`. It exists because
    #: Payme has moved this hostname before and a rail that can only be repointed by a release
    #: is a rail that is down for as long as a release takes.
    payme_checkout_base_url: str = Field(default="", max_length=255)
    #: The account subfield name inside the link (``ac.<field>``). **It must equal the
    #: cabinet's «Настройка Аккаунт» field name exactly**, and that is configured by a human in
    #: a web form no API can read. A mismatch makes every ``CheckPerformTransaction`` a
    #: ``-31050`` that looks like our bug, which is why the gateway's ``-31050`` log line names
    #: the fields it actually received alongside this one.
    payme_account_field: str = Field(default="order_id", min_length=1, max_length=32)
    #: Where Payme sends the customer after paying. **Blank is the default and blank is safe**:
    #: settlement is webhook-driven and depends on nothing the customer does, so an absent
    #: return URL is a fully working payment. A ``;`` anywhere in it is REFUSED below.
    payme_return_url: str = Field(default="", max_length=255)
    #: Whether links are built against the rail's test environment. Stamped onto every intent,
    #: so rehearsal rows are excludable from every revenue figure by construction rather than
    #: by remembering which week the sandbox was in use.
    #:
    #: **Defaults to True**, which is the opposite of most flags here and is deliberate: the
    #: failure mode of an accidental ``true`` in production is a link that does not charge
    #: anybody, and the failure mode of an accidental ``false`` in a rehearsal is a real card
    #: charged for a test. Only one of those needs a refund.
    payme_is_sandbox: bool = Field(default=True)
    #: How long an issued checkout link stays payable, in seconds. 12 hours by default, which
    #: matches Payme's own transaction window.
    #:
    #: Bounded ``60..86_400`` for this rail's own coherence: under a minute is not a product,
    #: and a link valid for longer than the 12-hour transaction it can open is a link whose
    #: second half is a promise the rail will not keep. **The bound that actually matters is not
    #: expressible here** — this must be strictly less than the wizard-state TTL, or a customer
    #: could pay for a draft that has already expired — because that number lives in
    #: ``bayram.bot.app``, which imports this module. ``bayram.main`` asserts it at boot
    #: instead, and the two checks are not redundant: this one is about the rail, that one is
    #: about two subsystems' clocks agreeing.
    payme_intent_ttl_s: int = Field(default=43_200, ge=60, le=86_400)
    #: Whether a settled REDIRECT payment starts the render it was opened for.
    #:
    #: ``False`` restores, exactly, the behaviour that shipped before ``DECISIONS.md D17``:
    #: the customer is told their payment landed and presses 🎬 themselves. It is the rollback
    #: lever for that decision, and it is an environment variable rather than a code change
    #: precisely so the rollback needs a restart and not a deploy — which is what this
    #: repository's decision format asks a fallback to be.
    #:
    #: **No effect on a stub deployment**, and therefore no blast radius on one: the pending
    #: branch that records a render marker is unreachable when ``charge`` reports the purchase
    #: already paid, so nothing is ever recorded and nothing is ever resumed. Default ``True``
    #: for that reason — the feature is off by construction everywhere it was not wanted.
    auto_render_on_payment: bool = Field(default=True)
    #: How often the worker's Payme sweep runs, in minutes.
    #:
    #: A BACKSTOP, not a mechanism: intent expiry is a predicate evaluated against the injected
    #: clock whenever a request forces the state machine to move, so no correctness property
    #: waits for this. The one arm that is genuinely about delivery is the re-enqueue of unsent
    #: "your payment went through" messages, which makes this number the ceiling on how long a
    #: paying customer can be left unnotified after a Redis outage at settlement time. That is
    #: customer-facing, which is why it is a setting and not a constant.
    payme_sweep_minutes: int = Field(default=5, ge=1, le=60)

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

    @field_validator("genai_script_model")
    @classmethod
    def _script_model_must_be_local(cls, value: str) -> str:
        # IMAGE_VIDEO_SPEC §5.5: the script model sits in its own local-only allowlist; a
        # ``:cloud`` model is served by a third party and would carry the prompt with it.
        if value.strip().lower().endswith(":cloud"):
            raise ValueError("genai_script_model must be a local model, not a ':cloud' one")
        return value.strip()

    @field_validator("supported_languages")
    @classmethod
    def _languages_must_be_unique(cls, value: tuple[Language, ...]) -> tuple[Language, ...]:
        if len(set(value)) != len(value):
            raise ValueError(f"duplicate entries in supported_languages: {value}")
        return value

    @field_validator("payme_return_url")
    @classmethod
    def _return_url_must_not_truncate_the_link(cls, value: str) -> str:
        """Refuse a ``;`` in the return URL, because Payme's parser eats it silently.

        The checkout link is ``base64('key=value;key=value;…')`` and ``;`` is the separator.
        A ``;`` inside a VALUE is not escaped and is not rejected — verified against Payme's
        own sandbox parser, which simply truncates the value there and carries on. So a return
        URL containing one produces a link that Payme accepts, a payment that succeeds, and a
        customer redirected to half an address. Nothing observes that, which is exactly why it
        has to be refused at settings-build time: this is the last point at which the mistake
        is still cheap and still attributable.

        Percent-encoding is NOT the fix and must not be attempted here: the parser does not
        decode, so ``%3B`` would arrive as the literal three characters. The value is passed
        raw and the only safe answer is to forbid the character.
        """
        if ";" in value:
            raise ValueError(
                "must not contain ';' — Payme's link parser truncates a value at the first "
                "one, silently, producing a payment that works and a redirect that does not"
            )
        return value

    @field_validator("terms_version")
    @classmethod
    def _terms_version_is_stripped(cls, value: str) -> str:
        """``"2026-10-01 "`` is ``"2026-10-01"``: a trailing space from a hand-edited ``.env``
        would otherwise be recorded on every acceptance and compared on every read."""
        return value.strip()

    @field_validator("privacy_version")
    @classmethod
    def _terms_versions_come_as_a_pair(cls, value: str, info: Any) -> str:
        """Both versions or neither. One alone is a half-switched gate.

        A Terms version with no Privacy version would record acceptances of a pair with an
        empty half — a lawful-basis record that names no notice — and the reverse would gate on
        a document nobody versioned. Refused at boot, where the mistake is still attributable.
        """
        terms = str(info.data.get("terms_version") or "").strip()
        if bool(terms) != bool(value.strip()):
            raise ValueError(
                "BAYRAM_TERMS_VERSION and BAYRAM_PRIVACY_VERSION are set together or not at all"
            )
        return value.strip()

    @property
    def is_terms_gate_enabled(self) -> bool:
        """Whether the Terms + Privacy gate asks anyone anything (IMAGE_VIDEO_SPEC §2.1)."""
        return bool(self.terms_version.strip())

    @field_validator(
        "image_price_minor",
        "video_standard_price_minor",
        "video_fast_price_minor",
        "image_fallback_backend",
        "video_standard_fallback_backend",
        "video_fast_fallback_backend",
        "media_uzs_per_usd",
        "higgsfield_usd_per_credit",
        "higgsfield_image_usd_per_output",
        "higgsfield_video_usd_per_output",
        "video_standard_max_cost_usd",
        mode="before",
    )
    @classmethod
    def _blank_is_unset(cls, value: Any) -> Any:
        """``BAYRAM_VIDEO_FAST_PRICE_MINOR=`` means "not sellable", as ``.env.example`` ships it.

        pydantic would otherwise try to parse the empty string as a number and refuse to
        boot on the documented spelling of "unset".
        """
        if isinstance(value, str) and not value.strip():
            return None
        return value

    @field_validator("media_beta_allowlist", mode="before")
    @classmethod
    def _allowlist_from_csv(cls, value: Any) -> Any:
        return _split_csv(value)

    @field_validator("media_beta_allowlist")
    @classmethod
    def _allowlist_holds_telegram_ids(cls, value: tuple[int, ...]) -> tuple[int, ...]:
        """Positive ids, de-duplicated in order. A 0 or a negative id is a typo, refused here."""
        if any(item <= 0 for item in value):
            raise ValueError("must list positive Telegram user ids")
        return tuple(dict.fromkeys(value))

    @property
    def is_any_media_offered(self) -> bool:
        """Whether any media SKU is in the catalogue (IMAGE_VIDEO_SPEC §4.5)."""
        return self.is_image_offered or self.is_video_standard_offered or self.is_video_fast_offered

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
    def gemini_tts_key_list(self) -> tuple[str, ...]:
        """The pool, split and de-duplicated (IMAGE_VIDEO_SPEC §5.2). Never log the result."""
        return tuple(dict.fromkeys(item for item in _split_csv(self.gemini_tts_api_keys) if item))

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

    The dotenv file is :func:`env_file` — ``.env`` unless ``BAYRAM_ENV_FILE`` names another —
    passed as a default, so a caller that already has an opinion keeps it. That is how every
    test in this suite reads no file at all: ``build_settings({"_env_file": None})``.

    ``require_vendor_secrets=False`` builds the same model with the three vendor
    credentials left optional — for a process that must not hold them at all (the admin
    API) or that is only checking whether a set of values *would* validate. It never
    relaxes anything else, and ``load_settings`` — the path the bot and the worker boot
    through — always passes ``True``.

    Raises ``ConfigError`` and nothing else — callers never see a pydantic exception.
    """
    model = _VendorBoundSettings if require_vendor_secrets else Settings
    values: dict[str, Any] = dict(overrides or {})
    values.setdefault("_env_file", env_file())
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
