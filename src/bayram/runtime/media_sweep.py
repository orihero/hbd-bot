"""``media_sweep``: the five-minutely reaper and re-driver of the media stage chain.

IMAGE_VIDEO_SPEC §3.3 (the ``media_sweep`` row), §3.4, §3.5, §2.6. Every stage enqueues its
successor after committing, and an enqueue can be lost (Redis blipped, the worker was killed
between the commit and the enqueue). Media jobs are not on the song debit path, so the song
sweeps never see them: this is their only backstop, and it is what makes "the row is the
promise, the queue is only the nudge" true. Eight arms, each bounded by :data:`SWEEP_BATCH`:

a. **abandon** unpaid rows past the quote TTL (``drafting``/``screening``/``quoted``) and
   ``awaiting_payment`` rows only once their Payme intent is EXPIRED or CANCELLED plus a
   10-minute grace — never on a clock of our own that could disagree with the intent (§2.6);
b. **start** ``paid`` rows older than two minutes (a burned or lost ``media_start``);
c. **re-drive** ``screening`` rows that never reached a verdict; ``queued``/``generating``
   rows whose heartbeat (``updated_at``) is stale — per unfinished variant, the next submit,
   a poll, a fetch or the fan-in, whatever its latest attempt says is missing; and ``post``
   rows whose output screen or delivery was lost;
d. **fail** paid jobs past their SKU deadline (§3.5), through the state-guarded path, with one
   credit when they were paid for;
e. **GPU hygiene** (§3.4): drop queue members whose job is finished or gone; free a lock
   held by an attempt that ended; hand an attempt that has sat ``submitting`` for five minutes
   to reconciliation (marking it ``ambiguous``, never re-posting it, §4.2); and, with the slot
   free, re-drive the queue HEAD by its own variant — the job-level heartbeat is refreshed by
   the job's other variant waiting, so it cannot tell that the head's own chain was lost;
f. **unstick** ``delivering`` rows a dead worker left mid-send (§3.3 ``media_deliver``):
   delivery is at-most-once, so a row whose album is recorded as sent is ``delivered``, and
   any other is failed with one credit;
g. **the review queue** (§6.6, M3.2): a pending review past its 24 h SLA is decided
   ``expired`` (→ failed + one credit), a decided review whose ``media_review_apply`` was lost
   is re-driven, and a released ``held`` job whose delivery enqueue was lost is delivered;
h. **orphaned holds** (M3.R): a ``held`` job that no review will ever end — a paid-backend
   ``ambiguous_submit`` hold (§4.3: "refund credit if unresolved in 2 h"), or one held before
   revision 0032 — is failed with one credit two hours after its last move. Without this it
   would sit in the one-open-request index for ever, and the customer could never ask again.

Every re-enqueue takes the NEXT suffix — a bumped ``submit_seq``/``oscreen_seq``, or the sweep's
own tick — never an id that ARQ might still be remembering (§3.3 "ARQ job ids").

It never raises into the scheduler: an arm that fails is logged and counted, and the next run
five minutes later is the retry.
"""

from __future__ import annotations

import time
from collections.abc import Mapping
from datetime import datetime, timedelta
from typing import Any, Final
from uuid import UUID

import sqlalchemy as sa

