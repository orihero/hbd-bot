import { describe, expect, it } from "vitest";

import { ORDER_STATE_VALUES } from "@/api";

import {
  CATEGORICAL_TONES,
  MARKER_SHAPES,
  SERIES_DASH,
  categoricalTone,
  chartToneVar,
  isOrderStateTone,
  isSemanticTone,
  markerPath,
  orderStateTintVar,
  seriesDash,
  seriesMarker,
} from "./chartTokens";
import { BAND_PRESENTATION } from "./StatTile";

describe("chartToneVar", () => {
  it("maps the eight categorical slots to --c-1..8", () => {
    expect(CATEGORICAL_TONES.map(chartToneVar)).toEqual([
      "var(--c-1)",
      "var(--c-2)",
      "var(--c-3)",
      "var(--c-4)",
      "var(--c-5)",
      "var(--c-6)",
      "var(--c-7)",
      "var(--c-8)",
    ]);
  });

  it("gives a semantic series its STATUS colour, never a ramp slot", () => {
    // §11.3: "green must mean the same thing everywhere."
    expect(chartToneVar("delivered")).toBe("var(--st-delivered)");
    expect(chartToneVar("failed")).toBe("var(--st-failed)");
    expect(chartToneVar("brief_ready")).toBe("var(--st-brief-ready)");
  });

  it("maps the rate bands to the same colours the tiles use", () => {
    // Literally the same tokens `StatTile.BAND_PRESENTATION` paints, so a 96.8% tile and the
    // series it summarises are never two different greens.
    expect(chartToneVar("good")).toBe(BAND_PRESENTATION.good.colorVar);
    expect(chartToneVar("warn")).toBe(BAND_PRESENTATION.warn.colorVar);
    expect(chartToneVar("bad")).toBe(BAND_PRESENTATION.bad.colorVar);
    expect(chartToneVar("good")).toBe("var(--success)");
    expect(chartToneVar("warn")).toBe("var(--caution)");
    expect(chartToneVar("bad")).toBe("var(--error)");
    // `neutral` is the true grey and no longer `--slate`: the reskin promotes slate to a
    // MEANING (cancelled), so reusing it for "no opinion" would put two different facts on
    // one hue.
    expect(chartToneVar("neutral")).toBe("var(--neutral)");
    expect(chartToneVar("cancelled")).toBe("var(--st-cancelled)");
  });

  it("never emits a hex, so the light palette follows the theme", () => {
    const everyTone = [...CATEGORICAL_TONES, ...ORDER_STATE_VALUES, "good", "warn", "bad"] as const;
    for (const tone of everyTone) {
      expect(chartToneVar(tone)).toMatch(/^var\(--[a-z0-9-]+\)$/);
    }
  });
});

describe("isSemanticTone", () => {
  it("separates the reserved status tones from the categorical ramp", () => {
    expect(isSemanticTone("delivered")).toBe(true);
    expect(isSemanticTone("c-3")).toBe(false);
  });
});

describe("categoricalTone", () => {
  it("assigns in fixed order", () => {
    expect(categoricalTone(0)).toBe("c-1");
    expect(categoricalTone(2)).toBe("c-3");
  });

  it("clamps past eight rather than cycling — a 9th hue is never generated", () => {
    expect(categoricalTone(8)).toBe("c-8");
    expect(categoricalTone(40)).toBe("c-8");
  });
});

describe("the secondary channels", () => {
  it("gives every one of the eight slots a distinct dash", () => {
    expect(new Set(SERIES_DASH).size).toBe(SERIES_DASH.length);
    expect(seriesDash(0)).toBe("0");
  });

  it("gives every one of the eight slots a distinct marker", () => {
    expect(new Set(MARKER_SHAPES).size).toBe(MARKER_SHAPES.length);
    expect(seriesMarker(0)).toBe("circle");
    expect(seriesMarker(3)).toBe("diamond");
  });

  it("keeps dash and marker aligned with the palette length", () => {
    // The reskin's ramp is properly stepped, but the SEMANTIC pair is not and cannot be:
    // --success and --error are 1.00:1 against each other in the light palette, because both
    // had to be pushed to nearly the same lightness to clear 4.5:1 on a white card. delivered
    // and failed are the two series this console plots together most often, so a slot without
    // a second channel is unreadable in greyscale and for a red-green reader.
    expect(SERIES_DASH).toHaveLength(CATEGORICAL_TONES.length);
    expect(MARKER_SHAPES).toHaveLength(CATEGORICAL_TONES.length);
    expect(seriesDash(0)).not.toBe(seriesDash(1));
    expect(seriesMarker(0)).not.toBe(seriesMarker(1));
  });

  it("clamps rather than cycling past eight", () => {
    expect(seriesDash(99)).toBe(SERIES_DASH[SERIES_DASH.length - 1]);
    expect(seriesMarker(99)).toBe(MARKER_SHAPES[MARKER_SHAPES.length - 1]);
  });
});

describe("markerPath", () => {
  it("returns a closed path centred on the point for every shape", () => {
    for (const shape of MARKER_SHAPES) {
      const path = markerPath(shape, 50, 50);
      expect(path.startsWith("M")).toBe(true);
      expect(path.endsWith("Z")).toBe(true);
      expect(path).not.toContain("NaN");
    }
  });

  it("scales with the radius", () => {
    expect(markerPath("square", 0, 0, 4)).not.toBe(markerPath("square", 0, 0, 8));
  });
});

describe("isOrderStateTone", () => {
  it("recognises every shipped order state", () => {
    for (const state of ORDER_STATE_VALUES) expect(isOrderStateTone(state)).toBe(true);
    expect(isOrderStateTone("c-1")).toBe(false);
  });
});

describe("orderStateTintVar", () => {
  it("names the state's own chip ground, snake_case turned into the token spelling", () => {
    expect(orderStateTintVar("delivered")).toBe("var(--st-delivered-tint)");
    expect(orderStateTintVar("brief_ready")).toBe("var(--st-brief-ready-tint)");
  });

  it("gives every shipped state a tint, never a hex", () => {
    for (const state of ORDER_STATE_VALUES) {
      expect(orderStateTintVar(state)).toMatch(/^var\(--st-[a-z-]+-tint\)$/u);
    }
  });
});
