# Deployed architecture

## STATUS — what has now been checked against the machine, 2026-09-10, re-checked 2026-09-11

**This page was written blind and is no longer blind.** It has been read against the
production host (`ssh` alias `aizu`, machine `abdu-test`) with read-only commands on
2026-09-10 between roughly 14:23 and 15:05 +05. Three marks now appear throughout, and they
mean exactly three different things:

- **`[HOST 2026-09-10]`** — a read-only command was run against `aizu` today and what is
  quoted is faithful to its output. The command is named wherever it is not obvious.
- **`[HOST 2026-09-11]`** — the same, one day later. Every `[HOST 2026-09-10]` mark on this
  page was **re-run** on 2026-09-11 and still holds; a `2026-09-11` mark means the claim is
  new on this page, or is a live gauge whose reading only ever means "at the moment it was
  read".
- **`[TREE 2026-09-10]`** — checkable by opening a file in this working tree; a `path:line`
  is given.
- **`[UNPROVEN]`** — exactly that, with the blocker named. Most of them are one blocker:
  `/etc/hbd` is `0750 root:hbd`, the `hbd` group is empty, `sudo -n` refuses, and `psql`
  needs a password the deploy account does not have. Those questions are not open for lack
  of looking; they are behind a permission wall the deployment put there on purpose.

**What has NOT been checked:** anything inside the three dotenv files, anything inside
Postgres, and the contents of `/var/lib/hbd` (mode `0750 hbd:hbd`, untraversable from
`developer`). Every variable this page cannot see is marked, never guessed.

**The host is PRE-RENAME and that is correct.** Units are `hbd-bot`, `hbd-worker`,
`hbd-admin`, `hbd-payme`; paths are `/etc/hbd/*.env`, `/opt/hbd/venv`, `/var/lib/hbd`; the
installed package is `hbd`; the environment prefix is `HBD_`; the database is `hbd`. This
**repository** is post-rename (`src/bayram`, `BAYRAM_`). Both are right at once. Every code
claim below is spelled `bayram`/`BAYRAM_` because that is what the tree says; every host
claim is spelled `hbd`/`HBD_` because that is what the machine says. **Do not sweep this page
with a rename pass** — a blind rename has already corrupted host facts in this tree once
(`00-host-inventory.md`, finding 7). The cutover script is staged at
`/opt/hbd/cutover-to-bayram.sh` and **has not run** `[HOST 2026-09-10]`, so the divergence is
live, not historical.

[00-host-inventory.md](00-host-inventory.md) is the inventory of record and **wins** wherever
it disagrees with this page; where a fact is fully developed there, this page points at it by
row rather than restating it.

**Second pass, 2026-09-11.** Every host claim below was re-run read-only against `abdu-test`
between roughly 10:38 and 10:47 +05. Nothing that this page asserts was overturned. Three
things moved, and they are recorded where they belong rather than silently refreshed:

- **All four units restarted at ~06:50 +05 on 2026-09-11** and came back with identical boot
  payloads — same `environment`, same `env_file`, same merchant id, same `credits_enforced:
  false`. `NRestarts=0` on all four, so those were stop/start, not crash loops
  `[HOST 2026-09-11]`.
- **Live gauges are not facts.** The Postgres backend count read `7` on 2026-09-10 and `2` on
  2026-09-11; `journalctl --disk-usage` read 88.6 M and now 96.6 M. Numbers like these are
  quoted below only with the date attached, and never as a ceiling or a budget.
- **The Payme settlement invariant still reports exactly one settlement**
  (`transactions_performed: 1, receipts_written: 1, grants_written: 1`) over its rolling 24 h
  window at 10:35 +05 `[HOST 2026-09-11]`. The go-live settlement is still the only one.

> **SUPERSEDED 2026-09-10, kept because it dates the change.** This page opened, until today,
> with: *"Everything below is derived from this repository, and nothing in it was observed on
> the production VPS. Nobody who wrote this document has access to `aizu`."* That was true
> when written (2026-09-07) and is false now. The code claims it made all survived contact
> with the machine; what it lacked was every host fact, and most of those are now filled in
> below rather than left as questions.

> **SUPERSEDED 2026-09-10 — the Payme rail is no longer off.** This page also opened with a
> note that the fourth process "ships **off** — `BAYRAM_PAYME_ENABLED` defaults to false and
> its lifespan refuses to boot while it is — so everything below remains an accurate
> description of a default deployment". The *code* half is still true
> (`src/bayram/payme/settings.py:171-180`) `[TREE 2026-09-10]`. The conclusion is not: **the
> production host is not a default deployment.** `hbd-payme.service` is active, holds a
> 36-character merchant key against merchant id `6aa24fd9ee30563de3a1ac22` in sandbox, and
> the rail took its **first real settlement today** — the five-minutely sweep reports
> `transactions_performed: 1, receipts_written: 1, grants_written: 1` over a rolling 24 h
> window `[HOST 2026-09-10]`. See [08-payme.md](08-payme.md) and
> [09-payme-go-live.md](09-payme-go-live.md); this page now treats the gateway as a peer
> process rather than an addendum.

## Four processes, and the commands you run by hand

The product is **four** long-running processes and three things you run by hand: two on every
deploy, and one exactly once per installation. All four processes are `python -m`
invocations: `pyproject.toml` has no `[project.scripts]` table, so
there is no `bayram` or `bayram-worker` binary on `PATH` after an install, and any process manager
must spell out an interpreter path plus `-m`.

```bash
# 1. the bot — aiogram long polling
.venv/bin/python -m bayram.main                                  # Makefile:68-69

# 2. the ARQ worker — every render, every cron
.venv/bin/python -m arq bayram.worker.WorkerSettings             # Makefile:71-72

# 3. the admin API — FastAPI, serving its own React bundle
.venv/bin/python -m uvicorn bayram.admin.app:app --host 127.0.0.1 --port 8080   # Makefile:74-75
```

```bash
# schema, run separately, from a checkout (migrations/ is not in the wheel)
.venv/bin/python -m alembic -c migrations/alembic.ini upgrade head   # Makefile:146-147

# the console bundle, required on every deploy — see "The console is a build artefact"
cd admin-ui && npm install    # Makefile:83-84  (`ui-install`)
cd admin-ui && npm run build  # Makefile:92-93  (`ui-build`)

# ONCE per installation: the first operator account. There is no signup route.
.venv/bin/python -m bayram.admin.bootstrap --username owner      # Makefile:77-81
```

**What the host actually runs** `[HOST 2026-09-10]`, re-read `[HOST 2026-09-11]` — the four
`ExecStart` lines verbatim, from `systemctl show -p ExecStart hbd-bot hbd-worker hbd-admin
hbd-payme`, each confirmed live by a PID owned by user `hbd` in `ps`:

```bash
/opt/hbd/venv/bin/python -m hbd.main                                                  # hbd-bot.service
/opt/hbd/venv/bin/python -m arq hbd.worker.WorkerSettings                             # hbd-worker.service
/opt/hbd/venv/bin/python -m uvicorn hbd.admin.app:app  --host 127.0.0.1 --port 8080   # hbd-admin.service
/opt/hbd/venv/bin/python -m uvicorn hbd.payme.app:app  --host 127.0.0.1 --port 8091   # hbd-payme.service
```

Four lines, four modules, one interpreter, and the module paths are spelled `hbd.*` because
the installed package is `hbd` — see the naming note in the STATUS block above. The shape the
paragraph above predicts is exactly the shape the host has: an interpreter path plus `-m`, with
no console script anywhere, and the admin and gateway bind addresses living on the command
line rather than in any configuration file.

The by-hand commands stay three. `bootstrap` leaves no trace anything else reports, and whether
it has ever been run on this host is still `[UNPROVEN]` — the only evidence would be a row in
`admin_users`, and `psql` needs a password the deploy account does not have.

> **Without the third command the panel has no account to log in with.**
> `src/bayram/admin/bootstrap.py:1-4`: "There is no signup route, so this CLI is the only thing
> that creates an operator account." A deploy that runs the migrations and builds the bundle
> produces an admin API that boots, answers `/healthz`, serves a login page and refuses every
> credential, because none exists. The password is never an argument — the CLI prompts, or
> takes `--password-file` (`Makefile:78-81`).

`make dev`, `make worker` and `make admin` run exactly those three strings, and each module's
own docstring repeats it (`src/bayram/main.py:1`, `src/bayram/worker.py:1`,
`src/bayram/admin/app.py:28-30`). Nothing in package metadata pins them, so renaming
`bayram.worker.WorkerSettings` breaks a deployment silently and no test fails.

