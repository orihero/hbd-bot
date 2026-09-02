"""Add admin_audit_log and audit_chain_anchors, and — where it can be real — the REVOKE.

Revision ID: 0007
Revises: 0006
Create Date: 2026-08-30

Both tables land together because neither is usable alone: an anchor pins a chain head, and a
chain with no way to record where it was truncated turns every retention sweep into an
indistinguishable "tamper" report.

**The two-role control ships whole or not at all.** ADMIN_PANEL_PLAN §12.4 asks for a
``REVOKE UPDATE, DELETE, TRUNCATE`` against the application role, so the process that writes
audit rows cannot rewrite them. That revoke also blocks the 730-day retention sweep, which is
why the ``SECURITY DEFINER`` function that legitimately works around it is created in **this
same revision**. Splitting them is the predictable failure: the revoke lands, the sweep fails
silently every hour, and an append-only table holding operator free text grows without bound.

**The revoke is applied only where it can mean something, and skipped loudly otherwise.**
Four conditions, all required:

1. the dialect is Postgres — on SQLite there is no privilege system to use;
2. ``HBD_ADMIN_AUDIT_DSN`` is non-empty, which is how a deployment declares that the separate
   owner role of §4.5 exists;
3. that application role actually exists in ``pg_roles``;
4. it is **not** ``current_user`` — revoking a privilege from a table's own owner is undone by
   that owner with one ``GRANT``, so a single-role deployment gains nothing and would be told
   it had gained something.

Any of them failing logs a WARNING naming the reason and continues. The migration never fails
for want of the two-role setup, and ``/audit/verify`` reports ``chainProtection: "hmac-only"``
by asking Postgres about the privileges rather than by trusting this file. A control that is
not deployed is reported as not deployed.

The role name is read from ``HBD_DB_APP_ROLE`` or, failing that, from the userinfo of
``HBD_DATABASE_URL``, and it is matched against a strict identifier pattern before it is ever
spliced into DDL — ``REVOKE`` takes no bind parameter for a role name, so the pattern is the
whole injection defence and a malformed value raises rather than being quoted and hoped for.

The enums are spelled out as non-native ``VARCHAR``s rather than imported from
``hbd.db.enums``: migrations must not import application code (a test asserts it), and a
native Postgres enum would make every later member a lock-taking ``ALTER TYPE``.
"""

from __future__ import annotations

import logging
import os
import re
from collections.abc import Sequence
from typing import Final
from urllib.parse import urlsplit

import sqlalchemy as sa
from alembic import op

revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None

_LOG: Final = logging.getLogger("alembic.runtime.migration")

_AUDIT = "admin_audit_log"
_ANCHORS = "audit_chain_anchors"

#: Declares that the separate owner role of §4.5 exists. Empty means it does not.
_AUDIT_DSN_ENV: Final[str] = "HBD_ADMIN_AUDIT_DSN"
#: The role the application connects as, and therefore the one the privileges are taken from.
_APP_ROLE_ENV: Final[str] = "HBD_DB_APP_ROLE"
_APP_DSN_ENV: Final[str] = "HBD_DATABASE_URL"
#: A SQL identifier, and nothing else. ``REVOKE`` accepts no bind parameter for a role.
_ROLE_PATTERN: Final[re.Pattern[str]] = re.compile(r"^[A-Za-z_][A-Za-z0-9_$]{0,62}$")

#: Mirrors ``hbd.db.admin.audit.PURGE_FUNCTION_NAME``, spelled literally because a migration
#: must keep working after the module it mirrors is refactored or deleted.
_PURGE_FUNCTION: Final[str] = "hbd_purge_audit_log"
_PURGE_SIGNATURE: Final[str] = f"{_PURGE_FUNCTION}(integer)"
#: The 90-day ``reason_text`` sweep is an ``UPDATE``, which the same REVOKE blocks, so it
#: needs its own definer function. 0007 originally shipped only the DELETE one, which is why
#: the reason clock had no way to run at all on a two-role deployment.
_REASON_PURGE_FUNCTION: Final[str] = "hbd_purge_audit_reasons"
_REASON_PURGE_SIGNATURE: Final[str] = f"{_REASON_PURGE_FUNCTION}(integer)"
#: A hard ceiling inside the function body. The caller supplies a batch size; it cannot
#: supply a licence to empty the table in one statement.
_MAX_PURGE_BATCH: Final[int] = 10_000
#: The legacy signature, which took a caller-supplied ``cutoff``. Dropped wherever it is
#: found: it handed the application role an unbounded DELETE against the very table the
#: REVOKE had just taken away from it.
_LEGACY_PURGE_SIGNATURE: Final[str] = f"{_PURGE_FUNCTION}(timestamptz, integer)"

