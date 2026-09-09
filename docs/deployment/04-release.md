# Releasing a change

This is the routine deploy to a host that is already provisioned: the checkout exists, the
virtualenv exists, the database has a schema, the two dotenv files are in place, and three
processes are already running. First-time provisioning is a different document.

Read it top to bottom the first time. After that it is a checklist, and the callouts are the
parts that bite.

## What this document can and cannot tell you

Everything below about the **code** is checked against the working tree and cited as
`file.py:123`, so you can verify any claim before you act on it.

Everything about the **host** is not. This repository does not know where the checkout lives,
what supervises the three processes, or what terminates TLS in front of the admin API.
`deploy/first-install-proposal.md` and `deploy/systemd/*.service` describe a systemd deployment under
`/srv/hbd` — those files are untracked in this branch and were written without access to the
box, so they are a **proposal**, not a record. Wherever this document needs a host fact it
uses a shell variable you fill in once, and says so.

```bash
# Fill these in for your host, once, then paste the rest verbatim.
CHECKOUT=…            # the git checkout; `migrations/` and `admin-dashboard/` must be under it
PY=…                  # the interpreter the three processes already run under — a HOST fact.
                      # Makefile:22 and the untracked deploy/first-install-proposal.md:90 both assume
                      # "$CHECKOUT/.venv/bin/python"; this repository cannot confirm that is
                      # what your host uses. Read it off a running process, don't assume it.
BOT_ENV=…             # the file HBD_ENV_FILE names for the bot and worker
ADMIN_ENV=…           # the file HBD_ADMIN_ENV_FILE names for the admin API
```

> **The `make` targets are for your machine, not for the host.** `make migrate ENV=prod`
> resolves to `HBD_ENV_FILE=.env.prod` relative to the working directory (Makefile:40-46) —
> a file in the checkout. A host that sets `HBD_ENV_FILE` to an absolute path outside the
> checkout, as the proposal does, wants the underlying command with the variable set
> explicitly. Every command below is written that way.

---

## 1. Pre-flight: the three gates

There is no CI in this repository — no `.github` directory exists — so "the gates pass" means
a human typed three commands. README.md:305-310 says this in as many words. Run all three
from your own machine, on the commit you are about to ship, before you touch the host.

```bash
make check      # ruff, mypy --strict, pytest -m "not integration" with the 80% gate
make ui-check   # tsc --noEmit, eslint, vitest, tokens:check
make ui-e2e     # the browser gate; needs `make ui-e2e-install` once, ~150 MB of Chromium
```

`make check` is the Python half **only** — it is `lint typecheck cov` and nothing else
(Makefile:144). It does not reach `ui-check` and it does not reach `ui-e2e`; the top of the
Makefile (Makefile:3-20) spells the split out because the omission is deliberate rather than
an oversight.

`make ui-check` (Makefile:106-107) adds `tokens:check` to the Vitest run, and that is not
redundant: `tokens:check` verifies the `on` / `at best on` **form** each `tokens.css`
annotation must take against its token's WCAG bar, and runs the wider `{6,8}` must-annotate
scan, neither of which Vitest does. It is also what makes one deliberate failure loud — a
malformed selector takes `admin-ui/src/styles/tokenContrast.test.ts` to *zero* tests on
purpose, and `vitest run` reports a file that contributed no tests as a pass.

**`make ui-e2e` is the one nothing forces you to run.** It sits outside `make check` because
it needs a ~150 MB Chromium download (`make ui-e2e-install`, Makefile:109-110) and a first
`make check` on a new machine must not silently start that. What it uniquely catches is a
**Content-Security-Policy regression**: jsdom implements no CSP at all, so a `<style>`
element Chrome refuses is accepted in silence by every one of the console's Vitest tests.
It is also the only gate that exercises the *built* console — `ui-e2e: ui-build`
(Makefile:112) rebuilds the bundle before running. It needs no Postgres, no Redis, no
network, no vendor key and no ffmpeg; the harness runs the real admin app over in-memory
SQLite and a dictionary Redis.

