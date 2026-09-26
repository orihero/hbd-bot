# The aizu host — inventory

> **STATUS, 2026-09-11 — two things changed since the 2026-09-10 pass, and both change what
> somebody would do next.**
>
> **1. An `hbd` → `bayram` cutover was attempted on this host on 2026-09-10 and failed, twice.**
> `[HOST 2026-09-11]` The host is still pre-rename — but only because the cutover aborted, not
> because nobody tried. Its SECOND attempt stopped at the migration step; its first died earlier
> and nobody has characterised where. It left debris that no
> earlier version of this file accounts for: `/etc/bayram` (a second complete copy of every
> secret), `/opt/bayram` (a built `bayram` venv), a `bayram` wheel in `/opt/hbd/release`, a
> post-rename `migrations/` tree inside `/opt/hbd`, a replaced `/opt/hbd/deploy-payme.sh`, and
> two more `pg_dump` files. Rows 49 and 50 are new and are the first thing to read.
>
> **2. Six of the ten cells this file called "behind the same permission wall" were never behind
> it.** Rows 11, 12, 13, 14, 15 and 36 are filled as of 2026-09-10/11, and not one of them needed
> a new privilege. They needed three readable things nobody had tried:
>
> | Route | Mode | Answers |
> | --- | --- | --- |
> | `/etc/postgresql/16/main/postgresql.conf` | `0644 postgres:postgres` — world-readable | row 11 |
> | `/var/log/postgresql/postgresql-16-main.log` | `0640 postgres:adm`, and `developer` is in `adm` | rows 12, 13, and `pg_hba.conf` line 125 quoted back in a `DETAIL` line |
> | `/var/backups/hbd/*.sql.gz` | `0644 root:root` | rows 14, 15 — owners, ACLs and `alembic_version` |
> | `journalctl -u hbd-worker` | no `sudo`; `developer` is in `adm` | row 36 |
>
> **Four cells remain empty: 23, 24, 30 and 35.** Three of them have a named cheap route
> (`GET /api/config` for 23 and 24; row 35 is a question a dump cannot answer). **Row 30 is the
> only genuinely blocked cell left**: `/var/lib/hbd` is `hbd:hbd` `0750`, `du` prints *Permission
> denied* and then misleadingly prints `4.0K`, and `sudo -n du` answers *a password is required*.
> **An empty cell here still means nobody has looked — but a blocker that is not real teaches
> operators to stop looking, and this one cost six rows and four of the index's open questions.**
>
> **The 2026-09-10 STATUS block is kept below, superseded where it is superseded.** Its
> "STILL EMPTY" list is the paragraph this pass replaces; the two verification lists still stand.
>
> ---
>
> **STATUS, 2026-09-10.** This file is no longer a blank form. Most of it is now read off the
> machine, and every filled cell carries the date it was verified. Read the three lists below
> before the table.
>
> **VERIFIED ON THE HOST, 2026-09-10** (by SSH, read-only, this date): the hostname; the four
> `hbd-*` units and their real `ExecStart`, `User`, `WorkingDirectory` and `EnvironmentFile`;
> every listening socket; `sudo -l` in full; the contents of `/opt/hbd` and `/opt/hbd/release`;
> the interpreter version and the shape of the install; the migration files on disk; Postgres,
> Redis, ffmpeg and journald versions and settings; the absence of Node; `/etc/caddy/Caddyfile`
> in full; the cloudflared unit, its tunnel id and the ingress it was last pushed; the host's own
> IP addressing; and — from the public internet rather than from the box — that the origin
> address answers on neither 80 nor 443, that `pay.bayrambot.uz` answers, and that
> `admin.bayrambot.uz` answers.
>
> **VERIFIED ON THE HOST, 2026-09-09** and carried forward here without being re-checked today:
> the Alembic revision (`0024`), the ten revisions applied that night, and the `308` redirect
> observed on the tunnelled Payme hostname before the Caddyfile was corrected. ~~Row 15 is the one
> that matters, and row 47 is the reason it needs re-checking rather than trusting.~~ **Row 15 was
> re-checked on 2026-09-11 and `0024` held — read out of a world-readable `pg_dump`, not out of
> `psql`.** What the re-check found instead is that `0025` is on disk, unapplied, and currently
> unappliable (rows 5, 50).
>
> **~~STILL EMPTY, AND STILL GUESSES IF YOU FILL THEM IN FROM MEMORY: rows 11–14, 23–25, 30 and
> 35–36. Every one of them is behind the same wall.~~ SUPERSEDED 2026-09-11** — six of those ten
> were answered with no new privilege, by the three readable routes named at the top of this
> block, and rows 13 and 25 by inference from evidence the same files carry. The wall itself is
> real and re-confirmed `[HOST 2026-09-11]`: `/etc/hbd` is `root:hbd` mode `0750`, `/var/lib/hbd`
> is `hbd:hbd` mode `0750`, `cat /etc/hbd/hbd.env` answers *Permission denied*, and the
> `NOPASSWD` drop-in (row 44) grants `pg_dump` but not `psql`. What was wrong was the inference
> that the wall bounded the *questions* rather than one route to them. **An empty cell here means
> nobody has looked, and that is information.** Do not read a filled row as blessing the empty
> ones — and do not read "behind a permission wall" as proof that the wall was tested.
>
> **The single biggest correction this pass makes:** row 17 used to say Caddy terminates TLS.
> It does not, for any traffic that comes from the internet. See "How public traffic actually
> reaches this host" below, and rows 39–43.

## The ten findings that outrank the table

**1. The host is not called `aizu`.** `hostname` returns `abdu-test`; `aizu` is only the
`~/.ssh/config:2-7` alias. Every `journalctl` and `systemctl` transcript you will ever be sent
says `abdu-test`, and somebody will eventually conclude it came from a different machine.

**2. The host has no public IP address at all.** `ip -4 addr` shows exactly one non-loopback
address: `100.200.100.108/24` on `ens18`, default gateway `100.200.100.1`. That is inside
`100.64.0.0/10` — carrier-grade NAT. `192.166.228.52` is not this machine's address; it is a
NAT address at the provider, and the only port forwarded through it is `722 → 22`
(`$SSH_CONNECTION` reports the server side of our own session as `100.200.100.108 22`).
**This is why 80 and 443 at the origin time out from the internet, and it is not a firewall
rule anybody here can change.** Every argument that begins "we could bypass Cloudflare by…"
ends here. Verified 2026-09-10.

**3. All public traffic arrives through a remotely-managed Cloudflare tunnel, and its
configuration is not on this host.** `cloudflared` runs as a systemd unit with
`--token-file /etc/cloudflared/token` and no local `config.yml`; the ingress lives in the
Cloudflare Zero Trust dashboard. The one local copy is a **log line** — `cloudflared` prints the
config it was pushed — which makes `journalctl` the only way to read the routing from the box.
Rows 41–42.

**4. The `http://` scheme in the Caddyfile is load-bearing, and this cost a day.** The tunnel
speaks **plain HTTP** to `127.0.0.1:80`. A site block written `pay.bayrambot.uz { … }` with no
scheme makes Caddy switch on automatic HTTPS and answer every tunnelled request with `308`,
redirecting the caller to the hostname it just came from. Payme reads any non-200 as `-32400`
and retries, so the endpoint looks alive, answers every probe, and can never take a payment.
Observed 2026-09-09; both `bayrambot.uz` blocks now carry `http://` (verified 2026-09-10, and
the `admin` one is fixed — the earlier note that it was still scheme-less is superseded).

**5. The deploy is a WHEEL, and `/srv/hbd` does not exist.** There is no git checkout on the
server, no `pip install -e`, and no Node. A wheel is built elsewhere, copied into
`/opt/hbd/release/`, and installed into `/opt/hbd/venv`. Row 45 carries the three traps that
have already bitten: PEP 427 filenames, migrations not travelling in the wheel, and
`--no-deps`.

**6. The running units load secrets with `EnvironmentFile=`, not with the `*_ENV_FILE`
indirection this repository argues for.** `hbd-bot` and `hbd-worker` both take
`EnvironmentFile=/etc/hbd/hbd.env`; `hbd-admin` takes `/etc/hbd/hbd-admin.env`. Only
`hbd-payme` uses `Environment=HBD_PAYME_ENV_FILE=/etc/hbd/payme.env`. The consequence is not
theoretical: those secrets ARE in the process environment, visible to `systemctl show` and to
anything that can read `/proc/<pid>/environ`. Rows 18–19. Verified 2026-09-10.

**7. This repository and this host do not agree on what anything is called, and the rename is
uncommitted.** The tree now ships a package `src/bayram`, a distribution `bayram-bot`, an
environment prefix `BAYRAM_` (`src/bayram/config.py:75`), unit files `deploy/systemd/bayram-*.service`,
and paths `/srv/bayram` and `/etc/bayram`. ~~**None of those exist on the host.**~~ **That
sentence was true when it was written on 2026-09-10 and is false as of 2026-09-10 14:07**: a
cutover attempt created `/etc/bayram` and `/opt/bayram` and left them behind when it aborted
(rows 46 and 49). What still does not exist is `/srv/bayram`, any `bayram-*.service`, and any
`bayram` package in the venv the running units execute. The host runs
package `hbd` from `hbd_bot-0.1.0.dist-info`, units `hbd-*`, paths `/opt/hbd`, `/var/lib/hbd`
and `/etc/hbd`, and dotenv files whose variables are `HBD_`-prefixed — re-verified
`[HOST 2026-09-11]`, **and it stays that way because the cutover failed, not because the cutover
was never run.** Row 46 states what the divergence costs on the day the rename ships; row 49
states what it has already cost. **It also already damaged this file**: a mechanical
find-and-replace across `docs/deployment/` rewrote `/opt/hbd` to `/opt/bayram`, `User=hbd` to
`User=bayram` and `/etc/hbd` to `/etc/bayram` — turning verified host facts into fiction in the
one document whose entire purpose is to hold the facts. **Host paths, unit names and `HBD_`
variables in this file are quoted from the machine. Do not sed them.**

**8. What the `developer` account can and cannot do**, because it bounds who — and what — can
act unattended. It OWNS `/opt/hbd` (`venv`, `release/`, `migrations/`), so building, installing
a wheel and running migrations need no root at all. It has full `sudo` **but only with a
password**, plus two `NOPASSWD` blocks: one pre-existing block for the unrelated `aizu` service,
and one deliberate drop-in at `/etc/sudoers.d/hbd-deploy` (row 44) enumerating exactly the
verbs the Payme deploy needs. Everything else under `/etc/hbd`, `/etc/systemd/system` and
`/etc/caddy` is out of reach of any unattended process, and `psql` is out of reach entirely.

**But the enumeration does not hold, and this finding understated the blast radius until
2026-09-11.** The drop-in's first grant is a **path**, `/usr/bin/bash /opt/hbd/deploy-payme.sh`,
and `[HOST 2026-09-11]` `/opt/hbd` is `755 developer:developer` and `deploy-payme.sh` is
`-rwxr-xr-x developer developer`. So it is not a grant to run a reviewed script; it is a grant
for `developer` to run **arbitrary code as root with no password**, by writing that code into a
file `developer` owns. That is not theoretical: the file was rewritten at `14:04:59` to wrap a
cutover script, run as root, rewritten again at `14:28:31` to wrap a different script
(`/opt/hbd/diagnose.sh`), and run as root again — six root invocations through that one path on
2026-09-10 (row 49). `sudo -l` also opens with `(ALL : ALL) ALL`: `developer` is unrestricted
root *with* a password. And `/home/developer/.sudo_askpass` exists (`-rwx------`, 37 bytes,
2026-08-07) — not read and not used here, reported because it weakens the "only with a password"
half of this finding as a statement about what can happen unattended. **Treat the `developer`
account as root-equivalent when reasoning about blast radius, and treat row 44's enumeration as a
description of intent rather than a boundary.**

**9. The migration role has no rights on schema `public`, and that is the one blocking defect on
this host.** `[HOST 2026-09-11]` `/var/log/postgresql/postgresql-16-main.log` line 414:

```
2026-09-10 14:07:26.883 +05 [163849] hbd@hbd ERROR:  no schema has been selected to create in at character 15
2026-09-10 14:07:26.883 +05 [163849] hbd@hbd STATEMENT:
	CREATE TABLE alembic_version (
		version_num VARCHAR(32) NOT NULL,
		CONSTRAINT alembic_version_pkc PRIMARY KEY (version_num)
	)
```

Alembic, connected as role `hbd`, could not create in `public` and could not even *see* the
existing `alembic_version` table through that connection. The cause is two missing words in a
readable script: `[HOST 2026-09-11]` `/opt/hbd/release/wipe-and-rebuild.sh:112-115` is
`DROP SCHEMA public CASCADE; CREATE SCHEMA public; GRANT ALL ON SCHEMA public TO ${APP_ROLE};
GRANT ALL ON SCHEMA public TO postgres;` and `APP_ROLE` is derived at line 51 from the username
in the `HBD_DATABASE_URL` the bot itself reads — which is `hbd_app` (row 13). **The 2026-09-10
rebuild re-granted the application role and the superuser, and never the migration role.** The
fix is one statement, `GRANT USAGE, CREATE ON SCHEMA public TO hbd;`, and nobody will find it
from the error text: it reads like a corrupt search_path or a missing database, it is invisible
from the application side because `hbd_app` is fine, and it stops *every* `alembic upgrade head`
that resolves to the migration DSN — revision `0025`, the rename cutover, and any release after
them. Rows 15, 25, 48 and 50.

