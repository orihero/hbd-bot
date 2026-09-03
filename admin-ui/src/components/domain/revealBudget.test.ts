/**
 * The budget as the client may honestly report it.
 *
 * Three properties carry the weight, and each of them is a way a meter lies:
 *
 *  - `null` is NOT zero. An untouched counter keeps what it had; a never-measured one says so.
 *  - A reading from a rolled window is discarded, not shown stale. The windows are fixed and
 *    epoch-aligned, so "3 left" measured at 10:59 describes a counter that no longer exists at
 *    11:01, and showing it would talk an operator out of work they are entitled to do.
 *  - A 429 is a MEASUREMENT. It is the only one an operator at their ceiling will get, and it
 *    has to name which budget and when it resets.
 */

import { describe, expect, it } from "vitest";

import { REVEAL_CONVERSATIONS_WINDOW_S, REVEAL_RECORDS_WINDOW_S, type ApiFailure } from "@/api";

import {
  applyBudgetRefusal,
  applyRevealBudget,
  budgetBand,
  budgetScopeOf,
  BUDGET_BAND_GLYPH,
  BUDGET_BAND_LABEL,
  currentSnapshot,
  formatResetIn,
  isSameWindow,
  readBudgetRefusal,
  remainingAfter,
  secondsToReset,
  UNMEASURED_REVEAL_BUDGET,
  willExceedBudget,
  windowIndex,
  windowResetAt,
} from "./revealBudget";

/** 2026-09-02T10:30:00Z — half past an hour, half way through a UTC day. */
const HALF_PAST = Date.UTC(2026, 8, 2, 10, 30, 0);
const NEXT_HOUR = Date.UTC(2026, 8, 2, 11, 0, 0);

function failure(init: Partial<ApiFailure>): ApiFailure {
  return {
    ok: false,
    code: "REVEAL_BUDGET_EXHAUSTED",
    message: "this operator's reveal budget for the window is spent",
    status: 429,
    correlationId: "c0ffee",
    endpoint: "POST /api/reveal",
    details: null,
    issues: null,
    retryAfterS: null,
    ...init,
  };
}

describe("the fixed, epoch-aligned windows", () => {
  it("indexes the hour the way budget._window_index does", () => {
    expect(windowIndex(HALF_PAST, REVEAL_RECORDS_WINDOW_S)).toBe(
      Math.floor(HALF_PAST / 1_000 / 3_600),
    );
  });

  it("resets on the clock hour, not an hour after the first reveal", () => {
    expect(windowResetAt(HALF_PAST, REVEAL_RECORDS_WINDOW_S)).toBe(NEXT_HOUR);
    expect(secondsToReset(HALF_PAST, REVEAL_RECORDS_WINDOW_S)).toBe(1_800);
  });

  it("makes the conversation budget a UTC DAY, so it resets at midnight", () => {
    expect(windowResetAt(HALF_PAST, REVEAL_CONVERSATIONS_WINDOW_S)).toBe(
      Date.UTC(2026, 8, 3, 0, 0, 0),
    );
  });

  it("puts 10:59 and 11:00 in different hours — 200 then 200 is inside policy", () => {
    const at1059 = Date.UTC(2026, 8, 2, 10, 59, 0);
    expect(isSameWindow(at1059, NEXT_HOUR, REVEAL_RECORDS_WINDOW_S)).toBe(false);
    expect(isSameWindow(at1059, HALF_PAST, REVEAL_RECORDS_WINDOW_S)).toBe(true);
  });
});

describe("learning from a reveal", () => {
  it("records the counters the response touched", () => {
    const next = applyRevealBudget(
      UNMEASURED_REVEAL_BUDGET,
      {
        recordsCharged: 1,
        recordsRemaining: 199,
        conversationsCharged: 0,
        conversationsRemaining: null,
      },
      HALF_PAST,
    );
    expect(next.records).toEqual({ remaining: 199, measuredAt: HALF_PAST });
    expect(next.conversations).toEqual({ remaining: null, measuredAt: null });
  });

  it("leaves an UNTOUCHED counter standing rather than blanking it to zero", () => {
    const withDay = applyRevealBudget(
      UNMEASURED_REVEAL_BUDGET,
      {
        recordsCharged: 50,
        recordsRemaining: 150,
        conversationsCharged: 1,
        conversationsRemaining: 19,
      },
      HALF_PAST,
    );
    const afterNameReveal = applyRevealBudget(
      withDay,
      {
        recordsCharged: 1,
        recordsRemaining: 149,
        conversationsCharged: 0,
        conversationsRemaining: null,
      },
      HALF_PAST + 60_000,
    );
    expect(afterNameReveal.conversations.remaining).toBe(19);
    expect(afterNameReveal.records.remaining).toBe(149);
  });

  it("drops a reading whose window has rolled instead of carrying it forward", () => {
    const measured = applyRevealBudget(
      UNMEASURED_REVEAL_BUDGET,
      {
        recordsCharged: 1,
        recordsRemaining: 3,
        conversationsCharged: 0,
        conversationsRemaining: null,
      },
      HALF_PAST,
    );
    expect(currentSnapshot(measured, NEXT_HOUR).records).toEqual({
      remaining: null,
      measuredAt: null,
    });
  });
});

