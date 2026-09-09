# Day-2 operations

Everything below is derived from the working tree and cites the file and line it comes from,
so a reader who doubts a sentence can check it in a minute. Nothing here describes a
particular host: this repository knows what the code does, not where it runs, what
supervises it, or which dotenv file a live process was pointed at. Wherever a command needs
that knowledge it is written with a placeholder, and wherever a runbook's answer depends on
it, the dependency is stated rather than guessed.

## How to run any of these commands

There is no installed console script for anything in this project — `pyproject.toml` has no
`[project.scripts]` table at all — so every entry point is `python -m`, and the interpreter
has to be named. The Makefile is the reference spelling: `.venv/bin/python -m hbd.main`
(Makefile:69), `-m arq hbd.worker.WorkerSettings` (Makefile:72),
`-m uvicorn hbd.admin.app:app` (Makefile:75).

Two things decide what an operator command actually acts on, and both are invisible in the
command itself:

```bash
cd <checkout>                       # decides the data root, see below
HBD_ENV_FILE=<the bot's env file> \
  .venv/bin/python -m hbd.tools.credits ...
HBD_ADMIN_ENV_FILE=<the panel's env file> \
  .venv/bin/python -m hbd.admin.bootstrap ...
```

`hbd.admin.bootstrap` builds `AdminSettings` (bootstrap.py:319 → `build_admin_settings()`),
so it reads whatever `HBD_ADMIN_ENV_FILE` names; both tools under `src/hbd/tools/` build
`Settings` (credits.py:302, identity.py:321), so they read `HBD_ENV_FILE`. Point one of them
at the wrong file and it will happily do the right thing to the wrong database.

> **`cd` is a load-bearing argument.** The bot and the worker derive their data root from the
> process working directory — `root = (data_root or Path.cwd() / "var").resolve()`
> (runtime/container.py:286) — and there is no environment variable that overrides it.
> `main()` never passes one (main.py:222). The admin process uses `HBD_ADMIN_DATA_ROOT`,
> whose default is the *relative* path `var` (admin/settings.py:423). The two agree only if
> the processes share a working directory. Whether they do on any given host is a deployment
> fact this repository cannot state; the symptom when they do not is that the panel's media
> reveals 404 while the database row says the file exists.

Both operator CLIs build settings with `require_vendor_secrets=False` (credits.py:302,
identity.py:321), so comping a customer does not require the ElevenLabs or LLM keys to be on
the box. `hbd.admin.bootstrap` needs no vendor key either — `AdminSettings` has no field that
could hold one.

---

## Operator accounts

There is no signup route. `python -m hbd.admin.bootstrap` is the only thing in the tree that
creates an operator account, and it is deliberately awkward about exactly one thing: the
password never travels through `argv`.

### The first OWNER

```bash
cd <checkout>
HBD_ADMIN_ENV_FILE=<admin env file> \
  .venv/bin/python -m hbd.admin.bootstrap --username owner
```

It prompts twice, without echo (bootstrap.py:137-144), and prints one line:

```
Created OWNER 'owner'. It must change its password at first sign-in.
```

`make admin-bootstrap u=owner` is the same command with the dotenv pair the `ENV` variable
selects (Makefile:77-82); anything else is passed through `args=`, as in
`args="--reset-owner"`.

A second run against a database that already has an account prints, and exits 1:

```
This database already has an admin account, so an OWNER already exists. Use --reset-owner
to recover ownership when no active OWNER remains.
```

That refusal is the *rowcount* of a conditional insert, not a pre-check
(bootstrap.py:155-176). The guarantee against two simultaneous runs is a constraint, not a
query: `ix_admin_users_active_owner`, the partial unique index from migration `0010`
(bootstrap.py:33-38). The module docstring records that two engines behind an `asyncio`
barrier produced two OWNER rows in five trials out of five on Postgres 16 before that index
existed, and that SQLite could not have caught it.

### The password rules, and why they are only one rule

`_validate_password` compares length and nothing else — 8 to 256 characters, no composition
rule, no blocklist, no username check (bootstrap.py:146-152, with the bounds at
admin/schemas/common.py:35 and :38). The floor was lowered from 12 to 8 by a product
decision on 2026-09-04, and the comment that records it also records what is now carrying the
weight: "At 8 the argon2 parameters are doing most of the work against a leaked hash, so keep
`HBD_ADMIN_ARGON2_MEMORY_KIB` high and leave the login throttle in place"
(admin/schemas/common.py:31-34). Those two are not tunables to be trimmed for latency; at an
8-character floor they are the defence.

### Why `--password` exists only to be refused

`--password` is added to the parser with `help=argparse.SUPPRESS` (bootstrap.py:116-120) so
that it can be rejected with an explanation rather than with an "unrecognised argument":

```
Refusing --password: a password in argv is visible in `ps` to every user on this host and
is written to your shell history. Run without it to be prompted, or use --password-file
with a file only you can read (chmod 600).
```

(bootstrap.py:80-84, raised at :305, exit 1.) A deploy script that passes `--password` gets
that line and no account.

The supported non-interactive channel is `--password-file`, and it is refused unless the
file has no group or other permission bit set at all — `mode & 0o077 == 0`
(bootstrap.py:78, :129-134). The comment on that constant is worth reading, because the
check is stricter than "readable" for a reason: a file the group can *write* is a file the
group can replace between the moment the operator writes it and the moment this command
reads it.

```bash
umask 077 && printf '%s' 'the password' > /tmp/pw
HBD_ADMIN_ENV_FILE=<admin env file> \
  .venv/bin/python -m hbd.admin.bootstrap --username owner --password-file /tmp/pw
shred -u /tmp/pw
```

The file's contents are `.strip("\r\n")` only (bootstrap.py:134), so trailing spaces or tabs
become part of the password.

### Recovering a lost OWNER

```bash
HBD_ADMIN_ENV_FILE=<admin env file> \
  .venv/bin/python -m hbd.admin.bootstrap --username owner --reset-owner
```

