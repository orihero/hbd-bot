/**
 * The rail section's seven reads and three writes, as hooks.
 *
 * `api/billing.ts` fetches and `lib/adminQuery.ts` holds the shared error, retry policy and
 * option bundles; this is the layer between them, and it makes four decisions the screens
 * depend on.
 *
 * **The status polls; the records do not.** The pause switch is a control an operator watches
 * during an incident, so {@link useRailStatus} refreshes on {@link RAIL_POLL_MS}. The payments
 * list, the dossier and the journal use `LIST_READ`/`SUBJECT_READ`, which carry no timer at
 * all: rows reshuffling under a cursor mid-read is worse than rows a few seconds old, and a
 * dossier is a thing somebody is reading carefully with a customer on the phone.
 *
 * **Polling stops while the pause dialog is open.** The status is what the dialog is about, and
 * a value that changes underneath a confirmation is a confirmation about something else. The
 * screen passes `isLive: false` rather than this module guessing, because only the screen
 * knows a dialog is open — a hook that tried to infer it would be a second source of truth
 * for a piece of UI state that lives in one component.
 *
 * **The two switch writes SET the status cache from their own response.** The handler re-reads
 * the Redis key after writing it, so the response is strictly more current than any follow-up
 * GET could be — and seeding it is what makes a pause feel like it took effect rather than
 * like it might have. Only `isPaused` is replaced; every probe and the last inbound call are
 * left exactly as they were, because a pause changed none of them and re-rendering them as
 * "unknown" for one frame would be a lie in the other direction.
 *
 * **The notify invalidates the dossier, the lists AND the attention counters.** It enqueues a
 * job; `notified_at` is stamped by the WORKER, seconds later, inside `mark_intent_notified`'s
 * `WHERE notified_at IS NULL`. So the row does not change synchronously and there is nothing to
 * seed — invalidating is a round trip that asks again in a moment, which is honest, where a
 * `setQueryData` would assert a stamp that has not been written. The payments LIST is
 * invalidated too, because `notifiedAt` is a column on it and `?attention=paid_unnotified` is a
 * filter over it — and the attention counters for exactly the same reason, since
 * `paidNeverAnnounced` counts that same population from the same predicate.
 *
 * **The two aggregates are windowed differently, because the server windows them differently.**
 * The funnel takes the screen's date range, so the strip above the table answers the question
 * the table is answering. The attention counters take NO window ever — a payment stuck last
 * Tuesday is still stuck today, and scoping those counts to a date picker would hide exactly
 * the rows they exist to find. That asymmetry is on the wire (`getAttention` has no `from`), and
 * it is mirrored here rather than smoothed over: one key carries the window, the other cannot.
 */

import {
  useMutation,
  useQuery,
  useQueryClient,
  type UseMutationResult,
  type UseQueryResult,
} from "@tanstack/react-query";

import {
  getAttention,
  getIntentDossier,
  getIntentLookup,
  getRailFunnel,
  getRailStatus,
  listCalls,
  listIntents,
  postIntentNotify,
  postRailPause,
  postRailResume,
  type Attention,
  type BillingWindowQuery,
  type CallFilters,
  type CallPage,
  type IntentDossier,
  type IntentFilters,
  type IntentLookup,
  type IntentPage,
  type LookupQuery,
  type NotifyEnqueued,
  type NotifyRequest,
  type RailFunnel,
  type RailStatus,
  type RailSwitch,
  type RailSwitchRequest,
} from "@/api/billing";
import type { CountedPageRequest } from "@/api/pagination";
import {
  LIST_READ,
  PRIVILEGED_WRITE,
  SUBJECT_READ,
  countedPageKey,
  filterKey,
  requireSubject,
  unwrap,
  type AdminQueryError,
  type CountedPageKey,
  type FilterKey,
} from "@/lib/adminQuery";

/* -------------------------------------------------------------------------- */
/* Keys                                                                        */
/* -------------------------------------------------------------------------- */

const RAIL_ROOT = "rail";

/**
 * The canonical projection of {@link IntentFilters}.
 *
 * `staleAfterHours` is in the key only when `attention` is `awaiting_stale`, exactly as
 * `listIntents` only sends it then: a key that recorded a parameter the request did not carry
 * would make one URL two cache entries, and the second would go stale unnoticed.
 */
export function intentsFilterKey(filters: IntentFilters): FilterKey {
  return filterKey({
    state: filters.state,
    product: filters.product,
    settledBy: filters.settledBy,
    attention: filters.attention,
    sandbox: filters.sandbox,
    from: filters.from,
    to: filters.to,
    staleAfterHours: filters.attention === "awaiting_stale" ? filters.staleAfterHours : null,
  });
}