> **A green `make check` proves nothing about ffmpeg.** README.md:333 still claims one unit
> test wants ffmpeg on PATH. It does not: `test_verify_host_passes_on_a_host_with_ffmpeg` is
> marked `@pytest.mark.integration` (tests/test_runtime/test_entrypoints.py:63-66) and
> `make test` / `make cov` run `pytest -m "not integration"` (Makefile:123). The only
> evidence that the host's ffmpeg satisfies the boot probe is a bot or worker process that
> actually started — see §6.

---

## 2. Pull

```bash
cd "$CHECKOUT"
git rev-parse HEAD            # WRITE THIS DOWN. It is your rollback target.
git pull --ff-only
git rev-parse HEAD
git log --oneline -1
```

Record the old SHA somewhere outside the terminal you are working in. Section 7 needs it, and
the moment you need it is the moment you will not want to be reconstructing it.

---

## 3. Dependency sync

```bash
uv pip install --python "$PY" -e "$CHECKOUT"
```

The install must stay **editable**. Two things depend on it and both fail as a 404 rather
than an error:

- `migrations/` lives at the repo root and is not packaged — `pyproject.toml:61` ships only
  `src/hbd`. A wheel has no migrations in it, so the schema step below has nothing to run.
- the admin console is served from `Path(__file__).resolve().parent / "static"`
  (src/hbd/admin/app.py:128), which under `-e .` resolves into the checkout. The
  `artifacts = ["src/hbd/admin/static/**"]` force-include (pyproject.toml:71) protects a
  wheel-based deploy; it does nothing on this path. Your protection is §5.

> **`uv.lock` is not applied by this command.** The lock file is in the tree and in sync with
> `pyproject.toml`, but nothing in the repository installs from it — `uv sync` appears
> nowhere, and `uv pip install` ignores a lock. Two deploys a week apart resolve
> independently inside the `>=` / `<` ranges in pyproject.toml:13-58. If a release goes wrong
> in a way the code cannot explain, a dependency that moved underneath you is a live
> hypothesis, and `uv pip freeze --python "$PY"` before and after is how you would know.

Python is pinned to 3.12 exactly (`requires-python = ">=3.12,<3.13"`, pyproject.toml:10), so
an interpreter upgrade on the host is a build failure, not a runtime surprise.

---

## 4. Migrations

```bash
cd "$CHECKOUT"
HBD_ENV_FILE="$BOT_ENV" "$PY" -m alembic -c migrations/alembic.ini current   # where you are
HBD_ENV_FILE="$BOT_ENV" "$PY" -m alembic -c migrations/alembic.ini heads     # where head is
HBD_ENV_FILE="$BOT_ENV" "$PY" -m alembic -c migrations/alembic.ini upgrade head
```

The `upgrade head` line is the command Makefile:147 wraps. The chain is linear —
`0001` → `0021`, no branches, every `down_revision` its immediate predecessor — so `current`
and `heads` printing the same revision is the whole of "the schema matches the code".

**Read alembic's own output.** One WARNING there decides whether a security control exists:

```
HBD_DB_MIGRATION_URL is not set, so migrations are running as the application role. That
role owns every table it creates, and an owner can GRANT back anything revoked from it — so
the audit log's REVOKE is not a control on this deployment.
```

That is migrations/env.py:89-93, emitted by `_database_url()` (env.py:117-129) when
`_owner_url()` finds nothing. `_owner_url()` (env.py:96-114) checks the process environment
**and** falls back to the dotenv file `HBD_ENV_FILE` names, so `HBD_DB_MIGRATION_URL` written
into `$BOT_ENV` is enough for that half.

