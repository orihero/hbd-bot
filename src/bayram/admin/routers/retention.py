"""``GET /api/retention`` — whether the retention job is running, and how far behind it is.

Slice 1b is the first time in this project's life that the retention sweep executes. An
operator therefore needs to be able to *see* that it did, and a log line is not evidence:
this route reads the ``purge_runs`` records the job writes, so "a sweep ran and deleted
nothing" and "the scheduler stopped firing" are two different answers rather than the same
silence.

**It is a read and it writes nothing.** No sweep is triggered from here, not even as a
convenience — ``POST /retention/run`` is the write, it is an OWNER cell in §12.2, and it
enqueues an ARQ job rather than running a 500-row batch inside a request. A ``GET`` that
swept would also be a state change behind a safe method, which the route-enumeration test
forbids and a browser prefetch would fire.

**The guard is ``require_permission`` at the router**, which resolves to ``check_role``.
``check_access`` is the wrong question here for the same reason it is on the audit list:
with no subject there is no scope to compare a step-up against, so ``check_access`` with
``subject_id=None`` would log an ERROR on every single request to a route that asks for no
step-up at all. §12.2 gives RETENTION_READ as **M** to all four roles.

**The handler takes no ``Admin``**, unlike the audit list. That is not an oversight: the
router dependency still authenticates every request, and there is nothing here to mask —
``purge_runs`` holds counts and no personal data, so the **M** cell has no redacted variant
to choose between. Taking the operator in order to ignore it would imply a masking decision
that does not exist.

**The policy comes from the settings, not from the module default.** The sweep resolves its
own policy with :func:`bayram.db.retention.resolve_retention_policy`
(``runtime/retention_job.py``); the live backlog is counted with the same call, so on the
day the ``retention_*`` fields land on the settings the panel's numbers and the job's
predicates move together instead of drifting by one release.
"""

from __future__ import annotations

from typing import Annotated, Final

from fastapi import APIRouter, Depends, Query

from bayram.admin.deps import API_PREFIX, Db, Settings, require_permission
from bayram.admin.schemas.retention import RetentionResponse, to_response
from bayram.admin.security.permissions import Permission
from bayram.db.admin.retention import DEFAULT_RUN_HISTORY, MAX_RUN_HISTORY, overview
from bayram.db.base import utc_now
from bayram.db.retention import resolve_retention_policy

__all__ = ["RETENTION_PATH", "build_retention_router"]

RETENTION_PATH: Final[str] = f"{API_PREFIX}/retention"


def build_retention_router() -> APIRouter:
    """The retention surface. One permission, declared once, on the router."""
    router = APIRouter(
        tags=["retention"],
        dependencies=[Depends(require_permission(Permission.RETENTION_READ))],
    )

    @router.get(RETENTION_PATH)
    async def retention_status(
        db: Db,
        settings: Settings,
        limit: Annotated[int, Query(ge=1, le=MAX_RUN_HISTORY)] = DEFAULT_RUN_HISTORY,
    ) -> RetentionResponse:
        """The last ``limit`` sweeps, newest first, plus what is due right now.

        ``limit`` is bounded by the schema rather than only by ``recent_runs``' own clamp:
        a query string asking for the whole table should be refused at the boundary, and
        the clamp behind it is the backstop, not the validation.
        """
        return to_response(
            await overview(
                db,
                now=utc_now(),
                policy=resolve_retention_policy(settings),
                limit=limit,
            )
        )

    return router
