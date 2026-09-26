/**
 * The Users screen's six reads and three privileged writes, as hooks.
 *
 * `api/users.ts` fetches and `lib/adminQuery.ts` holds the shared error, retry policy and
 * option bundles; this is the layer between them, and it makes four decisions the screen
 * depends on.
 *
 * **The filters and the cursor are IN the key.** A key that carried only "users" would show
 * the previous filter's rows under the new chips and page one's rows under every cursor —
 * relabelling instead of refetching, which is the failure a table cannot recover from because
 * nothing on screen looks wrong. `filterKey` also collapses the spellings the serialiser
 * treats as identical, so an unfiltered list is one cache entry and not four.
 *
 * **No timer.** These are records an operator reads, not a dashboard. `LIST_READ` sets
 * `refetchInterval: false` and leans on `refetchOnWindowFocus`: the operator looking back at
 * the tab is the freshness signal, and rows that reshuffle under a cursor mid-read are worse
 * than rows ten seconds old.
 *
 * **Invalidation is narrow.** A block moves one flag on one person; a grant moves three
 * numbers on one account. Neither touches orders, wizard drafts or the generation ledger, and
 * each hook below says exactly what it invalidates and why.
 *
 * **A grant's idempotency key belongs to the PRESS, not to the call.** `beginCreditGrant`
 * mints it once and the mutation never mints one; a retry — after a step-up round trip, after
 * a timeout — resends the same attempt object and the server answers `isReplay: true` with
 * nothing moved. A key minted per call would turn one retried timeout into two grants, which
 * is real vendor spend.
 */

import {
  useMutation,
  useQuery,
  useQueryClient,
  type QueryClient,
  type UseMutationResult,
  type UseQueryResult,
} from "@tanstack/react-query";

import { FIRST_PAGE, type CountedPageRequest, type PageRequest } from "@/api/pagination";
import type { ReasonedRequest } from "@/api/reveal";
import {
  blockUser,
  getUser,
  getUserCredits,
  getUserOrders,
  getUsersStats,
  getWizardState,
  grantCredits,
  listUsers,
  newRequestId,
  unblockUser,
  POPULATION_NEUTRAL,
  type CreditGrantRequest,
  type CreditGrantResultView,
  type CreditLedgerPage,
  type OrdersPage,
  type UserBlockRequest,
  type UserBlockResultView,
  type UserDetailView,
  type UsersFilters,
  type UsersPage,
  type UserStatsView,
  type WizardStateView,
} from "@/api/users";
import {
  LIST_READ,
  PRIVILEGED_WRITE,
  SUBJECT_READ,
  countedPageKey,
  filterKey,
  onlyWhenAsked,
  pageKey,
  requireSubject,
  unwrap,
  type AdminQueryError,
  type CountedPageKey,
  type FilterKey,
  type PageKey,
} from "@/lib/adminQuery";

/* -------------------------------------------------------------------------- */
/* Keys                                                                        */
/* -------------------------------------------------------------------------- */

const USERS_ROOT = "users";

/**
 * The canonical projection of `UsersFilters`.
 *
 * Every filter the request carries is here — an omitted one would be a cache entry serving
 * rows nobody asked for. `withTotal` goes through `onlyWhenAsked` because `withTotal=false`
 * is never sent, and `uiLanguage` is sorted because OR within a field has no order.
 */
export function usersFilterKey(filters: UsersFilters): FilterKey {
  return filterKey({
    withTotal: onlyWhenAsked(filters.withTotal),
    telegramUserId: filters.telegramUserId,
    q: filters.q,
    isBlocked: filters.isBlocked,
    hasBalance: filters.hasBalance,
    uiLanguage: filters.uiLanguage,
    from: filters.from,
    to: filters.to,
    // The base64url TOKEN, which is what makes this key agree with `segmentKeys.preview(token)`
    // and with the `?segment=` in the address bar: `encodeSegment` is byte-stable, so one
    // audience is one cache entry however many times its document was rebuilt in a render.
    segment: filters.segment,
    // The ordering is part of the question, not a view over the answer. A key that dropped it
    // would serve the rows of one ordering under the headers of another — and would hand the
    // walk a cursor minted for a different `ORDER BY`, which is a 422 at best.
    sort: filters.sort,
    sortDir: filters.sortDir,
  });
}