describe("a 429 is a measurement", () => {
  const exhausted = failure({
    retryAfterS: 1_800,
    details: {
      budget: "records",
      recordsRequested: 50,
      recordsRemaining: 12,
      conversationsRemaining: null,
    },
  });

  it("names which of the two ceilings refused", () => {
    expect(budgetScopeOf(exhausted)).toBe("records");
    expect(budgetScopeOf(failure({ details: { budget: "conversations" } }))).toBe(
      "conversations",
    );
    expect(budgetScopeOf(failure({ details: null }))).toBeNull();
  });

  it("says what is left and when the window resets, from Retry-After", () => {
    const refusal = readBudgetRefusal(exhausted, HALF_PAST);
    expect(refusal.scopeLabel).toBe("records an hour");
    expect(refusal.remaining).toBe(12);
    expect(refusal.requested).toBe(50);
    expect(refusal.resetsInS).toBe(1_800);
    expect(refusal.resetsAt).toBe(NEXT_HOUR);
  });

  it("still gives a reset when a proxy stripped Retry-After", () => {
    const refusal = readBudgetRefusal(
      failure({ details: { budget: "conversations" }, retryAfterS: null }),
      HALF_PAST,
    );
    expect(refusal.resetsInS).toBe(secondsToReset(HALF_PAST, REVEAL_CONVERSATIONS_WINDOW_S));
  });

  it("folds the refusal's figures into the snapshot — the only reading at a ceiling", () => {
    const next = applyBudgetRefusal(UNMEASURED_REVEAL_BUDGET, exhausted, HALF_PAST);
    expect(next.records.remaining).toBe(12);
    expect(next.conversations.remaining).toBeNull();
  });
});

describe("bands — colour is never the only channel (§11.3)", () => {
  it("calls an unmeasured counter unmeasured, not healthy and not spent", () => {
    expect(budgetBand({ remaining: null, measuredAt: null }, { cost: 1, ceiling: 200 })).toBe(
      "unmeasured",
    );
  });

  it("separates 'too big for what is left' from 'nothing left at all'", () => {
    const reading = { remaining: 10, measuredAt: HALF_PAST };
    expect(budgetBand(reading, { cost: 50, ceiling: 200 })).toBe("insufficient");
    expect(budgetBand({ remaining: 0, measuredAt: HALF_PAST }, { cost: 1, ceiling: 200 })).toBe(
      "spent",
    );
  });

  it("warns while there is still room", () => {
    expect(budgetBand({ remaining: 20, measuredAt: HALF_PAST }, { cost: 1, ceiling: 200 })).toBe(
      "tight",
    );
    expect(budgetBand({ remaining: 199, measuredAt: HALF_PAST }, { cost: 1, ceiling: 200 })).toBe(
      "ample",
    );
  });

  it("gives every band a glyph AND a word, so the hue is never load-bearing", () => {
    for (const band of ["unmeasured", "ample", "tight", "insufficient", "spent"] as const) {
      expect(BUDGET_BAND_GLYPH[band].length).toBeGreaterThan(0);
      expect(BUDGET_BAND_LABEL[band].length).toBeGreaterThan(0);
    }
  });
});

describe("what is left afterwards", () => {
  it("is null when the answer would be a guess", () => {
    expect(remainingAfter({ remaining: null, measuredAt: null }, 1)).toBeNull();
    expect(remainingAfter({ remaining: 100, measuredAt: HALF_PAST }, 0)).toBeNull();
  });

  it("never goes below zero", () => {
    expect(remainingAfter({ remaining: 3, measuredAt: HALF_PAST }, 50)).toBe(0);
  });
});

describe("willExceedBudget", () => {
  const measured = applyRevealBudget(
    UNMEASURED_REVEAL_BUDGET,
    {
      recordsCharged: 1,
      recordsRemaining: 10,
      conversationsCharged: 0,
      conversationsRemaining: null,
    },
    HALF_PAST,
  );

  it("is true only when this tab has actually measured a shortfall", () => {
    expect(willExceedBudget(measured, { records: 50, conversations: 1 }, HALF_PAST)).toBe(true);
    expect(willExceedBudget(measured, { records: 1, conversations: 0 }, HALF_PAST)).toBe(false);
  });

  it("is false when nothing has been measured — an unknown budget is not a refusal", () => {
    expect(
      willExceedBudget(UNMEASURED_REVEAL_BUDGET, { records: 50, conversations: 1 }, HALF_PAST),
    ).toBe(false);
  });
});

describe("formatResetIn", () => {
  it("reads as a wait rather than as a measured duration", () => {
    expect(formatResetIn(43)).toBe("in 43s");
    expect(formatResetIn(1_800)).toBe("in 30 min");
    expect(formatResetIn(11_100)).toBe("in 3 h 05 min");
  });
});
