"""Wire models for ``GET /api/retention`` — what the sweeps did, and what is still due.

Three shapes here are policy rather than convenience.

**The backlog and the last run's counts are the same model.** ``rowsPastExpiry`` and each
run's ``counts`` are both :class:`SweepCounts`, keyed by ``PurgeReport``'s own field names,
so the panel can put "deleted last run" beside "due right now" per clock with no translation
table between them. The names come from
:func:`bayram.db.purge.rows_past_expiry_statements`, which is also what the sweep itself runs;
a second naming of the clocks here is how a dashboard comes to report a clean schedule over
rows nobody is deleting.

**Every field of :class:`SweepCounts` is required, and extra keys are refused.** A default
of ``0`` would turn a clock added to the sweep and forgotten here into "nothing is due" —
the one wrong answer this endpoint must never give — so drift fails loudly instead. It
cannot reach production silently either: ``test_retention_router`` asserts this model's
field set equals the statement set.

**Nothing is masked.** §12.2 gives RETENTION_READ as **M** to all four roles, and unlike
the audit log there is no cell-dependent column to withhold: ``purge_runs`` holds counts and
no personal data at all (see :mod:`bayram.db.models.purge_run`). The **M** here is "you may see
the operational record", not "you may see a redacted one".

**The storage numbers are never collapsed into one.** ``purge_expired`` hands keys back and
the job deletes the objects afterwards, so "handed over" and "confirmed gone" are produced
by two different components; a single "objects cleaned up" figure would make a leak
arithmetically invisible. :class:`StorageReconciliation` names the four states those two
numbers can be in, and it exists because ``keysReturned == 0`` is **two** different facts
today: nothing was due, or asset rows were deleted while no key was recorded for them. The
asset repository does not write ``assets.storage_key`` yet (Phase 2), so a sweep that
deletes asset rows legitimately returns zero keys — and that is
:attr:`StorageReconciliation.KEYS_UNRECORDED`, not a clean archive.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime
from enum import StrEnum
from typing import Final
from uuid import UUID

from bayram.admin.schemas.common import ApiModel
from bayram.db.admin.retention import RetentionOverview
from bayram.db.enums import PurgeTrigger
from bayram.db.models.purge_run import PurgeRunRow

__all__ = [
    "PurgeRunView",
    "RetentionResponse",
    "StorageReconciliation",
    "StorageTally",
    "SweepCounts",
    "to_response",
    "to_view",
]


class SweepCounts(ApiModel):
    """One number per retention clock, in the order the sweeps run.

    Used twice with two meanings: on a run it is what that sweep deleted, and at the top
    level it is what is due **right now**, counted live and unbounded by ``batch_size``.
    Same keys either way, deliberately.
    """

    assets_deleted: int
    brief_notes_purged: int
    brief_identities_purged: int
    attempt_identities_purged: int
    attempt_transcripts_purged: int
    name_records_deleted: int
    abandoned_orders_deleted: int
    audit_reasons_purged: int
    audit_rows_deleted: int
    admin_sessions_deleted: int
    purge_runs_deleted: int
    vendor_usage_deleted: int
    #: ``bot_membership_events`` past the 400-day cutoff (revision 0017). Required
    #: like every other field here: a default of 0 would report a growing churn log
    #: as nothing due, which is the one wrong answer this endpoint must never give.
    membership_events_deleted: int
    chat_bodies_purged: int = 0
    chat_messages_deleted: int = 0
    #: ``payme_rpc_log`` past the 90-day cutoff and TERMINAL UNPAID ``payment_intents``
    #: past the 400-day one (revision 0023). Defaulted like the two above so an older
    #: stored run, written before the payment rail existed, still projects onto this model.
    payme_rpc_rows_deleted: int = 0
    payment_intents_deleted: int = 0
    #: ``broadcast_recipients`` past the 400-day cutoff (revision 0024). Defaulted like the
    #: four above so a run stored before the broadcast tables existed still projects onto this
    #: model, and worth watching more than any of them: the table takes a row per account per
    #: campaign, so this is where a sweep falling behind becomes visible first.
    broadcast_recipients_deleted: int = 0

    @property
    def total(self) -> int:
        return sum(getattr(self, name) for name in type(self).model_fields)


class StorageReconciliation(StrEnum):
    """What the two storage numbers, read together, actually say about the bytes.

    A boolean would not do. ``keysDeleted == keysReturned`` is true of a run that cleaned up
    everything it was handed **and** of a run that was handed nothing, and those are opposite
    facts when asset rows were deleted in the same pass.
    """

    #: Keys were handed over and every one is confirmed gone.
    RECONCILED = "reconciled"
    #: Fewer keys confirmed gone than were handed over, or a delete failed. Bytes leaked.
    LEAKED = "leaked"
    #: Asset ROWS were deleted and NO key came back for them, so the objects behind them
    #: cannot be accounted for. This is today's normal answer — ``assets.storage_key`` is
    #: not written yet — and it means "unknown", never "clean".
    KEYS_UNRECORDED = "keys_unrecorded"
    #: No asset row expired, so no object was due. The only honest clean answer.
    NOTHING_TO_RECONCILE = "nothing_to_reconcile"


#: Worst first, and exhaustive over the enum — asserted by test, because a member missing
#: from this tuple would drop out of the rollup and read as a better state than it is. Used
#: to fold several runs into one badge without letting a later clean run hide an earlier leak.
_SEVERITY: Final[tuple[StorageReconciliation, ...]] = (
    StorageReconciliation.LEAKED,
    StorageReconciliation.KEYS_UNRECORDED,
    StorageReconciliation.RECONCILED,
    StorageReconciliation.NOTHING_TO_RECONCILE,
)


class StorageTally(ApiModel):
    """The object-store leg of one sweep. Both counts, their difference, and the verdict."""

    #: Keys ``purge_expired`` handed back — i.e. rows whose objects are now orphaned.
    keys_returned: int
    #: Keys the object store confirmed gone.
    keys_deleted: int
    delete_failures: int
    #: ``keysReturned - keysDeleted``, floored at zero. Bytes known to be still there.
    unreconciled_keys: int
    reconciliation: StorageReconciliation


class PurgeRunView(ApiModel):
    """One ``purge_runs`` row as the panel sees it, including a run that failed."""

    id: UUID
    ran_at: datetime
    trigger: PurgeTrigger
    #: Set for a ``MANUAL`` run only — the operator who asked for it.
    triggered_by_username: str | None
    duration_ms: int
    counts: SweepCounts
    total_rows_affected: int
    storage: StorageTally
    batch_size: int
    #: A sweep came back full, so more was due than one pass could take: run it again.
    is_batch_full: bool
    #: Set when the sweep returned ``Err``. The row exists precisely so that is visible.
    error_code: str | None


class RetentionResponse(ApiModel):
    """``GET /api/retention``.

    There is deliberately no ``isOverdue`` boolean. "Overdue" is three facts and the
    threshold belongs to whoever is looking: has it ever run (``hasEverRun``), when it last
    did (``lastRunAt``), and how much is due now (``rowsPastExpiry`` / ``totalRowsPastExpiry``
    — which, unlike ``isBatchFull``, says *how far behind* rather than only *whether to run
    again*). Synthesising one number out of those here would bake a policy into the wire that
    the operator could not see or argue with.
    """

    runs: list[PurgeRunView]
    #: Counted live against the sweep's own predicates, not derived from any run's counts.
    rows_past_expiry: SweepCounts
    total_rows_past_expiry: int
    #: ``null`` when the sweep has never run at all, which is a different fact from a run
    #: that did nothing — the whole reason ``purge_runs`` exists.
    last_run_at: datetime | None
    has_ever_run: bool
    #: The most recent run's own "run me again" verdict; ``false`` when none has run.
    is_batch_full: bool
    #: The worst :class:`StorageReconciliation` among ``runs``. A rollup that could only get
    #: better as more runs are listed would let a recent clean pass bury an older leak.
    #:
    #: ``null`` when there are no runs to fold. That case is not
    #: :attr:`StorageReconciliation.NOTHING_TO_RECONCILE`: "no asset row expired" is evidence
    #: and "the sweep has never run" is the absence of it, and a scheduler that never fired
    #: must not be able to light a clean badge.
    storage_reconciliation: StorageReconciliation | None


def _reconciliation(row: PurgeRunRow) -> StorageReconciliation:
    """Which of the four states this row's two storage numbers are in. Order matters."""
    if row.is_storage_leaking or row.storage_delete_failures > 0:
        return StorageReconciliation.LEAKED
    if row.storage_keys_returned > 0:
        return StorageReconciliation.RECONCILED
    if row.assets_deleted > 0:
        return StorageReconciliation.KEYS_UNRECORDED
    return StorageReconciliation.NOTHING_TO_RECONCILE


