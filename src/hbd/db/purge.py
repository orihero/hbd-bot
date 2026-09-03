"""The FIL-7 purge job. A legal requirement, not a housekeeping nicety.

Four independent clocks run here, and they are independent on purpose — collapsing them
into one sweep would be simpler and would also be wrong, because they protect different
things and expire at different times:

======================  ==============================================  ==========
What                    Where                                           Default
======================  ==============================================  ==========
Delivered paid audio    ``assets`` rows, deleted outright               12 months
Free-tier output        ``assets`` rows, deleted outright               30 days
Free-text brief         ``briefs.note`` + ``briefs.approved_lyrics``,   30 days
                        nulled in place
Free-text transcript    ``generation_attempts.stt_transcript``,         30 days
                        nulled in place
Recipient identity      ``briefs`` name columns, nulled in place        90 days
Recipient identity      ``generation_attempts`` name text, nulled       90 days
Abandoned drafts        ``orders`` in ``DRAFT``, deleted outright       14 days
Operator free text      ``admin_audit_log.reason_text``, nulled         90 days
Audited actions         ``admin_audit_log`` rows, deleted outright      730 days
Admin sessions          ``admin_sessions`` rows, deleted outright       12 h
Sweep records           ``purge_runs``, deleted outright                12 months
======================  ==============================================  ==========

The last row is not customer data — it is this job's own audit trail, swept by the same
run so the bookkeeping cannot outgrow the thing it books. The three admin rows above it
live in :mod:`hbd.db.purge_admin`, because they are the only sweeps that have to know
about Postgres privileges: §12.4 revokes ``UPDATE``/``DELETE`` on ``admin_audit_log`` from
the application role, so on a two-role deployment they go through the ``SECURITY DEFINER``
functions migration 0007 installs.

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

**The song transcript is free text, not just a name.** ``stt_transcript`` was sized for an
isolated name chunk; inpainting is enterprise-gated, so verification hears the whole track
and the column holds the whole lyric — which, since the wizard's preview step, may be words
the customer wrote about a named third party. Those words live on the 30-day clock in
``briefs.approved_lyrics``, so the copy of them here gets the same clock rather than the
90-day identity one; leaving it on identity alone would have retained the customer's free
text for sixty days past the schedule the privacy notice states. The identity sweep clears
it as well, for the same "whichever fires first wins" reason as the lyric below.

**The approved lyric is nulled by BOTH brief sweeps, and that is not a duplicate.** It is
free text, so the 30-day note clock owns it; but it also carries the recipient's identity —
``LyricDraft.name_display`` is the display name and the name-hook section sings it verbatim
— and ``RetentionPolicy`` accepts any positive periods, so a deployment with
``brief_text_days`` longer than ``recipient_identity_days`` would otherwise leave the name
on disk past its own clock while every other identity column had already been cleared. The
identity sweep therefore clears it too, and whichever clock fires first wins.

Every sweep is bounded by ``batch_size``. A first run against a year of unpurged data must
not take a lock on the whole ``assets`` table.
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta
from pathlib import PurePosixPath
from typing import Any, Final
from uuid import UUID

import sqlalchemy as sa
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from hbd.contracts import OrderState, Result
from hbd.db.credits import settle_stale_debits
from hbd.db.guard import run_guarded
from hbd.db.models.admin_audit import AdminAuditRow
from hbd.db.models.admin_session import AdminSessionRow
from hbd.db.models.asset import AssetRow
from hbd.db.models.brief import BriefRow
from hbd.db.models.generation_attempt import GenerationAttemptRow
from hbd.db.models.name_record import NameRecordRow
from hbd.db.models.order import OrderRow
from hbd.db.models.purge_run import PurgeRunRow
from hbd.db.purge_admin import (
    admin_sessions_due,
    audit_reasons_due,
    audit_rows_due,
    pin_audit_head,
    purge_admin_sessions,
    purge_audit_log,
    purge_audit_reasons,
)
from hbd.db.retention import DEFAULT_RETENTION_POLICY, RetentionPolicy
from hbd.entitlements import DEFAULT_ENTITLEMENT_POLICY, EntitlementPolicy
from hbd.logging import get_logger
from hbd.storage import archive_key

__all__ = [
    "PurgeReport",
    "purge_expired",
    "DEFAULT_PURGE_BATCH_SIZE",
    "PURGE_RUN_RETENTION_DAYS",
    "rows_past_expiry_statements",
]

_log = get_logger(__name__)

#: Rows touched per table per run. Sized so a sweep stays well inside a statement timeout.
DEFAULT_PURGE_BATCH_SIZE: int = 500

#: How long the sweep's own records are kept (admin plan §12.5). Not a ``RetentionPolicy``
#: field on purpose: the policy holds periods for CUSTOMER data, every one of which is a
#: published legal commitment an operator may tune. This one bounds an internal counter
#: table that holds no personal data, so making it configurable would add a knob whose only
#: possible effect is to lose operational history.
PURGE_RUN_RETENTION_DAYS: Final[int] = 365


class PurgeReport(BaseModel):
    """What one purge run did. Logged, and returned so a scheduler can alert on it."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    ran_at: datetime
    #: The bound every sweep below ran under. Carried on the report rather than left with
    #: the caller because ``has_work_remaining`` cannot be answered without it.
    batch_size: int = Field(default=DEFAULT_PURGE_BATCH_SIZE, gt=0)
    assets_deleted: int = Field(default=0, ge=0)
    #: Object-store keys whose rows are gone. The CALLER deletes these objects.
    storage_keys: tuple[str, ...] = ()
    brief_notes_purged: int = Field(default=0, ge=0)
    brief_identities_purged: int = Field(default=0, ge=0)
    attempt_identities_purged: int = Field(default=0, ge=0)
    attempt_transcripts_purged: int = Field(default=0, ge=0)
    name_records_deleted: int = Field(default=0, ge=0)
    abandoned_orders_deleted: int = Field(default=0, ge=0)
    #: ``admin_audit_log.reason_text`` nulled at 90 days — the operator's own free text, the
    #: one column in that table an operator can type a customer's name into.
    audit_reasons_purged: int = Field(default=0, ge=0)
    #: ``admin_audit_log`` rows deleted at 730 days. Every deletion writes a chain anchor.
    audit_rows_deleted: int = Field(default=0, ge=0)
    #: ``admin_sessions`` past their absolute cap. Token digests, CSRF tokens and operator
    #: IP addresses; the sweep existed and had no caller until this pass.
    admin_sessions_deleted: int = Field(default=0, ge=0)
    purge_runs_deleted: int = Field(default=0, ge=0)
    #: Open credit debits the sweep closed — refunded, or consumed when the kit was already
    #: rendered. Not a retention clock and not personal data; it rides this run because this
    #: is the transaction the worker already schedules. Deliberately NOT added to
    #: ``rows_past_expiry_statements``: that function answers "how far behind is the
    #: RETENTION schedule", which the panel renders as a legal backlog, and a stale debit is
    #: not one.
    stale_debits_settled: int = Field(default=0, ge=0)

    @property
    def per_sweep_counts(self) -> tuple[int, ...]:
        """Every sweep's own count, unsummed. The order is the order they ran in."""
        return (
            self.assets_deleted,
            self.brief_notes_purged,
            self.brief_identities_purged,
            self.attempt_identities_purged,
            self.attempt_transcripts_purged,
            self.name_records_deleted,
            self.abandoned_orders_deleted,
            self.audit_reasons_purged,
            self.audit_rows_deleted,
            self.admin_sessions_deleted,
            self.purge_runs_deleted,
            self.stale_debits_settled,
        )

    @property
    def total_rows_affected(self) -> int:
        return sum(self.per_sweep_counts)

    @property
    def has_work_remaining(self) -> bool:
        """True when a sweep filled its batch, so the scheduler should run again soon.

        This used to be ``total_rows_affected > 0``, which is a different predicate wearing
        this one's docstring: it was true of every run that did any work at all and false
        the instant nothing was due. A nightly sweep that deleted three rows reported "more
        remaining" forever, and the panel's "run again" affordance would have been lit
        permanently — which is the same as not being there.

        A sweep is bounded by ``LIMIT batch_size``. The only evidence that more rows were
        due than one pass could take is a sweep that came back **full**, so that is what is
        asked. Each count is compared on its own: one saturated table means work remains
        even when every other clock had nothing due.
        """
        return any(count >= self.batch_size for count in self.per_sweep_counts)


