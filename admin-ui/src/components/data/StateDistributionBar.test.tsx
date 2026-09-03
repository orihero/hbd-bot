import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { ORDER_STATE_VALUES, type OrderStateCount } from "@/api";

import { StateDistributionBar } from "./StateDistributionBar";

const counts: readonly OrderStateCount[] = [
  { state: "failed", count: 10 },
  { state: "delivered", count: 70 },
  { state: "generating", count: 20 },
];

function segments(container: HTMLElement): readonly string[] {
  return [...container.querySelectorAll("[data-state]")].map(
    (element) => element.getAttribute("data-state") ?? "",
  );
}

describe("StateDistributionBar", () => {
  it("orders segments by the lifecycle, never by count", () => {
    const { container } = render(<StateDistributionBar counts={counts} isLegend={false} />);
    // ORDER_STATE_VALUES declaration order is the pipeline; sorting by count would move
    // `failed` on every poll.
    expect(segments(container)).toEqual(["generating", "delivered", "failed"]);
    const lifecycle = ORDER_STATE_VALUES.filter((state) =>
      counts.some((entry) => entry.state === state),
    );
    expect(segments(container)).toEqual([...lifecycle]);
  });

  it("skips a state with no orders rather than drawing a zero-width sliver", () => {
    const { container } = render(
      <StateDistributionBar counts={[{ state: "delivered", count: 3 }]} isLegend={false} />,
    );
    expect(segments(container)).toEqual(["delivered"]);
  });

  it("sizes segments by count, so the gaps cannot distort the proportions", () => {
    const { container } = render(<StateDistributionBar counts={counts} isLegend={false} />);
    const delivered = container.querySelector('[data-state="delivered"]');
    expect(delivered).toHaveStyle({ flexGrow: "70", flexBasis: "0px" });
  });

  it("paints from the --st-* tokens, never a hex", () => {
    const { container } = render(<StateDistributionBar counts={counts} isLegend={false} />);
    const failed = container.querySelector('[data-state="failed"]');
    expect(failed?.getAttribute("style")).toContain("var(--st-failed)");
    expect(failed?.getAttribute("style")).not.toMatch(/#[0-9a-f]{3,8}/i);
  });

  it("is 8px tall and full width — §11.2's dominant signal, not a prop", () => {
    const { container } = render(<StateDistributionBar counts={counts} isLegend={false} />);
    const bar = container.querySelector('[role="img"]');
    expect(bar).toHaveClass("h-2");
    expect(bar).toHaveClass("w-full");
    // Round ends, from the token that means "round this completely" rather than from a rung
    // that happens to be half of 8px — so the ends survive a change of height.
    expect(bar).toHaveClass("rounded-pill");
  });

  it("describes itself for a screen reader with counts and shares", () => {
    render(<StateDistributionBar counts={counts} isLegend={false} label="orders by state" />);
    const bar = screen.getByRole("img");
    expect(bar).toHaveAccessibleName(expect.stringContaining("delivered 70 (70%)"));
  });

  it("carries a glyph legend, so colour is never the only channel", () => {
    render(<StateDistributionBar counts={counts} />);
    const legend = screen.getByRole("list", { name: /legend/ });
    expect(legend).toHaveTextContent("delivered");
    expect(legend).toHaveTextContent("✓");
    expect(legend).toHaveTextContent("✗");
  });

  it("tints each legend pill with its own state's ground, never a bare hue behind text", () => {
    const { container } = render(<StateDistributionBar counts={counts} />);
    const pills = [...container.querySelectorAll("li")];
    // The palette's recommended pill: the WORD in --ink on the state's -tint, the glyph in
    // the state's hue. Putting the hue itself behind the words is what made status chips
    // unreadable the moment the theme went light-first.
    expect(pills.map((pill) => pill.getAttribute("style"))).toEqual([
      "background-color: var(--st-generating-tint);",
      "background-color: var(--st-delivered-tint);",
      "background-color: var(--st-failed-tint);",
    ]);
    for (const pill of pills) expect(pill).toHaveClass("text-ink");
  });

  it("renders an empty bar and no legend for an empty list", () => {
    render(<StateDistributionBar counts={[]} />);
    expect(screen.getByRole("img")).toHaveAccessibleName("orders by state: none");
    expect(screen.queryByRole("list")).toBeNull();
  });

  it("sums duplicate state rows rather than drawing two segments", () => {
    const { container } = render(
      <StateDistributionBar
        counts={[
          { state: "delivered", count: 2 },
          { state: "delivered", count: 3 },
        ]}
        isLegend={false}
      />,
    );
    expect(segments(container)).toEqual(["delivered"]);
    expect(container.querySelector('[data-state="delivered"]')).toHaveStyle({ flexGrow: "5" });
  });
});
