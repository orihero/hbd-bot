"""``GET /api/audit`` and ``GET /api/audit/verify`` — reading the log, and checking it holds.

Both routes are reads, and neither writes a row of any kind. That is worth stating because
the obvious convenience — having ``/audit/verify`` drop a fresh chain anchor while it is
already walking the chain — would put a write behind a ``GET``, which the route-enumeration
test forbids and a browser prefetch would trigger. Anchors are written by the retention job
(:func:`hbd.db.admin.audit.write_head_anchor`), on a schedule, in a transaction of its own.

**The guard is ``require_permission`` at the router**, which resolves to ``check_role``. That
is the right question here and ``check_access`` is not: with no subject there is no scope to
compare a step-up against, so ``check_access(subject_id=None)`` would log an ERROR on every
single request to the audit list and then answer ``STEP_UP_REQUIRED`` for a cell that asks for
no step-up at all. §12.2 gives AUDIT_READ as **M** to ADMIN and **R** to OWNER — a role check,
and a masking difference at the response boundary.

**Masking is one field.** ``reason_text`` is the only column an operator can have typed a
customer's name into, so it is the only thing the **M** cell withholds. Which cell applies is
read from the matrix (``grant_for``) rather than by comparing roles here — a second copy of
§12.2 in a router is a copy that eventually disagrees with the first, and the disagreement is
always a grant.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from typing import Annotated, Final
from uuid import UUID

from fastapi import APIRouter, Depends, Query

from hbd.admin.deps import API_PREFIX, Admin, Container, Db, require_permission
from hbd.admin.errors import AdminProblem, ProblemError
from hbd.admin.schemas.audit import (
    AuditPage,
    AuditPageMeta,
    ChainVerifyResponse,
    CursorError,
    decode_cursor,
    encode_cursor,
    to_view,
)
from hbd.admin.security.permissions import Permission, grant_for
from hbd.admin.window import require_aware
from hbd.db.admin.audit import (
    DEFAULT_PAGE_SIZE,
    MAX_PAGE_SIZE,
    AuditQuery,
    list_entries,
    verify_chain,
)
from hbd.db.enums import AuditAction
from hbd.db.models.admin_audit import AdminAuditRow, AuditOutcome
from hbd.errors import ErrorCode
from hbd.logging import get_logger

__all__ = ["build_audit_router"]

_LOGGER: Final = get_logger(__name__)

AUDIT_PATH: Final[str] = f"{API_PREFIX}/audit"
VERIFY_PATH: Final[str] = f"{AUDIT_PATH}/verify"


def _invalid(message: str) -> ProblemError:
    """422 in the pipeline taxonomy — the code the rest of the system already uses for this."""
    return ProblemError(AdminProblem(code=ErrorCode.INVALID_INPUT, message=message))


def _actor(actor: str | None) -> tuple[UUID | None, str | None]:
    """One ``actor`` parameter, matched as an id when it is one and as a username otherwise.

    The panel links to an operator by id and a human types a name; making the caller choose
    the right parameter would mean two ways to ask one question, and a filter silently
    matching nothing when the wrong one is used.
    """
    if not actor:
        return None, None
    try:
        return UUID(actor), None
    except ValueError:
        return None, actor.strip().casefold()


def build_query(
    actor: Annotated[str | None, Query()] = None,
    action: Annotated[list[AuditAction] | None, Query()] = None,
    subject_type: Annotated[str | None, Query(alias="subjectType", max_length=32)] = None,
    subject_id: Annotated[str | None, Query(alias="subjectId", max_length=64)] = None,
    outcome: Annotated[list[AuditOutcome] | None, Query()] = None,
    since: Annotated[datetime | None, Query(alias="from")] = None,
    until: Annotated[datetime | None, Query(alias="to")] = None,
) -> AuditQuery:
    """§6.8's filter set, as a dependency so the handler stays a straight line.

    Repeated ``action`` and ``outcome`` parameters are OR within the field and AND across
    fields (§6.1). Both are typed as enums, so an unknown value is a 422 from FastAPI rather
    than a filter that quietly matches nothing.

    The naive-instant refusal is :func:`hbd.admin.window.require_aware` and not a copy of it.
    This route is the only caller of that check that wants no :class:`TimeWindow`: ``from``
    and ``to`` reach ``AuditQuery`` as two independent bounds, so folding them into a
    half-open interval to share the validator would change a query's shape to reuse twelve
    lines. Importing the check alone is what deleted this module's private sixth copy —
    which was byte-identical and therefore invisible until somebody edited one of the six.
    """
    actor_id, actor_username = _actor(actor)
    return AuditQuery(
        actor_id=actor_id,
        actor_username=actor_username,
        actions=tuple(action or ()),
        subject_type=subject_type,
        subject_id=subject_id,
        outcomes=tuple(outcome or ()),
        since=require_aware("from", since),
        until=require_aware("to", until),
    )


Filters = Annotated[AuditQuery, Depends(build_query)]


def _before_seq(cursor: str | None) -> int | None:
    if cursor is None:
        return None
    try:
        return decode_cursor(cursor)
    except CursorError as exc:
        raise _invalid("that cursor is not one this endpoint issued") from exc


def _page(rows: Sequence[AdminAuditRow], *, limit: int, is_unmasked: bool) -> AuditPage:
    """The rows and the handle for the next page — ``null`` once a page is not full (§6.1)."""
    next_cursor = encode_cursor(rows[-1].seq) if len(rows) == limit and rows else None
    return AuditPage(
        items=[to_view(row, is_unmasked=is_unmasked) for row in rows],
        meta=AuditPageMeta(next_cursor=next_cursor),
    )


def build_audit_router() -> APIRouter:
    """The audit surface. One permission, declared once, on the router."""
    router = APIRouter(
        tags=["audit"],
        dependencies=[Depends(require_permission(Permission.AUDIT_READ))],
    )

    @router.get(AUDIT_PATH)
    async def list_audit(
        admin: Admin,
        db: Db,
        filters: Filters,
        cursor: Annotated[str | None, Query()] = None,
        limit: Annotated[int, Query(ge=1, le=MAX_PAGE_SIZE)] = DEFAULT_PAGE_SIZE,
    ) -> AuditPage:
        """One keyset page of the log, newest first."""
        grant = grant_for(Permission.AUDIT_READ, admin.role)
        rows = await list_entries(db, filters, limit=limit, before_seq=_before_seq(cursor))
        return _page(rows, limit=limit, is_unmasked=grant is not None and grant.is_unmasked)

    @router.get(VERIFY_PATH)
    async def verify(admin: Admin, db: Db, container: Container) -> ChainVerifyResponse:
        """Walk the chain, report the first break, and say what is protecting it."""
        settings = container.settings
        result = await verify_chain(
            db,
            key=settings.admin_audit_hmac_key.get_secret_value(),
            is_dsn_configured=bool(settings.admin_audit_dsn),
        )
        if not result.is_ok:
            _LOGGER.error(
                "the admin audit chain does not verify",
                extra={
                    "event": "admin.audit.chain_broken",
                    "first_break_seq": result.first_break_seq,
                    "admin_username": admin.username,
                },
            )
        return ChainVerifyResponse(
            ok=result.is_ok,
            first_break_seq=result.first_break_seq,
            chain_protection=result.protection,
            checked_rows=result.checked_rows,
            last_seq=result.last_seq,
            is_complete=result.is_complete,
            truncation_points=list(result.anchors),
        )

    return router
