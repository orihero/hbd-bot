/**
 * The formatting rules the plan pins by hand, so a later "tidy-up" has to argue with a test.
 */

import { describe, expect, it } from "vitest";

import {
  EMPTY_VALUE,
  NOT_PRICED_LABEL,
  costSourceLabel,
  formatCostUsd,
  formatRate,
  formatSpendUsd,
  formatTimestamp,
  formatTotal,
  latencyBand,
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

  it("classifies latency correctly: <1s fast, 1-5s neutral, 5-15s slow, >15s critical", () => {
    expect(latencyBand(null)).toBe("unknown");
    expect(latencyBand(undefined)).toBe("unknown");
    expect(latencyBand(500)).toBe("fast");
    expect(latencyBand(1_000)).toBe("neutral");
    expect(latencyBand(3_500)).toBe("neutral");
    expect(latencyBand(5_000)).toBe("neutral");
    expect(latencyBand(8_000)).toBe("slow");
    expect(latencyBand(15_000)).toBe("slow");
    expect(latencyBand(15_001)).toBe("critical");
    expect(latencyBand(30_000)).toBe("critical");
  });
});

describe("vendor spend", () => {
  it("says 'not priced' rather than $0.00 when this deployment configures no rate", () => {
    // Arrange: the shipped default — every vendor rate is 0.0, so nothing is priced.
    const isPriced = false;

    // Act / Assert: the absence is a sentence, and no currency reaches the DOM.
    expect(formatSpendUsd(null, isPriced)).toBe(NOT_PRICED_LABEL);
    expect(formatSpendUsd(12.34, isPriced)).toBe(NOT_PRICED_LABEL);
    expect(formatSpendUsd(0, isPriced)).not.toContain("$");
  });

  it("renders a null cost as an em dash even when the deployment IS priced — never $0.00", () => {
    // Arrange: rates exist, but this particular leg (Scribe) carries no cost by design.
    // Act / Assert: an unpriced leg inside a priced deployment is absent, not free.
    expect(formatSpendUsd(null, true)).toBe(EMPTY_VALUE);
    expect(formatSpendUsd(undefined, true)).toBe(EMPTY_VALUE);
    expect(formatSpendUsd(Number.NaN, true)).toBe(EMPTY_VALUE);
    expect(formatSpendUsd(null, true)).not.toBe("$0.00");
  });

  it("rounds an aggregate to cents, while a single call keeps its four decimals", () => {
    // Arrange: the same figure through both formatters.
    const costUsd = 0.014_2;

    // Act / Assert: the aggregate is money to compare against an invoice; the single call is
    // a measurement whose whole magnitude lives in the third and fourth digits.
    expect(formatSpendUsd(costUsd, true)).toBe("$0.01");
    expect(formatCostUsd(costUsd, true)).toBe("$0.0142");
    expect(formatSpendUsd(12.345, true)).toBe("$12.35");
    // A genuine, measured zero still prints as a figure — it is `null` that must not.
    expect(formatSpendUsd(0, true)).toBe("$0.00");
  });

  it("gives the money and the provenance the SAME sentence for an unpriced row, so only one may be rendered", () => {
    // Arrange: one unpriced group, read through both formatters. `cost_usd` and
    // `cost_source` are null together — the database will not let one exist without the
    // other — so both of these describe the same row at the same time.
    const group: { costUsd: number | null; costSource: string | null } = {
      costUsd: null,
      costSource: null,
    };

    // Act.
    const value = formatSpendUsd(group.costUsd, group.costSource !== null);
    const provenance = costSourceLabel(group.costSource);

    // Assert: identical strings, which is why a cell that prints both reads "not priced not
    // priced". `/vendors` shipped that way and now omits the provenance chip when there is
    // no provenance; this test is the anchor that makes re-adding it a visible decision.
    expect(value).toBe(NOT_PRICED_LABEL);
    expect(provenance).toBe(NOT_PRICED_LABEL);
    expect(value).toBe(provenance);
  });

  it("labels a cost's provenance, and calls an unknown or absent source 'not priced'", () => {
    // Arrange / Act / Assert: four strengths of claim, and one honest fallback.
    expect(costSourceLabel("vendor_reported")).toBe("vendor-reported");
    expect(costSourceLabel("derived")).toBe("derived");
    expect(costSourceLabel("estimated")).toBe("estimated");
    expect(costSourceLabel("mixed")).toBe("mixed");
    expect(costSourceLabel(null)).toBe(NOT_PRICED_LABEL);
    expect(costSourceLabel("invented_by_a_newer_server")).toBe(NOT_PRICED_LABEL);
  });
});

describe("a capped total", () => {
  it("renders TOTAL_COUNT_CAP with a plus — 10,000 flat would be a wrong number", () => {
    expect(formatTotal(10_000, false)).toBe("10,000+");
    expect(formatTotal(10_000, true)).toBe("10,000");
    expect(formatTotal(null, null)).toBe(EMPTY_VALUE);
  });
});
