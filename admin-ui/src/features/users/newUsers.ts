/**
 * The 30-day new-user series behind `/users`'s dominant signal (§11.2).
 *
 * §11.2 asks for "Total users + 30-day new-user sparkline". There is **no**
 * `/metrics/users-by-day` endpoint on this build — `dashboard.py` publishes orders-by-day,
 * failures, latency and name-strategies and nothing about accounts — so the series has to
 * be derived on the client from one windowed page of `GET /api/users`.
 *
 * Three consequences, all deliberate:
 *
 *  - **The bucket is `accountCreatedAt`, and that column is the FIRST ORDER's timestamp.**
 *    `userViewSchema` says so: "there is no signup event to date an account from". So this
 *    is "accounts that became real", not "people who opened the bot" — the same reason
 *    §11.2 refuses to head the list's date column "last seen".
 *  - **The window is closed at both ends.** Not because `/api/users` rejects a half one —
 *    it accepts a lone bound now and closes the open end at the instant it was served — but
 *    because an end recomputed per request is a DIFFERENT end per request, and this series
 *    is bucketed by day: two pages closed at two instants can land a row in two buckets or
 *    none. One pinned `to` is what makes the thirty buckets add up.
 *  - **A truncated page yields no series at all.** Users come back newest account first, so
 *    a partial page covers the most recent days and silently drops the older ones — a
 *    sparkline built from it would show a cliff that is an artefact of the page size. When
 *    `meta.nextCursor` is non-null the caller renders the total alone and says why.
 */

import type { UserView } from "@/api";

/** §11.2's window. Thirty days, inclusive of today. */
export const NEW_USER_WINDOW_DAYS = 30;

export const DAY_MS = 86_400_000;

/** The UTC midnight at or before `ms`. UTC, not local: every column is `timestamptz`. */
export function utcDayStart(ms: number): number {
  return Math.floor(ms / DAY_MS) * DAY_MS;
}

export interface NewUserWindow {
  /** RFC 3339, always with a `Z`. Goes straight into `UsersQuery.from`. */
  readonly from: string;
  /** RFC 3339, always with a `Z`. Pinned at build time, never "now" at request time. */
  readonly to: string;
  /** The UTC midnight the first bucket starts at. */
  readonly fromDayMs: number;
  /** How many daily buckets the series has. */
  readonly days: number;
}

/**
 * The window to ask the API for, and the bucket origin to fold the answer into.
 *
 * `to` is pinned to the moment this was called rather than left open, so a keyset walk
 * through the same window returns pages of one shape.
 */
export function newUserWindow(
  now: number = Date.now(),
  days: number = NEW_USER_WINDOW_DAYS,
): NewUserWindow {
  const span = Math.max(1, days);
  const fromDayMs = utcDayStart(now) - (span - 1) * DAY_MS;
  return {
    from: new Date(fromDayMs).toISOString(),
    to: new Date(now).toISOString(),
    fromDayMs,
    days: span,
  };
}

/**
 * Daily new-account counts, oldest day first, zero-filled.
 *
 * Zero-filling is right HERE and wrong on the wire: the API omits empty days because an
 * absent day and a zero day are different facts about a query, but a sparkline with a gap
 * would compress its own x-axis and draw a shape that never happened. The caller chose the
 * range, so the caller fills it.
 */
export function buildNewUserSeries(
  users: readonly UserView[],
  window: NewUserWindow,
): readonly number[] {
  const counts = new Array<number>(window.days).fill(0);
  for (const user of users) {
    const at = Date.parse(user.accountCreatedAt);
    if (!Number.isFinite(at)) continue;
    const index = Math.floor((at - window.fromDayMs) / DAY_MS);
    if (index < 0 || index >= window.days) continue;
    counts[index] = (counts[index] ?? 0) + 1;
  }
  return counts;
}
