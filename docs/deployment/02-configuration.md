# Configuration reference

## STATUS — what has now been checked against the machine, 2026-09-11

**This page was written blind. It is no longer blind, and the single most important thing it
learned is that its central deploy check does not work on the production host.** The page has
been read against `aizu` (machine `abdu-test`) with read-only commands on 2026-09-10 and again on
2026-09-11. Three marks now appear throughout:

- **`[HOST 2026-09-10]`** / **`[HOST 2026-09-11]`** — a read-only command was run against `aizu`
  on that date and what is quoted is faithful to its output. Every 09-10 mark was re-run on
  09-11 and still holds; an 09-11 mark means the claim is new here, or is a live gauge whose
  reading only means "when it was read".
- **`[TREE 2026-09-11]`** — checkable by opening a file in this working tree; a `path:line` is
  given. The counts on this page had all drifted and have been recounted.
- **`[UNPROVEN]`** — exactly that, with the blocker named.

**Read this before following any instruction below that says "read the boot log".** On this host,
three of the four processes are fed by systemd `EnvironmentFile=` rather than by the
`*_ENV_FILE` selector this page is built around. The logged `env_file` field therefore names a
file that is **not** the configuration source, and may not exist. See §"Precedence, and the one
failure the error message cannot describe".

**What has NOT been checked:** the contents of any of the three dotenv files, anything inside
Postgres, and `/var/lib/hbd`. `/etc/hbd` is `0750 root:hbd`, the `hbd` group has **no members**,
`sudo -n` refuses with *"sudo: a password is required"*, and `psql` fails with
`fe_sendauth: no password supplied` `[HOST 2026-09-11]`. So **no question of the form "is
variable X set on the host" can be answered by anyone short of root**, and this page marks each
one rather than guessing. That is a permission wall the deployment put there on purpose, not a
gap in the looking — see §"What the host settles and what it does not".

**The host is PRE-RENAME and that is correct.** Units are `hbd-bot`, `hbd-worker`, `hbd-admin`,
`hbd-payme`; paths are `/etc/hbd/*.env`, `/opt/hbd/venv`, `/var/lib/hbd`; the environment prefix
is **`HBD_`** and the database is `hbd`. This **repository** is post-rename (`src/bayram`,
`BAYRAM_`). Both are right at once: every code claim below is spelled `BAYRAM_` because that is
what the tree says, every host claim `HBD_` because that is what the machine says. **Do not sweep
this page with a rename pass** — a blind rename has already turned verified host facts into
fiction in this tree once (`00-host-inventory.md`, finding 7). The cutover script staged at
`/opt/hbd/cutover-to-bayram.sh` **has not run** `[HOST 2026-09-11]`, so the divergence is live.

[00-host-inventory.md](00-host-inventory.md) is the inventory of record and **wins** wherever it
disagrees with this page; rows 18–25 cover the dotenv ground below and are cross-referenced
rather than restated.

---

Everything this product reads is `BAYRAM_`-prefixed and maps 1:1 onto a field of one of **three**
settings classes: `bayram.config.Settings` for the bot and the worker,
`bayram.admin.settings.AdminSettings` for the admin API, and
`bayram.payme.settings.PaymeSettings` for the Payme gateway. All three are `frozen=True` and all
three use `extra="ignore"` (`src/bayram/config.py:161-167`,
`src/bayram/admin/settings.py:160-166`, `src/bayram/payme/settings.py`), which has a consequence
worth putting first: **a misspelled variable is not an error anywhere**. It is silently
discarded, in every file, in every environment.

> **SUPERSEDED 2026-09-11, kept because it dates the change.** This page opened, until today,
> *"maps 1:1 onto a field of one of **two** settings classes"*, and mentioned `PaymeSettings`
> nowhere. That was accurate when written (2026-09-07) and is not now. The third class is **20
> `Field()` declarations** with its own example file, its own selector variable
> `BAYRAM_PAYME_ENV_FILE`, its own closed-`Literal` environment and its own boot refusals
> (`src/bayram/payme/settings.py:115`, `:162`, `:348`) `[TREE 2026-09-11]` — and it governs the
> process that now handles money. A configuration reference that omitted it would be trusted as
> exhaustive and would not be.

This page is exhaustive about what production actually requires and deliberately not
exhaustive about the rest. `.env.example` (**100** assignments), `.env.admin.example` (**37**)
and `.env.payme.example` (**20**) carry the long tail with the reasoning attached; read them for
anything not named here. Those three counts were `89`, `35` and *unmentioned* until 2026-09-11;
they are `grep -cE '^[A-Z][A-Z0-9_]*=' <file>` and will drift again, so re-run the count rather
than trusting this sentence `[TREE 2026-09-11]`.

---

## The two axes

Conflating these is the usual mistake, and README.md:197-215 says so too.

**`BAYRAM_ENVIRONMENT` is a value *inside* a file.** It is what the code branches on. **Seven**
refusals in the whole tree key off it: two on the bot/worker side, three in the admin process,
and two in the Payme gateway.

| Refusal | Where | In force on this host? |
| --- | --- | --- |
| `BAYRAM_USE_FAKE_PROVIDERS` while `prod` | `src/bayram/runtime/providers.py:105` | **Yes** — bot and worker log `environment: prod`, and `is_fake: false` `[HOST 2026-09-11]` |
| the in-process (no-queue) submitter in `prod` | `src/bayram/runtime/submitter.py:101` | **Yes** — same |
| `BAYRAM_ADMIN_PUBLIC_ORIGIN` unset outside `dev` | `src/bayram/admin/settings.py:578-588` | **Yes** — panel is `prod`, and it booted, so the origin is set `[HOST 2026-09-11]` |
| `BAYRAM_IS_DEBUG` / `BAYRAM_LOG_LEVEL=DEBUG` in `prod` | `src/bayram/admin/settings.py:589-593` | **Yes** — panel is `prod` |
| a vendor credential within reach of the admin process in `prod` | `src/bayram/admin/app.py:189-201` | **Yes** — panel is `prod`, so a hit raises rather than warns |
| DEBUG logging in the **gateway** in `prod` | `src/bayram/payme/settings.py:330-338` | **NO — inert.** The gateway runs `environment: dev` `[HOST 2026-09-11]` |
| a vendor credential within reach of the **gateway** in `prod` | `src/bayram/payme/app.py:203`, raising only `if settings.is_production` at `:219-220` | **NO — downgraded to a WARNING** for the same reason |

> **The drift this section warns about is real on the production host, on the process holding the
> cashbox key.** `HBD_ENVIRONMENT` reads `prod` in the bot, the worker and the panel, and **`dev`
> in the gateway** — in both `payme.container.built` and `payme.boot.ok`, at the 2026-09-10 boot
> and again at 2026-09-11 06:49 `[HOST 2026-09-10]` `[HOST 2026-09-11]`. No typo is involved:
> `dev` is `PaymeSettings`' shipped default (`src/bayram/payme/settings.py:162`), the closed
> `Literal` accepts it, and nothing cross-checks the three files. The two bottom rows of that
> table are therefore not hypotheticals on this machine — they are two boot controls that do not
> exist, on the one process with something inbound from the public internet. The two Payme
> refusals that **do** run unconditionally are `_refuse_disabled_gateway` and
> `_refuse_a_blank_key` (`src/bayram/payme/app.py:631-633`) `[TREE 2026-09-11]`, and since the
> gateway booted, both passed. Recorded also in [01-architecture.md](01-architecture.md) and
> `00-host-inventory.md` row 20.

**`BAYRAM_ENV_FILE`, `BAYRAM_ADMIN_ENV_FILE` and `BAYRAM_PAYME_ENV_FILE` decide *which file* is
read.** They are process-environment variables and can only be that: a dotenv file cannot name the
dotenv file about to be read (`src/bayram/config.py:74-81`). Writing any of them *into* a dotenv
file is a line with no effect, not a redirect. They default to `.env`, `.env.admin` and
`.env.payme` (`src/bayram/config.py:71`, `src/bayram/admin/settings.py:65`,
`src/bayram/payme/settings.py:88`), so a checkout that has only ever had those behaves exactly as
it always has. The third is a **separate variable and not a tier name shared with the first** —
the rule is stated once, at `bayram.admin.settings.ADMIN_ENV_FILE_VAR`, and
`src/bayram/payme/settings.py:13-14` points back at it `[TREE 2026-09-11]`.

> **On this host only ONE of those three variables is set anywhere, and it is the gateway's.**
> `systemctl show -p Environment` is **empty** for `hbd-bot`, `hbd-worker` and `hbd-admin`; only
> `hbd-payme` carries `Environment=HBD_PAYME_ENV_FILE=/etc/hbd/payme.env` `[HOST 2026-09-10]`,
> re-confirmed `[HOST 2026-09-11]`. The other three are fed by systemd `EnvironmentFile=`
> instead. This is the single most consequential host fact on this page, and it is developed two
> sections down.

> **`Settings.environment` is an unvalidated `str`; `AdminSettings.environment` is a closed
> `Literal`.** `src/bayram/config.py:170` is `Field(default="dev")` with no validator, while
> `src/bayram/admin/settings.py:169` is `Literal["dev","staging","prod"]` — and the docstring at
> `src/bayram/admin/settings.py:15-17` explains why it was closed: "a typo like `production`
> would silently downgrade the strongest boot control in the package". Both classes derive
> production as `environment == "prod"` exactly (`src/bayram/config.py:684-686`,
> `src/bayram/admin/settings.py:597-599`). That argument was never applied back to `Settings`,
> so `BAYRAM_ENVIRONMENT=production` or `PROD` on the bot or the worker is accepted, reads as
> not-production, and disarms both bot-side refusals with no error anywhere. Type the string
> `prod`, lowercase, and confirm it from the boot log rather than from the file.

### The file × process matrix

