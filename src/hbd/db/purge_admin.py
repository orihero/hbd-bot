"""The three retention clocks the admin panel added, and the anchors that keep them honest.

These live beside :mod:`hbd.db.purge` rather than inside it for two reasons: that module is
already near the repo's file ceiling, and these three sweeps are the only ones that have to
know about Postgres privileges. Everything here is called from ``hbd.db.purge._purge``, in
the same transaction, so a failure takes the whole sweep back with it.

**Three clocks that were written and never run.** Slice 1b stamped
``admin_audit_log.reason_expires_at`` (90 days) and ``admin_audit_log.expires_at`` (730
days) on every audited action and read neither, and ``admin_sessions.expires_at`` had a
complete, documented, unit-tested sweep — ``sessions.purge_expired_sessions`` — with no
production caller at all. That is the exact defect the retention job was created to fix,
reproduced one table over. ``tests/test_db/test_audit_retention.py`` now asserts, from
``Base.metadata`` and the sweep predicates themselves, that no clock in the schema is
decorative.

**On a two-role Postgres this module cannot write to the audit table directly.** §12.4's
``REVOKE UPDATE, DELETE, TRUNCATE`` is the point of the design, and it blocks the sweep as
surely as it blocks an attacker. Migration 0007 therefore installs two ``SECURITY DEFINER``
functions owned by the migration role, and this module calls them when they exist. They take
**no cutoff**: the expiry is read from each row's own ``expires_at`` against the server
clock, so possessing EXECUTE on them is possession of "delete what is already legally due"
and never "delete whatever I name". The earlier signature took a caller-supplied cutoff,
which handed the application role an unbounded ``DELETE`` primitive against the one table it
was revoked from — a compromised app credential could erase the record of its own use and
``/audit/verify`` would still report ``revoke+hmac``.

**Anchors are written here because this is the only thing that legitimately shortens the
log.** A deletion the sweep made is recorded as a TRUNCATION anchor naming the surviving
row, and the current head is re-pinned as a HEAD anchor on every run. Without the first, a
730-day truncation is indistinguishable from an attacker excising the oldest rows; without
the second, excising the *newest* rows — the ones recording what the attacker just did —
leaves a shorter chain that verifies end to end. :func:`hbd.db.admin.audit.verify_chain`
checks both.
"""

from __future__ import annotations

from datetime import datetime

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from hbd.db.admin import sessions as session_store
from hbd.db.admin.audit import (
    PURGE_FUNCTION_NAME,
    REASON_PURGE_FUNCTION_NAME,
    write_head_anchor,
    write_truncation_anchor,
)
from hbd.db.models.admin_audit import AdminAuditRow
from hbd.db.models.admin_session import AdminSessionRow
from hbd.db.models.audit_anchor import AuditAnchorKind, AuditChainAnchorRow

__all__ = [
    "audit_reasons_due",
    "audit_rows_due",
    "admin_sessions_due",
    "purge_audit_reasons",
    "purge_audit_log",
    "purge_admin_sessions",
    "pin_audit_head",
]


def audit_reasons_due(now: datetime) -> sa.ColumnElement[bool]:
    """Rows whose 90-day operator free text is due. ``reason_purged_at`` makes it idempotent."""
    return sa.and_(
        AdminAuditRow.reason_expires_at.is_not(None),
        AdminAuditRow.reason_expires_at <= now,
        AdminAuditRow.reason_purged_at.is_(None),
        AdminAuditRow.reason_text.is_not(None),
    )


def audit_rows_due(now: datetime) -> sa.ColumnElement[bool]:
    """Rows past the 730-day accountability clock. Deleted outright, never nulled."""
    return AdminAuditRow.expires_at <= now


def admin_sessions_due(now: datetime) -> sa.ColumnElement[bool]:
    """Sessions past their absolute cap. Revoked-but-unexpired rows are evidence and stay."""
    return AdminSessionRow.expires_at <= now


def _is_postgres(session: AsyncSession) -> bool:
    return session.get_bind().dialect.name == "postgresql"


async def _definer_function(session: AsyncSession, signature: str) -> bool:
    """Whether migration 0007's ``SECURITY DEFINER`` helper exists on this database.

    A single-role deployment never gets one — 0007 skips the whole two-role block and says
    so — and then the plain statement below works, because nothing was revoked.
    """
    return bool(await session.scalar(sa.select(sa.func.to_regprocedure(signature))))