async def purge_expired(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    now: datetime,
    policy: RetentionPolicy = DEFAULT_RETENTION_POLICY,
    entitlements: EntitlementPolicy = DEFAULT_ENTITLEMENT_POLICY,
    batch_size: int = DEFAULT_PURGE_BATCH_SIZE,
) -> Result[PurgeReport]:
    """Run every retention clock once, and close every debit nobody settled. Never raises.

    ``now`` is injected rather than read from the system clock so a test can advance time
    thirteen months without waiting thirteen months.

    ``entitlements`` supplies the settlement grace, and it is DEFAULTED rather than required
    because the caller on the cron (``hbd.runtime.retention_job``) predates it and passes
    only ``policy=``. The default is derived from the SHIPPED queue ladder — see
    ``hbd.entitlements.derive_settlement_grace_s`` — so a deployment that lengthens
    ``HBD_QUEUE_JOB_TIMEOUT_S`` (or sets ``HBD_SETTLEMENT_GRACE_S``) moves the ledger's
    in-flight window, which ``AppContainer`` resolves from ``Settings``, without moving this
    one. Passing ``entitlements=resolve_entitlement_policy(settings)`` at that call site is
    still the tidier wiring.

    **It is no longer a correctness gap, and that is deliberate rather than lucky.** A grace
    shorter than the deployment's own retry ladder used to let the sweep refund an order that
    was still rendering — the customer then kept the credit and got the song. The selection
    in ``credit_sql.stale_debits`` now requires the ORDERS ROW to have been quiet for the
    grace as well as the debit, and every stage transition stamps ``orders.updated_at``
    (``repository._set_order_state``), so a live job is visible as live whatever number this
    parameter carries. A short grace can now only make the sweep tidy up sooner than
    necessary, never take a credit back from a job that is about to deliver.
    """
    return await run_guarded(
        "purge_expired",
        lambda: _purge(
            session_factory,
            now=now,
            policy=policy,
            entitlements=entitlements,
            batch_size=batch_size,
        ),
        now=now.isoformat(),
    )


