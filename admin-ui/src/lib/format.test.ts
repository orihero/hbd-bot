/**
 * The formatting rules the plan pins by hand, so a later "tidy-up" has to argue with a test.
 */

import { describe, expect, it } from "vitest";

import {
  EMPTY_VALUE,
  formatCostUsd,
  formatRate,
  formatTimestamp,
  formatTotal,
  rateBand,
  retryabilityLabel,
} from "./format";

describe("timestamps carry their zone", () => {
  it("never renders a bare time — an ambiguous 14:32 is a support incident (§11.2)", () => {
    const rendered = formatTimestamp("2026-09-02T12:00:00Z", "utc");
    expect(rendered).toBe("2026-09-02 12:00Z");
    expect(rendered).toMatch(/Z$/);
  });

  it("renders an unparseable instant as an em dash, never as Invalid Date", () => {
    expect(formatTimestamp("not-a-date")).toBe(EMPTY_VALUE);
    expect(formatTimestamp(null)).toBe(EMPTY_VALUE);
  });
});

describe("the three-state numbers", () => {
  it("renders a null success rate as absent, never as 0% (there is no denominator)", () => {
    expect(formatRate(null)).toBe(EMPTY_VALUE);
    expect(formatRate(0)).toBe("0.0%");
    expect(rateBand(null)).toBe("unknown");
  });

  it("bands the delivery rate at §11.2's thresholds: green >=95, amber 85-95, red <85", () => {
    expect(rateBand(0.96)).toBe("good");
    expect(rateBand(0.95)).toBe("good");
    expect(rateBand(0.9)).toBe("warn");
    expect(rateBand(0.84)).toBe("bad");
  });

  it("says 'not instrumented' rather than $0.00 when the row carries no telemetry", () => {
    expect(formatCostUsd(null, false)).toBe("not instrumented");
    expect(formatCostUsd(0.0142, true)).toBe("$0.0142");
  });

  it("keeps retryability three-state: unknown is not the same claim as terminal", () => {
    expect(retryabilityLabel(null)).toBe("unknown");
    expect(retryabilityLabel(false)).toBe("terminal");
    expect(retryabilityLabel(true)).toBe("retryable");
  });
});

describe("a capped total", () => {
  it("renders TOTAL_COUNT_CAP with a plus — 10,000 flat would be a wrong number", () => {
    expect(formatTotal(10_000, false)).toBe("10,000+");
    expect(formatTotal(10_000, true)).toBe("10,000");
    expect(formatTotal(null, null)).toBe(EMPTY_VALUE);
  });
});
