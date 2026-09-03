/**
 * Who is signed in — read from TanStack Query, never mirrored into Zustand.
 *
 * §11.1 allows exactly three client stores and none of them is the session. A role copied
 * into Zustand and a role in the query cache disagree the moment a re-auth lands, and the
 * disagreement always surfaces as an affordance shown to someone who has lost it.
 *
 * `GET /api/auth/me` is the single source. Every caller shares one query key
 * (`queryKeys.auth.me()`), so the NavRail, the account menu and every `PermissionGate` on
 * screen cost one request between them.
 */

import { useQuery } from "@tanstack/react-query";

import type { AdminRole, ApiFailure, MeResponse, Permission } from "@/api";
import { failureOf, getMe, unwrapAsync } from "@/api";
import { queryKeys } from "@/lib/queryKeys";

import { hasAllPermissions, hasAnyPermission, hasPermission } from "./rbac";

export interface Session {
  /** `null` until the first answer, and after the session ends. */
  readonly me: MeResponse | null;
  /** Convenience for the common case. `null` means "not known yet", never "no rights". */
  readonly role: AdminRole | null;
  readonly isPending: boolean;
  /** Set when `/auth/me` failed. `UNAUTHENTICATED` here means the session is over. */
  readonly failure: ApiFailure | null;
  /** §12.6: a bootstrapped account must change its password before doing anything else. */
  readonly mustChangePassword: boolean;
}

export function useSession(): Session {
  const query = useQuery({
    queryKey: queryKeys.auth.me(),
    queryFn: ({ signal }) => unwrapAsync(getMe({ signal })),
    // The signed-in identity does not change under the operator's feet; a poll here would
    // be one request per five seconds asking a question whose answer only a logout changes.
    staleTime: 60_000,
    refetchOnWindowFocus: true,
  });

  const me = query.data ?? null;
  return {
    me,
    role: me?.role ?? null,
    isPending: query.isPending,
    failure: failureOf(query.error),
    mustChangePassword: me?.mustChangePassword ?? false,
  };
}

/** The current role, or `null` while it is unknown. */
export function useRole(): AdminRole | null {
  return useSession().role;
}

/** Whether the signed-in role holds a §12.2 permission. `false` while the role is unknown. */
export function useHasPermission(permission: Permission): boolean {
  return hasPermission(useRole(), permission);
}

/** Whether the signed-in role holds at least one of these. */
export function useHasAnyPermission(permissions: readonly Permission[]): boolean {
  return hasAnyPermission(useRole(), permissions);
}

/** Whether the signed-in role holds every one of these. */
export function useHasAllPermissions(permissions: readonly Permission[]): boolean {
  return hasAllPermissions(useRole(), permissions);
}
