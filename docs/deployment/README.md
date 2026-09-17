# Deployment documentation

**Start here:** deploying a change today → [04-release.md](04-release.md); standing up a new
host → [03-provisioning.md](03-provisioning.md); something is broken right now →
[06-troubleshooting.md](06-troubleshooting.md); moving the host from `hbd` to `bayram` →
[10-rename-cutover.md](10-rename-cutover.md); what the machine actually is →
[00-host-inventory.md](00-host-inventory.md), which is no longer empty and **wins** wherever it
disagrees with the rest.

> **Before you run a migration on this host, read 00 row 50.** `alembic upgrade head` cannot
> succeed as of 2026-09-10: role `hbd` has no rights on schema `public`, the error reads like a
> corrupt database rather than a missing `GRANT`, and it is invisible from the application side.
> The fix is one statement. This is the only thing in this tree that will stop a release today.

---

## STATUS — read this before you trust a single line below, updated 2026-09-11

**The two halves are gone. As of 2026-09-11 every page in this directory has been held against
the machine**, and each marks every claim with its date and its method. That is a change of kind,
not of degree: until this date the honest warning at the top of this file was "claims about the
host are not made" on seven of the eleven pages, and a reader had to know which seven.

What replaces it is a weaker but real distinction — **how much of a page is host-checked, and
where its walls are.** Every page now carries `[HOST ...]`, `[TREE ...]` and `[UNPROVEN]` marks;
the count below is the marks each one carries, so you can see at a glance whether a page rests on
the machine or on the repository:

| Page | `[HOST]` | `[TREE]` | `[UNPROVEN]` |
| --- | --- | --- | --- |
| [00-host-inventory](00-host-inventory.md) | the whole page | — | 4 cells |
| [01-architecture](01-architecture.md) | 49 | 9 | 14 |
| [02-configuration](02-configuration.md) | 41 | 8 | 11 |
| [03-provisioning](03-provisioning.md) | 68 | 9 | 18 |
| [04-release](04-release.md) | 54 | 11 | 4 |
| [05-operations](05-operations.md) | 29 | — | 8 |
| [06-troubleshooting](06-troubleshooting.md) | 46 | — | 14 |
| [07-security](07-security.md) | 37 | — | 11 |
| [08-payme](08-payme.md) | transcripts throughout | — | — |
| [09-payme-go-live](09-payme-go-live.md) | the gate board's evidence column | — | named per gate |
| [10-rename-cutover](10-rename-cutover.md) | 38 | 21 | 8 |

**`[UNPROVEN]` is not a to-do list.** Most of those marks are one wall: `/etc/hbd` is `0750
root:hbd`, the `hbd` group is empty, `sudo -n` refuses, and `psql` wants a password the deploy
account does not have. Those questions are not open for lack of looking, and each now names its
blocker so nobody re-opens them from memory.

**Four documents are the ones to trust first**, because they were written against the machine
rather than merely checked against it:

- [00-host-inventory.md](00-host-inventory.md) — read off the machine on 2026-09-09/10 and
  **re-checked row by row on 2026-09-11**. Where a filled row disagrees with 01–07, with 10, or
  with `deploy/`, **the row is right**.
- [08-payme.md](08-payme.md) — the gateway as deployed, including transcripts. Updated
  2026-09-10 for the first settlement.
- [09-payme-go-live.md](09-payme-go-live.md) — the go-live gate board. Updated 2026-09-10: Gate C
  closed, four of Gate B's six facts closed.
- [10-rename-cutover.md](10-rename-cutover.md) — **new, written and host-checked 2026-09-11**,
  1 187 lines, for the `hbd` → `bayram` cutover. Its subject is not hypothetical: the cutover was
  **attempted on the host on 2026-09-10 at 14:05 and 14:06 and failed**, and the debris is still
  on the disk (00 rows 49 and 50).

**Two things the 2026-09-11 pass changed in the checked half, and both change what somebody
would do next:**

1. **There is a blocking defect on the host that no document recorded until now.** Role `hbd`
   has no rights on schema `public`, so `alembic upgrade head` cannot run: the 2026-09-10
   rebuild re-granted the *application* role and never the *migration* role. Revision `0025` is
   on disk and unapplied, and the rename cutover dies at that step. It is invisible from the
   application side and the error text reads like a corrupt database. 00 finding 9 and row 50.
2. **"Ten cells behind a permission wall" was wrong about six of them.** They were answered on
   2026-09-10/11 with no new privilege, out of a world-readable `postgresql.conf`, the
   `adm`-readable Postgres server log, the world-readable `pg_dump` files in `/var/backups/hbd`,
   and the worker's own journal. **Four cells remain empty (00 rows 23, 24, 30, 35), and only
   row 30 has no route at all.** A blocker that is not real teaches operators to stop looking,
   which is why 00 now names the route beside every wall.

