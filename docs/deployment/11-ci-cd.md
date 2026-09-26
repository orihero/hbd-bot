# CI, and why CD stops at the door

**Written 2026-09-16.** The question that prompted it: *"why do I have to run those scripts
every time I deploy? Can't we implement CI/CD?"* The honest answer is **half yes**. CI is
straightforward, safe, and landed in the same change as this page. Continuous *deployment* is
not a workflow file on this host; it is three prerequisites that do not exist yet, and this
page says what they are so the decision is a decision rather than an omission.

---

## 1. What landed: `.github/workflows/ci.yml`

There was **no CI of any kind** before this: no `.github/`, no `.gitlab-ci.yml`, no
`Jenkinsfile`. Two documents already prescribed one — `TEST_INFRA.md` §7.3 ("Integration with
CI / Build Gates") and `TEST_READY.md` §2 ("Strict CI Gate") — against a repository that had
never run a check automatically in its life.

Five jobs, of which three are the gate:

| Job | Runs | Required |
| --- | --- | --- |
| `python` | ffmpeg, `uv sync --locked`, `make lint`, `make typecheck`, `make cov`, then the admin re-report at 85% | yes |
| `node` | `npm ci`, then `typecheck` / `lint` / `test:unit` / `test:e2e:strict` / `build` / `check:built-shell` as six separate steps | yes |
| `migration-safety` | refuses destructive DDL in revisions new to the PR | yes (PR only) |
| `integration` | Postgres 16 + Redis 7, `hbd_test` bootstrapped, `-m integration` | **no — opt-in by label** |
| `gate` | one check to mark required in branch protection | — |

### The five things that would have made it red on day one

Each of these was found by reading the repository, and each is fixed in the workflow rather
than left to be discovered on a Monday.

1. **`cov-admin` has `cov` as a Make prerequisite** (`Makefile`: `cov-admin: cov`). The obvious
   workflow — `make check` then `make cov-admin` — runs the ~4 800-test suite **twice**. The
   job runs `make cov` once and then the *body* of `cov-admin` against the coverage data that
   run already wrote.
2. **`uv sync --locked`, not `make install`.** The `install` target is
   `uv pip install -e ".[dev]"`, which **ignores `uv.lock` entirely** — CI would have been
   testing a dependency set the lockfile does not describe. `--locked` also fails on drift,
   which nothing has ever caught. Verified with `uv lock --check`: no drift as of 2026-09-16.
3. **uv must be pinned, and not to an old version.** `uv.lock` declares `revision = 3`, a
   lockfile format older uv releases **reject outright**. The pin is `0.11.31`, the version the
   lock was verified against. An unpinned installer is one release away from a red tree that
   has nothing to do with the code.
4. **The unit job needs ffmpeg** — not only the integration job.
   `tests/test_runtime/test_entrypoints.py` calls `main_module.run(...)`, which reaches
   `bayram.audio.startup.verify_host` and probes for ffmpeg **with libopus**. It carries no
   `integration` marker, so it runs in the ordinary gate. A minimal static ffmpeg will not do.
5. **`npm test` fetched its own runner over the network.** The script was
   `npx tsx tests/run-all.ts`, and `tsx` appeared in `package-lock.json` only as an *optional
   peer dependency* of something else — it was not installed. Every CI run would have
   downloaded an unpinned package from the registry and executed it. Fixed at the source:
   `tsx` is now a pinned devDependency and the three scripts dropped the `npx`.

### Two deliberate choices

**`test:e2e:strict`, not `test`.** Plain `npm test` exits 0 even with
`PENDING_IMPLEMENTATION` assertions outstanding; strict fails on them. Measured 0 pending on
2026-09-16 (55 passed), so this is a real gate today and stays honest as tiers are added.

**`TZ: UTC` and `LANG: C.UTF-8` on every job.** Nothing pinned either. The Python side is
deliberately UTC-day-based (`src/bayram/db/admin/sql.py`, and the Asia/Tashkent traps
`tests/test_db/test_activity_snapshots.py` is written around), so a runner in another zone
tests a different program.

### A third, added 2026-09-19: the production build is a CI step

**The production build is in CI, and it is there for one specific reason.** `npm run build`
and `npm run check:built-shell` were added to the `node` job on 2026-09-19. The build is the
only step anywhere that produces `src/bayram/admin/static/index.html` — `.gitignore:63` excludes
that directory, so **no Python test can ever see the shell that actually ships**. Everything
Vite does to the document head between source and output is invisible to `pytest` by
construction: a plugin that injects an inline `<script>`, or a head rewrite that drops the
`__BAYRAM_CSP_NONCE__` placeholder, would be caught by nothing. `check:built-shell`
(`admin-dashboard/tests/built-shell-csp.ts`, jsdom) parses the emitted file and applies the same
rules `tests/test_admin/test_csp_shape.py` applies to the source shell, plus the one only it can
check — that the nonce placeholder survived the build. It **fails, never skips**, when the build
output is absent. A second effect worth naming rather than discovering: CI had never built the
SPA at all, so a broken production build was previously caught by nothing either.

> **Adding a build to a green job is a behaviour change independent of CSP.** It passes locally
> (vite 6, 2.02 s, one chunk-size warning that is not an error), but it will surface any latent
> build failure on the next push. Land it as its own commit so a build break is not read as a
> CSP-test failure.
>
> **And `Makefile`'s `ui-check` (line 126) now runs a strictly smaller set than CI** — four
> scripts where CI runs six. Until it is updated, a green `make ui-check` does not predict a
> green `node` job. That edit is owed; it is listed in this page's open items.

### The integration job is opt-in, and the reason is not timidity

**Nothing in this repository has ever created the `hbd_test` database.** `docker-compose.yml`
creates `hbd`; `docker/initdb/10-two-roles.sql` grants inside `hbd`. So on any clean machine
every Postgres suite **skips**, and a job that runs them reports green having tested nothing.
Where those tests "fail on permissions" instead, somebody created the database by hand and the
grants never followed.

The job therefore bootstraps `hbd_test` and **both roles** explicitly — the two-role split is
not decoration, because `tests/test_db/test_audit_purge_privileges.py` exists precisely to
prove the *app* role cannot delete an audit row before its clock is up. Against a single
superuser role that test passes while proving nothing.

It also asserts a **skip floor**: if more than half the suite skipped, the services were not
reachable and the job fails rather than reporting a green that means silence. Every heavy
module skips rather than fails when its dependency is absent, so silence is the default
failure mode here and has to be made loud on purpose.

Label a PR `run-integration` to exercise it. Promote it to required only once it has been
green for a while — it has never been green anywhere.

### The tree was not green when this was written

`make typecheck` **failed**, with eleven errors accumulated in `tests/` — none of them from
that day's work, all of them invisible because nothing had ever run the gate. They were fixed
in the same change. Two were not cosmetic:

- **`tests/test_checkout/test_intents.py`** — `_RecordingOpener` no longer matched
  `PaymentIntentOpener`, which had grown `resume_order_id: UUID | None` with the resume path.
  `checkout.py` predicted this in its own docstring: *"`runtime_checkable` verifies member
  PRESENCE only, never signatures — an `isinstance` check in a wiring test will accept a
  drifted fake — so `mypy --strict` over `tests` is what actually holds the shape."* The
  design was right; the gate was never run.
- **`tests/test_db/test_payme_ledger.py`** — `assert narrow is wide is ledger` compares two
  unrelated protocol types, so `--strict-equality` read it as an impossible identity check and
  marked everything below it **unreachable**, including
  `assert not hasattr(PaymentIntentOpener, "perform")` — the security property the test exists
  to prove. Three assertions had silently stopped being checked.

The other nine were honest typing gaps (`logging`'s `extra=` fields are not declared on
`LogRecord`; an optional `Brief.recipient` dereferenced without a guard; a `list[Any]` returned
where a `datetime | None` was declared).

**Measured after the fixes, 2026-09-16, on a developer machine:** `make lint` clean;
`make typecheck` clean over 647 files; `make cov` **8 034 passed, 56 deselected, 94.46%,
9m31s**; the console's four scripts green (318 vitest tests, 55 locale assertions, zero
pending). **Read "four" as "six" from 2026-09-19** — `build` and `check:built-shell` joined
them; the four numbers quoted here are the 2026-09-16 measurement and are left as measured.

