# Bayram Admin Panel — Implementation Plan (final, post-review)

> **Status.** This is the settled plan. It supersedes the pre-review draft. Every claim about
> the existing codebase in this document was checked against the working tree at
> `feat/live-vendor-integration`; where the draft was wrong, the correction is stated inline
> and summarised in §17. Section 14 is the section to act on.

---

## 1. What this is and why

bayram-bot generates personalised birthday songs. Today it runs as two host processes — an aiogram bot
(`python -m bayram.main`) and an ARQ worker (`python -m arq bayram.worker.WorkerSettings`) — against
Postgres and Redis, with no HTTP surface of any kind. Operating it means `psql`, `redis-cli`, and
reading JSON logs. There is no way to see why an order failed, no way to retry it, no way to read
what a customer actually typed, no way to change `BAYRAM_NAME_CANDIDATE_ORDER` without a redeploy, and
no way to erase one person's data on request.

This plan adds a third process: a FastAPI JSON API (`src/bayram/admin/`) and a React/Vite SPA served
from the same origin. It gives the team four powers — read everything, act on orders and users, edit
runtime config without a redeploy, and moderate flagged content before generation — plus a chat log
so a conversation can be read end to end.

The panel inverts the product's central privacy decision, and every control here exists to bound
that. The bot was built so a recipient's name lives 90 days, a note lives 30, audio lives 30/365,
and `/privacy` renders those numbers from a retention policy at call time so the notice cannot drift
from the code. An admin panel plus a chat log makes that data more available, for longer, to more
people, on a clock nobody has declared yet. So: masked by default, audited reveal counted in
**records not clicks**, hard retention on every new table that holds a word of customer text, real
per-user erasure executed by the process that owns the writable volume, and an append-only,
HMAC-chained audit log that outlives the data it records.

**One correction the review forced, and it changes the shape of the whole thing.** The draft claimed
`/privacy` "renders from `DEFAULT_RETENTION_POLICY` at call time so the notice cannot drift". That
is true today only by accident: `handle_privacy` (`bot/handlers/commands.py:91`) reads the
module-level constant `DEFAULT_RETENTION_POLICY`, **not** `resolve_retention_policy(deps.settings)`,
and it is accurate only because `Settings` carries no `retention_*` fields, so
`resolve_retention_policy` always returns the defaults (`db/retention.py:120-137`). The moment this
plan adds those fields (Phase 3), the purge job honours the operator's policy while `/privacy` keeps
printing the compiled-in numbers in four languages. **Fixing `handle_privacy` to render from the
resolved policy ships in the same PR as the `retention_*` fields, and no `retention_*` field enters
the live-editable allowlist until it has.** That is Phase 3 work, not Phase 7 work.

---

## 2. Decisions already fixed

These are settled. They are stated here as constraints on the work, not as options.

| # | Decision |
|---|---|
| D1 | **Stack.** FastAPI JSON API as a new package in this repo (`src/bayram/admin/`) + a separate React/Vite SPA (Tailwind + shadcn/ui) in `admin-ui/`, built into `src/bayram/admin/static/` and served same-origin by the API. |
| D2 | **Visuals.** Modern, vibrant, attention-grabbing dark-first operator console. Saturated accents, dense data, live-feeling motion. Explicitly not a generic CRUD skin. |
| D3 | **Power 1 — read everything.** Users, orders, briefs, generation attempts, assets with inline audio playback, cost, latency, failure codes, name-verification outcomes. |
| D4 | **Power 2 — operational actions.** Retry a failed order, re-enqueue a job, block/unblock a user, purge a user's personal data, force-deliver a kit. Requires an audit-log table. |
| D5 | **Power 3 — runtime config.** Change settings from the UI without a redeploy. Requires a settings-override table and an overlay layer over the frozen pydantic `Settings`. |
| D6 | **Power 4 — manual moderation.** Review flagged briefs and lyrics, approve or reject before generation. |
| D7 | **Chat.** Build it. New `chat_messages` table + aiogram middleware capture. Retention and privacy rules must match the existing identity/note/abandoned-draft expiry model. |
| D8 | **Auth.** Username + password, argon2-hashed, in a new `admin_users` table, session-based. Not Telegram login. |
| D9 | **Payments.** No real payment rail. `NoopPaymentProvider` stays. Add a `payments` ledger table that the **existing** `PaymentProvider` seam writes to, so history is real and a rail drops in later untouched. |
| **D10** | **The admin process holds no vendor credential and no bot token.** It loads a *separate* `AdminSettings` model, not `Settings`. This is new, and §4 and §12 depend on it being true rather than aspirational. |
| **D11** | **The admin process's data volume is read-only.** Every deletion of a file — retention sweep, user purge — is an ARQ job executed by the worker, which owns the writable volume. |
| **D12** | **Deployment uses two Postgres roles**: a migration/owner role and a restricted application role. Without it the audit log's immutability claim is theatre, and the plan says so rather than shipping the theatre. |

Repo constraints that bind every line of this plan (each verified against the working tree):

- Python 3.12 only. `mypy --strict` over `src` **and** `tests`. ruff with `ASYNC` and `TRY` enabled,
  line length 100. Coverage `fail_under = 80` over `src/bayram`, branch coverage.
- Files under 800 lines (200–400 typical), functions under 50, immutable patterns, no silently
  swallowed errors. Errors flow as `Result[T]` from `bayram.contracts`, never as exceptions across a
  boundary.
- Tests run on SQLite in-memory (`container.py:_create_schema` → `Base.metadata.create_all`;
  `db/engine.py` `SQLITE_MEMORY_URL`); production is Postgres. No native DB enums (`enum_type(E)` →
  `VARCHAR(32)`). No naive datetimes — `UtcDateTime.process_bind_param` raises `ValueError` on one,
  and that `ValueError` is **not** caught by `run_guarded`.
- **SQLite does not autoincrement a `BIGINT` primary key.** Only a column declared exactly
  `INTEGER PRIMARY KEY` is a ROWID alias. Every autoincrement PK in this plan is therefore
  `sa.BigInteger().with_variant(sa.Integer, "sqlite")` — in the model *and* in the migration.
- Alembic migrations are hand-written, `render_as_batch=True`, `batch_alter_table` throughout,
  `sa.DateTime(timezone=True)` in migration files (never `UtcDateTime`), constraint names from
  `NAMING_CONVENTION` in `src/bayram/db/base.py:41-47`.
- `tests/test_db/test_privacy_constraints.py` scans live metadata **and every migration file** for
  year-shaped columns and fails the build. Nothing here adds one. Its
  `tables_with_personal_data` set is **hardcoded** (`:149`) and every new table holding customer text
  must be added to it in the same PR.
- `tests/test_db/test_migrations.py` asserts `set(_schema_of(url)) == set(_EXPECTED_TABLES)` (`:224`,
  `:270`) against a hardcoded six-table frozenset (`:61-63`), and asserts the migrated schema equals
  `Base.metadata` column-for-column (`:228-243`). **Every migration in this plan breaks these three
  tests unless the same commit updates the file.** §14 lists it as a Modified file in every phase
  that ships DDL.
- Rule 15 (`src/bayram/db/__init__.py:3-6`): no `*Row` class is imported outside `bayram.db`. Admin queries
  live inside the DB package and return frozen pydantic view models.
- `ENUM_LENGTH = 32` (`db/base.py:52`) with a comment asserting "the longest is 17 characters". Two
  `AuditAction` values in this plan are longer than 17 (still well under 32). The comment is updated
  and a test now pins the invariant across every enum passed to `enum_type()` — SQLite does not
  enforce `VARCHAR` length and Postgres does, which is exactly the divergence the portability rules
  exist to prevent.

---

## 3. What exists today vs what we add

| Capability | Exists today | What we add |
|---|---|---|
| HTTP surface | Nothing. No fastapi/starlette/aiohttp in `pyproject.toml` | `src/bayram/admin/` FastAPI app; third process `make admin` on `127.0.0.1:8080` |
| Admin settings | Nothing — every process calls `load_settings()`, which requires `BAYRAM_TELEGRAM_BOT_TOKEN`, `BAYRAM_ELEVENLABS_API_KEY` and `BAYRAM_LLM_API_KEY` (`config.py:83`, `:90`, `:118`, all `Field(min_length=1)`) | `AdminSettings` in `src/bayram/admin/settings.py`: `database_url`, `redis_url`, `environment`, `log_level`, `is_debug` and the `BAYRAM_ADMIN_*` block. **No vendor field exists on it**, so a missing key is not an error and a present key is not read |
| Admin auth | Nothing | `admin_users` + `admin_sessions`, argon2id, opaque server-side session cookie, 4 roles, action-scoped step-up re-auth |
| Order read | `get_order`, `list_orders_for_user(limit≤100)` only. Both go through `to_order` → **raises `PipelineError` when `recipient_name_display IS NULL`** (`db/mapping.py:137-147`) | `bayram/db/admin/orders.py` querying `OrderRow` directly, modelling "identity purged" as a first-class state; filters by state/paid/date/correlation; keyset pagination |
| User read/write | `UserRow` is written only by `_ensure_user`, which is called **only from `_create_order`** (`repository.py:130`), and **read by nothing**. `users.is_blocked` has no reader and no writer. `users.last_seen_at` is therefore "last order created", not "last seen" | Full user list/detail, block/unblock (plus the `BlockGateMiddleware` that makes blocking mean something), per-user data inventory, **and an inbound upsert so a user who never confirms an order still has a row to block and a truthful `last_seen_at`** |
| Generation history | `generation_attempts` exists, but the only production writer is `_replace_verdicts` (`repository.py:345`), which deletes and re-inserts `kind='name_verification'` rows from `verdict_row_values` (`attempts.py:113-127`) with `provider=None` and no cost or latency. `GenerationAttemptRepository.record()` has **zero call sites in `src/`** | Wire `record()` into 4 pipeline sites and extend `NameVerdict` so verification cost/latency survives `_replace_verdicts` (Phase 5). Until then the UI shows an explicit "not instrumented" state, never `$0.00` |
| Cost / latency | `cost_usd` is always `0.0`, `latency_ms` always `0`. LLM token spend is unaccounted anywhere. STT cost has no field at all | Persisted per-call cost/latency/provider (Phase 5) + dashboards gated on a `capabilities.costTelemetry` flag |
| `orders.failed_reason` | Column exists, **never written**. Writing it needs a `KitRepository` protocol change — `set_order_state(order_id, state, *, now)` (`contracts.py:827-829`) has no reason parameter | Protocol + `SqlKitRepository` + every test double updated; `orchestrator._fail` writes it; surfaced in the failure breakdown |
| Assets | `assets.size_bytes` always 0, `storage_key` always NULL, `tg_file_id` always NULL. `_purge_assets` filters `if key` (`purge.py:194`) and therefore returns an **empty** `storage_keys` tuple forever | Write `storage_key` in `_replace_assets`; a `Storage.open_range` public seam; confined range-capable streaming; no storage-size column anywhere (it would be a lie) |
| Storage cleanup | `purge_expired` returns `storage_keys` for the **caller** to delete (`purge.py:52-58`, `:189-204`) and **nothing calls it**, so nothing deletes them | The purge cron job iterates `report.storage_keys` and calls `storage.delete(key)`, recording `storage_keys_deleted` |
| Chat / message log | **Nothing.** No message is stored anywhere | `chat_messages` + inbound outer middleware + outbound session middleware on **both** `Bot` instances |
| Retention execution | `purge_expired` exists and is **called by nothing**. `WorkerSettings` registers one function and no `cron_jobs`. The retention job is not running | ARQ `cron_jobs` hourly entry + storage deletion + a `purge_runs` record + panel view. Two new sweeps for chat, one for audit reasons, one for audit rows |
| `has_work_remaining` | `total_rows_affected > 0` (`purge.py:113-115`) — true whenever the sweep did *any* work, false the instant nothing was due. It does not mean what its docstring says | Compare each per-sweep count against `batch_size`; the panel drives its "run again" affordance from a server-side `rowsPastExpiry` count |
| Per-user erasure | `/forget` clears the FSM draft only; its docstring says so explicitly, and it deliberately re-parks `Wizard.submitting` for an in-flight order because `privacy.forgotten` promises the queued song survives | `purge_user()` in `bayram/db/purge.py` with `exclude_order_ids`, executed by an ARQ job, wired to both `/forget` (scoped, in-flight-safe) and the panel |
| Runtime config | `Settings` is `frozen=True`; every consumer holds a direct reference. `get_settings()`'s `lru_cache` is dead code — the obstacle is pass-by-value | `SettingsHolder` indirection + `settings_overrides`/`settings_versions` in Postgres + Redis version pub/sub with a mandatory poll backstop |
| Retention config | `resolve_retention_policy` reads six `retention_*` attributes **that do not exist on `Settings`**, so defaults always apply | Add all eight `retention_*` fields with bounds, **and fix `/privacy` to render from the resolved policy in the same PR** |
| Moderation | Runs in the worker, after payment, after the lyric was already written. A rejection is a log line and an `Err`. Nothing records a flag | Pre-enqueue human gate only: `OrderState.HELD_FOR_REVIEW` + `moderation_reviews`, inserted between `submitter.submit`'s persist and its enqueue. **No in-pipeline soft-flag path** (§10.3) |
| Payments | `NoopPaymentProvider` always authorises, records nothing, 0 UZS. Every order is authorised **twice** (bot + worker) with different references | `LedgerPaymentProvider` decorator + `payments` table; two rows per order is the truth and the UI says so |
| Audit | Nothing | `admin_audit_log`, append-only, **HMAC**-chained, two-role `REVOKE` plus a `SECURITY DEFINER` sweep function shipped together |
| Correlation | One `correlation_id` already spans bot update → order row → worker job → delivery; `new_correlation_id()` produces 32 hex chars | Admin request middleware accepts `X-Correlation-ID` **only when it matches `^[0-9a-f]{32}$`**, and regenerates otherwise, so a forged id cannot be mistaken for a system one |

---

## 4. Architecture

```mermaid
graph TB
    subgraph browser["Operator's browser"]
        SPA["React/Vite SPA<br/>admin-ui/ → src/bayram/admin/static/<br/>same origin, cookie auth"]
    end

    subgraph host["Application host"]
        BOT["bayram.main — Settings<br/>aiogram bot<br/>+ chat-log capture<br/>+ user upsert + block gate<br/>+ settings watcher"]
        WORKER["arq bayram.worker.WorkerSettings — Settings<br/>generate_and_deliver<br/>+ purge cron (owns var/ RW)<br/>+ purge_user_data job<br/>+ notify_order_failed job<br/>+ chat-log capture (worker Bot)<br/>+ settings watcher"]
        API["bayram.admin.app — AdminSettings<br/>FastAPI + uvicorn 127.0.0.1:8080<br/>no ProviderSet, no Bot, no vendor keys<br/>pool 5+5 · var/ mounted :ro<br/>+ settings watcher"]
    end

    subgraph data["Data"]
        PG[("Postgres<br/>app role: INSERT/SELECT on audit<br/>owner role: migrations + audit sweep<br/>orders, briefs, assets,<br/>generation_attempts, users, name_records,<br/>+ admin_users, admin_sessions,<br/>admin_audit_log, audit_chain_anchors,<br/>chat_messages, purge_runs, payments,<br/>moderation_reviews,<br/>settings_versions/_overrides")]
        REDIS[("Redis<br/>FSM storage + isolation<br/>ARQ queue<br/>admin session mirror (TTL ≤ 60s)<br/>login throttle · reveal budget<br/>bayram:settings:version")]
        FS[["var/workspace/&lt;order_id&gt;/<br/>var/archive/orders/&lt;order_id&gt;/<br/>RW for worker · :ro for API"]]
    end

    TG["Telegram Bot API"]
    VENDOR["ElevenLabs music/TTS/STT<br/>LLM provider"]

    SPA -->|"/api/v1/** JSON, no-store, nosniff"| API
    SPA -->|"/assets/*, index.html"| API
    TG <-->|"long poll"| BOT
    WORKER -->|"send_audio / send_voice / edit"| TG
    WORKER --> VENDOR
    BOT -->|"enqueue generate_and_deliver"| REDIS
    API -->|"enqueue actions / DEL arq:result"| REDIS
    BOT --> PG
    WORKER --> PG
    WORKER -->|"read + write + delete"| FS
    API --> PG
    API --> REDIS
    API -.->|"read-only range stream via Storage.open_range"| FS
    API -->|"INCR + PUBLISH bayram:settings:version"| REDIS
    REDIS -.->|"version bump + 30s poll backstop"| BOT
    REDIS -.->|"version bump + 30s poll backstop"| WORKER

    style API fill:#7C5CFF,color:#fff
    style SPA fill:#22D3EE,color:#000
```

### 4.1 Why a separate process

The bot is a long-poll loop and the worker is an ARQ consumer; neither can host an HTTP server
without entangling its lifecycle with request handling. The codebase already runs two processes
against one database and the container is explicitly designed so both entry points build from *one*
`build_container` function "so they cannot drift" (`runtime/container.py:3-5`). The API becomes the
third caller of that same function, with three changes.

### 4.2 `AdminSettings` — the fix that makes the security story true

The draft asserted the admin process "boots without `BAYRAM_ELEVENLABS_API_KEY`" because
`with_providers=False` means no adapters are constructed. **That was false.** `with_providers`
governs `build_container`; `Settings` validation happens *before* `build_container` is ever called,
and `telegram_bot_token`, `elevenlabs_api_key` and `llm_api_key` are all `Field(min_length=1)` with
no default (`config.py:83`, `:90`, `:118`). `load_settings()` raises `ConfigError` without them. The
admin host would have had to carry the Telegram bot token and both vendor keys — meaning an
admin-host compromise yields full read/write on every customer chat in perpetuity, which is the
opposite of the stated blast radius.

The fix is a separate settings model, not a relaxation of the existing one:

```python
# src/bayram/admin/settings.py
class AdminSettings(BaseSettings):
    """Everything the admin process needs and nothing it must not hold.

    There is no vendor field on this model, so a leaked BAYRAM_ELEVENLABS_API_KEY in the
    admin host's environment is not merely unread — there is no code path that could read it.
    """
    model_config = SettingsConfigDict(
        env_prefix="BAYRAM_", env_file=".env.admin", extra="ignore", frozen=True,
    )
    database_url: str = Field(min_length=1)
    redis_url: str = Field(default="redis://localhost:6379/0")
    environment: str = Field(default="dev")
    log_level: Literal["CRITICAL", "ERROR", "WARNING", "INFO", "DEBUG"] = "INFO"
    is_debug: bool = False
    # -- BAYRAM_ADMIN_* block (see §8.6) --------------------------------------
    admin_enabled: bool = False
    admin_config_enabled: bool = True
    admin_bind_host: str = "127.0.0.1"
    admin_bind_port: int = Field(default=8080, ge=1, le=65535)
    admin_public_origin: str = Field(min_length=1)
    admin_cookie_secure: bool | None = None          # None = derive from environment
    admin_session_idle_minutes: int = Field(default=60, ge=5, le=480)
    admin_session_absolute_hours: int = Field(default=12, ge=1, le=24)
    admin_step_up_grace_seconds: int = Field(default=300, ge=0, le=900)
    admin_argon2_time_cost: int = Field(default=3, ge=2, le=10)
    admin_argon2_memory_kib: int = Field(default=65536, ge=32768, le=1048576)
    admin_argon2_parallelism: int = Field(default=4, ge=1, le=16)
    admin_trusted_proxy_hops: int = Field(default=0, ge=0, le=4)
    admin_trusted_proxies: str = Field(default="")   # comma-separated CIDRs
    admin_audit_hmac_key: str = Field(min_length=32)
    admin_audit_dsn: str = Field(default="")         # owner role; empty ⇒ no REVOKE, see §12.4
    admin_probe_token: str = Field(default="")
    admin_reveal_records_per_hour: int = Field(default=200, ge=10, le=2000)
    admin_reveal_conversations_per_day: int = Field(default=20, ge=1, le=200)
```

- `.env.admin` is a **separate file** so a shared `.env` cannot leak vendor keys into the admin
  process by accident. `.env.example` gains a matching `.env.admin.example`.
- **Boot assertion.** `bayram/admin/app.py`'s lifespan refuses to start when `environment == "prod"`
  and any of `BAYRAM_TELEGRAM_BOT_TOKEN`, `BAYRAM_ELEVENLABS_API_KEY`, `BAYRAM_LLM_API_KEY`,
  `BAYRAM_LLM_FALLBACK_API_KEY` is present in `os.environ`. In `dev`/`staging` it logs a WARNING
  naming the variable, because a shared dev `.env` is normal and a hard failure would push people
  to weaken the check.
- **Acceptance test.** `AdminSettings` constructs cleanly with `BAYRAM_TELEGRAM_BOT_TOKEN` and
  `BAYRAM_ELEVENLABS_API_KEY` unset, and `bayram.admin.app.create_app()` boots under the same conditions.

`build_container` still takes a `Settings`. The admin process does not build a full container; it
builds a **narrower** one, `build_admin_container(admin_settings)` in `src/bayram/admin/container.py`,
which creates only the engine, the session factory, the Redis client, a read-only
`LocalFileStorage(archive)` and the repositories. It shares `create_engine`/`create_session_factory`
with `runtime/container.py` so the pool and typing rules cannot drift, and it never touches
`ProviderSet`, `FfmpegAudioPostProcessor` or `Bot`.

### 4.3 What happens to `with_providers`

`with_providers: bool = True` still lands on `build_container`, because the **worker's own tests**
and the config-validation path benefit from a provider-free container, and because a future
co-located deployment may want it. Its type story is specified, not left implicit
(the draft left `providers: ProviderSet | None` to break `mypy --strict` at two sites):

- `AppContainer.providers: ProviderSet | None = None`.
- `aclose()` guards: `if self.providers is not None: await self.providers.aclose()`.
- `pipeline()` returns `Result[KitPipeline]`? No — it is called from one place and a `None` there is
  a programming error, not a runtime condition. It raises `PipelineError("container built without
  providers")` **immediately at the top of the method**, before any attribute access, so the failure
  names the cause instead of surfacing as `AttributeError: 'NoneType' object has no attribute
  'music'` at an unrelated await point.
- Test: `build_container(settings, with_providers=False).pipeline()` raises `PipelineError` with that
  message; `aclose()` on the same container succeeds.

### 4.4 Connection budget and the read-only volume

Pool overrides (`pool_size=5, max_overflow=5`) because three processes at the current defaults is
`3 × 30 = 90` Postgres connections against a default `max_connections` of 100. `create_engine` gains
`pool_size` and `max_overflow` keyword arguments with the current values as defaults.

The API mounts `var/` **read-only**. That is a path-traversal blast-radius control and it is
load-bearing: it means the API physically cannot delete a customer's song, which is why **every file
deletion in this plan is an ARQ job** (D11). The draft had the API both mount `:ro` and delete
workspace directories during `purge_user` — mutually exclusive, and the failure mode is the worst
possible one: the row deletions commit, the file deletions fail with `EROFS`, `purge_user` returns
`Err` (it must not raise), the failure becomes a log line, and the UI reports a completed purge while
the song is still on disk with the row that pointed at it gone.

### 4.5 Two Postgres roles

`docker-compose.yml` currently defines one role (`POSTGRES_USER: hbd`) and `migrations/env.py` reads
`BAYRAM_DATABASE_URL` through `bayram.config`, so migrations run as the application role — which is also
the table owner. Revoking privileges from a table's owner is reversible by that owner with one
`GRANT`. Phase 1 therefore ships:

- `BAYRAM_DB_MIGRATION_URL` (owner role, used by `migrations/env.py` when set, falling back to
  `BAYRAM_DATABASE_URL` so nothing breaks for existing dev setups).
- `BAYRAM_ADMIN_AUDIT_DSN` on `AdminSettings` — unused today except as the flag that says the two-role
  setup exists.
- `docker-compose.yml` gains an init script creating `hbd_app` and granting it everything except
  `UPDATE, DELETE, TRUNCATE` on `admin_audit_log`.
- A README "production shape" section stating the requirement.
- **If `BAYRAM_ADMIN_AUDIT_DSN` is empty, migration `0007` skips the `REVOKE` and logs a WARNING**, and
  `/audit/verify` reports `chainProtection: "hmac-only"` in its response. The panel shows that
  verbatim. A control that is not deployed is reported as not deployed, never implied.

Every operational action is an ARQ enqueue, never a direct Telegram send, which is what keeps the API
`Bot`-free and `telegram_bot_token`-free.

---

## 5. Data model changes

**Ten new tables** (the draft said seven and then referenced three more it never defined —
`purge_runs`, `audit_chain_anchors`, and the two settings tables were counted as one). All follow
`src/bayram/db/base.py` without exception: `sa.Uuid` PKs, `UtcDateTime` for every instant, `enum_type(E)`
for every enum, constraint names from `NAMING_CONVENTION`. Append-only tables declare `created_at` by
hand and do **not** use `TimestampMixin` (matching `AssetRow`, `GenerationAttemptRow`); mutable tables
use it.

**Two rules that apply to every table below.**

1. **Autoincrement integer PKs are `sa.BigInteger().with_variant(sa.Integer, "sqlite")`**, in the
   model and in the migration. SQLite only treats a column declared exactly `INTEGER PRIMARY KEY` as
   a ROWID alias; `sa.BigInteger` renders `BIGINT`, gets no implicit value, and every insert fails
   `NOT NULL` — in the unit suite, which is where the audit chain's tests live.
2. **Every table holding a word of customer text carries a retention clock and is added to
   `tables_with_personal_data` in `tests/test_db/test_privacy_constraints.py:149` in the same PR.**
   That set is hardcoded; a new table is silently exempt otherwise.

### 5.1 New enums — `src/bayram/db/enums.py`

```python
class AdminRole(StrEnum):        VIEWER="viewer"; SUPPORT="support"; OPERATOR="operator"; OWNER="owner"
class ChatDirection(StrEnum):    INBOUND="inbound"; OUTBOUND="outbound"
class ChatMessageKind(StrEnum):  TEXT="text"; CALLBACK="callback"; SCREEN="screen"; AUDIO="audio"
                                 VOICE="voice"; TOAST="toast"; EDIT="edit"; SYSTEM="system"
class PaymentStatus(StrEnum):    AUTHORIZED="authorized"; DECLINED="declined"; FAILED="failed"
class ModerationStatus(StrEnum): PENDING="pending"; APPROVED="approved"; REJECTED="rejected"
class PurgeTrigger(StrEnum):     CRON="cron"; MANUAL="manual"; USER_REQUEST="user_request"
class AuditReasonCode(StrEnum):  # §5.4 — the reason field is structured, not free text
    CUSTOMER_REQUEST="customer_request"; GDPR_ERASURE="gdpr_erasure"; ABUSE_REPORT="abuse_report"
    SUPPORT_INVESTIGATION="support_investigation"; INCIDENT="incident"
    BAKE_OFF="bake_off"; ROUTINE_OPS="routine_ops"; OTHER="other"
class AuditAction(StrEnum):      # closed taxonomy, §12.4
    LOGIN_SUCCESS="login.success"; LOGIN_FAILURE="login.failure"; LOGIN_RATE_LIMITED="login.limited"
    LOGOUT="logout"; STEP_UP_SUCCESS="step_up.success"; STEP_UP_FAILURE="step_up.failure"
    SESSION_REVOKED="session.revoked"; REVEAL_PERSONAL="reveal.personal"; ASSET_STREAM="asset.stream"
    ORDER_RETRY="order.retry"; ORDER_REENQUEUE="order.reenqueue"; ORDER_FORCE_DELIVER="order.deliver"
    ORDER_CANCEL="order.cancel"; USER_BLOCK="user.block"; USER_UNBLOCK="user.unblock"
    USER_PURGE_REQUESTED="user.purge.req"; USER_PURGE_COMPLETED="user.purge.done"
    USER_PURGE_FAILED="user.purge.fail"; MODERATION_APPROVE="moderation.approve"
    MODERATION_REJECT="moderation.reject"; CONFIG_VALIDATE="config.validate"
    CONFIG_COMMIT="config.commit"; CONFIG_ROLLBACK="config.rollback"
    RETENTION_EXTENDED="retention.extended"; RETENTION_RUN="retention.run"
    EXPORT_AGGREGATE="export.aggregate"; EXPORT_ORDER="export.order"; EXPORT_AUDIT="export.audit"
    ADMIN_CREATE="admin.create"; ADMIN_UPDATE_ROLE="admin.role"; ADMIN_DEACTIVATE="admin.deactivate"
    ADMIN_PASSWORD_CHANGE="admin.password"; PERMISSION_DENIED="permission.denied"
```

Values were shortened where the draft's were long (`retention.run_triggered` → `retention.run`,
`user.purge.requested` → `user.purge.req`) so that **every value is ≤ 20 characters**, comfortably
inside `ENUM_LENGTH = 32`. `db/base.py:52`'s comment is corrected from "the longest is 17 characters"
to state the real maximum across all enums, and a new test iterates every `StrEnum` passed to
`enum_type()` anywhere in `bayram.db` and asserts `max(len(m.value)) <= ENUM_LENGTH`. SQLite silently
accepts an over-length `VARCHAR` and Postgres errors; the test closes that divergence.

`OrderState` in `src/bayram/contracts.py` gains one member: `HELD_FOR_REVIEW = "held_for_review"`
(**15 characters**, not 16 as the draft claimed; the column is `VARCHAR(32)` either way — **no DDL
change**). It is declared after `LYRICS_READY` and before `AUTHORIZED`, so `_PAID_STATES` and the
`is_paid` latch (`repository.py:65-67`, `:184`) are untouched and the asset retention class is
unaffected.

### 5.2 `admin_users` — `src/bayram/db/models/admin_user.py`

| Column | Type | Null | Notes |
|---|---|---|---|
| `id` | `sa.Uuid` | NO | PK, `uuid4` |
| `username` | `String(64)` | NO | UNIQUE `uq_admin_users_username`; stored casefolded |
| `password_hash` | `String(256)` | NO | argon2id PHC string. Never leaves the process, at any role |
| `role` | `enum_type(AdminRole)` | NO | |
| `display_name` | `String(120)` | NO | default `""` |
| `is_active` | `Boolean` | NO | default `True`. Deactivate, never delete — audit rows FK here |
| `must_change_password` | `Boolean` | NO | default `False`; set by bootstrap and by an OWNER reset |
| `last_login_at` | `UtcDateTime` | YES | |
| `last_login_ip` | `String(45)` | YES | IPv6 max; the **derived** client IP (§12.1 T-proxy), not the peer |
| `failed_login_count` | `Integer` | NO | default 0; advisory only, the throttle lives in Redis |
| `password_changed_at` | `UtcDateTime` | NO | default `utc_now`; invalidates sessions issued before it |
| `created_at` / `updated_at` | `TimestampMixin` | NO | |

No personal data (an operator is staff, not a customer), so no retention clock and not in
`tables_with_personal_data`.

### 5.3 `admin_sessions` — `src/bayram/db/models/admin_session.py`

