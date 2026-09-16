# Bayram — Tabriklar, Qoʻshiqlar

A Telegram bot for the Uzbekistan market. A user types a recipient's full name, answers
four short structured questions, and receives a **celebration kit**:

- one AI-generated song (~90 s — `BAYRAM_SONG_LENGTH_MS`) that names the recipient,
- a lyric sheet,

with the recipient's name **pronounced correctly**. That last part is the entire product.

**The words can be the customer's own, and then it is a different wizard.** The first
question ("What are we celebrating?") offers *My own lyrics* beside the occasions, and
choosing it switches the intake onto a second, shorter order:

```
occasion → LYRICS → genre → voice → language → confirm
```

The words are asked for **second**, before anything else, because that is what the customer
said they had. Three steps are dropped and each one is dropped for a reason:

- **the note** ("tell me one thing about them — I write it into the words") fed the lyric
  writer, and nothing writes the words now;
- **the name** and its confirmation fed the name subsystem — hook section, chunk isolation,
  acoustic verification — and a customer who wrote their own lyric already put whatever name
  they wanted where they wanted it. Weaving another one in would sing a word they did not
  write.

So these orders carry `Brief.recipient = None` all the way to the queue. There is no hook
section, no name chunk, no STT call and no candidate ladder; the composition plan spends the
whole song budget on their words, and the sheet drops its signature line. **This is the one
path where the pronunciation guarantee does not apply**, by the customer's own choice.

It also calls **no vendor at all** before the payment gate: no `MAX_LYRIC_WRITES`, no daily
lyric budget. Somebody who arrives with a poem already written should not have to buy a
machine's attempt at one to reach the screen that accepts theirs.

`lyrics_source` on the wizard draft names which order a session is walking, and the occasion
step is the only place it is ever written — picking a real occasion there hands the writing
back to the bot, which is the button's un-press. Nothing downstream may move it: a customer
who types over a lyric the bot wrote is still on the writer's path, name hook and all.

A `NULL` recipient is **not** the same as a purged one. `briefs.identity_purged_at` is
stamped only by the 90-day sweep, and that column alone is now what `is_identity_purged`
reads — an order that never collected a name must not report itself to an operator, or to an
erasure proof, as personal data deleted on schedule.

> **Greetings are switched off.** `BAYRAM_GREETINGS_PER_KIT` defaults to **0**, so a kit is the
> song and the sheet, and no TTS call is made at all. The spoken-greeting subsystem
> (`bayram.providers.tts`, personas, OGG/Opus voice notes) is fully built and tested and comes
> back by raising that one setting to 1–5. Note this contradicts SOW §4.5 (FR-38–FR-45),
> which makes song+speech the differentiator; it was switched off by product decision on
> 2026-08-28, not by accident.

Interface language and output language are chosen independently across Uzbek Latin
(default), Uzbek Cyrillic, Russian and English. All four ship complete.

---

## See it work in two commands, with no keys

Everything below was run on macOS 26.3 / Python 3.12.13 while writing this file.

```bash
make install                    # uv venv .venv + pip install -e ".[dev]"
make demo                       # one complete kit, offline
```

`make demo` runs the **real** pipeline — real orchestrator, real name subsystem, real
ffmpeg, real SQLite repository, real files — with only the vendor adapters (music, TTS, STT
and the LLM) swapped for fakes. No API key is read, no request leaves the machine, nothing
is spent. It prints the candidate orthographies, the acoustic verification loop re-rolling
the name, the paths of the assets it just wrote, and the lyric sheet in full. Those assets
are the song and the sheet and nothing else: `BAYRAM_GREETINGS_PER_KIT` is 0, as above, so the
orchestrator skips the greeting stages entirely. Raise it to 1–5 and that many OGG/Opus
voice notes appear in the same list.

It needs **ffmpeg on PATH** and nothing else (`brew install ffmpeg`).

### Drive the actual bot, still with no keys and no infrastructure

```bash
cp .env.example .env
# in .env:  BAYRAM_USE_FAKE_PROVIDERS=true
#           BAYRAM_TELEGRAM_BOT_TOKEN=<a real token from @BotFather>
#           BAYRAM_DATABASE_URL=sqlite+aiosqlite:///./var/bayram.db
make dev
```

