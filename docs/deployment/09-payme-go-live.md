# Payme go-live — what is left before we take real money

The rail is built, deployed, publicly reachable and **switched off**. Nothing on this host has
ever moved a som. This is the single page that answers *"what is left?"*, and the honest
short answer is: **two facts only Payme can still give us, one Cloudflare configuration nobody
has applied, one business decision already taken on 2026-09-10 (leave the stub paywall as it
is), and a package rename that has landed in the repository, was attempted on the host on
2026-09-10 and aborted part-way, leaving `/etc/bayram` and `/opt/bayram/venv` behind with the
four `hbd-*` units still enabled and serving — which no release can straddle.**

> **The sentence that stood here until 2026-09-11 was "a package rename that has landed in the
> repository but not on the host". Keep it in view: it was true on the morning of 2026-09-10, it
> is what every other page in this tree was written against, and it is no longer true.** The host
> is mid-rename, not pre-rename. §2 carries the state and `08-payme.md` §11.6 carries the
> inventory.

**The settlement rehearsal is no longer on that list.** It ran on this host on 2026-09-10 at
13:30 +05, against a real sandbox cashbox, and passed 4/4 with a Telegram message delivered to
a real phone — §4. Four of Gate B's six facts were closed the same afternoon. What is left of
Gate B is the production key, which belongs at Gate F anyway, and the Basic-auth login, which
only a call from Payme's side can prove.

Everything else — the gateway, the schema, the tunnel route, the Caddy block, the sweep, the
invariant — is done and was verified on the host. That is why this page is a gate board and not
a task list: the remaining work is largely *other people's*, and the engineering that is left
is one rename cutover, an hour of rehearsal, and one edit to two dotenv files.

Why the rail exists at all is [`../decisions/DECISIONS.md`](../decisions/DECISIONS.md) **D11**.
What it does is `PAYME_INTEGRATION` §1–§7. How it runs on a host is
[`08-payme.md`](08-payme.md). This page is only the sequencing: which gates are open, who can
close each one, and the command that proves a gate closed rather than looked closed.

---

## 0. What was verified, when, and how

> **This page is not covered by the tree's blanket "nothing here was checked against `aizu`"
> disclaimer.** Every claim below is marked. `[HOST 2026-09-10]` means a read-only command was
> run against `aizu` on that date and the output is quoted or paraphrased faithfully.
> `[HOST 2026-09-09]` means it was established during the deploy of that day and recorded then.
> `[HOST 2026-09-11]` is the newest pass and the one to trust where two dates disagree — **and
> where a 2026-09-10 claim is left standing beside it, that is deliberate**: a superseded
> statement with its date is more useful than a clean one with no history.
> `[TREE 2026-09-10]` means it is checkable by opening the file named in this working tree,
> whose contents moved under this page while it was being written. **`[UNPROVEN]` means exactly that,
> and there is more of it on this page than anybody would like.**

| Fact | Evidence |
| --- | --- |
| `hbd-payme`, `hbd-bot`, `hbd-worker`, `hbd-admin`, `caddy`, `cloudflared` all `active` | `[HOST 2026-09-10]` `systemctl is-active …`, and again `[HOST 2026-09-11]`. The four application units entered `active` at 06:50:11–06:50:13 on 2026-09-11 with `NRestarts=0` and no reboot — **so somebody restarted them by hand that morning**, which is worth knowing before you read any "since 14:08 nothing has been touched" claim |
| The gateway's real unit: `User=hbd`, `Environment=HBD_PAYME_ENV_FILE=/etc/hbd/payme.env`, `ExecStart=/opt/hbd/venv/bin/python -m uvicorn hbd.payme.app:app --host 127.0.0.1 --port 8091` | `[HOST 2026-09-10]` `systemctl cat hbd-payme` |
| Caddy's pay block is `http://pay.bayrambot.uz`, `handle /payme` → `127.0.0.1:8091` with `keepalive 10m`, everything else `respond 404`, logs to `output stderr` | `[HOST 2026-09-10]` `/etc/caddy/Caddyfile` |
| The public endpoint answers `200` with `-32504` unauthenticated and `-31003` authenticated, through the tunnel | `[HOST 2026-09-09]` |
| Database at alembic `0024`; backups at `/var/backups/hbd/pre-payme-*.sql.gz` | `[HOST 2026-09-09]`, and **re-verified** `[HOST 2026-09-11]` — still `0024`, read with no password via `sudo -n -u postgres /usr/bin/pg_dump hbd \| grep -A3 "COPY public.alembic_version"` |
| ~~`0024` is head~~ **`0024` is no longer head**: 25 revision files are on disk in `/opt/hbd/migrations/versions/`, the newest being `20260910_1000_0025_index_settlement_clocks.py`, and it is **unapplied**. `0025` adds an index, so `08-payme.md` §11.7's additive-rollback argument extends — because somebody checked | `[HOST 2026-09-11]` |
| **The rename was attempted on the host on 2026-09-10 and aborted.** `/etc/bayram/{bayram.env,bayram-admin.env,payme.env}` and `/opt/bayram/venv` (package `bayram` installed) exist; **no `bayram-*.service` file exists**, there is no `bayram` OS user or group, and the four `hbd-*` units are `enabled` and `active`. Two `pre-cutover-*.sql.gz` backups; services stopped 14:05:06–14:05:07 and restarted by hand at 14:08:00–14:08:01, `NRestarts=0` | `[HOST 2026-09-11]` — §2, and `08-payme.md` §11.6 for the full inventory |
| The gateway's cashbox is the sandbox one and **`environment` is still `dev`** — the `payme.boot.ok` line of 2026-09-11 06:50:15 reads `merchant_id: 6aa24fd9ee30563de3a1ac22`, `is_sandbox: true`, `environment: "dev"`, `env_file: /etc/hbd/payme.env`. So the gateway's vendor-credential boot refusal, an exact `== "prod"` compare, is **not armed** while a real cashbox key is loaded | `[HOST 2026-09-11]` `journalctl -u hbd-payme \| grep payme.boot.ok` — `08-payme.md` §2.1 |
| The rail tables now have rows: `payment_intents` 7, `payme_transactions` 3, `payme_rpc_log` 53, `topup_purchases` 6, `credit_ledger` 18 | `[HOST 2026-09-11]` counted out of `pg_dump hbd` — the ledger-side corroboration of §4 |
| **The pause key is not set, on either side of the rename.** Redis holds 5 keys; neither `hbd:payme:paused` nor `bayram:payme:paused` is among them | `[HOST 2026-09-11]` `redis-cli --scan`, `redis-cli get` on both. So §2's specific trap is **not armed today** — which is a fact with a timestamp, not a standing property |
| The worker runs `run_payme_sweep` every 5 minutes **and** the invariant arm. It reported `transactions_performed: 0, receipts_written: 0, grants_written: 0` all morning; at 13:35:00 +05, the first sweep whose window contained the rehearsal, it reported **`1, 1, 1`** — equal and non-zero, which is the assertion | `[HOST 2026-09-10]` `journalctl -u hbd-worker` at 09:55:00 and 13:35:00 |
| Still `1, 1, 1` at 10:45, 10:50 and 10:55 +05 on 2026-09-11, over a window opening the previous day — and **it returns to three zeroes at about 13:35 +05 that day**, when the rehearsal ages out of the rolling 24 hours. Twelve sweeps in the last hour | `[HOST 2026-09-11]` `journalctl -u hbd-worker`. **A third cause of three zeroes**, indistinguishable from the other two without a row probe — `PAYME_INTEGRATION` §8.5.1 |
| The bot boots warning `"the checkout is wired but the credit meter is dark"`, `credits_enforced: false` | `[HOST 2026-09-10]` `journalctl -u hbd-bot`, 09:27:36 |
| The **render gate** is a no-op: `"payment authorised by the no-op provider"`, `amount_minor: 0`. This is `NoopPaymentProvider.authorize` (`src/bayram/payments.py:71`), the *render* seam, **not** `CheckoutProvider.charge` — the two are separate by design (`PAYME_INTEGRATION` §1.1) and `amount_minor: 0` is `FREE_AMOUNT_MINOR`, a constant of that seam, not a price. Evidence about the checkout is the boot warning on the row above. | `[HOST 2026-09-10]` `journalctl -u hbd-bot`, most recent entry 2026-09-07 |
| ~~Settlement has never been executed on this host~~ **Settlement has now been executed on this host**: the harness passed 4/4 scenarios (`authorization`, `scenario-one`, `scenario-two`, `refusals`), run id `e767f6ce`, and the worker's *"your payment went through"* message arrived on a real phone | `[HOST 2026-09-10]` — 13:30:14 to 13:30:16 +05, transcript summarised in §4 |
| The gateway is running with a **real sandbox cashbox**: the boot line's `merchant_id` is no longer `placeholder`, and `is_sandbox` is still `true` | `[HOST 2026-09-10]` `journalctl -u hbd-payme \| grep payme.boot.ok` |

### 0.1 The three zeroes were not good news, and the run that ended them

`"the payme settlement invariant holds"` with `transactions_performed: 0`,
`receipts_written: 0`, `grants_written: 0` was the reconciliation arm reporting that nothing
disagreed because nothing had happened. It proved the *sweep* was wired, scheduled and reaching
the database. It proved nothing whatsoever about the path
`intent → CreateTransaction → PerformTransaction → receipt + credit in one commit → ARQ job →
Telegram message`, which is the only path that matters and which no process on this host had
ever walked. Gate C existed to walk it, and on 2026-09-10 it was walked (§4).

**Keep this subsection after the fact, because the shape of the trap outlives the instance.**
A green `systemctl is-active`, a `200` from `/healthz` and an invariant that holds are all
satisfied by a subsystem that has never done its job once. When the next rehearsal is needed —
after the Gate A rename, after a Postgres upgrade, after any change to the one-commit write
primitive — the zeroes will be back and they will look exactly as reassuring as they did on the
morning of 2026-09-10.

