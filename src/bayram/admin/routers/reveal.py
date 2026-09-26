"""``POST /api/reveal`` — the **one** path by which masked data becomes plaintext.

§12.2: "Every ``A`` cell routes through the same ``POST /reveal`` endpoint. One reveal path,
one audit shape, one budget — multiple reveal endpoints is how one of them ends up
unaudited." So there is one route in this module and there will not be a second: a new
subject or a new column is a member of :class:`~bayram.admin.schemas.reveal.RevealField`, not a
new handler with its own idea of what to charge and what to log.

**The guard is two permissions, not one, and that is this route's one non-obvious
decision.** ``deps.RequirePermission`` calls ``check_role``, which answers
``STEP_UP_REQUIRED`` for any cell carrying a step-up **without ever consulting the session's
grant** — it holds no subject, so there is none to weigh. A router guarded plainly by
``REVEAL_PERSONAL_DATA`` would therefore refuse a SUPPORT operator holding a live,
correctly-scoped ``reveal:<order>`` grant, for ever, and it would look right, because
``STEP_UP_REQUIRED`` is exactly what §12.2's cell predicts. Guarding it with ``RECORDS_READ``
instead is not available either: that cell is ``M`` for all four roles, and §12.2 gives
VIEWER no reveal cell at all.

So the §12.2 row is split, exactly the way §12.2 itself split the admin roster and the way
the media routes next door split theirs: ``REVEAL_PERSONAL_DATA_READ`` is the **role** half
(SUPPORT and above, no step-up) and lives on the router, so VIEWER is 403 ``FORBIDDEN`` here
and never reaches the handler; ``REVEAL_PERSONAL_DATA``'s ``A+S`` cell is enforced by the
**handler**, on the subject in the body, through
:func:`~bayram.admin.deps.enforce_step_up`. Both run on every request; neither is decorative
and neither is sufficient alone.

**The handler is four ordered steps, and the order is the control.**

1. **Plan.** The body is validated by pydantic first, so a missing ``reasonCode`` is a 422
   before anything is charged, logged or read.
2. **Step-up**, on this subject. A refusal costs no budget: an operator who has not
   re-authenticated has not disclosed anything, and charging them would let a probe drain a
   colleague's hourly ceiling.
3. **Budget**, charged for what the reveal is *authorised* to return, before the read.
4. **Audit, then read** — :func:`~bayram.admin.services.reveal.perform_reveal`, which commits
   the row in its own transaction so a read that then fails cannot roll back the record of
   who asked for it (§12.3).

``now`` is read **once** and threaded through all four. Two ``utc_now()`` calls would put
the step-up window, the budget's window index and the audit row's timestamp on either side
of a boundary, which is the class of bug that reproduces once a month at :00.
"""

from __future__ import annotations

from typing import Final

from fastapi import APIRouter, Depends

from bayram.admin.deps import (
    API_PREFIX,
    Admin,
    Container,
    Db,
    enforce_reveal_budget,
    enforce_step_up,
    require_permission,
)
from bayram.admin.schemas.reveal import (
    RevealBudgetView,
    RevealRequest,
    RevealResponse,
)
from bayram.admin.security.permissions import Permission, StepUpAction
from bayram.admin.services.reveal import (
    audit_subject_id,
    perform_reveal,
    plan_reveal,
    reveal_entry,
)
from bayram.db.base import utc_now

__all__ = ["REVEAL_PATH", "build_reveal_router"]

#: Declared as a full path because routers are included without a prefix — the
#: forced-rotation gate and the request log compare absolute paths.
REVEAL_PATH: Final[str] = f"{API_PREFIX}/reveal"


def build_reveal_router() -> APIRouter:
    """The reveal surface. One route, one permission, declared once on the router."""
    router = APIRouter(
        tags=["reveal"],
        dependencies=[Depends(require_permission(Permission.REVEAL_PERSONAL_DATA_READ))],
    )

    @router.post(REVEAL_PATH)
    async def reveal(
        body: RevealRequest, db: Db, admin: Admin, container: Container
    ) -> RevealResponse:
        """Plaintext for the named fields of one subject — never the whole object.

        Returns 403 ``STEP_UP_REQUIRED`` without a grant scoped to ``reveal:<subject>``, 429
        ``REVEAL_BUDGET_EXHAUSTED`` when either ceiling is spent, 404 when the subject does
        not exist, and 422 for a body that could not be charged honestly. Every one of those
        after step 4 leaves the audit row behind, which is the point of the ordering.
        """
        plan = plan_reveal(body)
        now = utc_now()
        await enforce_step_up(
            admin,
            container,
            action=StepUpAction.REVEAL,
            subject_id=plan.subject_id,
            now=now,
        )
        decision = await enforce_reveal_budget(
            admin,
            container,
            record_count=plan.records_authorised,
            conversation_count=plan.conversations_charged,
            now=now,
        )
        entry = reveal_entry(
            admin,
            body=body,
            plan=plan,
            records_charged=decision.records_charged,
            # Read before the audit row is built, and it is the ONE place the reveal's
            # ``users.id`` becomes the Telegram id the block and the grant file under —
            # otherwise ``/audit?subjectType=user`` answers half this customer's trail and
            # reads like the whole of it. See :func:`audit_subject_id`.
            subject_id=await audit_subject_id(db, plan),
        )
        result = await perform_reveal(db, container, entry=entry, plan=plan, now=now)
        return RevealResponse(
            subject_type=plan.subject_type,
            subject_id=plan.subject_uuid,
            revealed_at=now,
            reason_code=body.reason_code,
            record_count=decision.records_charged,
            revealed_fields=plan.fields,
            records=result.records,
            next_cursor=result.next_cursor,
            budget=RevealBudgetView(
                records_charged=decision.records_charged,
                records_remaining=decision.records_remaining,
                conversations_charged=decision.conversations_charged,
                conversations_remaining=decision.conversations_remaining,
            ),
        )

    return router