/**
 * The canonical projection of a windowed aggregate's range.
 *
 * `filterKey` drops a null or empty bound, which is what makes "the whole record" ONE cache
 * entry however the screen spelled it — and it matters more here than on a list, because an
 * unwindowed funnel is a genuinely different answer from a windowed one (`window` comes back
 * `null` rather than as a pair of instants) and two keys for it would leave one of them stale
 * and nobody looking at it.
 */
export function railWindowKey(window: BillingWindowQuery): FilterKey {
  return filterKey({ from: window.from, to: window.to });
}

/** The same projection for the inbound journal. */
export function callsFilterKey(filters: CallFilters): FilterKey {
  return filterKey({
    method: filters.method,
    faultsOnly: filters.faultsOnly === true ? true : null,
    ref: filters.ref,
    transactionId: filters.transactionId,
    from: filters.from,
    to: filters.to,
  });
}

/**
 * The key factory.
 *
 * Shaped so everything about ONE payment hangs under `payment(id)` while the list keys sit
 * beside it: a notify must be able to re-read one dossier and the lists without touching the
 * polled status.
 */
export const railKeys = {
  all: [RAIL_ROOT] as const,
  status: () => [RAIL_ROOT, "status"] as const,
  /** Every filtered page of payments, whatever the filters. What a write invalidates. */
  intentLists: () => [RAIL_ROOT, "intents"] as const,
  intents: (filters: IntentFilters, page: CountedPageRequest) =>
    [RAIL_ROOT, "intents", intentsFilterKey(filters), countedPageKey(page)] as const,
  callLists: () => [RAIL_ROOT, "calls"] as const,
  calls: (filters: CallFilters, page: CountedPageRequest) =>
    [RAIL_ROOT, "calls", callsFilterKey(filters), countedPageKey(page)] as const,
  /** Every window of the funnel. What a write that moves a COUNT would invalidate. */
  funnels: () => [RAIL_ROOT, "funnel"] as const,
  funnel: (window: BillingWindowQuery) =>
    [RAIL_ROOT, "funnel", railWindowKey(window)] as const,
  /**
   * The three populations an operator can act on. No window in the key, because there is none
   * on the wire — see the module header. One entry, which is why a write can invalidate it by
   * name rather than by prefix.
   */
  attention: () => [RAIL_ROOT, "attention"] as const,
  /** Everything held about one payment. */
  payment: (intentId: string | null) => [RAIL_ROOT, "payment", intentId] as const,
  dossier: (intentId: string | null) => [RAIL_ROOT, "payment", intentId, "dossier"] as const,
  /** A reference typed into the lookup box, not a payment. Keyed on what was typed. */
  lookup: (query: LookupQuery) =>
    [RAIL_ROOT, "lookup", filterKey({ ref: query.ref, transactionId: query.transactionId })] as const,
} as const;

export type RailKeys = typeof railKeys;

/** Re-exported so a screen can type a key it holds without importing the plumbing. */
export type { CountedPageKey, FilterKey };

/* -------------------------------------------------------------------------- */
/* Cadence                                                                     */
/* -------------------------------------------------------------------------- */

/**
 * How often the toolbar re-reads the pause switch.
 *
 * Fifteen seconds: slow enough that a screen left open all afternoon is four requests a
 * minute against one cheap read, fast enough that an operator who has just paused the rail —
 * or whose colleague has — sees it without reaching for Refresh.
 *
 * `refetchIntervalInBackground` stays at its default `false` everywhere below: a hidden tab is
 * not being read, and a console left open overnight should cost nothing.
 */
export const RAIL_POLL_MS = 15_000;

/* -------------------------------------------------------------------------- */
/* The switch                                                                  */
/* -------------------------------------------------------------------------- */

/**
 * The rail's current state. The list reads one field of it — `isPaused`, which decides whether
 * the toolbar offers Pause or Resume.
 *
 * `isLive` is the screen's, not this module's: the list turns it off while the pause dialog is
 * open, so the value a confirmation is about cannot move underneath it.
 */
export function useRailStatus(isLive = true): UseQueryResult<RailStatus, AdminQueryError> {
  return useQuery<RailStatus, AdminQueryError>({
    queryKey: railKeys.status(),
    queryFn: ({ signal }) => unwrap(getRailStatus(signal)),
    ...LIST_READ,
    refetchInterval: isLive ? RAIL_POLL_MS : false,
  });
}

/* -------------------------------------------------------------------------- */
/* The records                                                                 */
/* -------------------------------------------------------------------------- */

