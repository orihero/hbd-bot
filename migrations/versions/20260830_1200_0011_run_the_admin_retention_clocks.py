"""Make the admin panel's three retention clocks executable, and disarm the DELETE primitive.

Revision ID: 0011
Revises: 0010
Create Date: 2026-08-30

Slice 1b stamped ``admin_audit_log.reason_expires_at`` (90 days) and
``admin_audit_log.expires_at`` (730 days) on every audited action and read neither, and
``admin_sessions.expires_at`` had a complete, tested sweep with no caller. This revision is
the schema half of fixing that: three counter columns on ``purge_runs``, so each new sweep is
recorded like every other, and — on Postgres — the two ``SECURITY DEFINER`` functions those
sweeps go through when §12.4's ``REVOKE`` is in force.

**The security fix, stated plainly.** 0007's original helper was
``hbd_purge_audit_log(cutoff timestamptz, lim integer)`` with ``EXECUTE`` granted to the
application role. Both arguments were caller-supplied and neither was bounded, so a single
compromised application credential could call it with a cutoff in the year 9999 and delete
every row of the audit log — the one table the ``REVOKE`` exists to protect — while
``/audit/verify`` went on reporting ``chainProtection: "revoke+hmac"``. This revision drops
that signature wherever it is found and installs replacements that take **no cutoff**: the
expiry is each row's own ``expires_at`` / ``reason_expires_at``, compared against the server
clock, and ``lim`` is clamped inside the body. Holding ``EXECUTE`` is now the right to delete
what is already legally due, and nothing else.

0007 itself was corrected in the same pass, so a database migrated from scratch never holds
the old function at all. Everything here is written to be a no-op in that case: this revision
is the repair path for a database already at 0010.

**And one data repair.** ``briefs.recipient_candidates`` was declared as a bare ``sa.JSON``,
so the identity sweep's ``= None`` persisted the JSON scalar ``null`` — four characters of
text — rather than SQL ``NULL``. The candidate orthographies really were destroyed, so this
is not a retention leak; what it broke is the proof, because ``recipient_candidates IS NULL``
answered *false* on a row that had been purged, and that predicate is what an erasure proof
is built from. The model now carries ``none_as_null=True``; this rewrites the rows that were
purged before it did.

The counter columns carry a ``server_default`` of ``0`` so existing rows get a value, and it
is dropped immediately afterwards on Postgres: the application always supplies the number,
and a lingering default would let a future insert that forgets one look like a sweep that
found nothing.
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

revision: str = "0011"
down_revision: str | None = "0010"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None

_LOG: Final = logging.getLogger("alembic.runtime.migration")

_PURGE_RUNS: Final[str] = "purge_runs"
_AUDIT: Final[str] = "admin_audit_log"
_BRIEFS: Final[str] = "briefs"

#: One per new sweep, in the order the sweeps run.
_NEW_COUNTERS: Final[tuple[str, ...]] = (
    "audit_reasons_purged",
    "audit_rows_deleted",
    "admin_sessions_deleted",
)

# -- the two-role gate, restated ------------------------------------------------------
# Spelled out again rather than imported from 0007: a migration must keep working after the
# revision beside it is edited, and Alembic revisions are not a module a later one may
# depend on. The four conditions are 0007's, verbatim in meaning.
_AUDIT_DSN_ENV: Final[str] = "HBD_ADMIN_AUDIT_DSN"
_APP_ROLE_ENV: Final[str] = "HBD_DB_APP_ROLE"
_APP_DSN_ENV: Final[str] = "HBD_DATABASE_URL"
_ROLE_PATTERN: Final[re.Pattern[str]] = re.compile(r"^[A-Za-z_][A-Za-z0-9_$]{0,62}$")

_PURGE_FUNCTION: Final[str] = "hbd_purge_audit_log"
_REASON_PURGE_FUNCTION: Final[str] = "hbd_purge_audit_reasons"
_PURGE_SIGNATURE: Final[str] = f"{_PURGE_FUNCTION}(integer)"
_REASON_PURGE_SIGNATURE: Final[str] = f"{_REASON_PURGE_FUNCTION}(integer)"
#: The signature this revision exists to remove.
_LEGACY_PURGE_SIGNATURE: Final[str] = f"{_PURGE_FUNCTION}(timestamptz, integer)"
_MAX_PURGE_BATCH: Final[int] = 10_000

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


def _app_role() -> str | None:
    configured = os.environ.get(_APP_ROLE_ENV, "").strip()
    if configured:
        return configured
    dsn = os.environ.get(_APP_DSN_ENV, "").strip()
    if not dsn:
        return None
    return urlsplit(dsn).username or None


def _revoked_role() -> str | None:
    """The role §12.4's REVOKE was applied to, or ``None`` when it was never applied."""
    if not os.environ.get(_AUDIT_DSN_ENV, "").strip():
        return None
    role = _app_role()
    if role is None:
        return None
    if not _ROLE_PATTERN.match(role):
        raise ValueError(
            f"{_APP_ROLE_ENV} / {_APP_DSN_ENV} names {role!r}, which is not a SQL identifier; "
            "refusing to splice it into a GRANT"
        )
    connection = op.get_bind()
    exists = connection.execute(
        sa.text("SELECT 1 FROM pg_roles WHERE rolname = :role"), {"role": role}
    ).scalar()
    if not exists:
        return None
    if connection.execute(sa.text("SELECT current_user")).scalar() == role:
        return None
    return role


