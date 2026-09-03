/**
 * "Is there a stale account?" is a judgement, so it is pinned here rather than left to a
 * render assertion. The cases that matter are the three shapes of stale and the one shape
 * that looks stale and is not: a deactivated account.
 */

import { describe, expect, it } from "vitest";

import type { AdminAccountView } from "@/api";

import { DORMANT_DAYS, staleReasons, summariseRoster } from "./adminRoster";

const NOW = Date.parse("2026-09-02T12:00:00Z");
const DAY = 86_400_000;

function account(overrides: Partial<AdminAccountView> = {}): AdminAccountView {
  return {
    id: "11111111-2222-3333-4444-555555555555",
    username: "operator",
    role: "admin",
    isActive: true,
    mustChangePassword: false,
    lastLoginAt: "2026-09-01T09:15:00Z",
    passwordChangedAt: "2026-01-05T09:15:00Z",
    createdAt: "2026-01-01T09:15:00Z",
    ...overrides,
  };
}

describe("staleReasons", () => {
  it("says nothing about a healthy, recently used account", () => {
    expect(staleReasons(account(), NOW)).toEqual([]);
  });

  it("flags an account that has never signed in", () => {
    expect(staleReasons(account({ lastLoginAt: null }), NOW)).toEqual(["never-signed-in"]);
  });

  it("flags a credential still on its temporary password", () => {
    expect(staleReasons(account({ mustChangePassword: true }), NOW)).toEqual([
      "temporary-password",
    ]);
  });

  it("flags a long-quiet account, and only past the threshold", () => {
    const quiet = new Date(NOW - (DORMANT_DAYS + 1) * DAY).toISOString();
    const recent = new Date(NOW - (DORMANT_DAYS - 1) * DAY).toISOString();
    expect(staleReasons(account({ lastLoginAt: quiet }), NOW)).toEqual(["dormant"]);
    expect(staleReasons(account({ lastLoginAt: recent }), NOW)).toEqual([]);
  });

  it("carries both reasons when a bootstrapped account never signed in", () => {
    const reasons = staleReasons(
      account({ lastLoginAt: null, mustChangePassword: true }),
      NOW,
    );
    expect(reasons).toEqual(["never-signed-in", "temporary-password"]);
  });

  it("never calls a DEACTIVATED account stale — its silence is the control working", () => {
    const dead = account({ isActive: false, lastLoginAt: null, mustChangePassword: true });
    expect(staleReasons(dead, NOW)).toEqual([]);
  });
});

describe("summariseRoster", () => {
  it("counts active and deactivated separately and keeps both in the list", () => {
    const summary = summariseRoster(
      [
        account({ id: "a", username: "one" }),
        account({ id: "b", username: "two", isActive: false }),
        account({ id: "c", username: "three" }),
      ],
      NOW,
    );
    expect(summary.activeCount).toBe(2);
    expect(summary.deactivatedCount).toBe(1);
  });

  it("takes last-login recency from the most recent ACTIVE account", () => {
    const summary = summariseRoster(
      [
        account({ id: "a", lastLoginAt: "2026-08-01T00:00:00Z" }),
        // Deactivated and more recent — it must not become "the most recent sign-in".
        account({ id: "b", isActive: false, lastLoginAt: "2026-09-02T00:00:00Z" }),
        account({ id: "c", lastLoginAt: "2026-08-30T00:00:00Z" }),
      ],
      NOW,
    );
    expect(summary.lastLoginAt).toBe("2026-08-30T00:00:00Z");
  });

  it("reports never, not a blank, when no active account has ever signed in", () => {
    const summary = summariseRoster([account({ lastLoginAt: null })], NOW);
    expect(summary.lastLoginAt).toBeNull();
  });

  it("ranks the never-signed-in account above a merely quiet one", () => {
    const quiet = new Date(NOW - (DORMANT_DAYS + 5) * DAY).toISOString();
    const summary = summariseRoster(
      [
        account({ id: "a", username: "quiet", lastLoginAt: quiet }),
        account({ id: "b", username: "fresh", lastLoginAt: null }),
      ],
      NOW,
    );
    expect(summary.stale.map((entry) => entry.account.username)).toEqual(["fresh", "quiet"]);
  });
});
