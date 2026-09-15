# Troubleshooting

Symptom first, because that is what you have. Each entry names what an operator actually sees,
what in the code produces it, one command that settles the question, and the fix.

The failure modes worth a runbook are the **silent** ones: the panel that looks healthy while a
control is off, the process that boots on defaults it should have refused, the job that logs
"skipped" in a shape indistinguishable from a job that never ran. Loud failures name their own
variable and need no page here.

> **What this document can and cannot know — REVISED 2026-09-10.** Every claim below still
> carries a `file.py:line` you can check in this checkout, and every check below still holds on
> any host. What has changed is that **one host is now reachable read-only**, so where a step
> used to end in a question there is often an answer beside it, marked with its date:
>
> | Marker | What it promises |
> | --- | --- |
> | *(unmarked)* | A claim about this repository's code. Open the cited file. |
> | `[HOST 2026-09-10]` / `[HOST 2026-09-11]` | A read-only command was run against `aizu` (machine `abdu-test`) on that date and the quote is faithful to its output. **One host, not all hosts** — yours may differ, and the unmarked check is the one to run. |
> | `[UNPROVEN]` | Nobody has established it, with the blocker named. |
>
> The blanket disclaimer this box used to carry — "nothing here describes the production host,
> not its paths, not its service manager, not what terminates its TLS" — is withdrawn as
> *blanket*. Those three are now known for `abdu-test`: four systemd units (`hbd-bot`,
> `hbd-worker`, `hbd-admin`, `hbd-payme`), `WorkingDirectory=/var/lib/hbd`,
> `EnvironmentFile=/etc/hbd/*.env`, a wheel in `/opt/hbd/venv`, and TLS terminated **at
> Cloudflare's edge** with a tunnel speaking plain HTTP to Caddy on loopback (`00-host-inventory.md`
> rows 17 and 39–43). `deploy/systemd/*.service` are no longer only a proposal — near-identical
> units are installed and running — but `deploy/first-install-proposal.md` still is one, and
> commands quoted from it are still marked as such.
>
> Where a command below curls `http://127.0.0.1:8080`, that is the address `Makefile:75` uses —
> and `[HOST 2026-09-11]` it is also, as it happens, where the panel really listens
> (`127.0.0.1:8080`, with the gateway on `127.0.0.1:8091`). That is a fact about this host, not
> about the package: nothing in the package binds a socket and
> `BAYRAM_ADMIN_HOST`/`BAYRAM_ADMIN_PORT` are read by nothing that does (see §19).

> **PRE-REQUISITE: HOW TO READ A LOG LINE, AND THE HOST'S NAMING.** Every grep below is written
> `... | grep <event>` because the repository cannot know what collects a process's stdout.
> `[HOST 2026-09-11]` On `abdu-test` it is **the systemd journal and nothing else**, and
> `developer` is in `adm`, so no `sudo` is needed. That one line makes half the checks in this
> document executable in five seconds:
>
> ```bash
> ssh aizu 'journalctl -u hbd-admin  -o cat | grep admin.boot.ok'
> ssh aizu 'journalctl -u hbd-worker -o cat | grep "retention sweep finished"'
> ssh aizu 'journalctl -u hbd-bot    -o cat | grep "host verified"'
> ssh aizu 'journalctl -u hbd-payme  -o cat | grep payme.boot.ok'
> ```
>
> Two caveats, both of which have cost somebody time. **The host is PRE-RENAME**: units are
> `hbd-*`, paths are `/etc/hbd` and `/opt/hbd`, the importable package is `hbd`, variables are
> `HBD_*`. Every `python -m bayram.…` and `BAYRAM_…` below is typed `hbd` / `HBD_` at a shell on
> that box, and that is correct rather than stale — see `08-payme.md`'s NAMING note. And
> **`journalctl -u hbd-worker | jq` fails on every other line**: arq logs each line twice, once
> as its own plain text and once inside our JSON envelope, because `arq/cli.py:44-45` applies
> `dictConfig` after our `configure_logging()` has run and overwrites the `_NOISY_LOGGERS` floor
> (logging.py:100-113). Pipe through `grep '^{'` first. The gateway's journal carries uvicorn's
> plain `INFO:` lines for the same reason. §18 has the detail.

Throughout, the three long-running processes are the ones the Makefile defines, and there is no
console script for any of them — `pyproject.toml` has no `[project.scripts]` table, so `python -m`
is the only invocation (Makefile:69, Makefile:72, Makefile:75):

```bash
<venv>/bin/python -m bayram.main                                    # the bot, aiogram long polling
<venv>/bin/python -m arq bayram.worker.WorkerSettings               # the ARQ worker
<venv>/bin/python -m uvicorn bayram.admin.app:app --host 127.0.0.1 --port 8080   # the admin API
```

---

## 1. Modals stop locking the background; everything else looks fine

**SYMPTOM.** The console renders, sign-in works, data loads. But open any dialog and the page
keeps scrolling underneath it. No error banner, no failed request, no 500. In a PROD bundle the
browser console carries one `console.error` and nothing else.

**LIKELY CAUSE.** The deployed console bundle predates the CSP style-nonce placeholder, or the
deploy did not rebuild it. `admin-ui/index.html` carries `__BAYRAM_CSP_NONCE__` in a
`<meta name="csp-nonce">`, and the API substitutes this response's nonce into it per request
(shell.py:55, shell.py:86). A shell with no placeholder is served **unchanged** with a single
WARNING — deliberately, not by accident: shell.py:65-77 argues that an operator reaching for the
panel mid-incident is better served by a panel whose modals do not lock than by a 500. The cost is
that this is the only signal. Without the nonce, `style-src 'self' 'nonce-…'` blocks the `<style>`
element `react-remove-scroll` injects for every Radix modal.

`src/bayram/admin/static/` is gitignored (app.py:124-128), so the bundle on any host is whatever the
last `npm run build` left behind. Nothing gates it: `tests/test_admin/test_spa_nonce.py:49` checks
the **checked-in source** `admin-ui/index.html`, not the built artefact, and `make ui-e2e` rebuilds
before it runs (Makefile:112). The placeholder-drift check and the staleness check are different
checks, and only the first exists.

**HOW TO CONFIRM.** Grep the admin process's log for the one event:

```bash
# whatever collects the admin process's stdout on that host
... | grep admin.spa.nonce_placeholder_missing
```

Or ask the served shell directly, from the host, past the proxy:

```bash
curl -s http://127.0.0.1:8080/ | grep -o 'csp-nonce[^>]*'
```

Read the `content` attribute, not a match count — `grep -c` prints `1` for every case below in
which the meta element is present at all, which is most of them.

| What comes back | What it means |
| --- | --- |
| `content="<a base64url value>"` | Healthy. |
| `content=""` | The shell rendered with an **empty** nonce, so `SecurityHeadersMiddleware` was not in the stack. `_serve_spa_index` reads the nonce off the ASGI scope with a `""` default deliberately, "so a shell served by an application assembled without SecurityHeadersMiddleware renders an empty nonce instead of raising" (app.py:240-244). That response carries no CSP either. |
| `content="__BAYRAM_CSP_NONCE__"` | **This route did not serve that HTML.** `render_shell` substitutes the placeholder unconditionally whenever it is present (shell.py:78-86), so this code path can never emit the literal. A proxy or a stale CDN copy is serving `index.html` itself — which is what the SPA's own `console.error` says (`admin-ui/src/lib/csp.ts`, `installCspNonce`). |
| no output at all | A bundle built before the placeholder existed. This is the case that logs `admin.spa.nonce_placeholder_missing`. |

**FIX.** It depends on which of two deployment shapes you are on, and **that is the first thing
to establish** because on one of them the rebuild command does not exist. One line answers it:

```bash
which npm && echo "BUILD-IN-PLACE"                                       # a checkout that builds
ls <site-packages>/<pkg>/admin/static/index.html && echo "WHEEL SHAPE"   # a bundle in the wheel
```

* **A checkout that builds in place.** Rebuild the console and restart nothing — the shell is
  read from disk per request (app.py:249) and is deliberately outside the immutable cache
  prefix:

  ```bash
  cd <checkout>/admin-ui && npm ci && npm run build   # writes ../src/bayram/admin/static/
  ```

* **A wheel host.** There is nothing to rebuild *here*: the bundle is force-included in the
  wheel (`pyproject.toml:60-65`), so the fix belongs to **the machine that builds the wheel**,
  and the deployment step is to rebuild the wheel, reinstall it and restart the unit. Running
  `npm` on the host is not an option to fall back on.

> **`abdu-test` IS THE WHEEL SHAPE, AND `npm run build` IS IMPOSSIBLE THERE.**
> `[HOST 2026-09-11]` `which node npm` returns nothing — there is no Node on the box.
> `/srv/hbd` does not exist; there is no checkout at all. The bundle ships inside the installed
> wheel at `/opt/hbd/venv/lib/python3.12/site-packages/hbd/admin/static/` — `index.html` 636
> bytes plus `assets/`, all root-owned, dated Sep 10 00:01 — with 23 `admin/static` entries in
> `hbd_bot-0.1.0.dist-info/RECORD`. So **every "rebuild the console" instruction in §1 and §2
> has to be re-aimed at the build machine on this host**, and `07-security.md` §2's open question
> — checkout-that-builds-in-place versus installed wheel — is answered for `abdu-test`. The
> release runbook for that is `08-payme.md` §11.

> **Rebuild on every deploy, unconditionally.** A git pull does not update the console, because the
> bundle is not in git. The rebuild is the only mechanism keeping the served JavaScript in step
> with the Python that serves it — whichever machine performs it.

---

## 2. Every browser URL returns 404 while `/healthz` returns 200

**SYMPTOM.** `GET /` and every SPA route answer 404. The API answers normally. Liveness probes
pass. The process looks perfectly healthy at the process level.

**LIKELY CAUSE.** No console bundle at all. The SPA catch-all refuses when `index.html` is absent —
`if not SPA_INDEX.is_file(): raise HTTPException(status_code=404)` (app.py:238-239) — and the static
mount is deliberately `check_dir=False` so a missing directory is not a boot failure. A fresh
checkout with `make install` and no `make ui-build` is exactly this state: `make install` sets up
Python only (Makefile:58-60), and `make check` touches neither Node nor the bundle (Makefile:144).

**HOW TO CONFIRM.** Ask wherever the bundle is meant to be — a checkout, or inside the installed
package:

```bash
ls -la <checkout>/src/bayram/admin/static/index.html          # build-in-place
ls -la <site-packages>/<pkg>/admin/static/index.html          # wheel shape
```

`[HOST 2026-09-11]` On `abdu-test` the second form is the live one and it answers:
`/opt/hbd/venv/lib/python3.12/site-packages/hbd/admin/static/index.html`, 636 bytes, root-owned,
Sep 10 00:01. The bundle is present and correct there, so §2 is **not** the diagnosis on this
host today.

**FIX.** See §1's FIX — the two shapes and the one-line test that tells them apart. On a
build-in-place host, `cd <checkout>/admin-ui && npm ci && npm run build`. On a wheel host, rebuild
and reinstall the wheel. Note that the repo installs no Node anywhere: `admin-ui/package.json`
declares `"engines": {"node": ">=20.19"}` and `admin-ui/package-lock.json` is lockfileVersion 3
(npm 7+), and how Node reaches the *build* machine is still an open question this repo cannot
answer — `[HOST 2026-09-11]` on `abdu-test` it never needs to, because Node is absent and the
bundle arrives pre-built.

---

## 3. `/audit/verify` reports `chainProtection: "hmac-only"`

**SYMPTOM.** The Audit screen shows the chain verifying, but protection reads `hmac-only` rather
than `revoke+hmac`. The admin log carries `admin.audit.revoke_missing` at WARNING — or nothing at
all, which is a different diagnosis.

> **`abdu-test` IS THIS SYMPTOM, TODAY, AND IT IS THE ONE OPEN SECURITY FINDING ON THE HOST.**
> `[HOST 2026-09-10]` `hbd-admin` logged `admin.audit.revoke_missing` **twice**, at 09:29:50 and
> 12:36:59 +05, message verbatim: *"the audit REVOKE is configured but not in force; the app role
> can still write"* (logger `hbd.db.admin.audit`). Zero `admin.audit.privilege_probe_failed`;
> zero `admin.audit.chain_broken`, ever. That is **row 2** of the table below: the DSN is set and
> the probe says this connection can still write the log.
>
> Two cautions about how to state it. **(1)** Nobody has read `chainProtection` directly —
> `/api/audit/verify` needs an ADMIN or OWNER session and `/api/config` answers 401
> `UNAUTHENTICATED` without a cookie — so the honest sentence is "the panel logged the WARNING
> that accompanies `hmac-only`", not "the panel reported `hmac-only`". **(2)** The WARNING fires
> only when somebody *calls* `/api/audit/verify`. Two hits in the whole journal means the endpoint
> has been read twice, ever. **Absence of this line is evidence nobody looked, not evidence of
> health** — and on a host whose logs go to the journal and nowhere else (§19), that is the
> normal state.

**LIKELY CAUSE.** This value is asked of Postgres, not read from configuration
(`has_table_privilege(current_user, 'admin_audit_log', 'UPDATE' / 'DELETE' / 'TRUNCATE')`,
audit.py:779-805). Four distinct situations produce the same word, and the log line separates them
(audit.py:789-805):

| What you see | What it means |
| --- | --- |
| `hmac-only`, **no** WARNING | `BAYRAM_ADMIN_AUDIT_DSN` is unset, so the panel never probed. A supported deployment (settings.py:229-235) — the two-role split was never declared. |
| `hmac-only` + `admin.audit.revoke_missing` | The DSN is set, so somebody believes the split is deployed, and the probe says this connection can still write the log. The REVOKE did not land, or the admin connects as the wrong role. |
| `hmac-only` + `admin.audit.privilege_probe_failed` | The probe query itself errored. The weaker guarantee is reported rather than guessed. |
| `hmac-only` on a non-Postgres backend | Not applicable; reported honestly. |