| Column | Type | Null | Notes |
|---|---|---|---|
| `id` | `sa.Uuid` | NO | PK |
| `admin_id` | `sa.Uuid` | NO | FK → `admin_users.id` `ON DELETE CASCADE`, index |
| `token_hash` | `String(64)` | NO | UNIQUE. **Only `sha256(token)` is stored** — a DB dump yields no usable session |
| `csrf_token` | `String(64)` | NO | The **server-side** value the `X-CSRF-Token` header is compared against (§12.1 T8) |
| `created_at` | `UtcDateTime` | NO | index |
| `last_seen_at` | `UtcDateTime` | NO | sliding idle window |
| `expires_at` | `UtcDateTime` | NO | absolute cap, index |
| `step_up_at` | `UtcDateTime` | YES | grace window start |
| `step_up_scope` | `String(64)` | YES | **the action class the step-up was granted for**, e.g. `reveal`, `order.deliver`, `user.block` |
| `step_up_subject_id` | `String(64)` | YES | the subject the step-up was granted for |
| `created_ip` / `last_ip` | `String(45)` | YES | derived client IP, recorded, **not enforced** — IP binding breaks mobile and pushes operators to weaken the control |
| `user_agent_hash` | `String(64)` | YES | sha256, not the UA string |
| `password_changed_at` | `UtcDateTime` | NO | snapshot; a mismatch against the row kills the session |

**Step-up is action-scoped, not session-scoped.** The draft modelled it as a single nullable
timestamp, which makes one reveal open a five-minute window over *every* step-up-gated action the
role can reach — for an OWNER that is `POST /users/{tg}/purge` and `POST /config/commit`. The one
control designed to survive session theft would then be the one that does not scope itself.
`require_step_up(action, subject_id)` compares `step_up_scope`, `step_up_subject_id` and
`step_up_at` within the grace. `USER_PURGE_*`, `CONFIG_COMMIT` and `CONFIG_ROLLBACK` require a
**fresh** step-up (grace treated as 0) regardless of any prior one.

**Redis mirror and its invalidation.** `bayram:admin:session:<sha256>` caches **only the
token → `admin_id` + `session_id` mapping**, TTL capped at 60 seconds regardless of session lifetime.
`is_active`, `role` and `password_changed_at` are read from Postgres on **every** request — those
three are exactly what makes revocation work, and caching them is what would make a revoked admin
keep access. Every revoke, deactivate, role change and password change issues
`DEL bayram:admin:session:<sha256>` for every affected session inside the same request. Postgres is the
record of truth and the revoke list. Tests: revoke-then-request → 401; deactivate-then-request → 401;
password-change-then-request-on-old-session → 401; each asserted **with the Redis mirror still warm**.

### 5.4 `admin_audit_log` — `src/bayram/db/models/admin_audit.py`

Append-only. Never updated; deleted only by the 730-day sweep, and `reason_text` nulled by a 90-day
sweep.

| Column | Type | Null | Notes |
|---|---|---|---|
| `seq` | `BigInteger().with_variant(Integer,"sqlite")` | NO | autoincrement PK — the hash chain and ordering depend on it |
| `id` | `sa.Uuid` | NO | UNIQUE, for external reference |
| `at` | `UtcDateTime` | NO | index |
| `actor_id` | `sa.Uuid` | YES | FK → `admin_users.id` **`ON DELETE RESTRICT`**; NULL only for `system` |
| `actor_username` | `String(64)` | NO | denormalised snapshot — a rename must not rewrite history |
| `actor_role` | `enum_type(AdminRole)` | NO | the role **at the time of the action** |
| `action` | `enum_type(AuditAction)` | NO | index |
| `subject_type` | `String(32)` | NO | `order`/`user`/`asset`/`chat`/`config`/`admin`/`session`/`wizard_draft` |
| `subject_id` | `String(64)` | YES | UUID string or telegram id. **Never a name** |
| `field_names` | `JSON` | YES | list of field **names** revealed or changed. Never values |
| `record_count` | `Integer` | YES | **how many records were exposed** — 1 for a name reveal, N for a conversation. This is what the reveal budget and the dashboard measure |
| `reason_code` | `enum_type(AuditReasonCode)` | NO | **structured**, closed taxonomy |
| `reason_ref` | `String(64)` | YES | ticket id etc., validated `^[A-Za-z0-9#_-]{1,64}$` |
| `reason_text` | `String(500)` | YES | optional free text, **on its own 90-day clock**, excluded from the hashed canonical form |
| `reason_expires_at` | `UtcDateTime` | YES | index; NULL when `reason_text` is NULL |
| `reason_purged_at` | `UtcDateTime` | YES | audit stamp |
| `outcome` | `String(16)` | NO | `ok`/`denied`/`error` |
| `error_code` | `String(48)` | YES | an `ErrorCode` or `AdminErrorCode` value |
| `correlation_id` | `String(128)` | YES | index — joins to bot and worker log lines |
| `ip` | `String(45)` | YES | derived client IP |
| `user_agent_hash` | `String(64)` | YES | |
| `config_version` | `Integer` | YES | for config actions |
| `expires_at` | `UtcDateTime` | NO | index — 730 days |
| `prev_hash` / `entry_hash` | `String(64)` | YES/NO | HMAC-SHA256 chain, §12.4 |

Indexes: `ix_admin_audit_log_at`, `ix_admin_audit_log_actor_id`, `ix_admin_audit_log_correlation_id`,
`ix_admin_audit_log_subject_id`, `ix_admin_audit_log_action_at`, `ix_admin_audit_log_reason_sweep`
(on `reason_expires_at`), `ix_admin_audit_log_expiry_sweep` (on `expires_at`).

**Why the reason is structured.** Every destructive action requires a reason, retained 730 days, in
the table `purge_user` deliberately does not touch and `REVOKE` makes undeletable. Real support
reasons read *"Dilnoza asked us to delete her mother's song"* — so the append-only, purge-immune,
longest-clock table in the system becomes the place customer names accumulate, and §12.4's rule
("never a personal-data value") is unenforceable against a free-text field. `reason_code` +
`reason_ref` carries the accountability; `reason_text` is optional, capped at 500 chars, **excluded
from the hash** so nulling it does not break the chain, and swept at 90 days by
`_purge_audit_reasons`. The same treatment applies to `moderation_reviews.decision_note` (§5.8) and
`settings_versions.reason_text` (§5.9). The UI's reason field is a select plus two optional inputs,
and the select is required.

`admin_audit_log` **is** added to `tables_with_personal_data` — `reason_text` can hold a customer's
name and the test must know that.

### 5.5 `audit_chain_anchors` — `src/bayram/db/models/audit_anchor.py`

Three rows a day at most; tiny. Exists so a swept prefix is not confused with tampering, and so the
chain head is recorded somewhere `/audit/verify` can compare against.

| Column | Type | Null | Notes |
|---|---|---|---|
| `id` | `BigInteger().with_variant(Integer,"sqlite")` | NO | autoincrement PK |
| `at` | `UtcDateTime` | NO | index |
| `kind` | `String(16)` | NO | `head` (periodic) or `truncation` (after a sweep) |
| `seq` | `BigInteger` | NO | the `seq` this anchor pins |
| `entry_hash` | `String(64)` | NO | the chain value at that `seq` |
| `rows_deleted` | `Integer` | YES | for `truncation` anchors |

Every anchor is **also emitted as a log line** (`audit chain anchor`, `extra={"seq":…,"hash":…}`), so
the chain head exists outside the database it protects. That log line is the minimum viable
out-of-band copy and it is required, not optional.

### 5.6 `purge_runs` — `src/bayram/db/models/purge_run.py`

The draft required this table in three places and defined it in none. It exists so `/retention` is
reading a record rather than scraping a log line, and so a sweep that silently does nothing is
visible.

| Column | Type | Null | Notes |
|---|---|---|---|
| `id` | `sa.Uuid` | NO | PK |
| `ran_at` | `UtcDateTime` | NO | index |
| `trigger` | `enum_type(PurgeTrigger)` | NO | |
| `triggered_by_username` | `String(64)` | YES | for `manual` |
| `duration_ms` | `Integer` | NO | |
| `assets_deleted` | `Integer` | NO | |
| `storage_keys_returned` | `Integer` | NO | |
| `storage_keys_deleted` | `Integer` | NO | **the number actually removed from disk** |
| `storage_delete_failures` | `Integer` | NO | |
| `brief_notes_purged`, `brief_identities_purged`, `attempt_identities_purged`, `attempt_transcripts_purged`, `name_records_deleted`, `abandoned_orders_deleted` | `Integer` | NO | mirror `PurgeReport` |
| `chat_bodies_purged`, `chat_messages_deleted` | `Integer` | NO | Phase 3 |
| `audit_reasons_purged`, `audit_rows_deleted` | `Integer` | NO | Phase 1 |
| `moderation_details_purged` | `Integer` | NO | Phase 6 |
| `is_batch_full` | `Boolean` | NO | **true when any sweep hit `batch_size`** — the real "run me again" signal |
| `error_code` | `String(48)` | YES | when the run returned `Err` |
| `created_at` | `UtcDateTime` | NO | |

`purge_runs` rows are kept 365 days and swept by the same job (`_purge_purge_runs`). They hold no
personal data — counts only.

### 5.7 `chat_messages` — `src/bayram/db/models/chat_message.py`

| Column | Type | Null | Notes |
|---|---|---|---|
| `id` | `sa.Uuid` | NO | PK |
| `telegram_user_id` | `BigInteger` | NO | index — the only reliable join key; a message can predate the `users` row |
| `chat_id` | `BigInteger` | NO | |
| `user_id` | `sa.Uuid` | YES | FK → `users.id` `ON DELETE SET NULL`, index |
| `order_id` | `sa.Uuid` | YES | index, **plain Uuid, NO foreign key** — the log predates the order and must outlive it |
| `session_id` | `String(32)` | YES | index; `WizardDraft.session_id`. Also the key the body-clock promotion updates on |
| `direction` | `enum_type(ChatDirection)` | NO | |
| `kind` | `enum_type(ChatMessageKind)` | NO | |
| `wizard_step` | `String(32)` | YES | from `states.step_for_state(raw_state)` at arrival |
| `telegram_message_id` | `BigInteger` | YES | NULL for toasts |
| `callback_data` | `String(64)` | YES | `nav:back`, `occ:birthday` — **not personal data**, survives the body clock |
| `parse_mode` | `String(16)` | YES | `HTML` for outbound; the double-escape guard |
| `body` | `String(4000)` | YES | **the personal-data column**; clipped by `truncate_chat_text` |
| `is_truncated` | `Boolean` | NO | default `False` |
| `is_from_worker` | `Boolean` | NO | default `False` — separates delivery sends from bot traffic |
| `media_group_id` | `String(32)` | YES | so an album is one artefact, not ten conversations |
| `error_code` | `String(48)` | YES | when the error guard swallowed a handler exception |
| `correlation_id` | `String(128)` | YES | index |
| `text_expires_at` | `UtcDateTime` | NO | index `ix_chat_messages_text_sweep` — **14 days, promoted to 30 on payment** |
| `body_purged_at` | `UtcDateTime` | YES | audit stamp |
| `expires_at` | `UtcDateTime` | NO | index `ix_chat_messages_expiry_sweep` — **90 days** |
| `created_at` | `UtcDateTime` | NO | index |

Composite index `ix_chat_messages_user_timeline` on `(telegram_user_id, created_at)` — the only query
the transcript runs. No `updated_at`.

**Three clocks, and the third one is the correction the review forced.**

- `body` is the personal-data column and takes the **strictest applicable** clock. A single message
  body can hold the recipient's name (90-day class), the note (30-day class) and the whole approved
  lyric (30-day class) in one indivisible string; there is no way to null "the identity part" of a
  rendered confirm summary.
- **For an abandoned session, 30 days is too long.** Today a wizard the customer abandons keeps the
  name, the note and the lyric for exactly **14 days**: the Redis FSM TTL (`WIZARD_STATE_TTL`,
  `bot/app.py:45`, sized to `abandoned_draft_days` precisely so "the two copies agree") and the DRAFT
  order deleted at 14 days by `_purge_abandoned_orders`. A chat log at 30 days would more than double
  that window and create a third copy on a clock nobody chose. So: **`text_expires_at` is stamped
  `created_at + abandoned_draft_days` (14) at insert.**
- **Promotion on payment.** When `ArqOrderSubmitter.submit` persists an order that reaches a paid
  state, it issues one indexed `UPDATE chat_messages SET text_expires_at = :promoted WHERE
  session_id = :sid AND text_expires_at < :promoted`, moving that session's bodies to
  `created_at + brief_text_days` (30) — the same clock as the `briefs` copy of the same words. A
  paying customer's support window matches their brief's; an abandoned session's does not outlive
  its draft.
- The metadata skeleton (direction, step, kind, timestamps, `callback_data`) carries no personal data
  and survives to `expires_at = created_at + chat_log_days` (90), when the row is deleted. That keeps
  the funnel view for a quarter without keeping a word of anyone's text past a month.

Test: advance the clock 15 days; an abandoned session's bodies are NULL and a paid session's are not.
Advance to 31; both are NULL. Advance to 91; the rows are gone.

`chat_messages` is added to `tables_with_personal_data`, and a test asserts both clock columns are
`NOT NULL` **with no server default**, so an insert that omits either fails.

### 5.8 `payments` — `src/bayram/db/models/payment.py`

| Column | Type | Null | Notes |
|---|---|---|---|
| `id` | `sa.Uuid` | NO | PK |
| `order_id` | `sa.Uuid` | NO | index, **no FK** — the bot authorises *before* the order row exists (`confirm.py:116` gates, `submitter.submit` persists) |
| `provider` | `String(32)` | NO | `PaymentProvider.name` |
| `reference` | `String(128)` | NO | index, **not unique** — a failed authorisation gets a synthetic reference |
| `amount_minor` | `BigInteger` | NO | |
| `currency` | `String(3)` | NO | |
| `status` | `enum_type(PaymentStatus)` | NO | index |
| `failure_code` | `String(48)` | YES | `ErrorCode` when `status='failed'` |
| `call_site` | `String(16)` | NO | `"bot"` or `"pipeline"` |
| `raw_payload` | `JSON` | YES | provider response, **passed through `bayram.logging.redact()`**; NULL for the no-op |
| `created_at` | `UtcDateTime` | NO | index; composite `ix_payments_order_id_created_at` |

**No unique constraint on `order_id`.** Every order is authorised twice — bot
(`confirm.py:198-215`, amount frozen at boot from `deps.amount_minor`) and worker
(`orchestrator.py:388-404`, amount read live). Two rows is the truth; `call_site` records which is
which. That dual lifetime is also exactly why pricing is off the config allowlist until the
`BotDeps` refactor lands (§8.4).

### 5.9 `moderation_reviews` — `src/bayram/db/models/moderation_review.py`

| Column | Type | Null | Notes |
|---|---|---|---|
| `id` | `sa.Uuid` | NO | PK |
| `order_id` | `sa.Uuid` | NO | FK → `orders.id` `ON DELETE CASCADE`, index |
| `status` | `enum_type(ModerationStatus)` | NO | index |
| `held_from_state` | `enum_type(OrderState)` | NO | the state to restore on approval (`lyrics_ready` in practice) |
| `flag_reason` | `String(64)` | YES | `manual_gate` / `denylist` / `llm_verdict` |
| `flag_pattern_index` | `Integer` | YES | **index into `LOCAL_DENY_PATTERNS`** — a constant, not customer text |
| `flag_hit_in` | `String(16)` | YES | `name`/`note`/`lyrics`/`unknown`, from `_hit_source` (`moderation.py:81`) |
| `flag_detail` | `String(500)` | YES | the matched substring (`_local_hit`, `moderation.py:73`, returns `match.group(0)`) or the LLM's `reason` truncated to `REJECTED_NOTE_LOG_CHARS = 200`. **This is customer text** |
| `decision_note` | `String(500)` | YES | operator free text |
| `text_expires_at` | `UtcDateTime` | NO | index — **`brief_text_days` (30)**; nulls `flag_detail` and `decision_note` |
| `text_purged_at` | `UtcDateTime` | YES | |
| `reviewer_id` | `sa.Uuid` | YES | FK → `admin_users.id` `ON DELETE SET NULL` |
| `reviewer_username` | `String(64)` | YES | snapshot |
| `decided_at` | `UtcDateTime` | YES | |
| `created_at` / `updated_at` | `TimestampMixin` | NO | |

Indexes: `ix_moderation_reviews_status_created_at`, `ix_moderation_reviews_order_id`,
`ix_moderation_reviews_text_sweep`.

**The draft claimed this table "carries no copy of the brief text" and used that to argue the
30/90-day sweeps remain the only copy governor. That was wrong** — `flag_detail` is by definition a
fragment of the customer's own note or lyric, and `decision_note` will paraphrase it. The table also
survives indefinitely, because `ON DELETE CASCADE` from `orders` only fires when an order is deleted
and orders are never deleted outside the DRAFT sweep. So it gets a real clock on the brief-text
schedule, a `_purge_moderation_details` sweep, an entry in `purge_user`'s null list, a row in §12.5's
retention summary, and membership in `tables_with_personal_data`. The **structural** flag data
(`flag_pattern_index`, `flag_hit_in`, `flag_reason`) is not customer text and survives, so the queue's
analytics still work after the sweep.

The reviewer UI reads the note, name and lyric **live from `briefs`**, so the brief sweeps remain the
governor for those. Not folded into `briefs` because `briefs` is subject to erasure on two clocks and
"a named operator approved this at this instant" must survive both.

### 5.10 `settings_versions` and `settings_overrides`

`settings_versions` — one immutable row per committed version:

| Column | Type | Null | Notes |
|---|---|---|---|
| `id` | `BigInteger().with_variant(Integer,"sqlite")` | NO | autoincrement PK |
| `version` | `Integer` | NO | UNIQUE |
| `parent_version` | `Integer` | YES | rollback provenance |
| `payload` | `JSON` | NO | the **complete** override set, not a delta — a rollback is a copy, never a replay |
| `created_by_id` | `sa.Uuid` | YES | FK → `admin_users.id` `ON DELETE SET NULL` |
| `created_by_username` | `String(64)` | NO | snapshot |
| `reason_code` | `enum_type(AuditReasonCode)` | NO | |
| `reason_ref` | `String(64)` | YES | |
| `reason_text` | `String(500)` | YES | 90-day clock, same as the audit log |
| `reason_expires_at` | `UtcDateTime` | YES | |
| `created_at` | `UtcDateTime` | NO | index |

`settings_overrides` — the current effective set, one row per key, for fast loads and per-key revert:

| Column | Type | Null | Notes |
|---|---|---|---|
| `id` | `sa.Uuid` | NO | PK |
| `key` | `String(64)` | NO | UNIQUE; the `Settings` field name, lowercase, no `BAYRAM_` prefix |
| `value` | `JSON` | NO | `{"v": <json>}` wrapper — `sa.JSON` without `none_as_null=True` persists `None` as the text `'null'` (the exact trap at `db/models/brief.py:88-96`), and `false`/`0` must be distinguishable from "unset" |
| `previous_value` | `JSON` | YES | same wrapper; powers per-key revert without touching the version table |
| `version` | `Integer` | NO | the version that last wrote this key |
| `set_by_id` / `set_by_username` | `sa.Uuid` / `String(64)` | YES / NO | |
| `note` | `String(256)` | NO | default `""` |
| `created_at` / `updated_at` | `TimestampMixin` | NO | |

**No `BAYRAM_ADMIN_*` key can ever appear in `settings_overrides`**, structurally: those fields live on
`AdminSettings`, not on `Settings`, and the override key space is `Settings.model_fields`. The
watcher additionally rejects any key not in `LIVE_EDITABLE_FIELDS`. See §8.6.

### 5.11 Changes to existing tables

| Table | Change | Why |
|---|---|---|
| `orders` | `+ chat_id BigInteger NULL`, `+ progress_message_id Integer NULL` | Both live only in ARQ job args and FSM data today. An admin retry has nowhere to send progress. Nullable forever — historical orders have neither. **Requires a `contracts.Order` change or a new repository method** (§14 Phase 4) |
| `orders` | Index `ix_orders_state_created_at`, `ix_orders_delivered_at` | Dashboard aggregates |
| `generation_attempts` | Indexes `ix_gen_attempts_kind_created_at`, `ix_gen_attempts_error_code_created_at`, `ix_gen_attempts_provider_created_at` | Failure breakdown, cost-by-provider |
| `users` | No DDL. **`last_seen_at` gets a real writer** (the inbound middleware upsert) and `is_blocked` gets a reader (`BlockGateMiddleware`) and a writer | Today `_ensure_user` is called only from `_create_order` (`repository.py:130`), so a user who browses the wizard and never confirms has no row at all — and those are exactly the users an operator wants to block. `UPDATE … WHERE telegram_user_id=:id` would match zero rows for them |
| `assets` | No DDL. **`_replace_assets` starts writing `storage_key`** (`repository.py:314-333`) | `_purge_assets` filters `if key` (`purge.py:194`), so with NULL keys it returns an empty tuple forever. Combined with the cron actually deleting the returned keys (§9), this is what makes archived bytes go away |
| `orders.failed_reason` | No DDL. **Starts being written** in `orchestrator._fail`, via a protocol change | The column is dead today; without it, orders that fail at validation or moderation contribute nothing to the failure breakdown |
| `NameVerdict` (`contracts.py`) | `+ provider: str \| None`, `+ cost_usd: float`, `+ cost_source: str \| None`, `+ latency_ms: int` | §5.12 |

### 5.12 The `_replace_verdicts` collision, and how it is resolved

The draft's Phase 5 instrumented `name_stage._hear` to write `NAME_VERIFICATION` attempt rows with
provider, cost and latency. **That could never have worked.** `_replace_verdicts`
(`repository.py:345`) runs on every `save_kit`, deletes every `kind='name_verification'` row for the
order, and re-inserts from `verdict_row_values` (`attempts.py:113-127`), which hardcodes
`provider=_VERDICT_PROVIDER = None` and writes no cost or latency at all. Every instrumented row
would be destroyed by the next `save_kit`, and every admin retry would repeat the wipe.

**Resolution: one writer, not two.** `_hear` does **not** call `record()`. Instead `NameVerdict`
carries the telemetry, and `verdict_row_values` persists it:

```python
# contracts.py — NameVerdict gains four fields, all defaulted so existing construction sites compile
provider: str | None = None
cost_usd: float = 0.0
cost_source: str | None = None
latency_ms: int = 0
```

`_hear` populates them from the STT call it already makes. `_replace_verdicts` keeps its
delete-then-insert shape (which is what makes replay idempotent) and now round-trips the telemetry.
Test: run the pipeline, `save_kit`, then `save_kit` again — `latency_ms` and `provider` survive both.

### 5.13 Migration order

Heads today are `0001 → 0006`. Each phase owns its migrations, so a phase can ship or be reverted
whole.

> **Amended: the entitlement work took `0006`, so every revision this section reserved from `0006`
> onwards moved up by one (`0006-0012` → `0007-0013`).** The credits change had to land a migration
> before any of the admin phases, and Alembic linearises whichever arrives first — but two branches
> each writing a `0006` merge into **two heads**, which fails
> `tests/test_db/test_migrations.py::test_exactly_one_migration_head_exists`. The renumbering is
> therefore part of that same commit rather than a follow-up, so no author is ever reading a stale
> reservation. `0005` is also narrower than reserved here: it shipped `admin_users` and
> `admin_sessions` only, and `purge_runs` still has no revision.

| Rev | File | Contents | Phase |
|---|---|---|---|
| `0005` | `..._0005_add_admin_users_sessions_and_purge_runs.py` | `admin_users`, `admin_sessions`, `purge_runs` | 1 |
| `0006` | `..._0006_add_credit_accounts_and_ledger.py` | `credit_accounts` (natural `telegram_user_id` PK, `balance >= 0` check) and the append-only `credit_ledger` + 5 indexes. **Not** the `payments` ledger below: `payments` records authorisation *calls* (two rows per order, §5.8), `credit_ledger` records entitlement *movement* (one net charge per order). Both decorate the same `PaymentProvider` seam and neither replaces the other | — (entitlements) |
| `0007` | `..._0007_add_admin_audit_log.py` | `admin_audit_log` + 7 indexes, `audit_chain_anchors`, and — **guarded on `dialect.name == "postgresql"` AND a non-empty `BAYRAM_ADMIN_AUDIT_DSN`** — the `REVOKE UPDATE, DELETE, TRUNCATE … FROM hbd_app` plus the `SECURITY DEFINER` function `hbd_purge_audit_log(cutoff timestamptz, lim int)` the sweep calls. The REVOKE and the function that works around it ship in **one** migration so neither can exist without the other | 1 |
| `0008` | `..._0008_add_admin_read_indexes.py` | The five read indexes on `orders` and `generation_attempts`. Docstring states it takes a brief table lock — milliseconds at current row counts | 1 |
| `0009` | `..._0009_add_chat_messages.py` | `chat_messages` + 3 indexes | 3 |
| `0010` | `..._0010_add_order_dispatch_columns.py` | `orders.chat_id`, `orders.progress_message_id` | 4 |
| `0011` | `..._0011_add_payments_ledger.py` | `payments` + 2 indexes | 5 |
| `0012` | `..._0012_add_moderation_reviews.py` | `moderation_reviews` + 3 indexes | 6 |
| `0013` | `..._0013_add_settings_versions_overrides.py` | `settings_versions`, `settings_overrides` | 7 |

Index names are hand-written where the convention would exceed Postgres's 63-char identifier limit —
the repo already does this (`ix_generation_attempts_tuning`).

**Every new model must be imported in `src/bayram/db/models/__init__.py:12-27`** or `Base.metadata` is
incomplete and both the SQLite `create_all` branch and Alembic autogenerate silently miss it.

**And every phase that ships DDL must update `tests/test_db/test_migrations.py` in the same commit.**
`_EXPECTED_TABLES` (`:61-63`) is a hardcoded six-table frozenset asserted with `==` at `:224` and
`:270`, and `test_the_migrated_schema_matches_the_model_metadata` (`:228-243`) compares the migrated
schema to `Base.metadata` column-for-column. Phase 1 alone would turn `make check` red for everyone,
including people working on the bot. Phase 1 restructures the file:

```python
#: Derived, so the set cannot drift from the models.
_EXPECTED_TABLES: Final[frozenset[str]] = frozenset(Base.metadata.tables)
#: The pre-admin core, pinned by name. A migration that drops one of these is a regression.
_CORE_TABLES: Final[frozenset[str]] = frozenset(
    {"users", "orders", "briefs", "assets", "name_records", "generation_attempts"}
)
```
with `assert _CORE_TABLES <= set(_schema_of(url))` kept as the explicit guard. Later phases then need
no change to this file at all — which is the point.

---

## 6. Backend API

Base path `/api/v1`. JSON in, JSON out, `Cache-Control: no-store` **and
`X-Content-Type-Options: nosniff`** on every response. Roles: **V**iewer, **S**upport, **O**perator,
**W**=Owner. Each role reaches everything the roles to its left reach. `+S` means step-up re-auth
required, scoped to that action.

### 6.1 Conventions

- **Keyset pagination everywhere**: `?cursor=<opaque>&limit=` (1–200, default 50). Cursor is
  `base64url({"at": <iso>, "id": <uuid>})` applied as `(created_at, id) < (at, id)` with
  `ORDER BY created_at DESC, id DESC`. Response carries `meta.nextCursor` (`null` at the end). A
  separate `?withTotal=true` runs `SELECT count(*) FROM (SELECT 1 FROM … LIMIT 10001) s` and returns
  `{total, isTotalExact}` so "10,000+" is honest. Offset was rejected: the repo's own rule 12
  ("bound every list query") and the `MAX_ORDER_HISTORY = 100` comment both argue against unbounded
  scans, and offset degrades on a growing `orders` table exactly where the panel is most used.
- **Filtering:** repeated params are OR within a field, AND across fields. Dates are ISO-8601 with an
  offset; a naive value is 422 (the DB layer would raise `ValueError` on it anyway, and `run_guarded`
  does not catch `ValueError`).
- **Sorting:** `?sort=-created_at`. Each resource declares an allowlist mapping to a `Column` object.
  Anything else is 422 — never string-interpolated into SQL.
- **One identifier per namespace.** Every `/users/**` route takes `{telegramUserId}` typed `int`.
  The draft mixed `{telegramUserId}` and `{id}` inside one table while `purge_user` takes
  `telegram_user_id` and the purge body carried `confirmTelegramUserId` — an ambiguity aimed at an
  irreversible OWNER purge, which is precisely how the wrong subject gets erased. The purge body
  re-echoes the same path value (`confirmTelegramUserId` must equal the path parameter) and the
  server asserts equality before any work. A route-enumeration assertion forbids two routes in one
  namespace using different parameter names for the same entity.
- **Correlation.** Every response carries `X-Correlation-ID`. An inbound `X-Correlation-ID` is
  accepted **only if it matches `^[0-9a-f]{32}$`** — the exact shape `new_correlation_id()` produces
  — and silently regenerated otherwise. An unvalidated client string is never written to
  `admin_audit_log.correlation_id` and never reflected into a response header; otherwise anyone with
  a session could forge the join key between their own audit rows and unrelated orders' log streams,
  poisoning the investigation surface the header exists for.

### 6.2 The error envelope, and the second taxonomy

The draft said it reuses "the existing closed `ErrorCode` taxonomy rather than inventing a second
one". It cannot: `ErrorCode` (`errors.py:52-77`) has no member for 401, 403 / step-up-required, 409
conflict, 415, 416 or CSRF rejection — and extending it is worse, because `BayramError` carries
`user_message_key` and the bot renders customer-facing copy from it
(`jobs.py:181 _tell_the_customer_why`), so an admin-only code would leak into a customer-facing
taxonomy.

**Decision: a disjoint `AdminErrorCode` StrEnum in `src/bayram/admin/errors.py`.** The envelope's `code`
carries the union.

```python
class AdminErrorCode(StrEnum):
    UNAUTHENTICATED = "UNAUTHENTICATED"        # 401
    FORBIDDEN = "FORBIDDEN"                    # 403
    STEP_UP_REQUIRED = "STEP_UP_REQUIRED"      # 403
    CSRF_REJECTED = "CSRF_REJECTED"            # 403
    ORIGIN_REJECTED = "ORIGIN_REJECTED"        # 403
    CONFLICT = "CONFLICT"                      # 409
    PRECONDITION_FAILED = "PRECONDITION_FAILED"# 409
    UNSUPPORTED_MEDIA_TYPE = "UNSUPPORTED_MEDIA_TYPE"  # 415
    RANGE_NOT_SATISFIABLE = "RANGE_NOT_SATISFIABLE"    # 416
    REVEAL_BUDGET_EXHAUSTED = "REVEAL_BUDGET_EXHAUSTED"# 429
    LOGIN_RATE_LIMITED = "LOGIN_RATE_LIMITED"  # 429
    CONFIG_FIELD_NOT_EDITABLE = "CONFIG_FIELD_NOT_EDITABLE"  # 422
    CAPABILITY_DISABLED = "CAPABILITY_DISABLED"# 409
```

A test asserts `set(AdminErrorCode) & set(ErrorCode) == set()`, and a second asserts no
`AdminErrorCode` value is ever passed to `bayram.bot.i18n.translate()` (the admin package does not import
it; the test enumerates imports to keep it that way).

```json
{"error": {"code": "STEP_UP_REQUIRED", "message": "re-enter your password to continue",
           "correlationId": "9f2c…", "details": {"scope": "user.purge"}}}
```

One `unwrap(result)` helper raises a `ProblemException` carrying either an `BayramError` or an
`AdminProblem`; one exception handler renders the envelope. No route writes `try/except` — which is
also what keeps ruff's `TRY` ruleset happy.

