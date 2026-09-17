/**
 * The eight reads behind the dashboard, as hooks.
 *
 * `api/dashboard.ts` fetches and `lib/queryClient.ts` configures; this is the layer between
 * them, and it makes four decisions the page depends on.
 *
 * **One clock, quantised.** `windowFor` takes `now` as a parameter precisely so every section
 * of one refresh is asked for the SAME `[from, to)` — two `Date.now()` reads a few
 * milliseconds apart put a card and the chart under it on opposite sides of a bucket
 * boundary. `useDashboardWindow` is that single clock, quantised to the minute so the window
 * is a stable value and not a new one on every render (a window in the query key that moved
 * every render would be a cache miss every render, which is a poll with no interval).
 *
 * **The window is IN the key.** Changing the period must refetch, not relabel: showing last
 * month's eighteen cards under the word "Today" is the one failure mode a dashboard cannot
 * recover from, because nothing on screen looks wrong.
 *
 * **Four routes, four cadences.** `dashboard.py` is explicit that the split into four exists
 * so they can tick at different rates — "fire fast, vendors slower, cohorts nightly" — and
 * that the alternative would "force the slowest aggregate on the page, the latency
 * percentiles' three round trips, into the tick of the fastest card". The header pill says
 * `LIVE · 5s`; only `/ops/pulse` actually runs at 5s, and it is the one the pill should read.
 * Each interval below carries its reason.
 *
 * **A hidden tab asks for nothing.** `refetchIntervalInBackground: false` is the library
 * default, and it is restated here as a choice rather than left as an accident: seven polling
 * routes against a process that also serves `/readyz`, for a screen on a second monitor nobody
 * is looking at, is load spent on nothing. `pollWhileVisible` is belt to that braces — it
 * returns `false` while hidden, so the interval is not merely deferred, it is not scheduled.
 *
 * **One read does not poll at all.** `useAudienceLists` is `RECORDS_READ` and writes an audit
 * row per call, so it has no interval, no focus refetch and a long `staleTime`: the log's
 * whole value is that a row in it means an admin actually looked at customer identities.
 */

import {
  useIsFetching,
  useQuery,
  useQueryClient,
  type QueryCache,
  type UseQueryResult,
} from "@tanstack/react-query";
import { useCallback, useEffect, useMemo, useState, useSyncExternalStore } from "react";

import { CLIENT_ERROR_CODES, type ApiFailure, type ApiResult, type SchemaIssue } from "@/api/client";
import {
  audience as fetchAudience,
  audienceLists as fetchAudienceLists,
  finance as fetchFinance,
  performance as fetchPerformance,
  plans as fetchPlans,
  pulse as fetchPulse,
  series as fetchSeries,
  vendor as fetchVendor,
  DEFAULT_AUDIENCE_LIST_LIMIT,
  type AudienceListsResponse,
  type AudienceResponse,
  type FinanceResponse,
  type PerformanceResponse,
  type PlanLiabilityResponse,
  type PulseView,
  type SeriesBucket,
  type SeriesResponse,
  type VendorResponse,
} from "@/api/dashboard";
import { POLL_MS, pollWhileVisible } from "@/lib/queryClient";

import { bucketFor, windowFor, type ApiWindow, type Gran, type Period } from "./window";

/* -------------------------------------------------------------------------- */
/* The error a failed read becomes                                             */
/* -------------------------------------------------------------------------- */

/**
 * The one place this app opts back into exceptions.
 *
 * `api/client.ts` never throws — every failure is a resolved `ApiResult`. TanStack Query's
 * contract is the opposite: it needs a REJECTION to populate `error`/`isError` and to run a
 * retry policy at all. So the query boundary, and only the query boundary, converts one into
 * the other. The whole `ApiFailure` is carried, not just its message, because the page has
 * three different things to render from it: `code` picks the copy (a `SCHEMA_DRIFT` banner is
 * not an offline chip), `status` decides whether to send the operator to `/login`, and
 * `correlationId` is what an operator pastes into a bug report.
 */
export class DashboardQueryError extends Error {
  /** A server code (`UNAUTHENTICATED`, `FORBIDDEN`, …) or one of the client's own. */
  readonly code: string;
  /** The HTTP status. `0` when the request never reached the server. */
  readonly status: number;
  /** The route template that failed, e.g. `GET /api/metrics/dashboard/finance`. */
  readonly endpoint: string;
  readonly correlationId: string | null;
  /** Populated for `SCHEMA_DRIFT` only — the field paths this build did not understand. */
  readonly issues: readonly SchemaIssue[] | null;
  readonly retryAfterS: number | null;
  /** The failure verbatim, for anything the fields above flattened away. */
  readonly failure: ApiFailure;