The most likely root cause for the second row is that **migration 0007 skipped its own REVOKE**.
Its three deciding variables are read from `os.environ` and nowhere else:
`BAYRAM_ADMIN_AUDIT_DSN` (0007:336), then `BAYRAM_DB_APP_ROLE` or a username parsed out of
`BAYRAM_DATABASE_URL` (0007:314-322). None of them is read from a dotenv file. `migrations/env.py`
deliberately *does* fall back to the dotenv file for `BAYRAM_DB_MIGRATION_URL` (env.py:107-114) —
env.py:14-19 records that the environment-only version was a bug that would have migrated
production as the wrong role — and that fix was never carried into the two migration bodies that
need the same thing. `BAYRAM_ADMIN_AUDIT_DSN` is documented in `.env.admin.example:130`, a file the
alembic runner never loads. `BAYRAM_DB_APP_ROLE` appears in neither example file at all.

The skip is a WARNING in alembic's output, not a failure (0007:325-331):

```
admin_audit_log REVOKE skipped: BAYRAM_ADMIN_AUDIT_DSN is not set, so no separate owner role
exists. The chain is HMAC-only on this deployment and /audit/verify will report
chainProtection=hmac-only.
```

**HOW TO CONFIRM.** Three routes, cheapest first, and **say plainly which ones need a password**
— on a locked-down host only the first is reachable:

```bash
# 1. NO credential needed. The cheapest signal there is.
ssh aizu 'journalctl -u hbd-admin -o cat | grep admin.audit.revoke_missing'
```

```sql
-- 2. Needs the DATABASE password, as the owner role.
\dp admin_audit_log
-- the application role should hold SELECT and INSERT, and NOT UPDATE/DELETE/TRUNCATE
SELECT has_table_privilege('<the application role>', 'admin_audit_log', 'UPDATE');  -- want: f
SELECT tableowner FROM pg_tables WHERE tablename = 'admin_audit_log';               -- want: the OWNER
\df public.hbd_purge_audit_*                         -- both SECURITY DEFINER functions present?
```

Route 3 is `GET /api/audit/verify` → `chainProtection`, which needs an ADMIN or OWNER session.

> **On `abdu-test`, routes 2 and 3 are both behind a wall, and this is worth knowing BEFORE an
> incident.** `[HOST 2026-09-11]` `/etc/hbd` is `Permission denied` to `developer`, so no DSN is
> obtainable; `sudo -n -u postgres psql` answers `sudo: a password is required`; there is no
> `~/.pgpass`; Postgres listens on `127.0.0.1:5432` with password auth.
>
> **But three of those four questions do not need that password, and were answered on
> 2026-09-11.** The world-readable `pg_dump` files in `/var/backups/hbd` carry the grants and the
> ownership, and the absence of any `CREATE FUNCTION` in them settles the purge functions:
> `[HOST 2026-09-11]` 29 tables, every one `OWNER TO hbd_app`, `GRANT ALL … TO hbd_app` only, and
> **neither `hbd_purge_audit_log` nor `hbd_purge_audit_reasons` exists.**
> `00-host-inventory.md` row 14 and `03-provisioning.md` §4 carry them with their commands.
> **Only the LIVE privilege question — `has_schema_privilege` right now — still wants the
> password.** Reach for a dump before reaching for a credential.
>
> **The host already carries the script that asks three of those four questions.**
> `/opt/hbd/diagnose.sh` (world-readable, owned by `developer`) runs four
> `sudo -u postgres env LC_ALL=C psql -d hbd -At` queries:
> `has_schema_privilege('hbd','public','CREATE')`, the same for `USAGE`, the `alembic_version`
> owner, and every distinct `tableowner` in schema `public`. It needs exactly one sudo password.
> **And there is a trap beside it:** `/opt/hbd/deploy-payme.sh` is now a 434-byte wrapper whose
> header comment says it runs the `hbd`→`bayram` cutover and whose only executable line is
> `exec /usr/bin/bash /opt/hbd/diagnose.sh "$@"`. The filename, the comment and the code disagree
> three ways. Read it before you run it.
>
> **Whether the roles `hbd` and `hbd_app` exist was answered on 2026-09-11 — `[HOST]`, both
> exist — but only after a tempting wrong proof was killed, and the wrong proof is the part worth
> carrying.** Over TCP, Postgres answers `FATAL: password authentication failed
> for user "…"` for a wrong password **and for a role that does not exist, identically** —
> verified 2026-09-11 by probing a deliberately invented role name and getting the same refusal
> as `hbd_app`. (A local-socket attempt as `developer` does answer `role "developer" does not
> exist`, but that distinction does not carry over to the TCP password path.) Do not read that
> message as proof a role is there.
>
> **What does settle it costs nothing:** the Postgres server log is `adm`-readable, `developer` is
> in `adm`, and `log_line_prefix` carries role and database on every attributed line. **Read the
> `DETAIL`, not the `FATAL`** — a missing role's says `Role "…" does not exist.`, an existing
> role's names only the `pg_hba.conf` line. `00-host-inventory.md` row 12 carries the command.

And check which role the panel itself connects as — the probe asks about `current_user`, so an
admin process pointed at the **owner** DSN reports `hmac-only` *and* can rewrite the table the
control protects. `.env.admin.example:48` ships the owner DSN
(`postgresql+asyncpg://hbd:hbd@…`) while `.env.example:35` ships the application one
(`hbd_app`), and README.md:160-161 and `docker/initdb/10-two-roles.sql` both say all three
processes connect as `hbd_app`. That is a defect in the example file; a host that copied it
verbatim inherited it.

**FIX.** Which fix applies depends on whether 0007 has already run against this database, and
that is host state you must establish first — `SELECT version_num FROM alembic_version;` and
whether `admin_audit_log` exists. The two cases are genuinely different, because the REVOKE lives
only inside `upgrade()` (0007:386-390) and alembic runs `upgrade()` once per revision, ever.

**(a) 0007 has not been applied yet.** Export all four variables **into the shell**, not merely
into a file — the two the migration body reads come from `os.environ` only, and the migration
runner needs the owner DSN or it repeats §12:

```bash
cd <checkout>
export BAYRAM_DB_MIGRATION_URL='postgresql+asyncpg://<owner>:…@<host>:<port>/<db>'  # or §12 happens
export BAYRAM_ADMIN_AUDIT_DSN='postgresql+asyncpg://<owner>:…@<host>:<port>/<db>'   # the OWNER dsn
export BAYRAM_DATABASE_URL='postgresql+asyncpg://<app>:…@<host>:<port>/<db>'        # or BAYRAM_DB_APP_ROLE=<app>
BAYRAM_ENV_FILE=<the bot env file> <venv>/bin/python -m alembic \
  -c migrations/alembic.ini upgrade head
```

`BAYRAM_DB_MIGRATION_URL` is the one the doc's earlier drafts omitted and it is not optional here:
`migrations/env.py` reads the owner DSN from that variable alone (env.py:96-114), and without it
`_database_url` falls back to `load_settings().database_url` and connects as the application role
(env.py:117-129) — at which point 0007 skips its own REVOKE anyway, because "migrations run as the
application role, so a REVOKE from it is reversible by it" (0007:355-356).

**(b) 0007 is already applied — the deployment §3 describes, and the one `abdu-test` is in.**
`alembic upgrade head` is a **no-op** on this database and will not re-run the REVOKE, however the
environment is exported. The controls have to be applied by hand, as the **owner** role.

> **THE ORDER MATTERS, AND NO DOCUMENT USED TO SAY SO. Create the two functions FIRST, then
> REVOKE.** Getting it backwards turns a missing control into a *failing hourly sweep*, which is
> strictly worse: you lose the retention job's two audit clocks as well as the protection you
> were trying to add.
>
> Here is the mechanism, because the old wording here overstated it in a way that matters.
> `purge_admin.py` **probes** for the `SECURITY DEFINER` helper with `_definer_function`
> (purge_admin.py:90, called at :108 and :163) and falls back to an ordinary ORM
> `UPDATE`/`DELETE` when it is absent. So:
>
> | REVOKE | Functions | What the hourly sweep does |
> | --- | --- | --- |
> | absent | absent | **Works.** The fallback path runs as an owning role that may still delete. `[HOST 2026-09-11]` This is `abdu-test`: `audit_reasons_purged: 0, audit_rows_deleted: 0` every hour, cleanly. |
> | present | present | **Works**, through the functions. The intended state. |
> | **present** | **absent** | **BREAKS at the two audit clocks.** The fallback tries a direct `DELETE` the role no longer holds. |
> | absent | present | Works through the functions; the protection simply is not there. |
>
> The old sentence here — "without those, the REVOKE lands and the 730-day and 90-day audit
> sweeps have no way to run as the application role" — was true only of row 3, and read as though
> it were true of any host missing the functions. It is the **combination** that breaks.

```sql
-- as the OWNER role, and in this order.
-- 1. The two SECURITY DEFINER sweeps. Take their bodies verbatim from _apply_revoke
--    (migration 0007:360-383) rather than retyping them: the function also revokes each from
--    PUBLIC and grants EXECUTE to the application role, and both halves matter.
--    public.hbd_purge_audit_log(integer)  /  public.hbd_purge_audit_reasons(integer)
-- 2. Only then:
REVOKE UPDATE, DELETE, TRUNCATE ON TABLE public.admin_audit_log FROM "<the application role>";
```

That last statement is the control `chainProtection` probes for, and it is enough to flip the
value. Check ownership too: a table owned by the application role can `GRANT` back anything
revoked from it, so `ALTER TABLE … OWNER TO <owner>` may be needed first (§12).

In both cases: set the admin process's `BAYRAM_DATABASE_URL` to the **application** role and restart
it, then confirm `chainProtection` flips to `revoke+hmac`.

> **ON `abdu-test` THE ROOT CAUSE IS A SCRIPT, SO THE NEXT REBUILD WILL REPRODUCE IT.**
> `[HOST 2026-09-11]` The database was dropped and re-migrated at ~09:25 on 2026-09-10 by
> `/opt/hbd/release/wipe-and-rebuild.sh`. Its step 3 runs `DROP SCHEMA public CASCADE; CREATE
> SCHEMA public; GRANT ALL ON SCHEMA public TO ${APP_ROLE};` (also to `postgres`), with
> `APP_ROLE` parsed out of the DSN at line 51 — so **every table ends up owned by the application
> role as well**. Its step 4 tries `/usr/local/bin/hbd-migrate`, then falls back to:
>
> ```bash
> ( cd /opt/hbd && HBD_ENV_FILE="$BOT_ENV" \
>     /opt/hbd/venv/bin/python -m alembic -c /opt/hbd/migrations/alembic.ini upgrade head )
> ```
>
> `grep -c 'HBD_ADMIN_AUDIT_DSN\|HBD_DB_APP_ROLE\|HBD_DB_MIGRATION_URL'` on that script returns
> **0**. So 0007 took its **first** skip branch (`_skip("…AUDIT_DSN is not set…")`, 0007:336-337)
> on a schema built from scratch that morning: no REVOKE, no `hbd_purge_audit_log`, no
> `hbd_purge_audit_reasons`. **The fix belongs in that script**, beside the dump it already takes
> — not in an operator's memory, because case (b) above has to be redone by hand after every
> wipe. `[UNPROVEN]` `/usr/local/bin/hbd-migrate` is root-only (820 bytes) and unreadable with
> the available access, so whether *it* exports the two variables is unknown; the script's own
> comment records that it failed on 2026-09-10 by passing `"upgrade head"` as one argument, so
> the alembic fallback is what actually ran.
>
> **And before you run any of this on `abdu-test`: alembic cannot currently run there at all.**
> See §11's host box — `/opt/hbd/migrations/env.py` imports `bayram` and the venv holds only
> `hbd`.

> **Two roles are a manual step nobody in this repo performs.**
> `docker/initdb/10-two-roles.sql:25-33` says outright that its password is a local development
> password and that staging and production roles must be created by hand. It runs only on an empty
> Docker volume. Whether `hbd` and `hbd_app` exist on a given database, and whether
> `ALTER DEFAULT PRIVILEGES FOR ROLE hbd … GRANT … TO hbd_app` (that file, :46-49) was applied, is
> host state — and without that clause every table a future migration creates is invisible to the
> application role.

---

## 4. `ok: true` but `isComplete: false` on `/audit/verify`

**SYMPTOM.** A green verification on a mature deployment.

**LIKELY CAUSE.** The walk is bounded: `VERIFY_BATCH_SIZE = 500` and `MAX_VERIFY_ROWS = 50_000`
(audit.py:129-132). Past the ceiling the tail check is suppressed and `is_complete` goes false
(audit.py:646-656), with the field comment stating the reason: "so a clean result is not mistaken
for a clean *whole* chain" (audit.py:240-243).

**HOW TO CONFIRM.** Read both fields, never `ok` alone. `checkedRows` at exactly 50 000 is the
ceiling.

**FIX.** None available in the product — this is a reading instruction, not a defect. `ok: true`
with `isComplete: false` means "the oldest 50 000 rows verify", not "the log verifies".

---

## 5. Sign-in returns 403 `ORIGIN_REJECTED`

**SYMPTOM.** The login page loads. Submitting credentials returns 403 with code
`ORIGIN_REJECTED`; the admin log carries `admin.login.origin_refused`. After a successful sign-in
elsewhere, the same code appears on **every** state-changing request with
`admin.csrf.refused` instead.

**LIKELY CAUSE.** The `Origin` header does not exactly equal `BAYRAM_ADMIN_PUBLIC_ORIGIN`.
`verify_origin` is an exact set-membership test with no prefix, suffix or subdomain matching
(csrf.py:76-88), and outside `dev` the accepted set holds exactly one element
(settings.py:620-632). Three shapes produce it:

- **A second hostname.** A panel reachable at both `https://panel.example` and a bare IP, or a
  `www.` variant, 403s on whichever one is not configured.
- **A wrong scheme or port.** `http://` where the configured value is `https://`, or `:8080`
  appended by a proxy that does not rewrite it.
- **A proxy that strips `Origin`.** An absent header is `ORIGIN_MISSING`, mapped to the same
  `ORIGIN_REJECTED` code (deps.py:209-210).

