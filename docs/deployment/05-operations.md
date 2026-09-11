# Day-2 operations

Everything below is derived from the working tree and cites the file and line it comes from,
so a reader who doubts a sentence can check it in a minute. Wherever a command needs a host
fact it is written with a placeholder, and wherever a runbook's answer depends on one, the
dependency is stated rather than guessed.

**What has changed since this page was written: the host is now reachable, read-only.** The
repository-only claims below are unchanged and still carry their `file.py:line`. Beside them,
host observations now appear marked with their date and method, because an operator at 2 a.m.
needs both halves and needs to know which is which:

| Marker | What it promises |
| --- | --- |
| *(unmarked)* | A claim about this repository's code. Open the cited file. |
| `[HOST 2026-09-10]` / `[HOST 2026-09-11]` | A read-only command was run against `aizu` (machine `abdu-test`) on that date and the quote is faithful to its output. |
| `[UNPROVEN]` | Nobody has established it, and the blocker is named. Preferred here over a confident guess, every time. |

> **THE HOST IS PRE-RENAME AND THAT IS CORRECT.** `[HOST 2026-09-10]` On `abdu-test` the
> units are `hbd-bot`, `hbd-worker`, `hbd-admin`, `hbd-payme`; the dotenv files are
> `/etc/hbd/hbd.env`, `/etc/hbd/hbd-admin.env`, `/etc/hbd/payme.env`; the virtualenv is
> `/opt/hbd/venv`; the installed distribution is `hbd_bot-0.1.0` and the importable package is
> `hbd`; every variable is prefixed `HBD_`; the database is `hbd`. This repository has been
> renamed to `bayram` throughout and **that rename has not been deployed** — the wheel that
> would do it is staged at `/opt/hbd/release/bayram_bot-0.1.0-py3-none-any.whl` beside
> `cutover-to-bayram.sh`, both dated 2026-09-10, and neither has run. So **every `python -m
> bayram.…` command on this page is typed `python -m hbd.…` at a shell on that box, and every
> `BAYRAM_` variable is `HBD_`**, until `08-payme.md` §11.6 has been executed. Do not
> "correct" a host name to `bayram`; do not quote a `bayram` path as though it existed there.
>
> One command settles which prefix is live on a host whose history you do not know:
>
> ```bash
> ssh aizu 'systemctl list-units --type=service --all "hbd-*" "bayram-*" | cat; ls -d /opt/*/venv'
> ```

### Reading a log line on this host, which is the prerequisite for half this page

`[HOST 2026-09-11]` Every grep below is written `... | grep <something>` because the
repository cannot know what collects a process's stdout. On `abdu-test` the answer is
**systemd's journal and nothing else**, and `developer` is in `adm`, so no `sudo` is needed:

```bash
ssh aizu 'journalctl -u hbd-admin  -o cat | grep admin.boot.ok'
ssh aizu 'journalctl -u hbd-worker -o cat | grep "retention sweep finished"'
ssh aizu 'journalctl -u hbd-payme  -o cat | grep payme.boot.ok'
```

`-o cat` is what strips systemd's own prefix and leaves the application's JSON line intact.

> **Do not pipe `journalctl -u hbd-worker` into `jq`: every other line is not JSON.**
> `[HOST 2026-09-11]` The worker's journal carries each arq line **twice** — once as arq's own
> plain text, once inside our envelope:
>
> ```
> 09:00:00:   1.00s → run_payme_sweep()
> {"ts": "2026-09-11T09:00:00+0500", "level": "INFO", "logger": "arq.worker",
>  "message": "  1.00s → run_payme_sweep()", "correlation_id": "-"}
> ```
>
> The mechanism is checkable in the venv and is not a misconfiguration anyone can fix from a
> dotenv file: `arq/logs.py:default_log_config` returns a handler `arq.standard` with the
> format `%(asctime)s: %(message)s` and sets logger `arq` to INFO, and `arq/cli.py:44-45`
> applies it through `logging.config.dictConfig` **after** `bayram.worker`'s module-scope
> `configure_logging()` has already run. So the `_NOISY_LOGGERS` WARNING floor that pins `arq`
> (logging.py:100-113, applied at :247-248) is overwritten on the real invocation, and
> propagation hands the record to both handlers. The `hbd-payme` journal likewise carries
> uvicorn's plain `INFO:     Started server process […]` lines — 42 of them. Filter with
> `grep '^{'` before `jq`, or match on `message` instead.

### The host as it stood on 2026-09-11, in one block

`[HOST 2026-09-11]` Not a substitute for `00-host-inventory.md`, which wins wherever it
disagrees — just enough state to read the rest of this page against. All of it is read-only and
the whole block re-runs in about ten seconds.

```console
$ ssh aizu 'for u in hbd-bot hbd-worker hbd-admin hbd-payme; do \
    printf "%s %s %s\n" $u $(systemctl is-active $u) $(systemctl is-enabled $u); done'
hbd-bot active enabled          # PID 193451, NRestarts=0, started Fri 2026-09-11 06:50:13 +05
hbd-worker active enabled       # PID 193447, NRestarts=0
hbd-admin active enabled        # PID 193438, NRestarts=0
hbd-payme active enabled        # PID 193442, NRestarts=0

$ ssh aizu 'curl -s http://127.0.0.1:8080/readyz; curl -s http://127.0.0.1:8091/readyz'
{"status":"ok"}{"status":"ok"}        # the CONSTANT, from both. Proves reachability, not health — 06 §9
$ ssh aizu 'redis-cli ping; redis-cli dbsize; df -h / | tail -1'
PONG
4
/dev/mapper/ubuntu--vg-ubuntu--lv  38G  7.2G  28G  21% /
$ ssh aizu 'ffmpeg -hide_banner -encoders | grep -E "libopus|libmp3lame"'
 A....D libmp3lame  …        # BOTH present. 06 §10's "check libmp3lame by hand" is now checked
 A....D libopus     …
```

Four processes, all healthy, all restarted together this morning, on a box that is 21 % full.
The admin panel's connection pool is **5**, not the 10 an older arithmetic assumed:
`{"event": "admin.container.built", "environment": "prod", "pool_size": 5, "database":
"127.0.0.1:5432/hbd"}`.

## How to run any of these commands

There is no installed console script for anything in this project — `pyproject.toml` has no
`[project.scripts]` table at all — so every entry point is `python -m`, and the interpreter
has to be named. The Makefile is the reference spelling: `.venv/bin/python -m bayram.main`
(Makefile:69), `-m arq bayram.worker.WorkerSettings` (Makefile:72),
`-m uvicorn bayram.admin.app:app` (Makefile:75).

Two things decide what an operator command actually acts on, and both are invisible in the
command itself:

```bash
cd <checkout>                       # decides the data root, see below
BAYRAM_ENV_FILE=<the bot's env file> \
  .venv/bin/python -m bayram.tools.credits ...
BAYRAM_ADMIN_ENV_FILE=<the panel's env file> \
  .venv/bin/python -m bayram.admin.bootstrap ...
```

`bayram.admin.bootstrap` builds `AdminSettings` (bootstrap.py:319 → `build_admin_settings()`),
so it reads whatever `BAYRAM_ADMIN_ENV_FILE` names; both tools under `src/bayram/tools/` build
`Settings` (credits.py:302, identity.py:321), so they read `BAYRAM_ENV_FILE`. Point one of them
at the wrong file and it will happily do the right thing to the wrong database.

