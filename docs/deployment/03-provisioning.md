# Provisioning a host from bare metal

**`aizu` is already provisioned. Do not run this document against it.**

This is two things and neither of them is a deploy script:

1. **The record of what a correct host looks like** — every step, why it exists, and how you
   know it worked. Written from the repository, so every claim here is checkable against a
   file and a line number.
2. **The list to compare `aizu` against.** Where a step here produces observable state — a
   role in `pg_roles`, a file mode, a log line, a field in an API response — that observation
   is the comparison. Read it as an audit checklist, not as a runbook to replay.

Nobody who wrote this has access to `aizu`. Everything below is what the code in this
checkout requires. Nothing below is a statement about what is on that box.

> **The deploy proposal is a proposal.** `deploy/first-install-proposal.md` and `deploy/systemd/*.service`
> were authored in this repository by an assistant with no host access. They are a
> well-reasoned design for a host; they are not a record of one. Where this document cites
> them it says so, and it flags the places where following them verbatim does not do what
> they claim.

---

## 0. What you are provisioning

Three long-running processes and one command that is run by hand:

| what | command | needs |
| --- | --- | --- |
| the bot | `python -m hbd.main` (Makefile:69) | ffmpeg, Postgres, Redis, Telegram + vendor keys |
| the ARQ worker | `python -m arq hbd.worker.WorkerSettings` (Makefile:72) | the same, plus it is the only thing that runs the crons |
| the admin API | `python -m uvicorn hbd.admin.app:app --host 127.0.0.1 --port 8080` (Makefile:75) | Postgres, Redis, **no** ffmpeg, **no** vendor key |
| the schema | `python -m alembic -c migrations/alembic.ini upgrade head` (Makefile:147) | the owner DSN, a checkout on disk |

There is no console script for any of them. `pyproject.toml` has no `[project.scripts]`
table, so after installation there is no `hbd` or `hbd-worker` binary on `PATH` — every
supervisor entry must spell out the interpreter path plus `-m`. That also means nothing in
the package metadata pins these entry points: renaming `hbd.worker.WorkerSettings` breaks a
deploy silently.

> **The admin API needs a materially smaller host than the other two.** `verify_host` is
> called only from `src/hbd/main.py:100`, `src/hbd/worker.py:45` and `src/hbd/demo.py:179`.
> `src/hbd/admin/app.py` never imports it. An admin-only box needs no ffmpeg at all.

---

## 1. OS packages, and the ffmpeg requirement

```bash
sudo apt update
sudo apt install -y ffmpeg postgresql-16 redis-server build-essential python3-dev
```

**Why `build-essential` and `python3-dev` are on that line.** `pyproject.toml:27-29` claims
argon2-cffi is the only C extension in the tree. That comment is stale three times over —
`asyncpg` (pyproject.toml:18), `uvicorn[standard]`'s uvloop and httptools (pyproject.toml:31)
and `pillow` (pyproject.toml:45) are all compiled. On an architecture with prebuilt wheels
for all four you will not need a compiler; on one without, the install fails at build time
with no other hint. Installing the toolchain up front costs nothing and removes a failure
mode nothing in the repo documents. (`deploy/first-install-proposal.md:89` — the proposal — installs only
`ffmpeg postgresql-16 redis-server`.)

**Why ffmpeg is a hard prerequisite and not a nice-to-have.** `verify_host` refuses to start
the bot and the worker on exactly three things, and the message names the environment
variable in each case:

- `ffmpeg` on `PATH` (src/hbd/audio/startup.py:93)
- `ffprobe` on `PATH` (src/hbd/audio/startup.py:94)
- an ffmpeg build whose `-encoders` table contains `libopus` (src/hbd/audio/startup.py:96-103,
  with `REQUIRED_ENCODERS` at src/hbd/audio/constants.py:121 derived from
  `VOICE_NOTE_CODEC = "libopus"` at :113)

Without libopus, Telegram's `sendVoice` renders a greeting as a file attachment rather than a
voice note, which is why the check is a refusal rather than a warning. The probe has a 15
second ceiling (src/hbd/audio/constants.py:66) so a broken binary cannot hang a boot.

Verify:

```bash
ffmpeg -hide_banner -encoders | grep -E 'libopus|libmp3lame'
ffprobe -version | head -1
```

> **Check for `libmp3lame` even though nothing refuses without it.** The delivered song is
> written with the extension the vendor's MIME type implies — `audio/mpeg` becomes `.mp3`
> (src/hbd/pipeline/assets.py:75) — and `codec_args_for` pins a codec only for `.wav`
> (src/hbd/audio/commands.py:65-73), so ffmpeg infers the mp3 encoder from the suffix. The
> loudness master is explicitly non-fatal: `_normalized` falls back to the source file and
> never raises (src/hbd/pipeline/assets.py:129-133). An ffmpeg with libopus but no mp3
> encoder therefore passes the boot check and ships an unmastered song to every paying
> customer, with no error anywhere. The boot probe was written to prevent exactly this
> failure — for a different codec.

**ffmpeg does not have to be on `PATH`.** `HBD_FFMPEG_BINARY` and `HBD_FFPROBE_BINARY`
(src/hbd/config.py:414-415, documented at .env.example:233) take an absolute path, and the
"not found" message names them. A host with a custom build needs a config line, not a `PATH`
change.

**Postgres 16 and Redis 7** are what `docker-compose.yml` pins for local development
(`postgres:16-alpine`, `redis:7-alpine`). That file's first two lines say "Local dependencies
only", so those pins are a statement about the development stack, not a requirement the code
enforces. Nothing in `src/` asserts a server version.

---

## 2. The service user and the directory layout

```bash
sudo useradd --system --home-dir /srv/hbd --shell /usr/sbin/nologin hbd
sudo install -d -o hbd -g hbd /srv/hbd            # empty — git accepts an existing empty dir
sudo install -d -o root -g hbd -m 0750 /etc/hbd
sudo -u hbd git clone <repo> /srv/hbd
sudo install -d -o hbd -g hbd /srv/hbd/var        # AFTER the clone, not before
```

> **The proposal's version of this block cannot be run as written.**
> `deploy/first-install-proposal.md:84-86` creates `/srv/hbd` and `/srv/hbd/var` in one `install -d` and then
> clones into `/srv/hbd`. `git clone` refuses a destination that exists and is non-empty —
> `fatal: destination path '/srv/hbd' already exists and is not an empty directory` — so the
> proposal's fourth line dies every time. Creating `var` after the clone, as above, is the
> whole fix; cloning into an existing *empty* directory is allowed.

The paths come from the deploy proposal (deploy/first-install-proposal.md:60-65). The *shape* is forced by
the code:

**The data root is derived from the process working directory, and there is no variable that
moves it.** `build_container` computes `root = (data_root or Path.cwd() / "var").resolve()`
(src/hbd/runtime/container.py:286), creates `var/workspace` and `var/archive` under it
(:287-290), and `hbd.main.run` accepts a `data_root` argument that `main()` never passes
(src/hbd/main.py:222). There is no `data_root` field on `Settings`. So for the bot and the
worker, "where the songs live" is decided entirely by the directory the process is started
in.

The admin API gets its own knob, `HBD_ADMIN_DATA_ROOT`, defaulting to the **relative** path
`var` (src/hbd/admin/settings.py:423) and joined with the archive directory name at
src/hbd/admin/container.py:155. Its docstring claims it is "the same directory
`hbd.runtime.container.build_container` is given as its `data_root`" — a claim no variable
enforces.

