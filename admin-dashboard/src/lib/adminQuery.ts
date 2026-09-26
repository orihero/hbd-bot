/**
 * The query plumbing the record screens share: one error type, one retry policy, two option
 * bundles, and the key-shaping rules that keep a cache entry and a request URL in step.
 *
 * `features/dashboard/useDashboardData.ts` established these conventions for a page that
 * polls, and its `DashboardQueryError` stays where it is. This is the same reasoning for the
 * pages that do NOT poll — Users and Generations — extracted rather than copied twice,
 * because a `catch` in a screen that renders both lists cannot branch on two identical error
 * classes with different names.
 *
 * **Two spellings of one request must be one key.** `api/pagination.ts` omits `undefined`,
 * `null` and `""` from the query string and trims what it does send, so `{q: ""}` and `{}`
 * are one URL. If they were two keys they would be two fetches of the same page and two
 * entries to invalidate, and the second would go stale unnoticed. `filterKey` applies the
 * serialiser's rules to the key, and sorts repeated values, because `["ru","en"]` and
 * `["en","ru"]` are one question.
 */

import { keepPreviousData } from "@tanstack/react-query";

import { CLIENT_ERROR_CODES, type ApiFailure, type ApiResult, type SchemaIssue } from "@/api/client";
import type { CountedPageRequest, PageRequest } from "@/api/pagination";

/* -------------------------------------------------------------------------- */
/* The error a failed read or write becomes                                    */
/* -------------------------------------------------------------------------- */

/**
 * The one place these features opt back into exceptions.
 *
 * `api/client.ts` never throws — every failure is a resolved `ApiResult` — but TanStack Query
 * needs a REJECTION to populate `error`/`isError` and to run a retry policy at all. So the
 * query boundary, and only the query boundary, converts one into the other.
 *
 * The whole `ApiFailure` is carried because these screens have four different things to
 * render from it: `code` picks the copy (`STEP_UP_REQUIRED` is a password prompt,
 * `REVEAL_BUDGET_EXHAUSTED` is a named ceiling, `SCHEMA_DRIFT` is a banner), `status` decides
 * whether to send the operator to `/login`, `correlationId` is what goes in a bug report, and
 * `details` carries the REMEDY — `stepUpAction`/`subjectId`, or which budget refused. Read
 * `details` through the typed helpers in `api/reveal.ts`, never by casting.
 */
export class AdminQueryError extends Error {
  /** A server code (`UNAUTHENTICATED`, `STEP_UP_REQUIRED`, …) or one of the client's own. */
  readonly code: string;
  /** The HTTP status. `0` when the request never reached the server. */
  readonly status: number;
  /** The route template that failed, e.g. `POST /api/users/{telegramUserId}/block`. */
  readonly endpoint: string;
  readonly correlationId: string | null;
  /** Populated for `SCHEMA_DRIFT` only — the field paths this build did not understand. */
  readonly issues: readonly SchemaIssue[] | null;
  /** `error.details` verbatim. The remedy for a step-up or a budget refusal lives here. */
  readonly details: Record<string, unknown> | null;
  readonly retryAfterS: number | null;
  /** The failure verbatim, for the helpers that read a whole `ApiFailure`. */
  readonly failure: ApiFailure;

  constructor(failure: ApiFailure) {
    super(failure.message);
    this.name = "AdminQueryError";
    this.code = failure.code;
    this.status = failure.status;
    this.endpoint = failure.endpoint;
    this.correlationId = failure.correlationId;
    this.issues = failure.issues;
    this.details = failure.details;
    this.retryAfterS = failure.retryAfterS;
    this.failure = failure;
  }
}

export function isAdminQueryError(error: unknown): error is AdminQueryError {
  return error instanceof AdminQueryError;
}

/** The `ApiFailure` behind a rejection, for `stepUpTargetOf` and friends. `null` otherwise. */
export function failureOf(error: unknown): ApiFailure | null {
  return isAdminQueryError(error) ? error.failure : null;
}

/** `data` on success; an `AdminQueryError` rejection on failure. Used only in a query boundary. */
export async function unwrap<T>(promise: Promise<ApiResult<T>>): Promise<T> {
  const result = await promise;
  if (result.ok) return result.data;
  throw new AdminQueryError(result);
}

/* -------------------------------------------------------------------------- */
/* Retry policy                                                                */
/* -------------------------------------------------------------------------- */