/**
 * The projection the STAT STRIP is keyed on — the list's filters, narrowed.
 *
 * **`sort` and `sortDir` are dropped, and the list's key deliberately keeps them.** That is not
 * an inconsistency between two keys; it is the difference between two questions. "How many
 * accounts does this filter set select, and how many of them can we reach?" has one answer
 * however the rows beneath it are ordered — so keying the strip on the ordering would throw the
 * cached answer away and refetch the identical four numbers on every press of a column heading,
 * flickering a figure an operator is mid-sentence about for nothing. The list's own key cannot
 * do that: its rows ARE ordered, and a cursor minted under one `ORDER BY` is not a position in
 * another (`usersFilterKey` says so beside the two fields).
 *
 * `withTotal` goes for the same reason it is stripped in `getUsersStats`: it asks the list for
 * a bounded count this route does not take, so it changes nothing about the answer and must not
 * change the key that stores it.
 *
 * Everything else is shared with `usersFilterKey` rather than restated — the six chips, the
 * window and the segment token are what narrows BOTH, so a filter added to one is in the other.
 * `POPULATION_NEUTRAL` is the same constant `getUsersStats` spreads on the way to the wire, so
 * the key cannot describe a request different from the one that was actually sent.
 */
export function usersStatsFilterKey(filters: UsersFilters): FilterKey {
  return usersFilterKey({ ...filters, ...POPULATION_NEUTRAL });
}

/**
 * The key factory.
 *
 * Shaped so that everything about ONE person hangs under `user(id)` while `detail(id)` stays
 * a leaf: a block must refresh the person's record without also re-reading their orders, and
 * that is only expressible if the detail key is not a prefix of the sub-list keys.
 */
export const usersKeys = {
  all: [USERS_ROOT] as const,
  /** Every filtered page, whatever the filters. What a write invalidates when membership moves. */
  lists: () => [USERS_ROOT, "list"] as const,
  list: (filters: UsersFilters, page: PageRequest) =>
    [USERS_ROOT, "list", usersFilterKey(filters), pageKey(page)] as const,
  /**
   * Every filter set's counts. A SIBLING of `lists()`, not a child of one: the strip is one
   * answer about a whole filtered population and the list is a walk through it, so neither
   * prefix should invalidate the other by accident — a cursor turn must not refetch counts that
   * did not move, and a write that moves the counts says so explicitly, right below.
   */
  statsAll: () => [USERS_ROOT, "stats"] as const,
  stats: (filters: UsersFilters) =>
    [USERS_ROOT, "stats", usersStatsFilterKey(filters)] as const,
  /** Everything held about one person. */
  user: (telegramUserId: number | null) => [USERS_ROOT, "user", telegramUserId] as const,
  detail: (telegramUserId: number | null) =>
    [USERS_ROOT, "user", telegramUserId, "detail"] as const,
  /** All pages of this person's orders — the prefix a write would invalidate as a set. */
  ordersOf: (telegramUserId: number | null) =>
    [USERS_ROOT, "user", telegramUserId, "orders"] as const,
  orders: (telegramUserId: number | null, page: CountedPageRequest) =>
    [USERS_ROOT, "user", telegramUserId, "orders", countedPageKey(page)] as const,
  /** The balance and one page of movements are ONE response, so ONE key. */
  creditsOf: (telegramUserId: number | null) =>
    [USERS_ROOT, "user", telegramUserId, "credits"] as const,
  credits: (telegramUserId: number | null, page: CountedPageRequest) =>
    [USERS_ROOT, "user", telegramUserId, "credits", countedPageKey(page)] as const,
  /** Redis-backed and never 404s — a stuck customer can have a draft and no `users` row. */
  wizardState: (telegramUserId: number | null) =>
    [USERS_ROOT, "user", telegramUserId, "wizard-state"] as const,
} as const;

export type UsersKeys = typeof usersKeys;

/** Re-exported so a screen can type a key it holds without importing the plumbing. */
export type { CountedPageKey, FilterKey, PageKey };

/* -------------------------------------------------------------------------- */
/* The reads                                                                   */
/* -------------------------------------------------------------------------- */

