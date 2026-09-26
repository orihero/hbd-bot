# Releasing a change

## STATUS — §2, §3 and §5 of this document cannot be run on `aizu`. Updated 2026-09-11.

**There is no git checkout on the production host, and there never has been.** `/opt/hbd`
holds `venv/`, `release/`, `migrations/` and four loose scripts; `test -d /opt/hbd/.git`
answers `NO .git in /opt/hbd` `[HOST 2026-09-11]`. `/srv` is empty — two entries, no children
— so `/srv/bayram` and `/srv/hbd` have never existed on this machine `[HOST 2026-09-11]`.
There is no `admin-dashboard/`, no `node`, no `npm` and no `uv` on the box
`[HOST 2026-09-11]`.

So: **§2 (`git pull --ff-only`) fails on its first line. §3 (`uv pip install -e`) has no
checkout to point at and no `uv` to run it. §5 (`npm ci && npm run build`) has neither the
directory nor the toolchain. §8's "check out the SHA from §2" has no repository to check it
out of.** Those sections are kept — they are still correct for a host that *does* have a
checkout, and §3's and §5's *arguments* are exactly what the wheel model has to compensate
for — but on `aizu` you want §0 and nothing else above §4.

**A release on `aizu` is a wheel.** §0 is the shape and the state. The worked end-to-end
procedure, written from the script that actually performed it, is
[`08-payme.md`](08-payme.md) **§11**, and this page deliberately does not restate it: §11.1
(the model and the privilege), §11.2 (the filename), §11.3 (the migrations trap), §11.4 (the
order), §11.5 (`--no-deps` and `pip check`), §11.7 (rollback), §11.8 (idempotency). Read §0,
then read §11.

### The three marks

The convention is [`01-architecture.md`](01-architecture.md)'s, and it is load-bearing:

- **`[HOST 2026-09-11]`** — a read-only command was run against `aizu` (machine `abdu-test`)
  on that date and what is quoted is faithful to its output. The command is named where it is
  not obvious.
- **`[TREE 2026-09-11]`** — checkable by opening a file in this working tree; a `path:line` is
  given.
- **`[UNPROVEN]`** — exactly that, with the blocker named. On this page the blocker is almost
  always the same one: `sudo -n true` returns `sudo: a password is required`, the `NOPASSWD`
  drop-in grants `pg_dump` and not `psql`, and `/etc/hbd` is `0750 root:hbd`.

**The host is PRE-RENAME and that is correct.** Host commands below are spelled `hbd`,
`HBD_`, `/etc/hbd`, `/opt/hbd` because that is what the machine says; code claims are spelled
`bayram`, `BAYRAM_` because that is what this tree says. Both are right at once — the argument
is [`09-payme-go-live.md`](09-payme-go-live.md) §1.2. **Do not sweep this page with a rename
pass**; a blind rename has already turned verified host facts into fiction in this tree once
([`00-host-inventory.md`](00-host-inventory.md), finding 7).

**Reading order, for a release on `aizu` today:** §0 (all of it, including the four warnings in
§0.4), then §1 on your own machine, then [`08-payme.md`](08-payme.md) §11 for the procedure,
then §6 and §7 here for the restart order and what to read in the journal, then §8 before you
need it. §2, §3's editable path and §5 are kept for their arguments and for hosts that have a
checkout. Read the whole thing top to bottom the first time; after that it is a checklist and
the callouts are the parts that bite.

> **SUPERSEDED 2026-09-10, kept because it dates the change.** This document opened, until
> 2026-09-10, with: *"Everything about the **host** is not [checked]. This repository does not
> know where the checkout lives, what supervises the three processes, or what terminates TLS
> in front of the admin API. `deploy/first-install-proposal.md` and `deploy/systemd/*.service`
> describe a systemd deployment under `/srv/bayram` — those files are untracked in this branch
> and were written without access to the box, so they are a **proposal**, not a record."*
>
> Three claims, and they have aged differently.
>
> - **"Nobody has access to the box" is false.** `ssh aizu` has been routine since
>   2026-09-09. [`00-host-inventory.md`](00-host-inventory.md) is the inventory of record;
>   [`08-payme.md`](08-payme.md) §11 is the release runbook as executed.
> - **"Untracked" was wrong.** `git ls-files deploy/` lists `README.md`, both
>   `caddy/*.caddy` site files, `deploy-payme.sh`, `first-install-proposal.md` and all four
>   `systemd/bayram-*.service` units as tracked `[TREE 2026-09-11]`. Only
>   `deploy/cutover-to-bayram.sh` and `deploy/payme-open-orders.py` are untracked. The word
>   appeared four times on this page and is gone from all four.
> - **"A proposal, not a record" is still exactly right**, and has got *worse* rather than
>   better. §0.3 names which files in `deploy/` have drifted and §0.4 is the one that will
>   cost you a window.

---

## 0. What a release on `aizu` actually is

### 0.1 The model, in six lines

```
build the wheel on a developer machine        uv build --wheel
check the FILENAME parses as PEP 427          08-payme.md §11.2 — this has already cost a window
scp it into /opt/hbd/release/                 the account is `developer`, which OWNS /opt/hbd
copy any NEW migration files separately       a wheel carries none — 08-payme.md §11.3
/opt/hbd/venv/bin/pip install --force-reinstall --no-deps <wheel>  &&  pip check
restart, in the order §6 argues for
```

Every one of those six lines has a failure mode with a name, and all six are developed in
[`08-payme.md`](08-payme.md) §11.1–§11.5. Do not re-derive them from this page; the reason
they are written there rather than here is that §11 was written **from the script that ran**,
and this page was written from the repository.

**What is installed right now** `[HOST 2026-09-11]` — `pip`, non-editable, from a file URL:

```
INSTALLER                                    pip
direct_url.json url                          file:///opt/hbd/release/hbd_bot-0.1.0-20260909-py3-none-any.whl
direct_url.json sha256                       369db0983508619badec41ed50f72e53566de29a9fc9a0d518a5f2540c5587f3
interpreter                                  /opt/hbd/venv/bin/python — 3.12.3
venv built by                                /usr/bin/python3 -m venv /opt/hbd/venv   (pyvenv.cfg `command =`)
```

**The venv was not built with `uv` and does not contain it.** `pyvenv.cfg` records
`home = /usr/bin`, `executable = /usr/bin/python3.12`, `command = /usr/bin/python3 -m venv
/opt/hbd/venv` — the stdlib `venv` module from the distribution interpreter — and
`/opt/hbd/venv/bin/` holds `alembic`, `arq`, `fastapi`, `pip`, `uvicorn` and `wheel` and no
`uv`; `command -v uv` finds nothing on `PATH` either `[HOST 2026-09-11]`. Anywhere below that
this document says `uv`, it means your machine.

> **Your rollback target is a filename and a hash, not a SHA.** §2's `git rev-parse HEAD`
> has no meaning here. Write down the two lines above instead — the wheel's name and its
> `direct_url.json` `sha256` — because `release/` keeps several wheels and **nothing in the
> directory records which one is installed**. `direct_url.json` inside the `dist-info` is the
> only place on the box that answers it:
>
> ```bash
> ssh aizu 'cat /opt/hbd/venv/lib/python3.12/site-packages/hbd_bot-0.1.0.dist-info/direct_url.json'
> ```

### 0.2 When the last release landed, and what has happened since

**The last release that changed the running system landed 2026-09-10 at 00:01:16 +05**
`[HOST 2026-09-11]` — the fifth and final run of `deploy-payme.sh`. Three mtimes agree:

```
2026-09-10 00:01:16.487835199 +0500   …/site-packages/hbd_bot-0.1.0.dist-info
2026-09-10 00:01:16.263832772 +0500   …/site-packages/hbd/payme
2026-09-10 00:01:15.615825751 +0500   …/site-packages/hbd/admin/static/index.html
```

and the backup that run took is `/var/backups/hbd/pre-payme-20260910-000110.sql.gz`
`[HOST 2026-09-11]`.

Four things have happened to the host since, none of them a release, and each of them changes
what a runbook can assume:

1. **The database was dropped and rebuilt** on the morning of 2026-09-10
   (`/opt/hbd/release/wipe-and-rebuild.sh`, then `resume-wipe.sh`). Already recorded —
   [`00-host-inventory.md`](00-host-inventory.md) row 47. Its consequence for *this* document
   is §4's: the re-`GRANT` it performed is why migrations can no longer be run as the owner
   role at all.
2. **Revision `0025` was staged and not applied.** `/opt/hbd/migrations/versions/` holds 25
   revision files including `20260910_1000_0025_index_settlement_clocks.py`; the database is
   at `0024` `[HOST 2026-09-11]`. See §4.
3. **The rename cutover was run and failed, taking all four services down for just under
   three minutes.** §0.4.
4. **All four units were bounced twice by `unattended-upgrades` on 2026-09-11 at 06:49:45 and
   06:50:11 +05** — `systemd[1]: Reexecuting requested from client PID 192157 ('systemctl')
   (unit apt-daily-upgrade.service)` at 06:49:35, then stop/start of all four; `hbd-bot`
   logged a fresh `host verified` at 06:50:02 `[HOST 2026-09-11]`. **So §6's restart order is
   not the only thing that restarts these processes**, and a worker killed mid-render by the
   daily apt window costs exactly what §6 says a deploy restart costs. That belongs to
   [`05-operations.md`](05-operations.md) rather than here; it is noted because an operator
   reading §6 will otherwise believe restarts are scheduled by people.

