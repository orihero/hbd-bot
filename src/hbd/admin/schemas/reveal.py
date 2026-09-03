"""The wire shape of ``POST /reveal`` — §12.3's body, and the plaintext that comes back.

**One endpoint, one body, one closed field vocabulary.** §12.2: "every ``A`` cell routes
through the same ``POST /reveal`` endpoint. One reveal path, one audit shape, one budget —
multiple reveal endpoints is how one of them ends up unaudited." So the *subject* and the
*fields* are request data rather than route data, and both come from closed enums: a reveal
of a column nobody listed here is a 422, not a new route.

**Field values are the audit log's ``field_names``, spelled as the columns they name.**
``hbd.db.admin.audit._FIELD_NAME_PATTERN`` is ``^[a-z][a-z0-9_.]{0,63}$`` and a value that
fails it raises ``AuditValueRejectedError`` deep inside ``append`` — which
``audit_sink._append`` would swallow, retry with ``subject_id=None, ip=None`` and hand back
a 200 carrying an audit row that has lost the subject and the address. So the enum's values
are exactly ``table.column``, lowercase and dotted, and they go onto the row verbatim. A
camelCase wire name here would be an un-attributable reveal that looked like a successful one.

**Two record shapes, and the difference is the budget.** A name, a note or a lyric is one
record: one string, one unit charged, ``record_count=1``. The free text on an order's
generation attempts is many — one per attempt — so it pages at
:data:`~hbd.admin.security.budget.MAX_RECORDS_PER_REVEAL` and charges the page. §12.3 fixes
that cap at fifty bodies and requires a ``nextCursor`` that costs "a fresh reveal with a
``nextCursor``, each one charged and each one audited". Mixing the two shapes in one request
is refused, because a single ``record_count`` cannot honestly describe a mixed reveal, and a
budget can only measure exposure if the number it is handed is the number of records the
caller is authorised to return.

**``subjectId`` is a ``UUID``, and that is a security decision rather than a convenience.**
The step-up scope is compared **whole and byte-exact**
(``permissions.check_step_up``), so an id spelled with braces or in upper-case hex on one
side of the comparison and canonically on the other is a ``STEP_UP_SCOPE_MISMATCH`` nobody
can debug from the 403. Parsing to ``UUID`` here and stringifying once, canonically, means
the handler and ``POST /auth/step-up`` agree on one spelling — the same lowercase, unbraced
``str(uuid)`` every response in this API already carries.

**Nothing here touches the revealed value.** No ``.strip()``, no ``.normalize()``, no case
folding, no re-encoding: the reveal is the one path that returns the customer's string
whole, and ``NFKD`` folds U+02BB — correct Uzbek Latin orthography and the datum this
product exists to get right — into a plain apostrophe. ``reasonText`` *is* cleaned, and that
is not an exception: it is the **operator's** text, and §12.3 requires control characters
stripped from it before it reaches a 90-day column.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from enum import StrEnum
from types import MappingProxyType
from typing import Annotated, Final, Self
from uuid import UUID

from pydantic import Field, JsonValue, field_validator, model_validator

from hbd.admin.schemas.common import ApiModel
from hbd.admin.security.budget import MAX_RECORDS_PER_REVEAL
from hbd.db.enums import AuditReasonCode
from hbd.db.models.admin_audit import REASON_REF_LENGTH, REASON_TEXT_LENGTH

__all__ = [
    "MAX_CURSOR_CHARS",
    "MAX_REASON_TEXT_CHARS",
    "REASON_REF_PATTERN",
    "FIELD_SHAPES",
    "RevealShape",
    "RevealSubjectType",
    "RevealField",
    "RevealRequest",
    "RevealedRecord",
    "RevealBudgetView",
    "RevealResponse",
]

#: §12.3: "``reasonText`` is optional, capped at 500 chars, control chars stripped, and
#: lives on the audit log's 90-day reason clock." The cap is the column's, not a second
#: number: ``admin_audit_log.reason_text`` is ``String(500)``.
MAX_REASON_TEXT_CHARS: Final[int] = REASON_TEXT_LENGTH

#: ``^[A-Za-z0-9#_-]{1,64}$`` — §5.4's shape for a ticket reference, restated here so the
#: refusal is a 422 naming the field rather than an ``AuditValueRejectedError`` raised
#: half-way through the audit append. Note that ``audit._CREDENTIAL_SHAPES`` additionally
#: refuses any ``[A-Za-z0-9_-]{40,}`` run, so a 40-character ticket slug is legal by this
#: pattern and still refused by the audit boundary; that disagreement is the plan's, and it
#: surfaces as a 422 rather than as a reveal with an unwritten row.
REASON_REF_PATTERN: Final[str] = r"^[A-Za-z0-9#_-]{1,64}$"

#: Matches ``hbd.db.admin.page._MAX_CURSOR_CHARS``. Declared so an oversize cursor is
#: refused by the schema, before it reaches the decoder.
MAX_CURSOR_CHARS: Final[int] = 256


class RevealShape(StrEnum):
    """How many records one reveal of a given field can return.

    Not on the wire — it is derived from ``fields`` and decides the charge, the paging and
    which budget is touched. See :data:`FIELD_SHAPES`.
    """

    #: Exactly one record, unpaged. ``limit`` and ``cursor`` are refused.
    SINGLE = "single"
    #: Up to :data:`~hbd.admin.security.budget.MAX_RECORDS_PER_REVEAL` records, keyset-paged,
    #: and charged against the daily conversation ceiling as well as the hourly record one.
    PAGED = "paged"


class RevealSubjectType(StrEnum):
    """What the reveal is about. A subset of ``audit.SUBJECT_TYPES``, and deliberately so.

    ``audit.SUBJECT_TYPES`` is the closed vocabulary the audit column accepts —
    ``order``/``user``/``asset``/``chat``/``config``/``admin``/``session``/``wizard_draft``/
    ``system``. This enum is the subset ``POST /reveal`` can actually answer for **today**,
    which is one member. §12.3 lists four more subjects (``chat`` bodies, ``wizard_draft``
    keys, moderation detail, audio) and every one of them names a table or a route that does
    not exist yet: ``chat_messages`` and ``moderation_reviews`` are Phase 3, and the audio
    reveal is the asset stream's own route. Listing them here would put values on the wire
    that answer 500, so they arrive with their sources.
    """

    ORDER = "order"


class RevealField(StrEnum):
    """The closed list of columns a reveal may unmask, spelled as ``table.column``.

    The value is what lands in ``admin_audit_log.field_names`` — §12.4: "``field_names``
    records *that* ``briefs.note`` was revealed, never what it said."
    """

    RECIPIENT_NAME_DISPLAY = "briefs.recipient_name_display"
    RECIPIENT_NAME_RAW = "briefs.recipient_name_raw"
    RECIPIENT_LOOKUP_KEY = "briefs.recipient_lookup_key"
    RECIPIENT_CANDIDATES = "briefs.recipient_candidates"
    NOTE = "briefs.note"
    APPROVED_LYRICS = "briefs.approved_lyrics"
    STT_TRANSCRIPT = "generation_attempts.stt_transcript"
    NAME_CANDIDATE_TEXT = "generation_attempts.name_candidate_text"


#: Which shape each field produces. A ``briefs`` column is 1:1 with the order, so it is one
#: record; ``generation_attempts`` has a row per take, so its free text is the paged,
#: transcript-shaped reveal §12.3 caps at fifty bodies.
#:
#: **A note on which table the paged reveal reads, because it is not the one §12.3 names.**
#: §12.3's paged row is ``chat_messages.body`` ("Yes, **paged at ≤50 bodies per reveal**"),
#: and ``chat_messages`` does not exist: §14 creates it in Phase 3, and ``hbd.db.models`` has
#: no ``chat_message.py``. Phase 2 therefore builds the paging, the cap, the cursor and the
#: two-budget charge against the paged, customer-authored free text that *does* exist —
#: ``generation_attempts.stt_transcript`` and ``.name_candidate_text``, which §12.3's own
#: table lists as revealable on the row above. The shape is identical, which is the point:
#: Phase 3 adds two members to :class:`RevealField` and a branch to
#: ``services.reveal.read_records``, not a second endpoint with its own idea of what to
#: charge. Building the machinery against a synthetic source instead would have tested
#: arithmetic; leaving it out would have shipped a budget with no paged reveal to bound.
FIELD_SHAPES: Final[Mapping[RevealField, RevealShape]] = MappingProxyType(
    {
        RevealField.RECIPIENT_NAME_DISPLAY: RevealShape.SINGLE,
        RevealField.RECIPIENT_NAME_RAW: RevealShape.SINGLE,
        RevealField.RECIPIENT_LOOKUP_KEY: RevealShape.SINGLE,
        RevealField.RECIPIENT_CANDIDATES: RevealShape.SINGLE,
        RevealField.NOTE: RevealShape.SINGLE,
        RevealField.APPROVED_LYRICS: RevealShape.SINGLE,
        RevealField.STT_TRANSCRIPT: RevealShape.PAGED,
        RevealField.NAME_CANDIDATE_TEXT: RevealShape.PAGED,
    }
)

#: C0 controls and DEL. Stripped from ``reasonText`` — never from a revealed value.
_CONTROL_CHARS: Final[frozenset[str]] = frozenset(chr(code) for code in (*range(0x20), 0x7F))


class RevealRequest(ApiModel):
    """§12.3's body: ``{subjectType, subjectId, fields[], reasonCode, reasonRef?,
    reasonText?, limit?, cursor?}``.

    ``reasonCode`` has **no default**, which is the whole of "reveal without a ``reasonCode``
    → 422". A default of ``ROUTINE_OPS`` would make the accountability optional and the
    modal value meaningless, which is the failure §5.4's closed vocabulary exists to avoid.
    """

    subject_type: RevealSubjectType
    #: Parsed as a ``UUID`` so it canonicalises; see the module docstring on why the
    #: spelling is load-bearing rather than cosmetic.
    subject_id: UUID
    #: A tuple, so the request model stays frozen and the audit's ``field_names`` is the
    #: same object the handler read.
    fields: Annotated[tuple[RevealField, ...], Field(min_length=1, max_length=len(RevealField))]
    reason_code: AuditReasonCode
    reason_ref: Annotated[
        str | None, Field(default=None, pattern=REASON_REF_PATTERN, max_length=REASON_REF_LENGTH)
    ] = None
    reason_text: Annotated[str | None, Field(default=None, max_length=MAX_REASON_TEXT_CHARS)] = None
    #: The page size a paged reveal is authorised to return, and therefore the number of
    #: units it is charged. Absent means the whole page.
    limit: Annotated[int | None, Field(default=None, ge=1, le=MAX_RECORDS_PER_REVEAL)] = None
    cursor: Annotated[str | None, Field(default=None, max_length=MAX_CURSOR_CHARS)] = None

    @property
    def shape(self) -> RevealShape:
        """The one shape every requested field agrees on — enforced by :meth:`_one_shape`."""
        return FIELD_SHAPES[self.fields[0]]

    @field_validator("reason_text")
    @classmethod
    def _strip_control_chars(cls, value: str | None) -> str | None:
        """§12.3: control chars stripped. Whitespace-only text is no text.

        This is operator-authored, so cleaning it is required rather than forbidden. The
        revealed values go nowhere near here.
        """
        if value is None:
            return None
        cleaned = "".join(char for char in value if char not in _CONTROL_CHARS).strip()
        return cleaned or None

    @model_validator(mode="after")
    def _one_shape(self) -> Self:
        """Refuse a request whose ``record_count`` could not be honest.

        Three refusals, and each one is a way the budget would otherwise stop measuring
        exposure: a repeated field would be audited twice for one read; a mixed request
        would have to charge one number for two record shapes; and ``limit``/``cursor`` on a
        single-record reveal would be a page control on something that has no pages, which
        is how a caller learns to expect one.
        """
        if len(set(self.fields)) != len(self.fields):
            raise ValueError("fields must be distinct; a field revealed twice is audited twice")
        shapes = {FIELD_SHAPES[field] for field in self.fields}
        if len(shapes) != 1:
            raise ValueError(
                "one reveal covers one record shape; ask for the brief's fields and the "
                "attempts' free text in two reveals, each charged and each audited"
            )
        if self.shape is RevealShape.SINGLE and (self.limit is not None or self.cursor is not None):
            raise ValueError("limit and cursor apply to a paged reveal only")
        return self


class RevealedRecord(ApiModel):
    """One record's plaintext, byte-for-byte as it is stored.

    ``fields`` maps a :class:`RevealField` value to the column's value, and ``null`` there
    means **the column is NULL** — never a mask and never an empty string. That distinction
    is §12.3's, and it is why the two purge stamps travel with every record: "no name" and
    "name erased on schedule on 2026-05-14" are different facts about a record, and a screen
    that renders them identically cannot answer the question a data-subject request asks.
    """

    record_id: UUID
    created_at: datetime
    fields: dict[str, JsonValue]
    #: When the 90-day identity sweep cleared this record's name columns.
    identity_purged_at: datetime | None = None
    #: When the 30-day free-text sweep cleared its note, lyric or transcript. One clock,
    #: spelled ``note_purged_at`` on ``briefs`` and ``text_purged_at`` on
    #: ``generation_attempts``; the wire carries the fact, not the column name.
    text_purged_at: datetime | None = None


class RevealBudgetView(ApiModel):
    """What this reveal cost and what is left, for §11.4's ``RevealBudgetMeter``.

    ``*Remaining`` is ``null`` when the counter was not touched — a single-record reveal
    never reads the daily conversation budget — and ``null`` is not zero: a meter rendering
    "0 left" for "not asked" stops an operator doing legitimate work.
    """

    records_charged: int
    records_remaining: int | None = None
    conversations_charged: int
    conversations_remaining: int | None = None


class RevealResponse(ApiModel):
    """Plaintext for the named fields only — never the whole object (§12.3).

    ``recordCount`` is the number **charged and audited**, which is the page size the reveal
    was authorised to return rather than the number of rows it found. An empty result is not
    free: it cost a step-up, a budget charge and an audit row, and a budget that let a miss
    cost nothing would be a budget an operator could probe with.
    """

    subject_type: RevealSubjectType
    subject_id: UUID
    revealed_at: datetime
    reason_code: AuditReasonCode
    record_count: int
    revealed_fields: tuple[RevealField, ...]
    records: tuple[RevealedRecord, ...]
    #: Present only when more records exist. Continuing costs a fresh ``POST /reveal``: a
    #: cursor is a position, never a licence to keep reading on one grant and one charge.
    next_cursor: str | None = None
    budget: RevealBudgetView
