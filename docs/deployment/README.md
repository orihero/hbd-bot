# Deployment documentation

**Start here:** deploying a change today → [04-release.md](04-release.md); standing up a new
host → [03-provisioning.md](03-provisioning.md); something is broken right now →
[06-troubleshooting.md](06-troubleshooting.md). All three assume the host facts in
[00-host-inventory.md](00-host-inventory.md), which is empty.

---

## STATUS — read this before you trust a single line below

**The product is already deployed to a VPS reachable as the ssh alias `aizu`. Nothing in this
directory was verified against it. Every document here is derived from this repository
alone.**

Nobody who wrote these nine documents had access to that machine. What that means in
practice:

- **Claims about the code are checkable.** Every one carries a `file.py:line` from this
  working tree. Doubt a sentence, open the file.
- **Claims about the host are not made.** Where a procedure needs a host fact — a path, a
  service manager, a TLS terminator, the contents of a dotenv file — it is written as a
  placeholder you fill in, or as a question to answer on the box.
- **`deploy/` is a proposal, not a record.** `deploy/systemd/*.service` and the install
  narrative preserved beside them as `deploy/first-install-proposal.md` were authored in this
  repository on the same day, by an assistant that also had no host access. They describe a
  coherent `/srv/hbd` + systemd shape that somebody could deploy. They are not evidence that
  anything is deployed that way, and nothing here establishes that the host runs systemd at
  all. Several documents below borrow that proposal's nouns (`/srv/hbd`, `hbd-bot.service`)
  for want of anything better; each flags it at the point of use.
- **`00-host-inventory.md` is where this gets fixed.** It is a 39-row table, every cell
  empty, every row carrying the command that fills it, plus one read-only SSH discovery
  block that answers most of them in a single paste. Once it is filled in, **it wins**: where
  a filled-in row disagrees with 01–08 or with `deploy/`, the row is right and the other
  document is describing a machine that does not exist. Rows 37 and 38 are the newest and the
  most load-bearing: the hostname Payme calls and the caller-IP allowlist at the terminator,
  neither of which any code in this repository can supply or check.

Until that table has values in it, treat this directory as *the shape we propose and the
reasons for each line*, never as a description of a running system.

---

## The documents

| # | Document | What it is for |
| - | -------- | -------------- |
| 00 | [The aizu host — inventory](00-host-inventory.md) | The 39 host facts nobody here could check, each with the command that answers it, plus one read-only SSH block that answers most in a single paste. Empty on purpose; the reference every other page defers to once filled in. |
| 01 | [Deployed architecture](01-architecture.md) | The three long-running processes and the three by-hand commands, what talks to what, why only the worker runs the clocks, and why the admin API is a separate process that must not hold a vendor credential. |
| 02 | [Configuration reference](02-configuration.md) | Every variable production actually requires, which of the two settings classes owns it, which file each of the four commands reads, the five refusals that key off `HBD_ENVIRONMENT`, and the defects in `.env.admin.example` to fix before copying it. |
| 03 | [Provisioning a host from bare metal](03-provisioning.md) | Fourteen steps from a fresh OS to a booting fleet — packages, roles, dotenv modes, schema, console build, first OWNER, supervision, TLS — written as the audit checklist to compare `aizu` against, **not** a runbook to replay on it. |
| 04 | [Releasing a change](04-release.md) | The routine deploy to an already-provisioned host: three pre-flight gates, pull, dependency sync, migrations, the non-optional console rebuild, restart order, verification, and what can and cannot be rolled back. |
| 05 | [Day-2 operations](05-operations.md) | Operator accounts and the bootstrap CLI, the credits and identity tools, the three cron jobs, verifying the audit chain, the log events worth an alert rule, and backup/restore. |
| 06 | [Troubleshooting](06-troubleshooting.md) | Nineteen symptoms, each with what an operator sees, the code that produces it, one command that settles the question, and the fix. Biased towards the failures that look healthy. |
| 07 | [Security controls and their deployment dependencies](07-security.md) | Seven controls — vendor-credential separation, CSP and the style nonce, `__Host-` cookies, the exact origin check, trusted proxies, the audit HMAC chain and its REVOKE, loopback binding — each as: what it protects, what the deployment must do, how to prove it is on, how it fails. Ends with the ones that degrade silently. |
| 08 | [The Payme gateway](08-payme.md) | The fourth process, which is off unless `HBD_PAYME_ENABLED=true`: its systemd unit and `/etc/hbd/payme.env`, the connection arithmetic and the `hbd_app` role check, the TLS terminator contract including the `185.234.113.0/28` caller allowlist, the cabinet settings a human types, and the certification, manual-refund, key-rotation and weekly-reconciliation runbooks. |