async def _purge(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    now: datetime,
    policy: RetentionPolicy,
    entitlements: EntitlementPolicy,
    batch_size: int,
) -> PurgeReport:
    async with session_factory.begin() as session:
        storage_keys, assets_deleted = await _purge_assets(session, now=now, limit=batch_size)
        notes = await _purge_brief_notes(session, now=now, limit=batch_size)
        identities = await _purge_brief_identities(session, now=now, limit=batch_size)
        attempts = await _purge_attempt_identities(session, now=now, limit=batch_size)
        transcripts = await _purge_attempt_transcripts(session, now=now, limit=batch_size)
        names = await _purge_name_records(session, now=now, limit=batch_size)
        drafts = await _purge_abandoned_orders(
            session, cutoff=policy.abandoned_draft_cutoff(now), limit=batch_size
        )
        # The admin panel's own three clocks. They run before the anchor is pinned, so a
        # truncation this run made is recorded below the head this run records.
        audit_reasons = await purge_audit_reasons(session, now=now, limit=batch_size)
        audit_rows = await purge_audit_log(session, now=now, limit=batch_size)
        admin_sessions = await purge_admin_sessions(session, now=now, limit=batch_size)
        await pin_audit_head(session, now=now)
        runs = await _purge_purge_runs(
            session, cutoff=now - timedelta(days=PURGE_RUN_RETENTION_DAYS), limit=batch_size
        )
        # Last, and inside the same transaction: it writes ledger rows rather than deleting
        # anything, so a purge that fails half way must take these back with it.
        debits = await settle_stale_debits(session, now=now, limit=batch_size, policy=entitlements)

    report = PurgeReport(
        ran_at=now,
        batch_size=batch_size,
        assets_deleted=assets_deleted,
        storage_keys=storage_keys,
        brief_notes_purged=notes,
        brief_identities_purged=identities,
        attempt_identities_purged=attempts,
        attempt_transcripts_purged=transcripts,
        name_records_deleted=names,
        abandoned_orders_deleted=drafts,
        audit_reasons_purged=audit_reasons,
        audit_rows_deleted=audit_rows,
        admin_sessions_deleted=admin_sessions,
        purge_runs_deleted=runs,
        stale_debits_settled=debits,
    )
    # A purge that runs and does nothing is as important to see as one that deletes 40k
    # rows: silence here is indistinguishable from a scheduler that stopped firing.
    # The keys themselves are deliberately NOT logged — an object key is the only thing
    # standing between a signed URL and someone else's birthday song.
    summary = report.model_dump(mode="json", exclude={"storage_keys"})
    _log.info("retention purge complete", extra={**summary, "storage_key_count": len(storage_keys)})
    return report


