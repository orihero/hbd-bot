# Provisioning a host from bare metal

**`aizu` is already provisioned. Do not run this document against it.**

This is two things and neither of them is a deploy script:

1. **The record of what a correct host looks like** — every step, why it exists, and how you
   know it worked. Written from the repository, so every claim here is checkable against a
   file and a line number.
2. **The list to compare `aizu` against.** Where a step here produces observable state — a
   role in `pg_roles`, a file mode, a log line, a field in an API response — that observation
   is the comparison. Read it as an audit checklist, not as a runbook to replay.

## STATUS — the audit has been run. 2026-09-11.

**The checklist has been compared against `aizu`, and §13 now carries the result row by row
with a date on every answer.** Read §13 first if you came here to find out what the host
actually is; read the document top to bottom if you came here to find out what a correct host
looks like and why.

Short version of the result, because four of the answers change how you read everything above
them:

1. **Every path in this document is fictional for `aizu`.** `/srv` is empty — two entries, no
   children `[HOST 2026-09-11]`. The service account is `hbd`, the code is a **non-editable
   wheel** in `/opt/hbd/venv`, the config is `/etc/hbd/*.env`, the data root is
   `/var/lib/hbd/var`. `/srv/bayram` and `/srv/hbd` have never existed. §2 carries the mapping.
2. **The two-role split does not exist on this host.** Every table in schema `public` is owned
   by the *application* role `hbd_app`; migration `0007` took its `_skip` branch; neither
   `SECURITY DEFINER` sweep function was created. §4 and §7 argue that control at length as
   though it were deployed. It is not. The audit answer is NO, with the evidence, in §4.
3. **Redis persistence is off.** §5 calls it non-optional; `appendonly` is `no`
   `[HOST 2026-09-11]`.
4. **Three of the four units use `EnvironmentFile=`**, which is the opposite of what §10
   argues for, so the vendor credentials *are* in the process environment on this host.

### The three marks

Same convention as [`01-architecture.md`](01-architecture.md)'s status block:

- **`[HOST 2026-09-11]`** — a read-only command was run against `aizu` (machine `abdu-test`) on
  that date and what is quoted is faithful to its output.
- **`[TREE 2026-09-11]`** — checkable by opening a file in this working tree; a `path:line` is
  given.
- **`[UNPROVEN]`** — exactly that, with the blocker named. Three rows of §13 are `[UNPROVEN]`
  and the blocker is the same for all three: `/var/lib/hbd` is `0750 hbd:hbd` and untraversable
  from `developer`, and `psql` is behind a password the `NOPASSWD` drop-in deliberately does not
  grant. **Those questions are not open for lack of looking.**

**The host is PRE-RENAME and that is correct.** Every *target-shape* command in this document is
spelled `bayram` / `BAYRAM_` / `/srv/bayram` because that is what this tree says; every *observed*
host fact is spelled `hbd` / `HBD_` / `/opt/hbd` because that is what the machine says. Both are
right at once — [`09-payme-go-live.md`](09-payme-go-live.md) §1.2. **Do not sweep this page with
a rename pass.**

> **SUPERSEDED 2026-09-10, kept because it dates the change.** This document said, until
> 2026-09-10: *"Nobody who wrote this has access to `aizu`. Everything below is what the code in
> this checkout requires. Nothing below is a statement about what is on that box."*
>
> Somebody does now. `ssh aizu` has been routine since 2026-09-09;
> [`00-host-inventory.md`](00-host-inventory.md) is the inventory of record,
> [`08-payme.md`](08-payme.md) §11 is the release runbook as actually executed, and
> [`09-payme-go-live.md`](09-payme-go-live.md) is written from the box throughout. The sentence
> was an honest limit when written and had become a reason not to check. **What has not changed
> is the document's job:** it is the *target shape* plus the audit list, not a runbook to replay
> — and §13 is now where the two meet.

> **The deploy proposal is a proposal — still, and more so.** `deploy/first-install-proposal.md`
> and `deploy/systemd/*.service` were authored in this repository without host access. They are
> a well-reasoned design for a host; they are not a record of one, and since the `hbd` → `bayram`
> rename landed in the tree they name paths and units that exist on no machine.
> [04-release.md](04-release.md) §0.3 is the per-file standing — including that the four
> proposed unit files **do not agree with each other** about where the code and the data root
> live — and §0.4 is the list of `deploy/` artefacts that would do the wrong thing if run today.
> Where this document cites them it says so, and it flags the places where following them
> verbatim does not do what they claim.

---

## 0. What you are provisioning

Three long-running processes and one command that is run by hand:

| what | command | needs |
| --- | --- | --- |
| the bot | `python -m bayram.main` (Makefile:83) | ffmpeg, Postgres, Redis, Telegram + vendor keys |
| the ARQ worker | `python -m arq bayram.worker.WorkerSettings` (Makefile:86) | the same, plus it is the only thing that runs the crons |
| the admin API | `python -m uvicorn bayram.admin.app:app --host 127.0.0.1 --port 8080` (Makefile:89) | Postgres, Redis, **no** ffmpeg, **no** vendor key |
| the schema | `python -m alembic -c migrations/alembic.ini upgrade head` (Makefile:196) | the owner DSN, a checkout on disk |

There is no console script for any of them. `pyproject.toml` has no `[project.scripts]`
table, so after installation there is no `bayram` or `bayram-worker` binary on `PATH` — every
supervisor entry must spell out the interpreter path plus `-m`. That also means nothing in
the package metadata pins these entry points: renaming `bayram.worker.WorkerSettings` breaks a
deploy silently.

> **The admin API needs a materially smaller host than the other two.** `verify_host` is
> called only from `src/bayram/main.py:100`, `src/bayram/worker.py:45` and `src/bayram/demo.py:179`.
> `src/bayram/admin/app.py` never imports it. An admin-only box needs no ffmpeg at all.

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

- `ffmpeg` on `PATH` (src/bayram/audio/startup.py:93)
- `ffprobe` on `PATH` (src/bayram/audio/startup.py:94)
- an ffmpeg build whose `-encoders` table contains `libopus` (src/bayram/audio/startup.py:96-103,
  with `REQUIRED_ENCODERS` at src/bayram/audio/constants.py:121 derived from
  `VOICE_NOTE_CODEC = "libopus"` at :113)

Without libopus, Telegram's `sendVoice` renders a greeting as a file attachment rather than a
voice note, which is why the check is a refusal rather than a warning. The probe has a 15
second ceiling (src/bayram/audio/constants.py:66) so a broken binary cannot hang a boot.

Verify:

```bash
ffmpeg -hide_banner -encoders | grep -E 'libopus|libmp3lame'
ffprobe -version | head -1
```

> **AUDIT ANSWER, `aizu`, PASS on both halves** `[HOST 2026-09-11]`. Ubuntu 24.04.4,
> kernel `6.8.0-137-generic`, ffmpeg/ffprobe `6.1.1-3ubuntu5`:
>
> ```
>  A....D libmp3lame           libmp3lame MP3 (MPEG audio layer 3) (codec mp3)
>  A....D libopus              libopus Opus (codec opus)
> ```
>
> This closes the §13 question that used to read *"a running bot proves the first and says
> nothing about the second"* — the second is now answered directly rather than inferred, which
> matters because the unmastered-song failure mode below has no error anywhere.

> **Check for `libmp3lame` even though nothing refuses without it.** The delivered song is
> written with the extension the vendor's MIME type implies — `audio/mpeg` becomes `.mp3`
> (src/bayram/pipeline/assets.py:75) — and `codec_args_for` pins a codec only for `.wav`
> (src/bayram/audio/commands.py:65-73), so ffmpeg infers the mp3 encoder from the suffix. The
> loudness master is explicitly non-fatal: `_normalized` falls back to the source file and
> never raises (src/bayram/pipeline/assets.py:129-133). An ffmpeg with libopus but no mp3
> encoder therefore passes the boot check and ships an unmastered song to every paying
> customer, with no error anywhere. The boot probe was written to prevent exactly this
> failure — for a different codec.

**ffmpeg does not have to be on `PATH`.** `BAYRAM_FFMPEG_BINARY` and `BAYRAM_FFPROBE_BINARY`
(src/bayram/config.py:414-415, documented at .env.example:233) take an absolute path, and the
"not found" message names them. A host with a custom build needs a config line, not a `PATH`
change.

**Postgres 16 and Redis 7** are what `docker-compose.yml` pins for local development
(`postgres:16-alpine`, `redis:7-alpine`). That file's first two lines say "Local dependencies
only", so those pins are a statement about the development stack, not a requirement the code
enforces. Nothing in `src/` asserts a server version.

---

## 2. The service user and the directory layout

> **AUDIT ANSWER: every path in this section, and in §3, §6, §7, §8, §9 and §10, is fictional
> for `aizu`.** `ls -la /srv/` returns two entries and no children — `/srv` is **empty**, and
> `/srv/bayram` and `/srv/hbd` have never existed on this machine `[HOST 2026-09-11]`. The shape
> below is the target; the machine's shape is this:
>
> | This document says | `aizu` actually has `[HOST 2026-09-11]` |
> | --- | --- |
> | user/group `bayram` | **`hbd`** (uid 995), `User=hbd Group=hbd` on all four units |
> | checkout at `/srv/bayram` | **no checkout at all.** `/opt/hbd` holds `venv/`, `release/`, `migrations/` and four loose scripts; `test -d /opt/hbd/.git` → `NO .git in /opt/hbd`. Owned `developer:developer` |
> | venv at `/srv/bayram/.venv` | **`/opt/hbd/venv`**, built by `/usr/bin/python3 -m venv`, holding a **non-editable wheel** install. §3 |
> | config at `/etc/bayram/*.env` | **`/etc/hbd/hbd.env`, `/etc/hbd/hbd-admin.env`, `/etc/hbd/payme.env`** — `/etc/hbd` is `0750 root:hbd`, so the file contents are `[UNPROVEN]` from `developer` |
> | `WorkingDirectory=/srv/bayram` | **`/var/lib/hbd`** on all four units |
> | data root `/srv/bayram/var` | **`/var/lib/hbd/var/workspace` and `/var/lib/hbd/var/archive`** by construction. Size `[UNPROVEN]`: `ls -la /var/lib/hbd` → `Permission denied` (`0750 hbd:hbd`) |
> | three processes | **four.** `hbd-bot`, `hbd-worker`, `hbd-admin`, `hbd-payme` — the gateway is [`08-payme.md`](08-payme.md)'s |
>
> **The one thing the host gets right that this section says nothing could enforce**: all four
> units share `WorkingDirectory=/var/lib/hbd`, so the bot's `Path.cwd() / "var"` and the panel's
> relative `BAYRAM_ADMIN_DATA_ROOT` do resolve to the same tree. That is the agreement the
> callout below calls "the load-bearing one", and on `aizu` it holds — by a single line repeated
> in four unit files, which is exactly as fragile as it sounds. Note that
> `deploy/systemd/bayram-payme.service:63` would break it if adopted: it alone says
> `WorkingDirectory=/var/lib/bayram` against `/srv/bayram` in the other three
> `[TREE 2026-09-11]`. See [04-release.md](04-release.md) §0.3.

```bash
sudo useradd --system --home-dir /srv/bayram --shell /usr/sbin/nologin bayram
sudo install -d -o bayram -g bayram /srv/bayram            # empty — git accepts an existing empty dir
sudo install -d -o root -g bayram -m 0750 /etc/bayram
sudo -u bayram git clone <repo> /srv/bayram
sudo install -d -o bayram -g bayram /srv/bayram/var        # AFTER the clone, not before
```

> **The proposal's version of this block cannot be run as written.**
> `deploy/first-install-proposal.md:84-86` creates `/srv/bayram` and `/srv/bayram/var` in one `install -d` and then
> clones into `/srv/bayram`. `git clone` refuses a destination that exists and is non-empty —
> `fatal: destination path '/srv/bayram' already exists and is not an empty directory` — so the
> proposal's fourth line dies every time. Creating `var` after the clone, as above, is the
> whole fix; cloning into an existing *empty* directory is allowed.

The paths come from the deploy proposal (deploy/first-install-proposal.md:60-65). The *shape* is forced by
the code:

**The data root is derived from the process working directory, and there is no variable that
moves it.** `build_container` computes `root = (data_root or Path.cwd() / "var").resolve()`
(src/bayram/runtime/container.py:286), creates `var/workspace` and `var/archive` under it
(:287-290), and `bayram.main.run` accepts a `data_root` argument that `main()` never passes
(src/bayram/main.py:222). There is no `data_root` field on `Settings`. So for the bot and the
worker, "where the songs live" is decided entirely by the directory the process is started
in.

