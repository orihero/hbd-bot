"""Marketing channel performance aggregates for the admin dashboard."""

from __future__ import annotations

from dataclasses import dataclass

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from bayram.contracts import OrderState
from bayram.db.admin.sql import TimeWindow, apply_window
from bayram.db.models.channel_attribution import ChannelAttributionRow
from bayram.db.models.order import OrderRow
from bayram.db.models.plan_purchase import PlanPurchaseRow
from bayram.db.models.topup_purchase import TopupPurchaseRow
from bayram.db.models.user_profile import UserProfileRow

__all__ = ["ChannelPerformance", "channel_performance"]


@dataclass(frozen=True, slots=True)
class ChannelPerformance:
    """Acquisition metrics for one marketing channel."""

    channel: str
    clicks: int
    new_users: int
    onboarded_users: int
    orders_count: int
    paying_users: int
    revenue_minor: int
    conversion_rate: float


async def channel_performance(
    session: AsyncSession,
    *,
    window: TimeWindow | None = None,
) -> list[ChannelPerformance]:
    """Return aggregated performance metrics for each marketing channel.

    Measures:
    - ``clicks``: Total visits / starts from this channel
    - ``new_users``: Unique users acquired (first-touch)
    - ``onboarded_users``: Acquired users who completed onboarding
    - ``orders_count``: Delivered songs by acquired users
    - ``paying_users``: Unique paying customers acquired by this channel
    - ``revenue_minor``: Total UZS minor-unit revenue from acquired users
    - ``conversion_rate``: Ratio of paying customers to new users (0.0 if no new users)
    """
    # 1. Traffic (clicks and new first-touch users) per channel
    traffic_q = sa.select(
        ChannelAttributionRow.channel,
        sa.func.count(ChannelAttributionRow.id).label("clicks"),
        sa.func.count(
            sa.distinct(
                sa.case(
                    (
                        ChannelAttributionRow.is_first_touch.is_(True),
                        ChannelAttributionRow.telegram_user_id,
                    ),
                    else_=None,
                )
            )
        ).label("new_users"),
    ).group_by(ChannelAttributionRow.channel)
    traffic_q = apply_window(traffic_q, ChannelAttributionRow.created_at, window)

    traffic_rows = (await session.execute(traffic_q)).all()
    if not traffic_rows:
        return []

    # Map channel -> dict of metrics
    channels_map: dict[str, dict[str, int]] = {
        row.channel: {
            "clicks": int(row.clicks),
            "new_users": int(row.new_users),
            "onboarded_users": 0,
            "orders_count": 0,
            "revenue_minor": 0,
        }
        for row in traffic_rows
    }

    # 2. First-touch users per channel
    first_touch_subq = (
        sa.select(
            ChannelAttributionRow.telegram_user_id.label("uid"),
            ChannelAttributionRow.channel.label("channel"),
        )
        .where(
            ChannelAttributionRow.is_first_touch.is_(True),
            ChannelAttributionRow.telegram_user_id.isnot(None),
        )
        .distinct()
    )
    first_touch_subq = apply_window(first_touch_subq, ChannelAttributionRow.created_at, window)
    acq = first_touch_subq.subquery("acq")

    # 3. Onboarded users per channel
    onboarded_q = (
        sa.select(
            acq.c.channel,
            sa.func.count(sa.distinct(UserProfileRow.telegram_user_id)),
        )
        .select_from(acq)
        .join(UserProfileRow, UserProfileRow.telegram_user_id == acq.c.uid)
        .where(UserProfileRow.onboarded_at.isnot(None))
        .group_by(acq.c.channel)
    )
    for channel, count in (await session.execute(onboarded_q)).all():
        if channel in channels_map:
            channels_map[channel]["onboarded_users"] = int(count)

    # 4. Delivered orders per channel
    orders_q = (
        sa.select(
            acq.c.channel,
            sa.func.count(OrderRow.id),
        )
        .select_from(acq)
        .join(OrderRow, OrderRow.telegram_user_id == acq.c.uid)
        .where(OrderRow.state == OrderState.DELIVERED)
        .group_by(acq.c.channel)
    )
    for channel, count in (await session.execute(orders_q)).all():
        if channel in channels_map:
            channels_map[channel]["orders_count"] = int(count)

    # 5. Topup revenue per channel
    topup_q = (
        sa.select(
            acq.c.channel,
            sa.func.coalesce(sa.func.sum(TopupPurchaseRow.amount_minor), 0),
        )
        .select_from(acq)
        .join(TopupPurchaseRow, TopupPurchaseRow.telegram_user_id == acq.c.uid)
        .group_by(acq.c.channel)
    )
    for channel, amount in (await session.execute(topup_q)).all():
        if channel in channels_map:
            channels_map[channel]["revenue_minor"] += int(amount)

    # 6. Plan revenue per channel
    plan_q = (
        sa.select(
            acq.c.channel,
            sa.func.coalesce(sa.func.sum(PlanPurchaseRow.amount_minor), 0),
        )
        .select_from(acq)
        .join(PlanPurchaseRow, PlanPurchaseRow.telegram_user_id == acq.c.uid)
        .group_by(acq.c.channel)
    )
    for channel, amount in (await session.execute(plan_q)).all():
        if channel in channels_map:
            channels_map[channel]["revenue_minor"] += int(amount)

    # 7. Unique paying users per channel (union of topup and plan buyers)
    paying_union = (
        sa.select(acq.c.channel.label("channel"), TopupPurchaseRow.telegram_user_id.label("uid"))
        .select_from(acq)
        .join(TopupPurchaseRow, TopupPurchaseRow.telegram_user_id == acq.c.uid)
        .union(
            sa.select(acq.c.channel.label("channel"), PlanPurchaseRow.telegram_user_id.label("uid"))
            .select_from(acq)
            .join(PlanPurchaseRow, PlanPurchaseRow.telegram_user_id == acq.c.uid)
        )
        .subquery("paying_users_subq")
    )
    paying_q = sa.select(
        paying_union.c.channel,
        sa.func.count(sa.distinct(paying_union.c.uid)),
    ).group_by(paying_union.c.channel)
    paying_map: dict[str, int] = {
        channel: int(cnt) for channel, cnt in (await session.execute(paying_q)).all()
    }

    # Assemble and sort by clicks descending
    results: list[ChannelPerformance] = []
    for channel, metrics in channels_map.items():
        new_users = metrics["new_users"]
        paying = paying_map.get(channel, 0)
        conv = round(paying / new_users, 4) if new_users > 0 else 0.0
        results.append(
            ChannelPerformance(
                channel=channel,
                clicks=metrics["clicks"],
                new_users=new_users,
                onboarded_users=metrics["onboarded_users"],
                orders_count=metrics["orders_count"],
                paying_users=paying,
                revenue_minor=metrics["revenue_minor"],
                conversion_rate=conv,
            )
        )

    results.sort(key=lambda x: (x.clicks, x.revenue_minor), reverse=True)
    return results
