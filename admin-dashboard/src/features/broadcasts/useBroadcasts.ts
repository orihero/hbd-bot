/**
 * The Broadcasts screens' four reads and seven writes, as hooks.
 *
 * `api/broadcasts.ts` fetches and `lib/adminQuery.ts` holds the shared error, retry policy and
 * option bundles; this is the layer between them, and it makes five decisions the screens depend
 * on.
 *
 * **The filters and the cursor are IN the key.** A key that carried only "broadcasts" would show
 * the previous filter's rows under the new chips and page one's rows under every cursor —
 * relabelling instead of refetching, which is the failure a table cannot recover from because
 * nothing on screen looks wrong. `filterKey` also collapses the spellings the serialiser treats as
 * identical, so an unfiltered list is one cache entry and not four.
 *
 * **These lists poll, and only while something is moving.** This is the one namespace in the panel
 * whose rows change WITHOUT anybody in the panel doing anything: a worker is delivering forty
 * thousand messages and the counters climb under the reader. So the interval is a function of the
 * data rather than a flag a screen sets — {@link BROADCAST_POLL_MS} while any campaign on the page
 * is expanding, sending or waiting on a schedule, and `false` the moment nothing is. A timer that
 * kept running over a table of completed campaigns would be a request every five seconds, for
 * ever, for a number that cannot change; a timer a screen had to remember to stop is one somebody
 * forgets. `refetchIntervalInBackground` stays false — a hidden tab is not being read.
 *
 * **The strip polls on the LIST's liveness, not on its own.** `useBroadcastStats` is an aggregate
 * over the whole filter set and carries no campaign state it could read a verdict out of: a total
 * and a last-send instant look identical whether a worker is delivering or the deployment has been
 * asleep for a week. So the caller derives {@link hasBroadcastInFlight} from the list query it has
 * already paid for and hands it in — the same clock, one decision, taken where the evidence is.
 * The gate is the point rather than the interval: an IDLE DEPLOYMENT MUST MAKE NO REQUESTS AT ALL,
 * and a strip that polled unconditionally would be a request every five seconds, for ever, on
 * every tab left open on this screen, for four numbers that cannot move until somebody composes a
 * campaign — and composing one invalidates the key anyway.
 *
 * **Every mutation answers with the campaign, so the detail cache is SET rather than re-fetched.**
 * The server re-reads the row from the transaction it just wrote in; that view is more current
 * than anything a follow-up GET would return, and seeding it is what makes a pause feel like it
 * took effect rather than like it might have. The LIST is invalidated instead, because a state
 * change can move a row between filtered pages.
 *
 * **The send needs a step-up and this layer does not take one.** `useSendBroadcast` surfaces the
 * `STEP_UP_REQUIRED` as an `AdminQueryError`; the dialog reads `stepUpTargetOf(failureOf(error))`,
 * runs `StepUpDialog` with `subjectId` VERBATIM from the refusal, and replays the identical body —
 * the `GrantCreditsDialog` pattern, unchanged. Do not rebuild the body between the refusal and the
 * retry: the reason that reaches the audit row must be the reason the operator authorised.
 *
 * **Recipients are not invalidated by any write here.** A pause sets a column; a cancel stops the
 * next chunk. Neither rewrites the ledger synchronously — the worker does, over the following
 * seconds — so invalidating those pages would be a round trip claiming something moved that has
 * not moved yet. The poll is what brings them.
 */

import {
  useMutation,
  useQuery,
  useQueryClient,
  type QueryClient,
  type UseMutationResult,
  type UseQueryResult,
} from "@tanstack/react-query";

import {
  cancelBroadcast,
  createBroadcast,
  getBroadcast,
  getBroadcastStats,
  listBroadcastRecipients,
  listBroadcasts,
  pauseBroadcast,
  resumeBroadcast,
  reviseBroadcast,
  sendBroadcast,
  testSendBroadcast,
  type BroadcastCreateRequest,
  type BroadcastDetailView,
  type BroadcastRecipientsFilters,
  type BroadcastRecipientsPage,
  type BroadcastReviseRequest,
  type BroadcastSendRequest,
  type BroadcastState,
  type BroadcastStatsView,
  type BroadcastTestSendRequest,
  type BroadcastTestSendResultView,
  type BroadcastView,
  type BroadcastsFilters,
  type BroadcastsPage,
  type BroadcastsStatsFilters,
} from "@/api/broadcasts";
import type { ApiResult } from "@/api/client";
import { FIRST_PAGE, type PageRequest } from "@/api/pagination";
import type { ReasonedRequest } from "@/api/reveal";
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

