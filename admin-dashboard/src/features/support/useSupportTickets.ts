/**
 * The Support screens' three reads and four writes, as hooks.
 *
 * `api/support.ts` fetches and `lib/adminQuery.ts` holds the shared error, retry policy and
 * option bundles; this is the layer between them, and it makes five decisions the screens
 * depend on. `useBroadcasts.ts` is the convention being followed — key factories, option
 * bundles, typed errors. `features/chats/useChats.ts` is the older, thinner one and is
 * deliberately not the model.
 *
 * **The filters are IN every key, the board's included.** The board takes the same filter set as
 * the list precisely so the two describe one population, which means a board cached under a
 * bare `"board"` key would show the previous filter's column lengths beside the new filter's
 * rows — relabelling instead of refetching, the failure a screen cannot recover from because
 * nothing on it looks wrong. `filterKey` also collapses the spellings the serialiser treats as
 * identical, so an unfiltered queue is one cache entry rather than four.
 *
 * **These reads do not poll, and that is a decision rather than an omission.** A ticket moves
 * when a customer replies or a staffer presses a button in the Telegram group — both other
 * processes — so there IS something to poll for, unlike a ledger of finished records. It is
 * still refused: a support queue is read for minutes at a time while an operator writes a
 * reply, and a board that re-ordered its columns under a half-typed answer would cost more than
 * the freshness buys. The freshness signal is the operator looking at the tab
 * (`refetchOnWindowFocus`), plus the invalidation every write here performs. If a poll is ever
 * added it belongs on the BOARD alone, never on a detail somebody is typing into.
 *
 * **Every mutation answers with the whole ticket, so the detail cache is SET rather than
 * re-fetched.** The server re-reads the row inside the transaction it just wrote in; that view
 * is more current than anything a follow-up GET could return, and seeding it is what makes a
 * move feel like it took effect rather than like it might have. The board and the lists are
 * invalidated instead, because a status change moves a card between columns and between
 * filtered pages.
 *
 * **No step-up, anywhere in this namespace.** `support.write` is a plain `W` — see
 * `api/support.ts` for the argument — so there is no `STEP_UP_REQUIRED` to catch, no dialog to
 * drive and no body to replay. What the screens DO have to handle is the `409` the status route
 * answers when a staffer moved the ticket from the group first ({@link useMoveSupportTicket}),
 * and the `503` the three enqueueing writes answer when no worker is running.
 *
 * **An optimistic board move is the caller's, not this layer's.** The hooks expose the plain
 * mutation; a board that moves a card before the server answers must hold its own rollback,
 * because only the board knows which column the card was drawn in and only the board can put it
 * back. Doing it here would mean this module owning a copy of the board's state.
 */

import {
  useMutation,
  useQuery,
  useQueryClient,
  type QueryClient,
  type UseMutationResult,
  type UseQueryResult,
} from "@tanstack/react-query";

import type { ApiResult } from "@/api/client";
import { FIRST_PAGE, type PageRequest } from "@/api/pagination";
import {
  addSupportTicketNote,
  assignSupportTicket,
  getSupportBoard,
  getSupportTicket,
  listSupportTickets,
  moveSupportTicket,
  replyToSupportTicket,
  type SupportBoardView,
  type SupportTicketDetailView,
  type SupportTicketsFilters,
  type SupportTicketsPage,
  type TicketAssignRequest,
  type TicketNoteRequest,
  type TicketReplyRequest,
  type TicketStatusRequest,
} from "@/api/support";
import {
  LIST_READ,
  PRIVILEGED_WRITE,
  SUBJECT_READ,
  filterKey,
  onlyWhenAsked,
  pageKey,
  requireSubject,
  unwrap,
  type AdminQueryError,
  type FilterKey,
  type PageKey,
} from "@/lib/adminQuery";

/* -------------------------------------------------------------------------- */
/* Keys                                                                        */
/* -------------------------------------------------------------------------- */

/**
 * The cache root every Support query hangs off — the tickets here, and the group directory in
 * `useSupportGroups.ts`.
 *
 * Exported for that sibling rather than re-spelled there, because two modules holding two
 * string literals that must be equal is a drift nobody notices: the two would stop sharing a
 * prefix, and an invalidation written as "everything about Support" would quietly stop reaching
 * half of it. Nothing invalidates the root today; the constant is what keeps that option
 * honest, and what makes the devtools show one tree instead of two.
 */
