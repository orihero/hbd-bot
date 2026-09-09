# Troubleshooting

Symptom first, because that is what you have. Each entry names what an operator actually sees,
what in the code produces it, one command that settles the question, and the fix.

The failure modes worth a runbook are the **silent** ones: the panel that looks healthy while a
control is off, the process that boots on defaults it should have refused, the job that logs
"skipped" in a shape indistinguishable from a job that never ran. Loud failures name their own
variable and need no page here.

> **What this document can and cannot know.** Every claim below carries a `file.py:line` you can
> check in this checkout. Nothing here describes the production host — not its paths, not its
> service manager, not what terminates its TLS. Where a step needs a host fact, it is written as a
> question to answer on the host, never as an assertion. `deploy/first-install-proposal.md` and
> `deploy/systemd/*.service` are a **proposal** authored without host access; commands quoted from
> them are marked as such and are not a record of how anything is deployed. Where a command
> below curls `http://127.0.0.1:8080`, that is the address `Makefile:75` uses — not a claim
> about where any deployed process binds, since nothing in the package binds a socket and
> `HBD_ADMIN_HOST`/`HBD_ADMIN_PORT` are read by nothing that does (see §19).

Throughout, the three long-running processes are the ones the Makefile defines, and there is no
console script for any of them — `pyproject.toml` has no `[project.scripts]` table, so `python -m`
is the only invocation (Makefile:69, Makefile:72, Makefile:75):

```bash
<venv>/bin/python -m hbd.main                                    # the bot, aiogram long polling
<venv>/bin/python -m arq hbd.worker.WorkerSettings               # the ARQ worker
<venv>/bin/python -m uvicorn hbd.admin.app:app --host 127.0.0.1 --port 8080   # the admin API
```

---

## 1. Modals stop locking the background; everything else looks fine

**SYMPTOM.** The console renders, sign-in works, data loads. But open any dialog and the page
keeps scrolling underneath it. No error banner, no failed request, no 500. In a PROD bundle the
browser console carries one `console.error` and nothing else.

**LIKELY CAUSE.** The deployed console bundle predates the CSP style-nonce placeholder, or the
deploy did not rebuild it. `admin-ui/index.html` carries `__HBD_CSP_NONCE__` in a
`<meta name="csp-nonce">`, and the API substitutes this response's nonce into it per request
(shell.py:55, shell.py:86). A shell with no placeholder is served **unchanged** with a single
WARNING — deliberately, not by accident: shell.py:65-77 argues that an operator reaching for the
panel mid-incident is better served by a panel whose modals do not lock than by a 500. The cost is
that this is the only signal. Without the nonce, `style-src 'self' 'nonce-…'` blocks the `<style>`
element `react-remove-scroll` injects for every Radix modal.

`src/hbd/admin/static/` is gitignored (app.py:124-128), so the bundle on any host is whatever the
last `npm run build` left behind. Nothing gates it: `tests/test_admin/test_spa_nonce.py:49` checks
the **checked-in source** `admin-ui/index.html`, not the built artefact, and `make ui-e2e` rebuilds
before it runs (Makefile:112). The placeholder-drift check and the staleness check are different
checks, and only the first exists.

**HOW TO CONFIRM.** Grep the admin process's log for the one event:

```bash
# whatever collects the admin process's stdout on that host
... | grep admin.spa.nonce_placeholder_missing
```

Or ask the served shell directly, from the host, past the proxy:

```bash
curl -s http://127.0.0.1:8080/ | grep -o 'csp-nonce[^>]*'
```

Read the `content` attribute, not a match count — `grep -c` prints `1` for every case below in
which the meta element is present at all, which is most of them.

| What comes back | What it means |
| --- | --- |
| `content="<a base64url value>"` | Healthy. |
| `content=""` | The shell rendered with an **empty** nonce, so `SecurityHeadersMiddleware` was not in the stack. `_serve_spa_index` reads the nonce off the ASGI scope with a `""` default deliberately, "so a shell served by an application assembled without SecurityHeadersMiddleware renders an empty nonce instead of raising" (app.py:240-244). That response carries no CSP either. |
| `content="__HBD_CSP_NONCE__"` | **This route did not serve that HTML.** `render_shell` substitutes the placeholder unconditionally whenever it is present (shell.py:78-86), so this code path can never emit the literal. A proxy or a stale CDN copy is serving `index.html` itself — which is what the SPA's own `console.error` says (`admin-ui/src/lib/csp.ts`, `installCspNonce`). |
| no output at all | A bundle built before the placeholder existed. This is the case that logs `admin.spa.nonce_placeholder_missing`. |

**FIX.** Rebuild the console from the checkout and restart nothing — the shell is read from disk
per request (app.py:249) and is deliberately outside the immutable cache prefix:

```bash
cd <checkout>/admin-ui && npm ci && npm run build   # writes ../src/hbd/admin/static/
```

> **Rebuild on every deploy, unconditionally.** A git pull does not update the console, because the
> bundle is not in git. The rebuild is the only mechanism keeping the served JavaScript in step
> with the Python that serves it.

---

## 2. Every browser URL returns 404 while `/healthz` returns 200

**SYMPTOM.** `GET /` and every SPA route answer 404. The API answers normally. Liveness probes
pass. The process looks perfectly healthy at the process level.

**LIKELY CAUSE.** No console bundle at all. The SPA catch-all refuses when `index.html` is absent —
`if not SPA_INDEX.is_file(): raise HTTPException(status_code=404)` (app.py:238-239) — and the static
mount is deliberately `check_dir=False` so a missing directory is not a boot failure. A fresh
checkout with `make install` and no `make ui-build` is exactly this state: `make install` sets up
Python only (Makefile:58-60), and `make check` touches neither Node nor the bundle (Makefile:144).

**HOW TO CONFIRM.**

```bash
ls -la <checkout>/src/hbd/admin/static/index.html
```

**FIX.** `cd <checkout>/admin-ui && npm ci && npm run build`. Note that the repo installs no Node
anywhere: `admin-ui/package.json` declares `"engines": {"node": ">=20.19"}` and
`admin-ui/package-lock.json` is lockfileVersion 3 (npm 7+), and how Node reaches a deployment host
is an open question this repo cannot answer.

---

## 3. `/audit/verify` reports `chainProtection: "hmac-only"`

**SYMPTOM.** The Audit screen shows the chain verifying, but protection reads `hmac-only` rather
than `revoke+hmac`. The admin log carries `admin.audit.revoke_missing` at WARNING — or nothing at
all, which is a different diagnosis.

**LIKELY CAUSE.** This value is asked of Postgres, not read from configuration
(`has_table_privilege(current_user, 'admin_audit_log', 'UPDATE' / 'DELETE' / 'TRUNCATE')`,
audit.py:746-752). Four distinct situations produce the same word, and the log line separates them
(audit.py:755-780):

| What you see | What it means |
| --- | --- |
| `hmac-only`, **no** WARNING | `HBD_ADMIN_AUDIT_DSN` is unset, so the panel never probed. A supported deployment (settings.py:229-235) — the two-role split was never declared. |
| `hmac-only` + `admin.audit.revoke_missing` | The DSN is set, so somebody believes the split is deployed, and the probe says this connection can still write the log. The REVOKE did not land, or the admin connects as the wrong role. |
| `hmac-only` + `admin.audit.privilege_probe_failed` | The probe query itself errored. The weaker guarantee is reported rather than guessed. |
| `hmac-only` on a non-Postgres backend | Not applicable; reported honestly. |