The admin API gets its own knob, `BAYRAM_ADMIN_DATA_ROOT`, defaulting to the **relative** path
`var` (src/bayram/admin/settings.py:423) and joined with the archive directory name at
src/bayram/admin/container.py:155. Its docstring claims it is "the same directory
`bayram.runtime.container.build_container` is given as its `data_root`" — a claim no variable
enforces.

> **This is the load-bearing one.** If the admin process's working directory differs from the
> bot's, every media reveal in the panel returns "no such object" while the database row says
> the file exists, and there is no configuration error anywhere to explain it. Either run all
> three processes with the same `WorkingDirectory`, or set `BAYRAM_ADMIN_DATA_ROOT` to the
> bot's absolute `var` path. Do not rely on the two relative defaults agreeing by luck.

**`var/archive` holds two key namespaces with different lifecycles**, through one shared
`LocalFileStorage` instance (src/bayram/runtime/container.py:301-307, which explains why the
sharing is required): `orders/{order_id}/{filename}` (src/bayram/storage.py:84), swept on the
asset retention clock, and `users/{user_id}/avatar.jpg` (src/bayram/user_profiles.py:199-200),
deleted only by a customer's `/forget`. A filesystem backup of that tree is a backup of both
delivered songs and customer photographs; they cannot be scoped apart at the path level.

> **`var/workspace` is never swept by anything.** The retention job deletes only through the
> archive-rooted `Storage` (src/bayram/runtime/retention_job.py:135). A repo-wide search for
> `rmtree` / `.unlink(` / `os.remove` under `src/` finds two hits — src/bayram/storage.py:339
> (a failed atomic write's temp file) and src/bayram/audio/tempfiles.py:44 (a per-call scratch
> dir) — and neither touches a published workspace file. Per-order workspace directories are
> deterministic (`root / str(order_id)`, src/bayram/pipeline/assembly.py:54-56). Every song,
> greeting, cover and lyric sheet therefore exists twice on disk, and the second copy
> outlives every clock in `RetentionPolicy`. Provision the volume for unbounded growth, or
> put a host-level sweep on `var/workspace` — the repository has none.

---

## 3. Python 3.12 and the venv

> **AUDIT ANSWER: `aizu` uses neither `uv` nor an editable install, and that is a deliberate
> position rather than a deviation to correct** `[HOST 2026-09-11]`.
>
> ```
> /opt/hbd/venv/pyvenv.cfg:  home = /usr/bin
>                            include-system-site-packages = false
>                            version = 3.12.3
>                            executable = /usr/bin/python3.12
>                            command = /usr/bin/python3 -m venv /opt/hbd/venv     ← stdlib venv, not uv
> dist-info/INSTALLER:       pip
> dist-info/direct_url.json: {"archive_info": {"hash": "sha256=369db0983508619badec41ed50f72e53566de29a9fc9a0d518a5f2540c5587f3", …},
>                             "url": "file:///opt/hbd/release/hbd_bot-0.1.0-20260909-py3-none-any.whl"}
> ```
>
> `/opt/hbd/venv/bin/` holds `alembic`, `arq`, `fastapi`, `pip`, `uvicorn` and `wheel` — **no
> `uv`** — and `command -v uv` finds nothing on `PATH` either. The deployed recipe is therefore:
>
> ```bash
> /usr/bin/python3 -m venv /opt/hbd/venv
> /opt/hbd/venv/bin/pip install --force-reinstall --no-deps /opt/hbd/release/<wheel>
> /opt/hbd/venv/bin/pip check
> ```
>
> **The `uv` + `-e .` block below is the developer-machine path.** Keep it for that; do not
> "restore" it on a host. [`08-payme.md`](08-payme.md) §11.1 argues why a wheel is the right
> shape for a payment host — one file with one hash, built and tested elsewhere, and a rollback
> artefact that is already on disk — and [04-release.md](04-release.md) §0.1 records the state.

```bash
sudo -u bayram sh -c 'cd /srv/bayram && uv venv --python 3.12 .venv \
  && uv pip install --python .venv/bin/python -e .'
```

**3.12 and only 3.12.** `pyproject.toml:10` is `requires-python = ">=3.12,<3.13"` and
`uv.lock:3` is `requires-python = "==3.12.*"`; ruff targets `py312` (pyproject.toml:78) and
mypy is pinned to the same (pyproject.toml:122). A host that installs the distribution's
default `python3` and finds 3.13 fails at `uv venv --python 3.12`, which is the good place to
fail.

**A wheel is not a complete deployment unit — and `aizu` is the proof, not the counterexample.**
The reasoning below is right about *why*; the conclusion it draws (therefore install editable)
is one of two possible answers, and the host took the other one. A wheel host pays for the gap
by shipping `migrations/`, the unit files and the Caddy blocks as **separate copies** that
nothing in a wheel install updates. That is not a smaller problem than the one `-e .` solves —
it is a differently-shaped one, it is [`08-payme.md`](08-payme.md) §11.3's "most dangerous
property in the entire procedure", and on `aizu` it has already gone wrong: the separate copy at
`/opt/hbd/migrations/` drifted to the post-rename `env.py` and **cannot run a migration at all
today** `[HOST 2026-09-11]`. See [04-release.md](04-release.md) §0.4 warning 1.

The other half of the trade is worth stating because it is a genuine win and this section
predates it: on a wheel host the console bundle **cannot** be stale relative to the package,
because the `artifacts` force-include puts it *inside* the wheel and they are one artefact. §8's
whole stale-bundle failure mode is unreachable there. See §8's audit answer.

**On a checkout host, `-e .` is not an aesthetic choice.**
`migrations/` sits at the repository root and `[tool.hatch.build.targets.wheel] packages` is
`["src/bayram"]` (pyproject.toml:74), so no wheel contains the migration scripts, and every
documented alembic invocation assumes a checkout on disk (Makefile:196). The editable install
also means the console bundle is served straight from the checkout's
`src/bayram/admin/static/`, because `STATIC_DIR` is `Path(__file__).resolve().parent / "static"`
(src/bayram/admin/app.py:128). The `artifacts = ["src/bayram/admin/static/**"]` line
(pyproject.toml:84) exists to protect a *wheel-based* deploy and does nothing on this path.

> **`uv.lock` is documentation, not a pin.** It exists and is in sync with `pyproject.toml`,
> but `uv pip install` does not read it — `uv sync` appears nowhere in the tree. Two installs
> a week apart resolve independently inside the `>=` / `<` ranges. If reproducibility across
> hosts matters, that is a change to make deliberately; do not assume the lock file is doing
> it.

Verify:

```bash
/srv/bayram/.venv/bin/python -V                     # 3.12.x
/srv/bayram/.venv/bin/python -c 'import bayram, sys; print(bayram.__file__)'
```

`uv` itself is neither a project dependency nor in `uv.lock`, so it has to come from
somewhere else on the host. Note that `deploy/first-install-proposal.md` contradicts itself here: line 90
invokes bare `uv`, line 129 invokes `.venv/bin/uv`, which these instructions never create.
Use whichever `uv` you actually installed, consistently.

---

## 4. The two Postgres roles, created by hand

> ### AUDIT ANSWER: on `aizu` the two-role split DOES NOT EXIST, and this section describes a
> control that is not deployed.
>
> This is the most important row of the audit and it is provable without any database access, so
> nobody has to take it on trust. `/var/backups/hbd/*.sql.gz` are world-readable, and the
> `pre-cutover-20260910-140653.sql.gz` dump says `[HOST 2026-09-11]`:
>
> ```
> ALTER TABLE public.admin_audit_log OWNER TO hbd_app;   -- and 28 more: 29 CREATE TABLE public.
> REVOKE USAGE ON SCHEMA public FROM PUBLIC;             -- these two are the ONLY ACL statements
> GRANT ALL  ON SCHEMA public TO hbd_app;                -- NOTHING is granted to the owner role `hbd`
> ```
>
> plus `grep -c '^CREATE FUNCTION'` → **0**, and `grep -oE 'OWNER TO [a-z_]+' | sort | uniq -c`
> → 31 × `hbd_app`, 1 × `postgres`.
>
> Four conclusions, each one the negation of something argued below:
>
> 1. **The application role owns every table.** So there is nobody to revoke *from*, and
>    migration `0007`'s `REVOKE UPDATE, DELETE, TRUNCATE ON public.admin_audit_log FROM
>    "hbd_app"` is not a control — it is the exact non-control `migrations/env.py:89-93`
>    warns about.
> 2. **`0007` took its `_skip` branch.** There is no `REVOKE` on `admin_audit_log` in the dump
>    and there are **zero** `CREATE FUNCTION` statements, so neither `hbd_purge_audit_log` nor
>    `hbd_purge_audit_reasons` was ever installed. §7's `\df public.hbd_purge_audit_*` would
>    return no rows on this host, and for the real reason rather than the `\df`-syntax reason §7
>    spends a paragraph on.
> 3. **`/api/audit/verify` will report `chainProtection: "hmac-only"`.** The audit log's
>    append-only property on `aizu` is the HMAC chain alone, which promotes
>    `BAYRAM_ADMIN_AUDIT_HMAC_KEY` from "one of four things to back up" (§12) to *the* control.
> 4. **The owner role `hbd` has no rights on schema `public`, and that now breaks migrations
>    outright.** The `hbd` → `bayram` cutover died on exactly this, at
>    `2026-09-10 14:07:26.883 +05`: `hbd@hbd ERROR: no schema has been selected to create in at
>    character 15`, `STATEMENT: CREATE TABLE alembic_version (…)` `[HOST 2026-09-11]`. Alembic,
>    connecting as the owner through `BAYRAM_DB_MIGRATION_URL`, could neither see
>    `alembic_version` nor create one.
>
> **Why, because the cause changes the fix.** This is not a provisioning oversight that
> re-running `0007` repairs — `0007` will skip again. The database was dropped and rebuilt on the
> morning of 2026-09-10 ([`00-host-inventory.md`](00-host-inventory.md) row 47), and
> `/opt/hbd/release/wipe-and-rebuild.sh:112-115` is where the split was lost
> `[HOST 2026-09-11]`:
>
> ```sql
> DROP SCHEMA public CASCADE;  CREATE SCHEMA public;
> GRANT ALL ON SCHEMA public TO ${APP_ROLE};      -- hbd_app
> GRANT ALL ON SCHEMA public TO postgres;         -- and nothing to the owner role `hbd`
> ```
>
> Migrations were then run **as the application role** (`resume-wipe.sh:52-53`), so `hbd_app`
> created and therefore owns all 29 tables. **The repair order is: `GRANT` on the schema to
> `hbd`, then `REASSIGN`/`ALTER TABLE … OWNER TO hbd` for every table, then `upgrade head` under
> the owner DSN with `BAYRAM_ADMIN_AUDIT_DSN` and `BAYRAM_DB_APP_ROLE` exported as §7 shows.**
> In that order, and not as part of a release — it wants its own window.
>
> **`[UNPROVEN]`, and one password settles it:** that `hbd` currently holds neither `USAGE` nor
> `CREATE` on schema `public` is an inference from two directly observed ends (the `hbd@hbd`
> error and the `GRANT` block), not a reading. `sudo -n -u postgres psql -Atc "select
> has_schema_privilege(…)"` returns `sudo: a password is required`, because the `NOPASSWD`
> drop-in grants `pg_dump` and deliberately not `psql` (§10.1). Somebody wrote
> `/opt/hbd/diagnose.sh` for precisely this question and it needs one password to run —
> [04-release.md](04-release.md) §0.4 warning 2, and **read that warning before you type its
> path**, because the path is `/opt/hbd/deploy-payme.sh` and that file's own header lies about
> what it does.
>
> Everything below this box is the target shape. It has not been deployed here.

**Read `docker/initdb/10-two-roles.sql` before you run any of it anywhere.** That file is a
local development artefact. It carries a hardcoded password (`CREATE ROLE hbd_app WITH LOGIN
PASSWORD 'hbd_app'`, :35), it runs exactly once — on an empty Docker volume, by the
`postgres:16-alpine` entrypoint — and its own header says so in capitals: "THE PASSWORD BELOW
IS A LOCAL DEVELOPMENT PASSWORD… In staging or production, create these two roles by hand
with real secrets and put the two DSNs in your secret store."

Nothing in this repository creates production roles. This is the step.

> **Do not run that file against the production database — and the proposal tells you to.**
> `deploy/first-install-proposal.md:99` is `sudo -u postgres psql -d hbd -f /srv/bayram/docker/initdb/10-two-roles.sql`
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
> Nothing in `src/bayram/admin/settings.py` validates which role the DSN names.

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
refuses to construct when `is_production` (src/bayram/runtime/submitter.py:100-105), so
`build_submitter` takes the `create_pool(...)` branch (src/bayram/main.py:94) with nothing behind
it. The bot then opens Redis twice more, for the aiogram FSM storage and the per-chat event
isolation (src/bayram/main.py:103, :166-168 → src/bayram/bot/app.py:83, :97).

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
retention clock (src/bayram/bot/app.py:44-48, :83-85). It also holds the ARQ queue and job
results, the admin session mirrors (`bayram:admin:session`), the rate-limit and reveal-budget
counters (`bayram:admin:rl`, `bayram:admin:budget`) and the asset reveal window.

