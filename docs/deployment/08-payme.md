# The Payme gateway — the fourth process

Provisioning, releasing, operating and debugging `bayram-payme.service`: the JSON-RPC endpoint
Payme calls to tell us a customer paid. It is the **only inbound HTTP surface in this system
that is reachable from the public internet without a login**, and the only process that holds
the Payme cashbox key.

What it is *for* is [`../product/PAYME_INTEGRATION.md`](../product/PAYME_INTEGRATION.md), cited
by section (`PAYME_INTEGRATION §3`). Why it exists at all is
[`../decisions/DECISIONS.md`](../decisions/DECISIONS.md) **D11**. This page is only how it runs
on a host.

> **THIS PAGE IS NO LONGER A PROPOSAL — it was deployed on 2026-09-09 and re-checked against
> `aizu` on 2026-09-10.** It is the one document in this tree whose STATUS block does not
> apply. §2, §4 and §11 are transcripts of a running machine; §3.2, §5 and §6 are still
> unverified and say so at the point of use. Every claim below carries the date it was
> checked, and a claim with no date is a claim about this repository's code, not about the
> host.
>
> What that cost the earlier draft: its §4 was written for a reverse proxy reachable from the
> internet, and **that assumption is false** — nothing reaches the origin directly. The whole
> section has been rewritten. Two of its recommendations (a grey-cloud DNS record, an
> origin-firewall caller allowlist) are not merely unimplemented, they are **impossible** in
> the topology that exists. See §4.

> **NAMING: THE HOST STILL SAYS `hbd`, THIS REPOSITORY NOW SAYS `bayram`, AND BOTH ARE CURRENT.**
> Verified 2026-09-10. On `aizu` the units are `hbd-payme.service`, `hbd-bot.service`,
> `hbd-worker.service`, `hbd-admin.service`; the dotenv files are `/etc/hbd/payme.env`,
> `/etc/hbd/hbd.env`, `/etc/hbd/hbd-admin.env`; the virtualenv is `/opt/hbd/venv`; the service
> user and group are `hbd`; every environment variable is prefixed `HBD_`; and the installed
> package is `hbd`, which is why the running `ExecStart` reads `-m uvicorn hbd.payme.app:app`.
> The working tree has been renamed to `bayram` throughout — package, unit files, variable
> prefix, paths — and **no service on this host runs it**.
>
> **That last sentence was "the rename has not been deployed" until 2026-09-11, and it is worth
> keeping the superseded version in view, because the host is no longer in the state it
> describes.** `[HOST 2026-09-11]` a cutover was attempted on 2026-09-10 and stopped part-way:
> `/etc/bayram/` exists and holds `bayram.env` (1148 B), `bayram-admin.env` (11213 B) and
> `payme.env` (361 B), each `0640 root:hbd`, all stamped 14:06; `/opt/bayram/venv` exists, built
> 14:06–14:07, with the package `bayram` and `bayram_bot-0.1.0.dist-info` installed in it. What
> did **not** happen is the part that decides which code runs: there is no `bayram-*.service`
> file in `/etc/systemd/system/`, no `bayram` OS user or group, and all four `hbd-*` units are
> `enabled` and `active`. **Every running `ExecStart` still names `hbd`, and every running
> process still reads `/etc/hbd/*.env`.** So the host today is neither pre-rename nor
> post-rename — it is mid-rename, with a complete `bayram` install that nothing executes. §11.6 is
> the gateway's share of that, and [`10-rename-cutover.md`](10-rename-cutover.md) is the whole of
> it.
>
> **The immediate trap this creates.** `/etc/bayram/payme.env` is now a real file holding real
> values, and it is **not** the file the gateway reads: the unit says
> `Environment=HBD_PAYME_ENV_FILE=/etc/hbd/payme.env` `[HOST 2026-09-11]`. Editing the
> `bayram`-spelled file changes nothing, raises nothing and logs nothing — the exact failure
> shape §11.6 is about, arriving a step earlier than anybody planned for. Check the boot line
> (§2.1) for `env_file` before believing any edit took.
>
> This page is written in the repository's naming because the rest of the tree is; wherever you
> are about to type a command at a shell prompt on `aizu`, substitute `hbd` for `bayram` until the
> cutover has actually completed — which, as of 2026-09-11, it has not. Command blocks quoting observed host output keep the host's names
> deliberately and **must not be swept**: they are transcripts, not identifiers.
>
> Do not trust this paragraph over the machine. One command settles which prefix is live, and
> it is the right first move on any host whose history you do not know:
>
> ```bash
> ssh aizu 'systemctl list-units --type=service --all "*payme*" "*-bot.service" | cat; ls -d /opt/*/venv /etc/*/payme.env 2>/dev/null'
> ```
>
> **The glob is doing more work than it was written to do, and that is now the point.** It was a
> "which prefix is live" probe; since 2026-09-10 it answers *both* — `[HOST 2026-09-11]` the
> second half prints `/opt/bayram/venv /opt/hbd/venv /etc/bayram/payme.env /etc/hbd/payme.env`,
> four paths under two names, while the first half prints only `hbd-*` units. **Read the two
> halves together: the units decide what runs, the directories only say what exists.** Any
> verification that looks at one root and concludes from it — and `09-payme-go-live.md` §2's
> first verification command did exactly that until it was widened — cannot see this state at
> all.

> **Two switches, two questions, and only one of them is on.** `BAYRAM_PAYME_ENABLED` governs
> whether the **gateway daemon runs**. `BAYRAM_CHECKOUT_PROVIDER` governs whether the **rail
> sells anything**. Conflating them is the single easiest mistake to make about this
> subsystem. As of 2026-09-10 on `aizu`: the daemon is enabled and active, and
> `BAYRAM_CHECKOUT_PROVIDER` is unset, so the composition root builds `StubCheckoutProvider`
> and no customer's money can reach Payme. **The paywall is nevertheless live on the stub
> rail** — a customer taps pay, is granted the credit and told "Paid", and no money moves. That
> was put to the owner and decided on **2026-09-10: leave it as is**, to be switched when the
> business says so. It is a recorded decision with a date, not an oversight; do not "fix" it.

---

## 1. What this process is, and what it must never be

### 1.1 One credential, and it is a different kind of credential

The bot and worker hold four **outbound** credentials — a Telegram token and three vendor keys
— whose theft lets somebody impersonate us or spend our balance. The admin panel deliberately
holds none. This process holds exactly one secret, `BAYRAM_PAYME_MERCHANT_KEY`, and it is an
**inbound verification** secret: it is only ever compared against itself, in
`hmac.compare_digest`, to decide whether an incoming request really came from Payme. Its theft
mints credits. That is a third blast radius, distinct from both of the others, and it is why
this is a fourth container rather than a route somewhere.

Two consequences follow, and both are enforced rather than documented:

* **This process holds no Telegram token.** Telling a customer their payment landed is
  therefore an ARQ job the worker performs — the same rule every other credentialled action in
  this system follows.
* **The panel and the bot must not hold this key.** In prod each refuses to boot with
  `BAYRAM_PAYME_MERCHANT_KEY` in reach, the panel via `FORBIDDEN_ENV_VARS`
  (`src/bayram/admin/app.py:116-118`) widened with `FOREIGN_SECRET_ENV_VARS`. That refusal is what
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

**Nothing in front of this route may serve an error page of its own.** A 502 from the proxy
while the gateway restarts is indistinguishable, from Payme's side, from us being broken —
which is survivable (they retry) — but a proxy that rewrites a 200 body, adds a JSON wrapper,
or gzips a response the client did not ask for is not. Pass the body through unaltered.

Read §4 before assuming you know what "in front of this route" means. It is not one reverse
proxy: it is Cloudflare's edge, then a tunnel, then Caddy, and **the first of those three is
the one that can substitute a response and is configured in a dashboard nothing here can
read** (§4.6).

---

## 2. The unit, and where the secret comes from

This is the one unit file in `deploy/systemd/` that was ever **corrected against the host**
(commit `24bbeeb`) — it picked up the real `/opt/…/venv`, `WorkingDirectory=/var/lib/…` and
`Environment=…_PAYME_ENV_FILE=` shape. **The rename then carried it back out of sync, and the
aborted cutover of 2026-09-10 has since carried three quarters of it back in** — which is a more
dangerous place to be than plainly wrong, so read the list rather than the summary.
`[TREE 2026-09-11]` `deploy/systemd/bayram-payme.service` reads, at `:61-65` and `:93`:

| Line in the repository's unit | True on the host today? |
| --- | --- |
| `ExecStart=/opt/bayram/venv/bin/python …` (`:65`) | **the path exists** — `/opt/bayram/venv`, `755 root:root`, built 2026-09-10 14:06, with `bayram` installed `[HOST 2026-09-11]` |
| `Environment=BAYRAM_PAYME_ENV_FILE=/etc/bayram/payme.env` (`:64`) | **the file exists** — 361 B, `0640 root:hbd`, 14:06 `[HOST 2026-09-11]` |
| `InaccessiblePaths=/etc/bayram/bayram.env /etc/bayram/bayram-admin.env` (`:93`) | **both exist** `[HOST 2026-09-11]`, and these are the filenames the host's own cutover chose |
| `User=bayram`, `Group=bayram` (`:61-62`) | **no.** `getent passwd bayram` and `getent group bayram` both return nothing `[HOST 2026-09-11]` |
| `WorkingDirectory=/var/lib/bayram` (`:63`) | **no.** `No such file or directory` `[HOST 2026-09-11]` |

So this file is now two edits from being installable and **is still not installable**, and a unit
that starts and then cannot resolve its own `User=` is a unit that fails at `systemd`'s layer
rather than the application's. Gate A owns the decision (`09-payme-go-live.md` §2); §11.6 owns
the inventory.

The other three unit files are wrong in a deeper way and that has **not** changed:
`[TREE 2026-09-11]` `bayram-bot.service:24-28` and `bayram-worker.service:17-21` name
`User=bayram`, `WorkingDirectory=/srv/bayram` and `/srv/bayram/.venv/bin/python`;
`bayram-admin.service:26-30` names the same `/srv/bayram` venv with
`Environment=BAYRAM_ADMIN_ENV_FILE=/etc/bayram/admin.env`. `[HOST 2026-09-11]` **`/srv` is
empty** — `total 8`, only `.` and `..` — and `/srv/bayram` does not exist; nor does
`/etc/bayram/admin.env`, because the host's cutover named that file `bayram-admin.env`. **Three
filename schemes for three dotenv files are now in circulation** — the host's
(`bayram.env` / `bayram-admin.env`), these three units' (`bot.env` / `admin.env`, which
`03-provisioning.md` §6 also carries, at `docs/deployment/03-provisioning.md:358-359`), and the
payme unit's, which matches the host's. Whoever writes the rename document picks one and records
the other two as dead; this page does not pick for them.

They are deliberately left alone rather than half-corrected into something that is neither the
proposal nor the record. Do not copy any of the four onto the host as they stand.

Read off `aizu` on 2026-09-10 with plain `cat /etc/systemd/system/hbd-payme.service` — **no
`sudo`**, and the absence matters: the unit file is `-rw-r--r-- root:root`, so anyone with a
shell can read it, while the `payme.env` it points at cannot be read at all (§2.1). Reach for
`sudo` here and you will be asked for a password you do not need.

```ini
# /etc/systemd/system/hbd-payme.service — the record, on the host, today
# Host names, pre-rename. The repository's names for the same things are in the NAMING note
# at the top of this page; the running prefix is the one to type at a shell on this box.
User=hbd
Group=hbd
WorkingDirectory=/var/lib/hbd
Environment=HBD_PAYME_ENV_FILE=/etc/hbd/payme.env
ExecStart=/opt/hbd/venv/bin/python -m uvicorn hbd.payme.app:app --host 127.0.0.1 --port 8091
RestrictAddressFamilies=AF_INET AF_INET6 AF_UNIX
InaccessiblePaths=/etc/hbd/hbd.env /etc/hbd/hbd-admin.env
```

Five lines carry an argument each.

**`--host 127.0.0.1`.** The bind is on the command line; nothing in the package binds a socket.
Binding `0.0.0.0` publishes an unauthenticated POST endpoint to the entire internet with only
Basic auth in front of it and no TLS at all.

**`Environment=BAYRAM_PAYME_ENV_FILE=…`, not `EnvironmentFile=`. And this is the only unit on
the host that actually does it.** Secrets arrive through the env-file *variable* because with
`EnvironmentFile=` every value is loaded into the process environment, where it appears in
`systemctl show` and in `/proc/<pid>/environ`, readable by anything that can read the process.
`BAYRAM_PAYME_ENV_FILE` is a **second variable rather than a tier shared with `BAYRAM_ENV_FILE`**,
following the rule stated at `src/bayram/admin/settings.py:69-74` — *"one knob deriving both paths
would be one edit away from pointing them at the same file"*, and the whole point of this
process is that it reads a different file from the bot and the worker. Read from the process
environment only, never from a dotenv, because a dotenv cannot name itself.

> **This repository has argued for that indirection for months and the three older units do
> not use it.** Verified 2026-09-10 — **and quoted in the host's own names, because these are
> paths a reader will `stat`**: `hbd-bot.service` and `hbd-worker.service` carry
> `EnvironmentFile=/etc/hbd/hbd.env`, `hbd-admin.service` carries
> `EnvironmentFile=/etc/hbd/hbd-admin.env`. So the Telegram token and all four outbound vendor
> credentials **are** in those processes' environments today and **are** visible to
> `systemctl show hbd-bot` and to anything that can read `/proc/<pid>/environ`. The gateway is
> the only process whose secret is not. That is a real gap in the deployment, not in the
> design, and it is recorded here rather than quietly asserted away — see `07-security.md` for
> what the control was supposed to buy.

**`InaccessiblePaths=`.** The application-level refusal (§1.1) is a check this process performs
on itself; this one is the kernel's, and it survives a future edit that points
`BAYRAM_PAYME_ENV_FILE` at the wrong file. On the host it names the two files that actually
exist, in the host's spelling — `InaccessiblePaths=/etc/hbd/hbd.env /etc/hbd/hbd-admin.env`,
verified 2026-09-10 — which matters precisely because the older units load those same files with
`EnvironmentFile=`: the kernel refusal is the only thing
standing between this process and the four credentials it is defined by not holding.

**No `ReadWritePaths=`.** This process writes no files. It renders nothing, transcodes nothing
and stores nothing; `ProtectSystem=strict` with no writable path is therefore correct rather
than merely tidy.

One more deliberate absence, documented in `bayram/payme/app.py`'s module docstring so nobody
"fixes" it: **`bayram.runtime.startup.verify_host` is not called.** The gateway renders nothing,
speaks no locale to a customer and needs no ffmpeg. Running it would let a payment endpoint
refuse to boot over an i18n catalogue.

### 2.1 The gateway's env file — `/etc/hbd/payme.env` on the host today

> Host spellings throughout this subsection, deliberately: every path and every owner below is
> something a reader is about to type at a prompt on `aizu`, and the repository's `bayram`
> names would each answer *No such file*. After Gate A's cutover (`09-payme-go-live.md` §2),
> substitute `bayram` throughout.