The targets are not *quite* bare wrappers: every one of them — `dev`, `worker`, `admin`,
`admin-bootstrap` and `migrate` — is prefixed by `$(ENV_FILES)` (`Makefile:69`, `:72`, `:75`,
`:81`, `:147`), which is empty when `ENV=dev` and otherwise expands to
`BAYRAM_ENV_FILE=.env.$(ENV) BAYRAM_ADMIN_ENV_FILE=.env.admin.$(ENV)` (`Makefile:41-46`).
`BAYRAM_ENV_FILE` is the variable that decides **which dotenv file every one of these processes
reads**; it defaults to `.env` and is read from the process environment only, because a
dotenv file cannot name the dotenv file about to be read (`src/bayram/config.py:69-78`). The
code treats this as a sharp hazard rather than a convenience: `verify_host` logs the
environment and the env file at INFO precisely because "`BAYRAM_ENV_FILE` makes it possible to
boot a PRODUCTION configuration from a development checkout"
(`src/bayram/runtime/startup.py:31-34`), and the admin's `admin.boot.ok` line carries the same
field for the same reason (`src/bayram/admin/app.py:327-329`). A process manager that sets
`BAYRAM_ENV_FILE` is therefore setting the whole configuration, and nothing in the command line
above shows which file that is.

> **On this host that mechanism is not in use for three of the four processes, and the boot
> log therefore lies about where configuration came from.** `systemctl show -p Environment` is
> **empty** for `hbd-bot`, `hbd-worker` and `hbd-admin`: neither `HBD_ENV_FILE` nor
> `HBD_ADMIN_ENV_FILE` is set anywhere in their process environment. Configuration reaches
> them through systemd `EnvironmentFile=` instead — `/etc/hbd/hbd.env` for the bot and the
> worker, `/etc/hbd/hbd-admin.env` for the panel — so the values are already in the
> environment before Python starts, and the `env_file` field in the boot line names the unused
> *relative default*: the bot and worker log `"env_file": ".env"` and the panel logs
> `".env.admin"`, both relative to `WorkingDirectory=/var/lib/hbd`. Only `hbd-payme` uses the
> mechanism this page describes (`Environment=HBD_PAYME_ENV_FILE=/etc/hbd/payme.env`), and it
> is the only one whose logged `env_file` is a real absolute path `[HOST 2026-09-10]`,
> re-confirmed `[HOST 2026-09-11]`. Consequences are developed in "How the four processes are
> actually supervised" below and in [02-configuration.md](02-configuration.md); the inventory
> rows are 18–19.

> **The bind address is on the command line, not in configuration.** `BAYRAM_ADMIN_HOST` and
> `BAYRAM_ADMIN_PORT` exist (`src/bayram/admin/settings.py:187-189`) and are read by nothing that
> opens a socket — their only consumers are the two display fields on `GET /api/config`
> (`src/bayram/admin/schemas/config_view.py:108-109`). Changing `BAYRAM_ADMIN_PORT` changes what
> the panel *reports* and not what the process listens on. The `--host 127.0.0.1` in the
> uvicorn invocation is the whole of the loopback control, and `create_app()` is just an
> ASGI object — it cannot know or refuse the address it is served on.

## How the four processes are actually supervised

Nothing in this repository can answer this section; all of it is read off the machine. It is
here because every configuration question on [02-configuration.md](02-configuration.md) lands
in a systemd directive, and because three properties the code only *asserts* — the panel's
read-only object store, the gateway's unreachable sibling secrets, the restart behaviour a
misconfigured worker meets — are enforced here or nowhere.

`systemd`, four units in `/etc/systemd/system/`, all `root:root 0644`, all
**active/running** `[HOST 2026-09-10]`, re-confirmed `[HOST 2026-09-11]`:

| | `hbd-bot` | `hbd-worker` | `hbd-admin` | `hbd-payme` |
| --- | --- | --- | --- | --- |
| unit mtime / size | Sep 5 18:01, 951 B | Sep 5 18:01, 809 B | Sep 5 18:01, 1306 B | **Sep 9 23:39, 5022 B** |
| `User` / `Group` | `hbd` / `hbd` | `hbd` / `hbd` | `hbd` / `hbd` | `hbd` / `hbd` |
| `WorkingDirectory` | `/var/lib/hbd` | `/var/lib/hbd` | `/var/lib/hbd` | `/var/lib/hbd` |
| configuration | `EnvironmentFile=/etc/hbd/hbd.env` | same | `EnvironmentFile=/etc/hbd/hbd-admin.env` | `Environment=HBD_PAYME_ENV_FILE=/etc/hbd/payme.env`, **no `EnvironmentFile=`** |
| `Restart` / `RestartSec` | `on-failure` / 5 s | `on-failure` / 5 s | `on-failure` / 5 s | **`always`** / 5 s |
| effective `TimeoutStopSec` | 20 s | 1 min | 20 s | 1 min 30 s — **systemd's default, not a decision**; the unit sets none |
| `ReadWritePaths` | `/var/lib/hbd /var/log/hbd` | same | **empty** | **empty** |
| `InaccessiblePaths` | — | — | — | `/etc/hbd/hbd.env /etc/hbd/hbd-admin.env` |
| `RestrictAddressFamilies` | unset (`~`) | unset (`~`) | unset (`~`) | `AF_INET AF_INET6 AF_UNIX` |
| `MemoryDenyWriteExecute` / `RestrictNamespaces` | no / no | no / no | no / no | **yes / yes** |

All four also carry `NoNewPrivileges=yes`, `PrivateTmp=yes`, `ProtectHome=yes`,
`ProtectSystem=strict` and `StandardOutput=journal`. `hbd` is a system account — `hbd:x:995:986::/var/lib/hbd:/usr/sbin/nologin` — and the group `hbd` has **no supplementary
members**, which is the fact that closes most of the unread-variable questions on this page and
the next one.

Four things follow that are worth holding separately.

**1. The read-only object store is real, and it is not a `:ro` mount.** `src/bayram/admin/container.py:152-154` asserts a read-only mount and builds an ordinary
read-write `LocalFileStorage` anyway. On this host the property holds by a different mechanism
entirely: `hbd-admin.service` declares `ProtectSystem=strict` with an **empty**
`ReadWritePaths`, so the kernel presents the whole filesystem outside `/dev`, `/proc` and
`/sys` read-only to that process — including `/var/lib/hbd/var/archive`, which it would
otherwise be free to write, since it runs as `hbd`, the owner of that tree. The unit file says
so in a comment: *"No ReadWritePaths: the panel streams assets from a root it holds
READ-ONLY, which is the arrangement runtime/container.py's comment describes."*
`[HOST 2026-09-10]`. Same for `hbd-payme`. There is **one** real filesystem on the box
(`00-host-inventory.md` row 31), so a `:ro` mount was never available without repartitioning —
the sandbox is the implementation, and an operator who goes looking for the mount will not find
one and may wrongly conclude the control is missing.

**2. Secrets are in the process environment for three of the four units, which is the opposite
of what the gateway's own unit file claims the bot does.** `hbd-payme.service:33-37` reads:
*"SECRETS COME FROM HBD_PAYME_ENV_FILE, NOT FROM `EnvironmentFile=`. Same reason
hbd-bot.service gives… `EnvironmentFile=` loads every value into the process environment,
where it appears in `systemctl show hbd-payme` and in `/proc/<pid>/environ`."* The reasoning is
correct and the attribution is not: `hbd-bot.service` gives no such reason, because it *uses*
`EnvironmentFile=` `[HOST 2026-09-10]`. So the cashbox key genuinely never enters an
environment, and the Telegram token, the ElevenLabs key, the LLM key and the admin's audit HMAC
key genuinely do. The gateway's `InaccessiblePaths` is the other half of the same intent, and it
is the half that survives somebody later editing `HBD_PAYME_ENV_FILE` to point at the wrong
file.

**3. `Restart=always` on the gateway and `on-failure` on the other three is a visible
difference, not a stylistic one.** During the 2026-09-10 00:00 deploy window the journal shows
**twelve** `Started hbd-payme.service` lines between `00:00:05` and `00:01:26`, five seconds
apart, against **two** each for the bot, the worker and the panel `[HOST 2026-09-10]`. That is
what the warning further down this page — a worker whose settings fail at *module import*
produces a traceback once per restart attempt — looks like from the outside. Under
`on-failure` the attempts stop when systemd's start limit trips; under `always` the gateway
retries until someone intervenes. A gateway that cannot read its env file will therefore sit in
a five-second loop indefinitely, and the only thing that says so is the journal.

**4. `/var/log/hbd` exists, is `hbd:hbd 0755`, and is empty** `[HOST 2026-09-11]`. Everything
goes to the journal; the `ReadWritePaths=/var/log/hbd` grant on the bot and the worker is
currently unused. The journal is persistent (`/var/log/journal` exists) and
`/etc/systemd/journald.conf` sets no `Storage`, no `MaxRetentionSec` and no `SystemMaxUse`, so
retention is the distro default and the only bound is disk. `journalctl` needs no `sudo` —
`developer` is in group `4(adm)`.

