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

    Deliberately thin, and it stays that way now that free-tier counters exist: the
    entitlement balance lives in ``credit_accounts``, keyed on ``telegram_user_id``, not in
    a column here. Two commitments make that the only workable place. ``docs/
    ADMIN_PANEL_PLAN.md`` §5.11 rules out DDL on this table, and — more concretely — this
    row is created only by ``repository._ensure_user`` from ``_create_order``, so a person
    who walks the wizard and never confirms has no row at all, while the very first thing
    the gate must do for them is open an account and mint an allowance. A balance column
    here would be a mutable money counter on the row the erasure design treats as
    content-erasable-but-identity-surviving; a separate account row costs nothing and keeps
    both promises. Referral graph and revenue totals remain out of scope.
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
