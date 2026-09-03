/**
 * TanStack Query v5 setup and the §11.5 polling tiers.
 *
 * **v1 is tiered polling. v1.1 adds SSE for the live feed only. WebSocket: never.**
 *
 * The reason is in the pipeline, not in the frontend. There is no event bus to subscribe to:
 * `events.py`'s docstring says "Redis pub/sub, in practice", but the only production
 * `ProgressSink` is `TelegramProgressSink`, which edits one Telegram message. And
 * `KitPipeline._replay` returns the stored kit BEFORE the reporter is constructed, so a
 * retried order that replays emits ZERO progress events — a stream-only dashboard would
 * show a successfully re-delivered order as never having run. That rules out
 * stream-as-sole-source, and it is why the SSE upgrade keeps a 30s poll as a mandatory
 * backstop rather than replacing the poll.
 *
 * Four settings make "stale, not blank" work, and all four are needed:
 *
 *  - `refetchInterval` is a FUNCTION gated on `document.visibilityState === "visible"`, so a
 *    backgrounded tab stops asking.
 *  - `refetchIntervalInBackground: false`, belt and braces for the same thing.
 *  - `placeholderData: keepPreviousData` — the last good page stays on screen while the next
 *    one loads. A dashboard that blanks on a failed poll is worse than one showing stale
 *    numbers labelled stale (§11.4's Stale state).
 *  - exponential backoff capped at 60s, so a dead API is asked once a minute rather than
 *    every 5 seconds by six screens at once.
 */

import { QueryClient, keepPreviousData, type Query } from "@tanstack/react-query";

import { failureOf } from "@/api";

/* -------------------------------------------------------------------------- */
/* The tiers — §11.5's table, verbatim                                         */
/* -------------------------------------------------------------------------- */

export const POLL_MS = {
  /** `/ops/pulse` and `/ops/feed`. The one consolidated dashboard read. */
  pulse: 5_000,
  feed: 5_000,
  /** Order detail, ONLY while the order is in flight. Otherwise off. */
  orderDetail: 3_000,
  /** Moderation queue and its nav badge. */
  moderation: 10_000,
  /** Orders list — and only when no row is expanded. */
  ordersList: 15_000,
} as const;

/** "Everything else": on demand plus `refetchOnWindowFocus`. */
export const NO_POLLING = false as const;

/**
 * A `refetchInterval` that only fires while the tab is visible.
 *
 * Pass `false` to stop entirely — that is how the order-detail tier expresses "3s while the
 * state is authorized or generating, else off", and how the orders list expresses "only when
 * no row is expanded".
 */
export function pollWhileVisible(intervalMs: number | false) {
  return (): number | false => {
    if (intervalMs === false) return false;
    if (typeof document === "undefined") return false;
    return document.visibilityState === "visible" ? intervalMs : false;
  };
}

/** Exponential backoff, capped at 60s: 1s, 2s, 4s, 8s, … 60s. */
export function backoffDelay(attemptIndex: number): number {
  return Math.min(60_000, 1_000 * 2 ** attemptIndex);
}

/** How many attempts before a query gives up and shows the error state. */
export const MAX_QUERY_RETRIES = 3;

/**
 * Whether a failed query is worth retrying.
 *
 * A 4xx is not: an unauthenticated caller stays unauthenticated, a forbidden read stays
 * forbidden (and each retry writes a second refusal row to the audit log, which is how a
 * denial becomes an incident), and a 422 is a bug in the request. SCHEMA_DRIFT is
 * emphatically not retryable — the same bytes will arrive again, and the point is that the
 * operator sees the banner.
 */
export function shouldRetry(failureCount: number, error: unknown): boolean {
  if (failureCount >= MAX_QUERY_RETRIES) return false;
  const apiFailure = failureOf(error);
  if (apiFailure === null) return false;
  if (apiFailure.code === "SCHEMA_DRIFT" || apiFailure.code === "REQUEST_ABORTED") return false;
  // status 0 is a transport failure — worth another go.
  if (apiFailure.status === 0) return true;
  return apiFailure.status >= 500;
}

/* -------------------------------------------------------------------------- */
/* The client                                                                  */
/* -------------------------------------------------------------------------- */

/**
 * How long a result is considered fresh. Deliberately shorter than the fastest poll: the
 * polls are what drive updates, and a long `staleTime` would make a navigation back to a
 * screen show a minute-old number with no indication of its age.
 */
export const DEFAULT_STALE_TIME_MS = 2_000;

