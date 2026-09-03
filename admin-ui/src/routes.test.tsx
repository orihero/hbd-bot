/**
 * The route table, pinned against the two failures it can have that nothing else catches.
 *
 * **A `lazy()` that resolves to nothing.** `import("@/features/x/XScreen")` is checked by the
 * compiler, but `lazy()` resolving a module's `Component` export is a runtime contract with
 * React Router: a screen file that renames or drops that export still typechecks, still
 * builds, and then renders a blank page with a console error the operator never sees. This
 * file awaits every `lazy()` in the table and asserts a component came back.
 *
 * **A screen left as a placeholder.** Seven agents built these in parallel against
 * placeholder files. A route still pointing at one is the integration bug this suite exists
 * to make loud, so `ScreenPlaceholder` no longer exists and nothing may reintroduce a route
 * that renders "not built yet".
 *
 * It also enters the module graph through `@/routes`, which is `main.tsx`'s entry order and
 * the one that breaks if anyone adds a module-scope read of a `@/routes` binding to
 * `components/layout` (see `components/layout/routerCycle.test.tsx`).
 */

import { QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { RouterProvider, createMemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";

import {
  ensureMatchMedia,
  makeTestQueryClient,
  meFixture,
} from "@/components/util/testRender";
import { queryKeys } from "@/lib";

import { ROUTES, routeObjects, href } from "@/routes";

/** Every `{ path, lazy }` leaf in the table, flattened, with its full path. */
function leaves(): { path: string; lazy: NonNullable<(typeof routeObjects)[number]["lazy"]> }[] {
  const found: { path: string; lazy: NonNullable<(typeof routeObjects)[number]["lazy"]> }[] = [];
  for (const route of routeObjects) {
    if (route.lazy !== undefined && route.path !== undefined) {
      found.push({ path: route.path, lazy: route.lazy });
    }
    for (const child of route.children ?? []) {
      if (child.lazy === undefined) continue;
      const suffix = child.index === true ? "" : (child.path ?? "");
      found.push({ path: `/${suffix}`, lazy: child.lazy });
    }
  }
  return found;
}

describe("the route table", () => {
  it("resolves every lazy route to a real Component", async () => {
    const resolved = await Promise.all(
      leaves().map(async (leaf) => ({
        path: leaf.path,
        module: await leaf.lazy(),
      })),
    );
    expect(resolved.length).toBeGreaterThan(0);
    for (const { path, module } of resolved) {
      expect(typeof module.Component, `${path} has no Component export`).toBe("function");
    }
  });

  it("renders no placeholder screen — every route is a built one", async () => {
    const modules = await Promise.all(leaves().map(async (leaf) => leaf.lazy()));
    for (const module of modules) {
      expect(Object.keys(module)).not.toContain("ScreenPlaceholder");
    }
  });

  it("covers every ROUTES entry with a route object", () => {
    const paths = new Set(
      routeObjects.flatMap((route) => [
        route.path,
        ...(route.children ?? []).map((child) =>
          child.index === true ? "/" : `/${child.path ?? ""}`,
        ),
      ]),
    );
    for (const [name, path] of Object.entries(ROUTES)) {
      // Parameterised routes carry the same template on both sides.
      expect(paths.has(path), `${name} (${path}) is in ROUTES with no route object`).toBe(true);
    }
  });

  it("builds hrefs that match the templates they stand for", () => {
    expect(href.order("abc def")).toBe("/orders/abc%20def");
    expect(href.user(770_000_123)).toBe("/users/770000123");
    expect(href.nameStrategies()).toBe(ROUTES.nameStrategies);
  });
});

/**
 * The boot smoke test: the real router, the real shell, the real lazy screens.
 *
 * `main.tsx` is three lines around `createRouter()`, so this is as close to "the console
 * starts" as a jsdom can get — and it is the test that would have caught the class of bug
 * the parallel build was most exposed to: a module-scope read across the
 * `routes → RootLayout → AppShell → CommandPalette → routes` cycle, which typechecks,
 * bundles, and then throws on the first render.
 */
describe("booting the router", () => {
  it("mounts the shell and a lazy screen from a deep link", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(() =>
        Promise.resolve({
          ok: false,
          status: 401,
          headers: { get: () => null },
          json: () =>
            Promise.resolve({
              error: { code: "UNAUTHENTICATED", message: "no", correlationId: "c" },
            }),
        } as unknown as Response),
      ),
    );
    /*
     * The data router builds a `Request` for every navigation. Node's undici `Request`
     * rejects jsdom's `AbortSignal` as "not an instance of AbortSignal" — a runtime seam,
     * not an app bug (a browser has one implementation of both). A transparent stand-in
     * keeps the navigation on the code under test.
     */
    vi.stubGlobal(
      "Request",
      class {
        readonly signal: AbortSignal | undefined;
        constructor(
          readonly url: string,
          init?: { signal?: AbortSignal },
        ) {
          this.signal = init?.signal;
        }
      },
    );
    const client = makeTestQueryClient();
    client.setQueryData(queryKeys.auth.me(), meFixture("owner"));
    ensureMatchMedia();

    const router = createMemoryRouter(routeObjects, { initialEntries: ["/assets"] });
    render(
      <QueryClientProvider client={client}>
        <RouterProvider router={router} />
      </QueryClientProvider>,
    );

    // The rail is the shell; the heading is the lazy screen having resolved and rendered.
    // Named, because the shell now has TWO navigation landmarks: the rail and the page
    // header's breadcrumb trail. An unnamed lookup would pass or fail depending on which
    // screen was mounted, which is not what this assertion is about.
    expect(await screen.findByRole("navigation", { name: "Sections" })).toBeInTheDocument();
    expect(await screen.findByRole("heading", { name: "Assets", level: 1 })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Orders" })).toHaveAttribute("href", "/orders");
    vi.unstubAllGlobals();
  });
});