**Measured on a hosted runner, same day, run 35080297500 — all five jobs green:**

| Job | Duration |
| --- | --- |
| `Python — ruff, mypy, unit suite` | **32m 06s** |
| `Console — typecheck, lint, vitest, locales` | 1m 20s — **expect this to rise.** The two steps added 2026-09-19 are a Vite production build (2.0 s locally; budget 20–40 s on a hosted runner) plus a jsdom parse of its output. Not re-measured on a runner yet. |
| `Migrations — additive-only` | 5s |
| `gate` | 2s |

The Python job is **3.4x slower** on a hosted runner than on a developer machine, which is why
`timeout-minutes` is 60 and not the 45 it was written with: thirteen minutes of headroom on a
suite that grows every commit is how a gate ends up failing on the clock rather than on the
code, and teaching everyone to re-run it. Both of the steps nothing had ever exercised held:
`uv sync --locked` installed from the lockfile for the first time in this project's history,
and ffmpeg-with-libopus satisfied `verify_host`.

The first run of the workflow also found a defect **in the workflow** — the migration tripwire
grepped whole revision files, so it flagged every revision ever written, because every
`downgrade()` drops what its `upgrade()` created. Fixed to parse only the `upgrade()` body
with `ast`, and split into two severities: `drop_column`/`drop_table` fail, `alter_column`
warns (widening and narrowing are indistinguishable without reading it), `drop_constraint`
and `drop_index` are out of the pattern entirely.

### Before marking `gate` required

Land the workflow with **no branch protection**, let it run on a branch and on `main`, and
confirm the hosted-runner numbers match the local ones above. Only then make it required.

