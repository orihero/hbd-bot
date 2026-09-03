/**
 * The button language, as assertions.
 *
 * `vitest.config.ts` sets `css: false`, so nothing here can see a rendered colour — these
 * tests read class strings. That is exactly the right level for this particular requirement,
 * because the defect they guard was a class-level one: two different class lists claiming to
 * be the same variant. What the classes RESOLVE to is measured in
 * `src/styles/tokenContrast.test.ts` and recorded in the header of `buttonVariants.ts`.
 *
 * The requirement being encoded, in one sentence: a secondary affordance is a TINT OF ITS HUE
 * WITH THE HUE AS THE LABEL, never a grey ground under a grey label — and an inactive segment
 * is neither of those, because it has to stay visibly inactive beside an active one.
 */

import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { Button } from "./Button";
import { buttonVariants, segmentVariant } from "./buttonVariants";

const VARIANTS = ["primary", "secondary", "danger", "quiet", "tinted"] as const;

describe("buttonVariants", () => {
  it("paints the secondary variant as a tint of the hue with the hue as the label", () => {
    const classes = buttonVariants({ variant: "secondary" });
    expect(classes).toContain("bg-brand-tint");
    expect(classes).toContain("text-brand");
  });

  it("never pairs a grey ground with a grey label — the defect this file replaced", () => {
    // `/orders/:id` "Reveal the brief", `/users/:id` "Reveal this order's brief" and every
    // inactive tab were `bg-surface-control` under `text-ink-muted`: rgb(240,240,243) on
    // rgb(99,99,99). It measured 5.28:1, so no contrast gate could see it. The design
    // language rules it out anyway, and no variant may reintroduce it.
    for (const variant of VARIANTS) {
      const classes = buttonVariants({ variant });
      const isGreyGround = /(?:^|\s)bg-surface-control(?:\s|$)/u.test(classes);
      const isGreyLabel = classes.includes("text-ink-muted");
      expect(isGreyGround && isGreyLabel, `${variant} is grey on grey`).toBe(false);
    }
  });

  it("gives the quiet variant no ground at all, so it cannot read as a filled chip", () => {
    const classes = buttonVariants({ variant: "quiet" });
    expect(classes).toContain("bg-transparent");
    // The ground appears only on hover — the nav rail's treatment for a section you are not on.
    expect(classes).toContain("hover:bg-surface-control");
  });

  it("keeps an inactive segment visibly inactive beside an active one", () => {
    // The tension the fix had to hold: making every secondary affordance branded must NOT
    // make an inactive tab branded, or "which tab am I on" is answered by a shade.
    expect(segmentVariant(true)).toBe("secondary");
    expect(segmentVariant(false)).toBe("quiet");

    const active = buttonVariants({ variant: segmentVariant(true) });
    const inactive = buttonVariants({ variant: segmentVariant(false) });
    expect(active).not.toEqual(inactive);
    // The active one carries the hue; the inactive one carries none of it.
    expect(active).toContain("bg-brand-tint");
    expect(inactive).not.toContain("brand");
  });

  it("keeps a destructive affordance reading destructive", () => {
    const classes = buttonVariants({ variant: "danger" });
    expect(classes).toContain("bg-error-tint");
    expect(classes).toContain("text-error");
    // Same idiom, different hue — not "the only coloured button in the row".
    expect(classes).not.toContain("brand");
  });

  it("keeps a primary reading primary: the solid fill, not a tint", () => {
    const classes = buttonVariants({ variant: "primary" });
    expect(classes).toContain("bg-brand-solid");
    expect(classes).toContain("text-ink-on-brand");
  });

  it("makes a disabled control lose its GROUND, and keeps its label readable", () => {
    // The old `disabled:opacity-50` on a solid brand fill took white-on-magenta to roughly
    // 2.4:1. Losing the button shape is a louder signal than dimming it, and `--ink-muted`
    // clears 4.87:1 on the worst ground in the palette.
    for (const variant of VARIANTS) {
      const classes = buttonVariants({ variant });
      expect(classes).toContain("disabled:bg-transparent");
      expect(classes).toContain("disabled:text-ink-muted");
      expect(classes).not.toMatch(/disabled:opacity-/u);
    }
  });

  it("paints no policed token, so it needs no waiver in tokenContrast.test.ts", () => {
    for (const variant of VARIANTS) {
      expect(buttonVariants({ variant })).not.toMatch(/text-ink-(?:mark|rule)\b/u);
    }
  });

  it("hands the tinted variant no colour of its own — the caller supplies the pair", () => {
    // `LiveFeed`'s severity segments choose their family at render time. The variant carries
    // the box and the hover, and the ground/label arrive as an inline style naming an
    // `--x-tint` / `--x` pair, which is what the token layer already measures.
    // Everything the base contributes is stripped first: the `disabled:` block, which every
    // variant shares, and the size rung's type utility, which is not a colour.
    const painted = buttonVariants({ variant: "tinted", size: "none" })
      .split(/\s+/u)
      .filter((token) => token !== "" && !token.startsWith("disabled:"))
      .filter((token) => /^(?:bg|text)-/u.test(token));
    expect(painted).toEqual([]);
  });
});

describe("Button", () => {
  it("defaults to type=button, so a button inside a form does not submit it", () => {
    render(<Button>Reveal</Button>);
    expect(screen.getByRole("button", { name: "Reveal" })).toHaveAttribute("type", "button");
  });

  it("still submits when asked to", () => {
    render(<Button type="submit">Sign in</Button>);
    expect(screen.getByRole("button", { name: "Sign in" })).toHaveAttribute("type", "submit");
  });

  it("renders the variant it was given", () => {
    render(<Button variant="secondary">Show the 7-day window</Button>);
    expect(screen.getByRole("button")).toHaveClass("bg-brand-tint", "text-brand");
  });

  it("defaults to the secondary idiom, so a forgotten variant is not a grey chip", () => {
    render(<Button>Untyped</Button>);
    expect(screen.getByRole("button")).toHaveClass("bg-brand-tint", "text-brand");
  });

  it("wears the design's own button box at the default size", () => {
    // Gogo: 16px radius, padding 8px 20px, 14px/500. `rounded-button` is `--r-md` (16px),
    // `px-5 py-2` is 20px/8px, and `text-button` is the 14px/500 rung.
    render(<Button>Open full detail</Button>);
    expect(screen.getByRole("button")).toHaveClass(
      "rounded-button",
      "px-5",
      "py-2",
      "text-button",
    );
  });
});
