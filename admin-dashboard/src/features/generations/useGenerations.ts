/**
 * The Generations screen's three reads, as hooks.
 *
 * `api/generations.ts` fetches and `lib/adminQuery.ts` holds the shared error, retry policy
 * and option bundles; this is the layer between them, and it makes three decisions the screen
 * depends on.
 *
 * **The filters and the cursor are IN the key.** Seven kinds, nine adapters, an error code
 * and two tri-states: the render ledger is read almost entirely through its filters, so a key
 * that dropped one would leave the previous question's rows sitting under the new chips.
 * `filterKey` also collapses the spellings the serialiser treats as the same request, so the
 * unfiltered ledger is one cache entry.
 *
 * **No timer.** Attempts land continuously, but an operator scanning failures is reading, not
 * monitoring; rows that reshuffle under a cursor mid-read are worse than rows ten seconds old.
 * `refetchOnWindowFocus` — looking back at the tab — is the freshness signal. The dashboard is
 * where the live numbers live.
 *
 * **The stat strip is a THIRD query, and the permission is why.** `/api/generations` is
 * `RECORDS_READ`; `/api/metrics/name-analytics`, which answers the verification figures above
 * the table, is `DASHBOARD_READ`. The two are granted separately, so an operator can be
 * entitled to every row of the ledger and refused the aggregate over it — and a hook that
 * folded the two reads together would turn that refusal into an empty table. One query per
 * permission is what keeps the blast radius of a 403 to the tiles that asked for it.
 *
 * **There are no mutations here, and one deliberate absence.** Nothing on this surface writes,
 * and there is no key for a revealed transcript or name candidate: reading
 * `generation_attempts.stt_transcript` is a CHARGED, audited disclosure, and a cache entry is
 * a thing an invalidation can re-fetch without anybody asking. Reveal is driven as a mutation
 * from the dialog, so a second disclosure can only follow a second press.
 */

import { useQuery, type UseQueryResult } from "@tanstack/react-query";

import {
  nameAnalytics,
  type LedgerWindow,
  type NameAnalyticsView,
} from "@/api/dashboard";
import {
  getGeneration,
  listGenerations,
  type AttemptWireView,
  type AttemptsPage,
  type GenerationsFilters,
} from "@/api/generations";
import { FIRST_PAGE, type PageRequest } from "@/api/pagination";
import {
  LIST_READ,
  SUBJECT_READ,
  filterKey,
  onlyWhenAsked,
  pageKey,
  requireSubject,
  unwrap,
  type AdminQueryError,
  type FilterKey,
} from "@/lib/adminQuery";

/* -------------------------------------------------------------------------- */
/* Keys                                                                        */
/* -------------------------------------------------------------------------- */

const GENERATIONS_ROOT = "generations";

/**
 * The canonical projection of `GenerationsFilters`.
 *
 * Every filter the request carries. `kind` REPEATS on the wire and is sorted here, because OR
 * within a field has no order; `provider` and `errorCode` are free-form strings trimmed to
 * match what the serialiser sends; `withTotal` goes through `onlyWhenAsked` because
 * `withTotal=false` is never sent and a key that recorded it would split one request in two.
 */
export function generationsFilterKey(filters: GenerationsFilters): FilterKey {
  return filterKey({
    withTotal: onlyWhenAsked(filters.withTotal),
    kind: filters.kind,
    provider: filters.provider,
    isSuccess: filters.isSuccess,
    errorCode: filters.errorCode,
    strategy: filters.strategy,
    isOrphaned: filters.isOrphaned,
    from: filters.from,
    to: filters.to,
  });
}

/**
 * The verification read's key: the two instants, and deliberately nothing else.
 *
 * A key holds exactly what the REQUEST carries. `/api/metrics/name-analytics` accepts
 * `?from=&to=` and no other parameter, so putting the screen's six remaining filters in here
 * would mint a fresh cache entry every time an operator typed a provider — each one fetching,
 * and each one getting back the identical answer the previous entry already held. The
 * narrowing those filters do is real, it is just not something this route can be asked for;
 * see `nameAnalytics` in `api/dashboard.ts` on what that costs the screen rendering both.
 */
export function nameAnalyticsWindowKey(window: LedgerWindow): FilterKey {
  return filterKey({ from: window.from, to: window.to });
}

