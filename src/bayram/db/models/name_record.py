"""``name_records`` — the pronunciation dictionary. The moat.

One name legitimately has more than one correct stress pattern, so variants are rows, not
columns: uniqueness is ``(grapheme_normalized, language, variant_ordinal)`` and a caller
that gets two rows back asks the user which one they meant.

Retention is provenance-dependent. A curated entry is a work product with a licence and
never expires. A ``user_confirmed`` entry is a real person's name supplied by a real user,
so it carries the 90-day identity clock like any other recipient datum.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Final
from uuid import UUID, uuid4

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from bayram.contracts import MAX_CANDIDATE_CHARS, MAX_RECIPIENT_NAME_CHARS, Language, Script
from bayram.db.base import Base, TimestampMixin, UtcDateTime, enum_type
from bayram.db.enums import NameSource

__all__ = ["NameRecordRow", "IPA_LENGTH", "PROVENANCE_LENGTH"]

IPA_LENGTH: Final[int] = 160
PROVENANCE_LENGTH: Final[int] = 200
LOOKUP_KEY_LENGTH: Final[int] = 80


class NameRecordRow(TimestampMixin, Base):
    """One pronunciation of one name in one language."""

    __tablename__ = "name_records"
    __table_args__ = (
        sa.UniqueConstraint("grapheme_normalized", "language", "variant_ordinal"),
        sa.Index("ix_name_records_lookup", "grapheme_normalized", "language"),
    )

    id: Mapped[UUID] = mapped_column(sa.Uuid, primary_key=True, default=uuid4)

    #: As typed, byte-preserved.
    grapheme: Mapped[str] = mapped_column(sa.String(MAX_RECIPIENT_NAME_CHARS), nullable=False)
    #: Case-folded, mark-stripped, script-unified. The cache and dictionary key.
    grapheme_normalized: Mapped[str] = mapped_column(sa.String(LOOKUP_KEY_LENGTH), nullable=False)
    language: Mapped[Language] = mapped_column(enum_type(Language), nullable=False)
    script: Mapped[Script] = mapped_column(enum_type(Script), nullable=False)
    variant_ordinal: Mapped[int] = mapped_column(sa.Integer, nullable=False, default=0)

    #: Perfect U+02BB. This is what appears in message copy and on the lyric sheet.
    display_form: Mapped[str] = mapped_column(sa.String(MAX_RECIPIENT_NAME_CHARS), nullable=False)
    #: Ranked candidate orthographies as last built. Submitted to vendors, never shown.
    candidates: Mapped[list[dict[str, Any]]] = mapped_column(sa.JSON, nullable=False, default=list)

    ipa: Mapped[str | None] = mapped_column(sa.String(IPA_LENGTH), nullable=True)
    #: Uzbek stress is final-syllable; Russian must keep ё. Recorded, never ALL-CAPSed —
    #: capitals mean LOUDER to a music model, not stressed.
    stressed_form: Mapped[str | None] = mapped_column(sa.String(MAX_CANDIDATE_CHARS), nullable=True)
    syllables: Mapped[str | None] = mapped_column(sa.String(MAX_CANDIDATE_CHARS), nullable=True)

    source: Mapped[NameSource] = mapped_column(enum_type(NameSource), nullable=False)
    #: SoW FR-95: no entry may have an unknown source.
    source_reference: Mapped[str | None] = mapped_column(
        sa.String(PROVENANCE_LENGTH), nullable=True
    )
    licence: Mapped[str | None] = mapped_column(sa.String(PROVENANCE_LENGTH), nullable=True)
    contributor: Mapped[str | None] = mapped_column(sa.String(PROVENANCE_LENGTH), nullable=True)

    confidence: Mapped[float] = mapped_column(sa.Float, nullable=False, default=0.0)
    #: How the name subsystem learns: renders attempted, renders that passed STT, and
    #: times a human told us we got it wrong.
    usage_count: Mapped[int] = mapped_column(sa.Integer, nullable=False, default=0)
    success_count: Mapped[int] = mapped_column(sa.Integer, nullable=False, default=0)
    correction_count: Mapped[int] = mapped_column(sa.Integer, nullable=False, default=0)
    verified_at: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)

    #: Set only for ``NameSource.USER_CONFIRMED`` rows. ``None`` means "never expires".
    expires_at: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True, index=True)

    @property
    def success_rate(self) -> float:
        """Share of renders of this name that survived acoustic verification."""
        if self.usage_count <= 0:
            return 0.0
        return self.success_count / self.usage_count