Losing Redis loses every queued and in-flight generation job and parks every customer
mid-wizard. It does **not** lose money state: open credit debits are closed by
`settle_stale_debits`, which runs inside the hourly purge transaction
(src/bayram/db/credit_settlement.py:203-222, called at src/bayram/db/purge.py:376-378). That is what
makes a Redis loss a support incident rather than a financial one.

> **A Redis outage and an operator lockout are the same event.** The admin limiters fail
> **closed** — "When Redis is unreachable the answer is 'denied', not 'allowed'"
> (src/bayram/admin/security/ratelimit.py:22-27) — while the bot's inbound gate fails **open**
> (src/bayram/bot/gate.py:44-47). That asymmetry is deliberate, but it means nobody can sign in
> to the panel during a Redis incident, including the operator who needs to revoke sessions.

> **`BAYRAM_REDIS_URL` defaults to `redis://localhost:6379/0`** (src/bayram/config.py:188), so a
> worker with a mistyped or missing Redis URL connects to a *local* Redis rather than failing.
> The queue then looks empty instead of broken.

Verify:

```bash
redis-cli ping                                   # PONG
redis-cli config get appendonly save
```

> ### AUDIT ANSWER: FAIL. Redis persistence is off on `aizu`.
>
> `[HOST 2026-09-11]`, and no privilege is needed to read it:
>
> ```
> redis-cli ping                    → PONG
> redis-cli config get appendonly   → appendonly  no
> redis-cli config get save         → save  3600 1 300 100 60 10000      ← the stock defaults
> ```
>
> Redis 7.0.15, `/etc/redis/redis.conf`, listening on `127.0.0.1:6379` and `[::1]:6379`. So the
> configuration this section calls non-optional was never applied: **RDB snapshots only, on the
> stock triggers**, which means an unclean stop can lose up to an hour.
>
> What that costs, in this product's own terms, is the paragraph above: the 14-day wizard drafts
> — recipient name, free-text note, the full approved lyric — the ARQ queue and job results, the
> admin session mirrors and the reveal window have no AOF behind them. A loss parks every
> customer mid-wizard and drops every queued job. It does **not** lose money state, for the
> reason given above, and that remains the difference between a support incident and a financial
> one.
>
> **And one consequence this section could not have known**, because it predates the rail: the
> Payme pause key lives in Redis, so a Redis rebuild silently **un**-pauses the rail
> ([`08-payme.md`](08-payme.md) §10, [`00-host-inventory.md`](00-host-inventory.md) row 16). On a
> host taking real money, "persistence is a nice-to-have" stopped being arguable on 2026-09-10.

---

## 6. The dotenv files, and their modes

Two files, one per process group. The split by process is older and more important than the
split by environment: there is no field on `AdminSettings` that could hold a vendor
credential, and pointing the panel at the bot's file would hand it all five keys by accident.

```
/etc/bayram/bot.env     0640 root:bayram   bot token + vendor keys + both DSNs
/etc/bayram/admin.env   0640 root:bayram   NO vendor credential, ever
```

```bash
sudo cp /srv/bayram/.env.example       /etc/bayram/bot.env
sudo cp /srv/bayram/.env.admin.example /etc/bayram/admin.env
sudo chown root:bayram /etc/bayram/*.env
sudo chmod 0640 /etc/bayram/*.env
sudoedit /etc/bayram/bot.env
sudoedit /etc/bayram/admin.env
```

Paths and modes are the deploy proposal's (deploy/first-install-proposal.md:63-64); the code accepts any path
through `BAYRAM_ENV_FILE` / `BAYRAM_ADMIN_ENV_FILE`, defaulting to `.env` and `.env.admin`
(src/bayram/config.py:84-97, src/bayram/admin/settings.py:75-81).

### `.env.admin.example` cannot be copied and booted. Fix nine lines.

This is not a prediction. Building `AdminSettings` against the file verbatim produces nine
simultaneous refusals:

```
$ BAYRAM_ADMIN_ENV_FILE=.env.admin.example .venv/bin/python -c \
    "from bayram.admin.settings import build_admin_settings; build_admin_settings()"
The admin panel's configuration is invalid or incomplete. Fix these environment variables:
  BAYRAM_ADMIN_COOKIE_SECURE: Input should be a valid boolean, unable to interpret input
  BAYRAM_ADMIN_TRUSTED_PROXY_CIDRS: contains an unparsable entry: '# comma-separated'
  BAYRAM_ADMIN_AUDIT_HMAC_KEY: Value should have at least 32 items after validation, not 0
  BAYRAM_ADMIN_NAME_MATCH_MIN_SIMILARITY: Input should be a valid number
  BAYRAM_ADMIN_SETTLEMENT_GRACE_S: Input should be a valid integer
  BAYRAM_ADMIN_UZS_PER_USD: Input should be a valid number
  BAYRAM_ADMIN_UZS_PER_USD_AS_OF: Input should be a valid date or datetime
  BAYRAM_ADMIN_SINGLE_SONG_PRICE_MINOR: Input should be a valid integer
  BAYRAM_ADMIN_KIT_CURRENCY: String should have at most 3 characters
```

Seven of those are one formatting bug. `python-dotenv` strips an inline `#` comment only when
the value before it is non-empty, so a line like

```
BAYRAM_ADMIN_UZS_PER_USD=                    # soʻm per USD, e.g. 12800. Blank = no rate published
```

(.env.admin.example:216) parses with the *comment* as its value. The seven affected lines are
:114, :155, :171, :216, :217, :235 and :236 — every one of them a variable whose own comment
tells the operator to leave it blank. `_blank_mirror_means_unpublished`
(src/bayram/admin/settings.py:433-465) exists solely to make this file work and says so at :449:
"The example file ships the variables blank, so this is the path an untouched deployment
actually takes." It is not the path — the values are never blank as parsed, so that validator
never fires.

The eighth, `BAYRAM_ADMIN_COOKIE_SECURE=` (.env.admin.example:92), is genuinely blank and is a
separate failure: the field is `bool | None` (src/bayram/admin/settings.py:197) and pydantic
cannot read an empty string as either.

**Fix:** move each of those comments onto its own line above the variable, and delete the
`BAYRAM_ADMIN_COOKIE_SECURE=` line entirely (its default is `None`, which is what the file's own
"Leave empty" instruction meant). The ninth,
`BAYRAM_ADMIN_AUDIT_HMAC_KEY`, is not a bug — it is required and has no default to forget to
change.

### What must actually be set

**Bot and worker — four required variables, in every environment:** `BAYRAM_DATABASE_URL`
(src/bayram/config.py:187) plus `BAYRAM_TELEGRAM_BOT_TOKEN`, `BAYRAM_ELEVENLABS_API_KEY` and
`BAYRAM_LLM_API_KEY`, made required by the `_VendorBoundSettings` subclass
(src/bayram/config.py:697-699) that `load_settings()` always selects. Everything else defaults.
Also set here: `BAYRAM_ENVIRONMENT=prod`, `BAYRAM_USE_FAKE_PROVIDERS=false`, `BAYRAM_REDIS_URL`, and
`BAYRAM_DB_MIGRATION_URL` — the owner DSN, which lives in the bot's file because
`migrations/env.py` reads it from there and neither long-running process has a field for it.

**Admin — two required, plus two non-defaults:** `BAYRAM_DATABASE_URL`
(src/bayram/admin/settings.py:174, the **`hbd_app`** DSN), `BAYRAM_ADMIN_AUDIT_HMAC_KEY` (:229, a
`SecretStr` with `min_length=32`), `BAYRAM_ADMIN_ENABLED=true` — the default is `false`
(:180) and the lifespan refuses to boot without it (src/bayram/admin/app.py:206-208, 315) — and
`BAYRAM_ADMIN_AUDIT_DSN`, the owner DSN (:235, `default=""`).

> **`BAYRAM_ADMIN_AUDIT_DSN` is never dialled, and §12's acceptance check still fails without
> it.** The admin process never connects with this value; it reads it as a boolean. `/audit/verify`
> passes `is_dsn_configured=bool(settings.admin_audit_dsn)` (src/bayram/admin/routers/audit.py:168)
> and `resolve_chain_protection` returns `HMAC_ONLY` immediately when that is false, before it
> asks Postgres anything (src/bayram/db/admin/audit.py:765-766). So the variable is the
> deployment's *declaration* that the two-role split exists. Leave it out of `admin.env` and
> a host whose §7 REVOKE landed perfectly still reports `chainProtection: "hmac-only"`, and
> the §12 row and the §13 question that both rest on that field will read as a failure.
> (The proposal does say to set it — deploy/first-install-proposal.md:109.) It is separately required in the
> *migration* shell for a different reason; see §7.

```bash
python -c "import secrets; print(secrets.token_urlsafe(48))"   # BAYRAM_ADMIN_AUDIT_HMAC_KEY
```

> **`BAYRAM_ADMIN_PUBLIC_ORIGIN` must be edited, not inherited.** The prod guard tests whether
> the variable was *set*, not whether it is plausible: `"admin_public_origin" not in
> self.model_fields_set` (src/bayram/admin/settings.py:578-581). A dotenv value counts as set —
> and the example file ships it uncommented at the loopback dev value
> (`http://127.0.0.1:8080`, .env.admin.example:73). Copy the file to a prod host and the
> guard is disarmed, producing exactly the incident its own comment predicts at :582-587:
> the panel boots, passes `/healthz`, serves a login page, and then rejects every mutation
> with `ORIGIN_REJECTED`. Set it to the `https://` origin a browser actually types.

> **`BAYRAM_ENVIRONMENT` is spelled `prod` and nothing checks your spelling.** On the bot and
> worker it is an unvalidated free-form `str` (src/bayram/config.py:170) and every production
> refusal is `self.environment == "prod"` (:685-686). `production` or `PROD` silently
> permits fake providers (src/bayram/runtime/providers.py:104-108) and the in-process submitter
> (src/bayram/runtime/submitter.py:100-105), with no error anywhere. `AdminSettings` closes the
> same field to a `Literal` (src/bayram/admin/settings.py:169) precisely because "a typo like
> `production` would silently downgrade the strongest boot control in the package" (:15-18) —
> that argument was never applied to `Settings`.

> **The two files never cross-check each other.** Five variables are owned by both classes —
> `BAYRAM_ENVIRONMENT`, `BAYRAM_LOG_LEVEL`, `BAYRAM_IS_DEBUG`, `BAYRAM_DATABASE_URL`, `BAYRAM_REDIS_URL` —
> and both classes use `extra="ignore"` (src/bayram/config.py:165,
> src/bayram/admin/settings.py:164), so each file silently swallows the other's variables and a
> typo'd `BAYRAM_` name is a no-op with no error. `prod` in the bot's file and `dev` left in the
> admin's is a completely legal, silent state in which the panel permits DEBUG logging,
> permits the loopback origin, and downgrades the vendor-credential refusal to a warning
> (src/bayram/admin/app.py:198-201).

> **A mistyped `BAYRAM_ENV_FILE` reads no file and the error never says so.** `resolve_env_file`
> falls back to the default when the variable is blank (src/bayram/config.py:85-92), and a path
> that does not exist yields an empty parse with no exception. The failure message hardcodes
> "see `.env.example`" (src/bayram/config.py:702-704) rather than naming the file that was
> actually read, and `env_file()` is logged only *after* settings build successfully. If the
> four required variables happen to be exported, the bot boots on 100% defaults — including
> `BAYRAM_ENVIRONMENT=dev`.

**Never on the admin host:** `BAYRAM_TELEGRAM_BOT_TOKEN`, `BAYRAM_ELEVENLABS_API_KEY`,
`BAYRAM_LLM_API_KEY`, `BAYRAM_LLM_FALLBACK_API_KEY`, `BAYRAM_OPENROUTER_MANAGEMENT_KEY`. That list is
derived, never restated —
`FORBIDDEN_ENV_VARS` is built from `bayram.config.VENDOR_SECRET_FIELDS`
(src/bayram/admin/app.py:116-118; src/bayram/config.py:111-116). In prod the lifespan refuses to
boot when any of them is in reach, in the environment or in the admin dotenv file
(src/bayram/admin/app.py:186-199). Outside prod it is a warning
(`admin.boot.vendor_env_present`, :200-203).

Verify:

```bash
sudo stat -c '%a %U:%G %n' /etc/bayram/*.env        # 640 root:bayram
sudo -u bayram cat /etc/bayram/bot.env >/dev/null      # the service user can read it
sudo -u bayram env BAYRAM_ADMIN_ENV_FILE=/etc/bayram/admin.env /srv/bayram/.venv/bin/python -c \
  'from bayram.admin.settings import build_admin_settings as b; s=b(); print(s.environment, s.admin_enabled)'
```

