"""The FIL-7 purge job. A legal requirement, not a housekeeping nicety.

Four independent clocks run here, and they are independent on purpose — collapsing them
into one sweep would be simpler and would also be wrong, because they protect different
things and expire at different times:

======================  ==========================================  ==========
What                    Where                                       Default
======================  ==========================================  ==========
Delivered paid audio    ``assets`` rows, deleted outright           12 months
Free-tier output        ``assets`` rows, deleted outright           30 days
Free-text brief         ``briefs.note``, nulled in place            30 days
Recipient identity      ``briefs`` name columns, nulled in place    90 days
Recipient identity      ``generation_attempts`` name text, nulled   90 days
Abandoned drafts        ``orders`` in ``DRAFT``, deleted outright   14 days
======================  ==========================================  ==========

Two design choices worth stating, because both look like mistakes until you see why:

**Identity is nulled, not deleted.** Deleting the brief row would take the order's
occasion and genre with it, and those are not personal data — they are the operating
record of a transaction the tax authority expects to survive (SoW DAT-3). Nulling the
name columns is what makes "the tax record and the personal-data record are separable at
the schema level" true in practice rather than in a design document.

**Assets are deleted, and their storage keys are returned rather than deleted.** This
module owns rows; it does not own an object store, and it must not silently half-succeed
by deleting bytes and then failing to commit the row deletion. The caller gets the keys
back in :class:`PurgeReport` and deletes the objects after the transaction commits, so a
crash leaves orphaned bytes (recoverable, sweepable) rather than a row pointing at bytes
that no longer exist (a broken re-send that looks like data corruption).

Every sweep is bounded by ``batch_size``. A first run against a year of unpurged data must
not take a lock on the whole ``assets`` table.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

import sqlalchemy as sa
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from hbd.contracts import OrderState, Result
from hbd.db.guard import run_guarded
from hbd.db.models.asset import AssetRow
from hbd.db.models.brief import BriefRow
from hbd.db.models.generation_attempt import GenerationAttemptRow
from hbd.db.models.name_record import NameRecordRow
from hbd.db.models.order import OrderRow
from hbd.db.retention import DEFAULT_RETENTION_POLICY, RetentionPolicy
from hbd.logging import get_logger

__all__ = ["PurgeReport", "purge_expired", "DEFAULT_PURGE_BATCH_SIZE"]

_log = get_logger(__name__)

#: Rows touched per table per run. Sized so a sweep stays well inside a statement timeout.
DEFAULT_PURGE_BATCH_SIZE: int = 500


class PurgeReport(BaseModel):
    """What one purge run did. Logged, and returned so a scheduler can alert on it."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    ran_at: datetime
    assets_deleted: int = Field(default=0, ge=0)
    #: Object-store keys whose rows are gone. The CALLER deletes these objects.
    storage_keys: tuple[str, ...] = ()
    brief_notes_purged: int = Field(default=0, ge=0)
    brief_identities_purged: int = Field(default=0, ge=0)
    attempt_identities_purged: int = Field(default=0, ge=0)
    name_records_deleted: int = Field(default=0, ge=0)
    abandoned_orders_deleted: int = Field(default=0, ge=0)

    @property
    def total_rows_affected(self) -> int:
        return (
            self.assets_deleted
            + self.brief_notes_purged
            + self.brief_identities_purged
            + self.attempt_identities_purged
            + self.name_records_deleted
            + self.abandoned_orders_deleted
        )

    @property
    def has_work_remaining(self) -> bool:
        """True when a sweep filled its batch, so the scheduler should run again soon."""
        return self.total_rows_affected > 0


async def purge_expired(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    now: datetime,
    policy: RetentionPolicy = DEFAULT_RETENTION_POLICY,
    batch_size: int = DEFAULT_PURGE_BATCH_SIZE,
) -> Result[PurgeReport]:
    """Run every retention clock once. Never raises; returns a typed ``Err`` on failure.

    ``now`` is injected rather than read from the system clock so a test can advance time
    thirteen months without waiting thirteen months.
    """
    return await run_guarded(
        "purge_expired",
        lambda: _purge(session_factory, now=now, policy=policy, batch_size=batch_size),
        now=now.isoformat(),
    )


async def _purge(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    now: datetime,
    policy: RetentionPolicy,
    batch_size: int,
) -> PurgeReport:
    async with session_factory.begin() as session:
        storage_keys, assets_deleted = await _purge_assets(session, now=now, limit=batch_size)
        notes = await _purge_brief_notes(session, now=now, limit=batch_size)
        identities = await _purge_brief_identities(session, now=now, limit=batch_size)
        attempts = await _purge_attempt_identities(session, now=now, limit=batch_size)
        names = await _purge_name_records(session, now=now, limit=batch_size)
        drafts = await _purge_abandoned_orders(
            session, cutoff=policy.abandoned_draft_cutoff(now), limit=batch_size
        )

    report = PurgeReport(
        ran_at=now,
        assets_deleted=assets_deleted,
        storage_keys=storage_keys,
        brief_notes_purged=notes,
        brief_identities_purged=identities,
        attempt_identities_purged=attempts,
        name_records_deleted=names,
        abandoned_orders_deleted=drafts,
    )
    # A purge that runs and does nothing is as important to see as one that deletes 40k
    # rows: silence here is indistinguishable from a scheduler that stopped firing.
    # The keys themselves are deliberately NOT logged — an object key is the only thing
    # standing between a signed URL and someone else's birthday song.
    summary = report.model_dump(mode="json", exclude={"storage_keys"})
    _log.info("retention purge complete", extra={**summary, "storage_key_count": len(storage_keys)})
    return report