> **The units on the host and the units in `deploy/systemd/` are different files and only one
> of them runs anything.** `deploy/systemd/bayram-*.service` and
> `deploy/first-install-proposal.md` propose `bayram-*` unit names, a `/srv/bayram` checkout,
> `User=bayram` and `/etc/bayram/*.env`. **None of those exist on this machine**: `/srv` is
> empty, the install is a wheel, and the units are the four `hbd-*` files above
> `[HOST 2026-09-10]`. Read `deploy/` as the post-rename target state — the cutover script
> staged at `/opt/hbd/cutover-to-bayram.sh` is what would produce it, and it **has not run**.
> Do not quote a `bayram` path as though it were a host fact.

## What talks to what

```
                        ┌──────────────────────┐
        Telegram  ◄────►│   bot                │   python -m bayram.main
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
                        │   10 jobs, 5 crons   │  TTS   └──────────────────────┘
                        └──┬─────────┬─────────┘  STT
                           │         │            ┌──────────────────────┐
                           │         └───────────►│  LLM base URL        │
                           │                      │  openrouter default  │
                           │                      ├──────────────────────┤
                           │            (if set)  │  LLM FALLBACK host   │
                           │                      │  BAYRAM_LLM_FALLBACK_   │
                           │                      │  BASE_URL — 4th dest │
                           │                      └──────────────────────┘
                           │  as hbd_app
                           ▼
                        ┌──────────────────────┐
                        │  PostgreSQL          │◄──── alembic, as hbd (owner)
                        └──────────▲───────────┘
                                   │  read-mostly — on this host as hbd_app, like
                        ┌──────────┴───────────┐   every other backend (.env.admin.example
   browser              │   admin API          │   ships the OWNER — see Decision 2)
     │                  │   uvicorn 127.0.0.1  │   holds NO vendor credential
     │ TLS              │           :8080      │   serves its own SPA bundle
     ▼                  └──────────┬───────────┘
  Cloudflare edge                  │  reads — read-only to the KERNEL, not by a mount:
  (terminates TLS)                 │  ProtectSystem=strict + empty ReadWritePaths
     │                             ▼
     │ tunnel aizu-vds,  var/archive   ◄──── written by bot + worker
     │ PLAIN HTTP       /var/lib/hbd/var  (one filesystem root, two key namespaces)
     ▼
  Caddy v2.11.4 on 127.0.0.1:80 ──► 127.0.0.1:8080   admin.bayrambot.uz (whole hostname)
  (adds HSTS; the app adds none) ──► 127.0.0.1:8091   pay.bayrambot.uz, `handle /payme` only
                                            │
                                            ▼
                              ┌──────────────────────────┐
   Payme ───inbound, the only │   payme gateway          │  python -m bayram.payme.app
   thing from the internet ──►│   uvicorn 127.0.0.1:8091 │  holds ONE key: the cashbox key
                              └──────────┬───────────────┘  no Telegram token, no vendor key
                                         │  rows as hbd_app, pool 3+2
                                         ▼  and ONE enqueue: notify_payment_settled,
                                  PostgreSQL / Redis      because the process that took
                                                          the money cannot send a message
```

The right-hand column of that diagram is code; the left-hand chain from the browser down is
`[HOST 2026-09-10]`, re-confirmed `[HOST 2026-09-11]`, and it answers in full the question this
page used to leave open. **Public TLS is terminated by Cloudflare, not by anything on this
machine** — the host has no public IP at all (`00-host-inventory.md` finding 2), so nothing else
was ever possible. `cloudflared.service` runs tunnel `aizu-vds`; its ingress is pushed from the
Cloudflare Zero Trust dashboard and exists locally only as a log line (config `version=4`,
applied `2026-09-09T19:18:03Z`): `aizu.uz` and `www.aizu.uz` → `http://127.0.0.1:8765` (**a
different application — not ours**), `admin.bayrambot.uz` → `http://127.0.0.1:80`,
`pay.bayrambot.uz` → `http://127.0.0.1:80`, catch-all `http_status:404`. Caddy v2.11.4 owns
`*:80` and `*:443` locally and demultiplexes by `Host` header. **Both `bayrambot.uz` site blocks
are written `http://` on purpose** — the tunnel speaks plain HTTP to `:80`, and a scheme-less
block makes Caddy answer every tunnelled request with `308` (`00-host-inventory.md` finding 4;
this cost a day).

**HSTS is added by Caddy and by nothing else, exactly as the code side of this page predicted.**
Through Caddy, `/healthz` returns `Strict-Transport-Security: max-age=86400` and
`Via: 1.1 Caddy`; the identical request straight to `127.0.0.1:8080` returns **no** HSTS header
at all `[HOST 2026-09-11]`. There is no `includeSubDomains` and no `preload` — the Caddyfile
explains why (sibling hostnames on `bayrambot.uz` this file does not own). The application's own
headers are present on both paths: `Content-Security-Policy` with a per-response `style-src`
nonce, `X-Content-Type-Options: nosniff`, `Referrer-Policy: no-referrer`,
`Cache-Control: no-store`, `X-Correlation-Id`.

**Only two application sockets listen, both on loopback:** `127.0.0.1:8080` and
`127.0.0.1:8091`. Nothing binds `0.0.0.0` for either. Postgres is `127.0.0.1:5432`, Redis
`127.0.0.1:6379` and `[::1]:6379`, Caddy holds `*:80`/`*:443` plus its own admin API on
`127.0.0.1:2019` `[HOST 2026-09-11]`. The loopback bind came from the `--host 127.0.0.1` on the
command line, as the callout above insists; `HBD_ADMIN_PORT` is not what produces it.

Edge by edge, with the code that makes each one:

**Telegram.** Only the bot polls; the worker holds a `Bot` of its own that never polls and
only sends, because the progress edits and the finished kit have to reach the customer from
the process that produced them (`src/bayram/worker.py:7-9`, `:55`). On every start the bot calls
`delete_webhook(drop_pending_updates=True)` (`src/bayram/bot/app.py:216`), so every update that
arrived during a restart window is discarded and never resent. That is a deliberate,
documented deploy-window data loss, and it is why the worker also records bot-blocks — the
churn signal is the one thing given a second source (`src/bayram/main.py:156-162`).

**Redis.** A hard dependency of both the bot and the worker in production, not just the
worker. The bot opens it twice — an ARQ pool for the queue (`src/bayram/main.py:94`) and
`RedisStorage` plus `RedisEventIsolation` for the wizard FSM (`src/bayram/bot/app.py:83`, `:97`)
— and the worker opens it again for the same two purposes (`src/bayram/runtime/jobs.py:771`,
`src/bayram/worker.py:57`). In production the bot takes the `create_pool` branch with no
fallback, because the in-process submitter refuses to construct itself there
(`src/bayram/runtime/submitter.py:98-105`). The FSM key namespace is shared: the worker un-parks
the wizard session the bot parked, which only works while both point at the same URL and the
same logical database. `BAYRAM_REDIS_URL` defaults to `redis://localhost:6379/0`
(`src/bayram/config.py:188`), so a process that never had it set connects to a local Redis and
the queue looks *empty* rather than *broken*.