The boot guard cannot catch a *wrong* value, only an *unset* one — it tests
`"admin_public_origin" not in self.model_fields_set` (settings.py:578-581). And a dotenv-supplied
value counts toward `model_fields_set`, so a host that copied `.env.admin.example:73`
(`BAYRAM_ADMIN_PUBLIC_ORIGIN=http://127.0.0.1:8080`) verbatim **disarms the guard** and produces
exactly the incident the guard's own message predicts: "boot, pass /healthz, serve a login page and
then reject every mutation with ORIGIN_REJECTED" (settings.py:582-588).

In development the same 403 has a different cause and is not a bug: the Vite dev proxy sets
`changeOrigin: false` deliberately (`admin-ui/vite.config.ts:132-135`), so the browser's real
`Origin` reaches the API and the check is live locally too. The prerequisite is
`BAYRAM_ADMIN_PUBLIC_ORIGIN=http://localhost:5173` in `.env.admin` (Makefile:86-89). Flipping
`changeOrigin` to `true` "fixes" the 403 by disabling the panel's only cross-site control
everywhere but production.

**HOW TO CONFIRM.** The configured value is on the boot line and on the config screen:

```bash
... | grep admin.boot.ok      # context.public_origin — the value the process enforces
```

Then compare it, character for character, against what the browser sends:

```bash
curl -si https://<panel host>/api/auth/login -X POST \
  -H 'Origin: https://<panel host>' -H 'Content-Type: application/json' \
  -d '{"username":"origin-probe","password":"origin-probe"}'
# 403 ORIGIN_REJECTED   the header and the setting disagree
# 401 / 429             the origin check passed; the request reached the credential path
```

**The body must be well formed, and `-d '{}'` will lie to you.** `login` declares
`body: LoginRequest` as a parameter (auth.py:440-448), so pydantic validates it during dependency
solving and returns 422 before the handler body ever runs; `_enforce_origin(request, settings)` is
the *first statement inside* the handler (auth.py:450), and there is no origin or CSRF middleware in
the stack to catch it earlier (app.py:387-390). `username` and `password` are both required with
`min_length=1` (schemas/auth.py:47-50), so an empty object 422s on every deployment, correctly
configured or not — a 4xx that reads as "the origin check passed" when it never ran.

Two costs of the corrected probe, both small and both worth knowing: it charges one attempt against
the strict `(username, client_ip)` login counter (10 per 900 s, ratelimit.py:116-117), so use a
username no operator signs in as; and a failed check writes one `LOGIN_FAILURE` audit row
(auth.py:487-496).

> **THE CONTROL IS CONFIRMED WORKING ON `abdu-test`, IN BOTH DIRECTIONS — AND THE PANEL IS ON
> THE PUBLIC INTERNET, WHICH CHANGES WHAT THIS SECTION IS ABOUT.** `[HOST 2026-09-10]` The
> configured origin is real and is what a browser reaches: `admin.boot.ok` carries
> `"public_origin": "https://admin.bayrambot.uz"`, and `https://admin.bayrambot.uz/` answers
> HTTP/2 200 from the open internet (`server: cloudflare`, `via: 1.1 Caddy`). `admin.login.ok`
> has been logged, so somebody has signed in.
>
> The negative direction was tested too, once: a `POST /api/auth/login` from loopback carrying
> `Origin: http://evil.example` returned **403** and logged
> `{"event": "admin.login.origin_refused", "reason": "origin_mismatch"}` — the exact reason
> string this section predicts. `admin.csrf.refused` has **never** appeared, which is correct:
> it only fires on the authenticated path, so its absence is not evidence about the origin check.
>
> Two honest footnotes. That probe used the throwaway username `origin-probe-surveyor` and
> charged one attempt against the strict counter, exactly as warned above — if you are reading
> the journal, `[HOST 2026-09-10]` the single `admin.login.origin_refused` at 14:32:19 +05 on
> 2026-09-10 is **ours**, not an attack. And `abdu-test` has no second hostname to 403 on: Caddy
> answers `404` for anything outside the two configured host blocks.

**FIX.** Set `BAYRAM_ADMIN_PUBLIC_ORIGIN` to the exact origin a browser types — scheme, host and, if
non-default, port — and restart the admin process. If the panel is reachable by more than one name,
give it one and redirect the others at the proxy; the setting holds exactly one origin outside dev
and that is not a limitation to work around.

> **The panel must live at the root of its own origin.** The bundle references `/assets/…`
> absolutely, the immutable-cache carve-out is the literal prefix `"/assets/"`
> (security_headers.py:82), the API prefix is `/api` (deps.py:108), and both cookies are
> `__Host-` prefixed — a prefix *defined* to require `Path=/` and no `Domain` (csrf.py:45-49).
> Mounted under a subpath, the bundle 404s, the cache split lands on the wrong paths, and the
> cookies scope to everything else on that origin.

---

## 6. Nobody can sign in, or one operator is permanently locked out

**SYMPTOM (a).** Every sign-in returns 429, or 429s appear for one username in a pattern nobody can
explain — and **the log says nothing**.

That silence is the diagnostic, so do not go looking for a line. Two counters can produce this 429
and only one of them is logged. `admin.ratelimit.username_tripped` belongs to the **loose**
username-only ceiling — 100 per 900 s, the one whose docstring calls it "the counter an attacker
spread across many source addresses trips" (ratelimit.py:358-376). The **strict**
`(username, client_ip)` counter described below fires at 10 and emits nothing: `_LOGGER` appears
three times in that whole module — `store_unavailable` at :338, `username_tripped` at :367, a refund
failure at :557 — and none of them covers a strict-counter trip. The evidence it does leave is in
the database, not the log: one `LOGIN_RATE_LIMITED` audit row per limiter window, carrying the
attempted username and no actor (auth.py:468-481). The 429 itself also names which counter answered:
`_refuse_if_limited` passes the scope through `problem(...)`, whose keyword arguments become
`error.details` (auth.py:215-223, errors.py:175-185), so the response body carries
`details.scope: "user_ip"` for the strict counter and `"username"` for the loose one
(ratelimit.py:151-156). That field, not a grep, is what separates the two here.

**LIKELY CAUSE.** Every request resolves to the same client IP because the reverse proxy is not
declared. `resolve_client_ip` ignores `X-Forwarded-For` entirely unless **both** `hops > 0` **and**
the transport peer is inside a configured CIDR (clientip.py:110-149). The shipped defaults are
`admin_trusted_proxy_hops = 0` and empty CIDRs (settings.py:216-217), and
`.env.admin.example:113-114` ships them that way. Behind a proxy, `request.client.host` is the
proxy (deps.py:195-201), so the strict login counter — keyed `(username, client_ip)` at 10 attempts
per 900 s (ratelimit.py:116-117, :309-314) — collapses into one global bucket per username. That is
the shape ratelimit.py:9-13 was written to avoid: it "hands anyone who knows an operator's username
a permanent 429 against that account, at exactly the moment during an incident when the operator
needs to log in."

The same collapse writes the proxy's address into every `admin_audit_log.ip` and into
`admin_sessions.last_ip` (deps.py:329-347), so the audit log's only network evidence becomes a
constant.

Nothing validates hops against reality, and the boot line does **not** print them — `admin.boot.ok`
carries `environment`, `env_file`, `is_cookie_secure` and `public_origin` and nothing about proxies
(app.py:322-333).

**HOW TO CONFIRM.** `GET /api/config` publishes both values (config_view.py:96-129). Compare
`adminTrustedProxyHops` against the number of proxies the deployment actually controls, and check
that the audit log's `ip` column is not a single repeated address.

> **ON `abdu-test` THE TOPOLOGY IS KNOWN, THE CORRECT VALUES ARE DERIVABLE, AND WHETHER THE FILE
> HOLDS THEM IS `[UNPROVEN]`. This is the control `07-security.md` §5 names as having no signal at
> any level, and the host bears that out exactly.**
>
> `[HOST 2026-09-11]` The panel is **two proxies deep** — Cloudflare edge → Caddy → uvicorn —
> proven by one response carrying both `server: cloudflare` and `via: 1.1 Caddy`. So the correct
> values are `hops=2` and `cidrs=127.0.0.1/32`; `/etc/caddy/Caddyfile:69-70` states exactly that
> in a comment, adds that "The CIDR is the PEER — always loopback", and warns that switching the
> DNS record to grey cloud makes the count **1** with nothing anywhere reporting the mismatch.
> (Note the comment names the file as `/etc/hbd/admin.env` while the unit actually loads
> `/etc/hbd/hbd-admin.env` — a stale path in a comment, not a second file.)
>
> `[UNPROVEN]` Whether the live configuration holds those values cannot be established:
> `/etc/hbd/hbd-admin.env` is unreadable to `developer`, `GET /api/config` answers **401
> `UNAUTHENTICATED`** without a session cookie, `admin.boot.ok` carries no proxy settings by
> design (app.py:322-333), and no log line in the tree reports them.
>
> There is one piece of corroborating *shape*, and it is the right kind of worry: the gateway
> beside the panel journals `"peer_ip": "127.0.0.1"` on **62 of 62** RPCs, including one request
> made from the public internet. The application is demonstrably seeing the proxy rather than the
> caller. If the panel's `hops` is still the shipped `0`, then `admin_audit_log.ip` on this host
> is a constant and the strict login counter is one global bucket per username — the exact shape
> `ratelimit.py:9-13` was written to prevent. **Somebody with a session should read
> `adminTrustedProxyHops` and write the answer into `00-host-inventory.md` row 23.**

**FIX.** Set `BAYRAM_ADMIN_TRUSTED_PROXY_HOPS` to the exact count of proxies you control and
`BAYRAM_ADMIN_TRUSTED_PROXY_CIDRS` to the addresses those proxies connect from — and configure the
proxy to **append** to `X-Forwarded-For`, not replace it. Too high believes an attacker-written
entry; too low believes an inner proxy. A CIDR typo fails the boot with the variable named
(settings.py:486-499), which is the one part of this the code can check for you.

**SYMPTOM (b).** Sign-in fails with a rate-limit refusal that no amount of waiting clears, and the
Redis-backed screens are unhappy.

**LIKELY CAUSE.** Redis is unreachable and the admin limiter **fails closed** by design: "When
Redis is unreachable the answer is 'denied', not 'allowed'" (ratelimit.py:21-26), with
`BACKEND_UNAVAILABLE` kept distinct from `TRIPPED` so an outage does not read as an attack
(ratelimit.py:159-170). The log event is `admin.ratelimit.store_unavailable` (ratelimit.py:340).
Note the deliberate asymmetry: the bot's inbound gate **fails open** — "A meter that cannot be read
is not a reason to stop selling songs" (`src/bayram/bot/gate.py:44-47`). So a Redis incident locks
operators out of the panel while the bot keeps serving customers. Those are one event, not two.

**HOW TO CONFIRM.** `/readyz` with the probe token (see §9) reports `redis: false`.

**FIX.** Restore Redis. There is no bypass, and adding one would remove the control.

---

## 7. The admin API refuses to start

Three refusals run inside the lifespan, **in this order** (app.py:315-316), and the first one wins.

**SYMPTOM.** The process exits at start with:

```
The admin panel is disabled. Set BAYRAM_ADMIN_ENABLED=true in .env.admin to run it.
```

**CAUSE AND FIX.** `admin_enabled` defaults to `false` (settings.py:180) and the lifespan refuses
without it (app.py:206-208). Setting it is a required, non-default deployment step — a fresh admin
service refuses to start until somebody does.

**SYMPTOM.** The process exits at start naming one or more of
`BAYRAM_TELEGRAM_BOT_TOKEN`, `BAYRAM_ELEVENLABS_API_KEY`, `BAYRAM_LLM_API_KEY`,
`BAYRAM_LLM_FALLBACK_API_KEY`, `BAYRAM_OPENROUTER_MANAGEMENT_KEY`:

```
The admin process must not hold a vendor credential or a bot token, and these are within
reach of it — in its environment or in <the admin env file>: …
```

**CAUSE.** `_refuse_vendor_credentials` (app.py:186-199) scans `os.environ` **and** the variable
names in the admin dotenv file (app.py:175-183), and the list is derived from
`bayram.config.VENDOR_SECRET_FIELDS` rather than restated (app.py:116-118, config.py:111-117), so a
sixth credential added there is covered here without anyone remembering — as the fifth,
`BAYRAM_OPENROUTER_MANAGEMENT_KEY`, already was (D13: the tuple grew, this refusal followed, no
edit here). `AdminSettings` has no
field that could hold any of them.

**FIX.** Remove them from the admin host. The panel needs none of them: it opens exactly two
connections, Postgres and Redis (container.py:1, :121-128).

> **In `staging` this is a WARNING, not a refusal.** The refusal is gated on
> `environment == "prod"` exactly (app.py:192, settings.py:598-599). A staging admin host holding a
> real ElevenLabs key boots with `admin.boot.vendor_env_present` in a log nobody is watching. And
> because the disabled-panel refusal runs *first*, a prod host with both problems is told the panel
> is disabled and never learns about the credential.

**SYMPTOM.** A validation error listing many variables at once, including several the example file
told you to leave blank.

