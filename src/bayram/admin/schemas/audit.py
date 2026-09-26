"""Wire models for ``/api/audit`` and ``/api/audit/verify``, and the keyset cursor.

Two things here are policy rather than shape.

**``reasonText`` is the only maskable field, and it is absent rather than blanked.** §12.2
gives AUDIT_READ as **M** to ADMIN and **R** to OWNER, and the difference between the two
cells is exactly this column: it is the one place in the table an operator can have typed a
customer's name. A masked response omits the field entirely and sets ``hasReasonText``, so
the panel can show "a reason was recorded, you may not read it" instead of implying none was
given — a blanked-out value and an absent one are different facts about the record.

**The cursor is ``seq``, not ``(at, id)``.** §6.1's general rule is the composite, because
most tables order by a caller-set timestamp. This one has a database-assigned monotonic key
that the hash chain already depends on, and ``at`` is supplied by the writer — so paging on
``seq`` is both cheaper and the only ordering that cannot disagree with the chain.

The cursor is opaque but not authenticated, and deliberately so: the worst a forged one can
do is start the page at a different sequence number the caller was already allowed to read.
It is parsed defensively all the same — a malformed value is a 422, never a stack trace.
"""

from __future__ import annotations

import base64
import binascii
import json
from datetime import datetime
from typing import Final
from uuid import UUID

from pydantic import Field

from bayram.admin.schemas.common import ApiModel
from bayram.db.admin.audit import ChainProtection
from bayram.db.enums import AdminRole, AuditAction, AuditReasonCode
from bayram.db.models.admin_audit import AdminAuditRow, AuditOutcome

__all__ = [
    "AuditEntryView",
    "AuditPage",
    "AuditPageMeta",
    "ChainVerifyResponse",
    "CursorError",
    "decode_cursor",
    "encode_cursor",
    "to_view",
]

_CURSOR_KEY: Final[str] = "seq"
#: A cursor is one small integer in a JSON object; anything longer is not one of ours.
_MAX_CURSOR_CHARS: Final[int] = 64


class CursorError(ValueError):
    """A cursor that did not come from :func:`encode_cursor`. The route renders it as 422."""


def encode_cursor(seq: int) -> str:
    """``base64url({"seq": n})``, unpadded — the opaque handle the client sends back."""
    raw = json.dumps({_CURSOR_KEY: seq}, separators=(",", ":")).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def decode_cursor(cursor: str) -> int:
    """The sequence to page below. Raises :class:`CursorError` on anything unexpected."""
    if len(cursor) > _MAX_CURSOR_CHARS:
        raise CursorError("cursor is too long to be one of ours")
    padded = cursor + "=" * (-len(cursor) % 4)
    try:
        payload = json.loads(base64.urlsafe_b64decode(padded.encode("ascii")))
    except (binascii.Error, UnicodeEncodeError, json.JSONDecodeError, ValueError) as exc:
        raise CursorError("cursor is not decodable") from exc
    if not isinstance(payload, dict) or not isinstance(payload.get(_CURSOR_KEY), int):
        raise CursorError("cursor does not carry a sequence number")
    return int(payload[_CURSOR_KEY])


class AuditEntryView(ApiModel):
    """One row as the panel sees it. ``reasonText`` is present only at an unmasked role."""

    seq: int
    id: UUID
    at: datetime
    actor_id: UUID | None
    actor_username: str
    actor_role: AdminRole
    action: AuditAction
    subject_type: str
    subject_id: str | None
    field_names: list[str] | None
    record_count: int | None
    reason_code: AuditReasonCode
    reason_ref: str | None
    #: Whether the row carries operator free text at all, which a masked caller still learns.
    has_reason_text: bool
    reason_text: str | None = None
    outcome: AuditOutcome
    error_code: str | None
    correlation_id: str | None
    ip: str | None
    config_version: int | None
    #: The chain value at this row. Publishing it costs nothing — without the key it cannot be
    #: recomputed — and it is what lets an operator compare a row against the anchor log line.
    chain_hmac: str


class AuditPageMeta(ApiModel):
    """``nextCursor`` is ``null`` at the end of the list, never an empty string (§6.1)."""

    next_cursor: str | None = None


class AuditPage(ApiModel):
    items: list[AuditEntryView]
    meta: AuditPageMeta


class ChainVerifyResponse(ApiModel):
    """§12.4's report: does the chain hold, where does it first not, and what is protecting it.

    ``chainProtection`` is rendered verbatim by the panel. ``isComplete`` is false when the
    walk stopped at its row ceiling, so a clean answer over the first 50 000 rows is never
    read as a clean answer over the whole table.
    """

    ok: bool
    first_break_seq: int | None
    chain_protection: ChainProtection
    checked_rows: int
    last_seq: int | None
    is_complete: bool
    #: Sequence numbers below which rows were deleted on purpose by the 730-day sweep.
    truncation_points: list[int] = Field(default_factory=list)


def to_view(row: AdminAuditRow, *, is_unmasked: bool) -> AuditEntryView:
    """Project one row onto the wire, dropping the free text unless the role may read it."""
    return AuditEntryView(
        seq=row.seq,
        id=row.id,
        at=row.at,
        actor_id=row.actor_id,
        actor_username=row.actor_username,
        actor_role=row.actor_role,
        action=row.action,
        subject_type=row.subject_type,
        subject_id=row.subject_id,
        field_names=row.field_names,
        record_count=row.record_count,
        reason_code=row.reason_code,
        reason_ref=row.reason_ref,
        has_reason_text=row.reason_text is not None,
        reason_text=row.reason_text if is_unmasked else None,
        outcome=row.outcome,
        error_code=row.error_code,
        correlation_id=row.correlation_id,
        ip=row.ip,
        config_version=row.config_version,
        chain_hmac=row.chain_hmac,
    )