> **The owner role is only half the two-role control, and the other half reads a different
> place.** Migration `0007` installs the `REVOKE UPDATE, DELETE, TRUNCATE ON
> public.admin_audit_log` that makes the audit log append-only for the application role. Its
> preconditions are read from `os.environ` **only**, with no dotenv fallback: the DSN gate at
> `migrations/versions/20260830_1000_0007_add_admin_audit_log.py:336`, and the role name via
> `_app_role()` at the same file:314-322, which wants `HBD_DB_APP_ROLE` or a username inside
> `HBD_DATABASE_URL`. Migration `0011` repeats the pattern. `HBD_ADMIN_AUDIT_DSN` is
> documented as belonging in the *admin* dotenv file (.env.admin.example:130), which the
> alembic process never loads. Both misses are a `_skip()` WARNING, never a failure.
>
> If you want the REVOKE to land as a real two-role control, **four** variables have to be
> right in the migrate shell, not three. `HBD_DB_MIGRATION_URL` is the one that decides
> whether the REVOKE is a control at all — without it `_database_url()` falls back to the
> application DSN (env.py:117-129), the tables' own owner issues the REVOKE against itself,
> and you get exactly the non-control the WARNING above describes. `_owner_url()` reads
> `$BOT_ENV` as well as the environment, so if that line is already in `$BOT_ENV` it is
> already covered — check before you assume, because this document cannot know:
>
> ```bash
> grep -c '^HBD_DB_MIGRATION_URL=' "$BOT_ENV"    # 0 means the block below must set it too
> ```
>
> Then run the upgrade with the ones that are missing set explicitly:
>
> ```bash
> cd "$CHECKOUT"
> HBD_ENV_FILE="$BOT_ENV" \
> HBD_DB_MIGRATION_URL="<the owner DSN>" \
> HBD_ADMIN_AUDIT_DSN="<the owner DSN>" \
> HBD_DB_APP_ROLE="<the application role name>" \
> HBD_DATABASE_URL="<the application DSN>" \
>   "$PY" -m alembic -c migrations/alembic.ini upgrade head
> ```
>
> `HBD_DB_APP_ROLE` and `HBD_DATABASE_URL` are alternatives, not both required —
> `_app_role()` (0007:314-322) takes the role name from the first and otherwise from the
> userinfo of the second. Neither `HBD_DB_APP_ROLE` nor `HBD_ADMIN_AUDIT_DSN` appears in
> `.env.example`, and `HBD_DB_MIGRATION_URL` appears there once (.env.example:46), so none of
> them is likely to arrive by accident.
>
> **Omitting `HBD_DB_MIGRATION_URL` here is worse than doing nothing**, because it is not
> visibly worse: migration `0007` still installs a `REVOKE`, and `/api/audit/verify` still
> reports `chainProtection: revoke+hmac` afterwards. You would believe you had a two-role
> control and would not have one. See the `chainProtection` note in §7.
>
> Whether this was ever done on your host is not knowable from the repository. §6 tells you
> how to ask the running system instead.

One more trap worth knowing before it bites: when `HBD_DB_MIGRATION_URL` is *absent*,
`_database_url()` falls through to `load_settings()` (env.py:129), and `load_settings()`
always demands the three vendor secrets (src/hbd/config.py:689-699, :758-760). A migration
needs none of them. So a migrate shell with a DSN but no Telegram token fails with a message
about missing API keys — which is confusing, and is a signal that the owner DSN is not set.

---

## 5. Rebuild the admin console

```bash
cd "$CHECKOUT/admin-dashboard" && npm ci && npm run build
```

**Build `admin-dashboard/`, not `admin-ui/`.** There are two consoles in this tree and they
write to the *same* output directory with `emptyOutDir: true` — admin-dashboard/vite.config.ts:20-21
and admin-ui/vite.config.ts:106-107 both name `../src/hbd/admin/static`. So the last one built
wins, completely, and building the wrong one is not a partial deploy: it replaces the panel.
`admin-ui/` is the legacy Gogo console, marked `[DEPRECATED in favor of admin-dashboard]` in its
own admin-ui/package.json:6. The Makefile already reflects this — `UI := admin-dashboard`
(Makefile:30) and `make ui-build` (Makefile:110-111) build the dashboard, while the legacy
console has been moved aside to `make legacy-ui-build` (Makefile:116-117). This section said
`admin-ui` until 2026-09-09 and was wrong; if another document in this directory still says it,
it is wrong the same way.

This step is not optional and it is not cosmetic.