  constructor(failure: ApiFailure) {
    super(failure.message);
    this.name = "DashboardQueryError";
    this.code = failure.code;
    this.status = failure.status;
    this.endpoint = failure.endpoint;
    this.correlationId = failure.correlationId;
    this.issues = failure.issues;
    this.retryAfterS = failure.retryAfterS;
    this.failure = failure;
  }
}

export function isDashboardQueryError(error: unknown): error is DashboardQueryError {
  return error instanceof DashboardQueryError;
}

/** `data` on success; a `DashboardQueryError` rejection on failure. Used only in a `queryFn`. */
async function unwrap<T>(promise: Promise<ApiResult<T>>): Promise<T> {
  const result = await promise;
  if (result.ok) return result.data;
  throw new DashboardQueryError(result);
}

/* -------------------------------------------------------------------------- */
/* Retry policy                                                                */
/* -------------------------------------------------------------------------- */

/**
 * Statuses that will answer the same way however many times they are asked.
 *
 * **401** — the session is gone. Retrying cannot bring it back; what the operator needs is to
 * be sent to `/login`, and that only happens if the error surfaces on the first failure.
 * **403** — this role cannot read this section. Every attempt is an audit row saying so, and
 * three rows is not more informative than one.
 * **422** — the request itself is wrong (a `bucket` the window cannot serve, an unparseable
 * instant). A byte-identical retry gets a byte-identical refusal.
 */
const TERMINAL_STATUSES: readonly number[] = [401, 403, 422];

/** Two retries, then the poll takes over. A dashboard's real retry is its next tick. */
const MAX_RETRIES = 2;

function shouldRetry(failureCount: number, error: unknown): boolean {
  if (failureCount >= MAX_RETRIES) return false;
  if (!isDashboardQueryError(error)) return false;
  // The caller cancelled (unmount, or a period change superseding this window). Not a failure.
  if (error.code === CLIENT_ERROR_CODES.aborted) return false;
  // The server and this bundle disagree about the contract. Re-reading the same bytes is not
  // a fix, and the banner it raises is the loudest thing this app can say — say it at once.
  if (error.code === CLIENT_ERROR_CODES.schemaDrift) return false;
  if (TERMINAL_STATUSES.includes(error.status)) return false;
  // 0 is a transport failure — a flapped wifi, a proxy blip. Worth another go.
  if (error.status === 0) return true;
  // 5xx only. 429 falls through to `false`: retrying a rate limit is what caused it.
  return error.status >= 500;
}

/**
 * 1s then 2s, capped. Bounded so that both retries land INSIDE the fastest poll interval —
 * a backoff longer than the tick would leave two attempts at the same window in flight.
 */
const RETRY_BASE_MS = 1_000;
const RETRY_CAP_MS = 4_000;

function backoffMs(attemptIndex: number): number {
  return Math.min(RETRY_BASE_MS * 2 ** attemptIndex, RETRY_CAP_MS);
}

/* -------------------------------------------------------------------------- */
/* Cadence                                                                     */
/* -------------------------------------------------------------------------- */

/**
 * The refresh interval per route, with the round trips each one costs on the server.
 *
 * Five of the six are `POLL_MS`'s. `performance` deliberately is NOT: `POLL_MS.performance`
 * is the header pill's 5s, and the pill is about the PAGE feeling live rather than about
 * this route, which is seven sequential queries — delivered counts, delivery percentiles,
 * music-operation percentiles, the failure breakdown, the order funnel, the cached balances
 * and the capability probe. Three of them are the percentile round trips `dashboard.py` names
 * as the reason the page was split into four routes in the first place; putting them on a 5s
 * tick rebuilds by hand exactly the thing that split was avoiding. `pulse` keeps the 5s, and
 * `pulse` is what the LIVE pill should read.
 */