| | bot (`bayram.main`) | worker (`arq bayram.worker.WorkerSettings`) | admin API (`uvicorn bayram.admin.app:app`) | **Payme gateway** (`uvicorn bayram.payme.app:app`) | migrations (`alembic upgrade head`) |
| --- | --- | --- | --- | --- | --- |
| settings class | `Settings` | `Settings` | `AdminSettings` | `PaymeSettings` | none, when `BAYRAM_DB_MIGRATION_URL` is set; otherwise `Settings`, via `load_settings()` |
| file read | `BAYRAM_ENV_FILE`, else `.env` | same | `BAYRAM_ADMIN_ENV_FILE`, else `.env.admin` | `BAYRAM_PAYME_ENV_FILE`, else `.env.payme` — **no default worth relying on**; `/etc/hbd/payme.env` on this host `[HOST 2026-09-11]` | `BAYRAM_ENV_FILE`, else `.env` |
| file read **on this host** | `/etc/hbd/hbd.env`, via `EnvironmentFile=` | same | `/etc/hbd/hbd-admin.env`, via `EnvironmentFile=` | `/etc/hbd/payme.env`, via the selector — the only one | `[UNPROVEN]`; the host's cutover script sources an env file with `set -a` |
| holds vendor keys | yes, required | yes, required | **never** — no field can hold one | **never** — no field can hold one, **plus** `InaccessiblePaths` at the kernel level on this host | inherits the bot's file |
| needs ffmpeg | yes | yes | no | **no** | no |

The admin process reads a different file from the bot *because that separation is the
vendor-key boundary*, not as a convenience — `src/bayram/admin/settings.py:64` says it plainly
("Never `.env`: a shared file is how a vendor key reaches a process that must not hold
one"), and the deliberate choice of a *second* variable rather than one shared tier name is
argued at `src/bayram/admin/settings.py:67-72`.

The gateway reads a third file for the same reason the panel reads a second one, and the unit file
on the host argues it at length: `PaymeSettings` has no field that could hold a vendor credential,
so a key sitting in that process's environment is *"not merely unread — there is no attribute it
could be read through"*, and `InaccessiblePaths=/etc/hbd/hbd.env /etc/hbd/hbd-admin.env` is the
kernel's half of the same separation, *"and it survives a future edit that points
HBD_PAYME_ENV_FILE at the wrong file"* (`hbd-payme.service:23-31`) `[HOST 2026-09-11]`. Three
independent mechanisms, on purpose.

Migrations are a fifth command and read the **bot's** file (`migrations/env.py:95-113`,
`migrations/env.py:117-129`). They never read `.env.admin` or `.env.payme`. That has a sharp
consequence for the audit REVOKE — see below.

> **Whether migrations build a `Settings` object at all depends on `BAYRAM_DB_MIGRATION_URL`.**
> `load_settings` is imported at `migrations/env.py:57` and called from exactly one place,
> `migrations/env.py:129` — the else-branch of `_database_url()`, reached only when no owner
> DSN was found. With the owner DSN set (the two-role deployment the section below urges), no
> settings object is constructed and the bot's vendor keys are never touched. **Without it,
> the fallback calls `load_settings()`, which always passes `require_vendor_secrets=True`
> (`src/bayram/config.py:758-760`)** — so on a one-role host whose bot env file carries no vendor
> keys, `make migrate` does not fall back with a warning: it refuses outright with the same
> four-variable `ConfigError` the bot would raise. The matrix cell above reads "inherits the
> bot's file"; on that path it inherits the bot's *requirements* too.

`make` wraps the two variables in one flag (`Makefile:41-46`):

```bash
cp .env.example .env.prod             && $EDITOR .env.prod
cp .env.admin.example .env.admin.prod && $EDITOR .env.admin.prod

make dev   ENV=prod     # BAYRAM_ENV_FILE=.env.prod BAYRAM_ADMIN_ENV_FILE=.env.admin.prod
make admin ENV=prod     # …and the same for worker, migrate, revision, admin-bootstrap
```

`ENV=dev` is the default and maps to the bare names, so nothing changes for anyone who never
passes the flag. **`$(ENV_FILES)` covers two of the three selectors** — there is no
`BAYRAM_PAYME_ENV_FILE` in it, so a third file copied from `.env.payme.example` has to be pointed
at by hand. And on a host that supplies configuration some other way, none of this `make`
machinery is involved at all: **this production host is that host.** There is no checkout on it and
therefore no `Makefile`; nothing on `abdu-test` sets `HBD_ENV_FILE` or `HBD_ADMIN_ENV_FILE`; and the
files live at `/etc/hbd/hbd.env`, `/etc/hbd/hbd-admin.env` and `/etc/hbd/payme.env` —
**three** files, not four `[HOST 2026-09-11]`. No fourth is referenced by any unit or by either
host deploy script.

### Precedence, and the one failure the error message cannot describe

Process environment beats the dotenv file, for every variable on both classes: both builders
pass the resolved path as a `_env_file` *default* (`src/bayram/config.py:741`,
`src/bayram/admin/settings.py:668`) and pydantic-settings ranks init kwargs > environment >
dotenv > field defaults. A value supplied by the dotenv file still counts towards
`model_fields_set`, which is what the `BAYRAM_ADMIN_PUBLIC_ORIGIN` guard tests.

> **A mistyped `BAYRAM_ENV_FILE` reads no file at all, silently, and the error never names it.**
> `dotenv_values` on a path that does not exist returns an empty mapping and raises nothing.
> With `BAYRAM_ENV_FILE=/nonexistent/.env.prod`, `load_settings()` raises exactly this:
>
> ```
> Configuration is invalid or incomplete. Fix these environment variables (see .env.example):
>   BAYRAM_TELEGRAM_BOT_TOKEN: Field required
>   BAYRAM_DATABASE_URL: Field required
>   BAYRAM_ELEVENLABS_API_KEY: Field required
>   BAYRAM_LLM_API_KEY: Field required
> ```
>
> The preamble's "see .env.example" is hardcoded (`src/bayram/config.py:702-704`; the admin twin
> at `src/bayram/admin/settings.py:640-643`) and is *not* the file that was resolved. The file
> actually read is logged only afterwards, by `verify_host` (`src/bayram/runtime/startup.py:34-41`)
> and by `admin.boot.ok` (`src/bayram/admin/app.py:329`) — both of which run only once settings
> have already built. So the one failure mode this feature introduces is the one its error
> message cannot report. Worse: if the four required values happen to be exported in the
> deploy shell, a mistyped path boots the bot on 100% defaults, including
> `BAYRAM_ENVIRONMENT=dev`.

The check after any deploy is therefore the boot log, not the file on disk. All three boot paths
emit one line naming the file they actually read. The strings to look for are:

- **bot and worker** — `host verified`, one line at INFO, emitted by `verify_host`.
- **admin API** — `admin.boot.ok`, the same pair plus the origin the CSRF check will enforce.
- **Payme gateway** — `payme.boot.ok`, the same pair plus the merchant id, the account field, the
  basic-auth login, the duplicate-transaction code and the merchant key's **length** (never the
  key).

> **THE CENTRAL CHECK ON THIS PAGE RETURNS THE WRONG ANSWER ON THE PRODUCTION HOST, for three of
> the four processes.** `[HOST 2026-09-10]`, re-confirmed `[HOST 2026-09-11]`.
>
> The advice above is sound and the mechanism it assumes is not the one deployed. `hbd-bot` and
> `hbd-worker` take `EnvironmentFile=/etc/hbd/hbd.env`; `hbd-admin` takes
> `EnvironmentFile=/etc/hbd/hbd-admin.env`; and `systemctl show -p Environment` is **empty** for
> all three, so **`HBD_ENV_FILE` and `HBD_ADMIN_ENV_FILE` are set nowhere**. systemd puts the
> values straight into the process environment, pydantic-settings never resolves a real path, and
> the boot line faithfully reports the **unused relative default**:
>
> ```
> host verified   {"environment": "prod", "env_file": ".env",        "ffmpeg": "ffmpeg", "locales": 4, "catalogue_languages": 4}
> admin.boot.ok   {"environment": "prod", "env_file": ".env.admin",  "is_cookie_secure": true, "public_origin": "https://admin.bayrambot.uz"}
> payme.boot.ok   {"environment": "dev",  "env_file": "/etc/hbd/payme.env", "merchant_id": "6aa24fd9ee30563de3a1ac22", …}
> ```
>
> Those first two paths are relative to `WorkingDirectory=/var/lib/hbd`. **Whether
> `/var/lib/hbd/.env` or `/var/lib/hbd/.env.admin` exists at all is `[UNPROVEN]`** — that
> directory is `0750 hbd:hbd` and `developer` cannot traverse it — and it does not matter, because
> nothing read them. An operator following the instruction above would go looking in
> `/var/lib/hbd/.env` for a value that lives in `/etc/hbd/hbd.env`. Only the gateway's logged path
> is real, and it is real precisely because it is the one unit using the selector.
>
> **The command that answers the question on this host** is not a grep of the log:
>
> ```bash
> ssh aizu 'systemctl show -p EnvironmentFiles -p Environment hbd-bot hbd-worker hbd-admin hbd-payme'
> ```
>
> Two further consequences, neither of which the repository anticipates. **The secrets are in the
> process environment** — visible to `systemctl show` and to anything that can read
> `/proc/<pid>/environ` — which is exactly what `hbd-payme.service:33-37` warns against while
> mis-attributing the avoidance to `hbd-bot.service`, a unit that does the opposite. And **a
> mistyped `EnvironmentFile=` path fails differently from a mistyped `BAYRAM_ENV_FILE`**: systemd
> declares it `ignore_errors=no`, so the unit fails to start and says so, rather than booting on
> 100% defaults the way the callout above describes. That is a strictly better failure mode, and
> it is worth knowing which one you are exposed to. `00-host-inventory.md` rows 18–19 and finding
> 6 record the same divergence; where this page and 00 differ, 00 wins.

The log source is settled, too. All four units run `StandardOutput=journal` and log **nowhere
else**; the journal is persistent (`/var/log/journal` exists); `/etc/systemd/journald.conf` sets
no `Storage`, no `MaxRetentionSec` and no `SystemMaxUse`, so retention is the distro default and
the only bound is disk (96.6 MB on 2026-09-11, 88.6 MB the day before — a gauge, not a budget).
`journalctl` needs **no sudo**: `developer` is in group `4(adm)` `[HOST 2026-09-11]`. The three
searches are:

```bash
ssh aizu "journalctl -u hbd-bot   -o cat | grep 'host verified'"
ssh aizu "journalctl -u hbd-admin -o cat | grep 'admin.boot.ok'"
ssh aizu "journalctl -u hbd-payme -o cat | grep 'payme.boot.ok'"
```

