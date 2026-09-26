# Security controls and their deployment dependencies

Almost every control in the admin panel is a joint venture between this repository and a host.
The code half is knowable: it is in the tree, it has line numbers, and it is cited below. The
host half — what binds the socket, what terminates TLS, what the dotenv files on the box
actually say — used to be unknowable from here; **since 2026-09-10 most of it is readable
read-only on one host, and the part that still is not is the part behind a password.** Where a
control needs both halves, this document says so plainly rather than assuming the second one
landed, and where the second half has now been *observed* it says that, with the date.

Each section is the same four questions: what the control protects, what the deployment has to
do for it to exist, how to prove it is actually on, and what it looks like when it is not. As of
2026-09-10 each also carries a **verdict** against one real host.

> **REVISED 2026-09-10: THE HOST IS NOW REACHABLE READ-ONLY, AND SIX OF THE SEVEN CONTROLS HAVE
> BEEN CHECKED AGAINST IT.** This box used to say "the production host is out of reach from here;
> nothing in this document is an observation about it." That is withdrawn. The code half is still
> in the tree with line numbers; the host half is now checked against `aizu` (machine
> `abdu-test`), and each claim says which it is:
>
> | Marker | What it promises |
> | --- | --- |
> | *(unmarked)* | A claim about this repository's code. Open the cited file. |
> | `[HOST 2026-09-10]` / `[HOST 2026-09-11]` | A read-only command was run against `abdu-test` on that date and the quote is faithful to its output. |
> | `[UNPROVEN]` | Nobody has established it, with the blocker named. **These are the most important sentences on this page** — an unproven control and a working one look identical from a distance, and the whole value of this marker is refusing to collapse them. |
>
> **One host is not all hosts.** Another deployment may answer differently on every row, and the
> *checks* below are what you run there. `deploy/systemd/*.service` are no longer purely
> speculative — near-identical units are installed, running and enabled — and
> `deploy/caddy/admin.bayrambot.uz.caddy` is deployed into `/etc/caddy/Caddyfile`.
> `deploy/first-install-proposal.md` is still a proposal and still flagged as one at each use.
> **The host is pre-rename** (`hbd-*` units, `/etc/hbd`, `HBD_*`, package `hbd`) and the
> repository is post-rename; both are correct, and `08-payme.md`'s NAMING note is why.

## The verdict board

Read this before the sections. A control that is **provably on** is one where a command run
against the host returned the answer, not one where the code looks right.

| # | Control | Verdict on `abdu-test` | The short reason |
| - | --- | --- | --- |
| 1 | Vendor-credential separation | **PROVABLY ON** | The panel runs `environment: prod` and would not have booted otherwise; `admin.boot.vendor_env_present` never logged. The *file* half of the scan is a no-op here, though — §1 "How it fails" |
| 2 | CSP + style nonce | **PROVABLY ON** | The exact policy is on the wire, the nonce differs between fetches, `/assets/` is immutable, zero `nonce_placeholder_missing` |
| 3 | `__Host-` cookies / TLS | **ON in code, BROKEN in the deployment** | `is_cookie_secure: true` on every boot — but the login shell is **served over plain `http://` with no redirect**. §3 |
| 4 | Exact origin check | **PROVABLY ON**, both directions | A real sign-in succeeded; a forged `Origin` was refused 403 with `reason: origin_mismatch` |
| 5 | Trusted proxies / client-IP | **`[UNPROVEN]`, and unprovable without a password or a session** | The correct values are derivable (`hops=2`); whether the file holds them is unreadable. This is the row with no signal at any level |
| 6 | Audit HMAC chain + REVOKE | **HMAC half ON. REVOKE half PROVABLY OFF** | Anchors re-pinned hourly, `chain_broken` never logged; but `admin.audit.revoke_missing` fired, and the root cause is a release script that will reproduce it |
| 7 | Loopback binding | **PROVABLY ON at the socket — but the ARGUMENT IT RESTS ON NO LONGER HOLDS** | Only `127.0.0.1:8080` listens. The panel is nevertheless published to the whole internet, with no MFA and no IP allowlist. §7 |
| 8 | **The Payme gateway** (new section) | **ITS OWN TWO BOOT REFUSALS ARE DISARMED** | It runs `environment: dev` on the production host, and both its refusals are gated on `is_production`. §8 |

**Behind the permission wall, and therefore `[UNPROVEN]` however the prose is phrased:**
everything in `/etc/hbd/*.env` — so every `BAYRAM_ADMIN_TRUSTED_PROXY_*`,
`BAYRAM_ADMIN_PROBE_TOKEN`, DSN and role name; **live** schema privilege (`has_schema_privilege`);
`/var/lib/hbd` and everything under it; `/usr/local/bin/hbd-migrate`; and the alembic revision
currently stamped.