`src/hbd/admin/static/` is gitignored (src/hbd/admin/app.py:124-128), so `git pull` never
updates the bundle. `npm run build` writes into that directory with `emptyOutDir: true`
(admin-dashboard/vite.config.ts:20-21) — the Python package tree *is* the build target.

Skipping it degrades the panel **silently**, in two different ways, neither of which looks
like a build problem:

- **No bundle at all** (a fresh checkout, or a build that was cleaned). The API is perfectly
  healthy: `/healthz` answers, every `/api` route answers, and only browser URLs 404 —
  `if not SPA_INDEX.is_file(): raise HTTPException(status_code=404)` (app.py:238-239), with
  the static mount deliberately built `check_dir=False` (app.py:298) so the process still
  boots.
- **A stale bundle**, which is worse because it looks like it works. `admin-dashboard/index.html:8`
  carries a `__HBD_CSP_NONCE__` placeholder that the API replaces with this response's style
  nonce. A bundle built before that placeholder existed has nothing to replace, and
  `render_shell` serves such a shell **unchanged** and logs
  `WARNING admin.spa.nonce_placeholder_missing` (src/hbd/admin/shell.py:65-85) rather than
  returning 500 — deliberately, so an operator reaching for the panel mid-incident gets a
  working panel rather than a dead one. The cost is that the only symptoms are that one log
  line and modals that no longer lock the background: `style-src 'self' 'nonce-…'` refuses
  the scroll-lock `<style>` the bundle injects, and the page keeps scrolling behind an open
  dialog.

Nothing in either gate catches a stale *deployed* bundle. `tests/test_admin/test_spa_nonce.py`
checks the checked-in `admin-ui/index.html`, not the built one, and `make ui-e2e` rebuilds
before it runs (Makefile:112). Placeholder drift and staleness are different checks; only the
first exists.

---

## 6. Restart, in order

Three processes, three commands. There is no console script for any of them — `pyproject.toml`
has no `[project.scripts]` table — so whatever supervises them spells out the interpreter and
`-m`:

```bash
HBD_ENV_FILE="$BOT_ENV"         "$PY" -m hbd.main                       # the bot    (Makefile:69)
HBD_ENV_FILE="$BOT_ENV"         "$PY" -m arq hbd.worker.WorkerSettings  # the worker (Makefile:72)
HBD_ADMIN_ENV_FILE="$ADMIN_ENV" "$PY" -m uvicorn hbd.admin.app:app \
    --host <bind address> --port <port>                                # the admin  (Makefile:75)
```

The `HBD_ENV_FILE` / `HBD_ADMIN_ENV_FILE` prefixes are the rule from the top of this document,
not decoration. The Makefile recipes carry them as `$(ENV_FILES)` (Makefile:41-46) and that
prefix is *empty* for the default `ENV=dev`, so these three commands stripped of it fall back
to a bare `.env` / `.env.admin` inside the checkout — the precise accident Makefile:38-40 says
the split exists to prevent ("a stray `.env` left in /srv/hbd cannot be read by accident").

**The admin bind address and port are a host fact this document does not know.** `--host` and
`--port` are uvicorn arguments, and passing them *overrides* whatever the panel is configured
for: `HBD_ADMIN_HOST` and `HBD_ADMIN_PORT` are real settings (src/hbd/admin/settings.py:188-189,
documented at .env.admin.example:64-65), but nothing under `src/hbd` reads them to bind — they
only surface in the config view (src/hbd/admin/schemas/config_view.py:202-203). Both default to
`127.0.0.1:8080`, and `127.0.0.1 8080` is what Makefile:75 and the untracked proposal
(deploy/systemd/hbd-admin.service:30) hard-code. If your `$ADMIN_ENV` sets either variable to
something else, pasting `127.0.0.1 8080` binds the wrong socket and the TLS proxy in front of
the panel reaches nothing. Read the values out of `$ADMIN_ENV`, or off however the host
currently starts the process, before you fill the two placeholders in.

Restart **admin API → bot → worker**, and understand what each costs.

**The admin API is free to restart.** It holds no queue, no vendor client and no in-flight
customer work — its container is "engine, sessions, Redis, and nothing else"
(src/hbd/admin/container.py:1). Going first means its boot refusals fire while you are still
watching, before you have disturbed anything a customer is using. They come from two places
and this is not a closed list:

- `_refuse_disabled_panel(settings)` and `_refuse_vendor_credentials(settings)`, called back
  to back in the lifespan (src/hbd/admin/app.py:315-316) — the panel switched off, and a
  vendor credential or bot token within reach of the admin process.
- the `AdminSettings` validators, which raise earlier still, inside `_resolve_settings` on
  app.py:313. `_bounds_that_span_fields` (src/hbd/admin/settings.py:561-594) alone refuses an
  idle TTL longer than the absolute TTL, `admin_cookie_secure` false (the cookies are
  `__Host-` prefixed, so a browser would reject them outright), `HBD_ADMIN_PUBLIC_ORIGIN`
  unset outside `dev`, and DEBUG logging in prod. Other field and model validators in that
  file can refuse too.

**Restarting the bot loses messages.** `run_polling` calls
`bot.delete_webhook(drop_pending_updates=True)` on every start (src/hbd/bot/app.py:216), so
every Telegram update that arrived during the restart window is discarded and never resent.
This is a known, accepted deploy-window loss; src/hbd/main.py:156-162 explains that the churn
signal is the only thing given a second source, because the worker also learns about a block
from a refused `sendAudio`.

**The worker is the expensive one, and it matters most.** A `SIGTERM` cancels running jobs —
`build_kit_worker_settings` never sets `retry_jobs`, so arq's default `True` applies and
`Worker.handle_sig` cancels running tasks (src/hbd/runtime/jobs.py:221, :585). The job's
`CancelledError` path (jobs.py:575-590) does three things and, importantly, not a fourth: it
sends the customer a timed-out frame with a start-over keyboard, releases the parked wizard
session, re-raises so arq requeues the job — and **settles nothing**. That last omission is
deliberate: a refund there would be a refund plus a requeue plus a replay that finds the order
still paid for, i.e. one free song per deploy. The customer's experience is a scary message
followed by a song that arrives anyway on the next attempt, at the cost of a second vendor
render.

So: restart the worker when the queue is quiet if you can. And do not leave it down. It is the
only process that runs the three crons — the retention sweep hourly at :17, the vendor balance
poll hourly at :43, the activity snapshot daily at 00:07 UTC (jobs.py:705-770) — all with
`run_at_startup=False`, so a worker cold-started at 12:05 does nothing until 12:17. While it is
down: the retention sweep, a stated legal obligation, does not run; `settle_stale_debits`,
which rides inside the purge transaction (src/hbd/db/purge.py:376-378) and is the *only*
backstop for a debit whose job never came back (src/hbd/db/credit_settlement.py:203-222), does
not run; and the audit chain's HEAD anchor stops being re-pinned, which means tail deletions
become undetectable while `/audit/verify` still reports `ok: true`.

---

## 7. Verify

Logs are one JSON object per line whenever `HBD_IS_DEBUG` is false — that flag is the only
switch, and `HBD_LOG_LEVEL` does not change the format (src/hbd/logging.py:230-243). The
envelope is `ts`, `level`, `logger`, `message`, `correlation_id`, plus a `context` object
holding everything passed as `extra=` (logging.py:200-220). **The `event` name lives inside
`context`, not at the top level.**

Substitute your own log command for `<read the bot log>` below; the strings are what matter.

### The bot and the worker

```
"host verified"              # ← a SPACE, not an underscore
"bot starting"
"worker dependencies built"
"worker started"
```

`host verified` is src/hbd/runtime/startup.py:33-41 and carries `environment`, `env_file`,
`ffmpeg`, `locales` and `catalogue_languages`. Two of those are the whole point of the line:
`HBD_ENV_FILE` makes it possible to boot a production configuration from a development
checkout, and this is the one place that says which file was actually read. Confirm
`environment` is exactly `prod` — `Settings.environment` is an unvalidated `str`
(src/hbd/config.py:170) and `is_production` compares `== "prod"` (config.py:685-686), so
`production` or `PROD` silently disarms the fake-provider refusal
(src/hbd/runtime/providers.py:104-109) and the in-process-submitter refusal
(src/hbd/runtime/submitter.py:100-105).