const BROADCASTS_ROOT = "broadcasts";

/**
 * The canonical projection of {@link BroadcastsFilters}.
 *
 * Every filter the request carries is here — an omitted one would be a cache entry serving rows
 * nobody asked for. `withTotal` goes through `onlyWhenAsked` because `withTotal=false` is never
 * sent, and the two repeated fields are sorted because OR within a field has no order.
 */
export function broadcastsFilterKey(filters: BroadcastsFilters): FilterKey {
  return filterKey({
    withTotal: onlyWhenAsked(filters.withTotal),
    state: filters.state,
    kind: filters.kind,
    from: filters.from,
    to: filters.to,
    q: filters.q,
  });
}

/**
 * The same projection for the strip, and `withTotal` is deliberately not in it.
 *
 * The strip's request does not carry the flag — its `total` is the exact sum of the segments —
 * so a key that carried it would be two cache entries in front of one URL, and the second would
 * sit there going stale behind a screen that had asked for a bounded count it never receives.
 * Every other field is the list's, because the two describe the same set of campaigns.
 */
export function broadcastsStatsFilterKey(filters: BroadcastsStatsFilters): FilterKey {
  return filterKey({
    state: filters.state,
    kind: filters.kind,
    from: filters.from,
    to: filters.to,
    q: filters.q,
  });
}

/** The same projection for one campaign's ledger. There is no window here and no `q`. */
export function broadcastRecipientsFilterKey(filters: BroadcastRecipientsFilters): FilterKey {
  return filterKey({
    withTotal: onlyWhenAsked(filters.withTotal),
    state: filters.state,
    language: filters.language,
    telegramUserId: filters.telegramUserId,
  });
}

/**
 * The key factory.
 *
 * Shaped so everything about ONE campaign hangs under `campaign(id)` while `detail(id)` stays a
 * leaf: a pause must refresh the campaign record without also re-reading forty thousand recipient
 * rows, and that is only expressible if the detail key is not a prefix of the ledger keys.
 */
export const broadcastsKeys = {
  all: [BROADCASTS_ROOT] as const,
  /** Every filtered page, whatever the filters. What a write invalidates when a state moves. */
  lists: () => [BROADCASTS_ROOT, "list"] as const,
  list: (filters: BroadcastsFilters, page: PageRequest) =>
    [BROADCASTS_ROOT, "list", broadcastsFilterKey(filters), pageKey(page)] as const,
  /**
   * Every filter set's strip — the SIBLING of `lists()`, never a child of it.
   *
   * A sibling because the aggregate is not part of any page: it survives a cursor turn untouched,
   * and hanging it under a list key would make paging invalidate four numbers that did not move,
   * while `lists()` — invalidated by every write — would drag the strip along with it whether or
   * not the write could have changed a segment. Two prefixes, invalidated together on purpose by
   * `seedCampaign` and independently by nothing.
   */
  stats: () => [BROADCASTS_ROOT, "stats"] as const,
  statsOf: (filters: BroadcastsStatsFilters) =>
    [BROADCASTS_ROOT, "stats", broadcastsStatsFilterKey(filters)] as const,
  /** Everything held about one campaign. */
  campaign: (broadcastId: string | null) => [BROADCASTS_ROOT, "campaign", broadcastId] as const,
  detail: (broadcastId: string | null) =>
    [BROADCASTS_ROOT, "campaign", broadcastId, "detail"] as const,
  /** All pages of this campaign's ledger — the prefix a write would invalidate as a set. */
  recipientsOf: (broadcastId: string | null) =>
    [BROADCASTS_ROOT, "campaign", broadcastId, "recipients"] as const,
  recipients: (
    broadcastId: string | null,
    filters: BroadcastRecipientsFilters,
    page: PageRequest,
  ) =>
    [
      BROADCASTS_ROOT,
      "campaign",
      broadcastId,
      "recipients",
      broadcastRecipientsFilterKey(filters),
      pageKey(page),
    ] as const,
} as const;