**CAUSE.** `.env.admin.example` cannot be copied and booted as-is. python-dotenv strips an inline
`#` comment only when the value before it is non-empty, so seven variables parse as their own
trailing comment, and `BAYRAM_ADMIN_COOKIE_SECURE=` (genuinely blank, with the file instructing "Leave
empty" at :91-92) is a `bool | None` pydantic cannot read from an empty string. Reproduced against
this working tree:

```bash
cd /tmp && BAYRAM_ADMIN_ENV_FILE=<checkout>/.env.admin.example \
  <checkout>/.venv/bin/python -c "
from bayram.admin.settings import build_admin_settings
from bayram.errors import ConfigError
try: build_admin_settings()
except ConfigError as e: print(e.operator_message)"
```

```
The admin panel's configuration is invalid or incomplete. Fix these environment variables (see .env.admin.example):
  BAYRAM_ADMIN_COOKIE_SECURE: Input should be a valid boolean, unable to interpret input
  BAYRAM_ADMIN_TRUSTED_PROXY_CIDRS: Value error, BAYRAM_ADMIN_TRUSTED_PROXY_CIDRS contains an unparsable entry: '# comma-separated'
  BAYRAM_ADMIN_AUDIT_HMAC_KEY: Value should have at least 32 items after validation, not 0
  BAYRAM_ADMIN_NAME_MATCH_MIN_SIMILARITY: Input should be a valid number, unable to parse string as a number
  BAYRAM_ADMIN_SETTLEMENT_GRACE_S: Input should be a valid integer, unable to parse string as an integer
  BAYRAM_ADMIN_UZS_PER_USD: Input should be a valid number, unable to parse string as a number
  BAYRAM_ADMIN_UZS_PER_USD_AS_OF: Input should be a valid date or datetime, invalid character in year
  BAYRAM_ADMIN_SINGLE_SONG_PRICE_MINOR: Input should be a valid integer, unable to parse string as an integer
  BAYRAM_ADMIN_KIT_CURRENCY: String should have at most 3 characters
```

**FIX.** In the deployed copy, delete the value from each of those lines and move the explanatory
comment onto its own line above the variable. Then set `BAYRAM_ADMIN_AUDIT_HMAC_KEY` to at least 32
characters, and delete the `BAYRAM_ADMIN_COOKIE_SECURE=` line entirely — the field is a refusal, not a
switch (settings.py:570-577, :602-618), and its only legal states are absent or `true`.

The irony is worth knowing: `_blank_mirror_means_unpublished` (settings.py:433-465) exists solely to
make the untouched example file work and says so at :449 — "The example file ships the variables
blank, so this is the path an untouched deployment actually takes." It is not that path, because
the values are never blank as parsed, so the validator never fires.

---

## 8. `ConfigError` at startup naming variables you thought were set

**SYMPTOM.** The bot exits 2 with a single line and no traceback:

```
bayram: Configuration is invalid or incomplete. Fix these environment variables (see .env.example):
  BAYRAM_TELEGRAM_BOT_TOKEN: Field required
  BAYRAM_DATABASE_URL: Field required
  BAYRAM_ELEVENLABS_API_KEY: Field required
  BAYRAM_LLM_API_KEY: Field required
```

**LIKELY CAUSE.** `BAYRAM_ENV_FILE` names a file that does not exist. A missing dotenv path reads no
file and raises no error, and **the message cannot tell you that**: the preamble hardcodes the
*example* filename (config.py:702-704; the admin twin at settings.py:640-643), and the resolved path
is only logged later, by `verify_host` and by `admin.boot.ok` — both of which run after settings
build successfully. So the one failure mode the `BAYRAM_ENV_FILE` feature introduces is the one its
error message cannot describe.

Those four variables are the complete required set for the bot and the worker, in every environment
(config.py:187 for the DSN; the three vendor secrets are re-required by `_VendorBoundSettings` at
config.py:689-699, and `load_settings` always passes `require_vendor_secrets=True`,
config.py:758-760). The admin's set is two: `BAYRAM_DATABASE_URL` and a ≥32-character
`BAYRAM_ADMIN_AUDIT_HMAC_KEY` (settings.py:174, :229).

**HOW TO CONFIRM.** Ask the process which file it would read, without booting it:

```bash
BAYRAM_ENV_FILE=<the path the service sets> <venv>/bin/python -c \
  "from bayram.config import env_file; import pathlib
p = env_file(); print(p, pathlib.Path(p).is_file())"
```

**FIX.** Correct the path. Note the precedence, which bites in the other direction too: process
environment beats the dotenv file for every variable on both settings classes, so any `BAYRAM_*` left
exported in a deploy shell silently overrides the file the service points at.

> **ON A HOST THAT USES systemd `EnvironmentFile=`, `env_file` ON THE BOOT LINE ANSWERS A
> DIFFERENT QUESTION THAN YOU THINK, AND THE Quick reference TABLE AT THE BOTTOM OF THIS PAGE
> WILL MISDIAGNOSE A HEALTHY HOST.** That row says the healthy value is "the intended path, not a
> checkout `.env`". `[HOST 2026-09-11]` On `abdu-test`, `systemctl show <unit> -p Environment` is
> **empty** for `hbd-bot`, `hbd-worker` and `hbd-admin` — none of them sets `HBD_ENV_FILE` or
> `HBD_ADMIN_ENV_FILE` — so `resolve_env_file` falls back to the *relative* defaults and the boot
> lines print exactly that: `"env_file": ".env"` on bot and worker, `".env.admin"` on the panel.
> All three are perfectly healthy. Real configuration arrives through
> `EnvironmentFile=/etc/hbd/*.env` straight into `os.environ`, which no boot line reports. Only
> the gateway names its file — `Environment=HBD_PAYME_ENV_FILE=/etc/hbd/payme.env` — and its boot
> line prints the absolute path.
>
> **The row that IS broken by this is the silent one, and it is a security control.** With the
> dotenv path unset, the *file* half of the admin's vendor-credential scan reads a path that does
> not exist, `dotenv_values` returns `{}` without raising, and it reports nothing
> (`07-security.md` §1). What keeps the control effective on this host is that
> `EnvironmentFile=` puts everything into `os.environ`, which the *environment* half does cover —
> an accident of the unit file rather than a designed property. Diagnose "which file did this
> process really read" from `systemctl cat <unit>`, never from `env_file`.

**RELATED SYMPTOM.** The worker exits with a **traceback** rather than a clean line, once per
supervisor restart. That is not a different bug: `WorkerSettings` is built at import time so the ARQ
CLI can find it, and `_SETTINGS = _settings()` sits at module scope (worker.py:40, docstring at
worker.py:3-6) with no `try/except`. The bot wraps the same call and prints one line (main.py:213-218).
Same misconfiguration, two different presentations.

**WORSE SYMPTOM: no error at all.** If the four required variables happen to be exported, a mistyped
`BAYRAM_ENV_FILE` boots the bot on **100 % defaults** — including `BAYRAM_ENVIRONMENT=dev`, which disarms
the only two production refusals the bot has (fake providers, providers.py:104-108; the in-process
submitter, submitter.py:100-105). `Settings.environment` is an unvalidated free-form `str`
(config.py:170), unlike `AdminSettings.environment`, which is a closed `Literal` precisely because
"a typo like `production` would silently downgrade the strongest boot control in the package"
(settings.py:15-18). `BAYRAM_ENVIRONMENT=production` or `=PROD` on the bot is that typo, with no error
anywhere. Confirm from the boot line: `host verified` carries `environment` and `env_file`
(runtime/startup.py:33-41).

> **`BAYRAM_REDIS_URL` defaults to `redis://localhost:6379/0`** (config.py:188). A worker with a
> mistyped Redis URL does not fail — it connects to a local Redis and finds an empty queue. The
> queue looks idle rather than broken.

---

## 9. Monitoring reports the panel healthy while it serves nothing

**SYMPTOM.** `/readyz` returns `200 {"status":"ok"}` with the database down, Redis down, or both.
Nothing is ever removed from a load balancer.

**LIKELY CAUSE.** The unauthenticated `/readyz` body is a **constant** and pings nothing
(health.py:53-56, :126-131) — even the word "degraded" is treated as fleet telemetry
(health.py:9-19). Detail requires either `X-Probe-Token` matching `BAYRAM_ADMIN_PROBE_TOKEN` under
`secrets.compare_digest`, or a live operator session (health.py:93-114). The token defaults to empty,
and an empty setting authorises nobody (settings.py:426-428) — so there is no default token to
forget to change, and also no monitoring path at all until one is set.

`/healthz` is worse for this purpose by design: a bare 200 with an empty body that touches nothing
(health.py:121-124). It also takes no container, so it answers 200 even in the one state where every
API route 500s — a process whose ASGI lifespan never ran, where `get_container` raises
`RuntimeError("admin container is not on app.state; the lifespan did not run")` (deps.py:126-133).

**HOW TO CONFIRM.**

```bash
curl -s http://127.0.0.1:8080/readyz                                  # always {"status":"ok"}
curl -s -H 'X-Probe-Token: <token>' http://127.0.0.1:8080/readyz      # the real answer
# {"status":"ok|degraded","database":true,"redis":true,"configVersion":null}
```

**FIX.** Set `BAYRAM_ADMIN_PROBE_TOKEN` to a long random value and give it to the monitor. The settings
model imposes no minimum length on it — unlike the HMAC key's `min_length=32` — so length is
operator discipline here.

**Do not chase `configVersion: null`.** Nothing in this tree writes `bayram:settings:version`; the key
is read at health.py:74 and written nowhere, awaiting the Phase 7 config editor (health.py:50-51).
`null` means "nobody has published one", never "Redis is broken".

Neither the bot nor the worker exposes any HTTP probe at all. Supervision of those two is
process-level; there is nothing to curl.

> **`[UNPROVEN]` ON `abdu-test` NOBODY KNOWS WHETHER THE PROBE TOKEN IS SET, AND NOTHING IS
> POLLING EITHER WAY.** The unauthenticated `/readyz` body is a constant whether or not a token
> is configured, `GET /api/config` — which publishes `isProbeTokenConfigured` — needs a session,
> and `/etc/hbd/hbd-admin.env` is unreadable to the deploy account. So the setting itself is
> unproven. What *is* observable is circumstantial and points one way: `[HOST 2026-09-11]` the
> whole admin journal contains only a handful of `/readyz`-or-`/healthz` requests all day, several
> of them made by people checking by hand, so **nothing is polling on a schedule.** A further
> confirmation from the same census: zero `admin.health.redis_unreachable` and zero
> `admin.health.version_unreadable` have ever been logged — which on a box whose Redis has been
> up throughout is consistent with either answer, and is the kind of silence that proves nothing.
>
> Both endpoints do answer on loopback: `[HOST 2026-09-11]` `http://127.0.0.1:8080/healthz` → 200,
> `/readyz` → `{"status":"ok"}` (the constant), and the Payme gateway answers the same pair on
> `:8091`. **Reading either as "healthy" is the mistake this whole section exists to prevent.**
>
> For scale when you read that census: `admin.request` 1 828, `admin.container.built` 12,
> `admin.boot.ok` 12, `admin.login.ok` 6, `admin.password.refused` 5,
> `admin.audit.revoke_missing` 2, `admin.stepup.refused` 1, `admin.stepup.granted` 1,
> `admin.password.changed` 1, `admin.login.origin_refused` 1 — and **zero**
> `admin.ratelimit.*`, **zero** `admin.session.mirror_*`, **zero** `admin.rbac.*`, **zero**
> `admin.audit.write_failed`, **zero** `admin.spa.nonce_placeholder_missing`.

---

## 10. The bot or worker will not start: ffmpeg

**SYMPTOM.** One of:

```
'ffmpeg' was not found on PATH. Install ffmpeg, or point BAYRAM_FFMPEG_BINARY at the binary.
Audio post-processing cannot run without it and every order would fail.
```
```
'ffmpeg' was built without libopus. Telegram's sendVoice only renders a voice note for
OGG/Opus; without this encoder every greeting would arrive as a file attachment. Install an
ffmpeg build that includes it.
```
```
'/usr/bin/ffmpeg' did not answer -encoders within 15.0s; the binary looks broken.
```
```
'/usr/bin/ffmpeg' exited 1 listing its encoders; the binary looks broken.
```
```
'ffmpeg' is on PATH but could not be executed: <the OSError>
```

Note which name each message carries, because it is not consistent and it tells you where in the
check you are. The PATH and `libopus` messages name the **configured** binary — the bare `ffmpeg`
or whatever `BAYRAM_FFMPEG_BINARY` holds (audio/startup.py:35, :99). The three `-encoders` messages
name the **resolved** path, because `_encoder_table` is called with `shutil.which`'s answer
(audio/startup.py:96, messages at :62, :68, :75). **None of them can ever name `ffprobe`**:
`_encoder_table` is called exactly once, with `ffmpeg_path`; ffprobe is only checked for presence on
PATH (audio/startup.py:93-94) and is never asked for an encoder table at all.

**LIKELY CAUSE.** `verify_host` refuses on more than the encoder set, and the boot log's "host
verified" line is emitted only after all of it passes (runtime/startup.py:21-42). In order:

1. `ffmpeg` resolvable on PATH (audio/startup.py:31-40).
2. `ffprobe` resolvable on PATH — same function, same message shape, and that is the *only* thing
   asked of ffprobe (audio/startup.py:94).
3. ffmpeg actually executable: an `OSError` from the spawn is a `ConfigError` (audio/startup.py:60-65).
4. ffmpeg answering `-encoders` inside the 15 s ceiling (audio/startup.py:66-71;
   `STARTUP_PROBE_TIMEOUT_S = 15.0`, constants.py:66).
5. a zero exit from that call (audio/startup.py:73-78).
6. the table containing `libopus` — `REQUIRED_ENCODERS = (VOICE_NOTE_CODEC,)` = `("libopus",)`,
   constants.py:113-121; raised at audio/startup.py:97-103.
7. **the i18n catalogues loading.** `verify_host` calls `get_translator()` after the ffmpeg check
   and says why: "Loading the catalogues here turns a malformed locale file into one startup failure
   rather than a broken message in front of a customer" (runtime/startup.py:26-28, and
   `bayram/i18n/__init__.py:8-10`). A `locales/*.json` that breaks the orthography or plural rules is a
   `ConfigError` at that moment — a boot refusal with nothing to do with ffmpeg, which is worth
   knowing because every message above points at a binary.

`verify_host` is called by the bot (main.py:100) and the worker (worker.py:45) and **not** by the
admin API — an admin-only host needs no ffmpeg at all.

> **Two files are called `startup.py` and they are different files.** The ffmpeg checks are
> `src/bayram/audio/startup.py` (108 lines). `verify_host` and the `host verified` log line are
> `src/bayram/runtime/startup.py` (42 lines), which is what §8 and §18 mean by the bare name. Any
> citation past line 42 belongs to the audio one.

**HOW TO CONFIRM.**

```bash
ffmpeg -hide_banner -encoders | grep -E 'libopus|libmp3lame'
which ffmpeg ffprobe
```

