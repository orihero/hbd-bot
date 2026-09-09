# Configuration reference

Everything this product reads is `HBD_`-prefixed and maps 1:1 onto a field of one of two
settings classes: `hbd.config.Settings` for the bot and the worker, and
`hbd.admin.settings.AdminSettings` for the admin API. Both are `frozen=True` and both use
`extra="ignore"` (`src/hbd/config.py:161-167`, `src/hbd/admin/settings.py:160-166`), which
has a consequence worth putting first: **a misspelled variable is not an error anywhere**.
It is silently discarded, in both files, in every environment.

This page is exhaustive about what production actually requires and deliberately not
exhaustive about the rest. `.env.example` (89 assignments) and `.env.admin.example` (35)
carry the long tail with the reasoning attached; read them for anything not named here.

---

## The two axes

Conflating these is the usual mistake, and README.md:197-215 says so too.

**`HBD_ENVIRONMENT` is a value *inside* a file.** It is what the code branches on. Five
refusals in the whole tree key off it: two on the bot/worker side and three in the admin
process.

| Refusal | Where |
| --- | --- |
| `HBD_USE_FAKE_PROVIDERS` while `prod` | `src/hbd/runtime/providers.py:105` |
| the in-process (no-queue) submitter in `prod` | `src/hbd/runtime/submitter.py:101` |
| `HBD_ADMIN_PUBLIC_ORIGIN` unset outside `dev` | `src/hbd/admin/settings.py:578-588` |
| `HBD_IS_DEBUG` / `HBD_LOG_LEVEL=DEBUG` in `prod` | `src/hbd/admin/settings.py:589-593` |
| a vendor credential within reach of the admin process in `prod` | `src/hbd/admin/app.py:189-201` |

**`HBD_ENV_FILE` and `HBD_ADMIN_ENV_FILE` decide *which file* is read.** They are
process-environment variables and can only be that: a dotenv file cannot name the dotenv
file about to be read (`src/hbd/config.py:74-81`). Writing either of them *into* a dotenv
file is a line with no effect, not a redirect. They default to `.env` and `.env.admin`
(`src/hbd/config.py:71`, `src/hbd/admin/settings.py:65`), so a checkout that has only ever
had those two behaves exactly as it always has.

> **`Settings.environment` is an unvalidated `str`; `AdminSettings.environment` is a closed
> `Literal`.** `src/hbd/config.py:170` is `Field(default="dev")` with no validator, while
> `src/hbd/admin/settings.py:169` is `Literal["dev","staging","prod"]` — and the docstring at
> `src/hbd/admin/settings.py:15-17` explains why it was closed: "a typo like `production`
> would silently downgrade the strongest boot control in the package". Both classes derive
> production as `environment == "prod"` exactly (`src/hbd/config.py:684-686`,
> `src/hbd/admin/settings.py:597-599`). That argument was never applied back to `Settings`,
> so `HBD_ENVIRONMENT=production` or `PROD` on the bot or the worker is accepted, reads as
> not-production, and disarms both bot-side refusals with no error anywhere. Type the string
> `prod`, lowercase, and confirm it from the boot log rather than from the file.

### The file × process matrix

| | bot (`hbd.main`) | worker (`arq hbd.worker.WorkerSettings`) | admin API (`uvicorn hbd.admin.app:app`) | migrations (`alembic upgrade head`) |
| --- | --- | --- | --- | --- |
| settings class | `Settings` | `Settings` | `AdminSettings` | none, when `HBD_DB_MIGRATION_URL` is set; otherwise `Settings`, via `load_settings()` |
| file read | `HBD_ENV_FILE`, else `.env` | same | `HBD_ADMIN_ENV_FILE`, else `.env.admin` | `HBD_ENV_FILE`, else `.env` |
| holds vendor keys | yes, required | yes, required | **never** — no field can hold one | inherits the bot's file |
| needs ffmpeg | yes | yes | no | no |

The admin process reads a different file from the bot *because that separation is the
vendor-key boundary*, not as a convenience — `src/hbd/admin/settings.py:64` says it plainly
("Never `.env`: a shared file is how a vendor key reaches a process that must not hold
one"), and the deliberate choice of a *second* variable rather than one shared tier name is
argued at `src/hbd/admin/settings.py:67-72`.

Migrations are a fourth command and read the **bot's** file (`migrations/env.py:95-113`,
`migrations/env.py:117-129`). They never read `.env.admin`. That has a sharp consequence for
the audit REVOKE — see below.

> **Whether migrations build a `Settings` object at all depends on `HBD_DB_MIGRATION_URL`.**
> `load_settings` is imported at `migrations/env.py:57` and called from exactly one place,
> `migrations/env.py:129` — the else-branch of `_database_url()`, reached only when no owner
> DSN was found. With the owner DSN set (the two-role deployment the section below urges), no
> settings object is constructed and the bot's vendor keys are never touched. **Without it,
> the fallback calls `load_settings()`, which always passes `require_vendor_secrets=True`
> (`src/hbd/config.py:758-760`)** — so on a one-role host whose bot env file carries no vendor
> keys, `make migrate` does not fall back with a warning: it refuses outright with the same
> four-variable `ConfigError` the bot would raise. The matrix cell above reads "inherits the
> bot's file"; on that path it inherits the bot's *requirements* too.

`make` wraps the two variables in one flag (`Makefile:41-46`):

```bash
cp .env.example .env.prod             && $EDITOR .env.prod
cp .env.admin.example .env.admin.prod && $EDITOR .env.admin.prod

make dev   ENV=prod     # HBD_ENV_FILE=.env.prod HBD_ADMIN_ENV_FILE=.env.admin.prod
make admin ENV=prod     # …and the same for worker, migrate, revision, admin-bootstrap
```

`ENV=dev` is the default and maps to the bare names, so nothing changes for anyone who never
passes the flag. On a host that sets `HBD_ENV_FILE` in the process environment directly,
none of this `make` machinery is involved.

### Precedence, and the one failure the error message cannot describe

Process environment beats the dotenv file, for every variable on both classes: both builders
pass the resolved path as a `_env_file` *default* (`src/hbd/config.py:741`,
`src/hbd/admin/settings.py:668`) and pydantic-settings ranks init kwargs > environment >
dotenv > field defaults. A value supplied by the dotenv file still counts towards
`model_fields_set`, which is what the `HBD_ADMIN_PUBLIC_ORIGIN` guard tests.

