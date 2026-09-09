import { describe, expect, it } from "vitest";

import type { UserView } from "@/api";

import {
  DAY_MS,
  NEW_USER_WINDOW_DAYS,
  buildNewUserSeries,
  newUserWindow,
  utcDayStart,
} from "./newUsers";

const ANCHOR = Date.parse("2026-09-02T13:45:00Z");

/**
 * A `UserView` that exists only to carry an `accountCreatedAt` into the bucketer.
 *
 * `z.infer` makes every `.nullable()` field a REQUIRED property, so the nine contact-profile
 * fields and the three credit ones have to be written out here even though
 * `buildNewUserSeries` reads exactly one of them. The credit trio is `null` — no
 * `credit_accounts` row, which is what a brand-new account looks like and is emphatically not
 * a balance of `0`. They are all given their EMPTY values on purpose: this fixture must not become a
 * second, quietly different description of what an onboarded customer looks like. The screen
 * tests own that description, and a bucketer that ever started to care about a profile field
 * would be a bug this file should fail on rather than accommodate.
 */
function makeUser(accountCreatedAt: string): UserView {
  return {
    id: "11111111-1111-4111-8111-111111111111",
    telegramUserId: 770000123,
    telegramUserIdMasked: "•••••123",
    uiLanguage: "uz_latn",
    isBlocked: false,
    accountCreatedAt,
    firstOrderAt: accountCreatedAt,
    lastOrderAt: accountCreatedAt,
    orderCount: 1,
    paidOrderCount: 0,
    isProfilePresent: false,
    telegramUsernameMasked: null,
    firstNameMasked: null,
    lastNameMasked: null,
    phoneMasked: null,
    phoneSharedAt: null,
    hasAvatar: false,
    avatarUrl: null,
    avatarFetchedAt: null,
    creditBalance: null,
    lifetimeCreditsGranted: null,
    allowancePeriod: null,
  };
}

describe("utcDayStart", () => {
  it("floors to UTC midnight, not local midnight", () => {
    expect(new Date(utcDayStart(ANCHOR)).toISOString()).toBe("2026-09-02T00:00:00.000Z");
  });
});

describe("newUserWindow", () => {
  it("spans thirty days inclusive of today", () => {
    const window = newUserWindow(ANCHOR);
    expect(window.days).toBe(NEW_USER_WINDOW_DAYS);
    expect(window.from).toBe("2026-08-04T00:00:00.000Z");
    // 30 buckets: the first starts 29 days before today's midnight.
    expect(utcDayStart(ANCHOR) - window.fromDayMs).toBe(29 * DAY_MS);
  });

  it("closes the window rather than leaving `to` open", () => {
    // Not because `/api/users` refuses a half window — it accepts one and closes the open
    // end itself — but because it would close it at a DIFFERENT instant per request, and a
    // series bucketed by day cannot have its last bucket move between pages.
    const window = newUserWindow(ANCHOR);
    expect(window.to).toBe("2026-09-02T13:45:00.000Z");
    expect(window.to.endsWith("Z")).toBe(true);
  });
});

describe("buildNewUserSeries", () => {
  it("zero-fills every day in the window", () => {
    const series = buildNewUserSeries([], newUserWindow(ANCHOR));
    expect(series).toHaveLength(NEW_USER_WINDOW_DAYS);
    expect(series.every((count) => count === 0)).toBe(true);
  });

  it("buckets by UTC day, oldest first", () => {
    const window = newUserWindow(ANCHOR);
    const series = buildNewUserSeries(
      [
        makeUser("2026-09-02T00:00:01Z"),
        makeUser("2026-09-02T23:59:59Z"),
        makeUser("2026-08-04T06:00:00Z"),
      ],
      window,
    );
    expect(series[0]).toBe(1);
    expect(series[NEW_USER_WINDOW_DAYS - 1]).toBe(2);
  });

  it("drops accounts outside the window instead of clamping them into an edge bucket", () => {
    const window = newUserWindow(ANCHOR);
    const series = buildNewUserSeries(
      [makeUser("2025-01-01T00:00:00Z"), makeUser("2027-01-01T00:00:00Z")],
      window,
    );
    expect(series.reduce((sum, count) => sum + count, 0)).toBe(0);
  });

  it("ignores an unparseable timestamp rather than producing NaN", () => {
    const series = buildNewUserSeries([makeUser("not a timestamp")], newUserWindow(ANCHOR));
    expect(series.every(Number.isFinite)).toBe(true);
  });
});