With `BAYRAM_USE_FAKE_PROVIDERS=true` the bot keeps the wizard in memory, runs each order as
a background task in its own process, and writes to SQLite — no Redis, no Postgres, no
worker, no vendor. Message the bot, walk the wizard, and the kit arrives in the chat.
A Telegram token is the one thing a *chat* demo genuinely cannot fake; `make demo` needs
no token at all.

### Production shape

Three long-running processes — the bot, the ARQ worker and the admin API — plus the admin
console, which is a static bundle the API serves itself. `.env` belongs to the first two;
the admin API reads **`.env.admin`** and nothing else.

```bash
cp .env.example .env && $EDITOR .env              # real keys; BAYRAM_USE_FAKE_PROVIDERS=false
cp .env.admin.example .env.admin && $EDITOR .env.admin   # no vendor keys here — see below

docker compose up -d                              # postgres 16 (two roles) + redis 7
export BAYRAM_DB_MIGRATION_URL="postgresql+asyncpg://hbd:hbd@localhost:5432/hbd"
export BAYRAM_DATABASE_URL="postgresql+asyncpg://hbd_app:hbd_app@localhost:5432/hbd"
make migrate                                      # alembic upgrade head, as the owner role
make ui-build                                     # console → src/bayram/admin/static/ — every deploy
make admin-bootstrap u=owner                      # the first OWNER; prompts for the password

make dev                                          # terminal 1: the bot
make worker                                       # terminal 2: the ARQ worker
make admin                                        # terminal 3: the admin API on 127.0.0.1:8080
```

The panel is then at `http://127.0.0.1:8080`, serving the bundle `make ui-build` wrote.
`make admin` binds loopback deliberately: put TLS in front of it. Binding `0.0.0.0`
publishes a username/password login to the internet, and nothing in the panel is designed
for that.

`make admin-bootstrap u=<username>` forwards the one flag the CLI requires, the same way
`make revision m="…"` does; anything else goes through `args=`, as in
`args="--reset-owner"` or `args="--password-file ./pw"`. Run it with no `u=` and it prints
the usage instead of an argparse error. `--password` is accepted only so it can be
**refused** — a password in `argv` is in `ps` and in the shell history. Use the prompt, or
`--password-file` on a file only you can read; the CLI refuses one whose mode lets the
group or anybody else read or replace it.

> **Rebuild the console on every deploy.** `src/bayram/admin/static/` is gitignored — a
> committed bundle drifts from `admin-dashboard/` with nothing to notice — so a fresh checkout has
> no console at all, and a stale one is whatever the last build left behind. It is not only
> a cosmetic staleness: `admin-dashboard/index.html` carries a `__BAYRAM_CSP_NONCE__` placeholder that
> the API swaps for this response's style nonce, and a bundle built before that existed has
> no placeholder to swap. `render_shell` serves such a shell **unchanged** and logs
> `WARNING admin.spa.nonce_placeholder_missing` rather than returning 500 — deliberately, so
> that an operator reaching for the panel mid-incident gets a working panel rather than a
> dead one. The cost is that the only symptom is that log line, plus modals that no longer
> lock the background: `style-src 'self' 'nonce-…'` refuses the scroll-lock `<style>` the
> bundle injects, and the page keeps scrolling behind an open dialog. Grep the API's log for
> that event, then `make ui-build`.

> **The admin API reads `.env.admin`, not `.env`, and that is the point.** There is no field
> on `AdminSettings` that could hold `BAYRAM_TELEGRAM_BOT_TOKEN`, `BAYRAM_ELEVENLABS_API_KEY` or
> either LLM key, so the panel has no code path to a vendor credential. Pointing it at the
> shared `.env` would hand it all four by accident. In prod, any one of them within reach of
> the process — exported, *or written into `.env.admin`* — is a boot refusal naming the
> variable; in dev it is a WARNING, because a shared dev `.env` is normal.
>
> Every operational action that needs a credential is an ARQ job the worker performs. The
> API sends nothing to Telegram and calls no vendor.
>
> Three fields have no usable default: `BAYRAM_ADMIN_ENABLED` is `false` until somebody turns
> the panel on, `BAYRAM_ADMIN_AUDIT_HMAC_KEY` is required and has no default to forget to
> change (`python -c "import secrets; print(secrets.token_urlsafe(48))"`), and
> `BAYRAM_ADMIN_PUBLIC_ORIGIN` is required outside dev. `.env.admin.example` documents the rest
> with the reasoning attached.