> **A mistyped `HBD_ENV_FILE` reads no file at all, silently, and the error never names it.**
> `dotenv_values` on a path that does not exist returns an empty mapping and raises nothing.
> With `HBD_ENV_FILE=/nonexistent/.env.prod`, `load_settings()` raises exactly this:
>
> ```
> Configuration is invalid or incomplete. Fix these environment variables (see .env.example):
>   HBD_TELEGRAM_BOT_TOKEN: Field required
>   HBD_DATABASE_URL: Field required
>   HBD_ELEVENLABS_API_KEY: Field required
>   HBD_LLM_API_KEY: Field required
> ```
>
> The preamble's "see .env.example" is hardcoded (`src/hbd/config.py:702-704`; the admin twin
> at `src/hbd/admin/settings.py:640-643`) and is *not* the file that was resolved. The file
> actually read is logged only afterwards, by `verify_host` (`src/hbd/runtime/startup.py:34-41`)
> and by `admin.boot.ok` (`src/hbd/admin/app.py:329`) — both of which run only once settings
> have already built. So the one failure mode this feature introduces is the one its error
> message cannot report. Worse: if the four required values happen to be exported in the
> deploy shell, a mistyped path boots the bot on 100% defaults, including
> `HBD_ENVIRONMENT=dev`.

The check after any deploy is therefore the boot log, not the file on disk. Both boot paths
emit one line naming the file they actually read. The two strings to look for are:

- **bot and worker** — `host verified`, one line at INFO, emitted by `verify_host`.
- **admin API** — `admin.boot.ok`, the same pair plus the origin the CSRF check will enforce.

Whether these three processes' stdout is collected anywhere an operator can search, and for
how long it is kept, is a property of the deployment and is **not knowable from this
repository** — see "Host assumptions" at the end of this page. Whatever that source turns
out to be, the search is `<your log source> | grep 'host verified'` and
`<your log source> | grep 'admin.boot.ok'`.

Note the exact strings. `host verified` has a **space** and is the log *message*, not an
`event` field — `verify_host` puts `environment`, `env_file`, `ffmpeg`, `locales` and
`catalogue_languages` in `extra` and no `event` key at all
(`src/hbd/runtime/startup.py:33-41`), and under JSON logging the message lands as
`message` (`src/hbd/logging.py:200-220`). `admin.boot.ok` *is* a real `context.event`
(`src/hbd/admin/app.py:325`). A grep for `host_verified` with an underscore matches nothing
in this tree, so an empty result from that spelling is not evidence the bot failed to boot.

---

## Required in production — bot and worker

Exactly four, and they are required in **every** environment, not only prod. Nothing becomes
newly required at `HBD_ENVIRONMENT=prod` on this side.

| Variable | Class | Default | What refuses or degrades |
| --- | --- | --- | --- |
| `HBD_DATABASE_URL` | `Settings` | **none** (`Field(min_length=1)`, `src/hbd/config.py:187`) | Process will not build settings. `ConfigError`, exit 2 on the bot. |
| `HBD_TELEGRAM_BOT_TOKEN` | `_VendorBoundSettings` | **none** in this path (`src/hbd/config.py:697`; optional `""` on the base class at `:184`) | Same. |
| `HBD_ELEVENLABS_API_KEY` | `_VendorBoundSettings` | **none** (`src/hbd/config.py:698`) | Same. Music, TTS and STT all ride this one key. |
| `HBD_LLM_API_KEY` | `_VendorBoundSettings` | **none** (`src/hbd/config.py:699`) | Same. |

The three vendor secrets are required by a *subclass*, not a flag:
`build_settings(require_vendor_secrets=True)` selects `_VendorBoundSettings`
(`src/hbd/config.py:739`), and `load_settings()` — the boot path for both the bot and the
worker — always passes `True` (`src/hbd/config.py:758-760`). A process that must not hold
them passes `False`; the two operator CLIs under `src/hbd/tools/` do exactly that, which is
why they run on a box with no vendor keys.

> **The bot and the worker report the same misconfiguration differently.** `hbd.main` builds
> settings inside `try/except HbdError`, prints `hbd: <operator message>` and returns 2
> (`src/hbd/main.py:213-218`). The worker builds them at **module import** —
> `_SETTINGS = _settings()` at `src/hbd/worker.py:40` — so the same bad file produces an
> uncaught traceback from the `arq` CLI, with no clean one-line message. (Whether anything on
> the host restarts the worker after that exit, and therefore whether the traceback repeats,
> depends on a supervisor this repository knows nothing about.) Do not read a worker traceback
> as a different class of problem from a bot's tidy
> refusal; check the four variables first.

> **`HBD_REDIS_URL` is the dangerous default on this list.** It defaults to
> `redis://localhost:6379/0` (`src/hbd/config.py:188`), so a wrong or missing value does not
> fail — it connects to whatever local Redis exists. In production the bot has no non-Redis
> path: `build_submitter` takes the `create_pool(...)` branch because the in-process
> submitter is refused (`src/hbd/main.py:89-95`, `src/hbd/runtime/submitter.py:101`). Redis
> is a hard dependency of *both* long-running processes, and they must share one URL and one
> logical DB: the bot parks a wizard session in the FSM store and only the worker's job
> releases it (`src/hbd/bot/app.py:83-97`, `src/hbd/worker.py:51-57`,
> `src/hbd/runtime/jobs.py:771`). Two different Redis databases leaves customers parked with
> no error on either side.

---

## Required for the admin API

