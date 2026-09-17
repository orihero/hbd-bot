/**
 * The roster read, as a hook. One query, and four decisions the screen depends on.
 *
 * **The key has no filter and no page projection, because the wire has neither.** Every other
 * list in this console keys on `filterKey(...)` and `pageKey(...)` so that two different
 * questions cannot share one cache entry. `GET /api/admins` asks exactly one question and
 * takes no parameters at all, so there is exactly one entry — and a key carrying a projection
 * of filters the request cannot send would be a cache shape describing a request shape that
 * does not exist, which is the kind of thing a later reader copies.
 *
 * **`LIST_READ`, not `SUBJECT_READ`.** This is a list, and the bundle's stance is the one it
 * wants: no timer (`refetchInterval: false`), refetch when the operator comes back to the tab.
 * A roster changes when an OWNER changes it, and the writes that would do so are Phase 2 —
 * polling it would be a request every few seconds to learn nothing. `LIST_READ` also carries
 * `placeholderData: keepPreviousData`, which is inert here: with one static key there is never
 * a previous answer under a different question to keep, so `isPlaceholderData` never becomes
 * true and the screen has no "dim the old rows" state to render.
 *
 * **One mutation lives here: the create.** `POST /admins` is the first of §6.8's four account
 * writes to land. The other three — `PATCH /admins/{id}`, `POST /admins/{id}/reset-password`
 * and `DELETE /admins/{id}/sessions` — are still future work that would 404 today, so a hook
 * for them belongs here only when the route does; one added early is how a screen grows a
 * button that cannot work.
 *
 * The create invalidates `lists()`, which is why the key factory has always had a `lists()`
 * distinct from `list()`: "every roster read" was expressible before there was anything to
 * invalidate it for. It does NOT write the new row into the cache by hand — the roster is one
 * bounded read with a server-side ordering (`created_at ASC, id ASC`) and a `MAX_ADMIN_ACCOUNTS`
 * ceiling, so re-asking the one question is both cheap and the only way the list stays the
 * server's answer rather than this bundle's guess at where the row goes.
 *
 * **Refusals are not retried, and — the part `shouldRetryRead` cannot do — they are not
 * re-ASKED either.** The roster is OWNER-only, the guard writes a `permission.denied` audit
 * row in its own committed transaction before it raises, and a second GET is a second row in
 * the log naming an operator who did nothing but open a page. `shouldRetryRead` treats 403 as
 * terminal, which caps one TRIGGER at one request; it does not stop the trigger firing again.
 * And a query that has only ever rejected has no data, so react-query's staleness check
 * short-circuits to "stale" for ever — `RECORD_STALE_TIME_MS` is a ceiling on how often focus
 * can refetch a query that HAS an answer, and no ceiling at all on one that does not. Left as
 * `LIST_READ`, an ADMIN, SUPPORT or VIEWER who opens `/admins` (the rail shows it to every
 * role on purpose) and leaves the tab open writes one more refusal row every time they tab
 * back, which falsifies the bound this module, `api/admins.ts` and the screen all state.
 *
 * So both focus triggers are overridden to the function form and asked to stand down while the
 * query is in `error` — the same override `features/audit/useAudit.ts` applies to the chain
 * walk, for a related reason. A query that HAS a roster still refreshes on focus, which is the
 * whole reason this is a `LIST_READ` in the first place. `refetchOnReconnect` needs the same
 * treatment even though `LIST_READ` never mentions it: the client default turns it on
 * (`lib/queryClient.ts`), so leaving it alone would leave a second door into the same row.
 *
 * The screen withholds its own Retry button on that failure for the same reason.
 */

import {
  useMutation,
  useQuery,
  useQueryClient,
  type UseMutationResult,
  type UseQueryResult,
} from "@tanstack/react-query";

import {
  createAdmin,
  listAdmins,
  type AdminAccountView,
  type AdminCreateRequest,
  type AdminRoster,
} from "@/api/admins";
import {
  LIST_READ,
  PRIVILEGED_WRITE,
  unwrap,
  type AdminQueryError,
} from "@/lib/adminQuery";

/* -------------------------------------------------------------------------- */
/* Keys                                                                        */
/* -------------------------------------------------------------------------- */

const ADMINS_ROOT = "admins";

/**
 * The key factory.
 *
 * `lists()` and `list()` are the same array today — there is one list and no parameters to
 * vary it by — and they are kept apart anyway so that the day a write lands, invalidating
 * "every roster read" is already expressible without touching the shape of the key.
 */
export const adminsKeys = {
  all: [ADMINS_ROOT] as const,
  lists: () => [ADMINS_ROOT, "list"] as const,
  list: () => [ADMINS_ROOT, "list"] as const,
} as const;

export type AdminsKeys = typeof adminsKeys;

/* -------------------------------------------------------------------------- */
/* The read                                                                    */
/* -------------------------------------------------------------------------- */

/**
 * Every operator account, oldest first, deactivated ones included.
 *
 * The whole roster arrives in one bounded response: there is no cursor to walk and no total
 * to ask for, so a caller reads `data.items` and paginates nothing. A 403 here is the normal
 * answer for VIEWER, SUPPORT and ADMIN and must be rendered as a flat refusal — never as a
 * step-up prompt, which this route never asks for and no password could satisfy.
 */
export function useAdmins(): UseQueryResult<AdminRoster, AdminQueryError> {
  return useQuery<AdminRoster, AdminQueryError>({
    queryKey: adminsKeys.list(),
    queryFn: ({ signal }) => unwrap(listAdmins(signal)),
    ...LIST_READ,
    // A refused roster is not refreshed by looking at it. See the module header: the refusal
    // costs an audit row, and `status === "error"` is the only state in which asking again is
    // guaranteed to buy nothing but that row.
    refetchOnWindowFocus: (query) => query.state.status !== "error",
    refetchOnReconnect: (query) => query.state.status !== "error",
  });
}

/* -------------------------------------------------------------------------- */
/* The write                                                                   */
/* -------------------------------------------------------------------------- */

/**
 * Add one operator account.
 *
 * OWNER only, and it needs a live step-up scoped to `admin.manage:{username}` — so expect
 * `STEP_UP_REQUIRED` on the first attempt, take the target from the refusal's `details`
 * (`stepUpTargetOf`) and replay the SAME body once the grant lands. The username is the
 * subject, so a body whose name changed between the two is a different subject and a second
 * refusal; that is the grant doing its job.
 *
 * `PRIVILEGED_WRITE` for the reason every other account-touching write takes it: no retry.
 * A create that timed out may well have landed, and a second attempt would either mint a
 * second operator or collide with the first — and the refusal it earns costs an audit row
 * either way. The roster read after invalidation is what says which happened.
 */
export function useCreateAdmin(): UseMutationResult<
  AdminAccountView,
  AdminQueryError,
  AdminCreateRequest
> {
  const queryClient = useQueryClient();
  return useMutation<AdminAccountView, AdminQueryError, AdminCreateRequest>({
    mutationFn: (body) => unwrap(createAdmin(body)),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: adminsKeys.lists() });
    },
    ...PRIVILEGED_WRITE,
  });
}