> **Two Postgres roles, or the audit log's immutability is theatre.** `hbd` owns the tables
> and runs migrations; `hbd_app` is what the bot, the worker and the admin API connect as.
> An owner can `GRANT` back its own revocations, so migration `0007`'s
> `REVOKE UPDATE, DELETE, TRUNCATE ON admin_audit_log` means nothing at all when the
> application connects as the owner — there is nobody to revoke it *from*.
>
> `docker/initdb/10-two-roles.sql` creates `hbd_app` and its grants. The Postgres entrypoint
> runs it **only on an empty data volume**, so an already-initialised container needs
> `docker compose down -v && docker compose up -d` to pick it up. In staging or production,
> create the two roles by hand with real secrets — the password in that file is a local
> development password.
>
> Two variables switch the control on: `BAYRAM_DB_MIGRATION_URL` (the owner DSN, which
> `migrations/env.py` uses when set) and `BAYRAM_ADMIN_AUDIT_DSN` in `.env.admin`, whose
> presence is how a deployment declares the split exists. Leave either unset and everything
> still runs: migrations fall back to `BAYRAM_DATABASE_URL` with a WARNING, `0007` skips the
> REVOKE and logs why, and `/audit/verify` reports `chainProtection: "hmac-only"` — which
> the panel shows verbatim. A control that is not deployed is reported as not deployed,
> never implied.

> **If 5432 is already taken** (a system Postgres, Postgres.app, another project), the
> container will fail to bind, and `localhost` resolving to IPv6 first means a foreign
> Postgres can answer instead of ours. Pick a free port and pass it to both:
>
> ```bash
> BAYRAM_POSTGRES_PORT=55432 docker compose up -d
> export BAYRAM_TEST_POSTGRES_URL="postgresql+asyncpg://hbd:hbd@localhost:55432/hbd"
> export BAYRAM_DATABASE_URL="postgresql+asyncpg://hbd:hbd@localhost:55432/hbd"
> ```
>
> The Postgres-backed tests skip rather than fail when no *project* database answers, so a
> `make test-all` whose only skips are those means "Postgres not wired up", not "something is
> broken". They are the eighteen tests
> `.venv/bin/python -m pytest -m integration --collect-only tests/test_db tests/test_admin/test_bootstrap_race.py`
> lists, and they carry the skip reason with the DSN they tried.


### Dev and prod: which file each process reads

Two axes, and conflating them is the usual mistake.

`BAYRAM_ENVIRONMENT` (`dev` | `staging` | `prod`) is a value **inside** a config file, and it
is what the code branches on: at `prod`, `BAYRAM_USE_FAKE_PROVIDERS` is refused, panel `DEBUG`
is refused, `BAYRAM_ADMIN_PUBLIC_ORIGIN` is required, and an admin process that can reach a
vendor credential refuses to boot. `BAYRAM_ENV_FILE` and `BAYRAM_ADMIN_ENV_FILE` decide **which
file** is read. They are process-environment variables — a dotenv file cannot name the
dotenv file about to be read — and they default to `.env` and `.env.admin`, so a checkout
that has only ever had those two behaves exactly as it always has.

The split by *process* is the older and more important one, and it survives both:

|             | bot + worker       | admin API              |
| ----------- | ------------------ | ---------------------- |
| development | `.env`             | `.env.admin`           |
| production  | `/etc/bayram/bot.env` | `/etc/bayram/admin.env`   |

`make` wraps the two variables in one `ENV` flag:

```bash
cp .env.example .env.prod             && $EDITOR .env.prod
cp .env.admin.example .env.admin.prod && $EDITOR .env.admin.prod

make admin ENV=prod          # .env.prod + .env.admin.prod
make dev ENV=prod            # …and the same for worker, migrate, revision, admin-bootstrap
```

`ENV=dev` is the default and maps to the bare names, so nothing changes for anyone who
never passes the flag. Only `dev` and `prod` are in use; `staging` is a supported third
value of `BAYRAM_ENVIRONMENT` with nothing built for it yet.

> **`ENV=prod make dev` is a loaded gun, deliberately.** It points a real bot token, real
> vendor keys and a real database at a process running from your working tree. Both boot
> paths log which file they read — `host verified` carries `environment` and `env_file`,
> `admin.boot.ok` carries the same pair — so the terminal says which configuration is live
> before you type anything into the bot.

