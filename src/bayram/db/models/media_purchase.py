"""``media_purchases`` — the append-only receipt for a paid (or beta-free) media request.

IMAGE_VIDEO_SPEC §3.2.2, §7.2. ``topup_purchases``' vocabulary on purpose — ``telegram_user_id``,
``amount_minor``, ``currency``, ``provider``, ``reference``, ``idempotency_key``,
``created_at`` — so the receipt tables stay one ``UNION ALL`` apart; see that model's
docstring for the argument, which is not repeated here.

**NO ``stub`` PROVIDER.** A media SKU is never charged on the stub rail: it is free beta
(``beta``, amount 0) or it is not offered at all (§7.4). ``credit`` is a spend of a
kind-scoped refund credit; ``reference`` then names the ledger row.

**NO FOREIGN KEY TO ``media_jobs``.** The job row of an unpaid request is purged whole, and a
paid one keeps its row, but a receipt must survive either: it answers a billing dispute months
after the prompt and the images are lawfully gone.

**THE THIRD RETENTION ROUTE** (§3.2.4): ``/forget`` nulls ``telegram_user_id`` and keeps the
sale; a 400-day cutoff on ``created_at`` then bounds the ANONYMISED remainder only
(``bayram.db.purge``). An identified receipt is never swept — the same narrowing the
``terms_acceptances`` cutoff makes, for the same reason: a live account's record of what it
paid for must not age out while the account can still dispute it.
"""

from __future__ import annotations

from datetime import datetime
from typing import Final
from uuid import UUID, uuid4

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from bayram.db.base import Base, UtcDateTime, enum_type, utc_now
from bayram.db.enums import MediaPurchaseProvider, MediaSku

__all__ = ["MediaPurchaseRow", "MEDIA_IDEMPOTENCY_KEY_LENGTH", "MEDIA_REFERENCE_LENGTH"]

#: Matches ``TOPUP_IDEMPOTENCY_KEY_LENGTH``.
MEDIA_IDEMPOTENCY_KEY_LENGTH: Final[int] = 128
#: Matches ``TOPUP_REFERENCE_LENGTH``.
MEDIA_REFERENCE_LENGTH: Final[int] = 64


class MediaPurchaseRow(Base):
    """One media sale: which job, which SKU, for how much, on which rail. Never updated
    except by ``/forget``."""

    __tablename__ = "media_purchases"
    __table_args__ = (sa.CheckConstraint("amount_minor >= 0", name="amount_not_negative"),)

    id: Mapped[UUID] = mapped_column(sa.Uuid, primary_key=True, default=uuid4)
    #: NULLABLE ONLY SO ERASURE HAS SOMEWHERE TO GO: a NULL means ``/forget`` ran.
    telegram_user_id: Mapped[int | None] = mapped_column(sa.BigInteger, nullable=True, index=True)
    job_id: Mapped[UUID] = mapped_column(sa.Uuid, nullable=False)
    sku: Mapped[MediaSku] = mapped_column(enum_type(MediaSku), nullable=False)
    amount_minor: Mapped[int] = mapped_column(sa.Integer, nullable=False)
    currency: Mapped[str] = mapped_column(sa.String(3), nullable=False)
    provider: Mapped[MediaPurchaseProvider] = mapped_column(
        enum_type(MediaPurchaseProvider, length=16), nullable=False
    )
    #: The Payme transaction id, or the ledger row's id for a credit spend.
    reference: Mapped[str] = mapped_column(sa.String(MEDIA_REFERENCE_LENGTH), nullable=False)
    #: What makes a replayed settlement one sale.
    idempotency_key: Mapped[str] = mapped_column(
        sa.String(MEDIA_IDEMPOTENCY_KEY_LENGTH), nullable=False, unique=True
    )
    created_at: Mapped[datetime] = mapped_column(
        UtcDateTime, nullable=False, default=utc_now, index=True
    )
