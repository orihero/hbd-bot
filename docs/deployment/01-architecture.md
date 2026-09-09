# Deployed architecture

> **Everything below is derived from this repository, and nothing in it was observed on the
> production VPS.** Nobody who wrote this document has access to `aizu`. Where a path, a unit
> name or a host fact appears, it is either a repo file quoted as such or a *proposal* from
> `deploy/`, which was authored without host access on the same day and is a plan, not a
> record. Statements of the form "the code does X" are checkable against the file:line
> citations; statements of the form "the host does Y" are not made here at all.

> **There is now a FOURTH long-running process, and this document predates it.** The Payme
> Merchant API endpoint (`make payme`, `deploy/systemd/hbd-payme.service`) terminates an
> inbound rail on `127.0.0.1:8091` behind a TLS terminator. It ships **off** —
> `HBD_PAYME_ENABLED` defaults to false and its lifespan refuses to boot while it is — so
> everything below remains an accurate description of a default deployment. It is documented
> on its own page, [08-payme.md](08-payme.md), and deliberately not folded in here: it holds a
> different secret, reads a different dotenv, and is the only process in the fleet with an
> inbound socket from the public internet. Read the two together and treat every "three"
> below as "the three that were here first".

## Three processes, and the commands you run by hand

The product is three long-running processes and three things you run by hand: two on every
deploy, and one exactly once per installation. All three processes are `python -m`
invocations: `pyproject.toml` has no `[project.scripts]` table, so
there is no `hbd` or `hbd-worker` binary on `PATH` after an install, and any process manager
must spell out an interpreter path plus `-m`.

```bash
# 1. the bot — aiogram long polling
.venv/bin/python -m hbd.main                                  # Makefile:68-69

# 2. the ARQ worker — every render, every cron
.venv/bin/python -m arq hbd.worker.WorkerSettings             # Makefile:71-72

# 3. the admin API — FastAPI, serving its own React bundle
.venv/bin/python -m uvicorn hbd.admin.app:app --host 127.0.0.1 --port 8080   # Makefile:74-75
```

```bash
# schema, run separately, from a checkout (migrations/ is not in the wheel)
.venv/bin/python -m alembic -c migrations/alembic.ini upgrade head   # Makefile:146-147

# the console bundle, required on every deploy — see "The console is a build artefact"
cd admin-ui && npm install    # Makefile:83-84  (`ui-install`)
cd admin-ui && npm run build  # Makefile:92-93  (`ui-build`)

# ONCE per installation: the first operator account. There is no signup route.
.venv/bin/python -m hbd.admin.bootstrap --username owner      # Makefile:77-81
```

> **Without the third command the panel has no account to log in with.**
> `src/hbd/admin/bootstrap.py:1-4`: "There is no signup route, so this CLI is the only thing
> that creates an operator account." A deploy that runs the migrations and builds the bundle
> produces an admin API that boots, answers `/healthz`, serves a login page and refuses every
> credential, because none exists. The password is never an argument — the CLI prompts, or
> takes `--password-file` (`Makefile:78-81`).

`make dev`, `make worker` and `make admin` run exactly those three strings, and each module's
own docstring repeats it (`src/hbd/main.py:1`, `src/hbd/worker.py:1`,
`src/hbd/admin/app.py:28-30`). Nothing in package metadata pins them, so renaming
`hbd.worker.WorkerSettings` breaks a deployment silently and no test fails.

The targets are not *quite* bare wrappers: every one of them — `dev`, `worker`, `admin`,
`admin-bootstrap` and `migrate` — is prefixed by `$(ENV_FILES)` (`Makefile:69`, `:72`, `:75`,
`:81`, `:147`), which is empty when `ENV=dev` and otherwise expands to
`HBD_ENV_FILE=.env.$(ENV) HBD_ADMIN_ENV_FILE=.env.admin.$(ENV)` (`Makefile:41-46`).
`HBD_ENV_FILE` is the variable that decides **which dotenv file every one of these processes
reads**; it defaults to `.env` and is read from the process environment only, because a
dotenv file cannot name the dotenv file about to be read (`src/hbd/config.py:69-78`). The
code treats this as a sharp hazard rather than a convenience: `verify_host` logs the
environment and the env file at INFO precisely because "`HBD_ENV_FILE` makes it possible to
boot a PRODUCTION configuration from a development checkout"
(`src/hbd/runtime/startup.py:31-34`), and the admin's `admin.boot.ok` line carries the same
field for the same reason (`src/hbd/admin/app.py:327-329`). A process manager that sets
`HBD_ENV_FILE` is therefore setting the whole configuration, and nothing in the command line
above shows which file that is.