**10. The documents' "how to find out" instinct reaches for `sudo` and `psql` and walks past
four things that are already readable.** `postgresql.conf` (world-readable), the Postgres server
log (`0640 postgres:adm`, and `developer` is in `adm`), the `pg_dump` files in `/var/backups/hbd`
(`0644 root:root`) and the worker's own journal answered six of the ten cells this file called
blocked. The STATUS block at the top carries the table. **When a row says "behind the permission
wall", check which wall was actually tested** — naming a blocker precisely is this file's best
habit, and a blocker that is not real is the most expensive thing it can publish after a wrong
value.

## Why an empty table beats a plausible one

The repository is full of settings whose *default* is safe and whose *deployed value* decides
whether a control exists at all. Four examples, each of which fails silently:

- `Settings.environment` is an unvalidated `str` with default `"dev"`
  (`src/bayram/config.py:214`) and `is_production` is an exact `== "prod"` comparison
  (`src/bayram/config.py:913-914`). A host set to `production` or `PROD` disarms the
  fake-provider refusal and the in-process-submitter refusal with no error anywhere.
  `AdminSettings.environment` is a closed `Literal` (`src/bayram/admin/settings.py:171`); the
  bot's is not. Row 20 is how you find out, and today it is answerable *without* reading a
  dotenv file — the boot lines print it.
- `admin_host` and `admin_port` (`src/bayram/admin/settings.py:190-191`) are read by nothing
  that binds a socket — their only consumers are the display fields on `GET /api/config`
  (`src/bayram/admin/schemas/config_view.py:108-109, 202-203`). The bind comes from the uvicorn
  command line (`Makefile:86`). So the panel's own config screen is *not* evidence about its
  bind address; `ss` is (row 8).
- The bot and the worker have no data-root setting at all: the root is `Path.cwd() / "var"`
  (`src/bayram/runtime/container.py:449`), while the panel reads `BAYRAM_ADMIN_DATA_ROOT`,
  defaulting to the *relative* path `var` (`src/bayram/admin/settings.py:448`). The two agree
  only if the processes share a working directory — they do, `/var/lib/hbd` for all four (row
  2) — and if they ever disagree, every media reveal in the panel 404s while the database row
  insists the file exists.
- A fourth, added 2026-09-10 because it is the live one: the **environment variable prefix
  itself** is now a deployment fact. The tree reads `BAYRAM_*`; the host's dotenv files are
  written `HBD_*`. Both are internally consistent and neither is detectably wrong from inside
  its own half. Row 46.

None of the four can be answered by reading this repository. Writing a plausible value into the
table below would therefore not be documentation; it would be an assertion that survives being
wrong.

## How public traffic actually reaches this host

This section replaces the old row 17, which said "Caddy terminates TLS" and was wrong in the
way that matters — it named the right process and the wrong position in the path.

```
   browser / Payme
        │  HTTPS
        ▼
   Cloudflare edge            ← TLS terminated HERE. Certificates, WAF, bot management,
        │                       and every error page Cloudflare might substitute.
        │  Cloudflare tunnel (QUIC, outbound-initiated from the host)
        ▼
   cloudflared on abdu-test   ← unit: cloudflared.service, token-file /etc/cloudflared/token
        │  PLAIN HTTP to a loopback port  ← the 308 trap lives on this hop
        ▼
   Caddy on 127.0.0.1:80      ← a Host-header demultiplexer, NOT a public TLS terminator
        │
        ├─ http://admin.bayrambot.uz → 127.0.0.1:8080   (hbd-admin)
        └─ http://pay.bayrambot.uz   → 127.0.0.1:8091   (hbd-payme, POST /payme only)
```

Caddy does own `*:80` and `*:443` (`ss` confirms both, 2026-09-10) and it does hold an
automatic-HTTPS configuration for `aizu.uz`. **None of that is reachable from the internet**,
because of finding 2: the box has no public address. Caddy's `:443` listener exists and has
never served a public byte. Anyone reasoning about TLS versions, cipher suites, HSTS preload or
Payme's "SSL session cache ≥ 1 MB, session timeout ≥ 10 minutes" tuning
(`08-payme.md` §4.2, item 3) is reasoning about **Cloudflare's** edge, not about this Caddyfile.

### Published application routes, as pushed to the tunnel

Read from `cloudflared`'s own journal, config `version=4`, pushed `2026-09-09T19:18:03Z`.
Verified 2026-09-10.

| # | Hostname | Service | Whose application |
| - | -------- | ------- | ----------------- |
| 1 | `aizu.uz` | `http://127.0.0.1:8765` | **A DIFFERENT application.** Not hbd. Do not restart it, do not reason about it here. |
| 2 | `www.aizu.uz` | `http://127.0.0.1:8765` | same |
| 3 | `admin.bayrambot.uz` | `http://127.0.0.1:80` | ours — through Caddy to `hbd-admin` |
| 4 | `pay.bayrambot.uz` | `http://127.0.0.1:80` | ours — through Caddy to `hbd-payme` |
| — | catch-all | `http_status:404` | |

**Where this table lives, and why that is awkward.** Nowhere on this host. It is edited in the
Cloudflare Zero Trust dashboard under *Networks → Tunnels & Mesh → `aizu-vds` → Published
application routes*, by a human with dashboard access, and it takes effect within seconds
without touching the box. There is no file to diff, no `git log`, and no config-management
trail. The **only** local record is the line `cloudflared` logs when the edge pushes a new
config, so the read-back command is:

```bash
ssh aizu 'journalctl -u cloudflared --no-pager | grep "Updated to new configuration" | tail -1'
```

Two operational consequences follow, and both have already been paid for once:

* **A DNS record created by a tunnel route is of type `Tunnel`, and is always proxied.** A
  plain `A` record with the same name blocks the route from being saved at all — the dashboard
  answers "A DNS record with this name already exists". The `A` record for `pay` was created
  first, on the mistaken grey-cloud plan recorded here on 2026-09-09, and had to be deleted
  before the route would save. **That grey-cloud plan is impossible and is superseded** (row
  37): both hostnames resolve to Cloudflare anycast today — `104.21.0.246` / `172.67.151.126`,
  verified 2026-09-10 — and no configuration can make them resolve to an origin that has no
  public address.
* **Cloudflare's proxy is therefore unavoidable for Payme**, so the `-32400` risk from
  Cloudflare's own non-200 responses — a managed challenge, a 1020 access denial, a 5xx
  interstitial, any of which is an HTML body we never see and cannot log — has to be managed
  with Cloudflare *settings*: Bot Fight Mode off for `pay.bayrambot.uz`, and a WAF skip rule for
  that hostname. **THIS IS NOT DONE.** It is the one outstanding piece of the terminator
  contract in `08-payme.md` §4 that this host cannot enforce for itself.

## The facts

