/**
 * The two-line helper every shadcn/ui component expects to import — plus the one line of
 * configuration without which it silently deletes half of this design's type scale.
 *
 * `clsx` merges conditional class lists; `twMerge` resolves Tailwind conflicts so a
 * `className` prop can override a component's own utility without `!important` and without
 * caring about source order.
 *
 * ## Why `extendTailwindMerge` is not optional here
 *
 * `tailwind-merge` ships a hard-coded model of Tailwind's DEFAULT theme. Its `text-*` rules
 * are: if the value looks like a font size (`sm`, `2xl`, an arbitrary length) it belongs to
 * the `font-size` group; otherwise it is a TEXT COLOUR. `theme.extend.fontSize` in
 * `tailwind.config.ts` names this design's scale `hero · metric · h1 · h2 · h3 · body ·
 * body-sm · button · caption · mono`, and not one of those looks like a size to that model.
 *
 * So `cn("text-button rounded-pill bg-brand-solid text-ink-on-brand")` returned
 * `"rounded-pill bg-brand-solid text-ink-on-brand"` — `text-button` was resolved as a text
 * COLOUR, found to conflict with `text-ink-on-brand`, and dropped. Every `text-hero`,
 * `text-h1`, `text-body` … in the codebase does the same the moment a colour shares its
 * `cn()` call, which is nearly always. The element then renders at the inherited 14px/400
 * with no error, no warning and no failing test: jsdom runs with `css: false` and cannot see
 * a font size, so the whole suite stays green while the type scale is missing.
 *
 * Registering the scale in the `font-size` group fixes it and keeps both overrides intact:
 * a later size still beats an earlier size, and a later colour still beats an earlier colour.
 * `src/lib/utils.test.ts` asserts that, and cross-checks this list against the config's own
 * `fontSize` keys so a new rung cannot be added in one file and forgotten in the other.
 */

import { clsx, type ClassValue } from "clsx";
import { extendTailwindMerge } from "tailwind-merge";

/**
 * Every key of `theme.extend.fontSize` in `tailwind.config.ts`. Kept in sync by a test, not
 * by hope — see the note above.
 */
export const TYPE_SCALE_UTILITIES = [
  "hero",
  "metric",
  "h1",
  "h2",
  "h3",
  "body",
  "body-sm",
  "button",
  "caption",
  "mono",
] as const;

const twMerge = extendTailwindMerge({
  extend: { classGroups: { "font-size": [{ text: [...TYPE_SCALE_UTILITIES] }] } },
});

export function cn(...inputs: ClassValue[]): string {
  return twMerge(clsx(inputs));
}

/**
 * A stable id for a list that has no natural key. Never used for anything the server sees.
 */
let sequence = 0;
export function localId(prefix = "id"): string {
  sequence += 1;
  return `${prefix}-${String(sequence)}`;
}

/** `invariant`, for the handful of places a React tree genuinely cannot continue. */
export function assertPresent<T>(value: T | null | undefined, what: string): T {
  if (value === null || value === undefined) {
    throw new Error(`expected ${what} to be present`);
  }
  return value;
}
