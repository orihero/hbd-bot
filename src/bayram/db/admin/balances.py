"""``vendor_balances`` — what each vendor says is left, read from cache and never fetched.

**The security boundary is the reason this module exists at all, and it is the first thing
to state.** The admin process holds no vendor credential and makes no outbound HTTP request.
The poller lives in the ARQ worker, which already holds the keys because it already makes
the calls; it writes one row per ``(vendor, is_fallback)`` into ``vendor_balances`` and this
module reads what it wrote. Giving the panel an HTTP client and an API key so a tile could
say "$12.40 left" would put a vendor credential in the process an operator's browser talks
to, for a number that is at most an hour old either way. A "System status" strip is exactly
the place somebody reaches for a client, so the refusal is written down here rather than
left to be re-derived.

**Two clocks, and they are not interchangeable.** ``checked_at`` is when the poller last
ASKED; ``fetched_at`` is when the numbers beside it were last actually ANSWERED. They move
together while the vendor is up and diverge during an outage, because the writer's failure
path names a strict subset of columns and the last known balance survives untouched. A
single "as of" would render a three-hour-old figure as fresh, so both travel to the wire and
staleness is computed against ``fetched_at``.

**Nothing here is personal data.** A vendor name, a plan tier, a subscription status, a
handful of numbers and two clocks. ``data.label`` — the one field on OpenRouter's key
endpoint that could carry a person's name — is never parsed by the probe and therefore has
no column to read.

**A row's absence and a row's failure are different screens.** No row at all means the
poller has never run here (``capabilities.isVendorBalance`` is false and the panel says
"not polled"); a row with ``is_last_poll_ok`` false means we asked and were refused, and it
still carries the last balance we were told, aged. Neither renders as zero.
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from bayram.db.admin.views import VendorBalanceState
from bayram.db.models.vendor_balance import VendorBalanceRow

__all__ = ["vendor_balances", "has_polled_vendor_balances"]


async def vendor_balances(session: AsyncSession) -> tuple[VendorBalanceState, ...]:
    """Every cached balance row, ordered by vendor then primary-before-fallback.

    **Window-blind, and that is a decision rather than an omission.** A balance is a STATE,
    not a flow: "how much credit was left during March" is a question this table cannot
    answer — it holds one row per probe target and the poller overwrites it — so accepting a
    window would let a caller ask something the answer could not honour. The caller reads
    the two clocks on each row to decide how much to trust it.

    Ordered rather than left to the planner because the rows land in a fixed strip on the
    screen, and a strip whose tiles reorder between polls is one an operator cannot scan.

    INDEX: none needed. The table holds one row per probe target — three today — so a scan
    is the whole table and the primary key is the ordering.
    """
    rows = (
        await session.execute(
            sa.select(VendorBalanceRow).order_by(
                VendorBalanceRow.vendor, VendorBalanceRow.is_fallback
            )
        )
    ).scalars()
    return tuple(
        VendorBalanceState(
            vendor=row.vendor,
            is_fallback=row.is_fallback,
            provider=row.provider,
            balance_unit=row.balance_unit,
            balance_remaining=row.balance_remaining,
            balance_total=row.balance_total,
            balance_used=row.balance_used,
            is_unbounded=row.is_unbounded,
            quota_resets_at=row.quota_resets_at,
            quota_reset_hint=row.quota_reset_hint,
            plan_tier=row.plan_tier,
            subscription_status=row.subscription_status,
            songs_remaining=row.songs_remaining,
            per_song_rate=row.per_song_rate,
            estimate_basis=row.estimate_basis,
            fetched_at=row.fetched_at,
            checked_at=row.checked_at,
            is_last_poll_ok=row.is_last_poll_ok,
            http_status=row.http_status,
            error_code=row.error_code,
            consecutive_failures=row.consecutive_failures,
        )
        for row in rows
    )


async def has_polled_vendor_balances(session: AsyncSession) -> bool:
    """True once the poller has written any row. The ``isVendorBalance`` capability.

    A ROW probe rather than a :func:`~bayram.db.admin.sql.has_table` one, for the reason the
    vendor-usage pair already documents: the migration ships with the panel, so a schema
    probe would call every deployment polled on the day it lands — including one whose
    worker is an older build, or one where ``BAYRAM_VENDOR_BALANCE_POLL_ENABLED`` is off.
    """
    probe = await session.scalar(sa.select(sa.literal(1)).select_from(VendorBalanceRow).limit(1))
    return probe is not None
