/**
 * The freshness heartbeat the `LIVE` pill renders.
 *
 * Split out of `LivePill.tsx` so that file exports components only (Fast Refresh reloads a
 * module wholesale when it exports a mix, which would remount the top bar on every edit).
 */

import { useQuery } from "@tanstack/react-query";

import { getPulse, unwrapAsync } from "@/api";
import { useIsDocumentVisible, useNow } from "@/components/util";
import { POLL_MS, liveStatus, pollWhileVisible, type LiveStatus } from "@/lib/queryClient";
import { queryKeys } from "@/lib/queryKeys";

/**
 * The heartbeat every surface shares.
 *
 * `/ops/pulse` is §11.5's one consolidated dashboard read, at 5 s. Live Ops subscribes to the
 * same query key, so the pill and the dashboard cost ONE request per tick between them —
 * mounting this in the top bar does not add a poll, it joins the existing one.
 */
export function useLiveHeartbeat(): { status: LiveStatus; refetch: () => void } {
  const isVisible = useIsDocumentVisible();
  const query = useQuery({
    queryKey: queryKeys.ops.pulse(),
    queryFn: ({ signal }) => unwrapAsync(getPulse({ signal })),
    refetchInterval: pollWhileVisible(POLL_MS.pulse),
  });

  const isPaused = query.isPaused || !isVisible;
  // The age has to advance between fetches or a stall is invisible until the next attempt,
  // which is the one moment the operator needs to be told. Ticking stops when paused,
  // because a paused pill shows no number.
  const now = useNow(1_000, !isPaused);

  return {
    status: liveStatus({
      dataUpdatedAt: query.dataUpdatedAt,
      errorCount: query.failureCount,
      isPaused,
      now,
    }),
    refetch: () => {
      void query.refetch();
    },
  };
}

