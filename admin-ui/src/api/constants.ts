/**
 * Constants the server enforces, restated on the client so a form can refuse before a round
 * trip. Every value here has a named source in the Python tree; if one of them is wrong the
 * server still wins, and the disagreement shows up as a 422 rather than as silent drift.
 */

/** `bayram.admin.deps.API_PREFIX`. Same origin, always — never an absolute URL (§11.1). */
export const API_PREFIX = "/api";

/** `bayram.admin.deps.AUTH_PREFIX`. */
export const AUTH_PREFIX = "/api/auth";

/** The two probes live OUTSIDE `/api`. */
export const HEALTHZ_PATH = "/healthz";
export const READYZ_PATH = "/readyz";

/* --------------------------------------------------------------------------
 * Headers and cookies — bayram/admin/csrf.py, bayram/admin/middleware/correlation.py
 * -------------------------------------------------------------------------- */

/** Echoed on every non-GET; read out of the (non-HttpOnly) CSRF cookie. */
export const CSRF_HEADER_NAME = "X-CSRF-Token";

/** The only cookie the SPA can read. The session cookie is HttpOnly and must stay so. */
export const CSRF_COOKIE_NAME = "__Host-bayram_csrf";

/** HttpOnly. Named here for documentation only — JavaScript cannot and must not read it. */
export const SESSION_COOKIE_NAME = "__Host-bayram_session";

/** On every response, and equal to `error.correlationId` in a failure body. */
export const CORRELATION_HEADER = "X-Correlation-ID";

/** Seconds, as a decimal string, on every 429 and on the limiter's 503. */
export const RETRY_AFTER_HEADER = "Retry-After";

/** `^[0-9a-f]{32}$` — the shape the server accepts inbound and always emits outbound. */
export const CORRELATION_ID_PATTERN = /^[0-9a-f]{32}$/;

/* --------------------------------------------------------------------------
 * Pagination — bayram/db/admin/page.py
 * -------------------------------------------------------------------------- */

export const MIN_PAGE_LIMIT = 1;
export const MAX_PAGE_LIMIT = 200;
export const DEFAULT_PAGE_LIMIT = 50;

/**
 * `bounded_total` stops counting here. `{total: 10000, isTotalExact: false}` therefore means
 * "10,000+" and must be rendered with the plus — never as a flat 10,000.
 */
export const TOTAL_COUNT_CAP = 10_000;

/** `/api/retention` alone defaults to 24, not 50. */
export const DEFAULT_RETENTION_LIMIT = 24;
export const MAX_RETENTION_LIMIT = 200;

/** `/api/assets?expiringWithinDays=` — no lower bound on the window; already-expired rows
 *  are included, because they are the most urgent line on the retention page. */
export const MAX_EXPIRING_WITHIN_DAYS = 365;

/** `GET /api/admins` is a bounded whole-table read, not a page. */
export const MAX_ADMIN_ACCOUNTS = 500;

/* --------------------------------------------------------------------------
 * Field bounds — the models
 * -------------------------------------------------------------------------- */

/**
 * `q` longer than this is a 422 from the server, not a narrower list — see
 * `MAX_SEARCH_CHARS` in `bayram/db/admin/sql.py`, where 64 is chosen as longer than any
 * correlation id (32) or telegram id (19 digits). Cap the INPUT with it so a pasted
 * paragraph is truncated in the box the operator can see, rather than rejected wholesale.
 */
export const MAX_SEARCH_CHARS = 64;

export const MAX_CORRELATION_ID_CHARS = 128;
export const MAX_ERROR_CODE_CHARS = 48;
export const MAX_PROVIDER_CHARS = 64;
export const MIN_PASSWORD_CHARS = 8;
export const MAX_PASSWORD_CHARS = 256;
export const MAX_USERNAME_CHARS = 64;
export const MAX_SUBJECT_ID_CHARS = 96;
export const MAX_STEP_UP_SCOPE_CHARS = 128;

/** `error.message` is redacted then capped at this length by the server. */
export const MAX_MESSAGE_CHARS = 300;

/* --------------------------------------------------------------------------
 * Masking — bayram/admin/serializers/redaction.py
 * -------------------------------------------------------------------------- */

/**
 * THREE U+2022 BULLET. Not three asterisks, not an ellipsis. Comparing against `"***"`
 * silently never matches.
 *
 * `recipientName === null` and `recipientName === MASK` are DIFFERENT FACTS:
 * `null` means the identity was purged (check `identityPurgedAt`); `MASK` means the stored
 * name was empty or whitespace. A `??` that collapses them is a bug.
 */