The actual deployment artefacts — the unit files — live in
[`deploy/systemd/`](../../deploy/systemd/), not here. This tree is prose about them.

---

## Open questions

Every one of these needs somebody to look at `aizu`. They are ordered by what would hurt most
if the answer is wrong, not by how easily they are answered. Each command is read-only.
`00-host-inventory.md` carries the same questions as a table you can paste answers into,
along with an SSH block that runs most of them at once.

**1. Is anything backing up Postgres, `var/archive`, or `HBD_ADMIN_AUDIT_HMAC_KEY`?**
Nothing in this repository backs anything up — `grep -rin backup README.md Makefile deploy/`
returns nothing operational. `var/archive` holds every delivered song *and* every customer
avatar (`src/hbd/storage.py:73-84`, `src/hbd/user_profiles.py:199-200`). The HMAC key has no
key id (`src/hbd/db/admin/audit.py:10-12`), so if it exists only in the admin's dotenv file,
losing that file makes the entire audit log permanently unverifiable.
```bash
ssh aizu 'crontab -l 2>/dev/null; sudo ls -la /etc/cron.d 2>/dev/null; systemctl list-timers --all 2>/dev/null | grep -Ei "dump|backup|hbd"'
```

**2. Is `HBD_ENVIRONMENT` the exact string `prod` in *both* dotenv files?**
`Settings.environment` is an unvalidated `str` (`src/hbd/config.py:170`) compared with `==`;
the two settings classes own it independently. `production`, `Prod` or a stray space silently
disarms the fake-provider refusal (`src/hbd/runtime/providers.py:104`) and the
in-process-submitter refusal (`src/hbd/runtime/submitter.py:100`) with no error anywhere.
```bash
ssh aizu 'sudo grep -n "^HBD_ENVIRONMENT=" <bot env> <admin env>'
```

**3. Is `HBD_CREDITS_ENFORCED` true, with a price on screen?**
`src/hbd/main.py:177-189` logs a warning and *never refuses* when the checkout is wired and
the credit meter is dark. The customer is shown a price and charged; the worker then covers
the shortfall with an `UNENFORCED_RENDER` grant and renders anyway. Silent and expensive in
exactly one direction.
```bash
ssh aizu 'sudo grep -n "^HBD_CREDITS_ENFORCED=" <bot env>'   # then grep the bot log for "the credit meter is dark"
```

**4. What alembic revision is the live database actually at?**
The repo head is `0021`
(`migrations/versions/20260908_1200_0021_add_dashboard_read_indexes.py:93`). `make migrate` is
a manual step in every documented procedure, so a deploy that pulled code and restarted
services leaves the schema behind. The `-d hbd` is load-bearing: without it `psql` reports
`relation "alembic_version" does not exist`, which reads as "no migration ever ran".
```bash
ssh aizu 'sudo -u postgres psql -d hbd -Atc "select version_num from alembic_version"'
```

**5. Do the bot's working directory and the admin's data root resolve to the same absolute path?**
The bot and worker derive their data root from `Path.cwd()/"var"` with no environment
override (`src/hbd/runtime/container.py:286`); the admin defaults `admin_data_root` to a
*relative* `var` (`src/hbd/admin/settings.py:423`). If the two processes have different
working directories, every media reveal in the panel 404s while the database row insists the
file is there. Agreement is a deployment fact, not a code guarantee.
```bash
ssh aizu 'for p in $(pgrep -f "hbd.main|arq hbd.worker|uvicorn"); do ls -l /proc/$p/cwd; done; sudo grep -n "^HBD_ADMIN_DATA_ROOT=" <admin env>'
```

