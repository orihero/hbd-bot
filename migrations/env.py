"""Alembic environment. Async engine, config-sourced URL, no credentials on disk.

Three decisions worth knowing:

* **Migrations connect as the owner role when there is one.** ``HBD_DB_MIGRATION_URL`` is
  read first and ``HBD_DATABASE_URL`` is the fallback, with a WARNING naming what is not
  deployed. This is §4.5's two-role split, and without it the audit log's ``REVOKE`` in
  migration ``0007`` has nothing to revoke *from*: run as the application role, that role
  owns every table it created, and revoking a privilege from a table's owner is undone by
  that owner with one ``GRANT``. The variable is read from the environment rather than added
  to ``Settings`` on purpose — the bot and the worker must never hold the owner credential,
  and a field on the shared settings object is an invitation to.
* **The application DSN comes from ``hbd.config``, never from ``alembic.ini``.** One place
  configures a database, and a tracked file can never grow a password. A missing
  ``HBD_DATABASE_URL`` fails here with the same ``ConfigError`` the application would raise,
  naming the variable.
* **``render_as_batch=True``.** SQLite cannot ``ALTER TABLE`` in the ways a migration
  routinely needs; batch mode rewrites the table instead. Production is Postgres, where the
  flag is a no-op, but a migration that cannot run against the test database is a migration
  nobody exercises before it reaches production.

Nothing here ever logs a DSN: the WARNING names the variable that is unset and stops there,
because a connection string carries ``user:password@host`` and this line goes to whatever
ships the deploy log.

``compare_type`` is on so a widened column is caught by autogenerate rather than by a
truncation in production.

``render_item`` keeps application types out of the generated files. A migration that
imports ``hbd.db.base.UtcDateTime`` breaks the moment that class is renamed or moved — and
it breaks *historically*, on a migration that already ran everywhere, which is the worst
kind of breakage to debug. ``UtcDateTime`` is a ``timestamptz`` with a Python-side guard,
so the DDL it emits is exactly ``sa.DateTime(timezone=True)`` and that is what gets written.
"""

from __future__ import annotations

import asyncio
import logging
import os
from logging.config import fileConfig
from typing import Any, Final, Literal

from alembic import context
from alembic.autogenerate.api import AutogenContext
from sqlalchemy import Connection, pool
from sqlalchemy.ext.asyncio import async_engine_from_config

from hbd.config import load_settings
from hbd.db.base import UtcDateTime
from hbd.db.models import Base

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name, disable_existing_loggers=False)

#: Autogenerate compares the live database against this.
target_metadata = Base.metadata


def _render_item(type_: str, obj: Any, autogen_context: AutogenContext) -> str | Literal[False]:
    """Render our own column types as their plain SQLAlchemy equivalents.

    ``False`` means "no opinion, use Alembic's default rendering" — it is the documented
    sentinel, not a failure.
    """
    if type_ == "type" and isinstance(obj, UtcDateTime):
        return "sa.DateTime(timezone=True)"
    return False


#: The owner role's DSN. Set it and migrations run as the role that owns the tables, which
#: is what makes migration ``0007``'s ``REVOKE`` on ``admin_audit_log`` mean something
#: (§4.5, §12.4). Unset, everything still works and the panel reports the audit chain as
#: ``"hmac-only"`` — a control that is not deployed is reported as not deployed.
MIGRATION_URL_VAR: Final[str] = "HBD_DB_MIGRATION_URL"

_LOGGER: Final = logging.getLogger("alembic.env")

_SINGLE_ROLE_WARNING: Final[str] = (
    "%s is not set, so migrations are running as the application role. That role owns every "
    "table it creates, and an owner can GRANT back anything revoked from it — so the audit "
    "log's REVOKE is not a control on this deployment. See README 'Two Postgres roles'."
)


def _database_url() -> str:
    """The one place a migration learns where the database is, and as whom.

    The owner DSN wins when it is set; otherwise the application DSN is used and the WARNING
    says which control that costs. Falling back rather than refusing is deliberate: every
    existing dev setup has one role, and a migration runner that started failing on them
    would be a worse outcome than a one-role deployment that says so out loud.
    """
    owner = os.environ.get(MIGRATION_URL_VAR, "").strip()
    if owner:
        return owner
    _LOGGER.warning(_SINGLE_ROLE_WARNING, MIGRATION_URL_VAR)
    return load_settings().database_url


def run_migrations_offline() -> None:
    """Emit SQL to stdout without connecting. Used to review DDL before a release."""
    context.configure(
        url=_database_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
        render_as_batch=True,
        render_item=_render_item,
    )
    with context.begin_transaction():
        context.run_migrations()


def _run(connection: Connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        compare_type=True,
        render_as_batch=True,
        render_item=_render_item,
    )
    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    """Connect and migrate. ``NullPool`` because a migration runs once and exits."""
    section = config.get_section(config.config_ini_section, {})
    section["sqlalchemy.url"] = _database_url()
    engine = async_engine_from_config(section, prefix="sqlalchemy.", poolclass=pool.NullPool)
    try:
        async with engine.connect() as connection:
            await connection.run_sync(_run)
    finally:
        await engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())