**Full status mapping.** `NOT_FOUND`→404 · `INVALID_INPUT`/`CONFIG_INVALID`/`CONFIG_FIELD_NOT_EDITABLE`→422 ·
`CONTENT_REJECTED`/`CONFLICT`/`PRECONDITION_FAILED`/`CAPABILITY_DISABLED`→409 ·
`RATE_LIMITED`/`LOGIN_RATE_LIMITED`/`REVEAL_BUDGET_EXHAUSTED`→429 · `QUOTA_EXHAUSTED`→402 ·
`UPSTREAM_*`→502 · `STORAGE_FAILED`→503 · `UNAUTHENTICATED`→401 ·
`FORBIDDEN`/`STEP_UP_REQUIRED`/`CSRF_REJECTED`/`ORIGIN_REJECTED`→403 ·
`UNSUPPORTED_MEDIA_TYPE`→415 · `RANGE_NOT_SATISFIABLE`→416 · everything else→500.

Every rendered message passes through `bayram.logging.redact()` and is capped at 300 characters before
it enters the body **or** the audit row — `_describe_failure` and `_candidates_must_be_unique`
(`config.py`) interpolate the submitted value into the message, and `/config/validate` is the one
endpoint whose entire purpose is accepting operator-supplied values.

### 6.3 Auth & health

| Method | Path | Purpose | Role |
|---|---|---|---|
| POST | `/auth/login` | `{username, password}` → session + CSRF cookies. Returns `mustChangePassword` | public |
| POST | `/auth/logout` | Delete the session row **and its Redis mirror** | V |
| GET | `/auth/me` | `{id, username, displayName, role, lastLoginAt, mustChangePassword}` | V |
| POST | `/auth/step-up` | `{password, scope, subjectId}` → grace for **that scope+subject only** | V |
| POST | `/auth/password` | Change own password; revokes own other sessions + their mirrors | V |
| GET | `/auth/sessions` | List own sessions | V |
| DELETE | `/auth/sessions/{id}` | Revoke own session | V |
| GET | `/healthz` | Liveness. **Bare 200, empty body. No DB, no Redis, no version** | public |
| GET | `/readyz` | `{status: "ok"\|"degraded"}` unauthenticated. Full detail — `{database, redis, configVersion, chatDropCount, chainProtection}` — **only** with a VIEWER session or a `X-Probe-Token` matching `admin_probe_token` under `compare_digest` | public/V |

`/readyz` was public with full detail in the draft. Behind the reverse proxy §16 assumes, that is
unauthenticated fleet telemetry: whether the panel is up, whether its database is reachable, and —
via `configVersion` — whether a just-committed change has landed. The route-enumeration test's exempt
set is now `{/healthz, /readyz, /auth/login}` where `/readyz` is exempt only for its degraded-status
branch.

### 6.4 Dashboard

| Method | Path | Purpose | Role |
|---|---|---|---|
| GET | `/ops/pulse` | **The entire dashboard in one query**: orders by state, in-flight, hourly buckets, queue depth, failure codes, moderation backlog, cost (or `null`), capabilities | V |
| GET | `/ops/feed?since=` | Recent order-state transitions + attempts, capped at 200 | V |
| GET | `/ops/capabilities` | `{costTelemetry, chatCapture, liveStream, moderationGate, configEditor, chainProtection, twoRoleAudit}` | V |
| GET | `/metrics/orders-by-day` | `[{day, total, delivered, failed, paid}]` | V |
| GET | `/metrics/failures` | `[{errorCode, count, share, isRetryable}]` | V |
| GET | `/metrics/latency` | p50/p95 `created_at → delivered_at` | V |
| GET | `/metrics/cost-by-provider` | `[{provider, kind, calls, costUsd, costSource, avgLatencyMs}]` | V |
| GET | `/metrics/name-strategies?from=&to=` | Per-strategy bake-off with a time window | V |
| GET | `/metrics/reveals?days=7` | Reveals **and revealed record counts** per actor — the R1 detection control | O |

### 6.5 Orders

| Method | Path | Purpose | Role |
|---|---|---|---|
| GET | `/orders` | List; filters `state[]`, `isPaid`, `telegramUserId`, `correlationId`, `errorCode[]`, `from`, `to`, `hasAssets` | V (masked) |
| GET | `/orders/{id}` | Order + brief (purge-aware) + `stagePlan` + gaps | V (masked) |
| GET | `/orders/{id}/attempts` | Generation attempts, filterable by kind/success | V |
| GET | `/orders/{id}/timeline` | Merged, time-ordered. **Response carries a `sources` array** naming which of `{stateTransitions, attempts, payments, chat, audit}` are actually available in this deployment, so the SPA renders "chat capture not enabled" rather than an empty section. `chat` appears from Phase 3, `payments` from Phase 5. `stateTransitions` is `inferred` until an order-event table exists — `orders` carries only `state`, `created_at`, `updated_at`, `delivered_at` (`db/models/order.py:40-59`) and the timeline says so | V |
| GET | `/orders/{id}/assets` | Asset metadata only | V |
| GET | `/orders/{id}/payments` | Ledger rows for this order | V |
| GET | `/orders/{id}/job` | ARQ job status + result TTL — the retry preflight | O |
| POST | `/orders/{id}/retry` | `{reasonCode, reasonRef?, reasonText?, jobIdStrategy, postFreshProgressMessage}` | O |
| POST | `/orders/{id}/reenqueue` | `{reasonCode, …}` | O |
| POST | `/orders/{id}/force-deliver` | `{reasonCode, …}` | O +S |
| POST | `/orders/{id}/cancel` | `{reasonCode, …}` | O |

### 6.6 Users

Every path parameter is `{telegramUserId}`, typed `int`.

| Method | Path | Purpose | Role |
|---|---|---|---|
| GET | `/users` | List; `telegramUserId`, `q`, `isBlocked`, `hasBalance`, `uiLanguage`, `from`, `to` | V (masked) |
| GET | `/users/stats` | The stat strip: `matched`, `reachable`, `blocked`, `botBlocked` over the **list's own filter set** — the same `segment_breakdown` `/segments/preview` runs, narrowed by the six chips, the window and `?segment=` instead of by a segment alone. Takes no `limit`, `cursor`, `sort` or `withTotal`: an aggregate cannot honour paging and `matched` **is** the total, exact rather than `TOTAL_COUNT_CAP`-bounded. Counts only — no id, no handle, no name, and not the `byLanguage` split the preview carries. A **literal** segment, so it is registered before `/users/{telegramUserId}` or it 422s on `int` coercion | V (counts only) |
| GET | `/users/{telegramUserId}` | Detail + order counts by state + first/last seen | V (masked) |
| GET | `/users/{telegramUserId}/orders` | Their orders | V |
| GET | `/users/{telegramUserId}/wizard-state` | **Projected** FSM read from Redis: step, session id, order in flight, and per-draft-key `{isPresent, charCount}` only | V (no plaintext at any role) |
| GET | `/users/{telegramUserId}/data-inventory` | What we hold and when each item expires (§12.5) | V |
| POST | `/users/{telegramUserId}/block` | `{reasonCode, …}` | O +S |
| POST | `/users/{telegramUserId}/unblock` | `{reasonCode, …}` | O +S |
| POST | `/users/{telegramUserId}/purge` | `{scope: identity\|text\|all, reasonCode, reasonRef?, confirmTelegramUserId, excludeInFlight}` → **enqueues** `purge_user_data`; returns `202` with the job id | W +S (fresh) |

**`/wizard-state` is a reveal surface and the draft did not treat it as one.** The FSM draft is, per
`build_storage` and `handle_forget`'s docstring, the copy that holds the recipient's display name,
the free-text note and the whole approved lyric — and for abandoned sessions it is the only copy that
ever exists. The endpoint returns a projection built from an **allowlist of key names** (never a
denylist, and never the raw Redis hash), and the plaintext is reachable only through `POST /reveal`
with `subjectType="wizard_draft"`. Test: the endpoint's JSON contains no substring of the fixture
draft's known plaintext, at any role.

### 6.7 Generations, assets, chat, payments, reveal

| Method | Path | Purpose | Role |
|---|---|---|---|
| GET | `/generations` | `kind[]`, `provider`, `isSuccess`, `errorCode`, `strategy`, `isOrphaned`, `from`, `to` | V |
| GET | `/generations/{id}` | One attempt | V |
| GET | `/assets` | `kind[]`, `retentionClass`, `expiringWithinDays` | V (metadata) |
| GET | `/assets/{id}` | Metadata: mime, `durationS`, `loudnessLufs`, sha256, `expiresAt`, `isFilePresent` | V |
| GET | `/assets/{id}/stream` | Range-capable **audio** stream. `nosniff` always; `Content-Disposition: attachment` for every non-audio mime | S +S, audited |
| GET | `/assets/{id}/text` | Lyric-sheet content as **`application/json`** (`{"text": …}`), never as a raw `text/plain` body | S +S, audited |
| GET | `/chat/conversations` | Threads: `telegramUserId`, last activity, counts, current step | V (metadata) |
| GET | `/chat/{telegramUserId}/messages` | Keyset transcript; `includeProgress=false`, `direction`, `sessionId` | V (bodies hidden) |
| POST | `/reveal` | `{subjectType, subjectId, fields[], reasonCode, reasonRef?, reasonText?, limit?, cursor?}` → plaintext for the named fields only, **at most 50 records per call** | S +S, audited, budgeted |
| GET | `/payments` | `orderId`, `status[]`, `callSite`, `from`, `to` | V |
| GET | `/payments/summary` | Authorised / declined / failed counts, amount total | V |

### 6.8 Moderation, config, retention, audit, admins, export

| Method | Path | Purpose | Role |
|---|---|---|---|
| GET | `/moderation` | Queue; `status[]` default `pending` | V (masked) |
| GET | `/moderation/{id}` | Full review context — the note, name and lyric as they stand | O, audited reveal |
| POST | `/moderation/{id}/approve` | `{reasonCode, decisionNote?}` → restore state + enqueue | O +S |
| POST | `/moderation/{id}/reject` | `{reasonCode, decisionNote}` → FAILED + notify job | O +S |
| GET | `/config` | Every field: key, effective, envValue, override, tier, type, constraints, description. **Secrets — including `database_url` and `redis_url` — are absent, not masked**; a derived `databaseHost` is returned instead | V |
| POST | `/config/validate` | Dry run of a change set; 422 with the offending `BAYRAM_*` name | W |
| POST | `/config/commit` | `{changes, reasonCode, …}` → new version, INCR + PUBLISH | W +S (fresh) |
| GET | `/config/versions` | History | V |
| POST | `/config/versions/{n}/rollback` | Insert a new version equal to `n` | W +S (fresh) |
| GET | `/retention` | Last `purge_runs` row, per-sweep counts, **server-computed `rowsPastExpiry` per sweep**, `isBatchFull` | V |
| POST | `/retention/run` | Enqueue a sweep now | O |
| GET | `/audit` | `actor`, `action[]`, `subjectType`, `subjectId`, `outcome`, `from`, `to` | O (masked) / W |
| GET | `/audit/verify` | Walk the HMAC chain, report the first break and `chainProtection` | O |
| GET | `/admins` | List | W |
| POST | `/admins` | `{username, password, role, displayName}` — sets `must_change_password` | W +S |
| PATCH | `/admins/{id}` | `{role?, isActive?, displayName?}` | W +S |
| POST | `/admins/{id}/reset-password` | Sets `must_change_password` | W +S |
| DELETE | `/admins/{id}/sessions` | Revoke another admin's sessions **and their mirrors** | W +S |
| GET | `/export/aggregate` | Counts and rollups. **No names, no free text, no telegram ids, no order ids.** CSV cells sanitised per §12.3 | O |
| GET | `/export/order/{id}` | Single-order evidence pack, **JSON only**, watermarked | W +S, 5/day |

**The one rule that governs every read endpoint:** admin queries hit `OrderRow`/`BriefRow` directly
with explicit `selectinload`, and **never** go through `to_order`/`to_brief`. Those raise
`PipelineError` when `recipient_name_display IS NULL` (`db/mapping.py:137-147`), so a page spanning
orders older than 90 days would `Err` the whole page. Every relationship is `lazy="raise"`; an
unnamed load is a greenlet error at an unrelated await point.

---

## 7. Chat logging

### 7.1 Where it hooks

Two hooks in three places, because **two processes hold two `Bot` instances writing into the same
chat**. A logger installed only in the bot process misses the song, all greetings, the lyric sheet,
the closing message, every progress edit and the terminal failure message.

| Hook | File | Registered | Sees |
|---|---|---|---|
| `ChatLogInboundMiddleware` | `src/bayram/bot/chatlog_inbound.py` | `dispatcher.update.outer_middleware(...)` in `build_dispatcher` (`bot/app.py:116-125`), **after** aiogram's three built-ins | Every inbound `Update`, once, before any filter, with `state`, `raw_state`, `event_context` and `deps` already in `data` |
| `ChatLogOutboundMiddleware` | `src/bayram/bot/chatlog_outbound.py` | `bot.session.middleware(...)` on the bot `Bot` (`main.py:101`) | Every outgoing Bot API call the bot makes, plus the returned `Message` |
| same class | | `bot.session.middleware(...)` on the worker `Bot` (`worker.py:56`) | `send_audio`, `send_voice`, lyric-sheet chunks, closing message, failure message |

The session request middleware is the only real outbound chokepoint: `message.answer()` and
`edit_text()` are `Bot` calls underneath, and there are 12 outbound call sites across 8 modules with
no send module to wrap.

**The inbound middleware also carries the `users` upsert.** `_ensure_user` is called only from
`_create_order` (`repository.py:130`), so a user who browses the wizard and never confirms has no
`users` row — and those are exactly the users an operator wants to block, and exactly the population
`UPDATE users SET is_blocked WHERE telegram_user_id` would silently match zero rows for. The
middleware therefore offers a `UserTouch` alongside the `ChatLineDraft`, and the same background
drain performs one upsert per (user, minute) — `telegram_user_id`, `ui_language`, `last_seen_at` —
so `last_seen_at` finally means "last seen" instead of "last order created". Rate-limiting the
upsert to one per minute per user is what keeps it off the hot path's write budget.

### 7.2 What it stores

**Inbound:** `direction=inbound`; `kind=TEXT` for a `Message` with text, `CALLBACK` for a
`CallbackQuery`; `body` = raw text **as typed**, never the rendered form; `callback_data` =
`nav:back` / `lang:ui:ru` / `occ:birthday`; `wizard_step` from `step_for_state(raw_state)`;
`session_id` and `order_id` from the FSM data dict; `media_group_id` when present; `correlation_id`
from `current_correlation_id()`.

Callback rows are not optional. Half the traffic is buttons and the information lives in
`callback.data`, not in text — a message-only log makes the entire wizard invisible.

**Outbound:** `kind` from the method (`sendMessage`/`editMessageText`→`SCREEN`, `sendAudio`→`AUDIO`,
`sendVoice`→`VOICE`, `answerCallbackQuery`→`TOAST`); `telegram_message_id` from the returned
`Message`; `parse_mode='HTML'`; `is_from_worker=True` on the worker instance. The outbound payload is
where a Telegram `file_id` first becomes observable — `assets.tg_file_id` (declared, never written,
documented as the FIL-4 re-send cost control) could finally be populated from here. That is a
separate change; the capture makes it possible.

**Deliberate exclusion — progress edits.** `TelegramProgressSink._push` (`bot/progress.py:169-199`)
edits one message id dozens of times per order. Logging each as a message makes one order look like
forty. The outbound middleware skips `editMessageText` whose `message_id` matches the order's
`progress_message_id`; the panel renders progress from `generation_attempts` and the order state
instead.

**HTML handling.** Every message goes out `parse_mode=HTML` and `translate()` escapes every
interpolated value (`bot/i18n.py:81-97`). We store the string **verbatim** with `parse_mode`
recorded. The SPA renders it as text (React default — `dangerouslySetInnerHTML` is banned by an
ESLint error rule), running a deterministic un-escaper only on `parse_mode='HTML'` rows. Store raw,
escape at render, or you double-escape.

**Truncation before insert, not after.** `truncate_chat_text` mirrors `truncate_transcript`
(`db/attempts.py:59-69`), which exists because a 700-char transcript killed a live, already-billed
order against a `VARCHAR(200)`. The lyric-preview screen quotes a 3000-char lyric plus chrome and
*will* exceed 4000; `is_truncated=True` is the design, not a failure.

### 7.3 Retention

Three sweeps, each with an explicit predicate.

```sql
-- _purge_chat_bodies: nulls the personal-data column, stamps the audit column.
WHERE text_expires_at <= :now AND body IS NOT NULL AND body_purged_at IS NULL
-- _purge_chat_messages: deletes the metadata skeleton.
WHERE expires_at <= :now
```

**The `body IS NOT NULL AND body_purged_at IS NULL` predicate is load-bearing.**
`_purge_brief_notes` (`purge.py:213-240`) has no such guard and its docstring explains why that is
only safe there: both text columns are nulled in one statement, so the `OR` predicate stops matching.
`_purge_chat_bodies` nulls one column and stamps another; written naively as
`WHERE text_expires_at <= :now` it would re-select every already-purged row on every hourly run
forever, permanently filling the batch and permanently reporting work remaining. Test: run twice, the
second run reports zero.

Both sweeps are added to the existing single-transaction sweep list in `src/bayram/db/purge.py:145-153`,
each `LIMIT batch_size`. `PurgeReport` gains `chat_bodies_purged` and `chat_messages_deleted` (and,
from Phase 1, `audit_reasons_purged`, `audit_rows_deleted`, `purge_runs_deleted`; from Phase 6,
`moderation_details_purged`).

