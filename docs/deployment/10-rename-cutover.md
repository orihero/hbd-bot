# The hbd → bayram rename cutover

> **STATUS — written 2026-09-11, checked against the host the same day.** This page is the
> document [`08-payme.md`](08-payme.md) §11.6 demanded — *"give it its own document, its own
> window, and its own rollback plan"* — and the runbook behind Gate A of
> [`09-payme-go-live.md`](09-payme-go-live.md) §2, which is a gate board and was never meant to
> carry the steps.
>
> **The operation has already been attempted once. It failed, it took all four processes down
> for 2 min 54 s, and its half-built debris is on the host right now.** §2 is the transcript,
> §2.3 is the root cause, and it is not a bug in the script: **the cutover starts with a
> `GRANT`, not with the script.** Nobody had established that before this page was written.
>
> ### The four marks
>
> The convention is [`01-architecture.md`](01-architecture.md)'s and it is load-bearing:
>
> - **`[HOST 2026-09-11]`** — a read-only command was run against `aizu` (machine `abdu-test`)
>   on that date and what is quoted is faithful to its output. The command is named wherever it
>   is not obvious.
> - **`[TREE 2026-09-11]`** — checkable by opening a file in this working tree; a `path:line` is
>   given.
> - **`[UNPROVEN]`** — exactly that, with the blocker named. On this page the blocker is almost
>   always one of three: `/etc/hbd` is `0750 root:hbd` and the `hbd` group has no members, so no
>   dotenv file is readable; `sudo -n` answers `sudo: a password is required`; and the `NOPASSWD`
>   drop-in grants `pg_dump` and not `psql`.
> - **`[HOST+TREE 2026-09-11]`** — a fourth mark this page needs and the others do not, used four
>   times. It means **the same artefact was read on both sides and compared**: a file on the host
>   and a file in this working tree, matched by `md5sum`, or a set of strings generated from each
>   and diffed. A rename is exactly the operation where "the tree says X" and "the host says X"
>   have to be one fact rather than two, and collapsing such a check to either `[HOST]` or
>   `[TREE]` would throw away the half that makes it worth anything.
>
> **The host is PRE-RENAME and that is correct.** Every host command below is spelled `hbd`,
> `HBD_`, `/etc/hbd`, `/opt/hbd` because that is what the machine says. Every source citation is
> spelled `bayram`, `BAYRAM_` because that is what this tree says. Both are right at once — the
> argument is [`09-payme-go-live.md`](09-payme-go-live.md) §1.2. **Do not sweep this page with a
> rename pass.** A blind rename has already turned verified host facts into fiction in this tree
> once ([`00-host-inventory.md`](00-host-inventory.md), finding 7), and this is the one page
> where both spellings are deliberately present on the same line.
>
> **Nothing on this page renames the database.** §3.11 argues why.

---

## 0. How to read this page

§1 is the argument — read it even if you think you know it, because the failure mode it names is
*payments visible, endpoint gone*. §2 is what happened on 2026-09-10 and what state the machine
is in today. §3 is the inventory: everything that moves, everything that stays, and the nine
Redis key strings that move silently. §4 is the preconditions — the window cannot open until all
of them are true, and one of them is a `GRANT` nobody has issued. §5 is the ordered cutover. §6
is the rollback and the point of no return. §7 is the verification suite, including the
settlement rehearsal re-run that [`09-payme-go-live.md`](09-payme-go-live.md) §4.0 already says
this gate reopens for. §8 is the trap list.

**There is a script, it is staged on the host, and this page is not a wrapper around it.**
`/opt/hbd/cutover-to-bayram.sh` (9 271 bytes, `developer:developer` `0755`, dated 2026-09-10
14:03) is byte-identical to `deploy/cutover-to-bayram.sh` in this tree — `md5sum` agrees,
`c01caf751134f9d3d7e8c9a6f6d7bafa` `[HOST+TREE 2026-09-11]`. It is a good script and its header
is the best writing on this subject anybody has produced; §5 cites it by line throughout. But it
does **not** do six of the things this page says must happen, and §5.0 lists them. Read this page
and then read the script; do not run the script and then read this page.

---

## 1. What the operation is, and why no release may straddle it

**A renamed variable is an unset variable.** `pydantic-settings` reads the environment **by
prefix**: `ENV_PREFIX: Final[str] = "BAYRAM_"` (`src/bayram/config.py:75`), passed as
`env_prefix=ENV_PREFIX` to every settings class (`config.py:206`, `payme/settings.py:154`)
`[TREE 2026-09-11]`. A process that reads `BAYRAM_*` against a file of `HBD_*` lines does not see
a partly-configured system. It sees an **empty** one: `environment` falls back to `dev`,
`admin_enabled` to `false`, `redis_url` to `redis://localhost:6379/0`, and the required fields
that have no default raise a `ConfigError` naming the first one missing. That is
[`00-host-inventory.md`](00-host-inventory.md) row 46's argument and it is the reason the dotenv
rewrite and the wheel that reads it must land inside one restart.

**And the loud failure is worse than it sounds, because it is only loud in one process.** Install
a `bayram`-packaged wheel while a unit's `ExecStart` still names `hbd.payme.app:app` and the
gateway raises `ModuleNotFoundError` and dies. `hbd-payme.service` is `Restart=always` with
`RestartSec=5s` `[HOST 2026-09-11]`, so it restart-loops for ever, five seconds apart — **while
the bot, which restarted successfully, keeps serving a paywall.** Payments visible, endpoint
gone: the customer is shown a price, taps it, and Payme's `CheckTransaction` reaches a socket
that nothing is listening on. The gateway's loop is visible and nobody is watching it; the
paywall is invisible and every customer is.

That shape is not hypothetical on this host. `hbd-payme` restarted **twelve** times between
00:00:05 and 00:01:26 on 2026-09-10 under exactly that policy while the other three units
restarted twice, which is what a gateway that refuses to boot looks like in the journal
`[HOST 2026-09-11]`.

### 1.1 Two failures are loud. Two are silent, and both of them are about money.

**Silent failure one — the pause switch is a Redis key, and the rename moves it.** The deployed
wheel writes `"hbd:payme:paused"`
(`/opt/hbd/venv/lib/python3.12/site-packages/hbd/payme/pause.py:75`) `[HOST 2026-09-11]`; the new
code writes `"bayram:payme:paused"` (`src/bayram/payme/pause.py:75`) `[TREE 2026-09-11]`. **A rail
paused before the cutover is open after it, and nothing anywhere will say so.** The key has no
TTL and no durable backing — [`09-payme-go-live.md`](09-payme-go-live.md) §9.2 records why that
is deliberate — so there is no reconciliation that would catch it and no `cli status` output that
would look wrong: the new code truthfully reports the new key, which nobody set.

**Silent failure two — the vendor idempotency prefix moves too.** `KEY_PREFIX: Final[str] =
"bayram"` (`src/bayram/pipeline/idempotency.py:23`), against `"hbd"` in the installed package
`[HOST+TREE 2026-09-11]`. Every key is `f"{KEY_PREFIX}-{stage.value}-{digest}"` over a `sha256`
whose input *includes* the prefix (`idempotency.py:34-37`), so **every key changes, including the
digest**. An in-flight order retried across the boundary mints a key no vendor has seen and pays
for the same generation twice.

### 1.2 What does **not** move, and why that is the good news

This is where [`09-payme-go-live.md`](09-payme-go-live.md) §2 can be made more precise rather
than merely repeated. Three things an operator would reasonably fear do not move at all
`[TREE 2026-09-11]`:

| Mechanism | Key shape | Moves? |
| --- | --- | --- |
| The ARQ queue itself | `arq:queue` — the library default; no `queue_name` is set anywhere in `src/bayram/` | **No** |
| ARQ job ids | `generate_and_deliver:<order_id>` (`pipeline/worker.py:47-49`), `notify_payment_settled:<public_ref>` (`runtime/payme_jobs.py:179-193`), `broadcast:{expand,send,test}:<id>` (`admin/queue.py:93-130`) — derived from job **names** and a literal `"broadcast"`, never from the brand | **No** |
| The money keys | `topup:{telegram_user_id}:{scope}:{seq}`, persisted in `credit_ledger.idempotency_key` under a unique index (`db/models/credit_ledger.py:122`) and matched in `plan_purchase` (`:125`) | **No** |

Live corroboration: the keys in Redis right now are `arq:queue:health-check`,
`arq:in-progress:run_payme_sweep:…` and three `fsm:<chat>:<user>:{data,state}` entries from
aiogram's own storage — `DBSIZE` is `5` `[HOST 2026-09-11]`. None of them carries a brand
segment, so **queued jobs, in-progress jobs and every customer's open conversation state survive
the cutover**. Job payloads survive too: every enqueue site passes primitives — `str(order.id)`,
a chat id, a message id (`runtime/submitter.py:64-70`), `public_ref`
(`payme/container.py:184-186`), `str(broadcast_id)` and an ISO timestamp
(`admin/queue.py:246-266`) `[TREE 2026-09-11]` — so nothing in the queue is a pickled `hbd.*`
class that the new interpreter could not import.

**What this buys you is the thing worth knowing before the window: the cutover does not need the
queue drained to be *correct*.** It needs the queue drained so that no *vendor* call is retried
across the prefix change (§1.1, failure two). Those are different requirements with different
costs, and conflating them is how a window gets abandoned for no reason.

### 1.3 So the rule