> **The bind address is on the command line, not in configuration.** `HBD_ADMIN_HOST` and
> `HBD_ADMIN_PORT` exist (`src/hbd/admin/settings.py:187-189`) and are read by nothing that
> opens a socket — their only consumers are the two display fields on `GET /api/config`
> (`src/hbd/admin/schemas/config_view.py:108-109`). Changing `HBD_ADMIN_PORT` changes what
> the panel *reports* and not what the process listens on. The `--host 127.0.0.1` in the
> uvicorn invocation is the whole of the loopback control, and `create_app()` is just an
> ASGI object — it cannot know or refuse the address it is served on.

## What talks to what

```
                        ┌──────────────────────┐
        Telegram  ◄────►│   bot                │   python -m hbd.main
   api.telegram.org     │   aiogram polling    │
                        └──┬────────┬──────────┘
                           │        │  enqueue (ArqOrderSubmitter)
                    FSM +  │        │  main.py:94
                  isolation│        ▼
                  bot/app  │   ┌─────────────────┐
                    :83,:97│   │  Redis          │  queue, job results, FSM, rate limits,
                           └──►│  one logical db │  60 s session MIRROR (not the session)
                               └───┬─────────────┘
                                   │ ARQ pool + FSM  (jobs.py:771, worker.py:57)
                                   ▼
                        ┌──────────────────────┐        ┌──────────────────────┐
                        │   worker             │───────►│  ElevenLabs          │
                        │   arq WorkerSettings │  music  │  api.elevenlabs.io   │
                        │   3 crons :17 :43 0:07│  TTS   └──────────────────────┘
                        └──┬─────────┬─────────┘  STT
                           │         │            ┌──────────────────────┐
                           │         └───────────►│  LLM base URL        │
                           │                      │  openrouter default  │
                           │                      ├──────────────────────┤
                           │            (if set)  │  LLM FALLBACK host   │
                           │                      │  HBD_LLM_FALLBACK_   │
                           │                      │  BASE_URL — 4th dest │
                           │                      └──────────────────────┘
                           │  as hbd_app
                           ▼
                        ┌──────────────────────┐
                        │  PostgreSQL          │◄──── alembic, as hbd (owner)
                        └──────────▲───────────┘
                                   │  read-mostly, as whatever role its DSN names
                        ┌──────────┴───────────┐   (.env.admin.example ships the OWNER —
   browser ──TLS──?──►  │   admin API          │    see Decision 2)
   (terminator unknown) │   uvicorn 127.0.0.1  │   holds NO vendor credential
                        └──────────┬───────────┘   serves its own SPA bundle
                                   │  reads (the code's store is read-write;
                                   │   ":ro" is a host mount, unverified)
                                   ▼
                        var/archive   ◄──── written by bot + worker
                        (one filesystem root, two key namespaces)
```

Edge by edge, with the code that makes each one:

**Telegram.** Only the bot polls; the worker holds a `Bot` of its own that never polls and
only sends, because the progress edits and the finished kit have to reach the customer from
the process that produced them (`src/hbd/worker.py:7-9`, `:55`). On every start the bot calls
`delete_webhook(drop_pending_updates=True)` (`src/hbd/bot/app.py:216`), so every update that
arrived during a restart window is discarded and never resent. That is a deliberate,
documented deploy-window data loss, and it is why the worker also records bot-blocks — the
churn signal is the one thing given a second source (`src/hbd/main.py:156-162`).