> **`env` is doing real work in that line, and the proposal drops it.** With default sudoers
> (`env_reset`, no `setenv` tag) a variable assignment written directly after `sudo` matches
> neither `env_keep` nor `env_check` and sudo aborts with "sorry, you are not allowed to set
> the following environment variables: BAYRAM_ADMIN_ENV_FILE" — a refusal that reads like a
> permission problem with the env file rather than with sudo. `deploy/first-install-proposal.md:112` and
> `:114` are both written in that broken shape. Interpose `env`, as §7 and §9 do.

---

## 7. The schema, as the owner role

```bash
sudo -u bayram env \
  BAYRAM_ENV_FILE=/etc/bayram/bot.env \
  BAYRAM_ADMIN_AUDIT_DSN=two-role \
  BAYRAM_DB_APP_ROLE=hbd_app \
  sh -c 'cd /srv/bayram && .venv/bin/python -m alembic -c migrations/alembic.ini upgrade head'
```

> **No password belongs on that command line, and none is needed there.** Anything in the
> argv of `env` is readable in `ps` by every user on the host and lands in the invoking
> shell's history — the same exposure §9's `--password` refusal exists to prevent. Neither
> secret is required: migration 0007 tests `BAYRAM_ADMIN_AUDIT_DSN` for non-emptiness only and
> never parses or dials it (`if not os.environ.get(_AUDIT_DSN_ENV, "").strip():`, 0007:336),
> so any non-empty marker takes the same branch; and with `BAYRAM_DB_APP_ROLE` set explicitly,
> `_app_role()` returns before it ever looks at `BAYRAM_DATABASE_URL` (0007:314-322). The
> connection itself comes from `BAYRAM_DB_MIGRATION_URL` inside `/etc/bayram/bot.env`, which
> `_owner_url()` reads from the dotenv file (migrations/env.py:95-113) — a 0640 root:bayram
> file, not a process argument. If your own tooling prefers a real DSN in
> `BAYRAM_ADMIN_AUDIT_DSN`, put it in a file the shell sources, never in argv.

**Those two exported variables are the point of this section, and the deploy proposal omits
both.** The chain is 0001 → **0025**, linear, no branches
(`migrations/versions/20260827_0900_0001_initial_schema.py:35-36` through
`20260910_1000_0025_index_settlement_clocks.py:52-53`) `[TREE 2026-09-11]`.

> **Head is `0025`; `aizu` is at `0024`.** Read from the dump's
> `COPY public.alembic_version (version_num) FROM stdin;` → `0024`, with all 25 revision files
> present at `/opt/hbd/migrations/versions/` `[HOST 2026-09-11]`. `0025` adds two indexes on the
> settlement clocks and nothing else, so the gap is tolerated by the running code. **This
> document said `0021` at four places** (and [04-release.md](04-release.md) at four more) until
> 2026-09-11; the number was four revisions stale. Prefer `current` and `heads` to a transcribed
> revision, and date any number you do transcribe.
>
> **`0025` cannot be applied on this host today.** `/opt/hbd/migrations/env.py:57` imports
> `bayram.config` against a venv that contains only `hbd`, so the documented invocation dies with
> `ModuleNotFoundError: No module named 'bayram'` before it opens a connection
> `[HOST 2026-09-11]`. [04-release.md](04-release.md) §0.4 warning 1 is the full account and the
> three candidate repairs.

`migrations/env.py` gets the connection right on its own: `_owner_url()` reads
`BAYRAM_DB_MIGRATION_URL` from the environment **and then falls back to the dotenv file**
(migrations/env.py:95-113), with :14-19 explaining that the environment-only version was a
bug that would have migrated production as the wrong role. Unset, it falls back to the
application DSN with a named WARNING (:117-129, :89-93).

Migration 0007 has the bug that `env.py` was fixed for. `_install_two_role_controls` gates on
`os.environ.get(_AUDIT_DSN_ENV, "")` with no dotenv fallback (0007:336), and `_app_role()`
reads `BAYRAM_DB_APP_ROLE` then a username out of `BAYRAM_DATABASE_URL`, both from `os.environ`
only (0007:314-322). Migration 0011 repeats the same pattern. But
`BAYRAM_ADMIN_AUDIT_DSN` is documented to live in `.env.admin` (.env.admin.example:130,
README.md:172-174) — a file the migration runner never loads — and `BAYRAM_DB_APP_ROLE` appears
in **neither** example file.

> **Follow `deploy/first-install-proposal.md:112` verbatim and the REVOKE never runs.** That command exports
> only `BAYRAM_ENV_FILE`. `_install_two_role_controls` then takes its first `_skip` branch,
> logging "REVOKE skipped: BAYRAM_ADMIN_AUDIT_DSN is not set" as a WARNING rather than a failure
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
sudo -u postgres psql -d hbd -c 'SELECT version_num FROM alembic_version'   # 0025 is head
```

> **AUDIT ANSWER for all three lines, obtained WITHOUT running them.** On `aizu` none of these
> can be run: `psql` is behind the sudo password wall the `NOPASSWD` drop-in deliberately does
> not open (§10.1). All three were answered from the world-readable pre-cutover dump instead
> `[HOST 2026-09-11]`:
>
> | Line | Answer on `aizu` |
> | --- | --- |
> | `\dp admin_audit_log` | **FAIL.** `ALTER TABLE public.admin_audit_log OWNER TO hbd_app` — the application role *owns* the table. No `REVOKE` on it anywhere in the dump. §4's audit box. |
> | `\df public.hbd_purge_audit_*` | **FAIL, zero rows.** The dump contains **no** `CREATE FUNCTION` at all, so neither sweep function exists. Not a `\df`-syntax problem — they were never created. |
> | `SELECT version_num` | **`0024`**, against a repository head of `0025`. |
>
> **So the answer to this section's central question — "did `0007`'s REVOKE actually land?" — is
> NO**, and the `chainProtection` field below will read `hmac-only`. That is the code behaving
> exactly as designed: *a control that is not deployed is reported as not deployed, never
> implied.* The design kept its promise. The deployment did not install the control.

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
(src/bayram/db/admin/audit.py:746-780). `hmac-only` is also what it reports when
`BAYRAM_ADMIN_AUDIT_DSN` is unset, when the backend is not Postgres, and when the probe errors.
A control that is not deployed is reported as not deployed, never implied.

---

## 8. The admin console build

```bash
sudo -u bayram sh -c 'cd /srv/bayram/admin-ui && npm ci && npm run build'
```

**Node has to come from somewhere.** `admin-ui/package.json` declares `"node": ">=20.19"` and
`admin-ui/package-lock.json` is `lockfileVersion: 3` (npm 7+). The deploy proposal builds with
npm on a host it never installs Node on (deploy/first-install-proposal.md:89 vs :113) — install a Node 20.19+
before this step and pin the version somewhere you will remember.

**The build writes into the Python package tree and wipes it first.**
`admin-ui/vite.config.ts:106-107` sets `outDir: "../src/bayram/admin/static"` with
`emptyOutDir: true`, and that directory is gitignored (stated at src/bayram/admin/app.py:124-128).

> **An unbuilt console does not look like a build problem.** With no `index.html`, the SPA
> catch-all raises a 404 (src/bayram/admin/app.py:238-239) and the static mount is declared with
> `check_dir=False` (:298) so the app still starts. `/healthz` answers 200, `/api` answers
> normally, and every browser URL 404s. Nothing at the process level distinguishes that from
> a healthy deployment.

> **A *stale* console looks like a working panel.** The shell is a one-substitution template:
> `render_shell` replaces `__BAYRAM_CSP_NONCE__` (src/bayram/admin/shell.py:55, 65-86;
> `admin-ui/index.html:28`) with this response's style nonce. A bundle built before that
> placeholder existed is served unchanged with one WARNING per response,
> `admin.spa.nonce_placeholder_missing` (shell.py:78-85) — deliberately, rather than a 500.
> The only visible symptom is that modal scroll-lock stops working, because
> `react-remove-scroll` injects a real `<style>` element that `style-src 'self' 'nonce-…'`
> then blocks. This is why the rebuild is mandatory on **every** deploy, not only the first.

Nothing gates this. The Python suite checks the *source* `admin-ui/index.html`, not the built
one (tests/test_admin/test_spa_nonce.py:49), and `make ui-e2e` rebuilds before it runs
(Makefile:161) — so the placeholder-drift check exists and the staleness check does not.
There is no CI in this repository at all; `make check` is `lint typecheck cov` (Makefile:193)
and reaches neither `ui-check` nor `ui-e2e`.

Verify:

```bash
grep -c __BAYRAM_CSP_NONCE__ /srv/bayram/src/bayram/admin/static/index.html    # 1
ls /srv/bayram/src/bayram/admin/static/assets | head
```

> ### AUDIT ANSWER: the bundle is PRESENT and CURRENT, at a different path, under a different
> placeholder, and it got there without anything on the host running `npm`.
>
> The verify path above does not exist on `aizu`. The deployed bundle is **inside the wheel**,
> served out of `site-packages` `[HOST 2026-09-11]`:
>
> ```bash
> grep -c __HBD_CSP_NONCE__ /opt/hbd/venv/lib/python3.12/site-packages/hbd/admin/static/index.html
> #   1        (and __BAYRAM_CSP_NONCE__ → 0, because the host is pre-rename)
> ls  /opt/hbd/venv/lib/python3.12/site-packages/hbd/admin/static/assets | wc -l
> #   22       index-CizC0Esy.css, index-D9iMG-RF.js, index-D9iMG-RF.js.map, logo-DCc7YfOk.png,
> #            six Manrope woff2, twelve Outfit woff/woff2
> ```
>
> **There is no `npm run build` step on this host at all, and there cannot be: no `node`, no
> `npm`, no `admin-dashboard/`** `[HOST 2026-09-11]`. That is a consequence of the wheel model
> rather than a gap — and installing Node to make this section followable would be undoing the
> deploy model, not fixing it ([`00-host-inventory.md`](00-host-inventory.md) row 28).
>
> **The upside, stated plainly because it is the one place the wheel model is strictly better:**
> the two failure modes this section spends most of its length on cannot occur. A bundle that
> ships inside the package cannot be absent while the package is installed, and cannot be stale
> relative to it. The replacement check runs at **build** time, on the archive, before the wheel
> is copied: `deploy/cutover-to-bayram.sh:44-50` asserts the package directory, the billing
> router and at least one file under `admin/static/` in the wheel's namelist
> `[TREE 2026-09-11]`. Port that into whatever builds your wheels.

> **The source maps ARE in production. This is not a hypothetical on `aizu`.**
> `index-D9iMG-RF.js.map` is present in the deployed `assets/`, beside its `.js`
> `[HOST 2026-09-11]`. So the console's complete TypeScript source is being served from
> `/assets` by a middleware stack that authenticates nothing, stamped `public, max-age=31536000,
> immutable` — to anyone who can reach `https://admin.bayrambot.uz`, which is a public hostname.
> Read the next callout as a finding rather than as advice, and note its closing point: a
> year-immutable cache means removing them later does not un-cache them. This belongs in
> [`07-security.md`](07-security.md) as well.

> **Consider stripping the source maps.** `admin-ui/vite.config.ts:125` sets
> `sourcemap: true`, so the console's complete TypeScript source ships in the bundle and is
> served from `/assets` (src/bayram/admin/app.py:296-300) by a middleware stack that
> authenticates nothing (:387-390), stamped `public, max-age=31536000, immutable`
> (src/bayram/admin/middleware/security_headers.py:82, 85). Anyone who can reach the panel's
> origin can download them unauthenticated, and a year-immutable cache means removing them
> later does not un-cache them.

---

## 9. The first OWNER

There is no signup route. The only way an account comes into existence is this command:

```bash
sudo -u bayram env BAYRAM_ADMIN_ENV_FILE=/etc/bayram/admin.env \
  sh -c 'cd /srv/bayram && .venv/bin/python -m bayram.admin.bootstrap --username owner'
```

It prompts twice on the TTY via `getpass` and echoes nothing.

**`--password` on argv is refused, deliberately.** The flag is registered with
`help=argparse.SUPPRESS` purely so it can be rejected with an explanation
(src/bayram/admin/bootstrap.py:100-121, refusal text at :80-84, raised at :302-306): a password
in argv is visible in `ps` to every user on the host and lands in shell history. For an
unattended install, use `--password-file`, which is refused unless the file has no group or
other permission bit at all — `mode & 0o077` must be zero, i.e. 0600 or stricter — because a
group-*writable* file can be replaced before it is read (:76-78, :124-134). The refusal names
the actual mode.

