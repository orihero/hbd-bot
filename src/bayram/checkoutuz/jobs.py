"""The worker's two checkout.uz jobs: reconcile one order, and poll every open one.

**The poll is the source of truth; the webhook only makes it sooner** (``DECISIONS.md D28``).
checkout.uz's webhook is unsigned and never retried, and the gateway that receives it may not
even be running, so a payment must settle with no webhook at all. :func:`run_checkoutuz_poll`
is the cron that guarantees it; :func:`reconcile_checkoutuz_order` is the same settlement for one
order, enqueued by the gateway's :class:`~bayram.checkoutuz.app.CheckoutUzWebhookGate`.

**Both run whenever the API key is present, whatever the sale switches say.** The env flag, the
owner's per-rail switch and the global pause all govern NEW sales only; a link already handed
to a customer is money in flight, and turning the rail off must never strand it. So neither
job reads ``checkoutuz_enabled`` or the Redis switch — only "is there a key to ask with?".

The poll has two arms, counted separately:

* **poll** — pending links that are live, or lapsed by less than
  :data:`~bayram.checkoutuz.ports.POLL_GRACE_S`: ask, and settle what is paid.
* **final check** — pending links lapsed by the grace or more: ask ONE last time, settle if
  paid, otherwise close the link as ``expired``. The INTENT is never touched here; its own
  twelve-hour clock belongs to the Payme sweep, which expires intents of every rail. An order
  checkout.uz cannot answer for is asked again on later runs (each failed attempt is stamped,
  so the batch rotates past it), but only until
  :data:`~bayram.checkoutuz.ports.FINAL_CHECK_GIVE_UP_S` after the link's end; then it is
  closed ``expired`` with an ERROR ``checkoutuz.final_check_unresolved`` for a human.

Each job builds its own :class:`~bayram.checkoutuz.client.CheckoutUzClient` from the worker's
settings and closes it in ``finally``. Orders are settled one after another, never
concurrently: a batch is at most ``checkoutuz_poll_batch`` calls, and fanning them out would
only make checkout.uz's rate limit our problem.

ARQ dispatches by NAME, and the gateway — another process — enqueues
:data:`CHECKOUTUZ_RECONCILE_JOB_NAME` by that string; ``bayram.runtime.jobs`` registers both
functions under these names.
"""

from __future__ import annotations

import time
from collections import Counter
from collections.abc import Mapping
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any, Final, Protocol, cast

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from bayram.checkoutuz.client import CheckoutUzApi, CheckoutUzClient
from bayram.checkoutuz.ports import FINAL_CHECK_GIVE_UP_S, POLL_GRACE_S
from bayram.checkoutuz.settle import (
    Notifier,
    SettleOutcome,
    SettleStatus,
    settle_checkoutuz_order,
)
from bayram.db.base import utc_now
from bayram.db.checkoutuz_sql import final_check_payments, mark_payment, pollable_payments
from bayram.db.enums import CheckoutUzPaymentState
from bayram.errors import PipelineError
from bayram.logging import get_logger
from bayram.payme.container import QueuedNotifier

if TYPE_CHECKING:
    from bayram.config import Settings

__all__ = [
    "CHECKOUTUZ_POLL_JOB_NAME",
    "CHECKOUTUZ_RECONCILE_JOB_NAME",
    "reconcile_checkoutuz_order",
    "reconcile_job_id",
    "run_checkoutuz_poll",
]

_LOG = get_logger(__name__)

#: The ARQ function names. The reconcile name crosses a process boundary (gateway -> worker).
CHECKOUTUZ_RECONCILE_JOB_NAME: Final[str] = "reconcile_checkoutuz_order"
CHECKOUTUZ_POLL_JOB_NAME: Final[str] = "run_checkoutuz_poll"

#: Worker context keys, restated rather than imported from ``bayram.runtime`` — importing the
#: runtime package from here would be a cycle, since ``bayram.runtime.jobs`` registers these
#: functions. ``bayram.runtime.payme_jobs`` restates the same strings for the same reason.
_CONTAINER_CTX_KEY: Final[str] = "container"
_REDIS_CTX_KEY: Final[str] = "redis"

_SKIPPED_NO_KEY: Final[dict[str, Any]] = {"skipped": "no key"}


def reconcile_job_id(order_id: int) -> str:
    """The deterministic job id for one order's reconcile, so a burst of webhooks for one order
    becomes one job.

    ARQ refuses an id while it is queued OR while a RESULT is kept under it, which is why the
    worker registers this function with ``keep_result=0`` (``bayram.runtime.jobs``): otherwise
    a finished NOT_PAID reconcile — an early webhook, or a forged one — would block the real
    webhook's enqueue for the whole result TTL."""
    return f"checkoutuz_reconcile:{order_id}"


