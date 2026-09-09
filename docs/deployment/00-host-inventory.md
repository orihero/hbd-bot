# The aizu host — inventory

> **UNVERIFIED. Every cell in this document is empty because nobody who wrote it could reach
> the machine.** The product is *reported* to be deployed to a VPS — unverified. The only
> thing checkable from here is that a connection recipe was written down: `~/.ssh/config`
> lines 2–7 define `Host aizu` as `192.166.228.52`, port `722`, user `developer`, identity
> `~/.ssh/aizu_server`. That is an alias configured on one laptop. It does not establish that
> anything is deployed there, that the host answers, that the key still works, or that the
> account still exists — those are row 0 below. Nothing else on this page is a fact yet. The repository records how
> the software is *built* and how it *behaves*; it records nothing whatsoever about how it is
> *deployed*, and no document in `docs/` or `deploy/` was written by anyone with host access.

This file exists so that the guesses live in exactly one place and are visibly marked as
guesses. Fill it in from the host, once, and it becomes the reference the rest of the
deployment documentation defers to.

## Why an empty table beats a plausible one

The repository is full of settings whose *default* is safe and whose *deployed value* decides
whether a control exists at all. Three examples, each of which fails silently:

- `Settings.environment` is an unvalidated `str` with default `"dev"` (`src/hbd/config.py:170`),
  and `is_production` is an exact `== "prod"` comparison (`src/hbd/config.py:684-686`). A host
  set to `production` or `PROD` disarms the fake-provider refusal
  (`src/hbd/runtime/providers.py:104-109`) and the in-process-submitter refusal
  (`src/hbd/runtime/submitter.py:98-105`) with no error anywhere. `AdminSettings.environment`
  is a closed `Literal` (`src/hbd/admin/settings.py:169`); the bot's is not.
- `admin_host` and `admin_port` (`src/hbd/admin/settings.py:188-189`) are read by nothing that
  binds a socket — their only consumers are the display fields on `GET /api/config`
  (`src/hbd/admin/schemas/config_view.py:108-109`). The bind comes from the uvicorn command
  line (`Makefile:75`). So the panel's own config screen is *not* evidence about its bind
  address.
- The bot and the worker have no data-root setting at all: the root is
  `Path.cwd() / "var"` (`src/hbd/runtime/container.py:286`), while the panel reads
  `HBD_ADMIN_DATA_ROOT`, defaulting to the *relative* path `var`
  (`src/hbd/admin/settings.py:423`). The two agree only if the processes share a working
  directory, and if they disagree every media reveal in the panel 404s while the database row
  insists the file exists.

None of the three can be answered by reading this repository. Writing a plausible value into
the table below would therefore not be documentation; it would be an assertion that survives
being wrong.

## The facts that must be filled in

Run the discovery block further down and paste the answers into the "Value" column. Leave a
cell empty rather than inferring it.

