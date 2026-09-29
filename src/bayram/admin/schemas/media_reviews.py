"""Wire models for the media review queue (IMAGE_VIDEO_SPEC §6.6, §8).

**Nothing on this wire is customer data.** A review carries the job id, closed category codes,
the SKU, states and timings — never the prompt, never a Telegram id, never a byte of the
images (§8: the prompt is behind ``POST /reveal`` and the outputs behind a step-up stream, M5).
``actor`` is an operator's username, published on the ``credits`` screen's argument: "who
released this?" is the question the column is on the screen to answer.

Every action body is a :class:`~bayram.admin.schemas.actions.ReasonedRequest`: a reason code is
mandatory for a hold, a release and a refund alike, because each one is recorded against the
customer's request in the 730-day audit log.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from bayram.admin.schemas.actions import ReasonedRequest
from bayram.admin.schemas.common import ApiModel
from bayram.db.enums import (
    AuditReasonCode,
    MediaJobState,
    MediaKind,
    MediaPaidVia,
    MediaReviewDecision,
    MediaReviewSource,
    MediaSku,
)
from bayram.db.media_reviews import ReviewView

__all__ = [
    "MediaReviewView",
    "MediaReviewList",
    "MediaReviewActionRequest",
    "MediaReviewActionResult",
    "to_media_review_view",
]


class MediaReviewView(ApiModel):
    """One held job in the queue, or one decided review in its history."""

    id: UUID
    job_id: UUID
    kind: MediaKind
    sku: MediaSku
    job_state: MediaJobState
    paid_via: MediaPaidVia | None
    source: MediaReviewSource
    subject: str
    categories: list[str]
    outputs_requested: int
    created_at: datetime
    #: The 24 h SLA: past it, ``media_sweep`` decides ``expired`` and the job fails with a
    #: credit (§6.6).
    due_at: datetime
    decision: MediaReviewDecision | None
    decided_at: datetime | None
    actor: str | None
    reason_code: AuditReasonCode | None
    #: When the worker carried the decision out. ``null`` beside a decision is "queued".
    applied_at: datetime | None
    #: Whether a refund would mint a credit: a beta job never gets one (§7.5), and the SPA
    #: says so on the button rather than letting an operator believe they comped somebody.
    is_refundable: bool


class MediaReviewList(ApiModel):
    items: list[MediaReviewView]


class MediaReviewActionRequest(ReasonedRequest):
    """``POST …/hold``, ``…/release`` and ``…/refund``: the reason, and nothing else. The
    subject is the path parameter the step-up scope is built from."""


class MediaReviewActionResult(ApiModel):
    """What the action recorded. ``isQueued`` is whether the worker was asked to carry it out
    now; ``false`` means the enqueue failed and ``media_sweep`` will within minutes."""

    review: MediaReviewView
    is_queued: bool


def to_media_review_view(view: ReviewView) -> MediaReviewView:
    return MediaReviewView(
        id=view.id,
        job_id=view.job_id,
        kind=view.kind,
        sku=view.sku,
        job_state=view.job_state,
        paid_via=view.paid_via,
        source=view.source,
        subject=view.subject,
        categories=list(view.categories),
        outputs_requested=view.outputs_requested,
        created_at=view.created_at,
        due_at=view.due_at,
        decision=view.decision,
        decided_at=view.decided_at,
        actor=view.actor,
        reason_code=view.reason_code,
        applied_at=view.applied_at,
        is_refundable=view.paid_via in (MediaPaidVia.PAYME, MediaPaidVia.CREDIT),
    )