`/var/log/hbd` exists (`hbd:hbd 0755`) and is **empty**, so the
`ReadWritePaths=/var/log/hbd` grant on the bot and the worker is currently unused — do not look
for a file there.

Note the exact strings. `host verified` has a **space** and is the log *message*, not an
`event` field — `verify_host` puts `environment`, `env_file`, `ffmpeg`, `locales` and
`catalogue_languages` in `extra` and no `event` key at all
(`src/bayram/runtime/startup.py:33-41`), and under JSON logging the message lands as
`message` (`src/bayram/logging.py:200-220`). `admin.boot.ok` *is* a real `context.event`
(`src/bayram/admin/app.py:325`). A grep for `host_verified` with an underscore matches nothing
in this tree, so an empty result from that spelling is not evidence the bot failed to boot.

---

## Required in production — bot and worker

Exactly four, and they are required in **every** environment, not only prod. Nothing becomes
newly required at `BAYRAM_ENVIRONMENT=prod` on this side.

| Variable | Class | Default | What refuses or degrades |
| --- | --- | --- | --- |
| `BAYRAM_DATABASE_URL` | `Settings` | **none** (`Field(min_length=1)`, `src/bayram/config.py:187`) | Process will not build settings. `ConfigError`, exit 2 on the bot. |
| `BAYRAM_TELEGRAM_BOT_TOKEN` | `_VendorBoundSettings` | **none** in this path (`src/bayram/config.py:697`; optional `""` on the base class at `:184`) | Same. |
| `BAYRAM_ELEVENLABS_API_KEY` | `_VendorBoundSettings` | **none** (`src/bayram/config.py:698`) | Same. Music, TTS and STT all ride this one key. |
| `BAYRAM_LLM_API_KEY` | `_VendorBoundSettings` | **none** (`src/bayram/config.py:699`) | Same. |

**All four are satisfied on the production host, and the boot line proves it without reading a
file.** The bot and the worker log `host verified {"environment": "prod", "env_file": ".env",
"ffmpeg": "ffmpeg", "locales": 4, "catalogue_languages": 4}` followed by
`container built {"is_fake": false, "has_providers": true, "workspace":
"/var/lib/hbd/var/workspace", "database": "127.0.0.1:5432/hbd"}` and `bot starting
{"environment": "prod", "is_fake": false, "ui_language": "uz_latn"}` `[HOST 2026-09-10]`,
re-confirmed at the 2026-09-11 06:50 boot. Settings built, so all four required variables are
present; `has_providers: true` with `is_fake: false` means the real vendor clients were
constructed, so the three keys are non-blank. What those **values** are remains `[UNPROVEN]` and
always will be from this account.

The three vendor secrets are required by a *subclass*, not a flag:
`build_settings(require_vendor_secrets=True)` selects `_VendorBoundSettings`
(`src/bayram/config.py:739`), and `load_settings()` — the boot path for both the bot and the
worker — always passes `True` (`src/bayram/config.py:758-760`). A process that must not hold
them passes `False`; the two operator CLIs under `src/bayram/tools/` do exactly that, which is
why they run on a box with no vendor keys.

> **The bot and the worker report the same misconfiguration differently.** `bayram.main` builds
> settings inside `try/except BayramError`, prints `bayram: <operator message>` and returns 2
> (`src/bayram/main.py:213-218`). The worker builds them at **module import** —
> `_SETTINGS = _settings()` at `src/bayram/worker.py:40` — so the same bad file produces an
> uncaught traceback from the `arq` CLI, with no clean one-line message. **The supervisor is
> systemd, and the repeat behaviour is now knowable**: `hbd-worker` is `Restart=on-failure` with
> `RestartSec=5s`, so the traceback repeats every five seconds until systemd's start limit trips
> `[HOST 2026-09-11]`. The gateway is `Restart=always`, which retries **forever** — and that
> difference is visible in the journal: twelve `Started hbd-payme.service` lines between 00:00:05
> and 00:01:26 during the 2026-09-10 deploy, against two each for the bot, the worker and the
> panel `[HOST 2026-09-10]`. Do not read a worker traceback as a different class of problem from a
> bot's tidy refusal; check the four variables first.

> **`BAYRAM_REDIS_URL` is the dangerous default on this list.** It defaults to
> `redis://localhost:6379/0` (`src/bayram/config.py:188`), so a wrong or missing value does not
> fail — it connects to whatever local Redis exists. In production the bot has no non-Redis
> path: `build_submitter` takes the `create_pool(...)` branch because the in-process
> submitter is refused (`src/bayram/main.py:89-95`, `src/bayram/runtime/submitter.py:101`). Redis
> is a hard dependency of *both* long-running processes, and they must share one URL and one
> logical DB: the bot parks a wizard session in the FSM store and only the worker's job
> releases it (`src/bayram/bot/app.py:83-97`, `src/bayram/worker.py:51-57`,
> `src/bayram/runtime/jobs.py:771`). Two different Redis databases leaves customers parked with
> no error on either side. **On this host the dangerous default happens to be the truth**: one
> local Redis 7.0.15 on `127.0.0.1:6379`, shared by both processes, reported by the worker's own
> arq banner `[HOST 2026-09-11]`. Persistence is `appendonly no`, RDB only
> (`00-host-inventory.md` row 16), so a restart does lose in-flight drafts and queued jobs —
> whether `HBD_REDIS_URL` is written in the file or merely defaulting is `[UNPROVEN]`, and the
> operational answer is the same either way.

---

## Required for the admin API

| Variable | Class | Default | What refuses or degrades |
| --- | --- | --- | --- |
| `BAYRAM_DATABASE_URL` | `AdminSettings` | **none** (`src/bayram/admin/settings.py:174`) | Settings will not build. |
| `BAYRAM_ADMIN_AUDIT_HMAC_KEY` | `AdminSettings` | **none**, `SecretStr`, `min_length=32` (`src/bayram/admin/settings.py:229`) | Settings will not build. See the callout below — this one is not replaceable later. |
| `BAYRAM_ADMIN_ENABLED` | `AdminSettings` | `false` (`src/bayram/admin/settings.py:180`) | Settings build fine; the **lifespan** refuses (`src/bayram/admin/app.py:206-208, :315`) with "The admin panel is disabled. Set BAYRAM_ADMIN_ENABLED=true in .env.admin to run it." |
| `BAYRAM_ADMIN_PUBLIC_ORIGIN` | `AdminSettings` | `http://127.0.0.1:8080` — dev only (`src/bayram/admin/settings.py:194`) | Refused at boot outside `dev` unless **set** (`:578-588`). Wrong-but-set is not caught; every mutation then 403s `ORIGIN_REJECTED` while the panel looks healthy. |

`BAYRAM_ADMIN_ENABLED=false` is the shipped default on purpose — "an admin surface that appears
because a dependency was installed is not a decision anybody made"
(`src/bayram/admin/settings.py:177-179`). A first deploy of the admin process will refuse to
start until someone turns it on, and that is the intended shape.

**All four rows are answerable from the host, from one log line.** `admin.boot.ok` is emitted only
after settings construct *and* both lifespan refusals pass, and it carries
`{"environment": "prod", "env_file": ".env.admin", "is_cookie_secure": true, "public_origin":
"https://admin.bayrambot.uz"}`, beside `admin.container.built {"environment": "prod",
"pool_size": 5, "database": "127.0.0.1:5432/hbd"}` `[HOST 2026-09-10]`, re-read
`[HOST 2026-09-11]`. Read backwards: `HBD_DATABASE_URL` and `HBD_ADMIN_AUDIT_HMAC_KEY` are set and
the key is ≥32 characters (settings built); `HBD_ADMIN_ENABLED` is **true** (the lifespan refuses
otherwise); `HBD_ADMIN_PUBLIC_ORIGIN` is **set, and not to the loopback default** (the
outside-dev guard would have refused the boot, and the logged value is not the default); and
`admin_cookie_secure` derived to `true`. The origin also **matches** the hostname browsers reach —
`admin.bayrambot.uz` is a published tunnel route (`00-host-inventory.md` rows 22 and 42) — so the
`ORIGIN_REJECTED` trap the callout below describes is not armed here. What the line does **not**
settle: `env_file` `".env.admin"` is the unused relative default, for the reason given above.

> **The origin guard tests whether the variable was *set*, not whether it is plausible.** The
> check is `"admin_public_origin" not in self.model_fields_set`
> (`src/bayram/admin/settings.py:580`), and a value supplied by the dotenv file counts as set.
> `.env.admin.example:73` ships the line **uncommented, at the loopback dev value** — so
> copying the example onto a production host and setting `BAYRAM_ENVIRONMENT=prod` disarms the
> guard and produces precisely the incident its own message predicts: "the loopback default
> would boot, pass `/healthz`, serve a login page and then reject every mutation with
> ORIGIN_REJECTED" (`src/bayram/admin/settings.py:582-587`). Set it to the exact origin a browser
> reaches — scheme, host, optional port, no path, no trailing slash
> (`src/bayram/admin/settings.py:500-514`) — and confirm it from the `public_origin` field of
> `admin.boot.ok`.

### The admin process must not hold a vendor credential

`FORBIDDEN_ENV_VARS` is **derived**, never restated: it upper-cases
`bayram.config.VENDOR_SECRET_FIELDS` with the `BAYRAM_` prefix (`src/bayram/admin/app.py:116-118`),
so the five names are exactly `BAYRAM_TELEGRAM_BOT_TOKEN`, `BAYRAM_ELEVENLABS_API_KEY`,
`BAYRAM_LLM_API_KEY`, `BAYRAM_LLM_FALLBACK_API_KEY` and `BAYRAM_OPENROUTER_MANAGEMENT_KEY`
(`src/bayram/config.py:111-117`). Note the
asymmetry with the *required* tuple one field below it
(`REQUIRED_VENDOR_SECRET_FIELDS`, `src/bayram/config.py:123-127`): "the admin host must never
hold it" and "this process cannot start without it" are two different claims, and the
fallback LLM key is on the first list only.

The scan covers both the process environment and the names parsed out of the admin dotenv
file (`src/bayram/admin/app.py:175-183`), reading the file through the *same* resolver
`build_admin_settings` uses so it cannot clear a host whose keys sit in the file that was
actually loaded (`src/bayram/admin/app.py:141-149`). In `prod` a hit is a `ConfigError`; in
`dev` and `staging` it is the WARNING `admin.boot.vendor_env_present`
(`src/bayram/admin/app.py:189-203`).

