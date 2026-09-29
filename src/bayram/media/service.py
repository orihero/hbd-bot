"""Row moves the bot makes on a frozen media request, and the enqueue that follows each.

IMAGE_VIDEO_SPEC §2.3.1, §2.5, §7.2. The bot's media router (M2.5) is the caller; the worker's
stage chain (:mod:`bayram.runtime.media_jobs`) is what they hand the request to. Two rules:

* **commit, then enqueue** — the job the stage chain runs reads the row, so an enqueue before
  the commit could start a stage that sees nothing. An enqueue that fails after the commit is
  logged and left to ``media_sweep``, which re-drives a ``paid`` row older than two minutes
  (§3.3 ``media_sweep`` (b)): the row is the promise, the queue is only the nudge;
* **entitlement is re-checked here, at press time** (§2.5): the 🎁 button the worker drew is
  never proof that the account may still use it.
"""

from __future__ import annotations

from collections.abc import Awaitable
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Protocol
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from bayram.config import Settings
from bayram.db.enums import MediaJobState, MediaKind, MediaPaidVia, MediaPurchaseProvider
from bayram.db.media import count_paid_since, load_job, mark_paid, record_purchase
from bayram.logging import get_logger
from bayram.media.offering import daily_cap, is_beta_member, is_live_paid, media_offered
from bayram.media.stages import (
    MEDIA_PRESCREEN_JOB,
    MEDIA_SCREEN_JOB,
    MEDIA_SCRIPT_JOB,
    MEDIA_START_JOB,
    prescreen_job_id,
    screen_job_id,
    script_job_id,
    sku_deadline,
    start_job_id,
)

__all__ = [
    "MediaQueue",
    "BetaStart",
    "utc_day_start",
    "is_at_daily_cap",
    "start_free_beta",
    "enqueue_prescreen",
    "enqueue_screen",
    "enqueue_script",
    "enqueue_start",
]

_LOG = get_logger(__name__)


class MediaQueue(Protocol):
    """ARQ's pool, as far as media uses it. ``ArqRedis`` satisfies it."""

    def enqueue_job(
        self, function: str, *args: Any, _job_id: str, _defer_by: float = ...
    ) -> Awaitable[Any]: ...


class BetaStart(StrEnum):
    """What a 🎁 press came to."""

    STARTED = "started"
    #: The row is not this account's, or not ``quoted`` any more — ``media.stale``.
    STALE = "stale"
    #: The account, the SKU or the rail no longer admits a free beta — ``media.stale`` too;
    #: the reason is logged, never shown.
    NOT_ENTITLED = "not_entitled"
    #: Today's paid requests of this kind are used up (§7.6) — ``media.daily_cap``.
    AT_DAILY_CAP = "at_daily_cap"


def utc_day_start(now: datetime) -> datetime:
    """Midnight UTC of ``now``'s day: where a daily cap's count starts (§7.6)."""
    return now.astimezone(UTC).replace(hour=0, minute=0, second=0, microsecond=0)


async def is_at_daily_cap(
    session: AsyncSession,
    settings: Settings,
    *,
    telegram_user_id: int,
    kind: MediaKind,
    now: datetime,
) -> bool:
    """True when this account has already started today's cap of paid ``kind`` requests (§7.6).

    Counted from the database, not a Redis counter: the Payme settlement that makes a job
    paid runs in a process with no Redis, and a counter a restart can clear is not a cap.
    The row being quoted or pressed is not paid yet, so it is never counted against itself.
    """
    paid = await count_paid_since(
        session, telegram_user_id=telegram_user_id, kind=kind, since=utc_day_start(now)
    )
    return paid >= daily_cap(settings, kind)


async def _enqueue(queue: MediaQueue, name: str, *args: Any, job_id: str) -> bool:
    try:
        await queue.enqueue_job(name, *args, _job_id=job_id)
    except Exception as exc:
        _LOG.warning(
            "a media stage could not be enqueued; the sweep will re-drive it",
            extra={"job": name, "arq_job_id": job_id, "failure": repr(exc)},
        )
        return False
    return True


async def enqueue_screen(queue: MediaQueue, job_id: UUID, *, n: int = 0) -> bool:
    """``media_screen`` for a row just frozen (``n=0``) or a busy tray's 🔁 (``n>0``)."""
    return await _enqueue(queue, MEDIA_SCREEN_JOB, str(job_id), n, job_id=screen_job_id(job_id, n))


async def enqueue_prescreen(queue: MediaQueue, job_id: UUID, *, n: int = 0) -> bool:
    """``media_prescreen`` for a video ``drafting`` row (§2.4.1), or a busy tray's 🔁."""
    return await _enqueue(
        queue, MEDIA_PRESCREEN_JOB, str(job_id), n, job_id=prescreen_job_id(job_id, n)
    )


async def enqueue_script(queue: MediaQueue, job_id: UUID, *, n: int) -> bool:
    """``media_script`` for the ``n``-th line of a ``drafting`` row (§2.4.2)."""
    return await _enqueue(queue, MEDIA_SCRIPT_JOB, str(job_id), n, job_id=script_job_id(job_id, n))


async def enqueue_start(queue: MediaQueue, job_id: UUID, *, n: int = 0) -> bool:
    return await _enqueue(queue, MEDIA_START_JOB, str(job_id), n, job_id=start_job_id(job_id, n))


async def start_free_beta(
    sessions: async_sessionmaker[AsyncSession],
    queue: MediaQueue,
    settings: Settings,
    *,
    job_id: UUID,
    telegram_user_id: int,
    is_paused: bool,
    now: datetime,
) -> BetaStart:
    """🎁 on a quote: ``quoted → paid`` with ``paid_via='beta'``, a zero receipt, then start.

    Only off a live-paid rail and only for the allowlist, re-evaluated now (§2.5). The receipt
    is ``media_purchases(provider='beta', amount 0)`` so the finance series can count beta
    renders without ever mistaking one for revenue; a beta job's failure mints no credit
    (``db.media.grant_refund`` refuses it). ``mark_paid`` resets the uploads' backstop clock
    to the deadline in the same transaction (§3.2.2).
    """
    async with sessions.begin() as session:
        job = await load_job(session, job_id)
        if (
            job is None
            or job.telegram_user_id != telegram_user_id
            or job.state is not MediaJobState.QUOTED
        ):
            return BetaStart.STALE
        entitled = (
            not is_live_paid(settings)
            and is_beta_member(settings, telegram_user_id)
            and media_offered(settings, job.sku, telegram_user_id, is_paused=is_paused)
        )
        if not entitled:
            _LOG.info(
                "a beta press was refused at press time",
                extra={"media_job_id": str(job_id), "sku": job.sku.value},
            )
            return BetaStart.NOT_ENTITLED
        if await is_at_daily_cap(
            session, settings, telegram_user_id=telegram_user_id, kind=job.kind, now=now
        ):
            return BetaStart.AT_DAILY_CAP
        paid = await mark_paid(
            session,
            job_id,
            paid_via=MediaPaidVia.BETA,
            now=now,
            deadline=sku_deadline(settings, job.sku),
            expected=(MediaJobState.QUOTED,),
        )
        if not paid:
            return BetaStart.STALE
        await record_purchase(
            session,
            telegram_user_id=telegram_user_id,
            job_id=job_id,
            sku=job.sku,
            amount_minor=0,
            currency=job.currency,
            provider=MediaPurchaseProvider.BETA,
            reference="beta",
            idempotency_key=f"media:{job_id}:beta",
            now=now,
        )
    await enqueue_start(queue, job_id)
    return BetaStart.STARTED