On this host that default is, as it happens, the truth: one local **Redis 7.0.15** on
`127.0.0.1:6379`, `redis-server.service` active, shared by the bot and the worker, and lightly
used — the worker's own arq banner reads `redis_version=7.0.15 mem_usage=941.71K
clients_connected=1 db_keys=3` at the 06:50 boot `[HOST 2026-09-11]`. `mem_usage` and `db_keys`
are gauges (88.6 M → 96.6 M journal, 1.49 M → 941 K Redis between the two passes); the version,
the single instance and the shared URL are the facts. Persistence is `appendonly no`, RDB only
(`00-host-inventory.md` row 16) — which is the fact that makes "losing Redis loses every
in-flight wizard draft and every queued job" a live risk here rather than a theoretical one.

The admin panel's use of Redis is narrower than it looks, and the difference matters during
an incident. **Admin sessions are not in Redis.** They are rows in the Postgres table
`admin_sessions`, whose `token_sha256` is "the ONLY copy of the session token"
(`migrations/versions/20260829_1200_0005_add_admin_users_and_sessions.py:1-14`, `:41`). What
Redis holds is a 60-second mirror of a session snapshot — the module's first line is "Admin
sessions: the database is the truth, Redis is a mirror that cannot outlive it"
(`src/bayram/admin/sessions.py:1`) — and the operator row and the revocation column are re-read
from Postgres on **every** request regardless of whether the mirror is warm
(`src/bayram/admin/sessions.py:9-25`). So flushing this Redis does not log anybody out (the next
request re-reads the row), losing Redis does not lose sessions, and "kick everyone out" is a
write to `admin_sessions.revoked_at`, not a `FLUSHDB`. The only Redis-backed store the admin
container builds is `rate_limits` (`src/bayram/admin/container.py:151`).

**PostgreSQL.** All four processes. Pool sizing in this repository still assumes exactly three
of them: the bot and worker take 10 + 20 overflow each (`src/bayram/db/engine.py:40-41`) and the
admin API deliberately asks for a smaller share, 5 + 5
(`src/bayram/admin/container.py:53-54`), because "bot + worker + admin API at the defaults is
`3 × 30 = 90` connections against a stock `max_connections` of 100"
(`src/bayram/db/engine.py:64-67`).

**That arithmetic is out of date and the fourth unit already re-did it.** The gateway asks for
`pool_size=3, max_overflow=2` — `payme.container.built` logs `pool_size: 3` `[HOST 2026-09-10]`
— and `hbd-payme.service:48-52` states the sum for the fleet that exists: *"With bot 30, worker
30 and admin 10 that is 75 of a stock max_connections of 100, so installing this needs no host
change. **A FIFTH process has to re-argue that arithmetic rather than inherit it.**"* Two host
facts finish it:

- `max_connections = 100` in `/etc/postgresql/16/main/postgresql.conf` `[HOST 2026-09-11]`. The
  stock ceiling the code assumed is the real one, and the ceiling in force is
  30 + 30 + 10 + 5 = **75 of 100**, not 90 of 100.
- **Every backend on the box connects as the application role `hbd_app` to database `hbd`**, and
  there is no backend connected as an owner role `[HOST 2026-09-10]`, re-read
  `[HOST 2026-09-11]`. The bot, worker and admin all log `database: 127.0.0.1:5432/hbd` in their
  container lines, and so does the gateway. So the `.env.admin.example:48` owner-DSN hazard
  argued in Decision 2 **did not materialise here** — whatever `/etc/hbd/hbd-admin.env`
  contains, it is not that example's DSN.

The backend *count* is a gauge, not a fact: the same command read seven backends on 2026-09-10
and two on 2026-09-11. Do not plan a pool change off one reading.

**Vendors.** Exactly two *pooled* HTTP clients, both built only in the live provider set: one
to ElevenLabs, which carries music, TTS and STT, and one shared client object used for both
the primary and the fallback LLM (`src/bayram/runtime/providers.py:133-155`). Music is
ElevenLabs, not a separate service. The default hosts are `https://api.elevenlabs.io`
(`src/bayram/config.py:192`) and `https://openrouter.ai/api/v1` (`src/bayram/config.py:235`).

A shared client is not a shared destination, and an allowlist written from the client count
alone will be wrong twice:

- **The fallback LLM can have a host of its own.** `BAYRAM_LLM_FALLBACK_BASE_URL`
  (`llm_fallback_base_url`, `src/bayram/config.py:250-252`) defaults to empty, and empty means
  "the adapter's usual home"; set, it becomes the fallback adapter's `base_url`
  (`src/bayram/providers/llm/factory.py:168`, `base_url=settings.llm_fallback_base_url or
  default_host`). If it is set on the deployed host, there is a fourth destination, and an
  allowlist built from the primary hosts silently kills the LLM failover path.
- **The hourly balance poll does not use those clients at all.** It builds its own —
  `async with httpx.AsyncClient() as client` (`src/bayram/runtime/vendor_balance_job.py:330`),
  deliberately, "ONE CLIENT, OWNED BY THE RUN" (`:50-54`) — and resolves the fallback host
  itself with `_fallback_base_url` (`:175-186`), mirroring the factory's rule.

So the bot and worker need at least three outbound destinations — Telegram, ElevenLabs and
the LLM base URL — plus a fourth wherever `BAYRAM_LLM_FALLBACK_BASE_URL` is set, and **the admin
API needs none of them**. Which of those a firewall must allow is settled by the deployed
`.env`, not by this repository.

**The filesystem.** One object-store root, shared. The bot and worker derive it as
`Path.cwd()/"var"` with no environment override at all (`src/bayram/runtime/container.py:286`)
and create `var/workspace` and `var/archive` under it at every boot (`:287-290`). The admin
process reaches `<admin_data_root>/archive` through the same `Storage` protocol
(`src/bayram/admin/container.py:155`), where `admin_data_root` defaults to the *relative* path
`var` (`src/bayram/admin/settings.py:423`). One instance is shared on the writing side on
purpose: the avatar the bot writes and the object the panel streams must be the same key
under the same root, or "the row says an avatar was stored, and the bytes are on another
disk" (`src/bayram/runtime/container.py:301-311`).

> **The one path the processes must agree on is configurable on exactly one side.** The bot
> and worker have no data-root setting — `bayram.main.run` accepts `data_root` but `main()`
> never passes it (`src/bayram/main.py:98`, `:222`) — so relocating their root means changing
> the process working directory and nothing else. The admin's value is a relative default.
> If the two resolve differently, every media reveal in the panel returns "no such object"
> while the database row insists the file exists, and no configuration error is raised
> anywhere. Whether they agree on the live host is a deployment fact, not a code guarantee.
>
> **On this host they agree, by construction, and one variable could still break it.** All four
> units share `WorkingDirectory=/var/lib/hbd`, and the bot's container resolves
> `workspace: /var/lib/hbd/var/workspace` `[HOST 2026-09-10]`. The admin's default data root is
> the relative `var`, which under that same cwd resolves to `/var/lib/hbd/var` — so the two
> roots coincide **unless `HBD_ADMIN_DATA_ROOT` is set in `/etc/hbd/hbd-admin.env`**. Whether it
> is, is `[UNPROVEN]`: the variable appears in no boot line, and `/etc/hbd` is `0750 root:hbd`
> with an empty `hbd` group, so `developer` cannot read the file and `sudo -n` refuses
> ("sudo: a password is required"). That is the one residual unknown here, and it is behind a
> permission wall rather than open for lack of looking. `00-host-inventory.md` rows 2 and 30.

**Nothing else, with one named exception.** The admin process connects to Postgres and Redis and
to nothing else — its container is still "engine, sessions, Redis, and nothing else"
(`src/bayram/admin/container.py:1`) — and neither handle connects at construction, so `/healthz`
can answer without touching either. The exception is the **queue**: the container now holds an
`ArqAdminQueue` over its own second `ArqRedis` pool (`src/bayram/admin/container.py:179`), and the
module docstring calls it exactly that — *"the single exception to 'nothing else', it costs no
credential (enqueueing is a Redis write)"* `[TREE 2026-09-11]`. It is a second pool rather than a
shared one because the panel's client is `decode_responses=True` for text while arq's payloads
are pickled bytes. That edge is the panel→worker arrow this page once said did not exist; see the
retraction under Decision 1.

## Only the worker runs the clocks

> **SUPERSEDED 2026-09-10, kept because it dates the change.** This section said until today:
> *"Three ARQ crons, on deliberately staggered off-the-hour minutes"*, naming the retention
> sweep, the vendor-balance poll and the activity snapshot. That was an accurate reading of the
> tree when it was written (2026-09-07). There are now **five**, the two new ones are
> **five-minutely** rather than off-the-hour, and both the old count and the
> "staggered off-the-hour" framing are wrong.

**Five ARQ crons.** Three are hourly or daily on deliberately staggered off-the-hour minutes;
two are five-minutely and exist to backstop something that must not be allowed to stall
`[TREE 2026-09-11]`:

| Cron | Schedule | Declared at |
| --- | --- | --- |
| retention sweep | hourly at **:17** | `src/bayram/runtime/retention_job.py:73` |
| vendor-balance poll | hourly at **:43** | `src/bayram/runtime/vendor_balance_job.py:118` |
| activity snapshot | daily at **00:07** (see the timezone callout) | `src/bayram/runtime/activity_job.py:74-75` |
| Payme settlement sweep | **every 5 min**, `:00 :05 :10 …` | `tuple(range(0, 60, settings.payme_sweep_minutes))`, `src/bayram/runtime/payme_jobs.py:221`; `payme_sweep_minutes` default `5`, `ge=1 le=60`, `src/bayram/config.py:855` |
| broadcast due-sweep | **every 5 min**, `:04 :09 :14 …` | `tuple(range(4, 60, 5))`, `src/bayram/runtime/broadcast_job.py:152` |

All five were observed firing on the host. Over the 10.6 hours of 2026-09-11 up to the read:
the broadcast due-sweep 128 times, the Payme sweep 127, the retention sweep 11, the vendor poll
10, the activity snapshot once `[HOST 2026-09-11]`. The cadence is the claim; the counts are a
gauge.

**The worker registers ten functions, not one.** Its boot banner reads *"Starting worker for 10
functions: generate_and_deliver, run_retention_sweep, poll_vendor_balances,
record_activity_snapshot, notify_payment_settled, run_payme_sweep, expand_broadcast_audience,
send_broadcast_chunk, send_broadcast_test, sweep_due_broadcasts"* `[HOST 2026-09-10]`,
re-confirmed `[HOST 2026-09-11]`. Two of those names are the queue edges this page previously
said did not exist — see the retraction under Decision 1.

