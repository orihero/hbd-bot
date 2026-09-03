/**
 * The codepoint machinery, including the two things it must never do: fold a string, or
 * split a surrogate pair.
 */

import { describe, expect, it } from "vitest";

import {
  codepointSequence,
  formatCodepoint,
  isAmbiguousCodepoint,
  toCodepoints,
} from "./codepoints";
import { NAME_DILNOZA, NAME_OKTAM } from "./fixtures";

describe("formatCodepoint", () => {
  it("pads to four uppercase hex digits without touching a case-folding call", () => {
    expect(formatCodepoint(0x02bb)).toBe("U+02BB");
    expect(formatCodepoint(0x27)).toBe("U+0027");
    expect(formatCodepoint(0x414)).toBe("U+0414");
  });

  it("goes past four digits for an astral codepoint rather than truncating", () => {
    expect(formatCodepoint(0x1f512)).toBe("U+1F512");
  });
});

describe("toCodepoints", () => {
  it("iterates by codepoint, so an emoji is one entry and not half a surrogate pair", () => {
    const points = toCodepoints("🔒a");
    expect(points).toHaveLength(2);
    expect(points[0]?.code).toBe(0x1f512);
    expect(points[1]?.char).toBe("a");
  });

  it("returns the characters unchanged", () => {
    expect(toCodepoints(NAME_OKTAM).map((point) => point.char)).toEqual([
      "O",
      "ʻ",
      "k",
      "t",
      "a",
      "m",
    ]);
  });

  it("flags the apostrophe family and leaves legible letters alone", () => {
    const flagged = toCodepoints(NAME_OKTAM).filter((point) => point.isAmbiguous);
    expect(flagged).toHaveLength(1);
    expect(flagged[0]?.label).toBe("U+02BB");
    expect(toCodepoints(NAME_DILNOZA).some((point) => point.isAmbiguous)).toBe(false);
  });
});

describe("isAmbiguousCodepoint", () => {
  it("covers every character that draws as the same small tick", () => {
    for (const code of [0x0027, 0x2019, 0x02bb, 0x02bc, 0x00b4, 0x2032]) {
      expect(isAmbiguousCodepoint(code)).toBe(true);
    }
  });

  it("covers the invisible passengers a copy-paste drags along", () => {
    for (const code of [0x200b, 0x200d, 0xfeff, 0x00a0, 0x0301]) {
      expect(isAmbiguousCodepoint(code)).toBe(true);
    }
  });

  it("leaves ordinary letters alone in both scripts", () => {
    for (const code of [0x0041, 0x007a, 0x0414, 0x0438]) {
      expect(isAmbiguousCodepoint(code)).toBe(false);
    }
  });
});

describe("codepointSequence", () => {
  it("spells the whole value for a bug report", () => {
    expect(codepointSequence("Oʻk")).toBe("U+004F U+02BB U+006B");
  });
});