class _WorkerContainer(Protocol):
    """The two things these jobs take off ``bayram.runtime.container.AppContainer``."""

    @property
    def settings(self) -> Settings: ...

    def require_session_factory(self) -> async_sessionmaker[AsyncSession]: ...


async def reconcile_checkoutuz_order(
    ctx: Mapping[str, Any],
    order_id: int,
    *,
    client: CheckoutUzApi | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Settle one order the webhook told us about. Returns a JSON-safe summary.

    ``client`` and ``now`` are injectable for tests; ARQ never passes them. A failure to settle
    is not raised: the poll will reach the same order within minutes, so a retry here would only
    duplicate it.
    """
    container = _require_container(ctx)
    settings = container.settings
    if not settings.checkoutuz_api_key.strip():
        _LOG.warning(
            "a checkout.uz reconcile was skipped because no API key is configured",
            extra={"event": "checkoutuz.reconcile_skipped", "order_id": order_id},
        )
        return dict(_SKIPPED_NO_KEY)
    owned, api = _client_for(settings, client)
    try:
        outcome = await settle_checkoutuz_order(
            container.require_session_factory(),
            api,
            order_id=int(order_id),
            notifier=_notifier(ctx),
            now=now or utc_now(),
        )
    finally:
        if owned is not None:
            await owned.aclose()
    return {"order_id": outcome.order_id, "status": outcome.status.value}


async def run_checkoutuz_poll(
    ctx: Mapping[str, Any],
    *,
    now: datetime | None = None,
    client: CheckoutUzApi | None = None,
) -> dict[str, Any]:
    """The cron: the poll arm, then the final-check arm. ``max_tries=1``; the next run retries.

    Each arm reads its batch in its own short session and then settles row by row, so no
    database connection is held across a checkout.uz call.
    """
    container = _require_container(ctx)
    settings = container.settings
    if not settings.checkoutuz_api_key.strip():
        return dict(_SKIPPED_NO_KEY)
    sessions = container.require_session_factory()
    at = now or utc_now()
    limit = settings.checkoutuz_poll_batch
    notifier = _notifier(ctx)
    started = time.monotonic()
    owned, api = _client_for(settings, client)
    faults = 0
    try:
        poll_counts, poll_faults = await _poll_arm(
            sessions, api, notifier=notifier, now=at, limit=limit
        )
        final_counts, expired, unresolved, final_faults = await _final_check_arm(
            sessions, api, notifier=notifier, now=at, limit=limit
        )
        faults = poll_faults + final_faults
    finally:
        if owned is not None:
            await owned.aclose()

    summary: dict[str, Any] = {
        "polled": sum(poll_counts.values()),
        "settled": poll_counts[SettleStatus.SETTLED] + final_counts[SettleStatus.SETTLED],
        "not_paid": poll_counts[SettleStatus.NOT_PAID],
        "retry_later": poll_counts[SettleStatus.RETRY_LATER]
        + final_counts[SettleStatus.RETRY_LATER],
        "orphaned": poll_counts[SettleStatus.ORPHAN] + final_counts[SettleStatus.ORPHAN],
        "mismatched": poll_counts[SettleStatus.MISMATCH] + final_counts[SettleStatus.MISMATCH],
        "final_checked": sum(final_counts.values()),
        "expired": expired,
        "unresolved": unresolved,
        "faults": faults,
        "duration_ms": int((time.monotonic() - started) * 1000),
    }
    _LOG.info("checkout.uz poll finished", extra={"event": "checkoutuz.poll_finished", **summary})
    return summary


# ---------------------------------------------------------------------------
# Arms
# ---------------------------------------------------------------------------
async def _poll_arm(
    sessions: async_sessionmaker[AsyncSession],
    api: CheckoutUzApi,
    *,
    notifier: Notifier | None,
    now: datetime,
    limit: int,
) -> tuple[Counter[SettleStatus], int]:
    counts: Counter[SettleStatus] = Counter()
    try:
        async with sessions() as session:
            rows = await pollable_payments(session, now=now, grace_s=POLL_GRACE_S, limit=limit)
            order_ids = [row.order_id for row in rows]
    except Exception as exc:
        _LOG.error(
            "the checkout.uz poll batch could not be read",
            extra={"event": "checkoutuz.poll_read_failed", "arm": "poll"},
            exc_info=exc,
        )
        return counts, 1
    for order_id in order_ids:
        outcome = await settle_checkoutuz_order(
            sessions, api, order_id=order_id, notifier=notifier, now=now
        )
        counts[outcome.status] += 1
    return counts, 0


async def _final_check_arm(
    sessions: async_sessionmaker[AsyncSession],
    api: CheckoutUzApi,
    *,
    notifier: Notifier | None,
    now: datetime,
    limit: int,
) -> tuple[Counter[SettleStatus], int, int, int]:
    """``(counts, expired, unresolved, faults)``. ``unresolved`` rows are also in ``expired``."""
    counts: Counter[SettleStatus] = Counter()
    expired = 0
    unresolved = 0
    faults = 0
    give_up_before = now - timedelta(seconds=FINAL_CHECK_GIVE_UP_S)
    try:
        async with sessions() as session:
            rows = await final_check_payments(session, now=now, grace_s=POLL_GRACE_S, limit=limit)
            batch = [(row.order_id, row.link_valid_until) for row in rows]
    except Exception as exc:
        _LOG.error(
            "the checkout.uz final-check batch could not be read",
            extra={"event": "checkoutuz.poll_read_failed", "arm": "final_check"},
            exc_info=exc,
        )
        return counts, 0, 0, 1
    for order_id, link_valid_until in batch:
        outcome = await settle_checkoutuz_order(
            sessions, api, order_id=order_id, notifier=notifier, now=now
        )
        counts[outcome.status] += 1
        if outcome.status is SettleStatus.NOT_PAID:
            closed, fault = await _expire(sessions, outcome, now=now)
        elif outcome.status is SettleStatus.RETRY_LATER and link_valid_until <= give_up_before:
            # Nobody could get an answer about this order for a day past its link's end. Asking
            # forever would keep it in every batch; closing it silently could hide a paid order.
            # So it is closed, and the ERROR names it for a manual check against checkout.uz.
            closed, fault = await _expire(sessions, outcome, now=now, unresolved=True)
            unresolved += closed
        else:
            # Settled, orphaned and mismatched rows have already left ``pending``; a
            # RETRY_LATER row inside the give-up window stays pending (its attempt was stamped,
            # so it rotates to the back) and the next run asks again.
            continue
        expired += closed
        faults += fault
    return counts, expired, unresolved, faults


async def _expire(
    sessions: async_sessionmaker[AsyncSession],
    outcome: SettleOutcome,
    *,
    now: datetime,
    unresolved: bool = False,
) -> tuple[int, int]:
    """Close one lapsed, unpaid link. ``(closed, fault)``; a lost race is neither."""
    try:
        async with sessions.begin() as session:
            closed = await mark_payment(
                session,
                outcome.order_id,
                frm=CheckoutUzPaymentState.PENDING,
                to=CheckoutUzPaymentState.EXPIRED,
                now=now,
            )
    except Exception as exc:
        _LOG.error(
            "a lapsed checkout.uz link could not be closed",
            extra={"event": "checkoutuz.expire_failed", "order_id": outcome.order_id},
            exc_info=exc,
        )
        return 0, 1
    if closed and unresolved:
        _LOG.error(
            "checkout.uz never answered for a lapsed link; closed as expired UNVERIFIED — "
            "check this order in the checkout.uz dashboard and settle or refund by hand",
            extra={
                "event": "checkoutuz.final_check_unresolved",
                "order_id": outcome.order_id,
                "public_ref": outcome.public_ref,
                "retryable": outcome.retryable,
            },
        )
    elif closed:
        _LOG.info(
            "a lapsed, unpaid checkout.uz link was closed",
            extra={
                "event": "checkoutuz.link_expired",
                "order_id": outcome.order_id,
                "public_ref": outcome.public_ref,
            },
        )
    return int(closed), 0


# ---------------------------------------------------------------------------
# Plumbing
# ---------------------------------------------------------------------------
def _require_container(ctx: Mapping[str, Any]) -> _WorkerContainer:
    container = ctx.get(_CONTAINER_CTX_KEY)
    if not hasattr(container, "settings") or not hasattr(container, "require_session_factory"):
        raise PipelineError(
            "worker context is missing a usable 'container'",
            context={"key": _CONTAINER_CTX_KEY, "found": type(container).__name__},
        )
    return cast("_WorkerContainer", container)


def _client_for(
    settings: Settings, injected: CheckoutUzApi | None
) -> tuple[CheckoutUzClient | None, CheckoutUzApi]:
    """``(client to close, client to use)``. An injected client is its owner's to close."""
    if injected is not None:
        return None, injected
    built = CheckoutUzClient(
        api_key=settings.checkoutuz_api_key, base_url=settings.checkoutuz_base_url
    )
    return built, built


def _notifier(ctx: Mapping[str, Any]) -> Notifier | None:
    """The queued "your payment landed" enqueue, or ``None`` with no queue handle.

    ``None`` is survivable by design: the Payme sweep's notification arm re-enqueues every
    settled, unannounced intent, whatever its rail.
    """
    redis = ctx.get(_REDIS_CTX_KEY)
    if redis is None or not hasattr(redis, "enqueue_job"):
        return None
    return QueuedNotifier(redis)