The most likely root cause for the second row is that **migration 0007 skipped its own REVOKE**.
Its three deciding variables are read from `os.environ` and nowhere else:
`HBD_ADMIN_AUDIT_DSN` (0007:336), then `HBD_DB_APP_ROLE` or a username parsed out of
`HBD_DATABASE_URL` (0007:314-322). None of them is read from a dotenv file. `migrations/env.py`
deliberately *does* fall back to the dotenv file for `HBD_DB_MIGRATION_URL` (env.py:107-114) —
env.py:14-19 records that the environment-only version was a bug that would have migrated
production as the wrong role — and that fix was never carried into the two migration bodies that
need the same thing. `HBD_ADMIN_AUDIT_DSN` is documented in `.env.admin.example:130`, a file the
alembic runner never loads. `HBD_DB_APP_ROLE` appears in neither example file at all.

The skip is a WARNING in alembic's output, not a failure (0007:325-331):

```
admin_audit_log REVOKE skipped: HBD_ADMIN_AUDIT_DSN is not set, so no separate owner role
exists. The chain is HMAC-only on this deployment and /audit/verify will report
chainProtection=hmac-only.
```

**HOW TO CONFIRM.** On the host, against the database:

```sql
-- as the owner role
\dp admin_audit_log
-- the application role should hold SELECT and INSERT, and NOT UPDATE/DELETE/TRUNCATE
SELECT has_table_privilege('<the application role>', 'admin_audit_log', 'UPDATE');  -- want: f
```

And check which role the panel itself connects as — the probe asks about `current_user`, so an
admin process pointed at the **owner** DSN reports `hmac-only` *and* can rewrite the table the
control protects. `.env.admin.example:48` ships the owner DSN
(`postgresql+asyncpg://hbd:hbd@…`) while `.env.example:35` ships the application one
(`hbd_app`), and README.md:160-161 and `docker/initdb/10-two-roles.sql` both say all three
processes connect as `hbd_app`. That is a defect in the example file; a host that copied it
verbatim inherited it.

**FIX.** Which fix applies depends on whether 0007 has already run against this database, and
that is host state you must establish first — `SELECT version_num FROM alembic_version;` and
whether `admin_audit_log` exists. The two cases are genuinely different, because the REVOKE lives
only inside `upgrade()` (0007:386-390) and alembic runs `upgrade()` once per revision, ever.

**(a) 0007 has not been applied yet.** Export all four variables **into the shell**, not merely
into a file — the two the migration body reads come from `os.environ` only, and the migration
runner needs the owner DSN or it repeats §12:

```bash
cd <checkout>
export HBD_DB_MIGRATION_URL='postgresql+asyncpg://<owner>:…@<host>:<port>/<db>'  # or §12 happens
export HBD_ADMIN_AUDIT_DSN='postgresql+asyncpg://<owner>:…@<host>:<port>/<db>'   # the OWNER dsn
export HBD_DATABASE_URL='postgresql+asyncpg://<app>:…@<host>:<port>/<db>'        # or HBD_DB_APP_ROLE=<app>
HBD_ENV_FILE=<the bot env file> <venv>/bin/python -m alembic \
  -c migrations/alembic.ini upgrade head
```

`HBD_DB_MIGRATION_URL` is the one the doc's earlier drafts omitted and it is not optional here:
`migrations/env.py` reads the owner DSN from that variable alone (env.py:96-114), and without it
`_database_url` falls back to `load_settings().database_url` and connects as the application role
(env.py:117-129) — at which point 0007 skips its own REVOKE anyway, because "migrations run as the
application role, so a REVOKE from it is reversible by it" (0007:355-356).

**(b) 0007 is already applied — the deployment §3 describes.** `alembic upgrade head` is a **no-op**
on this database and will not re-run the REVOKE, however the environment is exported. The controls
have to be applied by hand, as the **owner** role:

```sql
-- as the owner role
REVOKE UPDATE, DELETE, TRUNCATE ON TABLE public.admin_audit_log FROM "<the application role>";
```

That one statement is the control `chainProtection` probes for, and it is enough to flip the value.
It is **not** the whole of `_apply_revoke` (0007:360-383): that function also creates the two
`SECURITY DEFINER` sweep functions `public.hbd_purge_audit_log(integer)` and
`public.hbd_purge_audit_reasons(integer)`, revokes them from `PUBLIC` and grants `EXECUTE` on them
to the application role. Without those, the REVOKE lands and the 730-day and 90-day audit sweeps
have no way to run as the application role. Take their bodies from that function rather than
retyping them; whether they already exist on the target database
(`\df public.hbd_purge_audit_*`) is another host question.

In both cases: set the admin process's `HBD_DATABASE_URL` to the **application** role and restart
it, then confirm `chainProtection` flips to `revoke+hmac`.

> **Two roles are a manual step nobody in this repo performs.**
> `docker/initdb/10-two-roles.sql:25-33` says outright that its password is a local development
> password and that staging and production roles must be created by hand. It runs only on an empty
> Docker volume. Whether `hbd` and `hbd_app` exist on a given database, and whether
> `ALTER DEFAULT PRIVILEGES FOR ROLE hbd … GRANT … TO hbd_app` (that file, :46-49) was applied, is
> host state — and without that clause every table a future migration creates is invisible to the
> application role.

---

## 4. `ok: true` but `isComplete: false` on `/audit/verify`

**SYMPTOM.** A green verification on a mature deployment.

**LIKELY CAUSE.** The walk is bounded: `VERIFY_BATCH_SIZE = 500` and `MAX_VERIFY_ROWS = 50_000`
(audit.py:129-132). Past the ceiling the tail check is suppressed and `is_complete` goes false
(audit.py:646-656), with the field comment stating the reason: "so a clean result is not mistaken
for a clean *whole* chain" (audit.py:240-243).

**HOW TO CONFIRM.** Read both fields, never `ok` alone. `checkedRows` at exactly 50 000 is the
ceiling.

**FIX.** None available in the product — this is a reading instruction, not a defect. `ok: true`
with `isComplete: false` means "the oldest 50 000 rows verify", not "the log verifies".

---

## 5. Sign-in returns 403 `ORIGIN_REJECTED`

**SYMPTOM.** The login page loads. Submitting credentials returns 403 with code
`ORIGIN_REJECTED`; the admin log carries `admin.login.origin_refused`. After a successful sign-in
elsewhere, the same code appears on **every** state-changing request with
`admin.csrf.refused` instead.

**LIKELY CAUSE.** The `Origin` header does not exactly equal `HBD_ADMIN_PUBLIC_ORIGIN`.
`verify_origin` is an exact set-membership test with no prefix, suffix or subdomain matching
(csrf.py:76-88), and outside `dev` the accepted set holds exactly one element
(settings.py:620-632). Three shapes produce it:

- **A second hostname.** A panel reachable at both `https://panel.example` and a bare IP, or a
  `www.` variant, 403s on whichever one is not configured.
- **A wrong scheme or port.** `http://` where the configured value is `https://`, or `:8080`
  appended by a proxy that does not rewrite it.
- **A proxy that strips `Origin`.** An absent header is `ORIGIN_MISSING`, mapped to the same
  `ORIGIN_REJECTED` code (deps.py:209-210).