def _worst(states: Iterable[StorageReconciliation]) -> StorageReconciliation | None:
    """The worst state present, or ``None`` when there is nothing to fold at all."""
    seen = frozenset(states)
    if not seen:
        return None
    # ``_SEVERITY`` is exhaustive over the enum, so this always finds one.
    return next(state for state in _SEVERITY if state in seen)


def _counts(row: PurgeRunRow) -> SweepCounts:
    return SweepCounts(
        assets_deleted=row.assets_deleted,
        brief_notes_purged=row.brief_notes_purged,
        brief_identities_purged=row.brief_identities_purged,
        attempt_identities_purged=row.attempt_identities_purged,
        attempt_transcripts_purged=row.attempt_transcripts_purged,
        name_records_deleted=row.name_records_deleted,
        abandoned_orders_deleted=row.abandoned_orders_deleted,
        audit_reasons_purged=row.audit_reasons_purged,
        audit_rows_deleted=row.audit_rows_deleted,
        admin_sessions_deleted=row.admin_sessions_deleted,
        purge_runs_deleted=row.purge_runs_deleted,
        vendor_usage_deleted=row.vendor_usage_deleted,
        membership_events_deleted=row.membership_events_deleted,
        chat_bodies_purged=row.chat_bodies_purged,
        chat_messages_deleted=row.chat_messages_deleted,
        payme_rpc_rows_deleted=row.payme_rpc_rows_deleted,
        payment_intents_deleted=row.payment_intents_deleted,
        broadcast_recipients_deleted=row.broadcast_recipients_deleted,
    )