> **`BAYRAM_DB_MIGRATION_URL` now comes from that file too.** It used to be read from
> `os.environ` alone, so the line `.env.example` documents did nothing unless it was also
> exported by hand — and `make migrate ENV=prod` would have migrated a production database
> as whichever role the shell happened to be carrying. `migrations/env.py` reads the
> process environment first and the selected dotenv file second. It is still kept off
> `Settings`: the bot and the worker must never hold the owner credential.

Production is three systemd units on one VPS, with the secrets in root-owned `0640` files
under `/etc/bayram/` rather than in `EnvironmentFile=` — which would put them in
`systemctl show` and `/proc/<pid>/environ`. The units and the full runbook are in
[`deploy/`](deploy/README.md); `bayram-admin.service` carries
`InaccessiblePaths=/etc/bayram/bot.env`, so the vendor-key separation is enforced by the
kernel as well as by the panel's own boot refusal.

### The admin console in development

A fourth terminal, and the only one that is not part of the production shape: Vite's dev
server, so a change to `admin-dashboard/` reloads without a rebuild.

```bash
make ui-install   # npm install in admin-dashboard/ — the only Node in the tree
make ui           # terminal 4: the console on :5174, proxying /api to :8080
```

It needs `make admin` running in another shell, and
`BAYRAM_ADMIN_PUBLIC_ORIGIN=http://localhost:5174` in `.env.admin`. The dev proxy forwards the
browser's real `Origin` (`changeOrigin: false`), so the API's origin check is live in
development too — that is deliberate. A 403 `ORIGIN_REJECTED` at sign-in means that
variable, not the proxy flag.

`make dev` is `python -m bayram.main`; `make worker` is
`python -m arq bayram.worker.WorkerSettings`; `make admin` is
`python -m uvicorn bayram.admin.app:app --host 127.0.0.1 --port 8080`.

### Checks

```bash
make test        # unit tests only: no network, Redis, Postgres or ffmpeg
make lint        # ruff
make typecheck   # mypy --strict over src and tests
make cov         # unit tests with the 80% gate
make test-all    # adds the integration tests (need ffmpeg; some need Postgres)
make cov-admin   # the same run, re-reported against src/bayram/admin alone, gated at 85%
make check       # lint + typecheck + cov — the Python half, and all `make check` is
```

**`make check` is not the whole gate, and knowing which part it is not is the point.** It
runs ruff, `mypy --strict` and the coverage run, and nothing that involves Node or a
browser. One more set exists and it is not reachable from it:

```bash
make ui-check        # the deployed console's gates: tsc, eslint, vitest, the locale suite
```

`ui-check` targets `admin-dashboard/` — the console that is actually deployed — and runs four
scripts: `typecheck`, `lint`, `test:unit` (Vitest, the components) and `test` (the tsx harness
that asserts 100% key parity and interpolation-token consistency across `en`/`ru`/`uz`).
Neither runner subsumes the other, so both are on the target.

Until 2026-09-10 `ui-check` ran the legacy console's script list against `admin-dashboard`, so
it **failed on a green tree** at `tokens:check` — a script `admin-dashboard` does not declare —
and, because that line came last, never reached `test:unit` at all: the deployed console's
component suite was guarded by no target.

> **There is no browser gate, and nothing replaced the one that was removed.** Until
> 2026-09-16 the repo carried a second console, `admin-ui/`, and the Playwright suite lived
> inside it: `e2e/csp.ts`, `e2e/smoke.spec.ts` and a font-coverage spec, driven by
> `make ui-e2e` through `tests/e2e/serve_admin_e2e.py`. That console was deprecated, was never
> deployed, built into the *same* `build.outDir` as the live one, and its specs asserted on its
> own bundle and font pipeline — so `make ui-e2e` had already been unrunnable for some time and
> could not have been re-pointed at `admin-dashboard/` without a rewrite. Console and suite were
> removed together, along with `tests/e2e/`.
>
> What that leaves uncovered is worth naming rather than discovering: **jsdom implements no
> CSP**, so a `<style>` element Chrome refuses is accepted in silence by every one of the
> console's Vitest tests, and no remaining check can see a Content-Security-Policy regression
> in a real browser. The *policy* is still covered in Python — `tests/test_admin/test_security_headers.py`
> asserts the header, and `test_spa_nonce.py` asserts the nonce is fresh per response and that
> `admin-dashboard/index.html` still carries the `__BAYRAM_CSP_NONCE__` placeholder Python
> substitutes. What is not covered is whether the built bundle actually complies with it.
>
> The font-coverage check went with it too (§14's `Oʻktam` / `Gʻulom` / `Дилноза` / `sanʼat`
> bullet): it rasterised every character in both token font stacks and compared each bitmap
> against an unassigned-plane codepoint, so a name drawn as `.notdef` boxes failed instead of
> counting as "rendered". The gap it documented is still open — §12.1 T7 asks for
> **self-hosted** Inter and JetBrains Mono and this build ships neither, so U+02BB/U+02BC and
> Cyrillic coverage is the operator's machine's rather than the bundle's. Restoring either
> check means new specs written against `admin-dashboard/`; the old ones are in git history.

