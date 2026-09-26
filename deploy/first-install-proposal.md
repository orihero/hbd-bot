# Environments, and how production is configured

Two axes, and conflating them is the mistake this document exists to prevent.

**`BAYRAM_ENVIRONMENT` (`dev` | `staging` | `prod`) is what the code branches on.** It is a
value *inside* a config file. At `prod` the system refuses `BAYRAM_USE_FAKE_PROVIDERS`
(`runtime/providers.py`), refuses `DEBUG` on the panel (`admin/settings.py`), requires
`BAYRAM_ADMIN_PUBLIC_ORIGIN`, and refuses to boot an admin process that can reach a vendor
credential (`admin/app.py`). Only `dev` and `prod` are in use; `staging` is a supported
third value with nothing built for it yet.

**`BAYRAM_ENV_FILE` / `BAYRAM_ADMIN_ENV_FILE` decide which file gets read.** They are set in the
*process environment* — never in a dotenv file, which cannot name the file about to be read
— and they default to `.env` and `.env.admin`, so a checkout that has only ever had those
two behaves exactly as it always has.

## The four files

The split by **process** is older and more important than the split by environment: the bot
and the worker read one file, the admin API reads a different one, and there is no field on
`AdminSettings` that could hold a vendor credential. Pointing the panel at the shared file
would hand it all four keys by accident.

|                | bot + worker         | admin API                  |
| -------------- | -------------------- | -------------------------- |
| development    | `.env`               | `.env.admin`               |
| production     | `/etc/bayram/bot.env`   | `/etc/bayram/admin.env`       |

Both templates live at the repo root and carry the reasoning for every variable:
`.env.example` and `.env.admin.example`. Everything matching `.env.*` is gitignored apart
from those two.

## Running a production config from your machine

```bash
cp .env.example .env.prod             && $EDITOR .env.prod
cp .env.admin.example .env.admin.prod && $EDITOR .env.admin.prod

make admin ENV=prod                   # reads .env.prod + .env.admin.prod
make dev ENV=prod
make migrate ENV=prod
```

`ENV=dev` (the default) maps to the bare `.env` / `.env.admin`, so nothing changes for
anyone who never passes the flag. `ENV=<anything else>` maps to `.env.<name>` and
`.env.admin.<name>`.

> This is a loaded gun and it is meant to be. `ENV=prod make dev` points **real bot token,
> real vendor keys, real database** at a process running from your working tree. Both boot
> paths log which file they read — `host verified` carries `environment` and `env_file`,
> `admin.boot.ok` carries the same pair — so `journalctl` and your terminal both say which
> configuration is live. Check it before you type anything into the bot.

## The VPS

One Linux box, three systemd services, Caddy or nginx terminating TLS in front of the
loopback admin API.

```
/srv/bayram            the checkout, owned by the bayram user
/srv/bayram/.venv      the virtualenv the units exec from
/srv/bayram/var        the workspace and local object store — the only writable path
/etc/bayram/bot.env    0640 root:bayram — bot token + vendor keys + application DSN
/etc/bayram/admin.env  0640 root:bayram — NO vendor credential, ever
```

### Why the secrets are not in `EnvironmentFile=`

`EnvironmentFile=` loads every value into the process environment, where it is visible in
`systemctl show bayram-bot` and in `/proc/<pid>/environ`. The units set
`Environment=BAYRAM_ENV_FILE=/etc/bayram/bot.env` instead, so pydantic-settings reads the 0640
file directly and the credentials never enter the process environment at all. The absolute
path is also what makes a stray `.env` left in `/srv/bayram` unreadable by accident.

`bayram-admin.service` additionally carries `InaccessiblePaths=/etc/bayram/bot.env`. The
application-level refusal is a check the panel performs on itself; that line is the
kernel's, and it survives an edit that points `BAYRAM_ADMIN_ENV_FILE` at the wrong file.

### First install