**Land the cutover as one all-or-nothing operation, with its own window and its own rollback,
either well before Gate F or well after it — never across it, and never on the same day.** That
is [`09-payme-go-live.md`](09-payme-go-live.md) §2's conclusion and nothing found since has
weakened it. The rejected alternative — *"finish the rename during go-live, it is only strings"* —
is rejected because it is not only strings: it is nine Redis keys, an idempotency prefix, four
unit names, three dotenv files, an env-var prefix, a venv, a sudoers rule and a `GRANT`, and two
of those fail without an error message.

---

## 2. It has been attempted. Read this before you schedule anything.

### 2.1 The transcript, 2026-09-10

All of this is `[HOST 2026-09-11]`, read from the journal, the Postgres log, the `sudo` audit
trail and the filesystem.

| Time (+05) | What happened | Evidence |
| --- | --- | --- |
| 14:03:12–14:03:40 | `bayram_bot-0.1.0-py3-none-any.whl` staged into `/opt/hbd/release/`; revision `0025` copied into `/opt/hbd/migrations/versions/` | file mtimes |
| 14:05:05 | `sudo bash /opt/hbd/deploy-payme.sh` — which at that moment `exec`ed the cutover | `sudo[163418]` in the journal |
| 14:05:05 | dump taken: `/var/backups/hbd/pre-cutover-20260910-140505.sql.gz`, 15 468 B | `ls -la /var/backups/hbd` |
| 14:05:06–07 | **all four units stopped** | `Stopping hbd-{bot,worker,admin,payme}.service` |
| — | first attempt died. It left no Postgres error and no `/etc/bayram`, so it did not reach step 3 | absence of both |
| ~14:06:46 | `/opt/hbd/migrations/env.py` and `alembic.ini` overwritten with their **post-rename** versions — see §8.8, this is still broken today. Who did it is `[UNPROVEN]`; the cutover only ever copies *out of* that directory (`:99`) | file mtimes; `env.py:57` |
| 14:06:53 | entered again; second dump `pre-cutover-20260910-140653.sql.gz`, 15 466 B | `sudo[163756]` |
| 14:06:54 | `/etc/bayram/{bayram.env,bayram-admin.env,payme.env}` written | file mtimes, to the centisecond |
| 14:06–14:07 | fresh venv built at `/opt/bayram/venv`; the `bayram` wheel installed | `direct_url.json`, `sha256=84cf7ec4…87c984` |
| 14:07 | migrations copied; alembic executed as root | root-owned `__pycache__/env.cpython-312.pyc` |
| **14:07:26.883** | **`hbd@hbd ERROR: no schema has been selected to create in at character 15`**, `STATEMENT: CREATE TABLE alembic_version (…)` | `/var/log/postgresql/postgresql-16-main.log:414-415` |
| — | step 6 never ran: **no `bayram-*.service` file was ever written and the journal has never mentioned one** | `ls /etc/systemd/system`; `journalctl \| grep -c "bayram-.*\.service"` → `0` |
| 14:08:00–14:08:01 | an operator recovered by hand: three `systemctl restart` and one `systemctl start`, through the `NOPASSWD` verbs | `sudo[163966,163969,163972,163975]` |
| 14:24–14:33 | the `alembic_version` revision and the owner role's grants probed repeatedly; `sudo -u postgres psql` refused for want of a password at 14:24:44 | `sudo` audit trail |
| 14:28:31 | `/opt/hbd/deploy-payme.sh` **repointed** at a new `diagnose.sh` — see §8.4 | file mtimes; `sudo[171314]` |

**A 2 min 54 s outage of all four processes**, with nothing restarting them automatically — the
script's own stage `2/9` *stops* the fleet, and a stopped unit is not a failed one. The same window is recorded, from the Caddy side, in
[`04-release.md`](04-release.md) §0.4 warning 3 — `502` to `admin.bayrambot.uz` at 14:05:12,
14:06:12 and 14:07:12.

### 2.2 What is on the machine right now, and what it is not

`[HOST 2026-09-11]`:

```
/etc/bayram                     drwxr-xr-x  root:root   0755   ← LOOSER than /etc/hbd's 0750
/etc/bayram/bayram.env          -rw-r-----  root:hbd    1 148 B   2026-09-10 14:06:54
/etc/bayram/bayram-admin.env    -rw-r-----  root:hbd   11 213 B   2026-09-10 14:06:54
/etc/bayram/payme.env           -rw-r-----  root:hbd      361 B   2026-09-10 14:06:54
/opt/bayram/venv                              ← a real venv; `import bayram` succeeds
/opt/bayram/migrations                        ← a copy
/opt/bayram/migrations/migrations             ← a SECOND copy, inside the first (§8.6)
/etc/systemd/system/bayram-*.service          ← DOES NOT EXIST, and never has
```

Two consequences an operator must hold at once. **The debris is inert** — no unit points at it,
nothing executes it, and `systemctl list-unit-files | grep -i bayram` returns nothing
`[HOST 2026-09-11]`. **And the debris is a secrets copy**: three `0640 root:hbd` files under a
`0755` directory, holding a `sed`-rewritten snapshot of the production configuration as it stood
at 14:06:54 on 2026-09-10. The files themselves are no more readable than the originals — `cat
/etc/bayram/bayram.env` is `Permission denied` from `developer` `[HOST 2026-09-11]` — but the
directory is now world-listable where `/etc/hbd` is not, and that is `chmod 0755 "$NEW_ETC"` at
`deploy/cutover-to-bayram.sh:73` doing exactly what it says `[TREE 2026-09-11]`.

**Whether that snapshot is still current is `[UNPROVEN]`** and it matters: `/etc/hbd` is `0750
root:hbd`, so `developer` cannot even `stat` the originals to compare mtimes. Treat
`/etc/bayram/*` as a 2026-09-10 snapshot, never as the configuration — §5 step 5 rewrites all
three from source for this reason.

### 2.3 Why it failed, which nobody had established

**The owner role `hbd` has no rights on schema `public`, and the database rebuild that morning is
what took them away.**

The chain, each link checkable:

1. The migration connected as role `hbd` to database `hbd` and **authenticated successfully** —
   it got far enough to execute a statement `[HOST 2026-09-11]`. So role `hbd` exists, and
   `/etc/bayram/bayram.env` carries a working `BAYRAM_DB_MIGRATION_URL` for it. (`migrations/env.py:96-129`
   reads `BAYRAM_DB_MIGRATION_URL` first and falls back to `BAYRAM_DATABASE_URL` with a WARNING
   `[TREE 2026-09-11]`; the `hbd@hbd` in the log is the former having been found.)
2. It then failed on `CREATE TABLE alembic_version` with *"no schema has been selected to create
   in"*. That is Postgres saying the effective `search_path` resolved to **nothing** — which is
   what happens to a role with neither `USAGE` nor `CREATE` on `public`.
3. It tried to *create* `alembic_version` at all because, to that role, the table is not visible.
   The database is not empty; [`04-release.md`](04-release.md) §0.2 records it at `0024`
   `[HOST 2026-09-11]`.
4. The grants went missing on the morning of the same day. `/opt/hbd/release/wipe-and-rebuild.sh`
   ran `DROP SCHEMA public CASCADE; CREATE SCHEMA public; GRANT ALL ON SCHEMA public TO
   ${APP_ROLE}; GRANT ALL ON SCHEMA public TO postgres;` (`:112-115`), and `APP_ROLE` is parsed
   out of the **application** DSN's userinfo (`:51`) `[HOST 2026-09-11]`. Every backend on this
   host connects as `hbd_app` ([`01-architecture.md`](01-architecture.md) §"PostgreSQL"), so the
   re-`GRANT` restored the application role and `postgres` — **and not the owner.**
5. Two later `FATAL: password authentication failed for user "hbd"` entries at 14:26:10 and
   14:45:18 `[HOST 2026-09-11]` are somebody trying to reach that role by hand afterwards, and
   the `DETAIL` names only the `pg_hba.conf` line, not a missing role.

**So: the first step of this cutover is a `GRANT`, issued by `postgres`, and it is not in the
script.** §4.1. Nothing about this is a defect in `cutover-to-bayram.sh`; the script correctly
refused to continue.

> **`[UNPROVEN]`, and it is the one question the window cannot open without.** Whether role `hbd`
> *currently* holds `USAGE` and `CREATE` on `public` cannot be read from `developer`: `psql` is
> not in the `NOPASSWD` drop-in and `sudo -n` wants a password. There is a script on the host that
> answers it with one password, `/opt/hbd/diagnose.sh`, and §4.1 gives both it and the raw query.

---

## 3. The complete inventory — what moves, what stays, what deliberately does not

Everything in this section was read off the machine or the tree on 2026-09-11. Where a row is a
claim about the *target* state it is the staged script's target, cited by line.

### 3.1 The package, the distribution and the module paths

| | Host today `[HOST 2026-09-11]` | Target `[TREE 2026-09-11]` |
| --- | --- | --- |
| Installed package | `hbd` in `/opt/hbd/venv/lib/python3.12/site-packages/` | `bayram` |
| Distribution | `hbd_bot-0.1.0`, from `hbd_bot-0.1.0-20260909-py3-none-any.whl` | `bayram_bot-0.1.0` |
| Interpreter | Python 3.12.3, stdlib `venv`, no `uv`, no `.pth` | unchanged |
| Module paths in `ExecStart` | `hbd.main`, `hbd.worker.WorkerSettings`, `hbd.admin.app:app`, `hbd.payme.app:app` | `bayram.*` |
| Import test | `python -c "import hbd"` OK; `import bayram` → `ModuleNotFoundError` | the inverse, and `/opt/bayram/venv` already passes it |

