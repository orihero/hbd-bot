/**
 * The support GROUP directory's one read and two writes, as hooks.
 *
 * `api/support.ts` fetches and `lib/adminQuery.ts` holds the shared error, retry policy and
 * option bundles; this is the layer between them. `useSupportTickets.ts` is the sibling it
 * copies — key factory, option bundles, typed errors — and it is a SEPARATE module rather than
 * four more exports there, for the reason the server split the routers: the two surfaces share a
 * URL prefix and nothing else. A ticket is one customer's complaint, addressed by a UUID, paged,
 * filtered and written by `support.write`; a directory row is a ROOM, addressed by a negative
 * integer Telegram issued, unpaged, unfiltered and written by `support.group.write`. Folding
 * them together would put a per-ticket key factory and a table-wide one in one object and make
 * "what does a write here invalidate?" a question with two different answers in one file.
 *
 * They do share `SUPPORT_ROOT`, imported rather than re-spelled, so the two key trees sit under
 * one prefix.
 *
 * ## The four decisions the dialog depends on
 *
 * **The read does not poll, and the writes are what refresh it.** This is not the ticket
 * queue's reasoning restated: there, polling was refused because a board must not re-order
 * itself under a half-typed reply. Here the temptation is the opposite and stronger — the
 * verification verdict arrives from ANOTHER PROCESS, seconds after a Select, and a poll would
 * turn "checking…" into "verified" without anybody pressing anything. It is still refused, and
 * {@link useSupportGroups} argues why at its own definition: a background timer against a
 * configuration screen that is open for a minute a month is machinery that runs for ever to
 * save one press, and the press is already on the dialog. What the writes do instead is seed the
 * directory they were answered with and invalidate it, so the list is never older than the last
 * thing the operator did.
 *
 * **Both writes answer with the whole directory, so the cache is SET rather than re-fetched.**
 * The server re-reads the table inside the transaction it just wrote in; that list is more
 * current than anything a follow-up GET could return, and seeding it is what makes a Select feel
 * like it took effect. The invalidation that follows is for the verification verdict, which this
 * response cannot contain.
 *
 * **A 503 from `/select` is not a failed write.** The enqueue follows the commit deliberately —
 * the other order was a critical defect in the ticket feature this morning — so a deployment
 * with no worker leaves the selection MADE and unverified. {@link useSelectSupportGroup} takes
 * the trouble to invalidate on that failure for exactly that reason, which is the one place
 * these hooks do something a caller would not think to ask for.
 *
 * **No step-up, anywhere.** `support.group.write` is a plain `W`, so there is no
 * `STEP_UP_REQUIRED` to catch, no dialog to drive and no body to replay. The refusals that do
 * reach a screen are a `403` for a role that lacks the cell, a `409` for a concurrent double
 * press, a `422` for an id that names a person, and the `503` above.
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
  clearSupportGroup,
  listSupportGroups,
  selectSupportGroup,
  type SupportGroupClearResponse,
  type SupportGroupSelectRequest,
  type SupportGroupSelectResponse,
  type SupportGroupsResponse,
} from "@/api/support";
import { SUPPORT_ROOT } from "@/features/support/useSupportTickets";
import {
  LIST_READ,
  PRIVILEGED_WRITE,
  unwrap,
  type AdminQueryError,
} from "@/lib/adminQuery";

/* -------------------------------------------------------------------------- */
/* Keys                                                                        */
/* -------------------------------------------------------------------------- */

/**
 * One key, and there will only ever be one.
 *
 * No filter projection and no page key, because the read takes neither: `list_bot_chats` returns
 * the whole table by construction and argues at length why — Telegram has no "list my groups"
 * API, so the population is a handful of rows in every deployment this product will have. A key
 * factory shaped for filters that do not exist would be four lines of machinery inviting a
 * filter nobody needs.
 */
export const supportGroupKeys = {
  all: [SUPPORT_ROOT, "groups"] as const,
  directory: () => [SUPPORT_ROOT, "groups", "directory"] as const,
} as const;

export type SupportGroupKeys = typeof supportGroupKeys;

/* -------------------------------------------------------------------------- */
/* The read                                                                    */
/* -------------------------------------------------------------------------- */

/**
 * Every chat the bot knows it is in, the selected one first. `support.read`, so every role.
 *
 * **It does not poll, and the decision is worth defending because this is the one read in the
 * console where a poll would genuinely be correct.** The verification verdict is written by the
 * worker, in another process, usually within a second or two of a Select — so a row that says
 * "checking…" really does become something else while nobody touches the screen, which is not
 * true of any list in this panel.
 *
 * It is still refused, on three grounds. The surface is a dialog an operator opens for a minute
 * when they are changing where tickets go, which is a thing that happens once and then not again
 * for months: a timer is machinery that runs whenever the dialog is open to save a press that is
 * already on the dialog. The verdict is not time-critical — it is read, acted on, and the
 * failure it reports (the bot was removed, the topic was deleted, the group migrated) needs a
 * human to go and fix something in Telegram before any number of refetches would say anything
 * new. And a poll here would be the first one in the panel, so it would also be the first place
 * anybody copied it from.
 *
 * `LIST_READ` therefore, with `refetchOnWindowFocus` doing the honest half of the job: an
 * operator who switches to Telegram to add the bot to a group and comes back gets a fresh
 * directory for having done exactly that.
 *
 * `enabled` is not exposed. Every role holds `support.read`, so there is no role for which this
 * read is a 403 waiting to happen, and a caller that wants it idle can unmount the dialog.
 */
