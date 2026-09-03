/**
 * The import cycle, pinned.
 *
 * `routes.tsx` → `RootLayout` → `AppShell` → `NavRail` → `navItems.ts` → `routes.tsx` is a
 * real ESM cycle and cannot be removed: the router needs a shell, and the shell needs the
 * route table. It is safe only while nothing READS a binding from `@/routes` during module
 * evaluation — `navHref()` and `routeHref()` exist for exactly that reason.
 *
 * This file is the guard, and it matters that it enters the cycle from the ROUTER side.
 * `NavRail.test.tsx` enters from `NavRail`, which is the order that happens to work even
 * with a module-scope read; `main.tsx` enters from `@/routes`, which is the order that
 * breaks. A regression here shows up as `href` being `undefined` on every rail item and
 * every palette row — a silently unnavigable console, not a crash.
 */

import { screen } from "@testing-library/react";
import { beforeEach, describe, expect, it } from "vitest";

// Deliberately FIRST: this is the entry order `main.tsx` uses.
import { ROUTES } from "@/routes";

import { meFixture, renderWithProviders, resetPrefs } from "@/components/util/testRender";

import { NavRail } from "./NavRail";
import { PRIMARY_NAV, SECONDARY_NAV, navHref } from "./navItems";
import { resolvePalette } from "./paletteResolve";

beforeEach(() => {
  resetPrefs();
});

describe("entering the cycle from @/routes", () => {
  it("resolves every routed nav item to a real path", () => {
    for (const item of [...PRIMARY_NAV, ...SECONDARY_NAV]) {
      if (item.route === null) continue;
      const to = navHref(item);
      expect(to, `${item.key} has no href`).toBeDefined();
      expect(to).toBe(ROUTES[item.route]);
      expect(to?.startsWith("/")).toBe(true);
    }
  });

  it("resolves every palette section to a real path", () => {
    for (const result of resolvePalette("")) {
      expect(result.href, `${result.id} has no href`).not.toBeNull();
      expect(result.href).toMatch(/^\//u);
    }
  });

  it("renders the rail with working links, not `to={undefined}`", () => {
    renderWithProviders(<NavRail />, { me: meFixture("owner") });
    expect(screen.getByRole("link", { name: "Orders" })).toHaveAttribute("href", "/orders");
    expect(screen.getByRole("link", { name: "Live" })).toHaveAttribute("href", "/");
  });
});
