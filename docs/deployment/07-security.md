# Security controls and their deployment dependencies

Almost every control in the admin panel is a joint venture between this repository and a host
nobody in this document has ever seen. The code half is knowable: it is in the tree, it has
line numbers, and it is cited below. The host half — what binds the socket, what terminates
TLS, what the dotenv files on the box actually say — is not. Where a control needs both
halves, this document says so plainly rather than assuming the second one landed.

Each section is the same four questions: what the control protects, what the deployment has to
do for it to exist, how to prove it is actually on, and what it looks like when it is not.

> **The production host is out of reach from here.** It is a VPS reachable as ssh alias `aizu`.
> Nothing in this document is an observation about it. `deploy/first-install-proposal.md` and
> `deploy/systemd/*.service` were written by an assistant that also had no access to it, so
> every path, unit name and command quoted from them is a **proposal**, flagged as such at each
> use. If your host does not run systemd, or does not live at `/srv/hbd`, the *checks* below
> still hold — only the way you reach the logs changes.

---

## 1. Vendor-credential separation

### What it protects

The admin process is the one thing on this system an operator signs into from a browser, over
the public internet, with a password. It is therefore the most exposed process in the fleet,
and it is deliberately the one with nothing worth stealing: no Telegram bot token, no
ElevenLabs key, no LLM key. The separation is structural before it is procedural —
`AdminSettings` has no field that could hold one, so even a value present in the environment
has nowhere to land (`src/hbd/admin/settings.py:164` sets `extra="ignore"`).

The four forbidden names are derived, never restated:

```python
# src/hbd/admin/app.py:116-118
FORBIDDEN_ENV_VARS: Final[tuple[str, ...]] = tuple(
    f"{ENV_PREFIX}{name.upper()}" for name in VENDOR_SECRET_FIELDS
)
```

`VENDOR_SECRET_FIELDS` is `telegram_bot_token`, `elevenlabs_api_key`, `llm_api_key`,
`llm_fallback_api_key` and `openrouter_management_key` (`src/hbd/config.py:111-117`) — five,
not three. The fifth arrived with **D13** and is the sharpest of them: an OpenRouter
management key can create and revoke API keys on the account, so its theft locks the workers
out rather than merely billing us. It is optional — unset, every process starts and the
balance poller reports the uncapped key it always did — and it is read by exactly one place,
the worker's hourly balance poll. The narrower tuple
`REQUIRED_VENDOR_SECRET_FIELDS` (`src/hbd/config.py:123-127`) is a different claim entirely:
"the bot cannot start without it", not "the admin host must never hold it". Adding a fifth
credential to `hbd.config` covers it here without anybody remembering to.

### What the deployment must do

Keep all five out of the admin process's environment **and** out of the dotenv file that
process reads. The scan covers both sources, because both are real:

```python
# src/hbd/admin/app.py:175-183
from_file = _env_file_names()
return tuple(name for name in FORBIDDEN_ENV_VARS if os.environ.get(name) or name in from_file)
```

The file half reads whatever `resolve_env_file(ADMIN_ENV_FILE_VAR, ADMIN_ENV_FILE)` returns
(`app.py:141-149`) — the same call `build_admin_settings` makes (`settings.py:75-81`,
`:661-668`), so the scan cannot clear a host whose credentials sit in the file that was really
loaded. That equality is load-bearing and the comment at `app.py:143-146` says why.

`HBD_ENVIRONMENT` must be exactly `prod` on the admin process, because the refusal is
conditional on it:

```python
# src/hbd/admin/app.py:191-199
if settings.is_production:
    raise ConfigError(
        "The admin process must not hold a vendor credential or a bot token, ..."
    )
```

`AdminSettings.environment` is a closed `Literal["dev","staging","prod"]`
(`src/hbd/admin/settings.py:169`), so a typo there fails the boot rather than downgrading the
control — unlike `Settings.environment` on the bot and worker, which is a bare `str`
(`src/hbd/config.py:170`) and will happily accept `production`.

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
(`src/hbd/logging.py:200-220`). `admin.boot.ok` carries `environment`, `env_file`,
`is_cookie_secure` and `public_origin` (`app.py:322-333`); it is the single line that
distinguishes "prod panel on prod config" from "prod panel booted off a dev checkout".

