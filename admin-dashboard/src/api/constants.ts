/**
 * Server-enforced names and bounds, restated here so a form can refuse before a round trip.
 * Every value has a named source in the Python tree; the server still wins, and a
 * disagreement shows up as a 422 rather than as silent drift.
 *
 * These are copied from admin-ui/src/api/constants.ts — the same API, a second SPA. Copied
 * rather than imported: the two apps have separate dependency trees and no build-time link,
 * and a cross-package relative import would tie this one's build to the other's layout.
 */

/** `hbd.admin.deps.AUTH_PREFIX`. Same origin, always — never an absolute URL. */
export const AUTH_PREFIX = "/api/auth";

/** `hbd.admin.routers.dashboard._OPS_PREFIX` — the two unwindowed probes live under it. */
export const OPS_PREFIX = "/api/ops";

/** `hbd.admin.routers.dashboard._METRICS_PREFIX`. The four windowed sections hang off it. */
export const METRICS_PREFIX = "/api/metrics";

/** Echoed on every non-GET; read out of the (non-HttpOnly) CSRF cookie. */
export const CSRF_HEADER_NAME = "X-CSRF-Token";

/** The only cookie the SPA can read. The session cookie is HttpOnly and must stay so. */
export const CSRF_COOKIE_NAME = "__Host-hbd_csrf";

/** On every response, and equal to `error.correlationId` in a failure body. */
export const CORRELATION_HEADER = "X-Correlation-ID";

/** Seconds, as a decimal string, on every 429 and on the limiter's 503. */
export const RETRY_AFTER_HEADER = "Retry-After";

/** `admin_users.username` — staff, not customers, so it is in the clear. */
export const MAX_USERNAME_CHARS = 64;

/** Password constraints enforced on credential rotation. */
export const MIN_PASSWORD_CHARS = 8;
export const MAX_PASSWORD_CHARS = 256;

/* -------------------------------------------------------------------------- */
/* Users, generations and reveal — Phase 2's routes and their server bounds     */
/* -------------------------------------------------------------------------- */

/** `hbd.admin.routers.users.USERS_PATH`. Every `/users/**` route hangs off it. */
export const USERS_PREFIX = "/api/users";

/** `hbd.admin.routers.generations.GENERATIONS_PATH`. */
export const GENERATIONS_PREFIX = "/api/generations";

/** `hbd.admin.routers.reveal.REVEAL_PATH` — the ONE route by which masked becomes plain. */
export const REVEAL_PATH = "/api/reveal";

/**
 * `hbd.db.admin.sql.MAX_SEARCH_CHARS`. Over-long `q` is a 422 naming the parameter, so the
 * input is capped rather than truncated silently — a widened match is a page nobody can explain.
 */
export const MAX_SEARCH_CHARS = 64;

/** `generation_attempt.PROVIDER_LENGTH` — the `provider` filter's bound. */
export const MAX_PROVIDER_CHARS = 64;

/** `generation_attempt.ERROR_CODE_LENGTH` — the `errorCode` filter's bound. */
export const MAX_ERROR_CODE_CHARS = 48;

/** `admin_audit_log.reason_text`, on the 90-day sweep. */
export const MAX_REASON_TEXT_CHARS = 500;

/** `admin_audit_log.reason_ref` — a ticket id, not prose. */
export const MAX_REASON_REF_CHARS = 64;

/**
 * `schemas.actions.ReasonedRequest`'s pattern, restated so a form refuses before the round
 * trip: a rejected body writes no audit row, which is the wrong way to fail a §9.2 action.
 */
