/**
 * `cn()`, and the one thing about it that is a requirement rather than a convenience.
 *
 * `tailwind-merge` models Tailwind's DEFAULT theme, in which a `text-*` value that does not
 * look like a size is a COLOUR. This design's type scale is named `hero`, `metric`, `h1`,
 * `body-sm`, `button` … so every one of those was being resolved as a colour and dropped
 * whenever a real colour shared the same `cn()` call. Nothing could catch it downstream:
 * jsdom runs with `css: false`, so a component whose font size silently vanished renders
 * identically to one that kept it, and the Playwright specs read text rather than metrics.
 *
 * These tests are that missing check. The first would have failed before the fix.
 */

import { readFileSync } from "node:fs";
import { resolve } from "node:path";

import { describe, expect, it } from "vitest";

import { cn, TYPE_SCALE_UTILITIES } from "./utils";

describe("cn keeps this design's type scale", () => {
  it.each(TYPE_SCALE_UTILITIES)(
    "text-%s survives a colour in the same call",
    (utility) => {
      // The real-world shape: a component sets its size and its colour together.
      const result = cn(`text-${utility} rounded-pill px-5 py-2`, "text-ink");
      expect(result, `text-${utility} was resolved as a colour and dropped`).toContain(
        `text-${utility}`,
      );
      expect(result).toContain("text-ink");
    },
  );

  it("still lets a later size win over an earlier one", () => {
    // The whole reason `twMerge` is here: a caller's `className` overrides the component's
    // own utility without `!important`. Registering the scale must not cost that.
    expect(cn("text-h1", "text-h2")).toBe("text-h2");
    expect(cn("text-hero", "text-metric")).toBe("text-metric");
  });

  it("still lets a later colour win over an earlier one", () => {
    expect(cn("text-ink", "text-brand")).toBe("text-brand");
    expect(cn("text-ink-muted text-body", "text-error")).toBe("text-body text-error");
  });

  it("leaves Tailwind's own sizes and arbitrary lengths alone", () => {
    expect(cn("text-sm text-ink")).toBe("text-sm text-ink");
    expect(cn("text-[28px] text-ink-muted")).toBe("text-[28px] text-ink-muted");
  });
});

describe("the registered scale is the config's scale", () => {
  it("names every fontSize key tailwind.config.ts defines, and no others", () => {
    // Read rather than imported: `tailwind.config.ts` belongs to `tsconfig.node.json`, and
    // pointing the app project at it makes every plugin type a parse error. The same trick
    // `tokenContrast.test.ts` uses on `tokens.css`, for the same reason.
    const source = readFileSync(
      resolve(import.meta.dirname, "../../tailwind.config.ts"),
      "utf8",
    );
    const block = /fontSize:\s*\{([\s\S]*?)\n {6}\},/u.exec(source)?.[1];
    expect(block, "could not find theme.extend.fontSize in tailwind.config.ts").toBeDefined();

    const keys = Array.from((block ?? "").matchAll(/^\s{8}"?([a-z0-9-]+)"?:\s*\[/gmu)).map(
      (match) => match[1],
    );
    // A scan that matched nothing would make this test vacuous.
    expect(keys.length).toBeGreaterThan(5);
    expect([...keys].sort()).toEqual([...TYPE_SCALE_UTILITIES].sort());
  });
});
