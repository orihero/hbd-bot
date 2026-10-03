"""Tests for marketing traffic channels metrics on the admin dashboard."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from bayram.admin.container import AdminContainer
from bayram.admin.routers.dashboard import AUDIENCE_PATH
from bayram.contracts import Language, OrderState
from bayram.db.enums import PlanKind, TopupKind
from bayram.db.models.channel_attribution import ChannelAttributionRow
from bayram.db.models.order import OrderRow
from bayram.db.models.plan_purchase import PlanPurchaseRow
from bayram.db.models.topup_purchase import TopupPurchaseRow
from bayram.db.models.user import UserRow
from bayram.db.models.user_profile import UserProfileRow
from tests.test_admin.test_dashboard_router import signed_in

pytestmark = pytest.mark.asyncio

NOW = datetime(2026, 9, 30, 12, 0, 0, tzinfo=UTC)
DAY_ONE = NOW - timedelta(days=5)
DAY_TWO = NOW - timedelta(days=3)
DAY_THREE = NOW - timedelta(days=1)


async def seed_user_with_channel(
    session: AsyncSession,
    *,
    telegram_user_id: int,
    channel: str,
    raw_param: str,
    created_at: datetime,
    is_first_touch: bool = True,
    is_onboarded: bool = False,
) -> UserRow:
    user = UserRow(
        id=uuid4(),
        telegram_user_id=telegram_user_id,
        created_at=created_at,
        last_seen_at=created_at,
        ui_language=Language.UZ_LATN,
    )
    session.add(user)
    if is_onboarded:
        session.add(
            UserProfileRow(
                user_id=user.id,
                telegram_user_id=telegram_user_id,
                first_name="Test",
                onboarded_at=created_at + timedelta(minutes=5),
                created_at=created_at,
            )
        )
    session.add(
        ChannelAttributionRow(
            id=uuid4(),
            telegram_user_id=telegram_user_id,
            channel=channel,
            raw_param=raw_param,
            is_first_touch=is_first_touch,
            created_at=created_at,
        )
    )
    return user


async def test_audience_channels_empty(
    container: AdminContainer, client: httpx.AsyncClient
) -> None:
    """An empty deployment returns an empty channels list."""
    await signed_in(container, client)
    response = await client.get(AUDIENCE_PATH)
    assert response.status_code == 200
    body = response.json()
    assert "channels" in body
    assert body["channels"] == []


async def test_audience_channels_aggregated_metrics(
    container: AdminContainer, client: httpx.AsyncClient
) -> None:
    """Verify clicks, new users, onboarded, orders, paying users, revenue, and conversion."""
    async with container.session_factory.begin() as session:
        # User 101: kanallanidodasi, onboarded, 1 order, 1 topup (50,000 UZS)
        u101 = await seed_user_with_channel(
            session,
            telegram_user_id=101,
            channel="kanallanidodasi",
            raw_param="utm_source=kanallanidodasi",
            created_at=DAY_ONE,
            is_first_touch=True,
            is_onboarded=True,
        )
        session.add(
            OrderRow(
                id=uuid4(),
                user_id=u101.id,
                telegram_user_id=101,
                state=OrderState.DELIVERED,
                correlation_id="corr-101",
                is_paid=True,
                created_at=DAY_ONE + timedelta(hours=1),
                delivered_at=DAY_ONE + timedelta(hours=2),
                updated_at=DAY_ONE + timedelta(hours=2),
            )
        )
        session.add(
            TopupPurchaseRow(
                id=uuid4(),
                telegram_user_id=101,
                product=TopupKind.SINGLE,
                credits_granted=1,
                currency="UZS",
                amount_minor=50_000,
                provider="stub",
                reference="ref-101",
                idempotency_key="key-101",
                created_at=DAY_ONE + timedelta(hours=3),
            )
        )

        # User 102: kanallanidodasi, not onboarded, no purchases
        await seed_user_with_channel(
            session,
            telegram_user_id=102,
            channel="kanallanidodasi",
            raw_param="utm_source_kanallanidodasi",
            created_at=DAY_TWO,
            is_first_touch=True,
            is_onboarded=False,
        )

        # User 101 returns later via kanallanidodasi link (click only, not first touch)
        session.add(
            ChannelAttributionRow(
                id=uuid4(),
                telegram_user_id=101,
                channel="kanallanidodasi",
                raw_param="c_kanallanidodasi",
                is_first_touch=False,
                created_at=DAY_THREE,
            )
        )

        # User 201: instagram_bio, onboarded, buys plan (150,000 UZS)
        await seed_user_with_channel(
            session,
            telegram_user_id=201,
            channel="instagram_bio",
            raw_param="utm_source=instagram_bio",
            created_at=DAY_TWO,
            is_first_touch=True,
            is_onboarded=True,
        )
        session.add(
            PlanPurchaseRow(
                id=uuid4(),
                telegram_user_id=201,
                plan=PlanKind.STARTER,
                currency="UZS",
                amount_minor=150_000,
                provider="stub",
                reference="ref-201",
                idempotency_key="key-201",
                songs_included=10,
                songs_used=0,
                plan_ends_at=NOW + timedelta(days=25),
                created_at=DAY_TWO + timedelta(hours=2),
                updated_at=DAY_TWO + timedelta(hours=2),
            )
        )

        # User 301: direct_promo, first touch, no purchases
        await seed_user_with_channel(
            session,
            telegram_user_id=301,
            channel="direct_promo",
            raw_param="direct_promo",
            created_at=DAY_THREE,
            is_first_touch=True,
            is_onboarded=False,
        )

    await signed_in(container, client)
    response = await client.get(AUDIENCE_PATH)
    assert response.status_code == 200
    body = response.json()
    channels = body["channels"]

    # Sorted by clicks descending
    assert len(channels) == 3
    kanal = next(c for c in channels if c["channel"] == "kanallanidodasi")
    assert kanal["clicks"] == 3
    assert kanal["newUsers"] == 2
    assert kanal["onboardedUsers"] == 1
    assert kanal["ordersCount"] == 1
    assert kanal["payingUsers"] == 1
    assert kanal["revenueMinor"] == 50_000
    assert kanal["conversionRate"] == 0.5  # 1 paying / 2 new users

    insta = next(c for c in channels if c["channel"] == "instagram_bio")
    assert insta["clicks"] == 1
    assert insta["newUsers"] == 1
    assert insta["onboardedUsers"] == 1
    assert insta["ordersCount"] == 0
    assert insta["payingUsers"] == 1
    assert insta["revenueMinor"] == 150_000
    assert insta["conversionRate"] == 1.0

    promo = next(c for c in channels if c["channel"] == "direct_promo")
    assert promo["clicks"] == 1
    assert promo["newUsers"] == 1
    assert promo["onboardedUsers"] == 0
    assert promo["ordersCount"] == 0
    assert promo["payingUsers"] == 0
    assert promo["revenueMinor"] == 0
    assert promo["conversionRate"] == 0.0


async def test_user_detail_includes_acquisition_channel(
    container: AdminContainer, client: httpx.AsyncClient
) -> None:
    """Verify that /api/users/{telegram_user_id} reports acquisitionChannel."""
    async with container.session_factory.begin() as session:
        await seed_user_with_channel(
            session,
            telegram_user_id=777,
            channel="kanallanidodasi",
            raw_param="utm_source=kanallanidodasi",
            created_at=DAY_ONE,
            is_first_touch=True,
            is_onboarded=True,
        )

    await signed_in(container, client)
    response = await client.get("/api/users/777")
    assert response.status_code == 200
    detail = response.json()
    assert detail["acquisitionChannel"] == "kanallanidodasi"


async def test_audience_channels_respects_time_window(
    container: AdminContainer, client: httpx.AsyncClient
) -> None:
    """Verify that from/to window parameters filter channel attributions."""
    async with container.session_factory.begin() as session:
        # Channel event on DAY_ONE
        await seed_user_with_channel(
            session,
            telegram_user_id=888,
            channel="old_campaign",
            raw_param="old_campaign",
            created_at=DAY_ONE,
            is_first_touch=True,
        )
        # Channel event on DAY_THREE
        await seed_user_with_channel(
            session,
            telegram_user_id=999,
            channel="recent_campaign",
            raw_param="recent_campaign",
            created_at=DAY_THREE,
            is_first_touch=True,
        )

    await signed_in(container, client)
    # Query window from DAY_TWO to NOW (should only include recent_campaign)
    response = await client.get(
        AUDIENCE_PATH,
        params={"from": DAY_TWO.isoformat(), "to": NOW.isoformat()},
    )
    assert response.status_code == 200
    channels = response.json()["channels"]
    assert len(channels) == 1
    assert channels[0]["channel"] == "recent_campaign"
