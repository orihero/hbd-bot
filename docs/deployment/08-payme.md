# The Payme gateway — the fourth process

Provisioning, releasing, operating and debugging `hbd-payme.service`: the JSON-RPC endpoint
Payme calls to tell us a customer paid. It is the **only inbound HTTP surface in this system
that is reachable from the public internet without a login**, and the only process that holds
the Payme cashbox key.

What it is *for* is [`../product/PAYME_INTEGRATION.md`](../product/PAYME_INTEGRATION.md), cited
by section (`PAYME_INTEGRATION §3`). Why it exists at all is
[`../decisions/DECISIONS.md`](../decisions/DECISIONS.md) **D11**. This page is only how it runs
on a host.

> **UNVERIFIED, like every page in this tree.** Nothing here was checked against `aizu`. Every
> claim about the code carries a `file.py:line` you can open; every claim about the host is
> written as a placeholder for you to fill in or as a question to answer on the box.
> `deploy/systemd/hbd-payme.service` is a **proposal** authored in this repository, exactly as
> the other three unit files are, and it borrows their `/srv/hbd` + systemd shape for want of
> anything better. Two host facts this page needs do not exist anywhere yet and are rows 37
> and 38 of [`00-host-inventory.md`](00-host-inventory.md), left empty on purpose.

> **It ships switched off.** `HBD_PAYME_ENABLED` defaults to `false` and the lifespan refuses
> to start without it; `HBD_CHECKOUT_PROVIDER` defaults to `stub`, so the bot issues no links.
> Installing this unit changes nothing a customer can see. That is deliberate: everything below
> can be rehearsed on the host before Payme has heard of us.

---

## 1. What this process is, and what it must never be

### 1.1 One credential, and it is a different kind of credential

The bot and worker hold four **outbound** credentials — a Telegram token and three vendor keys
— whose theft lets somebody impersonate us or spend our balance. The admin panel deliberately
holds none. This process holds exactly one secret, `HBD_PAYME_MERCHANT_KEY`, and it is an
**inbound verification** secret: it is only ever compared against itself, in
`hmac.compare_digest`, to decide whether an incoming request really came from Payme. Its theft
mints credits. That is a third blast radius, distinct from both of the others, and it is why
this is a fourth container rather than a route somewhere.

Two consequences follow, and both are enforced rather than documented:

* **This process holds no Telegram token.** Telling a customer their payment landed is
  therefore an ARQ job the worker performs — the same rule every other credentialled action in
  this system follows.
* **The panel and the bot must not hold this key.** In prod each refuses to boot with
  `HBD_PAYME_MERCHANT_KEY` in reach, the panel via `FORBIDDEN_ENV_VARS`
  (`src/hbd/admin/app.py:116-118`) widened with `FOREIGN_SECRET_ENV_VARS`. That refusal is what
  makes "the Payme endpoint is not a router on the panel" a mechanical fact.

### 1.2 Three routes, and every reply is HTTP 200

| Route | Purpose |
| --- | --- |
| `POST /payme` | The Merchant API. Everything. |
| `GET /healthz` | Bare 200. Touches no container and answers even if the lifespan never ran. |
| `GET /readyz` | A constant `{"status":"ok"}` unless `X-Probe-Token` matches under `compare_digest`. |

**Every reply on `/payme` is HTTP 200 — bad auth, unparseable body, unknown method, and any
unhandled exception alike.** Payme reads any other status as a transport fault, retries, and
we lose the `id` echo. So the gateway installs its own exception middleware and never reuses
the panel's `install_error_handlers`, whose `{"error":{code,message,correlationId}}` envelope
at 422/405/500 would read to Payme as `-32400` on every error path.

**If your terminator has an error page, it must not serve one for this route.** A 502 from the
proxy while the gateway restarts is indistinguishable, from Payme's side, from us being broken
— which is survivable (they retry) — but a proxy that rewrites a 200 body, adds a JSON
wrapper, or gzips a response the client did not ask for is not. Pass the body through
unaltered.

---