**01–07 were derived from this repository alone until 2026-09-11, and were reconciled against
the host on that date.** The sentence that stood here — "claims about the host are not made" —
is why the reconciliation was worth doing, and it is worth keeping a record of what it was like
to work from pages that honoured it: every procedure needing a host fact was written as a
placeholder to fill in or a question to answer on the box, and an operator had to carry the list
of which pages those were. What that history means in practice now:

- **Claims about the code are checkable, and always were.** Every one carries a `file.py:line`
  from this working tree. Doubt a sentence, open the file.
- **Claims about the host are now made, and every one is marked.** A sentence without a
  `[HOST ...]` mark in 01–07 is a claim about the repository, not about `aizu` — the absence of
  the mark is the signal, so read for it rather than assuming the page was updated throughout.
- **Where a page and 00 disagree, 00 wins.** That rule did not change and matters more now that
  the other pages also speak about the machine: two pages checking the same fact on the same day
  can still diverge, and one of them is the inventory.
- **`deploy/` is a proposal, not a record.** `deploy/systemd/*.service` and the install
  narrative preserved beside them as `deploy/first-install-proposal.md` were authored in this
  repository on the same day, by an assistant that also had no host access. They describe a
  coherent `/srv/bayram` + systemd shape that somebody could deploy. **`/srv` on the host is
  empty** (verified 2026-09-10): there is no checkout, the install is a wheel in
  `/opt/hbd/venv`, and the running units use `EnvironmentFile=` rather than the `*_ENV_FILE`
  indirection those files argue for. Only `deploy/systemd/bayram-payme.service` was ever
  corrected against reality, and the rename has since carried even that one back out of sync
  (`/opt/bayram/venv`, `User=bayram`). The other three are left disagreeing on purpose — see
  00's "Which document wins" — but do not read any of them as a record.
- **Two naming systems are live at once, and neither is wrong.** The repository has been
  renamed `hbd` → `bayram`; the host has not. Host paths, unit names and `HBD_*` variables in
  00, 08, 09 and 10 are quoted from the machine and **must not be swept by a rename pass**. That
  cutover is its own operation, with its own hazards: [09-payme-go-live.md](09-payme-go-live.md)
  §2 for why no release may straddle it, and [10-rename-cutover.md](10-rename-cutover.md) for the
  operation itself. **As of 2026-09-10 the host is pre-rename because the cutover FAILED, not
  because nobody has run it** — and it left `/etc/bayram` and `/opt/bayram` on the disk, so
  "no `bayram` path exists on the host" is a sentence to stop repeating (00 rows 46 and 49).

Outside those four, treat this directory as *the shape we propose and the reasons for each
line*, never as a description of a running system.

---

## The documents