### 0.3 `deploy/` is a proposal, and four of its files have drifted

`deploy/` is **not** a record of this host and must not be read as one. That was true when the
directory was written blind, and it is more true now: the tree has been renamed `hbd` →
`bayram` and the host has not, so every path and unit name in `deploy/` now names something
that does not exist on `aizu`. What follows is each file's actual standing `[TREE 2026-09-11]`
against the host `[HOST 2026-09-11]`.

| `deploy/` file | Standing |
| --- | --- |
| `systemd/bayram-{bot,worker,admin}.service` | **Wrong for this host, and wrong in a way the cutover script states in its own header.** They say `User=bayram`, `WorkingDirectory=/srv/bayram`, `ExecStart=/srv/bayram/.venv/bin/python`. The host runs `User=hbd`, `WorkingDirectory=/var/lib/hbd`, `ExecStart=/opt/hbd/venv/bin/python`. `deploy/cutover-to-bayram.sh:16-18` says so: *"the repository's `deploy/systemd/bayram-*.service` files — which say `User=bayram`, `/srv/bayram` and `/var/lib/bayram` — are **WRONG for this host** and are not used."* |
| `systemd/bayram-payme.service` | Wrong for the host in the same way, **and it does not agree with the other three.** It alone says `WorkingDirectory=/var/lib/bayram` (`:63`) and `ExecStart=/opt/bayram/venv/bin/python` (`:65`), against `/srv/bayram` and `/srv/bayram/.venv/bin/python` in the other three. Copy all four verbatim and the gateway gets a **different data root** from the bot — precisely the failure [03-provisioning.md](03-provisioning.md) §2 calls "the load-bearing one" — and needs a second venv nothing creates. Its `InaccessiblePaths=/etc/bayram/bayram.env /etc/bayram/bayram-admin.env` (`:93`) also names two files the other three units never create; they write `/etc/bayram/bot.env` and `/etc/bayram/admin.env`. As a set, the four units do not describe one machine. |
| `deploy-payme.sh` (committed, HEAD) | **Never the script that ran.** `diff -u HEAD:deploy/deploy-payme.sh /opt/hbd/deploy-payme.sh.pre-cutover.bak` — the host's own copy of what executed — produces exactly two hunks: `WHEEL=` names `hbd_bot-0.1.0-PAYME-20260909.whl` where the host copy names `hbd_bot-0.1.0-20260909-py3-none-any.whl`, and the host copy carries a 24-line `=== 5.5/6 give the gateway its database and queue ===` stage that the committed file **does not have at all** `[HOST+TREE 2026-09-11]`. That stage is the one [`08-payme.md`](08-payme.md) §11.8 explains line by line. **The only faithful copy is on the host**, at `/opt/hbd/deploy-payme.sh.pre-cutover.bak`. |
| `deploy-payme.sh` (working tree, uncommitted) | Has the `5.5/6` stage, and has renamed everything to `bayram`, so it matches neither the host nor `HEAD`. §0.4 is why this matters today. |
| `cutover-to-bayram.sh` | Untracked, **has been run twice, and failed both times.** §0.4. |
| `caddy/*.caddy`, `payme-open-orders.py`, `first-install-proposal.md` | Another surveyor's area and already documented elsewhere; `first-install-proposal.md` is a citation target and explicitly not to be followed (`deploy/README.md`, "Why `first-install-proposal.md` is still here"). |

> **`deploy/README.md` is behind this.** It lists three unit files where four are tracked, and
> mentions neither `deploy-payme.sh`, `cutover-to-bayram.sh` nor `deploy/caddy/`
> `[TREE 2026-09-11]` — so a reader who starts there does not learn that the two scripts in
> that directory are the ones that have actually touched the production host. Its routing
> table also sends every deploy question to 03 and 04 and never mentions
> [`08-payme.md`](08-payme.md) §11, which is the only place the procedure that works is
> written down. Both are that file's to fix, not this one's.

### 0.4 WARNINGS — four things in `deploy/` or on the host that will do the wrong thing today

These are live. Each one is a command somebody could reasonably type this afternoon.

> **1. `/opt/hbd/migrations/` can no longer run a migration at all, and the error does not say
> why.** `/opt/hbd/migrations/env.py` and `alembic.ini` were both overwritten on 2026-09-10 at
> 14:06:46 with their **post-rename** versions: `env.py:57` is `from bayram.config import
> env_file, load_settings` (and `:58-59` import `bayram.db.base` and `bayram.db.models`), and
> the only variables it names are `BAYRAM_DATABASE_URL` and `BAYRAM_DB_MIGRATION_URL`. The
> live venv contains the package `hbd` and **no** package `bayram`. Run the command §4
> documents and you get, today `[HOST 2026-09-11]`:
>
> ```
> $ /opt/hbd/venv/bin/python -m alembic -c /opt/hbd/migrations/alembic.ini current
>   File "/opt/hbd/migrations/env.py", line 57, in <module>
>     from bayram.config import env_file, load_settings
> ModuleNotFoundError: No module named 'bayram'
> ```
>
> `alembic.ini:15` compounds it — `prepend_sys_path = %(here)s/../src`, i.e. `/opt/hbd/src`,
> which does not exist on a wheel host `[HOST 2026-09-11]`. **This is exactly
> [`08-payme.md`](08-payme.md) §11.3's argument arriving from the other direction**: the wheel
> does not carry `migrations/`, so `migrations/` drifted on its own and nothing noticed.
>
> Who wrote those two files is **`[UNPROVEN]`**. `deploy/cutover-to-bayram.sh:99` copies *out
> of* `/opt/hbd/migrations`, never into it, so it was not the cutover; the `0025` revision file
> beside them is dated 14:03:40, three minutes earlier, which is consistent with somebody
> staging the repository's `migrations/` directory by hand — consistent, not proven.
>
> **Do not "fix" this by reinstalling the wheel.** The wheel has no `migrations/` in it. The
> three candidate repairs are: restore the `hbd`-era `env.py` (no copy of it is on the box, so
> this means rebuilding it from the tree with the prefix put back), complete the cutover (see
> warning 3 — it cannot succeed yet), or run alembic out of `/opt/bayram/migrations` against
> `/opt/bayram/venv`, which *does* have `bayram` installed `[HOST 2026-09-11]` and is the
> cutover's half-built debris rather than a supported path. Decide which before you need a
> migration, not during one. The same breakage disarms §8's `downgrade <revision>`.

> **2. The path the `NOPASSWD` drop-in names has been repointed twice in one afternoon, and
> it does not do what its own header says.** `/etc/sudoers.d/hbd-deploy` grants
> `bash /opt/hbd/deploy-payme.sh` — so that filename is a privileged entry point. It is no
> longer the Payme deploy. As of `[HOST 2026-09-11]` it is 434 bytes whose header reads
> *"SUPERSEDED 2026-09-10 … The sudoers drop-in names THIS path, so this file is the wrapper
> that runs the cutover as root"* and whose final line is:
>
> ```bash
> exec /usr/bin/bash /opt/hbd/diagnose.sh "$@"
> ```
>
> **The header and the `exec` disagree.** It does not run the cutover; `/opt/hbd/diagnose.sh`
> (536 B, written 2026-09-10 14:29) is a read-only Postgres privilege check — four
> `sudo -u postgres psql -At` SELECTs of `has_schema_privilege('hbd','public','CREATE'/'USAGE')`,
> the `alembic_version` table owner, and the distinct table owners in `public`
> `[HOST 2026-09-11]`. That makes it harmless to run and **the single most useful thing to
> run**, because it is §4's unanswered question packaged as a one-password script. But read
> the file before you type the command: on 2026-09-10 that same path was the Payme deploy, and
> between the survey pass at ~14:25 and the verification pass the next day it was rewritten
> again. A privileged path whose contents change daily is not a runbook step.
>
> ```bash
> ssh aizu 'cat /opt/hbd/deploy-payme.sh'     # read it EVERY time, before you run it
> ```

