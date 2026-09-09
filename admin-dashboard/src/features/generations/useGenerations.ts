/**
 * The Generations screen's two reads, as hooks.
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
 * **There are no mutations here, and one deliberate absence.** Nothing on this surface writes,
 * and there is no key for a revealed transcript or name candidate: reading
 * `generation_attempts.stt_transcript` is a CHARGED, audited disclosure, and a cache entry is
 * a thing an invalidation can re-fetch without anybody asking. Reveal is driven as a mutation
 * from the dialog, so a second disclosure can only follow a second press.
 */

import { useQuery, type UseQueryResult } from "@tanstack/react-query";

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

/** The key factory. `detail` is a leaf under its own namespace; nothing here invalidates it. */
export const generationsKeys = {
  all: [GENERATIONS_ROOT] as const,
  lists: () => [GENERATIONS_ROOT, "list"] as const,
  list: (filters: GenerationsFilters, page: PageRequest) =>
    [GENERATIONS_ROOT, "list", generationsFilterKey(filters), pageKey(page)] as const,
  details: () => [GENERATIONS_ROOT, "detail"] as const,
  detail: (attemptId: string | null) => [GENERATIONS_ROOT, "detail", attemptId] as const,
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
