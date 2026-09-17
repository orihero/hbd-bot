-- Restore the two-role split on `hbd`: role `hbd` OWNS, role `hbd_app` holds DML only.
--
-- Run as the postgres superuser, against the application database:
--   sudo -u postgres psql -d hbd -v ON_ERROR_STOP=1 -f /tmp/fix-table-ownership.sql
--
-- WHY THIS IS NEEDED [HOST 2026-09-11]. `wipe-and-rebuild.sh` recreated the schema on
-- 2026-09-10 and ran the migrations as the APPLICATION role, so all 29 tables in `public` came
-- out owned by `hbd_app`, and `pg_class.relacl` is NULL on every one of them — no explicit
-- grant exists anywhere, because an owner needs none. Two consequences, and the second is the
-- serious one:
--
--   1. Role `hbd` cannot read `alembic_version`, so `alembic upgrade head` dies with
--      "permission denied for table alembic_version" and NO migration can run. That is what
--      stopped the cutover at step 5 on 2026-09-11.
--   2. **The audit log's immutability is not in force.** 07-security.md rests on `hbd_app`
--      being unable to rewrite `admin_audit_log`, and migration 0007 revokes
--      UPDATE/DELETE/TRUNCATE from it. A null ACL means that REVOKE was never materialised
--      (0007 guards it on a non-empty admin audit DSN), and ownership would have outranked it
--      regardless. The control has been absent since the rebuild.
--
-- ORDERING IS THE WHOLE DESIGN. `hbd_app` currently reaches these tables BY OWNERSHIP. Move
-- ownership first and every service loses its access in the same statement — an outage at the
-- database, not at boot. So: grant first, move ownership second, re-apply 0007's revocation
-- third (the blanket grant in step 1 would otherwise re-arm exactly what 0007 takes away), and
-- set default privileges last so the next migration does not recreate the problem.
--
-- SAFETY. One transaction: any failure leaves the database exactly as it was. `lock_timeout`
-- makes a blocked ALTER fail fast instead of queueing behind a long read and stalling every
-- service behind it — this runs against a LIVE fleet, so a pile-up is the realistic risk, not
-- a syntax error.
--
-- TO REVERSE, if something downstream disagrees: the mirror image is
--   ALTER ... OWNER TO hbd_app for each object, then REVOKE the grants below.
-- Ownership changes drop no data and no ACL; nothing here is destructive.

\set ON_ERROR_STOP on

BEGIN;

SET LOCAL lock_timeout = '5s';
SET LOCAL statement_timeout = '60s';

-- 1. Make explicit what ownership was providing implicitly. Must precede the ALTERs.
GRANT USAGE ON SCHEMA public TO hbd_app;
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO hbd_app;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO hbd_app;

-- 2. Transfer every relation in `public` to the owner role. Tables, partitioned tables,
--    sequences, views and materialised views are all `pg_class` rows and all need the right
--    ALTER verb; the CASE is not decoration, `ALTER TABLE` on a sequence is an error.
DO $$
DECLARE r record;
BEGIN
  FOR r IN
    SELECT c.relname, c.relkind
    FROM pg_class c
    JOIN pg_roles o ON o.oid = c.relowner
    WHERE c.relnamespace = 'public'::regnamespace
      AND c.relkind IN ('r', 'p', 'S', 'v', 'm')
      AND o.rolname <> 'hbd'
    ORDER BY c.relname
  LOOP
    EXECUTE format(
      'ALTER %s public.%I OWNER TO hbd',
      CASE r.relkind
        WHEN 'S' THEN 'SEQUENCE'
        WHEN 'v' THEN 'VIEW'
        WHEN 'm' THEN 'MATERIALIZED VIEW'
        ELSE 'TABLE'
      END,
      r.relname);
  END LOOP;
END
$$;

-- 3. Functions too. `hbd_purge_audit_log` and `hbd_purge_audit_reasons` are SECURITY DEFINER:
--    they execute as their OWNER, which is the entire mechanism by which the sweep deletes
--    from a table the application role may not touch. Owned by `hbd_app` that mechanism is
--    circular and meaningless. This loop is a no-op if 0007 skipped creating them.
DO $$
DECLARE r record;
BEGIN
  FOR r IN
    SELECT p.oid::regprocedure AS sig
    FROM pg_proc p
    JOIN pg_roles o ON o.oid = p.proowner
    WHERE p.pronamespace = 'public'::regnamespace
      AND o.rolname <> 'hbd'
  LOOP
    EXECUTE format('ALTER FUNCTION %s OWNER TO hbd', r.sig);
  END LOOP;
END
$$;

-- 4. Re-apply migration 0007's control, which step 1 just re-armed along with everything else.
--    INSERT and SELECT stay: the panel must be able to append and read. UPDATE, DELETE and
--    TRUNCATE are what make the chain rewritable, and they go.
REVOKE UPDATE, DELETE, TRUNCATE ON public.admin_audit_log FROM hbd_app;

-- 5. Stop this recurring. Objects created BY `hbd` from here on — i.e. by every future
--    migration — grant `hbd_app` its DML automatically, so a new table is never unreachable
--    to the application until somebody notices.
ALTER DEFAULT PRIVILEGES FOR ROLE hbd IN SCHEMA public
  GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO hbd_app;
ALTER DEFAULT PRIVILEGES FOR ROLE hbd IN SCHEMA public
  GRANT USAGE, SELECT ON SEQUENCES TO hbd_app;

COMMIT;
