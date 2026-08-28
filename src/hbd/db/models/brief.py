"""``briefs`` — the single table subject to erasure (SoW DAT-3).

Everything a user told us about a real third party lives here and nowhere else, on two
independent clocks:

* the **free-text note** (recipient facts) is cleared 30 days after delivery;
* the **recipient's identity** (name, script, candidate orthographies) is cleared at 90
  days absent reminder consent.

Both sets of columns are therefore nullable. A brief whose identity has been cleared can
no longer be reconstructed into a :class:`hbd.contracts.Brief`, and that is the correct
outcome — the data is gone, and the repository says so rather than inventing a placeholder.

**No recipient birth year exists in this table or any other** (SoW FR-102, DAT-5, LR-69).
``event_day`` and ``event_month`` are the whole of what the product needs; the year is the
component that would turn the record into a date of birth. ``tests/test_db`` asserts the
absence by pattern, so a future migration cannot reintroduce one by accident.
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Any, Final
from uuid import UUID, uuid4

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column, relationship

from hbd.contracts import (
    MAX_RECIPIENT_NAME_CHARS,
    Genre,
    Language,
    Occasion,
    Script,
    VoiceGender,
)
from hbd.db.base import Base, TimestampMixin, UtcDateTime, enum_type

if TYPE_CHECKING:
    from hbd.db.models.order import OrderRow

__all__ = ["BriefRow", "MAX_NOTE_CHARS", "LOOKUP_KEY_LENGTH"]

#: Matches ``Brief.note``'s own bound; the column must not be the narrower of the two.
MAX_NOTE_CHARS: Final[int] = 600
LOOKUP_KEY_LENGTH: Final[int] = 80

_MIN_DAY: Final[int] = 1
_MAX_DAY: Final[int] = 31
_MIN_MONTH: Final[int] = 1
_MAX_MONTH: Final[int] = 12


class BriefRow(TimestampMixin, Base):
    """The four structured answers, the free-text note, and the recipient's name."""

    __tablename__ = "briefs"
    __table_args__ = (
        sa.CheckConstraint(
            f"event_day IS NULL OR (event_day BETWEEN {_MIN_DAY} AND {_MAX_DAY})",
            name="event_day_range",
        ),
        sa.CheckConstraint(
            f"event_month IS NULL OR (event_month BETWEEN {_MIN_MONTH} AND {_MAX_MONTH})",
            name="event_month_range",
        ),
    )

    id: Mapped[UUID] = mapped_column(sa.Uuid, primary_key=True, default=uuid4)
    order_id: Mapped[UUID] = mapped_column(
        sa.Uuid, sa.ForeignKey("orders.id", ondelete="CASCADE"), nullable=False, unique=True
    )

    # -- structured answers: not personal data, never purged ------------------
    occasion: Mapped[Occasion] = mapped_column(enum_type(Occasion), nullable=False)
    genre: Mapped[Genre] = mapped_column(enum_type(Genre), nullable=False)
    vocal_gender: Mapped[VoiceGender] = mapped_column(enum_type(VoiceGender), nullable=False)
    ui_language: Mapped[Language] = mapped_column(enum_type(Language), nullable=False)
    output_language: Mapped[Language] = mapped_column(enum_type(Language), nullable=False)

    # -- free-text facts: cleared at brief_text_expires_at --------------------
    note: Mapped[str | None] = mapped_column(sa.String(MAX_NOTE_CHARS), nullable=True)
    note_expires_at: Mapped[datetime] = mapped_column(UtcDateTime, nullable=False, index=True)
    note_purged_at: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)

    # -- recipient identity: cleared at identity_expires_at -------------------
    #: Byte-preserved as typed — U+2018, U+0027 and friends intact.
    recipient_name_raw: Mapped[str | None] = mapped_column(
        sa.String(MAX_RECIPIENT_NAME_CHARS), nullable=True
    )
    #: The canonicalised U+02BB form. The ONLY form a human ever reads.
    recipient_name_display: Mapped[str | None] = mapped_column(
        sa.String(MAX_RECIPIENT_NAME_CHARS), nullable=True
    )
    recipient_lookup_key: Mapped[str | None] = mapped_column(
        sa.String(LOOKUP_KEY_LENGTH), nullable=True, index=True
    )
    recipient_script: Mapped[Script | None] = mapped_column(enum_type(Script), nullable=True)
    recipient_language: Mapped[Language | None] = mapped_column(enum_type(Language), nullable=True)
    #: Ranked candidate orthographies, serialised. Never rendered to a user.
    recipient_candidates: Mapped[list[dict[str, Any]] | None] = mapped_column(
        sa.JSON, nullable=True
    )
    identity_expires_at: Mapped[datetime] = mapped_column(UtcDateTime, nullable=False, index=True)
    identity_purged_at: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)

    # -- occasion date: DAY AND MONTH ONLY. There is no year column. ----------
    event_day: Mapped[int | None] = mapped_column(sa.SmallInteger, nullable=True)
    event_month: Mapped[int | None] = mapped_column(sa.SmallInteger, nullable=True)

    order: Mapped[OrderRow] = relationship(back_populates="brief", lazy="raise")

    @property
    def is_identity_purged(self) -> bool:
        """True once the 90-day identity clock has been run by the purge job."""
        return self.identity_purged_at is not None or self.recipient_name_display is None

    @property
    def is_note_purged(self) -> bool:
        return self.note_purged_at is not None