> **The `gate` job was audited on 2026-09-19 and its verdict did not change.** The suspected
> defect — a skipped dependency passing green — **is not present**: `if: always()` plus explicit
> per-result tests, plus `success|skipped` for `migration-safety` alone (which is legitimately
> `pull_request`-only), already gives the right answer. Verified against a nine-case truth table.
> Two hardening edits landed, neither changing any verdict:
>
> - **`timeout-minutes: 5`.** Every other job bounds itself. A *required* check with no clock
>   blocks the merge button until somebody cancels it by hand.
> - **Accumulate, then exit.** `bash -e` aborted on the first failing `test`, so an operator only
>   ever saw one broken dependency. `python=failure node=failure` now reports both.
>
> `integration` is still deliberately **not** in `needs:`.

**Turning protection on** (once, from a workstation with `gh` authenticated):

```bash
echo '{"required_status_checks":{"strict":true,"contexts":["gate"]},"enforce_admins":false,"required_pull_request_reviews":null,"restrictions":null}' \
  | gh api -X PUT repos/orihero/hbd-bot/branches/main/protection --input -
```

Three things to know before running it. **`main` has no protection and no rulesets today**
(confirmed `404` / `[]`), is a single `Init` commit, and does not contain
`.github/workflows/ci.yml` at all — everything is in open draft PR #1. **The first thing
protection does is block that draft** until `gate` is green on it; `gate` *is* green on PR #1
(run 35190944330), so this is survivable, but confirm before clicking. If the required-checks
picker does not offer `gate`, the call above writes the literal name and it stays pending until
a run produces it. And **`enforce_admins` is `false` deliberately**: with one maintainer, `true`
means the maintainer cannot merge their own emergency fix without a green gate. Revisit once a
second person has push rights.

---

## 2. Why CD stops at the door

Three architectures were designed and judged on correctness, security blast-radius and
six-month maintainability. The verdict was unanimous across all three lenses.

| Architecture | Score | Killed by |
| --- | --- | --- |
| **Operator-triggered, CI-built artifact** | **8 / 8 / 8** | — |
| Signed-bundle pull agent on a timer | 5 / 6 / 6 | Automatic rollback driven by health signals this host does not have |
| Self-hosted GitHub Actions runner | 3 / 4 / 3 | Memory, and blast radius |

### The constraints that decide it

**The host cannot be reached inbound.** `abdu-test` has no public IP; every byte of public
traffic arrives through a Cloudflare token-run tunnel whose ingress lives in the Zero Trust
dashboard, not on the machine. A GitHub-hosted runner **cannot** SSH in. That is not a
configuration gap — it is the security posture, and it should stay.

**The migration step cannot be de-privileged.** All three deploy scripts feed alembic its DSN
with `set -a; . /etc/bayram/bayram.env; set +a`. That file holds the bot token and four vendor
credentials. *Whatever runs `alembic upgrade head` has every production secret sourced into its
environment.* This is the strongest argument against a GitHub-hosted runner doing the deploy,
and it is why the privileged half stays on the box.

**A self-hosted runner does not fit, twice over.** `00-host-inventory.md` row 1 names memory as
"the real constraint" — roughly 831 MiB available with four Python processes, Postgres, Redis,
Caddy and cloudflared resident. A runner takes 200–250 MB while a job runs. And a single
`runs-on: self-hosted` reaching a PR-triggered job — by copy-paste, by a `needs:` chain —
executes branch-authored code on the production host. The box also has no compiler and no
Node, so it could not build the artifact anyway.

**There is nothing to roll back to, and nothing to notice.** `00-host-inventory.md` row 34:
backups are *"Nothing. No timer, no cron, no copy off-box."* `admin/routers/health.py` returns
a constant `ok` to any unauthenticated caller, so it cannot distinguish a healthy release from
a broken one. **Automatic rollback needs a health signal that does not exist.** Automating
deploys onto a single unbacked host with no monitoring does not remove risk; it removes the
human who would have noticed.

### What the user was actually complaining about

Not the absence of automation — the **per-feature scripts**. `deploy-d17.sh`,
`deploy-payme.sh` and `deploy-support.sh` are the *same seven beats in the same order*:

```
0  preflight   (wheel, env file, alembic.ini, migrations staged)
1  backup      pg_dump | gzip  →  /var/backups/bayram/pre-<name>-<stamp>.sql.gz
2  revision    alembic current
3  MIGRATE     alembic upgrade head
4  install     pip install --force-reinstall --no-deps WHEEL  &&  pip check
5  restart     systemctl restart the fleet, then is-active
6  verify      import the new modules, assert schema and settings
```

They share an identical constants block (`/opt/bayram/venv`, `/etc/bayram/bayram.env`,
`/var/backups/bayram`, …). Nothing feature-specific lives in steps 1–5. **One idempotent,
versioned `bayram-release` script replaces all three**, and that — not a deploy robot — is the
fix for "why do I run these scripts every time".

Two details worth keeping when it is written:

- `deploy-support.sh`'s **wheel-bundle preflight**: it opens the wheel as a zip and asserts
  `bayram/admin/static/` is non-empty, because that directory is gitignored and force-included
  as a hatchling artifact, so a wheel built without `make ui-build` ships **last release's UI**.
  In a pipeline this moves left — CI builds the wheel and asserts the bundle is fresh, and the
  per-release magic-string hack disappears.
- The backup's `test -s` guard: *"a `pg_dump` that failed on permissions still leaves a valid,
  empty gzip."* That guard is the only thing making the migrate-first order survivable.

And one trap: `pip install --no-deps` encodes an assumption — that the release adds no runtime
dependency — which `pip check` catches only *after* installing. CI should diff the wheel's
`Requires-Dist` against the installed set at **build** time.

### The prerequisites, in order

Nothing below is CI work, and everything below makes automation either safe or theatre.

1. **Read `sudo -n -l` on the host.** `cutover-to-bayram.sh` says `/etc/sudoers.d/hbd-deploy`
   still names `hbd-*` units, and nothing shows `deploy/sudoers.d/bayram-deploy` was ever
   installed — so the live grant set may cover **none** of the four running units. Design
   nothing privileged until that answer exists. (This is also why an unattended restart cannot
   work today: `sudo` prompts for a password.)
2. **Schedule a database backup.** A systemd timer, `pg_dump`, and a copy off-box. Today the
   only backups that exist are the ones a deploy script happens to take.

   **STANDING, 2026-09-19 — three separate facts, and only the first is done.**
   *(a)* **The installer exists**, at `deploy/install-bayram-backup.sh`. It writes the timer, the
   unit and `/opt/bayram/sbin/bayram-backup`.
   *(b)* **It has still never been run on the host.** Verified read-only 2026-09-19: no
   `bayram-backup` unit in `/etc/systemd/system`, nothing for it in `systemctl list-timers`, and
   `/opt/bayram/sbin` holds only `bayram-release`. **So there is still no scheduled backup on
   `abdu-test`.** Running it is two commands and they are in [`05-operations.md`](05-operations.md).
   *(c)* **It now ships an off-box copy that is inert until a destination is set.** Three
   transports behind one switch; the mechanism needs no further decision, the destination does.
   See item 4 under *Before this is run for the first time*.

   > **The install line this page used to imply does not exist.** Anything of the form
   > `scp deploy/systemd/bayram-backup.timer aizu:…` names a path that was never in this
   > repository — the installer *generates* the unit and the timer, it does not ship them as
   > files. That wrong path is the likeliest reason the installer was copied to the host on
   > 2026-09-17 and then never run. The correct pair is `scp deploy/install-bayram-backup.sh
   > aizu:/tmp/…` then `ssh -t aizu 'sudo bash /tmp/install-bayram-backup.sh'` — and re-stage it
   > in the same breath rather than trusting the developer-owned copy sitting in a
   > world-writable `/tmp` since Sep 17.
3. **Give `/healthz` something to say.** Until a health check can distinguish a good release
   from a bad one, "automatic rollback" is a phrase, not a mechanism.
4. **Then** write `bayram-release` as one versioned script, invoked by a human, consuming a
   CI-built artifact. Automatic deployment remains a later decision, and a small one once the
   three above are done.

### On signing

If a CI-built artifact is ever pulled by the host, `sha256` alone is not enough: the manifest
and the bundle come from the same publisher, so the host would verify *integrity in transit*
and never *authenticity*. Sign the manifest (Ed25519) and put the public key on the host. Note
what that implies — a signing key in GitHub Actions **is** unattended root on the payment host,
which is why the key belongs with the operator-triggered flow, where a poisoned bundle still
waits for a human, and not with a timer.

---

## 3. The CD artifacts — written 2026-09-16, NEVER RUN

Four files landed. **None has executed against the host, and the host layout they assume does
not exist yet.** Treat them as a reviewed draft, not a tested tool.

> **PARTIALLY SUPERSEDED — the heading's "NEVER RUN" is true of three of the four, not all four.**
> `deploy/bayram-release` has been installed and used: the host carries it at
> `/opt/bayram/sbin/bayram-release` and the first real deploy through it was 2026-09-17. The
> layout it assumes **does** exist. `release.yml`, `install-bayram-backup.sh` and the three
> scripts added on 2026-09-19 have still never run against `abdu-test`.
>
> **And the host copy is installed BY HAND — the wheel bundle does not carry it.** The file on
> the host is a standalone 67 180-byte copy dated 2026-09-17, so **editing `deploy/bayram-release`
> in this repository changes nothing on the host until somebody copies it up.** A release will
> not do it for you. See [`04-release.md`](04-release.md) §7 for the two commands.

| File | What it is |
| --- | --- |
| `.github/workflows/release.yml` | The producer. Builds console → wheel → bundle, publishes a GitHub Release asset. |
| `deploy/bayram-release` | The consumer. One script replacing the three per-feature ones. |
| `deploy/sudoers.d/bayram-release` | The grant. `visudo -cf` clean. |
| `deploy/install-bayram-backup.sh` | Installs the daily backup timer — prerequisite 2. **Exists; STILL never run on the host** (verified read-only 2026-09-19). Since 2026-09-19 it also installs an env-configured off-box copy that is **inert until a destination is set** in `/etc/bayram/backup-offbox.env`. |