from bayram.db.enums import (
    MEDIA_TERMINAL_STATES,
    MediaAttemptStage,
    MediaAttemptStatus,
    MediaCreditReason,
    MediaJobState,
    MediaKind,
    MediaOutputRole,
    MediaReviewDecision,
    MediaScreenDecision,
    MediaSku,
    MediaVoiceMode,
    PaymentIntentState,
)
from bayram.db.media import (
    bump_seq,
    grant_refund,
    latest_attempts,
    list_outputs,
    set_attempt_status,
    transition,
)
from bayram.db.media_reviews import decide_review, overdue_reviews, unapplied_reviews
from bayram.db.models.media_attempt import MediaAttemptRow
from bayram.db.models.media_job import MediaJobRow
from bayram.db.models.moderation_review import SYSTEM_REVIEW_ACTOR, ModerationReviewRow
from bayram.db.models.payment_intent import PaymentIntentRow
from bayram.db.retention import resolve_retention_policy
from bayram.logging import get_logger
from bayram.media.stages import (
    MEDIA_CLEANUP_JOB,
    MEDIA_DELIVER_JOB,
    MEDIA_FETCH_JOB,
    MEDIA_MUX_JOB,
    MEDIA_OUTPUT_SCREEN_JOB,
    MEDIA_POLL_JOB,
    MEDIA_PRESCREEN_JOB,
    MEDIA_REVIEW_JOB,
    MEDIA_SCREEN_JOB,
    MEDIA_START_JOB,
    MEDIA_SWEEP_JOB,
    cleanup_job_id,
    deliver_job_id,
    fetch_job_id,
    mux_job_id,
    output_screen_job_id,
    poll_job_id,
    prescreen_job_id,
    review_job_id,
    screen_job_id,
    sku_deadline,
    start_job_id,
)
from bayram.runtime.gpu_lock import parse_queue_member, queue_member
from bayram.runtime.media_jobs import (
    GPU_BACKENDS,
    MediaErrorCode,
    MediaRuntime,
    enqueue_stage,
    enqueue_submit,
    enqueue_voice_stage,
    fail_job,
    image_fan_in,
    is_attempt_final,
    is_voice_leased,
    media_runtime,
    reconcile_ambiguous,
    video_fan_in,
)

__all__ = [
    "MEDIA_SWEEP_CRON_MINUTES",
    "SWEEP_BATCH",
    "STARTABLE_AFTER",
    "STALE_HEARTBEAT",
    "ORPHANED_HOLD_AFTER",
    "PAID_RENDER_GRACE",
    "media_sweep",
    "sweep_media",
]

_LOG = get_logger(__name__)

#: Every five minutes on the :01 offset, which no other writer in this worker uses — the Payme
#: sweep owns the multiples of five and the broadcast sweep :04, :09, … — except that :31 is
#: the workspace sweep's, so that one run moves to :32. Every other offset collides with
#: retention (:17), the activity snapshot (:07) or the vendor poll (:43).
MEDIA_SWEEP_CRON_MINUTES: Final[tuple[int, ...]] = (1, 6, 11, 16, 21, 26, 32, 36, 41, 46, 51, 56)

#: Rows per arm per run. A backlog is worked off in five-minute bites.
SWEEP_BATCH: Final[int] = 100

#: §3.3 (b): a paid row this old has not been started by the path that paid it.
STARTABLE_AFTER: Final[timedelta] = timedelta(minutes=2)

#: §3.3 (c): no stage touched a working row for this long, so its chain is presumed dead.
#: Longer than the slowest heartbeat (a video poll every 15 s, a waiting submit every 15 s).
STALE_HEARTBEAT: Final[timedelta] = timedelta(minutes=3)

#: A ``post`` row whose output screen went missing. Longer than the 2-minute guard retry.
_STALE_POST: Final[timedelta] = timedelta(minutes=10)

#: A ``screening`` row with no verdict this long after its last write lost its screen job.
_STALE_SCREEN: Final[timedelta] = timedelta(minutes=10)

#: §3.4: a lock held by a ``submitting`` attempt this old is a worker that died mid-POST.
_SUBMITTING_LOCK_MAX: Final[timedelta] = timedelta(minutes=5)

#: A ``delivering`` row untouched this long lost its worker mid-send. A send is one Bot API
#: call with a handful of ARQ retries; ten minutes is far past any of them.
_STALE_DELIVERING: Final[timedelta] = timedelta(minutes=10)

#: A decided review not yet applied this long after the decision lost its apply enqueue.
_STALE_DECISION: Final[timedelta] = timedelta(minutes=2)

#: §4.3: a hold no review covers is refunded when it is still unresolved after this.
ORPHANED_HOLD_AFTER: Final[timedelta] = timedelta(hours=2)

#: §3.5: how long past its deadline a job on a paid backend may wait on a render the vendor
#: still has (submitted, not yet terminal) before it is failed and refunded anyway.
PAID_RENDER_GRACE: Final[timedelta] = timedelta(hours=2)

