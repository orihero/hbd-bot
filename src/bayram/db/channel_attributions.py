"""SQL implementation of channel attribution recording and lookup."""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from bayram.channels import ChannelAttributionStore
from bayram.db.base import utc_now
from bayram.db.models.channel_attribution import ChannelAttributionRow
from bayram.logging import get_logger

__all__ = ["SqlChannelAttributions", "get_user_channel"]

_LOG = get_logger(__name__)


class SqlChannelAttributions(ChannelAttributionStore):
    """Database persistence for inbound Telegram deep-link traffic attributions."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def record_attribution(
        self,
        telegram_user_id: int,
        *,
        raw_param: str,
        channel: str,
    ) -> bool:
        """Record an inbound start parameter attribution.

        Checks whether this user already has a prior attribution record; if not, marks
        this event as ``is_first_touch=True``.
        """
        async with self._session_factory() as session, session.begin():
            existing = (
                await session.execute(
                    sa.select(ChannelAttributionRow.id)
                    .where(ChannelAttributionRow.telegram_user_id == telegram_user_id)
                    .limit(1)
                )
            ).scalar_one_or_none()

            is_first_touch = existing is None
            row = ChannelAttributionRow(
                telegram_user_id=telegram_user_id,
                channel=channel,
                raw_param=raw_param,
                is_first_touch=is_first_touch,
                created_at=utc_now(),
            )
            session.add(row)

        _LOG.info(
            "channel attribution recorded",
            extra={
                "telegram_user_id": telegram_user_id,
                "channel": channel,
                "is_first_touch": is_first_touch,
            },
        )
        return is_first_touch


async def get_user_channel(session: AsyncSession, telegram_user_id: int) -> str | None:
    """Return the first-touch acquisition channel for a user, if known."""
    stmt = (
        sa.select(ChannelAttributionRow.channel)
        .where(
            ChannelAttributionRow.telegram_user_id == telegram_user_id,
            ChannelAttributionRow.is_first_touch.is_(True),
        )
        .limit(1)
    )
    return (await session.execute(stmt)).scalar_one_or_none()