**On the host it is `root:hbd`, mode `0640`** — not `0600` owned by the service user, which is
what this page used to claim. `deploy/deploy-payme.sh` sets it that way on every run, and the
choice is deliberate: `0640 root:hbd` means the service can read the cashbox key and the
deploying account cannot. The consequence is one you will meet within a minute of trying to
debug anything — the `developer` login **cannot read this file**, cannot list `/etc/hbd` at
all, and cannot run the harness (§6.A) without `sudo -u hbd`. That is the control working, not
a permissions bug to route around.

The authoritative list of variables is `.env.payme.example` in the repository root, which
carries one commented block per field; the table below is the operator's short form.

| Variable | Set on the gateway? | Notes |
| --- | --- | --- |
| `BAYRAM_PAYME_ENABLED` | **yes**, `true` | The lifespan refuses to start on `false`. |
| `BAYRAM_PAYME_MERCHANT_KEY` | **yes, and nowhere else** | The cashbox key. The TEST_KEY during certification, the production key after. |
| `BAYRAM_PAYME_MERCHANT_ID` | yes | Public. Also on the bot (§5.2) — the gateway compares it against `payment_intents.merchant_id` and refuses a mismatch with `-31055`. |
| `BAYRAM_PAYME_BASIC_LOGIN` | yes | Defaults to `Paycom`. Inferred; see `PAYME_INTEGRATION` §7.1. |
| `BAYRAM_PAYME_ACCOUNT_FIELD` | yes | **Must equal the cabinet's «Настройка Аккаунт» field name exactly** (§5.1). Defaults to `order_id`. |
| `BAYRAM_PAYME_DUPLICATE_TRANSACTION_CODE` | yes | Defaults to `-31008`. Inferred; see `PAYME_INTEGRATION` §7.2. |
| `BAYRAM_PAYME_IS_SANDBOX` | yes | `true` until go-live. Stamped onto every intent, so sandbox rows are excludable from revenue by construction. |
| `BAYRAM_DATABASE_URL` | yes | Specified as `hbd_app`, never the owner role. **On this host that is intent rather than observation, and the roles turn out to be the other way round** — read §3.2's box before relying on it; `.env.payme.example:61` names `hbd`. |
| `BAYRAM_REDIS_URL` | yes | For the ARQ enqueue that notifies the customer. |
| `BAYRAM_ENVIRONMENT` | yes | `prod` enables the vendor-credential refusal. It is an exact `== "prod"` string comparison. |
| `BAYRAM_TELEGRAM_BOT_TOKEN` | **never** | The lifespan refuses in prod if it, or any other name in `bayram.config.REQUIRED_VENDOR_SECRET_FIELDS`, is reachable. |

Belt-and-braces check after any edit, which prints no secret value. It needs a password —
`/etc/sudoers.d/hbd-deploy` grants `tee` of this file, not `grep` of it (verified against
`sudo -l` on 2026-09-10):

```bash
ssh aizu 'sudo stat -c "%n mode=%a owner=%U:%G" /etc/hbd/payme.env;
          sudo grep -c "^HBD_PAYME_MERCHANT_KEY=.\+" /etc/hbd/payme.env;
          sudo grep -lE "^HBD_(TELEGRAM_BOT_TOKEN|ELEVENLABS_API_KEY|LLM_API_KEY|LLM_FALLBACK_API_KEY)=" /etc/hbd/payme.env || echo "no vendor credential in the payme env file — correct"'
```

**The cheaper check needs no privilege at all, and it is the one to reach for first.** The
gateway prints its whole effective configuration — never a secret value — on every boot, so
one journal line answers most of the table above:

```bash
ssh aizu 'journalctl -u hbd-payme -o cat | grep payme.boot.ok | tail -1'
```

At 09:27:28 on 2026-09-10 that line read, in part — **a transcript, in the host's names; a
rename sweep must not touch this block**:

```json
{"event": "payme.boot.ok", "environment": "dev", "env_file": "/etc/hbd/payme.env",
 "merchant_id": "placeholder", "is_sandbox": true, "account_field": "order_id",
 "basic_login": "Paycom", "duplicate_transaction_code": -31008, "merchant_key_length": 36}
```

**That block is a transcript of 2026-09-10 09:27:28 and is kept as one.** Here is the same line
read off the gateway's most recent start — **also a transcript, also in the host's names, also
not to be swept**:

```json
{"ts": "2026-09-11T06:50:15+0500", "event": "payme.boot.ok", "environment": "dev",
 "env_file": "/etc/hbd/payme.env", "merchant_id": "6aa24fd9ee30563de3a1ac22",
 "is_sandbox": true, "account_field": "order_id", "basic_login": "Paycom",
 "duplicate_transaction_code": -31008, "merchant_key_length": 36}
```

Three things across the pair are worth reading rather than skimming. One of them **has** become a
defect since the earlier line was written:

* **`"merchant_id"` is no longer `placeholder`.** `[HOST 2026-09-11]` it is
  `6aa24fd9ee30563de3a1ac22` — the 24-hex kassa id of a real **sandbox** cashbox, installed on
  the afternoon of 2026-09-10, and public by the same argument as §5.2. The merchant id and the
  TEST_KEY landed together, the endpoint and the `order_id` requisite were registered in the
  cabinet the same afternoon, and §5 is therefore no longer "entirely ahead of us": what is left
  of it is the production key, which belongs at Gate F (`09-payme-go-live.md` §8).
* **`"environment": "dev"` — still, and that is now the finding.** The earlier bullet said this
  *"must be flipped to `prod` in the same edit that installs a real merchant key"*. **The real
  key was installed and the flip was not made.** `[HOST 2026-09-11]` the gateway has restarted
  twice since (06:50:11 on 2026-09-11, `NRestarts=0`, so by hand rather than by crash) and still
  reports `dev`. The vendor-credential boot refusal keys off an exact `== "prod"` comparison
  (§1.1), so **the refusal that makes "the gateway holds no Telegram token" a mechanical fact is
  not armed on this host, and a real cashbox key is now sitting behind the unarmed version of
  it.** `InaccessiblePaths=` still is armed, which is precisely why §2 calls it belt and braces
  rather than redundancy — today it is carrying the control on its own. Flip it at Gate F at the
  latest; there is no longer a reason to wait for one.
* **`"merchant_key_length": 36`, unchanged across both lines.** The invented key of §6.A and the
  sandbox TEST_KEY are the same length, so this field cannot tell you which one is loaded and was
  never going to. `merchant_id` is the field that does.

---

## 3. Postgres: the connection arithmetic and the role

### 3.1 The arithmetic, recorded so the fifth process has to re-argue it

Do the arithmetic here once, in writing, so that the **fifth** long-running process has to
re-argue it rather than inherit it.

`src/bayram/db/engine.py:40-41` sets the defaults `pool_size=10, max_overflow=20` — at most 30
connections per process. The docstring at `:64-67` states the hypothetical that motivated the
two arguments: bot + worker + admin API *at the defaults* would be `3 × 30 = 90` against a
stock `max_connections` of 100, "so the API asks for a smaller share rather than everyone
quietly sharing a cliff edge". It does: `ADMIN_POOL_SIZE = 5`, `ADMIN_MAX_OVERFLOW = 5`
(`src/bayram/admin/container.py:53-54`).

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

The gateway is **specified** to connect as `hbd_app`, the application role from
`docker-compose.yml`'s two-role split — never the owner role `hbd`. The split exists so that
privileges can be revoked from the application and have that stick: an owner can `GRANT` back its
own revocations, so a one-role deployment cannot protect anything with privileges at all.

> **ON THIS HOST THE SPLIT IS NOT IN FORCE, AND THE ROLES ARE THE OTHER WAY ROUND FROM WHAT THIS
> SECTION ASSUMED.** `[HOST 2026-09-11]`, read through the one password-free route that answers
> it (`sudo -n -u postgres /usr/bin/pg_dump hbd`, which the NOPASSWD drop-in grants — §11.1):
>
> * **`hbd_app` owns everything.** 31 `OWNER TO hbd_app` lines against 1 `OWNER TO postgres`, and
>   the three rail tables by name: `ALTER TABLE public.payment_intents OWNER TO hbd_app;`, the
>   same for `payme_transactions` and `payme_rpc_log`.
> * **The whole dump contains exactly two privilege statements**, adjacent:
>   `REVOKE USAGE ON SCHEMA public FROM PUBLIC;` then `GRANT ALL ON SCHEMA public TO hbd_app;`.
>   There is no `GRANT` to any other role anywhere in it.
>
> So `hbd_app` is the **owner** here, not the restricted application role, and the protection the
> paragraph above describes — revoke from the application and have it stick — is not what this
> database is doing. An owner holds every privilege on its own tables implicitly, which is a
> different and weaker safety property than the one the two-role argument buys, and it is the
> reason nothing has ever answered `permission denied` on this host. **The argument for the split
> survives; the claim that this deployment implements it does not.** Changing that is a
> provisioning decision (`03-provisioning.md` §4), not a thing to fix from this page.
>
> **Which role the gateway itself presents is still `[UNPROVEN]`, and the repository disagrees
> with itself about it.** `/etc/hbd/payme.env` is unreadable as `developer`
> (`00-host-inventory.md` row 13), so the live DSN cannot be read. `[TREE 2026-09-11]`
> `.env.payme.example:61` names role **`hbd`** — `postgresql+asyncpg://hbd:…@localhost:5432/hbd`
> — as does `.env.admin.example:51`, while `.env.example:35` names `hbd_app` and `:46` names
> `hbd` for the migration URL. The §2.1 table's *"as `hbd_app`, never the owner role"* is
> therefore this page's intent rather than an observation.
>
> One inference, marked as one. A settlement **did** complete on this host on 2026-09-10, and
> `[HOST 2026-09-11]` the rows are there to prove it — `payment_intents` 7, `payme_transactions`
> 3, `payme_rpc_log` 53, `topup_purchases` 6, `credit_ledger` 18. Whatever role the gateway
> presents can therefore read and write all three rail tables. If it were presenting `hbd` with
> no grant and no membership it could not, so either the live DSN is not the example's, or `hbd`
> reaches `hbd_app`'s objects some other way. **Which of those is true is `[UNPROVEN]`** —
> settling it needs `psql`, which is the one thing the drop-in deliberately does not grant.

Migration `0023`'s three tables are created by the owner and inherit that role's default
grants. **Whether the role the gateway presents can actually read and write them is a fact about
the host, not a fact about this repository**, and the failure mode is ugly:
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

> **One caveat on reading that query's output, now that the box above says `hbd_app` owns these
> tables.** An owner's privileges are implicit rather than granted, and **whether
> `information_schema.role_table_grants` lists them for an owner on PostgreSQL 16 is
> `[UNPROVEN]` here** — it needs `psql`, which is exactly what is unavailable. So on *this* host
> an empty result would be ambiguous rather than damning, and "empty result means the problem"
> is safe advice only for the deployment §3.2 was written for, where the application role is not
> the owner. Read the ownership line out of `pg_dump` first; it is free and it is unambiguous.

