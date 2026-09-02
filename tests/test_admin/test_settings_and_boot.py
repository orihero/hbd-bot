"""The configuration surface the admin process boots through, and the five holes it had.

Every test here is a regression test for a specific finding against slice 1a, and each one
fails against the code as it shipped:

* **The vendor refusal missed a credential.** ``VENDOR_SECRET_FIELDS`` listed three keys
  while ``Settings`` carried four, so ``HBD_LLM_FALLBACK_API_KEY`` reached a prod admin host
  with neither a refusal nor a warning. The shape test below is the part that matters: it
  fails for the *fifth* credential too, without anyone remembering this file exists.
* **``__Host-`` cookies were unusable in dev.** The prefix is defined to make a browser
  reject a ``Set-Cookie`` without ``Secure``, so a dev panel stored neither cookie and could
  never sign anyone in. ``httpx`` does not enforce the prefix, which is why every existing
  test passed; the assertion here reads the ``Set-Cookie`` header itself.
* **The step-up grace was a constant**, at three times the specified default.
* **``admin_public_origin`` had a default**, so a prod deploy that forgot it booted, passed
  ``/healthz``, served a login page and then 403'd every mutation with ``ORIGIN_REJECTED``.
* **Five specified fields were absent**, and ``.env.admin.example`` had drifted from the
  model. The example-file test closes that drift permanently: a field with nowhere to be
  written down is a field an operator cannot set.
"""

from __future__ import annotations

import re
import tomllib
from pathlib import Path
from typing import Any, Final

import httpx
import pytest

from hbd.admin.app import FORBIDDEN_ENV_VARS, create_app
from hbd.admin.container import AdminContainer
from hbd.admin.csrf import CSRF_COOKIE_NAME, SESSION_COOKIE_NAME
from hbd.admin.settings import AdminEnvironment, AdminSettings, build_admin_settings
from hbd.config import (
    ENV_PREFIX,
    REQUIRED_VENDOR_SECRET_FIELDS,
    VENDOR_SECRET_FIELDS,
    Settings,
    build_settings,
)
from hbd.errors import ConfigError
from tests.test_admin.conftest import HMAC_KEY, create_account, make_settings, sign_in

#: A field whose name *ends* in one of these words holds a credential. Anchored so
#: ``llm_max_output_tokens`` — a count, not a token — is not swept in.
_SECRET_SHAPED: Final[re.Pattern[str]] = re.compile(
    r"(?:^|_)(?:api_key|apikey|token|secret|password|credential)$"
)

_HOST_PREFIX: Final[str] = "__Host-"
_ENVIRONMENTS: Final[tuple[AdminEnvironment, ...]] = ("dev", "staging", "prod")
_REPO_ROOT: Final[Path] = Path(__file__).resolve().parents[2]
_ENV_EXAMPLE: Final[Path] = _REPO_ROOT / ".env.admin.example"
_DOCUMENTED_VARIABLE: Final[re.Pattern[str]] = re.compile(r"^HBD_([A-Z0-9_]+)=", re.MULTILINE)
_MEMORY_URL: Final[str] = "sqlite+aiosqlite:///:memory:"


def _admin_values(**overrides: Any) -> dict[str, Any]:
    """The minimum a valid :class:`AdminSettings` needs, with no origin and no env file."""
    values: dict[str, Any] = {
        "_env_file": None,
        "database_url": _MEMORY_URL,
        "admin_audit_hmac_key": HMAC_KEY,
    }
    values.update(overrides)
    return values


# ---------------------------------------------------------------------------
# Issue 2: the prod vendor-credential refusal covers every credential
# ---------------------------------------------------------------------------
def test_every_secret_shaped_settings_field_is_a_declared_vendor_secret() -> None:
    """The shape test, so the *next* credential cannot be forgotten either.

    ``VENDOR_SECRET_FIELDS`` is what ``hbd.admin.app`` derives ``FORBIDDEN_ENV_VARS`` from.
    A credential on ``Settings`` that is missing from it is a credential the admin host may
    hold in prod with no refusal and no warning.
    """
    # Arrange / Act
    secret_shaped = {name for name in Settings.model_fields if _SECRET_SHAPED.search(name)}

    # Assert
    assert secret_shaped == set(VENDOR_SECRET_FIELDS)


def test_the_admin_forbidden_variables_include_the_llm_fallback_key() -> None:
    assert f"{ENV_PREFIX}LLM_FALLBACK_API_KEY" in FORBIDDEN_ENV_VARS