`--reset-owner` is refused while **any active OWNER exists** (bootstrap.py:187-191). That is
what stops it being a privilege escalation for anyone who reaches the host: recovery is for
the case where nobody can sign in, and that case is exactly "no active OWNER". When it
proceeds it writes the new hash, `role=OWNER`, `is_active`, `must_change_password` and
`password_changed_at` in one statement, then revokes every session that account had
(bootstrap.py:207-219) — so no window exists in which the account is an OWNER with the old
password.

> **The lockout trap this refusal creates.** An OWNER row that exists but cannot sign in —
> a forgotten password, or a login throttle the operator keeps tripping — is *not* the
> locked-out case as the code defines it, so `--reset-owner` refuses. The row has to be
> deactivated first, which is a hand-written `UPDATE` against `admin_users` and is the one
> operator step no document in this repository describes. The check the refusal message
> itself suggests is `SELECT username FROM admin_users WHERE role = 'owner' AND is_active;`
> (bootstrap.py:232-237).

Both bootstrap paths set `must_change_password=True` (db/admin/accounts.py:178 for the first
OWNER; bootstrap.py:201 and :213 for recovery), and a session in that state can reach only
`/api/auth/password` and `/api/auth/me` (admin/deps.py:116-118, enforced at :255). Note that
`/api/auth/logout` is deliberately *not* exempt: a first-boot operator cannot log out through
the API, they drop the cookie.

### What bootstrap writes to the audit log

The audit row goes in the **same transaction** as the account write (bootstrap.py:239-271),
because an OWNER created without a trace and a trace without an OWNER are both worse than
neither. It carries `actor_id = NULL` and `actor_username = "system:bootstrap"`
(bootstrap.py:242, :257) — the literal an operator should grep for to find every
out-of-band ownership event, chosen so that a login by an account that happens to be called
"bootstrap" cannot be mistaken for one. The reason code is `ROUTINE_OPS` on a create and
`INCIDENT` on a reset (bootstrap.py:262-266).

> **A recovery that creates an account is logged as a password change.** `_perform` picks the
> audit action from the `--reset-owner` flag, not from what happened (bootstrap.py:274-283),
> while `_reset_owner` calls `accounts.create(...)` when the username did not exist
> (bootstrap.py:193-204). So a brand-new OWNER born of a recovery appears in
> `admin_audit_log` as `ADMIN_PASSWORD_CHANGE` for an account that did not exist a moment
> earlier. The create is invisible in the action column; the returned message
> ("Created OWNER … by recovery.") is the only place it shows.

### Exit codes

`0` success, `1` an operator refusal, `2` a configuration failure (`HbdError`) —
bootstrap.py:72-74, dispatched at :319-343. The same three-way contract is used by both
tools under `src/hbd/tools/` (credits.py:70-72, identity.py:62-64). A deploy script can tell
"already bootstrapped" from "the environment is wrong" without parsing English. Nothing on
any of these paths ever prints a traceback, because a traceback from a command holding a
`Settings` object would carry the DSN (bootstrap.py:319-325).

---

## The operator CLIs

`src/hbd/tools/` holds exactly two, and neither is imported by the application: "Not a
library. Nothing under `src/hbd` imports from here" (tools/\_\_init\_\_.py:1-5). They write
through the same functions the product writes through, which is the whole point — the CLI
cannot produce a row shape the ordinary path could not.

> **Both tools reconfigure logging on the way in, unconditionally to JSON.** `main()` calls
> `configure_logging()` with no arguments (credits.py:319, identity.py:333) and the defaults
> are `level="INFO", is_json=True` (logging.py:230). So these commands emit JSON lines on
> stdout regardless of `HBD_IS_DEBUG` — which matters because for one of the two verbs below
> that line is the *only* record of what was done.

### Credits: `python -m hbd.tools.credits grant|block`

```bash
HBD_ENV_FILE=<bot env file> .venv/bin/python -m hbd.tools.credits grant \
  --telegram-user-id 123456789 --actor alice --credits 1 --reference ticket-4821
```

```
Account 123456789: balance is now 4. Reference: grant:admin:ticket-4821
```

The reference is printed on **every** run including the replay that added nothing
(credits.py:253-270), which is the shape an operator needs: repeat the command verbatim and
an identical balance with an identical reference means the first run had already landed.
Omit `--reference` and a fresh `uuid4` is minted and printed — safe once, deliberately not
safe to repeat blindly (credits.py:200-204).

> **A reference is global, not per-account.** The CLI's key is `grant:admin:{reference}`
> (credits.py:200-214) and `credit_ledger.idempotency_key` is `unique=True`
> (db/models/credit_ledger.py:122-123). Reuse one reference across two different accounts and
> the second run credits **nobody**: the key is spent, `grant` answers "already applied", and
> the tool prints that account's unchanged balance. This is the same defect the panel's grant
> route fixed by putting the Telegram id inside the key —
> `grant:admin:{telegram_user_id}:{requestId}` (admin/routers/credits.py:220, with the
> argument at :198-206) — and the CLI has not been given the same treatment. Key a reference
> off one press of one button, never off a ticket id you might reuse.

`--reference` accepts letters, digits, dash, underscore and dot only, and refuses a colon on
purpose: a colon could collide with `grant:period:{id}:{index}` and silently consume the key
a rolling allowance has not been minted under yet (credits.py:86-92, :209-213).

```bash
HBD_ENV_FILE=<bot env file> .venv/bin/python -m hbd.tools.credits block \
  --telegram-user-id 123456789 --actor alice          # --unblock lifts it
```

```
Account 123456789 is now blocked. Recorded in the log as admin:alice.
```

