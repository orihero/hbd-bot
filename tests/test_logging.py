"""The two logging controls that are privacy controls rather than ergonomics.

Redaction and the noisy-logger floor exist for the same reason: a log line has no
retention clock, is not reachable by ``hbd.db.purge`` and is not reachable by a per-user
erasure. Anything that reaches stdout is outside every promise the product makes about how
long it keeps a recipient's name, so what may reach stdout is asserted here rather than
reviewed by eye.
"""

from __future__ import annotations

import logging
from collections.abc import Iterator
from typing import Final

import pytest

from hbd.logging import REDACTED, configure_logging, redact

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
    "key", ["database_url", "redis_url", "audit_dsn", "connection_string", "conn_str", "hmac_key"]
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
# The noisy-logger floor
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("name", _MUST_BE_FLOORED)
@pytest.mark.usefixtures("_restore_child_levels")
def test_root_debug_cannot_pull_a_data_echoing_logger_down_with_it(name: str) -> None:
    # Arrange / Act — HBD_LOG_LEVEL=DEBUG is one config change away at any time.
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
