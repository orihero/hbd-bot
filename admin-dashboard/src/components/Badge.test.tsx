import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { Badge } from "@/components/Badge";

/**
 * The smoke test for the component runner itself (`npm run test:unit`).
 *
 * `Badge` is the smallest component in the kit that still has a rule worth holding: its own
 * doc comment says "a badge is a label, never a status announcement" and "colour is not
 * information anyone is required to be able to see". Both assertions below are that rule —
 * the WORD has to reach the accessibility tree, and the icon beside it must not, or a
 * screen reader announces a decorative glyph as part of an order's status.
 */
describe("Badge", () => {
  it("renders its label as text", () => {
    render(<Badge tone="danger">Failed</Badge>);

    expect(screen.getByText("Failed")).toBeInTheDocument();
  });

  it("hides the decorative icon from the accessibility tree, keeping the label", () => {
    render(<Badge icon={<span>★</span>}>Delivered</Badge>);

    expect(screen.getByText("Delivered")).toBeVisible();
    expect(screen.getByText("★").closest("[aria-hidden]")).not.toBeNull();
  });
});