export type BroadcastsKeys = typeof broadcastsKeys;

/** Re-exported so a screen can type a key it holds without importing the plumbing. */
export type { FilterKey, PageKey };

/* -------------------------------------------------------------------------- */
/* Liveness — what makes these lists poll, and what stops them                 */
/* -------------------------------------------------------------------------- */

/**
 * How often a campaign that is moving is re-read.
 *
 * Fast enough that a send looks live, slow enough that a screen left open on a two-hour campaign
 * costs a request every five seconds rather than every one. It is not a deadline: the counters are
 * a worker's rollup and were already a moment old when the response was built.
 */
export const BROADCAST_POLL_MS = 5_000;

/**
 * The states in which a campaign changes on its own.
 *
 * `ready` is in the set because a campaign scheduled for later moves to `sending` with nobody
 * touching the panel — the due sweep starts it — and a screen that stopped polling at `ready` would
 * show a scheduled campaign as never having started.
 *
 * `draft` is deliberately absent, and not because a draft is quiet: `create_broadcast` inserts
 * `expanding` directly, so there is no state in which a campaign exists and its recipients have
 * not begun to be materialised. `draft` stays in the enum for the panel's benefit and no campaign
 * this API returns is ever in it.
 */
export const IN_FLIGHT_BROADCAST_STATES: readonly BroadcastState[] = [
  "ready",
  "expanding",
  "sending",
  "paused",
];

/**
 * Whether this campaign is one the server is still moving.
 *
 * `paused` counts: the chunk job settles rows it had already claimed after the brake goes on, so
 * the counters keep climbing for a few seconds and an operator who just pressed Pause is watching
 * exactly those seconds.
 */
export function isBroadcastInFlight(broadcast: BroadcastView): boolean {
  return !broadcast.isTerminal && IN_FLIGHT_BROADCAST_STATES.includes(broadcast.state);
}

/**
 * Whether any campaign on this page is moving. `undefined` — nothing loaded yet — is not.
 *
 * Exported because the STRIP is gated on it too, and that gate has to be derived from the list:
 * an aggregate of totals carries no state to read a verdict out of. A screen that holds both
 * queries computes this once and hands the boolean to {@link useBroadcastStats}, so the two
 * cannot end up polling on different verdicts about the same campaigns.
 *
 * Not loaded is deliberately NOT in flight: a page that has never arrived is no evidence that
 * anything is moving, and starting a timer on a guess is how a screen that should be silent ends
 * up asking for ever.
 */
export function hasBroadcastInFlight(page: BroadcastsPage | undefined): boolean {
  return page !== undefined && page.items.some(isBroadcastInFlight);
}

/* -------------------------------------------------------------------------- */
/* The reads                                                                   */
/* -------------------------------------------------------------------------- */

/**
 * One keyset page of campaigns, newest composed first. **One row per campaign, never per
 * recipient.**
 *
 * Polls only while a campaign on the page is in flight — see this module's header. Read
 * `isPlaceholderData` from the result: while the next filter or cursor loads, the rows on screen
 * are the PREVIOUS answer and must be dimmed rather than presented as this one's.
 */
export function useBroadcasts(
  filters: BroadcastsFilters,
  page: PageRequest = FIRST_PAGE,
): UseQueryResult<BroadcastsPage, AdminQueryError> {
  return useQuery<BroadcastsPage, AdminQueryError>({
    queryKey: broadcastsKeys.list(filters, page),
    queryFn: ({ signal }) => unwrap(listBroadcasts(filters, page, signal)),
    ...LIST_READ,
    // After the spread, deliberately: `LIST_READ` writes `refetchInterval: false` as a decision
    // for the record screens, and this is the one namespace that overrides it.
    refetchInterval: (query) => (hasBroadcastInFlight(query.state.data) ? BROADCAST_POLL_MS : false),
  });
}

