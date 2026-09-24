"""``/forget`` against the media tables (IMAGE_VIDEO_SPEC §9.3, §3.2.4, O16).

The media arm of the data-subject request, beside :mod:`bayram.db.credit_erasure` and on its
two principles: **a balance is deleted, a receipt is anonymised**, and the object bytes go
AFTER the rows' commit, never inside it.

What one call does, in the caller's transaction:

1. **Pre-pay requests are cancelled** (drafting … awaiting_payment): nothing was paid, so
   there is nothing to finish.
2. **Paid, unfinished requests are marked** ``forget_requested_at``: the worker does not
   deliver them and purges them at their next stage boundary. Their state is not forced to
   ``failed`` here, because a render may still be running and the stage chain's own guarded
   path is what releases the GPU lock and the queue slot.
3. **Every upload and every output is deleted, rows and objects** — except ``legal_hold``
   rows (§6.7), which are kept to their own ≤72-hour clock whatever the account asks.
4. **The words are nulled**: ``prompt``, ``narration_text``, ``voice_transcript``, with
   ``text_purged_at`` as the proof. The job row itself stays until its own clock — a paid
   one is the record of a sale — and still carries ``telegram_user_id``, as §3.2.2 specifies.
5. **``media_credit_balances`` is deleted** (``tables_erased_on_request``).
6. **``media_purchases`` and ``media_credit_ledger`` lose their account id** and keep the rest:
   a receipt that erased itself on request would make ``/forget`` mean "refund me".

Objects are unlinked by :class:`SqlMediaEraser` after commit; a storage failure is logged with
the key for a manual delete and does not fail the request, :class:`bayram.db.user_profiles.
SqlUserProfiles`' rule: the rows ARE gone, and a retry could only repeat the same unlink.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from bayram.contracts import Result, Storage, is_err
from bayram.db.base import utc_now
from bayram.db.credit_sql import rowcount_of
from bayram.db.enums import MEDIA_IN_FLIGHT_STATES
from bayram.db.guard import run_guarded
from bayram.db.media import cancel_prepay_jobs
from bayram.db.models.media_credit import MediaCreditBalanceRow, MediaCreditLedgerRow
from bayram.db.models.media_input import MediaInputRow, MediaOutputRow
from bayram.db.models.media_job import MediaJobRow
from bayram.db.models.media_purchase import MediaPurchaseRow
from bayram.db.retention import RetentionClass
from bayram.logging import get_logger

__all__ = ["MediaErasure", "SqlMediaEraser", "forget_media"]

_log = get_logger(__name__)


@dataclass(frozen=True, slots=True)
class MediaErasure:
    """What one ``/forget`` did to the media tables. Diagnostic counts, and the keys to unlink.

    Bulk ``rowcount`` is driver-dependent (``credit_sql.rowcount_of``), so the numbers go in a
    log line and nothing branches on them.
    """

    jobs_cancelled: int = 0
    jobs_marked: int = 0
    inputs_deleted: int = 0
    outputs_deleted: int = 0
    texts_purged: int = 0
    balances_deleted: int = 0
    purchases_anonymised: int = 0
    ledger_anonymised: int = 0
    #: Object keys whose rows are gone. The caller deletes them after its commit.
    storage_keys: tuple[str, ...] = ()


async def forget_media(
    session: AsyncSession, *, telegram_user_id: int, now: datetime
) -> MediaErasure:
    """Erase what the media tables hold about one Telegram account. Idempotent.

    Commits nothing. Child rows are deleted by their own statements rather than trusted to
    ``ON DELETE CASCADE``, which is inert on the SQLite unit suite (no ``PRAGMA
    foreign_keys``) — the :func:`bayram.db.credit_erasure.forget_account` rule.
    """
    cancelled = await cancel_prepay_jobs(session, telegram_user_id=telegram_user_id, now=now)
    marked = await session.execute(
        sa.update(MediaJobRow)
        .where(
            MediaJobRow.telegram_user_id == telegram_user_id,
            MediaJobRow.state.in_(tuple(MEDIA_IN_FLIGHT_STATES)),
            MediaJobRow.forget_requested_at.is_(None),
        )
        .values(forget_requested_at=now, updated_at=now)
    )
    owned = sa.select(MediaJobRow.id).where(MediaJobRow.telegram_user_id == telegram_user_id)

    keys: list[str] = []
    inputs = (
        await session.execute(
            sa.select(MediaInputRow.id, MediaInputRow.storage_key).where(
                MediaInputRow.job_id.in_(owned),
                MediaInputRow.retention_class != RetentionClass.LEGAL_HOLD,
            )
        )
    ).all()
    if inputs:
        keys.extend(key for _, key in inputs if key is not None)
        await session.execute(
            sa.delete(MediaInputRow).where(MediaInputRow.id.in_([row_id for row_id, _ in inputs]))
        )
    outputs = (
        await session.execute(
            sa.select(MediaOutputRow.id, MediaOutputRow.storage_key).where(
                MediaOutputRow.job_id.in_(owned),
                MediaOutputRow.retention_class != RetentionClass.LEGAL_HOLD,
            )
        )
    ).all()
    if outputs:
        keys.extend(key for _, key in outputs)
        await session.execute(
            sa.delete(MediaOutputRow).where(
                MediaOutputRow.id.in_([row_id for row_id, _ in outputs])
            )
        )

    texts = await session.execute(
        sa.update(MediaJobRow)
        .where(
            MediaJobRow.telegram_user_id == telegram_user_id,
            sa.or_(
                MediaJobRow.prompt.is_not(None),
                MediaJobRow.narration_text.is_not(None),
                MediaJobRow.voice_transcript.is_not(None),
            ),
        )
        .values(prompt=None, narration_text=None, voice_transcript=None, text_purged_at=now)
    )
    purchases = await session.execute(
        sa.update(MediaPurchaseRow)
        .where(MediaPurchaseRow.telegram_user_id == telegram_user_id)
        .values(telegram_user_id=None)
    )
    ledger = await session.execute(
        sa.update(MediaCreditLedgerRow)
        .where(MediaCreditLedgerRow.telegram_user_id == telegram_user_id)
        .values(telegram_user_id=None)
    )
    balances = await session.execute(
        sa.delete(MediaCreditBalanceRow).where(
            MediaCreditBalanceRow.telegram_user_id == telegram_user_id
        )
    )
    return MediaErasure(
        jobs_cancelled=len(cancelled),
        jobs_marked=rowcount_of(marked),
        inputs_deleted=len(inputs),
        outputs_deleted=len(outputs),
        texts_purged=rowcount_of(texts),
        balances_deleted=rowcount_of(balances),
        purchases_anonymised=rowcount_of(purchases),
        ledger_anonymised=rowcount_of(ledger),
        storage_keys=tuple(keys),
    )


class SqlMediaEraser:
    """:class:`bayram.bot.ports.MediaEraser` over the media tables and the object store.

    One transaction for the rows, then the objects — the order is the safety argument (see
    the module docstring). Never raises.
    """

    __slots__ = ("_clock", "_sessions", "_storage")

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        *,
        storage: Storage,
        clock: Callable[[], datetime] = utc_now,
    ) -> None:
        self._sessions = session_factory
        self._storage = storage
        self._clock = clock

    async def forget_media(self, telegram_user_id: int) -> Result[int]:
        """Honour ``/forget`` for media. The number of objects handed for deletion."""
        return await run_guarded(
            "media.forget",
            lambda: self._forget(telegram_user_id),
            telegram_user_id=telegram_user_id,
        )

    async def _forget(self, telegram_user_id: int) -> int:
        async with self._sessions.begin() as session:
            erased = await forget_media(
                session, telegram_user_id=telegram_user_id, now=self._clock()
            )
        for key in erased.storage_keys:
            removed = await self._storage.delete(key)
            if is_err(removed):
                _log.warning(
                    "media object survived an erasure; delete it by hand",
                    extra={"telegram_user_id": telegram_user_id, "key": key},
                    exc_info=removed.error,
                )
        _log.info(
            "media erased on request",
            extra={
                "telegram_user_id": telegram_user_id,
                "jobs_cancelled": erased.jobs_cancelled,
                "jobs_marked": erased.jobs_marked,
                "inputs_deleted": erased.inputs_deleted,
                "outputs_deleted": erased.outputs_deleted,
                "texts_purged": erased.texts_purged,
                "balances_deleted": erased.balances_deleted,
                "purchases_anonymised": erased.purchases_anonymised,
                "ledger_anonymised": erased.ledger_anonymised,
                "storage_keys": len(erased.storage_keys),
            },
        )
        return len(erased.storage_keys)
