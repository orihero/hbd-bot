import { describe, expect, it } from "vitest";

import { makeOrder } from "@/components/domain/fixtures";

import {
  EMPTY_SUMMARY,
  ROLLING_WINDOW_MS,
  feedEventsFromOrders,
  feedSeverityOf,
  rollingWindow,
  summariseDays,
} from "./liveMetrics";

const NOON = Date.parse("2026-09-02T12:00:30.750Z");

describe("rollingWindow", () => {
  it("spans 24 hours and carries a Z on both ends", () => {
    const window = rollingWindow(NOON);
    expect(window.to).toBe("2026-09-02T12:00:00Z");
    expect(window.from).toBe("2026-09-01T12:00:00Z");
    expect(Date.parse(window.to) - Date.parse(window.from)).toBe(ROLLING_WINDOW_MS);
  });

  it("quantises, so a key built from it does not change between renders", () => {
    // Two moments 30 seconds apart inside the same minute must produce the same window, or
    // the query key changes on every render and the poll never settles.
    expect(rollingWindow(NOON)).toEqual(rollingWindow(NOON + 29_000));
    expect(rollingWindow(NOON).to).not.toBe(rollingWindow(NOON + 60_000).to);
  });

  it("never emits a naive instant — every windowed endpoint 422s on one", () => {
    const window = rollingWindow(NOON);
    expect(window.from).toMatch(/Z$/);
    expect(window.to).toMatch(/Z$/);
  });
});

describe("summariseDays", () => {
  const days = [
    { day: "2026-09-01", total: 10, delivered: 6, failed: 2, paid: 7 },
    { day: "2026-09-02", total: 5, delivered: 4, failed: 0, paid: 5 },
  ];

  it("sums the window and divides by delivered + failed", () => {
    const summary = summariseDays(days);
    expect(summary.orders).toBe(15);
    expect(summary.delivered).toBe(10);
    expect(summary.failed).toBe(2);
    expect(summary.paid).toBe(12);
    expect(summary.terminal).toBe(12);
    expect(summary.successRate).toBeCloseTo(10 / 12, 10);
  });

  it("does not divide by `total` — in-flight work is not a failure", () => {
    // 15 orders created, 12 terminal. Dividing by 15 would report 66% on a healthy morning.
    expect(summariseDays(days).successRate).not.toBeCloseTo(10 / 15, 3);
  });

  it("returns null, never 0, when nothing terminated", () => {
    const quiet = summariseDays([{ day: "2026-09-02", total: 3, delivered: 0, failed: 0, paid: 1 }]);
    expect(quiet.successRate).toBeNull();
    expect(quiet.terminal).toBe(0);
  });

  it("summarises an absent series as the empty summary", () => {
    expect(summariseDays([])).toEqual(EMPTY_SUMMARY);
  });
});

describe("feedEventsFromOrders", () => {
  it("keys on the update stamp, so a state change is a second entry", () => {
    const first = makeOrder({ state: "generating", updatedAt: "2026-09-02T11:00:00Z" });
    const second = { ...first, state: "failed" as const, updatedAt: "2026-09-02T11:05:00Z" };
    const [a, b] = feedEventsFromOrders([first, second]);
    expect(a?.id).not.toBe(b?.id);
  });

  it("carries the failure reason, which is our triage vocabulary", () => {
    const [event] = feedEventsFromOrders([
      makeOrder({ state: "failed", failedReason: "MUSIC_PROVIDER_TIMEOUT" }),
    ]);
    expect(event?.label).toBe("failed · MUSIC_PROVIDER_TIMEOUT");
    expect(event?.severity).toBe("error");
  });

  it("keeps the correlation id so a feed row leads to the logs", () => {
    const order = makeOrder({ state: "generating" });
    const [event] = feedEventsFromOrders([order]);
    expect(event?.correlationId).toBe(order.correlationId);
    expect(event?.orderId).toBe(order.id);
  });

  it("grades severity by consequence", () => {
    expect(feedSeverityOf("failed")).toBe("error");
    expect(feedSeverityOf("cancelled")).toBe("warn");
    expect(feedSeverityOf("generating")).toBe("info");
    expect(feedSeverityOf("delivered")).toBe("info");
  });
});
