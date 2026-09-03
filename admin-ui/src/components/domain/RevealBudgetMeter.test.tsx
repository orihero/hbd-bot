/**
 * The meter, and the two ways it could lie.
 *
 * It could render `null` as zero — which stops an operator doing legitimate work — or it
 * could carry its meaning in a hue alone, which fails greyscale, a projector and the
 * operators who cannot separate the amber from the green (§11.3). Both are asserted here.
 */

import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { RevealBudgetMeter } from "./RevealBudgetMeter";
import { applyRevealBudget, UNMEASURED_REVEAL_BUDGET } from "./revealBudget";

const HALF_PAST = Date.UTC(2026, 8, 2, 10, 30, 0);
const CEILINGS = { records: 200, conversations: 20 };

function measured(records: number | null, conversations: number | null) {
  return applyRevealBudget(
    UNMEASURED_REVEAL_BUDGET,
    {
      recordsCharged: 0,
      recordsRemaining: records,
      conversationsCharged: 0,
      conversationsRemaining: conversations,
    },
    HALF_PAST,
  );
}

function row(scope: "records" | "conversations"): HTMLElement {
  const found = screen
    .getAllByTestId("reveal-budget-row")
    .find((element) => element.dataset["scope"] === scope);
  if (found === undefined) throw new Error(`no ${scope} row`);
  return found;
}

describe("RevealBudgetMeter", () => {
  it("says 'not measured yet' rather than zero when nothing has been reported", () => {
    render(
      <RevealBudgetMeter
        budget={UNMEASURED_REVEAL_BUDGET}
        ceilings={CEILINGS}
        cost={{ records: 1, conversations: 0 }}
        now={HALF_PAST}
      />,
    );
    const records = row("records");
    expect(records.dataset["band"]).toBe("unmeasured");
    expect(within(records).getAllByText(/not measured yet/u).length).toBeGreaterThan(0);
    // The ceiling is still useful even when the remainder is not known.
    expect(records.textContent).toContain("200");
    expect(records.textContent).not.toMatch(/\b0 of 200\b/u);
  });

  it("shows the cost of the pending reveal AGAINST what is left, before any confirm", () => {
    render(
      <RevealBudgetMeter
        budget={measured(143, null)}
        ceilings={CEILINGS}
        cost={{ records: 1, conversations: 0 }}
        now={HALF_PAST}
      />,
    );
    const records = row("records");
    expect(records.textContent).toContain("143 of 200 left this hour");
    expect(records.textContent).toContain("this reveal costs 1 record");
    expect(records.textContent).toContain("142 would remain");
  });

  it("names the reset, because a spent budget with no reset time is a support ticket", () => {
    render(
      <RevealBudgetMeter budget={measured(143, null)} ceilings={CEILINGS} now={HALF_PAST} />,
    );
    expect(row("records").textContent).toContain("resets in 30 min");
  });

  it("draws the conversation ceiling only when the reveal actually touches it", () => {
    const { rerender } = render(
      <RevealBudgetMeter
        budget={UNMEASURED_REVEAL_BUDGET}
        ceilings={CEILINGS}
        cost={{ records: 1, conversations: 0 }}
        now={HALF_PAST}
      />,
    );
    expect(screen.getAllByTestId("reveal-budget-row")).toHaveLength(1);

    rerender(
      <RevealBudgetMeter
        budget={UNMEASURED_REVEAL_BUDGET}
        ceilings={CEILINGS}
        cost={{ records: 50, conversations: 1 }}
        now={HALF_PAST}
      />,
    );
    expect(screen.getAllByTestId("reveal-budget-row")).toHaveLength(2);
    expect(row("conversations").textContent).toContain("resets in 13 h 30 min");
  });

  it("pairs every band with a glyph and a word, never colour alone", () => {
    render(
      <RevealBudgetMeter
        budget={measured(10, null)}
        ceilings={CEILINGS}
        cost={{ records: 50, conversations: 0 }}
        now={HALF_PAST}
      />,
    );
    const records = row("records");
    expect(records.dataset["band"]).toBe("insufficient");
    expect(within(records).getByText("⊘")).toBeInTheDocument();
    expect(within(records).getByText("not enough left for this reveal")).toBeInTheDocument();
  });

  it("distinguishes 'spent' from 'too big for what is left'", () => {
    const { rerender } = render(
      <RevealBudgetMeter
        budget={measured(0, null)}
        ceilings={CEILINGS}
        cost={{ records: 1, conversations: 0 }}
        now={HALF_PAST}
      />,
    );
    expect(row("records").dataset["band"]).toBe("spent");

    rerender(
      <RevealBudgetMeter
        budget={measured(30, null)}
        ceilings={CEILINGS}
        cost={{ records: 50, conversations: 0 }}
        now={HALF_PAST}
      />,
    );
    expect(row("records").dataset["band"]).toBe("insufficient");
  });

  it("drops a reading whose fixed window has already rolled", () => {
    render(
      <RevealBudgetMeter
        budget={measured(3, null)}
        ceilings={CEILINGS}
        now={Date.UTC(2026, 8, 2, 11, 1, 0)}
      />,
    );
    const records = row("records");
    expect(records.dataset["band"]).toBe("unmeasured");
    expect(records.textContent).not.toContain("3 of 200");
  });

  it("survives a deployment whose ceilings have not arrived yet", () => {
    render(
      <RevealBudgetMeter
        budget={UNMEASURED_REVEAL_BUDGET}
        ceilings={{ records: null, conversations: null }}
        cost={{ records: 1, conversations: 0 }}
        now={HALF_PAST}
      />,
    );
    expect(row("records").textContent).toContain("not measured yet");
    expect(screen.queryByTestId("reveal-budget-spend")).not.toBeInTheDocument();
  });
});