Until this repo has CI wired to it, "before a release" means a human running both sets —
`make check` and `make ui-check` — and that is the whole of the policy.

Measured on this machine on **2026-09-16**, with the commands above, after `admin-ui/` was
removed and the eleven standing `mypy` errors were fixed: `make lint` clean; `make typecheck`
clean over **647 files**; `make cov` **8034 passed, 56 deselected** at **94.46%** repo-wide in
**9m31s**, and the admin re-report at **99%** on `src/bayram/admin/*`; `npm run test:unit` green
over **318 tests in 24 files** and `npm run test:e2e:strict` green over **55**, zero pending.

> The figures this paragraph carried until that date — 430 files, 4788 tests, 96%, and
> "815 tests in 73 files" — were all stale, and two of them were not merely out of date. The
> vitest count was the *legacy* console's and said nothing about the deployed one. And
> `make typecheck` did not pass at all: eleven errors had accumulated in `tests/`, unnoticed
> because nothing ever ran the gate. Two were real — a protocol fake that had drifted from
> `PaymentIntentOpener`, and a chained identity check that `--strict-equality` had marked
> unreachable, silently disabling the three assertions beneath it. This is what CI is for.
Those counts move with every commit that adds a test — the commands
print the current ones, and it is the *clean* that matters, not the number. One unit test —
`tests/test_runtime/test_entrypoints.py` — wants ffmpeg on PATH despite the convention
below, and is the only failure on a machine without it. The integration suite adds 49 more:
22 real-ffmpeg audio tests, 6 full-stack wizard-to-delivery tests, the offline demo, an
ffmpeg host check, one live-model moderation probe, and 18 Postgres tests that need
`docker compose up -d`.

---

## Module map

Every module depends on the foundation, and on nothing else in `src/bayram/` except through
a `Protocol`. Only `bayram.runtime` knows which concrete vendor is behind which protocol.

### Foundation

| File | Owns |
|---|---|
| `src/bayram/contracts.py` | Every frozen model, the `Result` type, and all eight `Protocol` interfaces. The one file every module imports. |
| `src/bayram/config.py` | All settings: keys, model ids, timeouts, retry bounds, loudness targets, chunk durations, free-tier caps, and **the name-candidate order**. |
| `src/bayram/errors.py` | `BayramError` and its subclasses. Every error carries a customer-safe `user_message_key` *and* full operator context, and declares itself retryable or terminal. |
| `src/bayram/logging.py` | JSON logs, one correlation id per order via `contextvars`, secret redaction at the formatter. |

### Modules

| Module | Responsibility |
|---|---|
| `bayram.names` | **The differentiator.** Canonicalise the typed name, emit ranked candidate orthographies, hold the display/submitted split. Pure functions; no network. |
| `bayram.i18n` | JSON locale catalogues, CLDR plurals, the U+02BB orthography guard. |
| `bayram.providers.llm` | Gemini 3.7 Flash (paid tier, strict JSON) with an OpenAI-compatible fallback behind the identical contract. Plus `FakeLlmProvider`. |
| `bayram.providers.music` | ElevenLabs Eleven Music. Builds the `CompositionPlan`, submits it, and re-renders the name chunk alone via inpainting. Plus `FakeMusicProvider`. |
| `bayram.providers.tts` | ElevenLabs v3 for all four languages, behind one `LanguageRoutingTts`. Also hosts `ElevenLabsScribe` (STT), used **only** to verify the rendered name. |
| `bayram.audio` | ffmpeg: two-pass loudnorm, silence trim, fades, libopus 32k/48k/mono voice notes. |
| `bayram.db` | Postgres via SQLAlchemy 2.x async + Alembic. `SqlKitRepository`, retention policy, the purge job. |
| `bayram.storage` | `LocalFileStorage` — the object-storage leg, filesystem-backed. Confined keys, atomic writes, never raises. |
| `bayram.pipeline` | The orchestrator: one `Brief` in, one `Kit` out, including the acoustic verification loop and its bounded re-rolls. |
| `bayram.bot` | aiogram 3.x wizard, four locales, progress, delivery. |
| `bayram.payments` | The RENDER gate — `PaymentProvider.authorize` answers "may this order be rendered?" against a credit already owned. `NoopPaymentProvider` always authorises. |
| `bayram.checkout` | The BUYING seam — `CheckoutProvider.charge` answers "did money change hands?", and the vendor-neutral redirect vocabulary (`PaymentIntent`, `PaymentIntentOpener`). Imports no HTTP client and **may never import `bayram.db`**. |
| `bayram.payme` | The Payme Merchant API: the pure wire layer (protocol, errors, Basic auth, the link builder), the inbound JSON-RPC service, its ASGI app and its own composition root, and the operator CLI. Ships switched off. |
| `bayram.admin` | The operator panel: a FastAPI JSON API (third process, `make admin`) plus the React/Vite console in `admin-dashboard/`. Read-only in this build. Holds no vendor credential and sends nothing to Telegram — every action that needs one is an ARQ job. |
| `bayram.runtime` | **The composition root.** Builds real or fake vendors from config, owns the container, the queue seam and the job that generates *and delivers*. |

