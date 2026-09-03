/**
 * The chart channels: colour, dash pattern, marker shape.
 *
 * Kept out of `ChartFrame.tsx` so that file can stay a module of components only (Fast
 * Refresh) and so a swap of Recharts for uPlot changes the renderer without touching a
 * single colour decision.
 *
 * ## Why there are three channels and not one
 *
 * §11.3 pins the sentence that matters: "Series also differ by dash pattern and marker shape
 * so hue is never the only channel." Under the Gogo palette that is more load-bearing than it
 * was, not less, and for a new reason.
 *
 * The reskin's ramp (`--c-1..8`) is a genuine categorical ramp — the slots are ordered so no
 * two neighbours are within 90° of hue, which is what the old ramp got wrong when it inherited
 * `--red` and `--magenta` from the status palette as adjacent slots. What replaces that hazard
 * is a worse one for the SEMANTIC tones, and it is documented in `tokens.css`: to clear 4.5:1
 * on a white card, `--success` and `--error` had to be pushed to nearly the same LIGHTNESS.
 * They are 1.00:1 against each other in the light palette. They differ in hue and in nothing
 * else, so a greyscale print, a projector with the colour dead, and a protanope reading a
 * light-theme chart all see one series where there are two.
 *
 * That is the whole argument for the second and third channels. `delivered` and `failed` are
 * the two series that appear together most often in this console, and dash pattern plus marker
 * shape are the only reason they can be told apart at all. A caller that strips them has made
 * the chart unreadable, and on exactly the chart that matters most.
 *
 * ## Semantic vs categorical
 *
 * A series that MEANS delivered or failed takes the `--st-*` token, never a ramp slot.
 * Green means delivered on the `/orders` distribution bar, in the pulse tile, on this
 * chart, and nowhere else does green mean anything. `chartToneVar` is the one function that
 * decides, so a screen cannot get it wrong by picking a hex.
 */

import { ORDER_STATE_VALUES, type OrderState } from "@/api";
import { orderStateColorVar } from "@/lib";

/** The eight categorical slots, in `--c-1..8` order. Assigned in order, never cycled. */
export const CATEGORICAL_TONES = [
  "c-1",
  "c-2",
  "c-3",
  "c-4",
  "c-5",
  "c-6",
  "c-7",
  "c-8",
] as const;

export type CategoricalTone = (typeof CATEGORICAL_TONES)[number];

/** Tones that carry meaning. Order states plus the three-band rate vocabulary. */
export type SemanticTone = OrderState | "good" | "warn" | "bad" | "neutral";

export type ChartTone = CategoricalTone | SemanticTone;

/**
 * The three-band rate vocabulary, on the reskin's palette.
 *
 * These are the SAME four tokens `StatTile`'s `BAND_PRESENTATION` uses, which is the point:
 * a 96.8% tile and the series it summarises must not be two different greens. `warn` is
 * `--caution` (§11.2's "amber 85–95%", the softer attention hue) rather than `--warning`,
 * which this palette reserves for a partial outage; `neutral` is `--neutral`, the true grey,
 * and no longer `--slate`, which the reskin promotes to a MEANING — cancelled — so that
 * `StateDistributionBar` can stack draft beside cancelled without them reading as one
 * segment.
 */
const SEMANTIC_VARS: Record<"good" | "warn" | "bad" | "neutral", string> = {
  good: "var(--success)",
  warn: "var(--caution)",
  bad: "var(--error)",
  neutral: "var(--neutral)",
};

/** The CSS custom property expression for a tone. Never a hex, so the light palette follows. */
export function chartToneVar(tone: ChartTone): string {
  if ((CATEGORICAL_TONES as readonly string[]).includes(tone)) return `var(--${tone})`;
  if (tone === "good" || tone === "warn" || tone === "bad" || tone === "neutral") {
    return SEMANTIC_VARS[tone];
  }
  return orderStateColorVar(tone);
}

/** Whether a tone is one of the reserved status colours. */
export function isSemanticTone(tone: ChartTone): boolean {
  return !(CATEGORICAL_TONES as readonly string[]).includes(tone);
}

/** The slot for the nth series when the caller has no semantic opinion. */
export function categoricalTone(index: number): CategoricalTone {
  // Never generated, never cycled past 8: a 9th series folds into "Other" or becomes small
  // multiples. Clamping rather than wrapping makes that failure visible instead of subtle.
  const slot = CATEGORICAL_TONES[Math.min(index, CATEGORICAL_TONES.length - 1)];
  return slot ?? "c-1";
}

/* -------------------------------------------------------------------------- */
/* Channel two: dash                                                           */
/* -------------------------------------------------------------------------- */

/**
 * `strokeDasharray` per series slot. Slot 0 is solid; nothing else is, so no two lines in
 * one chart share a stroke pattern.
 *
 * These are for the DATA marks only. Gridlines and axis rules stay solid hairlines —
 * a dashed grid reads as a threshold or a projection when it is just a grid.
 */