| # | Fact | Value | How to find out |
| - | ---- | ----- | --------------- |
| 0 | **Whether the host answers at all, and whether anything is deployed on it** | | `ssh -o BatchMode=yes aizu true; echo $?` — the `aizu` alias proves only that somebody wrote down a connection recipe (`~/.ssh/config:2-7`). Every other row assumes this one came back yes |
| 1 | OS and release | | `cat /etc/os-release; uname -a` |
| 2 | Where the checkout lives (and whether it *is* a checkout) | | `systemctl show -p WorkingDirectory hbd-bot 2>/dev/null; ls -la ~/ /srv /opt 2>/dev/null` |
| 3 | Whether the install is editable (`pip install -e .`) or a built wheel | | `ls -la <checkout>/.venv/lib/python3.12/site-packages/ \| grep -i hbd` — an `__editable__` finder or a `.pth` means editable |
| 4 | Python version the venv actually runs | | `<checkout>/.venv/bin/python -V` — the build backend requires `>=3.12,<3.13` (`pyproject.toml:10`) |
| 5 | Whether `migrations/` is present on the host | | `ls <checkout>/migrations/versions \| tail -3` — it is *not* in the wheel (`pyproject.toml:61` packages only `src/hbd`) |
| 6 | How the bot is supervised | | `systemctl list-units --type=service \| grep -i hbd; docker ps` |
| 7 | How the ARQ worker is supervised | | same; and `pgrep -af 'arq hbd.worker'` |
| 8 | How the admin API is supervised, **and what `--host` it is given** | | `pgrep -af uvicorn` — the bind is on the command line, not in config |
| 9 | Number of worker replicas | | `pgrep -cf 'arq hbd.worker'` — the vendor concurrency semaphores are per-process (`src/hbd/runtime/container.py:332-333`), so >1 multiplies the vendor ceiling |
| 10 | Postgres version, and where it runs (same box / container / managed) | | `psql -V; systemctl status postgresql; docker ps \| grep -i postgres` |
| 11 | `max_connections` on that server | | `sudo -u postgres psql -Atc 'show max_connections'` — the pools assume a stock 100 with a 10-connection margin (`src/hbd/db/engine.py:64-67`) |
| 12 | Whether the two roles (`hbd`, `hbd_app`) exist | | `sudo -u postgres psql -Atc "select rolname from pg_roles order by 1"` |
| 13 | Which role each process connects as | | the `HBD_DATABASE_URL` line in each dotenv file (see rows 18–19) |
| 14 | Whether migration 0007's `REVOKE` is in force | | `psql -d hbd -c '\dp admin_audit_log'`, or `GET /api/audit/verify` → `chainProtection` |
| 15 | Alembic head the database is actually at | | `sudo -u postgres psql -d hbd -Atc 'select version_num from alembic_version'` — **the `-d hbd` is load-bearing**: without it `psql` connects to the invoking role's default database (`postgres`), where the answer is `relation "alembic_version" does not exist`, which reads as "no migration has ever run". The repo's head is `0021` (`migrations/versions/20260908_1200_0021_add_dashboard_read_indexes.py:93-94`) |
| 16 | Redis presence, version, and **persistence** | | `redis-cli INFO server \| head -5; redis-cli CONFIG GET appendonly; redis-cli CONFIG GET save; redis-cli CONFIG GET dir` |
| 17 | What terminates TLS, on what hostname, and whether it adds HSTS | | `systemctl list-units --type=service \| grep -Ei 'caddy\|nginx\|traefik\|apache'; ss -ltnp \| grep -E ':(80\|443)'` |
| 18 | Path and mode of the bot/worker dotenv file | | `systemctl show -p Environment hbd-bot`, then `stat -c '%n %a %U:%G' <that path>` |
| 19 | Path and mode of the admin dotenv file | | `systemctl show -p Environment hbd-admin`, then `stat` as above |
| 20 | `HBD_ENVIRONMENT` in **each** of the two files | | `sudo grep -n '^HBD_ENVIRONMENT=' <bot env> <admin env>` — they are independent (`src/hbd/config.py:170`, `src/hbd/admin/settings.py:169`) |
| 21 | `HBD_ADMIN_ENABLED` | | `sudo grep -n '^HBD_ADMIN_ENABLED=' <admin env>` — default is `false` and the lifespan refuses without it (`src/hbd/admin/app.py:206-208`, `settings.py:180`) |
| 22 | `HBD_ADMIN_PUBLIC_ORIGIN`, and whether it matches the origin browsers actually reach | | `sudo grep -n '^HBD_ADMIN_PUBLIC_ORIGIN=' <admin env>` — compared exactly (`src/hbd/admin/settings.py:194`, `src/hbd/admin/csrf.py:76-88` — note `csrf.py` is at the package root, *not* under `security/`) |
| 23 | `HBD_ADMIN_TRUSTED_PROXY_HOPS` / `_CIDRS` | | `sudo grep -nE '^HBD_ADMIN_TRUSTED_PROXY' <admin env>` — at the shipped defaults every audit row and rate-limit key records the proxy's address (`src/hbd/admin/security/clientip.py:142`, `settings.py:216-217`) |
| 24 | `HBD_ADMIN_PROBE_TOKEN` — set or empty | | `sudo grep -c '^HBD_ADMIN_PROBE_TOKEN=.\+' <admin env>` — empty means `/readyz` answers a constant `ok` to every monitor (`src/hbd/admin/routers/health.py:93-105, 126-131`) |
| 25 | Whether `HBD_DB_MIGRATION_URL` is set anywhere the migration runner reads | | `sudo grep -n '^HBD_DB_MIGRATION_URL=' <bot env>` (`migrations/env.py:96-114`) |
| 26 | ffmpeg present, and whether it has `libopus` | | `ffmpeg -hide_banner -encoders \| grep -E 'libopus\|libmp3lame'` — `libopus` is the only encoder the boot probe checks (`src/hbd/audio/constants.py:113,121`; `src/hbd/audio/startup.py:93-103`) |
| 27 | ffprobe present | | `command -v ffprobe` |
| 28 | Node/npm present, and version | | `node -v; npm -v` — the console needs `npm run build`; `admin-ui/package.json` declares `node >=20.19` |
| 29 | Whether the served console bundle exists and is current | | `ls -la <checkout>/src/hbd/admin/static/index.html; grep -c __HBD_CSP_NONCE__ <checkout>/src/hbd/admin/static/index.html` — the directory is gitignored (`.gitignore:49`) |
| 30 | Absolute path of the data root, and its size | | `du -sh <checkout>/var/archive <checkout>/var/workspace 2>/dev/null` |
| 31 | Whether the admin's data volume is genuinely mounted read-only | | `findmnt -T <checkout>/var` — the code hands the panel a read-write `LocalFileStorage` (`src/hbd/admin/container.py:155`); only the filesystem can make the claim true |
| 32 | Where logs go and how long they are kept | | `journalctl --disk-usage; grep -E '^(Storage\|MaxRetentionSec)' /etc/systemd/journald.conf` |
| 33 | Backup story: Postgres | | `crontab -l; ls /etc/cron.d; systemctl list-timers` — **nothing in this repository backs anything up** |
| 34 | Backup story: `var/archive` (delivered audio *and* every customer avatar) | | as above; `src/hbd/storage.py:73-84` and `src/hbd/user_profiles.py:199-200` share one root |
| 35 | Backup story: `HBD_ADMIN_AUDIT_HMAC_KEY` | | is it stored anywhere but the admin dotenv file? The chain has no key id (`src/hbd/db/admin/audit.py:10-12`), so losing it makes the whole log unverifiable |
| 36 | Whether the retention cron has ever run | | `psql -d hbd -c 'select ran_at, is_batch_full, storage_keys_returned, storage_keys_deleted from purge_runs order by ran_at desc limit 5'` |
| 37 | **The hostname Payme calls, and whether it is a DEDICATED name** | | Nothing in this repository can answer this and nothing here can verify it. It is registered by a human in the Payme cabinet (Кассы → the kassa → Настройки → Инструменты разработчика) as the Endpoint URL, `https://<hostname>/payme`. It must NOT be the admin panel's name: the panel has to be the only reachable name at its origin, because both its cookies are `__Host-` prefixed and un-narrowable and its CSRF check compares `HBD_ADMIN_PUBLIC_ORIGIN` exactly. Confirm too that the terminator proxies `POST /payme` to `127.0.0.1:8091` and passes HTTP 200 bodies through unaltered — Payme reads any other status as a transport fault (`docs/deployment/08-payme.md` §4) |
| 38 | **The caller-IP allowlist actually configured at the terminator** | | Payme originates from `185.234.113.1`–`185.234.113.15` (`185.234.113.0/28`), and the allowlist is the terminator's job, NOT the application's: `payme_allowed_cidrs` defaults to empty and is honoured only when `payme_trusted_proxy_hops > 0`, because at zero hops the app sees the proxy's address and a filter matching the wrong address is worse than no filter. So this row is the whole control. `nginx -T \| grep -A5 payme`, or the equivalent for whatever row 17 turns out to be. Cross-check it against what actually called us: `journalctl -u hbd-payme --since '7 days ago' -o cat \| grep -o '"peer_ip": *"[^"]*"' \| sort \| uniq -c` |

