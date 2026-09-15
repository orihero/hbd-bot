import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { PageStats, type PageStat } from "@/components/PageStats";

/**
 * The rules in `PageStats`' own doc comment, asserted one by one.
 *
 * Every one of these is a defect that shipped somewhere before: a currency quoted beside a dash,
 * a blank number with nothing saying why it was blank, a zero printed while the request that
 * would have produced the real figure was still in flight. The component is small; what it
 * refuses to do is the entire reason it exists, so the tests are written against the refusals.
 */
describe("PageStats", () => {
  it("prints an em dash for a value that was not measured, and DROPS its unit", () => {
    const stats: readonly PageStat[] = [
      { key: "revenue", label: "Revenue", value: null, unit: "so'm" },
    ];
    render(<PageStats stats={stats} />);

    expect(screen.getByText("—")).toBeInTheDocument();
    /* The point of the rule: a currency beside a dash quotes a price for a figure that does
       not exist. The unit must not be anywhere on the screen, not merely dimmed. */
    expect(screen.queryByText("so'm")).toBeNull();
  });

  it("renders the reason under the dash, because an unexplained blank is the defect", () => {
    const stats: readonly PageStat[] = [
      {
        key: "revenue",
        label: "Revenue",
        value: null,
        unit: "so'm",
        reason: "No FX rate published for this window",
      },
    ];
    render(<PageStats stats={stats} />);

    expect(screen.getByText("—")).toBeInTheDocument();
    expect(screen.getByText("No FX rate published for this window")).toBeVisible();
  });

  it("renders a measured value with its unit, and no reason caption", () => {
    const stats: readonly PageStat[] = [
      {
        key: "revenue",
        label: "Revenue",
        value: "1 240 000",
        unit: "so'm",
        /* A reason supplied alongside a real figure is stale, not extra information: it
           explains an absence that is not there, so it must not be shown. */
        reason: "No FX rate published for this window",
      },
    ];
    render(<PageStats stats={stats} />);

    expect(screen.getByText("1 240 000")).toBeVisible();
    expect(screen.getByText("so'm")).toBeVisible();
    expect(screen.queryByText("—")).toBeNull();
    expect(screen.queryByText("No FX rate published for this window")).toBeNull();
  });

  it("associates each label with its value so the two are announced together", () => {
    const stats: readonly PageStat[] = [
      { key: "settled", label: "Settled", value: "412" },
    ];
    render(<PageStats stats={stats} />);

    expect(screen.getByLabelText("Settled")).toHaveTextContent("412");
  });

  it("while loading, shows skeletons, sets aria-busy, and prints no digit at all", () => {
    const stats: readonly PageStat[] = [
      { key: "intents", label: "Intents", value: "0" },
      { key: "settled", label: "Settled", value: null, reason: "Not instrumented" },
    ];
    const { container } = render(<PageStats stats={stats} isLoading />);

    expect(screen.getByRole("list")).toHaveAttribute("aria-busy", "true");
    expect(container.querySelectorAll("[aria-hidden].animate-pulse").length).toBeGreaterThan(0);

    /* The assertion that matters. A tile that shows `0` while it waits has told the operator
       something false — and a dash while loading would be just as wrong, since nothing has
       been measured OR failed to be measured yet. Labels only. */
    const text = container.textContent ?? "";
    expect(text).not.toMatch(/\d/);
    expect(text).not.toContain("—");
    expect(screen.getByText("Intents")).toBeVisible();
  });

  it("tints only the tile that asked for the warn tone", () => {
    const stats: readonly PageStat[] = [
      { key: "faults", label: "Faults", value: "7", tone: "warn" },
      { key: "settled", label: "Settled", value: "412" },
    ];
    render(<PageStats stats={stats} />);

    expect(screen.getByLabelText("Faults").className).toContain("text-warn-deep");
    expect(screen.getByLabelText("Settled").className).not.toContain("text-warn-deep");
  });

  it("walks as a list, one item per stat", () => {
    const stats: readonly PageStat[] = [
      { key: "accounts", label: "Accounts", value: "9 011" },
      { key: "reachable", label: "Reachable", value: "8 402" },
      { key: "blocked", label: "Blocked", value: null, reason: "Not instrumented" },
    ];
    render(<PageStats stats={stats} />);

    expect(screen.getAllByRole("listitem")).toHaveLength(3);
  });
});
