"""Structured JSON logging with a per-order correlation id and secret redaction.

Three jobs:

* One JSON object per line, so a log shipper needs no parsing rules.
* A ``correlation_id`` bound once per order and carried across every ``await`` in the
  pipeline via ``contextvars`` — no threading it through call signatures.
* Redaction applied at the formatter, so a careless call site cannot leak a key. Keys
  whose NAME looks secret are masked, and values that look like known key formats are
  masked wherever they appear. The one exception is a closed, integer-only allow-list of
  token-COUNT field names — see :data:`_USAGE_COUNTER_KEYS`.

Recipient names are personal data but not secrets: they are logged, and callers that
want them hashed should hash before logging.
"""

from __future__ import annotations

import json
import logging
import re
import sys
import uuid
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from contextvars import ContextVar, Token
from typing import Any, Final

from hbd.errors import HbdError

__all__ = [
    "configure_logging",
    "get_logger",
    "new_correlation_id",
    "bind_correlation_id",
    "current_correlation_id",
    "correlation_scope",
    "redact",
    "REDACTED",
]

REDACTED: Final[str] = "***REDACTED***"

#: Field names that must never reach a log line intact. A connection string carries its
#: own password in the userinfo, so the URL field names belong here as much as the keys do.
_SECRET_NAME_PATTERN: Final[re.Pattern[str]] = re.compile(
    r"(api[_-]?key|secret|token|password|passwd|authorization|credential|private[_-]?key"
    r"|database_url|redis_url|dsn|connection_string|conn_str|hmac_key)",
    re.IGNORECASE,
)

#: The three field names that carry a token COUNT, not a token.
#:
#: ``_SECRET_NAME_PATTERN`` matches the substring ``token``, which is right for
#: ``bot_token``, ``access_token`` and ``refresh_token`` and wrong for exactly three names:
#: an LLM response reports its work as ``prompt_tokens`` / ``completion_tokens`` /
#: ``total_tokens``, and those are the only quantities the chat-completion leg measures.
#: Masked, the ``vendor.usage`` line carries no measurement at all — and that line is the
#: designed fallback for when the ``vendor_usage`` insert fails, so the substring cost us
#: the whole record precisely when it was the only copy left.
#:
#: The exception is safe because it is narrow in three directions at once. It is a closed
#: set of literal, case-sensitive names rather than a pattern, so no key an attacker can
#: choose falls into it — ``token``, ``api_token`` and ``x_total_tokens`` all still mask.
#: It admits only a real ``int`` (``bool`` excluded: ``True`` is not a count, and a count
#: is a number the panel adds up), so a credential that lands in a field called
#: ``total_tokens`` is still a string and is still masked. And it never widens the value
#: patterns: a secret-shaped VALUE is unreachable from an int, so nothing that would have
#: been caught by shape escapes through the name.
_USAGE_COUNTER_KEYS: Final[frozenset[str]] = frozenset(
    {"prompt_tokens", "completion_tokens", "total_tokens"}
)

#: Value shapes for the keys this project actually holds.
_SECRET_VALUE_PATTERNS: Final[tuple[re.Pattern[str], ...]] = (
    re.compile(r"\b\d{6,12}:[A-Za-z0-9_-]{30,}\b"),  # Telegram bot token
    re.compile(r"\bsk_[A-Za-z0-9]{20,}\b"),  # ElevenLabs style
    # OpenRouter (sk-or-v1-…) and current OpenAI (sk-proj-…) keys use hyphens, so the
    # underscore pattern above never saw them.
    re.compile(r"\bsk-[a-z0-9-]{2,}-[A-Za-z0-9_-]{20,}\b"),
    re.compile(r"\bAIza[0-9A-Za-z_-]{30,}\b"),  # Google API key
    re.compile(r"\bBearer\s+[A-Za-z0-9._-]{10,}\b", re.IGNORECASE),
    # DSN userinfo: scheme://user:password@host. Masks the credentials and keeps the host,
    # because "which database" is the half of the string an operator is reading the log for.
    re.compile(r"\b[a-z][a-z0-9+.-]*://[^/\s:@]+:[^/\s@]+@"),
)

#: Long free text is truncated so a raw LLM payload cannot flood the log.
MAX_LOGGED_VALUE_CHARS: Final[int] = 2_000

#: Loggers floored at WARNING no matter how low the root goes.
#:
#: This is a privacy control, not tidiness. ``sqlalchemy.engine`` at DEBUG echoes every
#: statement **with its bound parameters** — recipient names, notes, approved lyrics, STT
#: transcripts — into stdout, which has no retention clock and is reachable by neither
#: ``hbd.db.purge`` nor a per-user erasure. One ``HBD_LOG_LEVEL=DEBUG`` would otherwise turn
#: the whole retention design into a no-op for as long as it is on, and leave an unclocked
#: copy behind afterwards. ``aiogram`` and ``uvicorn.access`` carry the same data by a
#: different route (update bodies, request lines).
_NOISY_LOGGERS: Final[tuple[str, ...]] = (
    "httpx",
    "httpcore",
    "asyncio",
    "aiogram",
    "aiogram.event",
    "arq",
    "sqlalchemy",
    "sqlalchemy.engine",
    "sqlalchemy.pool",
    "uvicorn",
    "uvicorn.access",
    "uvicorn.error",
)

