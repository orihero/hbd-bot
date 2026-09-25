"""``/media/reviews`` — the review queue for held media outputs (IMAGE_VIDEO_SPEC §6.6, §8).

**Five routes on one guard.** ``MEDIA_MODERATE`` (ADMIN and OWNER, a plain ``W``) is the role
half every route here declares: list, read, hold, release, refund. The refund is the one that
mints value — a SKU-scoped credit (D25) — so it sits in D14's step-up class and its handler
enforces ``MODERATION_DECIDE``'s ``W+S`` cell through ``StepUpAction.MODERATION_DECIDE`` on the
review id it has read. That is the split every step-up write in this package takes, for the
reason ``routers/credits.py`` gives: a router guard holds no subject and therefore no grant,
so a ``W+S`` cell declared here would be a 403 for everyone, for ever.

**The panel records; the worker acts.** This process holds no bot token (D10). A release, a
refund or a hold writes the review row, moves nothing past ``held``, and audits in the request's
transaction; after the COMMIT a release or a refund asks the worker, through ``AdminQueue``, to
carry it out (``media_review_apply``: deliver the images, or fail the job with one credit and
tell the customer). A hold enqueues nothing — the job's own row is what makes a queued delivery
stand down. If the enqueue fails the decision still stands and ``media_sweep`` applies it
within minutes; the response says which happened (``isQueued``).

**A refund writes two audit rows** (D14/D25 via IMAGE_VIDEO_SPEC §8): the INTENT,
``moderation.refund``, inside the decision's transaction — so a decision without its audit
row is impossible — with ``recordCount`` the credits it will mint (0 for a beta job, §7.5);
and the OUTCOME, ``moderation.refund.outcome``, after the enqueue, ``ok`` or ``error``, in a
transaction of its own because the request's has already committed.

**Every decision is a conditional UPDATE** (:func:`bayram.db.media_reviews.decide_review`), so
two operators, or an operator racing the 24 h SLA sweep, produce one decision and one 409.

**What the queue shows.** Job id, SKU, states, closed category codes, timings — never the
prompt and never the bytes (§8). Revealing the outputs is M5's reveal subject on
``media_outputs``; until then a reviewer decides from the codes, and the spec's residual risk
for that is §11 R3/R11.
"""

from __future__ import annotations

from typing import Annotated, Final, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Query

from bayram.admin import audit_sink
from bayram.admin.deps import (
    API_PREFIX,
    Admin,
    Container,
    CurrentAdmin,
    Db,
    enforce_step_up,
    require_permission,
)
from bayram.admin.errors import AdminErrorCode, AdminProblem, ProblemError, problem
from bayram.admin.schemas.media_reviews import (
    MediaReviewActionRequest,
    MediaReviewActionResult,
    MediaReviewList,
    MediaReviewView,
    to_media_review_view,
)
from bayram.admin.security.permissions import Permission, StepUpAction
from bayram.contracts import is_err
from bayram.db.admin.audit import AuditEntry
from bayram.db.base import utc_now
from bayram.db.enums import AuditAction, MediaJobState, MediaPaidVia, MediaReviewDecision
from bayram.db.media import load_job
from bayram.db.media_reviews import ReviewView, decide_review, get_review, hold_job, list_reviews
from bayram.db.models.admin_audit import ACTOR_USERNAME_LENGTH, AuditOutcome
from bayram.errors import ErrorCode

__all__ = [
    "MEDIA_REVIEWS_PATH",
    "MEDIA_REVIEW_PATH",
    "MEDIA_REVIEW_RELEASE_PATH",
    "MEDIA_REVIEW_REFUND_PATH",
    "MEDIA_JOB_HOLD_PATH",
    "MEDIA_JOB_SUBJECT_TYPE",
    "build_media_reviews_router",
]

MEDIA_REVIEWS_PATH: Final[str] = f"{API_PREFIX}/media/reviews"
MEDIA_REVIEW_PATH: Final[str] = f"{MEDIA_REVIEWS_PATH}/{{review_id}}"
MEDIA_REVIEW_RELEASE_PATH: Final[str] = f"{MEDIA_REVIEW_PATH}/release"
MEDIA_REVIEW_REFUND_PATH: Final[str] = f"{MEDIA_REVIEW_PATH}/refund"
#: Under ``/media-jobs`` — IMAGE_VIDEO_SPEC §8's namespace for the job itself — and not under
#: ``/media``, whose one identifier is the review: a namespace mixing ``{job_id}`` and
#: ``{review_id}`` is how a caller learns to send one to the other (§12.1 T3).
MEDIA_JOB_HOLD_PATH: Final[str] = f"{API_PREFIX}/media-jobs/{{job_id}}/hold"

