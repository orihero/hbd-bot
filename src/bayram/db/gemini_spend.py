"""What Gemini has cost us, and whether Google has said the prepay money ran out.

Google exposes no API for a Gemini prepay balance or for the credits bought into it — both
live only in AI Studio (DECISIONS.md D27) — so the panel reports SPEND instead, summed from
the calls ``vendor_usage`` already records. Read-only SQL, so the admin panel may call it
without gaining egress or a credential.

**All Gemini spend, not only music.** One prepay balance pays for every key on the billing
account, so an LLM leg running on Gemini is summed too. Health probes are excluded — they are
never priced — and so are fake rows. Figures are ESTIMATES: our per-request price
(``LYRIA_USD_PER_REQUEST``), not Google's invoice.

**"Depleted" is Google's word, not our arithmetic.** It is true when the most recent
non-health Gemini call failed with ``QUOTA_EXHAUSTED`` (a 402 "prepayment credits are
depleted"). A later success clears it, which is what a top-up looks like from here.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from bayram.contracts import Vendor, VendorOperation
from bayram.db.models.vendor_usage import VendorUsageRow
from bayram.errors import ErrorCode

__all__ = ["GeminiSpend", "GeminiSpendTotal", "measure_gemini_spend"]


@dataclass(frozen=True, slots=True)
class GeminiSpendTotal:
    """Priced spend since an instant, and how many calls carried that price."""

    spent_usd: float
    priced_calls: int


@dataclass(frozen=True, slots=True)
class GeminiSpend:
    """Today's and this month's spend, plus Google's latest verdict on the balance."""

    today: GeminiSpendTotal
    month: GeminiSpendTotal
    is_depleted: bool
    #: When the refusal that made ``is_depleted`` true was recorded; ``None`` otherwise.
    depleted_at: datetime | None


_SPENDABLE = (
    VendorUsageRow.vendor == Vendor.GEMINI,
    VendorUsageRow.is_fake.is_(False),
    VendorUsageRow.operation != VendorOperation.HEALTH,
)


async def _total(session: AsyncSession, *, since: datetime) -> GeminiSpendTotal:
    spent, priced = (
        await session.execute(
            sa.select(
                sa.func.coalesce(sa.func.sum(VendorUsageRow.cost_usd), 0.0),
                sa.func.count(VendorUsageRow.cost_usd),
            ).where(*_SPENDABLE, VendorUsageRow.created_at >= since)
        )
    ).one()
    return GeminiSpendTotal(spent_usd=float(spent), priced_calls=int(priced))


async def measure_gemini_spend(
    session: AsyncSession, *, day_start: datetime, month_start: datetime
) -> GeminiSpend:
    """Sum priced Gemini calls since each boundary and read the latest call's outcome."""
    latest = (
        await session.execute(
            sa.select(VendorUsageRow.error_code, VendorUsageRow.created_at)
            .where(*_SPENDABLE)
            .order_by(VendorUsageRow.created_at.desc(), VendorUsageRow.id.desc())
            .limit(1)
        )
    ).one_or_none()
    is_depleted = latest is not None and latest[0] == ErrorCode.QUOTA_EXHAUSTED.value
    return GeminiSpend(
        today=await _total(session, since=day_start),
        month=await _total(session, since=month_start),
        is_depleted=is_depleted,
        depleted_at=latest[1] if is_depleted and latest is not None else None,
    )