async def purge_audit_reasons(session: AsyncSession, *, now: datetime, limit: int) -> int:
    """Null the operator's free text once its own 90-day clock passes.

    The row survives: ``reason_code`` and ``reason_ref`` carry the accountability and are
    covered by the chain HMAC, while ``reason_text`` is deliberately excluded from it so
    this sweep does not break the chain every quarter (see
    :mod:`hbd.db.models.admin_audit`). ``reason_purged_at`` is stamped so "empty because
    swept" and "empty because none was given" stay distinguishable.
    """
    if _is_postgres(session) and await _definer_function(
        session, f"public.{REASON_PURGE_FUNCTION_NAME}(integer)"
    ):
        purged = await session.scalar(
            sa.text(f"SELECT public.{REASON_PURGE_FUNCTION_NAME}(:lim)"), {"lim": limit}
        )
        return int(purged or 0)
    due = list(
        (
            await session.execute(
                sa.select(AdminAuditRow.seq)
                .where(audit_reasons_due(now))
                .order_by(AdminAuditRow.seq)
                .limit(limit)
            )
        )
        .scalars()
        .all()
    )
    if not due:
        return 0
    await session.execute(
        sa.update(AdminAuditRow)
        .where(AdminAuditRow.seq.in_(due))
        .values(reason_text=None, reason_purged_at=now)
    )
    return len(due)


async def purge_audit_log(session: AsyncSession, *, now: datetime, limit: int) -> int:
    """Delete audited actions past 730 days, and record the cut as a truncation anchor.

    The anchor is what makes a legitimate truncation distinguishable from an excision
    (§5.5). It is written in the same transaction as the delete, so a chain can never be
    shortened without its explanation.
    """
    deleted = await _delete_expired_rows(session, now=now, limit=limit)
    if deleted == 0:
        return 0
    surviving = await session.scalar(sa.select(sa.func.min(AdminAuditRow.seq)))
    if surviving is not None:
        await write_truncation_anchor(
            session, below_seq=int(surviving), rows_deleted=deleted, now=now
        )
    return deleted


async def _delete_expired_rows(session: AsyncSession, *, now: datetime, limit: int) -> int:
    """The delete itself, through the ``SECURITY DEFINER`` helper where one exists.

    The helper takes no cutoff on purpose (see the module docstring), so on Postgres the
    boundary is the server clock rather than ``now``. Injected time still works everywhere
    the unit suite runs, and a Postgres deployment has no reason to sweep against anything
    but its own clock.
    """
    if _is_postgres(session) and await _definer_function(
        session, f"public.{PURGE_FUNCTION_NAME}(integer)"
    ):
        deleted = await session.scalar(
            sa.text(f"SELECT public.{PURGE_FUNCTION_NAME}(:lim)"), {"lim": limit}
        )
        return int(deleted or 0)
    due = list(
        (
            await session.execute(
                sa.select(AdminAuditRow.seq)
                .where(audit_rows_due(now))
                .order_by(AdminAuditRow.seq)
                .limit(limit)
            )
        )
        .scalars()
        .all()
    )
    if not due:
        return 0
    await session.execute(sa.delete(AdminAuditRow).where(AdminAuditRow.seq.in_(due)))
    return len(due)


async def purge_admin_sessions(session: AsyncSession, *, now: datetime, limit: int) -> int:
    """Delete admin sessions past their absolute cap.

    Thin, and deliberately so: ``sessions.purge_expired_sessions`` was already written,
    bounded and tested. What it never had was a caller, which is why the rows — carrying a
    token digest, a CSRF token and two operator IP addresses — accumulated forever.
    """
    return await session_store.purge_expired_sessions(session, now=now, batch_size=limit)


async def pin_audit_head(session: AsyncSession, *, now: datetime) -> None:
    """Re-pin the chain's head, replacing the previous pin.

    A tail deletion is invisible to a chain walk — the surviving rows still link — so the
    newest HEAD anchor is the only thing that says how far the log reached. It is refreshed
    every sweep, which means the undetectable window is one sweep interval wide. That is a
    real limit and it is stated rather than papered over: rows written since the last pin
    can still be excised without ``/audit/verify`` noticing.

    Exactly one HEAD anchor is kept. Only the newest pins the tail, and the full history of
    pins is in the log line :func:`hbd.db.admin.audit.write_head_anchor` emits for every
    one; keeping them all would grow a row an hour, forever, for no reader. TRUNCATION
    anchors are never touched — each one excuses a specific gap and must outlive it.
    """
    await session.execute(
        sa.delete(AuditChainAnchorRow).where(AuditChainAnchorRow.kind == AuditAnchorKind.HEAD)
    )
    await write_head_anchor(session, now=now)
