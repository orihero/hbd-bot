/**
 * §12.2's RBAC matrix, asserted AS DATA — the same shape §14's Slice 1c acceptance demands
 * of the server ("parameterised over §12.2 as data and passes for all four roles").
 *
 * The table below is transcribed from the plan independently of `rbac.ts`. That is the whole
 * value: if someone edits the mirror, this fails; if someone edits both to match a wrong
 * belief, the diff shows two files changing and a reviewer asks why.
 */

import { describe, expect, it } from "vitest";

import { ADMIN_ROLE_VALUES, PERMISSION_VALUES, type AdminRole, type Permission } from "@/api";

import { ROLE_PERMISSIONS, hasAllPermissions, hasAnyPermission, hasPermission } from "./rbac";

/**
 * §12.2, transcribed — with the `/admins` rows taken from §6.8's endpoint table instead,
 * which is the ruling on the two sections' contradiction. `—` in the plan means the role is
 * absent from the row.
 */
const EXPECTED: Readonly<Record<Permission, readonly AdminRole[]>> = {
  "session.self": ["viewer", "support", "admin", "owner"],
  "dashboard.read": ["viewer", "support", "admin", "owner"],
  "records.read": ["viewer", "support", "admin", "owner"],
  "chat.index.read": ["viewer", "support", "admin", "owner"],
  "wizard_state.read": ["viewer", "support", "admin", "owner"],
  "moderation.queue.read": ["viewer", "support", "admin", "owner"],
  "config.read": ["viewer", "support", "admin", "owner"],
  "retention.read": ["viewer", "support", "admin", "owner"],
  "reveal.personal_data": ["support", "admin", "owner"],
  "reveal.media": ["support", "admin", "owner"],
  "order.retry": ["admin", "owner"],
  "order.force_deliver": ["admin", "owner"],
  "user.block": ["admin", "owner"],
  "moderation.reveal": ["admin", "owner"],
  "moderation.decide": ["admin", "owner"],
  "retention.sweep": ["admin", "owner"],
  "audit.read": ["admin", "owner"],
  "reveal.volume.read": ["admin", "owner"],
  "export.aggregate": ["admin", "owner"],
  "user.purge": ["owner"],
  "config.write": ["owner"],
  "order.evidence_export": ["owner"],
  "audit.export": ["owner"],
  // §6.8 line 949 for the read (`| GET | /admins | List | W |`), §12.2 for the writes it
  // used to collapse into the same row. Two rows, one column: OWNER holds both and nobody else holds
  // either.
  "admin.read": ["owner"],
  "admin.manage": ["owner"],
};

describe("the §12.2 matrix", () => {
  it("covers every permission the API declares", () => {
    expect(Object.keys(EXPECTED).sort()).toEqual([...PERMISSION_VALUES].sort());
  });

  for (const role of ADMIN_ROLE_VALUES) {
    for (const permission of PERMISSION_VALUES) {
      const granted = EXPECTED[permission].includes(role);
      it(`${role} ${granted ? "holds" : "does not hold"} ${permission}`, () => {
        expect(hasPermission(role, permission)).toBe(granted);
        expect(ROLE_PERMISSIONS[role].has(permission)).toBe(granted);
      });
    }
  }
});

describe("an unknown role", () => {
  it("holds nothing — a null role is 'not known yet', never 'allowed'", () => {
    for (const permission of PERMISSION_VALUES) {
      expect(hasPermission(null, permission)).toBe(false);
      expect(hasPermission(undefined, permission)).toBe(false);
    }
  });
});

describe("the reads that matter for what the console draws", () => {
  it("hides Audit from VIEWER and SUPPORT (§12.2: audit.read is admin+)", () => {
    expect(hasPermission("viewer", "audit.read")).toBe(false);
    expect(hasPermission("support", "audit.read")).toBe(false);
    expect(hasPermission("admin", "audit.read")).toBe(true);
    expect(hasPermission("owner", "audit.read")).toBe(true);
  });

  it("hides Admins from everyone but OWNER", () => {
    // The nav entry and the screen are gated on `admin.read` — the roster GET's own cell.
    expect(ADMIN_ROLE_VALUES.filter((role) => hasPermission(role, "admin.read"))).toEqual([
      "owner",
    ]);
    expect(ADMIN_ROLE_VALUES.filter((role) => hasPermission(role, "admin.manage"))).toEqual([
      "owner",
    ]);
  });

  it("gives every role config.read — secrets are absent at every role, not gated", () => {
    for (const role of ADMIN_ROLE_VALUES) {
      expect(hasPermission(role, "config.read")).toBe(true);
    }
  });

  it("separates 'see a customer's words' from 'change the system's state'", () => {
    // The distinction §12.2 opens with: SUPPORT reveals but cannot retry; the plan's
    // OPERATOR (wire spelling `admin`) retries but is not thereby a reader of everything.
    expect(hasPermission("support", "reveal.personal_data")).toBe(true);
    expect(hasPermission("support", "order.retry")).toBe(false);
    expect(hasPermission("admin", "order.retry")).toBe(true);
  });
});

describe("anyOf / allOf", () => {
  it("anyOf is true when one matches", () => {
    expect(hasAnyPermission("support", ["order.retry", "reveal.media"])).toBe(true);
  });

  it("anyOf over an empty list is false, never 'unguarded'", () => {
    expect(hasAnyPermission("owner", [])).toBe(false);
  });

  it("allOf needs every one", () => {
    expect(hasAllPermissions("admin", ["order.retry", "audit.read"])).toBe(true);
    expect(hasAllPermissions("admin", ["order.retry", "admin.manage"])).toBe(false);
  });

  it("allOf over an empty list is false, same reason", () => {
    expect(hasAllPermissions("owner", [])).toBe(false);
  });
});