> **This is the load-bearing one.** If the admin process's working directory differs from the
> bot's, every media reveal in the panel returns "no such object" while the database row says
> the file exists, and there is no configuration error anywhere to explain it. Either run all
> three processes with the same `WorkingDirectory`, or set `HBD_ADMIN_DATA_ROOT` to the
> bot's absolute `var` path. Do not rely on the two relative defaults agreeing by luck.

**`var/archive` holds two key namespaces with different lifecycles**, through one shared
`LocalFileStorage` instance (src/hbd/runtime/container.py:301-307, which explains why the
sharing is required): `orders/{order_id}/{filename}` (src/hbd/storage.py:84), swept on the
asset retention clock, and `users/{user_id}/avatar.jpg` (src/hbd/user_profiles.py:199-200),
deleted only by a customer's `/forget`. A filesystem backup of that tree is a backup of both
delivered songs and customer photographs; they cannot be scoped apart at the path level.

> **`var/workspace` is never swept by anything.** The retention job deletes only through the
> archive-rooted `Storage` (src/hbd/runtime/retention_job.py:135). A repo-wide search for
> `rmtree` / `.unlink(` / `os.remove` under `src/` finds two hits — src/hbd/storage.py:339
> (a failed atomic write's temp file) and src/hbd/audio/tempfiles.py:44 (a per-call scratch
> dir) — and neither touches a published workspace file. Per-order workspace directories are
> deterministic (`root / str(order_id)`, src/hbd/pipeline/assembly.py:54-56). Every song,
> greeting, cover and lyric sheet therefore exists twice on disk, and the second copy
> outlives every clock in `RetentionPolicy`. Provision the volume for unbounded growth, or
> put a host-level sweep on `var/workspace` — the repository has none.

---

## 3. Python 3.12 and the venv

```bash
sudo -u hbd sh -c 'cd /srv/hbd && uv venv --python 3.12 .venv \
  && uv pip install --python .venv/bin/python -e .'
```

**3.12 and only 3.12.** `pyproject.toml:10` is `requires-python = ">=3.12,<3.13"` and
`uv.lock:3` is `requires-python = "==3.12.*"`; ruff targets `py312` (pyproject.toml:78) and
mypy is pinned to the same (pyproject.toml:122). A host that installs the distribution's
default `python3` and finds 3.13 fails at `uv venv --python 3.12`, which is the good place to
fail.

**`-e .` is not an aesthetic choice — a wheel is not a complete deployment unit.**
`migrations/` sits at the repository root and `[tool.hatch.build.targets.wheel] packages` is
`["src/hbd"]` (pyproject.toml:61), so no wheel contains the migration scripts, and every
documented alembic invocation assumes a checkout on disk (Makefile:147). The editable install
also means the console bundle is served straight from the checkout's
`src/hbd/admin/static/`, because `STATIC_DIR` is `Path(__file__).resolve().parent / "static"`
(src/hbd/admin/app.py:128). The `artifacts = ["src/hbd/admin/static/**"]` line
(pyproject.toml:71) exists to protect a *wheel-based* deploy and does nothing on this path.

> **`uv.lock` is documentation, not a pin.** It exists and is in sync with `pyproject.toml`,
> but `uv pip install` does not read it — `uv sync` appears nowhere in the tree. Two installs
> a week apart resolve independently inside the `>=` / `<` ranges. If reproducibility across
> hosts matters, that is a change to make deliberately; do not assume the lock file is doing
> it.

Verify:

```bash
/srv/hbd/.venv/bin/python -V                     # 3.12.x
/srv/hbd/.venv/bin/python -c 'import hbd, sys; print(hbd.__file__)'
```

`uv` itself is neither a project dependency nor in `uv.lock`, so it has to come from
somewhere else on the host. Note that `deploy/first-install-proposal.md` contradicts itself here: line 90
invokes bare `uv`, line 129 invokes `.venv/bin/uv`, which these instructions never create.
Use whichever `uv` you actually installed, consistently.

---

## 4. The two Postgres roles, created by hand

**Read `docker/initdb/10-two-roles.sql` before you run any of it anywhere.** That file is a
local development artefact. It carries a hardcoded password (`CREATE ROLE hbd_app WITH LOGIN
PASSWORD 'hbd_app'`, :35), it runs exactly once — on an empty Docker volume, by the
`postgres:16-alpine` entrypoint — and its own header says so in capitals: "THE PASSWORD BELOW
IS A LOCAL DEVELOPMENT PASSWORD… In staging or production, create these two roles by hand
with real secrets and put the two DSNs in your secret store."

Nothing in this repository creates production roles. This is the step.

> **Do not run that file against the production database — and the proposal tells you to.**
> `deploy/first-install-proposal.md:99` is `sudo -u postgres psql -d hbd -f /srv/hbd/docker/initdb/10-two-roles.sql`
> with the comment `# grants only — read it first`. It is not grants only. Line 35 of that
> file is `CREATE ROLE hbd_app WITH LOGIN PASSWORD 'hbd_app' NOSUPERUSER NOCREATEDB
> NOCREATEROLE;`, so an operator who follows the proposal verbatim creates the production
> application role with the literal string `hbd_app` as its password — and, because the role
> already exists by then, in a way the rest of the proposal never revisits. Of everything in
> `deploy/first-install-proposal.md` that does not do what it claims, this is the one that matters. Transcribe
> the grants by hand, as below, or edit the file before it goes anywhere near a real server.

```bash
sudo -u postgres psql <<'SQL'
CREATE ROLE hbd     LOGIN PASSWORD '<owner-password>';
CREATE ROLE hbd_app LOGIN PASSWORD '<app-password>' NOSUPERUSER NOCREATEDB NOCREATEROLE;
CREATE DATABASE hbd OWNER hbd ENCODING 'UTF8' LC_COLLATE 'C' LC_CTYPE 'C' TEMPLATE template0;
SQL

sudo -u postgres psql -d hbd <<'SQL'
GRANT CONNECT ON DATABASE hbd TO hbd_app;
GRANT USAGE ON SCHEMA public TO hbd_app;

-- Future tables. Without these, every table a later migration creates is invisible to
-- hbd_app and the bot fails its first query with "permission denied".
ALTER DEFAULT PRIVILEGES FOR ROLE hbd IN SCHEMA public
    GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO hbd_app;
ALTER DEFAULT PRIVILEGES FOR ROLE hbd IN SCHEMA public
    GRANT USAGE, SELECT ON SEQUENCES TO hbd_app;

-- Anything that already exists (nothing, on a fresh database).
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO hbd_app;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO hbd_app;

REVOKE CREATE ON SCHEMA public FROM PUBLIC;
REVOKE CREATE ON SCHEMA public FROM hbd_app;
SQL
```

Those grants are the development file's, transcribed with the development password removed —
`docker/initdb/10-two-roles.sql:41-64`. The `LC_COLLATE 'C'` matches
`POSTGRES_INITDB_ARGS: "--encoding=UTF8 --locale=C"` in `docker-compose.yml`, which exists so
`ORDER BY` on Uzbek and Russian text is deterministic.

**Why two roles.** `hbd` owns every table, so it is the table owner. An owner can `GRANT`
back anything revoked from it in one statement, so migration 0007's

```sql
REVOKE UPDATE, DELETE, TRUNCATE ON TABLE public.admin_audit_log FROM "hbd_app"
```

(migrations/versions/20260830_1000_0007_add_admin_audit_log.py:369) is not a control at all
when the application connects as the owner — and with one role there is nobody to revoke it
*from*. Migrations run as `hbd`; the bot, the worker and the admin API all connect as
`hbd_app`. That split is the only control in the schema that survives a compromised
application credential; everything else in the audit design is an HMAC that the same
credential could recompute if it could write.