The boot guard cannot catch a *wrong* value, only an *unset* one — it tests
`"admin_public_origin" not in self.model_fields_set` (settings.py:578-581). And a dotenv-supplied
value counts toward `model_fields_set`, so a host that copied `.env.admin.example:73`
(`HBD_ADMIN_PUBLIC_ORIGIN=http://127.0.0.1:8080`) verbatim **disarms the guard** and produces
exactly the incident the guard's own message predicts: "boot, pass /healthz, serve a login page and
then reject every mutation with ORIGIN_REJECTED" (settings.py:582-588).

In development the same 403 has a different cause and is not a bug: the Vite dev proxy sets
`changeOrigin: false` deliberately (`admin-ui/vite.config.ts:132-135`), so the browser's real
`Origin` reaches the API and the check is live locally too. The prerequisite is
`HBD_ADMIN_PUBLIC_ORIGIN=http://localhost:5173` in `.env.admin` (Makefile:86-89). Flipping
`changeOrigin` to `true` "fixes" the 403 by disabling the panel's only cross-site control
everywhere but production.

**HOW TO CONFIRM.** The configured value is on the boot line and on the config screen:

```bash
... | grep admin.boot.ok      # context.public_origin — the value the process enforces
```

Then compare it, character for character, against what the browser sends:

```bash
curl -si https://<panel host>/api/auth/login -X POST \
  -H 'Origin: https://<panel host>' -H 'Content-Type: application/json' \
  -d '{"username":"origin-probe","password":"origin-probe"}'
# 403 ORIGIN_REJECTED   the header and the setting disagree
# 401 / 429             the origin check passed; the request reached the credential path
```

**The body must be well formed, and `-d '{}'` will lie to you.** `login` declares
`body: LoginRequest` as a parameter (auth.py:440-448), so pydantic validates it during dependency
solving and returns 422 before the handler body ever runs; `_enforce_origin(request, settings)` is
the *first statement inside* the handler (auth.py:450), and there is no origin or CSRF middleware in
the stack to catch it earlier (app.py:387-390). `username` and `password` are both required with
`min_length=1` (schemas/auth.py:47-50), so an empty object 422s on every deployment, correctly
configured or not — a 4xx that reads as "the origin check passed" when it never ran.

Two costs of the corrected probe, both small and both worth knowing: it charges one attempt against
the strict `(username, client_ip)` login counter (10 per 900 s, ratelimit.py:116-117), so use a
username no operator signs in as; and a failed check writes one `LOGIN_FAILURE` audit row
(auth.py:487-496).

**FIX.** Set `HBD_ADMIN_PUBLIC_ORIGIN` to the exact origin a browser types — scheme, host and, if
non-default, port — and restart the admin process. If the panel is reachable by more than one name,
give it one and redirect the others at the proxy; the setting holds exactly one origin outside dev
and that is not a limitation to work around.

> **The panel must live at the root of its own origin.** The bundle references `/assets/…`
> absolutely, the immutable-cache carve-out is the literal prefix `"/assets/"`
> (security_headers.py:82), the API prefix is `/api` (deps.py:108), and both cookies are
> `__Host-` prefixed — a prefix *defined* to require `Path=/` and no `Domain` (csrf.py:45-49).
> Mounted under a subpath, the bundle 404s, the cache split lands on the wrong paths, and the
> cookies scope to everything else on that origin.

---

## 6. Nobody can sign in, or one operator is permanently locked out

**SYMPTOM (a).** Every sign-in returns 429, or 429s appear for one username in a pattern nobody can
explain — and **the log says nothing**.

That silence is the diagnostic, so do not go looking for a line. Two counters can produce this 429
and only one of them is logged. `admin.ratelimit.username_tripped` belongs to the **loose**
username-only ceiling — 100 per 900 s, the one whose docstring calls it "the counter an attacker
spread across many source addresses trips" (ratelimit.py:358-376). The **strict**
`(username, client_ip)` counter described below fires at 10 and emits nothing: `_LOGGER` appears
three times in that whole module — `store_unavailable` at :338, `username_tripped` at :367, a refund
failure at :557 — and none of them covers a strict-counter trip. The evidence it does leave is in
the database, not the log: one `LOGIN_RATE_LIMITED` audit row per limiter window, carrying the
attempted username and no actor (auth.py:468-481). The 429 itself also names which counter answered:
`_refuse_if_limited` passes the scope through `problem(...)`, whose keyword arguments become
`error.details` (auth.py:215-223, errors.py:175-185), so the response body carries
`details.scope: "user_ip"` for the strict counter and `"username"` for the loose one
(ratelimit.py:151-156). That field, not a grep, is what separates the two here.

**LIKELY CAUSE.** Every request resolves to the same client IP because the reverse proxy is not
declared. `resolve_client_ip` ignores `X-Forwarded-For` entirely unless **both** `hops > 0` **and**
the transport peer is inside a configured CIDR (clientip.py:110-149). The shipped defaults are
`admin_trusted_proxy_hops = 0` and empty CIDRs (settings.py:216-217), and
`.env.admin.example:113-114` ships them that way. Behind a proxy, `request.client.host` is the
proxy (deps.py:195-201), so the strict login counter — keyed `(username, client_ip)` at 10 attempts
per 900 s (ratelimit.py:116-117, :309-314) — collapses into one global bucket per username. That is
the shape ratelimit.py:9-13 was written to avoid: it "hands anyone who knows an operator's username
a permanent 429 against that account, at exactly the moment during an incident when the operator
needs to log in."

The same collapse writes the proxy's address into every `admin_audit_log.ip` and into
`admin_sessions.last_ip` (deps.py:329-347), so the audit log's only network evidence becomes a
constant.

Nothing validates hops against reality, and the boot line does **not** print them — `admin.boot.ok`
carries `environment`, `env_file`, `is_cookie_secure` and `public_origin` and nothing about proxies
(app.py:322-333).

**HOW TO CONFIRM.** `GET /api/config` publishes both values (config_view.py:96-129). Compare
`adminTrustedProxyHops` against the number of proxies the deployment actually controls, and check
that the audit log's `ip` column is not a single repeated address.

**FIX.** Set `HBD_ADMIN_TRUSTED_PROXY_HOPS` to the exact count of proxies you control and
`HBD_ADMIN_TRUSTED_PROXY_CIDRS` to the addresses those proxies connect from — and configure the
proxy to **append** to `X-Forwarded-For`, not replace it. Too high believes an attacker-written
entry; too low believes an inner proxy. A CIDR typo fails the boot with the variable named
(settings.py:486-499), which is the one part of this the code can check for you.

**SYMPTOM (b).** Sign-in fails with a rate-limit refusal that no amount of waiting clears, and the
Redis-backed screens are unhappy.

**LIKELY CAUSE.** Redis is unreachable and the admin limiter **fails closed** by design: "When
Redis is unreachable the answer is 'denied', not 'allowed'" (ratelimit.py:21-26), with
`BACKEND_UNAVAILABLE` kept distinct from `TRIPPED` so an outage does not read as an attack
(ratelimit.py:159-170). The log event is `admin.ratelimit.store_unavailable` (ratelimit.py:340).
Note the deliberate asymmetry: the bot's inbound gate **fails open** — "A meter that cannot be read
is not a reason to stop selling songs" (`src/hbd/bot/gate.py:44-47`). So a Redis incident locks
operators out of the panel while the bot keeps serving customers. Those are one event, not two.

