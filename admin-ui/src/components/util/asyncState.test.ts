/**
 * The six states' PRECEDENCE. Every case here corresponds to a sentence in §11.4 or §12.3,
 * and each one is a bug that has a name.
 */

import { describe, expect, it } from "vitest";

import { LIVE_THRESHOLD_MS } from "@/lib/queryClient";

import { keepsChildren, resolveAsyncState, type AsyncStateInput } from "./asyncState";

const BASE: AsyncStateInput = {
  status: "success",
  hasData: true,
  isEmpty: false,
  activeFilterCount: 0,
  purgedAt: null,
  dataUpdatedAt: 1_000_000,
  now: 1_000_000,
};

describe("resolveAsyncState", () => {
  it("is ready when fresh data is in hand", () => {
    expect(resolveAsyncState(BASE)).toBe("ready");
  });

  it("is skeleton before the first answer", () => {
    expect(resolveAsyncState({ ...BASE, status: "pending", hasData: false })).toBe("skeleton");
  });

  it("is error only when there is nothing to keep", () => {
    expect(resolveAsyncState({ ...BASE, status: "error", hasData: false })).toBe("error");
  });

  it("is STALE, not error, when a poll fails on top of last-known data", () => {
    // §11.4: "a dashboard that blanks on a failed poll is worse than one showing stale
    // numbers labelled stale".
    expect(resolveAsyncState({ ...BASE, status: "error", hasData: true })).toBe("stale");
  });

  it("goes stale at the same threshold the LIVE pill goes amber at", () => {
    const now = BASE.dataUpdatedAt + LIVE_THRESHOLD_MS + 1;
    expect(resolveAsyncState({ ...BASE, now })).toBe("stale");
    expect(resolveAsyncState({ ...BASE, now: BASE.dataUpdatedAt + LIVE_THRESHOLD_MS })).toBe(
      "ready",
    );
  });

  it("distinguishes empty-filtered from empty-virgin", () => {
    expect(resolveAsyncState({ ...BASE, isEmpty: true })).toBe("empty-virgin");
    expect(resolveAsyncState({ ...BASE, isEmpty: true, activeFilterCount: 3 })).toBe(
      "empty-filtered",
    );
  });

  describe("purged wins over everything", () => {
    // §12.3: `identity_purged_at` is ALWAYS displayed. "No name" and "name purged on
    // schedule 2026-05-14" are different facts and only one is defensible.
    const purged = { ...BASE, purgedAt: "2026-05-14T00:00:00Z" };

    it("over ready", () => {
      expect(resolveAsyncState(purged)).toBe("purged");
    });

    it("over error — a purge is a fact, not a failure", () => {
      expect(resolveAsyncState({ ...purged, status: "error", hasData: false })).toBe("purged");
    });

    it("over skeleton", () => {
      expect(resolveAsyncState({ ...purged, status: "pending", hasData: false })).toBe("purged");
    });

    it("over empty — a blank would be the wrong answer twice over", () => {
      expect(resolveAsyncState({ ...purged, isEmpty: true })).toBe("purged");
    });
  });

  it("does not go red on a cold start (dataUpdatedAt === 0 with data)", () => {
    // `keepPreviousData` can hand over data whose `dataUpdatedAt` is still 0 on the very
    // first render; that is "no answer yet", not "very stale".
    expect(resolveAsyncState({ ...BASE, dataUpdatedAt: 0 })).toBe("ready");
  });
});

describe("keepsChildren", () => {
  it("is true exactly for the two states that still render last-known data", () => {
    expect(keepsChildren("ready")).toBe(true);
    expect(keepsChildren("stale")).toBe(true);
    for (const kind of ["skeleton", "error", "empty-virgin", "empty-filtered", "purged"] as const) {
      expect(keepsChildren(kind)).toBe(false);
    }
  });
});
