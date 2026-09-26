/**
 * The first 401 on any read ends the tab.
 *
 * `state/auth.ts` says the app learns about an expired session on the next `me()` — which,
 * before these screens called the API, meant the next page load. A screen that keeps reading
 * with a dead cookie shows an operator empty panels, a nav rail still naming their account,
 * and Block / Grant / Reveal affordances that are still drawn and still pressable — every
 * press now a refused request. So the first 401 clears the store through `signOut()` (the
 * server refuses the logout, which is fine: the tab drops the session either way) and
 * `RequireAuth` takes it to `/login`.
 *
 * Once, and only once: several queries reach 401 within a tick of each other, and a second
 * logout is an audit row saying nothing new.
 *
 * It lives here rather than in one screen because every screen that reads needs it, and the
 * one that was written without it — the customer detail — is exactly the screen where the
 * stale affordances are privileged writes.
 */

import { useEffect, useRef } from "react";

import type { AdminQueryError } from "@/lib/adminQuery";
import { useAuthStore } from "@/state/auth";

export function useSessionGuard(errors: readonly (AdminQueryError | null)[]): void {
  const signOut = useAuthStore((state) => state.signOut);
  const done = useRef(false);
  const isExpired = errors.some((error) => error !== null && error.status === 401);

  useEffect(() => {
    if (!isExpired || done.current) return;
    done.current = true;
    void signOut();
  }, [isExpired, signOut]);
}