# ---------------------------------------------------------------------------
# The predicates, named once
# ---------------------------------------------------------------------------
# Each sweep below and :func:`rows_past_expiry_statements` ask the SAME question, one with
# a ``LIMIT`` and one with a ``COUNT``. Writing that question twice is how the panel comes
# to report a backlog the job does not sweep — or, worse, reports none while rows rot — so
# it is written once, here, and both callers read it from the same place.
def _assets_due(now: datetime) -> sa.ColumnElement[bool]:
    return AssetRow.expires_at <= now


def _brief_notes_due(now: datetime) -> sa.ColumnElement[bool]:
    return sa.and_(
        BriefRow.note_expires_at <= now,
        sa.or_(BriefRow.note.is_not(None), BriefRow.approved_lyrics.is_not(None)),
    )


def _brief_identities_due(now: datetime) -> sa.ColumnElement[bool]:
    return sa.and_(
        BriefRow.identity_expires_at <= now,
        BriefRow.recipient_name_display.is_not(None),
    )


def _attempt_identities_due(now: datetime) -> sa.ColumnElement[bool]:
    return sa.and_(
        GenerationAttemptRow.identity_expires_at <= now,
        GenerationAttemptRow.identity_purged_at.is_(None),
        sa.or_(
            GenerationAttemptRow.name_candidate_text.is_not(None),
            GenerationAttemptRow.stt_transcript.is_not(None),
        ),
    )


def _attempt_transcripts_due(now: datetime) -> sa.ColumnElement[bool]:
    return sa.and_(
        GenerationAttemptRow.text_expires_at <= now,
        GenerationAttemptRow.text_purged_at.is_(None),
        GenerationAttemptRow.stt_transcript.is_not(None),
    )


def _name_records_due(now: datetime) -> sa.ColumnElement[bool]:
    return sa.and_(NameRecordRow.expires_at.is_not(None), NameRecordRow.expires_at <= now)


def _abandoned_orders_due(cutoff: datetime) -> sa.ColumnElement[bool]:
    return sa.and_(OrderRow.state == OrderState.DRAFT, OrderRow.created_at <= cutoff)


def _purge_runs_due(cutoff: datetime) -> sa.ColumnElement[bool]:
    return PurgeRunRow.ran_at <= cutoff


def rows_past_expiry_statements(
    *,
    now: datetime,
    policy: RetentionPolicy = DEFAULT_RETENTION_POLICY,
) -> tuple[tuple[str, sa.Select[tuple[int]]], ...]:
    """``(report field name, COUNT statement)`` for every clock, unbounded by ``batch_size``.

    This is what ``GET /api/retention``'s ``rowsPastExpiry`` is built from, and it is the
    number an operator actually wants: ``has_work_remaining`` only says "a batch came back
    full", which answers *whether* to run again but never *how far behind* the sweep is.

    The keys are ``PurgeReport`` field names so a caller can line the backlog up against
    the last run's counts without a translation table in between.
    """
    return (
        ("assets_deleted", _count_of(AssetRow, _assets_due(now))),
        ("brief_notes_purged", _count_of(BriefRow, _brief_notes_due(now))),
        ("brief_identities_purged", _count_of(BriefRow, _brief_identities_due(now))),
        (
            "attempt_identities_purged",
            _count_of(GenerationAttemptRow, _attempt_identities_due(now)),
        ),
        (
            "attempt_transcripts_purged",
            _count_of(GenerationAttemptRow, _attempt_transcripts_due(now)),
        ),
        ("name_records_deleted", _count_of(NameRecordRow, _name_records_due(now))),
        (
            "abandoned_orders_deleted",
            _count_of(OrderRow, _abandoned_orders_due(policy.abandoned_draft_cutoff(now))),
        ),
        ("audit_reasons_purged", _count_of(AdminAuditRow, audit_reasons_due(now))),
        ("audit_rows_deleted", _count_of(AdminAuditRow, audit_rows_due(now))),
        ("admin_sessions_deleted", _count_of(AdminSessionRow, admin_sessions_due(now))),
        (
            "purge_runs_deleted",
            _count_of(PurgeRunRow, _purge_runs_due(now - timedelta(days=PURGE_RUN_RETENTION_DAYS))),
        ),
    )