**Redis.** A hard dependency of both the bot and the worker in production, not just the
worker. The bot opens it twice — an ARQ pool for the queue (`src/hbd/main.py:94`) and
`RedisStorage` plus `RedisEventIsolation` for the wizard FSM (`src/hbd/bot/app.py:83`, `:97`)
— and the worker opens it again for the same two purposes (`src/hbd/runtime/jobs.py:771`,
`src/hbd/worker.py:57`). In production the bot takes the `create_pool` branch with no
fallback, because the in-process submitter refuses to construct itself there
(`src/hbd/runtime/submitter.py:98-105`). The FSM key namespace is shared: the worker un-parks
the wizard session the bot parked, which only works while both point at the same URL and the
same logical database. `HBD_REDIS_URL` defaults to `redis://localhost:6379/0`
(`src/hbd/config.py:188`), so a process that never had it set connects to a local Redis and
the queue looks *empty* rather than *broken*.

The admin panel's use of Redis is narrower than it looks, and the difference matters during
an incident. **Admin sessions are not in Redis.** They are rows in the Postgres table
`admin_sessions`, whose `token_sha256` is "the ONLY copy of the session token"
(`migrations/versions/20260829_1200_0005_add_admin_users_and_sessions.py:1-14`, `:41`). What
Redis holds is a 60-second mirror of a session snapshot — the module's first line is "Admin
sessions: the database is the truth, Redis is a mirror that cannot outlive it"
(`src/hbd/admin/sessions.py:1`) — and the operator row and the revocation column are re-read
from Postgres on **every** request regardless of whether the mirror is warm
(`src/hbd/admin/sessions.py:9-25`). So flushing this Redis does not log anybody out (the next
request re-reads the row), losing Redis does not lose sessions, and "kick everyone out" is a
write to `admin_sessions.revoked_at`, not a `FLUSHDB`. The only Redis-backed store the admin
container builds is `rate_limits` (`src/hbd/admin/container.py:151`).

**PostgreSQL.** All three processes. Pool sizing assumes exactly three of them: the bot and
worker take 10 + 20 overflow each (`src/hbd/db/engine.py:40-41`) and the admin API
deliberately asks for a smaller share, 5 + 5 (`src/hbd/admin/container.py:53-54`), because
"bot + worker + admin API at the defaults is `3 × 30 = 90` connections against a stock
`max_connections` of 100" (`src/hbd/db/engine.py:64-67`). The repo's own margin is ten
connections; whether the production server has that ceiling, and what else shares it, is a
host question.

**Vendors.** Exactly two *pooled* HTTP clients, both built only in the live provider set: one
to ElevenLabs, which carries music, TTS and STT, and one shared client object used for both
the primary and the fallback LLM (`src/hbd/runtime/providers.py:133-155`). Music is
ElevenLabs, not a separate service. The default hosts are `https://api.elevenlabs.io`
(`src/hbd/config.py:192`) and `https://openrouter.ai/api/v1` (`src/hbd/config.py:235`).

A shared client is not a shared destination, and an allowlist written from the client count
alone will be wrong twice:

- **The fallback LLM can have a host of its own.** `HBD_LLM_FALLBACK_BASE_URL`
  (`llm_fallback_base_url`, `src/hbd/config.py:250-252`) defaults to empty, and empty means
  "the adapter's usual home"; set, it becomes the fallback adapter's `base_url`
  (`src/hbd/providers/llm/factory.py:168`, `base_url=settings.llm_fallback_base_url or
  default_host`). If it is set on the deployed host, there is a fourth destination, and an
  allowlist built from the primary hosts silently kills the LLM failover path.
- **The hourly balance poll does not use those clients at all.** It builds its own —
  `async with httpx.AsyncClient() as client` (`src/hbd/runtime/vendor_balance_job.py:330`),
  deliberately, "ONE CLIENT, OWNED BY THE RUN" (`:50-54`) — and resolves the fallback host
  itself with `_fallback_base_url` (`:175-186`), mirroring the factory's rule.

So the bot and worker need at least three outbound destinations — Telegram, ElevenLabs and
the LLM base URL — plus a fourth wherever `HBD_LLM_FALLBACK_BASE_URL` is set, and **the admin
API needs none of them**. Which of those a firewall must allow is settled by the deployed
`.env`, not by this repository.