> **3. `deploy/cutover-to-bayram.sh` has been run, it failed, and re-running it will fail in
> the same place after taking the product down again.** It was entered twice on 2026-09-10 —
> two `pre-cutover-*` dumps at 14:05:05 and 14:06:53, and its step 1 takes a dump
> (`:58-62`) `[HOST 2026-09-11]`; that there were two distinct *attempts* rather than one run
> and one resumption is a sound inference from those two dumps and not more than that,
> because the script logs nothing to the journal and the journal records only one
> `Stopping hbd-*` sequence. What **is** directly observed:
>
> - All four units were stopped at **14:05:06–07** and nothing restarted them. Caddy logged
>   `dial tcp 127.0.0.1:8080: connect: connection refused` / `status 502` to
>   `admin.bayrambot.uz` at 14:05:12, 14:06:12 and 14:07:12. An operator recovered it by hand
>   at **14:08:00–14:08:01** with four `sudo systemctl` calls. **A 2 min 54 s outage of all
>   four processes** `[HOST 2026-09-11]`.
> - It died in **step 5/9, the migrations**. Postgres logged, at
>   `2026-09-10 14:07:26.883 +05`, `hbd@hbd ERROR: no schema has been selected to create in at
>   character 15`, `STATEMENT: CREATE TABLE alembic_version (…)` `[HOST 2026-09-11]`. Step 6
>   never ran: `/etc/systemd/system/` holds `hbd-admin`, `hbd-bot`, `hbd-payme`, `hbd-worker`
>   and no `bayram-*` unit `[HOST 2026-09-11]`.
> - **Why** it died is §4's subject and is not a bug in the script: the owner role `hbd` has no
>   rights on schema `public`. **Fixing the rename therefore starts with a `GRANT`, not with
>   the script.**
>
> Three properties of the script make a re-run worse than a first run, all `[TREE 2026-09-11]`:
>
> - **It is not idempotent, and `deploy-payme.sh` has trained you to expect that it is.**
>   `:99` is `cp -a "$OLD_ROOT/migrations" "$NEW_ROOT/migrations"`, which on a second run
>   copies *into* the existing destination. `/opt/bayram/migrations/migrations/` — with its own
>   `alembic.ini`, `env.py`, `script.py.mako` and `versions/` — is on the host right now, which
>   is what that looks like `[HOST 2026-09-11]`. Compare `deploy-payme.sh`'s own advertised
>   *"It is idempotent. A rerun re-dumps, finds `alembic upgrade head` a no-op, reinstalls the
>   same wheel and restarts"* ([`08-payme.md`](08-payme.md) §11.8). Different script, opposite
>   property.
> - **Step 2 of 9 stops all four services** (`:65`), *before* the two steps that can fail
>   (the venv rebuild at `:88-96` and the migration at `:98-104`). The outage begins before
>   anything has been proven.
> - **It runs `set -uo pipefail` without `-e`** (`:28`), so only its explicit `die` calls halt
>   it. Everything else continues past a failure.
>
> Its own closing line (`:174`) is the other half of the trap and the script does nothing
> about it: `NOTE: /etc/sudoers.d/hbd-deploy still names the hbd-* units and will not cover
> bayram-*.` Confirmed from the host: every `NOPASSWD` verb names an `hbd-*` unit or an
> `/etc/hbd` path `[HOST 2026-09-11]`. **If the cutover ever succeeds, it locks the deploy
> account out of the four units it just created.**

> **4. The working-tree `deploy/deploy-payme.sh` would write its backup to a directory this
> host does not use — and that is the *second* thing wrong with it.** `[TREE 2026-09-11]`
> `:23` is `BACKUP_DIR=/var/backups/bayram` and `:38-39` are `mkdir -p "$BACKUP_DIR"` then
> `sudo -u postgres pg_dump hbd | gzip > "$BACKUP"`. `/var/backups/bayram` **does not exist on
> `aizu`**; the nine dumps that exist are in `/var/backups/hbd` `[HOST 2026-09-11]`. So the
> one artefact an incident needs would be created, silently, in a directory no inventory row,
> no runbook and no operator knows to look in — and `00-host-inventory.md` row 33, which
> enumerates the dumps, would not see it.
>
> It will not get that far today, which is luck rather than design: `:18` names
> `WHEEL=/opt/bayram/release/bayram_bot-0.1.0-20260909-py3-none-any.whl` and `:27` is
> `test -f "$WHEEL" || { … exit 1; }`, and `/opt/bayram/release/` does not exist at all
> `[HOST 2026-09-11]` — so it dies on the first preflight line, before the backup. The
> committed version dies at the same place for a different reason: the wheel it names,
> `hbd_bot-0.1.0-PAYME-20260909.whl`, is not in `/opt/hbd/release/` either — the five wheels
> there are `bayram_bot-0.1.0-py3-none-any.whl`,
> `hbd_bot-0.1.0-20260909-py3-none-any.whl` (the installed one),
> `hbd_bot-0.1.0-DASHBOARD-20260909.whl`, `hbd_bot-0.1.0-ROLLBACK-20260905.whl` and an undated
> `hbd_bot-0.1.0-py3-none-any.whl` `[HOST 2026-09-11]`.
>
> **Neither version of this script is runnable on `aizu` as it stands.** Treat a `deploy/`
> script as a draft to be read against `00-host-inventory.md` before every use, never as a
> command to paste. The preflight-before-backup ordering is the property that saved you here,
> and it is the one thing in both versions worth copying forward — [`08-payme.md`](08-payme.md)
> §11.3 and §11.4 argue it.

---

## A note on the shell variables below

§1 and §4–§8 still use the fill-in-once variables this document has always used, because they
are correct for any host. **For `aizu`, the values are known** `[HOST 2026-09-11]` and three of
the five do not exist:

```bash
# aizu / abdu-test, 2026-09-11. PRE-RENAME names, deliberately.
CHECKOUT=             # DOES NOT EXIST. No checkout, no .git, no /srv/bayram. See §0.
PY=/opt/hbd/venv/bin/python          # read off all four units' ExecStart, not assumed
BOT_ENV=/etc/hbd/hbd.env             # loaded by EnvironmentFile= in hbd-bot and hbd-worker
ADMIN_ENV=/etc/hbd/hbd-admin.env     # loaded by EnvironmentFile= in hbd-admin
# and a fourth this document predates:
PAYME_ENV=/etc/hbd/payme.env         # named by Environment=HBD_PAYME_ENV_FILE in hbd-payme
```

> **Two of those are not what this repository asks for, and the difference is a real exposure.**
> Three of the four units use **`EnvironmentFile=`**, not the `Environment=*_ENV_FILE=`
> pointer the tree argues for: `systemctl show` reports
> `EnvironmentFiles=/etc/hbd/hbd.env (ignore_errors=no)` for `hbd-bot` and `hbd-worker` with
> `Environment=` empty, and `/etc/hbd/hbd-admin.env` for `hbd-admin`. Only `hbd-payme` uses the
> pointer `[HOST 2026-09-11]`. **So on this host the bot token and all three vendor keys ARE in
> the process environment and ARE readable in `/proc/<pid>/environ`** — the exact thing
> [03-provisioning.md](03-provisioning.md) §10 argues the design avoids. Corroborated from the
> application side: `hbd-bot` logs `"env_file": ".env"` and `hbd-admin` logs
> `"env_file": ".env.admin"` — the bare pydantic defaults, i.e. neither process was ever handed
> a dotenv path at all `[HOST 2026-09-11]`. Their entire configuration comes from the
> systemd-loaded environment. `hbd-payme` is the one that does it right and is the model.

> **The `make` targets are for your machine, not for the host.** `make migrate ENV=prod`
> resolves to `BAYRAM_ENV_FILE=.env.prod` relative to the working directory (Makefile:55-60) —
> a file in the checkout. A host that sets the env file to an absolute path outside a checkout,
> which `aizu` does in four different units, wants the underlying command with the variable set
> explicitly. Every command below is written that way. On `aizu` there is no `.venv` and no
> `make`: `Makefile:25`'s `PYTHON := .venv/bin/python` does not resolve there.

---

## 1. Pre-flight: the three gates

There is no CI in this repository — no `.github` directory exists — so "the gates pass" means
a human typed three commands. README.md:305-310 says this in as many words. Run all three
from your own machine, on the commit you are about to ship, before you touch the host.

```bash
make check      # ruff, mypy --strict, pytest -m "not integration" with the 80% gate
make ui-check   # tsc --noEmit, eslint, vitest, the en/ru/uz key-parity suite
make ui-e2e     # the browser gate; needs `make ui-e2e-install` once, ~150 MB of Chromium
```

`make check` is the Python half **only** — it is `lint typecheck cov` and nothing else
(Makefile:193). It does not reach `ui-check` and it does not reach `ui-e2e`; the top of the
Makefile (Makefile:4-23) spells the split out because the omission is deliberate rather than
an oversight.

> **Every `Makefile` line number on this page moved, and has been re-derived**
> `[TREE 2026-09-11]`. The edit that added the Payme targets shifted them all: `check`
> :144→:193, `ui-e2e` :112→:161, `ui-e2e-install` :109-110→:158-159, `UI := admin-dashboard`
> :30→:33, `legacy-ui-build` :116-117→:119-120, the `ENV`/`ENV_FILES` block :40-46→:55-60,
> `PYTHON :=` :22→:25, `pytest -m "not integration"` :123→:172, the stray-`.env` argument
> :38-40→:52-54, the gates preamble :3-20→:4-23, the bot recipe :69→:83, the worker :72→:86,
> the admin :75→:89, and the `alembic upgrade head` recipe **:147→:196**. In `pyproject.toml`,
> `packages = ["src/bayram"]` is :74 (cited as :61) and `artifacts = [...]` is :84 (cited as
> :71). A line number is a claim like any other; if one of these is wrong when you read it, the
> Makefile moved again and so did the rest.

`make ui-check` runs **four** scripts in `admin-dashboard/` — the console that is actually
deployed — and each is there because that package splits its runners: `typecheck`, `lint`,
`test:unit` (Vitest, the components) and `test` (the tsx harness asserting 100% key parity and
interpolation-token consistency across `en`/`ru`/`uz`). Neither runner subsumes the other, and
until 2026-09-10 this target ran `admin-ui`'s script list instead: it ended in `tokens:check`,
which `admin-dashboard` does not declare, so it **failed on a green tree** and never reached
`test:unit` at all.