## 2. The unit, and where the secret comes from

```ini
# deploy/systemd/hbd-payme.service — a proposal, not a record
Environment=HBD_PAYME_ENV_FILE=/etc/hbd/payme.env
ExecStart=/srv/hbd/.venv/bin/python -m uvicorn hbd.payme.app:app --host 127.0.0.1 --port 8091
RestrictAddressFamilies=AF_INET AF_INET6 AF_UNIX
InaccessiblePaths=/etc/hbd/bot.env /etc/hbd/admin.env
```

Four lines carry an argument each.

**`--host 127.0.0.1`.** The bind is on the command line; nothing in the package binds a socket.
Binding `0.0.0.0` publishes an unauthenticated POST endpoint to the entire internet with only
Basic auth in front of it and no TLS at all.

**`Environment=HBD_PAYME_ENV_FILE=…`, not `EnvironmentFile=`.** Secrets arrive through the
env-file *variable*, for the reason `hbd-bot.service` already gives: with `EnvironmentFile=`
they appear in `/proc/<pid>/environ`, readable by anything that can read the process.
`HBD_PAYME_ENV_FILE` is a **second variable rather than a tier shared with `HBD_ENV_FILE`**,
following the rule stated at `src/hbd/admin/settings.py:69-74` — *"one knob deriving both paths
would be one edit away from pointing them at the same file"*, and the whole point of this
process is that it reads a different file from the bot and the worker. Read from the process
environment only, never from a dotenv, because a dotenv cannot name itself.

**`InaccessiblePaths=`.** The application-level refusal (§1.1) is a check this process performs
on itself; this one is the kernel's, and it survives a future edit that points
`HBD_PAYME_ENV_FILE` at the wrong file. Belt and braces, exactly as `hbd-admin.service` does.

**No `ReadWritePaths=`.** This process writes no files. It renders nothing, transcodes nothing
and stores nothing; `ProtectSystem=strict` with no writable path is therefore correct rather
than merely tidy.

One more deliberate absence, documented in `hbd/payme/app.py`'s module docstring so nobody
"fixes" it: **`hbd.runtime.startup.verify_host` is not called.** The gateway renders nothing,
speaks no locale to a customer and needs no ffmpeg. Running it would let a payment endpoint
refuse to boot over an i18n catalogue.

### 2.1 `/etc/hbd/payme.env`

Mode `0600`, owned by the service user. The authoritative list of variables is
`.env.payme.example` in the repository root, which carries one commented block per field; the
table below is the operator's short form.

| Variable | Set on the gateway? | Notes |
| --- | --- | --- |
| `HBD_PAYME_ENABLED` | **yes**, `true` | The lifespan refuses to start on `false`. |
| `HBD_PAYME_MERCHANT_KEY` | **yes, and nowhere else** | The cashbox key. The TEST_KEY during certification, the production key after. |
| `HBD_PAYME_MERCHANT_ID` | yes | Public. Also on the bot (§5.2) — the gateway compares it against `payment_intents.merchant_id` and refuses a mismatch with `-31055`. |
| `HBD_PAYME_BASIC_LOGIN` | yes | Defaults to `Paycom`. Inferred; see `PAYME_INTEGRATION` §7.1. |
| `HBD_PAYME_ACCOUNT_FIELD` | yes | **Must equal the cabinet's «Настройка Аккаунт» field name exactly** (§5.1). Defaults to `order_id`. |
| `HBD_PAYME_DUPLICATE_TRANSACTION_CODE` | yes | Defaults to `-31008`. Inferred; see `PAYME_INTEGRATION` §7.2. |
| `HBD_PAYME_IS_SANDBOX` | yes | `true` until go-live. Stamped onto every intent, so sandbox rows are excludable from revenue by construction. |
| `HBD_DATABASE_URL` | yes | As `hbd_app`, never the owner role (§3.2). |
| `HBD_REDIS_URL` | yes | For the ARQ enqueue that notifies the customer. |
| `HBD_ENVIRONMENT` | yes | `prod` enables the vendor-credential refusal. It is an exact `== "prod"` string comparison. |
| `HBD_TELEGRAM_BOT_TOKEN` | **never** | The lifespan refuses in prod if it, or any other name in `hbd.config.REQUIRED_VENDOR_SECRET_FIELDS`, is reachable. |