**HOW TO CONFIRM.** `/readyz` with the probe token (see §9) reports `redis: false`.

**FIX.** Restore Redis. There is no bypass, and adding one would remove the control.

---

## 7. The admin API refuses to start

Three refusals run inside the lifespan, **in this order** (app.py:315-316), and the first one wins.

**SYMPTOM.** The process exits at start with:

```
The admin panel is disabled. Set HBD_ADMIN_ENABLED=true in .env.admin to run it.
```

**CAUSE AND FIX.** `admin_enabled` defaults to `false` (settings.py:180) and the lifespan refuses
without it (app.py:206-208). Setting it is a required, non-default deployment step — a fresh admin
service refuses to start until somebody does.

**SYMPTOM.** The process exits at start naming one or more of
`HBD_TELEGRAM_BOT_TOKEN`, `HBD_ELEVENLABS_API_KEY`, `HBD_LLM_API_KEY`,
`HBD_LLM_FALLBACK_API_KEY`, `HBD_OPENROUTER_MANAGEMENT_KEY`:

```
The admin process must not hold a vendor credential or a bot token, and these are within
reach of it — in its environment or in <the admin env file>: …
```

**CAUSE.** `_refuse_vendor_credentials` (app.py:186-199) scans `os.environ` **and** the variable
names in the admin dotenv file (app.py:175-183), and the list is derived from
`hbd.config.VENDOR_SECRET_FIELDS` rather than restated (app.py:116-118, config.py:111-117), so a
sixth credential added there is covered here without anyone remembering — as the fifth,
`HBD_OPENROUTER_MANAGEMENT_KEY`, already was (D13: the tuple grew, this refusal followed, no
edit here). `AdminSettings` has no
field that could hold any of them.

**FIX.** Remove them from the admin host. The panel needs none of them: it opens exactly two
connections, Postgres and Redis (container.py:1, :121-128).

> **In `staging` this is a WARNING, not a refusal.** The refusal is gated on
> `environment == "prod"` exactly (app.py:192, settings.py:598-599). A staging admin host holding a
> real ElevenLabs key boots with `admin.boot.vendor_env_present` in a log nobody is watching. And
> because the disabled-panel refusal runs *first*, a prod host with both problems is told the panel
> is disabled and never learns about the credential.

**SYMPTOM.** A validation error listing many variables at once, including several the example file
told you to leave blank.

