# BROADCAST_SPEC — newsletter and notification broadcasts

**Migration head when this was written:** `0023`. Cite this document by section —
`BROADCAST_SPEC §4.4` — never by path, so the citation survives the file moving.

**Consent is out of scope for the initial build.** The design this document was cut from carried a
`marketing_consents` table, an opt-out command and a consent predicate on every send; all three were
removed rather than deferred in place, so nothing here half-implements them. §6.3 records what that
leaves standing, and what has to exist before the position changes.

---

## 0. Ground truth this specification is built on

Facts established by reconnaissance over this repository and re-verified before filing:

| Fact | Consequence |
| --- | --- |
| `grep -rn "enqueue_job\|create_pool\|ArqRedis" src/bayram/admin/` → **zero hits** | There is no admin→ARQ seam. It must be built (§3.6). |
| Migration head is `0023`; ids are hand-set 4-digit serials | The new revision is `0024`. |
| `AuditAction` is a closed StrEnum with no broadcast member; `SUBJECT_TYPES` is a closed frozenset without `broadcast` | Both must be extended (§6.4). |
| `Permission`, `StepUpAction`, `STEP_UP_ACTIONS`, `RBAC_MATRIX` are closed and cross-asserted by tests | Three new permissions + one step-up action (§3.1). |
| No `sort` parameter exists anywhere; ordering is fixed `keyset_order(created_at, id)` | "Sort by anything" is a **keyset redesign**, not a router change (§1.6). |
| `UserFilters` docstring refuses name/phone/free-text predicates in prose, as an unmask-oracle argument | The field registry is an **allowlist**, never derived from a row schema (§6.1). |
| `users.last_seen_at` is withheld from every per-row projection, aggregate-only | Filterable, never projectable, **never sortable** (§1.5). |
| `bounded_total` saturates at `TOTAL_COUNT_CAP = 10_000` | The dry-run count needs its own unbounded `count()` (§1.7). |
| `tables_with_personal_data` / `tables_erased_on_request` are disjoint sets asserted by test; a third route exists (`bot_membership_events`, `topup_purchases`) — "erased by anonymisation, bounded by a cutoff, on no clock" | `broadcast_recipients` takes the third route (§6.2). |
| Worker owns a `Bot` in the ARQ ctx (`BOT_CTX_KEY`); admin process is forbidden a bot token (`FORBIDDEN_ENV_VARS`) | Panel composes, worker sends. No exceptions. |
| Nothing rate-limits **outbound** Telegram traffic; no `TelegramRetryAfter` handler exists in `src/` | The pacer is net-new (§4.3). |
| `retry_jobs` defaults to `True`; SIGTERM cancels and re-runs jobs | Per-recipient persisted state is mandatory, not a nicety (§4.4). |
| `Makefile:37` `UI := admin-dashboard`; `admin-ui/package.json` says DEPRECATED; `admin-dashboard/` is **untracked** and has **no test runner** | §5 targets `admin-dashboard`; adding vitest there is an explicit task. |

**Conflict resolved.** Two reports disagree on which SPA to build in. `admin-ui` has 102 test files and all the better abstractions; `admin-dashboard` is what `make ui` runs, what the user is actually testing, and what `admin-ui/package.json` defers to. **Decision: build in `admin-dashboard`, and port the two abstractions that are worth it (`searchParams` zod codecs, `buildFilterChips`) rather than importing across app boundaries.** Better-evidenced because it rests on the Makefile and the deprecation notice, both of which are current, while admin-ui's advantage is only test coverage — a gap this specification closes with an explicit task.

---

## 1. SEGMENT ENGINE — the filter DSL

### 1.1 Where it lives

| File | Contents |
| --- | --- |
| `src/bayram/db/admin/segment.py` | `FIELDS` registry, `SegmentError`, `compile_segment()`, `sort_expression()`, `SEGMENT_LIMITS`. Pure SQLAlchemy; imports no FastAPI. |
| `src/bayram/admin/schemas/segment.py` | `SegmentModel`/`RuleModel`/`GroupModel`/`SortModel` pydantic wire models (subclass `ApiModel`), `decode_segment()` / `encode_segment()` base64url codec, `MAX_SEGMENT_CHARS`. |
| `src/bayram/db/admin/users.py` | `UserFilters` gains one field: `segment: CompiledSegment | None`. `_filtered()` gains three lines. |

The DSL is a **document**, not a query string. Both consumers hand the same document to the same compiler:

- **Users screen** — `GET /api/users?segment=<base64url-json>` (plus the six legacy chip params, ANDed with the segment; keeping them is what stops this being a breaking change and what keeps existing bookmarks working).
- **Broadcast wizard** — the identical JSON in the `POST /api/broadcasts` body and in `GET /api/segments/preview?segment=<base64url-json>`.

One compiler, one registry, one refusal list. A field that the Users screen cannot filter on is a field the wizard cannot target, structurally.

### 1.2 The JSON shape

```jsonc
{
  "v": 1,                              // schema version; unknown → 422
  "match": "all",                      // "all" (AND) | "any" (OR) | "none" (NOT OR)
  "rules": [
    { "field": "ui_language",  "op": "in",       "value": ["ru", "en"] },
    { "field": "joined_at",    "op": "between",  "value": ["2026-06-01T00:00:00Z",
                                                            "2026-07-01T00:00:00Z"] },
    { "match": "any", "rules": [                 // nested group, depth ≤ 3
        { "field": "plan_status",           "op": "in",  "value": ["lapsed"] },
        { "field": "delivered_order_count", "op": "gte", "value": 3 }
    ]}
  ],
  "sort": { "key": "delivered_order_count", "dir": "desc" }   // optional; default {created_at, desc}
}
```

- A node is **either** a rule (`field`/`op`/`value`) **or** a group (`match`/`rules`). `extra="forbid"` on both models means a hybrid is a 422.
- `"match": "none"` is the NOT: `sa.not_(sa.or_(*children))`. There is deliberately no per-rule `negate` flag — one negation mechanism, one place to reason about NULL semantics.
- Empty `rules` on the root = "everyone" (the unfiltered list). Empty `rules` on a nested group = 422 (`"a group must carry at least one rule"`), because a silently-true group is how an operator ships a broadcast to the whole database believing it is narrowed.

**Hard limits** (`SEGMENT_LIMITS`, module constants, all 422 with the offending parameter named and the value never echoed):

| Limit | Value | Why |
| --- | --- | --- |
| `MAX_RULES` | 25 | Total leaf rules across all groups. |
| `MAX_DEPTH` | 3 | Root + two nested levels. |
| `MAX_VALUE_MEMBERS` | 50 | `in`/`not_in` list length. |
| `MAX_SEGMENT_CHARS` | 4096 | The base64url string, before decode. Declared as `Query(max_length=MAX_SEGMENT_CHARS)` at the router — the same rule `q` follows, for the same reason. |
| `MAX_AGGREGATE_RULES` | 6 | Rules whose field compiles to a correlated subquery. Each one is a scan the planner pays for. |

### 1.3 Operators

| Operator | Applies to | SQL |
| --- | --- | --- |
| `eq` / `neq` | int, enum, bool | `col == v` / `col != v` |
| `in` / `not_in` | enum, int | `col.in_(vs)` / `~col.in_(vs)` — empty list is a 422, never `IN ()` |
| `gt` `gte` `lt` `lte` | int, instant | plain comparison |
| `between` | int, instant | half-open `[a, b)` — the same convention `apply_window` uses, so a June segment and a June dashboard tile agree |
| `is_true` / `is_false` | bool | `expr.is_(True)` / `expr.is_(False)`; no value member |
| `is_null` / `is_not_null` | instant, presence | `col.is_(None)` / `col.is_not(None)` |
| `within_last_days` | instant | `col >= now - timedelta(days=n)` |
| `not_within_last_days` | instant | `col < now - timedelta(days=n)` **or** `col IS NULL` — see §1.4 |
| `within_next_days` | instant | `now <= col < now + timedelta(days=n)` |

`n` is `int`, `1 ≤ n ≤ 3650`. Every instant value must be RFC3339 **with an offset** — reuse `bayram.admin.window.require_aware`, so the 422 message is byte-identical to the one `?from=` already produces and the frontend needs no second error path.

**The NULL rule, stated once and applied everywhere:** `not_within_last_days` and `lt`/`before` on a nullable instant **include NULL rows**, because "has not ordered in 90 days" must contain "has never ordered". `within_last_days` and `gt`/`after` **exclude** them. This is written into each `FieldSpec` as `null_is_stale: bool` rather than decided per call site, and the frontend prints it in the rule row ("includes accounts that never did this").

### 1.4 The field registry — every field this codebase can actually support

Each entry is a frozen `FieldSpec(key, kind, ops, build, sortable, null_is_stale, capability)`. `build(op, value, *, now)` returns a `ColumnElement[bool]`; `now` is threaded in, never read inside.

#### `users` — direct columns (cheapest; no subquery)

