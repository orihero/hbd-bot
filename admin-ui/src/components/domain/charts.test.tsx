/**
 * The two `/generations/names` charts.
 *
 * Both tests are really about the same failure: a number that is arithmetically defensible
 * and operationally wrong. A 0% bar for a strategy nothing ran, and a pile at 0.00 built
 * from attempts where verification never happened, both argue for exactly the wrong change
 * to `BAYRAM_NAME_CANDIDATE_ORDER`.
 */

import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it } from "vitest";

import { NAME_STRATEGY_VALUES } from "@/api";

import { makeStrategyOutcome } from "./fixtures";
import { buildSimilarityBuckets } from "./similarity";
import {
  AT_OR_ABOVE_THRESHOLD_LABEL,
  BELOW_THRESHOLD_LABEL,
  SimilarityHistogram,
  THRESHOLD_UNKNOWN_LABEL,
} from "./SimilarityHistogram";
import { NO_ATTEMPTS_LABEL, StrategyBakeoffChart } from "./StrategyBakeoffChart";

describe("StrategyBakeoffChart", () => {
  it("renders every strategy in declaration order, not in rank order", () => {
    render(
      <StrategyBakeoffChart
        rows={[
          makeStrategyOutcome({ strategy: "phonetic", verificationRate: 0.99, attempts: 10 }),
          makeStrategyOutcome({ strategy: "canonical", verificationRate: 0.5, attempts: 10 }),
        ]}
      />,
    );
    expect(
      screen.getAllByTestId("bakeoff-row").map((node) => node.getAttribute("data-strategy")),
    ).toEqual([...NAME_STRATEGY_VALUES]);
  });

  it("says 'no attempts' and draws no bar for a strategy nothing ran", () => {
    render(
      <StrategyBakeoffChart
        rows={[
          makeStrategyOutcome({ strategy: "canonical", attempts: 0, verified: 0, verificationRate: 0 }),
        ]}
      />,
    );
    const row = screen
      .getAllByTestId("bakeoff-row")
      .find((node) => node.getAttribute("data-strategy") === "canonical");
    expect(row).toHaveTextContent(NO_ATTEMPTS_LABEL);
    expect(row).not.toHaveTextContent("0.0%");
    expect(row?.querySelector("[data-testid='bakeoff-bar']")).toBeNull();
  });

  it("labels every bar with its denominator, so 100% cannot mean one attempt", () => {
    render(
      <StrategyBakeoffChart
        rows={[
          makeStrategyOutcome({
            strategy: "canonical",
            attempts: 1,
            verified: 1,
            verificationRate: 1,
          }),
        ]}
      />,
    );
    expect(
      screen.getAllByTestId("bakeoff-row").find((n) => n.getAttribute("data-strategy") === "canonical"),
    ).toHaveTextContent("100.0% · 1/1");
  });
});

describe("SimilarityHistogram", () => {
  const buckets = buildSimilarityBuckets([0.1, 0.2, 0.9, 0.95, 0.99, null], 10);

  it("marks the threshold and links straight at the field that sets it", () => {
    render(
      <MemoryRouter>
        <SimilarityHistogram buckets={buckets} threshold={0.8} />
      </MemoryRouter>,
    );
    expect(screen.getByTestId("similarity-threshold-marker")).toBeInTheDocument();
    expect(screen.getByTestId("similarity-threshold-link")).toHaveAttribute("href", "/config");
  });

  it("says so rather than inventing a threshold this deployment does not publish", () => {
    render(
      <MemoryRouter>
        <SimilarityHistogram buckets={buckets} threshold={null} />
      </MemoryRouter>,
    );
    expect(screen.queryByTestId("similarity-threshold-marker")).toBeNull();
    expect(screen.getByTestId("similarity-histogram")).toHaveTextContent(
      THRESHOLD_UNKNOWN_LABEL,
    );
  });

  it("counts only the attempts that were scored", () => {
    render(
      <MemoryRouter>
        <SimilarityHistogram buckets={buckets} threshold={0.8} />
      </MemoryRouter>,
    );
    // Six inputs, one of them null: five scored.
    expect(screen.getByTestId("similarity-histogram")).toHaveTextContent("5 scored attempts");
  });
});

describe("buildSimilarityBuckets", () => {
  it("drops nulls instead of bucketing an unrun verification at zero", () => {
    const buckets = buildSimilarityBuckets([null, null, 0.5], 10);
    expect(buckets[0]?.count).toBe(0);
    expect(buckets[5]?.count).toBe(1);
  });

  it("clamps a provider's 1.0000000002 into the top bucket rather than losing the sample", () => {
    const buckets = buildSimilarityBuckets([1.0000000002], 10);
    expect(buckets[9]?.count).toBe(1);
  });
});

/**
 * The threshold has to be readable with the colour removed.
 *
 * dataviz's non-negotiable and §11.3's own sentence are the same rule: hue is never the only
 * channel. The two sides of the threshold are a semantic pair, so they take the STATUS
 * colours — and a red-green reader, a greyscale print and a bad projector all need the
 * position, the texture and the legend to survive that.
 */