def _storage(row: PurgeRunRow) -> StorageTally:
    return StorageTally(
        keys_returned=row.storage_keys_returned,
        keys_deleted=row.storage_keys_deleted,
        delete_failures=row.storage_delete_failures,
        unreconciled_keys=max(0, row.storage_keys_returned - row.storage_keys_deleted),
        reconciliation=_reconciliation(row),
    )


def to_view(row: PurgeRunRow) -> PurgeRunView:
    """Project one sweep record onto the wire. Nothing is summarised away."""
    counts = _counts(row)
    return PurgeRunView(
        id=row.id,
        ran_at=row.ran_at,
        trigger=row.trigger,
        triggered_by_username=row.triggered_by_username,
        duration_ms=row.duration_ms,
        counts=counts,
        total_rows_affected=counts.total,
        storage=_storage(row),
        batch_size=row.batch_size,
        is_batch_full=row.is_batch_full,
        error_code=row.error_code,
    )


def to_response(overview: RetentionOverview) -> RetentionResponse:
    """The whole payload. ``rowsPastExpiry`` is validated, never defaulted — see the module
    docstring: a missing clock must not read as "nothing is due"."""
    runs = [to_view(row) for row in overview.runs]
    last_run = overview.last_run
    return RetentionResponse(
        runs=runs,
        rows_past_expiry=SweepCounts.model_validate(dict(overview.rows_past_expiry)),
        total_rows_past_expiry=overview.total_rows_past_expiry,
        last_run_at=last_run.ran_at if last_run is not None else None,
        has_ever_run=last_run is not None,
        is_batch_full=overview.is_batch_full,
        storage_reconciliation=_worst(run.storage.reconciliation for run in runs),
    )
