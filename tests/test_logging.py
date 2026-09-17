"""The two logging controls that are privacy controls rather than ergonomics.

Redaction and the noisy-logger floor exist for the same reason: a log line has no
retention clock, is not reachable by ``bayram.db.purge`` and is not reachable by a per-user
erasure. Anything that reaches stdout is outside every promise the product makes about how
long it keeps a recipient's name, so what may reach stdout is asserted here rather than
reviewed by eye.

Redaction has exactly one exception, and it is asserted from both sides. The secret matcher
looks for the substring ``token``, which swallowed ``prompt_tokens`` / ``completion_tokens``
/ ``total_tokens`` and left the ``vendor.usage`` line — the fallback copy of a measurement
when the ``vendor_usage`` insert fails — with no measurement on it. The carve-out is a
closed set of three literal names holding a real ``int``, so the tests below check that the
three counters survive, that those same names holding anything else do not, and that no
other ``token``-ish name has quietly joined them.
"""

from __future__ import annotations

import logging
from collections.abc import Iterator
from typing import Final

import pytest

from bayram.logging import REDACTED, configure_logging, redact

#: The three names the redactor deliberately lets through, and the only three.
_USAGE_COUNTERS: Final[tuple[str, ...]] = ("prompt_tokens", "completion_tokens", "total_tokens")

#: Names that merely contain the word and are NOT counters. ``x_total_tokens`` and
#: ``total_tokens_used`` are here because the carve-out is a literal set, not a pattern:
#: if either of them ever survives, the exception has become a substring rule of its own.
_NOT_COUNTERS: Final[tuple[str, ...]] = (
    "token",
    "access_token",
    "refresh_token",
    "bot_token",
    "api_token",
    "x_total_tokens",
    "total_tokens_used",
)

#: Shaped like the ones this project actually holds. None is a live credential.
_POSTGRES_DSN: Final[str] = "postgresql+asyncpg://hbd:s3cr3t-pw@db.internal:5432/hbd"
_REDIS_DSN: Final[str] = "redis://default:hunter2@redis.internal:6379/0"
_OPENROUTER_KEY: Final[str] = "sk-or-v1-0123456789abcdef0123456789abcdef0123"
_OPENAI_KEY: Final[str] = "sk-proj-0123456789abcdef0123456789abcdef0123"
_ELEVENLABS_KEY: Final[str] = "sk_0123456789abcdef0123456789abcdef"
_TELEGRAM_TOKEN: Final[str] = "1234567890:AAF0123456789abcdefghijklmnopqrstuvw"

#: Floored no matter how low the root goes; sqlalchemy.engine echoes bound parameters.
_MUST_BE_FLOORED: Final[tuple[str, ...]] = (
    "sqlalchemy",
    "sqlalchemy.engine",
    "sqlalchemy.pool",
    "aiogram",
    "arq",
    "uvicorn",
    "uvicorn.access",
    "uvicorn.error",
)


@pytest.fixture
def _restore_child_levels() -> Iterator[None]:
    """``configure_logging`` sets levels on named loggers; the root fixture misses those."""
    saved = {name: logging.getLogger(name).level for name in _MUST_BE_FLOORED}
    yield
    for name, level in saved.items():
        logging.getLogger(name).setLevel(level)


# ---------------------------------------------------------------------------
# Redaction
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "secret",
    [_POSTGRES_DSN, _REDIS_DSN, _OPENROUTER_KEY, _OPENAI_KEY, _ELEVENLABS_KEY, _TELEGRAM_TOKEN],
)
def test_a_credential_embedded_in_a_message_is_masked(secret: str) -> None:
    # Act
    masked = redact(f"connecting with {secret} now")

    # Assert — the whole point is that a careless call site cannot leak it.
    assert REDACTED in str(masked)


def test_a_dsn_keeps_its_host_and_loses_its_password() -> None:
    # Act
    masked = str(redact(_POSTGRES_DSN))

    # Assert — "which database" is why an operator reads the line; the password is not.
    assert "s3cr3t-pw" not in masked
    assert "db.internal:5432/hbd" in masked


