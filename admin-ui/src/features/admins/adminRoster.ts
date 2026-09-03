/**
 * The two questions `/admins` answers, computed off the roster and nothing else.
 *
 * Kept out of the screen so they are testable without a DOM: "is there a stale account?" is
 * a judgement about a list, and a judgement is worth pinning.
 *
 * **Staleness is not one condition.** Three different accounts are stale in three different
 * ways and an operator acts differently on each:
 *
 *  - **never signed in** — a bootstrapped or freshly created account whose temporary
 *    password is still live. This is the worst one and it has no `lastLoginAt` at all, so a
 *    "sort by last login" view puts it where the eye goes last.
 *  - **still holding a temporary password** (`mustChangePassword`) — the credential someone
 *    typed into a chat window is still the credential.
 *  - **quiet** — active, rotated, but has not signed in for a long time.
 *
 * `DORMANT_DAYS` is ours, not the plan's: §11.2 asks for "active count + last-login recency"
 * and names no threshold. 60 days is a deliberate choice of a number long enough that a
 * person on leave does not light it up, and short enough that a departed operator does.
 */

import type { AdminAccountView } from "@/api";

/** How long an active account may stay silent before it is worth a second look. */
export const DORMANT_DAYS = 60;

const DORMANT_MS = DORMANT_DAYS * 86_400_000;

export type StaleReason = "never-signed-in" | "temporary-password" | "dormant";

export interface RosterSummary {
  readonly activeCount: number;
  readonly deactivatedCount: number;
  /** The most recent sign-in across every ACTIVE account, or `null` if none ever signed in. */
  readonly lastLoginAt: string | null;
  /** Active accounts carrying at least one staleness reason, worst first. */
  readonly stale: readonly StaleAccount[];
}

export interface StaleAccount {
  readonly account: AdminAccountView;
  readonly reasons: readonly StaleReason[];
}

/** Worst first — the order the list is rendered in and the order the reasons are read in. */
const REASON_RANK: Record<StaleReason, number> = {
  "never-signed-in": 0,
  "temporary-password": 1,
  dormant: 2,
};

/**
 * Why this account is stale, or an empty list.
 *
 * A DEACTIVATED account is never stale: it cannot sign in, so its silence is the control
 * working. It still appears in the roster (§11.2: grey them, never omit them) — it is simply
 * not something to act on.
 */
export function staleReasons(
  account: AdminAccountView,
  now: number = Date.now(),
): readonly StaleReason[] {
  if (!account.isActive) return [];
  const reasons: StaleReason[] = [];
  if (account.lastLoginAt === null) reasons.push("never-signed-in");
  if (account.mustChangePassword) reasons.push("temporary-password");
  if (account.lastLoginAt !== null) {
    const at = Date.parse(account.lastLoginAt);
    if (!Number.isNaN(at) && now - at > DORMANT_MS) reasons.push("dormant");
  }
  return reasons;
}

export function summariseRoster(
  items: readonly AdminAccountView[],
  now: number = Date.now(),
): RosterSummary {
  let activeCount = 0;
  let lastLoginAt: string | null = null;
  let lastLoginMs = Number.NEGATIVE_INFINITY;
  const stale: StaleAccount[] = [];

  for (const account of items) {
    if (account.isActive) activeCount += 1;
    if (account.isActive && account.lastLoginAt !== null) {
      const at = Date.parse(account.lastLoginAt);
      if (!Number.isNaN(at) && at > lastLoginMs) {
        lastLoginMs = at;
        lastLoginAt = account.lastLoginAt;
      }
    }
    const reasons = staleReasons(account, now);
    if (reasons.length > 0) stale.push({ account, reasons });
  }

  stale.sort((left, right) => {
    const leftWorst = REASON_RANK[left.reasons[0] ?? "dormant"];
    const rightWorst = REASON_RANK[right.reasons[0] ?? "dormant"];
    return leftWorst - rightWorst;
  });

  return {
    activeCount,
    deactivatedCount: items.length - activeCount,
    lastLoginAt,
    stale,
  };
}

/** Our own copy for each reason. Never the account's own words — there are none. */
export const STALE_REASON_LABEL: Record<StaleReason, string> = {
  "never-signed-in": "never signed in",
  "temporary-password": "still on its temporary password",
  dormant: `no sign-in in ${String(DORMANT_DAYS)} days`,
};