### Entry points

| Command | Module | What it is |
|---|---|---|
| `make dev` | `bayram.main` | The bot process. Long polling. |
| `make worker` | `bayram.worker` | The ARQ worker. Owns a send-only `Bot`. |
| `make demo` | `bayram.demo` | One kit, offline, printed to the terminal. |
| `make admin` | `bayram.admin.app` | The admin API on `127.0.0.1:8080`, behind uvicorn. Reads `.env.admin`; serves the console out of `src/bayram/admin/static/`. |
| `make payme` | `bayram.payme.app` | The Payme gateway on `127.0.0.1:8091`, behind uvicorn. Reads `.env.payme`. Refuses to start unless `BAYRAM_PAYME_ENABLED=true`, which is not the default. |
| `make admin-bootstrap u=<username>` | `bayram.admin.bootstrap` | The first OWNER account, and the way back from losing one (`args="--reset-owner"`). Prompts for the password; never takes one in `argv`. |
| `make ui-install` / `make ui` / `make ui-build` | `admin-dashboard/` | Install the console's Node dependencies; run its dev server on `:5174`; build it into the API's static directory. It is the only Node package in the tree. |

The one flag that changes everything is `BAYRAM_USE_FAKE_PROVIDERS`. It is **all-or-nothing**
by design — a half-fake run spends money on a result nobody can trust — and it is refused
outright when `BAYRAM_ENVIRONMENT=prod`.

### Two payment seams, and four processes

**There are two payment seams and they answer different questions.**
`bayram.payments.PaymentProvider.authorize` is the RENDER gate — *"may this order be
rendered?"*, asked once per order against a credit the customer already owns, and
`NoopPaymentProvider` always says yes. `bayram.checkout.CheckoutProvider.charge` is the BUYING
seam — *"did money change hands for a product?"*, asked on a button tap, with a receipt and a
credit grant behind it. Overloading one with the other would give a single seam two meanings,
and the first person to fake it for one meaning would silently disable the other.

The domestic rail behind the buying seam is **Payme** (`DECISIONS.md` **D11**, specified in
`PAYME_INTEGRATION`), and it makes this a **four-process** system, because Payme's Merchant
API is *inbound*: its methods are calls Payme makes against a server we write.

| Process | Holds | Faces |
|---|---|---|
| `bayram.main` | the Telegram token and three vendor keys | outbound only — long polling, nothing inbound |
| `arq bayram.worker` | the same four | outbound only |
| `bayram.admin.app` | **no vendor credential at all** | an operator's browser, behind a login |
| `bayram.payme.app` | one secret: the Payme cashbox key | **the public internet, unauthenticated** |

The gateway is a fourth container rather than a route on the panel because its one credential
is a different *kind* of credential — an inbound verification secret whose theft mints
credits, rather than an outbound one that lets somebody spend our vendor balance. It holds no
Telegram token, which is why telling a customer their payment landed is an ARQ job the worker
performs. `CheckoutProvider.charge` itself **opens no socket**: Payme has no create-payment-link
API for the standard checkout, so a checkout link is base64 of a `;`-joined string.

