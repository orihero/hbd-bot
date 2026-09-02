"""Whether a stored error code describes something a retry could fix.

``is_retryable`` is a property of the *exception instance* the pipeline raised, and the
instance is gone by the time an operator reads the row: ``generation_attempts.error_code``
and ``orders.failed_reason`` are strings. So the panel has to answer "would retrying help?"
from a string, and the only defensible way to do that is to read the answer off the class
that owns the code rather than to restate it in a table beside :class:`ErrorCode`.

This module therefore walks :class:`HbdError`'s subclass tree once, at import, and builds
``code → default_is_retryable``. A new error class added to ``hbd.errors`` next quarter is
covered without anyone remembering this file exists, which is the whole reason it is derived
and not written out. The build is verified rather than assumed: a code claimed by two classes
that disagree resolves to ``None`` (unknown) instead of to whichever class the walk reached
first, and the disagreement is logged — a silent "retryable" for a terminal failure is how an
operator burns vendor money re-running something that cannot succeed.

**The answer is a hint about the class of failure, not a promise about this order.** The
raising site may pass ``is_retryable=`` per instance and override its class default, and that
per-instance value is not persisted anywhere. §9.4's rule that the retry UI must tell the
operator what it does and does not know is why this returns a tri-state: ``True``, ``False``,
and ``None`` for a code no class claims — today that is ``ARTIST_NAME_IN_STYLE``, which is
raised with an explicit ``code=`` rather than by a class of its own.
"""

from __future__ import annotations

from typing import Final

from hbd.errors import ErrorCode, HbdError
from hbd.logging import get_logger

__all__ = ["RETRYABILITY", "is_retryable_code"]

_LOGGER: Final = get_logger(__name__)


def _walk(root: type[HbdError], claims: dict[ErrorCode, set[bool]]) -> None:
    """Record every subclass's ``(code, default_is_retryable)`` claim, depth first."""
    for subclass in root.__subclasses__():
        claims.setdefault(subclass.code, set()).add(subclass.default_is_retryable)
        _walk(subclass, claims)


def _build() -> dict[ErrorCode, bool | None]:
    """``code → verdict``, with a disagreement collapsing to ``None`` and a log line.

    Every member of :class:`ErrorCode` is present, so a caller never has to distinguish
    "this code is unknown to the map" from "this code has no verdict" — both are ``None``
    and both mean the same thing to the operator reading the screen.
    """
    claims: dict[ErrorCode, set[bool]] = {}
    _walk(HbdError, claims)
    resolved: dict[ErrorCode, bool | None] = {}
    for code in ErrorCode:
        verdicts = claims.get(code, set())
        if len(verdicts) == 1:
            resolved[code] = next(iter(verdicts))
            continue
        if len(verdicts) > 1:
            _LOGGER.warning(
                "error code is claimed by classes that disagree about retryability; the "
                "panel will report it as unknown",
                extra={"event": "admin.retryability.ambiguous", "error_code": str(code)},
            )
        resolved[code] = None
    return resolved


#: Built once at import. A plain dict rather than a mapping proxy: it is module-private in
#: spirit and read through :func:`is_retryable_code`, which is the only supported entry point.
RETRYABILITY: Final[dict[ErrorCode, bool | None]] = _build()


def is_retryable_code(error_code: str | None) -> bool | None:
    """The verdict for a stored code string, or ``None`` when there is not one.

    A string that is not an :class:`ErrorCode` member at all also answers ``None``. That is
    reachable: ``generation_attempts.error_code`` is a ``VARCHAR``, and a writer outside the
    taxonomy — a migration, a hand-written row, a future provider adapter — can put anything
    in it. Guessing on behalf of an unrecognised string is exactly the confident lie this
    module exists to avoid.
    """
    if error_code is None:
        return None
    try:
        code = ErrorCode(error_code)
    except ValueError:
        return None
    return RETRYABILITY[code]