`has_work_remaining` is **fixed** in the same Phase 1 commit as the cron. Today it is
`total_rows_affected > 0` (`purge.py:113-115`), which is true whenever the sweep did any work at all
and false the instant nothing was due — it does not mean what its docstring ("True when a sweep
filled its batch") says, and the panel would have shown "more work remaining" forever. It becomes
`any(count >= batch_size for count in per_sweep_counts)`, and `PurgeReport` carries `batch_size` so
the property can compute it. `/retention` additionally shows a server-computed `rowsPastExpiry` per
sweep, which is the number an operator actually wants.

**Four things ship in the same PR as the `chat_messages` table, non-negotiably:**

1. **The purge scheduler** — already shipped in Phase 1, before this table exists (§14). Shipping a
   chat log while the clock exists only on paper is indefensible.
2. **`/privacy` rendering from the resolved policy in all four locales**, plus the chat-log clock.
   `handle_privacy` currently reads the module constant `DEFAULT_RETENTION_POLICY`
   (`commands.py:91`), not `resolve_retention_policy(deps.settings)`. Phase 3 changes its signature
   to take `deps: BotDeps` (`handle_support` next door already does) and renders every number from
   the resolved policy. A test sets non-default `BAYRAM_RETENTION_*` values and asserts every number in
   the rendered text, in all four locales, equals the resolved policy.
3. **`purge_user` wired to `/forget`, scoped for in-flight safety** (§9). `handle_forget` clears the
   FSM draft only, and its docstring says so.
4. **`chat_messages` added to `tables_with_personal_data`** in
   `tests/test_db/test_privacy_constraints.py:149`, with an assertion that both clock columns are
   `NOT NULL` with no server default.

### 7.4 Failure isolation

The inbound middleware runs **inside** the FSM isolation lock (`RedisEventIsolation`,
`bot/app.py:73-82`). A DB write there serialises that chat's updates for the write's duration, and
the lock expires after 60 s — long enough for a hung write to break the double-tap guarantee
`build_dispatcher` was written to provide.

So: **the middleware never touches the database.** It builds a frozen `ChatLineDraft` (no I/O) and
calls `recorder.offer(draft)` — a non-blocking `put_nowait` onto a bounded
`asyncio.Queue(maxsize=2000)` in `src/bayram/bot/chatlog.py`. On `QueueFull` it drops the oldest,
increments a counter, and logs WARNING once per 100 drops. **Dropping loudly is acceptable; blocking
the bot is not; swallowing silently violates the repo's no-silent-swallow rule.** The drop counter is
exposed on the authenticated branch of `/readyz`.

One drain task (started in the bot's `run()` and the worker's ARQ `on_startup`) batches up to 100
drafts or 500 ms and calls `ChatLogRepository.record_batch`, which returns `Result` and never raises.
On `Err` it logs and drops the batch. Shutdown drains with a 2 s timeout.

The middleware also wraps its own body in `try/except Exception` and logs, because aiogram's outermost
`ErrorsMiddleware` (`dispatcher.py:80`) turns any exception into an `errors`-observer event — a broken
logger would otherwise fail silently and log every subsequent update inconsistently.

**Three artefacts the UI must present honestly rather than "fix":**

- **Albums.** Nothing handles `media_group_id`. Ten photos are ten updates, and with no session
  `handle_stray_message` calls `reset_to_welcome` per message (`fallback.py:74-85`), minting ten
  `session_id`s. Group by `media_group_id` and annotate "10 sessions in 3 seconds — likely a media
  group".
- **Edited messages never arrive.** `start_polling` defaults `allowed_updates` to
  `resolve_used_update_types()`, and only `message` and `callback_query` have handlers. Registering
  an outer middleware does not change that — and we deliberately do **not** widen it, because the
  note and lyric steps have no logic for edits.
- **The log and the draft will legitimately disagree.** `handle_note` and `handle_typed_lyrics`
  reject text starting with `COMMAND_PREFIX`, so the log keeps a `/halp` the product deliberately did
  not store. Rows are labelled "not stored in the brief".

---

## 8. Runtime configuration

### 8.1 The overlay

`Settings` is `frozen=True` and every consumer holds a direct reference inside another frozen
dataclass. The minimal honest fix is one level of indirection, in `src/bayram/runtime/overlay.py`:

```python
class SettingsHolder:
    """One mutable reference to an immutable Settings. Reads are lock-free."""
    __slots__ = ("_current", "_version")
    @property
    def current(self) -> Settings: return self._current
    @property
    def version(self) -> int: return self._version
    def replace(self, settings: Settings, *, version: int) -> None: ...
```

Attribute assignment is atomic under the GIL and every reader takes a single reference, so no lock is
needed and no reader sees a half-built object.

`AppContainer` changes its `settings: Settings` **field** to `settings_source: SettingsHolder`, and
gains a `settings` **property** returning `self.settings_source.current` (a property coexists with
`@dataclass(frozen=True, slots=True)` as long as its name is not also a field). Every existing
`container.settings` **read** keeps working.

**The draft argued only about reads, and that was the omission.** Renaming a dataclass field breaks
every *construction* site, and `BotDeps` is `@dataclass(frozen=True, slots=True)` (`deps.py:26`) with
**25 construction sites across `src` and `tests`** (verified: `grep -rn 'BotDeps(' src tests` → 25).
So `BotDeps` keeps its field named `settings` and gains a keyword-only shim:

```python
@dataclass(frozen=True, slots=True)
class BotDeps:
    settings_source: SettingsHolder
    ...
    @property
    def settings(self) -> Settings: return self.settings_source.current

def bot_deps(*, settings: Settings | SettingsHolder, ...) -> BotDeps:
    """Factory every call site uses. A bare Settings is wrapped in a fixed holder."""
```

Every existing `BotDeps(settings=..., ...)` call site changes to `bot_deps(settings=..., ...)` — a
mechanical rename that a bare `Settings` still satisfies, so **test fixtures need no other change**.
Phase 7's Modified list names `tests/test_bot/conftest.py` and `tests/conftest.py` explicitly, and
Phase 7 is sized accordingly.

That single change lands the entire already-live read set at once: everything the pipeline reads
through `self._settings` (the pipeline is built **per job**, `container.py:66-84`), everything the
handlers read through `deps.settings` (per update), and the per-attempt reads at
`jobs.py:119/132/432`.

`src/bayram/config.py` gains one function and `load_settings` delegates to it:

```python
def build_settings(
    overrides: Mapping[str, Any] | None = None,
    *,
    require_vendor_secrets: bool = True,
) -> Settings:
    """Env base plus overrides, validated together. Raises ConfigError and nothing else.

    ``require_vendor_secrets=False`` injects a non-empty placeholder for the three
    ``min_length=1`` vendor fields so the admin process can VALIDATE a candidate settings
    object without holding a single real key. The placeholders are never returned to a
    caller and never persisted; ``/config`` omits those fields entirely.
    """
```

**Whole-model construction, never per-field, is load-bearing.** `_greeting_window_must_be_ordered`
(`config.py:275-283`) is a `field_validator` reading `info.data`, so overriding only
`greeting_max_duration_s` would validate it against the *default* minimum rather than the effective
one.

**Unknown keys must not be silently dropped.** `Settings.model_config` sets `extra="ignore"`
(`config.py:67`), so `Settings(**overrides)` discards any key that is not a declared field. Rename or
remove a `Settings` field and its hand-maintained allowlist entry becomes a key that passes the
allowlist check, constructs cleanly, commits a version, publishes a bump — and does nothing. That is
§8.4's worst failure mode reached through the front door. Two guards:

- A **module-level** assertion in `src/bayram/admin/config/policy.py`:
  `assert LIVE_EDITABLE_FIELDS <= set(Settings.model_fields)` — an import-time failure, not a test.
- `build_settings` validates through a `model_config` copy with `extra="forbid"`, so an unknown key
  is a pydantic error naming the field rather than a silent drop.

Resolution order: process env + `.env` → override rows filtered to the allowlist → `Settings(**…)`.
Overrides layer on top of env. This is written into `.env.example`, which currently claims every
variable "maps 1:1 to a field" — true today, incomplete after this.

### 8.2 Propagation

- Storage of record is **Postgres**, not Redis — it must survive a Redis flush; Redis here is
  `--appendonly yes` but is still the volatile tier.
- Commit does `INCR bayram:settings:version` then `PUBLISH bayram:settings:changed <version>`. **The
  payload is the version integer only**, never the values; the channel is the wrong trust boundary
  and a pub/sub payload has no schema.
- Each process runs `SettingsWatcher` (`src/bayram/runtime/watcher.py`): a subscriber for speed and **a
  30 s `GET bayram:settings:version` poll as a required backstop, not an alternative.** Redis pub/sub is
  fire-and-forget; a subscriber disconnected during the publish never learns. Pub/sub makes
  convergence fast; the poll makes it guaranteed.
- On a bump: read the rows from Postgres, filter to the allowlist, `build_settings(...)`. **On
  `ConfigError` *or* `ValueError`, log ERROR with the version and the offending field and keep the
  current settings.** `ValueError` is in that list deliberately: `RetentionPolicy.__post_init__`
  (`retention.py:66-79`) raises a bare `ValueError` for a non-positive period, `logging.setLevel`
  raises `ValueError` for an unknown level, and `run_guarded` catches neither. A running worker must
  never be taken down by a bad override.
- `configure_logging` is re-called on every successful refresh (it is documented idempotent,
  `logging.py:159-175`), which is what makes `log_level` and `is_debug` actually live — subject to
  §8.7.
- Each process reports its applied `config_version` on the authenticated `/readyz` branch and in a
  heartbeat log line; the panel shows a per-process badge. **The three processes never converge
  atomically, and the UI says so** rather than implying they do.

### 8.3 Live-editable allowlist

`LIVE_EDITABLE_FIELDS: Final[frozenset[str]]` in `src/bayram/admin/config/policy.py`. It is an
**allowlist, not a denylist** — with a denylist, adding a field to `Settings` would silently make it
editable. Enforced **twice**: the API refuses to write a key outside it, and the watcher ignores a
row outside it, so a row inserted by hand cannot change a restart-only field behind an operator's
back.

**The "effect takes hold" column is honest about the worker's real granularity.** `KitPipeline.__init__`
snapshots `self._settings = settings` and builds `LlmContentWriter(llm, settings)` and
`LlmModerator(llm, settings)` from that same snapshot, and the pipeline is built once per job
(`container.py:66-84`). So for anything the worker reads, the granularity is uniformly **next order**
— including the four `*_timeout_s` fields the draft listed as "next call". Only two values appear in
this column: **next order** and **on refresh**. The dry-run response (§8.5 step 4) renders this text
to an operator, so it has to be right.

**Tier 1 — live, no caveats.**

| Field | Read site | Effect takes hold |
|---|---|---|
| `support_contact` | `handlers/commands.py:113`, `navigation.py:139` | next update |
| `llm_timeout_s`, `music_timeout_s`, `tts_timeout_s`, `stt_timeout_s` | per-request in the adapters, but from the per-job snapshot | next order |
| `provider_max_attempts`, `provider_backoff_base_s`, `provider_backoff_jitter`, `llm_parse_max_attempts` | `RetryPolicy.from_settings` in `KitPipeline.__init__` | next order |
| **`name_candidate_order`** | `handlers/name.py:43`, `names/__init__.py:25` | next update (bot) / next order (worker) |
| `name_verification_max_attempts`, `name_match_min_similarity`, `name_chunk_duration_ms`, `is_name_verification_enabled` | `name_stage.py:152/166/243`, `plan_builder.py` | next order |
| `is_moderation_enabled` | `container.py:80`, evaluated per job | next order |
| `is_manual_review_required` *(new)* | `submitter.submit` | next submission |
| `loudnorm_song_lufs`, `loudnorm_speech_lufs` | `pipeline/assets.py:141/177` — **not** baked, unlike the other nine audio fields | next order |
| `default_ui_language` | `handlers/common.py:165` | new sessions |
| `song_length_ms`, `song_body_chunk_duration_ms` | `plan_builder.py:141/164`, `music/planner.py:80-82` | next order |
| The eight `retention_*` fields *(new)* | `resolve_retention_policy`, **and `/privacy` once Phase 3's fix lands** | next container build / next purge run |

`name_candidate_order` is the flagship: `config.py:7-9` and the README both say a bake-off result is
applied by reordering this variable, never by editing code. Today that requires a redeploy.

Two Tier-1 fields carry a UI note rather than exclusion: `song_length_ms` and
`name_chunk_duration_ms` are cross-coupled (`plan_builder.py:141` computes
`max(0, song_length_ms - name_chunk_duration_ms)`, bounded by `MAX_CHUNKS_PER_PLAN = 30`), so
pydantic's per-field validation can pass on a pair that yields a zero body budget. The cross-field
guards in §8.5 catch it.

**Retention fields carry hard bounds and an extra gate.** They are a legal commitment (FIL-7/LR-52,
per `retention.py`'s docstring), and the draft made all eight editable with no bound in either
direction: `retention_brief_text_days = 36500` makes every future note immortal — the operator
switching off the design the panel exists to bound — and `retention_paid_audio_days = 1` mass-deletes
on the next hourly sweep. So:

| Field | Bound on `Settings` |
|---|---|
| `retention_paid_audio_days` | `Field(default=365, ge=30, le=1095)` |
| `retention_free_output_days` | `Field(default=30, ge=7, le=365)` |
| `retention_ephemeral_days` | `Field(default=7, ge=1, le=30)` |
| `retention_abandoned_draft_days` | `Field(default=14, ge=1, le=30)` |
| `retention_brief_text_days` | `Field(default=30, ge=7, le=90)` |
| `retention_recipient_identity_days` | `Field(default=90, ge=14, le=365)` |
| `retention_chat_log_days` *(new)* | `Field(default=90, ge=14, le=365)` |
| `retention_audit_log_days` *(new)* | `Field(default=730, ge=90, le=1095)` |

and §8.5 adds a guard: **any change that lengthens a retention period requires an OWNER step-up and
writes a distinct `RETENTION_EXTENDED` audit row** alongside `CONFIG_COMMIT`. Shortening does not.
Lengthening is the privacy-affecting direction and it should be visible as its own event in `/audit`.

**Tier 2 — live only after a named fix.** Three fields, one fix each. All are Tier 3 until their fix
lands.

| Field(s) | Why it is not Tier 1 today | The named fix |
|---|---|---|
| `greetings_per_kit`, `greeting_min_duration_s`, `greeting_max_duration_s` | `greetings_per_kit` is read in the generation phase (`orchestrator.py:182`) **and** the delivery phase (`jobs.py:432`) of the *same* order, both feeding `scheduled_stages(has_greetings=…)`; if they disagree the last two progress frames are scored against a different denominator — the comment at `jobs.py:423-427` says exactly this. The two duration fields are read in **one expression** (`orchestrator.py:374-376`: `target_s = (greeting_min + greeting_max) / 2`), so there is no read-site asymmetry that could justify splitting them across tiers, and `_greeting_window_must_be_ordered` validates max against min — with max frozen, an operator could only ever lower min, which reads as a bug | `generate_and_deliver` resolves the holder **once** at `jobs.py:347` into a local and threads that `Settings` down. All three become Tier 1 together |
| `llm_temperature`, `llm_max_output_tokens` | `LlmContentWriter.__init__` captures `Settings` **by value** (`content.py:156`, `self._settings = settings`) and the bot builds exactly one instance at boot (`main.py:111`, held for the process lifetime on `BotDeps.content`). A commit would take effect in the worker's per-job pipeline and **not** in the bot's wizard lyric writer — the customer-visible one, called up to `MAX_LYRIC_WRITES = 5` times (`bot/handlers/lyrics.py:79`). That is exactly the per-process split §8.4 forbids for pricing | `LlmContentWriter` takes a `SettingsHolder` and exposes `_settings` as a property reading `holder.current`. Test: a version bump changes the temperature of the **bot's** next write |
| `kit_price_amount_minor`, `kit_currency` | **The sharpest hazard.** Frozen into `BotDeps.amount_minor` at `main.py:113-114` (boot) and read live at `orchestrator.py:391-392`. A live edit gates the bot at one price and authorises the worker at another — two authorisations, one order, two amounts | `BotDeps` holds the holder (§8.1) and `confirm.py:202-204` reads `deps.settings.kit_price_amount_minor` directly instead of `deps.amount_minor` |

**One trap to close in Phase 3, not Phase 7.** `WIZARD_STATE_TTL` (`bot/app.py:45`) is derived from
`DEFAULT_RETENTION_POLICY.abandoned_draft_days` **at import time**. Overriding
`retention_abandoned_draft_days` would silently split the Redis FSM TTL from the Postgres draft
sweep — and, after §5.7, from the chat body clock too. `build_storage` and `build_dispatcher` derive
the TTL from the resolved policy at call time. This ships with the `retention_*` fields, not with the
config editor, because adding the fields is what creates the hazard.

### 8.4 Never editable from the UI

Presented **read-only with an explicit reason**, never as an editable field that silently does
nothing. Silently-ignored edits are the failure mode that makes runtime config worse than none.

| Field(s) | Reason |
|---|---|
| `telegram_bot_token`, `elevenlabs_api_key`, `llm_api_key`, `llm_fallback_api_key` | **SECRET tier.** Omitted from the API response entirely, not masked — masked-but-present is a leak waiting for a bug. The admin process does not hold them at all (§4.2) |
| **`database_url`, `redis_url`** | **SECRET tier, corrected from the draft.** A production DSN is `postgresql+asyncpg://user:PASSWORD@host/db` and Redis is commonly `redis://:PASSWORD@host`. The draft classified these as "never editable" but left them in a `GET /config` response readable by role **V**, so the lowest-privileged role would read the database and Redis passwords off the config screen. The codebase already knows they are credential-bearing: `container.py:127` logs `settings.database_url.split("@")[-1]` specifically to strip them. `GET /config` returns a derived `databaseHost` and `redisHost` computed the same way, never the DSN. Test: no `GET /config` response body matches `://[^/\s:@]+:[^/\s@]+@` |
| `elevenlabs_base_url`, `llm_base_url`, `llm_fallback_base_url` | **SSRF + key exfiltration.** These are hostnames the *worker* attaches a live API key to. Editing one redirects authenticated vendor traffic to an attacker host, in a single field |
| `use_fake_providers`, `environment` | Structural: selects the entire `ProviderSet`, the FSM storage, the submitter, and gates the prod safety interlock at `providers.py:81` |
| `worker_concurrency`, `queue_job_timeout_s`, `queue_result_ttl_s`, `queue_max_tries` | `WorkerSettings` class attributes evaluated at **import time** (`jobs.py:459-471`). `queue_max_tries` is the worst: it is *also* read live at `jobs.py:132`, and a divergence either abandons a customer an attempt early or **parks their wizard session forever**. The codebase documents this twice |
| `music_max_concurrency`, `tts_max_concurrency` | `asyncio.Semaphore` cannot be resized; also read twice with different lifetimes |
| `ffmpeg_binary`, `ffprobe_binary`, `ffmpeg_timeout_s`, `loudnorm_true_peak_db`, `fade_in_ms`, `fade_out_ms`, `silence_trim_threshold_db`, `opus_bitrate_bps`, `opus_sample_rate_hz` | Baked into `FfmpegAudioPostProcessor.from_settings` (`container.py:133`). The binaries are additionally probed once by `verify_host`. `opus_*`: Telegram `sendVoice` needs OGG/Opus or the greeting renders as a file attachment |
| `music_model_id`, `music_output_format`, `tts_model_id`, `stt_model_id`, `llm_model_id`, `llm_provider`, `llm_fallback_provider`, `llm_fallback_model_id` | Baked into adapters at construction. `music_v1` silently loses inpainting |
| `tts_voice_registry_json`, `tts_routes` | Parsed at `providers.py:129-138`/`172-180`; a malformed value raises `ConfigError`, which is *correct* at startup and catastrophic in a live worker |
| `supported_languages` | Removing a language does not invalidate in-flight drafts holding it; i18n catalogues load at boot |
| `music_usd_per_minute`, `elevenlabs_usd_per_character` | Editing a cost rate silently rewrites the meaning of every future `cost_usd` row against a `cost_source` that still says "derived". Restart-only until `generation_attempts` records the rate it used |
| `log_level`, `is_debug` | **Moved out of Tier 1 — see §8.7.** Conditionally editable, with a hard cap in prod |

### 8.5 Validate → commit → rollback

1. Reject any key not in `LIVE_EDITABLE_FIELDS` → 422 `CONFIG_FIELD_NOT_EDITABLE` naming the field
   and its tier and reason. This check runs first. A second check rejects any key not in
   `Settings.model_fields` (§8.1).
2. `candidate = current | changes`; construct `build_settings(candidate, require_vendor_secrets=False)`
   with `extra="forbid"`. A `PydanticValidationError` goes through the existing `_describe_failure`,
   so the operator sees **the same words the process would have printed at boot**, naming every
   offending `BAYRAM_*` variable, as a 422 on the field — after `redact()` and a 300-char cap (§6.2).
3. Cross-field guards pydantic does not express (`admin/config/guards.py`):
   - every `*_timeout_s` strictly `< queue_job_timeout_s` (900), or a vendor timeout becomes a job
     cancellation at `jobs.py:364-377`;
   - `song_length_ms - name_chunk_duration_ms > 0`;
   - resulting chunk count `≤ MAX_CHUNKS_PER_PLAN`;
   - `greeting_min_duration_s < greeting_max_duration_s` on the whole model;
   - `name_verification_max_attempts × song_length_ms` bounded, because each re-roll is a full render
     and this field multiplies spend directly;
   - **`RetentionPolicy(**resolved)` constructs without raising** — the guard catches the bare
     `ValueError` from `__post_init__` and renders it as a 422 instead of letting it reach a watcher;
   - **any retention lengthening sets `requiresRetentionExtension: true`** on the dry run, which the
     UI surfaces as a distinct confirmation and the commit records as `RETENTION_EXTENDED`.
4. Dry-run response: effective before/after per field, tier of each, which processes pick it up and
   when (two values only, §8.3), and a spend warning where the change multiplies vendor calls.
5. Commit (Owner + **fresh** step-up) re-runs 1–3, then **in one transaction** inserts
   `settings_versions` (full payload, `parent_version`) + upserts `settings_overrides` + writes the
   `CONFIG_COMMIT` audit row (+ `RETENTION_EXTENDED` when applicable). Then `INCR` and `PUBLISH`.
   See §9.1 for why this action's audit row is in-transaction and a retry's is not.
6. Rollback inserts a **new** version whose payload equals version *n*'s. History is append-only; a
   rollback is visible as a rollback. **Version 0 is "no overrides"** and is always valid by
   construction — one click returns every process to pure `.env`.
7. **Kill switch:** `BAYRAM_ADMIN_CONFIG_ENABLED=false` + restart makes the overlay loader a no-op. It
   is read from `AdminSettings` — i.e. from the process environment — and never through the holder,
   so no override row can reach it. See §8.6.

### 8.6 The `BAYRAM_ADMIN_*` fields have no tier, because they are not on `Settings`

The draft's own exhaustiveness test (`set(Settings.model_fields) == EDITABLE | READ_ONLY | SECRET`)
forced a tier decision for every `BAYRAM_ADMIN_*` field, and the draft never made one. If any had landed
in EDITABLE, a stolen admin session could set `admin_public_origin` to an attacker origin and disable
the CSRF `Origin` check outright, drop `admin_argon2_memory_kib` so every subsequently-set password is
cheap to crack, extend session lifetimes indefinitely, or flip `admin_config_enabled` back on after it
was used as the kill switch — which would make the kill switch database-controlled, i.e. not a kill
switch.

**This is closed structurally by D10.** Every `BAYRAM_ADMIN_*` field lives on `AdminSettings`, not on
`Settings`. The override key space is `Settings.model_fields`. There is no code path by which a
`settings_overrides` row reaches an admin field, whatever anyone writes into the table by hand.

Belt and braces, all three cheap:

- `policy.py` declares `SECURITY_CRITICAL: Final[frozenset[str]]` containing every `AdminSettings`
  field name, and the validate endpoint rejects any submitted key in it with 422 and a named reason,
  before the allowlist check.
- A test parametrised over every `AdminSettings` field name asserts `POST /config/validate` returns
  422 for each.
- The exhaustiveness test becomes
  `set(Settings.model_fields) == EDITABLE | READ_ONLY | SECRET` **plus** a per-field-by-name assertion
  of SECRET membership (not a count), so adding `database_url` to the wrong bucket fails loudly.

### 8.7 `log_level` and `is_debug` are a data-exfiltration surface

The draft put both in Tier 1 with the note "`configure_logging`, re-called by the watcher". Two
problems, and the first is serious.

`configure_logging` (`logging.py:159-176`) sets the **root** level and then floors only `httpx`,
`httpcore`, `asyncio` and `aiogram.event`. **`sqlalchemy.engine` is not floored**, and at DEBUG it
echoes every statement with its bound parameters — recipient names, notes, approved lyrics, STT
transcripts — into stdout logs that have no retention clock, are not reachable by `purge.py`, and are
not reachable by `purge_user`. A single config commit would convert the entire retention design into
a no-op for as long as it is on, and leave an unclocked copy behind afterwards. R1 names "a temporary
CSV" as the risk to watch for; this is the same risk with a bigger pipe and no record of what was
emitted.

Second, `log_level: str = Field(default="INFO")` has no validation, so `BAYRAM_LOG_LEVEL=TRACE` passes
pydantic and then `root.setLevel("TRACE")` raises `ValueError` inside the watcher's refresh — outside
the `ConfigError` contract §8.2 relies on.

**Fixes, all in Phase 1 except the tier decision:**

- Extend the noisy-logger floor in `configure_logging` to include `sqlalchemy`, `sqlalchemy.engine`,
  `sqlalchemy.pool`, `aiogram`, `arq`, `uvicorn`, `uvicorn.access` and `uvicorn.error`, so root DEBUG
  cannot reach a logger that echoes personal data. **This is worth doing regardless of the panel** and
  ships in Phase 1.
- Type the field as `Literal["CRITICAL","ERROR","WARNING","INFO","DEBUG"]` on both `Settings` and
  `AdminSettings`, so an invalid level is a 422 in the editor instead of a `ValueError` in a live
  worker.
- Tier: **conditionally editable**. `WARNING`/`ERROR`/`CRITICAL`/`INFO` are Tier 1. Setting `DEBUG`
  (or `is_debug=true`) when `environment == "prod"` is **refused** by a §8.5 guard. In dev and
  staging it requires an OWNER step-up and writes a `CONFIG_COMMIT` audit row naming the level. The
  UI renders the refusal reason inline.

---

## 9. Operational actions

### 9.1 The audit-transaction rule

The draft stated two contradictory rules — §9 said the audit row is deliberately *not* in the
action's transaction, §8.5 said the config commit writes it *inside* the transaction — and never
reconciled them. Both are right for different action shapes, so the rule is stated once here and
every action below declares which it uses.

| Action shape | Rule | Why |
|---|---|---|
| **The action is a single database transaction** — config commit/rollback, block/unblock, moderation approve/reject, cancel, admin CRUD | The audit row goes **in that transaction**. | An unaudited state change is then impossible, including under deliberate DB pressure. This is the failure mode §12.4 exists to prevent |
| **The action is external and cannot be rolled back** — an ARQ enqueue, a file delete, an asset stream, a reveal | **Two rows**: an INTENT row committed *before* the action, an OUTCOME row after, carrying `outcome` and `error_code`. | A completed retry whose audit insert failed must still be recorded, and an audit insert must never roll back an enqueue that already happened. The draft already used this shape for `USER_PURGE_REQUESTED`/`_COMPLETED`; it is now the general rule for its class |

A parametrised test asserts the expected row count per action on the success path **and** on the
audit-failure path.

All actions live in `src/bayram/admin/services/actions.py` behind one wrapper so the audit row cannot be
forgotten:

```python
async def audited[T](
    action: AuditAction, *, actor: CurrentAdmin, subject_type: str, subject_id: str,
    reason: AuditReason, mode: AuditMode,      # IN_TRANSACTION | INTENT_OUTCOME
    run: Callable[[], Awaitable[Result[T]]],
    audit: AuditRepository, now: datetime,
) -> Result[T]: ...
```

### 9.2 The actions

| Action | What it calls | Idempotency | Audit | Role |
|---|---|---|---|---|
| **Retry a failed order** | `DEL arq:result:generate_kit:<id>` (best-effort), then `enqueue_job("generate_and_deliver", str(id), chat_id, progress_message_id, _job_id=job_id_for(id))`. The names genuinely differ: function `generate_and_deliver` (`jobs.py:86`), job-id prefix `generate_kit:` (`pipeline/worker.py:47`) | Four existing layers inherited: `KitPipeline._replay` probes `get_kit` first and re-delivers for one DB read without re-buying a song; `idempotency_key(order_id, stage, …)` is deterministic; the workspace is deterministic per order with fixed filenames; `_replace_assets`/`_replace_verdicts` are delete-then-insert. **Trap:** ARQ refuses a `_job_id` present in the *result* store, and `queue_result_ttl_s = 3600` — re-enqueuing within an hour silently returns `None`. Hence the `DEL`, or a `:admin-<n>` suffix behind `?force=true` | `ORDER_RETRY`, INTENT+OUTCOME, `field_names=["state"]`, `reason_code` required | O |
| **Re-enqueue a job** | Same call. Distinct intent: an order stuck in `GENERATING` whose job vanished (worker OOM, result expired mid-run). Refuses `DELIVERED` without `?force=true`, refuses `HELD_FOR_REVIEW` outright | As above | `ORDER_REENQUEUE`, INTENT+OUTCOME | O |
| **Force-deliver a kit** | Same enqueue. **Precondition checked first: `get_kit(order_id)` must return `Ok`.** If it `Err`s (assets expired, run never completed), 409 `PRECONDITION_FAILED` explaining that this would trigger a full regeneration with real vendor spend, pointing at retry. Without this check, "force-deliver" silently becomes "spend money" | `_replay` makes it one DB read + re-delivery. `DeliveryLedger` dedupes within a process only (in-memory, LRU 1024) so a cross-process retry legitimately resends — the correct trade for "the first one never arrived" | `ORDER_FORCE_DELIVER`, INTENT+OUTCOME | O +S |
| **Block / unblock a user** | `set_blocked` as an **upsert keyed on `telegram_user_id`**, not a bare UPDATE — see §5.11; a user with no `users` row (never confirmed an order) is exactly who an operator wants to block, and a rowcount-checked UPDATE fails for them. **Plus the other half:** `BlockGateMiddleware`, an outer middleware reading `is_blocked` (cached `SETEX bayram:blocked:<tg_id>` 60 s, invalidated by the action) that sends the localised `error.blocked` instead of calling the handler. It **fails open** — cache and DB both unreachable must not block every customer | Naturally idempotent; blocking a blocked user is a no-op that still writes an audit row (pressing it twice is information) | `USER_BLOCK` / `USER_UNBLOCK`, IN_TRANSACTION | O +S |
| **Purge a user's personal data** | **An ARQ job, not an inline call** (D11). The API writes `USER_PURGE_REQUESTED`, enqueues `purge_user_data(telegram_user_id, scope, actor_id, reason_code, exclude_order_ids)` and returns `202`. The **worker** — which owns the writable volume — runs `purge_user(...)` and writes `USER_PURGE_COMPLETED` with per-table and per-file counts, or `USER_PURGE_FAILED` with the `ErrorCode`. The UI shows the purge as **in progress** until the completion row lands, never as done on enqueue | Fully idempotent: every step is "null what is not null" / "delete what exists". A second run reports zeros | Three rows total across two processes | W +S (fresh), typed confirmation of the telegram id, `reason_code` mandatory |
| **Trigger the retention sweep** | Enqueue `run_retention_sweep(trigger="manual")`. Not inline — a 500-batch sweep must not block a request | Batched and bounded; `isBatchFull` plus `rowsPastExpiry` tell the operator to run it again | `RETENTION_RUN`, INTENT+OUTCOME | O |
| **Approve a moderation review** | One transaction: `decide(status=APPROVED)` (rowcount-guarded), `set_state(order_id, review.held_from_state)`, audit row. Then the enqueue, outside it | The rowcount guard makes a second approve a 409 `CONFLICT` | `MODERATION_APPROVE`, IN_TRANSACTION + an enqueue OUTCOME row | O +S |
| **Reject a moderation review** | One transaction: `decide(status=REJECTED)`, `set_state(FAILED, failed_reason="moderation_rejected")`, audit row. Then enqueue `notify_order_failed(order_id, message_key)` — **a new, tiny ARQ job**, because the API holds no `Bot` | Rowcount-guarded | `MODERATION_REJECT`, `decision_note` required (min 3 chars, 30-day clock) | O +S |

### 9.3 `purge_user` and `/forget`

`purge_user(session_factory, *, telegram_user_id, scope, exclude_order_ids, now)` in
`bayram/db/purge.py`:

- nulls `briefs` note + approved_lyrics + the six identity columns and stamps both `*_purged_at`;
- nulls `generation_attempts.name_candidate_text` + `stt_transcript` and stamps both;
- nulls `moderation_reviews.flag_detail` + `decision_note` and stamps `text_purged_at`;
- **deletes** `chat_messages` rows;
- deletes `assets` rows and **returns their `storage_key`s to the job**, which deletes the objects;
- deletes the Redis FSM draft;
- removes `var/workspace/<order_id>/` through `Storage`'s confined path helper;
- **keeps `orders` and `users`** — the tax record survives by design (DAT-3), and
  `generation_attempts`' tuning columns are the moat and hold no identity once the text is gone;
- children are deleted explicitly, never by cascade (SQLite does not enforce FKs);
- **`exclude_order_ids` is honoured everywhere**, so an in-flight order is skipped whole.

**`/forget` must not corrupt an in-flight order, and the draft's wiring would have.**
`handle_forget` (`commands.py:116-160`) deliberately re-parks `Wizard.submitting` with the order id,
and `privacy.forgotten` tells the customer in the next sentence that the queued song survives on the
`/privacy` schedule — a documented fix for a real bug where a Cancel claimed nothing was made about a
song that then arrived. Wiring `/forget` to an unscoped `purge_user` would, for a customer who types
it while the worker is mid-render, delete the workspace the running job is writing into and null the
brief the pipeline re-reads, corrupting a paid order and contradicting the message just sent.

So `/forget`:

1. resolves `order_in_flight` exactly as today and keeps the re-park behaviour **untouched**;
2. computes `exclude_order_ids` = every order of that user in
   `{AUTHORIZED, GENERATING, HELD_FOR_REVIEW}`;
3. enqueues `purge_user_data(scope="all", exclude_order_ids=…, trigger=USER_REQUEST)`;
4. for each excluded order, enqueues a **deferred** `purge_user_data` with `_defer_by` = the job
   timeout, so the erasure completes once the job settles;
5. answers with the existing copy.

The panel's OWNER purge shares the same implementation and **warns** (or, with
`excludeInFlight=false`, refuses with 409) when an order is in flight.

Test: `/forget` during `GENERATING` leaves the workspace and the brief intact, the song still
arrives, and the deferred job then erases everything.

### 9.4 Three things the retry UI must tell the operator

Because they are invisible from the button:

1. A retry **re-runs moderation and re-authorises** — there is no resume-from-stage entry point.
2. A `FAILED` order with no kit is a **full regeneration from stage 1 with full vendor spend**, while
   a `DELIVERED` order retried is pure re-delivery. `RetryOrderDialog` computes which by asking
   whether `get_kit` would succeed.
3. `chat_id`/`progress_message_id` are not stored on historical orders, so a **fresh** progress
   message must be posted or every sink edit 400s. `TelegramProgressSink` treats
   `progress_message_id == 0` as "post a fresh message on the first frame" (~12 lines inside
   `_push`).

---

## 10. Moderation queue

### 10.1 Where the gate sits

Today moderation runs in the worker at stage 2, **after** payment authorisation
(`orchestrator.py:251-255`) and **after** the wizard already spent LLM money writing the lyric
(`lyrics.py:82`, bounded only by `MAX_LYRIC_WRITES = 5`). A rejection is an
`Err(ModerationRejectedError)` → `FAILED` → a log line. Nothing records a flag. `moderation.py:5-9`
already signposts moving the gate earlier as the intended change.

The human gate is inserted at exactly one point: **between `ArqOrderSubmitter.submit`'s persist and
its enqueue** (`runtime/submitter.py:58-70`). **No orchestrator change is needed, and none is made.**

```mermaid
stateDiagram-v2
    [*] --> LYRICS_READY: wizard, lyric approved
    LYRICS_READY --> AUTHORIZED: gate off — enqueue immediately
    LYRICS_READY --> HELD_FOR_REVIEW: is_manual_review_required=true
    HELD_FOR_REVIEW --> AUTHORIZED: operator approves<br/>→ restore held_from_state + enqueue
    HELD_FOR_REVIEW --> FAILED: operator rejects<br/>→ failed_reason + notify_order_failed job
    AUTHORIZED --> GENERATING
    GENERATING --> DELIVERED
    GENERATING --> FAILED
```

`ArqOrderSubmitter.submit`, when `settings.is_manual_review_required` is true: persist the order with
`state=HELD_FOR_REVIEW`, insert a `pending` `moderation_reviews` row with
`held_from_state=LYRICS_READY`, **do not call `enqueue_job`**, and show the customer a "your song is
being checked" screen. Approval is exactly the §9 enqueue.

The FSM session is parked in `Wizard.submitting` as it is today, and that is correct here: the
customer is genuinely waiting and the panel's queue age counter (amber >5 min, red >15 min) is the
control that keeps the wait bounded.

### 10.2 What the reviewer sees

The review reads the note, name and lyric **live from `briefs`**, so the 30/90-day brief sweeps
remain the governor for those. The matched denylist pattern is highlighted in situ. Showing "flagged"
without showing *which characters* forces the operator to re-read a whole lyric.

**Corrected citations, because the highlight depends on them.** `LOCAL_DENY_PATTERNS` is the tuple at
`moderation.py:52-57`. The helpers that produce the flag context are `_local_hit` (`:73`, returning
`match.group(0)`) and `_hit_source` (`:81`), and the context is attached at `:118-127`. **Both
`pattern_hit` and `hit_in` are carried only on the DENYLIST branch**; the LLM-verdict branch attaches
only `reason` (`:148-157`), truncated to `REJECTED_NOTE_LOG_CHARS = 200`. So `flag_detail` is
populated with a matched substring for `denylist` flags and with the model's `reason` for
`llm_verdict` flags, `flag_pattern_index` and `flag_hit_in` are NULL for the LLM path, and the review
UI renders the LLM reason as prose rather than an empty highlight.

`ModerationReviewRepository.decide` uses `UPDATE … WHERE id=:id AND status='pending'` and checks
`rowcount`; zero rows means another operator already decided, and the service returns 409. This is
the only concurrency guard in the design and it is deliberate — the codebase has no advisory locks,
no `SELECT … FOR UPDATE` and no version column outside the audit chain, so a rowcount-checked
conditional update is the idiom that fits.

Opening a review is an audited reveal (`REVEAL_PERSONAL`, `record_count=1`, subject
`moderation_review`) for OPERATOR and above.

### 10.3 What this deliberately does not include

**There is no in-pipeline soft-flag path.** The draft's Phase 6 included one ("a soft-flag path that
opens a review instead of failing the order") and it breaks three invariants that it never addressed:

- `KitPipeline.run` returns `Result[Kit]`; a "held" outcome is neither `Ok` nor a retryable `Err`,
  and both branches of `jobs.py:_run_pipeline` either raise `Retry` or take the terminal path.
- `_release_session` (`jobs.py:218-280`) runs **only** on terminal ends, so a held order would leave
  the customer's FSM parked in `Wizard.submitting` staring at "still in the studio" until the 14-day
  `WIZARD_STATE_TTL` expires — the exact bug that function exists to prevent.
- Approval would loop: the re-enqueue finds no kit (`orchestrator.py:173`), the pipeline reruns, the
  same moderator flags the same brief, and it is held again. There is no approved-bypass flag
  anywhere in the design.

Fixing all three is a real piece of work (a distinct `ModerationHeld` outcome threaded through
`run` → `_run_pipeline`, an explicit session release plus a localised message from the job, and a
`moderation_reviews.status='approved'` probe in `KitPipeline._prepare`). It is **out of scope**; the
submit-time gate delivers the stated goal — no generation spend on unreviewed content — with no
orchestrator change at all.

**The gate protects generation spend, not lyric-writing spend.** The wizard has already made up to
five LLM calls by the time the customer presses confirm. A gate that also protected that would have
to sit before `enter_lyrics_step`, which changes the customer's experience of the wizard. Out of
scope; recorded here so nobody assumes otherwise.

---

## 11. Frontend

### 11.1 Stack and layout

React 18.3.1 + Vite 6 (`@vitejs/plugin-react-swc`) + TypeScript strict (`noUncheckedIndexedAccess`,
`exactOptionalPropertyTypes` — mirroring `mypy --strict`) + Tailwind 3.4 + shadcn/ui vendored on
Radix. TanStack Query v5 is the only server-state store; TanStack Table v8 headless for tables; React
Router 6.28 data router with `lazy()` per route; Recharts 2.13 behind a local `<ChartFrame>` so a swap
to uPlot is one file; **zod at every API boundary**; Zustand for exactly three client stores
(`usePlayerStore` — one `<audio>` element surviving route changes; `useFeedStore`; `usePrefsStore`);
URL search params (zod-parsed) for all filter state so an operator can paste "the failed orders I'm
looking at" into Slack.

```
bayram-bot/
├── admin-ui/                  # Node lives here and nowhere else
│   ├── src/{api,components,features,hooks,lib,styles}/
│   └── vite.config.ts         # build.outDir = ../src/bayram/admin/static
└── src/bayram/admin/static/      # gitignored; force-included in the wheel via
                               # [tool.hatch.build.targets.wheel] artifacts
```

Node stays outside `src/` because hatchling packages `src/bayram` wholesale, and a `node_modules` in
there breaks mypy's `files = ["src","tests"]` walk and ruff's `src` setting. New `.gitignore`
entries: `admin-ui/node_modules/`, `admin-ui/dist/`, `src/bayram/admin/static/`.

**Same origin, always.** Dev: Vite on 5173 proxies `/api` to `127.0.0.1:8080` with
`changeOrigin: false`. Prod: FastAPI mounts `/assets` (immutable) and serves `index.html`
(`no-store`) for every non-`/api` GET. This is a security decision — it removes CORS entirely (no
`allow_credentials` + origin-list combination to get wrong), lets the CSP be `default-src 'self'`,
and lets `<audio src>` carry the session cookie as a same-site subresource with no token in the URL.

The never-throw client mirrors `run_guarded`:

```ts
export type ApiResult<T> = { ok: true; data: T }
                         | { ok: false; code: ApiErrorCode; message: string; status: number }
```

Every response is `schema.safeParse`d. A parse failure becomes a distinct, loudly-rendered
`SCHEMA_DRIFT` banner naming the endpoint and the failing field path — the frontend twin of the
repo's decision to treat a `pydantic.ValidationError` on a stored row as a deliberately loud
data-integrity bug.

### 11.2 Information architecture

> **Amended 2026-09-09.** The rail gains **Broadcasts** and the table below gains its three
> routes. This line has to exist before the nav item can: `navItems.ts` is transcribed from this
> enumeration and refuses to be "extended by inference"
> (`admin-ui/src/components/layout/navItems.ts:20-22`), so a rail entry with no §11.2 row is a
> silent widening of the information architecture. It is **not** the notifications button
> `TopBar.tsx:29-32` refuses by name — that is an inbound feed with nothing behind it, and that
> refusal stands. This is an outbound action with a specification (`BROADCAST_SPEC`), three
> permissions, a step-up and two audit rows per send. `DECISIONS.md` **D12** records the reversal,
> its fallback and the trigger that switches to it.

> **Amended 2026-09-15.** The rail gains **Support** and the table below gains its two routes.
> The rule is the one the 2026-09-09 amendment states and is repeated here rather than assumed:
> `navItems.ts` is transcribed from this enumeration and refuses to be "extended by inference", so
> a ninth rail entry with no §11.2 row is a silent widening of the information architecture.
> `admin-dashboard/src/app/navItems.ts` additionally asserts a section COUNT in prose **twice** —
> "Eight sections are listed" and "eight items under two extra headings" — and both go stale at
> nine; that file's own argument is that stale counts are how this documentation rots, so both are
> corrected in the same change. Support sits **after Broadcasts and before the rule**, which is
> where an operator's day actually splits: everything above the rule is the work, everything below
> it (Config · Audit · Admins) is the console administering itself. `DECISIONS.md` **D18** records
> the decision, its fallback (`BAYRAM_SUPPORT_GROUP_CHAT_ID=0` — the ticket queue without the
> Telegram group leg) and the triggers that switch to it; `SUPPORT_TICKETS_SPEC` is the
> specification. This is again **not** the notifications button `TopBar.tsx:29-32` refuses by name,
> and that refusal still stands — this is a worked queue with a schema behind it, not an inbound
> feed with nothing behind it, and §4 of that spec is explicit that a reopened ticket is announced
> by the board and by nothing else, precisely so no notification surface is invented to carry it.

> **Amended 2026-09-15 — D18's fallback is no longer an environment variable.** The paragraph
> above names that fallback as `BAYRAM_SUPPORT_GROUP_CHAT_ID=0`, and that variable no longer
> exists: it and `BAYRAM_SUPPORT_GROUP_THREAD_ID` were **deleted** from `Settings` in the same
> change that added the `bot_chats` table (revision 0028), rather than kept as a seed or a
> fallback — see `SUPPORT_TICKETS_SPEC` **§3.8** and **D18**'s own 2026-09-15 amendment.
>
> **The fallback itself is unchanged in substance, only in spelling.** It is still "the ticket
> queue without the Telegram group leg", and it is still what every fresh deployment gets; it is
> now expressed as **no row in `bot_chats` carrying the selection** — an empty table — reached by
> `POST /api/support/groups/clear` rather than by editing a unit file and redeploying. The
> triggers that switch to it are the ones D18 already records.
>
> **This rewording does NOT widen §11.2.** The picker is a dialog on the Support board's toolbar,
> not a ninth rail entry: `navItems.ts` is still transcribed from this enumeration, the section
> count above is still right, and no route row is added here. That placement is argued at
> `SupportGroupDialog.tsx` and in §3.8; if it ever becomes a route, §11.2 gains a row in the same
> change and not before.

> **Amended 2026-09-15 (second amendment).** The `/broadcasts` row below gains a **stat strip**,
> served by `GET /api/broadcasts/stats` on `BROADCAST_READ` — the same cell as the list it sits
> above, because it is the same rows counted and an aggregate over them holds strictly less than
> the list does: one count per `BroadcastState`, the reach as two integers, and one UTC instant.
> `BROADCAST_SPEC` §3.2's router table gains the corresponding row.
>
> **Three things about the shape are decisions and not details.** The state counts are
> **zero-filled over the enum** — `BroadcastState` is a closed vocabulary, so a state with no
> campaigns is `0` rather than absent and the strip's tiles never appear from nowhere under the
> operator's cursor. That is the opposite of a time series, where a day nobody measured has to
> stay missing. The reach travels as `reachedRecipients` **and** `audienceTotal` and never as a
> percentage, which is this repo's rule for every quotient it publishes (`RatioView` in
> `schemas/overview.py` cannot be constructed without its denominator): the SPA divides, and a
> deployment with a zero denominator draws a dash rather than "0%". And `lastSendAt` is
> `MAX(broadcasts.started_at)` or **`null`** — a deployment that has never sent anything is a
> fact, and an epoch or a fall-back to `created_at` would render as a send nobody made.
>
> It is a **sibling route and not a field on the list's `meta`**, for `/orders/state-counts`'
> reason (§6.5): an aggregate over the whole filter set carried on `meta` runs again on every
> `?cursor=` an operator turns, paying for numbers that did not change. `/broadcasts/stats` is a
> single literal segment where `/broadcasts/:broadcastId` also matches, so it is **registered
> first** — the `ORDER_STATE_COUNTS_PATH` warning, which `/support/board` carries too.

