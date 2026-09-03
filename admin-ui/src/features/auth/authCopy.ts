/**
 * The auth screens' pinned copy, and the one derivation they share.
 *
 * Every string here mirrors a decision the SERVER already made, and getting one of them
 * "friendlier" would undo it:
 *
 *  - **No user enumeration.** §12.1 T1: an unknown username is verified against a
 *    module-level dummy hash "so timing and response match". The 401's message is
 *    `"that username and password do not match an active account"` for both cases. The UI
 *    renders whatever the server said and adds a line explaining that the answer is the same
 *    either way — the explanation is what stops an operator reading the sameness as a bug and
 *    "fixing" it.
 *  - **Two limiters, one message.** A 429 can come from the strict `(username, client_ip)`
 *    counter at 10/15 min or from the looser per-username ceiling at 100/15 min. The panel
 *    does not say which: the second one is a DoS an attacker aims at a known username, and
 *    telling them it worked is telling them it worked.
 *  - **`mustChangePassword` is a gate, not a suggestion.** While it is true, every route
 *    except `POST /api/auth/password` and `GET /api/auth/me` is a 403 — logout included. So
 *    the rotation screen offers no way out, because there is none to offer.
 */

/** §12.1 T1, in the operator's words. Never "unknown username". */
export const INDISTINGUISHABLE_NOTE =
  "The same answer is given for a username that does not exist and for a wrong password. That is deliberate.";

export const RATE_LIMITED_TITLE = "Too many attempts";

/** Deliberately does not say WHICH counter tripped. */
export const RATE_LIMITED_NOTE =
  "Sign-in attempts are limited per account and per address. Waiting is the only remedy — the counter does not reset on a correct password.";

/** `REAUTH_RATE_LIMITED` is a different code precisely because it has a remedy (§6.2). */
export const REAUTH_LIMITED_NOTE =
  "Password changes are limited per session. Signing in again starts a fresh window.";

export const FORCED_ROTATION_TITLE = "Choose a new password";

export const FORCED_ROTATION_NOTE =
  "This account was created with a temporary password. Until it is changed, every other route — including signing out — answers 403, so there is nothing else to do from here.";

/** The dev-only 403 that looks like a bug and is a correctly-configured origin check. */
export const ORIGIN_REJECTED_HINT =
  "In development this means HBD_ADMIN_PUBLIC_ORIGIN does not match the address in the URL bar. The dev proxy keeps the browser's Origin on purpose.";

/** Seconds left on a `Retry-After`, floored at zero. `null` when the server sent none. */
export function retrySecondsLeft(until: number | null, now: number): number | null {
  if (until === null) return null;
  return Math.max(0, Math.ceil((until - now) / 1_000));
}

/** When a `Retry-After` expires, as an epoch milli. `null` when there was no header. */
export function retryDeadline(retryAfterS: number | null, now: number): number | null {
  return retryAfterS === null ? null : now + retryAfterS * 1_000;
}