> **A block made *by this CLI* is attributable only in the process log.** `users` carries no actor column and
> §5.11 forbids DDL on it, so `_block` writes the actor to the log and says so in the
> returned sentence and in `--help` rather than pretending otherwise (credits.py:273-293).
> Grep for the message `an operator changed an account's block`, with `context.actor`,
> `context.telegram_user_id` and `context.is_blocked`. If the logs of the process that ran
> this command are not retained, the attribution does not exist anywhere. A grant, by
> contrast, is in `credit_ledger.actor` forever — and so is a block made through the panel,
> which writes an audit row rather than a log line (next paragraph).

The panel now has routes of its own for both of these actions. `POST
/api/users/{telegramUserId}/credits/grant` (admin/routers/credits.py:90, :177) sits behind
`CREDIT_GRANT_WRITE` on the router and a step-up re-authentication in the handler (:216-224),
writing its audit row inside the same transaction as the ledger row (:227). `POST
/api/users/{telegramUserId}/block` and `…/unblock` (users.py:173-174, :522, :531) sit behind
`USER_BLOCK_WRITE` on their own router (users.py:517-520) and a `USER_BLOCK` step-up in the
shared handler body, which writes the `users` row and a `USER_BLOCK` / `USER_UNBLOCK` audit
row in one transaction (users.py:575-588, :597-600). Both routers are registered on the app
(app.py:85, :411). The `tools/__init__.py` docstring claiming the panel "has authentication
and health and nothing else" predates both of them. Prefer the panel for *either* action
where an operator has one: it is the path that is audited in the database rather than in a
log line, and for a block that difference is the whole of the attribution.

### Bot identity: `python -m hbd.tools.identity show|set`

```bash
HBD_ENV_FILE=<bot env file> .venv/bin/python -m hbd.tools.identity show
HBD_ENV_FILE=<bot env file> .venv/bin/python -m hbd.tools.identity show --language-code ru
```

```
@<bot username> (<bot id>), locale: default
  name:              'HBD Bot'
  short description: '…'
  description:       '…'
  photo:             not readable over the Bot API — open the profile to see it
```

The locale is printed even when it is the default, because an empty translation and an empty
default look identical in the output and mean different things (identity.py:265-267).

```bash
HBD_ENV_FILE=<bot env file> .venv/bin/python -m hbd.tools.identity set \
  --name 'HBD Bot' --short-description 'Personalised birthday songs'
```

> **`set` is four Bot API calls and no transaction.** A failure on the third leaves the first
> two applied, so the refusal names what actually landed:
> `Telegram refused: … Applied before it did: name, description.` (identity.py:277-307,
> message at :306). Re-run with only the flags that did not apply. `--photo` with
> `--language-code` is refused outright, because a bot has one picture for every locale
> (identity.py:237-241), and a non-JPEG is refused with the `sips` invocation that fixes it
> rather than being sent to Telegram to earn a generic 400 (identity.py:183-198).

---

## Credits and entitlements

`credit_accounts.balance` is a deliberate second representation of `SUM(credit_ledger.delta)`.
Both are written in one transaction, and `verify_balances` exists because that makes drift
*detectable* rather than impossible — a hand-written `UPDATE` can still desynchronise them
(db/credits.py:43-46). It is the one query to run after any restore, any manual repair, and
any incident that touched the money tables. It takes no lock and writes nothing
(db/credit_sql.py:667-690); an empty tuple is the only healthy answer.

```bash
cd <checkout>
HBD_ENV_FILE=<bot env file> .venv/bin/python - <<'PY'
import asyncio
from hbd.config import build_settings
from hbd.db import create_engine, create_session_factory, verify_balances

async def main() -> None:
    engine = create_engine(build_settings(require_vendor_secrets=False).database_url)
    try:
        async with create_session_factory(engine)() as session:
            drifts = await verify_balances(session)
        print(drifts or "no drift")
    finally:
        await engine.dispose()

asyncio.run(main())
PY
```

Open debits — a credit charged for a render that never came back — are not an operator task.
`settle_stale_debits` closes them, and it runs *inside* the hourly retention purge's
transaction (db/purge.py:376-378, the function at db/credit_settlement.py:203-222). It is
the backstop for the things `settle` cannot cover: a worker that was SIGKILLed, an order
whose enqueue never happened, a settlement the database refused. An order the pipeline
finished is CONSUMED; everything else is REFUNDED. This is the reason a Redis wipe is a
support incident rather than a financial one — but only while the worker is running, because
that sweep is the only thing that closes them.

> **The meter can be dark while the checkout is live, and it is a warning, not a refusal.**
> When purchases are wired and `HBD_CREDITS_ENFORCED` is false, the bot logs
> `the checkout is wired but the credit meter is dark` at WARNING on every start
> (main.py:177-189). The symptom is silent and expensive: the customer is shown a price and
> charged, and the worker then covers the shortfall with an `UNENFORCED_RENDER` grant anyway,
> so the render happens whether or not the payment did. `credits_enforced` ships `false`
> (config.py:494-497). Whether a given deployment has turned it on is not knowable from the
> repository — that one boot line is where the answer is.

`HBD_FREE_ALLOWANCE_CREDITS` ships `0`, and the 0 is a product decision rather than a cautious
default: the free half of this product is the lyric, the recording is what is sold, and a
non-zero allowance hides the price screen until it is spent (config.py:505-534). The admin
panel mirrors this value as `HBD_ADMIN_FREE_ALLOWANCE_CREDITS` and **must be moved with it** —
the same comment records that while the panel defaulted the allowance instead of mirroring
it, it added 3 credits to every account forever, permanently, because a 0 allowance never
stamps an allowance period and so never stops being due (config.py:516-524).

---

## The scheduled jobs

Three ARQ cron entries exist, all of them registered on the **worker** and nowhere else
(runtime/jobs.py:705-768). Their minutes are staggered on purpose — a scheduled job has no
cause to queue behind everything else in the world that fires on the hour, and the three
must not contend for the same database at the same instant.

