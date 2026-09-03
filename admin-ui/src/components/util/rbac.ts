/**
 * §12.2's RBAC matrix, mirrored on the client for ONE purpose: deciding what to render.
 *
 * **The server is the authority and this table is not.** `src/hbd/admin/security/permissions.py`
 * holds `RBAC_MATRIX` and every route calls `require(...)`; nothing here can grant anything.
 * What this table buys is §11.4's rule — role-based **hiding**, not disabling. A disabled
 * button nobody can explain is worse than an absent one, and an operator must not discover
 * their role by clicking and collecting a `permission.denied` audit row.
 *
 * Two consequences follow, and both are deliberate:
 *
 *  - Drift is safe in one direction only. If this table is *stricter* than the server the
 *    operator loses an affordance; if it is *looser* they get a 403 and an audit row. So
 *    when in doubt, omit a role. The `satisfies` below makes a NEW `Permission` a compile
 *    error rather than a silent denial-of-everything.
 *  - The wire spells the third role `"admin"`. §12.2's table heads that column **OPERATOR**.
 *    They are the same role — `permissions.py` says so in a comment — and this file uses the
 *    wire spelling, because `AdminAccountView.role` renders `"admin"` and a console that
 *    shows one word in the roster and another in a tooltip is a support call.
 */

import type { AdminRole, Permission } from "@/api";
import { ADMIN_ROLE_VALUES, PERMISSION_VALUES } from "@/api";

const ALL: readonly AdminRole[] = ADMIN_ROLE_VALUES;
const OPERATOR_UP: readonly AdminRole[] = ["admin", "owner"];
const SUPPORT_UP: readonly AdminRole[] = ["support", "admin", "owner"];
const OWNER_ONLY: readonly AdminRole[] = ["owner"];

/**
 * Which roles hold a cell in §12.2's row for this permission. A role absent from the list
 * has no cell, which is a denial — the same reading `_row(...)` gives it server-side.
 */
export const RBAC_MATRIX = {
  "session.self": ALL,
  "dashboard.read": ALL,
  "records.read": ALL,
  "chat.index.read": ALL,
  "wizard_state.read": ALL,
  "moderation.queue.read": ALL,
  "config.read": ALL,
  "retention.read": ALL,
  "reveal.personal_data": SUPPORT_UP,
  "reveal.media": SUPPORT_UP,
  "order.retry": OPERATOR_UP,
  "order.force_deliver": OPERATOR_UP,
  "user.block": OPERATOR_UP,
  "moderation.reveal": OPERATOR_UP,
  "moderation.decide": OPERATOR_UP,
  "retention.sweep": OPERATOR_UP,
  "audit.read": OPERATOR_UP,
  "reveal.volume.read": OPERATOR_UP,
  "export.aggregate": OPERATOR_UP,
  "user.purge": OWNER_ONLY,
  "config.write": OWNER_ONLY,
  "order.evidence_export": OWNER_ONLY,
  "audit.export": OWNER_ONLY,
  // The `/admins` pair. §12.2 had one `W+S` row for all five endpoints; §6.8 line 949
  // splits the roster GET out as a bare owner `W`, and the endpoint table is the
  // authority. Both are OWNER-only here, which is all this table decides — the step-up
  // difference between them is the server's business and is not mirrored.
  "admin.read": OWNER_ONLY,
  "admin.manage": OWNER_ONLY,
} as const satisfies Record<Permission, readonly AdminRole[]>;

/**
 * The §12.1 T9 shape, DERIVED from the matrix rather than restated beside it — two
 * hand-maintained copies of an authorisation table disagree eventually, and the
 * disagreement is always a grant.
 */
function permissionsFor(role: AdminRole): ReadonlySet<Permission> {
  return new Set(PERMISSION_VALUES.filter((permission) => RBAC_MATRIX[permission].includes(role)));
}

export const ROLE_PERMISSIONS: Readonly<Record<AdminRole, ReadonlySet<Permission>>> = {
  viewer: permissionsFor("viewer"),
  support: permissionsFor("support"),
  admin: permissionsFor("admin"),
  owner: permissionsFor("owner"),
};

/**
 * Whether a role holds a permission. An unknown role — `null` while `/auth/me` is in
 * flight, or after a session ends — holds nothing: the affordance stays hidden until the
 * answer arrives, so a privileged control never flashes on screen for someone who cannot
 * use it.
 */
export function hasPermission(
  role: AdminRole | null | undefined,
  permission: Permission,
): boolean {
  if (role === null || role === undefined) return false;
  return ROLE_PERMISSIONS[role].has(permission);
}

/** True when the role holds at least one of these. Empty list → false, never "unguarded". */
export function hasAnyPermission(
  role: AdminRole | null | undefined,
  permissions: readonly Permission[],
): boolean {
  return permissions.some((permission) => hasPermission(role, permission));
}

/** True only when the role holds every one of these. Empty list → false, same reason. */
export function hasAllPermissions(
  role: AdminRole | null | undefined,
  permissions: readonly Permission[],
): boolean {
  if (permissions.length === 0) return false;
  return permissions.every((permission) => hasPermission(role, permission));
}

/**
 * Whether a role satisfies a `PermissionGate`'s conditions.
 *
 * It lives beside the matrix rather than in the component so a table column, a keyboard
 * shortcut or a route guard can ask the same question without rendering anything.
 *
 * A gate with NO conditions renders its children: it is a no-op wrapper, not an accidental
 * deny-all that would silently blank a screen.
 */
export function isPermitted(
  role: AdminRole | null | undefined,
  conditions: {
    readonly permission?: Permission | undefined;
    readonly anyOf?: readonly Permission[] | undefined;
    readonly allOf?: readonly Permission[] | undefined;
  },
): boolean {
  const { permission, anyOf, allOf } = conditions;
  if (permission !== undefined && !hasPermission(role, permission)) return false;
  if (anyOf !== undefined && !hasAnyPermission(role, anyOf)) return false;
  if (allOf !== undefined && !hasAllPermissions(role, allOf)) return false;
  return true;
}