> **Amended 2026-09-09 (second amendment).** The top bar's inventory below gains the **vendor
> balances** — one pill per polled account, a mark inside a ring rather than a word — and a
> **language switcher**, which is being built separately and has a reserved slot rather than a
> stub, because a disabled control that does nothing is worse than a bar that claims one it
> does not have. The same rule that
> governs the rail governs this line: a control in the bar with no §11.2 row is a silent
> widening of the shell. What earns the balances their place is that they are a property of
> the DEPLOYMENT and not of a screen: they lived in `DashboardPage`'s own header, which meant
> an operator reading `/generations` at two in the morning could not see that a vendor was
> about to run out without navigating away. They are now in the bar and nowhere else — the
> dashboard's duplicate strip was removed in the same change.
>
> This is again **not** the notifications button `admin-ui/src/components/layout/TopBar.tsx`
> refuses by name, and that refusal still stands: this is not an inbound feed with nothing
> behind it, it is a figure a cached `vendor_balances` row already holds and that the finance
> read already carries. The ring's denominator is what **D13** bought with a fifth credential.
>
> **The two consoles' bars differ, and the difference is recorded rather than resolved.**
> `admin-ui` (deprecated; `Makefile:26 LEGACY_UI`) has the six controls listed below.
> `admin-dashboard` — what `make ui` runs — has balances and theme today, with the language
> switcher landing separately into a marked slot between them (`app/TopBar.tsx`); it has none
> of the other four: no env badge, no ⌘K palette, no LIVE pill and no account menu, because
> `NavRail`'s footer owns the session and the palette and the pill were never built there. A
> reader auditing "does the console show which database this is" must read that as **no, not
> in the shipped console** — the env badge is a real gap in `admin-dashboard`, not a thing
> this amendment quietly renamed.

