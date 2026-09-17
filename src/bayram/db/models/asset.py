"""``assets`` — one row per delivered file, plus its retention clock.

``payload`` exists for exactly one asset kind: the lyric sheet, which is the only
deliverable whose *content* we need back out of the database (to re-send it, or to
re-typeset it in a different script). Audio content lives in object storage; the row
records where and what, never the bytes.
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Any, Final
from uuid import UUID, uuid4

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column, relationship

from bayram.contracts import MAX_CANDIDATE_CHARS, AssetKind, NameStrategy
from bayram.db.base import SHA256_LENGTH, Base, UtcDateTime, enum_type, utc_now
from bayram.db.retention import RetentionClass

if TYPE_CHECKING:
    from bayram.db.models.order import OrderRow

__all__ = ["AssetRow", "PATH_LENGTH", "MIME_LENGTH", "TG_FILE_ID_LENGTH"]

PATH_LENGTH: Final[int] = 512
MIME_LENGTH: Final[int] = 64
TG_FILE_ID_LENGTH: Final[int] = 128
PERSONA_ID_LENGTH: Final[int] = 64


class AssetRow(Base):
    """A finished file belonging to an order.

    ``(order_id, kind, variant_index)`` is unique so a re-render replaces its predecessor
    instead of quietly doubling the greeting count on a retried delivery.
    """

    __tablename__ = "assets"
    __table_args__ = (
        sa.UniqueConstraint("order_id", "kind", "variant_index"),
        sa.Index("ix_assets_expiry_sweep", "expires_at"),
    )

    id: Mapped[UUID] = mapped_column(sa.Uuid, primary_key=True, default=uuid4)
    order_id: Mapped[UUID] = mapped_column(
        sa.Uuid, sa.ForeignKey("orders.id", ondelete="CASCADE"), nullable=False, index=True
    )
    kind: Mapped[AssetKind] = mapped_column(enum_type(AssetKind), nullable=False)
    #: Position within a kind. The three greetings are variants 0, 1, 2 of GREETING.
    variant_index: Mapped[int] = mapped_column(sa.Integer, nullable=False, default=0)

    path: Mapped[str] = mapped_column(sa.String(PATH_LENGTH), nullable=False)
    storage_key: Mapped[str | None] = mapped_column(sa.String(PATH_LENGTH), nullable=True)
    mime: Mapped[str] = mapped_column(sa.String(MIME_LENGTH), nullable=False)
    size_bytes: Mapped[int] = mapped_column(sa.BigInteger, nullable=False, default=0)
    duration_s: Mapped[float] = mapped_column(sa.Float, nullable=False, default=0.0)
    #: SoW FIL-9 deduplicates on this before storing, hence the index.
    sha256: Mapped[str] = mapped_column(sa.String(SHA256_LENGTH), nullable=False, index=True)
    loudness_lufs: Mapped[float | None] = mapped_column(sa.Float, nullable=True)
    persona_id: Mapped[str | None] = mapped_column(sa.String(PERSONA_ID_LENGTH), nullable=True)
    #: SoW FIL-4: the cost control. Reusing it makes a re-send cost zero bytes.
    tg_file_id: Mapped[str | None] = mapped_column(sa.String(TG_FILE_ID_LENGTH), nullable=True)

    # -- which orthography produced this take ---------------------------------
    name_candidate_text: Mapped[str | None] = mapped_column(
        sa.String(MAX_CANDIDATE_CHARS), nullable=True
    )
    name_candidate_strategy: Mapped[NameStrategy | None] = mapped_column(
        enum_type(NameStrategy), nullable=True
    )
    name_candidate_rank: Mapped[int | None] = mapped_column(sa.Integer, nullable=True)

    #: Lyric-sheet content only. ``None`` for every audio asset.
    payload: Mapped[dict[str, Any] | None] = mapped_column(sa.JSON, nullable=True)

    retention_class: Mapped[RetentionClass] = mapped_column(
        enum_type(RetentionClass), nullable=False, default=RetentionClass.PAID_AUDIO
    )
    #: Stamped from ``RetentionPolicy.expires_at``; a legal hold pushes it out (DAT-6).
    expires_at: Mapped[datetime] = mapped_column(UtcDateTime, nullable=False)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime, nullable=False, default=utc_now)

    order: Mapped[OrderRow] = relationship(back_populates="assets", lazy="raise")
