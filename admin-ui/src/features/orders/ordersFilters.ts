/**
 * `/orders`' filter state: the URL, parsed.
 *
 * §11.1 — "URL search params (zod-parsed) for all filter state so an operator can paste 'the
 * failed orders I'm looking at' into Slack". There is no second copy of this state anywhere
 * in the feature; the address bar is the store, and `buildFilterChips` renders it back.
 *
 * ## The window is completed into a PAIR, and no longer because it has to be
 *
 * This used to be a refusal: `orders.py`'s `_window` 422'd on half a window ("from and to
 * are one window — give both bounds or neither"), so `completeWindow` existed to keep every
 * preset click off that error. `bayram/admin/window.py::resolve_window` no longer raises it —
 * a lone `from` is closed at the instant the request was served and a lone `to` leaves the
 * start genuinely absent — so half a window is now a question this API answers.
 *
 * `completeWindow` stays anyway, for the reason that outlived the 422: a pasted link has to
 * be REPRODUCIBLE. "Last 24 hours" resolved a week from now is a different set of orders; a
 * pair of fixed instants in the URL is the same set forever. Pinning the end at the click is
 * also what keeps a keyset walk honest — a `to` meaning "now" would widen the filter between
 * page one and page two.
 *
 * `toStateCountsQuery` still drops a half window rather than sending it, which is now a
 * SECOND copy of a rule the API layer has abandoned (see `windowParams` in `api/endpoints.ts`).
 * It is unreachable from the picker, which completes every range before it is written; it is
 * reachable from a hand-edited or pasted `?from=`-only URL, where it produces the failure
 * that helper was changed to stop — a filter chip naming a window over an unfiltered page.
 * Left as-is here only because changing it is a behaviour change to this screen rather than
 * a doc fix; it wants the same treatment `windowParams` got.
 *
 * ## `cursor` is here and is not a filter
 *
 * It lives in the URL so a page survives a reload, but `activeFilterCount` excludes it (with
 * `limit` and `withTotal`), and `SearchParamsState.patch` drops it on every filter change —
 * a keyset cursor cut against the old filter continues a list that no longer exists.
 */

import { z } from "zod";

import {
  DEFAULT_PAGE_LIMIT,
  MAX_PAGE_LIMIT,
  MIN_PAGE_LIMIT,
  ORDER_STATE_VALUES,
  type OrderStateCountsQuery,
  type OrdersQuery,
} from "@/api";
import type { FilterFieldDescriptor, TimeRange } from "@/components/data";
import {
  formatTimestamp,
  zBoolParam,
  zEnumList,
  zInstantParam,
  zIntParam,
  zStringParam,
  type SearchParamsSchema,
} from "@/lib";

export const ordersFilterSchema = z.object({
  /** Repeats: `?state=failed&state=cancelled` is failed OR cancelled. */
  state: zEnumList(ORDER_STATE_VALUES),
  isPaid: zBoolParam,
  hasAssets: zBoolParam,
  /** The INTEGER telegram id, never `users.id`. */
  telegramUserId: zIntParam({ min: 1 }),
  correlationId: zStringParam,
  from: zInstantParam,
  to: zInstantParam,
  limit: zIntParam({ min: MIN_PAGE_LIMIT, max: MAX_PAGE_LIMIT }),
  cursor: zStringParam,
});

export type OrdersFilter = z.infer<typeof ordersFilterSchema>;

/**
 * The same schema, named by its OUTPUT type for `useSearchParamsState`.
 *
 * The widening this comment used to ask for has been made: `useSearchParamsState` now takes
 * `SearchParamsSchema<T>` (`z.ZodType<T, z.ZodTypeDef, unknown>`), so a schema built from
 * `.transform()` codecs infers `T` from its output and this is a plain annotation instead of
 * an `as unknown as` that also switched off the output check.
 */
export const ordersFilterParser: SearchParamsSchema<OrdersFilter> = ordersFilterSchema;

/** The default view: newest orders, every state, no window. */
export const ORDERS_FILTER_FALLBACK: OrdersFilter = {
  state: undefined,
  isPaid: undefined,
  hasAssets: undefined,
  telegramUserId: undefined,
  correlationId: undefined,
  from: undefined,
  to: undefined,
  limit: undefined,
  cursor: undefined,
};

/** What the chips say. Instants are spelled out rather than humanised — an ISO string with
 *  a `Z` is the one form an operator can paste back into the bar. */
export const ORDER_FILTER_FIELDS: readonly FilterFieldDescriptor<OrdersFilter>[] = [
  { key: "state", label: "state" },
  { key: "isPaid", label: "paid" },
  { key: "hasAssets", label: "has assets" },
  { key: "telegramUserId", label: "telegram id" },
  { key: "correlationId", label: "correlation" },
  { key: "from", label: "from", format: formatInstantChip },
  { key: "to", label: "to", format: formatInstantChip },
];

function formatInstantChip(value: string | number | boolean): string {
  return typeof value === "string" ? formatTimestamp(value) : String(value);
}

/**
 * Give a half-open range its missing end, so what reaches the URL is a window the API will
 * accept. `to` defaults to now — that is what a "last 24 hours" preset means at the moment
 * it is clicked — and `from` to the epoch, which is the only honest lower bound when the
 * operator has named an upper one and nothing else.
 */
export function completeWindow(range: TimeRange, now: number = Date.now()): TimeRange {
  const hasFrom = range.from !== undefined && range.from !== "";
  const hasTo = range.to !== undefined && range.to !== "";
  if (hasFrom === hasTo) return range;
  if (hasFrom) return { from: range.from, to: instantOf(now) };
  return { from: instantOf(0), to: range.to };
}

function instantOf(ms: number): string {
  return new Date(ms).toISOString().replace(/\.\d{3}Z$/, "Z");
}

/**
 * The filter state as `/api/orders/state-counts`' query: every filter, no paging.
 *
 * This is the WHOLE of the filter dependency the two orders queries share, which is why it
 * is the base `toOrdersQuery` is built from rather than a second hand-maintained copy of the
 * same six fields. The bar and the table cannot drift onto different filters unless someone
 * deletes the spread below.
 *
 * `OrderStateCountsQuery` is `OrdersQuery` minus `PageQuery`, and the omission is what keeps
 * the aggregate's query key stable while an operator turns pages: the route ignores `limit`,
 * `cursor` and `withTotal`, so sending them would refetch an unbounded `GROUP BY` for a
 * parameter that changed nothing about its answer.
 */
export function toStateCountsQuery(filter: OrdersFilter): OrderStateCountsQuery {
  const isWindow = filter.from !== undefined && filter.to !== undefined;
  return {
    state: filter.state,
    isPaid: filter.isPaid,
    hasAssets: filter.hasAssets,
    telegramUserId: filter.telegramUserId,
    correlationId: filter.correlationId,
    from: isWindow ? filter.from : undefined,
    to: isWindow ? filter.to : undefined,
  };
}

/**
 * The filter state as the API's query.
 *
 * `withTotal` is on: this screen exists to describe the SHAPE of a filtered set, and "1–50
 * of 10,000+ orders" is part of that shape. It costs a second count query, which is why it
 * is off by default everywhere else. It is also CAPPED at `TOTAL_COUNT_CAP` — the exact
 * total the distribution bar is labelled from comes from the aggregate, not from here.
 */
export function toOrdersQuery(filter: OrdersFilter): OrdersQuery {
  return {
    ...toStateCountsQuery(filter),
    limit: filter.limit ?? DEFAULT_PAGE_LIMIT,
    cursor: filter.cursor,
    withTotal: true,
  };
}
