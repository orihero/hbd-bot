/**
 * §11.4: role-based **hiding**, not disabling.
 *
 * "A disabled button nobody can explain is worse than an absent one." A greyed-out *Purge*
 * on a SUPPORT screen teaches nothing, invites a click, and — because every refusal writes
 * a `permission.denied` audit row (§12.2) — turns curiosity into noise in the log an
 * incident is later reconstructed from. So the control is simply not there.
 *
 * This gate is a rendering decision and never a security control. `src/bayram/admin/security/
 * permissions.py` enforces; `rbac.ts` mirrors §12.2 so the console can decide what to draw.
 * If the two ever disagree the server wins and the operator sees a 403.
 *
 * While the role is unknown (the `/auth/me` query is in flight) NOTHING is rendered. A
 * privileged control that appears for 200 ms and then vanishes is worse than one that
 * arrives late.
 */

import type { ReactNode } from "react";

import type { AdminRole, Permission } from "@/api";

import { isPermitted } from "./rbac";
import { useRole } from "./useSession";

export interface PermissionGateProps {
  /** The single §12.2 permission this subtree needs. */
  readonly permission?: Permission | undefined;
  /** Rendered when the role holds ANY of these. */
  readonly anyOf?: readonly Permission[] | undefined;
  /** Rendered only when the role holds ALL of these. */
  readonly allOf?: readonly Permission[] | undefined;
  /**
   * Override the signed-in role. For tests and for a screen that already has the role in
   * hand; production code should leave it unset and let the gate read the session.
   */
  readonly role?: AdminRole | null | undefined;
  /**
   * What to render INSTEAD when the check fails.
   *
   * Deliberately not "the same control, disabled" — see the note above. Legitimate uses are
   * an explanation of why a column is absent, or nothing at all, which is the default.
   */
  readonly fallback?: ReactNode;
  readonly children: ReactNode;
}

export function PermissionGate({
  permission,
  anyOf,
  allOf,
  role,
  fallback = null,
  children,
}: PermissionGateProps) {
  const sessionRole = useRole();
  const effectiveRole = role === undefined ? sessionRole : role;
  return isPermitted(effectiveRole, { permission, anyOf, allOf }) ? <>{children}</> : <>{fallback}</>;
}