> **`cd` is a load-bearing argument.** The bot and the worker derive their data root from the
> process working directory — `root = (data_root or Path.cwd() / "var").resolve()`
> (runtime/container.py:286) — and there is no environment variable that overrides it.
> `main()` never passes one (main.py:222). The admin process uses `BAYRAM_ADMIN_DATA_ROOT`,
> whose default is the *relative* path `var` (admin/settings.py:423). The two agree only if
> the processes share a working directory. Whether they do on any given host is a deployment
> fact this repository cannot state; the symptom when they do not is that the panel's media
> reveals 404 while the database row says the file exists.
>
> **On this host they agree, and the reason is one line in each unit rather than a setting.**
> `[HOST 2026-09-11]` All four units carry `WorkingDirectory=/var/lib/hbd`, and the bot's own
> boot line confirms what that derives: `container built` → `{"workspace":
> "/var/lib/hbd/var/workspace", "database": "127.0.0.1:5432/hbd"}`. `hbd-bot.service`'s comment
> block says exactly why the line is load-bearing — the data root comes from the working
> directory, not from a setting, so changing it moves every asset the panel expects to stream.
> An operator running one of these CLIs by hand must therefore `cd /var/lib/hbd` first, or act
> on a `var/` tree the services have never written to.

> **`env_file` on a boot line does not answer "which file did this process read" here, and it
> is the field most likely to mislead you.** `[HOST 2026-09-11]` `systemctl show <unit> -p
> Environment` is **empty** for `hbd-bot`, `hbd-worker` and `hbd-admin` — none of them sets
> `HBD_ENV_FILE` or `HBD_ADMIN_ENV_FILE` — so `resolve_env_file` falls back to the *relative*
> defaults and the boot lines print exactly that: `"env_file": ".env"` on bot and worker,
> `".env.admin"` on the panel. Nothing is wrong. Real configuration arrives through
> `EnvironmentFile=/etc/hbd/*.env` straight into `os.environ`, which the boot line does not
> report. Only the gateway names its file: `Environment=HBD_PAYME_ENV_FILE=/etc/hbd/payme.env`,
> and its boot line prints the absolute path. The consequence for a security control is in
> `07-security.md` §1 — the *file* half of the vendor-credential scan reads a path that does not
> exist and finds nothing, and only the environment half is doing any work on this host.

Both operator CLIs build settings with `require_vendor_secrets=False` (credits.py:302,
identity.py:321), so comping a customer does not require the ElevenLabs or LLM keys to be on
the box. `bayram.admin.bootstrap` needs no vendor key either — `AdminSettings` has no field that
could hold one.

---

## Operator accounts

There is no signup route. `python -m bayram.admin.bootstrap` is the only thing in the tree that
creates an operator account, and it is deliberately awkward about exactly one thing: the
password never travels through `argv`.

### The first OWNER

```bash
cd <checkout>
BAYRAM_ADMIN_ENV_FILE=<admin env file> \
  .venv/bin/python -m bayram.admin.bootstrap --username owner
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
`BAYRAM_ADMIN_ARGON2_MEMORY_KIB` high and leave the login throttle in place"
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
BAYRAM_ADMIN_ENV_FILE=<admin env file> \
  .venv/bin/python -m bayram.admin.bootstrap --username owner --password-file /tmp/pw
shred -u /tmp/pw
```

The file's contents are `.strip("\r\n")` only (bootstrap.py:134), so trailing spaces or tabs
become part of the password.

### Recovering a lost OWNER

```bash
BAYRAM_ADMIN_ENV_FILE=<admin env file> \
  .venv/bin/python -m bayram.admin.bootstrap --username owner --reset-owner
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

`0` success, `1` an operator refusal, `2` a configuration failure (`BayramError`) —
bootstrap.py:72-74, dispatched at :319-343. The same three-way contract is used by both
tools under `src/bayram/tools/` (credits.py:70-72, identity.py:62-64). A deploy script can tell
"already bootstrapped" from "the environment is wrong" without parsing English. Nothing on
any of these paths ever prints a traceback, because a traceback from a command holding a
`Settings` object would carry the DSN (bootstrap.py:319-325).

---

## The operator CLIs

`src/bayram/tools/` holds exactly two, and neither is imported by the application: "Not a
library. Nothing under `src/bayram` imports from here" (tools/\_\_init\_\_.py:1-5). They write
through the same functions the product writes through, which is the whole point — the CLI
cannot produce a row shape the ordinary path could not.

> **THERE IS A THIRD OPERATOR CLI AND IT IS NOT IN THAT DIRECTORY.** `python -m
> bayram.payme.cli` (`src/bayram/payme/cli.py`) is the Payme rail's recovery surface, and its
> own docstring calls it "on day one the ONLY one" — the panel's payments screens are deferred
> on purpose (`PAYME_INTEGRATION §8`), because `ADMIN_PANEL_PLAN` WS3–WS8 are outstanding and a
> screen built on a surface about to be rebuilt would be thrown away twice. Nine subcommands:
>
> | Verb | What it is for |
> | --- | --- |
> | `journal --ref \| --payme-id \| --since` | everything known about one payment, joined across six tables: intent, transactions, receipt, grant, RPC log |
> | `statement --from --to` | the rows `GetStatement` would return, to diff against a cabinet export |
> | `settle --ref --note` | settle by hand after a lost callback, under the intent's **own** idempotency key, so a late genuine `PerformTransaction` grants nothing twice |
> | `notify --ref` | re-enqueue the settled-payment announcement — the same ARQ enqueue the gateway makes |
> | `pause` / `resume` | stop or start opening **new** checkouts. Never refuses a payment in flight |
> | `status --hours` | the pause switch, the last inbound call, the recent funnel |
> | `invariant --hours` | the three-way settlement count; **exits 3** when it does not balance |
> | `reconcile --limit` | run the sweep's arms once, synchronously |
>
> Three things about it that differ from the two tools above and will bite otherwise.
> **(1) It builds `PaymeSettings` from `BAYRAM_PAYME_ENV_FILE`, not `BAYRAM_ENV_FILE`** — so it
> must run on the host holding the gateway's env file. `[HOST 2026-09-11]` On `abdu-test` that
> is `/etc/hbd/payme.env`, it is the one file a unit names explicitly
> (`Environment=HBD_PAYME_ENV_FILE=/etc/hbd/payme.env`), and `[UNPROVEN]` it is **not readable
> by the deploy account** — `/etc/hbd` is mode-walled, so running this CLI needs whatever
> account the service runs as. **(2) It deliberately does not check `payme_enabled`**, because
> the first thing an operator does in a payment incident is switch the rail off and a recovery
> tool that refused to run against a disabled rail would be useless exactly when needed;
> `status` reports the flag instead. **(3) Its exit codes are four, not three** — `0` done, `1`
> refused, `2` configuration or database failure, and **`3` ran and found something wrong**,
> which exists so `invariant` can be driven from a monitor. `[HOST 2026-09-11]` Nothing is
> driving it from a monitor on this host; the worker's `run_payme_sweep` is what checks the
> invariant on a schedule today, and it reports into the journal nobody reads.
>
> The runbooks each subcommand belongs to are `08-payme.md` §7 (manual refund), §8 (key
> rotation) and §9 (weekly reconciliation); `09-payme-go-live.md` §11 records which two of them
> the admin console now covers and why `settle` and `reconcile` stay in the terminal.

> **Both tools reconfigure logging on the way in, unconditionally to JSON.** `main()` calls
> `configure_logging()` with no arguments (credits.py:319, identity.py:333) and the defaults
> are `level="INFO", is_json=True` (logging.py:230). So these commands emit JSON lines on
> stdout regardless of `BAYRAM_IS_DEBUG` — which matters because for one of the two verbs below
> that line is the *only* record of what was done.

### Credits: `python -m bayram.tools.credits grant|block`

```bash
BAYRAM_ENV_FILE=<bot env file> .venv/bin/python -m bayram.tools.credits grant \
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
BAYRAM_ENV_FILE=<bot env file> .venv/bin/python -m bayram.tools.credits block \
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