/**
 * One keyset page of payments, newest first, with the chain per row and the probes inside the
 * envelope.
 *
 * No timer: this is a filtered ledger somebody is reading, and `LIST_READ`'s freshness signal
 * is the operator looking at the tab. Read `isPlaceholderData` and DIM the rows — while the
 * next filter or cursor loads, what is on screen is the PREVIOUS answer, and presenting it at
 * full contrast under the new chips is the one failure a table cannot recover from.
 */
export function useIntents(
  filters: IntentFilters,
  page: CountedPageRequest = {},
): UseQueryResult<IntentPage, AdminQueryError> {
  return useQuery<IntentPage, AdminQueryError>({
    queryKey: railKeys.intents(filters, page),
    queryFn: ({ signal }) => unwrap(listIntents(filters, page, signal)),
    ...LIST_READ,
  });
}

/** One keyset page of the inbound journal, newest first. */
export function useCalls(
  filters: CallFilters,
  page: CountedPageRequest = {},
): UseQueryResult<CallPage, AdminQueryError> {
  return useQuery<CallPage, AdminQueryError>({
    queryKey: railKeys.calls(filters, page),
    queryFn: ({ signal }) => unwrap(listCalls(filters, page, signal)),
    ...LIST_READ,
  });
}

/**
 * One payment's dossier: the intent, every transaction, the receipt, the ledger, the calls,
 * the lifeline and where the chain stops.
 *
 * `SUBJECT_READ` rather than `LIST_READ`, and the difference is not cosmetic: keeping the
 * previous payment's data on screen across a subject change would leave one customer's masked
 * buyer, amount and receipt under another payment's reference for as long as the fetch takes.
 * A dimmed row in a table is honest; a dimmed IDENTITY is a misidentification.
 *
 * `null` means nothing is selected and the query is disabled rather than fired at a
 * placeholder id.
 */
export function useIntentDossier(
  intentId: string | null,
): UseQueryResult<IntentDossier, AdminQueryError> {
  return useQuery<IntentDossier, AdminQueryError>({
    queryKey: railKeys.dossier(intentId),
    queryFn: ({ signal }) => unwrap(getIntentDossier(requireSubject(intentId), signal)),
    enabled: intentId !== null,
    ...SUBJECT_READ,
  });
}

/**
 * A reference resolved to a payment, or an honest not-found.
 *
 * Disabled until the box holds something well-formed, because the three outcomes must stay
 * three: a malformed reference is a form that says so, and firing the request anyway would
 * turn a typo into a 422 banner that reads exactly like "no such payment". `SUBJECT_READ` for
 * its `placeholderData`: the previous reference's answer must not sit under a new one.
 */
export function useIntentLookup(
  query: LookupQuery,
  isEnabled: boolean,
): UseQueryResult<IntentLookup, AdminQueryError> {
  return useQuery<IntentLookup, AdminQueryError>({
    queryKey: railKeys.lookup(query),
    queryFn: ({ signal }) => unwrap(getIntentLookup(query, signal)),
    enabled: isEnabled,
    ...SUBJECT_READ,
    // A reference either matches or it does not, and asking again cannot change that. The
    // freshness signal here is the operator typing a different reference.
    refetchOnWindowFocus: false,
  });
}

/* -------------------------------------------------------------------------- */
/* The aggregates                                                              */
/* -------------------------------------------------------------------------- */

/**
 * Where a window's payments got to, on both sides of the rail, plus the RPC volume.
 *
 * `dashboard.read`, which `permissions.py` gives to every role including VIEWER — so unlike the
 * pause switch there is nothing to hide here and no `rbac.ts` cell to mirror. A caller that
 * gated this on a role would be stricter than the server for no gain.
 *
 * `LIST_READ`, so a window change SWAPS the figures instead of blanking them; the caller reads
 * `isPlaceholderData` and must not present the previous window's counts as this one's. There is
 * no timer, for the same reason the list has none: the figures above a ledger somebody is
 * reading should not move while they read it, and the freshness signal is the tab regaining
 * focus.
 *
 * Both count fields are SPARSE `{state, count}` lists — a state with no rows is absent, never
 * zero — so a caller sums or selects a state; it must not index a fixed set of bars.
 */
export function useRailFunnel(
  window: BillingWindowQuery,
): UseQueryResult<RailFunnel, AdminQueryError> {
  return useQuery<RailFunnel, AdminQueryError>({
    queryKey: railKeys.funnel(window),
    queryFn: ({ signal }) => unwrap(getRailFunnel(window, signal)),
    ...LIST_READ,
  });
}