`tokens:check` now lives on `make legacy-ui-check`, with `admin-ui`'s stylesheet and the
annotator that measures it, and it is not redundant there: it verifies the `on` / `at best on`
**form** each `tokens.css` annotation must take against its token's WCAG bar, and runs the
wider `{6,8}` must-annotate scan, neither of which Vitest does. It is also what makes one
deliberate failure loud — a malformed selector takes `admin-ui/src/styles/tokenContrast.test.ts`
to *zero* tests on purpose, and `vitest run` reports a file that contributed no tests as a pass.

**`make ui-e2e` does not run at all as of 2026-09-10, and this section describes what it was
built to do.** Both e2e recipes call `npm run e2e*` in `admin-dashboard/`, which declares
neither script — the Playwright config, the specs and the CSP assertions are all in
`admin-ui/`, and the font-coverage spec asserts on that package's own font pipeline, so
re-pointing the targets would test the wrong bundle. Everything below is the gate to restore,
not a gate you can type today. Until `e2e/csp.ts` and `e2e/smoke.spec.ts` are ported into
`admin-dashboard/`, **a CSP regression reaches production unseen** — plan the release
accordingly rather than reading a passing `make check` and `make ui-check` as full cover.

**`make ui-e2e` is the one nothing forces you to run.** It sits outside `make check` because
it needs a ~150 MB Chromium download (`make ui-e2e-install`, Makefile:158-159) and a first
`make check` on a new machine must not silently start that. What it uniquely catches is a
**Content-Security-Policy regression**: jsdom implements no CSP at all, so a `<style>`
element Chrome refuses is accepted in silence by every one of the console's Vitest tests.
It is also the only gate that exercises the *built* console — `ui-e2e: ui-build`
(Makefile:161) rebuilds the bundle before running. It needs no Postgres, no Redis, no
network, no vendor key and no ffmpeg; the harness runs the real admin app over in-memory
SQLite and a dictionary Redis.

> **A green `make check` proves nothing about ffmpeg.** README.md:333 still claims one unit
> test wants ffmpeg on PATH. It does not: `test_verify_host_passes_on_a_host_with_ffmpeg` is
> marked `@pytest.mark.integration` (tests/test_runtime/test_entrypoints.py:63-66) and
> `make test` / `make cov` run `pytest -m "not integration"` (Makefile:172). The only
> evidence that the host's ffmpeg satisfies the boot probe is a bot or worker process that
> actually started — see §6.

---

## 2. Pull — **not on `aizu`**

> **This whole section is inapplicable to the production host.** There is no checkout and no
> `.git` anywhere under `/opt/hbd` `[HOST 2026-09-11]`, so `git pull --ff-only` has nothing to
> pull into and `git rev-parse HEAD` has nothing to name. **The substitute is §0.1's last
> box**: record the installed wheel's filename and its `direct_url.json` `sha256`. That pair
> is this host's rollback target, and unlike a SHA it is a file that is already on the box —
> see [`08-payme.md`](08-payme.md) §11.1 and §11.7.
>
> It is kept because it is correct for a checkout-based host, and because §8's code rollback
> still reads from it.

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

**On `aizu`, the command is a wheel install and nothing below can be typed** `[HOST 2026-09-11]`:

```bash
# the host path. Run as `developer`, which OWNS /opt/hbd — no sudo at all.
/opt/hbd/venv/bin/pip install --force-reinstall --no-deps /opt/hbd/release/<wheel>
/opt/hbd/venv/bin/pip check            # MUST be the next line. 08-payme.md §11.5 is why.
```

`--no-deps` states an assumption and `pip check` turns it into an assertion that fails the
deploy rather than a hope that fails a customer — the `pillow` incident that proves it is
[`08-payme.md`](08-payme.md) §11.5, and the reason `pip check` must stay *immediately* after
the install, in the same script, before any restart, is argued there. Do not restate it; do not
move it.

**The rest of this section is the editable-install path, and its argument is the thing the
wheel model has to pay for.** Keep reading it for that reason, not as a command:

```bash
uv pip install --python "$PY" -e "$CHECKOUT"       # developer machine only — no uv on aizu
```

The install must stay **editable** *on a checkout host*. Two things depend on it and both fail
as a 404 rather than an error:

- `migrations/` lives at the repo root and is not packaged — `pyproject.toml:74` ships only
  `src/bayram`. A wheel has no migrations in it, so the schema step below has nothing to run.
- the admin console is served from `Path(__file__).resolve().parent / "static"`
  (src/bayram/admin/app.py:128), which under `-e .` resolves into the checkout. The
  `artifacts = ["src/bayram/admin/static/**"]` force-include (pyproject.toml:84) protects a
  wheel-based deploy; it does nothing on this path. Your protection is §5.

> **`uv.lock` is not applied by this command.** The lock file is in the tree and in sync with
> `pyproject.toml`, but nothing in the repository installs from it — `uv sync` appears
> nowhere, and `uv pip install` ignores a lock. Two deploys a week apart resolve
> independently inside the `>=` / `<` ranges in pyproject.toml:13-58. If a release goes wrong
> in a way the code cannot explain, a dependency that moved underneath you is a live
> hypothesis, and `uv pip freeze --python "$PY"` before and after is how you would know.

Python is pinned to 3.12 exactly (`requires-python = ">=3.12,<3.13"`, pyproject.toml:10), so
an interpreter upgrade on the host is a build failure, not a runtime surprise. `aizu` is inside
that window: `/opt/hbd/venv/bin/python -V` is **3.12.3**, from `/usr/bin/python3.12`
`[HOST 2026-09-11]`.

> **How the wheel model pays for the two bullets above.** Neither is "solved" on `aizu`; both
> are paid for somewhere else, and knowing where is how you avoid re-introducing them.
> `migrations/` is a **separate copy** at `/opt/hbd/migrations/`, which nothing in a wheel
> install updates — so the hazard moved from "no migrations at all" to "migrations that silently
> disagree with the package", which is [`08-payme.md`](08-payme.md) §11.3 and is also warning 1
> of §0.4, currently live. The console bundle is paid for by the `artifacts` force-include: it
> ships **inside** the wheel, and `…/site-packages/hbd/admin/static/index.html` carries exactly
> one `__HBD_CSP_NONCE__` placeholder and zero `__BAYRAM_CSP_NONCE__` `[HOST 2026-09-11]`. So
> the line this section dismisses as doing "nothing on this path" is the line doing all the work
> on the deployed path. See §5.

---

## 4. Migrations

> **On `aizu` this command does not run today, and the error names the wrong problem.**
> `/opt/hbd/migrations/env.py:57` imports `bayram.config` against a venv that contains only
> `hbd`, so the documented invocation dies at import with `ModuleNotFoundError: No module named
> 'bayram'` before it opens a connection `[HOST 2026-09-11]`. **Read §0.4 warning 1 before you
> type anything in this section**, including the `downgrade` in §8, which is broken the same
> way. The host-shaped command — for when that is repaired — is:
>
> ```bash
> # on the host, as `developer`. `cd /opt/hbd` first: alembic.ini uses %(here)s-relative paths.
> HBD_ENV_FILE=/etc/hbd/hbd.env /opt/hbd/venv/bin/python \
>   -m alembic -c /opt/hbd/migrations/alembic.ini current
> ```
>
> That is the shape `resume-wipe.sh` used on 2026-09-10 when it had to finish a migration by
> hand `[HOST 2026-09-11]`. **Do not reach for `/usr/local/bin/hbd-migrate`** — it is broken and
> already documented as such: [`00-host-inventory.md`](00-host-inventory.md) row 48.

```bash
cd "$CHECKOUT"
BAYRAM_ENV_FILE="$BOT_ENV" "$PY" -m alembic -c migrations/alembic.ini current   # where you are
BAYRAM_ENV_FILE="$BOT_ENV" "$PY" -m alembic -c migrations/alembic.ini heads     # where head is
BAYRAM_ENV_FILE="$BOT_ENV" "$PY" -m alembic -c migrations/alembic.ini upgrade head
```

The `upgrade head` line is the command Makefile:196 wraps. The chain is linear —
`0001` → `0025`, no branches, every `down_revision` its immediate predecessor — so `current`
and `heads` printing the same revision is the whole of "the schema matches the code".

> **Head is `0025`; `aizu` is at `0024`.** `migrations/versions/20260910_1000_0025_index_settlement_clocks.py`
> declares `revision: str = "0025"` (`:52`) and `down_revision: str | None = "0024"` (`:53`)
> `[TREE 2026-09-11]`. The database's `alembic_version` table holds `0024`, read out of the
> world-readable `/var/backups/hbd/pre-cutover-20260910-140653.sql.gz`, and all 25 revision
> files are present at `/opt/hbd/migrations/versions/` `[HOST 2026-09-11]`. **The gap is safe
> and is not an excuse to leave it**: `0025` only adds two indexes (`payment_intents` and
> `payme_transactions` settlement clocks), so the running `0024`-era schema serves the installed
> code correctly and the indexes are a performance property, not a correctness one. Every
> instance of `0021` that used to appear in this document was stale by four revisions.
>
> **This document said `0021` at four places until 2026-09-11**, and
> [03-provisioning.md](03-provisioning.md) said it at four more. A revision number in prose
> is a fact with a shelf life; prefer `current` and `heads` to a transcribed number, and
> when you must transcribe one, date it.

**Read alembic's own output.** One WARNING there decides whether a security control exists:

```
BAYRAM_DB_MIGRATION_URL is not set, so migrations are running as the application role. That
role owns every table it creates, and an owner can GRANT back anything revoked from it — so
the audit log's REVOKE is not a control on this deployment.
```

That is migrations/env.py:89-93, emitted by `_database_url()` (env.py:117-129) when
`_owner_url()` finds nothing. `_owner_url()` (env.py:96-114) checks the process environment
**and** falls back to the dotenv file `BAYRAM_ENV_FILE` names, so `BAYRAM_DB_MIGRATION_URL` written
into `$BOT_ENV` is enough for that half.

> **The owner role is only half the two-role control, and the other half reads a different
> place.** Migration `0007` installs the `REVOKE UPDATE, DELETE, TRUNCATE ON
> public.admin_audit_log` that makes the audit log append-only for the application role. Its
> preconditions are read from `os.environ` **only**, with no dotenv fallback: the DSN gate at
> `migrations/versions/20260830_1000_0007_add_admin_audit_log.py:336`, and the role name via
> `_app_role()` at the same file:314-322, which wants `BAYRAM_DB_APP_ROLE` or a username inside
> `BAYRAM_DATABASE_URL`. Migration `0011` repeats the pattern. `BAYRAM_ADMIN_AUDIT_DSN` is
> documented as belonging in the *admin* dotenv file (.env.admin.example:130), which the
> alembic process never loads. Both misses are a `_skip()` WARNING, never a failure.
>
> If you want the REVOKE to land as a real two-role control, **four** variables have to be
> right in the migrate shell, not three. `BAYRAM_DB_MIGRATION_URL` is the one that decides
> whether the REVOKE is a control at all — without it `_database_url()` falls back to the
> application DSN (env.py:117-129), the tables' own owner issues the REVOKE against itself,
> and you get exactly the non-control the WARNING above describes. `_owner_url()` reads
> `$BOT_ENV` as well as the environment, so if that line is already in `$BOT_ENV` it is
> already covered — check before you assume, because this document cannot know:
>
> ```bash
> grep -c '^BAYRAM_DB_MIGRATION_URL=' "$BOT_ENV"    # 0 means the block below must set it too
> ```
>
> Then run the upgrade with the ones that are missing set explicitly:
>
> ```bash
> cd "$CHECKOUT"
> BAYRAM_ENV_FILE="$BOT_ENV" \
> BAYRAM_DB_MIGRATION_URL="<the owner DSN>" \
> BAYRAM_ADMIN_AUDIT_DSN="<the owner DSN>" \
> BAYRAM_DB_APP_ROLE="<the application role name>" \
> BAYRAM_DATABASE_URL="<the application DSN>" \
>   "$PY" -m alembic -c migrations/alembic.ini upgrade head
> ```
>
> `BAYRAM_DB_APP_ROLE` and `BAYRAM_DATABASE_URL` are alternatives, not both required —
> `_app_role()` (0007:314-322) takes the role name from the first and otherwise from the
> userinfo of the second. Neither `BAYRAM_DB_APP_ROLE` nor `BAYRAM_ADMIN_AUDIT_DSN` appears in
> `.env.example`, and `BAYRAM_DB_MIGRATION_URL` appears there once (.env.example:46), so none of
> them is likely to arrive by accident.
>
> **Omitting `BAYRAM_DB_MIGRATION_URL` here is worse than doing nothing**, because it is not
> visibly worse: migration `0007` still installs a `REVOKE`, and `/api/audit/verify` still
> reports `chainProtection: revoke+hmac` afterwards. You would believe you had a two-role
> control and would not have one. See the `chainProtection` note in §7.
>
> Whether this was ever done on your host is not knowable from the repository. §6 tells you
> how to ask the running system instead.

One more trap worth knowing before it bites: when `BAYRAM_DB_MIGRATION_URL` is *absent*,
`_database_url()` falls through to `load_settings()` (env.py:129), and `load_settings()`
always demands the three vendor secrets (src/bayram/config.py:689-699, :758-760). A migration
needs none of them. So a migrate shell with a DSN but no Telegram token fails with a message
about missing API keys — which is confusing, and is a signal that the owner DSN is not set.

### 4.1 On `aizu` the two-role control does not exist, and that is now why a migration as the owner role fails outright

**The audit answer is NO, and it is provable without database access.** The world-readable
`pre-cutover-20260910-140653.sql.gz` dump says, in three lines `[HOST 2026-09-11]`:

```
ALTER TABLE public.admin_audit_log OWNER TO hbd_app;     -- and 28 more; 29 CREATE TABLE public.
REVOKE USAGE ON SCHEMA public FROM PUBLIC;               -- the ONLY two ACL statements
GRANT ALL ON SCHEMA public TO hbd_app;                   -- nothing is granted to `hbd`
```

and `grep -c '^CREATE FUNCTION'` over the same dump returns **0**, so `hbd_purge_audit_log`
and `hbd_purge_audit_reasons` were never created. **Migration `0007` took its `_skip` branch.**
The application role owns every table in `public`, which is exactly the state the WARNING above
describes: there is nobody to revoke *from*. On `aizu`, `admin_audit_log`'s append-only
property is the HMAC chain alone, and `/api/audit/verify` will report `chainProtection:
"hmac-only"`. Read §7's `chainProtection` note with that in hand: the "necessary but not
sufficient" caution does not apply here, because the necessary half is absent.

**And the same fact has a second consequence this document did not foresee.** Schema `public`
is owned by `postgres`, with `GRANT ALL` to `hbd_app` and **nothing to the owner role `hbd`**.
So alembic connecting as `hbd` through `BAYRAM_DB_MIGRATION_URL` can see no `alembic_version`
and cannot create one. That is not a hypothesis — it is the recorded cause of the failed
cutover (§0.4 warning 3): Postgres logged, at `2026-09-10 14:07:26.883 +05`, `hbd@hbd ERROR: no
schema has been selected to create in` on `CREATE TABLE alembic_version (…)`
`[HOST 2026-09-11]`.

**The causal chain, because without it the missing `REVOKE` reads as a provisioning oversight
to be fixed by re-running `0007`.** It is not, and `0007` will skip again:

```
09:22  wipe-and-rebuild.sh:112-115   DROP SCHEMA public CASCADE; CREATE SCHEMA public;
                                     GRANT ALL ON SCHEMA public TO hbd_app;
                                     GRANT ALL ON SCHEMA public TO postgres;     ← and nothing to `hbd`
09:24  resume-wipe.sh:52-53          alembic upgrade head, run as the APPLICATION role
                                     → hbd_app creates and therefore OWNS all 29 tables
14:07  cutover step 5/9              alembic as `hbd` → no USAGE, no CREATE → the error above
```

`[HOST 2026-09-11]` for both script excerpts and the Postgres line; the wipe itself is
[`00-host-inventory.md`](00-host-inventory.md) row 47.

> **That `hbd` currently holds neither `USAGE` nor `CREATE` on schema `public` is
> `[UNPROVEN]`** as a direct reading, and should be written that way rather than asserted. The
> blocker: `sudo -n -u postgres psql -Atc "select has_schema_privilege(…)"` returns `sudo: a
> password is required`, and the `NOPASSWD` drop-in grants `pg_dump` and deliberately not
> `psql`. The inference is strongly supported from two directly observed ends — the
> `hbd@hbd ERROR` and the `GRANT` block above — and **one password settles it**, because
> `/opt/hbd/diagnose.sh` was written for precisely this question (§0.4 warning 2).
>
> **The repair order is `GRANT` first, script second**, and it is a prerequisite for the rename
> rather than separate hygiene. Getting the two-role control back is a second, larger question:
> it needs the owner role granted on the schema, every table's ownership moved to `hbd`, and
> `upgrade head` re-run under the owner DSN with `BAYRAM_ADMIN_AUDIT_DSN` and
> `BAYRAM_DB_APP_ROLE` exported as §4's block and [03-provisioning.md](03-provisioning.md) §7
> describe. None of that is a release step. It wants its own window and its own document.

---

## 5. Rebuild the admin console — **at build time on a wheel host, not at deploy time**

> **There is no console rebuild step on `aizu`, and adding one would undo the deploy model.**
> No `admin-dashboard/`, no `node`, no `npm`, no checkout `[HOST 2026-09-11]`. The bundle ships
> **inside the wheel** and is served straight out of `site-packages`:
> `/opt/hbd/venv/lib/python3.12/site-packages/hbd/admin/static/index.html` contains exactly one
> `__HBD_CSP_NONCE__` and zero `__BAYRAM_CSP_NONCE__`, with 22 files in `assets/` beside it
> `[HOST 2026-09-11]`. That is the `artifacts = ["src/bayram/admin/static/**"]` force-include
> (pyproject.toml:84) doing the job §3 says it does nothing for.
>
> **One genuine advantage, and it is worth naming**: on a wheel host the *stale bundle* hazard
> this section spends most of its length on **cannot occur**, because the bundle and the package
> are the same artefact and cannot be at different versions. The mismatch is impossible rather
> than unlikely.
>
> **The step that replaces it** is to assert the bundle is in the wheel *before* you copy the
> wheel to the host — which `deploy/cutover-to-bayram.sh:44-50` already does, as three
> assertions on the archive's namelist (the `bayram/` package, `admin/routers/billing.py`, and
> at least one file under `admin/static/`). The staged rename wheel passes all three
> `[HOST 2026-09-11]`. Port that check into whatever builds your next wheel; it costs nothing
> and it is the only thing standing between you and a wheel that installs cleanly and serves
> 404s to every browser URL.
>
> Read the rest of this section anyway, on a developer machine, for the `admin-dashboard` vs
> `admin-ui` trap — that one is about which bundle you *build*, and it bites before the wheel
> exists.