/**
 * The strip above the campaign list: campaigns per state, what they reached, and the last send.
 *
 * One read for the WHOLE filter set, which is why it takes no page. Its `total` is exact where the
 * list's `meta.total` saturates at the server's cap, so a screen that draws both is drawing one
 * number twice and disagreeing with itself above ten thousand campaigns — draw this one.
 *
 * `isAnyInFlight` comes from the list, through {@link hasBroadcastInFlight}, and is the whole of
 * what decides whether this polls. Passed in rather than derived here for the reason in the module
 * header: this response cannot tell a busy deployment from a sleeping one, and an idle deployment
 * must make no requests at all.
 *
 * A failure belongs to the STRIP and to nothing else on the screen. The list beside it is a
 * separate query with its own error, and four missing figures must not blank a table that arrived:
 * render the tiles as absent with a reason, leave the rows where they are.
 */
export function useBroadcastStats(
  filters: BroadcastsStatsFilters,
  isAnyInFlight = false,
): UseQueryResult<BroadcastStatsView, AdminQueryError> {
  return useQuery<BroadcastStatsView, AdminQueryError>({
    queryKey: broadcastsKeys.statsOf(filters),
    queryFn: ({ signal }) => unwrap(getBroadcastStats(filters, signal)),
    ...LIST_READ,
    // After the spread, both of them deliberately.
    //
    // `keepPreviousData` is right for a TABLE and wrong for four big numbers. A dimmed row is
    // honest because the screen can dim it; a total has no such affordance, so the previous
    // filter's figures would sit under the new chips at full contrast and be read as this
    // filter's. Blanking to a skeleton says "not yet" in the one channel that cannot be misread.
    placeholderData: (): undefined => undefined,
    // The list's clock, on the list's verdict. `false` is not an optimisation here — it is the
    // difference between a screen left open costing nothing and costing a request every five
    // seconds until the tab is closed.
    refetchInterval: isAnyInFlight ? BROADCAST_POLL_MS : false,
  });
}

/**
 * One campaign: its bodies as Telegram will see them, its frozen filter, and both counts of the
 * funnel.
 *
 * `null` means nothing is selected — the query is disabled rather than fired against a placeholder
 * id. A 404 means we hold no campaign under this id, and the refusal does not echo it back.
 *
 * `SUBJECT_READ` rather than `LIST_READ`, so the previous campaign's bodies never sit under the
 * next campaign's header while a fetch is in flight: a dimmed row in a table is honest, dimmed
 * COPY that is about to be sent to forty thousand people is a misreading waiting to happen.
 */
export function useBroadcast(
  broadcastId: string | null,
): UseQueryResult<BroadcastDetailView, AdminQueryError> {
  return useQuery<BroadcastDetailView, AdminQueryError>({
    queryKey: broadcastsKeys.detail(broadcastId),
    queryFn: ({ signal }) => unwrap(getBroadcast(requireSubject(broadcastId), signal)),
    enabled: broadcastId !== null,
    ...SUBJECT_READ,
    refetchInterval: (query) => {
      const detail = query.state.data;
      return detail !== undefined && isBroadcastInFlight(detail.broadcast)
        ? BROADCAST_POLL_MS
        : false;
    },
  });
}

/**
 * This campaign's ledger, paged and masked. Every row, including the erased ones.
 *
 * There is **no 404** on this route: it is a filtered collection, and an empty page is the right
 * answer to a filter that matched nothing rather than a claim about the campaign. The detail query
 * beside it is what answers "does this campaign exist".
 *
 * Polled on the same clock as the rest of the screen while the campaign is moving — pass
 * `isCampaignInFlight` from the detail, because this response carries no campaign state of its own
 * and a ledger cannot tell "still pending" from "finished and this is the final answer".
 */
export function useBroadcastRecipients(
  broadcastId: string | null,
  filters: BroadcastRecipientsFilters,
  page: PageRequest = FIRST_PAGE,
  isCampaignInFlight = false,
): UseQueryResult<BroadcastRecipientsPage, AdminQueryError> {
  return useQuery<BroadcastRecipientsPage, AdminQueryError>({
    queryKey: broadcastsKeys.recipients(broadcastId, filters, page),
    queryFn: ({ signal }) =>
      unwrap(listBroadcastRecipients(requireSubject(broadcastId), filters, page, signal)),
    enabled: broadcastId !== null,
    ...LIST_READ,
    refetchInterval: isCampaignInFlight ? BROADCAST_POLL_MS : false,
  });
}