**CAUSE.** `.env.admin.example` cannot be copied and booted as-is. python-dotenv strips an inline
`#` comment only when the value before it is non-empty, so seven variables parse as their own
trailing comment, and `HBD_ADMIN_COOKIE_SECURE=` (genuinely blank, with the file instructing "Leave
empty" at :91-92) is a `bool | None` pydantic cannot read from an empty string. Reproduced against
this working tree:

```bash
cd /tmp && HBD_ADMIN_ENV_FILE=<checkout>/.env.admin.example \
  <checkout>/.venv/bin/python -c "
from hbd.admin.settings import build_admin_settings
from hbd.errors import ConfigError
try: build_admin_settings()
except ConfigError as e: print(e.operator_message)"
```

```
The admin panel's configuration is invalid or incomplete. Fix these environment variables (see .env.admin.example):
  HBD_ADMIN_COOKIE_SECURE: Input should be a valid boolean, unable to interpret input
  HBD_ADMIN_TRUSTED_PROXY_CIDRS: Value error, HBD_ADMIN_TRUSTED_PROXY_CIDRS contains an unparsable entry: '# comma-separated'
  HBD_ADMIN_AUDIT_HMAC_KEY: Value should have at least 32 items after validation, not 0
  HBD_ADMIN_NAME_MATCH_MIN_SIMILARITY: Input should be a valid number, unable to parse string as a number
  HBD_ADMIN_SETTLEMENT_GRACE_S: Input should be a valid integer, unable to parse string as an integer
  HBD_ADMIN_UZS_PER_USD: Input should be a valid number, unable to parse string as a number
  HBD_ADMIN_UZS_PER_USD_AS_OF: Input should be a valid date or datetime, invalid character in year
  HBD_ADMIN_SINGLE_SONG_PRICE_MINOR: Input should be a valid integer, unable to parse string as an integer
  HBD_ADMIN_KIT_CURRENCY: String should have at most 3 characters
```

**FIX.** In the deployed copy, delete the value from each of those lines and move the explanatory
comment onto its own line above the variable. Then set `HBD_ADMIN_AUDIT_HMAC_KEY` to at least 32
characters, and delete the `HBD_ADMIN_COOKIE_SECURE=` line entirely — the field is a refusal, not a
switch (settings.py:570-577, :602-618), and its only legal states are absent or `true`.

The irony is worth knowing: `_blank_mirror_means_unpublished` (settings.py:433-465) exists solely to
make the untouched example file work and says so at :449 — "The example file ships the variables
blank, so this is the path an untouched deployment actually takes." It is not that path, because
the values are never blank as parsed, so the validator never fires.

---

## 8. `ConfigError` at startup naming variables you thought were set

**SYMPTOM.** The bot exits 2 with a single line and no traceback:

```
hbd: Configuration is invalid or incomplete. Fix these environment variables (see .env.example):
  HBD_TELEGRAM_BOT_TOKEN: Field required
  HBD_DATABASE_URL: Field required
  HBD_ELEVENLABS_API_KEY: Field required
  HBD_LLM_API_KEY: Field required
```

**LIKELY CAUSE.** `HBD_ENV_FILE` names a file that does not exist. A missing dotenv path reads no
file and raises no error, and **the message cannot tell you that**: the preamble hardcodes the
*example* filename (config.py:702-704; the admin twin at settings.py:640-643), and the resolved path
is only logged later, by `verify_host` and by `admin.boot.ok` — both of which run after settings
build successfully. So the one failure mode the `HBD_ENV_FILE` feature introduces is the one its
error message cannot describe.

Those four variables are the complete required set for the bot and the worker, in every environment
(config.py:187 for the DSN; the three vendor secrets are re-required by `_VendorBoundSettings` at
config.py:689-699, and `load_settings` always passes `require_vendor_secrets=True`,
config.py:758-760). The admin's set is two: `HBD_DATABASE_URL` and a ≥32-character
`HBD_ADMIN_AUDIT_HMAC_KEY` (settings.py:174, :229).

**HOW TO CONFIRM.** Ask the process which file it would read, without booting it:

```bash
HBD_ENV_FILE=<the path the service sets> <venv>/bin/python -c \
  "from hbd.config import env_file; import pathlib
p = env_file(); print(p, pathlib.Path(p).is_file())"
```

**FIX.** Correct the path. Note the precedence, which bites in the other direction too: process
environment beats the dotenv file for every variable on both settings classes, so any `HBD_*` left
exported in a deploy shell silently overrides the file the service points at.

**RELATED SYMPTOM.** The worker exits with a **traceback** rather than a clean line, once per
supervisor restart. That is not a different bug: `WorkerSettings` is built at import time so the ARQ
CLI can find it, and `_SETTINGS = _settings()` sits at module scope (worker.py:40, docstring at
worker.py:3-6) with no `try/except`. The bot wraps the same call and prints one line (main.py:213-218).
Same misconfiguration, two different presentations.

**WORSE SYMPTOM: no error at all.** If the four required variables happen to be exported, a mistyped
`HBD_ENV_FILE` boots the bot on **100 % defaults** — including `HBD_ENVIRONMENT=dev`, which disarms
the only two production refusals the bot has (fake providers, providers.py:104-108; the in-process
submitter, submitter.py:100-105). `Settings.environment` is an unvalidated free-form `str`
(config.py:170), unlike `AdminSettings.environment`, which is a closed `Literal` precisely because
"a typo like `production` would silently downgrade the strongest boot control in the package"
(settings.py:15-18). `HBD_ENVIRONMENT=production` or `=PROD` on the bot is that typo, with no error
anywhere. Confirm from the boot line: `host verified` carries `environment` and `env_file`
(runtime/startup.py:33-41).

> **`HBD_REDIS_URL` defaults to `redis://localhost:6379/0`** (config.py:188). A worker with a
> mistyped Redis URL does not fail — it connects to a local Redis and finds an empty queue. The
> queue looks idle rather than broken.

---

## 9. Monitoring reports the panel healthy while it serves nothing

**SYMPTOM.** `/readyz` returns `200 {"status":"ok"}` with the database down, Redis down, or both.
Nothing is ever removed from a load balancer.

**LIKELY CAUSE.** The unauthenticated `/readyz` body is a **constant** and pings nothing
(health.py:53-56, :126-131) — even the word "degraded" is treated as fleet telemetry
(health.py:9-19). Detail requires either `X-Probe-Token` matching `HBD_ADMIN_PROBE_TOKEN` under
`secrets.compare_digest`, or a live operator session (health.py:93-114). The token defaults to empty,
and an empty setting authorises nobody (settings.py:426-428) — so there is no default token to
forget to change, and also no monitoring path at all until one is set.

`/healthz` is worse for this purpose by design: a bare 200 with an empty body that touches nothing
(health.py:121-124). It also takes no container, so it answers 200 even in the one state where every
API route 500s — a process whose ASGI lifespan never ran, where `get_container` raises
`RuntimeError("admin container is not on app.state; the lifespan did not run")` (deps.py:126-133).

**HOW TO CONFIRM.**

```bash
curl -s http://127.0.0.1:8080/readyz                                  # always {"status":"ok"}
curl -s -H 'X-Probe-Token: <token>' http://127.0.0.1:8080/readyz      # the real answer
# {"status":"ok|degraded","database":true,"redis":true,"configVersion":null}
```

**FIX.** Set `HBD_ADMIN_PROBE_TOKEN` to a long random value and give it to the monitor. The settings
model imposes no minimum length on it — unlike the HMAC key's `min_length=32` — so length is
operator discipline here.

**Do not chase `configVersion: null`.** Nothing in this tree writes `hbd:settings:version`; the key
is read at health.py:74 and written nowhere, awaiting the Phase 7 config editor (health.py:50-51).
`null` means "nobody has published one", never "Redis is broken".

Neither the bot nor the worker exposes any HTTP probe at all. Supervision of those two is
process-level; there is nothing to curl.

---

## 10. The bot or worker will not start: ffmpeg

**SYMPTOM.** One of:

```
'ffmpeg' was not found on PATH. Install ffmpeg, or point HBD_FFMPEG_BINARY at the binary.
Audio post-processing cannot run without it and every order would fail.
```
```
'ffmpeg' was built without libopus. Telegram's sendVoice only renders a voice note for
OGG/Opus; without this encoder every greeting would arrive as a file attachment. Install an
ffmpeg build that includes it.
```
```
'/usr/bin/ffmpeg' did not answer -encoders within 15.0s; the binary looks broken.
```
```
'/usr/bin/ffmpeg' exited 1 listing its encoders; the binary looks broken.
```
```
'ffmpeg' is on PATH but could not be executed: <the OSError>
```

Note which name each message carries, because it is not consistent and it tells you where in the
check you are. The PATH and `libopus` messages name the **configured** binary — the bare `ffmpeg`
or whatever `HBD_FFMPEG_BINARY` holds (audio/startup.py:35, :99). The three `-encoders` messages
name the **resolved** path, because `_encoder_table` is called with `shutil.which`'s answer
(audio/startup.py:96, messages at :62, :68, :75). **None of them can ever name `ffprobe`**:
`_encoder_table` is called exactly once, with `ffmpeg_path`; ffprobe is only checked for presence on
PATH (audio/startup.py:93-94) and is never asked for an encoder table at all.

**LIKELY CAUSE.** `verify_host` refuses on more than the encoder set, and the boot log's "host
verified" line is emitted only after all of it passes (runtime/startup.py:21-42). In order:

1. `ffmpeg` resolvable on PATH (audio/startup.py:31-40).
2. `ffprobe` resolvable on PATH — same function, same message shape, and that is the *only* thing
   asked of ffprobe (audio/startup.py:94).
3. ffmpeg actually executable: an `OSError` from the spawn is a `ConfigError` (audio/startup.py:60-65).
4. ffmpeg answering `-encoders` inside the 15 s ceiling (audio/startup.py:66-71;
   `STARTUP_PROBE_TIMEOUT_S = 15.0`, constants.py:66).
5. a zero exit from that call (audio/startup.py:73-78).
6. the table containing `libopus` — `REQUIRED_ENCODERS = (VOICE_NOTE_CODEC,)` = `("libopus",)`,
   constants.py:113-121; raised at audio/startup.py:97-103.
7. **the i18n catalogues loading.** `verify_host` calls `get_translator()` after the ffmpeg check
   and says why: "Loading the catalogues here turns a malformed locale file into one startup failure
   rather than a broken message in front of a customer" (runtime/startup.py:26-28, and
   `hbd/i18n/__init__.py:8-10`). A `locales/*.json` that breaks the orthography or plural rules is a
   `ConfigError` at that moment — a boot refusal with nothing to do with ffmpeg, which is worth
   knowing because every message above points at a binary.

`verify_host` is called by the bot (main.py:100) and the worker (worker.py:45) and **not** by the
admin API — an admin-only host needs no ffmpeg at all.

> **Two files are called `startup.py` and they are different files.** The ffmpeg checks are
> `src/hbd/audio/startup.py` (108 lines). `verify_host` and the `host verified` log line are
> `src/hbd/runtime/startup.py` (42 lines), which is what §8 and §18 mean by the bare name. Any
> citation past line 42 belongs to the audio one.

**HOW TO CONFIRM.**

```bash
ffmpeg -hide_banner -encoders | grep -E 'libopus|libmp3lame'
which ffmpeg ffprobe
```

**FIX.** Install an ffmpeg build with libopus, or point `HBD_FFMPEG_BINARY` / `HBD_FFPROBE_BINARY`
at one — the binaries are operator-configurable (config.py:414-418) and the error message names the
variable, so a host with ffmpeg somewhere unusual needs a config line rather than a PATH change.

> **Two asymmetries here will mislead you.** The probe demands `libopus`, which the default product
> configuration never exercises — `greetings_per_kit` defaults to 0, which "sells a song-only kit
> and buys no speech at all" (config.py:406-411). Meanwhile the **mp3** encoder the song master
> actually needs is never probed, and its absence is not fatal: `_normalized` in
> `pipeline/assets.py:129-132` is documented "Loudness-normalise, or fall back to the source file.
> Never fatal." An ffmpeg without an mp3 encoder passes boot and ships an unmastered song to every
> paying customer with no error anywhere. Check `libmp3lame` by hand; nothing else will.