**All of it ships switched off.** `BAYRAM_CHECKOUT_PROVIDER` defaults to `stub` and
`BAYRAM_PAYME_ENABLED` to `false`, so the stub rail is still what runs: still constructed at the
composition root, still wired into `BotDeps`, still under test.

---

## The name subsystem

No music model on earth supports IPA, SSML `<phoneme>`, lexicons or stress marks.
Pronunciation control is not a vendor feature, so we assemble one:

1. **Canonicalise.** Uzbek Latin `oʻ`/`gʻ` correctly use **U+02BB MODIFIER LETTER TURNED
   COMMA**. Real input arrives as U+2018, U+0027, U+0060, U+00B4 or U+2019. All of them
   fold to the canonical form.
2. **Emit ranked candidates.** Canonical, U+02BB-stripped, ASCII apostrophe, Cyrillic
   transliteration, syllable-hyphenated, phonetic respelling. **The ranking is
   configuration** — `BAYRAM_NAME_CANDIDATE_ORDER`, default
   `stripped,canonical,hyphenated,ascii,phonetic`. A bake-off result is applied by
   reordering that variable, never by editing code.
3. **Isolate the name.** It gets its own ~8 s chunk (`Chunk.is_name_chunk`), so a
   re-render costs one chunk, not one track.
4. **Close the loop acoustically.** The rendered name chunk goes through STT and is
   compared to the intended name after normalisation. A mismatch silently re-rolls that
   chunk with the *next* candidate before the customer hears anything. Retries are bounded
   by `BAYRAM_NAME_VERIFICATION_MAX_ATTEMPTS`; when they run out we deliver anyway.
5. **Never conflate display with submitted.** `RecipientName.display` is perfect U+02BB
   and is the only form a human ever sees. `NameCandidate.text` is what we post to a
   vendor and is internal. Two values, two fields, no exceptions.

Two notes that cost real money to learn: Uzbek stress falls on the **final** syllable, and
Russian needs `ё` preserved (Алёна /ɐˈlʲɵnə/, not Алена). Capitalising for stress does
**not** work in music models — ALL CAPS means louder, not stressed. Do not implement it.

---

## Conventions every module follows

- **Immutability.** Frozen models, tuples, `.model_copy()` / `with_*()` helpers. Nothing
  mutates an input.
- **`Result` at every boundary.** Protocol methods return `Ok`/`Err` and never raise.
  Exceptions are caught inside the adapter that owns the boundary.
- **LLM JSON.** Request the provider's structured mode, *then still* defend the parse:
  strip fences → parse → repair → validate against a pydantic model → return `Result`. Log
  the raw payload, finish reason and parse error on failure.
- **Small files.** 200–400 lines typical, 800 hard max. Functions under 50 lines.
- **Tests alongside code**, AAA structure, 80% coverage of your own module, and no unit
  test may need network, Redis, Postgres or ffmpeg. `tests/conftest.py` has the shared
  factories.

## Known gaps

Honest list, so nobody rediscovers these under pressure.

- **Object storage is filesystem-only.** `LocalFileStorage` archives to `./var/archive`
  and its `signed_url` returns a `file://` URL, because this backend has no credential to
  sign with. The S3/R2 settings that used to sit in `.env.example` were read by nothing and
  have been removed; the backend that replaces `LocalFileStorage` behind the same protocol
  brings its own configuration back with it.
- **Two i18n systems exist.** `bayram.bot.i18n` (Python catalogues, four locales, complete,
  used by every screen) and `bayram.i18n` (JSON catalogues, CLDR plurals, strict mode, also
  complete). Their key sets have diverged. The bot's is the shipped copy deck; converging
  them is a single-seam change in `bayram/bot/i18n.py::translate` plus a copy migration, and
  it was too large to do safely as part of integration.
- **Two content writers exist.** `bayram.pipeline.content.LlmContentWriter` (what the
  orchestrator actually uses) and `bayram.providers.llm.writer.write_kit` (a one-shot
  lyrics + scripts + respellings call). Both are tested; only the first is wired.
- **`bayram.pipeline.worker.generate_kit` is superseded.** It runs the pipeline but does not
  deliver. The shipped job is `bayram.runtime.jobs.generate_and_deliver`. Wiring a worker to
  the old one would generate kits that never reach a customer.