**The filesystem.** One object-store root, shared. The bot and worker derive it as
`Path.cwd()/"var"` with no environment override at all (`src/hbd/runtime/container.py:286`)
and create `var/workspace` and `var/archive` under it at every boot (`:287-290`). The admin
process reaches `<admin_data_root>/archive` through the same `Storage` protocol
(`src/hbd/admin/container.py:155`), where `admin_data_root` defaults to the *relative* path
`var` (`src/hbd/admin/settings.py:423`). One instance is shared on the writing side on
purpose: the avatar the bot writes and the object the panel streams must be the same key
under the same root, or "the row says an avatar was stored, and the bytes are on another
disk" (`src/hbd/runtime/container.py:301-311`).

> **The one path the processes must agree on is configurable on exactly one side.** The bot
> and worker have no data-root setting — `hbd.main.run` accepts `data_root` but `main()`
> never passes it (`src/hbd/main.py:98`, `:222`) — so relocating their root means changing
> the process working directory and nothing else. The admin's value is a relative default.
> If the two resolve differently, every media reveal in the panel returns "no such object"
> while the database row insists the file exists, and no configuration error is raised
> anywhere. Whether they agree on the live host is a deployment fact, not a code guarantee.

**Nothing else.** The admin process connects to Postgres and Redis and to nothing else — its
container holds "engine, sessions, Redis, and nothing else" (`src/hbd/admin/container.py:1`)
— and `Redis.from_url` does not connect at construction, so `/healthz` can answer without
touching either (`src/hbd/admin/container.py:117-128`).

## Only the worker runs the clocks

Three ARQ crons, on deliberately staggered off-the-hour minutes: the retention sweep hourly
at **:17** (`src/hbd/runtime/retention_job.py:73`), the vendor-balance poll hourly at **:43**
(`src/hbd/runtime/vendor_balance_job.py:118`), and the activity snapshot daily at **00:07
UTC** (`src/hbd/runtime/activity_job.py:74-75`), all wired at
`src/hbd/runtime/jobs.py:705-769` with `run_at_startup=False`.

No other process covers them. A worker that is down stops the retention sweep — a stated
legal obligation — stops re-pinning the audit chain's HEAD anchor, and puts permanent,
unbackfilled gaps in the activity series. None of that raises anything. And because
`run_at_startup=False`, a cold-started worker runs no cron until the next window: up to an
hour of stale balances, up to a day before the first snapshot.

Worker concurrency is 15 jobs (`src/hbd/runtime/jobs.py:772`, default at
`src/hbd/config.py:632-640`), but the vendor ceiling is a *per-process*
`asyncio.Semaphore` (`src/hbd/runtime/container.py:332-333`), defaulting to 2 simultaneous
renders — the number the vendor's plan allows. Two worker replicas would make four
simultaneous renders against a vendor limit of two. The guard is written as if one process
exists.

## Two of the three processes will not start without ffmpeg

`verify_host()` refuses to boot on exactly three things: `ffmpeg` on `PATH`, `ffprobe` on
`PATH`, and an ffmpeg build carrying the `libopus` encoder
(`src/hbd/runtime/startup.py:23-25`, `src/hbd/audio/startup.py:93-103`). It also force-loads
the i18n catalogues, so a malformed locale file is a boot failure rather than a broken
message in front of a customer (`src/hbd/runtime/startup.py:26-28`). It is called by the bot
(`src/hbd/main.py:100`), the worker (`src/hbd/worker.py:45`) and the demo — and **never by
the admin API**, which holds no post-processor at all. An admin-only host therefore has a
materially smaller dependency surface.

What `verify_host` does *not* check is Postgres, Redis, Telegram or any vendor. A host with
no database passes it cleanly and fails later.

> **Bot and worker fail differently on the same bad environment.** The bot builds settings
> inside a `try/except HbdError` and prints one line, `hbd: <operator message>`, then exits 2
> (`src/hbd/main.py:213-218`). The worker builds them at *module import* time
> (`src/hbd/worker.py:40`), because that is how ARQ's CLI finds `WorkerSettings` — so the
> same misconfiguration produces an uncaught traceback from the arq CLI, once per restart
> attempt, for as long as a supervisor keeps trying.