def _count_of(model: type[Any], predicate: sa.ColumnElement[bool]) -> sa.Select[tuple[int]]:
    return sa.select(sa.func.count()).select_from(model).where(predicate)


async def _ids_due(session: AsyncSession, statement: sa.Select[tuple[UUID]]) -> list[UUID]:
    """Materialise a bounded id list. Selecting ids first keeps the DELETE index-driven."""
    return list((await session.execute(statement)).scalars().all())


async def _purge_assets(
    session: AsyncSession, *, now: datetime, limit: int
) -> tuple[tuple[str, ...], int]:
    """Delete expired asset rows, returning the storage keys the caller must clean up.

    Rows written since ``repository._replace_assets`` learned to record ``storage_key``
    carry the key the archive actually used. Rows written before it do not, and deleting
    them was how archived audio outlived its retention clock: the row was the only record
    of where the bytes were, and it went away without saying. For those the key is
    RECONSTRUCTED from the two columns that do survive — ``order_id`` and ``path`` — through
    the same :func:`hbd.storage.archive_key` the ``put`` used, so the historical archive is
    reachable too rather than only the archive from here on.

    ``Path(path).name`` is validated before it is used. A stored path is data, not code
    (admin plan rule 9), and this function's output is handed straight to an object store's
    delete; a filename carrying a slash or a traversal segment would turn a retention sweep
    into a delete primitive aimed at whatever the caller's key namespace can address.

    Caveat worth knowing at the reading end: a reconstructed key is a well-founded GUESS
    that an object exists, not a record that one does. Archival is best effort, so a
    legacy row may name bytes that were never written.
    """
    rows = (
        await session.execute(
            sa.select(AssetRow.id, AssetRow.storage_key, AssetRow.order_id, AssetRow.path)
            .where(_assets_due(now))
            .order_by(AssetRow.expires_at)
            .limit(limit)
        )
    ).all()
    if not rows:
        return (), 0
    asset_ids = [row_id for row_id, _, _, _ in rows]
    keys = tuple(
        key
        for _, stored, order_id, path in rows
        if (key := stored or _legacy_key(order_id, path)) is not None
    )
    await session.execute(sa.delete(AssetRow).where(AssetRow.id.in_(asset_ids)))
    return keys, len(asset_ids)


#: What a filename written by ``pipeline.assets`` may look like: ``song.mp3``,
#: ``greeting-1.ogg``, ``lyrics.txt``. Deliberately narrow — this is a read of untrusted
#: stored data whose result becomes an object-store key.
_ARCHIVED_FILENAME = re.compile(r"^[A-Za-z0-9._-]{1,128}$")


def _legacy_key(order_id: UUID, path: str) -> str | None:
    """The archive key for a row written before ``storage_key`` was recorded, or ``None``.

    ``None`` — rather than a best-effort key — whenever the filename is not a shape the
    pipeline produces. An unrecognised name means the reconstruction's premise does not
    hold, and a purge that reports "no key" is recoverable where one that reports a wrong
    key is a delete aimed somewhere nobody chose.
    """
    filename = PurePosixPath(path).name
    if not _ARCHIVED_FILENAME.match(filename):
        return None
    return archive_key(order_id, filename)


async def _purge_brief_notes(session: AsyncSession, *, now: datetime, limit: int) -> int:
    """Clear the recipient's free-text facts — the note AND the approved lyric.

    The predicate is an ``OR`` because a brief may carry only one of the two: a customer
    who skipped the note but approved a lyric must still be swept, and the lyric is free
    text about a real person exactly as the note is.

    **Idempotency rests on the two columns being nulled in the same statement.** Unlike
    :func:`_purge_attempt_identities` this sweep has no ``note_purged_at IS NULL`` guard; a
    purged row is skipped on the next run only because the ``OR`` no longer matches. Nulling
    one column and not the other would make the nightly job re-select the same rows forever.
    """
    due = await _ids_due(
        session,
        sa.select(BriefRow.id)
        .where(_brief_notes_due(now))
        .order_by(BriefRow.note_expires_at)
        .limit(limit),
    )
    if not due:
        return 0
    await session.execute(
        sa.update(BriefRow)
        .where(BriefRow.id.in_(due))
        .values(note=None, approved_lyrics=None, note_purged_at=now)
    )
    return len(due)


