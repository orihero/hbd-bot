/**
 * §11.2: "an operator must never be unsure which database they are looking at."
 *
 * Each assertion below stands for a way that sentence can be violated. Two of them changed
 * when the badge was redesigned, and the reason is worth writing down where the assertions
 * are, because the old versions PASSED while the requirement was being violated:
 *
 *  - The old test asserted `shadow-ring-brand` on prod and its absence on dev. That is a
 *    true statement about two class lists and says nothing about whether prod stands out.
 *    In this palette the brand hue is the active nav pill, every link, every order ref and
 *    every pressed toggle, so "prod wears the brand" had stopped being a distinction at all.
 *  - The old test asserted three different `-tint` grounds. Three tints are three quiet
 *    chips. The requirement is not that prod DIFFERS; it is that prod is unmistakable.
 *
 * So the assertions below encode the properties that make it unmistakable, not the class
 * names that happen to implement them: prod is the only INVERTED chip (a solid hue as ground
 * with a surface token as its label, where the others put ink on a tint), the three
 * environments carry three different glyphs so the badge reads with no colour at all, and
 * prod's hue is not the brand.
 */

import { screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { renderWithProviders } from "@/components/util/testRender";

import { EnvBadge } from "./EnvBadge";

/** The chip element — the `<span>` that carries the ground, the label and the title. */
function chipFor(environment: "dev" | "staging" | "prod"): HTMLElement {
  const word = screen.getByText(environment);
  const chip = word.parentElement;
  if (chip === null) throw new Error("the badge word has no chip around it");
  return chip;
}

describe("EnvBadge", () => {
  it("names the environment in words, so it survives greyscale (§11.3)", () => {
    renderWithProviders(<EnvBadge environment="staging" />);
    expect(screen.getByText("staging")).toBeInTheDocument();
  });

  it("gives prod a SOLID fill and an inverted label — the one loud chip in the console", () => {
    // The channel that replaced the ring, and the one that survives greyscale: every other
    // chip in the console is a pale tint under `--ink`; prod is a saturated `--error` ground
    // under `--surface-card`. The polarity flips, in both themes.
    const { unmount } = renderWithProviders(<EnvBadge environment="prod" />);
    expect(chipFor("prod")).toHaveClass("bg-error", "text-surface-card");
    unmount();

    for (const quiet of ["dev", "staging"] as const) {
      const pass = renderWithProviders(<EnvBadge environment={quiet} />);
      const chip = chipFor(quiet);
      expect(chip).toHaveClass("text-ink");
      expect(chip.className).not.toContain("bg-error");
      expect(chip.className).toMatch(/bg-\w+-tint\b/u);
      pass.unmount();
    }
  });

  it("does NOT paint prod in the brand hue, because the brand hue is ambient chrome", () => {
    // The whole finding: the active nav pill, links, order refs, the active tab and every
    // pressed toggle are brand-coloured, so a brand-tinted prod chip stops registering.
    renderWithProviders(<EnvBadge environment="prod" />);
    expect(chipFor("prod").className).not.toMatch(/brand/u);
  });

  it("uses three DIFFERENT grounds, one per environment, so prod cannot be mistaken", () => {
    // §11.2's slate / amber / violet, re-pointed: the neutral grey, the caution amber and —
    // for prod — a solid error red rather than a fourth tint. What matters is that the three
    // differ and that only prod is solid.
    const grounds = {
      dev: "bg-neutral-tint",
      staging: "bg-caution-tint",
      prod: "bg-error",
    } as const;
    for (const [environment, ground] of Object.entries(grounds)) {
      const { unmount } = renderWithProviders(
        <EnvBadge environment={environment as "dev" | "staging" | "prod"} />,
      );
      expect(screen.getByText(environment).parentElement).toHaveClass(ground);
      unmount();
    }
  });

  it("gives each environment its own GLYPH, so the badge reads with no colour at all", () => {
    const glyphs = { dev: "●", staging: "◆", prod: "▲" } as const;
    const seen = new Set<string>();
    for (const [environment, glyph] of Object.entries(glyphs)) {
      const { unmount } = renderWithProviders(
        <EnvBadge environment={environment as "dev" | "staging" | "prod"} />,
      );
      expect(chipFor(environment as "dev" | "staging" | "prod")).toHaveTextContent(glyph);
      seen.add(glyph);
      unmount();
    }
    // Three shapes, not one shape three times — a greyscale reader has the glyph and the word.
    expect(seen.size).toBe(3);
  });

  it("keeps the sr-only 'Environment:' so the chip is not read as a bare word", () => {
    renderWithProviders(<EnvBadge environment="prod" />);
    expect(screen.getByText("Environment:")).toHaveClass("sr-only");
  });

  it("says 'env unknown' rather than guessing when /api/config has not answered", () => {
    // Falling back to `dev` would be a confident lie in exactly the situation the badge
    // exists to prevent.
    renderWithProviders(<EnvBadge environment={null} />);
    expect(screen.getByText("env unknown")).toBeInTheDocument();
    expect(screen.queryByText("dev")).not.toBeInTheDocument();
  });

  it("carries the environment on a data attribute, for a smoke test to read", () => {
    renderWithProviders(<EnvBadge environment="prod" />);
    expect(screen.getByText("prod").parentElement).toHaveAttribute("data-environment", "prod");
  });

  it("warns, in the title, that a production write reaches a real customer", () => {
    renderWithProviders(<EnvBadge environment="prod" />);
    expect(screen.getByText("prod").parentElement).toHaveAttribute(
      "title",
      "PRODUCTION database. Every write here reaches a real customer.",
    );
  });
});