> **`[HOST 2026-09-11]` On `abdu-test` this check has been run and it passes, including the half
> nothing else checks.** `ffmpeg` is `/usr/bin/ffmpeg` and the encoder table carries **both**:
>
> ```
>  A....D libmp3lame  libmp3lame MP3 (MPEG audio layer 3) (codec mp3)
>  A....D libopus     libopus Opus (codec opus)
> ```
>
> So the warning two paragraphs below — "check `libmp3lame` by hand; nothing else will" — is
> satisfied on this host rather than merely flagged. It is still the right warning everywhere
> else, because boot would have passed without it.

**FIX.** Install an ffmpeg build with libopus, or point `BAYRAM_FFMPEG_BINARY` / `BAYRAM_FFPROBE_BINARY`
at one — the binaries are operator-configurable (config.py:414-418) and the error message names the
variable, so a host with ffmpeg somewhere unusual needs a config line rather than a PATH change.

> **Two asymmetries here will mislead you.** The probe demands `libopus`, which the default product
> configuration never exercises — `greetings_per_kit` defaults to 0, which "sells a song-only kit
> and buys no speech at all" (config.py:406-411). Meanwhile the **mp3** encoder the song master
> actually needs is never probed, and its absence is not fatal: `_normalized` in
> `pipeline/assets.py:129-132` is documented "Loudness-normalise, or fall back to the source file.
> Never fatal." An ffmpeg without an mp3 encoder passes boot and ships an unmastered song to every
> paying customer with no error anywhere. Check `libmp3lame` by hand; nothing else will.

A post-boot ffmpeg failure never crashes the process. Every spawn goes through one function that
returns an `Err(AudioProcessingError)` carrying a stderr tail (`audio/runner.py:1-8`, :41-44), so
diagnosing one means reading job-level error context, not a traceback.

---

## 11. Migrations fail asking for API keys

**SYMPTOM.** `alembic upgrade head` on a database-only or CI host exits complaining about
`BAYRAM_TELEGRAM_BOT_TOKEN`, `BAYRAM_ELEVENLABS_API_KEY` and `BAYRAM_LLM_API_KEY` — none of which a
migration needs.

**LIKELY CAUSE.** When `BAYRAM_DB_MIGRATION_URL` is unset, `migrations/env.py` falls back to
`load_settings().database_url` (env.py:117-129), and `load_settings` always requires the vendor
secrets (config.py:758-760).

**FIX.** Set `BAYRAM_DB_MIGRATION_URL` — which you want set anyway, see §3 — and the vendor-key path is
never taken. `_owner_url` reads it from the environment first and from the dotenv file second
(env.py:96-114).

> **BEFORE ANY OF THAT ON `abdu-test`: ALEMBIC CANNOT RUN THERE AT ALL TODAY, AND THE ERROR
> POINTS AT THE WRONG THING.** `[HOST 2026-09-11]` `/opt/hbd/migrations/env.py` was copied from
> the **post-rename** repository on 2026-09-10 at 14:06, and its line 57 reads
> `from bayram.config import env_file, load_settings`. The venv holds only the **pre-rename**
> package:
>
> ```console
> $ /opt/hbd/venv/bin/python -c 'import bayram'
> ModuleNotFoundError: No module named 'bayram'
> $ /opt/hbd/venv/bin/python -c 'import hbd; print(hbd.__file__)'
> /opt/hbd/venv/lib/python3.12/site-packages/hbd/__init__.py
> ```
>
> `alembic.ini:15` also sets `prepend_sys_path = %(here)s/../src`, and `/opt/hbd/src` does not
> exist. The 25 migration files themselves are present and fine.
>
> **Four recovery procedures across these two documents end in an alembic invocation** — §3 case
> (a), §11 here, §12 below, and `05-operations.md` *After a restore* step 1 — and on this host all
> four die with that `ModuleNotFoundError`. An operator hitting it mid-incident reads "broken
> virtualenv" and starts reinstalling things. **It is a half-finished rename**, and the traceback
> gives no hint which. Check first:
>
> ```bash
> ssh aizu '/opt/hbd/venv/bin/python -c "import bayram" || echo "CUTOVER NOT RUN: the package is hbd"'
> ```
>
> The staged wheel (`/opt/hbd/release/bayram_bot-0.1.0-py3-none-any.whl`) and
> `/opt/hbd/cutover-to-bayram.sh` that fix it properly are both dated 2026-09-10 and **neither has
> run** — the installed distribution is still `hbd_bot-0.1.0`. The sequence is `08-payme.md` §11.6
> and `09-payme-go-live.md` §2. Until then, use the `HBD_` prefix and an `env.py` that imports
> `hbd`.

---

## 12. Migrations ran, but as the wrong role

**SYMPTOM.** In alembic's output, one line:

```
BAYRAM_DB_MIGRATION_URL is not set, so migrations are running as the application role. That
role owns every table it creates, and an owner can GRANT back anything revoked from it — so
the audit log's REVOKE is not a control on this deployment.
```

**LIKELY CAUSE.** Exactly what it says (env.py:89-93, :117-129). Falling back rather than refusing
is deliberate — every one-role dev setup would otherwise stop migrating — but the deployment now has
no privilege-based audit protection, only the HMAC.

**HOW TO CONFIRM.** The downstream evidence is `/audit/verify` reporting `hmac-only` (§3) and, in
Postgres, the audit table's owner:

```sql
SELECT tableowner FROM pg_tables WHERE tablename = 'admin_audit_log';
```

