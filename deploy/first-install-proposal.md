# Environments, and how production is configured

Two axes, and conflating them is the mistake this document exists to prevent.

**`HBD_ENVIRONMENT` (`dev` | `staging` | `prod`) is what the code branches on.** It is a
value *inside* a config file. At `prod` the system refuses `HBD_USE_FAKE_PROVIDERS`
(`runtime/providers.py`), refuses `DEBUG` on the panel (`admin/settings.py`), requires
`HBD_ADMIN_PUBLIC_ORIGIN`, and refuses to boot an admin process that can reach a vendor
credential (`admin/app.py`). Only `dev` and `prod` are in use; `staging` is a supported
third value with nothing built for it yet.

**`HBD_ENV_FILE` / `HBD_ADMIN_ENV_FILE` decide which file gets read.** They are set in the
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
| production     | `/etc/hbd/bot.env`   | `/etc/hbd/admin.env`       |

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
/srv/hbd            the checkout, owned by the hbd user
/srv/hbd/.venv      the virtualenv the units exec from
/srv/hbd/var        the workspace and local object store — the only writable path
/etc/hbd/bot.env    0640 root:hbd — bot token + vendor keys + application DSN
/etc/hbd/admin.env  0640 root:hbd — NO vendor credential, ever
```

### Why the secrets are not in `EnvironmentFile=`

`EnvironmentFile=` loads every value into the process environment, where it is visible in
`systemctl show hbd-bot` and in `/proc/<pid>/environ`. The units set
`Environment=HBD_ENV_FILE=/etc/hbd/bot.env` instead, so pydantic-settings reads the 0640
file directly and the credentials never enter the process environment at all. The absolute
path is also what makes a stray `.env` left in `/srv/hbd` unreadable by accident.

`hbd-admin.service` additionally carries `InaccessiblePaths=/etc/hbd/bot.env`. The
application-level refusal is a check the panel performs on itself; that line is the
kernel's, and it survives an edit that points `HBD_ADMIN_ENV_FILE` at the wrong file.

### First install

```bash
# 1. user, directories, checkout
sudo useradd --system --home-dir /srv/hbd --shell /usr/sbin/nologin hbd
sudo install -d -o hbd -g hbd /srv/hbd /srv/hbd/var
sudo install -d -o root -g hbd -m 0750 /etc/hbd
sudo -u hbd git clone <repo> /srv/hbd

# 2. dependencies. ffmpeg is a hard requirement — verify_host refuses to start without it.
sudo apt install -y ffmpeg postgresql-16 redis-server
sudo -u hbd sh -c 'cd /srv/hbd && uv venv --python 3.12 .venv && uv pip install --python .venv/bin/python -e .'

# 3. the two Postgres roles, WITH REAL PASSWORDS. docker/initdb/10-two-roles.sql is a
#    development file with a development password in it; do not run it here.
sudo -u postgres psql <<'SQL'
CREATE ROLE hbd      LOGIN PASSWORD '<owner-password>';
CREATE ROLE hbd_app  LOGIN PASSWORD '<app-password>';
CREATE DATABASE hbd OWNER hbd ENCODING 'UTF8' LC_COLLATE 'C' LC_CTYPE 'C' TEMPLATE template0;
SQL
sudo -u postgres psql -d hbd -f /srv/hbd/docker/initdb/10-two-roles.sql  # grants only — read it first

# 4. the config files
sudo cp /srv/hbd/.env.example       /etc/hbd/bot.env
sudo cp /srv/hbd/.env.admin.example /etc/hbd/admin.env
sudo chown root:hbd /etc/hbd/*.env && sudo chmod 0640 /etc/hbd/*.env
sudoedit /etc/hbd/bot.env      # HBD_ENVIRONMENT=prod, real keys, HBD_USE_FAKE_PROVIDERS=false
sudoedit /etc/hbd/admin.env    # HBD_ENVIRONMENT=prod, HBD_ADMIN_ENABLED=true,
                               # HBD_ADMIN_PUBLIC_ORIGIN=https://<panel host>,
                               # HBD_ADMIN_AUDIT_HMAC_KEY=$(python -c "import secrets; print(secrets.token_urlsafe(48))")
                               # HBD_ADMIN_AUDIT_DSN=<the OWNER dsn>  — declares the two-role split

# 5. schema, console bundle, first operator
sudo -u hbd HBD_ENV_FILE=/etc/hbd/bot.env sh -c 'cd /srv/hbd && .venv/bin/python -m alembic -c migrations/alembic.ini upgrade head'
sudo -u hbd sh -c 'cd /srv/hbd/admin-ui && npm ci && npm run build'
sudo -u hbd HBD_ADMIN_ENV_FILE=/etc/hbd/admin.env sh -c 'cd /srv/hbd && .venv/bin/python -m hbd.admin.bootstrap --username owner'

# 6. the services
sudo cp /srv/hbd/deploy/systemd/*.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now hbd-bot hbd-worker hbd-admin
```

`HBD_DB_MIGRATION_URL` (the owner DSN) belongs in `/etc/hbd/bot.env` alongside
`HBD_DATABASE_URL` (the application DSN). Migrations read it from there; the bot and the
worker have no field for it and never see it.

### Every subsequent deploy

```bash
sudo -u hbd sh -c 'cd /srv/hbd && git pull && .venv/bin/uv pip install --python .venv/bin/python -e .'
sudo -u hbd sh -c 'cd /srv/hbd/admin-ui && npm ci && npm run build'   # ALWAYS — see below
sudo -u hbd HBD_ENV_FILE=/etc/hbd/bot.env sh -c 'cd /srv/hbd && .venv/bin/python -m alembic -c migrations/alembic.ini upgrade head'
sudo systemctl restart hbd-bot hbd-worker hbd-admin
```

The console rebuild is not optional. `src/hbd/admin/static/` is gitignored, so a fresh
checkout has no console at all and a stale one is whatever the last build left behind —
including an `index.html` with no `__HBD_CSP_NONCE__` placeholder, which the API serves
unchanged while logging `admin.spa.nonce_placeholder_missing`.

### After a deploy, check three log lines

```bash
journalctl -u hbd-bot   -n 20 | grep host_verified          # environment=prod, env_file=/etc/hbd/bot.env
journalctl -u hbd-admin -n 20 | grep admin.boot.ok          # same pair, plus is_cookie_secure=true
journalctl -u hbd-admin | grep admin.boot.vendor_env_present   # MUST be empty in prod — it is a
                                                               # refusal there, so a running panel
                                                               # already proves it
```

Then open the panel and confirm `/audit/verify` reports `chainProtection` as something
other than `hmac-only`. `hmac-only` means the two-role split is not actually deployed:
either `HBD_ADMIN_AUDIT_DSN` is unset, or migrations ran as the application role and
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