**And one piece of reading-the-output craft, learned the same afternoon.** The sweep runs every
five minutes; the 13:30:00 sweep fired **fourteen seconds before** the harness started and
therefore reported zeroes that were perfectly correct and completely misleading. A sweep whose
window closes before the run begins cannot see it. Wait for the next one rather than concluding
the rehearsal did not settle.

**A third cause was found on 2026-09-11 and it is the one that will recur for ever.** The arm
reconciles a **rolling 24 hours**, so the `1, 1, 1` this page records is temporary by construction:
`[HOST 2026-09-11]` it was still `1, 1, 1` at 10:55 +05, and at about 13:35 +05 the rehearsal falls
out of the window and the counts return to `0, 0, 0` permanently — until something else settles.
**So three zeroes means "never settled" **or** "the sweep fired too early" **or** "nothing in the
last day", and a count cannot tell you which.** Only a window-ignoring row probe can; that is the
mechanism `BILLING_RAIL_BOARD` §8.1 built for the screen, and `PAYME_INTEGRATION` §8.5.1 applies it
to the log line. When the question is *"has this host ever settled anything"*, ask the tables.

---

## 1. How to read this page

### 1.1 Two switches, two questions — do not conflate them

`HBD_PAYME_ENABLED` governs **whether the gateway daemon runs**. It is `true` today, and the
lifespan refuses to start without it.

`HBD_CHECKOUT_PROVIDER` governs **whether the product sells anything through Payme**. It is
unset today, so the bot's composition root takes its first branch and builds
`StubCheckoutProvider` (`src/bayram/runtime/container.py:358`).

These are different questions with different blast radii, and it is worth saying so plainly
because "Payme is enabled" is true on this host and means nothing about revenue. The gateway
being up while the rail is off is the *designed* intermediate state: it is what let the
endpoint be certified, routed, tunnelled and proven publicly reachable weeks before anybody
decided to take money, and it is what makes Gate C runnable at all.

### 1.2 The commands on this page say `hbd`, the repository says `bayram`, and both are right

**The repository has been renamed from `hbd` to `bayram`; the host has not.** As of
`[TREE 2026-09-10]` the package is `src/bayram`, `ENV_PREFIX` is the literal `"BAYRAM_"`
(`src/bayram/config.py:75`), all 295 modules import `bayram.…`, `.env.example` carries a
hundred `BAYRAM_*` lines and no `HBD_*` ones, and the unit files are
`deploy/systemd/bayram-*.service`. As of `[HOST 2026-09-10]` the machine runs
`hbd-payme.service`, `ExecStart=/opt/hbd/venv/bin/python -m uvicorn hbd.payme.app:app`,
`Environment=HBD_PAYME_ENV_FILE=/etc/hbd/payme.env`, with the package installed as `hbd` in
`/opt/hbd/venv`.

**Every runnable command on this page is written for the host as it is today**, because a
go-live checklist whose commands do not run is not a checklist. Every *source citation* is
written against the tree as it is today (`src/bayram/…`), because that is where the line
numbers are. Closing that gap is Gate A (§2), and it is the operation that renames both
halves of this page at once:

| Reading | Host today | Repository today, and the host after Gate A |
| --- | --- | --- |
| Env prefix | `HBD_*` | `BAYRAM_*` |
| Units | `hbd-bot`, `hbd-worker`, `hbd-admin`, `hbd-payme` | `bayram-*` |
| Gateway env file | `/etc/hbd/payme.env` | ~~named by the unit; free to keep or move~~ **the choice has been made on the host and not recorded anywhere else**: the cutover script moves it to `/etc/bayram/payme.env` — same filename, new directory — and rewrites the pointer's value as well as its key. `/etc/bayram/payme.env` already exists there `[HOST 2026-09-11]` and is read by nothing (§2) |
| Venv, package | `/opt/hbd/venv`, `hbd` | `bayram` |
| Module path | `hbd.payme.cli`, `hbd.payme.harness` | `bayram.payme.…` |

After the cutover, this page is a `s/HBD_/BAYRAM_/g` and a `s/hbd/bayram/g` over its commands
— and that sed is safe only *because* Gate A insists the two halves move together rather than
drifting.

### 1.3 The gate board

| Gate | What must be true | Who can close it | State |
| --- | --- | --- | --- |
| **A** — one name | The host and the package agree: installed package, unit names, `ENV_PREFIX` and every Redis key string. The repository is already `bayram`; **every running process on the host is still `hbd`, and since 2026-09-10 a half-finished `bayram` install sits beside it that nothing executes** | Engineering — and it now has its own page, [`10-rename-cutover.md`](10-rename-cutover.md) | **OPEN, AND NO LONGER FROM A CLEAN HOST** — a cutover ran on 2026-09-10 and aborted inside its migration step; `/etc/bayram` and `/opt/bayram/venv` are the residue. No release can cross Gate F |
| **B** — the six facts | Merchant id, TEST_KEY, production key, registered endpoint, account field name, Basic-auth login | АО «PAYME», prompted by us | **FOUR OF SIX CLOSED 2026-09-10.** Open: the production key (belongs at Gate F) and the Basic-auth login (§3) |
| **C** — settlement proven | The harness has driven a full settlement on this host and a Telegram message arrived | Engineering, ~1 hour | **CLOSED 2026-09-10** — 4/4, run id `e767f6ce`, message delivered (§4) |
| **D** — Cloudflare | Bot Fight Mode off and a WAF skip rule for `pay.bayrambot.uz` | Whoever administers the Cloudflare Zero Trust account | **OPEN — not applied** |
| **E** — the business | The owner says take real money; the no-refunds position survives certification | The owner | **DECIDED 2026-09-10: not yet. See §6 and §7.** |
| **F** — the switch-on | Two dotenv edits, two restarts, one real card | Engineering, once A–E are closed | Not started |
| **G** — one bot holds the token | `hbd-bot` is the only consumer of `getUpdates` for this token | Engineering — find the other holder | **OPEN, and it is a live defect**: 487 `TelegramConflictError` lines, daily, most recently 2026-09-11 11:19 (`06-troubleshooting.md` §17a) |

Gates A and D are ours and can be closed this week; **C is closed.** The remainder of B is not
ours. E is a business decision already taken, with a date, and is recorded as a decision rather
than as a gap.

**Gate G was added on 2026-09-11 and was found by reading the journal, not by anybody reporting
it.** Two consumers are polling this bot's token and have been every day since the units were
enabled; `getUpdates` is exclusive, so they take turns stealing updates from each other and
nothing retries the stolen ones. **It is a gate rather than a note because of what it does to a
paid order**: a customer whose message lands on the other consumer has paid and started nothing.
Today `HBD_CHECKOUT_PROVIDER` is unset and no money can move, which is the only reason this has
cost nothing so far — so it must close **before** F, not after. The second consumer is not on this
host; the hourly distribution points at a developer machine. `06-troubleshooting.md` §17a has the
evidence and the three candidate causes.

---

## 2. Gate A — the host and the package must agree on one name

**What must be true.** The name the wheel ships, the name the unit's `ExecStart` imports, the
prefix the settings model reads, and the Redis keys the running code writes are all one name.

**The split used to be clean — repository `bayram`, host `hbd` — and as of 2026-09-10 it is not.**
A cutover script was run on the host that afternoon and stopped inside its migration step, so
there is now a third column: things that exist under the new name on the host and that **nothing
runs**. That is a worse starting position than a clean host, because a verification that looks at
one root can answer "nothing has moved" and be wrong.

| | Repository `[TREE 2026-09-11]` | Host, what RUNS `[HOST 2026-09-11]` | Host, what EXISTS and runs nothing `[HOST 2026-09-11]` |
| --- | --- | --- | --- |
| Package | `pyproject.toml:69` → `packages = ["src/bayram"]` | `hbd` installed in `/opt/hbd/venv` | `bayram` + `bayram_bot-0.1.0.dist-info` installed in `/opt/bayram/venv`, built 2026-09-10 14:06–14:07 |
| Imports | all 295 modules `from bayram.…` | — | — |
| Env prefix | `src/bayram/config.py:75` → `"BAYRAM_"`; `.env.example` has 100 `BAYRAM_*` lines and zero `HBD_*` | three dotenv files of `HBD_*` under `/etc/hbd/` | three `BAYRAM_*`-rewritten files under `/etc/bayram/` — `bayram.env`, `bayram-admin.env`, `payme.env`, `0640 root:hbd`, **read by nothing** |
| Units | `deploy/systemd/bayram-*.service` | `hbd-bot`, `hbd-worker`, `hbd-admin`, `hbd-payme` — all `enabled`, all `active` | **nothing.** No `bayram-*.service` file exists; no `bayram` OS user or group exists |
| Gateway `ExecStart` | — | `-m uvicorn hbd.payme.app:app` | — |
| Schema | 25 revision files, head `0025` | database at `0024` | `/opt/bayram/migrations/versions/` — the same 25 files, copied |
| Wheel | — | `hbd_bot-0.1.0-20260909-py3-none-any.whl` | `bayram_bot-0.1.0-py3-none-any.whl`, PEP 427 valid, in `/opt/hbd/release/` since 14:03 |

**So Gate A is no longer "do the rename". It is "finish or abandon the one that is already half
done".** The operation has its own page as of 2026-09-11 —
[`10-rename-cutover.md`](10-rename-cutover.md), §2 for the attempt and what it left behind, §3 for
the directive-by-directive inventory, §4 for the preconditions a window needs — and
`08-payme.md` §11.6 carries the gateway's share of it: the restart-loop mechanism that makes a
half-done rename look healthy, and what deliberately does not move. **Read both before scheduling
anything.** This page stays what it has always been: the gate board, and the sequencing around it.