const POLL = {
  /** 60s — cohort counts. A sign-up total does not move fast enough to reward a faster tick. */
  audience: POLL_MS.audience,
  /** 30s — receipts, FX and the balance table a worker refreshes on its own schedule anyway. */
  finance: POLL_MS.finance,
  /** 10s — seven server-side queries, three of them percentile scans. See above. */
  performance: 10_000,
  /** 15s — six charts. Redrawing them every 5s is motion no eye can read as a trend. */
  series: POLL_MS.series,
  /** 5s — the cheap whole-record probe, and the only honest source for a `LIVE · 5s` pill. */
  pulse: POLL_MS.pulse,
  /**
   * 30s — vendor spend, its provenance and the cached balance table. `finance`'s cadence and
   * not `audience`'s, because it republishes two of `finance`'s own fields (`vendorSpend`,
   * `vendorBalances`) from the same functions: two cards showing one quantity on two clocks
   * would disagree for as long as the slower of them was behind, and the contract says they
   * agree whenever they are fetched over the same window.
   */
  vendor: POLL_MS.finance,
  /**
   * 60s — the plan book. A STATE, not a flow: it moves when somebody buys or a plan expires,
   * which is the slowest thing on this page, and its `asOf` is printed beside every figure it
   * feeds so a minute of age is legible rather than hidden.
   */
  plans: POLL_MS.audience,
} as const;

/**
 * `audience-lists` has NO interval here, and it is the only read on this page that has none.
 *
 * Every call writes an audit row inside the request's own transaction — that log is what the
 * owner accepted INSTEAD OF a reveal gate on customer identity. A 30s poll would therefore
 * manufacture a disclosure record every thirty seconds for a screen nobody was reading, and
 * the log's value is precisely that a row in it means somebody looked.
 *
 * So: no `refetchInterval`, no refetch on focus, no refetch on reconnect (the last two are
 * `true` by default in `queryClient.ts` and are overridden per query below), and a stale time
 * long enough that a remount inside a working session reuses the answer rather than buying a
 * second row for the same look. The refresh is the operator's, by hand.
 */
const AUDIENCE_LISTS_STALE_MS = 5 * 60_000;

/**
 * Options every dashboard query shares.
 *
 * `refetchIntervalInBackground: false` is already the library default; it is written out
 * because "the tab stops polling when you look away" is a behaviour someone will look for the
 * switch for, and a default is not a switch anybody can find.
 */
const SHARED = {
  refetchIntervalInBackground: false,
  retry: shouldRetry,
  retryDelay: backoffMs,
} as const;

/* -------------------------------------------------------------------------- */
/* The window, and the clock behind it                                         */
/* -------------------------------------------------------------------------- */

/**
 * How coarsely the trailing window's edge moves.
 *
 * A minute, because the window is part of every query key: a window that advanced on every
 * render would be a new key on every render, and a new key is a cold fetch. Quantising makes
 * "now" a value that changes sixty times an hour rather than continuously, so a section polls
 * on its own interval against a stable key and only re-keys when the minute turns. The cost
 * is that the upper bound of a rolling window trails the wall clock by up to a minute, which
 * no card on this page can express anyway.
 */
export const WINDOW_QUANTUM_MS = 60_000;

/** How often the quantised clock is CHECKED. A no-op `setState` is free; a late window is not. */
const CLOCK_TICK_MS = 15_000;

function quantise(ms: number): number {
  return Math.floor(ms / WINDOW_QUANTUM_MS) * WINDOW_QUANTUM_MS;
}

/**
 * The minute, as a number that only changes when the minute does.
 *
 * Checked rather than scheduled on the boundary: a background tab throttles timers, so a
 * clock that fires exactly once a minute can be minutes late on return. Recomputing from
 * `Date.now()` on each check means the value is always correct when it does update, and the
 * identity comparison keeps every check between boundaries free of a re-render.
 */
function useQuantisedNow(): number {
  const [tick, setTick] = useState(() => quantise(Date.now()));
  useEffect(() => {
    const id = window.setInterval(() => {
      setTick((previous) => {
        const next = quantise(Date.now());
        return next === previous ? previous : next;
      });
    }, CLOCK_TICK_MS);
    return () => {
      window.clearInterval(id);
    };
  }, []);
  return tick;
}

/**
 * The `[from, to)` the whole page is asked about, for a given period.
 *
 * Every windowed hook calls this, so the windowed sections of one refresh carry byte-identical
 * bounds — which is also why their query keys agree and a shared window is fetched once.
 */
export function useDashboardWindow(period: Period): ApiWindow {
  const minute = useQuantisedNow();
  return useMemo(() => windowFor(period, new Date(minute)), [period, minute]);
}

/* -------------------------------------------------------------------------- */
/* Keys                                                                        */
/* -------------------------------------------------------------------------- */