export const SUPPORT_ROOT = "support";

/**
 * The canonical projection of {@link SupportTicketsFilters}.
 *
 * Every filter the request carries is here — an omitted one would be a cache entry serving rows
 * nobody asked for. `withTotal` and `onlyDescribed` both go through `onlyWhenAsked`, because
 * neither is sent as `false`: the server defaults both, and `withTotal=false` on the wire would
 * be a second spelling of one request. The three repeated fields are sorted by `filterKey`,
 * because OR within a field has no order.
 */
export function supportTicketsFilterKey(filters: SupportTicketsFilters): FilterKey {
  return filterKey({
    withTotal: onlyWhenAsked(filters.withTotal),
    onlyDescribed: onlyWhenAsked(filters.onlyDescribed),
    status: filters.status,
    source: filters.source,
    language: filters.language,
    assignedTo: filters.assignedTo,
    telegramUserId: filters.telegramUserId,
    from: filters.from,
    to: filters.to,
    q: filters.q,
  });
}

/**
 * The board's projection of the same filters.
 *
 * Deliberately NOT `supportTicketsFilterKey` reused: the board sends no paging, no `withTotal`
 * and no `onlyDescribed` (it forces that one on server-side), so a key carrying them would make
 * "the board under this filter" two or four cache entries depending on which switches the list
 * beside it happened to be holding.
 */
export function supportBoardFilterKey(filters: SupportTicketsFilters): FilterKey {
  return filterKey({
    status: filters.status,
    source: filters.source,
    language: filters.language,
    assignedTo: filters.assignedTo,
    telegramUserId: filters.telegramUserId,
    from: filters.from,
    to: filters.to,
    q: filters.q,
  });
}

/**
 * The key factory.
 *
 * Shaped so `ticket(id)` is the prefix for everything about one ticket while `detail(id)` stays
 * a leaf — the `broadcastsKeys` shape, kept even though a ticket currently has exactly one
 * sub-read, because the timeline arrives inside the detail. If a ticket ever grows a paged
 * child (it should not — the timeline is unpaged on purpose), the prefix is already the right
 * shape and the detail is not a prefix of it.
 *
 * `boards()` and `lists()` are separate prefixes so a write can invalidate both as sets without
 * either one being able to invalidate the other by accident.
 */
export const supportKeys = {
  all: [SUPPORT_ROOT] as const,
  /** Every board, whatever the filters. What a status move invalidates. */
  boards: () => [SUPPORT_ROOT, "board"] as const,
  board: (filters: SupportTicketsFilters) =>
    [SUPPORT_ROOT, "board", supportBoardFilterKey(filters)] as const,
  /** Every filtered page, whatever the filters. */
  lists: () => [SUPPORT_ROOT, "list"] as const,
  list: (filters: SupportTicketsFilters, page: PageRequest) =>
    [SUPPORT_ROOT, "list", supportTicketsFilterKey(filters), pageKey(page)] as const,
  /** Everything held about one ticket. */
  ticket: (ticketId: string | null) => [SUPPORT_ROOT, "ticket", ticketId] as const,
  detail: (ticketId: string | null) => [SUPPORT_ROOT, "ticket", ticketId, "detail"] as const,
} as const;

export type SupportKeys = typeof supportKeys;

/** Re-exported so a screen can type a key it holds without importing the plumbing. */
export type { FilterKey, PageKey };

/* -------------------------------------------------------------------------- */
/* The reads                                                                   */
/* -------------------------------------------------------------------------- */

/**
 * The four column lengths, under the same filters as the queue beside them.
 *
 * **Exact counts, and described tickets only.** They are `GROUP BY` buckets rather than a page
 * total, so render them as plain numbers — `formatTotal`'s "at least" wording belongs to the
 * list. The board never counts a ticket nobody described, whatever the filter says, because a
 * column length that included rows with nothing to read would be a backlog number that lies.
 *
 * `LIST_READ` rather than `SUBJECT_READ`: this is a distribution over a population, and keeping
 * the previous filter's numbers on screen while the next load runs is honest as long as the
 * screen dims them (`isPlaceholderData`).
 */