### How it fails

Three ways, in descending order of how quietly.

**Staging is a warning, not a refusal** (`app.py:200-203`). A staging admin host holding a real
ElevenLabs key boots normally and logs one WARNING.

**A missing dotenv file silences the file half of the scan.** `_env_file_names` catches only
`OSError` (`app.py:162-171`), and `dotenv_values` on a path that does not exist returns an
empty mapping without raising. So a mistyped `HBD_ADMIN_ENV_FILE` gives you the environment
half of the check and no signal at all that the other half found nothing. What saves this is not
the scan but the chain around it: with the file unread, `HBD_DATABASE_URL` (`settings.py:174`,
`min_length=1`, no default) and `HBD_ADMIN_AUDIT_HMAC_KEY` (`settings.py:229`, `SecretStr`,
`min_length=32`, no default) are missing, and those are required fields — so
`build_admin_settings()` raises `ConfigError` inside `_resolve_settings` (`app.py:313`, `:351`),
two lines *before* `_refuse_disabled_panel` (`app.py:315`) is reached. Expect a pydantic
field-required report naming `HBD_DATABASE_URL`, **not** the "Set HBD_ADMIN_ENABLED=true in
.env.admin" message (`app.py:120-122`) — the disabled-panel refusal never gets a turn on a host
whose only problem is a mistyped `HBD_ADMIN_ENV_FILE`. A field-required report on a config you
believe is complete is the signature of a dotenv file that was not read.

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

(`src/hbd/admin/middleware/security_headers.py:58-70`.) Alongside it go three constants —
`x-content-type-options: nosniff`, `referrer-policy: no-referrer`, `cache-control: no-store`
(`:73-77`) — and they **replace** rather than append, because two `Cache-Control` headers is
one header a proxy may resolve either way and the way that loses is the one that caches
(`:145-150`).

The nonce exists for one reason. `react-remove-scroll`, mounted by every Radix modal, injects a
real `<style>` element at runtime; `style-src 'self'` blocks it. So a fresh nonce is minted per
response (`security_headers.py:119-121`) and stamped into the SPA shell's `<meta
name="csp-nonce">` by a single `str.replace` of the literal `__HBD_CSP_NONCE__`
(`src/hbd/admin/shell.py:55`, `:86`). It is a meta element rather than an inline script
precisely so `script-src` never needs a nonce of its own (`shell.py:25-29`).

### What the deployment must do

Make sure the bundle on the host was built from the TypeScript being deployed.
`src/hbd/admin/static/` is gitignored, so it is never carried by a `git pull`; the repository
supports two ways for it to arrive, and which one your host uses is a **host question nobody in
this document can answer**:

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

---

## 3. `__Host-` cookies, Secure, and the TLS this repo does not terminate

### What it protects

The session cookie is a bearer credential. The `__Host-` prefix is not cosmetic: it is defined
so a browser refuses the cookie outright unless it is `Secure`, `Path=/` and carries no
`Domain` — which structurally prevents the sibling-subdomain injection that broke plain
double-submit CSRF (`src/hbd/admin/csrf.py:44-49`).

Both cookies are set that way, and the code cannot be configured out of it:

```python
# src/hbd/admin/routers/auth.py:304-330
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

Terminate TLS in front of the panel and set `HBD_ADMIN_PUBLIC_ORIGIN` to the `https://` origin
a browser actually types. Nothing in the code makes TLS a boot condition:
`_origin_must_be_a_bare_origin` accepts either scheme (`settings.py:501-515`,
`_ORIGIN_SCHEMES` at `:94`), and the prod guard only checks that the variable was *set*
(`settings.py:578-588`).

Give the panel its own hostname. `__Host-` cookies are scoped `Path=/` by definition and cannot
be narrowed, so anything else served at that origin sees them.

