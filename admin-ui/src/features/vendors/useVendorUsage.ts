/**
 * The three reads behind `/vendors`, and the one pivot that turns a sparse series into a
 * stacked bar chart.
 *
 * | query | endpoint | interval |
 * |---|---|---|
 * | `usage` | `GET /api/metrics/vendor-usage` | none |
 * | `byDay` | `GET /api/metrics/vendor-usage-by-day` | none |
 * | `errors` | `GET /api/metrics/vendor-errors` | none |
 *
 * **Nothing here polls.** §11.5 gives an interval to the pulse, order detail, the moderation
 * queue and the orders list; everything else is "on demand plus `refetchOnWindowFocus`", and
 * spend is the clearest case for it — a cost rollup is not live ops, a five-second tick
 * would re-run four `GROUP BY`s over a 400-day table to move a figure nobody is watching
 * change, and the answer an operator wants is the one from when they opened the screen.
 *
 * All three take the SAME query object, which is also their key, so the rollup and the chart
 * beside it can never be counted over different windows.
 *
 * Hooks and pure functions only — no component lives in this file, so editing it does not
 * remount the screen under Fast Refresh.
 */

import { useQuery, type UseQueryResult } from "@tanstack/react-query";

import {
  VENDOR_VALUES,
  getVendorErrors,
  getVendorUsage,
  getVendorUsageByDay,
  unwrapAsync,
  type Vendor,
  type VendorErrorView,
  type VendorUsagePerDayView,
  type VendorUsageQuery,
  type VendorUsageResponse,
} from "@/api";
import { categoricalTone, type ChartDatum, type ChartSeriesSpec } from "@/components/data";
import { NO_POLLING, humaniseEnum, queryKeys } from "@/lib";

export interface VendorUsageQueries {
  readonly usage: UseQueryResult<VendorUsageResponse>;
  readonly byDay: UseQueryResult<VendorUsagePerDayView[]>;
  readonly errors: UseQueryResult<VendorErrorView[]>;
}

export function useVendorUsage(query: VendorUsageQuery): VendorUsageQueries {
  const usage = useQuery({
    queryKey: queryKeys.vendors.usage(query),
    queryFn: ({ signal }) => unwrapAsync(getVendorUsage(query, { signal })),
    refetchInterval: NO_POLLING,
    refetchOnWindowFocus: true,
  });

  const byDay = useQuery({
    queryKey: queryKeys.vendors.byDay(query),
    queryFn: ({ signal }) => unwrapAsync(getVendorUsageByDay(query, { signal })),
    refetchInterval: NO_POLLING,
    refetchOnWindowFocus: true,
  });

  const errors = useQuery({
    queryKey: queryKeys.vendors.errors(query),
    queryFn: ({ signal }) => unwrapAsync(getVendorErrors(query, { signal })),
    refetchInterval: NO_POLLING,
    refetchOnWindowFocus: true,
  });

  return { usage, byDay, errors };
}

/* -------------------------------------------------------------------------- */
/* The pivot                                                                   */
/* -------------------------------------------------------------------------- */

/** A chart's data, its series list, and the coverage of the figure it plots — all derived
 *  together from one array so they cannot disagree about which window they describe. */
export interface VendorDaySeries {
  readonly data: readonly ChartDatum[];
  readonly series: readonly ChartSeriesSpec[];
  /**
   * Every call in the window, priced or not — summed over ALL the points, including the ones
   * the cost series drops.
   */
  readonly calls: number;
  /**
   * How many of those calls carried a cost. **The denominator of the money the cost chart
   * draws**, and the reason it is here rather than discarded in the pivot: `costUsd` sums
   * only priced rows, so a window of nine hundred calls of which nine were priced plots a
   * total that looks like the bill for nine hundred. The server computes this per point
   * precisely so that cannot be misread, and dropping it in the pivot would put the
   * misreading back.
   *
   * It is carried as a WINDOW total rather than per point because the only place a per-point
   * figure could surface is `ChartFrame`'s tooltip, whose `formatValue` hook is
   * `(value, seriesKey) => string` — it never sees the datum row, so a second quantity per
   * (day, vendor) cannot reach it, and §11.1 forbids reaching around the frame into Recharts
   * to fix that. The screen states the coverage in a caption under the chart instead.
   */
  readonly costedCalls: number;
}

