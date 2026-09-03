/**
 * The error half of the never-throw client — §11.1's `ApiResult`, and the two server
 * taxonomies that fill its `code`.
 *
 * `code` carries the UNION of two disjoint enums (a server test asserts
 * `set(AdminErrorCode) & set(ErrorCode) == set()`), plus a small set of codes that are the
 * CLIENT's own and never reach the wire.
 *
 * Parsing rule, and it matters: `code` is parsed as `z.string()`, not as `z.enum`. A future
 * server adding a code the bundle has never heard of must produce a rendered error, not a
 * SCHEMA_DRIFT banner about the error. The unions below exist for BRANCHING and for
 * exhaustive `switch`es on the codes we do handle — never as a parse gate.
 */

import { z } from "zod";

import { MAX_MESSAGE_CHARS } from "./constants";

/* -------------------------------------------------------------------------- */
/* The two server taxonomies                                                   */
/* -------------------------------------------------------------------------- */

/**
 * `hbd.admin.errors.AdminErrorCode` — 17 members, value == name.
 *
 * `REAUTH_RATE_LIMITED`, `SERVICE_UNAVAILABLE` and `INTERNAL_ERROR` are absent from §6.2's
 * snippet in the plan and present in the code; the code is authoritative (contract D4).
 * `REAUTH_RATE_LIMITED` is deliberately distinct from `LOGIN_RATE_LIMITED` because only it
 * has an operator remedy: sign in again to start a fresh window.
 */
export const ADMIN_ERROR_CODES = [
  "UNAUTHENTICATED",
  "FORBIDDEN",
  "STEP_UP_REQUIRED",
  "CSRF_REJECTED",
  "ORIGIN_REJECTED",
  "CONFLICT",
  "PRECONDITION_FAILED",
  "CAPABILITY_DISABLED",
  "UNSUPPORTED_MEDIA_TYPE",
  "RANGE_NOT_SATISFIABLE",
  "CONFIG_FIELD_NOT_EDITABLE",
  "LOGIN_RATE_LIMITED",
  "REAUTH_RATE_LIMITED",
  "REVEAL_BUDGET_EXHAUSTED",
  "INTERNAL_ERROR",
  "SERVICE_UNAVAILABLE",
] as const;
export type AdminErrorCode = (typeof ADMIN_ERROR_CODES)[number];

/**
 * `hbd.errors.ErrorCode` — the pipeline taxonomy. The whole enum can appear in `code`; only
 * ten of them carry a status mapping and anything else surfaces as a 500.
 */
export const PIPELINE_ERROR_CODES = [
  "NOT_FOUND",
  "INVALID_INPUT",
  "CONFIG_INVALID",
  "CONTENT_REJECTED",
  "RATE_LIMITED",
  "QUOTA_EXHAUSTED",
  "UPSTREAM_TIMEOUT",
  "UPSTREAM_5XX",
  "UPSTREAM_MALFORMED",
  "STORAGE_FAILED",
  "ARTIST_NAME_IN_STYLE",
  "PARSE_FAILED",
  "NAME_UNVERIFIABLE",
  "AUDIO_FAILED",
  "DELIVERY_FAILED",
  "PAYMENT_FAILED",
  "CREDITS_EXHAUSTED",
  "TOO_MANY_IN_FLIGHT",
  "ACCOUNT_BLOCKED",
  "UNKNOWN",
] as const;
export type PipelineErrorCode = (typeof PIPELINE_ERROR_CODES)[number];

/**
 * Codes this client invents. None of them ever appears on the wire, and each names a
 * different failure of the transport rather than of the request.
 *
 * `SCHEMA_DRIFT` is the loud one (§11.1): the request succeeded, the server answered 200,
 * and the body did not match the schema this bundle was built against. That is a
 * data-integrity bug — the frontend twin of the repo's decision to treat a
 * `pydantic.ValidationError` on a stored row as deliberately loud — and it must be rendered
 * as a banner naming the endpoint and the failing field path, never swallowed into an empty
 * table.
 */
export const CLIENT_ERROR_CODES = [
  "SCHEMA_DRIFT",
  "NETWORK_ERROR",
  "REQUEST_ABORTED",
  "MALFORMED_ERROR_BODY",
] as const;
export type ClientErrorCode = (typeof CLIENT_ERROR_CODES)[number];