Three more landed on 2026-09-19, all of them **operator-run scripts rather than installed
artefacts** — copy to `/tmp`, run with `sudo`, delete:

| File | What it is |
| --- | --- |
| `deploy/set-probe-tokens.sh` | Generates and installs the two `/readyz` probe tokens, preserving each env file's existing owner and mode, then restarts `bayram-admin` and `bayram-payme` and **proves** the tokens took by reading the gated body. `--rotate` / `--admin-only` / `--yes`. |
| `deploy/prune-stale-sudo-grants.sh` | Removes the stale sudo grants. `plan` is the default and is a **dry run that writes nothing**; `apply` is the only verb that writes. Two extra flags, both off by default: `--drop-blanket` (also removes `/etc/sudoers.d/90-developer-nopasswd`) and `--drop-pg-dump` (also removes `(postgres) NOPASSWD: /usr/bin/pg_dump hbd`). Both are owner decisions — see [`07-security.md`](07-security.md). |
| `deploy/sudoers.d/bayram-deploy` | Rewritten as the **post-cutover** grant file, and it is now the whole of the operational grant: the Caddy reload/restart/validate verbs moved here out of `hbd-deploy` so that file can be pruned without taking the Payme front end's operational verbs with it. |

> **A load-order dependency that is easy to break by accident.** `sudo` reads `/etc/sudoers.d`
> in **lexical order and the last match wins**. `/etc/sudoers.d/bayram-release`'s `PASSWD:`
> lines — the ones that keep `deploy`, `rollback` and `backup` prompting — are only effective
> because `bayram-release` sorts *after* `90-developer-nopasswd`. **Renaming that file to
> anything sorting before `90-` silently makes those three verbs passwordless.** The same
> ordering is why every narrower grant in `deploy/sudoers.d/` is decorative while the blanket
> rule stands.

### The bundle contract, frozen

A first attempt produced four individually-good artifacts that **did not work as a set**: the
producer's tarball had a leading directory the consumer did not strip, eight manifest fields
were named differently on each side, and a signature check *warned and continued* against a CI
that never signed. The fix was to freeze one contract and regenerate against it. A reviewer
then built a real bundle and ran the consumer's preflight over it verbatim: it round-trips.

Two decisions in that contract are worth knowing:

**There is no signing in v1, deliberately.** The manifest hashes the files beside it in the
same tarball, so it proves the bundle is internally consistent and undamaged in transit. It
proves nothing about authorship — anyone who can write the tarball can write the manifest.
Authenticity rests entirely on who can write to `/opt/bayram/release/incoming/` (0770
root:developer). A check that passes when the key is absent is worse than no check, because it
reads as protection in a runbook; that is exactly how the first attempt failed. Ed25519 is v2.

**No path argument is ever passed.** `deploy` scans a fixed directory and refuses on zero or
more than one bundle. This is what makes the sudoers grant safe: `sudo` matches with
**fnmatch, not regex**, so `deploy [A-Za-z0-9._-]*` does not mean "a token of safe characters"
— the class matches one character and the `*` then matches anything, `/` and `..` included. The
grant lists five fixed, fully-specified commands and nothing else.

### What the adversarial pass caught, and what it revealed about the project

Six blockers were found and fixed. Two were defects in the generated script; one was a fact
about **this repository** that nothing else had surfaced:

* **`pyproject.toml` pins a static `version = "0.1.0"`.** Every wheel ever built is named
  `bayram_bot-0.1.0-py3-none-any.whl`. Keyed on that basename, the wheel store would overwrite
  itself on every deploy and **`rollback` would reinstall the wheel it was backing out of, and
  report success.** Worked around by keying the store on the manifest's release string
  (`/opt/bayram/wheels/<release>/`). **The real fix is a version derived from the git tag
  (`hatch-vcs`). **DONE 2026-09-16**, in the same branch: `pyproject.toml` now declares
  `dynamic = ["version"]` with `[tool.hatch.version] source = "vcs"`, so the version comes off
  the git tag and an untagged build is `0.0.1.devN+g<sha>` — unique per commit, honest about
  being untagged. `fallback_version = "0.0.0"` is load-bearing: this repository has **no tags
  at all** yet, and without it every checkout that cannot see one fails at build time.

  Two consequences worth knowing. `uv.lock` records the project's own version, so it had to be
  regenerated — `uv sync --locked` caught that immediately, which is the drift that step exists
  for. And ci.yml's python job now clones with `fetch-depth: 0`, because `uv sync` builds the
  project and a shallow clone leaves setuptools_scm unable to describe.

  The evidence this hurt already is in `dist/`: the wheels there carry hand-stamped build tags
  (`0.1.0-20260914d`, `-20260915`, `-20260915b`) because somebody needed to tell two builds
  apart and the version could not. The per-release wheel-store directory in `bayram-release`
  stays regardless — it costs nothing and makes the store readable.