The staged wheel: `/opt/hbd/release/bayram_bot-0.1.0-py3-none-any.whl`, **5 219 850 bytes**, dated
2026-09-10 14:03, `sha256=84cf7ec4b8af878cd4ecdfd58966a6e37e291fdcc899f8e90603f6728087c984` —
recorded in `/opt/bayram/venv/.../bayram_bot-0.1.0.dist-info/direct_url.json`, because it has
already been installed there once `[HOST 2026-09-11]`.

> **Its filename is legal and undated, and that is a trap of its own.**
> `bayram_bot-0.1.0-py3-none-any.whl` parses — five PEP 427 parts, so it is not the
> `hbd_bot-0.1.0-PAYME-20260909.whl` mistake [`08-payme.md`](08-payme.md) §11.2 records. But it
> carries **no build tag**, so nothing in the name says which build it is, and
> `/opt/hbd/release/` already holds an undated `hbd_bot-0.1.0-py3-none-any.whl` from 2026-09-06
> alongside four other wheels `[HOST 2026-09-11]`. Write the `sha256` above into the window's
> notes before you start: after the install, `direct_url.json` is the only place on the box that
> says which file is in the venv ([`04-release.md`](04-release.md) §0.1).

The wheel's contents were asserted, not assumed: it carries `bayram/`, the billing router and a
non-empty `bayram/admin/static/` bundle — those three are the script's own preflight
(`deploy/cutover-to-bayram.sh:44-50`) and they pass `[HOST 2026-09-11]`.