> **Rows 33–35 are the ones to do first.** Every retention argument in this codebase is about
> deleting data on time; not one line of it is about losing data.
> `grep -rn 'pg_dump\|backup' README.md Makefile deploy/ docs/` finds no backup procedure
> anywhere: `pg_dump` appears only inside `docs/deployment/` itself, in this workflow's own
> "nothing backs anything up" sentences, and `grep -rin backup README.md Makefile deploy/`
> returns exactly one hit — a row in `deploy/README.md`'s index table pointing at
> `05-operations.md`, i.e. a cross-reference to prose, not a procedure. The one substantive
> hit anywhere for the word "backup" is
> `docs/research/DASHBOARD_METRICS_RESEARCH.md:133`, where it means a *fallback vendor*, not a data
> backup. If the answer to row 33 is "nothing", that is the finding, and it is worth more than
> the other thirty-eight put together.

## The single discovery block

Read-only. It writes nothing, restarts nothing, and prints no secret values — for `HBD_`
variables it prints the name, whether it is set, and the file's mode, with one deliberate
exception noted below: six named non-secret variables are printed in full. Paste it whole; the pieces that do not apply
(no systemd, no local Postgres) print a line saying so rather than failing the run.

```bash
ssh aizu 'bash -s' <<'EOF'
set +e
say() { printf '\n===== %s =====\n' "$1"; }

say "os / kernel / uptime"
cat /etc/os-release 2>/dev/null | head -3; uname -a; uptime

say "hbd processes as they are actually running (argv is where the admin bind lives)"
pgrep -af 'hbd.main|arq hbd.worker|uvicorn' || echo "no hbd process matched"

say "supervision"
command -v systemctl >/dev/null && systemctl list-units --type=service --all --no-legend | grep -i hbd || echo "no systemd, or no hbd units"
if command -v docker >/dev/null; then
  docker ps --format '{{.Names}}\t{{.Image}}\t{{.Status}}' \
    || echo "docker IS INSTALLED but did not answer (daemon stopped, or 'developer' not in the docker group) — record this, it is NOT 'not containerised'"
else
  echo "no docker binary on PATH"
fi

say "unit facts (WorkingDirectory decides the bot/worker data root)"
for u in hbd-bot hbd-worker hbd-admin; do
  systemctl show "$u" -p FragmentPath -p WorkingDirectory -p ExecStart -p Environment -p ReadWritePaths 2>/dev/null | sed "s/^/$u /"
done

say "listening sockets (is the admin API on loopback? what is on 80/443?)"
ss -ltnp 2>/dev/null || netstat -ltnp 2>/dev/null

say "tls terminator"
command -v systemctl >/dev/null && systemctl list-units --type=service --no-legend | grep -Ei 'caddy|nginx|traefik|apache|haproxy' || echo "none matched"

say "dotenv files: existence and mode ONLY, never contents"
for f in /etc/hbd/bot.env /etc/hbd/admin.env; do stat -c '%n mode=%a owner=%U:%G size=%s' "$f" 2>/dev/null; done
sudo -n ls -la /etc/hbd 2>/dev/null || echo "cannot list /etc/hbd without a password"

say "which HBD_ variables are SET in each file (names and set/empty only)"
for f in /etc/hbd/bot.env /etc/hbd/admin.env; do
  echo "-- $f"
  sudo -n awk -F= '/^HBD_[A-Z0-9_]+=/{n=$1; v=substr($0,index($0,"=")+1); print n, (length(v)?"set":"EMPTY")}' "$f" 2>/dev/null || echo "unreadable"
done

say "the six NON-SECRET values whose exact text decides whether a control exists (printed in full)"
for f in /etc/hbd/bot.env /etc/hbd/admin.env; do
  sudo -n grep -nE '^(HBD_ENVIRONMENT|HBD_ADMIN_ENABLED|HBD_ADMIN_PUBLIC_ORIGIN|HBD_ADMIN_TRUSTED_PROXY_HOPS|HBD_IS_DEBUG|HBD_LOG_LEVEL)=' "$f" 2>/dev/null | sed "s|^|$f:|"
done

say "python runtime and install shape"
for d in /srv/hbd /opt/hbd "$HOME/hbd-bot" "$HOME/hbd"; do
  [ -d "$d" ] && { echo "-- $d"; ls -la "$d" | head -20; "$d/.venv/bin/python" -V 2>/dev/null; ls "$d/.venv/lib/"*/site-packages 2>/dev/null | grep -iE 'hbd|editable'; }
done

say "checkout state, if it is a git checkout"
for d in /srv/hbd /opt/hbd "$HOME/hbd-bot" "$HOME/hbd"; do
  [ -d "$d/.git" ] && git -C "$d" log --oneline -1 && git -C "$d" status --porcelain | head -10
done

say "console bundle: present? still carrying the CSP nonce placeholder?"
for d in /srv/hbd /opt/hbd "$HOME/hbd-bot" "$HOME/hbd"; do
  i="$d/src/hbd/admin/static/index.html"
  [ -f "$i" ] && { stat -c '%n mtime=%y size=%s' "$i"; grep -c '__HBD_CSP_NONCE__' "$i"; }
done

say "data root: the two subdirectories with very different lifecycles"
for d in /srv/hbd /opt/hbd "$HOME/hbd-bot" "$HOME/hbd"; do
  [ -d "$d/var" ] && { du -sh "$d/var/archive" "$d/var/workspace" 2>/dev/null; findmnt -T "$d/var" 2>/dev/null | tail -1; }
done

say "ffmpeg — libopus is the only encoder the boot probe checks; libmp3lame is what the song needs"
if command -v ffmpeg >/dev/null; then
  command -v ffmpeg
  enc=$(ffmpeg -hide_banner -encoders 2>/dev/null)
  for e in libopus libmp3lame; do
    printf '%s ' "$e"
    printf '%s\n' "$enc" | grep -q -- "$e" && echo PRESENT || echo "MISSING (ffmpeg is installed — this is an encoder gap, not an absent binary)"
  done
else
  echo "no ffmpeg on PATH"
fi
command -v ffprobe || echo "no ffprobe on PATH"

say "node — the console cannot be rebuilt without it"
command -v node && node -v; command -v npm && npm -v

say "postgres"
command -v psql && psql -V
command -v systemctl >/dev/null && systemctl is-active postgresql 2>/dev/null
sudo -n -u postgres psql -Atc "select version()" 2>/dev/null
sudo -n -u postgres psql -Atc "show max_connections" 2>/dev/null
sudo -n -u postgres psql -Atc "select rolname from pg_roles where rolcanlogin order by 1" 2>/dev/null
sudo -n -u postgres psql -d hbd -Atc "select version_num from alembic_version" 2>/dev/null
sudo -n -u postgres psql -d hbd -Atc "select relname, relacl from pg_class where relname='admin_audit_log'" 2>/dev/null
sudo -n -u postgres psql -d hbd -Atc "select ran_at, is_batch_full, storage_keys_returned, storage_keys_deleted from purge_runs order by ran_at desc limit 5" 2>/dev/null

say "redis — presence and PERSISTENCE"
if command -v redis-cli >/dev/null; then
  command -v redis-cli
  if redis-cli PING >/dev/null 2>&1; then
    redis-cli INFO server 2>/dev/null | grep -E 'redis_version|config_file'
    redis-cli CONFIG GET appendonly; redis-cli CONFIG GET save; redis-cli CONFIG GET dir
    redis-cli DBSIZE
  else
    echo "redis-cli IS INSTALLED but the server did not answer PING (stopped, password-protected, bound elsewhere, or on another host) — record this as 'installed, not answering', NOT as 'no Redis on this box'"
    redis-cli PING 2>&1 | head -2
  fi
else
  echo "no redis-cli binary on PATH"
fi

say "backups — cron, timers, anything"
crontab -l 2>/dev/null; sudo -n ls -la /etc/cron.d /etc/cron.daily 2>/dev/null
command -v systemctl >/dev/null && systemctl list-timers --all --no-legend 2>/dev/null | head -20

say "logs — where they go and how much is kept"
command -v journalctl >/dev/null && journalctl --disk-usage 2>/dev/null
grep -sE '^[^#]*(Storage|MaxRetentionSec|SystemMaxUse)' /etc/systemd/journald.conf

say "boot lines that answer several rows at once (note the SPACE in 'host verified')"
command -v journalctl >/dev/null && {
  journalctl -u hbd-bot   -n 200 --no-pager 2>/dev/null | grep -F 'host verified' | tail -2
  journalctl -u hbd-admin -n 200 --no-pager 2>/dev/null | grep -F 'admin.boot.ok' | tail -2
  journalctl -u hbd-admin --no-pager 2>/dev/null | grep -F 'admin.boot.vendor_env_present' | tail -2
  journalctl -u hbd-admin --no-pager 2>/dev/null | grep -F 'admin.spa.nonce_placeholder_missing' | tail -2
  journalctl -u hbd-admin --no-pager 2>/dev/null | grep -F 'admin.audit.revoke_missing' | tail -2
}
EOF
```

