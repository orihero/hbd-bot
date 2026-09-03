/**
 * The three tiny hooks the shell and the boundary need, and nothing else.
 *
 * They live here rather than in `src/lib/` because `src/lib/` is the shared contract every
 * agent builds on and these are chrome concerns: a ticking clock for the `stale 42s` chip
 * and the red countdown, the tab's visibility (§11.5 gates every poll on it, so the LIVE
 * pill must agree with the poller about whether it is paused), and a mounted flag so a
 * timer never writes into an unmounted tree.
 */

import { useEffect, useState } from "react";

/**
 * `Date.now()`, re-read on an interval, for the two places a number ages on screen without
 * new data arriving: §11.4's `stale 42s` chip and §11.5's red countdown.
 *
 * `enabled` exists so a healthy dashboard is not re-rendering once a second forever — pass
 * `false` and the interval is never installed.
 */
export function useNow(intervalMs = 1_000, enabled = true): number {
  const [now, setNow] = useState<number>(() => Date.now());

  useEffect(() => {
    if (!enabled) return undefined;
    // Re-read immediately: a component that only just became stale should not wait a full
    // tick before its chip is right.
    setNow(Date.now());
    const id = window.setInterval(() => {
      setNow(Date.now());
    }, intervalMs);
    return () => {
      window.clearInterval(id);
    };
  }, [intervalMs, enabled]);

  return now;
}

/**
 * Whether the tab is visible.
 *
 * §11.5's polls are all gated on `document.visibilityState === "visible"`, so a hidden tab
 * genuinely stops fetching. The LIVE pill therefore has to know: without this it would go
 * amber and then red on a backgrounded tab and greet the returning operator with an
 * incident that never happened.
 */
export function useIsDocumentVisible(): boolean {
  const [isVisible, setIsVisible] = useState<boolean>(
    () => typeof document === "undefined" || document.visibilityState === "visible",
  );

  useEffect(() => {
    const onChange = (): void => {
      setIsVisible(document.visibilityState === "visible");
    };
    onChange();
    document.addEventListener("visibilitychange", onChange);
    return () => {
      document.removeEventListener("visibilitychange", onChange);
    };
  }, []);

  return isVisible;
}

/**
 * `matchMedia` as a boolean. Used for `prefers-reduced-motion`, which the tokens zero out
 * for CSS transitions but cannot reach a JS-driven animation or an auto-scrolling list.
 */
export function useMediaQuery(query: string): boolean {
  const [matches, setMatches] = useState<boolean>(() => {
    if (typeof window === "undefined" || typeof window.matchMedia !== "function") return false;
    return window.matchMedia(query).matches;
  });

  useEffect(() => {
    if (typeof window.matchMedia !== "function") return undefined;
    const media = window.matchMedia(query);
    const onChange = (): void => {
      setMatches(media.matches);
    };
    onChange();
    media.addEventListener("change", onChange);
    return () => {
      media.removeEventListener("change", onChange);
    };
  }, [query]);

  return matches;
}

/** `(prefers-reduced-motion: reduce)`, for the animations CSS tokens cannot reach. */
export function usePrefersReducedMotion(): boolean {
  return useMediaQuery("(prefers-reduced-motion: reduce)");
}