| Job | When (UTC) | Timeout | How to tell it ran |
| --- | --- | --- | --- |
| `run_retention_sweep` | hourly at `:17` | `HBD_QUEUE_JOB_TIMEOUT_S` (900s) | a `purge_runs` row; `GET /api/retention`; log `retention sweep finished` |
| `poll_vendor_balances` | hourly at `:43` | `HBD_VENDOR_BALANCE_JOB_TIMEOUT_S` (60s) | `vendor_balances.fetched_at`; log `vendor balance poll finished` |
| `record_activity_snapshot` | daily at `00:07` | `HBD_QUEUE_JOB_TIMEOUT_S` (900s) | a `user_activity_snapshots` row; log `activity snapshot recorded` |

All three are `run_at_startup=False`, `unique=True`, `max_tries=1` (jobs.py:706-768).
`unique=True` keeps a multi-worker deployment to one run per window. `max_tries=1` means the
next window *is* the retry, which is safe here for reasons written down per job: the balance
failure is on the row either way with its error code, and the snapshot's unique constraint on
`snapshot_date` makes a duplicate harmless.

> **A cold-started worker runs no cron until the next window.** `run_at_startup=False` was
> chosen over closing that gap, and the comment says why: a startup invocation is in no cron
> window, so `unique` does not deduplicate it, and a three-replica rolling deploy would fire
> three authenticated vendor probes at once — a rate-limit ban on the credential the pipeline
> depends on costs more than an hour of a stale cached number (jobs.py:731-738). So a worker
> restarted at 12:05 shows "not polled" for 38 minutes by design, and the first activity
> snapshot after a cold start can be up to 24 hours away.

> **None of the three binds a correlation id, so every line they emit carries
> `correlation_id: "-"`.** The scope is opened in five places and none of them is a cron job:
> the kit job (runtime/jobs.py:572), the pipeline orchestrator (pipeline/orchestrator.py:315),
> inbound bot updates (bot/middleware.py:112), and — for *every* HTTP request — the admin
> API's correlation middleware (admin/middleware/correlation.py:73) and its unhandled-exception
> middleware (admin/middleware/unhandled.py:89). Outside a scope the default is `"-"`
> (logging.py:115). A failed sweep cannot be joined to anything by id — find it by timestamp
> and message. Do not invert this into a log rule: `correlation_id: "-"` means "emitted
> outside any of those five scopes", not "cron output" — admin request lines all carry a real
> id (see *Named events*, below).

### Retention and purge

One hourly job drives fourteen sweeps and a chain-anchor pin in **one** database
transaction (db/purge.py:342-378): assets, brief notes, brief identities, attempt identities, attempt transcripts, name records,
abandoned drafts, the three admin clocks, the audit head anchor, `purge_runs`, `vendor_usage`,
`bot_membership_events`, and `settle_stale_debits` last of all. Each sweep is bounded at 500
rows per table per run (`DEFAULT_PURGE_BATCH_SIZE`, db/purge.py:170) — 12 000 a day per table.

Retention is *stamped, not computed*: every write site stores an `expires_at` from the policy
and the sweep only ever asks "is `expires_at` in the past" (db/retention.py:1-18, :102-105).
Changing a period therefore changes new rows only, and a restored backup carries its own
stamps.

Reading the result, in order of preference:

```
GET /api/retention        # the last N purge_runs rows, newest first, plus what is due now
```

(admin/routers/retention.py:49, `RETENTION_PATH = "/api/retention"`, guarded by
`RETENTION_READ` which §12.2 grants to all four roles.) The three numbers that matter on a row:

* `is_batch_full` — true when any sweep hit 500. This is the "run me again" signal, and the
  only thing that says the sweep is not keeping up (db/models/purge_run.py:110-111).
* `error_code` — set when the purge returned `Err`. The row is still written for a failed
  sweep, deliberately, because no row at all is indistinguishable from a scheduler that
  stopped firing (retention_job.py:28-30, db/models/purge_run.py:113-115).
* `storage_keys_returned` vs `storage_keys_deleted` — the second below the first means bytes
  were orphaned in the archive (db/models/purge_run.py:102-105). The purge deliberately does
  not delete objects itself; it hands back keys and the job deletes them after the commit, so
  a crash leaves recoverable orphaned bytes rather than a row pointing at bytes that are gone
  (db/purge.py:92-97). Every failed delete is logged individually with its key, because the
  key is the only handle an operator has for a manual sweep (retention_job.py:125-157).

> **The job's own docstring is stale about that last pair, in the direction that matters.**
> `retention_job.py:32-36` still says nothing writes `assets.storage_key` yet, so the storage leg is
> "an honest zero". That is no longer true: `db/repository.py:383` writes
> `storage_key=archive_key(kit.order_id, asset.path.name)` for every asset row, and
> `db/purge.py:601-613` reconstructs the key for rows written before that fix. A zero in
> `storageKeysDeleted` today means either nothing expired or the deletes are failing — not
> "the column is not written yet".

The log lines, none of which carry an `event` field, so match on the message:

```
retention purge complete            # db/purge.py:403 — the per-table counts, keys excluded
retention sweep finished            # retention_job.py:267 — the job's summary
the retention purge failed          # retention_job.py:280 — ERROR; a row is still written
an expired object could not be deleted from storage   # retention_job.py:151 — ERROR, one per key
```

> **There is no way to trigger a sweep on demand.** `POST /api/retention/run` is described in
> two docstrings (admin/routers/retention.py:10, retention_job.py:66) and does not exist:
> the only route on that router is the `GET` (retention.py:59), and the only enqueuer of
> `RETENTION_JOB_NAME` is the cron entry (jobs.py:708). If the hourly sweep stops, the
> recovery is to get the worker running and wait for `:17`, and an erasure request's purge
> cannot be expedited.

### Vendor balance probes