## The console is a build artefact the API serves itself

There is no separate web server for the admin console. `vite build` writes into the Python
package tree at `src/hbd/admin/static/` (`admin-ui/vite.config.ts:106-107`, with
`emptyOutDir: true`), the API mounts `static/assets` under `/assets` and registers a catch-all
that renders the SPA shell for every other browser URL (`src/hbd/admin/app.py:296-303`).

That directory is **gitignored** (`src/hbd/admin/app.py:124-128`). A fresh checkout has no
console, and the failure is quiet by design: the catch-all 404s when the shell is missing
rather than taking the process down (`src/hbd/admin/app.py:238-239`), and the assets mount is
constructed with `check_dir=False` so the app still imports (`:280-282`, `:296-300`).

> **An unbuilt console is indistinguishable from a healthy API at the process level.**
> `/healthz` answers 200, `/api` answers JSON, and every browser URL answers 404. The only
> signal is the missing bundle. `npm run build` is therefore not an optimisation step in a
> deploy — it is the step that makes the panel exist.

The shell is not served as a static file. It carries a per-response CSP style nonce, so it is
read, substituted and returned as an `HTMLResponse` on every request
(`src/hbd/admin/app.py:243-249`), which is also why it is deliberately outside the immutable
cache prefix. A bundle built before the `__HBD_CSP_NONCE__` placeholder existed degrades
silently — one WARNING per response, `admin.spa.nonce_placeholder_missing`, and a panel that
looks correct except that modal scroll-lock stops working
(`src/hbd/admin/shell.py:65-85`).

Packaging note, because the two mechanisms are easy to conflate: the wheel force-includes the
gitignored bundle through `[tool.hatch.build.targets.wheel] artifacts`
(`pyproject.toml:60-71`), but `migrations/` is not in the wheel at all, so a wheel is not a
complete deployment unit. An editable install from a checkout serves the console straight out
of the checkout's build output. Which of the two a given host uses decides which mechanism is
load-bearing there.

## Decision 1 — the admin API is a third process because it must not hold a credential

The panel is not a blueprint on the bot. It is a separate process with a separate settings
class and a separate configuration file, and the reason is one sentence in
`src/hbd/admin/app.py:8-12`: `AdminSettings` **cannot read** `HBD_ELEVENLABS_API_KEY`, because
there is no field for it. Introspection confirms the shape — only two `AdminSettings` *fields*
are pydantic-required (`database_url` at `src/hbd/admin/settings.py:174` and a ≥32-character
`admin_audit_hmac_key` at `:229`), and none of its fields can hold a vendor secret. The
bot and worker, by contrast, are bound to three: `_VendorBoundSettings` re-declares
`telegram_bot_token`, `elevenlabs_api_key` and `llm_api_key` as required
(`src/hbd/config.py:689-699`), and `load_settings()` always asks for that stricter model
(`:758-760`).

So the *value* is already unreachable. The lifespan then makes a second check about the
*host*: it scans both `os.environ` and the names parsed out of the admin dotenv file and
refuses to boot in prod if any of them are within reach, warning elsewhere
(`src/hbd/admin/app.py:175-203`). The forbidden list is derived, never restated —
`FORBIDDEN_ENV_VARS` is built by upper-casing `hbd.config.VENDOR_SECRET_FIELDS`
(`src/hbd/admin/app.py:116-118`; the five names at `src/hbd/config.py:111-117`), so a sixth
credential added to the config module is covered without anyone remembering to add it here.
The fifth, `openrouter_management_key`, arrived that way: **D13** added it to the config tuple
and this refusal picked it up with no edit here — which is the property this paragraph is
about, demonstrated rather than asserted.

> **Two required fields is not the same as two required variables.** Before either lifespan
> refusal below can run, `AdminSettings` has to construct, and a model validator,
> `_bounds_that_span_fields` (`src/hbd/admin/settings.py:561-592`), refuses three states that
> are field-by-field legal: `admin_cookie_secure=false` in *any* environment (`:570-576`),
> a missing `HBD_ADMIN_PUBLIC_ORIGIN` whenever `environment != "dev"` — "must be set when
> environment is …" (`:578-586`, echoed at `README.md:155-157`; `.env.admin.example:73` ships
> the loopback dev value) — and DEBUG logging in prod (`:588-592`). A prod `.env.admin`
> written from the two-required-fields sentence alone produces a panel that will not boot.