#: §2.6: an ``awaiting_payment`` row is abandoned only this long after its intent ended.
_INTENT_GRACE: Final[timedelta] = timedelta(minutes=10)

#: The states whose deadline runs (§3.5). ``held`` waits on a human and has its own 24 h SLA
#: (§6.6, the ``reviews`` arm); ``delivering`` is a send in flight.
_DEADLINE_STATES: Final[tuple[MediaJobState, ...]] = (
    MediaJobState.PAID,
    MediaJobState.QUEUED,
    MediaJobState.GENERATING,
    MediaJobState.POST,
)
_QUOTE_STATES: Final[tuple[MediaJobState, ...]] = (
    MediaJobState.DRAFTING,
    MediaJobState.SCREENING,
    MediaJobState.QUOTED,
)
_ENDED_INTENT_STATES: Final[tuple[PaymentIntentState, ...]] = (
    PaymentIntentState.EXPIRED,
    PaymentIntentState.CANCELLED,
)
#: Attempts whose lock is plainly stale. ``ambiguous`` is not here: it holds the slot on
#: purpose while it is reconciled (§4.2), and is freed only once its job stopped working.
_ENDED_ATTEMPT_STATES: Final[frozenset[MediaAttemptStatus]] = frozenset(
    {MediaAttemptStatus.FAILED, MediaAttemptStatus.REJECTED}
)
_WORKING_STATES: Final[tuple[MediaJobState, ...]] = (
    MediaJobState.QUEUED,
    MediaJobState.GENERATING,
)

_STAGE_FOR_KIND: Final[Mapping[MediaKind, MediaAttemptStage]] = {
    MediaKind.IMAGE: MediaAttemptStage.IMAGE,
    MediaKind.VIDEO: MediaAttemptStage.VIDEO,
}
#: Poll ticks handed out by the sweep start here, far above any tick a live chain reaches,
#: and move with the sweep's own tick so each run's id is new.
_SWEEP_POLL_TICK_BASE: Final[int] = 1_000_000


