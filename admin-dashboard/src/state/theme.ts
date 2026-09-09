/**
 * Which palette the console is painted in, and the one place `data-theme` is written.
 *
 * `styles/tokens.css` used to open with "light only, and `color-scheme` says so: the mockup
 * has no dark counterpart". It now has one, authored rather than derived — see the dark block
 * there — and this store is the switch between them.
 *
 * ## Three states behind a two-state button
 *
 * `choice` is `"light"`, `"dark"`, or `null` for **follow the operating system**, which is
 * what a browser that has never seen this console does. The button is still a plain toggle:
 * it flips to the opposite of what is currently ON SCREEN, which is the only mapping that
 * cannot surprise someone. What `null` buys is the case a two-state store gets wrong — an
 * operator whose machine turns dark at sunset gets a console that turns with it, until the
 * first time they disagree with it, after which their choice is the answer forever.
 *
 * A resolved value is stored, never `"system"`: the attribute on `<html>` is the resolved
 * palette, so CSS needs one selector per palette and no media query in the token file at all.
 * That matters more than it looks — a token defined only inside `@media (prefers-color-scheme:
 * dark)` cannot be overridden by an explicit choice, which is the classic way a theme toggle
 * ends up working in one direction.
 *
 * ## Applied before the first paint
 *
 * `applyStoredTheme()` runs from `main.tsx`, ahead of `createRoot`, so the attribute is on the
 * element before React renders anything. It is deliberately NOT an inline `<script>` in
 * `index.html`: this app serves a CSP nonce (`index.html` carries the placeholder) and adding
 * an inline script is a wider hole than a single frame of the wrong ground is worth.
 */

import { useEffect } from "react";
import { create } from "zustand";

/** What the operator picked. `null` is "whatever the OS says", which is also the default. */
export type ThemeChoice = "light" | "dark" | null;

/** What is actually on screen. Always one of two: the attribute value, and the CSS selector. */
export type ResolvedTheme = "light" | "dark";

const STORAGE_KEY = "hbd.dashboard.theme";
const DARK_QUERY = "(prefers-color-scheme: dark)";

function readChoice(): ThemeChoice {
  try {
    const stored = localStorage.getItem(STORAGE_KEY);
    return stored === "light" || stored === "dark" ? stored : null;
  } catch {
    // Storage can be denied outright (private mode, blocked site data). Following the OS is
    // a fine outcome; failing to render the console is not.
    return null;
  }
}

function writeChoice(choice: ThemeChoice): void {
  try {
    if (choice === null) localStorage.removeItem(STORAGE_KEY);
    else localStorage.setItem(STORAGE_KEY, choice);
  } catch {
    /* see readChoice */
  }
}

/** What the machine prefers. `false` on a browser too old to have an opinion, which is light. */
export function systemPrefersDark(): boolean {
  return typeof window !== "undefined" && window.matchMedia(DARK_QUERY).matches;
}

function resolve(choice: ThemeChoice): ResolvedTheme {
  if (choice !== null) return choice;
  return systemPrefersDark() ? "dark" : "light";
}

/**
 * Write the palette onto `<html>`.
 *
 * `color-scheme` moves with it, and it is not decoration: it is what makes the UA paint
 * scrollbars, form controls and the canvas behind an over-scroll in the right ground. A dark
 * page with a light native scrollbar is the tell that a theme was done in CSS only.
 */
function paint(theme: ResolvedTheme): void {
  const root = document.documentElement;
  root.dataset["theme"] = theme;
  root.style.colorScheme = theme;
}

export interface ThemeState {
  /** The operator's pick, or `null` while the OS is still the authority. */
  readonly choice: ThemeChoice;
  /** What is painted right now. The only value a component should render against. */
  readonly resolved: ResolvedTheme;
  /** Flip to the opposite of what is ON SCREEN, and stop following the OS from here on. */
  readonly toggle: () => void;
  /** Pick explicitly, or pass `null` to hand the decision back to the OS. */
  readonly setChoice: (choice: ThemeChoice) => void;
  /** The OS changed its mind. A no-op once the operator has picked. */
  readonly syncWithSystem: () => void;
}

export const useThemeStore = create<ThemeState>((set, get) => ({
  choice: readChoice(),
  resolved: resolve(readChoice()),
  toggle: () => {
    get().setChoice(get().resolved === "dark" ? "light" : "dark");
  },
  setChoice: (choice) => {
    const resolved = resolve(choice);
    writeChoice(choice);
    paint(resolved);
    set({ choice, resolved });
  },
  syncWithSystem: () => {
    if (get().choice !== null) return;
    const resolved = resolve(null);
    if (resolved === get().resolved) return;
    paint(resolved);
    set({ resolved });
  },
}));

/**
 * Paint the stored palette onto `<html>` before React mounts.
 *
 * Called from `main.tsx` rather than from a component: an effect runs AFTER the first paint,
 * so a dark-mode operator would see one frame of the light ground on every page load.
 */
export function applyStoredTheme(): void {
  paint(useThemeStore.getState().resolved);
}

/**
 * Follow the OS while the operator has expressed no preference.
 *
 * Mounted once, by the shell. `matchMedia` is subscribed to unconditionally rather than only
 * while `choice === null`, because the store's own guard is the cheaper place to decide and a
 * conditional subscription is a listener that leaks the first time the condition flips.
 */
export function useSystemThemeSync(): void {
  const syncWithSystem = useThemeStore((state) => state.syncWithSystem);
  useEffect(() => {
    const query = window.matchMedia(DARK_QUERY);
    query.addEventListener("change", syncWithSystem);
    return () => {
      query.removeEventListener("change", syncWithSystem);
    };
  }, [syncWithSystem]);
}