> **The disabled-panel refusal runs first.** `src/bayram/admin/app.py:315-316` calls
> `_refuse_disabled_panel` then `_refuse_vendor_credentials`, and both raise `ConfigError`.
> On a host with both problems the operator is told the panel is disabled and never learns a
> vendor key was within reach. After turning `BAYRAM_ADMIN_ENABLED=true`, read the next boot
> attempt rather than assuming the first message was the only one.

---

## The four fields with no usable default

Across all **103** `Settings` fields, all 103 `_VendorBoundSettings` fields, all **37**
`AdminSettings` fields and all **20** `PaymeSettings` fields, exactly four are required with no
default of any kind `[TREE 2026-09-11]`:

```
Settings.database_url               src/bayram/config.py:187
AdminSettings.database_url          src/bayram/admin/settings.py:174
AdminSettings.admin_audit_hmac_key  src/bayram/admin/settings.py:229
PaymeSettings.database_url          src/bayram/payme/settings.py:171   ← Field(min_length=1), no default
```

> **SUPERSEDED 2026-09-11, kept because it dates the change.** This section was headed "The three
> fields with no usable default" and counted "all 88 `Settings` fields… and all 35
> `AdminSettings` fields". The counts are now 103 / 37, with 20 more on a class the page did not
> mention, and `PaymeSettings.database_url` makes the answer **four** rather than three. The count
> is `Field(` declarations at class-body indentation; re-run it rather than trusting this sentence.

Everything else is defaulted; the three vendor secrets become required only through
`_VendorBoundSettings` (`src/bayram/config.py:689-699`). Note the shape of the fourth: every one of
the four processes needs a DSN and **every one of them declares its own field for it**, on its own
class, in its own file. On this host all four resolve to the same place — `127.0.0.1:5432/hbd`,
printed in all four container lines `[HOST 2026-09-11]` — and nothing in any of the three codebases
would notice if one of them drifted.

**Generate the audit key with this, and nothing else:**

```bash
python -c "import secrets; print(secrets.token_urlsafe(48))"
```

That is the command the repo already documents (`.env.admin.example:120`, README.md:156). It
yields 64 URL-safe characters, comfortably over the `min_length=32` floor — and note that the
floor is counted in *characters of the secret*, so pydantic's refusal reads "Value should
have at least 32 items after validation, not 0" rather than naming a key.

> **This key is write-once for the life of the audit log, and it lives outside the database.**
> Each row's MAC is `HMAC-SHA256(key, "v1" ‖ prev_hmac ‖ canonical_json(row))`
> (`src/bayram/db/admin/audit.py:10-15`) and there is **no key-id column** on `admin_audit_log`
> (`src/bayram/db/models/admin_audit.py:131-197`). `verify_chain` walks from the oldest row and
> reports the first MAC that does not recompute (`src/bayram/db/admin/audit.py:594-641`), so
> changing the key makes `/api/audit/verify` report a break at the first row, permanently, and
> losing it makes the log permanently unverifiable — neither is distinguishable from tampering.
> It is required from the first boot rather than from the first audited action precisely so
> the chain never has an unsigned prefix (`src/bayram/admin/settings.py:220-223`). Back it up
> **separately from the database dump**: a backup that contains both the table and its key is
> a backup anyone holding it can rewrite. Nothing in this repository backs up anything —
> `grep -rn 'pg_dump\|backup' README.md Makefile deploy/ docs/` finds one hit and it means a
> fallback vendor — so this is an obligation the deployment owns entirely.

Two DSNs, not one: `BAYRAM_DATABASE_URL` appears on both classes and both processes need it,
but they are separate fields on separate models. See "Owned by both classes" below for what
that means in practice.

---

## `BAYRAM_DB_MIGRATION_URL`, and why it is not a `Settings` field

It is read by `migrations/env.py` and by nothing else. It is deliberately **not** a field on
`Settings`, and `.env.example:43-45` gives the reason: "the bot and the worker must never
hold the owner credential, and a field on the shared object is an invitation to". A field
would put the table owner's password in reach of two long-running processes that have no use
for it.

Its presence is how a deployment *declares* the two-role split: `hbd` owns the tables and
runs migrations, `hbd_app` is what the bot, the worker and the admin API connect as, and
migration 0007's `REVOKE UPDATE, DELETE, TRUNCATE ON admin_audit_log` only means anything
when those are two different roles. An owner can `GRANT` back anything revoked from it, so a
one-role deployment has no privilege-based audit protection at all.

Resolution order (`migrations/env.py:95-114`): the process environment first, then
`dotenv_values(env_file())` — the **bot's** file. That dotenv fallback was added because the
environment-only version was a bug that would have migrated production as the wrong role
(`migrations/env.py:14-19`). Unset, migrations still run, against `BAYRAM_DATABASE_URL`, with
this WARNING (`migrations/env.py:88-93`):

```
BAYRAM_DB_MIGRATION_URL is not set, so migrations are running as the application role. That
role owns every table it creates, and an owner can GRANT back anything revoked from it — so
the audit log's REVOKE is not a control on this deployment.
```

That line at migration time, and `chainProtection` on `GET /api/audit/verify`, are the two
observable answers to "is the split actually deployed". The badge is honest by construction:
it asks Postgres `has_table_privilege(current_user, 'admin_audit_log', 'UPDATE'/'DELETE'/'TRUNCATE')`
rather than reading configuration (`src/bayram/db/admin/audit.py:746-780`), and reports
`hmac-only` with the WARNING `admin.audit.revoke_missing` when the role can still write.

> **Two more variables gate the REVOKE, and both are read from `os.environ` only.** Migration
> 0007 skips unless `BAYRAM_ADMIN_AUDIT_DSN` is in the environment
> (`migrations/versions/20260830_1000_0007_add_admin_audit_log.py:336`) and then resolves the
> role name from `BAYRAM_DB_APP_ROLE`, falling back to the username inside `BAYRAM_DATABASE_URL`
> — again from `os.environ` alone (`:314-322`). Migration 0011 repeats the pattern. Neither
> has the dotenv fallback `migrations/env.py` gave itself. `BAYRAM_ADMIN_AUDIT_DSN` is documented
> as living in `.env.admin` (`.env.admin.example:130`), which the migration runner never
> parses, and **`BAYRAM_DB_APP_ROLE` appears in neither example file**. So a deployment
> configured exactly as documented takes the first `_skip` branch and installs no REVOKE and
> no `SECURITY DEFINER` purge functions — as two WARNINGs in the alembic output, not a
> failure. Export both into the migrate shell — **and make sure the bot env file you point at
> carries `BAYRAM_DB_MIGRATION_URL`**, or alembic connects as the application role and the REVOKE
> is taken while connected as the role being revoked from. That combination is the worst one
> available: `BAYRAM_ADMIN_AUDIT_DSN` alone satisfies migration 0007's only guard (`:336`) so
> `_apply_revoke` runs and reports success, while alembic's own connection came from
> `_database_url()`, which silently fell back to the application DSN with nothing but the
> one-role WARNING (`migrations/env.py:117-129`). Three variables, not two:
>
> ```bash
> BAYRAM_ENV_FILE=<the bot env file, which must contain BAYRAM_DB_MIGRATION_URL> \
> BAYRAM_ADMIN_AUDIT_DSN='postgresql+asyncpg://<owner>:…@…/<db>' \
> BAYRAM_DB_APP_ROLE=<the application role> \
>   python -m alembic -c migrations/alembic.ini upgrade head
> ```
>
> `BAYRAM_DB_MIGRATION_URL` may equally be exported into the same shell — the process environment
> wins over the dotenv file (`migrations/env.py:95-114`) — but one of the two must supply it.
> Before running, read the alembic output for the one-role WARNING quoted above: if it is
> there, stop, because the REVOKE that follows it is theatre. The command shape assumes a
> source checkout with `migrations/` present and alembic importable; `migrations/` is not in
> the wheel. **On this host there is no checkout and `migrations/` is on disk anyway**, at
> `/opt/hbd/migrations` with alembic 1.19.2 in `/opt/hbd/venv` `[HOST 2026-09-11]`, so the shape
> that works there is `"$ROOT/venv/bin/python" -m alembic -c "$ROOT/migrations/alembic.ini"
> upgrade head` after `set -a; . <env file>; set +a` — which is also how the three variables above
> would reach it from a file rather than from a shell. See §"What the host settles and what it does
> not", and do **not** use `/usr/local/bin/hbd-migrate`, which is broken
> (`00-host-inventory.md` row 48).
>
> Then confirm with `chainProtection` on `/api/audit/verify`, or `\dp admin_audit_log` in
> psql. Do not infer it from the fact that the variables were set.

Two related facts about the DSNs, both from the repo rather than from any host:

- **`.env.admin.example:48` ships the admin process connecting as the owner role `hbd`,**
  contradicting `.env.example:35` (`hbd_app`), `docker/initdb/10-two-roles.sql` and
  README.md:160-161, all of which say the application processes connect as `hbd_app`. The admin
  API is the process that *writes* `admin_audit_log`; pointing it at the owner defeats the
  REVOKE even on a deployment that applied it. Give the admin process the **application**
  role's DSN.
- **`docker/initdb/10-two-roles.sql` is a local development artefact** with a hardcoded
  password and runs only once, on an empty Docker volume. The file itself says so
  (`docker/initdb/10-two-roles.sql:25-33`): "In staging or production, create these two roles
  by hand with real secrets." Nothing in this repository creates production roles — including
  the `ALTER DEFAULT PRIVILEGES FOR ROLE hbd … GRANT … TO hbd_app` lines
  (`docker/initdb/10-two-roles.sql:46-49`), without which every table a *future* migration
  creates is invisible to the application role.

---

## Notable optional variables, by subsystem

Defaults are the shipped values. Only the ones with a production consequence are here; the
rest are in the example files with their reasoning.

### Runtime, on all three classes

