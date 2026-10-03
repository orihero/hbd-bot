"""``channel_attributions`` — marketing traffic sources and campaign conversions."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from bayram.channels import MAX_CHANNEL_LENGTH
from bayram.db.base import Base, UtcDateTime, utc_now

__all__ = ["ChannelAttributionRow"]


class ChannelAttributionRow(Base):
    """One inbound traffic attribution event from a Telegram deep link.

    - ``telegram_user_id`` is nullable for erasure/anonymisation on ``/forget``.
    - ``channel`` is the parsed marketing channel or campaign identifier (e.g. ``kanallanidodasi``).
    - ``raw_param`` is the raw start payload received in ``/start <param>``.
    - ``is_first_touch`` indicates whether this was the user's initial acquisition touchpoint.
    - ``created_at`` is the UTC timestamp of the attribution event.
    """

    __tablename__ = "channel_attributions"

    id: Mapped[UUID] = mapped_column(sa.Uuid, primary_key=True, default=uuid4)
    telegram_user_id: Mapped[int | None] = mapped_column(sa.BigInteger, nullable=True, index=True)
    channel: Mapped[str] = mapped_column(sa.String(MAX_CHANNEL_LENGTH), nullable=False, index=True)
    raw_param: Mapped[str] = mapped_column(sa.String(MAX_CHANNEL_LENGTH), nullable=False)
    is_first_touch: Mapped[bool] = mapped_column(sa.Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(
        UtcDateTime, nullable=False, default=utc_now, index=True
    )