/**
 * The `code` on any failure.
 *
 * The `(string & {})` arm is load-bearing: it keeps editor completion for the known members
 * while still accepting a code no build has seen. Do not narrow it to the unions.
 */
export type ApiErrorCode =
  | AdminErrorCode
  | PipelineErrorCode
  | ClientErrorCode
  | (string & {});

const KNOWN_CODES: ReadonlySet<string> = new Set<string>([
  ...ADMIN_ERROR_CODES,
  ...PIPELINE_ERROR_CODES,
  ...CLIENT_ERROR_CODES,
]);

/** Whether this build knows how to talk about `code`, for a "we have not seen this" hint. */
export function isKnownErrorCode(code: string): boolean {
  return KNOWN_CODES.has(code);
}

export function isAdminErrorCode(code: string): code is AdminErrorCode {
  return (ADMIN_ERROR_CODES as readonly string[]).includes(code);
}

export function isPipelineErrorCode(code: string): code is PipelineErrorCode {
  return (PIPELINE_ERROR_CODES as readonly string[]).includes(code);
}

export function isClientErrorCode(code: string): code is ClientErrorCode {
  return (CLIENT_ERROR_CODES as readonly string[]).includes(code);
}

/** The codes that mean "your session is over" — the only ones that justify a redirect. */
export const SESSION_ENDED_CODES: readonly ApiErrorCode[] = ["UNAUTHENTICATED"];

/**
 * The codes a retry could plausibly fix. `FORBIDDEN` is deliberately absent: a role does not
 * change while a screen is open, and retrying a denial writes a second audit row.
 */
export const RETRYABLE_ERROR_CODES: readonly ApiErrorCode[] = [
  "NETWORK_ERROR",
  "SERVICE_UNAVAILABLE",
  "UPSTREAM_TIMEOUT",
  "UPSTREAM_5XX",
  "STORAGE_FAILED",
  "INTERNAL_ERROR",
];

/* -------------------------------------------------------------------------- */
/* The wire envelope                                                           */
/* -------------------------------------------------------------------------- */

/**
 * `hbd/admin/errors.py:render_envelope`. EVERY failure comes back in this shape — 404, 405
 * (rendered as `CONFLICT`), 422 and 500 included.
 *
 * `details` is the ONE key in the whole API that is genuinely absent rather than `null` when
 * there is nothing to say (`if details: body["details"] = …`).
 *
 * The generated OpenAPI advertises `HTTPValidationError` (`{detail: [{loc,msg,type}]}`) for
 * 422 on every parameterised endpoint. That shape NEVER reaches the wire — `_handle_validation`
 * renders this envelope with `code: "INVALID_INPUT"` and `details.fields`. Do not codegen
 * from the OpenAPI 422 responses (contract D5).
 */
export const apiErrorEnvelopeSchema = z.object({
  error: z.object({
    code: z.string(),
    message: z.string().max(MAX_MESSAGE_CHARS),
    correlationId: z.string(),
    details: z.record(z.string(), z.unknown()).optional(),
  }),
});
export type ApiErrorEnvelope = z.infer<typeof apiErrorEnvelopeSchema>;

/** `details.fields` on a 422 — dotted pydantic locations, e.g. `"body.newPassword"`. Values
 *  are NEVER echoed, so this is safe to render in full. */
export function validationFields(details: Readonly<Record<string, unknown>> | null): string[] {
  const fields = details?.["fields"];
  if (!Array.isArray(fields)) return [];
  return fields.filter((field): field is string => typeof field === "string");
}

/** `details.permission` on a 403 — the `Permission` value the role's cell is missing. */
export function refusedPermission(details: Readonly<Record<string, unknown>> | null): string | null {
  const permission = details?.["permission"];
  return typeof permission === "string" ? permission : null;
}

/** `details.scope` on a 429/503 from the limiter — a `RateLimitScope` value or `""`. */
export function limitedScope(details: Readonly<Record<string, unknown>> | null): string | null {
  const scope = details?.["scope"];
  return typeof scope === "string" ? scope : null;
}

/* -------------------------------------------------------------------------- */
/* ApiResult                                                                   */
/* -------------------------------------------------------------------------- */

/** One zod issue, flattened to something an error banner can print. */
export interface SchemaIssue {
  /** Dotted path into the response body, e.g. `"items.3.isRetryable"`. `""` at the root. */
  readonly path: string;
  readonly message: string;
}