/**
 * One keyset page of users, newest account first.
 *
 * `q` searches the Telegram id and nothing else; the placeholder and empty state must say so.
 * Read `isPlaceholderData` from the result: while the next filter or cursor loads, the rows on
 * screen are the PREVIOUS answer and must be dimmed rather than presented as this one's.
 */
export function useUsers(
  filters: UsersFilters,
  page: PageRequest = FIRST_PAGE,
): UseQueryResult<UsersPage, AdminQueryError> {
  return useQuery<UsersPage, AdminQueryError>({
    queryKey: usersKeys.list(filters, page),
    queryFn: ({ signal }) => unwrap(listUsers(filters, page, signal)),
    ...LIST_READ,
  });
}

/**
 * What the filtered population is made of: matched, reachable, and the two refusals.
 *
 * One request per FILTER SET, not per page: the key carries no cursor and no ordering, so a
 * walk through the table and a press of a column heading both reuse the answer already on
 * screen. The three counts besides `matched` overlap — read `UserStatsView` before adding any
 * two of them together.
 *
 * `LIST_READ` for the same reasons the list takes it, and `keepPreviousData` matters here:
 * while a new filter set loads, the previous counts stay up rather than blinking to skeletons
 * and back. They are the PREVIOUS narrowing's answer for that moment, which is exactly what the
 * dimmed rows below them are.
 */
export function useUsersStats(
  filters: UsersFilters,
): UseQueryResult<UserStatsView, AdminQueryError> {
  return useQuery<UserStatsView, AdminQueryError>({
    queryKey: usersKeys.stats(filters),
    queryFn: ({ signal }) => unwrap(getUsersStats(filters, signal)),
    ...LIST_READ,
  });
}

/**
 * One person's record and their per-state order breakdown.
 *
 * `null` means nothing is selected — the query is disabled rather than fired against a
 * placeholder id. A 404 here means we hold nothing at all under this id, which is a different
 * sentence from "this customer has never ordered".
 */
export function useUser(
  telegramUserId: number | null,
): UseQueryResult<UserDetailView, AdminQueryError> {
  return useQuery<UserDetailView, AdminQueryError>({
    queryKey: usersKeys.detail(telegramUserId),
    queryFn: ({ signal }) => unwrap(getUser(requireSubject(telegramUserId), signal)),
    enabled: telegramUserId !== null,
    ...SUBJECT_READ,
  });
}

/** This person's orders, newest first. A 404 is "no such id", never "no orders". */
export function useUserOrders(
  telegramUserId: number | null,
  page: CountedPageRequest = FIRST_PAGE,
): UseQueryResult<OrdersPage, AdminQueryError> {
  return useQuery<OrdersPage, AdminQueryError>({
    queryKey: usersKeys.orders(telegramUserId, page),
    queryFn: ({ signal }) => unwrap(getUserOrders(requireSubject(telegramUserId), page, signal)),
    enabled: telegramUserId !== null,
    // A sub-list still pages, so the previous page stays on screen — dimmed — while the next
    // arrives. The subject cannot change without the parent panel changing with it.
    ...LIST_READ,
  });
}

/**
 * This account's balance and one page of its movements.
 *
 * `account: null` is not a balance of zero — it is "no `credit_accounts` row", a third value,
 * and the grant button is exactly what opens one.
 */
export function useUserCredits(
  telegramUserId: number | null,
  page: CountedPageRequest = FIRST_PAGE,
): UseQueryResult<CreditLedgerPage, AdminQueryError> {
  return useQuery<CreditLedgerPage, AdminQueryError>({
    queryKey: usersKeys.credits(telegramUserId, page),
    queryFn: ({ signal }) => unwrap(getUserCredits(requireSubject(telegramUserId), page, signal)),
    enabled: telegramUserId !== null,
    ...LIST_READ,
  });
}

/**
 * The live wizard draft, projected to presence and lengths.
 *
 * Never 404s: `isStatePresent: false` is the normal state of everyone not mid-flow, and an
 * absent draft may simply mean the abandoned-draft sweep ran.
 */
