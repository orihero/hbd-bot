"""All configuration, in one place, validated at startup.

Two rules this module exists to enforce:

1. **No magic numbers anywhere else.** Timeouts, retry bounds, loudness targets, chunk
   durations and free-tier caps are settings, not literals buried in a worker.
2. **The name-candidate order is CONFIGURATION.** ``name_candidate_order`` is read by the
   name subsystem to rank orthographies. A bake-off result is applied by reordering this
   list in the environment — never by editing code.

``load_settings()`` never raises a pydantic error at a call site: it converts a failure
into a ``ConfigError`` whose operator message names every offending variable.
"""

from __future__ import annotations

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
    "load_settings",
    "get_settings",
    "DEFAULT_NAME_CANDIDATE_ORDER",
    "ENV_PREFIX",
]

ENV_PREFIX: Final[str] = "HBD_"

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
    """Every knob in the system. Immutable once loaded."""

    model_config = SettingsConfigDict(
        env_prefix=ENV_PREFIX,
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        frozen=True,
    )

    # -- runtime ------------------------------------------------------------
    environment: str = Field(default="dev", description="dev | staging | prod")
    log_level: str = Field(default="INFO")
    is_debug: bool = Field(default=False)
    use_fake_providers: bool = Field(
        default=False,
        description=(
            "Swap every vendor adapter for its Fake. No API key is read, nothing is spent, "
            "and the whole app runs offline. Never enable in prod."
        ),
    )

    # -- telegram -----------------------------------------------------------
    telegram_bot_token: str = Field(min_length=1)

    # -- infrastructure -----------------------------------------------------
    database_url: str = Field(min_length=1, description="postgresql+asyncpg://…")
    redis_url: str = Field(default="redis://localhost:6379/0")

    # -- ElevenLabs (music + RU/EN TTS + STT) -------------------------------
    elevenlabs_api_key: str = Field(min_length=1)
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
    llm_api_key: str = Field(min_length=1)
    llm_base_url: str = Field(default="https://openrouter.ai/api/v1")
    llm_model_id: str = Field(default="google/gemma-4-31b-it:free")
    llm_provider: Literal["gemini", "openai"] = Field(
        default="openai",
        description=(
            "Which adapter serves the primary model. OpenRouter is OpenAI-compatible, so it "
            "uses the 'openai' adapter with llm_base_url pointed at it."
        ),
    )
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
    song_length_ms: int = Field(default=120_000, ge=3_000, le=600_000)
    song_body_chunk_duration_ms: int = Field(default=20_000, ge=3_000, le=120_000)
    greeting_min_duration_s: float = Field(default=20.0, gt=0)
    greeting_max_duration_s: float = Field(default=45.0, gt=0)
    greetings_per_kit: int = Field(default=3, ge=1, le=5)

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


def load_settings() -> Settings:
    """Build settings or fail fast with a message that names the offending variables.

    Raises ``ConfigError`` and nothing else — callers never see a pydantic exception.
    """
    try:
        return Settings()  # values come from the environment and .env
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


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Process-wide singleton. Tests should build ``Settings(...)`` directly instead."""
    return load_settings()