_ADMIN_ROLES: Final[tuple[str, ...]] = ("owner", "admin", "support", "viewer")
_OUTCOMES: Final[tuple[str, ...]] = ("ok", "denied", "error")
_ANCHOR_KINDS: Final[tuple[str, ...]] = ("head", "truncation")
#: ``hbd.db.enums.AuditAction`` at revision 0007. Later members widen this list in a later
#: revision or, since the column is a plain ``VARCHAR(32)``, in none at all.
_ACTIONS: Final[tuple[str, ...]] = (
    "login.success",
    "login.failure",
    "login.limited",
    "logout",
    "step_up.success",
    "step_up.failure",
    "session.revoked",
    "reveal.personal",
    "asset.stream",
    "order.retry",
    "order.reenqueue",
    "order.deliver",
    "order.cancel",
    "user.block",
    "user.unblock",
    "user.purge.req",
    "user.purge.done",
    "user.purge.fail",
    "moderation.approve",
    "moderation.reject",
    "config.validate",
    "config.commit",
    "config.rollback",
    "retention.extended",
    "retention.run",
    "export.aggregate",
    "export.order",
    "export.audit",
    "admin.create",
    "admin.role",
    "admin.deactivate",
    "admin.password",
    "permission.denied",
)
_REASON_CODES: Final[tuple[str, ...]] = (
    "customer_request",
    "gdpr_erasure",
    "abuse_report",
    "support_investigation",
    "incident",
    "bake_off",
    "routine_ops",
    "other",
)

#: Deletes the oldest expired rows in one bounded batch and returns how many went. Owned by
#: the migration role, so it deletes despite the REVOKE; ``SET search_path`` is mandatory on
#: a ``SECURITY DEFINER`` function or the caller chooses which ``admin_audit_log`` it means.
#:
#: **It takes no cutoff, and that is the whole security property.** The first version
#: accepted ``cutoff timestamptz`` from the caller and granted EXECUTE to the application
#: role — which meant one compromised application credential could call
#: ``hbd_purge_audit_log('9999-01-01', 1000000)`` and erase the entire record of what it had
#: just done, while ``/audit/verify`` went on reporting ``chainProtection: "revoke+hmac"``.
#: That is precisely the theatre the REVOKE exists to remove. The expiry is now read from
#: each row's own ``expires_at`` against the server clock, so holding EXECUTE is the right to
#: delete what is already legally due and nothing else, and ``lim`` is clamped in the body so
#: a batch size cannot become a table-emptying primitive either.
_CREATE_PURGE_FUNCTION: Final[str] = f"""
CREATE OR REPLACE FUNCTION public.{_PURGE_FUNCTION}(lim integer)
RETURNS integer
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, public
AS $hbd$
DECLARE
    deleted integer;
    bounded integer;
BEGIN
    bounded := LEAST(COALESCE(lim, 0), {_MAX_PURGE_BATCH});
    IF bounded <= 0 THEN
        RETURN 0;
    END IF;
    WITH doomed AS (
        SELECT seq
        FROM public.admin_audit_log
        WHERE expires_at < now()
        ORDER BY seq
        LIMIT bounded
        FOR UPDATE SKIP LOCKED
    )
    DELETE FROM public.admin_audit_log AS a
    USING doomed AS d
    WHERE a.seq = d.seq;
    GET DIAGNOSTICS deleted = ROW_COUNT;
    RETURN deleted;
END;
$hbd$
"""

#: The 90-day reason sweep, same shape and same reasoning: no cutoff, a clamped limit, and a
#: predicate that can only ever touch rows whose own clock has passed. It nulls one column
#: and stamps another; it cannot rewrite anything the chain HMAC covers.
_CREATE_REASON_PURGE_FUNCTION: Final[str] = f"""
CREATE OR REPLACE FUNCTION public.{_REASON_PURGE_FUNCTION}(lim integer)
RETURNS integer
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, public
AS $hbd$
DECLARE
    purged integer;
    bounded integer;
BEGIN
    bounded := LEAST(COALESCE(lim, 0), {_MAX_PURGE_BATCH});
    IF bounded <= 0 THEN
        RETURN 0;
    END IF;
    WITH doomed AS (
        SELECT seq
        FROM public.admin_audit_log
        WHERE reason_expires_at IS NOT NULL
          AND reason_expires_at < now()
          AND reason_purged_at IS NULL
          AND reason_text IS NOT NULL
        ORDER BY seq
        LIMIT bounded
        FOR UPDATE SKIP LOCKED
    )
    UPDATE public.admin_audit_log AS a
    SET reason_text = NULL, reason_purged_at = now()
    FROM doomed AS d
    WHERE a.seq = d.seq;
    GET DIAGNOSTICS purged = ROW_COUNT;
    RETURN purged;
END;
$hbd$
"""


