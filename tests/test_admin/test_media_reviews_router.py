"""``/media/reviews`` — the review queue for held media outputs, over the real ASGI stack.

IMAGE_VIDEO_SPEC §6.6, §8, §10 M3.2. What this file holds the panel to:

* **refund without a step-up is refused** and changes nothing — the refund mints a credit, so
  it is in D14's step-up class (D25), and the step-up is scoped to the REVIEW;
* a release and a refund each record ONE decision, audit it in the decision's transaction,
  commit, and only then ask the worker (``media_review_apply``) to carry it out; a refund
  also writes its OUTCOME row after the enqueue (D14);
* a second decision is a 409, never a second refund;
* a hold stops only a screened output on its way out, and opens a pending review;
* the queue shows codes and timings, never the prompt.

What the worker then does with a decision is ``tests/test_runtime/test_media_review.py``.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import timedelta
from typing import Any, Final
from uuid import UUID, uuid4

import httpx
import pytest
import sqlalchemy as sa

from bayram.admin.container import AdminContainer
from bayram.admin.errors import AdminErrorCode
from bayram.admin.queue import MEDIA_REVIEW_JOB_NAME, NullAdminQueue, job_id_for_media_review
from bayram.admin.routers.media_reviews import (
    MEDIA_JOB_HOLD_PATH,
    MEDIA_REVIEW_PATH,
    MEDIA_REVIEW_REFUND_PATH,
    MEDIA_REVIEW_RELEASE_PATH,
    MEDIA_REVIEWS_PATH,
)
from bayram.contracts import Language
from bayram.db.enums import (
    AdminRole,
    AuditAction,
    AuditReasonCode,
    MediaAspect,
    MediaJobState,
    MediaKind,
    MediaPaidVia,
    MediaReviewDecision,
    MediaReviewSource,
    MediaScreenDecision,
    MediaSku,
)
from bayram.db.media import create_job
from bayram.db.media_reviews import open_review
from bayram.db.models.admin_audit import AdminAuditRow, AuditOutcome
from bayram.db.models.media_credit import MediaCreditLedgerRow
from bayram.db.models.media_job import MediaJobRow
from bayram.db.models.moderation_review import ModerationReviewRow
from bayram.db.models.user import UserRow
from tests.test_admin.conftest import (
    NOW,
    PASSWORD,
    FakeRedis,
    MemoryRateLimits,
    create_account,
    csrf_headers,
    make_settings,
    open_client,
    open_container,
    sign_in,
)

TELEGRAM_USER_ID: Final[int] = 700_000_321
PROMPT: Final[str] = "a very private prompt about my cousin"


@dataclass(frozen=True, slots=True)
class Panel:
    container: AdminContainer
    http: httpx.AsyncClient
    queue: NullAdminQueue


@pytest.fixture
async def panel() -> AsyncIterator[Panel]:
    queue = NullAdminQueue()
    async with (
        open_container(make_settings(), FakeRedis(), MemoryRateLimits(), queue) as container,
        open_client(container) as http,
    ):
        yield Panel(container=container, http=http, queue=queue)


async def signed_in(panel: Panel, *, role: AdminRole = AdminRole.ADMIN) -> str:
    name = f"{role.value}-reviewer"
    await create_account(panel.container, username=name, role=role)
    assert (await sign_in(panel.http, username=name, password=PASSWORD)).status_code == 200
    return name


async def step_up(panel: Panel, *, subject: UUID, scope: str = "moderation.decide") -> None:
    response = await panel.http.post(
        "/api/auth/step-up",
        json={"password": PASSWORD, "scope": scope, "subjectId": str(subject)},
        headers=csrf_headers(panel.http),
    )
    assert response.status_code == 200, response.text


async def post(panel: Panel, url: str, **body: Any) -> httpx.Response:
    payload = {"reasonCode": AuditReasonCode.ABUSE_REPORT.value, **body}
    return await panel.http.post(url, json=payload, headers=csrf_headers(panel.http))


async def seed_job(
    panel: Panel,
    *,
    state: MediaJobState = MediaJobState.HELD,
    output_decision: MediaScreenDecision = MediaScreenDecision.REVIEW,
    paid_via: MediaPaidVia = MediaPaidVia.PAYME,
    with_review: bool = True,
) -> tuple[UUID, UUID | None]:
    """A paid image job in ``state``, with a pending review when it is held."""
    async with panel.container.session_factory.begin() as db:
        user_id = uuid4()
        db.add(UserRow(id=user_id, telegram_user_id=TELEGRAM_USER_ID, created_at=NOW))
        await db.flush()
        job_id = await create_job(
            db,
            user_id=user_id,
            telegram_user_id=TELEGRAM_USER_ID,
            kind=MediaKind.IMAGE,
            sku=MediaSku.IMAGE,
            state=MediaJobState.SCREENING,
            chat_id=TELEGRAM_USER_ID,
            outputs_requested=2,
            aspect=MediaAspect.PORTRAIT,
            language=Language.EN,
            prompt=PROMPT,
            price_minor=500_000,
            currency="UZS",
            now=NOW,
            quote_ttl=timedelta(minutes=30),
        )
        await db.execute(
            sa.update(MediaJobRow)
            .where(MediaJobRow.id == job_id)
            .values(
                state=state,
                paid_via=paid_via,
                paid_at=NOW,
                output_decision=output_decision,
                output_categories=["violence"],
            )
        )
        review_id = (
            await open_review(
                db,
                job_id,
                kind=MediaKind.IMAGE,
                source=MediaReviewSource.OUTPUT_REVIEW,
                categories=["violence"],
                now=NOW,
            )
            if with_review
            else None
        )
    return job_id, review_id


async def review_row(panel: Panel, review_id: UUID) -> ModerationReviewRow:
    async with panel.container.session_factory() as db:
        row = await db.get(ModerationReviewRow, review_id)
    assert row is not None
    return row


async def job_row(panel: Panel, job_id: UUID) -> MediaJobRow:
    async with panel.container.session_factory() as db:
        row = await db.get(MediaJobRow, job_id)
    assert row is not None
    return row


async def audit_rows(panel: Panel, *actions: AuditAction) -> list[AdminAuditRow]:
    async with panel.container.session_factory() as db:
        return list(
            (
                await db.scalars(
                    sa.select(AdminAuditRow)
                    .where(AdminAuditRow.action.in_(actions))
                    .order_by(AdminAuditRow.seq)
                )
            ).all()
        )


def url(template: str, **ids: UUID) -> str:
    return template.format(**{key: str(value) for key, value in ids.items()})


# ---------------------------------------------------------------------------
# The queue read
# ---------------------------------------------------------------------------
async def test_the_queue_lists_pending_reviews_with_codes_and_never_the_prompt(
    panel: Panel,
) -> None:
    job_id, review_id = await seed_job(panel)
    await signed_in(panel)

    response = await panel.http.get(MEDIA_REVIEWS_PATH)

    assert response.status_code == 200
    [item] = response.json()["items"]
    assert item["id"] == str(review_id) and item["jobId"] == str(job_id)
    assert item["categories"] == ["violence"]
    assert item["source"] == "output_review" and item["decision"] is None
    assert item["isRefundable"] is True
    assert PROMPT not in response.text
    assert str(TELEGRAM_USER_ID) not in response.text


async def test_support_cannot_reach_the_queue(panel: Panel) -> None:
    await seed_job(panel)
    await signed_in(panel, role=AdminRole.SUPPORT)

    response = await panel.http.get(MEDIA_REVIEWS_PATH)

    assert response.status_code == 403
    assert response.json()["error"]["code"] == AdminErrorCode.FORBIDDEN.value


# ---------------------------------------------------------------------------
# Refund — behind a step-up scoped to the review
# ---------------------------------------------------------------------------
async def test_a_refund_without_a_step_up_is_refused_and_changes_nothing(panel: Panel) -> None:
    job_id, review_id = await seed_job(panel)
    assert review_id is not None
    await signed_in(panel)

    response = await post(panel, url(MEDIA_REVIEW_REFUND_PATH, review_id=review_id))

    assert response.status_code == 403
    assert response.json()["error"]["code"] == AdminErrorCode.STEP_UP_REQUIRED.value
    assert (await review_row(panel, review_id)).decision is None
    assert (await job_row(panel, job_id)).state is MediaJobState.HELD
    assert panel.queue.calls == []
    assert await audit_rows(panel, AuditAction.MODERATION_REFUND) == []


async def test_a_step_up_for_another_review_does_not_refund_this_one(panel: Panel) -> None:
    _, review_id = await seed_job(panel)
    assert review_id is not None
    await signed_in(panel)
    await step_up(panel, subject=uuid4())

    response = await post(panel, url(MEDIA_REVIEW_REFUND_PATH, review_id=review_id))

    assert response.status_code == 403
    assert (await review_row(panel, review_id)).decision is None


async def test_a_scoped_refund_decides_audits_both_rows_and_asks_the_worker(
    panel: Panel,
) -> None:
    job_id, review_id = await seed_job(panel)
    assert review_id is not None
    username = await signed_in(panel)
    await step_up(panel, subject=review_id)

    response = await post(
        panel, url(MEDIA_REVIEW_REFUND_PATH, review_id=review_id), reasonRef="T-9"
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["isQueued"] is True
    assert body["review"]["decision"] == MediaReviewDecision.BLOCKED.value
    review = await review_row(panel, review_id)
    assert (review.decision, review.actor) == (MediaReviewDecision.BLOCKED, username)
    assert review.reason_code is AuditReasonCode.ABUSE_REPORT
    # The panel records; the worker moves the job and mints the credit.
    assert (await job_row(panel, job_id)).state is MediaJobState.HELD
    async with panel.container.session_factory() as db:
        assert (await db.scalars(sa.select(MediaCreditLedgerRow))).all() == []
    [call] = panel.queue.calls
    assert (call.job, call.job_id, call.review_id) == (
        MEDIA_REVIEW_JOB_NAME,
        job_id_for_media_review(review_id),
        review_id,
    )
    intent, outcome = await audit_rows(
        panel, AuditAction.MODERATION_REFUND, AuditAction.MODERATION_REFUND_OUTCOME
    )
    assert intent.action is AuditAction.MODERATION_REFUND
    assert (intent.subject_type, intent.subject_id) == ("media_job", str(job_id))
    assert intent.record_count == 1 and intent.reason_ref == "T-9"
    assert outcome.action is AuditAction.MODERATION_REFUND_OUTCOME
    assert outcome.outcome is AuditOutcome.OK


async def test_a_refund_the_worker_cannot_be_told_about_still_stands_and_says_so() -> None:
    queue = NullAdminQueue(refusing=True)
    async with (
        open_container(make_settings(), FakeRedis(), MemoryRateLimits(), queue) as container,
        open_client(container) as http,
    ):
        panel = Panel(container=container, http=http, queue=queue)
        _, review_id = await seed_job(panel)
        assert review_id is not None
        await signed_in(panel)
        await step_up(panel, subject=review_id)

        response = await post(panel, url(MEDIA_REVIEW_REFUND_PATH, review_id=review_id))

        assert response.status_code == 200
        assert response.json()["isQueued"] is False
        # Committed: media_sweep re-drives an unapplied decision.
        assert (await review_row(panel, review_id)).decision is MediaReviewDecision.BLOCKED
        [outcome] = await audit_rows(panel, AuditAction.MODERATION_REFUND_OUTCOME)
        assert outcome.outcome is AuditOutcome.ERROR


async def test_a_beta_refund_is_audited_as_minting_nothing(panel: Panel) -> None:
    _, review_id = await seed_job(panel, paid_via=MediaPaidVia.BETA)
    assert review_id is not None
    await signed_in(panel)
    await step_up(panel, subject=review_id)

    response = await post(panel, url(MEDIA_REVIEW_REFUND_PATH, review_id=review_id))

    assert response.status_code == 200
    assert response.json()["review"]["isRefundable"] is False
    [intent] = await audit_rows(panel, AuditAction.MODERATION_REFUND)
    assert intent.record_count == 0


# ---------------------------------------------------------------------------
# Release, and deciding twice
# ---------------------------------------------------------------------------
async def test_a_release_needs_no_step_up_and_asks_the_worker_to_deliver(panel: Panel) -> None:
    job_id, review_id = await seed_job(panel)
    assert review_id is not None
    await signed_in(panel)

    response = await post(
        panel,
        url(MEDIA_REVIEW_RELEASE_PATH, review_id=review_id),
        reasonCode=AuditReasonCode.ROUTINE_OPS.value,
    )

    assert response.status_code == 200, response.text
    assert response.json()["review"]["decision"] == MediaReviewDecision.RELEASED.value
    assert (await review_row(panel, review_id)).decision is MediaReviewDecision.RELEASED
    assert [call.review_id for call in panel.queue.calls] == [review_id]
    [approved] = await audit_rows(panel, AuditAction.MODERATION_APPROVE)
    assert approved.subject_id == str(job_id)


async def test_a_second_decision_is_a_conflict_and_never_a_second_refund(panel: Panel) -> None:
    _, review_id = await seed_job(panel)
    assert review_id is not None
    await signed_in(panel)
    await step_up(panel, subject=review_id)
    assert (
        await post(panel, url(MEDIA_REVIEW_REFUND_PATH, review_id=review_id))
    ).status_code == 200

    again = await post(panel, url(MEDIA_REVIEW_REFUND_PATH, review_id=review_id))
    release = await post(panel, url(MEDIA_REVIEW_RELEASE_PATH, review_id=review_id))

    assert again.status_code == 409 and release.status_code == 409
    assert len(panel.queue.calls) == 1
    assert len(await audit_rows(panel, AuditAction.MODERATION_REFUND)) == 1


async def test_an_unknown_review_is_a_404(panel: Panel) -> None:
    await signed_in(panel)

    detail = await panel.http.get(url(MEDIA_REVIEW_PATH, review_id=uuid4()))
    release = await post(panel, url(MEDIA_REVIEW_RELEASE_PATH, review_id=uuid4()))

    assert detail.status_code == 404 and release.status_code == 404


# ---------------------------------------------------------------------------
# Hold
# ---------------------------------------------------------------------------
async def test_a_hold_stops_a_screened_output_and_opens_a_manual_review(panel: Panel) -> None:
    job_id, _ = await seed_job(
        panel,
        state=MediaJobState.POST,
        output_decision=MediaScreenDecision.ALLOW,
        with_review=False,
    )
    username = await signed_in(panel)

    response = await post(panel, url(MEDIA_JOB_HOLD_PATH, job_id=job_id))

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["source"] == "manual" and body["decision"] is None
    assert body["actor"] == username
    job = await job_row(panel, job_id)
    # ``review`` is what makes a delivery already queued stand down.
    assert (job.state, job.output_decision) == (MediaJobState.HELD, MediaScreenDecision.REVIEW)
    assert panel.queue.calls == []
    [held] = await audit_rows(panel, AuditAction.MODERATION_HOLD)
    assert held.subject_id == str(job_id)


@pytest.mark.parametrize(
    ("state", "decision"),
    [
        (MediaJobState.POST, MediaScreenDecision.UNAVAILABLE),
        (MediaJobState.GENERATING, MediaScreenDecision.ALLOW),
        (MediaJobState.DELIVERED, MediaScreenDecision.ALLOW),
    ],
    ids=["unscreened", "still-rendering", "already-delivered"],
)
async def test_only_a_screened_output_on_its_way_out_can_be_held(
    panel: Panel, state: MediaJobState, decision: MediaScreenDecision
) -> None:
    job_id, _ = await seed_job(panel, state=state, output_decision=decision, with_review=False)
    await signed_in(panel)

    response = await post(panel, url(MEDIA_JOB_HOLD_PATH, job_id=job_id))

    assert response.status_code == 409
    assert (await job_row(panel, job_id)).state is state
    assert await audit_rows(panel, AuditAction.MODERATION_HOLD) == []
