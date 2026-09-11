"""Which dotenv file each process reads, and the one security control that follows it.

``BAYRAM_ENV_FILE`` and ``BAYRAM_ADMIN_ENV_FILE`` exist so a production configuration can be
exercised from a development checkout (``ENV=prod make dev``) and so a systemd unit can
point at ``/etc/bayram/bot.env`` — outside the checkout, where a stray ``.env`` cannot be read
by accident. Three claims are worth a test:

* the **default is unchanged**, because every existing checkout depends on it;
* an explicit ``_env_file`` from a caller still wins, because that is how the entire suite
  reads no file at all;
* the admin process's **vendor-credential scan follows the selection**. That last one is the
  reason this module is not just three assertions about a string: the scan reads the file
  itself rather than the built settings — ``AdminSettings`` has no field a vendor key could
  land in, so a key in that file is invisible to the model — and a scan left pointing at
  ``.env.admin`` while pydantic-settings read ``.env.admin.prod`` would clear a host whose
  credentials are sitting in the file that was actually loaded.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path
from typing import Final

import pytest

from bayram.admin.app import _present_vendor_vars
from bayram.admin.settings import (
    ADMIN_ENV_FILE,
    ADMIN_ENV_FILE_VAR,
    admin_env_file,
    build_admin_settings,
)
from bayram.config import ENV_FILE, ENV_FILE_VAR, ENV_PREFIX, build_settings, env_file

_HMAC_KEY: Final[str] = "k" * 48
_APP_DSN: Final[str] = "postgresql+asyncpg://hbd_app:secret@db:5432/hbd"


@pytest.fixture(autouse=True)
def _no_developer_environment(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """No ``BAYRAM_`` variable from the developer's shell reaches a test in this module.

    Including the two this module is about: an operator who exports ``BAYRAM_ENV_FILE`` in
    their own shell would otherwise flip every assertion below.
    """
    for name in tuple(os.environ):
        if name.startswith(ENV_PREFIX):
            monkeypatch.delenv(name, raising=False)
    yield


def _write(path: Path, **values: str) -> Path:
    path.write_text("".join(f"{k}={v}\n" for k, v in values.items()), encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# Resolution
# ---------------------------------------------------------------------------
def test_the_default_files_are_the_ones_every_existing_checkout_already_has() -> None:
    """Nothing set: ``.env`` and ``.env.admin``, exactly as before this knob existed."""
    assert env_file() == ENV_FILE == ".env"
    assert admin_env_file() == ADMIN_ENV_FILE == ".env.admin"


def test_each_variable_selects_its_own_file_and_only_its_own(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Two variables, not one tier name deriving both paths.

    The bot and the admin process reading DIFFERENT files is the whole vendor-key
    separation; a single knob computing both is one edit away from collapsing it.
    """
    # Arrange / Act
    monkeypatch.setenv(ENV_FILE_VAR, ".env.prod")

    # Assert - the admin path did not move with it
    assert env_file() == ".env.prod"
    assert admin_env_file() == ".env.admin"


def test_an_exported_but_empty_variable_falls_back_rather_than_reading_nothing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``BAYRAM_ENV_FILE=`` is what a deploy script's unset interpolation produces.

    Resolving it to the empty path would boot the process on defaults with no dotenv file
    and no complaint — the silent failure this branch exists to avoid.
    """
    # Arrange / Act
    monkeypatch.setenv(ENV_FILE_VAR, "   ")

    # Assert
    assert env_file() == ENV_FILE


# ---------------------------------------------------------------------------
# The settings builders actually read the selected file
# ---------------------------------------------------------------------------
def test_build_settings_reads_the_selected_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A required credential arriving from the file proves it was read, not merely named."""
    # Arrange
    selected = _write(
        tmp_path / ".env.prod",
        BAYRAM_ENVIRONMENT="prod",
        BAYRAM_DATABASE_URL=_APP_DSN,
        BAYRAM_TELEGRAM_BOT_TOKEN="123456:from-the-selected-file",
        BAYRAM_ELEVENLABS_API_KEY="eleven-from-the-selected-file",
        BAYRAM_LLM_API_KEY="llm-from-the-selected-file",
    )
    monkeypatch.setenv(ENV_FILE_VAR, str(selected))

    # Act - vendor secrets required, which is the bot's and the worker's own boot path
    settings = build_settings()

    # Assert
    assert settings.environment == "prod"
    assert settings.is_production is True
    assert settings.telegram_bot_token == "123456:from-the-selected-file"


def test_an_explicit_env_file_from_the_caller_beats_the_variable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``build_settings({"_env_file": None})`` is how every other test reads no file.

    The selection is a *default*, so pointing ``BAYRAM_ENV_FILE`` at a populated file must not
    smuggle values into a test that asked for none.
    """
    # Arrange
    selected = _write(tmp_path / ".env.prod", BAYRAM_ENVIRONMENT="prod", BAYRAM_DATABASE_URL=_APP_DSN)
    monkeypatch.setenv(ENV_FILE_VAR, str(selected))

    # Act
    settings = build_settings(
        {"_env_file": None, "database_url": _APP_DSN}, require_vendor_secrets=False
    )

    # Assert - the default, not the "prod" sitting in the file the variable named
    assert settings.environment == "dev"


def test_build_admin_settings_reads_the_selected_admin_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Arrange
    selected = _write(
        tmp_path / ".env.admin.prod",
        BAYRAM_ENVIRONMENT="prod",
        BAYRAM_DATABASE_URL=_APP_DSN,
        BAYRAM_ADMIN_ENABLED="true",
        BAYRAM_ADMIN_PUBLIC_ORIGIN="https://panel.example.com",
        BAYRAM_ADMIN_AUDIT_HMAC_KEY=_HMAC_KEY,
    )
    monkeypatch.setenv(ADMIN_ENV_FILE_VAR, str(selected))

    # Act
    settings = build_admin_settings()

    # Assert
    assert settings.is_production is True
    assert settings.admin_enabled is True
    assert settings.admin_public_origin == "https://panel.example.com"


# ---------------------------------------------------------------------------
# The security control
# ---------------------------------------------------------------------------
def test_the_vendor_credential_scan_follows_the_selected_admin_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A key in the file that was LOADED must be seen, whichever file that is.

    Without this the scan reads ``.env.admin`` — very likely absent on the host, and
    therefore an empty result and a clean bill of health — while the panel boots from
    ``.env.admin.prod`` with an LLM key in it.
    """
    # Arrange
    selected = _write(
        tmp_path / ".env.admin.prod",
        BAYRAM_ADMIN_AUDIT_HMAC_KEY=_HMAC_KEY,
        BAYRAM_LLM_API_KEY="a key that must not be within reach of the panel",
    )
    monkeypatch.setenv(ADMIN_ENV_FILE_VAR, str(selected))

    # Act
    present = _present_vendor_vars()

    # Assert - the NAME, never the value
    assert present == ("BAYRAM_LLM_API_KEY",)


def test_the_scan_reports_nothing_when_the_selected_file_is_clean(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The negative case, so the test above is not passing on an unconditional hit."""
    # Arrange
    selected = _write(tmp_path / ".env.admin.prod", BAYRAM_ADMIN_AUDIT_HMAC_KEY=_HMAC_KEY)
    monkeypatch.setenv(ADMIN_ENV_FILE_VAR, str(selected))

    # Act / Assert
    assert _present_vendor_vars() == ()
