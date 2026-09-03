/**
 * The step-up seam — the thing four later phases will reuse, so its edges are pinned here.
 *
 * The one that matters most is the NEGATIVE case: a `STEP_UP_REQUIRED` with no `details` is
 * the ROUTER-level refusal, which reports a §12.2 cell's step-up requirement without ever
 * consulting the session's grant. Offering a password box for it would be a loop the operator
 * cannot win — they would re-authenticate correctly, retry, and be refused identically.
 */

import { describe, expect, it } from "vitest";

import type { ApiFailure } from "@/api";

import { graceNote, grantWindowS, isSameTarget, isStepUpRequired, stepUpTargetOf, ZERO_GRACE_NOTE } from "./stepUp";

const ORDER = "3f2a9c10-8b44-4d21-9f0e-6a7c5b3e1d02";

function failure(init: Partial<ApiFailure> = {}): ApiFailure {
  return {
    ok: false,
    code: "STEP_UP_REQUIRED",
    message: "re-authenticate for this action and this subject",
    status: 403,
    correlationId: "c0ffee",
    endpoint: "POST /api/reveal",
    details: { stepUpAction: "reveal", subjectId: ORDER },
    issues: null,
    retryAfterS: null,
    ...init,
  };
}

describe("stepUpTargetOf", () => {
  it("reads the remedy off the refusal itself", () => {
    expect(stepUpTargetOf(failure())).toEqual({ action: "reveal", subjectId: ORDER });
  });

  it("hands the subject id back BYTE-IDENTICAL — a reformatted id is a silent 403", () => {
    const target = stepUpTargetOf(failure());
    expect(target?.subjectId).toBe(ORDER);
  });

  it("is null for a router-level STEP_UP_REQUIRED, which no password can fix", () => {
    expect(stepUpTargetOf(failure({ details: null }))).toBeNull();
    expect(stepUpTargetOf(failure({ details: { permission: "reveal.personal_data" } }))).toBeNull();
  });

  it("is null for an action this build has never heard of", () => {
    expect(
      stepUpTargetOf(failure({ details: { stepUpAction: "quantum.audit", subjectId: ORDER } })),
    ).toBeNull();
  });

  it("is null for every other failure, including a plain FORBIDDEN", () => {
    expect(stepUpTargetOf(failure({ code: "FORBIDDEN", details: null }))).toBeNull();
    expect(stepUpTargetOf(null)).toBeNull();
  });

  it("recognises the code on its own, for a caller that only wants to branch", () => {
    expect(isStepUpRequired(failure())).toBe(true);
    expect(isStepUpRequired(failure({ code: "FORBIDDEN" }))).toBe(false);
    expect(isStepUpRequired(null)).toBe(false);
  });
});

describe("isSameTarget", () => {
  it("compares both halves — an action alone is not a grant", () => {
    const target = { action: "reveal", subjectId: ORDER } as const;
    expect(isSameTarget(target, { action: "reveal", subjectId: ORDER })).toBe(true);
    expect(isSameTarget(target, { action: "reveal", subjectId: "other" })).toBe(false);
    expect(isSameTarget(target, { action: "user.purge", subjectId: ORDER })).toBe(false);
  });
});

describe("the grace window", () => {
  it("is zero for the two §12.1 T2 actions, whatever the deployment configured", () => {
    expect(grantWindowS("user.purge", 300)).toBe(0);
    expect(grantWindowS("config.write", 900)).toBe(0);
    expect(graceNote(grantWindowS("user.purge", 300))).toBe(ZERO_GRACE_NOTE);
  });

  it("is the configured grace for a reveal", () => {
    expect(grantWindowS("reveal", 300)).toBe(300);
    expect(graceNote(300)).toContain("5 min");
  });

  it("never claims a grant is single-use, because nothing clears step_up_scope", () => {
    expect(graceNote(300)).toContain("not single-use");
  });
});