export function useWizardState(
  telegramUserId: number | null,
): UseQueryResult<WizardStateView, AdminQueryError> {
  return useQuery<WizardStateView, AdminQueryError>({
    queryKey: usersKeys.wizardState(telegramUserId),
    queryFn: ({ signal }) => unwrap(getWizardState(requireSubject(telegramUserId), signal)),
    enabled: telegramUserId !== null,
    ...SUBJECT_READ,
  });
}

/* -------------------------------------------------------------------------- */
/* The writes                                                                  */
/* -------------------------------------------------------------------------- */

/**
 * What block and unblock are asked with.
 *
 * The body is passed in whole and kept by the caller, so a `STEP_UP_REQUIRED` can be retried
 * with byte-identical bytes once the password round trip succeeds — a reason that changed
 * between the refusal and the retry would audit one thing and do another.
 */
export interface UserBlockVariables {
  readonly telegramUserId: number;
  readonly body: UserBlockRequest;
}

/**
 * Bar this Telegram account from the bot.
 *
 * Expect `STEP_UP_REQUIRED` on the first attempt — the scope is `user.block:{telegramUserId}`
 * with the id as bare decimal digits — and drive `POST /api/auth/step-up` from the refusal's
 * details rather than from anything reconstructed here. There is no 404 and no conflict code:
 * the write is an idempotent upsert, so blocking an already-blocked account answers 200.
 * OPERATOR+ only; hide the button for the roles that would only ever get a 403.
 */
export function useBlockUser(): UseMutationResult<
  UserBlockResultView,
  AdminQueryError,
  UserBlockVariables
> {
  const queryClient = useQueryClient();
  return useMutation<UserBlockResultView, AdminQueryError, UserBlockVariables>({
    mutationFn: ({ telegramUserId, body }) => unwrap(blockUser(telegramUserId, body)),
    onSuccess: (_result, variables) => {
      invalidateBlockState(queryClient, variables.telegramUserId);
    },
    ...PRIVILEGED_WRITE,
  });
}

/** Lift the bar. A separate route and a separate audit action, invalidating the same two things. */
export function useUnblockUser(): UseMutationResult<
  UserBlockResultView,
  AdminQueryError,
  UserBlockVariables
> {
  const queryClient = useQueryClient();
  return useMutation<UserBlockResultView, AdminQueryError, UserBlockVariables>({
    mutationFn: ({ telegramUserId, body }) => unwrap(unblockUser(telegramUserId, body)),
    onSuccess: (_result, variables) => {
      invalidateBlockState(queryClient, variables.telegramUserId);
    },
    ...PRIVILEGED_WRITE,
  });
}

/**
 * What a block changes, and nothing else.
 *
 * `isBlocked` lives on `UserView`, which is on screen in exactly two places: this person's
 * detail, and any list page whose filters happen to contain them — and since `isBlocked` is
 * itself a filter, the row may now belong on a different page, so the lists go as a set. Their
 * orders, their ledger, their wizard draft and the whole generation ledger are untouched by a
 * block; invalidating those would be extra round trips claiming something moved that did not.
 *
 * The stat strip goes too, and it is the surface a block moves most visibly: `blocked` and
 * `reachable` are the flag this write just flipped, counted. A strip left stale would keep
 * stating a reachable population that includes the account an operator has just barred — which
 * is the number somebody sizes a broadcast from. The counts go as a SET, like the lists and for
 * the same reason: with `isBlocked` a filter, the account may have left or joined the narrowing
 * behind any cached filter set, not only the one on screen.
 *
 * Not awaited: the result view already carries the new state for the confirmation to render,
 * and holding the dialog's spinner up until every cached list page has refetched would make a
 * write feel like it failed.
 */
function invalidateBlockState(
  queryClient: QueryClient,
  telegramUserId: number,
): void {
  void queryClient.invalidateQueries({ queryKey: usersKeys.detail(telegramUserId) });
  void queryClient.invalidateQueries({ queryKey: usersKeys.lists() });
  void queryClient.invalidateQueries({ queryKey: usersKeys.statsAll() });
}

/**
 * The idempotency brand.
 *
 * Not exported, which is the point: a `CreditGrantAttempt` can only be built by
 * `beginCreditGrant`, so there is no way to hand `useGrantCredits` a body carrying a
 * `requestId` that was minted anywhere other than one press of the button.
 */