> **Amended 2026-09-15 (second amendment).** The `/users` row of the table below is corrected:
> its dominant signal read "Total users + 30-day new-user sparkline", and what ships is neither
> half of that. The screen gets a **four-count stat strip** — accounts · reachable · blocked ·
> bot-blocked — from `GET /api/users/stats` (§6.6), computed over the operator's **own filter
> set** rather than over the whole database.
>
> The sparkline is not merely unbuilt, it is withdrawn, and the reason is the one this section
> keeps making about numbers that do not move: a 30-day new-account series is a DASHBOARD
> question that `/api/metrics/audience` already answers (§6.4), and repeating it above a
> *filtered* records table would put a figure on the screen that stays put while the operator
> changes a chip — which is the most misleading thing a strip above a table can do. "Total
> users" survives in a narrowed form as `matched`: the total of what is being SHOWN, exact
> rather than `TOTAL_COUNT_CAP`-bounded, so it deliberately disagrees with the list's own
> `meta.total` above ten thousand rows in the same way `/orders/state-counts` does.
>
> `reachable` is what the row's question — "who are they and are they blocked?" — was actually
> asking for, and it is the only one of the three refusal figures that is a complement.
> `blocked` is our bar, `botBlocked` is the customer's, an account can carry both, so the four
> numbers do not add up and the SPA must not sum them. This is the same breakdown the broadcast
> wizard authorises a send against (§6.7's `/segments/preview`), which is deliberate: the count
> an operator sees above the Users table and the count the wizard shows them are one statement
> about one population, not two numbers that have to be kept in agreement.

Left rail (220px, collapsible to 64px, persisted) → **Live · Orders · Users · Generations · Assets ·
Chat · Payments · Moderation ③ · Broadcasts · Support** ─── **Config · Audit · Admins**. Top bar (56px): env badge (`dev`
slate / `staging` amber / **`prod` violet with a glow ring** — an operator must never be unsure which
database they are looking at), ⌘K palette, `● LIVE` connection pill, **UTC/local toggle** (every
column is `timestamptz` and three parties may be in three places; an ambiguous "14:32" is a support
incident), theme, account.

The ⌘K palette is the single global entry point and resolves by shape: a UUID jumps to the order, a
bare integer to the user, a 32-hex string to a `correlation_id`, free text searches recipient display
names.

| Route | The question it answers | Dominant signal |
|---|---|---|
| `/` Live Ops | "Is the system fine right now?" | 24 h delivery success rate at 44px, colour-driven (green ≥95%, amber 85–95%, red <85%); secondary **in flight** with a pulsing ring |
| `/orders` | "What is the shape of what I just filtered to?" | A full-width 8px stacked state-distribution bar under the filter bar, before the eye reaches row one |
| `/orders/:id` | "Where is it, or exactly where did it die?" | `PipelineTimeline` across the top third, driven by `stagePlan` (9 stages by default, not 11 — `greetings_per_kit=0` is shipped) with unplanned stages ghosted. The merged timeline renders a `sources` legend so an absent section reads as "not enabled in this deployment", never as "nothing happened" |
| `/users` | "Who are they and are they blocked?" | A four-count stat strip over the CURRENT filter set — accounts · reachable · blocked · bot-blocked — from `GET /users/stats`, before the eye reaches row one, the same shape `/orders` gives its distribution bar. *Amended 2026-09-15: the earlier "Total users + 30-day new-user sparkline" is withdrawn — see the second amendment above this table for why a whole-database figure does not belong over a filtered list.* **`lastSeenAt` is labelled "last seen" only from Phase 3**, when the inbound upsert gives it a real writer; before that the column header reads "last order" |
| `/users/:id` | "What happened to my song?" | Full-width banner: status of their most recent order |
| `/generations` | "Is name verification working?" | Overall verification rate |
| `/generations/names` | "What should `BAYRAM_NAME_CANDIDATE_ORDER` be?" | Per-strategy bake-off bars + a similarity histogram with the threshold marked, linking straight to `/config` |
| `/assets` | "What is about to expire?" | Assets expiring within 7 days (storage size is **not** shown — `size_bytes` is always 0) |
| `/chat`, `/chat/:tgId` | "What did this person actually say?" | Last activity; transcript grouped by `session_id`, callbacks as first-class rows, progress edits collapsed, purged ranges shown as `PurgedRange` with the clock that did it |
| `/payments` | "How many authorisations, how many declines?" | Authorisation count — **not** revenue; a big "0 UZS" would be the most misleading number in the console |
| `/config` | "What differs from the deployed config?" | Active override count + restart-required-pending count; four visual tiers (live / after-fix / read-only / secret-absent) |
| `/moderation` | "How long has someone been waiting?" | Oldest waiting age, amber >5 min, red >15 min |
| `/broadcasts` | "What has been sent, and what is going out right now?" | Campaign list with a per-campaign progress bar for anything `expanding`/`sending`; the counters are `broadcast_recipients`, never the job result (`BROADCAST_SPEC` §4.7). Above it a **stat strip** over the list's own filter set — `GET /api/broadcasts/stats`, amended 2026-09-15: campaigns per state **zero-filled over the enum**, reach as `reachedRecipients` of `audienceTotal` (two integers, never a rate), and the last send as a UTC instant **or `null` when nothing has ever been sent** |
| `/broadcasts/new` | "Exactly who will receive this, before I authorise it?" | The dry-run audience count — an exact `count(*)`, never the capped total — restated at every step and typed back by the operator at the last one. A literal route, registered before `/broadcasts/:broadcastId` |
| `/broadcasts/:broadcastId` | "Did it land, and who did it miss?" | Sent / failed / skipped / **unknown** as four tiles, `unknown` shown rather than rounded away because an interrupted send is never retried (`BROADCAST_SPEC` §4.4). Recipient ids are masked on this wire — there is no `/broadcasts/**` route that keys on a raw Telegram id |
| `/support` | "What has a customer told us is wrong, and who is on it?" | A four-column Kanban board — `new` · `in_progress` · `waiting` · `resolved` — with the oldest unclaimed ticket in `new` as the number that matters. `waiting` means waiting on the CUSTOMER, never on us (`SUPPORT_TICKETS_SPEC` §4.1), which is the whole reason it is a column: a backlog that mixes "we asked them three days ago" with "nobody has looked at this" has a length that means nothing. Tickets with no description — tapped ⚠️ and never typed — are **excluded by default and not deleted** (§4.3). Cards move by native drag **and** by keyboard, with an `aria-live` announcement; a stale move is a 409 naming both ends, never a silent overwrite |
| `/support/:ticketId` | "What did they actually say, and what have we done about it?" | The customer's complaint in full — the one free-text column in this schema that crosses to the panel unmasked, argued in `SUPPORT_TICKETS_SPEC` §5.4 — above an append-only timeline of every status change, note, reply and group post. A `reply` row with no `relayed_at` is an answer nobody received. Telegram ids are masked here as everywhere else |
| `/audit` | "Who did something destructive?" | Destructive actions in the last 24 h, counted separately; **reveals charted by `record_count`, not by row count** |
| `/admins` | "Is there a stale account?" | Active count + last-login recency |

### 11.3 Design tokens

> **Amended 2026-09-03, at the user's explicit direction.** The original §11.3 palette — a
> dark-first console built out of 1px borders, with `--bg-0…3` / `--fg-0…3` positional names —
> was replaced wholesale by the "Gogo" language after the user said, verbatim, "I do not like
> the design of admin panel at all! Please implement this design:
> https://gogo-next.crealeaf.com/". This block is now the design of record; the palette it
> replaces is preserved only in this repository's history. **Light is home** — `:root` is the
> light palette and `[data-theme="dark"]` overrides it, the reverse of the original.
>
> Two things about the transcription. First, the tokens are named by ROLE, not by position:
> the old numbering is what allowed 131 prose sites to be painted with a token meant for marks
> and 41 more with a token meant for rules, and `--ink` / `--ink-muted` / `--ink-mark` /
> `--ink-rule` make the misuse visible in the class name. Second, **every one of Gogo's twelve
> hues had to be darkened for the light theme**: Gogo's own HSL values are dark-theme values
> that it only ever uses as chart fills under `#4D4D4D` text. Measured on `#FAFAFA`, Gogo's own
> page ground, eleven of the twelve are under 4.5:1 (only `--primary` clears it, at 4.75:1) and
> eight are under the 3:1 graphic bar as well — success 2.04:1, info 2.03:1, warning 2.40:1,
> the amber accent 1.77:1. Hue and saturation are Gogo's exactly; only lightness moved, and
> only nine of the twelve had to move in their graphic member (primary, secondary and error
> ship at Gogo's own lightness as `--brand-fill`, `--accent-fill` and `--error-fill`). Every
> family therefore has
> a text-safe member (`--x`, ≥4.5:1) and a graphic member (`--x-fill`, ≥3:1) at or near Gogo's
> own lightness, plus a `--x-tint` chip ground. The full per-token deviation log, with measured
> before/after, is at the bottom of `admin-ui/src/styles/tokens.css`.
>
> Every ratio below is measured and is re-measured on every run by
> `admin-ui/src/styles/tokenContrast.test.ts`, which also cross-checks each token comment's
> claimed ratio against the palette it annotates. **Do not write a ratio into this document
> that has not been measured** — §11.3's original annotations carried four wrong numbers and
> one of them ("`--fg-2` 4.6:1 — floor for real text", actually 4.34:1) is what licensed the
> incident above.

```css
:root {                                  /* LIGHT IS HOME */
  /* Surfaces — a card is separated from the ground by colour + shadow, never by a border */
  --surface:#FAFAFA; --surface-card:#FFFFFF; --surface-sunken:#F2F2F5;
  --surface-control:#F0F0F3; --surface-control-hover:#E7E7EC;
  --surface-nav:var(--surface-card); --surface-topbar:var(--surface-card);
  /* Ink — only the first two may paint a character */
  --ink:#4D4D4D;        /* 6.61:1 worst — all prose and headings */
  --ink-muted:#636363;  /* 4.70:1 worst — the one muted TEXT colour */
  --ink-mark:#767680;   /* 3.52:1 worst, 4.49:1 best — marks and glyphs, POLICED */
  --ink-rule:#ADADB4;   /* 2.23:1 at best — rules and dead controls, POLICED */
  --ink-on-brand:#FFFFFF;                /* 4.95:1 on --brand-solid */
  /* Lines — this design draws almost none */
  --hairline:#E6E6EA; --hairline-strong:#D6D6DC;
  --edge:#8F8F95;       /* 3.08:1 — the one border that carries meaning: a popover ring */
  --focus-ring:var(--brand-fill);
  /* Semantic hues: --x text-safe (4.5:1) · --x-fill graphic (3:1) · --x-tint chip ground */
  --brand:#A92D9D;   --brand-fill:#BD32AF;   --brand-tint:#BD32AF24; --brand-solid:#BD32AF;
  --accent:#823CD7;  --accent-fill:#9256DC;  --accent-tint:#9256DC24;
  --success:#3A732B; --success-fill:#4A9438; --success-tint:#4A943824;
  --caution:#7E6110; --caution-fill:#A27D15; --caution-tint:#A27D1524;
  --warning:#A74F11; --warning-fill:#D16315; --warning-tint:#D1631524;
  --error:#C02A4B;   --error-fill:#D64363;   --error-tint:#D6436324;
  --info:#166F88;    --info-fill:#1D90AF;    --info-tint:#1D90AF24;
  --neutral:#67676F; --neutral-fill:#71717A; --neutral-tint:#71717A24;
  --slate:#566786;   --slate-fill:#5B6E8F;   --slate-tint:#5B6E8F24;
  /* Order state — aliases, all three members each (--st-x, --st-x-fill, --st-x-tint) */
  --st-draft:var(--neutral); --st-brief-ready:var(--info); --st-lyrics-ready:var(--info);
  --st-authorized:var(--accent); --st-generating:var(--caution); --st-delivered:var(--success);
  --st-failed:var(--error); --st-cancelled:var(--slate); --st-held:var(--brand);
  /* Pipeline status — likewise */
  --pg-started:var(--info); --pg-retrying:var(--caution); --pg-succeeded:var(--success);
  --pg-degraded:var(--warning); --pg-failed:var(--error); --pg-skipped:var(--neutral);
  --retryable:var(--caution); --terminal:var(--error);
  /* Elevation — Gogo's scale verbatim; a card is a whisper of shadow and nothing else */
  --shadow-2xs:0px 3px 4px #0000000A;  --shadow-xs:0px 3px 8px #0000000A;
  --shadow-md:0px 3px 12px #0000000A;  --shadow-lg:0px 3px 20px #0000000A;
  --shadow-2xl:0px 3px 28px #0000000A; /* + a -darker variant of each at #0000000F */
  --shadow-card:var(--shadow-xs); --shadow-card-hover:var(--shadow-md-darker);
  --shadow-overlay:0 0 0 1px var(--edge), 0px 3px 28px #0000001F;
  --ring-brand:0 0 0 1px var(--brand-fill); /* + --ring-error, --ring-success */
  /* Geometry — Gogo's radius scale verbatim. Soft and round; nothing has a 4px corner */
  --r-4xs:.5rem; --r-3xs:.65rem; --r-2xs:.75rem; --r-xs:.785rem; --r-sm:.875rem; --r-md:1rem;
  --r-lg:1.125rem; --r-xl:1.375rem; --r-2xl:1.5rem; --r-3xl:1.75rem; --r-4xl:2rem;
  --r-full:9999px;
  --r-card:var(--r-3xl);    /* 28px */   --r-button:var(--r-md);  /* 16px */
  --r-control:var(--r-sm);  --r-pill:var(--r-full);
  /* Motion — unchanged */
  --d-instant:90ms; --d-fast:140ms; --d-base:200ms; --d-slow:320ms; --d-pulse:1600ms;
  --ease-standard:cubic-bezier(.2,0,0,1); --ease-decel:cubic-bezier(0,0,0,1);
  --ease-emphasis:cubic-bezier(.2,0,0,1.2);
  /* Layout — the rail nests children, so it is wider, and the whole console is airier */
  --nav-w:264px; --nav-w-collapsed:76px; --topbar-h:68px; --row-h:44px; --row-h-compact:34px;
  --gutter:24px; --card-pad:24px;
  /* --font-sans / --font-heading / --font-mono are NOT here. They live in
     admin-ui/src/styles/fonts.css beside the @font-face rules that self-host the faces they
     name — the value and the binary have to change together. */
}
[data-theme="dark"] {   /* hand-built at Gogo's dark values, not a programmatic inversion */
  --surface:#202022; --surface-card:#26262A; --surface-sunken:#1A1A1C;
  --surface-control:#2C2C31; --surface-control-hover:#33333A;
  --ink:#E6E6E6;       /* 8.00:1 worst */   --ink-muted:#B2B2BA;  /* 4.74:1 worst */
  --ink-mark:#9A9AA2;  /* 3.58:1 worst */   --ink-rule:#5E5E66;   /* 2.71:1 at best */
  --hairline:#313138; --hairline-strong:#404048; --edge:#767680;  /* 3.35:1 */
  --brand:#DC7AD2;   --brand-fill:#CD42BF;   --brand-tint:#CD42BF30;
  --accent:#B68DE8;  --accent-fill:#9A62DF;  --accent-tint:#9A62DF30;
  --success:#77C464; --success-fill:#77C464; --success-tint:#77C46430;
  --caution:#E6B93D; --caution-fill:#E6B93D; --caution-tint:#E6B93D30;
  --warning:#EE914F; --warning-fill:#ED8B45; --warning-tint:#ED8B4530;
  --error:#E38297;   --error-fill:#D84B6A;   --error-tint:#D84B6A30;
  --info:#47C0E1;    --info-fill:#47C0E1;    --info-tint:#47C0E130;
  --neutral:#A0A0A7; --neutral-fill:#7D7D87; --neutral-tint:#7D7D8730;
  --slate:#92A1B9;   --slate-fill:#6A7DA0;   --slate-tint:#6A7DA030;
  /* Gogo's 4%-black shadows are invisible on a #202022 ground. Same geometry, deeper alpha. */
  --shadow-xs:0px 3px 8px #00000052;  /* …and the rest of the scale, likewise */
  --shadow-overlay:0 0 0 1px var(--edge), 0px 3px 28px #0000008A;
}
@media (prefers-reduced-motion: reduce) {
  :root { --d-instant:1ms; --d-fast:1ms; --d-base:1ms; --d-slow:1ms; --d-pulse:0ms; }
}
```

**`--brand` and `--brand-solid` are different magentas on purpose.** `--brand-solid:#BD32AF` is
Gogo's `--primary 306 58% 47%` unmodified, and it is the primary-button fill because white on it is
4.95:1. `--brand:#A92D9D` is five points darker because brand-coloured TEXT also has to clear 4.5:1
when it sits on `--brand-tint`, which is exactly what Gogo's secondary button does. The same split —
a text-safe member and a graphic member — is why the light palette is hand-built out of Gogo's hues
pushed down in lightness rather than derived by a filter: regenerating it programmatically
reintroduces the contrast failure it exists to remove.

**Type:** `hero` 40/44 700 −0.02em · `metric` 28/34 700 · `h1` 26/34 700 · `h2` 18/26 600 · `h3`
15/22 600 · `body` 14/22 400 · `body-sm` 13/20 400 · `button` 14/20 500 · `caption` 11/16 600 0.06em
uppercase · `mono` 13/20. Headings and numerals are set in `--font-heading`; everything else in
`--font-sans`. Every numeric column and metric gets `font-variant-numeric: tabular-nums
slashed-zero`.

**Status pills are never colour alone** — glyph + text + colour, so they survive greyscale and a bad
projector: `○` draft, `◔` brief_ready, `◑` lyrics_ready, `◆` authorized, `◉` generating (the only
animated one), `✓` delivered, `✗` failed, `⊘` cancelled, `⚑` held. Error badges add `↻` retryable
(caution rule) vs `■` terminal (error rule), driven by `BayramError.is_retryable` — the operator's real
decision is "is retrying worth anything", and that is one glyph away. The pill puts its WORD in
`--ink` on an `--st-x-tint` ground and the hue in the glyph, so the word clears 4.5:1 whatever the
state is.

**Chart palette:** `--c-1..8`, light `#4585D9 #D8602C #2A938E #BD32AF #699031 #9256DC #A27D15
#33944D`, dark `#5690DC #DF7A4E #4CCDC6 #CD42BF #87BA40 #9A62DF #E6B93D #40BA60`; slots are ordered
so no two neighbours are within 90° of hue. Sequential brand ramp `#F6E2F4 → #7E2274` (dark
`#2B1F2B → #E9A9E2`); diverging `--error-fill / --neutral-fill / --success-fill`. Every slot is a
GRAPHIC token — 3:1 on every surface, never 4.5:1 — so a series label is `--ink`/`--ink-muted` and
never the series colour. Semantic series (delivered/failed) always use the **status** colours, never
the categorical ramp: green must mean the same thing everywhere. Note that `--success` and `--error`
are 1.00:1 against *each other* in the light palette, because both were pushed to the same lightness
to clear AA on a white card — which is exactly why series must also differ by dash pattern and marker
shape, and why hue is never the only channel.

### 11.4 Component inventory

**Layout:** `AppShell`, `NavRail`, `TopBar`, `CommandPalette`, `PageHeader`, `PlayerBar`.

**Data:** `DataTable<T>` (keyset paging, sticky header, `j/k` nav, density), `FilterBar` (URL-backed
removable chips), `CursorPager`, `JsonViewer` (collapsible, copy-path, client-side redaction of
`*api_key`/`*token`/`*secret`/`*_url` as belt-and-braces), `CodeBlock`, `Sparkline`, `StatTile`,
`StateDistributionBar`, `ChartFrame`, `TimeRangePicker`, `Timestamp`.

**Domain:** `StatusPill`, `ErrorCodeBadge`, `PipelineTimeline`, `TimelineSourceLegend`,
`StageMiniBar`, **`NameText`**, `CodepointTooltip`, `PurgedValue`, `PurgedRange`, `RetentionClocks`,
`CorrelationChip`, `OrderRefChip`, `TelegramUserChip`, `AudioPlayer`, `AssetCard`, `LiveFeed`,
`AttentionList`, `StrategyBakeoffChart`, `SimilarityHistogram`, `ChatTranscript`, `MessageBubble`,
`ConfigField`, `ConfigDiffDialog`, `ModerationCard`, `AuditRow`, `RetryOrderDialog`,
`ConfirmDangerDialog`, **`RevealDialog`** (carries the `reasonCode` select, optional `reasonRef`,
optional `reasonText`, and **shows the record cost of the reveal against the remaining budget before
the operator confirms**), `RevealBudgetMeter`.

**Utility:** `AsyncBoundary` (the six states below), `ErrorBoundary`, `EmptyState`, `ErrorState`,
`PermissionGate` (role-based **hiding**, not disabling — a disabled button nobody can explain is
worse than an absent one), `CopyButton`, `KeyboardShortcuts`.

**The six states, from one `AsyncBoundary`:** Skeleton (matching final dimensions exactly, 1.2 s
shimmer, never a centred spinner) · Empty-virgin · Empty-filtered (distinct copy naming the filter
count + Clear) · Error (inline, scoped, keeps surrounding data, shows the code and a copyable
correlation id) · **Stale** (last-known at 70% opacity with a `stale 42s` chip — a dashboard that
blanks on a failed poll is worse than one showing stale numbers labelled stale) · **Purged** (lock
glyph + the purge stamp + which clock did it; never a blank, never an error).

Two components carry non-obvious weight. **`NameText`** is the only way a name reaches the DOM: it
emits `<span lang="uz-Latn" dir="ltr">`, and the SPA never calls `.normalize()`, `toLowerCase()`,
`localeCompare()` or `text-transform` on user content — one accidental call destroys the datum this
product exists to get right. (An earlier draft of this paragraph said `NFKD` folds U+02BB to a plain
apostrophe. **It does not**: NFC, NFD, NFKC and NFKD are all the identity for U+02BB and U+02BC,
neither codepoint has a decomposition mapping, and `src/components/domain/codepointIntegrity.test.tsx`
proves it. What actually destroys these names is case folding — `Gʻulom` → `gʻulom` — and
`localeCompare`, which equates strings this product must keep distinct, and `text-transform`, which
alters what the operator reads with no trace in the data. `normalize` stays banned as the entry point
to that class, not because it eats the turned comma. The rule was always right; only its stated
reason was wrong, and a wrong reason is how a correct rule gets argued away.) (banned by an ESLint
`no-restricted-syntax` rule inside `components/domain/`). Its codepoint toggle renders
`O<sub>U+02BB</sub>ktam` — when a verification fails, the first question is which apostrophe the
customer typed, and the answer is invisible at 14px. **`RetryOrderDialog`** turns the three retry
traps into three sentences and computes "what runs" from whether `get_kit` would succeed, because a
replay and a full regeneration look identical from the button and are wildly different in cost.

### 11.5 Real-time

**v1: tiered polling. v1.1: SSE for the live feed only. WebSocket: never.**

There is no event bus to subscribe to. `events.py`'s docstring says "Redis pub/sub, in practice", but
the only production `ProgressSink` is `TelegramProgressSink`, which edits one Telegram message. And
`KitPipeline._replay` returns the stored kit **before the reporter is constructed**, so a retried
order that replays emits **zero** progress events — a stream-only dashboard would show a successfully
re-delivered order as never having run. That alone rules out stream-as-sole-source.

One consolidated endpoint, `GET /ops/pulse`, returns every dashboard counter so the dashboard is one
request per tick. Intervals, all gated on `document.visibilityState === 'visible'` with
`refetchIntervalInBackground: false`, `placeholderData: keepPreviousData` (this is what makes "stale,
not blank" work), and exponential backoff to 60 s on error:

| Surface | Interval |
|---|---|
| `/ops/pulse`, `/ops/feed` | 5 s |
| Order detail | 3 s while `state ∈ {authorized, generating, held_for_review}`, else off |
| Moderation queue + nav badge | 10 s |
| Orders list | 15 s, only when no row is expanded |
| Everything else | on demand + `refetchOnWindowFocus` |

The `LIVE` pill reads `dataUpdatedAt` and the query's error count — it is not a separate connection
concept. Green pulsing <10 s, amber 10–30 s or retrying, red >30 s with a countdown, slate when
paused.

The v1.1 upgrade is two small changes and **no frontend restructuring**: a `RedisFanoutProgressSink`
implementing the existing `ProgressSink` protocol publishing serialised `ProgressEvent`s to
`bayram:progress` (the worker already holds Redis; `redis>=5,<6` is already a dependency), and an
`EventSource` on `/api/v1/stream` that pushes into the **same TanStack Query cache** via
`setQueryData` while the poll drops to 30 s as a backstop. The backstop is mandatory: SSE is
fire-and-forget and a subscriber disconnected during a publish never learns.

---

## 12. Security and privacy

### 12.1 Threat → mitigation

| # | Threat | Mitigation |
|---|---|---|
| T1 | Credential stuffing / spraying on the one login route | argon2id (`time_cost=3, memory=64MiB, parallelism=4`, all `BAYRAM_ADMIN_ARGON2_*`), **hashed in `asyncio.to_thread`** — 64 MiB and ~50 ms on the event loop blocks every other request, and ruff's `ASYNC` ruleset is there to catch it; **no user enumeration** — an unknown username is verified against a module-level dummy hash so timing and response match; **two Redis counters**: a strict one keyed on `(username, client_ip)` at 10/15 min and a looser global-per-username ceiling at 100/15 min. The draft keyed the strict counter on the attacker-supplied username alone, which lets anyone who knows an operator's username keep that account permanently 429'd — the same DoS primitive the draft rejected a permanent lockout for, with a duty cycle, biting hardest during an incident. Both counters return 429 **without performing the argon2 verify**, or the limiter becomes the CPU-exhaustion vector. A request carrying a currently-valid session for that username is exempt. Every per-username trip logs WARNING naming the username, so the DoS is visible rather than merely effective. `is_active=false` is the hard stop and revokes sessions **and their Redis mirrors** in the same transaction; **no signup route** — the first account comes from `python -m bayram.admin.bootstrap` (§12.6) |
| T2 | Session theft | **Opaque server-side session, not JWT.** Revocation is a stated requirement (block, purge, config commit); a JWT cannot be revoked and the standard fixes rebuild a session store anyway. 256-bit `token_urlsafe(32)`, only `sha256` stored. Cookies named `__Host-bayram_session` and `__Host-bayram_csrf`, which forces `Secure`, `Path=/` and no `Domain` and structurally prevents subdomain injection. **`SameSite=Lax`, not `Strict`** — see the note below. `Secure` is enforced whenever `environment != "dev"`, not only in prod, and the lifespan **refuses to start** otherwise, mirroring the fake-provider interlock at `providers.py:81`. Idle 1 h sliding + absolute 12 h, both server-side. Rotation on login and on role/password change. IP and UA recorded, **not enforced**. **Action-scoped step-up** (§5.3) before every reveal, purge, force-deliver, block and config commit, with grace 0 for purge and config |
| T3 | IDOR / cross-resource id smuggling | Every path param typed `UUID`/`int` — a non-UUID is 422 before handler code runs, and one identifier per namespace (§6.1). One `require(Permission.X)` dependency applied **at router level**, never per-handler; a route-enumerating test asserts every route outside the exempt set carries exactly one. Resolve-then-check: the row loads, then the *serializer* decides what the role may see, so a VIEWER on a valid order gets 200-with-masked, not 403 and not the data. Order ids are UUIDv5 over a draft fingerprint — deterministic, so they are never treated as a capability |
| T4 | Path traversal on asset serving | The API accepts an **asset UUID only** — never a filename, key or path. The key is reconstructed server-side as `orders/{order_id}/{Path(row.path).name}` and resolved **only** through the `Storage` protocol's new `open_range` seam (§12.7), which delegates to `LocalFileStorage._resolve` (`storage.py:66-79`) — already rejecting absolute keys, `\`, NUL and `.`/`..` and re-checking containment. We do not re-implement confinement and we do not reach into a private method. `Path(row.path).name` is additionally regex-validated `^[A-Za-z0-9._-]{1,128}$`, because DB-sourced data is untrusted on read (rule 9). `Content-Type` from `assets.mime`, allowlisted to `{audio/mpeg, audio/ogg}` for `/stream` — **`text/plain` is no longer streamed at all** (§12.1 T7). Anything else is 415. Range/206 streams in 64 KiB chunks, never `LocalFileStorage.get` (which reads whole objects). Volume mounted `:ro` |
| T5 | **SSRF via the config editor** | `*_base_url` fields are hostnames the worker attaches a live API key to. They are **absent from the allowlist**, so the API has no code path that can set them. Secondary surface closed by construction: the admin process holds no `httpx` client, no vendor key and no URL-fetching endpoint, webhook tester or avatar proxy anywhere |
| T6 | Log injection | `JsonFormatter` serialises one object per record, so newlines in a value are escaped. **Rule: user-controlled text is passed only via `extra=`, never interpolated into the message string,** which is always a constant. `redact()` truncates at 2000 chars. The request line logs the route **template**, never the raw path or query string — the key-name redaction matches on the extra key, not on URL substrings, so a `?token=` would sail through |
| T7 | XSS via names, notes, lyrics, chat bodies — **and via a sniffed asset stream** | React escapes by default; `dangerouslySetInnerHTML` is banned by `react/no-danger: error` in CI. No markdown renderer, no HTML sanitiser — each is a bypass. Outbound chat bodies are HTML (`parse_mode=HTML`, escaped params), stored verbatim with `parse_mode` recorded, rendered **as text**. **The draft's `text/plain` lyric stream was a stored-XSS primitive that bypasses React entirely**: a same-origin response whose body is customer-written free text (up to 3000 chars), served without `nosniff`, is a document the browser may sniff as HTML and render at the panel's origin under the operator's session cookie — and `script-src 'self'` does not stop inline event handlers in it. So: `X-Content-Type-Options: nosniff` on **every** admin response; lyric text is served as `application/json` from `/assets/{id}/text`; any non-audio stream that survives carries `Content-Disposition: attachment`. CSP: `default-src 'self'; script-src 'self'; style-src 'self' 'nonce-<per-response>'; img-src 'self' data:; media-src 'self'; connect-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'; form-action 'none'; worker-src 'none'`. Plus `Referrer-Policy: no-referrer`. No CDN links for fonts or scripts — every face is self-hosted from this origin, so fonts load under `default-src 'self'` (there is no separate `font-src` directive). **The faces named in the original draft were Inter and JetBrains Mono, and the coverage claim attached to them was never verified against the binaries** — the reskin's font work reports that JetBrains Mono lacks U+02BB and the Uzbek Cyrillic letters Ғ/Қ/Ҳ entirely, so that sentence should not be cited to restore it to `--font-mono`. The reskin ships Mulish (body), Urbanist (headings) and Noto Sans Mono (ids, hashes, payloads), all SIL OFL, plus a vendored symbol face for §11.3's glyphs. Coverage is no longer asserted in prose: `admin-ui/src/assets/fonts/README.md` records it as read out of the binaries, and `admin-ui/e2e/font-coverage.spec.ts` re-measures it in a real browser on every `make ui-e2e` — including that Urbanist has NO Cyrillic, which is why `--font-heading` names Mulish behind it |
| T8 | CSRF on operational actions | Three layers, because CSRF is the class where one control failing silently is normal: `SameSite=Lax` (blocks every cross-site POST/DELETE); **exact `Origin` match** against `admin_public_origin` on every non-GET, with a missing `Origin` on a non-GET rejected; and **`X-CSRF-Token` compared against the stored `admin_sessions.csrf_token`** with `hmac.compare_digest`. The draft specified plain cookie-vs-header double-submit, which never uses the column it defines and falls to cookie injection from a sibling subdomain or a MITM on any `http://` host under the same registrable domain. The cookie is only the transport that hands the SPA its token. All mutations are POST/DELETE — no state change on GET, ever, asserted by the same route-enumerating test, which is also what makes `Lax` safe. Destructive actions additionally need step-up, which no cross-site request can satisfy |
| T9 | Privilege escalation | `Role`/`Permission` `StrEnum`s with a single `Final[Mapping[Role, frozenset[Permission]]]` — a pure data table, **no wildcard**, because a wildcard is how a new permission silently lands on a role nobody reviewed. `role`, `is_active` and `password_changed_at` are read from the DB row on **every** request, never from the session or the Redis mirror, so a demotion or a deactivation takes effect immediately. An admin can never change their own role or `is_active`; **at least one active OWNER must always remain** — enforced against self-demotion *and* against demotion or deactivation by another OWNER. No impersonation feature |
| T10 | Data in browser caches | `Cache-Control: no-store` on every `/api/**` response and on asset streams. SPA bundles get normal immutable caching (they hold no data) |
| T11 | Resource exhaustion | Every list keyset-paginated with `limit ≤ 200`; admin pool `5+5`; login limiter runs before the hash; asset streaming is chunked; reveal is budgeted in records (§12.3) |
| T12 | Admin-host compromise reaching vendor spend or customers | **`AdminSettings` (§4.2): there is no vendor field and no `telegram_bot_token` field on the model the admin process loads**, so a key in that host's environment is unreadable by any code path, and prod boot refuses if one is present. No `httpx` client, no `ProviderSet`, no `Bot`. Operational actions are queue enqueues. Blast radius is the database and the session store — which is now a true statement rather than an aspirational one |
| **T13** | **Client IP is the proxy's IP** | The plan binds to `127.0.0.1` and names a reverse proxy with an IP allowlist as the primary compensating control for having no MFA — and the draft never mentioned `X-Forwarded-For`. Behind a proxy, `request.client.host` is the proxy for every request: the per-IP limiter collapses into one global bucket shared by operators and attackers, every `ip` column records the proxy, and R4's own detection signal ("a session whose `last_ip` jumps countries") can never fire. Trusting the header unconditionally is worse — an attacker rotates it per request and bypasses the limiter entirely. So: `admin_trusted_proxy_hops` (default 0) and `admin_trusted_proxies` (explicit CIDR list). The client IP is derived by walking `X-Forwarded-For` **right-to-left, skipping exactly `hops` entries**, and only when the peer address is inside `admin_trusted_proxies`; otherwise `request.client.host` is used and the header ignored. Tests: no proxy; one trusted proxy; a spoofed XFF from an untrusted peer (must be ignored) |

**Why `Lax` and not `Strict`.** `SameSite=Strict` means a top-level navigation from anywhere but the
panel carries no session cookie — so every filter URL pasted into Slack, every link in an alert and
every bookmark opened from another app lands on a login screen and loses the deep link. §11.2 builds
URL-backed filter state specifically to enable that workflow, and operators would work around
`Strict` with something worse (a second long-lived cookie, a token in the URL). `Lax` still blocks
every cross-site POST/DELETE, and T8's `Origin` check plus the session-bound CSRF token cover state
changes.

### 12.2 RBAC matrix

Four roles. The distinction that matters is between *seeing a customer's words* and *changing the
system's state*: a support person needs the first and must not have the second, while a queue
operator needs the second and often not the first. **M** = read masked · **R** = read unmasked ·
**W** = write · **A** = audited reveal · **S** = step-up.

| Capability | VIEWER | SUPPORT | OPERATOR | OWNER |
|---|---|---|---|---|
| Login, logout, own sessions, step-up | W | W | W | W |
| Dashboard, metrics, aggregates | M | M | M | R |
| Orders / users / attempts / assets list + detail | M | M | M | M |
| Chat conversation index (metadata) | M | M | M | M |
| Wizard-state projection (presence + counts only) | M | M | M | M |
| Moderation queue (list) | M | M | M | M |
| Config read (secrets and DSNs absent at every role) | M | M | M | M |
| Retention status | M | M | M | M |
| **Reveal a name / note / lyric / transcript / chat body / wizard draft** | — | A+S | A+S | A+S |
| **Stream audio or read lyric text** | — | A+S | A+S | A+S |
| Order retry / re-enqueue / cancel | — | — | W | W |
| Order force-deliver | — | — | W+S | W+S |
| Block / unblock a user | — | — | W+S | W+S |
| Moderation open (reveal) / approve / reject | — | — | A+S / W+S | A+S / W+S |
| Trigger a retention sweep | — | — | W | W |
| Audit log read | — | — | M | R |
| Reveal-volume dashboard | — | — | R | R |
| Aggregate export (no personal data) | — | — | W | W |
| **Purge a user's personal data** | — | — | — | W+S (fresh) |
| **Config validate / commit / rollback** | — | — | — | W+S (fresh) |
| Single-order evidence pack export | — | — | — | W+S |
| Audit export | — | — | — | W+S |
| Admin roster read (`GET /admins`) | — | — | — | W |
| Admin account writes (create / patch / reset password), revoke others' sessions | — | — | — | W+S |

Every `A` cell routes through the **same** `POST /reveal` endpoint. One reveal path, one audit shape,
one budget — multiple reveal endpoints is how one of them ends up unaudited.

The last two rows were **one** row — `Admin account CRUD, revoke others' sessions | W+S` — until it
was split here. §6.8's endpoint table is the authority on this one and it never collapsed them:
`| GET | /admins | List | W |` carries no `+S`, while each of `POST /admins`, `PATCH /admins/{id}`,
`POST /admins/{id}/reset-password` and `DELETE /admins/{id}/sessions` carries `W +S` explicitly. The
collapsed row read literally made the roster unreachable by every role, the OWNER included: the
router-level guard holds no subject and therefore no grant, so it answers `STEP_UP_REQUIRED` to any
cell carrying a step-up and never consults one. The read is `admin.read`; the four writes keep
`admin.manage`.

### 12.3 Redaction policy and the reveal budget

Masking is **server-side**, in `src/bayram/admin/serializers/redaction.py`, applied at the response
boundary. Not a CSS blur, not a client toggle: an unmasked value must never be in a JSON payload the
operator did not explicitly request.

| Field | Default | Reveal? |
|---|---|---|
| `recipient_name_display` / `_raw` | First **grapheme cluster** + `•••` (`Intl.Segmenter`; never byte slicing — U+02BB is multi-byte) | Yes |
| `recipient_lookup_key`, `recipient_candidates` | Hidden; candidate count + strategies shown | Yes |
| `briefs.note` | Hidden; char count, language, `note_purged_at` shown | Yes |
| `briefs.approved_lyrics` | Hidden; line count + generated-vs-pasted shown | Yes |
| `stt_transcript`, `name_candidate_text` | Hidden; `match_confidence`, `is_name_verified` shown | Yes |
| `chat_messages.body` | Hidden; direction, step, kind, length, `callback_data` shown | Yes, **paged at ≤50 bodies per reveal** |
| **FSM wizard-draft fields (Redis)** | Hidden at every role; only key presence, char counts and the step are exposed, via a key **allowlist** in the serializer | Yes, `subjectType="wizard_draft"` |
| `moderation_reviews.flag_detail`, `decision_note` | Hidden | Yes |
| Audio assets | Metadata only. **No player until revealed** — a greeting says the name aloud, so playing *is* a reveal | Yes |
| `telegram_user_id` | `•••••123` | Yes |
| Enums, states, timestamps, costs, latencies, error codes, strategies, ranks | Always visible | n/a |
| `password_hash`, session tokens, CSRF tokens, any `*_api_key`, `telegram_bot_token`, `database_url`, `redis_url`, `admin_audit_hmac_key` | **Never returned at any role, revealed or not** | **No** |

**Reveal flow.** Body carries `{subjectType, subjectId, fields[], reasonCode, reasonRef?,
reasonText?, limit?, cursor?}`. `reasonCode` is required and comes from the closed
`AuditReasonCode` enum; `reasonText` is optional, capped at 500 chars, control chars stripped, and
lives on the audit log's 90-day reason clock. Requires the permission **and** a valid step-up scoped
to `reveal` + this subject. **Writes the audit row before the read**, so a reveal that then errors is
still attributable. Returns plaintext for the named fields only, not the whole object.

**The budget is counted in records, not requests, and that is the correction the review forced.** A
name reveal unmasks one string; a conversation reveal unmasks every stored body for that user — up to
90 days of transcript containing the recipient's name, the note, the full lyric and everything the
customer typed. At 30 requests/hour that would have been 30 complete conversations per hour, ~700 a
day, all inside policy and all logged as 30 rows — bulk export of personal data through the reveal
endpoint, defeating the export prohibition that R1 identifies as the reason the whole design exists.

So:

- Every reveal charges `record_count` units against `admin_reveal_records_per_hour` (default 200) per
  actor, tracked in Redis and **persisted on the audit row** so `/audit` and the dashboard measure
  exposure rather than clicks.
- A conversation reveal returns **at most 50 bodies**; more requires a fresh reveal with a
  `nextCursor`, each one charged and each one audited.
- Conversation reveals additionally have their own daily ceiling,
  `admin_reveal_conversations_per_day` (default 20).
- Exceeding either returns 429 `REVEAL_BUDGET_EXHAUSTED` with a WARNING log naming the actor. The
  limit is a **detection** control as much as a limit: bulk reveal is what a compromised session
  looks like, and `/metrics/reveals` charts records-per-actor over 7 days on the dashboard.

**Audio caveat.** An `<audio>` element issues many range requests. The router audits the **first**
per `(actor, asset)` per 10-minute window, keyed in Redis; the audit UI says so, so "1 play" is not
read as "1 HTTP request".

`identity_purged_at` is **always** displayed. "No name" and "name purged on schedule 2026-05-14" are
different facts and only one is defensible.

**Exports.** Bulk export of personal data is **forbidden**. No endpoint returns more than one
subject's names, free text, chat bodies or audio. An export is a copy that leaves every retention
clock in this system; `purge.py` cannot reach a CSV on someone's laptop, and one export defeats the
whole retention design permanently. Allowed: aggregate CSV/JSON with no names, no free text, no
telegram ids, no order ids (OPERATOR); a single-order evidence pack as **JSON only**, OWNER-only,
5/day, step-up, mandatory reason code, watermarked with *"This export is outside the system's
retention clocks. Delete it when the matter closes."*; and the audit log itself.

**CSV formula injection.** Operator-supplied free text (`reason_text`, `decision_note`, config
`note`) is stripped of C0 control characters and then emitted into CSV — and a value beginning with
`=`, `+`, `-`, `@`, tab or CR is interpreted as a formula by Excel, LibreOffice and Google Sheets,
the exact tools an operations team opens these in, giving arbitrary command execution via DDE on the
analyst's machine. Every CSV cell is quoted and any cell whose first character is in `=+-@\t\r` is
prefixed with a single quote. The audit export is **JSON only**, where the class does not exist. Unit
test with a `=cmd|' /C calc'!A0` reason.

### 12.4 The audit log's immutability — what actually holds

Three layers, and this section says plainly which of them are deployed.

**1. No code path writes UPDATE or DELETE** against `admin_audit_log` except two named sweeps. The
only accessor is `AdminAuditRepository.append()` plus `_purge_audit_reasons` (nulls `reason_text`)
and `_purge_audit_log` (deletes past 730 days). No ORM relationship, no cascade. `actor_id` is
`ON DELETE RESTRICT`.

**2. Database privileges — and the two-role requirement that makes them mean anything.** The repo
has exactly one Postgres role today (`docker-compose.yml`: `POSTGRES_USER: hbd`) and
`migrations/env.py` reads `BAYRAM_DATABASE_URL` through `bayram.config`, so migrations run as the
application role, which is therefore the table **owner** — and revoking a privilege from a table's
owner is reversible by that owner with one `GRANT`. It would also have blocked the plan's own
730-day sweep. The draft's escape hatch ("a separate owner role or a `SECURITY DEFINER` function")
was new infrastructure in no phase and no file list.

Phase 1 ships it:

- `BAYRAM_DB_MIGRATION_URL` (owner role) used by `migrations/env.py` when set;
- `docker-compose.yml` init SQL creating `hbd_app` and granting it everything except
  `UPDATE, DELETE, TRUNCATE` on `admin_audit_log`;
- migration `0007`, guarded on `dialect.name == "postgresql"` **and** a non-empty
  `BAYRAM_ADMIN_AUDIT_DSN`, issuing the `REVOKE` **and** creating
  `hbd_purge_audit_log(cutoff timestamptz, lim int) RETURNS int` as `SECURITY DEFINER` owned by the
  migration role. The REVOKE and the function that legitimately works around it ship in **one**
  migration so neither can exist without the other — otherwise the predictable outcome is the REVOKE
  landing, the sweep silently failing every hour, and the table growing without bound while holding
  operator free text;
- `_purge_audit_log` calls the function on Postgres and does a plain `DELETE` on SQLite;
- `PurgeReport` and `purge_runs` gain `audit_rows_deleted`, so a sweep that does nothing is visible
  on `/retention`;
- an integration test asserts the sweep actually deletes **under the revoked role**.

**If `BAYRAM_ADMIN_AUDIT_DSN` is empty, the migration skips the REVOKE, logs a WARNING, and
`/audit/verify` reports `chainProtection: "hmac-only"`, which the panel renders verbatim.** A control
that is not deployed is reported as not deployed.

**3. HMAC chain, not a bare hash.** `entry_hash = HMAC-SHA256(key, prev_hash || canonical_json(row))`
where `key` is `admin_audit_hmac_key`, held **only** in the admin process's environment and never in
the database. The draft's unkeyed `sha256` chain was recomputable by anyone who could write the
table — exactly the adversary it named — and `/audit/verify` would have reported the tamper clean.
`reason_text` is **excluded** from the canonical form, so the 90-day reason sweep does not break the
chain.

Appends take `pg_advisory_xact_lock(<const>)` so the chain is linear under concurrency — the one
place in this codebase worth an advisory lock, since it has none today and this is the only strictly
ordered table. On SQLite the lock is skipped. `GET /audit/verify` walks the chain and reports the
first break. Chain-head anchors are written to `audit_chain_anchors` **and emitted as a log line**
(§5.5), so the head exists outside the database it protects.

Integration test: mutate a row directly with SQL, then assert `/audit/verify` reports the break at
that `seq`.

**Never logged:** passwords in any form (not the hash, not a prefix, not a length), session tokens,
CSRF tokens, the HMAC key, any secret value, and any personal-data value. `field_names` records
*that* `briefs.note` was revealed, never what it said. Every value passes through
`bayram.logging.redact()` before persisting.

**`redact()` itself is extended in Phase 1**, because the draft noticed one gap and missed the rest.
`_SECRET_NAME_PATTERN` (`logging.py:44-47`) matches
`api_key|secret|token|password|passwd|authorization|credential|private_key` and does **not** match
`database_url`, `redis_url`, `dsn` or `connection_string`; `_SECRET_VALUE_PATTERNS` (`:50-55`) has no
pattern for `scheme://user:password@host` and its `\bsk_[A-Za-z0-9]{20,}\b` misses both an OpenRouter
`sk-or-v1-…` key and a current OpenAI `sk-proj-…` key (hyphens, not underscores). The panel multiplies
the number of call sites passing config values to logs and to the audit log. So:

```python
# added to _SECRET_NAME_PATTERN
database_url|redis_url|dsn|connection_string|conn_str|hmac_key
# added to _SECRET_VALUE_PATTERNS
re.compile(r"\b[a-z][a-z0-9+.-]*://[^/\s:@]+:[^/\s@]+@")      # DSN userinfo
re.compile(r"\bsk-[a-z0-9-]{2,}-[A-Za-z0-9_-]{20,}\b")        # sk-or-v1-…, sk-proj-…
```
with a unit test asserting a production-shaped DSN and one key of each vendor format are masked.

**Retention: 730 days** for the row, **90 days** for `reason_text`, with the truncation point recorded
in an `audit_chain_anchors` row so a deleted prefix is not confused with tampering. Two years is
longer than any data clock in the system, which is the point: the accountability record for a purge
must outlive the data it purged.

**Surfaced inline**, not only in a separate view: an order page shows that order's audit entries; a
user page shows theirs. The dashboard shows revealed-records-per-actor over 7 days as a sparkline and
a chain-status badge. An audit log nobody reads is not a control.

### 12.5 Retention summary after this work

| Data | Clock | Mechanism |
|---|---|---|
| `briefs.note`, `approved_lyrics` | 30 d | nulled, `note_purged_at` |
| `briefs` identity (6 cols) | 90 d | nulled, `identity_purged_at` |
| `generation_attempts.stt_transcript` | 30 d | nulled, `text_purged_at` |
| `generation_attempts.name_candidate_text` | 90 d | nulled, `identity_purged_at` |
| `assets` | 365 d paid / 30 d free | row deleted **and the object deleted by the cron job**, once `storage_key` is written |
| Draft orders | 14 d | order + brief + assets deleted |
| **`chat_messages.body`** | **14 d, promoted to 30 d on payment** | nulled, `body_purged_at` |
| **`chat_messages` row** | **90 d** | deleted |
| **`moderation_reviews.flag_detail`, `decision_note`** | **30 d** | nulled, `text_purged_at` |
| **`admin_audit_log.reason_text`** | **90 d** | nulled, `reason_purged_at`, excluded from the chain hash |
| **`admin_audit_log` row** | **730 d** | deleted via `SECURITY DEFINER`, chain anchor recorded |
| **`settings_versions.reason_text`** | **90 d** | nulled |
| **`purge_runs`** | **365 d** | deleted (counts only, no personal data) |
| FSM draft (Redis) | 14 d | TTL, derived from the resolved policy **at call time**, not at import |
| Admin sessions | 12 h absolute | row deleted; Redis mirror ≤ 60 s |

All eight `retention_*` fields land on `Settings` in Phase 3, **with bounds** (§8.3), and
`handle_privacy` starts rendering from `resolve_retention_policy(deps.settings)` in the same PR.

### 12.6 Bootstrap and owner recovery

The first admin comes from `python -m bayram.admin.bootstrap` — a host-local CLI requiring DB access,
which grants nothing the DB does not already grant. Three details the draft left unspecified, each a
real hole:

- **The password channel.** Read from a TTY with `getpass`. A password in `argv` is visible in `ps`
  to every user on the host and lands in shell history; an env var is readable from
  `/proc/<pid>/environ`. A non-interactive path accepts `--password-file <path>` and **refuses a file
  whose mode is group- or world-readable**. The password is never logged or echoed, asserted by test.
- **Forced rotation.** The bootstrap account is created with `must_change_password=True` and
  `password_changed_at` at epoch; the first login returns `mustChangePassword` and every route except
  `/auth/password` and `/auth/me` returns 403 until it is changed.
- **Concurrency.** "Refuses if any row exists" is a read-then-insert, and two concurrent runs both
  pass. The insert is `INSERT … SELECT … WHERE NOT EXISTS (SELECT 1 FROM admin_users)` with a
  rowcount check.

**Owner recovery.** The draft had no path back from losing the last OWNER: reset is OWNER-only,
self-service reset needs the current password, bootstrap refuses on a non-empty table, and
`ON DELETE RESTRICT` on the audit FK means the row cannot be deleted to re-enable bootstrap. One
forgotten password would permanently lock the panel, leaving `psql` as the only route back — the
manual operation the panel exists to replace, at the worst possible moment.

So `python -m bayram.admin.bootstrap --reset-owner <username>` exists. It requires host and DB access
(the same trust level as the original bootstrap), **refuses when any other active OWNER exists**,
sets `must_change_password=True`, and writes an `ADMIN_PASSWORD_CHANGE` audit row with
`actor_id=NULL, actor_username="system:bootstrap"`. Test: the two-OWNER-lockout case.

### 12.7 The `Storage` seam

`Storage` (`contracts.py:807-816`) has `put`/`get`/`signed_url`/`delete` and no streaming or resolve
member, and `LocalFileStorage._resolve` is private. The draft's T4 required resolving "only through
`LocalFileStorage._resolve`" while §15's open question 6 contemplated swapping in S3/R2 — so the
admin package would have had to reach into a private method of a concrete class (making the S3 answer
unimplementable) or duplicate confinement logic (which T4 forbids).

Phase 2 adds one public member to the protocol:

```python
class Storage(Protocol):
    ...
    def open_range(
        self, key: str, *, start: int, end: int | None
    ) -> Result[AsyncIterator[bytes]]:
        """A bounded byte range, streamed. Confinement is the implementation's job."""
```

`LocalFileStorage.open_range` is implemented on top of the existing `_resolve` and reads in 64 KiB
chunks via `asyncio.to_thread` (ruff's `ASYNC` ruleset would flag a blocking read). An S3 backend
implements it with a `Range` header. The admin service depends only on the protocol, and open
question 6 has something concrete to answer.

---

## 13. Testing and quality gates

### 13.1 Holding `mypy --strict`

- FastAPI, Starlette and `argon2-cffi` ship `py.typed`; no `ignore_missing_imports` override should be
  needed alongside the existing `json_repair`/`arq` entries. Verify at the point of adding; if one
  does not, add a targeted entry rather than loosening globally.
- **Every route handler is fully annotated including the return type, with `response_model` on the
  decorator.** No bare `dict` returns — `disallow_any_generics` rejects them and `dict[str, Any]`
  defeats the response contract anyway. Every response is a frozen pydantic model in
  `admin/schemas/`.
- Dependencies use `Annotated[T, Depends(f)]`, never the default-value form, which strict mode types
  poorly.
- The `Result[T]` boundary is already `TypeIs`-narrowed (`is_ok`/`is_err`), so the admin layer uses
  `if is_err(r): raise _to_http(r.error)` with one mapping in one place.
- `AppContainer.providers: ProviderSet | None` is handled explicitly (§4.3), not with a cast.
- Rule 15 holds: admin queries live in `src/bayram/db/admin/` and return frozen view models; the API
  never sees a mapped row. (`NameRecordRepository.lookup` already violates this; we do not add a
  second violation on the strength of the first.)

### 13.2 Holding ruff

`ASYNC` catches the two things most likely to go wrong here: argon2 hashing on the event loop (it
must be `asyncio.to_thread` — 64 MiB and ~50 ms blocks every other request) and blocking file reads
in the asset stream (hence `Storage.open_range`'s implementation). `TRY` forbids silent `except`,
which shapes the error layer into "one exception handler, no per-route try/except". Line length 100
keeps route signatures from turning into walls.

### 13.3 Holding 80% coverage

`source = ["src/bayram"]`, `fail_under = 80`, repo-wide, branch coverage. The SPA is outside `src/bayram`
and does not affect it. **The admin package does, immediately and repo-wide** — and because
`source` reports un-imported modules at 0%, the gate bites from the first commit, not just for tested
code. A half-finished `src/bayram/admin/` at 20% breaks `make check` for everyone, including people
working on the bot.

**Rule: every phase ships test-complete.** We do **not** add `omit = ["src/bayram/admin/*"]` — that
would make the most security-sensitive code in the repo the only uncovered code in the repo, and it
would not be removed on schedule.

Three structural choices make it cheap, and the third is the one the draft was missing.

1. **Routers contain no logic** — parse, call one service or query method, return; covered
   incidentally.
2. **All branching lives in services and query classes**, unit-testable against SQLite with no HTTP.
   The historically expensive parts — auth, RBAC, pagination, error mapping — are each a small pure
   module with a parametrised table test.
3. **The composition root is covered by an ASGI smoke suite.** `app.py`, `bootstrap.py`, the uvicorn
   wiring, the correlation middleware, the security-headers middleware and the CSRF dependency are
   exactly the modules that thin routers and fat services do *not* cover, and they are where a 0%
   module would sit. `httpx` is already a dependency, so `httpx.ASGITransport(app=create_app(...))`
   drives the full middleware stack end to end with no server: login → an authenticated GET → a CSRF
   failure → a 404 → logout. That one file lifts the whole root above the line.

**Phase 1 is sliced so no slice lands untested** (§14): 1a auth + health + the ASGI smoke suite,
1b the DB query layer and view models, 1c the routers and serializers, 1d the SPA. Each slice is a
mergeable PR and `make check` is green at every one. **Phase 1's acceptance names a number: the
`src/bayram/admin/` package alone must be ≥ 85%**, measured with
`coverage report --include='src/bayram/admin/*'`, not just "≥80% repo-wide".

**Five tests that pay for themselves:**

- **Route enumeration.** Iterate `app.routes`; assert every route outside `{/healthz, /readyz,
  /auth/login}` carries exactly one `require(...)` dependency, every non-GET carries the CSRF
  dependency, no GET route is registered on a handler that writes, and no two routes in one namespace
  use different parameter names for the same entity. This one class prevents the whole "someone added
  an endpoint and forgot the guard" family.
- **Permission exhaustiveness.** Every `Permission` member appears in the table for at least one role;
  every `Role` has an entry. The per-role × per-endpoint status assertions are parameterised over the
  §12.2 matrix **as data**, so the table and the tests cannot drift.
- **Config tier exhaustiveness.** `set(Settings.model_fields) == EDITABLE | READ_ONLY | SECRET`,
  **plus** a per-field-by-name assertion of SECRET membership (so `database_url` in the wrong bucket
  fails), **plus** a parametrised test that every `AdminSettings` field name is rejected by
  `POST /config/validate` with 422.
- **The purged-brief test.** A list page containing an identity-purged order returns `Ok` with
  `recipientNameDisplay=null` and `identityPurgedAt` set. The naive implementation via `to_order`
  `Err`s the whole page, so this test pins the design decision.
- **The enum-length test.** Every `StrEnum` passed to `enum_type()` anywhere in `bayram.db` has
  `max(len(m.value)) <= ENUM_LENGTH`. SQLite accepts an over-length `VARCHAR` and Postgres errors;
  this closes a real passes-in-CI/fails-in-prod divergence.

**Other unit coverage:** argon2 round trip / wrong password / rehash / unknown-user constant work and
`to_thread` offloading; session issue-refresh-revoke-expire, the `password_changed_at` kill, and the
three warm-mirror revocation tests (§5.3); rate limits including **Redis unreachable → fails closed**
and the `(username, ip)` keying; XFF derivation across the three proxy cases; redaction golden tests
including a **U+02BB grapheme test** (masking `Gʻulom` must not split the `ʻ` and must not emit
U+0027/U+2019); DSN and vendor-key patterns in `redact()`; every cross-field guard passing and
failing; the retention-lengthening gate; asset path traversal cases; `nosniff` present on a
`/assets/{id}/text` response; CSV formula escaping; chat truncation, queue overflow counting,
progress-edit exclusion, and the three-clock body test (15 d / 31 d / 91 d); `_purge_chat_bodies`
idempotency (run twice, second reports zero); `purge_user` idempotency and `exclude_order_ids`;
`/forget` during `GENERATING` leaving the workspace intact; audit chain continuity, the
in-transaction vs intent/outcome row counts per action, and no-secret assertions; `SettingsHolder`
visibility semantics; watcher fallback on `ConfigError` **and** on `ValueError`; the
`AdminSettings`-constructs-without-vendor-keys test; `build_container(with_providers=False).pipeline()`
raising `PipelineError`; two audit rows on SQLite having monotonic `seq`.

**Integration** (`@pytest.mark.integration`, excluded from `make test` and the gate): real Postgres
migration chain `0001→0013` up and down; the `REVOKE` actually denying `UPDATE` **and** the
`SECURITY DEFINER` sweep succeeding under the revoked role; a directly-mutated row detected by
`/audit/verify`; keyset pagination over 10k rows; the advisory-locked chain under concurrent appends;
real Redis pub/sub propagation and the poll backstop after a dropped subscription; a retried
`DELIVERED` order making **zero** vendor calls against a fake provider set; an expired asset's archive
file actually gone after one cron run.

**SPA:** Vitest for masking/format helpers and grapheme-safe truncation; a WCAG contrast unit test
over the token file (both palettes, pairwise); a font-coverage snapshot rendering `Oʻktam`, `Gʻulom`,
`Дилноза`, `sanʼat`; one Playwright smoke flow (login → orders → reveal with a reason code → audio
plays → logout) **run with the production CSP header applied, asserting a Radix dialog opens and is
correctly positioned**. That last assertion exists because Radix positions itself with inline
`style` attributes and `style-src 'self'` blocks them — the predictable resolution under delivery
pressure is someone appending `'unsafe-inline'`, which brings back CSS exfiltration and
clickjacking-by-overlay of exactly the confirm dialogs that gate destructive actions. Shipping
`'nonce-<per-response>'` threaded through Radix's `nonce` prop from day one makes a later
`'unsafe-inline'` a visible policy change rather than a silent fix.

CI runs `npm ci && typecheck && lint && test && build` as a **second job** with its own threshold
(start at 60% on `lib/`, `api/`, `components/domain/`) — it does not gate on the Python coverage
number, and a target that forces tests for JSX layout produces tests nobody reads.

### 13.4 New dependencies

`[project.dependencies]` += `fastapi`, `uvicorn`, `argon2-cffi`. FastAPI brings `starlette` — the only
genuinely new transitive dependency — and reuses the already-pinned `pydantic>=2.9,<3` and
`typing-extensions`. `argon2-cffi` pulls `cffi` → `pycparser`, the only C extension in the tree; on
wheels this is a non-issue, but a slim container would want a toolchain. `httpx` is already a
dependency so FastAPI's `ASGITransport` needs nothing new. Plain `uvicorn`, not `[standard]`, to keep
the tree small.

---

## 14. Delivery phases

Seven phases. Each is independently shippable and independently useful; nothing in phase *N+1* is
required for phase *N* to be worth running. **Phase 1 is sliced into four mergeable PRs** because it
creates ~25 backend modules at once and `make check` must be green at every merge (§13.3). Sizes are
revised from the draft where the review showed the work was larger than stated.

**Two files appear in the Modified list of every phase that ships DDL, and forgetting either turns
`make check` red for the whole team:**

- `tests/test_db/test_migrations.py` — `_EXPECTED_TABLES` (hardcoded six-table frozenset at `:61-63`,
  asserted with `==` at `:224` and `:270`) and `test_the_migrated_schema_matches_the_model_metadata`
  (`:228-243`). **Phase 1 derives `_EXPECTED_TABLES` from `Base.metadata.tables` and keeps a
  `_CORE_TABLES` regression guard**, after which later phases need no change to this file at all.
- `tests/test_db/test_privacy_constraints.py:149` — `tables_with_personal_data`, hardcoded, for every
  new table holding customer text.

---

### Phase 1 — Foundations + read-only panel · **XL** (four slices)

**Goal.** An operator opens `http://127.0.0.1:8080`, logs in, and sees real orders, users, generation
attempts and asset metadata from the live database — everything masked, nothing writable. The admin
process holds no vendor credential and no bot token. And the retention job starts running for the
first time, deleting archived files as well as rows.

#### Slice 1a — settings, auth, health, and the composition root

**Created**
- `src/bayram/admin/{__init__,app,settings,container,deps,errors,logging_mw,csrf}.py`
- `src/bayram/admin/security/{passwords,sessions,ratelimit,permissions,clientip}.py`
- `src/bayram/admin/middleware/{correlation,security_headers}.py`
- `src/bayram/admin/schemas/{common,auth}.py`
- `src/bayram/admin/routers/{auth,health}.py`
- `src/bayram/admin/bootstrap.py` (first-account CLI + `--reset-owner`)
- `src/bayram/db/models/{admin_user,admin_session}.py`
- `src/bayram/db/admin/{__init__,accounts,sessions}.py`
- `migrations/versions/..._0005_add_admin_users_sessions_and_purge_runs.py`
- `tests/test_admin/{test_asgi_smoke,test_passwords,test_sessions,test_ratelimit,test_clientip,test_csrf,test_permissions,test_bootstrap}.py`

**Modified**
- `src/bayram/db/enums.py` — `AdminRole`, `PurgeTrigger`
- `src/bayram/db/models/__init__.py` — register the new rows
- `src/bayram/db/engine.py` — `create_engine(..., pool_size=, max_overflow=)`
- `src/bayram/logging.py` — floor `sqlalchemy`, `sqlalchemy.engine`, `sqlalchemy.pool`, `aiogram`, `arq`, `uvicorn`, `uvicorn.access`, `uvicorn.error`; add the DSN-userinfo and `sk-…-…` value patterns and the `database_url|redis_url|dsn|connection_string|conn_str|hmac_key` name patterns
- `src/bayram/config.py` — `log_level` becomes a `Literal`; `build_settings(overrides, *, require_vendor_secrets=True)` added and `load_settings` delegates
- `tests/test_db/test_migrations.py` — `_EXPECTED_TABLES` derived from `Base.metadata`, `_CORE_TABLES` guard added
- `Makefile` (+`admin`, `admin-bootstrap`), `.gitignore`, `.env.example`, **new `.env.admin.example`**, `pyproject.toml` (deps)

**Acceptance**
- `AdminSettings` constructs and `create_app()` boots with `BAYRAM_TELEGRAM_BOT_TOKEN`,
  `BAYRAM_ELEVENLABS_API_KEY` and `BAYRAM_LLM_API_KEY` **all unset**.
- With `environment=prod` and any of those three present in `os.environ`, the lifespan **refuses to
  start** and names the variable. In dev it logs a WARNING.
- Login: 11th wrong password for the same `(username, ip)` in 15 min → 429 with **no argon2 verify
  performed**; unknown username and wrong password are indistinguishable in body and comparable in
  latency; the argon2 call runs in `asyncio.to_thread`.
- A per-username trip logs WARNING naming the username; a request bearing a valid session for that
  username is exempt from the strict counter.
- XFF: no proxy → peer IP; one trusted proxy with `hops=1` → the client IP; a spoofed XFF from an
  untrusted peer → **ignored**.
- Revoke-then-request → 401; deactivate-then-request → 401; password-change-then-old-session → 401 —
  **each with the Redis mirror still warm**.
- Cookies are `__Host-bayram_session` / `__Host-bayram_csrf`, `SameSite=Lax`; `Secure` is enforced and boot
  refuses without it whenever `environment != "dev"`.
- `X-CSRF-Token` is compared against the stored `admin_sessions.csrf_token`; a matching cookie with a
  different stored value is 403.
- A step-up obtained for `reveal:<order>` is **rejected** by a hypothetical `user.block` guard
  (parametrised across all step-up scopes).
- `X-Content-Type-Options: nosniff`, `Referrer-Policy: no-referrer` and the full CSP (with a
  per-response style nonce) are on every response.
- An `X-Correlation-ID` of `abc` is discarded and regenerated; one of 32 hex chars is reused.
- `/healthz` returns a bare 200 with an empty body and touches neither DB nor Redis. `/readyz`
  unauthenticated returns `{"status":"ok"}` only; the detailed body requires a session or
  `X-Probe-Token`.
- Bootstrap: refuses a password in `argv`; `getpass` path works; `--password-file` refuses a
  group-readable file; the account has `must_change_password=True` and every route but
  `/auth/password` and `/auth/me` returns 403 until changed; two concurrent runs create exactly one
  OWNER; `--reset-owner` refuses while another active OWNER exists.
- `coverage report --include='src/bayram/admin/*'` ≥ 85%. `make check` green.

#### Slice 1b — audit log, purge scheduler, and the DB query layer

**Created**
- `src/bayram/db/models/{admin_audit,audit_anchor,purge_run}.py`
- `src/bayram/db/admin/{views,page,sql,orders,users,attempts,metrics,audit,retention}.py`
- `migrations/versions/..._0007_add_admin_audit_log.py` (audit log + anchors + the guarded `REVOKE` **and** the `SECURITY DEFINER` sweep function, together)
- `migrations/versions/..._0008_add_admin_read_indexes.py`
- `tests/test_db/{test_admin_queries,test_audit_chain,test_enum_lengths}.py`
- `tests/test_runtime/test_purge_cron.py`

**Modified**
- `src/bayram/db/enums.py` — `AuditAction`, `AuditReasonCode`
- `src/bayram/db/purge.py` — `_purge_audit_reasons`, `_purge_audit_log` (via the `SECURITY DEFINER`
  function on Postgres, plain `DELETE` on SQLite), `_purge_purge_runs`; `PurgeReport` gains
  `audit_reasons_purged`, `audit_rows_deleted`, `purge_runs_deleted` and `batch_size`;
  **`has_work_remaining` fixed** to `any(count >= batch_size …)`
- `src/bayram/runtime/jobs.py` — a new `run_retention_sweep(ctx, *, trigger)` job that awaits
  `purge_expired`, **then iterates `report.storage_keys` calling `container.storage.delete(key)`**,
  logs each `Err`, and writes a `purge_runs` row with `storage_keys_deleted` and
  `storage_delete_failures`; an hourly `cron_jobs` entry invoking it
- `src/bayram/runtime/container.py` — `with_providers: bool = True` with the `ProviderSet | None` shape
  of §4.3; `session_factory` promoted to an `AppContainer` field; pool overrides
- `tests/test_db/test_migrations.py`, `tests/test_db/test_privacy_constraints.py`
  (`admin_audit_log` added to `tables_with_personal_data`)
- `docker-compose.yml` — the `hbd_app` role and its grants; `migrations/env.py` — honour
  `BAYRAM_DB_MIGRATION_URL`

**Acceptance**
- **The purge cron fires within the hour and writes a `purge_runs` record.**
- **An expired asset's archive file is gone after one cron run** — asserted against a real file, and
  the returned key count and the deleted count match.
- `has_work_remaining` is `False` after a run that touched fewer rows than `batch_size` and `True`
  after one that filled a batch.
- Two audit rows appended on **SQLite** have monotonic `seq` (the `.with_variant(Integer,"sqlite")`
  test).
- The HMAC chain verifies; a directly-mutated row is reported as the first break by `/audit/verify`
  (integration, Postgres).
- With `BAYRAM_ADMIN_AUDIT_DSN` set: `REVOKE` denies `UPDATE` to `hbd_app`, and the 730-day sweep still
  deletes via the `SECURITY DEFINER` function (integration). With it empty: the migration logs a
  WARNING and `/audit/verify` reports `chainProtection: "hmac-only"`.
- The enum-length test passes and `db/base.py:52`'s comment states the real maximum.
- A list query over an identity-purged order returns a view model with `recipient_name_display=None`
  and `identity_purged_at` set — **not** a `PipelineError` (the `to_order` trap).

#### Slice 1c — read-only routers and serializers

**Created**
- `src/bayram/admin/serializers/redaction.py`
- `src/bayram/admin/routers/{dashboard,orders,users,generations,assets,audit,admins,retention}.py`
- `src/bayram/admin/schemas/{orders,users,generations,assets,audit,config_view}.py`
- `tests/test_admin/{test_routes_enumeration,test_rbac_matrix,test_redaction,test_pagination}.py`

**Modified**
- `src/bayram/admin/app.py` — mount the routers

**Acceptance**
- Route-enumeration test passes: every route outside `{/healthz, /readyz, /auth/login}` carries
  exactly one `require(...)`, every non-GET carries CSRF, no GET route writes, and no namespace mixes
  identifier names.
- The RBAC matrix test is parameterised over §12.2 **as data** and passes for all four roles.
- A VIEWER's order-detail JSON contains **no** unmasked name substring (asserted against the
  fixture's known plaintext), and `/users/{tg}/wizard-state` contains no substring of the fixture
  draft's plaintext at any role.
- Masking `Gʻulom` yields `G` + `•••` — the U+02BB is never split and never normalised to U+0027 or
  U+2019.
- `GET /config` contains no DSN: no response body matches `://[^/\s:@]+:[^/\s@]+@`; `databaseHost`
  and `redisHost` are present instead.
- Keyset pagination round-trips a cursor and terminates with `nextCursor: null`.

#### Slice 1d — the SPA

**Created**
- `admin-ui/**` — full toolchain, tokens, `AppShell`, `NavRail`, `TopBar`, `CommandPalette`,
  `AsyncBoundary`, `DataTable`, `FilterBar`, `CursorPager`, `NameText`, `StatusPill`, `PurgedValue`,
  `PipelineTimeline`, `TimelineSourceLegend`, `StatTile`, `StateDistributionBar`, and the read-only
  screens for Live · Orders · Users · Generations · Assets · Audit · Retention · Config (read-only)
- `admin-ui/tests/**` (Vitest) and one Playwright smoke flow

**Modified**
- `src/bayram/admin/app.py` — static mount + SPA fallback
- `pyproject.toml` — `[tool.hatch.build.targets.wheel] artifacts`
- `Makefile` (+`ui-install`, `ui`, `ui-build`, all in `.PHONY`)
- `README.md` — production shape → 4 terminals, the two-role Postgres requirement, `.env.admin`;
  delete "the admin panel" from the out-of-scope list at line 249

**Acceptance**
- `make admin && make ui` → login with the bootstrapped account, land on Live Ops with real counts.
- Orders list renders an identity-purged order as `🔒 purged 2026-05-14`, not an error and not a
  blank.
- Order detail shows a 9-stage `stagePlan` (not 11) with the two greeting stages ghosted, and the
  failed stage highlighted with its error code and retryability.
- `/orders/:id/timeline` renders a `sources` legend: `chat` and `payments` read "not enabled in this
  deployment", and `stateTransitions` is labelled `inferred`.
- The `/users` list's date column is headed **"last order"**, not "last seen" — the real writer
  arrives in Phase 3.
- Playwright smoke passes **with the production CSP applied**, including a correctly-positioned Radix
  dialog.
- WCAG contrast test green on both palettes; font-coverage snapshot renders `Oʻktam`, `Gʻulom`,
  `Дилноза`, `sanʼat`.
- `make check` green: `mypy --strict`, ruff, coverage ≥80% repo-wide **and ≥85% on
  `src/bayram/admin/*`**.

---

### Phase 2 — Reveal, audio, and deep inspection · **M**

**Goal.** Support can answer "my song said my sister's name wrong": reveal a name or note with a
reason code, and play the song inline. Every reveal is audited and charged against a record budget.

**Created**
- `src/bayram/admin/routers/reveal.py`, `src/bayram/admin/services/{assets,reveal}.py`
- `src/bayram/admin/schemas/reveal.py`
- `src/bayram/admin/security/budget.py` (record-counted reveal budget in Redis)
- `admin-ui/src/features/assets/**`, `RevealDialog`, `RevealBudgetMeter`, `AudioPlayer`, `PlayerBar`,
  `usePlayerStore`, `SimilarityHistogram`, `StrategyBakeoffChart`
- `tests/test_admin/{test_reveal,test_asset_stream,test_budget}.py`

**Modified**
- `src/bayram/contracts.py` — **`Storage.open_range(key, *, start, end) -> Result[AsyncIterator[bytes]]`**
  added to the protocol (§12.7)
- `src/bayram/storage.py` — `LocalFileStorage.open_range` on top of the existing `_resolve`, 64 KiB
  chunks via `asyncio.to_thread`
- `src/bayram/db/repository.py` — `_replace_assets` writes `storage_key` (also fixes the archive-orphan
  bug for all future rows)
- `src/bayram/db/purge.py` — `_purge_assets` falls back to reconstructing
  `orders/{order_id}/{Path(path).name}` for rows written before the fix, so historical archives are
  reachable too
- `src/bayram/admin/security/sessions.py` — `require_step_up(action, subject_id)`
- `src/bayram/db/attempts.py` — `strategy_stats(since=…)` time window
- `tests/test_storage/**` — the new protocol member on every fake `Storage`

**Acceptance**
- Reveal without a `reasonCode` → 422; without a scoped step-up → 403 `STEP_UP_REQUIRED`; with both →
  plaintext for the named fields only, and the audit row written **before** the read.
- A conversation reveal returns at most 50 bodies, charges 50 units, records `record_count=50` on the
  audit row, and hands back a `nextCursor` that requires a fresh reveal.
- Exceeding `admin_reveal_records_per_hour` → 429 `REVEAL_BUDGET_EXHAUSTED` + WARNING naming the
  actor. Exceeding `admin_reveal_conversations_per_day` → the same, separately.
- `Range: bytes=0-99` → 206 with correct `Content-Range` and length; `bytes=999999-` → 416; a missing
  file → 404 whose body contains **no filesystem path** (asserted).
- Traversal attempts (`../`, absolute, NUL, backslash) rejected by `open_range`; a valid asset
  resolves under the root. The admin package imports **no private method** of `LocalFileStorage`
  (asserted by an import scan).
- `/assets/{id}/text` returns `application/json` with `nosniff`; there is no route that serves a
  customer-authored body as `text/plain`.
- Playing an asset writes exactly one `ASSET_STREAM` audit row per 10-minute window, not one per
  range request.
- Name analytics answers "what should `BAYRAM_NAME_CANDIDATE_ORDER` be" with a windowed bake-off and a
  threshold marker showing how many attempts sit within 0.05 of `name_match_min_similarity`.

---

### Phase 3 — Chat logging, retention config, and real privacy · **L**

**Goal.** Read a full conversation with a user. And — the panel's first genuine privacy
*improvement* — per-user erasure exists for the first time, `/forget` finally reaches Postgres, and
`/privacy` starts telling the truth about a configurable policy.

**Created**
- `src/bayram/db/models/chat_message.py`, `src/bayram/db/admin/chat.py`
- `src/bayram/bot/{chatlog,chatlog_inbound,chatlog_outbound}.py`
- `src/bayram/admin/routers/chat.py`
- `migrations/versions/..._0009_add_chat_messages.py`
- `admin-ui/src/features/chat/**`, `ChatTranscript`, `MessageBubble`, `PurgedRange`
- `tests/test_bot/{test_chatlog_inbound,test_chatlog_outbound,test_chatlog_queue,test_user_touch}.py`
- `tests/test_db/{test_chat_retention,test_purge_user}.py`
- `tests/test_bot/test_privacy_reflects_settings.py`

**Modified**
- `src/bayram/db/purge.py` — `_purge_chat_bodies` (predicate `text_expires_at <= :now AND body IS NOT
  NULL AND body_purged_at IS NULL`), `_purge_chat_messages`, `PurgeReport` fields, **`purge_user()`
  with `exclude_order_ids`**
- `src/bayram/runtime/jobs.py` — **`purge_user_data` ARQ job** (executed by the worker, which owns the
  writable volume): runs `purge_user`, deletes the returned storage keys and the workspace directory,
  writes `USER_PURGE_COMPLETED`/`_FAILED`
- `src/bayram/db/retention.py` — `chat_log_days=90`, `audit_log_days=730`, plus the two matching
  `_SETTINGS_FIELDS` entries
- `src/bayram/config.py` — **all eight `retention_*` fields, each with `ge`/`le` bounds** (§8.3)
- `src/bayram/bot/app.py` — register `ChatLogInboundMiddleware`; **derive `WIZARD_STATE_TTL` from the
  resolved policy inside `build_storage`/`build_dispatcher` instead of at import time**
- `src/bayram/main.py`, `src/bayram/worker.py` — install the outbound session middleware on **both** `Bot`
  instances; start the drain task
- `src/bayram/bot/deps.py` — a repository handle so `/forget` can enqueue `purge_user_data`
- `src/bayram/bot/handlers/commands.py` — **`handle_privacy` takes `deps: BotDeps` and renders from
  `resolve_retention_policy(deps.settings)`**; `/forget` computes `exclude_order_ids` from
  `{AUTHORIZED, GENERATING, HELD_FOR_REVIEW}`, enqueues the purge, enqueues deferred purges for
  excluded orders, and **keeps the existing re-park behaviour byte-identical**
- `src/bayram/runtime/submitter.py` — the chat-body clock promotion `UPDATE` on `session_id` when an
  order reaches a paid state
- `src/bayram/bot/locales/{en,ru,uz_latn,uz_cyrl}.py` — `privacy.text` updated in all four with the
  chat-log clock
- `.env.example` — fill the existing orphaned retention header rather than adding a third block
- `tests/test_db/test_migrations.py`, `tests/test_db/test_privacy_constraints.py`
  (`chat_messages` added to `tables_with_personal_data`)

**Acceptance**
- A full wizard run produces a readable transcript: typed messages, **callback rows with their
  `callback_data`**, screens, the song/greetings/lyric sheet from the worker — and **zero**
  progress-edit rows.
- Ten photos in one album produce ten rows sharing a `media_group_id`, rendered as one annotated
  group, not ten conversations.
- A user who talks to the bot and never confirms an order now **has a `users` row**, is blockable,
  and has a truthful `last_seen_at`; the `/users` column header changes to "last seen".
- Load test at 10× expected update rate: queue drop counter stays 0; p95 update handling time
  unchanged within noise.
- Killing the DB mid-run: the bot keeps answering, the drop counter climbs, a WARNING appears; no
  update is delayed.
- **Clocks:** advance 15 days → an abandoned session's bodies are NULL, a paid session's are not.
  Advance 31 → both NULL, `body_purged_at` stamped, metadata intact. Advance 91 → rows gone.
  `PurgeReport` counts all of it. Running `_purge_chat_bodies` twice reports zero the second time.
- `/forget` deletes the FSM draft **and** enqueues a purge of the user's chat rows and brief text;
  running it twice reports zeros. **`/forget` during `GENERATING` leaves the workspace and the brief
  intact and the song still arrives**, with a deferred purge completing afterwards.
- `/privacy` in all four locales states every retention number **from the resolved policy**: a test
  sets non-default `BAYRAM_RETENTION_*` values and asserts every rendered number changes.
- `BAYRAM_RETENTION_BRIEF_TEXT_DAYS=0` is rejected by pydantic at boot (bounds), not by a `ValueError`
  in `RetentionPolicy.__post_init__`.
- `WIZARD_STATE_TTL` follows `retention_abandoned_draft_days` rather than the import-time default.
- `tests/test_bot/test_locale_contract.py` green.

---

### Phase 4 — Operational actions · **L** (re-sized from M)

**Goal.** A failed order stops being a manual `redis-cli` job. Retry, re-enqueue, force-deliver,
cancel, block/unblock, purge — all step-up-gated and audited.

**Re-sized because the draft understated two contract changes.** Writing `orders.failed_reason`
requires changing the `KitRepository` **Protocol** (`contracts.py:827-829` —
`set_order_state(order_id, state, *, now)` has no reason parameter), `SqlKitRepository._set_order_state`
(`repository.py:178-187`) and **every fake implementing the protocol**. Persisting `chat_id` and
`progress_message_id` needs either two new `Order` fields (`contracts.py:670-677`, where
`create_order(order)` is the only write path) or a second repository method — and
`db/models/order.py:1-6` explicitly says the order row carries no data of this shape, so the decision
is deliberate: **a `set_dispatch_target(order_id, *, chat_id, progress_message_id)` repository
method**, which keeps `Order` a pure contract object and makes the write an explicit operational act.

**Created**
- `src/bayram/admin/services/actions.py`, `src/bayram/admin/schemas/actions.py`
- `src/bayram/bot/blockgate.py` — `BlockGateMiddleware`
- `migrations/versions/..._0010_add_order_dispatch_columns.py`
- `admin-ui/src/features/orders/{RetryOrderDialog,ForceDeliverDialog}.tsx`, `ConfirmDangerDialog`
- `tests/test_admin/test_actions.py`, `tests/test_bot/test_blockgate.py`

**Modified**
- `src/bayram/contracts.py` — `KitRepository.set_order_state(..., failed_reason: str | None = None)`;
  new `KitRepository.set_dispatch_target(...)`
- `src/bayram/db/repository.py` — both, plus `_ensure_user` reachable as an upsert for `set_blocked`
- **Every test double implementing `KitRepository`** (`tests/test_pipeline/**`,
  `tests/test_runtime/**`, `tests/test_bot/conftest.py`)
- `src/bayram/runtime/submitter.py` — call `set_dispatch_target` after persisting
- `src/bayram/bot/progress.py` — `progress_message_id == 0` means "post a fresh message on the first
  frame" (~12 lines in `_push`)
- `src/bayram/pipeline/orchestrator.py` — `_fail` passes `failed_reason` through `_advance_state`
- `src/bayram/bot/app.py` — register `BlockGateMiddleware`
- `src/bayram/bot/locales/*` — `error.blocked` in all four catalogues
- `src/bayram/db/admin/{orders,users}.py` — `set_state`, `get_dispatch_target`, `set_blocked` (upsert)
- `tests/test_db/test_migrations.py`

**Acceptance**
- Retry within an hour of a previous run: `arq:result:generate_kit:<id>` is deleted first, the job
  enqueues, and the UI reports the real result — never a blind "done". With `?force=true` the
  suffixed `:admin-<n>` id is used and the dialog says double-click protection is now covered by
  `_replay`.
- Retrying a `DELIVERED` order costs one DB read and re-delivers with **no new vendor calls**
  (asserted against a fake provider set in the integration test).
- Force-deliver on an order whose assets expired → 409 `PRECONDITION_FAILED` explaining it would
  trigger full regeneration, pointing at retry.
- `orders.failed_reason` is written for a validation failure and a moderation rejection, and both
  appear in `/metrics/failures`.
- A blocked user's next message gets `error.blocked` in their UI language and no handler runs;
  **including a user who never confirmed an order** (the upsert path). Unblocking takes effect within
  60 s (cache TTL) or immediately (invalidation).
- Block gate **fails open** when both Redis and Postgres are unreachable.
- Purge requires typed confirmation of the telegram id (equal to the path parameter) + reason code +
  **fresh** step-up + OWNER; the API returns 202 and writes `USER_PURGE_REQUESTED`; the **worker**
  writes `USER_PURGE_COMPLETED` with per-table and per-file counts; a second run reports zeros; the
  workspace directory and archive objects are gone — asserted with the worker on a writable volume
  and the API on a read-only one.
- The UI shows a purge as in-progress until the completion audit row lands.
- Audit row counts per action match §9.1: in-transaction actions write exactly one row and roll it
  back with the action; enqueue actions write an INTENT and an OUTCOME row on both the success and
  the failure path (parametrised test).

---

### Phase 5 — Attempt instrumentation, cost, and the payments ledger · **M**

**Goal.** The cost and latency dashboards stop showing "not instrumented" and start showing real
numbers. Payment history becomes real.

**Created**
- `src/bayram/db/models/payment.py`, `src/bayram/db/admin/payments.py`
- `src/bayram/admin/routers/payments.py`
- `migrations/versions/..._0011_add_payments_ledger.py`
- `admin-ui/src/features/payments/**`
- `tests/test_db/test_verdict_telemetry_survives_save.py`

**Modified**
- `src/bayram/contracts.py` — **`NameVerdict` gains `provider`, `cost_usd`, `cost_source`,
  `latency_ms`**, all defaulted (§5.12)
- `src/bayram/db/attempts.py` — `verdict_row_values` persists the four new fields instead of hardcoding
  `provider=None`
- `src/bayram/pipeline/name_stage.py` — `_render` → `record()` with `GenerationKind.SONG`; **`_hear`
  populates the `NameVerdict` telemetry rather than calling `record()`**, because `_replace_verdicts`
  (`repository.py:345`) deletes and re-inserts every `kind='name_verification'` row on **every**
  `save_kit` — a second writer would be wiped by the next save and by every admin retry
- `src/bayram/pipeline/greetings.py` (`_render_one` → `GREETING`), `src/bayram/providers/llm/writer.py`
  (→ `LYRICS`), `src/bayram/pipeline/moderation.py` (→ `LYRICS`, `sequence=-1`) — each `await`s
  `record()` and logs its `Err`, never propagating it
- `src/bayram/pipeline/orchestrator.py` — `KitPipeline.__init__` takes the attempts repository
- `src/bayram/runtime/container.py` — build `GenerationAttemptRepository`;
  `payment=LedgerPaymentProvider(NoopPaymentProvider(), ledger, call_site="pipeline")`
- `src/bayram/main.py` — a second `LedgerPaymentProvider` with `call_site="bot"`
- `src/bayram/payments.py` — `LedgerPaymentProvider`
- `src/bayram/db/admin/metrics.py` — cost-by-provider, cost-per-delivered-kit, per-stage p95
- `tests/test_db/test_migrations.py`

**Acceptance**
- One order produces attempt rows for song takes, verification (via the verdict path), greetings
  (when enabled) and the lyric write, each with `provider`, `cost_usd`, `cost_source` and
  `latency_ms` populated.
- **`save_kit` twice preserves the verification telemetry** — the `_replace_verdicts` round trip is
  asserted explicitly.
- `capabilities.costTelemetry` flips to `true` and every cost tile lights up with **no frontend
  change** — that is the point of the flag.
- Every cost figure is returned alongside its `cost_source`, and the UI labels an estimate as an
  estimate (music is derived from `music_usd_per_minute`; the vendor reports nothing, and TTS is
  `0.0` out of the box because `elevenlabs_usd_per_character` defaults to 0).
- A ledger write failure logs and does **not** change the authorisation result (asserted).
- `payments.raw_payload` passes through `redact()` — a test with a DSN-shaped and a key-shaped value
  asserts both are masked.
- Two payment rows per order with distinct `call_site` values, and the UI explains it inline so
  nobody files it as a duplicate-row bug.

---

### Phase 6 — Moderation queue · **M**

**Goal.** Flagged briefs and lyrics are reviewed by a human before any generation spend.

**Created**
- `src/bayram/db/models/moderation_review.py`, `src/bayram/db/admin/reviews.py`
- `src/bayram/admin/routers/moderation.py`, `src/bayram/admin/services/moderation_service.py`
- `migrations/versions/..._0012_add_moderation_reviews.py`
- `admin-ui/src/features/moderation/**`, `ModerationCard`
- `notify_order_failed` ARQ job in `src/bayram/runtime/jobs.py`

**Modified**
- `src/bayram/contracts.py` — `OrderState.HELD_FOR_REVIEW` (15 chars; no DDL), declared after
  `LYRICS_READY`
- `src/bayram/runtime/submitter.py` — hold between persist and enqueue when `is_manual_review_required`;
  insert the `pending` review; do not enqueue
- `src/bayram/config.py` — `is_manual_review_required: bool = False`
- `src/bayram/bot/screens.py` + all four locales — the "being checked" screen
- `src/bayram/db/purge.py` — `_purge_moderation_details` (nulls `flag_detail` and `decision_note` on the
  brief-text clock, predicate guarded on `text_purged_at IS NULL`); `purge_user` nulls them too;
  `PurgeReport` gains `moderation_details_purged`
- `tests/test_db/test_migrations.py`, `tests/test_db/test_privacy_constraints.py`
  (`moderation_reviews` added to `tables_with_personal_data`)

**Not modified: `src/bayram/pipeline/moderation.py` and `src/bayram/pipeline/orchestrator.py`.** The draft
included an in-pipeline soft-flag path; it is **out of scope** for the reasons in §10.3 (no held
outcome exists in `Result[Kit]`, `_release_session` runs only on terminal ends so the customer's FSM
would park until the 14-day TTL, and approval would loop because no approved-bypass flag exists).

**Acceptance**
- With the gate on, confirming a brief leaves the order `HELD_FOR_REVIEW` with a `pending` review and
  **no ARQ job**; `_PAID_STATES` and the `is_paid` latch are untouched.
- Approve restores `held_from_state` and enqueues; the customer's song arrives; **no second hold
  occurs**.
- Reject sets `FAILED` with `failed_reason`, and the customer gets a localised message via
  `notify_order_failed`.
- A second approve on the same review → 409 (rowcount guard).
- For a **denylist** flag the matched pattern is highlighted in the lyric via `flag_pattern_index` +
  `flag_hit_in`; for an **`llm_verdict`** flag those two are NULL and the model's `reason` is rendered
  as prose, never as an empty highlight.
- Opening a review is an audited reveal (`record_count=1`).
- `flag_detail` and `decision_note` are NULL after 31 days while `flag_pattern_index`, `flag_hit_in`
  and the decision metadata survive.
- `k`/`j`/`a`/`r` work the queue two-handed.
- Gate off (default) → behaviour byte-identical to Phase 5.

---

### Phase 7 — Runtime configuration editor · **L** (re-sized from M)

**Goal.** Reorder `BAYRAM_NAME_CANDIDATE_ORDER` from a bake-off result without a redeploy, and see it
take effect in the bot and worker within 30 seconds.

**Re-sized because the `SettingsHolder` change touches 25 `BotDeps(` construction sites across `src`
and `tests`** (verified count) plus one `AppContainer(` in `src` and its fixtures, and `BotDeps` is
`@dataclass(frozen=True, slots=True)` with no kwargs tolerance. The mitigation (§8.1) is the
`bot_deps(...)` factory accepting a bare `Settings`, which makes each site a one-word rename rather
than a rewrite — but it is still 25 sites.

**Created**
- `src/bayram/runtime/{overlay,watcher}.py`
- `src/bayram/db/models/{settings_version,settings_override}.py`, `src/bayram/db/admin/overrides.py`
- `src/bayram/admin/config/{policy,guards,service}.py`, `src/bayram/admin/routers/config.py`
- `migrations/versions/..._0013_add_settings_versions_overrides.py`
- `admin-ui/src/features/config/**`, `ConfigField`, `ConfigDiffDialog`
- `tests/test_runtime/{test_overlay,test_watcher}.py`,
  `tests/test_admin/{test_config_policy,test_config_guards}.py`

**Modified**
- `src/bayram/config.py` — `build_settings` gains the `extra="forbid"` validation copy
- `src/bayram/runtime/container.py` — `settings_source: SettingsHolder` field + `settings` property
- `src/bayram/bot/deps.py` — `settings_source` field + `settings` property + the `bot_deps()` factory
- **Every `BotDeps(` call site in `src` and `tests` (25), plus `tests/test_bot/conftest.py` and
  `tests/conftest.py`**
- `src/bayram/main.py`, `src/bayram/worker.py`, `src/bayram/admin/app.py` — start `SettingsWatcher`
- `src/bayram/runtime/jobs.py` — resolve settings **once** at `:347` and thread it down (this is what
  unlocks the greeting Tier-2 fields)
- `src/bayram/pipeline/content.py` — `LlmContentWriter` takes a `SettingsHolder` and exposes `_settings`
  as a property (this is what unlocks the LLM Tier-2 fields)
- `src/bayram/bot/handlers/confirm.py` — read `deps.settings.kit_price_amount_minor` directly at
  `:202-204` instead of `deps.amount_minor` (this is what unlocks pricing)
- `.env.example` — precedence stated: env is the base, DB overrides layer on top
- `tests/test_db/test_migrations.py`

**Acceptance**
- Committing a `name_candidate_order` change is visible in the bot and worker within 30 s (pub/sub
  typically milliseconds), and each process reports the new `config_version` on its heartbeat and on
  the authenticated `/readyz`.
- A Tier-3 key returns 422 `CONFIG_FIELD_NOT_EDITABLE` naming the field **and its reason**; the UI
  renders it read-only with that reason, never as an editable field that silently does nothing.
- **Every `AdminSettings` field name is rejected by `/config/validate`** (parametrised), and no
  `settings_overrides` row can reach one because they are not `Settings` fields at all.
- An unknown key (e.g. a renamed field left in the allowlist) is a 422 naming the field, not a silent
  drop — `extra="forbid"` plus the module-level `LIVE_EDITABLE_FIELDS <= set(Settings.model_fields)`
  assertion.
- An invalid value returns 422 carrying the exact `BAYRAM_*` variable name `_describe_failure` produces,
  after `redact()` and a 300-char cap.
- Cross-field guards fire: a `*_timeout_s` above `queue_job_timeout_s` is refused;
  `song_length_ms ≤ name_chunk_duration_ms` is refused; a retention set that would raise
  `ValueError` in `RetentionPolicy.__post_init__` is refused as a 422.
- **Lengthening a retention period requires OWNER step-up and writes a `RETENTION_EXTENDED` audit
  row**; shortening does not.
- `log_level=DEBUG` is **refused** when `environment == "prod"`; in dev it requires step-up and is
  audited. Root DEBUG no longer reaches `sqlalchemy.engine` (asserted by a caplog test that runs a
  query and finds no bound parameters).
- A corrupt override row written by hand does **not** crash a running worker — it logs ERROR and keeps
  the last known good settings, for a `ConfigError` **and** for a bare `ValueError` (integration test
  writes one of each directly).
- Rollback to version 0 returns every process to pure `.env`.
- `BAYRAM_ADMIN_CONFIG_ENABLED=false` + restart → the overlay is a no-op, and the flag is read from the
  process environment, never through the holder.
- Secrets **and both DSNs** are absent from `GET /config`, not masked.
- The three Tier-2 groups become editable and each is verified by the test named in §8.3: both
  `greetings_per_kit` read sites see the same value within one order; a version bump changes the
  **bot's** next lyric write temperature; the bot's gate price and the worker's authorisation price
  match after a commit.

---

## 15. Open questions

Six of the draft's questions survive review; two were settled by it and are recorded as settled.

1. **Should `name_records` with `source='user_confirmed'` be deleted by `purge_user`?** These are
   dictionary entries derived from a real person's confirmation of a spelling. They are the product's
   linguistic moat and are not attributable to one customer once written, but they *originated* from
   one. The plan currently **keeps** them. If a regulator would disagree, the deletion path is
   `_purge_name_records`'s existing shape and it is a small change — but it permanently shrinks the
   dictionary. **Decide before Phase 3 ships**, because that is when `purge_user` lands.
2. **`users.telegram_user_id` survives a purge** so a repeat customer is recognised, the block list
   still works, and a re-purge is possible. That means "purge" is erasure of *content*, not of the
   account's existence. The `/privacy` copy must say exactly that in all four languages — and after
   Phase 3 it renders from the resolved policy, so the wording change is a locale edit, not a code
   edit. Is that acceptable, or should the id be hashed — which would break `orders.telegram_user_id`'s
   denormalised join, the block gate and the chat log's only reliable key?
3. **Should `orders` carry a `config_version` column?** It would close the "which
   `name_candidate_order` rendered this song" gap exactly. The order fingerprint
   (`confirm.py:_order_fingerprint`) covers the draft only, so two orders queued a second apart can
   render under different settings with nothing recording which. The mitigation in the plan is to log
   `config_version` in the order's correlation-scoped run line so it is recoverable. `orders`
   deliberately carries no derived config today (`db/models/order.py:1-6`). **Deferred, not decided.**
4. **`_build_kit` requires song + lyric_sheet + ≥1 greeting** (`repository.py:398-405`), while `Kit`'s
   own contract permits empty greetings when `greetings_per_kit == 0` — which is the shipped default.
   So a song-only kit fails read-back, which blocks force-deliver on it (the precondition in §9.2 is
   `get_kit` returning `Ok`). This looks like a pre-existing bug, but the fix touches the delivery
   path. **Fix it in Phase 4, or leave force-deliver unavailable for song-only kits and say so in the
   dialog?** Phase 4's acceptance currently assumes the latter.
5. **MFA.** v1 has none; the compensating controls are loopback binding, a reverse proxy with an IP
   allowlist or VPN, action-scoped step-up re-auth, and `BAYRAM_ADMIN_ENABLED=false` by default. Note
   that the XFF work (T13) is what makes the proxy story coherent at all. Is that acceptable for the
   operating team's size, or should TOTP land in Phase 1?
6. **Where will the admin API run relative to the worker?** Assets live on the worker's filesystem.
   Co-location with a shared `var/` volume (`:ro` for the API, RW for the worker) is assumed
   throughout, and D11 makes that assumption load-bearing. If it will run elsewhere, `Storage` must
   be swapped for S3/R2 first — and `Storage.open_range` (§12.7) is now the seam that makes that
   answerable rather than a rewrite of the asset service.

**Settled by review, recorded so nobody reopens them:**

- *Where does the admin process get its settings?* A separate `AdminSettings` model with no vendor
  fields (D10, §4.2). The alternative — relaxing `min_length=1` on the three `Settings` secrets —
  was rejected because it makes a key-free boot possible everywhere, including in the worker, where
  it should remain impossible.
- *Does the panel need an in-pipeline moderation flag?* No. §10.3.

---

## 16. Risks

| # | Risk | Mitigation |
|---|---|---|
| **R1** | **The panel becomes a permanent, unclocked copy of data the bot deliberately expires.** A screenshot, an export, a browser cache, a "temporary" CSV — one copy defeats every clock in `purge.py`, permanently and invisibly. This is the risk the whole design exists to bound | Bulk export forbidden; masked by default with audited, step-up-gated reveal **budgeted in records, not clicks** (§12.3) and paged at 50 bodies; `no-store` everywhere; revealed-records-per-actor sparkline on the dashboard as a *detection* control; evidence pack JSON-only, watermarked, OWNER-only at 5/day; CSV cells escaped against formula injection. **Watch for:** anyone asking for "just a quick CSV of last month"; a support workflow that starts with "download the sheet"; an actor whose revealed-record count climbs while their request count does not |
| **R2** | **Chat log ships without the purge scheduler, the `/privacy` fix, or `purge_user`.** The clock exists in the schema and runs nowhere; the notice becomes false; `/forget` deletes a draft while a verbatim transcript sits in Postgres | The scheduler ships in **Phase 1 slice 1b**, before the table exists, **and it deletes storage keys**, which nothing does today. The `/privacy` fix (rendering from `resolve_retention_policy`, not the module constant), `purge_user`, and `chat_messages` in `tables_with_personal_data` are in the **same PR** as migration `0009`. A test asserts both clock columns are NOT NULL with no server default, so an insert that omits them fails. **Watch for:** no `retention purge complete` line in 2 hours; `chat_messages` growing with a flat oldest-`created_at`; `storage_keys_deleted` staying 0 while `storage_keys_returned` climbs |
| **R3** | **A bad runtime config override wedges the fleet, or applies to one process and not another** — the pricing split (boot `BotDeps` vs live `orchestrator`) authorising one order at two amounts; the LLM split (boot `LlmContentWriter` vs per-job pipeline) writing lyrics at two temperatures | Allowlist not denylist, enforced twice, with a module-level `LIVE_EDITABLE_FIELDS <= Settings.model_fields` assertion and `extra="forbid"` so a stale key is a 422 rather than a silent no-op; whole-model validation before write; never-throw application keeping last-known-good on `ConfigError` **and `ValueError`**; per-process `config_version` badges; `BAYRAM_ADMIN_CONFIG_ENABLED=false` + restart as the escape hatch, read from the environment and never from the holder. **Pricing and the two LLM fields stay off the list until their named fix lands** (§8.3 Tier 2). **Watch for:** two processes disagreeing on `config_version` for over a minute; a Tier-2 field appearing in the allowlist without its fix |
| **R4** | **Admin credential compromise.** No MFA in v1, one login route, and the account owns purge, force-deliver and config commit | argon2id off the event loop + dual limiters keyed on `(username, ip)` that trip **before** the hash; no enumeration; opaque revocable sessions with rotation, a ≤60 s Redis mirror and per-request DB reads of `role`/`is_active`/`password_changed_at`; **action-scoped** step-up with grace 0 on purge and config; `BAYRAM_ADMIN_ENABLED=false` by default; loopback bind behind a proxy with **real client-IP derivation** so the per-IP limiter and the "session jumped countries" signal actually work. **Watch for:** a login-failure spike; a session whose `last_ip` jumps countries; reveals outside working hours; a `permission.denied` cluster from one actor probing routes |
| **R5** | **Asset serving becomes a file-read primitive.** `assets.path` is an absolute DB-sourced string and `storage_key` is NULL, so the naive implementation string-joins a filename — on a process that can read `.env` | Asset UUID input only; key reconstructed server-side; resolution **only** through the public `Storage.open_range` seam over `_resolve`; filename regex-validated; mime allowlist with **no `text/plain` stream at all**; `nosniff` and `Content-Disposition` everywhere; `:ro` volume; traversal cases in the unit suite; an import scan asserting the admin package touches no private storage method. **Watch for:** any review of `admin/services/assets.py` that builds a `Path` by concatenation; a 200 on a request containing `%2e%2e`; a new route serving customer text as `text/plain` |
| **R6** | **The retry button silently does nothing.** ARQ refuses a `_job_id` present in the result store, `queue_result_ttl_s = 3600`, and `chat_id`/`progress_message_id` live nowhere but the job args and the FSM | `DEL arq:result:<job_id>` first, or a `:admin-<n>` suffix (double-click protection then covered by `_replay`); `chat_id` recovered from `orders.chat_id` (written by the new `set_dispatch_target`) or `telegram_user_id`; `progress_message_id == 0` posts a fresh message; the UI reports the enqueue result, never a blind "done". **Watch for:** a retry that returns success with no new attempt rows and no state change; Telegram 400s on progress edits |
| **R7** | **The capture middleware degrades the bot.** It runs inside the FSM isolation lock; a slow write there serialises a user's updates and can break the double-tap guarantee, with the 60 s lock expiry as the outer bound. The `users` upsert makes this worse if it is done inline | The middleware never writes — bounded queue + background drain, and the upsert goes through the *same* queue, rate-limited to one per user per minute; overflow drops loudly and counts; progress edits excluded; a 10× load test is a Phase 3 acceptance criterion. **Watch for:** a non-zero drop counter; rising p95 update handling; duplicate submissions reappearing after the double-tap gate had fixed them |
| **R8** | **Coverage and mypy gates erode.** A large new package lands faster than its tests; someone adds `omit = ["src/bayram/admin/*"]` "temporarily" and the most security-sensitive code becomes the only untested code | Phase 1 is sliced into four independently mergeable PRs, each green; the composition root is covered by an ASGI smoke suite through `httpx.ASGITransport` (already a dependency), which is what the draft's "thin routers, fat services" argument did *not* cover; the route-enumeration, RBAC-matrix and config-tier tests make guard coverage nearly free; `make check` is unchanged so the gate is felt by everyone immediately; **Phase 1 names a package-level number (≥85% on `src/bayram/admin/*`)**, not just the repo-wide one. **Watch for:** an `omit` line appearing in `pyproject.toml`; coverage parked at 80.4% for three PRs; a rising `# type: ignore` count under `src/bayram/admin/` |
| **R9** | **The audit log's immutability is theatre.** One Postgres role means the REVOKE is reversible by its target; an unkeyed hash chain is recomputable by anyone who can write the table; and the 730-day sweep needs the very DELETE the REVOKE removes | Two roles as explicit Phase 1 work (`BAYRAM_DB_MIGRATION_URL`, docker-compose init SQL, README); the REVOKE and its `SECURITY DEFINER` sweep function ship in **one** migration so neither exists without the other; an HMAC chain keyed on an environment-only secret; chain-head anchors written to a table **and to a log line**, so the head exists outside the database; and — the part that matters most — **when the two-role setup is absent, the migration skips the REVOKE and `/audit/verify` reports `chainProtection: "hmac-only"`, which the panel shows verbatim.** A control that is not deployed is reported as not deployed. **Watch for:** `audit_rows_deleted` staying 0 while the table grows; a `chainProtection` badge nobody has looked at in a month |
| **R10** | **A privacy control is added to the schema and never added to the guard tests.** `tables_with_personal_data` and `_EXPECTED_TABLES` are both hardcoded lists in the test suite; a new table is silently exempt from the first and breaks the second | `_EXPECTED_TABLES` is derived from `Base.metadata` in Phase 1 so it cannot drift again; `tables_with_personal_data` gains an entry in the same PR as every new text-holding table (Phases 1, 3, 6 each name it in their Modified list); the enum-length test closes the parallel SQLite-passes/Postgres-fails hole. **Watch for:** a new `String(...)` column holding free text with no `*_expires_at` sibling; a migration PR that touches no test file |

---

## 17. What changed after review

Two adversarial reviewers checked the draft against the real code. Everything below is a change to
the plan, not a caveat added to it. Line references were re-verified against the working tree while
making them.

### Falsified claims, corrected

1. **"The admin process boots without vendor keys" was false.** `telegram_bot_token`,
   `elevenlabs_api_key` and `llm_api_key` are all `Field(min_length=1)` with no default
   (`config.py:83`, `:90`, `:118`) and `load_settings()` raises without them; `with_providers=False`
   only skips adapter construction, which happens after validation. **Fix:** a separate
   `AdminSettings` model with no vendor fields at all, its own `.env.admin`, a prod boot assertion
   that refuses to start if a vendor variable is present, and a test that the app boots with them
   unset (D10, §4.2). T12's blast radius is now a true statement.
2. **"`/privacy` renders from the policy so it cannot drift" was accidental.** `handle_privacy`
   (`commands.py:91`) reads the module constant `DEFAULT_RETENTION_POLICY`, not
   `resolve_retention_policy(deps.settings)`; it is accurate only because `Settings` has no
   `retention_*` fields. **Fix:** the `/privacy` change ships in the same PR as those fields
   (Phase 3), with a test asserting non-default settings change every number in all four locales, and
   no `retention_*` field enters the allowlist before it.
3. **Writing `storage_key` does not, by itself, delete files.** `purge_expired` returns
   `storage_keys` for the *caller* (`purge.py:52-58`) and nothing calls it. **Fix:** the Phase 1 cron
   is a job that awaits `purge_expired` then deletes each key, recording `storage_keys_deleted`, with
   an acceptance test on a real file.
4. **`moderation_reviews` does carry brief text.** `flag_detail` holds `match.group(0)` from
   `_local_hit`. **Fix:** a 30-day clock, a sweep, a `purge_user` entry, a §12.5 row, and membership
   in `tables_with_personal_data`.
5. **`has_work_remaining` does not mean what its docstring says** (`purge.py:113-115`). **Fix:**
   compare per-sweep counts to `batch_size`, and drive the UI from a server-computed `rowsPastExpiry`.
6. **Citations corrected:** `HELD_FOR_REVIEW` is 15 characters, not 16; `LOCAL_DENY_PATTERNS` is at
   `moderation.py:52-57` and the helpers are `_local_hit` (`:73`) and `_hit_source` (`:81`), attached
   at `:118-127`; `pattern_hit`/`hit_in` exist only on the denylist branch, so `flag_detail` for an
   LLM verdict is the model's `reason` and the UI renders prose rather than an empty highlight;
   `session_factory` is not currently an `AppContainer` field (Phase 1 adds it); `db/base.py:52`'s
   "longest is 17 characters" comment is updated and pinned by a test.

### Structural changes

7. **Ten tables, not seven.** `purge_runs` and `audit_chain_anchors` were required by the draft in
   three places and defined in none; both are now specified with columns and clocks.
8. **Every autoincrement PK is `BigInteger().with_variant(Integer, "sqlite")`.** A `BIGINT` PK does
   not autoincrement on SQLite, and the entire unit suite runs on SQLite — the audit log could not
   have been written in a single test.
9. **`tests/test_db/test_migrations.py` is in every DDL phase's Modified list**, and Phase 1 derives
   `_EXPECTED_TABLES` from `Base.metadata` (keeping a `_CORE_TABLES` regression guard) so it cannot
   break again. Same for `tables_with_personal_data` in `test_privacy_constraints.py`.
10. **A disjoint `AdminErrorCode` enum** in `src/bayram/admin/errors.py` with the full status mapping
    (401/403/409/415/416 included) and a test that no admin code can reach `translate()`. `ErrorCode`
    is not extended, because `BayramError.user_message_key` drives customer-facing copy.
11. **`Storage.open_range` is a public protocol member**, so the admin service depends on the
    protocol instead of `LocalFileStorage._resolve`, and the S3 answer in open question 6 has
    something to implement.
12. **`AppContainer.providers: ProviderSet | None` has a specified shape** — guarded `aclose`,
    `pipeline()` raising `PipelineError` at the top with a named message, and a test.
13. **User purge and the retention sweep are ARQ jobs**, executed by the worker, because the API's
    volume is `:ro`. The draft had the API deleting files on a read-only mount, whose failure mode is
    a UI reporting a completed purge over a song still on disk.
14. **`_replace_verdicts` is not fought.** `NameVerdict` carries `provider`/`cost_usd`/`cost_source`/
    `latency_ms` and `verdict_row_values` persists them, so there is one writer instead of a second
    that every `save_kit` would wipe.
15. **No in-pipeline moderation soft-flag path** (§10.3): `Result[Kit]` has no held outcome,
    `_release_session` runs only on terminal ends so the customer's FSM would park for 14 days, and
    approval would loop with no bypass flag. The submit-time gate needs no orchestrator change and
    delivers the goal.
16. **`/forget` is scoped for in-flight safety** via `purge_user(exclude_order_ids=…)` plus deferred
    jobs, preserving the documented re-park behaviour that `privacy.forgotten` promises.
17. **A `users` upsert on the inbound path**, so a user who never confirms an order is blockable and
    `last_seen_at` means what it says. The `/users` column header is honest until Phase 3.
18. **`KitRepository` protocol changes are named**: `set_order_state(..., failed_reason=None)` and a
    new `set_dispatch_target(...)`, plus every test double. Phase 4 re-sized M → L. Phase 7 re-sized
    M → L for the 25 `BotDeps(` construction sites, mitigated by a `bot_deps()` factory that accepts a
    bare `Settings`. Phase 1 re-sized L → XL and sliced into four mergeable PRs.

### Security changes

19. **`database_url` and `redis_url` are SECRET tier**, absent from `GET /config` at every role; a
    derived `databaseHost`/`redisHost` is returned instead. The draft let role V read the database
    password.
20. **Every `BAYRAM_ADMIN_*` field is structurally unreachable by an override** because it lives on
    `AdminSettings`, plus a `SECURITY_CRITICAL` rejection list and a parametrised test. The draft's
    own exhaustiveness test demanded a tier for them and none was assigned; had any been editable, a
    session could have disabled the CSRF origin check or re-enabled the config kill switch.
21. **HMAC chain keyed on an environment-only secret**, a two-role deployment shipped as real Phase 1
    work, the `REVOKE` and its `SECURITY DEFINER` sweep function in one migration, chain anchors
    emitted as log lines, and an honest `chainProtection: "hmac-only"` report when the two-role setup
    is absent.
22. **Step-up is action- and subject-scoped**, with grace 0 for purge and config commit/rollback.
23. **The reveal budget counts records, not requests**, caps a conversation reveal at 50 bodies,
    persists `record_count` on the audit row, adds a separate daily conversation ceiling, and drives
    the dashboard sparkline off exposure rather than clicks.
24. **The audit `reason` is structured** (`reason_code` + `reason_ref` + optional `reason_text` on a
    90-day clock, excluded from the chain hash), so the longest-clock, purge-immune table stops being
    where customer names accumulate.
25. **Client IP is derived from `X-Forwarded-For` through an explicit trusted-proxy configuration**,
    right-to-left with a hop count, ignored from untrusted peers. Without it the per-IP limiter is one
    global bucket and every `ip` column records the proxy.
26. **The Redis session mirror caches only token → admin id, TTL ≤ 60 s, invalidated on every revoke,
    deactivate, role change and password change**; `role`, `is_active` and `password_changed_at` are
    read from Postgres per request.
27. **CSRF compares the header against the stored `admin_sessions.csrf_token`**, cookies use the
    `__Host-` prefix, and `Secure` is enforced whenever `environment != "dev"`.
28. **`SameSite=Lax`, not `Strict`**, so the deep-link workflow §11.2 is built for actually works;
    the `Origin` check and the session-bound CSRF token carry state-change protection.
29. **`nosniff` on every response, no `text/plain` asset stream at all** (lyric text is
    `application/json`), `Content-Disposition: attachment` for any non-audio stream, plus
    `Referrer-Policy`, `form-action 'none'`, `worker-src 'none'` and a **CSP style nonce threaded
    through Radix** so nobody reaches for `'unsafe-inline'` at integration time.
30. **`/readyz` detail is authenticated**; `/healthz` is a bare 200.
31. **`/users/{tg}/wizard-state` is a projection built from a key allowlist**, and the FSM draft is a
    reveal subject with its own row in the redaction table. It was role-V unmasked in the draft, over
    the only copy that exists for abandoned sessions.
32. **`redact()` gains DSN-userinfo and `sk-…-…` value patterns and DSN/HMAC name patterns**, with a
    test. The draft caught only `sk-or-v1-`.
33. **Retention fields carry `ge`/`le` bounds**, a guard that catches `RetentionPolicy`'s bare
    `ValueError` as a 422, a `RETENTION_EXTENDED` audit action gating any lengthening behind OWNER
    step-up, and a watcher that survives `ValueError` as well as `ConfigError`.
34. **`log_level`/`is_debug` moved off Tier 1**: `configure_logging` does not floor
    `sqlalchemy.engine`, which at DEBUG echoes every bound parameter — names, notes, lyrics,
    transcripts — into unclocked stdout. Phase 1 extends the floor list regardless of the panel;
    DEBUG is refused in prod and audited elsewhere; the field is a `Literal`.
35. **CSV formula injection is escaped**, and the audit export is JSON only.
36. **Bootstrap reads the password from a TTY**, refuses `argv`, checks the mode of a
    `--password-file`, forces a change on first login, and inserts with
    `WHERE NOT EXISTS`. **`--reset-owner` exists**, so losing the last OWNER is not a permanent
    lockout, and "at least one active OWNER" is enforced against demotion by others too.
37. **The audit-transaction rule is stated once** (§9.1): in-transaction for single-transaction
    actions, intent+outcome for external ones, with a per-action row-count test. The draft specified
    both models and reconciled neither.
38. **Chat bodies start on the 14-day abandoned-draft clock and are promoted to 30 days on payment.**
    The draft's flat 30 days more than doubled the retention of an abandoned wizard's text, against an
    invariant `build_storage` documents.
39. **`_purge_chat_bodies` has an explicit `body IS NOT NULL AND body_purged_at IS NULL` predicate**
    and an idempotency test; without it the sweep re-selects every purged row forever.
40. **`/orders/{id}/timeline` returns a `sources` array**, so Phase 1 renders "chat capture not
    enabled" rather than an empty section, and `stateTransitions` is labelled `inferred` because no
    order-event table exists.
41. **Phase 1 names a package coverage number (≥85% on `src/bayram/admin/*`) and adds an ASGI smoke
    suite** through `httpx.ASGITransport` covering `app.py`, `bootstrap.py` and the middleware stack —
    the modules thin routers and fat services do not reach.
42. **The Tier-1 "effect takes hold" column has two values only** — "next order" and "on refresh" —
    because `KitPipeline.__init__` snapshots `Settings` and is built per job, so "next call" was wrong
    for six fields whose text is rendered to an operator in the dry run.
43. **`greeting_min_duration_s` and `greeting_max_duration_s` are in the same tier as
    `greetings_per_kit`** (all Tier 2, one named fix). They are read in one expression at
    `orchestrator.py:374-376` and `_greeting_window_must_be_ordered` validates max against min, so the
    draft's split let an operator only ever lower the minimum.
44. **The unknown-key hole is closed** by a module-level `LIVE_EDITABLE_FIELDS <=
    set(Settings.model_fields)` assertion and an `extra="forbid"` validation copy, because
    `Settings.model_config` sets `extra="ignore"` (`config.py:67`) and a stale allowlist entry would
    validate, commit, publish and do nothing — §8.4's stated worst failure mode through the front door.
45. **Validation messages pass through `redact()` and a 300-char cap** before entering a 422 body or
    an audit row, because `_describe_failure` and `_candidates_must_be_unique` interpolate the
    submitted value.
46. **One identifier per namespace** (`{telegramUserId}` everywhere under `/users`), with the purge
    confirmation echoing the path value and a route-enumeration assertion.
47. **`llm_temperature` / `llm_max_output_tokens` moved to Tier 2** with `LlmContentWriter` named as
    the fix, because it captures `Settings` by value at `content.py:156` and the bot builds one
    instance at boot — so a commit would apply in the worker and not in the customer-visible wizard
    writer.
48. **`ENUM_LENGTH` is pinned by a test** across every enum passed to `enum_type()`, closing a real
    SQLite-accepts/Postgres-rejects divergence.
49. **The login limiter is keyed on `(username, ip)`** with a looser global-per-username ceiling and a
    session exemption, so knowing an operator's username is not a renewable lockout primitive.

### Rejected review findings

- **"Drop `flag_detail` and store only the denylist pattern index."** Rejected in favour of keeping
  `flag_detail` on a 30-day clock. The reviewer's alternative was also offered and is cheaper, but a
  moderator who cannot see *which characters* fired the pattern has to re-read the whole lyric, and
  the pattern index alone does not cover the `llm_verdict` branch, which has no pattern at all. The
  clock plus `purge_user` plus the retention-summary row closes the privacy gap without blinding the
  reviewer. `flag_pattern_index` is added **as well**, for post-sweep analytics.
- **"Set the chat body clock to `min(brief_text_days, abandoned_draft_days)` = 14 days for all
  rows."** Rejected in favour of 14 days with promotion to 30 on payment. A flat 14 days would leave
  support unable to read what a paying customer said three weeks ago, while the promotion is one
  indexed `UPDATE` on `session_id` at a point the submitter already writes. The privacy outcome for
  abandoned sessions — the population the finding was about — is identical.
- **"Add `reason` to `purge_user`'s null list keyed by `subject_id`."** Rejected. A `subject_id`
  identifies a user only for user-scoped actions; for config, admin and session actions it is not a
  person, so keying an erasure on it would be wrong in most cases and right in a few. The 90-day
  `reason_text` clock erases the free text for **every** action, which is strictly broader and needs
  no keying.
- **"Give `Settings` an `BAYRAM_ADMIN_ONLY=1` mode relaxing the three `min_length=1` vendor fields."**
  Rejected in favour of a separate `AdminSettings` model. A relaxation mode makes a key-free boot
  representable everywhere, including in the worker where it must stay impossible, and it leaves the
  vendor fields present-but-empty on the object the admin process holds. A model with no such field
  is the honest version, and it is what makes T12 a fact rather than a policy.
- **"Fix `_build_kit`'s song-only-kit bug in Phase 4."** Not rejected, but deliberately left as open
  question 4 rather than folded in: the fix touches the delivery path (`repository.py:398-405`)
  against a contract (`Kit`) that already permits the case, and it deserves its own decision rather
  than riding along inside an operational-actions PR. Phase 4 ships with force-deliver unavailable for
  song-only kits and a dialog that says so.