- **Rate limiting and the free-tier caps are not enforced**, and their settings are gone.
  `BAYRAM_MAX_ORDERS_PER_USER_PER_DAY` and the four `BAYRAM_FREE_*` knobs were read by nothing, so
  they were removed rather than left looking load-bearing. Enforcement needs
  `KitRepository.list_orders_for_user` in `BotDeps`, and adds its own config back.
  The one exception is `bayram.bot.handlers.lyrics.MAX_LYRIC_WRITES`: the lyric preview bills an
  LLM *before* the payment gate, so a per-session cap on how many lyrics one wizard may ask
  for lives in the draft. It is a spend cap, not a rate limiter, and it does not survive a
  `/start`. Neither it nor the daily budget applies on the bring-your-own-lyrics path, which
  is not an omission: that path makes no vendor call to cap.
- **Retention is a policy object, not configuration.** `RetentionPolicy` in
  `db/retention.py` owns the six periods as dataclass defaults, and `purge_expired` uses
  them. The `BAYRAM_RETENTION_*` settings duplicated those numbers and were wired to nothing —
  the config block even claimed "the purge job reads these" — so they were removed. Making
  them operator-tunable means building the settings-to-policy bridge that never existed.
- **In fake mode the audio is digital silence**, so the silence-trim pass removes
  everything and loudness normalisation degrades to shipping the raw render — the
  documented degradation path, visible as a warning in `make demo`. The real loudnorm
  passes are covered by the 22 ffmpeg integration tests.
- **Inpainting does not fire on this account, and fails SILENTLY.** Settled against the
  live API on 2026-08-28. The stored-song id guess was right: `SONG_ID_HEADERS` captures it
  (`store_for_inpainting: true` returned `song-id`, and the re-roll path has a real handle).
  The *shape* of the inpaint request was wrong. Eleven Music does not take a top-level
  `source_song_id` + `chunk_index`; unchanged sections are expressed as **audio-reference
  chunks** inside the plan — `{"song_id": ..., "range": {"start_ms": ..., "end_ms": ...}}` —
  mixed with the one generation chunk being re-rendered. `conditioning_ref` is that same
  object, not a string, and `condition_strength` is `low|medium|high|xhigh`, not a float.
  **Both the old shape and the documented shape return 200 and regenerate the whole track**,
  because `POST /v1/music` ignores fields it does not honour and inpainting is reportedly
  enterprise-gated. So a name re-roll currently costs a full render *and* returns a
  different song, rather than one patched chunk. The request shape itself is now correct:
  `payload.build_inpaint_body` emits audio-reference chunks and `Chunk.conditioning_ref` /
  `Chunk.condition_strength` carry the documented types, so the day inpainting is enabled
  on the account it should start working without a code change.

---

## Out of scope for this build

Referral and share pages, retention reminders, voice cloning, B2B.

Payment used to be on this list and is not any more: the checkout, the credit ledger and the
Payme rail are all built. What is deliberately **not** built, and is a decision rather than a
gap, is any post-perform reversal — `CancelTransaction` on a performed transaction answers
`-31007` unconditionally, and a refund is a cabinet action plus an operator credit correction
(`PAYME_INTEGRATION` §6). Also out: fiscalisation (`SetFiscalData`), Payme's Subscribe API,
and Telegram Stars, which remains the named fallback rail and is not implemented.

The admin panel used to be on this list and is not any more: `make admin` serves it today.
It is **read-only** in this build — no reveal, no retry, no purge, no config commit — so
treat the absent write surface as the scope note, not the panel itself.

## Reference documents

Everything that is not this file lives under [`docs/`](docs/README.md), which has its own
index. The three that explain *why the product is shaped this way*:

| Document | What it settles |
| --- | --- |
| [`docs/product/SCOPE_OF_WORK.md`](docs/product/SCOPE_OF_WORK.md) | §4 functional requirements, §6 architecture |
| [`docs/decisions/DECISIONS.md`](docs/decisions/DECISIONS.md) | Vendor picks, their named fallbacks, and the trigger that switches to each |
| [`docs/research/BENCHMARK-song-generation.md`](docs/research/BENCHMARK-song-generation.md) | Why ElevenLabs won, and which `DECISIONS.md` claims it corrects |
| [`docs/product/PAYME_INTEGRATION.md`](docs/product/PAYME_INTEGRATION.md) | The Payme rail: the two seams, both state machines, the one commit that makes fulfilment exactly-once, and the go-live sequence |

Deploying, or debugging a live problem, starts at
[`docs/deployment/README.md`](docs/deployment/README.md).