```bash
cd "$CHECKOUT/admin-dashboard" && npm ci && npm run build
```

**Build `admin-dashboard/`, not `admin-ui/`.** There are two consoles in this tree and they
write to the *same* output directory with `emptyOutDir: true` — admin-dashboard/vite.config.ts:20-21
and admin-ui/vite.config.ts:106-107 both name `../src/bayram/admin/static`. So the last one built
wins, completely, and building the wrong one is not a partial deploy: it replaces the panel.
`admin-ui/` is the legacy Gogo console, marked `[DEPRECATED in favor of admin-dashboard]` in its
own admin-ui/package.json:6. The Makefile already reflects this — `UI := admin-dashboard`
(Makefile:33) and `make ui-build` (Makefile:113-114) build the dashboard, while the legacy
console has been moved aside to `make legacy-ui-build` (Makefile:119-120). This section said
`admin-ui` until 2026-09-09 and was wrong; if another document in this directory still says it,
it is wrong the same way.

This step is not optional and it is not cosmetic.

`src/bayram/admin/static/` is gitignored (src/bayram/admin/app.py:124-128), so `git pull` never
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
  carries a `__BAYRAM_CSP_NONCE__` placeholder that the API replaces with this response's style
  nonce. A bundle built before that placeholder existed has nothing to replace, and
  `render_shell` serves such a shell **unchanged** and logs
  `WARNING admin.spa.nonce_placeholder_missing` (src/bayram/admin/shell.py:65-85) rather than
  returning 500 — deliberately, so an operator reaching for the panel mid-incident gets a
  working panel rather than a dead one. The cost is that the only symptoms are that one log
  line and modals that no longer lock the background: `style-src 'self' 'nonce-…'` refuses
  the scroll-lock `<style>` the bundle injects, and the page keeps scrolling behind an open
  dialog.

Nothing in either gate catches a stale *deployed* bundle. `tests/test_admin/test_spa_nonce.py`
checks the checked-in `admin-ui/index.html`, not the built one, and `make ui-e2e` rebuilds
before it runs (Makefile:161). Placeholder drift and staleness are different checks; only the
first exists.

---

## 6. Restart, in order

> **On `aizu` it is four processes, not three, and the commands are `systemctl`**
> `[HOST 2026-09-11]`. The gateway is the fourth and is the subject of
> [`08-payme.md`](08-payme.md). All four are `active`, `User=hbd`, `Group=hbd`,
> `WorkingDirectory=/var/lib/hbd`:
>
> ```bash
> # the NOPASSWD drop-in grants exactly these four verbs and no others of interest here
> sudo systemctl restart hbd-admin.service      # §6's argument for going first holds
> sudo systemctl restart hbd-bot.service
> sudo systemctl restart hbd-worker.service
> sudo systemctl restart hbd-payme.service      # gateway: enable/disable/start/stop/restart all granted
> ```
>
> ```
> hbd-bot      /opt/hbd/venv/bin/python -m hbd.main
> hbd-worker   /opt/hbd/venv/bin/python -m arq hbd.worker.WorkerSettings
> hbd-admin    /opt/hbd/venv/bin/python -m uvicorn hbd.admin.app:app --host 127.0.0.1 --port 8080
> hbd-payme    /opt/hbd/venv/bin/python -m uvicorn hbd.payme.app:app --host 127.0.0.1 --port 8091
> ```
>
> **The bind address and port question this section asks is already answered for this host**:
> `127.0.0.1:8080` is on the `hbd-admin` command line, and `ss` shows exactly one listener
> there and nothing on `0.0.0.0:8080` `[HOST 2026-09-11]`. The loopback bind is the
> compensating control for a panel with no MFA, and it lives in the unit, not in configuration
> — [`00-host-inventory.md`](00-host-inventory.md) row 8.
>
> **The data root on this host is `/var/lib/hbd/var/{workspace,archive}`, not
> `/srv/bayram/var`**, because `WorkingDirectory=/var/lib/hbd` on all four units and the root is
> `Path.cwd() / "var"`. Its size is `[UNPROVEN]`: `ls -la /var/lib/hbd` returns `Permission
> denied` (`0750 hbd:hbd`, and `developer` is not in the `hbd` group) `[HOST 2026-09-11]`.
>
> **Something other than you restarts these four.** `unattended-upgrades` bounced all four
> twice on 2026-09-11, at 06:49:45 and 06:50:11 +05 (§0.2, item 4) `[HOST 2026-09-11]`. The
> worker cost this section describes — a cancelled render, a scary message to the customer, a
> second vendor render on the retry — is therefore paid on a schedule nobody in this repository
> chose. That is [`05-operations.md`](05-operations.md)'s to own; it is here so that "restart the
> worker when the queue is quiet" is read as advice about one of several causes rather than all
> of them.

Three processes, three commands. There is no console script for any of them — `pyproject.toml`
has no `[project.scripts]` table — so whatever supervises them spells out the interpreter and
`-m`:

```bash
BAYRAM_ENV_FILE="$BOT_ENV"         "$PY" -m bayram.main                       # the bot    (Makefile:83)
BAYRAM_ENV_FILE="$BOT_ENV"         "$PY" -m arq bayram.worker.WorkerSettings  # the worker (Makefile:86)
BAYRAM_ADMIN_ENV_FILE="$ADMIN_ENV" "$PY" -m uvicorn bayram.admin.app:app \
    --host <bind address> --port <port>                                # the admin  (Makefile:89)
```

The `BAYRAM_ENV_FILE` / `BAYRAM_ADMIN_ENV_FILE` prefixes are the rule from the top of this document,
not decoration. The Makefile recipes carry them as `$(ENV_FILES)` (Makefile:55-60) and that
prefix is *empty* for the default `ENV=dev`, so these three commands stripped of it fall back
to a bare `.env` / `.env.admin` inside the checkout — the precise accident Makefile:52-54 says
the split exists to prevent ("a stray `.env` left in /srv/bayram cannot be read by accident").

**The admin bind address and port are a host fact this document does not know.** `--host` and
`--port` are uvicorn arguments, and passing them *overrides* whatever the panel is configured
for: `BAYRAM_ADMIN_HOST` and `BAYRAM_ADMIN_PORT` are real settings (src/bayram/admin/settings.py:188-189,
documented at .env.admin.example:64-65), but nothing under `src/bayram` reads them to bind — they
only surface in the config view (src/bayram/admin/schemas/config_view.py:202-203). Both default to
`127.0.0.1:8080`, and `127.0.0.1 8080` is what Makefile:89 and the tracked-but-host-blind
proposal (deploy/systemd/bayram-admin.service:30) hard-code — and what `hbd-admin.service`
actually passes `[HOST 2026-09-11]`. If your `$ADMIN_ENV` sets either variable to
something else, pasting `127.0.0.1 8080` binds the wrong socket and the TLS proxy in front of
the panel reaches nothing. Read the values out of `$ADMIN_ENV`, or off however the host
currently starts the process, before you fill the two placeholders in.

Restart **admin API → bot → worker**, and understand what each costs.

**The admin API is free to restart.** It holds no queue, no vendor client and no in-flight
customer work — its container is "engine, sessions, Redis, and nothing else"
(src/bayram/admin/container.py:1). Going first means its boot refusals fire while you are still
watching, before you have disturbed anything a customer is using. They come from two places
and this is not a closed list:

- `_refuse_disabled_panel(settings)` and `_refuse_vendor_credentials(settings)`, called back
  to back in the lifespan (src/bayram/admin/app.py:315-316) — the panel switched off, and a
  vendor credential or bot token within reach of the admin process.
- the `AdminSettings` validators, which raise earlier still, inside `_resolve_settings` on
  app.py:313. `_bounds_that_span_fields` (src/bayram/admin/settings.py:561-594) alone refuses an
  idle TTL longer than the absolute TTL, `admin_cookie_secure` false (the cookies are
  `__Host-` prefixed, so a browser would reject them outright), `BAYRAM_ADMIN_PUBLIC_ORIGIN`
  unset outside `dev`, and DEBUG logging in prod. Other field and model validators in that
  file can refuse too.

**Restarting the bot loses messages.** `run_polling` calls
`bot.delete_webhook(drop_pending_updates=True)` on every start (src/bayram/bot/app.py:216), so
every Telegram update that arrived during the restart window is discarded and never resent.
This is a known, accepted deploy-window loss; src/bayram/main.py:156-162 explains that the churn
signal is the only thing given a second source, because the worker also learns about a block
from a refused `sendAudio`.

**The worker is the expensive one, and it matters most.** A `SIGTERM` cancels running jobs —
`build_kit_worker_settings` never sets `retry_jobs`, so arq's default `True` applies and
`Worker.handle_sig` cancels running tasks (src/bayram/runtime/jobs.py:221, :585). The job's
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
which rides inside the purge transaction (src/bayram/db/purge.py:376-378) and is the *only*
backstop for a debit whose job never came back (src/bayram/db/credit_settlement.py:203-222), does
not run; and the audit chain's HEAD anchor stops being re-pinned, which means tail deletions
become undetectable while `/audit/verify` still reports `ok: true`.

