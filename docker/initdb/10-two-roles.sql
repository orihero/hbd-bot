-- Two Postgres roles, so that revoking a privilege means something (ADMIN_PANEL_PLAN §4.5).
--
-- Run once, by the postgres:16-alpine entrypoint, on an EMPTY data volume only. Editing
-- this file does nothing to a container that already initialised; `docker compose down -v`
-- and up again is what re-runs it.
--
-- WHY TWO ROLES
--
-- `hbd` (POSTGRES_USER) creates every table, so it is the table OWNER. An owner can GRANT
-- back anything that was revoked from it, with one statement — so migration 0007's
--
--     REVOKE UPDATE, DELETE, TRUNCATE ON admin_audit_log FROM <app role>
--
-- is not a control at all when the app connects as the owner. It also has to be revoked
-- from someone: with one role there is nobody to name.
--
-- So: migrations run as `hbd` (BAYRAM_DB_MIGRATION_URL), and the bot, the worker and the admin
-- API connect as `hbd_app` (BAYRAM_DATABASE_URL). A compromised application credential can
-- then read and write the product's tables and still cannot rewrite the record of what
-- operators did. Leave BAYRAM_DB_MIGRATION_URL unset and everything still runs — migrations
-- fall back to BAYRAM_DATABASE_URL with a WARNING, 0007 skips the REVOKE, and /audit/verify
-- reports chainProtection "hmac-only". A control that is not deployed is reported as not
-- deployed, never implied.
--
-- THE PASSWORD BELOW IS A LOCAL DEVELOPMENT PASSWORD.
--
-- docker-compose.yml is the local dependency stack; it is not a production deployment. In
-- staging or production, create these two roles by hand with real secrets and put the two
-- DSNs in your secret store. Nothing about the grants changes.

\set ON_ERROR_STOP on

-- The application role. NOSUPERUSER/NOCREATEDB/NOCREATEROLE are spelled out rather than
-- left to the defaults, because the defaults are the thing this role exists to not have.
CREATE ROLE hbd_app WITH LOGIN PASSWORD 'hbd_app' NOSUPERUSER NOCREATEDB NOCREATEROLE;

GRANT CONNECT ON DATABASE hbd TO hbd_app;
GRANT USAGE ON SCHEMA public TO hbd_app;

-- Future tables: migrations have not run yet, so the grants that matter are the default
-- ones attached to the OWNER role. Without these, every table alembic creates from here on
-- is invisible to hbd_app and the bot fails on its first query with "permission denied".
ALTER DEFAULT PRIVILEGES FOR ROLE hbd IN SCHEMA public
    GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO hbd_app;
ALTER DEFAULT PRIVILEGES FOR ROLE hbd IN SCHEMA public
    GRANT USAGE, SELECT ON SEQUENCES TO hbd_app;
-- NOTE: there is deliberately NO `ALTER DEFAULT PRIVILEGES ... GRANT EXECUTE ON FUNCTIONS`
-- here. It used to be, so the retention sweep could call 0007's SECURITY DEFINER helpers —
-- but a blanket default makes EVERY future SECURITY DEFINER function automatically callable
-- by the application role, which is the opposite of what a SECURITY DEFINER function is for.
-- Migration 0007 grants EXECUTE on exactly the two sweep functions, by name, and those
-- functions take no cutoff: EXECUTE on them is the right to delete rows already past their
-- own `expires_at`, never the right to delete rows the caller names.

-- Anything that already exists (nothing, on a fresh volume — but this file must be safe to
-- re-run by hand against a migrated database).
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO hbd_app;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO hbd_app;

-- hbd_app may not create tables of its own: a schema change belongs to a migration, run as
-- the owner. Postgres 15+ already withholds CREATE on `public` from PUBLIC; this is stated
-- rather than assumed so the intent survives a base-image change.
REVOKE CREATE ON SCHEMA public FROM PUBLIC;
REVOKE CREATE ON SCHEMA public FROM hbd_app;