| # | Fact | Value | How to find out |
| - | ---- | ----- | --------------- |
| 0 | **Whether the host answers at all, and whether anything is deployed on it** | **Yes to both.** `ssh aizu` connects (alias → `192.166.228.52:722`, user `developer`); `hbd-bot`, `hbd-worker`, `hbd-admin` and `hbd-payme` are all `active`, `NRestarts=0` on all four. **Do not trust a start timestamp read out of this row.** It has now carried three, each superseded within a day: `09:27:25 +05` on 2026-09-10 (the wipe-and-rebuild), then `14:08:00–14:08:01` (the services the cutover attempt stopped at 14:05 and that came back when it aborted), and `[HOST 2026-09-11]` **`2026-09-11 06:50:11–06:50:13 +05`**, which is the current one — the cause being an `apt-daily-upgrade` service-restart sweep at `06:49:45` that stopped and restarted all four along with `ssh`, `cron`, `postgresql@16-main` and journald. The durable facts are `active` and `NRestarts=0`; the timestamp is a thing to re-read, not a thing to quote. | `ssh -o BatchMode=yes aizu true; echo $?`, then `systemctl show hbd-bot hbd-worker hbd-admin hbd-payme -p Id -p ActiveState -p ActiveEnterTimestamp -p NRestarts`. The alias proves only that somebody wrote down a connection recipe (`~/.ssh/config:2-7`). Every other row assumes this one came back yes |
| 1 | OS, release, and the size of the box | **Ubuntu 24.04.4 LTS**, kernel `6.8.0-137-generic`. **2 vCPU, 1.9 GiB RAM** (≈831 MiB available with everything running), 38 GB root filesystem at **7.2 GB / 21%** used — the 2026-09-10 reading of 7.0 GB / 20% is superseded by a day's journal growth and the cutover debris of row 49, not by anything anybody deployed. Verified 2026-09-10, re-verified `[HOST 2026-09-11]`. **The memory is the real constraint**: four Python processes, Postgres 16, Redis, Caddy and cloudflared share 1.9 GiB, and a second worker replica (row 9) would come out of that, not out of the CPU. | `cat /etc/os-release; uname -a; free -h; nproc; df -h /` |
| 2 | Where the checkout lives (and whether it *is* a checkout) | **It is not a checkout.** `/opt/hbd` (`developer:developer`) holds `venv/`, `release/`, `migrations/` and `deploy-payme.sh`, and no `.git`. All four units run with `WorkingDirectory=/var/lib/hbd` (`hbd:hbd`, mode `750`). **`/srv/hbd` does not exist**, and neither does `/srv/bayram` — `/srv` is empty, re-verified `[HOST 2026-09-11]`. **Which makes one unit file's `Documentation=` a dangling pointer worth knowing about before you chase it: `hbd-payme.service` carries `Documentation=file:///srv/hbd/deploy/README.md`, a path that has never existed on this host** (`[HOST 2026-09-11]`). The same unit does confirm row 20's sandboxing: `InaccessiblePaths=/etc/hbd/hbd.env /etc/hbd/hbd-admin.env`, `MemoryDenyWriteExecute=yes`, `RestrictAddressFamilies=AF_INET AF_INET6 AF_UNIX`. **And since 2026-09-10 `/opt/hbd` has a sibling**: `/opt/bayram`, left by the failed cutover (row 49). Verified 2026-09-10. | `systemctl show -p WorkingDirectory hbd-bot; ls -la /opt /srv 2>/dev/null; grep -vE '^\s*#' /etc/systemd/system/hbd-payme.service` |
| 3 | Whether the install is editable or a built wheel | **A built wheel, non-editable.** `site-packages` holds `hbd/` and `hbd_bot-0.1.0.dist-info` — no `__editable__` finder, no `.pth`. Verified 2026-09-10. | `ls /opt/hbd/venv/lib/python3.12/site-packages \| grep -iE 'hbd\|editable'` |
| 4 | Python version the venv actually runs | **3.12.3**, at `/opt/hbd/venv/bin/python`. Inside the build backend's `>=3.12,<3.13`. Verified 2026-09-10. | `/opt/hbd/venv/bin/python -V` |
| 5 | Whether `migrations/` is present on the host | **Yes, and separately from the wheel** — ~~24 revision files, latest `20260909_1000_0024_add_broadcast_tables.py`~~ **25 as of 2026-09-10 14:03:40**, the new one `20260910_1000_0025_index_settlement_clocks.py` (4,619 bytes, `revision = "0025"`, `down_revision = "0024"`). `alembic.ini` is at `/opt/hbd/migrations/alembic.ini`. **The standing hazard row 45 describes is now live rather than hypothetical: `0025` is on disk and is NOT applied — the database is at `0024` (row 15) and the attempt to apply it failed at 14:07:26 (finding 9).** And this tree is now **post-rename while the venv beside it is pre-rename**: `[HOST 2026-09-11]` `/opt/hbd/migrations/env.py` (mtime 2026-09-10T14:06:46) reads `from bayram.config import env_file, load_settings` at line 57 and `MIGRATION_URL_VAR = "BAYRAM_DB_MIGRATION_URL"` at line 85, `alembic.ini` documents `BAYRAM_DATABASE_URL`, and `/opt/hbd/venv/bin/python -c 'import bayram'` answers `ModuleNotFoundError`. What rewrote it in place is `[UNPROVEN]` — the cutover script *copies* the tree rather than editing it (`cutover-to-bayram.sh:99`, checked 2026-09-11), so this was a separate staging step; the mtime is what is established, not the actor. Row 48 is the consequence. Verified 2026-09-10, re-verified `[HOST 2026-09-11]`. | `ls /opt/hbd/migrations/versions/*.py \| wc -l; grep -n '^from bayram' /opt/hbd/migrations/env.py; /opt/hbd/venv/bin/python -c 'import bayram'` |
| 6 | How the bot is supervised | **`hbd-bot.service`** (`/etc/systemd/system/hbd-bot.service`), `User=hbd`, `Group=hbd`, `WorkingDirectory=/var/lib/hbd`, `ExecStart=/opt/hbd/venv/bin/python -m hbd.main`, `EnvironmentFile=/etc/hbd/hbd.env`. Not containerised — no Docker on the box. Verified 2026-09-10. | `systemctl show hbd-bot -p FragmentPath -p ExecStart -p User -p EnvironmentFiles -p WorkingDirectory` |
| 7 | How the ARQ worker is supervised | **`hbd-worker.service`**, same user/dir/env file, `ExecStart=… -m arq hbd.worker.WorkerSettings`. Verified 2026-09-10. | as above |
| 8 | How the admin API is supervised, **and what `--host` it is given** | **`hbd-admin.service`**, `ExecStart=… -m uvicorn hbd.admin.app:app --host 127.0.0.1 --port 8080`, `EnvironmentFile=/etc/hbd/hbd-admin.env`. `ss` shows exactly one listener on `127.0.0.1:8080` and nothing on `0.0.0.0:8080`. The loopback bind is the compensating control for a panel with no MFA; it is on the command line, not in config. Verified 2026-09-10, re-verified `[HOST 2026-09-11]`. **One listener in that transcript was never accounted for, and an unexplained entry in a list offered as authoritative is what makes the next reader distrust the list: `127.0.0.1:20241` is `cloudflared`'s metrics server** (`journalctl -u cloudflared`: *"Starting metrics server on 127.0.0.1:20241/metrics"*), not ours, not a service. The full current set, `[HOST 2026-09-11]`: `127.0.0.1:5432`, `127.0.0.1:6379` + `[::1]:6379`, `127.0.0.1:2019` (Caddy admin), `127.0.0.1:8080` (ours), `127.0.0.1:8091` (ours), `127.0.0.1:8765` (the other application), `127.0.0.1:20241` (cloudflared metrics), `0.0.0.0:22` + `[::]:22`, `*:80`, `*:443`, and the two resolved stubs on `:53`. | `pgrep -af uvicorn; ss -ltn`, and for anything unrecognised `journalctl -u cloudflared \| grep -i 'metrics server'` before assuming it is ours |
| 9 | Number of worker replicas | **One.** One PID per unit; no template unit, no `@` instances. The vendor concurrency semaphores are per-process, so a second replica would double the vendor ceiling silently — and would come out of 1.9 GiB (row 1). Verified 2026-09-10. | `pgrep -cf 'arq hbd.worker'` |
| 10 | Postgres version, and where it runs | **PostgreSQL 16.15** (`16.15-0ubuntu0.24.04.1`), on this same box, `postgresql.service` active, listening on `127.0.0.1:5432` only. Not containerised, not managed. Verified 2026-09-10. | `psql -V; systemctl is-active postgresql; ss -ltn \| grep 5432` |
| 11 | `max_connections` on that server | **100.** `[HOST 2026-09-11]` `/etc/postgresql/16/main/postgresql.conf:65` reads `max_connections = 100  # (change requires restart)`, and `/etc/postgresql/16/main/conf.d/` is **empty**, so the `include_dir` at line 818 overrides nothing. **Caveat, and it is the honest limit of this answer**: this is the *configured* value. An `ALTER SYSTEM` would live in `postgresql.auto.conf` inside the `0700` data directory, which `developer` cannot read, so a `SHOW` could in principle differ. The pool arithmetic of 30 + 30 + 10 + 5 = 75 across the four processes (`08-payme.md` §3.1) therefore has the margin it assumes. | ~~`sudo -u postgres psql -Atc 'show max_connections'` — **needs a password**~~ — true, and irrelevant: **this row sat empty for a year of nobody trying `grep`.** `grep -nE '^[^#]*max_connections' /etc/postgresql/16/main/postgresql.conf; ls -A /etc/postgresql/16/main/conf.d/` — the file is `0644 postgres:postgres`, no privilege at all |
| 12 | Whether the two roles (`hbd`, `hbd_app`) exist | **Both exist.** `[HOST 2026-09-11]` the Postgres server log names them in authentication failures — `hbd@hbd` and `hbd_app@hbd` — and `log_line_prefix` at `postgresql.conf:570` is `'%m [%p] %q%u@%d '`, so every attributed line carries role and database. **Read the `DETAIL` line, not the `FATAL` line.** Over `127.0.0.1` with `scram-sha-256`, a role that does not exist produces the *same* `FATAL: password authentication failed for user "…"` as one that does — demonstrated on this host on 2026-09-10 14:45:29 with a deliberately bogus role name. The discriminator is the `DETAIL`: a missing role's `DETAIL` says `Role "…" does not exist.`; an existing role's carries only the `pg_hba.conf` line. (`role "developer" does not exist` at `FATAL` level appears only on the local/peer path, which is why it is not the general rule.) | `grep -E 'FATAL\|ERROR\|DETAIL' /var/log/postgresql/postgresql-16-main.log \| tail -40` — the log is `0640 postgres:adm` and `developer` is in `adm` (`groups` includes `4(adm)`), so this needs no `sudo`. The same file quotes `pg_hba.conf:125` back at you: `host all all 127.0.0.1/32 scram-sha-256`, which is otherwise unreadable (`0640 postgres:postgres`) |
| 13 | Which role each process connects as | **The application connects as `hbd_app`; the migration runner resolves to `hbd`. Marked as DERIVED, not read** — no dotenv file was opened. Three independent pieces: the app's own runtime errors are logged `hbd_app@hbd`; every one of the 31 objects in `public` is owned by `hbd_app` (row 14); and the cutover's Alembic, which sourced the env file with `set -a`, connected as `hbd@hbd` at 14:07:26 (finding 9). `[HOST 2026-09-11]` `wipe-and-rebuild.sh:49-51` closes it from the other side: it derives `APP_ROLE` from the username in the `HBD_DATABASE_URL` line of the bot's own dotenv, and the role it then granted is the one that owns everything. **The inference is strong and it is still an inference.** | the `HBD_DATABASE_URL` line in each dotenv file is **unreadable** (`/etc/hbd` is `root:hbd` `0750`, re-confirmed 2026-09-11) — so go round it: `grep -oE '\[[0-9]+\] [a-z_]+@[a-z_]+' /var/log/postgresql/postgresql-16-main.log \| sort \| uniq -c`. To *read* rather than derive it, the granted route is `sudo -u postgres /usr/bin/pg_dump hbd` (row 44) |
| 14 | Whether migration 0007's `REVOKE` is in force | **It is NOT in force, and there is no two-role split at the object level.** `[HOST 2026-09-11]`, from `/var/backups/hbd/pre-cutover-20260910-140653.sql.gz` (`0644 root:root`): **31** `OWNER TO hbd_app` statements — **29 `ALTER TABLE` plus 2 `ALTER SEQUENCE`**, which is the same count `03-provisioning.md` §4 reports as "all 29 tables"; the two pages count statements and tables respectively and both re-ran true on 2026-09-11 (`zcat … | grep -c 'OWNER TO hbd_app'` → 31; `grep -cE '^ALTER TABLE public\..* OWNER TO hbd_app'` → 29; `grep -c '^CREATE TABLE'` → 29) — including `ALTER TABLE public.admin_audit_log OWNER TO hbd_app;` at line 74, one `ALTER SCHEMA public OWNER TO postgres;`, **zero** `ALTER DEFAULT PRIVILEGES`, **zero** table-level `GRANT` or `REVOKE`. The only privilege statements in the whole schema are `REVOKE USAGE ON SCHEMA public FROM PUBLIC;` and `GRANT ALL ON SCHEMA public TO hbd_app;`. **The application role owns the audit table outright**, so `GET /api/audit/verify` should report `chainProtection: "hmac-only"` — a control that is not deployed, reported as not deployed. | ~~`psql -d hbd -c '\dp admin_audit_log'`~~ needs a password. Two routes that do not: `zcat /var/backups/hbd/pre-cutover-20260910-140653.sql.gz \| grep -E '^(GRANT\|REVOKE\|ALTER DEFAULT PRIVILEGES\|ALTER TABLE .* OWNER TO)'` — the dumps are world-readable (row 33); or sign in and read `GET /api/audit/verify` → `chainProtection`, because `resolve_chain_protection` (`src/bayram/db/admin/audit.py:768`) asks Postgres rather than trusting configuration and is therefore honest in both directions |
| 15 | Alembic head the database is actually at | **`0024`, re-verified 2026-09-11** — without `psql`. `[HOST 2026-09-11]` the cutover's own pre-flight dump, `/var/backups/hbd/pre-cutover-20260910-140653.sql.gz` (written 14:06:53, `0644 root:root`), carries the table verbatim: `COPY public.alembic_version (version_num) FROM stdin;` then `0024` then `\.`. The 2026-09-09 transcript figure was right and is now corroborated from the machine rather than trusted. **Two things follow, and both matter more than the number.** (a) **Revision `0025` is on disk and NOT applied** (row 5). (b) **It cannot currently be applied**: the attempt at 14:07:26 on 2026-09-10 failed with `hbd@hbd ERROR: no schema has been selected to create in`, because the migration role has no rights on schema `public` — finding 9 and row 50. **That was re-confirmed from a live session on 2026-09-11: `f|f|0024` — the role has neither `USAGE` nor `CREATE`, and the head is `0024`. See row 50.** The dump-derived figure above and the live one agree, which is the first time this number has been established two independent ways. | ~~`sudo -u postgres psql -d hbd -Atc 'select version_num from alembic_version'`~~ needs a password. **The route that works with none**: `zcat /var/backups/hbd/pre-cutover-*.sql.gz \| grep -A3 'COPY public.alembic_version'`. If you do have a terminal and a password, **the `-d hbd` is load-bearing**: without it `psql` connects to the invoking role's default database, where the answer is `relation "alembic_version" does not exist`, which reads as "no migration has ever run" |
| 16 | Redis presence, version, and **persistence** | **Redis 7.0.15**, config `/etc/redis/redis.conf`, listening `127.0.0.1:6379` and `[::1]:6379`, `dir=/var/lib/redis`. **`appendonly no`**; `save 3600 1 300 100 60 10000` — RDB snapshots only. Verified 2026-09-10. **Two consequences, both real:** an unclean stop can lose up to an hour of the ARQ queue, and the Payme pause key lives here — a Redis rebuild silently *un*-pauses the rail (`08-payme.md` §10). | `redis-cli INFO server; redis-cli CONFIG GET appendonly; redis-cli CONFIG GET save` |
| 17 | What terminates TLS, on what hostname, and whether it adds HSTS | **NOT Caddy, for anything from the internet — this row was wrong until 2026-09-10.** TLS is terminated at **Cloudflare's edge**; the tunnel then speaks **plain HTTP** to `127.0.0.1:80`, where **Caddy v2.11.4** (`/etc/caddy/Caddyfile`, admin API `127.0.0.1:2019`) demultiplexes by `Host` and reverse-proxies to `127.0.0.1:8080` (admin) or `127.0.0.1:8091` (payme, `POST /payme` only, everything else `404`). Caddy does hold `*:80` and `*:443`, and the internet can reach neither (rows 39–40). **HSTS**: `max-age=86400` on the admin block only, set by Caddy; none on the pay block; the application never sets it. Both `bayrambot.uz` blocks are written `http://…` — see finding 4. Verified 2026-09-10. | `cat /etc/caddy/Caddyfile; ss -ltn \| grep -E ':(80\|443)'`. **And then check the hop in front of it**, which is row 41, because the Caddyfile alone will mislead you exactly as it misled this row |
| 18 | Path and mode of the bot/worker dotenv file | **`/etc/hbd/hbd.env`**, loaded by **`EnvironmentFile=`** in both `hbd-bot.service` and `hbd-worker.service`. **This diverges from the repository**, which specifies `Environment=BAYRAM_ENV_FILE=/etc/bayram/bot.env` so pydantic-settings reads the file directly and the secrets never enter the process environment. As deployed they DO enter it, and are visible in `systemctl show hbd-bot` and `/proc/<pid>/environ`. ~~The file's own mode is not readable from `developer`~~ — **the mode is now known, DERIVED rather than read: `0640` owner `root:hbd`.** `[HOST 2026-09-11]` `cutover-to-bayram.sh:77-78` copies each dotenv with `chown --reference` and `chmod --reference`, and the copies it made at 14:06:54 are `-rw-r----- root hbd` in `/etc/bayram` (row 49). So the originals are `0640 root:hbd`, which is also what `08-payme.md` records for the third file. The directory itself is `root:hbd` `0750`, re-confirmed 2026-09-11. Verified 2026-09-10. | `systemctl show -p EnvironmentFiles hbd-bot`, then `sudo stat -c '%n %a %U:%G' <that path>` — which needs a password. The privilege-free route is the `--reference` copies the failed cutover left behind: `ls -la /etc/bayram` |
| 19 | Path and mode of the admin dotenv file | **`/etc/hbd/hbd-admin.env`**, **`0640 root:hbd`** (derived, as row 18), again via **`EnvironmentFile=`** rather than the repository's `Environment=BAYRAM_ADMIN_ENV_FILE=/etc/bayram/admin.env`. Same divergence, same consequence. Verified 2026-09-10. **Do not try to confirm the path from the process's own boot line** — it reports `.env.admin`, the relative default, for the reason row 20 gives. The unit file is the only honest source. | `systemctl show -p EnvironmentFiles hbd-admin` |
| 20 | `HBD_ENVIRONMENT` in **each** of the two files | **`prod` in both** — read off the boot lines rather than the files, which settles the row without any privilege at all. Bot: `"host verified"` carries `{"environment": "prod", "ffmpeg": "ffmpeg", "locales": 4, "catalogue_languages": 4}`. Admin: `admin.boot.ok` carries `{"environment": "prod", "is_cookie_secure": true}`. Verified 2026-09-10. **So every `prod`-gated refusal is armed in these two processes**, including the panel's vendor-credential refusal — which makes the running panel evidence (see the note below the table). **It does NOT generalise to the gateway.** `hbd-payme` reads a third file and its `payme.boot.ok` line says `"environment": "dev"` (verified 2026-09-10, `08-payme.md` §2.1), so the gateway's own vendor-credential refusal — an exact `== "prod"` compare — is **not** armed today. `InaccessiblePaths=` still is. Three processes, three files, three separate answers; ask each. **Re-verified `[HOST 2026-09-11]` after the 06:50 restart: both still `prod`, the gateway still `dev`.** | `journalctl -u hbd-bot -o cat \| grep -F 'host verified' \| tail -1` and `journalctl -u hbd-admin -o cat \| grep -F 'admin.boot.ok' \| tail -1` — no `sudo`, no secret. **But read only `environment` off these lines, never `env_file`.** `[HOST 2026-09-11]` the bot prints `"env_file": ".env"` and the panel `"env_file": ".env.admin"` — the *relative defaults*, because `EnvironmentFile=` means pydantic-settings never opens a file at all and reports the path it would have used. `hbd-payme`, which uses the `*_ENV_FILE` indirection, is the one process whose line names a real path (`/etc/hbd/payme.env`). Anyone who follows `README.md` open question 11's advice to "read `env_file` off the boot lines" will go looking for `/var/lib/hbd/.env`, which does not exist |
| 21 | `HBD_ADMIN_ENABLED` | **`true`.** Mechanically: the admin lifespan refuses to boot without it, and `admin.boot.ok` is logged on every restart including 2026-09-10 09:27:37. Verified 2026-09-10 by consequence, not by reading the file. | as row 20 |
| 22 | `HBD_ADMIN_PUBLIC_ORIGIN`, and whether it matches the origin browsers actually reach | **`https://admin.bayrambot.uz`**, printed in `admin.boot.ok`. **It matches**: that hostname is published route 3, and a public `GET /` returns `200`. `is_cookie_secure` is `true`, which is required — the `__Host-` cookies refuse a plaintext connection, so Cloudflare's TLS mode for this hostname must be Full (strict), not Flexible. Verified 2026-09-10. | as row 20, plus `curl -o /dev/null -w '%{http_code}' https://admin.bayrambot.uz/` |
| 23 | `HBD_ADMIN_TRUSTED_PROXY_HOPS` / `_CIDRS` | | `sudo grep -nE '^HBD_ADMIN_TRUSTED_PROXY' /etc/hbd/hbd-admin.env` — unreadable (row 13). **The correct values changed when the tunnel did, and nothing reported it**: admin traffic is now two proxies deep (Cloudflare's edge appends into `X-Forwarded-For`, then Caddy appends again), so the shipped default of `0` hops records the *proxy's* address in every audit row and every rate-limit bucket. The `hbd-payme` journal is the proof of shape: **every request the gateway has ever seen came from `127.0.0.1`** — 15 of 15 on 2026-09-10, **79 of 79** over the seven days to `[HOST 2026-09-11]`. **Quote the shape, not the count**: it has been 15, then 68, then 79 within two days, and a bare number written into a row is wrong by the next morning. **There is a read-only route past this wall and it costs one login, no `sudo` and no secret read**: `GET /api/config` projects `admin_trusted_proxy_hops` and `admin_trusted_proxy_cidrs` **verbatim** onto an allowlisted view (`src/bayram/admin/schemas/config_view.py:126,129,212,213`), which `07-security.md` §5 and `06-troubleshooting.md` already name — this row is the one place that should have pointed at them and did not. `[HOST 2026-09-11]` the route is mounted and answers `401 UNAUTHENTICATED` unauthenticated, so an OWNER session settles it. Whatever it says, check it against `hops=2`, `cidrs=127.0.0.1/32` and the reasoning in the Caddyfile comment — **and read that comment knowing it also carries a superseded routing claim (row 43)** |
| 24 | `HBD_ADMIN_PROBE_TOKEN` — set or empty | | ~~`sudo grep -c '^HBD_ADMIN_PROBE_TOKEN=.\+' /etc/hbd/hbd-admin.env`~~ — unreadable. ~~Empty means `/readyz` answers a constant `ok` to every monitor~~ **— true, and useless as a diagnostic, which is the correction this row needed. A SET token also answers a constant `ok` to every monitor that does not present the right value**: `src/bayram/admin/routers/health.py:94-100` returns `PUBLIC_STATUS` to any caller who fails the `compare_digest`. `[HOST 2026-09-11]` an unauthenticated call and one with `X-Probe-Token: bogus` both return `{"status":"ok"}` HTTP 200, and `/healthz` returns 200 with an empty body. **Empty and set are indistinguishable from outside, so probing cannot settle this row.** The route that can: `GET /api/config` returns `is_probe_token_configured` as a boolean (`config_view.py:188,230`) — an authenticated session rather than `sudo`, the same single login that settles row 23 |
| 25 | Whether `HBD_DB_MIGRATION_URL` is set anywhere the migration runner reads | **It is set, and it names role `hbd`. DERIVED, not read.** The chain: the cutover sourced the env file with `set -a` so every variable was in `os.environ`; `env.py` reads `BAYRAM_DB_MIGRATION_URL` from the environment first (`:85`, `:107`) and the dotenv file second (`:114`); the connection Alembic then opened was `hbd@hbd` (finding 9) while the application's own connections are `hbd_app@hbd` (row 13). Two different roles out of one file means the migration variable is present and distinct. **`[HOST 2026-09-11]` note the variable name on the host's migrations tree is the post-rename `BAYRAM_DB_MIGRATION_URL`, while the dotenv files are `HBD_`-prefixed — row 5's mismatch, and row 48's consequence.** | ~~`sudo grep -n '^HBD_DB_MIGRATION_URL=' /etc/hbd/hbd.env`~~ — unreadable; the derivation above is what is available. Note that the pre-cutover `deploy-payme.sh` sourced `/etc/hbd/hbd.env` with `set -a` before calling alembic, so on this host the value reaches `os.environ` from the file either way |
| 26 | ffmpeg present, and whether it has `libopus` | **`/usr/bin/ffmpeg`, with both `libopus` and `libmp3lame`.** `libopus` is the only encoder the boot probe checks (`src/bayram/audio/constants.py:113,120`; `src/bayram/audio/startup.py:43`) and `libmp3lame` is what the delivered song needs — a distro build with one and not the other passes the probe and fails every order. Both present. Verified 2026-09-10. | `ffmpeg -hide_banner -encoders \| grep -E 'libopus\|libmp3lame'` |
| 27 | ffprobe present | **`/usr/bin/ffprobe`.** Verified 2026-09-10. | `command -v ffprobe` |
| 28 | Node/npm present, and version | **NEITHER IS INSTALLED.** No `node`, no `npm` on `PATH`. Verified 2026-09-10. This is a consequence of row 45 rather than a gap: **the console bundle is built on the release machine and travels inside the wheel**, so nothing on the host ever runs `npm run build`. Any runbook step that says "rebuild the console on the host" cannot be followed here, and installing Node to make it followable would be undoing the deploy model, not fixing it. | `node -v; npm -v` |
| 29 | Whether the served console bundle exists and is current | **Present**, at `/opt/hbd/venv/lib/python3.12/site-packages/hbd/admin/static/index.html`, 636 bytes, `root:root`, mtime 2026-09-10 00:01. It contains one `__HBD_CSP_NONCE__` occurrence, **which is correct** — that is the placeholder the SPA route substitutes per response, and its *absence* is the fault the app logs as `admin.spa.nonce_placeholder_missing`. Verified 2026-09-10. **And the bundle ships its source map, which is public.** `[HOST 2026-09-11]` `https://admin.bayrambot.uz/assets/index-D9iMG-RF.js.map` returns HTTP 200, `content-length: 4242767` — 4.2 MB, larger than the bundle it maps — to any caller with no authentication, through Cloudflare and Caddy, with `cache-control: public, max-age=31536000, immutable`. Nothing in the path authenticates `/assets` (`src/bayram/admin/app.py`), and the tunnel added no filter. **This is a security finding, not an open question**: it hands anyone the panel's full pre-minification source — route names, permission checks, the shape of every API call — for a panel whose compensating control for having no MFA is that it is hard to reach (row 8). The one-year immutable header means it will sit in Cloudflare's cache and every visitor's cache long after any change. The decision may well be *accept it*; it should be a decision with a date, and `07-security.md` is where it belongs. | `grep -c __HBD_CSP_NONCE__ <that path>`; `journalctl -u hbd-admin \| grep -F 'admin.spa.nonce_placeholder_missing'` for the failure case; and from off-host `curl -sS -D- -o /dev/null https://admin.bayrambot.uz/assets/<bundle>.js.map` |
| 30 | Absolute path of the data root, and its size | Path is **`/var/lib/hbd/var`** by construction (`WorkingDirectory=/var/lib/hbd`, and the root is `Path.cwd() / "var"` — `src/bayram/runtime/container.py:449`). Size unknown, and this is **the one cell with no route at all. The exact blocker, `[HOST 2026-09-11]`:** `du -sh /var/lib/hbd` prints `du: cannot read directory '/var/lib/hbd': Permission denied` **and then prints `4.0K	/var/lib/hbd`** — which is the directory inode alone and is dangerously easy to copy into a document as the archive size. `sudo -n du -sh /var/lib/hbd` answers `sudo: a password is required`. The directory is `hbd:hbd` mode `0750` and `developer` is in neither. **Privilege needed: root, or membership of group `hbd`, or a `NOPASSWD` entry for `du`/`stat` under `/var/lib/hbd`.** `pg_dump` does not answer it — the archive is not in the database. **Upper bound from outside**: the whole root filesystem holds 7.2 GB including the OS, Postgres and the venv, so the archive is smaller than that. | `sudo du -sh /var/lib/hbd/var/archive /var/lib/hbd/var/workspace`. **If you run the unprivileged form, read the error and not the number** |
| 31 | Whether the admin's data volume is genuinely mounted read-only | **Not as a MOUNT — but the panel's view of it IS read-only, and systemd enforces it. This row said the control could not exist while it was already armed, which is the most expensive kind of error this file can make.** `[HOST 2026-09-11]` `hbd-admin.service` and `hbd-payme.service` both run `ProtectSystem=strict` **with no `ReadWritePaths=` directive at all** — the unit's `[Service]` section carries only the `Protect*`/`Restrict*` hardening, so `systemctl show -p ReadWritePaths` prints an empty value because the setting is unset, not because somebody set it empty. Under `ProtectSystem=strict` with nothing added back, the whole hierarchy including `/var/lib/hbd` is read-only to those two processes. `hbd-bot` and `hbd-worker` are the ones that carry `ReadWritePaths=/var/lib/hbd /var/log/hbd` and can write. `findmnt` is still right that there is exactly one real filesystem — `/dev/mapper/ubuntu--vg-ubuntu--lv` `ext4` `rw` at `/` — with no boundary under `/var/lib`; **it is simply not where this control lives, and reasoning only about mounts is how the row got it wrong.** The code does hand the panel a read-write `LocalFileStorage` (`src/bayram/admin/container.py:183`); the kernel refuses it anyway. ~~**No, and it cannot be without repartitioning.**~~ superseded 2026-09-11. **Stated as "systemd enforces this", on the evidence of `systemctl show` and the unit file — no write was attempted, because that would be a mutation.** | `systemctl show hbd-bot hbd-worker hbd-admin hbd-payme -p Id -p ProtectSystem -p ReadWritePaths -p StateDirectory -p BindPaths` **first**, then `findmnt -T /var/lib/hbd`. The unit is the answer; the mount table is the background |
| 32 | Where logs go and how long they are kept | **systemd-journald**, ~~80.6 MB~~ currently **96.6 MB** on disk (`[HOST 2026-09-11]`; it was 80.6 MB on 2026-09-10 and 88.6 MB that afternoon — 16 MB in a day, which is the point of the row rather than a detail). `/etc/systemd/journald.conf` sets no `Storage`, no `MaxRetentionSec` and no `SystemMaxUse`, so the distro defaults apply — persistent, capped at 10% of the filesystem (≈3.8 GB here), evicted by size and never by age. The journal still reaches back to the 2026-08-07 boot. `logrotate.timer` runs daily for Caddy's own file logs under `/var/log/caddy`. Verified 2026-09-10, re-verified `[HOST 2026-09-11]`. **Retention here is a volume budget, not a time budget**: a chatty week can silently evict the evidence of a quiet month. **Two rows of this table now rest on journal contents with no second copy anywhere, and neither of them says so: row 36 (the retention sweep has always run cleanly — 137 runs, journal only) and row 38 (every peer IP is loopback — seven days, journal only). Both pieces of evidence have an expiry date set by how chatty the box is.** Separately: **`/var/log/hbd` exists (`hbd:hbd` `0755`), is named in both the bot's and the worker's `ReadWritePaths`, and is completely empty** — nothing has ever written to it. `[UNPROVEN]` whether that is intentional (everything goes to the journal, which is what the code does) or a leftover of a provisioning step; it costs an operator ten minutes every time they go looking for log files where the unit file points. | `journalctl --disk-usage; grep -E '^[^#]*(Storage\|MaxRetentionSec\|SystemMaxUse)' /etc/systemd/journald.conf; ls -la /var/log/hbd /var/log/caddy` |
| 33 | Backup story: Postgres | **Nothing is scheduled. Every dump that exists was taken by hand.** `/var/backups/hbd` holds ~~seven~~ **nine** `pg_dump` files `[HOST 2026-09-11]` — five `pre-payme-*` from the 2026-09-09 Payme deploy, two `pre-wipe-*` from the 2026-09-10 rebuild, and **two `pre-cutover-*` written at 14:05:06 and 14:06:53 on 2026-09-10, one per failed cutover attempt** (row 49) — each written by a script a human ran. There is **no** `developer` crontab (`no crontab for developer`, re-verified 2026-09-11) and **no** hbd timer. **A use for them nobody had noticed: these dumps are `0644 root:root` and readable with no privilege whatsoever, which makes them the cheapest route on this host to schema, ACL and `alembic_version` facts that `psql` is walled off from** — rows 14 and 15 are both answered out of `pre-cutover-20260910-140653.sql.gz`. A backup that is also the only readable window into the schema is still not a backup. **`systemctl list-timers` does show `aizu-backup.timer`, and it is a trap**: `Description=Aizu SQLite nightly backup`, `User=aizu`, `ExecStart=/usr/local/bin/aizu-backup` — it belongs to the unrelated application on port 8765 and backs up none of our data. Verified 2026-09-10. **The 2026-09-09 finding stands: nothing backs this database up.** | `crontab -l; systemctl list-timers --all; systemctl cat aizu-backup.service; ls -la /var/backups/hbd` |
| 34 | Backup story: `var/archive` (delivered audio *and* every customer avatar) | **Nothing.** No timer, no cron, no copy off-box. `src/bayram/storage.py:73` and the profile writer share one root, so this is one directory holding both the deliverable and personal data. The 2026-09-10 wipe script deletes it outright as its step 5. Verified 2026-09-10. | as row 33 |
| 35 | Backup story: `HBD_ADMIN_AUDIT_HMAC_KEY` | **MOVES, DOES NOT CLOSE — and it moved in the wrong direction.** `[HOST 2026-09-11]` no readable copy exists anywhere `developer` can reach: no `*.env` under `/home/developer`, `/opt/hbd` or `/var/backups`, and no readable script in `/opt/hbd` names `HMAC_KEY`, `TELEGRAM_BOT_TOKEN` or `MERCHANT_KEY`. **But the key now exists in TWO files on the SAME disk** — `/etc/hbd/hbd-admin.env` and `/etc/bayram/bayram-admin.env` (11,213 bytes, `root:hbd` `0640`), the second left behind by the failed cutover (row 49). **That is duplication, not backup: a host rebuild loses both, and the second copy is a second place to leak from.** | Is it stored anywhere but `/etc/hbd/hbd-admin.env`? The *off-box* half is unanswerable from `developer` (row 13), and **`pg_dump` does not answer it either** — a dotenv file is not in the database, so none of the nine dumps in row 33 contains it. The chain has no key id, so losing the key makes the entire audit log unverifiable, and a host rebuild is the event that loses it. `find /home/developer /opt/hbd /var/backups -maxdepth 3 -name '*.env*'` is the cheap negative check |
| 36 | Whether the retention cron has ever run | **Yes — 137 completed sweeps, and nothing has ever been deleted from storage.** `[HOST 2026-09-11]` read out of the worker's own journal rather than out of `purge_runs`, which sidesteps the wipe caveat entirely: the journal predates the 2026-09-10 rebuild and reaches back to the 2026-08-07 boot. Earliest sweep **2026-09-05T18:17:00 +05** (which is when the units were first installed), most recent within the hour, **137 runs, every one of them `is_batch_full: false` with `storage_keys_returned: 0` and `storage_keys_deleted: 0`.** So no bytes are leaking — and the sweep has never had anything to delete, which is a different statement from "the sweep works". **Two separate events, and conflating them misreads the row**: `hbd.runtime.retention_job` logs *"retention sweep finished"* with the `storage_keys_*` fields (always zero), while `hbd.db.purge` logs *"retention purge complete"* with `admin_sessions_deleted`, and **that one has been non-zero** — 2, 2 and 3 on three separate runs, most recently 2026-09-11T07:17:01. The database half of retention demonstrably deletes rows; the storage half has never been exercised. **Caveat with a date on it: this evidence exists only in the journal (row 32), which is evicted by volume.** | ~~`psql -d hbd -c 'select ran_at, … from purge_runs order by ran_at desc limit 5'`~~ — row 11's wall, **and** the answer would mislead: the table was dropped and recreated on 2026-09-10 (row 47), so an empty result says nothing about the weeks before it. The journal has no such problem: `journalctl -u hbd-worker --no-pager -o cat \| grep -oE '"storage_keys_deleted": [0-9]+' \| sort \| uniq -c`, and `\| grep 'retention purge complete'` for the other event |
| 37 | **The hostname Payme calls, and whether it is a DEDICATED name** | **`pay.bayrambot.uz`** — a dedicated name, not the panel's, published route 4. **The 2026-09-09 grey-cloud plan recorded here is superseded and impossible**: a tunnel route creates a `Tunnel`-type DNS record which is *always* proxied, and the origin has no public address to point a grey-cloud `A` record at anyway (finding 2). The name resolves to Cloudflare anycast. **Reachable and correct from the public internet, verified 2026-09-10**: `POST https://pay.bayrambot.uz/payme` with no auth → HTTP **200** with `{"error":{"code":-32504}}`; `GET https://pay.bayrambot.uz/` → **404** (both re-verified `[HOST 2026-09-11]`, and both hostnames still resolve to `104.21.0.246` / `172.67.151.126`). ~~**NOT YET REGISTERED in the Payme cabinet.**~~ **REGISTERED 2026-09-10** as Endpoint URL `https://pay.bayrambot.uz/payme`, with the `order_id` requisite. **The evidence is a document, not this host, and the distinction is the point of this row**: `09-payme-go-live.md` §3 records Gate B item 4 *"Endpoint registered in the cabinet"* and item 5 *"the «Настройка Аккаунт» field name"* both **CLOSED 2026-09-10**. The gateway's `payme.boot.ok` line does carry a real sandbox cashbox (`merchant_id 6aa24fd9ee30563de3a1ac22`, `is_sandbox: true`, `account_field: order_id`, `merchant_key_length: 36`, re-read `[HOST 2026-09-11]`) — **but that is what is in `/etc/hbd/payme.env`, and a cashbox can be provisioned without its Endpoint URL ever being typed into the cabinet. The boot line is not evidence for this row and must not be quoted as if it were.** | Nothing in this repository can answer this. It is registered by a human in the Payme cabinet (Кассы → the kassa → Настройки → Инструменты разработчика) as the Endpoint URL `https://<hostname>/payme`. It must NOT be the admin panel's name: the panel has to be the only reachable name at its origin, because both its cookies are `__Host-` prefixed and un-narrowable and its CSRF check compares the public origin exactly |
| 38 | **The caller-IP allowlist actually configured at the terminator** | **NONE — deliberately, and now doubly moot.** Two reasons, and the second is new. (a) `185.234.113.0/28` is Payme's PRODUCTION range; their sandbox may originate elsewhere, and a filter that refuses every certification call is indistinguishable from a broken endpoint. (b) **Since the tunnel, there is no source address left to filter on at the origin**: every request arrives from `cloudflared` via Caddy, and the gateway logs `"peer_ip": "127.0.0.1"` for all of them — ~~15 of 15, verified 2026-09-10~~ **79 of 79 over the seven days to 2026-09-11, one bucket, no exceptions (`[HOST 2026-09-11]`)**. The count has been 15, then 68, then 79 within two days, largely from certification traffic; **the shape is the durable finding and the only part worth writing in a row.** The commented matcher in the Caddyfile would match loopback, i.e. everything or nothing. **The control has moved to Cloudflare** and has not been built there. | The gateway logs every peer IP unconditionally, so the *shape* is observable even though the value is now useless: `journalctl -u hbd-payme --since '7 days ago' -o cat \| grep -o '"peer_ip": *"[^"]*"' \| sort \| uniq -c`. To recover the real caller address the terminator must forward it (`CF-Connecting-IP` → `X-Forwarded-For`) **and** `payme_trusted_proxy_hops` must be raised, because at zero hops the app believes the proxy — and a filter matching the wrong address is worse than no filter |
| 39 | **The host's own network position** | **No public IP.** One non-loopback address: `100.200.100.108/24` on `ens18`, default gateway `100.200.100.1` — inside CGNAT space `100.64.0.0/10`. `192.166.228.52` is a provider NAT address, not this machine's. The only forwarded port is `722 → 22`; our own session reports its server side as `100.200.100.108 22`. Verified 2026-09-10. | `ip -4 -o addr show; ip route show default; echo $SSH_CONNECTION` |
| 40 | **Whether the origin is reachable from the internet on 80/443** | **NO.** From an off-host network on 2026-09-10, `https://192.166.228.52/` and `http://192.166.228.52/` both **time out** — no RST, no certificate, nothing. This is a consequence of row 39, not of a firewall rule on the box, and it cannot be undone locally. Caddy's `*:80` and `*:443` listeners exist and are reachable only from the tunnel and from loopback. Verified 2026-09-10. | From a machine that is not the host: `curl -m 8 -o /dev/null -w '%{http_code}\n' https://192.166.228.52/` |
| 41 | **The Cloudflare tunnel** | Unit `cloudflared.service` (`/etc/systemd/system/cloudflared.service`), `ExecStart=/usr/bin/cloudflared --no-autoupdate tunnel run --token-file /etc/cloudflared/token`, cloudflared **2026.7.3**. Tunnel name **`aizu-vds`**, id **`8b799983-8694-479b-98b3-09aaed9b3f8d`**, connector hostname `abdu-test`, QUIC to Cloudflare's `waw02`/`arn04` edges. Token at `/etc/cloudflared/token`, `root:root` `0600`. **There is no local `config.yml`** — the ingress is pushed from the dashboard (row 42). Verified 2026-09-10. | `systemctl show cloudflared -p ExecStart; journalctl -u cloudflared \| grep -E 'tunnelID\|Connector ID'; stat -c '%n %a %U:%G' /etc/cloudflared/token` |
| 42 | **The published application routes** | Four hostnames plus a `404` catch-all — see the routes table above. Config `version=4`, pushed `2026-09-09T19:18:03Z`. **Edited in the Cloudflare Zero Trust dashboard, not on this host**; the only local copy is a cloudflared log line. Verified 2026-09-10. | `journalctl -u cloudflared --no-pager \| grep 'Updated to new configuration' \| tail -1` |
| 43 | **What Caddy is actually for, now** | An internal `Host`-header demultiplexer on `127.0.0.1:80`, behind the tunnel. Four site blocks: `aizu.uz`/`www.aizu.uz` → `:8765` (**not ours**), a temporary cleartext `http://192.166.228.52` block that is now unreachable and can go, `http://admin.bayrambot.uz` → `:8080`, `http://pay.bayrambot.uz` → `:8091` with `POST /payme` proxied and everything else `respond 404`. **The `http://` prefix on the two `bayrambot.uz` blocks is required** (finding 4). Caddy v2.11.4, admin API on `127.0.0.1:2019`. The pay block logs to `output stderr` on purpose: `caddy validate` run under `sudo` creates `/var/log/caddy/payme.log` owned by `root:root`, after which the `caddy` user cannot open it and `systemctl reload caddy` fails with "permission denied" about a file the config only mentions. **That artefact is still sitting on the disk, armed**: `[HOST 2026-09-11]` `/var/log/caddy/payme.log` exists, 0 bytes, `-rw------- root:root`, dated Sep 10 00:02, beside `admin.log` (`caddy:caddy`, 3.16 MB and growing) and a 0-byte `aizu.log`. Verified 2026-09-10, re-verified `[HOST 2026-09-11]`. **Two claims inside the Caddyfile itself are wrong, and row 23 sends readers there to read the third one.** `[HOST 2026-09-11]` line 59 names the admin dotenv as `/etc/hbd/admin.env` — **the real file is `/etc/hbd/hbd-admin.env`** (row 19) — and the 2026-09-09 comment at line 65 still asserts *"pay.bayrambot.uz answers as 192.166.228.52, the origin itself"*, which finding 2 and today's DNS superseded. What it gets right is the part row 23 needs: `HBD_ADMIN_TRUSTED_PROXY_HOPS=2` / `_CIDRS=127.0.0.1/32` with the reasoning, at lines 69-70. The file is `0644 root:root` and needs no `sudo` to read. | `cat /etc/caddy/Caddyfile; caddy version; ls -la /var/log/caddy` |
| 44 | **The `NOPASSWD` sudo drop-in, and exactly what it grants** | `/etc/sudoers.d/hbd-deploy`, for user `developer`. Read from `sudo -l` on 2026-09-10, in full: `bash /opt/hbd/deploy-payme.sh`; `systemctl daemon-reload`; `enable\|disable\|start\|stop\|restart\|status\|is-active hbd-payme.service`; `restart` of `hbd-bot.service`, `hbd-worker.service`, `hbd-admin.service`; `reload\|restart caddy.service`; `journalctl -u hbd-payme *`; `tee /etc/hbd/payme.env` and `tee /etc/caddy/Caddyfile`; `caddy validate --config /etc/caddy/Caddyfile --adapter caddyfile`; and `pg_dump hbd` as `postgres`. **What it deliberately does NOT grant**: `psql` (which is why rows 11–15 and 36 were *thought* to be shut — six of them were not, see finding 10), any read of `/etc/hbd/hbd.env` or `/etc/hbd/hbd-admin.env` (rows 13, 23–25, 35), **`sudo -u hbd` — so the harness command under "What is deployed and verified" below cannot be run unattended; `sudo -n -u hbd true` answers `sudo: a password is required` (`[HOST 2026-09-11]`)** — `stop` of the bot/worker/admin (only `restart`), and any editing of a unit file. `tee` rather than an editor because it is a single non-interactive write with a known target. **`pg_dump` is the one granted route to schema, ACL and `alembic_version` facts**, and it is worth naming as such rather than only as a backup verb: `sudo -n -u postgres /usr/bin/pg_dump hbd` would answer rows 12, 14, 15 and 36 directly. It was **not exercised for this pass** — the attempt was refused by local tooling before it reached the machine, which is a workstation blocker and not the host's permission wall, and the same answers were obtained by reading the dumps the cutover had already written (row 33). A human at a terminal can run the `pg_dump` form. **A separate, pre-existing `NOPASSWD` block covers the unrelated `aizu` service and is nothing to do with us.** Revoke with `sudo rm /etc/sudoers.d/hbd-deploy`. **And read the first line of `sudo -l` before reasoning about any of this: it is `(ALL : ALL) ALL`. The enumeration below it bounds what happens without a password; it does not bound `developer`. Finding 8 carries the escalation — the `deploy-payme.sh` grant is a grant to run arbitrary developer-written code as root, and it was used that way six times on 2026-09-10.** | `sudo -n -l` |
| 45 | **The wheel-based deploy layout, and its three traps** | `/opt/hbd/release/` holds the wheels and the one-shot scripts; `/opt/hbd/venv` is the target; `/opt/hbd/migrations` is Alembic; a `-ROLLBACK-` wheel is kept beside the current one. Present ~~2026-09-10, four of them~~ **`[HOST 2026-09-11]`, FIVE of them**: `hbd_bot-0.1.0-20260909-py3-none-any.whl` (live), `hbd_bot-0.1.0-DASHBOARD-20260909.whl`, `hbd_bot-0.1.0-ROLLBACK-20260905.whl`, an undated `hbd_bot-0.1.0-py3-none-any.whl` from 2026-09-06, and **`bayram_bot-0.1.0-py3-none-any.whl` (5,219,850 bytes, staged 2026-09-10 14:03:13) — the first `bayram`-named artefact ever put on this host, the one the cutover installs, and NOT what the running units execute** (row 49). **Nothing in the directory says which one is installed** — the filename is not recorded anywhere the venv can be asked, so identifying the running wheel means matching sizes or trusting the deploy transcript. Two of the four (`DASHBOARD`, `ROLLBACK`) are the illegal shape below and are inert artefacts. **Trap 1 — filenames must be PEP 427 valid.** `hbd_bot-0.1.0-PAYME-20260909.whl` was refused outright by pip: *"Invalid wheel filename (wrong number of parts)"*. A build tag is the legal way to date one: `hbd_bot-0.1.0-20260909-py3-none-any.whl`. Note that the `ROLLBACK` and `DASHBOARD` names above are the illegal shape and are kept only as inert artefacts. **Trap 2 — a wheel carries no migrations.** `pyproject.toml` packages `src/bayram` only. Revision files must be copied to `/opt/hbd/migrations/versions/` *separately*, or `alembic upgrade head` stops at whatever is on disk and **reports success**. `deploy-payme.sh` counts the expected files in its preflight for exactly this reason. **Trap 3 — `pip install --no-deps` skips a new dependency.** `pillow` was new in the 2026-09-09 release and `--no-deps` left it missing; `pip check` caught it before any service restarted. Run `pip check` between install and restart, always. Verified 2026-09-10. | `ls -la /opt/hbd/release; head -40 /opt/hbd/deploy-payme.sh` |
| 46 | **The repository/host naming divergence** | **The tree has been renamed `hbd` → `bayram` and the host has not.** Tree (uncommitted, 2026-09-10): package `src/bayram`, distribution `bayram-bot` (`pyproject.toml:6,69`), env prefix `BAYRAM_` (`src/bayram/config.py:75`), units `deploy/systemd/bayram-{bot,worker,admin,payme}.service`, paths `/srv/bayram` and `/etc/bayram`. Host: package `hbd`, distribution `hbd_bot`, units `hbd-*`, paths `/opt/hbd`, `/var/lib/hbd`, `/etc/hbd`, and dotenv files whose variables are `HBD_`-prefixed. **The cost is a breaking deploy, not a cosmetic one**: the moment a `bayram-*` wheel is installed, the running services read `BAYRAM_*` and the files on disk say `HBD_*`, so *every* setting reverts to its default at once — `environment` back to `dev` (disarming every prod refusal, row 20), `admin_enabled` back to `false`, `redis_url` back to `redis://localhost:6379/0`, and the four required vendor variables missing. The rename therefore has to land as one change: new wheel, rewritten `/etc/hbd/*.env` (or new `/etc/bayram/*.env`), rewritten unit files, `daemon-reload`. Verified 2026-09-10. **And it has been tried: on 2026-09-10 at 14:05 and again at 14:06, in exactly that order, and it failed both times — the second at the migration step, the first before step 3 and uncharacterised — row 49.** So this row's closing inventory needs one correction: `[HOST 2026-09-11]` **`/etc/bayram` and `/opt/bayram` DO now exist** as debris from that attempt. What still does not exist: `/srv/bayram`, any `bayram-*.service` unit (`/etc/systemd/system` holds only the four `hbd-*.service` files), and any `bayram` package in `/opt/hbd/venv` — which still holds only `hbd` and `hbd_bot-0.1.0.dist-info`, with all four units `enabled enabled` and active. **The running system is unchanged. The disk is not.** **Do not "fix" the `hbd` spellings in this file** — they are the host's, and a blind rename has already corrupted them here once. | `ls /opt/hbd/venv/lib/python3.12/site-packages \| grep -i hbd` against `grep -n 'ENV_PREFIX' src/bayram/config.py` |
| 47 | **What this host actually is, and what happened to its data on 2026-09-10** | `abdu-test` is a **test box**, and it was **wiped and rebuilt on the morning of 2026-09-10**. `/opt/hbd/release/wipe-and-rebuild.sh` (`pg_dump`, stop all four, `DROP SCHEMA public CASCADE`, recreate, re-`GRANT`, migrate, delete the media archive, flush Redis, restart) records in its own header that *"the operator confirmed on 2026-09-10 [that it holds] no real customers and no real payments"*. Two `pre-wipe-*` dumps at 09:22 and 09:24 are its backups — the second is 563 bytes, i.e. taken after the schema was already empty. ~~All four services came back at 09:27:25 and have logged no `ERROR` since.~~ **Superseded twice: by the cutover's stop at 14:05 and restart at 14:08 on 2026-09-10, and by the `apt-daily-upgrade` restart sweep at 06:49:45 on 2026-09-11 (row 0).** The "no `ERROR` since" half also needs re-scoping, because it reads as more reassuring than it is: there are still no `ERROR`-level entries on `hbd-bot`, `hbd-worker` or `hbd-admin` (`[HOST 2026-09-11]`), **but the Postgres server log — which the units' journals do not carry — records one at 14:07:26 from the cutover's migration step** (finding 9). A clean `journalctl -p err` across our four units is not a clean box. **And this row's other silent legacy is the rebuild's missing GRANT**: `wipe-and-rebuild.sh` re-granted schema `public` to the application role and to `postgres`, never to the migration role, which is why migrations have been impossible since that morning without anybody noticing (row 50). **The operator's confirmation is quoted from the script, not independently established here.** Verified 2026-09-10. | `ls -la /var/backups/hbd; head -30 /opt/hbd/release/wipe-and-rebuild.sh; journalctl -u hbd-bot --since today -p err`, **and then** `grep -E 'FATAL\|ERROR' /var/log/postgresql/postgresql-16-main.log \| tail -20`, because the two are different evidence |
| 48 | **Both documented ways to run a migration on this host are now dead ends** | `/usr/local/bin/hbd-migrate` passes its Alembic command as **one argument**, so Alembic sees the literal string `"upgrade head"` where it expects the sub-command `upgrade` followed by `head`, and prints its usage instead of migrating — a quoting bug in the wrapper. It failed the 2026-09-10 rebuild at the migration step and `resume-wipe.sh` was written to call Alembic directly instead. The script itself is not readable from `developer` (`Permission denied`), so the exact line has not been seen. ~~**Do not use this wrapper in a runbook; call `/opt/hbd/venv/bin/python -m alembic -c /opt/hbd/migrations/alembic.ini upgrade head` with the env file sourced.**~~ **The replacement this row recommended stopped working on 2026-09-10 at 14:06:46.** `[HOST 2026-09-11]` `/opt/hbd/migrations` is now **post-rename** (`env.py:57` → `from bayram.config import …`) while `/opt/hbd/venv` is **pre-rename** (`import bayram` → `ModuleNotFoundError`), so that exact command fails before it reaches the database (row 5). Running a migration on this host today needs either the post-rename venv at `/opt/bayram/venv` — which is cutover debris, not a supported install (row 49) — or a pre-rename `migrations/` tree restored beside the running venv. **And either way it then hits the schema-privilege failure of row 50, which is the real blocker: fix the GRANT first, then worry about which interpreter.** Verified 2026-09-10, re-verified `[HOST 2026-09-11]`. | `head -14 /opt/hbd/release/resume-wipe.sh`; `grep -n '^from bayram' /opt/hbd/migrations/env.py`; `/opt/hbd/venv/bin/python -c 'import bayram'` |
| 49 | **The `hbd` → `bayram` cutover that was ATTEMPTED and FAILED on 2026-09-10, and the debris it left** | **Two attempts, 14:05:05 and 14:06:53 +05, both as root. They failed in DIFFERENT places and only the second is characterised.** Attempt 2 died at the migration step — `/var/log/postgresql/postgresql-16-main.log` carries exactly one error in the whole 14:00–14:15 window, at 14:07:26.883, and `/etc/bayram/*` plus the directory's own mtime are all 14:06:54, i.e. written by attempt 2 alone. Attempt 1 ran 14:05:05.689 → 14:06:21.596 (76 s), left **no** Postgres error and **no** `/etc/bayram`, so it never reached step 3 and **its failure mode is unknown.** `10-rename-cutover.md` §2.1 reads the same evidence the same way. **Fixing row 50's GRANT addresses the second failure only**: an operator who grants and re-runs may stop in a place nobody has described, having taken the fleet down again to get there. `[HOST 2026-09-11]`, in the order a reader will trip over it: `/opt/hbd/cutover-to-bayram.sh` (9,271 bytes, 14:03:14) is the work; `/opt/hbd/deploy-payme.sh` — **the exact path the `NOPASSWD` drop-in names** — was replaced at 14:04:59 by a short wrapper that `exec`s it, with the real deploy script preserved beside it as `deploy-payme.sh.pre-cutover.bak` (4,814 bytes); the journal carries `sudo[163418]: developer : PWD=/home/developer ; USER=root ; COMMAND=/usr/bin/bash /opt/hbd/deploy-payme.sh` at 14:05:05 and again at 14:06:53. **That wrapper was then rewritten a SECOND time at 14:28:31 and now `exec`s `/opt/hbd/diagnose.sh` (536 bytes, 14:29:20 — four read-only `psql` SELECTs about schema privilege, i.e. somebody debugging row 50), and its own header comment still claims it wraps the cutover. Read the file, not the comment.** Six root invocations went through that one path on 2026-09-10: 14:05:05, 14:06:53, 14:28:31, 14:28:45, 14:28:53, 14:29:20. **The debris, none of it cleaned up** — the script is `set -uo pipefail` with no `-e` and no cleanup trap, and it dies at its alembic step (lines 102-103) before step 6/9 ever writes a unit file: **`/etc/bayram/`** (`drwxr-xr-x root:root`, 14:06:54) holding `bayram.env`, `bayram-admin.env` and `payme.env`, each `-rw-r----- root:hbd` — **a second complete copy of every secret on this host, including the audit HMAC key (row 35) and the cashbox key**, the same values with keys rewritten `HBD_` → `BAYRAM_`; **`/opt/bayram/`** holding a fully built `venv` with `bayram-bot 0.1.0` installed and importable plus a copy of all 25 migrations; the `bayram` wheel in `/opt/hbd/release` (row 45); the post-rename `migrations/` tree inside `/opt/hbd` (rows 5 and 48); and two `pre-cutover-*` dumps (row 33). **It is debris, not a deployment — and that is the thing a reader cannot tell by looking.** Nothing runs from `/opt/bayram`, no `bayram-*.service` exists, and the running units are untouched (row 46). **Whoever cleans this up should delete `/etc/bayram` first and for its own sake**; whoever re-runs the cutover will fail at the same step until row 50 is fixed. | `ls -la --time-style=+%Y-%m-%dT%H:%M:%S /opt/hbd /etc/bayram /opt/bayram /var/backups/hbd; cat /opt/hbd/deploy-payme.sh; journalctl --since '2026-09-10 14:00' \| grep deploy-payme` |
| 50 | **Role `hbd` has no rights on schema `public`, so no migration can run** | **The single blocking defect on this host.** Finding 9 carries the transcript, the root cause (`wipe-and-rebuild.sh:112-115` granted `${APP_ROLE}` = `hbd_app` and `postgres`, never the migration role) and the one-statement fix, `GRANT USAGE, CREATE ON SCHEMA public TO hbd;`. What it costs: revision `0025` cannot be applied (rows 5, 15), the rename cutover cannot complete (row 49), and any release whose migration step resolves to the migration DSN stops the same way. **Why it went unnoticed from the 09:22 rebuild until the 14:07 cutover, and has stood since**: the application role is fine, so every service is healthy, every sweep runs, the panel serves, and the failure is visible only in the Postgres server log — which the units' journals do not carry — as a message that reads like a corrupt `search_path` rather than a missing `GRANT`. **SETTLED 2026-09-11, and it is worse than this row assumed.** The operator ran the query with a password: `has_schema_privilege('hbd','public','USAGE'), …('CREATE'), (select version_num from alembic_version)` returned **`f|f|0024`** `[HOST 2026-09-11]`. So the condition still held, **both** privileges are missing rather than only `CREATE`, and the head is confirmed at `0024` from a live session rather than inferred from a dump (row 15). The missing `USAGE` is the sharper half: without it the role cannot so much as resolve a name in `public`, which is why the 14:07:26 failure read as `no schema has been selected to create in` rather than as a permission error. The remedy is unchanged and still one statement — `GRANT USAGE, CREATE ON SCHEMA public TO hbd;` — and it is now known to be *necessary*, not merely suspected. **Record the `after` values in the window notes; this row should not go back to being inferred.** **RESOLVED 2026-09-14.** The same query from a live session returned **`t|t|0025`** `[HOST 2026-09-14]`: both privileges are present and the head has moved from `0024` to `0025`. So the `GRANT` was issued and revision `0025` applied at some point between 09-11 and 09-14, by a route this row does not record — which is the one thing still owed here, because §4.1 asks the window to write down what it granted and nobody wrote this one down. **The schema-level half of finding 9 is closed. The TABLE-level half is not, and they are different questions**: `has_schema_privilege` says nothing about who owns `alembic_version`, and `deploy/fix-table-ownership.sql` records all 29 tables coming out of the rebuild owned by `hbd_app` with a null ACL. That the head moved to `0025` proves only that *something* could write the table, not that role `hbd` can. Settle it with `diagnose.sh`'s third and fourth queries before the window opens. | `sed -n '412,420p' /var/log/postgresql/postgresql-16-main.log` for the failure, `grep -nE 'GRANT\|APP_ROLE' /opt/hbd/release/wipe-and-rebuild.sh` for the cause. To settle it live, from a terminal with a password: `sudo -u postgres psql -d hbd -Atc "select has_schema_privilege('hbd','public','CREATE')"` |
| 51 | **Which Telegram bot this host actually polls as, and what its public profile says** | **`@hbduzbot`, bot id `8748584192`.** Verified 2026-09-11 by the operator running the identity tool as root against `/etc/hbd/hbd.env`. **Three bot identities are in play and no two agree.** The host polls `8748584192` (`@hbduzbot`); the developer checkout's `.env` carries `8512686028`, which [[bayram-bot-decoration]] recorded on 2026-09-07 as **`@bunorobot`**; and every string in `brand/bot-decoration.json`, plus `WATERMARK_HANDLE` on the renamed branch, promises **`@bayram_uzbot`**. The host is at least *self*-consistent — the pre-rename wheel it runs watermarks `@hbduzbot` too (`src/hbd/watermark.py:48` at `290e6e7`), so the account it polls and the handle its songs advertise are the same one. **The trap is local**: `python -m bayram.tools.identity set` run from this checkout writes to `8512686028`, a third bot that is neither the live one nor the branded one, and it will report success. Check the id before any `set`. **The live profile is still the pre-rename decoration** — name `hbd studio · tabrik qoʻshiqlari` — and it carries three claims the Bayram copy deliberately refuses: `daqiqalar ichida` (a delivery-speed claim), `Hozir bepul` (a price claim, stated twice), and `ism toʻgʻri talaffuz bilan` (the QA register `bot-decoration.json`'s writing notes name as rejected). None of the three appears in any shipped copy field of the new pack, in any locale — verified by parsing the JSON, not by grep, because the notes discuss those words at length while the copy avoids them. `Hozir bepul` is true only while the rail is off; it becomes a false public promise the moment `BAYRAM_CREDITS_ENFORCED` goes true. | `sudo bash -c "set -a; . /etc/hbd/hbd.env; set +a; /opt/hbd/venv/bin/python -m hbd.tools.identity show"` — prints `@username (id)` and the live profile, never the token. For the id alone, without a Python process or the secret: `sudo sed -n "s/^HBD_TELEGRAM_BOT_TOKEN=\([0-9]*\):.*/\1/p" /etc/hbd/hbd.env` |

