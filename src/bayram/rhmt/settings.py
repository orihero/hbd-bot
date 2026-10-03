"""Configuration model for Rahmat (rhmt.uz / MultiCard) acquiring rail."""

from __future__ import annotations

from typing import Any, Final, Literal

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

from bayram.config import ENV_PREFIX, resolve_env_file
from bayram.rhmt.ports import (
    DEFAULT_RHMT_RETURN_URL,
    RHMT_PROD_BASE_URL,
    RHMT_SANDBOX_BASE_URL,
)

__all__ = [
    "RhmtSettings",
    "RHMT_ENV_FILE",
    "RHMT_ENV_FILE_VAR",
    "build_rhmt_settings",
]

RHMT_ENV_FILE: Final[str] = ".env.rhmt"
RHMT_ENV_FILE_VAR: Final[str] = f"{ENV_PREFIX}RHMT_ENV_FILE"


class RhmtSettings(BaseSettings):
    """Settings required for the Rahmat (rhmt.uz) payment rail.

    Loaded from .env.rhmt (or BAYRAM_RHMT_ENV_FILE).
    """

    model_config = SettingsConfigDict(
        env_prefix=ENV_PREFIX,
        extra="ignore",
        populate_by_name=True,
    )

    rhmt_application_id: str = Field(
        default="",
        max_length=128,
        description="Application ID provided by Rahmat / MultiCard onboarding.",
    )
    rhmt_secret: SecretStr = Field(
        default=SecretStr(""),
        description="API secret key provided by Rahmat (used for auth and webhook verification).",
    )
    rhmt_store_id: int = Field(
        default=0,
        description="Merchant Store ID provided by Rahmat.",
    )
    rhmt_base_url: str = Field(
        default="",
        max_length=255,
        description="Override for Rahmat API base URL. If empty, derived from is_sandbox.",
    )
    rhmt_callback_url: str = Field(
        default="https://pay.bayrambot.uz/rhmt/callback",
        max_length=255,
        description="Our public URL that Rahmat sends payment webhooks to.",
    )
    rhmt_return_url: str = Field(
        default=DEFAULT_RHMT_RETURN_URL,
        max_length=255,
        description="Where customer is returned after completing payment on Rahmat checkout.",
    )
    rhmt_is_sandbox: bool = Field(
        default=True,
        description="Whether to target Rahmat test sandbox (dev-mesh.multicard.uz).",
    )
    rhmt_callback_scheme: Literal["webhooks", "success"] = Field(
        default="webhooks",
        description="Signature scheme: 'webhooks' (sha1) or 'success' (md5).",
    )
    rhmt_intent_ttl_s: int = Field(
        default=43_200,
        ge=60,
        le=86_400,
        description="How long an opened intent stays payable (seconds).",
    )
    rhmt_environment: Literal["dev", "staging", "prod"] = Field(
        default="dev",
        description="Runtime environment tier.",
    )

    @property
    def resolved_base_url(self) -> str:
        if self.rhmt_base_url.strip():
            return self.rhmt_base_url.strip().rstrip("/")
        return RHMT_SANDBOX_BASE_URL if self.rhmt_is_sandbox else RHMT_PROD_BASE_URL

    @classmethod
    def from_env(cls, env_file_override: str | None = None) -> RhmtSettings:
        return build_rhmt_settings(env_file_override=env_file_override)


def build_rhmt_settings(
    env_file_override: str | None = None,
    **kwargs: Any,
) -> RhmtSettings:
    """Build RhmtSettings, locating the appropriate env file if not passed."""
    file_path = env_file_override or resolve_env_file(RHMT_ENV_FILE_VAR, RHMT_ENV_FILE)
    values: dict[str, Any] = {"_env_file": file_path, **kwargs}
    return RhmtSettings(**values)