**Password rules are length only:** 8 to 256 characters, no composition rule, no blocklist
(src/bayram/admin/bootstrap.py:146-152; `MIN_PASSWORD_CHARS = 8` at
src/bayram/admin/schemas/common.py:31-38, lowered from 12 by a product decision on 2026-09-04).
That comment says what carries the weight instead: "At 8 the argon2 parameters are doing most
of the work against a leaked hash, so keep `BAYRAM_ADMIN_ARGON2_MEMORY_KIB` high and leave the
login throttle in place." Those two are load-bearing controls, not tunables.

Both bootstrap paths set `must_change_password=True`
(src/bayram/db/admin/accounts.py:171-182), so the first session is gated to
`/api/auth/password` and `/api/auth/me` and nothing else
(`PASSWORD_GATE_EXEMPT_PATHS`, src/bayram/admin/deps.py:116). `/auth/logout` is deliberately not
exempt — a first-boot
operator drops the cookie instead.

The audit row is written in the same transaction as the account, with `actor_id=NULL` and
`actor_username="system:bootstrap"` (src/bayram/admin/bootstrap.py:239-271). That string is the
exact grep for every out-of-band ownership event, and a login by an account literally named
"bootstrap" cannot collide with it.

**Exit codes are a three-way contract** an install script can branch on without parsing
English: 0 success, 1 operator refusal (bad input, race, already bootstrapped), 2
configuration error (src/bayram/admin/bootstrap.py:72-74, :319-343). Nothing ever prints a
traceback, because a traceback here would carry the DSN.

> **Recovery is only for the fully-locked-out case.** `--reset-owner` is refused while *any*
> active OWNER exists (src/bayram/admin/bootstrap.py:178-191). If an OWNER row exists but nobody
> can sign in — locked out by the login throttle, say — the row must be deactivated in the
> database first. No document in this repository describes that step.

---

## 10. Process supervision

> ### AUDIT ANSWER: yes, systemd — under different names, different paths, and with two of this
> section's three arguments inverted on the machine.
>
> `[HOST 2026-09-11]`. `/etc/systemd/system/` holds exactly four of our units —
> `hbd-admin.service`, `hbd-bot.service`, `hbd-payme.service`, `hbd-worker.service` — and no
> `bayram-*` unit. All four are `active`, `User=hbd Group=hbd`,
> `WorkingDirectory=/var/lib/hbd`:
>
> ```
> hbd-bot      /opt/hbd/venv/bin/python -m hbd.main
> hbd-worker   /opt/hbd/venv/bin/python -m arq hbd.worker.WorkerSettings
> hbd-admin    /opt/hbd/venv/bin/python -m uvicorn hbd.admin.app:app  --host 127.0.0.1 --port 8080
> hbd-payme    /opt/hbd/venv/bin/python -m uvicorn hbd.payme.app:app  --host 127.0.0.1 --port 8091
> ```
>
> **One worker replica**, one PID per unit, no template unit and no `@` instances — so the
> per-process vendor semaphore argument below holds here
> ([`00-host-inventory.md`](00-host-inventory.md) row 9). Listeners are `127.0.0.1` on 5432,
> 6379, 8080 and 8091, plus `[::1]:6379`.
>
> **The three arguments this section makes, audited one by one:**
>
> | The argument | On `aizu` |
> | --- | --- |
> | `Environment=*_ENV_FILE=`, not `EnvironmentFile=` | **INVERTED for three of four.** See the `EnvironmentFile` box below. |
> | `InaccessiblePaths=` on the **admin** unit | **NOT DEPLOYED on the admin unit.** It is on the **gateway** instead. See that box below. |
> | one shared `WorkingDirectory` so the data roots agree | **HOLDS.** `/var/lib/hbd` on all four. |
>
> And one thing no unit should carry: `hbd-payme.service` has
> `Documentation=file:///srv/hbd/deploy/README.md` `[HOST 2026-09-11]` — a path that has never
> existed on this host, since `/srv` is empty. `deploy/systemd/bayram-payme.service:55` has the
> same line with `bayram` substituted, so the repository will reproduce the defect on the next
> host `[TREE 2026-09-11]`. A `Documentation=` URL that 404s is a small thing that teaches an
> operator to stop reading `Documentation=` lines.

`deploy/systemd/bayram-bot.service`, `bayram-worker.service`, `bayram-admin.service` and
`bayram-payme.service` — four, not three — are the **proposed** units, authored in this
repository without host access. They are not what `aizu` uses. `deploy/cutover-to-bayram.sh:16-18`
says so in as many words: *"the repository's `deploy/systemd/bayram-*.service` files — which say
`User=bayram`, `/srv/bayram` and `/var/lib/bayram` — are **WRONG for this host** and are not
used."* They also do not agree with one another; [04-release.md](04-release.md) §0.3 is the
per-file standing.

```bash
sudo cp /srv/bayram/deploy/systemd/*.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now bayram-bot bayram-worker bayram-admin
```

What is worth keeping from them, and why:

**`Environment=BAYRAM_ENV_FILE=/etc/bayram/bot.env`, not `EnvironmentFile=`**
(bayram-bot.service:27, bayram-worker.service:20, bayram-admin.service:29). `EnvironmentFile=` loads
every value into the process environment, where it is visible in `systemctl show` and in
`/proc/<pid>/environ`; naming the file instead means pydantic-settings reads the 0640 file
directly and the credentials never enter the environment. The absolute path is also what makes
a stray `.env` in `/srv/bayram` unreadable by accident. The corollary is real: process
environment beats the dotenv file for every variable on both settings classes, so any `BAYRAM_*`
left exported in a deploy shell silently overrides the file the unit points at.

> ### AUDIT ANSWER: three of the four deployed units do exactly the opposite, so on `aizu` the
> credentials ARE in the process environment.
>
> `systemctl show` `[HOST 2026-09-11]`:
>
> ```
> hbd-bot      EnvironmentFiles=/etc/hbd/hbd.env (ignore_errors=no)        Environment=   (empty)
> hbd-worker   EnvironmentFiles=/etc/hbd/hbd.env (ignore_errors=no)        Environment=   (empty)
> hbd-admin    EnvironmentFiles=/etc/hbd/hbd-admin.env (ignore_errors=no)  Environment=   (empty)
> hbd-payme    EnvironmentFiles=  (empty)     Environment=HBD_PAYME_ENV_FILE=/etc/hbd/payme.env
> ```
>
> **So the bot token and all three vendor keys are in the environment of `hbd-bot` and
> `hbd-worker`, visible to `systemctl show` and to anything that can read `/proc/<pid>/environ`
> — the exact exposure the argument above exists to prevent.** Corroborated from the application
> side, which is the cheaper check and needs no privilege: `hbd-bot` logs
> `"env_file": ".env"` and `hbd-admin` logs `"env_file": ".env.admin"` — pydantic's bare
> **defaults**, i.e. neither process was ever handed a dotenv path at all `[HOST 2026-09-11]`.
> Their entire configuration arrives through systemd.
>
> **`hbd-payme` already does it right and is the model**, deliberately: the cashbox key never
> enters an environment, and that is [`08-payme.md`](08-payme.md) §2's argument. So the fix is
> not a new design — it is three unit files edited to look like the fourth, plus the one
> consequence to plan for: the processes would then read the files *themselves*, so
> `/etc/hbd/*.env` must stay readable by `hbd` (it is: `root:hbd 0640`) and every variable now
> arriving from the environment must actually be in the file. That is a change to make with a
> restart window and a `host verified` line to read afterwards, not in passing.
>
> **One bonus the divergence costs**: the corollary above — "process environment beats the dotenv
> file" — becomes unobservable. With `EnvironmentFile=`, there is no dotenv file in the picture at
> all, so the `env_file` field on the boot line, the one place designed to tell you which
> configuration was read, reports a default and tells you nothing. You have to read
> `systemctl show -p EnvironmentFiles` instead.

