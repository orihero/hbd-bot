/**
 * `/orders`' filter state: the URL, parsed.
 *
 * §11.1 — "URL search params (zod-parsed) for all filter state so an operator can paste 'the
 * failed orders I'm looking at' into Slack". There is no second copy of this state anywhere
 * in the feature; the address bar is the store, and `buildFilterChips` renders it back.
 *
 * ## The window is a PAIR
 *
 * `from` and `to` are one window on every list endpoint: `orders.py`'s `_window` refuses
 * half of one with a 422 ("from and to are one window — give both bounds or neither").
 * `TimeRangePicker` emits `{from, to: undefined}` for its presets, which would be that 422
 * on every preset click, so `completeWindow` fills the missing end before the value is
 * written to the URL, and `toOrdersQuery` drops a half window rather than sending it. The
 * completed pair is also what makes a pasted link reproducible: "last 24 hours" a week from
 * now is a different set of orders, a fixed window is not.
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
  type OrderStateCount,
  type OrderView,
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
 * The filter state as the API's query.
 *
 * `withTotal` is on: this screen exists to describe the SHAPE of a filtered set, and "1–50
 * of 10,000+ orders" is part of that shape. It costs a second count query, which is why it
 * is off by default everywhere else.
 */
export function toOrdersQuery(filter: OrdersFilter): OrdersQuery {
  const isWindow = filter.from !== undefined && filter.to !== undefined;
  return {
    state: filter.state,
    isPaid: filter.isPaid,
    hasAssets: filter.hasAssets,
    telegramUserId: filter.telegramUserId,
    correlationId: filter.correlationId,
    from: isWindow ? filter.from : undefined,
    to: isWindow ? filter.to : undefined,
    limit: filter.limit ?? DEFAULT_PAGE_LIMIT,
    cursor: filter.cursor,
    withTotal: true,
  };
}

/**
 * The state distribution of the rows currently on screen.
 *
 * There is no endpoint that returns per-state counts for an arbitrary filter —
 * `ordersByState` exists on `UserDetailView` and nowhere else — so the bar describes THIS
 * PAGE, which is also exactly the question §11.2 asks ("what is the shape of what I just
 * filtered to?"). The screen labels it as the page's shape so it cannot be read as the
 * whole result set.
 *
 * States with no rows are omitted rather than zero-filled: `StateDistributionBar` skips a
 * zero-count state, and a zero-width sliver in the legend is noise.
 */
export function countByState(orders: readonly OrderView[]): readonly OrderStateCount[] {
  const counts = new Map<OrderView["state"], number>();
  for (const order of orders) {
    counts.set(order.state, (counts.get(order.state) ?? 0) + 1);
  }
  return ORDER_STATE_VALUES.filter((state) => counts.has(state)).map((state) => ({
    state,
    count: counts.get(state) ?? 0,
  }));
}