> **Do NOT copy the admin DSN from the example file.** `.env.admin.example:48` ships
> `postgresql+asyncpg://hbd:hbd@…` — the **owner** — while `.env.example:35` correctly ships
> `hbd_app`. The admin API is the process that writes `admin_audit_log`. Point it at the
> owner role and the REVOKE constrains nothing, even on a deployment where the REVOKE landed.
> Nothing in `src/hbd/admin/settings.py` validates which role the DSN names.

> **There is deliberately no blanket `GRANT EXECUTE ON FUNCTIONS`.** It used to be in the
> initdb file and was removed: a blanket default makes every future `SECURITY DEFINER`
> function automatically callable by the application role, which is the opposite of what such
> a function is for. Migration 0007 grants `EXECUTE` on exactly the two sweep functions by
> name (`_apply_revoke`, :363-378), and neither takes a caller-supplied cutoff — so the grant
> is the right to delete rows already past their own `expires_at`, never the right to delete
> rows the caller names.

Verify:

```bash
sudo -u postgres psql -d hbd -c '\du'                     # both roles, hbd_app not superuser
sudo -u postgres psql -d hbd -c '\ddp'                    # the two ALTER DEFAULT PRIVILEGES lines
```

---

## 5. Redis, with persistence

Redis is a **hard** dependency of both the bot and the worker in production, not just the
worker. In prod the bot cannot take the in-process fallback: `InProcessOrderSubmitter`
refuses to construct when `is_production` (src/hbd/runtime/submitter.py:100-105), so
`build_submitter` takes the `create_pool(...)` branch (src/hbd/main.py:94) with nothing behind
it. The bot then opens Redis twice more, for the aiogram FSM storage and the per-chat event
isolation (src/hbd/main.py:103, :166-168 → src/hbd/bot/app.py:83, :97).

