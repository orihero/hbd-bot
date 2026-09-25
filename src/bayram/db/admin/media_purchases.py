"""``media_purchases`` — a media SKU's receipt from the Payme rail (IMAGE_VIDEO_SPEC §7.7).

The third receipts table the billing dossier reads, beside :mod:`bayram.db.admin.topup_purchases`
and :mod:`bayram.db.admin.plan_purchases`, and read the same way: one module per table, the
ROUTER joins. A media sale grants no song credit and has no plan counters, so both halves of
:class:`~bayram.db.admin.views.PaymentReceipt`'s product-specific fields are ``None`` here and
:data:`MEDIA_RECEIPT_SOURCE` says why.
"""

from __future__ import annotations

from typing import Final

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from bayram.db.admin.views import PaymentReceipt
from bayram.db.models.media_purchase import MediaPurchaseRow

__all__ = ["MEDIA_RECEIPT_SOURCE", "receipt_for_key"]

#: What :attr:`~bayram.db.admin.views.PaymentReceipt.source` says when the sale landed here:
#: the table name, for the reason ``TOPUP_RECEIPT_SOURCE`` gives.
MEDIA_RECEIPT_SOURCE: Final[str] = "media_purchases"


async def receipt_for_key(session: AsyncSession, *, idempotency_key: str) -> PaymentReceipt | None:
    """The media sale written under one payment's key, or ``None`` if none was.

    ``None`` is legitimate for the reason the top-up reader gives (an erased buyer's settlement
    writes no sale). INDEX: the unique ``uq_media_purchases_idempotency_key``.
    """
    row = (
        await session.execute(
            sa.select(
                MediaPurchaseRow.amount_minor,
                MediaPurchaseRow.currency,
                MediaPurchaseRow.provider,
                MediaPurchaseRow.reference,
                MediaPurchaseRow.created_at,
            ).where(MediaPurchaseRow.idempotency_key == idempotency_key)
        )
    ).one_or_none()
    if row is None:
        return None
    return PaymentReceipt(
        source=MEDIA_RECEIPT_SOURCE,
        amount_minor=int(row.amount_minor),
        currency=str(row.currency),
        provider=str(row.provider),
        reference=None if row.reference is None else str(row.reference),
        credits_granted=None,
        songs_included=None,
        songs_used=None,
        plan_ends_at=None,
        created_at=row.created_at,
    )