export function useSupportBoard(
  filters: SupportTicketsFilters,
): UseQueryResult<SupportBoardView, AdminQueryError> {
  return useQuery<SupportBoardView, AdminQueryError>({
    queryKey: supportKeys.board(filters),
    queryFn: ({ signal }) => unwrap(getSupportBoard(filters, signal)),
    ...LIST_READ,
  });
}

/**
 * One keyset page of tickets, newest first, **with each customer's complaint on the row**.
 *
 * Read `isPlaceholderData` from the result: while the next filter or cursor loads, the rows on
 * screen are the PREVIOUS answer and must be dimmed rather than presented as this one's. That
 * matters more here than on any other list in the panel, because the thing being relabelled is
 * somebody's sentence about their own order.
 */
export function useSupportTickets(
  filters: SupportTicketsFilters,
  page: PageRequest = FIRST_PAGE,
): UseQueryResult<SupportTicketsPage, AdminQueryError> {
  return useQuery<SupportTicketsPage, AdminQueryError>({
    queryKey: supportKeys.list(filters, page),
    queryFn: ({ signal }) => unwrap(listSupportTickets(filters, page, signal)),
    ...LIST_READ,
  });
}

/**
 * One ticket and its whole timeline, oldest first.
 *
 * `null` means nothing is selected — the query is disabled rather than fired against a
 * placeholder id. A 404 means we hold no ticket under this id, and the refusal does not echo it
 * back.
 *
 * `SUBJECT_READ`, so the previous ticket's body never sits under the next ticket's header while
 * a fetch is in flight. A dimmed row in a table is honest; a dimmed COMPLAINT beside a reply box
 * is an operator about to answer the wrong customer.
 */
export function useSupportTicket(
  ticketId: string | null,
): UseQueryResult<SupportTicketDetailView, AdminQueryError> {
  return useQuery<SupportTicketDetailView, AdminQueryError>({
    queryKey: supportKeys.detail(ticketId),
    queryFn: ({ signal }) => unwrap(getSupportTicket(requireSubject(ticketId), signal)),
    enabled: ticketId !== null,
    ...SUBJECT_READ,
  });
}

/* -------------------------------------------------------------------------- */
/* The writes                                                                  */
/* -------------------------------------------------------------------------- */

/**
 * What every write about a ticket is asked with.
 *
 * The body is passed in whole and kept by the caller, which is the shape `BroadcastVariables`
 * takes for a step-up replay. There is no step-up here, and the shape is kept anyway for a
 * smaller reason that still bites: a `409` on a move is retried by the operator with a DIFFERENT
 * `expectedStatus`, and holding the variables object is what lets a dialog rebuild exactly the
 * one field that changed.
 */
export interface TicketVariables<TBody> {
  readonly ticketId: string;
  readonly body: TBody;
}

/**
 * Move a ticket between columns. **The one write with a refusal worth branching on.**
 *
 * `body.expectedStatus` must be the status the card was DRAWN in. A `409` means the row moved
 * first — almost always a staffer pressing `✋ Claim` or `✅ Resolve` on the card in the Telegram
 * group, which is a different process — and `ticketStatusConflictOf(failureOf(error))` unpacks
 * the status the server actually found. Roll the optimistic move back, show that status, and do
 * not retry: the same bytes lose the same race.
 *
 * A `422` is a move outside the grammar and should be unreachable, because a card offers only
 * `allowedTransitions`.
 *
 * A `503` is no worker: the enqueue is unwrapped server-side, so the whole move rolled back
 * rather than leaving this board and the group card permanently disagreeing about whether the
 * ticket is finished. Nothing was written; the operator presses again once the worker is up.
 */
export function useMoveSupportTicket(): UseMutationResult<
  SupportTicketDetailView,
  AdminQueryError,
  TicketVariables<TicketStatusRequest>
> {
  return useTicketWrite((variables) => moveSupportTicket(variables.ticketId, variables.body));
}

