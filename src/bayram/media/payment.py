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
from bayram.config import Settings
from bayram.contracts import Err, Result, err, ok
from bayram.db.base import utc_now
from bayram.db.enums import MediaBackend, MediaJobState, MediaSku, PaymentIntentState
from bayram.db.guard import run_guarded
from bayram.db.media import load_job, transition
from bayram.db.payme_sql import intent_by_key
from bayram.errors import CheckoutError, StorageError
from bayram.logging import get_logger
from bayram.media.desk import JobView
from bayram.media.offering import effective_backend, media_offered
from bayram.media.overrides import MediaSwitchStore, read_overrides
from bayram.media.service import is_at_daily_cap

__all__ = [
    "MEDIA_BUSY_KEY",
    "MEDIA_DAILY_CAP_KEY",
    "MEDIA_STALE_KEY",
    "MediaPayLink",
    "SqlMediaCharge",
    "media_idempotency_key",
]

_LOG = get_logger(__name__)

#: The toast a 💳 press answers when the row is no longer a quote or an open pay link.
MEDIA_STALE_KEY: Final[str] = "media.stale"
#: The alert a 💳 press answers past the account's daily cap (§7.6).
MEDIA_DAILY_CAP_KEY: Final[str] = "media.daily_cap"
#: The alert a 💳 press answers while the SKU is paused or its local GPU reserved (§4.5, O11).
MEDIA_BUSY_KEY: Final[str] = "media.busy"

#: The intent states a link may still be handed out for: nobody has paid, or a rail-side
#: transaction is paying it now. ``expired``/``cancelled`` are terminal — their link is dead.
_LIVE_INTENT: Final[tuple[PaymentIntentState, ...]] = (
    PaymentIntentState.PENDING,
    PaymentIntentState.AWAITING,
)

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

    __slots__ = ("_checkout", "_clock", "_sessions", "_settings", "_switches")

    def __init__(
        self,
        sessions: async_sessionmaker[AsyncSession],
        *,
        checkout: CheckoutProvider,
        settings: Settings,
        switches: MediaSwitchStore | None = None,
        clock: Callable[[], datetime] = utc_now,
    ) -> None:
        self._sessions = sessions
        self._checkout = checkout
        self._settings = settings
        # The operator's Redis switches (§4.5). ``None`` (no Redis wired) reads "not paused,
        # not reserved", as ``bot.media_offer.is_sku_paused`` does.
        self._switches = switches
        self._clock = clock

    async def _offer_refusal(
        self, job_id: UUID, sku: MediaSku, telegram_user_id: int
    ) -> CheckoutError | None:
        """§2.5: a drawn 💳 is never proof the SKU is still sold — re-read it at press time.

        Paused, or the local GPU inside the operator's reserved window (O11, D22) → ``busy``:
        the quote comes back once the switch is lifted. No longer offered to this account at
        all (flag off, beta list edited) → ``stale``. Both refuse before any intent exists.
        """
        is_paused = False
        is_reserved = False
        if self._switches is not None:
            overrides = await read_overrides(self._switches, sku)
            is_paused = overrides.is_paused
            backend = effective_backend(self._settings, sku, overrides.backend)
            is_reserved = backend is MediaBackend.LOCAL and overrides.is_gpu_reserved(self._clock())
        if not media_offered(self._settings, sku, telegram_user_id, is_paused=False):
            return _stale(job_id)
        if is_paused or is_reserved:
            return CheckoutError(
                "the media SKU is paused or its GPU is reserved",
                user_message_key=MEDIA_BUSY_KEY,
                context={
                    "media_job_id": str(job_id),
                    "sku": sku.value,
                    "is_paused": is_paused,
                    "is_gpu_reserved": is_reserved,
                },
            )
        return None

    async def __call__(self, job: JobView) -> Result[MediaPayLink]:
        async def read() -> tuple[MediaSku, int, str, MediaJobState, bool] | None:
            async with self._sessions() as session:
                row = await load_job(session, job.id)
                if row is None or row.telegram_user_id != job.telegram_user_id:
                    return None
                # §7.6, re-read at press time: a link is never opened past today's cap.
                at_cap = await is_at_daily_cap(
                    session,
                    self._settings,
                    telegram_user_id=row.telegram_user_id,
                    kind=row.kind,
                    now=self._clock(),
                )
            return row.sku, row.price_minor, row.currency, row.state, at_cap

        found = await run_guarded("media.pay.read", read, media_job_id=str(job.id))
        if isinstance(found, Err):
            return found
        if found.value is None or found.value[3] not in _PAYABLE:
            return err(_stale(job.id))
        sku, price_minor, currency, _, at_cap = found.value
        refusal = await self._offer_refusal(job.id, sku, job.telegram_user_id)
        if refusal is not None:
            return err(refusal)
        if at_cap:
            return err(
                CheckoutError(
                    "the account used today's paid requests of this kind",
                    user_message_key=MEDIA_DAILY_CAP_KEY,
                    context={"media_job_id": str(job.id)},
                )
            )
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
                if intent.state not in _LIVE_INTENT:
                    # The key is fixed per job, so a 💳 after the intent expired finds that
                    # dead intent again: its link can never take money. Refused, not handed
                    # out; ✖️ / ``/cancel`` withdraw the row (§2.6).
                    return False
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
