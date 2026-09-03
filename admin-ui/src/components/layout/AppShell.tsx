/**
 * The authenticated shell: top bar, rail, screen, player.
 *
 * Four placements here are load-bearing and should not be tidied.
 *
 *  1. **`<PlayerBar>` is outside the `<Outlet />`** (§11.1). One `<audio>` element survives
 *     every route change; moving it inside a screen re-mounts it on navigation and cuts the
 *     song off mid-bar.
 *  2. **The `ErrorBoundary` wraps `<main>` only.** A boundary around the whole shell turns a
 *     bug on the audit screen into "the console is down"; scoped here, the rail, the top bar
 *     and the player survive, and the operator can navigate away from the broken screen.
 *  3. **`<main>` is the only scroll container.** The rail and the bar are fixed size
 *     (`--nav-w`, `--topbar-h`), so a long table scrolls under a top bar that stays put — the
 *     LIVE pill must never scroll out of view during an incident. It is also why the browser
 *     gate expects `padding-right: 0` from the modal scroll lock: `<body>` never has a
 *     scrollbar to compensate for.
 *  4. **`<KeyboardShortcuts>` wraps everything**, because it is also the provider for the
 *     shortcut sheet the account menu opens (§11.1 allows exactly three Zustand stores and
 *     this is not one of them).
 *
 * The skip link is first in the DOM and visible on focus. With a rail of eleven items, a
 * keyboard operator would otherwise tab through the whole IA to reach a table on every
 * navigation.
 *
 * ## The one structural change the reskin made
 *
 * The top bar now spans the FULL WIDTH above the rail, where it used to sit in a column to
 * the rail's right. That is what lets the product mark and the env chip be the first two
 * things at the top-left of the window, which is the Gogo idiom and also the placement §11.2
 * wants for "an operator must never be unsure which database they are looking at". Nothing
 * else moved: the rail is still full height beside the screen, `<main>` is still the only
 * scroll container, and the player is still outside it.
 */

import type { ReactNode } from "react";
import { useLocation } from "react-router-dom";

import { ErrorBoundary, KeyboardShortcuts } from "@/components/util";
import { cn } from "@/lib/utils";

import { CommandPalette } from "./CommandPalette";
import { NavRail } from "./NavRail";
import { PlayerBar } from "./PlayerBar";
import { TopBar } from "./TopBar";

export interface AppShellProps {
  readonly children: ReactNode;
}

export function AppShell({ children }: AppShellProps) {
  const location = useLocation();

  return (
    <KeyboardShortcuts>
      <div className="flex h-full min-h-0 flex-col bg-surface text-ink">
        <a
          href="#main"
          className={cn(
            "type-body-sm sr-only rounded-button bg-surface-card px-4 py-2 text-ink",
            "shadow-overlay",
            "focus:not-sr-only focus:absolute focus:left-4 focus:top-4 focus:z-50",
          )}
        >
          Skip to content
        </a>

        <TopBar />

        <div className="flex min-h-0 flex-1">
          <NavRail />
          <main id="main" tabIndex={-1} className="min-h-0 flex-1 overflow-y-auto">
            {/*
             * `resetKeys` on the pathname: a screen that crashed must not leave its error
             * mounted over the next one the operator navigates to.
             */}
            <ErrorBoundary resetKeys={[location.pathname]}>{children}</ErrorBoundary>
          </main>
        </div>

        <PlayerBar />
        <CommandPalette />
      </div>
    </KeyboardShortcuts>
  );
}