> **Rows 33–35 remain the ones to do first**, and 2026-09-10 strengthened rather than weakened
> the case. Every retention argument in this codebase is about deleting data on time; not one
> line of it is about losing data. ~~Seven~~ **Nine** dumps now exist in `/var/backups/hbd` — every
> one of them taken by hand, by a script somebody ran, on the three days somebody happened to be
> deploying or cutting over. Nothing schedules a dump, nothing copies one off the box, and the one
> timer that *looks* like a backup belongs to a different application. And row 35 is the one a
> backup cannot fix: the audit HMAC key is not in any database dump, so a host rebuild makes every
> audit row unverifiable no matter how good the Postgres story gets — **and as of 2026-09-10 that
> key exists twice on this disk and still zero times off it (rows 35 and 49), which is what a
> problem getting worse looks like when it is mistaken for redundancy.**

> **A running prod panel is evidence, and on this host it is admissible.** The admin lifespan
> refuses to boot when a vendor credential is in reach and the environment is `prod`; at
> `staging` or `dev` the same finding is a WARNING nobody is watching. Row 20 says `prod` for
> both processes, so `admin.boot.ok` at 2026-09-10 09:27:37 *does* prove the vendor-separation
> check passed. That is the whole reason row 20 is asked of both files separately.
>
> **And it is the whole reason the gateway must be asked separately too, because it answers
> differently.** `hbd-payme` boots with `"environment": "dev"` (verified 2026-09-10), so *its*
> boot is not evidence of anything: the same refusal is a WARNING there. The running-process-is-
> evidence argument is per-process, and generalising it from two processes to four is exactly
> the kind of plausible guess this file exists to refuse. The command is the same shape:
> `journalctl -u hbd-payme -o cat | grep payme.boot.ok | tail -1`.