The entry is registered unconditionally but the job no-ops in two cases, and reports which:
`{"skipped": "fake_providers"}` under `HBD_USE_FAKE_PROVIDERS`, and
`{"skipped": "poll_disabled"}` when `HBD_VENDOR_BALANCE_POLL_ENABLED` is off
(vendor_balance_job.py:318-323, the two reasons named separately at :124-129 because "this
deployment contacts no vendor" and "this one surface is switched off" are different operator
decisions). A successful run logs `vendor balance poll finished` with `polled`, `succeeded`,
`failed`, `estimated` and `duration_ms` (vendor_balance_job.py:352).

**One OpenRouter account may cost two requests, and only one of them can fail loudly.** When
`HBD_OPENROUTER_MANAGEMENT_KEY` is set (D13) and `GET /api/v1/key` came back with no cap, the
probe also asks `GET /api/v1/credits` for the account's prepaid pool — the figure the panel
draws its balance RING against. That second call is deliberately not a probe: a refusal (a
revoked or rotated management key answers 401), an outage, an unreadable body or a renamed
field all leave the `/key` reading exactly as it was, so the run still counts as `succeeded`
and the row still carries its uncapped figure. **The operator-visible symptom of a dead
management key is therefore a pill that goes back to a dashed ring and the word `uncapped` —
never a failed poll and never an alert.** `duration_ms` roughly doubling for one account is
the other tell. The key is spent only on the primary account; a capped key never triggers the
second call at all.

> **The panel's balance tiles read "not polled" in three different situations** — a skipped
> run, a failed probe, and a worker that is simply not running — and the tile cannot tell
> them apart. The row carries `fetched_at`, so its age is never hidden; that timestamp is
> the thing to look at.

### Activity snapshots

Once a day just after midnight UTC, because the row *is* a daily sample. A night the worker
was down produces **no row and no backfill**, and that is the design: yesterday's
`last_seen_at` values no longer exist to be counted, and a zero-filled gap would be a false
measurement wearing a chart line (activity_job.py:19-25). Re-running the same day is
idempotent in the database rather than in a branch, so a worker restarted at 06:00 does not
re-anchor the day's sample by six hours; the job reports which of the two happened
(activity_job.py:27-33; the three lines at :167-173):

```
activity snapshot recorded                              # a night's work
activity snapshot for this day was already recorded     # a restart — INFO, deliberately not a warning
activity snapshot finished with no row                  # WARNING, carries the failure
```

The series also cannot be seeded. `active_30d_accounts` is honestly bounded by deployment age
for its first thirty days — a ramp that looks like growth and is not.

> **A worker that is down degrades three things silently and none of them raise.** Retention
> sweeps stop, which is a stated legal obligation; the audit chain's HEAD anchor stops being
> re-pinned, so tail deletions become undetectable while `/audit/verify` still reports
> `ok: true`; and the activity series accrues a permanent gap. No other actor covers any of
> them, and neither the bot nor the worker exposes an HTTP probe — the only two health
> endpoints in the tree are on the admin API (admin/routers/health.py:121-138). Supervision of
> the bot and the worker can only be process-level.

---

## Verifying the audit chain

```
GET /api/audit/verify
```

(admin/routers/audit.py:62, `VERIFY_PATH = "/api/audit/verify"`, behind `AUDIT_READ`.) It
writes nothing at all — not even a fresh anchor — because a write behind a `GET` is what a
browser prefetch triggers (audit.py:1-7). The response carries seven fields
(audit.py:179-187): `ok`, `firstBreakSeq`, `chainProtection`, `checkedRows`, `lastSeq`,
`isComplete`, `truncationPoints`.

It detects three distinct attacks, not one (db/admin/audit.py:603-607): a **mutated** row
breaks its own MAC; a **prefix** excision leaves a survivor whose `prev_hmac` no truncation
anchor accounts for; a **tail** excision leaves a head below the newest HEAD anchor. Only the
first of those was caught by the older design, which meant an attacker who deleted rows
rather than editing them got a green badge. A failed verification logs
`admin.audit.chain_broken` at ERROR with the breaking `seq` (audit.py:174) — this is one of
the two events worth paging on.

**Read `ok` and `isComplete` together.** The walk is bounded at 50 000 rows in batches of 500
(db/admin/audit.py:129-132); past the ceiling it returns `isComplete: false` and suppresses
the tail check, so `ok` then reflects only the prefix it checked (audit.py:647-657). On a
mature deployment `ok: true, isComplete: false` is *not* a verified log.

**`chainProtection` is asked of Postgres, not read from configuration.**
`resolve_chain_protection` runs
`has_table_privilege(current_user, 'admin_audit_log', 'UPDATE'/'DELETE'/'TRUNCATE')` and
returns `hmac-only` — with a WARNING, `admin.audit.revoke_missing` — when the answer is yes
(db/admin/audit.py:746-780). So `revoke+hmac` is claimed only when the database says the
connecting role really cannot rewrite the log. `hmac-only` is returned in four situations:
`HBD_ADMIN_AUDIT_DSN` unset, a non-Postgres backend, the probe erroring
(`admin.audit.privilege_probe_failed`), or the role still being writable.

> **`hmac-only` is the likely answer on any deployment that followed the written install
> steps, and this is a code prediction, not an observation.** Migration `0007` reads its
> preconditions from `os.environ` **only** — the audit DSN at
> `migrations/versions/20260830_1000_0007_add_admin_audit_log.py:336`, the role name at
> :314-322 — while `HBD_ADMIN_AUDIT_DSN` is documented as living in the admin dotenv file
> (.env.admin.example:130), which the migration runner never parses. `deploy/first-install-proposal.md:112`
> (a same-day proposal written without host access, not a record of any live host) exports
> only `HBD_ENV_FILE`. Under that invocation `_install_two_role_controls` takes its first
> skip branch, logs a WARNING, and neither the `REVOKE` nor the two `SECURITY DEFINER` purge
> functions are created. Note that `migrations/env.py:96-114` *does* fall back to the dotenv
> file for `HBD_DB_MIGRATION_URL`, and env.py:14-19 explains that the environment-only version
> of exactly this read was a bug — the fix was not carried across to the migration bodies. To
> install the control, export both variables into the shell that runs alembic:
>
> ```bash
> HBD_ADMIN_AUDIT_DSN='<owner dsn>' HBD_DB_APP_ROLE=hbd_app HBD_ENV_FILE=<bot env file> \
>   .venv/bin/python -m alembic -c migrations/alembic.ini upgrade head
> ```
>
> `HBD_DB_APP_ROLE` (0007:69) appears in neither example file, so an operator has no way to
> discover it exists. Whether either was ever exported on a given host is unknowable here;
> `/api/audit/verify` and `\dp admin_audit_log` are the two things that answer it.