A post-boot ffmpeg failure never crashes the process. Every spawn goes through one function that
returns an `Err(AudioProcessingError)` carrying a stderr tail (`audio/runner.py:1-8`, :41-44), so
diagnosing one means reading job-level error context, not a traceback.

---

## 11. Migrations fail asking for API keys

**SYMPTOM.** `alembic upgrade head` on a database-only or CI host exits complaining about
`HBD_TELEGRAM_BOT_TOKEN`, `HBD_ELEVENLABS_API_KEY` and `HBD_LLM_API_KEY` — none of which a
migration needs.

**LIKELY CAUSE.** When `HBD_DB_MIGRATION_URL` is unset, `migrations/env.py` falls back to
`load_settings().database_url` (env.py:117-129), and `load_settings` always requires the vendor
secrets (config.py:758-760).

**FIX.** Set `HBD_DB_MIGRATION_URL` — which you want set anyway, see §3 — and the vendor-key path is
never taken. `_owner_url` reads it from the environment first and from the dotenv file second
(env.py:96-114).

---

## 12. Migrations ran, but as the wrong role

**SYMPTOM.** In alembic's output, one line:

```
HBD_DB_MIGRATION_URL is not set, so migrations are running as the application role. That
role owns every table it creates, and an owner can GRANT back anything revoked from it — so
the audit log's REVOKE is not a control on this deployment.
```

**LIKELY CAUSE.** Exactly what it says (env.py:89-93, :117-129). Falling back rather than refusing
is deliberate — every one-role dev setup would otherwise stop migrating — but the deployment now has
no privilege-based audit protection, only the HMAC.

**HOW TO CONFIRM.** The downstream evidence is `/audit/verify` reporting `hmac-only` (§3) and, in
Postgres, the audit table's owner:

```sql
SELECT tableowner FROM pg_tables WHERE tablename = 'admin_audit_log';
```

**FIX.** Create the two roles by hand on the target database (the local init script is explicitly
not for production), set `HBD_DB_MIGRATION_URL` to the owner DSN and `HBD_DATABASE_URL` to the
application DSN, and export the environment as in §3 so every *subsequent* migration runs as the
owner. Tables already owned by the wrong role need `ALTER TABLE … OWNER TO <the owner role>` before
the REVOKE means anything.

Re-running `alembic upgrade head` will **not** repair the migrations that already ran: alembic
applies each revision once, so 0007's REVOKE does not fire a second time on a database that already
carries `admin_audit_log`. Fixing the ownership is an `ALTER TABLE`, and re-applying the audit
controls is §3 case (b) — by hand, as the owner.

---

## 13. Retention, balances and audit anchors quietly stop

**SYMPTOM.** No error anywhere. Symptoms accumulate slowly: the Vendors screen reads "not polled",
`purge_runs` gains no rows, the activity series grows permanent gaps, and `/audit/verify` keeps
reporting `ok: true`.

**LIKELY CAUSE.** The ARQ worker is down. All three cron jobs live only there
(jobs.py:705-768) — retention hourly at :17 (retention_job.py:73), the vendor-balance poll hourly at
:43 (vendor_balance_job.py:118), the activity snapshot daily at 00:07 UTC (activity_job.py:74-75) —
and no other actor covers any of them. Four consequences, none of which raises:

1. **Retention stops**, which the repo treats as a legal obligation.
2. **Audit tail protection stops being refreshed.** HEAD and TRUNCATION anchors are written only by
   the retention sweep (`pin_audit_head`, purge.py:362-365); `/audit/verify` writes nothing at all
   (routers/audit.py:1-7). The undetectable tail-deletion window is normally one sweep interval —
   with the worker down it is however long the worker is down, while the badge stays green.
3. **Balance tiles read "not polled"** — indistinguishable from the two legitimate skips below.
4. **Activity snapshots gap permanently.** Nothing back-fills; the `last_seen_at` values that would
   have answered for yesterday no longer exist (activity_job.py:20-25).

All three crons are `run_at_startup=False`, so a cold-started worker runs nothing until the next
window: up to an hour of "not polled" by design, and up to 24 h before the first activity snapshot
(jobs.py:733-738 argues the trade explicitly — `run_at_startup=True` would fire once per replica).

**HOW TO CONFIRM.**

```sql
SELECT ran_at, trigger, assets_deleted, name_records_deleted, is_batch_full,
       storage_keys_returned, storage_keys_deleted, storage_delete_failures, error_code
FROM purge_runs ORDER BY ran_at DESC LIMIT 5;
```

**There is no `rows_affected` column, and asking for one fails the whole query.** Each retention
clock has its own counter column — `assets_deleted`, `brief_notes_purged`,
`attempt_transcripts_purged`, `name_records_deleted` and the rest (purge_run.py:74-98, created by
migration 0008:57-83). `total_rows_affected` is a **computed property** over those
(`purge.py:277`); it reaches the worker log as the `rows_affected` key (retention_job.py:208) and
the retention API as `totalRowsAffected` (schemas/retention.py:143, :241), and it is stored
nowhere. Sum the counter columns if you want it in SQL.

A gap in `ran_at` at hourly :17 is the worker's downtime. Also grep the worker log for
`worker dependencies built` / `worker started` and `retention sweep finished`.

**FIX.** Restart the worker. Note there is **no way to trigger a sweep on demand**: `POST
/api/retention/run` is described in two docstrings but exists as no route — the only retention route
is a `GET` (routers/retention.py:59) — and nothing outside the cron enqueues `run_retention_sweep`.
Recovery is "restart the worker and wait for :17", and an erasure request's purge cannot be
expedited.

**Two look-alikes that are not a downed worker.** The balance poll no-ops with
`{"skipped": …}` under `HBD_USE_FAKE_PROVIDERS` or when `HBD_VENDOR_BALANCE_POLL_ENABLED` is off
(vendor_balance_job.py:318-323). The tile renders "not polled" in all three cases. Check the worker
log before assuming the process is dead.

---

## 14. `purge_runs` shows bytes leaking, or shows a zero you cannot read

**SYMPTOM.** `storage_keys_returned > storage_keys_deleted` on a row.

**CAUSE.** Object bytes are deleted by the job **after** the transaction commits, and the two
numbers are recorded separately on purpose — "a crash leaves orphaned bytes (recoverable, sweepable)
rather than a row pointing at bytes that no longer exist" (purge.py:96-101). Every failing delete is
logged individually with its key, because "the key is the only handle an operator has for a manual
sweep" (retention_job.py:125-157). That query is the only place the leak is recorded.

**FIX.** Grep the worker log for `an expired object could not be deleted from storage`, collect the
keys, and remove them by hand from `<data root>/archive`.

> **`storageKeysDeleted: 0` no longer means what the job's docstring says.**
> `retention_job.py:32-38` still states that nothing writes `assets.storage_key`, so the sweep
> "records deleting zero keys". That is stale: `db/repository.py:383` writes it
> (`storage_key=archive_key(kit.order_id, asset.path.name)`), and repository.py:354-366 explains
> that this closes the archive-orphan bug. A zero there today means either nothing expired or the
> deletes are failing — not "the column is not written yet". Rows written *before* that fix are
> reconstructed by `purge._legacy_key` behind a strict filename pattern (purge.py:599-613).

---

## 15. Every media reveal in the panel 404s while the row says the file exists