Belt-and-braces check after any edit, which prints no secret value:

```bash
ssh aizu 'sudo stat -c "%n mode=%a owner=%U:%G" /etc/hbd/payme.env;
          sudo grep -c "^HBD_PAYME_MERCHANT_KEY=.\+" /etc/hbd/payme.env;
          sudo grep -lE "^HBD_(TELEGRAM_BOT_TOKEN|ELEVENLABS_API_KEY|LLM_API_KEY|LLM_FALLBACK_API_KEY)=" /etc/hbd/payme.env || echo "no vendor credential in the payme env file — correct"'
```

---

## 3. Postgres: the connection arithmetic and the role

### 3.1 The arithmetic, recorded so the fifth process has to re-argue it

Do the arithmetic here once, in writing, so that the **fifth** long-running process has to
re-argue it rather than inherit it.

`src/hbd/db/engine.py:40-41` sets the defaults `pool_size=10, max_overflow=20` — at most 30
connections per process. The docstring at `:64-67` states the hypothetical that motivated the
two arguments: bot + worker + admin API *at the defaults* would be `3 × 30 = 90` against a
stock `max_connections` of 100, "so the API asks for a smaller share rather than everyone
quietly sharing a cliff edge". It does: `ADMIN_POOL_SIZE = 5`, `ADMIN_MAX_OVERFLOW = 5`
(`src/hbd/admin/container.py:53-54`).

So the fleet's real ceiling today is **30 + 30 + 10 = 70**, not 90. **The gateway asks for
`pool_size=3, max_overflow=2` — at most five — taking it to 75** against a stock 100. No host
change is required, and the margin is real rather than nominal.

Read `engine.py:64-67` carefully before quoting it: `3 × 30 = 90` is the number the third
process was built to *avoid*, not the number the fleet asks for. Anybody sizing a fifth pool
off that sentence will believe there are five connections of headroom when there are
twenty-five.

Why five is enough for a payment endpoint when the bot needs thirty: every method here is one
short database transaction with no vendor call, no Telegram call and no HTTP of its own, and
Payme is a single caller making sequential requests about individual transactions — not a
crowd of customers.

Confirm the server's actual ceiling before installing, because a value of 100 is an assumption
about a host nobody here has seen (row 11 of [`00-host-inventory.md`](00-host-inventory.md)):

```bash
ssh aizu 'sudo -u postgres psql -Atc "show max_connections"; sudo -u postgres psql -Atc "select count(*) from pg_stat_activity"'
```

### 3.2 The role, which is a deployment check and not an assumption

The gateway connects as **`hbd_app`**, the application role from `docker-compose.yml`'s
two-role split — never the owner role `hbd`. The split exists so that privileges can be revoked
from the application and have that stick: an owner can `GRANT` back its own revocations, so a
one-role deployment cannot protect anything with privileges at all.

Migration `0023`'s three tables are created by the owner and inherit that role's default
grants. **Whether `hbd_app` can actually read and write them is a fact about the host's
`ALTER DEFAULT PRIVILEGES`, not a fact about this repository**, and the failure mode is ugly:
the gateway boots, answers `/healthz`, and then returns `-32400` on every real method because
each transaction dies on `permission denied for table payment_intents`. Check it explicitly
after migrating, before pointing Payme at anything:

```bash
ssh aizu 'sudo -u postgres psql -d hbd -Atc "
  select table_name, privilege_type from information_schema.role_table_grants
   where grantee = '"'"'hbd_app'"'"'
     and table_name in ('"'"'payment_intents'"'"','"'"'payme_transactions'"'"','"'"'payme_rpc_log'"'"')
   order by 1,2"'
```

