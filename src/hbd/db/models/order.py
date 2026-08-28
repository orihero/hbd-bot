"""``orders`` — the durable record of one celebration kit request.

Carries **no** recipient data. SoW DAT-3 requires the tax record and the personal-data
record to be separable at the schema level: the brief is purged on its own clock while
the order row survives, so a recipient's facts can never be a column here.
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Final
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column, relationship

from hbd.contracts import OrderState
from hbd.db.base import Base, TimestampMixin, UtcDateTime, enum_type

if TYPE_CHECKING:
    from hbd.db.models.asset import AssetRow
    from hbd.db.models.brief import BriefRow

__all__ = ["OrderRow", "CORRELATION_ID_LENGTH", "FAILED_REASON_LENGTH"]

CORRELATION_ID_LENGTH: Final[int] = 128
FAILED_REASON_LENGTH: Final[int] = 256


class OrderRow(TimestampMixin, Base):
    """One order. Relationships are ``lazy="raise"`` on purpose.

    An implicit lazy load inside async SQLAlchemy surfaces as a confusing greenlet error
    at a random await point. Forcing every read to name its ``selectinload`` turns that
    class of bug into an immediate, local failure at development time.
    """

    __tablename__ = "orders"

    id: Mapped[UUID] = mapped_column(sa.Uuid, primary_key=True)
    user_id: Mapped[UUID] = mapped_column(
        sa.Uuid, sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    #: Denormalised from ``users`` so the history listing is a single-table scan.
    telegram_user_id: Mapped[int] = mapped_column(sa.BigInteger, nullable=False, index=True)
    state: Mapped[OrderState] = mapped_column(enum_type(OrderState), nullable=False, index=True)
    correlation_id: Mapped[str] = mapped_column(
        sa.String(CORRELATION_ID_LENGTH), nullable=False, index=True
    )
    #: Latched true the first time the order reaches ``AUTHORIZED`` — that state IS the
    #: payment-authorised moment, whichever ``PaymentProvider`` produced it. It never
    #: returns to false, because retention is measured from what the customer paid for,
    #: not from where the order happens to sit now. This is the ONLY input that decides
    #: whether an asset gets the 12-month paid clock or the 30-day free one (FIL-7).
    is_paid: Mapped[bool] = mapped_column(sa.Boolean, nullable=False, default=False)
    delivered_at: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)
    failed_reason: Mapped[str | None] = mapped_column(
        sa.String(FAILED_REASON_LENGTH), nullable=True
    )

    brief: Mapped[BriefRow | None] = relationship(
        back_populates="order",
        cascade="all, delete-orphan",
        uselist=False,
        lazy="raise",
    )
    assets: Mapped[list[AssetRow]] = relationship(
        back_populates="order",
        cascade="all, delete-orphan",
        lazy="raise",
        order_by="(AssetRow.kind, AssetRow.variant_index)",
    )