### Bot identity: `python -m bayram.tools.identity show|set`

```bash
BAYRAM_ENV_FILE=<bot env file> .venv/bin/python -m bayram.tools.identity show
BAYRAM_ENV_FILE=<bot env file> .venv/bin/python -m bayram.tools.identity show --language-code ru
```

```
@<bot username> (<bot id>), locale: default
  name:              'Bayram — a song with your name in it'
  short description: '…'
  description:       '…'
  photo:             not readable over the Bot API — open the profile to see it
```

The locale is printed even when it is the default, because an empty translation and an empty
default look identical in the output and mean different things (identity.py:265-267).

```bash
BAYRAM_ENV_FILE=<bot env file> .venv/bin/python -m bayram.tools.identity set \
  --name 'Bayram — a song with your name in it' --short-description 'Personalised birthday songs'
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
BAYRAM_ENV_FILE=<bot env file> .venv/bin/python - <<'PY'
import asyncio
from bayram.config import build_settings
from bayram.db import create_engine, create_session_factory, verify_balances

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

> **That argument needs one clause added now that a real payment rail exists.** A Redis wipe is
> a support incident *on the credit side*, because the hourly sweep closes the debits. It is not
> automatically so on the **settlement** side: the money is already in `payme_transactions` and
> `topup_purchases` either way — the gateway writes those in its own transaction, not through
> Redis — but the **message telling the customer** is an ARQ job, and the only thing that
> re-enqueues a lost one is `run_payme_sweep`'s `notifications_re_enqueued` leg. So a Redis wipe
> plus a downed worker is a customer who paid, whose receipt exists, and who has been told
> nothing. `python -m bayram.payme.cli notify --ref <our reference>` is the by-hand form of that
> recovery, and `journal --ref` is how you find out which refs need it.

> **SUPERSEDED 2026-09-10 — the two cases have separated.** This box used to read "the meter
> can be dark while the checkout is live, and it is a warning, not a refusal." That is no
> longer true for a **live** rail, and the sentence is kept because the distinction is now the
> whole diagnostic.
>
> * **A LIVE rail over a dark meter is a boot refusal.** `refuse_an_unsafe_checkout_rail`
>   (main.py:114, called at :286) raises `ConfigError` before anything is built. Its docstring
>   states the reversal plainly: "This used to be a WARNING… It is not right for a rail that
>   takes real money" — the customer is charged 7 000 UZS for a song the
>   `UNENFORCED_RENDER` grant would have rendered for nothing.
> * **A STUB rail over a dark meter is still a WARNING** (main.py:380-395), because a
>   deployment that wants to give songs away must be able to.
>
> So the WARNING has become an *inference you can make*: a prod process that logs
> `the checkout is wired but the credit meter is dark` **and is still running** is telling you
> its checkout provider is the stub. If it were live it would not have booted.
>
> `[HOST 2026-09-11]` `hbd-bot` logs it at every start — seven times in the journal, most
> recently `{"credits_enforced": false}` at `2026-09-11T06:50:25+0500` — and the refusal is
> present in the installed wheel (`grep -n refuse_an_unsafe_checkout_rail
> /opt/hbd/venv/lib/python3.12/site-packages/hbd/main.py` → lines 16, 73, 114, 286, 383). The
> bot's rail on `abdu-test` is therefore the **stub**, while the Payme gateway beside it is live
> and has settled real money (`08-payme.md`, `09-payme-go-live.md` §6: a recorded owner decision
> dated 2026-09-10, not an oversight). **Do not read the gateway's first settlement as the
> paywall having been switched on — they are two switches** (`08-payme.md`, the two-switches
> note at the top). `[UNPROVEN]` The direct confirmation, `grep '^HBD_CHECKOUT_PROVIDER='
> /etc/hbd/hbd.env`, needs a password: `/etc/hbd` is `Permission denied` to `developer` and
> `sudo -n` is refused. The inference above is sound but it is an inference.
>
> `credits_enforced` ships `false` (config.py:494-497).

`BAYRAM_FREE_ALLOWANCE_CREDITS` ships `0`, and the 0 is a product decision rather than a cautious
default: the free half of this product is the lyric, the recording is what is sold, and a
non-zero allowance hides the price screen until it is spent (config.py:505-534). The admin
panel mirrors this value as `BAYRAM_ADMIN_FREE_ALLOWANCE_CREDITS` and **must be moved with it** —
the same comment records that while the panel defaulted the allowance instead of mirroring
it, it added 3 credits to every account forever, permanently, because a 0 allowance never
stamps an allowance period and so never stops being due (config.py:516-524).

---

## The scheduled jobs

> **THERE IS NO TIMER AND NO CRONTAB FOR ANYTHING IN THIS STACK. Every schedule in this
> product is the ARQ worker's own cron loop, and if the worker is down there is no second
> mechanism behind it.** `[HOST 2026-09-11]` `systemctl list-timers --all` returns 18 timers
> and **not one of them activates an `hbd-*` or `bayram-*` unit**; `crontab -l` answers "no
> crontab for developer"; `/etc/cron.d/` holds only `.placeholder`, `e2scrub_all` and
> `sysstat`. All four `hbd` units are long-running `Type=simple` services.
>
> **`aizu-backup.timer` is a decoy and you will see it first.** It is enabled and active, it
> runs nightly — `OnCalendar=*-*-* 03:30:00`, `Persistent=true`, `RandomizedDelaySec=300`,
> `User=aizu`, last fired 2026-09-11 03:31:04 +05 — and it backs up
> `/var/lib/aizu/aizu.db`, a SQLite file belonging to an **unrelated tenant**, to
> `/var/backups/aizu`, keeping 14 days (`/usr/local/bin/aizu-backup`). It touches no Postgres,
> no `hbd` archive, no Redis and no HMAC key. An operator who reads `list-timers`, sees a
> nightly backup and stops reading has drawn exactly the wrong conclusion. See *Backup and
> restore*, below.

**Five** ARQ cron entries exist, all of them registered on the **worker** and nowhere else
(runtime/jobs.py:820-963 — the five `cron(` calls are at :821, :854, :875, :909 and :951).
Their minutes are staggered on purpose — a scheduled job has no cause to queue behind
everything else in the world that fires on the hour, and five database writers must not contend
for the same instant. That is not left to care: `test_no_two_crons_in_this_worker_contend_for_
the_same_minute` collects every entry's `minute` and asserts no two collide, which is why
`sweep_due_broadcasts` sits at `:04, :09, …` rather than on the five-minute boundary the Payme
sweep already owns (the argument is in the comment at jobs.py:942-944).

> **SUPERSEDED 2026-09-10: this table used to say three jobs and a UTC schedule. Both were
> wrong.** The two five-minutely entries arrived with the Payme rail and the broadcast feature,
> and the column header was never true — **arq schedules on the system timezone, not UTC.**
> `arq/worker.py:299-300` is explicit, comment and all: `# default to system timezone` /
> `self.timezone = datetime.now().astimezone().tzinfo if timezone is None else timezone`, and a
> `grep -n timezone src/bayram/worker.py src/bayram/runtime/jobs.py` returns **nothing** — this
> project's `WorkerSettings` passes none.
>
> `[HOST 2026-09-11]` `timedatectl` reports `Time zone: Asia/Tashkent (+05, +0500)`. The hourly
> entries are unaffected, because a whole-hour offset preserves the minute. **The nightly
> snapshot is five hours from where both this page and `06` used to put it**, and it has now
> been observed twice:
>
> ```json
> {"ts": "2026-09-11T00:07:00+0500", "message": "activity snapshot recorded",
>  "context": {"snapshot_date": "2026-09-10", "taken_at": "2026-09-10T19:07:00.556797+00:00",
>              "is_written": true, "total_accounts": 5, "active_30d_accounts": 5}}
> ```
>
> So on `abdu-test` the row for 2026-09-10 was written at **19:07 UTC** of that day. An operator
> computing "the 09-10 snapshot should exist by 00:07 UTC" looks five hours early and concludes
> the job never ran. It also means the daily sample's boundary is the **host's** midnight, not
> the UTC day a dashboard chart assumes — worth one sentence to whoever reads the activity
> series.

| Job | When (host local time) | Timeout | How to tell it ran |
| --- | --- | --- | --- |
| `run_retention_sweep` | hourly at `:17` | `BAYRAM_QUEUE_JOB_TIMEOUT_S` (900s) | a `purge_runs` row; `GET /api/retention`; log `retention sweep finished` |
| `poll_vendor_balances` | hourly at `:43` | `BAYRAM_VENDOR_BALANCE_JOB_TIMEOUT_S` (60s) | `vendor_balances.fetched_at`; log `vendor balance poll finished` |
| `record_activity_snapshot` | daily at `00:07` **local** | `BAYRAM_QUEUE_JOB_TIMEOUT_S` (900s) | a `user_activity_snapshots` row; log `activity snapshot recorded` |
| `run_payme_sweep` | every `BAYRAM_PAYME_SWEEP_MINUTES` — default 5, so `:00, :05, …` | `BAYRAM_QUEUE_JOB_TIMEOUT_S` (900s) | log `payme sweep finished`; see below for what it is a backstop *for* |
| `sweep_due_broadcasts` | `:04, :09, …` | `BAYRAM_BROADCAST_CHUNK_TIMEOUT_S` | log `the broadcast sweep finished` |

The minutes are constants, not settings, for the first three: `RETENTION_CRON_MINUTE = 17`
(retention_job.py:73), `VENDOR_BALANCE_CRON_MINUTE = 43` (vendor_balance_job.py:118),
`ACTIVITY_SNAPSHOT_CRON_HOUR/MINUTE = 0/7` (activity_job.py:74-75). The last two are computed:
`sweep_minutes()` returns `tuple(range(0, 60, settings.payme_sweep_minutes))`
(payme_jobs.py:196-221) and `BROADCAST_DUE_CRON_MINUTE = tuple(range(4, 60, 5))`
(broadcast_job.py:152).

All five are `run_at_startup=False`, `unique=True`, `max_tries=1`, but **three different timeout
knobs are in play** and that is deliberate. Retention, the snapshot and the Payme sweep take
`queue_job_timeout_s`; the balance poll takes `vendor_balance_job_timeout_s`; and
`sweep_due_broadcasts` takes `broadcast_chunk_timeout_s`, and the cron entry says why it is not
`queue_job_timeout_s`: "this makes one bounded query and at most fifty enqueues and has no business
holding a worker slot for fifteen minutes if Redis goes quiet" (jobs.py:946-950). The underlying
arithmetic is on the chunk job itself — 900 s is sized for a music render, a campaign is 250 chunks,
and "a chunk holding one of fifteen slots for a quarter of an hour would starve the paying customer
behind it, 250 times over" (jobs.py:771-777). `unique=True` keeps a multi-worker deployment to one run per window.
`max_tries=1` means the next window *is* the retry, which is safe for reasons written down per
job: the balance failure is on the row either way with its error code, the snapshot's unique
constraint on `snapshot_date` makes a duplicate harmless, and for the two sweeps a failed run
must not become two concurrent ones.

`[HOST 2026-09-11]` All five were observed firing on `abdu-test`, with these shapes — worth
pasting into an alert rule, because the key names are what a query matches on:

```json
{"ts":"2026-09-11T10:17:00+0500","message":"retention sweep finished",
 "context":{"trigger":"cron","duration_ms":121,"rows_affected":0,"storage_keys_returned":0,
            "storage_keys_deleted":0,"storage_delete_failures":0,"is_batch_full":false,"error":null}}
{"ts":"2026-09-11T09:43:02+0500","message":"vendor balance poll finished",
 "context":{"polled":2,"succeeded":2,"failed":0,"estimated":1,"duration_ms":2153}}
{"ts":"2026-09-11T00:07:00+0500","message":"activity snapshot recorded", ...}
{"ts":"2026-09-11T10:35:00+0500","message":"payme sweep finished",
 "context":{"intents_expired":0,"transactions_timed_out":0,"notifications_re_enqueued":0,...}}
{"ts":"2026-09-11T10:34:00+0500","message":"the broadcast sweep finished",
 "context":{"campaigns_scanned":0,"expansions_enqueued":0,"sends_enqueued":0,...}}
```

**The retention summary's failure key is `error`, not `error_code`.** `error_code` is the
column name on `purge_runs` (purge_run.py:113-115); `error` is the key in the job's log line.
A rule written against the wrong one matches nothing, forever, silently.

> **The Payme sweep is why a downed worker now costs money rather than only tidiness.** Its
> `notifications_re_enqueued` leg is the backstop that tells a customer whose payment settled
> during a Redis outage that it landed — the gateway holds no Telegram token, so every such
> message is an ARQ job (`08-payme.md` §1.1). `[HOST 2026-09-11]` The same job also re-checks
> the settlement invariant, and on this host it currently corroborates the first real
> settlement every time it runs: `{"message": "the payme settlement invariant holds",
> "transactions_performed": 1, "receipts_written": 1, "grants_written": 1}` at
> `2026-09-11T09:00:00+0500`.

> **A cold-started worker runs no cron until the next window, and the gap is now per-job.**
> `run_at_startup=False` was chosen over closing that gap, and the comment says why: a startup
> invocation is in no cron window, so `unique` does not deduplicate it, and a three-replica
> rolling deploy would fire three authenticated vendor probes at once — a rate-limit ban on the
> credential the pipeline depends on costs more than an hour of a stale cached number
> (jobs.py:850-860). The worst-case silence after a restart:
>
> | Job | Cold-start gap |
> | --- | --- |
> | `run_payme_sweep`, `sweep_due_broadcasts` | ≤ 5 minutes |
> | `run_retention_sweep`, `poll_vendor_balances` | ≤ 1 hour |
> | `record_activity_snapshot` | ≤ 24 hours |
>
> So a worker restarted at 12:05 shows "not polled" for 38 minutes by design, but a customer
> waiting on a settled-payment message waits at most five.

> **None of the five binds a correlation id, so every line they emit carries
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

One hourly job drives **nineteen** counted sweeps and a chain-anchor pin in **one** database
transaction (db/purge.py:471-511, the authoritative list being `PurgeSummary.per_sweep_counts`
at db/purge.py:373-394): assets, brief notes, brief identities, attempt identities, attempt
transcripts, name records, abandoned drafts, the two audit clocks, `admin_sessions`,
`purge_runs`, `vendor_usage`, `bot_membership_events`, chat bodies, chat messages, the Payme RPC
log, payment intents, broadcast recipients, and `settle_stale_debits` last of all — inside the
same transaction, because it writes ledger rows rather than deleting, "so a purge that fails
half way must take these back with it" (db/purge.py:509-511). The audit HEAD anchor is pinned in
the same transaction (`pin_audit_head`, db/purge.py:486). Each sweep is bounded at 500 rows per
table per run (`DEFAULT_PURGE_BATCH_SIZE`, db/purge.py:204) — 12 000 a day per table.

> **SUPERSEDED 2026-09-10: this used to say fourteen sweeps.** Five counters arrived with the
> chat, Payme and broadcast work — `chat_bodies_purged`, `chat_messages_deleted`,
> `payme_rpc_rows_deleted`, `payment_intents_deleted`, `broadcast_recipients_deleted` — and the
> cited line range had drifted by roughly a hundred lines. Watch
> `broadcast_recipients_deleted` in particular: `broadcast_recipients` takes **a row per account
> per campaign**, so it is the count most likely to be the one saturating the 500-row batch and
> holding `is_batch_full` true.

`[HOST 2026-09-11]` All nineteen appear in the live line, which is the cheapest proof that the
installed wheel matches this list:

```json
{"ts":"2026-09-11T10:17:00+0500","message":"retention purge complete",
 "context":{"ran_at":"2026-09-11T05:17:00.261180Z","batch_size":500,"assets_deleted":0,
  "brief_notes_purged":0,"brief_identities_purged":0,"attempt_identities_purged":0,
  "attempt_transcripts_purged":0,"name_records_deleted":0,"abandoned_orders_deleted":0,
  "audit_reasons_purged":0,"audit_rows_deleted":0,"admin_sessions_deleted":0,
  "purge_runs_deleted":0,"vendor_usage_deleted":0,"membership_events_deleted":0,
  "chat_bodies_purged":0,"chat_messages_deleted":0,"payme_rpc_rows_deleted":0,
  "payment_intents_deleted":0,"broadcast_recipients_deleted":0,"stale_debits_settled":0,
  "storage_key_count":0}}
```

Note `ran_at` is UTC in that line while `ts` is host-local — the same five-hour offset the cron
table warns about, on one line, in both spellings.

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
retention purge complete            # db/purge.py:542 — the per-table counts, keys excluded
retention sweep finished            # retention_job.py:267 — the job's summary
the retention purge failed          # retention_job.py:280 — ERROR; a row is still written
an expired object could not be deleted from storage   # retention_job.py:152 — ERROR, one per key
```

> **There is no way to trigger a sweep on demand.** `POST /api/retention/run` is described in
> two docstrings (admin/routers/retention.py:10, retention_job.py:66) and does not exist:
> the only route on that router is the `GET` (retention.py:59), and the only enqueuer of
> `RETENTION_JOB_NAME` is the cron entry (jobs.py:708). If the hourly sweep stops, the
> recovery is to get the worker running and wait for `:17`, and an erasure request's purge
> cannot be expedited.

### Vendor balance probes

The entry is registered unconditionally but the job no-ops in two cases, and reports which:
`{"skipped": "fake_providers"}` under `BAYRAM_USE_FAKE_PROVIDERS`, and
`{"skipped": "poll_disabled"}` when `BAYRAM_VENDOR_BALANCE_POLL_ENABLED` is off
(vendor_balance_job.py:318-323, the two reasons named separately at :124-129 because "this
deployment contacts no vendor" and "this one surface is switched off" are different operator
decisions). A successful run logs `vendor balance poll finished` with `polled`, `succeeded`,
`failed`, `estimated` and `duration_ms` (vendor_balance_job.py:352).

**One OpenRouter account may cost two requests, and only one of them can fail loudly.** When
`BAYRAM_OPENROUTER_MANAGEMENT_KEY` is set (D13) and `GET /api/v1/key` came back with no cap, the
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

> **A worker that is down degrades FIVE things silently and none of them raise.** Retention
> sweeps stop, which is a stated legal obligation; the audit chain's HEAD anchor stops being
> re-pinned, so tail deletions become undetectable while `/audit/verify` still reports
> `ok: true`; the activity series accrues a permanent gap; **the Payme delivery backstop stops,
> so a customer whose payment settled during a Redis outage is never told**; and **no scheduled
> broadcast fires**. No other actor covers any of them, and neither the bot nor the worker
> exposes an HTTP probe — the only two health endpoints in the tree are on the admin API
> (admin/routers/health.py:121-138). Supervision of the bot and the worker can only be
> process-level. `[HOST 2026-09-11]` On `abdu-test` that supervision is systemd and nothing
> else: all four units are `active` and `enabled` with `NRestarts=0`, last started together at
> `2026-09-11 06:50:11`–`06:50:13 +05` (PIDs 193438/193442/193447/193451). There is no external
> monitor — see *the probe token* in `06` §9.

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
(db/admin/audit.py:779-805, the WARNING at :800-803). So `revoke+hmac` is claimed only when the
database says the connecting role really cannot rewrite the log. `hmac-only` is returned in four
situations: `BAYRAM_ADMIN_AUDIT_DSN` unset, a non-Postgres backend, the probe erroring
(`admin.audit.privilege_probe_failed`, :794-797), or the role still being writable.

> **SUPERSEDED 2026-09-10 — THIS IS NO LONGER A PREDICTION. `abdu-test` IS THE CASE BELOW.**
> The box used to say "`hmac-only` is the likely answer on any deployment that followed the
> written install steps, and this is a code prediction, not an observation." The prediction was
> right and the hedge can go.
>
> `[HOST 2026-09-10]` `admin.audit.revoke_missing` was logged **twice** by `hbd-admin`, at
> 09:29:50 and 12:36:59 +05, message verbatim: *"the audit REVOKE is configured but not in
> force; the app role can still write"*. Per `resolve_chain_protection` that branch is reached
> **only** when `HBD_ADMIN_AUDIT_DSN` **is** set **and** the privilege probe came back writable
> — i.e. exactly row 2 of `06` §3's table. Zero `admin.audit.privilege_probe_failed`; zero
> `admin.audit.chain_broken`, ever.
>
> **The root cause is readable on the host and it will recur.** `[HOST 2026-09-11]` The schema
> was dropped and rebuilt at ~09:25 on 2026-09-10 by `/opt/hbd/release/wipe-and-rebuild.sh`. Its
> step 3 runs `DROP SCHEMA public CASCADE; CREATE SCHEMA public; GRANT ALL ON SCHEMA public TO
> ${APP_ROLE};` (and to `postgres`), where `APP_ROLE` is parsed out of the DSN at line 51. Its
> step 4 tries `/usr/local/bin/hbd-migrate` and falls back to:
>
> ```bash
> ( cd /opt/hbd && HBD_ENV_FILE="$BOT_ENV" \
>     /opt/hbd/venv/bin/python -m alembic -c /opt/hbd/migrations/alembic.ini upgrade head )
> ```
>
> A `grep` of that script for `HBD_ADMIN_AUDIT_DSN`, `HBD_DB_APP_ROLE` or
> `HBD_DB_MIGRATION_URL` returns **zero hits**. So on a schema built from scratch that morning,
> migration 0007 took its **first** skip branch — `_skip("BAYRAM_ADMIN_AUDIT_DSN is not set…")`
> at 0007:336-337 — and neither the REVOKE nor `hbd_purge_audit_log` /
> `hbd_purge_audit_reasons` was created. The step before it had already granted the application
> role everything in the schema. **The next wipe reproduces this exactly**, so the fix belongs in
> that script, not in an operator's memory; the ordering constraint is in `06` §3 FIX (b) and
> the export line is in `07-security.md` §6.
>
> `[UNPROVEN]` What this page cannot say is what the grant table *now* holds. `\dp
> admin_audit_log`, `pg_tables.tableowner` and `\df public.hbd_purge_audit_*` all need a
> database password: `/etc/hbd` is `Permission denied` to `developer`, `sudo -n` is refused,
> there is no `~/.pgpass`, and Postgres listens on `127.0.0.1:5432` with password auth.
> `[UNPROVEN]` Whether the roles `hbd` and `hbd_app` even exist is **also** unproven, and this
> is worth one sentence because it is an easy mistake to make: over TCP, Postgres answers
> `FATAL: password authentication failed for user "…"` for a **wrong password and for a role
> that does not exist alike** — verified 2026-09-11 with a deliberately invented role name,
> which got the same refusal as `hbd_app`. Do not read that message as proof a role exists.
>
> `/opt/hbd/diagnose.sh` on the host already asks three of these questions in four queries
> (`has_schema_privilege('hbd','public','CREATE')`, the same for `USAGE`, the
> `alembic_version` owner, and every distinct `tableowner` in `public`) — and it needs one sudo
> password. **Note the trap beside it:** `/opt/hbd/deploy-payme.sh` is now a two-line wrapper
> whose header comment says it runs the rename cutover and whose `exec` line runs
> `diagnose.sh`. The script name and both halves of the file disagree; read it before running
> it.

> **Why it skips, in the code rather than on the host.** Migration `0007` reads its
> preconditions from `os.environ` **only** — the audit DSN at
> `migrations/versions/20260830_1000_0007_add_admin_audit_log.py:336`, the role name at
> :314-322 — while `BAYRAM_ADMIN_AUDIT_DSN` is documented as living in the admin dotenv file
> (.env.admin.example:130), which the migration runner never parses. `deploy/first-install-proposal.md:112`
> (a same-day proposal written without host access, not a record of any live host) exports
> only `BAYRAM_ENV_FILE`. Under that invocation `_install_two_role_controls` takes its first
> skip branch, logs a WARNING, and neither the `REVOKE` nor the two `SECURITY DEFINER` purge
> functions are created. Note that `migrations/env.py:96-114` *does* fall back to the dotenv
> file for `BAYRAM_DB_MIGRATION_URL`, and env.py:14-19 explains that the environment-only version
> of exactly this read was a bug — the fix was not carried across to the migration bodies. To
> install the control, export both variables into the shell that runs alembic:
>
> ```bash
> BAYRAM_ADMIN_AUDIT_DSN='<owner dsn>' BAYRAM_DB_APP_ROLE=hbd_app BAYRAM_ENV_FILE=<bot env file> \
>   .venv/bin/python -m alembic -c migrations/alembic.ini upgrade head
> ```
>
> `BAYRAM_DB_APP_ROLE` (0007:69) appears in neither example file, so an operator has no way to
> discover it exists.

**Three things answer "did the REVOKE land", and on this host only one of them is reachable.**
The old text here offered two — `/api/audit/verify` and `\dp admin_audit_log`. Add the third,
and put it first, because it is the cheapest and the only one that needs no credential:

| Route | What it needs | On `abdu-test` |
| --- | --- | --- |
| `journalctl -u hbd-admin -o cat \| grep admin.audit.revoke_missing` | nothing — `developer` is in `adm` | `[HOST 2026-09-10]` **two hits.** The REVOKE is not in force. |
| `GET /api/audit/verify` → `chainProtection` | an ADMIN or OWNER browser session | `[UNPROVEN]` nobody in this workflow has a session; `/api/config` answers 401 `UNAUTHENTICATED` without a cookie. |
| `\dp admin_audit_log` | the database password | `[UNPROVEN]` behind the permission wall, as above. |

> **Phrase it as what was observed, not as what the panel said.** Nobody has read
> `chainProtection` on this host. The WARNING is a sound proxy — `resolve_chain_protection`
> reaches it only on the DSN-set-and-still-writable branch — so the defensible sentence is
> *"the panel logged the WARNING that accompanies `hmac-only`"*, and that is the sentence this
> page uses. The difference matters the day somebody signs in and finds something else.
>
> One consequence worth noticing: the WARNING fires **only when somebody calls
> `/api/audit/verify`**. `[HOST 2026-09-11]` Two hits in the whole journal means the endpoint
> has been read twice, ever — not that the condition cleared. Absence of the line is not
> evidence of health; it is evidence nobody looked.

**The undetectable tail window is one sweep interval wide.** HEAD and TRUNCATION anchors are
written by the retention job, not by the verifier: `pin_audit_head` deletes every prior HEAD
anchor and writes one (db/purge_admin.py:198), inside the hourly purge transaction
(db/purge.py:486). Its docstring states the limit rather than papering over it: rows written
since the last pin can still be excised without `/audit/verify` noticing. Every anchor write
logs `admin.audit.anchor` with its kind, seq and hash (db/admin/audit.py:705-715) — that log
line is the full history of pins, since only the newest row is kept.

`[HOST 2026-09-11]` On `abdu-test` the window is exactly one hour and the HMAC half is working:
the anchor is re-pinned at `:17` with every retention sweep, and `admin.audit.chain_broken` has
**never** been logged.

```json
{"ts":"2026-09-11T10:17:00+0500","message":"audit chain anchor",
 "context":{"event":"admin.audit.anchor","kind":"head","seq":16,
  "hash":"6317f7d7e5ddcd9d36ba0ac524e030467ade62643ee4a2be7523cf173d03bf31",
  "truncated_below_seq":null,"rows_deleted":null}}
```

> **`seq` in that log can go BACKWARDS, and it is not tampering — it is a database wipe.**
> `[HOST 2026-09-10]` The anchor history on this host reads `09:17 seq 8`, then `10:17 seq 4`,
> `11:17 seq 4`, `12:17 seq 4`, `13:17 seq 5`, `14:17 seq 6`. The schema was dropped and rebuilt
> at ~09:22 that morning (above), so the `seq 8` anchor belongs to a database that no longer
> exists. Since only the newest anchor ROW is kept, this log is the only place that history
> lives — and anyone reading it as a monotonic sequence will read a rebuild as an excision.
> Note the same wipe is why the chain is currently short: `seq` reached 16 by 2026-09-11, from a
> log that began that morning.

> **The HMAC has no key identifier.** The MAC is
> `HMAC-SHA256(key, "v1" ‖ prev_hmac ‖ canonical_json(row))` with `CHAIN_VERSION` a module
> constant (db/admin/audit.py:10-12) and no key-id column on the row
> (db/models/admin_audit.py:131-197). Rotating `BAYRAM_ADMIN_AUDIT_HMAC_KEY` is therefore
> indistinguishable from tampering across the whole 730-day log: change it and `/audit/verify`
> reports a break at the first row for ever; lose it and the log is permanently unverifiable.
> There is no rotation path in the code. Treat the key as a write-once secret and back it up
> where the database is not.

---

## Reading the logs

> **ON THIS HOST THE LOGS GO TO THE JOURNAL AND NOWHERE ELSE, AND NOTHING READS THEM.**
> `[HOST 2026-09-11]` No shipper. No `/etc/logrotate.d` entry for anything `hbd` (the directory
> holds fourteen files, all for other software). `/var/log/hbd/` exists, is owned `hbd:hbd`, and
> is **empty** — despite `ReadWritePaths=/var/log/hbd` on the bot and worker, nothing writes a
> file there. `/etc/systemd/journald.conf` sets no `SystemMaxUse`, no `MaxRetentionSec` and no
> `Storage`, so journald's defaults decide retention, and `journalctl --disk-usage` reports
> **96.6 MB** (88.6 MB the previous day — it is growing).
>
> That is the answer to a question these documents have been deferring, and it is the bad
> answer. **Every alert rule in the table below, and every "the only signal is a log line" row
> in `07-security.md`'s degradation table, currently pages nobody.** The worked example is one
> page up: `admin.audit.revoke_missing` — a security control reporting itself absent — sat
> unread in this journal from 2026-09-10 until somebody grepped for it. The two ERROR events
> genuinely worth paging on, `admin.audit.chain_broken` and `admin.audit.write_failed`, have a
> destination of exactly nobody.

Every process installs the same root handler, and the format switch is `BAYRAM_IS_DEBUG`, not the
level: `configure_logging(level=settings.log_level, is_json=not settings.is_debug)` at
main.py:220, worker.py:36 and admin/app.py:314.

> **Turning on `BAYRAM_IS_DEBUG` to get more detail silently switches the whole stream to
> unparseable plain text** (`%(asctime)s %(levelname)s [%(correlation_id)s] %(name)s:
> %(message)s`, logging.py:233-235) — which will break a shipper's parsing rules at the worst
> possible moment. Raise `BAYRAM_LOG_LEVEL` instead; it does not change the format.

The JSON line is a fixed five-key envelope plus two conditional keys (logging.py:200-220) —
**for every line this application emits.** It is not true of everything in a unit's journal: see
the arq and uvicorn caveat in the preamble, which is the difference between a working `jq` filter
and one that dies on every other line.

```json
{"ts": "...", "level": "INFO", "logger": "bayram.runtime.retention_job",
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
stream that has no retention clock and that neither `bayram.db.purge` nor a per-user erasure can
reach. The admin process additionally *refuses to boot* at DEBUG in prod
(admin/settings.py:589-593); the bot and the worker have no such refusal, and `configure_logging`
is the whole mitigation there.

### Named events worth an alert rule

Only the admin subsystem emits a machine-readable `event`; everything else in the tree is
prose. The table below is the set worth an alert rule, not the whole set — the tree currently
carries 45 distinct strings, and the authoritative list is
`grep -rhoE '"event": "[a-z_.]+"' src/bayram/admin/ | sort -u`. Grep `context.event`.

| Event | Where | Level | Means |
| --- | --- | --- | --- |
| `admin.audit.chain_broken` | routers/audit.py:174 | ERROR | the log does not verify — page |
| `admin.audit.revoke_missing` | db/admin/audit.py:802 | WARNING | the DSN says two roles; Postgres says the app role can still rewrite the log |
| `admin.audit.privilege_probe_failed` | db/admin/audit.py:796 | WARNING | could not ask; reporting the weaker guarantee |
| `admin.audit.write_failed` | audit_sink.py:111 | ERROR | an action happened and was not audited |
| `admin.audit.value_refused` | audit_sink.py:127, services/assets.py:483 | ERROR | a value could not be stored; the row was retried scrubbed |
| `admin.audit.secret_refused` | db/admin/audit.py:265 | ERROR | something tried to put a secret in the log |
| `admin.audit.anchor` | db/admin/audit.py:712 | INFO | a HEAD or TRUNCATION anchor was written — the only history of pins |
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
| `admin.csrf.refused` | deps.py:233 | WARNING | `ORIGIN_REJECTED` — usually a wrong `BAYRAM_ADMIN_PUBLIC_ORIGIN` |
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
bot starting                        # main.py:372
worker started                      # runtime/jobs.py — carries concurrency
worker dependencies built           # worker.py:47
the checkout is wired but the credit meter is dark   # main.py:393 — WARNING; see the box above
retention purge complete            # db/purge.py:542
retention sweep finished            # retention_job.py:267
the retention purge failed          # retention_job.py:280 — ERROR
an expired object could not be deleted from storage  # retention_job.py:152 — ERROR
vendor balance poll finished        # vendor_balance_job.py:367
activity snapshot recorded          # activity_job.py:169
activity snapshot for this day was already recorded  # activity_job.py:173 — INFO, a restart
activity snapshot finished with no row                # activity_job.py:167 — WARNING
payme sweep finished                # runtime/payme_jobs.py — the settlement backstop
the payme settlement invariant holds                  # runtime/payme_jobs.py — carries the three counts
the broadcast sweep finished        # runtime/broadcast_job.py
an operator changed an account's block               # tools/credits.py:281
an operator changed the bot's profile                # tools/identity.py:309
database ping failed                # db/engine.py:109
```

> **Line numbers in this tree drift, and on 2026-09-10 they drifted in one direction.** The
> Payme and broadcast work moved `db/purge.py`, `runtime/jobs.py`,
> `runtime/vendor_balance_job.py` and `db/admin/audit.py` by up to 140 lines each. Every citation
> on this page was re-checked against the working tree on 2026-09-11. If you are about to cite
> one of those four files from memory, don't.

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
argument in this codebase is about deletion being the risk; loss is unaddressed.

**What the host has is ad-hoc, Postgres-only, and on no schedule — and one nightly timer that
looks like a backup is somebody else's.** `[HOST 2026-09-11]`

* `/var/backups/hbd/` holds **nine** `*.sql.gz`, all written by release scripts immediately
  before they changed something: `pre-payme-*` ×5 (2026-09-09/10), `pre-wipe-20260910-092203`
  (23 KB), `pre-wipe-20260910-092437` (563 bytes — a dump of a schema that was *already*
  empty, which is the shape of a resumed script and not of a backup), and `pre-cutover-*` ×2
  from 14:05/14:06 on 2026-09-10. The command is `sudo -u postgres pg_dump -d hbd | gzip`
  (`/opt/hbd/release/wipe-and-rebuild.sh:91`), with **no** `--no-acl` either way — so whether
  grants come back is decided by `pg_dump`'s defaults, not by a considered flag. The script
  refuses to continue if the dump fails, which is the right instinct.
* **No restore path is scripted anywhere.** The closest thing is a hint the script prints on
  failure: `gunzip -c <dump> | sudo -u postgres psql -d hbd`.
* **`aizu-backup.timer` is the only scheduled backup on the box and it backs up a different
  application.** Nightly 03:30 ±300 s, `User=aizu`, `sqlite3 /var/lib/aizu/aizu.db ".backup …"`
  into `/var/backups/aizu`, 14 days kept. Nothing of ours.
* So of the four things below, **three are covered by nothing at all**: the archive, Redis and
  `HBD_ADMIN_AUDIT_HMAC_KEY`. And the one that is covered is covered by hand, on the days
  somebody happened to run a release script.

### What must be in a backup for it to be sufficient

Four things, and three of them are not the database.

1. **Postgres, in full.** **Twenty-eight** mapped tables plus `alembic_version` (`grep -h
   '__tablename__' src/bayram/db/models/*.py | sort -u | wc -l` → 28; this said twenty-one
   before the chat, Payme and broadcast tables landed). The ones that make a partial dump
   insufficient are `credit_ledger` (the only explanation of every balance), `plan_purchases`
   and `topup_purchases` — receipts that answer a payment dispute months after the recipient's
   name, the note and the audio are lawfully gone — `admin_audit_log` with
   `audit_chain_anchors`, which are meaningless apart from one another, and now
   **`payme_transactions`, `payment_intents` and `payme_rpc_log`** (migration `0023`). That last
   trio is not a theoretical addition: `[HOST 2026-09-10]` the Payme rail took its first real
   settlement on this host on 2026-09-10 and those are the only rows that record it. A dump
   taken from this list as it read yesterday **cannot answer a Payme dispute at all.**
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
4. **`BAYRAM_ADMIN_AUDIT_HMAC_KEY`.** It lives in the admin dotenv file and nowhere else — a
   `SecretStr` with `min_length=32` on `AdminSettings` (admin/settings.py:229) — and it is not
   in the database. A database-only restore comes back with an audit log nobody can verify.

> **Back the key up somewhere the database is not.** A backup that contains both the
> `admin_audit_log` table and the key that authenticates it is a backup an insider can rewrite
> end to end: the chain is recomputable by anyone holding the key. Storing them in one place
> defeats the only control that survives a compromised application credential.

### After a restore

The order matters, because each step tells you something the next one assumes.

```bash
# 1. Schema level. The chain is linear 0001..0025; a restore of an older dump against
#    newer code needs this before anything else touches the database.
BAYRAM_ENV_FILE=<bot env file> \
  .venv/bin/python -m alembic -c migrations/alembic.ini upgrade head
```

The chain runs to `0025` (`20260910_1000_0025_index_settlement_clocks.py`, dated 2026-09-10):
`0022` chat messages, `0023` the Payme rail tables, `0024` the broadcast tables, `0025` the
settlement-clock indexes. `[HOST 2026-09-11]` The same 25 files are on the host at
`/opt/hbd/migrations/versions/`.

> **STOP: ON THIS HOST THAT COMMAND CANNOT RUN TODAY, AND IT FAILS IN A WAY THAT WILL MISLEAD
> YOU MID-INCIDENT.** `[HOST 2026-09-11]` `/opt/hbd/migrations/env.py` was copied from the
> **post-rename** repository on 2026-09-10 at 14:06 and its line 57 reads `from bayram.config
> import env_file, load_settings` — while the venv holds only the **pre-rename** package:
>
> ```console
> $ /opt/hbd/venv/bin/python -c 'import bayram'
> ModuleNotFoundError: No module named 'bayram'
> $ /opt/hbd/venv/bin/python -c 'import hbd; print(hbd.__file__)'
> /opt/hbd/venv/lib/python3.12/site-packages/hbd/__init__.py
> ```
>
> `alembic.ini:15` also sets `prepend_sys_path = %(here)s/../src`, and `/opt/hbd/src` does not
> exist. So a half-finished rename presents as a broken virtualenv, and nothing in the traceback
> says which. **Check before you trust any recovery step on this page or in `06` that ends in an
> alembic invocation** — there are four of them (`06` §3(a), §11, §12, and step 1 here):
>
> ```bash
> ssh aizu '/opt/hbd/venv/bin/python -c "import bayram" || echo "CUTOVER NOT RUN: use the hbd package"'
> ```
>
> Until the cutover runs, the migration runner on `abdu-test` needs the `HBD_` prefix **and** an
> `env.py` that imports `hbd`. The staged wheel and `cutover-to-bayram.sh` that fix this
> properly are in `/opt/hbd` and `/opt/hbd/release`, unexecuted; the sequence is `08-payme.md`
> §11.6 and `09-payme-go-live.md` §2.

> **Migrations require the vendor keys they do not use.** `migrations/env.py:129` calls
> `load_settings()` for the DSN when `BAYRAM_DB_MIGRATION_URL` is unset, and `load_settings()`
> always requires the three vendor secrets (config.py:758-760). A migration-only host, or a CI
> step that has the DSN and no keys, fails with a message about missing API keys. Setting
> `BAYRAM_DB_MIGRATION_URL` avoids the fallback *and* is what makes migrations run as the owner
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
in place, re-run migrations with `BAYRAM_ADMIN_AUDIT_DSN` and `BAYRAM_DB_APP_ROLE` exported (above)
and confirm with `chainProtection` rather than with the fact that the command exited zero. The
migrations are the only grant statements this repository owns, and re-running them is
idempotent, so this costs nothing when the grants did survive.

> **PARTIALLY ANSWERED 2026-09-10 — and the de facto restore procedure on this host drops the
> audit REVOKE every time it runs.** The question used to read: "Whichever mechanism actually
> takes and restores these dumps — none of it is in the repository, and nobody in this workflow
> can inspect the host — decides whether roles and ACLs come back with the data." Half of it now
> has an answer.
>
> `[HOST 2026-09-11]` The mechanism is `/opt/hbd/release/wipe-and-rebuild.sh` (9.2 KB, with
> `resume-wipe.sh` beside it for a run that died half way), and it was run at ~09:22–09:25 on
> 2026-09-10. What it does, in order: `pg_dump | gzip` to `/var/backups/hbd/pre-wipe-*`,
> refusing to continue if that fails → stop the units → `DROP SCHEMA public CASCADE; CREATE
> SCHEMA public; GRANT ALL ON SCHEMA public TO ${APP_ROLE}` (and to `postgres`) → try
> `/usr/local/bin/hbd-migrate`, else `HBD_ENV_FILE=… alembic upgrade head`.
>
> **Compare that against the four numbered steps above and three are missing.** It does not
> export `HBD_ADMIN_AUDIT_DSN` / `HBD_DB_APP_ROLE` / `HBD_DB_MIGRATION_URL` (grep: zero hits),
> so step 1 silently skips the REVOKE and every table ends up owned by the application role. It
> does not run `verify_balances`, so step 2 never happens. It does not read
> `chainProtection`, so step 3 — **the step that would have caught the REVOKE gap** — never
> happens either. The gap is not a one-off: it reproduces on the next wipe.
>
> `[UNPROVEN]` `/usr/local/bin/hbd-migrate` is root-only (820 bytes) and cannot be read with the
> access available, so whether *it* exports the two-role variables is unknown. The outcome
> settles the practical question either way — the REVOKE did not land — but the script itself is
> unread. The script's own comment records that `hbd-migrate` failed on 2026-09-10 by passing
> `"upgrade head"` as a single argument, so the alembic fallback is the path that actually ran.
>
> Still open: whether `pg_dump`'s defaults on this host bring ACLs back, and where an off-box
> copy of any of these dumps lives. Nothing on the machine answers the second one.

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