async def test_prod_refuses_to_start_with_the_llm_fallback_key_in_the_environment(
    container: AdminContainer, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Arrange
    variable = f"{ENV_PREFIX}LLM_FALLBACK_API_KEY"
    monkeypatch.setenv(variable, "a-value-that-must-not-be-here")
    application = create_app(make_settings(environment="prod"))

    # Act / Assert — the message names the variable and never carries its value.
    with pytest.raises(ConfigError) as caught:
        async with application.router.lifespan_context(application):
            pass  # pragma: no cover - the lifespan must not reach here
    assert variable in caught.value.operator_message
    assert "a-value-that-must-not-be-here" not in caught.value.operator_message


def test_only_the_three_credentials_the_bot_cannot_run_without_are_required() -> None:
    """Forbidden on the admin host and required for the bot are two different sets.

    The fallback key is optional — an unconfigured failover is a supported deployment — so
    adding it to ``VENDOR_SECRET_FIELDS`` must not start demanding it from the worker.
    """
    # Arrange / Act
    with pytest.raises(ConfigError) as caught:
        build_settings({"_env_file": None, "database_url": _MEMORY_URL})

    # Assert
    message = caught.value.operator_message
    assert set(REQUIRED_VENDOR_SECRET_FIELDS) < set(VENDOR_SECRET_FIELDS)
    for field in REQUIRED_VENDOR_SECRET_FIELDS:
        assert f"{ENV_PREFIX}{field.upper()}" in message
    assert f"{ENV_PREFIX}LLM_FALLBACK_API_KEY" not in message


# ---------------------------------------------------------------------------
# Issue 6: a __Host- cookie is always sent with Secure
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("environment", _ENVIRONMENTS)
def test_the_host_prefix_and_the_secure_flag_stay_coherent(environment: AdminEnvironment) -> None:
    """``__Host-`` is *defined* to make a browser reject a cookie that lacks ``Secure``.

    Dropping ``Secure`` in dev did not make the cookie work there — it made the browser
    discard it, so nobody could sign in against ``make admin`` at all.
    """
    # Arrange
    settings = make_settings(environment=environment)

    # Act / Assert
    assert SESSION_COOKIE_NAME.startswith(_HOST_PREFIX)
    assert CSRF_COOKIE_NAME.startswith(_HOST_PREFIX)
    assert settings.is_cookie_secure is True


@pytest.mark.parametrize("environment", _ENVIRONMENTS)
def test_secure_may_not_be_switched_off_in_any_environment(
    environment: AdminEnvironment,
) -> None:
    with pytest.raises(ValueError, match="admin_cookie_secure"):
        make_settings(environment=environment, admin_cookie_secure=False)


async def test_a_dev_login_sets_both_cookies_with_secure(
    container: AdminContainer, client: httpx.AsyncClient
) -> None:
    # Arrange — the default fixture environment is dev, which is where this was broken.
    await create_account(container)

    # Act
    response = await sign_in(client)

    # Assert
    assert response.status_code == 200
    host_cookies = [
        header
        for header in response.headers.get_list("set-cookie")
        if header.startswith(_HOST_PREFIX)
    ]
    assert len(host_cookies) == 2
    assert all("Secure" in header for header in host_cookies)


# ---------------------------------------------------------------------------
# Issue 7: the step-up grace is configuration, with the specified bounds
# ---------------------------------------------------------------------------
def test_the_step_up_grace_defaults_to_five_minutes() -> None:
    assert make_settings().admin_step_up_grace_seconds == 300


@pytest.mark.parametrize("value", [0, 1, 900])
def test_the_step_up_grace_accepts_the_specified_range(value: int) -> None:
    assert make_settings(admin_step_up_grace_seconds=value).admin_step_up_grace_seconds == value


@pytest.mark.parametrize("value", [-1, 901])
def test_the_step_up_grace_refuses_a_value_outside_the_range(value: int) -> None:
    with pytest.raises(ValueError, match="admin_step_up_grace_seconds"):
        make_settings(admin_step_up_grace_seconds=value)


# ---------------------------------------------------------------------------
# Issue 8: admin_public_origin is required outside dev
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("environment", ["staging", "prod"])
def test_a_missing_public_origin_is_a_boot_refusal_outside_dev(environment: str) -> None:
    """A wrong origin 403s every mutation; a missing one must be a refusal that names it.

    Failing closed at the first state change instead of at boot turns a forgotten variable
    into an incident nobody can read from the symptom.
    """
    # Act / Assert
    with pytest.raises(ConfigError) as caught:
        build_admin_settings(_admin_values(environment=environment))
    message = caught.value.operator_message
    assert f"{ENV_PREFIX}ADMIN_PUBLIC_ORIGIN" in message
    # A cross-field refusal has no single field to blame, and "HBD_<ROOT>" names nothing.
    assert "<ROOT>" not in message


@pytest.mark.parametrize("environment", ["staging", "prod"])
def test_an_explicit_public_origin_boots_outside_dev(environment: str) -> None:
    settings = build_admin_settings(
        _admin_values(environment=environment, admin_public_origin="https://admin.example.com")
    )
    assert settings.admin_public_origin == "https://admin.example.com"


def test_the_environment_variable_satisfies_the_requirement(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The check reads "was it supplied", not "was it passed as a keyword".

    A requirement that only an explicit constructor argument could satisfy would refuse the
    boot of a correctly-configured prod host, which is worse than the trap it replaces.
    """
    # Arrange
    monkeypatch.setenv(f"{ENV_PREFIX}ADMIN_PUBLIC_ORIGIN", "https://admin.example.com")

    # Act
    settings = build_admin_settings(_admin_values(environment="prod"))

    # Assert
    assert settings.admin_public_origin == "https://admin.example.com"


def test_dev_keeps_the_loopback_default() -> None:
    assert build_admin_settings(_admin_values()).admin_public_origin == "http://127.0.0.1:8080"


# ---------------------------------------------------------------------------
# Issue 9: the five specified fields exist, with the specified bounds
# ---------------------------------------------------------------------------
def test_the_specified_defaults() -> None:
    # Arrange / Act
    settings = make_settings()

    # Assert
    assert settings.admin_audit_dsn == ""
    assert settings.admin_config_enabled is True
    assert settings.admin_step_up_grace_seconds == 300
    assert settings.admin_reveal_records_per_hour == 200
    assert settings.admin_reveal_conversations_per_day == 20


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("admin_reveal_records_per_hour", 9),
        ("admin_reveal_records_per_hour", 2_001),
        ("admin_reveal_conversations_per_day", 0),
        ("admin_reveal_conversations_per_day", 201),
    ],
)
def test_the_reveal_budgets_refuse_a_value_outside_their_bounds(field: str, value: int) -> None:
    with pytest.raises(ValueError, match=field):
        make_settings(**{field: value})


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("admin_reveal_records_per_hour", 10),
        ("admin_reveal_records_per_hour", 2_000),
        ("admin_reveal_conversations_per_day", 1),
        ("admin_reveal_conversations_per_day", 200),
    ],
)
def test_the_reveal_budgets_accept_their_bounds(field: str, value: int) -> None:
    assert getattr(make_settings(**{field: value}), field) == value


def test_the_audit_dsn_is_carried_verbatim_for_the_two_places_that_read_it() -> None:
    """Migration 0006's REVOKE guard and ``/audit/verify``'s report both read this."""
    dsn = "postgresql+asyncpg://hbd_owner:pw@localhost:5432/hbd"
    assert make_settings(admin_audit_dsn=dsn).admin_audit_dsn == dsn


def test_the_config_editor_can_be_switched_off() -> None:
    assert make_settings(admin_config_enabled=False).admin_config_enabled is False


def test_the_example_file_documents_every_admin_setting() -> None:
    """A field with nowhere to be written down is a field an operator cannot set."""
    # Arrange
    text = _ENV_EXAMPLE.read_text(encoding="utf-8")

    # Act
    documented = {match.group(1).lower() for match in _DOCUMENTED_VARIABLE.finditer(text)}

    # Assert
    assert documented == set(AdminSettings.model_fields)


def test_the_dotenv_library_the_boot_check_imports_is_a_declared_dependency() -> None:
    """``app.py`` does ``from dotenv import dotenv_values``; that must be a stated pin.

    It resolves today only because ``pydantic-settings`` happens to pull ``python-dotenv``
    in. A transitive dependency is not a contract: the day that pin stops requiring it — a
    minor release, a resolver picking a different tree — the admin process stops importing,
    and the failure lands at boot on the host rather than here. The vendor-credential check
    in ``_env_file_names`` is the thing that would go with it, so this is a security control
    resting on somebody else's dependency graph.
    """
    # Arrange - the import is real, not hypothetical
    source = (_REPO_ROOT / "src" / "hbd" / "admin" / "app.py").read_text(encoding="utf-8")
    assert "from dotenv import" in source

    # Act - the declared runtime dependency names, normalised the way PEP 508 compares them
    pyproject = tomllib.loads((_REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    declared = {
        re.split(r"[<>=!\[;\s]", requirement, maxsplit=1)[0].strip().lower().replace("_", "-")
        for requirement in pyproject["project"]["dependencies"]
    }

    # Assert
    assert "python-dotenv" in declared