export const SERIES_DASH = [
  "0",
  "6 3",
  "2 3",
  "10 4 2 4",
  "1 4",
  "8 3 2 3",
  "4 2",
  "12 4 2 4 2 4",
] as const;

export function seriesDash(index: number): string {
  return SERIES_DASH[Math.min(index, SERIES_DASH.length - 1)] ?? "0";
}

/* -------------------------------------------------------------------------- */
/* Channel three: marker shape                                                 */
/* -------------------------------------------------------------------------- */

export const MARKER_SHAPES = [
  "circle",
  "square",
  "triangle",
  "diamond",
  "triangle-down",
  "hexagon",
  "pentagon",
  "star",
] as const;

export type MarkerShape = (typeof MARKER_SHAPES)[number];

export function seriesMarker(index: number): MarkerShape {
  return MARKER_SHAPES[Math.min(index, MARKER_SHAPES.length - 1)] ?? "circle";
}

/** ≥8px across, per the dataviz mark spec: r=4.4 gives an 8.8px marker. */
export const MARKER_RADIUS = 4.4;

/**
 * The `d` of one marker, centred on `(cx, cy)`.
 *
 * Every shape is one path so the renderer is uniform and the marker keeps a single 2px
 * surface ring where it crosses its own line.
 */
export function markerPath(
  shape: MarkerShape,
  cx: number,
  cy: number,
  radius: number = MARKER_RADIUS,
): string {
  switch (shape) {
    case "circle": {
      const r = radius.toFixed(2);
      return `M${(cx - radius).toFixed(2)},${cy.toFixed(2)} a${r},${r} 0 1,0 ${(radius * 2).toFixed(
        2,
      )},0 a${r},${r} 0 1,0 ${(-radius * 2).toFixed(2)},0 Z`;
    }
    case "square":
      return regularPolygon(cx, cy, radius, 4, -45);
    case "diamond":
      return regularPolygon(cx, cy, radius * 1.15, 4, -90);
    case "triangle":
      return regularPolygon(cx, cy, radius * 1.2, 3, -90);
    case "triangle-down":
      return regularPolygon(cx, cy, radius * 1.2, 3, 90);
    case "pentagon":
      return regularPolygon(cx, cy, radius * 1.1, 5, -90);
    case "hexagon":
      return regularPolygon(cx, cy, radius * 1.05, 6, -90);
    case "star":
      return starPolygon(cx, cy, radius * 1.25, radius * 0.55, 5, -90);
  }
}

function regularPolygon(
  cx: number,
  cy: number,
  radius: number,
  sides: number,
  rotationDeg: number,
): string {
  const points: string[] = [];
  for (let index = 0; index < sides; index += 1) {
    const angle = ((rotationDeg + (360 / sides) * index) * Math.PI) / 180;
    points.push(
      `${(cx + radius * Math.cos(angle)).toFixed(2)},${(cy + radius * Math.sin(angle)).toFixed(2)}`,
    );
  }
  return `M${points.join(" L")} Z`;
}

function starPolygon(
  cx: number,
  cy: number,
  outer: number,
  inner: number,
  points: number,
  rotationDeg: number,
): string {
  const coordinates: string[] = [];
  for (let index = 0; index < points * 2; index += 1) {
    const radius = index % 2 === 0 ? outer : inner;
    const angle = ((rotationDeg + (360 / (points * 2)) * index) * Math.PI) / 180;
    coordinates.push(
      `${(cx + radius * Math.cos(angle)).toFixed(2)},${(cy + radius * Math.sin(angle)).toFixed(2)}`,
    );
  }
  return `M${coordinates.join(" L")} Z`;
}

/* -------------------------------------------------------------------------- */
/* Convenience                                                                 */
/* -------------------------------------------------------------------------- */

/** True when the string is one of our order states — lets a caller pass a state as a tone. */
export function isOrderStateTone(tone: string): tone is OrderState {
  return (ORDER_STATE_VALUES as readonly string[]).includes(tone);
}

/**
 * The chip GROUND for an order state — `--st-delivered-tint` and friends.
 *
 * The reskin gave every state a three-member family (`--st-x`, `-fill`, `-tint`) so a pill
 * can be built the way the palette recommends: the word in `--ink`, the ground in the tint,
 * the glyph in the hue. `orderStateColorVar` in `@/lib` returns the first member; this is the
 * third, and it lives here rather than beside it because a tint is only ever a data-surface
 * decision. There is no `-fill` helper because nothing in this directory needs one: an 8px
 * distribution segment reads better at the text token's contrast than at the graphic bar's.
 */
export function orderStateTintVar(state: string): string {
  return `var(--st-${state.replace(/_/g, "-")}-tint)`;
}