Two more refusals sit in the same lifespan, in this order (`src/hbd/admin/app.py:315-316`):

1. **The panel is off unless somebody turned it on.** `HBD_ADMIN_ENABLED` defaults to
   `false` (`src/hbd/admin/settings.py:180`) and the lifespan refuses while it is
   (`src/hbd/admin/app.py:206-208`). This is also the incident kill switch: taking the panel
   down is one variable and a restart, not a code change.
2. **Vendor credentials within reach**, as above.

> **A fresh admin deployment refuses to start in three tiers, and only ever reports the
> first one it hits.** Tier one is settings construction: `_resolve_settings` runs at
> `src/hbd/admin/app.py:313`, two lines *before* `_refuse_disabled_panel` at `:315`, so on a
> non-dev host the validators above — public origin, cookie-secure, DEBUG-in-prod — and the
> field requirements fire before either refusal below is reached. Tier two is
> `HBD_ADMIN_ENABLED`; tier three is a vendor credential within reach. Both of the latter
> raise `ConfigError`, and the disabled-panel check runs first — so on a host with both
> problems the operator is told the panel is disabled and never learns about the key. On a
> fresh *prod* host with neither variable set, though, neither message is what appears: the
> settings error is. The
> `admin.boot.ok` line, which carries the environment, the env file actually read and the
> public origin (`src/hbd/admin/app.py:322-333`), is emitted after both, so a refused boot
> logs neither.

What this buys operationally: an admin-only host needs no ffmpeg, no Telegram reachability,
no ElevenLabs or LLM reachability, and holds nothing that can spend money. What it costs: the
admin process has no ARQ client and no vendor HTTP client — a grep for `enqueue_job`,
`create_pool` or `arq` across `src/hbd/admin` returns nothing, and its container holds only
the engine, the session factory, Redis, the hasher, the trusted-proxy list (`:150`), the
Redis rate-limit store (`:151`) and a `LocalFileStorage` over
`<admin_data_root>/archive` (`:155`) — the whole construction is
`src/hbd/admin/container.py:140-156`. That storage object is **not** read-only in code: it is
the same read-write `LocalFileStorage` class the worker gets
(`src/hbd/runtime/container.py:311`). The read-only property is a `:ro` mount asserted in a
code comment about the deployment (`src/hbd/admin/container.py:152-154`,
`src/hbd/runtime/container.py:308`), which is a host fact nobody here can verify — the code
declines to `mkdir` because of it, and that is all the code does about it.

> **`deploy/systemd/hbd-worker.service:1-2` (a proposal, authored without host access) says
> the worker performs "every operational action the admin panel queues".** No such path
> exists in this tree today. Anyone reading that comment will go looking for a queue between
> the panel and the worker and not find one.

## Decision 2 — the two Postgres roles, and what breaks with one

The *intent*, stated in `docker/initdb/10-two-roles.sql:17-18`, is that `hbd` owns the tables
and runs migrations while "the bot, the worker and the admin API connect as `hbd_app`". The
repo only half ships that: `.env.example:35` is
`HBD_DATABASE_URL=postgresql+asyncpg://hbd_app:hbd_app@…`, but `.env.admin.example:48` is
`postgresql+asyncpg://hbd:hbd@…` — the **owner** DSN, in the example file for the one process
whose connection identity decides the audit-log badge. An untouched copy of that example
already connects the panel as the owner. That split exists for exactly one control:

```sql
REVOKE UPDATE, DELETE, TRUNCATE ON admin_audit_log FROM <app role>
```

An owner can `GRANT` back its own revocations in one statement, so that `REVOKE` — migration
`0007`'s, at `migrations/versions/20260830_1000_0007_add_admin_audit_log.py:369` — means
nothing at all when the application connects as the owner. There is also nobody to revoke it
*from*: with one role, `<app role>` names the same principal that ran the migration
(`docker/initdb/10-two-roles.sql:7-23`, restated at `README.md:160-164`).