/** The namespace every read on this page hangs under, so `useLiveness` can find them all. */
const DASHBOARD_ROOT = "dashboard";

/**
 * The key factory.
 *
 * The window goes in as an object; TanStack hashes it stably (its `hashKey` sorts keys), so
 * `{from, to}` and `{to, from}` are one entry and nothing needs normalising before the call.
 *
 * The PERIOD is deliberately absent: what was asked for is the window, and two spellings of
 * the same range are the same read. What must never be absent is the window itself — that is
 * what stops a period change from relabelling numbers instead of refetching them.
 */
export const dashboardKeys = {
  all: [DASHBOARD_ROOT] as const,
  audience: (window: ApiWindow) => [DASHBOARD_ROOT, "audience", window] as const,
  finance: (window: ApiWindow) => [DASHBOARD_ROOT, "finance", window] as const,
  performance: (window: ApiWindow) => [DASHBOARD_ROOT, "performance", window] as const,
  /** The bucket is a second dimension: one window is charted at several grains. */
  series: (window: ApiWindow, bucket: SeriesBucket) =>
    [DASHBOARD_ROOT, "series", window, bucket] as const,
  vendor: (window: ApiWindow) => [DASHBOARD_ROOT, "vendor", window] as const,
  /**
   * NO window in the key, because the route takes none: the plan book is a state, and one
   * cache entry is the whole truth about it. A window here would be a lie the cache told
   * fluently — four period-keyed entries all holding the same bytes, each captioned with a
   * period the server never applied.
   */
  plans: () => [DASHBOARD_ROOT, "plans"] as const,
  /**
   * The window narrows `topGenerators` and NOTHING else; `recentSubscribers` is a recency
   * list the route takes no parameter for. Both are in one key because they arrive in one
   * response — and `limit`, which applies to both, is the key's second dimension.
   */
  audienceLists: (topGeneratorsWindow: ApiWindow, limit: number) =>
    [DASHBOARD_ROOT, "audience-lists", topGeneratorsWindow, limit] as const,
  /** Unwindowed by the server's own decision — the deployment as a whole. */
  pulse: () => [DASHBOARD_ROOT, "pulse"] as const,
} as const;

export type DashboardKeys = typeof dashboardKeys;

/* -------------------------------------------------------------------------- */
/* The eight reads                                                             */
/* -------------------------------------------------------------------------- */

/**
 * ``enabled`` is what makes a per-card period affordable.
 *
 * Each section is now read once PER DISTINCT PERIOD its cards ask for, and the page calls
 * these hooks a fixed four times each — once per member of ``Period`` — so the hook order is
 * static and React is never asked to reconcile a changing call count. Only the periods some
 * card is actually showing are ``enabled``; the rest are inert subscriptions that issue no
 * request and hold no poll. The alternative, ``useQueries`` over a dynamic list, buys the
 * same three-to-twelve saving at the cost of an array whose identity has to stay stable by
 * hand — the bug that shape invites is a refetch storm, and it is invisible until it is a
 * rate limit.
 */
type SectionEnabled = { readonly enabled: boolean };

/** Population, sign-ups, activity and both kinds of block. */
export function useAudience(
  period: Period,
  { enabled }: SectionEnabled = { enabled: true },
): UseQueryResult<AudienceResponse, DashboardQueryError> {
  const apiWindow = useDashboardWindow(period);
  return useQuery<AudienceResponse, DashboardQueryError>({
    queryKey: dashboardKeys.audience(apiWindow),
    queryFn: ({ signal }) => unwrap(fetchAudience(apiWindow, signal)),
    refetchInterval: pollWhileVisible(POLL.audience),
    enabled,
    ...SHARED,
  });
}

/** What came in, what went out, and what is left at each vendor. */
export function useFinance(
  period: Period,
  { enabled }: SectionEnabled = { enabled: true },
): UseQueryResult<FinanceResponse, DashboardQueryError> {
  const apiWindow = useDashboardWindow(period);
  return useQuery<FinanceResponse, DashboardQueryError>({
    queryKey: dashboardKeys.finance(apiWindow),
    queryFn: ({ signal }) => unwrap(fetchFinance(apiWindow, signal)),
    refetchInterval: pollWhileVisible(POLL.finance),
    enabled,
    ...SHARED,
  });
}

