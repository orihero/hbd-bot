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
| `node` | `npm ci`, then `typecheck` / `lint` / `test:unit` / `test:e2e:strict` as four separate steps | yes |
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
pending). The python job's `timeout-minutes: 45` is set against that 9m31s with generous room
for a slower hosted runner.

### Before marking `gate` required

Land the workflow with **no branch protection**, let it run on a branch and on `main`, and
confirm the hosted-runner numbers match the local ones above. Only then make it required.

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

## 3. What this page does not cover

The release runbook itself is [`04-release.md`](04-release.md), whose STATUS header records
that its §2, §3 and §5 cannot be run on this host. Nothing here supersedes it; this page is
about the machinery around it. When `bayram-release` is written, §0.3's "four files in
`deploy/` have drifted" should be resolved in the same change.