| `field` | Column | Kind | Ops | Sortable |
| --- | --- | --- | --- | --- |
| `telegram_user_id` | `users.telegram_user_id` | int | `eq`, `in` | no |
| `ui_language` | `users.ui_language` | enum `Language` | `eq`, `in`, `not_in` | no |
| `is_blocked` | `users.is_blocked` | bool | `is_true`, `is_false` | no |
| `bot_blocked` | `users.blocked_bot_at IS NOT NULL` | bool | `is_true`, `is_false` | no |
| `bot_blocked_at` | `users.blocked_bot_at` | instant | full instant set | no |
| `joined_at` | `users.created_at` | instant | full instant set | **yes** (default) |
| `last_activity_at` | `users.last_seen_at` | instant | full instant set | **NO — refused** |

`is_blocked` and `bot_blocked` are two fields, never one. They are never OR-ed by the compiler and the builder gives them different labels in the UI ("barred by us" / "blocked our bot"). `last_activity_at` is filterable because a predicate discloses only the bucket the operator already chose; it is **not sortable** because a sort publishes a total order over identified accounts, which is the minute-by-minute surveillance the withheld projection exists to prevent (`db/admin/users.py:26-31`, `db/admin/overview.py:144-147`). Write that argument into the `FieldSpec` docstring — it is the kind of refusal this repo states in code.

#### `user_profiles` — presence only, via `sa.exists().correlate(UserRow)` on `user_id`

| `field` | Predicate | Kind | Ops |
| --- | --- | --- | --- |
| `has_profile` | row exists | bool | `is_true`, `is_false` |
| `has_phone` | `phone_e164 IS NOT NULL` | bool | `is_true`, `is_false` |
| `has_username` | `telegram_username IS NOT NULL` | bool | `is_true`, `is_false` |
| `has_avatar` | `avatar_stored_at IS NOT NULL` | bool | `is_true`, `is_false` |
| `onboarded_at` | `user_profiles.onboarded_at` | instant | instant set |
| `phone_shared_at` | `user_profiles.phone_shared_at` | instant | instant set |
| `language_chosen_at` | `user_profiles.language_chosen_at` | instant | instant set |

**No value predicate on `phone_e164`, `first_name`, `last_name`, `telegram_username` exists, at any role, ever.** No `contains`, no `startswith`, no `eq`. `SEGMENT_REFUSALS` is a module-level frozenset of those four column names, and a unit test asserts no `FieldSpec.build` closure references them — so the refusal is a diff a reviewer sees, exactly like `_SEARCHABLE_COLUMNS`.

#### `credit_accounts` — correlated scalar subquery on `telegram_user_id`

| `field` | Expression | Kind | Sortable |
| --- | --- | --- | --- |
| `has_credit_account` | `EXISTS` | bool | no |
| `credit_balance` | `COALESCE((SELECT balance …), 0)` | int | **yes** |
| `lifetime_credits_granted` | `COALESCE((SELECT lifetime_granted …), 0)` | int | **yes** |
| `first_metered_at` | `(SELECT created_at …)` | instant | yes |

`credit_balance` is the **stored** column, never `read_balance()`'s projection — the existing `has_balance` argument applies unchanged: the projection is three statements per account and moves with `now`, so a cursor would drift under it. `has_balance` from the legacy chip lowers to `credit_balance gt 0`.

#### `orders` — correlated scalar subqueries on `telegram_user_id`

| `field` | Expression | Kind | Sortable |
| --- | --- | --- | --- |
| `order_count` | `(SELECT count(*) …)` | int | **yes** |
| `paid_order_count` | `count(*) WHERE state IN (authorized, generating, delivered)` (reuse `_PAID_STATES`) | int | yes |
| `delivered_order_count` | `count(*) WHERE state = delivered` | int | **yes** |
| `failed_order_count` | `count(*) WHERE state = failed` | int | yes |
| `first_order_at` | `MIN(created_at)` | instant | yes |
| `last_order_at` | `MAX(created_at)` | instant | **yes** |
| `last_delivered_at` | `MAX(delivered_at)` | instant | yes |
| `order_state` | `EXISTS(state IN vs)` | enum `OrderState` | `in`, `not_in` — not sortable |

`ix_orders_telegram_user_id_created_at` already covers all of these.

#### `plan_purchases` — the subscription vocabulary

| `field` | Definition | Kind |
| --- | --- | --- |
| `plan_status` | four mutually-exclusive, exhaustive cases (below) | enum `PlanStatus` — `in`, `not_in` |
| `plan_ends_at` | `MAX(plan_ends_at)` | instant — full set incl. `within_next_days` |
| `plan_purchase_count` | `count(*)` | int |

```
none       NOT EXISTS(plan_purchases)
active     EXISTS(plan_ends_at > :now AND songs_used <  songs_included)
exhausted  EXISTS(plan_ends_at > :now) AND NOT EXISTS(plan_ends_at > :now AND songs_used < songs_included)
lapsed     EXISTS(any)                 AND NOT EXISTS(plan_ends_at > :now)
```

`PlanStatus` is a new `StrEnum` in `bayram.checkout` (leaf, next to `PlanState`), derived from `plan_sql.current_plan`/`live_plan`'s two existing predicates so there is one definition of "live". Values ≤ 32 chars.

**There is no renewal in this product** — no auto-renew, no `renewed_at`, no recurring billing. `lapsed` is therefore the only truthful spelling of "did not renew", and the UI label must say so: **"Plan expired and not repurchased"**, not "Did not renew". Getting this wrong is how a campaign goes out saying "your subscription lapsed" to people who never had one.

#### `topup_purchases`, `payment_intents`, `bot_membership_events`

| `field` | Expression | Kind | Sortable |
| --- | --- | --- | --- |
| `topup_count` | `count(*)` | int | yes |
| `topup_spend_minor` | `COALESCE(SUM(amount_minor), 0)` | int | yes |
| `last_topup_at` | `MAX(created_at)` | instant | yes |
| `has_paid_ever` | `EXISTS(topup) OR EXISTS(plan)` | bool | no |
| `has_abandoned_checkout` | `EXISTS(state IN (pending, awaiting, expired, cancelled)) AND NOT EXISTS(state = paid)` | bool | no |
| `bot_block_event_count` | `count(*) WHERE event = blocked` | int | no |
| `has_returned_after_block` | `EXISTS(blocked) AND EXISTS(unblocked)` | bool | no |

All of these key on nullable `telegram_user_id` (nulled by `/forget`). The correlated form `WHERE t.telegram_user_id = users.telegram_user_id` naturally excludes anonymised rows — no extra guard needed, and a comment must say so or someone will add a redundant `IS NOT NULL`.

#### `chat_messages` — capability-gated

| `field` | Expression | Kind |
| --- | --- | --- |
| `inbound_message_count` | `count(*) WHERE direction = inbound` | int |
| `last_inbound_message_at` | `MAX(created_at) WHERE direction = inbound` | instant |
| `wizard_step` | `EXISTS(wizard_step IN vs)` | enum-ish string, `in` only |

`FieldSpec.capability = "chat_messages"`. `compile_segment` takes `capabilities: frozenset[str]`, produced by `has_table(session, "chat_messages")` (`db/admin/sql.py:97`). A rule on an unavailable capability is a **422 naming the field**, never a silently-dropped clause — "the table is missing" and "nobody matched" must not look the same. `chat_messages.body` is a refusal on the same footing as the profile names.

#### Derived, read-only (offered by the wizard, allowed on `/users`)

| `field` | Expression | Kind |
| --- | --- | --- |
| `is_reachable` | `is_blocked IS false AND blocked_bot_at IS NULL` | bool |

### 1.5 The four named examples, verbatim

```jsonc
// "did not renew their subscription"
{"v":1,"match":"all","rules":[{"field":"plan_status","op":"in","value":["lapsed"]}]}

// "joined in June" (half-open, UTC, offsets mandatory)
{"v":1,"match":"all","rules":[{"field":"joined_at","op":"between",
  "value":["2026-06-01T00:00:00Z","2026-07-01T00:00:00Z"]}]}

// "generated the most" — a threshold plus a sort; a sort alone narrows nothing
{"v":1,"match":"all",
 "rules":[{"field":"delivered_order_count","op":"gte","value":3}],
 "sort":{"key":"delivered_order_count","dir":"desc"}}

// "inactive for months" — NULL-inclusive by the §1.3 rule
{"v":1,"match":"all","rules":[{"field":"last_activity_at","op":"not_within_last_days","value":90}]}

// composite: lapsed heavy users who still have credit and can be reached
{"v":1,"match":"all","rules":[
  {"field":"plan_status","op":"in","value":["lapsed"]},
  {"field":"delivered_order_count","op":"gte","value":2},
  {"field":"credit_balance","op":"gt","value":0},
  {"field":"is_reachable","op":"is_true"},
  {"match":"any","rules":[
     {"field":"ui_language","op":"in","value":["uz_latn","uz_cyrl"]},
     {"field":"topup_count","op":"gte","value":1}]}],
 "sort":{"key":"last_order_at","dir":"desc"}}
```

