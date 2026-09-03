/**
 * The three reads behind `/`, and their §11.5 intervals.
 *
 * | query | endpoint | interval |
 * |---|---|---|
 * | `pulse` | `GET /api/ops/pulse` | 5 s |
 * | `delivery` | `GET /api/metrics/orders-by-day` over a rolling 24 h | 5 s |
 * | `orders` | `GET /api/orders?state=…` (the feed's source) | 5 s |
 *
 * Every one is visibility-gated through `pollWhileVisible`: a console left open on a second
 * monitor overnight makes no requests at all.
 *
 * `pulse` uses `queryKeys.ops.pulse()` with exactly the options `useLiveHeartbeat` uses, so
 * the top bar's `LIVE` pill and this screen share ONE request per tick rather than racing
 * two — that sharing is the whole reason §11.5 consolidated the dashboard into one endpoint.
 *
 * Hooks and constants only: no component lives in this file, so editing it does not remount
 * the screen under Fast Refresh.
 */

import { useQuery, type UseQueryResult } from "@tanstack/react-query";
import { useMemo } from "react";

import {
  getOrders,
  getOrdersByDay,
  getPulse,
  unwrapAsync,
  type OrderState,
  type OrdersPage,
  type OrdersPerDayView,
  type OrdersQuery,
  type PulseView,
} from "@/api";
import { useNow } from "@/components/util";
import { POLL_MS, pollWhileVisible, queryKeys } from "@/lib";

import { rollingWindow, WINDOW_QUANTUM_MS, type RollingWindow } from "./liveMetrics";

/**
 * What the feed and the attention list are about: the two in-flight states plus failures.
 *
 * `delivered` and `cancelled` are deliberately absent. A dashboard list padded with healthy
 * rows is one an operator learns to skip, and `AttentionList` drops them anyway.
 */
export const LIVE_ORDER_STATES: readonly OrderState[] = ["authorized", "generating", "failed"];

/** Enough to fill the attention list and the visible feed, and no more. */
export const LIVE_ORDER_LIMIT = 25;

/**
 * Module scope, not a `useMemo`: the object IS part of the query key, and a fresh literal on
 * every render would be a fresh key on every render.
 */
export const LIVE_ORDERS_QUERY: OrdersQuery = {
  state: LIVE_ORDER_STATES,
  limit: LIVE_ORDER_LIMIT,
};

export interface LiveOps {
  readonly pulse: UseQueryResult<PulseView>;
  readonly delivery: UseQueryResult<OrdersPerDayView[]>;
  readonly orders: UseQueryResult<OrdersPage>;
  /** The window `delivery` was asked for, so the screen can label its own numbers. */
  readonly window: RollingWindow;
}

export function useLiveOps(): LiveOps {
  // One re-render a minute, which is what moves the quantised window forward. The queries
  // themselves tick five times faster; this only decides which 24 hours they ask about.
  const minute = useNow(WINDOW_QUANTUM_MS);
  const window = useMemo(() => rollingWindow(minute), [minute]);

  const pulse = useQuery({
    queryKey: queryKeys.ops.pulse(),
    queryFn: ({ signal }) => unwrapAsync(getPulse({ signal })),
    refetchInterval: pollWhileVisible(POLL_MS.pulse),
  });

  const delivery = useQuery({
    queryKey: queryKeys.metrics.ordersByDay(window),
    queryFn: ({ signal }) => unwrapAsync(getOrdersByDay(window, { signal })),
    refetchInterval: pollWhileVisible(POLL_MS.pulse),
  });

  const orders = useQuery({
    queryKey: queryKeys.orders.list(LIVE_ORDERS_QUERY),
    queryFn: ({ signal }) => unwrapAsync(getOrders(LIVE_ORDERS_QUERY, { signal })),
    refetchInterval: pollWhileVisible(POLL_MS.feed),
  });

  return { pulse, delivery, orders, window };
}
