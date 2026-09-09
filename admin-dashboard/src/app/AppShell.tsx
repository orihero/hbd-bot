/**
 * The frame every authenticated screen renders inside: the rail, and the page beside it.
 *
 * The DOCUMENT scrolls, not an inner element. An `overflow-y-auto` wrapper around the outlet
 * is the other obvious build and it costs more than it looks: the browser stops restoring
 * scroll position on back/forward, `#anchor` navigation stops working, `position: sticky`
 * inside a screen starts measuring against the wrapper instead of the viewport, and iOS drops
 * the address-bar collapse. The rail is `position: sticky` precisely so none of that is
 * needed — it pins itself while the page scrolls past.
 *
 * Direction is the only thing that changes across the breakpoint: below 1024px `NavRail`
 * renders a top bar, so the shell stacks; above it, a column beside the page.
 *
 * `TopBar` is inside the CONTENT column rather than above the whole shell, which is what lets
 * it pin at `top-3` beside a rail that pins at `top-3` — one horizontal line across the top of
 * the window, two independently scrolling neighbours under it. Above the shell it would either
 * push the full-height rail down or need the rail's own offset hard-coded into it.
 *
 * `useSystemThemeSync` is mounted here, once, for the whole authenticated app: it is what
 * makes a console left open at sunset follow the machine into dark, and only until the
 * operator picks a side for themselves.
 */

import type { JSX } from "react";
import { Outlet } from "react-router-dom";

import { NavRail } from "@/app/NavRail";
import { TopBar } from "@/app/TopBar";
import { useSystemThemeSync } from "@/state/theme";

export function AppShell(): JSX.Element {
  useSystemThemeSync();

  return (
    <div className="flex min-h-screen flex-col bg-bg lg:flex-row">
      <NavRail />
      {/* `min-w-0` is load-bearing: without it a wide table or chart inside the outlet sets
          this flex item's floor to its own content width and pushes the rail off-screen. */}
      <div className="flex min-w-0 flex-1 flex-col">
        <TopBar />
        <Outlet />
      </div>
    </div>
  );
}