**Four things this section used to file behind that wall are answered, and for free.** They were
answered on 2026-09-11 out of artefacts that need no privilege at all — the world-readable
`pg_dump` files in `/var/backups/hbd` and the `adm`-readable Postgres server log — and
`00-host-inventory.md` rows 12–14 carry them with their commands. **Do not spend a sudo password
on these:** both roles exist (row 12, by the server log's `DETAIL` line — see the box in §6);
table ownership and the grants are in the dump (row 14: 29 tables, every one `OWNER TO hbd_app`);
and neither `hbd_purge_audit_log` nor `hbd_purge_audit_reasons` exists, because the dump carries
zero `CREATE FUNCTION` statements (`03-provisioning.md` §4). A wall that is not real teaches
operators to stop looking, which is the failure this paragraph exists to prevent. `[HOST 2026-09-11]` The wall is one wall: `/etc/hbd` is
`Permission denied` to `developer`, `sudo -n` answers `sudo: a password is required`, there is no
`~/.pgpass`, and Postgres listens on `127.0.0.1:5432` with password auth. `/opt/hbd/diagnose.sh`
on the host answers three of those in four queries and needs exactly one sudo password.

---

## 1. Vendor-credential separation

### What it protects

The admin process is the one thing on this system an operator signs into from a browser, over
the public internet, with a password. It is therefore the most exposed process in the fleet,
and it is deliberately the one with nothing worth stealing: no Telegram bot token, no
ElevenLabs key, no LLM key. The separation is structural before it is procedural —
`AdminSettings` has no field that could hold one, so even a value present in the environment
has nowhere to land (`src/bayram/admin/settings.py:164` sets `extra="ignore"`).

**SUPERSEDED 2026-09-10: there are SIX forbidden names now, in TWO populations, and the
comprehension this section used to quote has been replaced by a function.** The old text said
"the four forbidden names are derived, never restated" and quoted a one-expression
`FORBIDDEN_ENV_VARS`. The count was already wrong (the tuple held five) and the derivation has
since widened:

```python
# src/bayram/admin/app.py:134-165 (abridged; the docstring is the part worth reading)
def derive_forbidden_env_vars() -> tuple[str, ...]:
    return tuple(f"{ENV_PREFIX}{name.upper()}" for name in VENDOR_SECRET_FIELDS) + (
        FOREIGN_SECRET_ENV_VARS
    )

FORBIDDEN_ENV_VARS: Final[tuple[str, ...]] = derive_forbidden_env_vars()   # app.py:167
```

**Why two populations, because the distinction is the whole point.** The first five are
credentials declared as **fields** on `bayram.config.Settings`, spelled by upper-casing
`VENDOR_SECRET_FIELDS` — so a sixth credential added to that class is covered here without
anybody remembering this file exists. The sixth is `FOREIGN_SECRET_ENV_VARS =
(f"{ENV_PREFIX}PAYME_MERCHANT_KEY",)` (`src/bayram/config.py:171`): an environment variable **name
belonging to a settings model this process never loads at all** (`bayram.payme.settings.PaymeSettings`),
which is why it cannot be derived from a field tuple. The tuples are kept separate for a mechanical
reason too — `tests/test_admin/test_settings_and_boot.py` asserts **set equality** between
`VENDOR_SECRET_FIELDS` and every secret-shaped field name on `Settings`, so a name with no field
behind it would fail the test whose whole job is to stop the *next* credential being forgotten.

**And say what the sixth name buys, because it is the mechanism behind a claim made elsewhere in
this tree.** A prod admin host that can reach the Payme cashbox key **refuses to boot**. That is
what makes "the Payme endpoint is not a router on the panel" (`08-payme.md` §1.1) a mechanical
fact rather than an intention: the endpoint cannot quietly be moved onto this app later. The key's
blast radius is different in kind from the five outbound credentials — stealing an outbound key
spends our money at a vendor or impersonates our bot; stealing this one **mints credits** by
forging settlements at our own gateway. Three blast radii, three containers; §8 is the third.

`VENDOR_SECRET_FIELDS` is `telegram_bot_token`, `elevenlabs_api_key`, `llm_api_key`,
`llm_fallback_api_key` and `openrouter_management_key` (`src/bayram/config.py:133-139`) — five,
not three. The fifth arrived with **D13** and is the sharpest of them: an OpenRouter
management key can create and revoke API keys on the account, so its theft locks the workers
out rather than merely billing us. It is optional — unset, every process starts and the
balance poller reports the uncapped key it always did — and it is read by exactly one place,
the worker's hourly balance poll. The narrower tuple
`REQUIRED_VENDOR_SECRET_FIELDS` (`src/bayram/config.py:146-150`) is a different claim entirely:
"the bot cannot start without it", not "the admin host must never hold it". Adding a sixth
credential to `bayram.config` covers it here without anybody remembering to.

### What the deployment must do

Keep all six out of the admin process's environment **and** out of the dotenv file that
process reads. The scan covers both sources, because both are real:

```python
# src/bayram/admin/app.py:175-183
from_file = _env_file_names()
return tuple(name for name in FORBIDDEN_ENV_VARS if os.environ.get(name) or name in from_file)
```

The file half reads whatever `resolve_env_file(ADMIN_ENV_FILE_VAR, ADMIN_ENV_FILE)` returns
(`app.py:141-149`) — the same call `build_admin_settings` makes (`settings.py:75-81`,
`:661-668`), so the scan cannot clear a host whose credentials sit in the file that was really
loaded. That equality is load-bearing and the comment at `app.py:143-146` says why.

`BAYRAM_ENVIRONMENT` must be exactly `prod` on the admin process, because the refusal is
conditional on it:

```python
# src/bayram/admin/app.py:191-199
if settings.is_production:
    raise ConfigError(
        "The admin process must not hold a vendor credential or a bot token, ..."
    )
```

`AdminSettings.environment` is a closed `Literal["dev","staging","prod"]`
(`src/bayram/admin/settings.py:169`), so a typo there fails the boot rather than downgrading the
control — unlike `Settings.environment` on the bot and worker, which is a bare `str`
(`src/bayram/config.py:170`) and will happily accept `production`.

### How to verify it is actually on

In prod the running process **is** the evidence: it would not have started. What you can check
is the reverse — that nobody is relying on a warning nobody reads:

```bash
# On the admin host, whatever collects its stdout.
grep 'admin.boot.vendor_env_present' <the admin process's log>
# MUST be empty. In prod it cannot be non-empty and also be running; on staging it can.

grep 'admin.boot.ok' <the admin process's log>
# Confirms environment= and env_file= — i.e. which file the scan and the settings both read.
```

Both are JSON lines with the name under `context.event`, not at the top level
(`src/bayram/logging.py:200-220`). `admin.boot.ok` carries `environment`, `env_file`,
`is_cookie_secure` and `public_origin` (`app.py:322-333`); it is the single line that
distinguishes "prod panel on prod config" from "prod panel booted off a dev checkout".

> **VERDICT: PROVABLY ON, by the strongest evidence available — the process is running in prod.**
> `[HOST 2026-09-11]` On `abdu-test` the two greps above are
> `journalctl -u hbd-admin -o cat | grep admin.boot…`, they need no `sudo`, and they answer:
>
> ```json
> {"event":"admin.boot.ok","environment":"prod","env_file":".env.admin",
>  "is_cookie_secure":true,"public_origin":"https://admin.bayrambot.uz"}
> ```
>
> `environment: prod` on every boot, and `admin.boot.vendor_env_present` has **never** been
> logged in the whole journal. In prod a vendor credential within reach is a refusal, so a
> *running* prod panel is itself the proof.
>
> **And the unit file adds a control these documents did not know existed.**
> `hbd-admin.service` loads `EnvironmentFile=/etc/hbd/hbd-admin.env` and nothing else, with a
> comment forbidding the bot's file. `hbd-payme.service` goes further:
> `InaccessiblePaths=/etc/hbd/hbd.env /etc/hbd/hbd-admin.env` — confirmed at runtime with
> `systemctl show hbd-payme -p InaccessiblePaths`. That is the separation argued for in code
> above, enforced **by the kernel**, for the one process holding the cashbox key. Nobody should
> "simplify" that line away.

### How it fails

Three ways, in descending order of how quietly.

**Staging is a warning, not a refusal** (`app.py:200-203`). A staging admin host holding a real
ElevenLabs key boots normally and logs one WARNING.

**A missing dotenv file silences the file half of the scan.** `_env_file_names` catches only
`OSError` (`app.py:162-171`), and `dotenv_values` on a path that does not exist returns an
empty mapping without raising. So a mistyped `BAYRAM_ADMIN_ENV_FILE` gives you the environment
half of the check and no signal at all that the other half found nothing. What saves this is not
the scan but the chain around it: with the file unread, `BAYRAM_DATABASE_URL` (`settings.py:174`,
`min_length=1`, no default) and `BAYRAM_ADMIN_AUDIT_HMAC_KEY` (`settings.py:229`, `SecretStr`,
`min_length=32`, no default) are missing, and those are required fields — so
`build_admin_settings()` raises `ConfigError` inside `_resolve_settings` (`app.py:313`, `:351`),
two lines *before* `_refuse_disabled_panel` (`app.py:315`) is reached. Expect a pydantic
field-required report naming `BAYRAM_DATABASE_URL`, **not** the "Set BAYRAM_ADMIN_ENABLED=true in
.env.admin" message (`app.py:120-122`) — the disabled-panel refusal never gets a turn on a host
whose only problem is a mistyped `BAYRAM_ADMIN_ENV_FILE`. A field-required report on a config you
believe is complete is the signature of a dotenv file that was not read.

> **ON `abdu-test` THE FILE HALF OF THIS SCAN IS A NO-OP, AND THE CONTROL SURVIVES BY ACCIDENT
> RATHER THAN BY DESIGN.** `[HOST 2026-09-11]` `systemctl show <unit> -p Environment` is **empty**
> for `hbd-bot`, `hbd-worker` and `hbd-admin` — none of them sets `HBD_ENV_FILE` or
> `HBD_ADMIN_ENV_FILE`. So `resolve_env_file` falls back to the *relative* defaults and the panel's
> boot line prints `"env_file": ".env.admin"` — a path relative to `WorkingDirectory=/var/lib/hbd`
> that does not exist. `dotenv_values` on it returns `{}` without raising, and the file half of the
> scan therefore reads nothing and reports nothing: the degradation table's "**None**" signal, live.
>
> **What saves it is that real configuration arrives through `EnvironmentFile=/etc/hbd/*.env`
> straight into `os.environ`** — which is exactly what the *environment* half of the scan covers.
> So on this host the scan is effective over everything the file contains, and the file half is
> simply idle. That is a property of the unit file, not of the application, and it would stop being
> true the moment somebody moved a credential into a dotenv file the panel loads itself. **Do not
> read `env_file` on the boot line as "the file this process read"** — read `systemctl cat <unit>`.
> `06-troubleshooting.md` §8 has the same warning aimed at the operator following its Quick
> reference, which would otherwise diagnose this healthy host as broken.
>
> Only the gateway names its file explicitly —
> `Environment=HBD_PAYME_ENV_FILE=/etc/hbd/payme.env` — and its boot line prints the absolute path,
> which is the shape the other three should have.

**The disabled-panel refusal runs first.** `app.py:315-316` calls `_refuse_disabled_panel`
before `_refuse_vendor_credentials`, and both raise `ConfigError`. On a host that has both
problems the operator is told the panel is disabled and never learns a vendor key was within
reach.

---

## 2. The CSP, and the style nonce that keeps it closed

### What it protects

The panel renders customer-written free text — recipient names, notes, lyrics — same-origin,
under an operator's session cookie. A body a browser is allowed to sniff as HTML runs *at the
panel's origin*, and `script-src 'self'` does not stop an inline event handler inside such a
document. So the sniff is refused rather than survived (`security_headers.py:1-8`).

The policy is stamped on every response, at the ASGI `http.response.start` boundary, so no
handler, exception path or static file can opt out:

```
default-src 'self'; script-src 'self'; style-src 'self' 'nonce-{nonce}';
img-src 'self' data:; media-src 'self'; connect-src 'self'; object-src 'none';
base-uri 'none'; frame-ancestors 'none'; form-action 'none'; worker-src 'none'
```

(`src/bayram/admin/middleware/security_headers.py:58-70`.) Alongside it go three constants —
`x-content-type-options: nosniff`, `referrer-policy: no-referrer`, `cache-control: no-store`
(`:73-77`) — and they **replace** rather than append, because two `Cache-Control` headers is
one header a proxy may resolve either way and the way that loses is the one that caches
(`:145-150`).

The nonce exists for one reason. `react-remove-scroll`, mounted by every Radix modal, injects a
real `<style>` element at runtime; `style-src 'self'` blocks it. So a fresh nonce is minted per
response (`security_headers.py:119-121`) and stamped into the SPA shell's `<meta
name="csp-nonce">` by a single `str.replace` of the literal `__BAYRAM_CSP_NONCE__`
(`src/bayram/admin/shell.py:55`, `:86`). It is a meta element rather than an inline script
precisely so `script-src` never needs a nonce of its own (`shell.py:25-29`).

### What the deployment must do

Make sure the bundle on the host was built from the TypeScript being deployed.
`src/bayram/admin/static/` is gitignored, so it is never carried by a `git pull`; the repository
supports two ways for it to arrive, and which one your host uses is a **host question** — answered
below for `abdu-test`, and one you must answer for yours before following either bullet:

- **A git checkout that builds in place.** Then the directory holds whatever the last
  `npm run build` left there, and rebuilding is mandatory on every deploy:

  ```bash
  cd <checkout>/admin-ui && npm ci && npm run build
  ```

  That is `make ui-build` (Makefile:92-93), and it is *not* reachable from `make install` or
  `make check` (Makefile:58-60, :144). `deploy/first-install-proposal.md:129-138` — a proposal, and one that
  assumes this shape — correctly makes it mandatory and explains why.

- **An installed wheel.** The directory is force-included in the wheel through
  `[tool.hatch.build.targets.wheel] artifacts` precisely so that an installed wheel ships the
  bundle (`pyproject.toml:60-65`, and the comment at `app.py:124-127` saying why). Then the
  bundle is whatever the machine that *built* the wheel compiled, `npm` need not exist on the
  host at all, and the rebuild belongs in the build pipeline instead.

Either way the failure is the same and the check below is the same: a bundle older than the
Python it is served by. Only the place you fix it moves.

> **ANSWERED 2026-09-10 for `abdu-test`: it is the WHEEL shape, and `npm run build` is impossible
> there.** `[HOST 2026-09-11]` `which node npm` returns nothing — there is no Node on the box.
> `/srv/hbd` does not exist; there is no checkout at all. The bundle ships inside the installed
> wheel at `/opt/hbd/venv/lib/python3.12/site-packages/hbd/admin/static/` — `index.html` 636
> bytes plus `assets/`, all root-owned, dated Sep 10 00:01 — with 23 `admin/static` entries in
> `hbd_bot-0.1.0.dist-info/RECORD`. The installed distribution is still `hbd_bot-0.1.0`.
>
> So on this host **every "rebuild the console" instruction belongs to the machine that builds the
> wheel**, and the release runbook is `08-payme.md` §11. `06-troubleshooting.md` §1 and §2 carry
> the one-line test that tells the two shapes apart, because getting it wrong sends an operator
> hunting for an `npm` that will never be there.

Serve the panel at the **root of its own origin**. Everything is absolute: the bundle
references `/assets/…`, the cache carve-out is a literal prefix match on `"/assets/"`
(`security_headers.py:82`), the API is `"/api"` (`deps.py:108`), and both cookies are
`Path=/`. A subpath mount breaks all four at once.

### How to verify it is actually on

```bash
# From a machine that can reach the panel. Headers only; no session needed for the shell.
curl -sI https://<panel host>/ | tr -d '\r' | grep -Ei 'content-security-policy|nosniff|cache-control|referrer'

# The nonce must differ between two fetches. If it is byte-identical, it is not a nonce.
curl -s https://<panel host>/ | grep -o 'content="[A-Za-z0-9_-]*"'
curl -s https://<panel host>/ | grep -o 'content="[A-Za-z0-9_-]*"'

# The bundle is stale if this ever appears:
grep 'admin.spa.nonce_placeholder_missing' <the admin process's log>
```

`/assets/` must come back `public, max-age=31536000, immutable`; everything else, the shell
included, must come back `no-store`.

> **VERDICT: PROVABLY ON.** `[HOST 2026-09-11]` The policy on the wire from
> `https://admin.bayrambot.uz/` is character-for-character the template above, including
> `object-src 'none'; base-uri 'none'; frame-ancestors 'none'; form-action 'none'; worker-src
> 'none'`, alongside `x-content-type-options: nosniff`, `referrer-policy: no-referrer` and
> `cache-control: no-store`. Two consecutive fetches returned **different** nonces
> (`lXQAqk-u-nJkFLJfe2OSCg`, then `6Cx6skd9c3fmD5GqLCuHeg`), which is the check that distinguishes
> a nonce from a constant. `/assets/index-D9iMG-RF.js` comes back
> `cache-control: public, max-age=31536000, immutable`. And
> `admin.spa.nonce_placeholder_missing` has **never** been logged in the whole journal, so the
> deployed bundle is not stale.

### How it fails

**A stale bundle degrades silently and looks like a broken panel, not a stale deploy.**
`render_shell` serves the HTML unchanged and logs one WARNING rather than raising
(`shell.py:78-85`), which is the right call during an incident — but the only user-visible
symptom is that the background keeps scrolling under an open dialog. There is no 500, no
banner, no failed request. Nothing in the Python suite checks the *built* shell; the
placeholder test reads the checked-in source at `admin-ui/index.html`
(`tests/test_admin/test_spa_nonce.py:49`), and the browser gate rebuilds before it runs
(Makefile:112). Staleness is caught by no gate at all — only by that grep.

**A missing bundle is a 404, not a crash.** `if not SPA_INDEX.is_file(): raise
HTTPException(status_code=404)` (`app.py:238-239`), and the `StaticFiles` mount is
`check_dir=False` (`app.py:295-300`). A console that 404s on every browser URL is
indistinguishable at the process level from a healthy one: `/healthz` and every `/api` route
answer normally.

**The outermost 500 is unprotected.** A failure inside `UnhandledErrorMiddleware` itself is
answered by Starlette's `ServerErrorMiddleware`, outside every layer installed here
(`app.py:382-390`) — so that one response carries no nosniff, no CSP and no `no-store`.

> **The bundle ships its own source maps.** `admin-ui/vite.config.ts:125` sets
> `sourcemap: true`, and `/assets/` is mounted with no authentication in front of it
> (`app.py:295-300`; the middleware stack at `app.py:387-390` is
> UnhandledError/RequestLog/SecurityHeaders/CorrelationId, none of which authenticates). Anyone
> who can reach the panel's origin can download the console's full TypeScript, cached
> immutable for a year. Whether your TLS terminator blocks `/assets/*.map` is a host question;
> the application does not.
>
> **ANSWERED 2026-09-10, AND THE ANSWER IS NO.** `[HOST 2026-09-11]` The source map is
> downloadable from the public internet, unauthenticated, today:
>
> ```console
> $ curl -s -o /dev/null -w '%{http_code} %{size_download}\n' \
>     https://admin.bayrambot.uz/assets/index-D9iMG-RF.js.map
> 200 4242767
> ```
>
> 4.2 MB, and byte-identical in size to the same file fetched from loopback. A grep of the whole
> `/etc/caddy/Caddyfile` for a `*.map` rule finds only comment text: the admin block
> reverse-proxies the entire hostname. **Treat the console's TypeScript as disclosed.**
>
> The fix is at a layer this repository does not own — a Caddy `handle_path /assets/*.map {
> respond 404 }`, or a Cloudflare rule — and note the asymmetry the year-immutable cache creates:
> adding that rule later stops new fetches and does **not** un-cache what has already been taken.

---

## 3. `__Host-` cookies, Secure, and the TLS this repo does not terminate

### What it protects

The session cookie is a bearer credential. The `__Host-` prefix is not cosmetic: it is defined
so a browser refuses the cookie outright unless it is `Secure`, `Path=/` and carries no
`Domain` — which structurally prevents the sibling-subdomain injection that broke plain
double-submit CSRF (`src/bayram/admin/csrf.py:44-49`).

Both cookies are set that way, and the code cannot be configured out of it:

```python
# src/bayram/admin/routers/auth.py:304-330
for name, value, is_http_only in (
    (SESSION_COOKIE_NAME, issued.token.raw, True),
    (CSRF_COOKIE_NAME, issued.csrf_token, False),
):
    response.set_cookie(name, value, max_age=max_age, path="/",
                        secure=settings.is_cookie_secure, httponly=is_http_only, samesite="lax")
```

`is_cookie_secure` is a hardcoded `True` property with no environment input
(`settings.py:602-618`), and `admin_cookie_secure is False` is refused in *every* environment,
dev included (`settings.py:570-577`). The field is a refusal, not a switch. `SameSite=Lax`
rather than `Strict` is a deliberate usability trade — `Strict` drops the cookie on every
top-level navigation from elsewhere, so a filter URL pasted into a chat lands on a login screen
(`auth.py:311-315`) — and `Lax` still blocks every cross-site POST.

The session cookie is `HttpOnly`; the CSRF cookie deliberately is not, because it is transport
and not the value being compared (`auth.py:307-310`). See §4.

### What the deployment must do

Terminate TLS in front of the panel and set `BAYRAM_ADMIN_PUBLIC_ORIGIN` to the `https://` origin
a browser actually types. Nothing in the code makes TLS a boot condition:
`_origin_must_be_a_bare_origin` accepts either scheme (`settings.py:501-515`,
`_ORIGIN_SCHEMES` at `:94`), and the prod guard only checks that the variable was *set*
(`settings.py:578-588`).

Give the panel its own hostname. `__Host-` cookies are scoped `Path=/` by definition and cannot
be narrowed, so anything else served at that origin sees them.

Add `Strict-Transport-Security` at the proxy.

> **The APPLICATION never emits HSTS.** `SECURITY_HEADERS` is exactly three pairs
> (`security_headers.py:73-77`) and the CSP template carries no `upgrade-insecure-requests`
> (`:58-70`). A case-insensitive grep for `strict-transport` or `hsts` across **`src/`** returns
> nothing. A first request to `http://<panel host>` is upgraded by nothing the application
> controls: the session cookie will not be sent over it, but the login form and the operator's URL
> will. This is a proxy requirement.
>
> **NARROWED 2026-09-10.** That grep used to be written across `src/`, `deploy/` **and** `docs/`,
> and it no longer returns nothing: `deploy/caddy/admin.bayrambot.uz.caddy:74` carries
> `header Strict-Transport-Security "max-age=86400"`. The claim holds for `src/`, which is the
> part that matters — the application still emits none.

> **VERDICT ON `abdu-test`, IN TWO HALVES, AND THE SECOND IS WORSE THAN THIS SECTION PREDICTED.**
>
> **HSTS is present, supplied by Caddy.** `[HOST 2026-09-11]` `/etc/caddy/Caddyfile:95`, in the
> admin block: `header Strict-Transport-Security "max-age=86400"` — deliberately **without**
> `includeSubDomains` and **without** `preload`, and the Caddyfile's own comment gives the reason
> (sibling hostnames on `bayrambot.uz` that are not all HTTPS-only, and preload is close to
> irreversible). `curl -sI https://admin.bayrambot.uz/` returns
> `strict-transport-security: max-age=86400`. The `pay.bayrambot.uz` block sets none.
>
> **THE PANEL NEVERTHELESS SERVES ITS LOGIN SHELL OVER PLAIN, UNENCRYPTED HTTP.**
> `[HOST 2026-09-11]`
>
> ```console
> $ curl -sI http://admin.bayrambot.uz/
> HTTP/1.1 200 OK
> Content-Type: text/html; charset=utf-8
> Cache-Control: no-store
> content-security-policy: default-src 'self'; …
> strict-transport-security: max-age=86400
> via: 1.1 Caddy
> Server: cloudflare
> ```
>
> **200, with the SPA shell, and no redirect at any layer** — Cloudflare's "Always Use HTTPS" is
> off for this hostname. HSTS on a cleartext response is worth nothing to a browser that has not
> already made one HTTPS visit, and an operator typing the hostname for the first time is exactly
> that browser. This is precisely the residual risk "How it fails" names below, now **observed
> rather than predicted**.
>
> The `__Host-` prefix means nobody can complete a sign-in over it — the browser refuses the
> cookie on a non-secure origin, so that half fails closed and loudly — but the login **form** and
> the typed URL travel in the clear first, and a credential typed into a cleartext form is already
> gone before the cookie refusal happens.
>
> **Fix:** a Cloudflare "Always Use HTTPS" rule for `admin.bayrambot.uz`, or a Caddy `http://`
> redirect. `08-payme.md` §4.6 tracks the Cloudflare settings nobody has applied. Until then,
> treat the panel's login page as publicly sniffable.

### How to verify it is actually on

```bash
curl -sI https://<panel host>/ | tr -d '\r' | grep -i strict-transport-security
# Comes from your proxy or from nowhere. Absent means nobody added it.

# After a real sign-in in a browser: DevTools → Application → Cookies. Both must read
# __Host-bayram_session (HttpOnly, Secure, SameSite=Lax, Path=/) and __Host-bayram_csrf
# (Secure, SameSite=Lax, Path=/), and neither may carry a Domain.

grep 'admin.boot.ok' <the admin process's log>   # is_cookie_secure must be true
```

### How it fails

Loudly, and that is the good direction. If the browser does not treat the panel's origin as a
secure context, it rejects both `Set-Cookie` headers outright and nobody can sign in at all —
a panel that is unusable rather than merely insecure, which is exactly the argument at
`settings.py:572-577`. The failure mode to actually worry about is the one above it: a panel
reachable over plain `http://` on a hostname the operator is willing to type, where the login
form is submitted before any cookie is involved. **`[HOST 2026-09-11]` That is the state of
`abdu-test` — see the box above.** The code half is confirmed sound on the same host:
`is_cookie_secure: true` on **every** `admin.boot.ok` without exception, and nothing on a host can
weaken it, because `is_cookie_secure` is a hardcoded property with no environment input
(`settings.py:602-618`).

---

## 4. The exact origin check (and the CSRF token that does not depend on it)

### What it protects

Two of the three CSRF layers live in `src/bayram/admin/csrf.py`; the third is `SameSite=Lax` on
the cookie. The header is compared against `admin_sessions.csrf_token` — a database column —
and never against a cookie:

```python
# src/bayram/admin/csrf.py:96-111
if stored_token is None or not _is_comparable(stored_token):
    # No live session token to compare against: refuse rather than fall back to the
    # cookie, which is the failure mode this whole design exists to remove.
    return CsrfDecision.SESSION_TOKEN_MISSING
if not secrets.compare_digest(header_token, stored_token):
    return CsrfDecision.TOKEN_MISMATCH
```

This is the strongest control on the list and the only one with no deployment dependency at
all beyond the database being reachable. A hostile sibling subdomain, or a machine-in-the-middle
on any `http://` host under the registrable domain, can set a cookie the browser will send — and
buys nothing, because the value actually compared is one it cannot read or write. Worth stating
explicitly so that nobody "simplifies" it back to double-submit.

The origin check in front of it is exact — no prefix, suffix or subdomain matching — and a
**missing** `Origin` on a state-changing request is a refusal, because every browser that can
reach this panel sends it on non-GET (`csrf.py:76-88`, `:12-14`). Outside dev the accepted set
holds exactly one element (`settings.py:620-632`). `GET` and `HEAD` are exempt; `OPTIONS` is
not, because this API is same-origin and serves no CORS preflight (`csrf.py:52`, `:16-20`).

### What the deployment must do

Set `BAYRAM_ADMIN_PUBLIC_ORIGIN` to the exact origin the browser sends — scheme, host and port,
no path, no trailing slash — and make sure the panel is reachable at **that origin and no
other**. A second hostname, a `www.` variant or a bare IP will each 403 every mutation.

The proxy must pass `Origin` through unmodified. It must not strip it and it must not rewrite
it. (This is the same reason the dev Vite proxy sets `changeOrigin: false` —
`admin-ui/vite.config.ts:11-23, 132-135` — where the "convenient" flag would rewrite `Origin`
to the target and disable the panel's only cross-site control everywhere but production.)

> **The example file disarms the boot guard.** The prod refusal keys on
> `"admin_public_origin" not in self.model_fields_set` (`settings.py:578-581`) — it catches
> *unset*, not *wrong*. And a dotenv-supplied value counts toward `model_fields_set`. The
> shipped example ships the variable set, uncommented, to the loopback dev value
> (`.env.admin.example:73` — `BAYRAM_ADMIN_PUBLIC_ORIGIN=http://127.0.0.1:8080`), and
> `deploy/first-install-proposal.md:103` (a proposal) copies that file verbatim to the host. A prod host that
> inherited that line boots clean, passes `/healthz` and serves the login *page* — `GET` is
> exempt (`csrf.py:52`) — and then refuses the login `POST` itself. Sign-in is **not** the part
> that still works: `login` calls `_enforce_origin` as its first act (`auth.py:450`), and that
> raises `ORIGIN_REJECTED` on a mismatch (`auth.py:179-190`). The guard's own message
> (`settings.py:582-588`) predicts "serve a login page and then reject every mutation", which
> is a shade optimistic: nobody gets far enough to attempt one.

### How to verify it is actually on

```bash
grep 'admin.boot.ok' <the admin process's log>   # public_origin= is the configured value
```

Or, signed in as any role, `GET /api/config` → `adminPublicOrigin` (`config_view.py:110`,
`:204`). Note that the value reported at boot and on `/api/config` is the single configured
origin; only the CSRF comparison widens, and only in dev (`settings.py:625-630`).

The behavioural check is the real one: **try to sign in.** With a wrong `BAYRAM_ADMIN_PUBLIC_ORIGIN`
the login form renders and the login `POST` 403s with `ORIGIN_REJECTED` — the login handler runs
`_enforce_origin` before it does anything else (`auth.py:450`). If sign-in succeeds, the
configured origin matches what your browser sends; then perform any write, and a 403 on the first
mutation is the same control refusing an authenticated request instead (`deps.py:217-238`).

### How it fails

It boots clean and fails at the sign-in, every time — not at the first write. The two refusals are
the same check in two places and they log under **different event names**, which matters when you
are grepping:

```bash
# The one that actually fires on a wrong BAYRAM_ADMIN_PUBLIC_ORIGIN: the refused login POST.
grep 'admin.login.origin_refused' <the admin process's log>   # auth.py:186-189

# Only ever emitted from the authenticated path (deps.py:230-236), so it stays empty while
# nobody can sign in. Absence here is not evidence the origin check is innocent.
grep 'admin.csrf.refused' <the admin process's log>
```

Both are WARNINGs, one per refusal. On `admin.csrf.refused`, `ORIGIN_REJECTED` distinguishes an
origin problem from `CSRF_REJECTED`'s token problem (`deps.py:208-238`, `_CSRF_CODES` at
`:208-215`); `admin.login.origin_refused` carries the raw `CsrfDecision` in `reason` instead
(`auth.py:188`), so `origin_mismatch` there is the wrong-value case and `origin_missing` is a
proxy that stripped the header.

> **VERDICT: PROVABLY ON, IN BOTH DIRECTIONS — the only control on this list with a negative test
> behind it.**
>
> **Positive.** `[HOST 2026-09-11]` `admin.boot.ok` carries
> `"public_origin": "https://admin.bayrambot.uz"`, that hostname answers HTTP/2 200 from the open
> internet, and `admin.login.ok` has been logged — somebody has signed in through it. A wrong
> origin would have made that impossible, because `login` calls `_enforce_origin` as its first act.
>
> **Negative.** `[HOST 2026-09-10]` A `POST /api/auth/login` from loopback carrying
> `Origin: http://evil.example` returned **403** and logged
> `{"event":"admin.login.origin_refused","reason":"origin_mismatch"}` (logger
> `hbd.admin.routers.auth`, 14:32:19 +05) followed by an `admin.request` row at status 403 — the
> exact reason string this section predicts, from the exact code path it names.
>
> **Two honest footnotes.** That probe is the **only** `admin.login.origin_refused` in the journal;
> it used the throwaway username `origin-probe-surveyor` and it charged one attempt against the
> strict `(username, client_ip)` counter, exactly as `06-troubleshooting.md` §5 warns. **If you are
> reading that line in the journal, it is ours, not an attack.** And `admin.csrf.refused` still has
> zero hits, which is correct and is not evidence about this control: it fires only on the
> authenticated path.

---

## 5. Trusted proxies and client-IP derivation

This is the control most likely to be silently wrong on a real host, and the one whose failure
does the most damage per unit of invisibility. Read this section before the others if you are
short of time.

### What it protects

Every rate limit and every audit row records a client address. Behind a reverse proxy, the
transport peer is the proxy — so a per-IP limiter collapses into one bucket shared by every
operator and every attacker, and `admin_sessions.last_ip` records the proxy on every row
(`clientip.py:1-15`). Trusting `X-Forwarded-For` instead is worse: an attacker rotates it per
request and the limiter stops existing at all.

So the header is read only when both conditions hold:

```python
# src/bayram/admin/security/clientip.py:142-149
if hops == 0 or not forwarded_for or not is_trusted_peer(peer_ip, trusted_proxies):
    return str(peer)
entries = _forwarded_entries(forwarded_for)
index = len(entries) - hops
if index < 0:
    return str(peer)
client = _parse_ip(entries[index])
return str(client) if client is not None else str(peer)
```

The parser is properly hostile to its input: the header is truncated to the rightmost 32
entries before parsing (`clientip.py:45`, `:105-107`), an out-of-range index or an unparsable
entry falls back to the peer rather than to a neighbouring value, and `_parse_ip` strips
proxy-appended ports in both `203.0.113.7:443` and `[2001:db8::1]:443` forms and unwraps
IPv4-mapped IPv6 so one client yields one limiter key (`clientip.py:73-94`). Typos in the CIDR
list fail the boot, not the first rate-limit decision (`settings.py:486-499`).

The address this produces is used in three places that matter: the strict login counter's key
(`ratelimit.py:309-314`, `:439-448`), `admin_audit_log.ip` on every audited action
(`auth.py:452-521`, `audit_sink.py:88`), and `admin_sessions.last_ip` on every authenticated
request (`deps.py:329-347`).

### What the deployment must do

Two settings, and they must agree with the real topology. **The topology used to be unknown from
this repository. For `abdu-test` it is now known, and the correct values follow from it** — but
read the warning after them, because knowing the right value is not the same as knowing what the
file holds.

> **ANSWERED 2026-09-10: the panel is TWO PROXIES DEEP.** `00-host-inventory.md` row 17 was filled
> in on 2026-09-10 and row 23 carries the reasoning. `[HOST 2026-09-11]` TLS terminates at
> **Cloudflare's edge**; a Cloudflare Tunnel speaks **plain HTTP** to `127.0.0.1:80`; **Caddy**
> v2.11.4 demultiplexes by `Host` to `127.0.0.1:8080` (panel) and `127.0.0.1:8091` (gateway). One
> response proves the chain on its own: `server: cloudflare` and `via: 1.1 Caddy` on the same
> reply. So:

```ini
# In the admin process's dotenv file. For abdu-test as it is configured on 2026-09-10:
# Cloudflare edge -> tunnel -> Caddy (loopback) -> uvicorn.  Derive, do not copy, on another host.
BAYRAM_ADMIN_TRUSTED_PROXY_HOPS=2                       # ge=0, le=4 — settings.py:216
BAYRAM_ADMIN_TRUSTED_PROXY_CIDRS=127.0.0.1/32           # the PEER — always loopback here
```

`/etc/caddy/Caddyfile:69-70` states exactly those two values in a comment, adds "The CIDR is the
PEER — always loopback", and warns of the thing no code can catch: **switching the DNS record to
grey cloud makes the count 1, with nothing anywhere reporting the mismatch.** (That comment names
the file as `/etc/hbd/admin.env` while the unit actually loads `/etc/hbd/hbd-admin.env` — a stale
path in a comment, not a second file.)

`hops` is the number of proxies **you control**, counted from the application outward. No proxy
at all is `hops=0` — the shipped default, and the right value for a panel reached directly. One
nginx or Caddy on the same box terminating TLS is `hops=1`. Cloudflare in front of that nginx is
`hops=2`. The CIDR list is not the clients' addresses — it is the addresses the proxies themselves
appear as to the uvicorn socket. With the panel bound to `127.0.0.1` and the proxy on the same
host, that is `127.0.0.1/32`; a proxy on another machine is that machine's address on whichever
interface it connects from, and a managed edge is whatever ranges its operator publishes. Read the
value off the host (`ss -ltnp`, and the peer address in the admin process's own request log)
rather than assuming loopback.

And the proxy must **set** `X-Forwarded-For` from the connection it observed rather than
forwarding whatever the client sent. This is where real hosts get bitten: nginx with a bare
`proxy_pass` and no `proxy_set_header X-Forwarded-For` passes the client's own header through
verbatim, and `hops=1` then believes its rightmost entry — which the attacker wrote.

nginx, either of these two forms is correct:

```nginx
location / {
    proxy_pass http://127.0.0.1:8080;
    proxy_set_header Host              $host;
    proxy_set_header X-Forwarded-For   $proxy_add_x_forwarded_for;  # appends the peer it saw
    proxy_set_header X-Forwarded-Proto $scheme;
    # Origin is passed through unmodified by default — do not add a proxy_set_header for it.
}
```

`$proxy_add_x_forwarded_for` appends the observed peer to any incoming header; a plain
`$remote_addr` replaces it. With `hops=1` both are safe, because the rightmost entry is the one
nginx observed either way. What is **not** safe is leaving the header untouched, or setting it
from `$http_x_forwarded_for`.

Caddy appends the observed peer by default:

```caddyfile
panel.example.com {
    reverse_proxy 127.0.0.1:8080
    header Strict-Transport-Security "max-age=31536000; includeSubDomains"
}
```

> **Set `hops` to the number of proxies you control, not to a number that "works".** Too high
> and the index steps left past your own proxies into entries an attacker appended — the
> limiter then counts against a forged identity and the audit log records one. Too low and it
> believes an inner proxy, so every request in the fleet shares one bucket again. No code can
> check this number against reality; `resolve_client_ip` does exactly what it is told.

### How to verify it is actually on

Signed in as any role — `CONFIG_READ` is granted to VIEWER upward
(`permissions.py:240`) — `GET /api/config` reports both values verbatim:

```bash
curl -s https://<panel host>/api/config \
  -H 'Cookie: __Host-bayram_session=<your session cookie>' \
  | python3 -m json.tool | grep -i 'trustedProxy'
```

They are published deliberately: "wrong values here silently change which address every rate
limit is keyed on, so they are exactly what an operator needs to see"
(`config_view.py:127-129`).

> **VERDICT: `[UNPROVEN]`, AND UNPROVABLE WITHOUT A PASSWORD OR A SESSION — exactly as this
> section warns.** This is the one row in the degradation table with no signal at any level, and
> the host bears that out rather than rescuing it. `[HOST 2026-09-11]`
> `/etc/hbd/hbd-admin.env` is unreadable to the deploy account (`/etc/hbd` →
> `Permission denied`, `sudo -n` refused). `curl http://127.0.0.1:8080/api/config` answers **401**
> `{"error":{"code":"UNAUTHENTICATED","message":"sign in to continue",…}}`. The boot line carries
> no proxy settings by design. No log line in the tree reports them. So the correct value is
> derivable, and **whether the live configuration holds it is not established.**
>
> There is one piece of corroborating shape, and it points the worrying way. `[HOST 2026-09-11]`
> The gateway beside the panel journals `"peer_ip": "127.0.0.1"` on **62 of 62** RPCs — including
> one request genuinely made from the public internet. The application layer is demonstrably
> seeing the proxy rather than the caller. If the panel's `hops` is still the shipped `0`, then on
> this host `admin_audit_log.ip` is a **constant** and the strict login counter is one global
> bucket per username: the account-lockout primitive described under "How it fails".
>
> **The cheapest way to settle it is for somebody with an operator session to read
> `adminTrustedProxyHops` off `/api/config` and write the answer into `00-host-inventory.md` row
> 23.** Two minutes, and it closes the highest-damage unknown on this page.

The behavioural check is stronger, and it is the only one that catches a proxy that forwards a
client-supplied header. Sign in successfully from two different networks, then read back the
two audit rows on the Audit screen (or `GET /api/audit`) and confirm the `ip` column shows two
different addresses rather than the proxy's, twice. Then, from one of them, retry with a forged
header and confirm the row does **not** record the forged value:

```bash
curl -si https://<panel host>/api/auth/login \
  -H 'Origin: https://<panel host>' -H 'Content-Type: application/json' \
  -H 'X-Forwarded-For: 203.0.113.99' \
  -d '{"username":"<a name that does not exist>","password":"x"}'
# Then read the login.failure row: ip must be your real address, never 203.0.113.99.
```

### How it fails

Silently, and in the direction that hurts most during an incident.

With the shipped defaults — `hops=0`, empty CIDRs (`settings.py:216-217`,
`.env.admin.example:113-114`) — every request behind a proxy resolves to the proxy's own
address. The strict login counter is keyed `(username, client_ip)` at 10 attempts per 900
seconds (`ratelimit.py:116-117`, `_user_ip_key` at `:309-314`), so with one constant address it
becomes **a single global bucket per username**. That is precisely the shape the module's own
docstring was written to avoid: it "hands anyone who knows an operator's username a permanent
429 against that account, at exactly the moment during an incident when the operator needs to
log in" (`ratelimit.py:9-13`). The strict counter inverts into the account-lockout primitive.

Nothing reports this. There is no validator that can compare `hops` against a topology, and the
boot line at `app.py:322-333` prints `environment`, `env_file`, `is_cookie_secure` and
`public_origin` — but **not** the proxy settings. The same collapse writes the proxy's address
into `admin_audit_log.ip` for every row, so the audit log's only network evidence becomes a
constant, and into `admin_sessions.last_ip`.

---

## 6. The audit HMAC chain, and the role REVOKE beneath it

### What it protects

Two independent layers over the same table, and they answer different attackers.

**The HMAC chain** makes an edit detectable. Each row's `chain_hmac` is:

```
HMAC-SHA256(admin_audit_hmac_key, "v1" ‖ "\n" ‖ prev_hmac ‖ "\n" ‖ canonical_json(row))
```

(`src/bayram/db/admin/audit.py:11-15`, computed at `:396`.) The key lives in the admin process's
environment and never in the database, so an adversary who can write the table cannot recompute
the chain over their edit. `append` is the only function in the codebase that constructs an
`AdminAuditRow`, and `tests/test_db/test_audit_chain.py` asserts that exclusivity by scanning
the source (`audit.py:3-9`). The verifier detects three distinct attacks — a mutated row, a
prefix excision and a tail excision (`audit.py:593-600`).

**The REVOKE** makes a write impossible in the first place, which is the only part that
survives a compromised application credential. It requires two Postgres roles: `hbd` owns the
tables and runs migrations, `hbd_app` is what the three processes connect as. Without the split
the app role owns the table and can `GRANT` back anything revoked from it, so a one-role
deployment has no privilege-based protection at all (`docker/initdb/10-two-roles.sql:1-33`).
The revoke itself, plus two narrowly-scoped `SECURITY DEFINER` sweeps that take a row limit and
**no cutoff** — so `EXECUTE` on them is the right to delete what is already legally due, never
the right to delete what the caller names:

```python
# migrations/versions/20260830_1000_0007_add_admin_audit_log.py:369-378
op.execute(f'REVOKE UPDATE, DELETE, TRUNCATE ON TABLE public.{_AUDIT} FROM "{role}"')
for body, signature in ((_CREATE_PURGE_FUNCTION, _PURGE_SIGNATURE),
                        (_CREATE_REASON_PURGE_FUNCTION, _REASON_PURGE_SIGNATURE)):
    op.execute(body)
    op.execute(f"REVOKE ALL ON FUNCTION public.{signature} FROM PUBLIC")
    op.execute(f'GRANT EXECUTE ON FUNCTION public.{signature} TO "{role}"')
```

### What the deployment must do

**Create the two roles by hand.** Nothing in the repository creates production roles.
`docker/initdb/10-two-roles.sql` runs only on an empty local Docker volume, ships a hardcoded
development password, and says so itself at `:25-33`. The `ALTER DEFAULT PRIVILEGES FOR ROLE
hbd IN SCHEMA public GRANT SELECT,INSERT,UPDATE,DELETE ON TABLES TO hbd_app` clause
(`:46-49`) is part of that manual step — without it, every table a future migration creates is
invisible to the application role.

> **`[UNPROVEN]` on `abdu-test`, and there is a tempting wrong proof that must not be written
> down.** Over TCP, Postgres answers `FATAL: password authentication failed for user "…"` for a
> wrong password **and for a role that does not exist, identically** — `[HOST 2026-09-11]` verified
> by probing a deliberately invented role name and getting the same refusal as `hbd_app`. (A
> local-socket attempt as the login user does answer `role "developer" does not exist`, but that
> distinction does not carry over to the TCP password path, which is the only one reachable here.)
> **That refutes the TCP proof, and it is not the end of the question.** `00-host-inventory.md`
> row 12 answers it from a different artefact: `log_line_prefix` (`postgresql.conf:570`) is
> `'%m [%p] %q%u@%d '`, so every attributed line in the Postgres server log carries role and
> database — and **the `DETAIL` line discriminates where the `FATAL` line does not.** A missing
> role's `DETAIL` reads `Role "…" does not exist.`; an existing role's carries only the
> `pg_hba.conf` line. The log is `adm`-readable and `developer` is in `adm`. **Both roles exist**
> `[HOST 2026-09-11]`, and `hbd_app` additionally owns all 29 tables in the world-readable
> pre-cutover dump (row 14).
>
> **Keep the wrong proof written down anyway** — it is the one somebody will reach for, it was
> reached for here, and the control that killed it (probing a deliberately invented role name and
> getting a byte-identical refusal) is the only thing that settles it. What changed is the
> conclusion, not the warning. Do **not** spend a sudo password on `/opt/hbd/diagnose.sh` for the
> ownership half; it answers live `has_schema_privilege`, which is genuinely unreachable, and that
> is the only reason to run it.

**Point the admin process at the application role.** `resolve_chain_protection` asks Postgres
about `current_user` — whoever `AdminSettings.database_url` connects as (`container.py:121`) —
and no validator anywhere refuses an owner DSN there. Note that `.env.admin.example:48` ships
the **owner** DSN (`postgresql+asyncpg://hbd:hbd@…`), contradicting the repo's own design at
`README.md:160-161` and `.env.example:35`. An admin process on the owner role defeats the
append-only property from inside the panel and reports `hmac-only` while doing it.

**Export the variables migration 0007 reads into the shell that runs alembic.** This is the sharp
edge. It reads them from `os.environ` only — never from a dotenv file:

```python
# migrations/versions/20260830_1000_0007_add_admin_audit_log.py:336-342
if not os.environ.get(_AUDIT_DSN_ENV, "").strip():
    _skip(f"{_AUDIT_DSN_ENV} is not set, so no separate owner role exists")
    return
role = _app_role()          # BAYRAM_DB_APP_ROLE, else the username in BAYRAM_DATABASE_URL — :314-322
if role is None:
    _skip(f"neither {_APP_ROLE_ENV} nor a username in {_APP_DSN_ENV} names the app role")
    return
```

`BAYRAM_ADMIN_AUDIT_DSN` is documented as living in `.env.admin` (`.env.admin.example:130`), and
the migration runner never loads that file — `migrations/env.py` reads only `bayram.config.env_file()`
and `load_settings()` (`env.py:95-129`). `BAYRAM_DB_APP_ROLE` appears in **neither** example file,
so an operator has no way to discover it exists. The proposed invocation at
`deploy/first-install-proposal.md:112` exports only `BAYRAM_ENV_FILE`. Following it verbatim, `_install_two_role_controls`
takes its first `_skip` branch and the REVOKE is never applied — and even with the DSN
exported, `_app_role()` returns `None` because `BAYRAM_DATABASE_URL` is only in the file too.

**Set `BAYRAM_DB_MIGRATION_URL` to the owner DSN — this is the variable that actually decides it,
and exporting the two above without it changes nothing.** `BAYRAM_ADMIN_AUDIT_DSN` is only a *flag*:
0007 tests that it is non-empty and never connects with it (`0007:336`). The role alembic
connects **as** is chosen by `migrations/env.py:_database_url` (`env.py:117-129`), which prefers
`BAYRAM_DB_MIGRATION_URL` (`env.py:85`, `_owner_url` at `:107-114`) and otherwise falls back to
`BAYRAM_DATABASE_URL` — the application role. Connect as the application role and 0007 reaches its
fourth skip branch:

```python
# migrations/versions/20260830_1000_0007_add_admin_audit_log.py:354-356
if connection.execute(sa.text("SELECT current_user")).scalar() == role:
    _skip("migrations run as the application role, so a REVOKE from it is reversible by it")
    return
```

— and the REVOKE is still never applied. Unlike the other two, this variable *does* fall back to
the dotenv file `BAYRAM_ENV_FILE` names (`env.py:107-114`), so it can live in the bot env file; the
README documents it as one of the two switches for the whole two-role split
(`README.md:172-173`, `docker/initdb/10-two-roles.sql:17`).

All together, whatever your runner:

```bash
cd <checkout>
BAYRAM_ENV_FILE=<bot env file> \
BAYRAM_DB_MIGRATION_URL='postgresql+asyncpg://hbd:<owner password>@localhost:5432/hbd' \
BAYRAM_ADMIN_AUDIT_DSN='postgresql://hbd:<owner password>@localhost:5432/hbd' \
BAYRAM_DB_APP_ROLE=hbd_app \
  .venv/bin/python -m alembic -c migrations/alembic.ini upgrade head
```

`BAYRAM_DB_MIGRATION_URL` may be dropped from that line if it is already in the file `BAYRAM_ENV_FILE`
names; `BAYRAM_ADMIN_AUDIT_DSN` and `BAYRAM_DB_APP_ROLE` may not, because 0007 reads only `os.environ`
for those two.

> **ON `abdu-test` THAT EXPORT LINE IS NOT WHAT RAN, AND THE THING THAT DID RUN WILL RUN AGAIN.**
> `[HOST 2026-09-11]` The schema was dropped and rebuilt at ~09:25 on 2026-09-10 by
> `/opt/hbd/release/wipe-and-rebuild.sh`. Its migration step is:
>
> ```bash
> # step 4, the fallback that actually executed (hbd-migrate was tried first and failed)
> ( cd /opt/hbd && HBD_ENV_FILE="$BOT_ENV" \
>     /opt/hbd/venv/bin/python -m alembic -c /opt/hbd/migrations/alembic.ini upgrade head )
> ```
>
> `grep -c 'HBD_ADMIN_AUDIT_DSN\|HBD_DB_APP_ROLE\|HBD_DB_MIGRATION_URL'` on that script returns
> **0**. So on a schema created from scratch that morning, 0007 took its **first** `_skip` branch
> and the REVOKE, `hbd_purge_audit_log` and `hbd_purge_audit_reasons` were all never created. The
> step before it had already run `GRANT ALL ON SCHEMA public TO ${APP_ROLE}` (and to `postgres`), so
> the application role is also an owner of everything.
>
> **The fix belongs in that script, beside the `pg_dump` it already takes** — not in a runbook
> somebody is expected to remember, because this reproduces on every wipe. And it has an **ordering
> constraint no document stated until now**: create the two `SECURITY DEFINER` functions **first**,
> then REVOKE. `06-troubleshooting.md` §3 FIX (b) has the table of the four REVOKE×functions
> combinations and which one breaks the hourly sweep.
>
> `[UNPROVEN]` `/usr/local/bin/hbd-migrate` is root-only (820 bytes) and unreadable with the access
> available, so whether *it* exports those variables is unknown. The outcome settles the practical
> question either way. `[HOST 2026-09-11]` Separately: **alembic cannot currently run on this host
> at all** — `/opt/hbd/migrations/env.py:57` imports `bayram` and the venv holds only `hbd`, so the
> command above dies with `ModuleNotFoundError`. Check with
> `/opt/hbd/venv/bin/python -c 'import bayram'` before planning any of this;
> `06-troubleshooting.md` §11 has the detail.

Note that `migrations/env.py:14-19` records this exact defect being fixed for
`BAYRAM_DB_MIGRATION_URL` — the environment-only read "would have migrated production as the wrong
role" — and the fallback was added there and not to the two migration bodies that need the same
thing.

**Back up `BAYRAM_ADMIN_AUDIT_HMAC_KEY` separately from the database.** It is a `SecretStr` with
`min_length=32`, required from the first boot (`settings.py:229`), and it lives only in the
admin dotenv file. A backup containing both the table and the key is a backup an insider can
rewrite; a database-only restore comes back with a log nobody can verify.

### How to verify it is actually on

The system reports this honestly rather than assuming it worked. The badge is derived by asking
Postgres, not by reading configuration:

```sql
-- src/bayram/db/admin/audit.py:779-805, run as the admin process's own role
SELECT has_table_privilege(current_user, 'admin_audit_log', 'UPDATE')
    OR has_table_privilege(current_user, 'admin_audit_log', 'DELETE')
    OR has_table_privilege(current_user, 'admin_audit_log', 'TRUNCATE') AS is_writable;
-- false is what you want.
```

Through the panel, signed in as ADMIN or OWNER (`AUDIT_READ` is granted to those two only —
`permissions.py:374`):

```bash
curl -s https://<panel host>/api/audit/verify \
  -H 'Cookie: __Host-bayram_session=<your session cookie>' | python3 -m json.tool
```

Read **three** fields, not one:

- `chainProtection` — `revoke+hmac` means the privileges really are gone. `hmac-only` is
  reported whenever the DSN is unset, the backend is not Postgres, the probe errored, *or* the
  probe says the role is still writable (`audit.py:789-805`).
- `ok` — no row's MAC failed to recompute.
- `isComplete` — a pass walks at most 50 000 rows in batches of 500 (`audit.py:129`, `:132`,
  `:646-656`). On a mature deployment `ok: true` with `isComplete: false` is **not** a verified
  log; it is a verified prefix.

And at migration time, the alembic output itself:

```
admin_audit_log REVOKE skipped: <reason>. The chain is HMAC-only on this deployment
and /audit/verify will report chainProtection=hmac-only.
```

(`migration 0007:325-331`.) That WARNING is the cheapest signal you will get, and it appears
exactly once, in the terminal of whoever ran the migration — which on a scripted deploy means
nowhere a human will ever read it.

> **THERE IS A FOURTH ROUTE, IT IS THE CHEAPEST OF ALL, AND IT IS THE ONLY ONE REACHABLE ON
> `abdu-test`.** The panel logs a WARNING whenever it resolves the badge:
>
> ```bash
> ssh aizu 'journalctl -u hbd-admin -o cat | grep admin.audit.revoke_missing'   # no sudo needed
> ```
>
> **VERDICT: THE HMAC HALF IS ON; THE REVOKE HALF IS PROVABLY OFF.**
>
> `[HOST 2026-09-10]` Two `admin.audit.revoke_missing` WARNINGs (logger `hbd.db.admin.audit`), at
> 09:29:50 and 12:36:59 +05: *"the audit REVOKE is configured but not in force; the app role can
> still write"*. `resolve_chain_protection` reaches that branch **only** when
> `HBD_ADMIN_AUDIT_DSN` **is** set **and** the privilege probe says the role can still write — so
> both halves of the diagnosis come free: somebody declared the split, and it did not land. Zero
> `admin.audit.privilege_probe_failed`.
>
> `[HOST 2026-09-11]` The HMAC half is working: the HEAD anchor is re-pinned hourly at `:17` with
> the retention sweep (`{"event":"admin.audit.anchor","kind":"head","seq":16,"hash":"6317f7d7…"}`),
> and **`admin.audit.chain_broken` has never been logged at all.**
>
> **Two things not to overclaim.** Nobody has read `chainProtection` directly — that needs an
> ADMIN or OWNER session — so the defensible sentence is *"the panel logged the WARNING that
> accompanies `hmac-only`"*, not *"the panel reported `hmac-only`"*. And the WARNING fires only
> when somebody **calls** `/api/audit/verify`: two hits in the whole journal means the endpoint has
> been read twice, ever. **Absence of this line is evidence nobody looked.** On a host whose logs
> go to the journal and nowhere else (see the closing section), that is the default state — and it
> is how a security control reporting its own absence sat unread for a day.

### How it fails

**The REVOKE skips itself with a warning, not an error.** `_skip` logs; `upgrade()` continues
(`0007:334-343`, `:387-391`). The migration succeeds, the schema is correct, and the control is
absent. There are **four** skip branches, and only the first two are about variables you forgot
to export: `BAYRAM_ADMIN_AUDIT_DSN` unset (`0007:336-338`), no app role named (`:339-342`), the named
role absent from `pg_roles` (`:349-353` — a typo in `BAYRAM_DB_APP_ROLE`, or roles that were never
created by hand), and `current_user` *being* the app role (`:354-356` — `BAYRAM_DB_MIGRATION_URL`
unset, so alembic connected as the application role). The last two are the ones that survive a
correct-looking export line, and all four produce the same one-line WARNING.

**A key rotation is indistinguishable from tampering.** The MAC input carries a
`CHAIN_VERSION` constant (`audit.py:111`) but no key identifier, and `AdminAuditRow` has no
key-id column (`src/bayram/db/models/admin_audit.py`). Change the key and `/audit/verify` reports
a break at the first row forever; lose it and the log is permanently unverifiable. There is no
rotation path in the code — treat the key as a write-once deployment secret.

**The tail-protection window is one hour wide, and only the worker refreshes it.**
`/audit/verify` writes nothing, including no fresh anchor (`routers/audit.py:1-7`). HEAD and
TRUNCATION anchors are pinned by the retention sweep (`src/bayram/db/purge.py:362-365`,
`purge_admin.py:198`), which is an ARQ cron at :17 past the hour
(`retention_job.py:73`, `jobs.py:821-829`). `[HOST 2026-09-11]` On `abdu-test` that cadence is
confirmed hourly and the anchor is the only history of pins, since only the newest row is kept. If the worker is down, rows written since the
last pin can be excised without the verifier noticing, while the panel keeps reporting
`ok: true`.

**An audit write can fail without failing the request.** `_append` catches
`AuditValueRejectedError` and retries once with the actor blanked (`audit_sink.py:115-135`);
`record_refusal` swallows any exception with `_LOGGER.exception` (`:99-113`). That is correct
for availability — the trade is stated at `audit_sink.py:22-29` — and it means an audit outage
is invisible to the client and visible only as `admin.audit.value_refused` or
`admin.audit.write_failed` in the log.

---

## 7. Loopback binding, and what has to be in front of it

### What it protects

The panel has no MFA. Binding to loopback behind a reverse proxy **is** the compensating
control (`clientip.py:3-5`, citing ADMIN_PANEL_PLAN §12.1 T13).

> **REVISED 2026-09-10: THAT SENTENCE WAS WRITTEN FOR A PANEL REACHED OVER AN SSH TUNNEL. IT IS
> NOW A PANEL ON THE PUBLIC INTERNET.** Both halves of this need saying, in this order, because
> the first is still true and the second is what changed.
>
> **Loopback binding is intact, and it still matters.** `[HOST 2026-09-11]` `ss -ltn` shows the
> panel on `127.0.0.1:8080` and the gateway on `127.0.0.1:8091` — **neither is on a public
> interface.** The only publicly-bound sockets on the box are `0.0.0.0:22` + `[::]:22` (sshd) and
> `*:80` + `*:443` (Caddy). That is exactly the posture this section asks for.
>
> **But it is no longer the whole compensating control.** `[HOST 2026-09-11]`
> `https://admin.bayrambot.uz/` answers **HTTP/2 200 from anywhere on the internet**
> (`server: cloudflare`, `via: 1.1 Caddy`), through a Cloudflare Tunnel. There is **no MFA** and
> **no IP allowlist**: the `@operators remote_ip` block in `/etc/caddy/Caddyfile` is present but
> **commented out** at lines 52-53, deliberately, with its reason recorded above it. The
> `hbd-admin.service` comment still says "Reach it over an SSH tunnel", and that is no longer how
> anybody reaches it.
>
> **So name what is actually carrying the weight now**, because "it is bound to loopback" is a
> true sentence that no longer answers the question "who can try to sign in":
>
> 1. **Cloudflare's edge** — whatever is configured there, in a dashboard nothing on the host can
>    read (`08-payme.md` §4.6). This is the largest single dependency and the least inspectable.
> 2. **The argon2 parameters**, which the 8-character password floor explicitly leans on
>    (`05-operations.md`, *The password rules*). Not a latency knob.
> 3. **The strict `(username, client_ip)` login counter**, 10 per 900 s — **and its value depends
>    on §5, which is `[UNPROVEN]` on this host.** If `hops` is still `0`, every request resolves to
>    Caddy's address, the counter collapses to one global bucket per username, and the control
>    inverts into an account-lockout primitive. `[HOST 2026-09-11]` Zero `admin.ratelimit.*` events
>    have ever been logged, so there is no evidence either way from the log.
> 4. **The exact origin check** (§4), which is provably on.
>
> Item 3 is the uncomfortable one: the third pillar of a no-MFA panel's defence rests on a setting
> nobody has read. **Re-enabling the `@operators` allowlist, or putting Cloudflare Access in front
> of the hostname, would restore the margin the SSH tunnel used to provide.**

### What the deployment must do

Pass the bind address on the command line, because that is the only thing that decides it:

```bash
<venv>/bin/python -m uvicorn bayram.admin.app:app --host 127.0.0.1 --port 8080
```

That string is Makefile:75, and the same string appears at `deploy/systemd/bayram-admin.service:30`
— a **proposal**, not a record of any host.

> **`BAYRAM_ADMIN_HOST` and `BAYRAM_ADMIN_PORT` bind nothing.** They are declared at
> `src/bayram/admin/settings.py:188-189`, and a grep across `src/` finds exactly two other
> readers: `config_view.py:108-109` and `:202-203`, which project them onto `GET /api/config`.
> `app: Final[FastAPI] = create_app()` (`app.py:440`) is an ASGI object; it cannot know or
> refuse the address it is served on. So if the process is started with `--host 0.0.0.0`, the
> panel is on the internet, the settings model cannot detect it, and `/api/config` still
> renders `adminHost: 127.0.0.1` to the operator checking. Changing `BAYRAM_ADMIN_PORT` in the
> env file changes what the panel *displays* and not what it binds.

### How to verify it is actually on

From the host itself, not from the panel:

```bash
ss -ltnp | grep 8080         # must show 127.0.0.1:8080, never 0.0.0.0:8080 or :::8080
ps -eo args | grep '[u]vicorn bayram.admin.app'   # read the actual --host flag in the command line
```

> **VERDICT: PROVABLY ON AT THE SOCKET.** `[HOST 2026-09-11]` `ss -ltn` in full — loopback only:
> `127.0.0.1:5432` (Postgres), `127.0.0.1:6379` + `[::1]:6379` (Redis), `127.0.0.1:2019` (Caddy's
> admin API), `127.0.0.1:8080` (the panel), `127.0.0.1:8091` (the Payme gateway),
> `127.0.0.1:20241`, `127.0.0.1:8765` (an unrelated tenant's app), `127.0.0.53%lo:53` /
> `127.0.0.54:53`. Public: `0.0.0.0:22` + `[::]:22` and `*:80` + `*:443`. **Neither the panel nor
> the gateway is on a public interface.**
>
> **One caveat about the command as written.** Without root, `ss -ltnp`'s Process column is
> **empty** for every row — and `sudo -n ss -ltnp` is refused on this host. So the port→unit
> mapping above comes from the units' own `ExecStart` lines (`systemctl cat`), not from `ss`. The
> `ps -eo args` form is the other route, and on a host whose process table you can read it is the
> better one, because it shows the `--host` flag that actually decided the bind.

And from anywhere else on the internet, the negative test:

```bash
curl -sS --max-time 5 http://<the VPS public IP>:8080/healthz
# Must fail to connect. A 200 here means the panel is bound to a public interface.
```

`/healthz` is the right probe for that test precisely because it answers unconditionally:
`Response(status_code=200)`, empty body, no database, no Redis (`routers/health.py:121-124`).

### How it fails

Completely, and with no signal from the application. There is no log line, no boot refusal, and
`/api/config` actively reports the wrong thing.

Two related notes on probes:

`/readyz` returns the constant `{"status": "ok"}` to every unauthenticated caller — even when
the database and Redis are both down, and it pings neither (`health.py:126-131`, `PUBLIC_STATUS`
at `:53-56`). Detail requires `X-Probe-Token` matching `BAYRAM_ADMIN_PROBE_TOKEN` under
`secrets.compare_digest`, or a live operator session (`health.py:93-114`). Any monitor pointed
at `/readyz` **without** the token will never remove a broken instance. The default is empty,
so there is no default token to forget to change (`settings.py:426-428`) — but there is also no
monitoring path at all until one is set, and the field has no `min_length`, unlike
`admin_audit_hmac_key`'s 32. A one-character token passes every check.

`/healthz` takes no container, so it answers 200 even when the lifespan never ran. Every
lifespan-less request to an API route raises `RuntimeError("admin container is not on
app.state; the lifespan did not run")` from `get_container` (`deps.py:126-133`) — the design
fails closed, but by accident of dependency wiring rather than by an explicit check, and a
naive liveness probe would call that process healthy.

---

## 8. The Payme gateway: a third blast radius, and the one process with an inbound public socket

**Until 2026-09-10 a `grep -in payme` across this whole document returned nothing.** An operator
who read §§1–7 came away believing this system has three processes and that the admin panel is the
most exposed of them. **Neither is true.** There is a fourth process, `hbd-payme`; it is the only
one in the system with an inbound socket reachable from the public internet **without a login**; it
holds the Payme cashbox key; and on 2026-09-10 it took a real settlement. That it had no section
here is the largest gap this revision closes.

Its own page is [`08-payme.md`](08-payme.md) and it is thorough — §1 for what the process is, §2
for the unit and the secret, §4 for the public path, §10 for symptoms. **This section is only the
security argument and the verdict**, and it does not restate that page.

### What it protects

**A third kind of secret, and the reason for a third container.** The bot and worker hold four
**outbound** credentials whose theft lets somebody impersonate us or spend our balance. The panel
deliberately holds none. This process holds exactly one, `BAYRAM_PAYME_MERCHANT_KEY`, and it is an
**inbound verification** secret: it is only ever compared against itself under
`hmac.compare_digest`, to decide whether a request really came from Payme. **Its theft mints
credits** — the thief forges settlements at our own gateway rather than spending our money
elsewhere. Three blast radii, three containers. §1's sixth forbidden name is the mechanism that
keeps it out of the panel, and `FOREIGN_SECRET_ENV_VARS` keeps it out of the bot.

Two consequences are enforced rather than documented: **this process holds no Telegram token**, so
telling a customer their payment landed is an ARQ job the worker performs; and **the panel and the
bot refuse to boot in prod with the key in reach**.

### What the deployment must do

`BAYRAM_ENVIRONMENT` must be **exactly `prod`** on this process, for the same reason it must be on
the panel — and for a sharper one, because here the default works against you.

### How to verify it is actually on

```bash
ssh aizu 'journalctl -u hbd-payme -o cat | grep payme.boot.ok | tail -1'
```

Read `environment`. Everything else on that line is useful context; this field is the control.

> **VERDICT: THE GATEWAY RUNS `environment: dev` ON THE PRODUCTION HOST, WHICH DISARMS BOTH OF ITS
> OWN BOOT REFUSALS. This is a live, silent control failure on the money path.**
>
> `[HOST 2026-09-11]` Every `payme.boot.ok` on this host — including today's, at `06:50:15 +05` —
> reads:
>
> ```json
> {"event":"payme.boot.ok","environment":"dev","env_file":"/etc/hbd/payme.env",
>  "merchant_id":"6aa24fd9ee30563de3a1ac22","is_sandbox":true,"account_field":"order_id",
>  "basic_login":"Paycom","duplicate_transaction_code":-31008,"merchant_key_length":36}
> ```
>
> In the tree: `PaymeSettings.environment` **defaults to `"dev"`** (`payme/settings.py:162`),
> `is_production` is `self.environment == "prod"` (`:348-349`), and both refusals are gated on it:
>
> * `_refuse_foreign_credentials` — `if settings.is_production:` (`payme/app.py:219`, the function
>   at `:203`, called from the lifespan at `:633`). **So a Telegram token or a vendor key in
>   `/etc/hbd/payme.env` would boot here without a word.**
> * the DEBUG refusal — `if self.is_production and (self.is_debug or self.log_level ==
>   _DEBUG_LEVEL)` (`payme/settings.py:338`). **So `HBD_IS_DEBUG=true` would be accepted here.**
>   That half is a privacy failure as much as a security one: at DEBUG the ORM echoes bound
>   parameters, and this process's include idempotency keys carrying **Telegram user ids**, into a
>   stream with no retention clock that neither `bayram.db.purge` nor a per-user erasure can reach.
>
> **`hbd-payme.service`'s own comment block asserts that both of these are prevented.** It is
> wrong on this host, and that is the worst property of this finding: the one place the reasoning
> is written down says the opposite of what is true, so a reviewer who reads the unit file comes
> away reassured.
>
> **`is_sandbox: true` does not compensate and must not be read as a mode.** `payme_is_sandbox` is
> documented in the settings model as "a label, not a switch" (`payme/settings.py:236-242`): it
> changes no behaviour whatsoever. The boot line reports a sandbox *label* and a `dev`
> *environment* in front of a cashbox that has moved real money.
>
> **Fix, in this order.** Read `/etc/hbd/payme.env` and confirm it holds no foreign credential;
> **then** set its `HBD_ENVIRONMENT=prod` and restart. The order matters because with the refusal
> armed, a credential that is present turns a silent boot into a boot *failure*, and you do not
> want to discover that during a payment incident. `[UNPROVEN]` Nobody can do the first step with
> the access available — `/etc/hbd` is `Permission denied` and `sudo -n` is refused — so this needs
> somebody with a sudo password and two minutes.

### How it fails

**Silently, and the logs cannot tell you who is calling.** `[HOST 2026-09-11]` All **62**
`payme.rpc` rows in the journal carry `"peer_ip": "127.0.0.1"`, including one request genuinely
sent from the public internet (a `GET https://pay.bayrambot.uz/payme` that reached the gateway and
was journalled with `reply_code -32300`). Caddy is the peer, and the gateway declares no
trusted-proxy hops — deliberately, and `08-payme.md` §4.5 argues why raising it would be wrong: the
value would be load-bearing for a filter that mints credits, and it is a header an attacker writes.

The consequence is worth stating plainly because a unit-file comment claims otherwise:
`hbd-payme.service` says *"Every request journals its peer IP regardless, so the real caller set is
discoverable from our own logs."* **On this host that is false.** The `185.234.113.0/28` caller
allowlist is therefore **neither enforced nor auditable from the box**, and
`payme.caller.refused` has never fired. The caller set lives in Cloudflare's event log, which
nothing on the host can read (§4.6).

`[HOST 2026-09-11]` `GET https://pay.bayrambot.uz/` returns **404** — Caddy's `handle { respond
404 }` — which confirms the one-path surface: `POST /payme` and the two probes, nothing else.

### What the host gets right here, and should not be "simplified"

`[HOST 2026-09-11]` This is the most hardened unit on the box, and two of its properties are
controls the rest of this document argues for in code:

* `InaccessiblePaths=/etc/hbd/hbd.env /etc/hbd/hbd-admin.env` — the credential separation of §1,
  enforced by the kernel, on the one process holding the cashbox key.
* `ProtectSystem=strict` with an **empty** `ReadWritePaths=`, plus `MemoryDenyWriteExecute=yes`,
  `RestrictNamespaces=yes` and `RestrictAddressFamilies=AF_INET AF_INET6 AF_UNIX`. The process has
  **no writable path at all**. (`hbd-admin` is the same minus the last three; only `hbd-bot` and
  `hbd-worker` get `ReadWritePaths=/var/lib/hbd /var/log/hbd`, which is the pair that needs it.)

Two smaller notes for anyone doing the connection arithmetic or following a link: `[HOST
2026-09-11]` the panel's real pool size is **5**, not the 10 the unit's comment arithmetic assumes
(`{"event":"admin.container.built","environment":"prod","pool_size":5}`), and
`hbd-payme.service` carries `Documentation=file:///srv/hbd/deploy/README.md` pointing at a path
that **does not exist on this machine**.

---

## Controls that degrade silently

These are the ones that report themselves as *not deployed* rather than failing. Each is a
supported configuration from the code's point of view, so nothing refuses to start — which
makes this exactly the set a reviewer has to check by hand on the host.

| Control | What it looks like when it is off | The only signal | Where to look |
|---|---|---|---|
| Client-IP derivation behind a proxy | Every rate limit and every audit row records the proxy's address; the strict login counter becomes one global bucket per username | **None.** Not in the boot line, not in any log | `GET /api/config` → `adminTrustedProxyHops`, `adminTrustedProxyCidrs` (`config_view.py:127-129`); then a two-network sign-in and read back `admin_audit_log.ip`. `[UNPROVEN]` on `abdu-test`: `/api/config` needs a session and the env file is unreadable — §5 |
| Audit REVOKE (two-role split) | The app credential can still `UPDATE`/`DELETE`/`TRUNCATE` the log; only the HMAC protects it | `chainProtection: "hmac-only"`, plus WARNING `admin.audit.revoke_missing` — and the latter **only when the DSN is set**, and **only when somebody calls `/api/audit/verify`** | `journalctl \| grep admin.audit.revoke_missing` (no credential needed, and the only route on a walled host); `GET /api/audit/verify`; `has_table_privilege` in psql; the alembic WARNING at migrate time (`0007:325-331`). `[HOST 2026-09-10]` **OFF on `abdu-test`** — §6 |
| CSP style nonce (stale bundle) | Panel looks fine; every runtime-injected `<style>` is blocked, so modal scroll-lock stops working | WARNING `admin.spa.nonce_placeholder_missing`, once per response | `shell.py:78-85`; rebuild with `make ui-build` |
| Vendor-credential scan, file half | Only the process environment was checked; the dotenv half found nothing and said nothing | **None** when the file is absent (`dotenv_values` returns `{}`, no `OSError`) | `admin.boot.ok` → `env_file`, compared against the file you believe is live (`app.py:329`) |
| Vendor-credential refusal on staging | A real vendor key sits on an operator-facing host | WARNING `admin.boot.vendor_env_present` (`app.py:200-203`) | Same grep; in prod this is a boot refusal instead |
| Origin check with a wrong value | The login page renders and the login `POST` 403s — nobody signs in at all (`auth.py:450`) | WARNING `admin.login.origin_refused`, per refusal (`auth.py:186-189`). **Not** `admin.csrf.refused`, which only the authenticated path emits (`deps.py:230-236`) | `admin.boot.ok` → `public_origin`; then try to sign in |
| **HSTS — REWRITTEN 2026-09-10** | Plain `http://` to the panel host is **served, not redirected**. The old row said "never upgraded", and the old signal column said "this repository emits no HSTS at all" — both now mislead, in opposite directions | HSTS **is** set, by the proxy (`max-age=86400`), so its presence is **not** evidence the risk is closed. The real signal is the response to a plain-`http://` request | `curl -sI http://<panel host>/` — a 200 with HTML is the failure. `[HOST 2026-09-11]` `abdu-test` returns exactly that |
| **The Payme gateway's `environment`** (§8) | `environment: dev` on a production host disarms **both** of the gateway's boot refusals: a foreign credential in its env file boots silently, and `IS_DEBUG=true` is accepted (ORM echoes idempotency keys carrying Telegram user ids) | **None.** Nothing warns, and `hbd-payme.service`'s own comment block asserts the opposite | `journalctl -u <gateway unit> \| grep payme.boot.ok` → `environment`. `[HOST 2026-09-11]` `abdu-test` reads `dev` |
| **The Payme caller allowlist** (§8) | Not enforced and not auditable: every `peer_ip` is the proxy | **None**, and worse than none — the unit file claims the caller set *is* discoverable from our logs | `journalctl -u <gateway unit> \| grep payme.rpc`. `[HOST 2026-09-11]` 62 of 62 rows are `127.0.0.1` |
| **Source maps at `/assets/*.map`** (§2) | The console's full TypeScript is downloadable, unauthenticated, cached immutable for a year | **None.** It is a 200 | `curl -s -o /dev/null -w '%{http_code} %{size_download}' <panel>/assets/*.js.map`. `[HOST 2026-09-11]` `200 4242767` from the public internet |
| `/readyz` without a probe token | Constant `{"status":"ok"}` to every monitor, database down or not | **None** — that is the point of the constant (`health.py:9-19`) | `GET /api/config` → `isProbeTokenConfigured` (`config_view.py:186-188`). `[UNPROVEN]` on `abdu-test`: that call needs a session and the env file is unreadable. Circumstantially, **nothing is polling on a schedule** — only a handful of `/readyz` requests all day, several of them made by hand |
| Loopback binding | The panel may be on a public interface; `/api/config` still reports `127.0.0.1` | **None** | `ss -ltnp` on the host (the Process column is empty without root — read the unit's `ExecStart` instead); the uvicorn `--host` flag in the actual command line. `[HOST 2026-09-11]` **ON** on `abdu-test` — but read §7 on why that is no longer the whole compensating control |
| Audit write path | Actions happen and are not recorded | ERROR `admin.audit.write_failed` / `admin.audit.value_refused`; the chain shows the gap as a break at the next `seq` | `audit_sink.py:99-135` |
| Session mirror invalidation | A revoked session may survive until its 60 s mirror expires | WARNING `admin.session.mirror_invalidation_failed` | `sessions.py:264` |
| `BAYRAM_ADMIN_CONFIG_ENABLED` | Protects nothing today — no endpoint reads it, and the runtime-config editor it names does not exist in this tree | **None.** It defaults to `true` and is published on `/api/config` as though it were armed | grep `admin_config_enabled`: the field (`settings.py:185`), its projection (`config_view.py:107`, `:201`), and prose in `routers/config.py:10` |

Two things about that list are worth saying out loud. The first is that every entry whose only
signal is a log line assumes somebody is reading the logs. The second is that the top row has no
signal of any kind, in any log, at any level. It is the one that has to be checked by hand.

> **ANSWERED 2026-09-10, AND IT IS THE ANSWER THAT MATTERS MOST ON THIS PAGE: THE LOGS GO TO THE
> JOURNAL AND NOWHERE ELSE.** The question used to read "whether the admin process's output is
> shipped anywhere at all is a host question this repository cannot answer."
>
> `[HOST 2026-09-11]` On `abdu-test`: **no log shipper.** **No `/etc/logrotate.d` entry for
> anything `hbd`** (the directory holds fourteen files, all for other software). `/var/log/hbd/`
> exists, is owned `hbd:hbd`, and is **empty** — nothing writes a file there despite
> `ReadWritePaths=/var/log/hbd` on the bot and worker. `/etc/systemd/journald.conf` sets no
> `SystemMaxUse`, no `MaxRetentionSec` and no `Storage`, so journald's compiled-in defaults decide
> retention, and `journalctl --disk-usage` reports **96.6 MB** (88.6 MB the day before — it grows).
>
> **So every row in that table whose only signal is a log line currently pages nobody.** The two
> ERROR-level events genuinely worth paging on — `admin.audit.chain_broken` and
> `admin.audit.write_failed` — have a destination of exactly zero people. And this is not a
> hypothetical: **the worked example is row 2 of this very table.** `admin.audit.revoke_missing`
> is a security control reporting its own absence, it fired twice on 2026-09-10, and it sat
> unread in this journal until somebody grepped for it. That is what "the only signal is a log
> line" costs when nothing reads the logs.
>
> Three things follow that are worth doing in roughly this order, and none of them is in this
> repository's power: **(1)** ship the journal somewhere, or at minimum alert on those two events;
> **(2)** cap journald explicitly rather than inheriting a default, since the retention that
> currently bounds your only evidence is accidental; **(3)** note that until (1) exists, the
> honest reading of any "no such line" check on this host is *"nobody has looked"*, not *"it is
> healthy"* — which is the distinction every `[UNPROVEN]` on this page is drawing.