> **PARTLY VERIFIED ON 2026-09-11, by a route this box said did not exist — and the important
> half is still open.** `show max_connections` has still never been run: `psql` needs a password
> and the pool arithmetic of §3.1 is still resting on a stock 100 (`00-host-inventory.md`
> row 11).
>
> The **grant** question, though, is answerable with no password at all, and the box above does
> it: `sudo -n -u postgres /usr/bin/pg_dump hbd` is NOPASSWD, and a dump carries every `OWNER
> TO`, `GRANT` and `REVOKE` in the database. That route had been sitting in the drop-in the whole
> time, named in this page's own §11.1 list, and nobody had pointed it at this question.
> **Generalise the move rather than the answer: a question about schema, ownership or privileges
> is usually a `pg_dump` away, and only a question about live state — connections, settings,
> sessions — actually needs `psql`.**
>
> Two things about the route are worth knowing before you reach for it. **It is the whole
> database, including every customer row**, so it belongs in a pipe to `grep`, never on a
> terminal and never into a file on the host. And the NOPASSWD rule matches the **exact argument
> vector** `/usr/bin/pg_dump hbd`: `[HOST 2026-09-11]` `sudo -n -u postgres /usr/bin/pg_dump
> --schema-only hbd` answers `sudo: a password is required`, so you cannot narrow the dump, only
> filter what comes out of it.
>
> **What the drop-in actually says, and the correction to how this page used to describe it.**
> `[HOST 2026-09-11]` the NOPASSWD rules reachable as `developer` are: `bash
> /opt/hbd/deploy-payme.sh`; `daemon-reload`; the seven `hbd-payme.service` verbs
> (`enable`/`disable`/`start`/`stop`/`restart`/`status`/`is-active`); `restart` — and **only**
> `restart` — of `hbd-bot.service`, `hbd-worker.service`, `hbd-admin.service`; `reload`/`restart`
> of `caddy.service`; `journalctl -u hbd-payme *`; `tee` of `/etc/hbd/payme.env` and
> `/etc/caddy/Caddyfile`; `caddy validate --config /etc/caddy/Caddyfile --adapter caddyfile`;
> and `pg_dump hbd` as `postgres`. **`psql` is not on it** — that is the drop-in doing its job,
> authorising a deploy rather than arbitrary database access.
>
> Three corrections to the earlier wording, all of them about not over-claiming: this list was
> described as *"read in full off `sudo -l`"* and attributed to `/etc/sudoers.d/hbd-deploy`, and
> `sudo -l` prints the **aggregate** sudoers policy and cannot attribute a rule to a file. It
> also prints two things the old list omitted — a leading `(ALL : ALL) ALL` for `developer`, so
> every gap below is a password rather than a wall, and a five-verb NOPASSWD block for an
> unrelated `aizu` service (§11.1's second drop-in). And `caddy validate` *is* covered, with its
> exact flags.
>
> The circumstantial evidence that the live grants are fine remains what it was, and it is now
> stronger: the worker's every-sweep invariant has read all three tables since 2026-09-09 with no
> `permission denied` in the journal, and since 2026-09-10 those tables have had rows in them.
> Still circumstantial about *the gateway's* role, because the worker connects as whichever role
> `/etc/hbd/hbd.env` names, which nobody here has read either.

---

## 4. The public path: a Cloudflare Tunnel, then Caddy, then loopback

**This section used to be called "the TLS terminator contract" and was written for a reverse
proxy reachable from the internet. That central assumption is false.** Verified 2026-09-10:
ports 80 and 443 at the origin are filtered — `curl http://192.166.228.52/` from an
arbitrary machine times out, as does `:443`, as does the same request carrying a
`Host: pay.bayrambot.uz` header. **Nothing reaches this box directly.** Caddy is still in the
path, but it is reached only from `127.0.0.1`, by a tunnel daemon on the same machine.

The whole **routing** path, verified end to end on 2026-09-10. (Routing only — no payment has
ever traversed it; see §6 and `09-payme-go-live.md` Gate C.)

```
Payme  →  Cloudflare edge (anycast; TLS terminated here)
       →  Cloudflare Tunnel  "aizu-vds"  (the origin dials OUT — there is no inbound port)
       →  cloudflared on abdu-test  →  http://127.0.0.1:80   (PLAIN HTTP)
       →  Caddy v2.11.4  site block  http://pay.bayrambot.uz  handle /payme
       →  reverse_proxy 127.0.0.1:8091  →  hbd-payme.service (uvicorn)
```

Three consequences reshape everything this section used to say, and each is worth stating on
its own: TLS is not ours to configure; the caller's address never reaches us; and Cloudflare's
proxy is now on the money path and cannot be taken off it.

### 4.1 Where the ingress lives, and what a `Tunnel` DNS record forecloses

**The ingress is not a file on this machine.** `cloudflared` runs as
`/usr/bin/cloudflared --no-autoupdate tunnel run --token-file /etc/cloudflared/token` — a
token-run tunnel, which means **there is no local `config.yml` and no local ingress rules at
all**. Grepping the host for the routing will find nothing, and that is not a
misconfiguration: the routing lives in the Cloudflare Zero Trust dashboard under **Networks →
Tunnels & Mesh → `aizu-vds` → Published application routes**, and is edited there by whoever
holds that account. Tunnel `aizu-vds`, id `8b799983-8694-479b-98b3-09aaed9b3f8d`, connector
hostname `abdu-test` (the machine's own hostname; `aizu` is only the SSH alias).

The published routes as of 2026-09-10:

| Hostname | Route | Note |
| --- | --- | --- |
| `aizu.uz` | `http://127.0.0.1:8765` | **A different application.** Not this product. Bypasses Caddy entirely. |
| `www.aizu.uz` | `http://127.0.0.1:8765` | Likewise. |
| `admin.bayrambot.uz` | `http://127.0.0.1:80` | Through Caddy. Concurrent admin-panel work. |
| `pay.bayrambot.uz` | `http://127.0.0.1:80` | Through Caddy. This page. |

Catch-all: `http_status:404`.

**A hostname routed through a tunnel gets a DNS record of type `Tunnel`, and a `Tunnel` record
is always proxied.** There is no toggle. That single fact kills two recommendations this
document and `deploy/caddy/pay.bayrambot.uz.caddy` both used to make in bold:

* **Grey cloud (DNS-only) for `pay.bayrambot.uz` is impossible**, not merely inadvisable. The
  earlier argument for it was sound on its own terms — a proxied hostname lets Cloudflare
  substitute 5xx pages, `1020` access denials and managed challenges, and Payme reads every one
  of those as `-32400` — but the mechanism it asked for does not exist here. It was tried: an
  `A` record for `pay` was created first, on that plan, and then had to be **deleted**, because
  a plain `A` record on the name blocks the tunnel route from being saved at all
  (*"A DNS record with this name already exists"*). Confirm the state of play by resolving the
  name: on 2026-09-10 `pay.bayrambot.uz` answers `104.21.0.246` / `172.67.151.126` — Cloudflare
  anycast — not `192.166.228.52`.
* **An origin-firewall caller allowlist is moot.** There is nothing to filter: no packet from
  Payme, or from anyone, arrives at this host's `:443`. The only address the origin ever sees
  on this path is `127.0.0.1`.

> **`00-host-inventory.md` row 37 said exactly this and has since been corrected** — as of
> 2026-09-10 it records the grey-cloud plan as superseded and impossible, for the same two
> reasons given above, and adds a third this page did not have: the origin has no public address
> to point a grey-cloud `A` record *at* (that file's finding 2 — one CGNAT address on `ens18`,
> and `192.166.228.52` is a provider NAT). Do not re-flag it.
>
> **`deploy/caddy/admin.bayrambot.uz.caddy` still carries the stale claim**, verified
> 2026-09-10: its comment asserts *"pay.bayrambot.uz answers as `192.166.228.52`, the origin
> itself"* — it does not; it answers as Cloudflare anycast, like every other name on this
> tunnel. That file also still opens its site block **scheme-less** (`admin.bayrambot.uz {`,
> line 25) while telling the reader to paste it into the host Caddyfile, so following it
> re-introduces the 308 trap that the host's own Caddyfile has already been fixed for (§4.3).
> Both belong to concurrent admin-panel work; they are flagged here, not fixed here.

### 4.2 The contract, revised

What is left of the old contract after the topology correction, plus what the topology adds:

1. **One dedicated hostname, not the admin panel's — unchanged, and now enforced by the
   tunnel.** The panel must be "the only reachable name" at its origin: both its cookies are
   `__Host-` prefixed and un-narrowable, and its CSRF check compares
   `BAYRAM_ADMIN_PUBLIC_ORIGIN` exactly. `pay.bayrambot.uz` and `admin.bayrambot.uz` are
   separate published routes and separate Caddy site blocks. Satisfied, verified 2026-09-10.
2. **`POST /payme` and nothing else.** Satisfied by Caddy, not by the tunnel: both routes point
   at `127.0.0.1:80` with no path matching, so the narrowing is `handle /payme` plus
   `handle { respond 404 }` in the site block. Verified from the public internet:
   `GET https://pay.bayrambot.uz/` → **404**. `/healthz` and `/readyz` stay on loopback for the
   local monitor and are not published.
3. **TLS is Cloudflare's, not ours, and the origin leg is plain HTTP.** Nothing on this host
   terminates TLS for this hostname and nothing should try to; see §4.3 for what happens when
   Caddy tries anyway. Payme's recommended TLS tuning — session cache, session timeout ≥ 10
   minutes — is now a Cloudflare property and not a knob we hold. The one piece still ours is
   the **upstream keepalive**, set to `10m` on the `reverse_proxy`, because Payme's client
   reconnects frequently.
4. **HTTP 200 bodies passed through unaltered** — no error-page substitution, no body
   rewriting, no added JSON envelope (§1.2). Caddy does this. **Cloudflare is now the risk
   holder for this clause**, and it is not yet configured (§4.6).
5. **The caller allowlist is enforced nowhere, deliberately, and is currently unbuildable.**
   See §4.5 — this is the clause that changed most.

### 4.3 THE 308 TRAP — the most valuable operational finding on this page

**Observed on `aizu`, 2026-09-09/10.** The Caddy site block for the Payme hostname was written
the way every Caddy example writes one:

```caddy
pay.bayrambot.uz {
	handle /payme { reverse_proxy 127.0.0.1:8091 }
}
```

A bare hostname with no scheme tells Caddy to **enable automatic HTTPS for that name**. Caddy
therefore answers every request arriving on port 80 with `308 Permanent Redirect` to
`https://pay.bayrambot.uz/…` — the canonical, correct, textbook behaviour of a web server that
believes it owns TLS for the name. **But the tunnel speaks plain HTTP to `127.0.0.1:80`.** So
every tunnelled request was redirected to a hostname that resolves straight back into the same
tunnel, into the same port 80, into the same 308.

**The fix is one word.**

```caddy
http://pay.bayrambot.uz {
	handle /payme { reverse_proxy 127.0.0.1:8091 }
}
```

`http://` on the site address disables automatic HTTPS for that block and makes Caddy serve the
request instead of redirecting it. It is load-bearing and it looks like a typo; that is exactly
why it is written down here and commented in `deploy/caddy/pay.bayrambot.uz.caddy` at the line
itself.

**Why this is worse than an outage, and why it earns its own section.** A 308 is a *successful*
response by every ordinary measure. Caddy logs it as a normal request. `curl -I` returns
promptly. `systemctl is-active` says `active`. Anyone following redirects — a browser, `curl -L`,
a monitoring check written the obvious way — sees a 200 at the end and reports the endpoint
healthy. **Payme follows no redirect. It reads any non-200 as a transport fault, answers
`-32400`, and retries.** So the failure mode is an endpoint that is green on our side and
permanently unusable on theirs, discovered — if you are lucky — during a certification slot,
and otherwise by a customer whose money moved and whose credit did not. Anything that makes
"broken" look like "fine" belongs in a document like this one; this is the clearest example the
project has produced.

**The diagnostic that settles it in one line**, because it is the *absence* of `-L` that makes
it informative:

```bash
curl -sS -o /dev/null -w '%{http_code} -> %{redirect_url}\n' \
     -X POST https://pay.bayrambot.uz/payme -H 'Content-Type: application/json' -d '{}'
```

`200` with an empty `redirect_url` is correct, and the body should be a JSON-RPC error object
(`-32504` unauthenticated — see §6). `308` with a `redirect_url` pointing back at the same
hostname is this trap. Verified correct from the public internet on 2026-09-10.

**Every site block behind this tunnel has the same exposure, and one still has the bug.**

* `pay.bayrambot.uz` — **fixed** on the host. `/etc/caddy/Caddyfile` reads
  `http://pay.bayrambot.uz {`, verified 2026-09-10, and `deploy/caddy/pay.bayrambot.uz.caddy`
  matches it.
* `admin.bayrambot.uz` — **fixed on the host, still broken in the repository.**
  `/etc/caddy/Caddyfile` reads `http://admin.bayrambot.uz {` as of 2026-09-10, but the
  committed `deploy/caddy/admin.bayrambot.uz.caddy` still opens `admin.bayrambot.uz {` with no
  scheme. That file's own header instructs the reader to *"paste into `/etc/caddy/Caddyfile` on
  the host"* — so following its instructions re-introduces the trap on the admin panel. **This
  belongs to concurrent admin-panel work; it is flagged, not fixed here.**
* `aizu.uz, www.aizu.uz` — scheme-less, and **harmless today only by accident**: those two
  published routes point at `127.0.0.1:8765` directly and never traverse Caddy. Re-point either
  route at `:80` and it acquires the bug in the same instant. Worth knowing before somebody
  "consolidates the proxies".

### 4.4 The `/var/log/caddy` permission trap

A second Caddy trap, met on the same two days, and it is the pre-flight check causing the
failure it exists to prevent.

`caddy validate` does not merely parse a config — **it provisions it**, and provisioning a
`log` directive *opens the file*. Run it under `sudo`, as any sane pre-flight does, and root
creates `/var/log/caddy/payme.log` owned `root:root`. The `caddy` user then cannot open it, and
`systemctl reload caddy` fails with *permission denied* on the very file the validation just
made. It fails **the whole reload**, not just that one site, so a validated config takes down
your ability to reload every other hostname on the box.

The artefact is still sitting there, verified 2026-09-10:

```
-rw------- 1 caddy caddy 826118 Sep 10 09:54 admin.log
-rw------- 1 caddy caddy      0 Aug  7 15:01 aizu.log
-rw------- 1 root  root       0 Sep 10 00:02 payme.log     ← created by `sudo caddy validate`
```

`aizu.log` escaped only because the `caddy` user had created it itself back in August.

Two fixes, and the Payme block takes the second:

* **Pre-create the file as the right user**, which is what the admin block does:
  `sudo install -o caddy -g caddy -m 600 /dev/null /var/log/caddy/admin.log` before reloading.
* **Do not log to a file at all.** The Payme site block logs `output stderr`, so its access log
  lands in `journalctl -u caddy` and there is no file to own. This is the better answer *for
  this block specifically*, and the reason is §4.5: Caddy's access log for this hostname would
  record `127.0.0.1` as the client on every line, so it is worth strictly less than the
  application's own journal. Give up nothing, remove a failure mode.

### 4.5 The caller allowlist: moot at the firewall, and no longer buildable from our own journal

The old §4.1 argued that the allowlist belongs at the terminator rather than in the
application, and **that argument still holds**. `payme_allowed_cidrs` exists, defaults to
**empty**, and is honoured only when `payme_trusted_proxy_hops > 0`. With zero hops the
application sees the *proxy's* address, so an in-app filter would match the wrong address —
refusing every genuine Payme call while accepting anything that reached the proxy. **A filter
matching the wrong address is worse than no filter.** `src/bayram/admin/security/clientip.py`
learned this already, and at that module's shipped defaults every audit row records the proxy's
address rather than the operator's.

**What no longer holds is the escape hatch.** That section promised that because every request
logs its peer IP unconditionally, the real caller set was discoverable from our own journal and
the allowlist could be built from observation rather than from a published range. In this
topology it cannot. Verified 2026-09-10 — every `peer_ip` recorded by the gateway since it
started, without exception, is the same value:

```console
$ journalctl -u hbd-payme --since "3 days ago" -o cat \
    | grep -o '"peer_ip": *"[^"]*"' | sort | uniq -c | sort -rn
     15 "peer_ip": "127.0.0.1"
```

That is Caddy's address, and it always will be. The real client address does exist — Cloudflare
writes it into `CF-Connecting-IP` and appends to `X-Forwarded-For` — but nothing on this host
consumes it for the gateway: Caddy passes the headers along untouched, and the application is
running at `payme_trusted_proxy_hops = 0`, so it reads the socket peer. **Do not raise that
setting to make the log prettier.** Trusting a hop count means trusting a header, and a header
is forgeable by anyone who can reach the socket; the reason it is zero is that the value would
be load-bearing for a filter that mints credits.

So the honest position, recorded rather than papered over:

* **The `185.234.113.0/28` range is documentation, not observation.** It is Payme's published
  production range; their sandbox may originate elsewhere, and a filter that refuses every
  certification call looks exactly like a broken endpoint. The commented `@payme_callers`
  matcher was removed from the deployed Caddy block for that reason.
* **Enforcing it at Caddy would filter the wrong address too** — Caddy's peer is `cloudflared`
  on loopback. An allowlist in this topology has to be expressed either as a Cloudflare WAF
  rule on the edge, where the real client address is known, or via `CF-Connecting-IP` with the
  proxy chain explicitly trusted end to end. Neither exists today.
* **What we do have is the `-32504` log line**, which records the Basic-auth login *presented*
  on every refused call and never the key. Against an unauthenticated prober that is the signal
  that matters, and it works regardless of the peer address. §8 makes rotation the mitigation
  for exactly this reason: this increment ships the diagnostic half and no throttle.

### 4.6 What Cloudflare must be told, and has not been

Because the proxy is unavoidable, the `-32400` risk it introduces has to be managed **with
Cloudflare settings for this hostname** rather than by bypassing the proxy. **None of this is
configured as of 2026-09-10.** It is the last thing standing between a certified endpoint and
an endpoint that fails intermittently for reasons invisible in our journal.

1. **Bot Fight Mode / Super Bot Fight Mode: off for `pay.bayrambot.uz`.** These target exactly
   this traffic shape — a server-to-server `POST` with no browser, no JavaScript and no
   cookies. A challenge served to Payme is a non-200 HTML body we never see, read as `-32400`,
   retried, and invisible in `journalctl -u hbd-payme` because the request never reached us.
2. **A WAF skip rule for `http.host eq "pay.bayrambot.uz" and http.request.uri.path eq
   "/payme"`**, skipping managed rules, rate limiting and bot management. Scope it to the path,
   not the hostname, so the 404 catch-all keeps whatever protection it has.
3. **No "Under Attack" mode, ever, on this hostname**, including as an incident reflex during
   an unrelated event on another name in the zone.
4. **Check the analytics after certification, not before.** The tell for all of the above is a
   gap: Payme reports errors we cannot see at all, and `journalctl -u hbd-payme` shows no
   corresponding request. Cloudflare's own event log for the hostname is then the only place
   the truth lives — see the §10 row reading *"Payme reports errors we cannot see at all"*.

> **The asymmetry to keep in mind.** Everything above is a setting in somebody's dashboard, not
> a line in this repository, and nothing in this repository can detect that one of them was
> changed. That is the price of the tunnel, and it was not chosen for this product — the tunnel
> predates it and carries an unrelated application on `aizu.uz`. Record who holds that account
> alongside the Payme cabinet credentials; on the day the endpoint stops working they are the
> same emergency.

---

## 5. What to enter in the Payme cabinet

Everything in this section is typed by a human into a web form on Payme's side, and **three of
those boxes can silently break every payment**: the account field's name, the validator applied
to its value, and the endpoint URL.

### 5.1 «Настройка Аккаунт» — the account field, and the rest of the form

The cabinet declares the account field set in a form; there is no API for it and nothing in
this repository can validate it before the cabinet exists. It must equal
`BAYRAM_PAYME_ACCOUNT_FIELD` **exactly** — we ship `order_id`.

If they disagree, every `CheckPerformTransaction` is a `-31050`, every payment fails, and it
looks like our bug. That is why the `-31050` log line records the account subfield names
actually **received** alongside the one expected:

```bash
ssh aizu 'journalctl -u hbd-payme --since today -o cat | grep -- "-31050" | tail -5'   # host name, pre-rename
```

One line of that journal settles it. Fix it in the cabinet, or change the variable and restart
— whichever is faster on the day; they are equivalent.

#### The «Добавление реквизита» form, field by field

The name is only the first box. The same form carries display labels and a validator, and the
validator is applied to the value **we** put in the link — so a validator that disagrees with
the mint refuses every payment just as thoroughly as a misspelled name does. The value is a
`public_ref`: 24 lowercase hex characters from `secrets.token_hex(12)`, in a column 32 wide
(`PUBLIC_REF_LENGTH`).

| Поле | Значение | Why this and not something else |
| --- | --- | --- |
| Название Реквизита | `order_id` | Equals `BAYRAM_PAYME_ACCOUNT_FIELD`, byte for byte. See above. |
| Отображаемое название (ru) | `Номер заказа` | Free text, read by a customer on Payme's page. No code depends on it. |
| Отображаемое название (uz) | `Buyurtma raqami` | Latin Uzbek — Payme's `uz` slot has no script variant (`link.py`, `LANGUAGE_PARAM`). |
| Отображаемое название (en) | `Order number` | |
| Регулярное выражение | `^[0-9a-f]{24,32}$` | The mint's alphabet, bounded by the column rather than by today's length — see below. |
| Цифры / Буквы / Символы | Цифры ✔, Буквы ✔, **Символы ✗** | Hex needs both classes. Symbols must stay off: `;` and `=` are structural in Payme's link parser and a `;` inside a value truncates it silently (`link.py`, parser fact 1). The reference is hex precisely so it cannot contain one; do not widen the class that would let it. |
| Ограничение по длине | min 24, max 32 (one number: 32) | Same reasoning as the regex. |
| Текст ошибки | `Неверный номер заказа` / `Buyurtma raqami notoʻgʻri` / `Invalid order number` | Payme renders this when its OWN validator refuses. It is not one of `ACCOUNT_MESSAGES` — those are ours, returned with `-31050..-31099`, and they say what happened to the order rather than to the string. |

**`{24,32}` rather than `{24}` on purpose, and the reason stands — but the sentence this page
used to support it with was wrong, so here is the whole picture instead.** A cabinet regex pinned
to `{24}` would have to be edited on Payme's side, by hand, the same hour a widened reference
shipped, and it would be discovered as a total payment outage rather than as a test failure.
That argument is untouched. What was wrong is the claim that
`bayram.payme.cli._public_ref` *"validates against the column width rather than against
`len(secrets.token_hex(12))`"* as though the two bounds agreed with the form above. **There are
four validators for this one identifier and no two of them agree** `[TREE 2026-09-11]`:

| Where | What it accepts | Cited at |
| --- | --- | --- |
| **The mint** | **exactly 24** lowercase hex — `secrets.token_hex(12)`, `_PUBLIC_REF_BYTES = 12` | `src/bayram/db/payme.py:135-144` |
| **The column** | up to **32** characters; the eight spare are deliberate, for *"a prefix (`bayram-`) or a checksum suffix"* | `src/bayram/db/models/payment_intent.py:125-130` |
| **The recovery CLI** | **1 to 32** lowercase hex — `not text or len(text) > PUBLIC_REF_LENGTH`, so the lower bound is one character, not 24 | `src/bayram/payme/cli.py:466-475` |
| **The admin panel's lookup** | **exactly 24** — `PUBLIC_REF_PATTERN = r"^[0-9a-f]{24}$"`, a 422 on anything else | `src/bayram/admin/routers/billing.py:252-257` |

Three consequences worth having in front of you before you type anything into that form:

* **The cabinet's `{24,32}` is the loosest validator in the system, and the looseness buys
  exactly one future: a longer hex reference.** Widening the mint would still need two edits
  inside this repository — the admin pattern, which pins 24 — and would need none in the cabinet.
  That is the right way round, and it is what the looser bound is for.
* **The `bayram-` prefix the column's own comment names as the motivating case is foreclosed by
  this form.** A `-` is not in `[0-9a-f]`, so the cabinet regex refuses it, the admin pattern
  refuses it, the CLI's hex check refuses it, and the «Символы ✗» row above refuses it a fourth
  time. If that prefix is ever actually wanted, it is a cabinet form change **and** two code
  changes, not a column that already has room. Better: spend the eight characters on more hex or
  a hex checksum, which costs nothing anywhere.
* **The CLI's one-character lower bound is not a defect to tighten.** It is refusing on the
  *alphabet* and the *column*, which is what stops a mistyped reference becoming a lookup; a
  three-character hex string is refused by the ledger a moment later with "no intent exists under
  reference", which is the same answer one step further on. Tightening it to 24 is the change the
  docstring at `:459-464` explicitly argues against, because a widened mint would then make the
  recovery tool refuse the one reference somebody is trying to find during an incident.

None of the four is what decides whether a reference is ours. `-31050` is, and it reads the
ledger.

**Declare exactly one requisite.** The checkout link carries `ac.order_id` and nothing else
(`link.build_checkout_link`), so a second declared field becomes a box Payme asks the customer
to fill in on a page we prefilled. Extra subfields arriving *on the wire* are harmless — the
gateway reads the account object by name and tolerates the rest
(`service.PaymeService._account_value`) — but an extra field *on the form* breaks the link.

### 5.2 Endpoint URL, and where the merchant id goes

* **Endpoint URL**: **`https://pay.bayrambot.uz/payme`**. The hostname exists, resolves, and
  answers — verified from the public internet on 2026-09-10 (§4, and the two probes in §6.C.0
  below). **It was registered in the cabinet on 2026-09-10**, together with the `order_id`
  requisite of §5.1, against the sandbox cashbox whose id the boot line now reports (§2.1). The
  sentence this replaces — *"it is not yet registered in the cabinet, which is the whole of §5's
  remaining work"* — was true for one afternoon and is kept here because it becomes true again
  for any new cashbox, including the production one. Row 37 of
  [`00-host-inventory.md`](00-host-inventory.md) names the same hostname and is correct about it;
  its parenthetical about a grey-cloud `A` record is stale, see §4.1.
* **Merchant id (кассы id)**: public. It goes in `/etc/bayram/bot.env` as `BAYRAM_PAYME_MERCHANT_ID`,
  because the **bot** builds the checkout link, and in `/etc/bayram/payme.env` as well, because the
  gateway compares it against the intent's stored `merchant_id` and answers `-31055` on a
  mismatch. That column is what makes a sandbox/production or second-cashbox split-brain a
  refusal instead of a customer charged by the wrong cashbox.
* **Both keys (TEST_KEY, production key)**: secret. They go **only** in `/etc/bayram/payme.env`,
  one at a time.

All three come from Кассы → the kassa → Настройки → Инструменты разработчика.

---

## 6. Certification runbook

Do these in order. Stages A and B need no Payme relationship at all and should be finished
before the certification slot is booked.

> **Where this stands on 2026-09-10, 13:30 +05.** Stages A and B are done, and **so is the thing
> that mattered: settlement has been executed on this host.** The harness passed 4/4 scenarios —
> `authorization`, `scenario-one`, `scenario-two`, `refusals` — under run id `e767f6ce`, and the
> worker's *"your payment went through"* message arrived on a real phone. The full transcript and
> what each scenario closed is [`09-payme-go-live.md`](09-payme-go-live.md) §4.0.
>
> The same afternoon the gateway stopped running on an invented key: a real sandbox cashbox's
> merchant id and TEST_KEY are in `/etc/hbd/payme.env`, `is_sandbox` is still `true`, and the
> endpoint and the `order_id` requisite are registered in the cabinet (§5). The command, which
> keeps the key out of your shell history by leaving `--key` off and letting the harness read the
> dotenv it was pointed at:
>
> ```bash
> ssh aizu 'sudo -u hbd env HBD_PAYME_ENV_FILE=/etc/hbd/payme.env \
>   /opt/hbd/venv/bin/python -m hbd.payme.harness \
>   --endpoint http://127.0.0.1:8091/payme --login Paycom --telegram-user-id <your id>'
> ```
>
> **The sentence this replaces is worth remembering rather than deleting**, because it becomes
> true again at every rename, every host move and every change to the one-commit write
> primitive: until the harness has run and passed *here*, no claim on this page about the
> settlement path is a claim about this host — it is a claim about the code and the tests, which
> is a different and weaker thing. A green `systemctl is-active` never implied otherwise, and the
> Gate A rename cutover puts this page back in that state deliberately.

### A. Rehearse on the host with an invented key

The merchant key is only ever compared against itself, so a made-up 36-character string makes a
**fully functional gateway**.

1. `BAYRAM_PAYME_ENABLED=true`, `BAYRAM_PAYME_IS_SANDBOX=true`, an invented key, an invented merchant
   id in `/etc/bayram/payme.env`. `BAYRAM_CHECKOUT_PROVIDER` stays `stub` — the bot issues nothing.
2. `systemctl start bayram-payme`, then `curl -sS -o /dev/null -w '%{http_code}\n'
   http://127.0.0.1:8091/healthz` → `200`.
3. `python -m bayram.payme.harness --endpoint http://127.0.0.1:8091/payme --login Paycom --key
   <that key>`. It replays Payme's two published sandbox scenarios against the running process
   and prints a pass/fail table. This exercises the real database, the real ARQ enqueue, the
   real worker notification and **a real Telegram message** — the whole settlement path up to
   the customer seeing "your payment went through" — before Payme has heard of us.
4. Rows created this way carry `is_sandbox=true` and are excluded from every revenue figure by
   construction.

### B. Prove the link against Payme's own parser, still with no credential

`https://test.paycom.uz/<base64>` echoes the parsed receipt as JSON with **no authentication**.
On a dev machine, with `BAYRAM_CHECKOUT_PROVIDER=payme`, an invented merchant id and
`BAYRAM_PAYME_CHECKOUT_BASE_URL=https://test.paycom.uz`, walk the customer path: a real intent row
is written, a real link is built, rendered under a real 🔗 button, and tapping it reaches
Payme's sandbox, which parses our receipt and echoes back the merchant id, every account
subfield, the tiyin amount, the language and the untruncated callback.

With an invented merchant id the sandbox stops at **«Поставщик не найден»**. That is the
correct answer and the last thing that changes at go-live.

### C. Sandbox certification, the day the cabinet exists

0. **Before anything else, re-prove the public path**, because it runs through infrastructure
   nobody in this repository controls and a dashboard setting can change under you between
   slots (§4.1, §4.6). Two probes from any machine on the internet, and note the deliberate
   absence of `-L`:

   ```bash
   curl -sS -o /dev/null -w 'root=%{http_code}\n' https://pay.bayrambot.uz/
   curl -sS -w '\nstatus=%{http_code} redirect=%{redirect_url}\n' \
        -X POST https://pay.bayrambot.uz/payme -H 'Content-Type: application/json' -d '{}'
   ```

   Correct as of 2026-09-10: `root=404`; the POST returns `status=200`, an empty `redirect`,
   and the body `{"error":{"code":-32504,…}}` — unauthenticated, which is the right refusal for
   a request carrying no `Authorization` header. Authenticated with `Paycom:<key>` the same
   endpoint answers `200` with `{"error":{"code":-31003},"id":77}`. **A `308` with a redirect
   URL is §4.3 and nothing else; fix that before spending the slot.**
1. **First**, declare the account field name in the cabinet and register the endpoint URL
   (§5). Doing this first is what stops the slot being spent diagnosing `-31050`.
2. TEST_KEY into `/etc/bayram/payme.env`; `BAYRAM_PAYME_ENABLED=true`; restart.
3. **Open the pending orders their engineer will ask for, and send him the ids and the
   amounts in tiyin.** See §6.C.1 — this is the step that is easy to be caught out by, because
   nothing that ships in the wheel can perform it.
4. Run Payme's sandbox UI against us, and close the three inferred facts
   (`PAYME_INTEGRATION` §7) — each is an environment value and a restart, never a release:
   read the real Basic-auth login off the first `-32504` log line;
   flip `BAYRAM_PAYME_DUPLICATE_TRANSACTION_CODE` until the duplicate-transaction scenario passes;
   confirm integer-`0` times are accepted.
5. Do the manual iOS and Android test of the `t.me` return redirect here. **Nothing depends on
   it** — settlement is webhook-driven and `BAYRAM_PAYME_RETURN_URL` defaults to blank. If you do
   set it, the only value the bot can answer is `https://t.me/<bot_username>?start=paid`:
   `bayram.bot.handlers.start.handle_paid_return` is registered for the payload `paid` alone, and
   it redraws the balance from the meter and claims nothing. It goes in the BOT's dotenv, since
   the bot is what builds the link; the gateway's copy is read only by the CLI and the harness.
6. Drive the 12-hour timeout branch by shrinking the transaction-timeout setting to seconds; it
   is a setting rather than a constant for exactly this.

#### C.1 The pending orders Payme asks for, and why nothing in the wheel can make one

**`[2026-09-10]` Their engineer's own words**, and they arrived with no warning in the middle of
the slot being arranged: «тест учун 3 пендинг статусда заказ яратиберин илтимос, айди ва эмаунт
тийнда керак болади» — *create 3 orders in pending status for the test; I will need the id and
the amount in tiyin.* Expect this request at every sandbox slot. Payme does not test against an
order they invent; they test against rows that already exist on our side, and they need the
`order_id` and the amount **before** they touch anything, because those two values are the
`params` of the first `CheckPerformTransaction` they will send.

**Nothing that ships in the wheel produces one, and the near misses are worth naming** so nobody
spends the slot rediscovering it:

* `payme.harness` *does* open real intents through `open_intent` — and then drives each one to a
  terminal state, which is the entire purpose of it. It leaves nothing payable behind, and
  [`09-payme-go-live.md`](09-payme-go-live.md) §4.0 records that as a virtue.
* The bot's own checkout would mint one, but `CHECKOUT_PROVIDER` is `stub` and stays `stub`
  until stage D — that is a decision, not an oversight (`09-payme-go-live.md` §6).
* `payme.cli` has no `open` verb, deliberately: it is a *recovery* surface, and every verb on it
  acts on a payment that already exists.

That leaves `INSERT INTO payment_intents` by hand on a production host, next to a `credit_ledger`
whose `verify_balances` invariant a hand-written row is one typo away from breaking — which is
exactly what `bayram.tools`' standing rule forbids. So the tool obeys the rule instead:

**`deploy/payme-open-orders.py`** opens *N* pending intents through `PaymeLedger.open_intent`,
the same port the bot's provider calls, and writes nothing else — no transaction, no receipt, no
grant. It cannot produce a row shape the product could not, and a schema change reaches it with
no edit. Every row carries `is_sandbox=true`.

**It is not in the wheel and does not need to be.** It is an operator script in `deploy/`, copied
to the host for the slot, and it imports under **either** package name — `bayram` or `hbd` —
so the certification slot and the Gate A rename cutover need not happen in a particular order.
Nobody should be editing a script while somebody from Payme is on the line.

```bash
scp deploy/payme-open-orders.py aizu:/tmp/
ssh -t aizu 'sudo -u hbd env HBD_PAYME_ENV_FILE=/etc/hbd/payme.env \
  /opt/hbd/venv/bin/python /tmp/payme-open-orders.py --telegram-user-id <your id>'
```

`sudo -u hbd` is not optional and it **will** prompt for a password: `/etc/hbd/payme.env` is
`0640 root:hbd`, `/etc/hbd` is not traversable by `developer`, and the NOPASSWD drop-in covers
`systemctl`, `journalctl`, `tee` and `pg_dump` — not this. `[HOST 2026-09-11]` `developer` is in
`adm sudo lxd …` and **not** in `hbd`, so there is no route to the file that skips the prompt.
Budget for a human at a keyboard, and do not schedule this into anything unattended.

`--telegram-user-id` is required for the same reason it is on the harness: if Payme actually
performs one of these, that account receives the credit and the worker's *"your payment went
through"* message. Use your own. `--amount` defaults to `700000` **tiyin** — 7 000 so'm, the
shipped `single_song_price_minor`; nothing on this path multiplies by 100. `--count` defaults to
3 because that is what they asked for, and is bounded at 20.

It prints two blocks. The first is the answer to forward verbatim — `order_id=<24 hex> amount=<tiyin>`,
one per line, and nothing internal — so nobody has to edit our own labels out of it under time
pressure. The second is ours: the cashbox, the idempotency keys, the deadline, and a checkout
link per order.

**THE ORDERS DIE TWELVE HOURS AFTER YOU RUN IT, AND THAT IS THE TRAP ON THIS PAGE.**
`DEFAULT_INTENT_TTL_S` is `43_200`, and the gateway's container deliberately threads no setting
through to it — opening an intent is the *bot's* port, so a copy of that value in the gateway
would be a second place to configure the link's lifetime with only one of them ever read. The
expiry sweep then flips `pending` to `expired`, and every `CheckPerformTransaction` afterwards
answers **`-31053`** — a refusal that reads, to the person testing us, exactly like a broken
merchant. **Open them on the day, not the night before.** If the slot slips, run it again with a
fresh `--label`; the printed table states each order's deadline for this reason.

The TTL is deliberately *not* extendable for a certification run, and the temptation should be
resisted: twelve hours matches the rail's own transaction window, and an order that outlives a
real customer's order is no longer the thing being certified.

**Reading them back afterwards.** Every key is `certify:<label>:<n>`, which is neither the bot's
`topup:{id}:{scope}:{seq}` nor the harness's `harness:{run}:{scenario}`. An operator with only
the journal in front of them can tell an order opened *for Payme to test* from a customer's real
purchase and from a rehearsal, months later, from the key alone. `payme.cli journal --since`
takes it from there.

Re-running with the **same** `--label` is safe and hands back the *same* orders rather than
opening more — `open_intent` is idempotent on the key. That is the way to re-print a table you
have lost, and it is not a way to refresh an expired one.

### D. Production — two restarts, no code change

1. Production key into `/etc/bayram/payme.env`; `BAYRAM_PAYME_IS_SANDBOX=false`;
   `BAYRAM_PAYME_CHECKOUT_BASE_URL` cleared so it derives to `checkout.paycom.uz`; the real
   `BAYRAM_PAYME_MERCHANT_ID` into `/etc/bayram/bot.env`.
2. `BAYRAM_CHECKOUT_PROVIDER=payme` **and** `BAYRAM_CREDITS_ENFORCED=true` in the **same edit** —
   `src/bayram/main.py` refuses to boot on a live rail with a dark credit meter, so they cannot be
   moved separately. `BAYRAM_KIT_PRICE_AMOUNT_MINOR` stays `0`; it is the render gate's quote, not
   the checkout's.
3. Restart the gateway, **then** the bot. In that order: the endpoint must be able to answer
   before the first link exists.
4. Arm the pause switch (`python -m bayram.payme.cli status`) before the first customer sees a
   button, so it is known to work rather than assumed.
5. Buy one song with a real card. Then refund it in the cabinet and confirm the `-31007`
   refusal appears in the journal — that is the designed behaviour (§7), and seeing it once
   deliberately is better than meeting it during an incident.

---

## 7. The manual-refund runbook

**There is no automated refund, by decision** — `CancelTransaction` on a performed transaction
answers `-31007` unconditionally, which is also PaycomUZ's own template's default behaviour.
The reason is in `PAYME_INTEGRATION` §6: `credit_accounts.balance` is a single fungible scalar
with no lot structure (`src/bayram/db/plan_sql.py:15`), so an automated reversal of purchase A can
debit a credit the customer paid for in purchase B.

A refund is therefore two actions by two systems, and **the money moves first**:

1. **Read the case.** `python -m bayram.payme.cli journal --ref <public_ref>` prints the intent,
   every transaction on it, the receipt and grant rows found under its idempotency key, the
   notification status, and every RPC we received about it. Establish whether the credit has
   already been **spent** — that changes step 3.
2. **Refund in the Payme cabinet.** This repository cannot do it and has no method that could;
   there is no outbound Merchant API for a merchant to call.
3. **Correct the credit.**
   * *Unspent*: debit it with `python -m bayram.tools.credits`, with a reason naming the Payme
     transaction id.
   * *Already spent*: the song was delivered. Do **not** drive the balance negative to chase
     it; record the write-off and stop. A negative balance breaks
     `credit_sql.verify_balances`, which arm four of the sweep asserts on every run — every
     five minutes as deployed, not hourly — and you will be paged by your own reconciliation.
4. **Expect `-31007` in the journal.** When Payme's system asks us to reverse, we refuse, and
   that refusal is correct. Confirm it appears; its absence means Payme never asked, which is a
   different conversation.
5. **Record it** where your accounting lives. `topup_purchases` is append-only and has no
   `refunded_at` column — deliberately — so this repository is not the record of a refund.

The opposite incident — **the customer paid and got nothing** — is the common one and has a
button:

```bash
python -m bayram.payme.cli settle --ref <public_ref> --note "paid 2026-09-09, cabinet tx <id>"
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
ssh aizu 'sudo systemctl stop bayram-payme'
ssh aizu 'sudo -e /etc/hbd/payme.env'             # host path today; replace the merchant-key line
ssh aizu 'sudo systemctl start bayram-payme && systemctl is-active bayram-payme'
```

Notes that matter:

* **Stop first, then edit.** A running process holds the old key in memory; editing under it
  leaves the file and the behaviour disagreeing until something restarts, which is the state in
  which a rotation gets declared done and is not.
* **Downtime here is safe.** Payme retries, and `CreateTransaction`/`PerformTransaction`/
  `CancelTransaction` are all replay-safe by construction (`PAYME_INTEGRATION` §5). A minute of
  502s from Caddy costs nothing but noise in their retry log. One caveat from §4: with the
  gateway stopped, Caddy answers `502` and **Cloudflare may substitute its own page for that
  502 before Payme sees it**. The retry behaviour is the same either way, but do not go looking
  for those minutes in `journalctl -u hbd-payme` — the requests never reached us, by design.
* **"Downtime is safe" is true of transactions and false of links, and nothing in the system
  closes that gap for you.** The replay-safety argument above is about a transaction Payme has
  already *created*; an intent still `pending` has no transaction, so none of it applies. Two
  processes keep running while the gateway is stopped, and both of them make the situation worse:
  * **the bot keeps quoting.** `PaymeCheckoutProvider.charge` opens no socket and owns no HTTP
    client — that is the whole of `src/bayram/payme/provider.py`'s opening claim, pinned by
    `tests/test_payme/test_provider.py::test_the_payme_provider_holds_no_http_client` — so there
    is **nothing in it that could notice the gateway is gone**. It opens intents and hands out
    checkout links at exactly the rate it did before. A customer who taps one reaches Payme,
    Payme asks us, and nothing answers.
  * **the worker keeps expiring.** Arm one of the sweep is `expire_lapsed`
    (`src/bayram/runtime/payme_jobs.py:628-630`), it runs every five minutes in `hbd-worker` — a
    different unit, untouched by a gateway restart — and it flips `pending → expired` at
    `valid_until` without consulting anything about the gateway. So **a gateway outage longer
    than the shortest remaining `valid_until` silently converts live links into `-31053`**, and
    the customer holding one sees a refusal that reads as a broken merchant.

  The intent *under a live transaction* is structurally safe and stays safe — it is not in the
  expiry predicate's set at all (`PAYME_INTEGRATION` §2.3) — so the exposure is confined to
  `pending`. **The control is the pause switch, and the order is: pause, then stop.** `pause`
  stops the bot quoting; it is read in the bot and never in the gateway, so stopping the gateway
  is not a pause and a paused rail is not a stopped gateway. A one-minute key rotation does not
  need it. Anything that could run long — a rename cutover, a Postgres upgrade, a host move —
  does, and `09-payme-go-live.md` §9.1's *"do not stop the gateway as part of a rollback"* is the
  same fact approached from the other side.
* **The boot line names the length, never the value.** The settings model logs the key's
  **length** at INFO on boot, deliberately, so a truncated paste is visible without the secret
  ever being printed. There is no assertion that the length is 36: the documentation says 36
  but the TEST_KEY's length is unverified, and a wrong length assertion is a boot failure on
  go-live day.
* **The rotation itself needs no password.** `/etc/sudoers.d/hbd-deploy` covers the `hbd-payme`
  systemctl verbs and `tee` of `/etc/hbd/payme.env` (§11.1), which is exactly the set this
  runbook needs and deliberately not `sudo -e`. Rewrite the file with `tee`, do not edit it in
  place.
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

**Automated, on every worker sweep — every `BAYRAM_PAYME_SWEEP_MINUTES`, five by default and
five as deployed — over a rolling 24-hour window.** The cadence and the window are different
numbers on purpose: a defect that appeared at 03:00 must still be visible at 09:00 when
somebody is awake to read it. The invariant is three-way:
performed `payme_transactions` == receipts with `provider='payme'` == credit grants under those
idempotency keys. A mismatch is logged at ERROR with all three numbers and is **never
self-repaired**, because it would be a defect in the shared write primitive and an operator must
see it. Likewise, a performed transaction whose intent is not `paid` is logged and never quietly
fixed. `credit_sql.verify_balances` runs in the same arm — in the worker, on a schedule, never
inside a JSON-RPC request that must answer in milliseconds.

```bash
ssh aizu 'journalctl -u hbd-worker --since "24 hours ago" -o cat | grep -i "payme.*invariant"'
python -m bayram.payme.cli invariant --hours 24
```

**Manual, weekly, by a human.** Diff our statement against the cabinet's export:

```bash
python -m bayram.payme.cli statement --from 2026-09-01T00:00:00Z --to 2026-09-08T00:00:00Z
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
| Every payment fails; journal shows `-31050` | The cabinet's «Настройка Аккаунт» versus `BAYRAM_PAYME_ACCOUNT_FIELD` (§5.1). The log line names both. |
| Payme reports errors we cannot see at all | **The public path, and in this order.** (1) `curl` the endpoint without `-L` and read the status — a `308` is §4.3 and is the single most likely cause. (2) Cloudflare's event log for the hostname: a challenge or a WAF block never reaches us and never appears in our journal (§4.6). (3) Only then `journalctl -u hbd-payme` and `journalctl -u caddy` — the unit is still `hbd-payme` on the host, and a `bayram-payme` that "could not be found" is the rename, not a missing gateway. The gap between "Payme says it failed" and "we logged nothing" *is* the diagnosis: the request died upstream. |
| The endpoint looks healthy to every check we have, and Payme cannot use it | §4.3, the 308 trap. `curl -I` is green, `-L` is green, `systemctl is-active` is green, and Caddy is redirecting every tunnelled request back to itself. `curl -sS -o /dev/null -w '%{http_code} %{redirect_url}\n' -X POST https://pay.bayrambot.uz/payme -d '{}'` — and note the **absence** of `-L`. |
| `systemctl reload caddy` fails with "permission denied" on a log file | §4.4. A `sudo caddy validate` created `/var/log/caddy/<site>.log` as `root:root`. `sudo install -o caddy -g caddy -m 600 /dev/null <that file>`, or move the block to `output stderr` as the Payme block does. It fails the whole reload, not one site. |
| Every `peer_ip` in the journal is `127.0.0.1` | **Correct, and not fixable by configuration you should be changing.** That is Caddy's address; the tunnel and proxy chain sit above it and `payme_trusted_proxy_hops` is deliberately `0` (§4.5). Do not raise it to make the log prettier — the value would be load-bearing for a filter that mints credits, and it is a header. |
| A burst of `-32504` | Wrong key, wrong login, or somebody probing. The line records the login **received**; if it is not `Paycom`, that answers `PAYME_INTEGRATION` §7.1. If it is unfamiliar, rotate (§8). |
| Gateway boots, `/healthz` is 200, every method is `-32400` | Almost always the database role (§3.2) or a pool exhausted (§3.1). |
| A customer paid and got nothing | `python -m bayram.payme.cli journal --ref <ref>`, then `settle --ref … --note …` (§7). |
| The customer was charged but never told | The notification is an ARQ job; the sweep re-enqueues anything unnotified and older than 60 seconds, so the ceiling on the silence is `BAYRAM_PAYME_SWEEP_MINUTES`. Check the worker is running before anything else. |
| Sales stopped with no error | The Redis pause key. `python -m bayram.payme.cli status`. Note the honest failure mode: a Redis rebuild silently **un**-pauses the rail, so re-check after any Redis restart. |
| You paused by hand with `redis-cli` and the rail is still selling | **Resuming is a `DELETE`, not a falsy write**, so presence is the signal and `redis-cli SET <key> 0` does **nothing**: `0`, `""`, `false`, `no` and `off` are all in `_OPEN_VALUES` and all read as open (`src/bayram/payme/pause.py`, `PAUSED_VALUE` / `_OPEN_VALUES`). That is deliberate — the alternative is `SET … 0` quietly pausing the rail, the exact opposite of what the person typing it meant. Use `cli pause`, or the console's switch; if you must use `redis-cli`, the value is `1` and the key is the one the **running** wheel spells (`hbd:payme:paused` on this host today, §11.6). |
| The gateway is stopped or restart-looping, and customers are still being handed checkout links | **Expected, and it gets worse on its own.** Nothing in the bot can notice: `charge` owns no HTTP client by design. Nothing in the worker stops either: the expiry arm keeps flipping `pending → expired`, so every outstanding link becomes a `-31053` as its twelve hours run out. **Pause first, then stop** — see the second bullet of §8. The journal will show nothing at all for the outage window, because the requests never reached us. |
| An edit to a dotenv file changed nothing, and nothing complained | Check which file the process actually reads before anything else: `journalctl -u hbd-payme -o cat \| grep payme.boot.ok \| tail -1` prints `env_file`. Since 2026-09-10 this host has **two** trees of dotenv files, `/etc/hbd/*.env` (read) and `/etc/bayram/*.env` (not read by anything) — the NAMING box at the top of this page, and §11.6. pydantic-settings also ignores an unrecognised prefix silently, so a `BAYRAM_`-spelled variable in the right file is equally quiet. |
| A duplicate-transaction scenario fails in certification | `BAYRAM_PAYME_DUPLICATE_TRANSACTION_CODE` (`PAYME_INTEGRATION` §7.2). Payme's own materials contradict each other here. |

---

## 11. Release runbook — the `0014 → head` deploy, as it was actually executed

**This is not the routine deploy of [`04-release.md`](04-release.md).** That document describes
a git checkout, a `git pull`, a dependency sync and a console rebuild on the host. **There is
no git checkout on this host.** `04-release.md` is still correct about the *code* — the gates,
the restart order, what can and cannot be rolled back — and wrong about the *shape* of a
deploy here, because it was written before anybody had looked at the box.

What follows is the procedure that put revisions `0015`–`0024` and the gateway onto `aizu` on
2026-09-09, written from the script that did it (`deploy/deploy-payme.sh`) and re-checked
against the host on 2026-09-10. Every ordering decision in it is load-bearing and each one
below says which failure it prevents.

### 11.1 The model: a wheel, not a checkout

`/opt/hbd` holds no source tree. A release is a wheel built on a developer machine
(`uv build --wheel`), copied into `release/`, and installed into the venv. The account that does
this is `developer`, which **owns** `/opt/hbd`; the services run as `hbd`; and the two are
deliberately not the same user.

**It held three things — `venv/`, `release/`, `migrations/` — until 2026-09-10. It now holds
six, and one of them has been swapped out from under the sudoers rule.** `[HOST 2026-09-11]`,
`755 developer:developer` throughout:

```
cutover-to-bayram.sh            9271  Sep 10 14:03   the rename, 9 steps — see §11.6
deploy-payme.sh                  434  Sep 10 14:28   NO LONGER THE DEPLOY SCRIPT (below)
deploy-payme.sh.pre-cutover.bak 4814  Sep 10 14:04   the 0014 → head deploy this section describes
diagnose.sh                      536  Sep 10 14:29   a read-only Postgres privilege probe
migrations/                            Sep  2 10:20
release/                               Sep 10 14:03   five wheels now, not four — §11.2
venv/                                  Sep  5 17:56
```

**`deploy-payme.sh` is the path the NOPASSWD sudoers rule names, and its contents have been
replaced.** It is now six lines `[HOST 2026-09-11]`, quoted verbatim because the mismatch between
what it says and what it does is the point:

```bash
#!/usr/bin/env bash
# SUPERSEDED 2026-09-10. The hbd-wheel deploy this file used to perform is obsolete: the package
# is now `bayram` and the four units, /opt and /etc all move with it. The sudoers drop-in names
# THIS path, so this file is the wrapper that runs the cutover as root. The work itself is in
# cutover-to-bayram.sh, kept as its own readable file rather than pasted in here.
exec /usr/bin/bash /opt/hbd/diagnose.sh "$@"
```

**Its comment is wrong about its own body.** It claims to be the wrapper that runs the cutover as
root; it runs `diagnose.sh`, which is a read-only `psql` privilege probe and performs no cutover
at all. So `sudo bash /opt/hbd/deploy-payme.sh` today runs neither the deploy this section
documents nor the cutover the comment advertises. **Read the file before you run it.** The deploy
this section describes is the `.bak`, and `head -40 /opt/hbd/deploy-payme.sh` — which
`00-host-inventory.md` row 45 offers as its verify command — now reads six lines of something
else.

> **THIS IS A SECURITY FINDING AND IT IS NOT THIS PAGE'S TO CLOSE.** `/etc/sudoers.d/hbd-deploy`
> grants `(root) NOPASSWD: /usr/bin/bash /opt/hbd/deploy-payme.sh`, and that file is
> `755 developer:developer` — `[HOST 2026-09-11]` `test -w` confirms `developer` can rewrite it,
> and so can rewrite `diagnose.sh` behind it. **A NOPASSWD rule pointing at a path the invoking
> account can write is passwordless root for that account**, which makes the narrow verb list
> above decorative rather than limiting. It is not a theoretical shape: the file was retargeted
> once already, on 2026-09-10 at 14:28:31 — and `diagnose.sh`, the file it execs, was not written
> until 14:29:20, so for forty-nine seconds the NOPASSWD root entry point pointed at a file that
> did not exist. Note the times against the rest of the day: the services came back at 14:08, so
> this repointing is **post-mortem diagnosis and not part of the cutover**. The fix is to make the
> target root-owned and the directory not writable by `developer`, and **the rename is the one
> scheduled change that has to rewrite this drop-in anyway** (§11.6), which makes it the cheapest
> moment to fix the shape. `07-security.md` is where the finding belongs in its own right; it is
> flagged here because §11.1 is the section that tells people to run the thing.

Why a wheel rather than the checkout `04-release.md` assumes:

* **A checkout on a payment host is a build toolchain and a remote.** `git pull` is an
  operation whose result depends on what somebody else pushed, resolved on the box, under
  time pressure. A wheel is one file with one hash that was built and tested somewhere else,
  and "is the host running what I tested" is answerable by comparing that hash rather than by
  reasoning about a working tree's state.
* **Rollback becomes a file that is already there.** `release/` keeps a `-ROLLBACK-` copy
  (`hbd_bot-0.1.0-ROLLBACK-20260905.whl`, present 2026-09-10), so the recovery path needs no
  network, no remote and no revision resolution — see §11.7 for the half of a rollback that
  this does not buy.

And the price, which is the whole of §11.3: **a wheel carries only the package.** Migrations,
unit files and Caddy blocks are separate copies, and nothing about installing a wheel notices
that they are missing.

**Privilege.** `developer` has full `sudo` **only with a password**. A NOPASSWD drop-in at
`/etc/sudoers.d/hbd-deploy` narrows a specific list for this work: `bash /opt/hbd/deploy-payme.sh`,
`systemctl daemon-reload`, the seven `hbd-payme` verbs, **`restart` and only `restart`** of
`hbd-bot`/`hbd-worker`/`hbd-admin`, `caddy` reload/restart, `caddy validate` with its exact flags,
`tee` of `/etc/hbd/payme.env` and `/etc/caddy/Caddyfile`, `journalctl -u hbd-payme *`, and
`pg_dump hbd` as `postgres`. §3.2 carries the list verbatim as of `[HOST 2026-09-11]`, with what
`sudo -l` can and cannot tell you about which file a rule came from. **The "only `restart`" is
load-bearing and is easy to read past**: there is no NOPASSWD `stop`, `disable` or `enable` for
the bot, the worker or the admin API, so any procedure that stops or re-enables those three
prompts for a password — half of the rename cutover included (§11.6). The drop-in is revoked with
one line:

```bash
ssh aizu 'sudo rm /etc/sudoers.d/hbd-deploy'
```

Two things about that list are deliberate and worth not "improving". It does **not** include
`psql`, which is why §3.2's grant check still cannot be run unattended — the drop-in authorises
a deploy, not arbitrary database access. And there is a **separate, pre-existing** NOPASSWD
rule for an unrelated service on this box (`/etc/sudoers.d/aizu-deploy`); deleting the wrong
file breaks somebody else's product.

### 11.2 PEP 427: the wheel filename is a data structure, not a label

`hbd_bot-0.1.0-PAYME-20260909.whl` was **rejected**:

```
Invalid wheel filename (wrong number of parts): 'hbd_bot-0.1.0-PAYME-20260909'
```

The name is parsed, not read. PEP 427 fixes it as
`{distribution}-{version}(-{build})?-{python}-{abi}-{platform}.whl` — five parts, or six with
a build tag. `hbd_bot-0.1.0-PAYME-20260909` has four, so `pip` cannot map them onto the fields
and refuses before it opens the archive. (A build tag would not have rescued `PAYME` anyway:
PEP 427 requires it to start with a digit.)

The name that works puts the date where the build tag goes, which is legal precisely because
it starts with a digit:

```
hbd_bot-0.1.0-20260909-py3-none-any.whl
```

**Why this deserves a paragraph rather than a footnote.** The rejection happens at `pip
install` — step 4 of 6, *after* the wheel has been built, copied to the host, the window
scheduled, and the database backed up and migrated. It is the most annoying possible place to
discover a typo, and it costs a window. Check the shape before you copy the file, not after:

```bash
python -c 'import sys; from packaging.utils import parse_wheel_filename as p; print(p(sys.argv[1]))' \
  hbd_bot-0.1.0-20260909-py3-none-any.whl
```

The general rule this leaves behind: **never encode a human-readable label in a wheel
filename.** `release/` on `aizu` today still contains `hbd_bot-0.1.0-DASHBOARD-20260909.whl`
and `hbd_bot-0.1.0-ROLLBACK-20260905.whl`, both unparseable and both un-installable as they
stand (verified 2026-09-10) — the second of which is supposed to be the emergency artefact.
Anything you want to say about a build belongs in a note beside it or in the build tag.

**There are now five wheels there, not four** `[HOST 2026-09-11]`, and the fifth is the one a
rename window needs:

```
bayram_bot-0.1.0-py3-none-any.whl        5219850  Sep 10 14:03   PEP 427 valid. The cutover artefact — §11.6
hbd_bot-0.1.0-20260909-py3-none-any.whl  4958162  Sep  9 17:53   PEP 427 valid. What is installed today
hbd_bot-0.1.0-py3-none-any.whl           2996469  Sep  6 16:26   PEP 427 valid, and undated — see below
hbd_bot-0.1.0-DASHBOARD-20260909.whl     4958162  Sep  9 18:00   unparseable
hbd_bot-0.1.0-ROLLBACK-20260905.whl      2934287  Sep  6 16:25   unparseable. The emergency artefact
```

Two readings. The `bayram` wheel is both the proof that the rename's artefact exists and a
loaded gun in a directory `developer` can write: nothing stops a `pip install` of it into
`/opt/hbd/venv`, which is §11.6's failure-by-halves with no rename attempted at all. And
`hbd_bot-0.1.0-py3-none-any.whl` carries **no build tag**, so it is indistinguishable by name
from any other 0.1.0 build — it is a similar size to the `-ROLLBACK-` copy and was written one
minute after it, which is suggestive and is not a record. **Byte size and mtime are not
provenance.** If you need to know what is in a wheel, read its `dist-info`.

### 11.3 A wheel carries no migrations — and `alembic upgrade head` reports success anyway

**This is the most dangerous property in the entire procedure**, because its failure mode is a
green deploy.

`alembic upgrade head` means *the head of the revision files present in this directory on this
disk*. It does not know what revisions exist in a repository it has never seen. Copy the wheel
and forget `migrations/versions/*.py`, and alembic upgrades to whatever happens to be there,
**prints a revision, and exits 0**. The deploy log looks perfect. What you then have is new
code against a schema that is several revisions short, and the first symptom is a customer's
payment dying on `relation "payment_intents" does not exist`.

The script therefore asserts the files as a **preflight**, counting them on the filesystem:

```bash
PENDING=$(ls /opt/hbd/migrations/versions/*_00{15,16,17,18,19,20,21,22,23,24}_*.py 2>/dev/null | wc -l)
test "$PENDING" -eq 10 || { echo "FATAL: expected 10 pending migration files, found $PENDING"; exit 1; }
```

Counting files is cruder than comparing `alembic heads` against the repository, and it is the
right check *here* for one reason: it needs no database connection, no env file and no
privilege, so **it can run before the backup** — before anything irreversible has happened. A
check that can only fail after the irreversible step has already protected you from nothing.
The same preflight asserts the wheel exists, the env file exists, and
`/etc/systemd/system/hbd-payme.service` is installed, for the same reason: unit files are not
in the wheel either.

Verified 2026-09-10: `/opt/hbd/migrations/versions/` held `…_0024_add_broadcast_tables.py` as its
newest revision, so the ten files did land.

**Both halves of that have moved, and they have moved apart.** `[HOST 2026-09-11]`:

* **On disk there are now 25 revision files**, the newest being
  `20260910_1000_0025_index_settlement_clocks.py`, written 2026-09-10 — and the same 25 were
  copied to `/opt/bayram/migrations/versions/` by the aborted cutover (§11.6).
* **The database is at `0024`.** Re-read today, with no password, through
  `sudo -n -u postgres /usr/bin/pg_dump hbd | grep -A3 "COPY public.alembic_version"` → `0024`.
  This is the first re-verification since the deploy transcript of 2026-09-09 recorded the same
  number, and it replaces the "day-old fact" caveat this paragraph used to end on with a measured
  one. `00-host-inventory.md` row 15 is the row to keep in step with it.

**So the host is one revision behind its own disk, and `0025` is unapplied.** That matters twice
over. It is a live loose end — `alembic upgrade head` on this box will apply something, which is
not what anybody wants to discover during a rename window — and it is a load-bearing input to
§11.7's rollback argument, which holds only while the applied revisions are additive. `0025` adds
an index, so the argument extends. **It extends because somebody checked, not because it was
assumed**, and that is the whole reason this paragraph has a date on it.

### 11.4 The order, which is not the obvious one

```
0  preflight            (assert wheel, env file, unit file, ten migration files)
1  backup               pg_dump hbd | gzip  →  /var/backups/hbd/pre-payme-<stamp>.sql.gz
2  revision before      alembic current
3  MIGRATE              alembic upgrade head            ← before the wheel
4  install the wheel    pip install --force-reinstall --no-deps  &&  pip check
5  restart bot, worker, admin
5.5 give the gateway its database and queue
6  enable --now hbd-payme, then curl /healthz
```

**Backup first**, because it is the only step in the list that cannot be undone by running
something again. The script also refuses to continue on an empty dump (`test -s "$BACKUP"`) —
a `pg_dump` that fails on permissions still creates a zero-byte gzip, and a backup you did not
check is a backup you do not have.

**Migrations before the wheel, which is the inverse of the intuitive order.** "Ship the code,
then the data" is what most people reach for, and it is wrong here. Every revision `0015`–`0024`
is **additive** — new tables and new indexes, no column drops, no type changes — so for the
minute between step 3 and step 4 the **old** code is running against the **new** schema, and
old code ignores tables it has never heard of. Invert the order and that minute becomes new
code against an old schema, which tolerates nothing: the bot, the worker and the admin API all
restart into a schema missing the tables they were just taught to read.

Two things follow that are easy to get wrong later:

* **The precondition is a property of these ten revisions, not a rule of the project.** The
  first revision that drops a column, narrows a type or renames anything inverts the argument
  — old code then breaks against the new schema too — and the answer at that point is a
  maintenance window with both services stopped, not a cleverer ordering. Check the diff, do
  not inherit the order.
* **The gateway starts last, alone.** Steps 5 and 6 are separate on purpose: the three existing
  units restart and are asserted healthy before the one genuinely new process is started, so a
  failure at step 6 is attributable to the gateway rather than to a fleet that was already
  broken.

### 11.5 `pip install --no-deps`, and the `pillow` lesson

Step 4 installs with `--force-reinstall --no-deps` and follows it immediately with `pip check`.
The script's own comment explains the `--no-deps` as *"this release adds no new runtime
dependency: the gateway is FastAPI and uvicorn, which the admin process already brought in."*

**That assertion was false.** `pillow` was a new runtime dependency in this release —
`pyproject.toml` pins `pillow>=10.4,<12` for the generated cover art — and `--no-deps` left it
out of the venv. `pip check` on the very next line caught it, and because the script runs under
`set -euo pipefail` the deploy stopped there: **before step 5, before any service restarted.**
The fix was one `pip install pillow` and a rerun. Verified 2026-09-10: `pillow 11.3.0` is
installed in `/opt/hbd/venv`.

**The lesson is not "stop using `--no-deps`."** It is the right default on a payment host, and
for a reason worth stating: dependency resolution during a deploy can upgrade a transitive
package nobody chose and nobody tested, at the exact moment you have least appetite for
surprise. What makes it *safe* rather than merely fast is the line after it. `--no-deps` states
an assumption; `pip check` turns that assumption into an assertion that fails the deploy
instead of a hope that fails a customer.

Two things to keep, therefore:

* **`pip check` must stay immediately after the install**, in the same script, before the
  restarts. Moved to the end, or into a separate "verification" step somebody skips, it
  protects nothing.
* **The comment in `deploy/deploy-payme.sh` is now stale** — it still claims the release adds
  no new runtime dependency, which is the exact belief that was wrong. Correct it when you next
  touch that file, and correct it to the general rule rather than to a new list of
  dependencies, which will be stale again by the next release.

### 11.6 What the next release must do that this one did not: the rename

**IT HAS BEEN ATTEMPTED. On 2026-09-10 it ran and stopped part-way through, and the host has sat
in the half-state ever since.** That is the first thing to know, because every other document in
this tree was written against "the rename has landed in the repository and not on the host", and
that sentence was true on the morning of 2026-09-10 and has not been true since 14:06.

A wheel install still renames nothing, and the `0014 → head` deploy of §11 still did not attempt
it. What happened afterwards is a separate, undocumented operation.

#### What is on the host now

`[HOST 2026-09-11]`, all of it:

| | State |
| --- | --- |
| `/opt/hbd/cutover-to-bayram.sh` | **exists** — 9271 B, `755 developer:developer`, written 2026-09-10 14:03. A 9-step script under `set -uo pipefail` (no `-e`), whose header reads *"hbd -> bayram cutover. Run ON THE HOST as root: sudo bash /opt/hbd/cutover-to-bayram.sh"*. The same file is in this working tree at `deploy/cutover-to-bayram.sh`, byte-identical — md5 `c01caf751134f9d3d7e8c9a6f6d7bafa` on both — and **untracked by git** |
| `/etc/bayram/` | **exists**, `0755 root:root`, holding `bayram.env` (1148 B), `bayram-admin.env` (11213 B) and `payme.env` (361 B), each `0640 root:hbd`, all 14:06. Nothing reads any of them |
| `/opt/bayram/venv` | **exists**, `755 root:root`, built 14:06–14:07. A **fresh** venv, not a moved one: package `bayram`, `bayram_bot-0.1.0.dist-info`, and `pillow 11.3.0` (the §11.5 dependency). Nothing executes it |
| `/opt/bayram/migrations/versions/` | **exists** — a copy of all 25 revision files, including the unapplied `0025` (§11.3) |
| `bayram-*.service` | **none.** Nothing in `/etc/systemd/system/` but the four `hbd-*` units, all `enabled` and `active` |
| the `bayram` OS user and group | **do not exist.** `getent passwd bayram` and `getent group bayram` both return nothing |
| the database | **still at `0024`** (§11.3), with `0025` on disk in both trees |
| two new backups | `/var/backups/hbd/pre-cutover-20260910-140505.sql.gz` (15468 B) and `pre-cutover-20260910-140653.sql.gz` (15466 B). Both smaller than the five `pre-payme-*` dumps, which is the 2026-09-10 wipe-and-rebuild rather than data loss |
| the services | stopped 14:05:06–14:05:07, started again 14:08:00–14:08:01, `NRestarts=0` on all four — **a clean stop and a manual restart, not a crash.** They were then restarted by hand a second time on 2026-09-11 at 06:50:11–06:50:13, with no reboot in between |

**Two `pre-cutover` dumps, one stop event.** The script dumps before it stops, so two dumps fits
two runs — a second run at 14:06:53 would have issued `stop` against already-stopped units, which
journals nothing. It also fits one run plus a separate manual `pg_dump`. **Which it was is
`[UNPROVEN]`**; settling it needs the operator's shell history. The `/etc/bayram` and
`/opt/bayram` timestamps (14:06:5x) sit inside the second window, which is the strongest thing
pointing at two.

**Where it stopped, precisely, because the step boundaries matter to whoever resumes it.** Step 4
builds the venv. Step 5 is three statements in order: `cp -a migrations`, then `alembic current`,
then `alembic upgrade head`. The migrations copy exists and the schema did not move, so **the
abort is inside step 5, at one of the two alembic calls** — not "after step 5" and not "at step
4". Steps 6 to 8 — write the `bayram` units, disable the `hbd` ones, enable the new ones — never
ran, which is why the rollback the script documents was never needed.

#### Why it stopped — inference, clearly marked

**`[UNPROVEN]`, and the blocker is named: the alembic run happened in an interactive root shell,
so nothing about it reached the journal and there is no record to read.** What can be said is
circumstantial and coherent:

* `/opt/hbd/diagnose.sh` was written at 14:29:20 — 21 minutes *after* the services came back — and
  it probes exactly `has_schema_privilege('hbd','public','CREATE')`,
  `has_schema_privilege('hbd','public','USAGE')`, the `alembic_version` owner and the distinct
  table owners. Somebody was asking whether the **migration role `hbd`** may create in `public`.
* The dump answers the neighbouring question: `[HOST 2026-09-11]` the only privilege statements in
  the database are `REVOKE USAGE ON SCHEMA public FROM PUBLIC` and
  `GRANT ALL ON SCHEMA public TO hbd_app`, and every object is owned by `hbd_app` (§3.2).
  **There is no grant to `hbd` anywhere.**

So a schema-privilege failure for the migration role is the shape the evidence fits. **From this
page it is not proven and must not be written down as though it were** — the causal link needs
`psql`, which is the one thing the NOPASSWD drop-in does not grant, and nothing about an
interactive root shell reaches the journal. **It is also the blocker: the cutover cannot be re-run
until this is answered**, and re-running the script without answering it spends another window and
another pair of stopped services. [`10-rename-cutover.md`](10-rename-cutover.md) §2.3 and §4.1 are
where that question is worked through and where any harder evidence will land; if it has been
settled there, that page wins over this paragraph.

#### The inventory — what the rename touches

Extended from what this section used to carry; the rows marked **new** are ones a checklist
derived from the old table would have missed entirely.

| What changes | Where | Verified |
| --- | --- | --- |
| the imported package name | the wheel, and every unit's `ExecStart` module path — `-m hbd.main`, `-m arq hbd.worker.WorkerSettings`, `-m uvicorn hbd.admin.app:app`, `-m uvicorn hbd.payme.app:app` | `[HOST 2026-09-11]` |
| the unit names | four files in `/etc/systemd/system/`, plus `daemon-reload`, plus `enable` | `[HOST 2026-09-11]` |
| **the `Environment=` / `EnvironmentFile=` split — three shapes, not one** (new) | `hbd-bot` and `hbd-worker` carry `EnvironmentFile=/etc/hbd/hbd.env`; `hbd-admin` carries `EnvironmentFile=/etc/hbd/hbd-admin.env`; `hbd-payme` carries `Environment=HBD_PAYME_ENV_FILE=/etc/hbd/payme.env` **plus** `InaccessiblePaths=/etc/hbd/hbd.env /etc/hbd/hbd-admin.env`. They are not interchangeable and the host's cutover script preserves the split exactly | `[HOST 2026-09-11]` |
| the dotenv directory **and the filenames** | `hbd.env` → `bayram.env`, `hbd-admin.env` → `bayram-admin.env`, `payme.env` keeps its name. The pointer's **value** moves too, not just its key | `[HOST 2026-09-11]` |
| **every environment variable prefix** | the contents of all three dotenv files. `ENV_PREFIX` is `"HBD_"` / `"BAYRAM_"` at `config.py:75` in each package; `:90` derives `ENV_FILE_VAR` and `:171` derives `FOREIGN_SECRET_ENV_VARS`, so the gateway's own env-file pointer **and** the panel's forbidden-variable guard both move with the prefix | `[HOST 2026-09-11]` |
| the venv and state paths | `ExecStart`, `WorkingDirectory` | `[HOST 2026-09-11]` |
| the service user and group | **they do not move, by decision.** The script keeps `User=hbd`, `Group=hbd`, `WorkingDirectory=/var/lib/hbd`, `ReadWritePaths=/var/lib/hbd /var/log/hbd`, and says why in its own words: *"That account owns the media archive; renaming it means chowning customer artefacts during a cutover, which is risk bought for tidiness."* `hbd` is uid 995, gid 986, `/var/lib/hbd` is `0750 hbd:hbd` | `[HOST 2026-09-11]` |
| the NOPASSWD drop-in | `/etc/sudoers.d/hbd-deploy` names units and paths by their old names — **and half the cutover was never covered by it even before the rename**: there is no NOPASSWD `stop` or `disable` for the bot, worker or admin, and no `enable` for anything but `hbd-payme`. Expect a password prompt at the stop, at the disable, at the enable and at the Gate C re-run (`sudo -u hbd env …` is not on the list either) | `[HOST 2026-09-11]` |
| **nine Redis key prefixes, not one** (new) | the installed `hbd` package spells `hbd:admin:budget`, `hbd:admin:reveal:window`, `hbd:admin:rl`, `hbd:admin:session`, `hbd:bot:rl`, `hbd:payme:paused`, `hbd:send:budget`, `hbd:send:park`, `hbd:settings:version` — each with a `bayram:` twin in the new wheel. The rate-limit and send-budget buckets (`bot:rl`, `send:budget`) reset to zero at the cutover, which is probably fine and is worth one sentence rather than a surprise | `[HOST 2026-09-11]` |
| **the admin session mirror and both cookies** (new) | `_MIRROR_PREFIX` moves `hbd:admin:session` → `bayram:admin:session` (`admin/sessions.py:80`), `CSRF_COOKIE_NAME` moves `__Host-hbd_csrf` → `__Host-bayram_csrf` (`admin/csrf.py:58`), and `settings.py:650` moves `__Host-hbd_session`. **The cutover ends every admin session and voids every CSRF token in every open tab.** Harmless if expected; an operator mid-refund sees a failed POST rather than a login screen | `[HOST 2026-09-11]` |
| **the served console's CSP nonce placeholder** (new) | the shipped SPA shell carries `<meta name="csp-nonce" content="__HBD_CSP_NONCE__">` and the server substitutes `CSP_NONCE_PLACEHOLDER` (`admin/shell.py:55`), raising at `:78` if it is absent. Both sides are internally consistent, so the coupling is **atomic with the wheel** — but hand-copying a `static/` directory across the cutover breaks the console with a nonce-less CSP and no obvious cause. The console's per-browser keys (`hbd.dashboard.{locale,theme,navRailCollapsed,rememberedUser}`, `hbd.admin.bootstrap`, the `hbdBot` window global) move too: operators lose theme, locale, nav-rail state and remembered username, and nothing else | `[HOST 2026-09-11]` |
| **a dead `Documentation=` line** (new) | `hbd-payme.service` carries `Documentation=file:///srv/hbd/deploy/README.md`, and `/srv` is empty. Harmless, and a fifth place the old name is written into a unit file | `[HOST 2026-09-11]` |
| **`/etc/bayram`'s mode** (new) | the script does `chmod 0755` on the new directory and copies mode and owner only for the **files** (`chown --reference`, `chmod --reference`), so `/etc/hbd` is `0750 root:hbd` and `/etc/bayram` is `0755 root:root`. Filenames are not secret, but this is an unremarked permission downgrade **that is live on the host right now** | `[HOST 2026-09-11]` |
| **the dotenv key inventory** (new) | `[UNPROVEN]` and it has to be closed **before** the window: the rewrite is `sed 's/^HBD_/BAYRAM_/'`, so any line not starting `HBD_` is copied through verbatim into a settings model that no longer reads it — the exact mirror of the renamed-variable failure and exactly as silent. `/etc/hbd` is `0750 root:hbd` and untraversable as `developer`, so neither the key counts nor the presence of an unprefixed line can be established from here. One `sudo grep -cv '^HBD_\|^#\|^$' /etc/hbd/*.env` settles it. The tree's examples have no unprefixed keys at all (`.env.example` 100/100 `BAYRAM_`, `.env.admin.example` 37/37, `.env.payme.example` 20/20), which is suggestive and is not the host | `[UNPROVEN]` — the blocker is the permission wall on `/etc/hbd` |

#### What deliberately does **not** move, and how to tell

Half the value of a rename inventory is stopping people renaming things. All of these were
checked `[HOST 2026-09-11]`:

* **The database name `hbd`, and the two Postgres function names.** The `bayram` package still
  hard-codes `"hbd_purge_audit_log"` and `"hbd_purge_audit_reasons"`
  (`src/bayram/db/admin/audit.py:122-123`, matching migrations `0007` and `0011`) — Postgres
  identifiers were held stable across the rename **on purpose**, and that is the precedent that
  covers the database name too. `09-payme-go-live.md` §2 carries the full list of places `hbd`
  appears as a database, role, backup directory and sudoers argument; every one of them is a
  further argument against renaming it.
* **The ARQ queue and job ids.** Neither package defines a `queue_name`, so arq runs on its
  default: live Redis shows `arq:queue:health-check` and in-progress keys of the form
  `run_payme_sweep:<ts>`, derived from function names and the intent's `public_ref`. **The queue
  and any in-flight job survive the cutover intact** — this is the one moving part that looks like
  a hazard and is not.
* **The aiogram FSM keys**, `fsm:<id>:<id>:data` and `:state` — unprefixed, so a customer with a
  half-finished order keeps their conversation state.
* **The Caddy site config**, and this is the sharp one: **every `hbd` token in
  `/etc/caddy/Caddyfile` is inside a comment.** Nothing functional names the old name, no reload
  is required by the rename, and a `sed` over that file would rewrite verified host transcripts
  into fiction. Leave it alone.
* **The cloudflared tunnel.** `ExecStart=… tunnel run --token-file /etc/cloudflared/token` and
  `/etc/cloudflared/` holds exactly that one file. There is no `config.yml`; the ingress is in the
  Cloudflare dashboard (§4.1). No Cloudflare change is part of this.
* **The repository's `admin-dashboard/` source**, which is already fully renamed —
  `[TREE 2026-09-11]` zero `hbd`/`HBD` occurrences across `admin-dashboard/src`,
  `admin-dashboard/index.html` and `admin-dashboard/package.json`. The console's name-bearing
  strings reach the host inside the wheel's `admin/static/` bundle, not from there.

#### The failure if it is done by halves — now a mechanism, not an assertion

Install a `bayram`-packaged wheel while the unit still says `hbd.payme.app:app` and the gateway
raises `ModuleNotFoundError`. **It then loops forever instead of going red, and the arithmetic is
why.** `[HOST 2026-09-11]` `hbd-payme` is `Restart=always`, `RestartUSec=5s`,
`StartLimitIntervalUSec=10s`, `StartLimitBurst=5`: at one start per five seconds only two starts
fall inside any ten-second window, so the burst of five is **never reached**, the unit never
enters `failed`, and `systemctl is-active` keeps a straight face. The other three are
`Restart=on-failure` with the same timings and a non-zero exit, so they loop the same way. Meanwhile
the bot — if it restarted successfully — keeps serving a paywall. Payments visible, endpoint gone:
precisely the combination this whole subsystem is arranged to avoid, and **not** a combination any
unit state will report.

And because pydantic-settings reads **by prefix**, the dotenv rewrite and the wheel that reads it
must land in the same restart; a renamed variable is an *unset* variable, and an unset
`BAYRAM_PAYME_ENABLED` is a gateway that refuses to boot.

#### Where the rest of it lives

**This section demanded "its own document, its own window, and its own rollback plan", and as of
2026-09-11 the document exists**: [`10-rename-cutover.md`](10-rename-cutover.md), with its row in
[`README.md`](README.md)'s table. **That page is the authority for the operation and this one is
not.** Read it for the attempt and its transcript (§2), the directive-by-directive inventory (§3),
the preconditions that have to be true before a window opens (§4), and the rollback. What stays
here is only what a reader of *this* page needs: that the gateway's own ExecStart, env-file pointer
and `InaccessiblePaths` are three of the moving parts, and that the failure shape is a silent
restart loop rather than a failed unit.

Two things worth carrying across, because they are about the state the host is in **today** rather
than about the procedure:

* **There is a second rollback case and the script does not cover it.** It documents rolling back
  *from a completed cutover* — disable the `bayram` units, re-enable the `hbd` ones — and steps 6
  to 8 never ran, so there is nothing to disable. Abandoning a **partial** cutover is a different
  question (what to delete, what to keep, what is safe to leave) and
  `10-rename-cutover.md` is where it belongs.
* **The debris is not inert.** Step 3's rewrite is **not** guarded, so a second run silently
  overwrites `/etc/bayram/*.env` — harmless while `/etc/hbd` is the source of truth, destructive the
  moment anybody edits the new files first. Step 4 does `rm -rf "$NEW_ROOT/venv"` and is idempotent.
  And every day `/etc/bayram/*.env` sits there it drifts further from `/etc/hbd`, so a later step 6
  that installs units pointing at them ships stale configuration that boots cleanly.

Do not fold any of it into a routine wheel swap because the diff looked mechanical.

### 11.7 Rollback, and the half of it that does not roll back

**The wheel rolls back in about a minute.** Reinstall the `-ROLLBACK-` artefact from
`release/` — after renaming it to something PEP 427 accepts (§11.2) — and restart. No network,
no remote.

**The schema does not roll back at all, and should not.** `alembic downgrade` is deliberately
not part of this procedure: a downgrade of a payment schema is a data-destroying operation
being run by somebody who is already having a bad day. What makes a wheel-only rollback safe is
the same property that licensed the ordering in §11.4 — `0015`–`0024` are additive, so the
`0014`-era code simply ignores tables it does not know about. **That is the second time a single
property of these ten revisions is doing structural work; the moment it stops holding, both
arguments fail together.**

The backup is the schema's rollback, and it is a disaster instrument rather than a release one:
restoring `/var/backups/hbd/pre-payme-<stamp>.sql.gz` discards every row written since it was
taken, which after a real payment means discarding a receipt for money that moved. Reading
those files needs the sudo password; they are not readable as `developer`.

### 11.8 Idempotency, and the two variables the script copies by name

**Rerunning the script is safe and is the intended recovery from a partial run.** It re-dumps,
finds `alembic upgrade head` a no-op, reinstalls the same wheel, and restarts. Nothing in it
destroys data. That property is what let the `pillow` failure (§11.5) be recovered by fixing
one thing and running the whole script again, rather than by hand-executing the remaining
steps and hoping the order was right.

Step 5.5 is the one part that writes a secret-bearing file, and its shape is the argument:

```bash
for var in HBD_DATABASE_URL HBD_REDIS_URL; do
  if ! grep -q "^${var}=" /etc/hbd/payme.env 2>/dev/null; then …append…; fi
done
```

**Exactly two variables, by name, and only if absent.** Not a copy of `hbd.env`, and not a
merge. A blanket copy would drag all four outbound vendor credentials into the one process
whose entire justification is that it holds none (§1.1) — and would do so *past* the
application-level refusal, since that refusal only fires when `BAYRAM_ENVIRONMENT` is exactly
`prod`, which on this host it is not (§2.1). The "only if absent" guard is the other half: an
unconditional write would clobber a cashbox key an operator had already placed. Values are
never echoed to the log.

The script then sets `HBD_PAYME_ENABLED=true` and re-applies `root:hbd` `0640` to the file, and
**ends by printing that the rail is still off**. That closing line is doing real work rather
than being polite: it exists to stop the person who has just watched a successful payment
deploy scroll past from believing they have turned on payments. They have not. That is
`BAYRAM_CHECKOUT_PROVIDER`, on the bot, and it is a separate decision with a separate owner —
see the note at the top of this page, and §6.D.

### 11.9 What a green run looks like afterwards

None of these need a password:

```bash
ssh aizu 'systemctl is-active hbd-bot hbd-worker hbd-admin hbd-payme caddy cloudflared'
ssh aizu 'curl -sS -o /dev/null -w "healthz=%{http_code}\n" http://127.0.0.1:8091/healthz'
ssh aizu 'journalctl -u hbd-payme -o cat | grep payme.boot.ok | tail -1'
ssh aizu 'journalctl -u hbd-worker --since "1 hour ago" -o cat | grep -c "payme sweep finished"'
curl -sS -o /dev/null -w 'public root=%{http_code}\n' https://pay.bayrambot.uz/
```

Expected, and observed on 2026-09-10: six `active`; `healthz=200`; a `payme.boot.ok` line
whose `env_file` is the one you meant (§2.1 reads the rest of it); at least one sweep in the
last hour, since `run_payme_sweep` runs every five minutes and logs `{'intents_expired': …,
'transactions_timed_out': …, 'notifications_re_enqueued': …}`; and `public root=404`, which is
the tunnel, Caddy and the site block all agreeing (§4.2).

**What none of it proves is settlement.** Every command above is read-only. See the note that
opens §6.

---

## 12. The operator CLI — nine subcommands, and the refusals are the interface

Every runbook above reaches for `python -m bayram.payme.cli` and none of them says what is on it.
This section is that inventory. It is written from `src/bayram/payme/cli.py` `[TREE 2026-09-11]`,
which is the authority; nothing here is a host claim.

**Read three properties before the table, because they decide whether you can use this tool at
all at 2 a.m.**

* **It builds the GATEWAY's container**, so it reads `PaymeSettings` from
  `BAYRAM_PAYME_ENV_FILE` and **must run on the host holding that file**. On `aizu` today that
  means `sudo -u hbd env HBD_PAYME_ENV_FILE=/etc/hbd/payme.env /opt/hbd/venv/bin/python -m
  hbd.payme.cli …`, and the `sudo -u hbd` **will** prompt: `/etc/hbd/payme.env` is `0640
  root:hbd`, `developer` is not in `hbd`, and the NOPASSWD drop-in does not cover `-u hbd`
  (§11.1). **Budget for a human at a keyboard.**
* **It does not check `payme_enabled`, deliberately.** The first thing anybody does in a payment
  incident is switch the rail off, and a recovery tool that refused to run against a disabled rail
  would be unusable at precisely the moment it is needed. `status` reports the flag instead of
  obeying it.
* **Exit codes are part of the interface**, because `invariant` is meant to be reachable from
  cron and a command that prints a settlement mismatch while exiting `0` is a command nobody will
  notice:

  | Code | Means |
  | --- | --- |
  | `0` | it did what it said |
  | `1` | **refused.** Your input was wrong, or the rail's state made the action impossible. **Nothing was written** |
  | `2` | configuration or database failure. Nothing was written |
  | `3` | it ran, and **what it found is wrong** — an invariant that does not balance, or a reconcile arm that failed |

### 12.1 The nine verbs

| Verb | Selector | Writes? | What it is for |
| --- | --- | --- | --- |
| `journal` | exactly one of `--ref`, `--payme-id`, `--since` (mutually exclusive, required), plus `--limit` (1–1000, default 200) for `--since` | no | Everything known about one payment across six tables — intent, every rail transaction, the receipt, the ledger rows, the notification status, every RPC we received about it. With `--since`, the recent list instead |
| `statement` | `--from` and `--to`, both required | no | Exactly the rows `GetStatement` would return for that window — inclusive, on Payme's own clock — so a human can diff it against a cabinet export |
| `settle` | `--ref` and `--note`, both required | **yes** | The recovery button (§7). Prints the intent **before** writing, writes the sale under the intent's own idempotency key, then prints the dossier |
| `notify` | `--ref` | enqueues | Re-queues the settled-payment announcement. **The job is not run here** — this process holds no Telegram token, so telling a customer anything is the worker's job |
| `pause` | — | **yes** (Redis) | Stops the bot handing out NEW links. Never refuses a payment in flight |
| `resume` | — | **yes** (Redis) | Deletes the key. **`resume` is the only thing that turns sales back on** |
| `status` | `--hours` (1–8760, default 24) | no | The screen to open first: the switch, the configured cashbox, the last inbound call, and the funnel over the window |
| `invariant` | `--hours` (1–8760, default 24) | no | The three-way settlement count plus the fourth number. **Exits `3`** when it does not balance |
| `reconcile` | `--limit` (1–1000, default 200) | **yes** | Runs the sweep's first three arms once, synchronously, through the same ledger methods the worker calls — for when the worker is not running. Any arm in failure exits `3` |

**`reconcile` is the same calls, not a second implementation**, and the distinction is what makes
it safe: it is `expire_lapsed`, `expire_stale_transactions` and the notification backlog, in the
worker's own order, and each arm is independent so one unreachable Redis does not strand the
others. The invariant is a separate verb here because an operator wants to *read* it far more
often than they want to move state.

### 12.2 The refusals, which are the part worth knowing in advance

Every refusal is exit `1` with **nothing written**, and they split into two kinds.

**Refusals about your input.** These need no database at all — `plan(argv)` is separated from
`main` precisely so they are provable without standing one up:

* `--ref` must be **lowercase hex, 1 to 32 characters** (the column's width). Anything else is
  *"references are lowercase hexadecimal. This one is not ours, so nothing would be found under
  it."* §5.1 explains why that bound is neither the mint's 24 nor the admin panel's 24.
* `--payme-id` is validated on **length and whitespace only**, and the looseness is the point: it
  is a third party's identifier, and a tool that enforced 24-hex and was wrong would refuse to look
  up the one transaction somebody is trying to find.
* `--note` must be **non-empty after stripping** and at most 200 characters. `argparse` makes it
  required; this makes `--note ""` mean something. It is the only record of why a sale exists that
  the rail never confirmed.
* `--from`/`--to`/`--since` take ISO-8601, and a **naive value is accepted and stamped UTC** rather
  than refused — an operator mid-incident types `2026-09-09T14:00`, and the assumption is printed
  back so the reader can see which window was queried. A `--to` before its `--from` is refused.
* `--hours` and `--limit` are validated **as text**, not handed to `type=int`, because `type=int`
  accepts `-1` and `0x10` and turns a typo into a traceback instead of a sentence.

**Refusals about the rail's state.** These are the ones that save you from a wrong move:

* Any verb taking `--ref`: *"No intent exists under reference …"*.
* `journal --payme-id` on an id we never created says so, and adds the part that is actually the
  answer: *"either the id is mistyped, or Payme never reached this endpoint about it"*.
* **`settle` on an intent that is already `paid` short-circuits and writes nothing**, naming who
  settled it and when. An operator pressing this twice needs to learn that the first press worked,
  not to have a second note written over the first. This is exit `0`, not a refusal — it did what
  it said.
* `notify` has exactly three refusals, and they are the same three the admin console re-checks
  server-side (`BILLING_RAIL_BOARD` §4.6): the intent is **not paid** (*"there is nothing to tell
  the customer yet"*); the buyer has been **erased** (*"the receipt and the credit are
  untouched"*); it was **already announced** (*"the job stops on that stamp — re-enqueuing it would
  do nothing"*, and a customer who never saw it has a delivery problem in the bot, not a queue
  problem here). A failed enqueue is also a refusal, with the reassurance that the worker's own
  sweep re-enqueues unannounced settlements every few minutes.

### 12.3 Two things `pause` prints that are easy to lose

`pause` says three things and each is load-bearing: the bot stops handing out links; **payments
already in flight are unaffected and will still settle**; and the switch lives in Redis with no
expiry, so *"a Redis restart or eviction silently un-pauses it — re-check with `status` after
either"*. When the rail **is** paused, `status` closes with *"Remember: `resume` is what turns
sales back on. Nothing else does."* — which is there because `resume` performs a **delete**, so
nothing you do to the value will resume it and nothing else will either (§10's `redis-cli` row).

`status` also does one thing no stored column could: it splits `expired` intents into **abandoned**
(never held a transaction — a customer who never reached the payment form, a funnel problem) and
**stalled** (did hold one — a payment that started and did not finish, a rail problem). It is a
read-time predicate, so it needs no migration and cannot drift out of step with the rows it
describes. Two very different incidents that would otherwise look identical.

### 12.4 What the CLI can do that the console cannot, and the one thing neither can

`09-payme-go-live.md` §11 has the full division and `DECISIONS.md` **D14** has the argument. The
short version for this page: `pause`, `resume` and *notify one intent* exist in both; `journal` and
`statement` are read-only in both and the console renders them better; **`settle` is terminal-only
and always will be**, because the panel is structurally forbidden the merchant key and therefore
cannot show the cabinet charge that authorises the press; and `reconcile` is terminal-only because
a read must not be a POST and the sweep already runs it twelve times an hour.

Neither can tell you whether the customer *saw* the message. `notified_at` says we enqueued and the
worker sent. That is a Telegram fact this database does not hold, and inventing a status we cannot
know would be worse than the honest sentence.