export const MASK = "•••";

/** FIVE U+2022, fixed width, then the last three digits: `•••••789`. */
export const TELEGRAM_ID_MASK_PREFIX = "•••••";

/** `TELEGRAM_ID_VISIBLE_DIGITS`. An id with ≤3 digits masks to the bare prefix. */
export const TELEGRAM_ID_VISIBLE_DIGITS = 3;

/* --------------------------------------------------------------------------
 * Copy strings the plan pins by hand
 * -------------------------------------------------------------------------- */

/**
 * §11.2: `lastSeenAt` is labelled "last seen" only from Phase 3, when the inbound upsert
 * gives it a real writer. `UserView` carries `lastOrderAt` and deliberately has NO
 * `lastSeenAt`, so the column header reads exactly this.
 */
export const LAST_ORDER_COLUMN_LABEL = "last order";

/**
 * Copy for the tri-state booleans (`isRetryable`, `isFailedReasonRetryable`). `null` means
 * no class in `bayram.errors` claims the code — render this and offer no retry. It is not
 * "not retryable", which is a decision; it is the absence of one.
 */
export const UNKNOWN_RETRYABILITY_LABEL = "unknown";

/** `costUsd` / `latencyMs` are `null`, never `0`, when `isInstrumented` is false. */
export const NOT_INSTRUMENTED_LABEL = "not instrumented";

/**
 * `TimelineView.unavailableSources` — an absent section reads as this, never as
 * "nothing happened".
 */
export const SOURCE_UNAVAILABLE_LABEL = "not enabled in this deployment";

/**
 * `hasReasonText === true` with `reasonText === null` at ADMIN. Never "no reason given".
 */
export const REASON_WITHHELD_LABEL = "a reason was recorded, you may not read it";

/* --------------------------------------------------------------------------
 * The reveal — bayram/admin/schemas/reveal.py, bayram/admin/security/budget.py
 * -------------------------------------------------------------------------- */

/**
 * `budget.MAX_RECORDS_PER_REVEAL`. §12.3: "a conversation reveal returns **at most 50
 * bodies**; more requires a fresh reveal with a `nextCursor`, each one charged and each one
 * audited." It is both the schema's `limit` ceiling and the largest charge one request can
 * make, which is why a paged reveal's cost is knowable before it is sent.
 */
export const MAX_RECORDS_PER_REVEAL = 50;

/** `admin_audit_log.reason_text` is `String(500)`; the server strips control chars too. */
export const MAX_REASON_TEXT_CHARS = 500;

/** `admin_audit_log.reason_ref` is `String(64)`. */
export const MAX_REASON_REF_CHARS = 64;

/**
 * `reveal.REASON_REF_PATTERN`, restated so a ticket reference is refused by the form rather
 * than by a 422.
 *
 * It is NOT the whole truth and the disagreement is the plan's, not a bug here:
 * `bayram/db/admin/audit.py`'s `_CREDENTIAL_SHAPES` additionally refuses any
 * `[A-Za-z0-9_-]{40,}` run, so a 40-character slug satisfies this pattern and is still
 * refused at the audit boundary — as a 422 naming the field, with no plaintext returned and
 * no audit row written. `LONG_REASON_REF_CHARS` is where that second rule starts.
 */
export const REASON_REF_PATTERN = /^[A-Za-z0-9#_-]{1,64}$/;

/** The length at which `_CREDENTIAL_SHAPES` starts reading a reference as a credential. */
export const LONG_REASON_REF_CHARS = 40;

/** `page._MAX_CURSOR_CHARS`. A cursor this API did not mint is a 422. */
export const MAX_REVEAL_CURSOR_CHARS = 256;

/**
 * The two budget windows, in seconds — `budget.REVEAL_RECORDS_WINDOW_S` and
 * `REVEAL_CONVERSATIONS_WINDOW_S`.
 *
 * They are **fixed and epoch-aligned**, not sliding: the window index is baked into the
 * Redis key, so the "hour" resets on the clock hour and the "day" is a UTC day. That is
 * what makes "resets in 12 min" computable on the client without asking the server, and it
 * is also why 200 records at 10:59 and 200 more at 11:00 is inside policy.
 */
export const REVEAL_RECORDS_WINDOW_S = 3_600;
export const REVEAL_CONVERSATIONS_WINDOW_S = 86_400;