* **`do_verify` imported `bayram.worker`**, whose module scope runs `_SETTINGS = _settings()`
  and therefore needs the env file — which this script deliberately scopes to the alembic call
  alone. Every deploy would have exited 4 *after* installing the wheel and restarting the
  fleet. The module is out of the import list; `systemctl is-active bayram-worker` is what
  proves the worker loads, under the environment systemd gives it.
* **`STAGE_EXIT=0` was set with three fallible statements still to run** and the `ERR` trap
  still armed, so a failure in the tail would have exited 0 — a failed deploy reporting
  success. Cleared only after the last statement that can fail.
* **A crash-looping unit passed the gate.** The live units are `Restart=on-failure`,
  `RestartSec=5`, so a unit dying on boot reads `active` to any single sample four seconds
  after a restart. `NRestarts` is now compared across the settle window.
* **`plan` refused non-additive bundles**, because the refusal lived in `preflight`. A dry run
  that will not run for the release you most need to understand is not a dry run.
* **A real gap in all three predecessor scripts**: none asserts the result of `alembic current`.
  The expected revision appears only in an `echo` banner, so **migrating to the wrong head is a
  silent success today**. The manifest's `migrations.head` makes it an assertion.

### Before this is run for the first time

1. ~~`sudo -n -l` on the host.~~ **DONE, 2026-09-16 — and it corrected two things.**

   The `bayram-*` units **are** granted: an extensive NOPASSWD block covers
   enable/disable/start/stop/restart/status/is-active on all four, alongside a stale set of
   `hbd-*` grants for units that no longer exist. The worry that the live set might cover none
   of them was wrong.

   The first line of the grant list is `(ALL : ALL) ALL`, so `developer` can already run any
   command as any user with a password. A scoped drop-in therefore buys no containment; what it
   buys is a small passwordless subset and a release path somebody can audit.

   **And it exposed a passwordless root escalation that exists today.** The live set contains
   `(root) NOPASSWD: /usr/bin/bash /opt/hbd/deploy-payme.sh`, and that file is
   `-rwxr-xr-x developer developer` inside a `developer`-owned directory. The account being
   granted **owns the script sudo runs as root without a password** — write anything into it,
   run it, you are root with no prompt. Precisely: `developer` already has `(ALL:ALL) ALL`, so
   this turns *password-protected* root into *passwordless* root rather than creating root
   access. On a host terminating payment callbacks that still matters — anything running as
   `developer` (a stolen key, a compromised process, unattended automation) gets root without
   the password, and the `use_pty` audit intent is bypassed. The fix is to delete that grant;
   `deploy/bayram-release` replaces the script it exists for. If it must stay in the interim,
   `chown root:root` the target. **The rule: a NOPASSWD grant naming a script path must never
   name a file writable by the account being granted.** `/opt/bayram` is correctly `root:root`,
   which is why the release script installs there and not into the old `/opt/hbd` tree.

   Two more grants are exposure rather than escalation and want a decision:
   `NOPASSWD: tee /etc/bayram/payme.env` (root write into a credential file) and
   `(postgres) NOPASSWD: pg_dump hbd` — the standing data-exposure grant this page argued
   against, already live. `bayram-release` dumps as root and does not need the latter.
2. **Create the layout.** `/opt/bayram/sbin`, `release/incoming`, `release/work`, `wheels` —
   the commands are at the foot of `deploy/sudoers.d/bayram-release`. Nothing creates them.
3. **Run `plan` first**, on a bundle built from a commit already deployed. It changes nothing
   and will expose every wrong path in one pass.
