"""``topup_purchases`` — single-song sales, and the population sold before we priced them.

The sibling of :mod:`bayram.db.admin.plan_purchases`, deliberately shaped the same way over a
table whose columns are named the same way, so a revenue read is a clean union on one
vocabulary. Everything that module's docstring states holds here without repetition: every
number is computed by the database, currencies are never summed together, ``provider`` is
never collapsed, no ``telegram_user_id`` leaves the module, and ``bounded_total`` is not
used.

**The centre of gravity of this module is** :func:`count_unpriced_topups`.

Until the revision that created this table, ``_fulfil_single`` wrote only a ``credit_ledger``
GRANT under ``reason=TOPUP_PURCHASE``: an idempotency key, a clock, ``delta=+1``, and no
amount, no currency, no provider. **That money is gone and cannot be recovered.** It is not
recoverable by back-pricing at ``Settings.single_song_price_minor`` either, and the
temptation to do so is worth naming explicitly because it looks harmless: that value is read
at QUERY time, not the price that was charged, so every historical figure would move the
next time the price does — LR-63's "retrofitting revenue recognition corrupts every prior
reported period". This codebase already refuses that shape twice in the two places nearest
to here: ``plan_purchases.songs_included`` is stored on the row rather than read from
``starter_plan_songs``, and ``vendor_usage.cost_usd`` stays NULL rather than 0 because a
rate applied after the fact is a fabricated number.

So the backlog is COUNTED and never priced, and it travels beside the money on the wire —
"118 top-ups sold · 113 priced · 5 sold before amounts were recorded" — which is exactly the
``costUsd``/``costedCalls`` pairing applied at population level.

**The two ambiguous states are told apart STRUCTURALLY, not by a null.** "Sold before we
recorded amounts" is a ``credit_ledger`` GRANT with ``reason='topup_purchase'`` and NO
``topup_purchases`` row sharing its ``idempotency_key``. "Sold for zero" is a
``topup_purchases`` row with ``amount_minor = 0`` — a real sale at a real promotional price,
which ``single_song_price_minor``'s ``ge=0`` bound permits. Absence of a row, never a null
inside one, which is why ``amount_minor`` is NOT NULL.

The count is a correlated ``NOT EXISTS`` on the shared key rather than a subtraction of two
windowed counts: the join is exact under any clock skew or partial write, and it probes the
unique ``ix_topup_purchases_idempotency_key`` index-only per candidate row while the outer
window rides ``ix_credit_ledger_created_at``.

**No index is added to ``credit_ledger`` for the ``reason`` predicate.** The window is the
selective clause, and a second index on the hottest write path in the entitlement schema is
too high a price for one dashboard card. Revisit only if a profile shows the filter
dominating; if an all-time window becomes the normal request, cap the route's window rather
than adding the index.

This is also the ONE query in the revenue surface that reads ``credit_ledger``, and it reads
a count and nothing else: no ``telegram_user_id``, no key, no row.
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
from bayram.db.admin.views import (
    PaymentReceipt,
    RevenueBucket,
    RevenueSource,
    RevenueTotal,
    UnpricedTopups,
)
from bayram.db.enums import CreditReason
from bayram.db.models.credit_ledger import CreditLedgerRow
from bayram.db.models.topup_purchase import TopupPurchaseRow

__all__ = [
    "TOPUP_RECEIPT_SOURCE",
    "topup_bookings_per_bucket",
    "topup_revenue_totals",
    "count_unpriced_topups",
    "has_recorded_topup_revenue",
    "receipt_for_key",
]

#: What :attr:`~bayram.db.admin.views.PaymentReceipt.source` says when the sale landed here.
#: The TABLE name and not a product label, because the question the dossier is answering is
#: literally "which table did this sale get written to?" — an operator who has to check a row
#: by hand needs the name they will type into ``psql``, and a friendly synonym would be one
#: more thing to translate at three in the morning.
TOPUP_RECEIPT_SOURCE: Final[str] = "topup_purchases"


async def topup_bookings_per_bucket(
    session: AsyncSession,
    *,
    window: TimeWindow | None = None,
    grain: SeriesGrain = SeriesGrain.DAY,
) -> tuple[RevenueBucket, ...]:
    """Top-ups sold per bucket, keyed by ``(product, currency, provider)``. Oldest first.

    A bucket with no sale is ABSENT, not zero. INDEX: ``ix_topup_purchases_created_at``.
    """
    bucket = bucket_expression(grain, TopupPurchaseRow.created_at)
    grouping = (TopupPurchaseRow.product, TopupPurchaseRow.currency, TopupPurchaseRow.provider)
    statement: Select[Any] = sa.select(
        bucket.label("bucket"),
        *grouping,
        sa.func.count().label("sales"),
        sa.func.sum(TopupPurchaseRow.amount_minor).label("amount_minor"),
    )
    statement = apply_window(statement, TopupPurchaseRow.created_at, window)
    rows = (
        await session.execute(statement.group_by(bucket, *grouping).order_by(bucket, *grouping))
    ).all()
    return tuple(
        RevenueBucket(
            bucket=str(row.bucket),
            started_at=bucket_started_at(grain, str(row.bucket)),
            source=RevenueSource.TOPUP,
            product=row.product.value,
            currency=row.currency,
            provider=row.provider,
            sales=int(row.sales),
            amount_minor=int(row.amount_minor),
        )
        for row in rows
    )


async def topup_revenue_totals(
    session: AsyncSession, *, window: TimeWindow | None = None
) -> tuple[RevenueTotal, ...]:
    """The window's top-up sales, one row per ``(product, currency, provider)``.

    A tuple and never a scalar, for the reasons :mod:`bayram.db.admin.plan_purchases` states.
    INDEX: ``ix_topup_purchases_created_at``.
    """
    grouping = (TopupPurchaseRow.product, TopupPurchaseRow.currency, TopupPurchaseRow.provider)
    amount = sa.func.sum(TopupPurchaseRow.amount_minor).label("amount_minor")
    statement: Select[Any] = sa.select(*grouping, sa.func.count().label("sales"), amount)
    statement = apply_window(statement, TopupPurchaseRow.created_at, window)
    rows = (
        await session.execute(statement.group_by(*grouping).order_by(amount.desc(), *grouping))
    ).all()
    return tuple(
        RevenueTotal(
            source=RevenueSource.TOPUP,
            product=row.product.value,
            currency=row.currency,
            provider=row.provider,
            sales=int(row.sales),
            amount_minor=int(row.amount_minor),
        )
        for row in rows
    )


async def count_unpriced_topups(
    session: AsyncSession, *, window: TimeWindow | None = None
) -> UnpricedTopups:
    """Top-up grants with no receipt, and with one. The backlog, counted and never priced.

    **Do not multiply the first number by a price.** See the module docstring: the amount
    those sales were charged at is unrecoverable, and pricing them at a value read now would
    reprice every prior reported period the next time the price moves. The count is the
    honest answer and the pair is what makes the money beside it readable.

    Both halves come from ONE scan of the same population — every ``TOPUP_PURCHASE`` grant
    in the window — split by whether a receipt shares its key. Two separate queries could
    disagree at the boundary; one conditional pair cannot. A ``PERIOD_ALLOWANCE`` or
    ``PLAN_SONG`` grant is outside the population entirely and is counted in neither.

    INDEX: ``ix_credit_ledger_created_at`` for the outer window, then an index-only probe of
    the unique ``ix_topup_purchases_idempotency_key`` per candidate row. ``reason`` is
    checked in the heap and deliberately carries no index of its own.
    """
    receipt_exists = (
        sa.select(sa.literal(1))
        .select_from(TopupPurchaseRow)
        .where(TopupPurchaseRow.idempotency_key == CreditLedgerRow.idempotency_key)
        .exists()
    )
    statement: Select[tuple[int, int]] = (
        sa.select(
            sa.func.count(sa.case((~receipt_exists, 1), else_=None)).label("unpriced"),
            sa.func.count(sa.case((receipt_exists, 1), else_=None)).label("priced"),
        )
        .select_from(CreditLedgerRow)
        .where(CreditLedgerRow.reason == CreditReason.TOPUP_PURCHASE)
    )
    statement = apply_window(statement, CreditLedgerRow.created_at, window)
    row = (await session.execute(statement)).one()
    return UnpricedTopups(unpriced=int(row.unpriced), priced=int(row.priced))


async def has_recorded_topup_revenue(session: AsyncSession) -> bool:
    """True once any top-up AMOUNT has been recorded. The ``isTopupRevenue`` capability.

    Window-blind, and false is the interesting answer: it is true of every deployment's
    entire history up to the revision that created this table, and it is the state the SPA
    must render as "sold before amounts were recorded" — with
    :func:`count_unpriced_topups`' first number beside it — rather than as an empty chart.
    """
    probe = await session.scalar(sa.select(sa.literal(1)).select_from(TopupPurchaseRow).limit(1))
    return probe is not None


async def receipt_for_key(session: AsyncSession, *, idempotency_key: str) -> PaymentReceipt | None:
    """The single-song sale written under one payment's key, or ``None`` if none was.

    The dossier's receipt panel, for ``product = 'single'``. It lives here rather than in
    :mod:`bayram.db.admin.payment_intents` because one module reads one TABLE and the ROUTER is
    what joins two sources — the rule this package states in
    :mod:`bayram.db.admin.plan_purchases` and follows everywhere.

    **``None`` is a legitimate answer and is not a defect.** A settled intent with no receipt is
    what an erased buyer looks like: ``db/payme.py::_settle`` claims the intent and writes no
    sale when ``telegram_user_id IS NULL``, because ``/forget`` ran between the payment starting
    and settling — the money moved and there is nobody left to grant a credit to. The caller
    renders that as "buyer erased" with the amounts intact, never as a discrepancy to repair.

    The plan-only fields are ``None`` here by construction and ``credits_granted`` is populated;
    :func:`bayram.db.admin.plan_purchases.receipt_for_key` is the mirror image. Which set is
    populated is stated by :data:`TOPUP_RECEIPT_SOURCE` rather than inferred from a null.

    INDEX: the unique ``ix_topup_purchases_idempotency_key`` — one index-only probe.
    """
    row = (
        await session.execute(
            sa.select(
                TopupPurchaseRow.amount_minor,
                TopupPurchaseRow.currency,
                TopupPurchaseRow.provider,
                TopupPurchaseRow.reference,
                TopupPurchaseRow.credits_granted,
                TopupPurchaseRow.created_at,
            ).where(TopupPurchaseRow.idempotency_key == idempotency_key)
        )
    ).one_or_none()
    if row is None:
        return None
    return PaymentReceipt(
        source=TOPUP_RECEIPT_SOURCE,
        amount_minor=int(row.amount_minor),
        currency=str(row.currency),
        provider=str(row.provider),
        reference=None if row.reference is None else str(row.reference),
        credits_granted=int(row.credits_granted),
        songs_included=None,
        songs_used=None,
        plan_ends_at=None,
        created_at=row.created_at,
    )
