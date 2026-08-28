"""``name_records`` — read and write the pronunciation dictionary.

The point of the table is that a name we have already got right is never re-derived, and
never re-verified against a paid STT call. ``lookup`` is therefore the first thing the name
subsystem asks and the cheapest answer it can get.

One name legitimately has more than one correct stress pattern (a Russian ``Ирина`` and an
Uzbek ``Irina`` are not the same word, and even within one language two families will
disagree), so **variants are rows, not columns**. ``lookup`` returns them ordered by
``variant_ordinal`` and a caller that receives more than one asks the user which they meant
rather than picking for them.

Retention is provenance-dependent, which is why ``upsert`` takes ``expires_at`` from the
caller instead of stamping one itself: a curated entry is a licensed work product that
never expires, a ``user_confirmed`` entry is a real person's name on the 90-day identity
clock. Getting that backwards either erodes the moat or retains personal data unlawfully.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from hbd.contracts import Language, Result, Script
from hbd.db.base import utc_now
from hbd.db.enums import NameSource
from hbd.db.guard import run_guarded
from hbd.db.models.name_record import NameRecordRow

__all__ = ["NameRecordRepository", "NameRecordDraft"]


@dataclass(frozen=True, slots=True)
class NameRecordDraft:
    """A dictionary entry on its way in.

    Frozen, so ``upsert`` cannot alter what its caller handed it. ``expires_at`` is the
    caller's decision rather than something stamped here — see the module docstring on why
    provenance, not the clock, decides whether an entry expires at all.
    """

    grapheme: str
    grapheme_normalized: str
    language: Language
    script: Script
    display_form: str
    source: NameSource
    candidates: tuple[Mapping[str, Any], ...] = ()
    ipa: str | None = None
    stressed_form: str | None = None
    syllables: str | None = None
    source_reference: str | None = None
    licence: str | None = None
    contributor: str | None = None
    confidence: float = 0.0
    variant_ordinal: int = 0
    expires_at: datetime | None = None


class NameRecordRepository:
    """Lookup, upsert and outcome-recording for the pronunciation dictionary."""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        *,
        clock: Callable[[], datetime] = utc_now,
    ) -> None:
        self._sessions = session_factory
        self._clock = clock

    async def lookup(
        self, lookup_key: str, language: Language
    ) -> Result[tuple[NameRecordRow, ...]]:
        """Every known variant of one name in one language, ordered by variant."""
        return await run_guarded(
            "name_lookup",
            lambda: self._lookup(lookup_key, language),
            lookup_key=lookup_key,
            language=str(language),
        )

    async def upsert(self, draft: NameRecordDraft) -> Result[UUID]:
        """Insert the entry, or update the existing variant in place. Returns its id."""
        return await run_guarded(
            "name_upsert",
            lambda: self._upsert(draft),
            lookup_key=draft.grapheme_normalized,
            source=str(draft.source),
        )

    async def record_outcome(
        self, record_id: UUID, *, is_verified: bool, is_correction: bool = False
    ) -> Result[None]:
        """Count one render of this name and whether it survived verification.

        Incremented in SQL rather than read-modify-written in Python: two workers
        rendering the same popular name concurrently would otherwise lose a count each
        time, and the success rate this feeds is the number the ranking is tuned on.
        """
        return await run_guarded(
            "name_record_outcome",
            lambda: self._record_outcome(record_id, is_verified, is_correction),
            record_id=str(record_id),
        )

    # -- implementations ----------------------------------------------------
    async def _lookup(self, lookup_key: str, language: Language) -> tuple[NameRecordRow, ...]:
        async with self._sessions.begin() as session:
            rows: Sequence[NameRecordRow] = (
                (
                    await session.execute(
                        sa.select(NameRecordRow)
                        .where(
                            NameRecordRow.grapheme_normalized == lookup_key,
                            NameRecordRow.language == language,
                        )
                        .order_by(NameRecordRow.variant_ordinal)
                    )
                )
                .scalars()
                .all()
            )
            return tuple(rows)

    async def _upsert(self, draft: NameRecordDraft) -> UUID:
        now = self._clock()
        async with self._sessions.begin() as session:
            existing = (
                await session.execute(
                    sa.select(NameRecordRow).where(
                        NameRecordRow.grapheme_normalized == draft.grapheme_normalized,
                        NameRecordRow.language == draft.language,
                        NameRecordRow.variant_ordinal == draft.variant_ordinal,
                    )
                )
            ).scalar_one_or_none()
            if existing is not None:
                _apply_draft(existing, draft, now=now)
                return existing.id
            row = NameRecordRow(id=uuid4(), created_at=now, updated_at=now)
            _apply_draft(row, draft, now=now)
            session.add(row)
            return row.id

    async def _record_outcome(
        self, record_id: UUID, is_verified: bool, is_correction: bool
    ) -> None:
        async with self._sessions.begin() as session:
            await session.execute(
                sa.update(NameRecordRow)
                .where(NameRecordRow.id == record_id)
                .values(
                    usage_count=NameRecordRow.usage_count + 1,
                    success_count=NameRecordRow.success_count + (1 if is_verified else 0),
                    correction_count=NameRecordRow.correction_count + (1 if is_correction else 0),
                    verified_at=self._clock() if is_verified else NameRecordRow.verified_at,
                )
            )


def _apply_draft(row: NameRecordRow, draft: NameRecordDraft, *, now: datetime) -> None:
    """Copy a draft onto a row. The only place a ``name_records`` row is written."""
    row.grapheme = draft.grapheme
    row.grapheme_normalized = draft.grapheme_normalized
    row.language = draft.language
    row.script = draft.script
    row.variant_ordinal = draft.variant_ordinal
    row.display_form = draft.display_form
    row.candidates = [dict(candidate) for candidate in draft.candidates]
    row.ipa = draft.ipa
    row.stressed_form = draft.stressed_form
    row.syllables = draft.syllables
    row.source = draft.source
    row.source_reference = draft.source_reference
    row.licence = draft.licence
    row.contributor = draft.contributor
    row.confidence = draft.confidence
    row.expires_at = draft.expires_at
    row.updated_at = now