**The undetectable tail window is one sweep interval wide.** HEAD and TRUNCATION anchors are
written by the retention job, not by the verifier: `pin_audit_head` deletes every prior HEAD
anchor and writes one (db/purge_admin.py:198-215), inside the hourly purge transaction
(db/purge.py:365). Its docstring states the limit rather than papering over it: rows written
since the last pin can still be excised without `/audit/verify` noticing. Every anchor write
logs `admin.audit.anchor` with its kind, seq and hash (db/admin/audit.py:684-693) — that log
line is the full history of pins, since only the newest row is kept.

> **The HMAC has no key identifier.** The MAC is
> `HMAC-SHA256(key, "v1" ‖ prev_hmac ‖ canonical_json(row))` with `CHAIN_VERSION` a module
> constant (db/admin/audit.py:10-12) and no key-id column on the row
> (db/models/admin_audit.py:131-197). Rotating `HBD_ADMIN_AUDIT_HMAC_KEY` is therefore
> indistinguishable from tampering across the whole 730-day log: change it and `/audit/verify`
> reports a break at the first row for ever; lose it and the log is permanently unverifiable.
> There is no rotation path in the code. Treat the key as a write-once secret and back it up
> where the database is not.

---

## Reading the logs

Every process installs the same root handler, and the format switch is `HBD_IS_DEBUG`, not the
level: `configure_logging(level=settings.log_level, is_json=not settings.is_debug)` at
main.py:220, worker.py:36 and admin/app.py:314.

> **Turning on `HBD_IS_DEBUG` to get more detail silently switches the whole stream to
> unparseable plain text** (`%(asctime)s %(levelname)s [%(correlation_id)s] %(name)s:
> %(message)s`, logging.py:233-235) — which will break a shipper's parsing rules at the worst
> possible moment. Raise `HBD_LOG_LEVEL` instead; it does not change the format.

The JSON line is a fixed five-key envelope plus two conditional keys (logging.py:200-220):

```json
{"ts": "...", "level": "INFO", "logger": "hbd.runtime.retention_job",
 "message": "retention sweep finished", "correlation_id": "-",
 "context": {"trigger": "cron", "rows_affected": 0, "is_batch_full": false}}
```

`context` holds every `extra=` field, redacted; `exception` and `error` appear when an
exception was passed. **The `event` name, where there is one, lives inside `context`** — a
query must be `context.event`, never a top-level `event`, and `message` is the human sentence
rather than a stable code.

A privacy control worth knowing about before someone "fixes" it: `sqlalchemy`,
`sqlalchemy.engine`, `aiogram`, `arq`, `uvicorn.access` and six others are floored at WARNING
no matter how low the root goes (logging.py:99-112, applied at :246-248). At DEBUG the ORM
echoes bound parameters — recipient names, notes, approved lyrics, STT transcripts — into a
stream that has no retention clock and that neither `hbd.db.purge` nor a per-user erasure can
reach. The admin process additionally *refuses to boot* at DEBUG in prod
(admin/settings.py:589-593); the bot and the worker have no such refusal, and `configure_logging`
is the whole mitigation there.

### Named events worth an alert rule

Only the admin subsystem emits a machine-readable `event`; everything else in the tree is
prose. The table below is the set worth an alert rule, not the whole set — the tree currently
carries 45 distinct strings, and the authoritative list is
`grep -rhoE '"event": "[a-z_.]+"' src/hbd/admin/ | sort -u`. Grep `context.event`.

