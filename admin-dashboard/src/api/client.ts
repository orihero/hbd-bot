/**
 * The never-throw HTTP client. A much smaller sibling of admin-ui/src/api/client.ts, with
 * the same three load-bearing properties:
 *
 * **It never throws.** Every path out of `request()` returns an `ApiResult`. Offline, an
 * abort, a 500, a non-JSON body and a JSON body of the wrong shape all arrive as
 * `{ok: false, code, …}`. Callers branch on `ok`; nothing here needs a try/catch.
 *
 * **Every response is `safeParse`d.** Not `parse`. A mismatch is `SCHEMA_DRIFT` naming the
 * endpoint and the failing field paths — the server and this bundle disagree about the
 * contract, and an operator reading numbers nobody verified must be told so, loudly.
 *
 * **Same origin, always.** Paths are relative and `credentials: "include"` is set on every
 * request, so the `__Host-` session and CSRF cookies travel. There is no CORS in this
 * system by design.
 */

import type { z } from "zod";

import {
  CORRELATION_HEADER,
  CSRF_COOKIE_NAME,
  CSRF_HEADER_NAME,
  RETRY_AFTER_HEADER,
} from "./constants";

/** The error envelope every hbd admin failure comes back in — `render_envelope`'s shape. */
interface ErrorEnvelope {
  readonly code: string;
  readonly message: string;
  readonly correlationId: string;
  readonly details?: Record<string, unknown>;
}

/** One zod issue, flattened to something an error banner can print. */
export interface SchemaIssue {
  /** Dotted path into the response body; `""` at the root. */
  readonly path: string;
  readonly message: string;
}

export interface ApiOk<T> {
  readonly ok: true;
  readonly data: T;
}

export interface ApiFailure {
  readonly ok: false;
  /** A server code (`UNAUTHENTICATED`, `LOGIN_RATE_LIMITED`, …) or one of this client's own. */
  readonly code: string;
  /** Server messages are already redacted and capped at 300 chars. Safe to render verbatim. */
  readonly message: string;
  /** The HTTP status. `0` when the request never reached the server. */
  readonly status: number;
  /** The route template that failed, e.g. `POST /api/auth/login`. */
  readonly endpoint: string;
  /** From `X-Correlation-ID` or the envelope. `null` when there was no response. */
  readonly correlationId: string | null;
  /** Populated for `SCHEMA_DRIFT` only, and never empty when it is. */
  readonly issues: readonly SchemaIssue[] | null;
  /**
   * `error.details` verbatim, or `null` when the failure carried none.
   *
   * Not decoration: two refusals on this surface put their REMEDY here and nowhere else.
   * `STEP_UP_REQUIRED` carries `stepUpAction` and `subjectId` — the exact pair
   * `POST /api/auth/step-up` must be asked for, byte-identical to what the handler compared
   * — and `REVEAL_BUDGET_EXHAUSTED` carries which of the two ceilings refused and what is
   * left of the other. Dropping it would leave the SPA guessing at a scope, and a guessed
   * scope is a permanent silent 403. `unknown` values: this is a server-shaped bag, so read
   * it through the typed helpers in `reveal.ts` rather than by casting.
   */
  readonly details: Record<string, unknown> | null;
  /** Parsed from `Retry-After`, in seconds. Present on 429 and on the limiter's 503. */
  readonly retryAfterS: number | null;
}

export type ApiResult<T> = ApiOk<T> | ApiFailure;

/** Codes this client invents. None of them ever appears on the wire. */
export const CLIENT_ERROR_CODES = {
  schemaDrift: "SCHEMA_DRIFT",
  network: "NETWORK_ERROR",
  aborted: "REQUEST_ABORTED",
  malformedBody: "MALFORMED_ERROR_BODY",
} as const;

/**
 * Read the CSRF token the server set.
 *
 * `__Host-hbd_csrf` is the one cookie that is not HttpOnly, and that is the point: the SPA
 * echoes it in `X-CSRF-Token`, which a cross-site form cannot do. `null` when there is no
 * session — a non-GET sent without it is a 403 `CSRF_REJECTED`, which is the right answer.
 */
export function readCsrfToken(): string | null {
  if (typeof document === "undefined") return null;
  // `request()` calls this OUTSIDE the try/catch around `fetch`, so a throw here would be
  // the one crack in this module's never-throw contract — and there are two: `document.cookie`
  // raises SecurityError in a sandboxed frame, and `decodeURIComponent` raises URIError on a
  // cookie value carrying a stray `%`. Either way, no token is the documented clean 403.
  try {
    const prefix = `${CSRF_COOKIE_NAME}=`;
    for (const chunk of document.cookie.split("; ")) {
      if (chunk.startsWith(prefix)) return decodeURIComponent(chunk.slice(prefix.length));
    }
  } catch {
    return null;
  }
  return null;
}

export interface RequestOptions<T> {
  /** The route template a failure names, e.g. `GET /api/auth/me`. */
  readonly endpoint: string;
  /** The concrete path. Relative and same-origin, never an absolute URL. */
  readonly path: string;
  readonly method?: "GET" | "POST";
  readonly body?: unknown;
  /**
   * The schema a 2xx body must satisfy. Omit for a 204 / empty-body response.
   *
   * The input side is `unknown`, not `T`: a schema is fed a parsed JSON body and nothing
   * else, and pinning input to output would refuse every schema that normalises as it parses
   * — an omitted-or-null `meta.total` landing as `null`, say. `T` is then inferred from what
   * a caller gets BACK, which is the only side a caller can see.
   */
  readonly schema?: z.ZodType<T, z.ZodTypeDef, unknown>;
  readonly signal?: AbortSignal;
}