> **`grep host_verified` matches nothing, ever.** The log line's message is `"host verified"` —
> with a space (`src/bayram/runtime/startup.py:34`) — and it is the message, not an `event`
> field. The underscored token appears nowhere in the tree. `admin.boot.ok`, by contrast, *is*
> an `event` field, so grepping for that one works. Rows 20 and 21 use the spellings that
> actually match.

## What is deployed and verified, and what took until 2026-09-10 to execute

The distinction matters more than any single row: until 13:30 +05 on 2026-09-10, everything
verified about the Payme rail was **read-only**.

**Verified working.** The gateway is `active` and `enabled`, serving `hbd.payme.app:app` on
`127.0.0.1:8091`. From the public internet (2026-09-10): unauthenticated `POST /payme` → HTTP
200 `{"error":{"code":-32504}}`; on 2026-09-09 the same endpoint answered an authenticated
`Paycom:<key>` call with HTTP 200 `{"error":{"code":-31003},"id":77}`, and an unknown method
with `-32601` naming the method in `data`. `GET /healthz` on loopback → 200. The worker has
registered the Payme jobs: `run_payme_sweep` fires every five minutes and logs
`{'intents_expired': …, 'transactions_timed_out': …, 'notifications_re_enqueued': …}` — last
observed 2026-09-10 09:50.