@pytest.mark.parametrize(
    "key",
    [
        "database_url",
        "redis_url",
        "audit_dsn",
        "connection_string",
        "conn_str",
        "hmac_key",
        "api_key",
        "openrouter_api_key",
        "secret",
        "password",
        "passwd",
        "authorization",
        "credential",
        "private_key",
    ],
)
def test_a_field_whose_name_looks_like_a_credential_is_masked_whatever_it_holds(key: str) -> None:
    # Act
    masked = redact({key: "postgresql://u:p@h/db"})

    # Assert
    assert masked == {key: REDACTED}


def test_redaction_returns_a_new_mapping_and_leaves_the_original_intact() -> None:
    # Arrange
    original = {"database_url": _POSTGRES_DSN, "order_id": 7}

    # Act
    masked = redact(original)

    # Assert
    assert original == {"database_url": _POSTGRES_DSN, "order_id": 7}
    assert masked == {"database_url": REDACTED, "order_id": 7}


# ---------------------------------------------------------------------------
# The token-counter carve-out
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("key", _USAGE_COUNTERS)
def test_a_token_count_survives_redaction_because_the_usage_line_is_the_fallback_copy(
    key: str,
) -> None:
    # Arrange — the ``vendor.usage`` line is what an operator still has when the
    # ``vendor_usage`` insert fails, and these three are the only quantities the
    # chat-completion leg measures at all.
    payload = {key: 1_234, "cost_usd": 0.000123}

    # Act
    masked = redact(payload)

    # Assert — an integer count, not the mask and not a stringified one.
    assert masked == {key: 1_234, "cost_usd": 0.000123}
    assert isinstance(masked[key], int)


@pytest.mark.parametrize("key", _USAGE_COUNTERS)
@pytest.mark.parametrize(
    "value",
    ["sk-or-v1-0123456789abcdef0123456789abcdef0123", "200", None, 12.5, True, ["1", "2"]],
    ids=["a key", "a numeric string", "a null", "a float", "a bool", "a list"],
)
def test_a_counter_name_holding_anything_but_an_integer_is_still_masked(
    key: str, value: object
) -> None:
    # Arrange / Act — the carve-out is a name AND a type. Without the type half, landing a
    # string in a field called total_tokens would be a way through the secret matcher.
    masked = redact({key: value})

    # Assert
    assert masked == {key: REDACTED}


@pytest.mark.parametrize("key", _NOT_COUNTERS)
def test_a_name_that_merely_contains_the_word_token_is_still_masked(key: str) -> None:
    # Arrange / Act — an integer, so only the name can decide. The allow-list is a closed
    # set of three literals; anything else keeps the substring rule it always had.
    masked = redact({key: 1_234})

    # Assert
    assert masked == {key: REDACTED}


def test_the_carve_out_reaches_a_counter_nested_inside_the_formatters_context_object() -> None:
    # Arrange — this is the real shape: log_usage passes one flat extra dict, and the
    # formatter redacts it as ``context``.
    extras = {
        "vendor": "openrouter",
        "prompt_tokens": 140,
        "completion_tokens": 60,
        "total_tokens": 200,
        "api_key": _OPENROUTER_KEY,
    }

    # Act
    masked = redact({"context": extras})

    # Assert — the measurement reaches the log line and the credential does not.
    assert masked["context"]["total_tokens"] == 200
    assert masked["context"]["prompt_tokens"] == 140
    assert masked["context"]["completion_tokens"] == 60
    assert masked["context"]["api_key"] == REDACTED


# ---------------------------------------------------------------------------
# The noisy-logger floor
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("name", _MUST_BE_FLOORED)
@pytest.mark.usefixtures("_restore_child_levels")
def test_root_debug_cannot_pull_a_data_echoing_logger_down_with_it(name: str) -> None:
    # Arrange / Act — BAYRAM_LOG_LEVEL=DEBUG is one config change away at any time.
    configure_logging(level="DEBUG", is_json=True)

    # Assert — at DEBUG, sqlalchemy.engine logs every statement with its bound parameters:
    # recipient names, notes, approved lyrics, STT transcripts.
    assert logging.getLogger(name).level >= logging.WARNING
    assert logging.getLogger().level == logging.DEBUG


@pytest.mark.usefixtures("_restore_child_levels")
def test_a_stricter_root_level_raises_the_floor_rather_than_lowering_it() -> None:
    # Act
    configure_logging(level="ERROR", is_json=True)

    # Assert — the floor is a minimum, not an assignment.
    assert logging.getLogger("sqlalchemy.engine").level == logging.ERROR