| Variable | Class | Default | Consequence |
| --- | --- | --- | --- |
| `BAYRAM_ENVIRONMENT` | all three | `dev` | The seven refusals above. Free-form `str` on `Settings` (`src/bayram/config.py:170`); closed literal on `AdminSettings` (`:169`) and on `PaymeSettings` (`src/bayram/payme/settings.py:115`, `:162`). **`prod` / `prod` / `prod` / `dev` on this host** `[HOST 2026-09-11]`. |
| `BAYRAM_LOG_LEVEL` | all three | `INFO` | Refused at `DEBUG` in prod on the admin (`src/bayram/admin/settings.py:589-593`) **and on the gateway** (`src/bayram/payme/settings.py:330-338`) — the latter inert here, where the gateway is `dev`. |
| `BAYRAM_IS_DEBUG` | all three | `false` | **Changes the log *format*, not the level.** `configure_logging(level, is_json=not is_debug)` — true switches the whole stream from one JSON object per line to human text (`src/bayram/logging.py:230-243`; callers `src/bayram/main.py:220`, `src/bayram/worker.py:36`, `src/bayram/admin/app.py:314`). Turning it on to get detail silently breaks any log shipper's parsing — and on this host all four units feed **one** journal, so the breakage is fleet-wide for anything parsing it `[HOST 2026-09-11]`. |
| `BAYRAM_USE_FAKE_PROVIDERS` | `Settings` | `false` | Refused outright in prod (`src/bayram/runtime/providers.py:105`). |

The bot and worker have **no** prod refusal on DEBUG. The mitigation on that side is the
floor in `configure_logging`, which pins `sqlalchemy`, `sqlalchemy.engine`,
`sqlalchemy.pool`, `aiogram`, `arq` and `uvicorn.access` at `max(WARNING, root.level)`
(`src/bayram/logging.py:100-113, :247-248`) — real, and applied in every process, but a policy
inside a module rather than a boot-time refusal.

### Vendors and spend