Expect `SELECT`, `INSERT`, `UPDATE` on all three (`DELETE` too, for the purge job). An empty
result is the problem, and the fix is a `GRANT` plus an `ALTER DEFAULT PRIVILEGES` so the next
migration does not reproduce it.

---

## 4. The TLS terminator contract

Nothing in this repository terminates TLS, emits HSTS, or filters by source address. Every line
in this section is work the terminator does, and none of it can be verified from here.
[`00-host-inventory.md`](00-host-inventory.md) row 17 (what terminates TLS) is empty and rows
37–38 are the two new ones this page needs.

The contract, in full:

1. **One dedicated hostname, not the admin panel's.** The panel must be "the only reachable
   name" at its origin — both its cookies are `__Host-` prefixed and un-narrowable, and its
   CSRF check compares `HBD_ADMIN_PUBLIC_ORIGIN` exactly. Sharing a name is how a payment
   endpoint's error page ends up inside the panel's origin.
2. **`POST /payme` proxied to `127.0.0.1:8091`.** Nothing else from the outside needs to reach
   this process. `/healthz` and `/readyz` are for the local monitor.
3. **TLS ≥ 1.2.**
4. **HTTP 200 bodies passed through unaltered** — no error page substitution, no body
   rewriting, no added JSON envelope (§1.2).
5. **The caller allowlist is enforced HERE.** Payme originates from `185.234.113.1` –
   `185.234.113.15` (`185.234.113.0/28`).
6. **Payme's own recommended tuning:** SSL session cache ~1 MB, session timeout ≥ 10 minutes,
   keepalive ≥ 10 minutes. Their client reconnects frequently and a cold handshake per call is
   latency we are not obliged to pay.

### 4.1 Why the allowlist is not in the application

`payme_allowed_cidrs` exists and defaults to **empty**, and is honoured only when
`payme_trusted_proxy_hops > 0`. With zero hops the application sees the *proxy's* address, so a
filter would match the wrong address and refuse every genuine Payme call while accepting
anything that reached the proxy — **a filter matching the wrong address is worse than no
filter**. `src/hbd/admin/security/clientip.py` learned this already, and at that module's
shipped defaults every audit row records the proxy's address rather than the operator's.

What the application does instead, unconditionally: **every request logs its peer IP**. So the
real caller set is discoverable from our own journal, and the allowlist can be built from
observation rather than from a documented range that may change:

```bash
ssh aizu 'journalctl -u hbd-payme --since "7 days ago" -o cat | grep -o "\"peer_ip\": *\"[^\"]*\"" | sort | uniq -c | sort -rn'
```

---

## 5. What to enter in the Payme cabinet

Three values are entered by a human into a web form, and **two of them can silently break every
payment**.

### 5.1 «Настройка Аккаунт» — the account field name

The cabinet declares the account field set in a form; there is no API for it and nothing in
this repository can validate it before the cabinet exists. It must equal
`HBD_PAYME_ACCOUNT_FIELD` **exactly** — we ship `order_id`.

If they disagree, every `CheckPerformTransaction` is a `-31050`, every payment fails, and it
looks like our bug. That is why the `-31050` log line records the account subfield names
actually **received** alongside the one expected:

```bash
ssh aizu 'journalctl -u hbd-payme --since today -o cat | grep -- "-31050" | tail -5'
```

One line of that journal settles it. Fix it in the cabinet, or change the variable and restart
— whichever is faster on the day; they are equivalent.

### 5.2 Endpoint URL, and where the merchant id goes

* **Endpoint URL**: `https://<the hostname from row 37>/payme`. Register it in the cabinet.
* **Merchant id (кассы id)**: public. It goes in `/etc/hbd/bot.env` as `HBD_PAYME_MERCHANT_ID`,
  because the **bot** builds the checkout link, and in `/etc/hbd/payme.env` as well, because the
  gateway compares it against the intent's stored `merchant_id` and answers `-31055` on a
  mismatch. That column is what makes a sandbox/production or second-cashbox split-brain a
  refusal instead of a customer charged by the wrong cashbox.
