/**
 * The never-throw HTTP client — §11.1's frontend twin of `run_guarded`.
 *
 * Three properties, and every one of them is load-bearing:
 *
 * **It never throws.** Every path out of `request()` returns an `ApiResult`. A network
 * failure, an aborted request, a 500, a body that is not JSON and a body that is JSON but
 * the wrong shape all arrive as `{ok: false, …}` with a code. A caller that wants an
 * exception opts in at the TanStack Query boundary via `unwrap` (errors.ts) — that is the
 * one place, and it is explicit.
 *
 * **Every response is `safeParse`d.** Not `parse`. A parse failure is not a crash and not a
 * silently-empty table: it is a `SCHEMA_DRIFT` failure naming the endpoint and the failing
 * field path, rendered as a loud banner. This mirrors the repo's decision to treat a
 * `pydantic.ValidationError` on a stored row as a deliberately loud data-integrity bug
 * rather than as something to route around. If the shape the server sends and the shape this
 * bundle expects have diverged, the operator is being shown numbers nobody has verified, and
 * that must be visible.
 *
 * **Same origin, always.** Paths are relative — `/api/…`, never an absolute URL. There is no
 * CORS in this system by design (§11.1): it lets the CSP be `default-src 'self'` and lets an
 * `<audio src>` carry the session cookie as a same-site subresource with no token in the
 * URL. `credentials: "include"` is set on every request so the `__Host-` cookies travel.
 */

import type { z } from "zod";

import {
  API_PREFIX,
  CORRELATION_HEADER,
  CSRF_COOKIE_NAME,
  CSRF_HEADER_NAME,
  RETRY_AFTER_HEADER,
} from "./constants";
import {
  apiErrorEnvelopeSchema,
  failure,
  ok,
  type ApiErrorCode,
  type ApiFailure,
  type ApiResult,
  type SchemaIssue,
} from "./errors";

/* -------------------------------------------------------------------------- */
/* Query strings                                                               */
/* -------------------------------------------------------------------------- */

/**
 * One query-parameter value. `null` and `undefined` are both OMITTED — the API's absent-vs-
 * present distinction is what drives its defaults, and sending `?state=` is not the same as
 * sending nothing (it is a 422).
 */
export type QueryValue = string | number | boolean | null | undefined;

/** A parameter map. An array value REPEATS the parameter, which is how the API spells OR. */
export type QueryParams = Readonly<Record<string, QueryValue | readonly QueryValue[]>>;

/**
 * Serialise a parameter map.
 *
 * Repeated parameters are how `?state=failed&state=cancelled` means "failed OR cancelled".
 * Booleans go out as `"true"`/`"false"` — FastAPI accepts both those and `1`/`0`, and the
 * spelled-out form is what shows up legibly in a URL an operator pastes into Slack (§11.1).
 */
export function buildQueryString(params: QueryParams | undefined): string {
  if (!params) return "";
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (Array.isArray(value)) {
      for (const item of value as readonly QueryValue[]) appendParam(search, key, item);
    } else {
      appendParam(search, key, value as QueryValue);
    }
  }
  const rendered = search.toString();
  return rendered === "" ? "" : `?${rendered}`;
}

function appendParam(search: URLSearchParams, key: string, value: QueryValue): void {
  if (value === null || value === undefined) return;
  search.append(key, String(value));
}

/* -------------------------------------------------------------------------- */
/* Cookies                                                                     */
/* -------------------------------------------------------------------------- */

/**
 * Read the CSRF token the server set.
 *
 * `__Host-bayram_csrf` is the ONE cookie that is not HttpOnly, and that is the whole point: the
 * SPA reads it and echoes it in `X-CSRF-Token`, which a cross-site form cannot do. The
 * server compares the header against the token STORED on the session row — not against the
 * cookie — so an attacker who can write a cookie for the registrable domain still fails.
 *
 * `null` when there is no session. A non-GET sent without it will be a 403 `CSRF_REJECTED`,
 * which is the correct answer.
 */
export function readCsrfToken(): string | null {
  if (typeof document === "undefined") return null;
  const prefix = `${CSRF_COOKIE_NAME}=`;
  for (const chunk of document.cookie.split("; ")) {
    if (chunk.startsWith(prefix)) return decodeURIComponent(chunk.slice(prefix.length));
  }
  return null;
}

/* -------------------------------------------------------------------------- */
/* The request                                                                 */
/* -------------------------------------------------------------------------- */