async def _ids_due(session: AsyncSession, statement: sa.Select[tuple[UUID]]) -> list[UUID]:
    """Materialise a bounded id list. Selecting ids first keeps the DELETE index-driven."""
    return list((await session.execute(statement)).scalars().all())


async def _purge_assets(
    session: AsyncSession, *, now: datetime, limit: int
) -> tuple[tuple[str, ...], int]:
    """Delete expired asset rows, returning the storage keys the caller must clean up."""
    rows = (
        await session.execute(
            sa.select(AssetRow.id, AssetRow.storage_key)
            .where(AssetRow.expires_at <= now)
            .order_by(AssetRow.expires_at)
            .limit(limit)
        )
    ).all()
    if not rows:
        return (), 0
    asset_ids = [row_id for row_id, _ in rows]
    keys = tuple(key for _, key in rows if key)
    await session.execute(sa.delete(AssetRow).where(AssetRow.id.in_(asset_ids)))
    return keys, len(asset_ids)


async def _purge_brief_notes(session: AsyncSession, *, now: datetime, limit: int) -> int:
    """Clear the recipient's free-text facts. The structured answers stay."""
    due = await _ids_due(
        session,
        sa.select(BriefRow.id)
        .where(
            BriefRow.note_expires_at <= now,
            BriefRow.note.is_not(None),
        )
        .order_by(BriefRow.note_expires_at)
        .limit(limit),
    )
    if not due:
        return 0
    await session.execute(
        sa.update(BriefRow).where(BriefRow.id.in_(due)).values(note=None, note_purged_at=now)
    )
    return len(due)


async def _purge_brief_identities(session: AsyncSession, *, now: datetime, limit: int) -> int:
    """Clear the recipient's name, script and candidate orthographies.

    ``identity_purged_at`` is set so the row can prove it was purged on schedule. An
    absent name and an absent audit trail look identical, and only one of them is
    defensible to a regulator.
    """
    due = await _ids_due(
        session,
        sa.select(BriefRow.id)
        .where(
            BriefRow.identity_expires_at <= now,
            BriefRow.recipient_name_display.is_not(None),
        )
        .order_by(BriefRow.identity_expires_at)
        .limit(limit),
    )
    if not due:
        return 0
    await session.execute(
        sa.update(BriefRow)
        .where(BriefRow.id.in_(due))
        .values(
            recipient_name_raw=None,
            recipient_name_display=None,
            recipient_lookup_key=None,
            recipient_script=None,
            recipient_language=None,
            recipient_candidates=None,
            identity_purged_at=now,
        )
    )
    return len(due)


async def _purge_attempt_identities(session: AsyncSession, *, now: datetime, limit: int) -> int:
    """Null the name text on render attempts, keeping strategy, rank and verdict.

    This is the whole reason the tuning table survives a retention review: what is deleted
    is the person, and what remains is the measurement.
    """
    due = await _ids_due(
        session,
        sa.select(GenerationAttemptRow.id)
        .where(
            GenerationAttemptRow.identity_expires_at <= now,
            GenerationAttemptRow.identity_purged_at.is_(None),
            sa.or_(
                GenerationAttemptRow.name_candidate_text.is_not(None),
                GenerationAttemptRow.stt_transcript.is_not(None),
            ),
        )
        .order_by(GenerationAttemptRow.identity_expires_at)
        .limit(limit),
    )
    if not due:
        return 0
    await session.execute(
        sa.update(GenerationAttemptRow)
        .where(GenerationAttemptRow.id.in_(due))
        .values(name_candidate_text=None, stt_transcript=None, identity_purged_at=now)
    )
    return len(due)


async def _purge_name_records(session: AsyncSession, *, now: datetime, limit: int) -> int:
    """Delete expired dictionary entries.

    Only ``user_confirmed`` rows ever carry an ``expires_at``; a curated entry is a
    licensed work product with no personal data in it and no clock on it, and the
    ``IS NOT NULL`` guard is what keeps the moat from eroding.
    """
    due = await _ids_due(
        session,
        sa.select(NameRecordRow.id)
        .where(
            NameRecordRow.expires_at.is_not(None),
            NameRecordRow.expires_at <= now,
        )
        .order_by(NameRecordRow.expires_at)
        .limit(limit),
    )
    if not due:
        return 0
    await session.execute(sa.delete(NameRecordRow).where(NameRecordRow.id.in_(due)))
    return len(due)


async def _purge_abandoned_orders(session: AsyncSession, *, cutoff: datetime, limit: int) -> int:
    """Delete drafts the user never completed, with their brief and any part-built assets.

    The child rows are removed explicitly rather than left to ``ON DELETE CASCADE``: SQLite
    does not enforce foreign keys unless asked to, so a cascade that works in Postgres and
    silently does nothing in the test suite is exactly the divergence that lets a bug ship.

    Render attempts are detached, not deleted. They outlive their order on purpose — the
    tuning signal is the point of the table, and it must not evaporate on the first purge.
    """
    due = await _ids_due(
        session,
        sa.select(OrderRow.id)
        .where(
            OrderRow.state == OrderState.DRAFT,
            OrderRow.created_at <= cutoff,
        )
        .order_by(OrderRow.created_at)
        .limit(limit),
    )
    if not due:
        return 0
    await session.execute(
        sa.update(GenerationAttemptRow)
        .where(GenerationAttemptRow.order_id.in_(due))
        .values(order_id=None)
    )
    await session.execute(sa.delete(BriefRow).where(BriefRow.order_id.in_(due)))
    await session.execute(sa.delete(AssetRow).where(AssetRow.order_id.in_(due)))
    await session.execute(sa.delete(OrderRow).where(OrderRow.id.in_(due)))
    return len(due)