/**
 * Hand the ticket to an operator — possibly oneself.
 *
 * Unconditional on the current holder, so there is no conflict to handle: a reassignment must
 * not be refused because somebody claimed it first, and the append-only `assigned` event keeps
 * the history of who has had it. **It does not move the ticket**; claiming and moving are two
 * acts here because the operator has the column controls in front of them.
 */
export function useAssignSupportTicket(): UseMutationResult<
  SupportTicketDetailView,
  AdminQueryError,
  TicketVariables<TicketAssignRequest>
> {
  return useTicketWrite((variables) => assignSupportTicket(variables.ticketId, variables.body));
}

/**
 * Append an internal line to the timeline. **The customer never sees this.**
 *
 * The only write here that enqueues nothing and therefore the only one that cannot answer `503`.
 * It is also invisible to the staffers working from the card in the Telegram group — that is
 * what an internal note IS, and a screen should not imply otherwise.
 */
export function useAddSupportTicketNote(): UseMutationResult<
  SupportTicketDetailView,
  AdminQueryError,
  TicketVariables<TicketNoteRequest>
> {
  return useTicketWrite((variables) => addSupportTicketNote(variables.ticketId, variables.body));
}

/**
 * Answer the customer. **The one action on this surface that leaves the building.**
 *
 * The `reply` event on the response carries `relayedAt: null` — the worker stamps it when the
 * message actually reaches the customer's chat — so a screen must render "composed" and
 * "delivered" as different states and must never report the first as the second.
 *
 * The relay job is keyed on the event id, so a double-clicked Send collapses onto the job
 * already queued rather than putting the same paragraph in somebody's phone twice. Disable the
 * button while `isPending` regardless: the second press still writes a second event, and the
 * timeline would show the same answer twice.
 */
export function useReplyToSupportTicket(): UseMutationResult<
  SupportTicketDetailView,
  AdminQueryError,
  TicketVariables<TicketReplyRequest>
> {
  return useTicketWrite((variables) => replyToSupportTicket(variables.ticketId, variables.body));
}

/* -------------------------------------------------------------------------- */
/* What the four ticket writes share                                           */
/* -------------------------------------------------------------------------- */

/**
 * Every write here is the same shape: one call, one `SupportTicketDetailView` back, one cache
 * seed, two invalidations.
 *
 * Written once because four copies of an invalidation rule drift apart one endpoint at a time,
 * and the drift here would be a board still showing a card in `new` after somebody resolved it.
 */
function useTicketWrite<TBody>(
  call: (variables: TicketVariables<TBody>) => Promise<ApiResult<SupportTicketDetailView>>,
): UseMutationResult<SupportTicketDetailView, AdminQueryError, TicketVariables<TBody>> {
  const queryClient = useQueryClient();
  return useMutation<SupportTicketDetailView, AdminQueryError, TicketVariables<TBody>>({
    mutationFn: (variables) => unwrap(call(variables)),
    onSuccess: (detail) => {
      seedTicket(queryClient, detail);
    },
    ...PRIVILEGED_WRITE,
  });
}

/**
 * What every ticket write changes, and nothing else.
 *
 * The response IS the ticket, re-read by the handler from the transaction it just wrote in — so
 * the detail cache is SET rather than invalidated: a follow-up GET could only return the same
 * rows or older ones, and the round trip would hold a dialog's spinner up over a write that
 * already landed.
 *
 * The lists and the boards go as SETS rather than as one entry each. `status` is itself a filter
 * and the board is four counts over the same population, so a move can take a card off the page
 * it was read from, out of one column and into another — and a NOTE, which changes neither,
 * still bumps `updatedAt` and `eventCount`, both of which a row renders. Invalidating the two
 * prefixes costs one refetch of what is mounted and nothing at all for what is not.
 *
 * Not awaited: `no-floating-promises` is on, so the discard is explicit with `void`. The
 * returned view already carries everything a confirmation needs to render, and awaiting a
 * refetch would make the dialog wait on a list nobody is looking at.
 */
function seedTicket(queryClient: QueryClient, detail: SupportTicketDetailView): void {
  queryClient.setQueryData(supportKeys.detail(detail.ticket.id), detail);
  void queryClient.invalidateQueries({ queryKey: supportKeys.boards() });
  void queryClient.invalidateQueries({ queryKey: supportKeys.lists() });
}