**6. Are all three processes running, on one box or several, under what supervisor, and with what in front of the admin API?**
The repo assumes a shared Redis and a shared filesystem root but proves nothing about
topology. Whether the host uses systemd at all is unknown; `deploy/systemd/*.service` is a
same-day proposal. TLS termination is named only as a suggestion ("Caddy or nginx",
`deploy/first-install-proposal.md:56`), and nothing in the package binds a socket — the bind is on the
uvicorn command line. A serving panel does prove `HBD_ADMIN_ENABLED=true`, since the lifespan
refuses without it (`src/hbd/admin/app.py:206-208`, default `false`).
```bash
ssh aizu 'systemctl list-units --type=service | grep -i hbd; docker ps; pgrep -af "hbd.main|arq hbd.worker|uvicorn"; ss -ltnp'
```

**7. How many worker replicas run?**
The music and TTS concurrency semaphores are per-process
(`src/hbd/runtime/container.py:332-333`), so any count above 1 silently multiplies the vendor
ceiling — and the spend.
```bash
ssh aizu 'pgrep -cf "arq hbd.worker"'
```

**8. Is the two-role split real: do `hbd` and `hbd_app` exist, did migration 0007's REVOKE land, and do default privileges cover the tables created since?**
`_install_two_role_controls` reads `HBD_ADMIN_AUDIT_DSN` from `os.environ` only and skips
silently otherwise
(`migrations/versions/20260830_1000_0007_add_admin_audit_log.py:336-338`); no documented
workflow exports it, so the prediction from the code is that the REVOKE is **not** in force.
`docker/initdb/10-two-roles.sql` runs only on an empty local Docker volume and its own header
says production roles are made by hand — if its `ALTER DEFAULT PRIVILEGES` was missed, every
table from migrations 0014–0021 is invisible to the application role. The panel's own answer
is honest in both directions because it asks Postgres rather than trusting configuration.
```bash
ssh aizu 'sudo -u postgres psql -Atc "select rolname from pg_roles order by 1"; sudo -u postgres psql -d hbd -c "\dp admin_audit_log"'
# or, from the panel: GET /api/audit/verify → chainProtection ("hmac-only" means it is not in force)
```

**9. Is production Redis persistent, and where does Postgres live?**
`--appendonly yes --save 60 1` and the `redis_data` volume are facts about the **local**
compose stack only (`docker-compose.yml:1-2` says local-only). A production Redis with
default or no persistence loses every in-flight wizard draft and every queued job on
restart. Separately, the SQLAlchemy pools are sized against an assumed stock
`max_connections` of 100 with a 10-connection margin (`src/hbd/db/engine.py:64-67`).
```bash
ssh aizu 'redis-cli INFO server | head -5; redis-cli CONFIG GET appendonly; redis-cli CONFIG GET save; redis-cli CONFIG GET dir; sudo -u postgres psql -Atc "show max_connections"'
```

**10. Does `HBD_ADMIN_PUBLIC_ORIGIN` match the origin browsers actually reach, and how many proxy hops sit in front?**
The origin is compared exactly (`src/hbd/admin/settings.py:578-588`): a loopback value
inherited from the example file boots, passes `/healthz`, serves a login page, then 403s
every mutation with `ORIGIN_REJECTED`. And with the shipped defaults for
`HBD_ADMIN_TRUSTED_PROXY_HOPS` (0) and `_CIDRS` (empty)
(`src/hbd/admin/settings.py:216-217`), every audit row and every rate-limit key records the
proxy's address rather than the client's.
```bash
ssh aizu 'sudo grep -nE "^HBD_ADMIN_(PUBLIC_ORIGIN|TRUSTED_PROXY|PROBE_TOKEN)" <admin env>'
```

