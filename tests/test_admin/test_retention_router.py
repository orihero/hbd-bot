"""``GET /api/retention`` over the real ASGI stack — the real container, login and guard.

The route exists because slice 1b is the first time the retention sweep has ever executed,
and an operator has to be able to see that it did. So the assertions that carry this file's
weight are the ones about what the response refuses to round off:

* a run that handed over three storage keys and confirmed one gone comes back as a **leak**,
  with both numbers and the difference, not as an "objects cleaned up" average;
* a run that deleted asset ROWS and got **zero** keys back — today's honest shape, because
  ``assets.storage_key`` is not written yet — comes back as ``keys_unrecorded``, which the
  panel can render as "0 keys returned because asset storage keys are not yet recorded" and
  which is deliberately not the same value as a sweep that had nothing to clean up;
* a later clean run does not bury an earlier leak in the top-level rollup;
* ``rowsPastExpiry`` is counted **live** against the sweep's own predicates, so it is
  non-zero while the last run's counts are all zero.

RBAC here is the whole matrix row: §12.2 gives RETENTION_READ to all four roles, and the
**M** cell has nothing to withhold because ``purge_runs`` holds counts and no personal data.
That is asserted as "every role sees the identical body", which would fail the moment
somebody added a maskable column to this table without adding a cell to go with it.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Final

import httpx
import pytest

from bayram.admin.container import AdminContainer
from bayram.admin.routers.retention import RETENTION_PATH
from bayram.admin.schemas.retention import _SEVERITY, StorageReconciliation, SweepCounts
from bayram.db.admin.retention import MAX_RUN_HISTORY, record_run
from bayram.db.base import utc_now
from bayram.db.enums import AdminRole, PurgeTrigger
from bayram.db.models.purge_run import PurgeRunRow
from bayram.db.purge import PurgeReport, rows_past_expiry_statements
from tests.test_admin.conftest import PASSWORD, create_account, sign_in

#: Every seeded run is anchored to the wall clock, because the route counts the live backlog
#: with its own ``utc_now()`` — a frozen instant here would put the fixtures on one side of
#: the 365-day ``purge_runs`` cutoff by accident rather than on purpose.
NOW: Final[datetime] = utc_now()
#: Comfortably past ``PURGE_RUN_RETENTION_DAYS`` (365), so a row stamped here is due.
LONG_EXPIRED: Final[datetime] = NOW - timedelta(days=400)


def make_report(*, ran_at: datetime | None = None, **counts: Any) -> PurgeReport:
    """A ``PurgeReport`` with everything at zero unless a test says otherwise."""
    return PurgeReport(ran_at=ran_at or NOW, **counts)


async def record(
    container: AdminContainer,
    *,
    report: PurgeReport | None = None,
    trigger: PurgeTrigger = PurgeTrigger.CRON,
    duration_ms: int = 12,
    storage_keys_deleted: int = 0,
    storage_delete_failures: int = 0,
    triggered_by_username: str | None = None,
    error_code: str | None = None,
) -> PurgeRunRow:
    """Write one sweep record through the one supported writer, as the job does."""
    async with container.session_factory.begin() as db:
        return await record_run(
            db,
            report=report or make_report(),
            trigger=trigger,
            duration_ms=duration_ms,
            storage_keys_deleted=storage_keys_deleted,
            storage_delete_failures=storage_delete_failures,
            triggered_by_username=triggered_by_username,
            error_code=error_code,
        )


async def signed_in(
    container: AdminContainer, client: httpx.AsyncClient, *, role: AdminRole
) -> None:
    username = f"{role.value}-account"
    await create_account(container, username=username, role=role)
    response = await sign_in(client, username=username, password=PASSWORD)
    assert response.status_code == 200


# ---------------------------------------------------------------------------
# Who may read it
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "role", [AdminRole.VIEWER, AdminRole.SUPPORT, AdminRole.ADMIN, AdminRole.OWNER]
)
async def test_every_role_in_the_matrix_row_may_read_the_retention_record(
    container: AdminContainer, client: httpx.AsyncClient, role: AdminRole
) -> None:
    # Arrange — §12.2 gives RETENTION_READ as M to all four roles.
    await record(container)
    await signed_in(container, client, role=role)

    # Act
    response = await client.get(RETENTION_PATH)

    # Assert
    assert response.status_code == 200
    assert len(response.json()["runs"]) == 1


async def test_an_unauthenticated_caller_gets_401_not_the_sweep_record(
    client: httpx.AsyncClient,
) -> None:
    # Act
    response = await client.get(RETENTION_PATH)

    # Assert
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "UNAUTHENTICATED"


async def test_a_viewer_and_an_owner_see_the_identical_body(
    container: AdminContainer, client: httpx.AsyncClient
) -> None:
    # Arrange — the M cell has nothing to withhold: this table holds counts, not people.
    await record(container, report=make_report(storage_keys=("a", "b"), assets_deleted=2))
    await signed_in(container, client, role=AdminRole.VIEWER)
    as_viewer = await client.get(RETENTION_PATH)
    client.cookies.clear()
    await signed_in(container, client, role=AdminRole.OWNER)

    # Act
    as_owner = await client.get(RETENTION_PATH)

    # Assert
    assert as_viewer.status_code == 200
    assert as_owner.json()["runs"] == as_viewer.json()["runs"]


# ---------------------------------------------------------------------------
# Shape
# ---------------------------------------------------------------------------
async def test_the_response_carries_each_sweeps_own_count_and_the_run_metadata(
    container: AdminContainer, client: httpx.AsyncClient
) -> None:
    # Arrange
    await record(
        container,
        report=make_report(
            assets_deleted=1,
            brief_notes_purged=2,
            brief_identities_purged=3,
            attempt_identities_purged=4,
            attempt_transcripts_purged=5,
            name_records_deleted=6,
            abandoned_orders_deleted=7,
            audit_reasons_purged=9,
            audit_rows_deleted=10,
            admin_sessions_deleted=11,
            purge_runs_deleted=8,
            vendor_usage_deleted=12,
            membership_events_deleted=13,
        ),
        trigger=PurgeTrigger.MANUAL,
        duration_ms=1234,
        triggered_by_username="owner",
    )
    await signed_in(container, client, role=AdminRole.ADMIN)

    # Act
    body = (await client.get(RETENTION_PATH)).json()

    # Assert — every clock on its own, never summed into one "rows deleted".
    run = body["runs"][0]
    assert run["counts"] == {
        "assetsDeleted": 1,
        "briefNotesPurged": 2,
        "briefIdentitiesPurged": 3,
        "attemptIdentitiesPurged": 4,
        "attemptTranscriptsPurged": 5,
        "nameRecordsDeleted": 6,
        "abandonedOrdersDeleted": 7,
        "auditReasonsPurged": 9,
        "auditRowsDeleted": 10,
        "adminSessionsDeleted": 11,
        "purgeRunsDeleted": 8,
        "vendorUsageDeleted": 12,
        # Revision 0017's churn transition log, swept on the same 400-day cutoff shape as
        # ``vendor_usage``. Present here because the endpoint publishes one number per
        # sweep and never a total: a clock the panel cannot see is a backlog it reports as
        # zero.
        "membershipEventsDeleted": 13,
        "chatBodiesPurged": 0,
        "chatMessagesDeleted": 0,
        # Revision 0023's two payment-rail cutoffs, here for the identical reason: the
        # endpoint publishes one number per sweep and never a total.
        "paymeRpcRowsDeleted": 0,
        "paymentIntentsDeleted": 0,
        # Revision 0024's delivery ledger, on the same 400-day cutoff shape, and the one an
        # operator has most reason to watch: the table takes a row per account per campaign.
        "broadcastRecipientsDeleted": 0,
    }
    assert run["totalRowsAffected"] == 91
    assert run["trigger"] == "manual"
    assert run["triggeredByUsername"] == "owner"
    assert run["durationMs"] == 1234
    assert run["isBatchFull"] is False
    assert run["errorCode"] is None
    assert body["hasEverRun"] is True


async def test_a_failed_sweep_is_visible_rather_than_missing(
    container: AdminContainer, client: httpx.AsyncClient
) -> None:
    # Arrange — the run an operator most needs to see. No row at all would be unreadable.
    await record(container, error_code="PIPELINE_ERROR")
    await signed_in(container, client, role=AdminRole.ADMIN)

    # Act
    body = (await client.get(RETENTION_PATH)).json()

    # Assert
    assert body["runs"][0]["errorCode"] == "PIPELINE_ERROR"


async def test_never_having_run_is_not_the_same_as_a_run_that_did_nothing(
    container: AdminContainer, client: httpx.AsyncClient
) -> None:
    # Arrange — nothing recorded at all.
    await signed_in(container, client, role=AdminRole.VIEWER)

    # Act
    body = (await client.get(RETENTION_PATH)).json()

    # Assert
    assert body["runs"] == []
    assert body["hasEverRun"] is False
    assert body["lastRunAt"] is None
    assert body["isBatchFull"] is False
    # And a scheduler that never fired cannot light a clean storage badge: no evidence is
    # null, not "nothing to reconcile".
    assert body["storageReconciliation"] is None


async def test_a_full_batch_is_reported_as_run_me_again(
    container: AdminContainer, client: httpx.AsyncClient
) -> None:
    # Arrange — one sweep filled its bound, which is what "more is due" actually means.
    await record(container, report=make_report(batch_size=5, name_records_deleted=5))
    await signed_in(container, client, role=AdminRole.ADMIN)

    # Act
    body = (await client.get(RETENTION_PATH)).json()

    # Assert
    assert body["runs"][0]["isBatchFull"] is True
    assert body["isBatchFull"] is True


async def test_runs_come_back_newest_first_and_the_limit_is_honoured(
    container: AdminContainer, client: httpx.AsyncClient
) -> None:
    # Arrange
    for minutes in range(3):
        await record(container, report=make_report(ran_at=NOW - timedelta(minutes=minutes)))
    await signed_in(container, client, role=AdminRole.ADMIN)

    # Act
    body = (await client.get(RETENTION_PATH, params={"limit": 2})).json()

    # Assert
    stamps = [run["ranAt"] for run in body["runs"]]
    assert len(stamps) == 2
    assert stamps == sorted(stamps, reverse=True)


@pytest.mark.parametrize("limit", [0, -1, MAX_RUN_HISTORY + 1])
async def test_a_limit_outside_the_bounds_is_refused_at_the_boundary(
    container: AdminContainer, client: httpx.AsyncClient, limit: int
) -> None:
    # Arrange — the clamp inside ``recent_runs`` is the backstop, not the validation.
    await signed_in(container, client, role=AdminRole.ADMIN)

    # Act
    response = await client.get(RETENTION_PATH, params={"limit": limit})

    # Assert
    assert response.status_code == 422


# ---------------------------------------------------------------------------
# The mismatch, surfaced
# ---------------------------------------------------------------------------
async def test_keys_handed_over_but_not_confirmed_gone_is_reported_as_a_leak(
    container: AdminContainer, client: httpx.AsyncClient
) -> None:
    # Arrange — three orphaned objects, one actually removed, two failures.
    await record(
        container,
        report=make_report(assets_deleted=3, storage_keys=("a", "b", "c")),
        storage_keys_deleted=1,
        storage_delete_failures=2,
    )
    await signed_in(container, client, role=AdminRole.ADMIN)

    # Act
    body = (await client.get(RETENTION_PATH)).json()

    # Assert — both numbers survive to the wire, and so does their difference.
    storage = body["runs"][0]["storage"]
    assert storage["keysReturned"] == 3
    assert storage["keysDeleted"] == 1
    assert storage["deleteFailures"] == 2
    assert storage["unreconciledKeys"] == 2
    assert storage["reconciliation"] == StorageReconciliation.LEAKED.value
    assert body["storageReconciliation"] == StorageReconciliation.LEAKED.value


async def test_zero_keys_beside_deleted_asset_rows_is_unknown_not_a_clean_archive(
    container: AdminContainer, client: httpx.AsyncClient
) -> None:
    # Arrange — today's real shape: ``_replace_assets`` does not write ``storage_key`` yet
    # (Phase 2), so the sweep deletes asset rows and hands back no keys at all.
    await record(container, report=make_report(assets_deleted=2, storage_keys=()))
    await signed_in(container, client, role=AdminRole.ADMIN)

    # Act
    body = (await client.get(RETENTION_PATH)).json()

    # Assert — the panel can say "0 keys returned because storage keys are not recorded".
    # It must NOT be able to say the archive is clean: rows went, bytes are unaccounted for.
    storage = body["runs"][0]["storage"]
    assert storage["keysReturned"] == 0
    assert storage["keysDeleted"] == 0
    assert storage["reconciliation"] == StorageReconciliation.KEYS_UNRECORDED.value
    assert storage["reconciliation"] != StorageReconciliation.RECONCILED.value
    assert body["storageReconciliation"] == StorageReconciliation.KEYS_UNRECORDED.value


async def test_nothing_due_is_distinguished_from_keys_that_were_never_recorded(
    container: AdminContainer, client: httpx.AsyncClient
) -> None:
    # Arrange — no asset row expired, so no object was due. The only honest clean answer.
    await record(container, report=make_report(brief_notes_purged=4))
    await signed_in(container, client, role=AdminRole.ADMIN)

    # Act
    body = (await client.get(RETENTION_PATH)).json()

    # Assert
    reconciliation = body["runs"][0]["storage"]["reconciliation"]
    assert reconciliation == StorageReconciliation.NOTHING_TO_RECONCILE.value


async def test_every_key_confirmed_gone_reads_as_reconciled(
    container: AdminContainer, client: httpx.AsyncClient
) -> None:
    # Arrange
    await record(
        container,
        report=make_report(assets_deleted=2, storage_keys=("a", "b")),
        storage_keys_deleted=2,
    )
    await signed_in(container, client, role=AdminRole.ADMIN)

    # Act
    body = (await client.get(RETENTION_PATH)).json()

    # Assert
    assert body["runs"][0]["storage"]["reconciliation"] == StorageReconciliation.RECONCILED.value
    assert body["storageReconciliation"] == StorageReconciliation.RECONCILED.value


async def test_a_later_clean_run_does_not_bury_an_earlier_leak(
    container: AdminContainer, client: httpx.AsyncClient
) -> None:
    # Arrange — the leak is older, so a "most recent run" rollup would hide it.
    await record(
        container,
        report=make_report(ran_at=NOW - timedelta(hours=2), assets_deleted=1, storage_keys=("a",)),
        storage_keys_deleted=0,
        storage_delete_failures=1,
    )
    await record(
        container,
        report=make_report(ran_at=NOW, assets_deleted=1, storage_keys=("b",)),
        storage_keys_deleted=1,
    )
    await signed_in(container, client, role=AdminRole.ADMIN)

    # Act
    body = (await client.get(RETENTION_PATH)).json()

    # Assert
    assert body["runs"][0]["storage"]["reconciliation"] == StorageReconciliation.RECONCILED.value
    assert body["storageReconciliation"] == StorageReconciliation.LEAKED.value


# ---------------------------------------------------------------------------
# The live backlog
# ---------------------------------------------------------------------------
async def test_rows_past_expiry_is_counted_live_and_not_read_off_the_last_run(
    container: AdminContainer, client: httpx.AsyncClient
) -> None:
    # Arrange — a sweep record older than the 365-day bound on this very table, so the
    # backlog is non-zero while the last run's own counts are all zero.
    await record(container, report=make_report(ran_at=LONG_EXPIRED))
    await signed_in(container, client, role=AdminRole.ADMIN)

    # Act
    body = (await client.get(RETENTION_PATH)).json()

    # Assert
    assert body["runs"][0]["counts"]["purgeRunsDeleted"] == 0
    assert body["rowsPastExpiry"]["purgeRunsDeleted"] == 1
    assert body["totalRowsPastExpiry"] == 1


async def test_an_empty_database_reports_no_backlog_rather_than_omitting_a_clock(
    container: AdminContainer, client: httpx.AsyncClient
) -> None:
    # Arrange
    await signed_in(container, client, role=AdminRole.ADMIN)

    # Act
    body = (await client.get(RETENTION_PATH)).json()

    # Assert — every clock is present and explicitly zero. A missing key would let the UI
    # render "no backlog" for a clock nobody is counting.
    assert body["totalRowsPastExpiry"] == 0
    assert set(body["rowsPastExpiry"]) == {
        "assetsDeleted",
        "briefNotesPurged",
        "briefIdentitiesPurged",
        "attemptIdentitiesPurged",
        "attemptTranscriptsPurged",
        "nameRecordsDeleted",
        "abandonedOrdersDeleted",
        "auditReasonsPurged",
        "auditRowsDeleted",
        "adminSessionsDeleted",
        "purgeRunsDeleted",
        "vendorUsageDeleted",
        "membershipEventsDeleted",
        "chatBodiesPurged",
        "chatMessagesDeleted",
        "paymeRpcRowsDeleted",
        "paymentIntentsDeleted",
        "broadcastRecipientsDeleted",
    }
    assert set(body["rowsPastExpiry"].values()) == {0}


def test_the_severity_order_covers_every_reconciliation_state() -> None:
    # Arrange / Act — a member missing from the rollup's order would silently drop out of
    # the fold and let the badge read better than the runs behind it.

    # Assert
    assert set(_SEVERITY) == set(StorageReconciliation)


def test_the_backlog_model_names_exactly_the_clocks_the_sweep_runs() -> None:
    # Arrange / Act — the drift guard. ``SweepCounts`` has no defaults, so a clock added to
    # the sweep and forgotten here is a loud failure; this makes it a failure in CI rather
    # than a 500 in front of an operator.
    statement_names = {name for name, _ in rows_past_expiry_statements(now=NOW)}

    # Assert
    assert set(SweepCounts.model_fields) == statement_names