/** Which measure a chart is drawing. Two charts and not one with two scales: `ChartFrame`
 *  has exactly one y-axis by design, and dollars and calls share no magnitude. */
export type VendorDayMetric = "calls" | "costUsd";

/**
 * Turn `[{day, vendor, calls, costUsd}]` into one row per day with one column per vendor.
 *
 * Three properties this function is careful about, all of them the same rule:
 *
 *  - **A (day, vendor) pair with no calls is ABSENT from the response and stays absent
 *    here.** No zero-fill. A stacked bar chart with a zero segment says the vendor was
 *    asked and did nothing; a gap says nobody asked. The endpoint refuses to invent the
 *    first and so does this.
 *  - **An unpriced point is dropped from the COST series, not zeroed into it.** `costUsd`
 *    is `null` when nothing that day was priced, and `null + null` in a stack renders as a
 *    baseline — an operator would read a flat run of days as "we spent nothing" when it
 *    means "no rate is configured". Dropping the point leaves the gap, and when every point
 *    is unpriced the series is empty and `ChartFrame` shows its own worded well instead.
 *  - **Series order is `VENDOR_VALUES`' declaration order**, not first-seen order, so a
 *    vendor keeps its colour slot when a filter changes which others are present.
 *
 * The two coverage counts come back beside the data for the reason `VendorDaySeries.
 * costedCalls` states: a partial dollar total is only readable next to the count of what was
 * priced, and both counts are summed over the WHOLE input — the points the cost series drops
 * are exactly the ones the caption exists to account for.
 */
export function toVendorDaySeries(
  points: readonly VendorUsagePerDayView[],
  metric: VendorDayMetric,
): VendorDaySeries {
  const usable =
    metric === "calls" ? points : points.filter((point) => point.costUsd !== null);

  const present: Vendor[] = VENDOR_VALUES.filter((vendor) =>
    usable.some((point) => point.vendor === vendor),
  );

  const byDay = new Map<string, Record<string, string | number | null>>();
  for (const point of usable) {
    const row = byDay.get(point.day) ?? { day: point.day };
    row[point.vendor] = metric === "calls" ? point.calls : point.costUsd;
    byDay.set(point.day, row);
  }

  let calls = 0;
  let costedCalls = 0;
  for (const point of points) {
    calls += point.calls;
    costedCalls += point.costedCalls;
  }

  return {
    data: [...byDay.values()],
    series: present.map((vendor, index) => ({
      key: vendor,
      label: humaniseEnum(vendor),
      tone: categoricalTone(index),
    })),
    calls,
    costedCalls,
  };
}

/**
 * The one cost source that describes a whole window, for the hero tile's caption.
 *
 * `null` when nothing in the window carried a cost, the single source when every priced
 * group agreed, and `"mixed"` the moment two groups were priced differently — which is the
 * common case the moment a deployment prices both a token rate and a music minute. It is
 * the same collapse the server does per group, applied once more across them, and it exists
 * so the hero figure never states a provenance stronger than its weakest leg.
 */
export function dominantCostSource(
  rows: readonly { readonly costUsd: number | null; readonly costSource: string | null }[],
): string | null {
  const sources = new Set<string>();
  for (const row of rows) {
    if (row.costUsd === null || row.costSource === null) continue;
    sources.add(row.costSource);
  }
  if (sources.size === 0) return null;
  if (sources.size > 1) return "mixed";
  return [...sources][0] ?? null;
}