4. **Decide the off-box backup.** The timer fixes "no backup exists". A dump on the same disk
   as the database is not protection against losing that disk, and this host has one disk.

   **This item split in two on 2026-09-19. The mechanism has landed; the destination has not.**

   **The mechanism — done.** `deploy/install-bayram-backup.sh` now carries a destination-agnostic
   dispatcher driven by one switch, `BAYRAM_BACKUP_OFFBOX_MODE`, with three transports plus
   empty: `s3` (an endpoint URL and a bucket path through `rclone` or `awscli`, so R2, B2,
   Wasabi, MinIO and AWS are the same three lines with a different URL), `rsync`
   (rsync-over-ssh, `StrictHostKeyChecking` left **on** and the host key required to be pinned
   first), and `command` (the old `/etc/bayram/backup-offsite.hook` contract, preserved — an
   existing hook is picked up automatically as `MODE=command`). Every upload is **read back
   before the run is called a success**: `HeadObject ContentLength` for s3, an end-to-end
   `rsync -n -c` checksum pass for rsync. Credentials are passed in the environment and never in
   `argv`, because `/proc/<pid>/cmdline` is world-readable. Every off-box command is wrapped in
   `timeout` (default 900 s), because the push holds the flock inside a unit with
   `TimeoutStartSec=3600` and an unbounded hang would eat the next night's run too.

   **Unset is a true no-op, on purpose.** With no `MODE`, the off-box block is one honest log
   line, `"offbox": "not-configured"` in the sentinel, and `return 0` — no stat, no network call,
   no non-zero exit, no `OnFailure`, and `bayram-backup check` **stays green**. An unconfigured
   copy is the current deliberate state, not a fault. `bayram-backup check-offbox` is the opt-in
   assertion: it exits 4 only when a destination **is** configured and the last copy did not
   report `ok`.

   **The destination — still an owner decision, and it is the same three options as before.**
   **A** pull from the workstation (which also needs a call on a narrow sudoers verb versus a
   group-readable dump mode); **B** push to object storage (which puts a long-lived write
   credential on the host that terminates payment callbacks — scope it to one write-only
   prefix); **C** provider snapshots, which nobody can evaluate because **no one has recorded
   who the provider is**. When the call is made, `/etc/bayram/backup-offbox.env` is where it gets
   written down — `root:root` `0600`, deliberately **not** one of the three `/etc/bayram` env
   files, which are `0640 root:hbd` and therefore readable by the account that serves customers
   and terminates payment callbacks. The script refuses to read it at any other owner or mode.

   Two practical notes for whoever picks B. **No off-box client is installed on the host** —
   `rclone`, `aws`, `restic` and `b2` are all absent (verified 2026-09-19); only
   `/usr/bin/rsync` 3.2.7 and `/usr/bin/scp` exist, so `apt-get install rclone` is a second,
   separate human command. The installer refuses at preflight if `MODE=s3` is configured with
   neither client present, rather than failing at 02:30. And **`MemoryDenyWriteExecute=yes` is
   left on the unit** — fine for a Go binary such as `rclone`, but an interpreted or JIT-ish
   client may need it relaxed and the failure looks like nothing else.

   **After configuring a destination, re-run the installer.** That is what writes the socket
   drop-in `10-offbox.conf`: the unit ships with `RestrictAddressFamilies=AF_UNIX`, and the
   drop-in is what widens it. The main unit stays byte-identical so `cmp -s` idempotency still
   reports "unchanged", the drop-in is removed again if the destination is blanked, and the
   installer then asserts via `systemctl show` that the merged unit really can open a socket.

## 4. The health signal — smaller than it looked

This page previously said `/healthz` "returns a constant `ok` to any unauthenticated caller",
and used that to argue automatic rollback has no signal to read. **The first half was wrong**,
and it was wrong because nobody had opened the file.

What is actually there, in both `admin` and `payme`:

* **`/healthz` is liveness** — a bare 200 with an **empty body**, touching neither Postgres nor
  Redis. That is the correct design and the docstring says why: an orchestrator restarts a
  container whose liveness probe fails, so a liveness probe that depends on the database turns
  a database blip into a restart loop across every replica at once.
* **`/readyz` is readiness** — a constant word to an unauthenticated caller, *and it pings
  nothing*, so it cannot be used to load the database either. The detail
  (`database`, `redis`, `configVersion`) needs a session or an `X-Probe-Token` compared under
  `compare_digest`. That is §6.3, deliberate: an unauthenticated detailed body is fleet
  telemetry for anyone who can reach the port.

Verified live on 2026-09-16 against the running admin API: `/healthz` → 200, 0 bytes;
`/readyz` → `{"status":"ok"}`.

So the work was not to build a health check. It was to **use** the one that exists:

* `bayram-release` made **no HTTP request at all**. Its `verify` imported modules and asserted
  `alembic current` — both of which describe the filesystem, not the four processes now
  running. A unit can be `active` while uvicorn is still starting, while a router failed to
  mount, or while a lazily-read dependency is unreachable. `do_readiness_probe` now does one
  loopback GET per HTTP process (`:8080`, `:8091`) after the restart.
* It is **not fatal by default**, deliberately: it runs after the fleet is already restarted,
  and turning a slow-starting uvicorn into a failed release would make this less reliable than
  what it replaces. A no-answer is reported loudly; an explicit `"status":"degraded"` **is**
  fatal, because that is the process itself saying a backing service is down.
