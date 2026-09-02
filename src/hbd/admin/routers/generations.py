"""``GET /api/generations`` and ``GET /api/generations/{attempt_id}`` — the render ledger.

**The wire model is :mod:`hbd.admin.schemas.orders`' and this module declares none of its
own.** ``AttemptWireView`` is already the projection of a ``generation_attempts`` row — the
order detail screen renders it — and a ``schemas/generations.py`` holding a second one would
be two views of one table. Two views of one table drift: the next privacy fix lands on the
copy whose screen somebody was looking at, and the other one keeps shipping the field that
was supposed to have been withdrawn. There is exactly one projection of this row in this
codebase, :func:`~hbd.admin.schemas.orders.to_attempt_view`, so the masking it applies is
applied everywhere the row is read.

**``isOrphaned`` selects attempts with no order, and it deliberately cannot say which kind.**
``order_id`` is nullable with ``ON DELETE SET NULL`` (``models/generation_attempt.py``): a
name preview is rendered *before* an order exists, and an attempt whose order was deleted
keeps its tuning signal, which is the entire reason the FK sets null instead of cascading —
the bake-off data has to outlive the orders it was collected from. Both reach the query as
``order_id IS NULL`` and nothing in the row tells them apart. Reporting a guess about which
one an operator is looking at would be worse than reporting the fact that they look
identical, so this filter states one predicate and the docstring states its two causes.

**``costUsd`` and ``latencyMs`` are ``null``, not ``0``, and ``isInstrumented`` says which
kind of row it is.** The columns default to ``0.0`` and ``0`` and nothing in ``src/`` writes
either, so every row in production today is uninstrumented. Rendering the defaults as
"$0.00 / 0 ms" on the one screen an operator uses to decide what to spend would be a
confident lie — and once Phase 5 starts writing real numbers it would be indistinguishable
from a genuinely free, instantaneous vendor call. ``attempts._telemetry`` reads a zero as
"never written"; this router simply does not undo that.

**The guard is ``require_permission`` at the router**, which resolves to ``check_role``:
there is no subject to weigh a step-up against on a list, and RECORDS_READ asks for none.
§12.2 gives RECORDS_READ as **M** to all four roles *including OWNER*, so there is no
unmasked cell to choose between and neither handler takes an ``Admin`` — taking the operator
in order to ignore them would imply a masking decision that does not exist. Plaintext for
``name_candidate_text`` and ``stt_transcript`` arrives through ``POST /reveal`` in Phase 2,
never from here.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Final
from uuid import UUID

from fastapi import APIRouter, Depends, Query

from hbd.admin.deps import API_PREFIX, Db, require_permission
from hbd.admin.errors import AdminProblem, ProblemError, unwrap
from hbd.admin.schemas.orders import AttemptsPage, AttemptWireView, to_attempt_view
from hbd.admin.schemas.page import Paging, page_meta
from hbd.admin.security.permissions import Permission
from hbd.contracts import NameStrategy
from hbd.db.admin.attempts import AttemptFilters, count_attempts, get_attempt, list_attempts
from hbd.db.admin.sql import TimeWindow, time_window
from hbd.db.enums import GenerationKind
from hbd.db.models.generation_attempt import ERROR_CODE_LENGTH, PROVIDER_LENGTH
from hbd.errors import ErrorCode

__all__ = ["GENERATIONS_PATH", "ATTEMPT_PATH", "build_generations_router"]

GENERATIONS_PATH: Final[str] = f"{API_PREFIX}/generations"
ATTEMPT_PATH: Final[str] = f"{GENERATIONS_PATH}/{{attempt_id}}"


def _invalid(message: str) -> ProblemError:
    """422 in the pipeline taxonomy — the code the rest of the system already uses for this."""
    return ProblemError(AdminProblem(code=ErrorCode.INVALID_INPUT, message=message))


def _aware(name: str, value: datetime | None) -> datetime | None:
    """Refuse a naive instant (§6.1): the column is ``timestamptz`` and would raise anyway."""
    if value is not None and value.tzinfo is None:
        raise _invalid(f"{name} must carry a UTC offset, e.g. 2026-08-30T12:00:00Z")
    return value


def _window(since: datetime | None, until: datetime | None) -> TimeWindow | None:
    """``from`` and ``to`` are a pair — both, or neither.

    A one-sided window has to invent its missing bound and both candidates are a lie about
    what was asked for. The epoch is a bound nobody typed, and ``now`` is re-evaluated on
    every request — so a keyset walk down a ``?from=`` result would quietly widen its own
    filter between page one and page two, which is the drift the opaque cursor exists to
    prevent. Refusing the half-window costs a caller one extra parameter and costs nobody a
    page of rows that silently changed shape underneath them.
    """
    start = _aware("from", since)
    end = _aware("to", until)
    if start is None and end is None:
        return None
    if start is None or end is None:
        raise _invalid("from and to are a pair: send both bounds of the window, or neither")
    return unwrap(time_window(start, end))


def build_query(
    kind: Annotated[list[GenerationKind] | None, Query()] = None,
    provider: Annotated[str | None, Query(max_length=PROVIDER_LENGTH)] = None,
    is_success: Annotated[bool | None, Query(alias="isSuccess")] = None,
    error_code: Annotated[
        str | None, Query(alias="errorCode", max_length=ERROR_CODE_LENGTH)
    ] = None,
    strategy: Annotated[NameStrategy | None, Query()] = None,
    is_orphaned: Annotated[bool | None, Query(alias="isOrphaned")] = None,
    since: Annotated[datetime | None, Query(alias="from")] = None,
    until: Annotated[datetime | None, Query(alias="to")] = None,
) -> AttemptFilters:
    """§6.7's filter set, as a dependency so the handler stays a straight line.

    Repeated ``kind`` parameters are OR within the field and AND across fields (§6.1).
    ``kind`` and ``strategy`` are typed as enums, so an unknown value is a 422 from FastAPI
    rather than a filter that quietly matches nothing; ``provider`` and ``errorCode`` are
    free-form because their vocabularies are a vendor's and the pipeline's respectively, so
    they are bounded by the column widths they will be compared against instead.
    """
    return AttemptFilters(
        kinds=tuple(kind or ()),
        provider=provider,
        is_success=is_success,
        error_code=error_code,
        strategy=strategy,
        is_orphaned=is_orphaned,
        window=_window(since, until),
    )


Filters = Annotated[AttemptFilters, Depends(build_query)]


def _not_found(attempt_id: UUID) -> ProblemError:
    """404 through the pipeline taxonomy — ``STATUS_BY_ERROR_CODE`` maps ``NOT_FOUND``.

    The id is echoed into ``details`` because it is a ``UUID`` FastAPI already parsed, not
    caller-chosen text: a malformed one never reaches this function.
    """
    return ProblemError(
        AdminProblem(
            code=ErrorCode.NOT_FOUND,
            message="no generation attempt has that id",
            details={"attemptId": str(attempt_id)},
        )
    )


def build_generations_router() -> APIRouter:
    """The generation surface. One permission, declared once, on the router."""
    router = APIRouter(
        tags=["generations"],
        dependencies=[Depends(require_permission(Permission.RECORDS_READ))],
    )

    @router.get(GENERATIONS_PATH)
    async def list_generations(
        db: Db,
        filters: Filters,
        paging: Paging,
        with_total: Annotated[bool, Query(alias="withTotal")] = False,
    ) -> AttemptsPage:
        """One keyset page of the render ledger, newest first.

        The count is a second query and it runs only when asked for: ``bounded_total`` stops
        at ``TOTAL_COUNT_CAP``, so it is cheap, but it is not free and no screen needs it to
        render the first page.
        """
        page = await list_attempts(db, filters=filters, request=paging)
        total = await count_attempts(db, filters=filters) if with_total else None
        return AttemptsPage(
            items=[to_attempt_view(attempt) for attempt in page.items],
            meta=page_meta(page, total),
        )

    @router.get(ATTEMPT_PATH)
    async def get_generation(db: Db, attempt_id: UUID) -> AttemptWireView:
        """One attempt by id. An id that matches nothing is a 404, never an empty body."""
        attempt = await get_attempt(db, attempt_id)
        if attempt is None:
            raise _not_found(attempt_id)
        return to_attempt_view(attempt)

    return router