| Variable | Class | Default | What refuses or degrades |
| --- | --- | --- | --- |
| `HBD_DATABASE_URL` | `AdminSettings` | **none** (`src/hbd/admin/settings.py:174`) | Settings will not build. |
| `HBD_ADMIN_AUDIT_HMAC_KEY` | `AdminSettings` | **none**, `SecretStr`, `min_length=32` (`src/hbd/admin/settings.py:229`) | Settings will not build. See the callout below — this one is not replaceable later. |
| `HBD_ADMIN_ENABLED` | `AdminSettings` | `false` (`src/hbd/admin/settings.py:180`) | Settings build fine; the **lifespan** refuses (`src/hbd/admin/app.py:206-208, :315`) with "The admin panel is disabled. Set HBD_ADMIN_ENABLED=true in .env.admin to run it." |
| `HBD_ADMIN_PUBLIC_ORIGIN` | `AdminSettings` | `http://127.0.0.1:8080` — dev only (`src/hbd/admin/settings.py:194`) | Refused at boot outside `dev` unless **set** (`:578-588`). Wrong-but-set is not caught; every mutation then 403s `ORIGIN_REJECTED` while the panel looks healthy. |

`HBD_ADMIN_ENABLED=false` is the shipped default on purpose — "an admin surface that appears
because a dependency was installed is not a decision anybody made"
(`src/hbd/admin/settings.py:177-179`). A first deploy of the admin process will refuse to
start until someone turns it on, and that is the intended shape.

> **The origin guard tests whether the variable was *set*, not whether it is plausible.** The
> check is `"admin_public_origin" not in self.model_fields_set`
> (`src/hbd/admin/settings.py:580`), and a value supplied by the dotenv file counts as set.
> `.env.admin.example:73` ships the line **uncommented, at the loopback dev value** — so
> copying the example onto a production host and setting `HBD_ENVIRONMENT=prod` disarms the
> guard and produces precisely the incident its own message predicts: "the loopback default
> would boot, pass `/healthz`, serve a login page and then reject every mutation with
> ORIGIN_REJECTED" (`src/hbd/admin/settings.py:582-587`). Set it to the exact origin a browser
> reaches — scheme, host, optional port, no path, no trailing slash
> (`src/hbd/admin/settings.py:500-514`) — and confirm it from the `public_origin` field of
> `admin.boot.ok`.

### The admin process must not hold a vendor credential

`FORBIDDEN_ENV_VARS` is **derived**, never restated: it upper-cases
`hbd.config.VENDOR_SECRET_FIELDS` with the `HBD_` prefix (`src/hbd/admin/app.py:116-118`),
so the five names are exactly `HBD_TELEGRAM_BOT_TOKEN`, `HBD_ELEVENLABS_API_KEY`,
`HBD_LLM_API_KEY`, `HBD_LLM_FALLBACK_API_KEY` and `HBD_OPENROUTER_MANAGEMENT_KEY`
(`src/hbd/config.py:111-117`). Note the
asymmetry with the *required* tuple one field below it
(`REQUIRED_VENDOR_SECRET_FIELDS`, `src/hbd/config.py:123-127`): "the admin host must never
hold it" and "this process cannot start without it" are two different claims, and the
fallback LLM key is on the first list only.

The scan covers both the process environment and the names parsed out of the admin dotenv
file (`src/hbd/admin/app.py:175-183`), reading the file through the *same* resolver
`build_admin_settings` uses so it cannot clear a host whose keys sit in the file that was
actually loaded (`src/hbd/admin/app.py:141-149`). In `prod` a hit is a `ConfigError`; in
`dev` and `staging` it is the WARNING `admin.boot.vendor_env_present`
(`src/hbd/admin/app.py:189-203`).

> **The disabled-panel refusal runs first.** `src/hbd/admin/app.py:315-316` calls
> `_refuse_disabled_panel` then `_refuse_vendor_credentials`, and both raise `ConfigError`.
> On a host with both problems the operator is told the panel is disabled and never learns a
> vendor key was within reach. After turning `HBD_ADMIN_ENABLED=true`, read the next boot
> attempt rather than assuming the first message was the only one.

---

## The three fields with no usable default

Across all 88 `Settings` fields, all 88 `_VendorBoundSettings` fields and all 35
`AdminSettings` fields, exactly three are required with no default of any kind:

```
Settings.database_url             src/hbd/config.py:187
AdminSettings.database_url        src/hbd/admin/settings.py:174
AdminSettings.admin_audit_hmac_key  src/hbd/admin/settings.py:229
```

Everything else is defaulted; the three vendor secrets become required only through
`_VendorBoundSettings` (`src/hbd/config.py:689-699`).

**Generate the audit key with this, and nothing else:**

```bash
python -c "import secrets; print(secrets.token_urlsafe(48))"
```

That is the command the repo already documents (`.env.admin.example:120`, README.md:156). It
yields 64 URL-safe characters, comfortably over the `min_length=32` floor — and note that the
floor is counted in *characters of the secret*, so pydantic's refusal reads "Value should
have at least 32 items after validation, not 0" rather than naming a key.

> **This key is write-once for the life of the audit log, and it lives outside the database.**
> Each row's MAC is `HMAC-SHA256(key, "v1" ‖ prev_hmac ‖ canonical_json(row))`
> (`src/hbd/db/admin/audit.py:10-15`) and there is **no key-id column** on `admin_audit_log`
> (`src/hbd/db/models/admin_audit.py:131-197`). `verify_chain` walks from the oldest row and
> reports the first MAC that does not recompute (`src/hbd/db/admin/audit.py:594-641`), so
> changing the key makes `/api/audit/verify` report a break at the first row, permanently, and
> losing it makes the log permanently unverifiable — neither is distinguishable from tampering.
> It is required from the first boot rather than from the first audited action precisely so
> the chain never has an unsigned prefix (`src/hbd/admin/settings.py:220-223`). Back it up
> **separately from the database dump**: a backup that contains both the table and its key is
> a backup anyone holding it can rewrite. Nothing in this repository backs up anything —
> `grep -rn 'pg_dump\|backup' README.md Makefile deploy/ docs/` finds one hit and it means a
> fallback vendor — so this is an obligation the deployment owns entirely.

Two DSNs, not one: `HBD_DATABASE_URL` appears on both classes and both processes need it,
but they are separate fields on separate models. See "Owned by both classes" below for what
that means in practice.

---

## `HBD_DB_MIGRATION_URL`, and why it is not a `Settings` field

It is read by `migrations/env.py` and by nothing else. It is deliberately **not** a field on
`Settings`, and `.env.example:43-45` gives the reason: "the bot and the worker must never
hold the owner credential, and a field on the shared object is an invitation to". A field
would put the table owner's password in reach of two long-running processes that have no use
for it.

