/**
 * §14 Slice 1d: "`/orders/:id/timeline` renders a `sources` legend: `chat` and `payments`
 * read 'not enabled in this deployment', and `stateTransitions` is labelled `inferred`."
 *
 * The copy is pinned in `SOURCE_UNAVAILABLE_LABEL` and asserted verbatim: "no chat
 * messages" and "chat capture is off" lead to opposite conclusions about whether a customer
 * replied.
 */

import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { SOURCE_UNAVAILABLE_LABEL, TIMELINE_SOURCE_VALUES } from "@/api";

import { INFERRED_SOURCE_LABEL, TimelineSourceLegend } from "./TimelineSourceLegend";

function renderLegend(): void {
  render(
    <TimelineSourceLegend
      availableSources={["order", "attempts", "assets", "audit"]}
      unavailableSources={["chat", "payments"]}
    />,
  );
}

function rowFor(source: string): HTMLElement | undefined {
  return screen
    .getAllByTestId("timeline-source")
    .find((node) => node.getAttribute("data-source") === source);
}

describe("an absent source", () => {
  it("reads 'not enabled in this deployment', never as nothing having happened", () => {
    renderLegend();
    for (const source of ["chat", "payments"]) {
      const row = rowFor(source);
      expect(row).toHaveTextContent(SOURCE_UNAVAILABLE_LABEL);
      expect(row).not.toHaveTextContent("nothing");
      expect(row).toHaveAttribute("data-standing", "unavailable");
    }
  });

  it("marks the available ones without that caption", () => {
    renderLegend();
    expect(rowFor("attempts")).not.toHaveTextContent(SOURCE_UNAVAILABLE_LABEL);
    expect(rowFor("attempts")).toHaveAttribute("data-standing", "available");
  });

  it("lists every source the wire can name, so a legend is never partial", () => {
    renderLegend();
    for (const source of TIMELINE_SOURCE_VALUES) {
      expect(rowFor(source)).toBeDefined();
    }
  });

  it("flags a source in neither list rather than assuming it is fine", () => {
    render(<TimelineSourceLegend availableSources={["order"]} unavailableSources={[]} />);
    expect(rowFor("audit")).toHaveAttribute("data-standing", "unknown");
  });
});

describe("state transitions", () => {
  it("is labelled inferred — there is no state-transition log on this build", () => {
    renderLegend();
    const row = rowFor("state_transitions");
    expect(row).toHaveTextContent("state transitions");
    expect(row).toHaveTextContent(INFERRED_SOURCE_LABEL);
  });
});