/**
 * The three populations an operator can act on, as of one instant.
 *
 * The cutoff is deliberately NOT passed: the server's default is the one every unqualified
 * reader sees, and threading the list's `staleAfterHours` in here would make the strip's total
 * move when somebody edited a filter chip — a count of what is stuck would then depend on what
 * the operator happened to be looking at. The chip that carries a cutoff into `?attention=` is
 * a different question, asked of the LIST, and it keeps its own answer.
 *
 * No timer here either, and the reason is the invalidation below rather than indifference: the
 * one write in this console that moves `paidNeverAnnounced` is the notify, and it invalidates
 * this key by name. A poll would be asking the server to tell us what our own mutation already
 * knows.
 */
export function useAttention(): UseQueryResult<Attention, AdminQueryError> {
  return useQuery<Attention, AdminQueryError>({
    queryKey: railKeys.attention(),
    queryFn: ({ signal }) => unwrap(getAttention(undefined, signal)),
    ...LIST_READ,
  });
}

/* -------------------------------------------------------------------------- */
/* The writes                                                                  */
/* -------------------------------------------------------------------------- */

/**
 * Pause or resume the checkout rail.
 *
 * One hook for both directions, because they are two directions of one idempotent write
 * against one Redis key — the SAME key `bayram.payme.pause` reads and the bot's checkout
 * provider consults. There is deliberately no second mechanism: two would give two answers to
 * "is the rail paused".
 *
 * No step-up, and no retry. The failures this actually hits are `FORBIDDEN` (needs a different
 * role) and `SERVICE_UNAVAILABLE` (the write to Redis failed, which the server refuses to
 * paper over) — neither is fixed by asking again, and each attempt is another audit row.
 */
export function useRailSwitch(): UseMutationResult<
  RailSwitch,
  AdminQueryError,
  { readonly paused: boolean; readonly body: RailSwitchRequest }
> {
  const queryClient = useQueryClient();
  return useMutation<
    RailSwitch,
    AdminQueryError,
    { readonly paused: boolean; readonly body: RailSwitchRequest }
  >({
    mutationFn: ({ paused, body }) =>
      unwrap(paused ? postRailPause(body) : postRailResume(body)),
    onSuccess: (result) => {
      // Only `isPaused` is replaced, and only when a status is already cached. Everything else
      // on that view — the probes, the last inbound call, the measured cashbox — is unchanged
      // by a pause, and re-rendering it from a response that does not carry it would blank
      // facts the operator is reading beside the switch.
      queryClient.setQueryData<RailStatus>(railKeys.status(), (previous) =>
        previous === undefined ? previous : { ...previous, isPaused: result.isPaused },
      );
    },
    ...PRIVILEGED_WRITE,
  });
}

/**
 * Re-send one payment's confirmation.
 *
 * Invalidates the dossier, the payments lists and the attention counters, and seeds nothing:
 * the worker stamps `notified_at`, not this response, so a `setQueryData` here would assert a
 * fact that has not been written yet. A 409 carrying `details.refusalCode` is the server
 * re-checking the three refusals the dossier already published — read it with
 * `notifyRefusalOf`, never by casting.
 */
export function useNotifyPayment(): UseMutationResult<
  NotifyEnqueued,
  AdminQueryError,
  { readonly intentId: string; readonly body: NotifyRequest }
> {
  const queryClient = useQueryClient();
  return useMutation<
    NotifyEnqueued,
    AdminQueryError,
    { readonly intentId: string; readonly body: NotifyRequest }
  >({
    mutationFn: ({ intentId, body }) => unwrap(postIntentNotify(intentId, body)),
    onSuccess: (_result, variables) => {
      void queryClient.invalidateQueries({ queryKey: railKeys.payment(variables.intentId) });
      void queryClient.invalidateQueries({ queryKey: railKeys.intentLists() });
      /*
       * And the attention counters, because `paidNeverAnnounced` is the one figure in this
       * console that THIS mutation moves. It counts the same population as
       * `?attention=paid_unnotified` — paid, and never announced — from the same predicate, so
       * a notify that refreshed the rows and left the counts alone would leave a strip reading
       * "3 need attention" directly above a table that has just dropped to two. Of the two
       * surfaces the stale one is the one an operator trusts, because it is the one they can
       * read without scrolling.
       *
       * The funnel is deliberately NOT invalidated. It counts intents and rail-side
       * transactions by STATE and the RPC volume; a re-sent confirmation changes none of them —
       * `notified_at` appears in no term of it — so invalidating it would be a round trip that
       * can only return the same numbers, on a route that runs four grouped counts and three
       * probes against the payments table.
       */
      void queryClient.invalidateQueries({ queryKey: railKeys.attention() });
    },
    ...PRIVILEGED_WRITE,
  });
}