> **`[UNPROVEN]` on `abdu-test` — and the host ships the script that would answer it.** That
> query needs the database password, which the deploy account does not have (§3's host box).
> `/opt/hbd/diagnose.sh` asks exactly this, plus the distinct `tableowner` set for the whole
> `public` schema, in four `sudo -u postgres psql` queries; it needs one sudo password.
> `[HOST 2026-09-11]` What *is* established is the shape that makes the wrong answer likely:
> `/opt/hbd/release/wipe-and-rebuild.sh:114` runs `GRANT ALL ON SCHEMA public TO ${APP_ROLE}`
> before migrating, and the migration fell back to the application-role alembic invocation (§3).
> So expect the app role to own the tables here, and expect the `ALTER TABLE … OWNER TO` below to
> be necessary — but **observe it, do not infer it**, because the whole point of §3's probe is
> that the badge is derived from the database rather than from reasoning like this paragraph.

**FIX.** Create the two roles by hand on the target database (the local init script is explicitly
not for production), set `BAYRAM_DB_MIGRATION_URL` to the owner DSN and `BAYRAM_DATABASE_URL` to the
application DSN, and export the environment as in §3 so every *subsequent* migration runs as the
owner. Tables already owned by the wrong role need `ALTER TABLE … OWNER TO <the owner role>` before
the REVOKE means anything.

Re-running `alembic upgrade head` will **not** repair the migrations that already ran: alembic
applies each revision once, so 0007's REVOKE does not fire a second time on a database that already
carries `admin_audit_log`. Fixing the ownership is an `ALTER TABLE`, and re-applying the audit
controls is §3 case (b) — by hand, as the owner.

---

## 13. Retention, balances and audit anchors quietly stop

**SYMPTOM.** No error anywhere. Symptoms accumulate slowly: the Vendors screen reads "not polled",
`purge_runs` gains no rows, the activity series grows permanent gaps, and `/audit/verify` keeps
reporting `ok: true`.

**LIKELY CAUSE.** The ARQ worker is down, and **nothing else in this system runs a schedule.**
`[HOST 2026-09-11]` On `abdu-test` there is no systemd timer and no crontab for anything in this
stack — `systemctl list-timers --all` returns 18 timers and not one activates an `hbd-*` unit,
`crontab -l` says "no crontab for developer", `/etc/cron.d/` holds only `.placeholder`,
`e2scrub_all` and `sysstat`. **`aizu-backup.timer` is a decoy**: nightly 03:30, `User=aizu`,
backing up `/var/lib/aizu/aizu.db` for an unrelated tenant. There is no belt to the worker's
braces.

**FIVE** cron jobs live there, not three (jobs.py:820-963; the `cron(` calls at :821, :854, :875,
:909, :951) — retention hourly at `:17` (retention_job.py:73), the vendor-balance poll hourly at
`:43` (vendor_balance_job.py:118), the activity snapshot daily at `00:07` **host-local**
(activity_job.py:74-75), `run_payme_sweep` every `BAYRAM_PAYME_SWEEP_MINUTES` — default 5, so
`:00, :05, …` (payme_jobs.py:196-221) — and `sweep_due_broadcasts` at `:04, :09, …`
(broadcast_job.py:152). No other actor covers any of them. **Six** consequences, none of which
raises:

1. **Retention stops**, which the repo treats as a legal obligation.
2. **Audit tail protection stops being refreshed.** HEAD and TRUNCATION anchors are written only by
   the retention sweep (`pin_audit_head`, purge.py:486); `/audit/verify` writes nothing at all
   (routers/audit.py:1-7). The undetectable tail-deletion window is normally one sweep interval —
   with the worker down it is however long the worker is down, while the badge stays green.
3. **Balance tiles read "not polled"** — indistinguishable from the two legitimate skips below.
4. **Activity snapshots gap permanently.** Nothing back-fills; the `last_seen_at` values that would
   have answered for yesterday no longer exist (activity_job.py:20-25).
5. **The Payme delivery backstop stops, and this one costs money.** `run_payme_sweep`'s
   `notifications_re_enqueued` leg is the only thing that re-sends a settled-payment announcement
   lost to a Redis restart — the gateway holds no Telegram token, so every such message is an ARQ
   job (`08-payme.md` §1.1). A customer who paid during an outage is simply never told. The same
   job is also what re-checks the settlement invariant on a schedule.
6. **No scheduled broadcast fires.** The panel deliberately enqueues nothing for a future instant
   — "a job deferred by three days inside Redis is a promise made by the least durable component
   in the system" (jobs.py:928-934) — so the sweep *is* the scheduled-send path, and it is also
   the crash recovery for a chunk job a deploy cancelled.

> **SUPERSEDED 2026-09-10: this section used to say three jobs and `00:07 UTC`.** Both were
> wrong, and the second is the one that wastes an hour at 2 a.m. **arq schedules on the system
> timezone, not UTC** — `arq/worker.py:299-300`, comment and all: `# default to system timezone`
> / `self.timezone = datetime.now().astimezone().tzinfo if timezone is None else timezone` — and
> this project's `WorkerSettings` passes none (`grep -n timezone src/bayram/worker.py
> src/bayram/runtime/jobs.py` → nothing). `[HOST 2026-09-11]` `abdu-test` is
> `Asia/Tashkent (+05)`, so its snapshot fires at 00:07 **+05 = 19:07 UTC of the previous day**,
> observed twice: `{"ts": "2026-09-11T00:07:00+0500", "snapshot_date": "2026-09-10", "taken_at":
> "2026-09-10T19:07:00.556797+00:00"}`. An operator computing "yesterday's row should exist by
> 00:07 UTC" looks **five hours early** and concludes the job never ran. The hourly jobs are
> unaffected, because a whole-hour offset preserves the minute.

All five crons are `run_at_startup=False`, so a cold-started worker runs nothing until the next
window — but the gap is now per-job, and the number that matters to a paying customer is the
smallest one:

| Job | Cold-start gap |
| --- | --- |
| `run_payme_sweep`, `sweep_due_broadcasts` | ≤ 5 minutes |
| `run_retention_sweep`, `poll_vendor_balances` | ≤ 1 hour |
| `record_activity_snapshot` | ≤ 24 hours |

(jobs.py:850-860 argues the trade explicitly — `run_at_startup=True` would fire once per replica,
and `unique` does not deduplicate an invocation that is in no cron window.)

**HOW TO CONFIRM.**

```sql
SELECT ran_at, trigger, assets_deleted, name_records_deleted, is_batch_full,
       storage_keys_returned, storage_keys_deleted, storage_delete_failures, error_code
FROM purge_runs ORDER BY ran_at DESC LIMIT 5;
```

**There is no `rows_affected` column, and asking for one fails the whole query.** Each retention
clock has its own counter column — `assets_deleted`, `brief_notes_purged`,
`attempt_transcripts_purged`, `name_records_deleted` and the rest (purge_run.py:74-98, created by
migration 0008:57-83). `total_rows_affected` is a **computed property** over those
(`purge.py:277`); it reaches the worker log as the `rows_affected` key (retention_job.py:208) and
the retention API as `totalRowsAffected` (schemas/retention.py:143, :241), and it is stored
nowhere. Sum the counter columns if you want it in SQL.

A gap in `ran_at` at hourly :17 is the worker's downtime. Also grep the worker log for
`worker dependencies built` / `worker started` and `retention sweep finished`.

`[HOST 2026-09-11]` On a host where `psql` is behind a password wall — which `abdu-test` is — the
journal is the only route, and all five jobs can be confirmed from it in one command. What a
healthy set looks like there, and note that the retention summary's failure key is **`error`**,
not the `error_code` the SQL above selects:

```console
$ ssh aizu 'journalctl -u hbd-worker --since "2026-09-11 00:00" -o cat | grep -E \
    "sweep finished|poll finished|snapshot recorded" | grep "^{"'
{"ts":"2026-09-11T10:17:00+0500","message":"retention sweep finished","context":{"trigger":"cron",
 "duration_ms":121,"rows_affected":0,"storage_keys_returned":0,"storage_keys_deleted":0,
 "storage_delete_failures":0,"is_batch_full":false,"error":null}}
{"ts":"2026-09-11T09:43:02+0500","message":"vendor balance poll finished","context":{"polled":2,
 "succeeded":2,"failed":0,"estimated":1,"duration_ms":2153}}
{"ts":"2026-09-11T00:07:00+0500","message":"activity snapshot recorded", …}
{"ts":"2026-09-11T10:35:00+0500","message":"payme sweep finished","context":{"intents_expired":0,
 "transactions_timed_out":0,"notifications_re_enqueued":0, …}}
{"ts":"2026-09-11T10:34:00+0500","message":"the broadcast sweep finished","context":{
 "campaigns_scanned":0,"expansions_enqueued":0,"sends_enqueued":0, …}}
```

The `grep "^{"` is not decoration — see the preamble: arq writes every line twice and the plain
copy is not JSON.

**FIX.** Restart the worker. Note there is **no way to trigger a sweep on demand**: `POST
/api/retention/run` is described in two docstrings but exists as no route — the only retention route
is a `GET` (routers/retention.py:59) — and nothing outside the cron enqueues `run_retention_sweep`.
Recovery is "restart the worker and wait for :17", and an erasure request's purge cannot be
expedited.

**Two look-alikes that are not a downed worker.** The balance poll no-ops with
`{"skipped": …}` under `BAYRAM_USE_FAKE_PROVIDERS` or when `BAYRAM_VENDOR_BALANCE_POLL_ENABLED` is off
(vendor_balance_job.py:318-323). The tile renders "not polled" in all three cases. Check the worker
log before assuming the process is dead.

---

## 14. `purge_runs` shows bytes leaking, or shows a zero you cannot read

**SYMPTOM.** `storage_keys_returned > storage_keys_deleted` on a row.

**CAUSE.** Object bytes are deleted by the job **after** the transaction commits, and the two
numbers are recorded separately on purpose — "a crash leaves orphaned bytes (recoverable, sweepable)
rather than a row pointing at bytes that no longer exist" (purge.py:96-101). Every failing delete is
logged individually with its key, because "the key is the only handle an operator has for a manual
sweep" (retention_job.py:125-157). That query is the only place the leak is recorded.

**FIX.** Grep the worker log for `an expired object could not be deleted from storage`, collect the
keys, and remove them by hand from `<data root>/archive`.

> **`storageKeysDeleted: 0` no longer means what the job's docstring says.**
> `retention_job.py:32-38` still states that nothing writes `assets.storage_key`, so the sweep
> "records deleting zero keys". That is stale: `db/repository.py:383` writes it
> (`storage_key=archive_key(kit.order_id, asset.path.name)`), and repository.py:354-366 explains
> that this closes the archive-orphan bug. A zero there today means either nothing expired or the
> deletes are failing — not "the column is not written yet". Rows written *before* that fix are
> reconstructed by `purge._legacy_key` behind a strict filename pattern (purge.py:599-613).

---

## 15. Every media reveal in the panel 404s while the row says the file exists

**SYMPTOM.** `GET /api/assets/{id}` returns metadata happily. Streaming the audio returns 404
`NOT_FOUND`. It is fleet-wide, not per-order.

**LIKELY CAUSE.** The admin process and the bot/worker do not agree on the data root. The bot and
worker derive theirs from the **process working directory** — `root = (data_root or Path.cwd() /
"var").resolve()` (runtime/container.py:286) with no environment knob, and `main()` never passes one
(main.py:222). The admin uses `BAYRAM_ADMIN_DATA_ROOT`, whose default is the **relative** path `var`
(settings.py:423). Both are relative, so agreement depends entirely on the two processes sharing a
working directory — a deployment fact, not a code guarantee, and `settings.py:413-414` claims the
agreement without any variable enforcing it.

The 404 is precise, not incidental: a missing file becomes `NotFoundError` rather than
`StorageError` (`storage.py:274-291` → `_absent`, storage.py:107-119), and `NOT_FOUND` maps to 404
(errors.py:119). A permission fault on a root that *does* exist maps to 503 `STORAGE_FAILED`
instead (errors.py:128) — so 404 fleet-wide points at the wrong directory, and 503 points at a
mount that is there but unreadable.

The admin container deliberately does **not** `mkdir` its root: "conjuring it here would succeed on
a developer's laptop and hand every asset request a silent 404 in production"
(admin/container.py:152-156).

**HOW TO CONFIRM.** On the host, resolve both sides. The bot/worker side is `<their cwd>/var`; the
admin side is `<its cwd>/<BAYRAM_ADMIN_DATA_ROOT>`. Then:

```bash
ls <resolved root>/archive/orders/ | head
```

The bot's own boot log prints its workspace path — `container built` carries `workspace`
(runtime/container.py:297-304), which is the sibling of `archive` under the same root.

> **`[HOST 2026-09-11]` ON `abdu-test` THE TWO ROOTS AGREE, SO THIS FLEET-WIDE 404 IS
> STRUCTURALLY AVOIDED — AND THE REASON IS ONE LINE IN EACH UNIT, NOT A SETTING.** All four units
> carry `WorkingDirectory=/var/lib/hbd`. `hbd-bot.service`'s own comment block explains why that
> line is load-bearing: the data root is derived from the working directory, not from a setting —
> `runtime/container.py` resolves it as `cwd/var`, giving `/var/lib/hbd/var/{workspace,archive}` —
> so "changing this line moves every asset the panel expects to stream". Confirmed at runtime by
> the bot's boot line: `{"message": "container built", "workspace": "/var/lib/hbd/var/workspace",
> "database": "127.0.0.1:5432/hbd"}`.
>
> Two things follow. **An operator running a CLI by hand must `cd /var/lib/hbd` first**, or they
> act on a `var/` tree nothing has ever written to. And `[UNPROVEN]` nobody has listed the
> contents: `/var/lib/hbd` is `hbd:hbd` mode `0750`, so `ls <root>/archive/orders/` — the command
> above — cannot be run as `developer`. The agreement is proven from the units; what is *in* there
> is not.

**FIX.** Make `BAYRAM_ADMIN_DATA_ROOT` an **absolute** path equal to the bot's `<cwd>/var`. There is no
corresponding knob on the bot side; relocating its root means changing its working directory.

> **That root holds two key namespaces with different lifecycles.** `orders/{order_id}/{filename}`
> is swept on the asset clock (storage.py:73-84); `users/{user_id}/avatar.jpg` is deleted only by a
> customer's `/forget` (user_profiles.py:199-200). One `LocalFileStorage` instance serves both, for
> the reason spelled out at runtime/container.py:301-307. They cannot be scoped separately at the
> filesystem level, which matters for anything you do to that directory by hand.

---

## 16. Cannot create or recover the first operator

**SYMPTOM.** `--reset-owner` exits 1 with:

```
Refusing --reset-owner: this panel still has an active OWNER. Ask them to reset the account
instead — recovery exists for the case where nobody can sign in.
```

**CAUSE.** Recovery is refused while any active OWNER exists (bootstrap.py:186-191), which is what
stops it being a privilege escalation for anyone who reaches the host. The corollary bites: an
operator locked out of an OWNER account they still own cannot use it either. Deactivate that row
first — a step no document in this repo describes.

**SYMPTOM.** `--password` exits 1 without creating anything.

**CAUSE.** Refused on purpose (bootstrap.py:80-84): "a password in argv is visible in `ps` to every
user on this host and is written to your shell history." It is parsed with `argparse.SUPPRESS`
solely so it can be rejected with an explanation.

**SYMPTOM.** `--password-file` exits 1 naming the file's mode.

**CAUSE.** Any group or other permission bit at all is refused — `mode & 0o077`
(bootstrap.py:76-78, :124-134) — because a group-*writable* file can be replaced before it is read.
`chmod 600` and retry. The password is `.strip("\r\n")` only, so trailing spaces or tabs in the file
become part of the password.

**Exit codes are a contract**: 0 success, 1 operator refusal, 2 configuration/`BayramError`
(bootstrap.py:72-74, :319-343). Nothing ever prints a traceback, because a traceback would carry the
DSN. A deploy script can tell "already bootstrapped" from "the environment is wrong" without parsing
English.

To find every out-of-band ownership event afterwards, grep the audit log for the actor
`system:bootstrap` (bootstrap.py:239-271) — a real login cannot collide with it. Be aware that a
`--reset-owner` which *creates* a new account is audited as `ADMIN_PASSWORD_CHANGE`, because the
action is chosen from the flag rather than from what happened (bootstrap.py:274-283 against
:193-204).

---

## 17. Customer messages sent during a restart are never answered

**SYMPTOM.** Customers report that a message sent around a deploy got no reply.

**CAUSE.** Not a bug — `run_polling` calls `bot.delete_webhook(drop_pending_updates=True)` on every
start (`bot/app.py:216`). Every update that arrived during the deploy window is discarded and never
resent. main.py:156-162 records the one place this is compensated: a bot-block is learned in two
places, by the bot's `my_chat_member` update *and* by the worker's refused `sendAudio`, "because
every membership update that arrived during a deploy window is discarded and never resent, so the
worker's arm is the only source that survives a restart."

**FIX.** Restart during a quiet window. Nothing recovers the lost updates.

---

## 17a. Two things are polling one Telegram token — this is happening on `abdu-test` right now

**SYMPTOM.** Customers report that the bot answers sometimes and ignores them other times, with no
pattern anyone can pin down. Nothing in the product's own logs looks wrong: no traceback in a
handler, no failed render, no refused `sendAudio`. The bot unit is `active (running)` and
`/healthz`-style checks — which the bot does not serve anyway (§9) — say nothing either way.

**This is the one symptom in this document that was found by reading the journal rather than from a
report, and it had never been written down. It is live.**

```
{"level": "ERROR", "logger": "aiogram.dispatcher",
 "message": "Failed to fetch updates - TelegramConflictError: Telegram server says - Conflict:
 terminated by other getUpdates request; make sure that only one bot instance is running"}
```

`[HOST 2026-09-11]` **487 of those lines, every day since the units were first enabled**, and the
most recent was 11:19:56 on the day this was written:

| Day | Conflicts |
| --- | --- |
| Sep 05 | 60 |
| Sep 06 | 78 |
| Sep 07 | 66 |
| Sep 08 | 151 |
| Sep 09 | 42 |
| Sep 10 | 28 |
| Sep 11 (to 11:19) | 62 |

**CAUSE.** Telegram's `getUpdates` is exclusive per token: the *second* caller wins and the first
is terminated. Two consumers holding one token therefore do not split the traffic — **they take
turns stealing it from each other**, and every conflict line is a poll cycle whose updates went to
the other consumer. Nothing retries them, because from this process's point of view they never
arrived. This is the same discard that §17 describes at restart, except it is not bounded by a
deploy window.

**The second consumer is NOT on this host, and that is the most useful half of the finding.**
`[HOST 2026-09-11]` `pgrep -af 'hbd.main|bayram.main'` returns exactly one process,
`/opt/hbd/venv/bin/python -m hbd.main` (pid 193451), and `systemctl list-units` knows exactly one
bot unit. Nothing runs from the `/opt/bayram` cutover debris (00 row 49). So the competitor is
somewhere else holding the same `HBD_TELEGRAM_BOT_TOKEN` — and the hourly distribution points at a
human's machine rather than a stuck service: spread thinly across the night (2 conflicts in hour
00, 1 in 01, 2 in 04) and clustered in working hours (**17 in hour 08, 29 in hour 10**).

**FIX.** Find the other holder of the token; there is no fix on this host, because this host is
behaving correctly. In order of likelihood:

1. **A developer machine running the bot against the production token.** `.env` locally carrying
   the same `*_TELEGRAM_BOT_TOKEN` as `/etc/hbd/hbd.env` is the whole of it. Two different tokens
   from [@BotFather](https://t.me/BotFather) — one per environment — is the only durable fix, and
   it is the same separation `02-configuration.md` argues for every other vendor credential.
2. **A second deployment of this bot**, anywhere, including a container somebody left running.
3. **A webhook and polling at once** — ruled out here (`run_polling` deletes the webhook at every
   start, `bot/app.py:216`), but it is the other way to produce this line.

**HOW TO CONFIRM you have found it.** Stop the suspected second consumer, then watch for the
absence of new lines — an absence is the only proof, so give it an hour of working time rather than
a minute:

```bash
ssh aizu 'journalctl -u hbd-bot -f -o cat | grep --line-buffered TelegramConflictError'
```

**Why this matters more than its ERROR count suggests.** A customer who pays and then sends the
message that starts their song is in a race: if their update lands on the other consumer, the
payment is settled and the order never starts. The settlement path is now proven end to end
(`09-payme-go-live.md` §4.0) and `HBD_CHECKOUT_PROVIDER` is still unset, so **nobody has lost
money to this yet.** It must be closed before the rail is switched on, not after.

---

## 18. Log lines you expect to find, and how to find them

**SYMPTOM.** A documented post-deploy check returns nothing.

**CAUSE.** `deploy/first-install-proposal.md:143` (a proposal, written without host access) greps for
`host_verified`. That token does not exist anywhere in the tree. The log message is
`"host verified"` — with a space — and it is the *message*, not an `event` field
(runtime/startup.py:33-41). The next line in the same proposal, `grep admin.boot.ok`, does work,
because that one **is** an event field (app.py:325).

**How the log is shaped.** One JSON object per line whenever `BAYRAM_IS_DEBUG` is false, with a fixed
envelope of `ts`, `level`, `logger`, `message`, `correlation_id`, plus `context` holding every
`extra=` field, plus `exception`/`error` when an exception was passed (logging.py:200-220). The
`event` name, where there is one, lives **inside `context`** — a query must be `context.event`, not
a top-level `event`.

**Only the admin subsystem emits named events.** The bot, worker, pipeline and providers log English
prose, so any grep against them matches wording that is free to change. The prose lines worth
knowing:

| What you want to know | Grep for | Where |
| --- | --- | --- |
| The bot/worker booted, and off which env file | `host verified` | runtime/startup.py:33 |
| The bot is polling | `bot starting` | main.py:372 |
| The worker is up | `worker dependencies built` | worker.py:47 |
| A sweep ran | `retention sweep finished` | retention_job.py:267 |
| A sweep failed | `the retention purge failed` | retention_job.py:280 |
| Bytes were orphaned | `an expired object could not be deleted from storage` | retention_job.py:152 |
| The balance poll ran | `vendor balance poll finished` | vendor_balance_job.py:367 |
| The Payme backstop ran | `payme sweep finished` | runtime/payme_jobs.py |
| The money balances | `the payme settlement invariant holds` | runtime/payme_jobs.py — §20.3 |
| Scheduled broadcasts are firing | `the broadcast sweep finished` | runtime/broadcast_job.py |
| The gateway booted, and in which environment | `payme.boot.ok` | payme/app.py — an `event`, not prose; §20.1 |
| The paywall is on and the meter is off | `the checkout is wired but the credit meter is dark` | main.py:393 — and on a *live* rail this is now a boot refusal instead, main.py:114 |
| The database is unreachable | `database ping failed` / `database unreachable` | db/engine.py:109, :112 |

> **Those `file.py:line` citations drifted by up to 140 lines on 2026-09-10** — the Payme and
> broadcast work moved `db/purge.py`, `runtime/jobs.py`, `runtime/vendor_balance_job.py` and
> `db/admin/audit.py` most. Every citation on this page was re-checked against the working tree
> on 2026-09-11. Grep for the **message**, which is stable; use the line number only to open the
> file.

The named admin events that should page are `admin.audit.chain_broken` (ERROR),
`admin.audit.revoke_missing`, `admin.audit.write_failed` and
`admin.session.mirror_invalidation_failed` — the last meaning a revoked session may survive until
its mirror expires.

> **Turning on `BAYRAM_IS_DEBUG` to get more detail silently reformats the whole stream.** It is the
> only switch between JSON and the plain `%(asctime)s %(levelname)s [%(correlation_id)s]` formatter
> (logging.py:230-243); `BAYRAM_LOG_LEVEL` does not change the format. A shipper's parsing rules break
> at the worst possible moment. In prod the admin process refuses DEBUG outright
> (settings.py:589-593, citing the ORM echoing "names, notes, lyrics"); the bot and worker have no
> such refusal, only the `_NOISY_LOGGERS` floor pinning sqlalchemy/aiogram/uvicorn.access at
> ≥ WARNING (logging.py:100-113, :247-248).

> **THE WORKER'S JOURNAL IS NOT PURE JSON, AND THE `arq` FLOOR IS DEFEATED ON THE REAL
> INVOCATION.** `[HOST 2026-09-11]` Every arq line appears **twice**:
>
> ```
> 09:00:00:   1.00s → run_payme_sweep()
> {"ts": "2026-09-11T09:00:00+0500", "level": "INFO", "logger": "arq.worker",
>  "message": "  1.00s → run_payme_sweep()", "correlation_id": "-"}
> ```
>
> The mechanism is in the installed `arq` 0.26.3 and no dotenv file can change it:
> `arq/logs.py:default_log_config` builds a handler `arq.standard` (a `StreamHandler` with format
> `%(asctime)s: %(message)s`) and sets logger `arq` to **INFO**, and `arq/cli.py:44-45` applies it
> with `logging.config.dictConfig` — **after** `bayram.worker`'s module-scope `configure_logging()`
> has already run. So the `_NOISY_LOGGERS` floor above is overwritten for `arq` specifically, and
> propagation hands the record to both handlers. The `hbd-payme` journal carries uvicorn's plain
> `INFO:     Started server process […]` lines for the same reason — 42 of them.
>
> The practical consequence: **a naive `journalctl -u hbd-worker | jq` dies on every other line.**
> Pipe through `grep '^{'` first, and do not conclude from the plain lines that JSON logging is
> misconfigured. The sentence "one JSON object per line whenever `BAYRAM_IS_DEBUG` is false" is
> true of every line *this application* emits, and not of everything in the unit's journal.

Cron jobs bind no correlation id, so every line they emit carries `correlation_id: "-"` — a failed
sweep is found by timestamp and message, never by correlation. Admin request logs record the **route
template**, never the raw path, and an unrouted request as the constant `<unmatched>`
(logging_mw.py:31-33, :74-93): you cannot recover an order id or a query string from them, which is
the point (logging_mw.py:1-14).

---

## 19. Things this repository cannot fix for you

These are real exposures with no in-repo remedy. They belong to whatever fronts the panel.

**No `Strict-Transport-Security` from the application, ever.** It emits exactly three fixed
security headers — `x-content-type-options: nosniff`, `referrer-policy: no-referrer`,
`cache-control: no-store` — plus a per-response CSP (middleware/security_headers.py:73-77, :145).
A case-insensitive grep for `strict-transport` across `src/` returns nothing, and the CSP carries
no `upgrade-insecure-requests`. A first plain-`http://` request is not upgraded by anything this
code controls. The Secure cookies will not travel over it — that part fails closed — but the login
form and the URL do.

> **ON `abdu-test` THIS IS NO LONGER HYPOTHETICAL, AND BOTH HALVES OF IT HAVE MOVED.**
> `[HOST 2026-09-11]`
>
> **HSTS is now present — added by Caddy, not by the application.** `/etc/caddy/Caddyfile:95` in
> the admin block: `header Strict-Transport-Security "max-age=86400"`, deliberately without
> `includeSubDomains` and without `preload`, with the Caddyfile's own comment giving the reason
> (sibling hostnames on `bayrambot.uz`; preload is close to irreversible). The `pay.bayrambot.uz`
> block sets none. The grep above still holds for `src/`, but **not** for `deploy/` —
> `deploy/caddy/admin.bayrambot.uz.caddy` carries that line and is deployed verbatim.
>
> **THE PANEL NEVERTHELESS SERVES ITS LOGIN SHELL OVER PLAIN, UNENCRYPTED HTTP.**
> `curl -sI http://admin.bayrambot.uz/` returns `HTTP/1.1 200 OK`, `Content-Type: text/html`,
> with the full SPA shell, the full CSP and `strict-transport-security: max-age=86400` on a
> **cleartext** response. There is no redirect at any layer: Cloudflare's "Always Use HTTPS" is
> off for this hostname. HSTS cannot protect a browser's *first* visit, so this is exactly the
> residual risk the paragraph above describes, now observed. The `__Host-` cookie prefix means
> nobody can actually complete a sign-in over it — that half fails closed, loudly — but the login
> form and the typed URL travel in the clear first, and a credential typed into a cleartext form
> is already gone.
>
> **The fix is at a layer this repository does not own**: a Cloudflare "Always Use HTTPS" rule for
> `admin.bayrambot.uz`, or a Caddy `http://` → `https://` redirect. `08-payme.md` §4.6 is where
> the Cloudflare settings nobody has applied are tracked. Until then, treat the panel's login page
> as publicly sniffable.

**The bind address is not a control this code holds.** `BAYRAM_ADMIN_HOST` and `BAYRAM_ADMIN_PORT` are
read by nothing that binds a socket; their only consumers are the config view
(schemas/config_view.py:108-109, :202-203). The bind comes from the uvicorn command line alone
(Makefile:75). Changing `BAYRAM_ADMIN_PORT` changes what the panel **displays** and not what it
listens on — and if something starts the process with `--host 0.0.0.0`, the settings model cannot
detect it while `/api/config` keeps rendering `adminHost: 127.0.0.1`.

> **`[HOST 2026-09-11]` On `abdu-test` the bind is correct, and `ss` alone cannot prove which unit
> owns which port.** `ss -ltn` shows the panel on `127.0.0.1:8080` and the gateway on
> `127.0.0.1:8091`, with nothing in this stack on a public interface — the only publicly-bound
> sockets are `0.0.0.0:22`/`[::]:22` (sshd) and `*:80`/`*:443` (Caddy). **But the Process column of
> `ss -ltnp` is empty without root**, and `sudo -n ss -ltnp` is refused here, so the port→unit
> mapping comes from each unit's `ExecStart` (`systemctl cat <unit>`) rather than from `ss`. Worth
> one line because "I ran `ss -ltnp` and it showed nothing" is a permissions result, not a finding.
>
> **The panel being bound to loopback is nevertheless no longer the whole story.** It is published
> to the public internet on a hostname through a Cloudflare Tunnel, with no MFA and no IP
> allowlist — `07-security.md` §7 has what that does to the compensating-control argument.

**Source maps are served unauthenticated and cached for a year.**
`admin-ui/vite.config.ts:125` sets `sourcemap: true`, and `/assets` is a plain `StaticFiles` mount
(app.py:296-300) behind a middleware stack that authenticates nothing (app.py:387-390), stamped
`public, max-age=31536000, immutable` (security_headers.py:82, :86). The complete TypeScript source of
the console is downloadable by anyone who can reach the origin, and a year-immutable cache means
removing it later does not un-cache it.

> **ON `abdu-test` "ANYONE WHO CAN REACH THE ORIGIN" MEANS THE PUBLIC INTERNET, AND THIS IS
> MEASURED.** `[HOST 2026-09-11]`
>
> ```console
> $ curl -s -o /dev/null -w '%{http_code} %{size_download}\n' \
>     https://admin.bayrambot.uz/assets/index-D9iMG-RF.js.map
> 200 4242767
> ```
>
> 4.2 MB of TypeScript, unauthenticated, from outside. `07-security.md` §2 used to say "whether
> your TLS terminator blocks `/assets/*.map` is a host question"; **the answer here is no** — a
> grep of the whole `/etc/caddy/Caddyfile` for a `*.map` rule finds only comment text, and the
> admin block reverse-proxies the entire hostname.
>
> The fix belongs at the layer that can apply it — a Caddy `handle_path /assets/*.map { respond
> 404 }`, or a Cloudflare rule — and note what the year-immutable cache means: removing it later
> does not un-cache what has already been fetched. Treat the console's source as disclosed.

**`GET /api/config` publishes the deployment's topology to VIEWER.** `CONFIG_READ` is granted to
every role (security/permissions.py:240), and the view exposes database host/port, Redis host/port,
the claimed bind address, the trusted-proxy CIDRs and the argon2 cost parameters
(config_view.py:96-129). Secrets are correctly absent — it is an allowlist, and `admin_audit_dsn` is
reduced to a boolean — but the network facts are deliberately published.

**The "read-only data volume" is a mount property, not a code property — or a service-manager
property.** The admin container is handed a fully read-write `LocalFileStorage`
(admin/container.py:155); only the filesystem *or the supervisor* can make the read-only claim
true. Path traversal *is* defended in code and soundly — `_resolve` refuses absolute keys,
backslashes, NULs, empty and `..` segments, then re-checks the resolved path is under the root
(storage.py:133-146) — so the gap is writes, not escapes.

> **`[HOST 2026-09-11]` On `abdu-test` the kernel satisfies this claim, and the units know things
> these documents did not.** `systemctl show hbd-admin -p ReadWritePaths -p ProtectSystem` returns
> an **empty** `ReadWritePaths=` with `ProtectSystem=strict` — so the whole filesystem is read-only
> to the panel and the code property does not need to hold. `hbd-payme` is the same, plus
> `MemoryDenyWriteExecute=yes` and `InaccessiblePaths=/etc/hbd/hbd.env /etc/hbd/hbd-admin.env` —
> a kernel-level enforcement of the credential separation `07-security.md` §1 argues for in code.
> Only `hbd-bot` and `hbd-worker` get `ReadWritePaths=/var/lib/hbd /var/log/hbd`, which is
> exactly the pair that needs to write. That is a better posture than either document assumed,
> and it is worth saying out loud so nobody "fixes" it by adding a `ReadWritePaths` line.

**Nothing in this repository backs anything up.** No `pg_dump`, no snapshot script, no restore path.
The checkable form of that claim is `grep -rin backup README.md Makefile deploy/`, which returns
**zero hits** — same grep the sibling doc runs (00-host-inventory.md:93-94). Widening it to `docs/`
returns around thirty, and they are not counter-evidence: all but one are `docs/deployment/` saying
this same sentence in its own words. The one substantive hit for the word anywhere in the tree is
`docs/research/DASHBOARD_METRICS_RESEARCH.md:133`, where "backup" means a **fallback vendor**, not a data
backup. A real backup covers four things, three of which are not the database:

1. Postgres — including `credit_ledger`, `plan_purchases` and `topup_purchases`, which migration
   0020 calls receipts that answer disputes months after the name, the note and the audio are
   lawfully gone, **and now `payme_transactions`, `payment_intents` and `payme_rpc_log`**
   (migration `0023`) — the only rows that record a Payme settlement, of which `abdu-test` has a
   real one as of 2026-09-10.
2. `<data root>/archive` — delivered audio **and** every customer avatar.
3. Redis — the only copy of every in-progress wizard draft (14-day TTL matched to the
   abandoned-draft clock, `bot/app.py:44-48, :83-85`) and of the queue.
4. `BAYRAM_ADMIN_AUDIT_HMAC_KEY` — which lives in the admin env file, not in the database.

> **The repository claim above is still exactly true. The host has SOME of item 1 and NONE of
> items 2, 3 and 4 — and the one timer that looks like a backup belongs to another tenant.**
> `[HOST 2026-09-11]`
>
> `/var/backups/hbd/` holds **nine** `*.sql.gz`, all of them taken by release scripts immediately
> before they changed something — `pre-payme-*` ×5 (2026-09-09/10), `pre-wipe-*` ×2 (2026-09-10
> 09:22 and 09:24, the second only 563 bytes because the schema was already empty by then), and
> `pre-cutover-*` ×2 (2026-09-10 14:05/14:06). The command is
> `sudo -u postgres pg_dump -d hbd | gzip` (`/opt/hbd/release/wipe-and-rebuild.sh:91`), with **no
> `--no-acl` either way**, so whether grants come back is decided by `pg_dump`'s defaults rather
> than by a choice anybody made. No restore is scripted; the script prints
> `gunzip -c <dump> | sudo -u postgres psql -d hbd` on failure and that is the whole of it.
>
> **These are pre-change snapshots, not backups.** They exist on the days somebody ran a release
> script, they are on the same disk as the database, and nothing copies them off the box. Nothing
> dumps `/var/lib/hbd/var/archive`, nothing dumps Redis, and nothing anywhere holds a copy of
> `HBD_ADMIN_AUDIT_HMAC_KEY` — which means a restore from any of these nine files comes back with
> an audit log nobody can verify.
>
> **The decoy:** `aizu-backup.timer` is enabled, active and nightly (`OnCalendar=*-*-* 03:30:00`,
> `RandomizedDelaySec=300`, `User=aizu`, last fired 2026-09-11 03:31:04 +05). It runs
> `sqlite3 /var/lib/aizu/aizu.db ".backup …"` into `/var/backups/aizu`, keeping 14 days. It is an
> **unrelated application's** SQLite file. An operator who checks `systemctl list-timers`, sees a
> nightly backup and stops there has concluded the exact opposite of the truth.

A database-only restore comes back with an audit log nobody can verify, rows pointing at archive
objects that are gone, and no in-flight orders.

> **The HMAC key is write-once.** The chain is
> `HMAC-SHA256(key, "v1" ‖ prev_hmac ‖ canonical_json(row))` (db/admin/audit.py:10-15) and there is
> no key-id or key-version column on `admin_audit_log` — so rotating the key is indistinguishable
> from tampering across the entire log, and `/audit/verify` will report a break at the first row
> forever. Losing it makes the log permanently unverifiable. Back it up somewhere that is not the
> same backup as the table it signs.

**`var/workspace` is deleted by nothing.** Every song, greeting, cover and lyric sheet exists twice
on disk: the archive copy, swept on the retention clock, and the workspace copy, which no code in
this repo ever removes. `grep -rn 'rmtree\|\.unlink\|os\.remove' src/` — note `.unlink` with **no**
parenthesis — returns three deleting call sites, and none of them touches a published workspace
file:

| Call site | What it deletes |
| --- | --- |
| `storage.py:211` — `await asyncio.to_thread(resolved.unlink, True)` | The object-store deletion primitive, the one the retention sweep and `/forget` both run. It is rooted at the archive: the single `LocalFileStorage` is constructed `LocalFileStorage(archive)` (runtime/container.py:311), so it cannot reach `workspace`. |
| `storage.py:339` | A failed atomic write, cleaning up its own temporary file. |
| `audio/tempfiles.py:44` | A per-call scratch directory. |

The parenthesis matters and is worth a warning to whoever re-runs this: a pattern of `.unlink(`
silently misses the first row, because that call passes the method as a value to
`asyncio.to_thread` rather than calling it. A search that misses the tree's only object-deletion
primitive is not evidence of anything.

Whether anything sweeps `var/workspace` out of band is a host question. `[UNPROVEN]` on
`abdu-test`, and it is one of the few that is unprovable for a boring reason rather than an
interesting one: `/var/lib/hbd` is `hbd:hbd` mode `0750`, so the deploy account cannot `du` or `ls`
it. What *is* established is that no scheduled job anywhere on the box could be doing it —
`[HOST 2026-09-11]` there is no timer and no crontab for anything `hbd` (§13), so if something
sweeps that directory it is a human. For scale: the filesystem is 21 % full, 7.2 G of 38 G, 28 G
free, so nothing is urgent yet.

---

## 20. The Payme gateway — the fourth process this document did not know about

**Until 2026-09-10 a `grep -in payme` across §§1–19 returned nothing.** There were four
long-running processes on the host and three of them had a troubleshooting section. The one that
was missing is the **only process in this system with an inbound socket reachable from the public
internet without a login**, it holds the Payme cashbox key, and on 2026-09-10 it took a real
settlement.

**Its own symptom table is `08-payme.md` §10 and it is better than anything that belongs here** —
the `308` trap, the `-31050` account-field mismatch, the `-32504` burst, the pause key that a
Redis rebuild silently un-sets, the checkout links that keep being handed out while the gateway is
down. **If you have a payment symptom, go there.** What follows is only the set this page owes you:
the failure modes that **arrived with real credentials on 2026-09-10** and are therefore in no
runbook written before it.

### 20.1 The gateway boots with both of its own refusals disarmed

**SYMPTOM.** None. That is the entire problem. Nothing warns, nothing refuses, and the one place
the reasoning is written down — `hbd-payme.service`'s comment block — asserts the opposite.

**CAUSE.** `[HOST 2026-09-11]` Every `payme.boot.ok` on this host, including today's at
`06:50:15 +05`, reads:

```json
{"event":"payme.boot.ok","environment":"dev","env_file":"/etc/hbd/payme.env",
 "merchant_id":"6aa24fd9ee30563de3a1ac22","is_sandbox":true,"account_field":"order_id",
 "basic_login":"Paycom","duplicate_transaction_code":-31008,"merchant_key_length":36}
```

`environment: "dev"` **on the production host.** In the tree, `PaymeSettings.environment` defaults
to `"dev"` (payme/settings.py:162), `is_production` is `environment == "prod"` (:348-349), and
**both** of the gateway's boot refusals are gated on it:

* `_refuse_foreign_credentials` — `if settings.is_production:` (payme/app.py:219, the function at
  :203, called from the lifespan at :633). So a Telegram token or a vendor key sitting in
  `/etc/hbd/payme.env` would **boot without a word** on this host.
* the DEBUG refusal — `if self.is_production and (self.is_debug or self.log_level == _DEBUG_LEVEL)`
  (payme/settings.py:338). So `HBD_IS_DEBUG=true` would be **accepted** here. That one is a privacy
  failure as much as a security one: at DEBUG the ORM echoes bound parameters, and this process's
  parameters include idempotency keys carrying Telegram user ids, into a stream with no retention
  clock that neither `bayram.db.purge` nor a per-user erasure can reach.

**`is_sandbox: true` does not compensate, and do not read it as a mode.** `payme_is_sandbox` is
documented in the settings model as "a label, not a switch" (payme/settings.py:236-242) — it
changes no behaviour at all. The boot line therefore reports a sandbox *label* and a `dev`
*environment* while sitting in front of a cashbox that has moved real money.

**HOW TO CONFIRM.**

```bash
ssh aizu 'journalctl -u hbd-payme -o cat | grep payme.boot.ok | tail -1'
```

Read `environment`. `prod` is what you want. Anything else means the two refusals above are off.

**FIX.** Set the gateway's `BAYRAM_ENVIRONMENT` (on the host: `HBD_ENVIRONMENT`, in
`/etc/hbd/payme.env`) to exactly `prod` and restart the unit, **after** confirming the file holds
no foreign credential — because with the refusal armed, one that is present becomes a boot failure
rather than a silent warning, and you do not want to discover that during a payment incident.
`[UNPROVEN]` Nobody can check that file first with the access available: `/etc/hbd` is
`Permission denied` to `developer` and `sudo -n` is refused. So this fix needs somebody with a sudo
password and two minutes, in that order: read the file, then flip the variable.

Unlike `Settings.environment` on the bot, a typo here cannot pass silently in the same way —
`PaymeEnvironment` is a closed type — but `dev` is not a typo, it is the **default**, which is why
nothing caught it.

### 20.2 The caller allowlist is neither enforced nor auditable, and the unit file says otherwise

**SYMPTOM.** `payme.caller.refused` has never been logged, and every `payme.rpc` row records the
same `peer_ip`.

**CAUSE.** `[HOST 2026-09-11]` All **62** `payme.rpc` rows in the journal carry
`"peer_ip": "127.0.0.1"` — including one from a `GET https://pay.bayrambot.uz/payme` sent from the
public internet, which reached the gateway and was journalled with `reply_code -32300` and that
same loopback address. Caddy is the peer; the gateway declares no trusted-proxy hops, deliberately
(`08-payme.md` §4.5 argues why raising it would be wrong — the value would be load-bearing for a
filter that mints credits, and it is a header).

**What is worth flagging here is a document that is now wrong.** `hbd-payme.service`'s own comment
block claims "Every request journals its peer IP regardless, so the real caller set is discoverable
from our own logs." On this host that is **false**: the caller set is not discoverable from our
logs, because every entry is `127.0.0.1`. The `185.234.113.0/28` allowlist is therefore neither
enforced nor auditable from the box.

**FIX.** None at this layer, and `08-payme.md` §4.5 is explicit that the apparent fix is a trap.
The caller set lives in Cloudflare's event log, which nothing on the host can read (§4.6). Do not
raise `payme_trusted_proxy_hops` to make the journal prettier.

### 20.3 The settlement invariant now returns a non-zero count, and that is correct

**SYMPTOM.** `run_payme_sweep` logs a settlement line with counts in it, where it used to log
zeroes.

**CAUSE.** `[HOST 2026-09-11]` The first real settlement on this host was on 2026-09-10, and the
24-hour invariant window still contains it:

```json
{"message":"the payme settlement invariant holds",
 "context":{"window_from":"2026-09-10T04:00:00.149127+00:00",
            "window_to":"2026-09-11T04:00:00.149127+00:00",
            "transactions_performed":1,"receipts_written":1,"grants_written":1}}
```

**Three equal counts is the healthy shape** — one performed transaction, one receipt, one grant.
`python -m bayram.payme.cli invariant --hours N` is the same check on demand, and it **exits 3**
when the three do not balance, which is what makes it usable from a monitor. `[HOST 2026-09-11]`
Nothing is running it from a monitor here; the cron is the only caller, and it reports into the
journal nobody reads (§19).

**Do not read a settled gateway as a live paywall.** They are two switches (`08-payme.md`, the
two-switches note). `[HOST 2026-09-11]` `hbd-bot` still logs `the checkout is wired but the credit
meter is dark` at every boot, which — given that a *live* rail over a dark meter is now a boot
refusal (`05-operations.md`, *Credits and entitlements*) — tells you the bot's own rail is still the
stub. That is a recorded owner decision dated 2026-09-10, not an oversight
(`09-payme-go-live.md` §6).

### 20.4 The customer paid and no song started

**SYMPTOM.** A customer says they paid, the receipt arrived, and nothing began recording.

**FIRST: is this deployment even supposed to start one?** `BAYRAM_AUTO_RENDER_ON_PAYMENT`
defaults true but is the documented rollback lever for `DECISIONS.md D17`, and the feature is
unreachable on a stub rail by construction. If the bot's rail is the stub, "no song started" is
the shipped behaviour and the customer should press 🎬.

**Otherwise the answer is two columns on `payment_intents`, read by `public_ref`:**

```sql
select resume_order_id, resumed_at, settled_at, notified_at
from payment_intents where public_ref = :ref;
```

* `resume_order_id IS NULL` — **no marker was ever minted.** The purchase was made from
  `/balance`, or the draft was incomplete or had no approved lyric when the link was built, or
  the intent predates migration 0026. Not a fault; the customer's receipt carried a live 🎬 if
  a usable draft was parked.
* `resumed_at IS NULL` — **the job never reached a decision.** The notification may not have
  been delivered yet (check `notified_at`), or the resume declined before claiming. The reason
  is in the journal:

  ```
  journalctl -u bayram-worker | grep "the settled payment's render was considered"
  ```

  The `reason` field is a closed vocabulary and is the whole answer: `disabled`, `no_marker`,
  `no_storage`, `no_draft`, `draft_moved`, `not_on_confirm`, `already_queued`, `order_exists`,
  `already_claimed`, `no_progress_message`, `no_queue`, `enqueue_failed`, `queued`.
* `resumed_at` set with **no `orders` row for `resume_order_id`** — the claim was taken and the
  worker then died before the enqueue. **There is no automated recovery for this, by design**
  (D17, claim-before-act): tell the customer to press 🎬, which still works and still costs
  them the credit they already paid for exactly once.

**`draft_moved` is not a bug.** It means the customer edited their answers after paying, and
the render was declined rather than made from the answers they had changed. Their receipt
carries a live 🎬 on the draft they are actually holding.


---

## Quick reference: what a healthy deployment answers

The third column is the value a healthy deployment answers. The fourth is what `abdu-test`
actually answered on 2026-09-10/11 — **three of these eleven rows do not pass there**, and an
unqualified target column was inviting readers to assume they did.

| Question | Where the answer is | Healthy value | `abdu-test` |
| --- | --- | --- | --- |
| Which env file did this process read? | `systemctl cat <unit>` → `EnvironmentFile=`. **Not** `context.env_file` — see §8 | the intended path | `[HOST 2026-09-11]` `/etc/hbd/*.env`, correct. The boot lines print the relative defaults `.env` / `.env.admin` and that is **healthy** here |
| Is this really prod? | `host verified` / `admin.boot.ok` → `context.environment`; and for the gateway, `payme.boot.ok` | the exact string `prod` | `[HOST 2026-09-11]` bot, worker, panel: `prod`. **Gateway: `dev`** — §20.1, and it disarms two refusals |
| Is the console bundle current? | absence of `admin.spa.nonce_placeholder_missing` | no such line | `[HOST 2026-09-11]` zero, in the whole journal. Passes |
| Are vendor keys near the panel? | `admin.boot.vendor_env_present` | no such line (in prod it is a boot refusal, so a running prod panel is itself the evidence) | `[HOST 2026-09-11]` zero, ever, and the panel runs `prod`. Passes — but see §8: the *file* half of that scan is a no-op here |
| Did the REVOKE land? | cheapest: `journalctl -u <admin unit> \| grep admin.audit.revoke_missing`. Then `GET /api/audit/verify` → `chainProtection` | `revoke+hmac`, and no WARNING | **FAILS.** `[HOST 2026-09-10]` two `admin.audit.revoke_missing` WARNINGs; `chainProtection` itself `[UNPROVEN]` (no session). An open item, not a passing check — §3 |
| Is the whole chain verified? | the same call → `ok` **and** `isComplete` | both true | `[UNPROVEN]` needs an ADMIN/OWNER session. Indirect evidence: `admin.audit.chain_broken` has never been logged, and the HEAD anchor is re-pinned hourly |
| Is the sweep running? | `SELECT max(ran_at) FROM purge_runs`, or the journal line if `psql` is walled | within the last hour | `[HOST 2026-09-11]` `retention sweep finished` at `:17` every hour. Passes |
| Are bytes leaking? | `storage_keys_returned` vs `storage_keys_deleted` | equal | `[HOST 2026-09-11]` `0` and `0`. Equal, and nothing has expired yet |
| Is the deployment observable? | `curl -H 'X-Probe-Token: …' /readyz` | a body with `database` and `redis`, not a bare `{"status":"ok"}` | **FAILS in practice.** `[UNPROVEN]` whether the token is set; `[HOST 2026-09-11]` nothing is polling on a schedule, and the logs go to the journal and nowhere else — §9, §19 |
| Can the migration runner run at all? | `<venv>/bin/python -c 'import <pkg>'` | the installed package imports | **FAILS.** `[HOST 2026-09-11]` `/opt/hbd/migrations/env.py` imports `bayram`; the venv holds `hbd`. Four recovery procedures end here — §11 |
| Is anything backing anything up? | `systemctl list-timers`, then read what the timer actually dumps | a timer that dumps *your* database, off-box | **FAILS.** `[HOST 2026-09-11]` nine hand-taken `pg_dump`s on the same disk; the only nightly timer backs up another tenant's SQLite file — §19 |