> **The activity snapshot does not fire at 00:07 UTC on this host, and the code's own stated
> reason for the time is not met as deployed.** This is a data defect, not a wording fix.
> `src/bayram/runtime/activity_job.py:69` says the hour was chosen *"Just after midnight UTC, so
> the sample sits at the very start of the day it is filed under"* `[TREE 2026-09-11]`. ARQ's
> cron is given **no timezone**, and the host is **`Asia/Tashkent (+05)`** — `timedatectl`
> reports `Time zone: Asia/Tashkent (+05, +0500)`, clock synchronised, NTP active. So the job
> fires at 00:07 **local** = **19:07 UTC of the preceding UTC day**: the journal stamps it
> `2026-09-11T00:07:00+05:00` `[HOST 2026-09-11]`. The same five-hour offset is visible in the
> retention purge, which logged `"ran_at": "2026-09-10T19:17:00.336650Z"` for its 00:17 local
> fire. The sample therefore lands near the **end** of the UTC day it is filed under, not the
> start — and the dashboard's population series is what reads it. Nobody would find this from
> the repository, because the code comment asserts the intent the deployment does not deliver.
> Two fixes exist and this page does not choose between them: give the cron an explicit
> timezone, or set the unit's `Environment=TZ=UTC`. Either is a change, not a correction, and
> it moves where a day boundary falls in an existing series.

No other process covers any of them. A worker that is down stops the retention sweep — a stated
legal obligation — stops re-pinning the audit chain's HEAD anchor, puts permanent,
unbackfilled gaps in the activity series, and **now also stops the Payme settlement backstop and
the broadcast due-sweep**. None of that raises anything. And because `run_at_startup=False`, a
cold-started worker runs no cron until the next window: five minutes for the two sweeps, up to an
hour of stale balances, up to a day before the first snapshot.

Worker concurrency is 15 jobs (`src/bayram/runtime/jobs.py:772`, default at
`src/bayram/config.py:632-640`), but the vendor ceiling is a *per-process*
`asyncio.Semaphore` (`src/bayram/runtime/container.py:332-333`), defaulting to 2 simultaneous
renders — the number the vendor's plan allows. Two worker replicas would make four
simultaneous renders against a vendor limit of two. The guard is written as if one process
exists — **and on this host exactly one does**: one `-m arq hbd.worker.WorkerSettings` process,
one unit, no template instance, and the boot line reports `"concurrency": 15`, the shipped
default unmodified `[HOST 2026-09-10]`. So the semaphore still means what it says here, and the
fleet-cap caveat is currently theoretical rather than live. `00-host-inventory.md` row 9.

**The hourly poll reaches two providers, both healthy.** `vendor balance poll finished` reports
`polled: 2, succeeded: 2, failed: 0`, against `elevenlabs_subscription` and `openrouter_key`,
both HTTP 200 `[HOST 2026-09-10]`, re-read at 09:43 +05 `[HOST 2026-09-11]`. No
`openrouter_credits` probe appears in either pass — that is the probe
`HBD_OPENROUTER_MANAGEMENT_KEY` buys, so the most likely reading is that the management key is
unset. **That last step is inference, not observation**, and the variable itself is
`[UNPROVEN]` behind the `/etc/hbd` wall.

## Two of the four processes will not start without ffmpeg

`verify_host()` refuses to boot on exactly three things: `ffmpeg` on `PATH`, `ffprobe` on
`PATH`, and an ffmpeg build carrying the `libopus` encoder
(`src/bayram/runtime/startup.py:23-25`, `src/bayram/audio/startup.py:93-103`). It also force-loads
the i18n catalogues, so a malformed locale file is a boot failure rather than a broken
message in front of a customer (`src/bayram/runtime/startup.py:26-28`). It is called by the bot
(`src/bayram/main.py:100`), the worker (`src/bayram/worker.py:45`) and the demo — and **never by
the admin API**, which holds no post-processor at all. An admin-only host therefore has a
materially smaller dependency surface.

What `verify_host` does *not* check is Postgres, Redis, Telegram or any vendor. A host with
no database passes it cleanly and fails later. Nor does it cover the gateway: `hbd-payme` calls
none of it, which is why a box running only the panel and the gateway would need no ffmpeg at
all.

**All three refusals are satisfied on this host by a real build, not merely inferred from a
running bot.** `ffmpeg version 6.1.1-3ubuntu5` at `/usr/bin/ffmpeg`, `ffprobe` at
`/usr/bin/ffprobe`, and `ffmpeg -encoders` lists `A....D libopus  libopus Opus (codec opus)`
`[HOST 2026-09-10]`, re-run `[HOST 2026-09-11]`. The bot and the worker both log
`audio.startup.ready {"ffmpeg": "/usr/bin/ffmpeg", "ffprobe": "/usr/bin/ffprobe"}` at every
boot, and `HBD_FFMPEG_BINARY` is at its default — `host verified` carries `"ffmpeg": "ffmpeg"`,
the bare name, so resolution is happening on `PATH`. `00-host-inventory.md` row 26 adds
`libmp3lame`, which the boot probe does **not** check but the song master needs.

> **Bot and worker fail differently on the same bad environment.** The bot builds settings
> inside a `try/except BayramError` and prints one line, `bayram: <operator message>`, then exits 2
> (`src/bayram/main.py:213-218`). The worker builds them at *module import* time
> (`src/bayram/worker.py:40`), because that is how ARQ's CLI finds `WorkerSettings` — so the
> same misconfiguration produces an uncaught traceback from the arq CLI, once per restart
> attempt, for as long as a supervisor keeps trying.

## The console is a build artefact the API serves itself

There is no separate web server for the admin console. `vite build` writes into the Python
package tree at `src/bayram/admin/static/` (`admin-ui/vite.config.ts:106-107`, with
`emptyOutDir: true`), the API mounts `static/assets` under `/assets` and registers a catch-all
that renders the SPA shell for every other browser URL (`src/bayram/admin/app.py:296-303`).

That directory is **gitignored** (`src/bayram/admin/app.py:124-128`). A fresh checkout has no
console, and the failure is quiet by design: the catch-all 404s when the shell is missing
rather than taking the process down (`src/bayram/admin/app.py:238-239`), and the assets mount is
constructed with `check_dir=False` so the app still imports (`:280-282`, `:296-300`).

> **An unbuilt console is indistinguishable from a healthy API at the process level.**
> `/healthz` answers 200, `/api` answers JSON, and every browser URL answers 404. The only
> signal is the missing bundle. `npm run build` is therefore not an optimisation step in a
> deploy — it is the step that makes the panel exist.

The shell is not served as a static file. It carries a per-response CSP style nonce, so it is
read, substituted and returned as an `HTMLResponse` on every request
(`src/bayram/admin/app.py:243-249`), which is also why it is deliberately outside the immutable
cache prefix. A bundle built before the `__BAYRAM_CSP_NONCE__` placeholder existed degrades
silently — one WARNING per response, `admin.spa.nonce_placeholder_missing`, and a panel that
looks correct except that modal scroll-lock stops working
(`src/bayram/admin/shell.py:65-85`).

Packaging note, because the two mechanisms are easy to conflate: the wheel force-includes the
gitignored bundle through `[tool.hatch.build.targets.wheel] artifacts`
(`pyproject.toml:60-71`), but `migrations/` is not in the wheel at all, so a wheel is not a
complete deployment unit. An editable install from a checkout serves the console straight out
of the checkout's build output. Which of the two a given host uses decides which mechanism is
load-bearing there.

**On this host it is the wheel, so the `artifacts` force-include is the load-bearing
mechanism** `[HOST 2026-09-10]`, re-read `[HOST 2026-09-11]`:

- `direct_url.json` in `hbd_bot-0.1.0.dist-info` records
  `file:///opt/hbd/release/hbd_bot-0.1.0-20260909-py3-none-any.whl`,
  `sha256=369db0983508619badec41ed50f72e53566de29a9fc9a0d518a5f2540c5587f3`, installed
  2026-09-10 00:01. **No `.pth` files**, no editable finder. Python 3.12.3.
- Because the wheel carries no `migrations/`, they are shipped **out of band** at
  `/opt/hbd/migrations` (versions through `20260910_1000_0025_index_settlement_clocks.py`), with
  alembic 1.19.2 inside `/opt/hbd/venv`. The repository's migrate command shape assumes a
  checkout; the host satisfies it with a directory instead. `00-host-inventory.md` rows 3, 5, 45.
- The bundle **is** inside the installed wheel and **is** being served:
  `…/site-packages/hbd/admin/static/index.html` plus `static/assets/`, `root:root 0644`, dated
  Sep 10 00:01.
- The deployed shell carries the placeholder **`__HBD_CSP_NONCE__`** — the host's pre-rename
  spelling of the string this page writes as `__BAYRAM_CSP_NONCE__` — and substitution works: a
  live response carries `style-src 'self' 'nonce-sa0phfvtWV5yXNosNTbQ5A'`, and a second request
  a different nonce. The `<title>` still reads `hbd dashboard`. No
  `admin.spa.nonce_placeholder_missing` warning appears.