/* -------------------------------------------------------------------------- */
/* The writes                                                                  */
/* -------------------------------------------------------------------------- */

/**
 * What every write about an EXISTING campaign is asked with.
 *
 * The body is passed in whole and kept by the caller, so a `STEP_UP_REQUIRED` can be retried with
 * byte-identical bytes once the password round trip succeeds — a reason that changed between the
 * refusal and the retry would audit one thing and authorise another.
 */
export interface BroadcastVariables<TBody> {
  readonly broadcastId: string;
  readonly body: TBody;
}

/**
 * Compose a campaign and FREEZE its audience.
 *
 * No step-up: this messages nobody. The refusal to branch on is a `409 CONFLICT` carrying both
 * audience counts — read it with `audienceDriftOf`, show the operator the two numbers, and let
 * them choose between re-previewing and insisting. Do not retry it silently with the server's
 * number: the whole point of the catch is that a human sees the audience they are committing to.
 *
 * **There is no idempotency key on this route**, so two presses of Create are two campaigns with
 * two frozen audiences. Disable the button while `isPending` and navigate away on success.
 */
export function useCreateBroadcast(): UseMutationResult<
  BroadcastDetailView,
  AdminQueryError,
  BroadcastCreateRequest
> {
  const queryClient = useQueryClient();
  return useMutation<BroadcastDetailView, AdminQueryError, BroadcastCreateRequest>({
    mutationFn: (body) => unwrap(createBroadcast(body)),
    onSuccess: (detail) => {
      seedCampaign(queryClient, detail);
    },
    ...PRIVILEGED_WRITE,
  });
}

/**
 * Replace the title and the whole body set of a campaign that has not gone out.
 *
 * A 409 here is the conditional `UPDATE` refusing, not a check taken a moment earlier — the send
 * job runs in another process, and by the time this answers, the first message may have left under
 * the old text. Render `broadcastStateConflictOf`'s state and re-read; do not retry.
 */
export function useReviseBroadcast(): UseMutationResult<
  BroadcastDetailView,
  AdminQueryError,
  BroadcastVariables<BroadcastReviseRequest>
> {
  return useCampaignWrite((variables) => reviseBroadcast(variables.broadcastId, variables.body));
}

/**
 * Authorise the send — now, or at a stated instant. **The destructive action.**
 *
 * One hook for both, because the server has one route: `body.scheduledFor` absent is "now" and the
 * job is enqueued in the same breath; a future instant is left for the due sweep. `sendBroadcastNow`
 * and `scheduleBroadcast` in `api/broadcasts.ts` are the two spellings a call site should use to
 * build the body.
 *
 * Expect `STEP_UP_REQUIRED` on the first attempt. The scope is `broadcast.send:{broadcastId}` and
 * the `subjectId` must come from the refusal's `details` VERBATIM — hold the variables object, run
 * `StepUpDialog`, and `mutate` the SAME object again. Re-authenticating authorises the action; it
 * does not make this a second send.
 */
export function useSendBroadcast(): UseMutationResult<
  BroadcastDetailView,
  AdminQueryError,
  BroadcastVariables<BroadcastSendRequest>
> {
  return useCampaignWrite((variables) => sendBroadcast(variables.broadcastId, variables.body));
}

/**
 * Stop delivering, from `sending`. **No step-up** — this is the brake, and a password box in front
 * of it costs seconds at exactly the moment somebody needs them.
 *
 * The counters keep climbing for a few seconds afterwards: rows a worker had already claimed are
 * settled rather than abandoned. The poll shows that happening, which is the honest picture.
 */
export function usePauseBroadcast(): UseMutationResult<
  BroadcastDetailView,
  AdminQueryError,
  BroadcastVariables<ReasonedRequest>
> {
  return useCampaignWrite((variables) => pauseBroadcast(variables.broadcastId, variables.body));
}

/** `paused -> sending`, and the chunk job that stopped is re-enqueued. */
export function useResumeBroadcast(): UseMutationResult<
  BroadcastDetailView,
  AdminQueryError,
  BroadcastVariables<ReasonedRequest>
> {
  return useCampaignWrite((variables) => resumeBroadcast(variables.broadcastId, variables.body));
}