def _install_safe_sweep_functions() -> None:
    """Drop the unbounded primitive, then install the two that cannot be aimed."""
    op.execute(f"DROP FUNCTION IF EXISTS public.{_LEGACY_PURGE_SIGNATURE}")
    role = _revoked_role()
    if role is None:
        # No two-role setup, so nothing was revoked and the sweep writes directly. Creating
        # a SECURITY DEFINER function here would add a privilege boundary where there is no
        # privilege to cross.
        _LOG.info(
            "audit sweep functions not installed: no separate owner role is configured, so "
            "%s is not revoked and the sweep writes to it directly",
            _AUDIT,
        )
        return
    for body, signature in (
        (_CREATE_PURGE_FUNCTION, _PURGE_SIGNATURE),
        (_CREATE_REASON_PURGE_FUNCTION, _REASON_PURGE_SIGNATURE),
    ):
        op.execute(body)
        op.execute(f"REVOKE ALL ON FUNCTION public.{signature} FROM PUBLIC")
        op.execute(f'GRANT EXECUTE ON FUNCTION public.{signature} TO "{role}"')
    _LOG.info(
        "the audit sweeps for role %s run through public.%s and public.%s, neither of which "
        "accepts a caller-supplied cutoff",
        role,
        _PURGE_SIGNATURE,
        _REASON_PURGE_SIGNATURE,
    )


def _repair_json_scalar_nulls() -> None:
    """Rewrite ``'null'`` to SQL ``NULL`` in ``briefs.recipient_candidates``.

    Two spellings because the comparison is dialect-specific: Postgres needs the column cast
    to text, SQLite stores the JSON as text already.
    """
    dialect = op.get_bind().dialect.name
    column = "recipient_candidates"
    predicate = f"{column}::text = 'null'" if dialect == "postgresql" else f"{column} = 'null'"
    op.execute(f"UPDATE {_BRIEFS} SET {column} = NULL WHERE {column} IS NOT NULL AND {predicate}")


def upgrade() -> None:
    with op.batch_alter_table(_PURGE_RUNS, schema=None) as batch_op:
        for name in _NEW_COUNTERS:
            batch_op.add_column(
                sa.Column(name, sa.Integer(), nullable=False, server_default="0")
            )
    if op.get_bind().dialect.name == "postgresql":
        # The default was only ever there to backfill. The application supplies every count,
        # and a surviving default would let a forgotten one read as "nothing was due".
        for name in _NEW_COUNTERS:
            op.alter_column(_PURGE_RUNS, name, server_default=None)
        _install_safe_sweep_functions()
    _repair_json_scalar_nulls()


def downgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        op.execute(f"DROP FUNCTION IF EXISTS public.{_PURGE_SIGNATURE}")
        op.execute(f"DROP FUNCTION IF EXISTS public.{_REASON_PURGE_SIGNATURE}")
    with op.batch_alter_table(_PURGE_RUNS, schema=None) as batch_op:
        for name in reversed(_NEW_COUNTERS):
            batch_op.drop_column(name)