**Why this is a payment gate and not a tidiness gate.** Most of the disagreement fails
*loudly*, which is fine: a unit whose `ExecStart` names `hbd.payme.app` against a wheel that
ships `bayram` dies at once, and a `BAYRAM_`-prefixed settings model reading a dotenv full of
`HBD_` lines sees an empty environment and raises a `ConfigError` naming the first missing
required field. Neither can serve a customer while broken.

**Two things fail silently, and both of them are about money.**

* **The pause switch is a Redis key, and the rename moved it.** `[HOST 2026-09-11]` the deployed
  wheel writes `"hbd:payme:paused"` at
  `/opt/hbd/venv/lib/python3.12/site-packages/hbd/payme/pause.py:75`, and the staged wheel — both
  in `/opt/bayram/venv` and in the tree at `src/bayram/payme/pause.py:75` — writes
  `"bayram:payme:paused"`. **A rail paused before the cutover is open after it, and nothing
  anywhere will say so.** The key has no TTL and no durable backing (§9.2 records why that is
  deliberate), so there is no reconciliation that would catch it and no `status` output that would
  look wrong — `cli status` run by the new code truthfully reports the new key, which nobody set.

  **`[HOST 2026-09-11]` neither key is set right now**, so this specific trap is not armed today:
  Redis holds five keys and neither spelling is among them. Read that as a fact with a timestamp
  rather than a property — it is true of this hour, it was checked because it is cheap to check,
  and it is exactly the state that step 1 of the cutover below exists to re-establish.
  Worth knowing while you are in there: **`resume` is a `DELETE`, not a falsy write**, and `0`,
  `""`, `false`, `no` and `off` all read as *open* (`src/bayram/payme/pause.py`), so a hand-written
  `redis-cli SET <key> 0` neither pauses nor resumes anything.
* **The deterministic idempotency prefix moved too.** `KEY_PREFIX = "bayram"`
  (`src/bayram/pipeline/idempotency.py:23`), and every key is
  `f"{KEY_PREFIX}-{stage}-{digest}"` over a `sha256` whose input *includes* the prefix. So
  every key changes. An in-flight order retried across the cutover mints a key no vendor has
  seen, and pays for the same generation twice.

There is a third, and this page used to understate it. The NOPASSWD drop-in at
`/etc/sudoers.d/hbd-deploy` is written against the **`hbd-*` verbs**, so renaming the units stops
it matching and every `systemctl` call during the cutover prompts for a password — including the
ones in the rollback. **But half the cutover was never covered even before the rename.**
`[HOST 2026-09-11]` the NOPASSWD list grants `restart` — and only `restart` — of `hbd-bot`,
`hbd-worker` and `hbd-admin`. There is **no `stop`**, **no `disable`**, and no `enable` for
anything but `hbd-payme`. So:

| Cutover action | Covered by the drop-in? |
| --- | --- |
| `systemctl stop hbd-bot hbd-worker hbd-admin` (step 2) | **no** — password |
| `systemctl stop hbd-payme` | yes |
| `systemctl disable hbd-*` (step 7) | only `hbd-payme` |
| `systemctl enable --now bayram-*` (step 8) | **no** — password |
| `systemctl daemon-reload` | yes |
| `sudo -u hbd env … -m bayram.payme.harness …` (the Gate C re-run, §4.0) | **no** — password |
| `tee /etc/bayram/*.env` | **no** — the rule names `/etc/hbd/payme.env` by path |

`developer` has a separate `(ALL : ALL) ALL` line `[HOST 2026-09-11]`, so every one of those gaps
is a password prompt rather than a wall. **Plan for a human at a keyboard for most of the window,
and do not schedule any of it unattended.** And one further reason not to leave the drop-in for
last: `08-payme.md` §11.1 records that its single NOPASSWD *root* target,
`/opt/hbd/deploy-payme.sh`, is a file `developer` can rewrite — and was rewritten on 2026-09-10.
The rename is the one scheduled change that has to touch this file anyway, which makes it the
cheapest moment to fix that shape.

**The rejected alternative** is "finish the rename during go-live, it is only strings". It is
not only strings: it is a Redis key, an idempotency prefix, four unit names, three dotenv
files, an env-var prefix, a venv path and a sudoers rule, and the two that matter most fail
without an error message. **Land the cutover as one all-or-nothing operation with its own
rollback, either well before Gate F or well after it — never across it, and never on the same
day.**

**The cutover, in the order that makes the silent failures impossible.**

1. **Confirm the rail is not paused, and quiesce.** The pause does not survive, and neither do
   in-flight idempotency keys. Check `cli status` (§9.2) and let the pipeline drain first.
2. Build the wheel with a **PEP 427 valid filename**. A build tag is legal; a marketing word is
   not — `hbd_bot-0.1.0-PAYME-20260909.whl` was rejected by pip with *"Invalid wheel filename
   (wrong number of parts)"* on 2026-09-09. Use
   `<name>-<version>-<build tag>-py3-none-any.whl`.
3. **Copy `migrations/versions/*.py` separately.** A wheel carries no migrations, and without
   them `alembic upgrade head` stops at whatever is on disk **and reports success** — a green
   deploy over a schema three revisions behind, which is the worst possible shape for a failure
   on a payment release.
4. Install, then **`pip check` before restarting anything**. `pip install --no-deps` silently
   omits new runtime dependencies; `pillow` was new in the 0.1.0-20260909 release and was
   caught exactly this way, before any service restarted.
5. **Write the dotenv files under their new names into a new directory — do not rewrite the
   existing three in place.** This step used to read *"rewrite the prefix in all three dotenv
   files"*, and that is not the shape the host's own cutover script implements, which makes the
   script the better record of the decision: it writes `/etc/hbd/hbd.env` →
   `/etc/bayram/bayram.env`, `/etc/hbd/hbd-admin.env` → `/etc/bayram/bayram-admin.env` and
   `/etc/hbd/payme.env` → `/etc/bayram/payme.env` — **new directory, new filenames, `/etc/hbd`
   left intact** — and it rewrites the gateway pointer's **value** as well as its key
   (`sed -i "s#$OLD_ETC/payme.env#$NEW_ETC/payme.env#"`), because `Environment=HBD_PAYME_ENV_FILE=`
   carries a path and renaming only the variable would leave it pointing at the old file.
   **Leaving `/etc/hbd` in place is what makes the rollback one `systemctl` pair rather than a
   restore from backup**, and it is why steps 3 and 4 of the script are the re-runnable ones.
   Two things to watch: the script `chmod 0755`es the new directory while copying mode and owner
   only for the files, so `/etc/bayram` ends up `0755 root:root` against `/etc/hbd`'s
   `0750 root:hbd` — fix that in the same operation; and the rewrite is `sed 's/^HBD_/BAYRAM_/'`,
   so any line **not** starting `HBD_` is copied through unrenamed into a settings model that no
   longer reads it (`08-payme.md` §11.6 has the one `sudo grep` that settles whether any such line
   exists, and it has to be run **before** the window).
6. Install the four `bayram-*` units, `systemctl disable` the four `hbd-*` ones, `daemon-reload`,
   `enable --now` the new ones, and **replace the sudoers drop-in in the same operation** —
   against the `bayram-*` unit names and the `/etc/bayram/` paths, and with its root target moved
   off a `developer`-writable file while you are in there.
7. Re-arm the pause switch if it was set at step 1.
8. **Re-run Gate C** (§4.0). It is the last step of the window, not a follow-up.

**How to verify it closed.**

```bash
# 0. FIRST: is the host pre-rename, post-rename, or half-way? Since 2026-09-10 the answer is
#    "half-way", and a probe that reads one root cannot see it. Look at both.
ssh aizu 'for v in /opt/*/venv; do printf "%s: " "$v"; ls "$v/lib/python3.12/site-packages/" | grep -ixE "hbd|bayram" | tr "\n" " "; echo; done'
ssh aizu 'ls -ld /etc/hbd /etc/bayram 2>/dev/null; ls -la /etc/bayram/ 2>/dev/null'

# 1. One name, three places. The units decide what RUNS; the directories above only say what
#    exists. Read them in that order.
ssh aizu 'systemctl cat bayram-payme | grep -E "ExecStart|ENV_FILE"'
grep -n "ENV_PREFIX: Final" src/bayram/config.py

# 2. The pause key the new code writes is the key the running bot reads. These two strings
#    must be identical; on 2026-09-10 they were not.
grep -n "PAYME_PAUSE_KEY: Final" src/bayram/payme/pause.py
ssh aizu 'grep -o "\"[a-z]*:payme:paused\"" /opt/hbd/venv/lib/python3.12/site-packages/*/payme/pause.py'

# 3. Nothing still answers to the old name — a stale enabled unit is how you get two bots
#    polling one Telegram token.
ssh aizu 'systemctl list-units --all --no-legend | grep -iE "hbd|bayram"'

# 4. The schema really did move. The psql form needs a password; this one does not, and it is
#    the route that answered the question on 2026-09-11.
ssh aizu 'sudo -n -u postgres /usr/bin/pg_dump hbd 2>/dev/null | grep -A3 "COPY public.alembic_version"'
```

**Item 4 is the one that would have caught the 2026-09-10 abort.** `[HOST 2026-09-11]` it answers
`0024` while `0025` sits unapplied on disk in both `/opt/hbd/migrations/versions/` and
`/opt/bayram/migrations/versions/`. The `pg_dump` route is NOPASSWD and the `psql` route is not;
note also that the rule matches the exact argument vector, so you cannot add `--schema-only`, and
the dump carries every customer row — keep it in a pipe (`08-payme.md` §3.2).

**The database is named `hbd` `[HOST 2026-09-09]` and there is no reason to rename it.** The
verdict stands; the evidence this page used to give for it — *"the name appears in
`BAYRAM_DATABASE_URL` and nowhere else"* — was wrong, and wrong in the direction that weakens a
correct conclusion. It also appears:

* in `BAYRAM_DB_MIGRATION_URL` (`.env.example:46`) `[TREE 2026-09-11]`, and as the database name
  in all four example DSNs;
* as the role names inside those DSNs — `hbd_app` in `.env.example:35`, `hbd` in `:46`,
  `.env.admin.example:51` and `.env.payme.example:61` `[TREE 2026-09-11]`;
* as the **owner of every object in the database** — 31 `OWNER TO hbd_app` lines — and the sole
  schema grantee, `GRANT ALL ON SCHEMA public TO hbd_app` after
  `REVOKE USAGE ON SCHEMA public FROM PUBLIC` `[HOST 2026-09-11]`;
* in the sudoers NOPASSWD rule `(postgres) NOPASSWD: /usr/bin/pg_dump hbd` `[HOST 2026-09-11]`,
  which is argument-exact and would stop matching;
* in the backup directory `/var/backups/hbd/` `[HOST 2026-09-11]`;
* and in the two Postgres function names the `bayram` package still **hard-codes**:
  `PURGE_FUNCTION_NAME = "hbd_purge_audit_log"` and
  `REASON_PURGE_FUNCTION_NAME = "hbd_purge_audit_reasons"` (`src/bayram/db/admin/audit.py:122-123`)
  `[TREE 2026-09-11]`, matching migrations `0007` and `0011`.

**Every one of those is a further argument against renaming it, and the last is the precedent:
the rename already held Postgres identifiers stable on purpose.** Renaming a live database to
match a brand is risk with no return.

One related fact, because it surprises people who go looking for those functions: `[HOST
2026-09-11]` **there are zero `CREATE FUNCTION` statements in this database**, so
`hbd_purge_audit_log` and `hbd_purge_audit_reasons` do not exist here at all — which is
`00-host-inventory.md`'s row about migration `0007`'s `REVOKE`, answerable the same way.

---

## 3. Gate B — the six facts only Payme can supply

**What must be true.** Six values exist, five of them are in `/etc/hbd/payme.env` or
`/etc/hbd/hbd.env`, and one is typed into the Payme cabinet by a human.

> **Four of the six closed on 2026-09-10** against a sandbox cashbox: the merchant id and
> TEST_KEY are in `/etc/hbd/payme.env` and the boot line confirms the gateway read them; the
> endpoint is registered; the account field is declared. The `Status` column below records which.
> **Two remain, and neither blocks sandbox certification**: the production key is a Gate F edit,
> and the Basic-auth login cannot be proved from our side at all — see §3.2.

| # | Fact | Status | Where it lands | What happens if it is wrong |
| - | --- | --- | --- | --- |
| 1 | **Merchant id (кассы id)** — public | **CLOSED 2026-09-10** (sandbox cashbox) | `HBD_PAYME_MERCHANT_ID` in **both** the bot's dotenv and the gateway's | Blank under `checkout_provider=payme` is a boot `ConfigError` naming the variable (`src/bayram/runtime/container.py:366`) — deliberately, because the alternative is a link with an empty `m=` and Payme answering «Поставщик не найден», a sentence about *their* system that a customer reads as one about ours. A *wrong* id is caught at settlement: the gateway compares it against `payment_intents.merchant_id` and answers `-31055`. |
| 2 | **TEST_KEY** | **CLOSED 2026-09-10** | `HBD_PAYME_MERCHANT_KEY`, gateway only | Certification cannot start. |
| 3 | **Production key** | OPEN — a Gate F edit, deliberately not earlier | Same variable, replacing the TEST_KEY at Gate F | Every call is `-32504`. |
| 4 | **Endpoint registered in the cabinet** — `https://pay.bayrambot.uz/payme` | **CLOSED 2026-09-10** | A cabinet form | Payme calls nothing; the journal is silent, which reads exactly like the endpoint being broken. |
| 5 | **The «Настройка Аккаунт» field name** | **CLOSED 2026-09-10** — `order_id`, with the validator of `08-payme.md` §5.1 | Must equal `HBD_PAYME_ACCOUNT_FIELD` exactly; we default to `order_id` | **Every payment fails and it looks like our bug.** Each `CheckPerformTransaction` answers `-31050`. This is the single most expensive way to spend a certification slot. |
| 6 | **The Basic-auth login** | OPEN — unprovable from our side (§3.2) | `HBD_PAYME_BASIC_LOGIN`, defaulting to the literal `Paycom` | Every call is `-32504`. Our default works against our own gateway, which proves precisely nothing about theirs. |

A seventh is not Payme's to supply and **was settled on 2026-09-10**: **the code for "this order
already has another active transaction"**. Payme's own materials contradict each other — the
sandbox scenario text demands `-31008`, PaycomUZ's PHP template returns `-31050`
(`PAYME_INTEGRATION` §7.2). We emit `-31008` through `HBD_PAYME_DUPLICATE_TRANSACTION_CODE` and
have decided to keep it, believing the documentation over the template. §3.1 records that as our
decision rather than their confirmation, and names the trigger that reverses it.

**Who can close it.** АО «PAYME», via the cabinet (Кассы → the kassa → Настройки →
Инструменты разработчика) and their technical contact. Not us. What *is* ours is asking for
all six at once, in one message, rather than discovering them one failed scenario at a time.

**Why every one of these is an environment variable and not a constant.** This is the design
decision that makes Gate B cheap: items 1, 2, 3, 5, 6 and the seventh are all read from the
dotenv, so closing each is **one edit and one restart, never a release**. That was chosen
precisely because the facts are inferred from secondary sources and the person holding the
certification slot must be able to turn the knob in the slot. `PAYME_INTEGRATION` §7 names the
experiment that closes each.

**How to verify it closed.** Each has an observation, not an assurance:

```bash
# 5 — the account field. The -31050 line records the subfield names RECEIVED alongside
#     the one expected. One line settles it.
ssh aizu 'journalctl -u hbd-payme --since today -o cat | grep -- "-31050" | tail -5'

# 6 — the login. The -32504 line records the login received and never the key.
ssh aizu 'journalctl -u hbd-payme --since today -o cat | grep -- "-32504" | tail -5'

# 1 — the merchant id, without printing the key.
ssh aizu 'sudo grep -c "^HBD_PAYME_MERCHANT_ID=.\+" /etc/hbd/payme.env'
```

The two journal reads need no `sudo` — `developer` is in the `adm` group `[HOST 2026-09-10]`.
The third does: `/etc/hbd/payme.env` is `root:hbd 0640` `[HOST 2026-09-09]`, so `developer`
cannot read it at all, and reading the gateway's own configuration is the one part of this
gate that needs a password. That is the same permission wall Gate C's harness command walks
around with `sudo -u hbd`.

### 3.1 The three inferred facts — two settled by us on 2026-09-10, one that answers itself

Each of these is a fact our implementation has had to *infer* from secondary sources —
PaycomUZ's PHP template, the sandbox scenario text, and published examples that contradict each
other. Each is already an environment variable precisely so that the answer costs one edit and
one restart rather than a release (`PAYME_INTEGRATION` §7). And each, left unresolved, fails in a
way that looks like our bug at the worst possible moment.

> **Provenance, stated plainly because it is the thing that decays.** Items 1 and 3 below were
> settled on **2026-09-10 on our own authority — believe the published documentation, discard the
> PHP template's behaviour — and NOT by a confirmation from Payme.** Nobody at АО
> «PAYME» has answered anything as of this writing. That distinction is the whole value of this
> subsection: a decision we took reverses at its own trigger, while a fact they confirmed does
> not, and recording the first as the second is how the next person stops looking. Item 2 is
> neither decided nor askable — it answers itself from a log line, see below.

| # | What we do today | Status | Set by | If it turns out to be wrong |
| - | --- | --- | --- | --- |
| 1 | Return **`-31008`** when an order already has another active transaction | **SETTLED 2026-09-10 — keep `-31008`**, the documented sandbox value; the PHP template's `-31050` is treated as stale. No change: it is already the default | `HBD_PAYME_DUPLICATE_TRANSACTION_CODE` | The sandbox's duplicate-transaction scenario fails and nothing else does, which reads as a state-machine bug rather than a one-line constant. **Trigger: that single scenario failing. Reversal: set the variable to `-31050` and restart, inside the slot.** |
| 2 | Authenticate every inbound call as Basic **`Paycom`**`:<key>` | **NOT ASKABLE — it answers itself**, from the first `-32504` of the slot (§3.2) | `HBD_PAYME_BASIC_LOGIN` | **Every single call is `-32504`.** Total outage that looks identical to a wrong key. **Reversal: the real login off the log line, one variable, one restart.** |
| 3 | Emit unset `perform_time` / `cancel_time` as **integer `0`**, never `null` | **SETTLED 2026-09-10 — integer `0` is correct.** No change: `MISSING_TIME` is already `0` | Not configurable — `MISSING_TIME` in `protocol.py:91` | The only one of the three that would be a **code change** rather than an env edit, so it cannot be fixed inside the slot. **Trigger: `CheckTransaction` rejected on a field we believe is well-formed.** |

Item 1 is the sharpest, because the contradiction is documented on both sides: the sandbox
scenario text demands `-31008`, and PaycomUZ's own PHP merchant template returns `-31050` for
the same condition (`PAYME_INTEGRATION` §7.2). **The position taken is to believe the
documentation and treat the template as stale** — the template is a sample application that has
drifted from the platform before, and the sandbox is the thing that actually grades us. It is
still worth one sentence to support, because it is free to ask and a wasted certification slot
is not; but the answer is no longer blocking, and if none arrives the position stands.

**The message, ready to send.** Russian, because that is the language their technical support
answers in, and down to the one item worth a question:

```text
Здравствуйте!

Мы завершаем интеграцию Merchant API: касса в песочнице, эндпоинт
https://pay.bayrambot.uz/payme зарегистрирован, реквизит order_id настроен,
сценарии песочницы проходят на нашей стороне.

Один вопрос перед сеансом сертификации. Код ошибки для случая «у заказа уже
есть другая активная транзакция»: мы возвращаем -31008, как указано в тексте
сценариев песочницы, однако в вашем PHP-шаблоне для этого же случая
возвращается -31050. Какой код проверяет песочница?

Заранее благодарим.
```

**Record the answer here, in the table, on the day it arrives** — with the date and who said it,
and change item 1's status from *settled by us* to *confirmed by Payme*. The two are not the same
thing and only one of them stops being revisited.

### 3.2 Why the login is the one fact we cannot close ourselves

Gate C's harness asserts that the right key under the login `admin` is refused `-32504`, and
that assertion is worth making — it is the specific weakening a popular third-party package
ships. But it proves our gateway refuses the wrong login. **It proves nothing about which login
Payme sends.** The two are independent, and our default working against our own code is the
exact shape of a fact that looks verified and is not.

There is precisely one piece of evidence that closes it, and it can only arrive from their side:
the first `-32504` our journal records during sandbox certification. That log line deliberately
records the login it was **sent** and never the key:

```bash
ssh aizu 'journalctl -u hbd-payme --since today -o cat | grep -- "-32504" | tail -5'
```

If the login in that line is not `Paycom`, put the real one in `HBD_PAYME_BASIC_LOGIN`, restart,
and the slot continues. That is the whole repair, and it is why this fact — alarming as a total
outage sounds — is a minute of work rather than a blocker.

---

## 4. Gate C — CLOSED 2026-09-10: settlement has been executed on this host

**What must be true.** The full path has run once on this host, end to end, and a real Telegram
message arrived on somebody's phone.

### 4.0 What happened, so the next person does not have to take it on trust

**`[HOST 2026-09-10]` 13:30:14 → 13:30:16 +05. Run id `e767f6ce`. 4/4 scenarios passed, and the
worker's message arrived on a real phone.** Sixteen hundred milliseconds, after weeks of the
whole question being open.

| Scenario | What it closed |
| --- | --- |
| `authorization` | A wrong key is `-32504` at HTTP 200; the right key under the login `admin` is `-32504` too; no `Authorization` header at all is `-32504` |
| `scenario-one` | Create → leave unconfirmed → cancel. State `1` then `-1`, both clocks integer `0` while unset, **and the released intent is payable again** — a declined card is not a dead order |
| `scenario-two` | Create → perform → cancel. State `2` with a `perform_time`; `CancelTransaction` on a delivered order is `-31007` and **reverses nothing**; `GetStatement` lists it with THEIR id under `id` and ours under `transaction` |
| `refusals` | `-31001` on a wrong amount; `-31050` for an unknown reference *and* for a real reference under the wrong subfield name; `-31003` for all three operations on a transaction we never created; the order mutex holds against a second transaction; `-32601` echoes an unknown method name; `ChangePassword` is dispatched and refused rather than a `-32601` surprise |

Every scenario also ended with *"the money outcomes, counted in the database"* — the assertion
that matters most, because it is the only one that reads the ledger rather than the wire.

**The worker agreed five minutes later, independently.** At 13:35:00 +05 the settlement
invariant reported `transactions_performed: 1, receipts_written: 1, grants_written: 1`. Equal
and non-zero **is** the assertion: the three counts come from three different tables, and the
sweep is a process that was not involved in the settlement and had no way to be told about it.
That is what makes it corroboration rather than an echo of the harness's own pass table.

Two things about the run are worth keeping:

* **It ran against the real sandbox cashbox**, not the invented key of §6.A in
  [`08-payme.md`](08-payme.md) — the merchant id and TEST_KEY had been installed minutes earlier
  the same afternoon. That was not necessary (see below) but it means the rehearsal and the
  certification slot share one configuration, so nothing about the gateway changes between them.
* **The rehearsal left nothing live behind it.** The `refusals` scenario cancels the transaction
  it opened, and the harness says so in its own output. Rows it wrote carry `is_sandbox=true`.

**This gate reopens on purpose after Gate A.** The rename moves the package, the unit, the env
prefix and every Redis key string in one window; a settlement path proven under `hbd` is not a
settlement path proven under `bayram`. Re-run this with a fresh `--run-id` as the last step of
that cutover — §0.1 explains why the invariant's zeroes will look reassuring again and will not
be.

**That reasoning is now demonstrable rather than argued, and three practical notes come with it.**
`[HOST 2026-09-11]` `payme/harness.py` exists at the identical path in both installed packages and
the two package directories match item for item, so **the re-run is a pure name substitution** —
`sudo -u hbd env BAYRAM_PAYME_ENV_FILE=/etc/bayram/payme.env /opt/bayram/venv/bin/python -m
bayram.payme.harness …`, same flags, same endpoint. What makes it necessary rather than ceremonial
is that the settlement path's **Redis** writes are name-prefixed on both sides — the
`<prefix>-<stage>-<digest>` idempotency keys, whose digest includes the prefix, and
`<prefix>:payme:paused` — while the sweep's corroboration reads three tables through a DSN whose
**database name does not move**. A pass under `hbd` genuinely proves nothing about the wiring under
`bayram`. Then: **the re-run needs an interactive password** (`sudo -u hbd env …` is not in the
NOPASSWD drop-in, §2), and it needs a `--telegram-user-id` and a real phone to watch, so it is the
step of the window that cannot be done by a script at 03:00.

**Why this was the gate to close first, and why the reasoning still stands.** It was the only
open gate with no external dependency. It needs no Payme relationship, no merchant id, no key from anybody: **the merchant
key is only ever compared against itself under `hmac.compare_digest`, so a made-up
36-character string produces a fully functional gateway.** Everything downstream of the auth
check is real — a real intent row through the real ledger, the real one-commit settlement, the
real ARQ enqueue, the real worker, the real Telegram token, a real message. Rows written this
way carry `is_sandbox=true` and are excluded from every revenue figure by construction, which
is why this is safe to run against production.

The alternative — "we will find out during certification" — spends a scheduled slot with
Payme's engineer on the line discovering that our own worker is not draining the notification
queue. That is the failure this gate prevents.

**The command.** It must run as `hbd`, because `/etc/hbd/payme.env` is `0640 root:hbd` and the
harness reads its configuration from the process environment only:

```bash
sudo -u hbd env HBD_PAYME_ENV_FILE=/etc/hbd/payme.env \
  /opt/hbd/venv/bin/python -m hbd.payme.harness \
    --endpoint http://127.0.0.1:8091/payme \
    --login Paycom \
    --key <the key the gateway is running with> \
    --telegram-user-id <your own Telegram id>
```

`--telegram-user-id` is **required** by the parser (`src/bayram/payme/harness.py:1140`) and is
the point of the exercise: it names whose account the rehearsal's credit lands on and who
receives the *"your payment went through"* message. Use your own. `--amount` defaults to
`700000` **tiyin** — 7 000 so'm; nothing in the system multiplies by 100.

Do not pass `--key` if you can avoid it: it puts the cashbox key in your shell history. The
harness falls back to `HBD_PAYME_MERCHANT_KEY` from the env file it was pointed at.

**How to verify it closed.** Three things, in this order, and all three must be true:

1. The harness prints a pass table with no failures.
2. **A Telegram message actually arrived.** The harness can pass while the worker is wedged;
   the pass table asserts the enqueue, the phone asserts the delivery.
3. The invariant stops reporting zeroes:
   ```bash
   ssh aizu 'journalctl -u hbd-worker --since "1 hour ago" -o cat | grep "settlement invariant"'
   ```
   `transactions_performed`, `receipts_written` and `grants_written` must be equal and
   non-zero. **Equal and non-zero is the assertion**; a mismatch is logged at ERROR and is
   never self-repaired, because it would be a defect in the shared write primitive and an
   operator must see it.

**Re-running it.** `--run-id` labels every idempotency key the run writes as
`harness:<run-id>:<scenario>`. Reuse an id **only** to re-run a rehearsal that did *not*
settle: a paid order is terminal and correctly refuses a second payment, so a reused id after
a successful run tests the replay guard rather than the settlement path.

---

## 5. Gate D — Cloudflare is unavoidably in the payment path, and is not configured

**What must be true.** Bot Fight Mode is **off** for `pay.bayrambot.uz` and a WAF skip rule
exempts it, so that no Cloudflare-generated challenge or error page can ever be what Payme
receives.

### 5.1 The correction this gate rests on

An earlier recommendation — run `pay.bayrambot.uz` DNS-only (grey cloud), and enforce the
`185.234.113.0/28` caller allowlist at the origin firewall — **is impossible and is
superseded.** `[HOST 2026-09-09]`:

* Ports 80 and 443 at the origin are **filtered from the internet**. Nothing reaches the box
  directly, so an origin firewall rule filters traffic that was never going to arrive.
* All public traffic arrives through a **remotely-managed Cloudflare tunnel** —
  `cloudflared --no-autoupdate tunnel run --token-file /etc/cloudflared/token`, tunnel
  `aizu-vds`, id `8b799983-8694-479b-98b3-09aaed9b3f8d`. **There is no local `config.yml`**;
  the ingress lives in the Zero Trust dashboard under Networks → Tunnels & Mesh → `aizu-vds`
  → Published application routes. Grepping the host for the routing table finds nothing,
  which is not evidence that there is none.
* A DNS record created by a tunnel route is of type `Tunnel` and is **always proxied**. A
  plain `A` record blocks the route from being saved at all — the `pay` `A` record created on
  the mistaken grey-cloud plan had to be deleted before the route would take.

**Cloudflare's proxy is therefore not optional, and the `-32400` risk it introduces has to be
managed with Cloudflare settings rather than avoided.**

### 5.2 Why a challenge page is worse than an outage

