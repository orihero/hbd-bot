/**
 * §11.3's rule, as a test: a status is never colour alone, and `◉ generating` is the only
 * animated one.
 */

import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { ORDER_STATE_VALUES } from "@/api";
import { STATUS_GLYPH, type StatusGlyphKey } from "@/lib";

import { StatusPill } from "./StatusPill";

describe("glyph + text + colour", () => {
  it.each(Object.entries(STATUS_GLYPH) as [StatusGlyphKey, string][])(
    "renders %s with its pinned glyph and its words",
    (state, glyph) => {
      render(<StatusPill state={state} />);
      expect(screen.getByTestId("status-pill-glyph")).toHaveTextContent(glyph);
      // The words are present as well as the glyph, so the pill survives greyscale.
      expect(screen.getByTestId("status-pill")).toHaveTextContent(state.replace(/_/g, " "));
    },
  );

  it("carries every shipped OrderState plus held, which has no state on this build", () => {
    for (const state of ORDER_STATE_VALUES) {
      expect(state in STATUS_GLYPH).toBe(true);
    }
    expect(STATUS_GLYPH.held).toBe("⚑");
  });

  it("colours from the --st-* token, never a hex literal", () => {
    render(<StatusPill state="delivered" />);
    // The Gogo badge idiom splits the colour across two elements and BOTH halves are
    // asserted, because either one drifting alone is a bug you cannot see in jsdom:
    // the ground is the state's tint, the glyph is the state's text-safe hue, and the
    // word is `--ink` so it clears 4.5:1 on that tint rather than depending on the hue.
    expect(screen.getByTestId("status-pill").getAttribute("style")).toContain(
      "var(--st-delivered-tint)",
    );
    expect(screen.getByTestId("status-pill-glyph").getAttribute("style")).toContain(
      "var(--st-delivered)",
    );
    expect(screen.getByTestId("status-pill").className).toContain("text-ink");
  });

  it("puts the word in --ink for every state, never in the state hue", () => {
    for (const state of Object.keys(STATUS_GLYPH) as StatusGlyphKey[]) {
      const { unmount } = render(<StatusPill state={state} />);
      const pill = screen.getByTestId("status-pill");
      // `text-ink`, not `text-ink-muted` and not an inline colour: a pill's own style
      // attribute must carry the GROUND only. The regex is anchored so that
      // `background-color:` — which the pill DOES set — is not mistaken for a `color:`.
      expect(pill.className).toContain("text-ink");
      expect(pill.getAttribute("style") ?? "").not.toMatch(/(?:^|;)\s*color:/u);
      unmount();
    }
  });
});

describe("motion means 'this is moving right now'", () => {
  it("animates generating and nothing else", () => {
    for (const state of Object.keys(STATUS_GLYPH) as StatusGlyphKey[]) {
      const { unmount } = render(<StatusPill state={state} />);
      const glyph = screen.getByTestId("status-pill-glyph");
      if (state === "generating") {
        expect(glyph.className).toContain("animate-pulse-ring");
      } else {
        expect(glyph.className).not.toContain("animate-pulse-ring");
      }
      unmount();
    }
  });
});

describe("the glyph-only variant", () => {
  it("keeps the words available to a screen reader when it hides them from the eye", () => {
    render(<StatusPill state="failed" isGlyphOnly />);
    const pill = screen.getByTestId("status-pill");
    expect(pill).toHaveAttribute("aria-label", "failed");
    expect(pill.textContent).toBe("✗");
  });
});
