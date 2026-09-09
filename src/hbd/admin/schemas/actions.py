"""The body every §9.2 operator action shares, and the block/unblock pair that is the first.

**One base class, because "why did you do that?" is not per-endpoint.** §12.4: every
destructive action requires a reason, and the reason is a closed code plus an optional ticket
reference rather than free text — "real support reasons read *'Dilnoza asked us to delete her
mother's song'*, so a free-text-only reason would make the longest-clocked, purge-immune table
in the system the place customer names accumulate". :class:`ReasonedRequest` is that rule as a
type, so an action added next quarter inherits the mandatory ``reasonCode``, the validated
``reasonRef`` and the scrubbed ``reasonText`` instead of restating them.
:class:`~hbd.admin.schemas.reveal.RevealRequest` inherits it too — it did not, for one
slice, and the cost was two copies of the control-character scrubber writing one column two
ways with no test comparing them.

The three constants are **declared here** and imported by :mod:`hbd.admin.schemas.reveal`,
which is the reverse of how they started: ``reveal`` spelled them first because it was the
first §9.2 action to ship, and the day a second action needed them the import pointed the
wrong way — the module that owns the rule was importing it from one of its own instances,
and ``RevealRequest`` could not inherit from :class:`ReasonedRequest` without a cycle. They
are not reveal-specific: they are the shapes of ``admin_audit_log``'s own columns. A second
spelling of ``^[A-Za-z0-9#_-]{1,64}$`` is a pattern that disagrees with the audit boundary's
the day somebody widens one of them, which surfaces as ``AuditValueRejectedError`` swallowed
inside ``audit_sink._append`` and a 200 carrying a row that lost its subject.

**Block and unblock are two routes and one request body.** The plan (§9.2) makes the pair
"naturally idempotent; blocking a blocked user is a no-op that still writes an audit row
(pressing it twice is information)", so the state being set is carried by the *path* and never
by a boolean in the body: a single ``POST /block {"isBlocked": false}`` would be an unblock
that audits as a block, and the audit row is the only durable record of which one happened.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Final

from pydantic import Field, field_validator

from hbd.admin.schemas.common import ApiModel
from hbd.db.enums import AuditReasonCode
from hbd.db.models.admin_audit import REASON_REF_LENGTH, REASON_TEXT_LENGTH

__all__ = [
    "CONTROL_CHARACTERS",
    "MAX_REASON_TEXT_CHARS",
    "REASON_REF_PATTERN",
    "ReasonedRequest",
    "UserBlockRequest",
    "UserBlockResultView",
]

#: §12.3: "``reasonText`` is optional, capped at 500 chars, control chars stripped, and lives
#: on the audit log's 90-day reason clock." The cap is the column's, not a second number:
#: ``admin_audit_log.reason_text`` is ``String(500)``.
MAX_REASON_TEXT_CHARS: Final[int] = REASON_TEXT_LENGTH

#: ``^[A-Za-z0-9#_-]{1,64}$`` — §5.4's shape for a ticket reference, restated here so the
#: refusal is a 422 naming the field rather than an ``AuditValueRejectedError`` raised
#: half-way through the audit append. Note that ``audit._CREDENTIAL_SHAPES`` additionally
#: refuses any ``[A-Za-z0-9_-]{40,}`` run, so a 40-character ticket slug is legal by this
#: pattern and still refused by the audit boundary; that disagreement is the plan's, and it
#: surfaces as a 422 rather than as an action with an unwritten row.
REASON_REF_PATTERN: Final[str] = r"^[A-Za-z0-9#_-]{1,64}$"

#: C0 controls and DEL, stripped from ``reasonText`` before it reaches a 90-day column
#: (§12.3). One set for every §9.2 action, the reveal included — two spellings of it meant
#: one column cleaned two ways depending on which endpoint wrote the row, and the day
#: somebody adds U+2028 to one of them that divergence becomes a forged line in whatever
#: renders the reason. Tab, newline and carriage return are inside the range on purpose —
#: this is a one-line justification on an audit row, and a newline in it is a paste accident
#: or an attempt to forge a second line.
CONTROL_CHARACTERS: Final[frozenset[str]] = frozenset(chr(code) for code in (*range(0x20), 0x7F))


class ReasonedRequest(ApiModel):
    """The accountability half of every operator action, and nothing else.

    ``reasonCode`` has **no default**, which is the whole of "an action without a reason is a
    422". A default of ``ROUTINE_OPS`` would make the accountability optional and the modal
    value meaningless, for the §5.4 reason the closed vocabulary exists for.

    :class:`~hbd.admin.schemas.reveal.RevealRequest` inherits this rather than restating it,
    which is the claim the module docstring above makes and is worth keeping true: the trio
    lived in two models with two copies of :meth:`_strip_control_chars`, and nothing compared
    them, so ``admin_audit_log.reason_text`` — one column, one 90-day sweep — was cleaned by
    whichever endpoint happened to write the row.
    """

    reason_code: AuditReasonCode
    #: A ticket reference, not a sentence. Validated here so a bad shape is a 422 naming the
    #: field rather than an ``AuditValueRejectedError`` raised half-way through the append.
    reason_ref: Annotated[
        str | None, Field(default=None, pattern=REASON_REF_PATTERN, max_length=REASON_REF_LENGTH)
    ] = None
    #: Optional, capped at the column's own length, control characters stripped, and on the
    #: audit log's 90-day reason clock. This is the **operator's** text, so cleaning it is
    #: required rather than forbidden — the rule against normalising a value applies to the
    #: customer's strings, which never come near this field.
    reason_text: Annotated[str | None, Field(default=None, max_length=MAX_REASON_TEXT_CHARS)] = None

    @field_validator("reason_text")
    @classmethod
    def _strip_control_chars(cls, value: str | None) -> str | None:
        """§12.3: control chars stripped. Whitespace-only text is no text.

        Declared on the base so every action inherits it. A subclass that redeclared
        ``reason_text`` would silently lose the validator, which is the one thing to watch
        for when adding the next action's body.
        """
        if value is None:
            return None
        cleaned = "".join(char for char in value if char not in CONTROL_CHARACTERS).strip()
        return cleaned or None


class UserBlockRequest(ReasonedRequest):
    """``POST /users/{telegramUserId}/block`` and ``/unblock``.

    A reason and nothing else: which of the two states is being set is carried by the path,
    for the reason the module docstring gives.
    """


class UserBlockResultView(ApiModel):
    """What the account looks like after the action, and when it was set.

    It echoes ``isBlocked`` rather than returning nothing, because the two routes are
    idempotent by design: an operator who pressed block on an already-blocked account has to
    be able to see that the state is what they wanted, and a 204 would leave the panel
    re-reading the list to find out.

    ``changedAt`` is the instant the action was recorded, not "when this account was first
    blocked" — the ``users`` row carries no such column, and inventing one from ``updated_at``
    would report the time of whatever last touched the row.
    """

    telegram_user_id: int
    telegram_user_id_masked: str
    is_blocked: bool
    changed_at: datetime
