import { describe, expect, it } from "vitest";

import { formatAudio, formatCents } from "@/features/dashboard/adapt";

/**
 * The two units the vendor cards were re-denominated into, and the three ways each of them was
 * got wrong on the way here. Every case below is a regression, not a specification exercise.
 */
describe("formatCents — the figure that used to read $0.00", () => {
  it("keeps the digits of a sub-cent song, which is the whole reason it exists", () => {
    // The shipped OpenRouter model renders a song for about four tenths of a cent.
    // `formatUsd` rounds that to `$0.00`; two decimal places of a DOLLAR is no precision at
    // all three orders of magnitude below one.
    expect(formatCents(0.00415206)).toBe("0.42¢");
  });

  it("does not route the fraction through formatCount, which rounds to a whole number", () => {
    // The first cut did exactly that and rendered every sub-cent figure as `0¢` — the same
    // defect in a new unit.
    expect(formatCents(0.004)).toBe("0.4¢");
    expect(formatCents(0.0099)).toBe("0.99¢");
  });

  it("stays in cents above a dollar rather than switching units under the reader", () => {
    // A card whose unit depends on its value renders `30¢` one window and `$1.20` the next,
    // and nothing tells the reader the scale moved.
    expect(formatCents(1.2)).toBe("120¢");
    expect(formatCents(12.5)).toBe("1 250¢");
  });

  it("trims a trailing decimal zero without eating a significant one", () => {
    // `120`.replace(/\.?0+$/) is `12`. The trim is guarded on the decimal point for this.
    expect(formatCents(0.05)).toBe("5¢");
    expect(formatCents(1.2)).toBe("120¢");
  });

  it("says <0.01¢ rather than rounding a real cost to nothing", () => {
    expect(formatCents(0.000009)).toBe("<0.01¢");
    expect(formatCents(0)).toBe("0¢");
  });

  it("keeps the sign", () => {
    expect(formatCents(-0.225)).toBe("-22.5¢");
  });
});

describe("formatAudio — rendered audio as a length", () => {
  it("reads a song as minutes and seconds", () => {
    expect(formatAudio(90_000)).toBe("1:30");
    expect(formatAudio(180_000)).toBe("3:00");
  });

  it("grows an hours field, because a window total is hours of audio", () => {
    // A minutes-only formatter renders this `247:30`, which reads as four minutes to anyone
    // who does not stop and count the digits.
    expect(formatAudio(14_850_000)).toBe("4:07:30");
  });

  it("pads both fields once an hour is present", () => {
    expect(formatAudio(3_723_000)).toBe("1:02:03");
  });

  it("renders well under a second as 0:00 rather than inventing a unit for it", () => {
    expect(formatAudio(400)).toBe("0:00");
    expect(formatAudio(0)).toBe("0:00");
  });

  it("never renders a negative clock", () => {
    expect(formatAudio(-5_000)).toBe("0:00");
  });
});