**Executed on this host for the first time on 2026-09-10, at 13:30:15 +05 by the gateway's own
clock.** `intent → CreateTransaction → PerformTransaction → receipt and credit in one commit →
ARQ job → Telegram message`, 4/4 scenarios, and the worker's settlement invariant reporting
`transactions_performed: 1, receipts_written: 1, grants_written: 1`. Before that, every check
above stopped at an error code — which is exactly the half of the protocol that needs no
database write to be correct.

**What the host itself proves, `[HOST 2026-09-11]`, stated separately from what the harness
reported, because the two are not the same evidence:**

* The gateway logged `PerformTransaction` with `payme_transaction_id
  3f3be3f731b84a04491949dc`, `reply_code 0`, `duration_ms 54` at **13:30:15 +05** — and a second
  `Perform` on `da461c658bc2e2113b98e96c` returning `-31003`, which is the refusals scenario.
* The worker ran `notify_payment_settled` and logged *"a settled payment was announced"* at
  **13:30:16** with `public_ref 8926277867483442184b1ccc`, `product single`,
  `language uz_latn`, `is_first_stamp true`.
* **The invariant is still re-asserting itself every five minutes and still holds**: `1, 1, 1`
  over a rolling 24-hour window, most recently re-read on 2026-09-11.

**Three things the host does NOT prove, and each was written as though it did.** (a) **The run id
`e767f6ce` appears zero times in the `hbd-payme` journal, and zero times in the whole journal.**
It is the harness's own identifier and belongs attributed to the harness transcript
(`09-payme-go-live.md` §4), never to the host. (b) **No log line says a Telegram message reached
a handset** — the announce job returned without error, which is a different and weaker claim
than "delivered to a real phone". The operator who watched the phone is the evidence for that
one, and that is worth saying out loud rather than borrowing the journal's authority for it.
(c) The `13:30:14` written here previously is the harness's clock; the gateway says `13:30:15`.
One second, named rather than silently corrected, because an unexplained discrepancy between two
transcripts is what makes the next reader doubt both.

