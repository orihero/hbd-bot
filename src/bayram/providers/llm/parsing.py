"""The tolerant parse boundary. Nothing in this module raises.

A model is a stochastic source we do not control. Even in strict JSON mode it drifts:
it fences the object, it thinks out loud first, it stops mid-object at the token cap,
it emits ``]`` where ``}`` belonged, it answers ``true``. Every one of those has taken
down a worker in production somewhere, and the fix is always the same shape:

    strip fences -> parse -> repair -> validate against a schema -> return a Result

Each stage is a *candidate string*; we try them in order and stop at the first that both
parses to an object and validates. Failure is a typed ``Err(LlmParseError)`` carrying the
raw payload, the finish reason and the last parser error, logged once at ERROR.

A hand-rolled repairer is a trap — a close-only fixer cannot repair a *swapped*
delimiter — so the repair stage is ``json-repair``, and even that is called inside a
``try`` because a library is external data too.

One recovery is worth stating outright because it looks like a bug otherwise: an object
wrapped in an array (``[{...}]``) is recovered as its first element. A model that answers
with a one-item list has produced the object we asked for.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Final

from json_repair import repair_json
from pydantic import BaseModel
from pydantic import ValidationError as PydanticValidationError

from bayram.contracts import Err, Result, err, ok
from bayram.errors import LlmParseError
from bayram.logging import get_logger

__all__ = [
    "parse_model_json",
    "strip_code_fences",
    "extract_first_json_object",
    "MAX_LOGGED_PAYLOAD_CHARS",
]

_LOG = get_logger(__name__)

#: The logging layer truncates too, but keep the error context itself bounded so a
#: 100k-token ramble cannot be carried around in memory by every retry frame.
MAX_LOGGED_PAYLOAD_CHARS: Final[int] = 4_000

_FENCE_OPEN: Final[str] = "```"
_OBJECT_OPEN: Final[str] = "{"
_OBJECT_CLOSE: Final[str] = "}"
_QUOTE: Final[str] = '"'
_ESCAPE: Final[str] = "\\"


def strip_code_fences(text: str) -> str:
    """Return the body of the first fenced block, or the text unchanged.

    Handles ```` ```json ```` and a bare ```` ``` ````, and an unterminated fence
    (a truncated response often loses its closing one).
    """
    start = text.find(_FENCE_OPEN)
    if start == -1:
        return text
    after_open = text.find("\n", start)
    if after_open == -1:
        return text
    body_start = after_open + 1
    close = text.find(_FENCE_OPEN, body_start)
    body = text[body_start:] if close == -1 else text[body_start:close]
    return body.strip() or text


def extract_first_json_object(text: str) -> str | None:
    """Return the first balanced ``{...}`` span, ignoring braces inside strings.

    This is what rescues chain-of-thought prose wrapped around a perfectly good object.
    Returns ``None`` when no object starts, or when one starts but never closes.
    """
    start = text.find(_OBJECT_OPEN)
    if start == -1:
        return None
    depth = 0
    is_in_string = False
    is_escaped = False
    for index in range(start, len(text)):
        char = text[index]
        if is_escaped:
            is_escaped = False
            continue
        if char == _ESCAPE and is_in_string:
            is_escaped = True
            continue
        if char == _QUOTE:
            is_in_string = not is_in_string
            continue
        if is_in_string:
            continue
        if char == _OBJECT_OPEN:
            depth += 1
        elif char == _OBJECT_CLOSE:
            depth -= 1
            if depth == 0:
                return text[start : index + 1]
    return None


def _repair(text: str) -> str | None:
    """Run the repairer. It is a third party, so it is allowed to fail, not to raise."""
    try:
        repaired = repair_json(text)
    except Exception:  # a third-party repairer that raises is simply a failed candidate
        return None
    return repaired if isinstance(repaired, str) and repaired.strip() else None


def _candidate_texts(raw_text: str) -> tuple[tuple[str, str], ...]:
    """Ordered ``(stage_name, text)`` attempts, cheapest and most literal first."""
    unfenced = strip_code_fences(raw_text).strip()
    extracted = extract_first_json_object(unfenced)
    stages: list[tuple[str, str]] = [("verbatim", raw_text.strip()), ("unfenced", unfenced)]
    if extracted is not None:
        stages.append(("extracted", extracted))
    repaired_extracted = _repair(extracted) if extracted is not None else None
    if repaired_extracted is not None:
        stages.append(("repaired_extracted", repaired_extracted))
    repaired = _repair(unfenced)
    if repaired is not None:
        stages.append(("repaired", repaired))

    seen: set[str] = set()
    unique: list[tuple[str, str]] = []
    for stage, text in stages:
        if text and text not in seen:
            seen.add(text)
            unique.append((stage, text))
    return tuple(unique)


@dataclass(frozen=True, slots=True)
class _Attempt:
    """One stage's outcome, kept for the failure log. Immutable by construction."""

    stage: str
    reason: str


def _load_object(text: str) -> tuple[dict[str, Any] | None, str]:
    """Parse ``text`` to a JSON object. Returns ``(object_or_None, reason)``."""
    try:
        loaded = json.loads(text)
    except (ValueError, RecursionError) as exc:
        return None, f"json.loads failed: {exc}"
    if not isinstance(loaded, dict):
        return None, f"payload is {type(loaded).__name__}, expected a JSON object"
    return loaded, ""


def parse_model_json[M: BaseModel](
    raw_text: str | None,
    response_model: type[M],
    *,
    provider: str,
    finish_reason: str | None = None,
) -> Result[M]:
    """Turn model output into a validated ``response_model``, or a typed ``Err``.

    Never raises. Never returns unvalidated data. Never casts.
    """
    if raw_text is None or not raw_text.strip():
        return _fail(
            raw_text or "",
            response_model,
            provider=provider,
            finish_reason=finish_reason,
            attempts=(_Attempt("empty", "model returned no text"),),
        )

    attempts: list[_Attempt] = []
    for stage, text in _candidate_texts(raw_text):
        payload, reason = _load_object(text)
        if payload is None:
            attempts.append(_Attempt(stage, reason))
            continue
        try:
            return ok(response_model.model_validate(payload))
        except PydanticValidationError as exc:
            attempts.append(_Attempt(stage, f"schema mismatch: {exc.errors(include_url=False)}"))

    return _fail(
        raw_text,
        response_model,
        provider=provider,
        finish_reason=finish_reason,
        attempts=tuple(attempts),
    )


def _fail[M: BaseModel](
    raw_text: str,
    response_model: type[M],
    *,
    provider: str,
    finish_reason: str | None,
    attempts: tuple[_Attempt, ...],
) -> Err:
    last_reason = attempts[-1].reason if attempts else "no parse candidates"
    context = {
        "provider": provider,
        "response_model": response_model.__name__,
        "finish_reason": finish_reason,
        "raw_payload": raw_text[:MAX_LOGGED_PAYLOAD_CHARS],
        "raw_payload_chars": len(raw_text),
        "parse_stages": [attempt.stage for attempt in attempts],
        "parse_error": last_reason,
    }
    _LOG.error(
        "LLM JSON parse failed after %d stage(s) for %s",
        len(attempts),
        response_model.__name__,
        extra=context,
    )
    return err(
        LlmParseError(
            f"{provider} returned output that failed strip -> parse -> repair -> validate "
            f"for {response_model.__name__}: {last_reason}",
            provider=provider,
            context=context,
        )
    )