#: ``bayram.db.admin.audit.SUBJECT_TYPES``' member for one media request.
MEDIA_JOB_SUBJECT_TYPE: Final[str] = "media_job"

_REFUNDABLE: Final[frozenset[MediaPaidVia]] = frozenset({MediaPaidVia.PAYME, MediaPaidVia.CREDIT})

ReviewStatus = Annotated[Literal["pending", "decided"], Query()]


def _not_found(message: str) -> ProblemError:
    return ProblemError(AdminProblem(code=ErrorCode.NOT_FOUND, message=message))


def _no_such_review() -> ProblemError:
    return _not_found("no such review")


def _already_decided(view: ReviewView) -> ProblemError:
    """409 with what the review says NOW — read before this request's write, never raced."""
    return problem(
        AdminErrorCode.CONFLICT,
        "this review has already been decided",
        decision=None if view.decision is None else str(view.decision),
    )


def _not_held(view: ReviewView) -> ProblemError:
    return problem(
        AdminErrorCode.CONFLICT,
        "this job is no longer held, so there is nothing to decide",
        jobState=str(view.job_state),
    )


async def _pending(db: Db, review_id: UUID) -> ReviewView:
    view = await get_review(db, review_id)
    if view is None:
        raise _no_such_review()
    if view.decision is not None:
        raise _already_decided(view)
    if view.job_state is not MediaJobState.HELD:
        raise _not_held(view)
    return view


async def _read_back(db: Db, review_id: UUID) -> MediaReviewView:
    view = await get_review(db, review_id)
    if view is None:  # pragma: no cover - read in this transaction a moment ago
        raise _no_such_review()
    return to_media_review_view(view)