**11. Which dotenv file is each live process actually reading?**
The defaults are `.env` and `.env.admin`; any path can be supplied via `HBD_ENV_FILE` /
`HBD_ADMIN_ENV_FILE` (`src/hbd/config.py:81-97`, `src/hbd/admin/settings.py:65-81`). The
proposal puts them at `/etc/hbd/bot.env` and `/etc/hbd/admin.env`. Every question above that
says "`<bot env>`" or "`<admin env>`" depends on this answer, and the boot log states it
directly.
```bash
ssh aizu 'for p in $(pgrep -f "hbd.main|arq hbd.worker|uvicorn"); do sudo tr "\0" "\n" < /proc/$p/environ | grep -E "^HBD_(ADMIN_)?ENV_FILE="; done'
# or read env_file off the boot lines: "host verified" (bot/worker) and "admin.boot.ok" (panel)
```

**12. Is the served console bundle current, and was it built on this host at all?**
`src/hbd/admin/static/` is gitignored, so a fresh checkout has no console and a stale one is
whatever the last build left. A bundle predating the `__HBD_CSP_NONCE__` placeholder
(`src/hbd/admin/shell.py:55`) is served unchanged, looks like a working panel, and logs
`admin.spa.nonce_placeholder_missing` (`shell.py:83`). Node arrives on that box by a path no
document records: `deploy/first-install-proposal.md:89` installs only ffmpeg,
postgresql-16 and redis-server, yet its lines 113/130 run `npm ci && npm run build`; `admin-ui/package.json` needs node >= 20.19.
```bash
ssh aizu 'node -v; npm -v; ls -la <checkout>/src/hbd/admin/static/index.html; grep -c __HBD_CSP_NONCE__ <checkout>/src/hbd/admin/static/index.html'
```

**13. Does the host's ffmpeg have `libopus` — and an mp3 encoder?**
`libopus` is the only encoder the boot probe checks, and its absence is a hard refusal
(`src/hbd/audio/startup.py:96-103`), so a *running* bot is itself the evidence. The mp3
encoder the song master needs is checked by nothing. Do not assume the build:
`pyproject.toml:36-38` records that at least one machine in this project's history had an ffmpeg without `drawtext`.
```bash
ssh aizu "ffmpeg -hide_banner -encoders | grep -E 'libopus|libmp3lame'; command -v ffprobe"
```

**14. Is the install an editable checkout or a built wheel, and is `migrations/` on disk?**
The two differ in how the console is served (checkout static dir vs. hatch `artifacts`
force-include), and `migrations/` is not in the wheel while every documented alembic
invocation assumes it is on disk. `deploy/first-install-proposal.md:129` invokes
`.venv/bin/uv`, which cannot exist from its own instructions (`uv` is in neither `pyproject.toml` nor `uv.lock`), so
whatever actually ran there is unknown. Also unknown: whether the host checkout has an
`admin-ui/public/` directory — it is untracked here, so a clone would not create it.
```bash
ssh aizu 'ls <checkout>/.venv/lib/python3.12/site-packages/ | grep -i hbd; <checkout>/.venv/bin/python -V; ls <checkout>/migrations/versions | tail -3; ls -d <checkout>/admin-ui/public'
```

**15. Has the retention cron ever fired, and is `var/workspace` growing without bound?**
Nothing in the repository deletes `var/workspace`, so absent an out-of-band sweep it holds a
second, unexpiring copy of every song, greeting and lyric ever generated. Only the worker
runs the clocks, so a worker that has been down has also stopped re-pinning the audit HEAD
anchor. `storage_keys_returned` exceeding `storage_keys_deleted` is bytes leaking.
```bash
ssh aizu 'sudo -u postgres psql -d hbd -c "select ran_at, is_batch_full, storage_keys_returned, storage_keys_deleted from purge_runs order by ran_at desc limit 5"; du -sh <checkout>/var/workspace <checkout>/var/archive'
```

**16. Are `/assets/*.js.map` reachable from the public internet?**
The application does not protect them — no middleware authenticates that prefix
(`src/hbd/admin/app.py:387-390`). If anything blocks them it is whatever terminates TLS,
which is question 6.
```bash
curl -sI https://<panel host>/assets/<some-bundle>.js.map | head -1
```