* **Both keys (TEST_KEY, production key)**: secret. They go **only** in `/etc/hbd/payme.env`,
  one at a time.

All three come from Кассы → the kassa → Настройки → Инструменты разработчика.

---

## 6. Certification runbook

Do these in order. Stages A and B need no Payme relationship at all and should be finished
before the certification slot is booked.

### A. Rehearse on the host with an invented key

The merchant key is only ever compared against itself, so a made-up 36-character string makes a
**fully functional gateway**.

1. `HBD_PAYME_ENABLED=true`, `HBD_PAYME_IS_SANDBOX=true`, an invented key, an invented merchant
   id in `/etc/hbd/payme.env`. `HBD_CHECKOUT_PROVIDER` stays `stub` — the bot issues nothing.
2. `systemctl start hbd-payme`, then `curl -sS -o /dev/null -w '%{http_code}\n'
   http://127.0.0.1:8091/healthz` → `200`.
3. `python -m hbd.payme.harness --endpoint http://127.0.0.1:8091/payme --login Paycom --key
   <that key>`. It replays Payme's two published sandbox scenarios against the running process
   and prints a pass/fail table. This exercises the real database, the real ARQ enqueue, the
   real worker notification and **a real Telegram message** — the whole settlement path up to
   the customer seeing "your payment went through" — before Payme has heard of us.
4. Rows created this way carry `is_sandbox=true` and are excluded from every revenue figure by
   construction.

### B. Prove the link against Payme's own parser, still with no credential

`https://test.paycom.uz/<base64>` echoes the parsed receipt as JSON with **no authentication**.
On a dev machine, with `HBD_CHECKOUT_PROVIDER=payme`, an invented merchant id and
`HBD_PAYME_CHECKOUT_BASE_URL=https://test.paycom.uz`, walk the customer path: a real intent row
is written, a real link is built, rendered under a real 🔗 button, and tapping it reaches
Payme's sandbox, which parses our receipt and echoes back the merchant id, every account
subfield, the tiyin amount, the language and the untruncated callback.

With an invented merchant id the sandbox stops at **«Поставщик не найден»**. That is the
correct answer and the last thing that changes at go-live.

### C. Sandbox certification, the day the cabinet exists

1. **First**, declare the account field name in the cabinet and register the endpoint URL
   (§5). Doing this first is what stops the slot being spent diagnosing `-31050`.
2. TEST_KEY into `/etc/hbd/payme.env`; `HBD_PAYME_ENABLED=true`; restart.
3. Run Payme's sandbox UI against us, and close the three inferred facts
   (`PAYME_INTEGRATION` §7) — each is an environment value and a restart, never a release:
   read the real Basic-auth login off the first `-32504` log line;
   flip `HBD_PAYME_DUPLICATE_TRANSACTION_CODE` until the duplicate-transaction scenario passes;
   confirm integer-`0` times are accepted.
4. Do the manual iOS and Android test of the `t.me` return redirect here. **Nothing depends on
   it** — settlement is webhook-driven and `HBD_PAYME_RETURN_URL` defaults to blank. If you do
   set it, the only value the bot can answer is `https://t.me/<bot_username>?start=paid`:
   `hbd.bot.handlers.start.handle_paid_return` is registered for the payload `paid` alone, and
   it redraws the balance from the meter and claims nothing. It goes in the BOT's dotenv, since
   the bot is what builds the link; the gateway's copy is read only by the CLI and the harness.
5. Drive the 12-hour timeout branch by shrinking the transaction-timeout setting to seconds; it
   is a setting rather than a constant for exactly this.

### D. Production — two restarts, no code change

1. Production key into `/etc/hbd/payme.env`; `HBD_PAYME_IS_SANDBOX=false`;
   `HBD_PAYME_CHECKOUT_BASE_URL` cleared so it derives to `checkout.paycom.uz`; the real
   `HBD_PAYME_MERCHANT_ID` into `/etc/hbd/bot.env`.