```bash
# 1. user, directories, checkout
sudo useradd --system --home-dir /srv/bayram --shell /usr/sbin/nologin bayram
sudo install -d -o bayram -g bayram /srv/bayram /srv/bayram/var
sudo install -d -o root -g bayram -m 0750 /etc/bayram
sudo -u bayram git clone <repo> /srv/bayram

# 2. dependencies. ffmpeg is a hard requirement — verify_host refuses to start without it.
sudo apt install -y ffmpeg postgresql-16 redis-server
sudo -u bayram sh -c 'cd /srv/bayram && uv venv --python 3.12 .venv && uv pip install --python .venv/bin/python -e .'

# 3. the two Postgres roles, WITH REAL PASSWORDS. docker/initdb/10-two-roles.sql is a
#    development file with a development password in it; do not run it here.
sudo -u postgres psql <<'SQL'
CREATE ROLE hbd      LOGIN PASSWORD '<owner-password>';
CREATE ROLE hbd_app  LOGIN PASSWORD '<app-password>';
CREATE DATABASE hbd OWNER hbd ENCODING 'UTF8' LC_COLLATE 'C' LC_CTYPE 'C' TEMPLATE template0;
SQL
sudo -u postgres psql -d hbd -f /srv/bayram/docker/initdb/10-two-roles.sql  # grants only — read it first

# 4. the config files
sudo cp /srv/bayram/.env.example       /etc/bayram/bot.env
sudo cp /srv/bayram/.env.admin.example /etc/bayram/admin.env
sudo chown root:bayram /etc/bayram/*.env && sudo chmod 0640 /etc/bayram/*.env
sudoedit /etc/bayram/bot.env      # BAYRAM_ENVIRONMENT=prod, real keys, BAYRAM_USE_FAKE_PROVIDERS=false
sudoedit /etc/bayram/admin.env    # BAYRAM_ENVIRONMENT=prod, BAYRAM_ADMIN_ENABLED=true,
                               # BAYRAM_ADMIN_PUBLIC_ORIGIN=https://<panel host>,
                               # BAYRAM_ADMIN_AUDIT_HMAC_KEY=$(python -c "import secrets; print(secrets.token_urlsafe(48))")
                               # BAYRAM_ADMIN_AUDIT_DSN=<the OWNER dsn>  — declares the two-role split

# 5. schema, console bundle, first operator
sudo -u bayram BAYRAM_ENV_FILE=/etc/bayram/bot.env sh -c 'cd /srv/bayram && .venv/bin/python -m alembic -c migrations/alembic.ini upgrade head'
sudo -u bayram sh -c 'cd /srv/bayram/admin-dashboard && npm ci && npm run build'
sudo -u bayram BAYRAM_ADMIN_ENV_FILE=/etc/bayram/admin.env sh -c 'cd /srv/bayram && .venv/bin/python -m bayram.admin.bootstrap --username owner'

# 6. the services
sudo cp /srv/bayram/deploy/systemd/*.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now bayram-bot bayram-worker bayram-admin
```

`BAYRAM_DB_MIGRATION_URL` (the owner DSN) belongs in `/etc/bayram/bot.env` alongside
`BAYRAM_DATABASE_URL` (the application DSN). Migrations read it from there; the bot and the
worker have no field for it and never see it.

### Every subsequent deploy

```bash
sudo -u bayram sh -c 'cd /srv/bayram && git pull && .venv/bin/uv pip install --python .venv/bin/python -e .'
sudo -u bayram sh -c 'cd /srv/bayram/admin-dashboard && npm ci && npm run build'   # ALWAYS — see below
sudo -u bayram BAYRAM_ENV_FILE=/etc/bayram/bot.env sh -c 'cd /srv/bayram && .venv/bin/python -m alembic -c migrations/alembic.ini upgrade head'
sudo systemctl restart bayram-bot bayram-worker bayram-admin
```

The console rebuild is not optional. `src/bayram/admin/static/` is gitignored, so a fresh
checkout has no console at all and a stale one is whatever the last build left behind —
including an `index.html` with no `__BAYRAM_CSP_NONCE__` placeholder, which the API serves
unchanged while logging `admin.spa.nonce_placeholder_missing`.

### After a deploy, check three log lines

```bash
journalctl -u bayram-bot   -n 20 | grep host_verified          # environment=prod, env_file=/etc/bayram/bot.env
journalctl -u bayram-admin -n 20 | grep admin.boot.ok          # same pair, plus is_cookie_secure=true
journalctl -u bayram-admin | grep admin.boot.vendor_env_present   # MUST be empty in prod — it is a
                                                               # refusal there, so a running panel
                                                               # already proves it
```

Then open the panel and confirm `/audit/verify` reports `chainProtection` as something
other than `hmac-only`. `hmac-only` means the two-role split is not actually deployed:
either `BAYRAM_ADMIN_AUDIT_DSN` is unset, or migrations ran as the application role and
`0007`'s `REVOKE` had nobody to revoke from.

---

> **SUPERSEDED — DO NOT FOLLOW THIS DOCUMENT.**
>
> Everything above is the original `deploy/README.md`, preserved here **verbatim and at its
> original line numbers** because `docs/deployment/00`–`07` cite it by line — several of them
> to point out where it is wrong. It was written on 2026-09-07 by an assistant with no access
> to the production host: it is a proposal, not a record of any machine.
>
> `docs/deployment/03-provisioning.md` supersedes the first-install sequence and
> `docs/deployment/04-release.md` supersedes the deploy sequence. Both cite a file and a line
> for every claim and are explicit about which statements are host facts nobody has checked.
> `docs/deployment/00-host-inventory.md:259` lists the steps above that are already known not
> to do what they say.
>
> The notice is at the bottom rather than the top so that line 1–153 numbering survives. This
> file is a citation target and a historical record; it is not instructions.
