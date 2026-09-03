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
    // `/api/users` 422s a half window, and a `to` that means "now" would widen the filter
    // between keyset pages.
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
