/**
 * The six states of §11.4, resolved as data so they can be tested without a DOM.
 *
 * > Skeleton · Empty-virgin · Empty-filtered · Error · **Stale** · **Purged**
 *
 * `AsyncBoundary` renders whatever this returns. Keeping the decision here rather than in a
 * chain of ternaries inside JSX is what makes the PRECEDENCE reviewable, and the precedence
 * is the part that is easy to get wrong:
 *
 *  1. **Purged wins over everything.** A purged subject is a fact the system is proud of,
 *     not a failure. §12.3: "`identity_purged_at` is **always** displayed. 'No name' and
 *     'name purged on schedule 2026-05-14' are different facts and only one is defensible."
 *     Rendering it as an error, or as a blank, discards the one thing that proves the
 *     retention design works.
 *  2. **A failed poll that still has last-known data is STALE, not ERROR.** §11.4: "a
 *     dashboard that blanks on a failed poll is worse than one showing stale numbers
 *     labelled stale". `placeholderData: keepPreviousData` in `queryClient.ts` is what
 *     keeps that data around; this is what labels it.
 *  3. **Error only when there is nothing to keep.** Then it is inline and scoped, and the
 *     rest of the screen survives.
 *  4. Empty-filtered before empty-virgin, because a filter is the likelier explanation and
 *     the only one with a remedy.
 *  5. A successful but old result is still stale — same 10s threshold the LIVE pill goes
 *     amber at (`isStale`), so the chip and the pill never disagree on screen.
 */

import { isStale } from "@/lib/queryClient";

export type AsyncStateKind =
  | "skeleton"
  | "empty-virgin"
  | "empty-filtered"
  | "error"
  | "stale"
  | "purged"
  | "ready";

export interface AsyncStateInput {
  /** TanStack Query's `status`. */
  readonly status: "pending" | "error" | "success";
  /** Whether anything renderable is in hand — `query.data !== undefined`. */
  readonly hasData: boolean;
  /** Whether the data in hand is an empty list. Ignored unless `hasData`. */
  readonly isEmpty: boolean;
  /** `SearchParamsState.activeCount`. Zero means the list is unfiltered. */
  readonly activeFilterCount: number;
  /** `identityPurgedAt` (or whichever purge stamp this panel is about). */
  readonly purgedAt: string | null;
  /** `query.dataUpdatedAt`. `0` before the first success. */
  readonly dataUpdatedAt: number;
  readonly now?: number | undefined;
}

export function resolveAsyncState(input: AsyncStateInput): AsyncStateKind {
  if (input.purgedAt !== null) return "purged";
  if (input.status === "error") return input.hasData ? "stale" : "error";
  if (!input.hasData) return "skeleton";
  if (input.isEmpty) {
    return input.activeFilterCount > 0 ? "empty-filtered" : "empty-virgin";
  }
  if (isStale(input.dataUpdatedAt, input.now ?? Date.now())) return "stale";
  return "ready";
}

/** Whether this state still renders the caller's children underneath. */
export function keepsChildren(kind: AsyncStateKind): boolean {
  return kind === "ready" || kind === "stale";
}
