"""The gateway's configuration surface, and the four things it must refuse.

The refusals are the point of this file. A payment endpoint that boots misconfigured is worse
than one that does not boot at all: a blank key answers ``-32504`` to Payme and looks like a
network problem; a ``;`` in the return URL truncates a deep link in a way nothing observes; a
vendor credential within reach turns a compromise of the one internet-facing process into a
compromise of the bot; and an example file that has drifted from the model is a variable an
operator cannot set.

Every test builds settings with ``_env_file=None`` so a developer's own ``.env.payme`` cannot
change the answer, and points ``BAYRAM_PAYME_ENV_FILE`` at a path that does not exist wherever a
boot scan is involved, so the scan sees the process environment and nothing else.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Final

import pytest

from bayram.config import ENV_PREFIX, VENDOR_SECRET_FIELDS
from bayram.errors import ConfigError
from bayram.payme.app import FORBIDDEN_ENV_VARS, create_app
from bayram.payme.protocol import DEFAULT_ACCOUNT_FIELD, DEFAULT_AUTH_LOGIN
from bayram.payme.settings import (
    PAYME_ENV_FILE_VAR,
    PAYME_SECRET_FIELDS,
    PaymeSettings,
    build_payme_settings,
)

_REPO_ROOT: Final[Path] = Path(__file__).resolve().parents[2]
_ENV_EXAMPLE: Final[Path] = _REPO_ROOT / ".env.payme.example"
_DOCUMENTED_VARIABLE: Final[re.Pattern[str]] = re.compile(r"^BAYRAM_([A-Z0-9_]+)=", re.MULTILINE)

_MEMORY_URL: Final[str] = "sqlite+aiosqlite:///:memory:"
#: A made-up 36-character key. The gateway only ever compares the key against itself, so this
#: is a fully functional credential — which is what lets the whole suite run before Payme has
#: handed anything over.
_PLACEHOLDER_KEY: Final[str] = "c" * 36
_MERCHANT: Final[str] = "587f72c72cac0d162c722ae2"


def _payme_values(**overrides: Any) -> dict[str, Any]:
    """A minimal, valid configuration. ``_env_file=None`` keeps a local dotenv out of it."""
    values: dict[str, Any] = {
        "_env_file": None,
        "database_url": _MEMORY_URL,
        "payme_enabled": True,
        "payme_merchant_id": _MERCHANT,
        "payme_merchant_key": _PLACEHOLDER_KEY,
    }
    values.update(overrides)
    return values


@pytest.fixture(autouse=True)
def _no_local_dotenv(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Point the boot scan at a file that does not exist.

    Without this, a developer with a real ``.env.payme`` in the checkout would have the
    credential scan read it, and the two lifespan tests below would pass or fail depending on
    whose laptop they ran on.
    """
    monkeypatch.setenv(PAYME_ENV_FILE_VAR, str(tmp_path / "absent.env"))


# ---------------------------------------------------------------------------
# The refusals
# ---------------------------------------------------------------------------
def test_a_live_rail_with_a_blank_key_is_refused_by_name() -> None:
    """The message names the variable an operator can actually edit."""
    # Arrange / Act
    with pytest.raises(ConfigError) as caught:
        build_payme_settings(_payme_values(payme_merchant_key=""))

    # Assert
    assert f"{ENV_PREFIX}PAYME_MERCHANT_KEY" in caught.value.operator_message


def test_a_disabled_rail_needs_no_key_at_all() -> None:
    """The shipped default. A checkout that configures nothing must still build settings."""
    # Arrange / Act
    settings = build_payme_settings(
        _payme_values(payme_enabled=False, payme_merchant_key="", payme_merchant_id="")
    )

    # Assert
    assert settings.payme_enabled is False
    assert settings.merchant_key == ""


def test_a_semicolon_in_the_return_url_is_refused() -> None:
    """Payme's parser truncates at ``;`` and reports nothing. Refuse it where it is readable."""
    # Arrange / Act
    with pytest.raises(ConfigError) as caught:
        build_payme_settings(_payme_values(payme_return_url="https://t.me/bot?start=a;b"))

    # Assert
    message = caught.value.operator_message
    assert f"{ENV_PREFIX}PAYME_RETURN_URL" in message
    assert "truncates" in message