Payme reads **any non-200 as a transport fault**, retries, and we lose the `id` echo. An
outage is survivable: they retry, and `CreateTransaction` / `PerformTransaction` /
`CancelTransaction` are all replay-safe by construction (`PAYME_INTEGRATION` §5). A managed
challenge is not an outage — it is a `403` with an HTML body served *on our behalf*, to a
server-to-server JSON-RPC POST with no browser, no cookie jar and no JavaScript, which will
never solve it. It looks, from Payme's side, exactly like a merchant whose endpoint is broken,
and it will arrive in the middle of a `PerformTransaction` — that is, **after the customer's
card has been charged.** That asymmetry is the whole argument: the bad case is not a lost
payment, it is a payment taken with no receipt on our side.

### 5.3 What to apply, and how to verify

In the Cloudflare dashboard for the zone:

1. **Bot Fight Mode: off** for `pay.bayrambot.uz`. It is a zone-wide toggle with no per-host
   exception, so if it is needed elsewhere, use Super Bot Fight Mode with an allow rule, or a
   WAF skip (below) that outranks it.
2. **A WAF custom rule, action Skip**, matching `http.host eq "pay.bayrambot.uz"`, skipping
   all managed rules, rate limiting and bot management. Narrow it to
   `and http.request.uri.path eq "/payme"` — Caddy already answers `404` to everything else on
   that hostname `[HOST 2026-09-10]`, so the skip needs to cover exactly one path.
3. **Leave the catch-all `http_status:404`** on the tunnel. It is the reason an unregistered
   hostname cannot reach anything.

Verification must come from **off this network**, because the loopback and the tunnel are
different paths:

```bash
# From anywhere on the public internet, several times, ideally from two addresses.
curl -sS -D- -o- -X POST https://pay.bayrambot.uz/payme \
  -H 'Content-Type: application/json' -d '{"method":"CheckTransaction","id":1}'
# Required: HTTP/2 200, a JSON body {"error":{"code":-32504},...}, and NO cf-mitigated header.
# Any HTML body, any 403, or `cf-mitigated: challenge` means this gate is still open.
```

**Who can close it.** Whoever administers the Cloudflare Zero Trust account. It cannot be
closed from the host, and nothing in this repository can check it — which is precisely why it
has its own gate rather than a line in a runbook.

### 5.4 The 308 trap, recorded because it will recur

The tunnel speaks **plain HTTP** to the local port. A Caddy site block written without a
scheme — `pay.bayrambot.uz { … }` — makes Caddy enable automatic HTTPS and answer every
tunnelled request with `308`, redirecting to itself. **Observed.** Payme reads the `308` as
non-200, treats it as `-32400`, and retries forever: an endpoint that curls fine from the
outside, logs nothing on the inside, and can never take a payment.

The fix is the scheme: `http://pay.bayrambot.uz { … }`. `[HOST 2026-09-10]` both the pay block
**and** the admin block now carry it; the admin block was scheme-less on 2026-09-09 and has
since been corrected by the concurrent admin-panel work. Any *new* hostname added to this
tunnel starts with this bug by default.

A second Caddy trap, in the same file: `caddy validate` run under `sudo` **creates**
`/var/log/caddy/payme.log` owned by `root:root`, after which the `caddy` user cannot open it
and `systemctl reload caddy` fails with "permission denied" — and it fails the *whole* reload,
not just that site. The pay block logs to `output stderr` (the journal) for exactly this
reason.

---

## 6. Gate E1 — the paywall stub. DECIDED 2026-09-10: leave it as it is.

**This is a recorded decision with a date, not an oversight, and it must not be re-raised as a
finding.**

**The state.** The paywall is live with the stub rail. Customers see pay and subscribe buttons;
tapping one grants the credit and replies "Paid"; **no money is taken.**
`[HOST 2026-09-10]` the bot warns at every boot — 00:00:45, 00:01:29 and 09:27:36 that day —
that `"the checkout is wired but the credit meter is dark"` with `credits_enforced: false`
(`src/bayram/main.py:392`). That warning is the checkout-side evidence. The render gate is
separately a no-op: `"payment authorised by the no-op provider"`, `amount_minor: 0` — a
different seam (`PAYME_INTEGRATION` §1.1), so read it as a second dark meter rather than as a
sale.

**The decision.** The owner was asked on 2026-09-10 and decided: **leave it as is for now.**
They will say when to accept real payments. Gate F is not a task waiting on engineering; it is
waiting on that sentence.

**Why the code permits this state at all, and only this one.** `src/bayram/main.py:150-160`
refuses to boot a **live** rail over a dark meter — the text is quoted in §8.3 — and the
warning at `:392` is what survives for the **stub** case, deliberately: a deployment that wants
to give songs away must be able to. So the current configuration is the one combination that
is allowed to be quiet, and the boundary has moved rather than blurred. The thing that cannot
happen by accident is the expensive one: a real rail charging into a meter nobody reads.

**What closes this gate.** The owner saying so. Nothing else, and no amount of engineering
readiness substitutes for it.

**How to verify it closed.** The two variables in §8 have moved together and the bot's boot
warning is gone:

```bash
ssh aizu 'journalctl -u hbd-bot --since "10 minutes ago" -o cat | grep -c "credit meter is dark"'   # 0
ssh aizu 'journalctl -u hbd-bot --since "10 minutes ago" -o cat | grep "the checkout rail is live"'
```

---

## 7. Gate E2 — the no-refunds position

**What must be true.** Payme's certifier accepts a merchant that never reverses a performed
transaction — or the business accepts what changing that costs.

**The position, and why it is a decision.** `CancelTransaction` on a performed transaction
answers `-31007` **unconditionally**, which is also PaycomUZ's own template's default. The
reason is not laziness: `credit_accounts.balance` is a single fungible scalar with no lot
structure (`src/bayram/db/plan_sql.py:15`), so an automated reversal of purchase A can debit a
credit the customer paid for in purchase B. An automated refund built on that ledger is a
mechanism for taking away songs people paid for.

A refund is therefore two actions by two systems, money first: refund in the cabinet, then
correct the credit by hand — and if the credit was already **spent**, record the write-off and
stop, because driving the balance negative breaks `credit_sql.verify_balances`, which arm
four of the payme sweep asserts on **every run** — every five minutes as deployed, not hourly —
and you will be paged by your own reconciliation. The full runbook is
[`08-payme.md`](08-payme.md) §7.

**The open question.** `PAYME_INTEGRATION` §6.3: whether Payme will certify a merchant that
never reverses. **If the certifier insists on transaction state `-2`, the answer is
commercial, not technical** — a negotiation, a manual process agreed in writing, or a decision
to build lot-structured credits, which is a schema change and a different quarter's work.

**Who can close it.** The owner, in conversation with Payme's certifier. Not an engineering
ticket, and it should not be turned into one before that conversation happens.

**How to verify it closed.** Certification passes with the behaviour as-shipped; and the first
time it is exercised deliberately, `-31007` appears in the journal:

```bash
ssh aizu 'journalctl -u hbd-payme --since today -o cat | grep -- "-31007"'
```

Seeing it once on purpose, during the Gate F test purchase, is much better than meeting it for
the first time during an incident.

---

## 8. Gate F — the switch-on sequence

Only when A–E are closed. Two dotenv files, two restarts, **no code change**.

> **Names.** This section is written for the host as it stands today — `HBD_*`, `/etc/hbd/`,
> `hbd-*.service`. If Gate A's cutover has already happened, every prefix here is `BAYRAM_`
> and every unit is `bayram-*`; nothing else about the sequence changes. Do not run the two
> operations on the same day (§2).

### 8.1 The gateway's file — `/etc/hbd/payme.env`

```
HBD_PAYME_MERCHANT_KEY=<the PRODUCTION key>     # replacing the TEST_KEY
HBD_PAYME_MERCHANT_ID=<the real кассы id>
HBD_PAYME_IS_SANDBOX=false
HBD_PAYME_CHECKOUT_BASE_URL=                    # cleared, so it derives to checkout.paycom.uz
HBD_PAYME_ACCOUNT_FIELD=<whatever the cabinet says — Gate B item 5>
HBD_PAYME_BASIC_LOGIN=<whatever the -32504 line showed — Gate B item 6>
```

**Stop the gateway before editing, not after.** A running process holds the old key in memory;
editing under it leaves the file and the behaviour disagreeing until something restarts, and
that is the state in which a rotation gets declared done and is not. Downtime here is safe —
Payme retries and every method is replay-safe.

The boot line logs the key's **length**, never its value, so a truncated paste is visible
without the secret ever being printed. There is deliberately no assertion that the length is
36: the documentation says 36, the TEST_KEY's length is unverified, and a wrong length
assertion is a boot failure on go-live day.

### 8.2 The bot's file — `/etc/hbd/hbd.env`

`[HOST 2026-09-09]` the bot and the worker both load `/etc/hbd/hbd.env` via
`EnvironmentFile=`. Three lines, and **the first two move in the same edit**:

```
HBD_CHECKOUT_PROVIDER=payme
HBD_CREDITS_ENFORCED=true
HBD_PAYME_MERCHANT_ID=<the real кассы id>       # public; the BOT builds the checkout link
HBD_KIT_PRICE_AMOUNT_MINOR=0                    # UNCHANGED — this is the render gate's quote,
                                                # not the checkout's
```

**`HBD_PAYME_MERCHANT_KEY` must not appear in this file.** In prod the bot refuses to boot with
it in reach, and so does the admin panel — the panel via `FORBIDDEN_ENV_VARS`
(`src/bayram/admin/app.py:116-118`) widened with `FOREIGN_SECRET_ENV_VARS`. That refusal is what
makes "the Payme endpoint is not a router on the panel" a mechanical fact rather than an
intention.

### 8.3 Why those two variables cannot be moved separately

`src/bayram/main.py:150-160` raises a `ConfigError` at boot:

> `BAYRAM_CHECKOUT_PROVIDER is 'payme' but BAYRAM_CREDITS_ENFORCED is false: a rail taking real
> money into a meter nobody reads sells the song for nothing and charges for it anyway. Set
> BAYRAM_CREDITS_ENFORCED=true in the same edit, or set BAYRAM_CHECKOUT_PROVIDER=stub.`

That message is quoted verbatim from the tree `[TREE 2026-09-10]`, which is why it says
`BAYRAM_` while the dotenv file on the host today says `HBD_` — the message is a literal
string, not derived from `ENV_PREFIX`, so on a host that has not been cut over it names
variables that host does not use. Worth knowing before you spend ten minutes grepping for a
variable that is not there. Read it as "the two flags in §8.2".

It is a refusal rather than a warning because the failure is silent and expensive in exactly
one direction: the customer is shown a price, the money arrives, and the worker then covers
the shortfall with an `UNENFORCED_RENDER` grant and renders anyway — so the song ships whether
or not the payment did, and nothing in the process notices, because the bot-side paywall
deliberately does not read that flag. **Failing the boot in that direction is the point.**

### 8.4 The order, and why it is this order

1. **Restart the gateway first.** `sudo systemctl restart hbd-payme && systemctl is-active
   hbd-payme`. The endpoint must be able to answer before the first link exists. Restarting
   the bot first opens a window in which a customer can be handed a checkout link that reaches
   a gateway still holding the TEST_KEY — every call `-32504`, the customer's card charged by
   Payme, and nothing on our side that knows.
2. **Arm the pause switch before the first customer sees a button**, so it is *known* to work
   rather than assumed:
   ```bash
   sudo -u hbd env HBD_PAYME_ENV_FILE=/etc/hbd/payme.env \
     /opt/hbd/venv/bin/python -m hbd.payme.cli status
   ```
3. **Restart the bot.** `sudo systemctl restart hbd-bot`. Confirm the boot line
   `"the checkout rail is live"` with the real merchant id and `is_sandbox: false`, and confirm
   `"the credit meter is dark"` is gone.
4. **The worker needs no restart for this edit** — the shortfall grant is taken on the bot's
   charge path (`src/bayram/bot/handlers/confirm.py:279`), and leaving the worker running is
   deliberate: it must keep draining the settled-payment notification queue across the
   switch-over.
5. **Buy one song with a real card.** Then refund it in the cabinet and confirm `-31007`
   appears in the journal (§7).

---

## 9. Rollback — arm it before you need it

### 9.1 The full rollback: one variable, one restart

```
HBD_CHECKOUT_PROVIDER=stub
```

then `sudo systemctl restart hbd-bot`. That is the whole of it, and it returns the product to
exactly today's behaviour: the stub is still wired, still constructed and still tested, both
Payme tables are additive and the stub reads neither. `HBD_CREDITS_ENFORCED` may stay `true` —
the refusal in §8.3 fires only on a *live* rail with a dark meter, never the other way round.

**Do not stop the gateway as part of a rollback.** `hbd-payme` is independent of the bot's
provider setting, and that independence is the property that makes rollback safe to perform
*during* a payment: open intents simply stop being created, while any Payme transaction
already in flight still settles correctly. Stopping the gateway converts a clean rollback into
a set of charged cards with no receipts.

### 9.2 The soft stop: pause, with no restart at all

```bash
sudo -u hbd env HBD_PAYME_ENV_FILE=/etc/hbd/payme.env \
  /opt/hbd/venv/bin/python -m hbd.payme.cli pause
```

It writes one Redis key that `PaymeCheckoutProvider.charge` reads — the bot-side half, the code
that opens an intent and hands a customer a link. **It is deliberately never consulted on an
inbound `PerformTransaction`, and that is not an oversight to be tidied up later for
symmetry.** Refusing money that is already in flight is how an incident becomes a dispute: the
card has been charged, the rail is holding funds it believes are ours, and a merchant who
answers `-31008` to that has not prevented a bad sale — it has produced a payment with no
receipt, no credit and no automatic way back, since `CancelTransaction` on a performed
transaction is `-31007` by design. **The correct shape of "stop taking money" is to stop
quoting it, and to settle every quote already given.**

Three honest caveats, all of them recorded in the module itself rather than dressed up:

* **A read that fails is not a pause.** `is_paused` logs at WARNING and answers `False` when
  Redis is unreachable. This looks wrong and is not: the population the switch protects is
  "sales we would rather not take for the next twenty minutes"; the population failing closed
  would destroy is "every sale, for as long as Redis is unwell". **It follows that this switch
  is not a security control and must never be relied on as one.**
* **A write that fails is loud.** `set_paused` raises rather than swallowing, because the
  operator typing `pause` is about to go and do something on the strength of believing the
  rail is shut.
* **A Redis rebuild silently un-pauses the rail.** The key has no TTL, but Redis is a cache in
  this deployment: a restart with no persistence, a `FLUSHDB`, or eviction under `maxmemory`
  all clear it and nothing says so. The compensating control is procedural — re-check the
  switch after any Redis restart, with `cli status` **or** on the admin console's rail header
  (§11), which reads the same key through the same function — and it is weaker than a durable
  flag, which would need a migration, a schema and a database read on a checkout path that
  currently touches none. **The console does not close this hole and does not claim to**: it
  renders both caveats permanently beside the switch, because a rail that reads "open" after an
  eviction reads exactly like a rail that was never paused.
  Add Gate A's key-rename hazard to that list: after §2's cutover, a pause set by the old code
  is invisible to the new, because the key itself was renamed.

---

## 10. What is deliberately *not* a gate

Each of these is open, known, and does **not** block taking money. They are listed so that
nobody rediscovers one the week of go-live and treats it as a blocker.

* **`HBD_PAYME_RETURN_URL` is blank.** Settlement is webhook-driven; nothing depends on the
  return redirect. If it is ever set, the only value the bot can answer is
  `https://t.me/<bot_username>?start=paid` — `handle_paid_return` is registered for the payload
  `paid` alone and it redraws the balance from the meter, claiming nothing. It belongs in the
  **bot's** dotenv, since the bot builds the link.
* **`receivers` is not emitted, and `SetFiscalData`/IKPU is not implemented.** Neither is
  required to take a payment. Both become required the day the business needs split settlement
  or fiscalisation, and that is a scoped piece of work, not a switch.
* **No post-perform reversal.** §7 above; a decision with a written reason.
* **No throttle and no alarm on the gateway.** This increment ships the diagnostic half — the
  RPC journal, the three-way invariant on every sweep, the `-32504` log line — but nothing rate-limits
  a burst and nothing pages anybody. **Key rotation is therefore the mitigation**, and the key
  is the only thing between the public internet and an unlimited credit mint: rotate on any
  suspicion at all ([`08-payme.md`](08-payme.md) §8). A burst-of-`-32504` alarm and an hourly
  grant-rate ceiling are worth a follow-up and are not worth delaying go-live for.
* **Three of the four unit files in `deploy/systemd/` describe a machine that does not exist.**
  `[TREE 2026-09-11]` `bayram-bot.service:24-28` and `bayram-worker.service:17-21` name
  `User=bayram`, `WorkingDirectory=/srv/bayram` and `/srv/bayram/.venv/bin/python` with
  `Environment=BAYRAM_ENV_FILE=/etc/bayram/bot.env`; `bayram-admin.service:26-30` names the same
  `/srv/bayram` venv with `Environment=BAYRAM_ADMIN_ENV_FILE=/etc/bayram/admin.env`.
  `[HOST 2026-09-11]` **`/srv` is empty** and `/srv/bayram` does not exist; the running units use
  `/opt/hbd/venv`, `WorkingDirectory=/var/lib/hbd` and plain `EnvironmentFile=/etc/hbd/hbd.env`.

  **One part of this bullet has been overtaken and it is worth saying which.** Only the payme unit
  was ever corrected against the host (commit `24bbeeb`), and this page recorded that the rename
  had carried even that one out of sync by making it name `/opt/bayram/venv`. **It has not:**
  `[HOST 2026-09-11]` `/opt/bayram/venv` now exists and is where the `bayram` package is actually
  installed, left behind by the aborted cutover — so that line is *correct* and it is the
  `User=bayram`, `Group=bayram` and `WorkingDirectory=/var/lib/bayram` lines that are still wrong
  (no `bayram` user or group exists; `/var/lib/bayram` does not exist). `08-payme.md` §2 has the
  line-by-line. The service account **does not move, by decision** — the host's own cutover script
  keeps `User=hbd` because that account owns the media archive and renaming it means chowning
  customer artefacts inside a cutover window — so those three lines are wrong in the direction of
  a change nobody intends to make.

  The other three are left disagreeing **on purpose**: they describe an intent the running
  units do not implement — secrets reached through an `*_ENV_FILE` variable rather than
  `EnvironmentFile=`, so they never enter the process environment — and quietly rewriting them
  to match reality would delete that argument without anybody deciding to drop it. Close the
  gap by *changing the host*, or by superseding the intent in writing. Editing the file to
  agree with what is running is the one move that loses information.
* **The bot's and the panel's secrets are in the process environment.** `[HOST 2026-09-09]`
  the three original units load `EnvironmentFile=/etc/hbd/hbd.env` (bot and worker) and
  `/etc/hbd/hbd-admin.env` (admin), so `HBD_TELEGRAM_BOT_TOKEN` and the vendor keys are
  readable from `/proc/<pid>/environ` by anything that can read the process. **The gateway is
  the exception**: `[HOST 2026-09-10]` its unit carries `Environment=HBD_PAYME_ENV_FILE=` and
  no `EnvironmentFile=`, so the cashbox key is read by the application from a file it opens
  itself and never enters the environment. That asymmetry is intended — it is the whole reason
  the indirection exists — and it means the one credential whose theft mints credits is the
  one credential not sitting in an environment block. Extending the same shape to the other
  three is a separate change with its own downtime, and it is not a go-live gate.