**Turn persistence on.** The development stack runs
`redis-server --appendonly yes --save 60 1` with a named volume
(`docker-compose.yml`, and the comment says why: "appendonly keeps FSM state and the
idempotency set across a restart"). That is a fact about the local stack only — the equivalent
must be configured on a provisioned host:

```
# /etc/redis/redis.conf
appendonly yes
save 60 1
```

**Why persistence is not optional here.** Redis is not a disposable cache in this product. It
holds the only copy of every in-progress wizard draft — recipient name, free-text note, the
full approved lyric — under a 14-day TTL deliberately matched to the abandoned-draft
retention clock (src/hbd/bot/app.py:44-48, :83-85). It also holds the ARQ queue and job
results, the admin session mirrors (`hbd:admin:session`), the rate-limit and reveal-budget
counters (`hbd:admin:rl`, `hbd:admin:budget`) and the asset reveal window.

Losing Redis loses every queued and in-flight generation job and parks every customer
mid-wizard. It does **not** lose money state: open credit debits are closed by
`settle_stale_debits`, which runs inside the hourly purge transaction
(src/hbd/db/credit_settlement.py:203-222, called at src/hbd/db/purge.py:376-378). That is what
makes a Redis loss a support incident rather than a financial one.

> **A Redis outage and an operator lockout are the same event.** The admin limiters fail
> **closed** — "When Redis is unreachable the answer is 'denied', not 'allowed'"
> (src/hbd/admin/security/ratelimit.py:22-27) — while the bot's inbound gate fails **open**
> (src/hbd/bot/gate.py:44-47). That asymmetry is deliberate, but it means nobody can sign in
> to the panel during a Redis incident, including the operator who needs to revoke sessions.

> **`HBD_REDIS_URL` defaults to `redis://localhost:6379/0`** (src/hbd/config.py:188), so a
> worker with a mistyped or missing Redis URL connects to a *local* Redis rather than failing.
> The queue then looks empty instead of broken.

Verify:

```bash
redis-cli ping                                   # PONG
redis-cli config get appendonly save
```

---

## 6. The dotenv files, and their modes

Two files, one per process group. The split by process is older and more important than the
split by environment: there is no field on `AdminSettings` that could hold a vendor
credential, and pointing the panel at the bot's file would hand it all five keys by accident.

```
/etc/hbd/bot.env     0640 root:hbd   bot token + vendor keys + both DSNs
/etc/hbd/admin.env   0640 root:hbd   NO vendor credential, ever
```

```bash
sudo cp /srv/hbd/.env.example       /etc/hbd/bot.env
sudo cp /srv/hbd/.env.admin.example /etc/hbd/admin.env
sudo chown root:hbd /etc/hbd/*.env
sudo chmod 0640 /etc/hbd/*.env
sudoedit /etc/hbd/bot.env
sudoedit /etc/hbd/admin.env
```

Paths and modes are the deploy proposal's (deploy/first-install-proposal.md:63-64); the code accepts any path
through `HBD_ENV_FILE` / `HBD_ADMIN_ENV_FILE`, defaulting to `.env` and `.env.admin`
(src/hbd/config.py:84-97, src/hbd/admin/settings.py:75-81).

### `.env.admin.example` cannot be copied and booted. Fix nine lines.

This is not a prediction. Building `AdminSettings` against the file verbatim produces nine
simultaneous refusals:

```
$ HBD_ADMIN_ENV_FILE=.env.admin.example .venv/bin/python -c \
    "from hbd.admin.settings import build_admin_settings; build_admin_settings()"
The admin panel's configuration is invalid or incomplete. Fix these environment variables:
  HBD_ADMIN_COOKIE_SECURE: Input should be a valid boolean, unable to interpret input
  HBD_ADMIN_TRUSTED_PROXY_CIDRS: contains an unparsable entry: '# comma-separated'
  HBD_ADMIN_AUDIT_HMAC_KEY: Value should have at least 32 items after validation, not 0
  HBD_ADMIN_NAME_MATCH_MIN_SIMILARITY: Input should be a valid number
  HBD_ADMIN_SETTLEMENT_GRACE_S: Input should be a valid integer
  HBD_ADMIN_UZS_PER_USD: Input should be a valid number
  HBD_ADMIN_UZS_PER_USD_AS_OF: Input should be a valid date or datetime
  HBD_ADMIN_SINGLE_SONG_PRICE_MINOR: Input should be a valid integer
  HBD_ADMIN_KIT_CURRENCY: String should have at most 3 characters
```

Seven of those are one formatting bug. `python-dotenv` strips an inline `#` comment only when
the value before it is non-empty, so a line like

```
HBD_ADMIN_UZS_PER_USD=                    # soʻm per USD, e.g. 12800. Blank = no rate published
```

(.env.admin.example:216) parses with the *comment* as its value. The seven affected lines are
:114, :155, :171, :216, :217, :235 and :236 — every one of them a variable whose own comment
tells the operator to leave it blank. `_blank_mirror_means_unpublished`
(src/hbd/admin/settings.py:433-465) exists solely to make this file work and says so at :449:
"The example file ships the variables blank, so this is the path an untouched deployment
actually takes." It is not the path — the values are never blank as parsed, so that validator
never fires.

The eighth, `HBD_ADMIN_COOKIE_SECURE=` (.env.admin.example:92), is genuinely blank and is a
separate failure: the field is `bool | None` (src/hbd/admin/settings.py:197) and pydantic
cannot read an empty string as either.

**Fix:** move each of those comments onto its own line above the variable, and delete the
`HBD_ADMIN_COOKIE_SECURE=` line entirely (its default is `None`, which is what the file's own
"Leave empty" instruction meant). The ninth,
`HBD_ADMIN_AUDIT_HMAC_KEY`, is not a bug — it is required and has no default to forget to
change.

### What must actually be set

**Bot and worker — four required variables, in every environment:** `HBD_DATABASE_URL`
(src/hbd/config.py:187) plus `HBD_TELEGRAM_BOT_TOKEN`, `HBD_ELEVENLABS_API_KEY` and
`HBD_LLM_API_KEY`, made required by the `_VendorBoundSettings` subclass
(src/hbd/config.py:697-699) that `load_settings()` always selects. Everything else defaults.
Also set here: `HBD_ENVIRONMENT=prod`, `HBD_USE_FAKE_PROVIDERS=false`, `HBD_REDIS_URL`, and
`HBD_DB_MIGRATION_URL` — the owner DSN, which lives in the bot's file because
`migrations/env.py` reads it from there and neither long-running process has a field for it.

**Admin — two required, plus two non-defaults:** `HBD_DATABASE_URL`
(src/hbd/admin/settings.py:174, the **`hbd_app`** DSN), `HBD_ADMIN_AUDIT_HMAC_KEY` (:229, a
`SecretStr` with `min_length=32`), `HBD_ADMIN_ENABLED=true` — the default is `false`
(:180) and the lifespan refuses to boot without it (src/hbd/admin/app.py:206-208, 315) — and
`HBD_ADMIN_AUDIT_DSN`, the owner DSN (:235, `default=""`).

> **`HBD_ADMIN_AUDIT_DSN` is never dialled, and §12's acceptance check still fails without
> it.** The admin process never connects with this value; it reads it as a boolean. `/audit/verify`
> passes `is_dsn_configured=bool(settings.admin_audit_dsn)` (src/hbd/admin/routers/audit.py:168)
> and `resolve_chain_protection` returns `HMAC_ONLY` immediately when that is false, before it
> asks Postgres anything (src/hbd/db/admin/audit.py:765-766). So the variable is the
> deployment's *declaration* that the two-role split exists. Leave it out of `admin.env` and
> a host whose §7 REVOKE landed perfectly still reports `chainProtection: "hmac-only"`, and
> the §12 row and the §13 question that both rest on that field will read as a failure.
> (The proposal does say to set it — deploy/first-install-proposal.md:109.) It is separately required in the
> *migration* shell for a different reason; see §7.

```bash
python -c "import secrets; print(secrets.token_urlsafe(48))"   # HBD_ADMIN_AUDIT_HMAC_KEY
```

> **`HBD_ADMIN_PUBLIC_ORIGIN` must be edited, not inherited.** The prod guard tests whether
> the variable was *set*, not whether it is plausible: `"admin_public_origin" not in
> self.model_fields_set` (src/hbd/admin/settings.py:578-581). A dotenv value counts as set —
> and the example file ships it uncommented at the loopback dev value
> (`http://127.0.0.1:8080`, .env.admin.example:73). Copy the file to a prod host and the
> guard is disarmed, producing exactly the incident its own comment predicts at :582-587:
> the panel boots, passes `/healthz`, serves a login page, and then rejects every mutation
> with `ORIGIN_REJECTED`. Set it to the `https://` origin a browser actually types.

> **`HBD_ENVIRONMENT` is spelled `prod` and nothing checks your spelling.** On the bot and
> worker it is an unvalidated free-form `str` (src/hbd/config.py:170) and every production
> refusal is `self.environment == "prod"` (:685-686). `production` or `PROD` silently
> permits fake providers (src/hbd/runtime/providers.py:104-108) and the in-process submitter
> (src/hbd/runtime/submitter.py:100-105), with no error anywhere. `AdminSettings` closes the
> same field to a `Literal` (src/hbd/admin/settings.py:169) precisely because "a typo like
> `production` would silently downgrade the strongest boot control in the package" (:15-18) —
> that argument was never applied to `Settings`.

> **The two files never cross-check each other.** Five variables are owned by both classes —
> `HBD_ENVIRONMENT`, `HBD_LOG_LEVEL`, `HBD_IS_DEBUG`, `HBD_DATABASE_URL`, `HBD_REDIS_URL` —
> and both classes use `extra="ignore"` (src/hbd/config.py:165,
> src/hbd/admin/settings.py:164), so each file silently swallows the other's variables and a
> typo'd `HBD_` name is a no-op with no error. `prod` in the bot's file and `dev` left in the
> admin's is a completely legal, silent state in which the panel permits DEBUG logging,
> permits the loopback origin, and downgrades the vendor-credential refusal to a warning
> (src/hbd/admin/app.py:198-201).

> **A mistyped `HBD_ENV_FILE` reads no file and the error never says so.** `resolve_env_file`
> falls back to the default when the variable is blank (src/hbd/config.py:85-92), and a path
> that does not exist yields an empty parse with no exception. The failure message hardcodes
> "see `.env.example`" (src/hbd/config.py:702-704) rather than naming the file that was
> actually read, and `env_file()` is logged only *after* settings build successfully. If the
> four required variables happen to be exported, the bot boots on 100% defaults — including
> `HBD_ENVIRONMENT=dev`.

**Never on the admin host:** `HBD_TELEGRAM_BOT_TOKEN`, `HBD_ELEVENLABS_API_KEY`,
`HBD_LLM_API_KEY`, `HBD_LLM_FALLBACK_API_KEY`, `HBD_OPENROUTER_MANAGEMENT_KEY`. That list is
derived, never restated —
`FORBIDDEN_ENV_VARS` is built from `hbd.config.VENDOR_SECRET_FIELDS`
(src/hbd/admin/app.py:116-118; src/hbd/config.py:111-116). In prod the lifespan refuses to
boot when any of them is in reach, in the environment or in the admin dotenv file
(src/hbd/admin/app.py:186-199). Outside prod it is a warning
(`admin.boot.vendor_env_present`, :200-203).

Verify:

```bash
sudo stat -c '%a %U:%G %n' /etc/hbd/*.env        # 640 root:hbd
sudo -u hbd cat /etc/hbd/bot.env >/dev/null      # the service user can read it
sudo -u hbd env HBD_ADMIN_ENV_FILE=/etc/hbd/admin.env /srv/hbd/.venv/bin/python -c \
  'from hbd.admin.settings import build_admin_settings as b; s=b(); print(s.environment, s.admin_enabled)'
```

> **`env` is doing real work in that line, and the proposal drops it.** With default sudoers
> (`env_reset`, no `setenv` tag) a variable assignment written directly after `sudo` matches
> neither `env_keep` nor `env_check` and sudo aborts with "sorry, you are not allowed to set
> the following environment variables: HBD_ADMIN_ENV_FILE" — a refusal that reads like a
> permission problem with the env file rather than with sudo. `deploy/first-install-proposal.md:112` and
> `:114` are both written in that broken shape. Interpose `env`, as §7 and §9 do.

---

## 7. The schema, as the owner role

```bash
sudo -u hbd env \
  HBD_ENV_FILE=/etc/hbd/bot.env \
  HBD_ADMIN_AUDIT_DSN=two-role \
  HBD_DB_APP_ROLE=hbd_app \
  sh -c 'cd /srv/hbd && .venv/bin/python -m alembic -c migrations/alembic.ini upgrade head'
```

> **No password belongs on that command line, and none is needed there.** Anything in the
> argv of `env` is readable in `ps` by every user on the host and lands in the invoking
> shell's history — the same exposure §9's `--password` refusal exists to prevent. Neither
> secret is required: migration 0007 tests `HBD_ADMIN_AUDIT_DSN` for non-emptiness only and
> never parses or dials it (`if not os.environ.get(_AUDIT_DSN_ENV, "").strip():`, 0007:336),
> so any non-empty marker takes the same branch; and with `HBD_DB_APP_ROLE` set explicitly,
> `_app_role()` returns before it ever looks at `HBD_DATABASE_URL` (0007:314-322). The
> connection itself comes from `HBD_DB_MIGRATION_URL` inside `/etc/hbd/bot.env`, which
> `_owner_url()` reads from the dotenv file (migrations/env.py:95-113) — a 0640 root:hbd
> file, not a process argument. If your own tooling prefers a real DSN in
> `HBD_ADMIN_AUDIT_DSN`, put it in a file the shell sources, never in argv.

**Those two exported variables are the point of this section, and the deploy proposal omits
both.** The chain is 0001 → 0021, linear, no branches
(`migrations/versions/20260827_0900_0001_initial_schema.py:35-36` through
`20260908_1200_0021_add_dashboard_read_indexes.py:93-94`).

`migrations/env.py` gets the connection right on its own: `_owner_url()` reads
`HBD_DB_MIGRATION_URL` from the environment **and then falls back to the dotenv file**
(migrations/env.py:95-113), with :14-19 explaining that the environment-only version was a
bug that would have migrated production as the wrong role. Unset, it falls back to the
application DSN with a named WARNING (:117-129, :89-93).

Migration 0007 has the bug that `env.py` was fixed for. `_install_two_role_controls` gates on
`os.environ.get(_AUDIT_DSN_ENV, "")` with no dotenv fallback (0007:336), and `_app_role()`
reads `HBD_DB_APP_ROLE` then a username out of `HBD_DATABASE_URL`, both from `os.environ`
only (0007:314-322). Migration 0011 repeats the same pattern. But
`HBD_ADMIN_AUDIT_DSN` is documented to live in `.env.admin` (.env.admin.example:130,
README.md:172-174) — a file the migration runner never loads — and `HBD_DB_APP_ROLE` appears
in **neither** example file.

> **Follow `deploy/first-install-proposal.md:112` verbatim and the REVOKE never runs.** That command exports
> only `HBD_ENV_FILE`. `_install_two_role_controls` then takes its first `_skip` branch,
> logging "REVOKE skipped: HBD_ADMIN_AUDIT_DSN is not set" as a WARNING rather than a failure
> (0007:325-338), and neither the REVOKE nor the two `SECURITY DEFINER` sweep functions are
> ever created. The migration succeeds. The audit log's append-only property is then the HMAC
> alone. Export the variables above into the migrate shell — that is exactly what
> `tests/test_db/test_audit_purge_privileges.py:62,71` does, which is why the test suite
> passes while the documented path does not.

0007 has four more preconditions and each logs why it skipped: the role must exist in
`pg_roles` (0007:350-352), the role name must match `^[A-Za-z_][A-Za-z0-9_$]{0,62}$` — a bad
one raises rather than skips (:343-348) — and `current_user` must not *be* the application
role, because "a REVOKE from it is reversible by it" (:354-356).

Verify — and this is the one check that cannot be faked, because it asks Postgres rather than
reading configuration:

```bash
sudo -u postgres psql -d hbd -c '\dp admin_audit_log'      # hbd_app must have r/a, not w/d/D
sudo -u postgres psql -d hbd -c '\df public.hbd_purge_audit_*'              # both, one pattern
sudo -u postgres psql -d hbd -c 'SELECT version_num FROM alembic_version'   # 0021
```

Two rows come back from that `\df`: `hbd_purge_audit_log(integer)` and
`hbd_purge_audit_reasons(integer)` (0007:75-82). **Do not write the two names as two words.**
Since PostgreSQL 14 the signature is `\df [pattern [arg_pattern ...]]` — the second word is
matched against the function's *argument* types, not against a second function name — so
`\df public.hbd_purge_audit_log public.hbd_purge_audit_reasons` asks a postgresql-16 server
for functions named `hbd_purge_audit_log` whose first argument is of type
`public.hbd_purge_audit_reasons`, and returns zero rows on a perfectly provisioned host. Both
functions take `(integer)`.

The in-product answer is `GET /api/audit/verify`'s `chainProtection` field. It runs
`has_table_privilege(current_user, 'admin_audit_log', 'UPDATE'/'DELETE'/'TRUNCATE')` against
the admin process's own connection and returns `hmac-only` — with a WARNING,
`admin.audit.revoke_missing` — whenever the answer is yes
(src/hbd/db/admin/audit.py:746-780). `hmac-only` is also what it reports when
`HBD_ADMIN_AUDIT_DSN` is unset, when the backend is not Postgres, and when the probe errors.
A control that is not deployed is reported as not deployed, never implied.

---

## 8. The admin console build

```bash
sudo -u hbd sh -c 'cd /srv/hbd/admin-ui && npm ci && npm run build'
```

**Node has to come from somewhere.** `admin-ui/package.json` declares `"node": ">=20.19"` and
`admin-ui/package-lock.json` is `lockfileVersion: 3` (npm 7+). The deploy proposal builds with
npm on a host it never installs Node on (deploy/first-install-proposal.md:89 vs :113) — install a Node 20.19+
before this step and pin the version somewhere you will remember.

**The build writes into the Python package tree and wipes it first.**
`admin-ui/vite.config.ts:106-107` sets `outDir: "../src/hbd/admin/static"` with
`emptyOutDir: true`, and that directory is gitignored (stated at src/hbd/admin/app.py:124-128).

> **An unbuilt console does not look like a build problem.** With no `index.html`, the SPA
> catch-all raises a 404 (src/hbd/admin/app.py:238-239) and the static mount is declared with
> `check_dir=False` (:298) so the app still starts. `/healthz` answers 200, `/api` answers
> normally, and every browser URL 404s. Nothing at the process level distinguishes that from
> a healthy deployment.

> **A *stale* console looks like a working panel.** The shell is a one-substitution template:
> `render_shell` replaces `__HBD_CSP_NONCE__` (src/hbd/admin/shell.py:55, 65-86;
> `admin-ui/index.html:28`) with this response's style nonce. A bundle built before that
> placeholder existed is served unchanged with one WARNING per response,
> `admin.spa.nonce_placeholder_missing` (shell.py:78-85) — deliberately, rather than a 500.
> The only visible symptom is that modal scroll-lock stops working, because
> `react-remove-scroll` injects a real `<style>` element that `style-src 'self' 'nonce-…'`
> then blocks. This is why the rebuild is mandatory on **every** deploy, not only the first.

Nothing gates this. The Python suite checks the *source* `admin-ui/index.html`, not the built
one (tests/test_admin/test_spa_nonce.py:49), and `make ui-e2e` rebuilds before it runs
(Makefile:112) — so the placeholder-drift check exists and the staleness check does not.
There is no CI in this repository at all; `make check` is `lint typecheck cov` (Makefile:144)
and reaches neither `ui-check` nor `ui-e2e`.

Verify:

```bash
grep -c __HBD_CSP_NONCE__ /srv/hbd/src/hbd/admin/static/index.html    # 1
ls /srv/hbd/src/hbd/admin/static/assets | head
```

> **Consider stripping the source maps.** `admin-ui/vite.config.ts:125` sets
> `sourcemap: true`, so the console's complete TypeScript source ships in the bundle and is
> served from `/assets` (src/hbd/admin/app.py:296-300) by a middleware stack that
> authenticates nothing (:387-390), stamped `public, max-age=31536000, immutable`
> (src/hbd/admin/middleware/security_headers.py:82, 85). Anyone who can reach the panel's
> origin can download them unauthenticated, and a year-immutable cache means removing them
> later does not un-cache them.

---

## 9. The first OWNER

There is no signup route. The only way an account comes into existence is this command:

```bash
sudo -u hbd env HBD_ADMIN_ENV_FILE=/etc/hbd/admin.env \
  sh -c 'cd /srv/hbd && .venv/bin/python -m hbd.admin.bootstrap --username owner'
```

It prompts twice on the TTY via `getpass` and echoes nothing.

**`--password` on argv is refused, deliberately.** The flag is registered with
`help=argparse.SUPPRESS` purely so it can be rejected with an explanation
(src/hbd/admin/bootstrap.py:100-121, refusal text at :80-84, raised at :302-306): a password
in argv is visible in `ps` to every user on the host and lands in shell history. For an
unattended install, use `--password-file`, which is refused unless the file has no group or
other permission bit at all — `mode & 0o077` must be zero, i.e. 0600 or stricter — because a
group-*writable* file can be replaced before it is read (:76-78, :124-134). The refusal names
the actual mode.

**Password rules are length only:** 8 to 256 characters, no composition rule, no blocklist
(src/hbd/admin/bootstrap.py:146-152; `MIN_PASSWORD_CHARS = 8` at
src/hbd/admin/schemas/common.py:31-38, lowered from 12 by a product decision on 2026-09-04).
That comment says what carries the weight instead: "At 8 the argon2 parameters are doing most
of the work against a leaked hash, so keep `HBD_ADMIN_ARGON2_MEMORY_KIB` high and leave the
login throttle in place." Those two are load-bearing controls, not tunables.

Both bootstrap paths set `must_change_password=True`
(src/hbd/db/admin/accounts.py:171-182), so the first session is gated to
`/api/auth/password` and `/api/auth/me` and nothing else
(`PASSWORD_GATE_EXEMPT_PATHS`, src/hbd/admin/deps.py:116). `/auth/logout` is deliberately not
exempt — a first-boot
operator drops the cookie instead.

The audit row is written in the same transaction as the account, with `actor_id=NULL` and
`actor_username="system:bootstrap"` (src/hbd/admin/bootstrap.py:239-271). That string is the
exact grep for every out-of-band ownership event, and a login by an account literally named
"bootstrap" cannot collide with it.

**Exit codes are a three-way contract** an install script can branch on without parsing
English: 0 success, 1 operator refusal (bad input, race, already bootstrapped), 2
configuration error (src/hbd/admin/bootstrap.py:72-74, :319-343). Nothing ever prints a
traceback, because a traceback here would carry the DSN.

> **Recovery is only for the fully-locked-out case.** `--reset-owner` is refused while *any*
> active OWNER exists (src/hbd/admin/bootstrap.py:178-191). If an OWNER row exists but nobody
> can sign in — locked out by the login throttle, say — the row must be deactivated in the
> database first. No document in this repository describes that step.

---

## 10. Process supervision

`deploy/systemd/hbd-bot.service`, `hbd-worker.service` and `hbd-admin.service` are the
**proposed** units, authored in this repository without host access. They are not confirmed
to be what `aizu` uses, or that `aizu` uses systemd at all.

```bash
sudo cp /srv/hbd/deploy/systemd/*.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now hbd-bot hbd-worker hbd-admin
```

What is worth keeping from them, and why:

**`Environment=HBD_ENV_FILE=/etc/hbd/bot.env`, not `EnvironmentFile=`**
(hbd-bot.service:27, hbd-worker.service:20, hbd-admin.service:29). `EnvironmentFile=` loads
every value into the process environment, where it is visible in `systemctl show` and in
`/proc/<pid>/environ`; naming the file instead means pydantic-settings reads the 0640 file
directly and the credentials never enter the environment. The absolute path is also what makes
a stray `.env` in `/srv/hbd` unreadable by accident. The corollary is real: process
environment beats the dotenv file for every variable on both settings classes, so any `HBD_*`
left exported in a deploy shell silently overrides the file the unit points at.

**`InaccessiblePaths=/etc/hbd/bot.env` on the admin unit** (hbd-admin.service:50). The
application-level vendor-credential refusal is a check the panel performs on itself; this one
is the kernel's, and it survives an edit that points `HBD_ADMIN_ENV_FILE` at the wrong file.

**`WorkingDirectory=/srv/hbd` on all three, and `ReadWritePaths=/srv/hbd/var`** on the bot and
worker (hbd-bot.service:26, :53). Under `ProtectSystem=strict` everything else is read-only.
This is what makes `Path.cwd() / "var"` resolve to the same tree for all three processes —
the agreement §2 says nothing in the code enforces. Note that `ReadWritePaths=` on a path
that does not exist fails the unit, and `build_container` creates `var/workspace` and
`var/archive` at every boot but only if `var` itself is writable.

**One correction to make if you adopt these files.** `hbd-worker.service:1-2` describes the
worker as performing "every operational action the admin panel queues". No such path exists
in this tree: a search across `src/hbd/admin` for `enqueue_job`, `create_pool` or `arq` finds
nothing, and the admin container holds only an engine, a session factory, Redis and rate
limits (src/hbd/admin/container.py:81-83, :142-151). Anyone reading that comment will look for
a queue that is not there.

> **Two things the units do not say.** First, the worker validates its entire configuration
> at module import (`_SETTINGS = _settings()`, src/hbd/worker.py:40), so a bad env produces an
> uncaught `ConfigError` traceback from the arq CLI on every restart attempt — the bot catches
> the same error and prints one line (src/hbd/main.py:213-218). A restart loop on the worker
> is noisy in a way the bot's is not. Second, four module-level `assert`s guard the
> enqueue-name ↔ function-name contract (src/hbd/runtime/jobs.py:786-788 and the three cron
> modules) and are erased under `python -O` or `PYTHONOPTIMIZE`. The proposed units do not use
> `-O`; nothing enforces that they never will.

> **Run exactly one worker replica unless you also change the vendor ceiling.** The music and
> TTS concurrency guards are per-process `asyncio.Semaphore`s
> (src/hbd/runtime/container.py:332-333) with `music_max_concurrency` defaulting to 2 —
> described at src/hbd/config.py:195-200 as "Vendor's simultaneous-render ceiling: 2 on
> Starter/Creator/Pro, 5 on Scale". Two replicas make four simultaneous renders against a
> vendor limit of 2. The guard is written as if one process exists.

> **Only the worker runs the crons**, and none of them runs at startup: the retention sweep
> hourly at :17, the vendor-balance poll hourly at :43, the activity snapshot daily at 00:07
> UTC, all `run_at_startup=False, unique=True, max_tries=1`
> (src/hbd/runtime/jobs.py:705-769). If the worker is down, retention stops — a stated legal
> obligation — the audit chain's HEAD anchor stops being re-pinned so tail deletions become
> undetectable while `/audit/verify` still reports `ok`, and the activity series accrues a
> permanent gap that nothing backfills. There is no way to trigger a retention sweep on
> demand: `POST /api/retention/run` is referenced in two docstrings and exists as no route.

**Connection budget.** The bot and the worker take `create_engine`'s defaults, 10 + 20
overflow each (src/hbd/db/engine.py:40-41). The admin API does not: `build_admin_container`
passes `pool_size=ADMIN_POOL_SIZE` / `max_overflow=ADMIN_MAX_OVERFLOW`, 5 + 5
(src/hbd/admin/container.py:53-54, used at :121-125). So three processes at the defaults is
30 + 30 + 10 = **70** connections against a stock `max_connections` of 100, leaving 30. The
docstring at engine.py:64-67 gives "3 × 30 = 90" as the counterfactual it *rejects* — "so the
API asks for a smaller share rather than everyone quietly sharing a cliff edge" — not as the
deployed number. Budget the remaining 30 for everything else on that server: a second worker
replica is another 30 and eats all of it, and a monitor or an open `psql` needs to fit too.

Verify:

```bash
systemctl status hbd-bot hbd-worker hbd-admin
journalctl -u hbd-bot   -n 50 | grep 'host verified'
journalctl -u hbd-admin -n 50 | grep 'admin.boot.ok'
```

> **`deploy/first-install-proposal.md:143` greps for the wrong string.** It runs
> `journalctl -u hbd-bot -n 20 | grep host_verified`. The log line's message is
> `"host verified"` with a space (src/hbd/runtime/startup.py:33-41) and it is not an `event`
> field — there is no `host_verified` token anywhere in the tree. An operator following that
> checklist sees an empty grep and may conclude the bot did not boot. Line 144's
> `admin.boot.ok` does work, because that one genuinely is an event field
> (src/hbd/admin/app.py:325).

---

## 11. TLS in front of the loopback admin API

The admin API binds loopback **only because the command line says so**. `HBD_ADMIN_HOST` and
`HBD_ADMIN_PORT` exist as settings (src/hbd/admin/settings.py:188-189) and are read by nothing
that binds a socket — their only consumers are the two projections onto `GET /api/config`
(src/hbd/admin/schemas/config_view.py:108-109, :202-203). The bind comes from
`--host 127.0.0.1 --port 8080` (Makefile:75, hbd-admin.service:30).

> **Changing `HBD_ADMIN_PORT` changes what the panel *displays*, not what it *binds*.** The
> settings comment at :186-189 ("Binding 0.0.0.0 publishes a password login to the internet")
> reads as though the field enforced the bind. It does not, and `/api/config` will keep
> rendering `adminHost: 127.0.0.1` to the operator checking, whatever the process is actually
> listening on. The bind flag belongs to whatever starts the process, and the panel's own
> config screen is not evidence about it.

The terminator in front of it must do five things:

1. **Terminate TLS**, and add `Strict-Transport-Security` itself. Nothing in this repository
   ever emits HSTS: `SECURITY_HEADERS` is exactly `x-content-type-options: nosniff`,
   `referrer-policy: no-referrer` and `cache-control: no-store`
   (src/hbd/admin/middleware/security_headers.py:73-77) plus a per-response CSP, and the CSP
   template contains no `upgrade-insecure-requests`. A first request to `http://` is upgraded
   by nothing the application controls.
2. **Serve the panel at the root of its own hostname.** Assets, the immutable-cache carve-out
   and the API prefix are all absolute — `IMMUTABLE_PATH_PREFIX = "/assets/"`
   (security_headers.py:82), `API_PREFIX = "/api"` (src/hbd/admin/deps.py:108) — and both
   cookies are `__Host-` prefixed (src/hbd/admin/csrf.py:48-49), which *requires*
   `Path=/` and so cannot be narrowed. Under a subpath mount the bundle 404s, the
   cache split lands on the wrong paths, and the cookies become visible to everything else on
   that origin.
3. **Pass `Origin` through unmodified.** The CSRF check is exact: `origin not in
   accepted_origins`, with an absent header a refusal (`ORIGIN_MISSING`, csrf.py:76-88), and
   outside dev `accepted_origins` is the single frozenset `{admin_public_origin}`
   (src/hbd/admin/settings.py:620-632). A proxy that rewrites or strips it produces a panel
   that logs in fine and then 403s every write, and the boot guard cannot catch it because it
   tests only whether the variable was set.
4. **Be the only reachable name.** Every additional hostname, port or scheme — a bare IP, a
   `www.` variant — 403s every state-changing request, and only at the first mutation.
5. **Append, not replace, `X-Forwarded-For`** — and then tell the panel about itself.

`deploy/first-install-proposal.md:56` names "Caddy or nginx" as a suggestion. The repository expresses no
preference and contains no proxy configuration.

### The proxy setting that is silently off by default

```
HBD_ADMIN_TRUSTED_PROXY_HOPS=1                # the exact count of proxies YOU control
HBD_ADMIN_TRUSTED_PROXY_CIDRS=127.0.0.1/32    # the addresses those proxies connect from
```

`resolve_client_ip` ignores `X-Forwarded-For` entirely unless **both** `hops > 0` **and** the
peer is inside a configured CIDR (src/hbd/admin/security/clientip.py:142). The shipped
defaults are `0` and empty (src/hbd/admin/settings.py:216-217), and the example file ships
them that way too.

With the defaults, every request behind a reverse proxy resolves to the proxy's own address.
The strict login counter is keyed `(username, ip)` at 10 attempts per 900 seconds
(`LOGIN_MAX_PER_USER_IP`, src/hbd/admin/security/ratelimit.py:117; `check_login_rate_limit`
at :414-448 via `_user_ip_key`, :309), so a collapsed IP turns it into a
single global bucket per username — the exact shape the module's own header calls out at
:9-13: it "hands anyone who knows an operator's username a permanent 429 against that account,
at exactly the moment during an incident when the operator needs to log in". The same collapse
writes the proxy's address into `admin_audit_log.ip` for every row and into
`admin_sessions.last_ip`, so the audit log's only network evidence becomes a constant.

Nothing validates hops against reality — too high believes an attacker-written entry, too low
believes an inner proxy — and nothing surfaces the value at boot: `admin.boot.ok` logs
`environment`, `env_file`, `is_cookie_secure` and `public_origin`, and neither proxy setting
(src/hbd/admin/app.py:322-333). The parser itself is properly hostile to its input — a 32-entry
cap, the believed entry counted from the right, an unparsable entry falling back to the peer
rather than a neighbour (clientip.py:45, 105-107, 144-149) — so where the configuration is
right, the control is sound. A CIDR typo fails the boot and names the variable
(src/hbd/admin/settings.py:486-499).

### Set a probe token, or nothing can observe this deployment

```
HBD_ADMIN_PROBE_TOKEN=<a long random string>
```

There are exactly two health endpoints in the tree, both on the admin API, and neither the bot
nor the worker exposes any HTTP probe at all — supervision of those two can only be
process-level.

`GET /healthz` is liveness: a bare 200 with an empty body that touches nothing
(src/hbd/admin/routers/health.py:121-124). It learns nothing about Postgres or Redis, and it
answers even when the lifespan-built container is absent — so a naive liveness probe reports a
process that can serve nothing as healthy.

`GET /readyz` is where the detail is, and **unauthenticated it returns the constant
`{"status":"ok"}` even when the database and Redis are both down**
(health.py:53-56, :126-131). Detail requires either a live operator session or an
`X-Probe-Token` header matching `HBD_ADMIN_PROBE_TOKEN` under `secrets.compare_digest`
(:93-105, tried first so it still works when the database is the thing that is down). The
default is empty and authorises nobody (src/hbd/admin/settings.py:428).

> **A monitor pointed at `/readyz` without the token will never remove a broken instance.**
> There is no default token to forget to change, which is the right shape — but there is also
> no monitoring path at all until one is set. Note the field has no `min_length`, unlike
> `admin_audit_hmac_key`'s 32: a one-character token passes every check. Length here is
> operator discipline, not a validated bound.

`configVersion` in that body is always `null` on this tree — nothing writes the Redis key
`hbd:settings:version` (health.py:50-51, :74; the config editor that would write it is a later
phase). A null there means "nobody has published one", not "Redis is broken".

Verify:

```bash
curl -sS -o /dev/null -w '%{http_code}\n' https://<panel host>/healthz
curl -sS -H "X-Probe-Token: <token>" https://<panel host>/readyz
curl -sSI https://<panel host>/ | grep -i 'strict-transport\|content-security-policy'
```

---

## 12. What "provisioned" looks like

Everything above, observed rather than assumed:

| claim | how you know |
| --- | --- |
| ffmpeg can do the job | `ffmpeg -hide_banner -encoders \| grep -E 'libopus\|libmp3lame'` — both present |
| the bot booted against the right config | `journalctl -u hbd-bot \| grep 'host verified'` → `environment=prod`, `env_file=/etc/hbd/bot.env` |
| the panel booted against the right config | `journalctl -u hbd-admin \| grep admin.boot.ok` → same pair, `is_cookie_secure=true`, the real `public_origin` |
| no vendor key is on the admin host | `journalctl -u hbd-admin \| grep admin.boot.vendor_env_present` is empty — in prod it is a refusal, so a *running* prod panel already proves it |
| the console bundle is current | `grep -c __HBD_CSP_NONCE__ .../static/index.html` = 1, and no `admin.spa.nonce_placeholder_missing` in the journal |
| the schema is at head | `SELECT version_num FROM alembic_version` → `0021` |
| the two-role split is real | `\dp admin_audit_log` shows no `w`/`d`/`D` for `hbd_app`, and `/api/audit/verify` reports `chainProtection` as something other than `hmac-only` |
| the audit chain is intact | the same call's `ok: true` **and** `isComplete: true` — the walk stops at 50 000 rows in batches of 500 (src/hbd/db/admin/audit.py:129, :132, and `is_ceiling_reached` at :647-654), so `ok` alone is not a verified whole chain |
| the crons are running | rows in `purge_runs`: check `ran_at`, `is_batch_full`, and whether `storage_keys_returned` exceeds `storage_keys_deleted` |
| the data roots agree | open a delivered asset in the panel; a 404 with the row present is the symptom |
| a monitor can see failure | `/readyz` with the probe token returns `database`, `redis`, `configVersion` |

Two things are worth saying plainly because nothing in the repository will say them for you.

**Logs are the only signal for several controls.** Every process emits one JSON object per
line whenever `HBD_IS_DEBUG` is false (src/hbd/logging.py:230-243) — the level does not change
the format, so turning on debug to get more detail silently switches the whole stream to
unparseable plain text. The envelope is `ts`, `level`, `logger`, `message`, `correlation_id`
plus `context`; the event name, where there is one, lives *inside* `context`, so a query must
be `context.event` rather than a top-level field. Only the admin subsystem emits named events
at all — the bot, worker and pipeline log English prose. The two that should page are
`admin.audit.chain_broken` and `admin.audit.revoke_missing`. And the audit write path can
never fail a request (src/hbd/admin/audit_sink.py:99-135), so an audit outage is invisible to
the client and visible only as `admin.audit.write_failed` in the journal. If the journal is
shipped nowhere, the audit log can stop being written to without anyone learning.

**Nothing in this repository backs anything up.** No `pg_dump`, no snapshot script, no backup
step in the deploy proposal — the only occurrence of "backup" anywhere under `src/` is
src/hbd/pipeline/assets.py:391, where it means a fallback vendor.

**The requirement exists; only the implementation is missing.** `docs/product/SCOPE_OF_WORK.md:716`
(**ENV-6, MUST**) is "Nightly Postgres backup with PITR, 30-day retention, and **a restore
drill executed and documented before launch**", and `:721` (**ENV-11, MUST**) specifies a
five-step tested post-restore reconciliation — ledger and payments reconciled against each
rail across the restore gap, Redis dedup sets rebuilt, already-delivered orders suppressed,
`reminders.next_fire_at` recomputed, and a report published — with `:722` (ENV-12) requiring
the drill twice a year. So this is not an unstated requirement; it is a stated MUST that no
code, script or deploy step in this checkout implements. Treat the list below as what that
MUST has to cover — four things, three of which are not the database:

1. **Postgres** — 22 tables, including `credit_ledger`, `plan_purchases` and `topup_purchases`,
   which migration 0020's docstring calls receipts that answer disputes "months after the
   recipient's name, the note and the audio are lawfully gone".
2. **`var/archive`** — the delivered audio and every customer avatar, in one tree.
3. **Redis** — the only copy of every in-progress wizard draft and of the queue.
4. **`HBD_ADMIN_AUDIT_HMAC_KEY`** — which lives in the admin env file and nowhere else. The
   chain is `HMAC-SHA256(key, "v1" ‖ prev_hmac ‖ canonical_json(row))`
   (`CHAIN_VERSION` at src/hbd/db/admin/audit.py:111, the MAC input built at :396) with **no
   key identifier anywhere on the row** — `AdminAuditRow` (src/hbd/db/models/admin_audit.py:115)
   carries `chain_hmac` and `prev_hmac` (:193-197) and no key-id or key-version column at all.
   Rotate or lose that key and `/audit/verify`
   reports a break at seq 1 for the rest of the log's 730-day life, indistinguishable from
   tampering. There is no rotation path in the code.

> A database-only restore comes back with an audit log nobody can verify, rows pointing at
> archive objects that are gone, and no in-flight orders. Back the key up *separately* from
> the database — a backup containing both the table and the key is a backup an insider can
> rewrite.

---

## 13. Comparing `aizu` against this

Every item below is a question this repository cannot answer. They are the difference between
"the code requires this" and "the host does this", and they are why the opening of this
document says not to run it.

- Does `aizu` use systemd, under these unit names and paths? `deploy/systemd/*.service` is a
  proposal.
- Are all three processes running, on one box or split? The repo assumes a shared Redis and a
  shared filesystem root and proves nothing about the topology.
- What is each process's working directory, and do the bot's `Path.cwd()/var` and the admin's
  `HBD_ADMIN_DATA_ROOT` resolve to the same absolute path?
- Is `HBD_ENVIRONMENT` the exact string `prod` in **each** of the three processes?
- Is `HBD_ADMIN_ENABLED=true`, and does the admin connect as `hbd_app` rather than the owner?
- Do both Postgres roles exist, with the `ALTER DEFAULT PRIVILEGES` clauses, and did 0007's
  REVOKE actually land? `\dp admin_audit_log` or `chainProtection` answers it.
- Is the database at head 0021?
- Does the host's ffmpeg include libopus *and* an mp3 encoder? A running bot proves the first
  and says nothing about the second.
- Is Redis persistent, and on what configuration?
- What terminates TLS, does it add HSTS, and does it append or replace `X-Forwarded-For`?
- Are `HBD_ADMIN_TRUSTED_PROXY_HOPS` and `HBD_ADMIN_TRUSTED_PROXY_CIDRS` set, or still the
  example file's `0` and empty?
- Is `HBD_ADMIN_PUBLIC_ORIGIN` the `https://` origin browsers actually reach, and is the panel
  reachable under any second name?
- Is `HBD_ADMIN_PROBE_TOKEN` set, and is anything polling `/readyz` with it?
- Is the deployed bundle current, or does it predate `__HBD_CSP_NONCE__`?
- How many worker replicas run?
- Has `var/workspace` ever been cleaned, by anything?
- Is anything backing up Postgres, `var/archive`, or the audit HMAC key?
- Has ENV-6's restore drill (docs/product/SCOPE_OF_WORK.md:716) ever been executed and documented, and
  does anything on the host implement ENV-11's post-restore reconciliation (:721)? Both are
  MUSTs that no code in this checkout implements, so only the host can answer them.
- Does `max_connections` on that server leave room above the 70 the three processes reserve?

Answering any of these takes host access. Assuming any of them is how a control that was never
deployed gets reported as deployed.