/** How long an unused result is kept so a back-navigation is instant rather than blank. */
export const DEFAULT_GC_TIME_MS = 5 * 60_000;

export function createQueryClient(): QueryClient {
  return new QueryClient({
    defaultOptions: {
      queries: {
        staleTime: DEFAULT_STALE_TIME_MS,
        gcTime: DEFAULT_GC_TIME_MS,
        // §11.4's Stale state depends on this: the previous page stays rendered (at 70%
        // opacity, with a `stale 42s` chip) instead of unmounting into a skeleton.
        placeholderData: keepPreviousData,
        refetchIntervalInBackground: false,
        refetchOnWindowFocus: true,
        refetchOnReconnect: true,
        // Remounting a screen must not refire a request whose answer is two seconds old.
        refetchOnMount: false,
        retry: shouldRetry,
        retryDelay: backoffDelay,
        // The client never throws on its own; `unwrap` at the query boundary is what makes
        // a failure a rejection, and this keeps that the only source of thrown errors.
        throwOnError: false,
      },
      mutations: {
        // A mutation is a decision an operator made once. Retrying it silently could mean
        // two force-deliveries, so retries are opt-in per mutation and never a default.
        retry: false,
      },
    },
  });
}

/* -------------------------------------------------------------------------- */
/* The LIVE pill                                                               */
/* -------------------------------------------------------------------------- */

/**
 * §11.5: "The `LIVE` pill reads `dataUpdatedAt` and the query's error count — it is not a
 * separate connection concept." There is no socket to be connected to; freshness IS the
 * connection.
 */
export type LiveState = "live" | "lagging" | "stalled" | "paused";

export const LIVE_THRESHOLD_MS = 10_000;
export const LAGGING_THRESHOLD_MS = 30_000;

export interface LiveStatus {
  readonly state: LiveState;
  /** Milliseconds since the last successful update. `null` when nothing has arrived yet. */
  readonly ageMs: number | null;
  /** Seconds until the next attempt, for the red countdown. `null` unless stalled. */
  readonly countdownS: number | null;
}

/**
 * Green pulsing <10s · amber 10–30s or retrying · red >30s with a countdown · slate when
 * paused.
 *
 * `dataUpdatedAt` is `0` before the first success, which is NOT "very stale" — it is "no
 * answer yet", and the pill must not go red on a cold start.
 */
export function liveStatus(input: {
  dataUpdatedAt: number;
  errorCount: number;
  isPaused: boolean;
  now?: number;
}): LiveStatus {
  const now = input.now ?? Date.now();
  if (input.isPaused) return { state: "paused", ageMs: null, countdownS: null };
  if (input.dataUpdatedAt === 0) {
    return { state: input.errorCount > 0 ? "lagging" : "live", ageMs: null, countdownS: null };
  }
  const ageMs = Math.max(0, now - input.dataUpdatedAt);
  if (ageMs > LAGGING_THRESHOLD_MS) {
    const nextAttemptMs = backoffDelay(input.errorCount);
    return { state: "stalled", ageMs, countdownS: Math.ceil(nextAttemptMs / 1_000) };
  }
  if (ageMs > LIVE_THRESHOLD_MS || input.errorCount > 0) {
    return { state: "lagging", ageMs, countdownS: null };
  }
  return { state: "live", ageMs, countdownS: null };
}

/**
 * Whether a rendered result is stale enough to earn §11.4's `stale 42s` chip. Deliberately
 * the same threshold the pill goes amber at, so the two never disagree on screen.
 */
export function isStale(dataUpdatedAt: number, now: number = Date.now()): boolean {
  return dataUpdatedAt !== 0 && now - dataUpdatedAt > LIVE_THRESHOLD_MS;
}

/** Seconds since the last successful update, for that chip. */
export function staleSeconds(dataUpdatedAt: number, now: number = Date.now()): number {
  return Math.max(0, Math.round((now - dataUpdatedAt) / 1_000));
}

/**
 * The v1.1 seam, written down so it does not get invented twice.
 *
 * An `EventSource` on `/api/v1/stream` will push into THIS cache via `setQueryData` while
 * the poll drops to 30s as a backstop. No frontend restructuring: the same query keys, the
 * same components. The backstop is mandatory because SSE is fire-and-forget and a subscriber
 * disconnected during a publish never learns what it missed.
 */
export const SSE_BACKSTOP_POLL_MS = 30_000;

/** Type-only helper so a screen can write a `refetchInterval` that reads its own data. */
export type RefetchIntervalFor<TData> = (query: Query<TData, Error, TData>) => number | false;