A `host verified` line is also your evidence about ffmpeg: `verify_host` refuses to start
without `ffmpeg`, `ffprobe` and an ffmpeg build carrying the `libopus` encoder
(src/hbd/audio/startup.py:82-108), so a bot or worker that reached this line passed that probe.

> **`grep host_verified` matches nothing, ever.** `deploy/first-install-proposal.md:143` — the same
> untracked, host-blind proposal named at the top of this document — tells you to grep for
> `host_verified` with an underscore. The message is `"host verified"` with a space, and it
> is the log *message*, not an `event` field. An operator following that line sees an empty
> result and concludes the bot did not boot. Grep the quoted string.

Also read, once, near the boot lines:

```
"the checkout is wired but the credit meter is dark"
```

That is src/hbd/main.py:177-189 — a WARNING and deliberately never a refusal. It means the
paywall is wired while `HBD_CREDITS_ENFORCED` is false, so a customer is shown a price,
charged, and the worker covers the shortfall with an `UNENFORCED_RENDER` grant anyway. If it
was not there before this deploy and is there now, something in the configuration moved.

### The admin API

Two lines, and only two, are decided at start-up:

```
admin.boot.ok                       # must be present
admin.boot.vendor_env_present       # must be absent in prod
```

Two other strings are worth knowing, but neither is a boot line, so **their absence from a
freshly restarted log proves nothing**:

- `admin.spa.nonce_placeholder_missing` is emitted per *response*, from `render_shell`
  (src/hbd/admin/shell.py:65, :78-84) — it can only appear once somebody has loaded a browser
  URL. Load the panel first, then grep. See §5.
- `admin.audit.revoke_missing` is emitted only inside `resolve_chain_protection`
  (src/hbd/db/admin/audit.py:774-778), which runs only when somebody requests
  `/api/audit/verify` (src/hbd/admin/routers/audit.py:161-169) — and even then only when
  `HBD_ADMIN_AUDIT_DSN` is set: with it unset the function returns `hmac-only` at
  audit.py:764-765 and logs nothing at all. In the common case its absence carries no
  information about whether the REVOKE of §4 landed. Read `chainProtection` below instead.

`admin.boot.ok` is a real `event` field (src/hbd/admin/app.py:321-333) carrying
`environment`, `env_file`, `is_cookie_secure` and `public_origin`. Check `public_origin` is
the `https://` origin a browser actually types: the CSRF check compares `Origin` **exactly**
(src/hbd/admin/csrf.py:76-88), and the boot guard only tests whether the variable was
*set*, not whether it is right (src/hbd/admin/settings.py:578-588). A wrong value gives you a
panel that logs in cleanly and then 403s every single mutation with `ORIGIN_REJECTED`.

`admin.boot.vendor_env_present` is a WARNING outside prod and a boot refusal inside it
(app.py:186-203), so a *running* prod panel already proves the four vendor variable names are
out of its reach — for `os.environ` plus the admin dotenv file it loaded, which is not the same
as "for every file on the box".

### The audit chain

Sign in to the panel as **ADMIN or OWNER** — `/api/audit` and `/api/audit/verify` are behind
`Permission.AUDIT_READ`, which is granted to those two roles only
(src/hbd/admin/security/permissions.py:374) — and read `GET /api/audit/verify`
(src/hbd/admin/routers/audit.py:62, :161-186). Three fields, in this order:

- **`chainProtection`. Read it as a one-way test, not as a verdict.** It is not read from
  configuration — `resolve_chain_protection` asks Postgres
  `has_table_privilege(current_user, 'admin_audit_log', 'UPDATE'/'DELETE'/'TRUNCATE')`
  (src/hbd/db/admin/audit.py:745-780) — so it reports a fact about the database rather than
  whether somebody set a variable. The direction it is sound in is the negative one, and that
  is all the code claims for itself (audit.py:759-762): `hmac-only` means this connection can
  still write the log, so the append-only guarantee is the HMAC chain alone.

  `revoke+hmac` means only that *this* connection currently lacks those three privileges. The
  probe (audit.py:746-751) cannot distinguish an application role that a separate owner
  revoked from — the real control — from a table owner that revoked its own default
  privileges and can `GRANT` them straight back, which is the non-control the WARNING quoted
  in §4 describes (migrations/env.py:89-93). A one-role deployment that ran `upgrade head`
  with `HBD_ADMIN_AUDIT_DSN` set but `HBD_DB_MIGRATION_URL` unset reports `revoke+hmac` too.
  So `revoke+hmac` is a necessary condition for the two-role control, not a sufficient one:
  pair it with evidence that the migrations ran under the owner DSN (§4).

  The gap in the other direction is real as well: it asks about the *admin process's*
  connection, so if that process connects as the table owner rather than the application role,
  this reads `hmac-only` and the panel itself can rewrite the log.
- **`ok`.** `false` names `firstBreakSeq`. It detects three distinct things: a mutated row, a
  prefix excision and a tail excision (audit.py:593-600).
- **`isComplete`.** The walk stops at 50 000 rows in batches of 500 (audit.py:129, :132,
  :646-656). `ok: true` with `isComplete: false` is **not** a verified chain — it is a
  verified prefix. Read both fields or you are reading a badge, not a check.

### The retention row

After the first `:17` past the hour following the deploy, check the newest `purge_runs` row
via the panel's retention screen. `is_batch_full` true means a sweep hit its 500-row bound and
did not keep up (src/hbd/db/models/purge_run.py:111).

For the bytes, read the screen's **reconciliation verdict**, not a subtraction. Three columns
record the outcome — `storage_keys_returned`, `storage_keys_deleted` and
`storage_delete_failures` (purge_run.py:102-105) — and `is_storage_leaking` (purge_run.py:118-121)
compares only the first two. The API folds all three into a `StorageReconciliation`, returning
`LEAKED` when `row.is_storage_leaking` **or** `storage_delete_failures > 0`
(src/hbd/admin/schemas/retention.py:183-191), and that is what the screen renders. So `LEAKED`
is strictly broader than `returned > deleted`: a sweep whose deletes failed outright leaks bytes
while those two counters can still match. The raw numbers are on the row too, as
`keysReturned` / `keysDeleted` / `deleteFailures` plus `unreconciledKeys`
(retention.py:221-226), if you want to see which of the two produced the verdict.

Note also that `RECONCILED` is not today's normal clean answer. `KEYS_UNRECORDED` — asset rows
deleted with no key handed back — is (retention.py:101-104), and it means "unknown", not "clean".

---

## 8. Rolling back

Be precise about what a rollback returns and what it does not. Three categories.

### Code: reversible

```bash
cd "$CHECKOUT"
git rev-parse --abbrev-ref HEAD    # WRITE THIS DOWN TOO — the branch you are leaving
git checkout <the SHA from §2>
uv pip install --python "$PY" -e "$CHECKOUT"
cd "$CHECKOUT/admin-dashboard" && npm ci && npm run build   # NOT optional on the way back either
# restart admin API → bot → worker, exactly as in §6 — including the HBD_ENV_FILE /
# HBD_ADMIN_ENV_FILE prefixes and your own bind address and port
```

The console rebuild is as mandatory on a rollback as on a deploy, for exactly the reason in
§5: the bundle is gitignored, so `git checkout` moves the source and leaves the *newer*
compiled console in place, serving the old API. That mismatch is silent.

> **This leaves the checkout on a detached HEAD, and §2 does not work from there.**
> `git checkout <SHA>` detaches; the next release opens with `git pull --ff-only`, which
> refuses outright with "You are not currently on a branch". Nothing else in this document
> puts you back, so do it deliberately once the incident is closed and you are ready to take
> the newer code again:
>
> ```bash
> cd "$CHECKOUT"
> git status -sb          # confirm nothing is uncommitted before you move
> git checkout <the branch you wrote down above>
> ```
>
> That reattaches to the branch *and* moves the working tree back to the code you rolled away
> from, so it is a re-deploy, not a tidy-up: follow it with §3, §5 and §6 in order.

