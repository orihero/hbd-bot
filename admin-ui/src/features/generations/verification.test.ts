import { describe, expect, it } from "vitest";

import { NAME_STRATEGY_VALUES, type StrategyOutcomeView } from "@/api";

import {
  CANDIDATE_ORDER_ENV,
  candidateOrderValue,
  hasBakeoffEvidence,
  overallVerification,
  suggestedCandidateOrder,
} from "./verification";

function outcome(
  strategy: StrategyOutcomeView["strategy"],
  attempts: number,
  verified: number,
): StrategyOutcomeView {
  return {
    strategy,
    attempts,
    verified,
    verificationRate: attempts === 0 ? 0 : verified / attempts,
  };
}

describe("overallVerification", () => {
  it("sums the groups rather than averaging their rates", () => {
    // 90/100 and 1/2 average to 0.70 but the true rate is 91/102.
    const totals = overallVerification([outcome("canonical", 100, 90), outcome("ascii", 2, 1)]);
    expect(totals.attempts).toBe(102);
    expect(totals.verified).toBe(91);
    expect(totals.rate).toBeCloseTo(91 / 102, 10);
  });

  it("reports null, never zero, when nothing ran", () => {
    // A 0% verification rate reads as "the verifier is broken"; "nothing has run yet" is a
    // different fact with a different next action.
    expect(overallVerification([]).rate).toBeNull();
    expect(overallVerification([outcome("canonical", 0, 0)]).rate).toBeNull();
  });
});

describe("suggestedCandidateOrder", () => {
  it("ranks by verification rate", () => {
    const order = suggestedCandidateOrder([
      outcome("canonical", 10, 5),
      outcome("ascii", 10, 9),
      outcome("stripped", 10, 7),
    ]);
    expect(order.slice(0, 3)).toEqual(["ascii", "stripped", "canonical"]);
  });

  it("breaks a rate tie on volume, so one lucky success never outranks four hundred", () => {
    const order = suggestedCandidateOrder([outcome("ascii", 1, 1), outcome("canonical", 400, 400)]);
    expect(order.slice(0, 2)).toEqual(["canonical", "ascii"]);
  });

  it("sends strategies that ran nothing to the end, in declaration order", () => {
    const order = suggestedCandidateOrder([outcome("phonetic", 4, 1)]);
    expect(order[0]).toBe("phonetic");
    expect(order.slice(1)).toEqual(NAME_STRATEGY_VALUES.filter((s) => s !== "phonetic"));
  });

  it("always returns every strategy exactly once", () => {
    const order = suggestedCandidateOrder([outcome("ascii", 3, 3)]);
    expect([...order].sort()).toEqual([...NAME_STRATEGY_VALUES].sort());
  });
});

describe("candidateOrderValue", () => {
  it("emits the comma-separated spelling `_split_csv` reads back", () => {
    expect(candidateOrderValue(["canonical", "ascii"])).toBe("canonical,ascii");
    expect(CANDIDATE_ORDER_ENV).toBe("BAYRAM_NAME_CANDIDATE_ORDER");
  });
});

describe("hasBakeoffEvidence", () => {
  it("is false when every strategy has zero attempts", () => {
    expect(hasBakeoffEvidence([])).toBe(false);
    expect(hasBakeoffEvidence([outcome("canonical", 0, 0)])).toBe(false);
    expect(hasBakeoffEvidence([outcome("canonical", 1, 0)])).toBe(true);
  });
});
