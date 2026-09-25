"""``media_purchases`` — a media SKU's receipt from the Payme rail (IMAGE_VIDEO_SPEC §7.7).

The third receipts table the billing dossier reads, beside :mod:`bayram.db.admin.topup_purchases`
and :mod:`bayram.db.admin.plan_purchases`, and read the same way: one module per table, the
ROUTER joins. A media sale grants no song credit and has no plan counters, so both halves of
:class:`~bayram.db.admin.views.PaymentReceipt`'s product-specific fields are ``None`` here and
:data:`MEDIA_RECEIPT_SOURCE` says why.

**Media revenue is read from the receipts, never from a price mirror** (§7.7, D19): no
``BAYRAM_ADMIN_*`` variable repeats a media price, because the amount a sale was charged at is
on its row. The finance readers below group by ``(sku, currency, provider)`` exactly as the
top-up readers group by ``(product, currency, provider)``, so the three sources concatenate on
one vocabulary. ``provider`` is never collapsed: a ``beta`` or ``credit`` row is a zero-amount
sale — volume, not revenue — and it stays visibly so rather than diluting the Payme figure.
No ``telegram_user_id`` leaves this module.
"""

from __future__ import annotations

from typing import Any, Final

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql import Select

from bayram.db.admin.sql import (
    SeriesGrain,
    TimeWindow,
    apply_window,
    bucket_expression,
    bucket_started_at,
)
from bayram.db.admin.views import PaymentReceipt, RevenueBucket, RevenueSource, RevenueTotal
from bayram.db.models.media_purchase import MediaPurchaseRow

__all__ = [
    "MEDIA_RECEIPT_SOURCE",
    "receipt_for_key",
    "media_bookings_per_bucket",
    "media_revenue_totals",
]

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


_GROUPING: Final = (MediaPurchaseRow.sku, MediaPurchaseRow.currency, MediaPurchaseRow.provider)


async def media_bookings_per_bucket(
    session: AsyncSession,
    *,
    window: TimeWindow | None = None,
    grain: SeriesGrain = SeriesGrain.DAY,
) -> tuple[RevenueBucket, ...]:
    """Media sales per bucket, keyed by ``(sku, currency, provider)``. Oldest first.

    A bucket with no sale is ABSENT, not zero. INDEX: ``ix_media_purchases_created_at``.
    """
    bucket = bucket_expression(grain, MediaPurchaseRow.created_at)
    statement: Select[Any] = sa.select(
        bucket.label("bucket"),
        *_GROUPING,
        sa.func.count().label("sales"),
        sa.func.sum(MediaPurchaseRow.amount_minor).label("amount_minor"),
    )
    statement = apply_window(statement, MediaPurchaseRow.created_at, window)
    rows = (
        await session.execute(statement.group_by(bucket, *_GROUPING).order_by(bucket, *_GROUPING))
    ).all()
    return tuple(
        RevenueBucket(
            bucket=str(row.bucket),
            started_at=bucket_started_at(grain, str(row.bucket)),
            source=RevenueSource.MEDIA,
            product=row.sku.value,
            currency=row.currency,
            provider=row.provider.value,
            sales=int(row.sales),
            amount_minor=int(row.amount_minor),
        )
        for row in rows
    )


async def media_revenue_totals(
    session: AsyncSession, *, window: TimeWindow | None = None
) -> tuple[RevenueTotal, ...]:
    """The window's media sales, one row per ``(sku, currency, provider)``.

    INDEX: ``ix_media_purchases_created_at``.
    """
    amount = sa.func.sum(MediaPurchaseRow.amount_minor).label("amount_minor")
    statement: Select[Any] = sa.select(*_GROUPING, sa.func.count().label("sales"), amount)
    statement = apply_window(statement, MediaPurchaseRow.created_at, window)
    rows = (
        await session.execute(statement.group_by(*_GROUPING).order_by(amount.desc(), *_GROUPING))
    ).all()
    return tuple(
        RevenueTotal(
            source=RevenueSource.MEDIA,
            product=row.sku.value,
            currency=row.currency,
            provider=row.provider.value,
            sales=int(row.sales),
            amount_minor=int(row.amount_minor),
        )
        for row in rows
    )