| Variable | Class | Default | Consequence |
| --- | --- | --- | --- |
| `BAYRAM_MUSIC_MAX_CONCURRENCY` | `Settings` | `2` (`src/bayram/config.py:195-200`) | A per-**process** `asyncio.Semaphore` (`src/bayram/runtime/container.py:332-333`), not a fleet cap. Two worker replicas at the default make 4 simultaneous renders against a vendor ceiling of 2. |
| `BAYRAM_MUSIC_USD_PER_MINUTE` | `Settings` | `0.15` (`src/bayram/config.py:207-217`) | **The only non-zero rate in the card**, and it is a placeholder list price. Every other leg ships `0.0`, which means "not priced" (`cost_usd` NULL, panel prints "not priced") and never "free". Until an operator fills the card in, the Vendors screen's spend total is a true sum over a minority of calls. No refusal behind this. |
| `BAYRAM_VENDOR_BALANCE_POLL_ENABLED` | `Settings` | `true` (`src/bayram/config.py:313`) | Off, or under fakes, the hourly cron registers and no-ops; the balance tiles render "not polled", which is indistinguishable from a worker that is down. **On this host it is on and working**: `vendor balance poll finished {"polled": 2, "succeeded": 2, "failed": 0}` against `elevenlabs_subscription` and `openrouter_key`, both HTTP 200, hourly at `:43` `[HOST 2026-09-10]`, re-read 09:43 +05 `[HOST 2026-09-11]`. |
| `BAYRAM_OPENROUTER_MANAGEMENT_KEY` | `Settings` | `""` (`src/bayram/config.py:248-262`) | **Optional, and the sharpest credential in the tree** (D13). An OpenRouter *management* key — not an inference key — read by one caller only: the hourly balance poll, which spends it on `GET /api/v1/credits` and only when `GET /api/v1/key` reported no cap (`src/bayram/runtime/vendor_balance_probes.py`). It buys the account's prepaid pool, which is what lets the panel draw remaining as a **fraction**; without it the row stays `is_unbounded` and the pill's ring is fully dashed. It belongs to the **primary** account (`BAYRAM_LLM_API_KEY`'s) — the fallback row is never read with it, because the variable cannot say which account it is for. It can create and revoke API keys, so it is in `VENDOR_SECRET_FIELDS` (a prod admin host is refused it) and **not** in `REQUIRED_VENDOR_SECRET_FIELDS` (every process starts without it). Adds no egress host: `/credits` is on `BAYRAM_LLM_BASE_URL`. **Most likely unset on this host** — no `openrouter_credits` probe appears in either pass's poll output, only `openrouter_key` `[HOST 2026-09-11]`. That is **inference, not observation**: the variable itself is `[UNPROVEN]` behind the `/etc/hbd` wall, and an absent probe is also what a failed probe would look like. |
| `BAYRAM_ELEVENLABS_BASE_URL`, `BAYRAM_LLM_BASE_URL` | `Settings` | `https://api.elevenlabs.io`, `https://openrouter.ai/api/v1` | The two vendor hosts the bot and worker reach on the primary path, plus `api.telegram.org` (`src/bayram/runtime/providers.py:133-150`). The admin host needs none of them. **Not the whole egress list when failover is configured — see the row below.** |
| `BAYRAM_LLM_FALLBACK_BASE_URL` | `Settings` | `""` (`src/bayram/config.py:251-252`) | Empty means "the adapter's own default host", which for the shipped `llm_fallback_provider="openai"` (`:247-249`) is `https://api.openai.com` (`src/bayram/providers/llm/openai_compat.py:69`) — a **third** vendor host, reached as soon as `BAYRAM_LLM_FALLBACK_API_KEY` is non-empty (`src/bayram/providers/llm/factory.py:158-168`, built at `src/bayram/runtime/providers.py:151`). Egress rules written from the row above alone will silently break the documented failover. Set this explicitly if the fallback must go somewhere else. |

### Queue and worker

| Variable | Class | Default | Consequence |
| --- | --- | --- | --- |
| `BAYRAM_WORKER_CONCURRENCY` | `Settings` | `15` (`src/bayram/config.py:632`) | `max_jobs` on the ARQ worker (`src/bayram/runtime/jobs.py:772`). It does **not** need to respect the vendor ceiling in the row above, and must not be lowered to it: simultaneous renders are already bounded independently by a per-process `asyncio.Semaphore(music_max_concurrency)` (`src/bayram/runtime/container.py:332`). Setting this to 2 would throttle every job that is not rendering music — settlement, delivery, balance polls — for nothing. |
| `BAYRAM_QUEUE_JOB_TIMEOUT_S` | `Settings` | `900.0` (`:633`) | Also feeds the derived settlement grace — see the next row. |
| `BAYRAM_QUEUE_MAX_TRIES` | `Settings` | `5` (`:638-648`) | Same. |
| `BAYRAM_SETTLEMENT_GRACE_S` | `Settings` | `None` → **derived** (`:548-556`) | The only field whose unset value is a derivation rather than a constant: `queue_job_timeout_s × queue_max_tries` plus backoff deferrals, 4550s under shipped defaults. `.env.example:317` ships it commented out, and that is correct — a fixed grace shorter than the queue ladder makes the sweep refund orders that are still rendering. |

### Broadcasts (the newsletter pipeline)

Three knobs and one credential note. All four matter on the **worker**; the panel composes a
campaign and enqueues it, and holds none of these.

| Variable | Class | Default | Consequence |
| --- | --- | --- | --- |
| `BAYRAM_BROADCAST_SEND_RATE_PER_S` | `Settings` | `12` (capped at 30) | Outbound messages per second **across every worker replica**, enforced through a Redis counter (`src/bayram/runtime/pacer.py`). Telegram limits at ~30/s per BOT TOKEN, and exceeding it earns a flood wait on the token — which stops the paid orders, not merely the campaign. Reminders will share this bucket by name; do not give a second feature its own key. |
| `BAYRAM_BROADCAST_CHUNK_TIMEOUT_S` | `Settings` | `120.0` | How long one send chunk (≤200 messages) may hold a worker slot. Deliberately not `BAYRAM_QUEUE_JOB_TIMEOUT_S`: 900s is sized for a music render, and a 50 000-recipient campaign is 250 chunks. **Not a knob to shorten** — the timeout is a cancellation, and a cancelled chunk leaves its claimed rows unresolved (they become `unknown`, counted as neither sent nor failed). |
| `BAYRAM_BROADCAST_SENDING_LEASE_S` | `Settings` | `300.0` | How long a claimed recipient may sit in `sending` before the five-minutely sweep retires it to `unknown`. **Must exceed the chunk timeout**, or a merely slow chunk is written off underneath itself. It is also what "this campaign has stalled" means to the sweep. |
| `BAYRAM_ADMIN_AUDIT_HMAC_KEY` | *not a `Settings` field* | unset | Normally the **panel's** variable (see "Required for the admin API"). The worker reads it, and only for one thing: the `broadcast.sent` OUTCOME audit row it writes when a campaign finishes, which has to be chained like every other audit row. **Unset is supported** — the campaign row and its six counters are the operational record either way — and the worker logs at ERROR that the outcome row was skipped. A deployment that wants the accountability copy sets the *same value* here as the panel holds; that widens where the chain key lives, which is why it is opt-in rather than required. It is deliberately not a field on `Settings`: every secret-shaped field there is a credential the ADMIN host is refused at boot, and this is the one secret the admin host cannot run without. |

### Entitlements and price

| Variable | Class | Default | Consequence |
| --- | --- | --- | --- |
| `BAYRAM_CREDITS_ENFORCED` | `Settings` | `false` (`src/bayram/config.py:494-497`) | Ships the meter dark. With the checkout wired, the bot logs the WARNING "the checkout is wired but the credit meter is dark" at boot and **never refuses** (`src/bayram/main.py:177-189`): the customer is shown a price and charged, and the worker covers the shortfall with an `UNENFORCED_RENDER` grant, so the render happens whether or not the payment did. `true` is the intended production setting once a price is on screen. **This is the live state of the production host** — see the callout below. |

> **`HBD_CREDITS_ENFORCED` is `false` on the machine that took its first real Payme settlement,
> and the bot says so out loud at every boot.** The WARNING
> `{"level": "WARNING", "message": "the checkout is wired but the credit meter is dark",
> "context": {"credits_enforced": false}}` was emitted at the 2026-09-10 boot and again at
> 2026-09-11 06:50 `[HOST 2026-09-10]` `[HOST 2026-09-11]`, and the gateway on the same box
> reports one settled transaction with one receipt and one grant written
> (`00-host-inventory.md`; [09-payme-go-live.md](09-payme-go-live.md)). So the row above has
> stopped being an explanation of a default and become a description of production: a customer is
> shown a price, charged through a real rail, and rendered for regardless. **This is a decision
> with a date, not a defect** — the owner's 2026-09-10 call to leave the stub paywall as it is, in
> `09-payme-go-live.md` §6 — but the decision was taken when the rail was a stub, and the rail is
> no longer a stub. Flipping it to `true` is one variable, one file and one restart; the cost of
> flipping it is that every customer without credits stops being able to render, which is why it
> is not a change to make without reading that section first.
| `BAYRAM_FREE_ALLOWANCE_CREDITS` | `Settings` | `0` (`src/bayram/config.py:527-534`) | 0 is the product decision, not a conservative default. Must be mirrored — see below. |
| `BAYRAM_GREETINGS_PER_KIT` | `Settings` | `0` (`src/bayram/config.py:406-411`) | 0 sells a song-only kit and buys no speech at all. |

### Host tooling

| Variable | Class | Default | Consequence |
| --- | --- | --- | --- |
| `BAYRAM_FFMPEG_BINARY` / `BAYRAM_FFPROBE_BINARY` | `Settings` | `ffmpeg` / `ffprobe` (`src/bayram/config.py:414-415`) | "On PATH" is the *default*, not the requirement — a host with ffmpeg somewhere unusual needs a config line, and the refusal message names the variable (`src/bayram/audio/startup.py:35-38`). `verify_host` refuses on either binary missing and on an ffmpeg build without a `libopus` encoder (`src/bayram/runtime/startup.py:23-25`, `src/bayram/audio/startup.py:93-103`). It is called by the bot, the worker and the demo only — **never by the admin API or the Payme gateway**, which need no ffmpeg at all. **At the default on this host, and satisfied by a real build**: `host verified` carries `"ffmpeg": "ffmpeg"` (the bare name, so `PATH` resolution is in play), `audio.startup.ready` resolves it to `/usr/bin/ffmpeg` + `/usr/bin/ffprobe`, and `ffmpeg 6.1.1-3ubuntu5` lists `A....D libopus  libopus Opus (codec opus)` `[HOST 2026-09-11]`. |
| `BAYRAM_I18N_STRICT` | none — read directly | **not strict** in any production process (`src/bayram/i18n/translator.py:51-56`) | Undocumented in both example files. `is_strict_by_default()` returns the parsed value of this variable when it is set, and otherwise returns whether `PYTEST_CURRENT_TEST` is in the environment — so unset means strict under pytest and **lenient everywhere else**, despite the function's own docstring at `:52` saying the opposite. Strictness is consumed only at render time (`:166-178`: raise on a missing key or parameter if strict, else log at ERROR and degrade to the key name). Leave it unset in production: on this side a copy bug should not take down a delivery. |

Catalogue *loading* is separate from strictness and is not configurable: `verify_host` calls
`get_translator()` (`src/bayram/runtime/startup.py:28`), which force-loads every catalogue
(`src/bayram/i18n/translator.py:184`) whatever `BAYRAM_I18N_STRICT` says. A malformed locale file is
therefore a boot failure on the bot and the worker in every environment — but a *missing key*
in a well-formed file is not, and reaches a customer as the key name.

### Admin: proxy, probes, volumes

| Variable | Class | Default | Consequence |
| --- | --- | --- | --- |
| `BAYRAM_ADMIN_TRUSTED_PROXY_HOPS` | `AdminSettings` | `0` (`src/bayram/admin/settings.py:216`) | `X-Forwarded-For` is ignored entirely unless hops > 0 **and** the peer is inside a configured CIDR (`src/bayram/admin/security/clientip.py:142`). Behind a reverse proxy at the defaults, every request resolves to the proxy's own address — which collapses the strict per-`(username, ip)` login counter into one global bucket per username and writes a constant into `admin_audit_log.ip`. Set it to the exact number of proxies you control. **The right number on this host is 2, and whether the file says so is `[UNPROVEN]` — see the callout.** |
| `BAYRAM_ADMIN_TRUSTED_PROXY_CIDRS` | `AdminSettings` | `()` (`:217`) | The addresses those proxies connect from. A typo fails the boot naming the variable (`:486-499`). |
| `BAYRAM_ADMIN_PROBE_TOKEN` | `AdminSettings` | `""` (`:426-428`) | Empty authorises nobody, and there is deliberately no default token to forget to change — but until it is set, `/readyz` answers a constant `{"status":"ok"}` to every monitor **even with the database and Redis both down** (`src/bayram/admin/routers/health.py:126-138`). Note the field has no `min_length`, unlike the HMAC key. |
| `BAYRAM_ADMIN_DATA_ROOT` | `AdminSettings` | `var` — **relative** (`:423`) | The panel reads `<root>/archive` through the `Storage` seam. The bot and worker have **no equivalent variable**: their root is `Path.cwd()/"var"` (`src/bayram/runtime/container.py:286`) and `bayram.main.run` never receives an override (`src/bayram/main.py:222`). The two agree only if the processes share a working directory. If they disagree, every media reveal in the panel returns "no such object" while the database row says the file exists — with no configuration error anywhere. **They do share one on this host**: `WorkingDirectory=/var/lib/hbd` on all four units, and the bot resolves `workspace: /var/lib/hbd/var/workspace`, so the relative default resolves to the same `/var/lib/hbd/var` `[HOST 2026-09-11]`. Whether the variable is **set** — which is the one thing that could break the agreement — is `[UNPROVEN]`: it appears in no boot line and the file is unreadable. `00-host-inventory.md` rows 2 and 30. |
| `BAYRAM_ADMIN_AUDIT_DSN` | `AdminSettings` | `""` (`:235`) | Empty is a supported deployment and reports `hmac-only`. Note the docstring at `:231-234` names migration **0006**; the REVOKE is in **0007** (`migrations/versions/20260830_1000_0007_add_admin_audit_log.py:369`), which is what `.env.example:39`, README.md:162 and `migrations/env.py:8` correctly say. |
| `BAYRAM_ADMIN_ARGON2_MEMORY_KIB` | `AdminSettings` | `65536` (`:212`) | Load-bearing rather than a tunable: the password floor is length-only, 8 characters (`src/bayram/admin/schemas/common.py:31-38`), so argon2 cost and the login throttle are the whole defence. Raise until a verify takes 250–500 ms on the host. |

> **`BAYRAM_ADMIN_HOST` and `BAYRAM_ADMIN_PORT` bind nothing.** They are declared
> (`src/bayram/admin/settings.py:188-189`) and their only readers in the tree are the display
> fields of `GET /api/config` (`src/bayram/admin/schemas/config_view.py:108-109, :202-203`). The
> actual bind comes from the uvicorn command line — `Makefile:75` passes
> `--host 127.0.0.1 --port 8080`. Setting `BAYRAM_ADMIN_PORT=9000` changes what the config screen
> *claims* and not what the process listens on, and the comment beside the field ("Binding
> 0.0.0.0 publishes a password login to the internet") reads as if the field enforced
> something it does not. Loopback binding is a property of whatever command starts the
> process; the panel's own config screen is not evidence about it.

> **`BAYRAM_ADMIN_CONFIG_ENABLED` is inert today.** It defaults to `true`
> (`src/bayram/admin/settings.py:185`) and `.env.admin.example:57-60` presents it as protecting
> "the riskiest surface in the panel" from a stolen session. No endpoint reads it: the only
> other references are its `ConfigView` projection and prose in
> `src/bayram/admin/routers/config.py:10`. `Permission.CONFIG_WRITE` exists and is attached to no
> route, and `src/bayram/admin/routers/` contains no config-write endpoint. Do not count it as an
> armed control.

> **`HBD_ADMIN_TRUSTED_PROXY_HOPS` got more wrong on 2026-09-09 and nothing reported it.**
> Admin traffic is now **two proxies deep** — Cloudflare's edge terminates TLS, a tunnel carries
> the request as plain HTTP to `127.0.0.1:80`, and Caddy proxies it to `127.0.0.1:8080`
> `[HOST 2026-09-11]`. The Caddyfile is the only place in the whole system that states the
> consequence, and it states it in a comment rather than anywhere enforceable
> (`/etc/caddy/Caddyfile:69-70`):
>
> ```
> #     HBD_ADMIN_TRUSTED_PROXY_HOPS=2
> #     HBD_ADMIN_TRUSTED_PROXY_CIDRS=127.0.0.1/32
> ```
>
> **Whether the deployed file carries those values is `[UNPROVEN]`**, and there is no way to infer
> it: `/etc/hbd/hbd-admin.env` is unreadable, the variables appear in no boot line, and the
> `admin.request` log line carries only `event`, `method`, `route`, `status` and `duration_ms` —
> **no client IP field at all** `[HOST 2026-09-11]`. The topology that made `2` the right answer
> was put in place on 2026-09-09, after whatever wrote that file. At the shipped default of `0`
> the panel keeps looking perfectly healthy while every audit row's `ip` and every login
> rate-limit bucket collapses onto Caddy's loopback address. Answering it needs root, and the
> command is `sudo grep -nE '^HBD_ADMIN_TRUSTED_PROXY' /etc/hbd/hbd-admin.env`.
> `00-host-inventory.md` row 23.

---

## The Payme gateway — a third class, a third file, and the only credential that mints credits

The gateway was added to the fleet on 2026-09-09 and took its first real settlement on
2026-09-10. `PaymeSettings` is **20 `Field()` declarations** (`src/bayram/payme/settings.py`)
against 20 assignments in `.env.payme.example` `[TREE 2026-09-11]`, selected by
`BAYRAM_PAYME_ENV_FILE` — `/etc/hbd/payme.env`, `root:hbd 0640`, on this host.

| Variable | Default | Consequence |
| --- | --- | --- |
| `BAYRAM_PAYME_ENABLED` | `false` (`:184`) | The lifespan refuses to boot while it is false, **unconditionally** — not gated on environment (`src/bayram/payme/app.py:233`, called at `:631`). A booted gateway therefore proves it is `true`. |
| `BAYRAM_PAYME_MERCHANT_KEY` | `SecretStr("")` (`:209`) | The cashbox key, and the **only** credential this process holds. It is an *inbound verification* secret — compared against itself to decide whether a call really came from Payme. Stealing it mints credits against our own database; it cannot message a customer and cannot spend a dollar of vendor balance. `_refuse_a_blank_key` is also unconditional (`app.py:238`, `:632`). |
| `BAYRAM_PAYME_MERCHANT_ID` | `""` (`:202`) | Printed in `payme.boot.ok`, so it is the one identity fact readable without privilege. |
| `BAYRAM_PAYME_ACCOUNT_FIELD` | `order_id` (`:219`) | The requisite name registered in the Payme cabinet. A mismatch between this and the cabinet is a rejected payment, not a boot failure. |
| `BAYRAM_PAYME_BASIC_LOGIN` | `Paycom` (`:214`) | The basic-auth username Payme sends. Changing it without changing the cabinet breaks every inbound call. |
| `BAYRAM_PAYME_IS_SANDBOX` | `false` (`:242`) | Which cashbox the credentials belong to. **Independent of `BAYRAM_ENVIRONMENT`** — a sandbox cashbox in `prod`, or a live cashbox in `dev`, are both legal and neither is checked. |
| `BAYRAM_PAYME_HOST` / `_PORT` | `127.0.0.1` / `8091` (`:189-190`) | Same trap as `BAYRAM_ADMIN_HOST`/`_PORT`: the real bind is the uvicorn command line. |
| `BAYRAM_PAYME_TRUSTED_PROXY_HOPS` | `0`, `ge=0 le=4` (`:261`) | The gateway's own copy of the hops problem, and it is **also** two proxies deep on this host. `[UNPROVEN]` on disk. |
| `BAYRAM_PAYME_ALLOWED_CIDRS` | `()` (`:269`) | Caller allowlist. Empty on purpose here — see `00-host-inventory.md` row 38 for why a Payme IP allowlist is moot behind Cloudflare. |
| `BAYRAM_PAYME_DUPLICATE_TRANSACTION_CODE` | `-31008` (`:226`) | Rail-protocol detail, printed at boot. |
| `BAYRAM_PAYME_PROBE_TOKEN` | `""` (`:193`) | Same shape as the admin probe token: empty authorises nobody. |
| `BAYRAM_PAYME_ENVIRONMENT` | `dev`, closed `Literal["dev","staging","prod"]` (`:115`, `:162`) | **The one to read first.** `is_production` is `== "prod"` (`:348`), and two boot controls hang off it — see the refusal table at the top of this page. |
| `BAYRAM_PAYME_DATABASE_URL` | **none**, `Field(min_length=1)` (`:171`) | The fourth field in the tree with no default. |

**What the host's gateway actually reports**, from `payme.boot.ok` and `payme.container.built`
`[HOST 2026-09-10]`, re-read at the 2026-09-11 06:49 boot:

```
payme.container.built  {"environment": "dev", "pool_size": 3, "database": "127.0.0.1:5432/hbd",
                        "merchant_id": "6aa24fd9ee30563de3a1ac22", "is_sandbox": true}
payme.boot.ok          {"environment": "dev", "env_file": "/etc/hbd/payme.env",
                        "merchant_id": "6aa24fd9ee30563de3a1ac22", "is_sandbox": true,
                        "account_field": "order_id", "basic_login": "Paycom",
                        "duplicate_transaction_code": -31008, "merchant_key_length": 36}
```

Note what that line is careful about: it prints the key's **length**, never the key. Nine of the
twenty variables are answerable from it without any privilege at all, which is more than any other
process on this host offers — and it is the only one of the four whose `env_file` field names the
file that was really read.

The deployment details — the cabinet settings a human types, the endpoint registration, the
certification and reconciliation runbooks — are [08-payme.md](08-payme.md) and
[09-payme-go-live.md](09-payme-go-live.md), not this page. What belongs here is the single
configuration fact an operator must not miss: **`environment` is `dev` on a production host**, and
it disarms two of this class's boot controls.

---

## Owned by all three classes — five variables, three files

> **SUPERSEDED 2026-09-11, kept because it dates the change.** This section was headed "five
> variables, two files" and argued the drift hazard between the bot's file and the panel's. There
> is a third file now, and the hazard is no longer hypothetical — it is the state of the
> production host.

`BAYRAM_ENVIRONMENT`, `BAYRAM_LOG_LEVEL`, `BAYRAM_IS_DEBUG`, `BAYRAM_DATABASE_URL` and `BAYRAM_REDIS_URL`
are fields on **all three** models (`src/bayram/config.py:170-173, :187-188`;
`src/bayram/admin/settings.py:169-171, :174-175`; `src/bayram/payme/settings.py:162-164`, `:171`,
`:177`) and must be written into all three files. Only the DSN and the Redis URL are meant to
match. The first three are independently settable and independently enforced, and **nothing
cross-checks them**: `BAYRAM_ENVIRONMENT=prod` in the bot's file with `dev` left in another is a
completely legal, silent state in which the bot refuses fake providers while the other process
permits DEBUG logging, permits a default origin, and downgrades its vendor-credential refusal to a
warning nobody is watching.

> **That is exactly the state of this host, in the third file.** `prod` / `prod` / `prod` / **`dev`**
> across bot, worker, panel and gateway `[HOST 2026-09-10]`, re-confirmed `[HOST 2026-09-11]`. The
> page's own argument — that this is the most dangerous shape available because it is legal and
> silent — is now a description rather than a warning, and the process it landed on is the one
> holding the cashbox key. The one mitigation the code offers is that the panel's and gateway's
> `environment` are closed `Literal`s, so a *typo* cannot produce this; only a file saying `dev`
> can, and one does. Where the value is readable without privilege: all four boot lines print it.

Three further values are *mirrored* from the worker into `AdminSettings` because the panel
deliberately cannot read the bot's file — that separation is the vendor-key boundary
(`src/bayram/admin/settings.py:258-262`):

| Worker variable | Admin mirror | If they drift |
| --- | --- | --- |
| `BAYRAM_NAME_MATCH_MIN_SIMILARITY` | `BAYRAM_ADMIN_NAME_MATCH_MIN_SIMILARITY` | The threshold marker lands in the wrong place on the similarity histogram. Blank means "not published" and draws no marker, which is honest. |
| `BAYRAM_SETTLEMENT_GRACE_S` (or its derivation) | `BAYRAM_ADMIN_SETTLEMENT_GRACE_S` | `inFlightRenderCount` — the number that explains a refusal to a customer on the phone — diverges from the gate that produced the refusal. `AdminSettings` holds no queue fields, so it cannot re-derive; this must be set by hand whenever the queue ladder moves. |
| `BAYRAM_FREE_ALLOWANCE_CREDITS` | `BAYRAM_ADMIN_FREE_ALLOWANCE_CREDITS` | A wrong `creditsProjected`. This mirror exists *because* the defect shipped: defaulting the allowance added 3 credits to every account in the fleet, forever (`src/bayram/admin/settings.py:302-312`). |

> **`extra="ignore"` makes every one of these drifts silent.** Writing
> `BAYRAM_ADMIN_FREE_ALLOWANCE_CREDITS` into `.env` discards it; writing
> `BAYRAM_FREE_ALLOWANCE_CREDITS` into `.env.admin` discards it; a typo'd prefix in either file
> is a no-op with no error. And of the three mirrors, the allowance is the one **not** yet
> published on `GET /api/config` — its own docstring admits it
> (`src/bayram/admin/settings.py:322-326`): "the only way to spot drift is to compare the two
> deployments' environments by hand". The other two are on that screen
> (`src/bayram/admin/schemas/config_view.py:140, :147`), which is the intended remedy.

---

## Two defects in `.env.admin.example` to fix before copying it

Both were verified against this working tree, not inferred.

**1. Seven variables parse as their own trailing comment.** python-dotenv strips an inline
`#` comment only when the value before it is non-empty; every one of these lines is blank
before the `#`, so the comment *becomes* the value:

```
BAYRAM_ADMIN_TRUSTED_PROXY_CIDRS        .env.admin.example:114
BAYRAM_ADMIN_NAME_MATCH_MIN_SIMILARITY  :155
BAYRAM_ADMIN_SETTLEMENT_GRACE_S         :171
BAYRAM_ADMIN_UZS_PER_USD                :216
BAYRAM_ADMIN_UZS_PER_USD_AS_OF          :217
BAYRAM_ADMIN_SINGLE_SONG_PRICE_MINOR    :235
BAYRAM_ADMIN_KIT_CURRENCY               :236
```

Every one is a variable whose own comment says to leave it blank. The
`_blank_mirror_means_unpublished` validator (`src/bayram/admin/settings.py:433-465`) exists
solely to make that work and states at `:449` that "the example file ships the variables
blank, so this is the path an untouched deployment actually takes" — it is not that path,
because the values are never blank as parsed, so the validator never fires.

**2. `BAYRAM_ADMIN_COOKIE_SECURE=` is genuinely blank and is a separate failure.** The field is
`bool | None` (`src/bayram/admin/settings.py:197`) and pydantic cannot read an empty string as
either; it is on neither blank-tolerating validator's list. The example file's own line 91
instructs "Leave empty".

Copying the file verbatim therefore produces nine validation errors, before anything
host-specific is even reached. To see them the way an operator would — as the tidy message
rather than as a traceback — catch the `ConfigError`:

```bash
BAYRAM_ADMIN_ENV_FILE=.env.admin.example python -c "
from bayram.admin.settings import build_admin_settings
from bayram.errors import BayramError
try:
    build_admin_settings()
except BayramError as exc:
    print(exc.operator_message)
"
```

That prints:

```
The admin panel's configuration is invalid or incomplete. Fix these environment variables (see .env.admin.example):
  BAYRAM_ADMIN_COOKIE_SECURE: Input should be a valid boolean, unable to interpret input
  BAYRAM_ADMIN_TRUSTED_PROXY_CIDRS: Value error, BAYRAM_ADMIN_TRUSTED_PROXY_CIDRS contains an unparsable entry: '# comma-separated'
  BAYRAM_ADMIN_AUDIT_HMAC_KEY: Value should have at least 32 items after validation, not 0
  BAYRAM_ADMIN_NAME_MATCH_MIN_SIMILARITY: Input should be a valid number, unable to parse string as a number
  BAYRAM_ADMIN_SETTLEMENT_GRACE_S: Input should be a valid integer, unable to parse string as an integer
  BAYRAM_ADMIN_UZS_PER_USD: Input should be a valid number, unable to parse string as a number
  BAYRAM_ADMIN_UZS_PER_USD_AS_OF: Input should be a valid date or datetime, invalid character in year
  BAYRAM_ADMIN_SINGLE_SONG_PRICE_MINOR: Input should be a valid integer, unable to parse string as an integer
  BAYRAM_ADMIN_KIT_CURRENCY: String should have at most 3 characters
```

Without the `try`/`except`, the same call is a 54-line traceback whose *first* exception is a
raw `pydantic_core._pydantic_core.ValidationError: 9 validation errors for AdminSettings`; the
message above is only the last line of it. That is what a bare one-liner shows, and it is why
the boot paths catch (`src/bayram/admin/settings.py:666-680`).

Only `BAYRAM_ADMIN_AUDIT_HMAC_KEY` is a real "you have not filled this in yet". The other eight
are the file's own formatting. The fix in the file is to move each inline comment onto its
own line above the variable; the fix in a copy you have already made is to delete the eight
offending lines' values (and delete the `BAYRAM_ADMIN_COOKIE_SECURE` line entirely — `None` is
the default and it derives to `True`, `src/bayram/admin/settings.py:602-618`).

`.env.example` has no equivalent *formatting* problem: its inline-commented lines all have
non-empty values, so nothing there parses as its own comment. It does not boot as shipped,
though, and that is by design rather than a defect — it ships the three vendor secrets blank,
so `BAYRAM_ENV_FILE=.env.example load_settings()` fails with exactly three errors:

```
  BAYRAM_TELEGRAM_BOT_TOKEN: String should have at least 1 character
  BAYRAM_ELEVENLABS_API_KEY: String should have at least 1 character
  BAYRAM_LLM_API_KEY: String should have at least 1 character
```

(`src/bayram/config.py:697-699`, `_VendorBoundSettings`.) Those are the "you have not filled this
in yet" errors, not formatting ones — do not read them as the same class of problem as the
nine above.

### Three stale section headers in `.env.example`

`.env.example:384-388` still carries a "Retention, in days" header with no variables under
it and the claim "The purge job reads these" — which README.md:467-471 already identified as
false: "Retention is a policy object, not configuration… they were removed." The periods are
constants (`src/bayram/db/retention.py:61-76`). The same shape appears at `.env.example:157-162`
(object storage) and `:395-398` (free tier). Nothing under those headers is configurable;
ignore them.

---

## What is not covered here

Seven `BAYRAM_*` variables outside the three settings classes are read by real code: the five
selector-and-role variables (`BAYRAM_ENV_FILE`, `BAYRAM_ADMIN_ENV_FILE`,
**`BAYRAM_PAYME_ENV_FILE`**, `BAYRAM_DB_MIGRATION_URL`, `BAYRAM_DB_APP_ROLE`), plus
`BAYRAM_ADMIN_AUDIT_DSN` in the migration bodies and `BAYRAM_I18N_STRICT`. The three `*_ENV_FILE`
variables are correctly explained in prose rather than as lines, because writing them into the file
they select is a no-op — `.env.example:5-11` and `.env.admin.example:5-11` both say so.
**`BAYRAM_DB_APP_ROLE` is the real gap**: it names the role the audit REVOKE is taken from and
appears in no example file, so an operator has no way to discover it exists.

Everything else — every one of the **103** `Settings` fields, all **37** `AdminSettings` fields and
all **20** `PaymeSettings` fields — is present in its example file with the reasoning attached.

> **The coverage claim and the date its check was last run, 2026-09-11.** The counts above are
> `Field(` declarations at class-body indentation (103 / 37 / 20) against top-level assignments in
> the example files (`.env.example` 100, `.env.admin.example` 37, `.env.payme.example` 20)
> `[TREE 2026-09-11]`. The assignment-vs-field *diff* this paragraph used to assert — "nothing is
> missing from either" — was last run across **two** class/file pairs when the page was written on
> 2026-09-07, and the `.env.example` count is 100 against 103 fields, so it no longer closes. Treat
> the sentence as a method, not a verdict: re-run the diff across all three pairs before relying
> on it, and re-state the date rather than the number.

The files are **not** disjoint, and must not be: the five shared-ownership variables above
(`BAYRAM_DATABASE_URL`, `BAYRAM_ENVIRONMENT`, `BAYRAM_IS_DEBUG`, `BAYRAM_LOG_LEVEL`,
`BAYRAM_REDIS_URL`) are fields on all three classes and appear in all three files, which is the
intended state. The only assignment in any of them that is not a field of its own class is
`BAYRAM_DB_MIGRATION_URL` in `.env.example`, explained above.

## What the host settles and what it does not

> **SUPERSEDED 2026-09-11, kept because it dates the change.** This section was headed "Host
> assumptions" and said every item below was *"a **proposal or an open question**, not a record"*.
> Most of them are now records. Two are still open, and the important change is **why**: not
> because nobody has looked, but because `developer` cannot read them and `root` is behind an
> interactive password. An open question invites a guess; a named wall does not.

Everything above about the *code* was read out of this working tree. The passages that presuppose
a host fact are settled here, each with its method.

**Settled** `[HOST 2026-09-10]`, re-confirmed `[HOST 2026-09-11]`:

- **The install is a wheel, not a source checkout — and alembic is available anyway.**
  `/opt/hbd/venv` holds `hbd` from `hbd_bot-0.1.0-20260909-py3-none-any.whl`, no `.pth`, Python
  3.12.3. Because the wheel carries no `migrations/`, they are shipped **out of band** at
  `/opt/hbd/migrations` (through `0025`), with alembic 1.19.2 in the venv. The host's own cutover
  script runs it in this shape, which is worth copying because of the first line:

  ```bash
  set -a; . <the env file>; set +a
  "$ROOT/venv/bin/python" -m alembic -c "$ROOT/migrations/alembic.ini" upgrade head
  ```

  `set -a` is how `HBD_DB_MIGRATION_URL` reaches the migration runner **from the file** rather
  than from a systemd environment — the one place on this host where the dotenv file is read the
  way this page assumes. Note also that `/usr/local/bin/hbd-migrate` is **broken** and must not be
  used: it passes `"upgrade head"` as a single argument (`00-host-inventory.md` row 48).
- **The supervisor is systemd**, four units, `Restart=on-failure` / `RestartSec=5s` on the bot,
  worker and panel and `Restart=always` / `5s` on the gateway. A worker that fails at module import
  therefore retraces every five seconds until the start limit trips; the gateway retries forever.
- **The log pipeline is journald**, persistent, with no `Storage`, `MaxRetentionSec` or
  `SystemMaxUse` set — so retention is the distro default and the only bound is disk.
  `StandardOutput=journal` on all four units and nothing writes a file: `/var/log/hbd` is empty.
  **`BAYRAM_IS_DEBUG` is fleet-wide for anything parsing that stream**: it switches the format from
  one JSON object per line to human text (`src/bayram/logging.py:230-243`), and all four units feed
  the same journal, so turning it on to get detail breaks every parse of every process at once.
- **The application role is real and is named `hbd_app`.** Every PostgreSQL backend on the box
  connects as it, to database `hbd` at `127.0.0.1:5432`, and **no backend connects as an owner
  role** — so `.env.admin.example:48`'s owner DSN was not copied here. `max_connections = 100`.
- **The two boot strings have a real log source**, given above, needing no `sudo`.

**Not settled, with the blocker named rather than left open.** `/etc/hbd` is `0750 root:hbd`, the
`hbd` group has **no members**, `sudo -n` refuses, and the `NOPASSWD` drop-in grants `pg_dump` but
**not** `psql` (`00-host-inventory.md` row 44). That one wall closes every question of the form "is
variable X set on the host" at once:

| `[UNPROVEN]` | Blocker | What would answer it |
| --- | --- | --- |
| `HBD_ADMIN_TRUSTED_PROXY_HOPS` / `_CIDRS` | file unreadable; `admin.request` logs no client IP | `sudo grep -nE '^HBD_ADMIN_TRUSTED_PROXY' /etc/hbd/hbd-admin.env` |
| `HBD_ADMIN_PROBE_TOKEN` — set or empty | same | `sudo grep -c '^HBD_ADMIN_PROBE_TOKEN=.\+' /etc/hbd/hbd-admin.env` |
| `HBD_ADMIN_DATA_ROOT` — set or defaulting | same; in no boot line | `sudo grep -n '^HBD_ADMIN_DATA_ROOT=' /etc/hbd/hbd-admin.env` |
| `HBD_DB_MIGRATION_URL` — set at all | same | `sudo grep -n '^HBD_DB_MIGRATION_URL=' /etc/hbd/hbd.env` |
| `HBD_ADMIN_AUDIT_DSN` — set at all | same | as above, in `hbd-admin.env`; or `chainProtection` on `GET /api/audit/verify` |
| `HBD_LLM_FALLBACK_BASE_URL` — set at all | same | as above, in `hbd.env` |
| `HBD_ADMIN_ARGON2_MEMORY_KIB` | same | as above — and a login timing on the host, for the 250–500 ms target |
| **whether an owner role exists, and whether `0007`'s `REVOKE` landed** | **`psql` refuses: `fe_sendauth: no password supplied`**, no peer path, not in the sudoers drop-in | `\dp admin_audit_log` as a role that can connect; or the panel's own badge |
| whether the audit HMAC key exists anywhere but `/etc/hbd/hbd-admin.env` | the file is unreadable, and **`pg_dump` cannot answer it** — a dotenv file is not in the database | a human who knows where the secret was written down |

**A database backup exists, and it is not scheduled.** `/var/backups/hbd` holds seven hand-taken
`pg_dump` files and there is no timer, no cron and no off-box copy — and **the HMAC key is in none
of them** (`00-host-inventory.md` rows 33–35). So the obligation this page states — keep the key
separately from the dump — is currently satisfied by accident rather than by arrangement, and the
other half of it (that a dump exists to keep it separate *from*) is satisfied only as often as
somebody remembers.

Beyond these: which files exist at which paths, what terminates TLS, and how the four processes are
started are all now recorded — in [01-architecture.md](01-architecture.md) and, authoritatively, in
[00-host-inventory.md](00-host-inventory.md). **`deploy/first-install-proposal.md` and
`deploy/systemd/*.service` describe the post-rename target state, not this machine**: they propose
`bayram-*` units, `/srv/bayram` and `/etc/bayram`, and `/srv` on the host is empty. Do not quote a
`bayram` path as though it existed on `abdu-test`, and do not read `deploy/` as a record.