const CREDIT_GRANT_ATTEMPT = Symbol("credit-grant-attempt");

/** What one press of Grant asks for, `requestId` included. Built only by `beginCreditGrant`. */
export interface CreditGrantAttempt {
  readonly brand: typeof CREDIT_GRANT_ATTEMPT;
  readonly telegramUserId: number;
  /** 1..100 whole credits. One credit is one render, so the cap is a blast radius. */
  readonly credits: number;
  /** The audit reason, validated by the form before it is sent — a 422 writes no audit row. */
  readonly reason: ReasonedRequest;
  /** Minted once, here, and resent unchanged by every retry of this same press. */
  readonly requestId: string;
}

/** The attempt without its key — what a dialog actually knows when the operator confirms. */
export interface CreditGrantInput {
  readonly telegramUserId: number;
  readonly credits: number;
  readonly reason: ReasonedRequest;
}

/**
 * Mint one grant attempt. **Call this once per press**, when the confirm dialog is submitted,
 * and keep the result in component state.
 *
 * Everything that follows — a `STEP_UP_REQUIRED` and its password round trip, a timeout, an
 * operator pressing Retry — must pass that SAME object back to `mutate`, so the server sees
 * one `requestId` and answers the second call `isReplay: true` with nothing moved. Minting per
 * call instead would make a retried timeout a second grant. A genuinely new decision to comp
 * the same customer again calls this again, because two decisions are two grants.
 */
export function beginCreditGrant(input: CreditGrantInput): CreditGrantAttempt {
  return {
    brand: CREDIT_GRANT_ATTEMPT,
    telegramUserId: input.telegramUserId,
    credits: input.credits,
    reason: input.reason,
    requestId: newRequestId(),
  };
}

/**
 * Add credits to one account on an operator's say-so.
 *
 * Scoped step-up `credit.grant:{telegramUserId}`, OPERATOR+, and no 404 — the writer opens an
 * account that has never been metered, which is exactly the customer a goodwill comp is for.
 * A `CreditGrantResultView` with `isReplay: true` is a SUCCESS in which nothing moved: print
 * that, and print `account.balance`, which was read back from the database rather than
 * computed.
 */
export function useGrantCredits(): UseMutationResult<
  CreditGrantResultView,
  AdminQueryError,
  CreditGrantAttempt
> {
  const queryClient = useQueryClient();
  return useMutation<CreditGrantResultView, AdminQueryError, CreditGrantAttempt>({
    mutationFn: (attempt) => {
      // The Telegram id is the path parameter and is deliberately NOT repeated in the body:
      // one answer to "who is being credited", the same one the step-up scope was built from.
      const body: CreditGrantRequest = {
        ...attempt.reason,
        credits: attempt.credits,
        requestId: attempt.requestId,
      };
      return unwrap(grantCredits(attempt.telegramUserId, body));
    },
    onSuccess: (_result, attempt) => {
      // Three reads carry a balance and all three move: the ledger and its account object,
      // the detail's `creditBalance`/`lifetimeCreditsGranted`/`creditsProjected`, and the
      // list's balance column — where `hasBalance` is also a filter, so membership can move
      // too. Nothing else does: a grant changes no order, no draft and no generation attempt.
      //
      // Invalidated on a replay as well. Nothing moved THEN, but the cached figures may
      // predate the original grant, and `account.balance` is the only figure the ledger agrees
      // with.
      void queryClient.invalidateQueries({ queryKey: usersKeys.creditsOf(attempt.telegramUserId) });
      void queryClient.invalidateQueries({ queryKey: usersKeys.detail(attempt.telegramUserId) });
      void queryClient.invalidateQueries({ queryKey: usersKeys.lists() });
      // The strip too, for the membership half of that sentence and not for the balance: no
      // count here reports credits, but `hasBalance` is a filter, so a grant can move an account
      // INTO a narrowing it was not in — and then `matched` and `reachable` are both a person
      // short of the rows now under them. Cheap, and the alternative is a strip that disagrees
      // with the table it captions until the next filter change.
      void queryClient.invalidateQueries({ queryKey: usersKeys.statsAll() });
    },
    ...PRIVILEGED_WRITE,
  });
}