> **A 4.2 MB JavaScript source map ships to production, and the admin API serves it out of the
> wheel.** `static/assets/` holds `index-D9iMG-RF.js` (1,066,757 B), `index-D9iMG-RF.js.map`
> (**4,242,767 B**), `index-CizC0Esy.css` (41,876 B) and `logo-DCc7YfOk.png` (**1,553,263 B**)
> `[HOST 2026-09-11]`. So a cold load of a password-protected panel carries roughly 6.9 MB
> through a Cloudflare Tunnel, of which the source map is more than half and the logo another
> fifth. Nothing in this repository decided that either way — the map is whatever `vite build`
> emitted and the force-include takes the directory wholesale. Two separate questions follow and
> this page settles neither: whether a map that reveals the panel's source belongs on a
> production host at all, and whether `/assets/*.js.map` is reachable **without a session** —
> the application authenticates no middleware over that prefix
> (`src/bayram/admin/app.py:387-390`), and the open question is question 16 in
> [README.md](README.md).

## Decision 1 — the admin API is a third process because it must not hold a credential

The panel is not a blueprint on the bot. It is a separate process with a separate settings
class and a separate configuration file, and the reason is one sentence in
`src/bayram/admin/app.py:8-12`: `AdminSettings` **cannot read** `BAYRAM_ELEVENLABS_API_KEY`, because
there is no field for it. Introspection confirms the shape — only two `AdminSettings` *fields*
are pydantic-required (`database_url` at `src/bayram/admin/settings.py:174` and a ≥32-character
`admin_audit_hmac_key` at `:229`), and none of its fields can hold a vendor secret. The
bot and worker, by contrast, are bound to three: `_VendorBoundSettings` re-declares
`telegram_bot_token`, `elevenlabs_api_key` and `llm_api_key` as required
(`src/bayram/config.py:689-699`), and `load_settings()` always asks for that stricter model
(`:758-760`).

So the *value* is already unreachable. The lifespan then makes a second check about the
*host*: it scans both `os.environ` and the names parsed out of the admin dotenv file and
refuses to boot in prod if any of them are within reach, warning elsewhere
(`src/bayram/admin/app.py:175-203`). The forbidden list is derived, never restated —
`FORBIDDEN_ENV_VARS` is built by upper-casing `bayram.config.VENDOR_SECRET_FIELDS`
(`src/bayram/admin/app.py:116-118`; the five names at `src/bayram/config.py:111-117`), so a sixth
credential added to the config module is covered without anyone remembering to add it here.
The fifth, `openrouter_management_key`, arrived that way: **D13** added it to the config tuple
and this refusal picked it up with no edit here — which is the property this paragraph is
about, demonstrated rather than asserted.

> **Two required fields is not the same as two required variables.** Before either lifespan
> refusal below can run, `AdminSettings` has to construct, and a model validator,
> `_bounds_that_span_fields` (`src/bayram/admin/settings.py:561-592`), refuses three states that
> are field-by-field legal: `admin_cookie_secure=false` in *any* environment (`:570-576`),
> a missing `BAYRAM_ADMIN_PUBLIC_ORIGIN` whenever `environment != "dev"` — "must be set when
> environment is …" (`:578-586`, echoed at `README.md:155-157`; `.env.admin.example:73` ships
> the loopback dev value) — and DEBUG logging in prod (`:588-592`). A prod `.env.admin`
> written from the two-required-fields sentence alone produces a panel that will not boot.

Two more refusals sit in the same lifespan, in this order (`src/bayram/admin/app.py:315-316`):

1. **The panel is off unless somebody turned it on.** `BAYRAM_ADMIN_ENABLED` defaults to
   `false` (`src/bayram/admin/settings.py:180`) and the lifespan refuses while it is
   (`src/bayram/admin/app.py:206-208`). This is also the incident kill switch: taking the panel
   down is one variable and a restart, not a code change.
2. **Vendor credentials within reach**, as above.

> **A fresh admin deployment refuses to start in three tiers, and only ever reports the
> first one it hits.** Tier one is settings construction: `_resolve_settings` runs at
> `src/bayram/admin/app.py:313`, two lines *before* `_refuse_disabled_panel` at `:315`, so on a
> non-dev host the validators above — public origin, cookie-secure, DEBUG-in-prod — and the
> field requirements fire before either refusal below is reached. Tier two is
> `BAYRAM_ADMIN_ENABLED`; tier three is a vendor credential within reach. Both of the latter
> raise `ConfigError`, and the disabled-panel check runs first — so on a host with both
> problems the operator is told the panel is disabled and never learns about the key. On a
> fresh *prod* host with neither variable set, though, neither message is what appears: the
> settings error is. The
> `admin.boot.ok` line, which carries the environment, the env file actually read and the
> public origin (`src/bayram/admin/app.py:322-333`), is emitted after both, so a refused boot
> logs neither.

What this buys operationally: an admin-only host needs no ffmpeg, no Telegram reachability,
no ElevenLabs or LLM reachability, and holds nothing that can spend money. What it costs: the
admin process has **no vendor HTTP client at all** — no `ProviderSet`, no `Bot`, no `httpx`
client, and the absence *is* the control, because a process with no HTTP client has no SSRF
surface and no vendor spend to reach (`src/bayram/admin/container.py:3-7`). Its container holds
the engine, the session factory, Redis, the hasher, the trusted-proxy list, the Redis rate-limit
store (`:172`), **an ARQ queue over its own second pool** (`:179`) and a `LocalFileStorage` over
`<admin_data_root>/archive` (`:183`).

> **SUPERSEDED 2026-09-11 — the grep no longer returns nothing.** This paragraph used to read
> *"the admin process has no ARQ client and no vendor HTTP client — a grep for `enqueue_job`,
> `create_pool` or `arq` across `src/bayram/admin` returns nothing"*. The vendor-client half is
> still exactly true and is the whole of Decision 1. The ARQ half is not:
> `grep -rn "enqueue_job\|arq" src/bayram/admin/` now returns `queue.py:45` (`from arq import
> ArqRedis`), `queue.py:299` (`enqueue_job`) and `container.py:30` `[TREE 2026-09-11]`. A queue
> handle is not a credential, which is why the decision survives the change — but anyone
> re-running that grep as a *test* of the decision will now get a hit and must not read it as a
> regression. That storage object is **not** read-only in code: it is
the same read-write `LocalFileStorage` class the worker gets
(`src/bayram/runtime/container.py:311`). The read-only property is a `:ro` mount asserted in a
code comment about the deployment (`src/bayram/admin/container.py:152-154`,
`src/bayram/runtime/container.py:308`) — the code declines to `mkdir` because of it, and that is
all the code does about it.

> **The read-only store is real on this host, and the mechanism is not the one that comment
> names.** There is no `:ro` mount and there could not be — `findmnt` shows exactly one real
> filesystem, mounted `rw` (`00-host-inventory.md` row 31). What makes the panel's root read-only
> is `ProtectSystem=strict` with an **empty** `ReadWritePaths` on `hbd-admin.service`, against
> `ReadWritePaths=/var/lib/hbd /var/log/hbd` on the bot and the worker `[HOST 2026-09-10]`,
> re-read `[HOST 2026-09-11]`. The kernel, not a mount table, is what stops the panel writing a
> tree it owns. The unit file states the intent in a comment, so this was a decision rather than
> an accident. See "How the four processes are actually supervised" above; the same holds for
> `hbd-payme`, which additionally cannot read its siblings' env files at all
> (`InaccessiblePaths=/etc/hbd/hbd.env /etc/hbd/hbd-admin.env`).

**The whole of this decision is confirmed in force on the host**, from one log line the panel
emits only after both lifespan refusals have passed: `admin.boot.ok` with
`{"environment": "prod", "env_file": ".env.admin", "is_cookie_secure": true, "public_origin":
"https://admin.bayrambot.uz"}`, beside `admin.container.built` with `{"environment": "prod",
"pool_size": 5, "database": "127.0.0.1:5432/hbd"}` `[HOST 2026-09-10]`, re-read at the 06:50
boot `[HOST 2026-09-11]`. Read backwards, that single line settles four things this page used to
list as unknown: `HBD_ADMIN_ENABLED` is **true** (the lifespan refuses otherwise);
`HBD_ADMIN_PUBLIC_ORIGIN` is **set, and not to the loopback default** (the outside-dev guard
would have refused the boot, and the logged value is not the default); no vendor credential is
within reach of the process (tier three passed, in `prod`, where it raises rather than warns);
and `environment` is the exact string `prod`. Note what it does *not* settle: `env_file`
`".env.admin"` is the **unused relative default**, because this unit is fed by
`EnvironmentFile=/etc/hbd/hbd-admin.env`.

