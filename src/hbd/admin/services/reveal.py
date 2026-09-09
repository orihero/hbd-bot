"""The reveal itself: plan it, audit it, **then** read it — in that order, on purpose.

§12.3: "**Writes the audit row before the read**, so a reveal that then errors is still
attributable." That sentence inverts the intuitive order and it is the reason this module
exists as something other than four lines in a router.

**Why the ordering is not free.** ``audit_sink.record`` appends into the *request's*
transaction, which ``deps.get_db_session`` commits only on a clean exit — so a row written
"before" the read is rolled back by the very error §12.3 wants it to survive, and a test
shaped "reveal, then assert the row exists" passes under that implementation and under a
correct one alike. So :func:`record_reveal` opens and commits a transaction of its **own**,
and the test that bites is ``test_reveal.py``'s: make the read raise *after* the audit call
and require the row to still be there.

**And why this module does not use** :mod:`hbd.admin.audit_sink`. That module's contract is
"the audit write must not become a new way to fail a request" — right for a login, where an
attacker chooses ``actor_username`` and a 500 on the one unauthenticated route would be the
worse bug. It is exactly wrong here: it catches ``AuditValueRejectedError``, retries once
with ``subject_id=None, ip=None``, and otherwise swallows — so an audit write that failed
would return 200 with the plaintext already on the wire and a row that cannot be attributed
to a subject. An unaudited reveal must not happen, so :func:`record_reveal` lets the failure
through: a malformed operator reason is a 422 naming the fields, and anything else is a 500
with no plaintext in it.

**§9.1 asks for two rows and §12.3 asks for one; this ships one on the happy path and a
second only on failure.** §9.1 classes a reveal as an external action and prescribes an
INTENT row before it and an OUTCOME row after. §12.3 and Phase 2's acceptance both say "the
audit row" (singular) and put ``record_count`` on it — and the panel sums ``recordCount``
across rows (``admin-ui/src/features/audit/auditQuery.ts``), so a second row repeating it
would double every reveal on the one chart §12.3 built the budget to feed. The reconciliation
here: the row committed before the read *is* §9.1's INTENT row and carries the charge; the
OUTCOME row is written only when the read failed, carries ``outcome=ERROR`` and the error
code, and carries **no** ``record_count``, because nothing was disclosed. A successful reveal
is therefore exactly one row. The contradiction is the plan's and is reported rather than
resolved silently.

**The charge is the page size, not the row count.** ``read_records`` runs after the budget
has already been charged for what the reveal was *authorised* to return. Charging the number
found would make an empty result free, which is a budget an operator can probe with; charging
after the read means the unbudgeted read already happened.

Nothing in :func:`read_records` touches a revealed value — no strip, no normalise, no
re-encode. It is the one path in the panel that returns the customer's string whole, and
``NFKD`` folds U+02BB into a plain apostrophe.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, replace
from datetime import datetime
from typing import Final, cast
from uuid import UUID

import sqlalchemy as sa
from pydantic import JsonValue
from sqlalchemy.ext.asyncio import AsyncSession

from hbd.admin.container import AdminContainer
from hbd.admin.deps import CurrentAdmin
from hbd.admin.errors import AdminErrorCode, AdminProblem, ProblemError, unwrap
from hbd.admin.schemas.reveal import (
    FIELD_SHAPES,
    RevealedRecord,
    RevealField,
    RevealRequest,
    RevealShape,
    RevealSubjectType,
)
from hbd.admin.security.budget import MAX_RECORDS_PER_REVEAL
from hbd.db.admin.audit import AuditEntry, AuditValueRejectedError, append
from hbd.db.admin.page import (
    Cursor,
    PageRequest,
    build_page,
    keyset_order,
    keyset_predicate,
    page_request,
)
from hbd.db.enums import AuditAction
from hbd.db.models.admin_audit import ACTOR_USERNAME_LENGTH, AuditOutcome
from hbd.db.models.brief import BriefRow
from hbd.db.models.generation_attempt import GenerationAttemptRow
from hbd.db.models.order import OrderRow
from hbd.db.models.user import UserRow
from hbd.db.models.user_profile import UserProfileRow
from hbd.errors import ErrorCode
from hbd.logging import get_logger

__all__ = [
    "BRIEF_COLUMNS",
    "ATTEMPT_COLUMNS",
    "PROFILE_COLUMNS",
    "RevealPlan",
    "RevealResult",
    "plan_reveal",
    "audit_subject_id",
    "reveal_entry",
    "record_reveal",
    "read_records",
    "perform_reveal",
]

_LOGGER: Final = get_logger(__name__)

#: The ``briefs`` columns each single-record field reads, as attributes of the row. A table
#: rather than a chain of ``if``s, and a ``Mapping`` rather than a ``dict.get`` default, so a
#: field added to :class:`~hbd.admin.schemas.reveal.RevealField` with no source here raises
#: instead of answering ``null`` as though the column were empty — which is the one answer
#: this endpoint must never invent, since ``null`` means "purged" (§12.3).
#: ``test_reveal.test_every_reveal_field_has_a_column_behind_it`` asserts the cover.
BRIEF_COLUMNS: Final[Mapping[RevealField, str]] = {
    RevealField.RECIPIENT_NAME_DISPLAY: "recipient_name_display",
    RevealField.RECIPIENT_NAME_RAW: "recipient_name_raw",
    RevealField.RECIPIENT_LOOKUP_KEY: "recipient_lookup_key",
    RevealField.RECIPIENT_CANDIDATES: "recipient_candidates",
    RevealField.NOTE: "note",
    RevealField.APPROVED_LYRICS: "approved_lyrics",
}

#: The same for ``generation_attempts``.
ATTEMPT_COLUMNS: Final[Mapping[RevealField, str]] = {
    RevealField.STT_TRANSCRIPT: "stt_transcript",
    RevealField.NAME_CANDIDATE_TEXT: "name_candidate_text",
}

#: The ``user_profiles`` columns each user-subject field reads. Same table-not-a-chain-of-ifs
#: rule as its two siblings: a field with no source here raises rather than answering
#: ``null``, which on this endpoint means "the column is NULL" and is a fact about the
#: customer rather than a fact about our code.
PROFILE_COLUMNS: Final[Mapping[RevealField, str]] = {
    RevealField.USER_PHONE_E164: "phone_e164",
    RevealField.USER_FIRST_NAME: "first_name",
    RevealField.USER_LAST_NAME: "last_name",
    RevealField.USER_TELEGRAM_USERNAME: "telegram_username",
}


@dataclass(frozen=True, slots=True)
class RevealPlan:
    """A validated reveal, with the numbers the budget and the audit row both read.

    ``subject_id`` is the canonical ``str(uuid)`` — lowercase and unbraced — and it is the
    right half of the step-up scope. It is computed once, here, so the handler cannot spell
    it one way for the guard and another for the audit row.
    """

    subject_type: RevealSubjectType
    subject_uuid: UUID
    subject_id: str
    fields: tuple[RevealField, ...]
    shape: RevealShape
    #: What the reveal may return, and therefore what it is charged and what is audited.
    records_authorised: int
    #: ``1`` for a paged transcript page, ``0`` otherwise — §12.3's separate daily ceiling.
    conversations_charged: int
    page: PageRequest | None


@dataclass(frozen=True, slots=True)
class RevealResult:
    """What the read produced: the records, and where the next page starts."""

    records: tuple[RevealedRecord, ...]
    next_cursor: str | None


def plan_reveal(body: RevealRequest) -> RevealPlan:
    """Turn a validated body into the plan the rest of the request is driven from.

    Raises :class:`ProblemError` (422) for a cursor this API did not mint —
    ``page_request`` is a never-throw boundary returning ``Result``, because a cursor is
    attacker-supplied text off a query string, and ``unwrap`` is where it becomes an
    envelope.
    """
    shape = FIELD_SHAPES[body.fields[0]]
    if shape is RevealShape.SINGLE:
        return RevealPlan(
            subject_type=body.subject_type,
            subject_uuid=body.subject_id,
            subject_id=str(body.subject_id),
            fields=body.fields,
            shape=shape,
            records_authorised=1,
            conversations_charged=0,
            page=None,
        )
    limit = MAX_RECORDS_PER_REVEAL if body.limit is None else body.limit
    page = unwrap(page_request(limit=limit, cursor=body.cursor))
    return RevealPlan(
        subject_type=body.subject_type,
        subject_uuid=body.subject_id,
        subject_id=str(body.subject_id),
        fields=body.fields,
        shape=shape,
        records_authorised=page.limit,
        conversations_charged=1,
        page=page,
    )


async def audit_subject_id(db: AsyncSession, plan: RevealPlan) -> str:
    """The id ``admin_audit_log`` files this subject under — **one id space per subject type**.

    ``subject_type="user"`` rows are written by three paths in this package, and they must
    agree on what a "user" is keyed by or the log answers half a question and reads like the
    whole one. ``users.py::_block_entry`` and ``credits.py::_grant_entry`` file under the
    **Telegram id**, because that is the only identifier those two routes ever hold — the
    block writer and the credit ledger are both keyed on it, and neither has a ``users.id``
    to use. A reveal arrives with the opposite half: ``RevealRequest.subject_id`` is the
    ``user_profiles`` primary key, for the byte-exact step-up comparison the request model's
    docstring argues at length. Filed as-is, ``GET /audit?subjectType=user&subjectId=…``
    returns the blocks and the grants for one customer and silently omits every reveal of
    their phone number, or the reveals and neither action, with nothing in either answer
    saying a second key exists. A DSAR or an abuse investigation then gets half the trail.

    So the reveal is translated **here and only here**: one indexed lookup on ``users.id``,
    and the step-up keeps the UUID it is compared against. ``None`` — a ``user_profiles``
    row whose ``users`` row is gone — falls back to the UUID rather than dropping the
    subject: the read below is about to 404 anyway, and an audit row that lost its subject
    is worse than one filed under the only id we still have.
    """
    if plan.subject_type is not RevealSubjectType.USER:
        return plan.subject_id
    telegram_user_id: int | None = await db.scalar(
        sa.select(UserRow.telegram_user_id).where(UserRow.id == plan.subject_uuid)
    )
    return plan.subject_id if telegram_user_id is None else str(telegram_user_id)


def reveal_entry(
    admin: CurrentAdmin,
    *,
    body: RevealRequest,
    plan: RevealPlan,
    records_charged: int,
    subject_id: str,
) -> AuditEntry:
    """The ``REVEAL_PERSONAL`` row §12.3 requires, with the columns a reveal actually fills.

    ``subject_id`` is a parameter rather than ``plan.subject_id`` because the audit log's id
    space and the step-up's are not the same for every subject type; :func:`audit_subject_id`
    owns that translation and says why.

    ``audit_sink.auth_entry`` cannot be reused: it hardcodes ``subject_type="admin"`` and
    ``reason_code=ROUTINE_OPS`` and carries no ``record_count``, ``reason_ref`` or
    ``reason_text`` — which is every column that makes a reveal row worth keeping for 730
    days.

    ``field_names`` records *that* a column was revealed, never what it said (§12.4), and
    ``record_count`` is the number **charged**, so ``/audit`` and the dashboard measure
    exposure rather than clicks.

    ``correlation_id`` is deliberately not set. ``audit._CORRELATION_PATTERN`` refuses
    anything outside ``^[0-9a-zA-Z._-]{1,128}$``, and the placeholder this process uses when
    no id has been bound is not a correlation id; a reveal that 500'd because its own audit
    row refused a placeholder would be the audit write failing the request for a reason that
    has nothing to do with the reveal.
    """
    return AuditEntry(
        action=AuditAction.REVEAL_PERSONAL,
        actor_id=admin.admin_user_id,
        actor_username=admin.username[:ACTOR_USERNAME_LENGTH],
        actor_role=admin.role,
        subject_type=plan.subject_type.value,
        subject_id=subject_id,
        field_names=tuple(field.value for field in plan.fields),
        record_count=records_charged,
        reason_code=body.reason_code,
        reason_ref=body.reason_ref,
        reason_text=body.reason_text,
        outcome=AuditOutcome.OK,
        ip=admin.client_ip,
    )


async def record_reveal(container: AdminContainer, entry: AuditEntry, *, now: datetime) -> None:
    """Commit the audit row in a transaction of its own — **and fail the reveal if it cannot**.

    Its own transaction because the request's is what a failed read rolls back, and this row
    has to outlive exactly that. Allowed to raise because §9.1's rule is that an unaudited
    action must be impossible: a swallowed audit failure here is a 200 with plaintext in it
    and nothing in the log.

    ``AuditValueRejectedError`` is the one failure that is the caller's fault rather than a
    bug — ``reasonRef`` and ``reasonText`` are operator-supplied and the audit boundary
    refuses credential-shaped values, including any 40-character alphanumeric run — so it
    becomes a 422 naming the two fields. Everything else propagates as a 500.
    """
    key = container.settings.admin_audit_hmac_key.get_secret_value()
    try:
        async with container.session_factory.begin() as db:
            await append(db, entry, key=key, now=now)
    except AuditValueRejectedError as exc:
        # ``exception`` rather than ``error``: a value that reached the audit boundary and
        # was refused is an incident, and the frame that built the entry is what tells an
        # operator which of the two operator-supplied fields did it.
        _LOGGER.exception(
            "a reveal was refused because its audit row could not be written",
            extra={"event": "admin.reveal.audit_refused", "admin_username": entry.actor_username},
        )
        raise ProblemError(
            AdminProblem(
                code=ErrorCode.INVALID_INPUT,
                message="this reveal could not be audited; check reasonRef and reasonText",
            )
        ) from exc


async def record_reveal_outcome(
    container: AdminContainer, entry: AuditEntry, *, error_code: str, now: datetime
) -> None:
    """§9.1's OUTCOME row, written only when the read failed. Never raises.

    ``record_count`` is cleared: nothing was disclosed, and the dashboard sums that column.
    This one *is* best-effort — the request is already failing, and a second exception here
    would replace the operator's real error with an audit one. The INTENT row is already
    committed, so the reveal stays attributable either way.
    """
    outcome = replace(
        entry,
        outcome=AuditOutcome.ERROR,
        record_count=None,
        error_code=error_code,
        reason_text=None,
    )
    key = container.settings.admin_audit_hmac_key.get_secret_value()
    try:
        async with container.session_factory.begin() as db:
            await append(db, outcome, key=key, now=now)
    except Exception:
        # Broad on purpose: see the docstring. The outcome row is the second-best record of
        # an event the first row already carries.
        _LOGGER.exception(
            "could not write the outcome row for a failed reveal",
            extra={"event": "admin.reveal.outcome_write_failed"},
        )


async def read_records(db: AsyncSession, plan: RevealPlan) -> RevealResult:
    """The read itself. Runs **after** the charge and the audit row, never before.

    **The subject is tested before the shape, and the order is load-bearing.** Every
    ``user_profiles`` column is ``SINGLE``, exactly like every ``briefs`` column, so a shape
    test alone routes a phone reveal into :func:`_read_brief` keyed by a ``users.id`` — and
    the shape assertion in ``test_reveal.py`` passes while it happens, because the shape *is*
    right. Two id spaces that happen not to collide are all that stands between that and a
    disclosure of one customer's note under another customer's grant.
    ``schemas.reveal.FIELD_SUBJECTS`` refuses the mixed request at the boundary; this branch
    is the second half of the same rule, at the read, so a body that somehow reached here
    without passing the validator still cannot read the wrong table.

    Reads the columns directly rather than going through :mod:`hbd.admin.schemas.orders`:
    that module's whole contract is that it masks, at every role, with no unmasked variant —
    "a ``to_view(..., is_unmasked=True)`` parameter would be an argument that exists to be
    passed ``True`` by the first caller who finds masking inconvenient". So the one path
    that must not mask does not touch it.
    """
    if plan.subject_type is RevealSubjectType.USER:
        return await _read_user_profile(db, plan)
    if plan.shape is RevealShape.SINGLE:
        return await _read_brief(db, plan)
    return await _read_attempts(db, plan)


async def perform_reveal(
    db: AsyncSession,
    container: AdminContainer,
    *,
    entry: AuditEntry,
    plan: RevealPlan,
    now: datetime,
) -> RevealResult:
    """Audit, then read. The ordering §12.3 specifies, in the one place that owns it.

    A router cannot own this: ruff's ``TRY`` ruleset and this package's own rule keep
    ``try``/``except`` out of handlers, and the OUTCOME row needs one. Keeping the pair here
    also means the two writes cannot drift apart into two files.
    """
    await record_reveal(container, entry, now=now)
    try:
        return await read_records(db, plan)
    except ProblemError as exc:
        await record_reveal_outcome(container, entry, error_code=_code_of(exc), now=now)
        raise
    except Exception:
        await record_reveal_outcome(
            container, entry, error_code=str(AdminErrorCode.INTERNAL_ERROR), now=now
        )
        raise


# ---------------------------------------------------------------------------
# internals
# ---------------------------------------------------------------------------
def _code_of(exc: ProblemError) -> str:
    failure = exc.failure
    code = failure.code if isinstance(failure, AdminProblem) else failure.error_code
    return str(code)


def _not_found(plan: RevealPlan) -> ProblemError:
    """404 from the pipeline taxonomy — ``AdminErrorCode`` has no member for it, by design.

    Names the subject's own id and nothing else — ``no order with id …`` or ``no user with
    id …``, from the plan's own subject type: a UUID the caller just sent back to them is
    not a disclosure, and every other thing the handler knows about this subject is exactly
    what the reveal was refused.
    """
    return ProblemError(
        AdminProblem(
            code=ErrorCode.NOT_FOUND,
            message=f"no {plan.subject_type.value} with id {plan.subject_uuid}",
        )
    )


def _value(row: object, attribute: str) -> JsonValue:
    """One column, untouched. ``None`` stays ``None`` — a purged column is not an empty one.

    No ``strip``, no ``normalise``, no re-encode: the returned object is the one SQLAlchemy
    loaded. ``cast`` rather than a runtime check because the four column types involved
    (``str``, ``dict``, ``list``, ``None``) are all ``JsonValue`` already and a validator
    here would be a second place for the shape to be decided.
    """
    return cast("JsonValue", getattr(row, attribute))


async def _read_user_profile(db: AsyncSession, plan: RevealPlan) -> RevealResult:
    """One customer's contact record, keyed on ``users.id``.

    **Keyed on ``users.id`` and never on the Telegram id**, and that is why the table is
    shaped the way it is: ``RevealRequest.subject_id`` is a ``UUID``, the step-up scope is
    ``reveal:<str(uuid)>`` compared whole and byte-exact, and putting a Telegram integer on
    one side of that comparison would be a ``STEP_UP_SCOPE_MISMATCH`` nobody can debug from
    the 403. ``user_profiles.user_id`` is the primary key, so this is one indexed lookup and
    no join.

    ``identity_purged_at`` and ``text_purged_at`` are both ``None`` here, and the absence is
    the design rather than an omission. ``briefs`` nulls its identity columns in place on a
    clock, so "no name" and "name erased on 2026-05-14" are different facts a stamp has to
    separate. ``user_profiles`` has no clock (PD-2) and ``/forget`` deletes the row outright
    (PD-3), so an erased customer is a **404** and a ``null`` in ``fields`` means one thing
    only: the customer never gave us that datum.
    """
    statement = sa.select(UserProfileRow).where(UserProfileRow.user_id == plan.subject_uuid)
    profile = (await db.execute(statement)).scalars().first()
    if profile is None:
        raise _not_found(plan)
    record = RevealedRecord(
        record_id=profile.user_id,
        created_at=profile.created_at,
        fields={field.value: _value(profile, PROFILE_COLUMNS[field]) for field in plan.fields},
    )
    return RevealResult(records=(record,), next_cursor=None)


async def _read_brief(db: AsyncSession, plan: RevealPlan) -> RevealResult:
    statement = sa.select(BriefRow).where(BriefRow.order_id == plan.subject_uuid)
    brief = (await db.execute(statement)).scalars().first()
    if brief is None:
        raise _not_found(plan)
    record = RevealedRecord(
        record_id=brief.id,
        created_at=brief.created_at,
        fields={field.value: _value(brief, BRIEF_COLUMNS[field]) for field in plan.fields},
        identity_purged_at=brief.identity_purged_at,
        text_purged_at=brief.note_purged_at,
    )
    return RevealResult(records=(record,), next_cursor=None)


async def _read_attempts(db: AsyncSession, plan: RevealPlan) -> RevealResult:
    """One keyset page of an order's attempt free text, newest first.

    The order's existence is checked first so a bogus id is a 404 rather than an empty page
    that looks like an order with nothing to say. It costs one indexed lookup and it is the
    difference between "there is no such order" and "this order has no takes", which are
    different answers to a support question.
    """
    page = plan.page
    if page is None:  # pragma: no cover - plan_reveal always sets one for a paged shape
        raise _not_found(plan)
    exists = await db.scalar(
        sa.select(sa.literal(1)).select_from(OrderRow).where(OrderRow.id == plan.subject_uuid)
    )
    if exists is None:
        raise _not_found(plan)
    statement = sa.select(GenerationAttemptRow).where(
        GenerationAttemptRow.order_id == plan.subject_uuid
    )
    predicate = keyset_predicate(
        GenerationAttemptRow.created_at, GenerationAttemptRow.id, page.cursor
    )
    if predicate is not None:
        statement = statement.where(predicate)
    statement = statement.order_by(
        *keyset_order(GenerationAttemptRow.created_at, GenerationAttemptRow.id)
    ).limit(page.fetch_limit)
    rows = list((await db.execute(statement)).scalars().all())
    records = [
        RevealedRecord(
            record_id=row.id,
            created_at=row.created_at,
            fields={field.value: _value(row, ATTEMPT_COLUMNS[field]) for field in plan.fields},
            identity_purged_at=row.identity_purged_at,
            text_purged_at=row.text_purged_at,
        )
        for row in rows
    ]
    built = build_page(
        records, page, key=lambda record: Cursor(at=record.created_at, id=record.record_id)
    )
    return RevealResult(records=built.items, next_cursor=built.next_cursor)