---

## 11. The admin console as an operator surface — new on 2026-09-10

**Until this landed, `python -m bayram.payme.cli` was the only way to look at or touch the
rail.** It is no longer the only way to *look*, and it is no longer the only way to press two
of the five buttons. It is still the only way to press the one that matters most. This section
says which is which, so that nobody goes hunting in the console for `settle` and concludes the
page is broken.

The section is specified by `BILLING_RAIL_BOARD` — §2 the three switches and which the panel
can see, §5 the settlement identity, §8 what the board says while the rail is off. Why the line
between the console and the terminal falls where it does is
[`../decisions/DECISIONS.md`](../decisions/DECISIONS.md) **D14**.

### 11.1 What the console now covers, and what it does not

| CLI command | In the console? | Why |
| --- | --- | --- |
| `pause` | **Yes** — `POST /api/ops/rail/pause`, OWNER and ADMIN | Same Redis key, same `set_paused`. §11.2 |
| `resume` | **Yes** — `POST /api/ops/rail/resume`, OWNER and ADMIN | ″ |
| *notify one intent* | **Yes** — `POST /api/billing/intents/{id}/notify`, and SUPPORT has it | SUPPORT takes the "I paid and nothing happened" call; the action re-enqueues a message the customer was already owed, writes no money row, and is collapsed by a deterministic ARQ job id |
| `journal`, `statement` | **Read-only, and better** | The paged calls journal and the per-payment dossier render the same rows with the joins already done. The CLI forms remain, and remain correct. **One qualification as of 2026-09-11**: the *fault clusters* band named here was removed from the console on the operator's instruction (`BILLING_RAIL_BOARD`'s amendment) — the route is still mounted and still answers, it simply has no caller, so for fault clustering the CLI and `journalctl` are again the only readers |
| `settle` | **NO. Deliberately.** | D14. The dossier renders the exact invocation as copyable text with **no submit path**, beside the cabinet reference the operator has to check first |
| `reconcile` | **NO.** | It runs the sweep's arms against the *gateway's* own container, which the admin process cannot construct — and `run_payme_sweep` already runs it every five minutes on both the healthy and the mismatched path. A read must not be a POST |

**The single most important sentence in this section:** the console can display every fact about
a payment **except** the one that authorises a force-settle — a charge in the Payme merchant
cabinet. `src/bayram/admin/app.py::derive_forbidden_env_vars` refuses to boot the panel in prod
if `BAYRAM_PAYME_MERCHANT_KEY` is reachable, which is the mechanism that keeps the gateway a
fourth process (**D11**, and `PAYME_INTEGRATION` §1.2). That is not an omission to be closed later;
it is the boundary working.

### 11.2 The pause switch now has two writers, and that is deliberate

`python -m bayram.payme.cli pause` and the console's pause button both call
`bayram.payme.pause.set_paused` against the one key, `bayram:payme:paused`, and both readers —
the console's header and the bot's `PaymeCheckoutProvider.charge` — both call
`bayram.payme.pause.is_paused`. **Two writers, one mechanism.** It must never become two
mechanisms: a second key, a database column shadowing the Redis flag, or a settings field the
panel reads instead would give two answers to "is the rail paused", and the answer that matters
is whichever one the bot's checkout path actually consults.

Two consequences follow, and §9.2's caveats apply unchanged to both surfaces:

* **A Redis rebuild silently un-pauses the rail, and the console cannot tell you it happened.**
  The key has no TTL, but Redis is a cache here; a restart with no persistence, a `FLUSHDB` or
  an eviction under `maxmemory` all clear it. The console renders "checkouts open", which is
  true, and is indistinguishable from a rail that was never paused. Re-check after any Redis
  restart — that step in §9.2 is not retired by the console, only made cheaper.
* **A Redis that cannot be reached reads as OPEN, in the console and in the bot alike.** The
  console does *not* render an UNKNOWN state, because `is_paused` never raises and answers
  `False` on a failed read, and a panel that reported UNKNOWN would be reporting a distinction
  the runtime does not make. It reports what the bot would see, with both caveats permanently
  beside the switch (`BILLING_RAIL_BOARD` §2.2).

The write half is not symmetric: `set_paused` **raises** on a failed write and the panel
surfaces that as a 503 rather than a silent success, because an operator who typed `pause` is
about to go and do something on the strength of believing the rail is shut. The response then
re-reads the key, so what the header shows is the switch **as stored**, never as requested.

Gate A's hazard applies here too and is worth restating in this context: after the rename
cutover (§2), a pause set by the old code is invisible to the new, **because the key string
itself is renamed** — and now there are three things reading it rather than two.

### 11.3 What the board shows today, and why that is the point

**Two things have overtaken this subsection since it was written on 2026-09-10, and it is kept
because the reasoning in it is what the next empty screen should inherit.**

**First, the tables are no longer empty.** `[HOST 2026-09-11]`: `payment_intents` 7,
`payme_transactions` 3, `payme_rpc_log` 53, `topup_purchases` 6, `credit_ledger` 18 — the
residue of the Gate C rehearsal (§4) and of the routing probes before it. Every sentence below
that begins *"no checkout ever opened here"* or *"last heard from Payme: none, ever"* has
therefore stopped being what the screen says. **The settlement card's `never_settled` verdict has
also stopped applying**, which is the point of it: it was never a green tick and it was always
going to flip the first time something settled.

**Second, the bands that printed these sentences were removed from the console**, on the
operator's instruction that the screen carried too much prose for a rail that had never sold —
`BILLING_RAIL_BOARD`'s amendment of 2026-09-10 records it. `/billing` is now the payments list,
its filter panel, the reference lookup and the pause switch. The aggregate routes are still
mounted and still answer; they simply have no caller in the console.

What the subsection said, and why it is worth keeping: the board showed *no checkout ever opened
here*, *merchant never recorded*, *checkouts open*, *gateway daemon: not readable from this
process*, *last heard from Payme: none, ever*, and **`never_settled`** as a sentence and a legend
rather than a balanced green tick — for the same reason §0.1 gives about the sweep's three zeroes.
Nothing disagreed because nothing had happened.

**And the state it predicted as "next" never arrived, which is instructive.** The prediction was
*inbound RPC rows with no payment intents at all* — the gateway answering correctly about a shop
that is not open — and `BILLING_RAIL_BOARD` §8.2 named it `armed_but_idle`. What actually happened
is that the rehearsal of 2026-09-10 wrote inbound calls **and** intents **and** a settlement inside
the same afternoon, so the deployment stepped over that state in one move. A screen whose verdict
ladder is built around the state a deployment passes through in ninety minutes is a screen built
around the wrong thing; the durable distinction was never *"calls but no intents"*, it was
**sandbox versus real**, which no verdict in that ladder reads. `BILLING_RAIL_BOARD` §8.2 carries
that correction.

### 11.4 The console is not a gate

Nothing on this page waits on it. It closes no gate in §1.3, it is not required for Gate C's
rehearsal — which is driven by the harness and read out of `journalctl` — and it is not
required for Gate F. What it changes is what happens **after** Gate F: the first week of real
payments is the first week anybody has looked at this data through anything but `psql` and the
CLI, and D14's own confidence note says that week should be read as a review of the screen's
choices rather than a confirmation of them.

### 11.5 What the cutover does to the operator sitting in front of this console

**New on 2026-09-11, and new to this tree: the rename cutover logs every admin out, and §11 has
just made this console the surface the runbook sends them to.** That combination is worth one
subsection, because an operator who reaches for the pause switch during the window finds
themselves signed out with no explanation at exactly the moment they were told to go and look.

`[HOST 2026-09-11]`, read out of the two installed wheels:

| What moves | From | To |
| --- | --- | --- |
| the session mirror prefix (`admin/sessions.py:80`) | `hbd:admin:session` | `bayram:admin:session` |
| the CSRF cookie (`admin/csrf.py:58`) | `__Host-hbd_csrf` | `__Host-bayram_csrf` |
| the session cookie (`settings.py:650`) | `__Host-hbd_session` | `__Host-bayram_session` |
| per-browser state | `hbd.dashboard.{locale,theme,navRailCollapsed,rememberedUser}`, `hbd.admin.bootstrap`, the `hbdBot` window global | the `bayram.*` / `bayramBot` twins |

So at the cutover **every admin session ends and every CSRF token in every open tab is voided**,
and theme, locale, nav-rail state and remembered username are lost. Nothing else is: the money
rows are untouched, and the audit log is untouched.

Three things to do with that, in order of how much they cost:

1. **Say so before the window.** A failed POST mid-task reads as a broken panel; "you will be
   logged out at 00:01, sign in again" costs one sentence.
2. **Do not use the console as the pause surface during the cutover.** §2 step 1 checks the switch
   and step 7 re-arms it, and both should be the CLI, which authenticates against the gateway's
   own dotenv rather than a session cookie.
3. **Do not hand-copy a `static/` directory across the cutover.** The served shell carries
   `__HBD_CSP_NONCE__` and the server substitutes `CSP_NONCE_PLACEHOLDER`
   (`admin/shell.py:55`, raising at `:78` when it is absent); both wheels are internally
   consistent, so the coupling is atomic **with the wheel** and breaks the console with a
   nonce-less CSP if the bundle and the server are mixed. `08-payme.md` §11.6 carries this row in
   the inventory.

**One thing this subsection deliberately does not claim.** An earlier draft of this finding said
there was a live admin session in Redis that the cutover would kill. `[HOST 2026-09-11]` there is
not — Redis holds five keys and no `*admin*` key among them, so nobody is signed in right now. The
**mechanism** is confirmed in both wheels and survives; the "there is a live one" evidence decayed
inside twenty hours and has no business in a runbook as a standing fact.