The command is the harness, and it needs `sudo -u hbd` because `/etc/hbd/payme.env` is
`root:hbd` `0640` and `developer` cannot read it. Leave `--key` off so the cashbox key stays out
of your shell history; the harness reads it from the env file it was pointed at:

```bash
sudo -u hbd env HBD_PAYME_ENV_FILE=/etc/hbd/payme.env \
  /opt/hbd/venv/bin/python -m hbd.payme.harness \
  --endpoint http://127.0.0.1:8091/payme --login Paycom --telegram-user-id <your id>
```

**`sudo -u hbd` is not in the `NOPASSWD` drop-in and will prompt** (`[HOST 2026-09-11]`:
`sudo -n -u hbd true` → `sudo: a password is required`; row 44). This block is for a human at a
terminal. **Never put it in anything unattended** — it hangs rather than failing.

**It becomes owed again at the Gate A rename** (`09-payme-go-live.md` §2): a settlement path
proven under `hbd` is not one proven under `bayram`. **And that rename has now been attempted and
has failed twice (row 49), so the rehearsal is owed against a cutover that has not yet
succeeded rather than one that is merely pending.**

**Two switches, two questions, and conflating them is the standing error.**
`HBD_PAYME_ENABLED=true` governs whether the **gateway daemon runs**. `HBD_CHECKOUT_PROVIDER`
governs whether the **bot sells anything through Payme**, and it is unset — so the composition
root builds `StubCheckoutProvider`. **The rail is off.** A live, healthy, publicly reachable
Payme endpoint tells you nothing about whether a customer can pay.

**And the paywall is live with the stub rail — as a decision, not an oversight.** Customers see
pay and subscribe buttons; tapping one grants the credit and replies "Paid" **without taking
money**. The owner was asked and decided on **2026-09-10** to leave it as is, and will say when
to accept real payments. Record it that way; it is a business position with a date on it.

**Still blocked on Payme** — but four of these closed on 2026-09-10 and are struck through
here rather than deleted, because the list is also the order in which they were asked for:
~~the merchant id~~ (sandbox, installed); ~~the test key~~ (installed); the production key;
~~registering the endpoint in the cabinet~~ (done); ~~the account field name~~ (`order_id`,
declared with the validator in `08-payme.md` §5.1); the Basic-auth login (we default to the
literal `Paycom`, which works against our own gateway and therefore proves nothing about
theirs); and `-31008` versus
`-31050` for a duplicate active transaction, which is why that one is an environment variable.

**Still not built, and named so nobody assumes otherwise**: no post-perform reversal —
`CancelTransaction` on a performed transaction answers `-31007`, and if Payme's certifier
insists on state `-2` the answer is commercial, not technical; `receivers` is not emitted;
`SetFiscalData`/IKPU is not implemented; `HBD_PAYME_RETURN_URL` is blank. And, from the routing
work: **Bot Fight Mode and a WAF skip rule for `pay.bayrambot.uz` are not configured**, which is
the only remaining lever on the `-32400`-from-Cloudflare risk now that grey cloud is impossible.

## The single discovery block

Read-only. It writes nothing, restarts nothing, and prints no secret value — for `HBD_`
variables it prints the name and whether it is set, never the value. Paste it whole; the pieces
that cannot run without a password print a line saying so rather than failing the run. It has
been updated to the paths and unit names the host actually has (row 46: **`hbd`, not
`bayram`**), and to read the routing from `cloudflared` rather than from the Caddyfile alone.