> **`grep host_verified` matches nothing, ever.** `deploy/first-install-proposal.md:143` tells an operator to
> check the bot booted with `journalctl -u hbd-bot -n 20 | grep host_verified`. The log line's
> message is `"host verified"` — with a space — and it is the message, not an `event` field
> (`src/hbd/runtime/startup.py:33-41`). The underscored token appears nowhere in the tree. An
> operator following that checklist sees an empty result and may conclude the bot did not
> start. The block above greps the real string. By contrast `admin.boot.ok` *is* an `event`
> field (`src/hbd/admin/app.py:325`), so `deploy/first-install-proposal.md:144` does work.

> **A running prod panel is itself evidence, for one thing only.** The admin lifespan refuses
> to boot when a vendor credential is in reach and `HBD_ENVIRONMENT=prod`
> (`src/hbd/admin/app.py:186-199`); at `staging` or `dev` the same finding is a WARNING nobody
> is watching. So a live panel proves the vendor-separation check passed *only if* row 20 says
> `prod`. That is why row 20 is asked of both files separately.

> **What the block deliberately does not do.** It never prints a *secret* value. For every
> `HBD_` variable it reports the name and whether it is set, and nothing more, because these
> files hold the Telegram token, both vendor keys, two database DSNs and
> `HBD_ADMIN_AUDIT_HMAC_KEY`, and a transcript of this command will end up pasted into an
> issue. The one exception is deliberate and bounded: six named non-secret variables —
> `HBD_ENVIRONMENT`, `HBD_ADMIN_ENABLED`, `HBD_ADMIN_PUBLIC_ORIGIN`,
> `HBD_ADMIN_TRUSTED_PROXY_HOPS`, `HBD_IS_DEBUG`, `HBD_LOG_LEVEL` — are printed **in full**,
> because the whole point of rows 20–23 is the exact text. If your dotenv holds anything
> secret under one of those six names, redact before you paste. It also never restarts a unit, never runs
> `alembic`, and never touches `var/`. If you need a value, read it on the host and record the
> *fact* here, not the secret.