/**
 * Stop the campaign for good, from any non-terminal state.
 *
 * **Cancelling does not un-send what has gone.** The counters are not reset and the recipient rows
 * stay as evidence; a confirmation that says "cancelled" beside a `sentCount` of nine thousand is
 * telling the truth, and one that implies recall is not.
 */
export function useCancelBroadcast(): UseMutationResult<
  BroadcastDetailView,
  AdminQueryError,
  BroadcastVariables<ReasonedRequest>
> {
  return useCampaignWrite((variables) => cancelBroadcast(variables.broadcastId, variables.body));
}

/**
 * Send the composed bodies to ONE allowlisted account.
 *
 * Same step-up as the send, and a `403 FORBIDDEN` when the recipient is not on this deployment's
 * allowlist — which ships empty, so the control is off until somebody turns it on. That refusal
 * names neither the campaign nor the id; do not echo the typed id back into the message.
 *
 * **Invalidates nothing.** This writes an audit row and enqueues a job; no campaign row, no
 * counter and no recipient row changes, so there is nothing stale to re-read afterwards. The
 * result carries the masked recipient and the job id, which is the whole of what happened.
 */
export function useTestSendBroadcast(): UseMutationResult<
  BroadcastTestSendResultView,
  AdminQueryError,
  BroadcastVariables<BroadcastTestSendRequest>
> {
  return useMutation<
    BroadcastTestSendResultView,
    AdminQueryError,
    BroadcastVariables<BroadcastTestSendRequest>
  >({
    mutationFn: ({ broadcastId, body }) => unwrap(testSendBroadcast(broadcastId, body)),
    ...PRIVILEGED_WRITE,
  });
}

/* -------------------------------------------------------------------------- */
/* What the six campaign writes share                                          */
/* -------------------------------------------------------------------------- */

/**
 * Every write about an existing campaign is the same shape: one call, one `BroadcastDetailView`
 * back, one cache seed, one list invalidation.
 *
 * Written once because six copies of an invalidation rule drift apart one endpoint at a time, and
 * the drift here would be a screen showing a campaign as `sending` after somebody cancelled it.
 */
function useCampaignWrite<TBody>(
  call: (variables: BroadcastVariables<TBody>) => Promise<ApiResult<BroadcastDetailView>>,
): UseMutationResult<BroadcastDetailView, AdminQueryError, BroadcastVariables<TBody>> {
  const queryClient = useQueryClient();
  return useMutation<BroadcastDetailView, AdminQueryError, BroadcastVariables<TBody>>({
    mutationFn: (variables) => unwrap(call(variables)),
    onSuccess: (detail) => {
      seedCampaign(queryClient, detail);
    },
    ...PRIVILEGED_WRITE,
  });
}

/**
 * What every campaign write changes, and nothing else.
 *
 * The response IS the campaign, re-read by the handler from the transaction it just wrote in — so
 * the detail cache is SET rather than invalidated: a follow-up GET could only return the same row
 * or an older one, and the round trip would hold a dialog's spinner up over a write that already
 * landed.
 *
 * The lists go as a SET, not as one page. `state` is itself a filter, so a cancel can move a row
 * off the page it was read from and onto another; and every list page carries a rollup this write
 * may have changed.
 *
 * **The strip goes with them, as its own set.** Every write that reaches here moved a campaign
 * between states or created one, and both are exactly what the strip counts: a campaign composed
 * is one more in `total` and one more `expanding`, a send is a new `lastSendAt`, a pause moves a
 * campaign into the tile an operator is being asked to act on. Invalidating the list and not the
 * strip would leave a table that had just refreshed sitting under four numbers describing the
 * world as it was before the button was pressed — and on an idle deployment, where the poll is
 * off by design, those numbers would stay wrong until somebody reloaded the tab.
 *
 * The recipient ledger is deliberately untouched — see this module's header. Nothing here rewrites
 * those rows synchronously.
 *
 * Not awaited: the returned view already carries everything a confirmation needs to render.
 */
function seedCampaign(queryClient: QueryClient, detail: BroadcastDetailView): void {
  queryClient.setQueryData(broadcastsKeys.detail(detail.broadcast.id), detail);
  void queryClient.invalidateQueries({ queryKey: broadcastsKeys.lists() });
  void queryClient.invalidateQueries({ queryKey: broadcastsKeys.stats() });
}