**SYMPTOM.** `GET /api/assets/{id}` returns metadata happily. Streaming the audio returns 404
`NOT_FOUND`. It is fleet-wide, not per-order.

**LIKELY CAUSE.** The admin process and the bot/worker do not agree on the data root. The bot and
worker derive theirs from the **process working directory** — `root = (data_root or Path.cwd() /
"var").resolve()` (runtime/container.py:286) with no environment knob, and `main()` never passes one
(main.py:222). The admin uses `HBD_ADMIN_DATA_ROOT`, whose default is the **relative** path `var`
(settings.py:423). Both are relative, so agreement depends entirely on the two processes sharing a
working directory — a deployment fact, not a code guarantee, and `settings.py:413-414` claims the
agreement without any variable enforcing it.

The 404 is precise, not incidental: a missing file becomes `NotFoundError` rather than
`StorageError` (`storage.py:274-291` → `_absent`, storage.py:107-119), and `NOT_FOUND` maps to 404
(errors.py:119). A permission fault on a root that *does* exist maps to 503 `STORAGE_FAILED`
instead (errors.py:128) — so 404 fleet-wide points at the wrong directory, and 503 points at a
mount that is there but unreadable.

The admin container deliberately does **not** `mkdir` its root: "conjuring it here would succeed on
a developer's laptop and hand every asset request a silent 404 in production"
(admin/container.py:152-156).

**HOW TO CONFIRM.** On the host, resolve both sides. The bot/worker side is `<their cwd>/var`; the
admin side is `<its cwd>/<HBD_ADMIN_DATA_ROOT>`. Then:

```bash
ls <resolved root>/archive/orders/ | head
```

The bot's own boot log prints its workspace path — `container built` carries `workspace`
(runtime/container.py:297-304), which is the sibling of `archive` under the same root.

**FIX.** Make `HBD_ADMIN_DATA_ROOT` an **absolute** path equal to the bot's `<cwd>/var`. There is no
corresponding knob on the bot side; relocating its root means changing its working directory.

> **That root holds two key namespaces with different lifecycles.** `orders/{order_id}/{filename}`
> is swept on the asset clock (storage.py:73-84); `users/{user_id}/avatar.jpg` is deleted only by a
> customer's `/forget` (user_profiles.py:199-200). One `LocalFileStorage` instance serves both, for
> the reason spelled out at runtime/container.py:301-307. They cannot be scoped separately at the
> filesystem level, which matters for anything you do to that directory by hand.

---

## 16. Cannot create or recover the first operator

**SYMPTOM.** `--reset-owner` exits 1 with:

```
Refusing --reset-owner: this panel still has an active OWNER. Ask them to reset the account
instead — recovery exists for the case where nobody can sign in.
```

**CAUSE.** Recovery is refused while any active OWNER exists (bootstrap.py:186-191), which is what
stops it being a privilege escalation for anyone who reaches the host. The corollary bites: an
operator locked out of an OWNER account they still own cannot use it either. Deactivate that row
first — a step no document in this repo describes.

**SYMPTOM.** `--password` exits 1 without creating anything.

**CAUSE.** Refused on purpose (bootstrap.py:80-84): "a password in argv is visible in `ps` to every
user on this host and is written to your shell history." It is parsed with `argparse.SUPPRESS`
solely so it can be rejected with an explanation.

**SYMPTOM.** `--password-file` exits 1 naming the file's mode.

**CAUSE.** Any group or other permission bit at all is refused — `mode & 0o077`
(bootstrap.py:76-78, :124-134) — because a group-*writable* file can be replaced before it is read.
`chmod 600` and retry. The password is `.strip("\r\n")` only, so trailing spaces or tabs in the file
become part of the password.

**Exit codes are a contract**: 0 success, 1 operator refusal, 2 configuration/`HbdError`
(bootstrap.py:72-74, :319-343). Nothing ever prints a traceback, because a traceback would carry the
DSN. A deploy script can tell "already bootstrapped" from "the environment is wrong" without parsing
English.

To find every out-of-band ownership event afterwards, grep the audit log for the actor
`system:bootstrap` (bootstrap.py:239-271) — a real login cannot collide with it. Be aware that a
`--reset-owner` which *creates* a new account is audited as `ADMIN_PASSWORD_CHANGE`, because the
action is chosen from the flag rather than from what happened (bootstrap.py:274-283 against
:193-204).

---

## 17. Customer messages sent during a restart are never answered

**SYMPTOM.** Customers report that a message sent around a deploy got no reply.

**CAUSE.** Not a bug — `run_polling` calls `bot.delete_webhook(drop_pending_updates=True)` on every
start (`bot/app.py:216`). Every update that arrived during the deploy window is discarded and never
resent. main.py:156-162 records the one place this is compensated: a bot-block is learned in two
places, by the bot's `my_chat_member` update *and* by the worker's refused `sendAudio`, "because
every membership update that arrived during a deploy window is discarded and never resent, so the
worker's arm is the only source that survives a restart."

**FIX.** Restart during a quiet window. Nothing recovers the lost updates.

---

## 18. Log lines you expect to find, and how to find them

**SYMPTOM.** A documented post-deploy check returns nothing.

**CAUSE.** `deploy/first-install-proposal.md:143` (a proposal, written without host access) greps for
`host_verified`. That token does not exist anywhere in the tree. The log message is
`"host verified"` — with a space — and it is the *message*, not an `event` field
(runtime/startup.py:33-41). The next line in the same proposal, `grep admin.boot.ok`, does work,
because that one **is** an event field (app.py:325).

**How the log is shaped.** One JSON object per line whenever `HBD_IS_DEBUG` is false, with a fixed
envelope of `ts`, `level`, `logger`, `message`, `correlation_id`, plus `context` holding every
`extra=` field, plus `exception`/`error` when an exception was passed (logging.py:200-220). The
`event` name, where there is one, lives **inside `context`** — a query must be `context.event`, not
a top-level `event`.

**Only the admin subsystem emits named events.** The bot, worker, pipeline and providers log English
prose, so any grep against them matches wording that is free to change. The prose lines worth
knowing:

| What you want to know | Grep for | Where |
| --- | --- | --- |
| The bot/worker booted, and off which env file | `host verified` | runtime/startup.py:33 |
| The bot is polling | `bot starting` | main.py:169 |
| The worker is up | `worker dependencies built` | worker.py:47 |
| A sweep ran | `retention sweep finished` | retention_job.py:267 |
| A sweep failed | `the retention purge failed` | retention_job.py:280 |
| Bytes were orphaned | `an expired object could not be deleted from storage` | retention_job.py:151 |
| The balance poll ran | `vendor balance poll finished` | vendor_balance_job.py:352 |
| The paywall is on and the meter is off | `the checkout is wired but the credit meter is dark` | main.py:186 |
| The database is unreachable | `database ping failed` / `database unreachable` | db/engine.py:109, :112 |

The named admin events that should page are `admin.audit.chain_broken` (ERROR),
`admin.audit.revoke_missing`, `admin.audit.write_failed` and
`admin.session.mirror_invalidation_failed` — the last meaning a revoked session may survive until
its mirror expires.

