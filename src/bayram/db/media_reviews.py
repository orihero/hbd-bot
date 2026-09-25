"""Queries over ``moderation_reviews`` — the media review queue (IMAGE_VIDEO_SPEC §6.6, §8).

Three callers, one writer each way:

* **the worker** opens a review in the SAME transaction as the job's move to ``held``
  (``media_output_screen``), and stamps ``applied_at`` once it has carried a decision out
  (``media_review_apply``);
* **the panel** holds a screened job on its way out (:func:`hold_job`) and records a decision
  (:func:`decide_review`) — it never moves a job past ``held`` itself: it holds no bot token
  (D10), so the customer notice, the delivery and the refund are the worker's;
* **``media_sweep``** decides a review the 24 h SLA ran out on (``expired``) and re-drives a
  decision whose apply job was lost.

**Every decision is a conditional ``UPDATE … WHERE decision IS NULL``** and its rowcount is the
lock: two operators, or an operator and the SLA sweep, cannot both decide one review, so a
job refunds at most once from here as it does everywhere else (``grant_refund``, §3.2.2).

Session first, exceptions propagate, nothing committed here — :mod:`bayram.db.media`'s shape.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Final
from uuid import UUID, uuid4

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from bayram.db.credit_sql import rowcount_of
from bayram.db.enums import (
    AuditReasonCode,
    MediaJobState,
    MediaKind,
    MediaPaidVia,
    MediaReviewDecision,
    MediaReviewSource,
    MediaScreenDecision,
    MediaSku,
)
from bayram.db.media import MEDIA_REVIEW_SLA, transition
from bayram.db.models.media_job import MediaJobRow
from bayram.db.models.moderation_review import REVIEW_ACTOR_LENGTH, ModerationReviewRow

__all__ = [
    "MAX_REVIEW_LIST",
    "ReviewView",
    "review_subject",
    "open_review",
    "hold_job",
    "load_review",
    "decide_review",
    "mark_applied",
    "overdue_reviews",
    "unapplied_reviews",
    "list_reviews",
    "get_review",
]

#: The queue's page. Pending reviews are bounded by the open-request index (one per account
#: and kind) and the 24 h SLA; the decided list is a recent-history view, newest first.
MAX_REVIEW_LIST: Final[int] = 200


def review_subject(kind: MediaKind) -> str:
    """The §6.3 subject a held output was screened as."""
    return "output_image" if kind is MediaKind.IMAGE else "output_frame"


async def open_review(
    session: AsyncSession,
    job_id: UUID,
    *,
    kind: MediaKind,
    source: MediaReviewSource,
    categories: Sequence[str],
    now: datetime,
) -> UUID:
    """Insert a pending review for a job the caller has JUST moved to ``held``.

    Called in the transaction of that conditional move, so only the path that won the move
    opens a row; the partial unique index is the second layer.
    """
    review_id = uuid4()
    session.add(
        ModerationReviewRow(
            id=review_id,
            job_id=job_id,
            source=source,
            subject=review_subject(kind),
            categories=list(categories),
            created_at=now,
            due_at=now + MEDIA_REVIEW_SLA,
        )
    )
    await session.flush()
    return review_id


async def hold_job(
    session: AsyncSession,
    job_id: UUID,
    *,
    now: datetime,
    actor_id: UUID | None,
    actor: str,
    reason_code: AuditReasonCode,
) -> UUID | None:
    """An operator stops a screened output on its way out. The review id, or None.

    Only a ``post`` row whose output screen ALLOWED it qualifies — that is the one window in
    which a job is about to be delivered and nothing else is deciding it. Moving it to
    ``held`` with ``output_decision='review'`` is what makes a delivery already queued stand
    down (``media_deliver`` needs ``allow``); an output nobody has screened is not holdable,
    because releasing it would deliver unscreened bytes.

    ``actor``/``reason_code`` are recorded on the review as the hold's author; the decision
    columns stay NULL — this is a pending review.
    """
    job = await session.get(MediaJobRow, job_id, populate_existing=True)
    if (
        job is None
        or job.state is not MediaJobState.POST
        or job.output_decision is not MediaScreenDecision.ALLOW
    ):
        return None
    moved = await transition(
        session,
        job_id,
        expected=(MediaJobState.POST,),
        to=MediaJobState.HELD,
        now=now,
        values={"output_decision": MediaScreenDecision.REVIEW},
    )
    if not moved:
        return None
    review_id = await open_review(
        session,
        job_id,
        kind=job.kind,
        source=MediaReviewSource.MANUAL,
        categories=(),
        now=now,
    )
    await session.execute(
        sa.update(ModerationReviewRow)
        .where(ModerationReviewRow.id == review_id)
        .values(actor_id=actor_id, actor=actor[:REVIEW_ACTOR_LENGTH], reason_code=reason_code)
    )
    return review_id


async def load_review(session: AsyncSession, review_id: UUID) -> ModerationReviewRow | None:
    return await session.get(ModerationReviewRow, review_id, populate_existing=True)


async def decide_review(
    session: AsyncSession,
    review_id: UUID,
    *,
    decision: MediaReviewDecision,
    now: datetime,
    actor_id: UUID | None,
    actor: str,
    reason_code: AuditReasonCode | None,
) -> bool:
    """Record a decision on a PENDING review. True when this call decided it.

    The job is not touched: the worker applies the decision (``media_review_apply``).
    """
    result = await session.execute(
        sa.update(ModerationReviewRow)
        .where(ModerationReviewRow.id == review_id, ModerationReviewRow.decision.is_(None))
        .values(
            decision=decision,
            decided_at=now,
            actor_id=actor_id,
            actor=actor[:REVIEW_ACTOR_LENGTH],
            reason_code=reason_code,
        )
    )
    return rowcount_of(result) == 1


async def mark_applied(session: AsyncSession, review_id: UUID, *, now: datetime) -> bool:
    """Stamp that the worker carried the decision out. Idempotent; True the first time."""
    result = await session.execute(
        sa.update(ModerationReviewRow)
        .where(
            ModerationReviewRow.id == review_id,
            ModerationReviewRow.decision.is_not(None),
            ModerationReviewRow.applied_at.is_(None),
        )
        .values(applied_at=now)
    )
    return rowcount_of(result) == 1


async def overdue_reviews(session: AsyncSession, *, now: datetime, limit: int) -> list[UUID]:
    """Pending reviews past their SLA (§6.6: an unreviewed hold at 24 h → fail + refund)."""
    return list(
        (
            await session.scalars(
                sa.select(ModerationReviewRow.id)
                .where(ModerationReviewRow.decision.is_(None), ModerationReviewRow.due_at < now)
                .order_by(ModerationReviewRow.due_at)
                .limit(limit)
            )
        ).all()
    )


async def unapplied_reviews(
    session: AsyncSession, *, decided_before: datetime, limit: int
) -> list[UUID]:
    """Decided reviews the worker has not carried out — a lost apply enqueue."""
    return list(
        (
            await session.scalars(
                sa.select(ModerationReviewRow.id)
                .where(
                    ModerationReviewRow.decision.is_not(None),
                    ModerationReviewRow.applied_at.is_(None),
                    ModerationReviewRow.decided_at < decided_before,
                )
                .order_by(ModerationReviewRow.decided_at)
                .limit(limit)
            )
        ).all()
    )


# ---------------------------------------------------------------------------
# The panel's reads (§8: job id, codes and timings — never the prompt, never the bytes)
# ---------------------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class ReviewView:
    """One queue row as the panel shows it. No customer text and no Telegram id."""

    id: UUID
    job_id: UUID
    kind: MediaKind
    sku: MediaSku
    job_state: MediaJobState
    paid_via: MediaPaidVia | None
    source: MediaReviewSource
    subject: str
    categories: tuple[str, ...]
    outputs_requested: int
    created_at: datetime
    due_at: datetime
    decision: MediaReviewDecision | None
    decided_at: datetime | None
    actor: str | None
    reason_code: AuditReasonCode | None
    applied_at: datetime | None


def _view_select() -> sa.Select[tuple[ModerationReviewRow, MediaJobRow]]:
    return sa.select(ModerationReviewRow, MediaJobRow).join(
        MediaJobRow, MediaJobRow.id == ModerationReviewRow.job_id
    )


def _to_view(review: ModerationReviewRow, job: MediaJobRow) -> ReviewView:
    return ReviewView(
        id=review.id,
        job_id=review.job_id,
        kind=job.kind,
        sku=job.sku,
        job_state=job.state,
        paid_via=job.paid_via,
        source=review.source,
        subject=review.subject,
        categories=tuple(review.categories or ()),
        outputs_requested=job.outputs_requested,
        created_at=review.created_at,
        due_at=review.due_at,
        decision=review.decision,
        decided_at=review.decided_at,
        actor=review.actor,
        reason_code=review.reason_code,
        applied_at=review.applied_at,
    )


async def list_reviews(
    session: AsyncSession, *, pending: bool, limit: int = MAX_REVIEW_LIST
) -> list[ReviewView]:
    """Pending reviews oldest first (the one nearest its SLA on top), or decided ones newest
    first. Bounded by :data:`MAX_REVIEW_LIST`."""
    bounded = max(1, min(limit, MAX_REVIEW_LIST))
    statement = (
        _view_select()
        .where(ModerationReviewRow.decision.is_(None))
        .order_by(ModerationReviewRow.created_at, ModerationReviewRow.id)
        if pending
        else _view_select()
        .where(ModerationReviewRow.decision.is_not(None))
        .order_by(ModerationReviewRow.decided_at.desc(), ModerationReviewRow.id.desc())
    )
    rows = (await session.execute(statement.limit(bounded))).all()
    return [_to_view(review, job) for review, job in rows]


async def get_review(session: AsyncSession, review_id: UUID) -> ReviewView | None:
    # ``populate_existing``: the panel reads this back after a Core ``UPDATE`` in the same
    # transaction, and the identity map would otherwise hand back the pre-decision row.
    row = (
        await session.execute(
            _view_select()
            .where(ModerationReviewRow.id == review_id)
            .execution_options(populate_existing=True)
        )
    ).one_or_none()
    return None if row is None else _to_view(row[0], row[1])