/** How fast, how reliably, where orders stand, and what is up. */
export function usePerformance(
  period: Period,
  { enabled }: SectionEnabled = { enabled: true },
): UseQueryResult<PerformanceResponse, DashboardQueryError> {
  const apiWindow = useDashboardWindow(period);
  return useQuery<PerformanceResponse, DashboardQueryError>({
    queryKey: dashboardKeys.performance(apiWindow),
    queryFn: ({ signal }) => unwrap(fetchPerformance(apiWindow, signal)),
    refetchInterval: pollWhileVisible(POLL.performance),
    enabled,
    ...SHARED,
  });
}

/**
 * Every chart on the page, at the grain asked for.
 *
 * A grain the window cannot honestly serve comes back as a 422 naming `bucket` — never a
 * silent coarsening — and 422 is on the no-retry list, so the refusal reaches the chart on
 * the first attempt instead of after three identical ones. `granFor` picks the DEFAULT pair
 * legally and `isGranLegal` filters what the toggle offers, so the refusal should be
 * unreachable from the UI; it is still handled, because a stale tab can outlive a settings
 * change.
 */
export function useSeries(
  period: Period,
  gran: Gran,
  { enabled }: SectionEnabled = { enabled: true },
): UseQueryResult<SeriesResponse, DashboardQueryError> {
  const apiWindow = useDashboardWindow(period);
  const bucket = bucketFor(gran);
  return useQuery<SeriesResponse, DashboardQueryError>({
    queryKey: dashboardKeys.series(apiWindow, bucket),
    queryFn: ({ signal }) => unwrap(fetchSeries(apiWindow, bucket, signal)),
    refetchInterval: pollWhileVisible(POLL.series),
    enabled,
    ...SHARED,
  });
}

/**
 * Which vendor the money went to, in what units, and how each figure was arrived at.
 *
 * Its own query on its own key, landing independently of `finance` even though the two
 * republish `vendorSpend` and `vendorBalances` from the same server functions: a vendor
 * section that waited on the finance read would blank the balance meters every time the
 * heavier response was in flight, and gating either on the other is exactly the coupling the
 * four-route split exists to avoid. They are asked for the SAME window, so the two answers
 * agree by contract.
 */
export function useVendor(
  period: Period,
  { enabled }: SectionEnabled = { enabled: true },
): UseQueryResult<VendorResponse, DashboardQueryError> {
  const apiWindow = useDashboardWindow(period);
  return useQuery<VendorResponse, DashboardQueryError>({
    queryKey: dashboardKeys.vendor(apiWindow),
    queryFn: ({ signal }) => unwrap(fetchVendor(apiWindow, signal)),
    refetchInterval: pollWhileVisible(POLL.vendor),
    enabled,
    ...SHARED,
  });
}

/**
 * What the running plans owe, and how fully the ended ones were used.
 *
 * **Takes no period and is given no window** — the route accepts neither, liability is a
 * state rather than a flow, and the two figures it feeds print the response's own `asOf`
 * instead. The hook's signature is where wiring the page's range picker to it is made
 * impossible: there is no parameter to wire.
 */
export function usePlans(
  { enabled }: SectionEnabled = { enabled: true },
): UseQueryResult<PlanLiabilityResponse, DashboardQueryError> {
  return useQuery<PlanLiabilityResponse, DashboardQueryError>({
    queryKey: dashboardKeys.plans(),
    queryFn: ({ signal }) => unwrap(fetchPlans(signal)),
    refetchInterval: pollWhileVisible(POLL.plans),
    enabled,
    ...SHARED,
  });
}

/**
 * The two IDENTIFIED lists — `RECORDS_READ`, unmasked, and **audited on every call**.
 *
 * Three things make this hook different from every other read on the page, and all three are
 * deliberate:
 *
 * **It does not poll.** No `refetchInterval`, and `refetchOnWindowFocus`/`refetchOnReconnect`
 * are turned off against the client's defaults. Each call writes a disclosure row, and a row
 * that says "an admin looked at customer identities" must mean somebody actually looked. The
 * long `staleTime` is the same argument continued: a remount inside one session should reuse
 * the answer rather than buy a second row for one look. An operator who wants a newer list
 * refetches this query by hand.
 *
 * **A 403 here is an EXPECTED outcome**, not a page failure: this permission is narrower than
 * the one the rest of the dashboard runs on, so a role can legitimately hold `DASHBOARD_READ`
 * and not `RECORDS_READ`. It is already terminal in `shouldRetry` — three identical refusals
 * are three audit rows and no more information — and the caller renders it as this section's
 * own denial beside four aggregate sections that answered fine.
 *
 * **The window narrows `topGenerators` only.** The parameter is named for the block it
 * applies to, exactly as the fetcher's is; `recentSubscribers` comes back captioned "the last
 * N" and there is no parameter on this route that would filter it.
 */