| # | Document | What it is for |
| - | -------- | -------------- |
| 00 | [The aizu host — inventory](00-host-inventory.md) | **Read off the machine, 2026-09-10, re-checked 2026-09-11.** Fifty-one host facts, each with the command that answers it and the date it was checked; **ten** findings that outrank the table (no public IP, a Cloudflare tunnel, the `http://` scheme trap, a wheel deploy, `EnvironmentFile=` not `*_ENV_FILE`, a `NOPASSWD` grant that is really root-on-demand, **the migration role's missing schema GRANT**, and the readable evidence routes nobody was using); the routing narrative that replaced the old "Caddy terminates TLS" row; and one read-only SSH block that re-answers most of it in a single paste. ~~Ten cells are still empty, all behind the same permission wall.~~ **Four are empty (rows 23, 24, 30, 35); the other six were answered on 2026-09-10/11 with no new privilege, mostly by reading world-readable or `adm`-readable files rather than by asking `psql`. Row 30 is the only cell with no route: `/var/lib/hbd` is `hbd:hbd` `0750` and `sudo -n du` answers "a password is required".** An empty cell still means nobody has looked. **This page wins.** |
| 01 | [Deployed architecture](01-architecture.md) | **Host-checked 2026-09-11 (49 marks).** The **four** long-running processes and the by-hand commands, what talks to what, why only the worker runs the clocks, and why the admin API is a separate process that must not hold a vendor credential. |
| 02 | [Configuration reference](02-configuration.md) | **Host-checked 2026-09-11 (41 marks).** Every variable production actually requires, which of the **three** settings classes owns it, which file each of the four commands reads, the **seven** refusals that key off `BAYRAM_ENVIRONMENT`, and the defects in `.env.admin.example` to fix before copying it. |
| 03 | [Provisioning a host from bare metal](03-provisioning.md) | **Host-audited 2026-09-11 (68 marks).** Fourteen steps from a fresh OS to a booting fleet — packages, roles, dotenv modes, schema, console build, first OWNER, supervision, TLS — written as the audit checklist to compare `aizu` against, **not** a runbook to replay on it. |
| 04 | [Releasing a change](04-release.md) | **Host-checked 2026-09-11 (54 marks), and it no longer describes the release this host actually gets — that is the wheel procedure in 08 §11.** The routine deploy to an already-provisioned host: three pre-flight gates, pull, dependency sync, migrations, the non-optional console rebuild, restart order, verification, and what can and cannot be rolled back. |
| 05 | [Day-2 operations](05-operations.md) | **Host-checked 2026-09-11 (29 marks).** Operator accounts and the bootstrap CLI, the credits and identity tools, the **five** clocks, verifying the audit chain, the log events worth an alert rule, and backup/restore. |
| 06 | [Troubleshooting](06-troubleshooting.md) | **Host-checked 2026-09-11 (46 marks), and §17a is a defect that is happening right now**: 487 `TelegramConflictError` lines, every day since the units were enabled, because something off this host holds the same bot token — it must be closed before the payment rail is switched on. Twenty-one symptoms, each with what an operator sees, the code that produces it, one command that settles the question, and the fix. Biased towards the failures that look healthy. |
| 07 | [Security controls and their deployment dependencies](07-security.md) | **Host-checked 2026-09-11 (37 marks).** Seven controls — vendor-credential separation, CSP and the style nonce, `__Host-` cookies, the exact origin check, trusted proxies, the audit HMAC chain and its REVOKE, loopback binding — each as: what it protects, what the deployment must do, how to prove it is on, how it fails. Ends with the ones that degrade silently. |
| 08 | [The Payme gateway](08-payme.md) | **Deployed and re-checked against the host, 2026-09-10.** The fourth process: its real systemd unit and env file as read off `aizu`, the connection arithmetic and the `hbd_app` role check, **the public path — Cloudflare's edge terminates TLS, a tunnel speaks plain HTTP to Caddy on loopback — and the `308` trap that scheme-less Caddy site block causes**, the cabinet settings a human types, and the certification, manual-refund, key-rotation and reconciliation runbooks, plus the wheel release runbook (§11). |
| 09 | [Payme go-live](09-payme-go-live.md) | **Checked against the host, 2026-09-10.** The gate board for taking real money: six facts only Payme can supply — **four of them closed on 2026-09-10**, including the endpoint registered in the cabinet and the `order_id` requisite; **the settlement rehearsal, first run on this host on 2026-09-10 at 13:30 +05 — 4/4 scenarios, corroborated in the gateway and worker journals, and owed again at the Gate A rename** (the "nobody has ever run it" this row said until 2026-09-11 stopped being true at 13:30 that afternoon); the Cloudflare settings nobody has applied; the `hbd` → `bayram` rename cutover that no release may straddle; the owner's 2026-09-10 decision to leave the stub paywall as it is; the switch-on and rollback sequences; and (§11) **the admin console as an operator surface** — which two of the CLI's five commands it now covers, why `settle` and `reconcile` deliberately stay in the terminal, and the fact that the pause switch now has two writers against one key. |
| 10 | [The `hbd` → `bayram` rename cutover](10-rename-cutover.md) | **Written and host-checked 2026-09-11 — 1 187 lines, ten sections, 38 `[HOST]` marks.** The operation Gate A names, as its own page because it is all-or-nothing and has its own rollback: the package, the four units, the three dotenv files, the venv path, the env-var prefix and the sudoers rule that all have to move together, and the two things that move silently and are both about money — the Redis pause key and the idempotency prefix (09 §2). **It starts from a failure, not a blank page: the cutover was attempted on the host on 2026-09-10 at 14:05 and 14:06, ran as root through the `NOPASSWD` deploy path, and failed both times — the second at its migration step** because the migration role has no rights on schema `public`, **the first somewhere before step 3 that nobody has characterised** (00 rows 49 and 50). Fixing the GRANT addresses the second failure only. The debris it left — `/etc/bayram`, `/opt/bayram`, a `bayram` wheel, a post-rename `migrations/` tree inside `/opt/hbd` — is still on the disk and is **not** a deployment. |

| 11 | [CI, and why CD stops at the door](11-ci-cd.md) | **Written 2026-09-16, and the workflow landed with it.** The repository had no CI of any kind, while `TEST_INFRA.md` §7.3 and `TEST_READY.md` §2 both prescribed one. `.github/workflows/ci.yml` runs the Python and console gates on every push and PR, plus a migration tripwire that refuses destructive DDL — because every script in `deploy/` migrates BEFORE installing the wheel and each says that is safe only for additive revisions. Records the five things that would have made it red on day one (`cov-admin: cov` running the suite twice; `make install` ignoring `uv.lock`; a uv pin that must read `revision = 3`; ffmpeg needed by an *unmarked* test; and `npm test` fetching its own runner via `npx tsx`, now a pinned devDependency). **And it says why continuous *deployment* stopped at the door**: no inbound path to the host, a migration step that sources every production secret, ~831 MiB of free memory, no scheduled backup and a `/healthz` that returns a constant `ok` — so there is nothing to roll back to and nothing to notice. Three architectures were judged; operator-triggered won 8/8/8. The real fix for "why do I run these scripts every time" is one versioned `bayram-release` replacing three per-feature scripts that are already the same seven beats. |

The actual deployment artefacts — the unit files — live in
[`deploy/systemd/`](../../deploy/systemd/), not here. This tree is prose about them.

---

## Open questions

> **Most of these are now answered — 2026-09-10, and six more on 2026-09-11.** They are kept
> rather than deleted because the reasoning under each is still the reason the question matters,
> and because an answered question with its evidence beside it is what stops the question being
> re-asked from memory. **Read the verdict line under each heading before running its command** —
> several of the commands printed below are the ones that *could not* answer their question, kept
> for the same reason.
>
> **And read this before reaching for `sudo`: four of these questions were answered on 2026-09-11
> out of files that were readable all along** — `/etc/postgresql/16/main/postgresql.conf` (`0644`),
> `/var/log/postgresql/postgresql-16-main.log` (`0640 postgres:adm`, and `developer` is in `adm`),
> the `pg_dump` files in `/var/backups/hbd` (`0644 root:root`), and `journalctl -u hbd-worker`.
> The answers live in [00-host-inventory.md](00-host-inventory.md), by row number.
>
> | | Question | Verdict, 2026-09-11 unless dated otherwise |
> | - | -------- | ------------------- |
> | 1 | Backups | **ANSWERED — nothing is scheduled.** ~~Seven~~ **nine** hand-taken dumps (two more from the failed cutover of 2026-09-10), no timer, no cron, no off-box copy; the HMAC key is in no dump and now exists in **two** files on one disk. Rows 33–35, 49. |
> | 2 | `ENVIRONMENT` is exactly `prod`? | **ANSWERED for the bot and the panel: yes.** Read off the boot lines, no privilege needed. **The gateway answers `dev`** — a third process, a third file, a third answer. Row 20, `08-payme.md` §2.1. |
> | 3 | `CREDITS_ENFORCED` true? | **ANSWERED — false**, and it is a decision with a date, not a defect: the paywall is deliberately live on the stub rail. `09-payme-go-live.md` §6. |
> | 4 | Alembic revision | **ANSWERED — `0024`, re-verified 2026-09-11 without `psql`.** Read out of `alembic_version` inside the cutover's own pre-flight `pg_dump` at `/var/backups/hbd/pre-cutover-20260910-140653.sql.gz`, which is `0644 root:root` and needs no privilege. ~~NOT re-verified since 2026-09-09~~ superseded. **The number is the least interesting half: revision `0025` is on disk, unapplied, and currently *unappliable* — the attempt failed at 14:07:26 on 2026-09-10 because the migration role has no rights on schema `public`.** Rows 5, 15, 50. |
> | 5 | Data-root agreement | **ANSWERED — they agree**, at `/var/lib/hbd/var`, because all four units share `WorkingDirectory=`. Rows 2 and 30. Size still unknown. |
> | 6 | Processes, topology, what is in front | **ANSWERED, and the answer corrected this file.** Four systemd units on one box; **Caddy does not terminate public TLS** — Cloudflare's edge does, over a tunnel, to plain HTTP on loopback. Rows 17, 39–43. |
> | 7 | Worker replicas | **ANSWERED — one.** Row 9. |
> | 8 | Two-role split and 0007's `REVOKE` | **ANSWERED 2026-09-11, and the answer is worse than "still open".** Both roles exist (`hbd`, `hbd_app`) — but **0007's `REVOKE` is NOT in force and there are no default privileges at all.** All 31 objects in `public` are owned by `hbd_app`, `admin_audit_log` included; the only privilege statements in the schema are `REVOKE USAGE ON SCHEMA public FROM PUBLIC` and `GRANT ALL ON SCHEMA public TO hbd_app`; zero `ALTER DEFAULT PRIVILEGES`, zero table-level grants. So `GET /api/audit/verify` should report `chainProtection: "hmac-only"`. **Related and worse: role `hbd` has no rights on schema `public` at all, which is why migrations fail (row 50).** Read out of the world-readable dump, not out of `psql`. Rows 12–14. |
> | 9 | Redis persistence, Postgres location | **ANSWERED — Redis 7.0.15 with `appendonly no`, RDB only; Postgres 16.15 on the same box, loopback.** Rows 10 and 16. ~~`max_connections` still unread.~~ **`max_connections = 100`, read 2026-09-11 from `/etc/postgresql/16/main/postgresql.conf:65`, which is world-readable, with an empty `conf.d`. So the 30+30+10+5=75 pool arithmetic of `08-payme.md` §3.1 has the margin it assumes. Caveat: that is the configured value; an `ALTER SYSTEM` would live in `postgresql.auto.conf` inside the `0700` data directory.** Row 11. |
> | 10 | Public origin and proxy hops | **HALF.** The origin matches (`https://admin.bayrambot.uz`, row 22). The hop count is **not** read and is probably now wrong: admin traffic is two proxies deep since the tunnel. **There is a route that needs no `sudo`: `GET /api/config` returns `admin_trusted_proxy_hops` and `admin_trusted_proxy_cidrs` verbatim, so one authenticated OWNER session settles it — and settles question 16's sibling, row 24, at the same time.** Row 23. |
> | 11 | Which dotenv each process reads | **ANSWERED — from the unit files, and ONLY from the unit files.** `EnvironmentFile=/etc/hbd/hbd.env` (bot, worker), `/etc/hbd/hbd-admin.env` (panel), `Environment=HBD_PAYME_ENV_FILE=/etc/hbd/payme.env` (gateway). **The advice printed below this table — "read `env_file` off the boot lines" — is wrong for three of the four processes and is corrected there.** Because `EnvironmentFile=` means pydantic-settings never opens a file, the bot prints `"env_file": ".env"` and the panel `".env.admin"`: the relative defaults, not the real paths. Only the gateway, which uses the `*_ENV_FILE` indirection, names a real path. Rows 18–20. |
> | 12 | Console bundle current, built where | **ANSWERED — present and correct, and there is no Node on the box.** The bundle travels inside the wheel. Rows 28–29. |
> | 13 | ffmpeg encoders | **ANSWERED — both `libopus` and `libmp3lame`.** Row 26. |
> | 14 | Wheel or checkout, migrations on disk | **ANSWERED — a wheel, and `migrations/` is on disk separately.** Rows 3, 5, 45. |
> | 15 | Retention cron, `var/workspace` growth | **ANSWERED for the cron half, 2026-09-11 — 137 sweeps, the earliest 2026-09-05T18:17 +05 (when the units were installed), every one of them `is_batch_full: false` with `storage_keys_returned: 0` and `storage_keys_deleted: 0`.** No bytes leaking, and nothing has ever been deleted from *storage* — though the separate `hbd.db.purge` event has deleted `admin_sessions` rows (2, 2 and 3), so the database half demonstrably works. The `purge_runs` caveat turned out to be irrelevant: the **worker's journal** is a durable record that predates the 2026-09-10 wipe and reaches the 2026-08-07 boot. **`var/workspace` growth is still unknown and belongs with row 30, the one cell with no route past the wall.** Rows 32, 36. |
> | 16 | Source maps reachable | **ANSWERED — YES, the map is public.** `curl -sS -D- -o /dev/null https://admin.bayrambot.uz/assets/index-D9iMG-RF.js.map` returns HTTP 200 and **4,242,767 bytes** to any caller, unauthenticated, through Cloudflare and Caddy, with `cache-control: public, max-age=31536000, immutable`. Re-run 2026-09-11. Nothing in the path authenticates `/assets`, exactly as `src/bayram/admin/app.py` predicts, and the tunnel added no filter. **This should stop being an open question and become a dated decision in [07-security.md](07-security.md): it hands anyone the panel's pre-minification source — routes, permission checks, every API shape — for a panel whose compensating control is that it is hard to reach, and the year-long immutable header means it outlives any fix in caches.** Row 29. |

Every question below that is still marked open needs somebody to look at `aizu`. They are
ordered by what would hurt most if the answer is wrong, not by how easily they are answered.
Each command is read-only. `00-host-inventory.md` carries the same questions as a table with
the answers in it, along with an SSH block that runs most of them at once.

> **The commands below are kept as written, including the ones that cannot answer their own
> question.** Each of the prose blocks still explains why the question matters, which is why they
> are here; but **four of them reach for `sudo -u postgres psql`, which needs a password this
> account does not have, and the answer was available without it.** Where the verdict table above
> says ANSWERED, follow the route in the verdict rather than the code block under the heading. The
> four routes, all of them read-only and none of them privileged, are named at the top of the
> verdict table and in 00's STATUS block. **The lesson is worth more than the four answers: this
> tree's habit of naming a blocker precisely is what exposed that the blocker had never been
> tested.**

> **One question below gives advice that is actively wrong, and it is corrected in place:**
> question 11's *"or read `env_file` off the boot lines"*. See its block.

**1. Is anything backing up Postgres, `var/archive`, or `BAYRAM_ADMIN_AUDIT_HMAC_KEY`?**
Nothing in this repository backs anything up — `grep -rin backup README.md Makefile deploy/`
returns nothing operational. `var/archive` holds every delivered song *and* every customer
avatar (`src/bayram/storage.py:73-84`, `src/bayram/user_profiles.py:199-200`). The HMAC key has no
key id (`src/bayram/db/admin/audit.py:10-12`), so if it exists only in the admin's dotenv file,
losing that file makes the entire audit log permanently unverifiable.
```bash
ssh aizu 'crontab -l 2>/dev/null; sudo ls -la /etc/cron.d 2>/dev/null; systemctl list-timers --all 2>/dev/null | grep -Ei "dump|backup|bayram"'
```

**2. Is `BAYRAM_ENVIRONMENT` the exact string `prod` in *both* dotenv files?**
`Settings.environment` is an unvalidated `str` (`src/bayram/config.py:170`) compared with `==`;
the two settings classes own it independently. `production`, `Prod` or a stray space silently
disarms the fake-provider refusal (`src/bayram/runtime/providers.py:104`) and the
in-process-submitter refusal (`src/bayram/runtime/submitter.py:100`) with no error anywhere.
```bash
ssh aizu 'sudo grep -n "^BAYRAM_ENVIRONMENT=" <bot env> <admin env>'
```

**3. Is `BAYRAM_CREDITS_ENFORCED` true, with a price on screen?**
`src/bayram/main.py:177-189` logs a warning and *never refuses* when the checkout is wired and
the credit meter is dark. The customer is shown a price and charged; the worker then covers
the shortfall with an `UNENFORCED_RENDER` grant and renders anyway. Silent and expensive in
exactly one direction.
```bash
ssh aizu 'sudo grep -n "^BAYRAM_CREDITS_ENFORCED=" <bot env>'   # then grep the bot log for "the credit meter is dark"
```

**4. What alembic revision is the live database actually at?**
The repo head is `0024`
(`migrations/versions/20260909_1000_0024_add_broadcast_tables.py`), and the host had all
twenty-four revision files on disk on 2026-09-10. `make migrate` is
a manual step in every documented procedure, so a deploy that pulled code and restarted
services leaves the schema behind. The `-d hbd` is load-bearing: without it `psql` reports
`relation "alembic_version" does not exist`, which reads as "no migration ever ran".
```bash
ssh aizu 'sudo -u postgres psql -d hbd -Atc "select version_num from alembic_version"'   # needs a password
# The route that needed none, and the one that answered it on 2026-09-11:
ssh aizu "zcat /var/backups/hbd/pre-cutover-20260910-140653.sql.gz | grep -A3 'COPY public.alembic_version'"
```

**5. Do the bot's working directory and the admin's data root resolve to the same absolute path?**
The bot and worker derive their data root from `Path.cwd()/"var"` with no environment
override (`src/bayram/runtime/container.py:286`); the admin defaults `admin_data_root` to a
*relative* `var` (`src/bayram/admin/settings.py:423`). If the two processes have different
working directories, every media reveal in the panel 404s while the database row insists the
file is there. Agreement is a deployment fact, not a code guarantee.
```bash
ssh aizu 'for p in $(pgrep -f "bayram.main|arq bayram.worker|uvicorn"); do ls -l /proc/$p/cwd; done; sudo grep -n "^BAYRAM_ADMIN_DATA_ROOT=" <admin env>'
```

**6. Are all three processes running, on one box or several, under what supervisor, and with what in front of the admin API?**
The repo assumes a shared Redis and a shared filesystem root but proves nothing about
topology. Whether the host uses systemd at all is unknown; `deploy/systemd/*.service` is a
same-day proposal. TLS termination is named only as a suggestion ("Caddy or nginx",
`deploy/first-install-proposal.md:56`), and nothing in the package binds a socket — the bind is on the
uvicorn command line. A serving panel does prove `BAYRAM_ADMIN_ENABLED=true`, since the lifespan
refuses without it (`src/bayram/admin/app.py:206-208`, default `false`).
```bash
ssh aizu 'systemctl list-units --type=service | grep -i bayram; docker ps; pgrep -af "bayram.main|arq bayram.worker|uvicorn"; ss -ltnp'
```

**7. How many worker replicas run?**
The music and TTS concurrency semaphores are per-process
(`src/bayram/runtime/container.py:332-333`), so any count above 1 silently multiplies the vendor
ceiling — and the spend.
```bash
ssh aizu 'pgrep -cf "arq bayram.worker"'
```

**8. Is the two-role split real: do `hbd` and `hbd_app` exist, did migration 0007's REVOKE land, and do default privileges cover the tables created since?**
`_install_two_role_controls` reads `BAYRAM_ADMIN_AUDIT_DSN` from `os.environ` only and skips
silently otherwise
(`migrations/versions/20260830_1000_0007_add_admin_audit_log.py:336-338`); no documented
workflow exports it, so the prediction from the code is that the REVOKE is **not** in force.
`docker/initdb/10-two-roles.sql` runs only on an empty local Docker volume and its own header
says production roles are made by hand — if its `ALTER DEFAULT PRIVILEGES` was missed, every
table from migrations 0014–0021 is invisible to the application role. The panel's own answer
is honest in both directions because it asks Postgres rather than trusting configuration.
```bash
ssh aizu 'sudo -u postgres psql -Atc "select rolname from pg_roles order by 1"; sudo -u postgres psql -d hbd -c "\dp admin_audit_log"'   # both need a password
# or, from the panel: GET /api/audit/verify → chainProtection ("hmac-only" means it is not in force)
# The two routes that answered it on 2026-09-11 with no privilege at all — the prediction from the
# code was right, the REVOKE is not in force:
ssh aizu "zcat /var/backups/hbd/pre-cutover-20260910-140653.sql.gz | grep -E '^(GRANT|REVOKE|ALTER DEFAULT PRIVILEGES|ALTER TABLE .* OWNER TO)' | sort | uniq -c"
ssh aizu "grep -E 'FATAL|DETAIL' /var/log/postgresql/postgresql-16-main.log | tail -20"   # 0640 postgres:adm
# Read the DETAIL line, never the FATAL line: over loopback with scram-sha-256 a role that does not
# exist produces the SAME "password authentication failed" as one that does. Only the DETAIL
# distinguishes them ('Role "…" does not exist.'). 00 row 12.
```

**9. Is production Redis persistent, and where does Postgres live?**
`--appendonly yes --save 60 1` and the `redis_data` volume are facts about the **local**
compose stack only (`docker-compose.yml:1-2` says local-only). A production Redis with
default or no persistence loses every in-flight wizard draft and every queued job on
restart. Separately, the SQLAlchemy pools are sized against an assumed stock
`max_connections` of 100 with a 10-connection margin (`src/bayram/db/engine.py:64-67`).
```bash
ssh aizu 'redis-cli INFO server | head -5; redis-cli CONFIG GET appendonly; redis-cli CONFIG GET save; redis-cli CONFIG GET dir; sudo -u postgres psql -Atc "show max_connections"'
# The last clause needs a password and never needed to: max_connections is in a world-readable file.
ssh aizu 'grep -nE "^[^#]*max_connections" /etc/postgresql/16/main/postgresql.conf; ls -A /etc/postgresql/16/main/conf.d/ | wc -l'
```

**10. Does `BAYRAM_ADMIN_PUBLIC_ORIGIN` match the origin browsers actually reach, and how many proxy hops sit in front?**
The origin is compared exactly (`src/bayram/admin/settings.py:578-588`): a loopback value
inherited from the example file boots, passes `/healthz`, serves a login page, then 403s
every mutation with `ORIGIN_REJECTED`. And with the shipped defaults for
`BAYRAM_ADMIN_TRUSTED_PROXY_HOPS` (0) and `_CIDRS` (empty)
(`src/bayram/admin/settings.py:216-217`), every audit row and every rate-limit key records the
proxy's address rather than the client's.
```bash
ssh aizu 'sudo grep -nE "^BAYRAM_ADMIN_(PUBLIC_ORIGIN|TRUSTED_PROXY|PROBE_TOKEN)" <admin env>'
```

**11. Which dotenv file is each live process actually reading?**
The defaults are `.env` and `.env.admin`; any path can be supplied via `BAYRAM_ENV_FILE` /
`BAYRAM_ADMIN_ENV_FILE` (`src/bayram/config.py:81-97`, `src/bayram/admin/settings.py:65-81`). The
proposal puts them at `/etc/bayram/bot.env` and `/etc/bayram/admin.env`. Every question above that
says "`<bot env>`" or "`<admin env>`" depends on this answer, and the boot log states it
directly.
```bash
ssh aizu 'for p in $(pgrep -f "bayram.main|arq bayram.worker|uvicorn"); do sudo tr "\0" "\n" < /proc/$p/environ | grep -E "^BAYRAM_(ADMIN_)?ENV_FILE="; done'
# DO NOT "read env_file off the boot lines". Corrected 2026-09-11: because the deployed units use
# EnvironmentFile= rather than the *_ENV_FILE indirection, pydantic-settings never opens a file and
# the boot line reports its RELATIVE DEFAULT. The bot prints "env_file": ".env" and the panel
# ".env.admin" — neither of which exists on disk. Following this advice sends you looking for
# /var/lib/hbd/.env. The unit file is the only honest source:
ssh aizu 'systemctl show hbd-bot hbd-worker hbd-admin hbd-payme -p Id -p EnvironmentFiles -p Environment'
# The gateway is the one exception and its boot line DOES name a real path (/etc/hbd/payme.env),
# because hbd-payme.service is the only unit that uses HBD_PAYME_ENV_FILE. 00 rows 18-20.
```

**12. Is the served console bundle current, and was it built on this host at all?**
`src/bayram/admin/static/` is gitignored, so a fresh checkout has no console and a stale one is
whatever the last build left. A bundle predating the `__BAYRAM_CSP_NONCE__` placeholder
(`src/bayram/admin/shell.py:55`) is served unchanged, looks like a working panel, and logs
`admin.spa.nonce_placeholder_missing` (`shell.py:83`). Node arrives on that box by a path no
document records: `deploy/first-install-proposal.md:89` installs only ffmpeg,
postgresql-16 and redis-server, yet its lines 113/130 run `npm ci && npm run build`; `admin-ui/package.json` needs node >= 20.19.
```bash
ssh aizu 'node -v; npm -v; ls -la <checkout>/src/bayram/admin/static/index.html; grep -c __BAYRAM_CSP_NONCE__ <checkout>/src/bayram/admin/static/index.html'
```

**13. Does the host's ffmpeg have `libopus` — and an mp3 encoder?**
`libopus` is the only encoder the boot probe checks, and its absence is a hard refusal
(`src/bayram/audio/startup.py:96-103`), so a *running* bot is itself the evidence. The mp3
encoder the song master needs is checked by nothing. Do not assume the build:
`pyproject.toml:36-38` records that at least one machine in this project's history had an ffmpeg without `drawtext`.
```bash
ssh aizu "ffmpeg -hide_banner -encoders | grep -E 'libopus|libmp3lame'; command -v ffprobe"
```

**14. Is the install an editable checkout or a built wheel, and is `migrations/` on disk?**
The two differ in how the console is served (checkout static dir vs. hatch `artifacts`
force-include), and `migrations/` is not in the wheel while every documented alembic
invocation assumes it is on disk. `deploy/first-install-proposal.md:129` invokes
`.venv/bin/uv`, which cannot exist from its own instructions (`uv` is in neither `pyproject.toml` nor `uv.lock`), so
whatever actually ran there is unknown. Also unknown: whether the host checkout has an
`admin-ui/public/` directory — it is untracked here, so a clone would not create it.
```bash
ssh aizu 'ls <checkout>/.venv/lib/python3.12/site-packages/ | grep -i bayram; <checkout>/.venv/bin/python -V; ls <checkout>/migrations/versions | tail -3; ls -d <checkout>/admin-ui/public'
```

**15. Has the retention cron ever fired, and is `var/workspace` growing without bound?**
Nothing in the repository deletes `var/workspace`, so absent an out-of-band sweep it holds a
second, unexpiring copy of every song, greeting and lyric ever generated. Only the worker
runs the clocks, so a worker that has been down has also stopped re-pinning the audit HEAD
anchor. `storage_keys_returned` exceeding `storage_keys_deleted` is bytes leaking.
```bash
ssh aizu 'sudo -u postgres psql -d hbd -c "select ran_at, is_batch_full, storage_keys_returned, storage_keys_deleted from purge_runs order by ran_at desc limit 5"; du -sh <checkout>/var/workspace <checkout>/var/archive'
# purge_runs was dropped and recreated on 2026-09-10, so it cannot answer the history anyway. The
# worker's journal can, and needs no sudo — it predates the wipe and reaches the 2026-08-07 boot:
ssh aizu 'journalctl -u hbd-worker --no-pager -o cat | grep -oE "\"storage_keys_deleted\": [0-9]+" | sort | uniq -c'
# The du half is row 30 and has NO route: /var/lib/hbd is hbd:hbd 0750, du prints "Permission
# denied" and then prints "4.0K", which is the inode and not the archive. Do not quote that number.
```

**16. Are `/assets/*.js.map` reachable from the public internet?**
**Answered 2026-09-11: yes.** The application does not protect them — no middleware authenticates
that prefix (`src/bayram/admin/app.py:387-390`) — and nothing in front of it does either. What
terminates TLS is Cloudflare (question 6), and the tunnel added no filter, so the prediction from
the code held exactly.
```bash
curl -sS -D- -o /dev/null https://admin.bayrambot.uz/assets/index-D9iMG-RF.js.map
# HTTP/2 200; content-length: 4242767; cache-control: public, max-age=31536000, immutable
# server: cloudflare; via: 1.1 Caddy — unauthenticated, 4.2 MB, cached for a year.
```
**This is now a decision to take rather than a fact to find**, and it belongs in
[07-security.md](07-security.md) with a date on it: either strip `*.map` from the wheel's
`admin/static/assets/`, or deny the suffix in the Caddy admin block, or write down that it is
accepted and why. Note what the immutable header costs if the answer is "strip it": the file stays
in Cloudflare's cache and in every visitor's cache long after the bundle changes.