> **Turning on `HBD_IS_DEBUG` to get more detail silently reformats the whole stream.** It is the
> only switch between JSON and the plain `%(asctime)s %(levelname)s [%(correlation_id)s]` formatter
> (logging.py:230-243); `HBD_LOG_LEVEL` does not change the format. A shipper's parsing rules break
> at the worst possible moment. In prod the admin process refuses DEBUG outright
> (settings.py:589-593, citing the ORM echoing "names, notes, lyrics"); the bot and worker have no
> such refusal, only the `_NOISY_LOGGERS` floor pinning sqlalchemy/aiogram/uvicorn.access at
> ≥ WARNING (logging.py:100-113, :247-248).

Cron jobs bind no correlation id, so every line they emit carries `correlation_id: "-"` — a failed
sweep is found by timestamp and message, never by correlation. Admin request logs record the **route
template**, never the raw path, and an unrouted request as the constant `<unmatched>`
(logging_mw.py:31-33, :74-93): you cannot recover an order id or a query string from them, which is
the point (logging_mw.py:1-14).

---

## 19. Things this repository cannot fix for you

These are real exposures with no in-repo remedy. They belong to whatever fronts the panel.

**No `Strict-Transport-Security`, ever.** The application emits exactly three fixed security headers
— `x-content-type-options: nosniff`, `referrer-policy: no-referrer`, `cache-control: no-store` —
plus a per-response CSP (middleware/security_headers.py:73-77, :145). A case-insensitive grep for
`strict-transport` across `src/` and `deploy/` returns nothing, and the CSP carries no
`upgrade-insecure-requests`. A first plain-`http://` request is not upgraded by anything this code
controls. The Secure cookies will not travel over it — that part fails closed — but the login form
and the URL do.

**The bind address is not a control this code holds.** `HBD_ADMIN_HOST` and `HBD_ADMIN_PORT` are
read by nothing that binds a socket; their only consumers are the config view
(schemas/config_view.py:108-109, :202-203). The bind comes from the uvicorn command line alone
(Makefile:75). Changing `HBD_ADMIN_PORT` changes what the panel **displays** and not what it
listens on — and if something starts the process with `--host 0.0.0.0`, the settings model cannot
detect it while `/api/config` keeps rendering `adminHost: 127.0.0.1`.

**Source maps are served unauthenticated and cached for a year.**
`admin-ui/vite.config.ts:125` sets `sourcemap: true`, and `/assets` is a plain `StaticFiles` mount
(app.py:296-300) behind a middleware stack that authenticates nothing (app.py:387-390), stamped
`public, max-age=31536000, immutable` (security_headers.py:82, :86). The complete TypeScript source of
the console is downloadable by anyone who can reach the origin, and a year-immutable cache means
removing it later does not un-cache it.

**`GET /api/config` publishes the deployment's topology to VIEWER.** `CONFIG_READ` is granted to
every role (security/permissions.py:240), and the view exposes database host/port, Redis host/port,
the claimed bind address, the trusted-proxy CIDRs and the argon2 cost parameters
(config_view.py:96-129). Secrets are correctly absent — it is an allowlist, and `admin_audit_dsn` is
reduced to a boolean — but the network facts are deliberately published.

**The "read-only data volume" is a mount property, not a code property.** The admin container is
handed a fully read-write `LocalFileStorage` (admin/container.py:155); only the filesystem can make
the read-only claim true. Path traversal *is* defended in code and soundly — `_resolve` refuses
absolute keys, backslashes, NULs, empty and `..` segments, then re-checks the resolved path is under
the root (storage.py:133-146) — so the gap is writes, not escapes.

**Nothing in this repository backs anything up.** No `pg_dump`, no snapshot script, no restore path.
The checkable form of that claim is `grep -rin backup README.md Makefile deploy/`, which returns
**zero hits** — same grep the sibling doc runs (00-host-inventory.md:93-94). Widening it to `docs/`
returns around thirty, and they are not counter-evidence: all but one are `docs/deployment/` saying
this same sentence in its own words. The one substantive hit for the word anywhere in the tree is
`docs/research/DASHBOARD_METRICS_RESEARCH.md:133`, where "backup" means a **fallback vendor**, not a data
backup. A real backup covers four things, three of which are not the database:

1. Postgres — including `credit_ledger`, `plan_purchases` and `topup_purchases`, which migration
   0020 calls receipts that answer disputes months after the name, the note and the audio are
   lawfully gone.
2. `<data root>/archive` — delivered audio **and** every customer avatar.
3. Redis — the only copy of every in-progress wizard draft (14-day TTL matched to the
   abandoned-draft clock, `bot/app.py:44-48, :83-85`) and of the queue.
4. `HBD_ADMIN_AUDIT_HMAC_KEY` — which lives in the admin env file, not in the database.

A database-only restore comes back with an audit log nobody can verify, rows pointing at archive
objects that are gone, and no in-flight orders.

> **The HMAC key is write-once.** The chain is
> `HMAC-SHA256(key, "v1" ‖ prev_hmac ‖ canonical_json(row))` (db/admin/audit.py:10-15) and there is
> no key-id or key-version column on `admin_audit_log` — so rotating the key is indistinguishable
> from tampering across the entire log, and `/audit/verify` will report a break at the first row
> forever. Losing it makes the log permanently unverifiable. Back it up somewhere that is not the
> same backup as the table it signs.

**`var/workspace` is deleted by nothing.** Every song, greeting, cover and lyric sheet exists twice
on disk: the archive copy, swept on the retention clock, and the workspace copy, which no code in
this repo ever removes. `grep -rn 'rmtree\|\.unlink\|os\.remove' src/` — note `.unlink` with **no**
parenthesis — returns three deleting call sites, and none of them touches a published workspace
file:

| Call site | What it deletes |
| --- | --- |
| `storage.py:211` — `await asyncio.to_thread(resolved.unlink, True)` | The object-store deletion primitive, the one the retention sweep and `/forget` both run. It is rooted at the archive: the single `LocalFileStorage` is constructed `LocalFileStorage(archive)` (runtime/container.py:311), so it cannot reach `workspace`. |
| `storage.py:339` | A failed atomic write, cleaning up its own temporary file. |
| `audio/tempfiles.py:44` | A per-call scratch directory. |

The parenthesis matters and is worth a warning to whoever re-runs this: a pattern of `.unlink(`
silently misses the first row, because that call passes the method as a value to
`asyncio.to_thread` rather than calling it. A search that misses the tree's only object-deletion
primitive is not evidence of anything.

Whether anything sweeps `var/workspace` out of band is a host question.

---

## Quick reference: what a healthy deployment answers

| Question | Where the answer is | Healthy value |
| --- | --- | --- |
| Which env file did this process read? | `host verified` → `context.env_file`; `admin.boot.ok` → `context.env_file` | the intended path, not a checkout `.env` |
| Is this really prod? | the same two lines, `context.environment` | the exact string `prod` |
| Is the console bundle current? | absence of `admin.spa.nonce_placeholder_missing` | no such line |
| Are vendor keys near the panel? | `admin.boot.vendor_env_present` | no such line (in prod it is a boot refusal, so a running prod panel is itself the evidence) |
| Did the REVOKE land? | `GET /api/audit/verify` → `chainProtection` | `revoke+hmac` |
| Is the whole chain verified? | the same call → `ok` **and** `isComplete` | both true |
| Is the sweep running? | `SELECT max(ran_at) FROM purge_runs` | within the last hour |
| Are bytes leaking? | `storage_keys_returned` vs `storage_keys_deleted` | equal |
| Is the deployment observable? | `curl -H 'X-Probe-Token: …' /readyz` | a body with `database` and `redis`, not a bare `{"status":"ok"}` |