export function useAudienceLists(
  topGeneratorsPeriod: Period,
  limit: number = DEFAULT_AUDIENCE_LIST_LIMIT,
  { enabled }: SectionEnabled = { enabled: true },
): UseQueryResult<AudienceListsResponse, DashboardQueryError> {
  const apiWindow = useDashboardWindow(topGeneratorsPeriod);
  return useQuery<AudienceListsResponse, DashboardQueryError>({
    queryKey: dashboardKeys.audienceLists(apiWindow, limit),
    queryFn: ({ signal }) => unwrap(fetchAudienceLists(apiWindow, limit, signal)),
    // Not `pollWhileVisible(false)` but the absence of an interval: there is no cadence to
    // express here, and a reader looking for one should find nothing rather than a switch.
    refetchInterval: false,
    refetchOnWindowFocus: false,
    refetchOnReconnect: false,
    staleTime: AUDIENCE_LISTS_STALE_MS,
    enabled,
    ...SHARED,
  });
}

/** The deployment as a whole. Takes no window, and the fastest thing on the page. */
export function usePulse(): UseQueryResult<PulseView, DashboardQueryError> {
  return useQuery<PulseView, DashboardQueryError>({
    queryKey: dashboardKeys.pulse(),
    queryFn: ({ signal }) => unwrap(fetchPulse(signal)),
    refetchInterval: pollWhileVisible(POLL.pulse),
    ...SHARED,
  });
}

/* -------------------------------------------------------------------------- */
/* The header chip                                                             */
/* -------------------------------------------------------------------------- */

export interface Liveness {
  /** At least one dashboard read is in flight right now. */
  readonly isFetching: boolean;
  /** When the newest number on the page arrived. `null` before anything has succeeded. */
  readonly lastUpdatedAt: Date | null;
}

/**
 * What the `LIVE` pill should say, rather than what it is drawn as.
 *
 * The mock's pill is a decoration reading `LIVE · 5s`, which is true of nothing on the page
 * except `/ops/pulse` and stays true even when the API has been unreachable for a minute.
 * This reports the two facts a reader actually needs: whether anything is being fetched, and
 * when the freshest answer landed. The age is taken across ALL six reads, so a stalled
 * `finance` cannot make the page look stale while the charts are ticking, and a stalled
 * charts query cannot hide behind a healthy pulse either — it is the NEWEST update, and the
 * per-section staleness belongs on the section, not in the header.
 *
 * Read through `useSyncExternalStore` on the query cache rather than from a hook per query:
 * `dataUpdatedAt` moves without any observer re-rendering, and a header that only refreshed
 * when some card happened to change would be a clock that stops whenever the numbers do.
 */
export function useLiveness(): Liveness {
  const cache = useQueryClient().getQueryCache();

  const subscribe = useCallback(
    (onStoreChange: () => void) =>
      cache.subscribe(() => {
        onStoreChange();
      }),
    [cache],
  );
  const getSnapshot = useCallback(() => newestUpdatedAt(cache), [cache]);
  const updatedAtMs = useSyncExternalStore(subscribe, getSnapshot, getSnapshot);

  const isFetching = useIsFetching({ queryKey: dashboardKeys.all }) > 0;

  return useMemo(
    () => ({
      isFetching,
      lastUpdatedAt: updatedAtMs === 0 ? null : new Date(updatedAtMs),
    }),
    [isFetching, updatedAtMs],
  );
}

/**
 * The newest successful `dataUpdatedAt` among the dashboard's queries, or `0` for none.
 *
 * A number and not a `Date`, because `useSyncExternalStore` compares snapshots by identity
 * and a fresh `Date` every read is a fresh identity every read — an infinite render loop.
 * Only `success` counts: `dataUpdatedAt` does not move on a failed tick, which is exactly the
 * property that lets the age keep climbing while the API is down.
 */
function newestUpdatedAt(cache: QueryCache): number {
  let newest = 0;
  for (const query of cache.getAll()) {
    if (query.queryKey[0] !== DASHBOARD_ROOT) continue;
    if (query.state.status !== "success") continue;
    if (query.state.dataUpdatedAt > newest) newest = query.state.dataUpdatedAt;
  }
  return newest;
}