export interface RequestOptions<T> {
  /** The route TEMPLATE, e.g. `/api/orders/{order_id}` — what a failure names, and what
   *  groups two failures on the same endpoint with different ids. */
  readonly endpoint: string;
  /** The concrete path, e.g. `/api/orders/3f2b…`. Relative. Never an absolute URL. */
  readonly path: string;
  readonly method?: "GET" | "POST" | undefined;
  readonly query?: QueryParams | undefined;
  readonly body?: unknown;
  /** The schema the 200 body must satisfy. Omit for a 204 / empty-body response. */
  readonly schema?: z.ZodType<T> | undefined;
  readonly signal?: AbortSignal | undefined;
}

/**
 * One request. Returns, never throws.
 *
 * The order of the checks below is deliberate: transport before status, status before
 * shape. A 500 whose body is not JSON must read as a 500, not as schema drift, or every
 * incident starts with the wrong hypothesis.
 */
export async function request<T>(options: RequestOptions<T>): Promise<ApiResult<T>> {
  const { endpoint, path, method = "GET", query, body, schema, signal } = options;
  const url = `${path}${buildQueryString(query)}`;

  const headers: Record<string, string> = { Accept: "application/json" };
  if (method !== "GET") {
    headers["Content-Type"] = "application/json";
    const csrf = readCsrfToken();
    // Sent only when we have one. An absent header is a clean 403 CSRF_REJECTED; an empty
    // one would be a header the server has to decide about, and that is a decision it
    // should not have to make.
    if (csrf !== null) headers[CSRF_HEADER_NAME] = csrf;
  }

  let response: Response;
  try {
    response = await fetch(url, {
      method,
      headers,
      // The `__Host-` session and CSRF cookies. Same origin, so this is same-site.
      credentials: "include",
      // The server never redirects an API call; following one would send the cookies
      // somewhere nobody chose.
      redirect: "error",
      cache: "no-store",
      ...(body === undefined ? {} : { body: JSON.stringify(body) }),
      ...(signal ? { signal } : {}),
    });
  } catch (error: unknown) {
    return transportFailure(endpoint, error);
  }

  const correlationId = response.headers.get(CORRELATION_HEADER);
  const retryAfterS = parseRetryAfter(response.headers.get(RETRY_AFTER_HEADER));

  if (!response.ok) {
    return await errorFailure(response, endpoint, correlationId, retryAfterS);
  }

  // 204, and `/healthz`'s empty 200. Nothing to parse; nothing that COULD be parsed.
  if (schema === undefined) {
    return ok(undefined as T);
  }

  let payload: unknown;
  try {
    payload = await response.json();
  } catch (error: unknown) {
    return failure({
      code: "MALFORMED_ERROR_BODY",
      message: `${endpoint} answered ${String(response.status)} with a body that is not JSON.`,
      status: response.status,
      endpoint,
      correlationId,
      retryAfterS,
      details: { cause: describe(error) },
    });
  }

  const parsed = schema.safeParse(payload);
  if (!parsed.success) {
    return schemaDrift(endpoint, response.status, correlationId, parsed.error);
  }
  return ok(parsed.data);
}

/* -------------------------------------------------------------------------- */
/* The four ways a request fails                                               */
/* -------------------------------------------------------------------------- */

/**
 * The loud one. The request succeeded and the body is the wrong shape — this bundle and the
 * server disagree about the contract.
 *
 * `issues` carries the dotted field path of every mismatch, because "the response was
 * invalid" sends nobody anywhere and "items.3.isRetryable: expected boolean, received
 * string" sends them straight to the serializer.
 */
function schemaDrift(
  endpoint: string,
  status: number,
  correlationId: string | null,
  error: z.ZodError,
): ApiFailure {
  const issues: SchemaIssue[] = error.issues.map((issue) => ({
    path: issue.path.join("."),
    message: issue.message,
  }));
  const first = issues[0];
  const where = first === undefined ? "the response body" : `\`${first.path || "(root)"}\``;
  return failure({
    code: "SCHEMA_DRIFT",
    message:
      `${endpoint} returned a body this build does not understand: ${where} — ` +
      (first?.message ?? "no issue reported") +
      (issues.length > 1 ? ` (and ${String(issues.length - 1)} more)` : ""),
    status,
    endpoint,
    correlationId,
    issues,
  });
}

/**
 * No response at all: offline, DNS, a TLS failure, or an abort.
 *
 * Exported for `stream.ts`, the one caller that cannot go through `request()` because it
 * needs a `Range` header on the way out and the response headers on the way back. It is
 * NOT re-exported from the barrel: a second copy of this mapping living in a component is
 * exactly how two failure taxonomies grow.
 */
