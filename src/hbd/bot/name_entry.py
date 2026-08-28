"""The name step: typed text in, a fully resolved :class:`RecipientName` out.

This is the one place in the bot that touches the name subsystem, and the one place where
the product's central distinction is made concrete:

* ``display`` — canonicalised with U+02BB, echoed back to the user for confirmation, and
  the only spelling that ever reaches a screen or the lyric sheet;
* ``candidates`` — the ranked vendor-facing spellings, in the order
  ``Settings.name_candidate_order`` puts them. Nobody ever sees these.

**This module resolves nothing itself.** It is a thin adapter over
``hbd.names.resolve.resolve_name`` — the resolver the 77-name golden set fences — and its
whole job is to turn that function's machine-readable ``reason`` into the locale key this
user should be shown. It used to carry a second, weaker implementation of the same logic,
which accepted ``Bekzod123``, ``王小明`` and ``Ali <script>`` and rendered ``gulomjon``
uncapitalised on the lyric sheet, because the golden fence guarded a function the bot did
not call. One resolver, one fence, one behaviour.

Nothing here raises. A name we cannot read comes back as an ``Err`` carrying the locale
key the user should be shown, so the handler has no branching of its own to get wrong.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Final

from hbd.contracts import (
    MAX_RECIPIENT_NAME_CHARS,
    Err,
    Language,
    NameStrategy,
    RecipientName,
    Result,
    err,
)
from hbd.errors import ValidationError
from hbd.logging import get_logger
from hbd.names.resolve import MAX_NAME_WORDS, resolve_name

__all__ = [
    "resolve_typed_name",
    "NAME_INVALID_KEY",
    "NAME_TOO_LONG_KEY",
    "NAME_TOO_MANY_WORDS_KEY",
    "NAME_UNRESOLVED_KEY",
]

_LOG = get_logger(__name__)

NAME_INVALID_KEY: Final[str] = "wizard.name.invalid"
NAME_TOO_LONG_KEY: Final[str] = "wizard.name.too_long"
NAME_TOO_MANY_WORDS_KEY: Final[str] = "wizard.name.too_many_words"
NAME_UNRESOLVED_KEY: Final[str] = "wizard.name.unresolved"

#: ``resolve_name`` reason -> the message this user should read. A reason with no entry
#: falls back to ``NAME_UNRESOLVED_KEY``, so a new rejection reason degrades to a polite
#: "please type it again" rather than to a missing-key placeholder.
_KEY_BY_REASON: Final[dict[str, str]] = {
    "empty": NAME_INVALID_KEY,
    "no_letters": NAME_INVALID_KEY,
    "unsupported_character": NAME_INVALID_KEY,
    "too_long": NAME_TOO_LONG_KEY,
    "too_many_words": NAME_TOO_MANY_WORDS_KEY,
    "unsupported_script": NAME_UNRESOLVED_KEY,
    "no_key": NAME_UNRESOLVED_KEY,
}

#: The ``{limit}`` each message interpolates. A key absent here takes no limit.
_LIMIT_BY_KEY: Final[dict[str, int]] = {
    NAME_TOO_LONG_KEY: MAX_RECIPIENT_NAME_CHARS,
    NAME_TOO_MANY_WORDS_KEY: MAX_NAME_WORDS,
}


def resolve_typed_name(
    typed: str,
    *,
    ui_language: Language,
    candidate_order: Sequence[NameStrategy],
) -> Result[RecipientName]:
    """Validate and resolve what the user typed. Never raises.

    ``ui_language`` is only a fallback for inferring the *name's* language: a Latin name
    typed by a Russian-speaking user is still an Uzbek Latin name, and the interface
    language must not distort the candidates.
    """
    resolved = resolve_name(typed, candidate_order=candidate_order, ui_language=ui_language)
    if isinstance(resolved, Err):
        return _localised(resolved)

    recipient = resolved.value
    _LOG.info(
        "recipient name resolved",
        extra={
            "name_language": str(recipient.language),
            "script": str(recipient.script),
            "candidate_count": len(recipient.candidates),
            "strategies": [str(candidate.strategy) for candidate in recipient.candidates],
        },
    )
    return resolved


def _localised(rejection: Err) -> Err:
    """Re-wrap a resolver rejection with the locale key and ``{limit}`` its message needs.

    The original context is carried through unchanged so the operator log still shows the
    machine-readable ``reason`` next to the human-readable key.
    """
    error = rejection.error
    reason = str(error.context.get("reason", ""))
    key = _KEY_BY_REASON.get(reason, NAME_UNRESOLVED_KEY)
    context: dict[str, object] = dict(error.context)
    limit = _LIMIT_BY_KEY.get(key)
    if limit is not None:
        context["limit"] = limit
    return err(
        ValidationError(
            error.operator_message,
            user_message_key=key,
            context=context,
            cause=error,
        )
    )