def build_media_reviews_router() -> APIRouter:
    """The queue. ``MEDIA_MODERATE`` on the router; the refund's step-up in its handler."""
    router = APIRouter(
        tags=["media"],
        dependencies=[Depends(require_permission(Permission.MEDIA_MODERATE))],
    )

    @router.get(MEDIA_REVIEWS_PATH)
    async def list_media_reviews(db: Db, status: ReviewStatus = "pending") -> MediaReviewList:
        """Pending reviews oldest first — the one nearest its 24 h SLA on top — or the decided
        history newest first. Bounded (``MAX_REVIEW_LIST``); the pending set is small by
        construction (one open request per account and kind, and the SLA)."""
        views = await list_reviews(db, pending=status == "pending")
        return MediaReviewList(items=[to_media_review_view(view) for view in views])

    @router.get(MEDIA_REVIEW_PATH)
    async def get_media_review(db: Db, review_id: UUID) -> MediaReviewView:
        view = await get_review(db, review_id)
        if view is None:
            raise _no_such_review()
        return to_media_review_view(view)

    @router.post(MEDIA_JOB_HOLD_PATH)
    async def hold_media_job(
        body: MediaReviewActionRequest, db: Db, admin: Admin, container: Container, job_id: UUID
    ) -> MediaReviewView:
        """Stop a screened output on its way out and open a review (§6.6 source ``manual``).

        Only a ``post`` job whose output screen allowed it can be held — the window in which it
        is about to be delivered. Anything else is a 409 naming the state: an unscreened output
        is not holdable (releasing it would deliver unscreened bytes), and a job already
        delivering is past stopping.
        """
        now = utc_now()
        review_id = await hold_job(
            db,
            job_id,
            now=now,
            actor_id=admin.admin_user_id,
            actor=admin.username,
            reason_code=body.reason_code,
        )
        if review_id is None:
            job = await load_job(db, job_id)
            if job is None:
                raise _not_found("no such media job")
            raise problem(
                AdminErrorCode.CONFLICT,
                "only a screened output waiting to be delivered can be held",
                jobState=str(job.state),
            )
        await audit_sink.record(
            db,
            container,
            _entry(
                AuditAction.MODERATION_HOLD,
                admin,
                job_id=job_id,
                body=body,
                field_names=("media_jobs.state", "moderation_reviews.id"),
                record_count=1,
            ),
            now=now,
        )
        return await _read_back(db, review_id)

    @router.post(MEDIA_REVIEW_RELEASE_PATH)
    async def release_media_review(
        body: MediaReviewActionRequest,
        db: Db,
        admin: Admin,
        container: Container,
        review_id: UUID,
    ) -> MediaReviewActionResult:
        """Release a held output: the worker marks it allowed and delivers it. No step-up —
        it delivers what the customer paid for and mints nothing (§8)."""
        now = utc_now()
        view = await _pending(db, review_id)
        if not await decide_review(
            db,
            review_id,
            decision=MediaReviewDecision.RELEASED,
            now=now,
            actor_id=admin.admin_user_id,
            actor=admin.username,
            reason_code=body.reason_code,
        ):
            raise _already_decided(view)
        await audit_sink.record(
            db,
            container,
            _entry(
                AuditAction.MODERATION_APPROVE,
                admin,
                job_id=view.job_id,
                body=body,
                field_names=("moderation_reviews.decision",),
                record_count=1,
            ),
            now=now,
        )
        answer = await _read_back(db, review_id)
        await db.commit()
        # COMMIT, then enqueue: the worker reads the decision off the row. ``db`` is closed.
        queued = await container.queue.enqueue_media_review(review_id)
        return MediaReviewActionResult(review=answer, is_queued=not is_err(queued))

    @router.post(MEDIA_REVIEW_REFUND_PATH)
    async def refund_media_review(
        body: MediaReviewActionRequest,
        db: Db,
        admin: Admin,
        container: Container,
        review_id: UUID,
    ) -> MediaReviewActionResult:
        """Confirm the block: the job fails and a paid one gets ONE SKU-scoped credit (§7.5).

        Step-up first, on the review id, so a refusal costs nothing and changes nothing. The
        INTENT row rides the decision's transaction; the OUTCOME row follows the enqueue.
        """
        now = utc_now()
        await enforce_step_up(
            admin,
            container,
            action=StepUpAction.MODERATION_DECIDE,
            subject_id=str(review_id),
            now=now,
        )
        view = await _pending(db, review_id)
        if not await decide_review(
            db,
            review_id,
            decision=MediaReviewDecision.BLOCKED,
            now=now,
            actor_id=admin.admin_user_id,
            actor=admin.username,
            reason_code=body.reason_code,
        ):
            raise _already_decided(view)
        credits = 1 if view.paid_via in _REFUNDABLE else 0
        await audit_sink.record(
            db,
            container,
            _entry(
                AuditAction.MODERATION_REFUND,
                admin,
                job_id=view.job_id,
                body=body,
                field_names=("moderation_reviews.decision", "media_credit_balances.balance"),
                record_count=credits,
            ),
            now=now,
        )
        answer = await _read_back(db, review_id)
        await db.commit()
        queued = await container.queue.enqueue_media_review(review_id)
        is_queued = not is_err(queued)
        await audit_sink.record_refusal(
            container,
            _entry(
                AuditAction.MODERATION_REFUND_OUTCOME,
                admin,
                job_id=view.job_id,
                body=body,
                field_names=("media_jobs.state",),
                record_count=credits,
                outcome=AuditOutcome.OK if is_queued else AuditOutcome.ERROR,
                error_code=None if is_queued else str(ErrorCode.STORAGE_FAILED),
            ),
            now=utc_now(),
        )
        return MediaReviewActionResult(review=answer, is_queued=is_queued)

    return router


def _entry(
    action: AuditAction,
    admin: CurrentAdmin,
    *,
    job_id: UUID,
    body: MediaReviewActionRequest,
    field_names: tuple[str, ...],
    record_count: int,
    outcome: AuditOutcome = AuditOutcome.OK,
    error_code: str | None = None,
) -> AuditEntry:
    """One review-queue row against the JOB (``subject_type="media_job"``)."""
    return AuditEntry(
        action=action,
        actor_id=admin.admin_user_id,
        actor_username=admin.username[:ACTOR_USERNAME_LENGTH],
        actor_role=admin.role,
        subject_type=MEDIA_JOB_SUBJECT_TYPE,
        subject_id=str(job_id),
        field_names=field_names,
        record_count=record_count,
        reason_code=body.reason_code,
        reason_ref=body.reason_ref,
        reason_text=body.reason_text,
        outcome=outcome,
        error_code=error_code,
        ip=admin.client_ip,
    )