### 1.6 Sorting — the keyset change

Today's cursor is `{at, id}` and the order is hard-wired to `(created_at DESC, id DESC)`. Sorting on anything else requires the cursor to carry the sort value. This is **additive**; old cursors keep decoding.

```python
# src/bayram/db/admin/page.py  (additions)
@dataclass(frozen=True, slots=True)
class SortSpec:
    key: str                     # a SORT_KEYS member
    direction: Literal["asc", "desc"]

@dataclass(frozen=True, slots=True)
class SortedCursor:
    k: str          # sort key name — a cursor minted under one sort is refused under another
    d: str          # "asc" | "desc"
    v: str          # the sort value, canonically encoded (ISO-8601 Z for instants, decimal for ints)
    id: UUID

def sorted_keyset_predicate(expr, id_col, cursor, *, direction) -> ColumnElement[bool] | None
def sorted_keyset_order(expr, id_col, *, direction) -> tuple[UnaryExpression, ...]
```

Three rules that make this safe:

1. **Every sortable expression is total and non-null.** `COALESCE(count, 0)`, `COALESCE(balance, 0)`, `COALESCE(last_order_at, '1970-01-01T00:00:00Z')`. No `NULLS FIRST/LAST` divergence between SQLite and Postgres, and the cursor's `v` is always a concrete scalar. The UI states the consequence: "never ordered" sorts as 0 / epoch.
2. **The tiebreak is always `users.id`**, so the order is total even when 4 000 accounts share `delivered_order_count = 0`.
3. **A cursor carries its sort.** `decode_cursor` rejects a `SortedCursor` whose `k`/`d` differ from the request's — 422 `INVALID_INPUT`, "this cursor belongs to a different sort". Silently continuing under a new sort is how a page repeats or skips rows.

`SORT_KEYS` is a `Mapping[str, SortSpec]`-style allowlist derived from `FIELDS` (`spec.sortable is True`), plus `created_at` as the default. An unknown `sort.key` is a 422 naming `sort`. **No string ever reaches `ORDER BY`** — the key indexes into the registry and the registry returns an expression object.

**Cost, stated plainly.** Sorting on an aggregate makes the planner evaluate a correlated subquery over the whole filtered set before it can order. On the current data volume that is fine; at 500 k users it is not. Mitigation shipped now: `?withTotal=` is **refused** (422) when `sort.key` is an aggregate, so one request never pays for both. Mitigation deferred: a `user_rollups` materialised table, §7 Q5.

### 1.7 Compilation, and why it cannot be injected into

```python
# src/bayram/db/admin/segment.py
@dataclass(frozen=True, slots=True)
class CompiledSegment:
    predicate: ColumnElement[bool] | None
    sort: SortSpec
    aggregate_rule_count: int

def compile_segment(
    segment: SegmentModel, *, now: datetime, capabilities: frozenset[str]
) -> Result[CompiledSegment]:
```

