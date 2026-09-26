/**
 * The Audit screen's two reads, as hooks.
 *
 * `api/audit.ts` fetches and `lib/adminQuery.ts` holds the shared error, retry policy and
 * option bundles; this is the layer between them, and it makes three decisions the screen
 * depends on.
 *
 * **The filters and the cursor are IN the key.** Seven filters narrow this list and two of them
 * repeat, so a key that dropped one would leave the previous question's rows sitting under the
 * new chips. `filterKey` sorts the repeated values, because OR within a field has no order and
 * `action=logout&action=login.success` is not a second question.
 *
 * **The verify read is NOT a list read, and it does not share `LIST_READ`.** `verify_chain`
 * walks the table in batches of 500 up to a ceiling of 50 000 rows, recomputing an HMAC per
 * row. `LIST_READ` asks again on every window focus, which would re-walk the whole log every
 * time an operator alt-tabs back to the panel — a self-inflicted load on the one table nobody
 * can afford to make slow. So the verdict is fetched once per visit and thereafter only when
 * the operator presses "Check again": an integrity answer is a thing you take deliberately,
 * and it does not go stale in the ten seconds `RECORD_STALE_TIME_MS` is measuring.
 *
 * **There are no mutations here, and there will not be.** §6.8 ships no audit writes at all —
 * not even the anchor `/verify` could conveniently drop while it is already walking the chain,
 * because that would put a write behind a `GET` a browser prefetch can fire. Anchors are the
 * retention job's, on a schedule, in a transaction of its own.
 */

import { useQuery, type UseQueryResult } from "@tanstack/react-query";

import {
  listAudit,
  verifyAuditChain,
  type AuditFilters,
  type AuditPage,
  type ChainVerify,
} from "@/api/audit";
import { FIRST_PAGE, type PageRequest } from "@/api/pagination";
import {
  LIST_READ,
  SUBJECT_READ,
  filterKey,
  pageKey,
  unwrap,
  type AdminQueryError,
  type FilterKey,
} from "@/lib/adminQuery";

/* -------------------------------------------------------------------------- */
/* Keys                                                                        */
/* -------------------------------------------------------------------------- */

const AUDIT_ROOT = "audit";

/**
 * The canonical projection of `AuditFilters`.
 *
 * Every filter the request carries, and nothing else — there is no `withTotal` on this endpoint
 * to run through `onlyWhenAsked`, because `AuditPageMeta` carries a cursor and no count.
 */
export function auditFilterKey(filters: AuditFilters): FilterKey {
  return filterKey({
    actor: filters.actor,
    action: filters.action,
    subjectType: filters.subjectType,
    subjectId: filters.subjectId,
    outcome: filters.outcome,
    from: filters.from,
    to: filters.to,
  });
}

/**
 * The key factory.
 *
 * `verify` sits under its own segment rather than under `lists()`: it asks a different question
 * — whether the log has been edited — and no filter narrows it, so an invalidation of the list
 * must not drag a 50 000-row walk along with it.
 */
export const auditKeys = {
  all: [AUDIT_ROOT] as const,
  lists: () => [AUDIT_ROOT, "list"] as const,
  list: (filters: AuditFilters, page: PageRequest) =>
    [AUDIT_ROOT, "list", auditFilterKey(filters), pageKey(page)] as const,
  verify: () => [AUDIT_ROOT, "verify"] as const,
} as const;

export type AuditKeys = typeof auditKeys;

/* -------------------------------------------------------------------------- */
/* The reads                                                                   */
/* -------------------------------------------------------------------------- */

/**
 * One keyset page of the log, newest `seq` first.
 *
 * Read `isPlaceholderData`: while the next filter or cursor loads, the rows on screen are the
 * PREVIOUS answer and must be dimmed rather than presented under the new chips as this one's.
 *
 * `meta.total` is always `null` here — the endpoint counts nothing — so a range label must be
 * composed from what is on the page and from the walk this tab actually made.
 *
 * The two focus overrides are the same ones `features/admins/useAdmins.ts` argues at length,
 * and they are here because this route refuses the same way: `audit.read` is ADMIN and OWNER
 * only, the guard writes a `permission.denied` row before it raises, and the rail offers
 * `/audit` to SUPPORT and VIEWER on purpose. `shouldRetryRead` makes that 403 terminal for one
 * trigger; without these it would still be re-asked on every tab focus and every reconnect,
 * because a query holding no data is permanently stale and `RECORD_STALE_TIME_MS` cannot gate
 * it. One refusal per visit is the cost this console accepts. A stream of them is not.
 */
export function useAuditEntries(
  filters: AuditFilters,
  page: PageRequest = FIRST_PAGE,
): UseQueryResult<AuditPage, AdminQueryError> {
  return useQuery<AuditPage, AdminQueryError>({
    queryKey: auditKeys.list(filters, page),
    queryFn: ({ signal }) => unwrap(listAudit(filters, page, signal)),
    ...LIST_READ,
    refetchOnWindowFocus: (query) => query.state.status !== "error",
    refetchOnReconnect: (query) => query.state.status !== "error",
  });
}

/**
 * How long a chain verdict stands before the panel would ask again on its own: it does not.
 *
 * `Infinity` rather than a long number, and the difference is a claim. A number would say "this
 * answer expires", which invites a refetch nobody asked for; the truth is that a verdict is
 * about the rows that existed when it was taken, and the honest way to get a newer one is to
 * take a newer one — which is what the panel's button does.
 */
const VERIFY_STALE_TIME_MS = Number.POSITIVE_INFINITY;

/**
 * The chain verdict — `ok`, the first break if there is one, and what is protecting the log.
 *
 * `SUBJECT_READ` for its `placeholderData`: this is one answer about one table, and keeping the
 * previous verdict on screen while a new walk runs would leave a green "chain holds" standing
 * over a check that has not finished. The two overrides below are the whole reason this is not
 * `LIST_READ` — see the module header.
 *
 * Note what the retry policy already does for us: a 403 is terminal, and `ok: false` is a
 * SUCCESSFUL response carrying a serious finding, so it is never retried away. The server has
 * already logged `admin.audit.chain_broken` at ERROR by the time this resolves.
 */
export function useChainVerify(): UseQueryResult<ChainVerify, AdminQueryError> {
  return useQuery<ChainVerify, AdminQueryError>({
    queryKey: auditKeys.verify(),
    queryFn: ({ signal }) => unwrap(verifyAuditChain(signal)),
    ...SUBJECT_READ,
    refetchOnWindowFocus: false,
    // The client default is `true` and `SUBJECT_READ` says nothing about it, so this is the
    // other half of the sentence above: "once per visit, and then only on Check again". An
    // answered walk is never stale and would not refetch anyway — a REFUSED one has no data,
    // is therefore stale for ever, and would re-walk on every wifi blip, writing a
    // `permission.denied` row each time for a SUPPORT or VIEWER operator.
    refetchOnReconnect: false,
    staleTime: VERIFY_STALE_TIME_MS,
  });
}