/**
 * One request. Returns, never throws.
 *
 * The order of the checks is deliberate: transport before status, status before shape. A
 * 500 whose body is not JSON must read as a 500, not as schema drift, or every incident
 * starts from the wrong hypothesis.
 */
export async function request<T>(options: RequestOptions<T>): Promise<ApiResult<T>> {
  const { endpoint, path, method = "GET", body, schema, signal } = options;

  const headers: Record<string, string> = { Accept: "application/json" };
  if (method !== "GET") {
    headers["Content-Type"] = "application/json";
    const csrf = readCsrfToken();
    // Sent only when we have one. An absent header is a clean 403; an empty one is a
    // decision the server should not have to make.
    if (csrf !== null) headers[CSRF_HEADER_NAME] = csrf;
  }

  let response: Response;
  try {
    response = await fetch(path, {
      method,
      headers,
      credentials: "include",
      // The API never redirects; following one would send the cookies somewhere nobody chose.
      redirect: "error",
      cache: "no-store",
      ...(body === undefined ? {} : { body: JSON.stringify(body) }),
      ...(signal === undefined ? {} : { signal }),
    });
  } catch (error: unknown) {
    const isAbort = error instanceof DOMException && error.name === "AbortError";
    return {
      ok: false,
      code: isAbort ? CLIENT_ERROR_CODES.aborted : CLIENT_ERROR_CODES.network,
      message: isAbort
        ? `${endpoint} was cancelled.`
        : `${endpoint} could not be reached. The panel is not talking to its API.`,
      status: 0,
      endpoint,
      correlationId: null,
      issues: null,
      details: null,
      retryAfterS: null,
    };
  }

  const correlationId = response.headers.get(CORRELATION_HEADER);
  const retryAfterS = parseRetryAfter(response.headers.get(RETRY_AFTER_HEADER));

  if (!response.ok) {
    return await errorFailure(response, endpoint, correlationId, retryAfterS);
  }

  // 204, and the probes' empty 200. Nothing to parse; nothing that could be parsed.
  if (schema === undefined) {
    return { ok: true, data: undefined as T };
  }

  let payload: unknown;
  try {
    payload = await response.json();
  } catch {
    return {
      ok: false,
      code: CLIENT_ERROR_CODES.malformedBody,
      message: `${endpoint} answered ${String(response.status)} with a body that is not JSON.`,
      status: response.status,
      endpoint,
      correlationId,
      issues: null,
      details: null,
      retryAfterS,
    };
  }

  const parsed = schema.safeParse(payload);
  if (parsed.success) return { ok: true, data: parsed.data };

  const issues: SchemaIssue[] = parsed.error.issues.map((issue) => ({
    path: issue.path.join("."),
    message: issue.message,
  }));
  const first = issues[0];
  return {
    ok: false,
    code: CLIENT_ERROR_CODES.schemaDrift,
    message:
      `${endpoint} returned a body this build does not understand: ` +
      `${first === undefined ? "the response body" : `\`${first.path || "(root)"}\``} — ` +
      (first?.message ?? "no issue reported") +
      (issues.length > 1 ? ` (and ${String(issues.length - 1)} more)` : ""),
    status: response.status,
    endpoint,
    correlationId,
    issues,
    details: null,
    retryAfterS,
  };
}

/**
 * A non-2xx. Every failure the API produces — 404, 405 (rendered `CONFLICT`), 422, 500 —
 * comes back in the envelope, so the envelope is tried first and the status table is only
 * the fallback for something that never reached a handler (a proxy's own 502 page, say).
 */
async function errorFailure(
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

  const envelope = readEnvelope(payload);
  if (envelope !== null) {
    return {
      ok: false,
      code: envelope.code,
      message: envelope.message,
      status: response.status,
      endpoint,
      // The envelope's own id is authoritative; the header should be identical.
      correlationId: envelope.correlationId || correlationId,
      issues: null,
      details: envelope.details ?? null,
      retryAfterS,
    };
  }

  return {
    ok: false,
    code: codeForStatus(response.status),
    message: `${endpoint} failed with HTTP ${String(response.status)}.`,
    status: response.status,
    endpoint,
    correlationId,
    issues: null,
    details: null,
    retryAfterS,
  };
}

/**
 * `{error: {code, message, correlationId, details?}}`, hand-read rather than zod-parsed: a
 * malformed error body must not turn into a second, different error about the error.
 */
function readEnvelope(payload: unknown): ErrorEnvelope | null {
  if (typeof payload !== "object" || payload === null) return null;
  const error: unknown = (payload as Record<string, unknown>)["error"];
  if (typeof error !== "object" || error === null) return null;
  const fields = error as Record<string, unknown>;
  const { code, message, correlationId, details } = fields;
  if (typeof code !== "string" || typeof message !== "string") return null;
  return {
    code,
    message,
    correlationId: typeof correlationId === "string" ? correlationId : "",
    ...(typeof details === "object" && details !== null
      ? { details: details as Record<string, unknown> }
      : {}),
  };
}

/**
 * Only for a body that never went through `render_envelope`. Mirrors the admin API's
 * Starlette routing table, including the one that surprises people: **405 is `CONFLICT`**.
 */
function codeForStatus(status: number): string {
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

/** Seconds as a decimal string. The HTTP-date form is not one the admin API emits. */
function parseRetryAfter(header: string | null): number | null {
  if (header === null) return null;
  const seconds = Number(header);
  return Number.isFinite(seconds) && seconds >= 0 ? seconds : null;
}
