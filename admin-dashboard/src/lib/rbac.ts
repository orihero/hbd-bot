/**
 * §12.2's RBAC matrix, mirrored on the client for ONE purpose: deciding what to RENDER.
 *
 * The server is the authority and this table is not — `src/bayram/admin/security/permissions.py`
 * holds the real matrix and every route calls `require(...)`. What this buys is role-based
 * **hiding**, not disabling. A privileged button an operator cannot use is worse than no
 * button: pressing it writes a `permission.denied` audit row against someone who did nothing
 * wrong, and it teaches them that half the console is broken.
 *
 * Drift is safe in one direction only. Stricter than the server costs an operator an
 * affordance; looser hands them a 403 and that audit row. So when in doubt, omit a role.
 *
 * Only the cells this app can actually spend are listed. A screen that needs another one adds
 * it here rather than testing `role === "owner"` inline — three inline role checks disagree
 * eventually, and the disagreement is always a grant.
 *
 * The wire spells the third role `"admin"`; §12.2's table heads that column OPERATOR. Same
 * role. The wire spelling wins, because `/auth/me` renders `"admin"`.
 */

import type { MeResponse } from "@/api/auth";
import { useAuthStore } from "@/state/auth";

/** The four roles, as `/auth/me` spells them. Taken from the API type, never restated. */
export type AdminRole = MeResponse["role"];

/**
 * The cells this console renders against.
 *
 * `reveal.personal_data` is the `A+S` cell `POST /api/reveal` ultimately spends; the server
 * also guards the router with its ROLE half (`reveal.personal_data.read`, SUPPORT and above)
 * so that a correctly re-authenticated SUPPORT operator is not refused by a guard that holds
 * no subject. That split is a server mechanism and is deliberately not mirrored: both halves
 * name the same three roles here.
 *
 * `user.block.write` and `credit.grant.write` are the ROLE halves the two writers are guarded
 * by — `permissions.py` gives them `_row(admin=_W, owner=_W)`. They are what a Block or a
 * Grant button must be gated on, because they are what the routers actually check.
 *
 * `rail.control` and `payment.notify` are the Payme rail's two cells and they are deliberately
 * SEPARATE. Both are plain `W` on the server — neither is a step-up cell — but they answer
 * different questions: `rail.control` stops the business selling, and `payment.notify` re-sends
 * a confirmation a customer was already owed. Riding the notify on `rail.control` would have
 * been one fewer constant and would have handed a support operator the switch; giving pause a
 * step-up would have been worse than either, because `check_role` holds no subject and so
 * answers `STEP_UP_REQUIRED` for ever at OWNER while looking exactly correct.
 */
export type Permission =
  | "reveal.personal_data"
  | "user.block.write"
  | "credit.grant.write"
  | "broadcast.write"
  | "rail.control"
  | "payment.notify";

const SUPPORT_UP: readonly AdminRole[] = ["support", "admin", "owner"];
const OPERATOR_UP: readonly AdminRole[] = ["admin", "owner"];

/** Which roles hold a cell. A role absent from the list has none, which is a denial. */
export const RBAC_MATRIX: Readonly<Record<Permission, readonly AdminRole[]>> = {
  "reveal.personal_data": SUPPORT_UP,
  "user.block.write": OPERATOR_UP,
  "credit.grant.write": OPERATOR_UP,
  "broadcast.write": OPERATOR_UP,
  "rail.control": OPERATOR_UP,
  "payment.notify": SUPPORT_UP,
};

/**
 * Whether a role holds a permission.
 *
 * An unknown role — `null` before `bootstrap()` answers, or after a session ends — holds
 * nothing, so a privileged control never flashes on screen for someone who cannot use it.
 */
export function hasPermission(role: AdminRole | null, permission: Permission): boolean {
  return role !== null && RBAC_MATRIX[permission].includes(role);
}

/** VIEWER has no reveal cell at all: the affordance is absent, not disabled (rule 4). */
export function canReveal(role: AdminRole | null): boolean {
  return hasPermission(role, "reveal.personal_data");
}

/** Block and unblock share one cell: they are the two directions of one idempotent write. */
export function canBlockUsers(role: AdminRole | null): boolean {
  return hasPermission(role, "user.block.write");
}

export function canGrantCredits(role: AdminRole | null): boolean {
  return hasPermission(role, "credit.grant.write");
}

/**
 * Whether this role may COMPOSE a campaign — create it, revise it, send it.
 *
 * The server's `broadcast.write` cell is ADMIN and OWNER; reading the campaign list and one
 * campaign's detail is `broadcast.read`, which every role holds, and neither is mirrored here
 * because neither hides anything. This one does: "Message these users" on the directory is a
 * button that would 403 for a viewer or a support operator, and a 403 on a press is a
 * `permission.denied` audit row against somebody who did nothing wrong.
 *
 * The step-up half (`broadcast.send`) is deliberately NOT a separate cell here. It is held by
 * the same two roles and is spent through a password round trip the dialog already drives, so
 * a second constant would only be a second thing to keep in step.
 */
export function canWriteBroadcasts(role: AdminRole | null): boolean {
  return hasPermission(role, "broadcast.write");
}

/**
 * Whether this role may PAUSE or RESUME the checkout rail.
 *
 * ADMIN and OWNER. Used to hide the switch, never to disable it: a support operator who
 * pressed it would get a 403 and a `permission.denied` audit row against somebody who did
 * nothing wrong, and would learn that a section of the console is broken.
 *
 * There is no step-up half to mirror. `permissions.py` keeps `RAIL_CONTROL` out of
 * `STEP_UP_ACTIONS` on purpose, and if that is ever revisited the remedy on the server is a
 * `RAIL_CONTROL_WRITE` + `RAIL_CONTROL` split — never adding the existing member to the
 * mapping, which would ship a route that refuses an owner for ever. Nothing changes here
 * either way: this constant names the ROLE half, which is what the router checks.
 */
export function canControlRail(role: AdminRole | null): boolean {
  return hasPermission(role, "rail.control");
}

/**
 * Whether this role may re-send a payment confirmation.
 *
 * SUPPORT and above, which is a wider cell than `rail.control` on purpose: support is who
 * takes the "I paid and nothing happened" call, and this is the single most common answer to
 * it. It writes no money row and no state a customer can spend.
 */
export function canNotifyPayment(role: AdminRole | null): boolean {
  return hasPermission(role, "payment.notify");
}

/** The signed-in role, or `null` while unknown. The one place a component reads it. */
export function useRole(): AdminRole | null {
  return useAuthStore((state) => state.account?.role ?? null);
}

export function useCanReveal(): boolean {
  return canReveal(useRole());
}

export function useCanBlockUsers(): boolean {
  return canBlockUsers(useRole());
}

export function useCanGrantCredits(): boolean {
  return canGrantCredits(useRole());
}

export function useCanWriteBroadcasts(): boolean {
  return canWriteBroadcasts(useRole());
}

export function useCanControlRail(): boolean {
  return canControlRail(useRole());
}

export function useCanNotifyPayment(): boolean {
  return canNotifyPayment(useRole());
}