/**
 * Statuses that will answer the same way however many times they are asked.
 *
 * **401** — the session is gone (and `CSRF_REJECTED` means the same thing by a different
 * door). Retrying cannot bring it back; the operator needs `/login`, and that only happens if
 * the failure surfaces on the first attempt.
 * **403** — a role refusal or a step-up refusal. Every attempt writes a `permission.denied`
 * audit row against someone who did nothing wrong, and three rows are not more informative
 * than one. A `STEP_UP_REQUIRED` needs a password, not another request.
 * **409** — someone else changed the row. The same bytes will lose the same race.
 * **422** — the filter or the body is wrong. A byte-identical retry gets a byte-identical
 * refusal, and on the write routes a 422 writes NO audit row, so retrying it is invisible.
 */
const TERMINAL_STATUSES: readonly number[] = [401, 403, 409, 422];

/** Two retries. There is no poll behind these lists, so this is the whole recovery budget. */
const MAX_RETRIES = 2;

export function shouldRetryRead(failureCount: number, error: unknown): boolean {
  if (failureCount >= MAX_RETRIES) return false;
  if (!isAdminQueryError(error)) return false;
  // The caller cancelled — a filter change superseding this page, or an unmount. Not a failure.
  if (error.code === CLIENT_ERROR_CODES.aborted) return false;
  // Server and bundle disagree about the contract. Re-reading the same bytes is not a fix.
  if (error.code === CLIENT_ERROR_CODES.schemaDrift) return false;
  if (TERMINAL_STATUSES.includes(error.status)) return false;
  // 0 is a transport failure — a flapped wifi, a proxy blip. Worth another go.
  if (error.status === 0) return true;
  // 5xx only. 429 falls through to `false`: retrying a rate limit is what caused it.
  return error.status >= 500;
}

const RETRY_BASE_MS = 1_000;
const RETRY_CAP_MS = 4_000;

export function retryBackoffMs(attemptIndex: number): number {
  return Math.min(RETRY_BASE_MS * 2 ** attemptIndex, RETRY_CAP_MS);
}

/* -------------------------------------------------------------------------- */
/* Cadence                                                                     */
/* -------------------------------------------------------------------------- */

/**
 * How long a page of records counts as fresh.
 *
 * Long enough that tabbing away and back twice in a few seconds is one question rather than
 * two, short enough that coming back to the tab after a coffee re-reads. It is a ceiling on
 * how often `refetchOnWindowFocus` can fire, not an interval.
 */
export const RECORD_STALE_TIME_MS = 10_000;

/**
 * Options every list read on these screens shares.
 *
 * **No timer.** `refetchInterval: false` is written out rather than left to the default,
 * because it is a decision: an operator reading a filtered ledger is not watching a dashboard,
 * and rows that reshuffle under a cursor mid-read are worse than rows a few seconds old. The
 * freshness signal is the operator LOOKING at the tab — `refetchOnWindowFocus` — plus
 * `refetchOnMount`, so opening the screen asks (subject to `RECORD_STALE_TIME_MS`).
 *
 * `keepPreviousData` is what makes a cursor page or a filter change swap rows instead of
 * blanking the table; the screen must read `isPlaceholderData` and DIM those rows, because
 * showing the previous filter's rows under the new chips at full contrast is the one failure
 * a table cannot recover from — nothing on screen looks wrong.
 */
export const LIST_READ = {
  refetchInterval: false,
  refetchIntervalInBackground: false,
  refetchOnWindowFocus: true,
  refetchOnMount: true,
  staleTime: RECORD_STALE_TIME_MS,
  placeholderData: keepPreviousData,
  retry: shouldRetryRead,
  retryDelay: retryBackoffMs,
} as const;

/**
 * Options for a read ABOUT ONE SUBJECT — a person, an attempt.
 *
 * Identical to `LIST_READ` but with `keepPreviousData` deliberately switched off. Keeping the
 * previous data across a subject change means the previous customer's masked identity sits
 * under the next customer's header for as long as the fetch takes; a dimmed row in a table is
 * honest, a dimmed IDENTITY is a misidentification. A panel that has not loaded shows a
 * skeleton instead.
 */