def _enum(values: tuple[str, ...], name: str) -> sa.Enum:
    return sa.Enum(*values, name=name, native_enum=False, length=32)


def _audit_columns() -> list[sa.Column[object]]:
    """Every column of ``admin_audit_log``, in the order §5.4 lists them."""
    return [
        sa.Column(
            "seq",
            sa.BigInteger().with_variant(sa.Integer, "sqlite"),
            autoincrement=True,
            nullable=False,
        ),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("actor_id", sa.Uuid(), nullable=True),
        sa.Column("actor_username", sa.String(length=64), nullable=False),
        sa.Column("actor_role", _enum(_ADMIN_ROLES, "adminrole"), nullable=False),
        sa.Column("action", _enum(_ACTIONS, "auditaction"), nullable=False),
        sa.Column("subject_type", sa.String(length=32), nullable=False),
        sa.Column("subject_id", sa.String(length=64), nullable=True),
        sa.Column("field_names", sa.JSON(), nullable=True),
        sa.Column("record_count", sa.Integer(), nullable=True),
        sa.Column("reason_code", _enum(_REASON_CODES, "auditreasoncode"), nullable=False),
        sa.Column("reason_ref", sa.String(length=64), nullable=True),
        sa.Column("reason_text", sa.String(length=500), nullable=True),
        sa.Column("reason_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("reason_purged_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("outcome", _enum(_OUTCOMES, "auditoutcome"), nullable=False),
        sa.Column("error_code", sa.String(length=48), nullable=True),
        sa.Column("correlation_id", sa.String(length=128), nullable=True),
        sa.Column("ip", sa.String(length=45), nullable=True),
        sa.Column("user_agent_hash", sa.String(length=64), nullable=True),
        sa.Column("config_version", sa.Integer(), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("prev_hmac", sa.String(length=64), nullable=True),
        sa.Column("chain_hmac", sa.String(length=64), nullable=False),
    ]


def _create_audit_table() -> None:
    op.create_table(
        _AUDIT,
        *_audit_columns(),
        # RESTRICT, not CASCADE: history that can be deleted by deleting its author is not
        # history. Operators are deactivated instead (§5.2).
        sa.ForeignKeyConstraint(
            ["actor_id"],
            ["admin_users.id"],
            name=op.f("fk_admin_audit_log_actor_id_admin_users"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("seq", name=op.f("pk_admin_audit_log")),
        sa.UniqueConstraint("id", name=op.f("uq_admin_audit_log_id")),
    )
    with op.batch_alter_table(_AUDIT, schema=None) as batch_op:
        for column in ("at", "actor_id", "subject_id", "correlation_id", "reason_expires_at"):
            batch_op.create_index(batch_op.f(f"ix_{_AUDIT}_{column}"), [column], unique=False)
        # The expiry sweep is one predicate over this column; the panel's default list is the
        # composite. Both are named by the convention in src/hbd/db/base.py.
        batch_op.create_index(batch_op.f(f"ix_{_AUDIT}_expires_at"), ["expires_at"], unique=False)
        batch_op.create_index(
            batch_op.f(f"ix_{_AUDIT}_action_at"), ["action", "at"], unique=False
        )


def _create_anchor_table() -> None:
    op.create_table(
        _ANCHORS,
        sa.Column(
            "id",
            sa.BigInteger().with_variant(sa.Integer, "sqlite"),
            autoincrement=True,
            nullable=False,
        ),
        sa.Column("at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("kind", _enum(_ANCHOR_KINDS, "auditanchorkind"), nullable=False),
        sa.Column("seq", sa.BigInteger(), nullable=False),
        sa.Column("chain_hmac", sa.String(length=64), nullable=False),
        sa.Column("truncated_below_seq", sa.BigInteger(), nullable=True),
        sa.Column("rows_deleted", sa.Integer(), nullable=True),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_audit_chain_anchors")),
    )
    with op.batch_alter_table(_ANCHORS, schema=None) as batch_op:
        batch_op.create_index(batch_op.f(f"ix_{_ANCHORS}_at"), ["at"], unique=False)


def _app_role() -> str | None:
    """The role to take privileges from, or ``None`` when the deployment does not say."""
    configured = os.environ.get(_APP_ROLE_ENV, "").strip()
    if configured:
        return configured
    dsn = os.environ.get(_APP_DSN_ENV, "").strip()
    if not dsn:
        return None
    return urlsplit(dsn).username or None


def _skip(reason: str, **context: object) -> None:
    _LOG.warning(
        "admin_audit_log REVOKE skipped: %s. The chain is HMAC-only on this deployment "
        "and /audit/verify will report chainProtection=hmac-only. Context: %s",
        reason,
        context,
    )


def _install_two_role_controls() -> None:
    """Apply the REVOKE and create the sweep function, or explain why neither happened."""
    if not os.environ.get(_AUDIT_DSN_ENV, "").strip():
        _skip(f"{_AUDIT_DSN_ENV} is not set, so no separate owner role exists")
        return
    role = _app_role()
    if role is None:
        _skip(f"neither {_APP_ROLE_ENV} nor a username in {_APP_DSN_ENV} names the app role")
        return
    if not _ROLE_PATTERN.match(role):
        raise ValueError(
            f"{_APP_ROLE_ENV} / {_APP_DSN_ENV} names {role!r}, which is not a SQL identifier; "
            "refusing to splice it into a REVOKE"
        )
    connection = op.get_bind()
    if not connection.execute(
        sa.text("SELECT 1 FROM pg_roles WHERE rolname = :role"), {"role": role}
    ).scalar():
        _skip("the application role does not exist in pg_roles", role=role)
        return
    if connection.execute(sa.text("SELECT current_user")).scalar() == role:
        _skip("migrations run as the application role, so a REVOKE from it is reversible by it")
        return
    _apply_revoke(role)


def _apply_revoke(role: str) -> None:
    """The two halves, in one place: take the privileges, then hand back the two sweeps.

    The grants are narrow by construction rather than by trust: neither function takes a
    cutoff, so EXECUTE on them cannot be turned into "delete a row I want gone". The blanket
    ``ALTER DEFAULT PRIVILEGES ... GRANT EXECUTE ON FUNCTIONS`` that used to sit in
    ``docker/initdb/10-two-roles.sql`` is gone for the same reason — it would have made every
    future ``SECURITY DEFINER`` function automatically callable by the application.
    """
    op.execute(f'REVOKE UPDATE, DELETE, TRUNCATE ON TABLE public.{_AUDIT} FROM "{role}"')
    for body, signature in (
        (_CREATE_PURGE_FUNCTION, _PURGE_SIGNATURE),
        (_CREATE_REASON_PURGE_FUNCTION, _REASON_PURGE_SIGNATURE),
    ):
        op.execute(body)
        op.execute(f"REVOKE ALL ON FUNCTION public.{signature} FROM PUBLIC")
        op.execute(f'GRANT EXECUTE ON FUNCTION public.{signature} TO "{role}"')
    _LOG.info(
        "admin_audit_log is append-only for role %s; the 730-day and 90-day sweeps run "
        "through SECURITY DEFINER functions public.%s and public.%s",
        role,
        _PURGE_SIGNATURE,
        _REASON_PURGE_SIGNATURE,
    )


def upgrade() -> None:
    _create_audit_table()
    _create_anchor_table()
    if op.get_bind().dialect.name == "postgresql":
        _install_two_role_controls()


def downgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        # Before the table: the function's body names it, and a dependency left behind is a
        # downgrade that only fails the second time it is run.
        op.execute(f"DROP FUNCTION IF EXISTS public.{_PURGE_SIGNATURE}")
        op.execute(f"DROP FUNCTION IF EXISTS public.{_REASON_PURGE_SIGNATURE}")
        op.execute(f"DROP FUNCTION IF EXISTS public.{_LEGACY_PURGE_SIGNATURE}")

    with op.batch_alter_table(_ANCHORS, schema=None) as batch_op:
        batch_op.drop_index(batch_op.f(f"ix_{_ANCHORS}_at"))
    op.drop_table(_ANCHORS)

    with op.batch_alter_table(_AUDIT, schema=None) as batch_op:
        batch_op.drop_index(batch_op.f(f"ix_{_AUDIT}_action_at"))
        for column in (
            "expires_at",
            "reason_expires_at",
            "correlation_id",
            "subject_id",
            "actor_id",
            "at",
        ):
            batch_op.drop_index(batch_op.f(f"ix_{_AUDIT}_{column}"))
    op.drop_table(_AUDIT)