---

## 7. Verify

Logs are one JSON object per line whenever `BAYRAM_IS_DEBUG` is false — that flag is the only
switch, and `BAYRAM_LOG_LEVEL` does not change the format (src/bayram/logging.py:230-243). The
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

`host verified` is src/bayram/runtime/startup.py:33-41 and carries `environment`, `env_file`,
`ffmpeg`, `locales` and `catalogue_languages`. Two of those are the whole point of the line:
`BAYRAM_ENV_FILE` makes it possible to boot a production configuration from a development
checkout, and this is the one place that says which file was actually read. Confirm
`environment` is exactly `prod` — `Settings.environment` is an unvalidated `str`
(src/bayram/config.py:170) and `is_production` compares `== "prod"` (config.py:685-686), so
`production` or `PROD` silently disarms the fake-provider refusal
(src/bayram/runtime/providers.py:104-109) and the in-process-submitter refusal
(src/bayram/runtime/submitter.py:100-105).

A `host verified` line is also your evidence about ffmpeg: `verify_host` refuses to start
without `ffmpeg`, `ffprobe` and an ffmpeg build carrying the `libopus` encoder
(src/bayram/audio/startup.py:82-108), so a bot or worker that reached this line passed that probe.

> **On `aizu` the `env_file` field is the bare default, and that is the observation rather than
> a complaint about the observation.** `hbd-bot` and `hbd-worker` log
> `{"environment": "prod", "env_file": ".env", "ffmpeg": "ffmpeg", "locales": 4,
> "catalogue_languages": 4}`, and `hbd-admin` logs `"env_file": ".env.admin"`
> `[HOST 2026-09-11]`. Those are pydantic's defaults, which means **no dotenv path was ever
> handed to these processes** — their configuration arrives entirely through `EnvironmentFile=`
> (see the note under "A note on the shell variables"). So the one thing this line was designed
> to tell you — *which file did it read* — tells you nothing on this host, and you have to read
> `systemctl show -p EnvironmentFiles` instead. `environment` is `prod` in all of them, which is
> the half that still works and the half that arms every `prod`-gated refusal.
>
> The ffmpeg half is now answered on both counts, not just the one the probe checks:
> `ffmpeg -hide_banner -encoders` lists both ` A....D libmp3lame` and ` A....D libopus` on
> `ffmpeg`/`ffprobe` 6.1.1-3ubuntu5 `[HOST 2026-09-11]`. A build with `libopus` and no mp3
> encoder passes the boot probe and ships an unmastered song to every paying customer; this host
> is not that build. [03-provisioning.md](03-provisioning.md) §1 has the argument.

> **`grep host_verified` matches nothing, ever.** `deploy/first-install-proposal.md:143` — the same
> tracked but host-blind proposal named at the top of this document — tells you to grep for
> `host_verified` with an underscore. The message is `"host verified"` with a space, and it
> is the log *message*, not an `event` field. An operator following that line sees an empty
> result and concludes the bot did not boot. Grep the quoted string.

Also read, once, near the boot lines:

```
"the checkout is wired but the credit meter is dark"
```

That is src/bayram/main.py:177-189 — a WARNING and deliberately never a refusal. It means the
paywall is wired while `BAYRAM_CREDITS_ENFORCED` is false, so a customer is shown a price,
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
  (src/bayram/admin/shell.py:65, :78-84) — it can only appear once somebody has loaded a browser
  URL. Load the panel first, then grep. See §5.
- `admin.audit.revoke_missing` is emitted only inside `resolve_chain_protection`
  (src/bayram/db/admin/audit.py:774-778), which runs only when somebody requests
  `/api/audit/verify` (src/bayram/admin/routers/audit.py:161-169) — and even then only when
  `BAYRAM_ADMIN_AUDIT_DSN` is set: with it unset the function returns `hmac-only` at
  audit.py:764-765 and logs nothing at all. In the common case its absence carries no
  information about whether the REVOKE of §4 landed. Read `chainProtection` below instead.

`admin.boot.ok` is a real `event` field (src/bayram/admin/app.py:321-333) carrying
`environment`, `env_file`, `is_cookie_secure` and `public_origin`. Check `public_origin` is
the `https://` origin a browser actually types: the CSRF check compares `Origin` **exactly**
(src/bayram/admin/csrf.py:76-88), and the boot guard only tests whether the variable was
*set*, not whether it is right (src/bayram/admin/settings.py:578-588). A wrong value gives you a
panel that logs in cleanly and then 403s every single mutation with `ORIGIN_REJECTED`.

`admin.boot.vendor_env_present` is a WARNING outside prod and a boot refusal inside it
(app.py:186-203), so a *running* prod panel already proves the four vendor variable names are
out of its reach — for `os.environ` plus the admin dotenv file it loaded, which is not the same
as "for every file on the box".

### The audit chain

Sign in to the panel as **ADMIN or OWNER** — `/api/audit` and `/api/audit/verify` are behind
`Permission.AUDIT_READ`, which is granted to those two roles only
(src/bayram/admin/security/permissions.py:374) — and read `GET /api/audit/verify`
(src/bayram/admin/routers/audit.py:62, :161-186). Three fields, in this order:

- **`chainProtection`. Read it as a one-way test, not as a verdict.** It is not read from
  configuration — `resolve_chain_protection` asks Postgres
  `has_table_privilege(current_user, 'admin_audit_log', 'UPDATE'/'DELETE'/'TRUNCATE')`
  (src/bayram/db/admin/audit.py:745-780) — so it reports a fact about the database rather than
  whether somebody set a variable. The direction it is sound in is the negative one, and that
  is all the code claims for itself (audit.py:759-762): `hmac-only` means this connection can
  still write the log, so the append-only guarantee is the HMAC chain alone.

  `revoke+hmac` means only that *this* connection currently lacks those three privileges. The
  probe (audit.py:746-751) cannot distinguish an application role that a separate owner
  revoked from — the real control — from a table owner that revoked its own default
  privileges and can `GRANT` them straight back, which is the non-control the WARNING quoted
  in §4 describes (migrations/env.py:89-93). A one-role deployment that ran `upgrade head`
  with `BAYRAM_ADMIN_AUDIT_DSN` set but `BAYRAM_DB_MIGRATION_URL` unset reports `revoke+hmac` too.
  So `revoke+hmac` is a necessary condition for the two-role control, not a sufficient one:
  pair it with evidence that the migrations ran under the owner DSN (§4).

  The gap in the other direction is real as well: it asks about the *admin process's*
  connection, so if that process connects as the table owner rather than the application role,
  this reads `hmac-only` and the panel itself can rewrite the log.

  > **On `aizu` this field will read `hmac-only`, and the "necessary but not sufficient"
  > caution above does not apply — the necessary half is simply absent.** Every table in
  > schema `public`, `admin_audit_log` included, is owned by the application role `hbd_app`;
  > there is no `REVOKE` on it in the dump and no `CREATE FUNCTION` at all `[HOST 2026-09-11]`.
  > §4.1 has the evidence and the causal chain. So the audit log's append-only property on this
  > host is the HMAC chain alone, which makes `BAYRAM_ADMIN_AUDIT_HMAC_KEY` the single control,
  > which makes the last bullet of §8 — never rotate it, back it up separately — the most
  > load-bearing sentence on this page for `aizu` specifically. Whether the panel can *reach*
  > the endpoint to report it is a separate question: `admin.boot.vendor_env_present` has never
  > appeared in the journal and `admin.boot.ok` carries
  > `is_cookie_secure: true, public_origin: https://admin.bayrambot.uz` `[HOST 2026-09-11]`, so
  > the panel is up and signing in is the only missing step.
- **`ok`.** `false` names `firstBreakSeq`. It detects three distinct things: a mutated row, a
  prefix excision and a tail excision (audit.py:593-600).
- **`isComplete`.** The walk stops at 50 000 rows in batches of 500 (audit.py:129, :132,
  :646-656). `ok: true` with `isComplete: false` is **not** a verified chain — it is a
  verified prefix. Read both fields or you are reading a badge, not a check.

### The retention row

After the first `:17` past the hour following the deploy, check the newest `purge_runs` row
via the panel's retention screen. `is_batch_full` true means a sweep hit its 500-row bound and
did not keep up (src/bayram/db/models/purge_run.py:111).

For the bytes, read the screen's **reconciliation verdict**, not a subtraction. Three columns
record the outcome — `storage_keys_returned`, `storage_keys_deleted` and
`storage_delete_failures` (purge_run.py:102-105) — and `is_storage_leaking` (purge_run.py:118-121)
compares only the first two. The API folds all three into a `StorageReconciliation`, returning
`LEAKED` when `row.is_storage_leaking` **or** `storage_delete_failures > 0`
(src/bayram/admin/schemas/retention.py:183-191), and that is what the screen renders. So `LEAKED`
is strictly broader than `returned > deleted`: a sweep whose deletes failed outright leaks bytes
while those two counters can still match. The raw numbers are on the row too, as
`keysReturned` / `keysDeleted` / `deleteFailures` plus `unreconciledKeys`
(retention.py:221-226), if you want to see which of the two produced the verdict.

Note also that `RECONCILED` is not today's normal clean answer. `KEYS_UNRECORDED` — asset rows
deleted with no key handed back — is (retention.py:101-104), and it means "unknown", not "clean".