def test_a_plain_return_url_is_accepted_untouched() -> None:
    """Percent-encoding is not decoded by their parser, so the value is passed through raw."""
    # Arrange
    url = "https://t.me/bayram_uzbot?start=paid"

    # Act
    settings = build_payme_settings(_payme_values(payme_return_url=url))

    # Assert
    assert settings.payme_return_url == url


def test_an_unparsable_cidr_fails_the_boot_rather_than_the_first_request() -> None:
    # Arrange / Act
    with pytest.raises(ConfigError) as caught:
        build_payme_settings(_payme_values(payme_allowed_cidrs="185.234.113.0/28,not-an-ip"))

    # Assert
    assert f"{ENV_PREFIX}PAYME_ALLOWED_CIDRS" in caught.value.operator_message


def test_debug_logging_is_refused_in_prod() -> None:
    """The ORM would echo idempotency keys carrying a Telegram id into unswept logs."""
    # Arrange / Act
    with pytest.raises(ConfigError) as caught:
        build_payme_settings(_payme_values(environment="prod", log_level="DEBUG"))

    # Assert
    assert "DEBUG" in caught.value.operator_message


def test_a_positive_duplicate_transaction_code_is_refused() -> None:
    """A positive "error code" would be read by Payme as a success."""
    # Arrange / Act
    with pytest.raises(ConfigError) as caught:
        build_payme_settings(_payme_values(payme_duplicate_transaction_code=31008))

    # Assert
    assert f"{ENV_PREFIX}PAYME_DUPLICATE_TRANSACTION_CODE" in caught.value.operator_message


# ---------------------------------------------------------------------------
# The one secret
# ---------------------------------------------------------------------------
def test_the_merchant_key_never_appears_in_a_repr_or_a_dump() -> None:
    """``SecretStr``, following ``admin_audit_hmac_key`` — the only precedent in the tree.

    ``bayram.logging.redact`` masks a value only when the field NAME is supplied beside it, and a
    settings repr is exactly a bare value. Without ``SecretStr`` the only thing keeping the key
    out of a log line would be that nobody had written the offending line yet.
    """
    # Arrange
    settings = build_payme_settings(_payme_values())

    # Act
    rendered = (repr(settings), str(settings.model_dump()), settings.model_dump_json())

    # Assert
    for text in rendered:
        assert _PLACEHOLDER_KEY not in text
    assert settings.merchant_key == _PLACEHOLDER_KEY


def test_every_declared_secret_field_is_a_secret_str() -> None:
    """The property that keeps :data:`PAYME_SECRET_FIELDS` from being a comment."""
    # Arrange / Act
    annotations = {name: PaymeSettings.model_fields[name].annotation for name in PAYME_SECRET_FIELDS}

    # Assert
    assert PAYME_SECRET_FIELDS == ("payme_merchant_key",)
    assert all(field.__name__ == "SecretStr" for field in annotations.values() if field is not None)


# ---------------------------------------------------------------------------
# Defaults that are load-bearing
# ---------------------------------------------------------------------------
def test_the_shipped_defaults_leave_the_rail_switched_off() -> None:
    """Production behaviour must be byte-identical to today until three values change."""
    # Arrange / Act
    settings = build_payme_settings(
        {"_env_file": None, "database_url": _MEMORY_URL}
    )

    # Assert
    assert settings.payme_enabled is False
    assert settings.payme_merchant_id == ""
    assert settings.payme_basic_login == DEFAULT_AUTH_LOGIN
    assert settings.payme_account_field == DEFAULT_ACCOUNT_FIELD


def test_the_allowlist_is_inert_until_a_hop_count_is_declared() -> None:
    """With zero hops the address a filter would match is the terminator's, not the caller's."""
    # Arrange
    configured = build_payme_settings(_payme_values(payme_allowed_cidrs="185.234.113.0/28"))

    # Act
    with_hops = build_payme_settings(
        _payme_values(payme_allowed_cidrs="185.234.113.0/28", payme_trusted_proxy_hops=1)
    )

    # Assert
    assert configured.allowed_networks == ()
    assert with_hops.allowed_networks == ("185.234.113.0/28",)