export function useSupportGroups(): UseQueryResult<SupportGroupsResponse, AdminQueryError> {
  return useQuery<SupportGroupsResponse, AdminQueryError>({
    queryKey: supportGroupKeys.directory(),
    queryFn: ({ signal }) => unwrap(listSupportGroups(signal)),
    ...LIST_READ,
  });
}

/* -------------------------------------------------------------------------- */
/* The writes                                                                  */
/* -------------------------------------------------------------------------- */

/**
 * Point the support inbox at a chat — known or pasted — and enqueue the check.
 *
 * **On success this seeds the directory and then invalidates it, which looks redundant and is
 * not.** The response is the table as the handler read it back inside its own transaction, so it
 * is the most current answer available AT THAT INSTANT — and the instant is before the worker
 * has run. Seeding puts the new selection on screen with no round trip; invalidating is what
 * goes back for the verdict the response could not contain. A screen must render the seeded row
 * as "checking…", never as verified: `verificationStateOf` is the only thing that may decide
 * which badge it wears.
 *
 * **On a `503` it invalidates too, and that is the unusual half.** A 503 here means the enqueue
 * was refused because no worker is running — but the enqueue follows the COMMIT (the other order
 * was a critical defect in the sibling feature this morning), so the selection happened and is
 * durable. Treating it as a failed write would leave the dialog showing the previous group while
 * the database holds the new one, which is the specific lie this whole feature exists to remove.
 * The refetch is what puts the truth back on screen; the caller still shows the failure, because
 * "it is selected and nothing will ever check it" is something an operator needs to be told.
 *
 * A `409` is a concurrent double press and is NOT retried — the same bytes lose the same race —
 * but it is invalidated for the same reason: the other operator's selection is now the truth and
 * this screen is showing a stale one. A `403` and a `422` wrote nothing and are left alone.
 */
export function useSelectSupportGroup(): UseMutationResult<
  SupportGroupSelectResponse,
  AdminQueryError,
  SupportGroupSelectRequest
> {
  const queryClient = useQueryClient();
  return useMutation<SupportGroupSelectResponse, AdminQueryError, SupportGroupSelectRequest>({
    mutationFn: (body) => unwrap(selectSupportGroup(body)),
    onSuccess: (answer) => {
      seedDirectory(queryClient, answer.groups);
    },
    onError: (error) => {
      /* 503: committed, unverified, and the response never arrived. 409: somebody else's
         selection won. Both mean what is on screen is no longer what the table says. */
      if (error.status === 503 || error.status === 409) {
        void queryClient.invalidateQueries({ queryKey: supportGroupKeys.all });
      }
    },
    ...PRIVILEGED_WRITE,
  });
}

/**
 * Unselect the support group. **Tickets keep working; only the group post stops.**
 *
 * Idempotent and enqueues nothing — there is no room to verify — so there is no 503 to handle
 * and no asynchronous half to wait for. This is the one write in the feature whose answer is
 * final the moment it arrives, which is why it seeds the directory and invalidates nothing
 * further.
 *
 * `clearedChatId` is `null` when nothing was selected, and that is a 200: the caller asked for
 * "no group selected" and that is what they have.
 */
export function useClearSupportGroup(): UseMutationResult<
  SupportGroupClearResponse,
  AdminQueryError,
  void
> {
  const queryClient = useQueryClient();
  return useMutation<SupportGroupClearResponse, AdminQueryError>({
    mutationFn: () => unwrap(clearSupportGroup()),
    onSuccess: (answer) => {
      queryClient.setQueryData<SupportGroupsResponse>(supportGroupKeys.directory(), {
        groups: answer.groups,
      });
    },
    ...PRIVILEGED_WRITE,
  });
}

/* -------------------------------------------------------------------------- */
/* What a select changes                                                       */
/* -------------------------------------------------------------------------- */

/**
 * Seed the directory from a write's own answer, then go back for the verdict.
 *
 * Written once because the seed and the invalidation are two halves of one rule about this
 * feature's asynchrony, and a second copy would drift into one of them alone — which reads as
 * either a dialog that flickers through a refetch it did not need, or a row that says "checking…"
 * for ever because nothing ever asked again.
 *
 * Not awaited: `no-floating-promises` is on, so the discard is explicit with `void`. The seeded
 * list already carries everything the dialog draws; waiting on the refetch would hold a spinner
 * over a write that has landed.
 */
function seedDirectory(
  queryClient: QueryClient,
  groups: SupportGroupsResponse["groups"],
): void {
  queryClient.setQueryData<SupportGroupsResponse>(supportGroupKeys.directory(), { groups });
  void queryClient.invalidateQueries({ queryKey: supportGroupKeys.all });
}