### Migrations: reversible only where a real downgrade exists

And "reversible" is not "lossless". There is no rule that a revision has a downgrade at all.
Check the file before you trust it:

```bash
sed -n '/^def downgrade/,$p' "$CHECKOUT/migrations/versions/"*_00NN_*.py
```

In this tree every revision from `0001` to `0021` has a real `downgrade()` body — none is a
`pass`. That is a strong repository, not a licence. Several of those bodies destroy data:

- **`0007` drops `admin_audit_log` and `audit_chain_anchors` outright**, along with the two
  `SECURITY DEFINER` purge functions
  (migrations/versions/20260830_1000_0007_add_admin_audit_log.py, `downgrade`). Downgrading
  past it deletes the audit log. It does not break the chain; it removes it.
- **`0003` drops `briefs.approved_lyrics`** — every approved lyric, gone. Its own comment
  argues this is the correct downgrade, because older code cannot read the column.
- **`0002` truncates** every `generation_attempts.stt_transcript` to the old 200-character
  bound *before* narrowing the column, deliberately, because a downgrade that raises is a
  downgrade nobody can run.
- **`0011` drops the `purge_runs` counter columns**, so the sweep history loses its counts.

If your rollback target is behind the current head:

```bash
cd "$CHECKOUT"
HBD_ENV_FILE="$BOT_ENV" "$PY" -m alembic -c migrations/alembic.ini downgrade <revision>
```

Same DSN resolution as §4, so the owner-role question is identical: without
`HBD_DB_MIGRATION_URL` you are downgrading as the application role.

> **Prefer not downgrading.** Most releases in this tree add a table or an index; the old code
> ignores what it does not know about, and leaving the schema ahead is usually cheaper than
> destroying rows to make a version number match. Downgrade when the new revision changed or
> narrowed something the old code reads — not as a reflex.

> **Never rotate `HBD_ADMIN_AUDIT_HMAC_KEY` as part of a rollback.** The chain is
> `HMAC-SHA256(key, "v1" ‖ prev_hmac ‖ canonical_json(row))` and carries **no key identifier**
> (src/hbd/db/admin/audit.py:8-16). Change the key and `/audit/verify` reports a break at the
> first row, forever, indistinguishable from tampering. Lose it and the log is permanently
> unverifiable. It lives in the admin dotenv file and nowhere in the database, so a
> database-only restore comes back with an audit log nobody can check.

### Customer-visible side effects: not reversible at all

Nothing in a rollback reaches these. Enumerate them out loud before you decide the incident is
over:

- **Kits already delivered.** A song sent to Telegram is sent.
- **Messages lost to the restart.** Every update that arrived while the bot was down was
  dropped by `delete_webhook(drop_pending_updates=True)` (src/hbd/bot/app.py:216) and is not
  resent — on the way out *and* on the way back, since the rollback restarts the bot again.
- **Credit ledger movements.** `credit_accounts.balance` is a second representation of
  `SUM(credit_ledger.delta)` (src/hbd/db/credits.py:43-46); rolling code back un-writes
  neither. After any manual repair, `verify_balances` (src/hbd/db/credit_sql.py:667) is the
  one query that says whether the money state is self-consistent.
- **Rows and bytes the retention sweep deleted.** The purge is a delete, not a soft delete,
  and expiries are *stamped* at write time rather than computed (src/hbd/db/retention.py:1-19)
  — so changing a policy never un-deletes anything and never reaches rows already written.
- **Vendor spend.** Money spent at ElevenLabs and the LLM is spent, including the second
  render a cancelled job costs you (§6).
- **Audit rows.** Append-only by design. Do not "clean up" the log to make a verify go green;
  the chain is what proves you did not.

Nothing in this repository backs anything up — `pg_dump` appears nowhere in `README.md`, the
`Makefile`, `deploy/` or `docs/`. Whether the host has snapshots is a question this document
cannot answer, and a database-only restore would come back with rows pointing at archive
objects that are gone, no in-flight orders, and an audit log it cannot verify without the HMAC
key from the admin dotenv file.