> **RETRACTED 2026-09-10, kept because it dates the change.** This page carried, until today:
> *"`deploy/systemd/bayram-worker.service:1-2` (a proposal, authored without host access) says the
> worker performs 'every operational action the admin panel queues'. **No such path exists in
> this tree today.**"* That retraction is now wrong and the proposal's comment is right. The
> panel→worker queue exists: `src/bayram/admin/queue.py` declares `EXPAND_JOB_NAME`,
> `SEND_JOB_NAME`, `TEST_SEND_JOB_NAME` and `PAYMENT_NOTIFY_JOB_NAME`, and
> `src/bayram/runtime/jobs.py:758-762` names the other side — *"THE THREE BROADCAST JOBS. Their
> enqueue side is the ADMIN PANEL — the second process after the Payme gateway whose jobs run
> here — so all three names are stated explicitly rather than taken from `__qualname__`"*
> `[TREE 2026-09-11]`. The names are restated in both modules on purpose, because
> `bayram.admin.queue` must not import the worker's module (which would drag a `Bot` into a
> process denied a token) and a rename that compiled on both sides would break the edge
> silently. All three job names are in the host's worker boot banner `[HOST 2026-09-11]`, so the
> edge is live, not merely declared. What *remains* true from the retracted paragraph: the panel
> still holds no credential and no vendor HTTP client, which is the whole of Decision 1. A queue
> handle is a Redis write, not a secret.

## Decision 2 — the two Postgres roles, and what breaks with one

The *intent*, stated in `docker/initdb/10-two-roles.sql:17-18`, is that `hbd` owns the tables
and runs migrations while "the bot, the worker and the admin API connect as `hbd_app`". The
repo only half ships that: `.env.example:35` is
`BAYRAM_DATABASE_URL=postgresql+asyncpg://hbd_app:hbd_app@…`, but `.env.admin.example:48` is
`postgresql+asyncpg://hbd:hbd@…` — the **owner** DSN, in the example file for the one process
whose connection identity decides the audit-log badge. An untouched copy of that example
already connects the panel as the owner.

> **The example's defect was not copied onto this host — and the control it protects is still
> `[UNPROVEN]`.** Every PostgreSQL backend on the box connects as the application role
> **`hbd_app`** to database `hbd`; there is no backend connected as an owner role
> `[HOST 2026-09-10]`, re-read `[HOST 2026-09-11]`. So whatever `/etc/hbd/hbd-admin.env`
> contains, it is not `.env.admin.example:48`'s owner DSN, and the first consequence below does
> not apply here. The rest of Decision 2 stays open, and for a stated reason rather than for
> lack of looking: **`psql` is behind the password wall.** Connecting as `hbd_app` over TCP
> fails with `fe_sendauth: no password supplied`, there is no peer path, and the `NOPASSWD`
> sudoers drop-in grants `pg_dump` but **not** `psql` (`00-host-inventory.md` row 44). So
> whether the owner role `hbd` exists, whether `HBD_DB_MIGRATION_URL` is set, whether `0007`'s
> `REVOKE` ever landed, and what `\dp admin_audit_log` says are all `[UNPROVEN]` from the deploy
> account. `00-host-inventory.md` rows 11–14. The way past it is not more shell: sign in and read
> `chainProtection` on `GET /api/audit/verify` — remembering what the third consequence below
> says about what that badge can and cannot mean.

That split exists for exactly one control:

```sql
REVOKE UPDATE, DELETE, TRUNCATE ON admin_audit_log FROM <app role>
```

An owner can `GRANT` back its own revocations in one statement, so that `REVOKE` — migration
`0007`'s, at `migrations/versions/20260830_1000_0007_add_admin_audit_log.py:369` — means
nothing at all when the application connects as the owner. There is also nobody to revoke it
*from*: with one role, `<app role>` names the same principal that ran the migration
(`docker/initdb/10-two-roles.sql:7-23`, restated at `README.md:160-164`).

Two variables switch it on. `BAYRAM_DB_MIGRATION_URL` is the owner DSN, which
`migrations/env.py:95-114` reads from the environment *and* from the dotenv file; unset,
migrations fall back to the application DSN with a WARNING that names what control that costs
(`migrations/env.py:87-93`, `:116-129`). `BAYRAM_ADMIN_AUDIT_DSN` is how a deployment declares
the split exists (`README.md:172-178`).

> **This is the only control in the schema that survives a compromised application
> credential.** Everything else in the audit design is an HMAC that the same credential could
> recompute if it could write. Losing the two-role split does not degrade the audit log a
> little; it removes the privilege half of it entirely.

Three consequences an operator must hold in their head:

- **`chainProtection` answers a narrower question than it looks.** It is not read from
  configuration when it runs: `resolve_chain_protection` asks Postgres, with
  `has_table_privilege(current_user, 'admin_audit_log', …)` on UPDATE, DELETE and TRUNCATE
  (`src/bayram/db/admin/audit.py:746-780`), and a still-writable table logs
  `admin.audit.revoke_missing` at WARNING while the panel reports `hmac-only`. **But
  configuration decides whether the probe runs at all.** The function opens with
  `if not is_dsn_configured or not _is_postgres(session): return ChainProtection.HMAC_ONLY`
  (`:764-765`), and `is_dsn_configured` is `bool(settings.admin_audit_dsn)`
  (`src/bayram/admin/routers/audit.py:168`) — i.e. `BAYRAM_ADMIN_AUDIT_DSN`, which defaults to `""`
  (`src/bayram/admin/settings.py:235`) and ships empty (`.env.admin.example:130`). So a
  deployment that created both roles, migrated as the owner and landed `0007`'s `REVOKE`, but
  left `BAYRAM_ADMIN_AUDIT_DSN` blank, reports `hmac-only` with **no probe and no WARNING** —
  indistinguishable from a deployment where the control genuinely is not there. Read the
  badge as "is the split *declared*, and if so is it in force", never as "did the `REVOKE`
  land". Only `\dp admin_audit_log` in psql answers the second question on its own.
- **When it does probe, it asks about the admin process's own connection.** Nothing in
  `AdminSettings` refuses an owner DSN there, and `.env.admin.example:48` supplies one. Point
  the panel at the owner role with `BAYRAM_ADMIN_AUDIT_DSN` set and the panel itself can rewrite
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
> always demands the three required vendor secrets (`src/bayram/config.py:758-760`). A
> migration-only host, or a CI step holding only the DSN, fails with a message about missing
> API keys. Setting `BAYRAM_DB_MIGRATION_URL` avoids that path entirely.

## Why the environment variable is the fragile part of all of this

Every production guard in the codebase hinges on `BAYRAM_ENVIRONMENT` being the exact string
`prod`, and the **three** settings classes treat it differently. `AdminSettings.environment`
is a closed `Literal["dev","staging","prod"]` (`src/bayram/admin/settings.py:169`), so a typo is
a boot failure. `PaymeSettings.environment` is the same closed literal, defaulting to `"dev"`
(`src/bayram/payme/settings.py:115`, `:162`), with `is_production` again `== "prod"` (`:348`)
`[TREE 2026-09-11]`. `Settings.environment` — the bot's and the worker's — is an unvalidated
free-form `str` with a `"dev"` default (`src/bayram/config.py:170`), and `is_production` is a
bare `== "prod"` (`:684-686`).

> **On this host the variable reads `prod` in three processes and `dev` in the fourth — the
> silent cross-file drift this section warns about, now live on the machine that took money.**
> `bot=prod`, `worker=prod`, `admin=prod`, **`payme=dev`**, read off the boot lines rather than
> the files, in both `payme.container.built` and `payme.boot.ok` `[HOST 2026-09-10]`,
> re-confirmed at the 06:50 boot `[HOST 2026-09-11]`. No typo is involved: `dev` is
> `PaymeSettings`' shipped default, the literal accepts it, and nothing cross-checks the three
> files. Two controls on the gateway are consequently **inert**, and both are gated on
> `is_production` rather than on anything a reader would notice:
>
> - `_refuse_foreign_credentials` (`src/bayram/payme/app.py:203`) raises only
>   `if settings.is_production` (`:219-220`) and otherwise **warns**. So a vendor credential
>   within reach of the process holding the cashbox key is a log line here, not a refusal.
> - `_debug_is_refused_in_prod` (`src/bayram/payme/settings.py:330`) is a model validator that
>   fires only when `is_production`. Its own docstring says why it exists: at DEBUG the ORM
>   echoes bound parameters, and on this process those parameters are *"an idempotency key
>   carrying a Telegram user id and a rail-side transaction id — the two values that join a
>   person to a payment."* On this host that refusal does not exist. `[TREE 2026-09-11]`
>
> The two refusals that **do** run unconditionally are `_refuse_disabled_gateway` and
> `_refuse_a_blank_key` (`src/bayram/payme/app.py:631-633`) — and since the gateway booted, both
> passed: `payme_enabled` is true and the merchant key is non-blank, 36 characters by its own
> boot line. Whether `dev` here is a deliberate staging posture for a sandbox cashbox or an
> oversight is not a question this page can answer; it is recorded in
> [09-payme-go-live.md](09-payme-go-live.md) and [08-payme.md](08-payme.md), and it is the kind of
> state that looks intentional for exactly as long as nobody asks.