Add `Strict-Transport-Security` at the proxy.

> **This repository never emits HSTS.** `SECURITY_HEADERS` is exactly three pairs
> (`security_headers.py:73-77`) and the CSP template carries no `upgrade-insecure-requests`
> (`:58-70`). A case-insensitive grep for `strict-transport` or `hsts` across `src/`, `deploy/`
> and `docs/` returns nothing. A first request to `http://<panel host>` is upgraded by nothing
> the application controls: the session cookie will not be sent over it, but the login form and
> the operator's URL will. This is a proxy requirement and it is written down nowhere else in
> the tree.

### How to verify it is actually on

```bash
curl -sI https://<panel host>/ | tr -d '\r' | grep -i strict-transport-security
# Comes from your proxy or from nowhere. Absent means nobody added it.

# After a real sign-in in a browser: DevTools → Application → Cookies. Both must read
# __Host-hbd_session (HttpOnly, Secure, SameSite=Lax, Path=/) and __Host-hbd_csrf
# (Secure, SameSite=Lax, Path=/), and neither may carry a Domain.

grep 'admin.boot.ok' <the admin process's log>   # is_cookie_secure must be true
```

### How it fails

Loudly, and that is the good direction. If the browser does not treat the panel's origin as a
secure context, it rejects both `Set-Cookie` headers outright and nobody can sign in at all —
a panel that is unusable rather than merely insecure, which is exactly the argument at
`settings.py:572-577`. The failure mode to actually worry about is the one above it: a panel
reachable over plain `http://` on a hostname the operator is willing to type, where the login
form is submitted before any cookie is involved.

---

## 4. The exact origin check (and the CSRF token that does not depend on it)

### What it protects

Two of the three CSRF layers live in `src/hbd/admin/csrf.py`; the third is `SameSite=Lax` on
the cookie. The header is compared against `admin_sessions.csrf_token` — a database column —
and never against a cookie:

```python
# src/hbd/admin/csrf.py:96-111
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

Set `HBD_ADMIN_PUBLIC_ORIGIN` to the exact origin the browser sends — scheme, host and port,
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
> (`.env.admin.example:73` — `HBD_ADMIN_PUBLIC_ORIGIN=http://127.0.0.1:8080`), and
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

The behavioural check is the real one: **try to sign in.** With a wrong `HBD_ADMIN_PUBLIC_ORIGIN`
the login form renders and the login `POST` 403s with `ORIGIN_REJECTED` — the login handler runs
`_enforce_origin` before it does anything else (`auth.py:450`). If sign-in succeeds, the
configured origin matches what your browser sends; then perform any write, and a 403 on the first
mutation is the same control refusing an authenticated request instead (`deps.py:217-238`).

### How it fails

It boots clean and fails at the sign-in, every time — not at the first write. The two refusals are
the same check in two places and they log under **different event names**, which matters when you
are grepping:

```bash
# The one that actually fires on a wrong HBD_ADMIN_PUBLIC_ORIGIN: the refused login POST.
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
# src/hbd/admin/security/clientip.py:142-149
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

Two settings, and they must agree with the real topology. There are no correct values to quote
here, because **the topology is unknown from this repository**: whether a reverse proxy exists at
all, whether it is co-located with the admin process, and whether anything (a CDN edge, a second
load balancer) sits in front of it are host facts — rows 17 and 23 of `00-host-inventory.md`, both
still empty. Derive the two values from the answer, do not copy them:

```ini
# In the admin process's dotenv file.
# EXAMPLE VALUES ONLY — they describe one nginx or Caddy on the same box as the panel,
# which nobody in this document has confirmed is the shape of the aizu host.
HBD_ADMIN_TRUSTED_PROXY_HOPS=1                       # ge=0, le=4 — settings.py:216
HBD_ADMIN_TRUSTED_PROXY_CIDRS=127.0.0.1/32           # the addresses your proxies connect FROM
```

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
  -H 'Cookie: __Host-hbd_session=<your session cookie>' \
  | python3 -m json.tool | grep -i 'trustedProxy'
```