export const REASON_REF_PATTERN = /^[A-Za-z0-9#_-]{1,64}$/;

/** `security.budget.MAX_RECORDS_PER_REVEAL` — §12.3's cap on one paged reveal. */
export const MAX_RECORDS_PER_REVEAL = 50;

/** `RevealRequest.fields` — one per member of `RevealField`, and at least one. */
export const MAX_REVEAL_FIELDS = 12;
export const MIN_REVEAL_FIELDS = 1;

/** `CreditGrantRequest.credits`. A comp, not a top-up rail. */
export const MIN_GRANT_CREDITS = 1;
export const MAX_GRANT_CREDITS = 100;

/** `StepUpRequest.subjectId` — a UUID or a Telegram id, never longer than the scope column. */
export const MAX_STEP_UP_SUBJECT_CHARS = 96;

/* -------------------------------------------------------------------------- */
/* The operator roster                                                         */
/* -------------------------------------------------------------------------- */

/** `hbd.admin.routers.admins.ADMINS_PATH`. One route hangs off it, and it is a GET. */
export const ADMINS_PREFIX = "/api/admins";

/**
 * `hbd.db.admin.accounts.MAX_ADMIN_ACCOUNTS` — the `LIMIT` the roster read is taken under.
 *
 * It is a ceiling, not a page size: the response carries no cursor, no total and no flag
 * saying it was cut. So a roster of exactly this many rows is one that MAY be truncated and
 * cannot say, and the only honest thing a screen can do is name the possibility rather than
 * claim a completeness the wire does not carry.
 */
export const MAX_ADMIN_ACCOUNTS = 500;

/* -------------------------------------------------------------------------- */
/* The audit log                                                               */
/* -------------------------------------------------------------------------- */

/**
 * `hbd.admin.routers.audit.AUDIT_PATH`. `VERIFY_PATH` is this plus `/verify`, and both are
 * mounted with their full path in the decorator over a router with no prefix of its own — so
 * these are the literal paths, not a base a router extends.
 */
export const AUDIT_PREFIX = "/api/audit";

/** `build_query`'s `subjectType` bound. Over-length is a 422 naming the parameter. */
export const MAX_SUBJECT_TYPE_CHARS = 32;

/** `build_query`'s `subjectId` bound, and `admin_audit_log.subject_id`'s own width. */
export const MAX_SUBJECT_ID_CHARS = 64;

/* -------------------------------------------------------------------------- */
/* Broadcasts — the campaign namespace and the columns a compose form writes    */
/* -------------------------------------------------------------------------- */

/**
 * `hbd.admin.routers.broadcasts.BROADCASTS_PATH`. Every `/broadcasts/**` route hangs off it,
 * across BOTH routers: the reads are guarded by `broadcast.read` and the seven writes by
 * `broadcast.write`, but they share one path space and one prefix.
 */
export const BROADCASTS_PREFIX = "/api/broadcasts";

/** `db.models.broadcast.BROADCAST_TITLE_LENGTH`. Operator copy, never a customer's words. */
export const MAX_BROADCAST_TITLE_CHARS = 120;

/**
 * `db.models.broadcast_body.BROADCAST_BODY_LENGTH` — Telegram's message ceiling, and the
 * column's.
 *
 * **The server measures it twice**, on the raw text against this and on the RENDERED text
 * against the same number, because `&` is one character in the editor and five on the wire.
 * A form counting only what was typed will let a body through that the server refuses, so
 * count the raw text against this AND read `renderedLength` back off the body view.
 */
export const MAX_BROADCAST_BODY_CHARS = 4_096;

/**
 * `BROADCAST_CAPTION_LENGTH`. A photo caption is a quarter of a message, so a body WITH an
 * image is bounded by this instead — `broadcastBodyLimit` in `api/broadcasts.ts` is the one
 * place that chooses between the two.
 */
export const MAX_BROADCAST_CAPTION_CHARS = 1_024;

/** `BUTTON_LABEL_LENGTH`. A label with no URL is refused, and so is a URL with no label. */
export const MAX_BROADCAST_BUTTON_LABEL_CHARS = 64;

/** `BUTTON_URL_LENGTH`. Absolute `http(s)` with a dotted host — see `api/broadcasts.ts`. */
export const MAX_BROADCAST_BUTTON_URL_CHARS = 512;

/** `MEDIA_STORAGE_KEY_LENGTH`. An object-store key we wrote, never a Telegram `file_id`. */
export const MAX_BROADCAST_MEDIA_KEY_CHARS = 512;

/**
 * `schemas.broadcasts.MAX_BODIES`, which is `len(Language)` and not a literal `4` — one body
 * per language and no more, with a duplicate language a 422 rather than an `IntegrityError`.
 */
export const MAX_BROADCAST_BODIES = 4;

/* -------------------------------------------------------------------------- */
/* Segments — the audience DSL both the Users list and a campaign are written in */
/* -------------------------------------------------------------------------- */

/**
 * `hbd.admin.routers.segments.SEGMENT_FIELDS_PATH` / `SEGMENT_PREVIEW_PATH`.
 *
 * Two routes under one prefix and behind two DIFFERENT permissions — the registry is
 * `broadcast.read`, the preview is `records.read` — so they are spelled out rather than
 * composed from a base a caller might assume shares a guard.
 */
export const SEGMENT_FIELDS_PATH = "/api/segments/fields";
export const SEGMENT_PREVIEW_PATH = "/api/segments/preview";

/**
 * `schemas.segment.SEGMENT_SCHEMA_VERSION` — the document shape this bundle speaks.
 *
 * Required in every document and never defaulted: it is the only thing that tells version 2
 * apart from a client that never heard of versions. The registry publishes the version it
 * expects; `lib/segmentCodec.isSupportedSegmentVersion` is what compares the two.
 */
export const SEGMENT_SCHEMA_VERSION = 1;

/**
 * `schemas.segment.MAX_SEGMENT_CHARS`. The base64url token's ceiling, checked BEFORE anything
 * decodes it — it bounds the work every later step does, which is why the client checks it in
 * the same place and in the same order.
 */
export const MAX_SEGMENT_CHARS = 4_096;

/** `schemas.segment.MAX_SEGMENT_KEY_CHARS` — a registry key, and a sort key's, own bound. */
export const MAX_SEGMENT_KEY_CHARS = 64;

/**
 * `schemas.segment._MAX_VALUE_CHARS`. An enum member, a wizard step or an RFC 3339 instant —
 * there is no free-text field in the registry and there cannot be one (`SEGMENT_REFUSALS`).
 */
export const MAX_SEGMENT_VALUE_CHARS = 64;