`BAYRAM_ENVIRONMENT=production` on the bot or worker therefore silently disables both refusals
those processes have: fake providers in prod (`src/bayram/runtime/providers.py:104-109`) and the
in-process submitter in prod (`src/bayram/runtime/submitter.py:100-105`). No error is raised
anywhere, and the symptom is customers being served silence and template lyrics.

The files also own the variable independently — `BAYRAM_ENVIRONMENT` appears in the bot's dotenv
file, the admin's and the gateway's, and all three classes use `extra="ignore"`
(`src/bayram/config.py:165`, `src/bayram/admin/settings.py:164`,
`src/bayram/payme/settings.py`), so no file's copy can correct or even notice another's. `prod`
in some and `dev` in another is a completely legal, silent state — and, as the callout above
records, it is the state this host is in.

And *which* two files those are is itself a variable. `.env` and `.env.admin` are only the
defaults (`src/bayram/config.py:69-78`); `BAYRAM_ENV_FILE` and `BAYRAM_ADMIN_ENV_FILE` redirect each
side independently, which is exactly what `ENV=prod make dev` does through `$(ENV_FILES)`
(`Makefile:41-46`, `:69`). Both are read from the process environment only — a dotenv file
cannot name the file about to be read — so the pairing that is actually in force on a host is
visible in the boot logs (`src/bayram/runtime/startup.py:31-34`,
`src/bayram/admin/app.py:327-329`) and nowhere in the checkout.

## What is knowable from here, what the host settled, and what is still behind a wall

Knowable from the tree, and cited above: the four command lines and the three by-hand commands;
every dependency edge and the code that opens it; the cron declarations; the boot refusals and
their order, settings validators included; the data-root derivation on both sides; the pool
arithmetic; the two roles and what the `REVOKE` protects.

**Answered on the host, 2026-09-10, re-confirmed 2026-09-11.** This list used to be the page's
"not knowable" section. It is kept in the same order, with each bullet replaced by its answer,
because the question is what tells you why the answer matters:

| Was asked | Answer |
| --- | --- |
| whether the VPS uses systemd, and whether `bayram-bot`/`bayram-worker`/`bayram-admin` exist under the names and paths `deploy/systemd/*.service` proposes | **systemd, yes — under the PRE-RENAME names.** Four units `hbd-bot`, `hbd-worker`, `hbd-admin`, `hbd-payme` in `/etc/systemd/system/`, `root:root 0644`, `User=hbd`, `WorkingDirectory=/var/lib/hbd`. The proposal's `bayram-*` names, `/srv/bayram` checkout and `/etc/bayram` paths **do not exist**. |
| whether all the processes run there at all, on one box or several | **Four, one box (`abdu-test`), all active**, sharing one PostgreSQL 16 and one Redis 7.0.15 on loopback. |
| what terminates TLS in front of the admin API, whether it adds HSTS, and whether it appends or replaces `X-Forwarded-For` | **Cloudflare terminates TLS**; a tunnel (`aizu-vds`) speaks plain HTTP to `127.0.0.1:80`; Caddy v2.11.4 proxies to `:8080`. **Caddy adds `Strict-Transport-Security: max-age=86400`**, no `includeSubDomains`, no `preload`; the application adds none — proven by comparing a response through Caddy with one straight to `:8080`, not merely asserted from `src/bayram/admin/middleware/security_headers.py:73-77`. The `X-Forwarded-For` half is not settled — see the wall below. |
| the working directory, and therefore whether the bot's `Path.cwd()/var` and the admin's `admin_data_root` resolve to the same path | **`/var/lib/hbd` on all four units**, and the bot resolves `workspace: /var/lib/hbd/var/workspace`. The two roots agree **by construction** unless `HBD_ADMIN_DATA_ROOT` overrides the panel's — which is the one residual unknown here. |
| whether the admin's `var/` is really mounted `:ro` | **It is read-only, and not by a mount.** `ProtectSystem=strict` with empty `ReadWritePaths` on `hbd-admin` and `hbd-payme`; `ReadWritePaths=/var/lib/hbd /var/log/hbd` on the bot and worker. There is one filesystem on the box and it is `rw`. |
| which dotenv file each process actually reads | **Three of four do not use the mechanism this page describes.** `EnvironmentFile=/etc/hbd/hbd.env` (bot, worker), `/etc/hbd/hbd-admin.env` (panel); only `hbd-payme` uses `Environment=HBD_PAYME_ENV_FILE=/etc/hbd/payme.env`. So `host verified` and `admin.boot.ok` name the **unused relative default**, and on this host the boot log is *not* evidence about where configuration came from. |
| whether `BAYRAM_ENVIRONMENT` is the exact string `prod` in each process | **`prod` in the bot, the worker and the panel; `dev` in the gateway** — with two Payme boot controls inert as a result. |
| whether `BAYRAM_ADMIN_ENABLED` is true | **True**, proven by `admin.boot.ok` being emitted at all, which happens only after the disabled-panel refusal. |
| how many worker replicas run | **One.** `concurrency: 15`, the shipped default. The per-process vendor semaphore still means what it says here. |
| whether the install is an editable checkout or a wheel, and whether the console bundle was built from current source | **A wheel**, `hbd_bot-0.1.0-20260909`, sha256 `369db098…5587f3`, no `.pth`; `migrations/` shipped separately at `/opt/hbd/migrations`; the bundle is present, served, and substitutes a fresh nonce per response. **Whether it matches current source is still open** — it was built elsewhere (there is no Node on the box) and installed 2026-09-10 00:01. |
| whether the host's ffmpeg carries `libopus` | **Yes, directly observed** rather than inferred from a running bot: ffmpeg 6.1.1-3ubuntu5 lists `libopus`. |

**Still not settled, and each one names its blocker rather than staying an open guess.** Most of
them are one wall: `/etc/hbd` is `0750 root:hbd`, the `hbd` group has no members, `sudo -n`
refuses, `/var/lib/hbd` is `0750 hbd:hbd` and untraversable, and `psql` needs a password the
deploy account does not have.

- **Whether `HBD_ADMIN_DATA_ROOT` is set** in `/etc/hbd/hbd-admin.env`. `[UNPROVEN]` — file
  unreadable; the variable appears in no boot line. If unset, the two object roots agree.
- **`HBD_ADMIN_TRUSTED_PROXY_HOPS` and `_CIDRS`.** `[UNPROVEN]` — file unreadable, and the
  `admin.request` log line carries no client-IP field to infer it from. This one **got worse
  without anything reporting it**: admin traffic is now two proxies deep (Cloudflare edge, then
  Caddy), and `/etc/caddy/Caddyfile:69-70` prescribes `HBD_ADMIN_TRUSTED_PROXY_HOPS=2` with
  `HBD_ADMIN_TRUSTED_PROXY_CIDRS=127.0.0.1/32` in a comment. Nothing confirms the file agrees.
  At the shipped default of `0`, every audit row's `ip` and every login rate-limit bucket
  collapses onto the proxy's address while the panel looks healthy. `00-host-inventory.md` row 23.
- **Whether the two Postgres roles exist, whether `HBD_DB_MIGRATION_URL` is set, and whether
  `0007`'s `REVOKE` landed.** `[UNPROVEN]` — `psql` refuses (`fe_sendauth: no password
  supplied`) and the sudoers drop-in deliberately does not grant it. `chainProtection` on
  `GET /api/audit/verify` cannot settle it either: with `BAYRAM_ADMIN_AUDIT_DSN` empty it returns
  `hmac-only` **without probing** (`src/bayram/db/admin/audit.py:764-765`).
- **Whether an operator account exists at all.** `[UNPROVEN]` — `bootstrap` is a one-time manual
  step that leaves no trace anything else reports, and the only evidence is a row in
  `admin_users`.
- **Whether `HBD_LLM_FALLBACK_BASE_URL` is set**, which decides whether the egress allowlist
  needs a fourth host. `[UNPROVEN]` — file unreadable, and the hourly poll's two-provider
  output (`elevenlabs_subscription`, `openrouter_key`) does not distinguish "fallback unset" from
  "fallback set but never polled".
- **Whether the served bundle matches current source.** `[UNPROVEN]` — the wheel was built on
  another machine and the tree has since been renamed; the deployed shell still carries the
  pre-rename `__HBD_CSP_NONCE__`.
- **Whether `/assets/*.js.map` is reachable without a session.** `[UNPROVEN]` — the application
  authenticates nothing over that prefix, so the answer belongs to Cloudflare and to Caddy.

A `[UNPROVEN]` above is not an invitation to fill it in from the proposal in `deploy/`. Each needs
root on `abdu-test`, or a signed-in panel session, and the command that would answer it is named
in [00-host-inventory.md](00-host-inventory.md) beside the row it belongs to.