They are published deliberately: "wrong values here silently change which address every rate
limit is keyed on, so they are exactly what an operator needs to see"
(`config_view.py:127-129`).

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

(`src/hbd/db/admin/audit.py:11-15`, computed at `:396`.) The key lives in the admin process's
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
role = _app_role()          # HBD_DB_APP_ROLE, else the username in HBD_DATABASE_URL — :314-322
if role is None:
    _skip(f"neither {_APP_ROLE_ENV} nor a username in {_APP_DSN_ENV} names the app role")
    return
```

`HBD_ADMIN_AUDIT_DSN` is documented as living in `.env.admin` (`.env.admin.example:130`), and
the migration runner never loads that file — `migrations/env.py` reads only `hbd.config.env_file()`
and `load_settings()` (`env.py:95-129`). `HBD_DB_APP_ROLE` appears in **neither** example file,
so an operator has no way to discover it exists. The proposed invocation at
`deploy/first-install-proposal.md:112` exports only `HBD_ENV_FILE`. Following it verbatim, `_install_two_role_controls`
takes its first `_skip` branch and the REVOKE is never applied — and even with the DSN
exported, `_app_role()` returns `None` because `HBD_DATABASE_URL` is only in the file too.

**Set `HBD_DB_MIGRATION_URL` to the owner DSN — this is the variable that actually decides it,
and exporting the two above without it changes nothing.** `HBD_ADMIN_AUDIT_DSN` is only a *flag*:
0007 tests that it is non-empty and never connects with it (`0007:336`). The role alembic
connects **as** is chosen by `migrations/env.py:_database_url` (`env.py:117-129`), which prefers
`HBD_DB_MIGRATION_URL` (`env.py:85`, `_owner_url` at `:107-114`) and otherwise falls back to
`HBD_DATABASE_URL` — the application role. Connect as the application role and 0007 reaches its
fourth skip branch:

```python
# migrations/versions/20260830_1000_0007_add_admin_audit_log.py:354-356
if connection.execute(sa.text("SELECT current_user")).scalar() == role:
    _skip("migrations run as the application role, so a REVOKE from it is reversible by it")
    return
```

— and the REVOKE is still never applied. Unlike the other two, this variable *does* fall back to
the dotenv file `HBD_ENV_FILE` names (`env.py:107-114`), so it can live in the bot env file; the
README documents it as one of the two switches for the whole two-role split
(`README.md:172-173`, `docker/initdb/10-two-roles.sql:17`).

All together, whatever your runner:

```bash
cd <checkout>
HBD_ENV_FILE=<bot env file> \
HBD_DB_MIGRATION_URL='postgresql+asyncpg://hbd:<owner password>@localhost:5432/hbd' \
HBD_ADMIN_AUDIT_DSN='postgresql://hbd:<owner password>@localhost:5432/hbd' \
HBD_DB_APP_ROLE=hbd_app \
  .venv/bin/python -m alembic -c migrations/alembic.ini upgrade head
```

`HBD_DB_MIGRATION_URL` may be dropped from that line if it is already in the file `HBD_ENV_FILE`
names; `HBD_ADMIN_AUDIT_DSN` and `HBD_DB_APP_ROLE` may not, because 0007 reads only `os.environ`
for those two.

Note that `migrations/env.py:14-19` records this exact defect being fixed for
`HBD_DB_MIGRATION_URL` — the environment-only read "would have migrated production as the wrong
role" — and the fallback was added there and not to the two migration bodies that need the same
thing.

**Back up `HBD_ADMIN_AUDIT_HMAC_KEY` separately from the database.** It is a `SecretStr` with
`min_length=32`, required from the first boot (`settings.py:229`), and it lives only in the
admin dotenv file. A backup containing both the table and the key is a backup an insider can
rewrite; a database-only restore comes back with a log nobody can verify.

### How to verify it is actually on

The system reports this honestly rather than assuming it worked. The badge is derived by asking
Postgres, not by reading configuration:

```sql
-- src/hbd/db/admin/audit.py:746-752, run as the admin process's own role
SELECT has_table_privilege(current_user, 'admin_audit_log', 'UPDATE')
    OR has_table_privilege(current_user, 'admin_audit_log', 'DELETE')
    OR has_table_privilege(current_user, 'admin_audit_log', 'TRUNCATE') AS is_writable;