**One more thing inside the wheel, and it is the kind of mismatch that ships a broken panel.**
The console shell's CSP nonce is substituted by a literal string match: `CSP_NONCE_PLACEHOLDER:
Final[str] = "__BAYRAM_CSP_NONCE__"` (`src/bayram/admin/shell.py:55`), and
`shell.py:78` refuses the response if the placeholder is absent `[TREE 2026-09-11]`. The deployed
bundle today carries the **pre-rename** spelling `__HBD_CSP_NONCE__` and `<title>hbd
dashboard</title>`; the staged wheel carries `__BAYRAM_CSP_NONCE__` and `<title>Bayram —
Tabriklar, Qoʻshiqlar</title>` `[HOST 2026-09-11]`. **Both halves are internally consistent,
because both travel inside one wheel** — which is the whole reason the bundle is packaged rather
than built on the host ([`01-architecture.md`](01-architecture.md) §"The console is a build
artefact the API serves itself"). The failure to avoid is mixing them: an old bundle served by
new code, or the reverse, renders a panel whose stylesheet is blocked by its own CSP. Never copy
`static/` between venvs.

### 3.2 The four units, directive by directive

Host, all four `[HOST 2026-09-11]` (`systemctl show`, `systemctl cat`, `ls -la
/etc/systemd/system`):

| | `hbd-bot` | `hbd-worker` | `hbd-admin` | `hbd-payme` |
| --- | --- | --- | --- | --- |
| File | 951 B, Sep 5 18:01 | 809 B, Sep 5 18:01 | 1 306 B, Sep 5 18:01 | 5 022 B, Sep 9 23:39 |
| `ExecStart` | `-m hbd.main` | `-m arq hbd.worker.WorkerSettings` | `-m uvicorn hbd.admin.app:app --host 127.0.0.1 --port 8080` | `-m uvicorn hbd.payme.app:app --host 127.0.0.1 --port 8091` |
| `User` / `Group` | `hbd` / `hbd` | same | same | same |
| `WorkingDirectory` | `/var/lib/hbd` | same | same | same |
| Config reaches it by | `EnvironmentFile=/etc/hbd/hbd.env` | `EnvironmentFile=/etc/hbd/hbd.env` | `EnvironmentFile=/etc/hbd/hbd-admin.env` | `Environment=HBD_PAYME_ENV_FILE=/etc/hbd/payme.env`, **no** `EnvironmentFile` |
| `Restart` / `RestartSec` | `on-failure` / 5 s | `on-failure` / 5 s | `on-failure` / 5 s | **`always`** / 5 s |
| `TimeoutStopSec` (effective) | 20 s | 1 min | 20 s | 1 min 30 s — systemd's default, not a decision |
| `ProtectSystem` | `strict` | `strict` | `strict` | `strict` |
| `ReadWritePaths` | `/var/lib/hbd /var/log/hbd` | `/var/lib/hbd /var/log/hbd` | **empty** | **empty** |
| `InaccessiblePaths` | — | — | — | `/etc/hbd/hbd.env /etc/hbd/hbd-admin.env` |
| Extra hardening | — | — | — | `MemoryDenyWriteExecute=yes`, `RestrictNamespaces=yes`, `RestrictAddressFamilies=AF_INET AF_INET6 AF_UNIX` |
| Shared by all four | `NoNewPrivileges`, `PrivateTmp`, `PrivateDevices`, `ProtectHome`, `ProtectKernelTunables`, `ProtectKernelModules`, `ProtectControlGroups`, `RestrictSUIDSGID`, `RestrictRealtime`, `LockPersonality`, `StandardOutput=journal` | | | |

All four are `enabled` and `active`; the running PIDs date from 2026-09-11 06:50 rather than the
deploy, because `unattended-upgrades` bounced the fleet that morning
([`04-release.md`](04-release.md) §0.2, item 4) `[HOST 2026-09-11]`.

> **The staged units are a security DOWNGRADE on four counts, and nobody has recorded it.**
> `deploy/cutover-to-bayram.sh:107-127` writes one `common()` block for all four units
> `[TREE 2026-09-11]`. Against the table above, that block:
>
> 1. **grants `ReadWritePaths=/var/lib/hbd /var/log/hbd` (`:125`) to the admin API and the
>    gateway**,
>    which have none today. The panel's read-only object store is not a `:ro` mount — it is
>    `ProtectSystem=strict` with an empty `ReadWritePaths`, and the current unit says so in its
>    own comment ([`01-architecture.md`](01-architecture.md) Decision 1). The new units hand the
>    panel write access to the media archive it is only supposed to stream, and hand the
>    money-handling gateway write access to both.
> 2. **drops `PrivateDevices`** from all four.
> 3. **drops the gateway's `MemoryDenyWriteExecute`, `RestrictNamespaces` and
>    `RestrictAddressFamilies`** — the three directives that exist only on the process holding the
>    cashbox key.
> 4. **changes the gateway to `Restart=on-failure` and `TimeoutStopSec=20`** from `always` and
>    90 s.
>
> It adds nothing in exchange: every kernel-protection directive it sets is already set on all
> four units today. **Fix the `common()` block before the window, or you will trade a payment
> outage for a quieter permanent regression.** §4.6 makes it a precondition and §5 step 9 is where
> the corrected block is written. `InaccessiblePaths`
> is the one thing it gets right — `:152` repoints it at `/etc/bayram/bayram.env` and
> `/etc/bayram/bayram-admin.env`, which is the correct translation.

### 3.3 The service account, file ownership, state and logs — all of which STAY

`[HOST 2026-09-11]`:

```
hbd:x:995:986::/var/lib/hbd:/usr/sbin/nologin      # getent passwd hbd
hbd:x:986:                                          # getent group hbd — NO members
/var/lib/hbd   0750  hbd:hbd        # the media archive and the workspace
/var/log/hbd   0755  hbd:hbd        # exists, EMPTY; the bot/worker grant on it is unused
/etc/hbd       0750  root:hbd
/opt/hbd       0755  developer:developer
```

There is **no `bayram` user and no `bayram` group**, and `/var/lib/bayram` and `/var/log/bayram`
do not exist `[HOST 2026-09-11]`.

**They should not be created, and the argument is the script's own** (`:13-18`
`[TREE 2026-09-11]`): the `hbd` account owns the media archive, so renaming it means `chown`ing
customer artefacts during a cutover — *"risk bought for tidiness"*. The staged units therefore
keep `User=hbd`, `Group=hbd` and `WorkingDirectory=/var/lib/hbd`, and that is the right call.

**This is also where the repository's own `deploy/` units must be refused.**
`deploy/systemd/bayram-*.service` say `User=bayram`, `WorkingDirectory=/srv/bayram` and
`ExecStart=/srv/bayram/.venv/bin/python`, and the payme one disagrees even with its three
siblings (`/var/lib/bayram`, `/opt/bayram/venv`) `[TREE 2026-09-11]`. `/srv` is empty on this
machine and always has been ([`04-release.md`](04-release.md) §0, §0.3). Copying those four files
is not a shortcut; it is four different machines.

Because the user, the group and both state paths stay, **no file ownership changes at all** —
which removes the single largest source of risk a rename usually carries.

### 3.4 The venv — rebuilt, never moved

`mv /opt/hbd /opt/bayram` would produce a venv whose `pyvenv.cfg` and every console-script
shebang name an interpreter path that no longer exists. `deploy/cutover-to-bayram.sh:20-22`
states this and `:88-96` acts on it: `rm -rf "$NEW_ROOT/venv"`, `python3 -m venv`, install the
wheel, `pip check`, then an explicit `import bayram, bayram.payme.app, bayram.admin.app`
`[TREE 2026-09-11]`.

`pip check` immediately after the install is the `pillow` lesson
([`08-payme.md`](08-payme.md) §11.5) carried forward correctly, and the import assertion is
better than anything the previous deploy had: it turns "the wheel installed" into "the three
entry points the units name can actually be imported".

`/opt/hbd/venv` is **kept**. It is the rollback (§6).

### 3.5 The dotenv directory, the filenames, and every variable prefix inside them

| | Host today `[HOST 2026-09-11]` | Target `[TREE 2026-09-11]` |
| --- | --- | --- |
| Directory | `/etc/hbd`, `0750 root:hbd` | `/etc/bayram` — and the script makes it `0755` (§8.7) |
| Bot + worker | `hbd.env` | `bayram.env` |
| Admin | `hbd-admin.env` | `bayram-admin.env` |
| Gateway | `payme.env` | `payme.env` — the only filename that does not change |
| Every key inside | `HBD_*` | `BAYRAM_*` |
| Selector variables | `HBD_PAYME_ENV_FILE` is the only one set anywhere | `BAYRAM_PAYME_ENV_FILE` |

**There are exactly three dotenv files.** No fourth is referenced by any unit or by any script on
the host. The bot and admin boot lines name `".env"` and `".env.admin"` — *relative* defaults,
unused, because those two processes are fed by `EnvironmentFile=` and the selector variable is
unset ([`00-host-inventory.md`](00-host-inventory.md) finding 6, rows 18–19). Whether
`/var/lib/hbd/.env` exists at all is `[UNPROVEN]`: the directory is `0750 hbd:hbd` and
`developer` cannot traverse it. **Do not write a fourth file into any runbook.**

The rewrite is a one-line `sed` and its narrowness is deliberate: `sed 's/^HBD_/BAYRAM_/'`
(`:76`) anchors at the start of a line, so a *value* that happens to contain `HBD_` — a URL, a
comment, a note — is left alone. Modes and ownership are copied from the source with `chown
--reference` and `chmod --reference` (`:77-78`) rather than assumed, because `payme.env` is
`0640 root:hbd` and the gateway cannot read it if that is lost (`:71`). That the rewritten copies
on the host are all `0640 root:hbd` `[HOST 2026-09-11]` is therefore evidence that the three
**sources** are too — an inference from the script's mechanism, not a direct read, since none of
the three is readable from `developer`.

One value, not just a key, has to change: `BAYRAM_PAYME_ENV_FILE` inside `payme.env` still points
into `/etc/hbd` after the `sed`, and `:86` fixes it with a second pass. **Nothing else is checked
for a path in a value, and that is the gap in §5 step 4's check.** `BAYRAM_DATABASE_URL`,
`BAYRAM_REDIS_URL`, `BAYRAM_DB_MIGRATION_URL` and `BAYRAM_ADMIN_AUDIT_DSN` are values; so is
`BAYRAM_ADMIN_DATA_ROOT` if it is set. **How many keys each file holds, and which of them carry a
filesystem path, is `[UNPROVEN]`** — the permission wall again. The counts the window should
expect from the tree are `.env.example` 100 assignments, `.env.admin.example` 37,
`.env.payme.example` 20 `[TREE 2026-09-11]`, and the script prints `grep -c '^BAYRAM_'` for each
rewritten file (`:79`), which is the number to compare against.

### 3.6 The `NOPASSWD` sudoers drop-in

`/etc/sudoers.d/hbd-deploy`, for user `developer`, read in full from `sudo -n -l`
`[HOST 2026-09-11]`:

```
(root) NOPASSWD: /usr/bin/bash /opt/hbd/deploy-payme.sh
(root) NOPASSWD: /usr/bin/systemctl daemon-reload
(root) NOPASSWD: /usr/bin/systemctl {enable|disable|start|stop|restart|status|is-active} hbd-payme.service
(root) NOPASSWD: /usr/bin/systemctl restart hbd-{bot,worker,admin}.service
(root) NOPASSWD: /usr/bin/systemctl {reload|restart} caddy.service
(root) NOPASSWD: /usr/bin/journalctl -u hbd-payme *
(root) NOPASSWD: /usr/bin/tee /etc/hbd/payme.env
(root) NOPASSWD: /usr/bin/tee /etc/caddy/Caddyfile
(root) NOPASSWD: /usr/bin/caddy validate --config /etc/caddy/Caddyfile --adapter caddyfile
(postgres) NOPASSWD: /usr/bin/pg_dump hbd
```

`developer` also has `(ALL : ALL) ALL` — full `sudo`, **with a password**. A separate pre-existing
block covers the unrelated `aizu` service and is nothing to do with us.

**Every verb in that list names an `hbd-*` unit or an `/etc/hbd` path.** The script knows and
says so at `:174` — *"`/etc/sudoers.d/hbd-deploy` still names the hbd-* units and will not cover
bayram-*"* — and then does nothing about it `[TREE 2026-09-11]`. §8.3 is what that costs, in both
directions.

### 3.7 Redis key strings — nine of them, and the rename moves every one

`grep` of every `"hbd…"` / `"bayram…"` literal in the installed package, the staged wheel and the
tree returns **twelve** strings each, in one-to-one correspondence `[HOST+TREE 2026-09-11]`. Nine
are Redis keys:

| Key (host → target) | Written by | What a silent move costs |
| --- | --- | --- |
| `hbd:payme:paused` → `bayram:payme:paused` | `payme/pause.py:75` | **A paused rail silently un-pauses.** §1.1 |
| `hbd:send:park` → `bayram:send:park` | `runtime/pacer.py:96` | **A flood-wait park is forgotten.** Its presence means *Telegram told us to stop* and its TTL is how much longer; the new fleet does not see it and resumes sending into the wait |
| `hbd:send:budget` → `bayram:send:budget` | `runtime/pacer.py:94` | One wall-clock second of outbound accounting. The bucket is per-second and shared by name on purpose; losing one is nothing |
| `hbd:bot:rl` → `bayram:bot:rl` | `ratelimit.py:88` | Per-user bot rate-limit counters reset — a fresh allowance |
| `hbd:admin:rl` → `bayram:admin:rl` | `admin/security/ratelimit.py:134` | **The login rate-limit window resets**, including a brute-force window in progress |
| `hbd:admin:budget` → `bayram:admin:budget` | `admin/security/budget.py:110` | The reveal budget's hourly/daily counters reset, so an operator's spent privacy allowance is refunded by accident |
| `hbd:admin:reveal:window` → `bayram:admin:reveal:window` | `admin/services/assets.py:152` | An open audio-reveal window is dropped; the next request re-opens and re-audits one |
| `hbd:admin:session` → `bayram:admin:session` | `admin/sessions.py:80` | **Nothing.** It is a ≤60 s mirror over a Postgres row that is re-read every request (`sessions.py:75-82`), so sessions survive and pay one extra read |
| `hbd:settings:version` → `bayram:settings:version` | `admin/routers/health.py:51` | The config version reads `null` until the editor writes again |

Plus the tenth brand-bearing string, which is not a Redis key but is the expensive one: the
vendor idempotency prefix of §1.1.

The remaining three are harmless and are listed so a future `grep` is not mistaken for a finding:
`bayram-demo-` (a `TemporaryDirectory` prefix, `demo.py:215`), `bayram-touch-drain` (an asyncio
task name, `bot/gate.py:288`) and `bayram-admin-nonexistent-account-placeholder` (the dummy
password that keeps a missing account's login constant-time, `admin/security/passwords.py:62`)
`[TREE 2026-09-11]`.

> **Only two of the nine are worth acting on during the window**, and the rest are recorded so
> that nobody has to guess: `payme:paused`, because an un-paused payment rail is the worst
> outcome on the page, and `send:park`, because a forgotten flood wait turns into a second flood
> wait. §5 step 2 reads both before the fleet stops and §5 step 11 re-arms them under the new
> names. **At the time of reading, neither key is set** — `DBSIZE` is 5 and none of the five is a
> brand key `[HOST 2026-09-11]` — so if the window opened now there would be nothing to carry.
> That is a live gauge, not a fact about tomorrow: read it again in the window.

### 3.8 Caddy and cloudflared — nothing functional moves

**cloudflared needs no change.** The ingress it was last pushed names four hostnames and two
loopback ports and no package, unit, user or path: `aizu.uz` and `www.aizu.uz` →
`http://127.0.0.1:8765`, `admin.bayrambot.uz` → `http://127.0.0.1:80`, `pay.bayrambot.uz` →
`http://127.0.0.1:80`, then `http_status:404`. Config `version=4`, pushed
`2026-09-09T19:18:03Z` `[HOST 2026-09-11]`. It is edited in the Cloudflare Zero Trust dashboard
and not on this host, so there is nothing here to get wrong.

**Caddy needs no functional change either.** Both `bayrambot.uz` site blocks proxy to
`127.0.0.1:8080` and `127.0.0.1:8091` by port, and the ports do not move. What Caddy *does* carry
is eight comment lines naming `hbd`. **Quoting them verbatim, because they are the Caddyfile's
text and not this tree's citations** — two of them name source paths that have never existed in
this repository, since the package here is `bayram` and was `hbd` only on the host:
`hbd-admin.service`, `journalctl -u hbd-payme`, `` `src/hbd/admin/app.py:238-239` `` (as written
in the Caddyfile; the file here is `src/bayram/admin/app.py`),
`HBD_ADMIN_TRUSTED_PROXY_HOPS=2`, `HBD_ADMIN_PORT`,
`` `src/hbd/admin/security/clientip.py` `` (likewise `src/bayram/...` here) and a reference to
`/etc/hbd/admin.env`, which is not even the right filename today (it is `hbd-admin.env`)
`[HOST 2026-09-11]`. Those are documentation
inside a config file and they will be wrong after the cutover. Fix them in the same window or
they become the next person's false lead — and remember that editing the Caddyfile is a
`tee`-through-`sudo` operation whose reload has its own permission trap
([`08-payme.md`](08-payme.md) §4.4). **Do not touch the `http://` scheme on either block while
you are in there** (§4.3 of the same page; it cost a day once).

