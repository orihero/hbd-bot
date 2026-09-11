/**
 * Keyset pagination, and the query-string rules every filtered list on this API obeys.
 *
 * **There is no page number and there is no offset.** `bayram.db.admin.page` walks
 * `(created_at, id)` and hands back an opaque cursor; a caller that invented `?page=3` would
 * get a 422 for an unknown parameter's sake at best, and at worst a stable-looking URL that
 * means something different every time a row is written. So the only way forward is
 * `meta.nextCursor`, and the only way back is the cursor the caller kept.
 *
 * **`total` and `isTotalExact` travel as a pair or not at all.** `bounded_total` stops
 * counting at `TOTAL_COUNT_CAP`, so a bare `10000` is a ceiling wearing a measurement's
 * clothes. Both are `null` unless the request asked `withTotal=true`; render the pair
 * (`"10,000+"`) or neither half.
 *
 * **An absent filter is OMITTED, never sent empty.** FastAPI's absent-vs-present distinction
 * is what selects a handler's default, and an empty value is not "no value": `?from=` is a
 * 422 (an empty string is not a datetime), `?isBlocked=` likewise, and `?q=` would be a
 * substring filter matching everything rather than the unfiltered list the operator asked
 * for. `appendParam` and `appendEach` below are the only writers in this package, so that
 * rule is enforced in one place rather than remembered at eleven call sites.
 */

import { z } from "zod";

/** `bayram.db.admin.page.MIN_PAGE_LIMIT` / `MAX_PAGE_LIMIT` / `DEFAULT_PAGE_LIMIT`. */
export const MIN_PAGE_LIMIT = 1;
export const MAX_PAGE_LIMIT = 200;
export const DEFAULT_PAGE_LIMIT = 50;

/**
 * `bayram.db.admin.page.TOTAL_COUNT_CAP`. A `total` equal to this with `isTotalExact: false` is
 * "at least this many", and the two are the only honest way to say so.
 */
export const TOTAL_COUNT_CAP = 10_000;

/**
 * `?limit=&cursor=`. Both optional: the server defaults the limit and treats a missing
 * cursor as "first page".
 *
 * Out-of-range limits are REFUSED, not clamped (`page_request`), so do not silently repair
 * one here either — a client asking for 5,000 rows has a bug that a clamp would hide until
 * it surfaced as a timeout.
 */
export interface PageRequest {
  readonly limit?: number;
  readonly cursor?: string | null;
}

/**
 * A page of a list that also has a `withTotal` switch and no other filters — the two
 * per-person sub-lists. It rides on the page request rather than on a filter object because
 * those routes have no filters to hang it off.
 *
 * It is off by default: the count is a second query, `bounded_total` stops at
 * `TOTAL_COUNT_CAP`, and no screen needs it to render the first page.
 */
export interface CountedPageRequest extends PageRequest {
  readonly withTotal?: boolean;
}

/** The first page, spelled out — clearer at a call site than a bare `{}`. */
export const FIRST_PAGE: PageRequest = {};

/**
 * `meta` on every list response.
 *
 * All three fields are nullable AND may be absent (the server omits `total`/`isTotalExact`
 * for a request that did not ask), so each defaults to `null`: a screen branching on
 * `undefined` in one build and `null` in the next is a bug waiting for a FastAPI upgrade.
 * `nextCursor` is `null` at the end of the walk and never `""`.
 */
export const pageMetaSchema = z.object({
  nextCursor: z.string().nullable().default(null),
  total: z.number().int().nullable().default(null),
  isTotalExact: z.boolean().nullable().default(null),
});
export type PageMeta = z.infer<typeof pageMetaSchema>;

/** Anything with a `meta` — `UsersPage`, `OrdersPage`, `CreditLedgerPage`, `AttemptsPage`. */
export interface PagedResponse {
  readonly meta: PageMeta;
}

/**
 * The cursor for the next request, or `null` at the end.
 *
 * Read it through this rather than off `meta` directly: it is the one place that knows an
 * empty string is not a cursor, and a `?cursor=` the server did not mint is a 422.
 */
export function nextCursorOf(page: PagedResponse): string | null {
  const cursor = page.meta.nextCursor;
  return cursor === null || cursor === "" ? null : cursor;
}

/** Whether there is another page to fetch. The only correct "load more" predicate. */
export function hasNextPage(page: PagedResponse): boolean {
  return nextCursorOf(page) !== null;
}

/**
 * The page after this one, ready to hand back to a fetcher. `null` at the end of the walk.
 * Everything else about the request (the limit, `withTotal`) is carried through unchanged.
 */
export function nextPageRequest<T extends PageRequest>(page: PagedResponse, request: T): T | null {
  const cursor = nextCursorOf(page);
  return cursor === null ? null : { ...request, cursor };
}

/**
 * One query parameter, or nothing.
 *
 * `undefined`, `null` and `""` all mean "the operator did not filter on this" and all omit
 * the parameter. A boolean is written `true`/`false` because these filters are TRI-STATE —
 * absent, true and false are three different questions (`hasBalance=false` deliberately
 * includes the account with no `credit_accounts` row at all), so `false` must be sent when
 * it was chosen.
 */
export function appendParam(
  params: URLSearchParams,
  name: string,
  value: string | number | boolean | null | undefined,
): void {
  if (value === undefined || value === null) return;
  if (typeof value === "string") {
    const trimmed = value.trim();
    if (trimmed === "") return;
    params.append(name, trimmed);
    return;
  }
  params.append(name, String(value));
}

/**
 * A REPEATED parameter — `uiLanguage=ru&uiLanguage=en`, `kind=song&kind=lyrics`.
 *
 * §6.1: repeats are OR within the field and AND across fields. An empty selection omits the
 * parameter entirely, which is "do not filter" — not "match nothing".
 */
export function appendEach(
  params: URLSearchParams,
  name: string,
  values: readonly string[] | null | undefined,
): void {
  if (values === undefined || values === null) return;
  for (const value of values) appendParam(params, name, value);
}

/** `limit` and `cursor`, on the same omit-when-absent rule as every filter. */
export function appendPage(params: URLSearchParams, page: PageRequest): void {
  appendParam(params, "limit", page.limit);
  appendParam(params, "cursor", page.cursor);
}

/**
 * `withTotal`, `limit` and `cursor`.
 *
 * `withTotal` is sent only when it is asked for: the server's default is `false`, so
 * `withTotal=false` would be a second spelling of the same request — two react-query keys
 * and two different lines in the request log for one question.
 */
export function appendCountedPage(params: URLSearchParams, page: CountedPageRequest): void {
  if (page.withTotal === true) params.append("withTotal", "true");
  appendPage(params, page);
}

/**
 * `"?a=1&b=2"`, or `""` when nothing was set.
 *
 * The bare `?` is worth avoiding: it makes two identical requests two different react-query
 * keys and two different lines in the server's request log.
 */
export function queryOf(params: URLSearchParams): string {
  const query = params.toString();
  return query === "" ? "" : `?${query}`;
}
