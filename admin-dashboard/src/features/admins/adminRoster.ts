/**
 * What the roster means, computed off `items` and nothing else.
 *
 * The screen asks one question — who can sign in to this panel, and who currently cannot —
 * and every judgement that answer rests on lives here rather than inside JSX, because each
 * one is a decision somebody could reasonably make differently and a decision buried in a
 * render function is a decision nobody can find.
 *
 * ## Deactivated accounts are grouped, never filtered out
 *
 * `isActive: false` is half the question, so the roster keeps them: an account deactivated
 * last year is the cleanest possible answer to "is anything stale here?", and a list that
 * drops it sends an operator to `psql` to find out. What `groupRoster` does instead is put
 * the accounts that can sign in first and the ones that cannot after them — the order the
 * question is asked in — while preserving the server's own order **within** each group. That
 * order is `created_at ASC, id ASC`, so a row's position is stable across reloads; a
 * client-side sort by username would move rows for reasons the server cannot reproduce, and
 * a "hide deactivated" toggle would answer "who has access?" with a number smaller than the
 * number of credentials that exist.
 *
 * ## Staleness is three different conditions, not one
 *
 * They are not interchangeable — an operator acts differently on each:
 *
 *  - **never signed in** — a bootstrapped or freshly created account whose temporary password
 *    is still live and has never been used. This is the worst of the three and it has no
 *    `lastLoginAt` at all, so any "sort by last login" view puts it where the eye goes last.
 *  - **still on a temporary password** — `mustChangePassword`: the credential somebody typed
 *    into a chat window is still the credential on the account.
 *  - **dormant** — active, rotated, and silent for a long time.
 *
 * `DORMANT_DAYS` is **ours, not the spec's**: §11.2 asks for "active count + last-login
 * recency" and names no threshold. 60 days is chosen to be long enough that a person on leave
 * does not light it up and short enough that a departed operator does. It is a number this
 * console invented, and the label interpolates it so the sentence and the threshold cannot
 * disagree.
 *
 * ## Three edge cases that a rewrite gets wrong
 *
 *  - **A deactivated account is never stale.** It cannot sign in, so its silence is the
 *    control working, not an item of work. It still appears in the table; it is simply not
 *    something to act on.
 *  - **An unparseable timestamp is not infinitely old.** `Date.parse` returning `NaN` means
 *    this build did not understand what the server sent, and manufacturing an alarm out of a
 *    contract change would send an operator after the wrong thing.
 *  - **`lastLoginAt` recency is measured across ACTIVE accounts only.** A deactivated
 *    account's old sign-in is not the roster's recency; it is a fact about a credential that
 *    no longer works.
 */

import type { AdminAccountView } from "@/api/admins";
import { MAX_ADMIN_ACCOUNTS } from "@/api/constants";
import type { TranslationPath } from "@/i18n/types";

/** How long an active account may stay silent before it is worth a second look. Ours. */
export const DORMANT_DAYS = 60;

const DORMANT_MS = DORMANT_DAYS * 86_400_000;

export type StaleReason = "never-signed-in" | "temporary-password" | "dormant";

/** Our own words for each reason — the account has none of its own. */
export const STALE_REASON_KEY: Readonly<Record<StaleReason, TranslationPath>> = {
  "never-signed-in": "admins.staleReasons.neverSignedIn",
  "temporary-password": "admins.staleReasons.temporaryPassword",
  dormant: "admins.staleReasons.dormant",
};

/** Worst first: the order the list is rendered in and the order the reasons are read in. */
const REASON_RANK: Readonly<Record<StaleReason, number>> = {
  "never-signed-in": 0,
  "temporary-password": 1,
  dormant: 2,
};

/** One account with the judgement about it attached, so a row never recomputes its own. */
export interface RosterEntry {
  readonly account: AdminAccountView;
  /** Empty for an account with nothing to act on — and always empty for a deactivated one. */
  readonly reasons: readonly StaleReason[];
}

export interface RosterView {
  /** Every account, sign-in first, deactivated after — server order within each group. */
  readonly rows: readonly RosterEntry[];
  readonly activeCount: number;
  readonly deactivatedCount: number;
  /** The most recent sign-in across ACTIVE accounts, or `null` when none has ever signed in. */
  readonly lastLoginAt: string | null;
  /** Active accounts carrying at least one reason, worst first. Empty is the good answer. */
  readonly stale: readonly RosterEntry[];
  /**
   * `items.length` hit the server's ceiling, so rows may have been cut.
   *
   * The response carries no flag and no total, so this is a possibility and never a claim:
   * the screen says "may be truncated", not "showing 500 of N", because N is not on the wire.
   */
  readonly isPossiblyTruncated: boolean;
}

/**
 * Why this account is worth a look, or an empty list.
 *
 * Exported on its own because a row renders its own reasons and the summary counts them; one
 * function so the two can never disagree about what "stale" means.
 */
export function staleReasons(
  account: AdminAccountView,
  now: number = Date.now(),
): readonly StaleReason[] {
  if (!account.isActive) return [];

  const reasons: StaleReason[] = [];
  if (account.lastLoginAt === null) reasons.push("never-signed-in");
  // Independent of the other two: an account can be in daily use and still be holding the
  // password somebody else chose for it.
  if (account.mustChangePassword) reasons.push("temporary-password");
  if (account.lastLoginAt !== null) {
    const at = Date.parse(account.lastLoginAt);
    // NaN is a timestamp this build did not understand, which is not the same as an old one.
    if (!Number.isNaN(at) && now - at > DORMANT_MS) reasons.push("dormant");
  }
  return reasons;
}

/**
 * The whole roster, read once.
 *
 * One pass rather than four passes over the same array, and one function rather than four
 * exports, because every figure the screen prints has to describe the same list: an
 * "active" count taken from a different traversal than the rows below it is how a header
 * ends up disagreeing with the table under it.
 *
 * `now` is a parameter with a default so the caller can pin it — a `Date.now()` read on every
 * render would let a row cross the dormancy threshold while somebody is reading it.
 */
export function readRoster(
  items: readonly AdminAccountView[],
  now: number = Date.now(),
): RosterView {
  const active: RosterEntry[] = [];
  const deactivated: RosterEntry[] = [];
  const stale: RosterEntry[] = [];
  let lastLoginAt: string | null = null;
  let lastLoginMs = Number.NEGATIVE_INFINITY;

  for (const account of items) {
    const entry: RosterEntry = { account, reasons: staleReasons(account, now) };

    if (account.isActive) {
      active.push(entry);
      if (account.lastLoginAt !== null) {
        const at = Date.parse(account.lastLoginAt);
        if (!Number.isNaN(at) && at > lastLoginMs) {
          lastLoginMs = at;
          lastLoginAt = account.lastLoginAt;
        }
      }
    } else {
      deactivated.push(entry);
    }

    if (entry.reasons.length > 0) stale.push(entry);
  }

  // Stable by construction: `sort` is stable in every engine this ships to, so two accounts
  // with the same worst reason stay in the server's order rather than swapping between
  // renders. `?? "dormant"` is unreachable — `stale` only holds entries with a reason — and
  // exists because `noUncheckedIndexedAccess` makes the first element `T | undefined`.
  stale.sort(
    (left, right) =>
      REASON_RANK[left.reasons[0] ?? "dormant"] - REASON_RANK[right.reasons[0] ?? "dormant"],
  );

  return {
    rows: [...active, ...deactivated],
    activeCount: active.length,
    deactivatedCount: deactivated.length,
    lastLoginAt,
    stale,
    isPossiblyTruncated: items.length >= MAX_ADMIN_ACCOUNTS,
  };
}
