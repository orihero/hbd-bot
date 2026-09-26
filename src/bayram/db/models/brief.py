"""``briefs`` — the single table subject to erasure (SoW DAT-3).

Everything a user told us about a real third party lives here and nowhere else, on two
independent clocks:

* the **free-text note** (recipient facts) and the **approved lyric** are cleared 30 days
  after delivery;
* the **recipient's identity** (name, script, candidate orthographies) is cleared at 90
  days absent reminder consent.

Both sets of columns are therefore nullable. A brief whose identity has been cleared can
no longer be reconstructed into a :class:`bayram.contracts.Brief`, and that is the correct
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

from bayram.contracts import (
    MAX_RECIPIENT_NAME_CHARS,
    Genre,
    Language,
    Occasion,
    Script,
    VoiceGender,
)
from bayram.db.base import Base, TimestampMixin, UtcDateTime, enum_type

if TYPE_CHECKING:
    from bayram.db.models.order import OrderRow

__all__ = ["BriefRow", "MAX_NOTE_CHARS", "LOOKUP_KEY_LENGTH"]

#: Matches ``Brief.note``'s own bound; the column must not be the narrower of the two.
MAX_NOTE_CHARS: Final[int] = 600
LOOKUP_KEY_LENGTH: Final[int] = 80

_MIN_DAY: Final[int] = 1
_MAX_DAY: Final[int] = 31
_MIN_MONTH: Final[int] = 1
_MAX_MONTH: Final[int] = 12


class BriefRow(TimestampMixin, Base):
    """The four structured answers, the free-text note and lyric, and the recipient's name."""

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
    #: The lyric the customer approved in the wizard, stored as the serialised
    #: :class:`bayram.contracts.LyricDraft`. It is free text about the recipient — pasted or
    #: approved by the customer, and it names them in the hook — so it is nulled by the
    #: same 30-day clock as ``note`` rather than kept for the life of the order.
    #:
    #: ``none_as_null`` is not optional here. ``sa.JSON`` defaults to persisting Python
    #: ``None`` as the JSON text ``'null'``, which reads back as ``None`` but is *not* SQL
    #: NULL — so ``approved_lyrics IS NOT NULL`` would stay true for a brief that has no
    #: lyric and for one the purge job has already cleared, and the note sweep in
    #: ``bayram.db.purge`` would re-select the same rows every night forever.
    approved_lyrics: Mapped[dict[str, Any] | None] = mapped_column(
        sa.JSON(none_as_null=True), nullable=True
    )
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
    #:
    #: ``none_as_null=True`` for the same reason ``approved_lyrics`` two columns above
    #: carries it, and the safeguard was applied to one of the pair and not the other:
    #: without it, assigning ``None`` persists the JSON **scalar** ``null`` — the four
    #: characters — rather than SQL ``NULL``. The identity sweep really does destroy the
    #: candidate orthographies either way, so this is not a retention leak; what it broke is
    #: the *proof*, because ``recipient_candidates IS NULL`` came back false on a row that
    #: had been purged, and that predicate is what an erasure proof and §6.6's data
    #: inventory are built from.
    recipient_candidates: Mapped[list[dict[str, Any]] | None] = mapped_column(
        sa.JSON(none_as_null=True), nullable=True
    )
    identity_expires_at: Mapped[datetime] = mapped_column(UtcDateTime, nullable=False, index=True)
    identity_purged_at: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)

    # -- occasion date: DAY AND MONTH ONLY. There is no year column. ----------
    event_day: Mapped[int | None] = mapped_column(sa.SmallInteger, nullable=True)
    event_month: Mapped[int | None] = mapped_column(sa.SmallInteger, nullable=True)

    order: Mapped[OrderRow] = relationship(back_populates="brief", lazy="raise")

    @property
    def is_identity_purged(self) -> bool:
        """True once the 90-day identity clock has been run by the purge job.

        This reads the AUDIT COLUMN alone, and it used to also treat a null display name as
        proof. That second signal was sound while every brief had a name — an absent one
        could only mean the sweep had been through — and it stopped being sound the day the
        bring-your-own-lyrics path shipped, because those orders never had a name to purge.
        Left as it was, every one of them would have reported itself to the admin console,
        and to any erasure proof built on this property, as lawfully erased personal data
        that had in fact never been collected.

        Nothing is lost by narrowing it. ``_purge_brief_identities`` nulls the six identity
        columns and stamps ``identity_purged_at`` in ONE statement, so the audit column is
        set for every row the sweep has ever touched.
        """
        return self.identity_purged_at is not None

    @property
    def is_note_purged(self) -> bool:
        return self.note_purged_at is not None
