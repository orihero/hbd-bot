/**
 * TanStack Query v5, configured for a page that polls.
 *
 * A much smaller sibling of admin-ui/src/lib/queryClient.ts.
 *
 * `api/client.ts` never throws — every failure is a resolved `ApiResult` — but the dashboard's
 * query boundary converts one into a `DashboardQueryError` rejection so that `error`/`isError`
 * populate at all (`unwrap` in `features/dashboard/useDashboardData.ts`). The `retry: false`
 * here is therefore a DEFAULT for a query that states no policy of its own, not a statement
 * that nothing can reject: every dashboard query spreads `SHARED`, which sets `retry:
 * shouldRetry` and `retryDelay: backoffMs`. The policy stays there rather than moving here
 * because it reads a `DashboardQueryError`, and `lib/` does not know about `features/`.
 *
 * Two settings carry the "stale, not blank" rule the mock's `LIVE · 5s` pill implies:
 *
 *  - `placeholderData: keepPreviousData` — a re-key (the window's minute quantum, or the
 *    period picker) keeps the previous section on screen while the next one loads, instead of
 *    blanking eighteen cards. `isPlaceholderData` is READ, in `DashboardPage`: figures from
 *    the previous window are dimmed and marked `aria-busy` rather than passed off as the
 *    current one's, which is the failure mode this option would otherwise create.
 *  - `refetchIntervalInBackground: false` plus `pollWhileVisible` — a backgrounded tab stops
 *    asking, because four routes at 5s against a process that also serves `/readyz` is a
 *    load nobody is reading.
 */

import { QueryClient, keepPreviousData } from "@tanstack/react-query";

/**
 * The cadences the four sections actually want. The router's own docstring names three of
 * them — "fire fast, vendors slower, cohorts nightly" — and this is that, at the resolution
 * a browser tab can honestly hold.
 */
export const POLL_MS = {
  /** The mock's header pill: latency, failures and the status strip move minute to minute. */
  performance: 5_000,
  /** The charts. Redrawing six of them every 5s is work nobody's eye can follow. */
  series: 15_000,
  /** Receipts and balances. The balances are a cached table a worker refreshes anyway. */
  finance: 30_000,
  /** Cohort counts. A sign-up total does not move fast enough to be worth a faster tick. */
  audience: 60_000,
  /** The whole-record probe. */
  pulse: 5_000,
} as const;

/**
 * A `refetchInterval` that only fires while the tab is visible. Pass `false` to stop
 * entirely — that is how a section expresses "not while a dialog owns the screen".
 */
export function pollWhileVisible(intervalMs: number | false) {
  return (): number | false => {
    if (intervalMs === false) return false;
    if (typeof document === "undefined") return false;
    return document.visibilityState === "visible" ? intervalMs : false;
  };
}

/** How long a result counts as fresh. Shorter than the fastest poll, so the poll drives. */
export const DEFAULT_STALE_TIME_MS = 2_000;

/** How long an unused result is kept, so a navigation back is instant rather than blank. */
export const DEFAULT_GC_TIME_MS = 5 * 60_000;

export function createQueryClient(): QueryClient {
  return new QueryClient({
    defaultOptions: {
      queries: {
        staleTime: DEFAULT_STALE_TIME_MS,
        gcTime: DEFAULT_GC_TIME_MS,
        placeholderData: keepPreviousData,
        refetchIntervalInBackground: false,
        refetchOnWindowFocus: true,
        refetchOnReconnect: true,
        // Remounting a section must not refire a request whose answer is two seconds old.
        refetchOnMount: false,
        // A default for a query that states none; the dashboard's own policy is in `SHARED`.
        retry: false,
        throwOnError: false,
      },
      mutations: { retry: false },
    },
  });
}
