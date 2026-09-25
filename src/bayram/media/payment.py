"""💳 on a media quote: ``CheckoutProvider.charge``, then ``quoted → awaiting_payment``.

IMAGE_VIDEO_SPEC §7.2 step 2. The press goes through ``charge`` — never straight to
``open_intent`` — so the operator pause switch and the link builder a direct call would skip
both apply. The request carries the job as ``resume_media_job_id``, the job's snapshotted
price, and the key ``{sku}:{tg}:{job_id}``: one job, one intent, one link however many times
💳 is pressed, and the settlement's media arm moves exactly that row.

**Order: the intent first, then the row.** The link the customer receives names an intent that
already exists, and ``CheckPerformTransaction``/``CreateTransaction`` refuse a media intent
whose job is not ``awaiting_payment`` — so the row is moved before the link is handed out, and
a link to a job that was cancelled meanwhile is refused on the payment page rather than taken.

**An inline "paid" answer is refused, not trusted.** A media SKU's receipt and state move are
written by the Payme settlement in its money commit (§7.2 step 3); a rail that reported the
purchase paid on the spot (the stub) has moved no money and written no receipt, so nothing is
started. ``offering.guarded_media_charge`` already keeps this callable off every rail that is
not live-paid; this is the second lock on the same door.

The bot calls this only through that guard (``handlers.media.jobs.handle_pay``).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Final
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from bayram.checkout import CheckoutProvider, Product, PurchaseRequest
from bayram.contracts import Err, Result, err, ok
from bayram.db.base import utc_now
from bayram.db.enums import MediaJobState, MediaSku
from bayram.db.guard import run_guarded
from bayram.db.media import load_job, transition
from bayram.db.payme_sql import intent_by_key
from bayram.errors import CheckoutError, StorageError
from bayram.logging import get_logger
from bayram.media.desk import JobView

__all__ = ["MEDIA_STALE_KEY", "MediaPayLink", "SqlMediaCharge", "media_idempotency_key"]

_LOG = get_logger(__name__)

#: The toast a 💳 press answers when the row is no longer a quote or an open pay link.
MEDIA_STALE_KEY: Final[str] = "media.stale"

#: The states 💳 applies to: the quote, and a pay link being re-sent (§2.3.3).
_PAYABLE: Final[tuple[MediaJobState, ...]] = (
    MediaJobState.QUOTED,
    MediaJobState.AWAITING_PAYMENT,
)


def media_idempotency_key(sku: MediaSku, telegram_user_id: int, job_id: UUID) -> str:
    """``{sku}:{tg}:{job_id}`` (§7.2 step 2) — the intent's key and the receipt's."""
    return f"{sku.value}:{telegram_user_id}:{job_id}"


@dataclass(frozen=True, slots=True)
class MediaPayLink:
    """Where to pay, and the amount the link was opened for (the intent's, not today's)."""

    url: str
    amount_minor: int


class SqlMediaCharge:
    """The live-paid half of a media 💳, as ``BotDeps.media_charge`` holds it."""

    __slots__ = ("_checkout", "_clock", "_sessions")

    def __init__(
        self,
        sessions: async_sessionmaker[AsyncSession],
        *,
        checkout: CheckoutProvider,
        clock: Callable[[], datetime] = utc_now,
    ) -> None:
        self._sessions = sessions
        self._checkout = checkout
        self._clock = clock

    async def __call__(self, job: JobView) -> Result[MediaPayLink]:
        async def read() -> tuple[MediaSku, int, str, MediaJobState] | None:
            async with self._sessions() as session:
                row = await load_job(session, job.id)
            if row is None or row.telegram_user_id != job.telegram_user_id:
                return None
            return row.sku, row.price_minor, row.currency, row.state

        found = await run_guarded("media.pay.read", read, media_job_id=str(job.id))
        if isinstance(found, Err):
            return found
        if found.value is None or found.value[3] not in _PAYABLE:
            return err(_stale(job.id))
        sku, price_minor, currency, _ = found.value
        key = media_idempotency_key(sku, job.telegram_user_id, job.id)
        charged = await self._checkout.charge(
            PurchaseRequest(
                telegram_user_id=job.telegram_user_id,
                product=Product(sku.value),
                amount_minor=price_minor,
                currency=currency,
                idempotency_key=key,
                resume_media_job_id=job.id,
            )
        )
        if isinstance(charged, Err):
            return charged
        purchase = charged.value
        if purchase.is_paid or purchase.checkout_url is None:
            # Not a redirect rail's answer. Nothing was settled through Payme, so no receipt
            # exists and the job must not start (§7.2 step 2).
            _LOG.error(
                "a media purchase was answered inline; refused, nothing started",
                extra={
                    "media_job_id": str(job.id),
                    "provider": purchase.provider,
                    "is_paid": purchase.is_paid,
                },
            )
            return err(
                CheckoutError(
                    "a media SKU is only sold down the redirect rail",
                    context={"media_job_id": str(job.id), "provider": purchase.provider},
                )
            )
        url = purchase.checkout_url

        async def record() -> bool:
            async with self._sessions.begin() as session:
                intent = await intent_by_key(session, key)
                if intent is None:
                    raise StorageError(
                        "the media payment intent is missing after it was opened",
                        context={"media_job_id": str(job.id)},
                    )
                return await transition(
                    session,
                    job.id,
                    expected=_PAYABLE,
                    to=MediaJobState.AWAITING_PAYMENT,
                    now=self._clock(),
                    values={"payment_intent_id": intent.id},
                )

        moved = await run_guarded("media.pay.record", record, media_job_id=str(job.id))
        if isinstance(moved, Err):
            return moved
        if not moved.value:
            # Cancelled or abandoned between the read and the move. The intent stays pending
            # and unpayable: Check/Create refuse a media intent whose job is not awaiting
            # payment (§7.2 step 3), so the link is never handed out and never takes money.
            return err(_stale(job.id))
        return ok(MediaPayLink(url=url, amount_minor=purchase.amount_minor))


def _stale(job_id: UUID) -> CheckoutError:
    return CheckoutError(
        "the media request is no longer payable",
        user_message_key=MEDIA_STALE_KEY,
        context={"media_job_id": str(job_id)},
    )
