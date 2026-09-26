/**
 * The vendor balances, for the bar that is on every screen.
 *
 * ## It is the dashboard's own read, deliberately
 *
 * This calls `useFinance(BASE_PERIOD)` — the same hook, the same quantised window, therefore
 * the same `dashboardKeys.finance(window)` entry — rather than a second endpoint of its own.
 * On `/` that means the header pills and the dashboard's `BalanceStrip` are one request and
 * one 30s poll between them, and it is why they can never disagree about a figure or about
 * how stale it is. On the other six screens this hook is the only subscriber, so the cost of
 * a global balance bar is one finance read per 30s per open tab.
 *
 * `BASE_PERIOD` is not a window over the balances themselves: `vendor_balances` is a cache a
 * worker refreshes hourly and the server returns it whole, unwindowed. The period only picks
 * WHICH cached finance response this shares, and picking the dashboard's base one is what
 * makes the sharing work.
 *
 * ## Three absences, not one
 *
 * The state this returns keeps apart what a `chips.length === 0` alone would collapse:
 * `undefined` while the first read is in flight, `isUnavailable` when the read failed and no
 * cached response survives, and an empty array when the deployment polls no vendor at all.
 * Those are a skeleton, a fault line and a quiet pill respectively — the same three the
 * dashboard's strip already draws, because they are the same three facts.
 */

import { useMemo } from "react";

import { financeBalanceChips, type BalanceChip } from "@/features/dashboard/adapt";
import { useFinance } from "@/features/dashboard/useDashboardData";
import type { Period } from "@/features/dashboard/window";

/** The window `DashboardPage` pins its balances to. Kept in step by sharing the value. */
const BASE_PERIOD: Period = "today";

export interface HeaderBalances {
  /** `undefined` until the first answer. Never an empty array in that state. */
  readonly chips: readonly BalanceChip[] | undefined;
  /** The read failed and nothing cached survives it — distinct from "nothing is polled". */
  readonly isUnavailable: boolean;
}

export function useHeaderBalances(): HeaderBalances {
  const finance = useFinance(BASE_PERIOD);
  const data = finance.data;

  const chips = useMemo(
    () => (data === undefined ? undefined : financeBalanceChips(data)),
    [data],
  );

  return {
    chips,
    // `data === undefined` matters: a poll that fails against a warm cache is not an outage
    // the operator needs told about, it is the previous figure ageing by one tick.
    isUnavailable: finance.error !== null && data === undefined,
  };
}
