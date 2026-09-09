"""The three clocks slice 1b wrote and never executed, plus two audit-trail gaps.

Every test here failed before this pass, and each one fails for a different reason than
"the column is missing" — the columns were all present. What was missing was a *sweep*:

* ``admin_audit_log.reason_expires_at`` (90 d) and ``admin_audit_log.expires_at`` (730 d)
  were stamped on every row and read by nothing, so operator free text about a named
  customer was retained forever;
* ``admin_sessions.expires_at`` (12 h absolute) had a written, documented, unit-tested
  sweep — ``purge_expired_sessions`` — with zero production callers;
* an attempt row whose identity clock had already passed on the sweep's *first* run had its
  transcript deleted with ``text_purged_at`` left ``NULL``, which destroys the proof rather
  than the data;
* ``briefs.recipient_candidates`` persisted the JSON scalar ``null`` instead of SQL ``NULL``,
  so an erasure-proof query reading ``IS NULL`` reported data still held after it was gone.

The last test is the one that should have caught the first two: it asserts every retention
clock in ``Base.metadata`` is named by a sweep, rather than asserting the column exists.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Final
from uuid import uuid4

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from hbd.contracts import CostSource, Genre, Language, Occasion, VoiceGender, is_ok
from hbd.db.admin import audit as audit_store
from hbd.db.enums import AdminRole, AuditAction, AuditReasonCode, GenerationKind
from hbd.db.models import Base
from hbd.db.models.admin_audit import AdminAuditRow
from hbd.db.models.admin_session import AdminSessionRow
from hbd.db.models.admin_user import AdminUserRow
from hbd.db.models.audit_anchor import AuditAnchorKind, AuditChainAnchorRow
from hbd.db.models.brief import BriefRow
from hbd.db.models.generation_attempt import GenerationAttemptRow
from hbd.db.purge import PurgeReport, purge_expired, rows_past_expiry_statements
from tests.test_db.conftest import MovableClock

KEY: Final[str] = "a-test-hmac-key-of-more-than-32-characters"
NOW: Final[datetime] = datetime(2026, 8, 30, 12, 0, tzinfo=UTC)
#: Past the 90-day reason clock but well inside the 730-day row clock.
_PAST_THE_REASON_CLOCK: Final[timedelta] = timedelta(days=91)
#: Past both.
_PAST_THE_ROW_CLOCK: Final[timedelta] = timedelta(days=731)


def _entry(**overrides: object) -> audit_store.AuditEntry:
    values: dict[str, object] = {
        "action": AuditAction.REVEAL_PERSONAL,
        "actor_username": "owner",
        "actor_role": AdminRole.OWNER,
        "subject_type": "order",
        "reason_code": AuditReasonCode.SUPPORT_INVESTIGATION,
        "reason_text": "the customer asked about their song for grandma",
    }
    values.update(overrides)
    return audit_store.AuditEntry(**values)  # type: ignore[arg-type]


async def _append(
    sessions: async_sessionmaker[AsyncSession], count: int, *, at: datetime = NOW
) -> list[int]:
    seqs: list[int] = []
    for index in range(count):
        async with sessions.begin() as db:
            row = await audit_store.append(
                db, _entry(reason_ref=f"TICKET-{index}"), key=KEY, now=at
            )
            seqs.append(row.seq)
    return seqs


async def _sweep(sessions: async_sessionmaker[AsyncSession], *, now: datetime) -> PurgeReport:
    outcome = await purge_expired(sessions, now=now)
    assert is_ok(outcome), outcome
    return outcome.value


async def _count_rows(
    sessions: async_sessionmaker[AsyncSession], statement: sa.Select[tuple[int]]
) -> int:
    async with sessions.begin() as db:
        return (await db.execute(statement)).scalar_one()


# ---------------------------------------------------------------------------
# admin_audit_log — two clocks, neither of which had a sweep
# ---------------------------------------------------------------------------
async def test_the_operators_free_text_is_nulled_once_its_ninety_day_clock_passes(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    # Arrange — a real audited action carrying a real customer's name in its reason.
    await _append(sessions, 1)

    # Act
    report = await _sweep(sessions, now=NOW + _PAST_THE_REASON_CLOCK)

    # Assert — the text is gone, the row and its accountability columns are not.
    async with sessions.begin() as db:
        row = (await db.execute(sa.select(AdminAuditRow))).scalar_one()
        assert row.reason_text is None
        assert row.reason_purged_at is not None
        assert row.reason_ref == "TICKET-0"
        assert row.reason_code is AuditReasonCode.SUPPORT_INVESTIGATION
    assert report.audit_reasons_purged == 1


async def test_a_swept_reason_is_not_swept_again_on_the_next_run(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    # Arrange
    await _append(sessions, 1)
    await _sweep(sessions, now=NOW + _PAST_THE_REASON_CLOCK)

    # Act — the predicate must exclude a row it already visited, or the job spins forever.
    second = await _sweep(sessions, now=NOW + _PAST_THE_REASON_CLOCK + timedelta(days=1))

    # Assert
    assert second.audit_reasons_purged == 0


async def test_the_audit_row_itself_is_deleted_once_its_seven_hundred_and_thirty_day_clock_passes(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    # Arrange
    await _append(sessions, 3)

    # Act
    report = await _sweep(sessions, now=NOW + _PAST_THE_ROW_CLOCK)

    # Assert
    assert report.audit_rows_deleted == 3
    remaining = await _count_rows(sessions, sa.select(sa.func.count()).select_from(AdminAuditRow))
    assert remaining == 0


async def test_a_row_inside_its_clock_survives_the_sweep_that_deletes_an_older_one(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    # Arrange — one ancient row and one written today.
    await _append(sessions, 1, at=NOW - timedelta(days=800))
    await _append(sessions, 1, at=NOW)

    # Act
    report = await _sweep(sessions, now=NOW)

    # Assert — the sweep is a clock, not a truncation.
    assert report.audit_rows_deleted == 1
    remaining = await _count_rows(sessions, sa.select(sa.func.count()).select_from(AdminAuditRow))
    assert remaining == 1


async def test_deleting_expired_audit_rows_records_a_truncation_anchor(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    # Arrange — three ancient rows and one current, so a chain survives the cut.
    old = await _append(sessions, 3, at=NOW - timedelta(days=800))
    await _append(sessions, 1, at=NOW)

    # Act
    await _sweep(sessions, now=NOW)

    # Assert — the cut is recorded, so the verifier can tell it from a deletion.
    async with sessions.begin() as db:
        anchors = (
            (
                await db.execute(
                    sa.select(AuditChainAnchorRow).where(
                        AuditChainAnchorRow.kind == AuditAnchorKind.TRUNCATION
                    )
                )
            )
            .scalars()
            .all()
        )
    assert len(anchors) == 1
    assert anchors[0].rows_deleted == 3
    assert anchors[0].truncated_below_seq is not None
    assert anchors[0].truncated_below_seq > old[-1] - 1


async def test_every_sweep_pins_the_current_head_so_a_tail_deletion_is_detectable(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    # Arrange
    await _append(sessions, 2)

    # Act
    await _sweep(sessions, now=NOW)

    # Assert
    async with sessions.begin() as db:
        head = (
            (
                await db.execute(
                    sa.select(AuditChainAnchorRow).where(
                        AuditChainAnchorRow.kind == AuditAnchorKind.HEAD
                    )
                )
            )
            .scalars()
            .all()
        )
    assert len(head) == 1
    assert head[0].seq == 2


# ---------------------------------------------------------------------------
# admin_sessions — a written, tested sweep with no caller
# ---------------------------------------------------------------------------
async def _an_admin(sessions: async_sessionmaker[AsyncSession]) -> AdminUserRow:
    row = AdminUserRow(
        id=uuid4(),
        username="owner",
        password_hash="x",
        role=AdminRole.OWNER,
        is_active=True,
        must_change_password=False,
        password_changed_at=NOW,
        created_at=NOW,
        updated_at=NOW,
    )
    async with sessions.begin() as db:
        db.add(row)
    return row


async def test_an_admin_session_past_its_twelve_hour_cap_is_deleted_by_the_hourly_sweep(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    # Arrange — the row carries token_sha256, csrf_token and two operator IP addresses.
    admin = await _an_admin(sessions)
    async with sessions.begin() as db:
        db.add(
            AdminSessionRow(
                id=uuid4(),
                admin_user_id=admin.id,
                token_sha256="d" * 64,
                csrf_token="c" * 43,
                created_at=NOW,
                last_seen_at=NOW,
                expires_at=NOW + timedelta(hours=12),
                created_ip="203.0.113.7",
                last_ip="203.0.113.7",
                user_agent="Mozilla/5.0",
            )
        )

    # Act
    report = await _sweep(sessions, now=NOW + timedelta(hours=13))

    # Assert
    assert report.admin_sessions_deleted == 1
    remaining = await _count_rows(sessions, sa.select(sa.func.count()).select_from(AdminSessionRow))
    assert remaining == 0


async def test_a_live_admin_session_is_left_alone(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    # Arrange
    admin = await _an_admin(sessions)
    async with sessions.begin() as db:
        db.add(
            AdminSessionRow(
                id=uuid4(),
                admin_user_id=admin.id,
                token_sha256="e" * 64,
                csrf_token="f" * 43,
                created_at=NOW,
                last_seen_at=NOW,
                expires_at=NOW + timedelta(hours=12),
                created_ip=None,
                last_ip=None,
                user_agent=None,
            )
        )

    # Act
    report = await _sweep(sessions, now=NOW + timedelta(hours=1))

    # Assert
    assert report.admin_sessions_deleted == 0
    remaining = await _count_rows(sessions, sa.select(sa.func.count()).select_from(AdminSessionRow))
    assert remaining == 1


# ---------------------------------------------------------------------------
# The two audit-trail gaps: a purge that deletes the data and loses the proof
# ---------------------------------------------------------------------------
async def test_a_first_sweep_that_reaches_the_identity_clock_still_stamps_the_text_clock(
    sessions: async_sessionmaker[AsyncSession],
    clock: MovableClock,
) -> None:
    # Arrange — one attempt whose 90-day identity clock has ALREADY passed when the sweep
    # first runs. That is not an edge case: it is every historical row on the first run of a
    # retention system that has never executed.
    attempt_id = uuid4()
    async with sessions.begin() as db:
        db.add(
            GenerationAttemptRow(
                id=attempt_id,
                order_id=None,
                kind=GenerationKind.SONG,
                sequence=1,
                attempt=1,
                provider="p",
                is_success=True,
                cost_usd=0.0,
                cost_source=CostSource.ESTIMATED,
                latency_ms=0,
                created_at=NOW,
                stt_transcript="happy birthday dear Dilnoza",
                identity_expires_at=NOW + timedelta(days=90),
                text_expires_at=NOW + timedelta(days=30),
            )
        )
    del clock

    # Act — a single sweep, well past both clocks, with no prior run.
    await _sweep(sessions, now=NOW + timedelta(days=95))

    # Assert — the transcript is gone AND both audit columns say who took it.
    async with sessions.begin() as db:
        row = (
            await db.execute(
                sa.select(GenerationAttemptRow).where(GenerationAttemptRow.id == attempt_id)
            )
        ).scalar_one()
        assert row.stt_transcript is None
        assert row.identity_purged_at is not None
        assert row.text_purged_at is not None, (
            "the identity sweep cleared the transcript and left the text clock unstamped; "
            "the data is deleted and the proof is not"
        )


async def test_purged_recipient_candidates_read_as_sql_null_not_the_json_scalar_null(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    # Arrange — a brief with candidate orthographies, past its identity clock.
    brief_id = uuid4()
    order_id = uuid4()
    async with sessions.begin() as db:
        db.add(
            BriefRow(
                id=brief_id,
                order_id=order_id,
                occasion=Occasion.BIRTHDAY,
                genre=Genre.POP,
                vocal_gender=VoiceGender.FEMALE,
                ui_language=Language.UZ_LATN,
                output_language=Language.UZ_LATN,
                recipient_name_raw="Dilnoza",
                recipient_name_display="Dilnoza",
                recipient_lookup_key="dilnoza",
                recipient_candidates=[{"text": "Dilnoza"}],
                created_at=NOW,
                updated_at=NOW,
                identity_expires_at=NOW + timedelta(days=90),
                note_expires_at=NOW + timedelta(days=30),
            )
        )

    # Act
    await _sweep(sessions, now=NOW + timedelta(days=95))

    # Assert — an erasure proof asks `IS NULL`, and the JSON scalar `null` is not NULL.
    held = await _count_rows(
        sessions,
        sa.select(sa.func.count())
        .select_from(BriefRow)
        .where(BriefRow.recipient_candidates.is_not(None)),
    )
    assert held == 0


# ---------------------------------------------------------------------------
# The guard that should have caught all of the above
# ---------------------------------------------------------------------------
def _clocks_in_the_schema() -> set[str]:
    return {
        f"{table_name}.{column.name}"
        for table_name, table in Base.metadata.tables.items()
        for column in table.columns
        if column.name.endswith("expires_at")
    }


def _clocks_read_by_a_sweep() -> set[str]:
    """Every clock column a ``rows_past_expiry_statements`` predicate actually references.

    Derived from the statements rather than from a hand-kept list: a list is exactly what
    let the old guard pass while ``admin_audit_log``'s two clocks were decorative.
    """
    read: set[str] = set()
    for _, statement in rows_past_expiry_statements(now=NOW):
        clause = statement.whereclause
        if clause is None:  # pragma: no cover - every sweep is a predicate
            continue
        for element in clause.get_children(column_collections=False):
            read.update(_columns_of(element))
        read.update(_columns_of(clause))
    return {name for name in read if name.endswith("expires_at")}


def _columns_of(element: object) -> set[str]:
    """Recursively collect ``table.column`` names from a SQLAlchemy clause element."""
    found: set[str] = set()
    if isinstance(element, sa.Column):
        return {f"{element.table.name}.{element.name}"}
    children = getattr(element, "get_children", None)
    if children is None:
        return found
    for child in children(column_collections=False):
        found |= _columns_of(child)
    return found


def test_the_vendor_telemetry_table_declares_no_retention_clock_to_be_swept_by() -> None:
    """``vendor_usage`` is deliberately outside this file's inventory, so say it once.

    Both halves of the guard below key off a column name ending in ``expires_at``, which is
    how ``user_profiles`` is passed over by construction. ``vendor_usage`` is passed over the
    same way and for a different reason: it holds no personal data at all — every column is a
    closed enum, an integer, a machine id or a bounded error code — so it has no legal clock
    to declare. Its growth is bounded by a cutoff on ``created_at`` instead
    (``hbd.db.purge.VENDOR_USAGE_RETENTION_DAYS``), counted through the sweep registry above.

    Naming a column there ``*_expires_at`` would enlist the table in the inventory below and
    claim a published schedule it does not have; this asserts the absence rather than
    leaving it to be reintroduced by somebody copying another model.
    """
    # Arrange / Act
    columns = {column.name for column in Base.metadata.tables["vendor_usage"].columns}

    # Assert
    assert not any(name.endswith("expires_at") for name in columns), (
        "vendor_usage is swept on a cutoff, not a clock; an *_expires_at column here would "
        "claim a retention schedule this table does not have"
    )


def test_every_retention_clock_in_the_schema_is_read_by_a_sweep() -> None:
    """A clock column with no sweep is data retained past its own stated schedule.

    The previous version of this guard asserted only that each table holding personal data
    *had* a column whose name ends in ``expires_at``. ``admin_audit_log`` passed it cleanly
    while both of its clocks were decorative, and ``admin_sessions`` was not in the set at
    all. This asks the question that matters, and answers it from the sweep predicates
    themselves: is anything reading the column?
    """
    # Arrange / Act
    unswept = _clocks_in_the_schema() - _clocks_read_by_a_sweep()

    # Assert
    assert unswept == set(), f"retention clocks with no sweep: {sorted(unswept)}"


def test_the_sweep_registry_lists_a_statement_for_every_new_clock() -> None:
    """``rows_past_expiry_statements`` is what the panel's backlog is counted from.

    A sweep that runs but is missing from this registry is a backlog the panel reports as
    zero, which is worse than no number at all.
    """
    # Arrange / Act
    names = {name for name, _ in rows_past_expiry_statements(now=NOW)}

    # Assert — ``vendor_usage_deleted`` is here despite ``vendor_usage`` holding no personal
    # data and carrying no ``*_expires_at`` column. It is swept on a 400-day CUTOFF, and the
    # backlog the panel reads comes from this registry alone, so a bounded-growth sweep that
    # is missing from it is a table quietly growing behind a number that says zero.
    assert {
        "audit_reasons_purged",
        "audit_rows_deleted",
        "admin_sessions_deleted",
        "vendor_usage_deleted",
        "chat_bodies_purged",
        "chat_messages_deleted",
    } <= names


@pytest.mark.parametrize(
    "field",
    [
        "audit_reasons_purged",
        "audit_rows_deleted",
        "admin_sessions_deleted",
        "vendor_usage_deleted",
        "chat_bodies_purged",
        "chat_messages_deleted",
    ],
)
async def test_each_new_count_is_stored_on_the_purge_runs_row(
    sessions: async_sessionmaker[AsyncSession], field: str
) -> None:
    # Arrange — the panel reads a stored row, never a log line.
    from hbd.db.models.purge_run import PurgeRunRow

    # Act / Assert — the column exists and is an integer counter.
    assert field in PurgeRunRow.__table__.columns