# ---------------------------------------------------------------------------
# The example file
# ---------------------------------------------------------------------------
def test_the_example_file_documents_every_gateway_setting() -> None:
    """A field with nowhere to be written down is a field an operator cannot set."""
    # Arrange
    text = _ENV_EXAMPLE.read_text(encoding="utf-8")

    # Act
    documented = {match.group(1).lower() for match in _DOCUMENTED_VARIABLE.finditer(text)}

    # Assert
    assert documented == set(PaymeSettings.model_fields)


def test_the_example_file_holds_no_vendor_credential() -> None:
    """Not commented out, not blank — the names must not appear as variables at all.

    ``PaymeSettings`` has no field that could hold one, so a line here would be inert; it would
    also be an instruction to an operator to put a bot token on the host that terminates an
    inbound internet endpoint.
    """
    # Arrange
    text = _ENV_EXAMPLE.read_text(encoding="utf-8")

    # Act
    documented = {f"{ENV_PREFIX}{match.group(1)}" for match in _DOCUMENTED_VARIABLE.finditer(text)}

    # Assert
    assert documented.isdisjoint(FORBIDDEN_ENV_VARS)


# ---------------------------------------------------------------------------
# The boot refusals, through the real lifespan
# ---------------------------------------------------------------------------
async def test_the_lifespan_refuses_to_start_a_disabled_gateway() -> None:
    """Off by default, and the kill switch: one variable and a restart takes the rail down."""
    # Arrange
    application = create_app(build_payme_settings(_payme_values(payme_enabled=False)))

    # Act / Assert
    with pytest.raises(ConfigError) as caught:
        async with application.router.lifespan_context(application):
            pass  # pragma: no cover - the lifespan must not reach here
    assert "BAYRAM_PAYME_ENABLED" in caught.value.operator_message


async def test_the_lifespan_refuses_a_whitespace_only_key() -> None:
    """The model's emptiness test accepts it; a botched paste into a dotenv produces it."""
    # Arrange
    application = create_app(build_payme_settings(_payme_values(payme_merchant_key="   ")))

    # Act / Assert
    with pytest.raises(ConfigError) as caught:
        async with application.router.lifespan_context(application):
            pass  # pragma: no cover - the lifespan must not reach here
    assert f"{ENV_PREFIX}PAYME_MERCHANT_KEY" in caught.value.operator_message


@pytest.mark.parametrize("field", VENDOR_SECRET_FIELDS)
async def test_prod_refuses_to_start_with_a_vendor_credential_in_the_environment(
    field: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The mirror image of the admin app's refusal, and it must cover the same four names.

    Parametrised over ``VENDOR_SECRET_FIELDS`` rather than hardcoding ``BAYRAM_TELEGRAM_BOT_TOKEN``
    so a fifth vendor credential added to ``bayram.config`` is covered here the day it lands.
    """
    # Arrange
    variable = f"{ENV_PREFIX}{field.upper()}"
    monkeypatch.setenv(variable, "a-value-that-must-not-be-here")
    application = create_app(build_payme_settings(_payme_values(environment="prod")))

    # Act / Assert — the message names the variable and never carries its value.
    with pytest.raises(ConfigError) as caught:
        async with application.router.lifespan_context(application):
            pass  # pragma: no cover - the lifespan must not reach here
    assert variable in caught.value.operator_message
    assert "a-value-that-must-not-be-here" not in caught.value.operator_message


async def test_prod_refuses_a_vendor_credential_written_into_the_gateways_own_dotenv(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Both places count as reach: the environment, and the file that was actually loaded."""
    # Arrange
    variable = f"{ENV_PREFIX}TELEGRAM_BOT_TOKEN"
    dotenv = tmp_path / "payme.env"
    dotenv.write_text(f"{variable}=1234:secret\n", encoding="utf-8")
    monkeypatch.setenv(PAYME_ENV_FILE_VAR, str(dotenv))
    application = create_app(build_payme_settings(_payme_values(environment="prod")))

    # Act / Assert
    with pytest.raises(ConfigError) as caught:
        async with application.router.lifespan_context(application):
            pass  # pragma: no cover - the lifespan must not reach here
    assert variable in caught.value.operator_message
    assert "1234:secret" not in caught.value.operator_message


async def test_the_merchant_key_is_not_itself_forbidden_on_this_host() -> None:
    """This is the one process that holds it. The admin app's list is the one that gains it."""
    # Arrange / Act / Assert
    assert f"{ENV_PREFIX}PAYME_MERCHANT_KEY" not in FORBIDDEN_ENV_VARS