### 3.9 Everything else on the host that answers to the old name

`[HOST 2026-09-11]`:

- **`/usr/local/bin/hbd-migrate`**, `0750 root:root`. Already known to be broken — it passes its
  Alembic command as one argument ([`00-host-inventory.md`](00-host-inventory.md) row 48). It is
  not readable from `developer`, nothing in any unit calls it, and after the cutover it is a
  command that exists, is named after the old brand, and does nothing useful. Remove it or
  replace it; do not leave it.
- **`/opt/hbd/release/`** — five wheels, four one-shot scripts, one Caddy site file. The
  `-ROLLBACK-` and `-DASHBOARD-` wheels are PEP 427-invalid and un-installable as they stand
  ([`08-payme.md`](08-payme.md) §11.2).
- **`/var/backups/hbd/`** — nine dumps. The backup directory keeps its name; the working-tree
  `deploy/deploy-payme.sh` writes to `/var/backups/bayram`, which does not exist and which no
  inventory row knows to look in ([`04-release.md`](04-release.md) §0.4 warning 4). Do not create
  it.
- **No timers, no cron, no logrotate** under either name: `systemctl list-timers --all` shows
  nothing of ours, and `/etc/logrotate.d/` has no `hbd` entry. The five clocks are ARQ crons
  inside the worker ([`01-architecture.md`](01-architecture.md) §"Only the worker runs the
  clocks"), so they move with the wheel and need no separate step.
- Among files `developer` can read, **only the four unit files** reference `/opt/hbd` or
  `/etc/hbd`. The sudoers drop-in does too (§3.6), via `sudo -l` rather than a read. Whether
  anything under `/etc` that `developer` cannot read references them is `[UNPROVEN]`.

### 3.10 The one thing in the fleet that is already half-renamed

**`/opt/hbd/migrations/` is post-rename and the live venv cannot run it.** `env.py:57-59` is
`from bayram.config import env_file, load_settings` and two more `bayram.db.*` imports; the live
venv has no `bayram` package, so today:

```
$ /opt/hbd/venv/bin/python -m alembic -c /opt/hbd/migrations/alembic.ini current
ModuleNotFoundError: No module named 'bayram'
```

`[HOST 2026-09-11]`, and `alembic.ini:15` compounds it — `prepend_sys_path = %(here)s/../src`,
i.e. `/opt/hbd/src`, which does not exist on a wheel host. This is fully documented in
[`04-release.md`](04-release.md) §0.4 warning 1, including the three candidate repairs and the
fact that **no `hbd`-era copy of `env.py` exists on the box**. It is repeated here for one
reason: **it means the pre-cutover state has no working migration path, so "migrate, then decide"
is not available.** The only interpreter on the host that can run a migration today is
`/opt/bayram/venv`, which is the failed cutover's debris.

### 3.11 What deliberately does NOT move — the database name

**The database stays `hbd`. Renaming it is risk with no return.**

The argument is [`09-payme-go-live.md`](09-payme-go-live.md) §2's and it survives contact with
everything on this page: the name appears in `BAYRAM_DATABASE_URL` (and
`BAYRAM_DB_MIGRATION_URL`) and nowhere else. It is not in a unit file, not in the Caddyfile, not
in the tunnel ingress, not in a Redis key and not in a filename the application opens. Renaming a
live database to match a brand means either `ALTER DATABASE … RENAME TO` with every client
disconnected, or a dump-and-restore — in both cases a step that can fail *after* the point where
the old name is gone, in exchange for nothing an operator will ever read.

The same reasoning retires three more candidates, and each has its own argument above: the OS
user and group `hbd` (§3.3 — it owns customer artefacts), `/var/lib/hbd` and `/var/log/hbd`
(§3.3), and `/var/backups/hbd` (§3.9 — an incident must find the dumps where the inventory says
they are). The role names `hbd_app` and `hbd` stay too, for the same reason the database name
does: they live in a DSN and nowhere else.

**What you are left with is a rename of the things that are *code and configuration* and nothing
that is *data*.** That is the property that makes a one-hour window defensible, and any proposal
that extends the rename to a data object should be refused on this page's evidence rather than
re-argued.

---

## 4. Preconditions — the window does not open until all seven are true

The first one is new, is not in the script, and is why the last attempt failed.

### 4.1 The owner role must be able to create in schema `public`

**Ask first.** There is a read-only script on the host that answers it and it needs one password:

```bash
ssh -t aizu 'cat /opt/hbd/diagnose.sh && sudo bash /opt/hbd/deploy-payme.sh'
```

`/opt/hbd/deploy-payme.sh` is the `NOPASSWD` entry point and it currently `exec`s
`/opt/hbd/diagnose.sh`, which runs four `sudo -u postgres psql -At` SELECTs:
`has_schema_privilege('hbd','public','CREATE')`, the same for `'USAGE'`, the `alembic_version`
table owner, and the distinct table owners in `public` `[HOST 2026-09-11]`. **`cat` it before you
run it, every time** — §8.4 is why. Or ask Postgres directly, which needs the `sudo` password:

```bash
ssh -t aizu "sudo -u postgres psql -d hbd -Atc \"
  select has_schema_privilege('hbd','public','USAGE'),
         has_schema_privilege('hbd','public','CREATE'),
         (select version_num from alembic_version)\""
```

**If either privilege is `f`, the remedy is one statement**, issued as `postgres`, and it is the
first thing the window does:

```sql
GRANT USAGE, CREATE ON SCHEMA public TO hbd;
```

Nothing else about the schema needs touching: the tables exist and are owned by whoever the
rebuild left owning them (`diagnose.sh`'s fourth query answers that). **Record the `before` and
`after` of both privileges in the window's notes** — this is the step whose absence cost 2 min
54 s on 2026-09-10, and a window that does not write down what it granted cannot hand the
question to 07-security afterwards.

> **`[UNPROVEN]` until somebody runs the above.** Which role *owns* the tables, and whether
> migration `0007`'s `REVOKE UPDATE, DELETE, TRUNCATE ON public.admin_audit_log` is in force, are
> the same question's neighbours and are also unreadable from `developer`
> ([`01-architecture.md`](01-architecture.md), the two-Postgres-roles bullet). Answer all of them
> in one password rather than three.

### 4.2 Somebody in the window must be able to authenticate `sudo` interactively

`sudo bash /opt/hbd/cutover-to-bayram.sh` is **not** in the `NOPASSWD` drop-in (§3.6). Neither is
`systemctl enable` for the bot, the worker or the admin — the drop-in grants `restart` for those
three and the full verb set only for `hbd-payme` `[HOST 2026-09-11]`. **So both the cutover and
the rollback need the password.** Establish, before the fleet stops, that the person at the
keyboard has it and that `sudo -v` succeeds. This is the cheapest possible precondition and the
most expensive one to discover halfway through step 11, with the fleet down and the rollback
asking for a password too.

> **Do not solve this by repointing `/opt/hbd/deploy-payme.sh` at the cutover script.** It is
> `developer`-writable and `NOPASSWD`-invokable, which is exactly the shape §8.4 warns about, and
> on 2026-09-10 that is how a privileged path came to mean two different things in 26 minutes.

### 4.3 The rail must be quiesced, and its two carry-over keys read

Not because the queue would break — §1.2 establishes that it would not — but because a **vendor**
call retried across the prefix change pays twice. Let the pipeline drain, confirm no
`generate_and_deliver` is in flight, and read both keys that do not survive:

```bash
ssh aizu 'redis-cli DBSIZE; redis-cli KEYS "hbd:*"; redis-cli KEYS "arq:in-progress:*"'
ssh aizu 'redis-cli GET hbd:payme:paused; redis-cli TTL hbd:send:park'
```

Write both answers down. §5 step 11 puts them back under the new names.

### 4.4 No unsettled payment may be in flight

A `CreateTransaction` that has not yet been `PerformTransaction`ed is a customer waiting. The
gateway's own state is in Postgres and survives, but the window's three minutes of downtime are
three minutes of `-32400` to Payme, which they retry. Check the board or the CLI — the pause
switch has two writers and both are legitimate ([`09-payme-go-live.md`](09-payme-go-live.md)
§11.2) — and prefer a window with nothing open.

### 4.5 The wheel, its hash, and revision `0025`

The staged wheel and `sha256` are §3.1. Revision `0025` must be on disk at
`/opt/hbd/migrations/versions/20260910_1000_0025_index_settlement_clocks.py` — it is
`[HOST 2026-09-11]` — because **a wheel carries no migrations** and `alembic upgrade head` means
*the head of the files in this directory*, which reports success over a schema three revisions
behind ([`08-payme.md`](08-payme.md) §11.3). The script asserts the file in its preflight
(`:51`).

`0025` only **adds an index** (`deploy/cutover-to-bayram.sh:27`, and the filename says
`index_settlement_clocks`) `[TREE 2026-09-11]`. That is the property the rollback rests on, and
§6 says what happens when it stops holding.

### 4.6 The `common()` block must be fixed first

§3.2's four downgrades. Edit `deploy/cutover-to-bayram.sh` in the tree, copy it to the host, and
diff it there. Do not edit it on the host only: `/opt/hbd` is `developer`-owned and the tree copy
is the one the next person reads.

### 4.7 A decision about the sudoers drop-in, taken before the window rather than in it

§8.3. The answer this page recommends is: **write a new drop-in that names both sets of units,
install it at step 8, and delete the `hbd-*` half only after §7 has passed.** A rollback that
needs a password it does not have is not a rollback.

---

## 5. The ordered cutover

### 5.0 What the staged script does NOT do

`deploy/cutover-to-bayram.sh` performs steps 3–9 and 11 below, and performs them well — though in
its own order, which stops the fleet earlier than step 7 does. It does
**not** do any of these, and five of the six are in this page's trap list:

1. the `GRANT` of §4.1 — **without which it fails in step 7 again**;
2. quiesce the pipeline, or read the two carry-over Redis keys (§4.3);
3. re-arm `payme:paused` or `send:park` under the new names (step 11);
4. replace the sudoers drop-in (§4.7) — it prints a `NOTE` at `:174` and moves on;
5. fix the hardening regression in its own `common()` block (§4.6);
6. re-run the settlement rehearsal (step 13).

It also **stops the fleet at step 2 of 9**, before the two steps that can fail, and runs
`set -uo pipefail` *without* `-e` (`:28`), so only its explicit `die` calls halt it
`[TREE 2026-09-11]`. §8.6 is the consequence. Run it with your eyes open, or run the steps.

### 5.1 The steps

Numbering is this page's; the script's own stage numbers are given where they match.

---

**1. Answer §4.1 and issue the `GRANT` if it is needed.** Nothing else happens until both
`has_schema_privilege` calls return `t`.

*Check:* both privileges `t`, and `select version_num from alembic_version` returns a revision.

---

**2. Quiesce; read and write down the two carry-over keys.** §4.3.

*Check:* `redis-cli KEYS "arq:in-progress:*"` is empty, and you have both values on paper.

---

**3. Preflight.** Script stage `0/9` (`:42-56`): the wheel exists and contains `bayram/`, the
billing router and a non-empty SPA bundle; revision `0025` is on disk; all four `hbd-*.service`
files exist; the `hbd` account exists.

*Check:* `preflight OK`. Every assertion here is deliberately one that needs no database, no env
file and no privilege, so it can run **before** anything irreversible — the same argument as
[`08-payme.md`](08-payme.md) §11.3.

---

**4. Back up the database.** Script stage `1/9` (`:58-62`): `sudo -u postgres pg_dump hbd | gzip >
/var/backups/hbd/pre-cutover-<stamp>.sql.gz`, and it refuses to continue on an empty dump.

*Check:* `ls -lh` shows a non-trivial file. A `pg_dump` that fails on permissions still creates a
zero-byte gzip, and a backup you did not check is a backup you do not have. Compare against the
existing `pre-cutover-*` files (15 468 B and 15 466 B on 2026-09-10) — a dump an order of
magnitude smaller means you dumped an empty schema.

---

**5. Rewrite the environment into `/etc/bayram`.** Script stage `3/9` (`:68-86`) — and note this
page reorders it **before** the stop, where the script has it after. The rewrite touches nothing
the running fleet reads: `/etc/hbd` is untouched and the four units do not know `/etc/bayram`
exists. Doing it first shortens the outage by however long three `sed`s take and, more
importantly, lets the key-count check below fail while the product is still up.

*Check:* the script prints `grep -c '^BAYRAM_'` per file (`:79`). Three non-zero counts, and
`grep -c '^HBD_'` must be **0** in all three. Then the one value that is not a key:

```bash
sudo grep -n 'ENV_FILE' /etc/bayram/payme.env      # must say /etc/bayram/payme.env
sudo grep -nE '=.*(/etc/hbd|/opt/hbd)' /etc/bayram/*.env   # must print NOTHING
```

The second command is the check the script does not have (§3.5). A surviving `/opt/hbd` in a
`DATA_ROOT` or a DSN is a silent misconfiguration.

---

**6. Build the fresh venv.** Script stage `4/9` (`:88-96`): `rm -rf`, `python3 -m venv`, `pip
install <wheel>`, `pip check`, then `import bayram, bayram.payme.app, bayram.admin.app`. Still no
outage — `/opt/bayram` is nothing's `ExecStart` yet.

*Check:* `bayram imports OK`, `pip check` clean, and

```bash
ssh aizu 'cat /opt/bayram/venv/lib/python3.12/site-packages/bayram_bot-0.1.0.dist-info/direct_url.json'
```

matches the `sha256` from §4.5. **This is the last step that can be abandoned at zero cost.**

---

**7. Stop the four `hbd-*` units.** Script stage `2/9` (`:64-66`). **The outage starts here** and
this page puts it as late as it can: every preceding step is reversible by deleting a directory.

*Check:* four `inactive`. Expect `502` on `admin.bayrambot.uz` from now until step 10 — that is
Caddy telling the truth.

---

**8. Migrate.** Script stage `5/9` (`:98-104`): copy `migrations/` to `/opt/bayram`, source
`/etc/bayram/bayram.env` with `set -a`, then `alembic current` and `alembic upgrade head` from
`/opt/bayram/venv`.

*Check:* `current` prints a revision **before** the upgrade — that is the step that failed on
2026-09-10, and it fails for want of a `GRANT`, not for want of a database. After `upgrade head`,
`current` and `heads` agree. **Read alembic's own WARNING**: if it says
`BAYRAM_DB_MIGRATION_URL is not set, so migrations are running as the application role`, then the
owner DSN did not survive the rewrite and migration `0007`'s `REVOKE` is not a control
([`04-release.md`](04-release.md) §4). Note the nested-copy hazard of §8.6 before you re-run
anything.

---

**9. Write the four `bayram-*` units, with the `common()` block of §4.6.** Script stage `6/9`
(`:106-158`), then `chmod 0644`, `daemon-reload`, and `systemd-analyze verify` on each.

*Check:* four units verify. Then diff the hardening against §3.2's table — `systemctl show -p
ReadWritePaths -p PrivateDevices -p MemoryDenyWriteExecute -p RestrictNamespaces -p
RestrictAddressFamilies -p Restart -p TimeoutStopUSec bayram-{bot,worker,admin,payme}` — and
confirm the admin and the gateway have **empty** `ReadWritePaths`.

---

**10. Install the new sudoers drop-in, naming both sets of units.** §4.7. Not in the script.

*Check:* `sudo -n -l` lists `bayram-*` verbs **and** still lists the `hbd-*` ones.

---

**11. Disable the old units; enable and start the new ones.** Script stages `7/9` and `8/9`
(`:160-166`). The old unit **files are kept** — `disable`, never `rm`. That is the rollback.

*Check — and this is the one that prevents two bots on one token:*

```bash
ssh aizu 'systemctl list-unit-files --no-legend | grep -iE "hbd|bayram"'
```

The four `bayram-*` must read `enabled`; the four `hbd-*` must read `disabled`. Then
`systemctl is-active` on all eight: four `active`, four `inactive`. §8.2 is what an `enabled`
`hbd-bot` costs after this point.

---

**12. Re-arm the two carry-over keys** from step 2, under their new names:

```bash
ssh aizu 'redis-cli SET bayram:payme:paused 1'        # ONLY if it was set at step 2
ssh aizu 'redis-cli SET bayram:send:park 1 EX <the TTL you wrote down>'
```

*Check:* `redis-cli GET bayram:payme:paused` agrees with the note from step 2, and the gateway's
own `cli status` agrees with Redis. **If the rail was paused before the window it must be paused
after it.** Prefer the CLI's own pause command over a raw `SET` if it is available to you — a raw
`SET` of the wrong value is how a pause becomes a no-op ([`09-payme-go-live.md`](09-payme-go-live.md)
§9.2).

---

**13. Run §7 in full, including the settlement rehearsal with a fresh `--run-id`.** The window is
not closed until §7.8 has passed.

---

## 6. Rollback, the half that does not roll back, and the point of no return

### 6.1 The rollback, which is two commands

```bash
ssh -t aizu 'sudo systemctl disable --now bayram-bot bayram-worker bayram-admin bayram-payme'
ssh -t aizu 'sudo systemctl enable  --now hbd-bot hbd-worker hbd-admin hbd-payme'
```

That is the script's own closing line (`:173`) and it works because three things were kept rather
than replaced: the four `hbd-*.service` files (disabled, not deleted), `/opt/hbd/venv` with the
`hbd` package in it, and `/etc/hbd/*.env` with its `HBD_*` keys. **Nothing in steps 1–12 deletes
any of them.** No network, no remote, no wheel to reinstall, about a minute.

**`systemctl enable` of the bot, the worker and the admin is not in the `NOPASSWD` drop-in**
(§3.6), so this needs the password. §4.2 is why you check that before step 7 rather than here.

### 6.2 The halves that do not roll back cleanly

| | Rolls back? |
| --- | --- |
| The four units, the venv, the package, the console bundle | **Yes, completely.** Both trees are on disk |
| `/etc/hbd/*.env` | **Yes** — untouched throughout |
| The **schema** | **No, and it should not.** `alembic downgrade` is deliberately not part of this procedure ([`08-payme.md`](08-payme.md) §11.7): a downgrade of a payment schema is a data-destroying operation run by somebody already having a bad day. What makes a code-only rollback *safe* is that `0025` only adds an index, so `0024`-era code ignores it |
| The **Redis keys** | **No, and the asymmetry bites in both directions.** Anything the `bayram` fleet wrote under `bayram:*` is invisible to the `hbd` fleet. A rail paused *after* the cutover and then rolled back is open again, for exactly the reason §1.1 gives — **re-read step 12's checks on the way back** |
| `bayram:send:park` | **No.** A flood wait entered under one name is served twice |
| Vendor idempotency keys | **No.** Every order in flight at the boundary can be charged twice, in either direction. This is the cost that makes the window's length matter |
| `/etc/bayram/*` | **Not removed.** A rollback leaves a second copy of the secrets on disk under a `0755` directory. Clean it up deliberately, later, when you are sure which way you went |
| The `GRANT` of §4.1 | **Not reverted, and should not be.** The owner role having rights on its own schema is the correct state regardless of which name the fleet runs under |
| The admin session mirror | **Yes, effectively** — it is a ≤60 s cache over Postgres |

### 6.3 The point of no return

**There is no filesystem point of no return in this operation, and that is the best property it
has.** Both package trees, both config directories and both unit sets coexist; the rollback is a
`systemctl` pair.

What is irreversible is narrower and worth naming precisely:

1. **The first non-additive migration.** Today `0025` adds an index, so rollback is free. The
   first revision that drops a column, narrows a type or renames anything inverts the argument
   and the answer at that point is a maintenance window with both fleets stopped, not a cleverer
   ordering ([`08-payme.md`](08-payme.md) §11.4). **Check the diff; do not inherit this page's
   conclusion.**
2. **Money that moves under the new name.** A settlement written under `bayram` is a receipt in
   the ledger; it is not undone by going back, and it should not be. The ledger's keys are
   brand-free (§1.2), so the rows are legible to both fleets — which is precisely why rolling
   back is safe and why the money is nonetheless final.
3. **Deleting the `hbd-*` half of the sudoers drop-in** (§4.7). Do it after §7 passes, never
   during the window.
4. **`rm -rf /opt/hbd`.** Don't, for weeks. It is the rollback.

---

## 7. The verification suite

Nine checks. None of the first eight needs a password. **A green check must not imply a claim it
does not support** — each row says what it proves and, where it matters, what it does not.

**7.1 One name, in four places.**

```bash
ssh aizu 'systemctl cat bayram-payme | grep -E "ExecStart|ENV_FILE"'
ssh aizu 'ls /opt/bayram/venv/lib/python3.12/site-packages/ | grep -ixE "hbd|bayram"'
ssh aizu '/opt/bayram/venv/bin/python -c "import bayram; print(bayram.__file__)"'
grep -n "ENV_PREFIX: Final" src/bayram/config.py
```

**7.2 Nothing answers to the old name.** The check that prevents two bots long-polling one
Telegram token and two workers draining one `arq:queue`:

```bash
ssh aizu 'systemctl list-unit-files --no-legend | grep -iE "hbd|bayram"'   # 4 enabled, 4 disabled
ssh aizu 'systemctl list-units --all --no-legend | grep -iE "hbd|bayram"'
ssh aizu 'ps -eo user,pid,args | grep -E "hbd\.|bayram\." | grep -v grep'  # exactly four, all bayram
ssh aizu 'ss -ltnp | grep -E "8080|8091"'                                  # one listener each
```

**7.3 The four boot lines, and the `env_file` each one names.**

```bash
ssh aizu 'journalctl -u bayram-bot   --since "10 min ago" -o cat | grep "host verified"'
ssh aizu 'journalctl -u bayram-admin --since "10 min ago" -o cat | grep "admin.boot.ok"'
ssh aizu 'journalctl -u bayram-payme --since "10 min ago" -o cat | grep "payme.boot.ok"'
ssh aizu 'journalctl -u bayram-worker --since "10 min ago" -o cat | grep "Starting worker for"'
```

Expect `environment` `prod` on the bot, the worker and the admin and `dev` on the gateway — that
drift is real, pre-existing and argued in [`02-configuration.md`](02-configuration.md); the
cutover neither causes nor fixes it, and a `prod` gateway after the window means somebody changed
a value they were not asked to. Expect the worker's banner to list **ten** functions. And note
what this check does *not* prove: the bot's and admin's `env_file` field will still name the
unused relative default (`.env`, `.env.admin`) because those two units are fed by
`EnvironmentFile=`. `systemctl show -p EnvironmentFiles` is the command that answers where
configuration came from ([`00-host-inventory.md`](00-host-inventory.md) rows 18–19).

**7.4 The pause key the new code reads is the key an operator would set.** Two strings that must
be identical; on 2026-09-10 they were not:

```bash
grep -n "PAYME_PAUSE_KEY: Final" src/bayram/payme/pause.py
ssh aizu 'grep -o "\"[a-z]*:payme:paused\"" /opt/bayram/venv/lib/python3.12/site-packages/bayram/payme/pause.py'
ssh aizu 'redis-cli KEYS "hbd:*"'      # should now be empty, or a list you decided to leave
```

**7.5 Postgres.** Backends still connect as the application role; the schema is at head:

```bash
ssh aizu 'ps -eo args | grep "^postgres: 16/main" | awk "{print \$3, \$4}" | sort | uniq -c'
ssh -t aizu 'sudo -u postgres psql -d hbd -Atc "select version_num from alembic_version"'
```

**7.6 The public path, end to end.**

```bash
ssh aizu 'curl -sS -o /dev/null -w "healthz=%{http_code}\n" http://127.0.0.1:8091/healthz'
ssh aizu 'curl -sS -o /dev/null -D - -H "Host: admin.bayrambot.uz" http://127.0.0.1/healthz | grep -iE "HTTP/|strict-transport"'
curl -sS -o /dev/null -w 'public root=%{http_code}\n' https://pay.bayrambot.uz/
curl -sS -X POST -H 'Content-Type: application/json' -d '{"method":"CheckPerformTransaction"}' \
  https://pay.bayrambot.uz/payme | head -c 200
```

Expect `healthz=200`; `200` with `Strict-Transport-Security: max-age=86400` through Caddy;
`public root=404`, which is the tunnel, Caddy and the site block all agreeing; and HTTP 200 with
`{"error":{"code":-32504}}` unauthenticated. **A `308` anywhere here is the trap of
[`08-payme.md`](08-payme.md) §4.3** and means somebody edited a site block's scheme.

**7.7 The console actually renders.** The CSP nonce substitution is a literal string match
(§3.1), so an unstyled panel is the symptom of a bundle/server mismatch:

```bash
ssh aizu 'curl -sS -o /dev/null -D - http://127.0.0.1:8080/ | grep -i content-security-policy'
ssh aizu 'curl -sS http://127.0.0.1:8080/ | grep -o "__[A-Z_]*CSP[A-Z_]*__"'   # must print NOTHING
```

A surviving placeholder in the response body means the substitution did not happen.

**7.8 The settlement rehearsal, with a FRESH `--run-id`.** **This is not optional and it is not a
formality.** [`09-payme-go-live.md`](09-payme-go-live.md) §4.0 says Gate C reopens after this
cutover, and here is where that becomes a step: **a settlement path proven under `hbd` is not a
settlement path proven under `bayram`.** The rename moved the package, the unit, the prefix and
nine Redis key strings in one window; the one thing that proves the path still works is walking
it.

```bash
sudo -u hbd env BAYRAM_PAYME_ENV_FILE=/etc/bayram/payme.env \
  /opt/bayram/venv/bin/python -m bayram.payme.harness \
    --endpoint http://127.0.0.1:8091/payme \
    --login Paycom \
    --run-id <A NEW ID — never e767f6ce> \
    --telegram-user-id <your own Telegram id>
```

It must run as `hbd`, because `payme.env` is `0640 root:hbd` and the harness reads its
configuration from the process environment only. Do not pass `--key`: it puts the cashbox key in
your shell history, and the harness falls back to `BAYRAM_PAYME_MERCHANT_KEY` from the file it was
pointed at. `--telegram-user-id` is required by the parser and is the point of the exercise.
`--amount` defaults to `700000` **tiyin** — 7 000 so'm; nothing multiplies by 100.

**Reuse of a run id is wrong here.** `--run-id` labels every idempotency key the run writes as
`harness:<run-id>:<scenario>`; the 2026-09-10 run id `e767f6ce` settled, and a paid order is
terminal and correctly refuses a second payment — so reusing it tests the replay guard and tells
you nothing about the settlement path.

Three things must all be true, in this order:

1. the harness prints a pass table with no failures (4/4 on 2026-09-10);
2. **a Telegram message actually arrived on a phone.** The harness can pass while the worker is
   wedged: the pass table asserts the enqueue, the phone asserts the delivery — and the worker is
   one of the four processes this window just replaced;
3. the invariant stops reporting the *old* counts on the next five-minutely sweep:

```bash
ssh aizu 'journalctl -u bayram-worker --since "15 min ago" -o cat | grep "settlement invariant"'
```

`transactions_performed`, `receipts_written` and `grants_written` must be **equal and non-zero** —
that is the assertion, because the three counts come from three different tables and the sweep
had no way to be told about the run. A mismatch is logged at ERROR and is never self-repaired.

> **The sweep's window is five minutes wide and it will lie to you once.** A sweep that fires
> *before* the harness starts reports counts that are perfectly correct and completely
> misleading; on 2026-09-10 the 13:30:00 sweep fired fourteen seconds before the run.
> [`09-payme-go-live.md`](09-payme-go-live.md) §0.1 is the standing record of that trap, and it
> applies again here: **wait for the next sweep rather than concluding the rehearsal did not
> settle.** Today's rolling 24 h window still reports `1, 1, 1` from the original go-live
> `[HOST 2026-09-11]`, so after a successful re-run expect the counts to *rise together*, not to
> appear from zero.

**7.9 An hour of quiet.** The five ARQ crons must all have fired at least once — retention at
`:17`, vendor balances at `:43`, the Payme sweep every five minutes on `:00/:05/:10…`, the
broadcast due-sweep on `:04/:09/:14…`, and the daily activity snapshot whenever 00:07 **local**
next comes round (the host is `Asia/Tashkent`, +05, and that is a real defect recorded in
[`01-architecture.md`](01-architecture.md), not something this window introduces).

```bash
ssh aizu 'journalctl -u bayram-bot -u bayram-worker -u bayram-admin -u bayram-payme --since "1 hour ago" -p err -o cat'
ssh aizu 'journalctl -u bayram-worker --since "1 hour ago" -o cat | grep -cE "payme sweep finished"'
ssh aizu 'systemctl show -p NRestarts bayram-bot bayram-worker bayram-admin bayram-payme'
```

`NRestarts=0` on all four an hour later is the check that catches a unit that boots, dies and
boots again — the failure §1 opens with.

---

## 8. The traps

### 8.1 The pause key, and the idempotency prefix

§1.1. They are first because they are the two that produce no error message. The pause key is
step 12; the idempotency prefix is why step 2 exists.

### 8.2 A stale `enabled` unit is how you get two bots polling one Telegram token

Step 11's `systemctl disable` is written `2>/dev/null || true` in the script (`:161`)
`[TREE 2026-09-11]`, and the script runs without `set -e`, so **a failed disable does not stop
it**. The fleet would look correct for as long as nobody reboots. On the next boot, systemd
starts both sets:

- **two bots** long-polling one Telegram token — `getUpdates` answers one of them with `409
  Conflict` and the product becomes intermittent rather than broken, which is worse;
- **two workers** on one `arq:queue` (§1.2 — the queue key does not move), each with its own
  idempotency prefix, so whichever wins a job pays for it under a different key than the other
  would have;
- **two gateways** racing for `127.0.0.1:8091` — the loser fails to bind and, under
  `Restart=always`, retries for ever.

`systemctl list-unit-files` at step 11 and again at §7.2 is the whole defence. `is-active` alone
does not catch it: a disabled-but-running unit and an enabled-but-stopped one look identical to
`is-active`.

### 8.3 The sudoers drop-in locks the deploy account out of what it just built

Every `NOPASSWD` verb names an `hbd-*` unit or an `/etc/hbd` path (§3.6). After a successful
cutover, `developer` has **no** unattended verb for the four units now running the product — and
the rollback's `systemctl enable --now hbd-*` is not granted either. The script knows and only
prints a note (`:174`).

Two failure shapes follow. **In the window:** step 11 prompts for a password the operator may not
have (§4.2). **Afterwards:** every routine restart, and every `journalctl -u` the drop-in was
written to allow, needs interactive `sudo` — so the next incident is slower for a reason nobody
will connect to a rename. §4.7's answer is a drop-in naming both sets, narrowed to the new one
only after §7 passes.

### 8.4 `/opt/hbd/deploy-payme.sh` is a privileged path whose meaning changed twice in 26 minutes

The drop-in grants `bash /opt/hbd/deploy-payme.sh`, so that **filename** is a root entry point.
The file is `developer`-owned and `developer`-writable `[HOST 2026-09-11]`. On 2026-09-10 it was
the Payme deploy; at 14:05 it `exec`ed the rename cutover; at 14:28 it was repointed again, and
today it is 434 bytes whose header still says *"this file is the wrapper that runs the cutover as
root"* while its last line is:

```bash
exec /usr/bin/bash /opt/hbd/diagnose.sh "$@"
```

**The header and the `exec` disagree**, and the `exec` wins. `diagnose.sh` is harmless — four
read-only Postgres SELECTs — and is the single most useful thing to run before this window (§4.1).
But the lesson is the filename, not the contents: **`cat` it every time, before you run it.** A
privileged path whose contents change daily is not a runbook step. This is also why §4.2 refuses
to solve the password problem by repointing it at the cutover.

### 8.5 The half-built debris changes what a re-run means

§2.2. `/etc/bayram` and `/opt/bayram` already exist with content. Two specific ways that misleads:

- **the three `/etc/bayram/*.env` files are a 2026-09-10 14:06:54 snapshot.** An operator who
  sees them and skips step 5 ships a day-old configuration — including, possibly, a superseded
  cashbox key. Step 5 rewrites unconditionally for this reason;
- **`/opt/bayram/venv` already has `bayram` installed.** Step 6's `rm -rf` is what makes it the
  wheel you meant rather than the wheel that was staged on 2026-09-10. Do not skip it because
  `import bayram` already works.

### 8.6 The script is not idempotent, and `deploy-payme.sh` trained you to expect that it is

`:99` is `cp -a "$OLD_ROOT/migrations" "$NEW_ROOT/migrations"`, which on a second run copies
*into* the existing destination. `/opt/bayram/migrations/migrations/` — with its own
`alembic.ini`, `env.py`, `script.py.mako` and `versions/` — is on the host right now, which is
what that looks like `[HOST 2026-09-11]`. Compare `deploy-payme.sh`'s own advertised property:
*"It is idempotent. A rerun re-dumps, finds `alembic upgrade head` a no-op, reinstalls the same
wheel and restarts"* ([`08-payme.md`](08-payme.md) §11.8). Different script, opposite property.

Add `set -e`'s absence (`:28`) and the nesting is not the worst case — it is the visible one.
**Before any re-run: `rm -rf /opt/bayram/migrations` and let step 8 re-copy it.**

### 8.7 `/etc/bayram` is created `0755` where `/etc/hbd` is `0750`

`chmod 0755 "$NEW_ETC"` (`:73`) `[TREE 2026-09-11]`, and the directory on the host is
`drwxr-xr-x root:root` today `[HOST 2026-09-11]`. The files inside stay `0640 root:hbd` via
`chmod --reference`, so **no secret becomes readable** — but every local account can now list and
`stat` them, where `/etc/hbd` denied even that. Change `:73` to `chmod 0750` and `chown
root:hbd "$NEW_ETC"` in the same edit as §4.6. This belongs to
[`07-security.md`](07-security.md) as a standing item; it is listed here because the window is
when it is cheap to fix.

### 8.8 Alembic is already broken in the *old* tree, in both directions

§3.10. `/opt/hbd/migrations/env.py` is post-rename and the live venv has no `bayram`, so there is
no working migration path on the host today. The consequence for this page: **after a rollback
you still cannot run a migration under the `hbd` fleet**, because the rollback restores the venv
and the units, not `migrations/env.py`. `0025` being additive is what makes that survivable.
[`04-release.md`](04-release.md) §0.4 warning 1 holds the three candidate repairs; pick one
before a window needs it, not during one.

### 8.9 Documentation that will be wrong the moment this lands

Not a host trap, but the one that wastes the next person's afternoon. Each of these names the old
world and will need the same window:

- **The Caddyfile's eight `hbd` comment lines** (§3.8), one of which already names a file that
  does not exist.
- **`/usr/local/bin/hbd-migrate`** (§3.9) — broken, and after the cutover also misnamed.
- **This tree.** [`00-host-inventory.md`](00-host-inventory.md),
  [`01-architecture.md`](01-architecture.md), [`02-configuration.md`](02-configuration.md),
  [`04-release.md`](04-release.md), [`08-payme.md`](08-payme.md) and
  [`09-payme-go-live.md`](09-payme-go-live.md) all quote host facts in `hbd` spelling **on
  purpose**, each under its own warning not to sweep them. After this cutover those warnings
  invert, and the correct edit is **not** a global `sed`: each page must be re-read against the
  machine and re-dated, and the old statements kept as superseded blocks with their dates, the way
  this tree does everywhere else. A blind rename has already corrupted verified facts here once
  ([`00-host-inventory.md`](00-host-inventory.md) finding 7).
- **[`09-payme-go-live.md`](09-payme-go-live.md) §1.2** says that after Gate A the page is a
  `s/HBD_/BAYRAM_/g` over its commands, *"and that sed is safe only because Gate A insists the
  two halves move together"*. That remains true of **its commands** and is not a licence to sed
  its host-fact transcripts.

---

## 9. What this page does not cover

- **Why the rail exists**, and the decision that specifies it:
  [`../decisions/DECISIONS.md`](../decisions/DECISIONS.md) **D11**.
- **What the Payme rail does**: `PAYME_INTEGRATION` §1–§7.
- **How the gateway runs on a host**, including its unit, its env file, the public path and the
  release runbook that executed: [`08-payme.md`](08-payme.md), and §11 in particular.
- **Which gates are still open before real money**, and who closes each:
  [`09-payme-go-live.md`](09-payme-go-live.md). This page closes the engineering half of its
  Gate A; it closes none of the others.
- **The host as it is**: [`00-host-inventory.md`](00-host-inventory.md) is the inventory of
  record. Where this page and the inventory disagree about a host fact, **the inventory wins** and
  one of us needs re-reading.
- **The two defects this window is a chance to fix but is not responsible for**: the Payme gateway
  running `environment=dev` on a production host, and `BAYRAM_CREDITS_ENFORCED` being false on a
  host that has taken a real settlement. Both are
  [`02-configuration.md`](02-configuration.md)'s, both were true on 2026-09-11
  `[HOST 2026-09-11]`, and **neither is a reason to delay or to extend this cutover.** Changing a
  value during a rename window is how you lose the ability to say which change broke it.
