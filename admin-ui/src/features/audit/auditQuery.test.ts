/**
 * The two derivations §11.2 names, tested without a DOM.
 *
 * The load-bearing assertion is the second one: **reveals are charted by `record_count`, not
 * by row count**. A regression here is invisible on screen — the chart still draws bars — and
 * it silently turns the exposure figure back into a click count, which is the exact misread
 * §12.3 says the record-counted budget exists to prevent.
 */

import { describe, expect, it } from "vitest";

import type { AuditEntryView } from "@/api";

import {
  countDestructive,
  countRoutine,
  isDestructiveAction,
  revealExposureByActor,
  toAuditQuery,
} from "./auditQuery";

function entry(overrides: Partial<AuditEntryView> = {}): AuditEntryView {
  return {
    seq: 1,
    id: "11111111-2222-3333-4444-555555555555",
    at: "2026-09-01T09:15:00Z",
    actorId: "11111111-2222-3333-4444-555555555555",
    actorUsername: "operator",
    actorRole: "owner",
    action: "login.success",
    subjectType: "admin_user",
    subjectId: null,
    fieldNames: null,
    recordCount: null,
    reasonCode: "routine_ops",
    reasonRef: null,
    hasReasonText: false,
    reasonText: null,
    outcome: "ok",
    errorCode: null,
    correlationId: null,
    ip: null,
    configVersion: null,
    chainHmac: "abc",
    ...overrides,
  };
}

describe("toAuditQuery", () => {
  it("omits absent filters rather than sending empty ones", () => {
    expect(toAuditQuery({})).toEqual({ limit: 50 });
  });

  it("carries the independent from/to window and the seq cursor", () => {
    expect(
      toAuditQuery({ from: "2026-09-01T00:00:00Z", cursor: "abc", limit: 25 }),
    ).toEqual({ from: "2026-09-01T00:00:00Z", cursor: "abc", limit: 25 });
  });
});

describe("the destructive set", () => {
  it("counts reveals, purges and config commits as destructive", () => {
    expect(isDestructiveAction("reveal.personal")).toBe(true);
    expect(isDestructiveAction("user.purge.done")).toBe(true);
    expect(isDestructiveAction("config.commit")).toBe(true);
  });

  it("does not count a login or a refusal", () => {
    expect(isDestructiveAction("login.success")).toBe(false);
    expect(isDestructiveAction("permission.denied")).toBe(false);
  });

  it("splits a window into two counts that do not overlap", () => {
    const entries = [
      entry({ seq: 1, action: "login.success" }),
      entry({ seq: 2, action: "reveal.personal" }),
      entry({ seq: 3, action: "user.block" }),
    ];
    expect(countDestructive(entries)).toBe(2);
    expect(countRoutine(entries)).toBe(1);
    expect(countDestructive(entries) + countRoutine(entries)).toBe(entries.length);
  });
});

describe("revealExposureByActor", () => {
  it("charts RECORDS, not rows — one reveal of 500 outweighs five reveals of one", () => {
    const rows = revealExposureByActor([
      entry({ seq: 1, actorUsername: "bulk", action: "reveal.personal", recordCount: 500 }),
      ...Array.from({ length: 5 }, (_unused, index) =>
        entry({
          seq: 10 + index,
          actorUsername: "careful",
          action: "reveal.personal",
          recordCount: 1,
        }),
      ),
    ]);

    expect(rows[0]?.actor).toBe("bulk");
    expect(rows[0]?.records).toBe(500);
    expect(rows[0]?.reveals).toBe(1);
    expect(rows[1]?.actor).toBe("careful");
    expect(rows[1]?.records).toBe(5);
    expect(rows[1]?.reveals).toBe(5);
  });

  it("does not read a null recordCount as zero — it counts it as uncounted", () => {
    const rows = revealExposureByActor([
      entry({ actorUsername: "operator", action: "reveal.personal", recordCount: null }),
      entry({ seq: 2, actorUsername: "operator", action: "reveal.personal", recordCount: 3 }),
    ]);
    expect(rows[0]?.records).toBe(3);
    expect(rows[0]?.reveals).toBe(2);
    expect(rows[0]?.uncountedReveals).toBe(1);
  });

  it("is empty for an empty window rather than throwing", () => {
    expect(revealExposureByActor([])).toEqual([]);
  });
});