**`InaccessiblePaths=/etc/bayram/bot.env` on the admin unit** (bayram-admin.service:50, argued
for in that file's own header comment at :10). The application-level vendor-credential refusal is
a check the panel performs on itself; this one is the kernel's, and it survives an edit that
points `BAYRAM_ADMIN_ENV_FILE` at the wrong file.

> ### AUDIT ANSWER: not deployed on the admin unit. The kernel-level control exists for the
> gateway and not for the panel.
>
> `[HOST 2026-09-11]`, from `systemctl show -p InaccessiblePaths -p ReadWritePaths`:
>
> ```
> hbd-bot      ReadWritePaths=/var/lib/hbd /var/log/hbd     InaccessiblePaths=   (empty)
> hbd-worker   ReadWritePaths=/var/lib/hbd /var/log/hbd     InaccessiblePaths=   (empty)
> hbd-admin    ReadWritePaths=  (empty)                     InaccessiblePaths=   (empty)
> hbd-payme    ReadWritePaths=  (empty)                     InaccessiblePaths=/etc/hbd/hbd.env /etc/hbd/hbd-admin.env
> ```
>
> `hbd-admin.service`'s hardening block ends at `LockPersonality=true`, followed by the comment
> *"# No ReadWritePaths: the panel streams assets from a root it holds READ-ONLY"* — which is a
> deliberate and correct decision about a *different* directive, and is not the missing line.
> **So on `aizu` the panel's vendor-key separation is application-level only**: it rests entirely
> on `_refuse_vendor_credentials` at boot, which is a real control (a running prod panel proves
> the four names are out of its reach — `admin.boot.vendor_env_present` has never appeared in the
> journal `[HOST 2026-09-11]`) but is the half this callout exists to say is not enough. An edit
> that points the admin unit's `EnvironmentFile=` at `/etc/hbd/hbd.env` would be caught by the
> application refusal and **not** by the kernel.
>
> The repository is correct here and should not be "fixed":
> `deploy/systemd/bayram-admin.service:50` does carry `InaccessiblePaths=/etc/bayram/bot.env`,
> and `bayram-payme.service:93` carries a separate, wider one
> (`/etc/bayram/bayram.env /etc/bayram/bayram-admin.env`) `[TREE 2026-09-11]`. Both units have
> one; only the *deployed* admin unit does not. Note that `deploy/cutover-to-bayram.sh` would
> reproduce the gap: the four units it writes give `InaccessiblePaths` to the gateway (`:152`)
> and to nothing else `[TREE 2026-09-11]`.

**`WorkingDirectory=/srv/bayram` on all three, and `ReadWritePaths=/srv/bayram/var`** on the bot and
worker (bayram-bot.service:26, :53). Under `ProtectSystem=strict` everything else is read-only.
This is what makes `Path.cwd() / "var"` resolve to the same tree for all three processes —
the agreement §2 says nothing in the code enforces. Note that `ReadWritePaths=` on a path
that does not exist fails the unit, and `build_container` creates `var/workspace` and
`var/archive` at every boot but only if `var` itself is writable.

> **AUDIT ANSWER: the *shape* of this is deployed and the paths are different.** All four units
> carry `WorkingDirectory=/var/lib/hbd`, and the bot and worker carry
> `ReadWritePaths=/var/lib/hbd /var/log/hbd` `[HOST 2026-09-11]`. So the agreement holds on
> `aizu` — the data root is `/var/lib/hbd/var` for every process that touches it — and it holds
> for the reason this callout gives, by one line repeated four times with nothing checking that
> they still match. `/var/log/hbd` is a second writable path the repository's units do not have.
>
> Whether `var/workspace` has ever grown unboundedly is **`[UNPROVEN]`**: `ls -la /var/lib/hbd`
> returns `Permission denied` (`0750 hbd:hbd`, and `developer` is not in the `hbd` group)
> `[HOST 2026-09-11]`. The upper bound from outside is the whole root filesystem — 38 GB at 21%
> used — so the archive is smaller than that and nothing narrower can be said without an operator
> password ([`00-host-inventory.md`](00-host-inventory.md) row 30).

**One correction to make if you adopt these files.** `bayram-worker.service:1-2` describes the
worker as performing "every operational action the admin panel queues". No such path exists
in this tree: a search across `src/bayram/admin` for `enqueue_job`, `create_pool` or `arq` finds
nothing, and the admin container holds only an engine, a session factory, Redis and rate
limits (src/bayram/admin/container.py:81-83, :142-151). Anyone reading that comment will look for
a queue that is not there.

> **Two things the units do not say.** First, the worker validates its entire configuration
> at module import (`_SETTINGS = _settings()`, src/bayram/worker.py:40), so a bad env produces an
> uncaught `ConfigError` traceback from the arq CLI on every restart attempt — the bot catches
> the same error and prints one line (src/bayram/main.py:213-218). A restart loop on the worker
> is noisy in a way the bot's is not. Second, four module-level `assert`s guard the
> enqueue-name ↔ function-name contract (src/bayram/runtime/jobs.py:786-788 and the three cron
> modules) and are erased under `python -O` or `PYTHONOPTIMIZE`. The proposed units do not use
> `-O`; nothing enforces that they never will.

> **Run exactly one worker replica unless you also change the vendor ceiling.** The music and
> TTS concurrency guards are per-process `asyncio.Semaphore`s
> (src/bayram/runtime/container.py:332-333) with `music_max_concurrency` defaulting to 2 —
> described at src/bayram/config.py:195-200 as "Vendor's simultaneous-render ceiling: 2 on
> Starter/Creator/Pro, 5 on Scale". Two replicas make four simultaneous renders against a
> vendor limit of 2. The guard is written as if one process exists.

> **Only the worker runs the crons**, and none of them runs at startup: the retention sweep
> hourly at :17, the vendor-balance poll hourly at :43, the activity snapshot daily at 00:07
> UTC, all `run_at_startup=False, unique=True, max_tries=1`
> (src/bayram/runtime/jobs.py:705-769). If the worker is down, retention stops — a stated legal
> obligation — the audit chain's HEAD anchor stops being re-pinned so tail deletions become
> undetectable while `/audit/verify` still reports `ok`, and the activity series accrues a
> permanent gap that nothing backfills. There is no way to trigger a retention sweep on
> demand: `POST /api/retention/run` is referenced in two docstrings and exists as no route.

**Connection budget.** The bot and the worker take `create_engine`'s defaults, 10 + 20
overflow each (src/bayram/db/engine.py:40-41). The admin API does not: `build_admin_container`
passes `pool_size=ADMIN_POOL_SIZE` / `max_overflow=ADMIN_MAX_OVERFLOW`, 5 + 5
(src/bayram/admin/container.py:53-54, used at :121-125). So three processes at the defaults is
30 + 30 + 10 = **70** connections against a stock `max_connections` of 100, leaving 30. The
docstring at engine.py:64-67 gives "3 × 30 = 90" as the counterfactual it *rejects* — "so the
API asks for a smaller share rather than everyone quietly sharing a cliff edge" — not as the
deployed number. Budget the remaining 30 for everything else on that server: a second worker
replica is another 30 and eats all of it, and a monitor or an open `psql` needs to fit too.

Verify:

```bash
systemctl status bayram-bot bayram-worker bayram-admin
journalctl -u bayram-bot   -n 50 | grep 'host verified'
journalctl -u bayram-admin -n 50 | grep 'admin.boot.ok'
```

> **`deploy/first-install-proposal.md:143` greps for the wrong string.** It runs
> `journalctl -u bayram-bot -n 20 | grep host_verified`. The log line's message is
> `"host verified"` with a space (src/bayram/runtime/startup.py:33-41) and it is not an `event`
> field — there is no `host_verified` token anywhere in the tree. An operator following that
> checklist sees an empty grep and may conclude the bot did not boot. Line 144's
> `admin.boot.ok` does work, because that one genuinely is an event field
> (src/bayram/admin/app.py:325).

### 10.1 How the deploy account gets its privileges — the `sudoers` drop-in

**New section, 2026-09-11.** This document covered packages, roles, dotenv modes, schema,
console, first OWNER, supervision and TLS, and said nothing about how the account that performs
a release is granted the privileges it needs. On `aizu` that grant is the whole privilege
boundary for every unattended operation, and it is already wrong for the next release.

**What exists** `[HOST 2026-09-11]`, read from `sudo -n -l` as `developer`. Ten `NOPASSWD`
lines, one of which belongs to an unrelated product on this box:

```
(ALL : ALL) ALL                                         ← requires a PASSWORD. `sudo -n true` → "sudo: a password is required"
(root) NOPASSWD: systemctl restart|status|start|stop|is-active aizu     ← NOT OURS. A different product.
(root) NOPASSWD: /usr/bin/bash /opt/hbd/deploy-payme.sh
(root) NOPASSWD: systemctl daemon-reload
(root) NOPASSWD: systemctl enable|disable|start|stop|restart|status|is-active hbd-payme.service
(root) NOPASSWD: systemctl restart hbd-bot.service, hbd-worker.service, hbd-admin.service
(root) NOPASSWD: systemctl reload|restart caddy.service
(root) NOPASSWD: journalctl -u hbd-payme *
(root) NOPASSWD: tee /etc/hbd/payme.env, tee /etc/caddy/Caddyfile
(root) NOPASSWD: caddy validate --config /etc/caddy/Caddyfile --adapter caddyfile
(postgres) NOPASSWD: /usr/bin/pg_dump hbd
```

Three things about that list are deliberate and worth not "improving":

- **It does not include `psql`.** That is why §4's and §7's grant checks cannot be run
  unattended and had to be answered from a `pg_dump` artefact instead. The drop-in authorises a
  **deploy**, not arbitrary database access, and the asymmetry is the point: `pg_dump` can only
  read, and an automated deploy has a real reason to need a backup.
- **It does not include any read of `/etc/hbd`.** Hence every `[UNPROVEN]` row in §13 that is
  about a variable's value.
- **The second line belongs to somebody else.** There are two drop-in files,
  `/etc/sudoers.d/hbd-deploy` and `/etc/sudoers.d/aizu-deploy`; deleting the wrong one breaks an
  unrelated product. Revoking ours is `sudo rm /etc/sudoers.d/hbd-deploy`.
  **`[UNPROVEN]`: which file carries which rule.** `/etc/sudoers.d/*` are `-r--r----- root root`,
  so the two filenames are confirmed and the mapping of rules to files is inferred from `sudo -l`
  plus `deploy/cutover-to-bayram.sh:174`, which names `hbd-deploy` explicitly.

> **THE DROP-IN IS ALREADY WRONG FOR THE RENAME, AND THE CUTOVER SCRIPT SAYS SO IN ITS OWN LAST
> LINE.** Every verb it grants names an `hbd-*` unit or an `/etc/hbd` path. Nothing covers
> `bayram-*`. `deploy/cutover-to-bayram.sh:174` is literally
> `echo "NOTE: /etc/sudoers.d/hbd-deploy still names the hbd-* units and will not cover
> bayram-*."` — and the script does nothing about it `[TREE 2026-09-11]`. **So if the cutover
> ever succeeds, it locks the deploy account out of the four units it just created**: no
> restart, no `journalctl -u`, no `tee` of the gateway's env file, until somebody with the sudo
> password writes a new drop-in. The new drop-in is part of the cutover, not a follow-up ticket.

> **And one hazard that is live today rather than after the rename.** The drop-in names
> `bash /opt/hbd/deploy-payme.sh` — so that *filename* is a privileged entry point, and the
> contents of the file behind it have been rewritten twice in one afternoon. As of
> `[HOST 2026-09-11]` it is a 434-byte wrapper whose header says it runs the rename cutover and
> whose `exec` line runs a read-only Postgres diagnostic instead. **Granting `NOPASSWD` on a
> path rather than on a verb means the privilege follows whatever is written at that path.**
> Read the file before every use: [04-release.md](04-release.md) §0.4 warning 2.

**What a correct first install should do here**, stated as the target since nothing in this
repository creates it: write one drop-in per product, name it after the product, grant verbs on
*named units* and `tee` on *named files* rather than anything wildcarded, keep `psql` out of it,
and put the revoke command in the same document as the grant. A drop-in is configuration with a
blast radius; it deserves the same treatment as the dotenv files in §6 and gets none in this
repository.

---

## 11. TLS in front of the loopback admin API

The admin API binds loopback **only because the command line says so**. `BAYRAM_ADMIN_HOST` and
`BAYRAM_ADMIN_PORT` exist as settings (src/bayram/admin/settings.py:188-189) and are read by nothing
that binds a socket — their only consumers are the two projections onto `GET /api/config`
(src/bayram/admin/schemas/config_view.py:108-109, :202-203). The bind comes from
`--host 127.0.0.1 --port 8080` (Makefile:89, bayram-admin.service:30).

> **Changing `BAYRAM_ADMIN_PORT` changes what the panel *displays*, not what it *binds*.** The
> settings comment at :186-189 ("Binding 0.0.0.0 publishes a password login to the internet")
> reads as though the field enforced the bind. It does not, and `/api/config` will keep
> rendering `adminHost: 127.0.0.1` to the operator checking, whatever the process is actually
> listening on. The bind flag belongs to whatever starts the process, and the panel's own
> config screen is not evidence about it.

The terminator in front of it must do five things:

1. **Terminate TLS**, and add `Strict-Transport-Security` itself. Nothing in this repository
   ever emits HSTS: `SECURITY_HEADERS` is exactly `x-content-type-options: nosniff`,
   `referrer-policy: no-referrer` and `cache-control: no-store`
   (src/bayram/admin/middleware/security_headers.py:73-77) plus a per-response CSP, and the CSP
   template contains no `upgrade-insecure-requests`. A first request to `http://` is upgraded
   by nothing the application controls.
2. **Serve the panel at the root of its own hostname.** Assets, the immutable-cache carve-out
   and the API prefix are all absolute — `IMMUTABLE_PATH_PREFIX = "/assets/"`
   (security_headers.py:82), `API_PREFIX = "/api"` (src/bayram/admin/deps.py:108) — and both
   cookies are `__Host-` prefixed (src/bayram/admin/csrf.py:48-49), which *requires*
   `Path=/` and so cannot be narrowed. Under a subpath mount the bundle 404s, the
   cache split lands on the wrong paths, and the cookies become visible to everything else on
   that origin.
3. **Pass `Origin` through unmodified.** The CSRF check is exact: `origin not in
   accepted_origins`, with an absent header a refusal (`ORIGIN_MISSING`, csrf.py:76-88), and
   outside dev `accepted_origins` is the single frozenset `{admin_public_origin}`
   (src/bayram/admin/settings.py:620-632). A proxy that rewrites or strips it produces a panel
   that logs in fine and then 403s every write, and the boot guard cannot catch it because it
   tests only whether the variable was set.
4. **Be the only reachable name.** Every additional hostname, port or scheme — a bare IP, a
   `www.` variant — 403s every state-changing request, and only at the first mutation.
5. **Append, not replace, `X-Forwarded-For`** — and then tell the panel about itself.

`deploy/first-install-proposal.md:56` names "Caddy or nginx" as a suggestion. The repository expresses no
preference and contains no proxy configuration.

### The proxy setting that is silently off by default

```
BAYRAM_ADMIN_TRUSTED_PROXY_HOPS=1                # the exact count of proxies YOU control
BAYRAM_ADMIN_TRUSTED_PROXY_CIDRS=127.0.0.1/32    # the addresses those proxies connect from
```

`resolve_client_ip` ignores `X-Forwarded-For` entirely unless **both** `hops > 0` **and** the
peer is inside a configured CIDR (src/bayram/admin/security/clientip.py:142). The shipped
defaults are `0` and empty (src/bayram/admin/settings.py:216-217), and the example file ships
them that way too.

With the defaults, every request behind a reverse proxy resolves to the proxy's own address.
The strict login counter is keyed `(username, ip)` at 10 attempts per 900 seconds
(`LOGIN_MAX_PER_USER_IP`, src/bayram/admin/security/ratelimit.py:117; `check_login_rate_limit`
at :414-448 via `_user_ip_key`, :309), so a collapsed IP turns it into a
single global bucket per username — the exact shape the module's own header calls out at
:9-13: it "hands anyone who knows an operator's username a permanent 429 against that account,
at exactly the moment during an incident when the operator needs to log in". The same collapse
writes the proxy's address into `admin_audit_log.ip` for every row and into
`admin_sessions.last_ip`, so the audit log's only network evidence becomes a constant.

Nothing validates hops against reality — too high believes an attacker-written entry, too low
believes an inner proxy — and nothing surfaces the value at boot: `admin.boot.ok` logs
`environment`, `env_file`, `is_cookie_secure` and `public_origin`, and neither proxy setting
(src/bayram/admin/app.py:322-333). The parser itself is properly hostile to its input — a 32-entry
cap, the believed entry counted from the right, an unparsable entry falling back to the peer
rather than a neighbour (clientip.py:45, 105-107, 144-149) — so where the configuration is
right, the control is sound. A CIDR typo fails the boot and names the variable
(src/bayram/admin/settings.py:486-499).

### Set a probe token, or nothing can observe this deployment

```
BAYRAM_ADMIN_PROBE_TOKEN=<a long random string>
```

There are exactly two health endpoints in the tree, both on the admin API, and neither the bot
nor the worker exposes any HTTP probe at all — supervision of those two can only be
process-level.

`GET /healthz` is liveness: a bare 200 with an empty body that touches nothing
(src/bayram/admin/routers/health.py:121-124). It learns nothing about Postgres or Redis, and it
answers even when the lifespan-built container is absent — so a naive liveness probe reports a
process that can serve nothing as healthy.

`GET /readyz` is where the detail is, and **unauthenticated it returns the constant
`{"status":"ok"}` even when the database and Redis are both down**
(health.py:53-56, :126-131). Detail requires either a live operator session or an
`X-Probe-Token` header matching `BAYRAM_ADMIN_PROBE_TOKEN` under `secrets.compare_digest`
(:93-105, tried first so it still works when the database is the thing that is down). The
default is empty and authorises nobody (src/bayram/admin/settings.py:428).

> **A monitor pointed at `/readyz` without the token will never remove a broken instance.**
> There is no default token to forget to change, which is the right shape — but there is also
> no monitoring path at all until one is set. Note the field has no `min_length`, unlike
> `admin_audit_hmac_key`'s 32: a one-character token passes every check. Length here is
> operator discipline, not a validated bound.

`configVersion` in that body is always `null` on this tree — nothing writes the Redis key
`bayram:settings:version` (health.py:50-51, :74; the config editor that would write it is a later
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

| claim | how you know | `aizu`, audited |
| --- | --- | --- |
| ffmpeg can do the job | `ffmpeg -hide_banner -encoders \| grep -E 'libopus\|libmp3lame'` — both present | **PASS.** Both encoders, ffmpeg 6.1.1 `[HOST 2026-09-11]` |
| the bot booted against the right config | `journalctl -u bayram-bot \| grep 'host verified'` → `environment=prod`, and `env_file` naming the file you meant | **HALF.** `environment` is `prod`; `env_file` is `".env"` — the bare default, because the unit uses `EnvironmentFile=`. §10. Read `systemctl show -p EnvironmentFiles` instead `[HOST 2026-09-11]` |
| the panel booted against the right config | `journalctl -u bayram-admin \| grep admin.boot.ok` → same pair, `is_cookie_secure=true`, the real `public_origin` | **PASS, same caveat.** `environment=prod`, `is_cookie_secure=true`, `public_origin=https://admin.bayrambot.uz`; `env_file` is `".env.admin"` `[HOST 2026-09-11]` |
| no vendor key is on the admin host | `journalctl -u bayram-admin \| grep admin.boot.vendor_env_present` is empty — in prod it is a refusal, so a *running* prod panel already proves it | **PASS.** Zero occurrences since 2026-09-01, and the panel is running in `prod` `[HOST 2026-09-11]` |
| the console bundle is current | `grep -c __BAYRAM_CSP_NONCE__ .../static/index.html` = 1, and no `admin.spa.nonce_placeholder_missing` in the journal | **PASS at a different path and placeholder.** `grep -c __HBD_CSP_NONCE__ /opt/hbd/venv/lib/python3.12/site-packages/hbd/admin/static/index.html` = 1. §8 `[HOST 2026-09-11]` |
| the schema is at head | `SELECT version_num FROM alembic_version` → compare against the newest file in `migrations/versions/` | **BEHIND BY ONE.** Database `0024`, repository head `0025`. §7. And `0025` cannot currently be applied — [04-release.md](04-release.md) §0.4 warning 1 `[HOST 2026-09-11]` |
| the two-role split is real | `\dp admin_audit_log` shows no `w`/`d`/`D` for `hbd_app`, and `/api/audit/verify` reports `chainProtection` as something other than `hmac-only` | **FAIL. The control is not deployed.** `hbd_app` **owns** `admin_audit_log` and all 29 tables; no `REVOKE`; zero `CREATE FUNCTION`. §4 `[HOST 2026-09-11]` |
| the audit chain is intact | the same call's `ok: true` **and** `isComplete: true` — the walk stops at 50 000 rows in batches of 500 (src/bayram/db/admin/audit.py:129, :132, and `is_ceiling_reached` at :647-654), so `ok` alone is not a verified whole chain | **`[UNPROVEN]`** — needs an ADMIN/OWNER session in the panel. Six `admin_audit_log` rows and one `audit_chain_anchors` row existed at the 14:06:53 dump, so there is a chain to verify `[HOST 2026-09-11]` |
| the crons are running | rows in `purge_runs`: check `ran_at`, `is_batch_full`, and whether `storage_keys_returned` exceeds `storage_keys_deleted` | **PASS, indirectly.** Four `purge_runs` rows in the 14:06:53 dump, consistent with the hourly `:17` sweep having fired four times since the 09:24 rebuild. The column values are `[UNPROVEN]` without `psql` `[HOST 2026-09-11]` |
| the data roots agree | open a delivered asset in the panel; a 404 with the row present is the symptom | **PASS by construction.** One `WorkingDirectory=/var/lib/hbd` on all four units. §10 `[HOST 2026-09-11]` |
| a monitor can see failure | `/readyz` with the probe token returns `database`, `redis`, `configVersion` | **`[UNPROVEN]`.** Whether `HBD_ADMIN_PROBE_TOKEN` is set is behind `/etc/hbd` mode `0750`. Nothing on the box polls it — no timer, no cron `[HOST 2026-09-11]` |
| **the deploy account's privileges are scoped** | `sudo -n -l` | **Scoped, and already wrong for the rename.** §10.1 `[HOST 2026-09-11]` |
| **Redis survives a restart** | `redis-cli config get appendonly save` | **FAIL.** `appendonly no`, stock `save`. §5 `[HOST 2026-09-11]` |

Two things are worth saying plainly because nothing in the repository will say them for you.

**Logs are the only signal for several controls.** Every process emits one JSON object per
line whenever `BAYRAM_IS_DEBUG` is false (src/bayram/logging.py:230-243) — the level does not change
the format, so turning on debug to get more detail silently switches the whole stream to
unparseable plain text. The envelope is `ts`, `level`, `logger`, `message`, `correlation_id`
plus `context`; the event name, where there is one, lives *inside* `context`, so a query must
be `context.event` rather than a top-level field. Only the admin subsystem emits named events
at all — the bot, worker and pipeline log English prose. The two that should page are
`admin.audit.chain_broken` and `admin.audit.revoke_missing`. And the audit write path can
never fail a request (src/bayram/admin/audit_sink.py:99-135), so an audit outage is invisible to
the client and visible only as `admin.audit.write_failed` in the journal. If the journal is
shipped nowhere, the audit log can stop being written to without anyone learning.

> **SUPERSEDED 2026-09-11, kept because the distinction it collapsed is the point.** This
> paragraph read: *"**Nothing in this repository backs anything up.** No `pg_dump`, no snapshot
> script, no backup step in the deploy proposal — the only occurrence of 'backup' anywhere under
> `src/` is src/bayram/pipeline/assets.py:391, where it means a fallback vendor."* The `src/`
> observation is still true and still worth knowing. The rest is now false in one direction and
> understated in the other.

**Something backs the database up before a migration. Nothing backs it up on a schedule.** Two
different claims with two different owners:

- **Ad-hoc, and it works.** `deploy/deploy-payme.sh:39` and `deploy/cutover-to-bayram.sh:60`
  both run `sudo -u postgres pg_dump hbd | gzip > "$BACKUP"` as step 1, *before* the migration,
  and both refuse to continue on an empty dump `[TREE 2026-09-11]`. `/var/backups/hbd/` holds
  **nine** such dumps in three families — five `pre-payme-*`, two `pre-wipe-*`, two
  `pre-cutover-*`, 563 B to 23,532 B `[HOST 2026-09-11]`. That ordering is the pattern to keep;
  [`08-payme.md`](08-payme.md) §11.4 argues it. `/var/backups/bayram/` does not exist, which
  matters because one uncommitted `deploy/` script would write there — [04-release.md](04-release.md)
  §0.4 warning 4.
- **Scheduled: still nothing.** No `hbd` or `bayram` systemd timer, `/etc/cron.d` holding only
  `e2scrub_all` and `sysstat`, and `crontab -l` → `no crontab for developer` `[HOST 2026-09-11]`.
  `systemctl list-timers` shows `aizu-backup.timer` and it is a trap — `Description=Aizu SQLite
  nightly backup`, for the unrelated application on this box
  ([`00-host-inventory.md`](00-host-inventory.md) row 33). **ENV-6 is unimplemented on the host
  as well as in the repository**, and the four-item list below is still the list nothing covers.

> **A finding that belongs in [`07-security.md`](07-security.md) and must not wait for it.**
> `/var/backups/hbd/` is `drwxr-xr-x root root` and every dump in it is `-rw-r--r--` — **world
> readable** `[HOST 2026-09-11]`. Any local account on the box can read a complete database dump,
> `credit_ledger`, payment receipts and `admin_audit_log` included, and this box has at least two
> unrelated service accounts. The callout at the end of this section argues that a backup holding
> both the audit table and the HMAC key is a backup an insider can rewrite; the same reasoning
> applies to a dump anyone can read, and it is unstated everywhere. It is also how §4's and §7's
> audit answers were obtained without database access — `zcat | grep` over schema metadata and
> `COPY` headers only, no customer rows read. **That a surveyor could do that at all is the
> finding.**

**The requirement exists; only the implementation is missing.** `docs/product/SCOPE_OF_WORK.md:716`
(**ENV-6, MUST**) is "Nightly Postgres backup with PITR, 30-day retention, and **a restore
drill executed and documented before launch**", and `:721` (**ENV-11, MUST**) specifies a
five-step tested post-restore reconciliation — ledger and payments reconciled against each
rail across the restore gap, Redis dedup sets rebuilt, already-delivered orders suppressed,
`reminders.next_fire_at` recomputed, and a report published — with `:722` (ENV-12) requiring
the drill twice a year. So this is not an unstated requirement; it is a stated MUST that no
code, script or deploy step in this checkout implements. Treat the list below as what that
MUST has to cover — four things, three of which are not the database:

1. **Postgres** — **every table in schema `public`**, including `credit_ledger`,
   `plan_purchases` and `topup_purchases`, which migration 0020's docstring calls receipts that
   answer disputes "months after the recipient's name, the note and the audio are lawfully gone".
   (The count was "22 tables" until 2026-09-11; it is **29** as of revision `0024`
   `[HOST 2026-09-11]`, the Payme and broadcast rails having arrived since. A count in prose goes
   stale with the next migration, so this list names the scope instead.)
2. **`var/archive`** — the delivered audio and every customer avatar, in one tree.
3. **Redis** — the only copy of every in-progress wizard draft and of the queue.
4. **`BAYRAM_ADMIN_AUDIT_HMAC_KEY`** — which lives in the admin env file and nowhere else. The
   chain is `HMAC-SHA256(key, "v1" ‖ prev_hmac ‖ canonical_json(row))`
   (`CHAIN_VERSION` at src/bayram/db/admin/audit.py:111, the MAC input built at :396) with **no
   key identifier anywhere on the row** — `AdminAuditRow` (src/bayram/db/models/admin_audit.py:115)
   carries `chain_hmac` and `prev_hmac` (:193-197) and no key-id or key-version column at all.
   Rotate or lose that key and `/audit/verify`
   reports a break at seq 1 for the rest of the log's 730-day life, indistinguishable from
   tampering. There is no rotation path in the code.

> A database-only restore comes back with an audit log nobody can verify, rows pointing at
> archive objects that are gone, and no in-flight orders. Back the key up *separately* from
> the database — a backup containing both the table and the key is a backup an insider can
> rewrite.

---

## 13. The audit result — `aizu` compared against this document, 2026-09-11

> **SUPERSEDED 2026-09-10, kept because it dates the change.** This section was, until today, a
> list of open questions, and it closed: *"Every item below is a question this repository cannot
> answer… Answering any of these takes host access. Assuming any of them is how a control that
> was never deployed gets reported as deployed."* The closing sentence is the most important one
> in this document and stands unchanged. The premise does not: host access exists, the questions
> have been asked, and **most of them are now answered**.
>
> What replaces the list is a result table in two halves — answered, and `[UNPROVEN]`. Every row
> carries the command that answered it and the date it was run, because an answer with no date and
> no method is a rumour.

**How to read the verdicts.** `PASS` means the host does what this document asks. `FAIL` means it
does not, and the consequence is named. `DIFFERENT` means the host does something else that is
defensible — usually the wheel model — and the row says where that is argued. `[UNPROVEN]` means
nobody has looked *and nobody can*, with the blocker named; it is not a synonym for "probably
fine".

**Six rows are `[UNPROVEN]` and will stay that way without an operator password** — three of them
questions this section has always asked (`var/workspace` growth, the probe token,
`max_connections`) and three more that surfaced during the audit. They are separated out into
their own table below rather than mixed in with the answers, so the next surveyor knows which rows
are worth another attempt and which need a human with a password. The blocker is the same for all
six: `/var/lib/hbd` is
`0750 hbd:hbd` and untraversable from `developer`, `/etc/hbd` is `0750 root:hbd`, `sudo -n true`
returns `sudo: a password is required`, and the `NOPASSWD` drop-in grants `pg_dump` and
deliberately not `psql` (§10.1). Postgres's own log independently records the surveyor's blocked
attempts at 14:26:09–14:26:10 on 2026-09-10 — `role "developer" does not exist`, `password
authentication failed for user "hbd_app"`, `… for user "hbd"` `[HOST 2026-09-11]`.

### Answered

| § | The question | Answer on `aizu` | Evidence |
| --- | --- | --- | --- |
| §10 | Does `aizu` use systemd, under these unit names and paths? | **DIFFERENT.** Yes, systemd — four units named `hbd-bot`, `hbd-worker`, `hbd-admin`, `hbd-payme` in `/etc/systemd/system/`, and **no** `bayram-*` unit. `ExecStart=/opt/hbd/venv/bin/python`, `WorkingDirectory=/var/lib/hbd`, `User=hbd`. The repository's `deploy/systemd/bayram-*.service` files are wrong for this host and `deploy/cutover-to-bayram.sh:16-18` says so. | `systemctl show`; `ls /etc/systemd/system/` `[HOST 2026-09-11]` |
| §0 | Are all the processes running, on one box or split? | **PASS, one box, and there are four.** All four `active`. Postgres 16 and Redis 7 are on the same machine, listening on loopback only. The fourth process is the Payme gateway — [`08-payme.md`](08-payme.md). | `systemctl is-active`; `ss -ltn` `[HOST 2026-09-11]` |
| §2 §10 | What is each process's working directory, and do the bot's `Path.cwd()/var` and the admin's `BAYRAM_ADMIN_DATA_ROOT` resolve to the same absolute path? | **PASS.** `WorkingDirectory=/var/lib/hbd` on all four, so the data root is `/var/lib/hbd/var` for every process. The agreement holds — by one line repeated four times, with nothing checking that they still match. | `systemctl show -p WorkingDirectory` `[HOST 2026-09-11]` |
| §6 | Is `BAYRAM_ENVIRONMENT` the exact string `prod` in **each** process? | **PASS for three of four, and answered without reading a file.** `hbd-bot` and `hbd-worker` log `"environment": "prod"` on `host verified`; `hbd-admin` logs `"environment": "prod"` on `admin.boot.ok`. So every `prod`-gated refusal is armed in those three. **It does not generalise to the gateway**, which reads a third file — [`00-host-inventory.md`](00-host-inventory.md) row 20. | `journalctl` boot lines `[HOST 2026-09-11]` |
| §6 | Is `BAYRAM_ADMIN_ENABLED=true`, and does the admin connect as `hbd_app` rather than the owner? | **HALF.** `ADMIN_ENABLED` is `true` **by consequence**: the lifespan refuses to boot without it and `admin.boot.ok` is logged on every restart. Which role the panel connects as is `[UNPROVEN]` — it is a DSN inside `/etc/hbd/hbd-admin.env`. It is also now moot in one direction: with `hbd_app` owning every table (§4), *both* candidate roles can write the audit log. | `journalctl -u hbd-admin` `[HOST 2026-09-11]` |
| §4 §7 | Do both roles exist with the `ALTER DEFAULT PRIVILEGES` clauses, and **did 0007's REVOKE actually land?** | **FAIL — the REVOKE never landed and the two-role split does not exist.** `hbd_app` owns `admin_audit_log` and all 29 tables in `public`; the dump's only ACLs are `REVOKE USAGE ON SCHEMA public FROM PUBLIC` and `GRANT ALL ON SCHEMA public TO hbd_app`; `CREATE FUNCTION` count is **0**, so neither sweep function exists. `0007` took its `_skip` branch. `chainProtection` will read `hmac-only`. **This is the central question of §4 and §7, answered NO.** Cause and repair order: §4's audit box. | `zcat` over `/var/backups/hbd/pre-cutover-20260910-140653.sql.gz` — world-readable `[HOST 2026-09-11]` |
| §7 | Is the database at head? | **BEHIND BY ONE.** `alembic_version` holds `0024`; repository head is `0025`. All 25 revision files are on the host. `0025` adds two indexes and nothing else, so the running code tolerates the gap — but it **cannot be applied today**, see the row below. | the same dump; `ls /opt/hbd/migrations/versions/` `[HOST 2026-09-11]` |
| §7 | *(new question, 2026-09-11)* Can a migration be run on this host at all? | **FAIL, right now, silently.** `/opt/hbd/migrations/env.py:57` is `from bayram.config import env_file, load_settings` and the live venv has no `bayram` package, so the documented command dies at import with `ModuleNotFoundError`. `alembic.ini:15`'s `prepend_sys_path = %(here)s/../src` names `/opt/hbd/src`, which does not exist on a wheel host. Who overwrote those two files at 14:06:46 on 2026-09-10 is `[UNPROVEN]`. Full account and the three candidate repairs: [04-release.md](04-release.md) §0.4 warning 1. | `grep`; `python -c "import bayram"`; and the command's own traceback `[HOST 2026-09-11]` |
| §1 | Does the host's ffmpeg include libopus **and** an mp3 encoder? | **PASS on both.** ` A....D libmp3lame` and ` A....D libopus`, ffmpeg/ffprobe 6.1.1-3ubuntu5. The second half used to be unanswerable by inference; it is now answered directly. | `ffmpeg -hide_banner -encoders` `[HOST 2026-09-11]` |
| §5 | Is Redis persistent, and on what configuration? | **FAIL.** `appendonly no`; `save 3600 1 300 100 60 10000` — the stock defaults, RDB snapshots only. §5's audit box has the consequences, including the one §5 predates: a Redis rebuild silently un-pauses the Payme rail. | `redis-cli config get` `[HOST 2026-09-11]` |
| §11 | What terminates TLS, does it add HSTS, and does it append or replace `X-Forwarded-For`? | **DIFFERENT, and answered elsewhere in full.** **Not Caddy**, for anything from the internet: TLS terminates at Cloudflare's edge, a tunnel speaks plain HTTP to `127.0.0.1:80`, and Caddy is an internal `Host` demultiplexer behind it. HSTS `max-age=86400` on the admin block only. Admin traffic is two proxies deep. This row is another surveyor's area — [`00-host-inventory.md`](00-host-inventory.md) "How public traffic actually reaches this host" and rows 17, 39–43; [`08-payme.md`](08-payme.md) §4. | as cited there |
| §11 | Is `BAYRAM_ADMIN_PUBLIC_ORIGIN` the `https://` origin browsers actually reach, and is the panel reachable under a second name? | **PASS.** `admin.boot.ok` carries `public_origin=https://admin.bayrambot.uz` and `is_cookie_secure=true`; that hostname is a published tunnel route and answers `200` publicly. | `journalctl -u hbd-admin`; public `curl` `[HOST 2026-09-11]` |
| §8 | Is the deployed bundle current, or does it predate the nonce placeholder? | **PASS, at a different path.** One `__HBD_CSP_NONCE__` in `/opt/hbd/venv/lib/python3.12/site-packages/hbd/admin/static/index.html`, zero `__BAYRAM_CSP_NONCE__`. **On a wheel host it cannot drift**: bundle and package are one artefact. §8's audit box. | `grep -c` `[HOST 2026-09-11]` |
| §8 | *(new question, 2026-09-11)* Are the source maps in production? | **YES — FAIL.** `index-D9iMG-RF.js.map` is in the deployed `assets/`, served unauthenticated from a public hostname with a year-immutable cache. §8. Belongs in [`07-security.md`](07-security.md). | `ls .../static/assets` `[HOST 2026-09-11]` |
| §10 | How many worker replicas run? | **One.** One PID per unit, no template unit, no `@` instances — so the per-process vendor semaphore argument holds. | `pgrep -cf`; [`00-host-inventory.md`](00-host-inventory.md) row 9 `[HOST 2026-09-11]` |
| §12 | Is anything backing up Postgres, `var/archive`, or the audit HMAC key? | **Postgres: ad-hoc yes, scheduled no. The other two: nothing at all.** Nine hand-taken `pg_dump` files in `/var/backups/hbd/`, every one written by a deploy script somebody ran; no `hbd`/`bayram` timer, no cron, no `developer` crontab; `aizu-backup.timer` belongs to a different product. **And the dumps are world-readable.** §12. | `ls -la /var/backups/hbd/`; `systemctl list-timers --all`; `crontab -l` `[HOST 2026-09-11]` |
| §12 | Has ENV-6's restore drill ever been executed and documented, and does anything implement ENV-11's reconciliation? | **NO to both, on the host as well as in the repository.** There is nothing scheduled to restore *from* and no drill artefact anywhere. Both remain stated MUSTs that nothing implements. | as the row above `[HOST 2026-09-11]` |
| §10 | *(new question, 2026-09-11)* How is the deploy account granted its privileges, and is the grant still correct? | **Scoped, and already wrong for the next release.** Ten `NOPASSWD` lines, nine ours; `psql` and every read of `/etc/hbd` deliberately excluded. Every verb names an `hbd-*` unit or an `/etc/hbd` path, so **nothing covers `bayram-*`** and the cutover would lock the deploy account out of the units it creates — `deploy/cutover-to-bayram.sh:174` prints exactly that and does nothing about it. §10.1. | `sudo -n -l` `[HOST 2026-09-11]` |

### `[UNPROVEN]` — behind a privilege this deployment withholds on purpose

| § | The question | Blocker, and what would settle it |
| --- | --- | --- |
| §2 | Has `var/workspace` ever been cleaned, by anything? | `ls -la /var/lib/hbd` → `Permission denied` (`0750 hbd:hbd`; `developer` is not in the `hbd` group) `[HOST 2026-09-11]`. Needs `sudo du -sh /var/lib/hbd/var/workspace /var/lib/hbd/var/archive` and the sudo password. The only outside bound is the 38 GB root filesystem at 21% used (7.2 G of 38 G, 2026-09-11). **Worth a second attempt with an operator**, because the repository has no sweep for this tree at all and unbounded growth is the documented expectation. |
| §11 | Is `BAYRAM_ADMIN_PROBE_TOKEN` set, and is anything polling `/readyz` with it? | The value is in `/etc/hbd/hbd-admin.env`, mode `0750` on its directory `[HOST 2026-09-11]`. The **second half is answered and is a no**: no timer and no cron polls anything. So even if the token is set, nothing uses it — which makes the first half the less interesting half. |
| §10 | Does `max_connections` leave room above what the processes reserve? | `sudo -n -u postgres psql -Atc 'show max_connections'` → `sudo: a password is required`; the drop-in grants `pg_dump`, not `psql` `[HOST 2026-09-11]`. Note the arithmetic has changed since this section was written: it is now **four** processes, 30 + 30 + 10 + 5 = 75 against a stock 100 ([`08-payme.md`](08-payme.md) §3.1), leaving 25 rather than 30. |
| §11 | Are `BAYRAM_ADMIN_TRUSTED_PROXY_HOPS` / `_CIDRS` set, or still `0` and empty? | `/etc/hbd` is unreadable `[HOST 2026-09-11]`. **But the correct values changed when the tunnel did and nothing reported it**: admin traffic is now two proxies deep, so whatever the file says must be checked against `hops=2, cidrs=127.0.0.1/32`. The `hbd-payme` journal shows the shape — every request logged `"peer_ip": "127.0.0.1"`. [`00-host-inventory.md`](00-host-inventory.md) row 23. |
| §6 §4 | Which role does each process connect as, and is `BAYRAM_DB_MIGRATION_URL` set where the migration runner reads it? | Both are DSNs inside `/etc/hbd/*.env` `[HOST 2026-09-11]`. Partly moot: §4 establishes that `hbd_app` owns everything, so the REVOKE is not a control whichever role the panel uses. `deploy-payme.sh` sources `/etc/hbd/hbd.env` with `set -a` before calling alembic, so on this host the migration URL comes from the file either way. |
| §12 | Is the audit HMAC key stored anywhere but the admin dotenv file? | Unanswerable from `developer`, **and `pg_dump` does not answer it either** — a dotenv file is not in the database, so none of the nine dumps contains it. [`00-host-inventory.md`](00-host-inventory.md) row 35. This is the row a backup cannot fix: the chain carries no key id, so a host rebuild makes the whole audit log permanently unverifiable. |

### What the audit changed about how to read this document

**Three of this document's arguments are now known to describe controls that are not deployed**
— the two-role split (§4, §7), the `Environment=` pointer (§10) and the admin unit's
`InaccessiblePaths=` (§10) — and one describes a configuration that was never applied (§5's Redis
persistence). In every case the *argument* is still right; what changed is that it can no longer
be read as a description.

**Two are now known to be satisfied by a different mechanism**, and those are the ones to be
careful about: the wheel model (§3) and the console bundle (§8). "This host does it differently"
and "this host does it wrong" look identical in a checklist and are not the same finding. The
rows above say which is which, and [`08-payme.md`](08-payme.md) §11.1 is where the wheel model is
argued rather than merely observed.

**The closing sentence of the old §13 is the one line of it worth keeping verbatim**, and it is
now a statement about the `[UNPROVEN]` table rather than about the whole section:

> Answering any of these takes host access. Assuming any of them is how a control that was never
> deployed gets reported as deployed.