def _tick(now: datetime) -> int:
    """The sweep's own monotonic suffix: whole minutes since the epoch."""
    return int(now.timestamp() // 60)


async def _abandon(rt: MediaRuntime, now: datetime) -> int:
    quote_cutoff = now - timedelta(seconds=rt.settings.media_quote_ttl_s)
    intent_cutoff = now - _INTENT_GRACE
    orphan_cutoff = now - timedelta(seconds=rt.settings.payme_intent_ttl_s) - _INTENT_GRACE
    async with rt.sessions() as session:
        stale_quotes = (
            await session.scalars(
                sa.select(MediaJobRow.id)
                .where(MediaJobRow.state.in_(_QUOTE_STATES), MediaJobRow.created_at < quote_cutoff)
                .limit(SWEEP_BATCH)
            )
        ).all()
        ended_intent = (
            sa.select(PaymentIntentRow.id)
            .where(
                PaymentIntentRow.id == MediaJobRow.payment_intent_id,
                PaymentIntentRow.state.in_(_ENDED_INTENT_STATES),
                PaymentIntentRow.valid_until < intent_cutoff,
            )
            .exists()
        )
        stale_payments = (
            await session.scalars(
                sa.select(MediaJobRow.id)
                .where(
                    MediaJobRow.state == MediaJobState.AWAITING_PAYMENT,
                    sa.or_(
                        ended_intent,
                        # No intent recorded at all: nothing can ever settle it. Wait out the
                        # longest an intent could have lived, then let it go.
                        sa.and_(
                            MediaJobRow.payment_intent_id.is_(None),
                            MediaJobRow.updated_at < orphan_cutoff,
                        ),
                    ),
                )
                .limit(SWEEP_BATCH)
            )
        ).all()
    abandoned = 0
    for job_id, expected in [
        *((job_id, _QUOTE_STATES) for job_id in stale_quotes),
        *((job_id, (MediaJobState.AWAITING_PAYMENT,)) for job_id in stale_payments),
    ]:
        async with rt.sessions.begin() as session:
            moved = await transition(
                session,
                job_id,
                expected=expected,
                to=MediaJobState.ABANDONED,
                now=now,
                policy=resolve_retention_policy(rt.settings),
            )
        if moved:
            abandoned += 1
            await enqueue_stage(rt, MEDIA_CLEANUP_JOB, str(job_id), job_id=cleanup_job_id(job_id))
    return abandoned


async def _start_paid(rt: MediaRuntime, now: datetime) -> int:
    async with rt.sessions() as session:
        ids = (
            await session.scalars(
                sa.select(MediaJobRow.id)
                .where(
                    MediaJobRow.state == MediaJobState.PAID,
                    MediaJobRow.paid_at < now - STARTABLE_AFTER,
                )
                .limit(SWEEP_BATCH)
            )
        ).all()
    tick = _tick(now)
    for job_id in ids:
        await enqueue_stage(
            rt, MEDIA_START_JOB, str(job_id), tick, job_id=start_job_id(job_id, tick)
        )
    return len(ids)


async def _redrive_variant(
    rt: MediaRuntime, job: MediaJobRow, variant: int, latest: MediaAttemptRow | None, tick: int
) -> None:
    if latest is None:
        await enqueue_submit(rt, job.id, variant, 1, defer_s=0.0)
    elif latest.status is MediaAttemptStatus.SUBMITTING:
        # The submit handler decides between "in flight" and "crashed before the POST".
        await enqueue_submit(rt, job.id, variant, latest.attempt, defer_s=0.0)
    elif latest.status is MediaAttemptStatus.SUBMITTED:
        poll_tick = _SWEEP_POLL_TICK_BASE + tick
        await enqueue_stage(
            rt,
            MEDIA_POLL_JOB,
            str(job.id),
            variant,
            latest.attempt,
            poll_tick,
            job_id=poll_job_id(job.id, variant, latest.attempt, poll_tick),
        )
    elif latest.status is MediaAttemptStatus.SUCCEEDED:
        await enqueue_stage(
            rt,
            MEDIA_FETCH_JOB,
            str(job.id),
            variant,
            latest.attempt,
            job_id=fetch_job_id(job.id, variant, latest.attempt),
        )
    elif latest.status is MediaAttemptStatus.AMBIGUOUS:
        # Reconciled before anything is resubmitted, final or not (§4.2): the submit handler
        # reads the gateway's queue for this attempt and decides.
        await enqueue_submit(rt, job.id, variant, latest.attempt, defer_s=0.0)
    elif not is_attempt_final(latest, rt.settings.media_max_attempts):
        await enqueue_submit(rt, job.id, variant, latest.attempt + 1, defer_s=0.0)


async def _redrive_video(rt: MediaRuntime, job: MediaJobRow, tick: int) -> None:
    """A stalled video (§3.3): the render's own re-drive, the voice if it never arrived, and
    the fan-in — idempotent, so a chain that only lost the fan-in's enqueue moves on."""
    async with rt.sessions() as session:
        latest = await latest_attempts(session, job.id, stage=_STAGE_FOR_KIND[job.kind])
        rendered = bool(await list_outputs(session, job.id, role=MediaOutputRole.VIDEO_RAW))
    if not rendered:
        await _redrive_variant(rt, job, 0, latest.get(0), tick)
    # Not while a voice run started within its stage timeout (``is_voice_leased``): a slow
    # narration is not a lost one, and a second copy would spend a second paid TTS call.
    if (
        job.voice_mode is not MediaVoiceMode.NONE
        and job.audio_ready_at is None
        and not await is_voice_leased(rt, job.id)
    ):
        await enqueue_voice_stage(rt, job, n=tick)
    await video_fan_in(rt, job.id)


async def _has_clip(rt: MediaRuntime, job_id: UUID) -> bool:
    async with rt.sessions() as session:
        return bool(await list_outputs(session, job_id, role=MediaOutputRole.VIDEO))


async def _redrive(rt: MediaRuntime, now: datetime) -> int:
    async with rt.sessions() as session:
        working = (
            await session.scalars(
                sa.select(MediaJobRow)
                .where(
                    MediaJobRow.state.in_((MediaJobState.QUEUED, MediaJobState.GENERATING)),
                    MediaJobRow.updated_at < now - STALE_HEARTBEAT,
                )
                .limit(SWEEP_BATCH)
            )
        ).all()
        stuck_post = (
            await session.execute(
                sa.select(MediaJobRow.id, MediaJobRow.output_decision, MediaJobRow.kind)
                .where(
                    MediaJobRow.state == MediaJobState.POST,
                    MediaJobRow.updated_at < now - _STALE_POST,
                )
                .limit(SWEEP_BATCH)
            )
        ).all()
        # Released by a reviewer (§6.6), with the delivery enqueue lost.
        released_held = (
            await session.scalars(
                sa.select(MediaJobRow.id)
                .where(
                    MediaJobRow.state == MediaJobState.HELD,
                    MediaJobRow.output_decision == MediaScreenDecision.ALLOW,
                    MediaJobRow.updated_at < now - _STALE_POST,
                )
                .limit(SWEEP_BATCH)
            )
        ).all()
        # A screen that never reached a verdict (the job died, or the enqueue was lost). A tray
        # that is ``busy`` for capacity carries a decision and waits for the customer's 🔁.
        unscreened = (
            await session.scalars(
                sa.select(MediaJobRow.id)
                .where(
                    MediaJobRow.state == MediaJobState.SCREENING,
                    MediaJobRow.screen_decision.is_(None),
                    MediaJobRow.updated_at < now - _STALE_SCREEN,
                )
                .limit(SWEEP_BATCH)
            )
        ).all()
        # The same for a video draft's prescreen (§2.4.1). A busy or allowed draft carries a
        # decision and waits for the customer.
        unprescreened = (
            await session.scalars(
                sa.select(MediaJobRow.id)
                .where(
                    MediaJobRow.state == MediaJobState.DRAFTING,
                    MediaJobRow.screen_decision.is_(None),
                    MediaJobRow.updated_at < now - _STALE_SCREEN,
                )
                .limit(SWEEP_BATCH)
            )
        ).all()
    tick = _tick(now)
    for job_id in unscreened:
        await enqueue_stage(
            rt, MEDIA_SCREEN_JOB, str(job_id), tick, job_id=screen_job_id(job_id, tick)
        )
    for job_id in unprescreened:
        await enqueue_stage(
            rt, MEDIA_PRESCREEN_JOB, str(job_id), tick, job_id=prescreen_job_id(job_id, tick)
        )
    for job in working:
        if job.kind is MediaKind.VIDEO:
            await _redrive_video(rt, job, tick)
            continue
        async with rt.sessions() as session:
            latest = await latest_attempts(session, job.id, stage=_STAGE_FOR_KIND[job.kind])
            done = {
                output.variant
                for output in await list_outputs(session, job.id, role=MediaOutputRole.IMAGE)
            }
        for variant in range(job.outputs_requested):
            if variant not in done:
                await _redrive_variant(rt, job, variant, latest.get(variant), tick)
        # Every variant may already be finished with the fan-in lost; it is idempotent.
        await image_fan_in(rt, job.id)
    for job_id, decision, kind in stuck_post:
        if kind is MediaKind.VIDEO and decision is None and not await _has_clip(rt, job_id):
            # The fan-in moved it to ``post`` and the mux enqueue was lost (or the mux died).
            await enqueue_stage(
                rt, MEDIA_MUX_JOB, str(job_id), tick, job_id=mux_job_id(job_id, tick)
            )
            continue
        if decision is MediaScreenDecision.ALLOW:
            # Screened and allowed; the delivery enqueue was lost.
            await enqueue_stage(rt, MEDIA_DELIVER_JOB, str(job_id), job_id=deliver_job_id(job_id))
            continue
        async with rt.sessions.begin() as session:
            seq = await bump_seq(session, job_id, column="oscreen_seq", now=now)
        if seq is not None:
            await enqueue_stage(
                rt,
                MEDIA_OUTPUT_SCREEN_JOB,
                str(job_id),
                seq,
                job_id=output_screen_job_id(job_id, seq),
            )
    for job_id in released_held:
        await enqueue_stage(rt, MEDIA_DELIVER_JOB, str(job_id), job_id=deliver_job_id(job_id, tick))
    return len(unscreened) + len(working) + len(stuck_post) + len(released_held)


async def _fail_past_deadline(rt: MediaRuntime, now: datetime) -> int:
    """Fail and refund every job past its SKU's deadline (§3.5).

    Except, for a backend that bills per call, a job whose render is still with the vendor
    (§3.5 "Higgsfield: only after status confirms terminal or 2 h ambiguity"): the vendor
    keeps rendering and billing whatever we decide, so its late result is waited for — up to
    :data:`PAID_RENDER_GRACE` past the deadline — rather than paid for and thrown away.
    """
    failed = 0
    in_flight = (
        sa.select(MediaAttemptRow.id)
        .where(
            MediaAttemptRow.job_id == MediaJobRow.id,
            MediaAttemptRow.status.in_(
                (MediaAttemptStatus.SUBMITTING, MediaAttemptStatus.SUBMITTED)
            ),
        )
        .exists()
    )
    for sku in MediaSku:
        cutoff = now - sku_deadline(rt.settings, sku)
        async with rt.sessions() as session:
            ids = (
                await session.scalars(
                    sa.select(MediaJobRow.id)
                    .where(
                        MediaJobRow.sku == sku,
                        MediaJobRow.state.in_(_DEADLINE_STATES),
                        MediaJobRow.paid_at < cutoff,
                        sa.or_(
                            MediaJobRow.backend.is_(None),
                            MediaJobRow.backend.in_(tuple(GPU_BACKENDS)),
                            MediaJobRow.paid_at < cutoff - PAID_RENDER_GRACE,
                            ~in_flight,
                        ),
                    )
                    .limit(SWEEP_BATCH)
                )
            ).all()
        for job_id in ids:
            if await fail_job(
                rt,
                job_id,
                expected=_DEADLINE_STATES,
                error_code=MediaErrorCode.DEADLINE,
                refund=MediaCreditReason.DEADLINE,
            ):
                failed += 1
    return failed


async def _gpu_hygiene(rt: MediaRuntime, now: datetime) -> int:
    fixed = 0
    members = await rt.gpu.members()
    parsed = {member: parse_queue_member(member) for member in members}
    job_ids = {found[0] for found in parsed.values() if found is not None}
    async with rt.sessions() as session:
        live = (
            set(
                (
                    await session.scalars(
                        sa.select(MediaJobRow.id).where(
                            MediaJobRow.id.in_(job_ids),
                            MediaJobRow.state.not_in(tuple(MEDIA_TERMINAL_STATES)),
                        )
                    )
                ).all()
            )
            if job_ids
            else set()
        )
    gone = [member for member, found in parsed.items() if found is None or found[0] not in live]
    if gone:
        await rt.gpu.leave(*gone)
        fixed += len(gone)
    holder = await rt.gpu.holder()
    if holder is None:
        return fixed
    try:
        attempt_id: UUID | None = UUID(holder)
    except ValueError:
        attempt_id = None
    async with rt.sessions() as session:
        row = await session.get(MediaAttemptRow, attempt_id) if attempt_id is not None else None
        job = await session.get(MediaJobRow, row.job_id) if row is not None else None
    job_working = job is not None and job.state in _WORKING_STATES
    if (
        row is None
        or row.status in _ENDED_ATTEMPT_STATES
        or (row.status is MediaAttemptStatus.AMBIGUOUS and not job_working)
    ):
        if await rt.gpu.release(holder):
            fixed += 1
    elif (
        row.status is MediaAttemptStatus.SUBMITTING
        and row.remote_id is None
        and row.created_at < now - _SUBMITTING_LOCK_MAX
    ):
        async with rt.sessions.begin() as session:
            marked = await set_attempt_status(
                session,
                row.id,
                expected=(MediaAttemptStatus.SUBMITTING,),
                status=MediaAttemptStatus.AMBIGUOUS,
                now=now,
                error_code=MediaErrorCode.CRASHED_BEFORE_POST.value,
            )
            row = await session.get(MediaAttemptRow, row.id, populate_existing=True)
        if marked and row is not None and job is not None and job_working:
            # The POST may have landed before the worker died: reconcile, holding the slot
            # while the gateway might be rendering it (§4.2), rather than free it blind.
            await reconcile_ambiguous(rt, job, row)
            fixed += 1
        elif await rt.gpu.release(holder):
            fixed += 1
    return fixed


async def _redrive_head(rt: MediaRuntime, now: datetime) -> int:
    """The GPU is free, yet the queue's head is not moving: re-drive the head's own variant.

    ``_redrive`` goes by the job's heartbeat, and a job's other variant, waiting for the slot,
    refreshes that heartbeat every 15 s — so a head whose own submit chain was lost would look
    alive while it, and every job behind it, waited out the deadline. Re-driving a head that
    was merely between two of its 15-second tries starts a second chain for the same attempt;
    that one finds the attempt row the first wrote and ends (``media_submit`` is idempotent).
    """
    if await rt.gpu.holder() is not None:
        return 0
    members = await rt.gpu.members()
    if not members:
        return 0
    parsed = parse_queue_member(members[0])
    if parsed is None:
        return 0
    job_id, variant = parsed
    async with rt.sessions() as session:
        job = await session.get(MediaJobRow, job_id)
        if job is None or job.state not in _WORKING_STATES or job.kind is not MediaKind.IMAGE:
            return 0
        latest = (await latest_attempts(session, job_id, stage=_STAGE_FOR_KIND[job.kind])).get(
            variant
        )
        done = variant in {
            output.variant
            for output in await list_outputs(session, job_id, role=MediaOutputRole.IMAGE)
        }
    if done or (
        latest is not None
        and latest.status is not MediaAttemptStatus.AMBIGUOUS
        and is_attempt_final(latest, rt.settings.media_max_attempts)
    ):
        # A finished variant that never left the queue blocks everyone behind it.
        await rt.gpu.leave(queue_member(job_id, variant))
        await image_fan_in(rt, job_id)
        return 1
    await _redrive_variant(rt, job, variant, latest, _tick(now))
    return 1


async def _unstick_delivering(rt: MediaRuntime, now: datetime) -> int:
    async with rt.sessions() as session:
        stuck = (
            await session.scalars(
                sa.select(MediaJobRow.id)
                .where(
                    MediaJobRow.state == MediaJobState.DELIVERING,
                    MediaJobRow.updated_at < now - _STALE_DELIVERING,
                )
                .limit(SWEEP_BATCH)
            )
        ).all()
    fixed = 0
    for job_id in stuck:
        async with rt.sessions() as session:
            outputs = await list_outputs(session, job_id, role=MediaOutputRole.IMAGE)
            job = await session.get(MediaJobRow, job_id)
        if job is None:
            continue
        if any(output.tg_file_id for output in outputs):
            # The album is on record as sent: finish what the dead worker could not.
            async with rt.sessions.begin() as session:
                moved = await transition(
                    session,
                    job_id,
                    expected=(MediaJobState.DELIVERING,),
                    to=MediaJobState.DELIVERED,
                    now=now,
                    values={"delivered_at": now},
                    policy=resolve_retention_policy(rt.settings),
                )
                if moved and len(outputs) < job.outputs_requested:
                    # Q3, as ``media_deliver`` would have granted it.
                    await grant_refund(
                        session, job_id, reason=MediaCreditReason.GENERATION_FAILED, now=now
                    )
            if moved:
                fixed += 1
                await enqueue_stage(
                    rt, MEDIA_CLEANUP_JOB, str(job_id), job_id=cleanup_job_id(job_id)
                )
            continue
        # Not known to have gone out: at-most-once means we cannot resend blind, so the
        # customer gets a credit (``fail_job`` also enqueues the cleanup).
        if await fail_job(
            rt,
            job_id,
            expected=(MediaJobState.DELIVERING,),
            error_code=MediaErrorCode.DELIVERY_FAILED,
            refund=MediaCreditReason.GENERATION_FAILED,
        ):
            fixed += 1
    return fixed


async def _review_queue(rt: MediaRuntime, now: datetime) -> int:
    """§6.6: expire what nobody decided in 24 h, and re-drive decisions nobody applied."""
    async with rt.sessions() as session:
        overdue = await overdue_reviews(session, now=now, limit=SWEEP_BATCH)
    expired: list[UUID] = []
    for review_id in overdue:
        async with rt.sessions.begin() as session:
            if await decide_review(
                session,
                review_id,
                decision=MediaReviewDecision.EXPIRED,
                now=now,
                actor_id=None,
                actor=SYSTEM_REVIEW_ACTOR,
                reason_code=None,
            ):
                expired.append(review_id)
    for review_id in expired:
        await enqueue_stage(rt, MEDIA_REVIEW_JOB, str(review_id), job_id=review_job_id(review_id))
    async with rt.sessions() as session:
        lost = await unapplied_reviews(
            session, decided_before=now - _STALE_DECISION, limit=SWEEP_BATCH
        )
    tick = _tick(now)
    for review_id in lost:
        await enqueue_stage(
            rt, MEDIA_REVIEW_JOB, str(review_id), tick, job_id=review_job_id(review_id, tick)
        )
    return len(expired) + len(lost)


async def _orphaned_holds(rt: MediaRuntime, now: datetime) -> int:
    """(h) ``held`` with no pending or unapplied review and no release waiting on delivery,
    untouched for :data:`ORPHANED_HOLD_AFTER` → failed + one credit, no strike."""
    live_review = sa.exists().where(
        ModerationReviewRow.job_id == MediaJobRow.id,
        sa.or_(ModerationReviewRow.decision.is_(None), ModerationReviewRow.applied_at.is_(None)),
    )
    async with rt.sessions() as session:
        ids = (
            await session.scalars(
                sa.select(MediaJobRow.id)
                .where(
                    MediaJobRow.state == MediaJobState.HELD,
                    MediaJobRow.updated_at < now - ORPHANED_HOLD_AFTER,
                    sa.or_(
                        MediaJobRow.output_decision.is_(None),
                        MediaJobRow.output_decision != MediaScreenDecision.ALLOW,
                    ),
                    ~live_review,
                )
                .limit(SWEEP_BATCH)
            )
        ).all()
    failed = 0
    for job_id in ids:
        if await fail_job(
            rt,
            job_id,
            expected=(MediaJobState.HELD,),
            error_code=MediaErrorCode.HELD_UNRESOLVED,
            refund=MediaCreditReason.GENERATION_FAILED,
        ):
            failed += 1
    return failed


async def sweep_media(rt: MediaRuntime, *, now: datetime | None = None) -> dict[str, Any]:
    """Run the eight arms once (GPU hygiene in two steps). A failed arm is contained, reported."""
    at = now or rt.clock()
    summary: dict[str, Any] = {}
    errors: list[str] = []
    for name, arm in (
        ("abandoned", _abandon),
        ("started", _start_paid),
        ("redriven", _redrive),
        ("deadline_failed", _fail_past_deadline),
        ("gpu_fixed", _gpu_hygiene),
        ("head_redriven", _redrive_head),
        ("delivering_unstuck", _unstick_delivering),
        ("reviews", _review_queue),
        ("orphaned_holds_failed", _orphaned_holds),
    ):
        try:
            summary[name] = await arm(rt, at)
        except Exception as exc:
            _LOG.error(
                "a media sweep arm failed", extra={"arm": name, "failure": repr(exc)}, exc_info=exc
            )
            summary[name] = 0
            errors.append(name)
    summary["errors"] = errors
    return summary


async def media_sweep(ctx: Mapping[str, Any]) -> dict[str, Any]:
    """The cron entry point. Raises only ``PipelineError`` for a mis-wired worker."""
    rt = media_runtime(ctx)
    started = time.monotonic()
    summary = await sweep_media(rt)
    summary["duration_ms"] = int((time.monotonic() - started) * 1000)
    _LOG.info("media sweep finished", extra=summary)
    return summary


assert media_sweep.__name__ == MEDIA_SWEEP_JOB