Two variables switch it on. `HBD_DB_MIGRATION_URL` is the owner DSN, which
`migrations/env.py:95-114` reads from the environment *and* from the dotenv file; unset,
migrations fall back to the application DSN with a WARNING that names what control that costs
(`migrations/env.py:87-93`, `:116-129`). `HBD_ADMIN_AUDIT_DSN` is how a deployment declares
the split exists (`README.md:172-178`).

> **This is the only control in the schema that survives a compromised application
> credential.** Everything else in the audit design is an HMAC that the same credential could
> recompute if it could write. Losing the two-role split does not degrade the audit log a
> little; it removes the privilege half of it entirely.

Three consequences an operator must hold in their head:

- **`chainProtection` answers a narrower question than it looks.** It is not read from
  configuration when it runs: `resolve_chain_protection` asks Postgres, with
  `has_table_privilege(current_user, 'admin_audit_log', …)` on UPDATE, DELETE and TRUNCATE
  (`src/hbd/db/admin/audit.py:746-780`), and a still-writable table logs
  `admin.audit.revoke_missing` at WARNING while the panel reports `hmac-only`. **But
  configuration decides whether the probe runs at all.** The function opens with
  `if not is_dsn_configured or not _is_postgres(session): return ChainProtection.HMAC_ONLY`
  (`:764-765`), and `is_dsn_configured` is `bool(settings.admin_audit_dsn)`
  (`src/hbd/admin/routers/audit.py:168`) — i.e. `HBD_ADMIN_AUDIT_DSN`, which defaults to `""`
  (`src/hbd/admin/settings.py:235`) and ships empty (`.env.admin.example:130`). So a
  deployment that created both roles, migrated as the owner and landed `0007`'s `REVOKE`, but
  left `HBD_ADMIN_AUDIT_DSN` blank, reports `hmac-only` with **no probe and no WARNING** —
  indistinguishable from a deployment where the control genuinely is not there. Read the
  badge as "is the split *declared*, and if so is it in force", never as "did the `REVOKE`
  land". Only `\dp admin_audit_log` in psql answers the second question on its own.
- **When it does probe, it asks about the admin process's own connection.** Nothing in
  `AdminSettings` refuses an owner DSN there, and `.env.admin.example:48` supplies one. Point
  the panel at the owner role with `HBD_ADMIN_AUDIT_DSN` set and the panel itself can rewrite
  the table the control protects — and the badge will say so. Leave the DSN unset as well and
  it will not even say that.