async def _purge_brief_identities(session: AsyncSession, *, now: datetime, limit: int) -> int:
    """Clear the recipient's name, script and candidate orthographies.

    ``identity_purged_at`` is set so the row can prove it was purged on schedule. An
    absent name and an absent audit trail look identical, and only one of them is
    defensible to a regulator.

    ``approved_lyrics`` is nulled here as well as in :func:`_purge_brief_notes`. The lyric
    names the recipient in its hook, so it must not outlive the identity clock under a
    policy whose note clock is the longer of the two. This sweep does not stamp
    ``note_purged_at``: the note clock has not necessarily run, and the audit column must
    keep meaning "the note sweep visited this row".
    """
    due = await _ids_due(
        session,
        sa.select(BriefRow.id)
        .where(_brief_identities_due(now))
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
            approved_lyrics=None,
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
        .where(_attempt_identities_due(now))
        .order_by(GenerationAttemptRow.identity_expires_at)
        .limit(limit),
    )
    if not due:
        return 0
    await session.execute(
        sa.update(GenerationAttemptRow)
        .where(GenerationAttemptRow.id.in_(due))
        .values(
            name_candidate_text=None,
            stt_transcript=None,
            identity_purged_at=now,
            # The text clock owns ``stt_transcript``, and this sweep is nulling it: stamping
            # only ``identity_purged_at`` left the transcript deleted with no proof of when.
            # That is the backlog case — every historical row on the first run of a system
            # whose 90-day identity clock has already passed — so the transcript sweep never
            # reaches it (its predicate needs ``stt_transcript IS NOT NULL``) and the column
            # stays NULL forever. The data goes either way; only the audit trail was lost.
            text_purged_at=now,
        )
    )
    return len(due)


async def _purge_attempt_transcripts(session: AsyncSession, *, now: datetime, limit: int) -> int:
    """Null the song transcript on render attempts, on the free-text clock.

    Separate from :func:`_purge_attempt_identities` because it runs sixty days earlier and
    clears a different thing: the identity sweep is about the recipient's NAME, this one is
    about the words of the song, which the customer may have written themselves. Keeping
    them apart is what lets the name text stay long enough to tune the candidate ladder
    while the free text goes when the brief's free text goes.
    """
    due = await _ids_due(
        session,
        sa.select(GenerationAttemptRow.id)
        .where(_attempt_transcripts_due(now))
        .order_by(GenerationAttemptRow.text_expires_at)
        .limit(limit),
    )
    if not due:
        return 0
    await session.execute(
        sa.update(GenerationAttemptRow)
        .where(GenerationAttemptRow.id.in_(due))
        .values(stt_transcript=None, text_purged_at=now)
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
        .where(_name_records_due(now))
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
        .where(_abandoned_orders_due(cutoff))
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


async def _purge_purge_runs(session: AsyncSession, *, cutoff: datetime, limit: int) -> int:
    """Delete sweep records older than ``cutoff``. The bookkeeping must not outgrow the data.

    A table written once an hour forever is a table that eventually costs more than the
    rows it accounts for, so the sweep sweeps itself. It is the LAST sweep in the run on
    purpose: the count it produces belongs to the report of the run that produced it, and
    running it first would delete rows that the current run is about to be judged against.

    The row this run is about to write does not exist yet — the job writes it after
    ``purge_expired`` returns — so there is no self-deletion hazard to guard against, and
    ``cutoff`` is a year in the past regardless.
    """
    due = await _ids_due(
        session,
        sa.select(PurgeRunRow.id)
        .where(_purge_runs_due(cutoff))
        .order_by(PurgeRunRow.ran_at)
        .limit(limit),
    )
    if not due:
        return 0
    await session.execute(sa.delete(PurgeRunRow).where(PurgeRunRow.id.in_(due)))
    return len(due)