* **`BAYRAM_ADMIN_PROBE_TOKEN` is empty** (`settings.py:453` defaults to `""`,
  `.env.admin.example:343` ships blank). Empty authorises nobody, so no monitor can read
  detailed readiness today — the capability exists and is switched off. Until it is set, the
  probe proves reachability only, which is still more than `is-active` can tell you.

  > **STILL EMPTY ON THE HOST, 2026-09-19 — but the reason it could not be fixed has changed,
  > and that half IS fixed.** `bayram-release` read the token out of `$ENVFILE` =
  > `/etc/bayram/bayram.env`. **That file does not declare `BAYRAM_ADMIN_PROBE_TOKEN` and never
  > did** — the variable lives in `/etc/bayram/bayram-admin.env`, which is what systemd actually
  > hands the unit (`systemctl show bayram-admin -p EnvironmentFiles`). So the token was a knob
  > nobody could turn on from outside the script: an operator could write it into the admin env
  > file correctly and `verify` would still print "no token set" forever. A second bug compounded
  > it — the one token it did find was sent to **both** endpoints, including payme on 8091, which
  > compares against `payme_probe_token` in a different file entirely, so the payme probe could
  > never unlock detail at all.
  >
  > Both are fixed. `READY_PROBES` now carries four fields per entry — unit, URL, **env file**,
  > **token variable** — so each process is probed with its own token read from its own file,
  > inside a per-entry subshell (which is what stops the bot token and four vendor credentials
  > leaking into the rest of the script). `deploy/set-probe-tokens.sh` is the operator step that
  > closes the item.
  >
  > **It is only half-closable, and the honest framing matters.** Setting the tokens buys almost
  > nothing on its own, because **nothing polls `/readyz`**: `systemctl list-timers --all` has no
  > `bayram` timer and `/etc/cron.d` holds only `e2scrub_all` and `sysstat`. After this work the
  > sole consumer is `bayram-release verify`, **once per release**. Decide whether the deliverable
  > is "token set" or "something watches it"; the latter is separate work. And exposing `/readyz`
  > to an off-box monitor is its own decision, not a side effect of setting a token — both
  > endpoints bind `127.0.0.1` and all public traffic goes through the Cloudflare Tunnel, so
  > routing `/readyz` through it needs its own exposure argument. The payme body leaks
  > `isSandbox`, i.e. whether the rail is pointed at real money.
  >
  > **`/opt/bayram/sbin/bayram-release` is installed BY HAND and is not shipped by the wheel
  > bundle** — the host copy is a standalone 67 180-byte file dated Sep 17. Editing it in this
  > repository changes nothing on `abdu-test` until it is copied up. A release alone will not
  > carry it.

One bug worth recording, found by running the probe against a dead port rather than by reading
it: **curl reports `000` when it never received an HTTP response at all** — connection refused,
or the timeout hit. The first version treated only an empty string as "no answer", so a refused
connection fell through to the generic branch and told the operator the process "answered with
HTTP 000", which is exactly backwards.

## 4.1 The CD open items, as they actually stand on 2026-09-19

Five items were open when this page was written. **None of them is closed on the host**, but four
of the five have moved from "nothing exists" to "a repo script exists and a human has to run it",
which is a different kind of open. Nothing below is done by pushing a commit.

| Item | Repo side | Host side |
| --- | --- | --- |
| **No scheduled backup** | `deploy/install-bayram-backup.sh` exists and now installs the off-box copy too | **STILL OPEN.** Never run. No `bayram-backup` unit, nothing in `list-timers`, `/opt/bayram/sbin` holds only `bayram-release`. Verified read-only 2026-09-19 |
| **No off-box copy** | **Mechanism DONE** — three transports, verified after upload, inert and non-failing when unset | **STILL OPEN, and it is an owner decision, not a coding task.** The destination is unchosen; `/etc/bayram/backup-offbox.env` is where it gets written down |
| **Probe token unset** | **Two real bugs fixed** in `bayram-release` (wrong env file; one token sent to both endpoints); `deploy/set-probe-tokens.sh` generates, installs, restarts and proves | **STILL OPEN.** Both tokens empty. And half-closable at best: nothing polls `/readyz`, so setting them changes `bayram-release verify` output and nothing else |
| **`gate` not required** | **No defect found** — the suspected skipped-dependency bug is not present; two non-verdict-changing hardening edits landed | **STILL OPEN.** `main` has no protection and no rulesets. One `gh api` call, above |
| **Old deploy scripts not retired** | `deploy/sudoers.d/bayram-deploy` rewritten post-cutover; `deploy/prune-stale-sudo-grants.sh` written | **STILL OPEN, and blocked on an owner decision.** `/etc/sudoers.d/90-developer-nopasswd` grants `developer` passwordless root; until whoever created it on 2026-09-17 says what it was for, every per-grant removal is cosmetic. The script has **never been executed end to end** — run `plan` and read the diff |

Two things that are **not** on that list because they were never on it, and both are live:

* **`git remote -v` shows `origin` as `https://orihero:ghp_…@github.com/orihero/hbd-bot.git`** —
  a plaintext classic PAT in `.git/config`, on a public repository. `ci.yml:9-12` already names
  this hazard and sets `persist-credentials: false` because of it. The token should be rotated
  and the remote rewritten credential-free; **anything that prints `git remote -v` into a log or
  a shared transcript leaks it.**
* **`sshd` has `PasswordAuthentication yes`** alongside a password-bearing `developer` account
  and `NOPASSWD: ALL`. One guessed password is unattended root on the host that terminates
  payment callbacks. The fix is `PasswordAuthentication no` in `/etc/ssh/sshd_config.d/` — keys
  are already in `/home/developer/.ssh/authorized_keys` — but it belongs to whoever owns ssh
  policy and must not ride along in a sudoers change.

## 5. What this page does not cover

The release runbook itself is [`04-release.md`](04-release.md), whose STATUS header records
that its §2, §3 and §5 cannot be run on this host. Nothing here supersedes it; this page is
about the machinery around it. When `bayram-release` is written, §0.3's "four files in
`deploy/` have drifted" should be resolved in the same change.
