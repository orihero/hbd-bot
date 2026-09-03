/**
 * Token lookups for the domain components.
 *
 * Every one of these returns a `var(--token)` string, never a hex literal. The light palette
 * is a hand-built set of the same hues pushed DOWN in lightness — Gogo's own HSL values are
 * dark-theme values, and eleven of its twelve hues are under 4.5:1 on its own `#FAFAFA`
 * ground — so a colour that resolves at render time follows the theme and a colour baked
 * into a component does not.
 *
 * Colour is never the ONLY channel in any of these: each caller pairs the colour with a
 * glyph and a word.
 */

import type { RateBand } from "@/lib";
import type { FeedSeverity } from "@/lib/stores";

/** `↻` amber retryable, `■` red terminal, slate for the absent decision (`null`). */
export function retryabilityColorVar(isRetryable: boolean | null): string {
  if (isRetryable === null) return "var(--slate)";
  return isRetryable ? "var(--retryable)" : "var(--terminal)";
}

/** §11.2's Live-Ops rule: green ≥95%, amber 85–95%, red <85%, and slate for "no data". */
export function rateBandColorVar(band: RateBand): string {
  switch (band) {
    case "good":
      return "var(--success)";
    case "warn":
      return "var(--caution)";
    case "bad":
      return "var(--error)";
    case "unknown":
      return "var(--slate)";
  }
}

export function feedSeverityColorVar(severity: FeedSeverity): string {
  switch (severity) {
    case "info":
      return "var(--info)";
    case "warn":
      return "var(--caution)";
    case "error":
      return "var(--error)";
  }
}

/** The feed's glyph channel, so a severity is legible in greyscale. */
export function feedSeverityGlyph(severity: FeedSeverity): string {
  switch (severity) {
    case "info":
      return "•";
    case "warn":
      return "⚠";
    case "error":
      return "✗";
  }
}

/**
 * The `-tint` member of whatever family a `var(--x)` lookup above returned.
 *
 * `var(--error)` → `var(--error-tint)`. Every semantic family in `tokens.css` ships all
 * three members (`--x` text-safe at 4.5:1, `--x-fill` graphic at 3:1, `--x-tint` the chip
 * ground), and the reskin's badge idiom needs two of them at once: the tint underneath and
 * the text-safe hue on the glyph.
 *
 * Deriving it beats a second switch statement with the same nine cases in it — a second
 * switch is a place where the ground and the glyph can come to name different states, and
 * that is a bug you cannot see in jsdom because `css: false` means no test ever resolves a
 * variable to a colour.
 */
export function tintVar(colorVar: string): string {
  return colorVar.replace(/\)$/u, "-tint)");
}
