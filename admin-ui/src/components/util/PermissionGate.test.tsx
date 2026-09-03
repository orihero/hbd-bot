/**
 * §11.4: role-based **hiding**, not disabling.
 *
 * The assertions that matter are the negative ones: nothing is in the DOM, not "something
 * disabled is in the DOM". A `disabled` attribute would still be a discoverable control, and
 * clicking it is how an operator collects a `permission.denied` audit row learning what their
 * role is.
 */

import { screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { PermissionGate } from "./PermissionGate";
import { isPermitted } from "./rbac";
import { meFixture, renderWithProviders } from "./testRender";

describe("PermissionGate", () => {
  it("renders for a role that holds the permission", () => {
    renderWithProviders(
      <PermissionGate permission="order.retry">
        <button type="button">Retry</button>
      </PermissionGate>,
      { me: meFixture("admin") },
    );
    expect(screen.getByRole("button", { name: "Retry" })).toBeInTheDocument();
  });

  it("renders NOTHING — not a disabled control — for a role that does not", () => {
    renderWithProviders(
      <PermissionGate permission="order.retry">
        <button type="button">Retry</button>
      </PermissionGate>,
      { me: meFixture("support") },
    );
    expect(screen.queryByRole("button", { name: "Retry" })).not.toBeInTheDocument();
    expect(screen.queryByText("Retry")).not.toBeInTheDocument();
  });

  it("renders nothing while the role is still unknown", () => {
    // A privileged control that appears for 200ms and then vanishes is worse than one that
    // arrives late.
    renderWithProviders(
      <PermissionGate permission="admin.manage">
        <button type="button">Deactivate</button>
      </PermissionGate>,
      { me: null },
    );
    expect(screen.queryByText("Deactivate")).not.toBeInTheDocument();
  });

  it("takes an explicit role, for a caller that already has one", () => {
    renderWithProviders(
      <PermissionGate permission="admin.manage" role="owner">
        <span>roster</span>
      </PermissionGate>,
      { me: meFixture("viewer") },
    );
    expect(screen.getByText("roster")).toBeInTheDocument();
  });

  it("renders a fallback when given one", () => {
    renderWithProviders(
      <PermissionGate permission="audit.read" fallback={<span>audit is admin-only</span>}>
        <span>the log</span>
      </PermissionGate>,
      { me: meFixture("viewer") },
    );
    expect(screen.getByText("audit is admin-only")).toBeInTheDocument();
    expect(screen.queryByText("the log")).not.toBeInTheDocument();
  });
});

describe("isPermitted", () => {
  it("is a no-op wrapper with no conditions, never an accidental deny-all", () => {
    expect(isPermitted("viewer", {})).toBe(true);
  });

  it("ANDs the three condition forms", () => {
    expect(isPermitted("owner", { permission: "admin.manage", anyOf: ["audit.read"] })).toBe(true);
    expect(isPermitted("admin", { permission: "audit.read", allOf: ["admin.manage"] })).toBe(false);
  });
});