## Which document wins

`deploy/first-install-proposal.md` and `deploy/systemd/hbd-{bot,worker,admin}.service` describe a `/srv/hbd`
checkout, an `hbd` system user, three systemd units, `/etc/hbd/*.env` at mode 0640, and
"Caddy or nginx" terminating TLS (`deploy/first-install-proposal.md:56-65`, `deploy/systemd/hbd-bot.service:24-28`).
Those files were authored by an assistant that had no more host access than this one. They are
a **proposal**: a coherent shape somebody could deploy, not a record of what is deployed.
**Every other document in this directory inherits that status.** `docs/deployment/` holds 00
through 07 as of this writing, and not one of them was written by anyone who could reach the
host. Some borrow the proposal's nouns outright — `/srv/hbd` appears 17 times in 03, once in
04 and once in 07, and the `hbd-{bot,worker,admin}` unit names appear 15 times in 03, three
times in 01 and once in 07. Others borrow its *shape* without naming a path: 05 and 06 give
operational and diagnostic procedures that assume the proposed three-unit, one-checkout
layout even where they never say `/srv/hbd`. Read all of them as "here is the shape we
propose, and here is why each line is the way it is" — never as a description of a machine
anyone has seen. This paragraph applies to any document added to the directory later; the
filenames counted above are a snapshot, not a closed set.

