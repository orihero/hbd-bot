"""The chain must catch an attacker who DELETES rows, not only one who edits them.

Before this pass ``/audit/verify`` answered ``ok: true`` for a tail cut, a prefix cut and a
completely emptied table. Two causes, both here:

* ``_verify_batch`` seeded the first row of the walk with that row's OWN stored
  ``prev_hmac``, so any prefix cut was accepted unconditionally — the whole point of §5.5
  is telling a legitimate 730-day truncation from a deletion, and nothing compared the
  surviving head against an anchor;
* nothing pinned the head, so deleting the newest N rows (the ones recording what the
  attacker just did) left a shorter chain that still verified end to end.

The fix is anchors that are actually *checked*: a gap at the bottom is excused only by a
TRUNCATION anchor naming that exact surviving row, and a head below the newest HEAD anchor
is a break. Both anchors are written by the retention sweep, which is the only thing that
legitimately shortens this table.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Final

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from hbd.db.admin.audit import (
    AuditEntry,
    ChainVerification,
    append,
    verify_chain,
    write_head_anchor,
    write_truncation_anchor,
)
from hbd.db.enums import AdminRole, AuditAction, AuditReasonCode

KEY: Final[str] = "a-test-hmac-key-of-more-than-32-characters"
NOW: Final[datetime] = datetime(2026, 8, 30, 12, 0, tzinfo=UTC)


def _entry(index: int) -> AuditEntry:
    return AuditEntry(
        action=AuditAction.REVEAL_PERSONAL,
        actor_username="owner",
        actor_role=AdminRole.OWNER,
        subject_type="order",
        reason_code=AuditReasonCode.SUPPORT_INVESTIGATION,
        reason_ref=f"TICKET-{index}",
    )


async def _append_many(sessions: async_sessionmaker[AsyncSession], count: int) -> list[int]:
    seqs: list[int] = []
    for index in range(count):
        async with sessions.begin() as db:
            row = await append(db, _entry(index), key=KEY, now=NOW + timedelta(minutes=index))
            seqs.append(row.seq)
    return seqs


async def _delete(sessions: async_sessionmaker[AsyncSession], seqs: list[int]) -> None:
    async with sessions.begin() as db:
        await db.execute(
            sa.text("DELETE FROM admin_audit_log WHERE seq IN :seqs").bindparams(
                sa.bindparam("seqs", expanding=True)
            ),
            {"seqs": seqs},
        )


async def _verify(sessions: async_sessionmaker[AsyncSession]) -> ChainVerification:
    async with sessions.begin() as db:
        return await verify_chain(db, key=KEY, is_dsn_configured=False)


async def test_a_prefix_deleted_without_an_anchor_is_reported_as_a_break(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    # Arrange — six audited actions, then the oldest three excised with raw SQL.
    seqs = await _append_many(sessions, 6)
    await _delete(sessions, seqs[:3])

    # Act
    result = await _verify(sessions)

    # Assert — the surviving head claims a predecessor that no anchor excuses.
    assert result.is_ok is False
    assert result.first_break_seq == seqs[3]


async def test_a_prefix_deleted_by_the_sweep_and_anchored_still_verifies(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    # Arrange — the SAME cut, made the way the retention sweep makes it: with an anchor.
    seqs = await _append_many(sessions, 6)
    await _delete(sessions, seqs[:3])
    async with sessions.begin() as db:
        await write_truncation_anchor(db, below_seq=seqs[3], rows_deleted=3, now=NOW)

    # Act
    result = await _verify(sessions)

    # Assert — a legitimate truncation is not a tamper (§5.5).
    assert result.is_ok is True
    assert result.first_break_seq is None


async def test_an_anchor_that_names_a_different_row_does_not_excuse_the_gap(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    # Arrange — an anchor exists, but it pins a survivor that is no longer the survivor:
    # the attacker deleted one more row after the legitimate sweep ran.
    seqs = await _append_many(sessions, 6)
    await _delete(sessions, seqs[:3])
    async with sessions.begin() as db:
        await write_truncation_anchor(db, below_seq=seqs[3], rows_deleted=3, now=NOW)
    await _delete(sessions, [seqs[3]])

    # Act
    result = await _verify(sessions)

    # Assert
    assert result.is_ok is False
    assert result.first_break_seq == seqs[4]


async def test_a_deleted_tail_is_reported_as_a_break_against_the_head_anchor(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    # Arrange — six actions, the head pinned by a sweep, then the newest three excised.
    seqs = await _append_many(sessions, 6)
    async with sessions.begin() as db:
        await write_head_anchor(db, now=NOW)
    await _delete(sessions, seqs[3:])

    # Act
    result = await _verify(sessions)

    # Assert — this is the attack that matters: deleting the record of what you just did.
    assert result.is_ok is False
    assert result.first_break_seq == seqs[-1]


async def test_an_emptied_table_with_an_anchor_is_not_reported_as_clean(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    # Arrange
    seqs = await _append_many(sessions, 4)
    async with sessions.begin() as db:
        await write_head_anchor(db, now=NOW)
    await _delete(sessions, seqs)

    # Act
    result = await _verify(sessions)

    # Assert — zero rows checked is not a clean chain when a head was pinned.
    assert result.is_ok is False
    assert result.checked_rows == 0


async def test_an_untouched_table_with_a_current_head_anchor_still_verifies(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    # Arrange — the ordinary case: the sweep pinned the head and nobody touched anything.
    await _append_many(sessions, 4)
    async with sessions.begin() as db:
        await write_head_anchor(db, now=NOW)

    # Act
    result = await _verify(sessions)

    # Assert
    assert result.is_ok is True


async def test_rows_appended_after_the_head_anchor_are_not_a_break(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    # Arrange — an anchor is a floor, never a ceiling: the log keeps growing after it.
    await _append_many(sessions, 2)
    async with sessions.begin() as db:
        await write_head_anchor(db, now=NOW)
    await _append_many(sessions, 3)

    # Act
    result = await _verify(sessions)

    # Assert
    assert result.is_ok is True
    assert result.last_seq == 5


async def test_an_empty_table_that_was_never_anchored_is_still_clean(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    # Arrange — a brand new deployment. Nothing has happened yet, which is not a break.

    # Act
    result = await _verify(sessions)

    # Assert
    assert result.is_ok is True
    assert result.checked_rows == 0