describe("SimilarityHistogram — hue is never the only channel", () => {
  const buckets = buildSimilarityBuckets([0.1, 0.2, 0.9, 0.95, 0.99, null], 10);

  it("hatches the failing side, so the split survives greyscale", () => {
    render(
      <MemoryRouter>
        <SimilarityHistogram buckets={buckets} threshold={0.8} />
      </MemoryRouter>,
    );
    const bars = screen.getAllByTestId("similarity-bucket");
    const below = bars.filter((bar) => bar.dataset["side"] === "below");
    const above = bars.filter((bar) => bar.dataset["side"] === "at-or-above");
    expect(below).not.toHaveLength(0);
    expect(above).not.toHaveLength(0);
    const fill = (bar: HTMLElement): string =>
      (bar.firstElementChild as HTMLElement | null)?.style.backgroundImage ?? "";
    expect(fill(below[0] as HTMLElement)).toContain("repeating-linear-gradient");
    expect(fill(above[0] as HTMLElement)).toBe("");
  });

  it("names both sides in a legend with their counts", () => {
    render(
      <MemoryRouter>
        <SimilarityHistogram buckets={buckets} threshold={0.8} />
      </MemoryRouter>,
    );
    const legend = screen.getByTestId("similarity-legend");
    expect(legend).toHaveTextContent(BELOW_THRESHOLD_LABEL);
    expect(legend).toHaveTextContent(AT_OR_ABOVE_THRESHOLD_LABEL);
    // Two below 0.8, three at or above.
    expect(legend).toHaveTextContent("2");
    expect(legend).toHaveTextContent("3");
  });

  it("prints the threshold's own value on the axis, not only as a rule", () => {
    render(
      <MemoryRouter>
        <SimilarityHistogram buckets={buckets} threshold={0.8} />
      </MemoryRouter>,
    );
    expect(screen.getByTestId("similarity-threshold-tick")).toHaveTextContent("0.80");
  });

  it("draws no legend, no band and no status colours without a threshold to judge against", () => {
    render(
      <MemoryRouter>
        <SimilarityHistogram buckets={buckets} threshold={null} band={0.05} nearThreshold={null} />
      </MemoryRouter>,
    );
    expect(screen.queryByTestId("similarity-legend")).toBeNull();
    expect(screen.queryByTestId("similarity-threshold-band")).toBeNull();
    expect(screen.queryByTestId("similarity-near-threshold")).toBeNull();
    expect(
      screen.getAllByTestId("similarity-bucket").every((bar) => bar.dataset["side"] === "unjudged"),
    ).toBe(true);
  });

  it("clamps a band that would run past a perfect score", () => {
    render(
      <MemoryRouter>
        <SimilarityHistogram buckets={buckets} threshold={0.98} band={0.05} nearThreshold={4} />
      </MemoryRouter>,
    );
    const band = screen.getByTestId("similarity-threshold-band");
    expect(band.style.left).toBe("93%");
    // 0.93 → 1.00, not 0.93 → 1.03.
    expect(band.style.width).toBe("7%");
  });

  it("states the cliff count in the chart's own footer, with the band it was counted over", () => {
    render(
      <MemoryRouter>
        <SimilarityHistogram buckets={buckets} threshold={0.8} band={0.05} nearThreshold={4} />
      </MemoryRouter>,
    );
    expect(screen.getByTestId("similarity-near-threshold")).toHaveTextContent(
      "4 within ±0.05 of the threshold",
    );
  });
});

describe("StrategyBakeoffChart — the analytics row", () => {
  it("attributes the cliff count to the strategy that owns it", () => {
    render(
      <StrategyBakeoffChart
        rows={[
          {
            ...makeStrategyOutcome({ strategy: "canonical", attempts: 100, verified: 92, verificationRate: 0.92 }),
            scored: 100,
            nearThreshold: 7,
          },
        ]}
      />,
    );
    const row = screen
      .getAllByTestId("bakeoff-row")
      .find((node) => node.getAttribute("data-strategy") === "canonical");
    expect(row).toHaveTextContent("7 decided inside the band");
  });

  it("says nothing about a band when the deployment publishes no threshold", () => {
    render(
      <StrategyBakeoffChart
        rows={[
          {
            ...makeStrategyOutcome({ strategy: "canonical", attempts: 100, verified: 92, verificationRate: 0.92 }),
            scored: 100,
            nearThreshold: null,
          },
        ]}
      />,
    );
    expect(screen.queryByTestId("bakeoff-near-threshold")).toBeNull();
  });

  it("takes a bare StrategyOutcomeView unchanged, so /generations keeps working", () => {
    render(<StrategyBakeoffChart rows={[makeStrategyOutcome({ strategy: "ascii" })]} />);
    expect(screen.queryByTestId("bakeoff-near-threshold")).toBeNull();
    const row = screen
      .getAllByTestId("bakeoff-row")
      .find((node) => node.getAttribute("data-strategy") === "ascii");
    expect(row).toHaveTextContent("95.0% · 114/120");
  });
});