Its presence is how a deployment *declares* the two-role split: `hbd` owns the tables and
runs migrations, `hbd_app` is what the bot, the worker and the admin API connect as, and
migration 0007's `REVOKE UPDATE, DELETE, TRUNCATE ON admin_audit_log` only means anything
when those are two different roles. An owner can `GRANT` back anything revoked from it, so a
one-role deployment has no privilege-based audit protection at all.

Resolution order (`migrations/env.py:95-114`): the process environment first, then
`dotenv_values(env_file())` — the **bot's** file. That dotenv fallback was added because the
environment-only version was a bug that would have migrated production as the wrong role
(`migrations/env.py:14-19`). Unset, migrations still run, against `HBD_DATABASE_URL`, with
this WARNING (`migrations/env.py:88-93`):

```
HBD_DB_MIGRATION_URL is not set, so migrations are running as the application role. That
role owns every table it creates, and an owner can GRANT back anything revoked from it — so
the audit log's REVOKE is not a control on this deployment.
```

That line at migration time, and `chainProtection` on `GET /api/audit/verify`, are the two
observable answers to "is the split actually deployed". The badge is honest by construction:
it asks Postgres `has_table_privilege(current_user, 'admin_audit_log', 'UPDATE'/'DELETE'/'TRUNCATE')`
rather than reading configuration (`src/hbd/db/admin/audit.py:746-780`), and reports
`hmac-only` with the WARNING `admin.audit.revoke_missing` when the role can still write.

> **Two more variables gate the REVOKE, and both are read from `os.environ` only.** Migration
> 0007 skips unless `HBD_ADMIN_AUDIT_DSN` is in the environment
> (`migrations/versions/20260830_1000_0007_add_admin_audit_log.py:336`) and then resolves the
> role name from `HBD_DB_APP_ROLE`, falling back to the username inside `HBD_DATABASE_URL`
> — again from `os.environ` alone (`:314-322`). Migration 0011 repeats the pattern. Neither
> has the dotenv fallback `migrations/env.py` gave itself. `HBD_ADMIN_AUDIT_DSN` is documented
> as living in `.env.admin` (`.env.admin.example:130`), which the migration runner never
> parses, and **`HBD_DB_APP_ROLE` appears in neither example file**. So a deployment
> configured exactly as documented takes the first `_skip` branch and installs no REVOKE and
> no `SECURITY DEFINER` purge functions — as two WARNINGs in the alembic output, not a
> failure. Export both into the migrate shell — **and make sure the bot env file you point at
> carries `HBD_DB_MIGRATION_URL`**, or alembic connects as the application role and the REVOKE
> is taken while connected as the role being revoked from. That combination is the worst one
> available: `HBD_ADMIN_AUDIT_DSN` alone satisfies migration 0007's only guard (`:336`) so
> `_apply_revoke` runs and reports success, while alembic's own connection came from
> `_database_url()`, which silently fell back to the application DSN with nothing but the
> one-role WARNING (`migrations/env.py:117-129`). Three variables, not two:
>
> ```bash
> HBD_ENV_FILE=<the bot env file, which must contain HBD_DB_MIGRATION_URL> \
> HBD_ADMIN_AUDIT_DSN='postgresql+asyncpg://<owner>:…@…/<db>' \
> HBD_DB_APP_ROLE=<the application role> \
>   python -m alembic -c migrations/alembic.ini upgrade head
> ```
>
> `HBD_DB_MIGRATION_URL` may equally be exported into the same shell — the process environment
> wins over the dotenv file (`migrations/env.py:95-114`) — but one of the two must supply it.
> Before running, read the alembic output for the one-role WARNING quoted above: if it is
> there, stop, because the REVOKE that follows it is theatre. The command shape assumes a
> source checkout with `migrations/` present and alembic importable; `migrations/` is not in
> the wheel, and how the migrate command is actually invoked on the target host is a
> deployment property this page does not know (see "Host assumptions").
>
> Then confirm with `chainProtection` on `/api/audit/verify`, or `\dp admin_audit_log` in
> psql. Do not infer it from the fact that the variables were set.

Two related facts about the DSNs, both from the repo rather than from any host:

- **`.env.admin.example:48` ships the admin process connecting as the owner role `hbd`,**
  contradicting `.env.example:35` (`hbd_app`), `docker/initdb/10-two-roles.sql` and
  README.md:160-161, all of which say all three processes connect as `hbd_app`. The admin
  API is the process that *writes* `admin_audit_log`; pointing it at the owner defeats the
  REVOKE even on a deployment that applied it. Give the admin process the **application**
  role's DSN.
- **`docker/initdb/10-two-roles.sql` is a local development artefact** with a hardcoded
  password and runs only once, on an empty Docker volume. The file itself says so
  (`docker/initdb/10-two-roles.sql:25-33`): "In staging or production, create these two roles
  by hand with real secrets." Nothing in this repository creates production roles — including
  the `ALTER DEFAULT PRIVILEGES FOR ROLE hbd … GRANT … TO hbd_app` lines
  (`docker/initdb/10-two-roles.sql:46-49`), without which every table a *future* migration
  creates is invisible to the application role.

---

## Notable optional variables, by subsystem

Defaults are the shipped values. Only the ones with a production consequence are here; the
rest are in the example files with their reasoning.

### Runtime, on both classes

| Variable | Class | Default | Consequence |
| --- | --- | --- | --- |
| `HBD_ENVIRONMENT` | both | `dev` | The five refusals above. Free-form `str` on `Settings` (`src/hbd/config.py:170`); closed literal on `AdminSettings` (`:169`). |
| `HBD_LOG_LEVEL` | both | `INFO` | Refused at `DEBUG` in prod on the admin only (`src/hbd/admin/settings.py:589-593`). |
| `HBD_IS_DEBUG` | both | `false` | **Changes the log *format*, not the level.** `configure_logging(level, is_json=not is_debug)` — true switches the whole stream from one JSON object per line to human text (`src/hbd/logging.py:230-243`; callers `src/hbd/main.py:220`, `src/hbd/worker.py:36`, `src/hbd/admin/app.py:314`). Turning it on to get detail silently breaks any log shipper's parsing. |
| `HBD_USE_FAKE_PROVIDERS` | `Settings` | `false` | Refused outright in prod (`src/hbd/runtime/providers.py:105`). |