| Event | Where | Level | Means |
| --- | --- | --- | --- |
| `admin.audit.chain_broken` | routers/audit.py:174 | ERROR | the log does not verify — page |
| `admin.audit.revoke_missing` | db/admin/audit.py:777 | WARNING | the DSN says two roles; Postgres says the app role can still rewrite the log |
| `admin.audit.privilege_probe_failed` | db/admin/audit.py:771 | WARNING | could not ask; reporting the weaker guarantee |
| `admin.audit.write_failed` | audit_sink.py:111 | ERROR | an action happened and was not audited |
| `admin.audit.value_refused` | audit_sink.py:127, services/assets.py:483 | ERROR | a value could not be stored; the row was retried scrubbed |
| `admin.audit.secret_refused` | db/admin/audit.py:265 | ERROR | something tried to put a secret in the log |
| `admin.audit.anchor` | db/admin/audit.py:687 | INFO | a HEAD or TRUNCATION anchor was written — the only history of pins |
| `admin.boot.ok` | app.py:325 | INFO | the panel started; carries `environment`, `env_file`, `is_cookie_secure`, `public_origin` |
| `admin.boot.vendor_env_present` | app.py:202 | WARNING | a vendor credential is within the panel's reach (a refusal in prod, this line elsewhere) |
| `admin.boot.env_file_unreadable` | app.py:168 | WARNING | the credential scan could not read the dotenv file it was told to |
| `admin.spa.nonce_placeholder_missing` | shell.py:83 | WARNING | the deployed console bundle predates the CSP nonce placeholder; rebuild it |
| `admin.session.mirror_invalidation_failed` | sessions.py:264 | WARNING | a revoked session may survive until its mirror expires |
| `admin.session.mirror_write_failed` / `.mirror_unavailable` / `.mirror_undecodable` | sessions.py:245 / :213 / :195 | WARNING | the session mirror is not answering or not decodable; the panel falls back to the database and gets slower, not wrong |
| `admin.ratelimit.store_unavailable` | ratelimit.py:340 | WARNING | Redis is gone and logins are being denied, not allowed |
| `admin.ratelimit.username_tripped` | ratelimit.py:370 | WARNING | one username's credential ceiling tripped across addresses — the targeting signal; carries `admin_username`, `attempts_in_window`, `window_s` |
| `admin.ratelimit.refund_failed` | ratelimit.py:559 | ERROR | a successful re-auth's reservation could not be refunded; it stands until it expires |
| `admin.reveal.budget_store_unavailable` | budget.py:241 | WARNING | same, for reveals |
| `admin.csrf.refused` | deps.py:233 | WARNING | `ORIGIN_REJECTED` — usually a wrong `HBD_ADMIN_PUBLIC_ORIGIN` |
| `admin.rbac.refused` | deps.py:436 | WARNING | a permission check said no |
| `admin.rbac.missing_subject` | security/permissions.py:586 | ERROR | a step-up permission was checked with no subject id; denied as `STEP_UP_REQUIRED` — a coding fault, not an operator one |
| `admin.stepup.refused` / `.granted` | deps.py:546 / auth.py:719 | WARNING / INFO | re-authentication for a sensitive cell |
| `admin.login.ok` / `.origin_refused` | auth.py:527 / :188 | INFO / WARNING | sign-in outcomes |
| `admin.password.changed` / `.refused` | auth.py:650 / :298 | INFO / WARNING | password changes |
| `admin.password.hash_unusable` | security/passwords.py:155 | WARNING | a stored hash cannot be verified |
| `admin.request` | logging_mw.py:77 | INFO / ERROR | one line per request: `method`, `route`, `status`, `duration_ms` |
| `admin.request.unhandled` | errors.py:332 | ERROR | an exception escaped every handler |
| `admin.health.redis_unreachable` | routers/health.py:66 | WARNING | `/readyz` could not ping Redis |
| `admin.health.version_unreadable` / `.version_malformed` | routers/health.py:78 / :88 | WARNING | the live settings version could not be read, or is not an integer; health reports no version |
| `admin.container.built` / `.redis_close_failed` | container.py:132 / :109 | INFO / WARNING | admin container lifecycle |
| `admin.asset.*`, `admin.reveal.*`, `admin.wizard_state.*`, `admin.retryability.ambiguous` | services/assets.py, services/reveal.py, wizard_state.py, serializers/retryability.py | mixed | per-surface refusals and store outages |

`admin.request` records the **route template**, never the raw path, and an unrouted request as
the constant `<unmatched>` (logging_mw.py:31-33, :74-93). Redaction matches on the extra
*key*, so a `?token=…` in a path would sail through it — which is why the raw path is not
logged at all. An operator cannot recover the order id or query string of a specific request
from the log; only the template, status, duration and correlation id.

> **One `event` key in the tree is not a dotted name.** `bot/handlers/membership.py:126,131`
> passes `event="blocked"` / `"unblocked"` as an ordinary extra. A rule matching
> `context.event` with a prefix will not be confused; one matching for existence will.

### Prose lines the rest of the fleet emits

The bot, the worker, the pipeline and the providers emit no `event` field at all — their log
calls are English sentences, so a grep there matches wording that is free to change. These are
the ones worth watching:

```
host verified                       # runtime/startup.py:33 — bot+worker boot; carries environment, env_file, ffmpeg
bot starting                        # main.py:170
worker started                      # runtime/jobs.py:671 — carries concurrency
worker dependencies built           # worker.py:47
the checkout is wired but the credit meter is dark   # main.py:187 — WARNING
retention purge complete            # db/purge.py:403
retention sweep finished            # retention_job.py:267
the retention purge failed          # retention_job.py:280 — ERROR
an expired object could not be deleted from storage  # retention_job.py:151 — ERROR
vendor balance poll finished        # vendor_balance_job.py:352
activity snapshot recorded          # activity_job.py:169
an operator changed an account's block               # tools/credits.py:281
an operator changed the bot's profile                # tools/identity.py:309
database ping failed                # db/engine.py:109
```

> **`host verified` is two words, and a documented check greps for one.**
> `deploy/first-install-proposal.md:143` — a proposal authored without host access, not a record — tells the
> operator to `grep host_verified`. The message is `"host verified"` with a space
> (runtime/startup.py:34) and there is no `host_verified` token anywhere in the tree, so that
> check matches nothing on a perfectly healthy boot. The line beside it,
> `grep admin.boot.ok`, does work, because that one really is an `event` field (app.py:325).

The only machine-shaped strings outside the admin package are fourteen `audio.*` names used as
the *message* rather than as an event field — `audio.startup.ready` (audio/startup.py:105),
`audio.subprocess.ok` (audio/runner.py:125), `audio.loudnorm.*` (audio/processor.py:315,:320),
`audio.cover.render_failed` (audio/cover.py:122) and the rest. They match on `message`, not on
`context.event`, so a rule written for the admin namespace misses them.

---

## Backup and restore

**Nothing in this repository backs anything up.** There is no `pg_dump`, no dump target, no
snapshot script, and no backup step in the deploy proposal: a grep for `pg_dump` across
`README.md`, `Makefile`, `deploy/` and `docs/` returns nothing at all. Every retention
argument in this codebase is about deletion being the risk; loss is unaddressed. Whether
anything outside the repository takes backups is not knowable here.

### What must be in a backup for it to be sufficient

Four things, and three of them are not the database.

1. **Postgres, in full.** Twenty-one mapped tables plus `alembic_version`. The ones that make a partial dump insufficient
   are `credit_ledger` (the only explanation of every balance), `plan_purchases` and
   `topup_purchases` — receipts that answer a payment dispute months after the recipient's
   name, the note and the audio are lawfully gone — and `admin_audit_log` with
   `audit_chain_anchors`, which are meaningless apart from one another.
