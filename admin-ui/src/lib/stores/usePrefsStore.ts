/**
 * `usePrefsStore` — one of the THREE client stores §11.1 allows. Persisted per browser.
 *
 * What belongs here: an operator's own display choices. What does NOT: anything the server
 * knows. TanStack Query is the only server-state store, and duplicating a role or a session
 * into Zustand is how the two start to disagree during a re-auth.
 *
 * The theme is written onto `<html data-theme>` rather than kept only in React state,
 * because `tokens.css` keys the dark palette off that attribute and CSS must see it before
 * first paint.
 *
 * LIGHT IS HOME, since the reskin. `:root` in `tokens.css` carries the light palette and
 * `[data-theme="dark"]` overrides it; there is no `[data-theme="light"]` block any more,
 * because an unattributed document is already light. `theme` therefore defaults to
 * `"light"`: a fresh operator sees the palette the console was designed in, and `"system"`
 * is an opt-in that resolves against `prefers-color-scheme` on every change.
 *
 * `timeZoneMode` is the top bar's UTC/local toggle. It defaults to **UTC** deliberately:
 * every column is `timestamptz`, three parties may be in three places, and a support
 * conversation that starts from a server log is a UTC conversation. An operator who wants
 * their own clock opts in.
 */

import { create } from "zustand";
import { persist } from "zustand/middleware";

import type { TimeZoneMode } from "@/lib/format";

export type ThemeChoice = "dark" | "light" | "system";

/** §11.4's `DataTable` density control. */
export type Density = "comfortable" | "compact";

export interface PrefsState {
  theme: ThemeChoice;
  timeZoneMode: TimeZoneMode;
  /** The left rail collapses 220px → 64px and the choice is persisted (§11.2). */
  isNavCollapsed: boolean;
  density: Density;
  /** Whether the ⌘K palette is open. Not persisted — see `partialize` below. */
  isCommandPaletteOpen: boolean;

  setTheme: (theme: ThemeChoice) => void;
  setTimeZoneMode: (mode: TimeZoneMode) => void;
  toggleTimeZoneMode: () => void;
  setNavCollapsed: (collapsed: boolean) => void;
  toggleNav: () => void;
  setDensity: (density: Density) => void;
  setCommandPaletteOpen: (open: boolean) => void;
  toggleCommandPalette: () => void;
}

export const PREFS_STORAGE_KEY = "bayram.admin.prefs";

export const usePrefsStore = create<PrefsState>()(
  persist(
    (set) => ({
      theme: "light",
      timeZoneMode: "utc",
      isNavCollapsed: false,
      density: "comfortable",
      isCommandPaletteOpen: false,

      setTheme: (theme) => {
        set({ theme });
        applyTheme(theme);
      },
      setTimeZoneMode: (timeZoneMode) => set({ timeZoneMode }),
      toggleTimeZoneMode: () =>
        set((state) => ({ timeZoneMode: state.timeZoneMode === "utc" ? "local" : "utc" })),
      setNavCollapsed: (isNavCollapsed) => set({ isNavCollapsed }),
      toggleNav: () => set((state) => ({ isNavCollapsed: !state.isNavCollapsed })),
      setDensity: (density) => set({ density }),
      setCommandPaletteOpen: (isCommandPaletteOpen) => set({ isCommandPaletteOpen }),
      toggleCommandPalette: () =>
        set((state) => ({ isCommandPaletteOpen: !state.isCommandPaletteOpen })),
    }),
    {
      name: PREFS_STORAGE_KEY,
      // Only the durable choices are written. A palette that reopens itself on every reload
      // because its open state was persisted is a bug nobody thinks to look for.
      partialize: (state) => ({
        theme: state.theme,
        timeZoneMode: state.timeZoneMode,
        isNavCollapsed: state.isNavCollapsed,
        density: state.density,
      }),
    },
  ),
);

/**
 * Stamp the theme onto `<html>`. Call once at boot before the first render, and on change.
 *
 * `"system"` is RESOLVED here rather than left to the cascade, and the listener in
 * `initTheme()` re-resolves it when the OS setting changes. It reads
 * `prefers-color-scheme: light`, which is the query that matches when the OS expresses no
 * preference at all, so "system" on a machine with nothing set lands on light — the palette
 * this console is designed in — and follows the operator to dark the moment they ask for it.
 */
export function applyTheme(theme: ThemeChoice): void {
  if (typeof document === "undefined") return;
  const root = document.documentElement;
  if (theme === "system") {
    const prefersLight = window.matchMedia("(prefers-color-scheme: light)").matches;
    root.setAttribute("data-theme", prefersLight ? "light" : "dark");
    return;
  }
  root.setAttribute("data-theme", theme);
}

/**
 * Boot-time wiring: apply the persisted theme and keep `"system"` following the OS.
 * Returns an unsubscribe function.
 */
export function initTheme(): () => void {
  applyTheme(usePrefsStore.getState().theme);
  if (typeof window === "undefined") return () => undefined;
  const media = window.matchMedia("(prefers-color-scheme: light)");
  const onChange = (): void => {
    if (usePrefsStore.getState().theme === "system") applyTheme("system");
  };
  media.addEventListener("change", onChange);
  return () => {
    media.removeEventListener("change", onChange);
  };
}