---

## 8. Rolling back

Be precise about what a rollback returns and what it does not. Three categories.

> **On `aizu`, the code half of this is a wheel and takes about a minute; the schema half is
> deliberately not part of the procedure at all.** Reinstall the `-ROLLBACK-` artefact from
> `/opt/hbd/release/` — after renaming it to something PEP 427 accepts, because
> `hbd_bot-0.1.0-ROLLBACK-20260905.whl` has four parts and `pip` refuses it before opening the
> archive — and restart. No network, no remote, no revision resolution. That is
> [`08-payme.md`](08-payme.md) §11.7 and §11.2, and it is not restated here.
>
> **Two things about that rollback wheel deserve saying out loud.** Its filename dates it
> 2026-09-05, which puts it behind the installed wheel by five days and roughly ten revisions
> `[HOST 2026-09-11]`;
> and the emergency artefact being the one with an un-installable filename is the failure mode
> §11.2 warns about, present on the host today. Fix the name *before* the incident.
>
> **`downgrade` cannot be run on this host at all right now** — the same
> `ModuleNotFoundError` as §4, because it goes through the same `env.py` (§0.4 warning 1).

```bash
cd "$CHECKOUT"
git rev-parse --abbrev-ref HEAD    # WRITE THIS DOWN TOO — the branch you are leaving
git checkout <the SHA from §2>
uv pip install --python "$PY" -e "$CHECKOUT"
cd "$CHECKOUT/admin-dashboard" && npm ci && npm run build   # NOT optional on the way back either
# restart admin API → bot → worker, exactly as in §6 — including the BAYRAM_ENV_FILE /
# BAYRAM_ADMIN_ENV_FILE prefixes and your own bind address and port
```

The console rebuild is as mandatory on a rollback as on a deploy, for exactly the reason in
§5: the bundle is gitignored, so `git checkout` moves the source and leaves the *newer*
compiled console in place, serving the old API. That mismatch is silent.

**On `aizu` none of those four lines runs and the mismatch cannot happen.** The rollback is the
one `pip install` of the §8 opening note; the bundle travels inside the wheel, so rolling the
wheel back rolls the console back with it, in the same atom. This is the clearest single
advantage the wheel model buys, and it is worth holding onto when somebody proposes putting a
checkout back on the box.

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

In this tree every revision from `0001` to `0025` has a real `downgrade()` body — none is a
`pass` `[TREE 2026-09-11]`. That is a strong repository, not a licence. Several of those bodies
destroy data:

- **`0023` drops the three Payme tables outright** — `op.drop_table(_RPC_LOG)`,
  `op.drop_table(_TRANSACTIONS)`, `op.drop_table(_INTENTS)`
  (`migrations/versions/20260909_0900_0023_add_payme_rail_tables.py`, `downgrade`)
  `[TREE 2026-09-11]`. **Downgrading past `0023` deletes every payment intent, every Payme
  transaction and the whole RPC log**, which after a real settlement means deleting the record
  of money that moved. That settlement has happened: the rail reached its first real settlement
  on 2026-09-10 — [`09-payme-go-live.md`](09-payme-go-live.md) §4.0. This revision did not exist
  when the list below was written, and it is now the most destructive entry in it.
- `0024` drops the broadcast tables and `0022` the `chat_messages` counters, both with the
  `purge_runs` counter columns that count them; `0025` drops two indexes and loses nothing.

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
BAYRAM_ENV_FILE="$BOT_ENV" "$PY" -m alembic -c migrations/alembic.ini downgrade <revision>
```

Same DSN resolution as §4, so the owner-role question is identical: without
`BAYRAM_DB_MIGRATION_URL` you are downgrading as the application role.

> **Prefer not downgrading.** Most releases in this tree add a table or an index; the old code
> ignores what it does not know about, and leaving the schema ahead is usually cheaper than
> destroying rows to make a version number match. Downgrade when the new revision changed or
> narrowed something the old code reads — not as a reflex.

> **Never rotate `BAYRAM_ADMIN_AUDIT_HMAC_KEY` as part of a rollback.** The chain is
> `HMAC-SHA256(key, "v1" ‖ prev_hmac ‖ canonical_json(row))` and carries **no key identifier**
> (src/bayram/db/admin/audit.py:8-16). Change the key and `/audit/verify` reports a break at the
> first row, forever, indistinguishable from tampering. Lose it and the log is permanently
> unverifiable. It lives in the admin dotenv file and nowhere in the database, so a
> database-only restore comes back with an audit log nobody can check.

### Customer-visible side effects: not reversible at all

Nothing in a rollback reaches these. Enumerate them out loud before you decide the incident is
over:

- **Kits already delivered.** A song sent to Telegram is sent.
- **Messages lost to the restart.** Every update that arrived while the bot was down was
  dropped by `delete_webhook(drop_pending_updates=True)` (src/bayram/bot/app.py:216) and is not
  resent — on the way out *and* on the way back, since the rollback restarts the bot again.
- **Credit ledger movements.** `credit_accounts.balance` is a second representation of
  `SUM(credit_ledger.delta)` (src/bayram/db/credits.py:43-46); rolling code back un-writes
  neither. After any manual repair, `verify_balances` (src/bayram/db/credit_sql.py:667) is the
  one query that says whether the money state is self-consistent.
- **Rows and bytes the retention sweep deleted.** The purge is a delete, not a soft delete,
  and expiries are *stamped* at write time rather than computed (src/bayram/db/retention.py:1-19)
  — so changing a policy never un-deletes anything and never reaches rows already written.
- **Vendor spend.** Money spent at ElevenLabs and the LLM is spent, including the second
  render a cancelled job costs you (§6).
- **Audit rows.** Append-only by design. Do not "clean up" the log to make a verify go green;
  the chain is what proves you did not.

> **SUPERSEDED 2026-09-11.** This document ended, until today, with: *"Nothing in this
> repository backs anything up — `pg_dump` appears nowhere in `README.md`, the `Makefile`,
> `deploy/` or `docs/`. Whether the host has snapshots is a question this document cannot
> answer."* The first half is now false and the second is answered. Both halves are replaced
> below rather than edited, because the distinction they collapsed is the whole point.

**Something backs the database up before a migration, and nothing backs it up on a schedule.**
Split the claim; they have different owners and different failure modes.

- **Ad-hoc, and it works.** `deploy/deploy-payme.sh:39` and `deploy/cutover-to-bayram.sh:60`
  both run `sudo -u postgres pg_dump hbd | gzip > "$BACKUP"` as step 1, *before* the migration,
  and both refuse to continue on an empty dump (`test -s "$BACKUP"`) `[TREE 2026-09-11]` — a
  `pg_dump` that fails on permissions still creates a zero-byte gzip, and a backup you did not
  check is a backup you do not have. `/var/backups/hbd/` holds **nine** such dumps in three
  families: five `pre-payme-*` (2026-09-09 23:51 → 2026-09-10 00:01), two `pre-wipe-*` (09:22,
  09:24) and two `pre-cutover-*` (14:05, 14:06), 563 B to 23,532 B `[HOST 2026-09-11]`. **This
  is the pattern to keep.** `backup → migrate → install` is argued in
  [`08-payme.md`](08-payme.md) §11.4.
- **Scheduled: nothing, still.** No `hbd` or `bayram` systemd timer, `/etc/cron.d` holding only
  `e2scrub_all` and `sysstat`, and `crontab -l` → `no crontab for developer`
  `[HOST 2026-09-11]`. `systemctl list-timers` *does* show `aizu-backup.timer` and it is a trap
  — `Description=Aizu SQLite nightly backup`, for the unrelated application on this box
  ([`00-host-inventory.md`](00-host-inventory.md) row 33). ENV-6 (nightly Postgres backup with
  PITR, 30-day retention, a restore drill executed and documented) is unimplemented in the
  repository **and** on the host.
- **And nothing at all covers the other three things a restore needs** — `var/archive`, Redis,
  and `BAYRAM_ADMIN_AUDIT_HMAC_KEY`. [03-provisioning.md](03-provisioning.md) §12 enumerates
  them and is where that argument lives.

> **`00-host-inventory.md` row 33 says seven dumps; there are nine.** The two `pre-cutover-*`
> files landed after that row was written. Mentioned because it is the shape of the problem: a
> count in prose goes stale on its own, while `ls -la /var/backups/hbd/` does not.

> **One finding that is not this document's to fix but must not wait for the right document.**
> `/var/backups/hbd/` is `drwxr-xr-x root root` and every dump in it is `-rw-r--r--` — i.e.
> **world-readable** `[HOST 2026-09-11]`. Any local account on the box can read a complete
> database dump, including `credit_ledger`, the payment receipts and `admin_audit_log`; the box
> has at least two unrelated service accounts. [03-provisioning.md](03-provisioning.md) §12
> argues at length that a backup containing both the audit table and the HMAC key is a backup an
> insider can rewrite — the same reasoning applies to a dump anyone can read, and it is
> unstated. It belongs in [`07-security.md`](07-security.md). (It is also how the schema facts in
> §4.1 were obtained without database access: `zcat | grep` over schema metadata and `COPY`
> headers only, no customer rows read. That a surveyor could do that is itself the finding.)

A database-only restore still comes back with rows pointing at archive objects that are gone,
no in-flight orders, and an audit log it cannot verify without the HMAC key from the admin
dotenv file.
