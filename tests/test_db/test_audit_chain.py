"""The audit chain: it links, it is keyed, it survives its own sweeps, and it catches a tamper.

The tests that matter most here are the negative ones. A hash chain that never fails a test
is indistinguishable from a chain that cannot fail — which is exactly what §12.4 says the
draft's unkeyed ``sha256`` was — so this module mutates rows behind the writer's back with raw
SQL and asserts the walk reports the break at the right ``seq``, verifies with the wrong key
and asserts it does *not* pass, and recomputes the plain digest of a row's canonical content
to prove the stored value is not one.

Everything runs on SQLite, which is the point of the ``with_variant`` on ``seq``: a ``BIGINT``
primary key is not a ROWID alias there, gets no implicit value, and would fail every insert in
this file with a ``NOT NULL`` violation rather than a message about autoincrement.
"""

from __future__ import annotations

import os
import re
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from pathlib import Path
from typing import Final

import pytest
import sqlalchemy as sa
from sqlalchemy.exc import ProgrammingError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from hbd.db.admin import accounts
from hbd.db.admin import audit as audit_module
from hbd.db.admin.audit import (
    AuditEntry,
    AuditQuery,
    AuditValueRejectedError,
    ChainProtection,
    append,
    canonical_content,
    compute_chain_hmac,
    list_entries,
    read_head,
    resolve_chain_protection,
    verify_chain,
    write_head_anchor,
    write_truncation_anchor,
)
from hbd.db.engine import create_engine, create_session_factory, ping
from hbd.db.enums import AdminRole, AuditAction, AuditReasonCode
from hbd.db.models import Base
from hbd.db.models.admin_audit import (
    AUDIT_REASON_RETENTION_DAYS,
    AUDIT_RETENTION_DAYS,
    AdminAuditRow,
    AuditOutcome,
)
from hbd.db.models.audit_anchor import AuditAnchorKind, AuditChainAnchorRow
from tests.test_db.conftest import refuse_a_foreign_database

KEY: Final[str] = "a-test-hmac-key-of-more-than-32-characters"
OTHER_KEY: Final[str] = "a-different-key-of-more-than-32-characters"
NOW: Final[datetime] = datetime(2026, 8, 30, 12, 0, tzinfo=UTC)

_SRC: Final[Path] = Path(__file__).resolve().parents[2] / "src" / "hbd"
#: The one module allowed to construct the row, plus the module that declares it.
_WRITER_FILES: Final[frozenset[str]] = frozenset({"db/admin/audit.py", "db/models/admin_audit.py"})


def entry(**overrides: object) -> AuditEntry:
    """A minimal, valid entry. Overridden field by field so each test names its own variable."""
    values: dict[str, object] = {
        "action": AuditAction.REVEAL_PERSONAL,
        "actor_username": "owner",
        "actor_role": AdminRole.OWNER,
        "subject_type": "order",
        "subject_id": "1c9e1a5e-0000-4000-8000-000000000001",
        "reason_code": AuditReasonCode.SUPPORT_INVESTIGATION,
    }
    values.update(overrides)
    return AuditEntry(**values)  # type: ignore[arg-type]


async def append_many(
    sessions: async_sessionmaker[AsyncSession], count: int, **overrides: object
) -> list[int]:
    """``count`` audited actions, each in its own transaction. Returns their sequence numbers."""
    seqs: list[int] = []
    for index in range(count):
        async with sessions.begin() as db:
            row = await append(
                db,
                entry(reason_ref=f"TICKET-{index}", **overrides),
                key=KEY,
                now=NOW + timedelta(minutes=index),
            )
            seqs.append(row.seq)
    return seqs