2. `HBD_CHECKOUT_PROVIDER=payme` **and** `HBD_CREDITS_ENFORCED=true` in the **same edit** —
   `src/hbd/main.py` refuses to boot on a live rail with a dark credit meter, so they cannot be
   moved separately. `HBD_KIT_PRICE_AMOUNT_MINOR` stays `0`; it is the render gate's quote, not
   the checkout's.
3. Restart the gateway, **then** the bot. In that order: the endpoint must be able to answer
   before the first link exists.
4. Arm the pause switch (`python -m hbd.payme.cli status`) before the first customer sees a
   button, so it is known to work rather than assumed.
5. Buy one song with a real card. Then refund it in the cabinet and confirm the `-31007`
   refusal appears in the journal — that is the designed behaviour (§7), and seeing it once
   deliberately is better than meeting it during an incident.

---

## 7. The manual-refund runbook

**There is no automated refund, by decision** — `CancelTransaction` on a performed transaction
answers `-31007` unconditionally, which is also PaycomUZ's own template's default behaviour.
The reason is in `PAYME_INTEGRATION` §6: `credit_accounts.balance` is a single fungible scalar
with no lot structure (`src/hbd/db/plan_sql.py:15`), so an automated reversal of purchase A can
debit a credit the customer paid for in purchase B.

A refund is therefore two actions by two systems, and **the money moves first**:

1. **Read the case.** `python -m hbd.payme.cli journal --ref <public_ref>` prints the intent,
   every transaction on it, the receipt and grant rows found under its idempotency key, the
   notification status, and every RPC we received about it. Establish whether the credit has
   already been **spent** — that changes step 3.
2. **Refund in the Payme cabinet.** This repository cannot do it and has no method that could;
   there is no outbound Merchant API for a merchant to call.
3. **Correct the credit.**
   * *Unspent*: debit it with `python -m hbd.tools.credits`, with a reason naming the Payme
     transaction id.
   * *Already spent*: the song was delivered. Do **not** drive the balance negative to chase
     it; record the write-off and stop. A negative balance breaks
     `credit_sql.verify_balances`, which the sweep asserts hourly, and you will be paged by
     your own reconciliation.
4. **Expect `-31007` in the journal.** When Payme's system asks us to reverse, we refuse, and
   that refusal is correct. Confirm it appears; its absence means Payme never asked, which is a
   different conversation.
5. **Record it** where your accounting lives. `topup_purchases` is append-only and has no
   `refunded_at` column — deliberately — so this repository is not the record of a refund.

The opposite incident — **the customer paid and got nothing** — is the common one and has a
button:

```bash
python -m hbd.payme.cli settle --ref <public_ref> --note "paid 2026-09-09, cabinet tx <id>"
```

It refuses without an explicit `--note`, prints the intent for confirmation before writing, and
writes the sale under the intent's **own** bot-minted idempotency key — so a late genuine
`PerformTransaction` collapses onto the same unique index and grants nothing twice. That is why
it is safe to press while still unsure.

---

## 8. The key-rotation runbook

`ChangePassword` is **dispatched and refused** with `-32400` carrying a message saying rotation
on this deployment is a redeploy. It is absent from the current documentation, survives only in
the archived 2017 specification, and implementing it would require the internet-facing process
to rewrite its own credential on an unauthenticated request — the single worst property a
process could have.

Rotation is three steps and roughly a minute of downtime:

```bash
ssh aizu 'sudo systemctl stop hbd-payme'
ssh aizu 'sudo -e /etc/hbd/payme.env'          # replace HBD_PAYME_MERCHANT_KEY
ssh aizu 'sudo systemctl start hbd-payme && systemctl is-active hbd-payme'
```

Notes that matter:

* **Stop first, then edit.** A running process holds the old key in memory; editing under it
  leaves the file and the behaviour disagreeing until something restarts, which is the state in
  which a rotation gets declared done and is not.
* **Downtime here is safe.** Payme retries, and `CreateTransaction`/`PerformTransaction`/
  `CancelTransaction` are all replay-safe by construction (`PAYME_INTEGRATION` §5). A minute of
  `-32300` at the terminator costs nothing but noise in their retry log.