/** The key factory. `detail` is a leaf under its own namespace; nothing here invalidates it. */
export const generationsKeys = {
  all: [GENERATIONS_ROOT] as const,
  lists: () => [GENERATIONS_ROOT, "list"] as const,
  list: (filters: GenerationsFilters, page: PageRequest) =>
    [GENERATIONS_ROOT, "list", generationsFilterKey(filters), pageKey(page)] as const,
  details: () => [GENERATIONS_ROOT, "detail"] as const,
  detail: (attemptId: string | null) => [GENERATIONS_ROOT, "detail", attemptId] as const,
  /** Under this root rather than the dashboard's: it is windowed by the LEDGER's `?from=&to=`,
   * so it goes stale with this screen's filters and not with the dashboard's period picker. */
  nameAnalytics: (window: LedgerWindow) =>
    [GENERATIONS_ROOT, "name-analytics", nameAnalyticsWindowKey(window)] as const,
} as const;

export type GenerationsKeys = typeof generationsKeys;

/* -------------------------------------------------------------------------- */
/* The reads                                                                   */
/* -------------------------------------------------------------------------- */

/**
 * One keyset page of the render ledger, newest first.
 *
 * Read `isPlaceholderData`: while the next filter or cursor loads, the rows on screen are the
 * PREVIOUS answer and must be dimmed rather than presented under the new chips as this one's.
 *
 * `provider` on a row is free-form varchar — a new adapter renders as itself. `PROVIDER_VALUES`
 * is the picker's vocabulary only, and an over-long `provider`/`errorCode` is a 422 naming the
 * parameter, so cap the INPUT rather than truncating it into a page nobody asked for.
 */
export function useGenerations(
  filters: GenerationsFilters,
  page: PageRequest = FIRST_PAGE,
): UseQueryResult<AttemptsPage, AdminQueryError> {
  return useQuery<AttemptsPage, AdminQueryError>({
    queryKey: generationsKeys.list(filters, page),
    queryFn: ({ signal }) => unwrap(listGenerations(filters, page, signal)),
    ...LIST_READ,
  });
}

/**
 * One attempt by id, for the detail panel.
 *
 * `null` closes the panel and disables the query rather than firing against a placeholder id.
 * An id that matches nothing is a 404, never an empty body — so a stale link says "no such
 * attempt" instead of drawing an empty shell. `identityPurgedAt`/`textPurgedAt` are not
 * missing data: a non-null stamp renders "purged {date}" and NO reveal affordance, because a
 * reveal that cannot succeed is worse than no button.
 */
export function useGeneration(
  attemptId: string | null,
): UseQueryResult<AttemptWireView, AdminQueryError> {
  return useQuery<AttemptWireView, AdminQueryError>({
    queryKey: generationsKeys.detail(attemptId),
    queryFn: ({ signal }) => unwrap(getGeneration(requireSubject(attemptId), signal)),
    enabled: attemptId !== null,
    ...SUBJECT_READ,
  });
}

/**
 * The verification figures behind the screen's stat strip, over the ledger's own window.
 *
 * Its own query, for the permission reason in this module's header: this is `DASHBOARD_READ`
 * and the list beside it is `RECORDS_READ`. A 403 lands in `error` here and nowhere else, so
 * the table keeps its rows and the strip explains itself.
 *
 * **`keepPreviousData` is switched back off, and that is the one thing this bundle changes.**
 * `LIST_READ` carries it because a table can DIM the previous answer while the next one loads,
 * and a dimmed row is an honest "this is not the page you just asked for". A tile has no such
 * affordance: it is four characters in a large weight, and the previous window's pass rate
 * standing under the new window's dates is simply a wrong measurement with nothing on screen
 * saying so. A skeleton says less and says it truthfully — `SUBJECT_READ` refuses the same
 * option for the same reason, one identity instead of one figure.
 */
export function useNameAnalytics(
  window: LedgerWindow,
): UseQueryResult<NameAnalyticsView, AdminQueryError> {
  return useQuery<NameAnalyticsView, AdminQueryError>({
    queryKey: generationsKeys.nameAnalytics(window),
    queryFn: ({ signal }) => unwrap(nameAnalytics(window, signal)),
    ...LIST_READ,
    placeholderData: (): undefined => undefined,
  });
}