- The JSON supplies a **key**, never an identifier. `FIELDS[rule.field]` is a dict lookup; a miss is `Err(INVALID_INPUT, "unknown field", field=rule.field)`. The `field` name is echoed (it is a schema name, not customer data); the **value never is**.
- Values are bound parameters through normal SQLAlchemy expression construction. There is no `text()`, no f-string, no `sa.column(name)` anywhere in the module — asserted by a test that greps the module source for `text(` and `column(`.
- Enum values go through `Language(value)` / `OrderState(value)` etc., so an unknown member is a `ValueError` caught into a 422 before any SQL is built.
- `now` is a parameter. `utc_now()` appears nowhere in this module (the router's `_window`-style helper supplies it, so tests can monkeypatch one clock).
- The result is composed into `_filtered()` **before** the joins, so `count_users` and `list_users` narrow identically — the existing invariant, unchanged:

```python
def _filtered(filters: UserFilters) -> Select[tuple[UserRow]]:
    statement = sa.select(UserRow)
    ...                                          # existing six predicates, untouched
    if filters.segment is not None and filters.segment.predicate is not None:
        statement = statement.where(filters.segment.predicate)
    return statement
```

Legacy chip params and `segment` are **ANDed**. The Users screen sends one or the other in practice, but the server does not care, and a bookmarked chip URL keeps working.

---

## 2. DATA MODEL

One migration. `0024` carries the whole broadcast machinery. There is no consent table in this build and no second revision — §6.3.

### 2.1 `broadcasts` — the campaign record (rev 0024)

`src/bayram/db/models/broadcast.py`

| Column | Type | Notes |
| --- | --- | --- |
| `id` | `sa.Uuid` PK default `uuid4` | |
| `title` | `String(120)` NOT NULL | Operator-facing only; never sent. |
| `kind` | `enum_type(BroadcastKind)` NOT NULL | `service` \| `marketing` — an operator-facing classification, recorded from the first campaign so it never has to be backfilled. It gates nothing in this build (§6.3). |
| `state` | `enum_type(BroadcastState)` NOT NULL, indexed | `draft`→`expanding`→`ready`→`sending`→(`paused`)→`completed`\|`cancelled`\|`failed` |
| `segment` | `sa.JSON(none_as_null=True)` NOT NULL | The frozen DSL document. `sa.JSON` precedent: `briefs.recipient_candidates`, `admin_audit_log.field_names`. |
| `segment_hash` | `String(64)` NOT NULL | sha256 of canonical JSON — lets the panel say "this campaign used the segment you are looking at". |
| `audience_evaluated_at` | `UtcDateTime` NULL | The `now` the segment was compiled against. Without it, "why did 12 fewer people get it than the preview said" is unanswerable. |
| `expand_cursor` | `String(256)` NULL | The keyset cursor the expansion phase resumes from. |
| `scheduled_for` | `UtcDateTime` NULL, indexed | NULL = send on schedule-now. |
| `started_at` / `finished_at` | `UtcDateTime` NULL | |
| `recipient_count` | `Integer` NOT NULL default 0 | Materialised rows. |
| `sent_count` / `failed_count` / `skipped_count` / `undeliverable_count` | `Integer` NOT NULL default 0 | Denormalised counters, recomputed per chunk from `broadcast_recipients`; the rows are truth. |
| `created_by_admin_id` / `scheduled_by_admin_id` | `sa.Uuid` NULL | No FK to `admin_users` — a deactivated operator's campaign must survive. |
| `created_by_username` / `scheduled_by_username` | `String(ACTOR_USERNAME_LENGTH)` NULL | Denormalised for the same reason `admin_audit_log` denormalises the actor. |
| `scheduled_by_role` | `enum_type(AdminRole)` NULL | |
| `reason_code` / `reason_ref` / `reason_text` | mirroring `ReasonedRequest` | Why this campaign exists, captured at schedule. |
| `error_code` | `String(ERROR_CODE_LENGTH)` NULL | Terminal failure of the run itself. |
| `created_at` / `updated_at` | `TimestampMixin` | |

Indexes: templated `ix_broadcasts_state`, `ix_broadcasts_scheduled_for`, `ix_broadcasts_created_at` (from the mixin). Composite `ix_broadcasts_state_scheduled_for(state, scheduled_for)` for the "what is due" scan — the shape `ix_payment_intents_state_valid_until` already uses.

`BroadcastState` / `BroadcastKind` go in `bayram.contracts` (**not** in a leaf module — the enum-length sweep only walks `bayram.contracts` and `bayram.db.*`, which is why `BotBlockSource` lives there). All values ≤ 32 chars.

### 2.2 `broadcast_bodies` and `broadcast_recipients` (rev 0024)

`broadcast_bodies` — one row per language. A child table rather than a JSON blob, because a `CHECK`-able length and a `UNIQUE (broadcast_id, language)` are what stop a campaign shipping with an empty Russian body.

| Column | Type |
| --- | --- |
| `id` | `sa.Uuid` PK |
| `broadcast_id` | `sa.Uuid` NOT NULL, FK `broadcasts.id` ON DELETE CASCADE, indexed |
| `language` | `enum_type(Language)` NOT NULL |
| `text` | `String(BROADCAST_BODY_LENGTH)` NOT NULL — `BROADCAST_BODY_LENGTH = 4096`, matching `delivery.MAX_MESSAGE_CHARS` |
| `button_label` | `String(64)` NULL |
| `button_url` | `String(512)` NULL |
| `created_at` / `updated_at` | mixin |

Constraints: `uq_broadcast_bodies_broadcast_id_language`, `ck_broadcast_bodies_text_not_empty` (`length(text) > 0`), `ck_broadcast_bodies_button_pair` (`(button_label IS NULL) = (button_url IS NULL)`).

`broadcast_recipients` — one row per (campaign, account). The progress ledger.

| Column | Type | Notes |
| --- | --- | --- |
| `id` | `sa.Uuid` PK | |
| `broadcast_id` | `sa.Uuid` NOT NULL FK CASCADE | |
| `telegram_user_id` | `BigInteger` **NULL**, indexed | NULL == `/forget` anonymised it (§6.2). |
| `language` | `enum_type(Language)` NOT NULL | Snapshotted at expansion; the body is chosen from this. |
| `state` | `enum_type(BroadcastRecipientState)` NOT NULL | `pending` → `sending` → `sent` \| `failed` \| `skipped_blocked` \| `undeliverable` \| `unknown` |
| `attempts` | `SmallInteger` NOT NULL default 0 | |
| `error_code` | `String(ERROR_CODE_LENGTH)` NULL | A closed `bayram.errors` member or a Telegram class token — **never** a response body excerpt (`usage.py:109-111`'s argument: a vendor error body can quote the prompt). |
| `sent_at` | `UtcDateTime` NULL | |
| `created_at` / `updated_at` | mixin | |

Constraints and indexes:
- `uq_broadcast_recipients_broadcast_id_telegram_user_id` — **the idempotency authority**. A replayed expansion chunk is a database-enforced no-op via `insert_or_ignore` (`credit_sql.py:146`), the `user_activity_snapshots` pattern, not a branch.
- `ix_broadcast_recipients_broadcast_state (broadcast_id, state)` — the claim query and the counter rollup.
- `ix_broadcast_recipients_telegram_user_id` — the `/forget` anonymisation arm.
- `ix_broadcast_recipients_created_at` — the retention cutoff sweep.

Note the UNIQUE index is partial-hostile: `telegram_user_id` becomes NULL on erasure, and multiple NULLs are permitted by both engines, which is exactly right — anonymised rows stop participating in uniqueness and keep their counts.

Rev 0024 also adds `purge_runs.broadcast_recipients_deleted INTEGER NOT NULL DEFAULT 0` (and reverses it in `downgrade` **before** dropping the tables).

### 2.3 Migration authoring checklist (rev 0024)

- Filename `20260910_HHMM_0024_add_broadcast_tables.py`; set `revision`/`down_revision` **by hand** (`make revision` mints a random hash) and rename the file's `_NNNN_` segment.
- `revision: str = "0024"`, `down_revision: str | None = "0023"`, the `str | Sequence[str] | None` spelling from `script.py.mako`.
- No `import bayram` — enums literal: `sa.Enum("draft", "expanding", "ready", "sending", "paused", "completed", "cancelled", "failed", name="broadcaststate", native_enum=False, length=32)`. Timestamps literal `sa.DateTime(timezone=True)`.
- Everything through `op.batch_alter_table`; templated names via `batch_op.f(...)`; composite names as module constants spelled identically in `__table_args__`.
- Real `downgrade()` — drop indexes in `reversed()` order, then the `purge_runs` column, then the tables child-first.
- Register all three models in `src/bayram/db/models/__init__.py` (import **and** `__all__`) **in the same commit**, or the whole suite passes against a schema that lacks the tables.

---

## 3. BACKEND API

### 3.1 Permissions, step-up, audit (edit these first — nothing else compiles without them)

`src/bayram/admin/security/permissions.py`:

```python
BROADCAST_READ  = "broadcast.read"
BROADCAST_WRITE = "broadcast.write"     # role half of the W+S cell
BROADCAST_SEND  = "broadcast.send"      # the W+S cell itself
```
```python
Permission.BROADCAST_READ:  _row(viewer=_M, support=_M, admin=_M, owner=_M),
Permission.BROADCAST_WRITE: _row(admin=_W, owner=_W),
Permission.BROADCAST_SEND:  _row(admin=_WS, owner=_WS),
```
`StepUpAction.BROADCAST_SEND = "broadcast.send"` + `STEP_UP_ACTIONS[Permission.BROADCAST_SEND] = StepUpAction.BROADCAST_SEND`. Its own action, never a reuse of `USER_BLOCK` — the `CREDIT_GRANT` comment makes exactly this argument and the same confused-deputy risk applies.

`src/bayram/db/enums.py` — new `AuditAction` members (all ≤ 32 chars):
```
BROADCAST_CREATE   = "broadcast.create"
BROADCAST_SCHEDULE = "broadcast.schedule"     # the INTENT row
BROADCAST_PAUSE    = "broadcast.pause"
BROADCAST_RESUME   = "broadcast.resume"
BROADCAST_CANCEL   = "broadcast.cancel"
BROADCAST_SENT     = "broadcast.sent"         # the OUTCOME row, written by the worker
BROADCAST_TEST     = "broadcast.test"
```

`src/bayram/db/admin/audit.py` — add `"broadcast"` to `SUBJECT_TYPES`. `BROADCAST_SUBJECT_TYPE: Final[str] = "broadcast"` is spelled once, in `routers/broadcasts.py`, and imported by the worker (the `USER_SUBJECT_TYPE` precedent).

### 3.2 The routers

`src/bayram/admin/routers/broadcasts.py` — **three factories**, one permission each, per the house rule.

```python
BROADCASTS_PATH:            Final[str] = f"{API_PREFIX}/broadcasts"
BROADCAST_PATH:             Final[str] = f"{BROADCASTS_PATH}/{{broadcast_id}}"
BROADCAST_RECIPIENTS_PATH:  Final[str] = f"{BROADCAST_PATH}/recipients"
BROADCAST_REVISE_PATH:      Final[str] = f"{BROADCAST_PATH}/revise"
BROADCAST_SCHEDULE_PATH:    Final[str] = f"{BROADCAST_PATH}/schedule"
BROADCAST_PAUSE_PATH:       Final[str] = f"{BROADCAST_PATH}/pause"
BROADCAST_RESUME_PATH:      Final[str] = f"{BROADCAST_PATH}/resume"
BROADCAST_CANCEL_PATH:      Final[str] = f"{BROADCAST_PATH}/cancel"
BROADCAST_TEST_SEND_PATH:   Final[str] = f"{BROADCAST_PATH}/test-send"
```

`src/bayram/admin/routers/segments.py`:
```python
SEGMENT_PREVIEW_PATH: Final[str] = f"{API_PREFIX}/segments/preview"
SEGMENT_FIELDS_PATH:  Final[str] = f"{API_PREFIX}/segments/fields"
```
Both literal-segment paths; nothing under `/segments` takes a `{param}`, so registration order is uncontested — but `BROADCAST_RECIPIENTS_PATH` and the five verb paths **must be registered before** `BROADCAST_PATH` (Starlette matches in order; the `ORDER_STATE_COUNTS_PATH` precedent).

| Method · Path | Permission (router) | Step-up (handler) | Body | Response |
| --- | --- | --- | --- | --- |
| `GET /api/segments/fields` | `BROADCAST_READ` | — | — | `SegmentFieldsView` — the registry as data: key, label, kind, ops, sortable, capability. **The builder is server-driven**, so a field can never appear in the UI that the compiler refuses. |
| `GET /api/segments/preview?segment=&limit=` | `RECORDS_READ` | — | — | `SegmentPreviewView` — `{ matched, reachable, skippedBlocked, skippedBotBlocked, byLanguage: [{language, count}], sample: [UserView…] }`. `matched` is an **exact** `SELECT count(*)` over `_filtered`, never `bounded_total`. `sample` is masked `UserView`s, ≤ 10. |
| `GET /api/users?segment=&…` | `RECORDS_READ` (existing router) | — | — | `UsersPage`, unchanged shape. |
| `GET /api/broadcasts?state=&from=&to=&limit=&cursor=&withTotal=` | `BROADCAST_READ` | — | — | `BroadcastsPage` |
| `GET /api/broadcasts/{broadcast_id}` | `BROADCAST_READ` | — | — | `BroadcastDetailView` — campaign + bodies + counters + the segment document echoed back |
| `GET /api/broadcasts/{broadcast_id}/recipients?state=&limit=&cursor=&withTotal=` | `BROADCAST_READ` | — | — | `BroadcastRecipientsPage` — `telegramUserIdMasked`, `language`, `state`, `errorCode`, `sentAt`. **The raw Telegram id is not on this wire** (§6.1). |
| `POST /api/broadcasts` | `BROADCAST_WRITE` | — | `BroadcastCreateRequest` | `BroadcastDetailView` (201-shaped body, default 200 status per house style) |
| `POST /api/broadcasts/{id}/revise` | `BROADCAST_WRITE` | — | `BroadcastReviseRequest` | `BroadcastDetailView` — 409 `INVALID_STATE` unless `state == draft` |
| `POST /api/broadcasts/{id}/schedule` | `BROADCAST_WRITE` | **`enforce_step_up(BROADCAST_SEND, subject_id=str(broadcast_id))`** | `BroadcastScheduleRequest(ReasonedRequest)` | `BroadcastDetailView` |
| `POST /api/broadcasts/{id}/pause` | `BROADCAST_WRITE` | — | `ReasonedRequest` | `BroadcastDetailView` |
| `POST /api/broadcasts/{id}/resume` | `BROADCAST_WRITE` | — | `ReasonedRequest` | `BroadcastDetailView` |
| `POST /api/broadcasts/{id}/cancel` | `BROADCAST_WRITE` | — | `ReasonedRequest` | `BroadcastDetailView` |
| `POST /api/broadcasts/{id}/test-send` | `BROADCAST_WRITE` | **step-up, same action** | `BroadcastTestSendRequest(ReasonedRequest)` — `telegramUserId` must be in `settings.admin_broadcast_test_recipients` | `BroadcastTestSendResultView` |

Router split: `build_broadcasts_read_router()` (`BROADCAST_READ`), `build_broadcasts_write_router()` (`BROADCAST_WRITE`), `build_segments_router()` (`RECORDS_READ` for preview) + `build_segment_fields_router()` (`BROADCAST_READ` for the registry). Four builders — a second permission is a second factory, always.

`subject_id` for the step-up is `str(broadcast_id)` and must be byte-identical to what the SPA sent to `/auth/step-up`.

### 3.3 Request/response schemas

`src/bayram/admin/schemas/broadcasts.py`, every model subclassing `ApiModel` (camelCase aliases, `frozen`, `extra="forbid"`), every projection a free `to_*_view()` function:

```python
class BroadcastBodyInput(ApiModel):
    language: Language
    text: str = Field(min_length=1, max_length=BROADCAST_BODY_LENGTH)
    button_label: str | None = Field(default=None, max_length=64)
    button_url: HttpUrl | None = None

class BroadcastCreateRequest(ApiModel):
    title: str = Field(min_length=1, max_length=120)
    kind: BroadcastKind
    segment: SegmentModel
    bodies: list[BroadcastBodyInput] = Field(min_length=1, max_length=len(Language))

class BroadcastScheduleRequest(ReasonedRequest):
    scheduled_for: datetime | None = None      # aware or 422, via require_aware
    expected_audience_size: int | None = None  # optimistic concurrency, see below
```

**`expectedAudienceSize` is the safety catch.** The wizard shows a dry-run count; between that render and the schedule click, the world moves. The handler recomputes the exact count and, if `expected_audience_size` is set and differs by more than `settings.admin_broadcast_audience_drift_tolerance` (default 5%), refuses with `409 AUDIENCE_DRIFTED` carrying both numbers. FR-90's "the dry-run count matches a direct query" is otherwise a promise nobody can keep.

Validation on bodies, at create/revise time (in the schema, not the handler):
- `_escaped_len(text) <= MAX_MESSAGE_CHARS` — measured **HTML-escaped**, reusing `delivery._escaped_len`, because the bot runs `parse_mode=HTML` globally.
- HTML tags restricted to Telegram's set (`b i u s a code pre tg-spoiler blockquote`) by an allowlist parser; anything else is a 422 naming `bodies[i].text`. An unclosed tag is a `TelegramBadRequest` at send time for *every* recipient — validating once at compose is the difference between a caught typo and a dead campaign.
- No `{placeholder}` interpolation is accepted at all. §6.1 explains why.

### 3.4 Router body shape (the canonical mutation)

```python
@router.post(BROADCAST_SCHEDULE_PATH)
async def schedule_broadcast(
    body: BroadcastScheduleRequest, db: Db, admin: Admin, container: Container, broadcast_id: UUID
) -> BroadcastDetailView:
    """Freeze the audience, write the INTENT row, and hand the send to the worker."""
    now = utc_now()
    await enforce_step_up(
        admin, container, action=StepUpAction.BROADCAST_SEND,
        subject_id=str(broadcast_id), now=now,
    )
    record = await get_broadcast(db, broadcast_id=broadcast_id)
    if record is None:
        raise _no_such_broadcast()
    if record.state is not BroadcastState.DRAFT:
        raise problem(AdminErrorCode.INVALID_STATE, "only a draft can be scheduled",
                      state=record.state.value)
    size = await count_segment_exactly(db, segment=record.segment, now=now)
    _refuse_on_drift(body.expected_audience_size, size)
    updated = await mark_scheduled(db, broadcast_id=broadcast_id, admin=admin,
                                   body=body, audience_size=size, now=now)
    await audit_sink.record(db, container, _schedule_entry(admin, record=updated, body=body,
                                                           audience_size=size), now=now)
    await container.queue.enqueue_expand(broadcast_id, now=now)   # §3.6
    return to_broadcast_detail_view(updated)
```

`now` read once and threaded through step-up, count, write, audit and the enqueue. No `try`/`except`. 404 helper `_no_such_broadcast()` returns (does not raise) a `ProblemError` and echoes no id.

The audit entry factory:

```python
def _schedule_entry(admin, *, record, body, audience_size) -> AuditEntry:
    """The INTENT row. §9.1: an external action gets a row before it happens and a row after,
    because 'we tried' and 'it landed' are different facts and only the first is knowable here."""
    return AuditEntry(
        action=AuditAction.BROADCAST_SCHEDULE,
        actor_id=admin.admin_user_id,
        actor_username=admin.username[:ACTOR_USERNAME_LENGTH],
        actor_role=admin.role,
        subject_type=BROADCAST_SUBJECT_TYPE,
        subject_id=str(record.id),
        field_names=("broadcasts.state", "broadcasts.scheduled_for"),
        record_count=audience_size,          # how many people this authorises a message to
        reason_code=body.reason_code, reason_ref=body.reason_ref, reason_text=body.reason_text,
        outcome=AuditOutcome.OK,
        ip=admin.client_ip,
    )
```

`field_names` names columns, never values. `record_count` is the audience size — the "how much did this move" column, which is what makes a 40-recipient test distinguishable from a 40 000-recipient send without reading reasons.

### 3.5 DB read/write layer

- `src/bayram/db/admin/broadcasts.py` — `list_broadcasts` / `count_broadcasts` / `get_broadcast` / `list_recipients` / `count_recipients` / `count_segment_exactly` / `segment_breakdown`. Session first and positional, everything else keyword-only, never commits, never catches. `_filtered()` + `_filtered_with_bodies()` split as usual.
- `src/bayram/db/broadcasts.py` — the **worker's** write side: `create`, `mark_scheduled`, `expand_chunk`, `claim_chunk`, `settle_recipient`, `roll_up_counters`, `mark_finished`. Module-level functions taking `AsyncSession`; a `SqlBroadcasts` facade wrapping them in `run_guarded` for the worker's never-throw boundary.
- `count_segment_exactly` is a plain `SELECT count(*) FROM (…)` over `_filtered`, **not** `bounded_total`. `account_totals` already refuses the cap for the same reason (`overview.py:111-116`); a broadcast that says "10,000+" is a broadcast nobody can approve.

### 3.6 The admin→ARQ seam (new, and the only genuinely novel plumbing)

```python
# src/bayram/admin/queue.py
class AdminQueue(Protocol):
    async def enqueue_expand(self, broadcast_id: UUID, *, now: datetime) -> Result[str]: ...
    async def enqueue_test_send(self, broadcast_id: UUID, *, telegram_user_id: int) -> Result[str]: ...

class ArqAdminQueue:
    """The one place the panel reaches the worker. Enqueueing is a Redis write and nothing
    more — it needs no bot token, which is what keeps D10 intact."""
```

Built in `build_admin_container` as a **separate** `ArqRedis` via `await create_pool(RedisSettings.from_dsn(settings.redis_url))`, held on the container as `queue: AdminQueue`. **Not** `ArqRedis(connection_pool=container.redis.connection_pool)` — the panel's client is `decode_responses=True` and arq's payloads are pickled bytes; sharing the pool corrupts them at the first non-trivial read.

- Deterministic `_job_id=f"broadcast:expand:{broadcast_id}"` — a duplicate enqueue returns `None`, which is the idempotency guarantee working, not a failure (the `ArqOrderSubmitter` precedent).
- `(TimeoutError, OSError)` → `Err(StorageError)` → `unwrap` → the standard envelope.
- A `NullAdminQueue` that returns `Err(ConfigError)` is injected in tests and in fake-provider mode, so "no worker" is a legible 503 rather than a hang.
- **Persist, then enqueue** — the write and the audit row commit with the request transaction; the enqueue is the last statement in the handler. A crash between them leaves a `ready` campaign that the worker's due-scan picks up (§4.1), so the enqueue is an optimisation, not the only path.

### 3.7 Registration (four edits, or the enumeration test fails)

1. `src/bayram/admin/routers/__init__.py` — import + `__all__` for all four builders.
2. `src/bayram/admin/app.py` — the alphabetical import block, then four `application.include_router(...)` lines in `create_app`, **no `prefix=`**, grouped with a comment (module ships more than one router).
3. `tests/test_admin/test_routes_enumeration.py` — every row into `MOUNTED_ROUTES` as `(method, PATH_CONSTANT, Permission.X)`; every non-GET also into `MUTATIONS`.
4. `admin-dashboard/src/api/broadcasts.ts` + `segments.ts` (§5.5).

---

## 4. SEND PIPELINE

### 4.1 Three jobs, on the existing machinery

`src/bayram/runtime/broadcast_job.py`, following `activity_job.py` exactly: module-level `JOB_NAME` constants, `CONTAINER_CTX_KEY`/`BOT_CTX_KEY` **re-stated not imported** (circular-import avoidance, with the comment saying so), a local `_require_container(ctx)`, a JSON-safe `dict[str, Any]` summary return, and the closing `assert fn.__name__ == JOB_NAME` for each.

| Job | Name | Role |
| --- | --- | --- |
| `expand_broadcast_audience` | `broadcast.expand` | Materialise `broadcast_recipients` in keyset chunks; re-enqueue itself; on completion set `ready` and enqueue the first send chunk. |
| `send_broadcast_chunk` | `broadcast.send` | Claim ≤ `BROADCAST_CHUNK_SIZE` pending rows, send them under the pacer, settle each, roll counters, re-enqueue successor or finish. |
| `sweep_due_broadcasts` | `broadcast.due` | `cron(minute=set(range(0, 60, 5)))` — finds `ready`/`sending` campaigns whose `scheduled_for <= now` with no live job and re-enqueues. This is the crash-recovery and the scheduled-send path in one. |

Registration: append all three to `functions` in `build_kit_worker_settings` (`jobs.py:683`), and one `cron(sweep_due_broadcasts, name=DUE_JOB_NAME, minute={0,5,…,55}, run_at_startup=False, unique=True, max_tries=1, timeout=settings.broadcast_due_timeout_s)` in `cron_jobs` (`:705`), each with the why-comment beside it that every other entry carries.

### 4.2 Expansion — resumable by construction

```
loop:
  page = keyset page of users matching compile_segment(segment, now=audience_evaluated_at)
         ORDER BY users.created_at DESC, users.id DESC   ← always the default sort, never the
                                                            campaign's display sort
  for each row: insert_or_ignore(BroadcastRecipientRow, {...}, index_elements=[broadcast_id,
                                                                              telegram_user_id])
  persist expand_cursor + recipient_count; commit
  if page.next_cursor is None: state = ready; enqueue send chunk; return
  re-enqueue self
```

- **Expansion sorts by the keyset default, not by the campaign's `sort`.** The display sort is a presentation of the preview; the send order is the account order. Conflating them makes the cursor depend on an aggregate subquery for 50 000 rows.
- `insert_or_ignore` + the UNIQUE constraint mean a replayed chunk writes nothing. This is the `user_activity_snapshots` idempotency shape: a re-run is a database no-op, not a branch someone has to get right.
- Eligibility is applied **twice**. At expansion, rows failing it are inserted as `skipped_blocked` (so the funnel is auditable and FR-101's "excluded from dry-run counts and delivered counters" is a fact in the table, not a filter someone remembers to apply). At send, the predicate is re-checked against fresh `users` state — a customer who blocked the bot an hour after expansion must not be messaged.

### 4.3 Rate limiting — the first outbound pacer in this codebase

```python
# src/bayram/runtime/pacer.py
SEND_BUDGET_KEY: Final[str] = "bayram:send:budget"
```

A Redis fixed-window counter of the `RedisWindowCounterStore.increment_by(key, n, ttl_s=2)` shape (`admin/security/ratelimit.py:246`) keyed on `f"{SEND_BUDGET_KEY}:{int(now)}"`. Before each send: `if increment_by(key, 1, ttl_s=2) > settings.broadcast_send_rate_per_s: sleep until the next second`. Cross-replica because it is Redis, which the in-memory inbound store explicitly is not.

- `broadcast_send_rate_per_s` default **12**. NFR-23 caps reminders **plus** broadcasts at 50% of ~30 msg/s; 12 leaves headroom for the reminder fan-out that FR-97 will add to the same bucket, and the bucket key is shared by name so that lands as a config change, not a rewrite.
- Per-chat 1/s needs no machinery: the UNIQUE constraint means one message per account per campaign.
- **`TelegramRetryAfter` must be handled and does not exist today.** Catch it, `await asyncio.sleep(exc.retry_after)`, leave the row `pending` (not `failed`), and **end the chunk** — re-enqueue the successor with `_defer_by=exc.retry_after`. Do not retry inside the loop; `delivery._send_song` already records that under a 429 the second call is the one most likely to deepen the wait.
- Chunk sizing: `BROADCAST_CHUNK_SIZE = 200` messages, `timeout=settings.broadcast_chunk_timeout_s` (default **120 s**, declared explicitly on the job — the `vendor_balance_job_timeout_s` precedent). At 12 msg/s a chunk is ~17 s of sending. A 50 000-recipient campaign is 250 chunks ≈ 70 minutes of wall clock, each holding one of 15 worker slots for under two minutes. A single job cannot do this: `queue_job_timeout_s` is 900 s and a customer's render is waiting behind it.

### 4.4 Resumability, and the never-double-send rule

`retry_jobs` defaults to `True` and SIGTERM cancels running tasks, so **every broadcast job will be replayed on every deploy.** The state machine is designed for it:

```
pending  --claim (UPDATE ... WHERE state='pending' AND id IN (...), rowcount is the claim)-->  sending  [COMMIT]
sending  --send ok-->    sent       [COMMIT]
sending  --Forbidden(blocked)-->  skipped_blocked  + BotBlockRecorder.record_bot_blocked(...)
sending  --Forbidden(deactivated)/BadRequest(chat not found)-->  undeliverable
sending  --other TelegramAPIError-->  failed (attempts += 1; retried while attempts < 3)
sending  --job died-->   stays 'sending'
```

**A row left in `sending` is never retried.** The sweep ages it to `unknown` after `BROADCAST_SENDING_LEASE_S` (default 300) and it counts as neither sent nor failed. That is the deliberate trade: an interrupted send may or may not have reached Telegram, and messaging a customer twice is worse than a hole in a counter. The panel shows `unknown` as its own tile so the hole is visible rather than rounded away.

The claim uses the **conditional-UPDATE-rowcount** idiom from `db/churn.py:82` (not `SELECT ... FOR UPDATE`, which SQLite lacks, so the unit suite could not exercise the production shape). `_job_id=f"broadcast:send:{broadcast_id}"` keeps one chunk job per campaign in flight, so two replicas cannot claim overlapping windows.

Pause/cancel: the handler flips `broadcasts.state`; the chunk job reads it at the top of each chunk **and every 25 messages** and returns early. A pause takes effect within ~2 seconds of sending, not at the end of the chunk.

### 4.5 Blocked handling

The send-time eligibility predicate, in one function so it cannot drift from the expansion one:

```python
def eligible(user: UserRow) -> Eligibility:
    if user.is_blocked:                  return Eligibility.SKIPPED_BLOCKED      # operator bar
    if user.blocked_bot_at is not None:  return Eligibility.SKIPPED_BLOCKED      # customer block
    return Eligibility.ELIGIBLE
```

It takes no `kind` and no consent state: there is nothing else to suppress on (§6.3). It stays a
function of a `UserRow` alone so that the day an opt-out exists it gains one parameter and one
branch, in one place, rather than a second predicate somewhere in the send loop.

Never `OR` the two blocks into one column; they are opposite facts (`models/user.py:82-109`). A refused send calls `container.bot_blocks.record_bot_blocked(telegram_user_id, at=now, source=BotBlockSource.DELIVERY_REFUSAL)` through the exact predicate `delivery.is_blocked_by_customer(exc)` — reused verbatim, never widened. A broadcast is the highest-volume block detector this system will ever have and it must feed the same recorder the delivery arm does, because `run_polling(drop_pending_updates=True)` loses `my_chat_member` events on every deploy.

### 4.6 i18n of the body

- Language per recipient is `users.ui_language`, snapshotted into `broadcast_recipients.language` at expansion. Not the profile, not the brief — the brief's language is what the customer chose when an order was confirmed and `delivery._send_closing` already warns it goes stale.
- Body lookup: exact language → `FALLBACK_LANGUAGE` (`uz_latn`) → `REFERENCE_LANGUAGE` (`en`), mirroring `bot/i18n._resolve_template`. If none of the three exists the row is `failed` with `error_code="no_body_for_language"` — and the create/revise validator refuses a campaign whose bodies do not cover every language present in its own preview breakdown, so this is a defence, not a routine path.
- The body is **literal operator-authored text**, not a catalogue key, and is **not** passed through `translate()`. It is validated as HTML at compose time (§3.3) and sent as-is. `escape_html` is not applied at send — the operator's intentional `<b>` must survive.
- The optional button becomes an `InlineKeyboardMarkup` with a single URL button. No callback buttons: a callback needs a bot handler, and adding one for a campaign that ended last month is how a dead callback becomes a customer-visible error.

### 4.7 Progress reporting

- Per chunk, one grouped `SELECT state, count(*) … GROUP BY state` over `(broadcast_id, state)` and one `UPDATE broadcasts SET sent_count=…, …` — two statements, not one per recipient.
- The job's return dict (`{"broadcast_id", "claimed", "sent", "failed", "skipped", "remaining"}`) is ARQ's job result, which lives `keep_result = 3600 s`. It is **operational garnish, never the record** — Postgres is the progress store.
- The **OUTCOME audit row** is written by `mark_finished` inside the worker's transaction: `AuditAction.BROADCAST_SENT`, actor = the operator stored on `scheduled_by_admin_id`/`_username`/`_role`, `subject_type="broadcast"`, `subject_id=str(id)`, `record_count=sent_count`, `field_names=("broadcasts.state", "broadcasts.sent_count")`, reason copied from the schedule request. Use `audit.append` directly (the same primitive `audit_sink` wraps) — `audit_sink.record` takes an `AdminContainer` the worker does not have.

---

## 5. FRONTEND (`admin-dashboard/`)

### 5.1 New files

```
admin-dashboard/src/
  api/
    segments.ts                  SEGMENT_ENDPOINT map, zod schemas for the field registry +
                                 preview, getSegmentFields(), previewSegment()
    broadcasts.ts                BROADCAST_ENDPOINT map, zod schemas, list/get/create/revise/
                                 schedule/pause/resume/cancel/testSend/listRecipients
  lib/
    segmentCodec.ts              Segment type, encodeSegment/decodeSegment (base64url, never
                                 throws — a hand-edited URL degrades to the default view),
                                 countRules(), isSegmentEmpty()
  components/
    SegmentBuilder/
      SegmentBuilder.tsx         the group/rule tree editor
      RuleRow.tsx                field <select> · operator <select> · value editor
      valueEditors.tsx           IntEditor, InstantRangeEditor, EnumMultiEditor, BoolEditor,
                                 RelativeDaysEditor  (registry keyed on FieldKind)
      segmentChips.ts            Segment -> FilterChip[] with an operator in the label
      useSegmentFields.ts        cached query over GET /api/segments/fields
  features/broadcasts/
    BroadcastsScreen.tsx         the campaign list
    BroadcastDetailScreen.tsx    counters, recipient table, pause/resume/cancel
    BroadcastWizard.tsx          the three-step flow (a route, not a dialog)
    useBroadcasts.ts             query keys + hooks (filterKey/pageKey canonicalisers)
    broadcastState.ts            state -> label/tone, DOM-free
    steps/AudienceStep.tsx  steps/MessageStep.tsx  steps/ReviewStep.tsx
```

### 5.2 `SegmentBuilder` — the reusable component

Props, deliberately state-free (the URL or the wizard owns the value):

```ts
interface SegmentBuilderProps {
  readonly value: Segment;
  readonly onChange: (next: Segment) => void;
  readonly fields: readonly SegmentField[];      // from GET /api/segments/fields
  readonly showSort?: boolean | undefined;       // Users screen: true; wizard: false
  readonly maxRules?: number | undefined;
  readonly label?: string | undefined;
}
```

- **The field list comes from the server.** The builder renders what `/api/segments/fields` returns and nothing else, so the privacy allowlist has exactly one home. Never derive options from a row schema.
- Operator options come from the field's `ops`; the value editor is chosen from `field.kind` via a registry. Changing the field resets the operator and value rather than trying to carry them.
- Group nesting to depth 3 with `[ + rule ] [ + group ]` and a visible `all / any / none` toggle per group. The header of the root group states the semantics in words ("accounts matching **all** of:"), because AND/OR mis-read is the top failure mode of every filter builder ever shipped.
- **Live preview inside the builder**: a debounced (400 ms) `previewSegment` call rendering `matched` and, on the wizard, the eligibility breakdown. The count is what an operator actually reasons about.
- Chips: `segmentChips.ts` produces `{id, field, value, onRemove}` for the existing `FilterChips` component, with the operator folded into the label — `"Delivered songs ≥ 3"`, `"Joined 1 Jun – 1 Jul"`, `"Not seen in 90 days"`. `activeFilterCount` counts **parsed leaf rules**, not the one `segment` URL key, or "Clear all 1 filter" lies about a nine-clause segment.
- 400 ms debounce, commit on Enter and blur, `maxLength` mirroring server caps — the conventions every existing text filter follows.

### 5.3 Where it plugs into the Users screen

`admin-dashboard/src/features/users/UsersScreen.tsx`:
- `UsersUrlState` gains `segment?: string` (the encoded document) and `sort?: string` (`"key:dir"`).
- The disclosed filter panel (`hidden={!isPanelOpen}`) gains a second section, **"Advanced segment"**, holding `<SegmentBuilder showSort />`. The six existing chip controls stay exactly as they are — they are the fast path, the builder is the complete one. Chips from both sources render in one row.
- Every mutation of the segment resets `cursor` **and** the `Walk` back-trail, like every other filter write.
- A **"Send a broadcast to these people"** button appears beside the chips when a segment is non-empty, gated by `hasPermission(role, "broadcast.write")`; it routes to `/broadcasts/new?segment=<same encoded string>`. That is the whole integration: one encoded document, two screens.

### 5.4 The wizard

Route `/broadcasts/new` (and `/broadcasts/:broadcastId/edit` for a draft) — a **route, not a dialog**, because it carries a segment in the URL and must survive a refresh. State machine in `BroadcastWizard.tsx` as a discriminated union, the `RevealPhase` shape:

```ts
type WizardPhase =
  | { kind: "audience" }
  | { kind: "message" }
  | { kind: "review" }
  | { kind: "submitting" }
  | { kind: "stepUp"; target: StepUpTarget; body: BroadcastScheduleRequest }  // remembered body
  | { kind: "drifted"; expected: number; actual: number; body: BroadcastScheduleRequest }
  | { kind: "scheduled"; broadcastId: string };
```

| Step | Contents | Advance gate |
| --- | --- | --- |
| **1 Audience** | `<SegmentBuilder showSort={false} />` + live preview: matched / reachable / skipped-blocked / by-language table | `reachable > 0` |
| **2 Message** | Campaign title, `kind` (service/marketing) — a label on the record, suppressing nothing today (§6.3) — one body editor per language present in the breakdown, escaped char counter against 4096, optional button, an HTML preview panel | every language in the breakdown has a non-empty body |
| **3 Review** | Frozen summary, the dry-run count restated, "send now" vs a scheduled instant, required `reasonCode` + optional `reasonRef`/`reasonText`, and a typed confirmation of the audience size (the operator types the number) | reason present, confirmation matches |

Submit → `POST /broadcasts` (if new) → `POST /schedule` carrying `expectedAudienceSize`. A `403 STEP_UP_REQUIRED` moves to `stepUp` and **replays the identical body** with `subjectId` verbatim after re-auth — never a second password form, always the existing `StepUpDialog` inside `DialogShell`. A `409 AUDIENCE_DRIFTED` moves to `drifted`, shows both numbers, and offers "review again" or "send to the current audience".

Step indicator: the existing `Segmented` component. No stepper library, no form library (neither app has one; `ConfirmDialog`'s reason field is hand-validated and that is the house pattern).

### 5.5 Campaign list, nav, RBAC

- `BroadcastsScreen`: `Toolbar` + state filter chips + `DataTable` columns `[title, kind, state, audience, sent, failed, skipped, scheduledFor, createdBy]` with a `Sparkline`-free progress bar for `sending`. Poll `sending`/`expanding` rows at the list tier; stop polling when nothing is in flight.
- `BroadcastDetailScreen`: counter tiles, the frozen segment rendered read-only through `SegmentBuilder` in a disabled mode, the recipient table (masked ids, state filter, cursor pager), and pause/resume/cancel through `ConfirmDialog` with its built-in reason field.
- Nav: one `PRIMARY_NAV` entry `{ key: "broadcasts", label: "Broadcasts", href: PATH.broadcasts, icon: Megaphone }` in `admin-dashboard/src/app/navItems.ts`, plus `PATH.broadcasts` / `broadcastDetailPath()` in `app/paths.ts` and the routes in `routes.tsx` — **literal `broadcasts/new` registered before `broadcasts/:broadcastId`**.
- RBAC: `admin-dashboard/src/lib/rbac.ts` gains the three permissions (the `satisfies Record<Permission, …>` makes a missed one a compile error). admin-dashboard gates by rendering the server's denial rather than hiding nav; keep that — but hide the *write* controls (`Schedule`, `Pause`, `Cancel`) behind `hasPermission`, since a button that always 403s is worse than no button.
- **The nav entry has its spec line already.** `ADMIN_PANEL_PLAN` §11.2's rail enumeration and per-route table were amended in the same change that filed this document, because `navItems.ts` is transcribed from §11.2 and is explicitly "not extended by inference", and `TopBar.tsx:29-32` refuses a notifications *button* by name. A `/broadcasts` route is a different artefact and `DECISIONS.md` **D12** says so in full, so this is a recorded reversal rather than a silent one.

---

## 6. PRIVACY & POLICY

### 6.1 What the segment and the send may touch

1. **No name, phone, username or free-text predicate exists at any role.** Not `eq`, not `contains`, not `startswith`. Those four columns are `M` at all four roles including OWNER, so a caller-steered `WHERE` over them recovers a masked value by binary search with no step-up, no budget unit and no audit row. `SEGMENT_REFUSALS` is a module constant and a test asserts no builder closure touches those columns — the refusal must be a diff a reviewer sees.
2. **Presence is fine, value is not.** `has_phone` discloses one bit an operator can already see on the row (`isProfilePresent`, `phoneSharedAt`). `phone_e164 = '+9989…'` discloses the number.
3. **`last_seen_at` is filterable, not projectable, not sortable.** A predicate discloses the bucket the operator picked; a projection or a sort discloses a per-account value the panel deliberately withholds.
4. **Every row this feature puts on the wire is masked.** `/broadcasts/{id}/recipients` carries `telegramUserIdMasked` and no raw id — unlike `/users`, which needs the raw id because every `/users/**` route keys on it. A recipient list has no such need, so it does not get one. `ApiModel(frozen, extra="forbid")` makes that checkable.
5. **The message body carries no personalisation.** Addressing a customer by first name would require one `POST /reveal` per recipient — 1 record each against a 200/hour ceiling with `MAX_RECORDS_PER_REVEAL = 50`. That is structurally a refusal at any scale, and it is the right one: a marketing message is not a support ticket. Personalising from `users.ui_language` is free and is the only personalisation there is.
6. **Recipient data (`briefs.recipient_*`) is not an audience dimension and never will be.** SEC-9: "recipient data is order-scoped, never enriched, **never used for marketing**. We never contact the recipient." LR-51 repeats it. The audience is built from `users` — purchasers — full stop. No field in the registry reads `briefs`.
7. **The exact count.** `count_segment_exactly` bypasses `bounded_total`. FR-90's test is that the dry-run count matches a direct query; a saturating count cannot pass it.

### 6.2 Retention and `/forget`

`broadcast_recipients` holds a Telegram id, two closed enums, a bounded error code and clocks — no name, no note, no free text *about* a person. It therefore takes the **third route** that `bot_membership_events`, `topup_purchases` and `payment_intents` take:

- **In neither** `tables_with_personal_data` **nor** `tables_erased_on_request`, with a comment block in `tests/test_db/test_privacy_constraints.py` in the shape of the four existing exemptions, arguing it explicitly.
- **No `*_expires_at` column.** That suffix is reserved for legal clocks a sweep reads, and claiming one here would oblige a `RetentionPolicy` field and a `SweepCounts` entry for a schedule this table does not have.
- **Bounded by a cutoff**, not a clock: `BROADCAST_RECIPIENT_RETENTION_DAYS: Final[int] = 400` in `bayram/db/purge.py`, a `_broadcast_recipients_due(now)` predicate written **once** and read by both the delete branch and `rows_past_expiry_statements` (the module's own stated rule), a `PurgeReport.broadcast_recipients_deleted` field, and the matching `purge_runs` column from rev 0024. `SweepCounts` in `admin/schemas/retention.py` gains the field too — it is `extra="forbid"` with every field required precisely so a forgotten clock fails loudly.
- **`/forget` anonymises in place.** `credit_erasure.forget_account` gains `broadcast_recipients` to its list of `UPDATE … SET telegram_user_id = NULL` tables. The counts survive (a completed campaign's arithmetic must not change retroactively), the identity does not. `broadcasts` and `broadcast_bodies` hold no customer data at all and are untouched.

### 6.3 Out of scope for the initial build

**Broadcasts ship with no opt-out mechanism.** There is no consent table, no `marketing_consents`
row, no `/stop` command, no consent line in any of the four copy catalogues, and no per-recipient
suppression an operator or a customer can set. Nothing in §1's registry, §2's schema, §3's API or
§4's pipeline reads one. That is a deliberate scope cut for the first build, recorded here so it is
a decision somebody made rather than a gap somebody missed.

**The only suppression signal is a Telegram block**, and it is respected in two places: at expansion
and again at send (§4.2, §4.5), against fresh `users` state each time. Both arms of it —
`users.is_blocked` (the operator's bar) and `users.blocked_bot_at` (the customer's own block) — skip
the recipient and record why, and a send refused by Telegram feeds `record_bot_blocked` through the
delivery arm's existing predicate, so every campaign makes the next one narrower.

**What this obliges before the position changes.** `BroadcastKind.MARKETING` exists as a label and
suppresses nothing (§2.1), so nothing about the schema has to move when consent arrives. What has to
exist first is a consent record, a customer-facing way to revoke that a bot handler serves, a
localised revocation line the create validator can require in every marketing body, and an answer to
LR-42/D-4 on lawful basis. Until then, treat a `marketing` campaign as a decision a human takes
knowingly, not as one the system has cleared. §7 Q10 is where that question sits.

### 6.4 Audit

- **Two rows per send, not one.** `broadcast.schedule` (INTENT, in the request transaction, `record_count` = audience size) and `broadcast.sent` (OUTCOME, written by the worker at completion, `record_count` = messages actually sent). §9.1 treats an external action as needing both because "we tried" and "it landed" are different facts and only the first is knowable in the request.
- Pause / resume / cancel each write their own row — the audit log is queried by equality on `action`, which is exactly why block and unblock are two actions rather than one boolean.
- `subject_type = "broadcast"`, `subject_id = str(uuid)` (matches `^[A-Za-z0-9:._-]{1,64}$`), `field_names` naming columns only. **No recipient id ever reaches an audit row** — a campaign has one subject, the campaign.
- `reason_code` is mandatory on schedule/pause/cancel via `ReasonedRequest`. `reason_text` is control-char-stripped and swept at 90 days; the row itself lives 730.
- A refused schedule (wrong role, missing step-up) is audited by `record_refusal` in its own committed transaction — never `record`, because the request transaction is about to roll back.

---

## 7. RISKS & OPEN QUESTIONS

| # | Question | Why it needs a human |
| --- | --- | --- |
| **Q1** | **Does a `/broadcasts` route reverse a written refusal?** `TopBar.tsx:29-32` and PLANIQ §PQ6 refuse a *notifications button* by name; `navItems.ts` is "transcribed from §11.2, not extended by inference". | **Answered.** `DECISIONS.md` **D12** records the reversal and `ADMIN_PANEL_PLAN` §11.2 gained the rail entry and the three route rows in the same change as this spec. The nav item may not ship ahead of either. |
| **Q2** | **FR-90 is a SHOULD, and ARC-4's irreducible launch minimum excludes the broadcast composer.** | Is this being built now because it is needed now, or because it was asked for? The answer changes how much of §5 can wait behind §1's segment engine, which is independently valuable. |
| **Q3** | **Is `12 msg/s` right?** NFR-23's 50% of ~30 msg/s is shared with the unbuilt reminder fan-out (FR-97, default 20 msg/s — the two numbers already exceed the cap). | Whoever owns NFR-23 must allocate the shared budget before both exist, or the first reminder release silently breaks the broadcast SLA. |
| **Q4** | **Should the worker's Bot get `ChatLogOutboundMiddleware`?** It is attached only to the bot process today. Attaching it logs broadcast sends into `chat_messages` — and also starts logging every kit delivery, a behaviour change, at 50 000 rows per campaign against §7.3's retention. | Recommendation: **no**. `broadcast_recipients` is the send log. Needs an explicit ruling. |
| **Q5** | **Aggregate sorting at scale.** Correlated subqueries in `ORDER BY` over the whole filtered set are fine at today's volume and not at 500 k users. | Decide whether to accept the ceiling or schedule a `user_rollups` materialised table (nightly, like `user_activity_snapshots`). |
| **Q6** | **`admin-dashboard` has no test runner and is untracked.** Everything in §5 ships untested unless vitest is added. | Add vitest or accept it. Given this feature can message every customer, "accept it" is hard to defend. |
| **Q7** | **Scheduled sends and the `aizu` host.** A 70-minute campaign spans deploys. §4.4 handles it, but nobody has verified worker restart behaviour on the real host (SSH is blocked to this session; host facts must come from the user). | Someone must run a 5 000-recipient rehearsal against staging with a mid-flight deploy. |
| **Q8** | **`sending` → `unknown` holes.** The never-double-send rule means a counter that does not add up after a crash. | Confirm that "we do not know if 3 of 40 000 were delivered" is preferred to "3 people got it twice". This spec assumes yes. |
| **Q9** | **Test-send allowlist.** `settings.admin_broadcast_test_recipients` is a config list of Telegram ids. Without it, test-send is an arbitrary-message-to-any-customer endpoint. | Confirm the mechanism and who populates it. |
| **Q10** | **No opt-out ships with this build (§6.3).** LR-42 wants marketing consent separate, affirmative and revocable; LR-54's in-bot notice does not exist; D-4's lawful basis is unresolved. | Product + legal must say when the absence becomes the blocker — at the first `marketing` campaign, or at the first `service` one. The answer decides whether the next phase is a consent table or nothing at all. |