# ---------------------------------------------------------------------------
# The column that SQLite has an opinion about
# ---------------------------------------------------------------------------
async def test_two_appended_rows_get_monotonic_sequence_numbers_on_sqlite(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    # Arrange / Act
    seqs = await append_many(sessions, 2)

    # Assert — a BIGINT primary key would have failed NOT NULL on both inserts.
    assert seqs == sorted(seqs)
    assert seqs[1] > seqs[0]


async def test_the_sequence_is_assigned_by_the_database_not_by_the_writer(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    # Arrange — a bare insert that supplies no seq at all, which is what the ``with_variant``
    # has to make work: this is the autoincrement itself, not the append helper.
    async with sessions.begin() as db:
        row = AdminAuditRow(
            at=NOW,
            actor_username="system:test",
            actor_role=AdminRole.OWNER,
            action=AuditAction.RETENTION_RUN,
            subject_type="system",
            reason_code=AuditReasonCode.ROUTINE_OPS,
            outcome=AuditOutcome.OK,
            expires_at=NOW + timedelta(days=AUDIT_RETENTION_DAYS),
            chain_hmac="x" * 64,
        )
        db.add(row)
        await db.flush()

        # Assert
        assert isinstance(row.seq, int)
        assert row.seq >= 1


# ---------------------------------------------------------------------------
# The chain
# ---------------------------------------------------------------------------
async def test_each_row_links_to_the_previous_rows_hmac(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    # Arrange
    await append_many(sessions, 3)

    # Act
    async with sessions.begin() as db:
        rows = list(
            (await db.execute(sa.select(AdminAuditRow).order_by(AdminAuditRow.seq))).scalars()
        )

    # Assert
    assert rows[0].prev_hmac is None
    assert [row.prev_hmac for row in rows[1:]] == [row.chain_hmac for row in rows[:-1]]


async def test_the_chain_verifies_after_a_series_of_appends(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    # Arrange
    await append_many(sessions, 5)

    # Act
    async with sessions.begin() as db:
        result = await verify_chain(db, key=KEY, is_dsn_configured=False)

    # Assert
    assert result.is_ok
    assert result.first_break_seq is None
    assert result.checked_rows == 5
    assert result.is_complete


async def test_a_row_mutated_behind_the_writers_back_is_reported_as_the_first_break(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    # Arrange — three good rows, then raw SQL edits the middle one, exactly as an attacker
    # with write access to the table would.
    seqs = await append_many(sessions, 3)
    async with sessions.begin() as db:
        await db.execute(
            sa.text("UPDATE admin_audit_log SET subject_type = 'user' WHERE seq = :seq"),
            {"seq": seqs[1]},
        )

    # Act
    async with sessions.begin() as db:
        result = await verify_chain(db, key=KEY, is_dsn_configured=False)

    # Assert
    assert not result.is_ok
    assert result.first_break_seq == seqs[1]


async def test_a_deleted_row_breaks_the_chain_at_the_row_that_followed_it(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    # Arrange
    seqs = await append_many(sessions, 3)
    async with sessions.begin() as db:
        await db.execute(sa.delete(AdminAuditRow).where(AdminAuditRow.seq == seqs[1]))

    # Act
    async with sessions.begin() as db:
        result = await verify_chain(db, key=KEY, is_dsn_configured=False)

    # Assert — the survivor's stored link names a row that is no longer there.
    assert not result.is_ok
    assert result.first_break_seq == seqs[2]


async def test_the_chain_does_not_verify_under_a_different_key(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    # Arrange
    seqs = await append_many(sessions, 2)

    # Act
    async with sessions.begin() as db:
        result = await verify_chain(db, key=OTHER_KEY, is_dsn_configured=False)

    # Assert — this is the whole difference from an unkeyed chain: possession of the key is
    # what verification proves, so the wrong key cannot report clean.
    assert not result.is_ok
    assert result.first_break_seq == seqs[0]


async def test_the_stored_value_is_not_a_plain_digest_of_the_row(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    # Arrange
    await append_many(sessions, 1)

    # Act
    async with sessions.begin() as db:
        row = await read_head(db)
        assert row is not None
        content = canonical_content(row)
        unkeyed = sha256(f"v1\n\n{content}".encode()).hexdigest()

    # Assert — an unkeyed chain is recomputable by whoever can write the table (§12.4).
    assert row.chain_hmac != unkeyed
    assert row.chain_hmac == compute_chain_hmac(key=KEY, prev_hmac=None, content=content)


def test_an_empty_key_is_refused_rather_than_producing_an_unkeyed_chain() -> None:
    # Act / Assert
    with pytest.raises(AuditValueRejectedError):
        compute_chain_hmac(key="", prev_hmac=None, content="{}")


async def test_nulling_the_reason_text_does_not_break_the_chain(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    # Arrange — exactly what the 90-day reason sweep does at the 90-day mark.
    await append_many(sessions, 2, reason_text="operator note about the ticket")
    async with sessions.begin() as db:
        await db.execute(sa.update(AdminAuditRow).values(reason_text=None, reason_purged_at=NOW))

    # Act
    async with sessions.begin() as db:
        result = await verify_chain(db, key=KEY, is_dsn_configured=False)

    # Assert — the reason columns are excluded from the canonical form for this reason.
    assert result.is_ok


async def test_the_retention_clocks_are_set_from_the_appending_instant(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    # Arrange / Act
    async with sessions.begin() as db:
        row = await append(db, entry(reason_text="why"), key=KEY, now=NOW)

        # Assert
        assert row.expires_at == NOW + timedelta(days=AUDIT_RETENTION_DAYS)
        assert row.reason_expires_at == NOW + timedelta(days=AUDIT_REASON_RETENTION_DAYS)


async def test_a_row_without_reason_text_carries_no_reason_clock(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    # Arrange / Act
    async with sessions.begin() as db:
        row = await append(db, entry(), key=KEY, now=NOW)

    # Assert — NULL exactly when the text is NULL, so the sweep's predicate stays honest.
    assert row.reason_expires_at is None


# ---------------------------------------------------------------------------
# Nothing that looks like a credential reaches a column
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    ("label", "secret"),
    [
        ("argon2 password hash", "$argon2id$v=19$m=65536,t=3,p=4$c29tZXNhbHQ$aGFzaHZhbHVl"),
        ("session token digest", "a" * 64),
        ("session token", "xQ3nZ9pLk2mR7vT1wY8bN4cV6sD0fG5hJ2kL9xZ3nQ4"),
        ("openrouter api key", "sk-or-v1-0123456789abcdef0123456789abcdef0123"),
        ("elevenlabs api key", "sk_0123456789abcdef0123456789abcdef"),
        ("database dsn", "postgresql+asyncpg://hbd:hunter2@db.internal:5432/hbd"),
        ("bearer token", "Bearer abcdef0123456789"),
    ],
)
async def test_a_secret_in_the_reason_text_is_refused(
    sessions: async_sessionmaker[AsyncSession], label: str, secret: str
) -> None:
    # Arrange / Act / Assert — refused, not stored redacted: a credential that reached an
    # audit row is an incident to surface.
    async with sessions.begin() as db:
        with pytest.raises(AuditValueRejectedError, match="credential"):
            await append(db, entry(reason_text=f"see {secret}"), key=KEY, now=NOW)


async def test_a_secret_shaped_subject_id_is_refused(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    # Arrange / Act / Assert
    async with sessions.begin() as db:
        with pytest.raises(AuditValueRejectedError):
            await append(db, entry(subject_id="b" * 64), key=KEY, now=NOW)


async def test_nothing_was_written_when_a_secret_was_refused(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    # Arrange
    async with sessions.begin() as db:
        with pytest.raises(AuditValueRejectedError):
            await append(db, entry(reason_text="sk-or-v1-" + "a" * 32), key=KEY, now=NOW)

    # Act
    async with sessions.begin() as db:
        total = await db.scalar(sa.select(sa.func.count()).select_from(AdminAuditRow))

    # Assert — the refusal happens before the row is built, so there is no partial entry.
    assert total == 0


@pytest.mark.parametrize("field_name", ["Dilnoza", "note: her mother's song", "1234", "a" * 70])
async def test_field_names_must_be_names_not_values(
    sessions: async_sessionmaker[AsyncSession], field_name: str
) -> None:
    # Arrange / Act / Assert — §12.4: the log records THAT briefs.note was revealed.
    async with sessions.begin() as db:
        with pytest.raises(AuditValueRejectedError):
            await append(db, entry(field_names=(field_name,)), key=KEY, now=NOW)


async def test_a_legitimate_field_name_list_is_stored(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    # Arrange / Act
    async with sessions.begin() as db:
        row = await append(
            db, entry(field_names=("briefs.note", "recipient_name_display")), key=KEY, now=NOW
        )

    # Assert
    assert row.field_names == ["briefs.note", "recipient_name_display"]


async def test_a_subject_type_outside_the_closed_set_is_refused(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    # Arrange / Act / Assert
    async with sessions.begin() as db:
        with pytest.raises(AuditValueRejectedError, match="closed set"):
            await append(db, entry(subject_type="whatever"), key=KEY, now=NOW)


async def test_a_reason_reference_that_is_not_a_ticket_shape_is_refused(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    # Arrange / Act / Assert
    async with sessions.begin() as db:
        with pytest.raises(AuditValueRejectedError):
            await append(db, entry(reason_ref="ticket 12; drop table"), key=KEY, now=NOW)


def test_append_is_the_only_place_that_constructs_an_audit_row() -> None:
    # Arrange — the chain is linear only if one function computes it.
    pattern = re.compile(r"\bAdminAuditRow\(")

    # Act
    offenders = [
        str(path.relative_to(_SRC))
        for path in _SRC.rglob("*.py")
        if pattern.search(path.read_text(encoding="utf-8"))
        and str(path.relative_to(_SRC)).replace("\\", "/") not in _WRITER_FILES
    ]

    # Assert
    assert offenders == [], f"a second audit writer would fork the chain: {offenders}"


# ---------------------------------------------------------------------------
# Anchors
# ---------------------------------------------------------------------------
async def test_a_head_anchor_records_the_head_and_emits_a_log_line(
    sessions: async_sessionmaker[AsyncSession], caplog: pytest.LogCaptureFixture
) -> None:
    # Arrange
    await append_many(sessions, 2)

    # Act
    with caplog.at_level("INFO", logger="hbd.db.admin.audit"):
        async with sessions.begin() as db:
            head = await read_head(db)
            anchor = await write_head_anchor(db, now=NOW)

    # Assert — the log line is the out-of-band copy §5.5 requires, not a nicety.
    assert anchor is not None and head is not None
    assert anchor.seq == head.seq
    assert anchor.chain_hmac == head.chain_hmac
    assert any(record.message == "audit chain anchor" for record in caplog.records)


async def test_no_anchor_is_written_for_an_empty_log(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    # Act
    async with sessions.begin() as db:
        anchor = await write_head_anchor(db, now=NOW)

    # Assert — there is no head to pin, and a row claiming otherwise would be a lie.
    assert anchor is None


async def test_a_truncation_anchor_records_where_the_sweep_cut_the_chain(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    # Arrange — the 730-day sweep deletes the oldest row, as it will in two years.
    seqs = await append_many(sessions, 3)
    async with sessions.begin() as db:
        await db.execute(sa.delete(AdminAuditRow).where(AdminAuditRow.seq == seqs[0]))
        anchor = await write_truncation_anchor(db, below_seq=seqs[1], rows_deleted=1, now=NOW)

    # Assert
    assert anchor is not None
    assert anchor.kind is AuditAnchorKind.TRUNCATION
    assert anchor.truncated_below_seq == seqs[1]
    assert anchor.rows_deleted == 1

    # Act — and the surviving prefix still verifies, because the walk seeds from the first
    # surviving row rather than treating a deliberate cut as tampering.
    async with sessions.begin() as db:
        result = await verify_chain(db, key=KEY, is_dsn_configured=False)

    # Assert
    assert result.is_ok
    assert result.anchors == (seqs[1],)


async def test_a_truncation_anchor_is_not_written_when_nothing_survives(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    # Act
    async with sessions.begin() as db:
        anchor = await write_truncation_anchor(db, below_seq=9, rows_deleted=3, now=NOW)
        total = await db.scalar(sa.select(sa.func.count()).select_from(AuditChainAnchorRow))

    # Assert
    assert anchor is None
    assert total == 0


# ---------------------------------------------------------------------------
# What the deployment actually has
# ---------------------------------------------------------------------------
async def test_sqlite_reports_hmac_only_however_the_dsn_is_configured(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    # Act — the claim is checked against the database, and SQLite has no privilege to revoke.
    async with sessions.begin() as db:
        claimed = await verify_chain(db, key=KEY, is_dsn_configured=True)
        unclaimed = await verify_chain(db, key=KEY, is_dsn_configured=False)

    # Assert
    assert claimed.protection is ChainProtection.HMAC_ONLY
    assert unclaimed.protection is ChainProtection.HMAC_ONLY


# ---------------------------------------------------------------------------
# Reading
# ---------------------------------------------------------------------------
async def test_the_actor_is_recorded_by_id_and_by_denormalised_username(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    # Arrange
    async with sessions.begin() as db:
        operator = await accounts.create(
            db,
            username="Reviewer",
            password_hash="not-a-real-hash",
            role=AdminRole.ADMIN,
            must_change_password=False,
            now=NOW,
        )
        row = await append(
            db,
            entry(actor_id=operator.id, actor_username=operator.username),
            key=KEY,
            now=NOW,
        )

    # Assert — the username is a snapshot, so a later rename cannot rewrite history.
    assert row.actor_id == operator.id
    assert row.actor_username == "reviewer"


async def test_the_list_is_newest_first_and_pages_by_sequence(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    # Arrange
    seqs = await append_many(sessions, 5)

    # Act
    async with sessions.begin() as db:
        first = await list_entries(db, AuditQuery(), limit=2)
        second = await list_entries(db, AuditQuery(), limit=2, before_seq=first[-1].seq)

    # Assert
    assert [row.seq for row in first] == [seqs[4], seqs[3]]
    assert [row.seq for row in second] == [seqs[2], seqs[1]]


async def test_filters_are_and_across_fields_and_or_within_one(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    # Arrange
    await append_many(sessions, 2, action=AuditAction.REVEAL_PERSONAL)
    await append_many(sessions, 1, action=AuditAction.USER_BLOCK, subject_type="user")

    # Act
    async with sessions.begin() as db:
        both = await list_entries(
            db, AuditQuery(actions=(AuditAction.REVEAL_PERSONAL, AuditAction.USER_BLOCK))
        )
        narrowed = await list_entries(
            db, AuditQuery(actions=(AuditAction.USER_BLOCK,), subject_type="user")
        )
        contradictory = await list_entries(
            db, AuditQuery(actions=(AuditAction.USER_BLOCK,), subject_type="order")
        )

    # Assert
    assert len(both) == 3
    assert len(narrowed) == 1
    assert contradictory == []


async def test_the_time_window_is_inclusive_of_its_bounds(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    # Arrange — three rows one minute apart, starting at NOW.
    await append_many(sessions, 3)

    # Act
    async with sessions.begin() as db:
        inside = await list_entries(db, AuditQuery(since=NOW, until=NOW + timedelta(minutes=1)))
        after = await list_entries(db, AuditQuery(since=NOW + timedelta(minutes=5)))

    # Assert
    assert len(inside) == 2
    assert after == []


async def test_a_page_is_bounded_even_when_the_caller_asks_for_everything(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    # Arrange
    await append_many(sessions, 3)

    # Act
    async with sessions.begin() as db:
        rows = await list_entries(db, AuditQuery(), limit=10_000)

    # Assert — the ceiling is applied in the query layer, not left to the router.
    assert len(rows) == 3


# ---------------------------------------------------------------------------
# The edges of the walk, and of the scrubber
# ---------------------------------------------------------------------------
async def test_an_empty_subject_id_is_refused_rather_than_stored_blank(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    # Arrange / Act / Assert — "" is not a subject; a row claiming one would be misleading.
    async with sessions.begin() as db:
        with pytest.raises(AuditValueRejectedError):
            await append(db, entry(subject_id=""), key=KEY, now=NOW)


async def test_blank_reason_text_is_stored_as_nothing_at_all(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    # Arrange / Act
    async with sessions.begin() as db:
        row = await append(db, entry(reason_text="   "), key=KEY, now=NOW)

    # Assert — whitespace is not a reason, and it must not start a 90-day clock.
    assert row.reason_text is None
    assert row.reason_expires_at is None


async def test_the_walk_continues_past_a_full_batch(
    sessions: async_sessionmaker[AsyncSession], monkeypatch: pytest.MonkeyPatch
) -> None:
    # Arrange — five rows over a batch size of two, so the walk has to carry the link across
    # three queries. The real batch is 500; forcing it here is what makes the seam testable
    # without writing 501 rows.
    await append_many(sessions, 5)
    monkeypatch.setattr(audit_module, "VERIFY_BATCH_SIZE", 2)

    # Act
    async with sessions.begin() as db:
        result = await verify_chain(db, key=KEY, is_dsn_configured=False)

    # Assert
    assert result.is_ok
    assert result.checked_rows == 5


async def test_a_walk_stopped_by_its_ceiling_does_not_claim_to_be_complete(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    # Arrange
    await append_many(sessions, 5)

    # Act
    async with sessions.begin() as db:
        result = await verify_chain(db, key=KEY, is_dsn_configured=False, max_rows=2)

    # Assert — a clean answer over part of the table is not a clean answer over the table.
    assert result.is_ok
    assert result.checked_rows == 2
    assert not result.is_complete


async def test_an_unreadable_privilege_probe_reports_the_weaker_guarantee(
    sessions: async_sessionmaker[AsyncSession], monkeypatch: pytest.MonkeyPatch
) -> None:
    # Arrange — the deployment claims the two-role setup and the probe cannot be run (here
    # because the statement is Postgres-only and the database is not).
    monkeypatch.setattr(audit_module, "_is_postgres", lambda _session: True)

    # Act
    async with sessions() as db:
        protection = await resolve_chain_protection(db, is_dsn_configured=True)

    # Assert — an unanswerable question is never answered with the stronger claim.
    assert protection is ChainProtection.HMAC_ONLY


# ---------------------------------------------------------------------------
# Postgres — the engine the REVOKE, the advisory lock and BIGSERIAL are real on
# ---------------------------------------------------------------------------
_POSTGRES_URL: Final[str] = os.environ.get(
    "HBD_TEST_POSTGRES_URL", "postgresql+asyncpg://hbd:hbd@localhost:5432/hbd_test"
)
_PROBE_ROLE: Final[str] = "hbd_audit_probe"
_PROBE_PASSWORD: Final[str] = "probe"


@pytest.fixture
async def pg_sessions() -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    """A real Postgres schema, dropped afterwards. Skips when no project Postgres answers."""
    engine = create_engine(_POSTGRES_URL)
    if not await ping(engine):
        await engine.dispose()
        pytest.skip(f"no Postgres at {_POSTGRES_URL}; run `docker compose up -d`")
    # Never drop_all a database this project did not create — the default URL is the port a
    # developer's unrelated Postgres is most likely to be listening on.
    await refuse_a_foreign_database(engine)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.drop_all)
        await connection.run_sync(Base.metadata.create_all)
    yield create_session_factory(engine)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.drop_all)
    await engine.dispose()


@pytest.mark.integration
async def test_the_chain_holds_and_catches_a_tamper_on_postgres(
    pg_sessions: async_sessionmaker[AsyncSession],
) -> None:
    # Arrange — three appends, each taking the advisory transaction lock, each getting its
    # sequence from a BIGSERIAL rather than from SQLite's ROWID.
    seqs = await append_many(pg_sessions, 3)
    async with pg_sessions.begin() as db:
        clean = await verify_chain(db, key=KEY, is_dsn_configured=False)
        await db.execute(
            sa.text("UPDATE admin_audit_log SET subject_type = 'user' WHERE seq = :seq"),
            {"seq": seqs[1]},
        )
    async with pg_sessions.begin() as db:
        tampered = await verify_chain(db, key=KEY, is_dsn_configured=False)

    # Assert
    assert clean.is_ok
    assert not tampered.is_ok
    assert tampered.first_break_seq == seqs[1]


@pytest.mark.integration
async def test_a_revoked_role_earns_the_stronger_claim_and_cannot_rewrite_a_row(
    pg_sessions: async_sessionmaker[AsyncSession],
) -> None:
    # Arrange — §12.4's two roles, built here as migration 0007 builds them: the owner keeps
    # the table, a separate login role gets everything except UPDATE, DELETE and TRUNCATE.
    await append_many(pg_sessions, 2)
    async with pg_sessions.begin() as owner:
        try:
            await _create_probe_role(owner)
        except ProgrammingError:
            pytest.skip("creating a role needs a superuser connection")

    probe = create_engine(
        f"postgresql+asyncpg://{_PROBE_ROLE}:{_PROBE_PASSWORD}@{_POSTGRES_URL.split('@', 1)[1]}"
    )
    try:
        async with create_session_factory(probe)() as db:
            # Act
            protection = await resolve_chain_protection(db, is_dsn_configured=True)
            with pytest.raises(ProgrammingError):
                await db.execute(sa.text("UPDATE admin_audit_log SET record_count = 1"))
    finally:
        await probe.dispose()
        async with pg_sessions.begin() as owner:
            await owner.execute(sa.text(f"DROP OWNED BY {_PROBE_ROLE}"))
            await owner.execute(sa.text(f"DROP ROLE IF EXISTS {_PROBE_ROLE}"))

    # Assert — the claim is earned from the database, not read from a setting.
    assert protection is ChainProtection.REVOKE_HMAC


async def _create_probe_role(owner: AsyncSession) -> None:
    """The application role of §4.5: everything on the log except the three write verbs."""
    await owner.execute(sa.text(f"DROP ROLE IF EXISTS {_PROBE_ROLE}"))
    await owner.execute(sa.text(f"CREATE ROLE {_PROBE_ROLE} LOGIN PASSWORD '{_PROBE_PASSWORD}'"))
    await owner.execute(sa.text(f"GRANT USAGE ON SCHEMA public TO {_PROBE_ROLE}"))
    await owner.execute(sa.text(f"GRANT SELECT, INSERT ON TABLE admin_audit_log TO {_PROBE_ROLE}"))
    await owner.execute(
        sa.text(f"REVOKE UPDATE, DELETE, TRUNCATE ON TABLE admin_audit_log FROM {_PROBE_ROLE}")
    )