```bash
ssh aizu 'bash -s' <<'EOF'
set +e
say() { printf '\n===== %s =====\n' "$1"; }

say "identity, os, size"
hostname; head -2 /etc/os-release; uname -r; free -h | head -2; nproc; df -h / | tail -1

say "network position — is there a public address at all?"
ip -4 -o addr show | awk '{print $2, $4}'; ip route show default; echo "session: $SSH_CONNECTION"

say "the four units, as they actually run"
for u in hbd-bot hbd-worker hbd-admin hbd-payme; do
  systemctl show "$u" -p FragmentPath -p User -p WorkingDirectory -p ExecStart \
    -p EnvironmentFiles -p Environment 2>/dev/null | sed "s/^/$u /"
done

say "listening sockets — the admin bind is a security control, check it here not in config"
ss -ltn 2>/dev/null
# 127.0.0.1:20241 is cloudflared's metrics server, not ours. Row 8. Account for every line,
# because this transcript is offered as the authoritative listener inventory.
journalctl -u cloudflared --no-pager 2>/dev/null | grep -i 'metrics server' | tail -1

say "PUBLIC ROUTING — the ingress is NOT a file on this host; this log line is the only copy"
systemctl show cloudflared -p ExecStart 2>/dev/null
journalctl -u cloudflared --no-pager 2>/dev/null | grep -E 'tunnelID|Connector ID' | tail -2
journalctl -u cloudflared --no-pager 2>/dev/null | grep 'Updated to new configuration' | tail -1

say "caddy — a demultiplexer behind the tunnel. The http:// scheme is load-bearing."
caddy version 2>/dev/null
grep -nE '^\s*(https?://)?[a-z0-9.-]+\.[a-z]+.*\{|reverse_proxy|respond' /etc/caddy/Caddyfile

say "what developer may do without a password — this bounds every unattended step"
sudo -n -l 2>&1 | head -25

say "deploy layout: no checkout, a wheel, and migrations that travel separately"
ls -la /opt/hbd /opt/hbd/release 2>/dev/null
/opt/hbd/venv/bin/python -V
ls /opt/hbd/venv/lib/python3.12/site-packages | grep -iE 'hbd|bayram|editable'
ls /opt/hbd/migrations/versions/*.py 2>/dev/null | tail -3
/opt/hbd/venv/bin/pip check 2>&1 | tail -3

say "boot lines that settle rows 20-22 WITHOUT reading a secret (note the SPACE in 'host verified')"
journalctl -u hbd-bot   -o cat --no-pager 2>/dev/null | grep -F 'host verified'  | tail -1
journalctl -u hbd-admin -o cat --no-pager 2>/dev/null | grep -F 'admin.boot.ok'  | tail -1
journalctl -u hbd-admin -o cat --no-pager 2>/dev/null | grep -F 'admin.boot.vendor_env_present' | tail -1
journalctl -u hbd-admin -o cat --no-pager 2>/dev/null | grep -F 'admin.spa.nonce_placeholder_missing' | tail -1

say "dotenv files: existence and mode ONLY, never contents"
sudo -n stat -c '%n mode=%a owner=%U:%G' /etc/hbd/hbd.env /etc/hbd/hbd-admin.env /etc/hbd/payme.env 2>/dev/null \
  || echo "cannot stat /etc/hbd/* without a password — this is the wall rows 13, 23-25 and 35 sit behind"

say "postgres — psql needs a password, and for most of these rows it is not needed at all"
psql -V
sudo -n -u postgres psql -d hbd -Atc 'select version_num from alembic_version' 2>/dev/null \
  || echo "no psql without a password — so use the three readable routes below instead"

say "ROUTE 1: postgresql.conf is world-readable. Row 11, with no privilege at all."
grep -nE '^[^#]*max_connections' /etc/postgresql/16/main/postgresql.conf
ls -A /etc/postgresql/16/main/conf.d/ | wc -l   # 0 means include_dir overrides nothing

say "ROUTE 2: the Postgres server log is 0640 postgres:adm and developer is in adm. Rows 12-13."
grep -nE '^[^#]*log_line_prefix' /etc/postgresql/16/main/postgresql.conf
grep -oE '\[[0-9]+\] [a-z_]+@[a-z_]+' /var/log/postgresql/postgresql-16-main.log | sort | uniq -c
grep -E 'FATAL|ERROR' /var/log/postgresql/postgresql-16-main.log | tail -10
grep 'pg_hba.conf' /var/log/postgresql/postgresql-16-main.log | tail -1   # quotes the rule back

say "ROUTE 3: the pg_dump files are 0644 root:root. Rows 14-15, owners, ACLs, alembic_version."
D=$(ls -t /var/backups/hbd/*.sql.gz 2>/dev/null | head -1); echo "reading $D"
zcat "$D" | grep -A3 'COPY public.alembic_version'
zcat "$D" | grep -E '^(GRANT|REVOKE|ALTER DEFAULT PRIVILEGES)' | sort | uniq -c
zcat "$D" | grep -cE 'OWNER TO '   # all one role means no object-level two-role split

say "ROUTE 4: the worker journal answers row 36 without purge_runs, and predates the wipe"
journalctl -u hbd-worker --no-pager -o cat | grep -oE '"storage_keys_deleted": [0-9]+' | sort | uniq -c
journalctl -u hbd-worker --no-pager -o cat | grep -c 'retention purge complete'

say "THE FAILED CUTOVER OF 2026-09-10 — rows 49 and 50. Debris, not a deployment."
ls -la --time-style=+%Y-%m-%dT%H:%M:%S /opt/hbd /etc/bayram /opt/bayram 2>&1 | head -30
cat /opt/hbd/deploy-payme.sh 2>/dev/null   # read the file, NOT its header comment
sed -n '412,420p' /var/log/postgresql/postgresql-16-main.log   # the migration-role failure
grep -nE 'GRANT|APP_ROLE' /opt/hbd/release/wipe-and-rebuild.sh   # the cause, two lines

say "the units' OWN sandboxing — row 31's control lives here, not in the mount table"
systemctl show hbd-bot hbd-worker hbd-admin hbd-payme \
  -p Id -p ProtectSystem -p ReadWritePaths -p StateDirectory -p BindPaths 2>/dev/null

say "redis — presence and PERSISTENCE (the payme pause key lives here)"
redis-cli INFO server 2>/dev/null | grep -E 'redis_version|config_file'
redis-cli CONFIG GET appendonly; redis-cli CONFIG GET save; redis-cli DBSIZE

say "ffmpeg — libopus is what the boot probe checks; libmp3lame is what the song needs"
command -v ffmpeg && ffmpeg -hide_banner -encoders 2>/dev/null | grep -E 'libopus|libmp3lame'
command -v ffprobe || echo "no ffprobe on PATH"

say "node — EXPECTED ABSENT. The console is built into the wheel; see row 28."
command -v node || echo "no node (expected)"

say "backups — and beware aizu-backup.timer, which is a different application"
crontab -l 2>/dev/null; ls -la /var/backups/hbd 2>/dev/null
systemctl list-timers --all --no-legend 2>/dev/null | grep -iE 'backup|hbd'

say "logs — a volume budget, not a time budget"
journalctl --disk-usage 2>/dev/null
grep -sE '^[^#]*(Storage|MaxRetentionSec|SystemMaxUse)' /etc/systemd/journald.conf || echo "distro defaults"

say "payme: what address does the gateway actually see? (rows 23 and 38)"
sudo -n journalctl -u hbd-payme --since '7 days ago' -o cat 2>/dev/null \
  | grep -o '"peer_ip": *"[^"]*"' | sort | uniq -c | sort -rn | head
EOF
```

And from a machine that is **not** the host, because rows 37 and 40 cannot be checked from
inside:

```bash
curl -m 8  -o /dev/null -w 'origin 443: %{http_code}\n' https://192.166.228.52/   # expect a timeout
curl -m 12 -o /dev/null -w 'pay root:   %{http_code}\n' https://pay.bayrambot.uz/ # expect 404
curl -m 12 -X POST -d '{"id":1,"method":"CheckPerformTransaction","params":{}}' \
     -w '\npayme:      %{http_code}\n' https://pay.bayrambot.uz/payme             # expect 200 + -32504
curl -m 12 -o /dev/null -w 'admin:      %{http_code}\n' https://admin.bayrambot.uz/
```

> **What the block deliberately does not do.** It never prints a *secret* value, because these
> files hold the Telegram token, the vendor keys, two database DSNs, the audit HMAC key and the
> Payme cashbox key, and a transcript of this command will end up pasted into an issue. It
> reads `HBD_ENVIRONMENT`, `HBD_ADMIN_ENABLED` and `HBD_ADMIN_PUBLIC_ORIGIN` **out of the boot
> lines instead of out of the files** — the processes print exactly those three, and nothing
> else, at INFO. It also never restarts a unit, never runs `alembic`, and never touches the data
> root. If you need a value, read it on the host and record the *fact* here, not the secret.

## Which document wins

`deploy/first-install-proposal.md` and `deploy/systemd/bayram-{bot,worker,admin}.service`
describe a `/srv/bayram` checkout, three systemd units, `/etc/bayram/*.env` at mode 0640, and
"Caddy or nginx" terminating TLS. Those files were authored by an assistant that had no host
access. They are a **proposal**: a coherent shape somebody could deploy, not a record of what is
deployed. `deploy/systemd/bayram-payme.service` is the only one whose real-world counterpart has
been corrected on the host — and the rename has already carried the repository copy back out of
sync: verified 2026-09-10 it names `User=bayram`, `ExecStart=/opt/bayram/venv/bin/python` and
`InaccessiblePaths=/etc/bayram/bayram.env …`, none of which exists here. It has the right
*shape* (a `/opt/…/venv`, `WorkingDirectory=/var/lib/…`, an `*_ENV_FILE` variable) and the wrong
*names*, which is row 46's problem rather than a separate one. The other three
are left alone deliberately — they describe an intent (`*_ENV_FILE` indirection, rows 18–19)
that the running units do not implement, and rewriting them without redeploying would make the
repository wrong in a second way instead of right in the first.

**Most other documents in this directory inherit that status.** `docs/deployment/` holds 00
through **10** as of 2026-09-11. **Three have been checked against the machine** — this file,
[`08-payme.md`](08-payme.md) and [`09-payme-go-live.md`](09-payme-go-live.md), each of which
marks its claims with the date and the method. **10 — the `hbd` → `bayram` rename cutover — is
being written as this is written**, and row 49 is the host fact it has to start from: the cutover
was attempted twice on 2026-09-10 and failed twice. The remaining seven (01–07) are derived from
this repository alone: read them as "here is the shape we propose, and here is why each line is
the way it is", never as a description of a machine anyone has seen. That applies to any document
added later; the range above is a snapshot, not a closed set.

> **This file wins.** Where a filled-in row here disagrees with `deploy/`, or with 01–10, the
> row is right and the other document is describing a machine that does not exist. Correct the
> other document rather than reconciling the two, and do not silently edit this table to match
> a proposal.

Places where the proposal is *already* known to be wrong or unsupported, so nobody spends time
confirming them on the host:

- Its `grep host_verified` matches nothing — the message has a space in it (see the note above).
- It invokes `.venv/bin/uv` in one step and a bare `uv` in another; `uv` is in neither this
  package's dependencies nor its lock entry, so that binary would not exist from those
  instructions. It is moot here anyway: the wheel is built on the release machine (row 45).
- It installs `ffmpeg postgresql-16 redis-server` and nothing else, then runs `npm ci && npm run
  build`. Node arrives by some path the document does not record — **and on this host it never
  arrives at all** (row 28), which is correct rather than a gap.
- Its migration step exports only the bot's env-file variable, while migration 0007 reads
  `*_ADMIN_AUDIT_DSN` and `*_DATABASE_URL` from `os.environ` alone — it never parses a dotenv —
  so following it verbatim skips the `REVOKE` and logs a WARNING. Row 14 is how you find out
  whether it landed anyway.
- `deploy/systemd/bayram-worker.service` describes the worker as performing "every operational
  action the admin panel queues". There is no admin→worker job path for operational actions in
  this tree: no module under `src/bayram/admin` enqueues one, and `POST /retention/run` exists
  only as prose in a docstring (`src/bayram/admin/routers/retention.py:10`), not as a registered
  route. (The broadcast feature does add admin→worker jobs, which is a different claim about a
  different subject.)

## What is knowable here, and is not in this table

Anything in the "Value" column is a host fact. The following are *code* facts, already settled,
and belong in 01/02 rather than here — they are listed only so nobody adds a row for them:

- The four long-running commands, exactly: `python -m bayram.main` (`Makefile:80`),
  `python -m arq bayram.worker.WorkerSettings` (`Makefile:83`),
  `python -m uvicorn bayram.admin.app:app --host 127.0.0.1 --port 8080` (`Makefile:86`), and the
  Payme gateway on `:8091`. There is no console script — `pyproject.toml` has no
  `[project.scripts]` table — so any unit file must spell out the interpreter path plus `-m`.
  The host's units do exactly that, with the `hbd` spellings (row 46).
- Four variables are required by the bot and worker in every environment (`*_DATABASE_URL`,
  `*_TELEGRAM_BOT_TOKEN`, `*_ELEVENLABS_API_KEY`, `*_LLM_API_KEY`); two by the admin
  (`*_DATABASE_URL`, `*_ADMIN_AUDIT_HMAC_KEY`), plus `*_ADMIN_ENABLED=true`.
- `redis_url` defaults to `redis://localhost:6379/0` (`src/bayram/config.py:232`), so a
  misconfigured worker connects to a *local* Redis rather than failing — the queue looks empty
  instead of broken. On this host that default happens to be correct, which is worse: it means a
  lost `*_REDIS_URL` would be invisible.
- Only the worker runs the cron jobs — five of them as of migration 0024: retention, vendor
  balance, the activity snapshot, the Payme sweep and the broadcast due-check
  (`src/bayram/runtime/jobs.py:820-960`). **The deployed worker registers TEN functions, not
  five**, and the count in this bullet is the *clocks* rather than the registry — worth stating
  because "five jobs" read against the boot line looks like a discrepancy. `[HOST 2026-09-11]`, in
  the order it logs them: `generate_and_deliver`, `run_retention_sweep`, `poll_vendor_balances`,
  `record_activity_snapshot`, `notify_payment_settled`, `run_payme_sweep`,
  `expand_broadcast_audience`, `send_broadcast_chunk`, `send_broadcast_test`,
  `sweep_due_broadcasts` — five clocks plus five queued jobs. If the worker is down, the retention sweep stops, the
  audit chain's HEAD anchor stops being re-pinned so tail deletions stop being detectable, the
  activity series accrues gaps nothing backfills, and unnotified Payme payers stay unnotified.
- `var/workspace` is deleted by nothing in the repository. `var/archive` is swept on the
  retention clock; the workspace copy of the same audio and lyrics is not. Whether anything
  cleans it on this host is row 30's real question, and row 30 is one of the empty ones.