_CORRELATION_ID: ContextVar[str] = ContextVar("hbd_correlation_id", default="-")

_RESERVED_RECORD_KEYS: Final[frozenset[str]] = frozenset(
    logging.LogRecord("", 0, "", 0, "", None, None).__dict__
) | {"message", "asctime", "taskName"}


# ---------------------------------------------------------------------------
# Correlation id
# ---------------------------------------------------------------------------
def new_correlation_id() -> str:
    """A fresh id. One per order, generated where the order is created."""
    return uuid.uuid4().hex


def bind_correlation_id(correlation_id: str) -> Token[str]:
    """Bind an id to the current context. Caller resets the token when done."""
    return _CORRELATION_ID.set(correlation_id)


def current_correlation_id() -> str:
    return _CORRELATION_ID.get()


@contextmanager
def correlation_scope(correlation_id: str | None = None) -> Iterator[str]:
    """Bind an id for the duration of a block, then restore the previous one."""
    resolved = correlation_id or new_correlation_id()
    token = _CORRELATION_ID.set(resolved)
    try:
        yield resolved
    finally:
        _CORRELATION_ID.reset(token)


# ---------------------------------------------------------------------------
# Redaction
# ---------------------------------------------------------------------------
def _redact_text(text: str) -> str:
    masked = text
    for pattern in _SECRET_VALUE_PATTERNS:
        masked = pattern.sub(REDACTED, masked)
    if len(masked) > MAX_LOGGED_VALUE_CHARS:
        return f"{masked[:MAX_LOGGED_VALUE_CHARS]}…[truncated {len(masked)} chars]"
    return masked


def _is_usage_counter(key: str, value: Any) -> bool:
    """True for one of the three token-count fields holding an actual count.

    Both halves are required. The name alone would let anything a call site puts under
    ``total_tokens`` through the secret matcher; the type alone would carve out every
    integer. Together they describe a value that cannot be a credential.
    """
    return key in _USAGE_COUNTER_KEYS and isinstance(value, int) and not isinstance(value, bool)


def redact(value: Any, *, key: str | None = None) -> Any:
    """Return a NEW value with secrets masked. Never mutates the input.

    The allow-list is consulted before the secret-name pattern because the pattern would
    otherwise win on the substring ``token``; see :data:`_USAGE_COUNTER_KEYS` for why the
    three counters need the exception and why granting it weakens nothing.
    """
    if key is not None and _is_usage_counter(key, value):
        return value
    if key is not None and _SECRET_NAME_PATTERN.search(key):
        return REDACTED
    if isinstance(value, str):
        return _redact_text(value)
    if isinstance(value, Mapping):
        return {str(k): redact(v, key=str(k)) for k, v in value.items()}
    if isinstance(value, list | tuple | set | frozenset):
        return [redact(item) for item in value]
    if value is None or isinstance(value, int | float | bool):
        return value
    return _redact_text(str(value))


# ---------------------------------------------------------------------------
# Formatter
# ---------------------------------------------------------------------------
class JsonFormatter(logging.Formatter):
    """One JSON object per record, with extras and error context folded in."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%S%z"),
            "level": record.levelname,
            "logger": record.name,
            "message": redact(record.getMessage()),
            "correlation_id": getattr(record, "correlation_id", current_correlation_id()),
        }
        extras = {
            key: value
            for key, value in record.__dict__.items()
            if key not in _RESERVED_RECORD_KEYS and key != "correlation_id"
        }
        if extras:
            payload["context"] = redact(extras)
        if record.exc_info is not None:
            payload["exception"] = _redact_text(self.formatException(record.exc_info))
            error = record.exc_info[1]
            if isinstance(error, HbdError):
                payload["error"] = redact(error.to_log_dict())
        return json.dumps(payload, ensure_ascii=False, default=str)


class _CorrelationFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        if not hasattr(record, "correlation_id"):
            record.correlation_id = current_correlation_id()
        return True


def configure_logging(*, level: str = "INFO", is_json: bool = True) -> None:
    """Install the root handler. Idempotent: repeated calls replace, never stack."""
    handler: logging.Handler = logging.StreamHandler(stream=sys.stdout)
    plain = logging.Formatter(
        "%(asctime)s %(levelname)s [%(correlation_id)s] %(name)s: %(message)s"
    )
    handler.setFormatter(JsonFormatter() if is_json else plain)
    handler.addFilter(_CorrelationFilter())

    root = logging.getLogger()
    for existing in tuple(root.handlers):
        root.removeHandler(existing)
    root.addHandler(handler)
    root.setLevel(level.upper())

    # Vendor clients and the ORM are chatty, and their debug logs echo request bodies and
    # bound SQL parameters. Floored, never merely defaulted: see _NOISY_LOGGERS.
    for noisy in _NOISY_LOGGERS:
        logging.getLogger(noisy).setLevel(max(logging.WARNING, root.level))


def get_logger(name: str) -> logging.Logger:
    """Module logger. Always ``get_logger(__name__)``."""
    return logging.getLogger(name)