- **Production roles are a manual step, by the repo's own instruction.**
  `docker/initdb/10-two-roles.sql` runs only once, on an empty local Docker volume, and its
  own header says so: "In staging or production, create these two roles by hand with real
  secrets" (`:25-29`). That includes the `ALTER DEFAULT PRIVILEGES FOR ROLE hbd … GRANT … TO
  hbd_app` lines at `:43-46` — without which every table a future migration creates is
  invisible to `hbd_app` and the bot fails its first query with "permission denied".

> **Running migrations requires the vendor keys, even though a migration needs none of them.**
> `migrations/env.py:129` calls `load_settings()` for the fallback DSN, and `load_settings()`
> always demands the three required vendor secrets (`src/hbd/config.py:758-760`). A
> migration-only host, or a CI step holding only the DSN, fails with a message about missing
> API keys. Setting `HBD_DB_MIGRATION_URL` avoids that path entirely.

## Why the environment variable is the fragile part of all of this

Every production guard in the codebase hinges on `HBD_ENVIRONMENT` being the exact string
`prod`, and the two settings classes treat it very differently. `AdminSettings.environment`
is a closed `Literal["dev","staging","prod"]` (`src/hbd/admin/settings.py:169`), so a typo is
a boot failure. `Settings.environment` — the bot's and the worker's — is an unvalidated
free-form `str` with a `"dev"` default (`src/hbd/config.py:170`), and `is_production` is a
bare `== "prod"` (`:684-686`).

`HBD_ENVIRONMENT=production` on the bot or worker therefore silently disables both refusals
those processes have: fake providers in prod (`src/hbd/runtime/providers.py:104-109`) and the
in-process submitter in prod (`src/hbd/runtime/submitter.py:100-105`). No error is raised
anywhere, and the symptom is customers being served silence and template lyrics.

The two files also own the variable independently — `HBD_ENVIRONMENT` appears in both the
bot's dotenv file and the admin's, and both classes use `extra="ignore"`
(`src/hbd/config.py:165`, `src/hbd/admin/settings.py:164`), so neither file's copy can
correct or even notice the other's. `prod` in one and `dev` in the other is a completely
legal, silent state.

And *which* two files those are is itself a variable. `.env` and `.env.admin` are only the
defaults (`src/hbd/config.py:69-78`); `HBD_ENV_FILE` and `HBD_ADMIN_ENV_FILE` redirect each
side independently, which is exactly what `ENV=prod make dev` does through `$(ENV_FILES)`
(`Makefile:41-46`, `:69`). Both are read from the process environment only — a dotenv file
cannot name the file about to be read — so the pairing that is actually in force on a host is
visible in the boot logs (`src/hbd/runtime/startup.py:31-34`,
`src/hbd/admin/app.py:327-329`) and nowhere in the checkout.

## What is knowable from here, and what is not

Knowable, and cited above: the three command lines and the three by-hand commands; every
dependency edge and the code that opens it; the cron schedule; the boot refusals and their
order, settings validators included; the data-root derivation on both sides; the pool
arithmetic; the two roles and what the `REVOKE` protects.

**Not knowable from this repository, and deliberately not asserted anywhere above:**

- whether the VPS uses systemd at all, and whether `hbd-bot`/`hbd-worker`/`hbd-admin` exist
  under the names, paths and `WorkingDirectory` that `deploy/systemd/*.service` proposes —
  those files, and `deploy/first-install-proposal.md`, were authored on 2026-09-07 by an assistant with no
  host access and are a proposal;
- whether all three processes run there at all, on one box or several;
- what terminates TLS in front of the admin API, whether it adds
  `Strict-Transport-Security` (this application emits none — the only headers it sets are at
  `src/hbd/admin/middleware/security_headers.py:73-77`), and whether it appends or replaces
  `X-Forwarded-For`;
- the working directory the deployed processes run in, and therefore whether the bot's
  `Path.cwd()/var` and the admin's `admin_data_root` resolve to the same absolute path;
- whether the admin's `var/` really is mounted `:ro` there. The code asserts it only in a
  comment (`src/hbd/admin/container.py:152-154`) and builds an ordinary read-write
  `LocalFileStorage`, so the read-only property is a host arrangement, unverified here;
- which dotenv file each process actually reads — `HBD_ENV_FILE` and `HBD_ADMIN_ENV_FILE`
  come from the process environment, so a checkout's `.env`/`.env.admin` may be irrelevant to
  the running system. The `host verified` and `admin.boot.ok` log lines name the file;
- whether `HBD_ENVIRONMENT` is the exact string `prod` in each of the three processes;
- whether `HBD_ADMIN_ENABLED` is true, which is the difference between a running panel and a
  refused boot;
- whether `HBD_LLM_FALLBACK_BASE_URL` is set, which decides whether the egress allowlist
  needs a fourth host;
- whether an operator account exists at all — `python -m hbd.admin.bootstrap` is a one-time
  manual step and leaves no trace anything else reports;
- whether the two Postgres roles exist, whether `HBD_DB_MIGRATION_URL` is set, and whether
  `0007`'s `REVOKE` ever landed. `chainProtection` on `GET /api/audit/verify` cannot settle
  this on its own: with `HBD_ADMIN_AUDIT_DSN` empty it returns `hmac-only` without probing
  (`src/hbd/db/admin/audit.py:764-765`). `\dp admin_audit_log` in psql is the answer;
- how many worker replicas run, which decides whether the per-process vendor semaphore still
  means what it says;
- whether the deployed console bundle was built from the current source, and whether the
  install is an editable checkout or a wheel;
- whether the host's ffmpeg carries `libopus` — a *running* bot is itself the evidence, since
  `verify_host` would have refused otherwise, but nobody here can check that it is running.

Each of those is a question to answer on the host, not a gap in this document.