> **This file wins, once it is filled in.** Where a filled-in row here disagrees with
> `deploy/`, or with any of 01–07, the row is right and the other document is describing a machine
> that does not exist. Correct the other document rather than reconciling the two, and do not
> silently edit this table to match a proposal — an empty cell means "nobody has looked", and
> that is information.

A short list of the places where the proposal is *already* known to be wrong or unsupported,
so nobody spends time confirming them on the host:

- `deploy/first-install-proposal.md:143`'s `grep host_verified` matches nothing (above).
- `deploy/first-install-proposal.md:129` invokes `.venv/bin/uv`; `uv` is in neither `pyproject.toml`'s
  dependencies nor `uv.lock`'s entry for this package, so that binary would not exist from
  these instructions. Line 90 invokes a bare `uv`, so the two commands disagree with each
  other as well.
- `deploy/first-install-proposal.md:89` installs `ffmpeg postgresql-16 redis-server` and nothing else, then
  lines 113 and 130 run `npm ci && npm run build`. Node arrives by some path the document does
  not record.
- `deploy/first-install-proposal.md:112`'s migration command exports only `HBD_ENV_FILE`. Migration 0007 reads
  `HBD_ADMIN_AUDIT_DSN` and `HBD_DATABASE_URL` from `os.environ` alone
  (`migrations/versions/20260830_1000_0007_add_admin_audit_log.py:314-322, 336`) — it never
  parses a dotenv file — so following that step verbatim skips the `REVOKE` and logs a WARNING.
  Row 14 is how you find out whether it landed anyway; `resolve_chain_protection` asks Postgres
  rather than trusting configuration (`src/hbd/db/admin/audit.py:754-780`), so the panel's
  answer is honest in both directions.
