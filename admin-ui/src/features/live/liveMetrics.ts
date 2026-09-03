/**
 * The pure arithmetic behind `/` — kept out of the screen so it can be tested without a
 * DOM, and so the one genuinely contestable decision on this page is written down where it
 * is made rather than buried in JSX.
 *
 * ## Why the hero number does not come from `/ops/pulse`
 *
 * §11.2 fixes the Live-Ops dominant signal as the **24 h delivery success rate**. The
 * shipped `/api/ops/pulse` deliberately takes NO window (`dashboard.py`: "The pulse takes no
 * window. It is the state of the deployment as a whole"), so `PulseView.delivery.successRate`
 * is an all-time figure. An all-time rate cannot go amber for an incident that started an
 * hour ago — on a deployment with ten thousand delivered orders, a morning in which every
 * single order failed moves it by a fraction of a point. Rendering it at 44px under the
 * label "24 h" would be a wrong number, and rendering it at 44px under the label "all time"
 * would answer a question nobody on this screen is asking.
 *
 * So the hero is computed from `GET /api/metrics/orders-by-day` over a rolling 24 h window,
 * which is the only windowed source of delivery counts this build has. The pulse still
 * drives everything that is genuinely "right now" — in flight, the failure mix, latency,
 * capabilities — and the two queries share the 5 s tick.
 *
 * Two consequences of that source, both deliberate and both stated on screen:
 *
 *  - **The denominator is `delivered + failed`.** `orders-by-day` counts delivered, failed,
 *    paid and total per day; it has no `cancelled` column. The pulse's `terminalCount`
 *    includes cancelled orders, so the two rates are not the same ratio. Excluding
 *    cancellations from a *delivery* rate is defensible on its own terms — a customer who
 *    cancelled is not a delivery failure — but the tile says which ratio it is rather than
 *    leaving the operator to assume.
 *  - **`total` is not the denominator.** It counts every order created in the window,
 *    including the ones still in flight, and dividing by it would report a healthy morning
 *    as a 60% success rate purely because work is still running.
 *
 * `successRate` is `null`, never `0`, when nothing terminated in the window — `rateBand`
 * maps that to `unknown`, and a red 0% on a quiet morning is the most alarming wrong number
 * this console could show.
 */

import type { OrderView, OrdersPerDayView } from "@/api";
import { humaniseEnum, type FeedEvent, type FeedSeverity } from "@/lib";

/** §11.2's window for the dominant signal. */
export const ROLLING_WINDOW_MS = 24 * 60 * 60 * 1_000;

/**
 * The window's ends are rounded down to this before they reach a query key.
 *
 * A window built from a raw `Date.now()` is a different string on every render, which means
 * a different query key, which means a refetch on every render — a poll that never stops
 * because the key never settles. Quantising to a minute makes the key stable between ticks
 * while keeping the window within a minute of true.
 */
export const WINDOW_QUANTUM_MS = 60_000;

export interface RollingWindow {
  /** RFC 3339 with a `Z`. Both ends, always — a half-open window is a 422 (§6.1). */
  readonly from: string;
  readonly to: string;
}

/** `2026-09-02T12:00:00Z` — no milliseconds, so the URL and the key stay readable. */
function instantOf(ms: number): string {
  return new Date(ms).toISOString().replace(/\.\d{3}Z$/, "Z");
}

export function rollingWindow(
  now: number = Date.now(),
  spanMs: number = ROLLING_WINDOW_MS,
  quantumMs: number = WINDOW_QUANTUM_MS,
): RollingWindow {
  const to = Math.floor(now / quantumMs) * quantumMs;
  return { from: instantOf(to - spanMs), to: instantOf(to) };
}

export interface DeliverySummary {
  /** Every order CREATED in the window, in flight included. Never a denominator. */
  readonly orders: number;
  readonly delivered: number;
  readonly failed: number;
  readonly paid: number;
  /** `delivered + failed`. Cancelled orders are not in this series at all. */
  readonly terminal: number;
  /** `null` — never `0` — when nothing terminated in the window. */
  readonly successRate: number | null;
}

export const EMPTY_SUMMARY: DeliverySummary = {
  orders: 0,
  delivered: 0,
  failed: 0,
  paid: 0,
  terminal: 0,
  successRate: null,
};

/**
 * Sum the per-day rows the API returned.
 *
 * Days with no orders are ABSENT from the series rather than zero-filled, so summing what
 * arrived is exactly the window's totals — there are no gaps to fill for an aggregate, only
 * for a chart.
 */
export function summariseDays(days: readonly OrdersPerDayView[]): DeliverySummary {
  let orders = 0;
  let delivered = 0;
  let failed = 0;
  let paid = 0;
  for (const day of days) {
    orders += day.total;
    delivered += day.delivered;
    failed += day.failed;
    paid += day.paid;
  }
  const terminal = delivered + failed;
  return {
    orders,
    delivered,
    failed,
    paid,
    terminal,
    successRate: terminal === 0 ? null : delivered / terminal,
  };
}

/** How loudly a state reads in the feed. Anything not listed is `info`. */
const FEED_SEVERITY: Partial<Record<OrderView["state"], FeedSeverity>> = {
  failed: "error",
  cancelled: "warn",
};

export function feedSeverityOf(state: OrderView["state"]): FeedSeverity {
  return FEED_SEVERITY[state] ?? "info";
}

/**
 * Orders, as feed entries.
 *
 * `GET /api/ops/feed` does not exist on this build — §11.5 gives it a 5 s slot and the
 * server has no such route, so the feed is fed from the in-flight-and-failed orders list
 * polled at the same 5 s. `LiveFeed`'s own docstring names this as the sanctioned source.
 *
 * The id carries `updatedAt`, so an order that moves from `generating` to `failed` produces
 * a SECOND entry rather than silently rewriting the first — the feed is a log of what
 * changed, and a mutating row is not a log.
 *
 * `label` is our own closed vocabulary: the state, and for a failure the `failedReason`,
 * which is operator triage text from a fixed set and never a customer's words.
 */
export function feedEventsFromOrders(orders: readonly OrderView[]): readonly FeedEvent[] {
  return orders.map((order) => ({
    id: `${order.id}:${order.updatedAt}`,
    at: order.updatedAt,
    label:
      order.state === "failed" && order.failedReason !== null
        ? `${humaniseEnum(order.state)} · ${order.failedReason}`
        : humaniseEnum(order.state),
    severity: feedSeverityOf(order.state),
    orderId: order.id,
    correlationId: order.correlationId,
  }));
}