export interface ApiOk<T> {
  readonly ok: true;
  readonly data: T;
}

export interface ApiFailure {
  readonly ok: false;
  readonly code: ApiErrorCode;
  /** Already redacted and capped at 300 chars by the server. Safe to render verbatim. */
  readonly message: string;
  /** The HTTP status. `0` when the request never reached the server. */
  readonly status: number;
  /**
   * From `X-Correlation-ID`, or from the envelope's `correlationId`. `null` only when the
   * request never got a response. §11.4's Error state renders this with a copy button — it
   * is the string that ties the operator's screen to a log line.
   */
  readonly correlationId: string | null;
  /** The endpoint that failed, as a route template — e.g. `GET /api/orders/{order_id}`. */
  readonly endpoint: string;
  /** Absent-when-empty on the wire; `null` here. */
  readonly details: Readonly<Record<string, unknown>> | null;
  /** Populated for `SCHEMA_DRIFT` only, and never empty when it is. */
  readonly issues: readonly SchemaIssue[] | null;
  /** Parsed from `Retry-After` (seconds). Present on every 429 and on the limiter's 503. */
  readonly retryAfterS: number | null;
}

/**
 * §11.1, verbatim in spirit: the client never throws, and every caller branches on `ok`.
 * The failure arm carries more than §11.1's four keys — the extra fields are what §11.4's
 * Error state needs to render a code, a copyable correlation id and a schema-drift path.
 */
export type ApiResult<T> = ApiOk<T> | ApiFailure;

export function ok<T>(data: T): ApiOk<T> {
  return { ok: true, data };
}

/** Build a failure. Every field is explicit; nothing here defaults silently. */
export function failure(init: {
  code: ApiErrorCode;
  message: string;
  status: number;
  endpoint: string;
  correlationId?: string | null;
  details?: Readonly<Record<string, unknown>> | null;
  issues?: readonly SchemaIssue[] | null;
  retryAfterS?: number | null;
}): ApiFailure {
  return {
    ok: false,
    code: init.code,
    message: init.message,
    status: init.status,
    endpoint: init.endpoint,
    correlationId: init.correlationId ?? null,
    details: init.details ?? null,
    issues: init.issues ?? null,
    retryAfterS: init.retryAfterS ?? null,
  };
}

/** Narrowing helpers, so a screen never has to remember which arm carries `data`. */
export function isOk<T>(result: ApiResult<T>): result is ApiOk<T> {
  return result.ok;
}

export function isFailure<T>(result: ApiResult<T>): result is ApiFailure {
  return !result.ok;
}

/**
 * A `SCHEMA_DRIFT` failure is the one the UI must never quietly absorb. Screens use this to
 * choose the loud banner over the ordinary inline error state.
 */
export function isSchemaDrift(result: ApiResult<unknown>): result is ApiFailure {
  return !result.ok && result.code === "SCHEMA_DRIFT";
}

/**
 * Throw a failure. Used ONLY at the TanStack Query boundary: Query's contract is that a
 * query function rejects on failure, and `useQuery` needs a rejection to populate
 * `error`/`isError` and to run its retry policy. The client itself still never throws —
 * this is the deliberate, single place a caller opts back into exceptions.
 */
export class ApiFailureError extends Error {
  readonly failure: ApiFailure;

  constructor(apiFailure: ApiFailure) {
    super(`${apiFailure.code}: ${apiFailure.message}`);
    this.name = "ApiFailureError";
    this.failure = apiFailure;
  }
}

export function isApiFailureError(error: unknown): error is ApiFailureError {
  return error instanceof ApiFailureError;
}

/** The failure behind a thrown query error, or `null` if something else threw. */
export function failureOf(error: unknown): ApiFailure | null {
  return isApiFailureError(error) ? error.failure : null;
}

/**
 * Unwrap for the query-function boundary: returns `data` or throws `ApiFailureError`.
 *
 * ```ts
 * queryFn: () => unwrap(getOrders(query, { signal }))
 * ```
 */
export function unwrap<T>(result: ApiResult<T>): T {
  if (result.ok) return result.data;
  throw new ApiFailureError(result);
}

/** The async form, so a query function is one expression. */
export async function unwrapAsync<T>(promise: Promise<ApiResult<T>>): Promise<T> {
  return unwrap(await promise);
}