- `deploy/systemd/hbd-worker.service:1-2` describes the worker as performing "every operational
  action the admin panel queues". There is no admin→worker job path in this tree. `AdminContainer`
  declares eight fields — settings, engine, session factory, Redis, an argon2 `PasswordHasher`,
  trusted proxies, rate limits and a `Storage` (`src/hbd/admin/container.py:80-93`, the storage
  built at `:155` and cited by row 31) — and an ARQ pool is not among them. No module under
  `src/hbd/admin` imports `arq` or enqueues a job; `POST /retention/run`, the one write the panel
  is documented as queueing, exists only as prose in a docstring
  (`src/hbd/admin/routers/retention.py:10`) and is not a registered route.

## What is knowable here, and is not in this table

Anything in the "Value" column is a host fact. The following are *code* facts, already settled,
and belong in 01/02 rather than here — they are listed only so nobody adds a row for them:

- The three long-running commands, exactly: `python -m hbd.main` (`Makefile:69`),
  `python -m arq hbd.worker.WorkerSettings` (`Makefile:72`), and
  `python -m uvicorn hbd.admin.app:app --host 127.0.0.1 --port 8080` (`Makefile:75`). There is
  no console script — `pyproject.toml` has no `[project.scripts]` table — so any unit file must
  spell out the interpreter path plus `-m`.
- Four variables are required by the bot and worker in every environment
  (`HBD_DATABASE_URL`, `HBD_TELEGRAM_BOT_TOKEN`, `HBD_ELEVENLABS_API_KEY`, `HBD_LLM_API_KEY` —
  `src/hbd/config.py:187, 689-699`); two by the admin (`HBD_DATABASE_URL`,
  `HBD_ADMIN_AUDIT_HMAC_KEY` — `src/hbd/admin/settings.py:174, 229`), plus
  `HBD_ADMIN_ENABLED=true`.
- `HBD_REDIS_URL` defaults to `redis://localhost:6379/0` (`src/hbd/config.py:188`), so a
  misconfigured worker connects to a *local* Redis rather than failing — the queue looks empty
  instead of broken. Redis is a hard dependency of both the bot and the worker in prod, not just
  the worker (`src/hbd/main.py:94`, `src/hbd/bot/app.py:83,97`).
- Only the worker runs the three cron jobs — retention at :17, vendor balance at :43, activity
  snapshot at 00:07 UTC (`src/hbd/runtime/jobs.py:705-769`). If it is down, the retention sweep
  stops, the audit chain's HEAD anchor stops being re-pinned so tail deletions stop being
  detectable, and the activity series accrues gaps nothing backfills.
- `var/workspace` is deleted by nothing in the repository. `var/archive` is swept on the
  retention clock; the workspace copy of the same audio and lyrics is not. Whether anything
  cleans it on the host is row 30's real question.