export function transportFailure(endpoint: string, error: unknown): ApiFailure {
  const isAbort =
    error instanceof DOMException ? error.name === "AbortError" : describe(error) === "AbortError";
  return failure({
    code: isAbort ? "REQUEST_ABORTED" : "NETWORK_ERROR",
    message: isAbort
      ? `${endpoint} was cancelled.`
      : `${endpoint} could not be reached. The panel is not talking to its API.`,
    status: 0,
    endpoint,
    details: { cause: describe(error) },
  });
}

/**
 * A non-2xx. EVERY failure the API produces — 404, 405 (rendered `CONFLICT`), 422, 500 —
 * comes back in `render_envelope`'s shape, so the envelope is tried first and the status
 * mapping is only the fallback for something that never reached the handler (a proxy's own
 * 502 page, say).
 */
export async function errorFailure(
  response: Response,
  endpoint: string,
  correlationId: string | null,
  retryAfterS: number | null,
): Promise<ApiFailure> {
  let payload: unknown = null;
  try {
    payload = await response.json();
  } catch {
    payload = null;
  }

  const envelope = apiErrorEnvelopeSchema.safeParse(payload);
  if (envelope.success) {
    const { code, message, details } = envelope.data.error;
    return failure({
      code,
      message,
      status: response.status,
      endpoint,
      // The envelope's own id is authoritative; the header should be identical.
      correlationId: envelope.data.error.correlationId || correlationId,
      details: details ?? null,
      retryAfterS,
    });
  }

  return failure({
    code: codeForStatus(response.status),
    message: `${endpoint} failed with HTTP ${String(response.status)}.`,
    status: response.status,
    endpoint,
    correlationId,
    retryAfterS,
  });
}

/**
 * Only for a body that never went through `render_envelope`. The mapping mirrors
 * `bayram/admin/errors.py`'s Starlette routing table, including the one that surprises people:
 * **405 is `CONFLICT`**, not a method error of its own.
 */
function codeForStatus(status: number): ApiErrorCode {
  switch (status) {
    case 401:
      return "UNAUTHENTICATED";
    case 403:
      return "FORBIDDEN";
    case 404:
      return "NOT_FOUND";
    case 405:
      return "CONFLICT";
    case 415:
      return "UNSUPPORTED_MEDIA_TYPE";
    case 422:
      return "INVALID_INPUT";
    case 429:
      return "RATE_LIMITED";
    case 503:
      return "SERVICE_UNAVAILABLE";
    default:
      return status >= 500 ? "INTERNAL_ERROR" : "UNKNOWN";
  }
}

/** `Retry-After` is seconds as a decimal string on this API — never an HTTP-date.
 *  Exported alongside `errorFailure` for `stream.ts`; not part of the barrel. */
export function parseRetryAfter(header: string | null): number | null {
  if (header === null) return null;
  const seconds = Number(header);
  return Number.isFinite(seconds) && seconds >= 0 ? seconds : null;
}

function describe(error: unknown): string {
  if (error instanceof Error) return error.name;
  return typeof error === "string" ? error : "unknown";
}

/* -------------------------------------------------------------------------- */
/* Sugar for the endpoint layer                                                */
/* -------------------------------------------------------------------------- */

export interface CallOptions {
  readonly signal?: AbortSignal | undefined;
}

/** A GET whose body is parsed against `schema`. */
export function get<T>(
  endpoint: string,
  path: string,
  schema: z.ZodType<T>,
  query?: QueryParams,
  options?: CallOptions,
): Promise<ApiResult<T>> {
  return request<T>({
    endpoint,
    path,
    schema,
    ...(query === undefined ? {} : { query }),
    ...(options?.signal ? { signal: options.signal } : {}),
  });
}

/** A POST with a JSON body. Carries `X-CSRF-Token`; the browser supplies `Origin`. */
export function post<T>(
  endpoint: string,
  path: string,
  schema: z.ZodType<T>,
  body: unknown,
  options?: CallOptions,
): Promise<ApiResult<T>> {
  return request<T>({
    endpoint,
    path,
    method: "POST",
    body,
    schema,
    ...(options?.signal ? { signal: options.signal } : {}),
  });
}

/** A POST that answers 204 with no body — `/api/auth/logout` is the only one. */
export function postNoContent(
  endpoint: string,
  path: string,
  body: unknown,
  options?: CallOptions,
): Promise<ApiResult<void>> {
  return request<void>({
    endpoint,
    path,
    method: "POST",
    body,
    ...(options?.signal ? { signal: options.signal } : {}),
  });
}

/** Join `/api` to a sub-path. Kept here so no caller hard-codes the prefix. */
export function apiPath(suffix: string): string {
  return `${API_PREFIX}${suffix}`;
}