-- false is what you want.
```

Through the panel, signed in as ADMIN or OWNER (`AUDIT_READ` is granted to those two only —
`permissions.py:374`):

```bash
curl -s https://<panel host>/api/audit/verify \
  -H 'Cookie: __Host-hbd_session=<your session cookie>' | python3 -m json.tool
```

Read **three** fields, not one:

- `chainProtection` — `revoke+hmac` means the privileges really are gone. `hmac-only` is
  reported whenever the DSN is unset, the backend is not Postgres, the probe errored, *or* the
  probe says the role is still writable (`audit.py:755-780`).
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
exactly once, in the terminal of whoever ran the migration.

### How it fails

**The REVOKE skips itself with a warning, not an error.** `_skip` logs; `upgrade()` continues
(`0007:334-343`, `:387-391`). The migration succeeds, the schema is correct, and the control is
absent. There are **four** skip branches, and only the first two are about variables you forgot
to export: `HBD_ADMIN_AUDIT_DSN` unset (`0007:336-338`), no app role named (`:339-342`), the named
role absent from `pg_roles` (`:349-353` — a typo in `HBD_DB_APP_ROLE`, or roles that were never
created by hand), and `current_user` *being* the app role (`:354-356` — `HBD_DB_MIGRATION_URL`
unset, so alembic connected as the application role). The last two are the ones that survive a
correct-looking export line, and all four produce the same one-line WARNING.

**A key rotation is indistinguishable from tampering.** The MAC input carries a
`CHAIN_VERSION` constant (`audit.py:111`) but no key identifier, and `AdminAuditRow` has no
key-id column (`src/hbd/db/models/admin_audit.py`). Change the key and `/audit/verify` reports
a break at the first row forever; lose it and the log is permanently unverifiable. There is no
rotation path in the code — treat the key as a write-once deployment secret.

**The tail-protection window is one hour wide, and only the worker refreshes it.**
`/audit/verify` writes nothing, including no fresh anchor (`routers/audit.py:1-7`). HEAD and
TRUNCATION anchors are pinned by the retention sweep (`src/hbd/db/purge.py:362-365`,
`purge_admin.py:198-215`), which is an ARQ cron at :17 past the hour
(`retention_job.py:70-73`, `jobs.py:706-714`). If the worker is down, rows written since the
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

### What the deployment must do

Pass the bind address on the command line, because that is the only thing that decides it:

```bash
<venv>/bin/python -m uvicorn hbd.admin.app:app --host 127.0.0.1 --port 8080
```

That string is Makefile:75, and the same string appears at `deploy/systemd/hbd-admin.service:30`
— a **proposal**, not a record of any host.

> **`HBD_ADMIN_HOST` and `HBD_ADMIN_PORT` bind nothing.** They are declared at
> `src/hbd/admin/settings.py:188-189`, and a grep across `src/` finds exactly two other
> readers: `config_view.py:108-109` and `:202-203`, which project them onto `GET /api/config`.
> `app: Final[FastAPI] = create_app()` (`app.py:440`) is an ASGI object; it cannot know or
> refuse the address it is served on. So if the process is started with `--host 0.0.0.0`, the
> panel is on the internet, the settings model cannot detect it, and `/api/config` still
> renders `adminHost: 127.0.0.1` to the operator checking. Changing `HBD_ADMIN_PORT` in the
> env file changes what the panel *displays* and not what it binds.

### How to verify it is actually on

From the host itself, not from the panel:

```bash
ss -ltnp | grep 8080         # must show 127.0.0.1:8080, never 0.0.0.0:8080 or :::8080
ps -eo args | grep '[u]vicorn hbd.admin.app'   # read the actual --host flag in the command line
```

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
at `:53-56`). Detail requires `X-Probe-Token` matching `HBD_ADMIN_PROBE_TOKEN` under
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

## Controls that degrade silently

These are the ones that report themselves as *not deployed* rather than failing. Each is a
supported configuration from the code's point of view, so nothing refuses to start — which
makes this exactly the set a reviewer has to check by hand on the host.

| Control | What it looks like when it is off | The only signal | Where to look |
|---|---|---|---|
| Client-IP derivation behind a proxy | Every rate limit and every audit row records the proxy's address; the strict login counter becomes one global bucket per username | **None.** Not in the boot line, not in any log | `GET /api/config` → `adminTrustedProxyHops`, `adminTrustedProxyCidrs` (`config_view.py:127-129`); then a two-network sign-in and read back `admin_audit_log.ip` |
| Audit REVOKE (two-role split) | The app credential can still `UPDATE`/`DELETE`/`TRUNCATE` the log; only the HMAC protects it | `chainProtection: "hmac-only"`, plus WARNING `admin.audit.revoke_missing` — and the latter **only when the DSN is set** | `GET /api/audit/verify`; `has_table_privilege` in psql; the alembic WARNING at migrate time (`0007:325-331`) |
| CSP style nonce (stale bundle) | Panel looks fine; every runtime-injected `<style>` is blocked, so modal scroll-lock stops working | WARNING `admin.spa.nonce_placeholder_missing`, once per response | `shell.py:78-85`; rebuild with `make ui-build` |
| Vendor-credential scan, file half | Only the process environment was checked; the dotenv half found nothing and said nothing | **None** when the file is absent (`dotenv_values` returns `{}`, no `OSError`) | `admin.boot.ok` → `env_file`, compared against the file you believe is live (`app.py:329`) |
| Vendor-credential refusal on staging | A real vendor key sits on an operator-facing host | WARNING `admin.boot.vendor_env_present` (`app.py:200-203`) | Same grep; in prod this is a boot refusal instead |
| Origin check with a wrong value | The login page renders and the login `POST` 403s — nobody signs in at all (`auth.py:450`) | WARNING `admin.login.origin_refused`, per refusal (`auth.py:186-189`). **Not** `admin.csrf.refused`, which only the authenticated path emits (`deps.py:230-236`) | `admin.boot.ok` → `public_origin`; then try to sign in |
| HSTS | Plain `http://` to the panel host is never upgraded | **None.** This repository emits no HSTS at all | `curl -sI` the panel; `security_headers.py:73-77` |
| `/readyz` without a probe token | Constant `{"status":"ok"}` to every monitor, database down or not | **None** — that is the point of the constant (`health.py:9-19`) | `GET /api/config` → `isProbeTokenConfigured` (`config_view.py:186-188`) |
| Loopback binding | The panel may be on a public interface; `/api/config` still reports `127.0.0.1` | **None** | `ss -ltnp` on the host; the uvicorn `--host` flag in the actual command line |
| Audit write path | Actions happen and are not recorded | ERROR `admin.audit.write_failed` / `admin.audit.value_refused`; the chain shows the gap as a break at the next `seq` | `audit_sink.py:99-135` |
| Session mirror invalidation | A revoked session may survive until its 60 s mirror expires | WARNING `admin.session.mirror_invalidation_failed` | `sessions.py:264` |
| `HBD_ADMIN_CONFIG_ENABLED` | Protects nothing today — no endpoint reads it, and the runtime-config editor it names does not exist in this tree | **None.** It defaults to `true` and is published on `/api/config` as though it were armed | grep `admin_config_enabled`: the field (`settings.py:185`), its projection (`config_view.py:107`, `:201`), and prose in `routers/config.py:10` |

Two things about that list are worth saying out loud. The first is that every entry whose only
signal is a log line assumes somebody is reading the logs — and whether the admin process's
output is shipped anywhere at all is a host question this repository cannot answer. The second
is that the top row has no signal of any kind, in any log, at any level. It is the one that has
to be checked by hand.