The bot and worker have **no** prod refusal on DEBUG. The mitigation on that side is the
floor in `configure_logging`, which pins `sqlalchemy`, `sqlalchemy.engine`,
`sqlalchemy.pool`, `aiogram`, `arq` and `uvicorn.access` at `max(WARNING, root.level)`
(`src/hbd/logging.py:100-113, :247-248`) — real, and applied in every process, but a policy
inside a module rather than a boot-time refusal.

### Vendors and spend

| Variable | Class | Default | Consequence |
| --- | --- | --- | --- |
| `HBD_MUSIC_MAX_CONCURRENCY` | `Settings` | `2` (`src/hbd/config.py:195-200`) | A per-**process** `asyncio.Semaphore` (`src/hbd/runtime/container.py:332-333`), not a fleet cap. Two worker replicas at the default make 4 simultaneous renders against a vendor ceiling of 2. |
| `HBD_MUSIC_USD_PER_MINUTE` | `Settings` | `0.15` (`src/hbd/config.py:207-217`) | **The only non-zero rate in the card**, and it is a placeholder list price. Every other leg ships `0.0`, which means "not priced" (`cost_usd` NULL, panel prints "not priced") and never "free". Until an operator fills the card in, the Vendors screen's spend total is a true sum over a minority of calls. No refusal behind this. |
| `HBD_VENDOR_BALANCE_POLL_ENABLED` | `Settings` | `true` (`src/hbd/config.py:313`) | Off, or under fakes, the hourly cron registers and no-ops; the balance tiles render "not polled", which is indistinguishable from a worker that is down. |
| `HBD_OPENROUTER_MANAGEMENT_KEY` | `Settings` | `""` (`src/hbd/config.py:248-262`) | **Optional, and the sharpest credential in the tree** (D13). An OpenRouter *management* key — not an inference key — read by one caller only: the hourly balance poll, which spends it on `GET /api/v1/credits` and only when `GET /api/v1/key` reported no cap (`src/hbd/runtime/vendor_balance_probes.py`). It buys the account's prepaid pool, which is what lets the panel draw remaining as a **fraction**; without it the row stays `is_unbounded` and the pill's ring is fully dashed. It belongs to the **primary** account (`HBD_LLM_API_KEY`'s) — the fallback row is never read with it, because the variable cannot say which account it is for. It can create and revoke API keys, so it is in `VENDOR_SECRET_FIELDS` (a prod admin host is refused it) and **not** in `REQUIRED_VENDOR_SECRET_FIELDS` (every process starts without it). Adds no egress host: `/credits` is on `HBD_LLM_BASE_URL`. |
| `HBD_ELEVENLABS_BASE_URL`, `HBD_LLM_BASE_URL` | `Settings` | `https://api.elevenlabs.io`, `https://openrouter.ai/api/v1` | The two vendor hosts the bot and worker reach on the primary path, plus `api.telegram.org` (`src/hbd/runtime/providers.py:133-150`). The admin host needs none of them. **Not the whole egress list when failover is configured — see the row below.** |
| `HBD_LLM_FALLBACK_BASE_URL` | `Settings` | `""` (`src/hbd/config.py:251-252`) | Empty means "the adapter's own default host", which for the shipped `llm_fallback_provider="openai"` (`:247-249`) is `https://api.openai.com` (`src/hbd/providers/llm/openai_compat.py:69`) — a **third** vendor host, reached as soon as `HBD_LLM_FALLBACK_API_KEY` is non-empty (`src/hbd/providers/llm/factory.py:158-168`, built at `src/hbd/runtime/providers.py:151`). Egress rules written from the row above alone will silently break the documented failover. Set this explicitly if the fallback must go somewhere else. |

### Queue and worker

| Variable | Class | Default | Consequence |
| --- | --- | --- | --- |
| `HBD_WORKER_CONCURRENCY` | `Settings` | `15` (`src/hbd/config.py:632`) | `max_jobs` on the ARQ worker (`src/hbd/runtime/jobs.py:772`). It does **not** need to respect the vendor ceiling in the row above, and must not be lowered to it: simultaneous renders are already bounded independently by a per-process `asyncio.Semaphore(music_max_concurrency)` (`src/hbd/runtime/container.py:332`). Setting this to 2 would throttle every job that is not rendering music — settlement, delivery, balance polls — for nothing. |
| `HBD_QUEUE_JOB_TIMEOUT_S` | `Settings` | `900.0` (`:633`) | Also feeds the derived settlement grace — see the next row. |
| `HBD_QUEUE_MAX_TRIES` | `Settings` | `5` (`:638-648`) | Same. |
| `HBD_SETTLEMENT_GRACE_S` | `Settings` | `None` → **derived** (`:548-556`) | The only field whose unset value is a derivation rather than a constant: `queue_job_timeout_s × queue_max_tries` plus backoff deferrals, 4550s under shipped defaults. `.env.example:317` ships it commented out, and that is correct — a fixed grace shorter than the queue ladder makes the sweep refund orders that are still rendering. |

### Broadcasts (the newsletter pipeline)

Three knobs and one credential note. All four matter on the **worker**; the panel composes a
campaign and enqueues it, and holds none of these.

| Variable | Class | Default | Consequence |
| --- | --- | --- | --- |
| `HBD_BROADCAST_SEND_RATE_PER_S` | `Settings` | `12` (capped at 30) | Outbound messages per second **across every worker replica**, enforced through a Redis counter (`src/hbd/runtime/pacer.py`). Telegram limits at ~30/s per BOT TOKEN, and exceeding it earns a flood wait on the token — which stops the paid orders, not merely the campaign. Reminders will share this bucket by name; do not give a second feature its own key. |
| `HBD_BROADCAST_CHUNK_TIMEOUT_S` | `Settings` | `120.0` | How long one send chunk (≤200 messages) may hold a worker slot. Deliberately not `HBD_QUEUE_JOB_TIMEOUT_S`: 900s is sized for a music render, and a 50 000-recipient campaign is 250 chunks. **Not a knob to shorten** — the timeout is a cancellation, and a cancelled chunk leaves its claimed rows unresolved (they become `unknown`, counted as neither sent nor failed). |
| `HBD_BROADCAST_SENDING_LEASE_S` | `Settings` | `300.0` | How long a claimed recipient may sit in `sending` before the five-minutely sweep retires it to `unknown`. **Must exceed the chunk timeout**, or a merely slow chunk is written off underneath itself. It is also what "this campaign has stalled" means to the sweep. |
| `HBD_ADMIN_AUDIT_HMAC_KEY` | *not a `Settings` field* | unset | Normally the **panel's** variable (see "Required for the admin API"). The worker reads it, and only for one thing: the `broadcast.sent` OUTCOME audit row it writes when a campaign finishes, which has to be chained like every other audit row. **Unset is supported** — the campaign row and its six counters are the operational record either way — and the worker logs at ERROR that the outcome row was skipped. A deployment that wants the accountability copy sets the *same value* here as the panel holds; that widens where the chain key lives, which is why it is opt-in rather than required. It is deliberately not a field on `Settings`: every secret-shaped field there is a credential the ADMIN host is refused at boot, and this is the one secret the admin host cannot run without. |

### Entitlements and price

| Variable | Class | Default | Consequence |
| --- | --- | --- | --- |
| `HBD_CREDITS_ENFORCED` | `Settings` | `false` (`src/hbd/config.py:494-497`) | Ships the meter dark. With the checkout wired, the bot logs the WARNING "the checkout is wired but the credit meter is dark" at boot and **never refuses** (`src/hbd/main.py:177-189`): the customer is shown a price and charged, and the worker covers the shortfall with an `UNENFORCED_RENDER` grant, so the render happens whether or not the payment did. `true` is the intended production setting once a price is on screen. |
| `HBD_FREE_ALLOWANCE_CREDITS` | `Settings` | `0` (`src/hbd/config.py:527-534`) | 0 is the product decision, not a conservative default. Must be mirrored — see below. |
| `HBD_GREETINGS_PER_KIT` | `Settings` | `0` (`src/hbd/config.py:406-411`) | 0 sells a song-only kit and buys no speech at all. |

### Host tooling

| Variable | Class | Default | Consequence |
| --- | --- | --- | --- |
| `HBD_FFMPEG_BINARY` / `HBD_FFPROBE_BINARY` | `Settings` | `ffmpeg` / `ffprobe` (`src/hbd/config.py:414-415`) | "On PATH" is the *default*, not the requirement — a host with ffmpeg somewhere unusual needs a config line, and the refusal message names the variable (`src/hbd/audio/startup.py:35-38`). `verify_host` refuses on either binary missing and on an ffmpeg build without a `libopus` encoder (`src/hbd/runtime/startup.py:23-25`, `src/hbd/audio/startup.py:93-103`). It is called by the bot, the worker and the demo only — **never by the admin API**, which needs no ffmpeg at all. |
| `HBD_I18N_STRICT` | none — read directly | **not strict** in any production process (`src/hbd/i18n/translator.py:51-56`) | Undocumented in both example files. `is_strict_by_default()` returns the parsed value of this variable when it is set, and otherwise returns whether `PYTEST_CURRENT_TEST` is in the environment — so unset means strict under pytest and **lenient everywhere else**, despite the function's own docstring at `:52` saying the opposite. Strictness is consumed only at render time (`:166-178`: raise on a missing key or parameter if strict, else log at ERROR and degrade to the key name). Leave it unset in production: on this side a copy bug should not take down a delivery. |

Catalogue *loading* is separate from strictness and is not configurable: `verify_host` calls
`get_translator()` (`src/hbd/runtime/startup.py:28`), which force-loads every catalogue
(`src/hbd/i18n/translator.py:184`) whatever `HBD_I18N_STRICT` says. A malformed locale file is
therefore a boot failure on the bot and the worker in every environment — but a *missing key*
in a well-formed file is not, and reaches a customer as the key name.

### Admin: proxy, probes, volumes

| Variable | Class | Default | Consequence |
| --- | --- | --- | --- |
| `HBD_ADMIN_TRUSTED_PROXY_HOPS` | `AdminSettings` | `0` (`src/hbd/admin/settings.py:216`) | `X-Forwarded-For` is ignored entirely unless hops > 0 **and** the peer is inside a configured CIDR (`src/hbd/admin/security/clientip.py:142`). Behind a reverse proxy at the defaults, every request resolves to the proxy's own address — which collapses the strict per-`(username, ip)` login counter into one global bucket per username and writes a constant into `admin_audit_log.ip`. Set it to the exact number of proxies you control. |
| `HBD_ADMIN_TRUSTED_PROXY_CIDRS` | `AdminSettings` | `()` (`:217`) | The addresses those proxies connect from. A typo fails the boot naming the variable (`:486-499`). |
| `HBD_ADMIN_PROBE_TOKEN` | `AdminSettings` | `""` (`:426-428`) | Empty authorises nobody, and there is deliberately no default token to forget to change — but until it is set, `/readyz` answers a constant `{"status":"ok"}` to every monitor **even with the database and Redis both down** (`src/hbd/admin/routers/health.py:126-138`). Note the field has no `min_length`, unlike the HMAC key. |
| `HBD_ADMIN_DATA_ROOT` | `AdminSettings` | `var` — **relative** (`:423`) | The panel reads `<root>/archive` through the `Storage` seam. The bot and worker have **no equivalent variable**: their root is `Path.cwd()/"var"` (`src/hbd/runtime/container.py:286`) and `hbd.main.run` never receives an override (`src/hbd/main.py:222`). The two agree only if the processes share a working directory. If they disagree, every media reveal in the panel returns "no such object" while the database row says the file exists — with no configuration error anywhere. |
| `HBD_ADMIN_AUDIT_DSN` | `AdminSettings` | `""` (`:235`) | Empty is a supported deployment and reports `hmac-only`. Note the docstring at `:231-234` names migration **0006**; the REVOKE is in **0007** (`migrations/versions/20260830_1000_0007_add_admin_audit_log.py:369`), which is what `.env.example:39`, README.md:162 and `migrations/env.py:8` correctly say. |
| `HBD_ADMIN_ARGON2_MEMORY_KIB` | `AdminSettings` | `65536` (`:212`) | Load-bearing rather than a tunable: the password floor is length-only, 8 characters (`src/hbd/admin/schemas/common.py:31-38`), so argon2 cost and the login throttle are the whole defence. Raise until a verify takes 250–500 ms on the host. |

> **`HBD_ADMIN_HOST` and `HBD_ADMIN_PORT` bind nothing.** They are declared
> (`src/hbd/admin/settings.py:188-189`) and their only readers in the tree are the display
> fields of `GET /api/config` (`src/hbd/admin/schemas/config_view.py:108-109, :202-203`). The
> actual bind comes from the uvicorn command line — `Makefile:75` passes
> `--host 127.0.0.1 --port 8080`. Setting `HBD_ADMIN_PORT=9000` changes what the config screen
> *claims* and not what the process listens on, and the comment beside the field ("Binding
> 0.0.0.0 publishes a password login to the internet") reads as if the field enforced
> something it does not. Loopback binding is a property of whatever command starts the
> process; the panel's own config screen is not evidence about it.

> **`HBD_ADMIN_CONFIG_ENABLED` is inert today.** It defaults to `true`
> (`src/hbd/admin/settings.py:185`) and `.env.admin.example:57-60` presents it as protecting
> "the riskiest surface in the panel" from a stolen session. No endpoint reads it: the only
> other references are its `ConfigView` projection and prose in
> `src/hbd/admin/routers/config.py:10`. `Permission.CONFIG_WRITE` exists and is attached to no
> route, and `src/hbd/admin/routers/` contains no config-write endpoint. Do not count it as an
> armed control.

---

## Owned by both classes — five variables, two files

`HBD_ENVIRONMENT`, `HBD_LOG_LEVEL`, `HBD_IS_DEBUG`, `HBD_DATABASE_URL` and `HBD_REDIS_URL`
are fields on **both** models (`src/hbd/config.py:170-173, :187-188`;
`src/hbd/admin/settings.py:169-171, :174-175`) and must be written into both files. Only the
last two are meant to match. The first three are independently settable and independently
enforced, and **nothing cross-checks them**: `HBD_ENVIRONMENT=prod` in the bot's file with
`dev` left in the admin's is a completely legal, silent state in which the bot refuses fake
providers while the panel permits DEBUG logging, permits the loopback origin, and downgrades
the vendor-credential refusal to a warning nobody is watching.

Three further values are *mirrored* from the worker into `AdminSettings` because the panel
deliberately cannot read the bot's file — that separation is the vendor-key boundary
(`src/hbd/admin/settings.py:258-262`):

| Worker variable | Admin mirror | If they drift |
| --- | --- | --- |
| `HBD_NAME_MATCH_MIN_SIMILARITY` | `HBD_ADMIN_NAME_MATCH_MIN_SIMILARITY` | The threshold marker lands in the wrong place on the similarity histogram. Blank means "not published" and draws no marker, which is honest. |
| `HBD_SETTLEMENT_GRACE_S` (or its derivation) | `HBD_ADMIN_SETTLEMENT_GRACE_S` | `inFlightRenderCount` — the number that explains a refusal to a customer on the phone — diverges from the gate that produced the refusal. `AdminSettings` holds no queue fields, so it cannot re-derive; this must be set by hand whenever the queue ladder moves. |
| `HBD_FREE_ALLOWANCE_CREDITS` | `HBD_ADMIN_FREE_ALLOWANCE_CREDITS` | A wrong `creditsProjected`. This mirror exists *because* the defect shipped: defaulting the allowance added 3 credits to every account in the fleet, forever (`src/hbd/admin/settings.py:302-312`). |

> **`extra="ignore"` makes every one of these drifts silent.** Writing
> `HBD_ADMIN_FREE_ALLOWANCE_CREDITS` into `.env` discards it; writing
> `HBD_FREE_ALLOWANCE_CREDITS` into `.env.admin` discards it; a typo'd prefix in either file
> is a no-op with no error. And of the three mirrors, the allowance is the one **not** yet
> published on `GET /api/config` — its own docstring admits it
> (`src/hbd/admin/settings.py:322-326`): "the only way to spot drift is to compare the two
> deployments' environments by hand". The other two are on that screen
> (`src/hbd/admin/schemas/config_view.py:140, :147`), which is the intended remedy.

---

## Two defects in `.env.admin.example` to fix before copying it

Both were verified against this working tree, not inferred.

**1. Seven variables parse as their own trailing comment.** python-dotenv strips an inline
`#` comment only when the value before it is non-empty; every one of these lines is blank
before the `#`, so the comment *becomes* the value:

```
HBD_ADMIN_TRUSTED_PROXY_CIDRS        .env.admin.example:114
HBD_ADMIN_NAME_MATCH_MIN_SIMILARITY  :155
HBD_ADMIN_SETTLEMENT_GRACE_S         :171
HBD_ADMIN_UZS_PER_USD                :216
HBD_ADMIN_UZS_PER_USD_AS_OF          :217
HBD_ADMIN_SINGLE_SONG_PRICE_MINOR    :235
HBD_ADMIN_KIT_CURRENCY               :236
```

Every one is a variable whose own comment says to leave it blank. The
`_blank_mirror_means_unpublished` validator (`src/hbd/admin/settings.py:433-465`) exists
solely to make that work and states at `:449` that "the example file ships the variables
blank, so this is the path an untouched deployment actually takes" — it is not that path,
because the values are never blank as parsed, so the validator never fires.

**2. `HBD_ADMIN_COOKIE_SECURE=` is genuinely blank and is a separate failure.** The field is
`bool | None` (`src/hbd/admin/settings.py:197`) and pydantic cannot read an empty string as
either; it is on neither blank-tolerating validator's list. The example file's own line 91
instructs "Leave empty".

Copying the file verbatim therefore produces nine validation errors, before anything
host-specific is even reached. To see them the way an operator would — as the tidy message
rather than as a traceback — catch the `ConfigError`:

```bash
HBD_ADMIN_ENV_FILE=.env.admin.example python -c "
from hbd.admin.settings import build_admin_settings
from hbd.errors import HbdError
try:
    build_admin_settings()
except HbdError as exc:
    print(exc.operator_message)
"
```

That prints:

```
The admin panel's configuration is invalid or incomplete. Fix these environment variables (see .env.admin.example):
  HBD_ADMIN_COOKIE_SECURE: Input should be a valid boolean, unable to interpret input
  HBD_ADMIN_TRUSTED_PROXY_CIDRS: Value error, HBD_ADMIN_TRUSTED_PROXY_CIDRS contains an unparsable entry: '# comma-separated'
  HBD_ADMIN_AUDIT_HMAC_KEY: Value should have at least 32 items after validation, not 0
  HBD_ADMIN_NAME_MATCH_MIN_SIMILARITY: Input should be a valid number, unable to parse string as a number
  HBD_ADMIN_SETTLEMENT_GRACE_S: Input should be a valid integer, unable to parse string as an integer
  HBD_ADMIN_UZS_PER_USD: Input should be a valid number, unable to parse string as a number
  HBD_ADMIN_UZS_PER_USD_AS_OF: Input should be a valid date or datetime, invalid character in year
  HBD_ADMIN_SINGLE_SONG_PRICE_MINOR: Input should be a valid integer, unable to parse string as an integer
  HBD_ADMIN_KIT_CURRENCY: String should have at most 3 characters
```

Without the `try`/`except`, the same call is a 54-line traceback whose *first* exception is a
raw `pydantic_core._pydantic_core.ValidationError: 9 validation errors for AdminSettings`; the
message above is only the last line of it. That is what a bare one-liner shows, and it is why
the boot paths catch (`src/hbd/admin/settings.py:666-680`).

Only `HBD_ADMIN_AUDIT_HMAC_KEY` is a real "you have not filled this in yet". The other eight
are the file's own formatting. The fix in the file is to move each inline comment onto its
own line above the variable; the fix in a copy you have already made is to delete the eight
offending lines' values (and delete the `HBD_ADMIN_COOKIE_SECURE` line entirely — `None` is
the default and it derives to `True`, `src/hbd/admin/settings.py:602-618`).

`.env.example` has no equivalent *formatting* problem: its inline-commented lines all have
non-empty values, so nothing there parses as its own comment. It does not boot as shipped,
though, and that is by design rather than a defect — it ships the three vendor secrets blank,
so `HBD_ENV_FILE=.env.example load_settings()` fails with exactly three errors:

```
  HBD_TELEGRAM_BOT_TOKEN: String should have at least 1 character
  HBD_ELEVENLABS_API_KEY: String should have at least 1 character
  HBD_LLM_API_KEY: String should have at least 1 character
```

(`src/hbd/config.py:697-699`, `_VendorBoundSettings`.) Those are the "you have not filled this
in yet" errors, not formatting ones — do not read them as the same class of problem as the
nine above.

### Three stale section headers in `.env.example`

`.env.example:384-388` still carries a "Retention, in days" header with no variables under
it and the claim "The purge job reads these" — which README.md:467-471 already identified as
false: "Retention is a policy object, not configuration… they were removed." The periods are
constants (`src/hbd/db/retention.py:61-76`). The same shape appears at `.env.example:157-162`
(object storage) and `:395-398` (free tier). Nothing under those headers is configurable;
ignore them.

---

## What is not covered here

Six `HBD_*` variables outside the two settings classes are read by real code: the four
described above (`HBD_ENV_FILE`, `HBD_ADMIN_ENV_FILE`, `HBD_DB_MIGRATION_URL`,
`HBD_DB_APP_ROLE`), plus `HBD_ADMIN_AUDIT_DSN` in the migration bodies and `HBD_I18N_STRICT`.
`HBD_ENV_FILE` and `HBD_ADMIN_ENV_FILE` are correctly explained in prose rather than as
lines, because writing them into the file they select is a no-op — `.env.example:5-11` and
`.env.admin.example:5-11` both say so. **`HBD_DB_APP_ROLE` is the real gap**: it names the
role the audit REVOKE is taken from and appears in neither example file, so an operator has
no way to discover it exists.

Everything else — every one of the 88 `Settings` fields and all 35 `AdminSettings` fields —
is present in its example file with the reasoning attached. That coverage was checked by
diffing the assignments in each file against the two classes' field-name sets: nothing is
missing from either — every `Settings` field appears in `.env.example`, every `AdminSettings`
field in `.env.admin.example`. The two files are **not** disjoint, and must not be: the five
shared-ownership variables above (`HBD_DATABASE_URL`, `HBD_ENVIRONMENT`, `HBD_IS_DEBUG`,
`HBD_LOG_LEVEL`, `HBD_REDIS_URL`) are fields on both classes and appear in both files, which
is the intended state. The only assignment in either file that is not a field of its own class
is `HBD_DB_MIGRATION_URL` in `.env.example`, explained above.

## Host assumptions

Everything above about the *code* was read out of this working tree. Several passages,
however, presuppose facts about the target host that nobody who wrote this page could check.
They are listed here rather than left implicit, and each is a **proposal or an open question**,
not a record:

- **A source checkout with alembic available.** The migrate command shape assumes
  `migrations/alembic.ini` is present and alembic is importable. `migrations/` is not in the
  wheel, so a wheel-only install cannot run it as written.
- **Two Postgres roles exist, and their names.** Nothing in this repository creates production
  roles; `docker/initdb/10-two-roles.sql` is a local-dev artefact that says so itself. The
  names used there (`hbd`, `hbd_app`) are dev names, not established production ones.
- **A supervisor.** Whether anything restarts the bot, the worker or the admin API after a
  failed boot is unknown here.
- **A log pipeline.** The two boot strings are real; whether their stdout is collected, where,
  and for how long, is not established by this repository.
- **A database backup exists** to keep the audit HMAC key separate from. The obligation stands
  either way, but "separately from the database dump" presumes a dump.
- **A reachable panel or psql session** for the `chainProtection` / `\dp admin_audit_log`
  confirmation, and shell access to the host for benchmarking argon2 to the 250–500 ms target.

Beyond these: which files exist at which paths, what terminates TLS, and how the three
processes are actually started are not in this repository. `deploy/first-install-proposal.md` and
`deploy/systemd/*.service` propose one answer; they were authored without access to the
target host and are a proposal, not a record.