* **The boot line names the length, never the value.** The settings model logs the key's
  **length** at INFO on boot, deliberately, so a truncated paste is visible without the secret
  ever being printed. There is no assertion that the length is 36: the documentation says 36
  but the TEST_KEY's length is unverified, and a wrong length assertion is a boot failure on
  go-live day.
* **Rotate on any suspicion at all.** This key is the only thing between the public internet and
  an unlimited credit mint. This increment ships the diagnostic half — the RPC journal, the
  hourly three-way invariant, the `-32504` log line — but **no throttle and no alarm**, so
  rotation *is* the mitigation. A burst-of-`-32504` alarm and an hourly grant-rate ceiling are
  worth a follow-up.

---

## 9. Weekly reconciliation, and what it cannot do

**There is no outbound Merchant API method a merchant may call.** No status polling, no
fetch-my-transactions. So reconciliation is two things, and the limitation is stated rather than
hidden.

**Automated, hourly, by the worker sweep.** A three-way invariant over the last 24 hours:
performed `payme_transactions` == receipts with `provider='payme'` == credit grants under those
idempotency keys. A mismatch is logged at ERROR with all three numbers and is **never
self-repaired**, because it would be a defect in the shared write primitive and an operator must
see it. Likewise, a performed transaction whose intent is not `paid` is logged and never quietly
fixed. `credit_sql.verify_balances` runs in the same arm — in the worker, on a schedule, never
inside a JSON-RPC request that must answer in milliseconds.

```bash
ssh aizu 'journalctl -u hbd-worker --since "24 hours ago" -o cat | grep -i "payme.*invariant"'
python -m hbd.payme.cli invariant --hours 24
```

**Manual, weekly, by a human.** Diff our statement against the cabinet's export:

```bash
python -m hbd.payme.cli statement --from 2026-09-01T00:00:00Z --to 2026-09-08T00:00:00Z
```

That prints exactly the rows `GetStatement` would return for the same window — inclusive on
Payme's own time, ascending — so any row in one and not the other is the finding. Look for: a
cabinet row we have no transaction for (an endpoint outage during `CreateTransaction`); a
performed transaction with no receipt (the invariant should already have shouted); and any
`is_sandbox=true` row in a production window (a stale variable).

---

## 10. Symptoms

| What you see | Where to look first |
| --- | --- |
| Every payment fails; journal shows `-31050` | The cabinet's «Настройка Аккаунт» versus `HBD_PAYME_ACCOUNT_FIELD` (§5.1). The log line names both. |
| Payme reports errors we cannot see at all | The terminator. Requests are not reaching us, or a non-200 is being substituted (§1.2, §4). `journalctl -u hbd-payme` and the proxy's access log for `POST /payme`. |
| A burst of `-32504` | Wrong key, wrong login, or somebody probing. The line records the login **received**; if it is not `Paycom`, that answers `PAYME_INTEGRATION` §7.1. If it is unfamiliar, rotate (§8). |
| Gateway boots, `/healthz` is 200, every method is `-32400` | Almost always the database role (§3.2) or a pool exhausted (§3.1). |
| A customer paid and got nothing | `python -m hbd.payme.cli journal --ref <ref>`, then `settle --ref … --note …` (§7). |
| The customer was charged but never told | The notification is an ARQ job; the sweep re-enqueues anything unnotified and older than 60 seconds, so the ceiling on the silence is `HBD_PAYME_SWEEP_MINUTES`. Check the worker is running before anything else. |
| Sales stopped with no error | The Redis pause key. `python -m hbd.payme.cli status`. Note the honest failure mode: a Redis rebuild silently **un**-pauses the rail, so re-check after any Redis restart. |
| A duplicate-transaction scenario fails in certification | `HBD_PAYME_DUPLICATE_TRANSACTION_CODE` (`PAYME_INTEGRATION` §7.2). Payme's own materials contradict each other here. |