2. **`<data root>/archive`.** One object-store root holding two key namespaces with different
   lifecycles: `orders/{order_id}/{filename}` for delivered assets (storage.py:73-84), swept on
   the asset clock, and `users/{user_id}/avatar.jpg` for customer profile photos
   (user_profiles.py:199-200), which is on **no** clock and is deleted only by `/forget`. They
   share one `LocalFileStorage` deliberately (runtime/container.py:306-311), so they cannot be
   scoped separately at the filesystem level: a backup of the archive is a backup of both
   delivered songs and customers' photographs.
3. **Redis.** It is not a disposable cache here. It holds the only copy of every in-progress
   wizard draft — recipient name, free-text note, full approved lyric — under a 14-day TTL
   matched to the abandoned-draft retention clock (bot/app.py:44-48, :83-85), plus the ARQ
   queue, job results, admin session mirrors and every rate-limit and budget counter. Losing
   it parks every customer mid-wizard and drops every queued render; it does **not** lose money
   state, because the hourly sweep closes the open debits (db/purge.py:376-378).
4. **`HBD_ADMIN_AUDIT_HMAC_KEY`.** It lives in the admin dotenv file and nowhere else — a
   `SecretStr` with `min_length=32` on `AdminSettings` (admin/settings.py:229) — and it is not
   in the database. A database-only restore comes back with an audit log nobody can verify.

> **Back the key up somewhere the database is not.** A backup that contains both the
> `admin_audit_log` table and the key that authenticates it is a backup an insider can rewrite
> end to end: the chain is recomputable by anyone holding the key. Storing them in one place
> defeats the only control that survives a compromised application credential.

### After a restore

The order matters, because each step tells you something the next one assumes.

```bash
# 1. Schema level. The chain is linear 0001..0021; a restore of an older dump against
#    newer code needs this before anything else touches the database.
HBD_ENV_FILE=<bot env file> \
  .venv/bin/python -m alembic -c migrations/alembic.ini upgrade head
```

> **Migrations require the vendor keys they do not use.** `migrations/env.py:129` calls
> `load_settings()` for the DSN when `HBD_DB_MIGRATION_URL` is unset, and `load_settings()`
> always requires the three vendor secrets (config.py:758-760). A migration-only host, or a CI
> step that has the DSN and no keys, fails with a message about missing API keys. Setting
> `HBD_DB_MIGRATION_URL` avoids the fallback *and* is what makes migrations run as the owner
> role; without it, `migrations/env.py` logs a WARNING naming the control that costs
> (env.py:89-93, :125-129).

```bash
# 2. Money. An empty answer is the only healthy one — see the snippet above.
#    Run it before anyone is let back in: a drift found now is a data question, a drift
#    found after the bot is live is a data question tangled up with new writes.
```

```
# 3. The log. Open the panel and read GET /api/audit/verify.
#    ok:true, isComplete:true            -> the chain holds as far as the ceiling allows
#    ok:false, firstBreakSeq:1           -> almost always the wrong HMAC key, not tampering
#    chainProtection: "hmac-only"        -> the REVOKE is not in force on this database
```

**Treat a restored database as having no grants until `chainProtection` says otherwise.**
Whether the `0007` REVOKE and the `ALTER DEFAULT PRIVILEGES` from the migrations survive a
restore is not knowable from this repository: `pg_dump` can emit ACL and default-privilege
statements, so the answer depends on the dump flags (`--no-acl`, data-only, `--section=…`), on
whether the app role even exists in the target cluster, and on how the restore is driven —
and, as two paragraphs above, no backup or restore mechanism exists in this tree to read those
choices off. So do not infer the grant state; observe it. If the two-role split is meant to be
in place, re-run migrations with `HBD_ADMIN_AUDIT_DSN` and `HBD_DB_APP_ROLE` exported (above)
and confirm with `chainProtection` rather than with the fact that the command exited zero. The
migrations are the only grant statements this repository owns, and re-running them is
idempotent, so this costs nothing when the grants did survive.

> **Open question (not answerable here).** Whichever mechanism actually takes and restores
> these dumps — none of it is in the repository, and nobody in this workflow can inspect the
> host — decides whether roles and ACLs come back with the data. Someone with access should
> write down the dump and restore commands; until then the `chainProtection` check above is
> the only evidence, and this document asserts nothing about what a restore preserves.

```
# 4. The archive. Rows and bytes are backed up by two different mechanisms and can be
#    restored to two different points in time.
```

A database newer than the archive gives asset rows whose objects are missing — the panel
reports that honestly and the retention sweep's delete becomes a no-op. An archive newer than
the database gives orphaned bytes that no sweep will ever reach, because the row carrying the
key is the only thing that would have returned it (db/purge.py:553-593). Neither is corruption;
both are silent.

> **`<data root>/workspace` is in no backup discussion because it is in no lifecycle at all.**
> Nothing in the repository ever deletes it: a repo-wide grep for `rmtree`, `.unlink(` and
> `os.remove` under `src/` returns two hits, a failed atomic write (storage.py:339) and a
> per-call scratch directory (audio/tempfiles.py:44), neither of which touches a published
> workspace file. Per-order directories are deterministic (`pipeline/assembly.py:54-56`), so
> every song, greeting, cover and lyric sheet exists there a second time, past every clock in
> `RetentionPolicy`. That is a growth problem and a privacy problem, and whether any host-level
> sweep has ever addressed it is not something this repository can say.

Finally, retention stamps come back with the rows. `expires_at` is whatever the policy was when
each row was written (db/retention.py:1-18), so restoring a year-old dump restores a year-old
schedule, and the first sweep after the restore will delete everything that fell due in the
meantime — in bounded batches of 500 per table per hour, which for a large gap means
`is_batch_full` stays true for a while. That is the sweep working, not failing.