export const SUBJECT_READ = {
  refetchInterval: false,
  refetchIntervalInBackground: false,
  refetchOnWindowFocus: true,
  refetchOnMount: true,
  staleTime: RECORD_STALE_TIME_MS,
  placeholderData: (): undefined => undefined,
  retry: shouldRetryRead,
  retryDelay: retryBackoffMs,
} as const;

/**
 * Options every privileged write here shares.
 *
 * `retry: false`, and not because a retry would be unsafe — block and unblock are idempotent
 * upserts and a grant carries an idempotency key. It is because the failures these writes
 * actually hit are `STEP_UP_REQUIRED` (needs a password), `FORBIDDEN` (needs a different
 * role) and 422 (needs a different body): none is fixed by asking again, and each extra
 * attempt is another audit row. A retry of a §9.2 action is the operator's decision, taken
 * again, with the same `requestId`.
 */
export const PRIVILEGED_WRITE = {
  retry: false,
} as const;

/* -------------------------------------------------------------------------- */
/* Key shaping                                                                 */
/* -------------------------------------------------------------------------- */

/** What may appear in a filter key. Arrays are the repeated parameters (`uiLanguage`, `kind`). */
export type FilterKeyValue = string | number | boolean | readonly string[];

/** A canonical, hashable projection of a filter set. */
export type FilterKey = Readonly<Record<string, FilterKeyValue>>;

/** Deterministic and locale-independent — a key is compared, never read aloud. */
function compareText(left: string, right: string): number {
  if (left < right) return -1;
  return left > right ? 1 : 0;
}

/**
 * A filter set, reduced to exactly what will be on the wire.
 *
 * `undefined`, `null`, `""` and an empty array all mean "not filtered" and all drop out, for
 * the same reason `appendParam` omits them: an unfiltered request must be ONE cache entry
 * however the screen happened to spell it. Strings are trimmed because the serialiser trims.
 * Repeated values are sorted because their order is not part of the question.
 *
 * `false` is KEPT: every boolean here is tri-state, and `hasBalance=false` is a real filter
 * that deliberately includes the customer with no `credit_accounts` row.
 */
export function filterKey(
  entries: Readonly<Record<string, FilterKeyValue | null | undefined>>,
): FilterKey {
  const key: Record<string, FilterKeyValue> = {};
  for (const [name, value] of Object.entries(entries)) {
    if (value === undefined || value === null) continue;
    if (typeof value === "string") {
      const trimmed = value.trim();
      if (trimmed !== "") key[name] = trimmed;
      continue;
    }
    if (typeof value === "boolean" || typeof value === "number") {
      key[name] = value;
      continue;
    }
    if (value.length > 0) key[name] = [...value].sort(compareText);
  }
  return key;
}

/**
 * `withTotal`, as the key should see it: `true`, or absent.
 *
 * The server's default is `false`, so `withTotal=false` is not sent — and a key that recorded
 * it would make one request two cache entries.
 */
export function onlyWhenAsked(withTotal: boolean | undefined): true | undefined {
  return withTotal === true ? true : undefined;
}

/** The paging half of a key. */
export interface PageKey {
  readonly limit: number | null;
  readonly cursor: string | null;
}

export interface CountedPageKey extends PageKey {
  readonly withTotal: boolean;
}

/**
 * The cursor is IN the key, always. It is the only thing that distinguishes page two from
 * page one — there is no page number and no offset — so a key without it would serve page
 * one's rows for every cursor in the walk. `""` is not a cursor (`nextCursorOf`).
 */
export function pageKey(page: PageRequest): PageKey {
  const cursor = page.cursor;
  return {
    limit: page.limit ?? null,
    cursor: cursor === undefined || cursor === null || cursor === "" ? null : cursor,
  };
}

/** As `pageKey`, plus the count switch the two per-person sub-lists carry on their page. */
export function countedPageKey(page: CountedPageRequest): CountedPageKey {
  return { ...pageKey(page), withTotal: page.withTotal === true };
}

/* -------------------------------------------------------------------------- */
/* Subjects                                                                    */
/* -------------------------------------------------------------------------- */

/**
 * The id a disabled query never actually asks with.
 *
 * A detail hook takes `null` for "nothing selected" and sets `enabled` from it; this is how
 * the id reaches the fetcher afterwards without a non-null assertion. The throw is
 * unreachable while `enabled` and the argument are read from the same value.
 */
export function requireSubject<T>(subject: T | null): T {
  if (subject === null) throw new Error("A subject query ran with nothing selected.");
  return subject;
}
