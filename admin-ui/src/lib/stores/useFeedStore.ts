/**
 * `useFeedStore` — the third and last of §11.1's client stores.
 *
 * The live feed on `/` is the one surface where the newest item pushing the list down is
 * actively hostile: an operator reading a failure at 14:32 does not want it to scroll away
 * because two more arrived. So the feed keeps its own client state — paused, buffered,
 * filtered — separate from the query cache that supplies it.
 *
 * **This store is a ring buffer, not a source of truth.** Events arrive from TanStack Query
 * (v1: the 5s poll of `/ops/feed`; v1.1: an `EventSource` pushing into the same cache via
 * `setQueryData`). The store only decides what is on screen and what is held back while the
 * operator is reading.
 *
 * ---
 * A NOTE FOR WHOEVER BUILDS `LiveFeed`: `GET /api/ops/feed` does not exist yet. §11.5's
 * table names it at a 5s tier, but the shipped router set has no feed endpoint and the
 * contract does not describe one, so `FeedEvent` below is THIS FILE'S invention, not a wire
 * type — there is no zod schema for it in `src/api/` because there is nothing to parse.
 * Until the endpoint lands, populate it from what does exist: `PulseView.failures`, an
 * orders list filtered to the in-flight states, or the audit log. When the real endpoint
 * ships, its schema goes in `src/api/schemas.ts` and `FeedEvent` becomes an alias of it.
 */

import { useMemo } from "react";
import { create } from "zustand";

/** How loudly an entry reads. Mapped to `--green` / `--amber` / `--red` by the component. */
export type FeedSeverity = "info" | "warn" | "error";

export interface FeedEvent {
  /** Stable across re-deliveries of the same event, so the ring can dedupe. */
  readonly id: string;
  /** RFC 3339. Rendered through `formatTimestamp` — never a bare time. */
  readonly at: string;
  /** Our own closed vocabulary, never free text and never a customer's words. */
  readonly label: string;
  readonly severity: FeedSeverity;
  readonly orderId: string | null;
  readonly correlationId: string | null;
}

/**
 * How many events are kept. A dashboard left open overnight must not grow without bound;
 * anything older than this belongs in `/orders` or `/audit`, which are queryable.
 */
export const FEED_CAPACITY = 200;

export interface FeedState {
  /** Newest first. */
  events: readonly FeedEvent[];
  /** While paused, arrivals go to `buffered` and the visible list does not move. */
  isPaused: boolean;
  buffered: readonly FeedEvent[];
  /** `null` shows everything. */
  severityFilter: FeedSeverity | null;

  /** Merge new events, newest-first, deduped by id and capped at `FEED_CAPACITY`. */
  ingest: (events: readonly FeedEvent[]) => void;
  setPaused: (isPaused: boolean) => void;
  togglePaused: () => void;
  /** Release everything held while paused into the visible list. */
  flushBuffered: () => void;
  setSeverityFilter: (severity: FeedSeverity | null) => void;
  clear: () => void;
}

function mergeNewestFirst(
  existing: readonly FeedEvent[],
  incoming: readonly FeedEvent[],
): FeedEvent[] {
  const seen = new Set<string>();
  const merged: FeedEvent[] = [];
  for (const event of [...incoming, ...existing]) {
    if (seen.has(event.id)) continue;
    seen.add(event.id);
    merged.push(event);
  }
  // Plain string comparison, not `localeCompare`: these are RFC 3339 instants, which sort
  // lexicographically, and a locale-aware collator would make the order depend on the
  // operator's machine.
  merged.sort((left, right) => (left.at < right.at ? 1 : left.at > right.at ? -1 : 0));
  return merged.slice(0, FEED_CAPACITY);
}

export const useFeedStore = create<FeedState>()((set, get) => ({
  events: [],
  isPaused: false,
  buffered: [],
  severityFilter: null,

  ingest: (incoming) => {
    if (incoming.length === 0) return;
    if (get().isPaused) {
      set((state) => ({ buffered: mergeNewestFirst(state.buffered, incoming) }));
      return;
    }
    set((state) => ({ events: mergeNewestFirst(state.events, incoming) }));
  },
  setPaused: (isPaused) => set({ isPaused }),
  togglePaused: () => set((state) => ({ isPaused: !state.isPaused })),
  flushBuffered: () =>
    set((state) => ({
      events: mergeNewestFirst(state.events, state.buffered),
      buffered: [],
      isPaused: false,
    })),
  setSeverityFilter: (severityFilter) => set({ severityFilter }),
  clear: () => set({ events: [], buffered: [] }),
}));

/**
 * The list a component should render, with the severity filter applied.
 *
 * The filter runs in a `useMemo` rather than inside the selector on purpose: a selector that
 * returns a fresh array on every call fails `useSyncExternalStore`'s identity check and
 * re-renders forever. Select the two stable pieces, derive outside.
 */
export function useVisibleFeed(): readonly FeedEvent[] {
  const events = useFeedStore((state) => state.events);
  const severityFilter = useFeedStore((state) => state.severityFilter);
  return useMemo(
    () =>
      severityFilter === null
        ? events
        : events.filter((event) => event.severity === severityFilter),
    [events, severityFilter],
  );
}
