"""``users`` — one row per Telegram account that has spoken to the bot."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from hbd.contracts import Language
from hbd.db.base import Base, TimestampMixin, UtcDateTime, enum_type, utc_now

__all__ = ["UserRow"]


class UserRow(TimestampMixin, Base):
    """A Telegram user.

    Deliberately thin. Free-tier counters, referral graph and revenue totals belong to
    modules that are out of scope for this build; adding empty columns for them now would
    be speculative schema that the first real requirement would immediately contradict.
    """

    __tablename__ = "users"

    id: Mapped[UUID] = mapped_column(sa.Uuid, primary_key=True, default=uuid4)
    telegram_user_id: Mapped[int] = mapped_column(sa.BigInteger, nullable=False, unique=True)
    #: Interface language. Chosen independently of an order's output language.
    ui_language: Mapped[Language] = mapped_column(
        enum_type(Language), nullable=False, default=Language.UZ_LATN
    )
    is_blocked: Mapped[bool] = mapped_column(sa.Boolean, nullable=False, default=False)
    last_seen_at: Mapped[datetime] = mapped_column(UtcDateTime, nullable=False, default=utc_now)
