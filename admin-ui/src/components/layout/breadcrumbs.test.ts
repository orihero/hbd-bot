/**
 * The trail under every page title.
 *
 * Three of these are requirements rather than descriptions of the current output: a crumb
 * never links somewhere that does not exist, a crumb never prints a customer-facing value,
 * and the last crumb is never a link. The rest pin the shape the design asks for.
 */

import { describe, expect, it } from "vitest";

import { ROUTES } from "@/routes";

import { breadcrumbTrail } from "./breadcrumbs";

describe("breadcrumbTrail", () => {
  it("is just Home on the root, and Home is not a link to the page you are on", () => {
    expect(breadcrumbTrail("/")).toEqual([{ label: "Home", href: null }]);
  });

  it("is Home / Orders on a section, with Home linked and the section not", () => {
    expect(breadcrumbTrail("/orders")).toEqual([
      { label: "Home", href: "/" },
      { label: "Orders", href: null },
    ]);
  });

  it("is Home / Orders / Detail on a record, with the section linked", () => {
    expect(breadcrumbTrail("/orders/0c4f2a1e-6b3d-4d8f-9a21-7f5e8c1b2d30")).toEqual([
      { label: "Home", href: "/" },
      { label: "Orders", href: "/orders" },
      { label: "Detail", href: null },
    ]);
  });

  it("names a nested section rather than calling it Detail", () => {
    expect(breadcrumbTrail("/generations/names")).toEqual([
      { label: "Home", href: "/" },
      { label: "Generations", href: "/generations" },
      { label: "Name strategies", href: null },
    ]);
  });

  it("NEVER prints the record's id — that is the §12.3 rule the masking exists for", () => {
    // A breadcrumb is our own chrome label. An order id is not customer content, but a
    // Telegram id identifies a person and the trail is exactly the sort of place a raw
    // value reappears after being masked everywhere else.
    const trail = breadcrumbTrail("/users/987654321");
    expect(trail.map((crumb) => crumb.label)).toEqual(["Home", "Users", "Detail"]);
    expect(JSON.stringify(trail)).not.toContain("987654321");
  });

  it("never links to a path that is not a route", () => {
    // The failure this prevents is a crumb an operator can click to a 404. Every href the
    // trail produces, on every route in the table and on a record beneath it, has to be a
    // real path.
    const real = new Set(Object.values(ROUTES).filter((path) => !path.includes(":")));
    const paths = [
      ...real,
      "/orders/0c4f2a1e-6b3d-4d8f-9a21-7f5e8c1b2d30",
      "/users/987654321",
      "/generations/names",
    ];
    for (const path of paths) {
      for (const crumb of breadcrumbTrail(path)) {
        if (crumb.href !== null) expect(real).toContain(crumb.href);
      }
    }
  });

  it("marks the current page by giving the LAST crumb no href, on every path", () => {
    for (const path of ["/", "/orders", "/orders/abc", "/config", "/generations/names"]) {
      const trail = breadcrumbTrail(path);
      expect(trail.at(-1)?.href).toBeNull();
      // …and every crumb before it IS a link, so the trail is navigable rather than decorative.
      expect(trail.slice(0, -1).every((crumb) => crumb.href !== null)).toBe(true);
    }
  });

  it("resolves ROUTES lazily, so the router import cycle cannot empty the link set", () => {
    // `routes.tsx` → RootLayout → AppShell → PageHeader → breadcrumbs → routes.tsx. Reading
    // ROUTES at module scope gets `undefined` mid-cycle; quieting that with `?? {}` would
    // yield an empty set and silently stop every crumb being a link. This asserts the
    // observable consequence: a section crumb IS linked.
    expect(breadcrumbTrail("/orders/abc")[1]?.href).toBe(ROUTES.orders);
  });
});
