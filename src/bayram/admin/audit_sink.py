"""The one way a router writes an audit row, and the reason there are two of them.

``bayram.db.admin.audit.append`` is the only writer of ``admin_audit_log`` and it stays that
way; this module is the thin layer between it and a FastAPI handler, so no route needs to
know about the HMAC key, the advisory lock or the ``AuditEntry`` shape.

**Two functions, because a refusal and a success need different transactions.**

``record`` writes into the **request's** transaction. That is right for an action that
succeeded: §12.6's rule is that a login which issues a session and then fails to audit
itself must leave neither, and ``bayram.admin.deps.get_db_session`` gives that for free by
committing on a clean exit.

``record_refusal`` opens a transaction of its **own** and commits it. That is right — and
necessary — for an action that is about to raise, because the request transaction rolls back
on the exception and would take the failure row with it. A failed login that leaves no trace
is the exact hole an audit log exists to close, so the row that records it cannot ride the
transaction that is being abandoned. It is a genuine trade: the row is committed slightly
before the refusal reaches the client, and if the process dies in between the client never
learns it was refused while the log says it was. That is the harmless direction of the two.

**Neither ever takes a route down.** ``append`` raises ``AuditValueRejectedError`` when a
value looks like a credential, and on the login route ``actor_username`` is whatever the
caller typed — an attacker can therefore choose a value that trips the refusal. A 500 on the
one unauthenticated route in the API, chosen by the caller, would be a worse bug than the one
being defended against, so a rejected value is logged at ERROR (the incident it is) and the
row is retried once with a placeholder username, which keeps the *event* recorded even when
the identifier cannot be. Everything else that goes wrong is logged and swallowed for the
same reason: the audit write must not become a new way to fail a request.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime
from typing import Final
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from bayram.admin.container import AdminContainer
from bayram.db.admin.audit import AuditEntry, AuditValueRejectedError, append
from bayram.db.enums import AdminRole, AuditAction, AuditReasonCode
from bayram.db.models.admin_audit import ACTOR_USERNAME_LENGTH, AuditOutcome
from bayram.logging import get_logger

__all__ = ["record", "record_refusal", "auth_entry", "UNSTORABLE_USERNAME"]

_LOGGER: Final = get_logger(__name__)

#: Stands in for a username ``append`` refused as credential-shaped. The event is still
#: recorded; only the identifier is replaced, and the ERROR line beside it carries the fact
#: that a refusal happened at all.
UNSTORABLE_USERNAME: Final[str] = "unstorable"


def auth_entry(
    action: AuditAction,
    *,
    username: str,
    role: AdminRole,
    outcome: AuditOutcome,
    actor_id: UUID | None = None,
    subject_id: str | None = None,
    field_names: tuple[str, ...] | None = None,
    error_code: str | None = None,
    ip: str | None = None,
) -> AuditEntry:
    """One authentication-family row, with the columns those five consumers actually fill.

    ``subject_type`` is ``"admin"`` for every one of them: the subject of a login, a logout,
    a password change and a step-up is the operator account itself. ``reason_code`` is
    ``ROUTINE_OPS`` because none of these is an investigation — the reason vocabulary exists
    for reveals and purges, and using ``OTHER`` here would make "other" the most common value
    in the table and therefore meaningless.
    """
    return AuditEntry(
        action=action,
        actor_id=actor_id,
        actor_username=username[:ACTOR_USERNAME_LENGTH],
        actor_role=role,
        subject_type="admin",
        subject_id=subject_id,
        field_names=field_names,
        reason_code=AuditReasonCode.ROUTINE_OPS,
        outcome=outcome,
        error_code=error_code,
        ip=ip,
    )


async def record(
    db: AsyncSession, container: AdminContainer, entry: AuditEntry, *, now: datetime
) -> None:
    """Audit a **successful** action inside the request's own transaction."""
    await _append(db, container, entry, now=now)


async def record_refusal(container: AdminContainer, entry: AuditEntry, *, now: datetime) -> None:
    """Audit an action that is about to be refused, in a transaction that will commit.

    Called immediately before the ``raise``. See the module docstring for why it cannot
    share the request's transaction.
    """
    try:
        async with container.session_factory.begin() as db:
            await _append(db, container, entry, now=now)
    except Exception:  # pragma: no cover - defensive; _append swallows its own
        _LOGGER.exception(
            "an audit row for a refused request could not be written",
            extra={"event": "admin.audit.write_failed", "action": str(entry.action)},
        )


async def _append(
    db: AsyncSession, container: AdminContainer, entry: AuditEntry, *, now: datetime
) -> None:
    """Append, retrying once with a placeholder when a caller-supplied value was refused."""
    key = container.settings.admin_audit_hmac_key.get_secret_value()
    try:
        await append(db, entry, key=key, now=now)
    except AuditValueRejectedError:
        # ERROR, not a warning: a credential-shaped value reaching the audit boundary is an
        # incident to surface. ``exception`` so the frame that built the entry is in the log.
        _LOGGER.exception(
            "an audited value was refused; the action is recorded without it",
            extra={"event": "admin.audit.value_refused", "action": str(entry.action)},
        )
    else:
        return
    await append(
        db,
        replace(entry, actor_username=UNSTORABLE_USERNAME, subject_id=None, ip=None),
        key=key,
        now=now,
    )
